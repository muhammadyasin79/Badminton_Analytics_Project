"""
FastAPI server exposing the badminton analysis pipeline as an async job API,
consumed by the Expo mobile app.

Flow:
  POST /jobs                (multipart mp4)  -> { job_id }
  GET  /jobs/{id}                            -> { status, progress, stage, ... }
  GET  /jobs/{id}/result                     -> summary JSON (when done)
  GET  /jobs/{id}/video                      -> annotated mp4 (HTTP Range ok)
  GET  /jobs/{id}/chart/{name}               -> swing_timeline | feature_dist png

GPU work is serialized through a single-worker thread pool (the pipeline can't
run two clips on one GPU in parallel anyway). Job state is in-memory; restarting
the server forgets jobs (artifacts on disk remain).
"""
import os
import sys
import uuid
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

# make sibling modules (pipeline.py, advice.py) importable when run via uvicorn
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import pipeline  # noqa: E402

JOBS_DIR = os.path.join(HERE, "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)
DEVICE = os.environ.get("BAD_DEVICE", "mps")

app = FastAPI(title="Badminton Analysis API", version="1.0.0")
# the phone hits this from a different origin; allow all for LAN/dev use
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# job_id -> state
JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=1)


def _set(job_id: str, **kw):
    with _LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(kw)


def _run_job(job_id: str, video_path: str, out_dir: str):
    _set(job_id, status="running")

    def on_progress(stage: str, frac: float):
        _set(job_id, stage=stage, progress=round(frac, 4))

    try:
        summary = pipeline.run_analysis(video_path, out_dir,
                                        progress_cb=on_progress, device=DEVICE)
        _set(job_id, status="done", progress=1.0, stage="完成", summary=summary)
    except Exception as e:  # surface failure to the client
        _set(job_id, status="error", stage="失败", error=str(e))


@app.get("/")
def root():
    return {"service": "badminton-analysis", "status": "ok", "device": DEVICE,
            "jobs": len(JOBS)}


@app.post("/jobs")
async def create_job(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith((".mp4", ".mov", ".m4v")):
        raise HTTPException(400, "请上传 mp4/mov 视频文件")
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(JOBS_DIR, job_id)
    out_dir = os.path.join(job_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    ext = os.path.splitext(file.filename)[1].lower() or ".mp4"
    video_path = os.path.join(job_dir, "input" + ext)

    # stream upload to disk (videos can be 100MB+)
    with open(video_path, "wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)
    await file.close()

    with _LOCK:
        JOBS[job_id] = {"status": "queued", "progress": 0.0, "stage": "排队中",
                        "error": None, "summary": None,
                        "filename": file.filename, "out_dir": out_dir}
    _POOL.submit(_run_job, job_id, video_path, out_dir)
    return {"job_id": job_id}


def _job_or_404(job_id: str) -> Dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job 不存在")
    return job


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = _job_or_404(job_id)
    return {"job_id": job_id, "status": job["status"], "progress": job["progress"],
            "stage": job["stage"], "error": job["error"]}


@app.get("/jobs/{job_id}/result")
def get_result(job_id: str):
    job = _job_or_404(job_id)
    if job["status"] != "done":
        raise HTTPException(409, f"任务尚未完成(当前:{job['status']})")
    return JSONResponse(job["summary"])


def _media_path(job: Dict[str, Any], fname: Optional[str]) -> str:
    if not fname:
        raise HTTPException(404, "该产物不存在")
    path = os.path.join(job["out_dir"], fname)
    if not os.path.exists(path):
        raise HTTPException(404, "文件未找到")
    return path


@app.get("/jobs/{job_id}/video")
def get_video(job_id: str):
    job = _job_or_404(job_id)
    if job["status"] != "done" or not job["summary"]:
        raise HTTPException(409, "任务尚未完成")
    path = _media_path(job, job["summary"]["media"].get("video"))
    # FileResponse handles HTTP Range -> phone can stream/seek
    return FileResponse(path, media_type="video/mp4", filename="annotated.mp4")


@app.get("/jobs/{job_id}/chart/{name}")
def get_chart(job_id: str, name: str):
    job = _job_or_404(job_id)
    if job["status"] != "done" or not job["summary"]:
        raise HTTPException(409, "任务尚未完成")
    key = {"swing_timeline": "swing_timeline", "feature_dist": "feature_dist"}.get(name)
    if key is None:
        raise HTTPException(404, "未知图表")
    path = _media_path(job, job["summary"]["media"].get(key))
    return FileResponse(path, media_type="image/png")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
