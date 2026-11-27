"""Verify native C Evidence Repairer against Python Dettato (Transcriber + EvidenceRepairer).

Usage:
  python mp3tomidi/check_evidence.py build/mp3tomidi build/weights --ffmpeg dist/ffmpeg.exe
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf
from safetensors.torch import load_file
import torch
from dettato.audio import Audio
from dettato.evidence.model import Repairer
from dettato.evidence.repair import EvidenceRepairer
from dettato.grouper import retune
from dettato.transcriber.core import Transcriber
from dettato.transcriber.model import LaneNet

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_transcribe import match_note_lists, synth_clip


def load_py_pipeline(weights_root: Path):
    tcfg = json.loads((weights_root / "dettato" / "config.json").read_text(encoding="utf-8"))
    tmodel = LaneNet(**tcfg["model"])
    tmodel.load_state_dict(load_file(str(weights_root / "dettato" / "model.safetensors")))
    tr = Transcriber(tmodel, tcfg["thresholds"], device="cpu")

    ecfg = json.loads((weights_root / "dettato-evidence" / "config.json").read_text(encoding="utf-8"))
    emodel = Repairer(**ecfg["model"])
    emodel.load_state_dict(load_file(str(weights_root / "dettato-evidence" / "model.safetensors")))
    rep = EvidenceRepairer(emodel, ecfg["keep_th"], ecfg["insert_th"], device="cpu")
    return tr, rep


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary", type=Path)
    p.add_argument("weights_dir", type=Path, help="Folder containing transcriber_f16.vtwt & evidence_f16.vtwt")
    p.add_argument("--ffmpeg", default="dist/ffmpeg.exe")
    p.add_argument("--dettato-root", type=Path, default=Path("tools/transcribe-env/dettato-weights"))
    args = p.parse_args()

    binary = str(args.binary.resolve())
    tr, repairer = load_py_pipeline(args.dettato_root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wdir = root / "w"
        wdir.mkdir()
        shutil.copy2(args.weights_dir / "transcriber_f16.vtwt", wdir / "transcriber.vtwt")
        shutil.copy2(args.weights_dir / "evidence_f16.vtwt", wdir / "evidence.vtwt")

        sig = synth_clip(44100, seconds=9.5, detune_cents=18.0)
        wav, mp3 = root / "song.wav", root / "song.mp3"
        sf.write(wav, np.column_stack([sig, sig * 0.92]), 44100)
        subprocess.run([args.ffmpeg, "-loglevel", "error", "-y", "-i", str(wav),
                        "-codec:a", "libmp3lame", str(mp3)], check=True)

        # Python reference: retune -> Transcriber.run -> EvidenceRepairer.from_run
        decoded, _ = sf.read(mp3, dtype="float32", always_2d=True)
        a16 = Audio(decoded.mean(axis=1), 44100).at(16000)
        _, _, shift, r = retune.ratio(a16)
        y = retune.resample(a16, r) if shift else a16
        maps, bufs = tr.run(y, hop_frac=0.25, batch=2, taps=("hidden",))
        rep, _, rinfo = repairer.from_run(tr, maps, bufs["hidden"])
        if r != 1.0:
            rep["onset"] = rep["onset"] * r
            rep["offset"] = rep["offset"] * r
        ref_notes = [(float(o), float(e), int(p)) for o, e, p in zip(rep["onset"], rep["offset"], rep["pitch"])]

        # Native C binary (--evidence-test)
        proc = subprocess.run(
            [binary, "--evidence-test", str(wdir), str(mp3)],
            executable=binary, capture_output=True, text=True, check=True,
        )
        got_json = json.loads(proc.stdout.strip())
        got_notes = [(n[0], n[1], int(n[2])) for n in got_json["notes"]]
        matched, n_ref, n_got, max_on = match_note_lists(ref_notes, got_notes, on_tol=0.02, off_tol=0.04)
        f1 = 2 * matched / max(1, n_ref + n_got)
        print(f"Python repairer info: {rinfo}")
        print(f"Native repairer info: {got_json['info']}")
        print(f"Matched {matched}/{n_ref} ref vs {n_got} got, F1={f1:.4f}, max_on_diff={max_on*1000:.2f} ms")
        assert f1 >= 0.95, f"Evidence repair parity too low: {f1:.4f}\nref={ref_notes}\ngot={got_notes}"
    print("Evidence Repairer parity passed!")


if __name__ == "__main__":
    main()
