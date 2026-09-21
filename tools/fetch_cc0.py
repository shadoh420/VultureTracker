"""Download selected files from CC0 sample libraries on GitHub into tools/cc0/<library>/ (gitignored).

Only the files matching each library's patterns are fetched (the full libraries are several GB), plus the
library's LICENSE. Every library here is CC0 1.0 (public domain dedication); licenses were checked in each
repo's LICENSE file. Add patterns and rerun to fetch more; files already present are skipped.

    python tools/fetch_cc0.py            # fetch
    python tools/fetch_cc0.py --list     # show what would be fetched, with sizes
"""
import fnmatch
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "cc0"

LIBRARIES = {
    "vsco2": {
        "repo": "sgossner/VSCO-2-CE", "branch": "master", "license": "CC0-1.0",
        "credit": "VSCO 2: Community Edition, Versilian Studios / Sam Gossner, https://vis.versilstudios.com/vsco-community.html",
        "patterns": [
            "Strings/Cello Section/susvib/*", "Strings/Viola Section/susvib/*", "Strings/Violin Section/susVib/*",
            "Strings/Cello Section/pizzT/*_v2_RR1.wav", "Strings/Harp/*",
            "Woodwinds/Flute/susvib/*", "Brass/F Horn/*sus*",
            "Miscellania Raw/Misc 1/alien*", "Miscellania Raw/Misc 1/zap*", "Miscellania Raw/Misc 1/metal_hit*",
            "Miscellania Raw/Misc 1/ambience1.wav", "Miscellania Raw/Misc 1/chain_loop.wav",
            "Percussion/susCymb1-cresc-*", "Percussion/gongHit_*", "Percussion/Timpani/*",
            "Readme.txt",
        ],
    },
    "vcsl": {
        "repo": "sgossner/VCSL", "branch": "master", "license": "CC0-1.0",
        "credit": "Versilian Community Sample Library, Versilian Studios, https://github.com/sgossner/VCSL",
        "patterns": [
            "Idiophones/Struck Idiophones/Vibraphone/Bowed/*",
            "Idiophones/Friction Idiophones/Wine Glasses/*",
            "Idiophones/Plucked Idiophones/Kalimba, Kenya/*",
            "Idiophones/Struck Idiophones/Tubular Bells 1/*",
            "README.md",
        ],
    },
    "bigrusty": {
        "repo": "sfzinstruments/karoryfer.big-rusty-drums", "branch": "main", "license": "CC0-1.0",
        "credit": "Big Rusty Drums, Karoryfer Samples, https://shop.karoryfer.com/pages/free-samples",
        "patterns": [
            "Samples/kick_24/kick/*/k_vl1[0-9]_rr[12].flac",
            "Samples/snare_14/center/*/*_vl1[0-9]_rr[12].flac", "Samples/snare_14/rimshot/*",
            "Samples/snare_14/sidestick/*",
            "Samples/hihat_14/tc/cl/*", "Samples/hihat_14/cl/cl/*", "Samples/hihat_14/chik/cl/*",
            "Samples/hihat_14/ho/cl/*", "Samples/hihat_14/open/cl/*",
            "Samples/crash_17/cr/oh/*", "Samples/ride_22/rd/cl/*", "Samples/ride_22/bl/cl/*",
            "Samples/tom_18/center/cl/*", "Samples/tom_14/center/cl/*",
        ],
    },
}


def _get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "vulturetracker"})).read()


def plan(name, lib):
    tree = json.loads(_get(f"https://api.github.com/repos/{lib['repo']}/git/trees/{lib['branch']}?recursive=1"))
    if tree.get("truncated"):
        sys.exit(f"{name}: GitHub truncated the file list; fetch patterns by subfolder instead")
    blobs = {t["path"]: t["size"] for t in tree["tree"] if t["type"] == "blob"}
    files = ["LICENSE"] + sorted(p for p in blobs if any(fnmatch.fnmatchcase(p, pat) for pat in lib["patterns"]))
    for pat in lib["patterns"]:
        if not any(fnmatch.fnmatchcase(p, pat) for p in blobs):
            print(f"  warning: {name}: pattern matched nothing: {pat}")
    return [(p, blobs[p]) for p in files]


def main():
    list_only = "--list" in sys.argv
    for name, lib in LIBRARIES.items():
        files = plan(name, lib)
        print(f"{name}: {len(files)} files, {sum(s for _, s in files) / 1e6:.0f} MB  ({lib['repo']}, {lib['license']})")
        if list_only:
            continue
        base = OUT / name
        for path, size in files:
            dest = base / path
            if dest.exists() and dest.stat().st_size == size:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://raw.githubusercontent.com/{lib['repo']}/{lib['branch']}/{urllib.parse.quote(path)}"
            dest.write_bytes(_get(url))
        (base / "SOURCE.txt").write_text(
            f"{lib['credit']}\nrepository: https://github.com/{lib['repo']} ({lib['branch']})\n"
            f"license: {lib['license']} (see LICENSE)\n", encoding="utf-8")
    print(f"done: {OUT}" if not list_only else "")


if __name__ == "__main__":
    main()
