"""API round trip with the fixture (no OMR: MusicXML input skips the omr service)."""

import time
import xml.etree.ElementTree as ET

import pytest

from fastapi.testclient import TestClient

from cello.main import app  # DATA_DIR is pointed at a temp dir by conftest


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _wait(client, job_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def _upload(client, path, name=None):
    with open(path, "rb") as f:
        return client.post("/convert", files={"file": (name or path.name, f, "application/octet-stream")})


def test_full_round_trip(client, fixtures):
    r = _upload(client, fixtures["sample"])
    assert r.status_code == 202
    job = _wait(client, r.json()["id"])
    assert job["status"] == "done", job
    assert job["selected_part"] == 0
    for mode in ("solfege", "fingering"):
        r = client.get(f"/jobs/{job['id']}/musicxml", params={"mode": mode})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/vnd.recordare.musicxml+xml")
        root = ET.fromstring(r.content)
        assert root.tag == "score-partwise"
        tag = "lyric" if mode == "solfege" else "fingering"
        assert root.find(f".//{tag}") is not None


def test_download_header(client, fixtures):
    job = _wait(client, _upload(client, fixtures["sample"]).json()["id"])
    r = client.get(f"/jobs/{job['id']}/musicxml", params={"mode": "fingering", "download": 1})
    assert r.headers["content-disposition"].startswith("attachment")
    assert "sample.fingering.musicxml" in r.headers["content-disposition"]


def test_picks_cello_and_part_override(client, fixtures):
    job = _wait(client, _upload(client, fixtures["duet"]).json()["id"])
    assert job["selected_part"] == 1  # the cello, even though it is listed second
    assert [p["is_cello"] for p in job["parts"]] == [False, True]
    r = client.get(f"/jobs/{job['id']}/musicxml", params={"mode": "solfege", "part": "0"})
    assert r.status_code == 200 and r.headers["x-part-index"] == "0"
    r = client.get(f"/jobs/{job['id']}/musicxml", params={"mode": "solfege", "part": "violin"})
    assert r.headers["x-part-index"] == "0"
    assert client.get(f"/jobs/{job['id']}/musicxml", params={"part": "9"}).status_code == 400


def test_lowest_part_when_no_cello(client, fixtures):
    job = _wait(client, _upload(client, fixtures["unnamed_parts"]).json()["id"])
    assert job["selected_part"] == 1


def test_rejects_wrong_type(client, fixtures):
    r = client.post("/convert", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    r = client.post("/convert", files={"file": ("fake.pdf", b"<xml/>", "application/pdf")})
    assert r.status_code == 415


def test_rejects_oversize(client):
    big = b"%PDF-" + b"0" * (31 * 1024 * 1024)
    r = client.post("/convert", files={"file": ("big.pdf", big, "application/pdf")})
    assert r.status_code == 413


def test_bad_mode_and_unknown_job(client, fixtures):
    job = _wait(client, _upload(client, fixtures["sample"]).json()["id"])
    assert client.get(f"/jobs/{job['id']}/musicxml", params={"mode": "tab"}).status_code == 422
    assert client.get("/jobs/nope").status_code == 404
