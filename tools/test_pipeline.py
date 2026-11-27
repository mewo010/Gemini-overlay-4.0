"""Retry/fallback timing plus the real worker loop (mock HTTP, never a real key)."""
import copy, http.server, json, os, sys, tempfile, threading, time, types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if "sounddevice" not in sys.modules:
    try: import sounddevice  # noqa: F401
    except Exception:
        sd = types.ModuleType("sounddevice"); sd.InputStream = sd.RawOutputStream = sd.RawInputStream = object
        sys.modules["sounddevice"] = sd

from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from ai_overlay_lib import core, ai, chat
from ai_overlay_lib.ai import AIError, stream_chat
from ai_overlay_lib.accounts import Usage, Memory, Vault

fails, passed = [], [0]


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  :: " + str(detail)) if detail and not cond else ""))
    if cond: passed[0] += 1
    else: fails.append(name)


# ---------- mock HTTP/1.1 chunked SSE server ----------
class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    counts = {}
    lock = threading.Lock()

    def log_message(self, *a): pass

    def _json(self, code, obj, headers=None):
        data = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(data)

    def _sse_start(self):
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked"); self.end_headers()

    def _chunk(self, obj):
        data = ("data: " + json.dumps(obj) + "\n\n").encode()
        self.wfile.write(("%X\r\n" % len(data)).encode() + data + b"\r\n"); self.wfile.flush()

    def _end(self): self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); self.rfile.read(n)
        with self.lock: self.counts[self.path] = self.counts.get(self.path, 0) + 1; c = self.counts[self.path]
        text = {"candidates": [{"content": {"parts": [{"text": "hello"}]}, "finishReason": "STOP"}]}
        usage15 = {"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2, "totalTokenCount": 15}}
        usage25 = {"usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 5, "totalTokenCount": 25}}
        if self.path == "/ok":
            self._sse_start(); self._chunk(usage25); self._chunk(text); self._end()
        elif self.path == "/503":
            self._json(503, {"error": {"message": "high demand", "status": "UNAVAILABLE"}})
        elif self.path == "/flaky":
            if c < 3: self._json(503, {"error": {"message": "high demand", "status": "UNAVAILABLE"}})
            else: self._sse_start(); self._chunk(text); self._end()
        elif self.path == "/429":
            self._json(429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}}, {"Retry-After": "30"})
        elif self.path == "/401":
            self._json(401, {"error": {"message": "invalid key", "status": "UNAUTHENTICATED"}})
        elif self.path == "/empty":
            self._sse_start(); self._chunk(usage15); self._end()
        elif self.path == "/usage-empty":
            self._sse_start()
            if c == 1: self._chunk(usage15); self._end()
            else: self._chunk(usage25); self._chunk(text); self._end()
        elif self.path == "/partial":
            self._sse_start(); self._chunk({"candidates": [{"content": {"parts": [{"text": "partial answer"}]}}]})
            self.close_connection = True                      # interrupt without the terminating chunk
        elif self.path == "/slow":
            time.sleep(2.0); self._sse_start(); self._chunk(text); self._end()
        else:
            self._json(404, {"error": {"message": "no route"}})


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def prov(path, name="Mock", pid=None):
    return {"id": pid or ("id-" + path.strip("/")), "name": name, "enabled": True, "key": "k", "model": "m",
            "url": BASE + path, "extra": {}, "vision": True, "audio": True, "daily_limit": 0}


def run(path, **kw):
    p = prov(path); out = {}
    kw.setdefault("first_timeout", 1.0); kw.setdefault("idle_timeout", 1.0); kw.setdefault("total_timeout", 5.0)
    return p, stream_chat(p, {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 20}, usage_out=out, **kw), out


# ---------- stream-level behaviour ----------
p, text, u = run("/ok", max_attempts=1)
check("a successful stream returns the answer", text == "hello")
check("usage metadata is captured", u.get("prompt") == 20 and u.get("output") == 5 and u.get("total") == 25, u)

old_base, old_cap = ai.RETRY_BASE, ai.RETRY_CAP
ai.RETRY_BASE, ai.RETRY_CAP = 0.05, 30.0
try:
    retries = []
    p, text, _ = run("/flaky", max_attempts=3, on_retry=lambda m, d, a: retries.append((d, a)), pre_response_timeout=3.0)
    check("503 is retried and then succeeds", text == "hello" and len(retries) == 2, retries)
    check("503 retry callback reports the attempt number", [a for _d, a in retries] == [1, 2], retries)

    p = prov("/503")
    try:
        stream_chat(p, {"messages": [{"role": "user", "content": "hi"}]}, first_timeout=1, total_timeout=3,
                    max_attempts=2, pre_response_timeout=2)
        check("repeated 503 eventually raises", False)
    except AIError as ex:
        check("repeated 503 eventually raises a readable error", "high demand" in ex.message, ex.message)

    p = prov("/401"); reqs0 = Handler.counts.get("/401", 0)
    try:
        stream_chat(p, {"messages": [{"role": "user", "content": "hi"}]}, max_attempts=3, first_timeout=1,
                    total_timeout=3, pre_response_timeout=2)
        check("401 is not silently retried", False)
    except AIError as ex:
        check("401 is not retried", Handler.counts.get("/401", 0) - reqs0 == 1 and "invalid key" in ex.message, ex.message)

    t0 = time.time(); p = prov("/429"); reqs0 = Handler.counts.get("/429", 0)
    try:
        stream_chat(p, {"messages": [{"role": "user", "content": "hi"}]}, max_attempts=2, first_timeout=1,
                    total_timeout=5, pre_response_timeout=2)
        check("429 with a long Retry-After does not block", False)
    except AIError as ex:
        dt = time.time() - t0
        check("429 with Retry-After 30 fails fast when another provider may take over",
              dt < 1.2 and ("switching provider" in ex.message or "did not respond" in ex.message), (dt, ex.message))
        check("429 Retry-After is not slept through", Handler.counts.get("/429", 0) - reqs0 == 1, Handler.counts.get("/429", 0) - reqs0)

    t0 = time.time(); p = prov("/slow")
    try:
        stream_chat(p, {"messages": [{"role": "user", "content": "hi"}]}, max_attempts=2, first_timeout=0.5,
                    total_timeout=5, pre_response_timeout=0.8)
        check("a stalled provider is abandoned within the pre-response budget", False)
    except AIError as ex:
        dt = time.time() - t0
        check("a stalled provider is abandoned within the pre-response budget",
              dt < 2.0 and ("did not respond" in ex.message or "no time left" in ex.message), (dt, ex.message))

    p = prov("/partial"); deltas = []
    reqs0 = Handler.counts.get("/partial", 0)
    try:
        stream_chat(p, {"messages": [{"role": "user", "content": "hi"}]}, max_attempts=3, first_timeout=1,
                    total_timeout=5, on_delta=deltas.append)
        check("an interrupted stream is surfaced", False)
    except AIError as ex:
        check("an interrupted stream keeps partial text and is not replayed",
              ex.partial == "partial answer" and deltas and Handler.counts.get("/partial", 0) - reqs0 == 1, ex.message)

    p = prov("/usage-empty"); u = {}
    text = stream_chat(p, {"messages": [{"role": "user", "content": "hi"}]}, max_attempts=2, first_timeout=1,
                       total_timeout=5, usage_out=u)
    check("usage from each HTTP attempt is summed, not overwritten", text == "hello" and u.get("prompt") == 30 and u.get("total") == 40, u)
finally:
    ai.RETRY_BASE, ai.RETRY_CAP = old_base, old_cap


# ---------- actual worker loop: order, status, usage ----------
app = QApplication.instance() or QApplication([])


def overlay(providers):
    chat.USAGE_PATH = os.path.join(tempfile.mkdtemp(), "usage.json")      # isolate every worker case
    cfg = copy.deepcopy(core.DEFAULTS); cfg["providers"] = copy.deepcopy(providers); core.normalize_providers(cfg)
    ov = chat.Overlay(cfg, Memory(os.path.join(tempfile.mkdtemp(), "memory.json")), Vault(os.path.join(tempfile.mkdtemp(), "vault.bin")))
    ov.speaker.enabled = lambda: False
    return ov


def worker_case(providers, fake, rid=1):
    ov = overlay(providers); ov.req = rid
    got = {"notes": [], "served": [], "finished": [], "partial": [], "calls": []}
    ov.note.connect(got["notes"].append); ov.served.connect(lambda r, t: got["served"].append(t))
    ov.finished.connect(lambda r, ok: got["finished"].append((r, ok))); ov.partial.connect(lambda r, t: got["partial"].append(t))
    real = chat.stream_chat
    def wrapper(p, body, headers, **kw):
        got["calls"].append(p["name"]); return fake(p, body, headers, **kw)
    try:
        chat.stream_chat = wrapper
        ov.worker_run(rid, dict(text="hi", audio=None, img=None, kind="chat", screen=False, history=[], system="sys"), providers)
    finally:
        chat.stream_chat = real
    return ov, got


A = {"id": "cfg-a", "name": "Gemini A", "enabled": True, "key": "a", "model": "m", "url": BASE + "/ok", "vision": True, "audio": True}
B = {"id": "cfg-b", "name": "Gemini B", "enabled": True, "key": "b", "model": "m", "url": BASE + "/ok", "vision": True, "audio": True}

# first succeeds
def ok(p, body, headers, **kw):
    kw["on_open"]({}); kw["on_first"](); kw["on_delta"]("hello"); kw["usage_out"].update({"prompt": 11, "output": 2, "thoughts": 1, "total": 14}); return "hello"
ov, got = worker_case([A, B], ok)
check("worker uses the first configured provider", got["calls"] == ["Gemini A"], got["calls"])
check("worker reports provider position on success", got["served"] and "(1/2)" in got["served"][0], got["served"])
check("worker finishes successfully", got["finished"] == [(1, True)], got["finished"])
check("tokens go only to the provider that answered", ov.usage.d["cfg-a"]["tok"]["total"] == 14 and "cfg-b" not in ov.usage.d, ov.usage.d)

# 503 first, second succeeds
def fail_then_ok(p, body, headers, **kw):
    if p["name"] == "Gemini A":
        kw["on_open"]({}); raise AIError("503 high demand", status=503)
    kw["on_open"]({}); kw["on_first"](); kw["on_delta"]("from B"); kw["usage_out"].update({"prompt": 7, "total": 7}); return "from B"
ov, got = worker_case([A, B], fail_then_ok)
check("fallback follows the displayed order", got["calls"] == ["Gemini A", "Gemini B"], got["calls"])
check("status names the failing provider and the next one",
      any("Gemini A unavailable. Switching to Gemini B (provider 2/2)" in n for n in got["notes"]), got["notes"])
check("served line names the actual provider and position", got["served"] and "Gemini B (2/2)" in got["served"][0], got["served"])
check("the failed provider gets the error, not the answer tokens",
      ov.usage.d["cfg-a"].get("errors") == 1 and "tok" not in ov.usage.d["cfg-a"] and ov.usage.d["cfg-b"]["tok"]["total"] == 7, ov.usage.d)
check("only one answer is emitted", got["partial"] == ["from B"] and got["finished"] == [(1, True)], (got["partial"], got["finished"]))

# timeout and auth failures also fall through to the next provider
def timeout_then_ok(p, body, headers, **kw):
    if p["name"] == "Gemini A": raise AIError("no response in 20.0 s")
    kw["on_open"]({}); kw["on_first"](); kw["on_delta"]("from B"); return "from B"
ov, got = worker_case([A, B], timeout_then_ok)
check("a timed-out first provider falls through to the next",
      got["calls"] == ["Gemini A", "Gemini B"] and got["finished"] == [(1, True)], (got["calls"], got["finished"]))

def auth_then_ok(p, body, headers, **kw):
    if p["name"] == "Gemini A": raise AIError("invalid key", status=401)
    kw["on_open"]({}); kw["on_first"](); kw["on_delta"]("from B"); return "from B"
ov, got = worker_case([A, B], auth_then_ok)
check("an authentication error falls through without retrying A",
      got["calls"] == ["Gemini A", "Gemini B"] and ov.usage.d["cfg-a"]["errors"] == 1, (got["calls"], ov.usage.d))

# Groq at the top must be named, not Gemini
G = {"id": "cfg-g", "name": "Groq", "enabled": True, "key": "g", "model": "m", "url": BASE + "/ok", "vision": False, "audio": False}
ov, got = worker_case([G, A], ok)
check("Groq-first configuration is attempted first", got["calls"] == ["Groq"], got["calls"])
check("no Gemini status appears when Groq is selected",
      got["notes"] and "Connecting to Groq (provider 1/2)" in got["notes"][0] and not any("Gemini" in n for n in got["notes"]), got["notes"])

# retry attempt number is not confused with provider position
def retrying(p, body, headers, **kw):
    kw["on_retry"]("high demand", 1, 1); kw["on_open"]({}); kw["on_first"](); kw["on_delta"]("ok"); return "ok"
ov, got = worker_case([A, B], retrying)
check("retry text separates attempt number from provider position",
      any("retry 1/2 for provider 1/2" in n for n in got["notes"]), got["notes"])

# partial stream: no fallback, no duplicate
def partial(p, body, headers, **kw):
    kw["on_open"]({}); kw["on_first"](); kw["on_delta"]("partial answer")
    raise AIError("connection interrupted", partial="partial answer")
ov, got = worker_case([A, B], partial)
check("a started stream is never replayed on another provider", got["calls"] == ["Gemini A"], got["calls"])
check("partial text is shown with the failure", got["partial"] and "partial answer" in got["partial"][0], got["partial"])
check("partial failure still attributes the request to A", ov.usage.d["cfg-a"]["count"] == 1 and "cfg-b" not in ov.usage.d, ov.usage.d)

# empty answer falls through
def empty(p, body, headers, **kw):
    kw["on_open"]({})
    if p["name"] == "Gemini A": return ""
    kw["on_first"](); kw["on_delta"]("from B"); return "from B"
ov, got = worker_case([A, B], empty)
check("an empty provider answer falls through in order", got["calls"] == ["Gemini A", "Gemini B"] and got["partial"] == ["from B"], (got["calls"], got["partial"]))
check("empty response is counted as an error on A", ov.usage.d["cfg-a"]["errors"] == 1, ov.usage.d)

# all fail
def all_fail(p, body, headers, **kw): raise AIError("invalid key", status=401)
ov, got = worker_case([A, B], all_fail)
check("all providers are tried in order when all fail", got["calls"] == ["Gemini A", "Gemini B"], got["calls"])
check("all-failure message lists both providers in order",
      got["partial"] and got["partial"][0].index("Gemini A") < got["partial"][0].index("Gemini B"), got["partial"])
check("failed requests are counted per configuration",
      ov.usage.d["cfg-a"]["errors"] == 1 and ov.usage.d["cfg-b"]["errors"] == 1, ov.usage.d)

# daily quota flag stays on the exact config
Aq, Bq = dict(A, daily_limit=100), dict(B, daily_limit=100)
def quota_then_ok(p, body, headers, **kw):
    if p["name"] == "Gemini A": raise AIError("daily quota exceeded", status=429)
    kw["on_open"]({}); kw["on_first"](); kw["on_delta"]("from B"); return "from B"
ov, got = worker_case([Aq, Bq], quota_then_ok)
check("a daily-quota 429 marks only that configuration as exhausted",
      ov.usage.left(Aq)[1] == 0 and ov.usage.left(Bq)[1] != 0, (ov.usage.left(Aq), ov.usage.left(Bq)))

# new request invalidates the old worker
ov = overlay([A, B]); ov.req = 2
done = []
ov.finished.connect(lambda r, ok: done.append((r, ok)))
real = chat.stream_chat
def slow_stream(p, body, headers, **kw):
    time.sleep(0.3); kw["on_delta"]("stale"); return "stale"
try:
    chat.stream_chat = slow_stream
    t = threading.Thread(target=ov.worker_run, args=(1, dict(text="old", audio=None, img=None, kind="chat", screen=False, history=[], system="s"), [A, B]))
    t.start(); time.sleep(0.05); ov.req = 3; t.join(2)
finally:
    chat.stream_chat = real
check("an outdated request cannot deliver its answer", not done and not ov.usage.d.get("cfg-a", {}).get("count"), done)

# concurrent accounting
u = Usage(os.path.join(tempfile.mkdtemp(), "u.json")); ps = [A, B]
def hammer(p, n):
    for _ in range(n): u.rec(p); u.tokens(p, {"prompt": 1, "output": 1, "total": 2})
ths = [threading.Thread(target=hammer, args=((A if i % 2 == 0 else B), 40)) for i in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
check("concurrent requests keep per-config counts exact", u.left(A)[0] == 160 and u.left(B)[0] == 160, (u.left(A), u.left(B)))
check("concurrent token sums are not lost", u.d[A["id"]]["tok"]["total"] == 320 and u.d[B["id"]]["tok"]["total"] == 320)

# ---------- animation smoke (no appearance change) ----------
ov = overlay([A])
ov.open_overlay(listen=False, full=True); QTest.qWait(200)
ov.expand(); QTest.qWait(650)
check("chat expands to the final surface", (not ov._ghost) and ov._panel.isVisible())
ov.collapse(force=True); QTest.qWait(600)
check("chat folds back to the orb", ov._collapsed and ov.big.anim.isActive())
ov.close_overlay()

srv.shutdown()
print("\n%d PASS / %d FAIL" % (passed[0], len(fails)))
sys.exit(1 if fails else 0)
