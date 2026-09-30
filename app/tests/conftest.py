from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Job storage for the API tests: always a throwaway dir (never the live /data volume,
# which JobStore.reset_storage() would wipe). Must be set before cello.jobs is imported.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="cello-test-")

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from cello.config import load_weights  # noqa: E402
from tests.make_fixtures import FIXTURES, write_all  # noqa: E402


@pytest.fixture(scope="session")
def fixtures() -> dict[str, Path]:
    """Fixture files on disk; regenerated if missing so tests go through real MusicXML."""
    paths = {p.stem: p for p in FIXTURES.glob("*.musicxml")}
    from tests.make_fixtures import ALL

    if set(ALL) - set(paths):
        paths = write_all()
    return paths


@pytest.fixture(scope="session")
def weights():
    return load_weights(APP_DIR / "fingering.toml")
