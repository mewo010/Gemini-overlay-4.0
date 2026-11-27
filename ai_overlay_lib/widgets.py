"""Painted widgets: the thinking pill, the whiteboard, the canvas and the notice card.

The orb and its animation live in orb_animation.py; this module re-exports them."""
from .core import *
from .system import *
from .voice import *

from .orb_animation import *


# ---------- floating status pill (thinking next to the orb) ----------
class StatusPill(QWidget):
    """Compact, sleek caption beside the orb while the AI is processing ("Thinking..." with animated dots).
    Click-through and never takes focus, so it can sit over any app."""

    def __init__(s, color="#6c8cf5", aura=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        s.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        s.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        s.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        s.base = "Thinking"; s.clock = 0.0
        c = QColor(color); s.color = c if c.isValid() else QColor("#6c8cf5")
        a = QColor(aura) if aura and QColor(aura).isValid() else QColor(s.color)
        s.aura = a
        s.font = QFont("Segoe UI", 10); s.font.setBold(True)
        s.anim = QTimer(s); s.anim.timeout.connect(s._tick)       # runs only while the pill is visible
        s._size_to_text()

    def showEvent(s, e):
        super().showEvent(e)
        if not s.anim.isActive(): s.anim.start(40)

    def hideEvent(s, e):
        s.anim.stop()
        super().hideEvent(e)

    def _tick(s):
        s.clock += 0.05; s.update()

    def set_color(s, color):
        c = color if isinstance(color, QColor) else QColor(str(color))
        if c.isValid(): s.color = c; s.update()

    def set_colors(s, color, aura=None):
        s.set_color(color)
        if aura is not None:
            a = aura if isinstance(aura, QColor) else QColor(str(aura))
            if a.isValid(): s.aura = a; s.update()

    def set_text(s, text):
        t = re.sub(r"[.\u2026\s]+$", "", str(text or "Thinking")).strip() or "Thinking"
        t = t[:64]
        if t != s.base: s.base = t; s._size_to_text(); s.update()

    def _size_to_text(s):
        w = QFontMetrics(s.font).horizontalAdvance(s.base + "...") + 86
        s.setFixedSize(max(160, w), 40)

    def follow(s, orb, screen):
        """Sit beside the orb on the side with the most room (right of a left-docked orb, left of a right-docked one)."""
        gap = 10; w, h = s.width(), s.height()
        left = orb.center().x() < screen.center().x()
        x = orb.right() + gap if left else orb.left() - w - gap
        y = orb.center().y() - h // 2
        x = max(screen.x() + 8, min(x, screen.right() - w - 8))
        y = max(screen.y() + 8, min(y, screen.bottom() - h - 8))
        s.move(x, y)

    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHint(QPainter.RenderHint.Antialiasing); r = QRectF(s.rect()).adjusted(1, 1, -1, -1)
        accent = s.color; light = accent.lighter(170); deep = accent.darker(150); rad = r.height() / 2
        bg = QLinearGradient(r.topLeft(), r.bottomLeft())
        bg.setColorAt(0, QColor(30, 35, 50, 236)); bg.setColorAt(1, QColor(15, 18, 27, 240))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(bg); p.drawRoundedRect(r, rad, rad)
        border = QColor(accent); border.setAlpha(120); p.setPen(QPen(border, 1.2)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRoundedRect(r, rad, rad)
        cx, cy = r.right() - 24, r.center().y()
        paint_black_hole(p, QPointF(cx, cy), 7.6, accent, s.aura, s.clock, think=0.75,
                         glow=1.0 + 0.10 * math.sin(s.clock * 2.2))
        p.setFont(s.font); p.setPen(QColor("#eef2ff"))
        dots = "." * (1 + int(s.clock * 2) % 3)
        p.drawText(QRectF(20, 0, r.width() - 60, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, s.base + dots)


# ---------- teacher on a whiteboard: animated on-screen explanations ----------
BOARD_FONT = "Segoe Print"          # handwriting look; Qt falls back to a system font when it is missing


class Whiteboard(QWidget):
    """Full-screen explanation layer: a marker-style step card whose animated pointer line draws itself to the
    highlighted UI element, with next / previous / read-aloud / dismiss controls."""
    closed = pyqtSignal()
    DIM = QColor(6, 9, 16, 96)
    INK = QColor("#20283a")
    CREAM = QColor("#fbf7ea")
    EDGE = QColor("#ddd4bd")
    ACCENTS = {"explain": QColor("#2f6feb"), "summarize": QColor("#0f9d76"), "translate": QColor("#d9480f")}
    LABELS = {"explain": "EXPLANATION", "summarize": "SUMMARY", "translate": "TRANSLATION"}

    def __init__(s, screen, steps, kind="explain", cfg=None, speaker=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        s.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        s.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        s.setFocusPolicy(Qt.FocusPolicy.StrongFocus); s.setCursor(Qt.CursorShape.ArrowCursor)
        place_on(s, screen); s.setGeometry(screen.geometry())
        s.steps = steps or []; s.kind = kind if kind in s.ACCENTS else "explain"
        s.cfg = cfg or {}; s.speaker = speaker
        s.i = 0; s.t = 0.0; s.clock = 0.0; s.speak = bool(s.cfg.get("board_speak", True))
        s.btns = {}; s._press = None; s._g = screen.geometry()
        s.accent = s.ACCENTS[s.kind]
        s.anim = QTimer(s); s.anim.timeout.connect(s._tick); s.anim.start(40)
        QTimer.singleShot(220, s.say_step)

    # --- animation / steps ---
    def _tick(s):
        s.t = min(1.0, s.t + 0.05); s.clock += 0.09; s.update()
        if s.t >= 1.0 and s.anim.interval() != 80: s.anim.setInterval(80)      # settle to a calm pulse once drawn

    def step(s): return s.steps[s.i] if 0 <= s.i < len(s.steps) else {"title": "", "points": [], "target": None}

    def next(s): s.go(1)
    def prev(s): s.go(-1)

    def go(s, d):
        n = max(0, min(len(s.steps) - 1, s.i + d))
        if n == s.i and d > 0: s.close(); return
        if n != s.i: s.i = n; s.t = 0.0
        s.say_step(); s.update()

    def say_step(s):
        if not s.speak or s.speaker is None: return
        try:
            if not s.speaker.enabled(): return
            st = s.step(); line = ". ".join([st.get("title", "")] + [p for p in st.get("points", [])]).strip(". ")
            if line: s.speaker.say(line)
        except Exception: pass

    def toggle_speak(s):
        s.speak = not s.speak
        if not s.speak:
            try: s.speaker.stop()
            except Exception: pass
        else: s.say_step()
        s.update()

    # --- layout ---
    CARD_W = 396

    @staticmethod
    def bullets_height(st):
        """Height the bullet block needs - used by both the card size and the painter so nothing overlaps the footer."""
        fm = QFontMetrics(QFont(BOARD_FONT, 11)); txtw = Whiteboard.CARD_W - 57; h = 0
        for pt in st.get("points") or []:
            h += max(24, fm.boundingRect(QRect(0, 0, txtw, 4000), int(Qt.TextFlag.TextWordWrap), "•  " + str(pt)).height() + 10)
        return h or 26

    def card_size(s):
        return QSize(s.CARD_W, 126 + s.bullets_height(s.step()))

    def card_rect(s):
        sz = s.card_size(); W, H = s.width(), s.height(); m = 20
        tgt = s.step().get("target")
        if tgt is None:
            return QRect(W - sz.width() - m, H - sz.height() - m, sz.width(), sz.height())
        pad = 18
        cands = [QRect(tgt.right() + pad, tgt.center().y() - sz.height() // 2, sz.width(), sz.height()),
                 QRect(tgt.left() - pad - sz.width(), tgt.center().y() - sz.height() // 2, sz.width(), sz.height()),
                 QRect(tgt.center().x() - sz.width() // 2, tgt.top() - pad - sz.height(), sz.width(), sz.height()),
                 QRect(tgt.center().x() - sz.width() // 2, tgt.bottom() + pad, sz.width(), sz.height())]
        best = None
        for r in cands:
            inner = r.intersected(QRect(m, m, W - 2 * m, H - 2 * m))
            off = r.width() * r.height() - max(0, inner.width()) * max(0, inner.height())
            hit = r.intersected(tgt); overlap = max(0, hit.width()) * max(0, hit.height())
            score = off * 3 + overlap * 2
            if best is None or score < best[0]: best = (score, r)
        r = best[1]
        r.moveLeft(min(max(r.x(), m), max(m, W - sz.width() - m)))
        r.moveTop(min(max(r.y(), m), max(m, H - sz.height() - m)))
        return r

    # --- painting ---
    def paintEvent(s, e):
        if not s.steps: return
        p = QPainter(s); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        k = 1 - (1 - min(1.0, s.t)) ** 3                              # ease-out for entrance
        st = s.step(); tgt = st.get("target"); card = s.card_rect()
        if tgt is not None: s._spotlight(p, tgt, k)
        s._card(p, card, k, st)
        if tgt is not None: s._pointer(p, card, tgt, k)

    def _spotlight(s, p, tgt, k):
        hole = tgt.adjusted(-12, -12, 12, 12).intersected(s.rect())
        if hole.isEmpty(): return
        dim = QColor(s.DIM); dim.setAlpha(int(s.DIM.alpha() * k))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(dim)
        for r in (QRect(0, 0, s.width(), hole.top()), QRect(0, hole.bottom(), s.width(), s.height() - hole.bottom()),
                  QRect(0, hole.top(), hole.left(), hole.height()), QRect(hole.right(), hole.top(), s.width() - hole.right(), hole.height())):
            if r.width() > 0 and r.height() > 0: p.fillRect(r, dim)
        pulse = 0.5 + 0.5 * math.sin(s.clock * 2.4)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(4):                                            # soft marker glow
            a = int((44 - i * 9) * k); p.setPen(QPen(QColor(255, 209, 102, max(0, a)), 6 - i, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawRoundedRect(QRectF(hole).adjusted(-i * 3, -i * 3, i * 3, i * 3), 14, 14)
        p.setPen(QPen(QColor(255, 209, 102, int(240 * k)), 2.4 + 1.6 * pulse, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawRoundedRect(QRectF(hole), 12, 12)
        p.setPen(QPen(QColor(47, 111, 235, int(230 * k)), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))     # corner markers
        L = 16; corners = [(hole.left(), hole.top(), 1, 1), (hole.right(), hole.top(), -1, 1), (hole.left(), hole.bottom(), 1, -1), (hole.right(), hole.bottom(), -1, -1)]
        for x, y, dx, dy in corners:
            p.drawLine(QPointF(x, y), QPointF(x + dx * L, y)); p.drawLine(QPointF(x, y), QPointF(x, y + dy * L))

    @staticmethod
    def _edge(r, toward):
        c = r.center(); dx = toward.x() - c.x(); dy = toward.y() - c.y()
        if dx == 0 and dy == 0: return QPointF(c)
        sx = (r.width() / 2) / abs(dx) if dx else 1e9
        sy = (r.height() / 2) / abs(dy) if dy else 1e9
        kk = min(sx, sy)
        return QPointF(c.x() + dx * kk, c.y() + dy * kk)

    def _pointer(s, p, card, tgt, k):
        a = s._edge(card, tgt.center()); b = s._edge(tgt, card.center())
        dx, dy = b.x() - a.x(), b.y() - a.y(); dist = max(1.0, math.hypot(dx, dy))
        nx, ny = -dy / dist, dx / dist
        curve = min(70.0, dist * 0.22)
        ctrl = QPointF((a.x() + b.x()) / 2 + nx * curve, (a.y() + b.y()) / 2 + ny * curve)
        path = QPainterPath(a); path.quadTo(ctrl, b)
        if k <= 0.01: return
        pts = [path.pointAtPercent(i / 100.0) for i in range(int(100 * k) + 1)]
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 120), 7.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))   # white under-stroke keeps it readable
        p.drawPolyline(QPolygonF(pts))
        p.setPen(QPen(QColor(s.accent), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF(pts))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(s.accent))
        p.drawEllipse(a, 4.2, 4.2)
        if k > 0.97:                                                  # arrow head at the target
            ang = math.atan2(b.y() - ctrl.y(), b.x() - ctrl.x()); ln, wd = 15, 6.5
            head = QPolygonF([b,
                              QPointF(b.x() - ln * math.cos(ang) + wd * math.sin(ang), b.y() - ln * math.sin(ang) - wd * math.cos(ang)),
                              QPointF(b.x() - ln * math.cos(ang) - wd * math.sin(ang), b.y() - ln * math.sin(ang) + wd * math.cos(ang))])
            p.drawPolygon(head)

    def _card(s, p, r, k, st):
        alpha = min(1.0, k * 1.35); rr = QRectF(r).translated(0, (1 - k) * 16)
        p.save(); p.setOpacity(alpha)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(3, 6, 12, 70))
        p.drawRoundedRect(rr.adjusted(-4, 2, 4, 10), 20, 20)                        # drop shadow
        g = QLinearGradient(rr.topLeft(), rr.bottomLeft()); g.setColorAt(0, QColor("#fdfbf3")); g.setColorAt(1, QColor("#f4eede"))
        p.setBrush(g); p.setPen(QPen(s.EDGE, 1)); p.drawRoundedRect(rr, 18, 18)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(s.accent)); p.drawRoundedRect(QRectF(rr.x() + 20, rr.y() + 18, 54, 5), 2.5, 2.5)
        f_lbl = QFont("Segoe UI", 8); f_lbl.setBold(True); f_lbl.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.6)
        p.setFont(f_lbl); p.setPen(QColor(s.accent))
        p.drawText(QRectF(rr.x() + 82, rr.y() + 11, 150, 18), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), s.LABELS[s.kind])
        f_step = QFont("Segoe UI", 8); f_step.setBold(True)
        p.setFont(f_step); p.setPen(QColor("#8a8270"))
        p.drawText(QRectF(rr.right() - 92, rr.y() + 11, 72, 18), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                   f"STEP {s.i + 1}/{len(s.steps)}")
        f_title = QFont(BOARD_FONT, 15); f_title.setBold(True)
        p.setFont(f_title); p.setPen(s.INK)
        tr = QRectF(rr.x() + 22, rr.y() + 36, rr.width() - 44, 30)
        p.drawText(tr, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), st.get("title", "")[:64])
        f_body = QFont(BOARD_FONT, 11); p.setFont(f_body)
        txtw = rr.width() - 57
        y = rr.y() + 70
        for pt in st.get("points") or []:
            br = QRectF(rr.x() + 35, y, txtw, 400)
            h = QFontMetrics(f_body).boundingRect(QRect(int(br.x()), int(y), int(txtw), 400), int(Qt.TextFlag.TextWordWrap), "•  " + str(pt)).height()
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(s.accent).lighter(115)); p.drawEllipse(QRectF(rr.x() + 24, y + 8, 5, 5))
            p.setPen(QColor("#3b4354"))
            p.drawText(br, int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), str(pt))
            y += max(24, h + 10)
        if not (st.get("points") or []):
            p.setPen(QColor("#8a8270")); p.drawText(QRectF(rr.x() + 22, y, rr.width() - 44, 24), int(Qt.AlignmentFlag.AlignLeft), "(no details)")
        # footer: step dots, then the controls
        by = rr.y() + 70 + s.bullets_height(st) + 10; s.btns = {}
        dots = len(s.steps)
        for d in range(dots):
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(s.accent) if d == s.i else QColor("#cfc6b1"))
            p.drawEllipse(QRectF(rr.x() + 22 + d * 11, by + 10, 6, 6))
        def btn(key, x, w, label, filled=False):
            rc = QRectF(x, by, w, 28); s.btns[key] = QRect(int(rc.x()), int(rc.y()), int(rc.width()), int(rc.height()))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(s.accent) if filled else QColor("#e7e0cf"))
            p.drawRoundedRect(rc, 14, 14)
            f = QFont("Segoe UI", 9); f.setBold(filled); p.setFont(f)
            p.setPen(QColor("#ffffff") if filled else QColor("#4a4335"))
            p.drawText(rc, int(Qt.AlignmentFlag.AlignCenter), label)
        x = rr.x() + 24 + dots * 11 + 14
        if s.i > 0: btn("prev", x, 56, "‹ Back"); x += 62
        if s.i < len(s.steps) - 1: btn("next", x, 62, "Next ›", True)
        else: btn("next", x, 62, "Done", True)
        btn("read", rr.right() - 126, 58, "🔊 Read" if s.speak else "🔇 Mute")
        btn("close", rr.right() - 62, 42, "✕")
        p.restore()

    # --- interaction ---
    def mousePressEvent(s, e):
        if e.button() == Qt.MouseButton.LeftButton: s._press = e.position().toPoint()

    def mouseReleaseEvent(s, e):
        if s._press is None or e.button() != Qt.MouseButton.LeftButton: return
        pt = e.position().toPoint(); s._press = None
        for key, rc in s.btns.items():
            if rc.adjusted(-2, -2, 2, 2).contains(pt):
                if key == "prev": s.prev()
                elif key == "next": s.next()
                elif key == "read": s.toggle_speak()
                else: s.close()
                return
        if not s.card_rect().contains(pt): s.close()                  # click anywhere else = dismiss

    def keyPressEvent(s, e):
        if e.key() == Qt.Key.Key_Escape: s.close()
        elif e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_Down): s.next()
        elif e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up): s.prev()
        elif e.key() == Qt.Key.Key_R: s.toggle_speak()

    def closeEvent(s, e):
        s.anim.stop(); s.closed.emit(); super().closeEvent(e)


# ---------- AI cursor: where the assistant's mouse is while Screen control works ----------
class AICursor(QWidget):
    """Click-through, always-on-top pointer with a red outline and an 'AI' tag: looks nothing like the system cursor, so you can always
    tell the assistant's mouse from yours. Positions arrive from the same code that moves the real pointer, so they cannot drift apart."""
    SZ, HOT = 72, 10                                   # window size, and where the pointer tip sits inside it

    def __init__(s):
        super().__init__()
        s.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool |
                         Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        s.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground); s.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        s.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); s.setFixedSize(s.SZ, s.SZ)
        s.pulse = 0.0; s.anim = QTimer(s); s.anim.timeout.connect(s._tick)

    def ripple(s): s.pulse = 1.0; s.anim.start(16)

    def _tick(s):
        s.pulse = max(0.0, s.pulse - 0.07); s.update()
        if s.pulse <= 0: s.anim.stop()

    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHint(QPainter.RenderHint.Antialiasing); h = s.HOT; red = QColor("#ff2d3d")
        g = QRadialGradient(QPointF(h, h), 16); g.setColorAt(0, QColor(255, 45, 61, 110)); g.setColorAt(1, QColor(255, 45, 61, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(g); p.drawEllipse(QPointF(h, h), 16, 16)
        if s.pulse > 0:                                                    # click ripple
            r = 8 + (1 - s.pulse) * 26; c = QColor(red); c.setAlpha(int(220 * s.pulse)); p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(c, 3)); p.drawEllipse(QPointF(h, h), r, r)
        pts = [(0, 0), (0, 25), (6.5, 19.5), (11.5, 30), (16, 28), (11, 17.5), (19.5, 17.5)]
        poly = QPolygonF([QPointF(h + x * 1.05, h + y * 1.05) for x, y in pts])
        p.setPen(QPen(red, 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)); p.setBrush(QColor("#1b1e2b")); p.drawPolygon(poly)
        p.setPen(QPen(QColor(255, 255, 255, 210), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPolygon(poly)
        tag = QRectF(h + 22, h + 24, 28, 17); p.setPen(Qt.PenStyle.NoPen); p.setBrush(red); p.drawRoundedRect(tag, 8, 8)
        p.setPen(QColor("white")); p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold)); p.drawText(tag, Qt.AlignmentFlag.AlignCenter, "AI")


# ---------- region selector ----------
class Selector(QWidget):
    done = pyqtSignal(object)

    def __init__(s, pix, screen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        s.pix = pix; s.a = s.b = None; s.rect_logical = None
        place_on(s, screen); s.setGeometry(screen.geometry()); s.setCursor(Qt.CursorShape.CrossCursor)
        s.setMouseTracking(True)

    def sel(s): return QRect(s.a, s.b).normalized() if s.a and s.b else None

    def src(s, r):
        d = s.pix.devicePixelRatio()
        return QRect(int(r.x() * d), int(r.y() * d), int(r.width() * d), int(r.height() * d))

    def paintEvent(s, e):
        p = QPainter(s); p.drawPixmap(s.rect(), s.pix, s.pix.rect()); p.fillRect(s.rect(), QColor(0, 0, 0, 120))
        r = s.sel()
        if r: p.drawPixmap(r, s.pix, s.src(r)); p.setPen(QPen(QColor("#8ab4f8"), 2)); p.drawRect(r)

    def mousePressEvent(s, e):
        if e.button() == Qt.MouseButton.RightButton: s.finish(None)
        else: s.a = s.b = e.position().toPoint()

    def mouseMoveEvent(s, e):
        if s.a: s.b = e.position().toPoint(); s.update()

    def mouseReleaseEvent(s, e):
        if s.a is None: return                    # release without a press (stray event) must not close the selector
        r = s.sel()
        s.rect_logical = QRect(r).translated(s.geometry().topLeft()) if r and r.width() > 10 and r.height() > 10 else None
        s.finish(s.pix.copy(s.src(r)) if r and r.width() > 10 and r.height() > 10 else None)

    def keyPressEvent(s, e):
        if e.key() == Qt.Key.Key_Escape: s.finish(None)

    def finish(s, pix): s.close(); s.done.emit(pix)


# ---------- canvas: shapes + function plots ----------
PALETTE = ["#8ab4f8", "#f28b82", "#81c995", "#fdd663", "#c58af9", "#ff8bcb", "#78d9ec"]


def nice_step(rng, target=8):
    raw = rng / target
    if raw <= 0: return 1.0
    mag = 10 ** math.floor(math.log10(raw)); f = raw / mag
    return mag * (1 if f < 1.5 else 2 if f < 3.5 else 5 if f < 7.5 else 10)


class Surface(QWidget):
    DEFAULT_VIEW = [-10.0, 10.0, -7.5, 7.5]

    def __init__(s):
        super().__init__(); s.setMinimumSize(480, 360)
        s.view = list(s.DEFAULT_VIEW); s.equal = True; s.shapes = []; s.curves = []; s.strokes = []
        s.pen_mode = False; s._drag = None; s._cur = None

    # coordinate mapping (view is kept consistent with the widget aspect when equal=True)
    def _eff(s):
        x0, x1, y0, y1 = s.view; w, h = max(s.width(), 1), max(s.height(), 1)
        if s.equal:
            yr = (x1 - x0) * h / w; cy = (y0 + y1) / 2; y0, y1 = cy - yr / 2, cy + yr / 2
        s.view = [x0, x1, y0, y1]

    def X(s, x): return (x - s.view[0]) / (s.view[1] - s.view[0]) * s.width()
    def Y(s, y): return s.height() - (y - s.view[2]) / (s.view[3] - s.view[2]) * s.height()

    def inv(s, px, py):
        return (s.view[0] + px / max(s.width(), 1) * (s.view[1] - s.view[0]),
                s.view[2] + (s.height() - py) / max(s.height(), 1) * (s.view[3] - s.view[2]))

    # --- public ops (called by the assistant) ---
    def clear_all(s): s.shapes = []; s.curves = []; s.strokes = []; s.view = list(s.DEFAULT_VIEW); s.equal = True

    def set_view(s, v):
        v = [float(t) for t in v]
        if len(v) != 4 or v[1] <= v[0] or v[3] <= v[2]: raise ValueError("bad view")
        s.view = v

    def plot(s, a):
        if a.get("clear"): s.clear_all()
        exprs = a.get("exprs") or ([a["expr"]] if a.get("expr") else [])
        x0 = float(a.get("xmin", s.view[0] if s.curves else -10)); x1 = float(a.get("xmax", s.view[1] if s.curves else 10))
        if x1 <= x0: raise ValueError("xmax must be greater than xmin")
        xs = np.linspace(x0, x1, 600); ok = []; bad = []
        for e in exprs[:8]:
            try: safe_eval(str(e), xs[:3]); ok.append(str(e))
            except Exception as ex: bad.append(f"{e} ({ex})")
        for e in ok: s.curves.append({"expr": e, "color": PALETTE[len(s.curves) % len(PALETTE)]})
        if "ymin" in a and "ymax" in a and float(a["ymax"]) > float(a["ymin"]):
            y0, y1 = float(a["ymin"]), float(a["ymax"])
        else:
            vals = np.concatenate([safe_eval(c["expr"], xs) for c in s.curves]) if s.curves else np.array([])
            vals = vals[np.isfinite(vals)]
            if vals.size:
                lo, hi = np.percentile(vals, [2, 98]); pad = (hi - lo) * 0.15 or 1.0; y0, y1 = lo - pad, hi + pad
            else: y0, y1 = -5, 5
        s.view = [x0, x1, float(y0), float(y1)]; s.equal = bool(a.get("equal", False)); s.update()
        return f"plotted {len(ok)} function(s)" + (f"; skipped {', '.join(bad)}" if bad else "")

    def _clean(s, sh):
        t = str(sh["type"]).lower(); col = str(sh.get("color") or PALETTE[len(s.shapes) % len(PALETTE)])
        out = {"type": t, "color": col, "fill": sh.get("fill"), "label": str(sh.get("label", "")),
               "labels": [str(x) for x in sh.get("labels", [])]}
        f = lambda k: float(sh[k])
        if t in ("triangle", "polygon", "polyline"):
            if "points" in sh: pts = [[float(p[0]), float(p[1])] for p in sh["points"]]
            else:
                n = int(sh["n"]); r = f("r"); cx, cy = f("cx"), f("cy")
                pts = [[cx + r * math.cos(math.pi / 2 + 2 * math.pi * i / n), cy + r * math.sin(math.pi / 2 + 2 * math.pi * i / n)] for i in range(n)]
            if (t == "triangle" and len(pts) != 3) or len(pts) < 2: raise ValueError("bad points")
            out["points"] = pts
        elif t == "circle": out.update(cx=f("cx"), cy=f("cy"), r=f("r"))
        elif t == "ellipse": out.update(cx=f("cx"), cy=f("cy"), rx=f("rx"), ry=f("ry"))
        elif t == "rect": out.update(x=f("x"), y=f("y"), w=f("w"), h=f("h"))
        elif t == "line": out.update(x1=f("x1"), y1=f("y1"), x2=f("x2"), y2=f("y2"))
        elif t == "point": out.update(x=f("x"), y=f("y"))
        elif t == "text": out.update(x=f("x"), y=f("y"), text=str(sh["text"]))
        else: raise ValueError("unknown shape")
        return out

    def draw(s, a):
        if a.get("clear"): s.clear_all()
        if a.get("view"): s.set_view(a["view"])
        n = bad = 0
        for sh in (a.get("shapes") or [])[:60]:
            try: s.shapes.append(s._clean(sh)); n += 1
            except Exception: bad += 1
        if not s.curves: s.equal = True
        s.update()
        return f"drew {n} shape(s)" + (f", {bad} invalid" if bad else "")

    # --- painting ---
    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHint(QPainter.RenderHint.Antialiasing); s._eff()
        w, h = s.width(), s.height(); x0, x1, y0, y1 = s.view
        p.fillRect(s.rect(), QColor("#17181a")); p.setFont(QFont("Segoe UI", 8))
        sx, sy = nice_step(x1 - x0), nice_step(y1 - y0)
        ax = min(max(s.Y(0), 14), h - 4); ay = min(max(s.X(0), 4), w - 28)
        for gx in np.arange(math.ceil(x0 / sx) * sx, x1 + sx * .5, sx)[:200]:
            p.setPen(QPen(QColor("#2a2c30"), 1)); p.drawLine(QPointF(s.X(gx), 0), QPointF(s.X(gx), h))
            if abs(gx) > sx * 1e-6: p.setPen(QColor("#80868b")); p.drawText(QPointF(s.X(gx) + 2, ax + 11 if ax < h - 16 else ax - 4), f"{gx:g}")
        for gy in np.arange(math.ceil(y0 / sy) * sy, y1 + sy * .5, sy)[:200]:
            p.setPen(QPen(QColor("#2a2c30"), 1)); p.drawLine(QPointF(0, s.Y(gy)), QPointF(w, s.Y(gy)))
            if abs(gy) > sy * 1e-6: p.setPen(QColor("#80868b")); p.drawText(QPointF(ay + 3, s.Y(gy) - 2), f"{gy:g}")
        p.setPen(QPen(QColor("#9aa0a6"), 1.4)); p.drawLine(QPointF(0, s.Y(0)), QPointF(w, s.Y(0))); p.drawLine(QPointF(s.X(0), 0), QPointF(s.X(0), h))
        # function curves are re-sampled for the current view, so panning/zooming stays sharp
        xs = np.linspace(x0, x1, max(300, w * 2)); pxs = (xs - x0) / (x1 - x0) * w
        for c in s.curves:
            try: ys = safe_eval(c["expr"], xs)
            except Exception: continue
            py = h - (ys - y0) / (y1 - y0) * h; ok = np.isfinite(py) & (np.abs(py) < 1e6)
            path = QPainterPath(); prev = False
            for i in range(len(xs)):
                if ok[i] and prev and abs(py[i] - py[i - 1]) <= 2 * h: path.lineTo(pxs[i], py[i])
                elif ok[i]: path.moveTo(pxs[i], py[i])
                prev = bool(ok[i])
            p.setPen(QPen(QColor(c["color"]), 2.2)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
        kx, ky = w / (x1 - x0), h / (y1 - y0)
        for sh in s.shapes:
            col = QColor(sh["color"]); col = col if col.isValid() else QColor("#8ab4f8"); t = sh["type"]
            p.setPen(QPen(col, 2))
            if sh.get("fill") and QColor(str(sh["fill"])).isValid():
                fc = QColor(str(sh["fill"])); fc.setAlpha(80); p.setBrush(fc)
            else: p.setBrush(Qt.BrushStyle.NoBrush)
            if t in ("triangle", "polygon", "polyline"):
                pts = [QPointF(s.X(x), s.Y(y)) for x, y in sh["points"]]
                p.drawPolyline(QPolygonF(pts)) if t == "polyline" else p.drawPolygon(QPolygonF(pts))
                p.setPen(QColor("#e8eaed"))
                for q, lab in zip(pts, sh["labels"]): p.drawText(QPointF(q.x() + 6, q.y() - 6), lab)
            elif t == "circle": p.drawEllipse(QPointF(s.X(sh["cx"]), s.Y(sh["cy"])), sh["r"] * kx, sh["r"] * ky)
            elif t == "ellipse": p.drawEllipse(QPointF(s.X(sh["cx"]), s.Y(sh["cy"])), sh["rx"] * kx, sh["ry"] * ky)
            elif t == "rect": p.drawRect(QRectF(s.X(sh["x"]), s.Y(sh["y"] + sh["h"]), sh["w"] * kx, sh["h"] * ky))
            elif t == "line": p.drawLine(QPointF(s.X(sh["x1"]), s.Y(sh["y1"])), QPointF(s.X(sh["x2"]), s.Y(sh["y2"])))
            elif t == "point":
                p.setBrush(col); p.drawEllipse(QPointF(s.X(sh["x"]), s.Y(sh["y"])), 4, 4)
                p.setPen(QColor("#e8eaed")); p.drawText(QPointF(s.X(sh["x"]) + 7, s.Y(sh["y"]) - 6), sh["label"])
            elif t == "text": p.setPen(col); p.drawText(QPointF(s.X(sh["x"]), s.Y(sh["y"])), sh["text"])
            if sh["label"] and t in ("circle", "rect", "line", "ellipse", "triangle", "polygon"):
                p.setPen(QColor("#e8eaed")); p.drawText(QPointF(8, 28 + 14 * s.shapes.index(sh)), sh["label"])
        p.setPen(QPen(QColor("#fdd663"), 2.5))
        for st in s.strokes + ([s._cur] if s._cur else []):
            if len(st) > 1: p.drawPolyline(QPolygonF([QPointF(s.X(x), s.Y(y)) for x, y in st]))
        for i, c in enumerate(s.curves):                     # legend
            p.setPen(QPen(QColor(c["color"]), 3)); p.drawLine(10, 14 + 16 * i, 28, 14 + 16 * i)
            p.setPen(QColor("#e8eaed")); p.drawText(QPointF(34, 18 + 16 * i), "y = " + c["expr"])

    # --- interaction: wheel zoom, drag pan, pen ---
    def mousePressEvent(s, e):
        if e.button() != Qt.MouseButton.LeftButton: return
        pt = e.position()
        if s.pen_mode: s._cur = [s.inv(pt.x(), pt.y())]
        else: s._drag = (pt, list(s.view))

    def mouseMoveEvent(s, e):
        pt = e.position()
        if s._cur is not None: s._cur.append(s.inv(pt.x(), pt.y())); s.update()
        elif s._drag:
            p0, v = s._drag; dx = (pt.x() - p0.x()) / s.width() * (v[1] - v[0]); dy = (pt.y() - p0.y()) / s.height() * (v[3] - v[2])
            s.view = [v[0] - dx, v[1] - dx, v[2] + dy, v[3] + dy]; s.update()

    def mouseReleaseEvent(s, e):
        if s._cur is not None: s.strokes.append(s._cur); s._cur = None
        s._drag = None; s.update()

    def wheelEvent(s, e):
        f = 0.85 if e.angleDelta().y() > 0 else 1 / 0.85; pt = e.position(); mx, my = s.inv(pt.x(), pt.y()); x0, x1, y0, y1 = s.view
        s.view = [mx - (mx - x0) * f, mx + (x1 - mx) * f, my - (my - y0) * f, my + (y1 - my) * f]; s.update()


class CanvasWindow(QWidget):
    send = pyqtSignal(object)

    def __init__(s):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        s.setWindowTitle("AI Canvas"); s.resize(780, 620)
        s.setStyleSheet("QWidget{background:#202124;color:#e8eaed;font:12px 'Segoe UI'}"
                        "QPushButton{background:#303134;border:none;border-radius:8px;padding:6px 12px}"
                        "QPushButton:hover{background:#3c4043} QPushButton:checked{background:#3b5bdb}")
        s.surface = Surface(); lay = QVBoxLayout(s); lay.setContentsMargins(8, 8, 8, 8)
        bar = QHBoxLayout(); lay.addLayout(bar); lay.addWidget(s.surface, 1)
        s.pen = QPushButton("✏ Pen"); s.pen.setCheckable(True); s.pen.toggled.connect(lambda on: setattr(s.surface, "pen_mode", on))
        b_clear = QPushButton("Clear"); b_reset = QPushButton("Reset view"); b_save = QPushButton("Save PNG"); b_ai = QPushButton("Ask AI about this")
        for b in (s.pen, b_clear, b_reset, b_save): bar.addWidget(b)
        bar.addStretch(); bar.addWidget(b_ai)
        b_clear.clicked.connect(lambda: (s.surface.clear_all(), s.surface.update()))
        b_reset.clicked.connect(s.reset_view)
        b_save.clicked.connect(s.save_png)
        b_ai.clicked.connect(lambda: s.send.emit(s.surface.grab()))

    def reset_view(s): s.surface.view = list(Surface.DEFAULT_VIEW); s.surface.equal = not s.surface.curves; s.surface.update()

    def save_png(s):
        path, _ = QFileDialog.getSaveFileName(s, "Save canvas", "canvas.png", "PNG (*.png)")
        if path: s.surface.grab().save(path, "PNG")

# One flat namespace across the package (it was split out of a single file); exporting
# everything, including the private helpers, keeps the behaviour identical.
__all__ = [n for n in globals() if not n.startswith('__')]
