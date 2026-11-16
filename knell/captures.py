"""Captures: SigMF sample pairs, rationed by a storage budget.

A capture is evidence, and evidence is rationed honestly. The manifest
says what was kept; the dropped log says what was rotated out and why.
One rule outranks the budget: the best capture of a cluster still
standing unexplained (or under watch) is never rotated out. The
evidence for the entries that matter most is not the first thing thrown
away.
"""

import json
import os

from . import UNEXPLAINED, UNDER_WATCH
from .store import iso

PROTECTED_STANDINGS = (UNEXPLAINED, UNDER_WATCH)


def load_manifest(store):
    return store.read_json("captures", "manifest.json", default=[])


def save_manifest(store, manifest):
    store.write_json(manifest, "captures", "manifest.json")


def capture_basename(event_id):
    return "cap-%s" % event_id


def write_capture(store, config, event, data, meta):
    """Write a SigMF pair for an event and record it in the manifest.

    The pair is written first, then the budget is enforced; if the
    budget cannot hold this capture even after rotating everything
    unprotected, this capture is dropped again and None is returned, so
    the caller records the loss in the event record instead of
    pretending the evidence exists.
    """
    base = capture_basename(event["id"])
    entry = {
        "file": base + ".sigmf-data",
        "meta_file": base + ".sigmf-meta",
        "event_id": event["id"],
        "cluster_id": event.get("cluster_id"),
        "ts": event["start_ts"],
        "bytes": len(data),
        "peak_db_above_floor": event.get("peak_db_above_floor", 0.0),
    }
    with open(store.path("captures", entry["file"]), "wb") as handle:
        handle.write(data)
    doc = {
        "global": dict(meta),
        "captures": [{
            "core:sample_start": 0,
            "core:frequency": event["center_hz"],
            "core:datetime": iso(event["start_ts"]),
        }],
        "annotations": [{
            "core:sample_start": 0,
            "core:sample_count": len(data) // 2,
            "core:label": "knell capture",
            "knell:event_id": event["id"],
        }],
    }
    doc["global"].setdefault("core:version", "1.0.0")
    doc["global"].setdefault("core:datatype", "ci8")
    doc["global"].setdefault("core:sample_rate", config.capture_sample_rate)
    with open(store.path("captures", entry["meta_file"]), "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=1, sort_keys=True)
        handle.write("\n")
    manifest = load_manifest(store)
    manifest.append(entry)
    save_manifest(store, manifest)
    enforce_budget(store, config)
    surviving = {m["event_id"] for m in load_manifest(store)}
    if entry["event_id"] not in surviving:
        return None
    return entry


def _drop_entry(store, entry, reason):
    manifest = [m for m in load_manifest(store) if m["event_id"] != entry["event_id"]]
    save_manifest(store, manifest)
    for name in (entry["file"], entry["meta_file"]):
        target = store.path("captures", name)
        if os.path.isfile(target):
            os.unlink(target)
    store.append_jsonl({
        "event_id": entry["event_id"],
        "file": entry["file"],
        "bytes": entry["bytes"],
        "reason": reason,
    }, "captures", "dropped.jsonl")


def total_bytes(manifest):
    return sum(m["bytes"] for m in manifest)


def protected_event_ids(store):
    """Event ids whose best capture is protected by the standing rule.

    For every cluster standing UNEXPLAINED or UNDER WATCH, the capture
    with the highest peak is protected. Clusters are consulted live, so
    a cluster that resolves loses its protection on the next rotation.
    """
    manifest = load_manifest(store)
    by_event = {m["event_id"]: m for m in manifest}
    protected = set()
    for cluster in store.clusters():
        if cluster.get("standing") not in PROTECTED_STANDINGS:
            continue
        candidates = [eid for eid in cluster.get("event_ids", []) if eid in by_event]
        if not candidates:
            continue
        winner = max(candidates, key=lambda eid: by_event[eid]["peak_db_above_floor"])
        protected.add(winner)
    return protected


def enforce_budget(store, config):
    """Rotate oldest unprotected captures out until under budget.

    Returns False when only protected captures remain and the budget
    still cannot be met.
    """
    budget = config.capture_budget_bytes
    manifest = load_manifest(store)
    protected = protected_event_ids(store)
    while total_bytes(manifest) > budget:
        candidates = [m for m in manifest if m["event_id"] not in protected]
        if not candidates:
            return False
        candidates.sort(key=lambda m: m["ts"])
        _drop_entry(store, candidates[0], "budget rotation: oldest unprotected")
        manifest = load_manifest(store)
    return True
