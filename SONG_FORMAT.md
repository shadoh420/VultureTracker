# VultureTracker song format (v1)

A song is one YAML file that compiles to an Impulse Tracker module (`.it`; instrument mode when it has `instruments:`, sample mode without). This
document is the complete reference: everything the compiler accepts is described here.

```
python -m vulturetracker check song.yaml            # validate only (errors carry file:line)
python -m vulturetracker build song.yaml -o song.it # compile, then verify with libopenmpt
python -m vulturetracker render song.it -o song.wav # listen without a tracker
```

## 1. Minimal example

```yaml
module:
  title: Hello
  tempo: 125            # T: BPM when speed = 6 and a beat is 4 rows
  speed: 6              # A: ticks per row
  channels: 2           # or a list of channel settings (section 3)

samples:
  1: {file: samples/kick.wav}
  2: {file: samples/bass.wav, base_note: C-3, loop: {start: 0}}

instruments:
  1: {name: Kick, sample: 1}
  2:
    name: Bass
    sample: 2
    volume_envelope: {nodes: [[0, 64], [4, 48], [20, 40]], sustain: 2}

patterns:
  main:
    rows: 16
    data: |
      00: C-5 01 v64 ... | E-3 02 ... ...
      01: ...            | ...
      02: ...            | E-4 02 v40
      03: ...            | ===
      04: C-5 01         | G-3 02

orders: [main, main]
```

## 2. File layout

Top-level keys (no others are allowed):

| key | required | meaning |
|---|---|---|
| `module` | yes | global settings and channels |
| `samples` | yes | numbered sample slots `1..99` → WAV file + playback settings |
| `instruments` | no | numbered instrument slots `1..99`. **If present, the module uses instrument mode** and pattern cells refer to instruments. If absent, cells refer to samples directly. |
| `patterns` | yes | named patterns, each a grid of rows × channels |
| `orders` | yes | playback order: a list of pattern names |
| `sections` | no | named non-overlapping spans of order entries; editor annotations only |
| `requires` | no | the oldest VultureTracker that reads the song, quoted: `requires: "1.2"` (section 10) |

Unknown keys anywhere are errors, so typos are caught. Numbers are decimal unless stated otherwise
(effect parameters are hex); a number written with a leading zero (`08`, `0125`) is decimal too, not YAML 1.1's
octal, in the compiler and in the app alike. Gaps in sample and instrument numbering are allowed: missing slots are empty.

YAML notes: quote text containing `: ` or starting with `[`, `{`, `#`, `&`, `*`, `!`, `|`, `>`, `%`, `@`.
Bare `off` is fine for the enum fields below that take `off`; a bare `on`, `yes` or `no` reads as true or false,
which no enum field takes (write the value itself). Give patterns names that start with
a letter.

## 3. `module`

| key | range | default | meaning |
|---|---|---|---|
| `title` | ≤25 ASCII chars | `""` | song title (an imported one has its accents dropped) |
| `tempo` | 32–255 | 125 | initial tempo (IT "T") |
| `speed` | 1–255 | 6 | initial ticks per row (IT "A") |
| `rows_per_beat` | 1-255 | 4 | grid/metronome beat spacing; displayed BPM = tempo * 24 / speed / rows_per_beat |
| `rows_per_bar` | 1-255 | 16 | grid/metronome bar spacing; stored with beat spacing in the IT row-highlight header |
| `global_volume` | 0–128 | 128 | initial global volume (the `V` effect changes it) |
| `mix_volume` | 0–128 | 48 | output gain. Raise it if the render is quiet, lower it if it clips. |
| `separation` | 0–128 | 128 | stereo separation |
| `linear_slides` | bool | true | linear pitch slides (keep true) |
| `old_effects` | bool | false | IT "old effects" mode (keep false) |
| `compatible_gxx` | bool | false | IT "compatible Gxx" mode (keep false) |
| `channels` | 1–64, or list | required | channel count, or one entry per channel |
| `message` | text | none | song message stored in the file (at most 65534 characters, IT's limit; Latin-1, other characters stored as `?`); several lines as a literal block (`message: \|`), which the app's MESSAGE box writes |
| `sample_rate` | 4000–192000 | none | resample every sample to this rate when compiling (band-limited; loop points and `c5_speed` follow, and each loop is resampled as it plays, so its wrap stays seamless). Samples stored at the playback rate neither image nor alias in the player near their root; a bright sample played more than about three semitones below it still images under 20 kHz, and `check` warns when those images come within 60 dB of it (88200 clears them). The file grows accordingly. Needs numpy. |
| `plugins` | mapping | none | mix plugins: OpenMPT's built-in DMO effects (section 3.1) |
| `macros` | mapping | none | SFx macros `SF0`..`SFF` of the embedded MIDI configuration, e.g. `SF1: F0F080z` (section 3.1) |
| `ceiling` | 1000–96000 | 18000 | Hz: how high `check` lets a sample's content reach when a note plays it above its root (the top of its spectrum, where it comes within 60 dB of its loudest band, times the transposition ratio); set it to the drums' own top to keep every sound under them. For `check` only, not stored in the .it. Added after 1.5.2: a song that sets it says so with `requires:` |
| `key` | text | none | the song's key, e.g. `A minor`, `F# major`, `D dorian` (major, minor and the seven modes): for people and agents, and the key `check` holds drums' ring tones to (§9); not stored in the .it |

Channel entry: `{name: Bass, pan: 32, volume: 64, muted: false}`

| key | range | default | meaning |
|---|---|---|---|
| `name` | ≤20 ASCII chars | `""` | label for humans; stored in the .it as OpenMPT stores channel names (its `CNAM` chunk, which keeps 19 characters), with the pattern names (`PNAM`, 32 characters) |
| `pan` | 0–64 or `surround` | 32 | initial pan: 0 = hard left, 32 = centre, 64 = hard right |
| `volume` | 0–64 | 64 | initial channel volume (the `M` effect changes it) |
| `muted` | bool | false | channel starts muted |
| `plugin` | plugin number | none | the mix plugin the channel plays through (section 3.1) |
| `approved` | bool | false | the owner's mark: the agent tools leave this channel alone |
| `color` | `"#rrggbb"`, quoted | none | the channel's colour in the app (the rail, the Pattern tab's header, the roll's ghosts); not stored in the .it, as `name` is kept only for the app. Quote it: unquoted, `#` starts a YAML comment. Added after 1.5.2: a song that sets it says so with `requires:` |

**Timing.** A tick lasts `2.5 / tempo` seconds. A row lasts `speed` ticks. With speed 6 and 4 rows
per beat, BPM = tempo. In general `BPM = tempo × 24 / (speed × rows_per_beat)`. Envelopes and
most effects run per tick.


### 3.1 Mix plugins

```yaml
module:
  channels:
    - {name: Lead, plugin: 1}
  plugins:
    1: {effect: echo, left_delay: 375, feedback: 30, output: 2}
    2: {effect: waves_reverb, reverb_time: 1500}
  macros:
    SF1: F0F080z      # SF1, then Zxx on the Lead channel, sets plugin 1's parameter 0 (wet_dry) to xx / 127
```

A channel plays through its `plugin`; a plugin passes its output to `output` (another plugin's number) or, without it,
to the master mix. These are OpenMPT's nine built-in DirectX Media Object effects, with OpenMPT's parameters, units and
defaults, written into the .it as OpenMPT saves them. **Only OpenMPT and libopenmpt play them** (this app and players
built on libopenmpt); other trackers play the channels dry. The app's RACK tab edits them.

Plugin keys: `effect` (required), `name` (≤31 characters), `output` (a plugin number; none = master), `bypass` (bool),
`output_gain` (0.1–25.5, the plugin's output gain as a factor, default 1), `dry` (0–1, the dry signal mixed back in),
`master` (bool, OpenMPT's "apply to master mix"), and the effect's parameters below (each optional, its default in
brackets):

For effects without their own `gain` parameter, `gain` remains an alias for `output_gain` (use one, not both).
For Compressor, Distortion and Parametric EQ, `gain` is always the effect's dB parameter in the table below.

| effect | OpenMPT's name | parameters |
|---|---|---|
| `chorus` | Chorus | `wet_dry` 0..100 % (50), `depth` 0..100 % (10), `frequency` 0..10 Hz (1.1), `waveform` square/sine (sine), `phase` -180/-90/0/90/180 (90), `feedback` -99..99 % (25), `delay` 0..20 ms (16) |
| `compressor` | Compressor | `gain` -60..60 dB (0), `attack` 0.01..500 ms (10.01), `release` 50..3000 ms (200), `threshold` -60..0 dB (-20), `ratio` 1..100 :1 (2.98), `predelay` 0..4 ms (4) |
| `distortion` | Distortion | `gain` -60..0 dB (-18), `edge` 0..100 % (15), `pre_lowpass` 100..8000 Hz (8000), `post_eq_center` 100..8000 Hz (2399), `post_eq_bandwidth` 100..8000 Hz (2399) |
| `echo` | Echo | `wet_dry` 0..100 % (50), `feedback` 0..100 % (50), `left_delay` 1..2000 ms (500), `right_delay` 1..2000 ms (500), `pan_delay` no/yes (no) |
| `flanger` | Flanger | `wet_dry` 0..100 % (50), `waveform` square/sine (sine), `frequency` 0..10 Hz (0.25), `depth` 0..100 % (100), `phase` -180/-90/0/90/180 (0), `feedback` -99..99 % (-50), `delay` 0..4 ms (2) |
| `gargle` | Gargle | `rate` 1..1000 Hz (20.98), `waveform` triangle/square (triangle) |
| `i3dl2_reverb` | I3DL2Reverb | `room` -10000..0 mB (-1000), `room_hf` -10000..0 mB (-100), `rolloff` 0..10 (0), `decay_time` 0.1..20 s (1.493), `decay_hf_ratio` 0.1..2 (0.83), `reflections` -10000..1000 mB (-2602), `reflections_delay` 0..0.3 s (0.07), `reverb` -10000..2000 mB (200), `reverb_delay` 0..0.1 s (0.011), `diffusion` 0..100 % (100), `density` 0..100 % (100), `hf_reference` 20..20000 Hz (5000), `quality` 0/1/2/3 (2) |
| `param_eq` | ParamEq | `center` 80..16000 Hz (8000), `bandwidth` 1..36 semitones (12), `gain` -15..15 dB (0) |
| `waves_reverb` | WavesReverb | `in_gain` -96..0 dB (0), `reverb_mix` -96..0 dB (0), `reverb_time` 0.001..3000 ms (1000), `high_freq_rt_ratio` 0.001..0.999 (0.001) |

**Automation.** IT's `Zxx` (00–7F) runs the channel's active SFx macro; SF0 is the filter cutoff by default. A macro
`F0F` + (128 + the parameter's index, three hex digits) + `z` sets that parameter of the channel's own plugin (not one
further down its chain) to xx / 127 of its range: `F0F080z` is the first parameter, `F0F081z` the second. Select the
macro with `SFx` in the channel, then write `Zxx`. A song that uses `plugins` or `macros` needs VultureTracker 1.3 or
newer: say so with `requires: "1.3"`.

## 4. `samples`

```yaml
samples:
  5:
    file: ../samples/bass.wav    # path relative to the song file
    name: Saw bass               # default: file name without extension
    base_note: C-3               # the pitch recorded in the WAV (default C-5)
    loop: {start: 32768}         # end defaults to the sample length
    volume: 64
```

| key | range | default | meaning |
|---|---|---|---|
| `file` | path | required* | WAV file: PCM 8/16/24/32-bit or float, any rate, mono or stereo (the app turns FLAC, AIFF, OGG and MP3 into WAVs beside the song when they are added). *A slot with only `name` (no `file`) is an empty sample slot. |
| `name` | ≤25 ASCII chars | file stem | sample name; instruments may refer to a sample by this name (from the file stem, accents are dropped: `Böse Bass.wav` is "Bose Bass") |
| `base_note` | note | `C-5` | the note at which the WAV plays at its recorded pitch |
| `c5_speed` | 256–9999999 | from WAV | playback rate for C-5, in Hz, for the WAV as written (rescaled with it under `module: sample_rate`). Use instead of `base_note` for fine tuning. |
| `volume` | 0–64 | 64 | default note volume (used when a cell has no volume command) |
| `global_volume` | 0–64 | 64 | fixed scaling of this sample |
| `pan` | 0–64 | none | if set, notes using this sample start at this pan |
| `loop` | see below | none | normal loop, active the whole time |
| `sustain_loop` | see below | none | loop active only until note-off (`===`), then playback continues past it |
| `vibrato` | see below | none | automatic vibrato applied to every note |
| `bits` | 8 or 16 | from WAV | storage depth (8-bit sources stay 8-bit; others become 16-bit) |
| `stereo` | bool | false | keep a stereo WAV as a stereo sample (libopenmpt/OpenMPT only; Impulse Tracker itself has no stereo). If false, stereo is mixed to mono. |

When the tryout or a dropped WAV points a slot at a new WAV, a `smpl` unity note in the WAV sets `base_note`; one
above B-9 (119) is no note and is ignored.

Pitch: `base_note: C-3` means the WAV contains a C-3, so playing `C-3` gives the recorded pitch and
`C-4` plays it an octave up. The compiler sets `c5_speed = wav_rate × 2^((60 − base)/12)`.

Loops, in sample frames: `{start: 0, end: 4096, type: forward}` (`type` is `forward` or `pingpong`).
`end` is exclusive (the first frame after the loop). `loop: from_wav` uses the loop stored in the WAV's
`smpl` chunk. For seamless loops, the loop length should contain whole waveform cycles.

Auto-vibrato: `{type: sine|ramp_down|square|random, speed: 0–64, depth: 0–64, rate: 0–255}`.
`rate` is the sweep: how quickly the vibrato fades in after a note starts (higher = faster).

## 5. `instruments`

An instrument maps notes to samples and adds envelopes and voice-management rules.

```yaml
instruments:
  1:
    name: Drum kit
    keymap:                                   # later entries override earlier ones
      - {notes: C-5, sample: Kick, play_note: C-5}
      - {notes: D-5, sample: Snare, play_note: C-5}
      - {notes: F#5, sample: 3, play_note: C-5}
  2:
    name: Bass
    sample: 5                                 # one sample for every note
    fadeout: 256
    nna: cut
    volume_envelope:
      nodes: [[0, 64], [3, 52], [16, 42]]     # [tick, value]
      sustain: 2                              # hold at node 2 until note-off
```

| key | range | default | meaning |
|---|---|---|---|
| `name` | ≤25 ASCII chars | `""` | instrument name |
| `sample` | number or name | none | shorthand: every note plays this sample at its own pitch |
| `keymap` | list | none | multisample map (below). Without `sample` or `keymap` the instrument maps no notes and is silent. |
| `fadeout` | 0–256 | 0 | fade speed after note-off or a fade action; 0 = never fades out. A note's fade level starts at 1024 and loses `fadeout` per tick, so 256 takes 4 ticks and 16 takes 64 ticks. |
| `nna` | `cut` `continue` `off` `fade` | `cut` | New Note Action: what happens to the playing note when a new note starts on the same channel. `cut` stops it; the others keep it in a background voice (`continue` lets it play on, `off` sends note-off, `fade` starts its fadeout). Use `fade` or `off` for pads and pianos so notes can overlap. |
| `dct` | `off` `note` `sample` `instrument` | `off` | Duplicate Check Type: which older background voices on the channel count as duplicates of the new note |
| `dca` | `cut` `off` `fade` | `cut` | Duplicate Check Action applied to those duplicates |
| `global_volume` | 0–128 | 128 | instrument volume scaling |
| `pan` | 0–64 | none | if set, notes on this instrument start at this pan |
| `pitch_pan_separation` | -32–32 | 0 | pan notes by pitch around `pitch_pan_center` |
| `pitch_pan_center` | note | `C-5` | |
| `random_volume` | 0–100 | 0 | random volume variation, % |
| `random_pan` | 0–64 | 0 | random pan variation |
| `filter_cutoff` | 0–127 | none | if set, enables the resonant low-pass filter at this cutoff |
| `filter_resonance` | 0–127 | none | filter resonance (used with `filter_cutoff`) |
| `filter_mode` | `lowpass` `highpass` | none | `highpass` turns the instrument's resonant filter into a high-pass (from its cutoff up). OpenMPT's extension, written where OpenMPT writes it: libopenmpt and OpenMPT play it, Impulse Tracker and other players play a low-pass. Added after 1.5.2: a song that sets it says so with `requires:`. Without `filter_cutoff`, `filter_resonance` or a `Zxx` it filters nothing (`check` warns). |
| `volume_envelope` | envelope | none | values 0–64 |
| `panning_envelope` | envelope | none | values -32 (left) to 32 (right), added to the channel pan |
| `pitch_envelope` | envelope | none | values -32–32 in half-semitones (-2 = one semitone down). Add `filter: true` to make it a filter-cutoff envelope instead. |
| `tuning` | a `.scl` file | none | the instrument plays a Scala scale instead of 12-TET (microtuning, below). Added after 1.5.2: a song that sets it says so with `requires:` |
| `keymap_file` | a `.kbm` file | none | the Scala keyboard map that lays `tuning` on the keys (below); only with `tuning` |

Keymap entry: `{notes: <note or range>, sample: <number or name>, transpose: <semitones>}` or
`{..., play_note: <note>}`.
- `notes`: one note (`C-5`) or an inclusive range (`C-0..B-4`). Notes outside every entry play silence;
  `check` warns when the patterns use such a note.
- default: the note plays the sample at the note's own pitch.
- `transpose: 12`: the note plays 12 semitones higher.
- `play_note: C-5`: every note in the range plays the sample at C-5. This is how drum kits keep
  each drum at its recorded pitch.

Microtuning: `tuning: scale.scl`, and optionally `keymap_file: map.kbm`, both paths beside the song, in Scala's formats
(huygens-fokker.org/scala). The .scl's pitches are cents when they hold a `.`, else ratios (`5/4`, `2` for 2/1); at
most 256 notes. Without a .kbm the scale goes on the keys OpenMPT's way: degree 0 on C-5 at the sample's own C-5 pitch,
one degree a key, so a 12-note scale is needed. A .kbm sets the middle note (where its first entry goes), the reference
note and its frequency, the range of keys retuned and the degree on each key (`x` for none); keys it leaves out, or
outside its range, play nothing. Each key is tuned from the note it plays (after `transpose` or `play_note`), against
12-TET at A-5 = 440 Hz. Only scales that repeat at the octave over 12 keys: the .scl's last degree must be 2/1 (1200.0
cents), and a .kbm must map 12 keys with the scale's size as its formal octave degree; anything else is a compile error.
IT has no tunings, so the compiler writes, for each key whose pitch is not 12-TET, a copy of its sample with
`c5_speed` times that ratio (one copy per sample and degree, sharing the sample's data in the .it, after the song's
samples; at most 99 samples in all); the app shows the slot, and a mix level for the slot reaches its copies.
`check`'s anti-aliasing measure takes each key at its 12-TET pitch (a scale degree moves it by its few cents).

Envelope: `{nodes: [[tick, value], ...], sustain: <i or [a, b]>, loop: [a, b], enabled: true, carry: false}`
- 1–25 nodes. The first tick must be 0 and ticks must increase (max 9999). Ticks are song ticks
  (section 3), so envelope speed follows the tempo.
- `sustain: i` holds at node `i` while the note is held; `sustain: [a, b]` loops between nodes `a` and
  `b` until note-off. After note-off the envelope continues to its end.
- `loop: [a, b]` loops between those nodes forever (after sustain is released). A loop plays its end node's tick
  too, then the start's: from tick 0 to tick 16 it repeats every 17 ticks (Impulse Tracker's rule, and libopenmpt's).
- `enabled: false` keeps the nodes but turns the envelope off (the `S78`/`S7A`/`S7C` effects can turn it on).
- `carry: true` makes a new note continue from the previous note's envelope position instead of
  restarting it. This is an OpenMPT extension: libopenmpt honours it, Impulse Tracker ignores it.
- `lfo: {shape, period, depth, centre, delay, attack, points, seed}` in place of `nodes`, `loop` and `sustain`: a
  low-frequency oscillator written as nodes when the song compiles (added after 1.5.2: a song that uses it says so
  with `requires:`). `shape` is `sine` (default), `triangle`, `square`, `saw`, `ramp` (a falling saw) or `random`
  (`points` values drawn from `seed`, the same each cycle); `period` is the cycle in ticks (default 16; more than
  `points`); `depth` how far it swings each way (default a quarter of the envelope's range: 16 for volume, 16 for pan
  and pitch, where pitch counts half-semitones, so 16 is eight semitones); `centre` the value it swings around (default:
  64 - depth for volume, so the peaks reach full volume; 0 for pan and pitch); `delay` ticks at the centre before it
  starts; `attack` ticks over which its depth grows from nothing; `points` nodes per cycle (default 8), linear between,
  so a square or a saw changes over one point's spacing (more points, sharper edges). After the delay and the attack,
  one cycle is looped for good, ending on the value it starts with. An envelope holds 25 nodes, so `points` + the
  attack's cycles + 3 must fit: an attack longer than a few periods does not. With `filter: true` on the pitch envelope
  it moves the filter cutoff. `enabled` and `carry` work as for nodes. Vibrato from the pattern (`Hxy`, `Uxy`) or from a
  sample's `vibrato:` needs no envelope.
- When the volume envelope reaches its last node, the note's fadeout starts. A note-off (`===`) starts
  the fadeout immediately only if the instrument has no volume envelope or its envelope loops. A
  note whose envelope ends above 0 with `fadeout: 0` keeps sounding at that level until it's cut or
  replaced.

## 6. Patterns

```yaml
patterns:
  verse:
    rows: 64              # 1..200; defaults to the number of rows written. The filled cells are stored at up to
                          # 7 bytes each, and IT holds 65535 bytes per pattern: about 9 000 filled cells
    data: |
      ; comment lines and blank lines are ignored
      00: C-5 01 v64 ... | E-3 02 ... A06 | ...
      01: ...            | ...
      02: D-5 01         | === .. ... ...
  fill: |                 # shorthand: the pattern is just its data (rows = rows written)
    C-5 01 v64 ... | ...
```

Rules:
- **One line per row.** Channels are separated by `|`, and a leading or trailing `|` is ignored.
- **Every written cell must contain something.** Write `...` for an empty cell.
- Rows may have fewer cells than the module has channels. Missing channels are empty.
- `rows` larger than the number of written rows pads with empty rows; more written rows than `rows` is an error.
- **Row labels.** An optional `NN:` prefix (decimal). If present it must equal the row's index, which
  catches added or dropped rows. Use labels in long patterns.
- `;` starts a comment that runs to the end of the line. Comment-only and blank lines are not rows,
  so you can separate bars with `; bar 2`.
- Use a literal block (`data: |`) so errors can report the exact line.
- **Marks** (they change nothing in the module): `approved: true` on a pattern, a channel entry or a sample entry is
  the owner's mark that the agent tools (GUIDE.md: Agents) leave it alone; `by:` on a pattern (`you`, `agent`, or
  `you and agent`) says who wrote it, set by the app when an agent writes the pattern.
- **Automation lanes.** `automation:` on a pattern is a list of curves the compiler writes into its cells, each the
  Pattern tab's AUTOMATE kept in the song and redone on every compile:

  ```yaml
  verse:
    rows: 64
    automation:
      - {target: Z, channel: 3, rows: [0, 63], from: 0x10, to: 0x7F, shape: scurve, every: 2}
      - {target: v, channel: Pad, rows: [32, 63], from: 64, to: 8}
    data: |
      ...
  ```

  `target` is `Z` (cutoff, or the SFx macro), `X` (pan), `M` (channel volume), `V` (global volume), `T` (tempo, 0x20
  up) or `v` (the volume column); `channel` a number from 1 or a channel's name (`V` and `T` are song-wide and go on
  that channel only); `rows` the first and last row, the whole pattern when left out; `from` and `to` whole numbers
  (write hex as `0x7F`); `shape` `linear` (default), `scurve`, `exp` or `steps`; `every` 1-64 rows between values
  (default 1). The values fall on the rows AUTOMATE would write (GUIDE.md: the SELECTION bar). A lane owns its column
  (the effect column, or the volume column for `v`) on its channel and rows: a cell written there in `data` is an error,
  and so is a second lane there; the rest of those cells (note, instrument, the other column) is yours. The app draws a
  lane's cells dimmed and refuses an edit of its column; MAKE EDITABLE turns the lanes into plain cells (one undo step).
  The .it holds plain cells; nothing of the lane is stored. Added after 1.5.2: a song that uses lanes says so with
  `requires:`.

### 6.1 Cell

`note instrument volume effect`, e.g. `C#4 03 v48 H44`. The fields are recognised by their shape and
must stay in this order. Any field may be omitted, and `...` / `..` are placeholders:
`C-5 01`, `... .. v20`, `A08` and `C-5 01 ... G10` are all valid cells.

| field | syntax | meaning |
|---|---|---|
| note | `C-5`, `C#5`, … `B-9`, `C-0` | note name (sharps only, octave 0–9). `C-5` is IT note 60. |
| | `===` | note off: releases sustain loops and envelope sustain, then the fadeout starts |
| | `^^^` | note cut: silences at once |
| | `~~~` | note fade: starts the fadeout at once |
| instrument | `01`–`99` | two decimal digits; in instrument mode an instrument number, else a sample number |
| volume | letter + 2 decimal digits | volume column (6.2) |
| effect | letter `A`–`Z` + 2 **hex** digits | effect column (6.3) |

A note without an instrument keeps using the channel's last instrument. An instrument without a
note resets the volume to the sample's default. A note with an instrument and no volume command
plays at the sample's `volume`.

### 6.2 Volume column (values are decimal)

| cmd | range | meaning |
|---|---|---|
| `vNN` | 00–64 | set note volume |
| `pNN` | 00–64 | set pan (0 left, 32 centre, 64 right) |
| `aNN` | 00–09 | fine volume slide up by NN, once |
| `bNN` | 00–09 | fine volume slide down by NN, once |
| `cNN` | 00–09 | volume slide up by NN per tick |
| `dNN` | 00–09 | volume slide down by NN per tick |
| `eNN` | 00–09 | pitch slide down (like `E` with 4× the value) |
| `fNN` | 00–09 | pitch slide up (like `F` with 4× the value) |
| `gNN` | 00–09 | tone portamento with speed from a table: 0 = continue, 1, 4, 8, 16, 32, 64, 96, 128, 255 (shares memory with `G`) |
| `hNN` | 00–09 | vibrato with depth NN, using the last `H` speed |

For `a` to `f`, `00` repeats the previous value. The volume column and the effect column can be used in the same cell.

### 6.3 Effect column (Impulse Tracker semantics; parameters are hex `xx` or nibbles `xy`)

"Per tick" means on every tick except the first of the row. "Fine" means once, on the first tick.
`00` usually means "reuse this effect's last parameter" (effect memory).

| eff | name | parameter |
|---|---|---|
| `Axx` | set speed | ticks per row, 01–FF |
| `Bxx` | jump to order | order index xx (hex, 0-based). Use it on the last row to loop the song: `B01` restarts at the second order entry. |
| `Cxx` | pattern break | go to the next order and start at row xx (**hex**: `C10` = row 16) |
| `Dxy` | volume slide | `Dx0` up x per tick; `D0y` down y per tick; `DxF` fine up x; `DFy` fine down y; `D00` repeat. `D0F` and `DF0` are normal slides by 15. |
| `Exx` | pitch slide down | xx/16 semitone per tick; `EFx` fine by x/16 semitone; `EEx` extra fine by x/64 semitone |
| `Fxx` | pitch slide up | same as `E`, upward |
| `Gxx` | tone portamento | slide toward this cell's note at speed xx (same units as E/F). The note isn't retriggered. `G00` continues. |
| `Hxy` | vibrato | speed x, depth y |
| `Ixy` | tremor | sound on for x ticks, off for y ticks, repeating (0 counts as 1) |
| `Jxy` | arpeggio | cycles base note, +x, +y semitones every tick (`J47` = major chord, `J37` = minor chord) |
| `Kxy` | vibrato + volume slide | continues `H`, plus `Dxy` |
| `Lxy` | tone porta + volume slide | continues `G`, plus `Dxy` |
| `Mxx` | set channel volume | 00–40 (hex; 40 = full) |
| `Nxy` | channel volume slide | like `D`, on the channel volume |
| `Oxx` | sample offset | start the sample at xx × 256 frames (plus `SAx` × 65536) |
| `Pxy` | pan slide | `P0y` right y per tick; `Px0` left x per tick; `PFy` fine right; `PxF` fine left |
| `Qxy` | retrigger | retrigger every y ticks. Volume change per retrigger x: 0 none, 1 −1, 2 −2, 3 −4, 4 −8, 5 −16, 6 ×2/3, 7 ×1/2, 8 none, 9 +1, A +2, B +4, C +8, D +16, E ×3/2, F ×2 |
| `Rxy` | tremolo | speed x, depth y (volume oscillation) |
| `Sxy` | special | see below |
| `Txx` | tempo | `T20`–`TFF` set tempo 32–255; `T0x` slide down x per tick; `T1x` slide up |
| `Uxy` | fine vibrato | like `H` with 4× finer depth |
| `Vxx` | set global volume | 00–80 (hex; 80 = full) |
| `Wxy` | global volume slide | like `D`, on the global volume |
| `Xxx` | set pan | 00 left, 80 centre, FF right |
| `Yxy` | panbrello | speed x, depth y (pan oscillation) |
| `Zxx` | MIDI macro / filter | `Z00`–`Z7F` sets the resonant filter cutoff; `Z80`–`Z8F` sets resonance. These are the default macros. |

`Sxy` subcommands:

| cmd | meaning |
|---|---|
| `S1x` | glissando for `G`: 1 slides in semitone steps, 0 slides smoothly |
| `S3x` | vibrato waveform: 0 sine, 1 ramp down, 2 square, 3 random |
| `S4x` | tremolo waveform (same values) |
| `S5x` | panbrello waveform (same values) |
| `S6x` | extend this row by x ticks |
| `S70` `S71` `S72` | cut / note-off / fade this channel's background (NNA) voices |
| `S73` `S74` `S75` `S76` | set this note's NNA to cut / continue / off / fade |
| `S77` `S78` | volume envelope off / on |
| `S79` `S7A` | panning envelope off / on |
| `S7B` `S7C` | pitch envelope off / on |
| `S8x` | set pan coarsely (0 left … F right) |
| `S91` | surround on (`S90` off) |
| `SAx` | high byte of the sample offset for the next `O` |
| `SB0` | set the loop start (this row); `SBx` loops back to it x times |
| `SCx` | cut the note after x ticks |
| `SDx` | delay the note by x ticks |
| `SEx` | repeat this row x extra times (pattern delay) |
| `SFx` | select the parameterised MIDI macro (`SF0` = filter cutoff, the default) |

Values these tables leave out (`S0x`, `S2x`, `S7D`, `S7E`, `S92`–`S9F`, `Z90`–`ZFF`) compile into the .it unchanged;
libopenmpt plays them as OpenMPT does (most are OpenMPT extensions, or do nothing in Impulse Tracker).

## 7. `orders`

```yaml
orders: [intro, a, b, a, +++, c]
```

Pattern names in play order. `+++` is a skip marker and `---` ends the song. At most 255 entries. Without
a `Bxx` jump, the song loops back to the first order after the last one. Patterns that are defined
but not in the list produce a warning.

### Named arrangement sections

```yaml
sections:
  Intro: [0, 2]       # orders 0 and 1
  Verse: [2, 6]       # orders 2 through 5
```

Names are non-empty strings up to 80 characters. Each value is `[first, exclusive_end]` with
`0 <= first < exclusive_end <= len(orders)`. Spans cannot overlap and count raw order-list entries, including markers.
Sections do not add IT commands or change playback; old songs need no new keys. The SONG tab edits these annotations
with the order list, retargets `Bxx` destinations by occurrence, and can clone patterns for independent section copies.
A duplicate that reuses pattern names shares future cell edits. MAKE THIS OCCURRENCE UNIQUE creates a new pattern name
for just one order. Phrase tryouts are project sidecar data; accepting a phrase writes ordinary cells, not macro commands.

## 8. Idioms

- **Drum kit:** one instrument, keymap entries with `play_note: C-5`, and a separate channel for
  each drum that can sound at the same time (kick, snare, hats).
- **Chords:** one channel per chord voice, or `Jxy` arpeggio on one channel for the chiptune-style effect.
- **Pads that overlap:** `nna: fade` (or `off`) with a small `fadeout` (10–40). New notes on the
  same channel then crossfade instead of cutting.
- **Echo:** copy the lead line to a second channel 2–3 rows later, at a lower volume and panned to the other side.
- **Accents:** shape drums and hats with the volume column (`v64` on the downbeat, `v20` on ghost notes).
- **Loop point:** end the last pattern with `Bxx` to skip an intro when the song repeats.
- **Releases:** end sustained notes with `===` so their envelope release and fadeout run. `^^^` is an abrupt stop.
- **Fills:** `Qxy` on a snare for rolls, and `SDx` for flams or swing.

## 9. Limits and validation

At most 64 channels, 99 samples, 99 instruments, 200 rows per pattern, 254 patterns (indexes 254/255 are skip/end markers), 255 orders and 25 envelope nodes.
`check` reports all errors at once as `file:line: error: ...`, plus warnings (unused patterns,
notes that map to no sample, samples played so far below their stored rate that interpolation images reach
the audible band, drums whose ring tones clash with the key). The ring-tone warning measures each sample the
patterns play at one note only (a drum, a one-shot): its steady partials (spectral peaks that stand 15 dB over the
bins around them through most of the sound past its attack, within 20 dB of its loudest band, so broadband noise has
none), from 50 Hz to 5 kHz as they sound at that note. When one sits more than 30 cents from every tone of the song's
key it names the loudest such partial in Hz, its nearest note and cents off, and its level under the sample's loudest
band. The key is `module: key`, else the key estimated from the notes (the SONG tab's estimate) when its correlation
r reaches 0.7; the warning says which. A song with neither gets no such warning. The key's tones are equal-tempered
at A = 440 Hz: slides, arpeggios, pitch envelopes, an instrument's tuning and pitched samples tuned off that grid
(`c5_speed`) are not followed. Common mistakes it catches:
- lower-case notes, flats, or `C5` instead of `C-5`
- effect letters that are digits (MOD/XM style `A08` is fine; `008` is not)
- lower-case effect letters
- volume values out of range or single-digit (`v8`)
- instruments that aren't defined
- `Bxx` beyond the order list
- misnumbered row labels
- patterns with too many rows or cells

## 10. Native score (in development)

The optional root `score` mapping preserves notation alongside residual tracker commands. `version: 1` has
`tracks`, `patterns`, `order_ids`, and optional `ties`, `measures` and `metadata`. Songs without it compile as before.
`metadata` holds optional text fields `title`, `artist`, `album`, `author`, `date`, `copyright`, `writer`,
`transcriber` (up to200 characters each), and `comments` (up to8000); NUL is rejected. This is saved notation
and credit information, separate from the short IT `module.title` and `module.message`. It does not change
playback. TG and supported GP credit fields round-trip; unsupported output fields are reported.
Native playback pairs the residual tracker module with an exact score-event schedule; score notes are never
duplicated into saved `patterns.data`. Conflicting raw fields are an error. Unrelated raw effects remain in `patterns`.
The standalone IT compiler retains its strict row projection and refuses unrepresentable score timing.

```yaml
score:
  version: 1
  tracks:
    guitar: {tuning: [64, 59, 55, 50, 45, 40], channels: [0, 1, 2, 3, 4, 5], capo: 0, instrument: 1}
  order_ids: [verse-first]    # one unique identity per order occurrence
  patterns:
    verse:
      row_step: [1, 4]      # quarter notes per row: module.speed / 24
      beats:
        - id: opening
          track: guitar
          voice: 0         # 0 or 1
          at: [0, 1]       # exact quarter-note numerator/denominator
          written: {value: 4, dots: 0, tuplet: [1, 1]}
          notes: [{id: high-e, pitch: 64, string: 1, fret: 0}]
  ties: []
  measures: []
```

This fragment requires a `verse` pattern, six module channels, instrument/sample 1, and enough rows for its release.
Pitches use the compiler's 0–119 numbering. Strings are one-based; channels are zero-based. Track tuning is ordered
top string first, with 1–25 strings, signed `capo` offsets from -24 through 24, and optional `max_fret` (default 29,
range 0–36) and `name`. Optional notation fields are `color: '#rrggbb'`, `clef` (treble, bass, alto, tenor or percussion),
`key: {fifths: -7..7, mode: major|minor}` and `stem` (auto, up or down). A beat's `stem` overrides its track default.
These fields do not transpose or retune playback. Optional `midi: {program: 0..127, bank: 0..16383}`
records a file-interchange sound assignment; `program` is required when the mapping exists and omitted `bank`
means zero. It does not change the native sample instrument. Each channel belongs to at most one score track. Notes optionally override `instrument`,
`volume`, `spelling` and zero-based `channel`; the channel override preserves existing Pattern routing when its
fingering moves to another string. Instrument zero on adopted notes retains tracker instrument inheritance.
An unplayable pitch has null `string`/`fret`. An empty notes list is a written rest. Beat and note IDs are unique
within a pattern and survive edits. Explicit adoption of a raw note uses `duration_source: tracker_boundary`
on its beat to identify inferred written duration; adoption must preserve playback semantics.

Bank 128 identifies a percussion track independently of its displayed clef. It requires 1–25 zero-tuned
lanes and capo zero. Its note `pitch` and `fret` both hold the authored drum key, 1–100; `string` remains the
stable one-based lane. `max_fret` retains its metadata range but does not limit drum keys. Pitch edits preserve
the lane, and the chosen native instrument may map different keys to distinct samples at the same playback
pitch. That sample mapping does not change the authored drum key. Plain notes, rests, both voices, velocities,
ties, repeats and lyrics share the existing score model. Ghost, accent, heavy accent, staccato, dead and palm
mute use the qualified shared velocity/gate rules. Drum let-ring uses the existing voice/lane-aware sustain scan
and independent held identities, including across supported ties/repeats; it cannot combine with staccato or
palm mute. Other drum techniques and populated pitched/drum conversion
refuse explicitly. Clipboard `track_kinds` prevents interpreting guitar frets as drum keys.
Strict native TG import supports keys 1–100; GP3–5 supports 1–99 because TuxGuitar normalizes GP key 100 to zero.
TG preserves these techniques including let-ring. Native GP3 import retains ghost/dead/let-ring, GP4 adds accent/staccato/
palm mute, and GP5 adds heavy accent. Unsupported version flags and conflicting dynamics refuse before
publication; absent GP velocity becomes the source default 95, never the performed accent/ghost value.
GP4/5 let-ring combined with palm mute or staccato follows the installed reader's normalization with an
explicit notice; unsupported dynamic combinations and gapped ties still refuse.
For neutral 0/major key,
TG export maps the native percussion clef alias to stored treble with an explicit warning; bank 128 still selects
the neutral drum glyph on reimport. Non-neutral-key alias conversion refuses.
Native MIDI export preserves drum keys on MIDI channel 10 (zero-based channel 9). Participating drum parents
must share fixed program, volume, pan and expression. Overlapping gates on the same drum key, changing parent
controls, pitch/fade techniques and raw drum attacks refuse before publication; different keys may overlap.

Optional track `lyrics: {from_measure: 1, text: "raw lyric stream"}` stores one stream starting at a
one-based authored measure number. Both keys are required: `from_measure` is an exact integer from 1 through
2147483647, and `text` is a string of at most 65536 characters. Spaces, tabs, CR/LF line endings and punctuation
are stored exactly. Empty text retains the starting measure; omit `lyrics` to remove it (`null` is invalid).
The agent's existing `track_set` replaces the complete track, so unrelated edits must retain this field.
Lyrics share the song's save and undo history and do not change notes, gates, samples or playback timing.

Placement uses the complete written arrangement and requires authored measures covering it without gaps.
Absent or incomplete measures produce a lyric-placement diagnostic; the raw stream and playback remain available.
CR and LF each become one space for placement only; tokens split on literal spaces, retaining internal empty
slots and discarding trailing empty slots. Tabs and nonbreaking spaces remain inside a token. One token attaches
to each non-rest onset on that track: voice 0 takes precedence when both voices sound together, and a chord
consumes one token. Tied continuations count; grace and repeated technique attacks add no slots. Playback repeats
do not consume the stream again. Start measures past the arrangement and excess text stay stored without anchors.
Structural edits retain the raw starting number and text; they do not rewrite either to follow moved bars.
Native TG interchange retains the stream and starting measure. GP4/5 import accepts the first lyric line and
refuses additional nonempty lines. Native MIDI export reports lyrics and starting measures as omitted; standalone
IT conversion reports an explicit notation-loss warning for nonempty lyrics. Neither export nor native playback
synthesizes vocals. Chord diagrams likewise produce a notation-loss warning in IT; diagrams never generate notes,
and any existing chord notes remain unchanged. Both annotations stay in the source and engraving.

Imported MIDI pan may retain `midi.source_pan: {value: 0..127, mixer_pan: 0..64}` (exact integers).
`value` is the source CC10; `mixer_pan` is its original VT channel-pan value. The audio mixer keeps its existing
0..64 scale. Native MIDI preserves the exact source value only while all track channels match that anchor and
no current pan override targets the track. Even an explicit override equal to the saved pan disables the binding;
volume and mute changes do not. WRITE MIX clears it atomically with any pan write on the track, and undo restores
both. Raw Pattern X commands override the initial value, including commands before an exported range. Channel
reassignment clears the binding; unrelated track name/program/bank edits retain it. Removing the whole `midi`
mapping also removes it. A manually changed channel pan that differs from the anchor uses the ordinary mixer
conversion. Native GP import preserves TuxGuitar's exact `max(8*balance_byte-1, 0)` values. Native TG retains the
all 0..127 source values, including neutral 64 and source-center 63 distinctly.
Volume has the parallel binding `midi.source_volume: {value: 0..127, mixer_volume: 0..64}` for CC7.
PTB and TEF imports use the same bindings after TuxGuitar's source-controller conversion; no separate import mix is saved.
It follows the same anchor, explicit override, channel reassignment and Undo rules; raw Pattern M commands
override it. Pan-only edits retain volume and volume-only edits retain pan. GP1–5 source volume is retained;
TG import maps each controller to the nearest native 0..64 mixer value and reports that audio quantization.
TG export accepts uniform volume/pan across each part's strings. GP3–5 additionally require native mixer
steps divisible by four and exact GP source bindings (`max(step*8-1,0)`); incompatible values refuse.
Unequal string mixes, string mute, non-neutral global mix, source effects and shared TG MIDI channels still
refuse. These bounds preserve musical intent; source-controller retention does not reproduce a synth timbre.

Optional note booleans `tapping`, `slapping` and `popping` are a mutually exclusive notation group, separate
from the tapped harmonic subtype. Enabling one through `note_set` clears the other two; setting one false
clears only itself. Multiple true flags in one edit or native YAML refuse. Other techniques remain unchanged.
Each flag stays on its authored note, including a tied continuation. They do not change the native event
schedule, audio backing or MIDI messages, matching the inspected and measured TuxGuitar parser paths. Uniform
voice-beats use the renderer's T/S/P glyph; sparse or mixed chords use string-qualified text so a marking is
not incorrectly applied to every string. Standalone IT conversion preserves the native sound and emits an
explicit notation-loss warning: IT cannot retain these semantic markings. The source score/history remains
unchanged; cleared/false flags emit no warning. Existing timing, instrument and cell-ownership limits still apply. Native
TG preserves per-note flags; conflicting source tags follow TG's tap, slap, pop setter order with a warning.
GP3/4/5 import expands its single voice-beat technique onto that record's notes; flagged rests/empty beats
refuse because they have no note recipients. No mixed-note GP export is implied.

Optional note booleans `staccato`, `palm_mute` and `dead` shorten the performed gate without changing written
duration, fingering, instrument or volume. The initiating note controls a tied chain; continuation flags remain
authored but do not independently shorten it. Dead takes precedence over palm mute, then staccato. Enabling
staccato through `note_set` clears palm mute and let-ring; each of those three clears the other two. Gate lengths follow TuxGuitar 2.1.0's truncated
960-tick quarter units: half the expanded duration for staccato, or the smaller of that duration and
`floor(tempo * 30 / 60)` ticks for dead / `tempo` ticks for palm mute. Tie expansion includes differences between
rounded absolute beat starts. Playback SPEED scales time after this calculation. These gates send note-off;
sample and instrument release tails still play. Pattern displays a generated release where it aligns to a row;
editing that release requires the score duration/technique control. Standalone IT conversion of these techniques
currently refuses explicitly.

Optional boolean `let_ring` extends performed duration using TuxGuitar 2.1.0's ordered same-voice scan,
without changing written duration or requiring velocity. Empty voices are skipped and explicit rests stop the
scan. While ringing, the first unmarked following note adds that beat's written duration and stops, before
checking its string; a marked replacement on the same string stops without adding it. Marked tied continuations
can enable ringing on an initially unmarked head. Chord order matters. Gaps alone do not extend the release:
a ringing quarter at 0 followed by an unmarked quarter at 3 releases at 2, not 3 or 4. The initiating head's
shortening gate applies after this scan; curves, harmonic layers and repetition use the resulting duration.
Written positions retain `end`, with `sounding_end` reporting the performed release separately. Ordinary
single-pitch notes may overlap a ringing note on the same channel: the earlier voice keeps its identity,
phase and release through the later attack. Harmonics, repeated attacks and grace/main pairs use independent
head contexts when their performed gates overlap. Every played attack on an affected parent must use an explicit
instrument, and all its backing cells must be empty or global T/V commands. Contexts retain same-head NNA/DCT;
other heads do not cut them. Envelope carry, random volume/pan and mapped random auto-vibrato refuse. The
runtime admits at most 64 active heads and 64 attack groups per frame; exhaustion refuses atomically. Written
voice overlap and raw local conflicts still refuse; the planner never clips a ring to hide a collision.
With repeats, crossing a measure boundary retains the initiating source measure's close flag, including its
final pass. Conflicting let-ring/palm-mute/staccato flags in native YAML refuse.

Optional `grace` is null or `{fret, value: 16|32|64, velocity: 0..127, transition: none|slide|bend|hammer,
on_beat: false, dead: false}`. Fret, value and velocity are required; the other fields default as shown.
The grace has independent velocity on the same string; authored tracker volume applies to both attacks.
On-beat grace delays the main attack by its duration while retaining the main release. Before-beat grace
precedes the written onset, falling back to on-beat when there is insufficient time since song start.
Dead grace shortens only its own gate. Transition labels affect notation only. Written anchors and ties
remain unchanged; positions expose `sounding_start`, `sounding_start_frame`, `grace_start` and `grace_end`.
The main tie head owns grace; continuation grace does not create an attack. Explicit source instrument is
required. A before-beat grace may overlap the preceding head in the qualified independent-context domain above.
Exhausted main duration, raw local conflicts, and slide controls
before the delayed main attack refuse. Standalone IT projection cannot preserve grace and refuses.

Optional note `velocity` is an authored MIDI integer 0..127, separate from nullable tracker `volume`.
Omission leaves inherited instrument/sample gain unchanged. An explicit value uses a linear `velocity / 127`
native voice gain; MIDI synthesizers can have other response curves. `note_set` with `velocity: null` removes
the authored override. Positive authored values survive MIDI export exactly, with sample/instrument gain carried
by rounded expression controllers. MIDI export refuses zero-velocity gates because MIDI interprets them as note-off.
Standalone IT projection refuses authored velocity rather than quantizing it into the 0..64 volume column.
Optional note booleans `ghost`, `accent`, `heavy_accent` and `hammer` preserve the written technique separately
from authored velocity. Playback subtracts 25 (floor 15) when the nearest preceding written note in the same
track/voice/string has hammer, then applies ghost -16, accent +16 or heavy accent +32 (in that precedence order,
floor 15, ceiling 127). The intermediate clamp matters. The predecessor search crosses rests and includes tied
continuations; continuations do not create new attacks. A modified attack requires explicit authored velocity;
missing velocity or ambiguous string/raw-note ownership refuses rather than guessing. Explicit zero can become
audible under these source-derived formulas. Enabling one accent flag clears the other two; hammer excludes
bend/bar/slide/dead and those techniques clear hammer. This changes the following attack's dynamics, without
suppressing its attack. MIDI exports performed velocity; the authored value remains unchanged in the score.

Optional `vibrato` is boolean. `bend` and `tremolo_bar` are null or
`{points: [{position: 0, value: 0}, {position: 6, value: 4}, {position: 12, value: 0}]}`.
Positions are integers 0..12 in nondecreasing order (coincident points are retained); values are 0..12 for bend
and -12..12 for tremolo bar, with at most 129 points. The initiating tied note owns its pitch curve. Bend takes
precedence over tremolo bar, then vibrato. The note editor clears competing bend/bar/dead flags when enabling
one; vibrato may remain authored alongside a curve. Pitch controls use TuxGuitar 2.1.0's integer interpolation
and 960-tick durations, including gate shortening, while native note onsets retain exact authored fractions.
The native receiver establishes a 12-semitone pitch-wheel range: a 7-bit controller step above neutral 64 is
3/16 semitone. This is an explicit receiver choice; external TuxGuitar synthesizer configuration can differ.
Controls address the original voice identity, including its live release tail, and never a replacement note.
MIDI export routes pitch-controlled notes and harmonic layers to independent melodic channels, keeping ownership
through the final in-range control. It sets a 12-semitone pitch-bend range and reports 14-bit wheel rounding.
Channel exhaustion and unsupported percussion/program ownership refuse before publication. IT export still refuses.

Optional note `harmonic: {type: natural|artificial|tapped|pinch|semi, data: 0..5}` retains harmonic notation;
omitted `data` means zero. Non-natural types index TuxGuitar's touch/interval table: 12/+12, 9/+28, 5/+24,
7/+19, 4/+28, 3/+31. Natural harmonics match the written fret modulo 12 against that table; unmatched frets
retain their primary pitch. Playback uses separate ordered layers under one logical attack, sharing its gate
and pitch controls. Semi adds the original pitch at performed velocity minus 48 (minimum 15); all types add
a lower octave when its pitch is positive, at velocity minus 64 (minimum 15), then the primary at performed
velocity. Explicit authored velocity is required; output pitches above the native engine's 119 limit refuse.
The initiating note owns harmonic layers across a tie. The grouped native runtime is required; MIDI export
assigns their independent melodic channels, refusing capacity or routing conflicts. `note_set` with `harmonic: null` clears it.
GP5 export stores tapped data0..5 as the written fret plus the touch interval, and natural/artificial/pinch/semi
data0 as the corresponding GP5 type. Nonzero data on those other types cannot survive GP5 and still refuses;
GP4 additionally preserves tapped/pinch/semi data0 and artificial data0/2/3 using their exact reader codes;
GP3 keeps natural/artificial data0 only. These format limits do not constrain native editing.

Optional note `trill: {fret: 7, value: 16}` alternates the written pitch with an absolute fret on the same resolved
string. Rates are 4, 8, 16, 32 or 64. `tremolo_picking: {value: 16}` repeats the written pitch at rate 8, 16 or 32.
Both require explicit velocity and retain one written note; generated attacks have separate playback identities
and a logical `source_id`. The tie head owns the effect and performed velocity through its continuations.
Repetition overrides harmonic playback, while preserving harmonic notation. Authoring either effect clears
bend, tremolo bar, slide, hammer, dead, vibrato and the other repetition effect; setting a conflicting technique
clears repetition. Invalid combinations in YAML refuse. Null clears either field through `note_set`.

Pulse timing follows TuxGuitar's 960-tick duration offsets from the exact native onset. Tied duration uses the
difference of truncated start ticks plus the final written duration, retaining compensating ticks across tuplets.
Gate effects shorten the whole chain before repetition. Full pulses touch at their release/next attack; the final
clipped pulse ends one tick early, and a remaining span of at most ten ticks produces no pulse. Tempo changes
do not restart the sequence. Native onsets remain rational rather than being rounded to TuxGuitar's tick grid.
`slide: true` selects the next authored beat in the same track/voice and its note on the same resolved string;
a rest or a chord without that string stops the lookup. It retains both attacks and uses TG's integer tick stride
and float32 pitch steps, with bend/bar taking precedence and slide suppressing vibrato. A slide may control its
original voice after its gate release; its final reset never retunes the next attack. Enabling slide clears bend,
tremolo bar and dead, and enabling any of those clears slide.

Written values are 1, 2, 4, 8, 16, 32 or 64, with zero, one or two dots. `tuplet: [3, 2]` means three notes in the
time of two. Exact source fractions are retained and native playback rounds each absolute boundary once to the
nearest sample frame, half up. A tie is `{from: {occurrence: verse-first, note: high-e}, to: {occurrence: next, note: next-e}}`.
A measure is `{id, from: {occurrence, at}, to: {occurrence, at}, meter: [numerator, denominator]}`; its exact bounds
and meter must agree. Repeated patterns share their notes, while occurrence IDs distinguish their order entries.
Optional measure `swing: none|eighth|sixteenth` changes performed timing of qualifying ordinary eighths or
sixteenths, while written positions stay unchanged. It follows TuxGuitar's source-measure/voice neighbor checks
on floored 960-tick quarters: an eighth pair becomes 640/320 ticks, a sixteenth pair 320/160. Dotted and tupleted
durations do not qualify. Exact authored onsets retain their fractional part; only the measured swing offset is
added. Swing precedes tie/let-ring extension, gates, grace and repetition. A first swung eighth tied to the next
lasts 1120 ticks. Beats crossing swing measure boundaries require splitting with an explicit tie. Ambiguous
source inheritance, raw local conflicts and unsupported performed overlaps refuse. This is a note transform,
so tempo commands and raw tracker rows keep their original times.

Optional beat `stroke: {direction: up|down, value: 4|8|16|32|64}` spreads its untied string attacks;
`pick_stroke: up|down` is a notation mark only. Null clears either field. Both belong to the shared track/onset
across its two voices. Optional beat `cohort: 0..127` distinguishes separate TG beat groups at the same
track/onset; absent means 0. The number is local to that pattern/track/onset and records stable group order.
Free edits assign it only when previously separate groups coincide; save/history and TG interchange preserve
the distinction. Sparse metadata is resolved without changing the source; conflicting non-null values
refuse, and a beat edit applies or clears the value across that cohort. Stroke uses the shortest written voice
duration, including an explicit rest, capped at one quarter. At 960 ticks per quarter its per-string increment
is that duration divided by twice `value`, rounded half up. Up visits increasing string numbers, down decreasing;
absent strings and tied continuations consume no step. Written anchors remain unchanged. Delay shifts the
performed attack and subtracts from the gate only when the gate is longer than the delay; a short gate retains
its duration. Stroke follows swing/gates and precedes grace, repetition and harmonic playback. Source ordering,
raw-conflict and shared-channel overlap guards still apply. Strict IT projection refuses performed stroke.

Optional note `fade_in: boolean` preserves an independent marking, including on tied continuations; omission
means false. Native live/audio and MIDI export share TuxGuitar's mixer-mode expression schedule; this intentionally
makes the marking audible beyond TuxGuitar's default live parser. An untied marked head starts a track-wide staircase after
stroke/gate timing and before grace timing. For gate duration D in 960-per-quarter ticks, values 31..126 occur
at S + i*floor(D/96), i=0..95, followed by 127 at S+D. A positive D below 96 keeps all 96 controls at S.
Tied continuation flags create no extra ramp; repeated heads create their own ramps. All strings, voices and
layers of the logical score track share the ordered expression stream, including unmarked notes.

MIDI composes this logical value with the existing static expression using round-half-up(base*value/127),
without rewriting authored velocity. New channels inherit preceding expression and apply ordered same-time
controls before their attack; a reused channel follows its new track. Existing release-before-attack ordering
remains. Source ramp ordering is retained, but physical controller values with non-neutral gain are a volume
conversion, not a claim of identical synthesizer response. Controllers are routed while a channel owns its gate
or pitch controls; unmeasured release tails are omitted. MIDI refuses more than 200000 logical or routed fade
events before publication. Native audio composes expression with each owned note/layer's original gain, including
released tails; raw attacks without score identities on an affected track refuse. Strict standalone IT projects
volume-column controls to the nearest row (at most half a row), retaining authored velocity/sample volume and
requiring a maximum normalized gain-trajectory error of 6.25 percentage points. CLI and UI report the measured
bound; this is not an instantaneous waveform bound. Unsafe inherited state, volume/effect collisions, delayed
SDx expression rows, off-row affected attacks and inadequately represented final tails refuse before writing.
Native TG preserves per-note flags; GP3–5
import copies each serialized voice-beat flag to its notes and refuses flagged rests or unsupported shared routing.

Optional beat `chord: {name, first_fret, frets}` is a shared onset/track annotation; null clears the cohort and
omission preserves it. `name` is at most 4096 characters and may be empty. `frets` has one integer per track string,
string 1 first: -1 muted, 0 open, positive absolute fret up to `max_fret`. `first_fret` is 0..max_fret; 0 preserves
automatic placement, resolved for display to the lowest positive fret or 1. Positive frets must fit the five-fret
window starting there. Validation never clips or reverses them. An all-muted array is a literal diagram, not a
portable symbol-only mode. Sparse voice metadata inherits the same diagram; conflicting non-null values refuse.
The diagram need not match played notes and does not alter audio or MIDI. Strict IT projection refuses it.
Whole-beat copy preserves it, note-only clipboard does not. Moving the unique sounding voice transfers it;
another sounding voice keeps it at the source, and conflicting destinations refuse. Final sounding-note removal
clears the source diagram; attaching one explicitly to a rest is allowed. Splits do not repeat it on tie continuations,
and transposing notes does not rewrite its frets. Native TG retains it; GP import refuses richer unsupported chord
fields and representations that would discard a name or fret.

The separate `chord_notes` edit applies a complete diagram and replaces the selected voice's notes in one
transaction. It uses fresh IDs, `tuning[string-1] + capo + fret`, chosen velocity (default 95), and the track
instrument; old per-note effects and overrides are not inherited. The selected beat's onset, duration and shared
fields remain. Played strings also replace same-onset other-voice notes on those strings. Muted strings leave
that other voice alone. Incident ties across all pattern uses refuse unless `remove_ties: true` explicitly
removes them. Reused patterns remain shared. All-muted clears the selected voice and attaches the diagram when
either voice originally sounded; when the whole beat was already a rest it makes no change. This command does
not generate a voicing from a chord name: its input is the literal fret array.

Measures accept `double_bar: boolean` for an ending double barline (display only, no repeat or timing change).
It survives native editing and GP3/4/5 export; TG export refuses because TG has no corresponding field.
Per-track `staff` key/clef changes remain effective through following measures until changed again.
Measures also accept `repeat_open: boolean`, `repeat_close: 0..100` (extra passes), and `endings: [1..8]`
(unique pass numbers). The native controller follows TuxGuitar's single repeat-start register and inherited
ending mask, including multi-measure endings; it is not a nested repeat stack. Authored orders, occurrence IDs,
patterns and print remain unchanged. A disposable performed visit list drives both backing rows and score events,
restoring each source entry's effective tempo. Source swing phase is retained; ties and let-ring resolve along
each played path. Unmatched tie continuations refuse. The current implementation requires explicit measures
covering the entire arrangement with boundaries aligned to tracker rows, at most 255 played fragments and
254 backing patterns. Measures may split a pattern or span adjacent patterns. A sounding gate can cross a
fragment boundary without another attack; a written beat crossing a measure boundary must be split and tied.
Tempo restoration needs a free entry-row effect slot if no T command already exists. Fractional-row boundaries
and capacity overflow refuse without truncation. Standalone IT export
still refuses repeats. Selecting source bars for a loop or export includes their played visits only when those
visits form a continuous span; disjoint or unreachable selections refuse. Listening notes retain the played
pass, fragment and local row alongside their original authored order and row.

An optional measure `marker: {title: Verse, color: '#ff4040'}` is anchored to its start; title is 1..4096 characters
and color is optional. An optional beat `text` is plain text of at most 4096 characters, anchored to its onset,
including on rests. These annotations never change playback. Beat copy/move preserves text, and split continuations
do not repeat it. MIDI retains marker titles and beat text at exact anchors, with named text tracks; marker color,
voice and engraving placement are explicit conversion losses.

Native playback requires constant tracker speed and `row_step == module.speed / 24`. Different written voices
of one track can share a parent channel during overlapping notes. Each head keeps its own source identity,
gate and playback context; every head on that parent needs an explicit resolved instrument. Envelope carry,
random source settings and raw backing other than empty/T/V cells remain unsupported on those parents.
Same-voice overlapping beats remain invalid, and standalone IT projection refuses overlapping ownership.
Pattern collisions expose every owner separately; bare cell edits refuse, source-ID edits affect one note,
and explicit all-head ranges affect all selected voices. Occurrence-qualified ties retain their own release boundaries. The strict IT projection
also requires identical generated cells in every occurrence of a reused pattern. Native backing supports raw
X00..FF pan, D00..FF volume slide, M00..40 channel volume, V00..80 global volume and v00..64 volume columns.
Absolute T20..FF commands produce one resolved tempo map across pattern occurrences. Their row boundaries, score
attacks, pitch controls, seek positions and rendered lengths use the same piecewise quarter-to-second clock,
rounded only at absolute frame boundaries. Multiple T commands on one row refuse; T00..1F slides/recall and speed
or flow changes remain unsupported. Palm/dead gates use the attack tempo in musical ticks, then map their endpoints;
a raw volume cannot override a score-owned attack volume. Unsupported raw effects, flow
commands, cross-boundary operations and unrepresentable written durations fail before persistence. Full rhythm, technique and interchange parity
remains in development; these limits are not silent rounding or permission to discard notation.

## 11. Compatibility

The format has no version number: it grows only by new optional keys, and a key keeps its meaning.

- **The promise.** VultureTracker 1.x opens every song that 0.6 or later wrote, without changing it, and compiles it to
  the same module. The tests hold the demos whose samples are all in git to the exact `.it` bytes they compile to
  (`tests/test_release100.py`); a change of meaning would be a 2.0.
- **A newer song in an older app.** A key added after an app was made is an "unknown key" error there. A song that uses
  one can say so: `requires: "1.2"` at the top level, and an app older than 1.2 then reports that one thing ("this song
  needs VultureTracker 1.2 or newer; this is 1.1.0") instead of the keys it does not know. Quote the version: YAML reads
  a bare `1.10` as the number 1.1. The app's own edits keep the key.
- **Which version wrote it.** A song the app creates or imports starts with a comment `# written by VultureTracker
  X.Y.Z` among its leading comments; `check --json` reports it as `written_by` (null without one). An app write brings
  the line to its own version only when it names another, and never adds one to a song without it, so a committed
  song's diff stays the edit. It is a comment: nothing reads it to decide what a key means.
- **The files beside the song** (`<song>.tryout.json`, `.notes.json` and the notes archives, `.history.json`, and a
  collected project's `project.json`) carry a `schema` number. An app reads its own and older ones and writes its own;
  one written by a newer app opens the song read-only, with a notice naming the file, and nothing is written over it.
