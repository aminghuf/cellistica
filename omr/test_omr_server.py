"""Stdlib tests for the low-resolution retry logic.

    docker compose exec omr python3 /opt/test_omr_server.py -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from omr_server import retry_dpi  # noqa: E402

# Trimmed from a real failure: a 1080x1472 phone image wrapped in a PDF.
LOW_RES_LOG = b"""\
INFO  [input]                 SheetStub 1278 | Loaded image #1 1080x1472 from /data/jobs/x/input.pdf
WARN  [input]                 SheetStub 411  | input   With a too low interline value of 9 pixels,  either this sheet contains no multi-line staves,  or the picture resolution is too low (try 300 DPI).
"""


class RetryDpi(unittest.TestCase):
    def test_low_interline_doubles_resolution(self):
        self.assertEqual(retry_dpi(LOW_RES_LOG), 600)

    def test_tiny_interline_scales_further(self):
        log = LOW_RES_LOG.replace(b"value of 9 pixels", b"value of 6 pixels")
        self.assertEqual(retry_dpi(log), 900)

    def test_capped_by_audiveris_pixel_limit(self):
        # A big page can't be blown up past 20 MP: 3000x4000 -> at most ~1.29x.
        log = LOW_RES_LOG.replace(b"1080x1472", b"3000x4000")
        self.assertEqual(retry_dpi(log), 350)

    def test_no_retry_when_already_at_the_cap(self):
        log = LOW_RES_LOG.replace(b"1080x1472", b"4000x5000")
        self.assertIsNone(retry_dpi(log))

    def test_other_failures_are_not_retried(self):
        self.assertIsNone(retry_dpi(b"WARN Too large image: 21,921,216 pixels (vs 20,000,000 max)"))
        self.assertIsNone(retry_dpi(b""))


if __name__ == "__main__":
    unittest.main()
