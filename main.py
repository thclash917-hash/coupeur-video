import os
import shutil
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
# DÉCOUPAGE VIDÉO
# ==========================================

@app.post("/cut")
def cut_video(
    data: VideoRequest,
    background_tasks: BackgroundTasks
):

    # ==========================================
    # DOSSIER DE SORTIE
    # ==========================================

    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)

    output_clip_path = os.path.join(
        output_dir,
        f"clip_{os.urandom(4).hex()}.mp4"
    )

    # ==========================================
    # CALCUL DES TEMPS
    # ==========================================

    start_sec = data.start_min * 60
    end_sec = data.end_min * 60

    # ==========================================
    # SÉCURITÉ
    # ==========================================

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
    # PRÉPARATION DES COOKIES YOUTUBE
    # ==========================================

    cookie_source = "/etc/secrets/cookies.txt"
    cookie_copy = "/tmp/cookies.txt"

    try:
        shutil.copyfile(
            cookie_source,
            cookie_copy
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Impossible de préparer les cookies YouTube : {str(e)}"
        )

    # ==========================================
    # CONFIGURATION YT-DLP
    # ==========================================

    ydl_opts = {

        # Format vidéo
        "format": "best[ext=mp4]/best",

        # Fichier de sortie
        "outtmpl": output_clip_path,

        # Cookies YouTube
        "cookiefile": cookie_copy,

        # Découpage directement pendant le téléchargement
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

        # Force les keyframes nécessaires au découpage
        "force_keyframes_at_cuts": True,

        # Affiche les logs Render
        "quiet": False,

        # Évite certains problèmes de certificat
        "nocheckcertificate": True,

        # Contournement anti-bot YouTube (clients mobiles)
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios"]
            }
        },
    }

    # ==========================================
    # TÉLÉCHARGEMENT
    # ==========================================

    try:

        print("========================================")
        print("NOUVELLE DEMANDE")
        print("URL :", data.url)
        print("Début :", start_sec, "secondes")
        print("Fin :", end_sec, "secondes")
        print("Durée demandée :", data.segment_duration, "secondes")
        print("Cookies :", cookie_copy)
        print("========================================")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([data.url])

    except Exception as e:

        print("========================================")
        print("ERREUR YT-DLP")
        print(str(e))
        print("========================================")

        raise HTTPException(
            status_code=400,
            detail=f"Erreur lors du traitement : {str(e)}"
        )

    # ==========================================
    # VÉRIFICATION DU FICHIER
    # ==========================================

    if not os.path.exists(output_clip_path):

        raise HTTPException(
            status_code=500,
            detail="Échec de la génération de la vidéo."
        )

    # ==========================================
    # SUPPRESSION AUTOMATIQUE
    # ==========================================

    background_tasks.add_task(
        cleanup_file,
        output_clip_path
    )

    # ==========================================
    # RETOUR DE LA VIDÉO
    # ==========================================

    return FileResponse(
        path=output_clip_path,
        filename="extrait.mp4",
        media_type="video/mp4"
    )
