#!/usr/bin/env python3
"""
YouTube Downloader CLI
Usage:
  python yt_download_cli.py <URL> [--mp3] [--quality 720] [--out ./downloads]
"""

import argparse
import os
import sys
import yt_dlp


def progress_hook(d):
    if d["status"] == "downloading":
        pct   = d.get("_percent_str", "?").strip()
        speed = d.get("_speed_str",   "").strip()
        eta   = d.get("_eta_str",     "").strip()
        print(f"\r  {pct:>7}  {speed:>12}  ETA {eta}   ", end="", flush=True)
    elif d["status"] == "finished":
        print(f"\r  Processing…{' ' * 40}")


def download(url, mode="mp4", quality="best", output_dir="."):
    os.makedirs(output_dir, exist_ok=True)
    outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

    if mode == "mp3":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "progress_hooks": [progress_hook],
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    else:
        if quality == "best":
            fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        else:
            fmt = (f"bestvideo[height<={quality}][ext=mp4]+"
                   f"bestaudio[ext=m4a]/best[height<={quality}][ext=mp4]/best")
        ydl_opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "progress_hooks": [progress_hook],
            "merge_output_format": "mp4",
        }

    label = "MP3 audio" if mode == "mp3" else f"MP4 ({quality})"
    print(f"\n▶ Downloading as {label}")
    print(f"  URL   : {url}")
    print(f"  Saving: {os.path.abspath(output_dir)}\n")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info  = ydl.extract_info(url, download=True)
        title = info.get("title", "video")

    print(f"\n✓ Done: {title}")
    print(f"  Saved to: {os.path.abspath(output_dir)}")


def main():
    parser = argparse.ArgumentParser(description="YouTube Downloader (MP4 / MP3)")
    parser.add_argument("url",                    help="YouTube video URL")
    parser.add_argument("--mp3",  action="store_true", help="Extract audio as MP3")
    parser.add_argument("--quality", default="best",
                        choices=["best", "1080", "720", "480", "360"],
                        help="Video quality (MP4 only, default: best)")
    parser.add_argument("--out",  default="./downloads",
                        help="Output directory (default: ./downloads)")
    args = parser.parse_args()

    mode = "mp3" if args.mp3 else "mp4"
    download(args.url, mode=mode, quality=args.quality, output_dir=args.out)


if __name__ == "__main__":
    main()
