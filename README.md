# Upscaler Pro

Cloud-based bulk image upscaler. The browser only uploads and displays; every pixel is processed on the server with Real-ESRGAN (ncnn).

## Run
    docker build -t upscaler-pro .
    docker run -p 7860:7860 upscaler-pro      # open http://localhost:7860

**Hugging Face Spaces:** create a Space with the Docker SDK, push this folder, and add `app_port: 7860` to the Space README metadata.

## Notes
- **Light theme only**: `color-scheme: light only`, no dark-mode rules.
- **No daily limits**: only per-file size (`MAX_FILE_MB`) and output-pixel (`MAX_OUTPUT_MP`) guards protect the server.
- **Queue**: images upload 3 at a time and are processed by `CONCURRENCY` workers (default 1). Progress comes from the engine's real output.
- **Free tier is CPU-only** (`REALESRGAN_GPU=-1`): expect minutes per large image. Set `REALESRGAN_GPU=0` on GPU hosts.
- **Factors**: 2X = AI 4X downsized, 4X = native, 8X = AI 4X + Lanczos 2X.
- **ZIP**: built with `zipfile` into a temporary file on disk (not RAM), streamed to the browser, then deleted. Failed images are excluded.
- **DPI**: written into JPG/PNG natively and into WEBP via EXIF.
- Batches and files are deleted after `BATCH_TTL_HOURS` or on "Clear all".
- Settings: see `.env.example`.
