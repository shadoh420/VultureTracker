"""End-to-end verification of mp3tomidi --mode enhanced (and --mode parity preservation)
on Windows and Linux WSL using a committed demo WAV excerpt (demo4/vantage.wav).

Usage:
  python mp3tomidi/check_enhanced.py build/mp3tomidi --wav demo4/vantage.wav --ffmpeg dist/ffmpeg.exe
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import mido
import pretty_midi
import soundfile as sf


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary", type=Path, help="Self-contained Cosmopolitan APE")
    p.add_argument("--wav", type=Path, default=Path("demo4/vantage.wav"))
    p.add_argument("--start-s", type=float, default=12.0)
    p.add_argument("--seconds", type=float, default=12.0)
    p.add_argument("--ffmpeg", default="dist/ffmpeg.exe")
    p.add_argument("--skip-wsl", action="store_true")
    args = p.parse_args()

    binary = str(args.binary.resolve())
    data, sr = sf.read(str(args.wav), dtype="float32", always_2d=True)
    i0 = int(round(args.start_s * sr))
    i1 = min(len(data), i0 + int(round(args.seconds * sr)))
    clip = data[i0:i1]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wav = root / "clip.wav"
        mp3 = root / "clip.mp3"
        mid_def = root / "clip-default.mid"
        mid_par = root / "clip-parity.mid"
        mid_enh = root / "clip-enhanced.mid"
        mid_em = root / "clip-enhance-midi.mid"
        sf.write(wav, clip, sr)
        subprocess.run(
            [args.ffmpeg, "-loglevel", "error", "-y", "-i", str(wav),
             "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3)],
            check=True,
        )

        # 1. Default and explicit --mode parity must be byte-identical
        r_def = subprocess.run([binary, str(mp3), "-o", str(mid_def)],
                               executable=binary, cwd=str(root), capture_output=True, text=True, check=True)
        r_par = subprocess.run([binary, str(mp3), "--mode", "parity", "-o", str(mid_par)],
                               executable=binary, cwd=str(root), capture_output=True, text=True, check=True)
        assert mid_def.read_bytes() == mid_par.read_bytes(), "Default and --mode parity differed!"
        print("Default vs --mode parity: BYTE-IDENTICAL", r_def.stdout.strip())

        # 2. Full standalone --mode enhanced (zero external files)
        r_enh = subprocess.run([binary, str(mp3), "--mode", "enhanced", "-o", str(mid_enh)],
                               executable=binary, cwd=str(root), capture_output=True, text=True, check=True)
        enh_meta = json.loads(r_enh.stdout.strip())
        print("Standalone --mode enhanced:", json.dumps(enh_meta))
        assert enh_meta["mode"] == "enhanced"
        assert enh_meta["cc_events"] > 0, "Expected CC7/CC11/CC74 events in enhanced MIDI"
        assert 50.0 <= enh_meta["bpm"] <= 220.0

        # Verify valid SMF with real tempo, CC7/CC11/CC74, and unique track names
        mm = mido.MidiFile(str(mid_enh))
        ccs_seen = {msg.control for tr in mm.tracks for msg in tr if msg.type == "control_change"}
        assert {7, 11, 74}.issubset(ccs_seen), f"Missing expected CCs: {ccs_seen}"
        pm = pretty_midi.PrettyMIDI(str(mid_enh))
        names = [ins.name for ins in pm.instruments]
        assert len(names) == len(set(names)), f"Duplicate track names: {names}"
        print(f"Enhanced MIDI verified: tempo={pm.get_tempo_changes()[1][0]:.2f} BPM, CCs={sorted(ccs_seen)}, tracks={names}")

        # 3. --enhance-midi on parity MIDI matches standalone --mode enhanced closely
        r_em = subprocess.run([binary, "--enhance-midi", str(mp3), str(mid_par), "-o", str(mid_em)],
                              executable=binary, cwd=str(root), capture_output=True, text=True, check=True)
        em_meta = json.loads(r_em.stdout.strip())
        print("--enhance-midi summary:", json.dumps({k: em_meta[k] for k in ("bpm", "notes", "drums", "cc_events")}))
        assert abs(em_meta["bpm"] - enh_meta["bpm"]) < 0.5, f"BPM diverged: {em_meta['bpm']} vs {enh_meta['bpm']}"
        assert em_meta["notes"] == enh_meta["notes"]
        assert em_meta["drums"] == enh_meta["drums"]

        # 4. Windows vs WSL Linux byte-identity for --mode enhanced
        if not args.skip_wsl:
            wsl_mp3 = Path("build/_enh_wsl.mp3")
            wsl_mid = Path("build/_enh_wsl.mid")
            try:
                wsl_mp3.write_bytes(mp3.read_bytes())
                rel_bin = args.binary.as_posix()
                subprocess.run(
                    ["wsl", "-d", "docker-desktop", "--exec", "/bin/sh",
                     rel_bin, "build/_enh_wsl.mp3", "--mode", "enhanced", "-o", "build/_enh_wsl.mid"],
                    capture_output=True, text=True, check=True,
                )
                b_win = mid_enh.read_bytes()
                b_wsl = wsl_mid.read_bytes()
                print(f"WIN enhanced MIDI: {len(b_win)} bytes sha256={hashlib.sha256(b_win).hexdigest()[:16]}")
                print(f"WSL enhanced MIDI: {len(b_wsl)} bytes sha256={hashlib.sha256(b_wsl).hexdigest()[:16]}")
                assert b_win == b_wsl, "WIN and WSL enhanced MIDI files differed!"
                print("WIN vs WSL enhanced MIDI: BYTE-IDENTICAL!")
            finally:
                wsl_mp3.unlink(missing_ok=True)
                wsl_mid.unlink(missing_ok=True)

    print("Enhanced mode end-to-end verification passed!")


if __name__ == "__main__":
    main()
