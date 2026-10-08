"""Fetch the free instruments that `vulturetracker synth` can use besides Surge XT (tools/fetch_surge.py):

- Dexed 1.0.1, a Yamaha DX7 emulation (GPL-3), into tools/synths/dexed/. Its bundled cartridges (Dexed_01 and
  SynprezFM) are written to %APPDATA%/DigitalSuburban/Dexed/Cartridges the first time the plugin loads.
- OB-Xd 2.20, an Oberheim OB-X emulation (free), whose Windows release is only an installer. With --install-obxd
  it is downloaded and run silently: the VST3 goes to Common Files\\VST3 and the preset banks to
  Documents\\discoDSP\\OB-Xd\\Banks. Without the flag, the URL is printed so you can install it yourself.
- MusicRadar's "hardware drum machine samples" (Roland TR-8, Alesis HR-16, Jomox, Nord Drum, DrumBrute) into
  tools/royalty-free/. Terms: royalty-free for use in your music, but the samples must not be redistributed,
  so this folder and anything rendered from it (samples/local/) are gitignored. Built modules (.it) embed
  their samples, so don't publish modules that use them either.

Every download is verified against the SHA-256 pinned beside its URL (Dexed's in vulturetracker.synth.FETCH, the
others here) before it is unpacked or run. To bump a version, download the new asset, hash it (certutil -hashfile /
sha256sum) and update the digest with the URL; MusicRadar's zip is unversioned, so its digest may need refreshing when
they republish it.

    python tools/fetch_instruments.py [--install-obxd]
"""
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))
from vulturetracker.fileio import fetch_verified  # noqa: E402
from vulturetracker.synth import fetch_synth  # noqa: E402

OBXD = "https://github.com/reales/OB-Xd/releases/download/v2.20/Obxd220.exe"
OBXD_SHA256 = "ec90fb619d6a18682ad6c60ee0b409477061c61edb422afdde1aed517d1a9c20"
DRUMS = "https://cdn.mos.musicradar.com/audio/musicradar-hardware-drum-machine-samples.zip"
DRUMS_SHA256 = "745b5081a7ec46852e8eef99f891857b66660ec557367397e15fe16f9c9dd4b9"  # as published 2026-10-08


def get(url, sha256, dest):
    print(f"downloading {url}...")
    return fetch_verified(url, sha256, dest)


def main():
    if sys.platform != "win32":
        print("Dexed and OB-Xd: install them normally and set DEXED_VST3 / OBXD_VST3 to the .vst3 bundles.")
    elif not (TOOLS / "synths" / "dexed" / "Dexed.vst3").exists():
        print("downloading Dexed...")
        fetch_synth("dexed")
    if sys.platform == "win32" and "--install-obxd" in sys.argv:
        exe = TOOLS / "synths" / "Obxd220.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        get(OBXD, OBXD_SHA256, exe)
        subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True)
    elif sys.platform == "win32":
        print(f"OB-Xd: install from {OBXD} (or rerun with --install-obxd)")
    out = TOOLS / "royalty-free" / "musicradar-drum-machines"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
            with zipfile.ZipFile(get(DRUMS, DRUMS_SHA256, Path(tmp) / "drums.zip")) as zf:
                zf.extractall(Path(tmp) / "x")
            (Path(tmp) / "x").rename(out)
        print("MusicRadar samples: royalty-free for your music; do not redistribute them.")
    print("done")


if __name__ == "__main__":
    main()
