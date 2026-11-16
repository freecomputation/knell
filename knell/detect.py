"""Detection: energy against a rolling baseline.

Each bin of each window keeps a rolling baseline estimated from its own
recent history. The estimate is a median over the last few sweeps, which
keeps it robust to the signals themselves: a signal present in a minority
of recent sweeps does not raise the floor it is measured against. An
event opens where a run of bins rises at least the open margin above the
baseline and closes when it falls back under the close margin.

The temporal baseline alone has a blind spot: a signal that is constant
in a few bins is present in every sweep, so its own level becomes its
baseline and it absorbs itself. The anchor against that is spatial: the
floor of a window is also estimated from the current row itself, as a
low percentile of its bins, since in most windows most bins are empty.
A bin's effective baseline is the lower of its temporal median and the
window floor estimate plus a small allowance for ripple. A constant
narrowband signal therefore cannot hide in its own history. A raise of
the whole window at once still absorbs, and honestly so: to an energy
detector that is a change of floor, not a signal.

Detection works on rows produced by any backend. It is pure bookkeeping
over lists of floats, which is what the survey host's processor budget
allows.
"""

import statistics

# Allowance above the window floor estimate when the spatial anchor is
# the lower baseline: covers per-bin ripple and filter shape, so a bin
# whose true floor sits a little above the window's low percentile is
# not falsely hot.
SPATIAL_ALLOWANCE_DB = 3.0


def _spatial_floor(powers):
    """A low percentile of the row's bins: the window's own floor."""
    ordered = sorted(powers)
    index = max(0, int(0.10 * len(ordered)))
    return ordered[index]


class BaselineTracker:
    """Rolling per-bin baselines for every window, with bounded history.

    History is held per (window, bin). state_dict()/load_state_dict()
    persist the medians between runs so a fresh run starts from the
    floor the last run measured, and in-run history rebuilds from there.
    """

    def __init__(self, history=9, seed_medians=None):
        self.history = max(3, history)
        self.samples = {}  # (window, bin) -> [recent power values]
        self.medians = {}  # (window, bin) -> float
        self.seeded_windows = set()
        if seed_medians:
            for key, value in seed_medians.items():
                window, _, bin_index = key.partition(":")
                self.medians[(int(window), int(bin_index))] = float(value)
                self.seeded_windows.add(int(window))

    def baseline_for(self, window, bin_index, current):
        samples = self.samples.get((window, bin_index))
        if samples:
            return statistics.median(samples)
        seeded = self.medians.get((window, bin_index))
        if seeded is not None:
            return seeded
        return current

    def observe(self, row):
        window = int(row["window"])
        for bin_index, power in enumerate(row["powers"]):
            key = (window, bin_index)
            samples = self.samples.setdefault(key, [])
            samples.append(power)
            if len(samples) > self.history:
                del samples[: len(samples) - self.history]
            self.medians[key] = statistics.median(samples)

    def state_dict(self):
        return {"%d:%d" % key: value for key, value in self.medians.items()}

    def warm(self, window, bin_count):
        """True when a window's baseline is trustworthy enough to judge.

        A window seeded from a previous run's medians is warm at once.
        A window never seen before needs two sweeps of its own history:
        the first sweep only seeds the baseline, because with no prior
        floor the honest baseline for a bin is its current value, and
        nothing can rise above itself.
        """
        if window in self.seeded_windows:
            return True
        seen = sum(len(values) for (w, _b), values in self.samples.items()
                   if w == window)
        return seen >= bin_count * 2


def _segments(row, baselines, open_margin):
    """Contiguous bin runs at or above baseline + open margin."""
    segments = []
    start = None
    for i, power in enumerate(row["powers"]):
        hot = power >= baselines[i] + open_margin
        if hot and start is None:
            start = i
        elif not hot and start is not None:
            segments.append((start, i - 1))
            start = None
    if start is not None:
        segments.append((start, len(row["powers"]) - 1))
    return segments


class Detector:
    """Turns a stream of rows for one window into events.

    Rows for a window are fed in time order. A segment that stays hot
    across consecutive sweeps grows one open event; when a sweep no
    longer shows the segment, the event closes. Events carry the shape
    of their mean spectrum so characterisation can judge the outline.
    """

    def __init__(self, config, tracker=None):
        self.config = config
        self.tracker = tracker or BaselineTracker(history=config.baseline_history)
        self.open_events = {}  # (window, first_bin) -> event dict in progress

    def feed(self, row):
        """Feed one row; return a list of events closed by this row."""
        cfg = self.config
        window = int(row["window"])
        spatial = _spatial_floor(row["powers"]) + SPATIAL_ALLOWANCE_DB
        baselines = [min(self.tracker.baseline_for(window, i, p), spatial)
                     for i, p in enumerate(row["powers"])]
        closed = []
        if self.tracker.warm(window, len(row["powers"])):
            segments = _segments(row, baselines, cfg.open_margin_db)
        else:
            segments = []
        live_keys = set()
        for (first, last) in segments:
            key = self._match_open(window, first, last)
            seg_powers = row["powers"][first:last + 1]
            seg_base = baselines[first:last + 1]
            peak = max(seg_powers)
            peak_above = peak - seg_base[seg_powers.index(peak)]
            if key is None:
                event = {
                    "window": window,
                    "start_ts": row["ts"],
                    "stop_ts": row["ts"] + row.get("dwell_s", 0.0),
                    "first_bin": first,
                    "last_bin": last,
                    "sweeps": 0,
                    "spectrum_sum": [0.0] * (last - first + 1),
                    "peak_db_above_floor": peak_above,
                    "sum_above": 0.0,
                    "overload": bool(row.get("overload")),
                    "rows": [],
                }
                key = (window, first)
                self.open_events[key] = event
            event = self.open_events[key]
            live_keys.add(key)
            event["stop_ts"] = row["ts"] + row.get("dwell_s", 0.0)
            event["sweeps"] += 1
            width = last - first + 1
            if width != len(event["spectrum_sum"]):
                merged = [0.0] * width
                for i in range(min(width, len(event["spectrum_sum"]))):
                    merged[i] = event["spectrum_sum"][i]
                event["spectrum_sum"] = merged
                event["first_bin"] = first
                event["last_bin"] = last
            for i in range(width):
                event["spectrum_sum"][i] += row["powers"][first + i]
            event["peak_db_above_floor"] = max(event["peak_db_above_floor"], peak_above)
            event["sum_above"] += sum(p - b for p, b in zip(seg_powers, seg_base))
            event["overload"] = event["overload"] or bool(row.get("overload"))
            event["rows"].append(row["ts"])
        for key in list(self.open_events):
            if key[0] == window and key not in live_keys:
                closed.append(self._finish(self.open_events.pop(key), row))
        self.tracker.observe(row)
        return closed

    def _match_open(self, window, first, last):
        for key, event in self.open_events.items():
            if key[0] != window:
                continue
            if first <= event["last_bin"] + 1 and last >= event["first_bin"] - 1:
                return key
        return None

    def _finish(self, event, row):
        cfg = self.config
        step = row["step_hz"]
        low = row["low_hz"]
        width_bins = event["last_bin"] - event["first_bin"] + 1
        mean_spectrum = [s / event["sweeps"] for s in event["spectrum_sum"]]
        center_bin = event["first_bin"] + (width_bins - 1) / 2.0
        center_hz = low + (center_bin + 0.5) * step
        mean_above = event["sum_above"] / max(1, event["sweeps"] * width_bins)
        return {
            "window": event["window"],
            "start_ts": event["start_ts"],
            "stop_ts": event["stop_ts"],
            "duration_s": event["stop_ts"] - event["start_ts"],
            "center_hz": round(center_hz, 1),
            "bandwidth_hz": round(width_bins * step, 1),
            "peak_db_above_floor": round(event["peak_db_above_floor"], 2),
            "mean_db_above_floor": round(mean_above, 2),
            "mean_spectrum": [round(v, 2) for v in mean_spectrum],
            "sweeps": event["sweeps"],
            "overload_coincident": event["overload"],
        }

    def flush(self, last_row_by_window):
        """Close every open event at the end of a run."""
        closed = []
        for key, event in list(self.open_events.items()):
            row = last_row_by_window.get(key[0])
            if row is not None:
                closed.append(self._finish(event, row))
            del self.open_events[key]
        return closed
