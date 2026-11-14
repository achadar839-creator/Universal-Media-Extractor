import os
import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from backend.extractor import get_info, download_media
from backend.security import sanitize_filename

app = FastAPI(title="Universal Media Extractor")

app.mount("/static", StaticFiles(directory="frontend"), name="static")


class URLRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format_id: str = "best"
    audio: bool = False


def remove_file(path: str):
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


@app.get("/")
async def home():
    return FileResponse("frontend/index.html")


@app.post("/api/info")
async def info(data: URLRequest):
    try:
        return await asyncio.to_thread(get_info, data.url.strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/download")
async def download(data: DownloadRequest, background_tasks: BackgroundTasks):
    try:
        filepath = await asyncio.to_thread(
            download_media,
            data.url.strip(),
            data.format_id or "best",
            data.audio,
        )

        clean_name = os.path.basename(filepath)
        if "_" in clean_name:
            clean_name = clean_name.split("_", 1)[1]
        clean_name = sanitize_filename(clean_name, default="media.mp3" if data.audio else "media.mp4")

        background_tasks.add_task(remove_file, filepath)

        return FileResponse(
            filepath,
            filename=clean_name,
            media_type="audio/mpeg" if clean_name.endswith(".mp3") else "application/octet-stream",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/health")
async def health():
    return {"status": "online"}
