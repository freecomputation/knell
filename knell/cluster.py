"""Clustering: events grouped into emitters, conservatively.

Two events belong to one cluster when their shapes agree within the
stated tolerances and their frequencies agree within the measured
stability of the thing itself. Habit can confirm a cluster and can
split one: shapes that agree but keep opposite schedules are two
emitters until evidence says otherwise, because merging wrongly writes
a real emitter off inside another's identity, while splitting wrongly
only lengthens the census.

Clusters are judgments laid over the event layer. The event layer is
never destroyed; merges and splits are dated history entries with
reasons, and a merge can be undone without losing the events under it.
"""

from . import features as features_mod
from .store import iso

MERGED_MARKER = "absorbed_by"


def add_history(cluster, ts, kind, text):
    cluster.setdefault("history", []).append({"ts": ts, "kind": kind, "text": text})


def new_cluster(store, event, ts):
    number = store.next_id("cluster")
    cluster = {
        "id": "C%06d" % number,
        "created_ts": ts,
        "event_ids": [event["id"]],
        "features": {},
        "standing": None,
        "cause": None,
        "resolution": None,
        "near_matches": [],
        "history": [],
    }
    add_history(cluster, ts, "created", "cluster opened by event %s" % event["id"])
    return cluster


def refresh_features(store, config, cluster):
    events = []
    by_id = {e["id"]: e for e in store.events()}
    for event_id in cluster["event_ids"]:
        if event_id in by_id:
            events.append(by_id[event_id])
    events.sort(key=lambda e: e["start_ts"])
    cluster["features"] = features_mod.cluster_features(events, config)
    return cluster


def _freq_delta_allowed(cluster_feats, config):
    drift = cluster_feats.get("drift_hz", 0.0)
    error = cluster_feats.get("instrument_error_hz", 0.0)
    return max(config.cluster_freq_tol_hz, drift + 2.0 * error)


def compatible(cluster, event, config):
    """Judge one event against one cluster.

    Returns (verdict, reason) where verdict is "match", "habit" (shape
    and frequency agree but habit disagrees: a split signal), or "no".
    """
    feats = cluster["features"]
    if not feats:
        return "match", "cluster has no features yet"
    delta = abs(event["center_hz"] - feats["center_hz"])
    if delta > _freq_delta_allowed(feats, config):
        return "no", "frequency delta %.0f Hz beyond tolerance" % delta
    event_outline = event.get("outline", "unknown")
    if (feats.get("outline") not in (None, "unknown") and event_outline != "unknown"
            and event_outline != feats["outline"]):
        return "no", "outline %s against cluster %s" % (event_outline, feats["outline"])
    if feats.get("bandwidth_hz"):
        ratio = event["bandwidth_hz"] / feats["bandwidth_hz"]
        if ratio < config.cluster_bw_ratio_min or ratio > config.cluster_bw_ratio_max:
            return "no", "bandwidth ratio %.2f outside tolerance" % ratio
    if feats.get("toll_count", 0) >= config.habit_min_tolls:
        hour = int((event["start_ts"] // 3600) % 24)
        hours = feats.get("hours_utc", [])
        slack = config.habit_hour_slack
        widened = set()
        for h in hours:
            for d in range(-slack, slack + 1):
                widened.add((h + d) % 24)
        if hour not in widened:
            return "habit", "event hour %02d outside cluster habit hours %s" % (hour, hours)
    return "match", "frequency, shape and habit agree"


def assign_events(store, config, ts):
    """Assign every unassigned event to a cluster, opening new ones.

    Returns (assigned_count, opened_count). Resolved clusters and
    absorbed clusters never take new events: a fresh emitter that
    resembles a resolved one forms its own cluster and is judged
    against the registry, which is how an operator identification is
    never silently re-filed.
    """
    events = store.events()
    by_id = {e["id"]: e for e in events}
    clusters = store.clusters()
    assigned_ids = set()
    for cluster in clusters:
        assigned_ids.update(cluster.get("event_ids", []))
    live = [c for c in clusters
            if not c.get(MERGED_MARKER) and c.get("standing") not in ("IDENTIFIED", "ARTIFACT")]
    for cluster in live:
        if not cluster["features"]:
            refresh_features(store, config, cluster)
    assigned = 0
    opened = 0
    pending = [e for e in events if e["id"] not in assigned_ids]
    pending.sort(key=lambda e: e["start_ts"])
    for event in pending:
        best = None
        best_delta = None
        habit_reject = None
        for cluster in live:
            verdict, reason = compatible(cluster, event, config)
            if verdict == "match":
                delta = abs(event["center_hz"] - cluster["features"].get("center_hz", event["center_hz"]))
                if best is None or delta < best_delta:
                    best, best_delta = cluster, delta
            elif verdict == "habit" and habit_reject is None:
                habit_reject = (cluster, reason)
        if best is not None:
            best["event_ids"].append(event["id"])
            refresh_features(store, config, best)
            store.save_cluster(best)
            assigned += 1
            continue
        cluster = new_cluster(store, event, ts)
        if habit_reject is not None:
            add_history(cluster, ts, "kept-separate",
                        "shape and frequency agree with %s but %s; kept separate"
                        % (habit_reject[0]["id"], habit_reject[1]))
        refresh_features(store, config, cluster)
        store.save_cluster(cluster)
        live.append(cluster)
        opened += 1
    _merge_pass(store, config, ts)
    return assigned, opened


def _habit_compatible(a_feats, b_feats, config):
    hours_a = set(a_feats.get("hours_utc", []))
    hours_b = set(b_feats.get("hours_utc", []))
    if not hours_a or not hours_b:
        return True
    slack = config.habit_hour_slack
    widened = set()
    for h in hours_a:
        for d in range(-slack, slack + 1):
            widened.add((h + d) % 24)
    return bool(hours_b & widened)


def _merge_pass(store, config, ts):
    """Merge live clusters that accumulated evidence says are one."""
    clusters = [c for c in store.clusters()
                if not c.get(MERGED_MARKER) and c.get("standing") not in ("IDENTIFIED", "ARTIFACT")]
    clusters.sort(key=lambda c: c["created_ts"])
    changed = True
    while changed:
        changed = False
        for i in range(len(clusters)):
            if clusters[i].get(MERGED_MARKER):
                continue
            for j in range(i + 1, len(clusters)):
                if clusters[j].get(MERGED_MARKER):
                    continue
                a, b = clusters[i], clusters[j]
                fa, fb = a["features"], b["features"]
                if not fa or not fb:
                    continue
                delta = abs(fa["center_hz"] - fb["center_hz"])
                allowed = max(_freq_delta_allowed(fa, config), _freq_delta_allowed(fb, config))
                if delta > allowed:
                    continue
                if (fa.get("outline") not in (None, "unknown") and fb.get("outline") not in (None, "unknown")
                        and fa["outline"] != fb["outline"]):
                    continue
                ratio = fb["bandwidth_hz"] / fa["bandwidth_hz"] if fa.get("bandwidth_hz") else 1.0
                if ratio < config.cluster_bw_ratio_min or ratio > config.cluster_bw_ratio_max:
                    continue
                if not _habit_compatible(fa, fb, config):
                    continue
                merge_clusters(store, config, a, b, ts,
                               "accumulated evidence: frequency, shape and habit agree")
                changed = True
                break
            if changed:
                break


def merge_clusters(store, config, keep, absorb, ts, reason):
    """Merge absorb into keep. The absorbed file is preserved, marked."""
    keep["event_ids"] = sorted(set(keep["event_ids"]) | set(absorb["event_ids"]),
                               key=lambda eid: _event_ts(store, eid))
    absorb[MERGED_MARKER] = keep["id"]
    add_history(absorb, ts, "merged", "absorbed into %s: %s" % (keep["id"], reason))
    add_history(keep, ts, "merged", "absorbed %s: %s" % (absorb["id"], reason))
    refresh_features(store, config, keep)
    store.save_cluster(absorb)
    store.save_cluster(keep)
    return keep


def _event_ts(store, event_id):
    event = store.event_by_id(event_id)
    return event["start_ts"] if event else 0.0


def split_cluster(store, config, cluster, at_ts, ts, reason):
    """Split a cluster's events at a time boundary into a new cluster."""
    by_id = {e["id"]: e for e in store.events()}
    early = [eid for eid in cluster["event_ids"] if by_id.get(eid, {}).get("start_ts", 0) < at_ts]
    late = [eid for eid in cluster["event_ids"] if by_id.get(eid, {}).get("start_ts", 0) >= at_ts]
    if not early or not late:
        return None
    first_late = by_id[late[0]]
    new = new_cluster(store, first_late, ts)
    new["event_ids"] = late
    cluster["event_ids"] = early
    add_history(cluster, ts, "split", "split at %s: %s; later tolls moved to %s"
                % (iso(at_ts), reason, new["id"]))
    add_history(new, ts, "split", "split from %s at %s: %s" % (cluster["id"], iso(at_ts), reason))
    refresh_features(store, config, cluster)
    refresh_features(store, config, new)
    store.save_cluster(cluster)
    store.save_cluster(new)
    return new
