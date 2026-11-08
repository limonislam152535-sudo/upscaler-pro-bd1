import asyncio, csv, io, os, tempfile, uuid, zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from queue_manager import DATA, QueueManager

MAX_MB = int(os.getenv("MAX_FILE_MB", "50"))
ALLOWED = {".jpg", ".jpeg", ".png", ".webp"}
FRONTEND = Path(os.getenv("FRONTEND_DIR", Path(__file__).parent.parent / "frontend"))
qm = QueueManager()


@asynccontextmanager
async def lifespan(app):
    await qm.start(); yield


app = FastAPI(title="Upscaler Pro", lifespan=lifespan)


def get_batch(bid):
    b = qm.batches.get(bid)
    if not b:
        raise HTTPException(404, "Batch not found or expired")
    return b


@app.get("/api/config")
def config():
    return {"max_file_mb": MAX_MB}


@app.post("/api/batches")
def create_batch(scale: int = Form(4), model: str = Form("quality"), fmt: str = Form("jpg", alias="format"),
                 quality: int = Form(95), dpi: int = Form(300), max_mb: int = Form(MAX_MB)):
    if scale not in (2, 4, 8) or model not in ("quality", "anime", "fast") or fmt not in ("jpg", "png", "webp") \
            or dpi not in (72, 150, 300, 600) or not 70 <= quality <= 100:
        raise HTTPException(422, "Invalid settings")
    b = qm.create({"scale": scale, "model": model, "format": fmt, "quality": quality, "dpi": dpi,
                   "max_mb": max(1, min(max_mb, MAX_MB))})
    return {"id": b.id}


@app.post("/api/batches/{bid}/images")
async def upload(bid: str, file: UploadFile = File(...), client_id: int = Form(...)):
    b = get_batch(bid)
    name = Path(file.filename or "image").name
    ext, iid = Path(name).suffix.lower(), uuid.uuid4().hex[:10]
    if ext not in ALLOWED:
        return qm.fail(b, iid, client_id, name, 0, "Unsupported format (use JPG, PNG or WEBP)").public()
    dest = DATA / bid / "in" / f"{iid}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    limit, size, too_big = b.settings["max_mb"] * 1048576, 0, False
    with dest.open("wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                too_big = True; break
            f.write(chunk)
    if too_big:
        dest.unlink(missing_ok=True)
        return qm.fail(b, iid, client_id, name, size, f"File exceeds the {b.settings['max_mb']} MB limit").public()
    return qm.add(b, iid, client_id, name, dest, size).public()


@app.get("/api/batches/{bid}")
def status(bid: str):
    return qm.status(get_batch(bid))


@app.delete("/api/batches/{bid}")
def delete(bid: str):
    qm.delete(bid); return {"ok": True}


@app.get("/api/batches/{bid}/images/{iid}/download")
def download(bid: str, iid: str):
    it = get_batch(bid).items.get(iid)
    if not it or it.status != "completed" or not it.out or not it.out.exists():
        raise HTTPException(404, "Image not ready")
    return FileResponse(it.out, filename=it.out_name)


def _build_zip(items, path):
    used = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED, allowZip64=True) as z:  # images are already compressed
        for it in items:
            name, n = it.out_name, 1
            while name.lower() in used:
                n += 1; name = f"{Path(it.out_name).stem} ({n}){Path(it.out_name).suffix}"
            used.add(name.lower()); z.write(it.out, name)


@app.get("/api/batches/{bid}/zip")
async def zip_download(bid: str):
    b = get_batch(bid)
    done = [i for i in b.items.values() if i.status == "completed" and i.out and i.out.exists()]
    if not done:
        raise HTTPException(409, "No completed images yet")
    fd, path = tempfile.mkstemp(suffix=".zip", dir=DATA); os.close(fd)
    try:
        await asyncio.to_thread(_build_zip, done, path)
    except Exception:
        os.unlink(path); raise HTTPException(500, "Could not build the ZIP archive")
    return FileResponse(path, media_type="application/zip", filename=f"upscaled_{bid}.zip",
                        background=BackgroundTask(os.unlink, path))


@app.get("/api/batches/{bid}/csv")
def csv_download(bid: str):
    b = get_batch(bid); s = b.settings
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["original_name", "output_name", "status", "original_px", "output_px", "scale", "model",
                "format", "dpi", "quality", "original_bytes", "output_bytes", "seconds", "error"])
    for i in b.items.values():
        w.writerow([i.name, i.out_name, i.status, i.in_dim, i.out_dim, f"{s['scale']}x", s["model"], s["format"],
                    s["dpi"], s["quality"], i.size, i.out_size, round(i.secs, 1), i.error])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="metadata_{bid}.csv"'})


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
