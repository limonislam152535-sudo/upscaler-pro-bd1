# Upscaler Pro

Professional, cloud-based AI image upscaling web application. All upscaling
runs on the server; the browser only uploads and downloads.

- **Light theme only** — pure white background, soft grey-blue cards, `#635BFF` accent.
- **No daily limits** — process as many images as the server can handle.
- **Real-ESRGAN** when available, with a high-quality Lanczos fallback so the
  app always works on CPU-only hosts.
- **Bulk upload** (200+ images per batch), drag & drop, paste from clipboard.
- **Live dashboard** with real per-image progress (no fake bars).
- **Reliable ZIP download** of all completed images, plus a metadata CSV.

---

## Tech stack

| Layer    | Choice                                  |
|----------|------------------------------------------|
| Frontend | HTML5 · Vanilla CSS · Vanilla ES6+ JS   |
| Backend  | Python 3.11 · FastAPI · uvicorn          |
| AI       | Real-ESRGAN (PyTorch) or Pillow Lanczos  |
| Archive  | Native Python `zipfile` + `io.BytesIO`   |
| Deploy   | Docker (Hugging Face Spaces compatible)  |

---

## Project structure

```
upscaler-pro/
├── frontend/
│   ├── index.html
│   ├── css/style.css
│   └── js/app.js
├── backend/
│   ├── main.py            # FastAPI app, routes, SSE stream
│   ├── upscaler.py        # Real-ESRGAN integration + fallback
│   ├── queue_manager.py   # Async job queue + ZIP/CSV builders
│   └── requirements.txt
├── Dockerfile
├── README.md
└── .env.example
```

---

## Run locally (without Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd .. && python backend/main.py
# → open http://localhost:7860
```

If `torch` + `realesrgan` are **not** installed, the server automatically
falls back to high-quality Pillow Lanczos upscaling with a mild unsharp mask.
Everything else (queue, dashboard, ZIP, CSV) works identically.

### Enabling Real-ESRGAN (optional, GPU recommended)

1. `pip install torch realesrgan basicsr numpy` (CPU build is fine; CUDA build
   is much faster).
2. Download the model weights:
   ```
   mkdir -p backend/models
   curl -L -o backend/models/RealESRGAN_x4plus.pth \
     https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth
   ```
3. Restart the server. The dashboard's engine pill will switch from
   "Lanczos (CPU fallback)" to "Real-ESRGAN".

---

## Run with Docker

```bash
docker build -t upscaler-pro .
docker run -p 7860:7860 --env-file .env upscaler-pro
```

For Hugging Face Spaces, push this repo to a Space with the **Docker SDK**.
The Dockerfile already exposes port 7860 and serves the FastAPI app + static
frontend from the same container.

---

## API summary

| Method | Path                                         | Purpose                              |
|--------|----------------------------------------------|--------------------------------------|
| GET    | `/api/health`                                | Health check                         |
| POST   | `/api/batches`                               | Create a batch (multipart settings)  |
| POST   | `/api/batches/{id}/images`                   | Upload images (multipart files)      |
| POST   | `/api/batches/{id}/start`                    | Start the queue                      |
| POST   | `/api/batches/{id}/cancel`                   | Cancel pending/processing            |
| DELETE | `/api/batches/{id}`                          | Delete the batch                     |
| GET    | `/api/batches/{id}`                          | Snapshot                             |
| GET    | `/api/batches/{id}/stream`                   | Server-Sent Events live updates      |
| GET    | `/api/batches/{id}/jobs/{job}/download`      | Single image download                |
| GET    | `/api/batches/{id}/zip`                       | ZIP of all completed images          |
| GET    | `/api/batches/{id}/csv`                       | Metadata CSV                         |

Interactive docs: `http://localhost:7860/api/docs`.

---

## Settings panel

- **Upscale factor**: 2X · 4X · 8X
- **Output format**: PNG · JPEG · WEBP
- **JPEG/WEBP quality**: 70–100
- **DPI**: 72 · 150 · 300 · 600 (written into image metadata)
- **Max upload size**: 1–200 MB (server-enforced, configurable via `MAX_UPLOAD_MB`)

---

## How the ZIP stays reliable

- Built in a worker thread (via `asyncio.run_in_executor`) so the event loop
  never blocks.
- `zipfile.ZipFile(..., ZIP_DEFLATED, compresslevel=6)` writes directly into
  an in-memory `BytesIO`. Memory usage is bounded by total output size; for
  very large batches, increase container RAM rather than changing this code.
- Failed and cancelled jobs are skipped automatically.
- Duplicate output filenames are de-duplicated by prefixing `_`.
- The response carries `Content-Length`, `Content-Disposition`, and
  `X-Content-Type-Options: nosniff` so browsers always trigger a clean
  download rather than rendering.

---

## Error handling

- Unsupported file types and oversize files are rejected at upload time with
  a clear per-file reason returned to the UI.
- A failed image (corrupt EXIF, decode error, OOM) is marked `failed` but the
  queue continues with the next image.
- The dashboard surfaces the error message inline per row.

---

## License

MIT — use freely for personal and commercial projects.
