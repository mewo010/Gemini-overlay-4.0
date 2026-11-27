"""Chat expansion animation: the unfold/fold geometry, its easing and the surface it paints.

The overlay owns the window; this module owns the motion. Keeping the curve, the frame maths and the
ghost-surface painting together makes the opening/closing transition testable without a live overlay,
and lets the orb animation stay completely independent of it.
"""
from dataclasses import dataclass

from .core import *
from .panel import PANEL_RADIUS

OPEN_MS = 480                 # orb -> chat
CLOSE_MS = 300                # chat -> orb
SETTLE_MS = 220               # small height changes while a reply streams in
GROW_END = 0.72               # the surface finishes unfolding here ...
GLIDE_START = 0.40            # ... before the sideways glide dominates
REMNANT_END = 0.42            # how long the orb's own light lingers at the origin
BLOOM_MS = 480


def ease_out_quint(t): return 1.0 - (1.0 - t) ** 5


def ease_in_out(t): return t * t * (3.0 - 2.0 * t)


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
        return QRect(int(round(self.x)), int(round(self.y)), max(1, int(round(self.w))), max(1, int(round(self.h))))


def compute_morph(p, a, b, outward):
    """One frame of the unfold.

    Outward: the surface grows from the orb's nearest corner, a little later in width than in height (so it
    reads as unfolding), then the last stretch slides it sideways into place. Inward: the exact reverse.
    """
    p = max(0.0, min(1.0, float(p)))
    if outward:
        grow = ease_in_out(min(1.0, p / GROW_END))
        glide = ease_in_out(max(0.0, min(1.0, (p - GLIDE_START) / (1.0 - GLIDE_START))))
        w = a.width() + (b.width() - a.width()) * (0.34 * grow + 0.66 * grow * grow)
        h = a.height() + (b.height() - a.height()) * grow
        ax = a.right() - w + 1 if b.center().x() < a.center().x() else float(a.left())
        ay = a.bottom() - h + 1 if b.center().y() < a.center().y() else float(a.top())
        x = ax + (b.x() - ax) * glide
        y = ay + (b.y() - ay) * glide
        inset = 16 * min(1.0, p / 0.45)
        radius = a.width() / 2 + (PANEL_RADIUS - a.width() / 2) * ease_out_quint(min(1.0, p / 0.75))
    else:
        e = ease_in_out(p)
        w = a.width() + (b.width() - a.width()) * e
        h = a.height() + (b.height() - a.height()) * e
        x = a.x() + (b.x() - a.x()) * e
        y = a.y() + (b.y() - a.y()) * e
        inset = 16 * max(0.0, 1.0 - p / 0.55)
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
    c = QPointF(origin); rad = 60 + 340 * bloom
    c.setX(max(6.0, min(c.x(), size.width() - 6.0))); c.setY(max(6.0, min(c.y(), size.height() - 6.0)))
    g = QRadialGradient(c, rad)
    k = (1 - bloom) ** 1.6
    g.setColorAt(0, _alpha(accent.lighter(150), 120 * k))
    g.setColorAt(.55, _alpha(accent, 60 * k))
    g.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
    painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(g); painter.drawEllipse(c, rad, rad)


def paint_orb_remnant(painter, origin, width, aura, k):
    """The orb's aura lingering where the surface emerges; k fades from 1 to 0 early in the unfold."""
    if k <= 0: return
    r = max(24.0, width * 0.34)
    g = QRadialGradient(QPointF(origin), r)
    g.setColorAt(0, _alpha(aura, 105 * k))
    g.setColorAt(0.55, _alpha(aura, 34 * k))
    g.setColorAt(1, _alpha(aura, 0))
    painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(g)
    painter.drawEllipse(QPointF(origin), r, r)


__all__ = [n for n in globals() if not n.startswith('__')]
