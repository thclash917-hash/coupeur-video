import os
import subprocess
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import whisper
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

# Charger le modèle Whisper au démarrage ("base" est un bon compromis rapidité/précision)
print("Chargement du modèle Whisper...")
model = whisper.load_model("tiny")
print("Modèle Whisper chargé avec succès !")

def format_time(seconds):
    """Convertit des secondes en format SRT (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

@app.post("/cut")
async def cut_video(
    file: UploadFile = File(...),
    segment_duration: int = Form(30),
    max_clips: int = Form(1),
    start_min: int = Form(0),
    end_min: int = Form(10),
    aspect_ratio: str = Form("original"),
    quality: str = Form("original"),
    add_subs: str = Form("false"),  # Reçoit "true" ou "false"
):
    input_path = f"temp_{file.filename}"
    output_dir = "output_clips"
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Sauvegarder la vidéo reçue temporairement
    with open(input_path, "wb") as buffer:
        buffer.write(await file.read())

    srt_path = None
    # 2. Si add_subs == "true", générer les sous-titres avec Whisper
    if add_subs == "true":
        audio_path = "temp_audio.mp3"
        try:
            # Extraire l'audio pour Whisper
            subprocess.run(["ffmpeg", "-y", "-i", input_path, "-q:a", "0", "-map", "a", audio_path], check=True)
            
            # Transcription avec Whisper
            result = model.transcribe(audio_path)
            
            # Créer un fichier de sous-titres .srt valide
            srt_path = "temp_subtitles.srt"
            with open(srt_path, "w", encoding="utf-8") as srt_file:
                for i, segment in enumerate(result["segments"], start=1):
                    start_str = format_time(segment["start"])
                    end_str = format_time(segment["end"])
                    text = segment["text"].strip()
                    srt_file.write(f"{i}\n{start_str} --> {end_str}\n{text}\n\n")
        except Exception as e:
            print(f"Erreur lors de la génération des sous-titres : {e}")
        finally:
            if os.path.exists(audio_path):
                os.remove(audio_path)

    # 3. Préparation des filtres FFmpeg (Format 9:16, Qualité et Sous-titres)
    filter_chains = []

    # Gestion du format d'image (Crop 9:16 si demandé)
    if aspect_ratio == "9:16":
        # Centre la vidéo en rognant pour obtenir du 9:16
        filter_chains.append("crop=in_h*9/16:in_h:(in_w-in_h*9/16)/2:0")

    # Gestion de la qualité / résolution
    if quality == "720p":
        filter_chains.append("scale=-2:720")
    elif quality == "1080p":
        filter_chains.append("scale=-2:1080")
    elif quality == "4k":
        filter_chains.append("scale=-2:2160")

    # Incrustation des sous-titres si le fichier .srt existe
    if srt_path and os.path.exists(srt_path):
        # Attention sous Windows/Linux avec les chemins absolus/relatifs pour le filtre subtitles de ffmpeg
        abs_srt_path = os.path.abspath(srt_path).replace("\\", "/")
        # Style personnalisable pour les sous-titres (Police blanche, contour noir, centrés)
        sub_filter = f"subtitles='{abs_srt_path}':force_style='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2'"
        filter_chains.append(sub_filter)

    # Construction de la chaîne de filtres globale (-vf)
    vf_arg = ",".join(filter_chains) if filter_chains else None

    # 4. Simulation / Découpage basique d'un extrait (à adapter selon ta logique de découpage globale)
    # Exemple pour un extrait basé sur start_min en secondes :
    start_time_sec = start_min * 60
    output_filename = f"extrait_1.mp4"
    output_filepath = os.path.join(output_dir, output_filename)

    cmd = ["ffmpeg", "-y", "-ss", str(start_time_sec), "-i", input_path, "-t", str(segment_duration)]
    
    if vf_arg:
        cmd.extend(["-vf", vf_arg])
    
    # Encodage standard rapide
    cmd.extend(["-c:v", "libx264", "-preset", "fast", "-c:a", "aac", output_filepath])

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Erreur FFmpeg : {e}")

    # 5. Compresser le(s) résultat(s) en ZIP
    zip_filename = "extraits_shorts.zip"
    zip_path = os.path.join(output_dir, zip_filename)
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        if os.path.exists(output_filepath):
            zipf.write(output_filepath, arcname=output_filename)

    # Nettoyage des fichiers temporaires sources et srt
    if os.path.exists(input_path):
        os.remove(input_path)
    if srt_path and os.path.exists(srt_path):
        os.remove(srt_path)

    # 6. Renvoyer le ZIP au client
    return FileResponse(zip_path, media_type="application/x-zip-compressed", filename=zip_filename)
