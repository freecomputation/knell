# KNELL - design

KNELL - Known-Emitter Nulling and Electromagnetic Listening Log.

A passive radio instrument that surveys the whole receivable sky, writes off every emitter it can identify on evidence, and keeps a standing census of the ones it cannot.

Status: design only, written 2026-11-16. No code exists. Nothing in this document is a measured result; every number in it is a design target or a piece of planning arithmetic, and it is labelled as such where it appears.

## What it is

Every receiver in the house starts from the known. Passband works from a schedule: named slices, named services, decoders for signals whose shape is already understood. KNELL inverts the direction. It starts from everything the antenna can hear, most of which has no name, and works by elimination. What survives elimination - identified on evidence, not on resemblance - is the product: a census of the unexplained, kept over weeks, with the evidence for every entry preserved so any verdict can be re-judged.

The inversion matters because collection is cheap and judgment is scarce. A single dongle hears more in a day than anyone can review in a month. The scarce resource is trustworthy triage: which of these thousands of transmissions are known and can be written off, which are the instrument fooling itself, and which are genuinely unexplained. KNELL exists to make that judgment at collection speed, and to be honest about which pile each signal landed in and why.

KNELL is a Free Computation program. It is offline-first, local-first, and passive. It never transmits. It runs on hardware already in the house and spends nothing.

## The laws

These govern every later section. Where a mechanism and a law conflict, the law wins and the mechanism is redesigned.

- KNELL never transmits. It is a listening instrument. Reception only, at every layer, with no exceptions for testing.
- Unknown is a first-class verdict. An entry that reads unexplained, with its evidence attached, is a success of the system, not a failure of it. The census is allowed to stay unexplained forever.
- No stage may manufacture an identification. A guess is labelled a guess with its margins shown. Nothing is promoted to identified on resemblance, on a band allocation alone, or because a transcription or classifier sounded confident. The standing failure this law exists to prevent: a machine inventing a voice out of static and reporting it as speech.
- A known is written off only on evidence, and the evidence is recorded with the write-off. If the match is short on any criterion, the signal is not written off; it stays in the census carrying a note that it nearly matched, and what it nearly matched.
- Every verdict carries its evidence. Captures, features, times and match margins are stored with each census entry so a human can re-judge any entry without re-running anything.
- The instrument must know itself. Signals KNELL's own hardware generates - dongle spurs, host clocks, USB noise - are identified as ours and never allowed to pose as the sky. The census of the unexplained must not fill up with the instrument.
- The tuner belongs to the operator. KNELL shares one dongle with the rest of the house and yields it on the rules in the tuner section below. It never holds the tuner against another program's claim and never restarts itself onto a tuner that was taken away.
- Nothing leaves the machine by default. A census of one place's sky is a fingerprint of that place. Reports and pages are local unless the operator rules otherwise, item by item.
- Absence is reported honestly. A backend that is not installed, a band that was not covered, a week the instrument did not run: the record says so. KNELL reports unavailable rather than guessing, and never papers over a gap in coverage.

## Vocabulary

The design uses these words with these meanings throughout.

- Event - one detected transmission: a span of time and frequency where energy rose above the local noise baseline and fell again, with its measured shape recorded.
- Cluster - a set of events judged to come from one emitter, grouped by shape and habit. The cluster, not the event, is the unit of the census, the way the event and not the post is the unit of a sightings register.
- Toll - one appearance of a cluster. A cluster that has tolled forty times on a regular pattern is a different object from one that tolled once, and the census says which.
- Nulling - the write-off step. A cluster is nulled when it is matched to a known emitter on all criteria and removed from the unexplained census into the registry, with the match recorded. The name of the program is this step: known-emitter nulling.
- Registry - the book of the known: what each identified emitter is, how it was identified, and the criteria a future cluster must meet to be written off as the same thing.
- Census - the standing register of the unexplained: every cluster not yet nulled, with its standing, its toll count, its evidence and its history.
- Standing - the current judgment on a census entry. The standings are defined in the census section.
- Self-portrait - a survey taken with the antenna port terminated, recording everything the instrument hears from itself. The baseline of the instrument's own noise, against which the sky is compared.

## Hardware and hosts

The receiver is the RTL-SDR Blog V4 already in the house: an RTL2832U with an R828D tuner, receivable range roughly 500 kHz to 1.75 GHz, instantaneous bandwidth a little over 2 MHz at the sample rates it sustains reliably. It is receive-only hardware, which suits the first law. The antenna is the stock telescopic whip. The design treats the antenna as the honest ceiling of the whole instrument: KNELL will hear what that whip, in that place, can hear, and the census is a census of that sky and no other. A better antenna widens the sky; it does not change the design.

The survey host is the X200, a Core 2 Duo laptop. That processor sets the compute budget, and the design respects it the way Passband's did: the Python core does no heavy signal mathematics. Spectrum capture and Fourier work happen in external capture tools, in the pattern of Passband's decoder runners - a backend that is absent is reported unavailable, never simulated and never crashed on. The core reads the plain files those tools produce and does bookkeeping, features, clustering and judgment, all of which are light.

The G1 is the heavy host. Captures that deserve a slower second look - a long look at one cluster's shape, a decode attempted purely to test an identification - are re-analysed there, where the decoders Passband already proved on real recordings live. The X200 surveys and keeps the books; the G1 thinks about the hard cases. Either host can run the whole design alone at reduced depth; the split is a convenience, not a dependency.

KNELL is written in Python against the standard library only, in the house pattern. Its data is plain files on disk. It needs no network, no account and no service, and it runs indefinitely at zero connectivity.

## The survey

A sweeping receiver sees each frequency only in passing, and the design is honest about what that costs. Planning arithmetic, offered as arithmetic and not as a promise: the receivable span divided into windows of about 2 MHz gives roughly 875 windows. A dwell of a tenth of a second per window walks the whole span in about ninety seconds and hears only the strong and the constant. A dwell of a full second per window takes about fifteen minutes and still misses nearly every short transmission on the span. No dwell policy fixes this. A single sweeping tuner cannot watch everything at once, and KNELL does not pretend otherwise.

So the survey is tiered, and its unit of completeness is the week, not the sweep.

- Tier 1, the lighthouse pass - a fast walk of the whole span, run often. It finds the strong, the constant and the frequent, and it keeps the noise baseline of every window current.
- Tier 2, the dwell pass - a slower walk that lingers where tier 1 saw energy, where the census has open entries, and where habit says an emitter keeps a schedule. Time is spent where the sky has already shown something.
- Tier 3, the watch - the tuner parked on one cluster's frequency for a span of hours, catching its tolls as they come, until its habit is measured well enough to judge. A watch is how a cluster earns the evidence for a verdict.

Gain is fixed during a survey, never automatic, because a wandering gain makes captures incomparable across days and the census is built on comparisons. The fixed value is set by calibration against the local sky and recorded in every run's header, the way the house's other receiver work pins its gain. Frequency correction for the dongle's clock error is measured against a known local emitter and recorded the same way; every frequency KNELL reports carries that correction behind it.

Coverage is a kept record, not an assumption. Every run logs which windows it actually visited, at what dwell, with what gain, so that a quiet week in the census can be told apart from a week the instrument never looked. An absence in the census means something only when the coverage record says the instrument was listening there.

## Detection and capture

Detection is energy against a rolling baseline. Each window keeps a noise floor estimated from its own recent history, robust to the signals themselves, and an event opens when energy rises a set margin above that floor and closes when it falls back. The margins are configuration, stated in the run header, and the same margins are used across a census period so that toll counts are comparable.

An event record is small and complete: start and stop time, centre frequency and occupied bandwidth, peak and mean power above the floor, and the window it was heard in. For events that pass a second, higher bar, KNELL also keeps a capture: a short span of raw samples in SigMF, the format the house already uses, long enough to characterise the signal and no longer. Captures are the expensive evidence and they are rationed by a storage budget with a stated default, oldest first out, and the rationing is itself logged - an event whose capture was dropped for budget says so in its record rather than pretending the evidence exists.

Strong-signal honesty is part of detection. A receiver of this class overloads: one loud transmitter can raise false energy across many windows and can manufacture phantom signals at harmonic and image frequencies. The detector therefore marks events that coincide with a known overload condition, and the clustering stage treats coincident phantoms as suspects for the artifact standing, not as citizens of the sky. The census section gives that suspicion a formal path to a verdict.

## Characterisation

Each event, and each cluster as it accumulates events, is described by features a judgment can stand on. The feature set is deliberately plain, because every feature must be measurable by the light core or by a named backend, and a feature that cannot be measured honestly is worse than none.

- Shape - occupied bandwidth, spectral outline, whether the energy is a single carrier, a pair, a comb or a block, and how the edges fall.
- Voice - the modulation family, judged from the capture where one exists: constant-envelope or varying, amplitude or frequency or phase movement, symbol rhythm where one can be measured. The judgment is a family, never a protocol, unless a real decoder names the protocol.
- Habit - duration of a toll, the gaps between tolls, duty cycle, time of day and day of week patterning, and regularity. Habit is measured over weeks and is often the strongest evidence a cluster offers.
- Strength - power above the floor, and its variation across tolls. A cluster whose strength swings widely is a different object from one that arrives identical every time, and the record keeps the spread, not just the mean.
- Stability - centre frequency drift across tolls, measured against the run's recorded clock correction. Drift is reported as measured, with the instrument's own error stated beside it, never silently absorbed.

## Clustering

Clustering groups events into emitters. Two events belong to one cluster when their shapes agree within stated tolerances and their frequencies agree within the measured stability of the thing itself. Habit can confirm a cluster and can split one: two shapes that agree but keep opposite schedules are two emitters until evidence says otherwise, because the cost of splitting wrongly is a longer census, while the cost of merging wrongly is a real emitter written off inside another's identity.

Clusters are conservative at birth and merge only on accumulated evidence. Every merge and split is a dated entry in the cluster's history with its reason, and a merge can be undone by the review loop without losing the events under it. The census never destroys the event layer; clusters are judgments laid over events, and judgments can be revised.

## The registry and nulling

The registry is the book of the known, and it has two layers.

The allocation layer is static knowledge: what the band plans say may lawfully be found at each frequency - broadcast, airband, maritime, amateur, satellite downlinks, the industrial and unlicensed bands, the house's own known services. This layer is a map of expectations. Matching it is never sufficient to null a cluster, because an allocation says what may be somewhere, not what this emitter is. A signal in the airband allocation is expected; it is not thereby identified.

The local layer is earned knowledge: emitters this station has actually identified, each with the evidence that identified it. It is seeded from what the house already knows - the slices and services Passband works, the decoders that have named real signals on the G1, the beacons and stations of the local sky - and it grows by two doors only: a cluster nulled on a full match, and a verdict from the operator recorded by hand. There is no third door. The registry cannot learn from its own guesses.

A cluster is nulled when it matches a registry entry on every criterion the entry carries: frequency within the entry's tolerance, bandwidth in agreement, modulation family in agreement, and habit in agreement where the entry keeps a habit. The match is recorded whole - which entry, which criteria, what margins - in the cluster's history, and the cluster moves out of the census into the registry's local layer as a known local emitter, still carrying its events. A cluster that meets some criteria and fails one is not nulled. It stays in the census with a near-match note naming the entry it almost was and the criterion it failed. Near matches are among the most valuable entries in the census: they are where new services, moved services and imitations of known services will first appear.

## The census and its standings

The census is the standing register of clusters not yet nulled. Every entry carries its cluster's full feature record, its toll count and pattern, its best captures, its near-match notes and its complete history of standings and the evidence behind each change. An entry's standing is one of the following.

- UNEXPLAINED - heard, characterised, and matched to nothing on full criteria. The ordinary citizen of the census.
- UNDER WATCH - unexplained, and chosen for a tier 3 watch because its habit or shape earns a closer look. Watching is a statement of interest, not of suspicion.
- IDENTIFIED - the cause is named and the entry leaves the census for the registry, by a full match or by the operator's verdict. Identified always names the cause; an entry may not be closed as identified in general.
- ARTIFACT - the cause is named and the cause is not a citizen of the sky: the instrument itself, the host computer, an overload phantom, a harmonic or image of a stronger signal, or a device in the house. Artifact always names the cause, and naming it requires the evidence in the self-knowledge section.
- INSUFFICIENT RECORD - heard too little to characterise: a single weak toll, a capture lost to budget, a shape half-seen at a window's edge. Such entries expire out of the active census after a stated window without another toll, and their expiry is recorded, not silent.

Standings change only on evidence or on the operator's verdict, and every change is a dated line in the entry's history with its grounds. Nothing is deleted from the census. Resolution moves an entry and preserves it, so the history of what the sky over this place was once thought to contain remains readable.

## Knowing itself

An instrument that hunts the unknown must first map its own noise, or its census becomes a portrait of itself. KNELL keeps a self registry alongside the sky registry, and maintains it by ritual.

The silence test is the ritual. With the antenna port terminated - a proper load on the connector, not an open socket and not a hand near the whip - KNELL runs its ordinary survey and records everything it hears from itself: the dongle's spurious responses at their known haunts, the host's clock harmonics walking up the span, USB and power-supply noise, the display and disk of the machine it lives on. That run is the self-portrait, and it is retaken whenever the hardware arrangement changes and on a regular cadence besides, because the instrument's noise is part of its state.

Any cluster whose shape and frequency are accounted for by the self-portrait is a candidate for the artifact standing with cause named as self, and the census entry records the self-portrait run that accounts for it. The same discipline covers the house: devices in the home emit, some of them on schedules, and a cluster identified as the house's own equipment is an artifact with that cause named - an honest entry, not an embarrassment. The artifact pile is expected to be large, especially early. A big artifact pile with named causes is the instrument learning its own house; a small unexplained pile is what remains when that learning is done.

Overload phantoms get the same treatment through the detector's overload marks: a cluster that tolls only when a known strong emitter is on the air, at a frequency that stands in a harmonic or image relation to it, is an artifact candidate with cause named as the strong emitter, and it is nulled as an artifact only when that relation and that coincidence are both in the record.

## Judgment and the review loop

KNELL's own judgments are proposals. The machine clusters, matches and assigns standings by the rules above, and it expresses confidence only as margins: how far inside or outside each criterion a match fell. It never converts a margin into a claim. Identification happens by full match or by the operator, and by nothing else.

On a regular cadence the instrument prepares a review packet: the new clusters since the last packet, the standings that changed and their grounds, the near matches, the clusters whose habits sharpened, and the entries recommended for a watch, each with its evidence files named. The packet is plain text, readable in one sitting, and it is the operator's working surface. Verdicts given on a packet - this one is the water tower telemetry, this one is ours, this one stays unexplained - are written back as registry entries and history lines, dated and attributed to the operator, and they take effect in the next survey cycle. A cluster the operator has identified by hand is never re-filed as unexplained; the registry remembers what the house has learned.

The loop is the long game. Week by week the registry absorbs the local sky, the artifact pile absorbs the instrument and the house, and the census burns down toward the genuinely unexplained. What is left standing in it after months of this is the instrument's real output: a short list of things transmitting over one place that nobody involved can yet explain, each with the evidence to begin explaining it.

## Data on disk

Everything KNELL keeps is plain files under one directory, in the house pattern, readable without KNELL running.

- runs - one directory per survey run, holding the run header (times, gain, clock correction, margins, coverage map) and the spectrum rows the capture backend produced.
- events.jsonl - the event layer, one line per event, append-only.
- clusters - one file per cluster carrying its features, tolls, standings and full history.
- registry - the allocation layer as shipped tables, and the local layer as it is earned, one entry per known emitter with its criteria and its identifying evidence.
- census - the active census and the resolved archive, generated from the cluster files, never edited by hand.
- captures - SigMF sample pairs for events that earned one, under the storage budget, with a manifest that says what was kept and what was dropped and why.
- self - the self-portraits, dated, with the hardware arrangement each was taken under.
- reviews - the review packets and the verdicts returned on them.

Retention follows the evidence law. Event records, cluster histories, registry entries and verdicts are kept indefinitely; they are small. Captures are the bulk and are kept under the budget, with one exception: the best captures of a cluster still standing unexplained are not rotated out. The evidence for the entries that matter most is never the first thing thrown away.

## Commands and surfaces

The operator drives KNELL with plain verbs, in the family pattern of the house's other instruments.

- knell survey - run the tiered survey, once or on its standing schedule.
- knell census - print the current census, standings first, in full or by standing.
- knell watch - park the tuner on a named cluster's frequency for a stated span.
- knell silence - run the silence test and refresh the self-portrait.
- knell review - prepare the review packet, or record verdicts returned on one.
- knell report - write the standing report for a period: coverage, new clusters, standings changed, the census as it stands.
- knell doctor - report the health of the whole arrangement: backends present or absent, tuner state, storage against budget, days since the last self-portrait, coverage gaps. Absent pieces are reported as absent.

The report and the census can also be rendered as a static page in the house form - white page, black text, no scripts - generated from the data files and never edited by hand. The page is local by default. Whether it is ever published is a separate decision for the operator, taken with the knowledge that a census names a place by its sky even when it never names it in words.

## Sharing the tuner

One dongle serves the house, and its ownership is the operator's, exercised through a simple rule. Only one program holds the tuner at a time. A standing claim - a Passband schedule, a KNELL survey, a watch - runs until it ends or the operator ends it. KNELL checks for the tuner before a run and reports it busy rather than contending; a KNELL run interrupted by the loss of the tuner stops cleanly, logs the interruption in its coverage record, and does not resume itself. When the operator rules that two programs must interleave, they interleave by schedule at coarse grain - hours, not seconds - because a tuner passed back and forth rapidly serves neither. The census's coverage record is what makes this honest: a gap caused by another program's claim is recorded as a gap, and no conclusion is ever drawn from a silence KNELL did not actually listen to.

## Limits, stated plainly

KNELL does not identify which physical device transmitted a signal. Telling two radios of the same model apart by the imperfections of their hardware is a real discipline, but it is not this one, and the dongle's own clock drift would contaminate naive attempts at it. Clusters are emitters as heard - a shape with a habit - and the design never upgrades that into a claim about a specific box.

KNELL does not find directions. One tuner hears that something transmitted, never where from. A cluster's place in the census carries no bearing, no distance and no location, and any future urge to add them is a different instrument's business.

KNELL does not decode the unknown. Where a real decoder exists for a known service, a decode may serve as identifying evidence for nulling, through the same runner pattern the house already trusts. An unexplained cluster is characterised, never decoded by force, and its content is not guessed at. Most of the census will be mundane - telemetry, links, beacons, the machinery of a connected countryside - and the design expects that. The instrument's worth is not that the unexplained stays mysterious; it is that every explanation on the books was earned.

Reception has a floor and a ceiling. Signals below the noise, signals too brief for any tier to catch twice, signals outside the whip's reach do not exist for KNELL, and the census makes no claim about them. The census is complete only about what the instrument actually heard, and the coverage record is the boundary of every claim.

## Relation to the house's other instruments

Passband knows the scheduled sky: named services, kept slices, decoders, a discipline of listening for what is expected. KNELL is its complement, not its extension - the instrument for everything that was never scheduled. The two share a tuner, a host and a body of local knowledge, and KNELL's registry is seeded from Passband's, but their questions are opposite and their code is separate.

Catoptrics hunts the emanations of devices at close range, the leakage of screens and circuits in a room. That is a near-field problem about equipment in hand. KNELL's sky is the far field: transmissions meant to travel, heard from wherever they were sent. The two share a habit of honesty about what their measurements are, and nothing else needs sharing.

Prodigia keeps a register of sightings whose unit is the event and whose standings are statements about the record. KNELL borrows that discipline for its census - standings as statements about evidence, resolution by named cause, nothing deleted - applied to a sky that can be re-measured on demand, which sightings cannot.

## Scope of the first version

The first version is the whole loop at honest depth: tiered survey, detection, characterisation, clustering, a registry seeded from allocations and the house's knowledge, nulling on full criteria, the census with its standings, the silence test, review packets and verdicts, the report, and the doctor. That is already a large instrument, and the milestones below build it in that order, each one usable before the next begins.

Deliberately not in the first version: any form of transmission, any direction finding, any hardware fingerprinting of individual devices, any decoding of unexplained signals, any networked or multi-site operation, any publication of the census, and any claim about signals the coverage record does not support. Each of those is excluded by a law or a limit above, not merely postponed.

## Milestones

Each milestone ends with an acceptance test run against the real sky over the station. A milestone is done when its test passes, not when its code is written.

- M1, survey and detection - the tiered survey runs on the X200 for a full day under the tuner rules, with fixed gain, recorded clock correction and a complete coverage record. Acceptance: the event log re-finds the strong known sky the house already knows is there - the broadcast band alive, the airband channels occupied, the 1090 MHz channel busy - as events with shapes a reader agrees are those services, and the run's coverage record accounts for every hour of the day.
- M2, characterisation and clustering - events accumulate into clusters with features and habits. Acceptance: on a week of running, the clusters corresponding to known continuous and scheduled emitters each hold together as one cluster, and no two plainly distinct known emitters are found merged in one.
- M3, the registry and nulling - the allocation layer is loaded, the local layer is seeded from the house's knowledge, and nulling runs on full criteria with near-match notes. Acceptance: every cluster corresponding to the known test set is nulled with the correct entry named and its margins recorded, and no cluster is nulled on allocation alone.
- M4, census, standings and the silence test - the census is kept with all five standings, the self-portrait is taken and applied, and the report and static page are generated. Acceptance: a terminated-port survey produces a self-portrait that accounts for the instrument's repeatable self-signals, those signals stand in the census history as artifacts with cause self, and every active census entry carries its evidence.
- M5, the review loop - packets are prepared, verdicts are recorded and take effect, watches are scheduled from the census. Acceptance: a cluster identified by the operator's verdict is absorbed into the registry and is not re-filed as unexplained in any later cycle, and a watched cluster's habit record measurably sharpens across its watch.

## Open questions

The design is complete without these answers; each is a ruling for the operator when its moment comes, and the defaults stated here hold until then.

- Publication - the census page is local by default. Publishing any form of it is a separate ruling, taken knowing a census identifies a place by its sky.
- Capture retention - the storage budget's default size, and how long the best captures of a long-unexplained cluster are kept beyond it, are set at first build and revisited when the budget first bites.
- The G1's depth - which hard cases earn re-analysis on the G1, and how captures travel there, are working habits to settle in the first review cycles rather than in advance.
- Cadence - how often review packets are prepared is set by the operator's appetite for judging them. Weekly is the design's assumption; the instrument is content at any cadence, because the census keeps its own history either way.

Design ends. Build begins only on the operator's word.
