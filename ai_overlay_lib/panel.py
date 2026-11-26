"""The chat panel's surface description and stylesheet, shared by the real panel and the unfold ghost."""
from .core import *

PANEL_RADIUS = 24


def panel_surface(accent):
    """The chat panel's own surface - gradient stops, edge and corner radius - described in ONE place.

    overlay_qss() styles the real #panel from this and Overlay.paintEvent() paints the ghost that grows out
    of the orb from it, so the unfolding capsule can never drift away from the panel it becomes."""
    a = QColor(accent) if QColor(accent).isValid() else QColor("#6c8cf5")
    return {"top": mix_color(QColor("#1f222b"), a, 0.10), "bot": mix_color(QColor("#16181e"), a, 0.06),
            "edge": mix_color(QColor("#2c313d"), a, 0.32), "radius": PANEL_RADIUS}


def overlay_qss(accent):
    """The chat panel's stylesheet, generated from its accent colour so the Orb and the Chat share one theme.

    Every surface stays dark and legible; the accent only tints the panel, its edge, the focus ring, selection,
    checked buttons and the small highlight labels - the same places the Orb's glow uses that colour."""
    a = QColor(accent) if QColor(accent).isValid() else QColor("#6c8cf5")
    surf = panel_surface(accent)
    vals = {
        "accent": a.name(), "light": a.lighter(145).name(), "pale": a.lighter(185).name(),
        "top": surf["top"].name(), "bot": surf["bot"].name(), "edge": surf["edge"].name(),
        "rad": str(surf["radius"]), "field": mix_color(QColor("#12141a"), a, 0.06).name(),
        "soft": mix_color(QColor("#272b36"), a, 0.08).name(), "hover": mix_color(QColor("#31364a"), a, 0.14).name(),
        "chip": mix_color(QColor("#1b1e27"), a, 0.14).name(), "quick": mix_color(QColor("#232842"), a, 0.30).name(),
        "quick2": mix_color(QColor("#2e3560"), a, 0.30).name(), "drawer": mix_color(QColor("#13151b"), a, 0.07).name(),
        "bar": mix_color(QColor("#303546"), a, 0.22).name()}
    qss = """
    #panel{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 @top@,stop:1 @bot@);border:1px solid @edge@;border-radius:@rad@px}
    QLabel{color:#9aa3b8;font:13px 'Segoe UI'}
    QPushButton{background:@soft@;color:#e8ebf4;border:none;border-radius:14px;padding:6px 13px;font:12px 'Segoe UI'}
    QPushButton:hover{background:@hover@} QPushButton:pressed{background:#222633}
    QPushButton:checked{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 @accent@,stop:1 @light@);color:#fff}
    QLineEdit{background:@field@;color:#eef1fa;border:1px solid #272b38;border-radius:17px;padding:9px 16px;font:14px 'Segoe UI';selection-background-color:@accent@}
    QLineEdit:focus{border:1px solid @accent@}
    QTextBrowser{background:transparent;color:#e8ebf4;border:none;font:14px 'Segoe UI'}
    QLabel#src{color:@light@;font:11px 'Segoe UI'} QLabel#execl{background:@chip@;border:1px solid @edge@;border-radius:10px;padding:7px 10px;color:#c3c9d9;font:12px 'Segoe UI'}
    QPushButton#mic_live{background:#c62839;color:#fff}
    QFrame#chip{background:@chip@;border:1px solid @edge@;border-radius:14px}
    QLabel#thumb{background:#0f1116;border-radius:8px} QLabel#chiptitle{color:@pale@;font:600 12px 'Segoe UI'}
    QPushButton#quick{background:@quick@;color:@pale@;border-radius:11px;padding:4px 11px;font:11px 'Segoe UI'} QPushButton#quick:hover{background:@quick2@}
    QPushButton#chipx,QPushButton#nx{background:transparent;color:#7d869c;padding:0;border-radius:11px} QPushButton#chipx:hover,QPushButton#nx:hover{background:#2b3040;color:#fff}
    QFrame#drawer{background:@drawer@;border-left:1px solid @edge@;border-top-right-radius:@rad@px;border-bottom-right-radius:@rad@px}
    QLabel#dtitle{color:#fff;font:600 14px 'Segoe UI'} QLabel#dempty{color:#6f778c;font:12px 'Segoe UI'}
    QPushButton#link{background:transparent;color:@light@;padding:2px 6px;font:11px 'Segoe UI'} QPushButton#link:hover{color:#fff}
    QFrame#ncard{background:@chip@;border:1px solid @edge@;border-radius:14px}
    QLabel#napp{color:@light@;font:600 11px 'Segoe UI'} QLabel#ntime{color:#6f778c;font:11px 'Segoe UI'}
    QLabel#ntitle{color:#fff;font:600 13px 'Segoe UI'} QLabel#nbody{color:#c3c9d9;font:12px 'Segoe UI'} QLabel#nres{color:#7be3c0;font:11px 'Segoe UI'}
    QLineEdit#nreply{border-radius:13px;padding:5px 11px;font:12px 'Segoe UI'}
    QPushButton#nsend{background:@accent@;color:#fff;border-radius:14px;padding:0;font:600 14px 'Segoe UI'} QPushButton#nsend:hover{background:@light@}
    QScrollArea,QScrollArea>QWidget>QWidget{background:transparent;border:none}
    QScrollBar:vertical{background:transparent;width:8px} QScrollBar::handle:vertical{background:@bar@;border-radius:4px;min-height:24px}
    QScrollBar::add-line,QScrollBar::sub-line{height:0}
    QToolTip{background:@chip@;color:#e8ebf4;border:1px solid @edge@;padding:5px}"""
    for k, v in vals.items(): qss = qss.replace("@" + k + "@", v)
    return qss

# One flat namespace across the package (it was split out of a single file); exporting
# everything, including the private helpers, keeps the behaviour identical.
__all__ = [n for n in globals() if not n.startswith('__')]
