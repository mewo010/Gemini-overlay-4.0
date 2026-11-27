"""Usage limits, the encrypted vault and the interactive sign-in flow.

Nothing in this module is ever sent to a model: the vault reveals a login only to the local UI.
"""
from .core import *

class Usage:
    """Per-provider-CONFIGURATION counters that reset daily.

    The key is the configuration's stable id, never its name/model/key: duplicate Gemini entries stay independent.
    Groq also reports the real remaining quota in response headers; for other providers 'left' = the daily limit
    set on that configuration minus today's count.
    """
    def __init__(s, path):
        s.path = path; s.lock = threading.Lock()
        try: s.d = json.load(open(path, encoding="utf-8"))
        except Exception: s.d = {}

    @staticmethod
    def key(p):
        """The stable provider-configuration id, never the display name or model.

        Two Gemini entries can share a name, model and even a key; they are still different configurations and
        must never share counters. `normalize_providers` guarantees an id in normal use; the fallback keeps
        unidentified dicts separate instead of merging them under a name.
        """
        pid = str(p.get("id") or "").strip()
        return pid or "unidentified-" + str(id(p))

    @staticmethod
    def today(p):   # Gemini's daily quota resets at midnight Pacific (approximated as UTC-8); everything else: UTC
        off = -8 * 3600 if "generativelanguage" in p.get("url", "") else 0
        return time.strftime("%Y-%m-%d", time.gmtime(time.time() + off))

    def _e(s, p):
        k, day = s.key(p), s.today(p); e = s.d.get(k)
        if not e or e.get("day") != day:
            hist = list((e or {}).get("history") or [])
            if e and e.get("day"):                       # keep a compact, per-configuration history
                snap = {"day": e["day"], "count": int(e.get("count", 0))}
                if e.get("errors"): snap["errors"] = int(e["errors"])
                if e.get("tok"): snap["tok"] = dict(e["tok"])
                hist = (hist + [snap])[-30:]
            e = s.d[k] = {"day": day, "count": 0}
            if hist: e["history"] = hist
        return e

    def migrate(s, providers):
        """Move old name|model counters onto an id only when exactly one configuration matches.

        The old key was shared by duplicate Gemini entries, so a shared counter cannot be attributed to one of
        them. In that case it is deliberately left alone rather than copied to the wrong configuration.
        """
        with s.lock:
            changed = False
            for p in providers or []:
                pid = str(p.get("id") or "").strip(); legacy = f"{p.get('name')}|{p.get('model')}"
                if not pid or pid == legacy or legacy not in s.d or pid in s.d: continue
                matches = [q for q in providers if f"{q.get('name')}|{q.get('model')}" == legacy]
                if len(matches) == 1:
                    s.d[pid] = s.d.pop(legacy); changed = True
            if changed: s._save()

    def _save(s):
        try:
            tmp = s.path + ".tmp"; json.dump(s.d, open(tmp, "w", encoding="utf-8")); os.replace(tmp, s.path)
        except Exception: pass

    def rec(s, p, headers=None):
        with s.lock:
            e = s._e(p); e["count"] += 1; e.pop("exhausted", None)
            if "groq.com" in p.get("url", "") and headers is not None:
                for hk, ek in (("x-ratelimit-remaining-requests", "hdr_rem"), ("x-ratelimit-limit-requests", "hdr_lim")):
                    try: e[ek] = int(float(headers.get(hk)))
                    except (TypeError, ValueError): pass
            s._save()

    def err(s, p, message=""):
        """Count a failed request against the exact configuration that made it."""
        with s.lock:
            e = s._e(p); e["errors"] = int(e.get("errors", 0)) + 1
            if message: e["last_error"] = str(message)[:160]
            s._save()

    def tokens(s, p, usage):
        """Add the exact token counts reported by the provider (Gemini native reports them every chunk)."""
        if not usage or not any(int(usage.get(k, 0) or 0) for k in ("prompt", "output", "thoughts", "total")): return
        with s.lock:
            e = s._e(p); t = e.setdefault("tok", {"prompt": 0, "output": 0, "thoughts": 0, "total": 0})
            for k in t:
                try: t[k] += int(usage.get(k, 0) or 0)
                except (TypeError, ValueError): pass
            s._save()

    def limited(s, p, body):
        if re.search(r"per ?day|daily|\bRPD\b", body or "", re.I):
            with s.lock: s._e(p)["exhausted"] = True; s._save()

    def left(s, p):
        """(used today, remaining or None if unknown, limit or None)"""
        with s.lock:
            e = s._e(p); used = e["count"]; lim = int(p.get("daily_limit") or 0)
            if e.get("exhausted"): return used, 0, lim or e.get("hdr_lim")
            if "hdr_rem" in e: return used, e["hdr_rem"], e.get("hdr_lim")
            return used, (max(0, lim - used) if lim else None), (lim or None)

    def line(s, p):
        with s.lock:
            e = s._e(p); t = e.get("tok") or {}; errs = int(e.get("errors", 0))
        used, rem, lim = s.left(p)
        base = f"{used} used today" if rem is None else f"{used} used · {rem}" + (f"/{lim}" if lim else "") + " left today"
        if errs: base += f" · {errs} err"
        return base + (f" · {t.get('total', 0) / 1000:.1f}k tok" if t.get("total") else "")

    def served(s, p, failed, position=None, total=None):
        tag = f" ({position}/{total})" if position and total else ""
        t = f"{p['name']}{tag} · {p['model']} · {s.line(p)}"
        return t + (f"   (after {', '.join(failed)} failed)" if failed else "")

    def reset(s):
        with s.lock: s.d = {}; s._save()


# ---------- encrypted vault ----------
class VaultError(Exception): pass


class Vault:
    """scrypt-derived key + Fernet (AES + HMAC). The master password is never stored. After one unlock the derived key can be kept in memory
    for a few minutes (session) so logins don't need the password every time; it is wiped when the session ends or on Lock."""
    N, R, P = 2 ** 15, 8, 1

    def __init__(s, path):
        s.path = path; s.fails = 0; s.locked_until = 0.0; s.lock = threading.RLock()
        s.key = None; s.entries = None; s.until = 0.0; s.session_min = 5

    def exists(s): return os.path.exists(s.path)

    @staticmethod
    def _derive(pw, salt, n, r, p):
        return base64.urlsafe_b64encode(Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(pw.encode("utf-8")))

    def _read(s): return json.load(open(s.path, encoding="utf-8"))

    def _store(s, key, entries, salt, n, r, p):
        tok = Fernet(key).encrypt(json.dumps(entries).encode("utf-8"))
        doc = {"v": 1, "n": n, "r": r, "p": p, "salt": base64.b64encode(salt).decode(), "token": tok.decode()}
        tmp = s.path + ".tmp"
        with s.lock:
            json.dump(doc, open(tmp, "w", encoding="utf-8"))
            try: os.chmod(tmp, 0o600)
            except OSError: pass
            if os.path.exists(s.path):
                try: import shutil; shutil.copyfile(s.path, s.path + ".bak")      # one previous version, in case a write is interrupted
                except OSError: pass
            os.replace(tmp, s.path)

    def create(s, pw):
        salt = os.urandom(16); key = s._derive(pw, salt, s.N, s.R, s.P)
        s._store(key, {}, salt, s.N, s.R, s.P); return key

    def write(s, key, entries):
        d = s._read(); s._store(key, entries, base64.b64decode(d["salt"]), d["n"], d["r"], d["p"])
        if s.key is not None and s.entries is not None: s.entries = entries

    def rekey(s, entries, newpw):
        salt = os.urandom(16); key = s._derive(newpw, salt, s.N, s.R, s.P); s._store(key, entries, salt, s.N, s.R, s.P)
        if s.key is not None: s.key = key
        return key

    def unlock(s, pw):
        now = time.time()
        if now < s.locked_until: raise VaultError(f"Too many wrong attempts. Try again in {int(s.locked_until - now) + 1}s.")
        d = s._read()
        key = s._derive(pw, base64.b64decode(d["salt"]), d["n"], d["r"], d["p"])
        try: entries = json.loads(Fernet(key).decrypt(d["token"].encode()))
        except InvalidToken:
            s.fails += 1
            if s.fails >= 5: s.locked_until = now + 60; s.fails = 0
            raise VaultError("Wrong master password.")
        s.fails = 0
        return key, entries

    # --- session (keeps the unlocked vault in memory for a few minutes) ---
    def open_session(s, pw):
        key, entries = s.unlock(pw)
        if s.session_min > 0:
            with s.lock: s.key, s.entries, s.until = key, entries, time.time() + s.session_min * 60
        return key, entries

    def current(s):
        with s.lock:
            if s.key is not None and time.time() < s.until: return s.key, s.entries
            s.lock_now(); return None

    def lock_now(s):
        with s.lock: s.key = s.entries = None; s.until = 0.0

    def seconds_left(s): return max(0, int(s.until - time.time())) if s.key is not None else 0

    def note_login(s, name, ok):
        """Remember how the last login with an entry went (only possible while unlocked)."""
        cur = s.current()
        if not cur or name not in cur[1]: return
        cur[1][name]["last_result"] = "ok" if ok else "failed"; cur[1][name]["last_used"] = int(time.time())
        try: s.write(cur[0], cur[1])
        except Exception: pass


# ---------- website recognition ----------
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe"}
_SLD = {"co", "com", "org", "net", "gov", "edu", "ac"}


def site_key(s):
    """URL / domain -> registrable domain ('https://accounts.google.com/x' -> 'google.com'); plain names stay lowercase words."""
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", str(s or "").strip().lower())
    s = re.split(r"[/?#]", s)[0].split("@")[-1].split(":")[0]; s = re.sub(r"^www\.", "", s)
    p = [x for x in s.split(".") if x]
    if len(p) >= 3 and p[-2] in _SLD and len(p[-1]) == 2: return ".".join(p[-3:])
    return ".".join(p[-2:]) if len(p) >= 2 else s


def entry_sites(name, e):
    sites = [site_key(x) for x in re.split(r"[,\s;]+", str(e.get("site", ""))) if x]
    if not sites and "." in name: sites = [site_key(name)]
    return sites


def match_site(entries, site=None, label=None, url=None, title=None):
    """Saved logins that belong to a website, best first: [(name, score)]. Score 100 = same domain, 40 = page title mentions it."""
    sc = {}; title = re.sub(r"\s[-–—]\s(?:google chrome|microsoft.? edge|mozilla firefox|brave|opera|vivaldi)\b.*$", "", title or "", flags=re.I)

    def bump(n, v): sc[n] = max(sc.get(n, 0), v)
    for n, e in entries.items():
        sites = entry_sites(n, e); nl = n.lower()
        for q in (site, url):
            if not q: continue
            k = site_key(q)
            if k in sites: bump(n, 100)
            elif "." not in k and (any(x.split(".")[0] == k for x in sites) or k == nl): bump(n, 85)
            elif "." not in k and k and k in nl: bump(n, 55)
        if label:
            ll = label.lower().strip()
            if ll == nl: bump(n, 95)
            elif ll and (ll in nl or nl in ll): bump(n, 60)
        if title:
            tl = title.lower()
            if any(len(w) > 2 and w in tl for w in {nl} | {x.split(".")[0] for x in sites}): bump(n, 40)
    return sorted(sc.items(), key=lambda kv: -kv[1])


def mask_user(u):
    u = str(u or "")
    if "@" in u: a, b = u.split("@", 1); return (a[:2] + "•••" if len(a) > 2 else a[:1] + "•") + "@" + b
    return u[:2] + "•••" if len(u) > 3 else "•••"


# ---------- login automation ----------
@dataclass
class Field:
    kind: str; name: str = ""; empty: bool = True; ref: object = None      # kind: user | password


class LoginFlow:
    """Signs in through a page 'probe' (real browser via UI Automation, or a fake in tests). It handles redirects and multi-step
    (username -> Next -> password) pages, never types a password unless the focused element really is a password field, never retries
    wrong credentials, never automates 2-step codes or captchas, and reports what it actually observed instead of assuming success."""
    ERR = ("incorrect", "invalid", "wrong password", "wrong username", "doesn't match", "does not match", "try again", "couldn't find your", "not recognized",
           "unable to sign in", "unable to log in", "isn't right", "rejected")
    TWO_FA = ("verification code", "two-step", "2-step", "two-factor", "authenticator", "security code", "one-time", "enter the code", "passkey", "confirm it's you")
    CAPTCHA = ("captcha", "not a robot", "verify you are human", "are you human")
    LOGIN_URL = re.compile(r"log-?in|sign-?in|sign_in|/auth|accounts?\.|session|sso|oauth", re.I)

    def __init__(s, probe, stop_ev, sleep=time.sleep, now=time.time): s.p, s.stop, s.sleep, s.now = probe, stop_ev, sleep, now

    def _has(s, words):
        txt = " ".join(s.p.texts()).lower(); return any(w in txt for w in words)

    def _wait_fields(s, secs):
        end = s.now() + secs
        while s.now() < end and not s.stop.is_set():
            f = s.p.fields()
            if f: return f
            s.sleep(0.5)
        return []

    def _fill(s, field, text, secret=False):
        if not s.p.foreground_ok(): return False
        if not s.p.focus(field): return False
        if secret and not s.p.focused_is_password(): return False          # the password goes ONLY into a verified password field
        s.p.type(text); return True

    def _after_submit(s, before_url, before_title, had_pw=True):
        end = s.now() + 14
        while s.now() < end and not s.stop.is_set():
            s.sleep(0.6); f = s.p.fields(); has_pw = any(x.kind == "password" for x in f)
            if s._has(s.CAPTCHA) or s._has(s.TWO_FA): return "needs_user"
            if has_pw and s._has(s.ERR): return "failed_credentials"
            moved = (s.p.url() != before_url) or (s.p.title() != before_title)
            if not had_pw and has_pw and moved: return "next_step"                 # username page done, the password page appeared
            if not has_pw and f and moved: return "next_step"                    # username page done, a new field set appeared
            if not has_pw and not f and moved and not s.LOGIN_URL.search(s.p.url() or ""): return "success"
            if not has_pw and moved and not s.LOGIN_URL.search(s.p.url() or ""): return "success"
        return "unverified"

    def run(s, user, pw):
        f = s._wait_fields(8)
        if not f:
            return ("unverified", "no login fields found (the page may still be loading)") if s.LOGIN_URL.search(s.p.url() or "") else ("already", "")
        for _round in range(3):
            if s.stop.is_set(): return "aborted", "stopped"
            if s._has(s.CAPTCHA) or s._has(s.TWO_FA): return "needs_user", ""
            pwf = next((x for x in f if x.kind == "password"), None); usr = next((x for x in f if x.kind == "user"), None)
            if not pwf and not usr: return "unverified", "no usable login fields"
            url0, title0 = s.p.url(), s.p.title()
            if usr and (usr.empty or not pwf):
                if not s._fill(usr, user): return "abort", "couldn't focus the username field"
            if pwf:
                if not s._fill(pwf, pw, secret=True): return "abort", "couldn't safely focus the password field, so nothing was typed"
            s.p.press("enter"); s.sleep(0.3)
            v = s._after_submit(url0, title0, had_pw=bool(pwf))
            if v != "next_step": return v, ""
            f = s._wait_fields(8)
            if not f: return "unverified", ""
        return "unverified", ""


def login_message(status, site, extra=""):
    m = {"success": f"signed in to {site} (verified: the page moved past the login screen)",
         "already": f"already signed in to {site} (an active session was found, nothing was typed)",
         "failed_credentials": f"login failed: {site} rejected the saved username or password. I did not retry. Update the saved login in Settings > Data > Secure vault",
         "needs_user": f"needs you: {site} is asking for a verification code or captcha. Complete it yourself; I never automate that",
         "unverified": f"login unverified: the login was submitted to {site} but I couldn't confirm the result (check the screen)",
         "abort": f"login failed: {extra}", "aborted": "login stopped"}.get(status, f"login failed: {extra or status}")
    return m


def force_foreground_hwnd(hwnd):
    if sys.platform != "win32": return
    try:
        u = ctypes.windll.user32; cur = ctypes.windll.kernel32.GetCurrentThreadId(); fg = u.GetForegroundWindow(); tid = u.GetWindowThreadProcessId(fg, None) if fg else 0
        if u.IsIconic(hwnd): u.ShowWindow(hwnd, 9)
        if tid and tid != cur: u.AttachThreadInput(tid, cur, True)
        u.BringWindowToTop(hwnd); u.SetForegroundWindow(hwnd)
        if tid and tid != cur: u.AttachThreadInput(tid, cur, False)
    except Exception: pass


def find_browser():
    """(hwnd, title) of the frontmost browser window, or None."""
    if sys.platform != "win32": return None
    try:
        for h, title in _top_windows():
            if _win_exe(h) in BROWSERS: return h, title
    except Exception: pass
    return None


def foreground_is_foreign():
    """True when the focused window belongs to another program: we must never type a secret into our own overlay or chat box."""
    if sys.platform != "win32": return True
    try:
        from ctypes import wintypes
        h = ctypes.windll.user32.GetForegroundWindow(); pid = wintypes.DWORD(); ctypes.windll.user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        return bool(h) and pid.value != os.getpid()
    except Exception: return False


class UiaPage:
    """Reads and drives a browser page through Windows UI Automation (no mouse; focus is set on the real field)."""
    SEARCH = re.compile(r"search|address|url|find", re.I)

    def __init__(s, hwnd): s.hwnd = hwnd; s.win = uia.ControlFromHandle(hwnd); s._d = None

    def _doc(s):
        if s._d is None or not s._d.Exists(0.3, 0.1):
            try:
                d = s.win.DocumentControl(searchDepth=14); s._d = d if d.Exists(2.0, 0.3) else None
            except Exception: s._d = None
        return s._d

    def can_inspect(s): return s._doc() is not None
    def title(s):
        try: return s.win.Name or ""
        except Exception: return ""

    def url(s):
        try:
            for c, _d in uia.WalkControl(s.win, maxDepth=9):
                if c.ControlTypeName == "EditControl" and s.SEARCH.search((c.Name or "") + " " + (c.AutomationId or "")):
                    p = c.GetValuePattern()
                    if p and p.Value: return str(p.Value)
        except Exception: pass
        return ""

    def _walk(s, limit=1800):
        d = s._doc(); n = 0
        if d is None: return
        for c, _depth in uia.WalkControl(d, maxDepth=30):
            n += 1
            if n > limit: return
            yield c

    def fields(s):
        out = []
        try:
            for c in s._walk():
                if c.ControlTypeName != "EditControl" or c.IsOffscreen: continue
                nm = c.Name or ""
                try: pw = bool(c.IsPassword)
                except Exception: pw = False
                if not pw and s.SEARCH.search(nm): continue
                p = c.GetValuePattern()
                out.append(Field("password" if pw else "user", nm, not (p and p.Value), c))
        except Exception: pass
        return out

    def texts(s):
        try: return [(c.Name or "") for c in s._walk() if c.ControlTypeName == "TextControl" and c.Name][:300]
        except Exception: return []

    def focus(s, f):
        try: f.ref.SetFocus(); time.sleep(0.15); return True
        except Exception: return False

    def focused_is_password(s):
        try: c = uia.GetFocusedControl(); return bool(c and c.IsPassword)
        except Exception: return False

    def foreground_ok(s):
        if sys.platform != "win32": return False
        force_foreground_hwnd(s.hwnd); time.sleep(0.1)
        return ctypes.windll.user32.GetForegroundWindow() == s.hwnd

    def type(s, text): keyboard.write(text, delay=0.012)
    def press(s, key): keyboard.send(key)


@dataclass
class LoginPlan:
    name: str; site: str; url: str; user: str; secret: str; title: str = ""


def run_login(plan, stop_ev, note, ask_user, vault):
    """Worker-thread login. `note(text)` shows progress, `ask_user(text)` blocks for the user (GUI thread). Returns the result line for the model."""
    try:
        bw = find_browser(); dom = site_key(plan.url or plan.site)
        if bw is None or (plan.url and dom not in site_key(bw[1]) and dom.split(".")[0] not in bw[1].lower()):
            note(f"Opening {plan.site}…"); webbrowser.open(plan.url or ("https://" + plan.site)); end = time.time() + 12; bw = None
            while time.time() < end and not stop_ev.is_set():
                time.sleep(0.6); bw = find_browser()
                if bw and dom.split(".")[0] in bw[1].lower(): break
            if bw is None: return login_message("abort", plan.site, "no browser window appeared")
        hwnd = bw[0]; force_foreground_hwnd(hwnd); time.sleep(0.4)
        page = UiaPage(hwnd) if uia is not None else None
        if page is not None and page.can_inspect():
            note(f"Signing in to {plan.site}…")
            status, extra = LoginFlow(page, stop_ev).run(plan.user, plan.secret)
        else:                                          # no UI Automation: guided mode, the user points at each field; focus is still checked
            if not ask_user(f"I can't read this page automatically.\n\nClick the USERNAME field in your browser, then press OK. I'll type it 2 seconds later."):
                return "login cancelled by the user"
            time.sleep(2.0)
            if not foreground_is_foreign(): return login_message("abort", plan.site, "focus was on the assistant itself, so nothing was typed")
            keyboard.write(plan.user, delay=0.012); keyboard.send("tab"); time.sleep(0.2)
            if not ask_user("Now click the PASSWORD field (or just press OK if the cursor is already there). I'll type the password 2 seconds later."):
                return "login cancelled by the user"
            time.sleep(2.0)
            if not foreground_is_foreign(): return login_message("abort", plan.site, "focus was on the assistant itself, so nothing was typed")
            keyboard.write(plan.secret, delay=0.012); keyboard.send("enter")
            status, extra = "unverified", ""
        if status in ("success", "already"): vault.note_login(plan.name, True)
        elif status == "failed_credentials": vault.note_login(plan.name, False)
        return login_message(status, plan.site, extra)
    except Exception as ex:
        return "login failed: " + redact(str(ex), plan.secret)
    finally:
        plan.secret = ""


def redact(text, *secrets_):
    for sct in secrets_:
        if sct and len(sct) >= 3: text = text.replace(sct, "•••")
    return text


def match_label(entries, q):
    q = q.lower().strip()
    for k in entries:
        if k.lower() == q: return k
    c = [k for k in entries if q and (q in k.lower() or k.lower() in q)]
    return c[0] if len(c) == 1 else None


def ask_password(title, msg, confirm=False, min_len=1):
    while True:
        d = QInputDialog(); d.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        d.setWindowTitle(title); d.setLabelText(msg); d.setTextEchoMode(QLineEdit.EchoMode.Password)
        if not d.exec(): return None
        pw = d.textValue()
        if not pw: return None
        if not confirm: return pw
        if len(pw) < min_len:
            QMessageBox.warning(None, title, f"Use at least {min_len} characters."); continue
        d2 = QInputDialog(); d2.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        d2.setWindowTitle(title); d2.setLabelText("Repeat the password:"); d2.setTextEchoMode(QLineEdit.EchoMode.Password)
        if not d2.exec(): return None
        if d2.textValue() == pw: return pw
        QMessageBox.warning(None, title, "Passwords didn't match.")


# ---------- open / close apps ----------
WEB = {"google": "https://www.google.com", "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com",
       "google maps": "https://maps.google.com", "maps": "https://maps.google.com", "github": "https://github.com",
       "netflix": "https://www.netflix.com", "reddit": "https://www.reddit.com", "twitter": "https://x.com",
       "x": "https://x.com", "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
       "whatsapp web": "https://web.whatsapp.com", "wikipedia": "https://www.wikipedia.org",
       "google drive": "https://drive.google.com", "chatgpt": "https://chatgpt.com", "linkedin": "https://www.linkedin.com"}
APPS = {   # name: (launch command / URI, process image name or None = never kill)
    "spotify": ("spotify:", "Spotify.exe"), "chrome": ("chrome", "chrome.exe"), "google chrome": ("chrome", "chrome.exe"),
    "edge": ("msedge", "msedge.exe"), "microsoft edge": ("msedge", "msedge.exe"), "firefox": ("firefox", "firefox.exe"),
    "notepad": ("notepad", "notepad.exe"), "calculator": ("calc", "CalculatorApp.exe"), "paint": ("mspaint", "mspaint.exe"),
    "file explorer": ("explorer", None), "explorer": ("explorer", None), "task manager": ("taskmgr", "Taskmgr.exe"),
    "word": ("winword", "WINWORD.EXE"), "excel": ("excel", "EXCEL.EXE"), "powerpoint": ("powerpnt", "POWERPNT.EXE"),
    "outlook": ("outlook", "OUTLOOK.EXE"), "vscode": ("code", "Code.exe"), "visual studio code": ("code", "Code.exe"),
    "vs code": ("code", "Code.exe"), "teams": ("msteams:", "ms-teams.exe"), "slack": ("slack:", "slack.exe"),
    "steam": ("steam:", "steam.exe"), "zoom": ("zoommtg:", "Zoom.exe"), "discord": (None, "Discord.exe"),
    "telegram": ("tg:", "Telegram.exe"), "whatsapp": ("whatsapp:", "WhatsApp.exe"), "vlc": ("vlc", "vlc.exe"),
    "terminal": ("wt", "WindowsTerminal.exe"), "cmd": ("cmd", "cmd.exe"), "settings": ("ms-settings:", None),
}
EDITORS = {"winword.exe", "excel.exe", "powerpnt.exe", "notepad.exe", "code.exe"}   # never force-killed (unsaved work)


def _lookup(table, n):
    if n in table: return n
    for k in table:
        if n in k or k in n: return k
    return None


def _norm(name):
    n = name.lower().strip()
    return re.sub(r"^(the|my)\s+|\s+(app|application|website|site)$", "", n).strip()




def vault_unlock(vault, why):
    """GUI thread. Reuses an unlocked session, otherwise asks for the master password. -> (key, entries) or None."""
    cur = vault.current()
    if cur: return cur
    pw = ask_password("Secure vault", why + "\nEnter your master password to continue.\n(It is never sent to any AI.)")
    if not pw: return None
    try: return vault.open_session(pw)
    except VaultError as ex: QMessageBox.warning(None, "Vault", str(ex)); return None
    finally: pw = None


def secure_copy(secret, secs=20):
    """Clipboard copy that Windows clipboard history / cloud sync are told to ignore, cleared after a while."""
    cb = QGuiApplication.clipboard(); md = QMimeData(); md.setText(secret)
    try:
        md.setData("ExcludeClipboardContentFromMonitorProcessing", b"1")
        for fmt in ("CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"): md.setData(fmt, struct.pack("<I", 0))
    except Exception: pass
    cb.setMimeData(md); QTimer.singleShot(secs * 1000, lambda: cb.clear() if cb.text() == secret else None)

# One flat namespace across the package (it was split out of a single file); exporting
# everything, including the private helpers, keeps the behaviour identical.
__all__ = [n for n in globals() if not n.startswith('__')]
