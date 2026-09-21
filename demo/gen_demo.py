"""Lays out the demo's patterns and writes them into demo/arena.yaml.

Everything above the `patterns:` line in arena.yaml (module, samples, instruments, orders) is
hand-written and kept as is; everything after it is regenerated from the musical choices below
(chord voicings, progressions, drum/bass rhythms, lead phrases). arena.yaml stays the source of
truth for building: this script is just a faster way to rewrite whole patterns.

Run: python demo/gen_demo.py
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

SONG = Path(__file__).resolve().parent / "arena.yaml"
CH = ["kick", "snare", "hats", "bass", "pad1", "pad2", "pad3", "lead", "echo"]
ROWS = 64

KIT = {"kick": "C-5", "snare": "D-5", "hat": "F#5", "open": "A#5"}
CHORDS = {  # pad voicings (3 voices), bass root
    "Em": (("E-4", "G-4", "B-4"), "E"),
    "C":  (("E-4", "G-4", "C-5"), "C"),
    "D":  (("F#4", "A-4", "D-5"), "D"),
    "B":  (("D#4", "F#4", "B-4"), "B"),
    "Am": (("E-4", "A-4", "C-5"), "A"),
}
PROG = ["Em", "C", "D", "B"]
BREAK_PROG = ["Am", "Em", "C", "B"]


def root(letter, octave):
    return f"{letter}-{octave}" if len(letter) == 1 else f"{letter}{octave}"


def empty():
    return [{c: "..." for c in CH} for _ in range(ROWS)]


def drums(p, style):
    for bar in range(4):
        b = bar * 16
        if style in ("four", "climax"):
            for r in (0, 4, 8, 12):
                p[b + r]["kick"] = f"{KIT['kick']} 01 v64"
            if style == "climax" and bar % 2 == 1:
                p[b + 14]["kick"] = f"{KIT['kick']} 01 v40"
        if style in ("four", "climax", "half"):
            for r in (4, 12):
                p[b + r]["snare"] = f"{KIT['snare']} 01 v56"
            if style == "climax":
                p[b + 15]["snare"] = f"{KIT['snare']} 01 v20"
        for r in range(0, 16, 2):
            if style == "sparse" and r % 4:
                continue
            if r in (2, 6, 10, 14) and style in ("four", "climax"):
                p[b + r]["hats"] = f"{KIT['open']} 01 v36"
            else:
                p[b + r]["hats"] = f"{KIT['hat']} 01 v{44 if r % 4 == 0 else 30}"
        if style in ("four", "climax"):
            for r in (1, 3, 5, 7, 9, 11, 13, 15):
                if p[b + r]["hats"] == "...":
                    p[b + r]["hats"] = f"{KIT['hat']} 01 v18"


def bass(p, prog, style):
    for bar, chord in enumerate(prog):
        b = bar * 16
        letter = CHORDS[chord][1]
        oct3 = 2 if letter in ("A", "B") else 3  # keep the line in one register
        if style == "roll":
            hits = [(0, 0, 64), (2, 0, 44), (3, 1, 52), (5, 0, 44), (6, 0, 52), (8, 0, 60),
                    (10, 1, 52), (11, 0, 44), (13, 0, 48), (14, 1, 52)]
            for r, up, vol in hits:
                p[b + r]["bass"] = f"{root(letter, oct3 + up)} 02 v{vol}"
        else:  # long notes
            p[b]["bass"] = f"{root(letter, oct3)} 02 v56"


def pads(p, prog, vol=40):
    for bar, chord in enumerate(prog):
        for voice, note in zip(("pad1", "pad2", "pad3"), CHORDS[chord][0]):
            p[bar * 16][voice] = f"{note} 03 v{vol}"


# Lead phrases: (row, note, extra effect) for 64 rows; '===' = note off.
LEAD_A = [
    (0, "B-5", ""), (6, "A-5", ""), (8, "G-5", ""), (12, "F#5", ""), (14, "G-5", ""),
    (16, "E-5", ""), (20, None, "H44"), (24, "G-5", ""), (28, "B-5", ""),
    (32, "A-5", ""), (36, "F#5", ""), (38, "A-5", ""), (40, "D-6", ""), (44, None, "H46"), (46, "C-6", ""),
    (48, "B-5", ""), (52, None, "H46"), (56, "A-5", ""), (58, "F#5", ""), (60, "D#5", ""), (63, "===", ""),
]
LEAD_B = [
    (0, "E-6", ""), (4, "D-6", ""), (6, "B-5", ""), (8, "D-6", ""), (12, "E-6", ""), (14, "F#6", ""),
    (16, "G-6", ""), (20, None, "H45"), (24, "E-6", ""), (28, "C-6", ""), (30, "D-6", ""),
    (32, "F#6", ""), (36, "E-6", ""), (38, "D-6", ""), (40, "A-5", ""), (44, "D-6", ""), (46, "E-6", ""),
    (48, "F#6", ""), (50, "D#6", ""), (52, None, "H46"), (56, "B-5", ""), (60, "===", ""),
]
LEAD_BREAK = [
    (0, "C-6", ""), (8, "B-5", ""), (12, "A-5", ""), (16, "G-5", ""), (22, "===", ""),
    (32, "E-5", ""), (36, "G-5", ""), (40, "C-6", ""), (44, "===", ""), (48, "B-5", ""), (50, None, "H34"), (58, "===", ""),
]


def lead(p, phrase, echo=True, lead_vol=48, echo_vol=22):
    for r, note, fx in phrase:
        cell = []
        cell.append(note if note else "...")
        cell.append("04" if note and note != "===" else "..")
        cell.append(f"v{lead_vol}" if note and note != "===" else "...")
        cell.append(fx or "...")
        text = " ".join(cell)
        p[r]["lead"] = text
        if echo and r + 3 < ROWS:
            e = [cell[0], cell[1], f"v{echo_vol}" if note and note != "===" else "...", fx or "..."]
            p[r + 3]["echo"] = " ".join(e)


def fmt(cell):
    parts = cell.split()
    while len(parts) < 4:
        parts.append("..." if len(parts) != 1 else "..")
    return f"{parts[0]} {parts[1]} {parts[2]} {parts[3]}"


def emit(name, p, comment, labels, extra=None):
    print(f"  {name}:")
    print(f"    # {comment}")
    print(f"    rows: {ROWS}")
    print("    data: |")
    print("      ;    kick           | snare          | hats           | bass           | pad 1          | pad 2          | pad 3          | lead           | lead echo")
    for r in range(ROWS):
        if r % 16 == 0:
            print(f"      ; bar {r // 16 + 1}: {labels[r // 16]}")
        cells = " | ".join(fmt(p[r][c]) for c in CH)
        print(f"      {r:02d}: {cells}")


# intro: pads + sparse hats + long bass, riser on last bar
intro = empty()
pads(intro, PROG, vol=34)
drums(intro, "sparse")
bass(intro, PROG, "long")
for i, r in enumerate(range(48, 64)):  # snare build in the last bar, getting louder
    intro[r]["snare"] = f"D-5 01 v{8 + i * 3:02d}"
intro[60]["snare"] = "D-5 01 v52 Q03"   # retrigger every 3 ticks
intro[62]["snare"] = "D-5 01 v60 Q02"

a = empty()
drums(a, "four")
bass(a, PROG, "roll")
pads(a, PROG)

b = empty()
drums(b, "four")
bass(b, PROG, "roll")
pads(b, PROG, vol=32)
lead(b, LEAD_A)

b2 = empty()
drums(b2, "four")
bass(b2, PROG, "roll")
pads(b2, PROG, vol=32)
lead(b2, LEAD_B)

brk = empty()
drums(brk, "sparse")
bass(brk, BREAK_PROG, "long")
pads(brk, BREAK_PROG, vol=44)
lead(brk, LEAD_BREAK, echo_vol=26)
for i, r in enumerate(range(56, 64)):
    brk[r]["snare"] = f"D-5 01 v{16 + i * 6:02d}"
brk[62]["snare"] = "D-5 01 v60 Q03"
brk[63]["snare"] = "D-5 01 v64 Q02"

c = empty()
drums(c, "climax")
bass(c, PROG, "roll")
pads(c, PROG, vol=36)
lead(c, LEAD_B, lead_vol=52)
c[63]["echo"] = fmt(c[63]["echo"])[:11] + "B01"  # loop: jump to order 1 (pattern 'a'), skipping the intro

SECTIONS = [
    ("intro", intro, "pads fade in, sparse hats, snare build with Q (retrigger) at the end", PROG),
    ("a", a, "groove: four-on-the-floor kit, rolling octave bass, pad chords", PROG),
    ("b", b, "theme: lead enters with a 3-row echo on channel 9", PROG),
    ("b2", b2, "theme, higher answer phrase", PROG),
    ("break", brk, "breakdown: no kick, long bass notes, Am-Em-C-B, snare roll", BREAK_PROG),
    ("c", c, "climax: busier kick and ghost snares; B01 on the last row loops back to 'a'", PROG),
]

if __name__ == "__main__":
    out = io.StringIO()
    with redirect_stdout(out):
        for name, p, comment, prog in SECTIONS:
            emit(name, p, comment, prog)
    marker = "\npatterns:\n"
    text = SONG.read_text(encoding="utf-8")
    head = text[: text.index(marker) + len(marker)]
    SONG.write_text(head + out.getvalue(), encoding="utf-8", newline="\n")
    print(f"rewrote the patterns in {SONG}", file=sys.stderr)
