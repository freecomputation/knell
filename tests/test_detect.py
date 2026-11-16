"""Detection against a rolling baseline, on synthetic spectrum rows."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from knelltest import KnellTestCase

from knell.config import Config
from knell.detect import BaselineTracker, Detector

LOW = 100_000_000.0
STEP = 31_250.0
BINS = 64


def row(ts, hot=None, dwell=0.1, window=0):
    powers = [-100.0] * BINS
    if hot:
        for b in hot:
            powers[b] = -60.0
    return {"ts": ts, "window": window, "low_hz": LOW, "high_hz": LOW + BINS * STEP,
            "step_hz": STEP, "dwell_s": dwell, "powers": powers, "overload": False,
            "backend": "synthetic"}


class TestBaseline(KnellTestCase):
    def test_baseline_is_robust_to_signals(self):
        tracker = BaselineTracker(history=9)
        for i in range(9):
            tracker.observe(row(float(i)))
        spike = row(9.0, hot=[10])
        tracker.observe(spike)
        # One hot sweep in ten must not raise the floor it is judged by.
        self.assertAlmostEqual(tracker.baseline_for(0, 10, -100.0), -100.0, places=5)
        self.assertAlmostEqual(tracker.baseline_for(0, 11, -100.0), -100.0, places=5)

    def test_seeded_window_is_warm_at_once(self):
        tracker = BaselineTracker(history=9, seed_medians={"0:10": -101.0})
        self.assertTrue(tracker.warm(0, BINS))
        fresh = BaselineTracker(history=9)
        self.assertFalse(fresh.warm(0, BINS))


class TestDetection(KnellTestCase):
    def make_detector(self):
        config = Config({"open_margin_db": 6.0, "close_margin_db": 3.0,
                         "baseline_history": 9})
        return Detector(config)

    def test_event_opens_and_closes(self):
        detector = self.make_detector()
        closed = []
        ts = 0.0
        for _ in range(3):  # warm-up noise
            closed += detector.feed(row(ts)); ts += 0.1
        for _ in range(3):  # signal on bins 10-13
            closed += detector.feed(row(ts, hot=[10, 11, 12, 13])); ts += 0.1
        closed += detector.feed(row(ts))  # falls back: closes
        self.assertEqual(len(closed), 1)
        event = closed[0]
        self.assertAlmostEqual(event["bandwidth_hz"], 4 * STEP, places=1)
        self.assertAlmostEqual(event["peak_db_above_floor"], 40.0, places=1)
        expected_center = LOW + (10 + 1.5 + 0.5) * STEP
        self.assertAlmostEqual(event["center_hz"], expected_center, places=1)
        self.assertEqual(event["sweeps"], 3)

    def test_pure_noise_detects_nothing(self):
        detector = self.make_detector()
        closed = []
        for i in range(12):
            closed += detector.feed(row(i * 0.1))
        closed += detector.flush({0: row(99.0)})
        self.assertEqual(closed, [])

    def test_constant_narrowband_signal_is_detected(self):
        # A carrier constant in two bins of sixty-four is present in
        # every sweep, so its temporal baseline absorbs its own level -
        # but the window's own floor anchors the judgment, and the
        # carrier is heard. This is the case of every constant narrow
        # service the census exists to write off.
        detector = self.make_detector()
        closed = []
        for i in range(8):
            closed += detector.feed(row(i * 0.1, hot=[20, 21]))
        closed += detector.flush({0: row(99.0, hot=[20, 21])})
        self.assertEqual(len(closed), 1)
        self.assertAlmostEqual(closed[0]["peak_db_above_floor"], 40.0, delta=3.5)

    def test_full_window_constant_raise_is_absorbed(self):
        # A raise of the whole window at once, constant in every bin,
        # is a change of floor rather than a signal: temporal and
        # spatial baselines agree on it, and nothing is detected. This
        # is the honest limit of energy detection.
        detector = self.make_detector()
        closed = []
        for i in range(14):
            hot_row = row(i * 0.1)
            hot_row["powers"] = [-60.0] * BINS
            closed += detector.feed(hot_row)
        last = row(99.0)
        last["powers"] = [-60.0] * BINS
        closed += detector.flush({0: last})
        self.assertEqual(closed, [])


if __name__ == "__main__":
    unittest.main()
