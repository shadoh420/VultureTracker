"""Adds a noise floor to the synth samples of Nadir, in place, and makes the riff voice from demo4's near-sine.

Plain synth renders have a line spectrum: nothing between the harmonics, 60-80 dB below them. The sounds of the era were
sampled from hardware through mixers and effects and carry hiss and spectral smear between the partials (their
spectral flatness sits around -20 to -30 dB; a plain patch measures -60 to -80), and the difference reads as chiptune.
This script shapes white noise by each sample's own long-term spectrum (so the hiss is the colour of the sound), scales
it a set number of dB under the tone, makes it periodic with the loop for looped samples and follows the amplitude
envelope for one-shot samples, and writes the result back with the same loop and root.
Run: python suite/nadir/gen_floor.py [names...]   (after `synth suite/nadir/kit.yaml`; running it twice on a sample adds
the floor twice, so re-render first; names limit it to the samples just re-rendered)
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from vulturetracker.notation import format_note  # noqa: E402
from vulturetracker.wavload import read_wav, write_wav  # noqa: E402

OUT = ROOT / "samples" / "nadir"
# sample -> dB of noise under the tone (RMS over RMS); looped samples get a loop-periodic floor
FLOORS = {"beda_g": -28, "beda_c": -28, "bedb_bb": -28, "bedb_g": -28, "choir": -24, "choir_hi": -24, "arp": -34,
          "seq": -30, "lead": -30, "riff": -32}
RIFF_SOURCE = ROOT / "samples" / "demo4" / "riff.wav"


def envelope_spectrum(x, rate, n=2048):
    """The sample's long-term power spectrum, smoothed over a third of an octave, on an n-point grid."""
    hop = n // 2
    frames = max(1, (len(x) - n) // hop)
    win = np.hanning(n)
    P = np.zeros(n // 2 + 1)
    for i in range(frames):
        P += np.abs(np.fft.rfft(x[i * hop: i * hop + n] * win)) ** 2
    f = np.fft.rfftfreq(n, 1 / rate)
    S = np.zeros_like(P)
    for k in range(1, len(f)):
        lo, hi = f[k] * 2 ** (-1 / 6), f[k] * 2 ** (1 / 6)
        sel = (f >= lo) & (f <= hi)
        S[k] = P[sel].mean()
    S[0] = S[1]
    return f, S


def shaped_noise(length, rate, f, S, seed):
    rng = np.random.default_rng(seed)
    spec = np.fft.rfft(rng.standard_normal(length))
    fr = np.fft.rfftfreq(length, 1 / rate)
    gain = np.sqrt(np.interp(fr, f, S))
    gain[fr < 40] = 0
    return np.fft.irfft(spec * gain, length)


def add_floor(path, db):
    w = read_wav(path)
    x = np.asarray(w.channels[0], float) / 32768
    rate = w.rate
    f, S = envelope_spectrum(x, rate)
    if w.loops:
        start, end = w.loops[0][0], w.loops[0][1]
        n_loop = end - start
        burst = shaped_noise(n_loop, rate, f, S, seed=len(x))
        noise = burst[(np.arange(len(x)) - start) % n_loop]
        tone_rms = np.sqrt(np.mean(x[start:end] ** 2))
    else:
        noise = shaped_noise(len(x), rate, f, S, seed=len(x))
        hop = max(1, rate // 100)
        env = np.sqrt(np.convolve(x * x, np.ones(hop) / hop, mode="same"))
        noise *= env / (env.max() + 1e-9)
        tone_rms = env.max()
    noise *= tone_rms * 10 ** (db / 20) / (np.sqrt(np.mean(noise ** 2)) + 1e-12)
    y = x + noise
    y = y / np.abs(y).max() * 0.89
    pcm = np.clip(y * 32767, -32768, 32767).astype(int).tolist()
    loop = (w.loops[0][0], w.loops[0][1], False) if w.loops else None
    write_wav(path, rate, [pcm], 16, root_note=w.root, **({"loop": loop} if loop else {}))
    print(f"{path.name}: floor {db} dB" + (f", loop {loop[0]}-{loop[1]}" if loop else "") + f", root {format_note(w.root) if w.root is not None else '-'}")


def main(names=()):
    if not names or "riff" in names:
        (OUT / "riff.wav").write_bytes(RIFF_SOURCE.read_bytes())
    for name, db in FLOORS.items():
        if not names or name in names:
            add_floor(OUT / f"{name}.wav", db)


if __name__ == "__main__":
    main(sys.argv[1:])
