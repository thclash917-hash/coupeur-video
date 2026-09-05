import os
import subprocess
import shutil
import uuid
from fastapi import FastAPI, File, Form, UploadFile, Header, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
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

# Initialisation des clients (clés lues depuis les variables d'environnement de Render)
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "mon_super_secret_123")

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
    # 2. Si add_subs == "true", générer les sous-titres via l'API Groq (Whisper)
    if add_subs == "true":
        audio_path = "temp_audio.mp3"
        try:
            subprocess.run(["ffmpeg", "-y", "-i", input_path, "-q:a", "0", "-map", "a", audio_path], check=True)
            
            with open(audio_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=(audio_path, audio_file.read()),
                    model="whisper-large-v3",
                    response_format="verbose_json"
                )
            
            srt_path = "temp_subtitles.srt"
            with open(srt_path, "w", encoding="utf-8") as srt_file:
                segments = getattr(transcription, "segments", [])
                for i, segment in enumerate(segments, start=1):
                    start = segment.start if hasattr(segment, "start") else segment["start"]
                    end = segment.end if hasattr(segment, "end") else segment["end"]
                    text = segment.text if hasattr(segment, "text") else segment["text"]
                    
                    start_str = format_time(start)
                    end_str = format_time(end)
                    clean_text = text.strip()
                    srt_file.write(f"{i}\n{start_str} --> {end_str}\n{clean_text}\n\n")
        except Exception as e:
            print(f"Erreur lors de la génération des sous-titres : {e}")
        finally:
            if os.path.exists(audio_path):
                os.remove(audio_path)

    # 3. Préparation des filtres FFmpeg
    filter_chains = []

    if aspect_ratio == "9:16":
        filter_chains.append("crop=in_h*9/16:in_h:(in_w-in_h*9/16)/2:0")

    if quality == "720p":
        filter_chains.append("scale=-2:720")
    elif quality == "1080p":
        filter_chains.append("scale=-2:1080")
    elif quality == "4k":
        filter_chains.append("scale=-2:2160")

    if srt_path and os.path.exists(srt_path):
        abs_srt_path = os.path.abspath(srt_path).replace("\\", "/")
        sub_filter = f"subtitles='{abs_srt_path}':force_style='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2'"
        filter_chains.append(sub_filter)

    vf_arg = ",".join(filter_chains) if filter_chains else None

    # 4. Découpage des extraits en boucle selon max_clips avec ID unique (preset ultrafast pour la vitesse)
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
        
        cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", output_filepath])

        try:
            subprocess.run(cmd, check=True)
            output_files.append((output_filepath, output_filename))
        except subprocess.CalledProcessError as e:
            print(f"Erreur FFmpeg pour l'extrait {i} : {e}")

    # 5. Compresser tous les extraits générés dans le ZIP
    zip_filename = f"extraits_shorts_{unique_id}.zip"
    zip_path = os.path.join(output_dir, zip_filename)
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for file_path, arc_name in output_files:
            if os.path.exists(file_path):
                zipf.write(file_path, arcname=arc_name)

    # Nettoyage des fichiers temporaires sources et srt
    if os.path.exists(input_path):
        os.remove(input_path)
    if srt_path and os.path.exists(srt_path):
        os.remove(srt_path)

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
