# 🎬 TheHours YT Downloader

A simple and powerful YouTube Video & Audio Downloader built with Python.

This application allows users to download YouTube videos or extract audio files easily with a simple interface. It supports different video qualities and provides a fast downloading experience.

## ✨ Features

- 🎥 Download YouTube videos
- 🎵 Extract audio from YouTube videos
- 📁 Choose download location
- ⚡ Fast download speed
- 🖥️ Desktop application support
- 🖼️ Custom application icon
- 💻 Command-line support
- 🔒 Uses local cookies authentication (optional)

## 🛠️ Built With

- Python 3.x
- yt-dlp
- PyInstaller
- Tkinter (GUI)

## 📋 Requirements

Before running the project, make sure you have:

- Python 3.10+
- pip package manager

Install required libraries:

```bash
pip install -r requirements.txt
```

## 🚀 Installation

### 1. Clone repository

```bash
git clone https://github.com/mornlyhour5/YouTube-Download-Video-Audio.git
```

### 2. Enter project folder

```bash
cd YouTube-Download-Video-Audio
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run application

GUI version:

```bash
python youtube_downloader.py
```

CLI version:

```bash
python yt_download_cli.py
```

## 📦 Build Desktop Application

This project uses PyInstaller to create a Windows `.exe` application.

Install PyInstaller:

```bash
pip install pyinstaller
```

Build:

```bash
pyinstaller "TheHours YT Downloader.spec"
```

The generated application will be available inside:

```
dist/
```

## 🍪 Cookies Authentication (Optional)

Some YouTube videos may require authentication.

You can provide your own browser cookies file:

```
cookies.txt
```

⚠️ Do not upload your cookies file to GitHub.

Cookies contain private authentication information.

## 📂 Project Structure

```
YouTube-Download-Video-Audio
│
├── youtube_downloader.py       # GUI application
├── yt_download_cli.py          # Command line downloader
├── backup.py                   # Backup utility
├── requirements.txt            # Python dependencies
├── icon.ico                    # Application icon
├── TheHours YT Downloader.spec # PyInstaller configuration
└── README.md
```

## 📸 Screenshot

(Add application screenshots here)

## 🤝 Contributing

Contributions are welcome.

If you want to improve this project:

1. Fork this repository
2. Create a new branch

```bash
git checkout -b feature/new-feature
```

3. Commit changes

```bash
git commit -m "Add new feature"
```

4. Push branch

```bash
git push origin feature/new-feature
```

5. Create a Pull Request

## 📄 License

This project is for educational purposes.

## 👨‍💻 Author

**Morn LyHour**

GitHub:
https://github.com/mornlyhour5
