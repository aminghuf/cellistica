"""FastAPI entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .jobs import MODES, JobStore
from .score import PartSelectionError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_MB", "30")) * 1024 * 1024
STATIC = Path(__file__).resolve().parent.parent / "static"

# extension -> (job kind, accepted leading bytes)
ACCEPTED = {
    ".pdf": ("pdf", (b"%PDF-",)),
    ".mxl": ("mxl", (b"PK\x03\x04",)),
    ".musicxml": ("musicxml", (b"<", b"\xef\xbb\xbf<")),
    ".xml": ("musicxml", (b"<", b"\xef\xbb\xbf<")),
    ".mid": ("midi", (b"MThd",)),
    ".midi": ("midi", (b"MThd",)),
}
MUSICXML_TYPE = "application/vnd.recordare.musicxml+xml"


class BodyLimit:
    """Rejects request bodies over MAX_UPLOAD, whether or not Content-Length is sent."""

    def __init__(self, app, limit: int) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            return await _too_large(send, self.limit)
        seen, rejected = 0, False

        async def counted():
            nonlocal seen, rejected
            if rejected:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.limit:
                    # Answer now and tell the app the client went away.
                    rejected = True
                    await _too_large(send, self.limit)
                    return {"type": "http.disconnect"}
            return msg

        async def guarded_send(msg):
            if not rejected:
                await send(msg)

        try:
            await self.app(scope, counted, guarded_send)
        except Exception:
            if not rejected:
                raise


async def _too_large(send, limit: int) -> None:
    resp = JSONResponse({"detail": f"file too large (max {limit // 1024 // 1024} MB)"}, status_code=413)
    await resp({"type": "http"}, None, send)


store = JobStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.reset_storage()
    tasks = [asyncio.create_task(store.run_worker()), asyncio.create_task(store.run_janitor())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="cello-reader", lifespan=lifespan)


@app.post("/convert", status_code=202)
async def convert(file: UploadFile):
    name = Path(file.filename or "upload").name
    ext = Path(name).suffix.lower()
    if ext not in ACCEPTED:
        raise HTTPException(415, f"unsupported file type {ext or '(none)'}; use {', '.join(ACCEPTED)}")
    kind, magics = ACCEPTED[ext]
    head = await file.read(8)
    if not head.startswith(magics):
        raise HTTPException(415, f"file content does not look like {ext}")

    job = store.new_job(name, kind)
    dest = job.dir / f"input.{kind}"
    with open(dest, "wb") as f:
        f.write(head)
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    store.enqueue(job)
    return {"id": job.id, "status": job.status}


def _job(job_id: str):
    job = store.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "no such job")
    return job


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    return store.public(_job(job_id))


@app.get("/jobs/{job_id}/musicxml")
async def get_musicxml(
    job_id: str,
    mode: str = Query("solfege", pattern="^(solfege|fingering)$"),
    part: str | None = Query(None, max_length=100, description="0-based index or part-name substring"),
    download: bool = False,
):
    job = _job(job_id)
    if job.status != "done":
        raise HTTPException(409, f"job is {job.status}")
    assert mode in MODES
    try:
        path, idx = await asyncio.to_thread(store.annotated_path, job, mode, part)
    except PartSelectionError as e:
        raise HTTPException(400, str(e)) from e
    stem = Path(job.filename).stem or "score"
    headers = {"X-Part-Index": str(idx)}
    return FileResponse(
        path,
        media_type=MUSICXML_TYPE,
        headers=headers,
        filename=f"{stem}.{mode}.musicxml" if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

# Outermost: enforce the upload cap before anything buffers the body.
app = BodyLimit(app, MAX_UPLOAD)  # type: ignore[assignment]
