from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VideoRequest(BaseModel):
    url: str
    segment_duration: int
    start_min: int
    end_min: int

@app.get("/")
def home():
    return {"status": "API en ligne"}

@app.post("/cut")
def cut_video(data: VideoRequest):
    return {
        "status": "success",
        "message": f"Demande reçue pour {data.url} ({data.segment_duration}s par extrait)."
    }
