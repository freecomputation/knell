"""Coverage accounting: a gap is recorded as a gap."""

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from knelltest import KnellTestCase

from knell.backends import (TunerBusy, acquire_tuner, release_tuner,
                            tuner_lock_path)
from knell.survey import coverage_gaps, run_survey

BINS = 64


def noise_row(window, low):
    return {"ts": 0.0, "window": window, "low_hz": low,
            "high_hz": low + 2_000_000.0, "step_hz": 31_250.0,
            "dwell_s": 0.1, "powers": [-100.0] * BINS,
            "overload": False, "backend": "replay"}


class TestCoverage(KnellTestCase):
    def test_unvisited_windows_are_gaps_with_reasons(self):
        replay_path = os.path.join(self.tmp, "rows.jsonl")
        with open(replay_path, "w", encoding="utf-8") as handle:
            for window in (0, 1):
                low = 100_000_000.0 + window * 2_000_000.0
                for _ in range(2):
                    handle.write(json.dumps(noise_row(window, low)) + "\n")
        config = self.make_config(replay_file=replay_path)
        result = run_survey(self.store, config, backend_name="replay", tiers=(1,))
        coverage = {e["window"]: e for e in result["header"]["coverage"]}
        self.assertTrue(coverage[0]["completed"])
        self.assertTrue(coverage[1]["completed"])
        for window in (2, 3, 4):
            self.assertFalse(coverage[window]["completed"])
            self.assertIn("no data", coverage[window]["note"])
        gaps, runs = coverage_gaps(self.store, config, time.time())
        self.assertEqual(runs, 1)
        self.assertEqual(gaps, [2, 3, 4])

    def test_unavailable_backend_records_a_full_gap(self):
        config = self.make_config(replay_file="")
        result = run_survey(self.store, config, backend_name="replay", tiers=(1,))
        coverage = result["header"]["coverage"]
        self.assertEqual(len(coverage), config.window_count())
        self.assertTrue(all(not e["completed"] for e in coverage))
        self.assertTrue(any("unavailable" in (e["note"] or "") for e in coverage))
        gaps, _ = coverage_gaps(self.store, config, time.time())
        self.assertEqual(gaps, list(range(config.window_count())))


class TestTunerLock(KnellTestCase):
    def test_live_holder_is_refused_and_stale_lock_is_taken_over(self):
        lock_path = tuner_lock_path(self.store)
        # A lock held by another live process is a claim KNELL yields to.
        with open(lock_path, "w", encoding="utf-8") as handle:
            handle.write(str(os.getppid()))
        with self.assertRaises(TunerBusy):
            acquire_tuner(self.store)
        # A lock left by a dead process is taken over, not obeyed forever.
        with open(lock_path, "w", encoding="utf-8") as handle:
            handle.write("999999999")
        acquire_tuner(self.store)
        release_tuner(self.store)
        self.assertFalse(os.path.isfile(lock_path))


if __name__ == "__main__":
    unittest.main()
