# Badminton analysis backend.
#
# Build from the PROJECT ROOT (needs the analysis scripts + model file):
#   docker build -f backend/Dockerfile -t badminton-backend .
#   docker run --rm -p 8000:8000 badminton-backend
#
# This default image is CPU-only (BAD_DEVICE=cpu) and works anywhere, but YOLO
# per-frame inference is slow on CPU. For a GPU host see DEPLOY.md (swap the base
# image to an nvidia/cuda one, install the CUDA torch build, set BAD_DEVICE=cuda).
FROM python:3.12-slim

# opencv needs libGL/glib; ffmpeg is used for audio muxing + duration probe
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# deps first (better layer caching)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# analysis scripts + model + backend code (model is ~24MB)
COPY color_id_weixin.py pose_analytics_weixin.py yolov8s-pose.pt /app/
COPY backend/ /app/backend/

ENV BAD_DEVICE=cpu \
    PYTHONUNBUFFERED=1

EXPOSE 8000
WORKDIR /app/backend
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
