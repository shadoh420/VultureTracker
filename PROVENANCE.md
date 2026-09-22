# Provenance: what is derived from what

The Unreal Tournament 99 soundtrack is Epic's (Foregone Destruction was composed by Michiel van den Bos) and cannot
be used or redistributed. Epic's 2024 permission to distribute the old games for free covers the games as shipped,
not reuse of their music. Foregone Destruction was the *reference* for demo4 "Vantage": nothing in this repository
ever contained its audio, and since 2026-09-21 nothing in it is measured from or copied from it either. This file
records what the reference contributed (descriptions and generic techniques, which are anyone's to use), what used
to be closer and was replaced, and how to keep it that way.

## What Vantage takes from the reference (descriptions, kept)

- The grid: tempo 140, speed 5, 4 rows per beat, 64-row patterns; sample rates of 11 kHz for beds and choir and
  22 kHz for riff, bass and motif.
- The layer plan: a sub-bass drone as the loudest layer, chords low, an intermittent portamento riff, a choir call
  in the build and the break, a one-bar break loop, drums late and out for the break, one root throughout with
  voicing changes over the pedal.
- Cell idioms of the style: beds retriggered per pattern, a swell that re-enters mid-pattern, GFF portamento riffs
  with delayed echo channels, a cymbal on every 8th with an S8x pan sweep, D01/DF3/DF2 fades, S91 surround on the
  beds and the break, a sample-offset replay of a break's snare.
- Descriptive targets used to *choose* sounds: a dark bed around 200 Hz centroid, a bright stab with a 30-130 ms
  attack, a short snare with a 2-4 kHz crack, a sub bass of a sine over a low-passed sawtooth.

## What was replaced (2026-09-21)

- [x] Chord beds, motif stabs and choir: were additive resyntheses of spectral snapshots of specific reference
  samples (48-partial tables and noise floors). Now Surge XT factory patches rendered by `demo4/kit.yaml`, picked
  by the descriptive targets above; the candidates and their measurements sit in the gitignored
  `samples/local/demo4-cand/`, so any of them can be re-picked in the tryout app. The tables are deleted.
- [x] Riff and sub-bass models: were harmonic series measured on reference samples. Now written from the generic
  description in `demo4/gen_samples.py` (a near-sine; a sine plus a sawtooth low-passed at 300 Hz with a slow dip).
- [x] The riff's opening cell shared its first four notes with the reference's riff; the cell order is changed
  (`RIFF` and `RIFF_S` in `demo4/gen_patterns.py`).
- [x] The motif hook (three hits on 0-6-12 with a four-row echo) and the choir call (rows 0 and 6, echoed four rows
  later) now sit on 0-5-10 with a six-row echo, and on rows 0 and 8 with a six-row echo.
- [x] The break: was a transcription of the reference's recorded loop including its per-hit levels and
  millisecond timing offsets, EQ-matched to that loop's octave bands. Now a common funk pattern with a generic
  accent scheme and a uniform push, no EQ matching (`demo4/gen_break.py`); the audio was always the CC0 Big Rusty
  Drums kit.
- [x] Comments, the song header and the docs no longer name the reference's sample files or describe passages as
  copies of it.

## The suite (suite/): pieces inspired by groups of the UT99 soundtrack

The 30 soundtrack modules were extracted and measured locally (`scratch/ut99-clean/`, gitignored: played tempo and
speed, spectrum, key, onsets, per-channel idioms, form) and sorted into five stylistic groups; each piece of the suite
is written for one group. What a piece takes is descriptive (grids, layer roles, rhythmic and textural idioms, the
shape of a form); no audio, no sample data, no measured sample table and no melodic cell is taken from any module,
and no sound is chosen by matching a specific module's sample.

- `suite/nadir/` (Nadir, the dark group: Skyward Fire, Seeker, Seeker 2, Enigma, Colossus, Nether Animal, Mechanism
  Eight): a driving 144 BPM grid under a dark mood, a sub drone as the loudest layer, one modal pedal (a held root instead
  of a chord progression; v6 dropped the breakdown's second colour), a dotted single-note pulse, a 16th arp, a
  portamento riff with an echo (v6 dropped the dotted-8th sequence line), a choir cluster, a recorded drum bar chopped
  with sample offsets in surround, long crescendo arcs with a one-pattern dip. Sounds: additive and noise models
  written from descriptions (`gen_samples.py`), CC0 drums (`gen_drums.py`) and CC0 string sections (`gen_strings.py`),
  Surge XT factory patches picked by measurement against the piece's own targets (`cand.yaml`, `cand2.yaml`,
  `measure.py`, `kit.yaml`) and given noise floors (`gen_floor.py`). The finished render was compared with the group's measured
  ranges (sub share, centroid, flatness, onsets, width, dynamics) to check it lives in the same world, which is a
  check of character, not a copy of any track.

## Must never be committed (already gitignored, keep it that way)

- [x] `scratch/ut99/`: extracted reference modules, their samples, imports and renders. Reference only, local only.
- [x] `demo4/vantage.it` and other `.it` renders: they embed the MusicRadar hits (see below).

## Third-party sounds that are not Epic's

- OK, CC0: Big Rusty Drums (Karoryfer Samples), VSCO 2 cymbal swell and gong, VCSL (`tools/cc0/`, `samples/demo3/`,
  `samples/demo4/break.wav`; credits in the `ATTRIBUTION.md` files).
- OK for music, not redistributable: MusicRadar's hardware drum-machine pack (TR-8, Jomox Airbase 99, Alesis HR-16b
  hits used by demo3 and demo4). Renders live in `samples/local/` (gitignored); the pack's terms allow use in your
  music, so the finished songs are fine, only the raw hits and the `.it` files stay out of the repo.
- OK: audio rendered from Surge XT, OB-Xd and Dexed factory patches (GPL programs; the renders are yours).
- Credited, terms unstated: Dexed ships the "SynprezFM" DX7 cartridges by Jean-Marc Desprez, used for demo3's Rhodes
  lead and string pad (`demo3/kit.yaml`). Dexed's README credits them without a license statement. The renders are
  our own recordings of those patches; if that is not good enough for a use, re-render the two sounds from Surge
  patches with the tryout app.

## How to keep this current

When a sound or a figure is added by measuring something we do not own, add it here with the file, the table or
function that holds the derived numbers, and the replacement; when it is replaced, tick it and delete the derived
data from the code in the same commit. Descriptions of a sound or a technique are fine; snapshots of a specific
sample and copied melodic cells are not.
