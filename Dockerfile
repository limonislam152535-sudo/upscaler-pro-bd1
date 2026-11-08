# =============================================================
# Upscaler Pro — Dockerfile (Hugging Face Spaces compatible)
# =============================================================
# Stage 1: Python base with system deps for image processing
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/tmp/hf \
    HOME=/tmp

# System packages required by Pillow / ffmpeg / vulkan (Real-ESRGAN ncnn)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgl1 \
        libglib2.0-0 \
        libvulkan1 \
        mesa-vulkan-drivers \
        vulkan-tools \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy backend
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

ENV FRONTEND_DIR=/app/frontend \
    MODEL_DIR=/app/backend/models \
    HOST=0.0.0.0 \
    PORT=7860

EXPOSE 7860

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:7860/api/health || exit 1

WORKDIR /app/backend
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
