import os
import static_ffmpeg
static_ffmpeg.add_paths()

from fastapi import FastAPI, HTTPException, BackgroundTasks
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

def cleanup_file(filepath: str):
    if os.path.exists(filepath):
        os.remove(filepath)

@app.post("/cut")
def cut_video(data: VideoRequest, background_tasks: BackgroundTasks):
    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)
    output_clip_path = os.path.join(output_dir, f"clip_{os.urandom(4).hex()}.mp4")

    start_sec = data.start_min * 60

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': output_clip_path,
        'download_ranges': yt_dlp.utils.download_range_func(None, [(start_sec, start_sec + data.segment_duration)]),
        'force_keyframes_at_cuts': True,
        'quiet': True,
        'nocheckcertificate': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb']
            }
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([data.url])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erreur lors du traitement: {str(e)}")

    if not os.path.exists(output_clip_path):
        raise HTTPException(status_code=500, detail="Échec de la génération de la vidéo.")

    background_tasks.add_task(cleanup_file, output_clip_path)

    return FileResponse(
        path=output_clip_path,
        filename="extrait.mp4",
        media_type="video/mp4"
    )
