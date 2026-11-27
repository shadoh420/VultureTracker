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


def verify_output(ind_bin: str, rel_ind: str, audio_path: Path, mid_path: Path,
                  cwd: Path, label: str, skip_wsl: bool) -> None:
    r_ind = subprocess.run(
        [ind_bin, str(audio_path), "-o", str(mid_path)],
        executable=ind_bin, cwd=str(cwd), capture_output=True, text=True, check=True,
    )
    ind_meta = json.loads(r_ind.stdout.strip())
    print(f"Standalone mp3tomidi-independent [{label}]:", json.dumps(ind_meta))
    assert ind_meta["mode"] == "independent"
    assert ind_meta["notes"] > 20, f"Too few pitched notes: {ind_meta['notes']}"
    assert ind_meta["drums"] > 20, f"Too few drum hits: {ind_meta['drums']}"
    assert ind_meta["cc_events"] > 0
    assert 50.0 <= ind_meta["bpm"] <= 220.0

    mm = mido.MidiFile(str(mid_path))
    ccs_seen = {msg.control for tr in mm.tracks for msg in tr if msg.type == "control_change"}
    assert {7, 11, 74}.issubset(ccs_seen), f"Missing CCs in independent MIDI: {ccs_seen}"
    pm = pretty_midi.PrettyMIDI(str(mid_path))
    names = [ins.name for ins in pm.instruments]
    assert len(names) == len(set(names)), f"Duplicate track names: {names}"
    has_bass = any((not ins.is_drum) and any(n.pitch <= 36 for n in ins.notes) for ins in pm.instruments)
    assert has_bass, "Expected independent DSP transcriber to catch low sub-bass on demo4/vantage"
    print(f"Independent MIDI [{label}] verified: tempo={pm.get_tempo_changes()[1][0]:.2f} BPM, CCs={sorted(ccs_seen)}, tracks={names}")

    if not skip_wsl:
        ext = audio_path.suffix or ".bin"
        wsl_in = Path(f"build/_ind_wsl_{label}{ext}")
        wsl_mid = Path(f"build/_ind_wsl_{label}.mid")
        try:
            wsl_in.write_bytes(audio_path.read_bytes())
            subprocess.run(
                ["wsl", "-d", "docker-desktop", "--exec", "/bin/sh",
                 rel_ind, wsl_in.as_posix(), "-o", wsl_mid.as_posix()],
                capture_output=True, text=True, check=True,
            )
            b_win = mid_path.read_bytes()
            b_wsl = wsl_mid.read_bytes()
            print(f"WIN [{label}] MIDI: {len(b_win)} bytes sha256={hashlib.sha256(b_win).hexdigest()[:16]}")
            print(f"WSL [{label}] MIDI: {len(b_wsl)} bytes sha256={hashlib.sha256(b_wsl).hexdigest()[:16]}")
            assert b_win == b_wsl, f"WIN and WSL [{label}] independent MIDI files differed!"
            print(f"WIN vs WSL [{label}] MIDI: BYTE-IDENTICAL!")
        finally:
            wsl_in.unlink(missing_ok=True)
            wsl_mid.unlink(missing_ok=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ind_binary", type=Path, help="Standalone zero-dependency Cosmopolitan APE")
    p.add_argument("--wav", type=Path, default=Path("demo4/vantage.wav"))
    p.add_argument("--start-s", type=float, default=12.0)
    p.add_argument("--seconds", type=float, default=12.0)
    p.add_argument("--ffmpeg", default="", help="Optional ffmpeg path to also test MP3 encoding/decoding")
    p.add_argument("--skip-wsl", action="store_true")
    args = p.parse_args()

    ind_bin = str(args.ind_binary.resolve())
    rel_ind = args.ind_binary.as_posix()
    data, sr = sf.read(str(args.wav), dtype="float32", always_2d=True)
    i0 = int(round(args.start_s * sr))
    i1 = min(len(data), i0 + int(round(args.seconds * sr)))
    clip = data[i0:i1]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        wav = root / "clip.wav"
        sf.write(wav, clip, sr)

        # 1. Native WAV input (zero ffmpeg required!)
        verify_output(ind_bin, rel_ind, wav, root / "clip-wav.mid", root, "wav", args.skip_wsl)

        # 2. Optional MP3 input when --ffmpeg is provided (or dist/ffmpeg.exe exists)
        ffmpeg = args.ffmpeg or ("dist/ffmpeg.exe" if Path("dist/ffmpeg.exe").is_file() else "")
        if ffmpeg:
            mp3 = root / "clip.mp3"
            subprocess.run(
                [ffmpeg, "-loglevel", "error", "-y", "-i", str(wav),
                 "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3)],
                check=True,
            )
            verify_output(ind_bin, rel_ind, mp3, root / "clip-mp3.mid", root, "mp3", args.skip_wsl)

    print("Independent zero-dependency APE verification passed!")


if __name__ == "__main__":
    main()
