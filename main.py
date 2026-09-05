import os
import subprocess
import requests
import static_ffmpeg

static_ffmpeg.add_paths()

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
# MODÈLE DE DONNÉES
# ==========================================

class VideoRequest(BaseModel):
    url: str
    segment_duration: int
    start_min: int
    end_min: int

# ==========================================
# ROUTES & LOGIQUE
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

@app.post("/cut")
def cut_video(data: VideoRequest, background_tasks: BackgroundTasks):

    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)
    output_clip_path = os.path.join(output_dir, f"clip_{os.urandom(4).hex()}.mp4")

    start_sec = data.start_min * 60
    end_sec = data.end_min * 60

    if start_sec >= end_sec:
        raise HTTPException(
            status_code=400,
            detail="La minute de début doit être inférieure à la minute de fin."
        )

    if data.segment_duration <= 0:
        raise HTTPException(
            status_code=400,
            detail="La durée du segment doit être supérieure à 0."
        )

    # ==========================================
    # 1. RÉCUPÉRATION DU FLUX VIA COBALT
    # ==========================================

    cobalt_url = "https://api.cobalt.tools/"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "url": data.url,
        "videoQuality": "720"
    }

    try:
        response = requests.post(cobalt_url, json=payload, headers=headers, timeout=15)
        res_data = response.json()

        if response.status_code != 200 or "url" not in res_data:
            error_detail = res_data.get("text", "Impossible d'extraire la vidéo.")
            raise HTTPException(status_code=400, detail=f"Erreur Cobalt : {error_detail}")

        direct_stream_url = res_data["url"]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impossible de contacter l'API Cobalt : {str(e)}")

    # ==========================================
    # 2. DÉCOUPAGE AVEC FFMPEG
    # ==========================================

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_sec),
            "-i", direct_stream_url,
            "-t", str(data.segment_duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-strict", "experimental",
            output_clip_path
        ]

        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    except Exception as e:
        cleanup_file(output_clip_path)
        raise HTTPException(status_code=500, detail=f"Erreur lors du traitement vidéo : {str(e)}")

    if not os.path.exists(output_clip_path):
        raise HTTPException(status_code=500, detail="Échec de la génération du fichier.")

    # Nettoyage automatique après l'envoi
    background_tasks.add_task(cleanup_file, output_clip_path)

    return FileResponse(
        path=output_clip_path,
        filename="extrait.mp4",
        media_type="video/mp4"
    )
