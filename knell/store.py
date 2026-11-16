"""The KNELL data directory: plain files, readable without KNELL running.

Layout, per the design:

- runs/<run_id>/header.json and rows.jsonl (plus backend raw files)
- events.jsonl            the event layer, append-only
- clusters/<id>.json      one file per cluster, with its full history
- registry/allocations.json (shipped copy), registry/local.jsonl
- census/census.json, census/census.txt, census/index.html (generated)
- captures/               SigMF pairs plus manifest.json and dropped.jsonl
- self/<ts>.json          self-portraits
- reviews/                packets, verdict files, reports, packet state
- state.json              counters and small bookkeeping (ids, baselines)

Nothing here requires a database. Every write that matters is append-only
or a whole-file rewrite of a small JSON document.
"""

import json
import os
import time

SUBDIRS = ("runs", "clusters", "registry", "census", "captures", "self", "reviews")


def iso(ts):
    """Render an epoch timestamp as an ISO 8601 UTC string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def run_id_for(ts, kind):
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ts))
    return "%s-%s" % (stamp, kind)


class Store:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    # -- paths ---------------------------------------------------------
    def path(self, *parts):
        return os.path.join(self.data_dir, *parts)

    def ensure(self):
        os.makedirs(self.data_dir, exist_ok=True)
        for sub in SUBDIRS:
            os.makedirs(self.path(sub), exist_ok=True)

    # -- small JSON documents ------------------------------------------
    def read_json(self, *parts, default=None):
        target = self.path(*parts)
        if not os.path.isfile(target):
            return default
        with open(target, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def write_json(self, payload, *parts):
        target = self.path(*parts)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, target)

    # -- JSONL ----------------------------------------------------------
    def append_jsonl(self, record, *parts):
        target = self.path(*parts)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def read_jsonl(self, *parts):
        target = self.path(*parts)
        if not os.path.isfile(target):
            return []
        rows = []
        with open(target, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    # -- state and id counters ------------------------------------------
    def state(self):
        return self.read_json("state.json", default={
            "next_event": 1,
            "next_cluster": 1,
            "baselines": {},
            "last_packet_ts": 0.0,
        })

    def save_state(self, state):
        self.write_json(state, "state.json")

    def next_id(self, kind):
        state = self.state()
        value = state["next_" + kind]
        state["next_" + kind] = value + 1
        self.save_state(state)
        return value

    # -- events ----------------------------------------------------------
    def append_event(self, event):
        self.append_jsonl(event, "events.jsonl")

    def events(self):
        return self.read_jsonl("events.jsonl")

    def event_by_id(self, event_id):
        for event in self.events():
            if event["id"] == event_id:
                return event
        return None

    # -- clusters ----------------------------------------------------------
    def cluster_path(self, cluster_id):
        return self.path("clusters", cluster_id + ".json")

    def save_cluster(self, cluster):
        self.write_json(cluster, "clusters", cluster["id"] + ".json")

    def load_cluster(self, cluster_id):
        return self.read_json("clusters", cluster_id + ".json", default=None)

    def clusters(self):
        out = []
        folder = self.path("clusters")
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.endswith(".json"):
                    with open(os.path.join(folder, name), "r", encoding="utf-8") as handle:
                        out.append(json.load(handle))
        return out

    # -- registry ----------------------------------------------------------
    def local_registry(self):
        return self.read_jsonl("registry", "local.jsonl")

    def append_local_registry(self, entry):
        self.append_jsonl(entry, "registry", "local.jsonl")

    def rewrite_local_registry(self, entries):
        target = self.path("registry", "local.jsonl")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        os.replace(tmp, target)

    # -- self-portraits ----------------------------------------------------
    def save_portrait(self, portrait):
        name = run_id_for(portrait["ts"], "self") + ".json"
        self.write_json(portrait, "self", name)
        return name

    def portraits(self):
        out = []
        folder = self.path("self")
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.endswith(".json"):
                    with open(os.path.join(folder, name), "r", encoding="utf-8") as handle:
                        out.append(json.load(handle))
        return out

    def latest_portrait(self):
        portraits = self.portraits()
        return portraits[-1] if portraits else None
