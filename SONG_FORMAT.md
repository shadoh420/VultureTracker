# VultureTracker song format (v1)

A song is one YAML file that compiles to an Impulse Tracker module (`.it`, instrument mode). This
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

Unknown keys anywhere are errors, so typos are caught. Numbers are decimal unless stated otherwise
(effect parameters are hex). Gaps in sample and instrument numbering are allowed: missing slots are empty.

YAML notes: quote text containing `: ` or starting with `[`, `{`, `#`, `&`, `*`, `!`, `|`, `>`, `%`, `@`.
Bare `off`, `on`, `yes`, `no` are fine for the enum fields below. Give patterns names that start with
a letter.

## 3. `module`

| key | range | default | meaning |
|---|---|---|---|
| `title` | ≤25 ASCII chars | `""` | song title |
| `tempo` | 32–255 | 125 | initial tempo (IT "T") |
| `speed` | 1–255 | 6 | initial ticks per row (IT "A") |
| `global_volume` | 0–128 | 128 | initial global volume (the `V` effect changes it) |
| `mix_volume` | 0–128 | 48 | output gain. Raise it if the render is quiet, lower it if it clips. |
| `separation` | 0–128 | 128 | stereo separation |
| `linear_slides` | bool | true | linear pitch slides (keep true) |
| `old_effects` | bool | false | IT "old effects" mode (keep false) |
| `compatible_gxx` | bool | false | IT "compatible Gxx" mode (keep false) |
| `channels` | 1–64, or list | required | channel count, or one entry per channel |
| `message` | text | none | song message stored in the file |

Channel entry: `{name: Bass, pan: 32, volume: 64, muted: false}`

| key | range | default | meaning |
|---|---|---|---|
| `name` | ≤20 chars | `""` | label for humans (not stored in the .it) |
| `pan` | 0–64 or `surround` | 32 | initial pan: 0 = hard left, 32 = centre, 64 = hard right |
| `volume` | 0–64 | 64 | initial channel volume (the `M` effect changes it) |
| `muted` | bool | false | channel starts muted |

**Timing.** A tick lasts `2.5 / tempo` seconds. A row lasts `speed` ticks. With speed 6 and 4 rows
per beat, BPM = tempo. In general `BPM = tempo × 24 / (speed × rows_per_beat)`. Envelopes and
most effects run per tick.

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
| `file` | path | required* | WAV file: PCM 8/16/24/32-bit or float, any rate, mono or stereo. *A slot with only `name` (no `file`) is an empty sample slot. |
| `name` | ≤25 chars | file stem | sample name; instruments may refer to a sample by this name |
| `base_note` | note | `C-5` | the note at which the WAV plays at its recorded pitch |
| `c5_speed` | 256–9999999 | from WAV | playback rate for C-5, in Hz. Use instead of `base_note` for fine tuning. |
| `volume` | 0–64 | 64 | default note volume (used when a cell has no volume command) |
| `global_volume` | 0–64 | 64 | fixed scaling of this sample |
| `pan` | 0–64 | none | if set, notes using this sample start at this pan |
| `loop` | see below | none | normal loop, active the whole time |
| `sustain_loop` | see below | none | loop active only until note-off (`===`), then playback continues past it |
| `vibrato` | see below | none | automatic vibrato applied to every note |
| `bits` | 8 or 16 | from WAV | storage depth (8-bit sources stay 8-bit; others become 16-bit) |
| `stereo` | bool | false | keep a stereo WAV as a stereo sample (libopenmpt/OpenMPT only; Impulse Tracker itself has no stereo). If false, stereo is mixed to mono. |

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
| `name` | ≤25 chars | `""` | instrument name |
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
| `volume_envelope` | envelope | none | values 0–64 |
| `panning_envelope` | envelope | none | values -32 (left) to 32 (right), added to the channel pan |
| `pitch_envelope` | envelope | none | values -32–32 in half-semitones (-2 = one semitone down). Add `filter: true` to make it a filter-cutoff envelope instead. |

Keymap entry: `{notes: <note or range>, sample: <number or name>, transpose: <semitones>}` or
`{..., play_note: <note>}`.
- `notes`: one note (`C-5`) or an inclusive range (`C-0..B-4`). Notes outside every entry play silence;
  `check` warns when the patterns use such a note.
- default: the note plays the sample at the note's own pitch.
- `transpose: 12`: the note plays 12 semitones higher.
- `play_note: C-5`: every note in the range plays the sample at C-5. This is how drum kits keep
  each drum at its recorded pitch.

Envelope: `{nodes: [[tick, value], ...], sustain: <i or [a, b]>, loop: [a, b], enabled: true, carry: false}`
- 1–25 nodes. The first tick must be 0 and ticks must increase (max 9999). Ticks are song ticks
  (section 3), so envelope speed follows the tempo.
- `sustain: i` holds at node `i` while the note is held; `sustain: [a, b]` loops between nodes `a` and
  `b` until note-off. After note-off the envelope continues to its end.
- `loop: [a, b]` loops between those nodes forever (after sustain is released).
- `enabled: false` keeps the nodes but turns the envelope off (the `S78`/`S7A`/`S7C` effects can turn it on).
- `carry: true` makes a new note continue from the previous note's envelope position instead of
  restarting it. This is an OpenMPT extension: libopenmpt honours it, Impulse Tracker ignores it.
- When the volume envelope reaches its last node, the note's fadeout starts. A note-off (`===`) starts
  the fadeout immediately only if the instrument has no volume envelope or its envelope loops. A
  note whose envelope ends above 0 with `fadeout: 0` keeps sounding at that level until it's cut or
  replaced.

## 6. Patterns

```yaml
patterns:
  verse:
    rows: 64              # 1..200; defaults to the number of rows written
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

## 7. `orders`

```yaml
orders: [intro, a, b, a, +++, c]
```

Pattern names in play order. `+++` is a skip marker and `---` ends the song. At most 255 entries. Without
a `Bxx` jump, the song loops back to the first order after the last one. Patterns that are defined
but not in the list produce a warning.

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

At most 64 channels, 99 samples, 99 instruments, 200 rows per pattern, 255 orders and 25 envelope nodes.
`check` reports all errors at once as `file:line: error: ...`, plus warnings (unused patterns,
notes that map to no sample). Common mistakes it catches:
- lower-case notes, flats, or `C5` instead of `C-5`
- effect letters that are digits (MOD/XM style `A08` is fine; `008` is not)
- lower-case effect letters
- volume values out of range or single-digit (`v8`)
- instruments that aren't defined
- `Bxx` beyond the order list
- misnumbered row labels
- patterns with too many rows or cells
