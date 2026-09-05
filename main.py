import os
import shutil
import zipfile
import static_ffmpeg

static_ffmpeg.add_paths()

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI()

# ==========================================
# CORS
# ==========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# MODÈLES DE DONNÉES
# ==========================================

class VideoRequest(BaseModel):
    url: str
    segment_duration: int
    start_min: int
    end_min: int

class AutoCutRequest(BaseModel):
    url: str
    segment_duration: int = 30

# ==========================================
# UTILITAIRES
# ==========================================

@app.get("/")
def home():
    return {"status": "API en ligne"}

def cleanup_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass

def cleanup_dir(dirpath: str):
    try:
        if os.path.exists(dirpath):
            shutil.rmtree(dirpath)
    except Exception:
        pass

# ==========================================
# 1. DÉCOUPAGE MANUEL (Ton bouton actuel)
# ==========================================

@app.post("/cut")
def cut_video(data: VideoRequest, background_tasks: BackgroundTasks):
    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)

    output_clip_path = os.path.join(output_dir, f"clip_{os.urandom(4).hex()}.mp4")

    start_sec = data.start_min * 60
    end_sec = data.end_min * 60

    if start_sec >= end_sec:
        raise HTTPException(status_code=400, detail="La minute de début doit être inférieure à la minute de fin.")

    if data.segment_duration <= 0:
        raise HTTPException(status_code=400, detail="La durée du segment doit être supérieure à 0.")

    cookie_source = "/etc/secrets/cookies.txt"
    cookie_copy = "/tmp/cookies.txt"

    try:
        shutil.copyfile(cookie_source, cookie_copy)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impossible de préparer les cookies YouTube : {str(e)}")

    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": output_clip_path,
        "cookiefile": cookie_copy,
        "download_ranges": yt_dlp.utils.download_range_func(
            None,
            [(start_sec, min(start_sec + data.segment_duration, end_sec))]
        ),
        "force_keyframes_at_cuts": True,
        "quiet": False,
        "nocheckcertificate": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["mweb", "android", "ios"]
            }
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([data.url])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erreur lors du traitement : {str(e)}")

    if not os.path.exists(output_clip_path):
        raise HTTPException(status_code=500, detail="Échec de la génération de la vidéo.")

    background_tasks.add_task(cleanup_file, output_clip_path)

    return FileResponse(path=output_clip_path, filename="extrait.mp4", media_type="video/mp4")

# ==========================================
# 2. DÉCOUPAGE AUTOMATIQUE (Nouveau style NoTube)
# ==========================================

@app.post("/auto-cut")
def auto_cut_video(data: AutoCutRequest, background_tasks: BackgroundTasks):
    job_id = os.urandom(4).hex()
    work_dir = os.path.join("downloads", job_id)
    os.makedirs(work_dir, exist_ok=True)
    
    ydl_info_opts = {
        "quiet": True,
        "nocheckcertificate": True,
        "extractor_args": {"youtube": {"player_client": ["mweb", "android"]}}
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(data.url, download=False)
            total_duration = info.get("duration", 0)
            
        if total_duration == 0:
            raise HTTPException(status_code=400, detail="Impossible de lire la durée de la vidéo.")
            
    except Exception as e:
        cleanup_dir(work_dir)
        raise HTTPException(status_code=400, detail=f"Erreur YouTube : {str(e)}")

    segments = []
    current_start = 0
    clip_index = 1

    while current_start < total_duration:
        current_end = min(current_start + data.segment_duration, total_duration)
        if (current_end - current_start) >= 5:
            segments.append((clip_index, current_start, current_end))
        current_start += data.segment_duration
        clip_index += 1

    generated_files = []
    
    for idx, start_sec, end_sec in segments:
        clip_filename = f"extrait_{idx}.mp4"
        clip_path = os.path.join(work_dir, clip_filename)
        
        ydl_cut_opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": clip_path,
            "download_ranges": yt_dlp.utils.download_range_func(None, [(start_sec, end_sec)]),
            "force_keyframes_at_cuts": True,
            "quiet": True,
            "nocheckcertificate": True,
            "extractor_args": {"youtube": {"player_client": ["mweb", "android"]}}
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_cut_opts) as ydl:
                ydl.download([data.url])
            if os.path.exists(clip_path):
                generated_files.append(clip_path)
        except Exception:
            continue

    if not generated_files:
        cleanup_dir(work_dir)
        raise HTTPException(status_code=500, detail="Aucun extrait n'a pu être généré.")

    zip_filename = f"extraits_{job_id}.zip"
    zip_path = os.path.join("downloads", zip_filename)
    
    with zipfile.ZipFile(zip_path, "w") as zipf:
        for file in generated_files:
            zipf.write(file, os.path.basename(file))

    cleanup_dir(work_dir)
    background_tasks.add_task(cleanup_file, zip_path)

    return FileResponse(path=zip_path, filename="mes_extraits.zip", media_type="application/zip")
