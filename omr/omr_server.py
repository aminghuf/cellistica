"""Minimal internal HTTP wrapper around the Audiveris CLI (stdlib only).

POST /convert {"job": "<32 hex>"}
    Runs Audiveris on /data/jobs/<job>/input.pdf, writing .mxl files under
    /data/jobs/<job>/omr/ and the console log to /data/jobs/<job>/omr.log.
    Responds when done: {"ok": bool, "files": [...], "returncode": int, "log_tail": str}
GET /health -> 200

Single-threaded on purpose: one Audiveris run at a time (it takes several GB of heap).
Not published outside the compose network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

AUDIVERIS = os.environ.get("AUDIVERIS_BIN", "/opt/audiveris/bin/Audiveris")
DATA = Path(os.environ.get("DATA_DIR", "/data"))
TIMEOUT = int(os.environ.get("OMR_TIMEOUT_SECONDS", "1800"))
JOB_ID = re.compile(r"^[0-9a-f]{32}$")

# Audiveris renders PDF pages at this DPI (its default) and rejects sheets whose
# staff-line gap ("interline") is too small, e.g. a phone image wrapped in a PDF.
PDF_DPI_CONSTANT = "org.audiveris.omr.image.ImageLoading.pdfResolution"
DEFAULT_PDF_DPI = 300
TARGET_INTERLINE = 18  # px; comfortably above Audiveris' minimum
MAX_SHEET_PIXELS = 20_000_000  # Audiveris refuses larger sheets
LOW_INTERLINE = re.compile(rb"too low interline value of (\d+) pixels")
LOADED_IMAGE = re.compile(rb"Loaded image #\d+ (\d+)x(\d+)")


def _run(cmd: list[str], log_path: Path) -> int:
    with open(log_path, "ab") as log:
        log.write(f"[omr] {' '.join(cmd)}\n".encode())
        log.flush()
        try:
            return subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            log.write(f"\n[omr] timed out after {TIMEOUT}s\n".encode())
            return -1


def retry_dpi(log: bytes) -> int | None:
    """Higher PDF render DPI that would lift the interline to TARGET_INTERLINE,
    or None if the failure wasn't a low-resolution one (or can't be helped)."""
    m = LOW_INTERLINE.search(log)
    if not m:
        return None
    factor = TARGET_INTERLINE / max(int(m.group(1)), 1)
    size = LOADED_IMAGE.search(log)
    if size:  # keep the re-rendered sheet under Audiveris' pixel cap
        w, h = int(size.group(1)), int(size.group(2))
        factor = min(factor, (MAX_SHEET_PIXELS / (w * h)) ** 0.5)
    dpi = int(DEFAULT_PDF_DPI * factor) // 50 * 50
    return dpi if dpi > DEFAULT_PDF_DPI else None


def run_audiveris(job: str) -> dict:
    job_dir = DATA / "jobs" / job
    src = job_dir / "input.pdf"
    out_dir = job_dir / "omr"
    out_dir.mkdir(exist_ok=True)
    log_path = job_dir / "omr.log"
    log_path.write_bytes(b"")
    base = [AUDIVERIS, "-batch", "-export", "-output", str(out_dir)]
    rc = _run([*base, "--", str(src)], log_path)
    notes: list[str] = []

    dpi = retry_dpi(log_path.read_bytes()) if rc != 0 else None
    if dpi:
        notes.append(f"The PDF's resolution was too low for OMR; re-read it at {dpi} dpi.")
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir()
        rc = _run([*base, "-constant", f"{PDF_DPI_CONSTANT}={dpi}", "--", str(src)], log_path)

    files = sorted(str(p.relative_to(job_dir)) for p in out_dir.rglob("*.mxl"))
    tail = log_path.read_bytes()[-4000:].decode("utf-8", "replace")
    return {"ok": rc == 0 and bool(files), "files": files, "returncode": rc, "log_tail": tail, "notes": notes}


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/convert":
            return self._reply(404, {"error": "not found"})
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 1024)
            job = json.loads(self.rfile.read(length) or b"{}").get("job", "")
        except (ValueError, AttributeError):
            return self._reply(400, {"error": "bad request"})
        if not isinstance(job, str) or not JOB_ID.match(job):
            return self._reply(400, {"error": "bad job id"})
        if not (DATA / "jobs" / job / "input.pdf").is_file():
            return self._reply(404, {"error": "input.pdf not found"})
        self._reply(200, run_audiveris(job))

    def log_message(self, fmt, *args):
        print("[omr]", fmt % args, flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8090"))
    print(f"[omr] listening on :{port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
