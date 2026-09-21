"""Renders samples/demo4/break.wav: one bar of breakbeat at 168 BPM played by the CC0 Big Rusty Drums kit (Karoryfer
Samples, tools/cc0/bigrusty), the rhythm bed of the song. The bar is a common funk pattern written out below with a
light push on the off-beats, built from the kit's close and overhead mics so the drums bleed into each other, and a
room is printed over the whole bar with the tail of the previous bar kept under the downbeat.
Run: python demo4/gen_break.py
"""
import re
import sys
from pathlib import Path

import numpy as np
from pedalboard import Reverb
from pedalboard.io import AudioFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from vulturetracker.notation import parse_note  # noqa: E402
from vulturetracker.wavload import write_wav  # noqa: E402

KIT = HERE.parent / "tools" / "cc0" / "bigrusty" / "Samples"
OUT = HERE.parent / "samples" / "demo4" / "break.wav"
RATE, BPM = 44100, 168
BAR = round(RATE * 240 / BPM)                  # 63000 frames: exactly 16 rows at speed 5, tempo 140
SLOT = BAR / 16


def late(slot):
    """The push: beats on the grid, 8ths 8 ms late, 16ths 10 ms late."""
    return 0 if slot % 4 == 0 else 8 if slot % 2 == 0 else 10


# The bar, per 16th: (slot, drum, dB below that drum's loudest hit, ms off the grid). Kicks on 0, 2, 10 and 11 with
# a soft pickup on 7; backbeat snares on 4 and 12; ghost snares on 7, 9, 11 and 15; hats on every 8th with two
# 16th pickups. Accents: downbeats full, other beats a little under, ghosts and pickups well under.
HITS = ([(s, "kick", db, late(s)) for s, db in ((0, 0), (2, -2), (7, -8), (10, -2), (11, -1))]
        + [(s, "snare", db, late(s)) for s, db in ((4, 0), (12, 0))]
        + [(s, "ghost", db, late(s)) for s, db in ((7, -8), (9, -8), (11, -8), (15, -8))]
        + [(s, "hat", db, late(s)) for s, db in ((0, -6), (2, -9), (4, -6), (6, -9), (8, -6), (10, -9), (12, -6), (14, -9),
                                                   (5, -12), (13, -12))])
# Each drum: the kit folders mixed for it (close mic plus overhead for bleed) and their gains in dB.
DRUMS = {
    "kick": [("kick_24/kick/kick", 0), ("kick_24/kick/oh", -6)],
    "snare": [("snare_14/center/top", 0), ("snare_14/center/oh", -6)],
    "ghost": [("snare_14/center/top", 0), ("snare_14/center/oh", -6)],
    "hat": [("hihat_14/cl/cl", 0)],
}
BANDS = {"kick": (40, 150), "snare": (150, 1000), "ghost": (150, 1000), "hat": (2000, 10000)}   # each drum's level band
ROOM = Reverb(room_size=0.35, damping=0.5, wet_level=0.30, dry_level=0.70, width=0.0)


def load(path):
    with AudioFile(str(path)) as f:
        assert f.samplerate == RATE, path
        return f.read(f.frames).mean(axis=0).astype(np.float64)


def layers(folder):
    """The folder's files by velocity layer, soft to hard, each a list of round robins."""
    by = {}
    for p in sorted((KIT / folder).glob("*.flac")):
        m = re.search(r"vl(\d+)_rr(\d+)", p.name)
        by.setdefault(int(m.group(1)), []).append(p)
    return [by[k] for k in sorted(by)]


def hit(drum, level_db, n):
    """One hit: the velocity layer for the level (-24 dB and below is the softest), round robin n, the mics mixed,
    normalised by the energy of its first 100 ms in the drum's band, so the layer sets the timbre and the level sets
    the gain."""
    parts = []
    for folder, mic_db in DRUMS[drum]:
        ls = layers(folder)
        layer = ls[min(len(ls) - 1, max(0, round((len(ls) - 1) * (1 + level_db / 24))))]
        parts.append(load(layer[n % len(layer)]) * 10 ** (mic_db / 20))
    y = sum(np.pad(p, (0, max(len(q) for q in parts) - len(p))) for p in parts)
    lo, hi = BANDS[drum]
    Y = np.abs(np.fft.rfft(y[: RATE // 10] * np.hanning(RATE // 10))) ** 2
    fr = np.fft.rfftfreq(RATE // 10, 1 / RATE)
    return y / np.sqrt(Y[(fr >= lo) & (fr < hi)].sum()) * 30 * 10 ** (level_db / 20)


if __name__ == "__main__":
    mix = np.zeros(2 * BAR + RATE)
    counts = {}
    for rep in range(2):                                    # the bar twice: bar 1's room sits under bar 2's downbeat
        for slot, drum, level, ms in HITS:
            counts[drum] = n = counts.get(drum, 0) + 1
            y = hit(drum, level, n)
            at = rep * BAR + round(slot * SLOT + ms * RATE / 1000)
            mix[at:at + len(y)] += y[: len(mix) - at]
    x = ROOM(mix[np.newaxis, :], RATE)[0][BAR: 2 * BAR]
    x = x / np.abs(x).max() * 0.89                          # -1 dBFS
    pcm = np.clip(x * 32767, -32768, 32767).astype(int).tolist()
    write_wav(OUT, RATE, [pcm], 16, root_note=parse_note("C-5"))
    snare_ms = next(ms for slot, drum, _, ms in HITS if drum == "snare" and slot == 4)
    off = (round(4 * SLOT + snare_ms * RATE / 1000) - 128) // 256
    print(f"wrote {OUT}: one {BAR / RATE:.4f} s bar at {BPM} BPM, {len(HITS)} hits; the beat-2 snare starts at O{off:02X}")
