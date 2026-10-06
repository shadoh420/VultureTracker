"""Score a transcription against the recording it came from: the sound (a log-mel delta per bar) and the notes (each
part's notes against its stem's constant-Q peaks, the drums against the drum stem's onsets), with a picture.

Runs in the basic-pitch environment that `tools/transcribe_audio.py --setup` makes (librosa, pretty_midi, matplotlib):

  <env>/bp/Scripts/python tools/transcription_diff.py --orig rec.wav --render song.wav --midi song.mid
                                                      --stems STEMS --png diff.png [--offset-ms 372] [--label v2]

STEMS is a folder of <part>.wav (the part names of the MIDI's instruments: bass, other, drums ...) or one file that every
part is scored against (the recording itself: then versions made from different stems compare fairly). The offset is how
much later the song starts than the recording (stems_to_midi.py writes it beside the MIDI; read from there when left out).

The scores are lenient proxies, for ranking versions against each other, not accuracy: "precision" is the share of a
part's notes whose pitch is a peak in the stem while it sounds (a wrong note can coincide with another instrument's peak),
"recall" the share of the stem's peaks a note covers (against a whole mix it counts drums and noise as notes to find).
The sound delta compares sound: placeholder sounds differ even where every note is right. Prints one JSON line."""
import argparse
import json
import sys
from pathlib import Path

SR, HOP = 22050, 512
LO, NB = 24, 84  # constant-Q bins: MIDI 24 (C1) and 84 semitones up


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--orig", required=True, type=Path, help="the recording (WAV)")
    ap.add_argument("--render", required=True, type=Path, help="the transcription rendered (WAV)")
    ap.add_argument("--midi", required=True, type=Path, help="the transcription's MIDI file (its instrument names = the parts)")
    ap.add_argument("--stems", required=True, type=Path, help="folder of <part>.wav, or one WAV to score every part against")
    ap.add_argument("--png", required=True, type=Path, help="the picture to write")
    ap.add_argument("--offset-ms", type=float, help="how much later the song starts than the recording (default: <midi>.json)")
    ap.add_argument("--label", default="", help="a name for this version in the picture and the JSON")
    args = ap.parse_args()
    for f in (args.orig, args.render, args.midi):
        if not f.is_file():
            ap.error(f"no such file: {f}")
    if not args.stems.exists():
        ap.error(f"no such file or folder: {args.stems}")
    if args.offset_ms is None:
        side = args.midi.with_suffix(".json")
        if not side.is_file():
            ap.error(f"--offset-ms is needed ({side} is missing)")
        args.offset_ms = json.loads(side.read_text(encoding="utf-8"))["offset_ms"]
    try:
        import librosa  # noqa: F401
        import matplotlib  # noqa: F401
        import pretty_midi  # noqa: F401
    except ImportError as e:
        sys.exit(f"{e.name} is missing: run this with the basic-pitch environment's python (tools/transcribe_audio.py --setup)")
    score(args)


def stem_peaks(y):
    """A stem's constant-Q peaks (`y` at SR, frames of HOP, bins from MIDI LO): (the peaks within 15 dB of their frame's
    loudest and over -45 dB, those of them that are no harmonic of a stronger one)."""
    import librosa
    import numpy as np
    C = librosa.amplitude_to_db(np.abs(librosa.cqt(y, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(LO), n_bins=NB)), ref=np.max)
    fmax = C.max(axis=0, keepdims=True)
    peak = (C >= np.maximum(np.roll(C, 1, 0), np.roll(C, -1, 0))) & (C > fmax - 15) & (C > -45)
    harm = np.zeros_like(peak)  # a peak an octave or a twelfth above a stronger peak is its harmonic, not a note
    harm[12:] |= peak[:-12] & (C[:-12] > C[12:])
    harm[19:] |= peak[:-19] & (C[:-19] > C[19:])
    return peak, peak & ~harm


def score(args):
    import librosa
    import matplotlib
    import numpy as np
    import pretty_midi as pm
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    off, fps = args.offset_ms / 1000, SR / HOP
    midi = pm.PrettyMIDI(str(args.midi))
    bpm = float(midi.get_tempo_changes()[1][0])

    # ---- sound: log-mel of both, the recording moved by the offset, levels matched
    a, _ = librosa.load(args.orig, sr=SR)
    b, _ = librosa.load(args.render, sr=SR)
    a = np.concatenate([np.zeros(int(off * SR)), a]) if off >= 0 else a[int(-off * SR):]
    n = min(len(a), len(b))
    a, b = a[:n], b[:n] * np.sqrt(np.mean(a[:n] ** 2) / max(np.mean(b[:n] ** 2), 1e-20))
    mel = lambda x: librosa.power_to_db(librosa.feature.melspectrogram(y=x, sr=SR, hop_length=HOP, n_mels=96), ref=1.0, top_db=None)  # noqa: E731
    A, B = mel(a), mel(b)
    floor = A.max() - 80
    A, B = np.maximum(A, floor), np.maximum(B, floor)
    D = B - A
    bar = max(1, int(round(4 * 60 / bpm * fps)))
    delta = np.array([np.abs(D[:, i:i + bar]).mean() for i in range(0, D.shape[1] - bar + 1, bar)]) if D.shape[1] >= bar else np.array([np.abs(D).mean()])

    # ---- notes: per part, precision (notes the stem holds) and recall (stem peaks a note covers)
    res, hits_bar, all_bar = {}, np.zeros(len(delta)), np.zeros(len(delta))
    for inst in midi.instruments:
        src = args.stems if args.stems.is_file() else args.stems / f"{inst.name}.wav"
        if not src.is_file():
            continue
        y, _ = librosa.load(src, sr=SR)
        if inst.is_drum:
            env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
            ref = librosa.onset.onset_detect(onset_envelope=env, sr=SR, hop_length=HOP, units="time")
            est = np.unique(np.round(np.array([nt.start - off for nt in inst.notes]), 3))
            near = lambda t, s: bool(len(s)) and np.min(np.abs(s - t)) <= 0.05  # noqa: E731
            p = float(np.mean([near(t, ref) for t in est])) if len(est) else 0.0
            r = float(np.mean([near(t, est) for t in ref])) if len(ref) else 0.0
            for t in est:
                k = int((t + off) * fps) // bar
                if 0 <= k < len(delta):
                    all_bar[k] += 1
                    hits_bar[k] += near(t, ref)
        else:
            peak, ref = stem_peaks(y)
            roll, ok, tot = np.zeros_like(peak), 0, 0
            for nt in inst.notes:
                i, j, k = int((nt.start - off) * fps), int((nt.end - off) * fps), nt.pitch - LO
                if not 0 <= k < NB or j <= max(0, i):
                    continue
                good = peak[k, max(0, i):j].mean() >= 0.5  # the stem peaks at the note's own pitch for half of it
                ok, tot = ok + good, tot + 1
                roll[k, max(0, i - 3):j + 3] = True  # 3 frames (70 ms) of quantization slack
                bk = int(nt.start * fps) // bar
                if 0 <= bk < len(delta):
                    all_bar[bk] += 1
                    hits_bar[bk] += good
            p, r = ok / max(1, tot), float((ref & roll).sum() / max(1, ref.sum()))
        res[inst.name] = {"notes": len(inst.notes), "precision": round(p, 2), "recall": round(r, 2)}
    support = np.where(all_bar > 0, hits_bar / np.maximum(all_bar, 1), np.nan)
    print(json.dumps({"label": args.label, "sound_delta_db_median": round(float(np.median(delta)), 1), "parts": res}))

    # ---- the picture
    t = np.arange(D.shape[1]) / fps
    fig, ax = plt.subplots(4, 1, figsize=(16, 11), sharex=True, gridspec_kw={"height_ratios": [2, 2, 2, 1.3]})
    ext = [0, t[-1], 0, 96]
    ax[0].imshow(A, aspect="auto", origin="lower", extent=ext, cmap="magma")
    ax[0].set_ylabel("recording (mel)")
    ax[1].imshow(B, aspect="auto", origin="lower", extent=ext, cmap="magma")
    ax[1].set_ylabel("transcription")
    im = ax[2].imshow(np.clip(D, -30, 30), aspect="auto", origin="lower", extent=ext, cmap="RdBu_r", vmin=-30, vmax=30)
    ax[2].set_ylabel("delta dB\n(red = louder in\ntranscription)")
    fig.colorbar(im, ax=ax[2], pad=0.005, fraction=0.02)
    bt = (np.arange(len(delta)) + 0.5) * bar / fps
    ax[3].plot(bt, delta, color="#c0392b", label="sound delta per bar (dB, lower = closer)")
    ax[3].set_ylabel("dB")
    a2 = ax[3].twinx()
    a2.plot(bt, support * 100, color="#2471a3", label="notes the stems hold (%)")
    a2.set_ylim(0, 100)
    a2.set_ylabel("%")
    ax[3].legend(loc="upper left", fontsize=8)
    a2.legend(loc="upper right", fontsize=8)
    ax[3].set_xlabel("seconds (song time)")
    fig.suptitle(f"{args.orig.stem} vs transcription {args.label}: "
                 + ", ".join(f"{k} P{v['precision']:.0%} R{v['recall']:.0%}" for k, v in res.items()))
    fig.tight_layout()
    args.png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.png, dpi=80)


if __name__ == "__main__":
    main()
