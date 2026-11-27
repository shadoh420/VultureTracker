"""Verify native C Drum Transcriber against Python Dettato (DrumTranscriber).

Usage:
  python mp3tomidi/check_drums.py build/mp3tomidi build/weights --ffmpeg dist/ffmpeg.exe
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
import soundfile as sf
from safetensors.torch import load_file
from dettato.audio import Audio
from dettato.drums.infer import DrumTranscriber


def synth_drum_clip(sr: int = 48000, seconds: float = 4.0) -> np.ndarray:
    """Synthesize clear kick + snare + hi-hat pattern at 48 kHz (exercises 48k->44.1k + drum kit)."""
    rng = np.random.default_rng(42)
    n = int(round(seconds * sr))
    x = np.zeros(n, dtype=np.float64)
    noise = rng.standard_normal(n)

    def add_kick(t0: float):
        i0 = int(round(t0 * sr))
        L = min(int(0.22 * sr), n - i0)
        if L <= 0:
            return
        t = np.arange(L) / sr
        f = 50.0 + 110.0 * np.exp(-t / 0.025)
        ph = 2 * np.pi * np.cumsum(f) / sr
        x[i0:i0 + L] += 0.85 * np.sin(ph) * np.exp(-t / 0.06)

    def add_snare(t0: float):
        i0 = int(round(t0 * sr))
        L = min(int(0.18 * sr), n - i0)
        if L <= 0:
            return
        t = np.arange(L) / sr
        body = 0.45 * np.sin(2 * np.pi * 190.0 * t) * np.exp(-t / 0.035)
        wire = 0.55 * noise[i0:i0 + L] * np.exp(-t / 0.055)
        x[i0:i0 + L] += body + wire

    def add_hat(t0: float):
        i0 = int(round(t0 * sr))
        L = min(int(0.06 * sr), n - i0)
        if L <= 0:
            return
        t = np.arange(L) / sr
        # Simple high-pass via first difference of white noise
        hp = np.diff(noise[i0:i0 + L + 1])
        x[i0:i0 + L] += 0.28 * hp * np.exp(-t / 0.015)

    for beat in range(8):
        tb = 0.25 + beat * 0.45
        if beat % 2 == 0:
            add_kick(tb)
        else:
            add_snare(tb)
        add_hat(tb)
        add_hat(tb + 0.225)
    peak = np.max(np.abs(x))
    if peak > 0.9:
        x *= 0.9 / peak
    return x.astype(np.float32)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary", type=Path)
    p.add_argument("weights_dir", type=Path)
    p.add_argument("--ffmpeg", default="dist/ffmpeg.exe")
    p.add_argument("--dettato-root", type=Path, default=Path("tools/transcribe-env/dettato-weights"))
    args = p.parse_args()

    binary = str(args.binary.resolve())
    cfg = json.loads((args.dettato_root / "dettato-drums" / "config.json").read_text(encoding="utf-8"))
    state = load_file(str(args.dettato_root / "dettato-drums" / "model.safetensors"))
    dt = DrumTranscriber(cfg, state, device="cpu")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wdir = root / "w"
        wdir.mkdir()
        shutil.copy2(args.weights_dir / "drums_f16.vtwt", wdir / "drums.vtwt")

        sig = synth_drum_clip(48000, seconds=4.0)
        wav, mp3 = root / "drums48.wav", root / "drums48.mp3"
        sf.write(wav, np.column_stack([sig, sig]), 48000)
        subprocess.run([args.ffmpeg, "-loglevel", "error", "-y", "-i", str(wav),
                        "-codec:a", "libmp3lame", str(mp3)], check=True)

        decoded, _ = sf.read(mp3, dtype="float32", always_2d=True)
        a44 = Audio(decoded.mean(axis=1), 48000).at(44100)
        py_hits = dt.transcribe(a44)
        py_info = dt.last_info

        proc = subprocess.run(
            [binary, "--drums-test", str(wdir), str(mp3)],
            executable=binary, capture_output=True, text=True, check=True,
        )
        got = json.loads(proc.stdout.strip())
        print(f"Python drums: router={py_info['router']:.4f} model={py_info['model']} hits={len(py_hits)}")
        print(f"Native drums: router={got['router']:.4f} model={got['model']} hits={len(got['hits'])}")
        assert abs(got["router"] - py_info["router"]) < 0.03, (got["router"], py_info["router"])
        assert got["model"] == py_info["model"]

        # Match hits within 20 ms (1 frame) on exact GM drum pitch
        used = [False] * len(got["hits"])
        matched = 0
        for h in py_hits:
            for j, g in enumerate(got["hits"]):
                if not used[j] and int(g[2]) == int(h["pitch"]) and abs(g[0] - h["onset"]) <= 0.021:
                    used[j] = True
                    matched += 1
                    break
        f1 = 2 * matched / max(1, len(py_hits) + len(got["hits"]))
        print(f"Matched {matched}/{len(py_hits)} ref vs {len(got['hits'])} got, F1={f1:.4f}")
        assert f1 >= 0.90, f"Drum parity too low: {f1:.4f}\npy={py_hits}\nc={got['hits']}"

        # Also verify low-sample-rate (16 kHz) skips drums cleanly
        sig16 = synth_drum_clip(16000, seconds=1.5)
        w16, m16 = root / "d16.wav", root / "d16.mp3"
        sf.write(w16, sig16, 16000)
        subprocess.run([args.ffmpeg, "-loglevel", "error", "-y", "-i", str(w16),
                        "-codec:a", "libmp3lame", str(m16)], check=True)
        got16 = json.loads(subprocess.run(
            [binary, "--drums-test", str(wdir), str(m16)],
            executable=binary, capture_output=True, text=True, check=True,
        ).stdout.strip())
        assert got16["hits"] == [] and got16["skipped"] is True
        print("16 kHz source drum skip verified.")
    print("Drum Transcriber parity passed!")


if __name__ == "__main__":
    main()
