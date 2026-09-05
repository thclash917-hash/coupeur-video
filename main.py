import os
import re
import subprocess
import requests
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
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass

def extract_video_id(url: str) -> str:
    patterns = [
        r"(?:v=|\/)([\w-]{11})(?:\?|&|#|$)",
        r"youtu\.be\/([\w-]{11})"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_stream_from_piped(video_id: str) -> str:
    piped_instances = [
        "https://pipedapi.kavin.rocks",
        "https://api.piped.privacydev.net",
        "https://pipedapi.mha.fi"
    ]
    for instance in piped_instances:
        try:
            res = requests.get(f"{instance}/streams/{video_id}", timeout=6)
            if res.status_code == 200:
                data = res.json()
                streams = data.get("videoStreams", [])
                # Recherche d'un flux combiné vidéo+audio
                for stream in streams:
                    if not stream.get("videoOnly", True) and stream.get("url"):
                        return stream["url"]
                # Repli sur le premier flux vidéo disponible
                if streams and "url" in streams[0]:
                    return streams[0]["url"]
        except Exception:
            continue
    return None

@app.post("/cut")
def cut_video(data: VideoRequest, background_tasks: BackgroundTasks):
    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)
    output_clip_path = os.path.join(output_dir, f"clip_{os.urandom(4).hex()}.mp4")

    start_sec = data.start_min * 60
    end_sec = data.end_min * 60

    if start_sec >= end_sec:
        raise HTTPException(status_code=400, detail="La minute de début doit être inférieure à la minute de fin.")

    video_id = extract_video_id(data.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="URL YouTube invalide.")

    # 1. Tentative via l'API Piped
    stream_url = get_stream_from_piped(video_id)

    # 2. Secours via yt-dlp (Clients TV / VR)
    if not stream_url:
        clean_url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "quiet": True,
            "nocheckcertificate": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["tvhtml5", "android_vr"]
                }
            }
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=False)
                stream_url = info.get("url")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Impossible de récupérer la vidéo : {str(e)}")

    if not stream_url:
        raise HTTPException(status_code=500, detail="Aucun flux vidéo accessible.")

    # 3. Découpage avec FFmpeg
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_sec),
            "-i", stream_url,
            "-t", str(data.segment_duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-strict", "experimental",
            output_clip_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        cleanup_file(output_clip_path)
        raise HTTPException(status_code=500, detail=f"Erreur de traitement FFmpeg : {str(e)}")

    if not os.path.exists(output_clip_path):
        raise HTTPException(status_code=500, detail="Échec du découpage.")

    background_tasks.add_task(cleanup_file, output_clip_path)

    return FileResponse(path=output_clip_path, filename="extrait.mp4", media_type="video/mp4")
