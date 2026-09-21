# VultureTracker guide

The short version is [README.md](README.md); this is the long one: the app, the demos, samples, tests and notes.

Write sample-based tracker music as a readable YAML text file and compile it to a real Impulse
Tracker module (`.it`). Every note, instrument, envelope and effect stays visible and editable, by
hand or by an AI.

```
song.yaml ──build──▶ song.it ──render──▶ song.wav
```

## Setup

```
git clone https://github.com/shadoh420/VultureTracker.git
cd VultureTracker
pip install pyyaml
```

Python 3.10+. On Windows x64, libopenmpt (used to verify and render) is included in `vendor/`.
Elsewhere, install libopenmpt (e.g. `apt install libopenmpt0`) or set `LIBOPENMPT` to its path.

## Usage

```
python -m vulturetracker check demo/arena.yaml                        # validate; errors show file:line
python -m vulturetracker build demo/arena.yaml -o demo/arena.it       # compile, then verify with libopenmpt
python -m vulturetracker build demo/arena.yaml --render demo/arena.wav # compile and render in one go
python -m vulturetracker render demo/arena.it -o demo/arena.wav --repeat 1
python -m vulturetracker info demo/arena.it                           # what libopenmpt sees
python -m vulturetracker import some.it -o some.yaml                  # existing .it -> song file + WAVs
```

`pip install -e .` also installs a `vulturetracker` command.

## GUI: choosing samples in context

```
python -m vulturetracker gui demo4/vantage.yaml
```

opens the app in its own window (`pip install pywebview`; without it, or with `--browser`, it opens in your
default browser instead; either way it is served on localhost and nothing leaves your machine). Run it with
no song to get the open-a-song screen with recent songs and the demos. Pick a sample slot and
a section of the song, add candidate WAVs by path or glob, and each candidate is rendered inside the song with
only that slot swapped. Keys `1`–`0` switch candidates without losing the playback position, `S`/`M` toggle
the sample alone vs. in the mix, stars/reject/notes are kept per candidate beside the song
(`<song>.tryout.json`), and `U` shows the one-line YAML change before writing it. The Song Overview tab has a stems rail (mute or solo
channels and the tryout re-renders without them; EXPORT STEMS writes one WAV per playing channel to
`<song>_stems/`), the arrangement grid and slot table, and a read-only pattern view that follows the selected
order and the playhead. Render & Export builds the `.it` (and a WAV) and verifies it with libopenmpt.
Renders are cached in `<song dir>/.tryout/`.

**Standalone binary:** `pip install pyinstaller && python tools/build_exe.py` produces `dist/vulturetracker.exe`,
the whole CLI with libopenmpt bundled: `vulturetracker.exe gui song.yaml`. Double-clicking it opens the app on its
open-a-song screen; dropping a song file onto it opens that song. Synth rendering (`synth`, `audition`)
still needs the plugins and packs from `tools/` next to a checkout, as described in SAMPLING.md.

## Making samples: synths, recordings, printed effects

`vulturetracker synth recipe.yaml` renders samples from a YAML recipe. A sample comes from a free synth
(Surge XT, Dexed's DX7 or OB-Xd's Oberheim: patch, notes or phrases, hold time) or from a recorded audio file,
such as the CC0 libraries that `tools/fetch_cc0.py` downloads or a royalty-free drum-machine pack. A recipe can print an effects chain into each
sample (reverb, delay, chorus, distortion, 8-bit / low-rate lo-fi) and bake in crossfaded loops.
`vulturetracker audition 'Pads/*'` (or a file glob) lets you hear a whole set of candidates in one WAV, and
`vulturetracker tryout` plays part of a song once per candidate sample, so you can choose sounds in context.
Setup and the recipe format are in **[SAMPLING.md](SAMPLING.md)**:

```
pip install pedalboard mido
python tools/fetch_surge.py            # Windows: portable Surge XT into tools/surge-xt/
python tools/fetch_instruments.py --install-obxd   # Dexed, OB-Xd, drum-machine samples
python tools/fetch_cc0.py              # CC0 recordings into tools/cc0/
python -m vulturetracker synth demo3/kit.yaml
```

## Writing songs

The song format is documented in **[SONG_FORMAT.md](SONG_FORMAT.md)**. It's the full reference,
written so an AI can compose from it alone. A song has `module` settings, numbered `samples`
(WAV files), `instruments` (keymaps and envelopes), named `patterns`, and an `orders` list. Pattern
rows use OpenMPT-style cells:

```yaml
patterns:
  main:
    rows: 16
    data: |
      00: C-5 01 v64 ... | E-3 02 ... ...
      01: ...            | ===
```

Four demos:

- `demo4/vantage.yaml`: "Vantage", 3:03 and loopable, E minor at 168 BPM (tempo 140, speed 5), in the style of a
  late-90s arena-shooter module: a sub-bass drone holds the tonic under everything, a synth riff on three
  round-robin channels rides over it, chord samples sit low (a minor bed, a major bed that swells once per pattern,
  a three-chord motif with an echo), a choir calls in the build and the break, drums arrive a minute in and leave
  for the break, and there is no lead melody and no chord progression. 16 channels, 32 patterns. The riff and sub
  bass are additive models (`demo4/gen_samples.py`); the beds, motif chords and choir are Surge XT patches rendered
  by `demo4/kit.yaml`; the rhythm bed is a one-bar break played by the CC0 Big Rusty Drums kit (`demo4/gen_break.py`)
  under MusicRadar drum-machine hits (`demo4/drums.yaml`) and demo3's TR-8 renders. Patterns are laid out by
  `demo4/gen_patterns.py`. UT99's Foregone Destruction was the reference for its grid and layer plan;
  `PROVENANCE.md` says what was taken from it and what was changed.
- `demo3/undertow.yaml`: "Undertow", 3:12 and loopable, E minor at 125 BPM, built on what the Unreal
  Tournament (1999) soundtrack modules measure: 16 channels in sample mode at speed 6 (4 rows per beat,
  4-bar patterns), 16-bit samples at 11 kHz (pads) to 22 kHz (bass, lead), 21 distinct patterns over 25
  orders. Its sounds were picked by ear with `tryout`: Roland TR-8 drums, an OB-Xd analog bass and gated
  string machine, a Dexed DX7 string pad, a soft DX7 Rhodes lead with chorus and a long reverb printed in,
  and CC0 cymbals (`demo3/kit.yaml`, `demo3/drums.yaml`). It shows hard-panned L/R channel pairs with small
  `Oxx` offsets (drums) or a one-tick `SD1` delay (lead) for width, per-hit `S8x` hat panning, volume-slide
  (`Dxy`) gating of a sustained chord, and `FF1`/`EF1` detune between pairs. Its patterns are laid out by
  `demo3/gen_patterns.py`. The drum samples can't be redistributed, so building it needs
  `tools/fetch_instruments.py` and `synth demo3/drums.yaml` first.
- `demo2/iron_relay.yaml`: "Iron Relay", 55 s, D minor at 140 BPM, modelled on late-90s
  arena-shooter modules. It has 16 channels at speed 3 (32nd-note grid). Its 15 samples are
  rendered from Surge XT by `demo2/kit.yaml`. It shows the classic techniques: a sequenced arp
  phrase chopped with `Oxx` and transposed per chord, `Zxx` filter sweeps, a multisampled bass
  with portamento slides, crossfade-looped stereo pads, a reverse-cymbal riser, `Qxy` snare rolls,
  note-delay swing, and echo channels. Its patterns are laid out by `demo2/gen_patterns.py`.
- `demo/arena.yaml`: the first, simpler 42-second demo with procedurally generated placeholder
  samples. Its patterns are laid out by `demo/gen_demo.py`.

Each generator holds the musical choices (chords, rhythms, melodies) as Python data and rewrites the
patterns in its song file. Rerun it after changing those choices, or just edit the YAML directly.

## Using your own samples

The WAVs in `samples/surge/` are rendered from Surge XT, those in `samples/demo3/` from OB-Xd, Dexed
and CC0 recordings (credited in `samples/demo3/ATTRIBUTION.md`), and those in `samples/demo4/` are additive
models measured on a reference module plus a break played by a CC0 drum kit (`samples/demo4/ATTRIBUTION.md`);
see above. `samples/local/` holds renders of
samples that may not be redistributed and is gitignored. The ones directly in `samples/`
are procedurally generated placeholders (`samples/gen_placeholders.py`).
To use real ones, change a sample's `file` in the song. Also set `base_note` to the pitch recorded
in the WAV, and `loop` if it should sustain (`loop: from_wav` uses loop points saved by a sample
editor). Then `check` and `build`.

## Provenance

`PROVENANCE.md` tracks every sound or figure that was derived by measuring material we do not own (the UT99
reference modules for demo4), how far each is from the original, and what replaces it before a release.

## Tests

```
python -m unittest discover tests
python tests/fetch_fixtures.py   # optional: downloads OpenMPT's IT test modules for the import round-trip test
```

## Notes

- Output is IT 2.14 format in instrument mode with uncompressed 8/16-bit samples, playable in
  OpenMPT, Schism Tracker, Impulse Tracker and anything built on libopenmpt.
- `import` keeps patterns, instruments, envelopes and samples. It drops embedded MIDI macros and
  OpenMPT-only extensions (with a warning).
- `vulturetracker/api.py` exposes plain functions (`new_song`, `add_sample`, `add_instrument`,
  `set_pattern`, `set_orders`, `check`, `build`, `render`) for tools and agents.
- The writer follows [ITTECH.TXT](https://github.com/schismtracker/schismtracker/wiki/ITTECH.TXT)
  and was checked against OpenMPT's
  [Load_it.cpp](https://github.com/OpenMPT/openmpt/blob/master/soundlib/Load_it.cpp).
- Bundled libopenmpt is BSD-licensed; see `vendor/LICENSE.txt` and `vendor/Licenses/`.
