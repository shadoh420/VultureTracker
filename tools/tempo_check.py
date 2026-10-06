"""Is a recording on a steady tempo grid? Its BPM, where row 0 of its 16th grid falls, and how far each stretch of it
sits off a straight grid.

Runs in the basic-pitch environment that tools/transcribe_audio.py --setup makes (librosa, soundfile):

  <env>/bp/Scripts/python tools/tempo_check.py AUDIO [--bpm 130] [--windows 8]

AUDIO is best the drum stem (stems/<model>/drums.wav in a transcribe_audio.py folder): a whole mix's beats and folds are
less clean. The first BPM is a line through librosa's beats (stems_to_midi.py's beat_period) unless --bpm gives it. The
level rises are folded over a 16th row (stems_to_song.py's fold), the whole recording and each of --windows stretches;
each stretch's fold is cross-correlated with the whole one, a line goes through those shifts, its slope is a BPM error
(taken out, and the folds made again, four times), and what is left is how far each stretch sits off the grid. The
fold's own scatter is a few ms (the mix of drum sounds changes from stretch to stretch): Track06 and Track07, both
sequenced, measured within 4 ms; a drum stem warped by 20 ms over 50 s, 21 ms. A fold whose peak stands less than 1.25
times over its mean has no clear grid at that BPM (wrong, or none to find). stems_to_song.py's hits and tempo channel
assume a steady grid; its sections are exact on any tempo."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stems_to_midi import beat_period  # noqa: E402
from stems_to_song import SR, fold, rises  # noqa: E402

STEADY_MS = 8.0  # a stretch further off the grid than this is not steady
CLEAR = 1.25  # a fold's peak over its mean under this: no clear grid


def grid_fit(x, bpm, windows=8, floor_db=30, rounds=4):
    """The 16th grid of `x` (samples x channels at SR) from a first `bpm`: (BPM, where row 0 falls in s, [(stretch
    centre s, ms off the grid)], the whole fold's peak over its mean); stretches more than `floor_db` under the
    loudest are left out."""
    import numpy as np
    t, r = rises(x)
    n = len(x) // windows
    lv = [float(np.sqrt(np.mean(x[i * n:(i + 1) * n] ** 2))) for i in range(windows)]
    use = [i for i in range(windows) if lv[i] > max(lv) * 10 ** (-floor_db / 20)]
    centre = np.array([(i + 0.5) * n / SR for i in use])
    parts = [(t >= i * n / SR) & (t < (i + 1) * n / SR) for i in use]
    for _ in range(rounds):
        p = 60 / bpm / 4
        whole = fold(t, r, p)
        bins, ref = len(whole), np.conj(np.fft.rfft(whole))
        shift = []
        for k in parts:
            c = np.fft.irfft(np.fft.rfft(fold(t[k], r[k], p)) * ref, bins)
            j = int(np.argmax(c))
            den = c[j - 1] - 2 * c[j] + c[(j + 1) % bins]
            frac = 0.5 * (c[j - 1] - c[(j + 1) % bins]) / den if den < 0 else 0.0
            shift.append(((j + frac) / bins * p + p / 2) % p - p / 2)
        shift = np.unwrap(np.array(shift) / p * 2 * np.pi) / (2 * np.pi) * p
        slope, b0 = np.polyfit(centre, shift, 1) if len(use) > 1 else (0.0, float(shift[0]))
        bpm = 15 / (p * (1 + slope))  # a stretch's fold slides by (true row - p) / p a second
    off = (shift - (b0 + slope * centre)) * 1000
    p = 60 / bpm / 4
    whole = fold(t, r, p)
    return bpm, float(np.argmax(whole)) / len(whole) * p, list(zip(centre.tolist(), off.tolist())), float(whole.max() / whole.mean())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("audio", type=Path, help="the recording, best its drum stem (anything librosa reads)")
    ap.add_argument("--bpm", type=float, help="the first BPM (default: a line through librosa's beats)")
    ap.add_argument("--windows", type=int, default=8, help="stretches the recording is folded in (2 or more)")
    args = ap.parse_args()
    if not args.audio.is_file():
        ap.error(f"no such file: {args.audio}")
    if args.windows < 2:
        ap.error("--windows must be 2 or more")
    if args.bpm is not None and not 20 <= args.bpm <= 400:
        ap.error("--bpm must be between 20 and 400")
    try:
        import librosa
        import numpy as np
    except ImportError as e:
        sys.exit(f"{e.name} is missing: run this with the basic-pitch environment's python (tools/transcribe_audio.py --setup)")
    y, _ = librosa.load(args.audio, sr=SR, mono=False)
    x = np.atleast_2d(y).T
    if len(x) < args.windows * SR * 4:
        sys.exit(f"{args.audio.name}: too short for {args.windows} stretches of 4 s or more")
    bpm = args.bpm
    if bpm is None:
        _, beats = librosa.beat.beat_track(y=x.mean(1), sr=SR, units="time")
        if len(beats) < 8:
            sys.exit(f"{args.audio.name}: librosa found {len(beats)} beats; give the BPM with --bpm")
        bpm = 60 / beat_period(beats)
        print(f"beats: {len(beats)}, a line through them at {bpm:.3f} BPM")
    fit, at0, offs, peak = grid_fit(x, bpm, args.windows)
    worst = max(abs(o) for _, o in offs)
    print(f"grid: {fit:.3f} BPM, row 0 at {at0 * 1000:.1f} ms (the fold's peak {peak:.2f} x its mean)")
    print("off the grid (ms) per stretch: " + ", ".join(f"{c:.0f} s {o:+.1f}" for c, o in offs))
    if peak < CLEAR:
        print(f"NO CLEAR GRID: the fold's peak is under {CLEAR} x its mean, so the BPM is off or the playing has no "
              "steady grid; on a mix try the drum stem, or give --bpm")
    elif worst > STEADY_MS:
        print(f"NOT steady: up to {worst:.1f} ms off a straight grid; stems_to_song.py's hits will sit off the beat there "
              "(its sections stay exact)")
    else:
        print(f"steady: every stretch within {worst:.1f} ms of the grid")


if __name__ == "__main__":
    main()
