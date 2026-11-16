"""The census: the standing register of the unexplained.

A judgment pass over the cluster files, run at the end of every survey,
watch and silence, and on demand. The pass applies, in order:

- expiry of stale INSUFFICIENT RECORD entries
- the self-portrait: clusters the instrument itself accounts for stand
  as ARTIFACT with cause self
- overload phantoms: clusters that toll only with a stronger emitter,
  at a harmonic relation to it, stand as ARTIFACT with that cause
- nulling: clusters matching a registry entry on every criterion stand
  as IDENTIFIED and leave the census for the registry
- near matches: recorded on the cluster, never promoted
- characterisation: clusters too thin to judge stand as INSUFFICIENT
  RECORD; the rest stand UNEXPLAINED, or UNDER WATCH where a watch or
  a verdict put them there

Standings change only here or on an operator verdict, and every change
is a dated history line with its grounds. The census documents are
generated from the cluster files and are never edited by hand.
"""

from . import (ARTIFACT, IDENTIFIED, INSUFFICIENT_RECORD, UNEXPLAINED,
               UNDER_WATCH)
from .cluster import add_history, refresh_features
from .registry import find_matches
from .store import iso


def _set_standing(store, cluster, standing, ts, grounds, cause=None, resolution=None):
    if cluster.get("standing") == standing and cluster.get("cause") == cause:
        return False
    old = cluster.get("standing")
    cluster["standing"] = standing
    cluster["cause"] = cause
    if resolution is not None:
        cluster["resolution"] = resolution
    add_history(cluster, ts, "standing",
                "%s -> %s: %s" % (old or "new", standing, grounds))
    return True


def _is_characterised(cluster, config):
    feats = cluster.get("features", {})
    if feats.get("toll_count", 0) >= config.min_tolls_characterised:
        return True
    return bool(feats.get("has_capture"))


def _portrait_match(cluster, portrait):
    """Does the latest self-portrait account for this cluster?"""
    if not portrait:
        return None
    feats = cluster.get("features", {})
    for signal in portrait.get("signals", []):
        delta = abs(feats.get("center_hz", 0.0) - signal["center_hz"])
        if delta <= max(25_000.0, signal.get("bandwidth_hz", 0.0)):
            if feats.get("outline") in (None, "unknown", signal.get("outline")):
                return signal
    return None


def _harmonic_relation(freq, other):
    if other <= 0 or freq <= 0:
        return None
    for n in (2, 3, 4):
        if abs(freq - n * other) <= max(50_000.0, 0.01 * n * other):
            return "%dx harmonic of %.1f MHz" % (n, other / 1e6)
        if abs(other - n * freq) <= max(50_000.0, 0.01 * n * freq):
            return "fundamental of %.1f MHz at 1/%d" % (other / 1e6, n)
    return None


def _toll_coincidence(store, a, b):
    """How completely a's appearances coincide with b's.

    A sweeping receiver never hears two frequencies in the same
    instant, so coincidence is judged at the level of the run: in what
    fraction of the runs where a tolled did b also toll. A phantom
    that appears in every run its strong emitter appears in, and in no
    run without it, scores 1.0.
    """
    by_id = {e["id"]: e for e in store.events()}
    a_runs = {by_id[eid].get("run_id") for eid in a["event_ids"] if eid in by_id}
    b_runs = {by_id[eid].get("run_id") for eid in b["event_ids"] if eid in by_id}
    if not a_runs or not b_runs:
        return 0.0
    return len(a_runs & b_runs) / len(a_runs)


def run_pass(store, config, ts):
    """Run one judgment pass. Returns a summary dict of what changed."""
    summary = {"nulled": 0, "artifacts": 0, "expired": 0, "near_matches": 0,
               "unexplained": 0, "insufficient": 0, "under_watch": 0}
    entries = store.local_registry()
    portrait = store.latest_portrait()
    clusters = [c for c in store.clusters() if not c.get("absorbed_by")]
    for cluster in clusters:
        refresh_features(store, config, cluster)
    # Overload suspects first: they inform the phantom test.
    strong = [c for c in clusters
              if c.get("features", {}).get("peak_db_max", 0) >= config.overload_peak_db]
    for cluster in clusters:
        if cluster.get("standing") in (IDENTIFIED, ARTIFACT):
            store.save_cluster(cluster)
            continue
        feats = cluster["features"]
        # Expiry of insufficient records.
        if cluster.get("standing") == INSUFFICIENT_RECORD:
            age_days = (ts - feats.get("last_ts", ts)) / 86400.0
            if age_days > config.insufficient_expiry_days:
                cluster["expired"] = True
                add_history(cluster, ts, "expired",
                            "no toll for %.1f days, beyond the %d day window; "
                            "expired out of the active census" % (age_days, config.insufficient_expiry_days))
                summary["expired"] += 1
                store.save_cluster(cluster)
                continue
        # Self-portrait artifacts.
        signal = _portrait_match(cluster, portrait)
        if signal is not None:
            if _set_standing(store, cluster, ARTIFACT, ts,
                             "accounted for by self-portrait %s (instrument spur at %.3f MHz)"
                             % (portrait["id"], signal["center_hz"] / 1e6),
                             cause="self",
                             resolution={"type": "artifact", "cause": "self",
                                         "portrait": portrait["id"]}):
                summary["artifacts"] += 1
            store.save_cluster(cluster)
            continue
        # Overload phantoms.
        phantom_of = None
        for other in strong:
            if other["id"] == cluster["id"]:
                continue
            if feats.get("peak_db_max", 0.0) >= other["features"].get("peak_db_max", 0.0):
                continue  # a phantom is weaker than its maker
            relation = _harmonic_relation(feats.get("center_hz", 0.0),
                                          other["features"].get("center_hz", 0.0))
            if relation and _toll_coincidence(store, cluster, other) >= 0.8:
                phantom_of = (other, relation)
                break
        if phantom_of is not None:
            other, relation = phantom_of
            cause = "overload phantom: %s" % relation
            if _set_standing(store, cluster, ARTIFACT, ts,
                             "tolls coincide with stronger cluster %s and stand in %s relation to it"
                             % (other["id"], relation),
                             cause=cause,
                             resolution={"type": "artifact", "cause": cause,
                                         "strong_cluster": other["id"]}):
                summary["artifacts"] += 1
            store.save_cluster(cluster)
            continue
        # Nulling on full criteria.
        full, near = find_matches(entries, feats)
        if full:
            best = full[0]
            if _set_standing(store, cluster, IDENTIFIED, ts,
                             "full match to registry entry %s (%s) on all criteria"
                             % (best["entry_id"], best["entry_name"]),
                             cause=best["entry_name"],
                             resolution={"type": "nulled", "entry_id": best["entry_id"],
                                         "margins": best["margins"]}):
                summary["nulled"] += 1
                _note_registry_observation(store, best["entry_id"], cluster, ts)
            cluster["near_matches"] = []
            store.save_cluster(cluster)
            continue
        if near:
            cluster["near_matches"] = [{
                "entry_id": n["entry_id"], "entry_name": n["entry_name"],
                "failed": n["failed"], "margins": n["margins"], "ts": ts,
            } for n in near]
            summary["near_matches"] += len(near)
        else:
            cluster["near_matches"] = []
        # Characterisation and the ordinary standings.
        if not _is_characterised(cluster, config):
            if _set_standing(store, cluster, INSUFFICIENT_RECORD, ts,
                             "too little record to characterise: %d toll(s), no capture"
                             % feats.get("toll_count", 0)):
                pass
            summary["insufficient"] += 1
        elif cluster.get("standing") == UNDER_WATCH:
            summary["under_watch"] += 1
        else:
            if _set_standing(store, cluster, UNEXPLAINED, ts,
                             "characterised; no full registry match"):
                pass
            summary["unexplained"] += 1
        store.save_cluster(cluster)
    return summary


def _note_registry_observation(store, entry_id, cluster, ts):
    """Record on the registry entry that it nulled another cluster."""
    entries = store.local_registry()
    for entry in entries:
        if entry["id"] == entry_id:
            entry.setdefault("observations", []).append({
                "cluster_id": cluster["id"], "ts": ts,
                "center_hz": cluster["features"].get("center_hz"),
            })
    store.rewrite_local_registry(entries)


def active_census(store):
    """Clusters standing in the active census, expired ones excluded."""
    out = []
    for cluster in store.clusters():
        if cluster.get("absorbed_by") or cluster.get("expired"):
            continue
        if cluster.get("standing") in (UNEXPLAINED, UNDER_WATCH, INSUFFICIENT_RECORD):
            out.append(cluster)
    return out


def resolved_archive(store):
    out = []
    for cluster in store.clusters():
        if cluster.get("absorbed_by"):
            continue
        if cluster.get("standing") in (IDENTIFIED, ARTIFACT) or cluster.get("expired"):
            out.append(cluster)
    return out


def census_document(store, ts):
    """The generated census document (JSON form)."""
    active = active_census(store)
    resolved = resolved_archive(store)

    def entry(cluster):
        feats = cluster.get("features", {})
        return {
            "id": cluster["id"],
            "standing": cluster.get("standing"),
            "cause": cluster.get("cause"),
            "center_mhz": round(feats.get("center_hz", 0.0) / 1e6, 4),
            "bandwidth_khz": round(feats.get("bandwidth_hz", 0.0) / 1e3, 1),
            "outline": feats.get("outline"),
            "family": feats.get("family"),
            "tolls": feats.get("toll_count", 0),
            "first_heard": iso(feats["first_ts"]) if feats.get("first_ts") else None,
            "last_heard": iso(feats["last_ts"]) if feats.get("last_ts") else None,
            "near_matches": cluster.get("near_matches", []),
            "history": cluster.get("history", []),
        }

    by_standing = {}
    for cluster in active:
        by_standing.setdefault(cluster["standing"], []).append(entry(cluster))
    return {
        "generated_ts": ts,
        "generated": iso(ts),
        "active_counts": {k: len(v) for k, v in by_standing.items()},
        "active": by_standing,
        "resolved": [entry(c) for c in resolved],
    }


def write_census_files(store, ts):
    doc = census_document(store, ts)
    store.write_json(doc, "census", "census.json")
    lines = ["KNELL census - generated %s" % iso(ts), ""]
    order = [UNEXPLAINED, UNDER_WATCH, INSUFFICIENT_RECORD]
    for standing in order:
        entries = doc["active"].get(standing, [])
        lines.append("%s: %d" % (standing, len(entries)))
        for e in entries:
            lines.append("- %s  %.4f MHz  bw %.1f kHz  %s / %s  tolls %d  first %s  last %s"
                         % (e["id"], e["center_mhz"], e["bandwidth_khz"], e["outline"],
                            e["family"], e["tolls"], e["first_heard"], e["last_heard"]))
            for near in e["near_matches"]:
                lines.append("    near match: %s - failed %s"
                             % (near["entry_name"], ", ".join(near["failed"])))
        lines.append("")
    lines.append("Resolved: %d" % len(doc["resolved"]))
    for e in doc["resolved"]:
        lines.append("- %s  %s  %.4f MHz  cause: %s"
                     % (e["id"], e["standing"], e["center_mhz"], e["cause"]))
    with open(store.path("census", "census.txt"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return doc
