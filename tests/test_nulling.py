"""Nulling: full criteria, the near-match path, and the allocation law."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from knelltest import DAY, KnellTestCase, make_event

from knell import IDENTIFIED, UNEXPLAINED, census as census_mod
from knell import cluster as cluster_mod


def build_cluster(store, config, **event_kwargs):
    count = event_kwargs.pop("tolls", 3)
    for i in range(count):
        make_event(store, start_ts=DAY + i * 600, **event_kwargs)
    cluster_mod.assign_events(store, config, DAY + 10_000)
    clusters = [c for c in store.clusters() if not c.get("absorbed_by")]
    assert len(clusters) == 1, clusters
    return clusters[0]


class TestNulling(KnellTestCase):
    def test_full_match_nulls_and_records_margins(self):
        cluster = build_cluster(
            self.store, self.config,
            center_hz=1_090_000_000.0, bandwidth_hz=2_000_000.0,
            outline="block", family="pulsed")
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], IDENTIFIED)
        self.assertEqual(cluster["resolution"]["entry_id"], "seed-adsb-1090")
        self.assertIn("frequency", cluster["resolution"]["margins"])
        self.assertIn("bandwidth", cluster["resolution"]["margins"])
        self.assertIn("family", cluster["resolution"]["margins"])
        self.assertEqual(census_mod.active_census(self.store), [])
        entries = {e["id"]: e for e in self.store.local_registry()}
        self.assertTrue(entries["seed-adsb-1090"].get("observations"))

    def test_allocation_alone_never_nulls(self):
        # 100 MHz sits inside the FM broadcast allocation. There is no
        # local registry entry for it, so allocation cannot identify it.
        cluster = build_cluster(
            self.store, self.config,
            center_hz=100_500_000.0, bandwidth_hz=200_000.0,
            outline="block", family="constant-envelope")
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], UNEXPLAINED)
        self.assertEqual(cluster["near_matches"], [])

    def test_near_match_failing_one_criterion_stays_with_note(self):
        # Right frequency and family for the seeded APT downlink, but
        # ten times its bandwidth: frequency and family pass, bandwidth
        # fails. The cluster stays, carrying the note.
        cluster = build_cluster(
            self.store, self.config,
            center_hz=137_620_000.0, bandwidth_hz=400_000.0,
            outline="block", family="constant-envelope")
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], UNEXPLAINED)
        self.assertEqual(len(cluster["near_matches"]), 1)
        near = cluster["near_matches"][0]
        self.assertEqual(near["entry_id"], "seed-apt-13762")
        self.assertEqual(near["failed"], ["bandwidth"])
        self.assertEqual(len(census_mod.active_census(self.store)), 1)

    def test_unknown_family_blocks_nulling(self):
        # Shape and frequency fit the ADS-B entry, but with no capture
        # the family is unknown and cannot be confirmed: no nulling.
        cluster = build_cluster(
            self.store, self.config,
            center_hz=1_090_000_000.0, bandwidth_hz=2_000_000.0,
            outline="block", family="unknown")
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], UNEXPLAINED)
        self.assertEqual(len(cluster["near_matches"]), 1)
        self.assertEqual(cluster["near_matches"][0]["failed"], ["family"])

    def test_frequency_failure_is_not_even_a_near_match(self):
        cluster = build_cluster(
            self.store, self.config,
            center_hz=300_000_000.0, bandwidth_hz=2_000_000.0,
            outline="block", family="pulsed")
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        cluster = self.store.load_cluster(cluster["id"])
        self.assertEqual(cluster["standing"], UNEXPLAINED)
        self.assertEqual(cluster["near_matches"], [])


if __name__ == "__main__":
    unittest.main()
