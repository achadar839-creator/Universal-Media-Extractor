import os
import asyncio
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from backend.extractor import get_info, download_media

app = FastAPI(title="Universal Media Extractor")

app.mount("/static", StaticFiles(directory="frontend"), name="static")


class URLRequest(BaseModel):
    url: HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
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
        return await asyncio.to_thread(get_info, str(data.url))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/download")
async def download(data: DownloadRequest, background_tasks: BackgroundTasks):
    try:
        filepath = await asyncio.to_thread(
            download_media,
            str(data.url),
            data.format_id,
            data.audio
        )

        clean_name = os.path.basename(filepath)
        if "_" in clean_name:
            clean_name = clean_name.split("_", 1)[1]

        background_tasks.add_task(remove_file, filepath)

        return FileResponse(
            filepath,
            filename=clean_name,
            media_type="application/octet-stream"
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/health")
async def health():
    return {"status": "online"}
