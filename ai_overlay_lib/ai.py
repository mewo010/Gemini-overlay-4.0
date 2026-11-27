"""The AI request pipeline: provider selection, bounded streaming, retries and context compaction.

Reliability rules encoded here:
  * a request can never wait forever: connect, first-token, idle-gap and total deadlines are bounded,
  * temporary congestion (503 / 429 / 5xx / a timed-out connect) is retried with exponential backoff,
    jitter and the provider's own Retry-After/RetryInfo hint instead of failing immediately,
  * a stream that already produced text is never retried (that would duplicate the answer),
  * direct Google keys use Gemini's native SSE endpoint, which also reports exact token usage and lets us
    control the thinking budget; a rejected native request falls back to the OpenAI-compatible endpoint,
  * history is compacted (newest turns + a short digest of older ones) so prompts do not grow without bound.
"""
import json, random, threading, time

from .core import SESSION, short_error, subst

CONNECT_TIMEOUT = 8.0          # TCP/TLS connect
FIRST_TOKEN_TIMEOUT = 20.0     # no first byte/token -> retry (the old 25 s read timeout was fatal)
IDLE_TIMEOUT = 30.0            # a gap between tokens longer than this means the stream is dead
TOTAL_TIMEOUT = 95.0           # hard ceiling for ALL attempts of one request
MAX_ATTEMPTS = 3               # one try + two retries; avoids hammering a struggling endpoint
RETRY_BASE = 1.6               # 1.6 s, 3.2 s ... plus jitter
RETRY_CAP = 30.0               # never sleep longer than this (even if Retry-After asks for more)
HISTORY_ITEMS = 8              # recent messages sent verbatim (4 exchanges)
HISTORY_CHARS = 3600           # ... within this character budget
SUMMARY_CHARS = 360            # compressed digest of the turns that fall out of the window
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
NO_RETRY_STATUS = {400, 401, 403, 404, 405, 413, 422}
GEMINI_HOST = "generativelanguage.googleapis.com"


class AIError(Exception):
    """A readable failure from one provider. `partial` holds any text already received."""

    def __init__(s, message, status=None, delay=0.0, partial=""):
        super().__init__(message)
        s.message, s.status, s.delay, s.partial = message, status, delay, partial


# ---------- context ----------
def _digest(messages, limit=SUMMARY_CHARS):
    """A free, local summary of dropped turns: who said what, one clipped line each."""
    bits = []
    for m in messages:
        text = " ".join(str(m.get("content") or "").split())
        if not text: continue
        bits.append(("You: " if m.get("role") == "user" else "Me: ") + text[:64])
    out = " · ".join(bits)
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0].rstrip(" ,;·") + "…"
    return out


def trim_history(messages, max_items=HISTORY_ITEMS, max_chars=HISTORY_CHARS, summarize=True):
    """Newest complete turns within a budget, preceded by a compact digest of the older ones.

    The digest keeps names, decisions and unfinished tasks in context while costing a fraction of the
    tokens the dropped turns would have cost. Recent turns stay verbatim for coherent follow-ups.
    """
    msgs = [m for m in (messages or []) if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    kept, used = [], 0
    for m in reversed(msgs):
        text = str(m.get("content") or "")
        if kept and (len(kept) >= max_items or used + len(text) > max_chars):
            break
        kept.append({"role": m["role"], "content": text})
        used += len(text)
    kept.reverse()
    dropped = msgs[:len(msgs) - len(kept)]
    while kept and kept[0]["role"] == "assistant":
        dropped.append(kept.pop(0))
    out = []
    summary = _digest(dropped) if (summarize and dropped) else ""
    if summary: out.append({"role": "user", "content": "Earlier conversation (compressed): " + summary})
    out += kept
    return out


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


def build_body(cfg, provider, system, history, user_parts, stream=True, kind="chat", effort=None):
    """OpenAI-shaped body. `history` is already compacted by trim_history (never trim twice: the digest
    would be treated as a real turn and could be summarised again)."""
    messages = [{"role": "system", "content": system}]
    messages += history or []
    messages.append({"role": "user", "content": user_parts})
    body = {"stream": bool(stream), "max_tokens": int(cfg.get("max_tokens", 600)),
            "messages": _merge(messages), "model": provider.get("model", "")}
    if kind in ("explain", "summarize", "translate"):
        body["max_tokens"] = max(body["max_tokens"], 800)      # the board JSON needs a little more room
    body.update(subst(provider.get("extra") or {}, effort or cfg.get("effort", "low")))
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


# ---------- Gemini native wire format ----------
def gemini_model(provider):
    """The plain model id for a direct Google key, or None when this is a gateway/custom URL."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(str(provider.get("url") or "")).hostname or "").lower()
    except Exception:
        return None
    if host != GEMINI_HOST or not provider.get("key"):
        return None
    model = str(provider.get("model") or "").strip()
    model = model.split(":", 1)[0]                        # models/x:generateContent
    if model.startswith("models/"): model = model[7:]
    if "/" in model: model = model.rsplit("/", 1)[-1]      # google/gemini-...
    return model or None


def gemini_native_url(provider):
    model = gemini_model(provider)
    if not model: return None
    return f"https://{GEMINI_HOST}/v1beta/models/{model}:streamGenerateContent?alt=sse"


def _data_url(value):
    """'data:image/jpeg;base64,AAA' -> (mime, AAA)."""
    if not isinstance(value, str) or not value.startswith("data:"): return None, None
    head, _, data = value.partition(",")
    mime = head[5:].split(";", 1)[0] or "application/octet-stream"
    return mime, data


def _gemini_parts(content):
    """OpenAI content (string or typed parts) -> Gemini parts."""
    if isinstance(content, str):
        return [{"text": content}] if content else []
    out = []
    for p in content or []:
        if not isinstance(p, dict): continue
        kind = p.get("type")
        if kind == "image_url" or "image_url" in p:
            url = p.get("image_url") or {}
            url = url.get("url") if isinstance(url, dict) else url
            mime, data = _data_url(url)
            if data: out.append({"inlineData": {"mimeType": mime, "data": data}})
        elif kind == "input_audio" or "input_audio" in p:
            a = p.get("input_audio") or {}
            fmt = str(a.get("format") or "wav")
            if a.get("data"): out.append({"inlineData": {"mimeType": "audio/" + fmt, "data": a["data"]}})
        else:
            text = p.get("text")
            if text: out.append({"text": str(text)})
    return out


def gemini_thinking(model, effort):
    """Thinking control for the model generation.

    Gemini 3/4 use `thinkingLevel` (budget is deprecated there and can intermittently 400); Gemini 2.5
    Flash can disable thinking entirely, 2.5 Pro has a floor. This is the largest avoidable token cost
    for short voice replies: thinking tokens are billed as output tokens.
    """
    level = str(effort or "low").strip().upper()
    if level not in ("MINIMAL", "LOW", "MEDIUM", "HIGH"): level = "LOW"
    m = str(model or "").lower()
    if "gemini-4" in m or "gemini-3" in m:
        return {"thinkingLevel": level}
    if "2.5" in m:
        if "pro" in m:
            return {"thinkingBudget": {"MINIMAL": 128, "LOW": 1024, "MEDIUM": 8192, "HIGH": 24576}[level]}
        return {"thinkingBudget": {"MINIMAL": 0, "LOW": 0, "MEDIUM": 8192, "HIGH": 24576}[level]}
    return {}


def gemini_body(body, model, effort="low"):
    """Convert the OpenAI-shaped request we already build into Gemini's native format."""
    system, contents = [], []
    for m in body.get("messages") or []:
        if m.get("role") == "system":
            system.append(str(m.get("content") or ""))
            continue
        role = "model" if m.get("role") == "assistant" else "user"
        parts = _gemini_parts(m.get("content"))
        if not parts: continue
        if contents and contents[-1]["role"] == role: contents[-1]["parts"] += parts
        else: contents.append({"role": role, "parts": parts})
    gen = {"maxOutputTokens": int(body.get("max_tokens") or 600)}
    for src, dst in (("temperature", "temperature"), ("top_p", "topP"), ("topP", "topP"),
                     ("top_k", "topK"), ("topK", "topK"), ("seed", "seed")):
        if src in body and body[src] is not None: gen[dst] = body[src]
    stop = body.get("stop")
    if isinstance(stop, str): gen["stopSequences"] = [stop]
    elif isinstance(stop, list) and stop: gen["stopSequences"] = stop[:5]
    think = gemini_thinking(model, effort)
    if think: gen["thinkingConfig"] = think
    out = {"contents": contents or [{"role": "user", "parts": [{"text": ""}]}], "generationConfig": gen}
    if any(system): out["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    return out


# ---------- stream parsing ----------
def _text_of(content):
    if isinstance(content, str): return content
    if isinstance(content, list):
        return "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return ""


def _extract(j):
    """(answer delta, reasoning delta, finish reason) from OpenAI, OpenRouter or Gemini chunks."""
    if not isinstance(j, dict): return "", "", ""
    ch = j.get("choices")
    if isinstance(ch, list) and ch:
        c = ch[0] if isinstance(ch[0], dict) else {}
        d = c.get("delta") or c.get("message") or {}
        finish = str(c.get("finish_reason") or "")
        if isinstance(d, dict):
            return _text_of(d.get("content")), _text_of(d.get("reasoning_content") or d.get("reasoning")), finish
        return _text_of(c.get("text")), "", finish
    cands = j.get("candidates")
    if isinstance(cands, list) and cands:
        cand = cands[0] if isinstance(cands[0], dict) else {}
        parts = (cand.get("content") or {}).get("parts") or []
        answer, thought = [], []
        for p in parts:
            if not isinstance(p, dict): continue
            (thought if p.get("thought") else answer).append(str(p.get("text") or ""))
        return "".join(answer), "".join(thought), str(cand.get("finishReason") or "")
    return "", "", ""


def _capture_usage(j, out):
    """Exact token counts when the provider reports them (Gemini: every chunk; OpenAI: final)."""
    if out is None or not isinstance(j, dict): return
    u = j.get("usageMetadata") or j.get("usage")
    if not isinstance(u, dict): return
    pairs = (("prompt", ("promptTokenCount", "prompt_tokens")),
             ("output", ("candidatesTokenCount", "completion_tokens")),
             ("thoughts", ("thoughtsTokenCount",)),
             ("total", ("totalTokenCount", "total_tokens")))
    for dst, keys in pairs:
        for k in keys:
            try:
                if u.get(k) is not None: out[dst] = max(int(out.get(dst, 0)), int(u[k]))
            except (TypeError, ValueError): pass


def _blocked_reason(j):
    pf = j.get("promptFeedback") if isinstance(j, dict) else None
    if isinstance(pf, dict) and pf.get("blockReason"):
        return str(pf.get("blockReason")).lower().replace("_", " ")
    return ""


def _answer_from_obj(j):
    text, _reason, finish = _extract(j)
    if text: return text
    if isinstance(j, dict):
        for key in ("text", "response", "output_text"):
            if isinstance(j.get(key), str): return j[key]
        err = j.get("error")
        if isinstance(err, dict): raise AIError(str(err.get("message") or err)[:200])
        blocked = _blocked_reason(j)
        if blocked: raise AIError(f"the prompt was blocked ({blocked})", status=400)
        if finish: raise AIError(f"the model stopped ({finish.lower().replace('_', ' ')})")
    return ""


def _retryable(ex):
    if ex.status in NO_RETRY_STATUS: return False
    if ex.status in RETRY_STATUS: return True
    msg = str(ex.message or "").lower()
    return any(k in msg for k in ("high demand", "temporar", "unavailable", "overload", "try again",
                                  "timeout", "timed out", "could not connect", "connection", "no response",
                                  "empty response"))


def _retry_delay(ex, attempt):
    if ex.delay and ex.delay > 0: return min(RETRY_CAP, float(ex.delay))
    return min(RETRY_CAP, RETRY_BASE * (2 ** (attempt - 1))) + random.uniform(0, 0.4)


def _wait(seconds, stop):
    """Sleep in small slices so the stop button / a new request cancels immediately."""
    end = time.time() + max(0.0, seconds)
    while time.time() < end:
        if stop is not None:
            try:
                if stop(): return True
            except Exception: pass
        time.sleep(min(0.15, max(0.0, end - time.time())))
    return False


def _stream_once(url, hdrs, body, on_delta, on_first, on_reason, on_open, stop, cut_at,
                 first_timeout, idle_timeout, deadline, usage_out):
    state = {"first": False, "aborted": None, "reasoning": False, "finish": ""}
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

    left = max(0.5, deadline - time.time())
    t_first = threading.Timer(min(first_timeout, left), lambda: abort("first")); t_first.daemon = True
    t_total = threading.Timer(left, lambda: abort("total")); t_total.daemon = True
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
            try: j = r.json()
            except Exception: raise AIError("unreadable response")
            _capture_usage(j, usage_out)
            answer = _answer_from_obj(j)                  # a provider that ignored stream: true
            if not answer: raise AIError("empty response")
            state["first"] = True; t_first.cancel()
            if on_first: on_first()
            if on_delta: on_delta(answer)
            return answer
        for raw in r.iter_lines(chunk_size=64):           # small reads: a long chunk_size buffers the first tokens
            if stop is not None:
                try:
                    if stop(): raise AIError("cancelled")
                except AIError: raise
                except Exception: pass
            if state["aborted"]:
                raise AIError("no response in %d s" % int(first_timeout) if state["aborted"] == "first"
                              else "took too long", partial="".join(text))
            if not raw: continue
            line = raw.decode("utf-8", "replace").strip()
            if not line or line.startswith(":") or line.startswith("event:"): continue
            if line.startswith("data:"): data = line[5:].strip()
            elif line.startswith("{"): data = line
            else: continue
            if data in ("[DONE]", "DONE"): break
            try: j = json.loads(data)
            except ValueError: continue
            _capture_usage(j, usage_out)
            if isinstance(j, dict) and isinstance(j.get("error"), dict):
                err = j["error"]
                raise AIError(str(err.get("message") or err)[:200], status=err.get("code"))
            blocked = _blocked_reason(j)
            if blocked: raise AIError(f"the prompt was blocked ({blocked})", status=400)
            delta, reason, finish = _extract(j)
            if finish: state["finish"] = finish
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
            if time.time() > deadline:
                raise AIError("took too long", partial=full)
        full = "".join(text)
        if state["aborted"]:
            raise AIError("no response in %d s" % int(first_timeout) if state["aborted"] == "first"
                          else "took too long", partial=full)
        if not full:
            if state["finish"] and state["finish"].upper() in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"):
                raise AIError("the response was blocked by the safety filter")
            raise AIError("only reasoning was returned" if state["reasoning"] else "empty response")
        return full
    except AIError:
        raise
    except Exception as ex:
        full = "".join(text)
        why = state["aborted"]
        if why == "first": raise AIError(f"no response in {int(first_timeout)} s", partial=full)
        if why == "total": raise AIError(f"no complete answer after {int(time.time() - started)} s", partial=full)
        if full: raise AIError(f"connection interrupted ({str(ex)[:110]})", partial=full)
        raise AIError(f"connection failed ({str(ex)[:110]})")
    finally:
        t_first.cancel(); t_total.cancel(); close()


def stream_chat(provider, body, headers=None, on_delta=None, on_first=None, on_reason=None,
                on_open=None, stop=None, cut_at=None, usage_out=None, effort=None, on_retry=None,
                first_timeout=FIRST_TOKEN_TIMEOUT, idle_timeout=IDLE_TIMEOUT,
                total_timeout=TOTAL_TIMEOUT, max_attempts=MAX_ATTEMPTS):
    """POST one request and consume the stream, calling on_delta(full_text) as content arrives.

    Retries temporary congestion with exponential backoff + jitter, honouring Retry-After/RetryInfo.
    `on_retry(message, delay, attempt)` is called before each wait so the UI can say what is happening.
    Returns the full answer; raises AIError with a readable reason (and any partial text).
    """
    hdrs = {"Accept": "text/event-stream", "Content-Type": "application/json"}
    hdrs.update(headers or {})
    native_url = gemini_native_url(provider)
    url, payload_hdrs, payload = provider.get("url", ""), hdrs, body
    native = False
    if native_url:
        try:
            url = native_url
            payload = gemini_body(body, gemini_model(provider), effort or "low")
            payload_hdrs = {"Accept": "text/event-stream", "Content-Type": "application/json",
                            "x-goog-api-key": str(provider.get("key", "")).strip()}
            native = True
        except Exception:
            url, payload_hdrs, payload = provider.get("url", ""), hdrs, body
    compat = (provider.get("url", ""), hdrs, body)
    deadline = time.time() + total_timeout
    last = None
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        try:
            return _stream_once(url, payload_hdrs, payload, on_delta, on_first, on_reason, on_open, stop,
                                cut_at, first_timeout, idle_timeout, deadline, usage_out)
        except AIError as ex:
            last = ex
            if ex.partial: raise                                  # never replay text the user already saw
            if native and ex.status in (400, 404, 405, 415):
                native = False                                    # unexpected native rejection: use the compat URL
                url, payload_hdrs, payload = compat
                if on_retry: on_retry("native endpoint refused this model, using the compatible endpoint", 0, attempt)
                continue
            if not _retryable(ex) or attempt >= max_attempts:
                if attempt > 1: raise AIError(f"{ex.message} (after {attempt} attempts)", ex.status, ex.delay)
                raise
            delay = _retry_delay(ex, attempt)
            if time.time() + delay >= deadline:
                raise AIError(f"{ex.message} (no time left to retry)", ex.status, ex.delay)
            if on_retry: on_retry(ex.message, delay, attempt)
            if _wait(delay, stop): raise AIError("cancelled")
    raise last or AIError("empty response")
