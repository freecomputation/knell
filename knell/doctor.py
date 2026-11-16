"""The doctor: health of the whole arrangement, reported plainly.

Backends present or absent, tuner state, storage against budget, days
since the last self-portrait, coverage gaps. Absent pieces are reported
as absent. The doctor never repairs anything silently; it reports.
"""

import os
import time

from . import __version__
from . import captures as captures_mod
from .backends import backend_status, tuner_state
from .survey import coverage_gaps


def run_doctor(store, config, ts=None):
    ts = ts if ts is not None else time.time()
    lines = []
    lines.append("KNELL doctor - %s" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)))
    lines.append("Version: %s. Data directory: %s" % (__version__, store.data_dir))
    lines.append("")
    lines.append("Backends:")
    for status in backend_status(config):
        mark = "present" if status["available"] else "absent"
        lines.append("- %s: %s - %s (captures: %s)"
                     % (status["name"], mark, status["reason"],
                        "yes" if status["supports_captures"] else "no"))
    lines.append("")
    state = tuner_state(store)
    if not state["held"]:
        lines.append("Tuner: no knell lock held. (This says nothing about other "
                     "programs; the lock is KNELL's own claim only.)")
    else:
        lines.append("Tuner: knell lock held by pid %s (alive: %s)."
                     % (state.get("holder"), state.get("alive")))
    lines.append("")
    manifest = captures_mod.load_manifest(store)
    used = captures_mod.total_bytes(manifest)
    lines.append("Captures: %d files, %d bytes against a budget of %d bytes (%.1f%%)."
                 % (len(manifest), used, config.capture_budget_bytes,
                    (100.0 * used / config.capture_budget_bytes) if config.capture_budget_bytes else 0.0))
    dropped = store.read_jsonl("captures", "dropped.jsonl")
    lines.append("Captures dropped by rotation: %d (see captures/dropped.jsonl)." % len(dropped))
    lines.append("")
    portrait = store.latest_portrait()
    if portrait is None:
        lines.append("Self-portrait: none taken. The instrument has not yet mapped "
                     "its own noise; run knell silence with the port terminated.")
    else:
        days = (ts - portrait["ts"]) / 86400.0
        lines.append("Self-portrait: last taken %s (%.1f days ago), %d self signals, "
                     "run %s."
                     % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(portrait["ts"])),
                        days, len(portrait.get("signals", [])), portrait.get("run_id")))
    lines.append("")
    gaps, runs = coverage_gaps(store, config, ts)
    lines.append("Coverage: %d runs in the last %d days; %d of %d windows uncovered "
                 "in that window."
                 % (runs, config.coverage_lookback_days, len(gaps), config.window_count()))
    if gaps and len(gaps) <= 40:
        lines.append("Uncovered windows: %s" % ", ".join(str(g) for g in gaps))
    lines.append("")
    clusters = store.clusters()
    by_standing = {}
    for cluster in clusters:
        by_standing[cluster.get("standing")] = by_standing.get(cluster.get("standing"), 0) + 1
    lines.append("Clusters on file: %d (%s)."
                 % (len(clusters),
                    ", ".join("%s %d" % (k, v) for k, v in sorted(by_standing.items(), key=lambda kv: str(kv[0])))))
    lines.append("Registry: %d local entries; %d events on file."
                 % (len(store.local_registry()), len(store.events())))
    return "\n".join(lines) + "\n"
