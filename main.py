import os
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
# MODÈLE
# ==========================================

class VideoRequest(BaseModel):
    url: str
    segment_duration: int
    start_min: int
    end_min: int


# ==========================================
# ACCUEIL
# ==========================================

@app.get("/")
def home():
    return {"status": "API en ligne"}


# ==========================================
# NETTOYAGE
# ==========================================

def cleanup_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass


# ==========================================
# DÉCOUPAGE
# ==========================================

@app.post("/cut")
def cut_video(
    data: VideoRequest,
    background_tasks: BackgroundTasks
):

    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)

    output_clip_path = os.path.join(
        output_dir,
        f"clip_{os.urandom(4).hex()}.mp4"
    )

    start_sec = data.start_min * 60
    end_sec = data.end_min * 60

    # Sécurité
    if start_sec >= end_sec:
        raise HTTPException(
            status_code=400,
            detail="La minute de début doit être inférieure à la minute de fin."
        )

    # ==========================================
    # CONFIGURATION YT-DLP
    # ==========================================

    ydl_opts = {
        "format": "best[ext=mp4]/best",

        "outtmpl": output_clip_path,

        "cookiefile": "/etc/secrets/cookies.txt",

        "download_ranges": yt_dlp.utils.download_range_func(
            None,
            [
                (
                    start_sec,
                    min(
                        start_sec + data.segment_duration,
                        end_sec
                    )
                )
            ]
        ),

        "force_keyframes_at_cuts": True,

        "quiet": False,

        "nocheckcertificate": True,

        # IMPORTANT :
        # PAS de username/password OAuth
        #
        # PAS de player_client forcé
    }

    # ==========================================
    # TÉLÉCHARGEMENT
    # ==========================================

    try:

        print("========================================")
        print("URL :", data.url)
        print("Début :", start_sec)
        print("Fin :", end_sec)
        print("Durée :", data.segment_duration)
        print("========================================")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([data.url])

    except Exception as e:

        print("ERREUR YT-DLP :", str(e))

        raise HTTPException(
            status_code=400,
            detail=f"Erreur lors du traitement: {str(e)}"
        )

    # ==========================================
    # VÉRIFICATION
    # ==========================================

    if not os.path.exists(output_clip_path):

        raise HTTPException(
            status_code=500,
            detail="Échec de la génération de la vidéo."
        )

    # ==========================================
    # SUPPRESSION APRÈS ENVOI
    # ==========================================

    background_tasks.add_task(
        cleanup_file,
        output_clip_path
    )

    # ==========================================
    # RETOUR VIDÉO
    # ==========================================

    return FileResponse(
        path=output_clip_path,
        filename="extrait.mp4",
        media_type="video/mp4"
    )
