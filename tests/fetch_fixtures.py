"""Download OpenMPT's IT playback test modules (mirrored in the libxmp repository) into tests/fixtures/.
They are third-party files used only for local round-trip testing and are not committed."""
import json
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "fixtures"
TREE = "https://api.github.com/repos/libxmp/libxmp/git/trees/master?recursive=1"
RAW = "https://raw.githubusercontent.com/libxmp/libxmp/master/"


def main():
    OUT.mkdir(exist_ok=True)
    tree = json.load(urllib.request.urlopen(TREE))["tree"]
    paths = [t["path"] for t in tree if t["path"].startswith("test-dev/openmpt/it/")
             and t["path"].endswith(".it") and t.get("size", 0) < 150_000]
    for p in paths:
        dest = OUT / Path(p).name
        if not dest.exists():
            urllib.request.urlretrieve(RAW + urllib.parse.quote(p), dest)
    print(f"{len(paths)} modules in {OUT}")


if __name__ == "__main__":
    main()
