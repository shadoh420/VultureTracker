# Audio-to-Editable-Tracker Transcription Guide

How to turn an audio recording into an editable VultureTracker song (`.yaml` -> `.it` -> `.wav`) that a listener recognizes by ear as the original performance.

This guide is written for both people and AI agents. Automated audio-to-MIDI models (Dettato, Basic Pitch, YourMT3+, ADTOF) are a fast starting point, but importing their raw MIDI straight into a tracker rarely produces a recognizable result — and lower spectrogram error alone does not predict whether a listener will recognize it. The workflow below separates *playback failures* from *transcription failures*, builds source-derived editable instruments that fit each sound archetype, and verifies every change with loudness-matched controlled listening tests.

---

## Core principles

1. **The listener's ear decides.** An agent cannot hear audio. Measure signals, compare spectrograms and envelopes, report measurements strictly as measurements, and let the human listener judge every milestone by ear.
2. **Preserve originals and baselines.** Keep the original recording, Dettato's raw MIDI (`mix/original.mid`), separated stems, and baseline previews intact in a working folder. Never overwrite prior takes.
3. **Separate playback failures from note-prediction failures.** Never assume a bad-sounding tracker preview means the MIDI notes are wrong — and never assume better instruments alone will fix wrong notes. Test those two hypotheses independently on a short common passage first.
4. **Stay editable.** Keep pattern rows as genuine editable tracker notes (no multi-bar backing audio stems hidden in sample slots). When testing a passage in a controlled comparison, cut every reusable sample **strictly outside the evaluated passage**, or synthesize it cleanly, so similarity cannot be inflated by copying the tested audio.
5. **Pass `vulturetracker.api.check()` with 0 errors and 0 warnings.** Every song must respect IT's anti-aliasing ceiling (`18 kHz` unless the song sets `module.ceiling`), pitch-down limits, loop continuity, and naming limits (`<= 25` ASCII characters for titles and sample/instrument names).

---

## Step 1: Establish the baseline and inspect the real signal

Before editing any notes or designing any samples, run the automated baseline and measure what is actually in the recording:

1. **Generate the automated baseline** (via **Transcribe audio…** in the app or `tools/transcribe_audio.py`):
   - Keep `mix/source.wav`, `mix/original.mid`, `mix/mix.yaml`, and `mix/preview.wav`.
   - Separate stems (`htdemucs_ft` into `drums.wav`, `bass.wav`, `other.wav`, `vocals.wav`) for **diagnostic inspection and clean single-note/hit extraction** — not to paste into the tracker as multi-bar backing tracks.
2. **Measure the tempo grid first.** Run `python tools/tempo_check.py <recording>` (or measure onset intervals directly) to determine:
   - True BPM and whether the performance sits on a steady grid (or drifts).
   - Exact row-0 offset (`T0`, in seconds).
   - Choose a clean IT `tempo` and `speed` with fine tick resolution. For example, at `108 BPM` with 16 rows/bar (16th-note grid), `tempo: 216, speed: 12` gives `11.57 ms` ticks — twice the resolution of `tempo: 108, speed: 6` for smooth volume envelopes, `GFF` portamento glides, and `SDx` micro-timing nudges.
   - **Tick-truncation note:** libopenmpt truncates ticks to `int(sample_rate * 2.5 / tempo)` samples (e.g., `int(44100 * 2.5 / 216) = 510` samples = `108.088 BPM` rather than `107.983 BPM`). Over a 3-minute song, align objective time-window comparisons to `row * speed * int(44100 * 2.5 / tempo)` samples rather than unshifted wall-clock seconds.
3. **Audit a short common passage (3–15 seconds) before trusting any MIDI predictions.** Measure directly from `source.wav` and the stems:
   - **Per-stem A-weighted loudness (`dBA`)** — identifies which stem actually dominates what a listener hears in that section (e.g., an `other` guitar/synth stem can carry 75%+ of perceived loudness while `bass` carries most unweighted RMS).
   - **STFT harmonic ridge tracking** — determine whether the prominent frequencies are independent notes, harmonics of one fundamental, or a moving resonant filter over a held chord. Automated transcribers routinely collapse a dark shifting texture or sweeping wah chord into 1–2 repeated MIDI notes or phantom high-tom hits.
   - **Adjacent-period waveform correlation** — distinguishes steady periodic sustains (loopable) from continuously evolving sweeps or noisy grit (which lose their identity if reduced to a 2-cycle static loop).
   - **6-band A-weighted energy distribution** (`20–100`, `100–250`, `250–600`, `600–1500`, `1500–4000`, `4000–12000 Hz`).

---

## Step 2: Run a controlled 4-clip diagnostic on one short passage

Do not rewrite a full 3-minute song before proving why the baseline failed. On one representative passage (4–6 bars, or 3–15 seconds), build four clips loudness-matched to the exact same integrated LUFS (for example `-17.00 LUFS`, avoiding clipping peaks that occur at `-14 LUFS`), separated by `0.7 s` silence gaps:

1. **Clip 1 — Original recording** (`source.wav` over the passage).
2. **Clip 2 — Automated baseline** (`mix/preview.wav` over the same passage).
3. **Clip 3 — Playback fix only** (unmodified automated MIDI notes, played through properly sampled/looped instruments with matched envelopes).
4. **Clip 4 — Playback fix + note/rhythm/envelope corrections** (corrected pitches, removed phantom drums, natural attack/sustain/decay envelopes, and matched articulation).

### Why Clip 3 matters

Standard MIDI import (`midiimport.py`) maps sustained tracks (synth strings, pads, drones, sustained bass) to short, unlooped `pluck` samples (`loops=[]`) and generic stock drums. Even when Dettato predicts reasonable pitches, unlooped plucks make held notes die immediately and sound like a choppy demake. Comparing Clip 2 -> Clip 3 -> Clip 4 tells you and the listener immediately:

- How much of the failure was **instrument/envelope playback** (Clip 2 -> Clip 3), and
- How much was **wrong notes, missed chord changes, phantom drum hits, or articulation mismatch** (Clip 3 -> Clip 4).

Cut every sample used in Clips 3 and 4 **strictly outside** the tested passage (for example, from another chorus or another bar range of the song) so the controlled comparison stays honest.

---

## Step 3: Match each sound archetype to the right editable instrument

No single sampling strategy fits every musical sound. Match the instrument architecture to what the spectrogram and waveform actually show:

### 1. Percussion and one-shot hits (`kick`, `snare`, `snare_dry`, `hat`)

- Extract clean isolated single hits (`150–350 ms`) from `drums.wav`, band-pass filtered to strip bleed (`kick: 28–5500 Hz`, `snare: 110–12000 Hz`, `hat: 800–12500 Hz`) with a `1.5–2 ms` linear fade-in and `45–85 ms` cosine fade-out.
- Map hits onto a drum kit keymap (`play_note: "C-5"`) with `stereo: true`.
- Trigger each drum voice across **round-robin channel pairs** (`Kick 1/2`, `Snare 1/2`, `Hat 1/2`) so fast consecutive hits never truncate each other's decay tails.
- Keep separate snare/hat articulations when the arrangement changes (for example, a drier restrained snare in minimal sections versus a full breakbeat snare in heavy sections).

### 2. Sustained pitched instruments (sub-bass, drones, leads, pads, vocal sustains)

- Extract a clean isolated sustained note (`1.2–2.2 s`) from its stem, band-limited to remove bleed from neighboring registers.
- Measure exact fundamental `f0` using parabolic FFT peak interpolation and set IT `c5_speed`:
  ```python
  c5_speed = int(round(sample_rate * (261.6256 / f0)))
  ```
  Remember VultureTracker's IT octave convention: **`C-5` = MIDI 60 = `C4 (261.63 Hz)`**, `C-3` = `C2 (65.41 Hz)`, `C-2` = `C1 (32.70 Hz)`.
- Build a **phase-aligned crossfaded forward loop**: search lags for the highest normalized cross-correlation against a `120–180 ms` reference window, apply a cosine crossfade across the loop boundary, and verify the seam-click metric stays low.
- **Multisample across register jumps** (e.g., `bass_c1` for `C-0..B-2` + `bass_c2` for `C-3..B-9`; `lead_c4`, `lead_e4`, `lead_f4` for wide leads). This prevents both upward anti-aliasing ceiling violations and downward interpolation images (`api.check()` warns whenever a bright sample is played more than a few semitones below its root).
- **Split dark vs bright roles into separate instruments sharing the same samples.** A brooding intro/build pad and a soaring climax lead often share the same underlying synth timbre with different filter cutoffs (`filter_cutoff: 50` vs `76`). Keeping them as separate instruments preserves macro contrast without inflating the sample bank.
- **Match natural attack, sustain, and release:** Use a `volume_envelope` with a `sustain` node, `nna: fade`, and calibrated `fadeout`. When a listener says notes *"start too quickly and don't sustain/decay naturally"*, check three concrete measurements against the original stem:
  1. Onset attack time (10% to 90% peak, in ms) -> adjust envelope attack ticks.
  2. Held sustain flatness and duration -> verify seamless loop + `sustain` node (not unlooped decay).
  3. Post-release decay time and cross-note overlap -> adjust `fadeout`, release ramp, and `nna: fade` vs `nna: cut`, plus sub-beat `SDx` tick delays if real attacks sit slightly behind the grid.

### 3. Time-varying resonant articulations (band-pass wah, phaser riffs, stutter-gated chords, bowed swells)

A common trap is trying to synthesize a sweeping band-pass guitar/synth riff from a tiny 2-cycle static loop using IT's instrument filter or DMO plugins. Know the exact engine limits up front:

- **IT's native filter (`pitch_envelope: {filter: true}`) is low-pass only.** It cannot cut frequencies *below* a moving formant peak. Attempting to model a Crybaby wah or phaser sweep with a low-pass filter produces unnatural vertical bright-to-dark pyramids and choppy volume pumping instead of continuous low-mid power-chord warmth plus slanted diagonal band-pass ribbons.
- **OpenMPT's DMO `param_eq` maps `center` (`80–16000 Hz`) linearly across `Z00–Z7F`.** That leaves only ~8 coarse frequency steps below `1100 Hz` — too stepped for smooth low-mid wah sweeps.

**What works instead — single-articulation / single-beat samples played as editable, transposable notes:**

- Cut **one single beat or articulation** (`~550–600 ms`, including a `25–30 ms` overlap tail with a `10 ms` fade-in and `30 ms` cosine fade-out) for each distinct articulation (e.g., `wah_beat_c2.wav` for a steady quarter-note wah sweep and `wah_gate_c2.wav` for a stutter-gated bar).
- Measure its root pitch `f0` via its strong harmonic (e.g., `130.8 Hz / 2` for a `C2` power chord) and set `c5_speed` accurately.
- Trigger it on the beat across **two round-robin channels** (`Wah 1` / `Wah 2`, `nna: fade`) so overlapping tails crossfade without clicks.
- **Transpose genuinely in the pattern** using tracker notes and `GFF` tone portamento (for example, `C-3` on beat 4 sliding down `-2` semitones to `A#2 .. ... GFF` on beat 4.5). This keeps every note 100% editable while preserving authentic analog band-pass notches, power-chord fifths, and real distortion texture.

### 4. Narrow tonal overtones, feedback lines, and micro-accents

When per-bar spectral inspection reveals an isolated high tonal line (such as an overdriven guitar feedback harmonic series `f0, 2*f0, 3*f0, 5*f0`) or a recurring narrow-band harmonic ping:

- Measure its exact harmonic frequency ratios, stereo balance, and beat-by-beat swell envelope.
- Either **synthesize a clean band-limited additive loop** tuned to play at `1.0x` native sample rate on its target note (zero audio copied from the passage, zero aliasing warnings) or cut a tiny isolated one-shot (`~200 ms`, band-pass filtered, mapped via `play_note: "C-5"`).
- Verify in the spectrogram that the line enters and fades on the exact bars where it actually exists (do not repeat a one-time Bar 20–21 feedback swell on Bars 24–25 if it is absent there).

---

## Step 4: Transcribe the full arrangement accurately

Once the short controlled passage passes the listener's ear, scale to the full song systematically:

1. **Section map first:** Slice the song into named 2-bar or 4-bar patterns matching musical sections (`intro_01`, `mel1_01`, `riff_01`, `beat_01`, `break_01`, `build_01`, `climax_01`, `post_01`, `outro_01`).
2. **Data-driven bass extraction:** On each 8th-note window of `bass.wav`, measure narrowband spectral peaks around candidate scale fundamentals, gate silence cleanly (`===`), track octave switches cleanly across multisampled zones, and derive note velocities (`vXX`) directly from stem RMS.
3. **Data-driven drum extraction with cross-band rejection:** Filter `drums.wav` into kick (`30–140 Hz`), snare (`220–1600 Hz`), and hat (`3.5–12 kHz`) bands. Require both an energy threshold and cross-band margin (e.g., snare midrange must clearly exceed kick low-end punch, and kick must not fire on beat-3 snare bleed) plus pre-onset rise checks to eliminate double-triggering and phantom hits.
4. **Verify melodic/harmonic lines against `other.wav` and `vocals.wav`:** Never copy automated MIDI notes blindly — verify every chord shift, counter-melody, and harmony voice against per-bar chroma and STFT peaks.
5. **Calibrate macro dynamics section by section (avoid dynamic inversion).** Automated imports commonly render quiet intros and breakdowns `+4` to `+7 dB` too loud while loud riffs and climaxes sit `-2` to `-4 dB` too quiet. Measure unweighted RMS and A-weighted RMS on every section against `source.wav`, adjust per-section velocities and dark/bright instrument assignments until every section sits within roughly `±1 dB` of the original's contrast, and cap the final render at `peak <= -1.0 dBFS` (`0` clipped samples).

---

## Step 5: Objective checks that actually catch audible failures

A single global spectrogram distance is misleading — a muddy blur can score better than a crisp transcription with a 30 ms offset. Use these targeted diagnostics together before presenting any audio to the listener:

| Metric / Visual Check | What it catches |
|---|---|
| **2D log-spectrogram correlation** (`120–3500 Hz` STFT matrix) | Captures moving wah/phaser formants, harmonic contours, and rhythmic articulation trajectories. |
| **Per-beat / per-bar 2D correlation** | Pinpoints the exact single beat or bar missing a feedback harmonic, chord shift, or accent (e.g., drops from `+0.80` to `+0.63` on one bar). |
| **A-weighted envelope correlation (`Env50`, `Env100`, `Env200`)** | Exposes choppy low-pass pumping, unlooped note decay, wrong sustain tails, and macro dynamic inversion across sections. |
| **6-band A-weighted energy balance** | Reveals missing presence (`1.5–4 kHz`), excessive harshness (`>4 kHz`), or missing warmth (`100–250 Hz`). |
| **Per-section chroma similarity + RMS delta (`dB`)** | Catches wrong pitches/chord shifts and loud-intro / quiet-climax balance errors. |
| **Multi-panel time-aligned spectrogram PNG** | Lets you visually compare Original vs Baseline vs Candidates pixel by pixel (checking vertical pyramids vs diagonal sweeps, continuous fifths, feedback lines, and drum bleed). |
| **`vulturetracker.api.check(yaml_path)`** | Enforces `0` errors, `0` warnings (anti-aliasing ceiling, pitch-down images, valid syntax, valid loops). |

When delivering clips for listening evaluation:
- Match all comparison clips to the exact same integrated LUFS (e.g., `-17.00 LUFS`) with `0` clipped samples.
- Provide both the comparison WAV, the multi-panel spectrogram PNG, and the editable `.yaml` file.
- State clearly what changed, where each sample came from, and what was measured — then iterate on whichever passage the listener flags by ear.

---

## Troubleshooting quick reference

| Symptom reported by listener or metrics | Usual root cause | Fix |
|---|---|---|
| Sounds like a "bad MIDI demake"; sustained notes die immediately | `midiimport.py` mapped held tracks to unlooped `pluck` samples (`loops=[]`) and generic stock sounds | Replace with phase-aligned seamless-loop source samples + sustained `volume_envelope` + `nna: fade` |
| Notes feel rushed, clipped, or unnatural in attack/decay | Attack ticks too short, `fadeout` too abrupt, `nna: cut` choking tails, or attacks slightly ahead of real groove | Measure onset rise time and release decay vs original stem; tune envelope attack/sustain/fadeout and use round-robin channels or `SDx` delays |
| Wah / phaser / distorted guitar riff sounds fake or choppy | Static 2-cycle loop + IT low-pass filter (cannot carve notches below the formant) or DMO `param_eq` (too few linear `Zxx` steps below `1100 Hz`) | Use single-beat articulated samples (`~550–600 ms`, cut outside the tested passage) on round-robin channels, transposed with real tracker notes + `GFF` |
| Quiet intro/breakdown is too loud; heavy climax lacks lift | One bright instrument used across all sections at flat MIDI velocities | Split dark pad (`filter_cutoff: 50`) vs bright lead (`filter_cutoff: 76`); calibrate per-section velocities against original section RMS |
| `api.check()` warns about anti-aliasing or low-note images | Bright sample pitched too far down (>3 semitones below root) or too far up (over `18 kHz` ceiling) | Multisample across registers, band-limit sample to its musical range, or raise `sample_rate: 88200` |
| Track plays one octave off in VultureTracker | Confusing scientific pitch `C4` with IT `C-4` | Remember IT `C-5` = MIDI 60 = `C4 (261.63 Hz)`; `C-3` = `C2`; `C-2` = `C1` |
| Automated drums fire phantom snares or miss ghost hats | Model bleed between kick/snare/hat or missing drum stem isolation | Extract from `drums.wav` using split frequency bands (`30–140`, `220–1600`, `3500–12000 Hz`) with cross-band rejection and round-robin pairs |
| High `1.5–4 kHz` deficit on one specific bar | Missed amp feedback harmonic series or subtle upper accent present only in certain bars | Compare per-bar `1.5–4 kHz` energy; measure exact harmonic peaks and add a clean band-limited loop or isolated accent on those bars only |
