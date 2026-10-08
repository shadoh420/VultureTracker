"""Rift listening test, round 2: v2 (the layer set the owner liked) with the sequence section (orders 31-52, from about
3:00) rewritten. The owner: the old sequence reads as Nether's melody whatever plays it. These lines are written from
scratch; none takes the old sequence's rhythm (a note on every 8th), its head-and-tail bar shape, its fourth and fifth
leaps, its register or its glides and copies. Each is one voice on channel 9 (channels 10-11 empty), your seq_calliope.
  rift_v2_seq_lament.yaml  long notes, mostly steps, answering the lead after its call in bar 1 (8-bar phrase)
  rift_v2_seq_riff.yaml    a low syncopated riff (3+3+2 sixteenths), narrow, short notes (2-bar figure)
  rift_v2_seq_pulse.yaml   one note pulsing in dotted 8ths (three against four), stepping to its neighbours
  rift_v2_noseq.yaml       the section without a sequence
Needs rift_v2_layers.yaml (make_variants.py). Run: python suite/rift/variants/make_seqlines.py [--build]
"""
import copy
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_variants as mv  # noqa: E402

E = ["...", "..", "...", "..."]


def note(n, v=36):
    return [n, "08", f"v{v:02d}", "..."]


# (row, note, rows it sounds); a note is cut (^^^) after its length unless the next note starts there
LAMENT = [
    [(16, "C-6", 8), (24, "B-5", 4), (28, "A-5", 4), (32, "G-5", 12), (44, "A-5", 4), (48, "E-5", 12)],
    [(16, "G-5", 8), (24, "E-5", 4), (28, "D-5", 4), (32, "C-5", 8), (40, "D-5", 4), (44, "E-5", 16)],
    [(16, "C-6", 8), (24, "B-5", 4), (28, "A-5", 4), (32, "G-5", 12), (44, "A-5", 4), (48, "C-6", 12)],
    [(16, "D-6", 8), (24, "C-6", 4), (28, "B-5", 4), (32, "A-5", 8), (40, "G-5", 4), (44, "A-5", 16)],
]
_X = [(0, "A-3", 2), (3, "A-3", 2), (6, "C-4", 2), (8, "A-3", 2), (11, "D-4", 2), (14, "C-4", 2)]
_Y = [(0, "A-3", 2), (3, "A-3", 2), (6, "C-4", 2), (8, "E-4", 2), (11, "D-4", 2), (14, "G-3", 2)]
_Z = [(0, "A-3", 2), (3, "A-3", 2), (6, "C-4", 2), (8, "A-3", 2), (11, "G-3", 2), (14, "E-3", 2)]


def bars(*bs):
    return [(16 * i + r, n, ln) for i, b in enumerate(bs) for r, n, ln in b]


RIFF = [bars(_X, _Y, _X, _Y), bars(_X, _Y, _X, _Z)]
_P = ["E-5"] * 5
PULSE = []
for tail in (["E-5", "E-5", "D-5", "E-5", "G-5"], ["E-5", "E-5", "C-5", "D-5", "E-5"],
             ["E-5", "E-5", "D-5", "C-5", "A-4"], ["E-5", "E-5", "G-5", "A-5", "G-5"]):
    ev = []
    for b in range(4):                                   # dotted 8ths: rows 0 3 6 9 12 of each bar, the fifth at the end
        pitches = _P if b < 3 else tail
        ev += [(16 * b + r, pitches[i], 2) for i, r in enumerate((0, 3, 6, 9, 12))]
    PULSE.append(ev)


# note volumes matched to v2's old three-voice sequence (-30.7 dB active in orders 31-52): the lines measured
# 1.2 / 1.9 / 2.7 dB under it at v36
VOL = {"rift_v2_seq_lament": 41, "rift_v2_seq_riff": 45, "rift_v2_seq_pulse": 49}


def write_line(g, events, vol=36):
    mv.blank(g, [9, 10, 11])
    starts = {r for r, _, _ in events}
    for r, n, ln in events:
        g[r][8] = note(n, vol)
        end = r + ln
        if end < 64 and end not in starts:
            g[end][8] = ["^^^", "..", "...", "..."]
    last = max(events)
    if last[0] + last[2] >= 64:                          # a note held to the pattern's end fades over its last two rows
        g[61][8] = ["...", "..", "...", "D0F"]
        g[62][8] = ["...", "..", "...", "D0F"]
        g[63][8] = ["^^^", "..", "...", "..."]


def main(build):
    src = HERE / "rift_v2_layers.yaml"
    song = yaml.safe_load(src.read_text(encoding="utf-8"))
    base = [mv.parse(song["patterns"][o]) for o in song["orders"]]
    seq_orders = [k for k, g in enumerate(base) if mv.notes_in(g, [9])]
    song["samples"] = {k: {**v, "file": str((HERE / v["file"]).resolve()), "_here": True} for k, v in song["samples"].items()}
    made = {}
    for name, lines, header in [
        ("rift_v2_seq_lament", LAMENT, "v2 with the sequence section rewritten: a lament, long notes, mostly steps, after the lead's call."),
        ("rift_v2_seq_riff", RIFF, "v2 with the sequence section rewritten: a low syncopated riff, short notes."),
        ("rift_v2_seq_pulse", PULSE, "v2 with the sequence section rewritten: one note pulsing in dotted 8ths, stepping to its neighbours."),
        ("rift_v2_noseq", None, "v2 without the sequence."),
    ]:
        grids = copy.deepcopy(base)
        for i, k in enumerate(seq_orders):
            if lines is None:
                mv.blank(grids[k], [9, 10, 11])
            else:
                write_line(grids[k], lines[i % len(lines)], VOL[name])
        s = copy.deepcopy(song)
        s["module"]["title"] = name.replace("rift_", "Rift ").replace("_", " ")
        made[name] = (s, grids, header)
    for name, (s, grids, header) in made.items():
        npat, nord = mv.write(name, s, grids, header)
        print(f"{name}: {nord} orders, {npat} patterns")
    if build:
        ff = subprocess.run([sys.executable, "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                            capture_output=True, text=True).stdout.strip()
        procs = []
        for name in made:
            y = HERE / f"{name}.yaml"
            cmd = f'"{sys.executable}" -m vulturetracker build "{y}" --render "{y.with_suffix(".wav")}" && ' \
                  f'"{ff}" -y -loglevel error -i "{y.with_suffix(".wav")}" -b:a 192k "{y.with_suffix(".mp3")}"'
            procs.append((name, subprocess.Popen(cmd, shell=True, cwd=mv.ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)))
        for name, p in procs:
            out = p.communicate()[0]
            print(name, "exit", p.returncode, out.strip().splitlines()[-1] if out.strip() else "")


if __name__ == "__main__":
    main("--build" in sys.argv)
