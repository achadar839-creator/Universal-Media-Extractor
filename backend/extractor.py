import os
import uuid
import socket
import ipaddress
import requests
from urllib.parse import urlparse
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

DOWNLOAD_DIR = "downloads"
COOKIE_FILE = os.path.abspath("private/youtube-cookies.txt")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def is_tor_running(host="127.0.0.1", port=9050):
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def get_proxy_url():
    custom = os.getenv("PROXY_URL")
    if custom:
        return custom
    if is_tor_running():
        return "socks5h://127.0.0.1:9050"
    return None


def is_tiktok_url(url):
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com", "douyin.com"))


def validate_url(url):
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid URL")

    host = parsed.hostname.lower()

    if host == "localhost" or host.endswith((".local", ".internal")):
        raise ValueError("Local address blocked")

    if is_tiktok_url(url):
        return url

    try:
        addresses = socket.getaddrinfo(host, None)
        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                raise ValueError("Private address blocked")
    except socket.gaierror:
        if not get_proxy_url():
            raise ValueError("Unable to resolve website")

    return url


def fetch_tiktok_via_api(url):
    """TikTok के Tor ब्लॉक से बचने के लिए डायरेक्ट हाई-स्पीड एक्सट्रैक्टर"""
    api_url = "https://www.tikwm.com/api/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.post(api_url, data={"url": url, "hd": 1}, headers=headers, timeout=20)
        data = resp.json()
    except Exception:
        proxy = get_proxy_url()
        if not proxy:
            raise ValueError("Unable to connect to TikTok extractor service")
        resp = requests.post(
            api_url,
            data={"url": url, "hd": 1},
            headers=headers,
            proxies={"http": proxy, "https": proxy},
            timeout=25
        )
        data = resp.json()

    if data.get("code") != 0 or not data.get("data"):
        raise ValueError(data.get("msg") or "Unable to fetch TikTok video")
    return data["data"]


def base_options():
    options = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "extractor_retries": 5,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "js_runtimes": {"deno": {}},
        "remote_components": ["ejs:github"],
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
    }

    custom_proxy = os.getenv("PROXY_URL")
    if custom_proxy:
        options["proxy"] = custom_proxy

    if os.path.isfile(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        options["cookiefile"] = COOKIE_FILE

    return options


def extract_with_fallback(url, options, download=False):
    """बाकी सभी वेबसाइट्स के लिए: पहले डायरेक्ट चलाएगा, ब्लॉक होने पर Tor इस्तेमाल करेगा"""
    try:
        with YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=download)
    except DownloadError as e:
        err_msg = str(e).lower()
        proxy = get_proxy_url()
        if proxy and not options.get("proxy") and any(k in err_msg for k in ("timed out", "timeout", "connection", "unreachable", "reset by peer")):
            options["proxy"] = proxy
            with YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=download)
        raise


def get_info(url):
    validate_url(url)

    if is_tiktok_url(url):
        tk = fetch_tiktok_via_api(url)
        formats = []
        if tk.get("hdplay"):
            formats.append({
                "format_id": "hd",
                "ext": "mp4",
                "height": 1080,
                "filesize": tk.get("hd_size"),
                "note": "HD (No Watermark)",
                "has_audio": True,
            })
        if tk.get("play"):
            formats.append({
                "format_id": "sd",
                "ext": "mp4",
                "height": 720,
                "filesize": tk.get("size"),
                "note": "Standard (No Watermark)",
                "has_audio": True,
            })
        if tk.get("music"):
            formats.append({
                "format_id": "audio",
                "ext": "mp3",
                "height": None,
                "filesize": None,
                "note": "Audio Only (MP3)",
                "has_audio": True,
            })
        return {
            "type": "video",
            "title": tk.get("title") or f"TikTok_{tk.get('id', 'video')}",
            "thumbnail": tk.get("cover"),
            "duration": tk.get("duration"),
            "uploader": (tk.get("author") or {}).get("nickname") or "TikTok Creator",
            "formats": formats,
        }

    options = base_options()
    options["noplaylist"] = False
    options["extract_flat"] = "in_playlist"

    info = extract_with_fallback(url, options, download=False)

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
    unique_prefix = uuid.uuid4().hex[:8]

    if is_tiktok_url(url):
        tk = fetch_tiktok_via_api(url)
        vid_id = tk.get("id") or "video"

        if audio or format_id == "audio":
            media_url = tk.get("music") or tk.get("play")
            ext = "mp3"
        elif format_id == "hd" and tk.get("hdplay"):
            media_url = tk.get("hdplay")
            ext = "mp4"
        else:
            media_url = tk.get("play") or tk.get("hdplay")
            ext = "mp4"

        if not media_url:
            raise ValueError("Direct media stream not found for this TikTok")

        filepath = os.path.join(DOWNLOAD_DIR, f"{unique_prefix}_TikTok_{vid_id}.{ext}")
        if media_url.startswith("/"):
            media_url = "https://www.tikwm.com" + media_url
        try:
            r = requests.get(media_url, stream=True, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
            r.raise_for_status()
        except Exception:
            proxy = get_proxy_url()
            r = requests.get(media_url, stream=True, headers={"User-Agent": "Mozilla/5.0"}, proxies={"http": proxy, "https": proxy} if proxy else None, timeout=60)
            r.raise_for_status()
        with r:
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        return filepath

    if audio:
        selected_format = "bestaudio/best"
    else:
        selected_format = format_id or "best"
        if selected_format != "best":
            check_options = base_options()
            check_options["noplaylist"] = True
            info = extract_with_fallback(url, check_options, download=False)

            selected = next(
                (
                    f for f in info.get("formats", [])
                    if str(f.get("format_id")) == str(selected_format)
                ),
                None,
            )

            if selected and selected.get("acodec") == "none":
                selected_format = f"{selected_format}+bestaudio/best"
        else:
            selected_format = "bestvideo+bestaudio/best"

    options = base_options()
    options.update({
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{unique_prefix}_%(extractor)s_%(id)s.%(ext)s"),
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

    info = extract_with_fallback(url, options, download=True)

    with YoutubeDL(options) as ydl:
        filepath = ydl.prepare_filename(info)

    if audio:
        filepath = os.path.splitext(filepath)[0] + ".mp3"
    elif not os.path.isfile(filepath):
        mp4_path = os.path.splitext(filepath)[0] + ".mp4"
        if os.path.isfile(mp4_path):
            filepath = mp4_path

    if not os.path.isfile(filepath):
        for fname in os.listdir(DOWNLOAD_DIR):
            if fname.startswith(unique_prefix):
                filepath = os.path.join(DOWNLOAD_DIR, fname)
                break

    if not os.path.isfile(filepath):
        raise FileNotFoundError("Downloaded file could not be located")

    return filepath
