import os
import asyncio
import subprocess
import shutil
import uuid
import zipfile
import time

from fastapi import (
    FastAPI,
    File,
    Form,
    UploadFile,
    Header,
    HTTPException,
    BackgroundTasks,
    status,
)

from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware


# ============================================================
# APPLICATION
# ============================================================

app = FastAPI(
    title="Découpeur Vidéo Shorts",
    version="2.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# CONFIGURATION
# ============================================================

ADMIN_SECRET = os.getenv(
    "ADMIN_SECRET",
    "mon_super_secret_123"
)

BASE_DIR = os.path.abspath(
    os.getenv(
        "JOBS_DIR",
        "jobs"
    )
)

os.makedirs(
    BASE_DIR,
    exist_ok=True
)


# ============================================================
# NETTOYAGE
# ============================================================

CLEANUP_AGE_HOURS = float(
    os.getenv(
        "CLEANUP_AGE_HOURS",
        "6"
    )
)


# ============================================================
# TRAITEMENTS SIMULTANÉS
# ============================================================

MAX_CONCURRENT_JOBS = int(
    os.getenv(
        "MAX_CONCURRENT_JOBS",
        "2"
    )
)

FFMPEG_SEMAPHORE = asyncio.Semaphore(
    MAX_CONCURRENT_JOBS
)


# ============================================================
# ROUTE PRINCIPALE
# ============================================================

@app.get("/")
async def root():

    return {
        "status": "online",
        "message": "Le serveur est bien réveillé !",
        "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
        "cleanup_age_hours": CLEANUP_AGE_HOURS,
    }


# ============================================================
# GESTION DES JOBS
# ============================================================

def get_active_marker(job_dir: str) -> str:

    return os.path.join(
        job_dir,
        ".active"
    )


def mark_job_active(job_dir: str):

    marker = get_active_marker(
        job_dir
    )

    try:

        with open(
            marker,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                str(time.time())
            )

    except Exception as e:

        print(
            f"[JOB] Erreur création marqueur : {e}"
        )


def unmark_job_active(job_dir: str):

    marker = get_active_marker(
        job_dir
    )

    try:

        if os.path.exists(marker):

            os.remove(marker)

    except Exception as e:

        print(
            f"[JOB] Erreur suppression marqueur : {e}"
        )


def is_job_active(job_dir: str) -> bool:

    return os.path.exists(
        get_active_marker(job_dir)
    )


def delete_job(job_dir: str):

    try:

        if os.path.exists(job_dir):

            shutil.rmtree(
                job_dir,
                ignore_errors=True
            )

            print(
                f"[JOB] Job supprimé : {job_dir}"
            )

    except Exception as e:

        print(
            f"[JOB] Erreur suppression job : {e}"
        )


# ============================================================
# APRÈS TÉLÉCHARGEMENT
# ============================================================

def release_job_after_download(job_dir: str):

    print(
        f"[JOB] Téléchargement terminé : {job_dir}"
    )

    unmark_job_active(
        job_dir
    )


# ============================================================
# FFMPEG
# ============================================================

def run_ffmpeg(cmd):

    print()
    print("========================================")
    print("LANCEMENT FFMPEG")
    print("========================================")
    print(" ".join(cmd))
    print("========================================")
    print()

    subprocess.run(
        cmd,
        check=True,
        stdin=subprocess.DEVNULL,
    )


async def run_ffmpeg_async(cmd):

    async with FFMPEG_SEMAPHORE:

        await asyncio.to_thread(
            run_ffmpeg,
            cmd
        )


# ============================================================
# CUT VIDEO
# ============================================================

@app.post("/cut")
async def cut_video(
    file: UploadFile = File(...),
    segment_duration: int = Form(30),
    max_clips: int = Form(1),
    start_min: int = Form(0),
    end_min: int = Form(10),
    aspect_ratio: str = Form("original"),
    quality: str = Form("original"),
    add_subs: str = Form("false"),
    background_tasks: BackgroundTasks = None,
):

    # ========================================================
    # VALIDATION
    # ========================================================

    if segment_duration <= 0:

        raise HTTPException(
            status_code=400,
            detail="La durée du segment doit être supérieure à 0."
        )


    if max_clips <= 0:

        raise HTTPException(
            status_code=400,
            detail="Le nombre de clips doit être supérieur à 0."
        )


    if max_clips > 25:

        raise HTTPException(
            status_code=400,
            detail="Maximum 25 extraits."
        )


    if start_min < 0:

        raise HTTPException(
            status_code=400,
            detail="start_min ne peut pas être négatif."
        )


    if end_min <= start_min:

        raise HTTPException(
            status_code=400,
            detail="end_min doit être supérieur à start_min."
        )


    # ========================================================
    # FORMAT
    # ========================================================

    if aspect_ratio not in {
        "original",
        "9:16",
    }:

        raise HTTPException(
            status_code=400,
            detail="Format invalide."
        )


    # ========================================================
    # QUALITÉ
    # ========================================================

    if quality not in {
        "original",
        "720p",
        "1080p",
        "4k",
    }:

        raise HTTPException(
            status_code=400,
            detail="Qualité invalide."
        )


    # ========================================================
    # ID UNIQUE
    # ========================================================

    unique_id = uuid.uuid4().hex

    print()
    print("========================================")
    print("NOUVELLE TÂCHE")
    print("========================================")
    print(f"JOB ID : {unique_id}")
    print(f"FICHIER : {file.filename}")
    print("========================================")
    print()


    # ========================================================
    # DOSSIER UNIQUE
    # ========================================================

    job_dir = os.path.join(
        BASE_DIR,
        unique_id
    )

    os.makedirs(
        job_dir,
        exist_ok=False
    )


    # ========================================================
    # PROTECTION
    # ========================================================

    mark_job_active(
        job_dir
    )


    # ========================================================
    # EXTENSION
    # ========================================================

    original_filename = (
        file.filename
        or "video.mp4"
    )

    extension = os.path.splitext(
        original_filename
    )[1].lower()


    allowed_extensions = {
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".m4v",
    }


    if extension not in allowed_extensions:

        extension = ".mp4"


    input_path = os.path.join(
        job_dir,
        f"input{extension}"
    )


    # ========================================================
    # UPLOAD
    # ========================================================

    try:

        with open(
            input_path,
            "wb"
        ) as buffer:

            while True:

                chunk = await file.read(
                    1024 * 1024
                )

                if not chunk:

                    break

                buffer.write(
                    chunk
                )


        await file.close()

        print(
            f"[JOB {unique_id}] Upload terminé."
        )


    except Exception as e:

        print(
            f"[JOB {unique_id}] Erreur upload : {e}"
        )

        delete_job(
            job_dir
        )

        raise HTTPException(
            status_code=500,
            detail="Erreur pendant l'upload."
        )


    # ========================================================
    # FILTRES FFMPEG
    # ========================================================

    filter_chains = []


    if aspect_ratio == "9:16":

        filter_chains.append(
            "crop="
            "min(in_h*9/16\\,in_w):"
            "min(in_h\\,in_w*16/9):"
            "(in_w-min(in_h*9/16\\,in_w))/2:"
            "(in_h-min(in_h\\,in_w*16/9))/2"
        )


    if quality == "720p":

        filter_chains.append(
            "scale=-2:720"
        )


    elif quality == "1080p":

        filter_chains.append(
            "scale=-2:1080"
        )


    elif quality == "4k":

        filter_chains.append(
            "scale=-2:2160"
        )


    vf_arg = (
        ",".join(filter_chains)
        if filter_chains
        else None
    )


    # ========================================================
    # GÉNÉRATION DES CLIPS
    # ========================================================

    start_sec = start_min * 60

    output_files = []


    for i in range(
        1,
        max_clips + 1
    ):

        current_start_sec = (
            start_sec
            + ((i - 1) * segment_duration)
        )


        output_filename = (
            f"extrait_{i}.mp4"
        )


        output_filepath = os.path.join(
            job_dir,
            output_filename
        )


        # ====================================================
        # COMMANDE FFMPEG
        # ====================================================

        cmd = [

            "ffmpeg",

            "-y",

            "-hide_banner",

            "-nostdin",

            "-i",
            input_path,

            "-ss",
            str(current_start_sec),

            "-t",
            str(segment_duration),
        ]


        # ====================================================
        # FILTRE
        # ====================================================

        if vf_arg:

            cmd.extend([
                "-vf",
                vf_arg
            ])


        # ====================================================
        # ENCODAGE
        # ====================================================

        cmd.extend([

            "-r",
            "30",

            "-c:v",
            "libx264",

            "-preset",
            "ultrafast",

            "-crf",
            "23",

            "-pix_fmt",
            "yuv420p",

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-movflags",
            "+faststart",

            output_filepath
        ])


        # ====================================================
        # EXÉCUTION
        # ====================================================

        try:

            print(
                f"[JOB {unique_id}] "
                f"Clip {i}/{max_clips}"
            )

            await run_ffmpeg_async(
                cmd
            )


            if os.path.exists(
                output_filepath
            ):

                output_files.append(
                    (
                        output_filepath,
                        output_filename
                    )
                )

                print(
                    f"[JOB {unique_id}] "
                    f"Clip {i} terminé."
                )


        except subprocess.CalledProcessError as e:

            print(
                f"[JOB {unique_id}] "
                f"FFmpeg erreur clip {i}: {e}"
            )


    # ========================================================
    # VÉRIFICATION
    # ========================================================

    if not output_files:

        delete_job(
            job_dir
        )

        raise HTTPException(
            status_code=500,
            detail="Aucun clip n'a pu être généré."
        )


    # ========================================================
    # ZIP
    # ========================================================

    zip_filename = (
        f"extraits_shorts_{unique_id}.zip"
    )


    zip_path = os.path.join(
        job_dir,
        zip_filename
    )


    try:

        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED
        ) as zipf:

            for (
                file_path,
                arc_name
            ) in output_files:

                if os.path.exists(
                    file_path
                ):

                    zipf.write(
                        file_path,
                        arcname=arc_name
                    )


        print(
            f"[JOB {unique_id}] ZIP créé."
        )


    except Exception as e:

        print(
            f"[JOB {unique_id}] Erreur ZIP : {e}"
        )

        delete_job(
            job_dir
        )

        raise HTTPException(
            status_code=500,
            detail="Erreur création du ZIP."
        )


    # ========================================================
    # SUPPRESSION SOURCE
    # ========================================================

    try:

        if os.path.exists(
            input_path
        ):

            os.remove(
                input_path
            )

    except Exception as e:

        print(
            f"[JOB {unique_id}] "
            f"Impossible de supprimer la source : {e}"
        )


    # ========================================================
    # VÉRIFICATION ZIP
    # ========================================================

    if not os.path.exists(
        zip_path
    ):

        delete_job(
            job_dir
        )

        raise HTTPException(
            status_code=500,
            detail="ZIP introuvable."
        )


    # ========================================================
    # FIN DU TRAITEMENT
    # ========================================================

    print()
    print("========================================")
    print("TÂCHE TERMINÉE")
    print("========================================")
    print(f"JOB ID : {unique_id}")
    print(f"ZIP : {zip_path}")
    print("========================================")
    print()


    # ========================================================
    # PROTECTION PENDANT LE TÉLÉCHARGEMENT
    # ========================================================

    if background_tasks is not None:

        background_tasks.add_task(
            release_job_after_download,
            job_dir
        )


    # ========================================================
    # RÉPONSE
    # ========================================================

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=zip_filename,
    )


# ============================================================
# CLEAN ADMIN
# ============================================================

@app.post("/clean")
async def clean_server(
    x_admin_token: str = Header(...)
):

    # ========================================================
    # AUTHENTIFICATION
    # ========================================================

    if x_admin_token != ADMIN_SECRET:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Accès refusé : mot de passe incorrect !"
        )


    # ========================================================
    # DOSSIER
    # ========================================================

    if not os.path.exists(
        BASE_DIR
    ):

        os.makedirs(
            BASE_DIR,
            exist_ok=True
        )

        return {
            "status": "Serveur déjà propre.",
            "jobs_supprimes": 0,
        }


    # ========================================================
    # ÂGE MAXIMUM
    # ========================================================

    max_age_seconds = (
        CLEANUP_AGE_HOURS
        * 60
        * 60
    )


    current_time = time.time()

    deleted = 0

    skipped_active = 0

    skipped_recent = 0


    # ========================================================
    # PARCOURS
    # ========================================================

    for name in os.listdir(
        BASE_DIR
    ):

        job_path = os.path.join(
            BASE_DIR,
            name
        )


        # ----------------------------------------------------
        # IGNORER LES FICHIERS
        # ----------------------------------------------------

        if not os.path.isdir(
            job_path
        ):

            continue


        # ----------------------------------------------------
        # PROTECTION JOB ACTIF
        # ----------------------------------------------------

        if is_job_active(
            job_path
        ):

            print(
                f"[CLEAN] Job actif protégé : {name}"
            )

            skipped_active += 1

            continue


        # ----------------------------------------------------
        # ÂGE
        # ----------------------------------------------------

        try:

            modified_time = os.path.getmtime(
                job_path
            )

            age = (
                current_time
                - modified_time
            )


        except Exception as e:

            print(
                f"[CLEAN] Erreur âge {name} : {e}"
            )

            continue


        # ----------------------------------------------------
        # JOB RÉCENT
        # ----------------------------------------------------

        if age < max_age_seconds:

            skipped_recent += 1

            continue


        # ----------------------------------------------------
        # SUPPRESSION
        # ----------------------------------------------------

        try:

            shutil.rmtree(
                job_path
            )

            deleted += 1

            print(
                f"[CLEAN] Job supprimé : {name}"
            )


        except Exception as e:

            print(
                f"[CLEAN] Erreur suppression "
                f"{name} : {e}"
            )


    # ========================================================
    # RÉSULTAT
    # ========================================================

    return {

        "status": "Nettoyage terminé.",

        "jobs_supprimes": deleted,

        "jobs_actifs_proteges": skipped_active,

        "jobs_recents_conserves": skipped_recent,

        "age_nettoyage_heures": CLEANUP_AGE_HOURS,

    }
