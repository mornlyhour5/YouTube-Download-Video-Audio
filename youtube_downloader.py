import sys
import os
import json
import re
import subprocess
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QComboBox,
    QFileDialog, QFrame, QTextEdit, QCheckBox, QStyle,
    QSizePolicy, QScrollArea, QDialog, QRadioButton, QButtonGroup,
    QMessageBox, QPlainTextEdit, QListWidget, QListWidgetItem, QTabWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QSettings
from PyQt5.QtGui import QFont, QIcon, QColor, QPalette, QPixmap, QPainter, QPainterPath, QBrush
import urllib.request
import yt_dlp


def resource_path(filename):
    """Get path to a bundled resource, works both in dev and in a PyInstaller .exe."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


# ── Persistent settings (stored forever via QSettings — survives app restarts) ──
# On Windows this lives in the registry, on macOS in ~/Library/Preferences,
# on Linux in ~/.config. No extra file to manage, and it's automatic.

class AppSettings:
    ORG  = "ProYTTools"
    APP  = "YouTubeDownloader"

    def __init__(self):
        self._s = QSettings(self.ORG, self.APP)

    def _default_dir(self, sub):
        return os.path.join(os.path.expanduser("~"), "Videos" if sub == "video" else "Music", "Fetched")

    def get_video_dir(self):
        return self._s.value("paths/video_dir", self._default_dir("video"))

    def set_video_dir(self, path):
        self._s.setValue("paths/video_dir", path)
        self._s.sync()

    def get_audio_dir(self):
        return self._s.value("paths/audio_dir", self._default_dir("audio"))

    def set_audio_dir(self, path):
        self._s.setValue("paths/audio_dir", path)
        self._s.sync()

    def get_use_same_dir(self):
        return self._s.value("paths/use_same_dir", True, type=bool)

    def set_use_same_dir(self, val):
        self._s.setValue("paths/use_same_dir", bool(val))
        self._s.sync()

    def get_default_quality(self):
        return self._s.value("prefs/default_quality", "Best (4K)")

    def set_default_quality(self, val):
        self._s.setValue("prefs/default_quality", val)
        self._s.sync()

    def get_subtitles(self):
        return self._s.value("prefs/subtitles", False, type=bool)

    def set_subtitles(self, val):
        self._s.setValue("prefs/subtitles", bool(val))
        self._s.sync()

    def get_default_format(self):
        return self._s.value("prefs/default_format", "video")

    def set_default_format(self, val):
        self._s.setValue("prefs/default_format", val)
        self._s.sync()

    # ── Download history (JSON file, kept forever until cleared) ──────────

    def _history_path(self):
        base = os.path.join(os.path.expanduser("~"), ".pro_yt_downloader")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "history.json")

    def load_history(self):
        path = self._history_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def add_history_entry(self, entry):
        history = self.load_history()
        history.insert(0, entry)   # newest first
        history = history[:500]    # cap so the file never grows unbounded
        try:
            with open(self._history_path(), "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
        except OSError:
            pass

    def clear_history(self):
        try:
            with open(self._history_path(), "w", encoding="utf-8") as f:
                json.dump([], f)
        except OSError:
            pass

    # ── Pending queue (JSON file, survives app restarts) ──────────────────

    def _queue_path(self):
        base = os.path.join(os.path.expanduser("~"), ".pro_yt_downloader")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "queue.json")

    def load_queue(self):
        path = self._queue_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def save_queue(self, entries):
        try:
            with open(self._queue_path(), "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
        except OSError:
            pass


# ── ANSI helpers ────────────────────────────────────────────────────────────────
# yt-dlp's progress-hook strings (_percent_str, _speed_str, _eta_str) are
# formatted for terminal display and can contain ANSI color escape codes
# (e.g. "\x1b[0;32m 12.9%\x1b[0m"). Parsing those directly with float() throws,
# which silently produced 0.0 every time and froze the UI progress bar even
# though the terminal (which strips ANSI itself for TTY output) looked fine.
# Always strip ANSI codes before doing anything numeric with these strings.

_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def _strip_ansi(text):
    if not text:
        return ""
    return _ANSI_ESCAPE_RE.sub("", str(text)).strip()

_RETRY_OPTS = {
    "retries": 5,
    "fragment_retries": 5,
    "extractor_retries": 3,
    "socket_timeout": 15,
}
_EXTRACTOR_ARGS = {
    "youtube": {"player_client": ["tv", "web", "android"]},
}

class DownloadWorker(QThread):
    progress   = pyqtSignal(float, str)
    processing = pyqtSignal()
    finished   = pyqtSignal(str)
    error      = pyqtSignal(str)

    def __init__(self, url, mode, quality, output_dir, subtitles=False):
        super().__init__()
        self.url        = url
        self.mode       = mode
        self.quality    = quality
        self.output_dir = output_dir
        self.subtitles  = subtitles
        self._last_pct  = -1.0

    def _hook(self, d):
        if d["status"] == "downloading":
            # Prefer the raw numeric byte fields — they're never colorized,
            # unlike _percent_str which can carry ANSI escape codes that
            # break a plain float() parse and silently zero out progress.
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0

            if total:
                pct_f = (downloaded / total) * 100.0
            else:
                # Fallback: strip ANSI codes before parsing the string version
                raw = _strip_ansi(d.get("_percent_str", "0%")).replace("%", "").strip()
                try:
                    pct_f = float(raw)
                except ValueError:
                    # Keep the last known good value instead of collapsing to 0
                    pct_f = self._last_pct if self._last_pct >= 0 else 0.0

            speed = _strip_ansi(d.get("_speed_str", ""))
            eta   = _strip_ansi(d.get("_eta_str", ""))
            label = f"{speed}  ETA {eta}" if speed else ""

            # Lower threshold so small legitimate steps aren't swallowed
            if abs(pct_f - self._last_pct) >= 0.1 or self._last_pct < 0:
                self._last_pct = pct_f
                self.progress.emit(pct_f, label)
        elif d["status"] == "finished":
            self._last_pct = 100.0
            self.progress.emit(100.0, "Processing…")
            self.processing.emit()

    def _base_opts(self):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            **_RETRY_OPTS,
            "extractor_args": _EXTRACTOR_ARGS,
            # Mimic a real browser so YouTube does not block the request
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://www.youtube.com/",
            },
            # Use exported cookie file if present (avoids DPAPI Chrome issue)
            **self._cookie_opts(),
        }
        return opts

    def _cookie_opts(self):
        cookie_file = resource_path("cookies.txt")
        if os.path.exists(cookie_file):
            return {"cookiefile": cookie_file}
        return {}

    def run(self):
        try:
            outtmpl = os.path.join(self.output_dir, "%(title)s.%(ext)s")
            base = self._base_opts()

            if self.mode == "mp3":
                ydl_opts = {
                    **base,
                    "format": "bestaudio/best",
                    "outtmpl": outtmpl,
                    "progress_hooks": [self._hook],
                    "writethumbnail": True,
                    # Order matters: extract audio FIRST, then add metadata, then embed art
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        },
                        {
                            "key": "FFmpegMetadata",
                            "add_metadata": True,
                        },
                        {
                            "key": "EmbedThumbnail",
                            "already_have_thumbnail": False,
                        },
                    ],
                    # Convert thumbnail to jpg first (png can cause embed failures)
                    "convert_thumbnails": "jpg",
                }
            else:
                # Always pair best video + best audio so ffmpeg can merge them.
                # Fallback chain guarantees audio is never skipped.
                if self.quality == "best":
                    fmt = (
                        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                        "bestvideo+bestaudio/"
                        "best"
                    )
                else:
                    h = self.quality
                    fmt = (
                        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
                        f"bestvideo[height<={h}]+bestaudio/"
                        f"best[height<={h}]/"
                        f"best"
                    )
                ydl_opts = {
                    **base,
                    "format": fmt,
                    "outtmpl": outtmpl,
                    "progress_hooks": [self._hook],
                    "merge_output_format": "mp4",
                    "prefer_ffmpeg": True,
                    "writethumbnail": True,
                    "postprocessors": [
                        {
                            "key": "FFmpegVideoRemuxer",
                            "preferedformat": "mp4",
                        },
                        {
                            # Embed thumbnail into mp4 container
                            "key": "EmbedThumbnail",
                            "already_have_thumbnail": False,
                        },
                        {
                            # Embed video metadata (title, uploader, etc.)
                            "key": "FFmpegMetadata",
                            "add_metadata": True,
                        },
                    ],
                }
                if self.subtitles:
                    ydl_opts.update({
                        "writesubtitles": True,
                        "writeautomaticsub": True,
                        "subtitlesformat": "srt",
                    })

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info  = ydl.extract_info(self.url, download=True)
                title = info.get("title", "video")
            self.finished.emit(f"Download complete. {title}")
        except Exception as e:
            self.error.emit(str(e))


class InfoWorker(QThread):
    info_ready = pyqtSignal(dict)
    error      = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def _cookie_opts(self):
        cookie_file = resource_path("cookies.txt")
        if os.path.exists(cookie_file):
            return {"cookiefile": cookie_file}
        return {}

    def run(self):
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                **_RETRY_OPTS,
                "extractor_args": _EXTRACTOR_ARGS,
                "http_headers": {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.youtube.com/",
                },
                **self._cookie_opts(),
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
            self.info_ready.emit({
                "title":     info.get("title",           "Unknown"),
                "channel":   info.get("uploader",        "Unknown"),
                "duration":  info.get("duration_string", "?"),
                "thumbnail": self._best_thumb_url(info),
            })
        except Exception as e:
            self.error.emit(str(e))

    @staticmethod
    def _best_thumb_url(info):
        """Pick a small-ish thumbnail (fast to fetch) if yt-dlp gives a list,
        otherwise fall back to the single 'thumbnail' field."""
        thumbs = info.get("thumbnails") or []
        if thumbs:
            # Prefer something close to 96px wide so the row loads snappily
            sized = [t for t in thumbs if t.get("width")]
            if sized:
                sized.sort(key=lambda t: abs(t["width"] - 96))
                return sized[0].get("url")
            return thumbs[-1].get("url")
        return info.get("thumbnail")


class ThumbnailWorker(QThread):
    """Downloads a thumbnail image off the UI thread."""
    thumb_ready = pyqtSignal(int, QPixmap)   # item_id, pixmap
    failed      = pyqtSignal(int, str)       # item_id, error message

    def __init__(self, item_id, url):
        super().__init__()
        self.item_id = item_id
        self.url     = url

    def run(self):
        if not self.url:
            self.failed.emit(self.item_id, "No thumbnail URL provided")
            return
        try:
            req = urllib.request.Request(
                self.url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://www.youtube.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read()
            pix = QPixmap()
            if pix.loadFromData(data):
                self.thumb_ready.emit(self.item_id, pix)
            else:
                self.failed.emit(self.item_id, "Downloaded data was not a valid image")
        except Exception as e:
            self.failed.emit(self.item_id, str(e))


# ── Card widget ────────────────────────────────────────────────────────────────

class Card(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)
        self._layout = lay

    def layout(self):
        return self._layout


# ── Toggle button pair ─────────────────────────────────────────────────────────

class ToggleGroup(QWidget):
    changed = pyqtSignal(str)   # emits "video" or "audio"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "video"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.btn_video = QPushButton("▶  Video")
        self.btn_audio = QPushButton("♪  Audio")
        for btn in (self.btn_video, self.btn_audio):
            btn.setFixedHeight(38)
            btn.setFont(QFont("Segoe UI", 11))
            btn.setCursor(Qt.PointingHandCursor)

        self.btn_video.setObjectName("toggleActive")
        self.btn_audio.setObjectName("toggleInactive")
        self.btn_video.clicked.connect(lambda: self._select("video"))
        self.btn_audio.clicked.connect(lambda: self._select("audio"))

        container = QWidget()
        container.setObjectName("toggleContainer")
        c_lay = QHBoxLayout(container)
        c_lay.setContentsMargins(4, 4, 4, 4)
        c_lay.setSpacing(0)
        c_lay.addWidget(self.btn_video)
        c_lay.addWidget(self.btn_audio)

        lay.addWidget(container)
        lay.addStretch()

    def _select(self, mode):
        self._mode = mode
        if mode == "video":
            self.btn_video.setObjectName("toggleActive")
            self.btn_audio.setObjectName("toggleInactive")
        else:
            self.btn_video.setObjectName("toggleInactive")
            self.btn_audio.setObjectName("toggleActive")
        # Force style refresh
        self.btn_video.style().unpolish(self.btn_video)
        self.btn_video.style().polish(self.btn_video)
        self.btn_audio.style().unpolish(self.btn_audio)
        self.btn_audio.style().polish(self.btn_audio)
        self.changed.emit(mode)

    def mode(self):
        return self._mode

    def set_mode(self, mode):
        self._select(mode)


# ── Settings dialog ────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    """
    Central place to configure where video and audio downloads are saved.
    Choices made here are written to AppSettings immediately, so they are
    remembered forever (across restarts) — the main window just reads them
    back the next time it needs a folder.
    """

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setFixedWidth(560)
        self._build_ui()
        self._apply_style()
        self._load_current()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(16)

        title = QLabel("⚙  Preferences")
        title.setObjectName("dlgTitle")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        root.addWidget(title)

        subtitle = QLabel("Choose where downloads are stored. Your choice is saved automatically.")
        subtitle.setObjectName("dlgSubtitle")
        subtitle.setFont(QFont("Segoe UI", 9))
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # Same-folder toggle
        same_card = Card()
        same_lay = same_card.layout()
        same_lbl = QLabel("Storage Mode")
        same_lbl.setObjectName("cardTitle")
        same_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        same_lay.addWidget(same_lbl)

        self.radio_group = QButtonGroup(self)
        self.radio_same = QRadioButton("Use one folder for everything")
        self.radio_split = QRadioButton("Use separate folders for Video and Audio")
        for r in (self.radio_same, self.radio_split):
            r.setObjectName("settingsRadio")
            r.setFont(QFont("Segoe UI", 10))
            self.radio_group.addButton(r)
        self.radio_same.toggled.connect(self._toggle_mode)
        same_lay.addWidget(self.radio_same)
        same_lay.addWidget(self.radio_split)
        root.addWidget(same_card)

        # Video folder
        video_card = Card()
        video_lay = video_card.layout()
        v_lbl = QLabel("🎬  Video Save Location")
        v_lbl.setObjectName("cardTitle")
        v_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        video_lay.addWidget(v_lbl)

        v_row = QHBoxLayout()
        v_row.setSpacing(8)
        self.video_path = QLineEdit()
        self.video_path.setObjectName("folderInput")
        self.video_path.setFixedHeight(38)
        self.video_path.setReadOnly(True)
        self.video_path.setFont(QFont("Segoe UI", 10))
        video_browse = QPushButton("Browse...")
        video_browse.setObjectName("browseBtn")
        video_browse.setFixedHeight(38)
        video_browse.setFixedWidth(90)
        video_browse.setFont(QFont("Segoe UI", 10))
        video_browse.clicked.connect(self._browse_video)
        v_row.addWidget(self.video_path)
        v_row.addWidget(video_browse)
        video_lay.addLayout(v_row)
        root.addWidget(video_card)
        self.video_card = video_card

        # Audio folder
        audio_card = Card()
        audio_lay = audio_card.layout()
        a_lbl = QLabel("🎵  Audio Save Location")
        a_lbl.setObjectName("cardTitle")
        a_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        audio_lay.addWidget(a_lbl)

        a_row = QHBoxLayout()
        a_row.setSpacing(8)
        self.audio_path = QLineEdit()
        self.audio_path.setObjectName("folderInput")
        self.audio_path.setFixedHeight(38)
        self.audio_path.setReadOnly(True)
        self.audio_path.setFont(QFont("Segoe UI", 10))
        audio_browse = QPushButton("Browse...")
        audio_browse.setObjectName("browseBtn")
        audio_browse.setFixedHeight(38)
        audio_browse.setFixedWidth(90)
        audio_browse.setFont(QFont("Segoe UI", 10))
        audio_browse.clicked.connect(self._browse_audio)
        a_row.addWidget(self.audio_path)
        a_row.addWidget(audio_browse)
        audio_lay.addLayout(a_row)
        root.addWidget(audio_card)
        self.audio_card = audio_card

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Done")
        close_btn.setObjectName("dlBtnSmall")
        close_btn.setFixedHeight(42)
        close_btn.setFixedWidth(120)
        close_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _load_current(self):
        use_same = self.settings.get_use_same_dir()
        self.radio_same.setChecked(use_same)
        self.radio_split.setChecked(not use_same)
        self.video_path.setText(self.settings.get_video_dir())
        self.audio_path.setText(self.settings.get_audio_dir())
        self._toggle_mode()

    def _toggle_mode(self):
        split = self.radio_split.isChecked()
        self.audio_card.setVisible(split)
        self.video_card.findChild(QLabel, "cardTitle").setText(
            "🎬  Video Save Location" if split else "📁  Save Location (Video & Audio)"
        )
        self.settings.set_use_same_dir(not split)

    def _browse_video(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Video Folder", self.video_path.text())
        if folder:
            self.video_path.setText(folder)
            self.settings.set_video_dir(folder)
            if self.radio_same.isChecked():
                self.settings.set_audio_dir(folder)
                self.audio_path.setText(folder)

    def _browse_audio(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Audio Folder", self.audio_path.text())
        if folder:
            self.audio_path.setText(folder)
            self.settings.set_audio_dir(folder)

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog { background: #17140F; }
            QWidget { font-family: 'Segoe UI', Arial, sans-serif; }
            QLabel#dlgTitle    { color: #F4E9C9; }
            QLabel#dlgSubtitle { color: #8A8375; }
            QWidget#card {
                background: #201C15;
                border: 1px solid #3A331F;
                border-radius: 14px;
            }
            QLabel#cardTitle { color: #E9DBAF; }
            QRadioButton#settingsRadio { color: #C9C2AF; padding: 4px 0; }
            QRadioButton#settingsRadio::indicator {
                width: 16px; height: 16px;
                border: 2px solid #6B5F3C;
                border-radius: 9px;
                background: transparent;
            }
            QRadioButton#settingsRadio::indicator:checked {
                background: #D4AF37;
                border-color: #D4AF37;
            }
            QLineEdit#folderInput {
                background: #14120D;
                border: 2px solid #3A331F;
                border-radius: 8px;
                padding: 0 12px;
                color: #B7AF98;
            }
            QPushButton#browseBtn {
                background: #26221A;
                color: #E9DBAF;
                border: 2px solid #4A4128;
                border-radius: 8px;
                font-weight: 500;
            }
            QPushButton#browseBtn:hover {
                border-color: #D4AF37;
                background: #2C2719;
            }
            QPushButton#browseBtn:pressed { background: #1C1912; }
            QPushButton#dlBtnSmall {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #D4AF37, stop:0.5 #E8CB5E, stop:1 #D4AF37);
                color: #1A1608;
                border: none;
                border-radius: 10px;
            }
            QPushButton#dlBtnSmall:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #E0C04A, stop:0.5 #F2D876, stop:1 #E0C04A);
            }
            QPushButton#dlBtnSmall:pressed { background: #B8963A; }
        """)

# ── Main window ────────────────────────────────────────────────────────────────
#
# Redesigned to match a MediaHuman-style queue list:
#   • A single "Paste Link" action (button or Ctrl+V paste) adds a URL as a
#     queued row — no permanent big URL textbox in the main flow.
#   • Each row shows a thumbnail placeholder, title/URL, status text, and two
#     small icon buttons: ⬇ (download this item) and ✕ (remove this item).
#   • Tabs across the top filter the queue: All / Ready / Processing / Failed
#     / Skipped / Complete — counts update live.
#   • Save-to-location lives ONLY in Settings now; there is no folder field
#     on the main screen at all.
#   • A top-level Format switch (Video / Audio) plus quality picker decides
#     how *newly downloaded* items are fetched; each item remembers its own
#     mode so a mixed queue (some audio, some video) is possible if the user
#     changes the switch between pastes.

QUEUE_STATUS_QUEUED     = "queued"
QUEUE_STATUS_LOADING    = "loading"
QUEUE_STATUS_READY      = "ready"
QUEUE_STATUS_PROCESSING = "processing"
QUEUE_STATUS_COMPLETE   = "complete"
QUEUE_STATUS_FAILED     = "failed"
QUEUE_STATUS_SKIPPED    = "skipped"

_YT_URL_RE = re.compile(r'(https?://[^\s]*(?:youtube\.com|youtu\.be)[^\s]*)', re.IGNORECASE)

_YT_LIST_STRIP_RE = re.compile(r'([&?])(list|start_radio|index)=[^&]*')


def _clean_youtube_url(url):
    """Strip playlist/radio-mix params (list=, start_radio=, index=) so a
    pasted 'Radio' or 'Mix' link resolves as a single video instead of
    yt-dlp trying (and often failing) to walk an auto-generated playlist."""
    cleaned = _YT_LIST_STRIP_RE.sub('', url)
    cleaned = re.sub(r'[?&]+$', '', cleaned)
    cleaned = cleaned.replace('?&', '?')
    return cleaned


_STATUS_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|\[[0-9;]*m")


def _clean_status_text(text):
    """Strip ANSI color codes (and yt-dlp's escaped '\x1b[' variants that
    sometimes arrive as literal text) and collapse whitespace/newlines so
    error messages fit on one line."""
    if not text:
        return ""
    text = _STATUS_ANSI_RE.sub("", str(text))
    text = text.replace("ERROR:", "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -")


class QueueItem:
    """One row in the download queue/list."""
    _next_id = 1

    def __init__(self, url):
        self.id = QueueItem._next_id
        QueueItem._next_id += 1
        self.url        = url
        self.title      = url
        self.channel     = ""
        self.duration   = ""
        self.thumbnail_url = ""
        self.thumbnail_pixmap = None   # QPixmap once loaded
        self.status     = QUEUE_STATUS_QUEUED
        self.mode       = "mp4"     # "mp4" or "mp3" — set when downloaded
        self.quality    = "best"
        self.subtitles  = False
        self.error_msg  = ""
        self.output_dir = ""


class QueueRowWidget(QWidget):
    """A single visual row in the queue list, styled like the MediaHuman rows."""
    download_clicked     = pyqtSignal(int)   # emits queue item id
    remove_clicked       = pyqtSignal(int)
    open_folder_clicked  = pyqtSignal(int)

    def __init__(self, item: QueueItem, parent=None):
        super().__init__(parent)
        self.item_id = item.id
        self.setObjectName("queueRow")
        self.setFixedHeight(64)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        # Thumbnail placeholder
        self.thumb = QLabel("▶")
        self.thumb.setObjectName("rowThumb")
        self.thumb.setFixedSize(48, 48)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lay.addWidget(self.thumb)

        # Title + status column
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title_lbl = QLabel()
        self.title_lbl.setObjectName("rowTitle")
        self.title_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.title_lbl.setWordWrap(False)
        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("rowStatus")
        self.status_lbl.setFont(QFont("Segoe UI", 8))
        self.status_lbl.setWordWrap(False)
        self.status_lbl.setTextInteractionFlags(Qt.NoTextInteraction)
        self.status_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_col.addWidget(self.title_lbl)
        text_col.addWidget(self.status_lbl)
        lay.addLayout(text_col, stretch=1)

        # Small progress bar (only visible while processing)
        self.mini_progress = QProgressBar()
        self.mini_progress.setObjectName("miniProgress")
        self.mini_progress.setFixedWidth(180)
        self.mini_progress.setFixedHeight(18)
        self.mini_progress.setTextVisible(True)
        self.mini_progress.setAlignment(Qt.AlignCenter)
        self.mini_progress.setFormat("%p%")
        self.mini_progress.setRange(0, 100)
        self.mini_progress.setVisible(False)
        lay.addWidget(self.mini_progress)

        # Per-row action icons: Download / Open Folder / Remove
        self.download_btn = QPushButton("⬇")
        self.download_btn.setObjectName("rowDownloadBtn")
        self.download_btn.setFixedSize(30, 30)
        self.download_btn.setFont(QFont("Segoe UI", 11))
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.setToolTip("Download this item")
        self.download_btn.clicked.connect(lambda: self.download_clicked.emit(self.item_id))
        lay.addWidget(self.download_btn)

        self.folder_btn = QPushButton("📂")
        self.folder_btn.setObjectName("rowFolderBtn")
        self.folder_btn.setFixedSize(30, 30)
        self.folder_btn.setFont(QFont("Segoe UI", 11))
        self.folder_btn.setCursor(Qt.PointingHandCursor)
        self.folder_btn.setToolTip("Open containing folder")
        self.folder_btn.clicked.connect(lambda: self.open_folder_clicked.emit(self.item_id))
        lay.addWidget(self.folder_btn)

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("rowRemoveBtn")
        self.remove_btn.setFixedSize(30, 30)
        self.remove_btn.setFont(QFont("Segoe UI", 10))
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.setToolTip("Remove from list")
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.item_id))
        lay.addWidget(self.remove_btn)

        self.update_from(item)

    def update_from(self, item: QueueItem):
        self.title_lbl.setText(item.title)
        icon_map = {
            QUEUE_STATUS_QUEUED:     ("⏳", "#8A8066", "Queued"),
            QUEUE_STATUS_LOADING:    ("⟳",  "#D4AF37", "Loading info…"),
            QUEUE_STATUS_READY:      ("●",  "#6FBF73", "Ready"),
            QUEUE_STATUS_PROCESSING: ("⬇",  "#D4AF37", "Downloading…"),
            QUEUE_STATUS_COMPLETE:   ("✓",  "#6FBF73", "Done"),
            QUEUE_STATUS_FAILED:     ("✗",  "#D96C5F", "Failed"),
            QUEUE_STATUS_SKIPPED:    ("↷",  "#8A8066", "Skipped"),
        }
        icon, color, label = icon_map.get(item.status, ("", "#8A8066", ""))
        kind = "🎵" if item.mode == "mp3" else "🎬"
        raw_detail = item.error_msg if item.status == QUEUE_STATUS_FAILED else (
            item.channel if item.channel else item.url
        )
        detail = _clean_status_text(raw_detail)
        full_text = f"{icon} {label} — {detail}" if detail else f"{icon} {label}"

        metrics = self.status_lbl.fontMetrics()
        avail_width = max(self.status_lbl.width(), 220)
        elided = metrics.elidedText(full_text, Qt.ElideRight, avail_width)
        self.status_lbl.setText(elided)
        self.status_lbl.setToolTip(full_text if elided != full_text else "")
        self.status_lbl.setStyleSheet(f"color: {color};")

        if item.thumbnail_pixmap is not None:
            self.set_thumbnail_pixmap(item.thumbnail_pixmap)
        else:
            self.thumb.setPixmap(QPixmap())  # clear any stale image
            self.thumb.setText(kind)

        self.mini_progress.setVisible(item.status == QUEUE_STATUS_PROCESSING)

        # Disable the download icon once complete/processing; disable remove while processing
        self.download_btn.setEnabled(item.status not in (QUEUE_STATUS_PROCESSING,))
        self.remove_btn.setEnabled(item.status != QUEUE_STATUS_PROCESSING)
        self.folder_btn.setEnabled(item.status == QUEUE_STATUS_COMPLETE and bool(item.output_dir))
        if item.status == QUEUE_STATUS_COMPLETE:
            self.download_btn.setToolTip("Download again")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Re-elide using the tooltip's full text (set whenever truncated)
        full_text = self.status_lbl.toolTip() or self.status_lbl.text()
        if full_text:
            metrics = self.status_lbl.fontMetrics()
            avail_width = max(self.status_lbl.width(), 220)
            elided = metrics.elidedText(full_text, Qt.ElideRight, avail_width)
            self.status_lbl.setText(elided)
            self.status_lbl.setToolTip(full_text if elided != full_text else "")

    def set_thumbnail_pixmap(self, pixmap: QPixmap):
        """Render a cropped, rounded-corner thumbnail into the fixed 48x48 slot."""
        size = self.thumb.width()
        scaled = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation)
        # Center-crop to a square
        x = max(0, (scaled.width()  - size) // 2)
        y = max(0, (scaled.height() - size) // 2)
        cropped = scaled.copy(x, y, size, size)

        rounded = QPixmap(size, size)
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, size, size, 8, 8)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, cropped)
        painter.end()

        self.thumb.setText("")
        self.thumb.setPixmap(rounded)


class YouTubeDownloader(QMainWindow):
    MAX_CONCURRENT_DOWNLOADS = 3

    def __init__(self):
        super().__init__()
        self.settings     = AppSettings()
        self.workers      = {}     # item_id -> DownloadWorker (active concurrent downloads)
        self.info_worker  = None
        self.queue_items  = {}     # id -> QueueItem
        self.row_widgets  = {}     # id -> QueueRowWidget
        self.download_queue_ids = []  # ids waiting for a free download slot

        self._build_ui()
        self._apply_style()
        self._reload_history()
        self._restore_saved_queue()
        self._refresh_tabs_and_list()

    def _ts(self):
        return datetime.now().strftime("[%-I:%M:%S %p]") if sys.platform != "win32" \
               else datetime.now().strftime("[%I:%M:%S %p]")

    def _current_output_dir(self):
        """Returns the save folder for whatever mode (video/audio) is active right now."""
        mode = self.toggle.mode()
        if mode == "audio" or self.quality_combo.currentText() == "Audio Only":
            return self.settings.get_audio_dir()
        return self.settings.get_video_dir()

    def _existing_matches(self, folder, title):
        if not title or not os.path.isdir(folder):
            return []
        safe_title = title.strip().lower()
        matches = []
        try:
            for fname in os.listdir(folder):
                name_no_ext = os.path.splitext(fname)[0].strip().lower()
                if name_no_ext == safe_title or name_no_ext.startswith(safe_title):
                    matches.append(fname)
        except OSError:
            pass
        return matches

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("TheHours YouTube Downloader")
        self.setMinimumWidth(760)
        self.setMinimumHeight(640)
        self.setWindowIcon(QIcon(resource_path("icon.ico")))

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        main = QVBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # ── Top toolbar ───────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setObjectName("toolbar")
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(16, 10, 16, 10)
        tb_lay.setSpacing(10)

        self.paste_btn = QPushButton("⊕  Paste Link")
        self.paste_btn.setObjectName("pasteBtn")
        self.paste_btn.setFixedHeight(38)
        self.paste_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.paste_btn.setCursor(Qt.PointingHandCursor)
        self.paste_btn.clicked.connect(self._paste_from_clipboard)
        tb_lay.addWidget(self.paste_btn)

        # Format toggle (Video / Audio) — decides mode for newly added links
        self.toggle = ToggleGroup()
        self.toggle.changed.connect(self._on_format_change)
        tb_lay.addWidget(self.toggle)

        self.quality_combo = QComboBox()
        self.quality_combo.setObjectName("qualityCombo")
        self.quality_combo.setFixedHeight(36)
        self.quality_combo.setFont(QFont("Segoe UI", 9))
        self.quality_combo.addItems(["Best (4K)", "1080p", "720p", "480p", "360p", "Audio Only"])
        self.quality_combo.setFixedWidth(140)
        self.quality_combo.currentTextChanged.connect(self._on_quality_change)
        tb_lay.addWidget(self.quality_combo)

        self.sub_check = QCheckBox("Subtitles")
        self.sub_check.setObjectName("subCheck")
        self.sub_check.setFont(QFont("Segoe UI", 9))
        tb_lay.addWidget(self.sub_check)

        tb_lay.addStretch()

        self.header_settings_btn = QPushButton("⚙  Settings")
        self.header_settings_btn.setObjectName("headerSettingsBtn")
        self.header_settings_btn.setFixedHeight(38)
        self.header_settings_btn.setFont(QFont("Segoe UI", 10))
        self.header_settings_btn.setCursor(Qt.PointingHandCursor)
        self.header_settings_btn.clicked.connect(self._open_settings)
        tb_lay.addWidget(self.header_settings_btn)

        self.download_all_btn = QPushButton("⬇  Download All Ready")
        self.download_all_btn.setObjectName("dlAllBtn")
        self.download_all_btn.setFixedHeight(38)
        self.download_all_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.download_all_btn.setCursor(Qt.PointingHandCursor)
        self.download_all_btn.clicked.connect(self._download_all_ready)
        tb_lay.addWidget(self.download_all_btn)

        main.addWidget(toolbar)

        # ── Filter tabs (All / Ready / Processing / Failed / Skipped / Complete)
        tabs_bar = QWidget()
        tabs_bar.setObjectName("tabsBar")
        tabs_lay = QHBoxLayout(tabs_bar)
        tabs_lay.setContentsMargins(16, 8, 16, 8)
        tabs_lay.setSpacing(6)

        self.filter_buttons = {}
        self.filter_mode = "all"
        for key, label in [
            ("all", "All"), ("ready", "Ready"), ("processing", "Processing"),
            ("failed", "Failed"), ("skipped", "Skipped"), ("complete", "Complete"),
        ]:
            btn = QPushButton(f"{label} (0)")
            btn.setObjectName("filterTabActive" if key == "all" else "filterTabInactive")
            btn.setFixedHeight(30)
            btn.setFont(QFont("Segoe UI", 9, QFont.Bold if key == "all" else QFont.Normal))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._set_filter(k))
            tabs_lay.addWidget(btn)
            self.filter_buttons[key] = btn
        tabs_lay.addStretch()
        main.addWidget(tabs_bar)

        # ── Split view: queue list (left) + integrated history panel (right) ──
        split = QWidget()
        split.setObjectName("splitView")
        split_lay = QHBoxLayout(split)
        split_lay.setContentsMargins(0, 0, 0, 0)
        split_lay.setSpacing(0)

        # Queue list
        self.queue_scroll = QScrollArea()
        self.queue_scroll.setObjectName("queueScroll")
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setFrameShape(QFrame.NoFrame)
        self.queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.queue_container = QWidget()
        self.queue_container.setObjectName("queueContainer")
        self.queue_list_lay = QVBoxLayout(self.queue_container)
        self.queue_list_lay.setContentsMargins(0, 0, 0, 0)
        self.queue_list_lay.setSpacing(1)
        self.queue_list_lay.addStretch()

        self.empty_hint = QLabel("No links yet — click \"Paste Link\" to add a YouTube URL to your list.")
        self.empty_hint.setObjectName("emptyHint")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setFont(QFont("Segoe UI", 10))
        self.queue_list_lay.insertWidget(0, self.empty_hint)

        self.queue_scroll.setWidget(self.queue_container)
        split_lay.addWidget(self.queue_scroll, stretch=1)

        # Integrated history panel (hidden by default, toggled from footer)
        self.history_panel = self._build_history_panel()
        self.history_panel.setVisible(False)
        split_lay.addWidget(self.history_panel)

        main.addWidget(split, stretch=1)

        # ── Bottom status bar ─────────────────────────────────────────────
        status_bar = QWidget()
        status_bar.setObjectName("statusBar")
        sb_lay = QHBoxLayout(status_bar)
        sb_lay.setContentsMargins(16, 8, 16, 8)

        self.ver_lbl = QLabel("version 1.3.1")
        self.ver_lbl.setObjectName("footer")
        self.ver_lbl.setFont(QFont("Segoe UI", 9))
        sb_lay.addWidget(self.ver_lbl)
        sb_lay.addStretch()

        self.history_link = QPushButton("🕓  History")
        self.history_link.setObjectName("feedbackLink")
        self.history_link.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.history_link.setCursor(Qt.PointingHandCursor)
        self.history_link.setFlat(True)
        self.history_link.clicked.connect(self._toggle_history_panel)
        sb_lay.addWidget(self.history_link)

        main.addWidget(status_bar)

        # Apply saved preferences (default quality, subtitles) on launch
        saved_quality = self.settings.get_default_quality()
        idx = self.quality_combo.findText(saved_quality)
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)
        self.sub_check.setChecked(self.settings.get_subtitles())

        # Restore saved Video/Audio format
        saved_format = self.settings.get_default_format()
        self.toggle.set_mode(saved_format)
        self._on_format_change(saved_format)

    # ── Stylesheet — Luxury dark & gold theme, MediaHuman-style list ───────

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget#root { background: #121009; }
            QWidget { font-family: 'Segoe UI', Arial, sans-serif; }

            QWidget#toolbar {
                background: #17140D;
                border-bottom: 1px solid #322A17;
            }
            QPushButton#pasteBtn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FFE27A, stop:1 #D4AF37);
                color: #1A1608;
                border: 2px solid #FFDD70;
                border-radius: 10px;
                padding: 0 16px;
                font-weight: bold;
            }
            QPushButton#pasteBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FFEA96, stop:1 #E8CB5E);
                border-color: #FFF0A8;
            }
            QPushButton#pasteBtn:pressed { background: #A9860F; border-color: #C9A227; }

            QPushButton#headerSettingsBtn {
                background: #211D14;
                border: 1px solid #4A4128;
                border-radius: 10px;
                color: #E9DBAF;
                padding: 0 14px;
            }
            QPushButton#headerSettingsBtn:hover { border-color: #D4AF37; }

            QPushButton#dlAllBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #C9A227, stop:0.5 #E8CB5E, stop:1 #C9A227);
                color: #1A1608;
                border: none;
                border-radius: 10px;
                padding: 0 14px;
            }
            QPushButton#dlAllBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #D4AF37, stop:0.5 #F2D876, stop:1 #D4AF37);
            }
            QPushButton#dlAllBtn:disabled { background: #2A2618; color: #6E6553; }

            QComboBox#qualityCombo {
                background: #100E09;
                border: 2px solid #362E1B;
                border-radius: 8px;
                padding: 2px 10px;
                color: #F0E6C8;
            }
            QComboBox#qualityCombo::drop-down { border: none; width: 24px; }
            QComboBox#qualityCombo QAbstractItemView {
                background: #1A1610; color: #E9DBAF;
                border: 2px solid #D4AF37;
                selection-background-color: #3A3016;
            }
            QCheckBox#subCheck { color: #9A9075; }
            QCheckBox#subCheck::indicator {
                width: 15px; height: 15px;
                border: 2px solid #4A4128; border-radius: 4px;
                background: #100E09;
            }
            QCheckBox#subCheck::indicator:checked { background: #D4AF37; border-color: #D4AF37; }

            QWidget#toggleContainer { background: #100E09; border: 1px solid #322A17; border-radius: 9px; }
            QPushButton#toggleActive {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFE27A, stop:1 #D4AF37);
                color: #1A1608; border: none; border-radius: 7px; padding: 0 16px; font-weight: bold;
            }
            QPushButton#toggleInactive {
                background: transparent; color: #6E6553; border: none; border-radius: 7px; padding: 0 16px;
            }
            QPushButton#toggleInactive:hover { color: #C9BE9E; }

            /* ── Split view / integrated history panel ── */
            QWidget#splitView { background: #121009; }
            QWidget#historyPanel {
                background: #17140D;
                border-left: 1px solid #322A17;
            }
            QLabel#historyTitle { color: #F4E9C9; }
            QPushButton#historyPanelCloseBtn {
                background: #211D14; border: 1px solid #4A2820; border-radius: 12px; color: #D96C5F;
            }
            QPushButton#historyPanelCloseBtn:hover { border-color: #D96C5F; background: #2B1E1B; }
            QListWidget#historyList {
                background: #0A0904; color: #C9BE9E;
                border: 1px solid #2A2618; border-radius: 10px; padding: 6px;
                font-size: 10px;
            }
            QListWidget#historyList::item { padding: 6px 4px; border-bottom: 1px solid #201C15; }
            QListWidget#historyList::item:selected { background: #2B2518; color: #F0E6C8; }
            QPushButton#historyClearBtn {
                background: #211D14; color: #D96C5F; border: 1px solid #4A2820; border-radius: 8px;
                padding: 0 12px; font-weight: 600;
            }
            QPushButton#historyClearBtn:hover { border-color: #D96C5F; background: #2B1E1B; }
            QPushButton#historyCloseBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #C9A227, stop:0.5 #E8CB5E, stop:1 #C9A227);
                color: #1A1608; border: none; border-radius: 8px; padding: 0 16px; font-weight: bold;
            }
            QPushButton#historyCloseBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #D4AF37, stop:0.5 #F2D876, stop:1 #D4AF37);
            }

            /* ── Filter tabs ── */
            QWidget#tabsBar { background: #14120C; border-bottom: 1px solid #2A2618; }
            QPushButton#filterTabActive {
                background: #2B2518; color: #E9DBAF;
                border: 1px solid #4A4128; border-radius: 14px; padding: 0 14px;
            }
            QPushButton#filterTabInactive {
                background: transparent; color: #8A8066;
                border: 1px solid transparent; border-radius: 14px; padding: 0 14px;
            }
            QPushButton#filterTabInactive:hover { color: #D4AF37; border-color: #4A4128; }

            /* ── Queue list ── */
            QScrollArea#queueScroll { background: #121009; }
            QWidget#queueContainer { background: #121009; }
            QLabel#emptyHint { color: #5E5642; padding: 60px 20px; }

            QWidget#queueRow { background: #17140D; border-bottom: 1px solid #241F14; }
            QWidget#queueRow:hover { background: #1D1810; }
            QLabel#rowThumb {
                background: #26221A; border-radius: 8px; color: #D4AF37;
            }
            QLabel#rowTitle  { color: #F0E6C8; }
            QLabel#rowStatus { color: #8A8066; }

            QProgressBar#miniProgress { border: none; border-radius: 2px; background: #2A2618; }
            QProgressBar#miniProgress::chunk { background: #D4AF37; border-radius: 2px; }

            QPushButton#rowDownloadBtn {
                background: #211D14; border: 1px solid #4A4128; border-radius: 15px; color: #D4AF37;
            }
            QPushButton#rowDownloadBtn:hover { border-color: #D4AF37; background: #2B2518; }
            QPushButton#rowDownloadBtn:disabled { color: #4A4128; border-color: #241F14; }

            QPushButton#rowFolderBtn {
                background: #211D14; border: 1px solid #4A4128; border-radius: 15px; color: #E9DBAF;
            }
            QPushButton#rowFolderBtn:hover { border-color: #E9DBAF; background: #2B2518; }
            QPushButton#rowFolderBtn:disabled { color: #4A4128; border-color: #241F14; }

            QPushButton#rowRemoveBtn {
                background: #211D14; border: 1px solid #4A2820; border-radius: 15px; color: #D96C5F;
            }
            QPushButton#rowRemoveBtn:hover { border-color: #D96C5F; background: #2B1E1B; }
            QPushButton#rowRemoveBtn:disabled { color: #4A2820; border-color: #241F14; }

            /* ── Status bar ── */
            QWidget#statusBar { background: #17140D; border-top: 1px solid #322A17; }
            QLabel#footer       { color: #5E5642; }
            QPushButton#feedbackLink {
                background: transparent; border: none; color: #D4AF37; padding: 0;
            }
            QPushButton#feedbackLink:hover { color: #F2D876; text-decoration: underline; }

            QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
            QScrollBar::handle:vertical { background: #4A4128; border-radius: 3px; min-height: 30px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

    # ── Paste-link → fetch-info → queue flow ────────────────────────────────

    def _paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text() or ""
        urls = _YT_URL_RE.findall(text)
        if not urls:
            QMessageBox.information(
                self, "No Link Found",
                "Copy a YouTube link to your clipboard first, then click \"Paste Link\"."
            )
            return
        added = 0
        for raw_u in urls:
            u = _clean_youtube_url(raw_u)
            if not any(qi.url == u for qi in self.queue_items.values()):
                self._add_queue_item(u)
                added += 1
        if added == 0:
            self._flash_status("That link is already in your list.")

    def _add_queue_item(self, url):
        item = QueueItem(url)
        self.queue_items[item.id] = item
        self.empty_hint.setVisible(False)
        row = QueueRowWidget(item)
        row.download_clicked.connect(self._download_single)
        row.remove_clicked.connect(self._remove_item)
        row.open_folder_clicked.connect(self._open_item_folder)
        self.row_widgets[item.id] = row
        self.queue_list_lay.insertWidget(self.queue_list_lay.count() - 1, row)
        self._refresh_tabs_and_list()
        self._fetch_item_info(item.id)

    def _fetch_item_info(self, item_id):
        item = self.queue_items.get(item_id)
        if not item:
            return
        item.status = QUEUE_STATUS_LOADING
        self._update_row(item_id)

        worker = InfoWorker(item.url)
        worker.info_ready.connect(lambda info, iid=item_id: self._on_item_info_ready(iid, info))
        worker.error.connect(lambda msg, iid=item_id: self._on_item_info_error(iid, msg))
        # Keep a reference so it isn't garbage-collected mid-flight
        item._info_worker = worker
        worker.start()

    def _on_item_info_ready(self, item_id, info):
        item = self.queue_items.get(item_id)
        if not item:
            return
        item.title        = info["title"]
        item.channel      = info["channel"]
        item.duration     = info["duration"]
        item.thumbnail_url = info.get("thumbnail") or ""
        item.status       = QUEUE_STATUS_READY
        self._update_row(item_id)
        self._refresh_tabs_and_list()
        if item.thumbnail_url:
            self._fetch_item_thumbnail(item_id, item.thumbnail_url)

    def _on_item_info_error(self, item_id, msg):
        item = self.queue_items.get(item_id)
        if not item:
            return
        item.status = QUEUE_STATUS_FAILED
        item.error_msg = msg
        self._update_row(item_id)
        self._refresh_tabs_and_list()

    def _fetch_item_thumbnail(self, item_id, thumb_url):
        worker = ThumbnailWorker(item_id, thumb_url)
        worker.thumb_ready.connect(self._on_item_thumbnail_ready)
        worker.failed.connect(self._on_item_thumbnail_failed)
        item = self.queue_items.get(item_id)
        if item:
            item._thumb_worker = worker  # keep a reference alive
        worker.start()

    def _on_item_thumbnail_ready(self, item_id, pixmap):
        item = self.queue_items.get(item_id)
        if not item:
            return
        item.thumbnail_pixmap = pixmap
        row = self.row_widgets.get(item_id)
        if row:
            row.set_thumbnail_pixmap(pixmap)

    def _on_item_thumbnail_failed(self, item_id, msg):
        # Keep the emoji fallback, but log why so it's easy to diagnose
        # (network blocked, bad URL, non-image response, etc.)
        item = self.queue_items.get(item_id)
        url = item.thumbnail_url if item else "?"
        print(f"[thumbnail] item {item_id} failed to load ({url}): {msg}", file=sys.stderr)

    def _update_row(self, item_id):
        item = self.queue_items.get(item_id)
        row = self.row_widgets.get(item_id)
        if item and row:
            row.update_from(item)

    def _remove_item(self, item_id):
        item = self.queue_items.get(item_id)
        if item and item.status == QUEUE_STATUS_PROCESSING:
            return  # don't allow removing something actively downloading
        row = self.row_widgets.pop(item_id, None)
        if row:
            self.queue_list_lay.removeWidget(row)
            row.deleteLater()
        self.queue_items.pop(item_id, None)
        if item_id in self.download_queue_ids:
            self.download_queue_ids.remove(item_id)
        self._refresh_tabs_and_list()

    def _open_item_folder(self, item_id):
        item = self.queue_items.get(item_id)
        if item:
            self._open_in_explorer(item.output_dir)

    def _open_in_explorer(self, path):
        """Open a folder in the OS's native file browser (Explorer/Finder/etc.)."""
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "Folder Not Found", "That download folder no longer exists.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(self, "Couldn't Open Folder", f"Could not open the folder:\n{e}")

    def _persist_queue(self):
        entries = [
            {"url": qi.url, "title": qi.title, "mode": qi.mode}
            for qi in self.queue_items.values()
            if qi.status != QUEUE_STATUS_COMPLETE
        ]
        self.settings.save_queue(entries)

    def _restore_saved_queue(self):
        for entry in self.settings.load_queue():
            url = entry.get("url")
            if url and not any(qi.url == url for qi in self.queue_items.values()):
                self._add_queue_item(url)

    # ── Filter tabs ──────────────────────────────────────────────────────

    def _set_filter(self, key):
        self.filter_mode = key
        for k, btn in self.filter_buttons.items():
            btn.setObjectName("filterTabActive" if k == key else "filterTabInactive")
            btn.setFont(QFont("Segoe UI", 9, QFont.Bold if k == key else QFont.Normal))
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._refresh_tabs_and_list()

    def _status_matches_filter(self, status):
        if self.filter_mode == "all":
            return True
        return status == self.filter_mode

    def _refresh_tabs_and_list(self):
        counts = {"all": 0, "ready": 0, "processing": 0, "failed": 0, "skipped": 0, "complete": 0}
        for item in self.queue_items.values():
            counts["all"] += 1
            if item.status in counts:
                counts[item.status] += 1

        labels = {
            "all": "All", "ready": "Ready", "processing": "Processing",
            "failed": "Failed", "skipped": "Skipped", "complete": "Complete",
        }
        for key, btn in self.filter_buttons.items():
            btn.setText(f"{labels[key]} ({counts[key]})")

        any_visible = False
        for item_id, row in self.row_widgets.items():
            item = self.queue_items[item_id]
            visible = self._status_matches_filter(item.status)
            row.setVisible(visible)
            any_visible = any_visible or visible
        self.empty_hint.setVisible(len(self.queue_items) == 0)

        ready_count = counts["ready"]
        self.download_all_btn.setText(f"⬇  Download All Ready ({ready_count})")
        self.download_all_btn.setEnabled(ready_count > 0)

        self._persist_queue()

    def _flash_status(self, msg):
        self.history_link.setText(msg)
        QTimer.singleShot(2500, lambda: self.history_link.setText("🕓  History"))

    # ── Format / quality controls ───────────────────────────────────────

    def _on_format_change(self, mode):
        self.settings.set_default_format(mode)
        if mode == "audio":
            self.quality_combo.setCurrentText("Audio Only")
            self.quality_combo.setEnabled(False)
        else:
            self.quality_combo.setEnabled(True)
            if self.quality_combo.currentText() == "Audio Only":
                self.quality_combo.setCurrentIndex(0)

    def _on_quality_change(self, text):
        self.settings.set_default_quality(text)

    # ── Download (single item / all ready) ──────────────────────────────

    def _resolve_mode_quality(self):
        fmt = self.toggle.mode()
        mode = "mp3" if (fmt == "audio" or self.quality_combo.currentText() == "Audio Only") else "mp4"
        quality_map = {
            "Best (4K)": "best", "1080p": "1080", "720p": "720",
            "480p": "480", "360p": "360", "Audio Only": "best",
        }
        quality = quality_map.get(self.quality_combo.currentText(), "best")
        return mode, quality, self.quality_combo.currentText()

    def _download_single(self, item_id):
        item = self.queue_items.get(item_id)
        if not item or item.status == QUEUE_STATUS_PROCESSING:
            return
        if item_id not in self.download_queue_ids:
            self.download_queue_ids.append(item_id)
        self._fill_download_slots()

    def _download_all_ready(self):
        ready_ids = [qi.id for qi in self.queue_items.values() if qi.status == QUEUE_STATUS_READY]
        if not ready_ids:
            return
        for iid in ready_ids:
            if iid not in self.download_queue_ids:
                self.download_queue_ids.append(iid)
        self._fill_download_slots()

    def _fill_download_slots(self):
        while self.download_queue_ids and len(self.workers) < self.MAX_CONCURRENT_DOWNLOADS:
            next_id = self.download_queue_ids.pop(0)
            self._begin_download(next_id)

    def _begin_download(self, item_id):
        item = self.queue_items.get(item_id)
        if not item:
            self._fill_download_slots()
            return

        self.settings.set_subtitles(self.sub_check.isChecked())
        mode, quality, quality_label = self._resolve_mode_quality()
        output_dir = self.settings.get_audio_dir() if mode == "mp3" else self.settings.get_video_dir()
        os.makedirs(output_dir, exist_ok=True)

        # Duplicate-file check
        existing = self._existing_matches(output_dir, item.title)
        if existing and item.status != QUEUE_STATUS_COMPLETE:
            kind = "audio" if mode == "mp3" else "video"
            file_list = "\n".join(f"• {f}" for f in existing[:5])
            more = f"\n…and {len(existing) - 5} more" if len(existing) > 5 else ""
            box = QMessageBox(self)
            box.setWindowTitle("Already Downloaded")
            box.setIcon(QMessageBox.Question)
            box.setText(f"This {kind} already exists in your download folder:")
            box.setInformativeText(f"{file_list}{more}\n\nDownload it again?")
            yes_btn = box.addButton("Download Again", QMessageBox.YesRole)
            no_btn  = box.addButton("Skip", QMessageBox.NoRole)
            box.setDefaultButton(no_btn)
            box.exec_()
            if box.clickedButton() is no_btn:
                item.status = QUEUE_STATUS_SKIPPED
                self._update_row(item_id)
                self._refresh_tabs_and_list()
                self._fill_download_slots()
                return

        item.mode       = mode
        item.quality    = quality
        item.subtitles  = self.sub_check.isChecked()
        item.output_dir = output_dir
        item.status     = QUEUE_STATUS_PROCESSING
        self._update_row(item_id)
        self._refresh_tabs_and_list()

        # Reset the row's mini progress bar to a clean determinate 0% state
        # before this download's signals start arriving.
        row = self.row_widgets.get(item_id)
        if row:
            row.mini_progress.setRange(0, 100)
            row.mini_progress.setValue(0)
            row.mini_progress.setFormat("0.0%")

        worker = DownloadWorker(item.url, mode, quality, output_dir, item.subtitles)
        worker.progress.connect(lambda pct, label, iid=item_id: self._on_progress(iid, pct, label))
        worker.processing.connect(lambda iid=item_id: self._on_processing(iid))
        worker.finished.connect(lambda msg, iid=item_id: self._on_finished(iid, msg))
        worker.error.connect(lambda msg, iid=item_id: self._on_error(iid, msg))
        self.workers[item_id] = worker
        worker.start()

    def _on_progress(self, item_id, pct, label):
        row = self.row_widgets.get(item_id)
        if not row:
            return

        # Make sure we're in determinate mode (a prior "Processing…" state
        # for a *different* download on this row could have left it
        # indeterminate — guard against that here too).
        if row.mini_progress.maximum() == 0:
            row.mini_progress.setRange(0, 100)

        pct_clamped = max(0.0, min(100.0, pct))
        row.mini_progress.setValue(int(pct_clamped))
        row.mini_progress.setFormat(f"{pct_clamped:.1f}%")

        # Smooth red -> green color ramp as progress increases
        colors = [
            "rgb(255,   0,  80)", "rgb(255,  32,  80)", "rgb(255,  64,  80)",
            "rgb(255,  96,  80)", "rgb(255, 128,  80)", "rgb(255, 160,  80)",
            "rgb(255, 192,  80)", "rgb(255, 208,  80)", "rgb(255, 224,  80)",
            "rgb(255, 240,  80)", "rgb(255, 255,  80)", "rgb(224, 255,  80)",
            "rgb(192, 255,  80)", "rgb(160, 255,  80)", "rgb(128, 255,  80)",
            "rgb( 96, 255,  80)", "rgb( 64, 255,  80)", "rgb( 32, 255,  80)",
            "rgb( 16, 255,  80)", "rgb(  8, 255,  80)", "rgb(  0, 255,  80)",
        ]
        index = min(int(pct_clamped / 5), len(colors) - 1)
        color = colors[index]

        row.mini_progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: rgb(40, 40, 40);
                border: 1px solid rgb(70, 70, 70);
                border-radius: 8px;
                color: white;
                text-align: center;
                font-weight: bold;
                font-size: 10px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 7px;
            }}
        """)

    def _on_processing(self, item_id):
        row = self.row_widgets.get(item_id)
        if not row:
            return
        row.mini_progress.setRange(0, 0)   # indeterminate "still working" animation
        row.mini_progress.setFormat("Processing…")
        row.mini_progress.setStyleSheet("""
            QProgressBar {
                background-color: rgb(40, 40, 40);
                border: 1px solid rgb(70, 70, 70);
                border-radius: 8px;
                color: white;
                text-align: center;
                font-weight: bold;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #D4AF37;
                border-radius: 7px;
            }
        """)

    def _on_finished(self, item_id, msg):
        row = self.row_widgets.get(item_id)
        if row:
            row.mini_progress.setRange(0, 100)   # leave indeterminate mode
            row.mini_progress.setValue(100)
            row.mini_progress.setFormat("100%")
        item = self.queue_items.get(item_id)
        if item:
            item.status = QUEUE_STATUS_COMPLETE
            self._update_row(item_id)
            self.settings.add_history_entry({
                "title": item.title,
                "url": item.url,
                "type": "Audio (MP3)" if item.mode == "mp3" else f"Video ({item.quality})",
                "folder": item.output_dir,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
        self.workers.pop(item_id, None)
        self._refresh_tabs_and_list()
        self._fill_download_slots()

    def _on_error(self, item_id, msg):
        row = self.row_widgets.get(item_id)
        if row:
            row.mini_progress.setRange(0, 100)   # leave indeterminate mode
        item = self.queue_items.get(item_id)
        if item:
            item.status = QUEUE_STATUS_FAILED
            item.error_msg = msg
            self._update_row(item_id)
        self.workers.pop(item_id, None)
        self._refresh_tabs_and_list()
        self._fill_download_slots()

    def _advance_download_queue(self):
        self._fill_download_slots()

    # ── Settings / history dialogs ───────────────────────────────────────

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        dlg.exec_()

    def _build_history_panel(self):
        """Integrated Download History panel, styled to match the app theme,
        docked to the right of the queue list instead of popping up."""
        panel = QWidget()
        panel.setObjectName("historyPanel")
        panel.setFixedWidth(320)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(10)

        header_row = QHBoxLayout()
        title = QLabel("Download History")
        title.setObjectName("historyTitle")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        header_row.addWidget(title)
        header_row.addStretch()
        panel_close_btn = QPushButton("✕")
        panel_close_btn.setObjectName("historyPanelCloseBtn")
        panel_close_btn.setFixedSize(24, 24)
        panel_close_btn.setCursor(Qt.PointingHandCursor)
        panel_close_btn.clicked.connect(self._toggle_history_panel)
        header_row.addWidget(panel_close_btn)
        lay.addLayout(header_row)

        self.history_list = QListWidget()
        self.history_list.setObjectName("historyList")
        self.history_list.itemDoubleClicked.connect(self._open_history_item_folder)
        lay.addWidget(self.history_list, stretch=1)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear History")
        clear_btn.setObjectName("historyClearBtn")
        clear_btn.setFixedHeight(34)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_history)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("historyCloseBtn")
        close_btn.setFixedHeight(34)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._toggle_history_panel)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        return panel

    def _toggle_history_panel(self):
        showing = not self.history_panel.isVisible()
        if showing:
            self._refresh_history_list()
        self.history_panel.setVisible(showing)
        self.history_link.setText("🕓  Hide History" if showing else "🕓  History")

    def _refresh_history_list(self):
        self.history_list.clear()
        history = self.settings.load_history()
        if not history:
            item = QListWidgetItem("No downloads yet.")
            item.setFlags(Qt.NoItemFlags)
            self.history_list.addItem(item)
            return
        for entry in history:
            kind_icon = "🎵" if "Audio" in entry.get("type", "") else "🎬"
            list_item = QListWidgetItem(
                f"{kind_icon}  {entry.get('title', 'Unknown')}\n"
                f"     {entry.get('type', '')} • {entry.get('timestamp', '')}\n"
                f"     {entry.get('folder', '')}"
            )
            list_item.setData(Qt.UserRole, entry.get("folder", ""))
            list_item.setToolTip("Double-click to open this folder")
            self.history_list.addItem(list_item)

    def _open_history_item_folder(self, list_item):
        folder = list_item.data(Qt.UserRole)
        if folder:
            self._open_in_explorer(folder)

    def _clear_history(self):
        self.settings.clear_history()
        self._refresh_history_list()

    def _reload_history(self):
        pass  # history now lives entirely in its own dialog, loaded on open


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    win = YouTubeDownloader()
    win.show()
    sys.exit(app.exec_())