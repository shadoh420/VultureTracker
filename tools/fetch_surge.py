"""Download the portable Windows build of Surge XT (GPL-3, https://surge-synthesizer.github.io) into
tools/surge-xt/. Nothing is installed system-wide. On macOS/Linux, install Surge XT normally and set
SURGE_XT_DIR to the folder containing 'Surge XT.vst3' and 'SurgeXTData'.

The URL and its SHA-256 are pinned in vulturetracker.synth.FETCH (the app's RECIPE box downloads the same file);
the download is verified against the digest before it is unpacked."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vulturetracker.synth import FETCH, fetch_synth  # noqa: E402

URL, SHA256, OUT = FETCH["surge"]


def main():
    if sys.platform != "win32":
        sys.exit("The portable build is Windows-only; install Surge XT and set SURGE_XT_DIR instead.")
    print(f"downloading {URL} (~300 MB)...")
    fetch_synth("surge")
    print(f"extracted to {OUT}")


if __name__ == "__main__":
    main()
