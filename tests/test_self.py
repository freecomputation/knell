"""The self-portrait: artifact path, overload phantoms, the silence run."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from knelltest import DAY, KnellTestCase, make_event

from knell import ARTIFACT, UNEXPLAINED, census as census_mod
from knell import cluster as cluster_mod
from knell.survey import run_silence, run_survey


def build(store, config, tolls=3, **kwargs):
    for i in range(tolls):
        make_event(store, start_ts=DAY + i * 600, **kwargs)
    cluster_mod.assign_events(store, config, DAY + 10_000)
    clusters = [c for c in store.clusters() if not c.get("absorbed_by")]
    assert len(clusters) == 1, clusters
    return clusters[0]


class TestPortrait(KnellTestCase):
    def test_portrait_marks_self_signals_as_artifacts(self):
        cluster = build(self.store, self.config, center_hz=104_000_000.0)
        self.store.save_portrait({
            "id": "P-test", "ts": DAY, "run_id": "silence-test",
            "signals": [{"center_hz": 104_000_000.0, "bandwidth_hz": 10_000.0,
                         "outline": "carrier", "peak_db_above_floor": 22.0}],
            "notes": []})
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], ARTIFACT)
        self.assertEqual(cluster["cause"], "self")
        self.assertEqual(cluster["resolution"]["portrait"], "P-test")
        self.assertEqual(census_mod.active_census(self.store), [])

    def test_cluster_away_from_portrait_signals_is_untouched(self):
        cluster = build(self.store, self.config, center_hz=300_000_000.0)
        self.store.save_portrait({
            "id": "P-test", "ts": DAY, "run_id": "silence-test",
            "signals": [{"center_hz": 104_000_000.0, "bandwidth_hz": 10_000.0,
                         "outline": "carrier", "peak_db_above_floor": 22.0}],
            "notes": []})
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], UNEXPLAINED)


class TestOverloadPhantom(KnellTestCase):
    def _pair(self, phantom_runs):
        strong = [make_event(self.store, 101_100_000.0, peak=62.0,
                             start_ts=DAY + i * 3600, run_id=r,
                             outline="block", family="constant-envelope")
                  for i, r in enumerate(["run-a", "run-b"])]
        phantom = [make_event(self.store, 202_200_000.0, peak=20.0,
                              start_ts=DAY + i * 3600 + 30, run_id=r,
                              outline="block", family="constant-envelope")
                   for i, r in enumerate(phantom_runs)]
        cluster_mod.assign_events(self.store, self.config, DAY + 10_000)
        clusters = {round(c["features"]["center_hz"]): c
                    for c in self.store.clusters() if not c.get("absorbed_by")}
        return clusters[101_100_000], clusters[202_200_000]

    def test_phantom_that_only_tolls_with_its_maker_is_an_artifact(self):
        strong, phantom = self._pair(["run-a", "run-b"])
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        phantom = self.store.load_cluster(phantom["id"])
        strong = self.store.load_cluster(strong["id"])
        self.assertEqual(phantom["standing"], ARTIFACT)
        self.assertIn("overload phantom", phantom["cause"])
        self.assertEqual(strong["standing"], UNEXPLAINED)

    def test_phantom_heard_without_its_maker_stays_unexplained(self):
        strong, phantom = self._pair(["run-a", "run-c"])
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        phantom = self.store.load_cluster(phantom["id"])
        self.assertEqual(phantom["standing"], UNEXPLAINED)


class TestSilenceRun(KnellTestCase):
    def test_silence_builds_portrait_and_artifacts_the_spurs(self):
        config = self.make_config(span_low_hz=20_000_000.0,
                                  span_high_hz=60_000_000.0)
        run_survey(self.store, config, tiers=(1, 2))   # seeds the baseline
        run_survey(self.store, config, tiers=(1, 2))   # now the sky is heard
        result = run_silence(self.store, config)
        portrait = result["portrait"]
        centers = [s["center_hz"] for s in portrait["signals"]]
        self.assertTrue(any(abs(c - 28_800_000.0) < 500_000 for c in centers),
                        centers)
        spur = [c for c in self.store.clusters()
                if abs(c["features"].get("center_hz", 0) - 28_800_000.0) < 500_000]
        self.assertTrue(spur)
        for cluster in spur:
            self.assertEqual(cluster["standing"], ARTIFACT)
            self.assertEqual(cluster["cause"], "self")


if __name__ == "__main__":
    unittest.main()
