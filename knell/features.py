"""Characterisation: the features a judgment can stand on.

Shape comes from the event's mean spectrum. Voice, the modulation
family, is judged from a capture where one exists and is otherwise
recorded as unknown; the judgment is a family, never a protocol. Habit,
strength and stability are properties of a cluster across its tolls.
Every feature here is measurable by the light core or by a named
backend; a feature that cannot be measured is recorded as absent,
never invented.
"""

import math
import statistics


def classify_outline(mean_spectrum):
    """Classify the spectral outline of an event's mean spectrum.

    Returns one of carrier, pair, comb, block, or unknown. The test is
    the shape of the energy: one narrow peak, two peaks, several evenly
    spaced teeth, or a filled block with falling edges.
    """
    if not mean_spectrum:
        return "unknown"
    peak = max(mean_spectrum)
    floor = min(mean_spectrum)
    if peak - floor < 3.0:
        return "unknown"
    threshold = floor + (peak - floor) * 0.6
    hot = [i for i, v in enumerate(mean_spectrum) if v >= threshold]
    if not hot:
        return "unknown"
    groups = []
    start = hot[0]
    prev = hot[0]
    for i in hot[1:]:
        if i > prev + 1:
            groups.append((start, prev))
            start = i
        prev = i
    groups.append((start, prev))
    widths = [b - a + 1 for a, b in groups]
    total = len(mean_spectrum)
    if len(groups) == 1:
        if widths[0] <= 2 and total >= 3:
            return "carrier"
        return "block"
    if len(groups) == 2:
        return "pair"
    if len(groups) >= 3:
        gaps = [groups[i + 1][0] - groups[i][1] for i in range(len(groups) - 1)]
        if gaps and max(gaps) - min(gaps) <= 1:
            return "comb"
        return "comb"
    return "unknown"


def family_from_capture(data):
    """Judge the modulation family from fabricated or real sample bytes.

    The samples are ci8. The judgment uses only envelope behaviour:
    how steady the envelope is, and how much of the span is silence.
    It returns a family, never a protocol: pulsed, constant-envelope,
    varying-envelope, or unknown when the span is too short to judge.
    """
    if not data or len(data) < 64:
        return "unknown"
    amps = []
    for i in range(0, len(data) - 1, 2):
        amps.append(math.hypot(data[i] - 128, data[i + 1] - 128))
    if not amps:
        return "unknown"
    peak = max(amps)
    if peak <= 0:
        return "unknown"
    silent = sum(1 for a in amps if a < peak * 0.15) / len(amps)
    if silent > 0.45:
        return "pulsed"
    mean = statistics.mean(amps)
    if mean <= 0:
        return "unknown"
    variation = statistics.pstdev(amps) / mean
    if variation < 0.45:
        return "constant-envelope"
    return "varying-envelope"


def event_features(event, capture_family=None):
    """The feature record for one event."""
    return {
        "center_hz": event["center_hz"],
        "bandwidth_hz": event["bandwidth_hz"],
        "outline": classify_outline(event.get("mean_spectrum", [])),
        "family": capture_family or "unknown",
        "peak_db_above_floor": event["peak_db_above_floor"],
        "mean_db_above_floor": event["mean_db_above_floor"],
        "duration_s": event["duration_s"],
    }


def cluster_features(events, config):
    """Aggregate a cluster's features from its events (its tolls).

    events are event records in time order. The record keeps spreads,
    not just means: strength variation and frequency drift are evidence.
    """
    if not events:
        return {}
    centers = [e["center_hz"] for e in events]
    bandwidths = [e["bandwidth_hz"] for e in events]
    peaks = [e["peak_db_above_floor"] for e in events]
    durations = [e["duration_s"] for e in events]
    starts = [e["start_ts"] for e in events]
    gaps = [starts[i + 1] - events[i]["stop_ts"] for i in range(len(events) - 1)]
    hours = sorted({int((e["start_ts"] // 3600) % 24) for e in events})
    outlines = [classify_outline(e.get("mean_spectrum", [])) for e in events]
    outline = statistics.mode(outlines) if outlines else "unknown"
    families = [e.get("family", "unknown") for e in events]
    known_families = [f for f in families if f != "unknown"]
    family = statistics.mode(known_families) if known_families else "unknown"
    observed_span = (events[-1]["stop_ts"] - events[0]["start_ts"]) if len(events) > 1 else durations[0]
    on_time = sum(durations)
    center = statistics.median(centers)
    instrument_error_hz = abs(center) * float(config.ppm_error) / 1_000_000.0
    return {
        "center_hz": round(center, 1),
        "center_min_hz": min(centers),
        "center_max_hz": max(centers),
        "drift_hz": round(max(centers) - min(centers), 1),
        "instrument_error_hz": round(instrument_error_hz, 1),
        "bandwidth_hz": round(statistics.median(bandwidths), 1),
        "resolution_hz": round(config.window_hz / config.bins_per_window, 1),
        "outline": outline,
        "family": family,
        "has_capture": any(e.get("capture") for e in events),
        "toll_count": len(events),
        "first_ts": events[0]["start_ts"],
        "last_ts": events[-1]["stop_ts"],
        "peak_db_mean": round(statistics.mean(peaks), 2),
        "peak_db_min": min(peaks),
        "peak_db_max": max(peaks),
        "duration_median_s": round(statistics.median(durations), 3),
        "gap_median_s": round(statistics.median(gaps), 3) if gaps else None,
        "gap_cv": round(statistics.pstdev(gaps) / statistics.mean(gaps), 3)
                  if len(gaps) > 1 and statistics.mean(gaps) > 0 else None,
        "duty_cycle": round(on_time / observed_span, 4) if observed_span > 0 else 1.0,
        "hours_utc": hours,
    }
