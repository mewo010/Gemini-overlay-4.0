"""The overlay window itself: collapsed orb, unfolding chat, actions and the streaming reply pipeline."""
from .core import *
from .accounts import *
from .system import *
from .voice import *
from .widgets import *
from .connectors import *
from .panel import *
from .orb_animation import should_hover_expand
from .chat_animation import *
from .ai import (provider_chain, build_body, stream_chat, AIError, trim_history, gemini_model,
                 TOTAL_TIMEOUT, MAX_ATTEMPTS)

# ---------- main overlay ----------
CONTROL = {"click", "move", "drag", "scroll", "type", "key", "wait"}




class Overlay(QWidget):
    partial = pyqtSignal(int, str); finished = pyqtSignal(int, bool); heard = pyqtSignal(int, str)
    ai_cur = pyqtSignal(int, int, str); open_conn = pyqtSignal(); gui_sig = pyqtSignal(object)
    acts_done = pyqtSignal(int, object); note = pyqtSignal(str); open_settings = pyqtSignal(); served = pyqtSignal(int, str); launched = pyqtSignal(int, object, object); fast = pyqtSignal(int, object, str)
    W_BASE, DRAWER_W, H_COMPACT, H_FULL = 1040, 300, 132, 540
    W = property(lambda s: s.W_BASE + (s.DRAWER_W if getattr(s, "_drawer_on", False) else 0))   # grows when the notification drawer is open

    def __init__(s, cfg, memory, vault):
        super().__init__()
        s.cfg, s.memory, s.vault = cfg, memory, vault
        s.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        s.setMinimumSize(0, 0)          # the window must be able to shrink to the orb, so the chat can grow out of it
        s.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        s.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)      # re-showing mid-automation must not steal focus
        s.rec = Recorder(); s.speaker = Speaker(cfg); s.speaker.err_cb = s.note.emit
        s.messages = []; s.pending = None; s.reply = ""; s.kind = "chat"
        s.region = None; s.state = "idle"; s.req = 0; s.sel = None; s._grp = None; s._grp_done = None; s.canvas = None
        s.cool = {}; s.step = 0; s.stop_ev = threading.Event(); s._stealth = False; s._sc = None; s.meta = None
        s.cur = AICursor(); s._cur_scr = None; s._cur_was = False; s._scr_cache = []; s._cur_dim = QTimer(s); s._cur_dim.setSingleShot(True)
        s._cur_dim.timeout.connect(lambda: s.cur.setWindowOpacity(0.45)); s._notice_only = False; s.repairs = 0; s.recoveries = 0; s._last_auto = False; s.exec_lines = []; s.fail_streak = False; s._run_t0 = 0.0
        s.usage = Usage(USAGE_PATH); s._closing = False; s.scr = None; s.blocked = lambda: False      # blocked(): App says Settings is open -> no automation

        outer = QVBoxLayout(s); outer.setContentsMargins(16, 16, 16, 16)
        panel = QFrame(); panel.setObjectName("panel"); outer.addWidget(panel)
        s._panel = panel; s.notices = []; s._drawer_on = False; s._unread = 0; s.hub = None; s._tickn = 0     # shadow is painted in paintEvent (graphics effects were slow and left artifacts)
        hbox = QHBoxLayout(panel); hbox.setContentsMargins(0, 0, 0, 0); hbox.setSpacing(0)
        mainw = QWidget(); lay = QVBoxLayout(mainw); lay.setContentsMargins(16, 12, 16, 14); hbox.addWidget(mainw, 1)
        s.drawer = QFrame(); s.drawer.setObjectName("drawer"); s.drawer.setFixedWidth(s.DRAWER_W); s.drawer.hide(); hbox.addWidget(s.drawer)
        dv = QVBoxLayout(s.drawer); dv.setContentsMargins(14, 14, 14, 12); dv.setSpacing(8)
        dh = QHBoxLayout(); dt = QLabel("Notifications"); dt.setObjectName("dtitle"); dclear = QPushButton("Clear all"); dclear.setObjectName("link")
        dclose = QPushButton("✕"); dclose.setObjectName("nx"); dclose.setFixedSize(22, 22); dclose.setToolTip("Close notifications")
        dh.addWidget(dt, 1); dh.addWidget(dclear); dh.addWidget(dclose); dv.addLayout(dh)
        s.dconn = QPushButton(""); s.dconn.setObjectName("link"); s.dconn.setCursor(Qt.CursorShape.PointingHandCursor); dv.addWidget(s.dconn, 0, Qt.AlignmentFlag.AlignLeft)
        s.dconn.clicked.connect(lambda: (s.close_overlay(), QTimer.singleShot(260, s.open_conn.emit)))
        dclose.clicked.connect(lambda: s.toggle_drawer(False))
        s.dscroll = QScrollArea(); s.dscroll.setWidgetResizable(True); s.dscroll.setFrameShape(QFrame.Shape.NoFrame)
        dinner = QWidget(); s.dlist = QVBoxLayout(dinner); s.dlist.setContentsMargins(0, 0, 4, 0); s.dlist.setSpacing(8)
        s.dempty = QLabel("Nothing yet.\nTap “Manage connections” to link an app."); s.dempty.setObjectName("dempty"); s.dempty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.dlist.addWidget(s.dempty); s.dlist.addStretch(1); s.dscroll.setWidget(dinner); dv.addWidget(s.dscroll, 1)
        dclear.clicked.connect(s.clear_notices)

        top = QHBoxLayout(); s.orb = Orb(); top.addWidget(s.orb)
        s.status = QLabel("Ready - tap 🎤 or type"); top.addWidget(s.status, 1)
        s.b_sum = QPushButton("Summarize"); s.b_area = QPushButton("Select area")
        s.b_exp = QPushButton("Explain"); s.b_tr = QPushButton("Translate")
        s.b_scr = QPushButton("Screen control"); s.b_scr.setCheckable(True)
        s.b_can = QPushButton("Canvas"); s.b_bell = QPushButton("🔔"); s.b_snd = QPushButton("🔊"); s.b_snd.setCheckable(True); s.b_snd.setChecked(not cfg.get("muted"))
        s.b_set = QPushButton("⚙"); s.b_x = QPushButton("✕")
        for b in (s.b_snd, s.b_set, s.b_x): b.setFixedWidth(32)
        s.b_sum.setToolTip("One-shot, read-only summary of your screen (or the selected area)")
        s.b_area.setToolTip("Pick a region for the assistant to look at (read-only)")
        s.b_scr.setToolTip("Live mode: fresh screenshot every turn; the assistant can click, drag, scroll and type.\nStop anytime with the emergency-stop hotkey.")
        s.b_snd.setToolTip("Spoken replies on/off")
        for b in (s.b_exp, s.b_tr, s.b_sum, s.b_area, s.b_scr, s.b_can, s.b_bell, s.b_snd, s.b_set, s.b_x):
            b.setCursor(Qt.CursorShape.PointingHandCursor); top.addWidget(b)
        s.b_exp.setToolTip("Whiteboard explanation of this screen (or the selected area): steps + arrows to the exact elements")
        s.b_tr.setToolTip("Translate the text on this screen (or the selected area) on the whiteboard")
        lay.addLayout(top)
        s.out = QTextBrowser(); s.out.setOpenExternalLinks(True); s.out.hide(); lay.addWidget(s.out, 1)
        s.execl = QLabel(""); s.execl.setObjectName("execl"); s.execl.setWordWrap(True); s.execl.setTextFormat(Qt.TextFormat.RichText); s.execl.hide(); lay.addWidget(s.execl)
        s.srcl = QLabel(""); s.srcl.setObjectName("src"); s.srcl.setWordWrap(True); s.srcl.hide(); lay.addWidget(s.srcl)
        s.chip = QFrame(); s.chip.setObjectName("chip"); s.chip.hide(); cv = QHBoxLayout(s.chip); cv.setContentsMargins(8, 6, 8, 6); cv.setSpacing(10)
        s.thumb = QLabel(); s.thumb.setFixedSize(84, 52); s.thumb.setObjectName("thumb"); cv.addWidget(s.thumb)
        ct = QVBoxLayout(); ct.setSpacing(4); cl = QLabel("Asking about the selected area"); cl.setObjectName("chiptitle"); ct.addWidget(cl)
        qrow = QHBoxLayout(); qrow.setSpacing(6)
        for label, prompt, kind in (("Explain", "Explain what is in this area.", "explain"), ("Summarize", "Summarize this area briefly.", "summarize"),
                                    ("Translate", "Translate the text in this area (to English, or to Hebrew if it is already English).", "translate"),
                                    ("Extract text", "Extract all the text in this area exactly.", None)):
            qb = QPushButton(label); qb.setObjectName("quick"); qb.setCursor(Qt.CursorShape.PointingHandCursor)
            qb.clicked.connect(lambda _, p=prompt, k=kind: s.board_ask(k, p) if k else s.user_ask(text=p)); qrow.addWidget(qb)
        qrow.addStretch(1); ct.addLayout(qrow); cv.addLayout(ct, 1)
        cx = QPushButton("✕"); cx.setObjectName("chipx"); cx.setFixedSize(26, 26); cx.setToolTip("Remove the area"); cx.clicked.connect(lambda: s.set_region(None)); cv.addWidget(cx, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(s.chip)
        bot = QHBoxLayout(); s.edit = QLineEdit(); s.edit.setPlaceholderText("Ask anything, or just speak…")
        s.b_mic = QPushButton("🎤"); s.b_mic.setFixedWidth(40); bot.addWidget(s.edit, 1); bot.addWidget(s.b_mic); lay.addLayout(bot)
        s.setStyleSheet(overlay_qss(chat_color(s.cfg)))

        s.b_x.clicked.connect(s.close_overlay)
        s.b_set.clicked.connect(s.request_settings)
        s.b_sum.clicked.connect(s.summarize); s.b_area.clicked.connect(s.select_area)
        s.b_exp.clicked.connect(s.explain); s.b_tr.clicked.connect(s.translate)
        s.b_scr.toggled.connect(s.on_screen_toggle); s.b_can.clicked.connect(s.show_canvas); s.b_bell.clicked.connect(lambda: s.toggle_drawer())
        s.b_snd.toggled.connect(s.on_sound_toggle); s.b_mic.clicked.connect(s.mic_clicked)
        s.edit.returnPressed.connect(s.submit_text)
        s.partial.connect(s.on_partial); s.finished.connect(s.on_finished); s.heard.connect(s.on_heard)
        s.ai_cur.connect(s.on_ai_cursor); s.gui_sig.connect(lambda fn: fn())
        s.acts_done.connect(s.on_acts_done); s.note.connect(s.on_note); s.served.connect(s.on_served); s.launched.connect(s.on_launched); s.fast.connect(s.on_fast)
        s.timer = QTimer(s); s.timer.timeout.connect(s.tick)        # started on open, stopped on close
        s._stream_text = ""; s._stream_dirty = False                  # coalesced repaints while a reply streams
        s._render_timer = QTimer(s); s._render_timer.setSingleShot(True); s._render_timer.timeout.connect(s._flush_stream)

        # --- collapsed AI orb state + on-screen explanation layer ---
        s._collapsed = False; s._leave_at = 0.0; s._dragging = False; s._expand_t = 0.0; s._seen_inside = False
        s._think_from_open = False; s._bloom = 0.0; s._bloom_anim = None
        s._ghost = False                                                    # the panel surface painted while it is still growing
        s._unfold_p = 1.0; s._unfold_rad = PANEL_RADIUS; s._ghost_inset = 16   # live unfold progress / corner radius / inset
        s._unfold_dir = 1                                                       # 1 = growing out of the orb, -1 = folding back
        s.board = None; s.region_rect = None; s._map = None
        s.outer = outer
        s.big = AIOrb(orb_window(s.cfg), orb_color(s.cfg), aura_color(s.cfg))
        s.collapsed = QWidget(); cbox = QVBoxLayout(s.collapsed); cbox.setContentsMargins(0, 0, 0, 0)
        cbox.addWidget(s.big, 0, Qt.AlignmentFlag.AlignCenter); s.collapsed.hide(); outer.addWidget(s.collapsed)
        s.big.clicked.connect(lambda: s.expand(activate=True)); s.big.move_by.connect(s.orb_moved); s.big.released.connect(s.orb_dropped)
        s.pill = None; s._last_grow = 0.0; s._think_collapsed = False
        s.watch = QTimer(s); s.watch.timeout.connect(s.watch_cursor)    # hover the orb -> open; only runs while visible
        s._watchdog = QTimer(s); s._watchdog.setSingleShot(True); s._watchdog.timeout.connect(s._request_timed_out)
        s._watchdog_rid = 0                                             # a request can never sit in 'thinking' forever
        QApplication.instance().installEventFilter(s)                                      # double-click the open overlay to close it

    # --- geometry / animation ---
    def screen_now(s):
        return s.scr or resolve_screen(s.cfg)

    DRAWER_MIN_H = 400

    def reply_h(s, txt=None):
        """Compact bar by default; it only grows taller for replies that genuinely need more vertical space.

        `txt` lets the streaming path size the window from the text it already has, instead of copying the
        whole document out of the text browser on every repaint."""
        if txt is None: txt = s.out.toPlainText() if not s.out.isHidden() else ""
        lines = sum(max(1, math.ceil(len(ln) / 105)) for ln in (str(txt).splitlines() or [""]))
        h = s.H_COMPACT + 28 + min(360, lines * 20)
        if not s.execl.isHidden(): h += s.execl.sizeHint().height() + 12
        return int(min(s.H_FULL, max(s.H_COMPACT + 46, h)))

    def want_h(s):
        """Height the panel needs RIGHT NOW, derived from what is on screen. Opening notifications only raises it; closing them returns to exactly this."""
        base = s.reply_h() if not s.out.isHidden() else (s.H_COMPACT + (92 if not s.chip.isHidden() else 0) + (s.execl.sizeHint().height() + 10 if not s.execl.isHidden() else 0))
        return max(base, s.DRAWER_MIN_H) if s._drawer_on else base

    def target(s, h):
        """The expanded panel, anchored to the side/corner the orb was docked on (not always bottom-center)."""
        a = s.screen_now().availableGeometry(); m = 10; o = s.orb_rect()
        pm, mg = s._panel_min(), s.outer.contentsMargins()      # never ask for less than the controls need
        need_w = max(s.outer.minimumSize().width(), pm.width() + mg.left() + mg.right())
        need_h = max(s.outer.minimumSize().height(), pm.height() + mg.top() + mg.bottom())
        w = min(max(s.W, need_w), a.width() - 24)
        h = min(max(h, need_h), a.height() - 16)
        x = a.x() + 12 if o.center().x() < a.center().x() else a.right() - w - 12
        y = o.bottom() + m if o.center().y() < a.center().y() else o.top() - h - m
        x = max(a.x() + 8, min(x, a.right() - w - 8)); y = max(a.y() + 8, min(y, a.bottom() - h - 8))
        return QRect(x, y, w, h)

    def orb_rect(s, size=None):
        return orb_rect(s.cfg, s.screen_now(), size)

    def orb_hit(s, pos):
        return s.geometry().adjusted(-6, -6, 6, 6).contains(pos)

    def apply_display(s):
        """Settings changed the target monitor: move an open overlay there now."""
        s.scr = resolve_screen(s.cfg)
        if s.isVisible() and not s._closing: place_on(s, s.scr)
        s.apply_orb_style()

    def apply_theme(s):
        """Re-render the chat from its accent (shared with the orb or independent), live, no restart."""
        qss = overlay_qss(chat_color(s.cfg))
        if qss != s.styleSheet(): s.setStyleSheet(qss); s.update()
        s.orb.set_colors(chat_color(s.cfg), aura_color(s.cfg))

    def _min_for(s, collapsed):
        """Keep the window's minimum in step with its form: exactly the orb when collapsed, free when expanded
        (target() still sizes the panel for its contents), so the chat can always grow out of the orb."""
        if collapsed:
            w = orb_window(s.cfg); s.setMinimumSize(w, w)
        else:
            s.setMinimumSize(0, 0)

    def apply_orb_style(s):
        """Apply the Orb settings (size / colour / position / theme) immediately, without waiting for a restart.

        Safe in every state: it never hides the window, never sets a zero size and never leaves the orb off-screen
        (orb_rect() clamps a saved position onto a real monitor)."""
        normalize_orb(s.cfg)
        size, accent, aura = orb_window(s.cfg), orb_color(s.cfg), aura_color(s.cfg)
        if s.big.width() != size:
            s.big.setFixedSize(size, size); s.outer.invalidate(); s.outer.activate()   # drop the stale layout minimum
        s.big.set_colors(accent, aura)
        if s.pill is not None:
            s.pill.set_colors(accent, aura)
            if s.pill.isVisible(): s._place_pill()
        s.apply_theme()
        if not s.isVisible(): return                                   # the next open() uses the new settings
        if s._closing: return                                        # mid-close: keep the exit quiet
        if s._collapsed:
            s._cancel_run()                                          # a leftover grow/shrink must not move the orb
            s._ghost = False
            s.outer.setContentsMargins(0, 0, 0, 0); s._min_for(True)
            s.collapsed.show(); s._panel.hide()
            s.setGeometry(s.orb_rect())
            s.setWindowOpacity(1.0)
        else:
            s.outer.setContentsMargins(16, 16, 16, 16); s._min_for(False)
            s.setGeometry(s.target(max(s.height(), s.want_h())))     # never shrink a reply that is already showing
        s.raise_()

    # --- thinking pill beside the orb ---
    def _place_pill(s):
        if s.pill is not None: s.pill.follow(s.orb_rect(size=orb_window(s.cfg)), s.screen_now().availableGeometry())

    def show_pill(s, text):
        if s.pill is None: s.pill = StatusPill(orb_color(s.cfg), aura_color(s.cfg))
        s.pill.set_colors(orb_color(s.cfg), aura_color(s.cfg)); s.pill.set_text(text); s._place_pill()
        if not s.pill.isVisible(): s.pill.show()
        s.pill.raise_()

    def hide_pill(s):
        if s.pill is not None and s.pill.isVisible(): s.pill.hide()

    def request_settings(s):
        s.close_overlay(); QTimer.singleShot(260, s.open_settings.emit)     # open AFTER the click is fully finished and the overlay is gone

    # --- collapsed orb <-> full panel ---
    def bloom(s, ms=520):
        """A soft accent halo that spreads from the orb as the chat grows out of it (fades out by itself)."""
        if s._bloom_anim is not None:
            try: s._bloom_anim.stop(); s._bloom_anim.deleteLater()
            except Exception: pass
        a = QVariantAnimation(s); a.setStartValue(0.0); a.setEndValue(1.0); a.setDuration(ms)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(lambda v: s._set_bloom(float(v)))
        a.finished.connect(lambda: s._set_bloom(0.0))
        s._bloom_anim = a; s._set_bloom(0.02); a.start()

    def _set_bloom(s, v):
        s._bloom = max(0.0, min(1.0, v)); s.update()

    def _morph_frame(s, p, a, b, outward):
        """One frame of the unfold, computed by the dedicated chat animation module."""
        f = compute_morph(p, a, b, outward)
        s._unfold_p, s._unfold_rad, s._ghost_inset = f.p, f.radius, f.inset
        s.setGeometry(f.rect())
        s.update()

    def morph(s, to, done=None, ms=460, outward=True):
        """Animate the whole window between the orb and the chat as one continuous surface.

        The ghost keeps painting the real panel surface through the transition, so there is no flicker and no
        layout shift; the controls only appear once the window has reached its final size.
        """
        if not s.isVisible(): return
        a = QRect(s.geometry()); b = QRect(to)
        s._ghost = True; s._unfold_p = 0.0; s._unfold_dir = 1 if outward else -1
        s._ghost_inset = 0 if outward else 16
        pending = None
        if s._grp is not None:
            pending = s._grp_done
            try: s._grp.finished.disconnect()
            except Exception: pass
            try: s._grp.stop(); s._grp.deleteLater()
            except Exception: pass
        if done is None: done = pending                   # streaming mid-unfold keeps the reveal
        g = QParallelAnimationGroup(s)
        anim = QVariantAnimation(s); anim.setStartValue(0.0); anim.setEndValue(1.0); anim.setDuration(max(120, ms))
        anim.setEasingCurve(QEasingCurve.Type.Linear)
        anim.valueChanged.connect(lambda v: s._morph_frame(float(v), a, b, outward))
        g.addAnimation(anim)
        op = QPropertyAnimation(s, b"windowOpacity")
        if outward:
            op.setStartValue(0.0); op.setEndValue(1.0); op.setDuration(max(140, int(ms * 0.50)))
        else:
            op.setDuration(max(140, ms)); op.setKeyValueAt(0.0, 1.0); op.setKeyValueAt(0.60, 1.0); op.setKeyValueAt(1.0, 0.0)
        g.addAnimation(op)
        if done: g.finished.connect(done)
        g.finished.connect(lambda: s._group_done(g))
        s._grp = g; s._grp_done = done; g.start()

    def expand(s, activate=False):
        """Orb -> full chat: the surface unfolds from the orb's corner and glides sideways into place."""
        if not s.isVisible() or s._closing: return
        if not activate and s.settings_open(): return          # hover must not fire through the settings dialog
        if not s._collapsed:
            if activate: s.activateWindow(); s.raise_(); s.edit.setFocus()
            return
        s._collapsed = False; s._leave_at = 0.0; s._expand_t = time.time(); s._seen_inside = False; s._think_collapsed = False
        s.hide_pill()
        s._min_for(False)
        to = s.target(s.want_h())                                        # measured before the margins shrink
        s.outer.setContentsMargins(0, 0, 0, 0)
        s.collapsed.hide(); s._panel.hide()
        start = QRect(s.orb_rect())
        s.setGeometry(start); s.setWindowOpacity(0.0)
        s.morph(to, s._reveal_panel, 480, outward=True)
        s.bloom(480)
        s.raise_()
        if activate: s.activateWindow(); force_foreground(s); s.edit.setFocus()

    def collapse(s, force=False):
        """Full chat -> tiny orb again: the surface folds back into the exact orb and hands its glow over."""
        if s._collapsed or s._closing or not s.isVisible(): return
        if not force and s._busy(): return
        s._collapsed = True; s._leave_at = 0.0; s._min_for(False)
        s._panel.hide(); s.collapsed.hide()
        s.morph(s.orb_rect(), s._collapsed_done, 300, outward=False)

    def _reveal_panel(s):
        """The window has finished growing: swap the painted surface for the real controls."""
        s._ghost = False
        s._unfold_p = 1.0; s._unfold_rad = PANEL_RADIUS; s._ghost_inset = 16
        if s._collapsed or s._closing: return
        s.outer.setContentsMargins(16, 16, 16, 16)
        s._panel.show()
        s.setGeometry(s.target(max(s.height(), s.want_h())))
        s.update()

    def _panel_min(s):
        """Minimum size the real panel needs (works while it is hidden, so the grow animation knows its goal)."""
        lay = s._panel.layout()
        try:
            if lay is not None: lay.activate(); return lay.minimumSize()
        except Exception: pass
        return QSize(0, 0)

    def _collapsed_done(s):
        if not s._collapsed or s._closing: return
        s._ghost = False; s._unfold_p = 1.0; s._ghost_inset = 16
        QToolTip.hideText()
        s.outer.setContentsMargins(0, 0, 0, 0)                    # the orb paints its own glow; no layout inset
        s._panel.hide(); s.collapsed.show(); s.outer.activate(); s._min_for(True); s.setGeometry(s.orb_rect())
        s.setWindowOpacity(0.0); s.run(s.orb_rect(), 1.0, None, 220, QEasingCurve.Type.OutCubic)

    def _busy(s):
        """Reasons to stay open while the pointer is away (typing, listening, thinking, a dialog or the board)."""
        return (s.state in ("listening", "thinking") or s.edit.hasFocus() or s.rec.stream is not None
                or (s.board is not None and s.board.isVisible()) or s.sel is not None or s._drawer_on)

    def settings_open(s):
        """True while the Settings dialog (or any modal) is in front: the orb must not react to the pointer."""
        try:
            if s.blocked and s.blocked(): return True
        except Exception:
            pass
        return QApplication.activeModalWidget() is not None

    def watch_cursor(s):
        """Hover the orb -> open the full overlay. It then stays open until it is closed or the AI starts thinking."""
        if should_hover_expand(visible=s.isVisible(), collapsed=s._collapsed, closing=s._closing,
                               dragging=s._dragging, settings_open=s.settings_open(),
                               enabled=s.cfg.get("orb_hover_expand", True), over_orb=s.orb_hit(QCursor.pos())):
            s.expand()

    def orb_moved(s, dx, dy):
        s._dragging = True
        g = s.geometry().translated(dx, dy); a = s.screen_now().availableGeometry()
        g.moveLeft(min(max(g.x(), a.x() - 8), a.right() - 24)); g.moveTop(min(max(g.y(), a.y() - 8), a.bottom() - 24))
        s.setGeometry(g)

    def orb_dropped(s):
        s._dragging = False
        g = s.geometry(); s.cfg["orb_position"] = "custom"
        s.cfg["orb_x"], s.cfg["orb_y"] = g.x(), g.y()
        try: save_cfg(s.cfg)
        except Exception: pass

    def _cancel_run(s):
        """Stop the current geometry group without running its completion (used when applying static geometry)."""
        if s._grp is None: return
        try: s._grp.finished.disconnect()
        except Exception: pass
        try: s._grp.stop(); s._grp.deleteLater()
        except Exception: pass
        s._grp = None; s._grp_done = None

    def run(s, rect, opacity=None, done=None, ms=280, curve=None, fade_ms=None):
        """Animate geometry (+ optional opacity) as one group, so a stale group can never hide a fresh window.

        A later animation that has no completion of its own (a reply streaming in while the chat is still
        unfolding, which starts a new grow animation) inherits the interrupted one's completion, so the
        window always reaches the state that animation was heading for."""
        if s._ghost:                                    # an interrupted unfold keeps painting the finished surface
            s._unfold_p = 1.0; s._unfold_rad = PANEL_RADIUS; s._ghost_inset = 16
        if s._grp is not None:                          # a stale group used to fire hide() after a quick re-open -> window vanished / clicks lost
            pending = s._grp_done
            try: s._grp.finished.disconnect()
            except Exception: pass
            s._grp.stop(); s._grp.deleteLater()
            if done is None: done = pending              # keep the interrupted animation's ending, e.g. the panel reveal
        g = QParallelAnimationGroup(s)
        a = QPropertyAnimation(s, b"geometry"); a.setDuration(ms); a.setEndValue(rect)
        a.setEasingCurve(curve or QEasingCurve.Type.OutCubic); g.addAnimation(a)
        if opacity is not None:
            o = QPropertyAnimation(s, b"windowOpacity"); o.setDuration(fade_ms or ms); o.setEndValue(opacity)
            o.setEasingCurve(QEasingCurve.Type.OutCubic if opacity >= s.windowOpacity() else QEasingCurve.Type.InCubic)
            g.addAnimation(o)
        if done: g.finished.connect(done)
        g.finished.connect(lambda: s._group_done(g))
        s._grp = g; s._grp_done = done; g.start()

    def _group_done(s, g):
        """Forget a finished group and release it, so a later run() cannot inherit a stale completion."""
        if s._grp is g:
            s._grp = None; s._grp_done = None
            g.deleteLater()

    def is_open(s): return s.isVisible() and not s._closing and s.windowOpacity() > 0.5

    def toggle(s):
        if not s.isVisible(): s.open_overlay()
        elif s._collapsed: s.expand(activate=True)
        elif s.is_open(): s.close_overlay()
        else: s.open_overlay()

    def open_overlay(s, listen=None, full=False):
        """Show the overlay. It always comes back as the Orb unless a caller explicitly asks for the chat (`full`)."""
        s._notice_only = False; s.repairs = 0; s.fail_streak = False; s.execl.hide(); s.exec_lines = []; s.ai_cursor_hide()
        s.region = None; s.messages = []; s.pending = None; s.req += 1; s.step = 0; s._stealth = False; s._closing = False
        s.scr = resolve_screen(s.cfg)                  # locked for this session so automation moving the mouse can't switch monitors
        s.speaker.stop()
        s.b_scr.blockSignals(True); s.b_scr.setChecked(False); s.b_scr.blockSignals(False)
        s.set_region(None); s.out.hide(); s.out.clear(); s.srcl.hide(); s.edit.clear()
        if not s.timer.isActive(): s.timer.start(33)
        if not s.watch.isActive(): s.watch.start(120)
        prov = s.speaker.provider()
        warm([p["url"] for p in s.cfg["providers"]] + ([s.cfg["tts_url"]] if prov == "openai" else ["https://api.elevenlabs.io"] if prov == "elevenlabs" else []))
        s.close_board()
        start_full = bool(full)                                    # the orb is the default entry point, always
        s._collapsed = not start_full; s._leave_at = 0.0; s._dragging = False; s._expand_t = time.time(); s._seen_inside = False
        s._think_from_open = False; s._think_collapsed = False
        s._min_for(not start_full)
        s._ghost = False
        if start_full:
            s.outer.setContentsMargins(16, 16, 16, 16)
            s.collapsed.hide(); s._panel.show()
            place_on(s, s.scr); s.setGeometry(s.target(s.want_h())); s.setWindowOpacity(0)
            s.show(); s.raise_()
            s.run(s.target(s.want_h()), 1.0)
        else:
            s.outer.setContentsMargins(0, 0, 0, 0)
            s._panel.hide(); s.collapsed.show(); s._min_for(True)
            place_on(s, s.scr); s.setGeometry(s.orb_rect()); s.setWindowOpacity(0)
            s.show(); s.raise_()                                # the orb must not steal focus from the app underneath
            s.run(s.orb_rect(), 1.0, None, 260, QEasingCurve.Type.OutCubic, fade_ms=200)
            if s.cfg.get("orb_hover_expand", True) and s.orb_hit(QCursor.pos()): QTimer.singleShot(180, s.expand)
        if listen is None: listen = s.cfg.get("listen_mode", "manual") == "auto"      # default: the mic only turns on when YOU tap it
        if listen: s.start_listening()
        else: s.set_state("idle", "Ready - tap 🎤 or type")

    def close_overlay(s):
        s._render_timer.stop(); s._stream_dirty = False; s._watchdog.stop()
        QToolTip.hideText(); s.req += 1; s.speaker.stop(); s.stop_ev.set(); s.ai_cursor_hide(); s.close_board(); s.hide_pill()
        s._think_collapsed = False; s._think_from_open = False; s._ghost = False
        if s.rec.stream: s.rec.stop()
        s._stealth = False; s.state = "idle"; s.orb.mode = "idle"; s._closing = True
        s._collapsed = False; s._leave_at = 0.0
        s._min_for(False)
        s._panel.hide(); s.collapsed.hide()
        end = QRect(s.orb_rect()); end.adjust(4, 4, -4, -4)       # the chat folds back into the orb
        s.morph(end, s._finish_close, 300, outward=False)

    def _finish_close(s):
        if s._closing:
            s.watch.stop(); s._watchdog.stop()
            s.hide_pill(); s.hide(); s.timer.stop(); QToolTip.hideText(); s._ghost = False
            s._unfold_p = 1.0; s._ghost_inset = 16
            s.collapsed.hide(); s._panel.show(); s.outer.setContentsMargins(16, 16, 16, 16)

    def keyPressEvent(s, e):
        if e.key() == Qt.Key.Key_Escape:
            if s._drawer_on: s.toggle_drawer(False)          # Esc closes the notification layer first, nothing else
            else: s.close_overlay()

    def mouseDoubleClickEvent(s, e):
        if s.isVisible() and not s._collapsed and not s._closing: s.close_overlay()

    def eventFilter(s, o, e):
        """Double-clicking anywhere on the open overlay closes it (text fields keep word selection)."""
        if (e.type() == QEvent.Type.MouseButtonDblClick and s.isVisible() and not s._collapsed and not s._closing
                and isinstance(o, QWidget) and o.window() is s and not isinstance(o, (QLineEdit, QTextBrowser))):
            s.close_overlay(); return True
        return super().eventFilter(o, e)

    def emergency_stop(s):
        s._render_timer.stop(); s._stream_dirty = False
        s.stop_ev.set(); s.req += 1; s.speaker.stop(); s.ai_cursor_hide(); s.close_board()
        if s.rec.stream: s.rec.stop()
        s._unstealth(); s.set_state("idle", "⛔ Stopped")

    def _unstealth(s):
        if s._stealth: s._stealth = False; s.show(); s.raise_()

    # --- hotkeys / small handlers ---
    def hotkey_summarize(s):
        if not s.is_open(): s.open_overlay(listen=False)
        s.expand(activate=True); s.summarize()

    def hotkey_area(s): s.select_area()

    def on_sound_toggle(s, on):
        s.cfg["muted"] = not on
        if not on: s.speaker.stop()

    def on_note(s, msg):
        if s.state != "listening":
            s.status.setText(msg[:110])
            if s.state == "thinking" and s.pill is not None: s.pill.set_text(msg)      # the pill keeps up with the real stage

    def show_canvas(s):
        if s.canvas is None:
            s.canvas = CanvasWindow(); s.canvas.send.connect(s.region_from_canvas)
        if not s.canvas.isVisible():
            sc = s.screen_now(); a = sc.availableGeometry(); place_on(s.canvas, sc); s.canvas.move(a.x() + 60, a.y() + 50)
        s.canvas.show(); s.canvas.raise_()

    def region_from_canvas(s, pix):
        if not s.isVisible(): s.open_overlay(listen=False)
        s.region = pix; s.region_rect = None; s.expand()
        s.b_scr.blockSignals(True); s.b_scr.setChecked(False); s.b_scr.blockSignals(False)
        s.b_area.setText("Canvas ✓"); s.activateWindow(); s.edit.setFocus()
        s.set_state("idle", "Canvas attached - ask about it")

    # --- voice ---
    def set_state(s, st, text):
        prev = s.state
        s.state = st; s.orb.mode = st; s.big.mode = st; s.status.setText(text)
        s.b_mic.setStyleSheet("background:#c62839;color:#fff" if st == "listening" else "")           # red mic = the microphone is ON
        if st == "thinking" and s.isVisible() and not s._closing and s.board is None:
            s._think_from_open = s._think_from_open or not s._collapsed                          # remember where it came from
            if not s._collapsed: s.collapse(force=True)                                           # thinking morphs to the orb + pill
            s._think_collapsed = True
            s.show_pill(text)
        else:
            s.hide_pill()
            if prev == "thinking" and s._think_collapsed:                                          # thinking is over: back to the full overlay
                s._think_collapsed = False; restore, s._think_from_open = s._think_from_open, False
                if (restore and s._collapsed and s.board is None and s.kind not in BOARD_KINDS
                        and s.isVisible() and not s._closing): s.expand()

    def start_listening(s):
        s.speaker.stop()                                           # barge-in + don't record our own voice
        try: s.rec.start(); s.set_state("listening", "Listening…")
        except Exception as ex: s.set_state("idle", f"Mic error: {ex}")

    def finish_listening(s):
        audio = s.rec.stop()
        if audio is None: s.set_state("idle", "Didn't catch that - click 🎤 or type")
        else: s.user_ask(audio=audio)

    def mic_clicked(s):
        s._notice_only = False
        if s.state == "listening": s.finish_listening()
        else: s.start_listening()

    def tick(s):
        if not s.isVisible(): return
        s.orb.level = s.big.level = s.rec.level; s._tickn += 1
        spk = s.speaker.speaking()                                 # Siri-like rings while the reply is being spoken
        if spk and s.state == "idle": mode = "speaking"
        elif not spk and s.big.mode == "speaking": mode = s.state
        else: mode = s.big.mode
        s.big.mode = s.orb.mode = mode
        if s._collapsed and s.pill is not None and s.pill.isVisible(): s._place_pill()
        if mode != "idle" or s.rec.level > 0.02 or s._tickn % 3 == 0: s.orb.update()      # idle orb repaints at 1/3 rate
        if s.state == "listening":
            r = s.rec; now = time.time()
            if (r.spoke and now - r.last_voice > s.cfg["silence"]) or (not r.spoke and now - r.t0 > 8): s.finish_listening()

    # --- AI cursor ---
    def _refresh_screens(s):
        s._scr_cache = []
        for sc in QGuiApplication.screens():
            try: s._scr_cache.append((sc, phys_rect(sc), sc.geometry(), sc.devicePixelRatio()))
            except Exception: pass

    def _to_logical(s, x, y):
        """physical pixel (what pyautogui uses) -> (screen, logical x, logical y) for placing a Qt window"""
        if not s._scr_cache: s._refresh_screens()
        best = None
        for sc, (l, t, w, h), g, d in s._scr_cache:
            if l <= x < l + w and t <= y < t + h: best = (sc, g.x() + (x - l) / d, g.y() + (y - t) / d); break
        if best is None and s._scr_cache:
            sc, (l, t, w, h), g, d = s._scr_cache[0]; best = (sc, g.x() + (x - l) / d, g.y() + (y - t) / d)
        return best

    def on_ai_cursor(s, x, y, kind):
        if kind == "hide" or not s.b_scr.isChecked(): s.ai_cursor_hide(); return
        pos = s._to_logical(x, y)
        if pos is None: return
        sc, lx, ly = pos
        if sc is not s._cur_scr: place_on(s.cur, sc); s._cur_scr = sc
        s.cur.move(int(lx - AICursor.HOT), int(ly - AICursor.HOT))
        if not s.cur.isVisible(): s.cur.show(); s.cur.raise_()
        s.cur.setWindowOpacity(1.0); s._cur_dim.start(4000)                      # fades to 45% when the assistant is idle
        if kind in ("click", "dclick", "rclick"): s.cur.ripple()

    def ai_cursor_hide(s):
        s._cur_dim.stop(); s.cur.hide(); s._cur_scr = None

    def ai_emit(s, x, y, kind): s.ai_cur.emit(int(x), int(y), kind)             # safe to call from the worker thread

    def call_gui(s, fn, timeout=180):
        """Run fn() on the GUI thread and wait for its result (dialogs while a worker thread is busy)."""
        box = {}; ev = threading.Event()

        def run():
            try: box["r"] = fn()
            except Exception as ex: box["e"] = ex
            ev.set()
        s.gui_sig.emit(run); ev.wait(timeout)
        if "e" in box: raise box["e"]
        return box.get("r")

    # --- screen: summarize (read-only) vs. Screen control (live + actions) ---
    def on_screen_toggle(s, on):
        if not on: s.ai_cursor_hide()
        if on:
            s._refresh_screens()
            s.set_region(None)
            s.set_state("idle", "Screen control ON - I can see and control your screen" + ("" if pyautogui else " (install pyautogui!)"))

    def snap_screen(s, cb):
        """Hide the overlay, grab a fresh screenshot, restore the overlay (without taking focus), call cb(pix)."""
        was = s.isVisible() or s._stealth; tok = s.req
        s._cur_was = s.cur.isVisible()
        if s._cur_was: s.cur.hide()                                  # keep the AI cursor out of the screenshot
        s.hide_pill()
        if was: s.hide()
        QTimer.singleShot(100 if was else 0, lambda: s._snap_done(cb, was, tok))

    def _snap_done(s, cb, was, tok=None):
        if tok is not None and tok != s.req: return          # overlay was closed / stopped meanwhile: don't re-show it
        s._sc, pix = grab_screen(getattr(s, "target_scr", None) or s.screen_now())
        if s._cur_was and s.b_scr.isChecked(): s.cur.show(); s.cur.raise_()
        if was: s._stealth = False; s.show()
        if s.state == "thinking" and s.isVisible(): s.show_pill(s.status.text())
        cb(pix)

    def summarize(s): s.board_ask("summarize", SUMMARY_PROMPT, "Reading screen…")
    def explain(s): s.board_ask("explain", PROMPT_EXPLAIN, "Looking at your screen…")
    def translate(s): s.board_ask("translate", PROMPT_TRANSLATE, "Reading the text…")

    def board_ask(s, kind, text, status="Reading screen…"):
        """Explain / summarize / translate -> a whiteboard walkthrough of the screen (or the selected area)."""
        s.speaker.stop(); s.close_board(); s.set_state("thinking", status)
        if s.region: s.ask(text=text, pix=s.region, kind=kind)
        else:
            s.set_state("thinking", "Reading screen…")
            s.snap_screen(lambda pix: s.ask(text=text, pix=pix, kind=kind, screen=True))

    # --- whiteboard explanations (teacher-on-a-canvas layer) ---
    def board_target(s, r):
        """Rect in screenshot/image pixels -> Qt logical screen pixels for the on-screen highlight."""
        if r is None: return None
        m = getattr(s, "_map", None)
        if not m: return None
        try:
            if m["mode"] == "screen":
                sx = m["ox"] + r.x() * m["k"]; sy = m["oy"] + r.y() * m["k"]
                sc = m.get("sc") or s.screen_now(); d = sc.devicePixelRatio() or 1.0
                pos = s._to_logical(sx, sy)
                if pos is None: return None
                return QRect(round(pos[1]), round(pos[2]), max(8, round(r.width() * m["k"] / d)), max(8, round(r.height() * m["k"] / d)))
            rr = QRect(m["rect"]); kx = rr.width() / m["iw"]; ky = rr.height() / m["ih"]
            return QRect(round(rr.x() + r.x() * kx), round(rr.y() + r.y() * ky), max(8, round(r.width() * kx)), max(8, round(r.height() * ky)))
        except Exception:
            return None

    def show_board(s, steps, kind):
        s._think_collapsed = False
        s.close_board()
        m = getattr(s, "_map", None) or {}
        sc = m.get("sc")
        if sc is None and m.get("mode") == "region":
            sc = next((q for q in QGuiApplication.screens() if q.geometry().contains(m["rect"].center())), None)
        sc = sc or s.screen_now(); g = sc.geometry()
        for st in steps:
            r = s.board_target(st.get("target"))
            st["target"] = r.translated(-g.x(), -g.y()) if r is not None else None
        b = Whiteboard(sc, steps, kind, s.cfg, s.speaker)
        b.closed.connect(s._board_closed); s.board = b
        b.show(); b.raise_(); b.setFocus()

    def close_board(s):
        b, s.board = s.board, None
        if b is not None:
            try: b.close()
            except Exception: pass

    def _board_closed(s): s.board = None

    def select_area(s):
        if s.rec.stream: s.rec.stop()
        vis = s.is_open()
        if vis: s.setWindowOpacity(0)
        QTimer.singleShot(180 if vis else 0, s.pick)

    def pick(s):
        sc, pix = grab_screen(s.screen_now()); s.sel = Selector(pix, sc); s.sel.done.connect(s.region_done)
        s.sel.show(); s.sel.raise_(); s.sel.activateWindow(); force_foreground(s.sel); s.sel.setFocus()

    def region_done(s, pix):
        rect = getattr(s.sel, "rect_logical", None) if s.sel is not None else None
        s.sel = None
        if not s.isVisible():
            if pix is None: return
            s.open_overlay(listen=False)
        else: s.setWindowOpacity(1); s.activateWindow()
        if pix is None:
            if s.cfg.get("listen_mode", "manual") == "auto": s.start_listening()
            return
        s.region_rect = rect
        s.b_scr.blockSignals(True); s.b_scr.setChecked(False); s.b_scr.blockSignals(False)
        s.expand(activate=True)
        s.set_region(pix); force_foreground(s); s.edit.setFocus()                    # ready to type right away (no auto-listening)
        s.set_state("idle", "Area selected. Type your question, or tap a quick action.")

    def set_region(s, pix):
        s.region = pix
        if pix is None:
            s.region_rect = None
            s.b_area.setText("Select area"); s.chip.hide(); s.edit.setPlaceholderText("Ask anything, or just speak…")
            if s.isVisible() and not s._closing and not s._collapsed and s.out.isHidden(): s.run(s.target(s.want_h()), None, None, 180)
            return
        s.b_area.setText("Area ✓"); s.chip.show(); s.edit.setPlaceholderText("Ask about the selected area…")
        s.thumb.setPixmap(pix.scaled(84, 52, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if s.isVisible() and not s._closing and not s._collapsed: s.run(s.target(s.want_h()), None, None, 200)

    # --- notification drawer ---
    def toggle_drawer(s, show=None):
        """Show/hide ONLY the notification layer. Nothing underneath is reset: messages, reply, windows and panels stay as they were."""
        on = (not s._drawer_on) if show is None else bool(show)
        if on == s._drawer_on: return
        if on and s._collapsed: s.expand(activate=True)
        s._drawer_on = on; s.drawer.setVisible(on)
        if on: s._unread = 0; s._bell(); s.dempty.setVisible(not s.notices); s._conn_line()
        if s.isVisible() and not s._closing and not s._collapsed:
            s.run(s.target(s.want_h()), None, None, 220)         # closing returns to the height the content itself needs
        if not on and s._notice_only: s._notice_only = False; s.close_overlay()      # opened just to read notifications: hide again as before

    def _conn_line(s):
        n = s.hub.connected_count() if s.hub else 0
        s.dconn.setText((f"● {n} app{'s' if n != 1 else ''} connected  ·  Manage connections" if n else "Connect an app…  Manage connections"))

    def _bell(s): s.b_bell.setText(f"🔔 {s._unread}" if s._unread else "🔔")

    def add_notice(s, n):
        s.notices.insert(0, n)
        for old in s.notices[60:]: s.drop_notice(old)
        card = NoticeCard(n); card.reply.connect(lambda nn, t: s.hub.reply(nn, t) if s.hub else None); card.dismiss.connect(s.drop_notice)
        n._card = card; s.dlist.insertWidget(0, card); s.dempty.hide()
        if not s._drawer_on: s._unread += 1; s._bell()
        if s.is_open() and s.cfg.get("speak_notices", True) and s.state not in ("listening", "thinking") and s.speaker.enabled():
            s.speaker.say(f"New message from {n.app}. {n.title}.")

    def drop_notice(s, n):
        if n in s.notices: s.notices.remove(n)
        c = getattr(n, "_card", None)
        if c is not None: c.setParent(None); c.deleteLater(); n._card = None
        s.dempty.setVisible(not s.notices)

    def clear_notices(s):
        for n in list(s.notices): s.drop_notice(n)

    def on_replied(s, nid, ok, err):
        for n in s.notices:
            if n.id == nid and getattr(n, "_card", None) is not None: n._card.set_result(ok, err)

    def paintEvent(s, e):                         # soft shadow + accent glow around the panel (cheap, no graphics effect)
        ghost = s._ghost
        if s._panel.isHidden() and not ghost: return   # collapsed: only the orb is on screen
        p = QPainter(s); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setPen(Qt.PenStyle.NoPen)
        if ghost:
            i = s._ghost_inset; r = QRectF(s.rect()).adjusted(i, i, -i, -i)
        else:
            r = QRectF(s._panel.geometry())
        accent = chat_color(s.cfg); surf = panel_surface(accent)
        rad = max(2.0, float(s._unfold_rad)) if ghost else surf["radius"]
        paint_panel_frame(p, r, rad, accent)
        paint_bloom(p, s.mapFromGlobal(s.orb_rect().center()), s.size(), accent, s._bloom)
        if ghost and s._unfold_dir > 0 and s._unfold_p < REMNANT_END:
            paint_orb_remnant(p, s.mapFromGlobal(s.orb_rect().center()), s.width(), aura_color(s.cfg),
                              max(0.0, 1.0 - s._unfold_p / REMNANT_END))
        if ghost: paint_ghost_surface(p, r, rad, surf)

    # --- asking ---
    def submit_text(s):
        t = s.edit.text().strip()
        if t: s.edit.clear(); s.user_ask(text=t)

    def user_ask(s, text=None, audio=None):
        s._notice_only = False; s.repairs = 0; s.recoveries = 0
        s.target_scr = infer_target_screen(text) if text else None           # auto-pick the monitor the request is about
        if text and not audio:
            fa = fast_media(text) or fast_intent(text)
            if fa: s.req += 1; s.run_fast(fa, text); return                    # instant, no model round-trip
        if s.b_scr.isChecked():                                    # live mode: always a fresh screenshot
            s.set_state("thinking", "Looking at your screen…")
            s.snap_screen(lambda pix: s.ask(text=text, audio=audio, pix=pix, screen=True))
        else:
            s.ask(text=text, audio=audio, pix=s.region)

    def providers(s):
        """Usable providers; ones in a cooldown are skipped unless nothing else is left."""
        return provider_chain(s.cfg["providers"], s.cool, s.usage)

    def system_prompt(s, kind, screen, img):
        """`img` may be a (width, height) tuple: the screenshot only needs encoding in the worker thread."""
        sp = SYSTEM_BASE
        persona = PERSONAS.get(s.cfg.get("voice_persona", "default"), PERSONAS["default"])[1]
        if persona: sp += " Personality: " + persona + " Keep it light and short; it changes only your wording, never accuracy, action blocks, or what you report about results."
        if kind in BOARD_KINDS: sp += BOARD_DOC
        else:
            sp += "\n\n" + ACTIONS_DOC
            if s.b_scr.isChecked() or screen:
                sp += "\n\nMonitors (physical px):\n" + monitor_text(s._sc if screen else None)   # only needed for screen actions
            sp += "\nWhen the user does not name a music service, use: " + str(s.cfg.get("music_service", "spotify")) + "."
            if screen and img is not None:
                iw, ih = img if isinstance(img, tuple) else (img.width(), img.height())
                sp += (f"\n\nScreen control: ON. The attached screenshot is {iw}x{ih} px with a labelled red coordinate grid; "
                       "all x,y values use that pixel space. Aim for the centre of the target.")
            elif s.b_scr.isChecked():       # the real toggle, not whether this particular message carries a screenshot
                sp += "\n\nScreen control: ON, but no screenshot is attached to this message. Use observe {} when you need to see the screen."
            else:
                sp += "\n\nScreen control: OFF - click/move/drag/scroll/type/key/observe are unavailable. If the user wants the screen controlled, tell them to switch on the 'Screen control' button."
        mem = s.memory.prompt(1800)                 # newest facts within a smaller budget: less prompt on every turn
        if mem: sp += "\n\nLong-term memory about the user (persists across sessions):\n" + mem
        return sp + "\n\nCurrent date/time: " + time.strftime("%A %d %B %Y, %H:%M")

    def ask(s, text=None, audio=None, pix=None, screen=False, kind="chat", auto=False):
        if s.rec.stream: s.rec.stop()
        if not auto: s.speaker.stop(); s.step = 0; s.stop_ev.clear(); s.recoveries = 0; s.fail_streak = False; s.exec_lines = []; s._exec_render()
        s._last_auto = auto; s.req += 1; rid = s.req; provs = s.providers()
        if not provs:
            s.set_state("idle", "No provider"); s.partial.emit(rid, "⚠️ Add a provider + API key in ⚙ Settings → Providers."); return
        # Copy the pixmap once on the GUI thread, then scale/grid/encode in the worker: a 4K screenshot
        # used to block the UI while it was smoothly resized and base64-encoded.
        img = (pix.toImage() if hasattr(pix, "toImage") else pix) if pix is not None else None
        img_size = None
        if img is not None:
            iw = min(img.width(), 1280); ih = max(1, round(img.height() * iw / max(1, img.width())))
            img_size = (iw, ih)
        s.meta = None; s._map = None
        if screen and pix is not None and s._sc is not None:        # map screenshot px -> real screen px for clicks
            px, py, pw, ph = phys_rect(s._sc)             # physical origin of THIS monitor (correct with mixed DPI / negative offsets)
            s.meta = {"ox": px, "oy": py, "k": pw / img_size[0], "w": pw, "h": ph}
            s._map = {"mode": "screen", "sc": s._sc, **s.meta}
        elif img is not None and getattr(s, "region_rect", None) is not None:
            s._map = {"mode": "region", "rect": QRect(s.region_rect), "iw": max(1, img_size[0]), "ih": max(1, img_size[1])}
        note = text or "(spoken question)"
        if img is not None: note += " [screen attached]"
        s.pending = {"role": "user", "content": note}; s.reply = ""; s.kind = kind
        req = dict(text=text, audio=audio, img=img, kind=kind, screen=bool(screen),
                   history=trim_history(s.messages), system=s.system_prompt(kind, screen, img_size))
        s.set_state("thinking", "Thinking…")
        threading.Thread(target=s.worker, args=(rid, req, provs), daemon=True).start()
        s._watchdog_rid = rid; s._watchdog.start(int((TOTAL_TIMEOUT + 25) * 1000))

    def _request_timed_out(s):
        """Last line of defence: even if a worker thread dies in an unexpected way, the UI never stays stuck."""
        if s.state != "thinking" or s._watchdog_rid != s.req: return
        s.req += 1; s.stop_ev.set(); s._render_timer.stop(); s._stream_dirty = False
        s.out.setMarkdown("⚠️ No complete answer arrived - the request timed out. Tap Send or the microphone to try again.")
        s.out.show()
        if s._collapsed: s.expand()
        s._unstealth(); s.set_state("idle", "Request timed out - try again")

    def worker(s, rid, req, provs):
        """Always finish the request, even on an unexpected error, so the overlay cannot stay on 'Waiting'."""
        try:
            s.worker_run(rid, req, provs)
        except Exception as ex:
            if rid == s.req:
                try: s.partial.emit(rid, f"⚠️ Internal error: {str(ex)[:180]}")
                finally: s.finished.emit(rid, False)

    def worker_run(s, rid, req, provs):
        errs = []; text, audio = req["text"], req["audio"]; kind = req.get("kind", "chat")
        if audio:      # speech -> text when needed: Whisper API if configured, else Windows' built-in recognizer, else send the audio to a model that takes audio
            remote = s.cfg["stt_mode"] == "transcribe" and s.cfg["stt_key"]; native = any(p.get("audio") for p in provs)
            if remote or not native:
                try:
                    text = transcribe(s.cfg, audio) if remote else local_transcribe(audio)
                    if not text: s.partial.emit(rid, "⚠️ Didn't catch that."); s.finished.emit(rid, False); return
                    audio = None; s.heard.emit(rid, text)
                    fa = fast_media(text) or fast_intent(text)
                    if fa: s.fast.emit(rid, fa, text); return
                except Exception as ex:
                    if not native: s.partial.emit(rid, f"⚠️ I couldn't turn your speech into text ({str(ex)[:120]}). Type your request, or add a speech-to-text key in Settings → Voice."); s.finished.emit(rid, False); return
                    errs.append(f"Speech-to-text: {ex} (sending raw audio instead)")
        img = prep_image(req["img"], grid=req.get("screen")) if req["img"] is not None else None
        b64 = img_to_b64(img) if img is not None else None
        a64 = base64.b64encode(audio).decode() if audio else None
        chunker = Chunker(s.speaker.say) if s.speaker.enabled() else None
        clean = (lambda t: strip_board(strip_actions(t))) if kind in BOARD_KINDS else strip_actions
        for p in provs:
            if rid != s.req: return
            name = p["name"]
            if b64 and not p.get("vision", True): errs.append(f"{name}: no image support"); continue
            if a64 and not p.get("audio", False): errs.append(f"{name}: no audio support"); continue
            parts = [{"type": "text", "text": text or "Answer the user's spoken request in the attached audio."}]
            if b64: parts.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}})
            if a64: parts.append({"type": "input_audio", "input_audio": {"data": a64, "format": "wav"}})
            # Short voice questions do not need the default reasoning budget. Only Gemini is downgraded
            # (its thinking tokens are billed as output); long requests, screen control and whiteboards
            # keep exactly the effort the user chose.
            peffort = s.cfg.get("effort", "low")
            if (peffort == "low" and gemini_model(p) and kind == "chat" and not req.get("screen")
                    and len(text or "") < 180):
                peffort = "minimal"
            body = build_body(s.cfg, p, req["system"], req["history"], parts, kind=kind, effort=peffort)
            headers = {"X-Title": "AI Overlay"}
            if p["key"]: headers["Authorization"] = "Bearer " + p["key"]
            usage = {}
            fed = [0]
            slow = threading.Timer(1.6, lambda n=name: rid == s.req and s.note.emit(f"Waiting for {n}…")); slow.daemon = True; slow.start()
            slow2 = threading.Timer(8.0, lambda n=name: rid == s.req and s.note.emit(f"Still waiting for {n}…")); slow2.daemon = True; slow2.start()

            def on_first():
                """The first token arrived: stop the 'waiting' timers and say what is really happening."""
                slow.cancel(); slow2.cancel()
                if rid == s.req: s.note.emit("Answering…")

            def on_delta(full):
                if rid != s.req: return
                s.partial.emit(rid, full)
                if chunker and (len(full) - fed[0] >= 60 or full.rstrip().endswith((".", "!", "?"))):
                    fed[0] = len(full); chunker.feed(clean(full))

            def cut(t):
                """The first complete action block ends the reply, so actions run without waiting for the model."""
                if kind != "chat" or "```" not in t: return None
                return next((m.end() for m in ACT_RE.finditer(t) if parse_actions(m.group(0))), None)

            def opened(h, p=p):
                s.usage.rec(p, h)

            def retry(msg, delay, attempt):
                if rid != s.req: return
                if delay > 0: s.note.emit(f"{name} is busy - retrying in {delay:.0f} s ({attempt}/{MAX_ATTEMPTS})…")
                else: s.note.emit(f"{name}: {str(msg)[:80]}")

            key = (p["url"], p["model"])
            try:
                acc = stream_chat(p, body, headers, on_delta=on_delta, on_first=on_first, on_open=opened,
                                  stop=lambda: rid != s.req or s.stop_ev.is_set(), cut_at=cut, usage_out=usage,
                                  effort=peffort, on_retry=retry)
            except AIError as ex:
                if rid != s.req: return
                if ex.delay: s.cool[key] = time.time() + ex.delay          # let a healthy provider go first
                elif ex.status is not None or ex.partial: s.cool[key] = time.time() + 4.0
                if ex.status == 429: s.usage.limited(p, ex.message)
                if ex.partial:                                        # keep what arrived, explain the cut
                    s.served.emit(rid, s.usage.served(p, list(dict.fromkeys(e.split(':')[0] for e in errs if not e.startswith('Speech')))))
                    if chunker: chunker.feed(clean(ex.partial), final=True)
                    s.partial.emit(rid, ex.partial + f"\n\n⚠️ {ex.message}")
                    s.finished.emit(rid, False); return
                errs.append(f"{name}: {ex.message}"); continue
            except Exception as ex:
                errs.append(f"{name}: {str(ex)[:140]}"); continue
            finally:
                slow.cancel(); slow2.cancel(); s.usage.tokens(p, usage)
            if acc:
                s.served.emit(rid, s.usage.served(p, list(dict.fromkeys(e.split(':')[0] for e in errs if not e.startswith('Speech')))))
                if chunker and rid == s.req: chunker.feed(clean(acc), final=True)
                s.partial.emit(rid, acc); s.finished.emit(rid, True); return
            errs.append(f"{name}: empty response")
        if rid != s.req: return
        s.partial.emit(rid, "⚠️ " + "\n\n".join(errs or ["No provider answered."])); s.finished.emit(rid, False)

    def on_served(s, rid, txt):
        if rid != s.req: return
        s.srcl.setText("● " + txt); s.srcl.show()

    def on_heard(s, rid, text):
        if rid != s.req: return
        had = s.pending and "[screen attached]" in s.pending["content"]
        s.pending = {"role": "user", "content": text + (" [screen attached]" if had else "")}
        s.status.setText("“" + text[:70] + "”")

    def on_partial(s, rid, txt):
        """Every streamed token lands here. Keep it cheap: remember the text and let a 45 ms timer paint it.

        Re-parsing the whole markdown document and re-measuring the window on every token used to stall the
        GUI thread, which in turn delayed reading the next chunk from the socket."""
        if rid != s.req: return
        s.reply = txt
        if s.state == "thinking": s.set_state("idle", "Answering…")
        if s._collapsed:                                                   # never hide the answer behind the orb
            if s.kind in BOARD_KINDS: return                               # the whiteboard presents it instead
            s.expand()
        s._stream_text = txt; s._stream_dirty = True
        if not s._render_timer.isActive(): s._render_timer.start(45)

    def _flush_stream(s):
        """Paint the newest reply text at most ~22 times a second, however fast tokens arrive."""
        if not s._stream_dirty: return
        s._stream_dirty = False
        txt = s._stream_text
        view = (strip_board(txt) if s.kind in BOARD_KINDS else strip_actions(txt)).strip()
        s.out.setMarkdown(view or "…")
        if s.out.isHidden(): s.out.show()
        h = s.reply_h(view)                                                # compact bar until the reply needs more room
        if abs(s.height() - h) > 22 and time.time() - s._last_grow > 0.30:
            s._last_grow = time.time(); s.run(s.target(h), None, None, 220)
        sb = s.out.verticalScrollBar(); sb.setValue(sb.maximum())

    def on_finished(s, rid, ok):
        if rid != s.req: return
        s._watchdog.stop(); s._render_timer.stop(); s._flush_stream()
        if not ok:
            if s._collapsed and s.kind not in BOARD_KINDS: s.expand()
            s._unstealth(); s.set_state("idle", "Something went wrong"); return
        vis = (strip_board(s.reply) if s.kind in BOARD_KINDS else strip_actions(s.reply)).strip()
        acts = parse_actions(s.reply) if s.kind == "chat" else []
        if s.pending:
            tag = " [actions: " + ", ".join(str(a.get("do")) for a in acts) + "]" if acts else ""
            s.messages = (s.messages + [s.pending, {"role": "assistant", "content": (vis + tag) or "(done)"}])[-24:]
        if s.kind in BOARD_KINDS:
            steps = parse_board(s.reply)
            if steps: s.show_board(steps, s.kind)
            elif s._collapsed: s.expand()                                  # no board came back: show the text answer
        elif s._collapsed: s.expand()                                      # thinking is over: back to the full (compact) overlay
        if acts: s.handle_actions(rid, acts); return
        if s.kind == "chat" and not getattr(s, "_last_auto", False) and s.repairs < 1 and s.step < s.cfg["max_steps"] and claims_action(s.reply):
            s.repairs += 1       # it SAID it was doing something but produced no action: demand the action instead of letting it pretend
            s.follow_up("Your last reply said you were doing something on the computer, but it contained no action block, so NOTHING happened. If an action "
                        "is needed, output the action block now (one short line before it at most). If no action was needed, answer in one plain sentence and do not promise anything.", True)
            return
        s._unstealth()
        if s.isVisible() and not s._collapsed and not s._closing: s.run(s.target(s.want_h()), None, None, 220)   # settle to the final height
        s.set_state("idle", "⚠ Not completed - see above" if s.fail_streak else ("Done" if s.step else "Tap 🎤 or type to follow up"))

    def follow_up(s, msg, want_screen=False):
        s.step += 1; s.set_state("thinking", f"Step {s.step}…")
        if want_screen and s.b_scr.isChecked(): s.snap_screen(lambda pix: s.ask(text=msg, pix=pix, screen=True, auto=True))
        else: s.ask(text=msg, screen=False, auto=True)

    # --- execution status (what is really happening, shown under the reply) ---
    def _exec_render(s):
        if not s.exec_lines: s.execl.hide(); return
        col = {"run": "#8ab4f8", "wait": "#ffc66d", "ok": "#7be3c0", "fail": "#ff9aa8"}; ic = {"run": "⏳", "wait": "⏳", "ok": "✓", "fail": "✗"}
        rows = [f"<span style='color:{col[k]}'>{ic[k]}</span> {html.escape(str(m).splitlines()[0][:110] if str(m) else '')}" for k, m in s.exec_lines[:6]]
        s.execl.setText("<br>".join(rows)); s.execl.show()
        if s.isVisible() and not s._closing: s.run(s.target(s.want_h()), None, None, 160)

    def exec_begin(s, acts):
        s.exec_lines = [("run", describe(a)) for a in acts if a["do"] != "observe"]; s._exec_render()
        s.set_state("thinking", "Working: " + (s.exec_lines[0][1] if s.exec_lines else "…"))

    def exec_finish(s, results):
        s.exec_lines = [(classify(r), r) for r in results]; s._exec_render()

    def note_outcome(s, results):
        """Put the REAL outcome into the conversation history so the model never believes an action worked when it did not."""
        if s.messages and s.messages[-1]["role"] == "assistant":
            sm = "; ".join(f"{classify(r).upper()}: {str(r).splitlines()[0][:60]}" for r in results[:4])
            s.messages[-1] = {**s.messages[-1], "content": s.messages[-1]["content"] + f" [results: {sm}]"}

    def announce(s, msg):
        """The assistant speaks up on its own (failures, long tasks) - not only when answering a question."""
        if s.speaker.enabled(): s.speaker.say(msg)

    LOCAL_FINAL = ("Screen control is OFF", "user declined", "Settings is open", "stopped")

    def conclude(s, rid, results):
        s._unstealth(); dt = time.time() - s._run_t0
        kinds = [classify(r) for r in results]; bad = [r for r, k in zip(results, kinds) if k == "fail"]; wait = [r for r, k in zip(results, kinds) if k == "wait"]
        s.fail_streak = bool(bad); first = lambda r: str(r).splitlines()[0][:140]
        if any("Screen control is OFF" in r for r in results):
            msg = "That needs Screen control. Turn on the Screen control button and ask again."
            s.set_state("idle", "✗ " + msg); s.announce(msg); return
        if bad:
            s.set_state("idle", "✗ " + first(bad[0])[:100]); s.announce("I couldn't finish that. " + first(bad[0]))
        elif wait:
            s.set_state("idle", "⏳ " + first(wait[0])[:100]); s.announce("That isn't confirmed yet. " + first(wait[0]))
        else:
            s.set_state("idle", "✓ Done" + (f" in {dt:.0f}s" if dt >= 3 else ""))
            if dt >= 2.5 or (s.kind == "chat" and not strip_actions(s.reply).strip()): s.announce("Done.")

    # --- actions ---
    def handle_actions(s, rid, acts):
        acts = acts[:12]; results, ctl, look, procs, jobs = [], [], False, [], []
        for a in acts: a["do"] = str(a.get("do", "")).lower()
        acts = coalesce(acts); s._run_t0 = time.time(); login = False
        screen_on = s.b_scr.isChecked()
        if s.blocked():
            s.after(rid, ["refused: Settings is open - no automation runs while you edit settings"], False); return
        risky = [a for a in acts if a["do"] in CONTROL or a["do"] in ("close_app", "move_window", "ui_click", "ui_type")]
        if s.cfg["confirm_actions"] and risky:
            desc = "\n".join(f"• {a['do']} {json.dumps({k: v for k, v in a.items() if k != 'do'})[:80]}" for a in risky)
            if QMessageBox.question(None, "Allow actions?", "The assistant wants to:\n" + desc) != QMessageBox.StandardButton.Yes:
                s.after(rid, ["user declined the actions"], False); return
        s.exec_begin(acts)
        for a in acts:
            k = a["do"]
            if k in CONTROL:
                if screen_on: ctl.append(a)
                else: results.append(f"{k}: refused, Screen control is OFF")
            elif k == "observe":
                if a.get("monitor") and pick_screen(a["monitor"]): s.target_scr = pick_screen(a["monitor"])
                if screen_on: look = True
                else: results.append("observe: refused, Screen control is OFF")
            elif k == "open_app":
                key = _norm(str(a.get("name", "")))
                if time.time() - _RECENT_OPEN.get(key, 0) < 8: results.append(f"open_app {key}: already launching, waiting for it - do not repeat"); continue
                m = s.do_local(a)
                if classify(m) == "fail": results.append(m); continue          # launching itself failed: report it, don't pretend
                _RECENT_OPEN[key] = time.time(); procs.append(launch_proc(key))       # the verified outcome comes from wait_all
            elif k == "close_app": jobs.append(lambda a=a: (close_app(str(a.get("name", "")), s.stop_ev), False))
            elif k == "login":
                plan, err = s.login_prepare(a)
                if err: results.append(err)
                else:
                    login = True
                    jobs.append(lambda p=plan: (lambda m: (m, classify(m) == "wait" and screen_on))(s.do_login(p)))
            elif k == "spotify" and a.get("cmd") in ("ensure_playing", "play", "resume") and not a.get("query"):
                if ctl: ctl.append(a)                                              # keep order: run AFTER the clicks before it
                else: jobs.append(lambda a=a: (spotify_do(a, screen_on, s.stop_ev)[0], False))
            elif k == "spotify":
                if a.get("query") and s.sp_api().enabled(): jobs.append(lambda a=a: spotify_job(s, a, screen_on))
                else:
                    msg, pr = spotify_do(a, screen_on); results.append(msg)
                    if pr: procs.append(pr)
                    if a.get("query") and screen_on: look = True
            elif k == "youtube": jobs.append(lambda a=a: youtube_job(a, screen_on))
            elif k in ("ui_list", "ui_click", "ui_type"): jobs.append(lambda a=a: ui_job(a))
            elif k == "move_window": results.append(move_window(a.get("monitor", "secondary"), str(a.get("title", ""))))
            else: results.append(s.do_local(a))
        if procs and screen_on: look = True                                         # fresh screenshot once the app is ready
        if ctl or login:
            if ctl and pyautogui is None: results.append("control unavailable: pip install pyautogui"); s.after(rid, results, look); return
            s._refresh_screens(); s.set_state("thinking", "Working… (emergency stop: " + s.cfg["hk_stop"] + ")")
            s._stealth = True; s.hide()                            # get out of the way of clicks / typing
            threading.Thread(target=s.run_control, args=(rid, ctl, results, procs, jobs), daemon=True).start()
        elif procs or jobs:
            threading.Thread(target=s.wait_then, args=(rid, procs, results, look, jobs), daemon=True).start()
        else: s.after(rid, results, look)

    def do_local(s, a):
        k = a["do"]
        try:
            if k == "open_app": return open_app(str(a.get("name", "")))
            if k == "remember": return s.memory.add(str(a.get("text", "")))[1]
            if k == "forget": return s.memory.remove(str(a.get("text", "")))
            if k in ("plot", "draw"):
                s.show_canvas(); return s.canvas.surface.plot(a) if k == "plot" else s.canvas.surface.draw(a)
            if k == "vault_get": return s.vault_request(str(a.get("label", "") or a.get("site", "")), str(a.get("mode", "show")))
        except Exception as ex:
            return f"{k}: failed ({redact(str(ex))})"
        return f"{k}: unknown action"

    def sp_api(s):
        if getattr(s, "_sp", None) is None: s._sp = SpotifyAPI(s.cfg)
        return s._sp

    def wait_then(s, rid, procs, results, look, jobs=()):
        results.extend(wait_all(procs, s.stop_ev)); lk = run_jobs(jobs, results)
        s.launched.emit(rid, results, True if (look is True or lk is True) else (lk or False))

    def on_launched(s, rid, results, look):
        if rid != s.req: s._unstealth(); return
        if look == "text": s.after_text(rid, results)
        else: s.after(rid, results, bool(look))

    def after_text(s, rid, results):
        """Text-only continuation (UI Automation results): no screenshot, so it is much faster."""
        s.exec_finish(results); s.note_outcome(results)
        if s.step < s.cfg["max_steps"] and not s.stop_ev.is_set() and rid == s.req:
            s.follow_up("Action results:\n" + fmt_results(results) + "\nContinue, or give a short final answer with no action block if finished. Only claim success for [OK] lines.")
        else: s.conclude(rid, results)

    def run_fast(s, a, text):
        """Pure open/close/media commands skip the model: instant, and the outcome is still verified and reported."""
        s.stop_ev.clear(); s.step = 0; s.recoveries = 2; s.fail_streak = False; s.kind = "fast"        # recoveries=2: failures are reported locally, no model call; s.reply = ""; s.speaker.stop()
        s.messages = (s.messages + [{"role": "user", "content": text}, {"role": "assistant", "content": f"(running {a['do']})"}])[-24:]
        say = {"open_app": "Opening " + str(a.get("name", "")).replace("https://", "") + ".", "close_app": "Closing " + str(a.get("name", "")) + "."}.get(a["do"])
        if say: s.on_partial(s.req, say); s.announce(say)
        s.handle_actions(s.req, [dict(a)])

    def on_fast(s, rid, a, text):
        if rid == s.req: s.run_fast(a, text)

    def to_screen(s, x, y):
        m = s.meta or {"ox": 0, "oy": 0, "k": 1.0, "w": 0, "h": 0}
        px, py = m["ox"] + float(x) * m["k"], m["oy"] + float(y) * m["k"]
        if m.get("w"):          # never click outside the monitor the screenshot came from
            tol = 0.03 * max(m["w"], m["h"])
            if not (m["ox"] - tol <= px <= m["ox"] + m["w"] + tol and m["oy"] - tol <= py <= m["oy"] + m["h"] + tol):
                raise ValueError("coordinates fall outside the monitor shown in the screenshot")
            px = min(max(px, m["ox"]), m["ox"] + m["w"] - 1); py = min(max(py, m["oy"]), m["oy"] + m["h"] - 1)
        return int(px), int(py)

    def control_one(s, a):
        k = a["do"]; em = s.ai_emit
        if k == "spotify": return spotify_do(a, True, s.stop_ev)[0]
        if k == "click":
            x, y = s.to_screen(a["x"], a["y"]); glide(x, y, em)
            right = str(a.get("button", "")).lower() == "right"; em(x, y, "rclick" if right else ("dclick" if a.get("double") else "click"))
            pyautogui.click(clicks=2 if a.get("double") else 1, button="right" if right else "left")
            return f"clicked ({a['x']},{a['y']})"
        if k == "move": glide(*s.to_screen(a["x"], a["y"]), em); return "moved"
        if k == "drag":
            x1, y1 = s.to_screen(a["x1"], a["y1"]); x2, y2 = s.to_screen(a["x2"], a["y2"])
            glide(x1, y1, em); em(x1, y1, "click"); pyautogui.mouseDown(); time.sleep(0.05)
            glide(x2, y2, em, min(1.5, 0.3 + math.hypot(x2 - x1, y2 - y1) / 1500)); time.sleep(0.08); pyautogui.mouseUp()
            return f"dragged ({a['x1']},{a['y1']})→({a['x2']},{a['y2']})"
        if k == "scroll":
            glide(*s.to_screen(a.get("x", 0), a.get("y", 0)), em); pyautogui.scroll(int(float(a.get("amount", 3))) * 120); return "scrolled"
        if k == "type": keyboard.write(str(a.get("text", ""))[:2000], delay=0.01); return "typed text"
        if k == "key": keyboard.send(str(a.get("keys", ""))); return f"pressed {a.get('keys')}"
        if k == "wait": time.sleep(min(float(a.get("seconds", 1)), 5)); return "waited"
        return f"{k}: unknown"

    def run_control(s, rid, acts, results, procs=(), jobs=()):
        if procs: results.extend(wait_all(procs, s.stop_ev))
        if jobs: run_jobs(jobs, results)
        start = pyautogui.position() if pyautogui else None; last = None
        for a in acts:
            if s.stop_ev.is_set() or rid != s.req or s.blocked(): results.append("stopped"); break
            if a.get("do") in CONTROL and not wait_user_idle(s.stop_ev):          # you are typing/moving: never fight over the mouse
                results.append(f"{a.get('do')}: skipped, you were using the mouse/keyboard"); continue
            try: results.append(s.control_one(a))
            except pyautogui.FailSafeException: s.stop_ev.set(); results.append("stopped: mouse hit a screen corner (fail-safe)"); break
            except Exception as ex: results.append(f"{a.get('do')}: failed ({redact(str(ex))})")
            mark_injected(); last = pyautogui.position()
            time.sleep(0.03 if a.get("do") in ("move", "scroll") else 0.12)
        try:
            if last is not None and pyautogui.position() == last and start != last: pyautogui.moveTo(start); mark_injected()   # give the real cursor back; the AI cursor stays where it acted
        except Exception: pass
        s.acts_done.emit(rid, results)

    def on_acts_done(s, rid, results):
        if rid != s.req: s._unstealth(); return
        s.after(rid, results, True)

    def after(s, rid, results, looked):
        """After actions ran: show the REAL outcome, then either keep going (screen loop), recover from failures, or finish. Never assumes success."""
        s.exec_finish(results); s.note_outcome(results)
        can = rid == s.req and not s.stop_ev.is_set() and s.step < s.cfg["max_steps"]
        local = any(m in r for r in results for m in s.LOCAL_FINAL)
        if s.b_scr.isChecked() and looked and can and not local:
            s._unstealth()
            s.follow_up("Action results:\n" + fmt_results(results) + "\nHere is the updated screen. Continue, or give a short final answer with no action block if finished. "
                        "Only claim success for [OK] lines and for what you can actually see.", True)
            return
        failing = any(classify(r) in ("fail", "wait") for r in results)
        if failing and can and not local and s.recoveries < 2:
            s.recoveries += 1; s.fail_streak = True; s._unstealth()
            s.follow_up("Action results:\n" + fmt_results(results) + "\nDo not claim success for [FAILED] or [WAITING] lines. If there is a sensible different approach, try ONE with an "
                        "action block. Otherwise say in one sentence exactly what went wrong and what the user can do.")
            return
        s.conclude(rid, results)

    # --- vault (local only; nothing here is ever sent to a model) ---
    def login_prepare(s, a):
        """GUI thread: unlock (if needed), find the right saved login for the site, apply its policy and ask the user when required.
        -> (LoginPlan, None) or (None, result line for the model). The model never sees the username or password."""
        if Fernet is None: return None, "login failed: install the 'cryptography' package to use the vault"
        if not s.cfg.get("vault_ai", True): return None, "login refused: assistant access to saved logins is turned off (Settings > Data)"
        if not s.vault.exists(): return None, "login failed: there is no vault yet - create one in Settings > Data > Secure vault"
        site = str(a.get("site", "")).strip(); label = str(a.get("label", "")).strip(); url = title = None
        bw = find_browser()
        if bw:
            title = bw[1]
            if not site and not label and uia is not None:
                try: url = UiaPage(bw[0]).url() or None
                except Exception: url = None
        got = vault_unlock(s.vault, f"The assistant wants to sign in to {site or label or 'the open website'}.")
        if not got: return None, "login cancelled by the user (the vault stayed locked)"
        key, entries = got
        cands = match_site(entries, site or None, label or None, url, None if (site or label) else title)
        if not cands: return None, f"login failed: no saved login for {site or label or 'this website'}. Add it in Settings > Data > Secure vault"
        top = [n for n, sc in cands if sc == cands[0][1]]
        if len(top) > 1:
            name, ok = QInputDialog.getItem(None, "Which account?", "Several saved logins match. Use which one?", sorted(top), 0, False)
            if not ok: return None, "login cancelled by the user"
        else: name = top[0]
        e = entries[name]; pol = e.get("ai", "ask"); disp = (entry_sites(name, e) or [name])[0]
        if pol == "never": return None, f"login refused: “{name}” is set to manual only"
        if pol != "auto":
            box = QMessageBox(QMessageBox.Icon.Question, "Allow sign-in?", f"The assistant wants to sign in to {disp}\nusing the saved login “{name}” ({mask_user(e.get('user', ''))}).")
            box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint); cb = QCheckBox("Don't ask again for this login"); box.setCheckBox(cb)
            yes = box.addButton("Allow", QMessageBox.ButtonRole.AcceptRole); box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole); box.exec()
            if box.clickedButton() is not yes: return None, "login cancelled by the user"
            if cb.isChecked():
                entries[name]["ai"] = "auto"
                try: s.vault.write(key, entries)
                except Exception: pass
        return LoginPlan(name, disp, e.get("login_url", ""), e.get("user", ""), e.get("secret", ""), title or ""), None

    def do_login(s, plan):
        def ask_user(msg):
            return bool(s.call_gui(lambda: QMessageBox.information(None, "Sign in", msg, QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Ok))
        return run_login(plan, s.stop_ev, s.note.emit, ask_user, s.vault)

    def vault_request(s, label, mode):
        mode = mode if mode in ("show", "copy", "type") else "show"
        if Fernet is None: return "vault_get failed: install the 'cryptography' package"
        if not s.cfg.get("vault_ai", True): return "vault_get refused: assistant access to saved logins is turned off"
        if not s.vault.exists(): return "vault_get failed: there is no vault yet (Settings > Data > Secure vault)"
        got = vault_unlock(s.vault, f"The assistant asked for “{label[:40]}”.")
        if not got: return "vault_get cancelled by the user"
        key, entries = got
        if not entries: return "vault_get failed: the vault is empty"
        name = match_label(entries, label)
        if name is None:
            m = match_site(entries, site=label, label=label)
            name = m[0][0] if m and (len(m) == 1 or m[0][1] > m[1][1]) else None
        if name is None:
            name, ok = QInputDialog.getItem(None, "Vault", "Which entry?", sorted(entries), 0, False)
            if not ok: return "vault_get cancelled by the user"
        e = entries[name]; secret = e.get("secret", "")
        if e.get("ai", "ask") == "never": return f"vault_get refused: “{name}” is set to manual only"
        if mode == "copy":
            secure_copy(secret); s.note.emit(f"Copied the secret for “{name}” (clipboard clears in 20 s)")
            return f"copied the secret for “{name}” to the clipboard for the user (you cannot see it)"
        if mode == "type":
            s.note.emit(f"Click the target field - typing “{name}” in 4 s…")

            def typer():
                if not foreground_is_foreign(): s.note.emit("Not typed: focus was on the assistant itself."); return
                keyboard.write(secret, delay=0.01)
            QTimer.singleShot(4000, lambda: threading.Thread(target=typer, daemon=True).start())
            return f"will type the secret for “{name}” into the field the user clicks (unverified, you cannot see it)"
        d = QMessageBox(QMessageBox.Icon.Information, "Vault - " + name, f"Username: {e.get('user', '')}\nPassword: ••••••••\n\nNote: {e.get('note', '')}")
        d.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint); rv = d.addButton("Reveal for 10 s", QMessageBox.ButtonRole.ActionRole)
        cp = d.addButton("Copy", QMessageBox.ButtonRole.ActionRole); d.addButton("Close", QMessageBox.ButtonRole.RejectRole); d.exec()
        if d.clickedButton() is rv:
            d2 = QMessageBox(QMessageBox.Icon.Information, "Vault - " + name, f"Username: {e.get('user', '')}\nPassword: {secret}\n\n(closes automatically in 10 s)")
            d2.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint); QTimer.singleShot(10000, d2.close); d2.exec()
        elif d.clickedButton() is cp: secure_copy(secret); s.note.emit("Copied (clipboard clears in 20 s)")
        return f"showed “{name}” to the user locally (you cannot see it)"

# One flat namespace across the package (it was split out of a single file); exporting
# everything, including the private helpers, keeps the behaviour identical.
__all__ = [n for n in globals() if not n.startswith('__')]
