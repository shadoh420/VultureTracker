"""Rift: rows where two sounding notes sit a semitone or a major seventh apart (suite/nadir/harmony.py's rule), from the
song's patterns through the app's sounding table. The bed sample holds A-3 E-4 C-5 on its A-3, the drone sample
A-3 E-4 A-4 C-5 on its A-3, the vocal pad's A-3 E-4 C-5 (sounding) on its written A-3; every other pitched
sample sounds its cell note; the break, hats and crash are unpitched. Background voices of an nna: fade note are not in
the table (the call's, while channels 7 and 8 are muted and left out; unmuted, its E fades would meet the strings' F).
A voice faded by volume slides (Dxy, D00 repeating the last) to max(2, its strike volume / 8) or less no longer sounds,
melodic.py's audible end (-18 dB under the strike), read at each row's end; the app's table keeps a looped sample to its
next note. Muted channels are left out.
Run: python suite/rift/clash.py [song.yaml]
"""
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from vulturetracker.gui import facts_of, sounding_table  # noqa: E402
from vulturetracker.notation import parse_note  # noqa: E402
from vulturetracker.song import load_song_text  # noqa: E402

UNPITCHED = {"Break", "Hats", "Crash"}
VOICING = {"Bed": (0, 7, 15), "Drone": (0, 7, 12, 15), "Vocal": (0, 7, 15)}
NAMES = "C C# D D# E F F# G G# A A# B".split()


def volumes(mod):
    """Per played order, per row: each channel's (volume at the row's end, volume at its last strike), 0-64, from the
    volume column, the sample's volume and the D slides (x or y per tick after the first, D00 repeating the last)."""
    n = len(mod.channels)
    vol, v0, mem, speed, out = [64] * n, [64] * n, [0] * n, mod.speed, []
    for o in (o for o in mod.orders if o < 254):
        rows = []
        for row in mod.patterns[o].rows:
            for ch, c in enumerate(row):
                if c.effect == 1 and c.param:                        # Axx: speed
                    speed = c.param
            for ch, c in enumerate(row):
                if c.note is not None and c.note < 120 and c.instrument:
                    smp = c.instrument
                    if mod.instruments is not None and 0 < c.instrument <= len(mod.instruments):
                        smp = mod.instruments[c.instrument - 1].keymap[c.note][1]
                    vol[ch] = v0[ch] = mod.samples[smp - 1].volume if 0 < smp <= len(mod.samples) else 64
                if c.volcmd is not None and c.volcmd <= 64:
                    vol[ch] = c.volcmd
                    if c.note is not None and c.note < 120:
                        v0[ch] = c.volcmd
                if c.effect == 4:                                    # Dxy
                    mem[ch] = c.param or mem[ch]
                    x, y = mem[ch] >> 4, mem[ch] & 15
                    if x == 15 and y:                                # fine down
                        vol[ch] -= y
                    elif y == 15 and x:                              # fine up
                        vol[ch] += x
                    else:
                        vol[ch] += (x - y) * (speed - 1)
                    vol[ch] = max(0, min(64, vol[ch]))
            rows.append(list(zip(vol, v0)))
        out.append(rows)
    return out


def main(path):
    mod, warnings = load_song_text(path.read_text(encoding="utf-8"), path.parent, str(path))
    facts = facts_of(mod, warnings)
    vols = volumes(mod)
    total = bad = 0
    for oi, rows in enumerate(sounding_table(mod, facts)):
        pairs, clash_rows, seen = Counter(), 0, Counter()
        for r, entries in enumerate(rows):
            entries = [e for e in entries if not mod.channels[e["ch"]].muted
                       and vols[oi][r][e["ch"]][0] > max(2, vols[oi][r][e["ch"]][1] / 8)]
            notes = [((parse_note(e["note"]) + k) % 12, e["name"]) for e in entries
                     if e["name"] not in UNPITCHED and e["sample"] for k in VOICING.get(e["name"], (0,))]
            seen.update(f"{n}:{NAMES[pc]}" for pc, n in notes)
            hit = [(a, b) for i, a in enumerate(notes) for b in notes[i + 1:] if (a[0] - b[0]) % 12 in (1, 11)]
            clash_rows += bool(hit)
            pairs.update(tuple(sorted(f"{n}:{NAMES[pc]}" for pc, n in p)) for p in hit)
        total += len(rows)
        bad += clash_rows
        print(f"order {oi} {facts['orders'][oi]['pattern']:7s} clash rows {clash_rows:3d} of {len(rows)}  "
              f"{', '.join(f'{a}+{b} x{c}' for (a, b), c in pairs.most_common(3))}")
        print("  sounding (rows):", " ".join(f"{k} {v}" for k, v in sorted(seen.items())))
    print(f"total: {bad} clash rows of {total}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "rift.yaml")
