"""Application controller: tray, hotkeys, updates and the main entry point."""
from .core import *
from .accounts import *
from .system import *
from .voice import *
from .connectors import *
from .chat import *
from .dialogs import *

# ---------- update check (GitHub Releases) ----------
def _vtuple(v): return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def latest_release():
    """Highest-numbered published release (drafts ignored) if it is newer than this app, else None."""
    r = SESSION.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases", params={"per_page": 15}, timeout=10, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    rels = [j for j in r.json() if not j.get("draft") and j.get("tag_name")]
    if not rels: return None
    j = max(rels, key=lambda x: _vtuple(x["tag_name"])); tag = str(j["tag_name"])
    if _vtuple(tag) > _vtuple(APP_VERSION): return {"version": tag.lstrip("vV"), "page": j.get("html_url"), "notes": str(j.get("body") or "")}
    return None


def delete_self_after_exit():
    """Packaged .exe only: a hidden helper deletes this old exe as soon as the app has closed (settings/memory/vault files are kept)."""
    if not FROZEN or sys.platform != "win32": return
    exe = sys.executable
    subprocess.Popen(f'for /l %i in (1,1,15) do (del /f /q "{exe}" >nul 2>&1 & if not exist "{exe}" exit /b & ping -n 2 127.0.0.1 >nul)',
                     shell=True, creationflags=NO_WINDOW)


# ---------- app controller ----------
class App(QObject):
    toggle = pyqtSignal(); summ = pyqtSignal(); area = pyqtSignal(); stop = pyqtSignal(); update_found = pyqtSignal(object)

    def __init__(s, qapp):
        super().__init__()
        s.cfg = load_cfg(); s.memory = Memory(MEM_PATH); s.vault = Vault(VAULT_PATH)
        s.vault.session_min = int(s.cfg.get("vault_session_min", 5)); s.ov = Overlay(s.cfg, s.memory, s.vault); s.settings = Settings(s)
        s.ov.blocked = lambda: s.settings.isVisible() or bool(s.settings.recording)
        QGuiApplication.instance().screenAdded.connect(lambda _: s.on_screens_changed())
        QGuiApplication.instance().screenRemoved.connect(lambda _: s.on_screens_changed())
        s.toggle.connect(s.ov.toggle); s.summ.connect(s.ov.hotkey_summarize); s.area.connect(s.ov.hotkey_area)
        s.stop.connect(s.ov.emergency_stop); s.ov.open_settings.connect(s.show_settings); s.ov.open_conn.connect(lambda: s.show_settings("Connections"))
        pm = QPixmap(32, 32); pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#8ab4f8")); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(4, 4, 24, 24); p.end()
        s.tray = QSystemTrayIcon(QIcon(pm)); m = QMenu()
        for label, fn in (("Open overlay", lambda: s.ov.open_overlay()), ("Canvas", s.ov.show_canvas), ("Check for updates", lambda: s.check_updates(manual=True)), ("Settings", s.show_settings), ("Quit", qapp.quit)):
            a = QAction(label, m); a.triggered.connect(lambda _, fn=fn: fn()); m.addAction(a)
        s.tray.setContextMenu(m); s.tray.setToolTip("AI Overlay"); s.tray.show(); s._menu = m
        s.apply_hotkeys()
        s.update_found.connect(s.on_update_found)
        QTimer.singleShot(5000, s.check_updates); s._ut = QTimer(s); s._ut.timeout.connect(s.check_updates); s._ut.start(6 * 3600 * 1000)
        s.hub = ConnectorHub(s.cfg); s.ov.hub = s.hub
        s.hub.notice.connect(s.on_notice); s.hub.replied.connect(s.ov.on_replied); s.hub.status.connect(s.settings.on_conn_status)
        s.tray.messageClicked.connect(s.open_notifications); QTimer.singleShot(1500, s.hub.apply)
        if not s.ov.providers(): s.show_settings()

    # ---------- connected apps ----------
    def on_notice(s, n):
        s.ov.add_notice(n)
        if not s.ov.is_open(): s.tray.showMessage(f"{n.app}: {n.title}"[:60], n.body[:120], QSystemTrayIcon.MessageIcon.Information, 5000)

    def open_notifications(s):
        if not s.ov.is_open(): s.ov.open_overlay(listen=False, full=True); s.ov._notice_only = True     # opened only to read them: closing them hides it again
        s.ov.toggle_drawer(True)

    # ---------- updates ----------
    def check_updates(s, manual=False):
        if "YOUR_NAME" in GITHUB_REPO:
            if manual: QMessageBox.information(None, "Updates", "Set GITHUB_REPO at the top of the script first (for example \"john/ai-overlay\").")
            return
        if not manual and (not FROZEN or not s.cfg.get("auto_update", True)): return      # no automatic nagging while running from source
        threading.Thread(target=s._check_thread, args=(manual,), daemon=True).start()

    def _check_thread(s, manual):
        try: info = latest_release(); s.update_found.emit({"manual": manual, **info} if info else {"manual": manual, "uptodate": True})
        except Exception as ex: s.update_found.emit({"manual": manual, "error": str(ex)})

    def on_update_found(s, info):
        manual = info.get("manual")
        if info.get("error"):
            if manual: QMessageBox.warning(None, "Updates", f"Couldn't check for updates:\n{info['error']}")
            return
        if info.get("uptodate"):
            if manual: QMessageBox.information(None, "Updates", f"You're up to date (version {APP_VERSION}).")
            return
        v = str(info["version"])
        if not manual and v == s.cfg.get("skipped_version"): return
        box = QMessageBox(); box.setWindowTitle("Update available"); box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        old = "This old version will be deleted when the app closes. Save the new .exe in this same folder to keep your settings and memory." if FROZEN else ""
        box.setText(f"A new version ({v}) is available. You have {APP_VERSION}.\n\n{info['notes'][:300]}\n\n{old}")
        yes = box.addButton("Download new version", QMessageBox.ButtonRole.AcceptRole); box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        skip = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole); box.exec()
        if box.clickedButton() is skip: s.cfg["skipped_version"] = v; save_cfg(s.cfg); return
        if box.clickedButton() is not yes: return
        webbrowser.open(str(info.get("page") or f"https://github.com/{GITHUB_REPO}/releases/latest"))
        if FROZEN: delete_self_after_exit(); QGuiApplication.instance().quit()

    def on_screens_changed(s):
        s.settings.refresh_displays(); s.ov.apply_display()

    def show_settings(s, page=None):
        w = s.settings
        if isinstance(page, str) and page in w.PAGES: w.nav.setCurrentRow(w.PAGES.index(page))
        if w.isMinimized(): w.showNormal()
        sc = resolve_screen(s.cfg)
        if not w.isVisible(): place_on(w, sc); w.move(sc.availableGeometry().center() - w.rect().center())
        w.show(); w.raise_(); w.activateWindow(); force_foreground(w)

    def _clear_hotkeys(s):
        for h in getattr(s, "_hk", []):
            try: keyboard.remove_hotkey(h)
            except Exception: pass
        s._hk = []

    def pause_hotkeys(s): s._clear_hotkeys()

    def apply_hotkeys(s):
        s._clear_hotkeys(); bad = []
        for key, sig in (("hk_toggle", s.toggle), ("hk_summarize", s.summ), ("hk_area", s.area), ("hk_stop", s.stop)):
            c = s.cfg.get(key)
            if not c: continue
            try: s._hk.append(keyboard.add_hotkey(c, sig.emit))
            except Exception: bad.append(c)
        if bad: s.tray.showMessage("AI Overlay", "Couldn't register: " + ", ".join(bad))


def main():
    qapp = QApplication(sys.argv); qapp.setQuitOnLastWindowClosed(False)
    app = App(qapp)
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()

# One flat namespace across the package (it was split out of a single file); exporting
# everything, including the private helpers, keeps the behaviour identical.
__all__ = [n for n in globals() if not n.startswith('__')]
