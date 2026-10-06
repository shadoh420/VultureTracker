"""Merge transcribed stems into one MIDI file on the recording's own beat grid, for `vulturetracker import`.

Runs in the basic-pitch environment that `tools/transcribe_audio.py --setup` makes (it needs librosa, pretty_midi and
soundfile); transcribe_audio.py calls it, and it can be run alone:

  <env>/bp/Scripts/python tools/stems_to_midi.py --stems STEMS --midi-dir MIDI --out song.mid [--notes yourmt3]
                                                 [--bass yin] [--drums-midi drums.mid] [--grid 4] [--beats-from drums]

STEMS holds <stem>.wav files (bass, drums, other, guitar, vocals, piano: those present). MIDI holds the notes of the
pitched ones: basic-pitch's <stem>_basic_pitch.mid, or with --notes yourmt3 <stem>_yourmt3.mid (every instrument
YourMT3+ heard in that stem, as one part; a stem it found nothing in falls back to basic-pitch's, and says so). The beats are tracked in one stem (drums by default), every note is snapped
to `grid` steps a beat following those beats (so a drifting tempo stays on the grid), and the song is shifted by whole
beats so nothing starts before its first row. The bass is from --notes too, or (--bass yin) one line tracked by
VultureTracker's YIN; the drums come from a drum MIDI in General MIDI keys (ADTOF), else from three band onset detectors.
Writes `out` and `out` with .json ({"bpm", "offset_ms"}: how much later the song starts than the recording)."""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PITCHED = [("other", 89), ("guitar", 30), ("vocals", 52), ("piano", 0)]  # stem, General MIDI program of its placeholder
GM_KIT = {35: 36, 36: 36, 38: 38, 40: 38, 42: 42, 44: 42, 46: 46, 45: 45, 47: 47, 48: 48, 49: 49, 51: 51, 57: 49}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stems", required=True, type=Path, help="folder with <stem>.wav files")
    ap.add_argument("--midi-dir", required=True, type=Path, help="folder with basic-pitch's <stem>_basic_pitch.mid files")
    ap.add_argument("--out", required=True, type=Path, help="the MIDI file to write")
    ap.add_argument("--notes", choices=["basic-pitch", "yourmt3"], default="basic-pitch", help="where the pitched stems' notes come from")
    ap.add_argument("--bass", choices=["notes", "yin"], default="notes", help="the bass from --notes, or one line by YIN")
    ap.add_argument("--drums-midi", type=Path, help="drum MIDI in General MIDI keys (ADTOF); default: band onsets of drums.wav")
    ap.add_argument("--grid", type=int, default=4, help="steps a beat the notes snap to (4: sixteenths)")
    ap.add_argument("--beats-from", default="drums", help="the stem the beats are tracked in")
    args = ap.parse_args()
    for f in (args.stems, args.midi_dir):
        if not f.is_dir():
            ap.error(f"no such folder: {f}")
    if not (args.stems / f"{args.beats_from}.wav").is_file():
        ap.error(f"{args.stems / (args.beats_from + '.wav')} is missing: choose --beats-from another stem")
    if args.drums_midi and not args.drums_midi.is_file():
        ap.error(f"no such file: {args.drums_midi}")
    if args.grid < 1:
        ap.error("--grid must be 1 or more")
    try:
        import librosa  # noqa: F401
        import pretty_midi  # noqa: F401
        import soundfile  # noqa: F401
    except ImportError as e:
        sys.exit(f"{e.name} is missing: run this with the basic-pitch environment's python (tools/transcribe_audio.py --setup)")
    merge(args)


def beat_period(beats):
    """The slope of a line through the beat times, each beat counted in whole median intervals from the one before (a
    skipped beat counts two). The median interval alone comes in whole frames of librosa's 23 ms: 130 BPM read 129.2."""
    import numpy as np
    d = np.diff(beats)
    k = np.concatenate([[0], np.cumsum(np.maximum(1, np.round(d / np.median(d))))])
    return float(np.polyfit(k, beats, 1)[0])


def merge(args):
    import librosa
    import numpy as np
    import pretty_midi as pm
    import scipy.signal as ss
    import soundfile as sf
    sys.path.insert(0, str(REPO))
    from vulturetracker import dsp

    y, sr = librosa.load(args.stems / f"{args.beats_from}.wav", sr=22050)
    _, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    if len(beats) < 2:
        sys.exit(f"no beats found in {args.beats_from}.wav: choose --beats-from another stem")
    period = beat_period(beats)
    idx = np.arange(len(beats))

    def to_beat(t):  # seconds -> beats, following the detected beats (drift included), extrapolated at the ends
        if t < beats[0]:
            return (t - beats[0]) / period
        if t > beats[-1]:
            return idx[-1] + (t - beats[-1]) / period
        return float(np.interp(t, beats, idx))

    shift = int(np.ceil(-to_beat(0)))  # whole beats so nothing starts before 0
    step = 1 / args.grid
    q = lambda t: round((to_beat(t) + shift) * args.grid) / args.grid  # noqa: E731
    out = pm.PrettyMIDI(initial_tempo=60 / period)

    def add(name, prog, notes, drum=False):  # notes: (start s, end s, pitch, velocity) in the recording's time
        inst, seen = pm.Instrument(prog, is_drum=drum, name=name), set()
        for a, b, p, v in sorted(notes, key=lambda n: (n[0], -n[3])):
            qa = q(a)
            qb = qa + step if drum else max(q(b), qa + step)
            if (qa, p) not in seen:  # one note per pitch per step
                seen.add((qa, p))
                inst.notes.append(pm.Note(int(v), int(p), qa * period, qb * period))
        out.instruments.append(inst)
        print(f"{name}: {len(inst.notes)} notes")

    def basic_pitch(stem, min_dur, min_vel):  # basic-pitch's blips dropped: very short or very quiet notes
        m = pm.PrettyMIDI(str(args.midi_dir / f"{stem}_basic_pitch.mid"))
        return [(n.start, n.end, n.pitch, n.velocity) for i in m.instruments for n in i.notes
                if n.end - n.start >= min_dur and n.velocity >= min_vel]

    def notes_of(stem, min_dur, min_vel):
        f = args.midi_dir / f"{stem}_yourmt3.mid"
        if args.notes == "yourmt3":
            found = [(n.start, n.end, n.pitch, n.velocity) for i in pm.PrettyMIDI(str(f)).instruments if not i.is_drum
                     for n in i.notes] if f.is_file() else []
            if found:
                return found
            print(f"{stem}: YourMT3+ found no notes, basic-pitch's used")
        return basic_pitch(stem, min_dur, min_vel) if (args.midi_dir / f"{stem}_basic_pitch.mid").is_file() else []

    def silent(stem):  # an empty stem: basic-pitch normalizes it and finds notes in the leakage
        rms = float(np.sqrt(np.mean(sf.read(args.stems / f"{stem}.wav")[0] ** 2)))
        if rms < 10 ** (-50 / 20):
            print(f"{stem}: skipped, the stem is {20 * np.log10(rms + 1e-12):.0f} dBFS")
        return rms < 10 ** (-50 / 20)

    def yin_line(path, fmin=30.0, fmax=500.0, hop_s=0.01):
        """One line: YIN per 10 ms frame, the recording's tuning offset taken out, runs of one note of 60 ms or more,
        split at the stem's onsets (a repeated note), ended where the level falls 30 dB under the run's peak."""
        x, rate = sf.read(path, always_2d=True)
        x = x.T
        m = x.mean(0)
        hop, size = int(rate * hop_s), int(2.5 * rate / fmin)
        starts = np.arange(0, len(m) - size, hop)
        lvl = np.array([np.sqrt(np.mean(m[s:s + size] ** 2)) for s in starts])
        loud = lvl > lvl.max() * 10 ** (-40 / 20)
        hz = np.full(len(starts), np.nan)
        for i, s in enumerate(starts):
            if loud[i]:
                h, conf = dsp.yin(m[s:s + size], rate, fmin, fmax)
                if h and conf > 0.8:
                    hz[i] = h
        midi = 69 + 12 * np.log2(hz / 440)
        tune = np.nanmedian(midi - np.round(midi))  # the recording's tuning, in semitones
        note = np.round(midi - tune)
        centre = (starts + size / 2) / rate
        cuts = {int(round(o / rate / hop_s)) for o in dsp.onsets(x, rate, sensitivity=60)[1:]}
        notes, i = [], 0
        while i < len(note):
            if np.isnan(note[i]):
                i += 1
                continue
            j = i + 1
            while j < len(note) and j not in cuts and (note[j] == note[i] or (
                    np.isnan(note[j]) and j + 1 < len(note) and note[j + 1] == note[i])):
                j += 1
            if j - i >= 6:
                pk = lvl[i:j].max()
                quiet = lvl[i:j] < pk * 10 ** (-30 / 20)
                k = i + int(np.argmax(quiet)) if quiet.any() else j
                notes.append((centre[i] - size / 2 / rate, centre[max(i, k - 1)], int(note[i]),
                              int(np.clip(40 + 87 * pk / lvl.max(), 40, 127))))
            i = j
        print(f"bass tuning offset {tune * 100:+.0f} cents")
        return notes

    if (args.stems / "bass.wav").is_file() and not silent("bass"):
        add("bass", 33, yin_line(args.stems / "bass.wav") if args.bass == "yin" else notes_of("bass", 0.10, 45))
    for stem, prog in PITCHED:
        if (args.stems / f"{stem}.wav").is_file() and not silent(stem):
            add(stem, prog, notes_of(stem, 0.12, 40 if stem == "other" else 45))
    if args.drums_midi:
        add("drums", 0, [(n.start, n.end, GM_KIT[n.pitch], n.velocity) for i in pm.PrettyMIDI(str(args.drums_midi)).instruments
                         for n in i.notes if n.pitch in GM_KIT], drum=True)
    elif (args.stems / "drums.wav").is_file():  # three bands -> kick 36, snare 38, hat 42 (crude)
        d, _ = librosa.load(args.stems / "drums.wav", sr=sr)
        hits = []
        for lo, hi, key, thr in [(20, 150, 36, 0.25), (150, 2500, 38, 0.3), (6000, 11000, 42, 0.3)]:
            env = librosa.onset.onset_strength(y=ss.sosfilt(ss.butter(4, [lo, hi], "bandpass", fs=sr, output="sos"), d), sr=sr)
            env = env / (env.max() or 1)
            for f in librosa.onset.onset_detect(onset_envelope=env, sr=sr, delta=thr, units="frames"):
                t = librosa.frames_to_time(f, sr=sr)
                hits.append((t, t + 0.1, key, int(60 + 60 * min(1, env[f]))))
        add("drums", 0, hits, drum=True)
    out.instruments = [i for i in out.instruments if i.notes]
    if not out.instruments:
        sys.exit("nothing to write: no stems with notes")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.write(str(args.out))
    info = {"bpm": round(60 / period, 3), "offset_ms": round((to_beat(0) + shift) * period * 1000)}
    args.out.with_suffix(".json").write_text(json.dumps(info), encoding="utf-8")
    print(f"{info['bpm']:g} BPM; the song starts {info['offset_ms']} ms after the recording")


if __name__ == "__main__":
    main()
