import os
import re
import time
import shutil
import uuid
import socket
import requests
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from backend.security import is_tiktok_url, is_youtube_url, validate_url, sanitize_filename

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def _resolve_cookie_file():
    candidates = [
        "/etc/secrets/youtube-cookies.txt",
        os.path.abspath("private/youtube-cookies.txt"),
        os.path.abspath("cookies/youtube.cookies"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            target = "/tmp/youtube-cookies.txt"
            try:
                with open(candidate, "r", encoding="utf-8", errors="ignore") as src, open(target, "w", encoding="utf-8") as dst:
                    for line in src:
                        s = line.strip()
                        if not s or s.startswith("#"):
                            dst.write(line)
                        elif "\t" not in s and len(s.split()) >= 7:
                            parts = s.split(None, 6)
                            dst.write("\t".join(parts) + "\n")
                        else:
                            dst.write(line)
                return target
            except OSError:
                return candidate
    return None


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


def _has_playable_media(info):
    if not info or not isinstance(info, dict):
        return False
    if info.get("_type") in ("playlist", "multi_video") or info.get("entries"):
        return True
    if info.get("_via_public_api"):
        return bool(info.get("formats"))
    for f in info.get("formats") or []:
        ext = (f.get("ext") or "").lower()
        if ext in ("mhtml", "none") or f.get("vcodec") == "images":
            continue
        if f.get("url") or f.get("manifest_url"):
            if f.get("height") or (f.get("acodec") and f.get("acodec") != "none") or (f.get("vcodec") and f.get("vcodec") != "none"):
                return True
    return bool(info.get("url"))


def fetch_tiktok_via_api(url):
    api_url = "https://www.tikwm.com/api/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.tikwm.com",
        "Referer": "https://www.tikwm.com/",
    }

    last_error = None
    for attempt in range(3):
        try:
            response = requests.post(
                api_url,
                data={"url": url, "hd": 1},
                headers=headers,
                timeout=(10, 35),
            )
            response.raise_for_status()
            result = response.json()
            if result.get("code") == 0 and result.get("data"):
                data = result["data"]
                # Normalize relative paths from TikWM
                for key in ("hdplay", "play", "wmplay", "music", "cover"):
                    val = data.get(key)
                    if isinstance(val, str) and val.startswith("/"):
                        data[key] = "https://www.tikwm.com" + val
                return data
            last_error = result.get("msg") or "TikWM returned no video data"
        except Exception as exc:
            last_error = str(exc)
        if attempt < 2:
            time.sleep(1.5)

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
            "_use_ytdlp": True,
        }
    except Exception as fallback_error:
        raise ValueError(
            f"TikTok extraction failed. TikWM: {last_error}. "
            f"yt-dlp fallback: {fallback_error}"
        )


def fetch_youtube_via_public_api(url):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise ValueError("Invalid YouTube video ID")
    vid_id = m.group(1)
    clean_watch_url = f"https://www.youtube.com/watch?v={vid_id}"

    # 1. Try Cobalt public API instances (best for Render / Cloud IPs)
    cobalt_instances = [
        "https://api.cobalt.tools/",
        "https://cobalt-api.kwiatekmiki.com/",
        "https://cobalt.api.timelessnesses.me/",
    ]
    for c_api in cobalt_instances:
        try:
            r = requests.post(
                c_api,
                json={"url": clean_watch_url, "videoQuality": "720"},
                headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                timeout=5,
            )
            if r.status_code == 200:
                cdata = r.json()
                dl_url = cdata.get("url")
                if dl_url:
                    return {
                        "id": vid_id,
                        "extractor": "youtube",
                        "title": cdata.get("filename") or f"YouTube_{vid_id}",
                        "thumbnail": f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                        "duration": None,
                        "uploader": "YouTube",
                        "formats": [{
                            "format_id": "cobalt_720",
                            "url": dl_url,
                            "ext": "mp4",
                            "height": 720,
                            "filesize": None,
                            "format_note": "720p HD",
                            "vcodec": "h264",
                            "acodec": "aac",
                        }],
                        "_via_public_api": True,
                        "_cobalt_url": clean_watch_url,
                    }
        except Exception:
            continue

    # 2. Try Piped / Invidious public instances
    piped_instances = [
        f"https://pipedapi.kavin.rocks/streams/{vid_id}",
        f"https://pipedapi.adminforge.de/streams/{vid_id}",
        f"https://api.piped.private.coffee/streams/{vid_id}",
        f"https://pipedapi.darkness.services/streams/{vid_id}",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for api in piped_instances:
        try:
            r = requests.get(api, headers=headers, timeout=12)
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
                        "thumbnail": data.get("thumbnailUrl") or f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                        "duration": data.get("duration"),
                        "uploader": data.get("uploader"),
                        "formats": formats,
                        "_via_public_api": True,
                    }
        except Exception:
            continue

    raise ValueError("Cloud IP blocked by YouTube. Add youtube-cookies.txt in Render Secrets for 100% uptime.")


def base_options():
    options = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 10,
        "extractor_retries": 1,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "remote_components": ["ejs:github"],
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
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
    last_error = None
    cookie_file = _resolve_cookie_file()

    yt_profiles = [
        {"player_client": ["android_vr", "ios"]},
    ]

    if is_youtube_url(url):
        if cookie_file:
            try:
                cookie_opts = dict(options)
                cookie_opts["cookiefile"] = cookie_file
                cookie_opts["extractor_args"] = {"youtube": {"player_client": ["tv", "mweb", "web"]}}
                with YoutubeDL(cookie_opts) as ydl:
                    info = ydl.extract_info(url, download=download)
                if download or _has_playable_media(info):
                    return info
            except Exception as e:
                last_error = e

        for yt_arg in yt_profiles:
            try:
                try_opts = dict(options)
                try_opts["extractor_args"] = {"youtube": yt_arg}
                with YoutubeDL(try_opts) as ydl:
                    info = ydl.extract_info(url, download=download)
                if download or _has_playable_media(info):
                    return info
                last_error = ValueError("No playable formats returned by client profile")
            except Exception as e:
                last_error = e
                continue

    try:
        default_opts = dict(options)
        if cookie_file and not is_youtube_url(url):
            default_opts["cookiefile"] = cookie_file
        with YoutubeDL(default_opts) as ydl:
            info = ydl.extract_info(url, download=download)
        if download or _has_playable_media(info):
            return info
    except Exception as e:
        last_error = e

    proxy = get_proxy_url()
    if proxy and not options.get("proxy"):
        try:
            proxy_opts = dict(options)
            proxy_opts["proxy"] = proxy
            with YoutubeDL(proxy_opts) as ydl:
                info = ydl.extract_info(url, download=download)
            if download or _has_playable_media(info):
                return info
        except Exception as e:
            last_error = e

    if is_youtube_url(url):
        try:
            return fetch_youtube_via_public_api(url)
        except Exception as e:
            last_error = e

    if last_error:
        raise last_error
    raise ValueError("Unable to extract media information from the provided URL")


def get_info(url):
    url = validate_url(url, has_proxy=bool(get_proxy_url()))

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
                "has_video": True,
            })
        if tk.get("play") and tk.get("play") != tk.get("hdplay"):
            formats.append({
                "format_id": "sd",
                "ext": "mp4",
                "height": 720,
                "filesize": tk.get("size"),
                "note": "Standard (No Watermark)",
                "has_audio": True,
                "has_video": True,
            })
        elif not formats and tk.get("play"):
            formats.append({
                "format_id": "sd",
                "ext": "mp4",
                "height": 720,
                "filesize": tk.get("size"),
                "note": "Standard (No Watermark)",
                "has_audio": True,
                "has_video": True,
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
            "uploader": info.get("uploader") or "Playlist",
            "thumbnail": info.get("thumbnail") or (entries[0].get("thumbnail") if entries else None),
            "entries": entries,
            "count": len(entries),
        }

    formats = []
    seen_keys = set()
    for f in info.get("formats", []):
        ext = (f.get("ext") or "").lower()
        if ext in ("mhtml", "none") or f.get("vcodec") == "images":
            continue
        has_url = bool(f.get("url") or f.get("manifest_url"))
        has_video = bool(f.get("height") or (f.get("vcodec") and f.get("vcodec") != "none"))
        has_audio = bool(f.get("acodec") and f.get("acodec") != "none")
        # Only keep video formats in dropdown (audio is handled by DOWNLOAD MP3 button)
        if not has_url or not has_video or not f.get("height"):
            continue

        height = f.get("height")
        fid = str(f.get("format_id"))
        dedup_key = (height, ext, has_audio)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        formats.append({
            "format_id": fid,
            "ext": ext or "mp4",
            "height": height,
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "note": f.get("format_note") or "Video",
            "has_audio": has_audio,
            "has_video": True,
        })

    formats.sort(
        key=lambda x: (
            x.get("height") or 0,
            1 if x.get("has_audio") else 0,
            x.get("filesize") or 0,
        ),
        reverse=True,
    )

    return {
        "type": "video",
        "title": info.get("title") or "Media",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel") or "Unknown",
        "formats": formats[:30],
    }


def _stream_download_to_file(media_url, filepath, headers=None):
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
        "Accept": "*/*",
    }
    if headers:
        req_headers.update(headers)
    try:
        r = requests.get(media_url, stream=True, headers=req_headers, timeout=30, allow_redirects=True)
        r.raise_for_status()
    except Exception:
        proxy = get_proxy_url()
        r = requests.get(
            media_url,
            stream=True,
            headers=req_headers,
            proxies={"http": proxy, "https": proxy} if proxy else None,
            timeout=60,
            allow_redirects=True,
        )
        r.raise_for_status()
    with r:
        with open(filepath, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    return filepath


def download_media(url, format_id="best", audio=False):
    url = validate_url(url, has_proxy=bool(get_proxy_url()))
    unique_prefix = uuid.uuid4().hex[:8]

    if is_tiktok_url(url):
        tk = fetch_tiktok_via_api(url)
        vid_id = sanitize_filename(str(tk.get("id") or "video"))

        if audio or format_id == "audio":
            candidates = [tk.get("music"), tk.get("play"), tk.get("hdplay")]
            ext = "mp3" if tk.get("music") else "mp4"
        elif format_id == "hd":
            candidates = [tk.get("hdplay"), tk.get("play"), tk.get("wmplay")]
            ext = "mp4"
        else:
            candidates = [tk.get("play"), tk.get("hdplay"), tk.get("wmplay")]
            ext = "mp4"

        candidates = [c for c in candidates if c]
        filepath = os.path.join(DOWNLOAD_DIR, f"{unique_prefix}_TikTok_{vid_id}.{ext}")

        # Try direct stream from TikWM/CDN candidates with proper TikTok Referer
        for media_url in candidates:
            try:
                _stream_download_to_file(
                    media_url,
                    filepath,
                    headers={"Referer": "https://www.tiktok.com/", "Origin": "https://www.tiktok.com"},
                )
                if os.path.isfile(filepath) and os.path.getsize(filepath) > 1024:
                    return filepath
            except Exception:
                continue

        # Fallback: let yt-dlp download TikTok directly if CDN returned 403
        yt_opts = base_options()
        yt_opts.update({
            "outtmpl": os.path.join(DOWNLOAD_DIR, f"{unique_prefix}_TikTok_{vid_id}.%(ext)s"),
            "format": "bestaudio/best" if audio else "best",
            "noplaylist": True,
        })
        if audio:
            yt_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
        with YoutubeDL(yt_opts) as ydl:
            ydl.extract_info(url, download=True)
        for fname in os.listdir(DOWNLOAD_DIR):
            if fname.startswith(unique_prefix) and not fname.endswith((".part", ".ytdl")):
                fp = os.path.join(DOWNLOAD_DIR, fname)
                if os.path.isfile(fp) and os.path.getsize(fp) > 0:
                    return fp
        raise ValueError("TikTok CDN blocked direct download (403) and yt-dlp fallback failed")

    if audio:
        selected_format = "bestaudio/best"
    elif format_id and format_id != "best" and not str(format_id).startswith(("piped_", "cobalt_")):
        selected_format = f"{format_id}+bestaudio/{format_id}/bestvideo+bestaudio/best"
    else:
        selected_format = "bestvideo+bestaudio/best"

    options = base_options()
    options.update({
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{unique_prefix}_%(extractor)s_%(id)s.%(ext)s"),
        "format": selected_format,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "overwrites": True,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 5,
        "socket_timeout": 10,
        "continuedl": True,
        "nopart": False,
        "merge_output_format": "mp4",
        "max_filesize": int(os.getenv("MAX_DOWNLOAD_MB", "500")) * 1024 * 1024,
    })

    if audio:
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    info = extract_with_fallback(url, options, download=True)

    if info and info.get("_via_public_api"):
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
        vid_id = sanitize_filename(str(info.get("id") or "video"))
        filepath = os.path.join(DOWNLOAD_DIR, f"{unique_prefix}_youtube_{vid_id}.{ext}")
        return _stream_download_to_file(chosen["url"], filepath)

    for fname in os.listdir(DOWNLOAD_DIR):
        if fname.startswith(unique_prefix) and not fname.endswith((".part", ".ytdl")):
            filepath = os.path.join(DOWNLOAD_DIR, fname)
            if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
                return filepath

    raise FileNotFoundError("Downloaded file could not be located on server")
