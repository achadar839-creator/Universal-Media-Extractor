import re
import socket
import ipaddress
from urllib.parse import urlparse

TIKTOK_DOMAINS = ("tiktok.com", "vt.tiktok.com", "vm.tiktok.com", "douyin.com")
YOUTUBE_DOMAINS = ("youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com")


def is_tiktok_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in TIKTOK_DOMAINS)


def is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in YOUTUBE_DOMAINS)


def validate_url(url: str, has_proxy: bool = False) -> str:
    if not url or not isinstance(url, str):
        raise ValueError("Invalid URL")
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid URL: must start with http:// or https://")

    host = parsed.hostname.lower()
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.endswith((".local", ".internal", ".lan")):
        raise ValueError("Local or internal address is blocked")

    try:
        ip_obj = ipaddress.ip_address(host)
        if not ip_obj.is_global:
            raise ValueError("Private IP address is blocked")
    except ValueError as e:
        if "blocked" in str(e):
            raise

    if is_tiktok_url(url):
        return url

    try:
        addresses = socket.getaddrinfo(host, None)
        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                raise ValueError("Private network address blocked")
    except socket.gaierror:
        if not has_proxy:
            raise ValueError("Unable to resolve website domain")

    return url


def sanitize_filename(name: str, default: str = "media") -> str:
    if not name:
        return default
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", name).strip(" ._")
    return cleaned[:150] or default
