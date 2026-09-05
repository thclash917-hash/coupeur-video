import os
import subprocess
import static_ffmpeg
static_ffmpeg.add_paths()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VideoRequest(BaseModel):
    url: str
    segment_duration: int
    start_min: int
    end_min: int

@app.get("/")
def home():
    return {"status": "API en ligne"}

@app.post("/cut")
def cut_video(data: VideoRequest):
    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)
    raw_video_path = os.path.join(output_dir, "input.mp4")
    
    if os.path.exists(raw_video_path):
        os.remove(raw_video_path)

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': raw_video_path,
        'quiet': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([data.url])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erreur de téléchargement YouTube: {str(e)}")

    start_sec = data.start_min * 60
    duration_sec = data.segment_duration
    output_clip_path = os.path.join(output_dir, "clip.mp4")

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", raw_video_path,
        "-t", str(duration_sec),
        "-c", "copy",
        output_clip_path
    ]
    
    subprocess.run(cmd, check=True)

    if not os.path.exists(output_clip_path):
        raise HTTPException(status_code=500, detail="Échec du traitement vidéo par ffmpeg.")

    return FileResponse(
        path=output_clip_path,
        filename="extrait.mp4",
        media_type="video/mp4"
    )
