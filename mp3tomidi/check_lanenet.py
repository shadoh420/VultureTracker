"""Compare native C LaneNet (stem, hidden, logits) against PyTorch Dettato.

Usage:
  python mp3tomidi/check_lanenet.py build/mp3tomidi build/weights/transcriber_f32.vtwt [--fp16-weights build/weights/transcriber_f16.vtwt] [--seconds 2.0]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from safetensors.torch import load_file
import torch
from dettato.transcriber.model import LaneNet


def make_test_signal(seconds: float, sr: int = 16000) -> np.ndarray:
    n = int(round(seconds * sr))
    t = np.arange(n, dtype=np.float64) / sr
    # Rich polyphonic chord + melody + harmonics to activate all lanes and attention heads
    x = np.zeros(n, dtype=np.float64)
    for f, amp, t0, t1 in [
        (220.0, 0.25, 0.05, seconds - 0.1),   # A3
        (277.18, 0.20, 0.20, seconds - 0.2),  # C#4
        (329.63, 0.22, 0.35, seconds - 0.15), # E4
        (440.0, 0.18, 0.60, seconds - 0.05),  # A4
        (659.25, 0.12, 0.90, seconds - 0.1),  # E5
        (110.0, 0.28, 0.10, seconds - 0.05),  # A2 bass
    ]:
        gate = ((t >= t0) & (t < t1)).astype(np.float64)
        env = np.exp(-1.5 * np.maximum(0.0, t - t0)) * gate
        for h in range(1, 5):
            x += (amp / h) * env * np.sin(2.0 * np.pi * f * h * t)
    return x.astype(np.float32)


def load_py_lanenet(weights_dir: Path) -> LaneNet:
    cfg = json.loads((weights_dir / "config.json").read_text(encoding="utf-8"))
    model = LaneNet(**cfg["model"])
    model.load_state_dict(load_file(str(weights_dir / "model.safetensors")))
    model.eval()
    return model


def compare_run(binary: str, weights_vtwt: Path, audio: np.ndarray,
                ref_stem: np.ndarray, ref_hidden: np.ndarray, ref_logits: np.ndarray,
                label: str, tol_logits: float, tol_prob: float) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f_in = root / "audio.f32"
        f_in.write_bytes(audio.tobytes())
        prefix = root / "out"
        proc = subprocess.run(
            [binary, "--lanenet-test", str(weights_vtwt), str(f_in), str(prefix)],
            executable=binary, capture_output=True, text=True, check=True,
        )
        info = json.loads(proc.stdout.strip())
        T = info["T"]
        got_logits = np.frombuffer((root / "out.logits.f32").read_bytes(), "<f4").reshape(T, 88, 6)
        got_stem = np.frombuffer((root / "out.stem.f32").read_bytes(), "<f4").reshape(T, 88, 368)
        got_hidden = np.frombuffer((root / "out.hidden.f32").read_bytes(), "<f4").reshape(T, 88, 368)

        d_stem = np.abs(got_stem - ref_stem)
        d_hid = np.abs(got_hidden - ref_hidden)
        d_log = np.abs(got_logits - ref_logits)
        p_got = 1.0 / (1.0 + np.exp(-got_logits))
        p_ref = 1.0 / (1.0 + np.exp(-ref_logits))
        d_prob = np.abs(p_got - p_ref)

        print(f"[{label}] T={T} threads={info['threads']} avx2_fma={info['avx2_fma']} "
              f"load={info['load_s']:.3f}s forward={info['forward_s']:.3f}s")
        print(f"  stem   max={d_stem.max():.5g} mean={d_stem.mean():.5g}")
        print(f"  hidden max={d_hid.max():.5g} mean={d_hid.mean():.5g}")
        print(f"  logits max={d_log.max():.5g} mean={d_log.mean():.5g}")
        print(f"  probs  max={d_prob.max():.5g} mean={d_prob.mean():.5g}")
        assert d_log.max() < tol_logits, f"{label} logits max err {d_log.max()} >= {tol_logits}"
        assert d_prob.max() < tol_prob, f"{label} probs max err {d_prob.max()} >= {tol_prob}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary", type=Path)
    p.add_argument("f32_weights", type=Path)
    p.add_argument("--fp16-weights", type=Path, default=None)
    p.add_argument("--dettato-dir", type=Path, default=Path("tools/transcribe-env/dettato-weights/dettato"))
    p.add_argument("--seconds", type=float, default=2.0)
    args = p.parse_args()

    binary = str(args.binary.resolve())
    audio = make_test_signal(args.seconds)
    model = load_py_lanenet(args.dettato_dir)
    taps: dict = {}
    with torch.no_grad():
        res = model(torch.from_numpy(audio)[None], taps=taps)
    # Convert PyTorch (1, C, T, P) -> (T, 88, C) and logits -> (T, 88, 6)
    ref_stem = taps["stem"][0, :, :, :88].permute(1, 2, 0).numpy()
    ref_hidden = taps["hidden"][0, :, :, :88].permute(1, 2, 0).numpy()
    heads = ("onset", "frame", "offset", "onset2", "frame2", "offset2")
    ref_logits = np.stack([res[h][0].numpy() for h in heads], axis=-1)

    compare_run(binary, args.f32_weights, audio, ref_stem, ref_hidden, ref_logits,
                f"FP32 {args.seconds:.1f}s", tol_logits=5e-3, tol_prob=5e-4)
    if args.fp16_weights:
        compare_run(binary, args.fp16_weights, audio, ref_stem, ref_hidden, ref_logits,
                    f"FP16 {args.seconds:.1f}s", tol_logits=0.1, tol_prob=1e-3)
    print("LaneNet tensor & logit parity passed!")


if __name__ == "__main__":
    main()
