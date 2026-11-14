import os
import re
import time
import shutil
import uuid
import socket
import ipaddress
import requests
from urllib.parse import urlparse
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

if os.path.isfile("/etc/secrets/youtube-cookies.txt"):
    with open("/etc/secrets/youtube-cookies.txt", "r", encoding="utf-8", errors="ignore") as src, open("/tmp/youtube-cookies.txt", "w", encoding="utf-8") as dst:
        for line in src:
            s = line.strip()
            if not s or s.startswith("#"):
                dst.write(line)
            elif "\t" not in s and len(s.split()) >= 7:
                parts = s.split(None, 6)
                dst.write("\t".join(parts) + "\n")
            else:
                dst.write(line)
    COOKIE_FILE = "/tmp/youtube-cookies.txt"
else:
    COOKIE_FILE = os.path.abspath("private/youtube-cookies.txt")


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


def is_youtube_url(url):
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ("youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com"))


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
    """TikWM API with retries and yt-dlp fallback."""
    api_url = "https://www.tikwm.com/api/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://www.tikwm.com/",
    }

    last_error = None
    for attempt in range(3):
        try:
            response = requests.post(
                api_url,
                data={"url": url, "hd": 1},
                headers=headers,
                timeout=(10, 45),
            )
            response.raise_for_status()
            result = response.json()
            if result.get("code") == 0 and result.get("data"):
                return result["data"]
            last_error = result.get("msg") or "TikWM returned no video data"
        except Exception as exc:
            last_error = str(exc)
        if attempt < 2:
            time.sleep(2)

    try:
        opts = base_options()
        opts.update({"noplaylist": True, "format": "best"})
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = [
            f for f in info.get("formats", [])
            if f.get("url") and f.get("vcodec") != "none"
        ]
        formats.sort(key=lambda f: f.get("height") or 0, reverse=True)
        best = formats[0] if formats else {}
        sd = formats[-1] if len(formats) > 1 else best
        audio = next(
            (f for f in info.get("formats", [])
             if f.get("url") and f.get("vcodec") == "none"
             and f.get("acodec") != "none"),
            {}
        )
        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "cover": info.get("thumbnail"),
            "duration": info.get("duration"),
            "author": {"nickname": info.get("uploader") or "TikTok Creator"},
            "hdplay": best.get("url") or info.get("url"),
            "play": sd.get("url") or best.get("url") or info.get("url"),
            "music": audio.get("url"),
            "_fallback_formats": formats,
        }
    except Exception as fallback_error:
        raise ValueError(
            f"TikTok extraction failed. TikWM: {last_error}. "
            f"yt-dlp fallback: {fallback_error}"
        )


def fetch_youtube_via_public_api(url):
    """Public Piped API fallback when cloud IP is blocked by YouTube."""
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise ValueError("Invalid YouTube video ID")
    vid_id = m.group(1)
    instances = [
        f"https://pipedapi.kavin.rocks/streams/{vid_id}",
        f"https://pipedapi.tokhmi.xyz/streams/{vid_id}",
        f"https://pipedapi.moomoo.me/streams/{vid_id}",
        f"https://pipedapi.syncpundit.io/streams/{vid_id}",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for api in instances:
        try:
            r = requests.get(api, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if data.get("videoStreams") or data.get("audioStreams"):
                    formats = []
                    for idx, vs in enumerate(data.get("videoStreams", [])):
                        if not vs.get("url"):
                            continue
                        height = None
                        q = str(vs.get("quality") or "")
                        hm = re.search(r"(\d+)p", q)
                        if hm:
                            height = int(hm.group(1))
                        formats.append({
                            "format_id": f"piped_v_{idx}_{height or 0}",
                            "url": vs.get("url"),
                            "ext": (vs.get("format") or "mp4").lower(),
                            "height": height,
                            "filesize": vs.get("contentLength"),
                            "format_note": q or "Video",
                            "vcodec": vs.get("codec") or "h264",
                            "acodec": "none" if vs.get("videoOnly") else "aac",
                        })
                    for idx, aus in enumerate(data.get("audioStreams", [])):
                        if not aus.get("url"):
                            continue
                        formats.append({
                            "format_id": f"piped_a_{idx}",
                            "url": aus.get("url"),
                            "ext": "m4a",
                            "height": None,
                            "filesize": aus.get("contentLength"),
                            "format_note": aus.get("quality") or "Audio",
                            "vcodec": "none",
                            "acodec": aus.get("codec") or "aac",
                        })
                    return {
                        "id": vid_id,
                        "extractor": "youtube",
                        "title": data.get("title") or f"YouTube_{vid_id}",
                        "thumbnail": data.get("thumbnailUrl"),
                        "duration": data.get("duration"),
                        "uploader": data.get("uploader"),
                        "formats": formats,
                        "_via_public_api": True,
                    }
        except Exception:
            continue
    raise ValueError("Cloud IP blocked by YouTube and backup APIs are busy")


def base_options():
    options = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "extractor_retries": 5,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "remote_components": ["ejs:github"],
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    deno_path = shutil.which("deno")
    if deno_path:
        options["js_runtimes"] = {"deno": {"path": deno_path}}

    custom_proxy = os.getenv("PROXY_URL")
    if custom_proxy:
        options["proxy"] = custom_proxy
    return options


def extract_with_fallback(url, options, download=False):
    client_profiles = [
        ["tv_embedded", "ios"],
        ["ios", "android_vr"],
        ["mweb", "tv"],
        ["android", "web_embedded"],
    ]

    last_error = None

    # Step 1: Try client profiles if YouTube URL
    if is_youtube_url(url):
        for clients in client_profiles:
            try:
                try_opts = dict(options)
                try_opts["extractor_args"] = {
                    "youtube": {
                        "player_client": clients,
                        "player_skip": ["webpage", "configs"],
                    }
                }
                with YoutubeDL(try_opts) as ydl:
                    return ydl.extract_info(url, download=download)
            except Exception as e:
                last_error = e
                continue

    # Step 2: Default extraction
    try:
        default_opts = dict(options)
        if is_youtube_url(url):
            default_opts["extractor_args"] = {"youtube": {"player_client": ["ios", "tv", "mweb"]}}
        with YoutubeDL(default_opts) as ydl:
            return ydl.extract_info(url, download=download)
    except Exception as e:
        last_error = e

    # Step 3: Cookie file fallback
    if os.path.isfile(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        try:
            cookie_opts = dict(options)
            cookie_opts["cookiefile"] = COOKIE_FILE
            if is_youtube_url(url):
                cookie_opts["extractor_args"] = {"youtube": {"player_client": ["tv", "mweb", "web"]}}
            with YoutubeDL(cookie_opts) as ydl:
                return ydl.extract_info(url, download=download)
        except Exception as e:
            last_error = e

    # Step 4: Tor / Proxy fallback
    proxy = get_proxy_url()
    if proxy and not options.get("proxy"):
        try:
            proxy_opts = dict(options)
            proxy_opts["proxy"] = proxy
            with YoutubeDL(proxy_opts) as ydl:
                return ydl.extract_info(url, download=download)
        except Exception as e:
            last_error = e

    # Step 5: Public API fallback for YouTube
    if is_youtube_url(url):
        try:
            return fetch_youtube_via_public_api(url)
        except Exception as e:
            last_error = e

    if last_error:
        raise last_error
    raise ValueError("Unable to extract video information")


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
        if tk.get("play") and tk.get("play") != tk.get("hdplay"):
            formats.append({
                "format_id": "sd",
                "ext": "mp4",
                "height": 720,
                "filesize": tk.get("size"),
                "note": "Standard (No Watermark)",
                "has_audio": True,
            })
        elif not formats and tk.get("play"):
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
        ext = f.get("ext") or ""
        if ext in ("mhtml", "none") or f.get("vcodec") == "images":
            continue
        if f.get("url") and (f.get("height") or f.get("acodec") != "none"):
            formats.append({
                "format_id": f.get("format_id"),
                "ext": ext,
                "height": f.get("height"),
                "filesize": f.get("filesize") or f.get("filesize_approx"),
                "note": f.get("format_note"),
                "has_audio": f.get("acodec") != "none",
            })

    formats.sort(key=lambda x: (x.get("height") or 0, 1 if x.get("has_audio") else 0), reverse=True)

    return {
        "type": "video",
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "formats": formats[:60],
    }


def _stream_download_to_file(media_url, filepath, headers=None):
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    }
    if headers:
        req_headers.update(headers)
    try:
        r = requests.get(media_url, stream=True, headers=req_headers, timeout=30)
        r.raise_for_status()
    except Exception:
        proxy = get_proxy_url()
        r = requests.get(
            media_url,
            stream=True,
            headers=req_headers,
            proxies={"http": proxy, "https": proxy} if proxy else None,
            timeout=60,
        )
        r.raise_for_status()
    with r:
        with open(filepath, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    return filepath


def download_media(url, format_id="best", audio=False):
    validate_url(url)
    unique_prefix = uuid.uuid4().hex[:8]

    if is_tiktok_url(url):
        tk = fetch_tiktok_via_api(url)
        vid_id = tk.get("id") or "video"

        if audio or format_id == "audio":
            media_url = tk.get("music") or tk.get("play") or tk.get("hdplay")
            ext = "mp3" if tk.get("music") else "mp4"
        elif format_id == "hd" and tk.get("hdplay"):
            media_url = tk.get("hdplay")
            ext = "mp4"
        else:
            media_url = tk.get("play") or tk.get("hdplay")
            ext = "mp4"

        if not media_url:
            raise ValueError("Direct media stream not found for this TikTok")

        if media_url.startswith("/"):
            media_url = "https://www.tikwm.com" + media_url

        filepath = os.path.join(DOWNLOAD_DIR, f"{unique_prefix}_TikTok_{vid_id}.{ext}")
        _stream_download_to_file(media_url, filepath, headers={"Referer": "https://www.tiktok.com/"})
        return filepath

    if audio:
        selected_format = "bestaudio/best"
    elif format_id and format_id != "best":
        selected_format = f"{format_id}+bestaudio/{format_id}/best"
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

    # Handle public API fallback direct stream download
    if info.get("_via_public_api"):
        fmts = info.get("formats", [])
        chosen = None
        if audio:
            chosen = next((f for f in fmts if f.get("vcodec") == "none"), None)
        elif format_id and format_id != "best":
            chosen = next((f for f in fmts if str(f.get("format_id")) == str(format_id)), None)
        if not chosen and fmts:
            chosen = fmts[0]
        if not chosen or not chosen.get("url"):
            raise ValueError("No downloadable stream found from backup API")
        ext = "m4a" if audio else (chosen.get("ext") or "mp4")
        filepath = os.path.join(DOWNLOAD_DIR, f"{unique_prefix}_youtube_{info.get('id', 'video')}.{ext}")
        return _stream_download_to_file(chosen["url"], filepath)

    for fname in os.listdir(DOWNLOAD_DIR):
        if fname.startswith(unique_prefix) and not fname.endswith((".part", ".ytdl")):
            filepath = os.path.join(DOWNLOAD_DIR, fname)
            if os.path.isfile(filepath):
                return filepath

    raise FileNotFoundError("Downloaded file could not be located")
