import os
import shutil
import subprocess
import static_ffmpeg

static_ffmpeg.add_paths()

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
async def cut_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    segment_duration: int = Form(...),
    start_min: int = Form(...),
    end_min: int = Form(...)
):
    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)

    token = os.urandom(4).hex()
    input_video_path = os.path.join(output_dir, f"input_{token}_{file.filename}")
    output_clip_path = os.path.join(output_dir, f"clip_{token}.mp4")

    # 1. Sauvegarde du fichier téléversé
    try:
        with open(input_video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la réception du fichier : {str(e)}")

    start_sec = start_min * 60
    end_sec = end_min * 60

    if start_sec >= end_sec:
        cleanup_file(input_video_path)
        raise HTTPException(status_code=400, detail="La minute de début doit être inférieure à la minute de fin.")

    if segment_duration <= 0:
        cleanup_file(input_video_path)
        raise HTTPException(status_code=400, detail="La durée du segment doit être supérieure à 0.")

    # 2. Découpage vidéo ultra-rapide avec FFmpeg
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_sec),
            "-i", input_video_path,
            "-t", str(segment_duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-strict", "experimental",
            output_clip_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        cleanup_file(input_video_path)
        cleanup_file(output_clip_path)
        raise HTTPException(status_code=500, detail=f"Erreur de traitement FFmpeg : {str(e)}")

    # Suppression du fichier source lourd dès le découpage terminé
    cleanup_file(input_video_path)

    if not os.path.exists(output_clip_path):
        raise HTTPException(status_code=500, detail="Échec du découpage.")

    # Nettoyage de l'extrait après envoi au client
    background_tasks.add_task(cleanup_file, output_clip_path)

    return FileResponse(
        path=output_clip_path,
        filename=f"extrait_{segment_duration}s.mp4",
        media_type="video/mp4"
    )
