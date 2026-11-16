"""Clustering: tolerances, the habit split, merges and splits."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from knelltest import DAY, KnellTestCase, make_event

from knell import cluster as cluster_mod


def live_clusters(store):
    return [c for c in store.clusters() if not c.get("absorbed_by")]


class TestClustering(KnellTestCase):
    def test_same_emitter_events_cluster_together(self):
        for i in range(3):
            make_event(self.store, 433_920_000.0, start_ts=DAY + i * 3600)
        assigned, opened = cluster_mod.assign_events(self.store, self.config, DAY + 10_000)
        clusters = live_clusters(self.store)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]["event_ids"]), 3)
        self.assertEqual(opened, 1)

    def test_distant_frequency_opens_new_cluster(self):
        make_event(self.store, 101_000_000.0, start_ts=DAY)
        make_event(self.store, 105_000_000.0, start_ts=DAY + 60)
        cluster_mod.assign_events(self.store, self.config, DAY + 100)
        self.assertEqual(len(live_clusters(self.store)), 2)

    def test_bandwidth_mismatch_opens_new_cluster(self):
        make_event(self.store, 102_000_000.0, bandwidth_hz=50_000.0, start_ts=DAY)
        make_event(self.store, 102_000_000.0, bandwidth_hz=900_000.0, start_ts=DAY + 60)
        cluster_mod.assign_events(self.store, self.config, DAY + 100)
        self.assertEqual(len(live_clusters(self.store)), 2)

    def test_outline_mismatch_opens_new_cluster(self):
        make_event(self.store, 102_000_000.0, outline="carrier", start_ts=DAY)
        make_event(self.store, 102_000_000.0, outline="block", start_ts=DAY + 60)
        cluster_mod.assign_events(self.store, self.config, DAY + 100)
        self.assertEqual(len(live_clusters(self.store)), 2)

    def test_habit_split_keeps_opposite_schedules_separate(self):
        # Four tolls in the small hours build a habit; a fifth event of
        # the same shape at midday must not join it.
        for i in range(4):
            make_event(self.store, 103_000_000.0, start_ts=DAY + 3600 + i * 600)
        cluster_mod.assign_events(self.store, self.config, DAY + 10_000)
        self.assertEqual(len(live_clusters(self.store)), 1)
        make_event(self.store, 103_000_000.0, start_ts=DAY + 14 * 3600)
        cluster_mod.assign_events(self.store, self.config, DAY + 20_000)
        clusters = live_clusters(self.store)
        self.assertEqual(len(clusters), 2)
        counts = sorted(len(c["event_ids"]) for c in clusters)
        self.assertEqual(counts, [1, 4])
        singleton = [c for c in clusters if len(c["event_ids"]) == 1][0]
        self.assertTrue(any(h["kind"] == "kept-separate" for h in singleton["history"]))

    def test_merge_pass_unites_clusters_accumulated_evidence_agrees_on(self):
        a = make_event(self.store, 104_000_000.0, start_ts=DAY + 3600)
        b = make_event(self.store, 104_010_000.0, start_ts=DAY + 7200)
        first = cluster_mod.new_cluster(self.store, a, DAY)
        cluster_mod.refresh_features(self.store, self.config, first)
        self.store.save_cluster(first)
        second = cluster_mod.new_cluster(self.store, b, DAY)
        second["event_ids"] = [b["id"]]
        cluster_mod.refresh_features(self.store, self.config, second)
        self.store.save_cluster(second)
        cluster_mod.assign_events(self.store, self.config, DAY + 10_000)
        clusters = live_clusters(self.store)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]["event_ids"]), 2)
        absorbed = [c for c in self.store.clusters() if c.get("absorbed_by")]
        self.assertEqual(len(absorbed), 1)
        self.assertTrue(any(h["kind"] == "merged" for h in absorbed[0]["history"]))

    def test_split_cluster_by_time(self):
        events = [make_event(self.store, 106_000_000.0, start_ts=DAY + i * 3600)
                  for i in range(6)]
        cluster_mod.assign_events(self.store, self.config, DAY + 30_000)
        clusters = live_clusters(self.store)
        self.assertEqual(len(clusters), 1)
        cluster = clusters[0]
        new = cluster_mod.split_cluster(self.store, self.config, cluster,
                                        DAY + 3 * 3600, DAY + 40_000, "test split")
        self.assertIsNotNone(new)
        self.assertEqual(len(cluster["event_ids"]), 3)
        self.assertEqual(len(new["event_ids"]), 3)
        self.assertTrue(any(h["kind"] == "split" for h in new["history"]))


if __name__ == "__main__":
    unittest.main()
