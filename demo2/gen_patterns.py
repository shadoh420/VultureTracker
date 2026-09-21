"""Lays out the patterns of demo2/iron_relay.yaml (everything after its `patterns:` line).

Grid: speed 3, 8 rows per beat, so 1 row = a 32nd note, 2 rows = a 16th, 4 rows = an 8th, 32 rows = a bar.
Musical material is plain data below: chord progressions, drum and bass rhythms (in 16ths), melodies.

Run: python demo2/gen_patterns.py   (then: python -m vulturetracker build demo2/iron_relay.yaml)
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
SONG = HERE / "iron_relay.yaml"
ARP_WAV = HERE.parent / "samples" / "surge" / "arp.wav"
sys.path.insert(0, str(HERE.parent))
from vulturetracker.notation import format_cell, parse_cell  # noqa: E402

ROWS, BAR, S = 128, 32, 2          # rows per pattern, rows per bar, rows per 16th
CH = ["kick", "snare", "hats", "cym", "toms", "fx", "bass", "arp", "arpecho",
      "pad1", "pad2", "pad3", "choir", "stab", "lead", "leadecho"]
KIT = {"kick": "C-5", "snare": "D-5", "hat": "F#5", "open": "A#5", "crash": "C#6"}
INS = {"kit": "01", "tom": "02", "riser": "03", "bass": "04", "arp": "05", "pad": "06", "choir": "07",
       "stab": "08", "lead": "09", "sweep": "10"}

# chord -> (pad voicing, bass note, arp note = transposition of the D minor phrase, stab note = m7 chord root)
CHORDS = {
    "Dm": (("D-4", "F-4", "A-4"), "D-3", "D-4", "D-4"),
    "Bb": (("D-4", "F-4", "A#4"), "A#2", "D-4", "G-3"),   # unshifted Dm arp over Bb = Bbmaj9 colour
    "C":  (("E-4", "G-4", "C-5"), "C-3", "E-4", "A-3"),   # Em arp over C = Cmaj7 colour
    "Am": (("E-4", "A-4", "C-5"), "A-2", "A-3", "A-3"),
    "Gm": (("D-4", "G-4", "A#4"), "G-2", "G-3", "G-3"),
}
PROG = ["Dm", "Bb", "C", "Am"]
BREAK = ["Gm", "Dm", "Bb", "C"]


def arp_slices():
    """Sample offsets (Oxx) that start each 16th of the arp phrase, measured from the rendered WAV."""
    try:
        import numpy as np
        from vulturetracker.wavload import read_wav
        w = read_wav(ARP_WAV)
        x = np.abs(np.array(w.channels[0], dtype=float))
        env = np.convolve(x, np.ones(64) / 64, "same")
        step = round(w.rate * 60 / 140 / 4)
        out = []
        for k in range(8):
            lo = max(0, k * step - 1500)
            onset = lo + int(np.argmax(np.diff(env[lo:k * step + 1500])))
            out.append(min(255, onset // 256))
        return out
    except Exception as e:  # keep working without numpy: use the nominal grid
        print(f"warning: could not measure {ARP_WAV.name} ({e}); using nominal slice offsets", file=sys.stderr)
        return [min(255, k * 4725 // 256) for k in range(8)]


SLICES = arp_slices()


def empty():
    return [{c: "..." for c in CH} for _ in range(ROWS)]


def put(p, row, ch, cell):
    if 0 <= row < ROWS:
        p[row][ch] = cell


def fx_only(p, row, ch, effect):
    """Add an effect to a cell without disturbing its note/instrument/volume."""
    cell = parse_cell(p[row][ch])
    fx = parse_cell(effect)
    cell.effect, cell.param = fx.effect, fx.param
    p[row][ch] = format_cell(cell)


# ---------------------------------------------------------------- parts

def drums(p, style, bars=range(4)):
    for bar in bars:
        b = bar * BAR
        if style in ("groove", "climax"):
            kicks = [0, 6, 10] if style == "groove" else [0, 3, 6, 10]
            if style == "groove" and bar % 2:
                kicks = [0, 6, 10, 13]
            for s in kicks:
                put(p, b + s * S, "kick", f"{KIT['kick']} {INS['kit']} v{64 if s in (0, 10) else 50}")
            for s in (4, 12):
                put(p, b + s * S, "snare", f"{KIT['snare']} {INS['kit']} v60")
            # ghost snares, nudged late by one tick (SD1) for swing
            for s, v in ((7, 14), (15, 12)):
                put(p, b + s * S, "snare", f"{KIT['snare']} {INS['kit']} v{v:02d} SD1")
            for s in range(16):
                if s in (14,) and bar % 2:
                    put(p, b + s * S, "hats", f"{KIT['open']} {INS['kit']} v30")
                else:
                    put(p, b + s * S, "hats", f"{KIT['hat']} {INS['kit']} v{36 if s % 2 == 0 else 16}")
        elif style == "sparse":
            for s in range(0, 16, 2):
                put(p, b + s * S, "hats", f"{KIT['hat']} {INS['kit']} v{24 if s % 4 == 0 else 14}")
        elif style == "halftime":
            put(p, b, "kick", f"{KIT['kick']} {INS['kit']} v56")
            put(p, b + 8 * S, "snare", f"{KIT['snare']} {INS['kit']} v48")
            for s in range(0, 16, 2):
                put(p, b + s * S, "hats", f"{KIT['hat']} {INS['kit']} v{22 if s % 4 == 0 else 12}")


def crash(p, row=0):
    put(p, row, "cym", f"{KIT['crash']} {INS['kit']} v48")


def tom_fill(p, bar=3):
    b = bar * BAR
    for s, note in ((12, "G-4"), (13, "E-4"), (14, "C-4"), (15, "A-3")):
        put(p, b + s * S, "toms", f"{note} {INS['tom']} v{40 + (s - 12) * 6}")


def snare_roll(p, bar=3):
    """16ths getting louder, then 32nds with retrigger for the last beat."""
    b = bar * BAR
    for s in range(8, 16):
        vol = 16 + (s - 8) * 5
        put(p, b + s * S, "snare", f"{KIT['snare']} {INS['kit']} v{vol:02d}" + (" Q01" if s >= 12 else ""))


def riser(p):
    # The reverse crash is ~2.34 s = ~44 rows at 140 BPM; start it so it peaks on the next downbeat.
    put(p, ROWS - 44, "fx", f"C-5 {INS['riser']} v48")


def bass(p, prog, style):
    for bar, chord in enumerate(prog):
        b = bar * BAR
        root = CHORDS[chord][1]
        up = root[:2] + str(int(root[2]) + 1)
        if style == "roll":
            hits = [(0, root, 64), (2, root, 40), (3, up, 52), (6, root, 56), (8, root, 60),
                    (10, up, 50), (11, root, 40), (14, root, 52)]
            for s, note, v in hits:
                put(p, b + s * S, "bass", f"{note} {INS['bass']} v{v}")
            nxt = CHORDS[prog[(bar + 1) % len(prog)]][1]
            if nxt != root and bar % 2 == 1:  # slide into the next chord with tone portamento
                put(p, b + 15 * S, "bass", f"{nxt} .. ... G18")
        else:  # long notes; the filter opens over the bar with Zxx on the in-between rows
            put(p, b, "bass", f"{root} {INS['bass']} v56 Z20")
            for i, z in enumerate(("Z30", "Z40", "Z50", "Z60", "Z70", "Z7F")):
                fx_only(p, b + (i + 1) * 4, "bass", z)


def arp(p, prog, order=(0, 2, 4, 6, 0, 2, 4, 6), vol=40, echo=True, filt=None):
    """Retrigger slices of the arp phrase every 8th note, transposed to each chord."""
    for bar, chord in enumerate(prog):
        note = CHORDS[chord][2]
        for i, k in enumerate(order):
            row = bar * BAR + i * 4
            put(p, row, "arp", f"{note} {INS['arp']} v{vol} O{SLICES[k]:02X}")
            if echo:  # a dotted-8th (6 rows) echo on the other side, quieter
                put(p, row + 6, "arpecho", f"{note} {INS['arp']} v{vol // 2:02d} O{SLICES[k]:02X}")
    if filt:  # Zxx filter sweep over the pattern on rows that carry no retrigger
        lo, hi = filt
        for i in range(ROWS // 4):
            z = lo + (hi - lo) * i // (ROWS // 4 - 1)
            fx_only(p, i * 4 + 2, "arp", f"Z{z:02X}")


def pads(p, prog, vol=36):
    for bar, chord in enumerate(prog):
        for ch, note in zip(("pad1", "pad2", "pad3"), CHORDS[chord][0]):
            put(p, bar * BAR, ch, f"{note} {INS['pad']} v{vol}")


def stabs(p, prog, vol=44):
    for bar, chord in enumerate(prog):
        for s in (0, 6, 10):
            put(p, bar * BAR + s * S, "stab", f"{CHORDS[chord][3]} {INS['stab']} v{vol - (6 if s else 0)}")


def choir(p, notes, vol=40):
    """notes: one (note or None) per bar."""
    for bar, note in enumerate(notes):
        if note:
            put(p, bar * BAR, "choir", f"{note} {INS['choir']} v{vol}")


# Melodies: (16th index across the 4 bars, note, effect). '===' = note off. Effects: Hxy vibrato, Gxx glide.
LEAD_A = [
    (0, "A-5", ""), (6, "G-5", ""), (8, "F-5", ""), (12, "E-5", ""), (14, "F-5", ""),
    (16, "D-5", ""), (20, None, "H46"), (24, "F-5", ""), (28, "A#5", ""),
    (32, "C-6", ""), (38, "A#5", ""), (40, "A-5", ""), (44, "G-5", "G20"),
    (48, "A-5", ""), (54, None, "H48"), (60, "===", ""), (62, "E-5", ""),
]
LEAD_B = [
    (0, "D-6", ""), (6, "E-6", ""), (8, "F-6", ""), (12, "E-6", ""), (14, "D-6", ""),
    (16, "F-6", ""), (20, None, "H46"), (24, "D-6", ""), (28, "A#5", ""),
    (32, "C-6", ""), (36, "E-6", ""), (40, "G-6", "G18"), (44, None, "H46"),
    (48, "A-6", ""), (52, None, "H48"), (58, "===", ""), (60, "A-5", ""), (62, "C-6", ""),
]


def lead(p, phrase, vol=48, echo=True):
    for s, note, fx in phrase:
        row = s * S
        ins = INS["lead"] if note and note != "===" else ".."
        v = f"v{vol}" if note and note != "===" else "..."
        put(p, row, "lead", f"{note or '...'} {ins} {v} {fx or '...'}")
        if echo:
            ev = f"v{vol // 2:02d}" if note and note != "===" else "..."
            put(p, row + 6, "leadecho", f"{note or '...'} {ins} {ev} {fx or '...'}")


# ---------------------------------------------------------------- patterns

def build():
    pats = {}

    p = empty()                                   # intro: pads swell, filtered arp opens up, riser
    pads(p, PROG, vol=30)
    arp(p, PROG, vol=34, filt=(0x18, 0x6C))
    drums(p, "sparse", bars=(2, 3))
    bass(p, PROG, "long")
    riser(p)
    pats["intro"] = (p, "pads swell in, the arp's filter opens with Zxx, reverse crash into the drop", PROG)

    p = empty()                                   # a: the groove
    crash(p)
    drums(p, "groove")
    bass(p, PROG, "roll")
    arp(p, PROG)
    pads(p, PROG, vol=30)
    tom_fill(p)
    pats["a"] = (p, "groove: broken kick pattern with swung ghost snares, rolling bass with slides, chopped arp", PROG)

    p = empty()                                   # a2: groove + stabs, arp slices re-ordered
    drums(p, "groove")
    bass(p, PROG, "roll")
    arp(p, PROG, order=(0, 2, 4, 6, 4, 6, 1, 7))
    pads(p, PROG, vol=28)
    stabs(p, PROG)
    snare_roll(p)
    pats["a2"] = (p, "adds minor-7 stabs; arp slices re-ordered for a stutter; snare roll with Q01 retrigger", PROG)

    p = empty()                                   # b: lead theme
    crash(p)
    drums(p, "groove")
    bass(p, PROG, "roll")
    arp(p, PROG, vol=32)
    pads(p, PROG, vol=28)
    lead(p, LEAD_A)
    pats["b"] = (p, "theme: lead enters with a dotted-8th echo, vibrato holds and a glide (Gxx)", PROG)

    p = empty()                                   # b2: answer phrase + stabs
    drums(p, "groove")
    bass(p, PROG, "roll")
    arp(p, PROG, vol=32, order=(0, 2, 4, 6, 4, 6, 1, 7))
    pads(p, PROG, vol=28)
    stabs(p, PROG, vol=38)
    lead(p, LEAD_B)
    tom_fill(p)
    pats["b2"] = (p, "answer phrase, higher; stabs return; tom fill", PROG)

    p = empty()                                   # break
    drums(p, "halftime")
    bass(p, BREAK, "long")
    pads(p, BREAK, vol=36)
    choir(p, ["A#4", "A-4", "F-4", "G-4"])
    put(p, 0, "fx", f"D-3 {INS['sweep']} v44")
    arp(p, BREAK, vol=26, filt=(0x7F, 0x30), echo=False)
    snare_roll(p)
    riser(p)
    pats["break"] = (p, "breakdown: half-time drums, choir, filter-sweep synth, arp closing down, snare roll", BREAK)

    for name, ph in (("c", LEAD_A), ("c2", LEAD_B)):
        p = empty()                               # climax
        if name == "c":
            crash(p)
        drums(p, "climax")
        bass(p, PROG, "roll")
        arp(p, PROG, vol=34, order=(0, 2, 4, 6, 4, 6, 1, 7))
        pads(p, PROG, vol=30)
        stabs(p, PROG, vol=40)
        choir(p, ["A-4", "A#4", "C-5", "A-4"], vol=34)
        lead(p, ph, vol=50)
        if name == "c2":
            snare_roll(p)
            tom_fill(p)
            fx_only(p, ROWS - 1, "leadecho", "B01")   # loop back to order 1 ('a'), skipping the intro
        pats[name] = (p, "climax: busier kick, choir under the lead" +
                      ("; B01 on the last row loops back to 'a'" if name == "c2" else ""), PROG)
    return pats


def fmt(cell):
    return format_cell(parse_cell(cell))  # validates the cell and pads it to aligned columns


def emit(pats):
    header = "      ; " + " | ".join(f"{c:14s}" for c in ["kick", "snare", "hats", "cymbals", "toms", "fx", "bass", "arp",
                                                          "arp echo", "pad 1", "pad 2", "pad 3", "choir", "stab",
                                                          "lead", "lead echo"]).rstrip()
    for name, (p, comment, prog) in pats.items():
        print(f"  {name}:")
        print(f"    # {comment}")
        print(f"    rows: {ROWS}")
        print("    data: |")
        print(header)
        for r in range(ROWS):
            if r % BAR == 0:
                print(f"      ; bar {r // BAR + 1}: {prog[r // BAR]}")
            print(f"      {r:03d}: " + " | ".join(fmt(p[r][c]) for c in CH))


if __name__ == "__main__":
    out = io.StringIO()
    with redirect_stdout(out):
        emit(build())
    marker = "\npatterns:\n"
    text = SONG.read_text(encoding="utf-8")
    SONG.write_text(text[: text.index(marker) + len(marker)] + out.getvalue(), encoding="utf-8", newline="\n")
    print(f"rewrote the patterns in {SONG} (arp slice offsets: {' '.join(f'{s:02X}' for s in SLICES)})", file=sys.stderr)
