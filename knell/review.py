"""The review loop: packets out, verdicts back.

On a regular cadence KNELL prepares a review packet: new clusters,
standings changed, near matches, habits sharpened, watch
recommendations, each with its evidence named. The packet is plain
text, readable in one sitting.

Verdicts come back as a JSON file of instructions and are written into
the record dated and attributed to the operator. An identification by
verdict creates a registry entry from the cluster's measured features,
so the emitter the operator named is never re-filed as unexplained.
"""

import os

from . import ARTIFACT, IDENTIFIED, UNEXPLAINED, UNDER_WATCH
from .cluster import add_history, merge_clusters, refresh_features, split_cluster
from .store import iso


def prepare_packet(store, config, ts):
    """Build the review packet text and record the packet time."""
    state = store.state()
    since = state.get("last_packet_ts", 0.0)
    clusters = [c for c in store.clusters() if not c.get("absorbed_by")]
    new_clusters = [c for c in clusters if c["created_ts"] > since]
    changed = []
    for cluster in clusters:
        for line in cluster.get("history", []):
            if line["ts"] > since and line["kind"] in ("standing", "expired", "merged", "split"):
                changed.append((cluster["id"], line))
    near = [c for c in clusters if c.get("near_matches")]
    sharpened = []
    for cluster in clusters:
        before = cluster.get("packet_tolls", 0)
        now = cluster.get("features", {}).get("toll_count", 0)
        if now - before >= 3 and cluster.get("standing") == UNEXPLAINED:
            sharpened.append((cluster, before, now))
    watch_recs = [c for c in clusters
                  if c.get("standing") == UNEXPLAINED
                  and c.get("features", {}).get("toll_count", 0) >= 5]
    lines = []
    lines.append("KNELL review packet - %s" % iso(ts))
    lines.append("Covering changes since %s." % (iso(since) if since else "the beginning"))
    lines.append("")
    lines.append("New clusters: %d" % len(new_clusters))
    for c in new_clusters:
        f = c.get("features", {})
        lines.append("- %s  %.4f MHz  bw %.1f kHz  %s / %s  tolls %d  standing %s  evidence: clusters/%s.json"
                     % (c["id"], f.get("center_hz", 0) / 1e6, f.get("bandwidth_hz", 0) / 1e3,
                        f.get("outline"), f.get("family"), f.get("toll_count", 0),
                        c.get("standing"), c["id"]))
    lines.append("")
    lines.append("Standings changed: %d" % len(changed))
    for cluster_id, line in changed:
        lines.append("- %s  %s  %s" % (cluster_id, iso(line["ts"]), line["text"]))
    lines.append("")
    lines.append("Near matches: %d" % sum(len(c["near_matches"]) for c in near))
    for c in near:
        for n in c["near_matches"]:
            lines.append("- %s near %s - failed %s  evidence: clusters/%s.json"
                         % (c["id"], n["entry_name"], ", ".join(n["failed"]), c["id"]))
    lines.append("")
    lines.append("Habits sharpened: %d" % len(sharpened))
    for c, before, now in sharpened:
        lines.append("- %s  tolls %d -> %d  gap median %s s  duty %s"
                     % (c["id"], before, now, c["features"].get("gap_median_s"),
                        c["features"].get("duty_cycle")))
    lines.append("")
    lines.append("Recommended for a watch: %d" % len(watch_recs))
    for c in watch_recs:
        f = c["features"]
        lines.append("- %s  %.4f MHz  tolls %d  run: knell watch %s --span 7200"
                     % (c["id"], f.get("center_hz", 0) / 1e6, f.get("toll_count", 0), c["id"]))
    text = "\n".join(lines) + "\n"
    stamp = "%04d%02d%02dT%02d%02d%02dZ" % _stamp_parts(ts)
    name = "packet-%s.txt" % stamp
    with open(store.path("reviews", name), "w", encoding="utf-8") as handle:
        handle.write(text)
    for cluster in clusters:
        cluster["packet_tolls"] = cluster.get("features", {}).get("toll_count", 0)
        store.save_cluster(cluster)
    state["last_packet_ts"] = ts
    store.save_state(state)
    return {"file": name, "text": text, "new": len(new_clusters),
            "changed": len(changed), "near": sum(len(c["near_matches"]) for c in near)}


def _stamp_parts(ts):
    import time
    t = time.gmtime(ts)
    return (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


def apply_verdicts(store, config, verdicts, ts):
    """Record operator verdicts. Returns a list of result lines.

    Each verdict is a dict: {cluster, action, cause, note, at_ts, with}.
    Actions: identify, artifact, watch, unwatched, split, merge, note.
    """
    results = []
    for verdict in verdicts:
        cluster = store.load_cluster(verdict.get("cluster", ""))
        if cluster is None:
            results.append("no such cluster: %s" % verdict.get("cluster"))
            continue
        action = verdict.get("action")
        note = verdict.get("note", "")
        if action == "identify":
            cause = verdict.get("cause")
            if not cause:
                results.append("%s: identify needs a cause" % cluster["id"])
                continue
            entry = _entry_from_cluster(cluster, cause, ts)
            store.append_local_registry(entry)
            cluster["standing"] = IDENTIFIED
            cluster["cause"] = cause
            cluster["resolution"] = {"type": "verdict", "entry_id": entry["id"]}
            add_history(cluster, ts, "verdict",
                        "identified by operator verdict: %s. %s" % (cause, note))
            results.append("%s identified: %s (registry entry %s)"
                           % (cluster["id"], cause, entry["id"]))
        elif action == "artifact":
            cause = verdict.get("cause")
            if not cause:
                results.append("%s: artifact needs a cause" % cluster["id"])
                continue
            cluster["standing"] = ARTIFACT
            cluster["cause"] = cause
            cluster["resolution"] = {"type": "verdict-artifact", "cause": cause}
            add_history(cluster, ts, "verdict",
                        "artifact by operator verdict: %s. %s" % (cause, note))
            results.append("%s artifact: %s" % (cluster["id"], cause))
        elif action == "watch":
            cluster["standing"] = UNDER_WATCH
            cluster["watch"] = {"source": "verdict", "started_ts": ts}
            add_history(cluster, ts, "verdict", "placed under watch by operator verdict. %s" % note)
            results.append("%s under watch" % cluster["id"])
        elif action == "unwatched":
            if cluster.get("standing") == UNDER_WATCH:
                cluster["standing"] = UNEXPLAINED
            cluster["watch"] = None
            add_history(cluster, ts, "verdict", "watch lifted by operator verdict. %s" % note)
            results.append("%s watch lifted" % cluster["id"])
        elif action == "split":
            at_ts = verdict.get("at_ts")
            if at_ts is None:
                results.append("%s: split needs at_ts" % cluster["id"])
                continue
            new = split_cluster(store, config, cluster, float(at_ts), ts,
                                "operator verdict. %s" % note)
            results.append("%s split -> %s" % (cluster["id"], new["id"] if new else "no split possible"))
            continue
        elif action == "merge":
            other = store.load_cluster(verdict.get("with", ""))
            if other is None:
                results.append("%s: no such cluster to merge with: %s"
                               % (cluster["id"], verdict.get("with")))
                continue
            merge_clusters(store, config, cluster, other, ts,
                           "operator verdict. %s" % note)
            results.append("%s absorbed %s" % (cluster["id"], other["id"]))
            continue
        elif action == "note":
            add_history(cluster, ts, "verdict", "operator note: %s" % note)
            results.append("%s noted" % cluster["id"])
        else:
            results.append("%s: unknown action %s" % (cluster["id"], action))
            continue
        refresh_features(store, config, cluster)
        store.save_cluster(cluster)
    return results


def _entry_from_cluster(cluster, cause, ts):
    feats = cluster.get("features", {})
    number = abs(hash((cluster["id"], cause, ts))) % 1_000_000
    return {
        "id": "verdict-%s-%06d" % (cluster["id"].lower(), number),
        "name": cause,
        "cause": cause,
        "center_hz": feats.get("center_hz", 0.0),
        "freq_tol_hz": max(25_000.0, feats.get("drift_hz", 0.0) * 2 + 25_000.0),
        "bandwidth_hz": feats.get("bandwidth_hz", 0.0) or None,
        "bw_ratio_min": 0.4,
        "bw_ratio_max": 2.5,
        "family": feats.get("family") if feats.get("family") not in (None, "unknown") else None,
        "habit": None,
        "source": "verdict",
        "evidence": "operator verdict on cluster %s at %s" % (cluster["id"], iso(ts)),
        "created_ts": ts,
    }
