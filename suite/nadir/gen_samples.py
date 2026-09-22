"""Renders the additive and noise samples of Nadir into samples/nadir/ with demo4's renderer (demo4/gen_samples.py):
the sub drone (a sine with its octave and a low-passed sawtooth under it and a slow one-octave filter dip once per
loop, the loudest layer of the piece), the pulse (the same recipe with more second harmonic, played short by its
instrument envelope for the dotted single-note pulse) and the wind (a loop of pink noise under a slowly breathing
low-pass, periodic with its loop). All are designed from the description, measured from nothing.
Run: python suite/nadir/gen_samples.py
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
import demo4.gen_samples as gs  # noqa: E402
from vulturetracker.notation import parse_note  # noqa: E402
from vulturetracker.wavload import write_wav  # noqa: E402

gs.OUT = ROOT / "samples" / "nadir"
hz, saw = gs.hz, gs.saw_lowpassed

VOICES = {
    # the drone at G-1 (49 Hz): a sine, its octave 2 dB under it, the sawtooth's higher harmonics low-passed at 240 Hz
    # and 4 dB under, a 6 dB dip closing the filter one octave mid-loop; 4 s loop, whole cycles
    "drone": dict(rate=22050, partials=[(hz("G-1"), 0), (2 * hz("G-1"), -2)] + [(f, db - 4) for f, db in saw("G-1", 240)[2:]],
                  noise=-50, floor=[(300, -88), (800, -96), (2000, -100), (4000, -100)], attack=0.02, pre=0.03, loop=4.0,
                  root="G-1", f0=hz("G-1"), mod=(6.0, 1.0, 110.0), zero=True),
    # the pulse at G-2 (98 Hz): a rounder sub with a stronger second harmonic and no filter motion
    "pulse": dict(rate=22050, partials=[(hz("G-2"), 0), (hz("G-2") * 2, -9), (hz("G-2") * 3, -22), (hz("G-2") * 4, -34)],
                  noise=-54, floor=[(200, -90), (1000, -100), (4000, -100)], attack=0.004, pre=0.01, loop=1.0,
                  root="G-2", f0=hz("G-2"), zero=True),
}


def wind(rate=11025, seconds=4.0, seed=7):
    """Pink noise through a low-pass that breathes between 400 Hz and 1.6 kHz once per loop; built in the frequency
    domain on exactly the loop length so it loops without a seam."""
    n = int(rate * seconds)
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / rate)
    x = np.fft.irfft(spec / np.sqrt(np.maximum(f, 20.0)), n)          # pink
    t = np.arange(n) / rate
    fc = 800 * 2 ** np.sin(2 * np.pi * t / seconds)                     # 400..1600 Hz, one breath per loop
    # a one-pole low-pass whose cutoff moves: y += a (x - y), a = 1 - exp(-2 pi fc / rate)
    a = 1 - np.exp(-2 * np.pi * fc / rate)
    y = np.zeros(n)
    acc = 0.0
    for i in range(n):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    y = y / np.abs(y).max() * 0.89
    pcm = np.clip(y * 32767, -32768, 32767).astype(int).tolist()
    out = gs.OUT / "wind.wav"
    write_wav(out, rate, [pcm], 16, loop=(0, n, False), root_note=parse_note("C-5"))
    print(f"wrote {out.name}: {rate} Hz, {seconds:.1f} s pink-noise loop")


if __name__ == "__main__":
    gs.OUT.mkdir(parents=True, exist_ok=True)
    for name, spec in VOICES.items():
        gs.render(name, **spec)
    wind()
