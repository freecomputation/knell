"""The standing report and the static census page.

The report covers a period: coverage, new clusters, standings changed,
and the census as it stands. The page renders the same census as a
static HTML file in the house form - white page, black text, no
scripts - generated from the data files and never edited by hand. The
page is local by default; publishing it is a separate decision.
"""

import html
import os
import time

from . import census as census_mod
from .store import iso
from .survey import coverage_gaps


def build_report(store, config, ts, period_days=7):
    since = ts - period_days * 86400.0
    gaps, runs = coverage_gaps(store, config, ts, lookback_days=period_days)
    clusters = [c for c in store.clusters() if not c.get("absorbed_by")]
    new_clusters = [c for c in clusters if c["created_ts"] >= since]
    changes = []
    for cluster in clusters:
        for line in cluster.get("history", []):
            if line["ts"] >= since and line["kind"] in ("standing", "expired", "verdict"):
                changes.append((cluster["id"], line))
    doc = census_mod.census_document(store, ts)
    lines = []
    lines.append("KNELL report - %s" % iso(ts))
    lines.append("Period: the last %d days (since %s)." % (period_days, iso(since)))
    lines.append("")
    lines.append("Coverage: %d runs in period; %d of %d windows have no completed "
                 "coverage in the period."
                 % (runs, len(gaps), config.window_count()))
    if gaps:
        shown = ", ".join(str(g) for g in gaps[:20])
        lines.append("Coverage gaps (window indexes): %s%s"
                     % (shown, " ..." if len(gaps) > 20 else ""))
    lines.append("")
    lines.append("New clusters: %d" % len(new_clusters))
    for c in new_clusters:
        f = c.get("features", {})
        lines.append("- %s  %.4f MHz  %s / %s  tolls %d  standing %s"
                     % (c["id"], f.get("center_hz", 0) / 1e6, f.get("outline"),
                        f.get("family"), f.get("toll_count", 0), c.get("standing")))
    lines.append("")
    lines.append("Standings changed: %d" % len(changes))
    for cluster_id, line in changes:
        lines.append("- %s  %s  %s" % (cluster_id, iso(line["ts"]), line["text"]))
    lines.append("")
    counts = doc["active_counts"]
    lines.append("The census as it stands: %s"
                 % (", ".join("%s %d" % (k, v) for k, v in sorted(counts.items())) or "empty"))
    lines.append("Resolved archive: %d entries." % len(doc["resolved"]))
    text = "\n".join(lines) + "\n"
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ts))
    name = "report-%s.txt" % stamp
    with open(store.path("reviews", name), "w", encoding="utf-8") as handle:
        handle.write(text)
    return {"file": name, "text": text}


def render_page(store, config, ts):
    """Render the census as a static page. Returns the file path."""
    doc = census_mod.census_document(store, ts)
    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en"><head><meta charset="utf-8">')
    parts.append("<title>KNELL census</title>")
    parts.append("<style>body{background:#ffffff;color:#000000;"
                 "font-family:Georgia,serif;margin:2em auto;max-width:44em;"
                 "padding:0 1em;line-height:1.45}h1{font-size:1.5em}"
                 "h2{font-size:1.15em;margin-top:1.6em}"
                 "p.meta{color:#000000;font-size:0.9em}</style>")
    parts.append("</head><body>")
    parts.append("<h1>KNELL census</h1>")
    parts.append('<p class="meta">Known-Emitter Nulling and Electromagnetic '
                 "Listening Log. Generated %s. This page is generated from "
                 "the census files and is never edited by hand.</p>" % iso(ts))
    counts = doc["active_counts"]
    parts.append("<p>The census as it stands: %s. Resolved archive: %d entries.</p>"
                 % (html.escape(", ".join("%s %d" % (k, v) for k, v in sorted(counts.items())) or "empty"),
                    len(doc["resolved"])))
    for standing in ("UNEXPLAINED", "UNDER WATCH", "INSUFFICIENT RECORD"):
        entries = doc["active"].get(standing, [])
        parts.append("<h2>%s: %d</h2>" % (standing, len(entries)))
        if not entries:
            parts.append("<p>None.</p>")
        for e in entries:
            parts.append("<p>%s - %.4f MHz, bandwidth %.1f kHz, %s / %s, "
                         "%d tolls, first heard %s, last heard %s.</p>"
                         % (html.escape(e["id"]), e["center_mhz"], e["bandwidth_khz"],
                            html.escape(str(e["outline"])), html.escape(str(e["family"])),
                            e["tolls"], html.escape(str(e["first_heard"])),
                            html.escape(str(e["last_heard"]))))
            for near in e["near_matches"]:
                parts.append("<p>Near match: %s - failed %s.</p>"
                             % (html.escape(near["entry_name"]),
                                html.escape(", ".join(near["failed"]))))
    parts.append("<h2>Resolved: %d</h2>" % len(doc["resolved"]))
    for e in doc["resolved"]:
        parts.append("<p>%s - %s, %.4f MHz, cause: %s.</p>"
                     % (html.escape(e["id"]), html.escape(str(e["standing"])),
                        e["center_mhz"], html.escape(str(e["cause"]))))
    parts.append("</body></html>")
    text = "\n".join(parts) + "\n"
    target = store.path("census", "index.html")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text)
    return target
