"""Generate the placeholder WAVs used by the demo song. Replace any of them with real samples
(keep the file name, or change the path in the song file).

Tonal samples use rate 66976 Hz = 261.6256 Hz (C-5) * 256, so one C-5 cycle is exactly 256
samples and one C-3 cycle is exactly 1024; loops then contain whole cycles and don't click.

Run: python samples/gen_placeholders.py
"""
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vulturetracker.wavload import write_wav  # noqa: E402

OUT = Path(__file__).resolve().parent
DRUM_RATE = 44100
TONE_RATE = 66976
rng = random.Random(1999)


def clip16(xs, gain=1.0):
    peak = max(1e-9, max(abs(x) for x in xs))
    return [max(-32767, min(32767, round(x / peak * 32000 * gain))) for x in xs]


def kick():
    n = int(DRUM_RATE * 0.45)
    out, phase = [], 0.0
    for i in range(n):
        t = i / DRUM_RATE
        f = 45 + 110 * math.exp(-t * 30)
        phase += 2 * math.pi * f / DRUM_RATE
        body = math.sin(phase) * math.exp(-t * 7)
        click = (rng.uniform(-1, 1) * math.exp(-t * 400)) * 0.3
        out.append(math.tanh(1.8 * (body + click)))
    return clip16(out)


def snare():
    n = int(DRUM_RATE * 0.3)
    out, lp = [], 0.0
    for i in range(n):
        t = i / DRUM_RATE
        noise = rng.uniform(-1, 1)
        lp += 0.5 * (noise - lp)
        tone = math.sin(2 * math.pi * 185 * t) * math.exp(-t * 25)
        out.append(0.7 * lp * math.exp(-t * 14) + 0.5 * tone)
    return clip16(out)


def hat(decay):
    n = int(DRUM_RATE * min(0.5, 6 / decay))
    out, prev = [], 0.0
    for i in range(n):
        t = i / DRUM_RATE
        noise = rng.uniform(-1, 1)
        hp = noise - prev  # crude high-pass
        prev = noise
        out.append(hp * math.exp(-t * decay))
    return clip16(out, 0.8)


def additive(period, length, harmonics, amp_fn, detunes=(0,)):
    """Sum of harmonics; each partial has an integer cycle count over `period`*k so loops are seamless.
    detunes are extra cycles per `length` samples."""
    out = [0.0] * length
    for d in detunes:
        base_cycles = length / period + d  # integer by construction
        for h in range(1, harmonics + 1):
            w = 2 * math.pi * base_cycles * h / length
            ph = rng.uniform(0, 2 * math.pi)
            for i in range(length):
                a = amp_fn(h, i)
                if a:
                    out[i] += a * math.sin(w * i + ph)
    return out


def bass():
    # C-3, 1024-sample period. 0.5 s of decaying brightness, then a looped 4-cycle tail.
    period, cycles = 1024, 36
    length = period * cycles
    settle = period * 32

    def amp(h, i):
        bright = 2 + 18 * max(0.0, 1 - i / settle) ** 3  # exactly 2 from the loop start on
        return (1 / h) * math.exp(-(h - 1) / bright)
    return clip16(additive(period, length, 24, amp)), (settle, length)


def pad():
    # C-5, three detuned saw-ish voices, 128 base cycles; loop = whole sample.
    period, cycles = 256, 128
    length = period * cycles
    return clip16(additive(period, length, 14, lambda h, i: h ** -1.4, detunes=(-1, 0, 1))), (0, length)


def lead():
    # C-5 square-ish (odd harmonics) with a little even content, single-cycle loop over 16 cycles.
    period, cycles = 256, 16
    length = period * cycles
    return clip16(additive(period, length, 20, lambda h, i: (1 / h) if h % 2 else 0.25 / h)), (0, length)


def main():
    write_wav(OUT / "kick.wav", DRUM_RATE, [kick()])
    write_wav(OUT / "snare.wav", DRUM_RATE, [snare()])
    write_wav(OUT / "hat_closed.wav", DRUM_RATE, [hat(60)])
    write_wav(OUT / "hat_open.wav", DRUM_RATE, [hat(9)])
    for name, fn in [("bass", bass), ("pad", pad), ("lead", lead)]:
        data, (ls, le) = fn()
        write_wav(OUT / f"{name}.wav", TONE_RATE, [data])
        print(f"{name}.wav: {len(data)} frames, loop {ls}..{le}")
    print("wrote placeholders to", OUT)


if __name__ == "__main__":
    main()
