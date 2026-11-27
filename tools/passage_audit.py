"""Audit a short audio passage against its MIDI transcription and FluidSynth GM render,
separating SoundFont timbre/dynamics mismatch from genuine MIDI note/drum errors.

Runs in the basic-pitch environment that `tools/transcribe_audio.py --setup` creates
(librosa, pretty_midi, soundfile, scipy, matplotlib, FluidSynth + TimGM6mb):

  <env>/bp/Scripts/python tools/passage_audit.py --orig recording.wav --midi song.mid
      --out-dir scratch/audit/passage --start-s 192.03 --duration-s 18.46 [--gm render.wav]

Outputs loudness-matched Original, GM Mix, and Neutral-Synth (unmodified MIDI) WAVs,
a concatenated A/B/C WAV, per-track GM solos via `tools/render_gm.py --track`,
`vulturetracker/measure.py` & `tools/transcription_diff.py` scores, 6-band A-weighted
energy, chroma/envelope/onset correlations, note-by-note local CQT audit, a multi-panel
diagnostic PNG, and `passage-report.json`.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
RENDER_GM = TOOLS / "render_gm.py"
DIFF_PY = TOOLS / "transcription_diff.py"
RATE = 44100


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "track").lower()).strip("-")
    return s or "track"


def read_stereo_f32(path: Path, target_sr: int = RATE):
    import librosa
    import numpy as np
    import soundfile as sf

    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    elif x.shape[1] > 2:
        x = x[:, :2]
    if sr != target_sr:
        ch0 = librosa.resample(x[:, 0], orig_sr=sr, target_sr=target_sr)
        ch1 = librosa.resample(x[:, 1], orig_sr=sr, target_sr=target_sr)
        x = np.stack([ch0, ch1], axis=1).astype(np.float32)
        sr = target_sr
    return x, sr


def crop_audio(x, sr: int, t0: float, t1: float, fade_ms: float = 15.0):
    import numpy as np

    i0 = int(round(t0 * sr))
    i1 = int(round(t1 * sr))
    n = max(1, i1 - i0)
    out = np.zeros((n, x.shape[1]), dtype=np.float32)
    a0, a1 = max(0, i0), min(len(x), i1)
    if a1 > a0:
        out[a0 - i0:a1 - i0] = x[a0:a1]
    nf = min(n // 4, int(round(fade_ms * sr / 1000.0)))
    if nf > 1:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, nf, dtype=np.float32))
        out[:nf] *= ramp[:, None]
        out[-nf:] *= ramp[::-1, None]
    return out


def calc_lufs(x_stereo, sr: int = RATE) -> float:
    import numpy as np
    sys.path.insert(0, str(ROOT))
    from vulturetracker import dsp

    return float(dsp.integrated_lufs(x_stereo.T.astype(np.float64), sr))


def write_wav_s16(path: Path, x_stereo, sr: int = RATE) -> dict:
    import numpy as np

    peak = float(np.max(np.abs(x_stereo)))
    clipped = int(np.sum(np.abs(x_stereo) >= 1.0))
    pcm = np.clip(np.round(x_stereo * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setparams((2, 2, sr, 0, "NONE", ""))
        w.writeframes(pcm.tobytes())
    lufs = calc_lufs(x_stereo, sr)
    return {
        "lufs": round(lufs, 2) if math.isfinite(lufs) else None,
        "peak_dbfs": round(20.0 * math.log10(max(peak, 1e-9)), 2),
        "clipped_samples": clipped,
        "seconds": round(len(x_stereo) / sr, 3),
    }


def scale_to_lufs(x_stereo, target_lufs: float, max_peak_dbfs: float = -1.0):
    import numpy as np

    cur = calc_lufs(x_stereo, RATE)
    if not math.isfinite(cur) or cur < -80.0:
        return x_stereo.copy(), 0.0
    gain_db = target_lufs - cur
    y = x_stereo * (10.0 ** (gain_db / 20.0))
    peak = float(np.max(np.abs(y)))
    cap = 10.0 ** (max_peak_dbfs / 20.0)
    if peak > cap:
        trim_db = 20.0 * math.log10(cap / peak)
        y = y * (cap / peak)
        gain_db += trim_db
    return y.astype(np.float32), gain_db


def synthesize_neutral_pitched(mid, t0: float, t1: float, src_mono, sr: int = RATE):
    """Synthesize unmodified pitched MIDI notes with a clean band-limited sawtooth and
    a 250 ms source macro loudness follower to separate SoundFont timbre from MIDI notes."""
    import numpy as np
    from scipy import signal
    from scipy.ndimage import uniform_filter1d

    n = len(src_mono)
    out = np.zeros(n, dtype=np.float64)
    nyq = 0.5 * sr

    for ins in mid.instruments:
        if ins.is_drum:
            continue
        for nt in ins.notes:
            if nt.end <= t0 or nt.start >= t1:
                continue
            f0 = 440.0 * (2.0 ** ((nt.pitch - 69) / 12.0))
            s_a = max(0, int(round((nt.start - t0) * sr)))
            rel_s = 0.08 if nt.pitch < 60 else 0.05
            s_off = int(round((nt.end - t0) * sr))
            s_b = min(n, int(round((nt.end + rel_s - t0) * sr)))
            if s_b <= s_a:
                continue
            length = s_b - s_a
            t = (np.arange(length, dtype=np.float64) + (s_a - (nt.start - t0) * sr)) / sr
            max_h = max(1, min(14, int(min(6500.0, 0.4 * nyq) / max(f0, 20.0))))
            sig = np.zeros(length, dtype=np.float64)
            for k in range(1, max_h + 1):
                sig += (1.0 / (k ** 1.15)) * np.sin(2.0 * np.pi * f0 * k * t)
            env = np.ones(length, dtype=np.float64)
            att = min(length, int(round(0.012 * sr)))
            if att > 1:
                env[:att] = np.linspace(0.0, 1.0, att)
            rel_start = max(0, min(length, s_off - s_a))
            if rel_start < length:
                env[rel_start:] = np.linspace(1.0, 0.0, length - rel_start)
            reg_gain = 1.0 if nt.pitch < 48 else (0.55 if nt.pitch < 64 else 0.30)
            vel_gain = (nt.velocity / 127.0) ** 1.2
            out[s_a:s_b] += sig * env * reg_gain * vel_gain

    if np.max(np.abs(out)) > 0:
        b_lp, a_lp = signal.butter(2, 7000.0 / nyq, btype="low")
        out = signal.filtfilt(b_lp, a_lp, out)
        win = max(1, int(round(0.25 * sr)))
        src_env = np.sqrt(uniform_filter1d(src_mono.astype(np.float64) ** 2, size=win, mode="nearest") + 1e-8)
        syn_env = np.sqrt(uniform_filter1d(out ** 2, size=win, mode="nearest") + 1e-8)
        ratio = np.clip(src_env / np.maximum(syn_env, 1e-4), 0.15, 4.0)
        ratio = uniform_filter1d(ratio, size=win, mode="nearest")
        out = out * ratio
    return np.stack([out, out], axis=1).astype(np.float32)


def six_band_dba(mono, sr: int = RATE) -> dict:
    import librosa
    import numpy as np

    bands = [
        ("20-100Hz", 20, 100),
        ("100-250Hz", 100, 250),
        ("250-600Hz", 250, 600),
        ("600-1500Hz", 600, 1500),
        ("1.5-4kHz", 1500, 4000),
        ("4-12kHz", 4000, 12000),
    ]
    n_fft, hop = 4096, 1024
    spec = np.abs(librosa.stft(mono.astype(np.float32), n_fft=n_fft, hop_length=hop)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    a_lin = 10.0 ** (librosa.A_weighting(np.maximum(freqs, 10.0)) / 10.0)
    p_a = (spec * a_lin[:, None]).mean(axis=1)
    tot = float(p_a[(freqs >= 20) & (freqs <= 12000)].sum()) + 1e-20
    return {name: round(100.0 * float(p_a[(freqs >= lo) & (freqs < hi)].sum()) / tot, 1) for name, lo, hi in bands}


def cqt_chroma_and_metrics(src_mono, test_mono, sr: int = RATE, split_s: float | None = None) -> dict:
    import librosa
    import numpy as np

    sr22, hop, lo, nb = 22050, 512, 24, 84
    a = librosa.resample(src_mono.astype(np.float32), orig_sr=sr, target_sr=sr22)
    b = librosa.resample(test_mono.astype(np.float32), orig_sr=sr, target_sr=sr22)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]

    ca_mat = np.abs(librosa.cqt(a, sr=sr22, hop_length=hop, fmin=librosa.midi_to_hz(lo), n_bins=nb))
    cb_mat = np.abs(librosa.cqt(b, sr=sr22, hop_length=hop, fmin=librosa.midi_to_hz(lo), n_bins=nb))

    def to_chroma(mat):
        ch = np.zeros((12, mat.shape[1]), dtype=np.float64)
        for i in range(mat.shape[0]):
            ch[(lo + i) % 12] += mat[i] ** 2
        ch = np.sqrt(ch)
        return ch / np.maximum(np.linalg.norm(ch, axis=0, keepdims=True), 1e-9)

    cos = np.sum(to_chroma(ca_mat) * to_chroma(cb_mat), axis=0)
    fps = sr22 / hop

    sa = np.abs(librosa.stft(a, n_fft=2048, hop_length=hop)) ** 2
    sb = np.abs(librosa.stft(b, n_fft=2048, hop_length=hop)) ** 2
    freqs = librosa.fft_frequencies(sr=sr22, n_fft=2048)
    awt = 10.0 ** (librosa.A_weighting(np.maximum(freqs, 10.0)) / 10.0)
    ea = 10.0 * np.log10((sa * awt[:, None]).sum(axis=0) + 1e-12)
    eb = 10.0 * np.log10((sb * awt[:, None]).sum(axis=0) + 1e-12)
    k5 = np.ones(5) / 5.0
    ea_s = np.convolve(ea, k5, mode="same")
    eb_s = np.convolve(eb, k5, mode="same")
    env_r = float(np.corrcoef(ea_s, eb_s)[0, 1]) if np.std(ea_s) > 0 and np.std(eb_s) > 0 else 0.0

    sel = (freqs >= 120) & (freqs <= 3500)
    la = 10.0 * np.log10(sa[sel] + 1e-10)
    lb = 10.0 * np.log10(sb[sel] + 1e-10)
    la = np.maximum(la, la.max() - 60.0)
    lb = np.maximum(lb, lb.max() - 60.0)
    spec2d_r = float(np.corrcoef(la.ravel(), lb.ravel())[0, 1])

    cent_a = float(np.median(librosa.feature.spectral_centroid(y=a, sr=sr22, hop_length=hop)[0]))
    cent_b = float(np.median(librosa.feature.spectral_centroid(y=b, sr=sr22, hop_length=hop)[0]))
    oa = librosa.onset.onset_strength(y=a, sr=sr22, hop_length=hop)
    ob = librosa.onset.onset_strength(y=b, sr=sr22, hop_length=hop)
    onset_r = float(np.corrcoef(oa, ob)[0, 1]) if np.std(oa) > 0 and np.std(ob) > 0 else 0.0

    res = {
        "chroma_cos_all": round(float(cos.mean()), 3),
        "env_dba_corr_100ms": round(env_r, 3),
        "spec2d_log_corr_120_3500hz": round(spec2d_r, 3),
        "onset_strength_corr": round(onset_r, 3),
        "centroid_src_hz": round(cent_a, 0),
        "centroid_test_hz": round(cent_b, 0),
        "chroma_series": cos,
        "Ca_db": librosa.amplitude_to_db(ca_mat, ref=np.max),
        "fps": fps,
    }
    if split_s is not None and 0.0 < split_s < n / sr22:
        sf_idx = int(round(split_s * fps))
        res["chroma_cos_before_split"] = round(float(cos[:sf_idx].mean()), 3)
        res["chroma_cos_after_split"] = round(float(cos[sf_idx:].mean()), 3)
    return res


def make_cropped_midi(src_mid: Path, dst_mid: Path, t0: float, t1: float) -> None:
    import pretty_midi as pm

    mid = pm.PrettyMIDI(str(src_mid))
    tempos = mid.get_tempo_changes()[1]
    bpm = float(tempos[0]) if len(tempos) else 120.0
    out = pm.PrettyMIDI(initial_tempo=bpm)
    for ins in mid.instruments:
        ni = pm.Instrument(program=ins.program, is_drum=ins.is_drum, name=ins.name)
        for nt in ins.notes:
            if nt.end <= t0 or nt.start >= t1:
                continue
            a = max(0.0, nt.start - t0)
            b = min(t1 - t0, nt.end - t0)
            if b - a >= 0.015:
                ni.notes.append(pm.Note(velocity=nt.velocity, pitch=nt.pitch, start=a, end=b))
        if ni.notes:
            out.instruments.append(ni)
    out.write(str(dst_mid))


def classify_passage_notes(src_mono, mid, t0: float, t1: float):
    import librosa
    import numpy as np
    from scipy import signal

    sr22, hop, lo, nb = 22050, 512, 24, 84
    y = librosa.resample(src_mono.astype(np.float32), orig_sr=RATE, target_sr=sr22)
    c_mat = np.abs(librosa.cqt(y, sr=sr22, hop_length=hop, fmin=librosa.midi_to_hz(lo), n_bins=nb))
    c_db = librosa.amplitude_to_db(c_mat, ref=np.max)
    freqs = librosa.cqt_frequencies(nb, fmin=librosa.midi_to_hz(lo))
    c_dba = c_db + librosa.A_weighting(freqs)[:, None]
    fps = sr22 / hop

    def band_onsets(lo_hz, hi_hz):
        sos = signal.butter(4, [lo_hz / (0.5 * sr22), min(hi_hz, 0.48 * sr22) / (0.5 * sr22)], btype="band", output="sos")
        yb = signal.sosfiltfilt(sos, y)
        env = librosa.onset.onset_strength(y=yb.astype(np.float32), sr=sr22, hop_length=256)
        return librosa.onset.onset_detect(onset_envelope=env, sr=sr22, hop_length=256, units="time")

    on_all = librosa.onset.onset_detect(y=y, sr=sr22, hop_length=256, units="time")
    on_lo = band_onsets(30, 150)
    on_mid = band_onsets(200, 1800)
    on_hi = band_onsets(3500, 10500)

    all_p = [
        (ti, nt)
        for ti, ins in enumerate(mid.instruments)
        if not ins.is_drum
        for nt in ins.notes
        if nt.end > t0 and nt.start < t1
    ]

    per_track = {}
    note_records = []

    for ti, ins in enumerate(mid.instruments):
        ns = [nt for nt in ins.notes if nt.end > t0 and nt.start < t1]
        if ins.is_drum:
            by_key = {}
            matched_all = matched_band = 0
            for nt in ns:
                rt = nt.start - t0
                if rt < 0 or rt > (t1 - t0):
                    continue
                ok_all = bool(len(on_all)) and float(np.min(np.abs(on_all - rt))) <= 0.045
                ref = on_lo if nt.pitch in (35, 36) else (on_mid if nt.pitch in (37, 38, 39, 40) else on_hi)
                ok_b = bool(len(ref)) and float(np.min(np.abs(ref - rt))) <= 0.045
                matched_all += ok_all
                matched_band += ok_b
                d = by_key.setdefault(nt.pitch, {"count": 0, "all_ok": 0, "band_ok": 0, "vels": []})
                d["count"] += 1
                d["all_ok"] += int(ok_all)
                d["band_ok"] += int(ok_b)
                d["vels"].append(nt.velocity)
            key_summary = {
                str(k): {
                    "count": d["count"],
                    "broadband_onset_pct": round(100.0 * d["all_ok"] / d["count"], 1),
                    "band_onset_pct": round(100.0 * d["band_ok"] / d["count"], 1),
                    "vel_med": int(np.median(d["vels"])),
                }
                for k, d in sorted(by_key.items(), key=lambda x: -x[1]["count"])
            }
            hit_ts = np.array([nt.start - t0 for nt in ns if t0 <= nt.start < t1])
            rec_all = float(np.mean([len(hit_ts) > 0 and np.min(np.abs(hit_ts - t)) <= 0.045 for t in on_all])) if len(on_all) else 0.0
            per_track[ins.name or f"Track {ti + 1}"] = {
                "program": None,
                "is_drum": True,
                "notes": len(ns),
                "broadband_onset_precision_pct": round(100.0 * matched_all / max(1, len(ns)), 1),
                "band_onset_precision_pct": round(100.0 * matched_band / max(1, len(ns)), 1),
                "broadband_onset_recall_pct": round(100.0 * rec_all, 1),
                "by_key": key_summary,
            }
            continue

        c_true = c_overtone = c_weak = c_dup = 0
        snrs = []
        vels = [nt.velocity for nt in ns]
        pitches = [nt.pitch for nt in ns]
        tname = ins.name or f"Track {ti + 1}"
        for nt in ns:
            a = max(0.0, nt.start - t0)
            b_t = min(t1 - t0, nt.end - t0)
            i0 = max(0, min(c_dba.shape[1] - 1, int(round(a * fps))))
            i1 = max(i0 + 1, min(c_dba.shape[1], int(round(b_t * fps))))
            bi = nt.pitch - lo
            is_dup = any(
                oti != ti and ont.pitch == nt.pitch and min(ont.end, nt.end) - max(ont.start, nt.start) > 0.04
                for oti, ont in all_p
            )
            if is_dup:
                c_dup += 1
            if not (0 <= bi < nb):
                c_weak += 1
                status, snr = "weak", -10.0
            else:
                val = float(np.mean(c_dba[bi, i0:i1]))
                nb_idx = [bb for bb in (bi - 5, bi - 4, bi + 4, bi + 5) if 0 <= bb < nb]
                bg = float(np.median(np.mean(c_dba[nb_idx, i0:i1], axis=1)))
                snr = val - bg
                lo_b, hi_b = max(0, bi - 2), min(nb, bi + 3)
                loc_max = max(float(np.mean(c_dba[bb, i0:i1])) for bb in range(lo_b, hi_b))
                is_local_peak = (val >= loc_max - 1.5) and (snr >= 3.0)
                raw_val = float(np.mean(c_db[bi, i0:i1]))
                is_overtone = False
                for sh in (12, 19, 24):
                    if bi - sh >= 0 and float(np.mean(c_db[bi - sh, i0:i1])) > raw_val + 4.0:
                        lb = bi - sh
                        l_lo, l_hi = max(0, lb - 2), min(nb, lb + 3)
                        if float(np.mean(c_db[lb, i0:i1])) >= max(float(np.mean(c_db[bb, i0:i1])) for bb in range(l_lo, l_hi)) - 1.0:
                            is_overtone = True
                            break
                if not is_local_peak:
                    c_weak += 1
                    status = "weak"
                elif is_overtone:
                    c_overtone += 1
                    status = "overtone"
                else:
                    c_true += 1
                    status = "true"
            snrs.append(snr)
            note_records.append((ti, tname, a, b_t, nt.pitch, nt.velocity, status))

        per_track[tname] = {
            "program": ins.program,
            "is_drum": False,
            "notes": len(ns),
            "pitch_range": [int(min(pitches)), int(max(pitches))] if pitches else None,
            "pitch_median": int(np.median(pitches)) if pitches else None,
            "vel_min_med_max": [int(min(vels)), int(np.median(vels)), int(max(vels))] if vels else None,
            "local_cqt_peak_ok_pct": round(100.0 * (c_true + c_overtone) / max(1, len(ns)), 1),
            "true_fundamental_count": c_true,
            "overtone_of_stronger_lower_count": c_overtone,
            "weak_or_wrong_pitch_count": c_weak,
            "cross_track_dup_count": c_dup,
            "median_local_snr_dba": round(float(np.median(snrs)), 1) if snrs else None,
        }

    return per_track, note_records


def plot_diagnostic(out_png: Path, title: str, orig_wav: Path, gm_wav: Path,
                    gm_metrics: dict, neu_metrics: dict | None, note_records: list,
                    t0: float, dur: float, bpm: float | None, downbeat_s: float, split_s: float | None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    sys.path.insert(0, str(ROOT))
    from vulturetracker import measure

    st_o, st_g = orig_wav.stat(), gm_wav.stat()
    s_gm, s_orig, d_gm, _, _, _ = measure.reference_compare(
        str(gm_wav), (st_g.st_mtime_ns, st_g.st_size),
        str(orig_wav), (st_o.st_mtime_ns, st_o.st_size),
        0, 0.0, "log",
    )
    fig, ax = plt.subplots(5, 1, figsize=(16, 15), sharex=True,
                           gridspec_kw={"height_ratios": [1.8, 1.8, 1.6, 2.2, 1.3]})

    ext_spec = [0, dur, 0, s_orig.shape[0]]
    ax[0].imshow(s_orig, aspect="auto", origin="lower", extent=ext_spec, cmap="magma", vmin=-90, vmax=-10)
    ax[0].set_ylabel("Original\n(log freq)")
    ax[0].set_title(title)

    ax[1].imshow(s_gm, aspect="auto", origin="lower", extent=ext_spec, cmap="magma", vmin=-90, vmax=-10)
    ax[1].set_ylabel("GM Render")

    ax[2].imshow(np.clip(d_gm, -30, 30), aspect="auto", origin="lower", extent=ext_spec, cmap="RdBu_r", vmin=-30, vmax=30)
    ax[2].set_ylabel("GM - Orig\n(dB, red=GM)")

    ca_db = gm_metrics["Ca_db"]
    ax[3].imshow(ca_db, aspect="auto", origin="lower", extent=[0, dur, 24, 108], cmap="gray_r", alpha=0.45, vmin=-55, vmax=-5)
    palette = ["#e74c3c", "#e67e22", "#2ecc71", "#3498db", "#9b59b6", "#1abc9c", "#f39c12", "#e84393"]
    track_colors = {}
    plotted = set()
    for ti, tname, a, b, pitch, vel, status in note_records:
        col = track_colors.setdefault(tname, palette[len(track_colors) % len(palette)])
        ls = "-" if status == "true" else ("--" if status == "overtone" else ":")
        lw = 3.0 if status == "true" else (2.2 if status == "overtone" else 1.5)
        lbl = tname if tname not in plotted else None
        plotted.add(tname)
        ax[3].plot([a, max(a + 0.04, b)], [pitch, pitch], color=col, linestyle=ls, linewidth=lw,
                   alpha=0.95 if status != "weak" else 0.55, label=lbl)
        if status == "weak":
            ax[3].scatter([a], [pitch], color=col, marker="x", s=22, zorder=5)
    ax[3].set_ylim(24, 88)
    ax[3].set_ylabel("MIDI Pitch\n(solid=f0, --=ot,\nx=weak/wrong)")
    if plotted:
        ax[3].legend(loc="upper left", ncol=min(6, len(plotted)), fontsize=8, framealpha=0.85)

    t_f = np.arange(len(gm_metrics["chroma_series"])) / gm_metrics["fps"]
    ax[4].plot(t_f, gm_metrics["chroma_series"], color="#c0392b", lw=1.4,
               label=f"Chroma cos GM (mean {gm_metrics['chroma_cos_all']:.2f})")
    if neu_metrics is not None:
        ax[4].plot(t_f, neu_metrics["chroma_series"], color="#27ae60", lw=1.4,
                   label=f"Chroma cos Neutral Synth (mean {neu_metrics['chroma_cos_all']:.2f})")
    ax[4].set_ylim(0.0, 1.05)
    ax[4].set_ylabel("Chroma\nCosine")
    ax[4].legend(loc="lower left", fontsize=8)
    ax[4].set_xlabel(f"Seconds into passage (0 s = {t0:.2f} s)")

    if bpm and bpm > 0:
        bar_s = 4.0 * 60.0 / bpm
        first_bar = math.ceil((t0 - downbeat_s) / bar_s) * bar_s + downbeat_s - t0
        bx = first_bar
        while bx <= dur + 1e-6:
            if bx >= -1e-6:
                for a_i in ax:
                    a_i.axvline(bx, color="#ffffff", alpha=0.28, lw=0.7)
            bx += bar_s
    if split_s is not None and 0.0 < split_s < dur:
        for a_i in ax:
            a_i.axvline(split_s, color="#f1c40f", alpha=0.9, lw=1.8, linestyle="--")

    fig.tight_layout()
    fig.savefig(str(out_png), dpi=110)
    plt.close(fig)


def parse_args():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1],
    )
    ap.add_argument("--orig", required=True, type=Path, help="Original recording WAV")
    ap.add_argument("--midi", required=True, type=Path, help="Transcribed MIDI file")
    ap.add_argument("--out-dir", required=True, type=Path, help="Output folder for clips, solos, PNGs, and JSON")
    ap.add_argument("--gm", type=Path, help="Pre-rendered full GM WAV (rendered via render_gm.py if omitted)")
    ap.add_argument("--start-s", type=float, default=0.0, help="Passage start time in seconds (default: 0.0)")
    ap.add_argument("--duration-s", type=float, default=18.0, help="Passage duration in seconds (default: 18.0)")
    ap.add_argument("--end-s", type=float, help="Optional passage end time in seconds (overrides --duration-s)")
    ap.add_argument("--bpm", type=float, help="Optional BPM for bar-grid guide lines on the diagnostic PNG")
    ap.add_argument("--downbeat-s", type=float, default=0.0, help="Downbeat offset in seconds for bar lines")
    ap.add_argument("--section-split-s", type=float, help="Optional offset inside passage (seconds) for split chroma metrics")
    ap.add_argument("--target-lufs", type=float, default=-17.0, help="Integrated LUFS target for A/B clips (default: -17.0)")
    ap.add_argument("--skip-solos", action="store_true", help="Skip per-track FluidSynth solo renders")
    ap.add_argument("--skip-neutral", action="store_true", help="Skip neutral-synth timbre control clip")
    ap.add_argument("--label", default="gm", help="Short label for plots and transcription_diff.py")
    args = ap.parse_args()

    for name, p in (("--orig", args.orig), ("--midi", args.midi)):
        if not p.is_file():
            ap.error(f"{name}: file not found: {p}")
    if args.gm is not None and not args.gm.is_file():
        ap.error(f"--gm: file not found: {args.gm}")
    if args.start_s < 0:
        ap.error("--start-s must be >= 0")
    t1 = args.end_s if args.end_s is not None else args.start_s + args.duration_s
    if t1 <= args.start_s + 0.5:
        ap.error("Passage duration must be > 0.5 s")
    if args.bpm is not None and not (20.0 <= args.bpm <= 400.0):
        ap.error("--bpm must be between 20 and 400")
    args.t0, args.t1 = args.start_s, t1
    return args


def main() -> None:
    args = parse_args()
    try:
        import mido
        import numpy as np
        import pretty_midi as pm
    except ImportError as e:
        sys.exit(f"{e.name} is missing: run this with the basic-pitch environment's python (tools/transcribe_audio.py --setup)")

    sys.path.insert(0, str(ROOT))
    from vulturetracker import measure

    t_start = time.time()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    t0, t1 = args.t0, args.t1

    mid = pm.PrettyMIDI(str(args.midi))
    mido_mid = mido.MidiFile(str(args.midi))
    src_full, _ = read_stereo_f32(args.orig, RATE)
    t1 = min(t1, len(src_full) / RATE)
    if t1 <= t0 + 0.5:
        sys.exit(f"Passage [{t0:.2f}, {t1:.2f}] s is outside audio length ({len(src_full) / RATE:.2f} s)")

    orig_clip = crop_audio(src_full, RATE, t0, t1)
    orig_norm, orig_gain_db = scale_to_lufs(orig_clip, args.target_lufs)
    orig_path = out_dir / "01-original.wav"
    files_meta = {
        "01-original.wav": {**write_wav_s16(orig_path, orig_norm), "gain_applied_db": round(orig_gain_db, 2)},
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        gm_source = args.gm
        if gm_source is None:
            gm_source = tmp_dir / "gm-full.wav"
            subprocess.run([sys.executable, str(RENDER_GM), str(args.midi), str(args.orig), str(gm_source)], check=True)
        gm_full, _ = read_stereo_f32(gm_source, RATE)
        gm_clip = crop_audio(gm_full, RATE, t0, t1)
        gm_norm, gm_gain_db = scale_to_lufs(gm_clip, args.target_lufs)
        gm_path = out_dir / "02-gm-all.wav"
        files_meta["02-gm-all.wav"] = {**write_wav_s16(gm_path, gm_norm), "gain_applied_db": round(gm_gain_db, 2)}

        solo_meta = {}
        drums_mix = None
        gm_scale = 10.0 ** (gm_gain_db / 20.0)

        # Match non-empty mido tracks to render_gm --track indices
        note_tracks = [
            (idx, tr.name or f"track-{idx}")
            for idx, tr in enumerate(mido_mid.tracks)
            if any(msg.type == "note_on" and msg.velocity > 0 for msg in tr)
        ]
        if not args.skip_solos:
            for seq, (tr_idx, tr_name) in enumerate(note_tracks, start=1):
                full_solo = tmp_dir / f"solo-{tr_idx}.wav"
                subprocess.run(
                    [sys.executable, str(RENDER_GM), str(args.midi), str(args.orig), str(full_solo), "--track", str(tr_idx)],
                    check=True,
                )
                solo_full, _ = read_stereo_f32(full_solo, RATE)
                in_mix = crop_audio(solo_full, RATE, t0, t1) * gm_scale
                mix_lufs = calc_lufs(in_mix, RATE)
                mix_rms_db = 20.0 * math.log10(max(float(np.sqrt(np.mean(in_mix ** 2))), 1e-9))
                extra_boost_db = 0.0
                out_clip = in_mix
                if math.isfinite(mix_lufs) and mix_lufs < -28.0:
                    out_clip, extra_boost_db = scale_to_lufs(in_mix, -22.0, max_peak_dbfs=-2.0)
                fname = f"{seq + 2:02d}-solo-t{tr_idx}-{slugify(tr_name)}.wav"
                wmeta = write_wav_s16(out_dir / fname, out_clip)
                if tr_name.lower() == "drums":
                    drums_mix = in_mix
                solo_meta[tr_name] = {
                    "file": fname,
                    "track_index": tr_idx,
                    "in_mix_lufs": round(mix_lufs, 2) if math.isfinite(mix_lufs) else None,
                    "in_mix_rms_db": round(mix_rms_db, 2),
                    "extra_solo_boost_db": round(extra_boost_db, 2),
                    **wmeta,
                }

    neu_path = None
    neu_norm = None
    if not args.skip_neutral:
        src_mono = orig_norm.mean(axis=1)
        neu_pitched = synthesize_neutral_pitched(mid, t0, t1, src_mono, RATE)
        p_rms = float(np.sqrt(np.mean(neu_pitched ** 2))) + 1e-9
        if drums_mix is not None and float(np.max(np.abs(drums_mix))) > 1e-5:
            d_rms = float(np.sqrt(np.mean(drums_mix ** 2))) + 1e-9
            neu_combined = (neu_pitched / p_rms * 0.70 + drums_mix / d_rms * 0.45).astype(np.float32)
        else:
            neu_combined = (neu_pitched / p_rms * 0.70).astype(np.float32)
        cur_l = calc_lufs(neu_combined, RATE)
        neu_gain_db = (args.target_lufs - cur_l) if math.isfinite(cur_l) else 0.0
        neu_scaled = neu_combined * (10.0 ** (neu_gain_db / 20.0))
        thresh, ceil_v = 0.80, 0.89
        over = np.abs(neu_scaled) > thresh
        if np.any(over):
            s = np.sign(neu_scaled[over])
            ex = (np.abs(neu_scaled[over]) - thresh) / (ceil_v - thresh)
            neu_scaled[over] = s * (thresh + (ceil_v - thresh) * np.tanh(ex))
        cur_l2 = calc_lufs(neu_scaled, RATE)
        trim = (args.target_lufs - cur_l2) if math.isfinite(cur_l2) else 0.0
        neu_norm = (neu_scaled * (10.0 ** (trim / 20.0))).astype(np.float32)
        neu_path = out_dir / "09-unmodified-midi-neutral-synth.wav"
        files_meta[neu_path.name] = {**write_wav_s16(neu_path, neu_norm), "gain_applied_db": round(neu_gain_db + trim, 2)}

    gap = np.zeros((int(round(0.7 * RATE)), 2), dtype=np.float32)
    ab_parts = [orig_norm, gap, gm_norm] + ([gap, neu_norm] if neu_norm is not None else [])
    ab_path = out_dir / "00-ab-comparison.wav"
    files_meta[ab_path.name] = write_wav_s16(ab_path, np.vstack(ab_parts))

    def run_measure_pair(test_wav: Path):
        so, st = orig_path.stat(), test_wav.stat()
        _, _, _, cols, rg, _ = measure.reference_compare(
            str(test_wav), (st.st_mtime_ns, st.st_size),
            str(orig_path), (so.st_mtime_ns, so.st_size),
            0, 0.0, "log",
        )
        vals = [v for v in cols if v is not None]
        align_ms, align_corr = measure.reference_align(str(test_wav), str(orig_path), 0, 0.0, reach=2.0)
        return {
            "mean_abs_delta_db": round(float(np.mean(vals)), 3),
            "median_abs_delta_db": round(float(np.median(vals)), 2),
            "p95_abs_delta_db": round(float(np.percentile(vals, 95)), 2),
            "ref_gain_db": rg,
            "align_offset_ms": align_ms,
            "onset_novelty_corr": align_corr,
        }

    meas_gm = run_measure_pair(gm_path)
    meas_neu = run_measure_pair(neu_path) if neu_path else None

    crop_mid = out_dir / "passage.mid"
    make_cropped_midi(args.midi, crop_mid, t0, t1)
    diff_gm = json.loads(subprocess.run(
        [sys.executable, str(DIFF_PY), "--orig", str(orig_path), "--render", str(gm_path),
         "--midi", str(crop_mid), "--stems", str(orig_path),
         "--png", str(out_dir / f"diff-{slugify(args.label)}.png"), "--offset-ms", "0", "--label", args.label],
        capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()[-1])

    gm_m = cqt_chroma_and_metrics(orig_norm.mean(axis=1), gm_norm.mean(axis=1), RATE, args.section_split_s)
    neu_m = cqt_chroma_and_metrics(orig_norm.mean(axis=1), neu_norm.mean(axis=1), RATE, args.section_split_s) if neu_norm is not None else None
    per_track_err, note_records = classify_passage_notes(orig_norm.mean(axis=1), mid, t0, t1)

    bands = {
        "original": six_band_dba(orig_norm.mean(axis=1), RATE),
        "gm": six_band_dba(gm_norm.mean(axis=1), RATE),
    }
    if neu_norm is not None:
        bands["neutral_synth"] = six_band_dba(neu_norm.mean(axis=1), RATE)

    title = f"{args.orig.stem} [{args.label}] ({t0:.2f}-{t1:.2f} s) — Timbre vs MIDI Audit"
    plot_diagnostic(out_dir / "passage-diagnostic.png", title, orig_path, gm_path, gm_m, neu_m, note_records,
                    t0, t1 - t0, args.bpm, args.downbeat_s, args.section_split_s)

    report = {
        "passage": {
            "orig": str(args.orig),
            "midi": str(args.midi),
            "label": args.label,
            "t0_s": round(t0, 4),
            "t1_s": round(t1, 4),
            "duration_s": round(t1 - t0, 3),
            "bpm_grid": args.bpm,
            "target_lufs": args.target_lufs,
        },
        "files": files_meta,
        "solos": solo_meta,
        "measure_py": {
            "gm_vs_orig": meas_gm,
            "neutral_vs_orig": meas_neu,
            "mix_numbers": {
                "original": measure.mix_numbers(str(orig_path)),
                "gm": measure.mix_numbers(str(gm_path)),
                **({"neutral_synth": measure.mix_numbers(str(neu_path))} if neu_path else {}),
            },
        },
        "transcription_diff": diff_gm,
        "timbre_vs_midi_metrics": {
            "gm": {k: v for k, v in gm_m.items() if not isinstance(v, np.ndarray) and k != "fps"},
            "neutral_synth": ({k: v for k, v in neu_m.items() if not isinstance(v, np.ndarray) and k != "fps"} if neu_m else None),
            "six_band_dba_pct": bands,
        },
        "per_track_note_audit": per_track_err,
        "elapsed_s": round(time.time() - t_start, 2),
    }

    jdef = lambda o: int(o) if isinstance(o, np.integer) else (float(o) if isinstance(o, np.floating) else str(o))
    rep_path = out_dir / "passage-report.json"
    rep_path.write_text(json.dumps(report, indent=2, default=jdef) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "out_dir": str(out_dir),
        "measure_gm_delta_db": meas_gm["mean_abs_delta_db"],
        "diff_gm_med_db": diff_gm["sound_delta_db_median"],
        "chroma_gm": gm_m["chroma_cos_all"],
        "env_corr_gm": gm_m["env_dba_corr_100ms"],
        "elapsed_s": report["elapsed_s"],
    }))


if __name__ == "__main__":
    main()
