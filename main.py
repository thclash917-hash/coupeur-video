import os
import zipfile
import shutil
import subprocess
import json
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_video_duration(input_path):
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", input_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])

@app.post("/cut")
async def cut_video(
    file: UploadFile = File(...),
    segment_duration: int = Form(...),
    max_clips: int = Form(...),
    start_min: int = Form(...),
    end_min: int = Form(...)
):
    temp_dir = "temp_clips"
    
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)
    
    input_path = os.path.join(temp_dir, file.filename)
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Récupération de la durée réelle de la vidéo en secondes
    actual_video_duration = get_video_duration(input_path)

    start_sec = start_min * 60
    end_sec = min(end_min * 60, actual_video_duration)
    total_available_time = end_sec - start_sec

    if total_available_time <= 0 or start_sec >= actual_video_duration:
        shutil.rmtree(temp_dir)
        raise HTTPException(status_code=400, detail="La plage demandée dépasse la durée réelle de la vidéo.")

    if max_clips > 1:
        step = (total_available_time - segment_duration) / (max_clips - 1)
        step = max(step, segment_duration)
    else:
        step = 0

    generated_files = []

    for i in range(max_clips):
        clip_start = start_sec + (i * step)
        
        # Stop si le début du clip + la durée dépasse la fin réelle
        if clip_start + segment_duration > actual_video_duration:
            break

        output_filename = f"extrait_{i+1}.mp4"
        output_path = os.path.join(temp_dir, output_filename)

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(int(clip_start)),
            "-i", input_path,
            "-t", str(segment_duration),
            "-c", "copy",
            output_path
        ]
        
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # On ne garde le fichier que s'il est valide (> 100 Ko)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
            generated_files.append(output_path)

    if not generated_files:
        shutil.rmtree(temp_dir)
        raise HTTPException(status_code=400, detail="Impossible de générer des extraits valides sur cette plage.")

    zip_path = os.path.join(temp_dir, "extraits.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for f in generated_files:
            zipf.write(f, os.path.basename(f))

    return FileResponse(zip_path, media_type="application/zip", filename="extraits.zip")
