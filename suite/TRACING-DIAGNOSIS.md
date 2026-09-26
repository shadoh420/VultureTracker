# Why Rift and Vantage read as traced: the diagnosis (2026-09-24)

The owner's verdict stands as given: Rift and Vantage sound too close to Nether Animal and Foregone Destruction. Rift's
intro and the passage from 2:59 sound nearly identical to Nether's, and the same comparisons can be made between
Vantage and Foregone. This page does not argue with that. It records what each piece inherits and where the likeness
sits, so the method can change in the right places. Everything below is a count or a distance. Nothing has been
listened to, and no UT99 note, cell or sample is printed. The page describes Epic's modules, so it stays uncommitted,
like `suite/rift/BRIEF.md`.

Tools (local, in `scratch/ut99-clean/`): `sections.py` (order by order, see below) with `sections_report.txt`,
`globaldims.py` (whole-song dimensions from `features.json`) with `globaldims_report.txt`, `formcurve.py` (the form as
curves), `variants_likeness.py` (the listening-test variants), `echoprofile.py` (echo delays, effects and strike rows
per sample: the Vantage table's idiom figures).

## 1. What each piece inherits

C = copied exactly (the reference's figure or rule, unchanged). G = a genre trait, shared by several UT99 tracks.
O = ours.

### Rift against Nether Animal

| Dimension | What Rift does | Mark |
|---|---|---|
| Tempo, grid | 165 BPM (110/4) against 175.5 (117/4); speed 4, 4 rows a beat, 16-row bars, 64-row patterns | tempo O (6 % slower), grid G |
| Key, root | A minor at A440 against C# +30 c; one root, the sub on it with a passing fifth | key O, one-root harmony G (the brief's item 5) |
| Form: lengths, order | 55 orders in Nether's section lengths 4-6-8-2-4-6-2-17-6, in its order (intro, build, A, break, B, peak, break, C, outro) | C |
| Form: entries, exits | every tonal layer enters and leaves at the order where its counterpart does (formmap.py, cellorder.py) | C |
| Form: arc | section means (dB against the loudest order) within 0.1-2.9 dB of Nether's in eight of nine sections; the build 3.8 dB higher (the sub plays there: departure 1 in the handoff), and our peak does not rise over C (-1.2 against -0.5 dB; Nether's -0.8 against -2.9) | the arc's kind G (the brief's item 8), its levels per section mostly C, the peak's height not |
| Layer set, roles | nine tonal and colour layers, one for each of Nether's nine (sequence, lead call, tonal hit, surround bed, strings, drone, noise swell, vocal pad, second line); the drums are Nether's minus the kick, the noise snare, the second break, the drum riff and the FX hits | C (the set), drums partly O |
| Sequence | 8ths, one voice restarted on row 0 of each pattern at v36, GFF on the other notes, copies at +2 rows v6 pan 34 and +3 rows v12 pan 56, main pan 17, each copy restarting in its pattern | C, every parameter |
| Lead call | one call per pattern in bar 1, three notes on the 8ths from row 2 alternating two channels at v30, re-strikes at +4 and +8 rows at v14 and v8, D03/D01 fades, cut on row 32 | C, every parameter |
| Tonal hit | row 0 of every bar alternating two channels, started 2.3 % in (O0F), tuned +60 c above the root | C (Nether's offset 2 %, detune 43-85 c) |
| Strings | two three-voice groups on rows 0 and 32, held 32 rows, faded D02 then D00 from the other group's strike, S87 | C |
| Drone | one strike, restated by GFF on row 0 of each pattern; the entry swell v7 to v30 over 24 rows, flat v30, then v30/v40 alternation; D02/D00 fade; pan 29 | C, every parameter |
| Noise | row 0 at the sample's own volume, S89, struck in every pattern of orders 0-6, then every second pattern, then every fourth | C |
| Vocal pad | strike v5 swelled to v23 over 16 rows, GFF restatements, D01/D00 fade, pan 32 | C |
| Second line | bar-1 figure on rows 0 2 4 6 10 14, glides G54/G20, echo +3 rows at -7.2 dB, a three-note pickup | rows and idioms C, notes O |
| Bed | an A minor triad once per pattern with nna fade (Nether: two open fifths, one re-struck every bar) | O (approved) |
| Sample character | each generator matched Nether's sample for that role: length and loop points (e.g. the sequence 0.994 s looped 0.194 s from 0.80 s; the drone 6.26 s looped 3.86 s from 2.39 s), swell times, noise floor, vibrato and wobble depth and rate, bandwidth, stored root and transposition | C as figures; the sources (patches, recordings) O |
| Levels | each layer set to Nether's level under the sub (sequence 8.0 dB, lead 10.6, hit 12.4, drone 9.6, noise 12.0, vocal 11.9, second 10.3) | C (the owner's faders changed strings, stab and bed) |
| Drums | our two-step break, its rows and sounds; hats every 8th (Nether: every even row, the same thing); where they play follows Nether: the break in Nether's break-loop orders and cut on row 58 where Nether cuts its riff, the hats' windows, the stab at Nether's stab orders, the sub outside departure 1, a crash on row 0 at Nether's crash orders, the last bar stepped down as Nether's (64/40/22/10/4 against 64/40/20/10/5) | sounds and rows O, hats G, placement C |
| Melodic cells | our notes; the guards allow at most one shared interval in a row | O |
| Rhythm of the lines | the sequence on every 8th, the lead on rows 2/4/6, the second line on rows 0 2 4 6 10 14 | C |
| Harmony, colours | the colours at Nether's places: the strings' major seventh on the minor sixth, the hit's near-minor-second detune, the minor triads of the drone and vocal pad; the bed a triad (Nether: fifths); the sub stays on A (Nether moves to the minor seventh in C) | C, with two departures |

### Vantage against Foregone Destruction

| Dimension | What Vantage does | Mark |
|---|---|---|
| Tempo, grid | 168 BPM (140/5), 4 rows a beat, 64-row patterns, identical | C |
| Key, root | E against F, a semitone away; one root throughout | key O (1 semitone), one-root harmony C |
| Form | 32 orders, 3:03 (Foregone 44, 4:11); the layer plan and entry order kept (drums arrive late and leave for the break, a four-on-the-floor kick section late); section lengths ours | plan and order C, lengths O |
| Layer set, roles | sub drone as the loudest layer, a riff on three channels (main + two echoes), a minor bed and a major bed in surround, a three-chord motif with an echo, a choir call with an echo, a one-bar break in surround, kick, snare, hats, open hat, crash, reverse crash: Foregone's set, role for role | C |
| Riff | notes on every 8th from row 0 (as Foregone's main channels) with a glide on 93 % of them (Foregone 96-97 %); echo channels +1 row at 0.31 and +2 rows at 0.25 of the main's volume (Foregone +3 at 0.33 and +2 at 0.25) | rows and glides C, one echo delay C, one O |
| Hats | a cymbal on every 8th cut by the next, S8x pan sweep, ghosts on rows 13 and 15 | C |
| Snare, kick, open hat | snare rows the same as Foregone's; the kick every 4 rows; the open hat on rows 2, 10, 14, 18, 26, 30, 34, 42, the same rows as Foregone's | C |
| Break | retriggered on rows 0, 6, 16, 32, 38, 48 with a pickup on 62, an offset jump to its beat-2 snare, S91 surround; its content a common funk bar | rows and idioms C, content O |
| Beds | the minor bed struck on row 0 of every pattern; the major bed re-entering on row 36 with a D swell and dying from 56 | C |
| Sub | one tonic note on row 0 of every pattern | C |
| Motif | rows 0/6, 5/11, 10/16, echo +6 rows at 0.4 (Foregone 0/4, 6/10, 12/16, echo +4 at 0.5) | idiom C, numbers O |
| Choir | octave-up call first, echo +6 rows at 0.5 (Foregone echo +4 at 0.31) | idiom C, numbers O |
| Harmony, colours | the motif's chord qualities (add9, 7sus4, minor 9th) and a minor and a major bed over one root: Foregone's colour set (the major bed's relation to the root differs) | C, one relation O |
| Sample character | storage rates (11 kHz beds and choir, 22 kHz riff, bass and motif) and descriptive targets taken from Foregone's samples (a dark bed near 200 Hz, a stab attack of 30-130 ms); sources Surge patches, additive models (riff, sub) and CC0/TR-8 drums | targets C, sources O |
| Levels | the sub drone loudest, the chords low | C |
| Melodic cells | our riff notes (reordered once when its first four notes matched) | O |

In both pieces, "ours" covers the notes, the cells, the sources and a few numbers. Everything that decides how a
passage behaves is copied: which layers play, what each one does on which row, how it moves, how loud it is and when
it enters.

## 2. How close, against how close UT99 tracks get to each other

### Order by order (`sections.py`)

Every order of the 28 readable UT99 modules (1086 orders), and of our pieces, is described as a set of layers. Each
layer is one sample sounding in the order, with:
- where it strikes in the bar and how often;
- whether it is struck or only held;
- its sound as played (centroid, flatness, length, loop, number of pitches);
- its idioms (glides, offsets, slides, pans, echoes, re-strikes);
- its level against the order's loudest layer.

Two orders' distance matches each layer to its closest counterpart in the other order. The baseline is each UT99
order's nearest order in another UT99 track: minimum 0.125, 5th percentile 0.164, median 0.214. Seeker and Seeker 2
share material, so they don't count as a pair; the XM module (Firebreath) and the duplicate Save Me are left out.

| | Rift / Nether | Vantage / Foregone | Nadir (no reference) |
|---|---|---|---|
| orders whose closest order in all of UT99 is in the reference | 48 of 55 | 28 of 32 | its nearest orders spread over 7 tracks (Title 16, Skyward 9, Nether 4, ...) |
| the same share between different UT99 tracks (a track's orders whose nearest is in its most frequent other track, picked afterwards from 26, so a generous baseline) | median 0.47, up to 0.79 (Skyward to Run, Organic to Go Down; Nether to Foregone 0.71): Rift 0.87 and Vantage 0.88 lie above every UT99 track | | |
| median distance to the nearest reference order (percentile of the baseline) | 0.162 (4.4 %) | 0.189 (21.8 %) | 0.210 (44.9 %) to its nearest UT99 order |
| orders closer to the reference than any UT99 order is to another track (under 0.125) | 12 | 0 | 0 |
| longest run of consecutive orders under the baseline's 5 %, following the reference's orders | 20 | 0 | – |
| the same, between any two different UT99 tracks (377 pairs) | longest 4 (Go Down / Organic), the only pair to reach 4 | | |

Rift by section, against the same-index order of Nether. The component costs run from 0 (identical) to 1; their
baseline medians are rhythm 0.26, density 0.15, level 0.22, sound class 0.33, idioms 0.08.

| Section | Orders | Distance (percentile) | Rhythm | Density | Level | Sound class | Idioms |
|---|---|---|---|---|---|---|---|
| intro | 0-3 | 0.109 (0.0 %) | 0.08 | 0.03 | 0.21 | 0.17 | 0.03 |
| build | 4-9 | 0.196 (29 %) | 0.29 | 0.10 | 0.26 | 0.34 | 0.03 |
| A | 10-17 | 0.208 (44 %) | 0.25 | 0.18 | 0.30 | 0.32 | 0.04 |
| break 1 | 18-19 | 0.194 (27 %) | 0.14 | 0.06 | 0.30 | 0.42 | 0.05 |
| B | 20-23 | 0.177 (13 %) | 0.17 | 0.09 | 0.24 | 0.34 | 0.05 |
| peak | 24-29 | 0.206 (39 %) | 0.29 | 0.11 | 0.20 | 0.30 | 0.05 |
| break 2 | 30-31 (2:55-3:06) | 0.122 (0.0 %) | 0.06 | 0.01 | 0.24 | 0.29 | 0.02 |
| C | 32-48 (3:06-4:45) | 0.131 (0.2 %) | 0.13 | 0.03 | 0.12 | 0.29 | 0.05 |
| outro | 49-54 | 0.164 (5.1 %) | 0.19 | 0.08 | 0.17 | 0.30 | 0.06 |

The two passages the owner named are where the measure finds the trace too. The intro (median 0.109) and break 2
(0.122) sit closer to Nether's orders at the same place than any UT99 order sits to another track's (0.125). C (0.131)
sits just above that line, with 2 of its 17 orders under it, and at the 0.2nd percentile. The outro follows at 5 %,
with two orders under the line. In these sections the rhythm and the density are near-identical (0.01-0.13 against
baseline medians of 0.15-0.26). The idioms are near-identical everywhere (0.02-0.06 in every section), so they do not
single out these passages, but they are copied throughout. The sound class sits nearer the baseline (0.29 in break 2
and C against 0.33), except in the intro (0.17, the closest of any section). Its measure is partly how a sample is
stored (length, loop, number of pitches), not only how it sounds. The build, A and the peak lie at 29-44 %. There,
by inference rather than measurement, our approved break, sub and stab stand where Nether has a kick, a chopped break
and a loud stab.

Vantage's orders follow Foregone less closely by this measure (none under the minimum, no run). Two causes:
- its motif and choir rows and its form lengths were changed;
- this measure reads rows and sample classes per order, and Vantage's copies sit mostly in the whole-song frame.

### Whole-song dimensions (`globaldims.py`, `formcurve.py`)

Each row gives the distance from ours to the reference, as a percentile of the 405 pairs of different UT99 tracks. 0 %
means closer than any two UT99 tracks. The bass root and the chroma come from `analyze.py`: it reads Nether as D (its
+30 c tuning) and Rift as E, so for Rift the key and harmony rows are unreliable. The real relation is A against C#, 4
semitones.

| Dimension | Rift / Nether | Vantage / Foregone |
|---|---|---|
| tempo | 9.6 % | 0.0 % (identical) |
| grid (speed) | same (21 % of pairs share one) | same |
| key (tonic distance) | 4 semitones (see note) | 1 semitone (9 %) |
| harmony (chroma over the root) | 60 % (misread) | 8.4 % |
| harmonic motion | 78 % | 50 % |
| spectrum balance | 63 % | 97 % |
| mix (width, flatness, centroid) | 54 % | 11 % |
| dynamics and arc | 8.1 % | 4.2 % |
| rhythm density (onsets, flux, pulse) | 3.0 % | 36 % |
| length | 12 % | 42 % |
| layer-count curve over the song (377 pairs) | 0.0 % | 47 % |
| entry schedule (share of samples entered over time, 377 pairs) | 8.2 % | 18 % |

Vantage copies the frame: the tempo and grid, a key a semitone away, the harmony profile, the width and the dynamic
arc; tempo, harmony, mix and dynamics each closer than 89-100 % of UT99 pairs, the grid shared as 21 % of pairs share
theirs, the key closer than about 74 % (17 % tie). Counted at the 5th percentile, though, the frame alone is not a trace
signal. Rift has 1 of 8 whole-song dimensions there (the ten above without grid and key: rhythm density) and Vantage 2
(tempo, dynamics), which puts Vantage among the closest 5.4 % of UT99 pairs, borderline rather than clear. Among the 405
pairs of different UT99 tracks, 22 have 2 or more and 4 have 3. Rift copies the timeline: the layer-count curve (closer than every UT99
pair), the arc, the rhythm density and the entries. Neither is close in spectrum balance or sound class. That fits the
sounds being our own and still not enough.

## 3. Reading

- A trace is not one dimension. It is the reference's choices kept together, at the reference's places. In Rift that
  means, per section, the same layers doing the same things on the same rows at the same levels. The measure finds a
  run of 20 orders in Nether's order, where two different UT99 tracks never share more than 4. In Vantage it is the
  same tempo, grid, colour set, layer plan and drum rows at once.
- Averaging (Nadir) removed the runs but also every choice a real track makes together: its nearest orders scatter
  over 7 tracks at an ordinary distance (45 %). The owner judged the approach wrong ("combined too many songs in one";
  "jumbled" was their word for v2); the v6 measured here has not been heard.
- What stays our own in both pieces (notes, cells, sources) is exactly what the measures above find least decisive.
  The dimensions that carry the likeness in the measures (form and entries, per-layer idioms and rows, the layer set,
  levels, and for Vantage the frame) are the ones the method copies.
- What the measures can and cannot see. Rift's trace shows plainly in two figures: the 20-order run (UT99 pairs top
  out at 4) and 12 orders closer than any two UT99 tracks get. Vantage's shows weakly: none of its orders goes
  under the minimum, it has no run, and its frame sits within what UT99 pairs share. Its likeness is still plain in the
  inheritance table (the drum, riff and bed rows, the colour set, the layer plan and the grid, all copied), and in its
  share of nearest orders (0.88, above every UT99 track's 0.79 at most). A measured distance alone therefore cannot
  certify "not a trace"; the audit of what is copied has to sit beside it.
- These readings are measurements. The variants in `suite/rift/variants/` (LISTENING.md) test them by ear, one
  dimension at a time.
