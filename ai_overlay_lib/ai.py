"""The AI request pipeline: provider selection, bounded streaming and context trimming.

The old pipeline lived inside the overlay's worker method and had three reliability problems:
  * a response that sent keep-alives but no content could stream forever (only a 40 s socket read timeout),
  * a provider that ignored `stream: true` returned JSON that the SSE loop silently dropped (empty answer),
  * every token re-rendered the whole chat in the GUI thread, delaying the next read.

This module fixes the first two. The overlay fixes the third by coalescing repaints.
"""
import threading, time, json

from .core import SESSION, short_error, subst, ACT_RE, parse_actions

FIRST_TOKEN_TIMEOUT = 14.0     # no first token in this many seconds -> try the next provider
IDLE_TIMEOUT = 25.0            # a gap between tokens longer than this means the stream is dead
TOTAL_TIMEOUT = 150.0          # hard ceiling for one provider, so nothing waits forever
CONNECT_TIMEOUT = 6.0
HISTORY_ITEMS = 12             # turns kept per request
HISTORY_CHARS = 7000           # ... and a character budget, so a long chat cannot slow every request


class AIError(Exception):
    """A readable failure from one provider. `partial` holds any text already received."""

    def __init__(s, message, status=None, delay=0.0, partial=""):
        super().__init__(message)
        s.message, s.status, s.delay, s.partial = message, status, delay, partial


def trim_history(messages, max_items=HISTORY_ITEMS, max_chars=HISTORY_CHARS):
    """Keep the newest complete turns within a size budget and never start with an assistant message."""
    msgs = [m for m in (messages or []) if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    kept, used = [], 0
    for m in reversed(msgs):
        text = str(m.get("content") or "")
        if kept and (len(kept) >= max_items or used + len(text) > max_chars):
            break
        kept.append({"role": m["role"], "content": text})
        used += len(text)
    kept.reverse()
    while kept and kept[0]["role"] == "assistant":
        kept.pop(0)
    return kept


def _merge(messages):
    """Some providers reject two consecutive messages with the same role."""
    out = []
    for m in messages:
        if out and out[-1]["role"] == m["role"]:
            a, b = out[-1]["content"], m["content"]
            if isinstance(a, str) and isinstance(b, str): joined = a + "\n\n" + b
            elif isinstance(a, list) and isinstance(b, list): joined = a + b
            elif isinstance(a, list): joined = a + [{"type": "text", "text": b}]
            else: joined = [{"type": "text", "text": a}] + b
            out[-1] = {"role": m["role"], "content": joined}
        else:
            out.append(dict(m))
    return out


def build_body(cfg, provider, system, history, user_parts, stream=True):
    messages = [{"role": "system", "content": system}]
    messages += trim_history(history)
    messages.append({"role": "user", "content": user_parts})
    body = {"stream": bool(stream), "max_tokens": int(cfg.get("max_tokens", 600)),
            "messages": _merge(messages), "model": provider.get("model", "")}
    body.update(subst(provider.get("extra") or {}, cfg.get("effort", "low")))
    return body


def provider_chain(providers, cool=None, usage=None, now=None):
    """Usable providers, in the user's order, skipping those in a cooldown.

    Cooling providers are only used when every provider is cooling (so a single provider that hit a rate
    limit is still retried, but a healthy alternative is always preferred).
    """
    cool = cool or {}
    now = time.time() if now is None else now
    ready, cooling = [], []
    for p in providers or []:
        url = str(p.get("url") or "")
        if not (p.get("enabled", True) and url and p.get("model")): continue
        local = any(h in url for h in ("localhost", "127.0.0.1"))
        if not (p.get("key") or local): continue
        if (cool.get((url, p.get("model")), 0) > now):
            cooling.append(((cool[(url, p.get("model"))]), p)); continue
        ready.append(p)
    if usage is not None:
        try: ready.sort(key=lambda p: usage.left(p)[1] == 0)      # out-of-quota last, order otherwise kept
        except Exception: pass
    if ready: return ready
    cooling.sort(key=lambda x: x[0])
    return [p for _until, p in cooling]


def _text_of(content):
    if isinstance(content, str): return content
    if isinstance(content, list):
        return "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return ""


def _extract(j):
    """(answer delta, reasoning delta) from an OpenAI, OpenRouter or Gemini-shaped chunk."""
    if not isinstance(j, dict): return "", ""
    ch = j.get("choices")
    if isinstance(ch, list) and ch:
        c = ch[0] if isinstance(ch[0], dict) else {}
        d = c.get("delta") or c.get("message") or {}
        if isinstance(d, dict):
            return _text_of(d.get("content")), _text_of(d.get("reasoning_content") or d.get("reasoning"))
        return _text_of(c.get("text")), ""
    cands = j.get("candidates")
    if isinstance(cands, list) and cands:
        parts = ((cands[0] or {}).get("content") or {}).get("parts") or []
        return "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict)), ""
    return "", ""


def _body_text(r):
    try:
        j = r.json()
    except Exception:
        return ""
    text, _reason = _extract(j)
    if text: return text
    if isinstance(j, dict):                                    # some gateways wrap the message differently
        for key in ("text", "response", "output_text"):
            if isinstance(j.get(key), str): return j[key]
        err = j.get("error")
        if isinstance(err, dict): raise AIError(str(err.get("message") or err)[:200])
    return ""


def stream_chat(provider, body, headers=None, on_delta=None, on_first=None, on_reason=None,
                on_open=None, stop=None, cut_at=None, first_timeout=FIRST_TOKEN_TIMEOUT,
                idle_timeout=IDLE_TIMEOUT, total_timeout=TOTAL_TIMEOUT):
    """POST one request and consume the stream, calling on_delta(full_text) as content arrives.

    Returns the full answer. Raises AIError with a readable reason; the error keeps any partial text.
    `stop()` is polled between lines; `cut_at(text)` may return an index at which to stop early
    (used to execute an action block as soon as it is complete instead of waiting for the model).
    """
    url = provider.get("url", "")
    hdrs = {"Accept": "text/event-stream", "Content-Type": "application/json"}
    hdrs.update(headers or {})
    state = {"first": False, "aborted": None, "reasoning": False}
    box = {"r": None}
    text = []

    def close():
        r = box.get("r")
        for obj in (r, getattr(r, "raw", None)):
            try:
                if obj is not None: obj.close()
            except Exception:
                pass

    def abort(why):
        if why == "first" and state["first"]: return
        state["aborted"] = state["aborted"] or why
        close()

    t_first = threading.Timer(first_timeout, lambda: abort("first")); t_first.daemon = True
    t_total = threading.Timer(total_timeout, lambda: abort("total")); t_total.daemon = True
    t_first.start(); t_total.start()
    started = time.time()
    try:
        try:
            r = SESSION.post(url, json=body, stream=True, timeout=(CONNECT_TIMEOUT, idle_timeout), headers=hdrs)
        except Exception as ex:
            raise AIError(f"could not connect ({str(ex)[:110]})")
        box["r"] = r
        if r.status_code != 200:
            msg, delay = short_error(r)
            raise AIError(msg, status=r.status_code, delay=delay)
        if on_open: on_open(r.headers)
        ctype = str(r.headers.get("content-type") or "").lower()
        if "event-stream" not in ctype and "application/json" in ctype:
            answer = _body_text(r)                    # a provider that ignored stream: true
            if not answer: raise AIError("empty response")
            state["first"] = True; t_first.cancel()
            if on_first: on_first()
            if on_delta: on_delta(answer)
            return answer
        for raw in r.iter_lines(chunk_size=1):
            if stop is not None:
                try:
                    if stop(): raise AIError("cancelled")
                except AIError: raise
                except Exception: pass
            if not raw: continue
            line = raw.decode("utf-8", "replace").strip()
            if not line or line.startswith(":") or line.startswith("event:"): continue
            if line.startswith("data:"): data = line[5:].strip()
            elif line.startswith("{"): data = line
            else: continue
            if data in ("[DONE]", "DONE"): break
            try: j = json.loads(data)
            except ValueError: continue
            if isinstance(j, dict) and isinstance(j.get("error"), dict):
                raise AIError(str(j["error"].get("message") or j["error"])[:200])
            delta, reason = _extract(j)
            if reason:
                state["reasoning"] = True
                if on_reason: on_reason(reason)
            if not delta: continue
            if not state["first"]:
                state["first"] = True; t_first.cancel()
                if on_first: on_first()
            text.append(delta)
            full = "".join(text)
            if on_delta: on_delta(full)
            if cut_at is not None:
                end = cut_at(full)
                if end:
                    return full[:end]
            if time.time() - started > total_timeout:
                raise AIError("took too long", partial="".join(text))
        full = "".join(text)
        if not full:
            raise AIError("only reasoning was returned" if state["reasoning"] else "empty response")
        return full
    except AIError:
        raise
    except Exception as ex:
        full = "".join(text)
        why = state["aborted"]
        if why == "first": raise AIError(f"no response in {int(first_timeout)} s", partial=full)
        if why == "total": raise AIError(f"no complete answer after {int(total_timeout)} s", partial=full)
        if full: raise AIError(f"connection interrupted ({str(ex)[:110]})", partial=full)
        raise AIError(f"connection failed ({str(ex)[:110]})")
    finally:
        t_first.cancel(); t_total.cancel(); close()
