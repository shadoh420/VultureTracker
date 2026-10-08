"""Rift, Step 3 of suite/NEXT-PROMPT.md: the full form, laid out by Nether Animal's form map (BRIEF.md "## Form"; the
reference's layers per order counted by scratch/ut99-clean/rifttools/formmap.py and cellorder.py, no pitch read), the
plan in suite/HANDOFF.md item 2, "Step 3".

`python suite/rift/gen_form.py` rewrites rift.yaml's patterns and order list and nothing else before them but the
"Step 3" paragraph of the header (the channel lines, samples and instruments stay as the song has them: the owner's mix
and picks). Every layer's columns come from its own writer: the loop's figure() and the form's variants (gen_hit.thin,
gen_strings.closing, gen_drone.form_column, gen_vocal.fade, gen_second.figure(fuller=False), gen_second.close,
gen_seq.columns over the orders, so the sequence's copies spill into the next order and stop with a cut). The approved
break, hats, crash, sub, stab and bed are the loop's own cells row for row (rift_loop.yaml, the 8-bar loop the sounds
were picked in), each inside the rows the form gives it per order (a window: the reference's layer plays only part of
the pattern there); the break and the sub (looped samples) are cut where they leave, the bed released or faded out, and
the last bar steps the drums down as the reference's does. The muted round-4 call (channels 7-8) keeps its lines,
sample and instrument; its cells stay in rift_loop.yaml.
"""
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def writer(name):
    """A layer writer by its file (suite/nadir, which the writers put on the path, has a gen_strings.py too)."""
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


gen_seq, gen_lead, gen_hit, gen_strings, gen_drone, gen_noise, gen_vocal, gen_second = (
    writer(n) for n in ("gen_seq", "gen_lead", "gen_hit", "gen_strings", "gen_drone", "gen_noise", "gen_vocal", "gen_second"))

SECTIONS = [("intro", 4), ("build", 6), ("a", 8), ("break1", 2), ("b", 4), ("peak", 6), ("break2", 2), ("c", 17), ("outro", 6)]
N = sum(n for _, n in SECTIONS)                            # 55 orders, the reference's
FULL = (0, 63)


def span(a, b):
    return list(range(a, b + 1))


def each(orders, value):
    return {o: value for o in orders}


# ---- the approved drums, sub, stab and bed: which orders, inside which rows (first, last) of the loop's cells
HATS = {**each(span(2, 17) + span(20, 22) + span(24, 53), FULL), 23: (0, 32), 54: (0, 54)}   # out in the break (18-19)
CRASH = each([4, 6, 8, 10, 12, 14, 16, 18] + span(24, 30) + [33, 35, 36, 37, 39, 40, 41, 43, 45, 47, 49, 51, 53], (0, 0))
BREAK = {**each(span(10, 17) + span(24, 29) + span(33, 53), FULL), 54: (0, 56)}   # the reference's breaks and drum riff
SUB = {**each(span(4, 17) + span(24, 29) + span(32, 48), FULL),                   # the build's kick and the peak's low end
       18: (26, 32), **each([20, 21, 22, 23, 50, 52], (0, 32)), 49: (0, 0), 51: (0, 0)}   # the reference's sub rows
STAB = {**each([4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 30], (0, 15)), **each(span(24, 29), FULL)}   # bar 1; the peak every bar
BED = {**each([6, 7, 8] + span(18, 23), "strike"), 9: "last", 24: "cut"}   # "last": struck, released (===) on row 32;
# "cut": faded by D0F on rows 0-1 (as the reference cuts its stab; libopenmpt slides it from the first tick: 4/64 at the
# end of row 0, silent early in row 1) and cut on row 2, where the reference cuts its bed (a hard cut there read 16.8 dB
# over the bed's steady 12-20 kHz energy: check round 1)
# the reference's last bar steps its drums down (its order 54: the drum riff re-struck at v64/40/20/10/5 on rows 48-56,
# the hats v12 then 6/3/1 on rows 50-54, its riff and second break cut on row 58): ours on the approved rows, the hats'
# volumes scaled by the same steps, the break (one bar struck on row 48) slid down by its volume column through the same
# levels (dNN on ticks 1-3: 64, 40, 22, 10 and 4 at rows 48, 50, 52, 54 and 56, silent early in row 57; set volumes
# stepped, and the v20 step on the break's snare made a burst above 12 kHz), then cut on row 58 (its sample loops: uncut,
# it played to row 63 and wrapped into the render's tail)
LAST = 54
LAST_BAR = {0: {48: "d04", 49: "d04", 50: "d03", 51: "d03", 52: "d02", 53: "d02", 54: "d01", 55: "d01", 56: "d01", 57: "d01",
                58: None},
            1: {50: 5, 52: 4, 54: 1}}                       # column -> {row: volume (or a volume-column field), None: cut}

# ---- the layers, by their writers
SEQ = {o: "loop" if o % 2 else "loop_b" for o in span(31, 52)}          # bar 4 alternating, as the reference's does
LEAD = {o: "loop_b" if o in (34, 38, 42, 44, 46, 48) else "loop" for o in span(20, 23) + span(26, 52)}
HIT = {**each(span(0, 9) + span(18, 23), "four"), **each(span(10, 17) + [24, 25], "two")}
STRINGS = {**each(span(26, 29), "play"), 30: "close"}
DRONE = {31: "entry", **each(span(32, 40), "flat"), **{o: "swell" if o % 2 else "hold" for o in span(41, 48)}, 49: "fade"}
NOISE = set(span(0, 6) + [8, 10, 12, 14, 16, 18, 24, 26, 28, 30, 33, 37])  # every pattern, then every second, then fourth
VOCAL = {41: "strike", 45: "strike", **each([42, 43, 44, 46, 47, 48], "hold"), 49: "fade"}
SECOND = {41: "simple", 45: "simple", 43: "full", 47: "full", 42: "close", 46: "close", 44: "close_pickup", 48: "close_pickup"}

HEAD = "# Step 3, the form"
PARAGRAPH = """# Step 3, the form (suite/rift/gen_form.py writes every pattern and the order list; don't edit them by hand): Nether
# Animal's form map, 55 orders in its section lengths (BRIEF.md "## Form"): intro 0-3, build 4-9, A 10-17, break 18-19,
# B 20-23, peak 24-29, break 30-31, C 32-48, outro 49-54 (5:20 at 165 BPM). Each layer plays where the reference's
# plays, its columns from its own writer: the loop's figures and the form's variants (the hit two a pattern without the
# offset in A and the peak's first two, the strings' closing fade, the drone's entry swell, flat v30 and fade, the vocal
# pad's strike every fourth pattern and fade, the second line's other pattern in orders 41 and 45, and their exits).
# The approved break, hats, crash, sub, stab and bed are the loop's cells row for row (rift_loop.yaml, the 8-bar loop
# the sounds were picked in), each inside the rows the form gives it, cut or faded where they leave, and the last bar
# steps the drums down as the reference's does. The layer paragraphs above describe the loop: their gen_*.py pattern
# commands write nothing here. The plan, and each departure from the reference's map with its reason:
# suite/HANDOFF.md item 2, "Step 3".
"""
PARAGRAPH_END = 'suite/HANDOFF.md item 2, "Step 3".\n'                  # the paragraph's last line, old and new


def loop_cells(path=HERE / "rift_loop.yaml"):
    """The loop's cells of channels 1-6 (break, hats, crash, sub, stab, bed) per row; the two patterns agree there."""
    cells, pat = {}, None
    for line in path.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"  (\w+):$", line)
        if m:
            pat = m.group(1)
            continue
        r = re.match(r"\s+(\d\d): (.*)$", line)
        if pat in ("loop", "loop_b") and r:
            cells.setdefault(pat, {})[int(r.group(1))] = [c.strip() for c in r.group(2).split("|")][:6]
    assert cells["loop"] == cells["loop_b"] and len(cells["loop"]) == 64
    return [{r: row[c] for r, row in cells["loop"].items() if row[c] != "..."} for c in range(6)]


def window(col, rows):
    return {r: c for r, c in col.items() if rows and rows[0] <= r <= rows[1]}


FIELDS = [r"[A-G][-#]\d|===|\^\^\^|~~~|\.\.\.", r"\d\d|\.\.", r"[a-hpv]\d\d|\.\.\."]   # note, instrument, volume


def with_volume(cell, v):
    """The cell with its volume field set to vNN (v a number) or to the field v; its note, instrument and effect kept.
    The fields are read by their shape, as the song format reads them, so a short cell ("C-5 01 O9C") keeps its effect."""
    toks, out = cell.split(), []
    for shape, empty in zip(FIELDS, ("...", "..", "...")):
        out.append(toks.pop(0) if toks and re.fullmatch(shape, toks[0]) else empty)
    out[2] = f"v{v:02d}" if isinstance(v, int) else v
    return " ".join(out + toks)


def order_columns(o, drums, seq):
    """The 26 columns of order o, each {row: cell}."""
    brk, hats, crash, sub, stab, bed = drums
    bed_col = {"strike": {0: bed[0]}, "last": {0: bed[0], 32: "==="},
               "cut": {0: "... .. ... D0F", 1: "... .. ... D0F", 2: "^^^"}}.get(BED.get(o), {})
    lead = gen_lead.figure()[LEAD[o]] if o in LEAD else [{}, {}]
    hit = {"four": gen_hit.figure()["loop"], "two": gen_hit.thin()}.get(HIT.get(o), [{}, {}])
    strings = {"play": gen_strings.figure()["loop"], "close": gen_strings.closing()}.get(STRINGS.get(o), [{} for _ in range(6)])
    drone = gen_drone.form_column(DRONE[o]) if o in DRONE else [{}]
    noise = gen_noise.figure()["loop"] if o in NOISE else [{}]
    vocal = {"strike": gen_vocal.figure()["loop"], "hold": gen_vocal.figure()["loop_b"], "fade": gen_vocal.fade()}.get(VOCAL.get(o), [{}])
    second = {"full": gen_second.figure()["loop"], "simple": gen_second.figure(fuller=False)["loop"],
              "close": gen_second.close(False), "close_pickup": gen_second.close(True)}.get(SECOND.get(o), [{}, {}])
    brk_col = window(brk, BREAK.get(o)) if o in BREAK else {0: "^^^"} if o - 1 in BREAK else {}   # its sample loops: cut
    sub_col = window(sub, SUB.get(o))
    # the sub loops too: where it leaves or its window starts later (18, 19, 30, 53) it fades by D0F on rows 0-1 and is
    # cut on row 2 (the passing E of row 60 rings into 18 and 30, the row-32 A's short tail into 19 and 53; a hard cut
    # read 17.4 dB over its steady 12-20 kHz level: check round 2). The rule reads the loop's sub striking row 0.
    assert 0 in sub
    if o - 1 in SUB and 0 not in sub_col:
        assert not set(sub_col) & {0, 1, 2}, o
        sub_col.update({0: "... .. ... D0F", 1: "... .. ... D0F", 2: "^^^"})
    cols = ([brk_col, window(hats, HATS.get(o)), window(crash, CRASH.get(o)), sub_col,
             window(stab, STAB.get(o)), bed_col, {}, {}] + seq[o] + lead + hit + strings + drone + noise + vocal + second)
    assert len(cols) == 26, (o, len(cols))
    for c, steps in (LAST_BAR.items() if o == LAST else ()):
        for r, v in steps.items():
            cols[c][r] = "^^^" if v is None else with_volume(cols[c].get(r, "..."), v)
    return cols


def pattern_text(name, cols):
    lines = [f"  {name}:", "    rows: 64", "    data: |"]
    for r in range(64):
        if r % 16 == 0:
            lines.append(f"      ; bar {r // 16 + 1}")
        lines.append(f"      {r:02d}: " + " | ".join(f"{c.get(r, '...'):14s}" for c in cols).rstrip())
    return "\n".join(lines)


def form():
    """The patterns (name -> columns) and the order list (names)."""
    drums = loop_cells()
    seq = gen_seq.columns([SEQ.get(o) for o in range(N)])
    section = [s for s, n in SECTIONS for _ in range(n)]
    pats, names, orders = {}, {}, []
    for o in range(N):
        cols = order_columns(o, drums, seq)
        key = tuple(tuple(sorted(c.items())) for c in cols)
        if key not in names:
            k = 1 + sum(1 for n in pats if n.startswith(section[o] + "_"))
            names[key] = f"{section[o]}_{k}"
            pats[names[key]] = cols
        orders.append(names[key])
    return pats, orders


def main(path=HERE / "rift.yaml"):
    b = path.read_bytes()
    crlf = b"\r\n" in b
    t = b.decode("utf-8").replace("\r\n", "\n")
    head, sep, _ = t.partition("\npatterns:\n")
    assert sep
    cut = head.find(HEAD)
    if cut >= 0:                                            # the paragraph alone: lines after it stay
        end = head.find(PARAGRAPH_END, cut)
        if end < 0:
            raise SystemExit(f"the song's Step 3 paragraph no longer ends with {PARAGRAPH_END.strip()!r}: restore that line "
                             "or delete the paragraph (gen_form.py writes it)")
        head = head[:cut] + PARAGRAPH + head[end + len(PARAGRAPH_END):]
    else:
        at = head.index("\nmodule:\n") + 1
        head = head[:at] + PARAGRAPH + head[at:]
    pats, orders = form()
    t = head + "\npatterns:\n" + "\n".join(pattern_text(n, c) for n, c in pats.items()) + "\n\n"
    at = 0
    rows = []
    for s, n in SECTIONS:                                   # the order list, one section a line
        rows.append(", ".join(orders[at: at + n]))
        at += n
    t += "orders: [" + ",\n         ".join(rows) + "]\n"
    if crlf:
        t = t.replace("\n", "\r\n")
    path.write_bytes(t.encode("utf-8"))
    at = 0
    for s, n in SECTIONS:
        print(f"{s:6s} orders {at:2d}-{at + n - 1:2d}: {' '.join(orders[at: at + n])}")
        at += n
    print(f"wrote {path.name}: {len(pats)} patterns, {len(orders)} orders")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve() if sys.argv[1:] else HERE / "rift.yaml")
