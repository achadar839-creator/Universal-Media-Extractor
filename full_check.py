import sys
import socket
import shutil
import subprocess
import importlib.util
from pathlib import Path

ROOT = Path.cwd()
results = []

def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append((name, status, str(detail)))
    print(f"[{status}] {name}: {detail}")

print("\n========== UNIVERSAL MEDIA EXTRACTOR CHECK ==========\n")

for f in [
    "app.py", "requirements.txt", "Dockerfile",
    "backend/extractor.py", "backend/security.py",
    "frontend/index.html", "frontend/js/script.js", "frontend/css/style.css"
]:
    exists = (ROOT / f).is_file()
    check("FILE " + f, exists, "Present" if exists else "Missing")

check("Python", True, sys.version.split()[0])

for pkg in ["fastapi", "uvicorn", "yt_dlp", "requests", "dotenv", "aiofiles", "multipart"]:
    ok = importlib.util.find_spec(pkg) is not None
    check("Python package " + pkg, ok, "Installed" if ok else "Missing")

for tool in ["ffmpeg", "git", "curl", "deno"]:
    path = shutil.which(tool)
    check("Command " + tool, bool(path), path or "Not installed")

p = subprocess.run([sys.executable, "-m", "compileall", "-q", "app.py", "backend"], capture_output=True, text=True)
check("Python syntax", p.returncode == 0, p.stderr.strip() or "No syntax errors")

for host in ["www.youtube.com", "www.instagram.com", "github.com"]:
    try:
        ip = socket.gethostbyname(host)
        check("DNS " + host, True, ip)
    except Exception as e:
        check("DNS " + host, False, e)

passed = sum(x[1] == "PASS" for x in results)
failed = sum(x[1] == "FAIL" for x in results)
print(f"\nSUMMARY -> TOTAL: {len(results)} | PASS: {passed} | FAIL: {failed}\n")
