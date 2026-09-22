"""Measures rendered sound candidates so picks can be made against targets instead of by ear: per WAV the sounding
pitch, spectral centroid, attack, decay, flatness, the hold level (RMS from 1.5 to 2.5 s against the peak, for
sustained sounds), movement (the spread of the 100 ms RMS over the hold, i.e. LFO or chorus motion) and the nine
octave bands from 31 Hz. Run: python suite/nadir/measure.py [samples/local/nadir-cand] [prefix]
"""
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from vulturetracker.gui import measure  # noqa: E402
from vulturetracker.wavload import read_wav  # noqa: E402


def hold_stats(path):
    w = read_wav(path)
    x = np.asarray(w.channels[0], float) / 32768
    hop = w.rate // 10
    n = len(x) // hop
    if n < 3:
        return None, None
    env = np.sqrt((x[: n * hop] ** 2).reshape(n, hop).mean(axis=1)) + 1e-9
    a, b = min(n - 1, 15), min(n, 25)
    if b - a < 2:
        return None, None
    seg = 20 * np.log10(env[a:b])
    return round(float(seg.mean() - 20 * math.log10(env.max())), 1), round(float(seg.std()), 2)


def main(folder, prefix=""):
    rows = []
    for p in sorted(Path(folder).glob(f"{prefix}*.wav")):
        m = measure(p)
        hold, move = hold_stats(p)
        bands = "".join(f"{int(round(9 * b)):d}" for b in (m["bands"] or []))
        rows.append((p.stem, m["duration"], m["pitch"], m["cents"], m["centroid"], m["attack"], m["decay"], m["flatness"], hold, move, bands))
    print(f"{'name':16s} {'dur':>5s} {'pitch':>6s} {'cent':>5s} {'centHz':>6s} {'atk ms':>6s} {'decay s':>7s} {'flat dB':>7s} {'hold dB':>7s} {'move':>5s}  bands 31..8k")
    for name, dur, pitch, cents, cen, atk, dec, flat, hold, move, bands in rows:
        print(f"{name:16s} {dur:5.2f} {str(pitch):>6s} {str(cents):>5s} {cen or 0:6.0f} {1000 * (atk or 0):6.0f} "
              f"{dec if dec is not None else float('nan'):7.2f} {10 * math.log10(flat) if flat else float('nan'):7.1f} "
              f"{hold if hold is not None else float('nan'):7.1f} {move if move is not None else float('nan'):5.2f}  {bands}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "samples" / "local" / "nadir-cand"), sys.argv[2] if len(sys.argv) > 2 else "")
