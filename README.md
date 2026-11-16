# KNELL

Known-Emitter Nulling and Electromagnetic Listening Log - a passive instrument that surveys the radio sky, writes off every emitter it can identify, and keeps a standing census of the unexplained.

KNELL receives only. It never transmits. It sweeps the receivable span in tiers, detects energy against a rolling baseline, characterises what it hears by shape, modulation family and habit, and clusters repeated hearings into emitters. Every emitter it can identify on full evidence is nulled out of the census and written into the registry with the margins that identified it. Everything left stands in the census with its evidence, under one of five standings: UNEXPLAINED, UNDER WATCH, IDENTIFIED, ARTIFACT, or INSUFFICIENT RECORD. Unknown is a first-class answer. A cluster that almost matches a known emitter stays in the census carrying the note of which criterion failed.

The registry has two layers. The allocation layer is shipped knowledge of what band plans say may be found at each frequency; matching it is never sufficient to null anything. The local layer is earned knowledge: seeded with universal services whose frequencies are the same everywhere, and grown only by full-match nulling and by operator verdicts recorded through the review loop. There is no third door.

The instrument knows itself. A silence test, run with the antenna port terminated, builds a self-portrait of the receiver's own spurs and noise habits, and clusters the portrait accounts for stand as artifacts of the instrument rather than citizens of the sky. A phantom raised by an overloaded strong emitter is likewise named an artifact, with its maker named. Coverage is a kept record: a window a run never reached is a gap with a reason, never a silence the record stays quiet about.

## Running it

KNELL is Python, standard library only, with plain files on disk for all of its state. It runs as a module:

python3 -m knell --data /path/to/data doctor

The verbs are these:

- survey - run the tiered survey: a fast lighthouse pass over the whole span, then a dwell pass over the windows that earned one
- census - print the standing census, or one standing from it, with an optional refresh and an optional static page
- watch - park the tuner on one cluster's frequency for a span and record only there
- silence - run the silence test against a terminated port and refresh the self-portrait
- review - prepare the review packet, or record a file of operator verdicts
- report - write the standing report for a period and render the census page
- doctor - report the health of the whole arrangement: backends, tuner, storage, portrait, coverage, registry

Three capture backends follow the runner pattern. The synthetic backend generates a small fake sky, so the whole pipeline runs and is testable with no hardware. The replay backend reads recorded spectrum rows, in KNELL's JSONL row format or in rtl_power CSV. The rtl backend drives rtl_power when the tools exist. An absent backend is reported unavailable, never a crash, and a tuner held by another process is reported busy, never fought over: one holder at a time, and an interrupted run logs its gap and does not resume itself.

## Data

All state is plain files under the data directory: runs with their coverage records, an event layer, cluster files with their standings and histories, the registry in its two layers, the census as JSON and as text, captures as SigMF pairs under a storage budget with a dropped log, the self-portrait, and review packets and reports. The best capture of a cluster still standing unexplained is never rotated out by the budget.

## Tests

The test suite runs with no hardware:

python3 -m unittest discover -s tests -t .

It covers detection against a rolling baseline, clustering tolerances and the split and merge rules, nulling on full criteria, the near-match path, standings transitions and expiry, the self-portrait artifact path, capture budget rotation and its protection rule, coverage accounting, and the full pipeline end to end on the synthetic sky.

## Design

The full design is in DESIGN.md: the laws the instrument operates under, the survey arithmetic, the judgment rules, the data layout, and the limits stated plainly - no per-device fingerprinting, no direction finding, no decoding of unknown signals, and a census that is complete only about what was actually heard.

## License

AGPL-3.0. See LICENSE.
