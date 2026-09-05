import os
import subprocess
import shutil
import uuid
from fastapi import FastAPI, File, Form, UploadFile, Header, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import zipfile

app = FastAPI()

# Configuration CORS pour autoriser ton interface front-end
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en production si besoin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "mon_super_secret_123")

@app.post("/cut")
async def cut_video(
    file: UploadFile = File(...),
    segment_duration: int = Form(30),
    max_clips: int = Form(1),
    start_min: int = Form(0),
    end_min: int = Form(10),
    aspect_ratio: str = Form("original"),
    quality: str = Form("original"),
    add_subs: str = Form("false"),  # Gardé en paramètre pour éviter l'erreur si ton HTML l'envoie encore
):
    input_path = f"temp_{file.filename}"
    output_dir = "output_clips"
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Sauvegarder la vidéo reçue temporairement
    with open(input_path, "wb") as buffer:
        buffer.write(await file.read())

    # 2. Préparation des filtres FFmpeg
    filter_chains = []

    if aspect_ratio == "9:16":
        filter_chains.append("crop=in_h*9/16:in_h:(in_w-in_h*9/16)/2:0")

    if quality == "720p":
        filter_chains.append("scale=-2:720")
    elif quality == "1080p":
        filter_chains.append("scale=-2:1080")
    elif quality == "4k":
        filter_chains.append("scale=-2:2160")

    vf_arg = ",".join(filter_chains) if filter_chains else None

    # 3. Découpage des extraits en boucle selon max_clips avec ID unique (preset ultrafast pour une vitesse maximale)
    unique_id = str(uuid.uuid4())[:8]
    start_sec = start_min * 60
    output_files = []

    for i in range(1, max_clips + 1):
        current_start_sec = start_sec + ((i - 1) * segment_duration)
        output_filename = f"extrait_{i}_{unique_id}.mp4"
        output_filepath = os.path.join(output_dir, output_filename)

        cmd = ["ffmpeg", "-y", "-ss", str(current_start_sec), "-i", input_path, "-t", str(segment_duration)]
        
        if vf_arg:
            cmd.extend(["-vf", vf_arg])
        
        # Ajout de "-r", "30" pour bloquer le framerate et empêcher l'explosion des frames
        cmd.extend(["-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", output_filepath])

        try:
            subprocess.run(cmd, check=True)
            output_files.append((output_filepath, output_filename))
        except subprocess.CalledProcessError as e:
            print(f"Erreur FFmpeg pour l'extrait {i} : {e}")

    # 4. Compresser tous les extraits générés dans le ZIP
    zip_filename = f"extraits_shorts_{unique_id}.zip"
    zip_path = os.path.join(output_dir, zip_filename)
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for file_path, arc_name in output_files:
            if os.path.exists(file_path):
                zipf.write(file_path, arcname=arc_name)

    # Nettoyage du fichier source temporaire
    if os.path.exists(input_path):
        os.remove(input_path)

    return FileResponse(zip_path, media_type="application/x-zip-compressed", filename=zip_filename)


# Route de nettoyage sécurisée (réservée à l'administrateur)
@app.post("/clean")
async def clean_server(x_admin_token: str = Header(...)):
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Accès refusé : mot de passe incorrect !"
        )
    
    output_dir = "output_clips"
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        
    return {"status": "Serveur nettoyé avec succès ! Tous les clips temporaires ont été supprimés."}
