"""In-process job queue: one asyncio worker, blocking steps run in a thread.

Job metadata lives in memory; files live under $DATA_DIR/jobs/<id>/ on the
volume shared with the omr container. A restart forgets jobs (and removes their
files on startup) - fine for a personal tool.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import threading
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import score as sc
from .config import load_weights

log = logging.getLogger("cello.jobs")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
OMR_URL = os.environ.get("OMR_URL", "http://omr:8090")
OMR_TIMEOUT = int(os.environ.get("OMR_TIMEOUT_SECONDS", "1800"))
JOB_TTL = float(os.environ.get("JOB_TTL_HOURS", "24")) * 3600

MODES = ("solfege", "fingering")


@dataclass
class Job:
    id: str
    filename: str
    kind: str  # pdf | musicxml | mxl | midi
    status: str = "queued"  # queued | omr | annotating | done | error
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    error: str | None = None
    messages: list[str] = field(default_factory=list)
    parts: list[dict] = field(default_factory=list)
    selected_part: int | None = None
    source: str | None = None  # score file (relative to job dir) used for annotation
    omr_log_tail: str | None = None

    @property
    def dir(self) -> Path:
        return DATA_DIR / "jobs" / self.id


class JobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._order: list[str] = []  # queued ids, for queue position
        self._render_lock = threading.Lock()

    # --- lifecycle -----------------------------------------------------------

    def reset_storage(self) -> None:
        root = DATA_DIR / "jobs"
        if root.exists():
            for d in root.iterdir():
                shutil.rmtree(d, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)

    async def run_worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            if job_id in self._order:
                self._order.remove(job_id)
            job = self.jobs.get(job_id)
            if job is None:
                continue
            try:
                await asyncio.to_thread(self._process, job)
            except Exception as e:  # noqa: BLE001 - report anything to the user
                log.exception("job %s failed", job.id)
                job.status, job.error = "error", str(e) or e.__class__.__name__
            finally:
                job.finished = time.time()

    async def run_janitor(self) -> None:
        while True:
            await asyncio.sleep(3600)
            cutoff = time.time() - JOB_TTL
            for job in list(self.jobs.values()):
                if job.finished and job.finished < cutoff:
                    shutil.rmtree(job.dir, ignore_errors=True)
                    self.jobs.pop(job.id, None)

    # --- API helpers ---------------------------------------------------------

    def new_job(self, filename: str, kind: str) -> Job:
        job = Job(id=uuid.uuid4().hex, filename=filename, kind=kind)
        job.dir.mkdir(parents=True)
        self.jobs[job.id] = job
        return job

    def enqueue(self, job: Job) -> None:
        self._order.append(job.id)
        self.queue.put_nowait(job.id)

    def public(self, job: Job) -> dict:
        d = asdict(job)
        d.pop("source")
        now = job.finished or time.time()
        d["elapsed_seconds"] = round(now - (job.started or job.created), 1)
        d["queue_position"] = self._order.index(job.id) + 1 if job.id in self._order else 0
        if job.status == "omr":
            d["omr_progress"] = omr_progress(job)
        return d

    # --- pipeline ------------------------------------------------------------

    def _process(self, job: Job) -> None:
        job.started = time.time()
        if job.kind == "pdf":
            job.status = "omr"
            job.source = self._omr(job)
        else:
            job.source = f"input.{job.kind}"
        job.status = "annotating"
        score = sc.load(job.dir / job.source)
        job.parts = sc.describe_parts(score)
        job.selected_part = sc.choose_part(score)
        if not any(p["notes"] for p in job.parts):
            raise ValueError("no notes found in the score")
        for mode in MODES:
            self._render(job, score, mode, job.selected_part)
        job.status = "done"

    def _omr(self, job: Job) -> str:
        req = urllib.request.Request(
            f"{OMR_URL}/convert",
            data=json.dumps({"job": job.id}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=OMR_TIMEOUT + 60) as r:
            res = json.load(r)
        job.omr_log_tail = res.get("log_tail")
        job.messages.extend(res.get("notes", []))
        if not res.get("ok"):
            raise RuntimeError(explain_omr_failure(job, res.get("returncode")))
        files = res["files"]
        if len(files) > 1:
            job.messages.append(
                f"Audiveris found {len(files)} movements; showing the first ({Path(files[0]).name})."
            )
        return files[0]

    def _render(self, job: Job, score, mode: str, part: int) -> Path:
        out = job.dir / f"{mode}-p{part}.musicxml"
        if not out.exists():
            annotated = sc.annotate(score, part, mode, load_weights())
            tmp = out.with_suffix(".tmp")
            tmp.write_bytes(sc.to_musicxml(annotated))
            tmp.replace(out)
        return out

    def annotated_path(self, job: Job, mode: str, part_override: str | None) -> tuple[Path, int]:
        """Cached annotated file; renders on demand for a non-default part."""
        if part_override in (None, "") and job.selected_part is not None:
            out = job.dir / f"{mode}-p{job.selected_part}.musicxml"
            if out.exists():
                return out, job.selected_part
        with self._render_lock:
            score = sc.load(job.dir / job.source)
            part = sc.choose_part(score, part_override)
            return self._render(job, score, mode, part), part


# Known Audiveris failure signatures -> advice a person can act on.
_OMR_FAILURES = [
    (
        re.compile(r"too low interline value of (\d+) pixels"),
        "The page resolution is too low to read (staff lines only {0} px apart). "
        "Export or scan the page at 300 dpi or more and try again.",
    ),
    (
        re.compile(r"Too large image: ([\d,]+) pixels"),
        "The page image is too large for OMR ({0} pixels, limit 20,000,000). "
        "Export it at a lower resolution (300 dpi is plenty).",
    ),
    (
        re.compile(r"Created scores: \[\]"),
        "Audiveris found no music staves on the page. Is this a scan of sheet music?",
    ),
]


def explain_omr_failure(job: Job, returncode) -> str:
    try:
        log = (job.dir / "omr.log").read_text("utf-8", "replace")
    except FileNotFoundError:
        log = job.omr_log_tail or ""
    for pattern, advice in _OMR_FAILURES:
        found = pattern.findall(log)
        if found:
            return advice.format(found[-1])  # the last attempt is the one that counts
    return f"Audiveris could not read this PDF (exit {returncode}). Details below."


_SHEET = re.compile(r"\[[^\]]*?#(\d+)\]")


def omr_progress(job: Job) -> dict | None:
    """Best-effort: highest sheet number Audiveris has logged so far."""
    path = job.dir / "omr.log"
    try:
        text = path.read_bytes()[-200_000:].decode("utf-8", "replace")
    except FileNotFoundError:
        return None
    sheets = [int(m) for m in _SHEET.findall(text)]
    last = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")
    return {"sheet": max(sheets) if sheets else None, "last_line": last[-200:]}
