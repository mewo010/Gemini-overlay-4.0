"""Windows automation: apps, windows, monitors, Spotify/YouTube, jobs, screenshots and transcription."""
from .core import *
from .accounts import *

def open_app(name):
    """Launch an app / site. The text returned is only 'launched'; whether it really came up is verified by wait_all()."""
    n = _norm(name)
    if not n: return "open_app: no name given"
    if re.match(r"https?://", n): webbrowser.open(n); return f"opened {n}"
    k = n if n in APPS else (n if n in WEB else (_lookup(APPS, n) or _lookup(WEB, n)))
    try:
        if k in APPS and APPS[k][0]:
            os.startfile(APPS[k][0]); return f"launched {k}"
    except Exception:
        if k == "spotify": webbrowser.open("https://open.spotify.com"); return "Spotify app not found, opened the web player"
    if k in WEB: webbrowser.open(WEB[k]); return f"opened {k}"
    target = k or n

    def via_start_menu():                       # works for any installed app (Discord, games, ...); never types over the user
        if not wait_user_idle(threading.Event(), 600, 8.0): return
        keyboard.send("windows"); time.sleep(0.6); keyboard.write(target, delay=0.01); time.sleep(0.9); keyboard.send("enter")
    threading.Thread(target=via_start_menu, daemon=True).start()
    return f"launched {target} through the Start menu"


def _running(proc):
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {proc}", "/NH"], capture_output=True, text=True,
                             creationflags=NO_WINDOW).stdout
        return proc.lower() in out.lower()
    except Exception:
        return False


def close_app(name, stop_ev=None):
    """Close an app and VERIFY it is gone (runs in a worker thread). Returns the real outcome."""
    n = _norm(name); k = n if n in APPS else _lookup(APPS, n)
    proc = APPS[k][1] if k in APPS else (n.replace(" ", "") + ".exe")
    if k in APPS and not proc: return f"close_app: I won't close {n} (system component)"
    if not _running(proc): return f"{n} isn't running, so there is nothing to close" if k in APPS else f"close_app failed: no running program called {n} (tell me its exact name)"

    def gone(secs):
        end = time.time() + secs
        while time.time() < end:
            if not _running(proc): return True
            time.sleep(0.3)
        return not _running(proc)
    try:
        subprocess.run(["taskkill", "/IM", proc], capture_output=True, creationflags=NO_WINDOW)      # polite close request
        if gone(2.0): return f"closed {n} (verified)"
        if proc.lower() in EDITORS: return f"{n} is still open (it may be asking to save your work)"
        subprocess.run(["taskkill", "/IM", proc, "/F"], capture_output=True, creationflags=NO_WINDOW)
        return f"closed {n} (forced, verified)" if gone(1.5) else f"couldn't close {n}: it is still running (it may be running as administrator)"
    except Exception as ex:
        return f"close_app failed ({ex})"


# ---------- screen helpers ----------
def resolve_screen(cfg):
    """Target monitor from settings: 'cursor' (follow mouse), 'primary', or 'name:<QScreen.name()>' (falls back to cursor)."""
    d = str(cfg.get("display", "cursor"))
    if d == "primary": return QGuiApplication.primaryScreen()
    if d.startswith("name:"):
        for sc in QGuiApplication.screens():
            if sc.name() == d[5:]: return sc
    return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()


def screen_label(i, sc):
    g = sc.geometry(); d = sc.devicePixelRatio()
    return f"Monitor {i + 1} - {int(g.width() * d)}x{int(g.height() * d)}" + (" (primary)" if sc is QGuiApplication.primaryScreen() else "")


def place_on(w, sc):
    """Bind a widget to a screen BEFORE moving it, so Qt applies that screen's DPI scaling (mixed-DPI setups)."""
    try:
        w.winId(); h = w.windowHandle()
        if h is not None and h.screen() is not sc: h.setScreen(sc)
    except Exception: pass


def phys_rect(sc, work=False):
    """(x, y, w, h) of a monitor in PHYSICAL pixels - the coordinate space pyautogui / SetCursorPos use."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            u32 = ctypes.windll.user32; found = []

            class MI(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                            ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]
            Proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

            def cb(hm, hdc, rc, lp):
                mi = MI(); mi.cbSize = ctypes.sizeof(MI)
                if u32.GetMonitorInfoW(hm, ctypes.byref(mi)): found.append((mi.szDevice, mi.rcWork if work else mi.rcMonitor))
                return 1
            u32.EnumDisplayMonitors(None, None, Proc(cb), 0)
            for dev, r in found:
                if dev == sc.name(): return r.left, r.top, r.right - r.left, r.bottom - r.top
        except Exception: pass
    g = sc.availableGeometry() if work else sc.geometry(); d = sc.devicePixelRatio()
    return int(g.x() * d), int(g.y() * d), int(g.width() * d), int(g.height() * d)


# ---------- multi-monitor awareness / window moving ----------
def ordered_screens():
    """Primary first, then the others left-to-right (physical pixels)."""
    pri = QGuiApplication.primaryScreen()
    others = sorted((s for s in QGuiApplication.screens() if s is not pri), key=lambda s: phys_rect(s)[:2])
    return [pri] + others


def role_of(sc):
    scs = ordered_screens()
    if sc is None or sc not in scs: return "unknown monitor"
    i = scs.index(sc)
    return "Primary" if i == 0 else (f"Secondary {i}" if len(scs) > 2 else "Secondary")


def monitor_text(current=None):
    lines = []
    for sc in ordered_screens():
        x, y, w, h = phys_rect(sc)
        lines.append(f"- {role_of(sc)}: {w}x{h} px at ({x},{y})" + ("  <- the attached screenshot shows THIS monitor" if sc is current else ""))
    return "\n".join(lines)


def screen_at_phys(x, y):
    for sc in ordered_screens():
        l, t, w, h = phys_rect(sc)
        if l <= x < l + w and t <= y < t + h: return sc
    return None


def pick_screen(target):
    scs = ordered_screens(); t = str(target or "").lower().strip()
    if t in ("primary", "main", "first", "1"): return scs[0]
    m = re.search(r"(\d+)", t)
    if t.startswith("secondary") or t in ("other", "second", "next", "external"):
        i = int(m.group(1)) if m else 1
        return scs[i] if 0 < i < len(scs) else None
    if m and 0 < int(m.group(1)) <= len(scs): return scs[int(m.group(1)) - 1]
    byx = sorted(scs, key=lambda s: phys_rect(s)[0])
    if t == "left": return byx[0]
    if t == "right": return byx[-1]
    return None


def _top_windows():
    """Visible titled top-level windows in z-order (frontmost first), excluding this process."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32; out = []; me = os.getpid()
    Proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(h, lp):
        try:
            if not u.IsWindowVisible(h) or (u.GetWindowLongW(h, -20) & 0x80): return True      # hidden / tool window
            n = u.GetWindowTextLengthW(h)
            if n <= 0: return True
            buf = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, buf, n + 1)
            pid = wintypes.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value != me and buf.value not in ("Program Manager", "Settings"): out.append((h, buf.value))
        except Exception: pass
        return True
    u.EnumWindows(Proc(cb), 0)
    return out


def move_window(target="secondary", title=""):
    """Move a window to another monitor and VERIFY where it really ended up."""
    if sys.platform != "win32": return "move_window: Windows only"
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    if len(ordered_screens()) < 2: return "NOT moved: only one monitor is connected"
    dest = pick_screen(target)
    if dest is None: return f"NOT moved: unknown monitor '{target}'. Monitors:\n" + monitor_text()
    t = str(title or "").lower().strip()
    hit = next(((h, ti) for h, ti in _top_windows() if not t or t in ti.lower()), None)
    if not hit: return f"NOT moved: no visible window matches '{title}'" if t else "NOT moved: no window found"
    h, ti = hit; r = wintypes.RECT()
    zoomed = bool(u.IsZoomed(h))
    if zoomed or u.IsIconic(h): u.ShowWindow(h, 9)                          # restore, so it can be placed
    u.GetWindowRect(h, ctypes.byref(r)); w, hh = r.right - r.left, r.bottom - r.top
    dx, dy, dw, dh = phys_rect(dest, work=True); w, hh = min(w, dw), min(hh, dh)
    u.SetWindowPos(h, 0, dx + (dw - w) // 2, dy + (dh - hh) // 2, w, hh, 0x0014)   # NOZORDER | NOACTIVATE
    if zoomed: u.ShowWindow(h, 3)                                           # re-maximize on the new monitor
    time.sleep(0.25)
    u.GetWindowRect(h, ctypes.byref(r)); on = screen_at_phys((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    if on is dest: return f"moved “{ti[:40]}” to {role_of(dest)} (verified)"
    return f"NOT moved: “{ti[:40]}” is still on {role_of(on)} (it may be running as admin or refuses to move)"


# ---------- launch readiness ("Light" + stable) ----------
_RECENT_OPEN = {}


def launch_proc(name):
    n = _norm(name); k = n if n in APPS else _lookup(APPS, n)
    if k in APPS and APPS[k][1]: return (APPS[k][1], k)
    if re.match(r"https?://", n) or n in WEB or _lookup(WEB, n): return ("", "browser")
    return ("", "start:" + (k or n))


def _window_ready(proc):
    """True when the process has a titled window and Windows does not flag it 'Not Responding'."""
    try:
        out = subprocess.run(["tasklist", "/V", "/FI", f"IMAGENAME eq {proc}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, creationflags=NO_WINDOW).stdout
        for r in csv.reader(io.StringIO(out)):
            if len(r) >= 9 and r[0].lower() == proc.lower() and r[5].lower() != "not responding" and r[8] not in ("N/A", ""): return True
    except Exception: pass
    return False


def _window_named(name):
    """Is there a visible window whose title or program name contains `name`? (verifies Start-menu launches)"""
    n = name.lower().replace(" ", "")
    try:
        for h, title in _top_windows():
            if n in title.lower().replace(" ", "") or n in _win_exe(h).replace(".exe", ""): return True
    except Exception: pass
    return False


def _wait_one(proc, kind, stop_ev, timeout):
    end = time.time() + timeout; ok = True
    if proc:
        ok = False
        while time.time() < end and not stop_ev.is_set():
            if _window_ready(proc): ok = True; break
            time.sleep(0.35)
        if ok: time.sleep(0.5)
        return f"{kind} is loaded and ready" if ok else f"{kind} is still loading after {int(timeout)}s - wait, do not repeat the command"
    if kind.startswith("start:"):
        name = kind[6:]; ok = False
        while time.time() < end and not stop_ev.is_set():
            if _window_named(name): ok = True; break
            time.sleep(0.5)
        return f"“{name}” is open (verified)" if ok else f"couldn't confirm “{name}” opened after {int(timeout)}s: it may not be installed or the name is different"
    time.sleep(1.2)
    return "opened in your browser (page load not checked)"


def wait_all(procs, stop_ev, timeout=12.0):
    """Blocking (run in a thread): wait for ALL launched apps in parallel until each is loaded and responsive."""
    if not procs: return []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(len(procs)) as ex:
        return list(ex.map(lambda pk: _wait_one(pk[0], pk[1], stop_ev, timeout), procs))


# ---------- Spotify / media keys (car-infotainment style) ----------
MEDIA_KEYS = {"play": "play/pause media", "pause": "play/pause media", "toggle": "play/pause media", "resume": "play/pause media",
              "next": "next track", "skip": "next track", "previous": "previous track", "prev": "previous track", "back": "previous track",
              "restart": "previous track", "volume_up": "volume up", "volume_down": "volume down", "mute": "volume mute", "unmute": "volume mute"}
_FAST = [
    (r"(?:pause|stop)(?: the)?(?: (?:music|song|track|spotify|playback))|pause", "pause"),
    (r"(?:resume|unpause|continue)(?: the)?(?: (?:music|song|track|spotify|playback))?|play(?: the)? (?:music|spotify)", "play"),
    (r"(?:skip|next)(?: (?:the|this))?(?: (?:song|track))?", "next"),
    (r"go back|previous|prev|last (?:song|track)|back a (?:song|track)|previous (?:song|track)", "previous"),
    (r"restart(?: (?:the|this))?(?: (?:song|track))?", "restart"),
    (r"volume up|louder|turn (?:it|the volume) up", "volume_up"),
    (r"volume down|quieter|softer|turn (?:it|the volume) down", "volume_down"),
    (r"mute|unmute", "mute"),
]


def fast_media(text):
    """Pure transport commands skip the model entirely so they run instantly."""
    t = re.sub(r"[.!?,]+$", "", re.sub(r"^(?:hey |ok |okay )?(?:please |can you |could you )?", "", str(text).lower().strip())).strip()
    t = re.sub(r" (?:please|now)$", "", t)
    for pat, cmd in _FAST:
        if re.fullmatch(pat, t): return {"do": "spotify", "cmd": cmd}
    m = re.fullmatch(r"(?:play|put on|start)\s+(.+?)\s+(?:on|in|using|with)\s+(spotify|youtube)", t)
    if m: return {"do": m.group(2), "query": m.group(1).strip()}
    m = re.fullmatch(r"(spotify|youtube)\s+play\s+(.+)", t)
    if m: return {"do": m.group(1), "query": m.group(2).strip()}
    return None


_OPEN_RE = re.compile(r"(?:open|launch|start|run)(?: up)?(?: the)? (.+?)(?: (?:app|application|website|site|page))?(?: for me)?(?: please| now)?")
_CLOSE_RE = re.compile(r"(?:close|quit|exit)(?: the)? (.+?)(?: (?:app|application|window))?(?: for me)?(?: please| now)?")
_URL_RE = re.compile(r"(?:https?://)?(?:[\w-]+\.)+(?:com|org|net|io|co|dev|app|ai|gov|edu|me|tv|us|uk|de|fr|il)(?:/\S*)?")


def fast_intent(text):
    """'open chrome' / 'close notepad' / 'open github.com' for names we know exactly: no model round trip, so it is instant."""
    t = re.sub(r"[.!?,]+$", "", re.sub(r"^(?:(?:hey|ok|okay)[, ]+)?(?:(?:please|can you|could you|would you)[, ]+)*", "", str(text).lower().strip())).strip()
    m = _OPEN_RE.fullmatch(t)
    if m:
        n = _norm(m.group(1))
        if _URL_RE.fullmatch(n): return {"do": "open_app", "name": n if n.startswith("http") else "https://" + n}
        if n in APPS or n in WEB: return {"do": "open_app", "name": n}
    m = _CLOSE_RE.fullmatch(t)
    if m and _norm(m.group(1)) in APPS: return {"do": "close_app", "name": _norm(m.group(1))}
    return None


def spotify_info():
    """(state, title): True = playing, False = paused/idle, None = unknown. Free detection from Spotify's window title:
    it is just 'Spotify Free/Premium' when idle and 'Artist - Song' while something plays."""
    if sys.platform != "win32": return None, ""
    try:
        for h, title in _top_windows():
            if _win_exe(h) != "spotify.exe": continue
            t = title.strip()
            if t.lower().startswith(("gdi+", "chrome legacy", "default ime", "msctfime", "spotify widget")): continue
            return (t.lower() not in ("", "spotify", "spotify free", "spotify premium")), t
    except Exception: pass
    return None, ""


def spotify_state(): return spotify_info()[0]


def _wait_state(want, secs, stop_ev):
    end = time.time() + secs
    while time.time() < end and not (stop_ev and stop_ev.is_set()):
        if spotify_state() is want: return True
        time.sleep(0.2)
    return spotify_state() is want


def spotify_ensure_playing(stop_ev=None):
    """Make sure music is REALLY playing: give the click time to register, press Play only if still paused, then verify."""
    if _wait_state(True, 1.6, stop_ev): return f"spotify: playing '{spotify_info()[1][:60]}' (verified)"
    if spotify_state() is None: return "spotify: can't read Spotify's state (window hidden?); look at the screen and click Play if it is paused"
    for _ in range(2):
        try: keyboard.send("play/pause media")
        except Exception as ex: return f"spotify play: failed ({ex})"
        if _wait_state(True, 1.8, stop_ev): return f"spotify: playing '{spotify_info()[1][:60]}' (started with the Play key; check it is the song that was asked for)"
    return "spotify: still paused after pressing Play twice; click the green Play button on the screen"


def spotify_do(a, screen_on=False, stop_ev=None):
    """Returns (result message, launched (proc, kind) or None)."""
    cmd = str(a.get("cmd", "")).lower().strip(); q = str(a.get("query", "")).strip()
    if q:
        try: os.startfile("spotify:search:" + urllib.parse.quote(q)); launched = ("Spotify.exe", "spotify")
        except Exception: webbrowser.open("https://open.spotify.com/search/" + urllib.parse.quote(q)); launched = ("", "browser")
        hint = ("click Play on the top result, then confirm the Pause icon shows (it is really playing)" if screen_on else
                "Screen control is OFF, so I can't press play; tell the user to switch it on, or add a Spotify Client ID in Settings for hands-free playback")
        return f"opened Spotify search for “{q}”; {hint}", launched
    if cmd in ("play", "resume", "ensure_playing"): return spotify_ensure_playing(stop_ev), None
    if cmd == "pause" and spotify_state() is False: return "spotify: already paused", None
    if cmd in MEDIA_KEYS:
        try: keyboard.send(MEDIA_KEYS[cmd])
        except Exception as ex: return f"spotify {cmd}: failed ({ex})", None
        return f"spotify {cmd}: sent", None
    return f"spotify: unknown command '{cmd}'", None


def coalesce(acts):
    """Light mode: collapse micro-movements so they don't become separate heavy steps."""
    out = []
    for a in acts:
        d = a["do"]
        if d == "move" and out and out[-1]["do"] == "move": out[-1] = a; continue        # keep only the last of consecutive moves
        if d in ("click", "drag", "scroll") and out and out[-1]["do"] == "move": out.pop()   # these move the cursor themselves
        out.append(a)
    return out


def glide(x, y, emit=None, min_dur=0.0):
    """Smooth, distance-scaled cursor move. Every step is reported through emit(x, y, kind) so the on-screen AI cursor follows the REAL pointer."""
    cx, cy = pyautogui.position(); d = math.hypot(x - cx, y - cy)
    if emit: emit(int(cx), int(cy), "start")
    if d < 4:
        pyautogui.moveTo(x, y, _pause=False)
        if emit: emit(int(x), int(y), "move")
        return
    dur = max(min_dur, min(0.4, 0.06 + d / 4500)); n = max(3, int(dur / 0.011)); t0 = time.time()
    for i in range(1, n + 1):
        u = i / n; e = u * u * (3 - 2 * u)                                   # smoothstep: eases in and out like a hand
        px, py = int(cx + (x - cx) * e), int(cy + (y - cy) * e)
        pyautogui.moveTo(px, py, _pause=False)
        if emit: emit(px, py, "move")
        time.sleep(max(0.0, t0 + dur * u - time.time()))


# ---------- background control: user-idle yield, UI Automation, Spotify Web API, monitor targeting ----------
import ctypes


class _LII(ctypes.Structure): _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


_inj = [0]


def _tick(): return ctypes.windll.kernel32.GetTickCount() if sys.platform == "win32" else 0


def mark_injected(): _inj[0] = _tick()


def _idle_ms():
    """Milliseconds since the last REAL user input (input we injected ourselves is ignored)."""
    if sys.platform != "win32": return 99999
    li = _LII(); li.cbSize = ctypes.sizeof(li)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)): return 99999
    if li.dwTime <= _inj[0] + 150: return 99999
    return (_tick() - li.dwTime) & 0xFFFFFFFF


def wait_user_idle(stop_ev, need=450, timeout=12.0):
    """Never type/click over the user: wait until they pause, so they can keep working meanwhile."""
    end = time.time() + timeout
    while _idle_ms() < need:
        if stop_ev.is_set() or time.time() > end: return False
        time.sleep(0.08)
    return True


INTERACTIVE = {"ButtonControl", "MenuItemControl", "EditControl", "CheckBoxControl", "ListItemControl", "TabItemControl",
               "HyperlinkControl", "ComboBoxControl", "RadioButtonControl", "SplitButtonControl", "TreeItemControl"}


def _uia_window(title):
    w = uia.WindowControl(searchDepth=1, SubName=str(title))
    if not w.Exists(1.2, 0.2): raise RuntimeError(f"no window matching '{title}'")
    return w


def _uia_find(title, name, edit=False):
    w = _uia_window(title); n = str(name or "").lower()
    for c, _d in uia.WalkControl(w, maxDepth=12):
        if edit and c.ControlTypeName == "EditControl" and (not n or n in (c.Name or "").lower()): return c
        if not edit and c.ControlTypeName in INTERACTIVE and n and n in (c.Name or "").lower(): return c
    raise RuntimeError(f"no {'text field' if edit else 'control'} '{name}' in '{title}'")


def ui_job(a):
    """UI Automation (no mouse, no keyboard, no focus change). Returns (message, look_flag)."""
    if uia is None: return "ui_*: install the 'uiautomation' package (pip install uiautomation)", False
    k = a["do"]; title = a.get("window", "")
    try: ctx = uia.UIAutomationInitializerInThread()
    except Exception: ctx = None
    try:
        if ctx is not None: ctx.__enter__()
        if k == "ui_list":
            w = _uia_window(title); out = []
            for c, _d in uia.WalkControl(w, maxDepth=9):
                if c.ControlTypeName in INTERACTIVE and (c.Name or c.ControlTypeName == "EditControl") and not c.IsOffscreen:
                    out.append(f"{c.ControlTypeName[:-7]}: {(c.Name or '')[:50]}")
                    if len(out) >= 50: break
            return (f"controls in '{title}':\n" + "\n".join(out)) if out else f"no accessible controls in '{title}' (the app may not expose UI Automation)", "text"
        if k == "ui_click":
            c = _uia_find(title, a.get("name", ""))
            for getter, act in (("GetInvokePattern", "Invoke"), ("GetSelectionItemPattern", "Select"), ("GetTogglePattern", "Toggle"), ("GetExpandCollapsePattern", "Expand")):
                p = getattr(c, getter)()
                if p: getattr(p, act)(); return f"clicked '{(c.Name or '')[:40]}' in the background", False
            return f"'{(c.Name or '')[:40]}' can't be triggered without the mouse; use click instead", "text"
        if k == "ui_type":
            c = _uia_find(title, a.get("name", ""), edit=True); p = c.GetValuePattern()
            if not p: return "that field doesn't accept direct text; use type instead", "text"
            p.SetValue(str(a.get("text", ""))); return f"typed into '{(c.Name or 'text field')[:40]}' in the background", False
        return f"{k}: unknown", False
    except Exception as ex: return f"{k}: failed ({ex})", "text"
    finally:
        if ctx is not None:
            try: ctx.__exit__(None, None, None)
            except Exception: pass


class SpotifyAPI:
    """Spotify Web API with PKCE (no client secret). Plays things directly, in the background; needs Premium for playback control."""
    AUTH, TOKEN, API = "https://accounts.spotify.com/authorize", "https://accounts.spotify.com/api/token", "https://api.spotify.com/v1"
    REDIRECT = "http://127.0.0.1:8888/callback"
    SCOPE = "user-modify-playback-state user-read-playback-state user-read-currently-playing"

    def __init__(s, cfg):
        s.cfg = cfg; s.path = os.path.join(BASE, "spotify_token.json"); s.tok = {}
        try: s.tok = json.load(open(s.path, encoding="utf-8"))
        except Exception: pass

    def enabled(s): return bool(str(s.cfg.get("spotify_client_id", "")).strip())

    def _store(s, j):
        s.tok = {**s.tok, **j, "exp": time.time() + int(j.get("expires_in", 3600)) - 30}
        try: json.dump(s.tok, open(s.path, "w", encoding="utf-8"))
        except Exception: pass

    def _post(s, data):
        r = SESSION.post(s.TOKEN, data=data, timeout=15)
        if r.status_code >= 400: raise RuntimeError(f"Spotify login failed ({r.status_code})")
        s._store(r.json())

    def login(s):
        import secrets, hashlib, http.server, urllib.parse
        cid = str(s.cfg["spotify_client_id"]).strip(); ver = secrets.token_urlsafe(64)[:100]; state = secrets.token_urlsafe(8); box = {}
        chal = base64.urlsafe_b64encode(hashlib.sha256(ver.encode()).digest()).rstrip(b"=").decode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(h):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query); box["code"] = q.get("code", [None])[0]; box["state"] = q.get("state", [None])[0]
                h.send_response(200); h.send_header("Content-Type", "text/html; charset=utf-8"); h.end_headers()
                h.wfile.write(b"<h2>Spotify connected. You can close this tab.</h2>")
            def log_message(h, *a): pass
        srv = http.server.HTTPServer(("127.0.0.1", 8888), H); srv.timeout = 120
        webbrowser.open(s.AUTH + "?" + urllib.parse.urlencode({"client_id": cid, "response_type": "code", "redirect_uri": s.REDIRECT, "scope": s.SCOPE,
                                                                  "code_challenge_method": "S256", "code_challenge": chal, "state": state}))
        try: srv.handle_request()
        finally: srv.server_close()
        if not box.get("code") or box.get("state") != state: raise RuntimeError("Spotify login was cancelled or timed out")
        s._post({"grant_type": "authorization_code", "code": box["code"], "redirect_uri": s.REDIRECT, "client_id": cid, "code_verifier": ver})

    def access(s):
        if s.tok.get("access_token") and time.time() < s.tok.get("exp", 0): return s.tok["access_token"]
        if s.tok.get("refresh_token"):
            try: s._post({"grant_type": "refresh_token", "refresh_token": s.tok["refresh_token"], "client_id": str(s.cfg["spotify_client_id"]).strip()}); return s.tok["access_token"]
            except Exception: pass
        s.login(); return s.tok["access_token"]

    def call(s, method, path, **kw):
        for _ in range(2):
            r = SESSION.request(method, s.API + path, headers={"Authorization": "Bearer " + s.access()}, timeout=12, **kw)
            if r.status_code != 401: return r
            s.tok["exp"] = 0
        return r

    def device(s, stop_ev):
        """Pick the active (or first) device; start the Spotify app and wait for it if none is up."""
        launched = False; end = time.time() + 14
        while time.time() < end and not stop_ev.is_set():
            r = s.call("GET", "/me/player/devices")
            devs = r.json().get("devices", []) if r.status_code == 200 else []
            if devs: return next((d for d in devs if d.get("is_active")), devs[0])["id"]
            if not launched:
                launched = True
                try: os.startfile("spotify:")
                except Exception: pass
            time.sleep(0.7)
        raise RuntimeError("no Spotify device found - open the Spotify app and log in")

    def play(s, query, kind, stop_ev):
        kind = kind if kind in ("track", "artist", "playlist", "album") else "track"
        r = s.call("GET", "/search", params={"q": query, "type": kind, "limit": 1})
        if r.status_code != 200: raise RuntimeError(f"search failed ({r.status_code})")
        items = [i for i in r.json().get(kind + "s", {}).get("items", []) if i]
        if not items: raise RuntimeError(f"nothing found for '{query}'")
        it = items[0]; name = it["name"] + (" - " + it["artists"][0]["name"] if kind == "track" and it.get("artists") else "")
        dev = s.device(stop_ev)
        r = s.call("PUT", "/me/player/play", params={"device_id": dev}, json={"uris": [it["uri"]]} if kind == "track" else {"context_uri": it["uri"]})
        if r.status_code == 403: raise RuntimeError("Spotify Premium is required for remote playback")
        if r.status_code >= 300: raise RuntimeError(f"play failed ({r.status_code})")
        return f"now playing {name} on Spotify"


def spotify_job(app, a, screen_on):
    q = str(a.get("query", "")).strip(); kind = str(a.get("kind", "")).lower() or ("playlist" if "playlist" in q.lower() else "track")
    try: return app.sp_api().play(q, kind, app.stop_ev), False
    except Exception as ex:
        m, _ = spotify_do({"query": q}, screen_on)            # fallback: open the search; the model then finishes it on screen
        return f"Spotify API unavailable ({ex}); {m}", bool(screen_on)


def youtube_job(a, screen_on):
    """Free, no account: find the first YouTube result and open that video directly (it normally starts by itself)."""
    q = str(a.get("query", "")).strip()
    try:
        r = SESSION.get("https://www.youtube.com/results", params={"search_query": q, "hl": "en"}, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"})
        ids = re.findall(r'"videoRenderer":\{"videoId":"([\w-]{11})"', r.text) or re.findall(r'"videoId":"([\w-]{11})"', r.text)
        if not ids: raise RuntimeError("no results")
        vid = ids[0]; t = re.search(r'"videoId":"' + vid + r'".{0,600}?"title":\{"runs":\[\{"text":"(.*?)"\}', r.text, re.S)
        try: title = json.loads('"' + t.group(1) + '"') if t else q
        except Exception: title = q
        webbrowser.open("https://www.youtube.com/watch?v=" + vid)
        if screen_on: time.sleep(2.5)
        return f"opened “{title[:60]}” on YouTube; verify it is playing, and if paused click the video once", bool(screen_on)
    except Exception as ex:
        webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q))
        if screen_on: time.sleep(2.5)
        return f"YouTube lookup failed ({ex}); opened the search instead - click the first video", bool(screen_on)


def run_jobs(jobs, results):
    flag = False
    for j in jobs:
        try: msg, f = j()
        except Exception as ex: msg, f = f"failed ({ex})", False
        results.append(msg)
        if f is True: flag = True
        elif f == "text" and flag is False: flag = "text"
    return flag


def _win_exe(h):
    from ctypes import wintypes
    k, u = ctypes.windll.kernel32, ctypes.windll.user32
    k.OpenProcess.restype = wintypes.HANDLE; k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    pid = wintypes.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    hp = k.OpenProcess(0x1000, False, pid.value)
    if not hp: return ""
    try:
        buf = ctypes.create_unicode_buffer(520); n = wintypes.DWORD(520)
        ok = k.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(n))
        return os.path.basename(buf.value).lower() if ok else ""
    finally: k.CloseHandle(hp)


def window_screen(exes):
    """Which monitor currently holds a window of one of these executables?"""
    if sys.platform != "win32": return None
    from ctypes import wintypes
    r = wintypes.RECT()
    for h, _t in _top_windows():
        if _win_exe(h) in exes:
            ctypes.windll.user32.GetWindowRect(h, ctypes.byref(r))
            return screen_at_phys((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    return None


def infer_target_screen(text):
    """Pick the monitor a request is about: 'on my second screen' or an app that lives on another monitor."""
    t = str(text or "").lower()
    if not t or len(ordered_screens()) < 2: return None
    scr = r"(?:monitor|screen|display)"
    if re.search(r"\b(?:secondary|second|2nd|other|external|another)\s+" + scr, t): return pick_screen("secondary")
    if re.search(r"\b(?:primary|main|first|1st)\s+" + scr, t): return pick_screen("primary")
    for side in ("left", "right"):
        if re.search(r"\b" + side + r"\s+" + scr, t): return pick_screen(side)
    try:
        for k, v in APPS.items():
            if v[1] and re.search(r"\b" + re.escape(k) + r"\b", t):
                sc = window_screen({v[1].lower()})
                if sc: return sc
    except Exception: pass
    return None


def force_foreground(w):
    """Windows refuses focus to background apps; without it the first click on a freshly shown window can be swallowed."""
    if sys.platform != "win32": return
    try:
        import ctypes
        u = ctypes.windll.user32; hwnd = int(w.winId()); cur = ctypes.windll.kernel32.GetCurrentThreadId()
        fg = u.GetForegroundWindow(); tid = u.GetWindowThreadProcessId(fg, None) if fg else 0
        if tid and tid != cur: u.AttachThreadInput(tid, cur, True)
        u.BringWindowToTop(hwnd); u.SetForegroundWindow(hwnd)
        if tid and tid != cur: u.AttachThreadInput(tid, cur, False)
    except Exception: pass


def grab_screen(sc=None):
    sc = sc or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    return sc, sc.grabWindow(0)


def prep_image(pix, grid=False, maxw=1280):
    """QPixmap -> QImage scaled for the model; optional labelled coordinate grid so the model can aim clicks."""
    img = pix.toImage(); img.setDevicePixelRatio(1.0)
    if img.width() > maxw: img = img.scaledToWidth(maxw, Qt.TransformationMode.SmoothTransformation)
    if grid:
        img = img.convertToFormat(QImage.Format.Format_RGB32)
        p = QPainter(img); p.setFont(QFont("Segoe UI", 8)); step = 200
        for x in range(0, img.width(), step):
            p.setPen(QPen(QColor(255, 0, 80, 90), 1)); p.drawLine(x, 0, x, img.height())
            p.setPen(QColor(255, 0, 80)); p.drawText(x + 2, 11, str(x))
        for y in range(step, img.height(), step):
            p.setPen(QPen(QColor(255, 0, 80, 90), 1)); p.drawLine(0, y, img.width(), y)
            p.setPen(QColor(255, 0, 80)); p.drawText(2, y - 2, str(y))
        p.end()
    return img


def img_to_b64(img):
    ba = QByteArray(); buf = QBuffer(ba); buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG", 65)
    return base64.b64encode(bytes(ba)).decode()


def transcribe(cfg, wav):
    r = SESSION.post(cfg["stt_url"], headers={"Authorization": "Bearer " + cfg["stt_key"]},
                     files={"file": ("a.wav", wav, "audio/wav")},
                     data={"model": cfg["stt_model"], "response_format": "json"}, timeout=(5, 25))
    r.raise_for_status()
    return (r.json().get("text") or "").strip()


def warm(urls):
    def go():
        for u in dict.fromkeys(urls):
            try:
                p = urllib.parse.urlparse(u)
                if p.scheme: SESSION.head(f"{p.scheme}://{p.netloc}", timeout=4)
            except Exception: pass
    threading.Thread(target=go, daemon=True).start()

# One flat namespace across the package (it was split out of a single file); exporting
# everything, including the private helpers, keeps the behaviour identical.
__all__ = [n for n in globals() if not n.startswith('__')]
