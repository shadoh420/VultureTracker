"""Lays out the patterns and orders of demo4/vantage.yaml (everything after its `patterns:` line) on the layer plan
of a late-90s arena-shooter module: a sub-bass drone holds the tonic under everything (the loudest layer of the
mix), a portamento riff runs on three channels (a voice and two delayed echoes), chord samples sit low underneath
(a minor bed retriggered every pattern, a major bed that swells in the second half of each pattern, a three-chord
motif on an uneven three-hit rhythm with an echo and a slow fade), a choir call answers in the build and the
break, a one-bar break loop and drums arrive late and leave for the break. There is no chord progression: every
chord is rooted on E; the motion is voicing changes over the pedal.

Grid: speed 5 at tempo 140 (168 BPM), 1 row = a 16th, 16 rows = a bar, 64 rows = a 4-bar pattern of two 2-bar
halves. Rhythms are 16th indexes within a bar (0..15).

Run: python demo4/gen_patterns.py   (then: python -m vulturetracker build demo4/vantage.yaml)
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
SONG = HERE / "vantage.yaml"
sys.path.insert(0, str(HERE.parent))
from vulturetracker.notation import format_cell, format_note, parse_cell, parse_note  # noqa: E402

ROWS, HALF, BAR = 64, 32, 16
CH = ["kick", "snare", "hats", "perc", "break", "riff1", "riff2", "riff3", "bed1", "bed2", "motif", "echo", "bass", "choir",
      "cecho", "fx"]
RIFF_CH = ["riff1", "riff2", "riff3"]
SMP = {"kick": "01", "snare": "02", "hat": "03", "ride": "04", "crash": "05", "revcrash": "06", "riff": "07",
       "bed1": "08", "bed2": "09", "bass": "10", "choir": "11", "motif1": "12", "motif2": "13", "motif3": "14",
       "swell": "15", "gong": "16", "break": "17", "open": "18"}
ROOT, THIRD = parse_note("E-4"), 3                    # E minor; the riff is written an octave above ROOT
CHORD = "C-5"                                         # every chord sample is rendered so that C-5 sounds its E chord
SUB, SUB_LOW, BASS_VOL = "E-2", "E-1", 36             # the drone: one tonic note, an octave lower in the intro

# Riff figures: one entry per 8th of the bar, as semitones above the root ("T" = the third, None = hold): static
# 8th-note arpeggios of the one chord, the idiom of the style; they never change.
RIFF = [12, 2, 7, "T", 2, 12, "T", 7]
RIFF_B = [12, "T", 7, 2, 12, 7, "T", 2]
RIFF_S = [12, None, 2, None, 7, None, "T", None]      # quarter notes: intro and outro
GHOSTS = ((7, 13, 15), (2, 7, 9))                     # snare ghosts per bar of a half
# The break: one bar of breakbeat (samples/demo4/break.wav, demo4/gen_break.py), retriggered on these rows (a stutter
# on the 'and' of 2 in bars 1 and 3, a pickup on 62); the kick section also replays the loop's beat-2 snare on row 60
# with a sample offset; in the intro only the pickups play. A crash marks the turnaround of bar 4.
BREAK = {"groove": (0, 6, 16, 32, 38, 48, 62), "kick": (0, 6, 16, 32, 38, 48, 54, 62), "pickup": (58, 62)}
BREAK_SNARE = 0x3B                                    # O-offset of the loop's beat-2 snare, printed by gen_break.py


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


def slide(p, ch, row, first, rows):
    """A volume slide started by `first` (D01, DF3, D10...) and carried by D00 for `rows` rows."""
    put(p, row, ch, f"... .. ... {first}")
    for r in range(row + 1, row + rows):
        put(p, r, ch, "... .. ... D00")


def note(semis, octave=0):
    return format_note(ROOT + semis + 12 * octave)


# ---------------------------------------------------------------- parts on a 2-bar half

def riff(h, fig, vol=16):
    """The riff idiom: one sustained voice whose pitch steps on every 8th with GFF tone portamento, so it never
    retriggers and has no attacks; two more channels repeat it a 16th and two 16ths behind at a fraction of the
    volume. Written an octave above the root (the E-5 register)."""
    for ch, delay, v in ((RIFF_CH[0], 0, vol), (RIFF_CH[1], 1, max(2, vol // 3)), (RIFF_CH[2], 2, max(2, vol // 4))):
        first = True
        for bar in (0, 1):
            for i, deg in enumerate(fig):
                if deg is None:
                    continue
                n = note(THIRD if deg == "T" else deg, 1)
                cell = f"{n} {SMP['riff']} v{v:02d}" if first else f"{n} .. v{v:02d} GFF"
                first = False
                put(h, bar * BAR + 2 * i + delay, ch, cell)


def riff_ghost(h, fig, vol=12):
    """The groove riff: the voice alone, dying over the first bar (v12 down to v01) and cut; no echoes."""
    steps = [i for i, deg in enumerate(fig) if deg is not None]
    for k, i in enumerate(steps):
        n = note(THIRD if fig[i] == "T" else fig[i], 1)
        v = max(1, round(vol * (1 - k / len(steps))))
        put(h, 2 * i, RIFF_CH[0], f"{n} {SMP['riff']} v{v:02d}" if k == 0 else f"{n} .. v{v:02d} GFF")
    put(h, BAR, RIFF_CH[0], f"{note(12, 1)} .. v01 GFF")
    put(h, BAR + 1, RIFF_CH[0], "^^^ .. ... ...")


def hat_pan(row):
    """The hat pan: one step per hit from S81 to S8F and back, a 48-row triangle that restarts with each pattern."""
    v = (row // 2) % 28
    return 1 + v if v <= 14 else 29 - v


def drums(h, row0=0, kicks=False, snares=True, hats=True, ghosts=True):
    for bar in (0, 1):
        if kicks:  # the kick section: four on the floor, open hats on the 'and' of 1, 3 and 4
            for s in (0, 4, 8, 12):
                put(h, bar * BAR + s, "kick", f"C-5 {SMP['kick']} v47")
        if snares:  # the breakbeat backbeat: 4 and 10 in the first bar, 4 and a quiet 12 in the second
            for s, v in ((4, 60), (10, 60)) if bar == 0 else ((4, 60), (12, 40)):
                put(h, bar * BAR + s, "snare", f"C-5 {SMP['snare']} v{v}")
            if ghosts:
                for s in GHOSTS[bar]:
                    put(h, bar * BAR + s, "snare", f"C-5 {SMP['snare']} v16 O08")
        if hats:  # one cymbal hit every 8th at v27, cut by the next; a ghost pair closes every other bar
            for s in range(0, 16, 2):
                put(h, bar * BAR + s, "hats", f"C-5 {SMP['hat']} v27 S8{hat_pan(row0 + bar * BAR + s):X}")
            if bar == 0:
                for s in (13, 15):
                    put(h, s, "hats", f"C-5 {SMP['hat']} v15 S8{hat_pan(row0 + s):X}")
            if kicks:
                for s in (2, 10, 14):
                    put(h, bar * BAR + s, "hats", f"C-5 {SMP['open']} v40")


def loop(p, kind):
    """The break: retriggers on BREAK[kind] in surround (S91), the beat-2 snare replayed on row 60 in the kick
    section with a sample offset, a crash on the turnaround; cut when it is out."""
    if kind is None or kind == "pickup":
        put(p, 0, "break", "^^^ .. ... ...")
    if kind is None:
        return
    for r in BREAK[kind]:
        put(p, r, "break", f"C-5 {SMP['break']} v{32 if kind == 'pickup' else 40}{' S91' if r == 0 else ''}")
    if kind == "kick":
        put(p, 60, "break", f"C-5 {SMP['break']} v40 O{BREAK_SNARE:02X}")
        put(p, 56, "perc", f"C-5 {SMP['crash']} v30")
    elif kind == "groove":
        put(p, 58, "perc", f"C-5 {SMP['crash']} v30")


def snare_build(h):
    for s in range(8, 16):
        put(h, BAR + s, "snare", f"C-5 {SMP['snare']} v{24 + (s - 8) * 5}")


def ride(h, vol=28):
    for bar in (0, 1):
        for s in range(0, 16, 2):
            put(h, bar * BAR + s, "perc", f"C-5 {SMP['ride']} v{vol if s % 4 == 0 else vol - 8}")


# ---------------------------------------------------------------- parts on a whole 4-bar pattern

def bed(p, vol, fade_in=False):
    """The minor bed, retriggered at the top of every pattern so its slow swell breathes with the form, in surround
    (S91). `fade_in` starts it quiet and slides it up (D10) for a section's first pattern."""
    put(p, 20, "bed1", "... .. ... S91")                # the channel state persists; row 20 is free in every variant
    if vol is None:
        put(p, 0, "bed1", "... .. ... D0F")               # the layer is out: fade whatever still rings
    elif fade_in:
        put(p, 0, "bed1", f"{CHORD} {SMP['bed1']} v06 D10")
        for r in range(1, max(1, min(16, (vol - 6) // 5))):   # D10 adds 1 per tick = 5 per row
            put(p, r, "bed1", "... .. ... D10")
    else:
        put(p, 0, "bed1", f"{CHORD} {SMP['bed1']} v{vol:02d}")


def swell(p, on):
    """The major bed: the previous swell dies over the first bar, a new one enters quiet on row 36 and slides up
    to full, and starts dying again at row 56; in surround (S91)."""
    put(p, 20, "bed2", "... .. ... S91")
    if not on:
        put(p, 0, "bed2", "... .. ... D0F")
        return
    slide(p, "bed2", 0, "D01", 17)
    put(p, 36, "bed2", f"{CHORD} {SMP['bed2']} v08 D10")
    for r in range(37, 56):
        put(p, r, "bed2", "... .. ... D00")
    slide(p, "bed2", 56, "D01", 8)


def motif(p, vol=48):
    """The chord motif: three chord samples on rows 0, 5 and 10 (three hits leaning into the bar), echoed six rows
    later at 40% on a second channel panned the other way, then both fade over the second bar."""
    for r, key in ((0, "motif1"), (5, "motif2"), (10, "motif3")):
        put(p, r, "motif", f"{CHORD} {SMP[key]} v{vol:02d}")
        put(p, r + 6, "echo", f"{CHORD} {SMP[key]} v{vol * 2 // 5:02d}")
    slide(p, "motif", 16, "D01", 14)
    slide(p, "echo", 22, "DF3", 10)


def choir(p, vol=40):
    """The choir call: the cluster an octave up on row 0 and at pitch on row 8, echoed six rows later at half
    volume on a second channel, both fading over the rest of the pattern."""
    put(p, 0, "choir", f"C-6 {SMP['choir']} v{vol:02d}")
    put(p, 8, "choir", f"{CHORD} {SMP['choir']} v{vol:02d}")
    slide(p, "choir", 16, "DF2", 48)
    put(p, 0, "cecho", "^^^ .. ... ...")
    put(p, 6, "cecho", f"C-6 {SMP['choir']} v{vol // 2:02d}")
    put(p, 14, "cecho", f"{CHORD} {SMP['choir']} v{vol // 2:02d}")
    slide(p, "cecho", 16, "D01", 29)


# ---------------------------------------------------------------- patterns

def pattern(fig=None, riff_vol=16, ghost=False, drum=None, loop_kind=None, bed1=None, bed1_fade=False, bed2=False,
            motif_vol=None, choir_vol=None, bass=SUB, ride_vol=None):
    """A 4-bar pattern from two 2-bar halves. `drum` is a dict of drums() flags or None; `ghost` writes the riff
    as the dying groove riff instead of the full three-channel figure; `loop_kind` picks the break's rows."""
    p = []
    for k in range(2):
        h = empty()
        if fig and ghost:
            if k == 0:
                riff_ghost(h, fig)
        elif fig:
            riff(h, fig, riff_vol)
        else:
            for ch in RIFF_CH:
                put(h, 0, ch, "... .. ... D0F")           # the looped riff sample rings until faded
        if drum is not None:
            drums(h, row0=k * HALF, **drum)
        if ride_vol:
            ride(h, ride_vol)
        p += h
    if bass:
        put(p, 0, "bass", f"{bass} {SMP['bass']} v{BASS_VOL}")   # retriggered at the top of every pattern
    loop(p, loop_kind)
    bed(p, bed1, bed1_fade)
    swell(p, bed2)
    if motif_vol:
        motif(p, motif_vol)
    if choir_vol:
        choir(p, choir_vol)
    return p


FULL = {"kicks": True}
GROOVE = {}
HATS = {"snares": False}


def build():
    pats, order = {}, []

    def add(name, comment, **kw):
        p = pattern(**kw)
        pats[name] = (p, comment)
        order.append(name)
        return p

    # ---- intro: motif and riff over the low drone; the beds arrive; then everything but
    #      the drone and drums thins out before the drop
    add("i1", "intro: sparse riff and the chord motif over the low drone", fig=RIFF_S, riff_vol=12, motif_vol=32,
        bass=SUB_LOW)
    add("i2", "intro: the riff fills in", fig=RIFF, riff_vol=14, motif_vol=40, bass=SUB_LOW)
    add("i3", "intro: the minor bed fades in, cymbal 8ths", fig=RIFF, motif_vol=40, bed1=48, bed1_fade=True,
        drum=HATS, loop_kind="pickup", bass=SUB_LOW)
    add("i4", "intro: the major bed swells", fig=RIFF, motif_vol=40, bed1=48, bed2=True, drum=HATS, loop_kind="pickup", bass=SUB_LOW)
    add("b1", "build: snare without kick; the choir calls", fig=RIFF, motif_vol=40, bed1=48, bed2=True, choir_vol=40,
        drum=GROOVE, loop_kind="pickup", bass=SUB_LOW)
    p = add("b2", "build: cymbal swell", fig=RIFF, motif_vol=40, bed1=48, bed2=True, drum=GROOVE, loop_kind="pickup", bass=SUB_LOW)
    put(p, ROWS - 12, "fx", f"C-5 {SMP['swell']} v40")
    add("b3", "build: motif and beds out; the choir calls again", fig=RIFF, choir_vol=40, drum=GROOVE, loop_kind="pickup", bass=SUB_LOW)
    p = add("b4", "build: snare build and reverse crash into the drop", fig=RIFF, drum=GROOVE, loop_kind="pickup", bass=SUB_LOW)
    snare_build(p[HALF:])
    put(p, ROWS - 26, "fx", f"C-5 {SMP['revcrash']} v40")

    # ---- groove 1: the break and drums, the drone up an octave, beds and motif; the riff only as a dying ghost on
    #      alternate patterns
    for i in range(6):
        p = add(f"g{i + 1}", "groove: full drums, beds and motif" + ("; the riff dies away" if i % 2 == 0 else ""),
                fig=RIFF if i % 2 == 0 else None, ghost=True, drum=GROOVE, loop_kind="groove", bed1=48, bed2=True, motif_vol=48)
        if i == 0:
            put(p, 0, "perc", f"C-5 {SMP['crash']} v44")

    # ---- thin: drums out; the riff returns in full over beds and motif
    add("t1", "thin: drums out; the riff returns in full over beds and motif", fig=RIFF, bed1=48, bed2=True, motif_vol=48)
    add("t2", "thin: the second riff figure", fig=RIFF_B, riff_vol=18, bed1=48, bed2=True, motif_vol=48)

    # ---- choir section: drums back, the choir calls on alternate patterns, no riff
    for i in range(4):
        add(f"h{i + 1}", "choir section: drums, beds and motif" + ("; the choir calls" if i % 2 == 0 else ""),
            drum=GROOVE, loop_kind="groove", bed1=48, bed2=True, motif_vol=48, choir_vol=40 if i % 2 == 0 else None)

    # ---- break: drums out, the gong; beds and the choir, then the riff returns sparse over a ride
    p = add("k1", "break: gong; beds and the choir call, no drums", bed1=52, bed2=True, choir_vol=44)
    put(p, 0, "fx", f"C-5 {SMP['gong']} v44")
    add("k2", "break: beds and motif alone", bed1=52, bed2=True, motif_vol=40)
    add("k3", "break: ride and the sparse riff return", fig=RIFF_S, riff_vol=13, bed1=52, bed2=True, motif_vol=40,
        ride_vol=26)
    p = add("k4", "break: cymbals return; swell into the drop", fig=RIFF, riff_vol=15, bed1=52, bed2=True,
            motif_vol=44, drum=HATS, loop_kind="pickup", ride_vol=24)
    put(p, ROWS - 12, "fx", f"C-5 {SMP['swell']} v44")

    # ---- return (the kick section): four on the floor and open hats over the break, the riff in full; then the loop
    for i in range(6):
        p = add(f"r{i + 1}", "return: full drums, riff, beds and motif" + ("; crash" if i == 0 else
                                                                        "; the choir calls" if i == 2 else ""),
                fig=RIFF if i < 4 else RIFF_B, drum=FULL, loop_kind="kick", bed1=48, bed2=True, motif_vol=48,
                choir_vol=40 if i == 2 else None)
        if i == 0:
            put(p, 0, "perc", f"C-5 {SMP['crash']} v44")
    add("o1", "outro: kick out; riff, beds and motif", fig=RIFF, riff_vol=15, drum=GROOVE, loop_kind="groove", bed1=48, bed2=True,
        motif_vol=40)
    p = add("o2", "outro: sparse riff over the bed; B02 loops back to 'i3'", fig=RIFF_S, riff_vol=13, bed1=48,
            motif_vol=32)
    fx_only(p, ROWS - 1, "fx", "B02")
    return pats, order


def emit(pats, order):
    header = "      ; " + " | ".join(f"{c:14s}" for c in CH).rstrip()
    for name, (p, comment) in pats.items():
        print(f"  {name}:")
        print(f"    # {comment}")
        print(f"    rows: {ROWS}")
        print("    data: |")
        print(header)
        for r in range(ROWS):
            if r % BAR == 0:
                print(f"      ; bar {r // BAR + 1}")
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
