"""Shared scaffolding for the KNELL test suite.

Every test works in its own data directory of plain files, created
under a scratch root inside the workspace and removed afterwards.
"""

import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from knell.config import Config
from knell.registry import ensure_registry_files, seed_local_registry
from knell.store import Store

SCRATCH_ROOT = os.path.expanduser("~/workspace/knell-test-tmp")

# 2026-01-01 00:00:00 UTC, an exact day boundary, for habit arithmetic.
DAY = 1767225600.0


def make_event(store, center_hz, bandwidth_hz=100_000.0, peak=25.0, start_ts=DAY,
               duration=2.0, outline="carrier", family="unknown", run_id="test-run",
               spectrum=None, capture=None):
    """Append a synthetic event record directly to the event layer."""
    number = store.next_id("event")
    if spectrum is None:
        spectrum = {
            "carrier": [-80.0, -60.0, -80.0],
            "block": [-80.0, -62.0, -60.0, -60.0, -60.0, -62.0, -80.0, -80.0],
            "pair": [-80.0, -60.0, -80.0, -80.0, -60.0, -80.0],
            "comb": [-60.0, -80.0, -60.0, -80.0, -60.0, -80.0],
        }.get(outline, [-80.0, -60.0, -80.0])
    event = {
        "id": "E%07d" % number,
        "run_id": run_id,
        "window": 0,
        "start_ts": start_ts,
        "stop_ts": start_ts + duration,
        "duration_s": duration,
        "center_hz": center_hz,
        "bandwidth_hz": bandwidth_hz,
        "peak_db_above_floor": peak,
        "mean_db_above_floor": peak * 0.7,
        "mean_spectrum": spectrum,
        "sweeps": 1,
        "overload_coincident": False,
        "outline": outline,
        "family": family,
        "capture": capture,
        "capture_note": None,
    }
    store.append_event(event)
    return event


class KnellTestCase(unittest.TestCase):
    def setUp(self):
        os.makedirs(SCRATCH_ROOT, exist_ok=True)
        self.tmp = os.path.join(SCRATCH_ROOT, self.id().replace(".", "_"))
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.makedirs(self.tmp)
        self.store = Store(os.path.join(self.tmp, "data"))
        self.store.ensure()
        ensure_registry_files(self.store)
        seed_local_registry(self.store)
        self.config = self.make_config()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_config(self, **overrides):
        values = {
            "span_low_hz": 100_000_000.0,
            "span_high_hz": 110_000_000.0,
            "window_hz": 2_000_000.0,
            "bins_per_window": 64,
            "capture_seconds": 0.01,
            "backend": "synthetic",
        }
        values.update(overrides)
        return Config(values)
