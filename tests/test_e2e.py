"""End to end on the synthetic sky: survey, silence, census, report, page.

Two surveys and a silence run over the full span with the standard
scenario, at fixed start times so the run is deterministic. Every
judgment path the design defines is exercised: a nulling on full
criteria, a near match kept with its note, an unknown standing
unexplained, a self spur artifacted by the portrait, an overload
phantom artifacted by its maker, and a single weak toll standing as an
insufficient record.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from knelltest import DAY, KnellTestCase

from knell import (ARTIFACT, IDENTIFIED, INSUFFICIENT_RECORD as INSUFFICIENT,
                   UNEXPLAINED)
from knell.report import build_report, render_page
from knell.survey import run_silence, run_survey


def cluster_at(store, freq_hz, slack=400_000.0):
    for cluster in store.clusters():
        if cluster.get("absorbed_by"):
            continue
        if abs(cluster["features"].get("center_hz", 0.0) - freq_hz) <= slack:
            return cluster
    return None


class TestEndToEnd(KnellTestCase):
    def test_full_pipeline(self):
        config = self.make_config(span_low_hz=500_000.0,
                                  span_high_hz=1_750_000_000.0)
        run_survey(self.store, config, tiers=(1, 2), ts_start=DAY)
        run_survey(self.store, config, tiers=(1, 2), ts_start=DAY + 86400)

        adsb = cluster_at(self.store, 1_090_000_000.0, slack=5_000_000.0)
        self.assertIsNotNone(adsb)
        self.assertEqual(adsb["standing"], IDENTIFIED)
        self.assertEqual(adsb["resolution"]["entry_id"], "seed-adsb-1090")

        wwv = cluster_at(self.store, 15_000_000.0)
        self.assertIsNotNone(wwv)
        self.assertEqual(wwv["standing"], IDENTIFIED)
        self.assertEqual(wwv["resolution"]["entry_id"], "seed-wwv-15")

        apt = cluster_at(self.store, 137_620_000.0)
        self.assertIsNotNone(apt)
        self.assertEqual(apt["standing"], UNEXPLAINED)
        self.assertEqual(len(apt["near_matches"]), 1)
        self.assertEqual(apt["near_matches"][0]["failed"], ["bandwidth"])

        unknown = cluster_at(self.store, 433_920_000.0)
        self.assertIsNotNone(unknown)
        self.assertEqual(unknown["standing"], UNEXPLAINED)
        self.assertEqual(unknown["near_matches"], [])

        strong = cluster_at(self.store, 101_100_000.0)
        self.assertIsNotNone(strong)
        self.assertEqual(strong["standing"], UNEXPLAINED)

        phantom = cluster_at(self.store, 202_200_000.0)
        self.assertIsNotNone(phantom)
        self.assertEqual(phantom["standing"], ARTIFACT)
        self.assertIn("overload phantom", phantom["cause"])

        blip = cluster_at(self.store, 902_400_000.0)
        self.assertIsNotNone(blip)
        self.assertEqual(blip["standing"], INSUFFICIENT)

        spur = cluster_at(self.store, 28_800_000.0)
        self.assertIsNotNone(spur)
        self.assertEqual(spur["standing"], UNEXPLAINED)

        result = run_silence(self.store, config, ts_start=DAY + 2 * 86400)
        centers = [s["center_hz"] for s in result["portrait"]["signals"]]
        self.assertTrue(any(abs(c - 28_800_000.0) < 500_000 for c in centers))
        spur = cluster_at(self.store, 28_800_000.0)
        self.assertEqual(spur["standing"], ARTIFACT)
        self.assertEqual(spur["cause"], "self")

        report = build_report(self.store, config, DAY + 3 * 86400, period_days=7)
        self.assertTrue(os.path.isfile(
            self.store.path("reviews", report["file"])))
        page = render_page(self.store, config, DAY + 3 * 86400)
        self.assertTrue(os.path.isfile(page))
        with open(page, "r", encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn("UNEXPLAINED", html)
        self.assertNotIn("<script", html)

        with open(self.store.path("census", "census.json"),
                  "r", encoding="utf-8") as handle:
            doc = json.load(handle)
        self.assertIn("UNEXPLAINED", doc["active"])
        self.assertTrue(os.path.isfile(self.store.path("census", "census.txt")))


if __name__ == "__main__":
    unittest.main()
