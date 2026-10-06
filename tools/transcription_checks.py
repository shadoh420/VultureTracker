"""Checks on a transcription made by tools/transcribe_audio.py, stems_to_song.py and make_notes.py: the downbeats, the
transcribers against their stems, the tab read back, the exported .it's DELTA, and what the notes leave out.

  <env>/torch/Scripts/python tools/transcription_checks.py downbeats WORK [--short-bar ROW]
  <env>/bp/Scripts/python tools/transcription_checks.py score WORK [STEM ...]
  <env>/bp/Scripts/python tools/transcription_checks.py gp5 WORK [--notes NAME]
  <env>/bp/Scripts/python tools/transcription_checks.py it WORK [--song NAME]
  <env>/bp/Scripts/python tools/transcription_checks.py missing WORK [--downbeat-row K] [--short-bar ROW] [--notes NAME]
                                                                     [--song NAME]

WORK is a folder transcribe_audio.py made (<name>.wav, stems/<model>/, midi/, <name>-basic-pitch.json). Every check uses
the grid the other tools use: the BPM in <name>-basic-pitch.json, row 0 where the drum stem's level rises fold
(stems_to_song.py's grid_phase); rows are its 16ths, counted from the recording's row 0 unless said otherwise.
  downbeats  (torch env, with beat_this) the grid's fold peak (under 1.25 x its mean the json's BPM has no clear grid: set
             it from tempo_check.py); beat_this's downbeats on the recording (final0, no DBN): its BPM (the tempo octave),
             K = their most common row mod 16 and its share, the rows between them, the runs of one phase; ADTOF's crashes
             on bar lines; ADTOF's hits on a straight 16th and on a triplet 8th (a swing or triplet feel). --short-bar
             ROW: the shares on the bar lines with a 2/4 bar at that row (stems_to_song.py's and make_notes.py's option).
  score      each pitched stem's notes (midi/<stem>_basic_pitch.mid, midi_bp58/<stem>_basic_pitch.mid: basic-pitch with
             --minimum-note-length 58, midi/<stem>_yourmt3.mid) against the stem as transcription_diff.py counts them:
             precision (the stem peaks at the note's pitch for half of it), recall (the stem's fundamental peaks a note
             covers), and the stem onsets with a note within 30 ms; the quiet notes (velocity under 45, under 40 for
             other: what make_notes.py drops) against the rest. Picks per stem the notes with the higher F1 of precision
             and recall, and keeps their quiet notes when those measure within 0.02 of the rest; prints make_notes.py's
             --part and --keep-quiet arguments. Stems under -50 dBFS are left out, as make_notes.py leaves them.
  gp5        <notes>.gp5 read back by `vulturetracker import` against <notes>.mid: per part the (row, note) pairs in
             both and in one only; the drums by rows (default <name>-notes).
  it         <song>.it (made by `vulturetracker export <song>.yaml -f it`) rendered as stems_to_song.py renders the
             song, its DELTA beside the song's in <song>.json (default <name>-B-sections).
  missing    rows where a stem sounds (within 30 dB of its loudest row) but no note of its part sounds in the MIDI or
             the tab, and the bars with the most (numbered as make_notes.py writes them: --downbeat-row K, --short-bar
             ROW); for the drums, the song's hit rows with no MIDI hit (the song built with --row0 (16 - K) % 16)."""
import argparse
import bisect
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "tools"), str(REPO)]
from stems_to_song import SR, bar_starts, fold, grid_phase, rises  # noqa: E402

PITCHED = ("guitar", "bass", "other", "piano", "vocals")
NOTES = {"basic-pitch": "midi/{}_basic_pitch.mid", "bp58": "midi_bp58/{}_basic_pitch.mid", "yourmt3": "midi/{}_yourmt3.mid"}
SKIP = ("...", "===", "^^^", "")  # pattern cells with no note


def runs(rows):
    """Runs of downbeats in one bar phase: [(first row, last row, row mod 16, downbeats)]."""
    out = []
    for r in rows:
        if out and out[-1][2] == r % 16:
            out[-1] = (out[-1][0], r, r % 16, out[-1][3] + 1)
        else:
            out.append((r, r, r % 16, 1))
    return out


def bar_lines(k, short, total):
    """Recording rows where bars start, up to `total`: k mod 16, and 8 rows later after a 2/4 bar at row `short`."""
    b0 = k % 16 - (16 if k % 16 else 0)  # make_notes.py's first bar line, at or before row 0
    return {r + b0 for r in bar_starts(total - b0, None if short is None else short - b0)}


def choose(scores, tolerance=0.02):
    """The notes to use: the name with the highest F1 of (precision, recall), and whether its quiet notes measure as
    precise as the rest (within `tolerance`). `scores`: {name: (precision, recall, quiet precision or None, rest's)}."""
    f1 = {k: 2 * p * r / (p + r) if p + r else 0.0 for k, (p, r, _, _) in scores.items()}
    best = max(f1, key=f1.get)
    q, rest = scores[best][2:]
    return best, q is not None and q >= rest - tolerance


def mmss(t):
    t = max(0.0, t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


def rel(f):
    return f.relative_to(REPO) if f.is_relative_to(REPO) else f


class Work:
    """A transcription folder: its name, stems folder, and the tools' grid."""

    def __init__(self, folder):
        import soundfile as sf
        self.path = folder.resolve()
        sides = list(self.path.glob("*-basic-pitch.json"))
        if len(sides) != 1:
            sys.exit(f"want one <name>-basic-pitch.json in {self.path} (made by transcribe_audio.py), found {len(sides)}")
        self.name = sides[0].name[:-len("-basic-pitch.json")]
        self.bpm = json.loads(sides[0].read_text(encoding="utf-8"))["bpm"]
        self.p = 60 / self.bpm / 4
        found = [d for d in (self.path / "stems").glob("*") if d.is_dir() and any(d.glob("*.wav"))]
        self.stems = found[0] if len(found) == 1 else self.path / "stems" / "htdemucs_ft"
        if not self.stems.is_dir():
            sys.exit(f"no stems folder in {self.path / 'stems'}")
        beat = self.stems / "drums.wav" if (self.stems / "drums.wav").is_file() else sorted(self.stems.glob("*.wav"))[0]
        self.beat = sf.read(beat, always_2d=True)[0]
        self.g0 = grid_phase(self.beat, self.p)

    def row(self, t):
        return round((t - self.g0) / self.p)

    def t(self, row):
        return self.g0 + row * self.p

    def file(self, name):
        f = self.path / name  # a name in WORK, or an absolute path
        if not f.is_file():
            sys.exit(f"no such file: {f}")
        return f


def downbeats(w, short):
    import numpy as np
    import pretty_midi as pm
    from beat_this.inference import File2Beats
    from tempo_check import CLEAR
    h = fold(*rises(w.beat), w.p)
    print(f"grid: {w.bpm} BPM ({w.name}-basic-pitch.json), row 0 at {w.g0 * 1000:.1f} ms; the fold's peak "
          f"{h.max() / h.mean():.2f} x its mean" + ("" if h.max() / h.mean() >= CLEAR else
                                                    f": under {CLEAR}, no clear grid; set the json's bpm from tempo_check.py"))
    beats, downs = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)(str(w.file(f"{w.name}.wav")))
    rows = [w.row(t) for t in downs]
    if len(rows) < 2:
        sys.exit(f"beat_this found {len(rows)} downbeats")
    k, n = Counter(r % 16 for r in rows).most_common(1)[0]
    print(f"beat_this: {len(beats)} beats at {60 / np.median(np.diff(beats)):.2f} BPM (median interval); {len(rows)} downbeats, "
          f"K = {k}: {n} of them ({n / len(rows):.0%}); rows between downbeats: "
          + ", ".join(f"{d} x{c}" for d, c in Counter(np.diff(rows).tolist()).most_common(5)))
    print("runs of one phase (first and last downbeat, row mod 16, downbeats): "
          + "; ".join(f"{mmss(w.t(a))}{'-' + mmss(w.t(b)) if b > a else ''} {m} ({c})" for a, b, m, c in runs(rows)))
    adtof = w.path / "midi" / "drums_adtof.mid"
    hits = [(n.start, n.pitch) for i in pm.PrettyMIDI(str(adtof)).instruments for n in i.notes] if adtof.is_file() else []
    crashes = [w.row(t) for t, key in hits if key in (49, 57)]
    if short is not None and (short - k) % 16:
        sys.exit(f"--short-bar {short} does not start a bar of K = {k} (a multiple of 16 rows from it)")
    total = max(rows + crashes) + 16
    for label, s in [(f"K = {k}", None)] + ([(f"K = {k}, a 2/4 bar at row {short}", short)] if short is not None else []):
        lines = bar_lines(k, s, total)
        print(f"on the bar lines with {label}: downbeats {sum(r in lines for r in rows)} of {len(rows)}"
              + (f", ADTOF's crashes {sum(r in lines for r in crashes)} of {len(crashes)}" if crashes else ""))
    if hits:
        beat = np.array([((t - w.g0) / w.p - k) % 4 for t, _ in hits])  # where in the beat, in rows from a bar line
        off16 = np.abs(beat - np.round(beat)) * w.p
        off3 = np.minimum(np.abs(beat - 4 / 3), np.abs(beat - 8 / 3)) * w.p
        print(f"ADTOF's {len(hits)} hits: on a straight 16th (within 15 ms) {np.mean(off16 <= 0.015):.0%}, "
              f"on a triplet 8th {np.mean(off3 <= 0.015):.0%}")


def score(w, stems):
    import librosa
    import numpy as np
    import pretty_midi as pm
    import soundfile as sf
    from transcription_diff import HOP, LO, NB, SR as CQT_SR, stem_peaks
    fps = CQT_SR / HOP
    args = []
    for stem in stems or [s for s in PITCHED if (w.stems / f"{s}.wav").is_file()]:
        wav = w.file(w.stems / f"{stem}.wav")
        if np.sqrt(np.mean(sf.read(wav)[0] ** 2)) < 10 ** (-50 / 20):
            print(f"{stem}: left out, the stem is under -50 dBFS")
            continue
        y, _ = librosa.load(wav, sr=CQT_SR)
        peak, ref = stem_peaks(y)
        onsets = librosa.onset.onset_detect(y=y, sr=CQT_SR, hop_length=HOP, units="time")
        quiet_v, scores = 40 if stem == "other" else 45, {}
        for name, pat in NOTES.items():
            f = w.path / pat.format(stem)
            if not f.is_file():
                continue
            notes = [n for i in pm.PrettyMIDI(str(f)).instruments if not i.is_drum for n in i.notes]
            roll, good = np.zeros_like(peak), []
            for nt in notes:  # transcription_diff.py's count
                i, j, k = int(nt.start * fps), int(nt.end * fps), nt.pitch - LO
                if not 0 <= k < NB or j <= max(0, i):
                    continue
                seg = peak[k, max(0, i):j]
                good.append((bool(seg.size) and seg.mean() >= 0.5, nt.velocity < quiet_v, nt.end - nt.start >= 0.05))
                roll[k, max(0, i - 3):j + 3] = True
            g = np.array(good, dtype=bool).reshape(-1, 3)
            p, r = float(g[:, 0].mean()) if len(g) else 0.0, float((ref & roll).sum() / max(1, ref.sum()))
            quiet, rest = g[g[:, 2] & g[:, 1], 0], g[g[:, 2] & ~g[:, 1], 0]
            starts = np.array(sorted({round(n.start, 3) for n in notes}))
            cover = np.mean([np.min(np.abs(starts - t)) <= 0.03 for t in onsets]) if len(starts) and len(onsets) else 0.0
            scores[name] = (p, r, float(quiet.mean()) if len(quiet) else None, float(rest.mean()) if len(rest) else 0.0)
            print(f"{stem:6s} {name:11s}: {len(notes):5d} notes, precision {p:.2f}, recall {r:.2f}, stem onsets with a note "
                  f"{cover:.2f}; of those >= 50 ms (make_notes keeps them): {len(rest)} at velocity >= {quiet_v} precision "
                  f"{scores[name][3]:.2f}, {len(quiet)} quieter " + (f"{scores[name][2]:.2f}" if len(quiet) else "-"))
        if scores:
            best, keep = choose(scores)
            print(f"{stem:6s} pick: {best}" + (", its quiet notes kept" if keep else ""))
            args += [f"--part {stem}={rel(w.path / NOTES[best].format(stem))}"] + ([f"--keep-quiet {stem}"] if keep else [])
    print("make_notes.py arguments: " + " ".join(args))


def imported(gp5):
    """The song `vulturetracker import` makes of a .gp5: {part (its channels' first word): {(row, note)}}, pattern rows."""
    import yaml
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, "-m", "vulturetracker", "import", str(gp5), "-o", f"{d}/t.yaml"], cwd=REPO, check=True,
                       stdout=subprocess.DEVNULL)
        song = yaml.safe_load(Path(d, "t.yaml").read_text(encoding="utf-8"))
    names = [c["name"].split()[0].lower() for c in song["module"]["channels"]]
    got, base = {}, 0
    for pid in song["orders"]:
        pat = song["patterns"][pid]
        for line in pat["data"].splitlines():
            r, cells = line.split(":", 1)
            for ch, cell in zip(names, cells.split("|")):
                if cell.split()[0] not in SKIP:
                    got.setdefault(ch, set()).add((base + int(r), cell.split()[0]))
        base += pat["rows"]
    return got, sorted({p["rows"] for p in song["patterns"].values()})


def gp5(w, notes):
    import pretty_midi as pm
    from vulturetracker.gpimport import note_name
    mid = pm.PrettyMIDI(str(w.file(f"{notes}.mid")))
    got, rows = imported(w.file(f"{notes}.gp5"))
    row_s = 60 / mid.get_tempo_changes()[1][0] / 4
    print(f"{notes}.gp5 read back by vulturetracker import: patterns of {', '.join(map(str, rows))} rows")
    for inst in mid.instruments:
        want = {(round(n.start / row_s), note_name(n.pitch)) for n in inst.notes}
        have = got.get(inst.name, set())
        if inst.is_drum:
            want, have = {r for r, _ in want}, {r for r, _ in have}
            print(f"{inst.name:6s}: MIDI hits on {len(want)} rows, the tab on {len(have)}; rows only in the MIDI "
                  f"{len(want - have)}, only in the tab {len(have - want)}")
        else:
            print(f"{inst.name:6s}: MIDI {len(want)} notes, tab {len(have)}; in both {len(want & have)}, only in the MIDI "
                  f"{len(want - have)}, only in the tab {len(have - want)}")


def it(w, song):
    from stems_to_song import delta
    from vulturetracker import api
    s = w.file(f"{song}.yaml")
    meta = json.loads(w.file(f"{song}.json").read_text(encoding="utf-8"))
    if not s.with_suffix(".it").is_file():
        sys.exit(f"no {song}.it: python -m vulturetracker export {s} -f it")
    with tempfile.TemporaryDirectory() as d:
        api.render(str(s.with_suffix(".it")), f"{d}/it.wav")
        got = delta(f"{d}/it.wav", str(w.file(f"{w.name}.wav")), meta["offset_ms"])
    four = lambda d: f"{d['median']} / {d['mean']} / {d['p75']} / {d['p90']}"  # noqa: E731
    print(f"DELTA (median / mean / p75 / p90), OFFSET {meta['offset_ms']}: the song {four(meta['delta_db'])}, "
          f"its .it {four(got)}")


def missing(w, notes, song, k, short):
    import guitarpro as gp
    import numpy as np
    import pretty_midi as pm
    import soundfile as sf
    import yaml
    b0 = k % 16 - (16 if k % 16 else 0)  # MIDI row r is recording row r + b0
    mid = pm.PrettyMIDI(str(w.file(f"{notes}.mid")))
    row_s = 60 / mid.get_tempo_changes()[1][0] / 4
    starts = bar_starts(10 ** 6, None if short is None else short - b0)
    tab = gp.parse(str(w.path / f"{notes}.gp5")) if (w.path / f"{notes}.gp5").is_file() else None

    def tab_rows(part):
        out = set()
        for t in tab.tracks if tab else []:
            if t.name.split()[0].lower() == part:
                for m in t.measures:
                    for v in m.voices:
                        for b in v.beats:
                            if b.notes and b.status == gp.BeatStatus.normal:
                                a = (b.start - gp.Duration.quarterTime) // 240
                                out.update(range(a, a + max(1, b.duration.time // 240)))
        return out

    for inst in (i for i in mid.instruments if not i.is_drum):
        x = sf.read(w.file(w.stems / f"{inst.name}.wav"), always_2d=True)[0].mean(1)
        lv = np.array([np.sqrt(np.mean(x[int(w.t(r) * SR):int(w.t(r + 1) * SR)] ** 2)) for r in range(int((len(x) / SR - w.g0) / w.p))])
        sounding = {int(r) - b0 for r in np.flatnonzero(lv > lv.max() * 10 ** (-30 / 20))}
        noted = {r for n in inst.notes for r in range(round(n.start / row_s), max(round(n.start / row_s) + 1, round(n.end / row_s)))}
        gaps = sounding - noted
        in_tab = tab_rows(inst.name)
        print(f"{inst.name:6s}: the stem sounds on {len(sounding)} rows; no MIDI note on {len(gaps)} ({len(gaps) / max(1, len(sounding)):.0%})"
              + (f", no tab note on {len(sounding - in_tab)} ({len(sounding - in_tab) / max(1, len(sounding)):.0%})" if in_tab else ", not in the tab"))
        worst = Counter(bisect.bisect_right(starts, r) for r in gaps).most_common(6)
        print("        bars with the most: " + ", ".join(f"{b} ({c} rows)" for b, c in worst))
    s = w.path / f"{song}.yaml"
    if s.is_file() and any(i.is_drum for i in mid.instruments):
        sg = yaml.safe_load(s.read_text(encoding="utf-8"))
        chans, hit, base = [c["name"] for c in sg["module"]["channels"]], set(), 0
        for pid in sg["orders"]:
            pat = sg["patterns"][pid]
            for line in pat["data"].splitlines():
                r, cells = line.split(":", 1)
                hit.update(base + int(r) for ch, cell in zip(chans, cells.split("|")) if ch == "drums" and cell.split()[0] not in SKIP)
            base += pat["rows"]
        midi = {round(n.start / row_s) for i in mid.instruments if i.is_drum for n in i.notes}
        print(f"drums : {song} plays a hit on {len(hit)} rows, the MIDI on {len(midi)}; {len(hit - midi)} of the song's have no MIDI hit")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    sub = ap.add_subparsers(dest="check", required=True)
    cmd = {name: sub.add_parser(name) for name in ("downbeats", "score", "gp5", "it", "missing")}
    for p in cmd.values():
        p.add_argument("work", type=Path, help="the folder transcribe_audio.py made")
    cmd["downbeats"].add_argument("--short-bar", type=int, metavar="ROW", help="also count with a 2/4 bar at this recording row")
    cmd["score"].add_argument("stems", nargs="*", help=f"stems to score (default: every one of {', '.join(PITCHED)} there is)")
    for name in ("gp5", "missing"):
        cmd[name].add_argument("--notes", help="make_notes.py's files: <notes>.mid and .gp5 (default <name>-notes)")
    for name in ("it", "missing"):
        cmd[name].add_argument("--song", help="stems_to_song.py's song: <song>.yaml (default <name>-B-sections)")
    cmd["missing"].add_argument("--downbeat-row", type=int, default=0, help="as given to make_notes.py")
    cmd["missing"].add_argument("--short-bar", type=int, metavar="ROW", help="as given to make_notes.py")
    a = ap.parse_args()
    if not a.work.is_dir():
        ap.error(f"no such folder: {a.work}")
    if getattr(a, "short_bar", None) is not None and a.short_bar < 0:
        ap.error("--short-bar is 0 or more")
    bad = set(getattr(a, "stems", [])) - set(PITCHED)
    if bad:
        ap.error(f"no stem {', '.join(sorted(bad))}: one of {', '.join(PITCHED)}")
    env = "torch" if a.check == "downbeats" else "bp"
    try:
        w = Work(a.work)
        notes, song = getattr(a, "notes", None) or f"{w.name}-notes", getattr(a, "song", None) or f"{w.name}-B-sections"
        {"downbeats": lambda: downbeats(w, a.short_bar), "score": lambda: score(w, a.stems), "gp5": lambda: gp5(w, notes),
         "it": lambda: it(w, song), "missing": lambda: missing(w, notes, song, a.downbeat_row, a.short_bar)}[a.check]()
    except ImportError as e:
        sys.exit(f"{e.name} is missing: run `{a.check}` with the {env} environment's python (tools/transcribe_audio.py --setup"
                 + ('; beat_this: uv pip install -p tools/transcribe-env/torch/Scripts/python.exe '
                    '"beat_this @ https://github.com/CPJKU/beat_this/archive/main.zip")' if e.name == "beat_this" else ")"))


if __name__ == "__main__":
    main()
