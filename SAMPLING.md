# Making samples: synths, recordings and printed effects

90s tracker musicians sampled their hardware synths: a long note with the filter sweep baked
in, a chord stab, a whole sequenced phrase. VultureTracker does the same with free software synths:
[Surge XT](https://surge-synthesizer.github.io), [Dexed](https://github.com/asb2m10/dexed) (a Yamaha DX7
emulation: the electric pianos, basses and bells of early-90s records) and
[OB-Xd](https://github.com/reales/OB-Xd) (an Oberheim OB-X emulation: analog strings, pads and basses).
A YAML **sample recipe** lists what to record; `vulturetracker synth` plays it through the synths offline and
writes WAVs ready for a song. Like songs, recipes are plain text, so every sound choice stays visible and editable.

A recipe can also start from a **recorded audio file** (`file:`) instead of a patch, for example the
CC0 orchestral and drum libraries fetched by `tools/fetch_cc0.py`. Either way, **`fx:`** prints an
effects chain (reverb, delay, chorus, distortion, lo-fi resampling and bit crushing) into the sample,
the way 90s musicians sampled through an effects rack.

## Setup (once)

```
pip install pedalboard mido          # plugin host (renders VST3 instruments offline) + MIDI messages
python tools/fetch_surge.py          # Windows: portable Surge XT 1.3.4 into tools/surge-xt/ (~300 MB, no installer)
python tools/fetch_instruments.py --install-obxd   # Dexed, OB-Xd (runs its installer) and a drum-machine pack
```

The exe needs none of this: its RECIPE box (GUIDE.md) downloads Surge XT or Dexed the first time a recipe needs one.
`fetch_instruments.py` puts Dexed in `tools/synths/` (no installer). OB-Xd's Windows release is an installer
only: `--install-obxd` downloads and runs it silently (VST3 in Common Files, preset banks in
`Documents\discoDSP\OB-Xd\Banks`); leave the flag off to install it yourself. It also downloads MusicRadar's
free [hardware drum machine samples](https://www.musicradar.com/music-tech/samples/sampleradar-493-free-hardware-drum-machine-samples)
(Roland TR-8, Alesis HR-16, Jomox Airbase 99, Nord Drum, Arturia DrumBrute) into `tools/royalty-free/`.
Their terms allow any use in your music but forbid redistributing the samples, so recipes that use them
write to `samples/local/` (gitignored), and modules built from them (which embed their samples) shouldn't be
published. The synths are free; audio you render from them is yours.

Every download (Surge XT, Dexed, OB-Xd's installer, the MusicRadar zip, faustwasm) is verified against a SHA-256
digest pinned beside its URL (`synth.FETCH`, `faust.SHA256`, the constants in `tools/fetch_instruments.py`) before it
is unpacked or run; a mismatch deletes the file and reports it. To bump a version, download the new asset, hash it
(`certutil -hashfile <file> SHA256` or `sha256sum`) and update the digest with the URL. MusicRadar's zip is
unversioned, so its digest may need refreshing when they republish it.

For recorded samples, `python tools/fetch_cc0.py` downloads a curated selection (~630 MB) of three CC0
(public domain) libraries into `tools/cc0/` (gitignored): Big Rusty Drums by Karoryfer Samples (drum kit),
VSCO 2 Community Edition (orchestra, percussion, sound effects) and the Versilian Community Sample Library
(tuned percussion and more), both by Versilian Studios. Each library's folder holds its `LICENSE` and a
`SOURCE.txt`. To fetch more, add glob patterns to `LIBRARIES` in the script and rerun it; files already
present are skipped, and `--list` shows the plan with sizes. CC0 needs no attribution, but crediting the
libraries is good manners (see `samples/demo3/ATTRIBUTION.md`).

On macOS or Linux, install Surge XT normally and set `SURGE_XT_DIR` to the folder containing
`Surge XT.vst3` and `SurgeXTData`. `DEXED_VST3` and `OBXD_VST3` point at those plugins' `.vst3` bundles when they are
not where the fetch scripts put them, and `FAUSTWASM_DIR` at a faustwasm other than the one GET FAUST fetches. Audio you render is yours to use. Surge itself is GPL-3 and
is not committed to this repo.

## Workflow

```
python -m vulturetracker audition 'Pads/*' -o pads.wav              # hear every pad patch, with a timestamp list
python -m vulturetracker audition '3rdparty/Cybersoda/Drums/*' -o drums.wav --note C-5
python -m vulturetracker synth demo2/kit.yaml                        # render every sample in the recipe
python -m vulturetracker synth demo2/kit.yaml --only 'bass*'         # re-render some
python -m vulturetracker surge-params cutoff                         # parameter names for 'params:'
python -m vulturetracker audition 'tools/cc0/bigrusty/**/cl/*_rr1.flac' -o hats.wav   # a file glob plays audio files
python -m vulturetracker audition 'obxd:008 - Pads and Strings 1/*' -o strings.wav   # OB-Xd bank
python -m vulturetracker audition 'dexed:SynprezFM_0[1-4]/*' -o dx.wav                   # Dexed cartridges
python -m vulturetracker synth demo3/kit.yaml                        # synths + effects recipe
python -m vulturetracker tryout demo3/undertow.yaml --sample 8 --orders 2-3 -o bass.wav cand/bass_*.wav
```

Then reference the WAVs from a song (`file:`, `base_note:` = the root the log printed, and
`loop: from_wav` for looped samples). See `demo2/kit.yaml` and `demo2/iron_relay.yaml`.

### Choosing sounds in context

A sound that is fine on its own can clash with the rest of a mix, so compare candidates *inside* the song:
render each candidate (a recipe with one sample per candidate, same note and effects), then
`vulturetracker tryout song.yaml --sample N cand/*.wav` plays a part of the song once per candidate, with only
sample slot `N` swapped, and prints a timestamp per version. `--orders 2-3` picks the order positions to play.
The candidate's root note (from its `smpl` chunk, which `synth` writes) sets the slot's `base_note`.
Pick by number, then put the winner in the real recipe. That's how demo3's sounds were chosen.

In the app the same loop is one box: when a recipe in the song's folder writes the slot's WAV, the Tryout tab's RECIPE
box holds that sample's entry as YAML; RENDER CANDIDATE renders the edited entry as a new candidate (`<name>-r1.wav`
beside the original) and WRITE TO RECIPE puts the entry back into the recipe (GUIDE.md, Tryout).

### Portable editable sound sources

PROJECT → Collect Samples copies supported recipes beside the collected song, rewrites their file inputs to collected
relative paths, includes referenced Faust `.dsp` files, and keeps candidate-specific edited recipe entries. The rendered
WAVs are sufficient for playback/rendering without the original location. Re-rendering a named Surge/Dexed/OB-Xd patch
still needs that synth and patch library; collection does not copy installed plugins. Browser Faust drafts and Paint
pictures are included as project settings and can be explicitly restored in the receiving browser. Adjacent credit and
license documents are copied into `credits/` and associated with their assets in `project.json`. Credits and licensing
still apply to the source material; collection is a local copy, not permission to publish third-party samples.

Choose an original line first with the PHRASES comparison, then choose its sound with TRYOUT. Phrase capture freezes
WAVs and audition settings for identical accompaniment; it never composes new notes. All audio export still uses the
existing oversampled renderer. The owner's ear decides sounds and levels.

## Recipe format

```yaml
out_dir: ../samples/surge        # relative to the recipe file
sample_rate: 44100
defaults: {velocity: 110, hold: 0.5, tail: 0.5, normalize: -1.0, mono: true}   # applied to every sample

samples:
  kick: {patch: Percussion/Kick Tech 1, note: C-5, hold: 0.3, tail: 0.4}
  bass:
    patch: Basses/Distorted Bass
    notes: [C-4, C-5]            # one file per note: bass_c3.wav, bass_c4.wav (named by sounding pitch)
    root_offset: -12             # the patch sounds an octave below the key played
  pad:
    patch: Pads/MKS-70 Warm Pad
    note: C-5
    hold: 7.0
    mono: false
    loop: {start: 2.5, end: 6.5, crossfade: 1.0}
  arp:
    patch: Plucks/FM Pluck
    phrase: {bpm: 140, root: D-5, length: 2, notes: [[D-5, 0, 0.2], [A-5, 0.25, 0.2]]}
```

| key | default | meaning |
|---|---|---|
| `patch` | | Surge XT: `Category/Name` (factory), `3rdparty/Author/Category/Name`, or a path to an `.fxp`. Dexed: `dexed:Cartridge/Voice` (voices of each `.syx` cartridge in Dexed's cartridge folder or `tools/synths/cartridges/`). OB-Xd: `obxd:Bank/Program` (programs of each `.fxb` bank). Use `audition` with a glob to list and hear them. |
| `file` | | instead of `patch`: an audio file (WAV, FLAC, AIFF, OGG, MP3; relative to the recipe), or a list of files mixed together (e.g. close and overhead mics of one drum hit). Resampled to `sample_rate`. |
| `resynth` | | instead of `patch` or `file`: a target WAV rebuilt from blocks of other WAVs (see below) |
| `faust` | | instead of `patch`: Faust code, or a `.dsp` file beside the recipe, rendered a voice per note (see below) |
| `wave` | | instead of `patch`: one looped cycle of a chip or drawn waveform, band-limited by construction (see below) |
| `sfxr` | | instead of `patch`: a sound effect from sfxr's synthesis, a preset drawn from a seed (see below) |
| `additive` | | instead of `patch`: a PADsynth pad, harmonics as bands of noise in one exact loop (see below) |
| `drum` | | instead of `patch`: DrumSynth's sections (tone, noise, overtones, noise bands, distortion, filter), or a `.ds` file (see below) |
| `mip` | none | any source: copies band-limited per octave (or `step`) and the song's `samples:`/`keymap:` to paste (see below) |
| `start`, `length` | 0, all | `file` and `resynth` (its target): seconds to skip, and seconds to keep (effects tails still ring past `length`) |
| `note` | | `patch`: the key to play, in tracker names (`C-5` = MIDI 60 = middle C). `file`: the pitch recorded in the file (default `C-5`) |
| `notes` | | a list of keys, rendering one file per key (for multisampled instruments) |
| `chord` | | a list of keys played together as one sample (root = the first; an empty one is an error) |
| `phrase` | | `{bpm, notes: [[note, start_beat, length_beats, velocity?], ...], length?, root?}`: a whole sequence as one sample, to chop in the song with `Oxx` (`bpm` above 0 and one note at least, each of three or four values) |
| `velocity` | 100 | MIDI velocity 1–127 (outside it, and in a phrase note, an error) |
| `hold` | 1.0 | seconds the key is held (`0`: one sample frame) |
| `tail` | 0.5 | seconds recorded after release (for release and effects tails) |
| `root_offset` | 0 | semitones from the key played to the pitch heard (use -12 for patches that sound an octave down) |
| `params` | | `{parameter_name: value}` plugin parameter overrides (Surge names: `surge-params`; Dexed uses DX7 names like `op1_output_level`, `algorithm`) |
| `mono` | false | mix to mono (drums, basses, leads); keep stereo for pads |
| `normalize` | none | peak level in dBFS (e.g. `-1.0`); without it, a render over full scale (a chord, `gain`) is scaled just under it, and the log says by how much |
| `gain` | 0 | extra gain in dB after normalizing |
| `trim` | true | cut leading silence and trailing silence below -60 dB |
| `fade_out` | 0.01 | seconds of fade at the end (unlooped samples) |
| `reverse` | false | reverse the sample (reverse cymbal risers); after `fx`, so a reverb tail becomes a swell |
| `fx` | none | effects printed into the sample, in order (see below) |
| `fx_tail` | 1.0 | seconds of silence added before `fx`, so reverb and delay tails ring out (then trimmed) |
| `loop` | none | `{start, end, crossfade, type}` in seconds after trimming. The crossfade is baked in so the loop is seamless; it is stored in the WAV's `smpl` chunk (`type`: `forward` or `pingpong`). |

After rendering, `synth` estimates each sample's pitch. If it doesn't match the recorded root, it
prints a warning suggesting a `root_offset` (common for bass and pad patches built an octave down).
Unpitched sounds (drums, noise) aren't checked, and neither are `file` samples without a `note:`
(taken as drums). For recorded files this checks the `note:` you
gave, and it is how file names were confirmed to be scientific pitch: VSCO's `E3` is tracker `E-4`.

Every sample needs exactly one of `patch`, `file`, `resynth`, `faust`, `wave`, `sfxr`, `drum` or `additive`. `file`, `resynth`,
`sfxr` and `drum` samples take `note` (never `notes`, `chord` or `phrase`), and `wave` and `additive` take `note` or `notes` (never `chord`, `phrase` or `loop`); `hold`,
`velocity` and `params` only apply to patches and `faust`.

## Faust code (`faust:`)

```yaml
  pluck:
    faust: |
      import("stdfaust.lib");
      freq = hslider("freq", 440, 20, 4000, 0.01);
      gate = button("gate");
      bright = hslider("bright", 0.5, 0, 1, 0.01);
      process = os.sawtooth(freq) * en.adsr(0.002, 0.3, 0.2, 0.2, gate) : fi.lowpass(2, 300 + bright * 6000);
    notes: [C-4, C-5]        # or note:, chord:, phrase:; or faust: pluck.dsp for a file beside the recipe
    hold: 0.6
    tail: 0.4
    params: {bright: 0.3}    # the other controls, by label
```

[Faust](https://faust.grame.fr) (GRAME's language for signal processing, with its libraries of oscillators, filters,
physical models and effects) is compiled and rendered offline by the Faust compiler built as WebAssembly (faustwasm,
LGPL-3.0, fetched from npm into `tools/faustwasm` by the app's FAUST tab or RECIPE box, or `python -c "from
vulturetracker import faust; faust.fetch()"`; about 6 MB kept). Each note is a voice of its own, the way Faust plays
polyphony: the controls whose paths end in `freq`, `gain` and `gate` (lowercase) get the note's pitch, its velocity /
127, and 1 while the note is held (`hold` seconds for a `note` or a `chord`; a `phrase` note its length), then the
render goes on `tail` seconds after the last release. `note`, `notes`, `chord` and `phrase` work as for patches (a
chord's root is its first note; without any of them a `faust:` sample plays C-5). `params` sets the other controls,
shared by all voices, by label (an unknown label is an error; `gain` is the velocity's). An `effect = ...;` definition
in the code (Faust's own convention) runs once on the voices' sum, a reverb over the whole chord say. The rest of the
chain (`fx`, `trim`, `loop`, `normalize`) follows as for any sample.
Rendering in a recipe runs under [node](https://nodejs.org) (`web/faust-render.mjs`); the app's FAUST tab renders the
same code in the page without it. Every sound the FAUST tab saves gets an entry like the one above, named after its WAV,
in `faust.yaml` beside the song (`out_dir: .`, so the entry writes that very WAV), with `trim: false` and `fade_out: 0`
because the tab renders without them: `synth faust.yaml --only NAME` renders it again, and in the app the slot's
RECIPE box shows it.

The app ships examples to start from, used as `faust: NAME.dsp` when no file of that name sits beside the recipe (their
code is in `vulturetracker/faust_examples/`; copy one beside the recipe to change it). Each takes `freq`, `gain` and
`gate` from the notes, and its other controls through `params`:

| file | what | controls (`params`) |
|---|---|---|
| `pluck.dsp` | Karplus-Strong string (`pm.ks`) plucked by a noise burst combed at the pick position | `position` (0.02-0.5 from the end), `damping`, `burst` (s) |
| `nylon.dsp` | nylon-string guitar (`pm.nylonGuitar`) | `position` |
| `marimba.dsp` | marimba bar and resonator tube (`pm.marimba`'s parts) | `position` (0-4), `cutoff` (the mallet, Hz), `sharpness`, `decay` (the ring, s) |
| `organ.dsp` | drawbar organ: nine sines at the tonewheel footages, each 0-8, with a key click | `bar1`-`bar9` (16' to 1'; default 008800000: `bar1` sounds an octave below the note), `click` |
| `opl2.dsp` | two-operator FM in the manner of the OPL2 chip, its four waves (sine, half, absolute, quarter sine) | `mod_wave`, `car_wave` (0-3), `mod_mult`, `car_mult`, `index`, `mod_decay` |
| `acid.dsp` | saw through a diode ladder (`ve.diodeLadder`) swept down at each note | `cutoff`, `envmod`, `decay`, `resonance`, `accent` |
| `kick.dsp` | a sine falling from `start` to `end` Hz with a decay and tanh drive; the note's pitch leaves it alone | `start`, `end`, `slope` (s), `env` (s), `dist` |

```yaml
  pluck: {faust: pluck.dsp, notes: [E-3, E-4], hold: 0.8, tail: 1.5, params: {position: 0.12}}
  kick: {faust: kick.dsp, hold: 0.5, params: {start: 220, end: 42, dist: 0.4}}
```

## Resynthesis from a corpus (`resynth:`)

```yaml
  mosaic:
    resynth:
      target: loops/break.wav          # the sound whose rhythm and loudness are followed
      corpus: [kit/, pads/*.wav]       # WAV files, globs or folders (relative to the recipe) whose sounds rebuild it
      block: 0.05                      # seconds per block
      overlap: 4                       # blocks per block length: the hop is block / overlap
      variety: 1                       # pick at random among this many nearest blocks (with seed)
      reuse: 0.5                       # avoid the corpus blocks used in the last 8 blocks (0: no, 1: strongly)
      level: 1.0                       # how far each block follows the target block's loudness (0: its own)
      mix: 0.0                         # the target itself blended back in
    normalize: -1
```

The idea is Samplebrain's (nothing of its code is used): the target and every corpus file are cut into overlapping
blocks, each block is described by 12 MFCCs (the same mel bands the MAP tab's index uses), and every target block is
replaced by the corpus block nearest it in timbre, brought to the target block's level and overlap-added with a Hann
window. A drum loop rebuilt from pads keeps its rhythm with the pads' sounds; a voice rebuilt from a drum kit talks in
hits. Target blocks under `gate` dBFS (default -60) stay silent; `corpus_seconds` (default 120) caps how much of the
corpus is read (the files in order, each from its start); `seed` (default 0) makes `variety` repeatable. The output
is mono, at the recipe's `sample_rate`; the rest of the chain (`fx`, `trim`, `loop`, `normalize`) follows as for any
sample. Numpy only: no synth and no pedalboard are needed unless `fx:` is used. `synth` logs how many blocks and
distinct corpus blocks were used.

## Waves (`wave:`) and band-limited copies (`mip:`)

```yaml
  chip:
    wave: {shape: pulse, duty: 0.125}  # pulse saw square triangle tri4 lfsr gb table
    notes: [C-4]                       # the cycle's pitch (default C-5)
    mip: {octaves: 4}                  # chip.wav, chip_o1.wav ... chip_o4.wav, and the song blocks printed
  wavetable:
    wave: {table: [0, 6, 12, 15, 12, 6, 0, -6, -12, -15, -12, -6]}   # one cycle drawn in steps
  noise:
    wave: {shape: lfsr, short: true}   # the NES noise channel's 93-step period
```

A `wave` is one cycle of a waveform, looped: the sample is the fewest whole cycles that fit whole frames within 0.1
cent of the note (a C-5 takes 9 cycles in 1517 frames), with the loop on exactly those frames, so it never drifts or
clicks. It is summed from the shape's harmonics at or under `ceiling` (default 18000 Hz) and has no DC, so it is
band-limited by construction: nothing in it aliases, and `check` measures it like any sample. Shapes: `pulse` (`duty`
0-1, default 0.5), `saw`, `square`, `triangle`; `tri4`, the NES triangle's 32 steps of 4 bits; `gb`, a Game Boy wave
table (`table`: 32 whole numbers 0-15); `table`, any list of numbers drawn as equal steps (scaled to full range); and
`lfsr`, one period of the NES noise channel's 15-bit shift register (32767 steps, or 93 with `short: true`), a step per
frame at the recipe's rate, the note naming the pitch it plays at. `frames: N` draws `pulse`, `saw`, `square` or
`triangle` as N equal steps, the way a wavetable chip stores it. The staircase of a step table is kept up to the
ceiling. `fx` runs on the stored cycles: memoryless effects (`waveshape`, `bitcrush`) keep the loop seamless, a delay or
a reverb does not.

A single cycle with harmonics up to 18 kHz can only be played at its root and below: played up, its harmonics pass the
ceiling, and `check` says so (`mip` exists for this; playing it far below the root raises the images warning). `mip:
{octaves, ceiling, step}` (defaults 3, 18000 Hz, 12 semitones; `mip: true` takes them all) works on any source: the
render is written as `octaves` + 1 copies, the first serving every key up to `step` - 1 semitones above the root, each
next one the following `step` keys (a boundary key takes the narrower copy). Each copy is band-limited so that its
highest key lifts it exactly to the ceiling, and stored at twice that width (the base copy of a C-4 at about 19 kHz,
each further octave at half the rate), as the references store samples low and play them octaves up; a loop is
resampled with it and stays whole frames (the rate nudged to keep it so). The log ends with the `samples:` and
`instruments:` blocks to paste into the song, paths from the recipe's folder (renumber the samples to free slots; with
a `notes:` list each key gets its own copies and block). With them a song plays the sound on every key the copies cover
with no ceiling warning (four octaves of copies of a C-4 reach B-8). A song's `sample_rate: 44100` resamples the copies up again when it compiles, band-limited, so they
cost nothing in the module.

## Pads (`additive:`)

```yaml
  pad:
    additive: {harmonics: [1, 0.5, 0.6, 0.2, 0.3, 0.1], bandwidth_cents: 60, bandwidth_scale: 1, loop_seconds: 4, seed: 2}
    notes: [C-4, C-5]
```

Nasca Octavian Paul's PADsynth algorithm (public domain; from his description, zynaddsubfx.sourceforge.io): every
harmonic of the note is a Gaussian band of frequencies, `bandwidth_cents` wide (default 40) at the first harmonic and
`h ** bandwidth_scale` times that at the h-th (default 1: as wide in cents at every harmonic; 0 keeps them equal in Hz,
above 1 the high ones spread more), never narrower than one bin; every bin of the spectrum gets a random phase from
`seed` (default 0), and one inverse FFT turns it into `loop_seconds` (default 3) of sound. The result is a chorus-like
pad with no beating pattern that repeats, and it loops exactly: the loop is the whole sample and its end runs into its
start. `harmonics` is a list of amplitudes (the first is the fundamental; 0 leaves one out) or a count (amplitudes 1/h,
default 16). As in PADsynth the amplitude is per hertz, so a wider band is quieter: a harmonic's power falls as its
band widens. Harmonics, and bins, over `ceiling` (default 18000 Hz) are left out, so `mip` can make the higher copies.
Like `wave`, it takes `note` or `notes` (default C-5), not `chord`, `phrase` or `loop`, and is not pitch-checked.

## Sound effects (`sfxr:`)

```yaml
  zap1: {sfxr: {preset: laser, seed: 1}}
  zap2: {sfxr: {preset: laser, seed: 2}}
  coin: {sfxr: {preset: pickup, seed: 7, p_env_decay: 0.5}}     # a preset with one parameter changed
  tone: {sfxr: {wave_type: square, p_base_freq: 0.35, p_duty: 0.6, p_freq_ramp: 0.2}}
```

The synthesis of [sfxr](https://www.drpetter.se/project_sfxr.html) by Tomas Pettersson (DrPetter; MIT, reimplemented
from his source): one oscillator (`wave_type` square, saw, sine or noise, or 0-3) with a slide and a slide of the slide,
a duty sweep, an arpeggio jump, vibrato and repeat, a phaser, a resonant low-pass and a high-pass with sweeps, and an
attack, sustain, punch and decay envelope. Parameters go by sfxr's names, the same in jsfxr, each 0 to 1 (the ramps,
`p_arp_mod` and `p_pha_offset` -1 to 1): `p_env_attack`, `p_env_sustain`, `p_env_punch`, `p_env_decay`, `p_base_freq`,
`p_freq_limit`, `p_freq_ramp`, `p_freq_dramp`, `p_vib_strength`, `p_vib_speed`, `p_arp_mod`, `p_arp_speed`, `p_duty`,
`p_duty_ramp`, `p_repeat_speed`, `p_pha_offset`, `p_pha_ramp`, `p_lpf_freq`, `p_lpf_ramp`, `p_lpf_resonance`,
`p_hpf_freq`, `p_hpf_ramp`; unnamed ones keep sfxr's defaults. `preset` is one of sfxr's generator buttons (`pickup` or
`coin`, `laser` or `shoot`, `explosion`, `powerup`, `hit` or `hurt`, `jump`, `blip` or `select`), its random choices
drawn from `seed` (default 0), so a seed always gives the same sound: write several seeds as candidates and pick by ear.
The parameters named beside it replace the preset's. sfxr runs eight sub-steps of its oscillator and filters per 1/44100
s frame and averages them, which folds what lies above 22 kHz back down; here the sub-steps are kept as a 352.8 kHz
stream and resampled to the recipe's rate, band-limited. The sound ends where sfxr's does (its envelope's end, or the
frequency limit). `note` (default C-5) only names the pitch it is played at; sfxr samples are not pitch-checked.

## Drums (`drum:`)

```yaml
  kick:
    drum:
      tone: {level: 181, f1: 600, f2: 50, droop: 50, phase: 90, envelope: [[0, 100], [3000, 40], [15000, 0]]}
      noise: {level: 40, slope: -50, envelope: '0,100 500,0'}
  hat:
    drum:
      noiseband: {level: 120, f: 9000, df: 80, envelope: '0,100 2000,0'}
      general: {filter: 1, highpass: 1, filterenv: '0,60 2000,60'}
  mine: {drum: kits/mine.ds}     # your own DrumSynth file, beside the recipe
```

The drum maker of Paul Kellett's DrumSynth 2.0 (mda-vst.com; MIT, reimplemented from his renderer and help file), built
on the circuits of early drum machines: a section is a sound generator with its own envelope, and the sections are
summed. A section given in the mapping is on (`on: 0` turns it off); a `.ds` file beside the recipe is read as
DrumSynth reads it (an INI file whose `[General]` `Version` is DrumSynth 1 or 2; its sections need `On=1`), so a sound
saved from DrumSynth renders here. Keys are DrumSynth's names in any case, and a key left out takes DrumSynth's default. Envelopes are
`time,level` points in a string (`'0,100 3000,40 15000,0'`, as in a `.ds` file) or a list of pairs, times in frames at
44100 Hz (DrumSynth's rate: 4410 is a tenth of a second), levels 0-100, linear between points; a section stops at its
last point. Levels go up to 255 and square: 181 is full scale. The sound is rendered at 44100 Hz as DrumSynth does,
then resampled to the recipe's rate.

| section | keys (default) |
|---|---|
| `tone` | a sine swept from `f1` (200 Hz) to `f2` (120 Hz) over its envelope; `droop` (0: a straight sweep; higher reaches F2 sooner), `phase` (90 degrees: the start phase, 0 starts on a click-free zero), `level` (128), `envelope` |
| `noise` | white noise; `slope` (0; -100 to 100: darker to brighter, not tuned by `tuning`), `level` (0), `envelope` |
| `overtones` | two oscillators `f1` (200) and `f2` (120) Hz, `wave1`/`wave2` (0 sine, 1 rectified sine, 2 triangle, 3 saw, 4 square), `track1`/`track2` (1: follow the tone's sweep as a ratio of its F1), `method` (2; 0 mixed, 1 the second modulates the first's frequency, 2 ring modulation, 3 the 808 cymbal: six pulse trains between the two periods through a band-pass that `envelope2` sweeps), `param` (50: the balance; the drive for 1 and 2, the resonance for 3), `filter` (1: the master filter on the overtones only), `level` (128), `envelope1`, `envelope2` |
| `noiseband`, `noiseband2` | a band of noise around `f` (1000 Hz), `df` (50) wide, `level` (128), `envelope` |
| `distortion` | `clipping` (0 dB of gain into the clip), `bits` (0; each step takes two bits off), `rate` (0; 1-6 hold every 2, 3, 4, 8, 10 or 20 frames) |
| `general` | `tuning` (0 semitones), `stretch` (100: % of every envelope's length, 20-1000), `level` (0 dB), `filter` (1: the master filter on everything), `resonance` (0-100), `highpass` (1: a high-pass instead), `filterenv` (the cutoff, 0-100; it holds its last level) |

`note` (default C-5) names the pitch the sample is played at, as for a recorded drum; drums are not pitch-checked. The
noise sections fill the band to half the rate: play such a drum at its root or below (`check` measures it like any
sample).

## Printed effects (`fx:`)

```yaml
  kalimba:
    file: "../tools/cc0/vcsl/Idiophones/Plucked Idiophones/Kalimba, Kenya/Mbira6_Normal_MainSpirit_B3_k12_vl3_rr2.wav"
    note: B-4
    fx_tail: 1.5
    fx:
      - delay: {delay_seconds: 0.36, feedback: 0.35, mix: 0.3}     # a dotted 8th at 125 BPM
      - reverb: {room_size: 0.6, wet_level: 0.25, dry_level: 0.85}
      - resample: {target_sample_rate: 16000}                      # lo-fi: a 16 kHz rate, 8 kHz bandwidth
      - bitcrush: {bit_depth: 8}                                   # lo-fi: 8-bit quantisation noise
```

Each item is one effect: a name, or `{name: {parameter: value}}`. The effects are
[pedalboard](https://spotify.github.io/pedalboard/reference/pedalboard.html)'s built-in plugins, and the
parameters are their constructor arguments. Names are case-insensitive, with or without underscores
(`highpass_filter` = `HighpassFilter`). A parameter that takes one of a set of names (`quality`, `mode`) is written as
the name. All 24 effects `fx:` accepts (pedalboard's 25th, `IIRFilter`, is the shelves' base class and cannot be
built):

| effect | parameters (defaults) |
|---|---|
| `reverb` | `room_size` 0.5, `damping` 0.5, `wet_level` 0.33, `dry_level` 0.4, `width` 1, `freeze_mode` 0 |
| `delay` | `delay_seconds` 0.5, `feedback` 0, `mix` 0.5 |
| `chorus` | `rate_hz` 1, `depth` 0.25, `centre_delay_ms` 7, `feedback` 0, `mix` 0.5 |
| `phaser` | `rate_hz` 1, `depth` 0.5, `centre_frequency_hz` 1300, `feedback` 0, `mix` 0.5 |
| `convolution` | `impulse_response_filename`, `mix` 1: any impulse response WAV makes a reverb or a cabinet; the path is read as given (from the folder the command runs in), so give it absolute |
| `distortion` | `drive_db` 25: tanh saturation |
| `clipping` | `threshold_db` -6: hard clip |
| `bitcrush` | `bit_depth` 8: the hiss and grit of 8-bit samples |
| `compressor` | `threshold_db` 0, `ratio` 1, `attack_ms` 1, `release_ms` 100 |
| `limiter` | `threshold_db` -10, `release_ms` 100 |
| `brickwall_limiter` | `ceiling_db` -1, `release_ms` 100, `lookahead_ms` 5, `true_peak` false |
| `noise_gate` | `threshold_db` -100, `ratio` 10, `attack_ms` 1, `release_ms` 100 |
| `gain` | `gain_db` 1 |
| `invert` | none: polarity flip |
| `highpass_filter`, `lowpass_filter` | `cutoff_frequency_hz` 50 (12 dB per octave) |
| `low_shelf_filter`, `high_shelf_filter` | `cutoff_frequency_hz` 440, `gain_db` 0, `q` 0.707 |
| `peak_filter` | `cutoff_frequency_hz` 440, `gain_db` 0, `q` 0.707: one band of a parametric EQ (list several) |
| `ladder_filter` | `mode` LPF12 (or HPF12, BPF12, LPF24, HPF24, BPF24), `cutoff_hz` 200, `resonance` 0, `drive` 1 |
| `pitch_shift` | `semitones` 0 |
| `resample` | `target_sample_rate` 8000, `quality` WindowedSinc32: downsample and back, for early-sampler bandwidth. The windowed sinc qualities (`WindowedSinc`, `WindowedSinc8` to `WindowedSinc256`) are band-limited: they remove what is above the new Nyquist frequency. `quality: ZeroOrderHold` is the aliasing lo-fi (a sample-and-hold, what a bitcrusher's rate knob does): content above the new Nyquist folds back down as inharmonic tones; `Linear`, `CatmullRom` and `Lagrange` alias less |
| `mp3_compressor` | `vbr_quality` 2 (0 best to 10 worst): MP3 codec artefacts |
| `gsm_full_rate_compressor` | `quality` WindowedSinc8: the GSM phone codec at 8 kHz |

Eight more are VultureTracker's own (numpy; no pedalboard needed for a recipe that uses only these). They mix freely
with the ones above and every item runs in the list's order:

```yaml
    fx:
      - waveshape: {shape: foldback, drive_db: 9}           # folds the peaks: new harmonics
      - bandlimit: {hz: 6000}                               # nothing above 6 kHz: playable an octave and a half up
      - multitap: {bpm: 165, step: 3/16, taps: [[-6, 3000, 0.7], [-12, 2000, -0.7]]}  # two panned, darker echoes
```

| effect | parameters (defaults) |
|---|---|
| `bandlimit` | `hz`: nothing above it (the compiler's own 1023-tap sinc, a transition about 0.5 % of the rate wide, the stop band under -74 dB), so `check` measures the sample `hz` wide. pedalboard's `resample` is about as clean (a 20000 target leaves 10.6 kHz); its `lowpass_filter` (12 dB per octave) and `ladder_filter` leave content far above their cutoff that `check` counts (a 6 kHz `lowpass_filter` measures 22 kHz wide) |
| `multitap` | `bpm` and `step` (a note length in whole notes, `3/16` a dotted eighth) set the gap; `taps` [[gain_db, lowpass_hz, pan], ...] (pan -1 left to 1 right, ignored on a `mono: true` take; the last two optional), or `count` taps each `decay_db_per_tap` (-6) quieter and low-passed by `lowpass_hz` once more than the one before, `pingpong` alternating right and left. The dry take stays. Tempo-synced echoes printed into the sample, so the tryout can swap the whole figure; the echoes are at the recipe's `bpm`, not the song's |
| `waveshape` | `shape` (`tanh`, `sine`, `foldback`, `rectify`, `half_rectify`, `soft`) or `curve` [[in, out], ...] from 0 to 1 (linear between points, the sign kept), `drive_db` 0, `mix` 1 |
| `slew` | `up_db` 0, `down_db` 0 (how far each frame may rise or fall: -20 dB is 0.1 of full scale a frame), `drive_db` 0, `shape` (one of `waveshape`'s): the soft corners of a slow amplifier. A Python loop: a few seconds of sample take a second |
| `shift` | `hz` (negative moves down), `ring` 0 (1: ring modulation by a `hz` sine instead), `mix` 1: every partial moved by the same Hz, so a harmonic sound turns inharmonic (bells, metal, ±1 Hz for a slow beat) |
| `stereo` | `matrix` [[ll, lr], [rl, rr]], then `width` 1 (0 mono, 2 twice as wide: the side scaled), then `haas_ms` 0 (the right channel delayed, up to 30), then `swap` false. Needs two channels (not `mono: true`). A Haas delay prints a sample that loses level summed to mono: the correlation meter shows it |
| `dispersion` | `stages` 8, `hz` 1000, `q` 0.7: that many all-passes in series, each frequency delayed by its own amount at its own level, so a click becomes a chirp |
| `granular` | `grain_ms` 80, `density` 4 (grains overlapping), `pitch_st` 0, `jitter` 0 (semitones at random per grain), `spray_ms` 0 (read that far either side at random), `shape` `hann` (or `triangle`, `rect`), `seed` 0: a cloud of grains at the same length; the same seed gives the same cloud |

`fx_tail` grows by itself to fit the last echo tap, the Haas delay and a dispersion's chirp. Anti-aliasing:
`waveshape`, `slew`, `shift` up and `granular` up widen the sample's band, and `check` warns when a note then lifts it
over the song's ceiling (18 kHz unless `module: ceiling` says otherwise). Put a `bandlimit` or a `resample` after them
(or render the recipe at a lower `sample_rate`: the compiler's resampler band-limits it the same way). The effects run at the recipe's rate, so what they create above half of it folds back down inside the take:
drive a shape gently, low-pass before a `shift` or a `granular` pitch up, or render the source at a higher
`sample_rate` first.

The order of processing is: source → `start`/`length` → peak-normalise to -1 dBFS → pad with `fx_tail`
seconds of silence → `fx` → `mono` → `reverse` → trim silence → `loop` → `fade_out` → `normalize`/`gain`.
The input is normalised first, so `bitcrush` and `distortion` act the same whatever the recording level.
A mono source becomes stereo before the effects unless `mono: true`, so reverb and chorus get their width.
Put `resample` and `bitcrush` last, so the reverb tail gets the same grit as the dry sound.

`demo3/kit.yaml` is a complete example: an analog bass and a looped lead cut from the same patch, a string-machine
chord for gating, a DX7 string pad and two CC0 cymbals, each resampled to the rate its role has in the UT99 modules
(11 kHz pads, 22 kHz bass and lead).
