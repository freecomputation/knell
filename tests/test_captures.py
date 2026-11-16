"""Capture budget rotation and the protection rule."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from knelltest import DAY, KnellTestCase, make_event

from knell import census as census_mod
from knell import cluster as cluster_mod
from knell.captures import (enforce_budget, load_manifest, write_capture)

FAR_FREQ = 300_000_000.0
DATA = bytes(1000)


def write(store, config, event):
    return write_capture(store, config, event, DATA, {"core:datatype": "ci8"})


class TestRotation(KnellTestCase):
    def _sky(self):
        # Two tolled events of one unexplained emitter, one stray event.
        e1 = make_event(self.store, FAR_FREQ, peak=20.0, start_ts=DAY)
        e2 = make_event(self.store, FAR_FREQ, peak=30.0, start_ts=DAY + 600)
        e3 = make_event(self.store, 305_000_000.0, peak=25.0, start_ts=DAY + 1200)
        cluster_mod.assign_events(self.store, self.config, DAY + 10_000)
        census_mod.run_pass(self.store, self.config, DAY + 20_000)
        return e1, e2, e3

    def test_best_capture_of_unexplained_cluster_is_never_rotated(self):
        e1, e2, e3 = self._sky()
        roomy = self.make_config(capture_budget_bytes=10_000_000)
        write(self.store, roomy, e1)
        write(self.store, roomy, e2)
        write(self.store, roomy, e3)
        self.assertEqual(len(load_manifest(self.store)), 3)
        tight = self.make_config(capture_budget_bytes=1500)
        enforce_budget(self.store, tight)
        surviving = {m["event_id"] for m in load_manifest(self.store)}
        # e2 is the best capture of a cluster still standing unexplained:
        # protected. e1 (older, weaker) and e3 (no cluster) rotated out,
        # oldest first.
        self.assertEqual(surviving, {e2["id"]})
        dropped = self.store.read_jsonl("captures", "dropped.jsonl")
        self.assertEqual([d["event_id"] for d in dropped], [e1["id"], e3["id"]])
        self.assertTrue(os.path.isfile(
            self.store.path("captures", "cap-%s.sigmf-data" % e2["id"])))
        self.assertFalse(os.path.isfile(
            self.store.path("captures", "cap-%s.sigmf-data" % e1["id"])))

    def test_resolved_cluster_loses_its_protection(self):
        e1, e2, e3 = self._sky()
        roomy = self.make_config(capture_budget_bytes=10_000_000)
        write(self.store, roomy, e2)
        cluster = [c for c in self.store.clusters()
                   if e2["id"] in c["event_ids"]][0]
        cluster["standing"] = "IDENTIFIED"
        self.store.save_cluster(cluster)
        enforce_budget(self.store, self.make_config(capture_budget_bytes=0))
        self.assertEqual(load_manifest(self.store), [])

    def test_capture_that_cannot_fit_is_dropped_and_reported(self):
        event = make_event(self.store, FAR_FREQ, peak=25.0, start_ts=DAY)
        tiny = self.make_config(capture_budget_bytes=10)
        result = write(self.store, tiny, event)
        self.assertIsNone(result)
        self.assertEqual(load_manifest(self.store), [])
        dropped = self.store.read_jsonl("captures", "dropped.jsonl")
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["event_id"], event["id"])


if __name__ == "__main__":
    unittest.main()
