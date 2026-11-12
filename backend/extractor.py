import os
import socket
import ipaddress
from urllib.parse import urlparse
from yt_dlp import YoutubeDL

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def validate_url(url):
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid URL")

    host = parsed.hostname.lower()

    if host == "localhost" or host.endswith((".local", ".internal")):
        raise ValueError("Local addresses are not allowed")

    try:
        addresses = socket.getaddrinfo(host, None)
        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                raise ValueError("Private address blocked")
    except socket.gaierror:
        raise ValueError("Unable to resolve website")

    return url


def get_info(url):
    validate_url(url)

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "extractor_retries": 5,
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = []

    for f in info.get("formats", []):
        if f.get("url") and (
            f.get("height") or f.get("acodec") != "none"
        ):
            formats.append({
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "height": f.get("height"),
                "filesize": f.get("filesize") or f.get("filesize_approx"),
                "note": f.get("format_note"),
                "has_audio": f.get("acodec") != "none"
            })

    return {
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "formats": formats[:60]
    }


def download_media(url, format_id, audio=False):
    validate_url(url)

    options = {
        "outtmpl": os.path.join(
            DOWNLOAD_DIR,
            "%(extractor)s_%(id)s.%(ext)s"
        ),
        "format": "bestaudio/best" if audio else (format_id or "best"),
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "overwrites": True,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 5,
        "extractor_retries": 5,
        "socket_timeout": 30,
        "continuedl": True,
        "nopart": False,
        "http_chunk_size": 10485760,
        "max_filesize": 500 * 1024 * 1024,
    }

    if audio:
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192"
        }]

    with YoutubeDL(options) as ydl:
        ydl.download([url])

    return True
