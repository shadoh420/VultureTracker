"""Lays out the patterns and orders of suite/nadir/nadir.yaml (everything after its `patterns:` line).

Nadir is a dark, driving piece on modal pedals: a sub drone holds one root per section under everything, a synth bed
and a recorded string bed breathe with the form (retriggered every pattern; the swelling second bed in surround), the
melody is a soft synth lead doubled by a recorded violin section (two phrases per colour, alternating pattern by
pattern, each note held until the next takes over), and one moving line at a time answers it: an arp in 8ths or
16ths an octave below the lead, a dotted-8th sequence in its own soft voice, or a portamento riff with an echo (the B
section and the last peak). v5, from the first listening notes: the beds hold root and fifth only, no line stacks its
own notes (short fadeouts), the sequence has no echo, the B section stays on G, the intro hats are sparse. v6 (the last pass, from the second notes): no sequence line at all, no arp figure under
the B-section riff, the B groove on the closed hat instead of the ride, the breakdown on G like everything else and
three patterns long, and the choir call is G D G without its ninth. A choir cluster calls in the peaks and the breakdown. The drums drive: 8th hats sweeping across the
stereo field, a kick pattern, a snare with ghosts, section downbeats marked by a "boom", and a recorded breakbeat bar
retriggered every bar and chopped with a sample offset under the peaks; a quiet quarter-note sub throb sits under
the kick.

Grid: tempo 120, speed 5, 4 rows per beat at 144 BPM; a bar is 16 rows, a pattern is four bars (64 rows). One pitch
collection (the notes of F major) under one pedal, G (Dorian), since v6 (the breakdown's C-Mixolydian colour read as out of place).

Run: python suite/nadir/gen_patterns.py   (rewrites everything after `patterns:` in nadir.yaml, discarding hand edits
made there; then: python -m vulturetracker build suite/nadir/nadir.yaml --render suite/nadir/nadir.wav)
"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
SONG = HERE / "nadir.yaml"
sys.path.insert(0, str(HERE.parent.parent))
from vulturetracker.notation import format_cell, parse_cell  # noqa: E402

ROWS, BAR = 64, 16
CH = ["kick", "snare", "hats", "perc", "loop", "pulse", "drone", "beda", "bedb", "strbed", "arp", "seq", "seqecho", "riff",
      "riffecho", "choir", "lead", "violins", "wind", "fx"]
I = {"kick": "01", "snare": "02", "ghost": "03", "side": "04", "hat": "05", "hatopen": "06", "ride": "07", "crash": "08",
     "tomlow": "09", "boom": "10", "loop": "11", "revcrash": "12", "swell": "13", "drone": "14", "pulse": "15", "beda_g": "16",
     "beda_c": "17", "bedb_bb": "18", "bedb_g": "19", "strbed_g": "20", "strbed_bb": "21", "strbed_c": "22", "choir": "23",
     "arp": "24", "seq": "25", "riff": "26", "lead": "27", "wind": "28", "choir_hi": "29", "violins": "32"}
CHORD = "C-5"                     # every chord sample plays as voiced at C-5
LOOP_SNARE = 0x23                 # O-offset of the drum bar's beat-2 snare (printed by gen_drums.py)

# The pedals: drone and pulse notes, which bed samples carry the colour, where the G choir cluster is transposed to.
PEDAL = {
    "G":  dict(drone="G-1", pulse="G-2", beda="beda_g", bedb="bedb_g", strbed="strbed_g", choir="C-5"),
    "Bb": dict(drone="A#1", pulse="A#2", beda=None, bedb="bedb_bb", strbed="strbed_bb", choir="D#5"),
    "C":  dict(drone="C-2", pulse="C-3", beda="beda_c", bedb=None, strbed="strbed_c", choir="F-5"),
}
# Arp cells (eight notes, cycled) an octave under the violins, one per colour: chord tones with the mode's colour note.
ARP = {
    "G":  ["G-3", "D-4", "A-3", "E-4", "D-4", "A-3", "G-3", "E-4"],
    "G2": ["G-3", "A-3", "D-4", "E-4", "G-4", "E-4", "D-4", "A-3"],
    "Bb": ["A#3", "F-4", "D-4", "C-4", "F-4", "D-4", "A#3", "C-4"],
    "C":  ["C-4", "G-3", "A#3", "D-4", "G-3", "C-4", "D-4", "A#3"],
}
# Dotted-8th sequence phrases (3 rows a note, eight notes = 24 rows) in the arp's tone, stepwise, leaning on the
# colour notes; a phrase fills three of a half-pattern's four bars... twice per pattern.
SEQ = {
    "A1": ["G-3", "A-3", "D-4", "E-4", "D-4", "A-3", "G-3", "F-3"],
    "A2": ["D-4", "E-4", "G-4", "E-4", "D-4", "C-4", "A-3", "G-3"],
    "C1": ["C-4", "A#3", "G-3", "A-3", "A#3", "C-4", "D-4", "C-4"],
    "C2": ["G-4", "F-4", "E-4", "D-4", "C-4", "D-4", "E-4", "C-4"],
}
# Portamento riff cells (2 rows a note, eight notes = one bar), two per colour, played A A B A over a pattern.
RIFF = {
    "Bb": (["A#3", "F-4", "D-4", "A#3", "C-4", "D-4", "F-4", "A-3"], ["A#3", "D-4", "F-4", "G-4", "F-4", "D-4", "C-4", "A-3"]),
    "G":  (["G-3", "D-4", "A#3", "G-3", "C-4", "D-4", "A#3", "F-3"], ["G-3", "A#3", "D-4", "F-4", "D-4", "C-4", "A#3", "A-3"]),
}
# The melody, two phrases per colour, (note, row, volume): the first rises through the colour note and falls back, the
# second climbs from the root and settles; both end hanging on the pedal's ninth. Quarter notes are the fastest move,
# most notes hold a bar or half of one, and each hangs until the next fades it (the lead and the violins doubling it
# are nna: fade instruments).
LEAD = {
    "G":  [[("D-5", 0, 50), ("E-5", 12, 46), ("F-5", 16, 50), ("E-5", 24, 46), ("D-5", 28, 46), ("C-5", 32, 48), ("A#4", 44, 44),
            ("C-5", 48, 46), ("A-4", 56, 44)],
           [("G-4", 0, 46), ("A-4", 8, 44), ("A#4", 12, 44), ("D-5", 16, 50), ("C-5", 28, 46), ("E-5", 32, 48), ("D-5", 40, 46),
            ("A-4", 48, 44)]],
    "Bb": [[("F-5", 0, 48), ("G-5", 12, 44), ("A-5", 16, 48), ("G-5", 24, 44), ("F-5", 28, 44), ("D-5", 32, 46), ("C-5", 44, 42),
            ("D-5", 48, 44), ("C-5", 56, 42)],
           [("D-5", 0, 46), ("F-5", 8, 44), ("G-5", 12, 44), ("A-5", 16, 48), ("G-5", 28, 44), ("F-5", 32, 46), ("D-5", 40, 44),
            ("C-5", 48, 42)]],
    "C":  [[("G-5", 0, 46), ("A-5", 12, 42), ("A#5", 16, 46), ("A-5", 24, 42), ("G-5", 28, 42), ("E-5", 32, 46), ("F-5", 44, 42),
            ("E-5", 48, 44), ("D-5", 56, 42)],
           [("C-5", 0, 44), ("D-5", 8, 42), ("E-5", 12, 42), ("G-5", 16, 48), ("F-5", 28, 42), ("A-5", 32, 46), ("G-5", 40, 44),
            ("D-5", 48, 42)]],
}


def empty():
    return [{c: "..." for c in CH} for _ in range(ROWS)]


def put(p, row, ch, cell):
    if 0 <= row < ROWS:
        p[row][ch] = cell


def fine_slide(p, ch, row, cmd, rows):
    """A fine volume slide (`D1F` up or `DF1` down by one per row) repeated by D00 for `rows` rows."""
    put(p, row, ch, f"... .. ... {cmd}")
    for r in range(row + 1, row + rows):
        put(p, r, ch, "... .. ... D00")


def hat_pan(row):
    """One pan step per 8th hat: S84 to S8C and back over two bars."""
    k = (row // 2) % 16
    return 4 + k if k <= 8 else 20 - k


# ---------------------------------------------------------------- layers

def drums(p, kind, busy=False):
    """`groove`: kicks on 1 and 3 with a pickup, snare on 2 and 4 with ghosts, 8th hats; `drive`: four on the floor with
    open hats on the 'and' of 1 and 3; `ride`: the groove kick with a lighter snare under 8ths on the closed hat (v6; the ride read as rock, the rows
    are unchanged); `hats`: hats alone;
    `intro`: closed hats on the offbeat 8ths only, centred, no sweep (v5: the swept 8ths read as Vantage's intro).
    `busy` adds 16th hats in the last bar."""
    for bar in range(4):
        b = bar * BAR
        if kind in ("groove", "ride"):
            put(p, b + 0, "kick", f"C-5 {I['kick']} v60")
            put(p, b + 8, "kick", f"C-5 {I['kick']} v54")
            if bar % 2 == 1:
                put(p, b + 14, "kick", f"C-5 {I['kick']} v46")
        if kind == "drive":
            for r in (0, 4, 8, 12):
                put(p, b + r, "kick", f"C-5 {I['kick']} v{62 if r % 8 == 0 else 56}")
            if bar == 3:
                put(p, b + 14, "kick", f"C-5 {I['kick']} v46")
        if kind in ("groove", "drive"):
            put(p, b + 4, "snare", f"C-5 {I['snare']} v{58 if kind == 'drive' else 60}")
            put(p, b + 12, "snare", f"C-5 {I['snare']} v{58 if kind == 'drive' else 60}")
            if bar % 2 == 1:
                put(p, b + 7, "snare", f"C-5 {I['ghost']} v22")
                put(p, b + 15, "snare", f"C-5 {I['ghost']} v20")
            if bar == 3:
                put(p, b + 10, "snare", f"C-5 {I['side']} v36")
        if kind == "ride":
            put(p, b + 4, "snare", f"C-5 {I['snare']} v50")
            put(p, b + 12, "snare", f"C-5 {I['side']} v44")
            for r in range(0, BAR, 2):
                put(p, b + r, "hats", f"C-5 {I['hat']} v{44 if r % 4 == 0 else 32}")
        if kind == "intro":
            for r in (2, 6, 10, 14):
                put(p, b + r, "hats", f"C-5 {I['hat']} v30")
        if kind in ("groove", "drive", "hats"):
            for r in range(0, BAR, 2):
                put(p, b + r, "hats", f"C-5 {I['hat']} v{46 if r % 4 == 0 else 34} S8{hat_pan(b + r):X}")
            if kind == "drive":
                for r in (2, 10):
                    put(p, b + r, "hats", f"C-5 {I['hatopen']} v44 S8{hat_pan(b + r):X}")
            if busy and bar == 3:
                for r in range(1, BAR, 2):
                    put(p, b + r, "hats", f"C-5 {I['hat']} v22 S8{hat_pan(b + r):X}")


def booms(p):
    """Section-weight hits: the boom on beats 1 and 4 of the first bar and on 1 of the third; a low-tom fill ends bar 4."""
    put(p, 0, "perc", f"C-5 {I['boom']} v48")
    put(p, 12, "perc", f"C-5 {I['boom']} v34")
    put(p, 32, "perc", f"C-5 {I['boom']} v44")
    put(p, 60, "perc", f"C-5 {I['tomlow']} v42")
    put(p, 62, "perc", f"C-5 {I['tomlow']} v48")


def loop_bed(p, on):
    """The recorded bar in surround, retriggered every bar; in the last bar its beat-2 snare is replayed on beat 4
    with a sample offset and its downbeat comes an 8th early as a pickup."""
    if not on:
        put(p, 0, "loop", "^^^ .. ... ...")
        return
    for bar in range(4):
        put(p, bar * BAR, "loop", f"C-5 {I['loop']} v52" + (" S91" if bar == 0 else ""))
    put(p, 60, "loop", f"C-5 {I['loop']} v52 O{LOOP_SNARE:02X}")
    put(p, 62, "loop", f"C-5 {I['loop']} v44")


def pulse(p, note, vol, step):
    """The sub pulse: one short sub note every `step` rows (4 = a quiet throb on every beat under the kick; 6 = a
    dotted-quarter drift where nothing else moves), restarting with the pattern."""
    for r in range(0, ROWS, step):
        put(p, r, "pulse", f"{note} {I['pulse']} v{vol}")


def beds(p, sec, a_vol, b_vol, s_vol, b_early=False):
    """Bed A and the string bed retriggered at the top of the pattern in the centre (their fadeouts crossfade the
    previous swell); bed B enters at row 32 and swells through the second half with its own slow attack, in surround
    (with the drum bar, the width of the mix)."""
    put(p, 20, "bedb", "... .. ... S91")
    put(p, 0, "beda", f"{CHORD} {I[sec['beda']]} v{a_vol}" if a_vol and sec["beda"] else "=== .. ... ...")
    put(p, 0, "strbed", f"{CHORD} {I[sec['strbed']]} v{s_vol}" if s_vol and sec["strbed"] else "=== .. ... ...")
    if b_vol and sec["bedb"]:
        if b_early:
            put(p, 0, "bedb", f"{CHORD} {I[sec['bedb']]} v{b_vol}")
        put(p, 32, "bedb", f"{CHORD} {I[sec['bedb']]} v{b_vol}")
    else:
        put(p, 0, "bedb", "=== .. ... ...")


def choir(p, sec, vol):
    """The cluster at pitch on row 0 with a slow shallow panbrello, the octave-up render at half volume on row 40 (a
    call); its envelope fades it in and its fadeout lets the two overlap."""
    if not vol:
        put(p, 0, "choir", "=== .. ... ...")
        return
    put(p, 0, "choir", f"{sec['choir']} {I['choir']} v{vol} Y11")
    put(p, 40, "choir", f"{sec['choir']} {I['choir_hi']} v{vol // 2:02d}")


def arp(p, cell, vol, step):
    """The arp: the cell cycled every `step` rows (2 = 8ths, 1 = 16ths), beats accented, cut by each next note."""
    for k, r in enumerate(range(0, ROWS, step)):
        put(p, r, "arp", f"{cell[k % len(cell)]} {I['arp']} v{vol if r % 4 == 0 else vol - 6:02d}")


def seq(p, phrases, vol=26):
    """Dotted-8th sequence phrases (3 rows a note) in the sequence voice (its own slot, so the tryout can swap it; an
    nna: fade instrument with a short fadeout, so each note just touches the next instead of ringing under the two after
    it), released at the phrase end. v5: no echo (the six-row echo laid every note over its neighbours)."""
    for start, name in phrases:
        for k, n in enumerate(SEQ[name]):
            put(p, start + 3 * k, "seq", f"{n} {I['seq']} v{vol if k % 2 == 0 else vol - 5:02d}")
        put(p, start + 3 * len(SEQ[name]), "seq", "=== .. ... ...")


def riff(p, cells, vol=28):
    """The portamento riff: one held voice whose pitch glides (G18) to the next note every two rows, never retriggered
    within the pattern (cells A A B A over the four bars); an echo one row behind at a third of the volume on the
    other side."""
    if not cells:
        put(p, 0, "riff", "=== .. ... ...")
        put(p, 0, "riffecho", "=== .. ... ...")
        return
    for bar in range(4):
        cell = cells[1 if bar == 2 else 0]
        for k, n in enumerate(cell):
            r = bar * BAR + 2 * k
            first = bar == 0 and k == 0
            put(p, r, "riff", f"{n} {I['riff']} v{vol:02d}" if first else f"{n} .. v{vol:02d} G18")
            put(p, r + 1, "riffecho", f"{n} {I['riff']} v{vol // 3:02d}" if first else f"{n} .. v{vol // 3:02d} G18")


def lead(p, sec, phr):
    """The melody: one of the colour's two phrases (0 or 1) on the lead, doubled by the violins 10 under it."""
    if phr is None:
        put(p, 0, "lead", "=== .. ... ...")
        put(p, 0, "violins", "=== .. ... ...")
        return
    for n, r, v in LEAD[sec][phr]:
        put(p, r, "lead", f"{n} {I['lead']} v{v}")
        put(p, r, "violins", f"{n} {I['violins']} v{max(v - 10, 1):02d}")


def snare_build(p):
    """A snare roll over the last bar: retriggered every three ticks, rising from v18 to v48."""
    for i, r in enumerate(range(48, ROWS, 2)):
        put(p, r, "snare", f"C-5 {I['snare']} v{18 + i * 4} Q03")


# ---------------------------------------------------------------- patterns

def pattern(sec, drone_vol=44, pulse_vol=None, pulse_step=4, beda=None, bedb=None, bedb_early=False, strbed=None,
            choir_vol=None, arp_cell=None, arp_vol=24, arp_step=2, seq_phr=(), riff_cells=None, lead_phr=None,
            drum=None, busy=False, boom=False, loop_on=False):
    s = PEDAL[sec]
    p = empty()
    put(p, 0, "drone", f"{s['drone']} {I['drone']} v{drone_vol}")
    if pulse_vol:
        pulse(p, s["pulse"], pulse_vol, pulse_step)
    beds(p, s, beda, bedb, strbed, bedb_early)
    choir(p, s, choir_vol)
    if arp_cell:
        arp(p, ARP[arp_cell], arp_vol, arp_step)
    seq(p, seq_phr)
    riff(p, RIFF[riff_cells] if riff_cells else None)
    lead(p, sec, lead_phr)
    if drum:
        drums(p, drum, busy)
    if boom:
        booms(p)
    loop_bed(p, loop_on)
    return p


def build():
    pats, order = {}, []

    def add(name, comment, **kw):
        p = pattern(**kw)
        pats[name] = (p, comment)
        order.append(name)
        return p

    # ---- intro on G: the drone under a noise wind, the beds fade in, the pulse, hats, the arp and the violins arrive
    p = add("i1", "intro: drone and wind; the bed swells in", sec="G", drone_vol=16, beda=24)
    put(p, 0, "wind", f"C-5 {I['wind']} v02 D1F")
    for r in range(1, 30):
        put(p, r, "wind", "... .. ... D00")
    add("i2", "intro: the string bed and the choir cluster", sec="G", drone_vol=24, beda=32, strbed=22, choir_vol=24)
    add("i3", "intro: a dotted pulse and sparse offbeat hats", sec="G", drone_vol=30, pulse_vol=24, pulse_step=6, beda=36, strbed=26,
        drum="intro")
    p = add("i4", "intro: the arp, the melody begins; the wind dies", sec="G", drone_vol=34, pulse_vol=26,
            pulse_step=6, beda=40, strbed=28, arp_cell="G", arp_vol=34, lead_phr=0, drum="intro")
    fine_slide(p, "wind", 0, "DF1", 30)
    put(p, 31, "wind", "=== .. ... ...")

    # ---- groove on G: drums; one moving line at a time: arp 8ths, then the sequence, then arp 16ths under the violins
    common = dict(sec="G", pulse_vol=28, beda=42, strbed=28, drum="groove")
    p = add("a1", "groove: drums, arp 8ths, beds", arp_cell="G", **common)
    put(p, 0, "fx", f"C-5 {I['crash']} v44")
    add("a2", "groove: arp 8ths under the melody", arp_cell="G", lead_phr=1, **common)
    add("a3", "groove: the melody alone over the beds (v6: the sequence line is gone)", lead_phr=0, **common)
    add("a4", "groove: the melody's second phrase", lead_phr=1, **common)
    add("a5", "groove: arp 16ths, the melody, the second bed swells", arp_cell="G", arp_step=1, lead_phr=0, bedb=26, **common)
    p = add("a6", "groove: build into the peak", arp_cell="G", arp_step=1, lead_phr=1, bedb=26, busy=True, **common)
    snare_build(p)
    put(p, 48, "fx", f"C-5 {I['revcrash']} v48")

    # ---- peak 1 on G: four on the floor, booms, the recorded bar, the melody over arp 16ths or the sequence
    common = dict(sec="G", pulse_vol=30, beda=46, bedb=28, strbed=30, drum="drive", busy=True, boom=True, loop_on=True)
    p = add("p1", "peak: drive drums, booms, the bar; arp 16ths, the choir calls", arp_cell="G", arp_step=1, arp_vol=26,
            choir_vol=34, lead_phr=0, **common)
    put(p, 0, "fx", f"C-5 {I['crash']} v48")
    add("p2", "peak: the melody alone (v6: no sequence)", lead_phr=1, **common)
    add("p3", "peak: arp 16ths, the choir calls", arp_cell="G", arp_step=1, arp_vol=26, choir_vol=34, lead_phr=0, **common)
    add("p4", "peak: the melody alone", lead_phr=1, **common)

    # ---- the dip: one pattern of drone, beds and a single boom
    p = add("d1", "dip: one boom; drone and beds alone", sec="G", drone_vol=26, beda=36, strbed=22)
    put(p, 0, "perc", f"C-5 {I['boom']} v52")

    # ---- B section, on G since v5 (the Bb-major lift read as a tone shift): the swelling bed under the string bed, the
    # portamento riff as the one line, a light groove on the closed hat (v6: the ride read as rock, the arp figure under
    # the riff was hated); the texture changes, the root does not
    common = dict(sec="G", bedb=24, bedb_early=True, strbed=28, riff_cells="G")
    p = add("b1", "B: the swelling bed, the portamento riff", drone_vol=40, **common)
    put(p, 0, "perc", f"C-5 {I['boom']} v46")
    add("b2", "B: the ride groove joins", pulse_vol=28, drum="ride", **common)
    add("b3", "B: the melody over the riff", pulse_vol=28, drum="ride", lead_phr=0, **common)
    add("b4", "B: the riff alone again (v6: the arp figure is gone)", pulse_vol=28, drum="ride", **common)
    add("b5", "B: the melody's second phrase over the riff", pulse_vol=28, drum="ride", lead_phr=1, **common)
    p = add("b6", "B: the choir calls; into the breakdown", pulse_vol=28, drum="ride", choir_vol=28, **common)
    put(p, 48, "fx", f"C-5 {I['revcrash']} v44")

    # ---- breakdown, on G like the rest since v6 (the C-Mixolydian colour and its sequence line read as out of place):
    # drums out, beds and the choir, the melody over a dotted pulse, then the build; three patterns instead of five
    common = dict(sec="G", beda=40, strbed=26)
    add("c1", "breakdown: drums out; beds and the choir", drone_vol=28, choir_vol=30, **common)
    add("c2", "breakdown: the melody over a dotted pulse", drone_vol=32, lead_phr=0, pulse_vol=24, pulse_step=6, **common)
    p = add("c3", "breakdown: the build; hats, the melody, the snare roll", drone_vol=36, lead_phr=1, drum="hats", busy=True,
            pulse_vol=26, pulse_step=6, choir_vol=30, **common)
    snare_build(p)
    put(p, 36, "fx", f"C-5 {I['swell']} v44")
    put(p, 48, "fx", f"C-5 {I['revcrash']} v48")
    put(p, 24, "wind", f"C-5 {I['wind']} v04 D1F")
    for r in range(25, 63):
        put(p, r, "wind", "... .. ... D00")

    # ---- peak 2 on G: drive drums, booms, the bar; the riff as the line under the melody, then the melody and the arp
    common = dict(sec="G", pulse_vol=30, beda=46, strbed=30, drum="drive", busy=True, boom=True, loop_on=True)
    p = add("p5", "peak 2: the riff on G under the melody; the choir calls", riff_cells="G", choir_vol=34, lead_phr=0, **common)
    put(p, 0, "fx", f"C-5 {I['crash']} v48")
    put(p, 0, "wind", "=== .. ... ...")
    add("p6", "peak 2: the riff", riff_cells="G", lead_phr=1, **common)
    add("p7", "peak 2: the riff, the second bed swells, the choir calls", riff_cells="G", bedb=28, choir_vol=34, lead_phr=0, **common)
    add("p8", "peak 2: the riff", riff_cells="G", bedb=28, lead_phr=1, **common)
    add("p9", "peak 2: the melody, the choir calls (v6: no sequence)", bedb=28, choir_vol=34, lead_phr=0, **common)
    add("p10", "peak 2: arp 16ths (the first figure; v6 retired the second)", arp_cell="G", arp_step=1, arp_vol=26, bedb=28, lead_phr=1, **common)

    # ---- outro on G: drums out, the bar rings once more, the arp thins, the beds and the drone remain; loops to a1
    add("o1", "outro: drums out; the bar, arp 8ths and the melody linger", sec="G", pulse_vol=26, beda=42, strbed=26, arp_cell="G",
        arp_vol=22, lead_phr=0, loop_on=True)
    add("o2", "outro: the bar out; arp, beds, pulse", sec="G", drone_vol=38, pulse_vol=22, beda=38, strbed=22, arp_cell="G", arp_vol=18)
    add("o3", "outro: the beds and the drone", sec="G", drone_vol=30, beda=30, strbed=18)
    p = add("o4", "outro: fading; B04 loops back to a1", sec="G", drone_vol=22, beda=20, strbed=12)
    fine_slide(p, "drone", 32, "DF1", 31)
    put(p, ROWS - 1, "fx", "... .. ... B04")
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
