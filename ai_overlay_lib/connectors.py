"""Connected apps (Telegram, webhooks, Spotify) and the notification hub."""
from .core import *
from .system import *

# ---------- connections: apps that send notifications and accept replies ----------
from dataclasses import dataclass, field


@dataclass
class Notice:
    id: str; app_id: str; app: str; icon: str; title: str; body: str; ts: float
    can_reply: bool = False; meta: dict = field(default_factory=dict)


class ConfigError(Exception):
    """Something the user must fix (wrong token, port taken...): shown in plain words, no automatic retry."""


class Connector:
    """Base class. To add an app: subclass, set id/name/icon/FIELDS/STEPS, implement run() (loop until self.stop is set, call self.push(...)
    for each event) and reply(); then add it to CONNECTORS. Settings and the drawer pick it up automatically.
    Raise ConfigError for problems the user must fix; any other exception (network drop...) is retried automatically with a growing delay."""
    id = ""; name = ""; icon = "🔗"; blurb = ""; STEPS = ""; FIELDS = []; REQUIRED = []      # FIELDS: [(key, label, is_secret)]

    def __init__(s, hub, conf): s.hub, s.conf, s.stop, s.dead = hub, conf, threading.Event(), False

    def start(s): threading.Thread(target=s._guard, daemon=True).start()

    def _guard(s):
        delay = 3
        while not s.stop.is_set():
            try: s.run(); return
            except ConfigError as ex: s.dead = True; s.hub.set_status(s.id, str(ex), "error"); return
            except Exception as ex:
                if s.stop.is_set(): return
                s.hub.set_status(s.id, f"Connection lost ({str(ex)[:60]}). Retrying in {delay}s…", "warn")
                if s.stop.wait(delay): return
                delay = min(delay * 2, 60); s.hub.set_status(s.id, "Reconnecting…", "info")

    def halt(s): s.stop.set()

    def push(s, title, body, app=None, can_reply=False, meta=None):
        s.hub.notice.emit(Notice(uuid.uuid4().hex[:8], s.id, app or s.name, s.icon, str(title), str(body), time.time(), can_reply, meta or {}))

    def run(s): raise NotImplementedError
    def reply(s, n, text): raise NotImplementedError


class TelegramConnector(Connector):
    id, name, icon = "telegram", "Telegram", "✈️"
    blurb = "Messages sent to your bot show up here and you can answer from the overlay."
    STEPS = "1. In Telegram open @BotFather and send /newbot.   2. Copy the token it gives you.   3. Paste it below and press Connect."
    FIELDS = [("token", "Bot token", True)]; REQUIRED = ["token"]

    def run(s):
        tok = s.conf.get("token", "").strip()
        if not tok: raise ConfigError("Paste your bot token first.")
        s.base = f"https://api.telegram.org/bot{tok}"; off = 0
        r = SESSION.get(s.base + "/getMe", timeout=10)
        if r.status_code in (401, 404): raise ConfigError("Telegram didn't accept that token. Copy it again from @BotFather.")
        me = r.json()
        if not me.get("ok"): raise ConfigError("Telegram didn't accept that token. Copy it again from @BotFather.")
        s.hub.set_status(s.id, "Connected as @" + me["result"].get("username", "bot"), "ok")
        while not s.stop.is_set():
            r = SESSION.get(s.base + "/getUpdates", params={"timeout": 25, "offset": off}, timeout=35).json()
            if not r.get("ok"): s.stop.wait(3); continue
            for u in r.get("result", []):
                off = u["update_id"] + 1; m = u.get("message") or {}
                if m.get("text"): s.push(m.get("from", {}).get("first_name", "Someone"), m["text"], can_reply=True, meta={"chat": m["chat"]["id"]})

    def reply(s, n, text):
        SESSION.post(s.base + "/sendMessage", json={"chat_id": n.meta["chat"], "text": text}, timeout=10).raise_for_status()


class WebhookConnector(Connector):
    id, name, icon = "webhook", "Webhook (any app)", "🔌"
    blurb = "Lets any app, script or automation (Zapier, n8n, IFTTT...) send notifications here. Local only."
    STEPS = ("Press Connect, then have your tool POST JSON to http://127.0.0.1:8765/ like {\"title\":\"Hi\",\"body\":\"Hello\"}. "
             "Add \"reply_url\" if you want to answer from the overlay. The port and secret are optional.")
    FIELDS = [("port", "Port (default 8765)", False), ("secret", "Secret (optional, sent as X-Secret)", True)]

    def run(s):
        import http.server
        try: port = int(s.conf.get("port") or 8765)
        except ValueError: raise ConfigError("The port must be a number, for example 8765.")
        secret = s.conf.get("secret", ""); me = s

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(h):
                try:
                    if "json" not in h.headers.get("Content-Type", ""): h.send_response(415); h.end_headers(); return     # blocks cross-site form posts
                    if secret and h.headers.get("X-Secret", "") != secret: h.send_response(403); h.end_headers(); return
                    j = json.loads(h.rfile.read(min(int(h.headers.get("Content-Length", 0)), 20000)) or b"{}"); ru = str(j.get("reply_url") or "")
                    me.push(str(j.get("title") or "Notification")[:120], str(j.get("body") or "")[:1000], app=str(j.get("app") or "")[:40] or None,
                            can_reply=ru.startswith(("http://", "https://")), meta={"reply_url": ru, "ref": j.get("id")})
                    h.send_response(200); h.end_headers(); h.wfile.write(b"ok")
                except Exception: h.send_response(400); h.end_headers()
            def log_message(h, *a): pass
        try: srv = http.server.HTTPServer(("127.0.0.1", port), H)
        except OSError: raise ConfigError(f"Port {port} is already in use. Pick another port and press Connect again.")
        srv.timeout = 0.5; s.hub.set_status(s.id, f"Listening on 127.0.0.1:{port}", "ok")
        try:
            while not s.stop.is_set(): srv.handle_request()
        finally: srv.server_close()

    def reply(s, n, text): SESSION.post(n.meta["reply_url"], json={"reply": text, "id": n.meta.get("ref")}, timeout=10).raise_for_status()


class SpotifyConnector(Connector):
    id, name, icon = "spotify", "Spotify", "🎵"
    blurb = "Shows what is playing and lets you play a song by replying with its name."
    STEPS = ("1. Open developer.spotify.com/dashboard and create an app (redirect URI http://127.0.0.1:8888/callback).   "
             "2. Copy its Client ID.   3. Paste it below and press Connect; approve the login in your browser. (Playing music needs Premium.)")
    FIELDS = [("client_id", "Client ID", False)]; REQUIRED = ["client_id"]

    def _api(s): cfg = dict(s.hub.cfg); cfg["spotify_client_id"] = s.conf.get("client_id", ""); return SpotifyAPI(cfg)

    def run(s):
        api = s._api()
        if not api.enabled(): raise ConfigError("Paste your Spotify Client ID first.")
        s.hub.set_status(s.id, "Waiting for you to approve the login in your browser…", "info")
        try: api.access()
        except Exception as ex: raise ConfigError(f"Spotify login didn't finish ({str(ex)[:70]}). Press Connect to try again.")
        s.hub.set_status(s.id, "Connected", "ok"); last = None
        while not s.stop.is_set():
            r = api.call("GET", "/me/player/currently-playing")
            it = r.json().get("item") if r.status_code == 200 and r.text else None
            if it and it.get("id") != last:
                last = it["id"]; s.push("Now playing", f"{it['name']} - {it['artists'][0]['name']}", can_reply=True)
            s.stop.wait(6)

    def reply(s, n, text): s._api().play(re.sub(r"^play\s+", "", text, flags=re.I), "track", s.stop)


CONNECTORS = {c.id: c for c in (SpotifyConnector, TelegramConnector, WebhookConnector)}


class ConnectorHub(QObject):
    notice = pyqtSignal(object); status = pyqtSignal(str, str, str); replied = pyqtSignal(str, bool, str)

    def __init__(s, cfg): super().__init__(); s.cfg = cfg; s.live = {}; s.state = {}; s.level = {}

    def set_status(s, cid, text, level="info"): s.state[cid] = text; s.level[cid] = level; s.status.emit(cid, text, level)

    def wanted(s, cid): return bool(s.cfg.get("connections", {}).get(cid, {}).get("enabled"))

    def connected_count(s): return sum(1 for c in s.live if s.level.get(c) == "ok")

    def connect(s, cid, fields):
        """One click: validate, remember the details, save and start right away (no separate 'Save' step)."""
        cls = CONNECTORS[cid]; fields = {k: str(v).strip() for k, v in fields.items()}
        missing = [lbl for k, lbl, _ in cls.FIELDS if k in cls.REQUIRED and not fields.get(k)]
        if missing: s.set_status(cid, f"Fill in: {', '.join(missing)}", "error"); return False
        s.cfg.setdefault("connections", {})[cid] = {"enabled": True, **fields}
        try: save_cfg(s.cfg)
        except Exception as ex: s.set_status(cid, f"Couldn't save settings: {ex}", "error"); return False
        s.apply(); return True

    def disconnect(s, cid):
        c = s.cfg.setdefault("connections", {}).setdefault(cid, {}); c["enabled"] = False
        try: save_cfg(s.cfg)
        except Exception: pass
        s.apply()

    def apply(s):
        """Start/stop connectors to match the saved settings."""
        conns = s.cfg.get("connections", {})
        for cid, cls in CONNECTORS.items():
            c = conns.get(cid, {}); want = bool(c.get("enabled")); live = s.live.get(cid)
            if live and (not want or live.conf != c or live.dead): live.halt(); s.live.pop(cid); s.set_status(cid, "Not connected", "off")
            if want and cid not in s.live:
                s.live[cid] = cls(s, dict(c)); s.set_status(cid, "Connecting…", "info"); s.live[cid].start()
            if not want and cid not in s.state: s.set_status(cid, "Not connected", "off")

    def reply(s, n, text):
        def work():
            try:
                c = s.live.get(n.app_id)
                if not c: raise RuntimeError("that app is disconnected")
                c.reply(n, text); s.replied.emit(n.id, True, "")
            except Exception as ex: s.replied.emit(n.id, False, str(ex))
        threading.Thread(target=work, daemon=True).start()


class NoticeCard(QFrame):
    reply = pyqtSignal(object, str); dismiss = pyqtSignal(object)

    def __init__(s, n):
        super().__init__(); s.n = n; s.sent = ""; s.setObjectName("ncard")
        v = QVBoxLayout(s); v.setContentsMargins(12, 10, 12, 10); v.setSpacing(6)
        h = QHBoxLayout(); a = QLabel(f"{n.icon}  {n.app}"); a.setObjectName("napp")
        t = QLabel(time.strftime("%H:%M", time.localtime(n.ts))); t.setObjectName("ntime")
        x = QPushButton("✕"); x.setObjectName("nx"); x.setFixedSize(22, 22); x.clicked.connect(lambda: s.dismiss.emit(s.n))
        h.addWidget(a, 1); h.addWidget(t); h.addWidget(x); v.addLayout(h)
        if n.title: tl = QLabel(n.title); tl.setObjectName("ntitle"); tl.setWordWrap(True); v.addWidget(tl)
        if n.body:
            b = QLabel(n.body[:600]); b.setObjectName("nbody"); b.setWordWrap(True)
            b.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); v.addWidget(b)
        s.res = QLabel(""); s.res.setObjectName("nres"); s.res.setWordWrap(True); s.res.hide(); v.addWidget(s.res)
        if n.can_reply:
            r = QHBoxLayout(); s.ed = QLineEdit(); s.ed.setObjectName("nreply"); s.ed.setPlaceholderText("Reply…")
            s.go = QPushButton("↑"); s.go.setObjectName("nsend"); s.go.setFixedSize(28, 28)
            s.ed.returnPressed.connect(s.send); s.go.clicked.connect(s.send); r.addWidget(s.ed, 1); r.addWidget(s.go); v.addLayout(r)

    def send(s):
        t = s.ed.text().strip()
        if not t: return
        s.sent = t; s.ed.setEnabled(False); s.go.setEnabled(False)
        s.res.setStyleSheet(""); s.res.setText("Sending…"); s.res.show(); s.reply.emit(s.n, t)

    def set_result(s, ok, err=""):
        s.res.setStyleSheet("" if ok else "color:#ff9aa8")
        s.res.setText(("✓ Sent: " + s.sent[:60]) if ok else ("⚠ " + err[:100])); s.res.show(); s.ed.setEnabled(True); s.go.setEnabled(True)
        if ok: s.ed.clear()

# One flat namespace across the package (it was split out of a single file); exporting
# everything, including the private helpers, keeps the behaviour identical.
__all__ = [n for n in globals() if not n.startswith('__')]
