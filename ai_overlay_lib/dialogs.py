"""Settings and local data dialogs (providers, memory, vault, preferences)."""
from .core import *
from .accounts import *
from .system import *
from .voice import *
from .connectors import *
from .orb_animation import AIOrb
from PyQt6.QtWidgets import QSlider

# ---------- settings / data dialogs ----------
DARK = """
    QDialog{background:#202124} QLabel,QCheckBox{color:#e8eaed;font:13px 'Segoe UI'}
    QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox,QListWidget{background:#303134;color:#e8eaed;border:1px solid #3c4043;border-radius:8px;padding:6px;font:13px 'Segoe UI'}
    QPushButton{background:#303134;color:#e8eaed;border:none;border-radius:8px;padding:7px 14px;font:13px 'Segoe UI'}
    QPushButton:hover{background:#3c4043} QPushButton#save{background:#3b5bdb}
    QTabWidget::pane{border:1px solid #3c4043;border-radius:8px} QTabBar::tab{background:#303134;color:#e8eaed;padding:7px 14px;border-radius:6px;margin:2px}
    QTabBar::tab:selected{background:#3b5bdb}"""


class ProviderDialog(QDialog):
    def __init__(s, p=None, parent=None):
        super().__init__(parent); s.setWindowTitle("Model provider"); s.setMinimumWidth(560); s.setStyleSheet(SETTINGS_QSS); s.result_p = None; s.pid = (p or {}).get("id")
        f = QFormLayout(s)
        s.preset = QComboBox(); s.preset.addItems(list(PRESETS))
        s.name = QLineEdit(); s.url = QLineEdit(); s.url.setPlaceholderText("https://…/v1/chat/completions (OpenAI-compatible)")
        s.key = QLineEdit(); s.key.setEchoMode(QLineEdit.EchoMode.Password); s.key.setPlaceholderText("API key (leave empty for local servers)")
        s.model = QLineEdit(); s.extra = QLineEdit(); s.extra.setPlaceholderText('extra request fields as JSON, e.g. {"temperature":0.4}')
        s.vision = QCheckBox("Accepts images"); s.audio = QCheckBox("Accepts audio input"); s.enabled = QCheckBox("Enabled")
        f.addRow("Preset", s.preset); f.addRow("Name", s.name); f.addRow("Chat URL", s.url); f.addRow("API key", s.key)
        s.daily = QSpinBox(); s.daily.setRange(0, 1000000); s.daily.setSpecialValueText("unknown")
        s.daily.setToolTip("Your free daily request quota. Used to show how many requests are left (Groq reports it automatically).")
        f.addRow("Model", s.model); f.addRow("Daily request limit", s.daily); f.addRow("Extra JSON", s.extra); f.addRow("", s.vision); f.addRow("", s.audio); f.addRow("", s.enabled)
        bar = QHBoxLayout(); c = QPushButton("Cancel"); ok = QPushButton("OK"); ok.setObjectName("save"); bar.addStretch(); bar.addWidget(c); bar.addWidget(ok); f.addRow(bar)
        c.clicked.connect(s.reject); ok.clicked.connect(s.accept)
        if p:
            s.preset.blockSignals(True); s.preset.setCurrentText(p["name"] if p["name"] in PRESETS else "Custom"); s.preset.blockSignals(False)
            s.name.setText(p["name"]); s.url.setText(p["url"]); s.key.setText(p["key"]); s.model.setText(p["model"])
            s.extra.setText(json.dumps(p.get("extra") or {})); s.vision.setChecked(p.get("vision", True))
            s.audio.setChecked(p.get("audio", False)); s.enabled.setChecked(p.get("enabled", True)); s.daily.setValue(int(p.get("daily_limit", 0)))
        else: s.fill(s.preset.currentText())
        s.preset.currentTextChanged.connect(s.fill)

    def fill(s, n):
        pr = PRESETS[n]; s.name.setText(n if n != "Custom" else ""); s.url.setText(pr["url"]); s.model.setText(pr["model"])
        s.extra.setText(json.dumps(pr["extra"])); s.vision.setChecked(pr["vision"]); s.audio.setChecked(pr["audio"]); s.enabled.setChecked(True); s.daily.setValue(pr.get("daily_limit", 0))

    def accept(s):
        try:
            extra = json.loads(s.extra.text().strip() or "{}")
            if not isinstance(extra, dict): raise ValueError("must be a JSON object")
        except ValueError as ex: QMessageBox.warning(s, "Provider", f"Extra JSON is invalid: {ex}"); return
        if not s.url.text().strip().startswith("http") or not s.model.text().strip():
            QMessageBox.warning(s, "Provider", "A chat URL (http…) and a model name are required."); return
        s.result_p = {"id": s.pid or uuid.uuid4().hex,
                      "name": s.name.text().strip() or "Custom", "url": s.url.text().strip(), "key": s.key.text().strip(),
                      "model": s.model.text().strip(), "extra": extra, "vision": s.vision.isChecked(),
                      "audio": s.audio.isChecked(), "enabled": s.enabled.isChecked(), "daily_limit": s.daily.value()}
        super().accept()


class MemoryPanel(QWidget):
    """Browse / search / edit / export the assistant's long-term memory (memory.json)."""

    def __init__(s, mem, parent=None):
        super().__init__(parent); s.mem = mem; s._sig = None
        lay = QVBoxLayout(s); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(10)
        top = QHBoxLayout(); s.count = QLabel(); s.count.setObjectName("h2"); top.addWidget(s.count); top.addStretch()
        s.search = QLineEdit(); s.search.setPlaceholderText("Search memories…"); s.search.setClearButtonEnabled(True); s.search.setMinimumWidth(220)
        top.addWidget(s.search); lay.addLayout(top)
        s.bar = QProgressBar(); s.bar.setRange(0, 100); s.bar.setTextVisible(False); s.bar.setFixedHeight(8); lay.addWidget(s.bar)
        s.budget = QLabel(); s.budget.setObjectName("hint"); s.budget.setWordWrap(True); lay.addWidget(s.budget)
        s.lst = QListWidget(); s.lst.setMinimumHeight(250); s.lst.setSpacing(2); s.lst.setWordWrap(True)
        s.lst.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection); lay.addWidget(s.lst, 1)
        row = QHBoxLayout(); s.new = QLineEdit(); s.new.setPlaceholderText("Add something for the assistant to remember…")
        s.b_add = QPushButton("Add"); s.b_add.setObjectName("save"); row.addWidget(s.new, 1); row.addWidget(s.b_add); lay.addLayout(row)
        row = QHBoxLayout(); s.b_edit = QPushButton("Edit"); s.b_del = QPushButton("Delete"); s.b_exp = QPushButton("Export…"); s.b_clr = QPushButton("Clear all")
        s.b_clr.setObjectName("danger")
        for b in (s.b_edit, s.b_del, s.b_exp): row.addWidget(b)
        row.addStretch(); row.addWidget(s.b_clr); lay.addLayout(row)
        n = QLabel("Stored in memory.json - not encrypted. Passwords and keys are refused here; use the secure vault for secrets.")
        n.setObjectName("hint"); n.setWordWrap(True); lay.addWidget(n)
        for b in s.findChildren(QPushButton): b.setAutoDefault(False)
        s.search.textChanged.connect(lambda _: s.refresh()); s.b_add.clicked.connect(s.add); s.new.returnPressed.connect(s.add)
        s.b_edit.clicked.connect(s.edit); s.lst.itemDoubleClicked.connect(lambda _: s.edit()); s.b_del.clicked.connect(s.delete)
        s.b_exp.clicked.connect(s.export); s.b_clr.clicked.connect(s.clear_all); s.lst.itemSelectionChanged.connect(s._buttons)
        s.poll = QTimer(s); s.poll.timeout.connect(s._poll); s.poll.start(1500)       # the assistant can add/forget items while this is open
        s.refresh()

    def _signature(s): return (len(s.mem.items), hash(tuple(i["text"] for i in s.mem.items)))

    def _poll(s):
        if s.isVisible() and s._signature() != s._sig: s.refresh()

    def showEvent(s, e): s.refresh(); super().showEvent(e)

    def _buttons(s):
        n = len(s.lst.selectedItems()); s.b_edit.setEnabled(n == 1); s.b_del.setEnabled(n >= 1)

    def refresh(s):
        keep = {it.data(Qt.ItemDataRole.UserRole) for it in s.lst.selectedItems()}
        total, inc, used, limit = s.mem.stats(); q = s.search.text().strip().lower(); s._sig = s._signature()
        s.lst.clear(); first_sent = total - inc
        for idx, it in enumerate(s.mem.items):
            if q and q not in it["text"].lower(): continue
            ts = it.get("ts"); date = time.strftime("%b %d, %Y", time.localtime(ts)) if ts else "unknown date"
            note = "" if idx >= first_sent else "  ·  ⚠ not sent to the model (over budget)"
            li = QListWidgetItem(f"{it['text']}\n{date}{note}"); li.setData(Qt.ItemDataRole.UserRole, idx); s.lst.addItem(li)
            if idx in keep: li.setSelected(True)
        s.count.setText(f"{total} memor{'y' if total == 1 else 'ies'}" + (f"  ·  {s.lst.count()} shown" if q else ""))
        s.bar.setValue(min(100, int(used * 100 / limit))); s.budget.setText(
            f"{used} / {limit} characters of the prompt budget used." + (f" The oldest {total - inc} won't be sent to the model." if inc < total else ""))
        s._buttons()

    def _selected_idx(s): return sorted(it.data(Qt.ItemDataRole.UserRole) for it in s.lst.selectedItems())

    def add(s):
        if not s.new.text().strip(): return
        ok, msg = s.mem.add(s.new.text())
        if not ok: QMessageBox.warning(s, "Memory", msg); return
        s.new.clear(); s.refresh(); s.lst.scrollToBottom()

    def edit(s):
        idx = s._selected_idx()
        if len(idx) != 1: return
        cur = s.mem.items[idx[0]]["text"]
        text, ok = QInputDialog.getText(s, "Edit memory", "Memory:", QLineEdit.EchoMode.Normal, cur)
        if not ok: return
        done, msg = s.mem.edit(idx[0], text)
        if not done: QMessageBox.warning(s, "Memory", msg)
        s.refresh()

    def delete(s):
        for i in reversed(s._selected_idx()): s.mem.remove_index(i)
        s.refresh()

    def clear_all(s):
        if s.mem.items and QMessageBox.question(s, "Clear memory", f"Delete all {len(s.mem.items)} memories? This can't be undone.") == QMessageBox.StandardButton.Yes:
            s.mem.clear(); s.refresh()

    def export(s):
        path, _ = QFileDialog.getSaveFileName(s, "Export memory", "memory_export.json", "JSON (*.json)")
        if path:
            try: s.mem.export(path)
            except Exception as ex: QMessageBox.warning(s, "Memory", f"Export failed: {ex}")


class MemoryDialog(QDialog):
    def __init__(s, mem, parent=None):
        super().__init__(parent); s.setWindowTitle("Long-term memory"); s.setMinimumSize(560, 520); s.setStyleSheet(SETTINGS_QSS)
        lay = QVBoxLayout(s); lay.addWidget(MemoryPanel(mem))


class VaultDialog(QDialog):
    POL = [("Ask me each time", "ask"), ("Automatically while the vault is unlocked", "auto"), ("Never - manual only", "never")]

    def __init__(s, vault, key, entries):
        super().__init__(); s.vault, s.key, s.entries, s.cur = vault, key, entries, None
        s.setWindowTitle("Secure vault"); s.setMinimumSize(800, 540); s.setStyleSheet(SETTINGS_QSS)
        root = QVBoxLayout(s); body = QHBoxLayout(); body.setSpacing(16); root.addLayout(body, 1)
        left = QVBoxLayout(); s.search = QLineEdit(); s.search.setPlaceholderText("Search logins…"); s.lst = QListWidget(); s.lst.setMinimumWidth(250)
        new = QPushButton("＋ New login"); left.addWidget(s.search); left.addWidget(s.lst, 1); left.addWidget(new); body.addLayout(left)
        right = QVBoxLayout(); f = QFormLayout(); f.setVerticalSpacing(10)
        s.label = QLineEdit(); s.label.setPlaceholderText("A name you will recognise, e.g. GitHub")
        s.site = QLineEdit(); s.site.setPlaceholderText("github.com   (several allowed, separated by commas)"); use = QPushButton("Use open website"); use.setToolTip("Reads the address of the website open in your browser")
        srow = QHBoxLayout(); srow.addWidget(s.site, 1); srow.addWidget(use)
        s.url = QLineEdit(); s.url.setPlaceholderText("Optional: the sign-in page, e.g. https://github.com/login")
        s.user = QLineEdit(); s.secret = QLineEdit(); s.secret.setEchoMode(QLineEdit.EchoMode.Password)
        show = QCheckBox("Show"); gen = QPushButton("Generate"); prow = QHBoxLayout(); prow.addWidget(s.secret, 1); prow.addWidget(show); prow.addWidget(gen)
        s.pol = QComboBox()
        for lbl, v in s.POL: s.pol.addItem(lbl, v)
        s.note = QLineEdit(); s.last = QLabel(""); s.last.setObjectName("hint")
        for lbl, w in (("Name", s.label), ("Website", srow), ("Sign-in page", s.url), ("Username / email", s.user), ("Password", prow), ("Assistant may sign in", s.pol), ("Note", s.note), ("", s.last)):
            f.addRow(lbl, w)
        right.addLayout(f); right.addWidget(hint_label("The assistant never sees the username or password: it only asks this app to sign in, and this app types them locally. "
                                                         "Two-step codes and captchas are always left to you."))
        row = QHBoxLayout(); sv = QPushButton("Save login"); sv.setObjectName("save"); dl = QPushButton("Delete"); dl.setObjectName("danger"); row.addWidget(sv); row.addWidget(dl); row.addStretch()
        right.addLayout(row); right.addStretch(1); body.addLayout(right, 1)
        bot = QHBoxLayout(); chg = QPushButton("Change master password"); cl = QPushButton("Lock && close"); cl.setObjectName("save"); bot.addWidget(chg); bot.addStretch(); bot.addWidget(cl); root.addLayout(bot)
        show.toggled.connect(lambda on: s.secret.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        gen.clicked.connect(s.generate); use.clicked.connect(s.use_open_site); new.clicked.connect(s.new); sv.clicked.connect(s.save); dl.clicked.connect(s.delete)
        chg.clicked.connect(s.change_pw); cl.clicked.connect(s.lock_close); s.search.textChanged.connect(lambda _: s.refresh()); s.lst.currentItemChanged.connect(lambda it, _: s.pick(it))
        for b in s.findChildren(QPushButton): b.setAutoDefault(False)
        s.idle = QTimer(s); s.idle.setSingleShot(True); s.idle.timeout.connect(s.lock_close); s.idle.start(180000)      # auto-lock after 3 quiet minutes
        s.refresh()

    def _touch(s): s.idle.start(180000)

    def refresh(s, select=None):
        q = s.search.text().strip().lower(); s.lst.blockSignals(True); s.lst.clear()
        for n in sorted(s.entries, key=str.lower):
            e = s.entries[n]; sites = ", ".join(entry_sites(n, e))
            if q and q not in n.lower() and q not in sites: continue
            mark = {"ok": "  ✓", "failed": "  ⚠"}.get(e.get("last_result", ""), "")
            it = QListWidgetItem(f"🌐  {n}" + (f"   ·   {sites}" if sites else "") + mark); it.setData(Qt.ItemDataRole.UserRole, n); s.lst.addItem(it)
            if n == select: s.lst.setCurrentItem(it)
        s.lst.blockSignals(False)

    def new(s):
        s.cur = None; s.lst.clearSelection()
        for w in (s.label, s.site, s.url, s.user, s.secret, s.note): w.clear()
        s.pol.setCurrentIndex(0); s.last.setText(""); s.label.setFocus(); s._touch()

    def pick(s, item):
        if item is None: return
        n = item.data(Qt.ItemDataRole.UserRole); e = s.entries.get(n)
        if not e: return
        s.cur = n; s.label.setText(n); s.site.setText(e.get("site", "")); s.url.setText(e.get("login_url", "")); s.user.setText(e.get("user", ""))
        s.secret.setText(e.get("secret", "")); s.note.setText(e.get("note", "")); s.pol.setCurrentIndex(max(0, s.pol.findData(e.get("ai", "ask"))))
        lr = e.get("last_result", ""); lu = e.get("last_used")
        s.last.setText((("✓ Last sign-in worked" if lr == "ok" else "⚠ Last sign-in was rejected - check the password") + (" · " + time.strftime("%d %b %H:%M", time.localtime(lu)) if lu else "")) if lr else "")
        s._touch()

    def generate(s):
        alpha = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%^&*-_"
        s.secret.setText("".join(secrets.choice(alpha) for _ in range(20))); s.secret.setEchoMode(QLineEdit.EchoMode.Normal); s._touch()

    def use_open_site(s):
        bw = find_browser(); url = ""
        if bw and uia is not None:
            try: url = UiaPage(bw[0]).url()
            except Exception: url = ""
        k = site_key(url) if url else ""
        if not k: QMessageBox.information(s, "Vault", "I couldn't read the address of the open website. Type it in the Website box (for example github.com)."); return
        s.site.setText(k)
        if not s.label.text().strip(): s.label.setText(k.split(".")[0].capitalize())
        s._touch()

    def save(s):
        n = s.label.text().strip()
        if not n: QMessageBox.information(s, "Vault", "Give the login a name first."); return
        if n != s.cur and n in s.entries and QMessageBox.question(s, "Vault", f"“{n}” already exists. Replace it?") != QMessageBox.StandardButton.Yes: return
        old = s.entries.get(s.cur or n, {})
        if s.cur and s.cur != n: s.entries.pop(s.cur, None)
        s.entries[n] = {**old, "site": s.site.text().strip(), "login_url": s.url.text().strip(), "user": s.user.text(), "secret": s.secret.text(),
                        "note": s.note.text(), "ai": s.pol.currentData(), "created": old.get("created", int(time.time()))}
        try: s.vault.write(s.key, s.entries)
        except Exception as ex: QMessageBox.warning(s, "Vault", f"Couldn't save: {ex}"); return
        s.cur = n; s.refresh(n); s._touch()

    def delete(s):
        n = s.cur or s.label.text().strip()
        if n in s.entries and QMessageBox.question(s, "Vault", f"Delete the login “{n}”?") == QMessageBox.StandardButton.Yes:
            del s.entries[n]; s.vault.write(s.key, s.entries); s.new(); s.refresh()

    def change_pw(s):
        pw = ask_password("Change master password", "Choose a new master password (min. 10 characters).\nIt cannot be recovered if you forget it.", confirm=True, min_len=10)
        if pw:
            try: s.key = s.vault.rekey(s.entries, pw); QMessageBox.information(s, "Vault", "Master password changed.")
            except Exception as ex: QMessageBox.warning(s, "Vault", f"Couldn't change it: {ex}")

    def lock_close(s): s.vault.lock_now(); s.accept()


def open_vault_manager(vault):
    if Fernet is None: QMessageBox.warning(None, "Vault", "Install the 'cryptography' package:  pip install cryptography"); return
    if not vault.exists():
        pw = ask_password("Create vault", "Choose a master password (min. 10 characters).\nIt cannot be recovered if you forget it.", confirm=True, min_len=10)
        if not pw: return
        key, entries = vault.create(pw), {}
    else:
        got = vault_unlock(vault, "Open the secure vault.")
        if not got: return
        key, entries = got
    VaultDialog(vault, key, entries).exec()


SETTINGS_QSS = """
    QDialog{background:qlineargradient(x1:0,y1:0,x2:0.55,y2:1,stop:0 #15171e,stop:0.55 #101217,stop:1 #0c0e13)}
    QLabel,QCheckBox{color:#e7eaf3;font:13px 'Segoe UI'}
    QLabel#brand{font:700 19px 'Segoe UI';color:#fff} QLabel#ver{color:#717a90;font:11px 'Segoe UI'}
    QLabel#h1{font:700 25px 'Segoe UI';color:#fff} QLabel#sub{color:#8b93a7;font:13px 'Segoe UI'}
    QLabel#h2{font:600 14px 'Segoe UI';color:#fff} QLabel#hint{color:#8b93a7;font:12px 'Segoe UI'}
    QLabel#preview_title{color:#cfd6ea;font:600 12px 'Segoe UI'}
    QFrame#side{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #12141b,stop:1 #0b0d12);border:1px solid #1e2230;border-radius:18px}
    QFrame#card{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #1a1d26,stop:1 #161922);border:1px solid #272c3a;border-radius:16px}
    QFrame#card:hover{border:1px solid #323949}
    QFrame#sep{background:#202533;border:none}
    #nav{background:transparent;border:none;outline:0}
    #nav::item{color:#a9b1c6;padding:11px 14px;border-radius:10px;margin:1px 0;font:13px 'Segoe UI'}
    #nav::item:hover:!selected{background:#191d27;color:#e7eaf3}
    #nav::item:selected{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #26305a,stop:1 #1c2240);color:#fff}
    QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox{background:#0f1117;color:#e7eaf3;border:1px solid #2b303e;border-radius:10px;padding:8px 12px;font:13px 'Segoe UI';selection-background-color:#5b7cfa;min-height:18px}
    QLineEdit:hover,QComboBox:hover,QDoubleSpinBox:hover,QSpinBox:hover{border:1px solid #3a4152}
    QLineEdit:focus,QComboBox:focus,QDoubleSpinBox:focus,QSpinBox:focus{border:1px solid #6f8cff;background:#11141c}
    QLineEdit:disabled,QComboBox:disabled,QSpinBox:disabled,QDoubleSpinBox:disabled{color:#5c6478;background:#0c0e13;border-color:#20242f}
    QLineEdit:read-only{color:#c9d1ff}
    QComboBox::drop-down{border:none;width:28px}
    QComboBox QAbstractItemView{background:#191d27;color:#e7eaf3;border:1px solid #2b303e;border-radius:10px;selection-background-color:#2c3560;selection-color:#fff;outline:0;padding:5px}
    QCheckBox::indicator{width:18px;height:18px;border-radius:5px;border:1px solid #3a4152;background:#0f1117}
    QCheckBox::indicator:hover{border-color:#6f8cff}
    QCheckBox::indicator:checked{background:#5b7cfa;border-color:#6f8cff}
    QPushButton{background:#222634;color:#e7eaf3;border:1px solid #2f3546;border-radius:10px;padding:8px 16px;font:13px 'Segoe UI'}
    QPushButton:hover{background:#2b3140;border-color:#3a4256} QPushButton:pressed{background:#1c202c}
    QPushButton:disabled{color:#596177;background:#171a22;border-color:#232734}
    QPushButton#save{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #5b7cfa,stop:1 #8b6cff);border:none;color:#fff;font:600 13px 'Segoe UI';padding:9px 26px}
    QPushButton#save:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #6f8cff,stop:1 #9a7dff)}
    QPushButton#ghost{background:transparent;border:none;color:#a9b1c6} QPushButton#ghost:hover{color:#fff;background:#1a1e28}
    QPushButton#danger{background:#4a2428;border:1px solid #6b2f35} QPushButton#danger:hover{background:#63303a}
    QListWidget{background:#0f1117;color:#e7eaf3;border:1px solid #2b303e;border-radius:12px;padding:5px;font:13px 'Segoe UI'}
    QListWidget::item{padding:8px 10px;border-radius:8px} QListWidget::item:hover{background:#191d27} QListWidget::item:selected{background:#2c3560;color:#fff}
    QSlider::groove:horizontal{height:5px;background:#262b39;border-radius:3px}
    QSlider::sub-page:horizontal{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #5b7cfa,stop:1 #8b6cff);border-radius:3px}
    QSlider::handle:horizontal{width:16px;height:16px;margin:-6px 0;border-radius:8px;background:#eef1ff;border:2px solid #5b7cfa}
    QSlider::handle:horizontal:hover{background:#fff;border-color:#8b6cff}
    QProgressBar{background:#262a37;border:none;border-radius:4px;max-height:8px} QProgressBar::chunk{background:#5b7cfa;border-radius:4px}
    QScrollArea{background:transparent}
    QScrollBar:vertical{background:transparent;width:10px;margin:2px} QScrollBar::handle:vertical{background:#303546;border-radius:5px;min-height:30px}
    QScrollBar::handle:vertical:hover{background:#41475c} QScrollBar::add-line,QScrollBar::sub-line{height:0}
    QToolTip{background:#1b1e27;color:#e7eaf3;border:1px solid #2b303e;padding:6px}"""


PAGE_SUB = {"General": "Behavior, music and hotkeys", "Providers": "The AI models the assistant can use", "API keys": "Keys for voice and online services",
            "Voice": "How the assistant speaks and when it listens", "Display": "Where the overlay appears", "Memory": "What the assistant remembers about you",
            "Data": "Your files, vault and updates", "Connections": "Link apps, see their messages here and reply from the overlay"}


def mk_card(title, hint=None):
    f = QFrame(); f.setObjectName("card"); v = QVBoxLayout(f); v.setContentsMargins(22, 18, 22, 20); v.setSpacing(14)
    t = QLabel(title); t.setObjectName("h2"); v.addWidget(t)
    if hint: h = QLabel(hint); h.setObjectName("hint"); h.setWordWrap(True); v.addWidget(h)
    form = QFormLayout(); form.setHorizontalSpacing(24); form.setVerticalSpacing(14); form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow); v.addLayout(form)
    return f, form, v


def mk_page(title, *cards):
    sa = QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    inner = QWidget(); v = QVBoxLayout(inner); v.setContentsMargins(8, 4, 12, 18); v.setSpacing(18)
    h = QLabel(title); h.setObjectName("h1"); v.addWidget(h)
    if title in PAGE_SUB: sub = QLabel(PAGE_SUB[title]); sub.setObjectName("sub"); v.addWidget(sub); v.addSpacing(6)
    for c in cards: v.addWidget(c)
    v.addStretch(); sa.setWidget(inner); sa.viewport().setAutoFillBackground(False); inner.setAutoFillBackground(False)
    return sa


class Switch(QCheckBox):
    """Modern on/off toggle that replaces the plain checkbox."""
    def __init__(s, text=""): super().__init__(text); s.setCursor(Qt.CursorShape.PointingHandCursor); s.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    def sizeHint(s): return QSize(50 + (s.fontMetrics().horizontalAdvance(s.text()) + 12 if s.text() else 0), 28)
    def hitButton(s, pos): return s.rect().contains(pos)
    def enterEvent(s, e): s.update(); super().enterEvent(e)
    def leaveEvent(s, e): s.update(); super().leaveEvent(e)

    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHint(QPainter.RenderHint.Antialiasing); on = s.isChecked(); h = s.height()
        track = QRectF(0, (h - 22) / 2, 42, 22)
        if on:
            g = QLinearGradient(track.topLeft(), track.topRight())
            g.setColorAt(0, QColor("#5b7cfa")); g.setColorAt(1, QColor("#8b6cff"))
            p.setBrush(g)
        else:
            p.setBrush(QColor("#3b4152" if s.underMouse() else "#323747"))
        p.setPen(Qt.PenStyle.NoPen); p.drawRoundedRect(track, 11, 11)
        knob = QRectF(22 if on else 2, (h - 18) / 2, 18, 18)
        p.setBrush(QColor(0, 0, 0, 40)); p.drawEllipse(knob.translated(0, 1))
        p.setBrush(QColor("#ffffff")); p.drawEllipse(knob)
        if s.text():
            p.setPen(QColor("#e7eaf3" if s.isEnabled() else "#5c6478")); p.setFont(s.font())
            p.drawText(QRectF(52, 0, s.width() - 52, h), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), s.text())


class SliderField(QWidget):
    """A slider with an inline value readout; keeps the same value()/setValue() API as a spin box."""
    valueChanged = pyqtSignal(float)

    def __init__(s, lo, hi, step=1, suffix="", scale=1, width=160):
        super().__init__()
        h = QHBoxLayout(s); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(12)
        s.scale = scale; s.suffix = suffix
        s.sl = QSlider(Qt.Orientation.Horizontal); s.sl.setRange(lo, hi); s.sl.setSingleStep(step); s.sl.setPageStep(max(step, (hi - lo) // 10))
        s.sl.setMinimumWidth(width); s.sl.setCursor(Qt.CursorShape.PointingHandCursor)
        s.val = QLabel(""); s.val.setObjectName("hint"); s.val.setMinimumWidth(62); s.val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(s.sl, 1); h.addWidget(s.val)
        s.sl.valueChanged.connect(s._changed)
        s._changed(s.sl.value())

    def _changed(s, v):
        s.val.setText((f"{v / s.scale:.1f}" if s.scale != 1 else f"{v:,}") + s.suffix)
        s.valueChanged.emit(v / s.scale if s.scale != 1 else v)

    def value(s): return s.sl.value() / s.scale if s.scale != 1 else s.sl.value()

    def setValue(s, v):
        s.sl.blockSignals(True); s.sl.setValue(int(round(float(v) * s.scale))); s.sl.blockSignals(False)
        s._changed(s.sl.value())


def hint_label(text):
    l = QLabel(text); l.setObjectName("hint"); l.setWordWrap(True); return l


class SecretEdit(QWidget):
    """API-key field: hidden by default, Show/Hide toggle."""
    def __init__(s, placeholder="Paste API key"):
        super().__init__(); h = QHBoxLayout(s); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
        s.e = QLineEdit(); s.e.setEchoMode(QLineEdit.EchoMode.Password); s.e.setPlaceholderText(placeholder)
        s.b = QPushButton("Show"); s.b.setCheckable(True); s.b.setFixedWidth(64); s.b.setAutoDefault(False)
        s.b.toggled.connect(lambda on: (s.e.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password), s.b.setText("Hide" if on else "Show")))
        h.addWidget(s.e, 1); h.addWidget(s.b)

    def text(s): return s.e.text().strip()
    def setText(s, t): s.e.setText(t or "")


class HotkeyEdit(QLineEdit):
    """Captures a shortcut with Qt key events (no global keyboard hook, so keys are never forwarded to other apps)."""
    captured = pyqtSignal(str)
    rec = False; _prev = ""   # class defaults: Qt calls event() during super().__init__(), before instance attributes exist
    K = Qt.Key
    NAMES = {K.Key_Space.value: "space", K.Key_Return.value: "enter", K.Key_Enter.value: "enter", K.Key_Tab.value: "tab",
             K.Key_Backspace.value: "backspace", K.Key_Delete.value: "delete", K.Key_Insert.value: "insert", K.Key_Home.value: "home",
             K.Key_End.value: "end", K.Key_PageUp.value: "page up", K.Key_PageDown.value: "page down", K.Key_Up.value: "up",
             K.Key_Down.value: "down", K.Key_Left.value: "left", K.Key_Right.value: "right"}
    MODS = {K.Key_Control.value, K.Key_Shift.value, K.Key_Alt.value, K.Key_Meta.value, K.Key_AltGr.value, K.Key_unknown.value}

    def __init__(s): super().__init__(); s.setReadOnly(True); s.rec = False; s._prev = ""

    def start(s): s.rec = True; s._prev = s.text(); s.setText("Press the shortcut…  (Esc cancels)"); s.setFocus()

    def _end(s, text, emit):
        s.rec = False; s.setText(text); s.captured.emit(emit)

    def event(s, e):
        if s.rec and e.type() == QEvent.Type.ShortcutOverride: e.accept(); return True
        if s.rec and e.type() == QEvent.Type.KeyPress: s.keyPressEvent(e); return True
        return super().event(e)

    def focusOutEvent(s, e):
        if s.rec: s._end(s._prev, "")
        super().focusOutEvent(e)

    def keyPressEvent(s, e):
        if not s.rec: return super().keyPressEvent(e)
        k = e.key()
        if k == Qt.Key.Key_Escape.value: s._end(s._prev, ""); return
        if k in s.MODS: return
        m, KM = e.modifiers(), Qt.KeyboardModifier; parts = []
        for flag, name in ((KM.ControlModifier, "ctrl"), (KM.AltModifier, "alt"), (KM.ShiftModifier, "shift"), (KM.MetaModifier, "windows")):
            if m & flag: parts.append(name)
        if k in s.NAMES: parts.append(s.NAMES[k])
        elif Qt.Key.Key_F1.value <= k <= Qt.Key.Key_F24.value: parts.append(f"f{k - Qt.Key.Key_F1.value + 1}")
        else:
            nm = QKeySequence(k).toString().lower()
            if not nm: return
            parts.append(nm)
        combo = "+".join(parts); s._end(combo, combo)


class Settings(QDialog):
    PAGES = ["General", "Providers", "API keys", "Voice", "Display", "Orb", "Memory", "Connections", "Data"]
    ICONS = {"General": "⚙", "Providers": "🧠", "API keys": "🔑", "Voice": "🎙", "Display": "🖥", "Orb": "🔮", "Memory": "💾", "Connections": "🔗", "Data": "📦"}

    def __init__(s, app):
        super().__init__(); s.app = app; s.recording = None; s.provs = []; s.krows = []; s._ids = []
        s.setWindowTitle("AI Overlay - Settings"); s.setMinimumSize(920, 620); s.resize(1020, 700); s.setStyleSheet(SETTINGS_QSS)
        root = QVBoxLayout(s); root.setContentsMargins(22, 22, 22, 16); root.setSpacing(14)
        body = QHBoxLayout(); body.setSpacing(22); root.addLayout(body, 1)
        side = QFrame(); side.setObjectName("side"); side.setFixedWidth(228); sv = QVBoxLayout(side); sv.setContentsMargins(14, 22, 14, 14); sv.setSpacing(5)
        brand = QLabel("AI Overlay"); brand.setObjectName("brand"); ver = QLabel(f"Settings  ·  v{APP_VERSION}"); ver.setObjectName("ver")
        sv.addWidget(brand); sv.addWidget(ver); sv.addSpacing(12)
        s.nav = QListWidget(); s.nav.setObjectName("nav"); s.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for name in s.PAGES: s.nav.addItem(f"{s.ICONS[name]}   {name}")
        sv.addWidget(s.nav, 1); body.addWidget(side)
        s.stack = QStackedWidget(); body.addWidget(s.stack, 1)
        for build in (s._general, s._providers, s._apikeys, s._voice, s._display, s._orb, s._memory, s._connections, s._data): s.stack.addWidget(build())
        s.nav.currentRowChanged.connect(s.stack.setCurrentIndex); s.nav.setCurrentRow(0)

        sep = QFrame(); sep.setObjectName("sep"); sep.setFixedHeight(1); root.addWidget(sep)
        bar = QHBoxLayout(); bar.setContentsMargins(6, 4, 6, 0); bar.setSpacing(10); s.status = QLabel(""); s.status.setObjectName("hint")
        cancel = QPushButton("Cancel"); save = QPushButton("Save changes"); save.setObjectName("save"); cancel.setObjectName("ghost")
        cancel.clicked.connect(s.close); save.clicked.connect(s.save)
        bar.addWidget(s.status, 1); bar.addWidget(cancel); bar.addWidget(save); root.addLayout(bar)
        for b in s.findChildren(QPushButton): b.setAutoDefault(False); b.setDefault(False)    # Enter in a field must never press a random button
        for k, _ in HK_LABELS: s.edits[k].captured.connect(lambda combo, k=k: s.on_captured(k, combo))

    # ---------- pages ----------
    def _general(s):
        c1, f1, _ = mk_card("Assistant behavior")
        s.effort = QComboBox(); s.effort.addItems(["minimal", "low", "medium", "high"])
        s.sil = SliderField(4, 50, 1, " s", scale=10, width=150)          # 0.4 - 5.0 s
        s.steps = QSpinBox(); s.steps.setRange(1, 25)
        s.maxtok = SliderField(100, 4000, 50, " tokens", width=170)
        s.confirm = Switch("Ask before every mouse / keyboard / close-app action")
        f1.addRow("Thinking effort", s.effort); f1.addRow("Auto-send after silence", s.sil); f1.addRow("Max reply tokens", s.maxtok)
        f1.addRow("Max steps (Screen control)", s.steps); f1.addRow("", s.confirm)
        cm, fm, _ = mk_card("Music", "Free Spotify works: the assistant clicks Play for you and checks that music is really playing. YouTube starts by itself.")
        s.music = QComboBox(); s.music.addItems(["spotify", "youtube"]); fm.addRow("Play music with", s.music)
        s.sp_id = QLineEdit(); s.sp_id.setPlaceholderText("Optional, Premium accounts only"); fm.addRow("Spotify Client ID", s.sp_id)
        c2, f2, v2 = mk_card("Hotkeys", "Click Change, then press the new shortcut. Use a modifier (Ctrl / Alt / Shift / Win) or an F-key.")
        s.edits, s.btns = {}, {}
        for k, label in HK_LABELS:
            row = QHBoxLayout(); e = HotkeyEdit(); b = QPushButton("Change"); b.setFixedWidth(84)
            b.clicked.connect(lambda _, k=k: s.record(k)); row.addWidget(e, 1); row.addWidget(b); s.edits[k], s.btns[k] = e, b; f2.addRow(label, row)
        rb = QPushButton("Reset to defaults"); rb.clicked.connect(s.reset_hk); v2.addWidget(rb, 0, Qt.AlignmentFlag.AlignLeft)
        return mk_page("General", c1, cm, c2)

    def _providers(s):
        c, f, v = mk_card("Model providers", "Tried top to bottom; the first that answers wins. Any OpenAI-compatible endpoint works. API keys are managed in the “API keys” tab.")
        s.plist = QListWidget(); s.plist.setMinimumHeight(220); v.addWidget(s.plist, 1)
        row = QHBoxLayout()
        for txt, fn in (("Add", s.p_add), ("Edit", s.p_edit), ("Remove", s.p_del), ("↑", lambda: s.p_move(-1)), ("↓", lambda: s.p_move(1))):
            b = QPushButton(txt); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); v.addLayout(row); s.plist.itemDoubleClicked.connect(lambda _: s.p_edit())
        c2, f2, v2 = mk_card("Usage today", "Requests, errors and exact tokens are tracked separately for every configuration (resets daily; Gemini at midnight Pacific). "
                                            "“Left” uses that configuration's daily limit - Groq reports the real number itself. The list is tried strictly top to bottom; a failure falls through to the next entry.")
        s.usage_lbl = QLabel(""); s.usage_lbl.setWordWrap(True); v2.addWidget(s.usage_lbl)
        rb = QPushButton("Reset counters"); rb.clicked.connect(lambda: (s.app.ov.usage.reset(), s.p_usage())); v2.addWidget(rb, 0, Qt.AlignmentFlag.AlignLeft)
        s.utimer = QTimer(s); s.utimer.timeout.connect(lambda: s.isVisible() and s.p_usage()); s.utimer.start(2000)
        return mk_page("Providers", c, c2)

    def _apikeys(s):
        c1, s.kform, _ = mk_card("Model providers", "One key per provider. Leave empty for local servers (Ollama, LM Studio).")
        c2, f2, _ = mk_card("Voice & speech", "Text-to-speech key (ElevenLabs or an OpenAI-compatible TTS) and the optional Whisper-style speech-to-text key.")
        s.tkey = SecretEdit("TTS API key (ElevenLabs / OpenAI)"); s.skey = SecretEdit("STT API key (e.g. Groq)")
        f2.addRow("TTS API key", s.tkey); f2.addRow("STT API key", s.skey)
        c3, f3, v3 = mk_card("Where keys are stored")
        v3.addWidget(hint_label("Keys are saved as plain text in config.json next to the program. Don't share or commit that file. "
                                "If a TTS key is empty, the ELEVENLABS_API_KEY environment variable is used."))
        return mk_page("API keys", c1, c2, c3)

    def _voice(s):
        c1, f1, v1 = mk_card("Voice", "Works out of the box with your computer's built-in voice: no account, no key. Pick how it sounds and how it talks.")
        s.speak_on = Switch("Speak replies aloud"); s.spk_notices = Switch("Read new notifications aloud while the overlay is open")
        s.vstyle = QComboBox(); s.persona = QComboBox()
        for k, st in VOICE_STYLES.items(): s.vstyle.addItem(f"{st['label']} - {st['desc']}", k)
        for k, (lbl, _) in PERSONAS.items(): s.persona.addItem(lbl, k)
        s.vrate = QSpinBox(); s.vrate.setRange(-5, 5); s.vrate.setToolTip("0 = normal speed")
        s.vname = QComboBox(); s.vname.addItem("Default Windows voice", "")
        prev = QPushButton("▶  Preview voice"); prev.clicked.connect(s.test_voice)
        f1.addRow("", s.speak_on); f1.addRow("Voice style", s.vstyle); f1.addRow("Personality", s.persona); f1.addRow("Speaking speed", s.vrate)
        f1.addRow("Built-in voice", s.vname); f1.addRow("", s.spk_notices); f1.addRow("", prev)
        c2, f2, v2 = mk_card("Microphone", "Choose whether the assistant listens by itself. The mic button turns red whenever the microphone is on.")
        s.listen = QComboBox(); s.listen.addItem("Manual - listen only after I tap 🎤 (recommended)", "manual"); s.listen.addItem("Auto-listen - start listening as soon as the overlay opens", "auto")
        f2.addRow("When the overlay opens", s.listen)
        c3, f3, _ = mk_card("Speech recognition", "Your AI model hears your voice directly. If it can't, Windows' built-in recognizer is used automatically. A Whisper-style service is optional and more accurate.")
        s.stt = QComboBox(); s.stt.addItems(["native", "transcribe"]); s.surl = QLineEdit(); s.smodel = QLineEdit()
        f3.addRow("Mode", s.stt); f3.addRow("Whisper-style URL", s.surl); f3.addRow("STT model", s.smodel)
        c4, f4, _ = mk_card("Online voice (optional)", "Higher-quality voices from ElevenLabs or an OpenAI-compatible service. Add the key in the “API keys” tab. Without a key the built-in voice is used.")
        s.tts = QComboBox(); s.tts.addItems(["system", "elevenlabs", "openai", "off"]); s.tvoice = QLineEdit(); s.tmodel = QLineEdit(); s.turl = QLineEdit()
        f4.addRow("Voice engine", s.tts); f4.addRow("Voice ID / name", s.tvoice); f4.addRow("TTS model", s.tmodel); f4.addRow("TTS URL (OpenAI-compatible)", s.turl)
        return mk_page("Voice", c1, c2, c3, c4)

    def refresh_voices(s):
        def work():
            vs = s.app.ov.speaker.sapi.voices() if s.app.ov.speaker.sapi.available() else []
            s.app.ov.gui_sig.emit(lambda: s._fill_voices(vs))
        threading.Thread(target=work, daemon=True).start()

    def _fill_voices(s, vs):
        cur = s.app.cfg.get("voice_name", ""); s.vname.clear(); s.vname.addItem("Default Windows voice", "")
        for v in vs: s.vname.addItem(v, v)
        s.vname.setCurrentIndex(max(0, s.vname.findData(cur)))

    def _display(s):
        c1, f1, v1 = mk_card("Target monitor", "Choose which monitor the overlay (and the Canvas, screenshots and area selection) uses.")
        s.disp = QComboBox(); row = QHBoxLayout(); ident = QPushButton("Identify monitors"); ident.clicked.connect(s.identify_screens)
        row.addWidget(s.disp, 1); row.addWidget(ident); f1.addRow("Open overlay on", row)
        s.disp_info = hint_label(""); v1.addWidget(s.disp_info)
        c2, f2, v2 = mk_card("On-screen explanations", "Explain / Summarize / Translate draw a teacher-style whiteboard: step cards, an animated "
                                                     "pointer line and a highlighted frame on the exact element. Its colour, size and position live in the Orb tab.")
        s.board_speak = Switch("Read explanation steps aloud"); f2.addRow("", s.board_speak)
        c3, f3, v3 = mk_card("How it works")
        v3.addWidget(hint_label("“Follow the mouse cursor” opens on whichever monitor the pointer is on when you press the hotkey. The monitor is then "
                                "kept for that session, so Screen control stays on the same display even while it moves the mouse. "
                                "If a chosen monitor is unplugged, the overlay falls back to the cursor's monitor. The emergency-stop screen corners "
                                "refer to the primary monitor."))
        return mk_page("Display", c1, c2, c3)

    def _orb(s):
        c1, f1, v1 = mk_card("Placement", "The overlay opens as a small animated AI orb. Hover it to open the full overlay; that overlay then "
                                                      "stays open until you close it or the AI starts thinking. Drag the orb itself to save a custom spot.")
        s.opos = QComboBox()
        for key, label in ORB_PLACES: s.opos.addItem(label, key)
        s.ox = QSpinBox(); s.oy = QSpinBox()
        for sp in (s.ox, s.oy): sp.setRange(-100000, 100000); sp.setSingleStep(10); sp.setSuffix(" px"); sp.setFixedWidth(110)
        crow = QHBoxLayout(); crow.setSpacing(8)
        for lbl, sp in (("X", s.ox), ("Y", s.oy)):
            q = QLabel(lbl); q.setObjectName("hint"); crow.addWidget(q); crow.addWidget(sp)
        crow.addStretch(); f1.addRow("Orb position", s.opos); f1.addRow("Custom coordinates", crow)
        use_now = QPushButton("Use the orb's current spot"); use_now.clicked.connect(s._orb_use_now)
        row = QHBoxLayout(); row.addWidget(use_now); row.addStretch(); f1.addRow("", row)
        s.opos.currentIndexChanged.connect(s._orb_changed)
        for sp in (s.ox, s.oy): sp.valueChanged.connect(s._orb_changed)
        v1.addWidget(hint_label("Changes here apply immediately and are saved right away. A custom spot is always kept "
                                "on a connected monitor, so the orb can never end up off-screen."))

        c2, f2, v2 = mk_card("Colour", "The orb is a small black hole: a coloured accretion disk and photon ring around a near-black core, "
                                         "with a soft aura of its own around it. The aura can match the energy colour or be completely different.")
        s.opreview = AIOrb(132, orb_color(s.app.cfg), aura_color(s.app.cfg))
        prow = QHBoxLayout(); prow.setSpacing(16); prow.addWidget(s.opreview, 0, Qt.AlignmentFlag.AlignVCenter)
        ptext = QVBoxLayout(); ptext.setSpacing(4)
        p1 = QLabel("Live preview"); p1.setObjectName("preview_title")
        p2 = hint_label("This is the real orb, not a picture. It updates as you change anything below.")
        ptext.addWidget(p1); ptext.addWidget(p2); ptext.addStretch(); prow.addLayout(ptext, 1)
        v2.insertLayout(min(2, v2.count()), prow)          # under the title + hint, above the colour rows
        s.orb_shared = Switch("Use one colour theme for the Orb and the Chat")
        s.orb_shared.toggled.connect(s._orb_changed); f2.addRow("", s.orb_shared)
        s.ocolor = QComboBox(); s.ccolor = QComboBox(); s.acolor = QComboBox()
        for hexv, label in ORB_COLORS:
            s.ocolor.addItem(label, hexv); s.ccolor.addItem(label, hexv); s.acolor.addItem(label, hexv)
        s.acolor.insertItem(0, "Match the orb colour", "")
        for combo in (s.ocolor, s.ccolor, s.acolor): combo.setMinimumWidth(130)
        s.swatch = QLabel(); s.swatch.setFixedSize(30, 24)
        s.cswatch = QLabel(); s.cswatch.setFixedSize(30, 24)
        s.aswatch = QLabel(); s.aswatch.setFixedSize(30, 24)
        s.ocolor_btn = QPushButton("Custom…"); s.ccolor_btn = QPushButton("Custom…"); s.acolor_btn = QPushButton("Custom…")
        s.ocolor_btn.clicked.connect(s._pick_orb_color); s.ccolor_btn.clicked.connect(s._pick_chat_color); s.acolor_btn.clicked.connect(s._pick_aura_color)
        s.ocolor.currentIndexChanged.connect(s._orb_preset); s.ccolor.currentIndexChanged.connect(s._chat_preset); s.acolor.currentIndexChanged.connect(s._aura_preset)
        ccol = QHBoxLayout(); ccol.setSpacing(8); ccol.addWidget(s.swatch); ccol.addWidget(s.ocolor, 1); ccol.addWidget(s.ocolor_btn)
        qcol = QHBoxLayout(); qcol.setSpacing(8); qcol.addWidget(s.cswatch); qcol.addWidget(s.ccolor, 1); qcol.addWidget(s.ccolor_btn)
        acol = QHBoxLayout(); acol.setSpacing(8); acol.addWidget(s.aswatch); acol.addWidget(s.acolor, 1); acol.addWidget(s.acolor_btn)
        f2.addRow("Energy colour", ccol); f2.addRow("Aura colour", acol); f2.addRow("Chat colour", qcol)

        c3, f3, v3 = mk_card("Size", "Small, Medium or Large - the black hole, its disk, its aura and the spot the chat grows out of all scale together.")
        s.osize = QComboBox()
        for key, label, _f in ORB_SIZES: s.osize.addItem(label, key)
        f3.addRow("Orb size", s.osize); s.osize.currentIndexChanged.connect(s._orb_changed)
        rb = QPushButton("Reset the Orb to defaults"); rb.clicked.connect(s._orb_reset)
        rrow = QHBoxLayout(); rrow.addWidget(rb); rrow.addStretch(); v3.addLayout(rrow)
        v3.addWidget(hint_label("Tip: a Large orb is easier to hover on a 4K or TV screen; Small keeps it out of the way."))
        return mk_page("Orb", c1, c2, c3)

    def _orb_coords_state(s):
        """The X / Y boxes only mean something for a custom spot; the rest of the time they mirror the live orb."""
        custom = s.opos.currentData() == "custom"
        s.ox.setEnabled(custom); s.oy.setEnabled(custom)
        shared = s.orb_shared.isChecked()
        for w in (s.ccolor, s.ccolor_btn): w.setEnabled(not shared)
        s.cswatch.setEnabled(not shared)

    def _paint_swatch(s):
        aura = getattr(s, "_aura_hex", "") or getattr(s, "_orb_hex", "#6c8cf5")
        for lbl, hexv, tip in ((s.swatch, getattr(s, "_orb_hex", "#6c8cf5"), "Energy colour"),
                               (s.cswatch, getattr(s, "_chat_hex", "#6c8cf5"), "Chat colour"),
                               (s.aswatch, aura, "Aura colour")):
            c = QColor(hexv)
            lbl.setStyleSheet(f"background:{hexv};border:1px solid rgba(255,255,255,60);border-radius:7px")
            lbl.setToolTip(f"{tip}: {c.name() if c.isValid() else hexv}")
        if getattr(s, "opreview", None) is not None:
            s.opreview.set_colors(getattr(s, "_orb_hex", "#6c8cf5"), aura)

    @staticmethod
    def _sync_combo(combo, hexv):
        """Select a stored colour, adding a Custom entry when it is not one of the presets."""
        combo.blockSignals(True)
        if hexv and combo.findData(hexv) < 0: combo.addItem("Custom", hexv)
        ix = combo.findData(hexv) if hexv else 0
        combo.setCurrentIndex(max(0, ix)); combo.blockSignals(False)

    def _orb_preset(s):
        hexv = s.ocolor.currentData()
        if hexv: s._orb_hex = hexv; s._paint_swatch(); s._orb_changed()

    def _chat_preset(s):
        hexv = s.ccolor.currentData()
        if hexv: s._chat_hex = hexv; s._paint_swatch(); s._orb_changed()

    def _aura_preset(s):
        hexv = s.acolor.currentData()
        if hexv is not None:
            s._aura_hex = hexv; s._paint_swatch(); s._orb_changed()

    def _pick_color(s, key, title):
        current = getattr(s, key, "") or getattr(s, "_orb_hex", "#6c8cf5")
        c = QColorDialog.getColor(QColor(current), s, title)
        if not c.isValid(): return
        setattr(s, key, c.name())
        combo = {"_orb_hex": s.ocolor, "_chat_hex": s.ccolor, "_aura_hex": s.acolor}[key]
        s._sync_combo(combo, c.name())
        s._paint_swatch(); s._orb_changed()

    def _pick_orb_color(s): s._pick_color("_orb_hex", "Orb energy colour")

    def _pick_chat_color(s): s._pick_color("_chat_hex", "Chat colour")

    def _pick_aura_color(s): s._pick_color("_aura_hex", "Orb aura colour")

    def _orb_use_now(s):
        """Adopt the orb's current on-screen position as the custom spot."""
        ov = getattr(s.app, "ov", None)
        r = ov.orb_rect() if ov is not None else None
        if r is None: return
        s._orb_loading = True
        s.ox.setValue(r.x()); s.oy.setValue(r.y())
        s.opos.setCurrentIndex(max(0, s.opos.findData("custom")))
        s._orb_loading = False
        s._orb_changed()

    def _orb_reset(s):
        s._orb_loading = True
        s.opos.setCurrentIndex(max(0, s.opos.findData(DEFAULTS["orb_position"])))
        s.osize.setCurrentIndex(max(0, s.osize.findData(DEFAULTS["orb_size"])))
        s.orb_shared.setChecked(DEFAULTS["orb_theme_shared"])
        s._orb_hex = DEFAULTS["orb_color"]; s._chat_hex = DEFAULTS["chat_color"]; s._aura_hex = DEFAULTS["orb_aura_color"]
        for combo, hexv in ((s.ocolor, s._orb_hex), (s.ccolor, s._chat_hex), (s.acolor, s._aura_hex)):
            s._sync_combo(combo, hexv)
        s.ox.setValue(0); s.oy.setValue(0)
        s._orb_loading = False
        s._paint_swatch(); s._orb_changed()

    def _orb_changed(s):
        """Apply Orb placement / colour / theme / size live (and persist), without waiting for Save.

        Only the setting that changed is written, the result is validated in one place (normalize_orb) and the
        widgets are re-synced from that validated config - so the UI can never show something the orb is not doing."""
        if getattr(s, "_orb_loading", False): return
        c = s.app.cfg
        c["orb_position"] = s.opos.currentData() or "bottom-right"
        if c["orb_position"] == "custom": c["orb_x"], c["orb_y"] = s.ox.value(), s.oy.value()
        c["orb_color"] = getattr(s, "_orb_hex", c.get("orb_color", "#6c8cf5"))
        c["orb_aura_color"] = getattr(s, "_aura_hex", c.get("orb_aura_color", ""))
        c["chat_color"] = getattr(s, "_chat_hex", c.get("chat_color", "#6c8cf5"))
        c["orb_theme_shared"] = s.orb_shared.isChecked()
        c["orb_size"] = s.osize.currentData() or "medium"
        normalize_orb(c)
        try: save_cfg(c)
        except Exception: pass
        ov = getattr(s.app, "ov", None)
        if ov is not None:
            ov.apply_orb_style()
            r = ov.orb_rect()
            s._orb_loading = True
            s.ox.setValue(r.x()); s.oy.setValue(r.y())        # show where the orb really is
            s._orb_loading = False
        s._paint_swatch(); s._orb_coords_state()

    def _memory(s):
        c, f, v = mk_card("Long-term memory"); s.memory_panel = MemoryPanel(s.app.memory); v.addWidget(s.memory_panel)
        return mk_page("Memory", c)

    LEVEL_COL = {"ok": "#7be3c0", "info": "#8ab4f8", "warn": "#ffc66d", "error": "#ff9aa8", "off": "#8b93a7"}

    def _connections(s):
        s.conn = {}; cards = []
        intro, _f, vi = mk_card("Connect your apps", "Press Connect on an app and it is linked straight away: there is nothing else to save. Messages from connected apps show up under 🔔 in the overlay, and you can answer from there. Press Disconnect any time.")
        cards.append(intro)
        for cid, cls in CONNECTORS.items():
            card, f, v = mk_card(f"{cls.icon}  {cls.name}", cls.blurb)
            st = QLabel(""); st.setTextFormat(Qt.TextFormat.RichText); st.setWordWrap(True); v.insertWidget(2, st)
            steps = hint_label(cls.STEPS); v.addWidget(steps); box = QWidget(); bf = QFormLayout(box); bf.setContentsMargins(0, 0, 0, 0); fields = {}
            for key, label, secret in cls.FIELDS:
                e = QLineEdit(); e.setEchoMode(QLineEdit.EchoMode.Password if secret else QLineEdit.EchoMode.Normal); bf.addRow(label, e); fields[key] = e
            v.addWidget(box); btn = QPushButton("Connect"); btn.setObjectName("save"); row = QHBoxLayout(); row.addWidget(btn); row.addStretch(); v.addLayout(row)
            btn.clicked.connect(lambda _, c=cid: s.toggle_conn(c)); s.conn[cid] = dict(st=st, fields=fields, box=box, btn=btn, steps=steps); cards.append(card)
        return mk_page("Connections", *cards)

    def toggle_conn(s, cid):
        hub = s.app.hub; w = s.conn[cid]
        if hub.wanted(cid) and hub.level.get(cid) != "error": hub.disconnect(cid)
        else: hub.connect(cid, {k: e.text() for k, e in w["fields"].items()})
        s.refresh_conn(cid)

    def refresh_conn(s, cid):
        hub = s.app.hub; w = s.conn[cid]; lvl = hub.level.get(cid, "off"); txt = hub.state.get(cid, "Not connected")
        active = hub.wanted(cid) and lvl in ("ok", "info", "warn")
        w["st"].setText(f"<span style='color:{s.LEVEL_COL.get(lvl, '#8b93a7')}'>●</span>  {html.escape(txt)}")
        w["btn"].setText("Disconnect" if active else ("Try again" if lvl == "error" else "Connect"))
        w["box"].setVisible(not active); w["steps"].setVisible(not active)

    def load_conns(s):
        saved = s.app.cfg.get("connections", {})
        for cid, w in s.conn.items():
            for k, e in w["fields"].items(): e.setText(str(saved.get(cid, {}).get(k, "")))
            s.refresh_conn(cid)

    def on_conn_status(s, cid, text, level="info"):
        if cid in s.conn: s.refresh_conn(cid)
        ov = getattr(s.app, "ov", None)
        if ov is not None and ov._drawer_on: ov._conn_line()

    def _data(s):
        c1, f1, v1 = mk_card("Secure vault", "Saved logins, encrypted with your master password. The assistant can ask this app to sign in to a website for you, "
                                              "but it never sees the username or password. Manage which website each login belongs to, and whether the assistant may use it, in the vault.")
        s.vault_ai = Switch("Let the assistant sign in to websites with my saved logins"); f1.addRow("", s.vault_ai)
        s.vsess = QComboBox()
        for lbl, m in (("Ask for the master password every time", 0), ("Stay unlocked for 5 minutes", 5), ("Stay unlocked for 15 minutes", 15), ("Stay unlocked for 30 minutes", 30)): s.vsess.addItem(lbl, m)
        f1.addRow("Unlock", s.vsess); s.vstat = hint_label(""); f1.addRow("Status", s.vstat)
        row = QHBoxLayout(); bv = QPushButton("Open secure vault…"); bv.clicked.connect(lambda: open_vault_manager(s.app.vault)); bl = QPushButton("Lock now")
        bl.clicked.connect(lambda: (s.app.vault.lock_now(), s.vault_status())); row.addWidget(bv); row.addWidget(bl); row.addStretch(); v1.addLayout(row)
        s.vtimer = QTimer(s); s.vtimer.timeout.connect(lambda: s.isVisible() and s.vault_status()); s.vtimer.start(1000)
        c2, f2, v2 = mk_card("Files", "config.json, memory.json and vault.bin live next to the program.")
        bf = QPushButton("Open data folder"); bf.clicked.connect(s.open_folder); v2.addWidget(bf, 0, Qt.AlignmentFlag.AlignLeft)
        c3, f3, v3 = mk_card("Updates", f"Version {APP_VERSION}. The app checks GitHub for a newer release and tells you.")
        s.auto_upd = Switch("Check for updates automatically"); f3.addRow("", s.auto_upd)
        bu = QPushButton("Check now"); bu.clicked.connect(lambda: s.app.check_updates(manual=True)); v3.addWidget(bu, 0, Qt.AlignmentFlag.AlignLeft)
        return mk_page("Data", c1, c2, c3)

    def vault_status(s):
        v = s.app.vault
        if not v.exists(): s.vstat.setText("No vault yet."); return
        left = v.seconds_left() if v.current() else 0
        s.vstat.setText(f"🔓 Unlocked - locks in {left // 60}:{left % 60:02d}" if left else "🔒 Locked")

    def open_folder(s):
        try: os.startfile(BASE)
        except Exception: subprocess.Popen(["explorer", BASE], creationflags=NO_WINDOW)

    # ---------- load / lifecycle ----------
    def load(s):
        c = s.app.cfg
        s.effort.setCurrentText(c["effort"]); s.sil.setValue(float(c["silence"])); s.confirm.setChecked(c["confirm_actions"])
        s.steps.setValue(int(c["max_steps"])); s.maxtok.setValue(int(c["max_tokens"])); s.sp_id.setText(c.get("spotify_client_id", "")); s.music.setCurrentText(c.get("music_service", "spotify")); s.auto_upd.setChecked(bool(c.get("auto_update", True)))
        for k, _ in HK_LABELS: s.edits[k].setText(c[k])
        s.provs = copy.deepcopy(c["providers"]); s.p_refresh()
        s.tts.setCurrentText(c["tts_provider"]); s.tkey.setText(c["tts_key"]); s.tvoice.setText(c["tts_voice"]); s.tmodel.setText(c["tts_model"]); s.turl.setText(c["tts_url"])
        s.stt.setCurrentText(c["stt_mode"]); s.surl.setText(c["stt_url"]); s.skey.setText(c["stt_key"]); s.smodel.setText(c["stt_model"])
        s.speak_on.setChecked(not c.get("muted")); s.spk_notices.setChecked(bool(c.get("speak_notices", True)))
        s.vstyle.setCurrentIndex(max(0, s.vstyle.findData(c.get("voice_style", "natural")))); s.persona.setCurrentIndex(max(0, s.persona.findData(c.get("voice_persona", "default"))))
        s.vrate.setValue(int(c.get("voice_rate", 0))); s.listen.setCurrentIndex(max(0, s.listen.findData(c.get("listen_mode", "manual"))))
        s.vault_ai.setChecked(bool(c.get("vault_ai", True))); s.vsess.setCurrentIndex(max(0, s.vsess.findData(int(c.get("vault_session_min", 5)))))
        s._snap = {k: c.get(k) for k in s.VOICE_KEYS}; s._saved = False; s.refresh_voices(); s.vault_status()
        s.refresh_displays(c.get("display", "cursor")); s.memory_panel.refresh(); s.load_conns(); s.status.setText("")
        s._orb_loading = True
        normalize_orb(c)
        s.opos.setCurrentIndex(max(0, s.opos.findData(c.get("orb_position", "bottom-right"))))
        s.ox.setValue(_as_int(c.get("orb_x", 0), 0)); s.oy.setValue(_as_int(c.get("orb_y", 0), 0))
        s._orb_hex = c["orb_color"]; s._chat_hex = c["chat_color"]; s._aura_hex = c.get("orb_aura_color", "")
        s.orb_shared.setChecked(_as_bool(c.get("orb_theme_shared"), True))
        for combo, hexv in ((s.ocolor, s._orb_hex), (s.ccolor, s._chat_hex), (s.acolor, s._aura_hex)):
            s._sync_combo(combo, hexv)
        s._paint_swatch()
        s.osize.setCurrentIndex(max(0, s.osize.findData(c.get("orb_size", "medium"))))
        s.board_speak.setChecked(bool(c.get("board_speak", True)))
        s._orb_loading = False; s._orb_coords_state()

    VOICE_KEYS = ("tts_provider", "tts_key", "tts_voice", "tts_model", "tts_url", "voice_style", "voice_persona", "voice_rate", "voice_name", "muted")

    def showEvent(s, e):
        if not e.spontaneous(): s.load()          # only on a real open - never wipe unsaved edits when restored from minimize
        super().showEvent(e)

    def closeEvent(s, e):
        for ed in s.edits.values():
            if ed.rec: ed._end(ed._prev, "")
        if s.recording: s.recording = None; s.app.apply_hotkeys()
        if not getattr(s, "_saved", True) and getattr(s, "_snap", None): s.app.cfg.update(s._snap)       # a voice preview must not outlive a cancelled dialog
        super().closeEvent(e)

    # ---------- display ----------
    def refresh_displays(s, sel=None):
        sel = sel if sel is not None else (s.disp.currentData() or s.app.cfg.get("display", "cursor"))
        s.disp.blockSignals(True); s.disp.clear()
        s.disp.addItem("Follow the mouse cursor", "cursor"); s.disp.addItem("Primary monitor", "primary")
        lines = []
        for i, sc in enumerate(QGuiApplication.screens()):
            s.disp.addItem(screen_label(i, sc), "name:" + sc.name()); lines.append(screen_label(i, sc))
        ix = s.disp.findData(sel); s.disp.setCurrentIndex(ix if ix >= 0 else 0); s.disp.blockSignals(False)
        s.disp_info.setText("Detected: " + "  |  ".join(lines) if lines else "No monitors detected")

    def identify_screens(s):
        for w in s._ids: w.close()
        s._ids = []
        for i, sc in enumerate(QGuiApplication.screens()):
            w = QLabel(str(i + 1)); w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
            w.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating); w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            w.setStyleSheet("background:#3b5bdb;color:white;font:700 64px 'Segoe UI';border-radius:18px"); w.setFixedSize(120, 120)
            place_on(w, sc); g = sc.geometry(); w.move(g.x() + 30, g.y() + 30); w.show(); s._ids.append(w)
        QTimer.singleShot(1800, lambda ws=list(s._ids): [w.close() for w in ws])

    # ---------- API keys ----------
    def k_rebuild(s):
        while s.kform.rowCount(): s.kform.removeRow(0)
        s.krows = []
        if not s.provs: s.kform.addRow(hint_label("No providers yet - add one in the Providers tab."))
        for i, p in enumerate(s.provs, 1):
            w = SecretEdit("No key set" if p.get("key", "") == "" else ""); w.setText(p.get("key", ""))
            s.kform.addRow(f"{i}. {p['name']}  ({p['model']})", w); s.krows.append((p, w))

    def k_collect(s):
        for p, w in s.krows: p["key"] = w.text()

    def p_usage(s):
        u = s.app.ov.usage
        s.usage_lbl.setText("\n".join(f"{i}. {'●' if p.get('enabled', True) else '○'}  {p['name']} · {p['model']}  -  {u.line(p)}"
                                     for i, p in enumerate(s.provs, 1)) or "No providers yet.")

    # ---------- providers list ----------
    def p_refresh(s, sel=0):
        s.plist.clear(); s.plist.addItems([f"{i}. {'✔' if p.get('enabled', True) else '✖'} {p['name']} - {p['model']}"
                                           for i, p in enumerate(s.provs, 1)])
        if s.provs: s.plist.setCurrentRow(min(max(sel, 0), len(s.provs) - 1))
        s.k_rebuild(); s.p_usage()

    def p_add(s):
        s.k_collect(); d = ProviderDialog(parent=s)
        if d.exec() and d.result_p: s.provs.append(d.result_p); s.p_refresh(len(s.provs) - 1)

    def p_edit(s):
        r = s.plist.currentRow()
        if r < 0: return
        s.k_collect(); d = ProviderDialog(s.provs[r], parent=s)
        if d.exec() and d.result_p:
            d.result_p["id"] = s.provs[r].get("id") or d.result_p.get("id") or uuid.uuid4().hex
            s.provs[r] = d.result_p; s.p_refresh(r)

    def p_del(s):
        r = s.plist.currentRow()
        if r >= 0: s.k_collect(); del s.provs[r]; s.p_refresh(r)

    def p_move(s, d):
        r = s.plist.currentRow(); n = r + d
        if 0 <= r < len(s.provs) and 0 <= n < len(s.provs): s.k_collect(); s.provs[r], s.provs[n] = s.provs[n], s.provs[r]; s.p_refresh(n)

    def test_voice(s):
        c = s.app.cfg; c.update(tts_provider=s.tts.currentText(), tts_key=s.tkey.text(), tts_voice=s.tvoice.text().strip(), tts_model=s.tmodel.text().strip(),
                                tts_url=s.turl.text().strip(), voice_style=s.vstyle.currentData(), voice_rate=s.vrate.value(), voice_name=s.vname.currentData() or "", muted=False)
        s.app.ov.speaker.stop(); s.app.ov.speaker.say(f"Hi! This is the {VOICE_STYLES[s.vstyle.currentData()]['label']} voice. I can open apps, answer questions and do things for you.")

    # ---------- hotkeys ----------
    def reset_hk(s):
        for k, _ in HK_LABELS: s.edits[k].setText(DEFAULTS[k])

    def record(s, k):
        if s.recording: return
        s.recording = k; s.btns[k].setText("Press keys…"); s.app.pause_hotkeys()     # pause globals so the new combo doesn't fire an action
        s.edits[k].start()

    def on_captured(s, k, combo):
        if combo: s.edits[k].setText(combo)
        s.btns[k].setText("Change"); s.recording = None; s.app.apply_hotkeys()

    @staticmethod
    def valid(combo):
        parts = combo.split("+"); mods = {"ctrl", "alt", "shift", "windows", "left windows", "right windows", "alt gr"}
        if any(p in mods for p in parts[:-1]) and len(parts) > 1 and parts[-1] not in mods: return True
        return len(parts) == 1 and parts[0].startswith("f") and parts[0][1:].isdigit()

    def save(s):
        combos = {k: s.edits[k].text().strip().lower() for k, _ in HK_LABELS}
        for k, c in combos.items():
            if c and not s.valid(c):
                QMessageBox.warning(s, "Hotkey", f"“{c}” would fire while you type normally.\nUse a modifier (Ctrl/Alt/Shift/Win) + key, or an F-key."); return
        if len(set(c for c in combos.values() if c)) < len([c for c in combos.values() if c]):
            QMessageBox.warning(s, "Hotkey", "Two actions share the same hotkey."); return
        s.k_collect()
        s.app.cfg.update(providers=s.provs, effort=s.effort.currentText(), silence=round(s.sil.value(), 2),
                         confirm_actions=s.confirm.isChecked(), spotify_client_id=s.sp_id.text().strip(), music_service=s.music.currentText(), auto_update=s.auto_upd.isChecked(), max_steps=s.steps.value(), max_tokens=s.maxtok.value(), tts_provider=s.tts.currentText(),
                         tts_key=s.tkey.text(), tts_voice=s.tvoice.text().strip(), tts_model=s.tmodel.text().strip(),
                         tts_url=s.turl.text().strip(), stt_mode=s.stt.currentText(), stt_url=s.surl.text().strip(),
                         stt_key=s.skey.text(), stt_model=s.smodel.text().strip(), display=s.disp.currentData() or "cursor",
                         muted=not s.speak_on.isChecked(), speak_notices=s.spk_notices.isChecked(), voice_style=s.vstyle.currentData(), voice_persona=s.persona.currentData(),
                         voice_rate=s.vrate.value(), voice_name=s.vname.currentData() or "", listen_mode=s.listen.currentData(), vault_ai=s.vault_ai.isChecked(),
                         vault_session_min=s.vsess.currentData(), orb_position=s.opos.currentData() or "bottom-right",
                         orb_x=(s.ox.value() if s.opos.currentData() == "custom" else s.app.cfg.get("orb_x", -1)),
                         orb_y=(s.oy.value() if s.opos.currentData() == "custom" else s.app.cfg.get("orb_y", -1)),
                         orb_color=getattr(s, "_orb_hex", "#6c8cf5"),
                         orb_aura_color=getattr(s, "_aura_hex", ""),
                         chat_color=getattr(s, "_chat_hex", "#6c8cf5"), orb_theme_shared=s.orb_shared.isChecked(),
                         orb_size=s.osize.currentData() or "medium", board_speak=s.board_speak.isChecked(), **combos)
        s.app.vault.session_min = int(s.vsess.currentData())
        if s.app.vault.session_min == 0: s.app.vault.lock_now()
        normalize_orb(s.app.cfg)
        s._saved = True; s.app.ov.b_snd.blockSignals(True); s.app.ov.b_snd.setChecked(s.speak_on.isChecked()); s.app.ov.b_snd.blockSignals(False)
        try: save_cfg(s.app.cfg)
        except Exception as ex: QMessageBox.warning(s, "Settings", f"Couldn't write config.json: {ex}"); return
        s.app.apply_hotkeys(); s.app.ov.apply_display(); s.app.hub.apply(); s.close()

# One flat namespace across the package (it was split out of a single file); exporting
# everything, including the private helpers, keeps the behaviour identical.
__all__ = [n for n in globals() if not n.startswith('__')]
