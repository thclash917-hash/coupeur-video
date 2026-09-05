import os
import subprocess
import shutil
import uuid
import zipfile
import asyncio

from fastapi import (
FastAPI,
File,
Form,
UploadFile,
Header,
HTTPException,
status,
)

from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# ============================================================

# APPLICATION

# ============================================================

app = FastAPI()

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

BASE_DIR = "jobs"

# Création du dossier principal

os.makedirs(BASE_DIR, exist_ok=True)

# ============================================================

# ROUTE ROOT

# ============================================================

@app.get("/")
async def root():
return {
"status": "online",
"message": "Le serveur est bien réveillé !"
}

# ============================================================

# FONCTION FFmpeg

# ============================================================

def run_ffmpeg(cmd):
"""
Lance FFmpeg de manière isolée.
"""

```
print("\n========================================")
print("LANCEMENT FFMPEG")
print("========================================")
print(" ".join(cmd))
print("========================================\n")

subprocess.run(
    cmd,
    check=True,
    stdin=subprocess.DEVNULL,
)
```

# ============================================================

# CUT VIDEO

# ============================================================

@app.post("/cut")
async def cut_video(
file: UploadFile = File(...),

```
segment_duration: int = Form(30),
max_clips: int = Form(1),

start_min: int = Form(0),
end_min: int = Form(10),

aspect_ratio: str = Form("original"),
quality: str = Form("original"),

add_subs: str = Form("false"),
```

):

```
# ========================================================
# 1. VALIDATION
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
# 2. ID UNIQUE DE LA TÂCHE
# ========================================================

unique_id = uuid.uuid4().hex

print("\n")
print("========================================")
print("NOUVELLE TÂCHE")
print("========================================")
print(f"JOB ID : {unique_id}")
print(f"FICHIER : {file.filename}")
print("========================================")


# ========================================================
# 3. DOSSIER INDIVIDUEL
# ========================================================

job_dir = os.path.join(
    BASE_DIR,
    unique_id
)

os.makedirs(
    job_dir,
    exist_ok=True
)


# ========================================================
# 4. NOM DE FICHIER SÉCURISÉ
# ========================================================

# On ne fait PAS confiance au nom envoyé par le navigateur.

original_filename = file.filename or "video.mp4"

extension = os.path.splitext(
    original_filename
)[1].lower()

if not extension:
    extension = ".mp4"

input_filename = f"input{extension}"

input_path = os.path.join(
    job_dir,
    input_filename
)


# ========================================================
# 5. SAUVEGARDE DU FICHIER
# ========================================================

try:

    with open(input_path, "wb") as buffer:

        while True:

            chunk = await file.read(1024 * 1024)

            if not chunk:
                break

            buffer.write(chunk)

except Exception as e:

    shutil.rmtree(
        job_dir,
        ignore_errors=True
    )

    raise HTTPException(
        status_code=500,
        detail=f"Erreur pendant l'upload : {str(e)}"
    )


print(f"Fichier sauvegardé : {input_path}")


# ========================================================
# 6. PRÉPARATION DES FILTRES
# ========================================================

filter_chains = []


# --------------------------------------------------------
# FORMAT 9:16
# --------------------------------------------------------

if aspect_ratio == "9:16":

    filter_chains.append(
        "crop=in_h*9/16:in_h:"
        "(in_w-in_h*9/16)/2:0"
    )


# --------------------------------------------------------
# QUALITÉ
# --------------------------------------------------------

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
# 7. GÉNÉRATION DES CLIPS
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


    # ----------------------------------------------------
    # CHAQUE CLIP EST DANS LE DOSSIER DE LA TÂCHE
    # ----------------------------------------------------

    output_filename = (
        f"extrait_{i}.mp4"
    )

    output_filepath = os.path.join(
        job_dir,
        output_filename
    )


    # ----------------------------------------------------
    # COMMANDE FFMPEG
    # ----------------------------------------------------

    cmd = [
        "ffmpeg",

        "-y",
        "-nostdin",

        "-i",
        input_path,

        "-ss",
        str(current_start_sec),

        "-t",
        str(segment_duration),
    ]


    # ----------------------------------------------------
    # FILTRE
    # ----------------------------------------------------

    if vf_arg:

        cmd.extend([
            "-vf",
            vf_arg
        ])


    # ----------------------------------------------------
    # ENCODAGE
    # ----------------------------------------------------

    cmd.extend([
        "-r",
        "30",

        "-c:v",
        "libx264",

        "-preset",
        "ultrafast",

        "-c:a",
        "aac",

        "-movflags",
        "+faststart",

        output_filepath
    ])


    try:

        run_ffmpeg(cmd)

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
                f"Clip {i} terminé : "
                f"{output_filepath}"
            )

    except subprocess.CalledProcessError as e:

        print(
            f"Erreur FFmpeg pour le clip "
            f"{i} : {e}"
        )


# ========================================================
# 8. VÉRIFICATION
# ========================================================

if not output_files:

    shutil.rmtree(
        job_dir,
        ignore_errors=True
    )

    raise HTTPException(
        status_code=500,
        detail="Aucun clip n'a pu être généré."
    )


# ========================================================
# 9. CRÉATION DU ZIP
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

            if os.path.exists(file_path):

                zipf.write(
                    file_path,
                    arcname=arc_name
                )

except Exception as e:

    shutil.rmtree(
        job_dir,
        ignore_errors=True
    )

    raise HTTPException(
        status_code=500,
        detail=f"Erreur création ZIP : {str(e)}"
    )


# ========================================================
# 10. SUPPRESSION DE LA VIDÉO SOURCE
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
        f"Impossible de supprimer "
        f"la source : {e}"
    )


# ========================================================
# 11. RÉPONSE
# ========================================================

print("\n")
print("========================================")
print("TÂCHE TERMINÉE")
print("========================================")
print(f"JOB ID : {unique_id}")
print(f"ZIP : {zip_path}")
print("========================================\n")


return FileResponse(
    path=zip_path,
    media_type="application/zip",
    filename=zip_filename,
)
```

# ============================================================

# CLEAN

# ============================================================

@app.post("/clean")
async def clean_server(
x_admin_token: str = Header(...)
):

```
# --------------------------------------------------------
# AUTHENTIFICATION
# --------------------------------------------------------

if x_admin_token != ADMIN_SECRET:

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Accès refusé : mot de passe incorrect !"
    )


# --------------------------------------------------------
# ATTENTION :
#
# On ne supprime PAS les jobs en cours brutalement.
#
# Cette route peut être utilisée pour supprimer
# les anciens dossiers.
# --------------------------------------------------------

if not os.path.exists(
    BASE_DIR
):

    os.makedirs(
        BASE_DIR,
        exist_ok=True
    )

    return {
        "status": "Serveur nettoyé."
    }


deleted = 0


for name in os.listdir(
    BASE_DIR
):

    job_path = os.path.join(
        BASE_DIR,
        name
    )


    if not os.path.isdir(
        job_path
    ):
        continue


    try:

        shutil.rmtree(
            job_path
        )

        deleted += 1

    except Exception as e:

        print(
            f"Impossible de supprimer "
            f"{job_path} : {e}"
        )


return {
    "status": "Nettoyage terminé.",
    "jobs_supprimes": deleted
}
```
