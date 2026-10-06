"""A transcription played on samples cut from the recording's own stems (the tracker way), scored against the recording.

Runs in the basic-pitch environment that tools/transcribe_audio.py --setup makes (librosa, soundfile, scikit-learn,
pretty_midi, pyyaml):

  <env>/bp/Scripts/python tools/stems_to_song.py WORK [--notes basic-pitch] [--part STEM=MODE ...] [--legato]
                                                 [--types 56] [--section-bars 4] [--row0 N] [--short-bar ROW]
                                                 [--title sampled]

WORK is a folder made by transcribe_audio.py: <name>.wav (the recording), stems/<model>/<stem>.wav, <name>-<notes>.mid
and .json (the merged notes, the BPM and the song's offset), midi/drums_adtof.mid when ADTOF ran. Each stem becomes a
part, played one of three ways (--part STEM=MODE; default drums=hits, every other stem notes):
  hits      a slice of the stem at every row where a hit starts (ADTOF's rows for the drums, and rows where the stem's
            level rises), clustered by the shape of their spectrum into --types hit types (6 for a stem other than the
            drums, fewer when IT's 99 samples run short); every hit plays its type's slice at its own level, on one channel
  notes     the stem's notes from the MIDI (back-to-back notes of a pitch joined where the stem has no onset), one sample
            per pitch cut from the stem where that pitch sounds most alone, each note at the level of its pitch's first
            three harmonics; --legato holds each note to the next one on its channel
  sections  the stem itself, a sample every --section-bars bars: exact, but a slice of the song that starts inside a
            section is silent on that channel until the next section
The recording's 16th grid is measured from the drum stem (level rises folded over a row); the recording's row 0 plays on
song row --row0 (default: the transcription's offset rounded to a row; 0 puts the song's bar lines on the recording's
when the recording starts on a downbeat, as a downbeat tracker can tell). --short-bar ROW puts a 2/4 bar (8 rows) at
the recording's row ROW, for a recording that gains half a bar there: bars start every 16 rows from song row 0 up to it
and 8 rows later after it (sections follow the bars). A tempo channel keeps the render on
it: libopenmpt counts a tick in whole samples of its mixing rate (the app renders at 2 x 44.1 kHz), so at tempo 136 a
row comes out 198 ppm short; a row one tempo slower goes in whenever the render runs 0.4 ms ahead.
Writes <name>-<title>.yaml with its samples (<name>-<title>_samples), -song.wav, .mp3 (the song, lined up with the
recording), .json (the offset and the SPECTRUM tab's DELTA: median, mean, 75th and 90th percentiles of the columns) and
prints each part's level against its stem."""
import argparse
import json
import math
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SR = 44100
PRE = 0.005  # every cut starts this long before its row
ADTOF = {35: "kick", 36: "kick", 38: "snare", 40: "snare", 42: "hat", 44: "hat", 46: "hat", 47: "tom", 49: "crash", 51: "ride",
         57: "crash"}
MODES = ("hits", "notes", "sections")


class Grid:
    """The recording's 16th grid and the song on it: recording row k sounds at g0 + k p; song row = k + r0."""

    def __init__(self, bpm, g0, r0, short=None):
        self.p, self.g0, self.r0, self.short = 60 / bpm / 4, g0, r0, short  # short: the song row of a 2/4 bar
        self.offset_ms = round((r0 * self.p - g0 + PRE) * 1000)

    def t(self, k):
        return self.g0 + k * self.p


def bar_starts(total, short=None):
    """The rows where bars start, before `total`: every 16 from row 0, with a 2/4 bar (8 rows) at row `short`."""
    out, r = [], 0
    while r < total:
        out.append(r)
        r += 8 if r == short else 16
    return out


def rises(x):
    """The level rises of `x`: (times s, rises dB) of its 32-sample frames, those more than 50 dB under the loudest at 0."""
    import numpy as np
    m = x.mean(1)
    n = len(m) // 32
    lv = 20 * np.log10(np.sqrt((m[:n * 32].reshape(n, 32) ** 2).mean(1)) + 1e-6)
    rise = np.maximum(0, np.diff(lv, prepend=lv[0]))
    rise[lv < lv.max() - 50] = 0
    return np.arange(n) * 32 / SR, rise


def fold(t, rise, p):
    """Rises at times `t` folded over a row of `p` s in 0.2 ms bins, smoothed over 1 ms."""
    import numpy as np
    bins = int(p / 0.0002)
    h = np.bincount(((t % p) / p * bins).astype(int) % bins, weights=rise, minlength=bins)
    return np.convolve(np.concatenate([h[-2:], h, h[:2]]), np.ones(5) / 5, mode="valid")


def grid_phase(x, p):
    """Where row 0 of the recording's grid falls: the strongest bin of its level rises folded over a row of `p` s."""
    import numpy as np
    h = fold(*rises(x), p)
    return float(np.argmax(h)) / len(h) * p


def cut(x, t0, t1, fade_in=0.002, fade_out=0.003):
    """x from t0 to t1 s (silence before its start), faded in and out (raised cosine)."""
    import numpy as np
    a, b = int(round(t0 * SR)), min(len(x), int(round(t1 * SR)))
    y = np.concatenate([np.zeros((max(0, -a), x.shape[1])), x[max(0, a):b]])
    n_in, n_out = min(len(y), int(fade_in * SR)), min(len(y), int(fade_out * SR))
    if n_in:
        y[:n_in] *= (0.5 - 0.5 * np.cos(np.pi * np.arange(n_in) / n_in))[:, None]
    if n_out:
        y[-n_out:] *= (0.5 + 0.5 * np.cos(np.pi * np.arange(n_out) / n_out))[:, None]
    return y


def rms(x, t0, t1):
    import numpy as np
    a, b = max(0, int(round(t0 * SR))), min(len(x), int(round(t1 * SR)))
    return float(np.sqrt(np.mean(x[a:b].mean(1) ** 2))) if b > a else 0.0


class Part:
    """A part: samples (stem scale; the loudest use at volume 64), their names and pitches (None: a hit, played at its
    recorded pitch), sustain loops, and events (song row, sample, amplitude 0-1, pitch or None, channel, end row or None)."""

    def __init__(self, name, nna=None, fadeout=None):
        self.name, self.nna, self.fadeout = name, nna, fadeout
        self.samples, self.names, self.roots, self.loops, self.events = [], [], [], [], []


def onset_rows(x, g, flux_min=5.0, labels=None, floor_db=70):
    """Recording rows where a hit starts: those in `labels`, and those where the stem's mel level rises by `flux_min`
    dB on average over the bands within `floor_db` of its loudest."""
    import librosa
    import numpy as np
    hop = 128
    L = 10 * np.log10(librosa.feature.melspectrogram(y=x.mean(1), sr=SR, n_fft=1024, hop_length=hop, n_mels=40, fmax=18000) + 1e-10)
    fr = lambda t: int(round(t * SR / hop))  # noqa: E731
    rows = []
    for k in range(int((len(x) / SR - g.g0) / g.p)):
        t = g.t(k)
        pre = L[:, max(0, fr(t - 0.025)):max(1, fr(t - 0.005))].mean(1)
        post = L[:, fr(t + 0.005):fr(t + 0.030)].max(1)
        live = post > L.max() - floor_db
        if k in (labels or {}) or (live.any() and np.maximum(0, post - pre)[live].mean() > flux_min):
            rows.append(k)
    return rows


def hits_part(name, x, g, rows, labels, types, max_rows=16):
    """A slice of `x` from each row of `rows` to the next, clustered (k-means on the log-mel shape of its first two rows)
    into `types` types; a type's sample is the slice, among its closest third, with the longest gap after it; every hit
    then takes the nearest of those slices, at its first row's level against that slice's."""
    import librosa
    import numpy as np
    from sklearn.cluster import KMeans
    m = x.mean(1)
    gaps = [min(max_rows, (rows[i + 1] - k) if i + 1 < len(rows) else max_rows) for i, k in enumerate(rows)]
    feats, lv = [], []
    for k, gap in zip(rows, gaps):
        d = []
        for r in range(2):  # a row past the next hit repeats the one before it
            a = g.t(k) + min(r, gap - 1) * g.p
            S = librosa.feature.melspectrogram(y=m[int(a * SR):int((a + g.p) * SR)], sr=SR, n_fft=2048, hop_length=512, n_mels=40, fmax=18000)
            d.append(10 * np.log10(S.mean(1) + 1e-10))
        d = np.concatenate(d)
        feats.append(d - d.max())
        lv.append(rms(x, g.t(k), g.t(k) + g.p))
    F = np.maximum(np.array(feats), -60)
    types = min(types, len(rows))
    km = KMeans(n_clusters=types, n_init=10, random_state=0).fit(F)
    reps = []
    for c in range(types):
        idx = np.where(km.labels_ == c)[0]
        pool = idx[np.argsort(np.linalg.norm(F[idx] - km.cluster_centers_[c], axis=1))][:max(3, len(idx) // 3)]
        reps.append(max(pool, key=lambda i: (gaps[i], -np.linalg.norm(F[i] - km.cluster_centers_[c]))))
    assign = np.argmin(((F[:, None, :] - F[reps][None, :, :]) ** 2).sum(-1), axis=1)
    part = Part(name)
    for c, rep in enumerate(reps):
        idx = np.where(assign == c)[0]
        ratios = np.array([lv[i] / max(lv[rep], 1e-9) for i in idx])
        top = max(1.0, float(np.percentile(ratios, 95))) if len(idx) else 1.0
        part.samples.append(cut(x, g.t(rows[rep]) - PRE, g.t(rows[rep]) + gaps[rep] * g.p - PRE) * top)
        lab = Counter("+".join(sorted((labels or {}).get(rows[i], {"hit"}))) for i in idx).most_common(1)[0][0] if len(idx) else "hit"
        part.names.append(f"{name} {c + 1:02d} {lab}"[:25])
        part.roots.append(None)
        part.loops.append(None)
        part.events += [(rows[i] + g.r0, c, min(1.0, r / top), None, name, None) for i, r in zip(idx, ratios)]
    part.events.sort()
    print(f"{name}: {len(rows)} hits in {types} types")
    return part


class Harmonics:
    """A stem's power at a pitch's first three harmonics (+-40 cents), per STFT frame."""

    def __init__(self, x, n_fft=4096, hop=512):
        import librosa
        import numpy as np
        self.S = np.abs(librosa.stft(x.mean(1), n_fft=n_fft, hop_length=hop)) ** 2
        self.f = np.fft.rfftfreq(n_fft, 1 / SR)
        self.fps = SR / hop

    def level(self, pitch, t0, t1):
        import numpy as np
        f0 = 440 * 2 ** ((pitch - 69) / 12)
        a = int(t0 * self.fps)
        b = max(a + 1, int(t1 * self.fps))
        tot = 0.0
        for h in (1, 2, 3):
            band = (self.f > h * f0 * 2 ** (-40 / 1200)) & (self.f < h * f0 * 2 ** (40 / 1200))
            if not band.any():
                band = np.abs(self.f - h * f0) == np.abs(self.f - h * f0).min()
            tot += self.S[band, a:b].max(0).mean()
        return tot


def merge_held(notes, onsets, r0):
    """Back-to-back notes of one pitch joined where the stem has no onset at the joint (basic-pitch splits a held note
    where its level moves)."""
    out, last = [], {}
    for a, b, p in sorted(notes):
        k = last.get(p)
        if k is not None and a <= out[k][1] and (a - r0) not in onsets:
            out[k] = (out[k][0], max(out[k][1], b), p)
            continue
        last[p] = len(out)
        out.append((a, b, p))
    return sorted(out)


def notes_part(name, x, g, notes, legato=False, max_release=0.15, level_rows=4):
    """`notes` (song start row, end row, pitch) on a sample per pitch cut from `x`: of that pitch's notes covered least
    by the part's others (within 0.3 of the best), the longest, from its row to its end plus its decay (up to
    `max_release` s, not past the part's next note), with a sustain loop when longer notes of the pitch (or `legato`) need
    one; each note at its pitch's harmonics in its first `level_rows` rows against the cut note's."""
    import numpy as np
    from vulturetracker.dsp import find_loop
    H = Harmonics(x)
    starts = sorted({a for a, _, _ in notes})
    span = np.zeros(max(b for _, b, _ in notes) + 2, int)
    for a, b, _ in notes:
        span[a:b] += 1
    part = Part(name, fadeout=192)
    by_pitch = {}
    for n in notes:
        by_pitch.setdefault(n[2], []).append(n)
    for j, (pitch, ns) in enumerate(sorted(by_pitch.items())):
        iso = [float(np.mean(span[a:b] == 1)) for a, b, _ in ns]
        a, b, _ = ns[max((i for i in range(len(ns)) if iso[i] >= max(iso) - 0.3), key=lambda i: (ns[i][1] - ns[i][0], iso[i]))]
        t0 = g.t(a - g.r0)
        nxt = next((s for s in starts if s >= b), None)
        release = max_release if nxt is None else min(max_release, (nxt - b) * g.p)
        y = cut(x, t0 - PRE, t0 + (b - a) * g.p + release - PRE)
        loop = None
        if legato or max(e - s for s, e, _ in ns) > b - a:
            body = y[:int(((b - a) * g.p + PRE) * SR)]
            loop = find_loop(body.T, SR, hz=440 * 2 ** ((pitch - 69) / 12), min_s=min(0.2, 0.3 * len(body) / SR))
        ref = H.level(pitch, t0, t0 + min(b - a, level_rows) * g.p)
        ratios = np.sqrt(np.array([H.level(pitch, g.t(s - g.r0), g.t(s - g.r0) + min(e - s, level_rows) * g.p)
                                   for s, e, _ in ns]) / max(ref, 1e-20))
        top = max(1.0, float(np.percentile(ratios, 95)))
        part.samples.append(y * top)
        part.names.append(f"{name} {note_name(pitch)}"[:25])
        part.roots.append(pitch)
        part.loops.append(loop)
        part.events += [[s, j, min(1.0, r / top), pitch, None, e] for (s, e, _), r in zip(ns, ratios)]
    part.events.sort(key=lambda e: (e[0], e[3]))
    ends = []
    for ev in part.events:  # channels: the first whose last note has ended
        k = next((i for i, end in enumerate(ends) if end <= ev[0]), len(ends))
        ends[k:k + 1] = [ev[5]]
        ev[4] = f"{name} {k + 1}"
    if legato:  # each note held to the next note of its channel, 32 rows past its own end at most
        by_lane = {}
        for ev in part.events:
            by_lane.setdefault(ev[4], []).append(ev)
        for evs in by_lane.values():
            for e1, e2 in zip(evs, evs[1:]):
                if e2[0] <= e1[5] + 32:
                    e1[5] = e2[0]
    part.events = [tuple(e) for e in part.events]
    print(f"{name}: {len(notes)} notes, {len(by_pitch)} pitches, {len(ends)} channels")
    return part


def sections_part(name, x, g, bars):
    """The stem itself, a sample every `bars` bars from song row 0, cross-faded over 2 PRE at the joins (NNA continue)."""
    n = int((len(x) / SR - g.g0) / g.p)
    part = Part(name, nna="continue")
    starts = bar_starts(n + g.r0, g.short)
    cuts = [a - g.r0 for a in starts[::bars]] + [n]  # recording rows
    for j, (s, e) in enumerate(zip(cuts, cuts[1:])):
        part.samples.append(cut(x, g.t(s) - PRE, g.t(e) + PRE, fade_in=2 * PRE, fade_out=2 * PRE))
        part.names.append(f"{name} bars {j * bars + 1}-{min(len(starts), (j + 1) * bars)}"[:25])
        part.roots.append(None)
        part.loops.append(None)
        part.events.append((s + g.r0, j, 1.0, None, name, None))
    print(f"{name}: {len(part.samples)} sections of {bars} bars")
    return part


def note_name(n):
    from vulturetracker.gpimport import note_name as nn
    return nn(n)


def tempo_lane(g, rows, tempo, speed=6, mix_rate=2 * SR):
    """Tempo changes that keep the render on the grid: a row at tempo t lasts speed x (mix_rate x 2.5 // t) samples of
    the mixing rate (libopenmpt's whole-sample ticks); each row takes `tempo` or its neighbour on the grid's side,
    whichever leaves the render nearer the grid, a Txx where that changes."""
    from vulturetracker.gpimport import Lane
    row = lambda t: speed * (mix_rate * 5 // (2 * t)) / mix_rate  # noqa: E731
    other = tempo - 1 if row(tempo) < g.p else tempo + 1
    ln, err, now = Lane("tempo"), 0.0, tempo
    for r in range(rows):
        t = min((tempo, other), key=lambda t: abs(err + row(t) - g.p))
        if t != now:
            ln.put(r, fx=f"T{t:02X}")
            now = t
        err += row(t) - g.p
    return ln


def write(parts, g, song_path, tempo, gains=None):
    """The parts as a song (samples in <song>_samples), each part's samples times its gain, then one gain for all so
    that none clips."""
    import numpy as np
    import soundfile as sf
    from vulturetracker.gpimport import Lane, write_song
    gains = gains or {}
    sdir = song_path.with_name(song_path.stem + "_samples")
    sdir.mkdir(parents=True, exist_ok=True)
    for f in sdir.glob("*.wav"):
        f.unlink()
    peak = max(float(np.abs(s).max()) * gains.get(p.name, 1.0) for p in parts for s in p.samples)
    samples, instruments, lanes = {}, {}, []
    for p in parts:
        ins, first, keymap = len(instruments) + 1, len(samples) + 1, []
        for j, (s, nm, root, loop) in enumerate(zip(p.samples, p.names, p.roots, p.loops)):
            f = sdir / f"{p.name}_{j + 1:02d}.wav"
            sf.write(f, s * gains.get(p.name, 1.0) * 0.98 / peak, SR, subtype="PCM_16")
            entry = {"file": f"{sdir.name}/{f.name}", "name": nm, "stereo": True}
            if loop:
                entry["sustain_loop"] = {"start": int(loop[0]), "end": int(loop[1])}
            if root is None:  # a hit or a section: a key of its own, played at its recorded pitch
                keymap.append({"notes": note_name(36 + j), "sample": first + j, "play_note": "C-5"})
            else:
                entry["base_note"] = note_name(root)
                keymap.append({"notes": note_name(root), "sample": first + j})
            samples[first + j] = entry
        instruments[ins] = {"name": p.name, "keymap": keymap, **({"fadeout": p.fadeout} if p.fadeout else {}),
                            **({"nna": p.nna} if p.nna else {})}
        by_lane, offs = {}, []
        for row, j, amp, pitch, lane, end in p.events:
            v = round(64 * amp)
            if v >= 1:
                ln = by_lane.setdefault(lane, Lane(lane))
                ln.put(row, note_name(36 + j) if pitch is None else note_name(pitch), ins, f"v{v:02d}", force=True)
                if end is not None:
                    offs.append((ln, end))
        for ln, end in offs:
            ln.off(end)
        lanes += [by_lane[k] for k in sorted(by_lane, key=lambda s: (len(s), s))]
    total = max(r for ln in lanes for r in ln.cells) + 1
    lanes.append(tempo_lane(g, total, tempo))
    if len(samples) > 99 or len(lanes) > 64:
        sys.exit(f"{len(samples)} samples and {len(lanes)} channels: IT holds 99 and 64 (lower --types, or use sections)")
    ph = type("Ph", (), {})()
    ph.samples, ph.instruments = samples, instruments
    starts = bar_starts(total, g.short)
    bars = [(f"b{i + 1}", a, min(e, total) - a) for i, (a, e) in enumerate(zip(starts, starts[1:] + [starts[-1] + 16]))]
    head = (f"# Played on samples cut from the recording's stems by tools/stems_to_song.py: "
            f"{', '.join(f'{p.name} {mode_of(p)}' for p in parts)}\n# the song starts {g.offset_ms} ms after the "
            "recording (SPECTRUM REFERENCE OFFSET); the tempo channel keeps it on the recording's grid\n")
    write_song(song_path, song_path.stem, lanes, bars, ph, 4, 6, tempo, (4, 4), [], head)
    print(f"{song_path.name}: {len(samples)} samples, {len(lanes)} channels, {len(bars)} bars")


def mode_of(p):
    return "sections" if p.nna == "continue" else "notes" if p.roots and p.roots[0] is not None else "hits"


def solo_levels(song_path, g, stems):
    """Per part, its solo render's level against its stem: the median, over 100 ms frames where both sound (within 30 dB
    of their loudest), of the difference in dB."""
    import tempfile
    import numpy as np
    import soundfile as sf
    from vulturetracker import api
    song = api.load(song_path)
    names = sorted({c["name"].split()[0] for c in song["module"]["channels"]} - {"tempo"})
    off = int(round(g.offset_ms / 1000 * SR))
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            for c in song["module"]["channels"]:
                c["muted"] = c["name"].split()[0] != name and c["name"] != "tempo"
            w = Path(tmp) / "solo.wav"
            api.render(song, str(w), base_dir=song_path.parent)
            y, x = sf.read(w)[0].mean(1), stems[name].mean(1)
            y, x = (y[off:], x) if off >= 0 else (y, x[-off:])  # a negative offset: the song starts inside the recording
            n = min(len(x), len(y)) // 4410 * 4410
            ly, lx = (10 * np.log10((v[:n].reshape(-1, 4410) ** 2).mean(1) + 1e-12) for v in (y, x))
            both = (ly > ly.max() - 30) & (lx > lx.max() - 30)
            out[name] = float(np.median(lx[both] - ly[both]))
    return out


def delta(render, rec, offset_ms):
    """The SPECTRUM tab's DELTA of the render against the recording (vulturetracker.gui.reference_compare): the median,
    mean, 75th and 90th percentiles of the columns' mean |delta| in dB."""
    import numpy as np
    from vulturetracker.gui import reference_compare
    *_, cols, _, _ = reference_compare(str(render), "r", str(rec), "x", offset_ms, 0.0)
    live = np.array(sorted(v for v in cols if v is not None))
    return {"median": float(live[len(live) // 2]), "mean": round(float(live.mean()), 1),
            "p75": round(float(np.percentile(live, 75)), 1), "p90": round(float(np.percentile(live, 90)), 1)}


def ffmpeg():
    exe = REPO / "tools" / "transcribe-env" / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if exe.is_file():
        return str(exe)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("work", type=Path, help="the folder transcribe_audio.py made")
    ap.add_argument("--notes", default="basic-pitch", help="whose notes: <name>-<notes>.mid in WORK (default basic-pitch)")
    ap.add_argument("--stems", type=Path, help="the stems folder (default: the only one in WORK/stems, else htdemucs_ft)")
    ap.add_argument("--part", action="append", default=[], metavar="STEM=MODE", help=f"how a stem plays: {', '.join(MODES)}")
    ap.add_argument("--legato", action="store_true", help="notes held to the next note on their channel")
    ap.add_argument("--types", type=int, default=56, help="hit types for the drums (fewer when the 99 samples run short)")
    ap.add_argument("--section-bars", type=int, default=4, help="bars per sample for sections")
    ap.add_argument("--row0", type=int, help="the song row the recording's row 0 plays on (default: from the offset)")
    ap.add_argument("--short-bar", type=int, metavar="ROW", help="a 2/4 bar at this recording row (where it gains half a bar)")
    ap.add_argument("--title", default="sampled", help="the song is <name>-<title>.yaml in WORK")
    args = ap.parse_args()
    work = args.work.resolve()
    mids = [m for m in work.glob(f"*-{args.notes}.mid")]
    if len(mids) != 1:
        ap.error(f"want one <name>-{args.notes}.mid in {work}, found {len(mids)}")
    name = mids[0].name[:-len(f"-{args.notes}.mid")]
    rec, side = work / f"{name}.wav", mids[0].with_suffix(".json")
    for f in (rec, side):
        if not f.is_file():
            ap.error(f"no such file: {f}")
    folders = [d for d in (work / "stems").glob("*") if d.is_dir() and any(d.glob("*.wav"))] if (work / "stems").is_dir() else []
    sdir = args.stems or (folders[0] if len(folders) == 1 else work / "stems" / "htdemucs_ft")
    if not sdir.is_dir():
        ap.error(f"no stems folder: {sdir} (name one with --stems)")
    modes = {}
    for spec in args.part:
        stem, _, mode = spec.partition("=")
        if mode not in MODES:
            ap.error(f"--part {spec}: the mode is one of {', '.join(MODES)}")
        modes[stem] = mode
    if args.types < 1 or args.section_bars < 1:
        ap.error("--types and --section-bars are 1 or more")
    if args.row0 is not None and args.row0 < 0:
        ap.error("--row0 is 0 or more")
    try:
        import librosa  # noqa: F401
        import pretty_midi  # noqa: F401
        import sklearn  # noqa: F401
        import soundfile as sf
        import yaml  # noqa: F401
    except ImportError as e:
        sys.exit(f"{e.name} is missing: run this with the basic-pitch environment's python (tools/transcribe_audio.py --setup)")
    import pretty_midi as pm
    sys.path.insert(0, str(REPO))
    from vulturetracker import api

    stems = {f.stem: sf.read(f, always_2d=True)[0] for f in sorted(sdir.glob("*.wav"))}
    meta = json.loads(side.read_text(encoding="utf-8"))
    bpm = meta["bpm"]
    g0 = grid_phase(stems.get("drums", next(iter(stems.values()))), 60 / bpm / 4)
    r0 = round((meta["offset_ms"] / 1000 + g0) / (60 / bpm / 4)) if args.row0 is None else args.row0
    g = Grid(bpm, g0, r0, None if args.short_bar is None else args.short_bar + r0)
    if g.short is not None and (g.short < 0 or g.short % 16):
        ap.error(f"--short-bar {args.short_bar} plays on song row {g.short}, which does not start a bar (every 16 rows from 0)")
    print(f"grid: row 0 of the recording at {g0 * 1000:.1f} ms, song row {g.r0}; offset {g.offset_ms} ms"
          + (f"; a 2/4 bar at song row {g.short} (bar {g.short // 16 + 1})" if g.short is not None else ""))
    mid = pm.PrettyMIDI(str(mids[0]))
    row = 60 / float(mid.get_tempo_changes()[1][0]) / 4
    notes = {i.name: sorted((round(n.start / row), max(round(n.end / row), round(n.start / row) + 1), n.pitch) for n in i.notes)
             for i in mid.instruments if not i.is_drum}
    labels = {}
    if (work / "midi" / "drums_adtof.mid").is_file():
        for i in pm.PrettyMIDI(str(work / "midi" / "drums_adtof.mid")).instruments:
            for n in i.notes:
                labels.setdefault(int(round((n.start - g.g0) / g.p)), set()).add(ADTOF.get(n.pitch, "hit"))
    known = ("drums", "bass", "other", "guitar", "piano", "vocals")
    unknown = set(modes) - set(stems)
    if unknown:
        sys.exit(f"--part: no stem {', '.join(sorted(unknown))} in {sdir}")
    order = [s for s in known if s in stems] + sorted(set(stems) - set(known))
    plan = {s: modes.get(s, "hits" if s == "drums" else "notes") for s in order}
    for s, mode in list(plan.items()):
        if mode == "notes" and not notes.get(s):
            print(f"{s}: no notes in {mids[0].name}, left out")
            del plan[s]
    rows_total = int((len(next(iter(stems.values()))) / SR - g.g0) / g.p) + g.r0
    need = sum(-(-len(bar_starts(rows_total, g.short)) // args.section_bars) if m == "sections" else len({n[2] for n in notes[s]}) if m == "notes" else 6
               for s, m in plan.items() if not (m == "hits" and s == "drums"))
    parts = []
    for s, mode in plan.items():
        x = stems[s]
        if mode == "hits":
            types = max(1, 99 - need) if s == "drums" else 6
            if s == "drums" and types < args.types:
                print(f"drums: {types} hit types, the rest of IT's 99 samples go to the other parts")
            lab = labels if s == "drums" else None
            parts.append(hits_part(s, x, g, onset_rows(x, g, labels=lab) if s == "drums" else onset_rows(x, g, 8.0, floor_db=40),
                                   lab, min(types, args.types) if s == "drums" else types))
        elif mode == "notes":
            parts.append(notes_part(s, x, g, merge_held(notes[s], set(onset_rows(x, g, 3.0)), g.r0), args.legato))
        else:
            parts.append(sections_part(s, x, g, args.section_bars))
    song = work / f"{name}-{args.title}.yaml"
    tempo = round(meta["bpm"])
    write(parts, g, song, tempo)
    ref = "drums" if "drums" in plan else next(iter(plan))
    diff = solo_levels(song, g, stems)
    gains = {s: 10 ** ((d - diff[ref]) / 20) for s, d in diff.items()}
    print("levels against the stems (dB, " + ref + " = 0): " + ", ".join(f"{s} {d - diff[ref]:+.1f}" for s, d in diff.items()))
    write(parts, g, song, tempo, {s: v for s, v in gains.items() if plan[s] != "sections"})
    wav = song.with_name(song.stem + "-song.wav")
    api.render(str(song), str(wav))
    d = delta(wav, rec, g.offset_ms)
    o = g.offset_ms  # the MP3 starts where the recording does, so the two line up
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(wav), "-af",
                    f"atrim=start={o / 1000},asetpts=PTS-STARTPTS" if o >= 0 else f"adelay={-o}|{-o}", "-b:a", "320k",
                    str(song.with_suffix(".mp3"))], check=True)
    song.with_suffix(".json").write_text(json.dumps({"bpm": bpm, "offset_ms": g.offset_ms, "delta_db": d,
                                                     "parts": {p.name: mode_of(p) for p in parts}}), encoding="utf-8")
    print(f"\nsong:   {song}\nlisten: {song.with_suffix('.mp3')} (lined up with the recording)\n"
          f"DELTA:  median {d['median']} dB, mean {d['mean']}, p75 {d['p75']}, p90 {d['p90']} (SPECTRUM: REFERENCE "
          f"{rec.name}, OFFSET {g.offset_ms})")


if __name__ == "__main__":
    main()
