"""Timbre-free symbolic transcription diff & benchmark tool.

Renders a symbolic reference (either a VultureTracker `.yaml` ground-truth song, a
reference `.mid`, or signal-derived acoustic CQT ridges + multi-band drum onsets from a
`.wav`) alongside one or more candidate `.mid` transcriptions onto a shared 16th-note
musical bar/row grid in three sound-independent, directly diffable text formats:

  1. Canonical Tracker Patterns (`.pat.txt`), side-by-side table (`side-by-side.pat.txt`),
     and standard `diff -u` unified diffs (`.pat.diff`).
  2. Bar-aligned ASCII Tablature (`.tab.txt`: 4-str Bass, 6-str Mid/Lead via Viterbi
     fretboard fingering, 5-line Drums) + unified diffs (`.tab.diff`).
  3. Standard ABC Music Notation (`.abc`: multi-voice High/Mid/Bass, 16th-note bars).

Also computes zero-timbre symbolic MIR metrics (`symbolic-metrics.json`): Note
Onset+Pitch F1, Note Onset+Chroma F1, 20 ms Piano-Roll Frame F1 (overall, chroma, and
Bass/Mid/High registers), Drum Onset F1 (overall, Kick, Snare, Hats/Cymbals), and
tracker-pattern row-match statistics.

Examples:
  # Compare MIDI candidates against exact VultureTracker YAML ground truth:
  python tools/symbolic_diff.py --yaml demo2/iron_relay.yaml --bpm 140.083 ^
      --start-s 10.28 --duration-s 13.706 --bar-offset 7 ^
      --skip-channels "arp,arp echo,stab,fx" ^
      --midi enhanced=scratch/enhanced.mid --midi independent=scratch/independent.mid ^
      --out-dir scratch/sym-iron-relay

  # Compare MIDI candidates against audio acoustic CQT ridges (no SoundFont render):
  python tools/symbolic_diff.py --audio scratch/song.wav --bpm 130.0 ^
      --start-s 192.0338 --duration-s 18.4615 --bar-offset 104 ^
      --midi enhanced=scratch/enh.mid --midi independent=scratch/ind.mid ^
      --out-dir scratch/sym-passage
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

NOTE_NAMES = ("C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "B-")
ABC_NAMES = ("C", "^C", "D", "^D", "E", "F", "^F", "G", "^G", "A", "^A", "B")


def midi_to_pat(p: int) -> str:
    """Scientific pitch in 3-char tracker notation: C-4 = MIDI 60, C#4 = MIDI 61, A-1 = MIDI 33."""
    return f"{NOTE_NAMES[p % 12]}{p // 12 - 1}"


def midi_to_abc(p: int) -> str:
    """MIDI pitch to standard ABC pitch token (C4=60 -> C, C5=72 -> c, C3=48 -> C,)."""
    octv = p // 12 - 1
    name = ABC_NAMES[p % 12]
    if octv >= 5:
        return name.lower() + ("'" * (octv - 5))
    return name + ("," * (4 - octv))


def drum_class(pitch: int) -> str | None:
    if pitch in (35, 36):
        return "K"
    if pitch in (37, 38, 39, 40):
        return "S"
    if pitch in (42, 44):
        return "H"
    if pitch in (46, 51, 53, 59):
        return "O"
    if pitch in (49, 52, 55, 57):
        return "C"
    if pitch in (41, 43, 45, 47, 48, 50):
        return "T"
    return None


def load_midi_events(path: Path, t0: float = 0.0, t1: float | None = None):
    """Return (pitched: [(on, off, pitch, vel)], drums: [(on, cls, pitch, vel)])."""
    import pretty_midi as pm

    mid = pm.PrettyMIDI(str(path))
    pitched, drums = [], []
    for ins in mid.instruments:
        for nt in ins.notes:
            if t1 is not None and nt.start >= t1:
                continue
            if nt.end <= t0:
                continue
            a = max(0.0, nt.start - t0)
            b = (min(t1, nt.end) - t0) if t1 is not None else (nt.end - t0)
            if ins.is_drum:
                if nt.start < t0:
                    continue
                cls = drum_class(nt.pitch)
                if cls:
                    drums.append((a, cls, int(nt.pitch), int(nt.velocity)))
            else:
                if b - a >= 0.015:
                    pitched.append((a, b, int(nt.pitch), int(nt.velocity)))
    pitched.sort(key=lambda x: (x[0], x[2]))
    drums.sort(key=lambda x: (x[0], x[2]))
    return pitched, drums


def load_yaml_ground_truth(yaml_path: Path, t0: float = 0.0, t1: float | None = None,
                           skip_channels: set[str] | None = None,
                           octave_shift: dict[str, int] | None = None):
    """Extract exact symbolic pitched & drum events from a VultureTracker YAML song."""
    from vulturetracker import model, song

    m, _ = song.load_song(str(yaml_path))
    tick_s = int(44100 * 2.5 / m.tempo) / 44100.0
    row_s = m.speed * tick_s
    skip_set = {s.strip().lower() for s in (skip_channels or set()) if s.strip()}
    shift_map = {k.strip().lower(): int(v) for k, v in (octave_shift or {}).items()}

    def classify_yaml_drum(ch_name: str, note: int) -> tuple[str, int] | None:
        cl = ch_name.lower()
        if "kick" in cl:
            return ("K", 36)
        if "snare" in cl:
            return ("S", 38)
        if "hat" in cl:
            return ("O", 46) if note == 70 else ("H", 42)
        if "cymbal" in cl:
            return ("C", 49)
        if "tom" in cl:
            return ("T", 45)
        if "perc" in cl:
            return ("H", 42)
        return None

    timeline = []
    t = 0.0
    for oi in m.orders:
        if oi >= len(m.patterns):
            continue
        for row in m.patterns[oi].rows:
            timeline.append((t, row))
            t += row_s
    song_end = t

    pitched, drums = [], []
    for ci, ch in enumerate(m.channels):
        cl = ch.name.lower()
        if cl in skip_set:
            continue
        is_drum_ch = any(k in cl for k in ("kick", "snare", "hat", "cymbal", "tom", "perc"))
        if "echo" in cl or "break" in cl or "fx" in cl or "sweep" in cl:
            continue

        active_note = None
        for rt, row in timeline:
            cell = row[ci]
            vol = 100
            if cell.volcmd is not None and 0 <= cell.volcmd <= 64:
                vol = max(1, min(127, int(round(cell.volcmd * 127 / 64))))
            if cell.note in (model.NOTE_OFF, model.NOTE_CUT, model.NOTE_FADE):
                if active_note is not None:
                    a, mp, mv = active_note
                    if rt > a + 0.01:
                        pitched.append((a, rt, mp, mv))
                    active_note = None
                continue
            if cell.note is not None and 0 <= cell.note < 120:
                if is_drum_ch:
                    dc = classify_yaml_drum(ch.name, cell.note)
                    if dc:
                        drums.append((rt, dc[0], dc[1], vol))
                else:
                    if active_note is not None:
                        a, mp, mv = active_note
                        if rt > a + 0.01:
                            pitched.append((a, rt, mp, mv))
                    midi_p = int(cell.note) + shift_map.get(cl, 0)
                    active_note = (rt, midi_p, vol)
        if active_note is not None:
            a, mp, mv = active_note
            if song_end > a + 0.01:
                pitched.append((a, song_end, mp, mv))

    p_out, d_out = [], []
    for a, b, mp, mv in pitched:
        if t1 is not None and a >= t1:
            continue
        if b <= t0:
            continue
        ca = max(0.0, a - t0)
        cb = (min(t1, b) - t0) if t1 is not None else (b - t0)
        if cb - ca >= 0.015:
            p_out.append((ca, cb, mp, mv))
    for a, cls, mp, mv in drums:
        if a < t0 or (t1 is not None and a >= t1):
            continue
        d_out.append((a - t0, cls, mp, mv))
    p_out.sort(key=lambda x: (x[0], x[2]))
    d_out.sort(key=lambda x: (x[0], x[2]))
    return p_out, d_out, song_end


def extract_acoustic_ridge_reference(wav_path: Path, t0: float, dur: float | None):
    """Signal-derived symbolic reference (CQT harmonic ridges + 3-band percussive onsets)
    without any SoundFont audio rendering."""
    import librosa
    import numpy as np
    from scipy import signal
    import soundfile as sf

    x, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    full_s = len(x) / sr
    if dur is None:
        dur = max(0.5, full_s - t0)
    i0 = int(round(t0 * sr))
    i1 = min(len(x), int(round((t0 + dur) * sr)))
    mono = x[i0:i1].mean(axis=1)
    sr22 = 22050
    y = librosa.resample(mono, orig_sr=sr, target_sr=sr22)
    hop = 512
    lo, nb = 24, 66
    C = np.abs(librosa.cqt(y, sr=sr22, hop_length=hop, fmin=librosa.midi_to_hz(lo), n_bins=nb))
    Cdb = librosa.amplitude_to_db(C, ref=np.max)
    freqs = librosa.cqt_frequencies(nb, fmin=librosa.midi_to_hz(lo))
    Cdba = Cdb + librosa.A_weighting(freqs)[:, None]
    fps = sr22 / hop

    pitched = []
    for k in range(1, nb - 1):
        midi_p = lo + k
        mat = Cdb if midi_p <= 44 else Cdba
        fmax = mat.max(axis=0)
        thr = fmax - (12.0 if midi_p <= 44 else 11.0)
        is_pk = (mat[k] >= mat[k - 1]) & (mat[k] >= mat[k + 1]) & (mat[k] >= thr) & (Cdb[k] > -40.0)
        idx, nf = 0, len(is_pk)
        while idx < nf:
            if not is_pk[idx]:
                idx += 1
                continue
            a = idx
            while idx < nf and is_pk[idx]:
                idx += 1
            if idx - a >= 3:
                pitched.append((a / fps, idx / fps, midi_p, 100))

    def band_ts(lo_hz, hi_hz):
        sos = signal.butter(4, [lo_hz / (0.5 * sr22), min(hi_hz, 0.48 * sr22) / (0.5 * sr22)], btype="band", output="sos")
        yb = signal.sosfiltfilt(sos, y)
        env = librosa.onset.onset_strength(y=yb.astype(np.float32), sr=sr22, hop_length=256)
        return librosa.onset.onset_detect(onset_envelope=env, sr=sr22, hop_length=256, units="time")

    drums = []
    for ts in band_ts(30, 145):
        drums.append((float(ts), "K", 36, 100))
    for ts in band_ts(200, 1800):
        drums.append((float(ts), "S", 38, 100))
    for ts in band_ts(4000, 10500):
        drums.append((float(ts), "H", 42, 100))
    pitched.sort(key=lambda z: (z[0], z[2]))
    drums.sort(key=lambda z: (z[0], z[2]))
    return pitched, drums, len(mono) / sr


def quantize_to_grid(pitched, drums, bpm: float, row0_s: float, dur_s: float,
                     split_bm: int = 42, split_mh: int = 60):
    step_s = 15.0 / bpm
    n_rows = max(16, int(math.ceil((dur_s - row0_s) / step_s)))
    n_bars = max(1, (n_rows + 15) // 16)
    total_rows = n_bars * 16

    def t_to_row(t: float) -> int:
        return max(0, min(total_rows - 1, int(round((t - row0_s) / step_s))))

    role_on = [defaultdict(set) for _ in range(3)]
    role_hold = [defaultdict(set) for _ in range(3)]
    drum_row = defaultdict(set)

    for a, b, p, _ in pitched:
        role = 0 if p <= split_bm else (1 if p < split_mh else 2)
        ra = t_to_row(a)
        rb = max(ra + 1, min(total_rows, int(round((b - row0_s) / step_s))))
        role_on[role][ra].add(p)
        for r in range(ra + 1, rb):
            role_hold[role][r].add(p)

    for a, cls, _, _ in drums:
        drum_row[t_to_row(a)].add(cls)

    return total_rows, n_bars, role_on, role_hold, drum_row


def format_pat_cell(on_set: set[int], hold_set: set[int], max_n: int = 3) -> str:
    if on_set:
        ps = sorted(on_set)[:max_n]
        tok = " ".join(midi_to_pat(p) for p in ps)
        if len(on_set) > max_n:
            tok += "+"
        return tok
    if hold_set:
        return " | "
    return "..."


def format_drum_cell(dset: set[str]) -> str:
    return " ".join(c if c in dset else "." for c in ("K", "S", "H", "O", "C"))


def render_tracker_pattern(title: str, bpm: float, bar_offset: int,
                           total_rows: int, role_on, role_hold, drum_row) -> str:
    lines = [
        f"; Canonical 16th-Note Tracker Pattern — {title}",
        f"; Grid: {bpm:.3f} BPM, 4/4, 16 rows/bar (scientific pitch: C-4 = MIDI 60)",
        "; Bar:Row | Bass (<=F#2)     | Mid / Chords (G2..B3)   | High / Lead (>=C4)      | Drums (K S H O C)",
    ]
    for r in range(total_rows):
        bar = bar_offset + r // 16
        sub = r % 16
        if sub == 0:
            lines.append(f"; --- Bar {bar:03d} ---")
        c0 = format_pat_cell(role_on[0].get(r, set()), role_hold[0].get(r, set()), 2)
        c1 = format_pat_cell(role_on[1].get(r, set()), role_hold[1].get(r, set()), 3)
        c2 = format_pat_cell(role_on[2].get(r, set()), role_hold[2].get(r, set()), 3)
        cd = format_drum_cell(drum_row.get(r, set()))
        lines.append(f"  {bar:03d}:{sub:02d}  | {c0:<16s} | {c1:<23s} | {c2:<23s} | {cd}")
    return "\n".join(lines) + "\n"


def render_side_by_side(title: str, bpm: float, bar_offset: int, total_rows: int,
                        grids: list[tuple[str, tuple]]) -> str:
    hdr_cols = " | ".join(f"{name:<30s}" for name, _ in grids)
    lines = [
        f"; Side-by-Side Tracker Pattern Comparison — {title}",
        f"; Grid: {bpm:.3f} BPM, 16 rows/bar | Each cell: [Bass | Mid | High | KSHOC]",
        f"Bar:Row | {hdr_cols}",
        "-" * (10 + 33 * len(grids)),
    ]

    def compact_cell(r: int, role_on, role_hold, drum_row) -> str:
        b = ",".join(midi_to_pat(p) for p in sorted(role_on[0].get(r, set()))[:1]) or ("|" if role_hold[0].get(r) else ".")
        m = ",".join(midi_to_pat(p) for p in sorted(role_on[1].get(r, set()))[:2]) or ("|" if role_hold[1].get(r) else ".")
        h = ",".join(midi_to_pat(p) for p in sorted(role_on[2].get(r, set()))[:2]) or ("|" if role_hold[2].get(r) else ".")
        d = "".join(c if c in drum_row.get(r, set()) else "." for c in ("K", "S", "H", "O", "C"))
        return f"{b:<4s} {m:<8s} {h:<8s} {d}"

    for r in range(total_rows):
        bar = bar_offset + r // 16
        sub = r % 16
        if sub == 0:
            lines.append(f"; === Bar {bar:03d} ===")
        cells = []
        any_evt = False
        for _, (ron, rhold, drow) in grids:
            if ron[0].get(r) or ron[1].get(r) or ron[2].get(r) or drow.get(r):
                any_evt = True
            cells.append(f"{compact_cell(r, ron, rhold, drow):<30s}")
        if any_evt or sub % 4 == 0:
            lines.append(f"{bar:03d}:{sub:02d}  | " + " | ".join(cells))
    return "\n".join(lines) + "\n"


def render_ascii_tab(title: str, bpm: float, bar_offset: int, n_bars: int,
                     role_on, drum_row) -> str:
    from make_notes import BASS as BASS_TUNINGS, GUITAR as GUITAR_TUNINGS, playable, viterbi

    lines = [
        f"# ASCII Tablature — {title} ({bpm:.3f} BPM, 16th-note columns per bar)",
        "",
    ]

    def build_fretted_section(sec_title: str, role_indices: list[int],
                              tunings: list[tuple[str, list[int]]], str_labels: list[str]):
        all_p = [p for ri in role_indices for ps in role_on[ri].values() for p in ps]
        if not all_p:
            return [f"[{sec_title}: (no notes)]", ""]
        lo_p = min(all_p)
        t_name, tuning = tunings[-1]
        for nm, tun in tunings:
            if lo_p >= tun[-1]:
                t_name, tuning = nm, tun
                break
        rows_list, groups = [], []
        for r in range(n_bars * 16):
            ps = sorted({p for ri in role_indices for p in role_on[ri].get(r, set())})
            if not ps:
                continue
            _, fs, _ = playable(ps, tuning, spans=(4, 5, 7))
            if fs:
                rows_list.append(r)
                groups.append(fs)
        chosen = dict(zip(rows_list, viterbi(groups))) if groups else {}

        out = [f"[{sec_title} — {t_name}]"]
        for b0 in range(0, n_bars, 2):
            b1 = min(n_bars, b0 + 2)
            hdr = "    " + "".join(
                f"| Bar {bar_offset + b:03d}" + " " * (32 - len(f"| Bar {bar_offset + b:03d}"))
                for b in range(b0, b1)
            ) + "|"
            out.append(hdr)
            for s_idx, lbl in enumerate(str_labels):
                s_num = s_idx + 1
                row_str = f"{lbl:<3s} "
                for b in range(b0, b1):
                    row_str += "|"
                    for sub in range(16):
                        fmap = dict(chosen.get(b * 16 + sub, ()))
                        if s_num in fmap:
                            ft = str(fmap[s_num])
                            row_str += ft if len(ft) == 2 else (ft + "-")
                        else:
                            row_str += "--"
                row_str += "|"
                out.append(row_str)
            out.append("")
        return out

    lines += build_fretted_section("Bass Tab", [0], BASS_TUNINGS, ["G", "D", "A", "E"])
    lines += build_fretted_section("Mid / Lead Tab", [1, 2], GUITAR_TUNINGS, ["e", "B", "G", "D", "A", "E"])

    lines.append("[Drums Tab — C=Crash O=OpenHH H=ClosedHH S=Snare K=Kick]")
    d_lanes = [("C", "x"), ("O", "o"), ("H", "x"), ("S", "o"), ("K", "o")]
    for b0 in range(0, n_bars, 2):
        b1 = min(n_bars, b0 + 2)
        hdr = "    " + "".join(
            f"| Bar {bar_offset + b:03d}" + " " * (32 - len(f"| Bar {bar_offset + b:03d}"))
            for b in range(b0, b1)
        ) + "|"
        lines.append(hdr)
        for cls, sym in d_lanes:
            row_str = f"{cls:<3s} "
            for b in range(b0, b1):
                row_str += "|"
                for sub in range(16):
                    row_str += (sym + "-") if cls in drum_row.get(b * 16 + sub, set()) else "--"
            row_str += "|"
            lines.append(row_str)
        lines.append("")

    return "\n".join(lines) + "\n"


def render_abc_notation(title: str, bpm: float, bar_offset: int, n_bars: int, role_on, role_hold) -> str:
    lines = [
        "X:1",
        f"T:{title}",
        "M:4/4",
        "L:1/16",
        f"Q:1/4={int(round(bpm))}",
        "K:C",
    ]
    voice_specs = [
        ('V:1 name="High/Lead" clef=treble', 2),
        ('V:2 name="Mid/Chords" clef=treble', 1),
        ('V:3 name="Bass" clef=bass', 0),
    ]
    for vhdr, ri in voice_specs:
        lines.append(vhdr)
        for b in range(n_bars):
            tokens = []
            sub = 0
            while sub < 16:
                r = b * 16 + sub
                on = sorted(role_on[ri].get(r, set()))
                if not on:
                    end = sub + 1
                    while end < 16 and (end % 4 != 0) and not role_on[ri].get(b * 16 + end):
                        end += 1
                    d = end - sub
                    tokens.append("z" if d == 1 else f"z{d}")
                    sub = end
                else:
                    end = sub + 1
                    while end < 16 and not role_on[ri].get(b * 16 + end) and (set(on) & role_hold[ri].get(b * 16 + end, set())):
                        end += 1
                    d = end - sub
                    dstr = "" if d == 1 else str(d)
                    if len(on) == 1:
                        tokens.append(f"{midi_to_abc(on[0])}{dstr}")
                    else:
                        tokens.append("[" + "".join(midi_to_abc(p) for p in on[:4]) + f"]{dstr}")
                    sub = end
            lines.append(f"% Bar {bar_offset + b}")
            lines.append(" ".join(tokens) + " |")
    return "\n".join(lines) + "\n"


def match_bipartite_f1(ref_ev, est_ev, tol_s: float, key_fn):
    used = [False] * len(est_ev)
    m = 0
    for r in ref_ev:
        rt, rk = r[0], key_fn(r)
        best_j, best_dt = -1, tol_s + 1.0
        for j, e in enumerate(est_ev):
            if used[j] or key_fn(e) != rk:
                continue
            dt = abs(e[0] - rt)
            if dt <= tol_s and dt < best_dt:
                best_dt, best_j = dt, j
        if best_j >= 0:
            used[best_j] = True
            m += 1
    p = m / max(1, len(est_ev))
    rc = m / max(1, len(ref_ev))
    f1 = 2 * p * rc / max(1e-12, p + rc)
    return {"matched": m, "ref": len(ref_ev), "est": len(est_ev),
            "P": round(p, 3), "R": round(rc, 3), "F1": round(f1, 3)}


def frame_roll_f1(ref_p, est_p, dur_s: float, hop_s: float = 0.02,
                  chroma: bool = False, p_lo: int = 0, p_hi: int = 127):
    import numpy as np

    nf = max(1, int(math.ceil(dur_s / hop_s)))
    nb = 12 if chroma else 128
    ra = np.zeros((nf, nb), dtype=bool)
    eb = np.zeros((nf, nb), dtype=bool)
    for a, b, p, _ in ref_p:
        if not (p_lo <= p <= p_hi):
            continue
        i0 = max(0, min(nf - 1, int(round(a / hop_s))))
        i1 = max(i0 + 1, min(nf, int(round(b / hop_s))))
        ra[i0:i1, (p % 12) if chroma else p] = True
    for a, b, p, _ in est_p:
        if not (p_lo <= p <= p_hi):
            continue
        i0 = max(0, min(nf - 1, int(round(a / hop_s))))
        i1 = max(i0 + 1, min(nf, int(round(b / hop_s))))
        eb[i0:i1, (p % 12) if chroma else p] = True
    tp = int(np.sum(ra & eb))
    rp = int(np.sum(ra))
    ep = int(np.sum(eb))
    p = tp / max(1, ep)
    r = tp / max(1, rp)
    f1 = 2 * p * r / max(1e-12, p + r)
    return {"P": round(p, 3), "R": round(r, 3), "F1": round(f1, 3)}


def score_symbolic(ref_p, ref_d, est_p, est_d, dur_s: float, pat_ref: str, pat_est: str) -> dict:
    hat_set = {"H", "O", "C"}
    r_rows = [ln for ln in pat_ref.splitlines() if ln.startswith("  ")]
    e_rows = [ln for ln in pat_est.splitlines() if ln.startswith("  ")]
    n_cmp = min(len(r_rows), len(e_rows))
    exact_rows = sum(1 for i in range(n_cmp) if r_rows[i] == e_rows[i])
    return {
        "note_onset_pitch_50ms": match_bipartite_f1(ref_p, est_p, 0.050, lambda x: x[2]),
        "note_onset_chroma_50ms": match_bipartite_f1(ref_p, est_p, 0.050, lambda x: x[2] % 12),
        "frame_20ms_pitch": frame_roll_f1(ref_p, est_p, dur_s, chroma=False),
        "frame_20ms_chroma": frame_roll_f1(ref_p, est_p, dur_s, chroma=True),
        "frame_bass_le44": frame_roll_f1(ref_p, est_p, dur_s, chroma=False, p_lo=0, p_hi=44),
        "frame_mid_45_63": frame_roll_f1(ref_p, est_p, dur_s, chroma=False, p_lo=45, p_hi=63),
        "frame_high_ge64": frame_roll_f1(ref_p, est_p, dur_s, chroma=False, p_lo=64, p_hi=127),
        "drums_any_35ms": match_bipartite_f1(ref_d, est_d, 0.035, lambda x: "D"),
        "drums_kick_35ms": match_bipartite_f1([d for d in ref_d if d[1] == "K"], [d for d in est_d if d[1] == "K"], 0.035, lambda x: "K"),
        "drums_snare_35ms": match_bipartite_f1([d for d in ref_d if d[1] == "S"], [d for d in est_d if d[1] == "S"], 0.035, lambda x: "S"),
        "drums_hats_35ms": match_bipartite_f1([d for d in ref_d if d[1] in hat_set], [d for d in est_d if d[1] in hat_set], 0.035, lambda x: "H"),
        "pat_exact_row_pct": round(100.0 * exact_rows / max(1, n_cmp), 1),
        "pat_seq_similarity": round(difflib.SequenceMatcher(None, r_rows, e_rows).ratio(), 3),
    }


def parse_args():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1],
    )
    ref_grp = ap.add_mutually_exclusive_group(required=True)
    ref_grp.add_argument("--yaml", type=Path, help="Ground-truth VultureTracker song YAML")
    ref_grp.add_argument("--ref-midi", type=Path, help="Reference MIDI file to diff candidates against")
    ref_grp.add_argument("--audio", type=Path, help="Reference audio WAV (extracts acoustic CQT ridges + 3-band drums)")

    ap.add_argument("--midi", action="append", required=True, metavar="LABEL=PATH",
                    help="Candidate MIDI to evaluate (repeatable; e.g. --midi independent=out.mid)")
    ap.add_argument("--out-dir", required=True, type=Path, help="Output folder for .pat.txt, .tab.txt, .abc, .diff, and JSON")
    ap.add_argument("--bpm", type=float, required=True, help="Grid BPM for 16th-note bar/row quantization")
    ap.add_argument("--start-s", type=float, default=0.0, help="Start offset in seconds (default: 0.0)")
    ap.add_argument("--midi-start-s", type=float, default=None,
                    help="Optional separate start offset for candidate MIDIs (default: same as --start-s)")
    ap.add_argument("--duration-s", type=float, default=None, help="Duration in seconds (default: full reference length)")
    ap.add_argument("--row0-s", type=float, default=0.0, help="16th-note grid phase offset inside window in seconds (default: 0.0)")
    ap.add_argument("--bar-offset", type=int, default=1, help="First bar number in headers (default: 1)")
    ap.add_argument("--skip-channels", default="", help="Comma-separated YAML channel names to exclude from ground truth")
    ap.add_argument("--octave-shift", action="append", default=[], metavar="CHANNEL=SEMITONES",
                    help="Optional semitone shift for a YAML channel (e.g. bass=12 for 2f sub-bass)")
    ap.add_argument("--title", default=None, help="Short title for headers (default: reference stem)")
    args = ap.parse_args()

    if not (20.0 <= args.bpm <= 400.0):
        ap.error("--bpm must be between 20 and 400")
    if args.start_s < 0:
        ap.error("--start-s must be >= 0")
    if args.duration_s is not None and args.duration_s <= 0.25:
        ap.error("--duration-s must be > 0.25")

    ref_file = args.yaml or args.ref_midi or args.audio
    if not ref_file.is_file():
        ap.error(f"Reference file not found: {ref_file}")

    cands = []
    for spec in args.midi:
        if "=" not in spec:
            ap.error(f"--midi must be LABEL=PATH (got: {spec!r})")
        lbl, pstr = spec.split("=", 1)
        lbl = lbl.strip()
        mp = Path(pstr.strip())
        if not lbl:
            ap.error(f"Empty label in --midi {spec!r}")
        if not mp.is_file():
            ap.error(f"Candidate MIDI not found: {mp}")
        cands.append((lbl, mp))
    args.candidates = cands

    shifts = {}
    for spec in args.octave_shift:
        if "=" not in spec:
            ap.error(f"--octave-shift must be CHANNEL=SEMITONES (got: {spec!r})")
        ch, sval = spec.split("=", 1)
        try:
            shifts[ch.strip().lower()] = int(sval.strip())
        except ValueError:
            ap.error(f"Invalid integer in --octave-shift {spec!r}")
    args.shifts = shifts
    return args


def main() -> None:
    args = parse_args()
    t0 = args.start_s
    midi_t0 = args.start_s if args.midi_start_s is None else args.midi_start_s

    if args.yaml:
        skip = {s.strip() for s in args.skip_channels.split(",") if s.strip()}
        ref_p, ref_d, full_len = load_yaml_ground_truth(
            args.yaml, t0=t0, t1=(t0 + args.duration_s) if args.duration_s else None,
            skip_channels=skip, octave_shift=args.shifts,
        )
        ref_label = "yaml-truth"
        dur_s = args.duration_s if args.duration_s is not None else max(0.5, full_len - t0)
        title = args.title or args.yaml.stem
    elif args.ref_midi:
        import pretty_midi as pm
        full_len = pm.PrettyMIDI(str(args.ref_midi)).get_end_time()
        dur_s = args.duration_s if args.duration_s is not None else max(0.5, full_len - t0)
        ref_p, ref_d = load_midi_events(args.ref_midi, t0=t0, t1=t0 + dur_s)
        ref_label = "ref-midi"
        title = args.title or args.ref_midi.stem
    else:
        ref_p, ref_d, dur_s = extract_acoustic_ridge_reference(args.audio, t0=t0, dur=args.duration_s)
        ref_label = "cqt-ridges"
        title = args.title or args.audio.stem

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    total_rows, n_bars, r_on, r_hold, r_dr = quantize_to_grid(ref_p, ref_d, args.bpm, args.row0_s, dur_s)
    ref_pat = render_tracker_pattern(f"{title} [{ref_label}]", args.bpm, args.bar_offset, total_rows, r_on, r_hold, r_dr)
    ref_tab = render_ascii_tab(f"{title} [{ref_label}]", args.bpm, args.bar_offset, n_bars, r_on, r_dr)
    ref_abc = render_abc_notation(f"{title} [{ref_label}]", args.bpm, args.bar_offset, n_bars, r_on, r_hold)
    (out_dir / f"00-{ref_label}.pat.txt").write_text(ref_pat, encoding="utf-8", newline="\n")
    (out_dir / f"00-{ref_label}.tab.txt").write_text(ref_tab, encoding="utf-8", newline="\n")
    (out_dir / f"00-{ref_label}.abc").write_text(ref_abc, encoding="utf-8", newline="\n")

    sbs_grids = [(ref_label, (r_on, r_hold, r_dr))]
    results = {
        "title": title, "bpm": args.bpm, "start_s": t0, "midi_start_s": midi_t0,
        "duration_s": round(dur_s, 3), "reference": ref_label,
        "ref_counts": {"pitched": len(ref_p), "drums": len(ref_d)}, "modes": {},
    }

    cand_pats = {}
    cand_events = {}
    for idx, (mname, mid_path) in enumerate(args.candidates, start=1):
        cp, cd = load_midi_events(mid_path, t0=midi_t0, t1=midi_t0 + dur_s)
        cand_events[mname] = (cp, cd)
        _, _, c_on, c_hold, c_dr = quantize_to_grid(cp, cd, args.bpm, args.row0_s, dur_s)
        c_pat = render_tracker_pattern(f"{title} [{mname}]", args.bpm, args.bar_offset, total_rows, c_on, c_hold, c_dr)
        c_tab = render_ascii_tab(f"{title} [{mname}]", args.bpm, args.bar_offset, n_bars, c_on, c_dr)
        c_abc = render_abc_notation(f"{title} [{mname}]", args.bpm, args.bar_offset, n_bars, c_on, c_hold)
        (out_dir / f"{idx:02d}-{mname}.pat.txt").write_text(c_pat, encoding="utf-8", newline="\n")
        (out_dir / f"{idx:02d}-{mname}.tab.txt").write_text(c_tab, encoding="utf-8", newline="\n")
        (out_dir / f"{idx:02d}-{mname}.abc").write_text(c_abc, encoding="utf-8", newline="\n")
        cand_pats[mname] = c_pat

        pdiff = "".join(difflib.unified_diff(
            ref_pat.splitlines(keepends=True), c_pat.splitlines(keepends=True),
            fromfile=f"{ref_label}.pat.txt", tofile=f"{mname}.pat.txt", n=2,
        ))
        tdiff = "".join(difflib.unified_diff(
            ref_tab.splitlines(keepends=True), c_tab.splitlines(keepends=True),
            fromfile=f"{ref_label}.tab.txt", tofile=f"{mname}.tab.txt", n=2,
        ))
        (out_dir / f"diff-{ref_label}-vs-{mname}.pat.diff").write_text(pdiff, encoding="utf-8", newline="\n")
        (out_dir / f"diff-{ref_label}-vs-{mname}.tab.diff").write_text(tdiff, encoding="utf-8", newline="\n")

        if len(sbs_grids) < 5:
            sbs_grids.append((mname, (c_on, c_hold, c_dr)))

        sc = score_symbolic(ref_p, ref_d, cp, cd, dur_s, ref_pat, c_pat)
        results["modes"][mname] = sc
        print(
            f"[{title} | {mname:12s}] NotePitch F1={sc['note_onset_pitch_50ms']['F1']:.3f} "
            f"(P={sc['note_onset_pitch_50ms']['P']:.2f} R={sc['note_onset_pitch_50ms']['R']:.2f}) | "
            f"FrmPitch F1={sc['frame_20ms_pitch']['F1']:.3f} FrmChroma F1={sc['frame_20ms_chroma']['F1']:.3f} "
            f"(B={sc['frame_bass_le44']['F1']:.2f} M={sc['frame_mid_45_63']['F1']:.2f} H={sc['frame_high_ge64']['F1']:.2f}) | "
            f"Drums F1={sc['drums_any_35ms']['F1']:.3f} "
            f"(K={sc['drums_kick_35ms']['F1']:.2f} S={sc['drums_snare_35ms']['F1']:.2f} H={sc['drums_hats_35ms']['F1']:.2f})"
        )

    # Pairwise unified pattern diffs between first candidate and subsequent candidates
    if len(args.candidates) >= 2:
        base_name = args.candidates[0][0]
        for other_name, _ in args.candidates[1:]:
            ud = "".join(difflib.unified_diff(
                cand_pats[base_name].splitlines(keepends=True),
                cand_pats[other_name].splitlines(keepends=True),
                fromfile=f"{base_name}.pat.txt", tofile=f"{other_name}.pat.txt", n=2,
            ))
            (out_dir / f"diff-{base_name}-vs-{other_name}.pat.diff").write_text(ud, encoding="utf-8", newline="\n")

    sbs = render_side_by_side(title, args.bpm, args.bar_offset, total_rows, sbs_grids)
    (out_dir / "side-by-side.pat.txt").write_text(sbs, encoding="utf-8", newline="\n")
    (out_dir / "symbolic-metrics.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
