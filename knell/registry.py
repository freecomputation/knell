"""The registry: the book of the known, in two layers.

The allocation layer is shipped static knowledge - what band plans say
may lawfully be found at each frequency. It is a map of expectations.
Matching it is never sufficient to null a cluster.

The local layer is earned knowledge: emitters actually identified,
each with its criteria and the evidence that identified it. It ships
with a seed of universal services whose frequencies are the same
everywhere, and it grows by two doors only: a cluster nulled on a full
match, and an operator verdict recorded by hand. There is no third
door; the registry cannot learn from its own guesses.

A match is judged criterion by criterion, and the margins are the
record: how far inside or outside each criterion the cluster fell.
"""

import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _load_package_json(name):
    with open(os.path.join(DATA_DIR, name), "r", encoding="utf-8") as handle:
        return json.load(handle)


def allocations():
    return _load_package_json("allocations.json")


def seed_entries():
    return _load_package_json("seed_registry.json")


def allocations_for(freq_hz):
    """Every allocation whose span contains a frequency."""
    return [a for a in allocations() if a["low_hz"] <= freq_hz <= a["high_hz"]]


def ensure_registry_files(store):
    """Copy the shipped allocation table into the data directory."""
    target = store.path("registry", "allocations.json")
    if not os.path.isfile(target):
        store.write_json(allocations(), "registry", "allocations.json")


def seed_local_registry(store):
    """Seed the local layer once, if it has never been seeded."""
    marker = store.path("registry", "seeded.json")
    if os.path.isfile(marker):
        return 0
    count = 0
    for entry in seed_entries():
        store.append_local_registry(entry)
        count += 1
    store.write_json({"seeded": True, "entries": count}, "registry", "seeded.json")
    return count


def _criterion(passed, value, limit):
    return {"passed": bool(passed), "value": value, "limit": limit}


def match_entry(entry, feats):
    """Judge a cluster's features against one registry entry.

    Returns a dict with full (all carried criteria passed), the margin
    record per criterion, and the list of failed criteria. Criteria the
    entry does not carry are not judged and cannot fail.
    """
    margins = {}
    failed = []
    delta = abs(feats.get("center_hz", 0.0) - entry["center_hz"])
    tol = entry["freq_tol_hz"]
    margins["frequency"] = _criterion(delta <= tol, round(delta, 1), tol)
    if delta > tol:
        failed.append("frequency")
    if entry.get("bandwidth_hz"):
        cluster_bw = feats.get("bandwidth_hz", 0.0)
        ratio = cluster_bw / entry["bandwidth_hz"]
        lo = entry.get("bw_ratio_min", 0.5)
        hi = entry.get("bw_ratio_max", 2.0)
        ok = lo <= ratio <= hi
        margin = _criterion(ok, round(ratio, 3), [lo, hi])
        if not ok:
            # A measurement cannot be finer than the observing window's
            # resolution: a narrow entry measured a few bins wide has
            # not failed on bandwidth, it has been measured coarsely.
            resolution = feats.get("resolution_hz")
            if resolution and abs(cluster_bw - entry["bandwidth_hz"]) <= 3.0 * resolution:
                ok = True
                margin = _criterion(True, round(ratio, 3), [lo, hi])
                margin["via"] = "resolution: within 3 bins of the entry bandwidth"
        margins["bandwidth"] = margin
        if not ok:
            failed.append("bandwidth")
    if entry.get("family"):
        fam = feats.get("family", "unknown")
        ok = fam == entry["family"]
        margins["family"] = _criterion(ok, fam, entry["family"])
        if not ok:
            failed.append("family")
    habit = entry.get("habit")
    if habit:
        if habit.get("hours") is not None:
            cluster_hours = set(feats.get("hours_utc", []))
            overlap = len(cluster_hours & set(habit["hours"]))
            ok = bool(cluster_hours) and overlap * 2 >= len(cluster_hours)
            margins["habit_hours"] = _criterion(ok, sorted(cluster_hours), habit["hours"])
            if not ok:
                failed.append("habit_hours")
        if habit.get("min_duty") is not None:
            duty = feats.get("duty_cycle", 0.0)
            ok = duty >= habit["min_duty"]
            margins["habit_duty"] = _criterion(ok, duty, habit["min_duty"])
            if not ok:
                failed.append("habit_duty")
        if habit.get("period_s") is not None:
            gap = feats.get("gap_median_s")
            tol_ratio = habit.get("period_tol_ratio", 0.25)
            ok = gap is not None and abs(gap - habit["period_s"]) <= habit["period_s"] * tol_ratio
            margins["habit_period"] = _criterion(ok, gap, habit["period_s"])
            if not ok:
                failed.append("habit_period")
    passed_count = sum(1 for m in margins.values() if m["passed"])
    return {
        "entry_id": entry["id"],
        "entry_name": entry["name"],
        "full": not failed,
        "margins": margins,
        "failed": failed,
        "passed_count": passed_count,
        "criteria_count": len(margins),
    }


def find_matches(entries, feats):
    """Split candidate entries into full matches and near matches.

    A near match must pass frequency and at least one other criterion
    while failing at least one: close enough to name, short enough to
    keep. Anything failing frequency is not named at all.
    """
    full = []
    near = []
    for entry in entries:
        result = match_entry(entry, feats)
        if result["full"]:
            full.append(result)
        elif (result["margins"].get("frequency", {}).get("passed")
              and result["passed_count"] >= 2 and result["failed"]):
            near.append(result)
    full.sort(key=lambda r: -r["passed_count"])
    near.sort(key=lambda r: -r["passed_count"])
    return full, near
