"""End-to-end verification of the single-file self-contained Cosmopolitan mp3tomidi APE
against full Python Dettato (transcriber + evidence repairer + grouper + drums) on a real
multi-instrument + drum audio clip, on both Windows and Linux WSL.

Usage:
  python mp3tomidi/check_e2e.py build/mp3tomidi-standalone --wav demo4/vantage.wav --ffmpeg dist/ffmpeg.exe
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import pretty_midi
import soundfile as sf
from safetensors.torch import load_file
from dettato.drums.infer import DrumTranscriber
from dettato.evidence.model import Repairer
from dettato.evidence.repair import EvidenceRepairer
from dettato.grouper.core import Grouper
from dettato.grouper.model import NoteNet
from dettato.pipeline import Dettato
from dettato.transcriber.core import Transcriber
from dettato.transcriber.model import LaneNet


def load_full_py_dettato(root: Path) -> Dettato:
    tcfg = json.loads((root / "dettato" / "config.json").read_text(encoding="utf-8"))
    tmodel = LaneNet(**tcfg["model"])
    tmodel.load_state_dict(load_file(str(root / "dettato" / "model.safetensors")))
    tr = Transcriber(tmodel, tcfg["thresholds"], device="cpu")

    ecfg = json.loads((root / "dettato-evidence" / "config.json").read_text(encoding="utf-8"))
    emodel = Repairer(**ecfg["model"])
    emodel.load_state_dict(load_file(str(root / "dettato-evidence" / "model.safetensors")))
    rep = EvidenceRepairer(emodel, ecfg["keep_th"], ecfg["insert_th"], device="cpu")

    gcfg = json.loads((root / "dettato-grouper" / "config.json").read_text(encoding="utf-8"))
    gmodel = NoteNet(**gcfg["model"])
    gmodel.load_state_dict(load_file(str(root / "dettato-grouper" / "model.safetensors")))
    grp = Grouper(gmodel, gcfg, device="cpu")

    dcfg = json.loads((root / "dettato-drums" / "config.json").read_text(encoding="utf-8"))
    drm = DrumTranscriber(dcfg, load_file(str(root / "dettato-drums" / "model.safetensors")), device="cpu")
    return Dettato(tr, rep, grp, drm, "cpu")


def match_events(ref, got, on_tol: float = 0.03):
    used = [False] * len(got)
    matched = 0
    for ron, rp in ref:
        best_j, best_e = -1, 1e9
        for j, (gon, gp) in enumerate(got):
            if not used[j] and gp == rp and abs(gon - ron) <= on_tol and abs(gon - ron) < best_e:
                best_j, best_e = j, abs(gon - ron)
        if best_j >= 0:
            used[best_j] = True
            matched += 1
    f1 = 2 * matched / max(1, len(ref) + len(got))
    return matched, len(ref), len(got), f1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary", type=Path, help="Self-contained Cosmopolitan APE (with embedded weights)")
    p.add_argument("--wav", type=Path, default=Path("demo4/vantage.wav"))
    p.add_argument("--start-s", type=float, default=12.0)
    p.add_argument("--seconds", type=float, default=12.0)
    p.add_argument("--ffmpeg", default="dist/ffmpeg.exe")
    p.add_argument("--dettato-root", type=Path, default=Path("tools/transcribe-env/dettato-weights"))
    p.add_argument("--skip-wsl", action="store_true")
    args = p.parse_args()

    binary = str(args.binary.resolve())
    det = load_full_py_dettato(args.dettato_root)

    # Read a real clip excerpt (no private audio, committed demo WAV)
    data, sr = sf.read(str(args.wav), dtype="float32", always_2d=True)
    i0 = int(round(args.start_s * sr))
    i1 = min(len(data), i0 + int(round(args.seconds * sr)))
    clip = data[i0:i1]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wav = root / "clip.wav"
        mp3 = root / "clip.mp3"
        mid_win = root / "clip-win.midi"
        sf.write(wav, clip, sr)
        subprocess.run([args.ffmpeg, "-loglevel", "error", "-y", "-i", str(wav),
                        "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True)

        # 1. Python full Dettato reference
        py_res = det.transcribe(str(mp3))
        print("Python Dettato summary:", json.dumps(py_res.summary()))

        # 2. Standalone C APE with ZERO extra flags / ZERO external weights!
        # Run from tmp cwd to prove zero dependency on repo files!
        proc = subprocess.run(
            [binary, str(mp3), "-o", str(mid_win)],
            executable=binary, cwd=str(root),
            capture_output=True, text=True, check=True,
        )
        print("Native APE stdout:", proc.stdout.strip())
        pm = pretty_midi.PrettyMIDI(str(mid_win))
        got_summary = [
            {"name": ins.name, "program": None if ins.is_drum else ins.program,
             "is_drum": ins.is_drum, "notes": len(ins.notes)}
            for ins in pm.instruments
        ]
        print("Native MIDI tracks:", got_summary)

        # Compare all pitched notes combined & all drum hits
        py_pitched = [(float(n[0]), int(n[2])) for t in py_res.tracks if not t.is_drum for n in t.notes]
        c_pitched = [(n.start, n.pitch) for ins in pm.instruments if not ins.is_drum for n in ins.notes]
        mp, rp, gp, f1_p = match_events(py_pitched, c_pitched, on_tol=0.03)
        print(f"Pitched events: matched={mp}/{rp} ref vs {gp} got, F1={f1_p:.4f}")
        assert f1_p >= 0.90, f"Pitched F1 {f1_p:.4f} < 0.90"

        py_drums = [(float(n[0]), int(n[2])) for t in py_res.tracks if t.is_drum for n in t.notes]
        c_drums = [(n.start, n.pitch) for ins in pm.instruments if ins.is_drum for n in ins.notes]
        md, rd, gd, f1_d = match_events(py_drums, c_drums, on_tol=0.025)
        print(f"Drum events:    matched={md}/{rd} ref vs {gd} got, F1={f1_d:.4f}")
        assert f1_d >= 0.90, f"Drum F1 {f1_d:.4f} < 0.90"

        # 3. Verify Windows vs WSL Linux byte-identical MIDI output!
        if not args.skip_wsl:
            # Copy clip.mp3 into build/ briefly so WSL can see it under workspace path
            wsl_mp3 = Path("build/_e2e_wsl.mp3")
            wsl_mid = Path("build/_e2e_wsl.midi")
            try:
                wsl_mp3.write_bytes(mp3.read_bytes())
                rel_bin = args.binary.as_posix()
                subprocess.run(
                    ["wsl", "-d", "docker-desktop", "--exec", "/bin/sh",
                     rel_bin, "build/_e2e_wsl.mp3", "-o", "build/_e2e_wsl.midi"],
                    capture_output=True, text=True, check=True,
                )
                b_win = mid_win.read_bytes()
                b_wsl = wsl_mid.read_bytes()
                print(f"WIN MIDI: {len(b_win)} bytes sha256={hashlib.sha256(b_win).hexdigest()[:16]}")
                print(f"WSL MIDI: {len(b_wsl)} bytes sha256={hashlib.sha256(b_wsl).hexdigest()[:16]}")
                assert b_win == b_wsl, "WIN and WSL MIDI files differed!"
                print("WIN vs WSL MIDI output: BYTE-IDENTICAL!")
            finally:
                wsl_mp3.unlink(missing_ok=True)
                wsl_mid.unlink(missing_ok=True)

    print("End-to-end single-file APE verification passed!")


if __name__ == "__main__":
    main()
