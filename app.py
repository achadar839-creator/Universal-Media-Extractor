import os
import glob
import asyncio
from fastapi import FastAPI, HTTPException
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
async def download(data: DownloadRequest):
    try:
        existing = set(glob.glob("downloads/*"))

        await asyncio.to_thread(
            download_media,
            str(data.url),
            data.format_id,
            data.audio
        )

        files = [
            f for f in glob.glob("downloads/*")
            if f not in existing and os.path.isfile(f)
        ]

        if not files:
            raise Exception("New download file not found")

        latest = max(files, key=os.path.getmtime)

        return FileResponse(
            latest,
            filename=os.path.basename(latest),
            media_type="application/octet-stream"
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/health")
async def health():
    return {"status": "online"}
