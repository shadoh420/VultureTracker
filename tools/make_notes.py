"""A transcription's notes as a MIDI file and a Guitar Pro 5 tab, on the recording's own 16th grid with the bar lines on
its downbeats.

Runs in the basic-pitch environment that tools/transcribe_audio.py --setup makes (pretty_midi, soundfile, PyGuitarPro):

  <env>/bp/Scripts/python tools/make_notes.py WORK [--notes basic-pitch] [--part STEM=FILE ...] [--keep-quiet STEM ...]
                                               [--downbeat-row 0] [--tempo BPM] [--out NAME]

WORK is a folder made by transcribe_audio.py: stems/<model>/<stem>.wav, midi/<stem>_<notes>.mid (each pitched stem's
notes), midi/drums_adtof.mid when ADTOF ran, and <name>-<notes>.json (the BPM). The grid is stems_to_song.py's: that BPM,
row 0 where the drum stem's level rises fold. --downbeat-row is a recording row where a bar starts (0 when the recording
starts on a downbeat; a downbeat tracker such as beat_this tells), and the MIDI begins at the bar line at or before the
recording. Each pitched stem louder than -50 dBFS plays its notes (--part STEM=FILE takes them from another MIDI, such as
basic-pitch run again with --minimum-note-length 58: its default, about 128 ms, is longer than a 16th above 117 BPM);
basic-pitch's quiet notes (velocity under 45, under 40 for "other") are dropped as stems_to_midi.py drops them, except for
the stems named with --keep-quiet. Drums: ADTOF's hits in General MIDI keys.

The tab holds the guitar and bass stems and the drums (the other stems are in the MIDI only): each on the standard-family
tuning whose lowest string takes its lowest note that occurs three times or more, frets by a Viterbi path (a chord on
distinct strings, a higher note on a higher string, within 4 frets or else 5, the hand moving least); notes no fingering
fits are dropped and counted. In the tab a note lasts to the next onset at most (the MIDI keeps the lengths). The tab is
read back once written. Writes WORK/<out>.mid and .gp5 (default <name>-notes) and prints where bar 1 falls in the
recording."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stems_to_midi import GM_KIT  # noqa: E402
from stems_to_song import grid_phase  # noqa: E402

PITCHED = ("guitar", "bass", "other", "piano", "vocals")
PROGRAM = {"guitar": 30, "bass": 33, "other": 89, "piano": 0, "vocals": 52}  # General MIDI, as stems_to_midi.py's placeholders
GUITAR = [("E standard", [64, 59, 55, 50, 45, 40]), ("Eb standard", [63, 58, 54, 49, 44, 39]),
          ("D standard", [62, 57, 53, 48, 43, 38]), ("C# standard", [61, 56, 52, 47, 42, 37]),
          ("C standard", [60, 55, 51, 46, 41, 36]), ("B standard", [59, 54, 50, 45, 40, 35])]
BASS = [("E standard", [43, 38, 33, 28]), ("Eb standard", [42, 37, 32, 27]), ("D standard", [41, 36, 31, 26]),
        ("C# standard", [40, 35, 30, 25]), ("C standard", [39, 34, 29, 24]), ("5-string B standard", [43, 38, 33, 28, 23])]
FRETS = 24
LENGTHS = (16, 12, 8, 6, 4, 3, 2, 1)  # rows a Guitar Pro duration can take in 4/4
ALIGN = {16: 16, 12: 4, 8: 8, 6: 2, 4: 4, 3: 1, 2: 2, 1: 1}  # rows of the bar each may start on
DUR = {16: (1, False), 12: (2, True), 8: (2, False), 6: (4, True), 4: (4, False), 3: (8, True), 2: (8, False), 1: (16, False)}


def quantize(raw):
    """(start row, end row, pitch, velocity): one note per pitch per row (the loudest, the longest end), each cut where
    the next note of its pitch starts."""
    best = {}
    for a, b, k, v in raw:
        o = best.get((a, k))
        best[(a, k)] = (a, max(b, o[1]), k, max(v, o[3])) if o else (a, b, k, v)
    out = sorted(best.values(), key=lambda n: (n[2], n[0]))
    for i in range(len(out) - 1):
        if out[i][2] == out[i + 1][2] and out[i][1] > out[i + 1][0]:
            out[i] = (out[i][0], out[i + 1][0], out[i][2], out[i][3])
    return sorted(out)


def fingerings(pitches, tuning, span):
    """Every way to put `pitches` (ascending) on distinct strings (1 = highest), a higher pitch on a higher string,
    fretted notes within `span` frets: tuples of (string, fret)."""
    out = []

    def rec(i, below, chosen):
        if i == len(pitches):
            fr = [f for _, f in chosen if f]
            if not fr or max(fr) - min(fr) <= span:
                out.append(tuple(chosen))
            return
        for s in range(below - 1, 0, -1):
            f = pitches[i] - tuning[s - 1]
            if 0 <= f <= FRETS:
                rec(i + 1, s, chosen + [(s, f)])
    rec(0, len(tuning) + 1, [])
    return out


def playable(pitches, tuning):
    """The chord's notes that fit (out-of-range notes dropped, then its highest until a fingering exists) and their
    fingerings: (pitches, fingerings, dropped)."""
    ps = [k for k in sorted(set(pitches)) if tuning[-1] <= k <= tuning[0] + FRETS]
    dropped = len(set(pitches)) - len(ps)
    while ps:
        for span in (4, 5):
            fs = fingerings(ps, tuning, span)
            if fs:
                return ps, fs, dropped
        ps, dropped = ps[:-1], dropped + 1
    return [], [], dropped


def hand(f):
    """Where the hand sits for fingering `f`: its fretted notes' mean fret (None: open strings only)."""
    fr = [x for _, x in f if x]
    return sum(fr) / len(fr) if fr else None


def viterbi(groups):
    """A fingering per group (lists of candidates) minimising span + 0.05 x position + the hand's moves."""
    def static(f):
        fr = [x for _, x in f if x]
        return (max(fr) - min(fr) if fr else 0) + 0.05 * (hand(f) or 0)

    def move(f, g):
        a, b = hand(f), hand(g)
        return abs(a - b) if a is not None and b is not None else 0.0
    cost, back = [static(f) for f in groups[0]], []
    for prev, cur in zip(groups, groups[1:]):
        new, bk = [], []
        for f in cur:
            j = min(range(len(prev)), key=lambda j: cost[j] + move(prev[j], f))
            new.append(cost[j] + move(prev[j], f) + static(f))
            bk.append(j)
        cost, back = new, back + [bk]
    k = min(range(len(cost)), key=cost.__getitem__)
    path = [k]
    for bk in reversed(back):
        k = bk[k]
        path.append(k)
    return [g[i] for g, i in zip(groups, reversed(path))]


def split(a, b):
    """Rows a..b of one bar as Guitar Pro durations: (start, length) pieces."""
    out = []
    while a < b:
        L = next(L for L in LENGTHS if L <= b - a and a % ALIGN[L] == 0)
        out.append((a, L))
        a += L
    return out


def tab_track(song, number, name, tuning, notes, channel, program, total, drums=False):
    """A track of `song` (its measure headers made) holding `notes` (start row, end row, pitch, velocity) over `total`
    rows; returns (notes written, notes dropped)."""
    import guitarpro as gp
    track = gp.Track(song, number=number, name=name, strings=[gp.GuitarString(i + 1, v) for i, v in enumerate(tuning)],
                     channel=gp.MidiChannel(channel=channel, effectChannel=channel if drums else channel + 1, instrument=program),
                     isPercussionTrack=drums, fretCount=FRETS)
    by_row = {}
    for a, b, k, v in notes:
        by_row.setdefault(a, []).append((b, k, v))
    rows, groups, cands, dropped = [], [], [], 0
    for a in sorted(by_row):
        g = by_row[a]
        if drums:
            keys = sorted({k for _, k, _ in g})[:len(tuning)]
            dropped += len({k for _, k, _ in g}) - len(keys)
            ps, fs = keys, [tuple((i + 1, k) for i, k in enumerate(keys))]
        else:
            ps, fs, d = playable([k for _, k, _ in g], tuning)
            dropped += d
        if ps:
            rows.append(a)
            groups.append([(b, k, v) for b, k, v in g if k in ps])
            cands.append(fs)
    segs, t = [], 0
    for i, (a, g, f) in enumerate(zip(rows, groups, viterbi(cands) if cands else [])):
        nxt = rows[i + 1] if i + 1 < len(rows) else total
        if a > t:
            segs.append((t, a, None))
        end = min(nxt, max(b for b, _, _ in g))
        vel = {k: v for _, k, v in g}
        segs.append((a, end, [(s, fr, vel[k]) for (s, fr), k in zip(f, sorted(vel))]))
        if end < nxt:
            segs.append((end, nxt, None))
        t = nxt
    if t < total:
        segs.append((t, total, None))
    written = 0
    for a, b, ns in segs:
        first = True
        while a < b:
            bar = a // 16
            e = min(b, (bar + 1) * 16)
            for _, L in split(a - bar * 16, e - bar * 16):
                voice = track.measures[bar].voices[0]
                beat = gp.Beat(voice, status=gp.BeatStatus.normal if ns else gp.BeatStatus.rest, duration=gp.Duration(*DUR[L]))
                for string, fret, v in ns or []:
                    beat.notes.append(gp.Note(beat, value=fret, velocity=int(v), string=string,
                                              type=gp.NoteType.normal if first else gp.NoteType.tie))
                written += len(ns or []) if first else 0
                voice.beats.append(beat)
                first = False
            a = e
    for m in track.measures:  # the second voice: one empty beat, as Guitar Pro writes an unused voice
        m.voices[1].beats.append(gp.Beat(m.voices[1], status=gp.BeatStatus.empty, duration=gp.Duration(1)))
    song.tracks.append(track)
    return written, dropped


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("work", type=Path, help="the folder transcribe_audio.py made")
    ap.add_argument("--notes", default="basic-pitch", choices=["basic-pitch", "yourmt3"], help="whose notes (midi/<stem>_<notes>.mid)")
    ap.add_argument("--stems", type=Path, help="the stems folder (default: the only one in WORK/stems, else htdemucs_ft)")
    ap.add_argument("--part", action="append", default=[], metavar="STEM=FILE", help="a stem's notes from another MIDI file")
    ap.add_argument("--keep-quiet", action="append", default=[], metavar="STEM", help="keep this stem's quiet notes")
    ap.add_argument("--downbeat-row", type=int, default=0, help="a recording row (16ths from the grid's row 0) where a bar starts")
    ap.add_argument("--tempo", type=int, help="the tempo written (default: the measured BPM rounded)")
    ap.add_argument("--out", help="the files are WORK/<out>.mid and .gp5 (default <name>-notes)")
    args = ap.parse_args()
    work = args.work.resolve()
    sides = [f for f in work.glob(f"*-{args.notes}.json")]
    if len(sides) != 1:
        ap.error(f"want one <name>-{args.notes}.json in {work} (made by transcribe_audio.py), found {len(sides)}")
    name = sides[0].name[:-len(f"-{args.notes}.json")]
    folders = [d for d in (work / "stems").glob("*") if d.is_dir() and any(d.glob("*.wav"))] if (work / "stems").is_dir() else []
    sdir = args.stems or (folders[0] if len(folders) == 1 else work / "stems" / "htdemucs_ft")
    if not sdir.is_dir():
        ap.error(f"no stems folder: {sdir} (name one with --stems)")
    parts = {}
    for spec in args.part:
        stem, _, f = spec.partition("=")
        if stem not in PITCHED or not f:
            ap.error(f"--part {spec}: STEM=FILE with STEM one of {', '.join(PITCHED)}")
        if not Path(f).is_file():
            ap.error(f"--part {spec}: no such file")
        parts[stem] = Path(f)
    for stem in args.keep_quiet:
        if stem not in PITCHED:
            ap.error(f"--keep-quiet {stem}: one of {', '.join(PITCHED)}")
    if args.tempo is not None and not 20 <= args.tempo <= 400:
        ap.error("--tempo must be between 20 and 400")
    try:
        import guitarpro as gp
        import numpy as np
        import pretty_midi as pm
        import soundfile as sf
    except ImportError as e:
        sys.exit(f"{e.name} is missing: run this with the basic-pitch environment's python (tools/transcribe_audio.py --setup)")

    bpm = json.loads(sides[0].read_text(encoding="utf-8"))["bpm"]
    p = 60 / bpm / 4
    beat_src = sdir / "drums.wav" if (sdir / "drums.wav").is_file() else next(iter(sorted(sdir.glob("*.wav"))))
    g0 = grid_phase(sf.read(beat_src, always_2d=True)[0], p)
    b0 = args.downbeat_row % 16 - (16 if args.downbeat_row % 16 else 0)  # the bar line at or before the recording's row 0
    row = lambda t: max(0, round((t - g0) / p) - b0)  # noqa: E731
    tempo = args.tempo or round(bpm)
    print(f"grid: {bpm} BPM, row 0 at {g0 * 1000:.1f} ms; bar 1 starts at {(g0 + b0 * p) * 1000:.0f} ms of the recording; "
          f"written at tempo {tempo}")

    notes = {}
    for stem in PITCHED:
        src = parts.get(stem, work / "midi" / f"{stem}_{args.notes.replace('-', '_')}.mid")
        wav = sdir / f"{stem}.wav"
        if not src.is_file() or not wav.is_file():
            continue
        if np.sqrt(np.mean(sf.read(wav)[0] ** 2)) < 10 ** (-50 / 20):
            print(f"{stem}: left out, the stem is under -50 dBFS")
            continue
        quiet = 0 if stem in args.keep_quiet else 40 if stem == "other" else 45
        notes[stem] = quantize([(row(n.start), max(row(n.start) + 1, row(n.end)), n.pitch, n.velocity)
                                for i in pm.PrettyMIDI(str(src)).instruments if not i.is_drum for n in i.notes
                                if n.velocity >= quiet and n.end - n.start >= 0.05])
    adtof = work / "midi" / "drums_adtof.mid"
    if adtof.is_file():
        notes["drums"] = quantize([(row(n.start), row(n.start) + 1, GM_KIT[n.pitch], n.velocity)
                                   for i in pm.PrettyMIDI(str(adtof)).instruments for n in i.notes if n.pitch in GM_KIT])
    notes = {k: v for k, v in notes.items() if v}
    if not notes:
        sys.exit("no notes to write")
    total = (max(b for ns in notes.values() for _, b, _, _ in ns) + 15) // 16 * 16
    out = work / (args.out or f"{name}-notes")

    mid = pm.PrettyMIDI(initial_tempo=tempo)
    mid.time_signature_changes.append(pm.TimeSignature(4, 4, 0))
    sec = 60 / tempo / 4
    for stem, ns in notes.items():
        inst = pm.Instrument(0 if stem == "drums" else PROGRAM[stem], is_drum=stem == "drums", name=stem)
        inst.notes = [pm.Note(int(v), int(k), a * sec, b * sec) for a, b, k, v in ns]
        mid.instruments.append(inst)
    mid.write(str(out.with_suffix(".mid")))
    print(f"{out.name}.mid: {total // 16} bars; " + ", ".join(f"{s} {len(ns)} notes" for s, ns in notes.items()))

    song = gp.Song(title=name, tempo=tempo)
    song.measureHeaders, song.tracks = [], []
    for i in range(total // 16):
        song.addMeasureHeader(gp.MeasureHeader(number=i + 1, start=gp.Duration.quarterTime * (1 + 4 * i)))
    plan = []
    for stem, family, ch, label in (("guitar", GUITAR, 0, "Guitar"), ("bass", BASS, 2, "Bass")):
        if stem in notes:
            counts = Counter(k for _, _, k, _ in notes[stem])
            low = min([k for k, c in counts.items() if c >= 3] or counts)
            tname, tuning = next((t for t in family if t[1][-1] <= low), family[-1])
            plan.append((f"{label} ({tname})", tuning, notes[stem], ch, PROGRAM[stem], False))
    if "drums" in notes:
        plan.append(("Drums", [0] * 6, notes["drums"], 9, 0, True))
    if not plan:
        sys.exit(f"{out.name}.mid written; no guitar, bass or drums for a tab")
    for number, (tname, tuning, ns, ch, prog, drums) in enumerate(plan, 1):
        written, dropped = tab_track(song, number, tname, tuning, ns, ch, prog, total, drums)
        print(f"  {tname}: {written} notes in the tab, {dropped} dropped (no fingering, or out of range)")
    gp.write(song, str(out.with_suffix(".gp5")))
    back = gp.parse(str(out.with_suffix(".gp5")))
    counts = [sum(1 for m in t.measures for v in m.voices for b in v.beats for n in b.notes if n.type == gp.NoteType.normal)
              for t in back.tracks]
    print(f"{out.name}.gp5 read back: {len(back.measureHeaders)} bars, " + ", ".join(f"{t.name} {c} notes" for t, c in zip(back.tracks, counts)))


if __name__ == "__main__":
    main()
