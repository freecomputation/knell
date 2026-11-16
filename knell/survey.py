"""Survey orchestration: the tiered survey, the watch, the silence test.

A run captures spectrum rows through a backend, detects events against
the rolling baseline, keeps captures for the events that earn them,
assigns events to clusters, and finishes with a census judgment pass.
Coverage is recorded window by window as the run actually went: a
window the run never reached is a gap with a reason, never a silence
the record stays quiet about.
"""

import os
import time

from . import census as census_mod
from . import captures as captures_mod
from . import cluster as cluster_mod
from . import features as features_mod
from .backends import (BackendError, BackendUnavailable, ReplayExhausted,
                        TunerBusy, acquire_tuner, make_backend, release_tuner)
from .detect import BaselineTracker, Detector
from .store import iso, run_id_for


def _interesting_windows(store, config, run_events):
    """Windows a tier 2 dwell pass should linger on."""
    windows = set()
    for event in run_events:
        windows.add(int(event["window"]))
    for cluster in store.clusters():
        if cluster.get("absorbed_by"):
            continue
        center = cluster.get("features", {}).get("center_hz")
        if center:
            windows.add(int((center - config.span_low_hz) // config.window_hz))
    for entry in store.local_registry():
        center = entry["center_hz"]
        windows.add(int((center - config.span_low_hz) // config.window_hz))
    return sorted(w for w in windows if 0 <= w < config.window_count())


def _enrich_event(store, config, backend, raw, run_id):
    """Turn a detector event into a stored event record with evidence."""
    number = store.next_id("event")
    event = dict(raw)
    event["id"] = "E%07d" % number
    event["run_id"] = run_id
    event["outline"] = features_mod.classify_outline(raw.get("mean_spectrum", []))
    event["family"] = "unknown"
    event["capture"] = None
    event["capture_note"] = None
    if raw["peak_db_above_floor"] >= config.capture_margin_db:
        if backend.supports_captures:
            made = backend.capture(raw["center_hz"], raw["bandwidth_hz"],
                                   raw["start_ts"], event["id"])
            if made is not None:
                data, meta = made
                event["family"] = features_mod.family_from_capture(data)
                entry = captures_mod.write_capture(store, config, event, data, meta)
                if entry is not None:
                    event["capture"] = entry["file"]
                else:
                    event["capture_note"] = "capture dropped: storage budget"
        else:
            event["capture_note"] = ("capture unavailable: backend %s provides "
                                     "spectrum only" % backend.name)
    return event


def _run_capture_phase(store, config, backend, windows_plan, header, ts_now):
    """Execute a capture plan: a list of (window, dwell, sweeps) visits.

    Returns (events, last_rows). Coverage and notes are written into the
    header as the run goes.
    """
    state = store.state()
    tracker = BaselineTracker(history=config.baseline_history,
                              seed_medians=state.get("baselines", {}))
    detector = Detector(config, tracker=tracker)
    rows_file = os.path.join(store.path("runs", header["id"]), "rows.jsonl")
    events = []
    last_rows = {}
    interrupted = False
    with open(rows_file, "a", encoding="utf-8") as rows_handle:
        import json as _json
        for (window, dwell, sweeps) in windows_plan:
            low, high = config.window_bounds(window)
            entry = {"window": window, "low_hz": low, "high_hz": high,
                     "dwell_s": dwell, "sweeps": 0, "completed": False, "note": None}
            header["coverage"].append(entry)
            if interrupted:
                entry["note"] = "not reached: run interrupted"
                continue
            try:
                for _ in range(sweeps):
                    row = backend.sweep(window, low, high, dwell)
                    rows_handle.write(_json.dumps(row, sort_keys=True) + "\n")
                    last_rows[window] = row
                    entry["sweeps"] += 1
                    for raw in detector.feed(row):
                        events.append(_enrich_event(store, config, backend, raw, header["id"]))
                entry["completed"] = entry["sweeps"] == sweeps
                if not entry["completed"]:
                    entry["note"] = "partial: %d of %d sweeps" % (entry["sweeps"], sweeps)
            except TunerBusy as exc:
                entry["note"] = "tuner busy: %s" % exc
                header["notes"].append("tuner busy at window %d: %s" % (window, exc))
                interrupted = True
            except ReplayExhausted as exc:
                entry["note"] = "no data: %s" % exc
            except BackendError as exc:
                entry["note"] = "backend error: %s" % exc
                header["notes"].append("window %d: %s" % (window, exc))
    for raw in detector.flush(last_rows):
        events.append(_enrich_event(store, config, backend, raw, header["id"]))
    state = store.state()
    state["baselines"] = tracker.state_dict()
    store.save_state(state)
    return events


def _finish_run(store, config, header, events, ts_end):
    for event in events:
        store.append_event(event)
    assigned, opened = cluster_mod.assign_events(store, config, ts_end)
    summary = census_mod.run_pass(store, config, ts_end)
    census_mod.write_census_files(store, ts_end)
    header["ts_end"] = ts_end
    header["events"] = len(events)
    header["clusters_assigned"] = assigned
    header["clusters_opened"] = opened
    header["census_summary"] = summary
    store.write_json(header, "runs", header["id"], "header.json")
    return {"header": header, "events": events, "census": summary}


def _new_header(store, kind, backend_name, config, ts_start, extra=None):
    header = {
        "id": run_id_for(ts_start, kind),
        "kind": kind,
        "ts_start": ts_start,
        "ts_end": None,
        "backend": backend_name,
        "gain_db": config.gain_db,
        "ppm_error": config.ppm_error,
        "margins": {"open_db": config.open_margin_db,
                    "close_db": config.close_margin_db,
                    "capture_db": config.capture_margin_db},
        "span": {"low_hz": config.span_low_hz, "high_hz": config.span_high_hz,
                 "window_hz": config.window_hz},
        "coverage": [],
        "notes": [],
    }
    if extra:
        header.update(extra)
    os.makedirs(store.path("runs", header["id"]), exist_ok=True)
    store.write_json(header, "runs", header["id"], "header.json")
    return header


def run_survey(store, config, backend_name=None, tiers=(1, 2), ts_start=None,
               scenario=None):
    """Run the tiered survey. Returns the run summary dict."""
    virtual = ts_start is not None
    ts_start = ts_start if ts_start is not None else time.time()
    name = backend_name or config.backend
    backend = make_backend(name, config, store=store, start_ts=ts_start, scenario=scenario)
    ok, reason = backend.available()
    header = _new_header(store, "survey", name, config, ts_start,
                         {"tiers": list(tiers)})
    if not ok:
        header["notes"].append("backend unavailable: %s" % reason)
        for window in range(config.window_count()):
            low, high = config.window_bounds(window)
            header["coverage"].append({"window": window, "low_hz": low, "high_hz": high,
                                       "dwell_s": 0.0, "sweeps": 0, "completed": False,
                                       "note": "backend unavailable: %s" % reason})
        return _finish_run(store, config, header, [], _end_ts(virtual, backend, ts_start))
    plan = []
    if 1 in tiers:
        plan += [(w, config.tier1_dwell_s, 1) for w in range(config.window_count())]
    events = []
    locked = False
    try:
        if name == "rtl":
            try:
                acquire_tuner(store)
                locked = True
            except TunerBusy as exc:
                header["notes"].append("tuner busy before the run began: %s" % exc)
                for window in range(config.window_count()):
                    low, high = config.window_bounds(window)
                    header["coverage"].append({
                        "window": window, "low_hz": low, "high_hz": high,
                        "dwell_s": 0.0, "sweeps": 0, "completed": False,
                        "note": "gap: tuner busy (%s)" % exc})
                return _finish_run(store, config, header, [],
                                   _end_ts(virtual, backend, ts_start))
        events = _run_capture_phase(store, config, backend, plan, header, ts_start)
        if 2 in tiers:
            interesting = _interesting_windows(store, config, events)
            plan2 = [(w, config.tier2_dwell_s, config.tier2_sweeps) for w in interesting]
            more = _run_capture_phase(store, config, backend, plan2, header, ts_start)
            events = events + more
    finally:
        if locked:
            release_tuner(store)
    return _finish_run(store, config, header, events, _end_ts(virtual, backend, ts_start))


def _backend_end(backend, fallback):
    clock = getattr(backend, "clock", None)
    return clock if clock is not None else fallback


def _end_ts(virtual, backend, start):
    """End time for a run. A run started at an explicit time (a test or
    a replay) ends on the backend's own clock; a real run ends now."""
    if virtual:
        return _backend_end(backend, start)
    return time.time()


def run_watch(store, config, cluster_id, span_s, backend_name=None, ts_start=None,
              scenario=None):
    """Tier 3: park the tuner on one cluster's frequency for a span."""
    from . import UNEXPLAINED, UNDER_WATCH
    from .cluster import add_history
    virtual = ts_start is not None
    ts_start = ts_start if ts_start is not None else time.time()
    cluster = store.load_cluster(cluster_id)
    if cluster is None:
        raise ValueError("no such cluster: %s" % cluster_id)
    center = cluster.get("features", {}).get("center_hz")
    if not center:
        raise ValueError("cluster %s has no measured centre frequency" % cluster_id)
    window = int((center - config.span_low_hz) // config.window_hz)
    window = max(0, min(window, config.window_count() - 1))
    name = backend_name or config.backend
    backend = make_backend(name, config, store=store, start_ts=ts_start, scenario=scenario)
    ok, reason = backend.available()
    header = _new_header(store, "watch", name, config, ts_start,
                         {"cluster_id": cluster_id, "window": window, "span_s": span_s})
    previous_standing = cluster.get("standing")
    cluster["watch"] = {"source": "watch", "started_ts": ts_start}
    if cluster.get("standing") in (UNEXPLAINED, None):
        cluster["standing"] = UNDER_WATCH
        add_history(cluster, ts_start, "standing",
                    "%s -> UNDER WATCH: watch begun" % (previous_standing or "new"))
    store.save_cluster(cluster)
    events = []
    locked = False
    try:
        if not ok:
            header["notes"].append("backend unavailable: %s" % reason)
            low, high = config.window_bounds(window)
            header["coverage"].append({"window": window, "low_hz": low, "high_hz": high,
                                       "dwell_s": 0.0, "sweeps": 0, "completed": False,
                                       "note": "backend unavailable: %s" % reason})
        else:
            busy = False
            if name == "rtl":
                try:
                    acquire_tuner(store)
                    locked = True
                except TunerBusy as exc:
                    busy = True
                    header["notes"].append("tuner busy before the watch began: %s" % exc)
                    low, high = config.window_bounds(window)
                    header["coverage"].append({
                        "window": window, "low_hz": low, "high_hz": high,
                        "dwell_s": 0.0, "sweeps": 0, "completed": False,
                        "note": "gap: tuner busy (%s)" % exc})
            if not busy:
                sweeps = max(1, int(span_s / config.watch_dwell_s))
                events = _run_capture_phase(store, config, backend,
                                            [(window, config.watch_dwell_s, sweeps)],
                                            header, ts_start)
    finally:
        if locked:
            release_tuner(store)
    ts_end = _end_ts(virtual, backend, ts_start)
    result = _finish_run(store, config, header, events, ts_end)
    cluster = store.load_cluster(cluster_id)
    if cluster is not None and cluster.get("watch", {}).get("source") == "watch":
        cluster["watch"] = None
        if cluster.get("standing") == UNDER_WATCH:
            cluster["standing"] = UNEXPLAINED
            add_history(cluster, ts_end, "standing",
                        "UNDER WATCH -> UNEXPLAINED: watch complete; "
                        "standing returns pending judgment")
            store.save_cluster(cluster)
            census_mod.write_census_files(store, ts_end)
    return result


def run_silence(store, config, backend_name=None, ts_start=None, scenario=None,
                hardware_note=None):
    """The silence test: survey with the port terminated, then portrait.

    For the synthetic backend the terminated sky contains only the
    instrument's own spurs. For the rtl backend the operator asserts
    the terminated state with the call itself; the run header records
    the hardware note either way.
    """
    virtual = ts_start is not None
    ts_start = ts_start if ts_start is not None else time.time()
    name = backend_name or config.backend
    if name == "replay":
        raise BackendUnavailable("the silence test needs a live or synthetic backend")
    backend = make_backend(name, config, store=store, start_ts=ts_start,
                           terminated=True, scenario=scenario)
    ok, reason = backend.available()
    header = _new_header(store, "silence", name, config, ts_start,
                         {"terminated": True,
                          "hardware_note": hardware_note or config.hardware_note})
    events = []
    locked = False
    try:
        if not ok:
            header["notes"].append("backend unavailable: %s" % reason)
            for window in range(config.window_count()):
                low, high = config.window_bounds(window)
                header["coverage"].append({"window": window, "low_hz": low, "high_hz": high,
                                           "dwell_s": 0.0, "sweeps": 0, "completed": False,
                                           "note": "backend unavailable: %s" % reason})
        else:
            busy = False
            if name == "rtl":
                try:
                    acquire_tuner(store)
                    locked = True
                except TunerBusy as exc:
                    busy = True
                    header["notes"].append("tuner busy before the silence run began: %s" % exc)
                    for window in range(config.window_count()):
                        low, high = config.window_bounds(window)
                        header["coverage"].append({
                            "window": window, "low_hz": low, "high_hz": high,
                            "dwell_s": 0.0, "sweeps": 0, "completed": False,
                            "note": "gap: tuner busy (%s)" % exc})
            if not busy:
                plan = [(w, config.tier1_dwell_s, 1) for w in range(config.window_count())]
                events = _run_capture_phase(store, config, backend, plan, header, ts_start)
    finally:
        if locked:
            release_tuner(store)
    ts_end = _end_ts(virtual, backend, ts_start)
    result = _finish_run(store, config, header, events, ts_end)
    portrait = _build_portrait(store, header, events, ts_end)
    result["portrait"] = portrait
    # A second pass so the fresh portrait judges the whole census.
    summary = census_mod.run_pass(store, config, ts_end)
    census_mod.write_census_files(store, ts_end)
    result["census_after_portrait"] = summary
    return result


def _build_portrait(store, header, events, ts):
    import statistics
    groups = {}
    for event in events:
        key = round(event["center_hz"] / 25_000.0)
        groups.setdefault(key, []).append(event)
    signals = []
    for key in sorted(groups):
        group = groups[key]
        signals.append({
            "center_hz": round(statistics.median([e["center_hz"] for e in group]), 1),
            "bandwidth_hz": round(statistics.median([e["bandwidth_hz"] for e in group]), 1),
            "outline": group[0].get("outline", "unknown"),
            "mean_peak_db": round(statistics.mean([e["peak_db_above_floor"] for e in group]), 2),
            "events": len(group),
        })
    portrait = {
        "id": run_id_for(ts, "self"),
        "ts": ts,
        "run_id": header["id"],
        "hardware_note": header.get("hardware_note"),
        "signals": signals,
    }
    store.save_portrait(portrait)
    return portrait


def coverage_gaps(store, config, now_ts, lookback_days=None):
    """Windows with no completed coverage inside the lookback window.

    Returns (gap_windows, runs_considered). A gap is recorded as a gap:
    the absence of a visit, stated as such.
    """
    lookback = lookback_days if lookback_days is not None else config.coverage_lookback_days
    cutoff = now_ts - lookback * 86400.0
    covered = set()
    runs = 0
    runs_dir = store.path("runs")
    if os.path.isdir(runs_dir):
        for name in sorted(os.listdir(runs_dir)):
            header = store.read_json("runs", name, "header.json", default=None)
            if not header or header.get("ts_start", 0) < cutoff:
                continue
            runs += 1
            for entry in header.get("coverage", []):
                if entry.get("completed"):
                    covered.add(entry["window"])
    gaps = [w for w in range(config.window_count()) if w not in covered]
    return gaps, runs
