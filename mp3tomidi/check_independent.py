"""End-to-end verification of the standalone zero-dependency Cosmopolitan APE
(build/mp3tomidi-independent) on Windows and Linux WSL using a committed demo WAV
excerpt (demo4/vantage.wav).

Usage:
  python mp3tomidi/check_independent.py build/mp3tomidi-independent [--wav demo4/vantage.wav]
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
    p.add_argument("ind_binary", type=Path, help="Standalone zero-dependency Cosmopolitan APE")
    p.add_argument("--wav", type=Path, default=Path("demo4/vantage.wav"))
    p.add_argument("--start-s", type=float, default=12.0)
    p.add_argument("--seconds", type=float, default=12.0)
    p.add_argument("--ffmpeg", default="dist/ffmpeg.exe")
    p.add_argument("--skip-wsl", action="store_true")
    args = p.parse_args()

    ind_bin = str(args.ind_binary.resolve())
    data, sr = sf.read(str(args.wav), dtype="float32", always_2d=True)
    i0 = int(round(args.start_s * sr))
    i1 = min(len(data), i0 + int(round(args.seconds * sr)))
    clip = data[i0:i1]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wav = root / "clip.wav"
        mp3 = root / "clip.mp3"
        mid_ind = root / "clip-ind.mid"
        sf.write(wav, clip, sr)
        subprocess.run(
            [args.ffmpeg, "-loglevel", "error", "-y", "-i", str(wav),
             "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3)],
            check=True,
        )

        # 1. Standalone binary run from isolated temp cwd (zero external files/weights)
        r_ind = subprocess.run(
            [ind_bin, str(mp3), "-o", str(mid_ind)],
            executable=ind_bin, cwd=str(root), capture_output=True, text=True, check=True,
        )
        ind_meta = json.loads(r_ind.stdout.strip())
        print("Standalone mp3tomidi-independent:", json.dumps(ind_meta))
        assert ind_meta["mode"] == "independent"
        assert ind_meta["notes"] > 20, f"Too few pitched notes: {ind_meta['notes']}"
        assert ind_meta["drums"] > 20, f"Too few drum hits: {ind_meta['drums']}"
        assert ind_meta["cc_events"] > 0
        assert 50.0 <= ind_meta["bpm"] <= 220.0

        mm = mido.MidiFile(str(mid_ind))
        ccs_seen = {msg.control for tr in mm.tracks for msg in tr if msg.type == "control_change"}
        assert {7, 11, 74}.issubset(ccs_seen), f"Missing CCs in independent MIDI: {ccs_seen}"
        pm = pretty_midi.PrettyMIDI(str(mid_ind))
        names = [ins.name for ins in pm.instruments]
        assert len(names) == len(set(names)), f"Duplicate track names: {names}"
        has_bass = any((not ins.is_drum) and any(n.pitch <= 36 for n in ins.notes) for ins in pm.instruments)
        assert has_bass, "Expected independent DSP transcriber to catch low sub-bass on demo4/vantage"
        print(f"Independent MIDI verified: tempo={pm.get_tempo_changes()[1][0]:.2f} BPM, CCs={sorted(ccs_seen)}, tracks={names}")

        # 2. Windows vs WSL Linux byte-identity
        if not args.skip_wsl:
            wsl_mp3 = Path("build/_ind_wsl.mp3")
            wsl_mid = Path("build/_ind_wsl.mid")
            try:
                wsl_mp3.write_bytes(mp3.read_bytes())
                rel_ind = args.ind_binary.as_posix()
                subprocess.run(
                    ["wsl", "-d", "docker-desktop", "--exec", "/bin/sh",
                     rel_ind, "build/_ind_wsl.mp3", "-o", "build/_ind_wsl.mid"],
                    capture_output=True, text=True, check=True,
                )
                b_win = mid_ind.read_bytes()
                b_wsl = wsl_mid.read_bytes()
                print(f"WIN independent MIDI: {len(b_win)} bytes sha256={hashlib.sha256(b_win).hexdigest()[:16]}")
                print(f"WSL independent MIDI: {len(b_wsl)} bytes sha256={hashlib.sha256(b_wsl).hexdigest()[:16]}")
                assert b_win == b_wsl, "WIN and WSL independent MIDI files differed!"
                print("WIN vs WSL independent MIDI: BYTE-IDENTICAL!")
            finally:
                wsl_mp3.unlink(missing_ok=True)
                wsl_mid.unlink(missing_ok=True)

    print("Independent zero-dependency APE verification passed!")


if __name__ == "__main__":
    main()
