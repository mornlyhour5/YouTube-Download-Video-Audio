import sys
from PyQt5.QtCore import Qt, QPoint, QSize
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QProgressBar,
    QScrollArea, QFrame, QGraphicsDropShadowEffect
)
from PyQt5.QtGui import QColor, QFont, QIcon


# ── Theme Palette Definition ───────────────────────────────────────────────────

THEME_DARK = {
    'bg': '#121009',
    'surface': '#17140D',
    'panel': '#1F1A12',
    'panel_border': '#2E271B',
    'hover_panel': '#292218',
    'border': '#2C251A',
    'row_border': '#221D14',
    'row_hover': '#1C1710',
    'title': '#F5F5F7',
    'text': '#E5E5E7',
    'text_secondary': '#8E8E93',
    'accent': '#D4AF37',       # Gold Accent
    'accent_hover': '#E2BE4B',
    'accent_bright': '#F0CB58',
    'accent_press': '#B89628',
    'on_accent': '#000000',
    'input': '#18140E',
    'input_border': '#2A2318',
    'radio_border': '#3D3323',
    'dropdown': '#1A160F',
    'dropdown_sel': '#2E2619',
    'thumb': '#262017',
    'progress_bg': '#1A160F',
    'progress_border': '#2E271B',
    'danger': '#FF453A',
}


# ── Enhanced Stylesheet Definition ─────────────────────────────────────────────

def get_app_stylesheet(t):
    return f"""
    QMainWindow {{
        background-color: {t['bg']};
    }}

    QWidget#root {{
        background-color: {t['bg']};
    }}

    /* ── Custom Window Title Bar ── */
    QWidget#titleBar {{
        background-color: {t['surface']};
        border-bottom: 1px solid {t['border']};
    }}
    QLabel#windowTitle {{
        color: {t['accent']};
        font-weight: bold;
        font-size: 13px;
    }}
    QPushButton#winControlBtn {{
        background: transparent;
        border: none;
        color: {t['text_secondary']};
        font-size: 12px;
    }}
    QPushButton#winControlBtn:hover {{
        background-color: {t['panel']};
        color: {t['text']};
    }}
    QPushButton#closeBtn:hover {{
        background-color: {t['danger']};
        color: #FFFFFF;
    }}

    /* ── Top Header / Toolbar ── */
    QWidget#toolbar {{
        background-color: {t['surface']};
        border-bottom: 1px solid {t['border']};
    }}

    QPushButton#pasteBtn {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t['accent']}, stop:1 {t['accent_hover']});
        color: {t['on_accent']};
        border: none;
        border-radius: 8px;
        padding: 0 16px;
        font-weight: bold;
    }}
    QPushButton#pasteBtn:hover {{
        background: {t['accent_bright']};
    }}
    QPushButton#pasteBtn:pressed {{
        background: {t['accent_press']};
    }}

    /* ── Mode Toggle Switch ── */
    QWidget#toggleContainer {{
        background-color: {t['input']};
        border: 1px solid {t['input_border']};
        border-radius: 8px;
    }}
    QPushButton#toggleActive {{
        background-color: {t['accent']};
        color: {t['on_accent']};
        border: none;
        border-radius: 6px;
        font-weight: bold;
        padding: 0 14px;
    }}
    QPushButton#toggleInactive {{
        background: transparent;
        color: {t['text_secondary']};
        border: none;
        padding: 0 14px;
    }}
    QPushButton#toggleInactive:hover {{
        color: {t['text']};
    }}

    /* ── Platform Tabs ── */
    QWidget#navTabBar {{
        background-color: {t['surface']};
        border-bottom: 1px solid {t['border']};
    }}
    QPushButton#navTabActive {{
        background-color: {t['panel']};
        color: {t['accent']};
        border: 1px solid {t['panel_border']};
        border-radius: 8px;
        font-weight: bold;
        padding: 6px 16px;
    }}
    QPushButton#navTabInactive {{
        background: transparent;
        color: {t['text_secondary']};
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 6px 16px;
    }}
    QPushButton#navTabInactive:hover {{
        color: {t['text']};
        background-color: {t['hover_panel']};
    }}

    /* ── Inputs & Combos ── */
    QComboBox#qualityCombo {{
        background-color: {t['input']};
        border: 1px solid {t['input_border']};
        border-radius: 8px;
        color: {t['text']};
        padding: 0 10px;
    }}
    QComboBox#qualityCombo::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox#qualityCombo QAbstractItemView {{
        background-color: {t['dropdown']};
        color: {t['text']};
        selection-background-color: {t['dropdown_sel']};
        border: 1px solid {t['border']};
    }}

    QCheckBox#subCheck {{
        color: {t['text']};
        spacing: 6px;
    }}
    QCheckBox#subCheck::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {t['radio_border']};
    }}
    QCheckBox#subCheck::indicator:checked {{
        background-color: {t['accent']};
        border-color: {t['accent']};
    }}

    QPushButton#themeBtn {{
        background-color: {t['panel']};
        border: 1px solid {t['panel_border']};
        border-radius: 8px;
        color: {t['text']};
    }}
    QPushButton#themeBtn:hover {{
        border-color: {t['accent']};
        background-color: {t['hover_panel']};
    }}

    /* ── Queue Item Row ── */
    QWidget#queueRow {{
        background-color: {t['surface']};
        border: 1px solid {t['row_border']};
        border-radius: 10px;
    }}
    QWidget#queueRow:hover {{
        border-color: {t['border']};
        background-color: {t['row_hover']};
    }}

    QLabel#rowThumb {{
        background-color: {t['thumb']};
        border-radius: 8px;
        color: {t['text_secondary']};
    }}

    QLabel#rowTitle {{
        color: {t['title']};
        font-weight: bold;
    }}

    QLabel#rowSubtitle {{
        color: {t['text_secondary']};
        font-size: 11px;
    }}

    /* ── Action Buttons ── */
    QPushButton#rowDownloadBtn, QPushButton#rowFolderBtn, QPushButton#rowRemoveBtn {{
        background-color: {t['panel']};
        border: 1px solid {t['panel_border']};
        border-radius: 6px;
        color: {t['text']};
    }}
    QPushButton#rowDownloadBtn:hover, QPushButton#rowFolderBtn:hover {{
        border-color: {t['accent']};
        color: {t['accent']};
    }}
    QPushButton#rowRemoveBtn:hover {{
        border-color: {t['danger']};
        color: {t['danger']};
    }}

    /* ── Progress Bar ── */
    QProgressBar#miniProgress {{
        background-color: {t['progress_bg']};
        border: 1px solid {t['progress_border']};
        border-radius: 6px;
        color: {t['text']};
        text-align: center;
        font-size: 10px;
    }}
    QProgressBar#miniProgress::chunk {{
        background-color: {t['accent']};
        border-radius: 5px;
    }}

    /* ── Scroll Area ── */
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    """


# ── Custom Queue Row Widget ────────────────────────────────────────────────────

class QueueRowItem(QWidget):
    def __init__(self, title, info_text, progress_val=0, parent=None):
        super().__init__(parent)
        self.setObjectName("queueRow")
        self.setFixedHeight(80)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        # Thumbnail Placeholder
        self.thumb = QLabel("THUMB")
        self.thumb.setObjectName("rowThumb")
        self.thumb.setFixedSize(96, 60)
        self.thumb.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.thumb)

        # Text Details Container
        text_container = QWidget()
        vbox = QVBoxLayout(text_container)
        vbox.setContentsMargins(0, 2, 0, 2)
        vbox.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("rowTitle")

        self.sub_label = QLabel(info_text)
        self.sub_label.setObjectName("rowSubtitle")

        self.progress = QProgressBar()
        self.progress.setObjectName("miniProgress")
        self.progress.setFixedHeight(12)
        self.progress.setValue(progress_val)

        vbox.addWidget(self.title_label)
        vbox.addWidget(self.sub_label)
        vbox.addWidget(self.progress)
        layout.addWidget(text_container, stretch=1)

        # Actions Row
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(6)

        self.btn_download = QPushButton("Download")
        self.btn_download.setObjectName("rowDownloadBtn")
        self.btn_download.setFixedSize(76, 32)

        self.btn_folder = QPushButton("Folder")
        self.btn_folder.setObjectName("rowFolderBtn")
        self.btn_folder.setFixedSize(60, 32)

        self.btn_remove = QPushButton("✕")
        self.btn_remove.setObjectName("rowRemoveBtn")
        self.btn_remove.setFixedSize(32, 32)

        actions_layout.addWidget(self.btn_download)
        actions_layout.addWidget(self.btn_folder)
        actions_layout.addWidget(self.btn_remove)

        layout.addLayout(actions_layout)


# ── Main Application Window ────────────────────────────────────────────────────

class YouTubeDownloaderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.drag_position = QPoint()

        # Window Setup
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.resize(900, 620)

        # Root Widget & Layout
        self.root = QWidget()
        self.root.setObjectName("root")
        self.setCentralWidget(self.root)

        self.main_layout = QVBoxLayout(self.root)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Build UI Sections
        self.build_title_bar()
        self.build_toolbar()
        self.build_nav_tabs()
        self.build_queue_area()

        # Apply Stylesheet
        self.setStyleSheet(get_app_stylesheet(THEME_DARK))

    # 1. Frameless Custom Title Bar
    def build_title_bar(self):
        self.title_bar = QWidget()
        self.title_bar.setObjectName("titleBar")
        self.title_bar.setFixedHeight(36)

        tb_layout = QHBoxLayout(self.title_bar)
        tb_layout.setContentsMargins(12, 0, 0, 0)
        tb_layout.setSpacing(8)

        # App Title
        title = QLabel("TheHours YouTube Downloader")
        title.setObjectName("windowTitle")
        tb_layout.addWidget(title)
        tb_layout.addStretch()

        # Minimize, Maximize, Close
        btn_min = QPushButton("—")
        btn_min.setObjectName("winControlBtn")
        btn_min.setFixedSize(40, 36)
        btn_min.clicked.connect(self.showMinimized)

        btn_max = QPushButton("▢")
        btn_max.setObjectName("winControlBtn")
        btn_max.setFixedSize(40, 36)
        btn_max.clicked.connect(self.toggle_maximize)

        btn_close = QPushButton("✕")
        btn_close.setObjectName("closeBtn")
        btn_close.setFixedSize(40, 36)
        btn_close.clicked.connect(self.close)

        tb_layout.addWidget(btn_min)
        tb_layout.addWidget(btn_max)
        tb_layout.addWidget(btn_close)

        self.main_layout.addWidget(self.title_bar)

    # 2. Main Controls Header / Toolbar
    def build_toolbar(self):
        toolbar = QWidget()
        toolbar.setObjectName("toolbar")
        toolbar.setFixedHeight(56)

        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(12, 8, 12, 8)
        tb_layout.setSpacing(12)

        # Paste Link Action Button
        paste_btn = QPushButton("+ Paste Link")
        paste_btn.setObjectName("pasteBtn")
        paste_btn.setFixedHeight(36)

        # Mode Toggle Switch Container
        toggle_box = QWidget()
        toggle_box.setObjectName("toggleContainer")
        toggle_box.setFixedHeight(36)
        tg_layout = QHBoxLayout(toggle_box)
        tg_layout.setContentsMargins(3, 3, 3, 3)
        tg_layout.setSpacing(0)

        btn_single = QPushButton("Single")
        btn_single.setObjectName("toggleActive")
        btn_single.setFixedHeight(30)

        btn_batch = QPushButton("Batch")
        btn_batch.setObjectName("toggleInactive")
        btn_batch.setFixedHeight(30)

        tg_layout.addWidget(btn_single)
        tg_layout.addWidget(btn_batch)

        # Quality Selection
        combo_quality = QComboBox()
        combo_quality.setObjectName("qualityCombo")
        combo_quality.setFixedHeight(36)
        combo_quality.addItems(["1080p Full HD", "720p HD", "480p SD", "Audio Only (MP3)"])

        # Subtitle Checkbox
        sub_check = QCheckBox("Subtitles")
        sub_check.setObjectName("subCheck")

        # Theme Switcher
        theme_btn = QPushButton("🌙 Theme")
        theme_btn.setObjectName("themeBtn")
        theme_btn.setFixedSize(80, 36)

        tb_layout.addWidget(paste_btn)
        tb_layout.addWidget(toggle_box)
        tb_layout.addWidget(combo_quality)
        tb_layout.addWidget(sub_check)
        tb_layout.addStretch()
        tb_layout.addWidget(theme_btn)

        self.main_layout.addWidget(toolbar)

    # 3. Platform Navigation Tabs
    def build_nav_tabs(self):
        nav_bar = QWidget()
        nav_bar.setObjectName("navTabBar")
        nav_bar.setFixedHeight(48)

        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(12, 6, 12, 6)
        nav_layout.setSpacing(8)

        tab_yt = QPushButton("YouTube (3)")
        tab_yt.setObjectName("navTabActive")

        tab_fb = QPushButton("Facebook & Instagram")
        tab_fb.setObjectName("navTabInactive")

        tab_tt = QPushButton("TikTok")
        tab_tt.setObjectName("navTabInactive")

        nav_layout.addWidget(tab_yt)
        nav_layout.addWidget(tab_fb)
        nav_layout.addWidget(tab_tt)
        nav_layout.addStretch()

        self.main_layout.addWidget(nav_bar)

    # 4. Scrollable Queue Item List
    def build_queue_area(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        scroll_content = QWidget()
        self.queue_layout = QVBoxLayout(scroll_content)
        self.queue_layout.setContentsMargins(12, 12, 12, 12)
        self.queue_layout.setSpacing(8)

        # Sample Queue Rows
        self.queue_layout.addWidget(QueueRowItem("Sample YouTube Video Title 1 - 1080p", "Duration: 12:45 | 1080p • MP4", 65))
        self.queue_layout.addWidget(QueueRowItem("Sample YouTube Video Title 2 - Audio Download", "Duration: 03:20 | Audio • MP3", 100))
        self.queue_layout.addWidget(QueueRowItem("Sample YouTube Video Title 3 - Queued", "Duration: 08:15 | 720p • MP4", 0))

        self.queue_layout.addStretch()
        scroll.setWidget(scroll_content)

        self.main_layout.addWidget(scroll)

    # ── Window Drag & Window Controls ──────────────────────────────────────────

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()


# ── App Execution Entry Point ──────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = YouTubeDownloaderApp()
    window.show()
    sys.exit(app.exec_())