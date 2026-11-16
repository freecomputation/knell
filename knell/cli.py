"""KNELL command line: survey, census, watch, silence, review, report, doctor.

Plain verbs, in the family pattern of the house's other instruments.
Every verb works against a data directory of plain files. Hardware
verbs check their backend first and report it unavailable rather than
failing; a busy tuner is reported, never fought over.
"""

import argparse
import json
import os
import sys
import time

from . import __version__
from .backends import BackendUnavailable, TunerBusy
from .census import run_pass as census_pass
from .census import write_census_files
from .config import load_config
from .doctor import run_doctor
from .registry import ensure_registry_files, seed_local_registry
from .report import build_report, render_page
from .review import apply_verdicts, prepare_packet
from .store import Store
from .survey import run_silence, run_survey, run_watch


def _prepare(args):
    data_dir = args.data or os.environ.get("KNELL_DATA") or os.path.join(
        os.path.expanduser("~"), ".local", "share", "knell")
    store = Store(data_dir)
    store.ensure()
    ensure_registry_files(store)
    overrides = {}
    if getattr(args, "backend", None):
        overrides["backend"] = args.backend
    if getattr(args, "span_low", None) is not None:
        overrides["span_low_hz"] = args.span_low
    if getattr(args, "span_high", None) is not None:
        overrides["span_high_hz"] = args.span_high
    if getattr(args, "gain", None) is not None:
        overrides["gain_db"] = args.gain
    if getattr(args, "budget", None) is not None:
        overrides["capture_budget_bytes"] = args.budget
    config = load_config(data_dir, getattr(args, "config", None), overrides)
    seeded = seed_local_registry(store)
    return store, config, seeded


def cmd_survey(args):
    store, config, _ = _prepare(args)
    tiers = tuple(int(t) for t in args.tiers.split(",")) if args.tiers else (1, 2)
    try:
        result = run_survey(store, config, backend_name=args.backend, tiers=tiers)
    except BackendUnavailable as exc:
        print("survey: backend unavailable: %s" % exc)
        return 2
    except TunerBusy as exc:
        print("survey: tuner busy: %s" % exc)
        return 3
    header = result["header"]
    print("run %s (%s): %d events, census %s"
          % (header["id"], header["backend"], header["events"], result["census"]))
    for note in header["notes"]:
        print("note: %s" % note)
    return 0


def cmd_census(args):
    store, config, _ = _prepare(args)
    if args.refresh:
        census_pass(store, config, time.time())
    doc = write_census_files(store, time.time())
    if args.page:
        target = render_page(store, config, time.time())
        print("page written: %s" % target)
    if args.standing:
        entries = doc["active"].get(args.standing, [])
        print("%s: %d" % (args.standing, len(entries)))
        for e in entries:
            print("- %s  %.4f MHz  bw %.1f kHz  %s / %s  tolls %d"
                  % (e["id"], e["center_mhz"], e["bandwidth_khz"], e["outline"],
                     e["family"], e["tolls"]))
        return 0
    with open(store.path("census", "census.txt"), "r", encoding="utf-8") as handle:
        sys.stdout.write(handle.read())
    return 0


def cmd_watch(args):
    store, config, _ = _prepare(args)
    try:
        result = run_watch(store, config, args.cluster, args.span,
                           backend_name=args.backend)
    except ValueError as exc:
        print("watch: %s" % exc)
        return 2
    except BackendUnavailable as exc:
        print("watch: backend unavailable: %s" % exc)
        return 2
    except TunerBusy as exc:
        print("watch: tuner busy: %s" % exc)
        return 3
    print("watch %s: %d events over %d s"
          % (args.cluster, result["header"]["events"], args.span))
    return 0


def cmd_silence(args):
    store, config, _ = _prepare(args)
    if args.backend == "rtl" and not args.terminated:
        print("silence: with the rtl backend the operator must assert the port "
              "is terminated, by passing --terminated")
        return 2
    try:
        result = run_silence(store, config, backend_name=args.backend,
                             hardware_note=args.hardware_note)
    except BackendUnavailable as exc:
        print("silence: %s" % exc)
        return 2
    except TunerBusy as exc:
        print("silence: tuner busy: %s" % exc)
        return 3
    portrait = result["portrait"]
    print("self-portrait %s: %d self signals recorded"
          % (portrait["id"], len(portrait["signals"])))
    return 0


def cmd_review(args):
    store, config, _ = _prepare(args)
    if args.verdicts:
        with open(args.verdicts, "r", encoding="utf-8") as handle:
            verdicts = json.load(handle)
        results = apply_verdicts(store, config, verdicts, time.time())
        for line in results:
            print(line)
        census_pass(store, config, time.time())
        write_census_files(store, time.time())
        return 0
    packet = prepare_packet(store, config, time.time())
    print("packet written: reviews/%s" % packet["file"])
    sys.stdout.write(packet["text"])
    return 0


def cmd_report(args):
    store, config, _ = _prepare(args)
    report = build_report(store, config, time.time(), period_days=args.days)
    print("report written: reviews/%s" % report["file"])
    sys.stdout.write(report["text"])
    if args.page:
        target = render_page(store, config, time.time())
        print("page written: %s" % target)
    return 0


def cmd_doctor(args):
    store, config, _ = _prepare(args)
    sys.stdout.write(run_doctor(store, config))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="knell",
        description="KNELL - Known-Emitter Nulling and Electromagnetic "
                    "Listening Log. A passive instrument that surveys the "
                    "radio sky, writes off every emitter it can identify, "
                    "and keeps a standing census of the unexplained.")
    parser.add_argument("--version", action="version",
                        version="knell %s" % __version__)
    parser.add_argument("--data", default=None,
                        help="data directory (default: $KNELL_DATA or ~/.local/share/knell)")
    parser.add_argument("--config", default=None, help="config JSON file")
    sub = parser.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("survey", help="run the tiered survey")
    p.add_argument("--backend", default=None, choices=["synthetic", "replay", "rtl"])
    p.add_argument("--tiers", default=None, help="comma list, e.g. 1 or 1,2")
    p.add_argument("--span-low", type=float, default=None)
    p.add_argument("--span-high", type=float, default=None)
    p.add_argument("--gain", type=float, default=None)
    p.set_defaults(func=cmd_survey, backend=None)

    p = sub.add_parser("census", help="print the current census")
    p.add_argument("--standing", default=None,
                   choices=["UNEXPLAINED", "UNDER WATCH", "IDENTIFIED", "ARTIFACT",
                            "INSUFFICIENT RECORD"])
    p.add_argument("--refresh", action="store_true", help="re-run the judgment pass first")
    p.add_argument("--page", action="store_true", help="also render the static census page")
    p.set_defaults(func=cmd_census, backend=None)

    p = sub.add_parser("watch", help="park the tuner on one cluster's frequency")
    p.add_argument("cluster")
    p.add_argument("--span", type=int, default=3600, help="watch length in seconds")
    p.add_argument("--backend", default=None, choices=["synthetic", "replay", "rtl"])
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("silence", help="run the silence test and refresh the self-portrait")
    p.add_argument("--backend", default=None, choices=["synthetic", "replay", "rtl"])
    p.add_argument("--terminated", action="store_true",
                   help="assert the antenna port is terminated (rtl backend)")
    p.add_argument("--hardware-note", default=None)
    p.set_defaults(func=cmd_silence)

    p = sub.add_parser("review", help="prepare the review packet, or record verdicts")
    p.add_argument("--verdicts", default=None, help="JSON file of verdicts to record")
    p.set_defaults(func=cmd_review, backend=None)

    p = sub.add_parser("report", help="write the standing report for a period")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--page", action="store_true", help="also render the static census page")
    p.set_defaults(func=cmd_report, backend=None)

    p = sub.add_parser("doctor", help="report the health of the whole arrangement")
    p.set_defaults(func=cmd_doctor, backend=None)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
