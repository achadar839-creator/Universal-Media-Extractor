import os
import socket
import ipaddress
from urllib.parse import urlparse
from yt_dlp import YoutubeDL

DOWNLOAD_DIR = "downloads"
COOKIE_FILE = os.path.abspath("private/youtube-cookies.txt")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def validate_url(url):
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid URL")

    host = parsed.hostname.lower()

    if host == "localhost" or host.endswith((".local", ".internal")):
        raise ValueError("Local address blocked")

    try:
        addresses = socket.getaddrinfo(host, None)

        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                raise ValueError("Private address blocked")

    except socket.gaierror:
        raise ValueError("Unable to resolve website")

    return url


def base_options():
    options = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "extractor_retries": 5,
        "js_runtimes": {"deno": {}},
        "remote_components": ["ejs:github"],
    }

    if os.path.isfile(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        options["cookiefile"] = COOKIE_FILE

    return options


def get_info(url):
    validate_url(url)

    options = base_options()
    options["noplaylist"] = False
    options["extract_flat"] = "in_playlist"

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") in ("playlist", "multi_video") or info.get("entries"):
        entries = []

        for entry in info.get("entries") or []:
            if not entry:
                continue

            video_url = entry.get("webpage_url") or entry.get("url") or ""

            if video_url and not video_url.startswith(("http://", "https://")):
                video_url = "https://www.youtube.com/watch?v=" + video_url

            entries.append({
                "id": entry.get("id"),
                "title": entry.get("title") or "Untitled",
                "url": video_url,
                "thumbnail": entry.get("thumbnail"),
                "duration": entry.get("duration"),
            })

        return {
            "type": "playlist",
            "title": info.get("title") or "Playlist",
            "uploader": info.get("uploader"),
            "entries": entries,
            "count": len(entries),
        }

    formats = []

    for f in info.get("formats", []):
        if f.get("url") and (f.get("height") or f.get("acodec") != "none"):
            formats.append({
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "height": f.get("height"),
                "filesize": f.get("filesize") or f.get("filesize_approx"),
                "note": f.get("format_note"),
                "has_audio": f.get("acodec") != "none",
            })

    return {
        "type": "video",
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "formats": formats[:60],
    }


def download_media(url, format_id="best", audio=False):
    validate_url(url)

    if audio:
        selected_format = "bestaudio/best"
    else:
        selected_format = format_id or "best"

        check_options = base_options()
        check_options["noplaylist"] = True

        with YoutubeDL(check_options) as ydl:
            info = ydl.extract_info(url, download=False)

        selected = next(
            (
                f for f in info.get("formats", [])
                if str(f.get("format_id")) == str(selected_format)
            ),
            None,
        )

        if selected and selected.get("acodec") == "none":
            selected_format = f"{selected_format}+bestaudio/best"

    options = base_options()
    options.update({
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(extractor)s_%(id)s.%(ext)s"),
        "format": selected_format,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "overwrites": True,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 5,
        "socket_timeout": 30,
        "continuedl": True,
        "nopart": False,
        "merge_output_format": "mp4",
        "max_filesize": 500 * 1024 * 1024,
    })

    if audio:
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    with YoutubeDL(options) as ydl:
        ydl.download([url])

    return True
