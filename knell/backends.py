"""Capture backends, in the house runner pattern.

A backend produces spectrum rows: one row is one sweep of one window, a
list of power values in dB across the window's bins. Backends are runners:
when the tool a backend needs is absent, the backend reports itself
unavailable with a reason. Nothing in KNELL crashes because a backend is
missing, and nothing pretends an absent backend produced data.

Three backends ship in the first version:

- rtl - drives rtl_power from the rtl-sdr suite when it is installed.
  Spectrum only: it cannot produce sample captures, and event records say
  so rather than pretending otherwise.
- replay - replays spectrum rows recorded earlier, either KNELL rows in
  JSONL or an rtl_power CSV file. Also spectrum only.
- synthetic - generates a small fake sky from a seeded scenario, so the
  whole pipeline runs and is testable with no hardware at all. Its
  captures are fabricated sample spans and are labelled synthetic in
  their SigMF metadata.
"""

import hashlib
import json
import math
import os
import random
import shutil
import subprocess

from .store import iso


class BackendUnavailable(Exception):
    """The backend cannot run here at all (tool absent, file absent)."""


class TunerBusy(Exception):
    """The tuner is held by another process. KNELL reports and yields."""


class BackendError(Exception):
    """The backend ran and failed for one window or sweep."""


class ReplayExhausted(BackendError):
    """A replay backend has no more rows for a window."""


# ----------------------------------------------------------------------
# Tuner lock. Only hardware runs take it. A lock whose pid is dead is
# stale and may be taken over; a lock with a live pid is a claim KNELL
# yields to, per the tuner law.
# ----------------------------------------------------------------------

def tuner_lock_path(store):
    return store.path("tuner.lock")


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_tuner(store):
    path = tuner_lock_path(store)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                holder = int(handle.read().strip() or "0")
        except (ValueError, OSError):
            holder = 0
        if holder and holder != os.getpid() and _pid_alive(holder):
            raise TunerBusy("tuner held by pid %d (knell lock)" % holder)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def release_tuner(store):
    path = tuner_lock_path(store)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            holder = int(handle.read().strip() or "0")
        if holder == os.getpid():
            os.unlink(path)
    except (ValueError, OSError):
        pass


def tuner_state(store):
    path = tuner_lock_path(store)
    if not os.path.isfile(path):
        return {"held": False}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            holder = int(handle.read().strip() or "0")
    except (ValueError, OSError):
        return {"held": True, "holder": None, "note": "lock file unreadable"}
    return {"held": True, "holder": holder, "alive": _pid_alive(holder) if holder else False}


# ----------------------------------------------------------------------
# Base class
# ----------------------------------------------------------------------

class Backend:
    name = "base"
    supports_captures = False

    def available(self):
        return True, "available"

    def sweep(self, window_index, low_hz, high_hz, dwell_s):
        """Return one spectrum row dict for one sweep of one window."""
        raise NotImplementedError

    def capture(self, center_hz, bandwidth_hz, ts, tag):
        """Return (data_bytes, meta_dict) for a sample capture, or None."""
        return None


# ----------------------------------------------------------------------
# Synthetic backend: a small fake sky, seeded and deterministic.
# ----------------------------------------------------------------------

def default_scenario():
    """The standard fake sky. Frequencies are the universal ones the seed
    registry knows, plus unknowns, self spurs and an overload phantom, so
    a demo run exercises every judgment path the design defines."""
    return [
        # Heard in normal and terminated runs alike: the instrument itself.
        {"center_hz": 28_800_000.0, "bandwidth_hz": 30_000.0, "outline": "carrier",
         "family": "constant-envelope", "power_db": 22.0,
         "pattern": {"type": "constant"}, "self_spur": True},
        {"center_hz": 57_600_000.0, "bandwidth_hz": 30_000.0, "outline": "carrier",
         "family": "constant-envelope", "power_db": 18.0,
         "pattern": {"type": "constant"}, "self_spur": True},
        # A universal service the seed registry can null on full criteria.
        # Pulse-position traffic: on the air about half the time, in
        # bursts, which is how the real service behaves.
        {"center_hz": 1_090_000_000.0, "bandwidth_hz": 2_000_000.0, "outline": "block",
         "family": "pulsed", "power_db": 30.0,
         "pattern": {"type": "periodic", "period_s": 2.0, "on_s": 1.0}},
        # A second universal service, narrow and constant.
        {"center_hz": 15_000_000.0, "bandwidth_hz": 40_000.0, "outline": "carrier",
         "family": "varying-envelope", "power_db": 26.0,
         "pattern": {"type": "constant"}},
        # Near match: right frequency for a seeded service, wrong bandwidth.
        {"center_hz": 137_620_000.0, "bandwidth_hz": 400_000.0, "outline": "block",
         "family": "constant-envelope", "power_db": 24.0,
         "pattern": {"type": "constant"}},
        # Wholly unknown: a periodic narrow emitter in an unlicensed band.
        {"center_hz": 433_920_000.0, "bandwidth_hz": 60_000.0, "outline": "carrier",
         "family": "pulsed", "power_db": 28.0,
         "pattern": {"type": "periodic", "period_s": 20.0, "on_s": 3.0}},
        # One weak blip, seen once: an insufficient record in the making.
        # Its offset is set so a tier 1 pass reaches its window while it
        # is on the air.
        {"center_hz": 902_400_000.0, "bandwidth_hz": 50_000.0, "outline": "carrier",
         "family": "pulsed", "power_db": 12.0,
         "pattern": {"type": "once", "at_offset_s": 44.9, "on_s": 0.4}},
        # A strong emitter that overloads the receiver, and its phantom.
        {"center_hz": 101_100_000.0, "bandwidth_hz": 200_000.0, "outline": "block",
         "family": "constant-envelope", "power_db": 62.0,
         "pattern": {"type": "constant"}, "overload": True},
        {"center_hz": 202_200_000.0, "bandwidth_hz": 200_000.0, "outline": "block",
         "family": "constant-envelope", "power_db": 20.0,
         "pattern": {"type": "constant"}, "phantom_of": 7},
    ]


class SyntheticBackend(Backend):
    name = "synthetic"
    supports_captures = True

    def __init__(self, config, scenario=None, terminated=False, start_ts=None):
        self.config = config
        self.seed = int(config.synthetic_seed)
        self.scenario = scenario if scenario is not None else default_scenario()
        self.terminated = terminated
        self.clock = float(start_ts) if start_ts is not None else 1_760_000_000.0
        self.start_ts = self.clock
        self.sweep_count = 0

    def available(self):
        return True, "synthetic backend always available"

    def _emitter_active(self, index, emitter, ts):
        if emitter.get("phantom_of") is not None:
            parent = self.scenario[emitter["phantom_of"]]
            return self._emitter_active(emitter["phantom_of"], parent, ts)
        pattern = emitter["pattern"]
        kind = pattern["type"]
        offset = ts - self.start_ts
        if kind == "constant":
            return True
        if kind == "periodic":
            return (offset % pattern["period_s"]) < pattern["on_s"]
        if kind == "once":
            return pattern["at_offset_s"] <= offset < pattern["at_offset_s"] + pattern["on_s"]
        if kind == "bursty":
            slot = int(offset // pattern["mean_gap_s"])
            rng = random.Random(self.seed + index * 7919 + slot)
            return rng.random() < pattern.get("duty", 0.3)
        return False

    def _floor(self, bin_freq, window_index, bin_index):
        rng = random.Random(self.seed * 31 + window_index * 131 + bin_index)
        jitter = (rng.random() * 2.0 - 1.0) * 1.2
        slope = 2.0 * math.sin(bin_freq / 400_000_000.0)
        return -100.0 + jitter + slope

    def sweep(self, window_index, low_hz, high_hz, dwell_s):
        bins = int(self.config.bins_per_window)
        step = (high_hz - low_hz) / bins
        ts = self.clock
        powers = []
        overload = False
        for b in range(bins):
            freq = low_hz + (b + 0.5) * step
            value = self._floor(freq, window_index, b)
            for index, emitter in enumerate(self.scenario):
                if self.terminated and not emitter.get("self_spur"):
                    continue
                if not self._emitter_active(index, emitter, ts):
                    continue
                contribution = self._contribution(emitter, freq, step)
                if contribution is not None:
                    value = max(value, self._floor(freq, window_index, b) + contribution)
                    if emitter.get("overload"):
                        overload = True
            powers.append(round(value, 2))
        self.clock += dwell_s
        self.sweep_count += 1
        return {
            "ts": ts,
            "window": window_index,
            "low_hz": low_hz,
            "high_hz": high_hz,
            "step_hz": step,
            "dwell_s": dwell_s,
            "powers": powers,
            "overload": overload,
            "backend": self.name,
        }

    def _contribution(self, emitter, freq, step):
        center = emitter["center_hz"]
        bw = emitter["bandwidth_hz"]
        dist = abs(freq - center)
        if dist > bw / 2.0 + step:
            return None
        power = emitter["power_db"]
        outline = emitter["outline"]
        if outline == "carrier":
            if dist <= step * 0.75:
                return power
            if dist <= step * 1.75:
                return power - 20.0
            return None
        if outline == "pair":
            peaks = (center - bw / 4.0, center + bw / 4.0)
            best = None
            for peak in peaks:
                d = abs(freq - peak)
                if d <= step * 0.75:
                    best = power if best is None else max(best, power)
                elif d <= step * 1.75:
                    best = power - 20.0 if best is None else max(best, power - 20.0)
            return best
        if outline == "comb":
            tooth = bw / 6.0
            pos = (freq - (center - bw / 2.0)) % tooth if tooth else step
            if pos <= step * 0.75 or tooth - pos <= step * 0.75:
                return power
            return power - 24.0 if dist <= bw / 2.0 else None
        # block
        if dist <= bw / 2.0 - step:
            return power
        if dist <= bw / 2.0 + step:
            return power - 6.0
        return None

    def _emitter_at(self, center_hz, bandwidth_hz):
        """The scenario emitter a capture at this frequency would hear."""
        best = None
        for emitter in self.scenario:
            reach = max(emitter["bandwidth_hz"], bandwidth_hz) / 2.0
            delta = abs(emitter["center_hz"] - center_hz)
            if delta <= reach and (best is None or delta < best[0]):
                best = (delta, emitter)
        return best[1] if best else None

    def capture(self, center_hz, bandwidth_hz, ts, tag):
        """Fabricate a capture whose envelope behaves like the emitter.

        The samples are synthetic and labelled so in their metadata.
        Their envelope follows the family of the emitter at the capture
        frequency - bursts for a pulsed emitter, a steady carrier for a
        constant-envelope one, a wandering envelope for a varying one -
        because the family judgment downstream reads the envelope, and
        a simulation that cannot reproduce it proves nothing.
        """
        nsamples = int(self.config.capture_sample_rate * self.config.capture_seconds)
        seed = int(hashlib.sha256(("%s|%s" % (tag, ts)).encode("utf-8")).hexdigest()[:12], 16)
        rng = random.Random(seed ^ self.seed)
        emitter = self._emitter_at(center_hz, bandwidth_hz)
        family = emitter["family"] if emitter else "unknown"
        out = bytearray(nsamples * 2)
        phase = rng.random() * 6.283185307179586
        for i in range(nsamples):
            if family == "pulsed":
                amp = 100.0 if (i // 400) % 4 == 0 else 2.0
            elif family == "constant-envelope":
                amp = 90.0 + rng.uniform(-4.0, 4.0)
            elif family == "varying-envelope":
                amp = 70.0 + 55.0 * math.sin(i / 977.0) + rng.uniform(-6.0, 6.0)
            else:
                amp = 26.0 + rng.uniform(-8.0, 8.0)
            phase += 0.11
            ivalue = int(128 + amp * math.cos(phase))
            qvalue = int(128 + amp * math.sin(phase))
            out[2 * i] = min(255, max(0, ivalue))
            out[2 * i + 1] = min(255, max(0, qvalue))
        meta = {
            "core:datatype": "ci8",
            "core:sample_rate": self.config.capture_sample_rate,
            "core:frequency": center_hz,
            "knell:backend": self.name,
            "knell:synthetic": True,
        }
        return bytes(out), meta


# ----------------------------------------------------------------------
# Replay backend
# ----------------------------------------------------------------------

class ReplayBackend(Backend):
    name = "replay"
    supports_captures = False

    def __init__(self, config):
        self.config = config
        self.rows_by_window = {}
        self.pointers = {}
        self._load()

    def _path(self):
        return self.config.replay_file

    def available(self):
        path = self._path()
        if not path:
            return False, "no replay file configured (replay_file is empty)"
        if not os.path.isfile(path):
            return False, "replay file not found: %s" % path
        return True, "replaying %s" % path

    def _load(self):
        path = self._path()
        if not path or not os.path.isfile(path):
            return
        if path.endswith(".jsonl"):
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        row = json.loads(line)
                        self.rows_by_window.setdefault(int(row["window"]), []).append(row)
        elif path.endswith(".csv"):
            self._load_rtl_csv(path)

    def _load_rtl_csv(self, path):
        cfg = self.config
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 7:
                    continue
                try:
                    low = float(parts[2]); high = float(parts[3]); step = float(parts[4])
                    powers = [float(p) for p in parts[6:]]
                except ValueError:
                    continue
                for w in range(cfg.window_count()):
                    wlow, whigh = cfg.window_bounds(w)
                    bins = []
                    for i, power in enumerate(powers):
                        freq = low + (i + 0.5) * step
                        if wlow <= freq < whigh:
                            bins.append(power)
                    if bins:
                        self.rows_by_window.setdefault(w, []).append({
                            "ts": 0.0, "window": w, "low_hz": wlow, "high_hz": whigh,
                            "step_hz": step, "dwell_s": 0.0, "powers": bins,
                            "overload": False, "backend": self.name,
                        })

    def sweep(self, window_index, low_hz, high_hz, dwell_s):
        rows = self.rows_by_window.get(window_index, [])
        pointer = self.pointers.get(window_index, 0)
        if pointer >= len(rows):
            raise ReplayExhausted("replay exhausted for window %d" % window_index)
        self.pointers[window_index] = pointer + 1
        row = dict(rows[pointer])
        row["low_hz"] = low_hz
        row["high_hz"] = high_hz
        return row


# ----------------------------------------------------------------------
# rtl backend: rtl_power as an external runner
# ----------------------------------------------------------------------

class RtlBackend(Backend):
    name = "rtl"
    supports_captures = False

    def __init__(self, config):
        self.config = config

    def available(self):
        tool = shutil.which("rtl_power")
        if tool is None:
            return False, "rtl_power not found on PATH"
        return True, "rtl_power at %s" % tool

    def sweep(self, window_index, low_hz, high_hz, dwell_s):
        ok, reason = self.available()
        if not ok:
            raise BackendUnavailable(reason)
        step = self.config.bin_step_hz()
        cmd = [
            "rtl_power",
            "-f", "%d:%d:%d" % (int(low_hz), int(high_hz), int(step)),
            "-i", "%gs" % dwell_s,
            "-g", "%g" % self.config.gain_db,
            "-1", "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=dwell_s + 60)
        except subprocess.TimeoutExpired:
            raise BackendError("rtl_power timed out on window %d" % window_index)
        except OSError as exc:
            raise BackendUnavailable("rtl_power could not be run: %s" % exc)
        if proc.returncode != 0:
            err = (proc.stderr or "").strip()
            lowered = err.lower()
            if "busy" in lowered or "claim" in lowered:
                raise TunerBusy("rtl_power reports the tuner busy: %s" % err[:200])
            if "no supported devices" in lowered or "usb_open" in lowered:
                raise BackendUnavailable("no receiver device: %s" % err[:200])
            raise BackendError("rtl_power failed on window %d: %s" % (window_index, err[:200]))
        rows = []
        stamp = None
        for line in proc.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 7:
                continue
            try:
                powers = [float(p) for p in parts[6:]]
            except ValueError:
                continue
            rows.append(powers)
            stamp = parts[0] + " " + parts[1]
        if not rows:
            raise BackendError("rtl_power produced no rows on window %d" % window_index)
        bins = int(self.config.bins_per_window)
        averaged = []
        for i in range(bins):
            values = [r[i] for r in rows if i < len(r)]
            averaged.append(round(sum(values) / len(values), 2) if values else -120.0)
        import time as _time
        return {
            "ts": _time.time(),
            "window": window_index,
            "low_hz": low_hz,
            "high_hz": high_hz,
            "step_hz": step,
            "dwell_s": dwell_s,
            "powers": averaged,
            "overload": False,
            "backend": self.name,
            "raw_stamp": stamp,
        }


# ----------------------------------------------------------------------
# Factory and status
# ----------------------------------------------------------------------

def make_backend(name, config, store=None, start_ts=None, terminated=False, scenario=None):
    if name == "synthetic":
        return SyntheticBackend(config, scenario=scenario, terminated=terminated, start_ts=start_ts)
    if name == "replay":
        return ReplayBackend(config)
    if name == "rtl":
        return RtlBackend(config)
    raise BackendUnavailable("unknown backend: %s" % name)


def backend_status(config):
    """Availability of every backend, for the doctor. Never raises."""
    out = []
    for name in ("rtl", "replay", "synthetic"):
        try:
            backend = make_backend(name, config)
            ok, reason = backend.available()
        except Exception as exc:  # a backend must never crash the doctor
            ok, reason = False, "error: %s" % exc
        out.append({"name": name, "available": ok, "reason": reason,
                    "supports_captures": name == "synthetic"})
    return out
