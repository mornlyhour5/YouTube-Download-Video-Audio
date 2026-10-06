"""
ui_style.py - professional flat theme, vector icons and stylesheets for the
downloader. Drop this next to your main script and import from it.
"""
import math
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QPixmap, QPainter, QPen, QColor, QIcon, QPainterPath, QPolygonF

# ── Palettes ──────────────────────────────────────────────────────────────────
THEMES = {
    "light": {
        "bg": "#F3F4F7", "surface": "#FFFFFF", "raised": "#EEF0F4", "card": "#F7F8FA",
        "border": "#E2E5EC", "text": "#1B2030", "text2": "#586073", "muted": "#8A92A4",
        "accent": "#DDA520", "accent_hover": "#E8B63A", "accent_press": "#BF8C12",
        "accent_text": "#946A00", "accent_soft": "#FBF0CF", "on_accent": "#1A1405",
        "danger": "#C9473A", "danger_soft": "#FBE9E6", "success": "#2F9A55",
        "input": "#FFFFFF", "row_hover": "#FAF8F0",
        "progress_bg": "#E6E9EF", "progress_border": "#CDD2DC", "dim": "#8A92A4",
    },
    "dark": {
        "bg": "#0E1014", "surface": "#151821", "raised": "#1D212C", "card": "#1B1F2A",
        "border": "#272C38", "text": "#E9ECF2", "text2": "#A3AABB", "muted": "#6B7385",
        "accent": "#E3B341", "accent_hover": "#EEC45E", "accent_press": "#C99A2B",
        "accent_text": "#E3B341", "accent_soft": "#2B2415", "on_accent": "#17130A",
        "danger": "#F0705F", "danger_soft": "#2A1B19", "success": "#52C07A",
        "input": "#0F1218", "row_hover": "#191D27",
        "progress_bg": "#262B36", "progress_border": "#343B4A", "dim": "#6B7385",
    },
}


# ── Vector icons (no emoji / font dependence, recoloured per theme) ───────────
def make_icon(name, color, size=18):
    scale = 2
    px = QPixmap(size * scale, size * scale)
    px.setDevicePixelRatio(scale)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    col = QColor(color)
    p.setPen(QPen(col, s * 0.10, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    c = s / 2

    def pt(x, y):
        return QPointF(x * s, y * s)

    def rays(r1, r2, n=8):
        for i in range(n):
            a = 2 * math.pi * i / n
            p.drawLine(QPointF(c + math.cos(a) * r1 * s, c + math.sin(a) * r1 * s),
                       QPointF(c + math.cos(a) * r2 * s, c + math.sin(a) * r2 * s))

    if name == "plus":
        p.drawLine(pt(.5, .2), pt(.5, .8))
        p.drawLine(pt(.2, .5), pt(.8, .5))
    elif name == "download":
        p.drawLine(pt(.5, .15), pt(.5, .62))
        p.drawPolyline(QPolygonF([pt(.3, .44), pt(.5, .64), pt(.7, .44)]))
        p.drawPolyline(QPolygonF([pt(.16, .72), pt(.16, .86), pt(.84, .86), pt(.84, .72)]))
    elif name == "folder":
        path = QPainterPath()
        path.moveTo(pt(.12, .26)); path.lineTo(pt(.38, .26)); path.lineTo(pt(.47, .36))
        path.lineTo(pt(.88, .36)); path.lineTo(pt(.88, .80)); path.lineTo(pt(.12, .80))
        path.closeSubpath()
        p.drawPath(path)
    elif name == "close":
        p.drawLine(pt(.3, .3), pt(.7, .7))
        p.drawLine(pt(.7, .3), pt(.3, .7))
    elif name == "gear":
        p.drawEllipse(QPointF(c, c), s * .26, s * .26)
        p.drawEllipse(QPointF(c, c), s * .09, s * .09)
        rays(.34, .44)
    elif name == "clock":
        p.drawEllipse(QPointF(c, c), s * .38, s * .38)
        p.drawLine(pt(.5, .5), pt(.5, .28))
        p.drawLine(pt(.5, .5), pt(.67, .58))
    elif name == "sun":
        p.drawEllipse(QPointF(c, c), s * .17, s * .17)
        rays(.30, .42)
    elif name == "moon":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        full = QPainterPath(); full.addEllipse(QPointF(c, c), s * .36, s * .36)
        cut = QPainterPath(); cut.addEllipse(QPointF(c + s * .17, c - s * .10), s * .30, s * .30)
        p.drawPath(full.subtracted(cut))
    p.end()
    return QIcon(px)


# ── Stylesheets ───────────────────────────────────────────────────────────────
def build_main_qss(t):
    return f"""
    QMainWindow, QWidget#root {{ background: {t['bg']}; }}
    QWidget {{ font-family: 'Segoe UI', Arial, sans-serif; }}
    QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 4px 8px; }}

    /* Toolbar */
    QWidget#toolbar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
    QPushButton#pasteBtn, QPushButton#dlAllBtn {{
        background: {t['accent']}; color: {t['on_accent']}; border: none;
        border-radius: 8px; padding: 0 16px; font-weight: 600;
    }}
    QPushButton#pasteBtn:hover, QPushButton#dlAllBtn:hover {{ background: {t['accent_hover']}; }}
    QPushButton#pasteBtn:pressed, QPushButton#dlAllBtn:pressed {{ background: {t['accent_press']}; }}
    QPushButton#dlAllBtn:disabled {{ background: {t['raised']}; color: {t['muted']}; }}

    QPushButton#themeBtn, QPushButton#headerSettingsBtn {{
        background: {t['surface']}; color: {t['text2']};
        border: 1px solid {t['border']}; border-radius: 8px; padding: 0 12px;
    }}
    QPushButton#themeBtn:hover, QPushButton#headerSettingsBtn:hover {{
        background: {t['raised']}; color: {t['text']};
    }}

    QWidget#toggleContainer {{ background: {t['raised']}; border: 1px solid {t['border']}; border-radius: 9px; }}
    QPushButton#toggleActive {{
        background: {t['accent']}; color: {t['on_accent']}; border: none;
        border-radius: 6px; padding: 0 18px; font-weight: 600;
    }}
    QPushButton#toggleInactive {{
        background: transparent; color: {t['text2']}; border: none; border-radius: 6px; padding: 0 18px;
    }}
    QPushButton#toggleInactive:hover {{ color: {t['text']}; }}

    QComboBox#qualityCombo {{
        background: {t['input']}; color: {t['text']};
        border: 1px solid {t['border']}; border-radius: 8px; padding: 2px 12px;
    }}
    QComboBox#qualityCombo:hover {{ border-color: {t['accent']}; }}
    QComboBox#qualityCombo:disabled {{ color: {t['muted']}; background: {t['raised']}; }}
    QComboBox#qualityCombo::drop-down {{ border: none; width: 24px; }}
    QComboBox#qualityCombo QAbstractItemView {{
        background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
        selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; outline: none;
    }}
    QCheckBox#subCheck {{ color: {t['text2']}; spacing: 8px; }}
    QCheckBox#subCheck::indicator {{
        width: 16px; height: 16px; border: 1.5px solid {t['muted']}; border-radius: 4px; background: {t['input']};
    }}
    QCheckBox#subCheck::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}

    /* Platform tabs: underline style */
    QWidget#pageTabsBar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
    QPushButton#pageTabActive {{
        background: transparent; color: {t['text']}; border: none;
        border-bottom: 3px solid {t['accent']}; border-radius: 0; padding: 0 18px;
    }}
    QPushButton#pageTabInactive {{
        background: transparent; color: {t['text2']}; border: none;
        border-bottom: 3px solid transparent; border-radius: 0; padding: 0 18px;
    }}
    QPushButton#pageTabInactive:hover {{ color: {t['text']}; background: {t['raised']}; }}

    /* Status filter pills */
    QWidget#tabsBar {{ background: {t['bg']}; }}
    QPushButton#filterTabActive {{
        background: {t['accent_soft']}; color: {t['accent_text']};
        border: 1px solid {t['accent']}; border-radius: 14px; padding: 0 14px;
    }}
    QPushButton#filterTabInactive {{
        background: transparent; color: {t['text2']}; border: 1px solid transparent; border-radius: 14px; padding: 0 14px;
    }}
    QPushButton#filterTabInactive:hover {{ background: {t['raised']}; color: {t['text']}; }}

    /* Queue */
    QScrollArea#queueScroll, QWidget#queueContainer, QWidget#splitView {{ background: {t['bg']}; }}
    QLabel#emptyHint {{ color: {t['muted']}; padding: 70px 20px; font-size: 13px; }}
    QWidget#queueRow {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
    QWidget#queueRow:hover {{ background: {t['row_hover']}; }}
    QLabel#rowThumb {{ background: {t['raised']}; border-radius: 8px; color: {t['accent_text']}; }}
    QLabel#rowTitle {{ color: {t['text']}; background: transparent; }}
    QLabel#rowStatus {{ color: {t['dim']}; background: transparent; }}
    QProgressBar#miniProgress {{ border: none; border-radius: 8px; background: {t['progress_bg']}; }}
    QProgressBar#miniProgress::chunk {{ background: {t['accent']}; border-radius: 8px; }}

    QPushButton#rowDownloadBtn, QPushButton#rowFolderBtn, QPushButton#rowRemoveBtn {{
        background: transparent; border: 1px solid {t['border']}; border-radius: 15px;
    }}
    QPushButton#rowDownloadBtn:hover {{ background: {t['accent_soft']}; border-color: {t['accent']}; }}
    QPushButton#rowFolderBtn:hover {{ background: {t['raised']}; border-color: {t['muted']}; }}
    QPushButton#rowRemoveBtn:hover {{ background: {t['danger_soft']}; border-color: {t['danger']}; }}
    QPushButton#rowDownloadBtn:disabled, QPushButton#rowFolderBtn:disabled,
    QPushButton#rowRemoveBtn:disabled {{ border-color: transparent; }}

    /* History panel */
    QWidget#historyPanel {{ background: {t['surface']}; border-left: 1px solid {t['border']}; }}
    QLabel#historyTitle {{ color: {t['text']}; }}
    QPushButton#historyPanelCloseBtn {{
        background: transparent; border: 1px solid {t['border']}; border-radius: 12px; color: {t['text2']};
    }}
    QPushButton#historyPanelCloseBtn:hover {{ border-color: {t['danger']}; color: {t['danger']}; background: {t['danger_soft']}; }}
    QListWidget#historyList {{
        background: {t['bg']}; color: {t['text2']}; border: 1px solid {t['border']};
        border-radius: 10px; padding: 6px; font-size: 10px; outline: none;
    }}
    QListWidget#historyList::item {{ padding: 8px 6px; border-bottom: 1px solid {t['border']}; }}
    QListWidget#historyList::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
    QPushButton#historyClearBtn {{
        background: transparent; color: {t['danger']}; border: 1px solid {t['border']};
        border-radius: 8px; padding: 0 12px; font-weight: 600;
    }}
    QPushButton#historyClearBtn:hover {{ border-color: {t['danger']}; background: {t['danger_soft']}; }}
    QPushButton#historyCloseBtn {{
        background: {t['accent']}; color: {t['on_accent']}; border: none;
        border-radius: 8px; padding: 0 16px; font-weight: 600;
    }}
    QPushButton#historyCloseBtn:hover {{ background: {t['accent_hover']}; }}

    /* Status bar */
    QWidget#statusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']}; }}
    QLabel#footer {{ color: {t['muted']}; }}
    QPushButton#feedbackLink {{
        background: transparent; border: none; color: {t['accent_text']}; padding: 0 4px; font-weight: 600;
    }}
    QPushButton#feedbackLink:hover {{ text-decoration: underline; }}

    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def build_dialog_qss(t):
    return f"""
    QDialog {{ background: {t['surface']}; }}
    QWidget {{ font-family: 'Segoe UI', Arial, sans-serif; }}
    QScrollArea#settingsScroll {{ background: {t['surface']}; border: none; }}
    QScrollArea#settingsScroll > QWidget > QWidget {{ background: {t['surface']}; }}
    QWidget#settingsContent {{ background: {t['surface']}; }}
    QLabel#dlgTitle {{ color: {t['text']}; }}
    QLabel#dlgSubtitle {{ color: {t['text2']}; }}
    QWidget#card {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 12px; }}
    QWidget#card QLabel {{ background: transparent; }}
    QLabel#cardTitle {{ color: {t['text']}; }}

    QRadioButton#settingsRadio {{ color: {t['text2']}; padding: 3px 0; spacing: 10px; background: transparent; }}
    QRadioButton#settingsRadio:hover {{ color: {t['text']}; }}
    QRadioButton#settingsRadio::indicator {{
        width: 16px; height: 16px; border: 2px solid {t['muted']}; border-radius: 9px; background: transparent;
    }}
    QRadioButton#settingsRadio::indicator:checked {{
        border-color: {t['accent']};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0 {t['accent']}, stop:0.45 {t['accent']}, stop:0.55 {t['card']}, stop:1 {t['card']});
    }}
    QLineEdit#folderInput {{
        background: {t['input']}; border: 1px solid {t['border']}; border-radius: 8px;
        padding: 0 12px; color: {t['text2']};
    }}
    QPushButton#browseBtn {{
        background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']};
        border-radius: 8px; font-weight: 500;
    }}
    QPushButton#browseBtn:hover {{ border-color: {t['accent']}; background: {t['accent_soft']}; }}
    QPushButton#dlBtnSmall {{
        background: {t['accent']}; color: {t['on_accent']}; border: none; border-radius: 8px;
    }}
    QPushButton#dlBtnSmall:hover {{ background: {t['accent_hover']}; }}
    QPushButton#dlBtnSmall:pressed {{ background: {t['accent_press']}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """