"""Embed the four packed FP16 Dettato weight archives into a Cosmopolitan APE binary.

Usage:
  python mp3tomidi/embed_weights.py build/mp3tomidi build/weights build/mp3tomidi-standalone
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import zipfile

MODELS = [
    ("transcriber_f16.vtwt", "weights/transcriber.vtwt"),
    ("evidence_f16.vtwt",    "weights/evidence.vtwt"),
    ("grouper_f16.vtwt",     "weights/grouper.vtwt"),
    ("drums_f16.vtwt",       "weights/drums.vtwt"),
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("base_ape", type=Path, help="Compiled Cosmopolitan APE binary without weights")
    p.add_argument("weights_dir", type=Path, help="Directory holding *_f16.vtwt archives")
    p.add_argument("out_ape", type=Path, help="Output self-contained APE binary")
    args = p.parse_args()

    for src_name, _ in MODELS:
        src = args.weights_dir / src_name
        if not src.is_file():
            raise FileNotFoundError(f"Missing weight archive: {src}")

    args.out_ape.parent.mkdir(parents=True, exist_ok=True)
    if args.base_ape.resolve() != args.out_ape.resolve():
        shutil.copy2(args.base_ape, args.out_ape)

    with zipfile.ZipFile(args.out_ape, "a", compression=zipfile.ZIP_STORED) as zf:
        existing = set(zf.namelist())
        for src_name, arc_name in MODELS:
            if arc_name in existing:
                raise RuntimeError(
                    f"{args.out_ape} already contains {arc_name}; copy from a fresh base APE instead."
                )
            zf.write(args.weights_dir / src_name, arcname=arc_name)

    print(f"Embedded {len(MODELS)} models into {args.out_ape} ({args.out_ape.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
