"""Orb animation system: the painted black hole, its idle/thinking timing, hover, opening and drag behaviour.

All motion of the collapsed orb lives here so the overlay window only wires signals to it.
Motion is time-based (delta time), so it stays smooth and the same speed at any frame rate.
"""
import time
from .core import *

ORB_FRAME_MS = 16          # ~60 fps while the orb is visible (the timer stops when it is hidden)
ORB_CLOCK_RATE = 1.25      # disk rotation speed (clock units per second)
ORB_THINK_RATE = 1.50      # extra speed while thinking
ORB_HOVER_RATE = 9.0       # easing rates (1/seconds): higher = snappier
ORB_THINK_RATE_EASE = 3.5
ORB_APPEAR_RATE = 7.0
ORB_OPEN_SECONDS = 0.80    # length of the opening burst


def should_hover_expand(visible, collapsed, closing, dragging, settings_open, enabled, over_orb):
    """Hover-to-open policy, kept next to the orb it belongs to (Settings must never trigger it)."""
    return bool(visible and collapsed and not closing and not dragging and not settings_open
                and enabled and over_orb)


def _rgba(color, alpha):
    """A copy of a colour with a clamped alpha (Qt wants 0..255 ints)."""
    c = QColor(color); c.setAlpha(max(0, min(255, int(alpha)))); return c


def _clamp01(x):
    return max(0.0, min(1.0, x))


def _smooth(x):
    """Smoothstep: gentle start and end."""
    x = _clamp01(x); return x * x * (3 - 2 * x)


def _ease_out(x):
    """Cubic ease-out: fast start, soft landing."""
    x = _clamp01(x); return 1 - (1 - x) ** 3


def _damp(cur, target, rate, dt):
    """Frame-rate independent exponential easing toward a target."""
    return cur + (target - cur) * (1 - math.exp(-rate * dt))


def px_room(c, R):
    """How far the aura may spread before it would be clipped by the (square) orb window."""
    return max(R * 1.5, min(c.x(), c.y()) - 2)


def paint_black_hole(p, c, R, accent, aura, clock, think=0.0, glow=1.0, waves=0.0, level=0.0, burst=0.0):
    """A miniature black hole, drawn from primitives so it stays crisp at every orb size.

    Layers, back to front: the soft aura (its own colour), a tilted accretion disk whose colours sweep
    around the hole, a photon ring, then the near-black event horizon with a faint coloured energy core
    and one hot bead travelling on the disk. `think` (0..1) brightens and speeds everything up while the
    model is working. `burst` (0..1, 1 = start) drives the opening shockwave and glow flash.
    """
    accent = QColor(accent) if QColor(accent).isValid() else QColor("#6c8cf5")
    aura = QColor(aura) if QColor(aura).isValid() else QColor(accent)
    light = accent.lighter(165)
    think = _clamp01(float(think))
    burst = _clamp01(float(burst))
    flash = burst * burst                                   # glow flash fades quickly
    breath = 1.0 + 0.035 * math.sin(clock * 1.6)
    room = px_room(c, R)

    # --- atmosphere: a wide, soft aura in its own colour ---
    ar = min(R * (2.05 + 0.06 * think + 0.18 * flash) * breath, room)
    g = QRadialGradient(c, ar)
    g.setColorAt(0.00, _rgba(aura, (108 + 44 * think + 70 * flash) * glow))
    g.setColorAt(0.36, _rgba(aura, (54 + 26 * think + 40 * flash) * glow))
    g.setColorAt(0.72, _rgba(aura, 17 * glow))
    g.setColorAt(1.00, _rgba(aura, 0))
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(g); p.drawEllipse(c, ar, ar)

    # --- accretion disk: tilted ellipses stroked with a sweeping colour ---
    p.save(); p.translate(c); p.rotate(-16)
    rx, ry = R * 1.95, R * 0.52
    boost = think + 0.6 * flash
    for k, (sc, width, alpha) in enumerate(((1.00, 0.24, 120), (0.83, 0.13, 190), (1.15, 0.07, 60))):
        sweep = QConicalGradient(QPointF(0, 0), math.degrees(clock * (0.55 + 1.1 * think) * (1 if k % 2 == 0 else -1)))
        sweep.setColorAt(0.00, _rgba(accent, 0))
        sweep.setColorAt(0.14, _rgba(light, alpha * (0.55 + 0.45 * boost)))
        sweep.setColorAt(0.36, _rgba(accent, alpha * 0.85))
        sweep.setColorAt(0.60, _rgba(accent, alpha * 0.20))
        sweep.setColorAt(0.82, _rgba(accent, 0))
        sweep.setColorAt(1.00, _rgba(accent, 0))
        pen = QPen(QBrush(sweep), max(0.9, R * width), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(-rx * sc, -ry * sc, rx * sc * 2, ry * sc * 2))
    p.restore()

    # --- one hot bead travelling along the disk ---
    ang = clock * (0.9 + 1.4 * think)
    dx, dy = math.cos(ang) * rx * 0.98, math.sin(ang) * ry * 0.98
    tilt = math.radians(-16)
    bx, by = c.x() + dx * math.cos(tilt) - dy * math.sin(tilt), c.y() + dx * math.sin(tilt) + dy * math.cos(tilt)
    bead = QRadialGradient(QPointF(bx, by), R * 0.16)
    bead.setColorAt(0, _rgba(QColor(255, 255, 255), 120 + 70 * boost))
    bead.setColorAt(0.4, _rgba(light, 110))
    bead.setColorAt(1, _rgba(accent, 0))
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(bead); p.drawEllipse(QPointF(bx, by), R * 0.16, R * 0.16)

    # --- photon ring: a thin rim plus a brighter arc that turns slowly ---
    pr = R * 1.02
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_rgba(aura, 46 + 30 * think + 40 * flash), max(0.8, R * 0.022)))
    p.drawEllipse(c, pr, pr)
    rim = QConicalGradient(QPointF(c.x(), c.y()), math.degrees(-clock * 0.8))
    rim.setColorAt(0.00, _rgba(light, 20))
    rim.setColorAt(0.18, _rgba(light, 190 + 60 * boost))
    rim.setColorAt(0.42, _rgba(accent, 120 + 60 * boost))
    rim.setColorAt(0.70, _rgba(accent, 30))
    rim.setColorAt(1.00, _rgba(light, 20))
    p.setPen(QPen(QBrush(rim), max(1.0, R * 0.06), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawEllipse(c, pr, pr)

    # --- the event horizon: almost black, with a whisper of colour inside ---
    core = QRadialGradient(QPointF(c.x() - R * 0.26, c.y() - R * 0.30), R * 1.85)
    core.setColorAt(0.00, QColor(13, 15, 22))
    core.setColorAt(0.42, QColor(6, 7, 12))
    core.setColorAt(0.80, QColor(1, 1, 3))
    core.setColorAt(1.00, QColor(0, 0, 0))
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(core); p.drawEllipse(c, R, R)
    inner = QRadialGradient(c, R * 0.72)
    inner.setColorAt(0, _rgba(accent, 26 + 30 * think + 40 * flash))
    inner.setColorAt(0.55, _rgba(accent, 10 + 14 * think + 16 * flash))
    inner.setColorAt(1, _rgba(accent, 0))
    p.setBrush(inner); p.drawEllipse(c, R * 0.72, R * 0.72)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_rgba(accent, 55 + 55 * think), max(0.8, R * 0.018)))
    p.drawEllipse(c, R * 0.995, R * 0.995)

    # --- the near half of the disk passes IN FRONT of the shadow: that is what makes it a black hole ---
    p.save(); p.translate(c); p.rotate(-16)
    front = QConicalGradient(QPointF(0, 0), math.degrees(clock * (0.55 + 1.1 * think) + 1.6))
    front.setColorAt(0.00, _rgba(accent, 40))
    front.setColorAt(0.18, _rgba(light, 120 + 60 * boost))
    front.setColorAt(0.40, _rgba(accent, 170 + 50 * boost))
    front.setColorAt(0.62, _rgba(accent, 40))
    front.setColorAt(1.00, _rgba(accent, 40))
    p.setPen(QPen(QBrush(front), max(0.9, R * 0.10), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(-rx * 0.86, -ry * 0.86, rx * 1.72, ry * 1.72), 180 * 16, 180 * 16)
    p.restore()

    # --- opening shockwave: one clean ring leaving the horizon, thinning and fading as it goes ---
    if burst > 0.01:
        e = _ease_out(1.0 - burst)                          # 0 -> 1 as the burst plays
        wr = min(R * (1.08 + 1.15 * e), room)
        fade = (1.0 - e) ** 1.6
        for width, a in ((0.16, 70), (0.05, 190)):         # soft halo + crisp core
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_rgba(light, a * fade), max(0.8, R * width * (1.0 - 0.6 * e))))
            p.drawEllipse(c, wr, wr)

    # --- gentle voice rings while speaking, in the aura colour ---
    if waves > 0.01:
        amp = R * (0.05 + min(1.0, level * 2.5) * 0.08)
        for k in range(2):
            rad = R * (1.30 + k * 0.20) + 2.4 * math.sin(clock * 2.0 + k)
            path = QPainterPath()
            for i in range(73):
                th = 2 * math.pi * i / 72
                rr = rad + amp * math.sin(5 * th + clock * 2.6 + k * 1.4)
                pt = QPointF(c.x() + rr * math.cos(th), c.y() + rr * math.sin(th))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            path.closeSubpath()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_rgba(aura, (110 - k * 40) * waves), max(1.0, R * (0.07 - k * 0.02))))
            p.drawPath(path)


class Orb(QWidget):
    """The small black hole in the chat's top row, tinted with the chat accent so the panel matches the big orb."""
    def __init__(s):
        super().__init__(); s.setFixedSize(46, 46); s.mode = "idle"; s.level = 0.0; s.t = 0.0
        s.color = QColor("#6c8cf5"); s.aura = QColor("#6c8cf5"); s._last = None

    def set_color(s, color):
        c = color if isinstance(color, QColor) else QColor(str(color))
        if c.isValid(): s.color = c; s.update()

    def set_colors(s, color, aura=None):
        s.set_color(color)
        a = aura if isinstance(aura, QColor) else QColor(str(aura)) if aura else None
        if a is not None and a.isValid(): s.aura = a; s.update()

    def paintEvent(s, e):
        now = time.perf_counter()
        dt = 0.016 if s._last is None else min(0.05, now - s._last)
        s._last = now
        s.t += (ORB_CLOCK_RATE + (0.9 if s.mode == "thinking" else 0.0)) * dt
        p = QPainter(s); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        think = 1.0 if s.mode == "thinking" else 0.0
        glow = 1.0 + (0.35 if s.mode == "listening" else 0.0) + (0.25 if s.mode == "speaking" else 0.0)
        paint_black_hole(p, QPointF(23, 23), 9.6, s.color, s.aura, s.t, think=think, glow=glow,
                         waves=1.0 if s.mode == "speaking" else 0.0, level=s.level)


class AIOrb(QWidget):
    """The collapsed overlay: a small, mysterious black hole docked where you like.

    A near-black core, a coloured accretion disk, a photon ring and a soft aura in its own colour. Hovering
    brightens it and opens the overlay; dragging docks it in a new place. When the AI thinks, the disk turns
    faster and the aura breathes. When it appears it fades and scales in with a single shockwave ring
    (call `play_open()` to replay that at any time).
    """
    clicked = pyqtSignal(); move_by = pyqtSignal(int, int); released = pyqtSignal()

    def __init__(s, size=96, color="#6c8cf5", aura=None):
        super().__init__()
        s.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        s.setFixedSize(size, size); s.setCursor(Qt.CursorShape.PointingHandCursor)
        s.setToolTip("AI Overlay - hover to open  ·  drag to move")
        s.mode = "idle"; s.level = 0.0; s.clock = 0.0; s.hover = False; s._drag = None; s._moved = False
        s.hv = 0.0; s.bob = 0.0; s.think = 0.0      # eased hover / idle float / eased thinking amount
        s.appear = 1.0                               # eased 0..1 fade/scale-in
        s.burst = 0.0                                # 1 -> 0 while the opening burst plays
        s._open_t = 1.0; s._last = None
        c = QColor(color); s.color = c if c.isValid() else QColor("#6c8cf5")
        a = QColor(aura) if aura and QColor(aura).isValid() else QColor(s.color)
        s.aura = a
        s.anim = QTimer(s); s.anim.setTimerType(Qt.TimerType.PreciseTimer)
        s.anim.timeout.connect(s._tick)              # runs only while the orb is actually on screen

    def play_open(self):
        """Replay the opening: soft fade/scale-in, glow flash and one shockwave ring."""
        self.appear = 0.0; self._open_t = 0.0; self.burst = 1.0

    def _tick(s):
        now = time.perf_counter()
        dt = 0.016 if s._last is None else min(0.05, now - s._last)   # clamp so a stall never makes a jump
        s._last = now
        s.hv = _damp(s.hv, 1.0 if s.hover else 0.0, ORB_HOVER_RATE, dt)
        s.think = _damp(s.think, 1.0 if s.mode == "thinking" else 0.0, ORB_THINK_RATE_EASE, dt)
        s.appear = _damp(s.appear, 1.0, ORB_APPEAR_RATE, dt)
        if s._open_t < 1.0:
            s._open_t = min(1.0, s._open_t + dt / ORB_OPEN_SECONDS)
            s.burst = 1.0 - _smooth(s._open_t)
        else:
            s.burst = 0.0
        # the disk spins up a little during the opening, then settles back
        s.clock += (ORB_CLOCK_RATE + ORB_THINK_RATE * s.think + 2.0 * s.burst) * dt
        s.bob = 1.2 * math.sin(s.clock * 0.55)
        s.update()

    def set_color(s, color):
        c = color if isinstance(color, QColor) else QColor(str(color))
        if c.isValid(): s.color = c; s.update()

    def set_colors(s, color, aura=None):
        """The energy colour and the aura colour are independent; aura=None keeps the current aura."""
        s.set_color(color)
        if aura is not None:
            a = aura if isinstance(aura, QColor) else QColor(str(aura))
            if a.isValid(): s.aura = a; s.update()

    def showEvent(s, e):
        super().showEvent(e)
        s._last = None
        s.play_open()                                # every time the orb shows, it opens nicely
        if not s.anim.isActive(): s.anim.start(ORB_FRAME_MS)

    def hideEvent(s, e):
        s.anim.stop()                                # no timer work while the chat covers the orb
        super().hideEvent(e)

    def enterEvent(s, e): s.hover = True; s.update()
    def leaveEvent(s, e): s.hover = False; s.update()

    def mousePressEvent(s, e):
        if e.button() == Qt.MouseButton.LeftButton: s._drag = e.globalPosition().toPoint(); s._moved = False

    def mouseMoveEvent(s, e):
        if s._drag is None: return
        p = e.globalPosition().toPoint(); d = p - s._drag
        if not s._moved and d.manhattanLength() < 4: return
        s._moved = True; s.move_by.emit(d.x(), d.y()); s._drag = p

    def mouseReleaseEvent(s, e):
        if s._drag is None: return
        s._drag = None
        if s._moved: s.released.emit()
        else: s.clicked.emit()

    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = s.width(); R = w * 0.23 * (1.0 + 0.035 * s.hv)       # hovering swells it very slightly
        c = QPointF(w / 2, w / 2 + s.bob)
        glow = 1.0 + 0.30 * s.hv + (0.25 if s.mode == "listening" else 0.0)
        waves = 1.0 if s.mode == "speaking" else 0.0
        ap = _smooth(s.appear)
        if ap < 0.999:                                           # fade + scale in from 82%
            k = 0.82 + 0.18 * ap
            p.setOpacity(ap)
            p.translate(c); p.scale(k, k); p.translate(-c.x(), -c.y())
        paint_black_hole(p, c, R, s.color, s.aura, s.clock, think=s.think, glow=glow,
                         waves=waves, level=s.level, burst=s.burst)

__all__ = [n for n in globals() if not n.startswith('__')]
