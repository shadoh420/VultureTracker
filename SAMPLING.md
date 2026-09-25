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

`fetch_instruments.py` puts Dexed in `tools/synths/` (no installer). OB-Xd's Windows release is an installer
only: `--install-obxd` downloads and runs it silently (VST3 in Common Files, preset banks in
`Documents\discoDSP\OB-Xd\Banks`); leave the flag off to install it yourself. It also downloads MusicRadar's
free [hardware drum machine samples](https://www.musicradar.com/music-tech/samples/sampleradar-493-free-hardware-drum-machine-samples)
(Roland TR-8, Alesis HR-16, Jomox Airbase 99, Nord Drum, Arturia DrumBrute) into `tools/royalty-free/`.
Their terms allow any use in your music but forbid redistributing the samples, so recipes that use them
write to `samples/local/` (gitignored), and modules built from them (which embed their samples) shouldn't be
published. The synths are free; audio you render from them is yours.

For recorded samples, `python tools/fetch_cc0.py` downloads a curated selection (~630 MB) of three CC0
(public domain) libraries into `tools/cc0/` (gitignored): Big Rusty Drums by Karoryfer Samples (drum kit),
VSCO 2 Community Edition (orchestra, percussion, sound effects) and the Versilian Community Sample Library
(tuned percussion and more), both by Versilian Studios. Each library's folder holds its `LICENSE` and a
`SOURCE.txt`. To fetch more, add glob patterns to `LIBRARIES` in the script and rerun it; files already
present are skipped, and `--list` shows the plan with sizes. CC0 needs no attribution, but crediting the
libraries is good manners (see `samples/demo3/ATTRIBUTION.md`).

On macOS or Linux, install Surge XT normally and set `SURGE_XT_DIR` to the folder containing
`Surge XT.vst3` and `SurgeXTData`. Audio you render is yours to use. Surge itself is GPL-3 and
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
| `start`, `length` | 0, all | `file` only: seconds to skip, and seconds to keep (effects tails still ring past `length`) |
| `note` | | `patch`: the key to play, in tracker names (`C-5` = MIDI 60 = middle C). `file`: the pitch recorded in the file (default `C-5`) |
| `notes` | | a list of keys, rendering one file per key (for multisampled instruments) |
| `chord` | | a list of keys played together as one sample (root = the first) |
| `phrase` | | `{bpm, notes: [[note, start_beat, length_beats, velocity?], ...], length?, root?}`: a whole sequence as one sample, to chop in the song with `Oxx` |
| `velocity` | 100 | MIDI velocity 1–127 |
| `hold` | 1.0 | seconds the key is held |
| `tail` | 0.5 | seconds recorded after release (for release and effects tails) |
| `root_offset` | 0 | semitones from the key played to the pitch heard (use -12 for patches that sound an octave down) |
| `params` | | `{parameter_name: value}` plugin parameter overrides (Surge names: `surge-params`; Dexed uses DX7 names like `op1_output_level`, `algorithm`) |
| `mono` | false | mix to mono (drums, basses, leads); keep stereo for pads |
| `normalize` | none | peak level in dBFS (e.g. `-1.0`) |
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

Every sample needs exactly one of `patch` or `file`. `file` samples take `note` (never `notes`, `chord` or
`phrase`); `hold`, `velocity` and `params` only apply to patches.

## Printed effects (`fx:`)

```yaml
  kalimba:
    file: "../tools/cc0/vcsl/Idiophones/Plucked Idiophones/Kalimba, Kenya/Mbira6_Normal_MainSpirit_B3_k12_vl3_rr2.wav"
    note: B-4
    fx_tail: 1.5
    fx:
      - delay: {delay_seconds: 0.36, feedback: 0.35, mix: 0.3}     # a dotted 8th at 125 BPM
      - reverb: {room_size: 0.6, wet_level: 0.25, dry_level: 0.85}
      - resample: {target_sample_rate: 16000}                      # lo-fi: 16 kHz bandwidth and aliasing
      - bitcrush: {bit_depth: 8}                                   # lo-fi: 8-bit quantisation noise
```

Each item is one effect: a name, or `{name: {parameter: value}}`. The effects are
[pedalboard](https://spotify.github.io/pedalboard/reference/pedalboard.html)'s built-in plugins, and the
parameters are their constructor arguments. Names are case-insensitive, with or without underscores
(`highpass_filter` = `HighpassFilter`). Useful ones:

| effect | typical parameters |
|---|---|
| `reverb` | `room_size` 0–1, `damping`, `wet_level`, `dry_level`, `width` |
| `delay` | `delay_seconds`, `feedback`, `mix` |
| `chorus` | `rate_hz`, `depth`, `centre_delay_ms`, `feedback`, `mix` |
| `phaser` | `rate_hz`, `depth`, `mix` |
| `distortion` | `drive_db` |
| `compressor` | `threshold_db`, `ratio`, `attack_ms`, `release_ms` |
| `highpass_filter`, `lowpass_filter` | `cutoff_frequency_hz` |
| `ladder_filter` | `cutoff_hz`, `resonance`, `drive` (a 12 dB low-pass) |
| `resample` | `target_sample_rate`: downsample and back with a windowed sinc, for early-sampler bandwidth (band-limited: it removes what is above the new Nyquist frequency rather than aliasing it) |
| `bitcrush` | `bit_depth`: 8 gives the hiss and grit of 8-bit samples |
| `gain`, `limiter`, `pitch_shift` | `gain_db`; `threshold_db`; `semitones` |

The order of processing is: source → `start`/`length` → peak-normalise to -1 dBFS → pad with `fx_tail`
seconds of silence → `fx` → `mono` → `reverse` → trim silence → `loop` → `fade_out` → `normalize`/`gain`.
The input is normalised first, so `bitcrush` and `distortion` act the same whatever the recording level.
A mono source becomes stereo before the effects unless `mono: true`, so reverb and chorus get their width.
Put `resample` and `bitcrush` last, so the reverb tail gets the same grit as the dry sound.

`demo3/kit.yaml` is a complete example: an analog bass and a looped lead cut from the same patch, a string-machine
chord for gating, a DX7 string pad and two CC0 cymbals, each resampled to the rate its role has in the UT99 modules
(11 kHz pads, 22 kHz bass and lead).
