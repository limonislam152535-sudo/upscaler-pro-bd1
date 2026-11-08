"""In-memory batch registry + background worker queue (conservative concurrency)."""
import asyncio, os, shutil, time, uuid
from dataclasses import dataclass, field
from pathlib import Path
from upscaler import process_image

DATA = Path(os.getenv("DATA_DIR", "/tmp/upscaler"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "1"))
TTL = int(float(os.getenv("BATCH_TTL_HOURS", "6")) * 3600)


@dataclass
class Item:
    id: str; client_id: int; name: str; src: Path; size: int
    status: str = "pending"; progress: float = 0.0; error: str = ""
    out: Path | None = None; out_name: str = ""; in_dim: str = ""; out_dim: str = ""
    secs: float = 0.0; out_size: int = 0

    def public(self):
        return {"id": self.id, "client_id": self.client_id, "status": self.status,
                "progress": round(self.progress, 1), "error": self.error}


@dataclass
class Batch:
    id: str; settings: dict
    items: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    busy: float = 0.0


class QueueManager:
    def __init__(self):
        self.batches: dict[str, Batch] = {}
        self.q: asyncio.Queue = asyncio.Queue()

    async def start(self):
        DATA.mkdir(parents=True, exist_ok=True)
        for _ in range(CONCURRENCY):
            asyncio.create_task(self._worker())
        asyncio.create_task(self._janitor())

    def create(self, settings: dict) -> Batch:
        b = Batch(uuid.uuid4().hex[:12], settings); self.batches[b.id] = b
        return b

    def add(self, b: Batch, iid, client_id, name, src, size) -> Item:
        it = Item(iid, client_id, name, src, size); b.items[iid] = it
        self.q.put_nowait((b, it)); return it

    def fail(self, b: Batch, iid, client_id, name, size, msg) -> Item:
        it = Item(iid, client_id, name, Path(), size, status="failed", error=msg)
        b.items[iid] = it; return it

    def delete(self, bid):
        if self.batches.pop(bid, None):
            shutil.rmtree(DATA / bid, ignore_errors=True)

    def status(self, b: Batch):
        its = list(b.items.values())
        n = lambda s: sum(i.status == s for i in its)
        done = n("completed") + n("failed")
        avg = b.busy / done if done else None
        left = n("pending") + n("processing")
        return {
            "counts": {"pending": n("pending"), "processing": n("processing"),
                       "completed": n("completed"), "failed": n("failed")},
            "current": [i.name for i in its if i.status == "processing"],
            "speed_ipm": round(60 * CONCURRENCY / avg, 2) if avg else None,
            "eta_sec": round(left * avg / CONCURRENCY) if avg else None,
            "items": [i.public() for i in its],
        }

    async def _worker(self):
        while True:
            b, it = await self.q.get()
            try:
                if b.id not in self.batches:
                    continue
                it.status = "processing"; t = time.time()
                ext = b.settings["format"]
                it.out_name = f"{Path(it.name).stem}.{ext}"
                out = DATA / b.id / "out" / f"{it.id}.{ext}"
                try:
                    it.in_dim, it.out_dim = await process_image(
                        it.src, out, b.settings, lambda p: setattr(it, "progress", p))
                    it.out, it.out_size = out, out.stat().st_size
                    it.status, it.progress = "completed", 100.0
                except Exception as e:
                    it.status, it.error = "failed", (str(e) or "Unknown error")[:300]
                it.secs = time.time() - t; b.busy += it.secs
                it.src.unlink(missing_ok=True)
            except Exception as e:  # never let the worker die
                it.status, it.error = "failed", str(e)[:300]
            finally:
                self.q.task_done()

    async def _janitor(self):
        while True:
            await asyncio.sleep(600)
            for bid, b in list(self.batches.items()):
                if time.time() - b.created > TTL:
                    self.delete(bid)
