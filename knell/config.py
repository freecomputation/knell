"""Configuration for KNELL.

Defaults live here. A JSON file named by --config, or config.json inside
the data directory, may override any key. Command line flags override the
file. Every value that shapes a verdict (margins, tolerances, budgets) is
written into run headers and packets so a judgment can be re-checked
against the configuration that produced it.
"""

import json
import os

DEFAULTS = {
    # Receivable span and windowing. Defaults follow the design: the full
    # RTL-SDR Blog V4 span in windows of about 2 MHz.
    "span_low_hz": 500_000.0,
    "span_high_hz": 1_750_000_000.0,
    "window_hz": 2_000_000.0,
    "bins_per_window": 64,
    # Fixed survey gain and clock correction. Gain is never automatic.
    "gain_db": 23.0,
    "ppm_error": 0.0,
    # Tier dwells, in seconds per window visit.
    "tier1_dwell_s": 0.1,
    "tier2_dwell_s": 1.0,
    "tier2_sweeps": 5,
    "watch_dwell_s": 1.0,
    # Detection margins, in dB above the rolling baseline.
    "open_margin_db": 6.0,
    "close_margin_db": 3.0,
    "capture_margin_db": 15.0,
    "baseline_history": 9,
    # An event at or above this peak power (dB above floor) marks the
    # window as an overload suspect for the same sweep.
    "overload_peak_db": 55.0,
    # Clustering tolerances.
    "cluster_freq_tol_hz": 25_000.0,
    "cluster_bw_ratio_min": 0.5,
    "cluster_bw_ratio_max": 2.0,
    "habit_hour_slack": 2,
    "habit_min_tolls": 4,
    # Characterisation: a cluster needs at least this many tolls, or one
    # capture, before it can stand as characterised.
    "min_tolls_characterised": 2,
    # INSUFFICIENT RECORD entries expire after this long without a toll.
    "insufficient_expiry_days": 14,
    # Capture storage budget in bytes, and the synthetic capture size.
    "capture_budget_bytes": 512 * 1024 * 1024,
    "capture_sample_rate": 2_400_000,
    "capture_seconds": 0.25,
    # Backend selection: synthetic, replay or rtl.
    "backend": "synthetic",
    "synthetic_seed": 1723,
    "replay_file": "",
    # Hardware arrangement note recorded with each self-portrait.
    "hardware_note": "stock telescopic whip; arrangement unchanged",
    # Coverage accounting window for the doctor.
    "coverage_lookback_days": 7,
}


class Config:
    def __init__(self, values=None):
        merged = dict(DEFAULTS)
        if values:
            for key, value in values.items():
                if key in merged:
                    merged[key] = value
        self.values = merged

    def __getattr__(self, name):
        try:
            return self.values[name]
        except KeyError:
            raise AttributeError(name)

    def get(self, name, default=None):
        return self.values.get(name, default)

    def window_count(self):
        span = self.values["span_high_hz"] - self.values["span_low_hz"]
        width = self.values["window_hz"]
        count = int(span // width)
        if span % width:
            count += 1
        return count

    def window_bounds(self, index):
        low = self.values["span_low_hz"] + index * self.values["window_hz"]
        high = min(low + self.values["window_hz"], self.values["span_high_hz"])
        return low, high

    def bin_step_hz(self):
        return self.values["window_hz"] / self.values["bins_per_window"]

    def to_dict(self):
        return dict(self.values)


def load_config(data_dir, config_path=None, overrides=None):
    """Load configuration: defaults, then file, then explicit overrides."""
    values = {}
    candidates = []
    if config_path:
        candidates.append(config_path)
    if data_dir:
        candidates.append(os.path.join(data_dir, "config.json"))
    for path in candidates:
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                values.update(json.load(handle))
            break
    if overrides:
        values.update(overrides)
    return Config(values)
