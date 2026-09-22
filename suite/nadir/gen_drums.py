"""Renders the drums of Nadir into samples/nadir/ from CC0 recordings: the Big Rusty Drums kit (Karoryfer Samples,
tools/cc0/bigrusty). The piece wants deep, roomy drums with tails rather than dry ticks: a low-passed kick with a
room, a soft snare and a ghost, a sidestick, a short closed hat and a half-open hat, a ride, a crash, a low tom, a
"boom" (kick and low tom struck together in a room) for section downbeats, and one 16-row bar of breakbeat played by
the kit at the song's tempo (a loop to retrigger every bar and chop with Oxx). Hits reuse demo4/gen_break.py's mic
mixing and level normalisation. Run: python suite/nadir/gen_drums.py
"""
import sys
from pathlib import Path

import numpy as np
from pedalboard import HighpassFilter, LowpassFilter, Pedalboard, Reverb
from pedalboard.io import AudioFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
import demo4.gen_break as gb  # noqa: E402
from vulturetracker.notation import parse_note  # noqa: E402
from vulturetracker.resample import resample  # noqa: E402
from vulturetracker.wavload import write_wav  # noqa: E402

RATE = 44100
OUT = ROOT / "samples" / "nadir"
TEMPO, SPEED, ROWS_PER_BAR = 120, 5, 16           # the song's grid: a row is 5 ticks of 2.5/120 s; 4 rows a beat at 144 BPM
ROW = RATE * 2.5 / TEMPO * SPEED                   # frames per row (4593.75)
BAR = round(ROW * ROWS_PER_BAR)                    # 73500 frames = 1.6667 s

gb.DRUMS.update({
    "tomlow": [("tom_18/center/cl", 0)],
    "ride": [("ride_22/rd/cl", 0)],
    "crash": [("crash_17/cr/oh", 0)],
    "side": [("snare_14/sidestick/top", 0), ("snare_14/sidestick/oh", -6)],
    "hatopen": [("hihat_14/ho/cl", 0)],
})
gb.BANDS.update({"tomlow": (60, 300), "ride": (2000, 10000), "crash": (1000, 8000), "side": (500, 4000), "hatopen": (2000, 10000)})

ROOM = Reverb(room_size=0.55, damping=0.6, wet_level=0.28, dry_level=0.72, width=0.0)
BIG = Reverb(room_size=0.7, damping=0.5, wet_level=0.35, dry_level=0.65, width=0.0)


def load(path):
    with AudioFile(str(path)) as f:
        x = f.read(f.frames).mean(axis=0).astype(np.float64)
        return resample(x, f.samplerate, RATE) if f.samplerate != RATE else x


def mix(*parts):
    n = max(len(p) for p in parts)
    return sum(np.pad(p, (0, n - len(p))) for p in parts)


def fx(x, *chain, tail=1.0):
    x = np.pad(x, (0, round(tail * RATE)))
    y = Pedalboard(list(chain))(x[np.newaxis, :].astype(np.float32), RATE)[0].astype(np.float64)
    keep = np.nonzero(np.abs(y) > 10 ** (-60 / 20) * np.abs(y).max())[0]
    return y[: keep[-1] + 1] if len(keep) else y


def save(name, x, rate=RATE, root="C-5", loop=None, max_s=6.0):
    if max_s and len(x) > max_s * RATE:                        # long tails end with a fade
        n, f = int(max_s * RATE), int(0.4 * RATE)
        x = x[:n] * np.concatenate([np.ones(n - f), np.linspace(1, 0, f)])
    x = x / (np.abs(x).max() or 1) * 0.89                     # -1 dBFS
    if rate != RATE:                                           # band-limited, stored at the role's rate
        x = resample(x, RATE, rate)
        if loop:
            loop = (round(loop[0] * rate / RATE), round(loop[1] * rate / RATE), loop[2])
    pcm = np.clip(x * 32767, -32768, 32767).astype(int).tolist()
    out = OUT / f"{name}.wav"
    write_wav(out, rate, [pcm], 16, root_note=parse_note(root), **({"loop": loop} if loop else {}))
    print(f"wrote {out.name}: {rate} Hz, {len(pcm) / rate:.2f} s" + (f", loop {loop[0]}-{loop[1]}" if loop else ""))


# The bar (16 rows = 4 beats at 144 BPM): kicks on 1, the 'and' of 2 and the 'a' of 3; backbeat snares on 2 and 4
# with ghosts before the downbeat and after 2; closed hats on every 8th with three 16th pickups.
# Each entry: (row, drum, dB below the drum's loudest hit, ms off the grid).
LOOP = ([(0, "kick", 0, 0), (6, "kick", -3, 6), (10, "kick", -4, 8)]
        + [(4, "snare", -4, 0), (12, "snare", -2, 0), (7, "ghost", -18, 8), (15, "ghost", -16, 10)]
        + [(r, "hat", -9 if r % 4 else -6, 5 if r % 4 else 0) for r in range(0, 16, 2)]
        + [(5, "hat", -15, 8), (11, "hat", -15, 8), (13, "hat", -13, 8)])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lp = LowpassFilter(cutoff_frequency_hz=3000)
    save("kick", fx(gb.hit("kick", -2, 1), lp, ROOM), 22050)
    save("snare", fx(gb.hit("snare", -6, 1), HighpassFilter(cutoff_frequency_hz=180), ROOM), 22050)
    save("ghost", fx(gb.hit("ghost", -18, 2), HighpassFilter(cutoff_frequency_hz=250), ROOM), 22050)
    save("side", fx(gb.hit("side", -6, 1), ROOM), 22050)
    h = gb.hit("hat", -8, 1)
    n = min(len(h), round(0.25 * RATE))
    save("hat", h[:n] * np.linspace(1, 0, n) ** 0.3, 22050)
    save("hatopen", fx(gb.hit("hatopen", -8, 1), HighpassFilter(cutoff_frequency_hz=500), tail=0.2), 22050, max_s=0.9)
    save("ride", fx(gb.hit("ride", -6, 1), HighpassFilter(cutoff_frequency_hz=400)), 22050, max_s=3.0)
    save("crash", fx(gb.hit("crash", -3, 1), HighpassFilter(cutoff_frequency_hz=300)), 22050)
    save("tomlow", fx(gb.hit("tomlow", -4, 1), lp, ROOM), 22050)
    # the boom: the kit's hardest kick and low tom together, low-passed, in a bigger room
    boom = mix(gb.hit("kick", 0, 2), gb.hit("tomlow", -2, 2) * 0.8)
    save("boom", fx(boom, LowpassFilter(cutoff_frequency_hz=1500), BIG, tail=1.2), 22050, max_s=3.0)
    # the bar: two passes so the first pass's room sits under the second's downbeat; the second bar is kept
    loop = np.zeros(2 * BAR + 2 * RATE)
    counts = {}
    for rep in range(2):
        for row, drum, level, ms in LOOP:
            counts[drum] = n = counts.get(drum, 0) + 1
            y = gb.hit(drum, level, n)
            if drum == "kick":
                y = fx(y, lp, tail=0)
            at = rep * BAR + round(row * ROW + ms * RATE / 1000)
            loop[at:at + len(y)] += y[: len(loop) - at]
    x = ROOM(loop[np.newaxis, :].astype(np.float32), RATE)[0][BAR: 2 * BAR].astype(np.float64)
    save("loop", x, 22050, loop=(0, len(x), False), max_s=None)
    snare_at = round(4 * ROW * 22050 / RATE)
    print(f"the bar is {BAR / RATE:.4f} s = {ROWS_PER_BAR} rows at tempo {TEMPO} speed {SPEED}; its beat-2 snare starts at O{(snare_at - 128) // 256:02X}")


if __name__ == "__main__":
    main()
