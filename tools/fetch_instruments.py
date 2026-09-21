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

    python tools/fetch_instruments.py [--install-obxd]
"""
import io
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
DEXED = "https://github.com/asb2m10/dexed/releases/download/v1.0.1/Dexed-1.0.1-win.zip"
OBXD = "https://github.com/reales/OB-Xd/releases/download/v2.20/Obxd220.exe"
DRUMS = "https://cdn.mos.musicradar.com/audio/musicradar-hardware-drum-machine-samples.zip"


def get(url):
    print(f"downloading {url}...")
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "vulturetracker"})).read()


def main():
    if sys.platform != "win32":
        print("Dexed and OB-Xd: install them normally and set DEXED_VST3 / OBXD_VST3 to the .vst3 bundles.")
    elif not (TOOLS / "synths" / "dexed" / "Dexed.vst3").exists():
        zipfile.ZipFile(io.BytesIO(get(DEXED))).extractall(TOOLS / "synths" / "dexed")
    if sys.platform == "win32" and "--install-obxd" in sys.argv:
        exe = TOOLS / "synths" / "Obxd220.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(get(OBXD))
        subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True)
    elif sys.platform == "win32":
        print(f"OB-Xd: install from {OBXD} (or rerun with --install-obxd)")
    out = TOOLS / "royalty-free" / "musicradar-drum-machines"
    if not out.exists():
        zipfile.ZipFile(io.BytesIO(get(DRUMS))).extractall(out)
        print("MusicRadar samples: royalty-free for your music; do not redistribute them.")
    print("done")


if __name__ == "__main__":
    main()
