"""Chat expansion animation: the unfold/fold geometry, its easing and the surface it paints.

The overlay owns the window; this module owns the motion. Keeping the curve, the frame maths and the
ghost-surface painting together makes the opening/closing transition testable without a live overlay,
and lets the orb animation stay completely independent of it.
"""
from dataclasses import dataclass

from .core import *
from .panel import PANEL_RADIUS

OPEN_MS = 520                 # orb -> chat
CLOSE_MS = 340                # chat -> orb
SETTLE_MS = 220               # small height changes while a reply streams in
GROW_END = 0.78               # the surface finishes unfolding here ...
GLIDE_START = 0.22            # ... while the sideways glide already blends in (one flowing path, no stages)
REMNANT_END = 0.42            # how long the orb's own light lingers at the origin
BLOOM_MS = 520


def _c01(t): return max(0.0, min(1.0, t))


def ease_out_quint(t): t = _c01(t); return 1.0 - (1.0 - t) ** 5


def ease_out_quart(t): t = _c01(t); return 1.0 - (1.0 - t) ** 4


def ease_in_out(t): t = _c01(t); return t * t * (3.0 - 2.0 * t)


def smootherstep(t):
    """Quintic ease: zero velocity AND zero acceleration at both ends, so nothing ever snaps or stalls."""
    t = _c01(t); return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


@dataclass
class MorphFrame:
    p: float
    x: float
    y: float
    w: float
    h: float
    radius: float
    inset: float

    def rect(self):
        # Snap the EDGES to pixels, not x/w separately: the surface then never jitters by a pixel
        # while it grows (rounding width and position independently makes edges wobble).
        x0, y0 = int(round(self.x)), int(round(self.y))
        x1, y1 = int(round(self.x + self.w)), int(round(self.y + self.h))
        return QRect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))


def compute_morph(p, a, b, outward):
    """One frame of the unfold.

    Outward: the surface grows from the orb's nearest corner - height first and a touch ahead of width, so it
    reads as unfolding - while it glides toward its final spot as ONE continuous motion (the two curves
    overlap and both ease to a complete stop). Inward: the matching, slightly quicker fold.
    """
    p = _c01(float(p))
    if outward:
        grow = ease_out_quart(min(1.0, p / GROW_END))           # responsive start, soft landing
        grow = grow * 0.55 + smootherstep(min(1.0, p / GROW_END)) * 0.45
        glide = smootherstep((p - GLIDE_START) / (1.0 - GLIDE_START))
        gw = grow * (0.60 + 0.40 * grow)                         # width trails height slightly
        w = a.width() + (b.width() - a.width()) * gw
        h = a.height() + (b.height() - a.height()) * grow
        ax = a.right() - w + 1 if b.center().x() < a.center().x() else float(a.left())
        ay = a.bottom() - h + 1 if b.center().y() < a.center().y() else float(a.top())
        x = ax + (b.x() - ax) * glide
        y = ay + (b.y() - ay) * glide
        inset = 16 * smootherstep(min(1.0, p / 0.45))            # content margin eases in with the surface
        radius = a.width() / 2 + (PANEL_RADIUS - a.width() / 2) * ease_out_quint(min(1.0, p / 0.80))
    else:
        e = smootherstep(p)
        w = a.width() + (b.width() - a.width()) * e
        h = a.height() + (b.height() - a.height()) * e
        x = a.x() + (b.x() - a.x()) * e
        y = a.y() + (b.y() - a.y()) * e
        inset = 16 * (1.0 - smootherstep(p / 0.55))
        radius = a.width() / 2 + (b.width() / 2 - a.width() / 2) * e
    return MorphFrame(p, x, y, w, h, radius, inset)


def _alpha(color, alpha):
    c = QColor(color); c.setAlpha(max(0, min(255, int(alpha)))); return c


def paint_panel_frame(painter, rect, radius, accent):
    """The faint accent halo + soft shadow that make the panel read as the orb's light."""
    painter.setPen(Qt.PenStyle.NoPen)
    for i in range(6, 0, -1):
        painter.setBrush(_alpha(accent, 20 * (1 - (i - 1) / 6) ** 2))
        painter.drawRoundedRect(rect.adjusted(-i, -i, i, i), radius + i, radius + i)
    for i in range(10):
        painter.setBrush(QColor(0, 0, 0, int(34 * (1 - i / 10) ** 2)))
        painter.drawRoundedRect(rect.adjusted(-i, -i + 4, i, i + 4), radius + i, radius + i)


def paint_ghost_surface(painter, rect, radius, surface):
    """Exactly the surface #panel is styled with, painted at the interpolated size during the morph."""
    fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    fill.setColorAt(0, surface["top"]); fill.setColorAt(1, surface["bot"])
    rad = min(float(radius), rect.height() / 2, rect.width() / 2)
    painter.setBrush(fill); painter.setPen(Qt.PenStyle.NoPen); painter.drawRoundedRect(rect, rad, rad)
    painter.setBrush(Qt.BrushStyle.NoBrush); painter.setPen(QPen(surface["edge"], 1))
    painter.drawRoundedRect(rect, rad, rad)


def paint_bloom(painter, origin, size, accent, bloom):
    """Light spilling out of the orb while the chat unfolds (fades as the surface reaches full size)."""
    if bloom <= 0: return
    c = QPointF(origin); rad = 60 + 340 * ease_out_quart(bloom)
    c.setX(max(6.0, min(c.x(), size.width() - 6.0))); c.setY(max(6.0, min(c.y(), size.height() - 6.0)))
    g = QRadialGradient(c, rad)
    k = (1 - bloom) ** 1.8 * smootherstep(bloom / 0.10)          # fades in over the first instant, then out
    g.setColorAt(0, _alpha(accent.lighter(150), 120 * k))
    g.setColorAt(.55, _alpha(accent, 60 * k))
    g.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
    painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(g); painter.drawEllipse(c, rad, rad)


def paint_orb_remnant(painter, origin, width, aura, k):
    """The orb's aura lingering where the surface emerges; k fades from 1 to 0 early in the unfold."""
    if k <= 0: return
    k = smootherstep(k)                                          # no hard cut when it disappears
    r = max(24.0, width * 0.34)
    g = QRadialGradient(QPointF(origin), r)
    g.setColorAt(0, _alpha(aura, 105 * k))
    g.setColorAt(0.55, _alpha(aura, 34 * k))
    g.setColorAt(1, _alpha(aura, 0))
    painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(g)
    painter.drawEllipse(QPointF(origin), r, r)


__all__ = [n for n in globals() if not n.startswith('__')]
