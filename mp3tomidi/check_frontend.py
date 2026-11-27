"""Development check. Run with the Dettato environment; usage: --help."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import soundfile as sf
import torch
from dettato.audio import Audio
from dettato.transcriber.frontend import HCQT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg", help="fixture encoder")
    args = parser.parse_args()
    binary = str(args.binary.resolve())

    def cli(*arguments, check=True):
        return subprocess.run([binary, *arguments], executable=binary,
                              capture_output=True, check=check)

    torch.set_num_threads(1)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rate, channels in [(16000, 2), (44100, 1), (44100, 2), (48000, 2)]:
            t = np.arange(rate + 39) / rate
            # Smooth 20 ms fade on resampled fixtures avoids artificial step ringing in the 7.6-8 kHz stopband transition
            env = 1.0 if rate == 16000 else np.minimum(1.0, np.minimum(t / 0.02, (t[-1] - t) / 0.02))
            left = env * (0.32 * np.sin(2 * np.pi * (160*t + 290*t*t)))
            right = env * (0.23 * np.cos(2 * np.pi * 784*t) * (t > 0.3))
            if rate >= 44100:
                # Include 5.5 kHz in-band tone and 12 kHz above-Nyquist tone to verify passband + anti-aliasing
                left = left + env * (0.12 * np.sin(2 * np.pi * 5500*t) + 0.15 * np.sin(2 * np.pi * 12000*t))
            wav, mp3 = root / f"test_{rate}_{channels}.wav", root / f"test_{rate}_{channels}.mp3"
            sf.write(wav, np.column_stack([left, right]) if channels == 2 else left, rate)
            subprocess.run([args.ffmpeg, "-loglevel", "error", "-y", "-i", wav,
                            "-codec:a", "libmp3lame", str(mp3)], check=True)
            decoded, _ = sf.read(mp3, dtype="float32", always_2d=True)
            mono = decoded.mean(axis=1)
            report = json.loads(cli("--inspect", mp3).stdout)
            assert (report["rate"], report["channels"], report["frames"]) == (rate, channels, len(mono)), report
            np.testing.assert_allclose(report["mono_rms"], np.sqrt(np.mean(mono**2)), atol=2e-5)

            model_in = Audio(mono, rate).at(16000)[:8 * 16000]
            actual = np.frombuffer(cli("--features", mp3).stdout, "<f4").reshape(-1, 9, 288)
            expected = HCQT()(torch.from_numpy(model_in)[None])[0].permute(1, 0, 2).numpy()
            assert actual.shape == expected.shape, (actual.shape, expected.shape)
            diff = np.abs(actual - expected)
            max_err = float(diff.max())
            p999_err = float(np.percentile(diff, 99.9))
            mean_err = float(diff.mean())
            print(f"{rate} Hz {channels}ch -> {actual.shape}, max {max_err:.6g}, p99.9 {p999_err:.6g}, mean {mean_err:.6g}")
            if rate == 16000:
                np.testing.assert_allclose(actual, expected, rtol=0, atol=0.004)
            else:
                # Passband (h=1 & short-window channels, all <= 6.91 kHz) must match tightly;
                # only quiet transition-band harmonic bins (7.6-8 kHz) may see ~0.03 diff on transients.
                np.testing.assert_allclose(actual[:, [0, 1, 8], :], expected[:, [0, 1, 8], :], rtol=0, atol=0.005)
                assert p999_err < 0.003 and mean_err < 0.0003 and max_err < 0.04, (max_err, p999_err, mean_err)
        invalid = root / "invalid.mp3"
        invalid.write_bytes(b"this is not audio")
        bad_input = cli("--inspect", invalid, check=False)
        assert bad_input.returncode and b"MP3" in bad_input.stderr
        output = root / "sentinel.midi"
        output.write_bytes(b"existing work")
        failed_transcribe = cli(invalid, "-o", output, check=False)
        assert failed_transcribe.returncode != 0
        assert output.read_bytes() == b"existing work"
        bad_flags = cli("--bogus", mp3, check=False)
        assert bad_flags.returncode and b"Usage:" in bad_flags.stderr
    print("MP3 decode, resampling, features and error paths passed")


if __name__ == "__main__":
    main()
