"""KNELL - Known-Emitter Nulling and Electromagnetic Listening Log.

A passive radio instrument that surveys the whole receivable sky, writes
off every emitter it can identify on evidence, and keeps a standing census
of the ones it cannot. Reception only: KNELL never transmits.

Standard library only. Data is plain files on disk.
"""

__version__ = "0.1.0"

NAME = "KNELL"
EXPANSION = "Known-Emitter Nulling and Electromagnetic Listening Log"

# The five census standings. These strings are load-bearing: they appear in
# cluster files, census output, reports and the static page.
UNEXPLAINED = "UNEXPLAINED"
UNDER_WATCH = "UNDER WATCH"
IDENTIFIED = "IDENTIFIED"
ARTIFACT = "ARTIFACT"
INSUFFICIENT_RECORD = "INSUFFICIENT RECORD"

STANDINGS = (UNEXPLAINED, UNDER_WATCH, IDENTIFIED, ARTIFACT, INSUFFICIENT_RECORD)

# Standings that keep a cluster in the active census.
ACTIVE_STANDINGS = (UNEXPLAINED, UNDER_WATCH, INSUFFICIENT_RECORD)
# Standings that resolve a cluster out of the active census.
RESOLVED_STANDINGS = (IDENTIFIED, ARTIFACT)
