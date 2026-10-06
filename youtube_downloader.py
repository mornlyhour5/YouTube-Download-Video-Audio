import sys
import os
import json
import re
import subprocess
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QComboBox,
    QFileDialog, QFrame, QCheckBox,
    QSizePolicy, QScrollArea, QDialog, QRadioButton, QButtonGroup,
    QMessageBox, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QSettings
from PyQt5.QtGui import QFont, QIcon, QPixmap, QPainter, QPainterPath
import urllib.request
import urllib.parse as urlparse
import yt_dlp

# New professional theme, vector icons and stylesheets live in ui_style.py
from ui_style import THEMES, make_icon, build_main_qss, build_dialog_qss


def resource_path(filename):
    """Get path to a bundled resource, works both in dev and in a PyInstaller .exe."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


# ── Quality options ──────────────────────────────────────────────────────────

APP_VERSION = "1.4.0"

QUALITY_KEYS = ["best4k", "1080p", "720p", "480p", "360p", "audio_only"]

QUALITY_TO_YTDLP = {
    "best4k": "best", "1080p": "1080", "720p": "720",
    "480p": "480", "360p": "360", "audio_only": "best",
}

_LEGACY_QUALITY_MAP = {
    "Best (4K)": "best4k", "1080p": "1080p", "720p": "720p",
    "480p": "480p", "360p": "360p", "Audio Only": "audio_only",
}


# ── Persistent settings ───────────────────────────────────────────────────────

class AppSettings:
    ORG = "ProYTTools"
    APP = "YouTubeDownloader"

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
        raw = self._s.value("prefs/default_quality", "best4k")
        return _LEGACY_QUALITY_MAP.get(raw, raw if raw in QUALITY_KEYS else "best4k")

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

    def get_theme(self):
        val = self._s.value("prefs/theme", "dark")
        return val if val in ("dark", "light") else "dark"

    def set_theme(self, val):
        self._s.setValue("prefs/theme", val)
        self._s.sync()

    def get_language(self):
        val = self._s.value("prefs/language", "en")
        return val if val in ("en", "km") else "en"

    def set_language(self, val):
        self._s.setValue("prefs/language", val)
        self._s.sync()

    # ── Download history ──────────────────────────────────────────────────

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
        history.insert(0, entry)
        history = history[:500]
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

    # ── Pending queue ─────────────────────────────────────────────────────

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


# ── ANSI helpers ────────────────────────────────────────────────────────────
# yt-dlp progress strings can contain ANSI color codes that break float().

_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def _strip_ansi(text):
    if not text:
        return ""
    return _ANSI_ESCAPE_RE.sub("", str(text)).strip()


# ── Shared yt-dlp network/retry options ─────────────────────────────────────

_RETRY_OPTS = {
    "retries": 15,
    "fragment_retries": 15,
    "extractor_retries": 7,
    "socket_timeout": 30,
    "http_chunk_size": 10485760,
}

_EXTRACTOR_ARGS = {
    "youtube": {
        "player_client": ["web_embedded", "web", "android", "tv"],
        "player_skip": ["configs", "js"],
    },
}


# ── Translations (English / Khmer) ──────────────────────────────────────────
# Leading decorative symbols ("⚙  Settings") are stripped by tr(); the UI now
# uses vector icons instead, so the plain text is what is displayed.

TRANSLATIONS = {
    "en": {
        "paste_link": "Paste Link",
        "video": "Video",
        "audio": "Audio",
        "quality_best": "Best (4K)",
        "quality_audio_only": "Audio Only",
        "subtitles": "Subtitles",
        "settings": "Settings",
        "settings_window_title": "Settings",
        "version_label": "version {v}",
        "download_all_ready": "Download All Ready",
        "theme_tooltip": "Switch between dark and light theme",
        "tab_all": "All", "tab_ready": "Ready", "tab_processing": "Processing",
        "tab_failed": "Failed", "tab_skipped": "Skipped", "tab_complete": "Complete",
        "empty_hint_youtube": 'No YouTube links yet — click "Paste Link" to add one.',
        "empty_hint_meta": 'No Facebook or Instagram links yet — click "Paste Link" to add one.',
        "empty_hint_tiktok": 'No TikTok links yet — click "Paste Link" to add one.',
        "added_to_other_page": "Also added to: {pages}",
        "history": "History",
        "hide_history": "Hide History",
        "status_queued": "Queued",
        "status_loading": "Loading info…",
        "status_ready": "Ready",
        "status_processing": "Downloading…",
        "status_complete": "Done",
        "status_failed": "Failed",
        "status_skipped": "Skipped",
        "progress_processing": "Processing…",
        "tooltip_download": "Download this item",
        "tooltip_download_again": "Download again",
        "tooltip_open_folder": "Open containing folder",
        "tooltip_remove": "Remove from list",
        "history_title": "Download History",
        "history_clear": "Clear History",
        "history_close": "Close",
        "history_empty": "No downloads yet.",
        "history_tooltip_open": "Double-click to open folder",
        "history_type_audio": "Audio (MP3)",
        "history_type_video": "Video",
        "settings_title": "Preferences",
        "settings_subtitle": "Choose where downloads are stored. Your choice is saved automatically.",
        "appearance": "Appearance",
        "theme_dark": "Dark theme",
        "theme_light": "Light theme",
        "language_section": "Language",
        "storage_mode": "Storage Mode",
        "storage_same": "Use one folder for everything",
        "storage_split": "Use separate folders for Video and Audio",
        "video_location": "Video Save Location",
        "combined_location": "Save Location (Video & Audio)",
        "audio_location": "Audio Save Location",
        "browse": "Browse...",
        "done": "Done",
        "no_link_title": "No Link Found",
        "no_link_text": 'Copy a YouTube, Facebook, Instagram or TikTok link to your clipboard first, then click "Paste Link".',
        "already_in_list": "That link is already in your list.",
        "already_downloaded_title": "Already Downloaded",
        "already_downloaded_audio_text": "This audio already exists in your download folder:",
        "already_downloaded_video_text": "This video already exists in your download folder:",
        "and_more": "…and {n} more",
        "confirm_download_again": "Download it again?",
        "btn_download_again": "Download Again",
        "btn_skip": "Skip",
        "folder_not_found_title": "Folder Not Found",
        "folder_not_found_text": "That download folder no longer exists.",
        "couldnt_open_folder_title": "Couldn't Open Folder",
        "couldnt_open_folder_text": "Could not open the folder:\n{e}",
        "select_video_folder": "Select Video Folder",
        "select_audio_folder": "Select Audio Folder",
        "playlist_title": "Playlist Detected",
        "playlist_text": "This link is part of a playlist or Mix.\n\nAdd every video (up to {n}) or only this one?",
        "playlist_add_all": "Add All Videos",
        "playlist_add_one": "Just This Video",
        "btn_cancel": "Cancel",
        "playlist_loading": "Loading playlist…",
        "playlist_added": "Added {n} videos from the playlist",
        "playlist_nothing_new": "All videos from that playlist are already in your list.",
        "playlist_failed_title": "Couldn't Load Playlist",
    },
    "km": {
        "paste_link": "បិទភ្ជាប់តំណ",
        "video": "វីដេអូ",
        "audio": "សំឡេង",
        "quality_best": "ល្អបំផុត (4K)",
        "quality_audio_only": "តែសំឡេងប៉ុណ្ណោះ",
        "subtitles": "អក្សររត់",
        "settings": "ការកំណត់",
        "settings_window_title": "ការកំណត់",
        "version_label": "កំណែ {v}",
        "download_all_ready": "ទាញយកទាំងអស់ដែលរួចរាល់",
        "theme_tooltip": "ប្តូររវាងរបៀបងងឹត និងរបៀបភ្លឺ",
        "tab_all": "ទាំងអស់", "tab_ready": "រួចរាល់", "tab_processing": "កំពុងដំណើរការ",
        "tab_failed": "បរាជ័យ", "tab_skipped": "រំលង", "tab_complete": "បញ្ចប់",
        "empty_hint_youtube": 'មិនទាន់មានតំណ YouTube នៅឡើយទេ — ចុច "បិទភ្ជាប់តំណ" ដើម្បីបន្ថែម។',
        "empty_hint_meta": 'មិនទាន់មានតំណ Facebook ឬ Instagram នៅឡើយទេ — ចុច "បិទភ្ជាប់តំណ" ដើម្បីបន្ថែម។',
        "empty_hint_tiktok": 'មិនទាន់មានតំណ TikTok នៅឡើយទេ — ចុច "បិទភ្ជាប់តំណ" ដើម្បីបន្ថែម។',
        "added_to_other_page": "ក៏បានបន្ថែមទៅក្នុង៖ {pages}",
        "history": "ប្រវត្តិ",
        "hide_history": "លាក់ប្រវត្តិ",
        "status_queued": "ក្នុងជួរ",
        "status_loading": "កំពុងផ្ទុកព័ត៌មាន…",
        "status_ready": "រួចរាល់",
        "status_processing": "កំពុងទាញយក…",
        "status_complete": "បានបញ្ចប់",
        "status_failed": "បរាជ័យ",
        "status_skipped": "រំលង",
        "progress_processing": "កំពុងដំណើរការ…",
        "tooltip_download": "ទាញយកធាតុនេះ",
        "tooltip_download_again": "ទាញយកម្តងទៀត",
        "tooltip_open_folder": "បើកថតដែលមានឯកសារនេះ",
        "tooltip_remove": "លុបចេញពីបញ្ជី",
        "history_title": "ប្រវត្តិទាញយក",
        "history_clear": "សម្អាតប្រវត្តិ",
        "history_close": "បិទ",
        "history_empty": "មិនទាន់មានការទាញយកនៅឡើយទេ។",
        "history_tooltip_open": "ចុចពីរដងដើម្បីបើកថត",
        "history_type_audio": "សំឡេង (MP3)",
        "history_type_video": "វីដេអូ",
        "settings_title": "ចំណូលចិត្ត",
        "settings_subtitle": "ជ្រើសរើសកន្លែងរក្សាទុកការទាញយក។ ជម្រើសរបស់អ្នកនឹងត្រូវបានរក្សាទុកដោយស្វ័យប្រវត្តិ។",
        "appearance": "រូបរាង",
        "theme_dark": "រូបរាងងងឹត",
        "theme_light": "រូបរាងភ្លឺ",
        "language_section": "ភាសា",
        "storage_mode": "របៀបផ្ទុក",
        "storage_same": "ប្រើថតតែមួយសម្រាប់អ្វីៗទាំងអស់",
        "storage_split": "ប្រើថតដាច់ដោយឡែកសម្រាប់វីដេអូ និងសំឡេង",
        "video_location": "ទីតាំងរក្សាទុកវីដេអូ",
        "combined_location": "ទីតាំងរក្សាទុក (វីដេអូ និងសំឡេង)",
        "audio_location": "ទីតាំងរក្សាទុកសំឡេង",
        "browse": "រកមើល...",
        "done": "រួចរាល់",
        "no_link_title": "រកមិនឃើញតំណ",
        "no_link_text": 'ចម្លងតំណ YouTube, Facebook, Instagram ឬ TikTok ទៅក្ដារតម្បៀតខ្ទាស់របស់អ្នកជាមុនសិន រួចចុច "បិទភ្ជាប់តំណ"។',
        "already_in_list": "តំណនោះមានរួចហើយនៅក្នុងបញ្ជីរបស់អ្នក។",
        "already_downloaded_title": "បានទាញយករួចហើយ",
        "already_downloaded_audio_text": "សំឡេងនេះមានរួចហើយនៅក្នុងថតទាញយករបស់អ្នក៖",
        "already_downloaded_video_text": "វីដេអូនេះមានរួចហើយនៅក្នុងថតទាញយករបស់អ្នក៖",
        "and_more": "…និងមានទៀត {n}",
        "confirm_download_again": "តើចង់ទាញយកម្តងទៀតទេ?",
        "btn_download_again": "ទាញយកម្តងទៀត",
        "btn_skip": "រំលង",
        "folder_not_found_title": "រកមិនឃើញថត",
        "folder_not_found_text": "ថតទាញយកនោះលែងមានទៀតហើយ។",
        "couldnt_open_folder_title": "មិនអាចបើកថតបានទេ",
        "couldnt_open_folder_text": "មិនអាចបើកថតបានទេ៖\n{e}",
        "select_video_folder": "ជ្រើសរើសថតវីដេអូ",
        "select_audio_folder": "ជ្រើសរើសថតសំឡេង",
        "playlist_title": "រកឃើញបញ្ជីចាក់",
        "playlist_text": "តំណនេះជាផ្នែកមួយនៃបញ្ជីចាក់ ឬ Mix។\n\nបន្ថែមវីដេអូទាំងអស់ (រហូតដល់ {n}) ឬតែវីដេអូនេះ?",
        "playlist_add_all": "បន្ថែមវីដេអូទាំងអស់",
        "playlist_add_one": "តែវីដេអូនេះ",
        "btn_cancel": "បោះបង់",
        "playlist_loading": "កំពុងផ្ទុកបញ្ជីចាក់…",
        "playlist_added": "បានបន្ថែមវីដេអូ {n} ពីបញ្ជីចាក់",
        "playlist_nothing_new": "វីដេអូទាំងអស់ពីបញ្ជីចាក់នោះមានក្នុងបញ្ជីរបស់អ្នករួចហើយ។",
        "playlist_failed_title": "មិនអាចផ្ទុកបញ្ជីចាក់បានទេ",
    },
}

# Strips a leading decorative symbol + two spaces, e.g. "⚙  Settings" -> "Settings"
_ICON_PREFIX_RE = re.compile(r'^[^\w\s]+\s{2}')


def tr(lang, key, **kwargs):
    """Look up a translated string, falling back to English."""
    table = TRANSLATIONS.get(lang) or TRANSLATIONS["en"]
    text = table.get(key, TRANSLATIONS["en"].get(key, key))
    text = _ICON_PREFIX_RE.sub("", text)
    return text.format(**kwargs) if kwargs else text


# ── Workers ────────────────────────────────────────────────────────────────────

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
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0

            if total:
                pct_f = (downloaded / total) * 100.0
            else:
                raw = _strip_ansi(d.get("_percent_str", "0%")).replace("%", "").strip()
                try:
                    pct_f = float(raw)
                except ValueError:
                    pct_f = self._last_pct if self._last_pct >= 0 else 0.0

            speed = _strip_ansi(d.get("_speed_str", ""))
            eta   = _strip_ansi(d.get("_eta_str", ""))
            label = f"{speed}  ETA {eta}" if speed else ""

            if abs(pct_f - self._last_pct) >= 0.1 or self._last_pct < 0:
                self._last_pct = pct_f
                self.progress.emit(pct_f, label)
        elif d["status"] == "finished":
            self._last_pct = 100.0
            self.progress.emit(100.0, "Processing…")
            self.processing.emit()

    def _base_opts(self):
        return {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "allow_unplayable_formats": False,
            **_RETRY_OPTS,
            "extractor_args": _EXTRACTOR_ARGS,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://www.youtube.com/",
                "Accept-Encoding": "gzip, deflate",
                "DNT": "1",
                "Sec-CH-UA": '"Not_A_Brand";v="8", "Chromium";v="131"',
                "Sec-CH-UA-Mobile": "?0",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            },
        }

    def _cookie_opts(self):
        cookie_file = resource_path("cookies.txt")
        if os.path.exists(cookie_file):
            return {"cookiefile": cookie_file}
        return {}

    def run(self):
        try:
            outtmpl = os.path.join(self.output_dir, "%(title)s.%(ext)s")
            base = self._base_opts()
            base.update(self._cookie_opts())

            if self.mode == "mp3":
                ydl_opts = {
                    **base,
                    "format": "bestaudio/best",
                    "outtmpl": outtmpl,
                    "progress_hooks": [self._hook],
                    "writethumbnail": True,
                    "postprocessors": [
                        {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
                        {"key": "FFmpegMetadata", "add_metadata": True},
                        {"key": "EmbedThumbnail", "already_have_thumbnail": False},
                    ],
                    "convert_thumbnails": "jpg",
                }
            else:
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
                        {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
                        {"key": "EmbedThumbnail", "already_have_thumbnail": False},
                        {"key": "FFmpegMetadata", "add_metadata": True},
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
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "https://www.youtube.com/",
                    "Accept-Encoding": "gzip, deflate",
                    "DNT": "1",
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
        thumbs = info.get("thumbnails") or []
        if thumbs:
            sized = [t for t in thumbs if t.get("width")]
            if sized:
                sized.sort(key=lambda t: abs(t["width"] - 96))
                return sized[0].get("url")
            return thumbs[-1].get("url")
        return info.get("thumbnail")


MAX_PLAYLIST_ITEMS = 50   # safety cap; YouTube Mixes are practically endless


class PlaylistWorker(QThread):
    """Expands a playlist / Mix link into a list of single-video entries
    (flat extraction: fast, nothing is downloaded)."""
    entries_ready = pyqtSignal(list)
    error         = pyqtSignal(str)

    def __init__(self, url, limit=MAX_PLAYLIST_ITEMS):
        super().__init__()
        self.url   = url
        self.limit = limit

    def run(self):
        try:
            cookie_file = resource_path("cookies.txt")
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "extract_flat": "in_playlist",
                "noplaylist": False,
                "playlistend": self.limit,
                **_RETRY_OPTS,
                "extractor_args": _EXTRACTOR_ARGS,
                "http_headers": {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            }
            if os.path.exists(cookie_file):
                opts["cookiefile"] = cookie_file
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)

            entries = []
            for e in (info.get("entries") or []):
                if not e:
                    continue
                url = e.get("url") or ""
                if not url.startswith("http"):
                    vid = e.get("id")
                    if not vid:
                        continue
                    url = f"https://www.youtube.com/watch?v={vid}"
                entries.append({
                    "url": url,
                    "title": e.get("title") or url,
                    "channel": e.get("uploader") or e.get("channel") or "",
                })
                if len(entries) >= self.limit:
                    break
            if not entries:
                raise ValueError("No videos were found in this playlist.")
            self.entries_ready.emit(entries)
        except Exception as ex:
            self.error.emit(str(ex))


class ThumbnailWorker(QThread):
    """Downloads a thumbnail image off the UI thread."""
    thumb_ready = pyqtSignal(int, QPixmap)
    failed      = pyqtSignal(int, str)

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
                        "Chrome/131.0.0.0 Safari/537.36"
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
        # Required so the stylesheet background/border actually paints
        # on a QWidget subclass.
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)
        self._layout = lay

    def layout(self):
        return self._layout


# ── Toggle button pair ─────────────────────────────────────────────────────────

class ToggleGroup(QWidget):
    changed = pyqtSignal(str)   # emits "video" or "audio"

    def __init__(self, video_text="Video", audio_text="Audio", parent=None):
        super().__init__(parent)
        self._mode = "video"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.btn_video = QPushButton(video_text)
        self.btn_audio = QPushButton(audio_text)
        for btn in (self.btn_video, self.btn_audio):
            btn.setFixedHeight(30)
            btn.setFont(QFont("Segoe UI", 10))
            btn.setCursor(Qt.PointingHandCursor)

        self.btn_video.setObjectName("toggleActive")
        self.btn_audio.setObjectName("toggleInactive")
        self.btn_video.clicked.connect(lambda: self._select("video"))
        self.btn_audio.clicked.connect(lambda: self._select("audio"))

        container = QWidget()
        container.setObjectName("toggleContainer")
        c_lay = QHBoxLayout(container)
        c_lay.setContentsMargins(4, 4, 4, 4)
        c_lay.setSpacing(2)
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
        for b in (self.btn_video, self.btn_audio):
            b.style().unpolish(b)
            b.style().polish(b)
        self.changed.emit(mode)

    def mode(self):
        return self._mode

    def set_mode(self, mode):
        self._select(mode)

    def set_labels(self, video_text, audio_text):
        self.btn_video.setText(video_text)
        self.btn_audio.setText(audio_text)


# ── Settings dialog ────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    """Where video/audio are saved, plus theme and language. Saved immediately."""

    def __init__(self, settings: AppSettings, theme, language, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.theme = theme
        self.language = language
        self.setWindowTitle(self._t("settings_window_title"))
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setMinimumSize(440, 300)
        screen = QApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() if screen else 800
        self.resize(540, max(300, min(580, avail_h - 120)))
        self._build_ui()
        self._apply_style()
        self._load_current()

    def _t(self, key, **kwargs):
        return tr(self.language, key, **kwargs)

    def _make_folder_row(self, browse_handler):
        row = QHBoxLayout()
        row.setSpacing(8)
        line = QLineEdit()
        line.setObjectName("folderInput")
        line.setFixedHeight(34)
        line.setReadOnly(True)
        line.setFont(QFont("Segoe UI", 10))
        btn = QPushButton(self._t("browse"))
        btn.setObjectName("browseBtn")
        btn.setFixedHeight(34)
        btn.setFixedWidth(96)
        btn.setFont(QFont("Segoe UI", 10))
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(browse_handler)
        row.addWidget(line)
        row.addWidget(btn)
        return row, line, btn

    def _card_title(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("cardTitle")
        lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        return lbl

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 16)
        outer.setSpacing(8)

        self.dlg_title_lbl = QLabel(self._t("settings_title"))
        self.dlg_title_lbl.setObjectName("dlgTitle")
        self.dlg_title_lbl.setFont(QFont("Segoe UI", 15, QFont.Bold))
        outer.addWidget(self.dlg_title_lbl)

        self.dlg_subtitle_lbl = QLabel(self._t("settings_subtitle"))
        self.dlg_subtitle_lbl.setObjectName("dlgSubtitle")
        self.dlg_subtitle_lbl.setFont(QFont("Segoe UI", 9))
        self.dlg_subtitle_lbl.setWordWrap(True)
        outer.addWidget(self.dlg_subtitle_lbl)

        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("settingsContent")
        content.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 6, 12, 6)
        root.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # Appearance
        appearance_card = Card()
        lay = appearance_card.layout()
        self.appearance_lbl = self._card_title(self._t("appearance"))
        lay.addWidget(self.appearance_lbl)
        self.theme_radio_group = QButtonGroup(self)
        self.radio_dark = QRadioButton(self._t("theme_dark"))
        self.radio_light = QRadioButton(self._t("theme_light"))
        for r in (self.radio_dark, self.radio_light):
            r.setObjectName("settingsRadio")
            r.setFont(QFont("Segoe UI", 10))
            r.setCursor(Qt.PointingHandCursor)
            self.theme_radio_group.addButton(r)
        self.radio_dark.toggled.connect(self._on_theme_toggled)
        lay.addWidget(self.radio_dark)
        lay.addWidget(self.radio_light)
        root.addWidget(appearance_card)

        # Language
        language_card = Card()
        lay = language_card.layout()
        self.language_lbl = self._card_title(self._t("language_section"))
        lay.addWidget(self.language_lbl)
        self.language_radio_group = QButtonGroup(self)
        self.radio_en = QRadioButton("English")
        self.radio_km = QRadioButton("ខ្មែរ")
        for r in (self.radio_en, self.radio_km):
            r.setObjectName("settingsRadio")
            r.setFont(QFont("Segoe UI", 10))
            r.setCursor(Qt.PointingHandCursor)
            self.language_radio_group.addButton(r)
        self.radio_en.toggled.connect(self._on_language_toggled)
        lay.addWidget(self.radio_en)
        lay.addWidget(self.radio_km)
        root.addWidget(language_card)

        # Storage mode
        same_card = Card()
        lay = same_card.layout()
        self.storage_mode_lbl = self._card_title(self._t("storage_mode"))
        lay.addWidget(self.storage_mode_lbl)
        self.radio_group = QButtonGroup(self)
        self.radio_same = QRadioButton(self._t("storage_same"))
        self.radio_split = QRadioButton(self._t("storage_split"))
        for r in (self.radio_same, self.radio_split):
            r.setObjectName("settingsRadio")
            r.setFont(QFont("Segoe UI", 10))
            r.setCursor(Qt.PointingHandCursor)
            self.radio_group.addButton(r)
        self.radio_same.toggled.connect(self._toggle_mode)
        lay.addWidget(self.radio_same)
        lay.addWidget(self.radio_split)
        root.addWidget(same_card)

        # Video folder
        video_card = Card()
        self.video_title_lbl = self._card_title(self._t("video_location"))
        video_card.layout().addWidget(self.video_title_lbl)
        v_row, self.video_path, self.video_browse_btn = self._make_folder_row(self._browse_video)
        video_card.layout().addLayout(v_row)
        root.addWidget(video_card)
        self.video_card = video_card

        # Audio folder
        audio_card = Card()
        self.audio_card_title_lbl = self._card_title(self._t("audio_location"))
        audio_card.layout().addWidget(self.audio_card_title_lbl)
        a_row, self.audio_path, self.audio_browse_btn = self._make_folder_row(self._browse_audio)
        audio_card.layout().addLayout(a_row)
        root.addWidget(audio_card)
        self.audio_card = audio_card
        root.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.done_btn = QPushButton(self._t("done"))
        self.done_btn.setObjectName("dlBtnSmall")
        self.done_btn.setFixedHeight(38)
        self.done_btn.setFixedWidth(120)
        self.done_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.done_btn.setCursor(Qt.PointingHandCursor)
        self.done_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.done_btn)
        outer.addLayout(btn_row)

    def _retranslate_ui(self):
        self.setWindowTitle(self._t("settings_window_title"))
        self.dlg_title_lbl.setText(self._t("settings_title"))
        self.dlg_subtitle_lbl.setText(self._t("settings_subtitle"))
        self.appearance_lbl.setText(self._t("appearance"))
        self.radio_dark.setText(self._t("theme_dark"))
        self.radio_light.setText(self._t("theme_light"))
        self.language_lbl.setText(self._t("language_section"))
        self.storage_mode_lbl.setText(self._t("storage_mode"))
        self.radio_same.setText(self._t("storage_same"))
        self.radio_split.setText(self._t("storage_split"))
        self.audio_card_title_lbl.setText(self._t("audio_location"))
        self.video_browse_btn.setText(self._t("browse"))
        self.audio_browse_btn.setText(self._t("browse"))
        self.done_btn.setText(self._t("done"))
        self._toggle_mode()

    def _load_current(self):
        theme_name = self.settings.get_theme()
        self.radio_dark.setChecked(theme_name != "light")
        self.radio_light.setChecked(theme_name == "light")

        self.radio_en.setChecked(self.language != "km")
        self.radio_km.setChecked(self.language == "km")

        use_same = self.settings.get_use_same_dir()
        self.radio_same.setChecked(use_same)
        self.radio_split.setChecked(not use_same)
        self.video_path.setText(self.settings.get_video_dir())
        self.audio_path.setText(self.settings.get_audio_dir())
        self._toggle_mode()

    def _on_theme_toggled(self):
        name = "light" if self.radio_light.isChecked() else "dark"
        parent = self.parent()
        if parent is not None and hasattr(parent, "_apply_theme"):
            parent._apply_theme(name)
            self.theme = parent.theme
        else:
            self.settings.set_theme(name)
            self.theme = THEMES[name]
        self._apply_style()

    def _on_language_toggled(self):
        name = "km" if self.radio_km.isChecked() else "en"
        if name == self.language:
            return
        self.language = name
        parent = self.parent()
        if parent is not None and hasattr(parent, "_apply_language"):
            parent._apply_language(name)
        else:
            self.settings.set_language(name)
        self._retranslate_ui()

    def _toggle_mode(self):
        split = self.radio_split.isChecked()
        self.audio_card.setVisible(split)
        self.video_title_lbl.setText(
            self._t("video_location") if split else self._t("combined_location")
        )
        self.settings.set_use_same_dir(not split)

    def _browse_video(self):
        folder = QFileDialog.getExistingDirectory(self, self._t("select_video_folder"), self.video_path.text())
        if folder:
            self.video_path.setText(folder)
            self.settings.set_video_dir(folder)
            if self.radio_same.isChecked():
                self.settings.set_audio_dir(folder)
                self.audio_path.setText(folder)

    def _browse_audio(self):
        folder = QFileDialog.getExistingDirectory(self, self._t("select_audio_folder"), self.audio_path.text())
        if folder:
            self.audio_path.setText(folder)
            self.settings.set_audio_dir(folder)

    def _apply_style(self):
        self.setStyleSheet(build_dialog_qss(self.theme))


# ── Queue model / helpers ──────────────────────────────────────────────────────

QUEUE_STATUS_QUEUED     = "queued"
QUEUE_STATUS_LOADING    = "loading"
QUEUE_STATUS_READY      = "ready"
QUEUE_STATUS_PROCESSING = "processing"
QUEUE_STATUS_COMPLETE   = "complete"
QUEUE_STATUS_FAILED     = "failed"
QUEUE_STATUS_SKIPPED    = "skipped"

_VIDEO_URL_RE = re.compile(
    r'(https?://[^\s]*(?:'
    r'youtube\.com|youtu\.be'
    r'|(?:[a-z0-9-]+\.)?facebook\.com|fb\.watch'
    r'|(?:www\.)?instagram\.com|instagr\.am'
    r'|(?:[a-z0-9-]+\.)?tiktok\.com'
    r')[^\s]*)',
    re.IGNORECASE,
)

PLATFORM_LABELS = {"youtube": "YouTube", "facebook": "Facebook", "instagram": "Instagram", "tiktok": "TikTok"}

PAGE_YOUTUBE = "youtube"
PAGE_META = "meta"
PAGE_TIKTOK = "tiktok"
PAGE_KEYS = [PAGE_YOUTUBE, PAGE_META, PAGE_TIKTOK]

PLATFORM_TO_PAGE = {
    "youtube": PAGE_YOUTUBE,
    "facebook": PAGE_META,
    "instagram": PAGE_META,
    "tiktok": PAGE_TIKTOK,
}

PAGE_NAMES = {PAGE_YOUTUBE: "YouTube", PAGE_META: "Facebook & Instagram", PAGE_TIKTOK: "TikTok"}


def _page_tab_text(key, count):
    # "&" is a keyboard-mnemonic marker in Qt button text; "&&" shows a literal "&".
    return f"{PAGE_NAMES[key].replace('&', '&&')}   ({count})"


def _detect_platform(url):
    host = (url or "").lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "facebook.com" in host or "fb.watch" in host:
        return "facebook"
    if "instagram.com" in host or "instagr.am" in host:
        return "instagram"
    if "tiktok.com" in host:
        return "tiktok"
    return "other"


_YT_LIST_STRIP_RE = re.compile(r'([&?])(list|start_radio|index)=[^&]*')

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid",
    "extid", "mibextid", "rdid",
    "igshid", "igsh",
    "is_from_webapp", "sender_device", "sender_web_id", "web_id",
    "share_app_id", "share_item_id", "_r", "_t", "checksum",
}


def _youtube_list_info(url):
    """Returns (has_list, has_single_video) for a YouTube URL."""
    if _detect_platform(url) != "youtube":
        return False, True
    try:
        parts = urlparse.urlsplit(url)
    except ValueError:
        return False, True
    q = dict(urlparse.parse_qsl(parts.query))
    has_list = bool(q.get("list"))
    has_video = bool(q.get("v")) or "youtu.be" in parts.netloc.lower() or "/shorts/" in parts.path
    return has_list, has_video


def _clean_url(url, keep_list=False):
    """Strip YouTube playlist params and known tracking-only params."""
    cleaned = url
    if _detect_platform(url) == "youtube" and not keep_list:
        cleaned = _YT_LIST_STRIP_RE.sub('', url)
    try:
        parts = urlparse.urlsplit(cleaned)
        if parts.query:
            kept = [
                (k, v) for k, v in urlparse.parse_qsl(parts.query, keep_blank_values=True)
                if k.lower() not in _TRACKING_PARAMS
            ]
            cleaned = urlparse.urlunsplit(parts._replace(query=urlparse.urlencode(kept)))
    except ValueError:
        pass
    cleaned = re.sub(r'[?&]+$', '', cleaned)
    cleaned = cleaned.replace('?&', '?')
    return cleaned


_STATUS_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|\[[0-9;]*m")


def _clean_status_text(text):
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
        self.channel    = ""
        self.duration   = ""
        self.platform   = _detect_platform(url)
        self.thumbnail_url = ""
        self.thumbnail_pixmap = None
        self.status     = QUEUE_STATUS_QUEUED
        self.mode       = "mp4"
        self.quality    = "best"
        self.subtitles  = False
        self.error_msg  = ""
        self.output_dir = ""


class QueueRowWidget(QWidget):
    """A single visual row in the queue list."""
    download_clicked     = pyqtSignal(int)
    remove_clicked       = pyqtSignal(int)
    open_folder_clicked  = pyqtSignal(int)

    def __init__(self, item: QueueItem, parent=None):
        super().__init__(parent)
        self.item_id = item.id
        self.setObjectName("queueRow")
        self.setAttribute(Qt.WA_StyledBackground, True)   # paint bg / hover / border
        self.setFixedHeight(68)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(12)

        self.thumb = QLabel("▶")
        self.thumb.setObjectName("rowThumb")
        self.thumb.setFixedSize(48, 48)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFont(QFont("Segoe UI", 14, QFont.Bold))
        lay.addWidget(self.thumb)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self.title_lbl = QLabel()
        self.title_lbl.setObjectName("rowTitle")
        self.title_lbl.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        self.title_lbl.setWordWrap(False)
        self.title_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("rowStatus")
        self.status_lbl.setFont(QFont("Segoe UI", 8))
        self.status_lbl.setWordWrap(False)
        self.status_lbl.setTextInteractionFlags(Qt.NoTextInteraction)
        self.status_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_col.addWidget(self.title_lbl)
        text_col.addWidget(self.status_lbl)
        lay.addLayout(text_col, stretch=1)

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

        # Icon-only action buttons (icons are set in update_from, per theme)
        self.download_btn = QPushButton()
        self.download_btn.setObjectName("rowDownloadBtn")
        self.folder_btn = QPushButton()
        self.folder_btn.setObjectName("rowFolderBtn")
        self.remove_btn = QPushButton()
        self.remove_btn.setObjectName("rowRemoveBtn")
        for btn in (self.download_btn, self.folder_btn, self.remove_btn):
            btn.setFixedSize(32, 32)
            btn.setIconSize(QSize(16, 16))
            btn.setCursor(Qt.PointingHandCursor)
            lay.addWidget(btn)
        self.download_btn.clicked.connect(lambda: self.download_clicked.emit(self.item_id))
        self.folder_btn.clicked.connect(lambda: self.open_folder_clicked.emit(self.item_id))
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.item_id))

        self.update_from(item)

    def update_from(self, item: QueueItem):
        win = self.window()
        t = getattr(win, "theme", None) or THEMES["dark"]
        lang = getattr(win, "language", None) or "en"

        for btn, name, col in (
            (self.download_btn, "download", t["accent_text"]),
            (self.folder_btn,   "folder",   t["text2"]),
            (self.remove_btn,   "close",    t["danger"]),
        ):
            btn.setIcon(make_icon(name, col, 16))

        self.title_lbl.setText(item.title)
        icon_map = {
            QUEUE_STATUS_QUEUED:     ("●", t["dim"],     tr(lang, "status_queued")),
            QUEUE_STATUS_LOADING:    ("●", t["accent"],  tr(lang, "status_loading")),
            QUEUE_STATUS_READY:      ("●", t["success"], tr(lang, "status_ready")),
            QUEUE_STATUS_PROCESSING: ("●", t["accent"],  tr(lang, "status_processing")),
            QUEUE_STATUS_COMPLETE:   ("●", t["success"], tr(lang, "status_complete")),
            QUEUE_STATUS_FAILED:     ("●", t["danger"],  tr(lang, "status_failed")),
            QUEUE_STATUS_SKIPPED:    ("●", t["dim"],     tr(lang, "status_skipped")),
        }
        icon, color, label = icon_map.get(item.status, ("", t["dim"], ""))
        kind = "♪" if item.mode == "mp3" else "▶"
        raw_detail = item.error_msg if item.status == QUEUE_STATUS_FAILED else (
            item.channel if item.channel else item.url
        )
        detail = _clean_status_text(raw_detail)
        plat_label = PLATFORM_LABELS.get(getattr(item, "platform", ""), "")
        if plat_label:
            detail = f"{plat_label} • {detail}" if detail else plat_label
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
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText(kind)

        self.mini_progress.setVisible(item.status == QUEUE_STATUS_PROCESSING)

        self.download_btn.setEnabled(item.status not in (QUEUE_STATUS_PROCESSING,))
        self.remove_btn.setEnabled(item.status != QUEUE_STATUS_PROCESSING)
        self.folder_btn.setEnabled(item.status == QUEUE_STATUS_COMPLETE and bool(item.output_dir))
        self.download_btn.setToolTip(
            tr(lang, "tooltip_download_again") if item.status == QUEUE_STATUS_COMPLETE
            else tr(lang, "tooltip_download")
        )
        self.folder_btn.setToolTip(tr(lang, "tooltip_open_folder"))
        self.remove_btn.setToolTip(tr(lang, "tooltip_remove"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
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
        scaled = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
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


# ── Main window ────────────────────────────────────────────────────────────────

class YouTubeDownloader(QMainWindow):
    MAX_CONCURRENT_DOWNLOADS = 3

    def __init__(self):
        super().__init__()
        self.settings     = AppSettings()
        self.theme_name   = self.settings.get_theme()
        self.theme        = THEMES[self.theme_name]
        self.language     = self.settings.get_language()
        self.active_page  = PAGE_YOUTUBE
        self.workers      = {}
        self.info_worker  = None
        self._playlist_workers = []   # keep references so threads aren't GC'd
        self.queue_items  = {}
        self.row_widgets  = {}
        self.download_queue_ids = []

        self._build_ui()
        self._apply_style()
        self._reload_history()
        self._restore_saved_queue()
        self._refresh_tabs_and_list()

    def _t(self, key, **kwargs):
        return tr(self.language, key, **kwargs)

    def _quality_label(self, key):
        if key == "best4k":
            return self._t("quality_best")
        if key == "audio_only":
            return self._t("quality_audio_only")
        return key

    def _ts(self):
        return datetime.now().strftime("[%-I:%M:%S %p]") if sys.platform != "win32" \
               else datetime.now().strftime("[%I:%M:%S %p]")

    def _current_output_dir(self):
        mode = self.toggle.mode()
        if mode == "audio" or self.quality_combo.currentData() == "audio_only":
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
        self.setMinimumWidth(860)
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
        tb_lay.setContentsMargins(16, 12, 16, 12)
        tb_lay.setSpacing(10)

        self.paste_btn = QPushButton(self._t("paste_link"))
        self.paste_btn.setObjectName("pasteBtn")
        self.paste_btn.setFixedHeight(38)
        self.paste_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.paste_btn.setCursor(Qt.PointingHandCursor)
        self.paste_btn.clicked.connect(self._paste_from_clipboard)
        tb_lay.addWidget(self.paste_btn)

        self.toggle = ToggleGroup(self._t("video"), self._t("audio"))
        self.toggle.changed.connect(self._on_format_change)
        tb_lay.addWidget(self.toggle)

        self.quality_combo = QComboBox()
        self.quality_combo.setObjectName("qualityCombo")
        self.quality_combo.setFixedHeight(38)
        self.quality_combo.setFont(QFont("Segoe UI", 9))
        for key in QUALITY_KEYS:
            self.quality_combo.addItem(self._quality_label(key), key)
        self.quality_combo.setFixedWidth(150)
        self.quality_combo.currentIndexChanged.connect(self._on_quality_change)
        tb_lay.addWidget(self.quality_combo)

        self.sub_check = QCheckBox(self._t("subtitles"))
        self.sub_check.setObjectName("subCheck")
        self.sub_check.setFont(QFont("Segoe UI", 9))
        tb_lay.addWidget(self.sub_check)

        tb_lay.addStretch()

        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("themeBtn")
        self.theme_btn.setFixedSize(38, 38)
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip(self._t("theme_tooltip"))
        self.theme_btn.clicked.connect(self._toggle_theme)
        tb_lay.addWidget(self.theme_btn)

        self.header_settings_btn = QPushButton(self._t("settings"))
        self.header_settings_btn.setObjectName("headerSettingsBtn")
        self.header_settings_btn.setFixedHeight(38)
        self.header_settings_btn.setFont(QFont("Segoe UI", 10))
        self.header_settings_btn.setCursor(Qt.PointingHandCursor)
        self.header_settings_btn.clicked.connect(self._open_settings)
        tb_lay.addWidget(self.header_settings_btn)

        self.download_all_btn = QPushButton(self._t("download_all_ready"))
        self.download_all_btn.setObjectName("dlAllBtn")
        self.download_all_btn.setFixedHeight(38)
        self.download_all_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.download_all_btn.setCursor(Qt.PointingHandCursor)
        self.download_all_btn.clicked.connect(self._download_all_ready)
        tb_lay.addWidget(self.download_all_btn)

        main.addWidget(toolbar)

        # ── Platform page tabs (underline style) ──────────────────────────
        page_tabs_bar = QWidget()
        page_tabs_bar.setObjectName("pageTabsBar")
        page_tabs_lay = QHBoxLayout(page_tabs_bar)
        page_tabs_lay.setContentsMargins(12, 0, 12, 0)
        page_tabs_lay.setSpacing(4)

        self.page_buttons = {}
        for key in PAGE_KEYS:
            btn = QPushButton(_page_tab_text(key, 0))
            btn.setObjectName("pageTabActive" if key == self.active_page else "pageTabInactive")
            btn.setFixedHeight(42)
            btn.setFont(QFont("Segoe UI", 10, QFont.Bold if key == self.active_page else QFont.Normal))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._switch_page(k))
            page_tabs_lay.addWidget(btn)
            self.page_buttons[key] = btn
        page_tabs_lay.addStretch()
        main.addWidget(page_tabs_bar)

        # ── Filter tabs ───────────────────────────────────────────────────
        tabs_bar = QWidget()
        tabs_bar.setObjectName("tabsBar")
        tabs_lay = QHBoxLayout(tabs_bar)
        tabs_lay.setContentsMargins(16, 10, 16, 10)
        tabs_lay.setSpacing(6)

        self.filter_buttons = {}
        self.filter_mode = "all"
        for key, tr_key in [
            ("all", "tab_all"), ("ready", "tab_ready"), ("processing", "tab_processing"),
            ("failed", "tab_failed"), ("skipped", "tab_skipped"), ("complete", "tab_complete"),
        ]:
            btn = QPushButton(f"{self._t(tr_key)} (0)")
            btn.setObjectName("filterTabActive" if key == "all" else "filterTabInactive")
            btn.setFixedHeight(30)
            btn.setFont(QFont("Segoe UI", 9, QFont.Bold if key == "all" else QFont.Normal))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._set_filter(k))
            tabs_lay.addWidget(btn)
            self.filter_buttons[key] = btn
        tabs_lay.addStretch()
        main.addWidget(tabs_bar)

        # ── Split view: queue list + history panel ────────────────────────
        split = QWidget()
        split.setObjectName("splitView")
        split_lay = QHBoxLayout(split)
        split_lay.setContentsMargins(0, 0, 0, 0)
        split_lay.setSpacing(0)

        self.queue_scroll = QScrollArea()
        self.queue_scroll.setObjectName("queueScroll")
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setFrameShape(QFrame.NoFrame)
        self.queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        empty_hint_keys = {PAGE_YOUTUBE: "empty_hint_youtube", PAGE_META: "empty_hint_meta", PAGE_TIKTOK: "empty_hint_tiktok"}
        self.page_containers = {}
        for key in PAGE_KEYS:
            container = QWidget()
            container.setObjectName("queueContainer")
            container.setAttribute(Qt.WA_StyledBackground, True)
            list_lay = QVBoxLayout(container)
            list_lay.setContentsMargins(0, 0, 0, 0)
            list_lay.setSpacing(0)
            list_lay.addStretch()

            empty_hint = QLabel(self._t(empty_hint_keys[key]))
            empty_hint.setObjectName("emptyHint")
            empty_hint.setAlignment(Qt.AlignCenter)
            empty_hint.setFont(QFont("Segoe UI", 10))
            list_lay.insertWidget(0, empty_hint)

            self.page_containers[key] = (container, list_lay, empty_hint)

        self.queue_scroll.setWidget(self.page_containers[self.active_page][0])
        split_lay.addWidget(self.queue_scroll, stretch=1)

        self.history_panel = self._build_history_panel()
        self.history_panel.setVisible(False)
        split_lay.addWidget(self.history_panel)

        main.addWidget(split, stretch=1)

        # ── Bottom status bar ─────────────────────────────────────────────
        status_bar = QWidget()
        status_bar.setObjectName("statusBar")
        sb_lay = QHBoxLayout(status_bar)
        sb_lay.setContentsMargins(16, 8, 16, 8)

        self.ver_lbl = QLabel(self._t("version_label", v=APP_VERSION))
        self.ver_lbl.setObjectName("footer")
        self.ver_lbl.setFont(QFont("Segoe UI", 9))
        sb_lay.addWidget(self.ver_lbl)
        sb_lay.addStretch()

        self.history_link = QPushButton(self._t("history"))
        self.history_link.setObjectName("feedbackLink")
        self.history_link.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.history_link.setCursor(Qt.PointingHandCursor)
        self.history_link.setFlat(True)
        self.history_link.clicked.connect(self._toggle_history_panel)
        sb_lay.addWidget(self.history_link)

        main.addWidget(status_bar)

        saved_quality_key = self.settings.get_default_quality()
        idx = self.quality_combo.findData(saved_quality_key)
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)
        self.sub_check.setChecked(self.settings.get_subtitles())

        saved_format = self.settings.get_default_format()
        self.toggle.set_mode(saved_format)
        self._on_format_change(saved_format)

    # ── Style ────────────────────────────────────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet(build_main_qss(self.theme))
        self._refresh_icons()

    def _refresh_icons(self):
        """Vector icons are re-tinted whenever the theme changes."""
        t, sz = self.theme, QSize(16, 16)
        pairs = [
            (self.paste_btn,           "plus",     t["on_accent"]),
            (self.download_all_btn,    "download", t["on_accent"]),
            (self.header_settings_btn, "gear",     t["text2"]),
            (self.theme_btn,           "sun" if self.theme_name == "light" else "moon", t["text2"]),
            (self.history_link,        "clock",    t["accent_text"]),
        ]
        for btn, name, col in pairs:
            btn.setIcon(make_icon(name, col, 16))
            btn.setIconSize(sz)
        # Disabled "Download All" should look muted, not accent-coloured
        self.download_all_btn.setIcon(make_icon("download", t["on_accent"], 16))

    # ── Paste-link → fetch-info → queue flow ────────────────────────────────

    def _paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text() or ""
        urls = _VIDEO_URL_RE.findall(text)
        if not urls:
            QMessageBox.information(self, self._t("no_link_title"), self._t("no_link_text"))
            return
        added = 0
        expanding = 0
        landed_pages = set()
        for raw_u in urls:
            has_list, has_video = _youtube_list_info(raw_u)
            if has_list:
                # Pure playlist link -> always expand; video+list (e.g. a Mix) -> ask.
                choice = self._ask_playlist_choice() if has_video else "all"
                if choice == "cancel":
                    continue
                if choice == "all":
                    self._start_playlist_expand(_clean_url(raw_u, keep_list=True))
                    expanding += 1
                    continue
            u = _clean_url(raw_u)
            if not any(qi.url == u for qi in self.queue_items.values()):
                landed_pages.add(self._add_queue_item(u))
                added += 1
        if added == 0 and expanding == 0:
            self._flash_status(self._t("already_in_list"))
        elif added:
            elsewhere = [k for k in PAGE_KEYS if k in landed_pages and k != self.active_page]
            if elsewhere:
                names = ", ".join(PAGE_NAMES[k] for k in elsewhere)
                self._flash_status(self._t("added_to_other_page", pages=names))

    # ── Playlist / Mix support ───────────────────────────────────────────

    def _ask_playlist_choice(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(self._t("playlist_title"))
        box.setText(self._t("playlist_text", n=MAX_PLAYLIST_ITEMS))
        all_btn = box.addButton(self._t("playlist_add_all"), QMessageBox.AcceptRole)
        one_btn = box.addButton(self._t("playlist_add_one"), QMessageBox.NoRole)
        box.addButton(self._t("btn_cancel"), QMessageBox.RejectRole)
        box.setDefaultButton(all_btn)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is all_btn:
            return "all"
        if clicked is one_btn:
            return "one"
        return "cancel"

    def _start_playlist_expand(self, url):
        self._flash_status(self._t("playlist_loading"), 6000)
        worker = PlaylistWorker(url)
        worker.entries_ready.connect(lambda entries, w=worker: self._on_playlist_ready(entries, w))
        worker.error.connect(lambda msg, w=worker: self._on_playlist_error(msg, w))
        self._playlist_workers.append(worker)
        worker.start()

    def _release_playlist_worker(self, worker):
        if worker in self._playlist_workers:
            self._playlist_workers.remove(worker)

    def _on_playlist_ready(self, entries, worker):
        self._release_playlist_worker(worker)
        self._switch_page(PAGE_YOUTUBE)
        added = 0
        for e in entries:
            u = _clean_url(e["url"])
            if any(qi.url == u for qi in self.queue_items.values()):
                continue
            # Stagger the per-video info lookups so 50 requests don't fire at once
            self._add_queue_item(u, title=e["title"], channel=e["channel"], delay_ms=added * 250)
            added += 1
        if added:
            self._flash_status(self._t("playlist_added", n=added), 4000)
        else:
            self._flash_status(self._t("playlist_nothing_new"), 4000)

    def _on_playlist_error(self, msg, worker):
        self._release_playlist_worker(worker)
        QMessageBox.warning(self, self._t("playlist_failed_title"), _clean_status_text(msg))

    def _add_queue_item(self, url, title=None, channel="", delay_ms=0):
        item = QueueItem(url)
        if title:
            item.title = title
        item.channel = channel
        page_key = PLATFORM_TO_PAGE.get(item.platform, PAGE_YOUTUBE)
        self.queue_items[item.id] = item
        row = QueueRowWidget(item)
        row.download_clicked.connect(self._download_single)
        row.remove_clicked.connect(self._remove_item)
        row.open_folder_clicked.connect(self._open_item_folder)
        self.row_widgets[item.id] = row
        container, list_lay, empty_hint = self.page_containers[page_key]
        empty_hint.setVisible(False)
        list_lay.insertWidget(list_lay.count() - 1, row)
        self._refresh_tabs_and_list()
        if delay_ms:
            self._update_row(item.id)
            QTimer.singleShot(delay_ms, lambda iid=item.id: self._fetch_item_info(iid))
        else:
            self._fetch_item_info(item.id)   # also re-renders the row with the live theme
        return page_key

    def _fetch_item_info(self, item_id):
        item = self.queue_items.get(item_id)
        if not item:
            return
        item.status = QUEUE_STATUS_LOADING
        self._update_row(item_id)

        worker = InfoWorker(item.url)
        worker.info_ready.connect(lambda info, iid=item_id: self._on_item_info_ready(iid, info))
        worker.error.connect(lambda msg, iid=item_id: self._on_item_info_error(iid, msg))
        item._info_worker = worker
        worker.start()

    def _on_item_info_ready(self, item_id, info):
        item = self.queue_items.get(item_id)
        if not item:
            return
        item.title         = info["title"]
        item.channel       = info["channel"]
        item.duration      = info["duration"]
        item.thumbnail_url = info.get("thumbnail") or ""
        item.status        = QUEUE_STATUS_READY
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
            item._thumb_worker = worker
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
            return
        row = self.row_widgets.pop(item_id, None)
        if row and item:
            page_key = PLATFORM_TO_PAGE.get(item.platform, PAGE_YOUTUBE)
            self.page_containers[page_key][1].removeWidget(row)
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
        if not path or not os.path.exists(path):
            QMessageBox.information(self, self._t("folder_not_found_title"), self._t("folder_not_found_text"))
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(self, self._t("couldnt_open_folder_title"), self._t("couldnt_open_folder_text", e=e))

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

    # ── Platform pages ───────────────────────────────────────────────────

    def _switch_page(self, page_key):
        if page_key not in PAGE_KEYS or page_key == self.active_page:
            return
        self.active_page = page_key
        for k, btn in self.page_buttons.items():
            btn.setObjectName("pageTabActive" if k == page_key else "pageTabInactive")
            btn.setFont(QFont("Segoe UI", 10, QFont.Bold if k == page_key else QFont.Normal))
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.queue_scroll.takeWidget()
        self.queue_scroll.setWidget(self.page_containers[page_key][0])
        self._refresh_tabs_and_list()

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
        page_totals = {k: 0 for k in PAGE_KEYS}
        for item in self.queue_items.values():
            page_key = PLATFORM_TO_PAGE.get(item.platform, PAGE_YOUTUBE)
            page_totals[page_key] += 1
        for key, btn in self.page_buttons.items():
            btn.setText(_page_tab_text(key, page_totals[key]))

        active = self.active_page
        counts = {"all": 0, "ready": 0, "processing": 0, "failed": 0, "skipped": 0, "complete": 0}
        for item in self.queue_items.values():
            if PLATFORM_TO_PAGE.get(item.platform, PAGE_YOUTUBE) != active:
                continue
            counts["all"] += 1
            if item.status in counts:
                counts[item.status] += 1

        tr_keys = {
            "all": "tab_all", "ready": "tab_ready", "processing": "tab_processing",
            "failed": "tab_failed", "skipped": "tab_skipped", "complete": "tab_complete",
        }
        for key, btn in self.filter_buttons.items():
            btn.setText(f"{self._t(tr_keys[key])} ({counts[key]})")

        for item_id, row in self.row_widgets.items():
            item = self.queue_items[item_id]
            if PLATFORM_TO_PAGE.get(item.platform, PAGE_YOUTUBE) != active:
                continue
            row.setVisible(self._status_matches_filter(item.status))
        self.page_containers[active][2].setVisible(page_totals[active] == 0)

        ready_count = counts["ready"]
        self.download_all_btn.setText(f"{self._t('download_all_ready')} ({ready_count})")
        self.download_all_btn.setEnabled(ready_count > 0)

        self._persist_queue()

    def _flash_status(self, msg, ms=2500):
        self.history_link.setText(msg)
        QTimer.singleShot(ms, lambda: self.history_link.setText(
            self._t("hide_history") if self.history_panel.isVisible() else self._t("history")))

    # ── Format / quality controls ───────────────────────────────────────

    def _on_format_change(self, mode):
        self.settings.set_default_format(mode)
        if mode == "audio":
            idx = self.quality_combo.findData("audio_only")
            if idx >= 0:
                self.quality_combo.setCurrentIndex(idx)
            self.quality_combo.setEnabled(False)
        else:
            self.quality_combo.setEnabled(True)
            if self.quality_combo.currentData() == "audio_only":
                self.quality_combo.setCurrentIndex(0)

    def _on_quality_change(self, index):
        key = self.quality_combo.itemData(index)
        if key:
            self.settings.set_default_quality(key)

    # ── Download (single item / all ready) ──────────────────────────────

    def _resolve_mode_quality(self):
        fmt = self.toggle.mode()
        key = self.quality_combo.currentData() or "best4k"
        mode = "mp3" if (fmt == "audio" or key == "audio_only") else "mp4"
        quality = QUALITY_TO_YTDLP.get(key, "best")
        return mode, quality, key

    def _download_single(self, item_id):
        item = self.queue_items.get(item_id)
        if not item or item.status == QUEUE_STATUS_PROCESSING:
            return
        if item_id not in self.download_queue_ids:
            self.download_queue_ids.append(item_id)
        self._fill_download_slots()

    def _download_all_ready(self):
        ready_ids = [
            qi.id for qi in self.queue_items.values()
            if qi.status == QUEUE_STATUS_READY
            and PLATFORM_TO_PAGE.get(qi.platform, PAGE_YOUTUBE) == self.active_page
        ]
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

        existing = self._existing_matches(output_dir, item.title)
        if existing and item.status != QUEUE_STATUS_COMPLETE:
            file_list = "\n".join(f"• {f}" for f in existing[:5])
            more = "\n" + self._t("and_more", n=len(existing) - 5) if len(existing) > 5 else ""
            box = QMessageBox(self)
            box.setWindowTitle(self._t("already_downloaded_title"))
            box.setIcon(QMessageBox.Question)
            box.setText(self._t("already_downloaded_audio_text" if mode == "mp3" else "already_downloaded_video_text"))
            box.setInformativeText(f"{file_list}{more}\n\n{self._t('confirm_download_again')}")
            box.addButton(self._t("btn_download_again"), QMessageBox.YesRole)
            no_btn = box.addButton(self._t("btn_skip"), QMessageBox.NoRole)
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

    def _progress_qss(self, chunk_color):
        t = self.theme
        return f"""
            QProgressBar {{
                background-color: {t['progress_bg']};
                border: 1px solid {t['progress_border']};
                border-radius: 9px;
                color: {t['text']};
                text-align: center;
                font-weight: bold;
                font-size: 10px;
            }}
            QProgressBar::chunk {{
                background-color: {chunk_color};
                border-radius: 8px;
            }}
        """

    def _on_progress(self, item_id, pct, label):
        row = self.row_widgets.get(item_id)
        if not row:
            return
        if row.mini_progress.maximum() == 0:
            row.mini_progress.setRange(0, 100)

        pct_clamped = max(0.0, min(100.0, pct))
        row.mini_progress.setValue(int(pct_clamped))
        row.mini_progress.setFormat(f"{pct_clamped:.1f}%")

        # Smooth red -> green ramp
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
        row.mini_progress.setStyleSheet(self._progress_qss(colors[index]))

    def _on_processing(self, item_id):
        row = self.row_widgets.get(item_id)
        if not row:
            return
        row.mini_progress.setRange(0, 0)
        row.mini_progress.setFormat(self._t("progress_processing"))
        row.mini_progress.setStyleSheet(self._progress_qss(self.theme['accent']))

    def _on_finished(self, item_id, msg):
        row = self.row_widgets.get(item_id)
        if row:
            row.mini_progress.setRange(0, 100)
            row.mini_progress.setValue(100)
            row.mini_progress.setFormat("100%")
        item = self.queue_items.get(item_id)
        if item:
            item.status = QUEUE_STATUS_COMPLETE
            self._update_row(item_id)
            self.settings.add_history_entry({
                "title": item.title,
                "url": item.url,
                "mode": item.mode,
                "quality": item.quality,
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
            row.mini_progress.setRange(0, 100)
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

    # ── Theme ─────────────────────────────────────────────────────────────

    def _apply_theme(self, name):
        if name not in THEMES:
            return
        self.theme_name = name
        self.theme = THEMES[name]
        self.settings.set_theme(name)
        self._apply_style()   # also re-tints the toolbar icons
        for item_id in list(self.queue_items.keys()):
            self._update_row(item_id)

    def _toggle_theme(self):
        self._apply_theme("light" if self.theme_name == "dark" else "dark")

    # ── Language ──────────────────────────────────────────────────────────

    def _apply_language(self, name):
        if name not in TRANSLATIONS:
            return
        self.language = name
        self.settings.set_language(name)
        self._retranslate_ui()

    def _retranslate_ui(self):
        self.paste_btn.setText(self._t("paste_link"))
        self.ver_lbl.setText(self._t("version_label", v=APP_VERSION))
        self.toggle.set_labels(self._t("video"), self._t("audio"))
        self.sub_check.setText(self._t("subtitles"))
        self.theme_btn.setToolTip(self._t("theme_tooltip"))
        self.header_settings_btn.setText(self._t("settings"))
        empty_hint_keys = {PAGE_YOUTUBE: "empty_hint_youtube", PAGE_META: "empty_hint_meta", PAGE_TIKTOK: "empty_hint_tiktok"}
        for key, (_, _, empty_hint) in self.page_containers.items():
            empty_hint.setText(self._t(empty_hint_keys[key]))

        current_key = self.quality_combo.currentData()
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        for key in QUALITY_KEYS:
            self.quality_combo.addItem(self._quality_label(key), key)
        idx = self.quality_combo.findData(current_key)
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)
        self.quality_combo.blockSignals(False)

        self.history_panel_title_lbl.setText(self._t("history_title"))
        self.history_clear_btn.setText(self._t("history_clear"))
        self.history_close_btn.setText(self._t("history_close"))
        showing = self.history_panel.isVisible()
        self.history_link.setText(self._t("hide_history") if showing else self._t("history"))
        if showing:
            self._refresh_history_list()

        self._refresh_tabs_and_list()
        for item_id in list(self.queue_items.keys()):
            self._update_row(item_id)

    # ── Settings / history ───────────────────────────────────────────────

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self.theme, self.language, self)
        dlg.exec_()

    def _build_history_panel(self):
        panel = QWidget()
        panel.setObjectName("historyPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setFixedWidth(330)

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(10)

        header_row = QHBoxLayout()
        self.history_panel_title_lbl = QLabel(self._t("history_title"))
        self.history_panel_title_lbl.setObjectName("historyTitle")
        self.history_panel_title_lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        header_row.addWidget(self.history_panel_title_lbl)
        header_row.addStretch()
        panel_close_btn = QPushButton("✕")
        panel_close_btn.setObjectName("historyPanelCloseBtn")
        panel_close_btn.setFixedSize(26, 26)
        panel_close_btn.setCursor(Qt.PointingHandCursor)
        panel_close_btn.clicked.connect(self._toggle_history_panel)
        header_row.addWidget(panel_close_btn)
        lay.addLayout(header_row)

        self.history_list = QListWidget()
        self.history_list.setObjectName("historyList")
        self.history_list.itemDoubleClicked.connect(self._open_history_item_folder)
        lay.addWidget(self.history_list, stretch=1)

        btn_row = QHBoxLayout()
        self.history_clear_btn = QPushButton(self._t("history_clear"))
        self.history_clear_btn.setObjectName("historyClearBtn")
        self.history_clear_btn.setFixedHeight(34)
        self.history_clear_btn.setCursor(Qt.PointingHandCursor)
        self.history_clear_btn.clicked.connect(self._clear_history)
        self.history_close_btn = QPushButton(self._t("history_close"))
        self.history_close_btn.setObjectName("historyCloseBtn")
        self.history_close_btn.setFixedHeight(34)
        self.history_close_btn.setCursor(Qt.PointingHandCursor)
        self.history_close_btn.clicked.connect(self._toggle_history_panel)
        btn_row.addWidget(self.history_clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.history_close_btn)
        lay.addLayout(btn_row)

        return panel

    def _toggle_history_panel(self):
        showing = not self.history_panel.isVisible()
        if showing:
            self._refresh_history_list()
        self.history_panel.setVisible(showing)
        self.history_link.setText(self._t("hide_history") if showing else self._t("history"))

    def _history_type_label(self, entry):
        mode = entry.get("mode")
        if not mode:
            return entry.get("type", "")
        if mode == "mp3":
            return self._t("history_type_audio")
        q = str(entry.get("quality", "best"))
        q_label = self._t("quality_best") if q == "best" else f"{q}p"
        return f"{self._t('history_type_video')} ({q_label})"

    def _refresh_history_list(self):
        self.history_list.clear()
        history = self.settings.load_history()
        if not history:
            item = QListWidgetItem(self._t("history_empty"))
            item.setFlags(Qt.NoItemFlags)
            self.history_list.addItem(item)
            return
        for entry in history:
            is_audio = entry.get("mode") == "mp3" or (
                not entry.get("mode") and "Audio" in entry.get("type", "")
            )
            kind_icon = "♪" if is_audio else "▶"
            folder = entry.get("folder", "")
            display_text = (
                f"{kind_icon}  {entry.get('title', 'Unknown')}\n"
                f"     {self._history_type_label(entry)} • {entry.get('timestamp', '')}\n"
                f"     {folder}"
            )
            list_item = QListWidgetItem(display_text)
            list_item.setData(Qt.UserRole, folder)
            list_item.setToolTip(self._t("history_tooltip_open"))
            self.history_list.addItem(list_item)

    def _open_history_item_folder(self, list_item):
        folder = list_item.data(Qt.UserRole)
        if folder:
            self._open_in_explorer(folder)

    def _clear_history(self):
        self.settings.clear_history()
        self._refresh_history_list()

    def _reload_history(self):
        pass


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    win = YouTubeDownloader()
    win.show()
    sys.exit(app.exec_())