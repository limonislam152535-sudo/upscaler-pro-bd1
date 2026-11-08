"""Server-side Real-ESRGAN (ncnn) wrapper. All pixel work happens on the server."""
import asyncio, os, re
from pathlib import Path
from PIL import Image, ImageOps

BIN = os.getenv("REALESRGAN_BIN", "/opt/realesrgan/realesrgan-ncnn-vulkan")
MODELS = os.getenv("REALESRGAN_MODELS", "/opt/realesrgan/models")
GPU = os.getenv("REALESRGAN_GPU", "-1")          # -1 = CPU, 0 = first GPU
TILE = os.getenv("REALESRGAN_TILE", "200")       # tile size keeps RAM/VRAM bounded
TIMEOUT = int(os.getenv("IMAGE_TIMEOUT_SEC", "900"))
MAX_PIXELS = int(float(os.getenv("MAX_OUTPUT_MP", "120")) * 1e6)
MODEL_MAP = {"quality": "realesrgan-x4plus", "anime": "realesrgan-x4plus-anime", "fast": "realesr-animevideov3"}


def _prepare(src: Path, work: Path, scale: int):
    try:
        with Image.open(src) as im:
            im.verify()
        im = ImageOps.exif_transpose(Image.open(src))
        im.load()
    except Exception:
        raise ValueError("Corrupted or unreadable image file")
    if im.width * im.height * scale * scale > MAX_PIXELS:
        raise ValueError(f"Output would exceed {MAX_PIXELS // 1_000_000} MP; choose a lower factor")
    alpha = "A" in im.getbands() or "transparency" in im.info
    im.convert("RGBA" if alpha else "RGB").save(work, "PNG")
    return im.size


def _finalize(raw: Path, out: Path, scale: int, size, s: dict):
    fmt, q, dpi = s["format"], s["quality"], s["dpi"]
    tw, th = size[0] * scale, size[1] * scale
    with Image.open(raw) as im:
        im.load()
        if im.size != (tw, th):  # 2X = AI 4X downsized; 8X = AI 4X + Lanczos 2X
            im = im.resize((tw, th), Image.LANCZOS)
        if fmt == "jpg":
            if "A" in im.getbands():
                bg = Image.new("RGB", im.size, "white"); bg.paste(im, mask=im.getchannel("A")); im = bg
            im.convert("RGB").save(out, "JPEG", quality=q, dpi=(dpi, dpi), optimize=True, subsampling=0)
        elif fmt == "png":
            im.save(out, "PNG", dpi=(dpi, dpi))
        else:
            exif = Image.Exif(); exif[282] = float(dpi); exif[283] = float(dpi); exif[296] = 2
            im.save(out, "WEBP", quality=q, exif=exif.tobytes())
    return f"{tw}x{th}"


async def _read_progress(proc, cb):
    buf, log = "", ""
    while True:
        chunk = await proc.stderr.read(512)
        if not chunk:
            break
        buf += chunk.decode(errors="ignore")
        parts = re.split(r"[\r\n]+", buf); buf = parts.pop()
        for p in parts:
            log = (log + " " + p)[-300:]
            m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)%\s*", p)
            if m:
                cb(min(float(m[1]), 99.0))
    return log


async def process_image(src: Path, out: Path, s: dict, on_progress):
    out.parent.mkdir(parents=True, exist_ok=True)
    scale = int(s["scale"])
    work, raw = src.with_suffix(".in.png"), src.with_suffix(".out.png")
    try:
        size = await asyncio.to_thread(_prepare, src, work, scale)
        proc = await asyncio.create_subprocess_exec(
            BIN, "-i", str(work), "-o", str(raw), "-n", MODEL_MAP[s["model"]], "-s", "4",
            "-m", MODELS, "-g", GPU, "-t", TILE,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            log = await asyncio.wait_for(_read_progress(proc, on_progress), TIMEOUT)
            code = await proc.wait()
        except asyncio.TimeoutError:
            proc.kill(); raise RuntimeError("Processing timed out")
        if code != 0 or not raw.exists():
            raise RuntimeError("AI engine failed: " + log[-150:])
        out_dim = await asyncio.to_thread(_finalize, raw, out, scale, size, s)
        return f"{size[0]}x{size[1]}", out_dim
    finally:
        work.unlink(missing_ok=True); raw.unlink(missing_ok=True)
