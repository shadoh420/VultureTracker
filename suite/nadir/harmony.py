"""Harmonic density of a Nadir build, measured from its patterns: per order, how many pitch classes the sustained and
ringing layers stack on each row (the GUI's sounding table, with chord samples expanded to their voicings) and how often
two of them sit a semitone or a major seventh apart; plus, for the sequence channel, how many of its own notes ring at
once (an nna: fade instrument keeps every note fading under the next). A check of the arrangement, not of the sound.
Run: python suite/nadir/harmony.py [song.yaml] [--v5]  (default: nadir.yaml beside this file; --v5 = the open voicings)"""
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from vulturetracker.gui import facts_of, sounding_table  # noqa: E402
from vulturetracker.notation import parse_note  # noqa: E402
from vulturetracker.song import load_song_text  # noqa: E402

# chord samples: the notes each voicing holds when the cell plays C-5 (kit.yaml, gen_strings.py); a cell on another note
# transposes them. Every other pitched sample sounds its cell note.
VOICINGS = {
    "beda_g": "G-2 D-3 A-3 A#3 D-4", "beda_c": "C-3 G-3 A#3 D-4 E-4", "bedb_bb": "A#2 F-3 A-3 D-4 F-4", "bedb_g": "G-2 D-3 F-3 A-3 D-4",
    "strbed_g": "G-3 D-4 A-4 A#4 D-5", "strbed_bb": "A#3 F-4 A-4 D-5 F-5", "strbed_c": "C-4 G-4 A#4 D-5 E-5",
    "choir": "G-3 A-3 D-4 E-4 G-4", "choir_hi": "G-4 A-4 D-5 E-5 G-5",
}
if "--v5" in sys.argv:  # the v5 voicings of the same sample names (root and fifth); default: the v4 ones above
    VOICINGS.update({"beda_g": "G-2 D-3 G-3 D-4", "beda_c": "C-3 G-3 C-4 G-4", "bedb_g": "G-2 D-3 G-3 D-4",
                     "strbed_g": "G-3 D-4 G-4 D-5", "strbed_bb": "A#3 F-4 A#4 F-5", "strbed_c": "C-4 G-4 C-5 G-5",
                     "choir": "G-3 D-4 G-4", "choir_hi": "G-4 D-5 G-5"})  # the choir without its ninth since v6
UNPITCHED = {"kick", "snare", "hats", "perc", "loop", "fx", "wind"}
NAMES = "C C# D D# E F F# G G# A A# B".split()


def pitch_classes(entry, smp_name):
    if smp_name in VOICINGS:
        shift = parse_note(entry["note"]) - parse_note("C-5")
        return {(parse_note(n) + shift) % 12 for n in VOICINGS[smp_name].split()}
    return {parse_note(entry["note"]) % 12}


def main():
    path = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), HERE / "nadir.yaml"))
    mod, warnings = load_song_text(path.read_text(encoding="utf-8"), path.parent, str(path))
    facts = facts_of(mod, warnings)
    table = sounding_table(mod, facts)
    chans = facts["channels"]
    # channels whose instrument is nna: fade keep every note fading under the next: rows a note keeps ringing =
    # 1024 / fadeout ticks (IT fades 0..1024 by `fadeout` a tick) over `speed` ticks a row
    fade_rows = {}
    for ci, ch in enumerate(chans):
        ins = next((i for i in (mod.instruments or []) if i.name.lower() == ch.lower()), None)
        if ins and ins.nna == 3 and ins.fadeout:
            fade_rows[ci] = 1024 / ins.fadeout / mod.speed
    ring_cols = [ci for ci in fade_rows if chans[ci].lower() in ("seq", "lead", "violins")]
    total_rows = total_clash = 0
    print(f"{'ord':>3} {'pat':4} {'pcs':>4} {'clash%':>6}  worst pairs (channel:note)          "
          + "  ".join(f"{chans[ci]} ringing" for ci in ring_cols))
    for oi, rows in enumerate(table):
        o = facts["orders"][oi]
        pcs_sum = clash_rows = 0
        pairs = Counter()
        pat = mod.patterns[mod.orders[[k for k, x in enumerate(mod.orders) if x < 254][oi]]]
        ring_max = {ci: 0 for ci in ring_cols}
        for r, entries in enumerate(rows):
            stack = []  # (pc, label)
            for e in entries:
                if chans[e["ch"]].lower() in UNPITCHED or e["sample"] is None:
                    continue
                name = mod.samples[e["sample"] - 1].name
                for pc in pitch_classes(e, name):
                    stack.append((pc, f"{chans[e['ch']]}:{NAMES[pc]}"))
            pcs = {pc for pc, _ in stack}
            pcs_sum += len(pcs)
            clash = False
            for i in range(len(stack)):
                for j in range(i + 1, len(stack)):
                    if (stack[i][0] - stack[j][0]) % 12 in (1, 11):  # a semitone or a major seventh, any two layers or one voicing
                        clash = True
                        pairs[tuple(sorted((stack[i][1], stack[j][1])))] += 1
            clash_rows += clash
            for ci in ring_cols:
                ringing = sum(1 for rr in range(max(0, int(r - fade_rows[ci])), r + 1)
                              if pat.rows[rr][ci].note is not None and pat.rows[rr][ci].note < 120)
                ring_max[ci] = max(ring_max[ci], ringing)
        n = len(rows) or 1
        total_rows += n
        total_clash += clash_rows
        worst = ", ".join(f"{a}+{b} {c}" for (a, b), c in pairs.most_common(2))
        print(f"{oi:>3} {o['pattern']:4} {pcs_sum / n:4.1f} {100 * clash_rows / n:5.0f}%  {worst:38.38} "
              + "  ".join(f"{str(ring_max[ci] or '-'):>{len(chans[ci]) + 8}}" for ci in ring_cols))
    print(f"rows with a semitone clash: {100 * total_clash / total_rows:.0f}% of {total_rows}; a fading note rings "
          + ", ".join(f"{chans[ci]} {fade_rows[ci]:.1f} rows" for ci in ring_cols))


if __name__ == "__main__":
    main()
