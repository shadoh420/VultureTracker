"""Verify native tuning estimation, multi-window LaneNet transcription, decoding, and MIDI output
against Python Dettato (retune + Transcriber.run + Transcriber.notes).

Usage:
  python mp3tomidi/check_transcribe.py build/mp3tomidi build/weights --ffmpeg dist/ffmpeg.exe
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
import pretty_midi
import soundfile as sf
from safetensors.torch import load_file
import torch
from dettato.audio import Audio
from dettato.grouper import retune
from dettato.transcriber.core import Transcriber
from dettato.transcriber.model import LaneNet


def synth_clip(sr: int = 44100, seconds: float = 9.5, detune_cents: float = 0.0) -> np.ndarray:
    """Synthesize a multi-voice harmonic clip spanning > 8 s (multiple overlapping windows)."""
    n = int(round(seconds * sr))
    t = np.arange(n, dtype=np.float64) / sr
    x = np.zeros(n, dtype=np.float64)
    ratio = 2.0 ** (detune_cents / 1200.0)
    # Piano-like harmonic tones across 9.5 s
    events = [
        (0.4, 2.0, 48, 0.30),  # C3
        (0.4, 2.0, 55, 0.24),  # G3
        (0.8, 1.8, 60, 0.22),  # C4
        (1.6, 2.8, 64, 0.24),  # E4
        (2.4, 4.2, 53, 0.28),  # F3
        (2.4, 4.2, 60, 0.22),  # C4
        (3.2, 4.6, 69, 0.20),  # A4
        (4.5, 6.4, 55, 0.28),  # G3
        (4.5, 6.4, 59, 0.22),  # B3
        (5.0, 6.8, 62, 0.24),  # D4
        (6.8, 8.8, 48, 0.30),  # C3
        (6.8, 8.8, 60, 0.22),  # C4
        (7.4, 9.0, 64, 0.22),  # E4
        (8.0, 9.2, 67, 0.20),  # G4
    ]
    for t0, t1, midi, amp in events:
        f0 = 440.0 * (2.0 ** ((midi - 69) / 12.0)) * ratio
        m = (t >= t0) & (t < t1)
        dt = t[m] - t0
        att = np.minimum(1.0, dt / 0.015)
        rel = np.minimum(1.0, (t1 - t[m]) / 0.03)
        env = att * rel * np.exp(-0.9 * dt)
        sig = np.zeros_like(dt)
        for h in range(1, 7):
            if f0 * h < sr * 0.45:
                sig += (1.0 / (h ** 1.15)) * np.sin(2.0 * np.pi * f0 * h * dt)
        x[m] += amp * env * sig
    peak = np.max(np.abs(x))
    if peak > 0.85:
        x *= 0.85 / peak
    return x.astype(np.float32)


def load_py_transcriber(dettato_dir: Path) -> Transcriber:
    cfg = json.loads((dettato_dir / "config.json").read_text(encoding="utf-8"))
    model = LaneNet(**cfg["model"])
    model.load_state_dict(load_file(str(dettato_dir / "model.safetensors")))
    return Transcriber(model, cfg["thresholds"], device="cpu")


def match_note_lists(ref_notes: list[tuple[float, float, int]],
                     got_notes: list[tuple[float, float, int]],
                     on_tol: float = 0.03, off_tol: float = 0.06) -> tuple[int, int, int, float]:
    used = [False] * len(got_notes)
    matched = 0
    max_on_diff = 0.0
    for ron, roff, rp in ref_notes:
        best_j = -1
        best_err = 1e9
        for j, (gon, goff, gp) in enumerate(got_notes):
            if used[j] or gp != rp:
                continue
            err = abs(gon - ron)
            if err <= on_tol and abs(goff - roff) <= off_tol and err < best_err:
                best_err = err
                best_j = j
        if best_j >= 0:
            used[best_j] = True
            matched += 1
            max_on_diff = max(max_on_diff, best_err)
    return matched, len(ref_notes), len(got_notes), max_on_diff


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary", type=Path)
    p.add_argument("weights_vtwt", type=Path, help="FP16 or FP32 transcriber .vtwt")
    p.add_argument("--ffmpeg", default="dist/ffmpeg.exe")
    p.add_argument("--dettato-dir", type=Path, default=Path("tools/transcribe-env/dettato-weights/dettato"))
    args = p.parse_args()

    binary = str(args.binary.resolve())
    tr = load_py_transcriber(args.dettato_dir)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wdir = root / "w"
        wdir.mkdir()
        shutil.copy2(args.weights_vtwt, wdir / "transcriber.vtwt")

        # 1. Verify retune estimation on both A440 and +27 cents detuned 44.1 kHz MP3
        for detune in (0.0, 27.0):
            sig = synth_clip(44100, seconds=4.0, detune_cents=detune)
            wav, mp3 = root / f"rt_{int(detune)}.wav", root / f"rt_{int(detune)}.mp3"
            sf.write(wav, sig, 44100)
            subprocess.run([args.ffmpeg, "-loglevel", "error", "-y", "-i", str(wav),
                            "-codec:a", "libmp3lame", str(mp3)], check=True)
            decoded, _ = sf.read(mp3, dtype="float32", always_2d=True)
            a16 = Audio(decoded.mean(axis=1), 44100).at(16000)
            rd, rs, rsh, rr = retune.ratio(a16)
            got = json.loads(subprocess.run(
                [binary, "--retune-test", str(mp3)], executable=binary,
                capture_output=True, text=True, check=True,
            ).stdout)
            print(f"[retune {detune:+.0f}c] py=({rd:.3f}c, str={rs:.4f}, sh={rsh:.3f}c) "
                  f"c=({got['delta']:.3f}c, str={got['strength']:.4f}, sh={got['shift']:.3f}c)")
            assert abs(got["delta"] - rd) < 0.05, (got, rd)
            assert abs(got["strength"] - rs) < 0.002, (got, rs)
            assert abs(got["ratio"] - rr) < 5e-5, (got, rr)

        # 2. Full multi-window transcription + MIDI output on a 9.5 s 44.1 kHz stereo MP3 (detuned +24 cents!)
        sig = synth_clip(44100, seconds=9.5, detune_cents=24.0)
        wav, mp3, mid = root / "song.wav", root / "song.mp3", root / "song.mid"
        sf.write(wav, np.column_stack([sig, sig * 0.9]), 44100)
        subprocess.run([args.ffmpeg, "-loglevel", "error", "-y", "-i", str(wav),
                        "-codec:a", "libmp3lame", str(mp3)], check=True)

        # Reference Python Dettato (retune + Transcriber.run + Transcriber.notes)
        decoded, _ = sf.read(mp3, dtype="float32", always_2d=True)
        a16 = Audio(decoded.mean(axis=1), 44100).at(16000)
        _, _, shift, r = retune.ratio(a16)
        y = retune.resample(a16, r) if shift else a16
        maps, _ = tr.run(y, hop_frac=0.25, batch=2)
        res = tr.notes(maps)
        if r != 1.0:
            res["onset"] = res["onset"] * r
            res["offset"] = res["offset"] * r
        ref_notes = [(float(o), float(e), int(p)) for o, e, p in zip(res["onset"], res["offset"], res["pitch"])]

        # Native C CLI -> MIDI
        proc = subprocess.run(
            [binary, str(mp3), "-o", str(mid), "--weights-dir", str(wdir)],
            executable=binary, capture_output=True, text=True, check=True,
        )
        info = json.loads(proc.stdout.strip())
        pm = pretty_midi.PrettyMIDI(str(mid))
        assert len(pm.instruments) == 1
        got_notes = [(n.start, n.end, n.pitch) for n in pm.instruments[0].notes]

        matched, n_ref, n_got, max_on = match_note_lists(ref_notes, got_notes)
        f1 = 2 * matched / max(1, n_ref + n_got)
        print(f"[transcribe 9.5s +24c] {info}")
        print(f"  ref={n_ref} notes, got={n_got} notes, matched={matched}, F1={f1:.4f}, max_on_diff={max_on*1000:.2f} ms")
        assert f1 >= 0.95, f"Expected F1 >= 0.95, got {f1:.4f}\nref={ref_notes}\ngot={got_notes}"
    print("Tuning, windowed transcription, note decode, and MIDI output passed!")


if __name__ == "__main__":
    main()
