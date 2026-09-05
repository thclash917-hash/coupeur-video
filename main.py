import os
import zipfile
import shutil
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
import subprocess

app = FastAPI()

@app.post("/cut")
async def cut_video(
    file: UploadFile = File(...),
    segment_duration: int = Form(...),
    max_clips: int = Form(...),
    start_min: int = Form(...),
    end_min: int = Form(...)
):
    temp_dir = "temp_clips"
    os.makedirs(temp_dir, exist_ok=True)
    
    input_path = os.path.join(temp_dir, file.filename)
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    start_sec = start_min * 60
    end_sec = end_min * 60
    total_available_time = end_sec - start_sec

    # Calcul du pas d'espacement pour garantir des extraits différents
    if max_clips > 1:
        step = max(segment_duration, (total_available_time - segment_duration) / (max_clips - 1))
    else:
        step = 0

    generated_files = []

    for i in range(max_clips):
        clip_start = start_sec + (i * step)
        
        # Sécurité pour ne pas dépasser la fin spécifiée
        if clip_start + segment_duration > end_sec:
            break

        output_filename = f"extrait_{i+1}.mp4"
        output_path = os.path.join(temp_dir, output_filename)

        # Commande FFmpeg ré-encodée proprement
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(clip_start),
            "-i", input_path,
            "-t", str(segment_duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            output_path
        ]
        
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            generated_files.append(output_path)

    if not generated_files:
        shutil.rmtree(temp_dir)
        raise HTTPException(status_code=400, detail="Plage horaire trop courte pour générer ces extraits.")

    # Création du fichier ZIP avec tous les extraits uniques
    zip_path = os.path.join(temp_dir, "extraits.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for f in generated_files:
            zipf.write(f, os.path.basename(f))

    return FileResponse(zip_path, media_type="application/zip", filename="extraits_30s.zip")
