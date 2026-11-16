"""Standings: the insufficient record, its expiry, verdicts, watches."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from knelltest import DAY, KnellTestCase, make_event

from knell import (IDENTIFIED, INSUFFICIENT_RECORD as INSUFFICIENT,
                   UNDER_WATCH, UNEXPLAINED, census as census_mod)
from knell import cluster as cluster_mod
from knell.review import apply_verdicts

FAR_FREQ = 300_000_000.0  # no seed entry anywhere near


def build_cluster(store, config, tolls, **kwargs):
    kwargs.setdefault("center_hz", FAR_FREQ)
    for i in range(tolls):
        make_event(store, start_ts=DAY + i * 600, **kwargs)
    cluster_mod.assign_events(store, config, DAY + 10_000)
    clusters = [c for c in store.clusters() if not c.get("absorbed_by")]
    assert len(clusters) == 1, clusters
    return clusters[0]


class TestInsufficient(KnellTestCase):
    def test_single_weak_toll_without_capture_is_insufficient(self):
        cluster = build_cluster(self.store, self.config, 1)
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], INSUFFICIENT)
        self.assertEqual(len(census_mod.active_census(self.store)), 1)

    def test_insufficient_expires_after_the_window(self):
        cluster = build_cluster(self.store, self.config, 1)
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], INSUFFICIENT)
        later = DAY + 20_000 + 15 * 86400  # past the 14 day expiry
        census_mod.run_pass(self.store, self.config, later)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertTrue(cluster["expired"])
        self.assertEqual(census_mod.active_census(self.store), [])
        self.assertTrue(any(h["kind"] == "expired" for h in cluster["history"]))

    def test_insufficient_does_not_expire_early(self):
        cluster = build_cluster(self.store, self.config, 1)
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        census_mod.run_pass(self.store, self.config, DAY + 20_000 + 5 * 86400)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], INSUFFICIENT)
        self.assertFalse(cluster.get("expired"))

    def test_two_tolls_are_characterised_and_unexplained(self):
        cluster = build_cluster(self.store, self.config, 2)
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], UNEXPLAINED)

    def test_single_toll_with_a_capture_is_characterised(self):
        capture = {"sigmf_meta": "captures/x.sigmf-meta",
                   "sigmf_data": "captures/x.sigmf-data", "bytes": 48,
                   "sample_format": "ci8", "sample_rate": 2_400_000.0,
                   "center_hz": FAR_FREQ, "ts": DAY, "synthetic": True}
        cluster = build_cluster(self.store, self.config, 1, capture=capture)
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], UNEXPLAINED)


class TestVerdicts(KnellTestCase):
    def test_identify_verdict_resolves_and_teaches_the_registry(self):
        cluster = build_cluster(self.store, self.config, 3,
                                outline="block", family="pulsed")
        lines = apply_verdicts(self.store, self.config, [
            {"cluster": cluster["id"], "action": "identify",
             "cause": "a test emitter, named by the operator"}], DAY + 30_000)
        self.assertTrue(any("identified" in line for line in lines))
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], IDENTIFIED)
        self.assertEqual(cluster["resolution"]["type"], "verdict")
        verdict_entries = [e for e in self.store.local_registry()
                           if e["source"] == "verdict"]
        self.assertEqual(len(verdict_entries), 1)
        # New events of the same emitter null against the verdict entry
        # on the next pass: the registry has learned. The new toll is
        # placed at the same hour of day, inside the recorded habit.
        make_event(self.store, center_hz=FAR_FREQ, outline="block",
                   family="pulsed", start_ts=DAY + 86400 + 600)
        cluster_mod.assign_events(self.store, self.config, DAY + 90_000)
        census_mod.run_pass(self.store, self.config, DAY + 100_000)
        clusters = [c for c in self.store.clusters() if not c.get("absorbed_by")]
        for c in clusters:
            self.assertEqual(c["standing"], IDENTIFIED)

    def test_watch_verdict_holds_through_a_pass(self):
        cluster = build_cluster(self.store, self.config, 3)
        apply_verdicts(self.store, self.config, [
            {"cluster": cluster["id"], "action": "watch"}], DAY + 30_000)
        census_mod.run_pass(self.store, self.config, DAY + 40_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], UNDER_WATCH)

    def test_artifact_verdict_requires_a_cause(self):
        cluster = build_cluster(self.store, self.config, 3)
        lines = apply_verdicts(self.store, self.config, [
            {"cluster": cluster["id"], "action": "artifact"}], DAY + 30_000)
        self.assertTrue(any("needs a cause" in line for line in lines))
        cluster = self.store.load_cluster(cluster["id"])
        self.assertNotEqual(cluster["standing"], "ARTIFACT")


if __name__ == "__main__":
    unittest.main()
