"""Verify native C Instrument Grouper (full Dettato.pitched: retune + LaneNet + Evidence + Grouper)
against Python Dettato.

Usage:
  python mp3tomidi/check_grouper.py build/mp3tomidi build/weights --ffmpeg dist/ffmpeg.exe
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
from dettato.audio import Audio
from dettato.evidence.model import Repairer
from dettato.evidence.repair import EvidenceRepairer
from dettato.grouper.core import Grouper
from dettato.grouper.model import NoteNet
from dettato.pipeline import Dettato
from dettato.transcriber.core import Transcriber
from dettato.transcriber.model import LaneNet

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_transcribe import match_note_lists, synth_clip


def load_py_pitched(weights_root: Path) -> Dettato:
    tcfg = json.loads((weights_root / "dettato" / "config.json").read_text(encoding="utf-8"))
    tmodel = LaneNet(**tcfg["model"])
    tmodel.load_state_dict(load_file(str(weights_root / "dettato" / "model.safetensors")))
    tr = Transcriber(tmodel, tcfg["thresholds"], device="cpu")

    ecfg = json.loads((weights_root / "dettato-evidence" / "config.json").read_text(encoding="utf-8"))
    emodel = Repairer(**ecfg["model"])
    emodel.load_state_dict(load_file(str(weights_root / "dettato-evidence" / "model.safetensors")))
    rep = EvidenceRepairer(emodel, ecfg["keep_th"], ecfg["insert_th"], device="cpu")

    gcfg = json.loads((weights_root / "dettato-grouper" / "config.json").read_text(encoding="utf-8"))
    gmodel = NoteNet(**gcfg["model"])
    gmodel.load_state_dict(load_file(str(weights_root / "dettato-grouper" / "model.safetensors")))
    grp = Grouper(gmodel, gcfg, device="cpu")
    return Dettato(tr, rep, grp, None, "cpu")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary", type=Path)
    p.add_argument("weights_dir", type=Path)
    p.add_argument("--ffmpeg", default="dist/ffmpeg.exe")
    p.add_argument("--dettato-root", type=Path, default=Path("tools/transcribe-env/dettato-weights"))
    args = p.parse_args()

    binary = str(args.binary.resolve())
    det = load_py_pitched(args.dettato_root)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wdir = root / "w"
        wdir.mkdir()
        shutil.copy2(args.weights_dir / "transcriber_f16.vtwt", wdir / "transcriber.vtwt")
        shutil.copy2(args.weights_dir / "evidence_f16.vtwt", wdir / "evidence.vtwt")
        shutil.copy2(args.weights_dir / "grouper_f16.vtwt", wdir / "grouper.vtwt")

        sig = synth_clip(44100, seconds=9.5, detune_cents=0.0)
        wav, mp3 = root / "song.wav", root / "song.mp3"
        sf.write(wav, np.column_stack([sig, sig * 0.95]), 44100)
        subprocess.run([args.ffmpeg, "-loglevel", "error", "-y", "-i", str(wav),
                        "-codec:a", "libmp3lame", str(mp3)], check=True)

        decoded, _ = sf.read(mp3, dtype="float32", always_2d=True)
        a16 = Audio(decoded.mean(axis=1), 44100).at(16000)
        _, _, _, py_groups, py_ginfo = det.pitched(a16)

        proc = subprocess.run(
            [binary, "--grouper-test", str(wdir), str(mp3)],
            executable=binary, capture_output=True, text=True, check=True,
        )
        got = json.loads(proc.stdout.strip())
        py_summary = [(g["instrument"], int(g["program"]), len(g["notes"])) for g in py_groups]
        c_summary = [(t["instrument"], int(t["program"]), len(t["notes"])) for t in got["tracks"]]
        print("Python tracks:", py_summary)
        print("Native tracks:", c_summary)
        assert py_summary == c_summary, (py_summary, c_summary)

        for pg, cg in zip(py_groups, got["tracks"]):
            ref_n = [(float(r[0]), float(r[1]), int(r[2])) for r in pg["notes"]]
            got_n = [(float(r[0]), float(r[1]), int(r[2])) for r in cg["notes"]]
            m, nr, ng, mx = match_note_lists(ref_n, got_n, on_tol=0.02, off_tol=0.04)
            f1 = 2 * m / max(1, nr + ng)
            print(f"  Track {pg['instrument']}: matched {m}/{nr} (F1={f1:.4f}, max_on={mx*1000:.2f} ms)")
            assert f1 >= 0.95
    print("Full pitched pipeline (transcriber + evidence + grouper) parity passed!")


if __name__ == "__main__":
    main()
