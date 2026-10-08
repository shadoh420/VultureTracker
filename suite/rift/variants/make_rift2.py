"""Rift 2: the owner's round-2 pick as a working song, with the riff's voice open in the tryout.

- The song: rift_v2_seq_riff (round 1's v2 layer set with the from-scratch low riff in the sequence section), with the
  intro shortened (the owner: "the intro seems to go on a bit too long ... we matched the song length to Nether a bit
  too closely"): v2's first ten orders (intro 4, build 6) become six (intro 2, build 4); the rest as it is. Written to
  suite/rift/rift2.yaml (rift.yaml, rift_loop.yaml and the generators stay untouched). From here rift2.yaml is the
  source of truth: the tryout's U writes into it.
- The riff's voice (slot 8): the calliope the song has, plus five candidates from riffkit.yaml, each given a floor
  (-26 dB, shaped like the sound, as gen_floor.py does) and tuned to A-3, listed in suite/rift/rift2.tryout.json.
Run once after `python -m vulturetracker synth suite/rift/variants/riffkit.yaml` (the floor is added in place, so a
second run would add it twice): python suite/rift/variants/make_rift2.py [--build]
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
RIFT = HERE.parent
ROOT = RIFT.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "suite" / "nadir"))
sys.path.insert(0, str(RIFT))
import make_variants as mv  # noqa: E402

CAND = ROOT / "samples/local/rift-variants/riff"
NAMES = ["riff_helmeto", "riff_rhodes", "riff_ebass", "riff_fingered", "riff_rubber"]
DROP = {1, 3, 5, 8}          # a repeat of intro_1, of intro_2, build_2, the repeat of build_3


def candidates():
    from gen_floor import add_floor
    from gen_cand import tune
    for n in NAMES:
        p = CAND / f"{n}.wav"
        add_floor(p, -26)
        tune(p, 110.0, (0.02 * 165 / 60, 0.3 * 165 / 60), harmonics=3)   # the strongest of partials 1-3 near A-3


def song():
    src = yaml.safe_load((HERE / "rift_v2_seq_riff.yaml").read_text(encoding="utf-8"))
    grids = [mv.parse(src["patterns"][o]) for k, o in enumerate(src["orders"]) if k not in DROP]
    src["module"]["title"] = "Rift 2"
    for v in src["samples"].values():              # paths relative to suite/rift, where the song is written
        v["file"] = os.path.relpath((HERE / v["file"]).resolve(), RIFT).replace("\\", "/")
    header = "\n".join([
        "Rift 2 (working song, 2026-09-24): round 1's v2 (no tonal hit, noise, strings, vocal pad or second line; the",
        "bed through the intro, build and peak), the sequence section rewritten from scratch as a low syncopated riff",
        "(the owner's round-2 pick), the intro shortened to two orders and the build to four. Made by",
        "suite/rift/variants/make_rift2.py; from here this file is the source of truth (the tryout writes here)."])
    old, mv.HERE = mv.HERE, RIFT                   # mv.write writes to mv.HERE and keeps paths relative to suite/rift
    try:
        npat, nord = mv.write("rift2", src, grids, header)
    finally:
        mv.HERE = old
    print(f"rift2.yaml: {nord} orders, {npat} patterns")


def tryout():
    p = RIFT / "rift2.tryout.json"
    if p.exists():
        print("rift2.tryout.json exists: left as it is")
        return
    cur = str((ROOT / "samples/local/rift-cand/seq_calliope.wav").resolve())
    meta = {"slot": 8, "orders": None, "candidates": {"8": [cur] + [str((CAND / f"{n}.wav").resolve()) for n in NAMES]},
            "ratings": {}, "muted": [], "solo": None, "mix": {}}
    p.write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
    print("rift2.tryout.json: slot 8 with", len(meta["candidates"]["8"]), "candidates")


if __name__ == "__main__":
    if "--song-only" not in sys.argv:
        candidates()
    song()
    tryout()
    if "--build" in sys.argv:
        ff = subprocess.run([sys.executable, "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                            capture_output=True, text=True).stdout.strip()
        y = RIFT / "rift2.yaml"
        subprocess.run([sys.executable, "-m", "vulturetracker", "build", str(y), "--render", str(y.with_suffix(".wav"))], cwd=ROOT, check=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(y.with_suffix(".wav")), "-b:a", "192k", str(y.with_suffix(".mp3"))], check=True)
