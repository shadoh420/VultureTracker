"""Lays out the patterns and orders of demo3/undertow.yaml (everything after its `patterns:` line).

Grid (the one UT99's Run / Nether Animal / Foregone Destruction use): speed 6 at tempo 125, 4 rows per beat,
so 1 row = a 16th, 16 rows = a bar, 64 rows = a 4-bar pattern built from two 2-bar halves (one chord each).
Rhythms are lists of 16th indexes within a bar (0..15); melodies are 16th indexes within a half (0..31).

Run: python demo3/gen_patterns.py   (then: python -m vulturetracker build demo3/undertow.yaml)
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
SONG = HERE / "undertow.yaml"
sys.path.insert(0, str(HERE.parent))
from vulturetracker.notation import format_cell, format_note, parse_cell, parse_note  # noqa: E402

ROWS, HALF, BAR, S = 64, 32, 16, 1
CH = ["kickL", "kickR", "snareL", "snareR", "gateL", "gateR", "bass", "hatA", "hatB",
      "padL", "padR", "leadL", "leadR", "perc", "fx"]
SMP = {"kick": "01", "snare": "02", "rim": "03", "hat": "04", "open": "05", "ride": "06", "tom": "07",
       "bass": "08", "gate": "09", "pad": "10", "lead": "11", "revcrash": "12", "crash": "13", "swell": "14",
       "gong": "15"}

# One chord per 2-bar half: (gate / strings root, strings fifth, bass root). The gate sample is an open
# E-F#-B-E voicing, so it moves to any root without clashing.
CHORDS = {"E": ("E-4", "B-4", "E-2"), "C": ("C-4", "G-4", "C-2"), "A": ("A-3", "E-4", "A-2"),
          "D": ("D-4", "A-4", "D-2"), "G": ("G-3", "D-4", "G-2")}
PAIRS = [("E", "C"), ("A", "D")]                      # the two 4-bar chord pairs the song cycles

# The lead (a soft DX7 Rhodes) plays short phrases: each is a list of (16th within the half, semitones above
# the lead root). Intervals are limited to root, 2nd, 4th, 5th and their octaves, which fit every root in E minor.
FIGURE = [[(0, 7), (3, 12), (6, 7), (10, 2), (12, 0)],
          [(16, 12), (19, 7), (22, 14), (24, 12), (27, 7), (30, 2)]]
FIGURE_B = [[(0, 7), (3, 12), (6, 14), (10, 12), (12, 7)],                # same rhythm, turns on the 9th
            [(16, 5), (19, 7), (22, 12), (24, 14), (27, 12), (30, 7)]]     # (a displaced version read as a stumble)
ANSWER = [[(0, 14), (2, 12), (4, 7), (8, 12), (11, 14), (14, 19)],        # the climax variation, reaching higher
          [(16, 19), (19, 14), (22, 12), (24, 7), (27, 12), (30, 14)]]
LEAD_ROOT = {"E": "E-5", "C": "C-5", "A": "A-4", "D": "D-5", "G": "G-4"}


def phrase(chord, figure):
    base = parse_note(LEAD_ROOT[chord])
    return [[(s, format_note(base + semis)) for s, semis in ph] for ph in figure]

# Gate accents, one per 16th: the left and right channels interlock. Each row sets the volume and then
# slides it down (Dxy), so loud steps ring and quiet steps chop, the UT99 way (Run's gate channel).
GATE_L = [48, 4, 30, 4, 40, 4, 22, 34, 48, 4, 30, 4, 40, 26, 4, 34]
GATE_R = [8, 40, 4, 34, 6, 44, 30, 4, 8, 40, 4, 34, 6, 44, 30, 18]
# Hat pan per 16th (S8x, 0 = left .. F = right): a slow drift that crosses the field twice per bar.
HAT_PAN = [3, 5, 7, 9, 0xB, 0xC, 0xA, 8, 6, 4, 2, 4, 6, 8, 0xA, 0xC]

# Drum variations, picked per half so no two grooves in a row are identical: (kicks bar 1, kicks bar 2,
# ghost snares, open-hat steps).
VARS = [([0, 7, 10], [0, 3, 10, 13], (7, 9, 15), (14,)),
        ([0, 7, 10], [0, 3, 10, 13], (7, 15), (6, 14)),
        ([0, 6, 10], [0, 4, 7, 10, 14], (3, 9, 15), (10,)),
        ([0, 7, 10, 12], [0, 3, 8, 10, 13], (7, 9, 13, 15), (14,))]
BUSY = [([0, 3, 7, 10], [0, 3, 6, 10, 13], (7, 9, 15), (14,)),
        ([0, 3, 7, 10], [0, 3, 6, 10, 13], (7, 15), (6, 14)),
        ([0, 3, 6, 10], [0, 3, 6, 10, 12, 14], (3, 9, 15), (10,)),
        ([0, 3, 7, 10, 12], [0, 3, 6, 8, 10, 13], (7, 9, 13, 15), (14,))]


def empty(rows=HALF):
    return [{c: "..." for c in CH} for _ in range(rows)]


def put(p, row, ch, cell):
    if 0 <= row < len(p):
        p[row][ch] = cell


def fx_only(p, row, ch, effect):
    cell = parse_cell(p[row][ch])
    fx = parse_cell(effect)
    cell.effect, cell.param = fx.effect, fx.param
    p[row][ch] = format_cell(cell)


# ---------------------------------------------------------------- parts (on a 2-bar half unless noted)

def kick(h, bar, steps, vol=64):
    for s in steps:
        row = bar * BAR + s * S
        off = " O03" if s % 4 == 3 else ""                       # syncopated kicks: softer attack
        put(h, row, "kickL", f"C-5 {SMP['kick']} v{vol}{off}")
        put(h, row, "kickR", f"C-5 {SMP['kick']} v{vol - 12} {'O04' if off else 'O01'}")  # later in, quieter


def snare(h, bar, steps, vol=60, ghosts=(7, 9, 15)):
    for s in steps:
        row = bar * BAR + s * S
        put(h, row, "snareL", f"C-5 {SMP['snare']} v{vol}")
        put(h, row, "snareR", f"C-5 {SMP['snare']} v{vol - 10} O02")
    for s in ghosts:
        put(h, bar * BAR + s * S, "snareL" if s % 2 else "snareR", f"C-5 {SMP['snare']} v14 O08")


def hats(h, bar, density="16", vol=52, open_at=(14,)):
    for s in range(16):
        if density == "8" and s % 2:
            continue
        ch = "hatA" if s % 2 == 0 else "hatB"
        smp, v = (SMP["open"], vol - 8) if s in open_at else (SMP["hat"], vol if s % 4 == 0 else
                                                              vol - 14 if s % 2 else vol - 6)
        put(h, bar * BAR + s * S, ch, f"C-5 {smp} v{v:02d} S8{HAT_PAN[s]:X}")


def groove(h, var=0, busy=False, hat_density="16"):
    k1, k2, ghosts, opens = (BUSY if busy else VARS)[var % len(VARS)]
    for bar, k in ((0, k1), (1, k2)):
        kick(h, bar, k)
        snare(h, bar, (4, 12), ghosts=ghosts)
        hats(h, bar, hat_density, open_at=opens)


def gate(h, chord, vol_scale=1.0):
    root = CHORDS[chord][0]
    for i in range(HALF // S):
        vl = max(1, round(GATE_L[i % 16] * vol_scale))
        vr = max(1, round(GATE_R[i % 16] * vol_scale))
        dl, dr = ("D03" if vl >= 20 else "D09"), ("D03" if vr >= 20 else "D09")   # accents ring, ghosts chop
        if i == 0:
            put(h, 0, "gateL", f"{root} {SMP['gate']} v{vl:02d} {dl}")
            put(h, 0, "gateR", f"{root} {SMP['gate']} v{vr:02d} FF1")   # fine slide up: a few cents sharp
        else:
            put(h, i * S, "gateL", f"... .. v{vl:02d} {dl}")
            put(h, i * S, "gateR", f"... .. v{vr:02d} {dr}")


def pad(h, chord, vol=40):
    root, fifth, _ = CHORDS[chord]
    put(h, 0, "padL", f"{root} {SMP['pad']} v{vol}")
    put(h, 0, "padR", f"{fifth} {SMP['pad']} v{vol} EF1")                  # a few cents flat


def bass(h, chord, style="groove"):
    root = CHORDS[chord][2]
    up = root[:2] + str(int(root[2]) + 1)
    if style == "long":
        put(h, 0, "bass", f"{root} {SMP['bass']} v56")
        put(h, BAR, "bass", f"{root} {SMP['bass']} v48")
        return
    for bar in (0, 1):
        hits = [(0, root, 64), (3, root, 40), (6, up, 48), (8, root, 58), (11, root, 38), (14, up, 50)]
        if bar == 1:
            hits = [(0, root, 64), (3, root, 40), (6, up, 48), (10, root, 56), (12, up, 44), (13, root, 40)]
        for s, note, v in hits:
            put(h, bar * BAR + s * S, "bass", f"{note} {SMP['bass']} v{v}")


def melody(p, phrases, base, vol=64):
    """Electric-piano lead on the full pattern: every note retriggers the decaying sample. leadR doubles each
    note a tick late (SD1) and quieter on the other side, the paired-channel width trick, with no echo
    channel, so the line stays as sparse as it is written."""
    for ph in phrases:
        for s, note in ph:
            put(p, base + s * S, "leadL", f"{note} {SMP['lead']} v{vol}")
            put(p, base + s * S, "leadR", f"{note} {SMP['lead']} v{vol - 20:02d} SD1")


def ride(h, vol=30):
    for bar in (0, 1):
        for s in range(0, 16, 2):
            put(h, bar * BAR + s * S, "perc", f"C-5 {SMP['ride']} v{vol if s % 4 == 0 else vol - 10}")


def rim(p, steps=((1, 14), (3, 14))):
    for bar, s in steps:
        put(p, bar * BAR + s * S, "perc", f"C-5 {SMP['rim']} v40")


def tom_fill(p):                                          # last bar of the pattern
    for s, note, v in ((10, "C-5", 40), (12, "A-4", 46), (13, "G-4", 50), (14, "E-4", 54), (15, "D-4", 58)):
        put(p, 3 * BAR + s * S, "perc", f"{note} {SMP['tom']} v{v}")


def swell(p):
    # The cymbal swell peaks 1.4 s in = ~12 rows (0.12 s per row); start it so it peaks on the next downbeat.
    put(p, ROWS - 12, "fx", f"C-5 {SMP['swell']} v44")


def snare_build(p):                                       # 16ths getting louder through the last bar
    for s in range(8, 16):
        put(p, 3 * BAR + s * S, "snareL" if s % 2 == 0 else "snareR", f"C-5 {SMP['snare']} v{20 + (s - 8) * 5}")


# ---------------------------------------------------------------- patterns

def pattern(chords, var=0, drums=True, busy=False, hat_density="16", gate_scale=1.0, pad_vol=None,
            bass_style="groove", lead=None, lead_vol=64, ride_vol=None):
    """A 4-bar pattern: two 2-bar halves, one chord each, then the lead line laid over the whole thing."""
    p = []
    for k, chord in enumerate(chords):
        h = empty()
        if drums:
            groove(h, var + k, busy, hat_density)
        if gate_scale:
            gate(h, chord, gate_scale)
        if pad_vol:
            pad(h, chord, pad_vol)
        if bass_style:
            bass(h, chord, bass_style)
        if ride_vol:
            ride(h, ride_vol)
        p += h
    if lead:
        for k, chord in enumerate(chords):
            melody(p, phrase(chord, lead), k * HALF, lead_vol)
    return p


def build():
    pats, order = {}, []

    def add(name, p, comment, chords):
        pats[name] = (p, comment, chords)
        order.append(name)

    p = pattern(PAIRS[0], drums=False, gate_scale=0, pad_vol=34, bass_style=None)
    for bar in (1, 3):
        hats(p, bar, "8", vol=40, open_at=())
    put(p, ROWS - 25, "fx", f"C-5 {SMP['revcrash']} v36")    # 3.0 s = 25 rows: it lands on the next downbeat
    add("intro1", p, "intro: string pad alone, sparse hats, a reverse crash into the next pattern", PAIRS[0])

    p = pattern(PAIRS[1], drums=False, gate_scale=0.6, pad_vol=34, bass_style=None)
    hats(p, 0, "8", vol=40, open_at=())
    hats(p, 1, "8", vol=40, open_at=())
    hats(p, 2, "16", vol=44)
    hats(p, 3, "16", vol=44)
    swell(p)
    add("intro2", p, "intro: the gated strings fade in under the pad; cymbal swell into the groove", PAIRS[1])

    for i in range(4):                                    # A: groove
        p = pattern(PAIRS[i % 2], var=i)
        if i == 0:
            put(p, 0, "fx", f"C-5 {SMP['crash']} v40")
        if i == 3:
            tom_fill(p)
        else:
            rim(p)
        add(f"a{i + 1}", p, "groove: paired drums, gated strings, analog bass" +
            ("; crash on the downbeat" if i == 0 else "; tom fill" if i == 3 else ""), PAIRS[i % 2])

    for i in range(4):                                    # B: the lead
        p = pattern(PAIRS[i % 2], var=i + 1, gate_scale=0.8, pad_vol=26, lead=FIGURE if i < 2 else FIGURE_B)
        rim(p)
        if i == 3:
            swell(p)
        add(f"b{i + 1}", p, "theme: the legato bass-timbre lead with its echo channel" +
            ("" if i < 2 else "; second contour"), PAIRS[i % 2])

    p = pattern(PAIRS[0], drums=False, gate_scale=0.5, pad_vol=40, bass_style="long", lead=FIGURE, lead_vol=52,
                ride_vol=22)
    add("drop", p, "drop: drums out, the lead over pad, soft gate and long bass", PAIRS[0])

    p = pattern(("A", "G"), drums=False, gate_scale=0, pad_vol=40, bass_style="long", lead=[FIGURE[0]],
                lead_vol=48, ride_vol=26)
    put(p, 0, "fx", f"C-5 {SMP['gong']} v44")
    kick(p, 0, [0], vol=56)
    add("break1", p, "breakdown: gong, ride, strings on A then G, the first phrase only", ("A", "G"))

    p = pattern(("G", "G"), drums=False, gate_scale=0.5, pad_vol=40, bass_style="long", ride_vol=26)
    snare_build(p)
    swell(p)
    add("break2", p, "breakdown: gate returns softly under a snare build", ("G", "G"))

    for i in range(4):                                    # C: climax with the answer phrase
        p = pattern(PAIRS[i % 2], var=i, busy=True, pad_vol=24, lead=ANSWER, ride_vol=22)
        if i == 0:
            put(p, 0, "fx", f"C-5 {SMP['crash']} v40")
        if i == 3:
            tom_fill(p)
        add(f"c{i + 1}", p, "climax: busier kicks, ride, the lead's higher variation", PAIRS[i % 2])

    for i in range(4):                                    # D: theme again, then loop
        p = pattern(PAIRS[i % 2], var=i + 2, pad_vol=26, lead=FIGURE if i < 2 else FIGURE_B)
        if i == 3:
            tom_fill(p)
            fx_only(p, ROWS - 1, "fx", "B02")             # loop to order 2 ('a1'), skipping the intro
        else:
            rim(p)
        add(f"d{i + 1}", p, "theme returns over the full groove" +
            ("; B02 on the last row loops back to 'a1'" if i == 3 else ""), PAIRS[i % 2])

    # Play order: the A and B sections come back between the climax and the return, as UT99 tracks repeat pairs.
    order = ["intro1", "intro2", "a1", "a2", "a3", "a4", "b1", "b2", "b3", "b4", "drop", "b1", "b2",
             "break1", "break2", "c1", "c2", "c3", "c4", "a3", "a4", "d1", "d2", "d3", "d4"]
    return pats, order


def emit(pats, order):
    header = "      ; " + " | ".join(f"{c:14s}" for c in CH).rstrip()
    for name, (p, comment, chords) in pats.items():
        print(f"  {name}:")
        print(f"    # {comment}")
        print(f"    rows: {ROWS}")
        print("    data: |")
        print(header)
        for r in range(ROWS):
            if r % BAR == 0:
                print(f"      ; bar {r // BAR + 1}: {chords[r // HALF]}")
            print(f"      {r:02d}: " + " | ".join(format_cell(parse_cell(p[r][c])) for c in CH))
    print()
    print(f"orders: [{', '.join(order)}]")


if __name__ == "__main__":
    out = io.StringIO()
    with redirect_stdout(out):
        emit(*build())
    marker = "\npatterns:\n"
    text = SONG.read_text(encoding="utf-8")
    SONG.write_text(text[: text.index(marker) + len(marker)] + out.getvalue(), encoding="utf-8", newline="\n")
    print(f"rewrote the patterns and orders in {SONG}", file=sys.stderr)
