FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvulkan1 mesa-vulkan-drivers libgomp1 unzip curl ca-certificates && rm -rf /var/lib/apt/lists/*
# Real-ESRGAN ncnn binary + models (runs on CPU with -g -1, or on a GPU if the host exposes Vulkan)
RUN curl -fsSL -o /tmp/re.zip https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip \
 && unzip -q /tmp/re.zip -d /tmp/re \
 && d="$(dirname "$(find /tmp/re -name realesrgan-ncnn-vulkan -type f | head -1)")" \
 && mv "$d" /opt/realesrgan && chmod +x /opt/realesrgan/realesrgan-ncnn-vulkan && rm -rf /tmp/re /tmp/re.zip
RUN useradd -m -u 1000 app
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend
RUN mkdir -p /tmp/upscaler && chown -R app /app /tmp/upscaler
USER app
ENV PORT=7860 DATA_DIR=/tmp/upscaler
EXPOSE 7860
CMD ["sh", "-c", "cd backend && uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
