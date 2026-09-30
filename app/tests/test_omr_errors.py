"""Audiveris failures turn into advice a person can act on."""

from cello.jobs import Job, explain_omr_failure


def _job_with_log(tmp_path, monkeypatch, text):
    monkeypatch.setattr(Job, "dir", property(lambda self: tmp_path))
    (tmp_path / "omr.log").write_text(text)
    return Job(id="x", filename="part.pdf", kind="pdf")


def test_low_resolution(tmp_path, monkeypatch):
    job = _job_with_log(tmp_path, monkeypatch, "WARN ... With a too low interline value of 9 pixels, either ...")
    msg = explain_omr_failure(job, 1)
    assert "resolution is too low" in msg and "9 px" in msg and "300 dpi" in msg


def test_last_attempt_wins(tmp_path, monkeypatch):
    log = "too low interline value of 9 pixels\n[omr] retry\ntoo low interline value of 7 pixels\n"
    assert "7 px" in explain_omr_failure(_job_with_log(tmp_path, monkeypatch, log), 1)


def test_too_large(tmp_path, monkeypatch):
    job = _job_with_log(tmp_path, monkeypatch, "WARN Too large image: 21,921,216 pixels (vs 20,000,000 max)\nCreated scores: []")
    assert "21,921,216" in explain_omr_failure(job, 1)


def test_unknown_failure(tmp_path, monkeypatch):
    job = _job_with_log(tmp_path, monkeypatch, "something else entirely")
    assert "exit 3" in explain_omr_failure(job, 3)
