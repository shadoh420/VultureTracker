"""Download the portable Windows build of Surge XT (GPL-3, https://surge-synthesizer.github.io) into
tools/surge-xt/. Nothing is installed system-wide. On macOS/Linux, install Surge XT normally and set
SURGE_XT_DIR to the folder containing 'Surge XT.vst3' and 'SurgeXTData'."""
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "1.3.4"
URL = (f"https://github.com/surge-synthesizer/releases-xt/releases/download/{VERSION}/"
       f"surge-xt-win64-{VERSION}-portable-install.zip")
OUT = Path(__file__).resolve().parent / "surge-xt"


def main():
    if sys.platform != "win32":
        sys.exit("The portable build is Windows-only; install Surge XT and set SURGE_XT_DIR instead.")
    print(f"downloading {URL} (~300 MB)...")
    data = urllib.request.urlopen(URL).read()
    zipfile.ZipFile(io.BytesIO(data)).extractall(OUT)
    print(f"extracted to {OUT}")


if __name__ == "__main__":
    main()
