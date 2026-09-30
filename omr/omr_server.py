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
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

AUDIVERIS = os.environ.get("AUDIVERIS_BIN", "/opt/audiveris/bin/Audiveris")
DATA = Path(os.environ.get("DATA_DIR", "/data"))
TIMEOUT = int(os.environ.get("OMR_TIMEOUT_SECONDS", "1800"))
JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def run_audiveris(job: str) -> dict:
    job_dir = DATA / "jobs" / job
    src = job_dir / "input.pdf"
    out_dir = job_dir / "omr"
    out_dir.mkdir(exist_ok=True)
    cmd = [AUDIVERIS, "-batch", "-export", "-output", str(out_dir), "--", str(src)]
    with open(job_dir / "omr.log", "wb") as log:
        try:
            rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            rc = -1
            log.write(f"\n[omr] timed out after {TIMEOUT}s\n".encode())
    files = sorted(str(p.relative_to(job_dir)) for p in out_dir.rglob("*.mxl"))
    tail = (job_dir / "omr.log").read_bytes()[-4000:].decode("utf-8", "replace")
    return {"ok": rc == 0 and bool(files), "files": files, "returncode": rc, "log_tail": tail}


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
