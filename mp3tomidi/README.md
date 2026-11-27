# mp3tomidi-independent — Zero-Dependency Offline Audio-to-MIDI

`mp3tomidi/` builds a single ~`1.05 MB` offline [Cosmopolitan APE](https://justine.lol/ape.html) binary
(`build/mp3tomidi-independent`) that transcribes an MP3 or WAV file into a multi-track Standard MIDI File
(`.mid`) using pure C11 digital signal processing — **zero neural weights, zero PyTorch/Python runtime
dependencies, and zero external files**. The same compiled binary runs natively on Windows and Linux
(including WSL) and produces **byte-identical** MIDI output across platforms.

This lives on branch `cosmopolitan-mp3tomidi-independent` (clean off `main`, completely separate from
the Dettato neural model branch `cosmopolitan-mp3tomidi-enhanced`).

---

## Quick Start

### 1. Build from repository root

Requires Cosmopolitan SDK 4.0.2 unpacked under ignored `build/mp3tomidi-sdk/` and MSYS2 `bash` on
Windows (or `cosmocc` directly on Linux). **Always compile with `-O2`, never `-O3`** (to keep
floating-point evaluation deterministic and avoid over-aggressive auto-vectorization drift):

```powershell
# Windows (PowerShell)
$env:TMPDIR = "$PWD/build/mp3tomidi-sdk/tmp"
$env:Path   = 'C:\msys64\usr\bin;' + $env:Path
C:\msys64\usr\bin\bash.exe build/mp3tomidi-sdk/bin/cosmocc -O2 -std=c11 -Wall -Wextra -pthread `
  -o build/mp3tomidi-independent `
  mp3tomidi/main.c mp3tomidi/resample.c mp3tomidi/nn.c mp3tomidi/retune.c `
  mp3tomidi/midi.c mp3tomidi/tempo.c mp3tomidi/enhance.c mp3tomidi/independent.c
```

```bash
# Linux / WSL
cosmocc -O2 -std=c11 -Wall -Wextra -pthread \
  -o build/mp3tomidi-independent \
  mp3tomidi/main.c mp3tomidi/resample.c mp3tomidi/nn.c mp3tomidi/retune.c \
  mp3tomidi/midi.c mp3tomidi/tempo.c mp3tomidi/enhance.c mp3tomidi/independent.c
```

### 2. Transcribe an MP3 or WAV

```bash
./build/mp3tomidi-independent input.mp3 -o output.mid
./build/mp3tomidi-independent input.wav -o output.mid
```

On Windows PowerShell, either invoke via `bash` or Python `subprocess.run(..., executable=...)`, or
copy/rename the APE binary with a `.exe` extension (`mp3tomidi-independent.exe`) to run directly from
`cmd.exe` / PowerShell. Native WAV decoding supports 8/16/24/32-bit PCM and 32/64-bit IEEE float
(including `WAVE_FORMAT_EXTENSIBLE`) automatically by inspecting the `RIFF`/`WAVE` header.

The CLI writes a Type-1 SMF to `output.mid` and prints a single JSON summary line to stdout containing
detected BPM, tuning offset, note/drum counts, track list, GM program assignments, and wall-clock time.

### 3. CLI Reference

| Command / Flag | Description |
|---|---|
| `INPUT.{mp3\|wav} -o OUTPUT.mid` | Transcribe MP3 or WAV to multi-track MIDI (default `--mode independent`). |
| `--no-cc74` | Disable `CC74` (Brightness) controller automation. |
| `--enhance-midi INPUT.{mp3\|wav} BASE.mid -o OUT.mid` | Apply audio-driven dynamics/CC calibration and cleanup to an existing MIDI. |
| `--hybrid-midi INPUT.{mp3\|wav} BASE.mid -o OUT.mid` | Fuse an existing MIDI with pure-DSP HPSS verification and bass/mid rescue. |
| `--tempo-test INPUT.{mp3\|wav}` | Estimate BPM, initial BPM, row-0 phase, clarity, and grid steadiness (JSON). |
| `--retune-test INPUT.{mp3\|wav}` | Estimate A440 tuning deviation in cents and resample ratio (JSON). |
| `--inspect INPUT.{mp3\|wav}` | Report source sample rate, channels, decoded frame count, and mono RMS (JSON). |
| `--help` | Show CLI usage help. |

Environment variable: `MP3TOMIDI_THREADS=<N>` overrides automatic CPU thread-pool sizing.

---

## How the Pipeline Works

### Plain-English Overview

1. **Decode & tune:** Reads the MP3 straight into memory (`vendor/dr_mp3.h`), mixes to mono, measures if
   the song is slightly sharp or flat relative to standard A440 tuning (`retune.c`), and gently resamples
   so every note lines up on exact semitone centers.
2. **Find drums first:** Splits the full-rate audio into fine low-frequency slices and crisp mid/high
   slices (`transcribe_drums_dsp`) so it detects both acoustic/808 kicks and downward-sweeping synth
   kicks right at impact, separates real snares from low thumps and cymbal bleed, distinguishes closed
   hats, open hats, and crashes, and automatically stays silent on drumless harmonic/ambient recordings
   by gating band percussive peaks against total signal energy and wire-snap percussiveness.
3. **Subtract drum ring before reading melody & chords:** Automatically learns the song's own average
   kick and snare body resonance from its detected hits (`subtract_drum_class_template`) — measuring
   local background from non-hit gaps across `±1.44 s`, splitting deep-sub (`35–95 Hz`) from kick-body
   (`95–165 Hz`), and scaling by linear hit amplitude — then subtracts that repeating drum ring from
   the low/mid spectrograms without hardcoding any pitches or erasing sustained bass or chords.
4. **Separate notes & chords across three zoom levels:** Computes long (`8192`-pt), medium (`2048`-pt),
   and short (`1024`-pt) STFTs with 2D harmonic/percussive separation (`hpss_worker`), subtracting only
   the *sustained* harmonic wash so drum hits don't punch holes in held chords. An iterative pitch
   extractor (`pitch_frame_worker`) peels off up to 8 simultaneous voices per frame from bass upward while
   preserving layered mid-register chord octaves/fifths and rejecting high overtone ghosts and blurry
   broadband reverb/noise shimmer via narrowband peak-to-shoulder sharpness gating.
5. **Track note holds & repeated attacks:** A 2-state Viterbi decoder (`decode_pitched_notes`) tracks
   smooth note holds, bridges brief masking dropouts in mid-register chords (`45..64`) when the raw
   harmonic envelope stays steady, sharpens `8192`-pt pre-onset lead-in edges across Bass & Mid (`<= C#4`),
   and splits repeated attacks via a parallel short-window un-HPSS detector without chopping up sustained
   or chorused pads.
6. **Assign roles, tempo & dynamics:** Clusters surviving notes into Bass, Mid/Chords, and High/Lead
   tracks with automatic GM instrument matching, estimates tempo with a duple-subdivision autocorrelation
   comb + 16th-note phase-fold refinement (`tempo.c`), and writes audio-driven velocity, `CC7`, `CC11`,
   and `CC74` curves (`enhance.c`, `midi.c`).

### Source Layout

| File | Role |
|---|---|
| `mp3tomidi/main.c` | CLI entry point, MP3 decoding (`vendor/dr_mp3.h`), JSON reporting |
| `mp3tomidi/independent.c`, `.h` | Pure-DSP drum transcriber, unsupervised drum template subtraction, tri-res HPSS, multi-pitch salience & cancellation, Viterbi HMM + repeated-note re-articulation, role/GM assignment |
| `mp3tomidi/tempo.c`, `.h` | 4-band log-flux onset envelope, drum-reinforced autocorrelation tempogram (`sigma=0.80`), 4-round 16th-note phase-fold refinement |
| `mp3tomidi/retune.c`, `.h` | Chroma-based A440 tuning deviation estimator and retune resampler |
| `mp3tomidi/resample.c`, `.h` | Kaiser-windowed sinc resampler |
| `mp3tomidi/enhance.c`, `.h` | Orthogonal audio-driven `CC7`/`CC11`/`CC74` and velocity calibration |
| `mp3tomidi/midi.c`, `.h` | Standard Type-1 MIDI reader & writer |
| `mp3tomidi/nn.c`, `.h` | Cross-platform pthread worker pool (`nn_parallel_for`) and SIMD math helpers |
| `mp3tomidi/check_independent.py` | End-to-end Windows == WSL Linux byte-identical parity check |

---

## Verification & Timbre-Free Symbolic Benchmarking

> **Runtime vs. Developer Test Tools:** Running `mp3tomidi-independent` itself to transcribe an `.mp3`
> or `.wav` into `.mid` has **zero runtime dependencies** — no Python, no `ffmpeg`, no DLLs, and no
> external files (MP3 decoding is compiled in via `vendor/dr_mp3.h`, and RIFF/WAVE decoding is built into
> `main.c`). Python (and optional `ffmpeg` only if also testing `.mp3` re-encoding from a `.wav`) is used
> **only** by the optional developer verification and grading harnesses listed below.

SoundFont GM audio renders mix MIDI instrument timbre mismatch into audio comparisons and obscure real
note/drum errors. Evaluate changes strictly in **timbre-free symbolic form** using:

- **`mp3tomidi/check_independent.py`** — verifies JSON metadata, MIDI structure, and Windows vs WSL Linux
  byte-for-byte determinism on native `.wav` directly (zero `ffmpeg` needed; automatically also tests
  `.mp3` when `dist/ffmpeg.exe` is present or `--ffmpeg` is passed):
  ```powershell
  tools/transcribe-env/bp/Scripts/python.exe mp3tomidi/check_independent.py build/mp3tomidi-independent `
    --wav demo4/vantage.wav --start-s 12.0 --seconds 12.0
  ```
- **`tools/symbolic_diff.py`** — renders canonical 16th-note tracker patterns (`.pat.txt`,
  `side-by-side.pat.txt`, unified `.pat.diff`), bar-aligned ASCII bass/guitar/drum tablature (`.tab.txt`),
  multi-voice ABC notation (`.abc`), and exact MIR metrics (`symbolic-metrics.json`: Note Onset+Pitch F1
  @ 50 ms, 20 ms Piano-Roll Frame Pitch & Chroma F1 overall and by Bass/Mid/High register, Drum Onset F1
  @ 35 ms overall & Kick/Snare/Hat) against either exact VultureTracker `.yaml` ground truth or an
  acoustic CQT ridge reference (`--audio`).
- **`tools/mp3tomidi_bench.py`** — runs the compiled binary and `tools/symbolic_diff.py` across the demo
  benchmark suite (`iron_relay_full`, `iron_relay_bars7_14`, `vantage_12_24`) plus any optional local
  audio slice passed via CLI flags:
  ```powershell
  # Built-in demo targets
  tools/transcribe-env/bp/Scripts/python.exe tools/mp3tomidi_bench.py --tag my_run

  # Single demo target
  tools/transcribe-env/bp/Scripts/python.exe tools/mp3tomidi_bench.py --only vantage_12_24 --tag quick

  # Include an extra local recording (never hardcoded in git)
  tools/transcribe-env/bp/Scripts/python.exe tools/mp3tomidi_bench.py --tag full `
    --extra-name clip --extra-mp3 PATH/TO/AUDIO.mp3 --extra-wav PATH/TO/REF.wav `
    --extra-bpm 120 --extra-start-s 0 --extra-duration-s 30
  ```

---

## Verified Benchmark Snapshot (2026-11-27, Pass 2)

Measured on `build/mp3tomidi-independent` (`1.07 MB` / `1,124,550` bytes, APE sha256 `eab78eae7ec300e3`,
WIN == WSL byte-identical on `demo4/vantage.yaml` 12–24 s for both `.mp3` [`3,712` bytes, sha256
`b6433ab9279bfd0a`] and native `.wav` [`3,725` bytes, sha256 `80e6506bbd75451c`]):

| Target | Ground Truth | NotePitch F1 (R) | FrmPitch F1 | FrmChroma F1 | Bass / Mid / High | Drums F1 (K / S / H) | CPU |
|---|---|---|---|---|---|---|---|
| `demo2/iron_relay.yaml` (full 54.92 s) | Exact YAML | `0.307` (`0.46`) | `0.685` | `0.788` | `0.74 / 0.70 / 0.54` | `0.908` (`0.92 / 0.51 / 0.98`) | `1.55 s` |
| `demo2/iron_relay.yaml` (Bars 7–14) | Exact YAML | `0.325` (`0.53`) | `0.666` | `0.767` | `0.71 / 0.72 / 0.26` | `0.888` (`0.93 / 0.49 / 0.97`) | — |
| `demo4/vantage.yaml` (`12..24 s`) | Exact YAML | `0.437` (`0.33`) | `0.695` | `0.726` | `0.62 / — / 0.85` | `0.969` (`— / 0.80 / 0.99`) | `0.40 s` |
| Private 4:19 test track (Bars 104–113) | Acoustic CQT | `0.177` (`0.12`) | `0.482` | `0.568` | `0.49 / 0.56 / 0.29` | `0.604` (`0.35 / 0.50 / 0.84`) | `7.93 s` |
| Private 2:39 dark-ambient cue (`30..46 s` / full) | Acoustic CQT | `0.170` / `0.174` | `0.424` / `0.383` | `0.632` / `0.572` | `0.72 / — / 0.27` | `0` phantom drums (`K=0 S=0 H=0`) | `5.86 s` |
