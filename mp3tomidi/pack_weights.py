"""Pack a Dettato safetensors model into a VTWT binary weight archive.

Usage:
  python mp3tomidi/pack_weights.py INPUT.safetensors OUTPUT.vtwt [--fp16]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct

import numpy as np
from safetensors import safe_open

VTWT_NAME_MAX = 112
ENTRY_FMT = f"<{VTWT_NAME_MAX}sIIIIIIQQ"
ENTRY_SIZE = struct.calcsize(ENTRY_FMT)
assert ENTRY_SIZE == 152, ENTRY_SIZE


def align64(n: int) -> int:
    return (n + 63) & ~63


def pack(src: Path, dst: Path, fp16: bool) -> None:
    tensors: list[tuple[str, int, tuple[int, ...], bytes]] = []
    with safe_open(str(src), framework="numpy") as f:
        for name in sorted(f.keys()):
            if name.endswith(".num_batches_tracked"):
                continue
            arr = f.get_tensor(name)
            if arr.dtype == np.int64:
                continue
            arr = np.ascontiguousarray(arr, dtype=np.float32)
            name_b = name.encode("utf-8")
            if len(name_b) >= VTWT_NAME_MAX:
                raise ValueError(f"Tensor name too long ({len(name_b)} >= {VTWT_NAME_MAX}): {name}")
            if arr.ndim > 4:
                raise ValueError(f"Tensor {name} has ndim={arr.ndim} > 4")
            use_f16 = fp16 and arr.ndim >= 2 and arr.size >= 1024
            if use_f16:
                dtype_code = 1
                payload = np.ascontiguousarray(arr, dtype=np.float16).tobytes()
            else:
                dtype_code = 0
                payload = arr.tobytes()
            tensors.append((name, dtype_code, tuple(int(s) for s in arr.shape), payload))

    header_size = align64(16 + len(tensors) * ENTRY_SIZE)
    offset = header_size
    entries = []
    for name, dtype_code, shape, payload in tensors:
        s4 = list(shape) + [0] * (4 - len(shape))
        name_padded = name.encode("utf-8").ljust(VTWT_NAME_MAX, b"\x00")
        entries.append(struct.pack(
            ENTRY_FMT,
            name_padded, dtype_code, len(shape),
            s4[0], s4[1], s4[2], s4[3],
            offset, len(payload),
        ))
        offset = align64(offset + len(payload))

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as out:
        out.write(struct.pack("<4sIII", b"VTWT", 1, len(tensors), header_size))
        for ent in entries:
            out.write(ent)
        pos = 16 + len(tensors) * ENTRY_SIZE
        if pos < header_size:
            out.write(b"\x00" * (header_size - pos))
        for _, _, _, payload in tensors:
            out.write(payload)
            rem = align64(len(payload)) - len(payload)
            if rem:
                out.write(b"\x00" * rem)
    print(f"Packed {len(tensors)} tensors ({'fp16' if fp16 else 'fp32'}) -> {dst} ({dst.stat().st_size:,} bytes)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("src", type=Path)
    p.add_argument("dst", type=Path)
    p.add_argument("--fp16", action="store_true", help="Store large >=2D matrices in IEEE-754 float16")
    args = p.parse_args()
    pack(args.src, args.dst, args.fp16)


if __name__ == "__main__":
    main()
