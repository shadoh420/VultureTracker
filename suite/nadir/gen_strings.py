"""Renders the string layers of Nadir into samples/nadir/ from the VSCO 2 Community Edition string sections (Versilian
Studios, CC0, tools/cc0/vsco2): three chord beds (each voice is the nearest recorded section note, pitch-shifted by at
most two semitones, mixed with a room and looped with a crossfade) and the violins sample that doubles the lead. Recorded sections bring
the noise, vibrato and bow texture a synth pad lacks; the song layers them under the synth beds.
VSCO names notes in scientific pitch, one octave below tracker names (VSCO C4 = tracker C-5).
Run: python suite/nadir/gen_strings.py
"""
import re
import sys
from pathlib import Path

import numpy as np
from pedalboard import PitchShift, Reverb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gen_drums import RATE, fx, load, save  # noqa: E402
from vulturetracker.notation import parse_note  # noqa: E402
from vulturetracker.resample import fir_filter, lowpass_fir  # noqa: E402

VSCO = HERE.parent.parent / "tools" / "cc0" / "vsco2"
SECTIONS = [  # folder, soft dynamic marker, tracker range (MIDI) the section covers in the beds
    (VSCO / "Strings" / "Cello Section" / "susvib", "v1", (36, 64)),
    (VSCO / "Strings" / "Viola Section" / "susvib", "v1", (50, 78)),
    (VSCO / "Strings" / "Violin Section" / "susVib", "v1", (64, 96)),
]
ROOM = Reverb(room_size=0.6, damping=0.55, wet_level=0.3, dry_level=0.7, width=0.0)
BEDS = {  # tracker voicings: root and fifth only since v5 (the v4 add9 chords held A and Bb a semitone apart), the mode's
    # colour lives in the lines; the synth beds hold the same open fifths
    "strbed_g": ["G-3", "D-4", "G-4", "D-5"],
    "strbed_bb": ["A#3", "F-4", "A#4", "F-5"],      # unused since v5 (the B section moved to G); kept for the tryout
    "strbed_c": ["C-4", "G-4", "C-5", "G-5"],
}


def library():
    lib = []
    for folder, dyn, (lo, hi) in SECTIONS:
        for p in folder.glob(f"*{dyn}*.wav"):
            m = re.search(r"_([A-G]#?)(\d)_", p.name)
            name = m.group(1)
            midi = parse_note(f"{name}{'' if '#' in name else '-'}{int(m.group(2)) + 1}")     # VSCO C4 is tracker C-5
            lib.append((midi, lo, hi, p))
    return lib


def voice(lib, note):
    """The nearest recorded note within its section's range, shifted to `note` (at most two semitones)."""
    midi = parse_note(note)
    cands = [(abs(m - midi), m, p) for m, lo, hi, p in lib if lo <= midi <= hi and abs(m - midi) <= 2]
    if not cands:
        raise SystemExit(f"no section note within two semitones of {note}")
    d, m, p = min(cands)
    x = load(p)
    if m != midi:
        x = fx(x, PitchShift(semitones=midi - m), tail=0)
    return x / (np.sqrt(np.mean(x[: 2 * RATE] ** 2)) + 1e-9), p.name


def crossfade_loop(x, start_s, end_s, cross_s):
    start, end, cross = (round(t * RATE) for t in (start_s, end_s, cross_s))
    y = x[:end].copy()
    a = np.linspace(0, 1, cross)
    y[end - cross:end] = y[end - cross:end] * (1 - a) + x[start - cross:start] * a
    return y, (start, end, False)


def main():
    lib = library()
    for name, notes in BEDS.items():
        parts, names = [], []
        for n in notes:
            x, fname = voice(lib, n)
            parts.append(x[: 7 * RATE])
            names.append(fname)
        n = min(len(p) for p in parts)
        chord = sum(p[:n] for p in parts)
        chord = fx(chord, ROOM, tail=0.5)
        y, loop = crossfade_loop(chord, 2.5, 6.0, 1.2)
        save(name, y, 16000, loop=loop, max_s=None)
        print("   " + ", ".join(names))
    x, fname = voice([e for e in lib if "Violin" in str(e[3])], "E-5")      # the line is the violins alone
    x = fir_filter(x, lowpass_fir(5000 / RATE, 255))                          # dark, but with its bow: little above 5 kHz
    y, loop = crossfade_loop(fx(x[: 7 * RATE], ROOM, tail=0.5), 2.0, 5.5, 1.0)
    save("strings", y, 16000, root="E-5", loop=loop, max_s=None)
    print("   " + fname)


if __name__ == "__main__":
    main()
