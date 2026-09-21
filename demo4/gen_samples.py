"""Renders the two additive samples of demo4 into samples/demo4/: the riff voice and the sub-bass drone. Both are
designed from a description, not measured from anything: the riff is a near-sine (a fundamental with a faint
sheen of upper harmonics, the odd ones a little stronger), the drone a sine reinforced by a low-passed sawtooth
with a slow filter dip once per loop. Every partial is snapped to a whole number of cycles per loop and the noise
floor is periodic with the loop, so both loop seamlessly without a crossfade. The chord samples (beds, motif
chords, choir) are synth renders: demo4/kit.yaml. Run: python demo4/gen_samples.py
"""
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from vulturetracker.notation import parse_note  # noqa: E402
from vulturetracker.wavload import write_wav  # noqa: E402

OUT = HERE.parent / "samples" / "demo4"


def hz(note):
    return 440.0 * 2 ** ((parse_note(note) - 69) / 12)


def harmonics(note, levels_db):
    """A harmonic series at `note`: (Hz, dB) for harmonics 1.. at the given levels."""
    return [(hz(note) * (k + 1), db) for k, db in enumerate(levels_db)]


def saw_lowpassed(note, cutoff, n=16):
    """A sawtooth's harmonics (1/k) through a 2-pole low-pass at `cutoff` Hz: the classic sub-bass recipe."""
    f0 = hz(note)
    return [(f0 * k, 20 * math.log10(1 / k) - 20 * math.log10(1 + (f0 * k / cutoff) ** 2)) for k in range(1, n + 1)]


# name: rate, partials, noise RMS in dB below the tone's RMS, noise shape, attack s, loop s, WAV root note, and
# optionally pre (seconds before the loop, default = attack), f0 (loop snapped to whole cycles of it), mod (dip dB,
# filter octaves, open cutoff Hz: a slow closing once per loop) and zero phases.
VOICES = {
    # the riff: a near-sine; odd harmonics a little stronger than the even ones give it a faint hollow sheen
    "riff": dict(rate=22050, partials=harmonics("E-5", [0, -46, -38, -50, -42, -54, -46, -58]), noise=-63,
                 floor=[(100, -100), (4000, -105)], attack=0.015, pre=0.26, loop=0.5, root="E-5", f0=hz("E-5"), zero=True),
    # the drone: a sine plus a sawtooth low-passed at 300 Hz, 3 dB under it, with a 5 dB one-octave filter dip mid-loop
    "bass": dict(rate=22050, partials=[(hz("E-2"), 0)] + [(f, db - 3) for f, db in saw_lowpassed("E-2", 300)[1:]],
                 noise=-56, floor=[(500, -87), (1000, -96), (2000, -100), (4000, -99)], attack=0.01, pre=0.02, loop=3.0,
                 root="E-2", f0=hz("E-2"), mod=(5.0, 1.0, 130.0), zero=True),
}


def render(name, rate, partials, noise, floor, attack, loop, root, pre=None, f0=None, mod=None, zero=False):
    n_loop = int(round(loop * rate))
    if f0:                                                     # a whole number of fundamental cycles per loop
        n_loop = int(round(round(f0 * loop) * rate / f0))
    n_pre = int(round((attack if pre is None else pre) * rate))
    n = n_pre + n_loop
    i = np.arange(n)
    t = i / rate
    ph = (1 - np.cos(2 * np.pi * (i - n_pre) / n_loop)) / 2  # 0 at the loop points, 1 mid-loop
    rng = np.random.default_rng(sum(map(ord, name)))
    x = np.zeros(n)
    for f, db in partials:
        f = round(f * n_loop / rate) * rate / n_loop          # whole cycles per loop: the loop is seamless
        a = 10 ** (db / 20)
        if mod:
            dip, octaves, fc_open = mod
            fc = fc_open * 2 ** (-octaves * ph)                # a 2-pole low-pass closing mid-loop
            a = a * (1 + (f / fc_open) ** 4) ** 0.5 / (1 + (f / fc) ** 4) ** 0.5
        x += a * np.sin(2 * np.pi * f * t + (0.0 if zero else rng.uniform(0, 2 * np.pi)))
    if mod:
        x *= 10 ** (-mod[0] * ph / 20)
    tone_rms = np.sqrt(np.mean(x[n_pre:] ** 2))
    # The noise floor: white noise shaped by `floor`, one loop long and repeated, so it loops too.
    spec = np.fft.rfft(rng.standard_normal(n_loop))
    fr = np.fft.rfftfreq(n_loop, 1 / rate)
    fl = np.array(floor, float)
    gain_db = np.interp(np.log(np.maximum(fr, 1.0)), np.log(fl[:, 0]), fl[:, 1]) - fl[:, 1].mean()
    burst = np.fft.irfft(spec * 10 ** (gain_db / 20), n_loop)
    burst *= tone_rms * 10 ** (noise / 20) / np.sqrt(np.mean(burst ** 2))
    x += burst[(i - n_pre) % n_loop]
    x *= np.minimum(1.0, t / attack)
    x = x / np.abs(x).max() * 0.89                             # -1 dBFS
    pcm = np.clip(x * 32767, -32768, 32767).astype(int).tolist()
    out = OUT / f"{name}.wav"
    write_wav(out, rate, [pcm], 16, loop=(n_pre, n, False), root_note=parse_note(root))
    print(f"wrote {out.name}: {rate} Hz, {n / rate:.2f} s, {len(partials)} partials, loop {n_pre}-{n}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, spec in VOICES.items():
        render(name, **spec)
