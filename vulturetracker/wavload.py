"""WAV reader (stdlib only): PCM 8/16/24/32-bit, float 32/64, WAVE_FORMAT_EXTENSIBLE, any channel count.
Also reads loop points from a 'smpl' chunk if present."""
import struct
import sys
from array import array
from dataclasses import dataclass, field


@dataclass
class WavData:
    rate: int
    bits: int                          # source bit depth
    channels: list[list[int]]          # per channel, converted to signed 16-bit (or 8-bit if source was 8-bit)
    out_bits: int                      # 8 or 16
    loops: list[tuple[int, int, bool]] = field(default_factory=list)  # (start, end_exclusive, pingpong)
    root: int | None = None            # 'smpl' chunk unity note (MIDI, 60 = C-5), if present


class WavError(ValueError):
    pass


def read_wav(path) -> WavData:
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise WavError(f"{path}: not a RIFF/WAVE file")
    fmt = data = None
    loops = []
    root = None
    pos = 12
    while pos + 8 <= len(raw):
        cid, size = struct.unpack_from("<4sI", raw, pos)
        body = raw[pos + 8: pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            data = body
        elif cid == b"smpl" and len(body) >= 36:
            root = struct.unpack_from("<I", body, 12)[0]
            nloops = struct.unpack_from("<I", body, 28)[0]
            for i in range(nloops):
                off = 36 + 24 * i
                if off + 24 > len(body):
                    break
                _id, ltype, start, end, _frac, _count = struct.unpack_from("<6I", body, off)
                loops.append((start, end + 1, ltype == 1))  # smpl end is inclusive
        pos += 8 + size + (size & 1)
    if fmt is None or data is None:
        raise WavError(f"{path}: missing fmt or data chunk")
    if len(fmt) < 16:
        raise WavError(f"{path}: the fmt chunk is {len(fmt)} bytes; a WAV header needs 16")
    tag, nch, rate, _brate, align, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    if tag == 0xFFFE and len(fmt) >= 26:
        tag = struct.unpack_from("<H", fmt, 24)[0]  # sub-format GUID starts with the real tag
    if tag not in (1, 3):
        raise WavError(f"{path}: unsupported WAV encoding (format tag {tag}); save as PCM or float")
    if nch < 1 or align < nch or rate < 1:
        raise WavError(f"{path}: the fmt chunk gives {nch} channels, {align} bytes per frame and {rate} Hz")
    width = align // nch
    frames = len(data) // align
    data = data[: frames * align]

    if tag == 3:
        if width not in (4, 8):
            raise WavError(f"{path}: unsupported float width {width * 8}")
        a = array("f" if width == 4 else "d", data)
        if sys.byteorder == "big":
            a.byteswap()
        inter = [max(-32768, min(32767, round(x * 32767))) for x in a]
        out_bits = 16
    elif width == 1:
        inter = [b - 128 for b in data]  # WAV 8-bit is unsigned
        out_bits = 8
    elif width == 2:
        a = array("h", data)
        if sys.byteorder == "big":
            a.byteswap()
        inter = a.tolist()
        out_bits = 16
    elif width == 3:
        inter = [int.from_bytes(data[i + 1: i + 3], "little", signed=True) for i in range(0, len(data), 3)]
        out_bits = 16
    elif width == 4:
        a = array("i", data)
        if sys.byteorder == "big":
            a.byteswap()
        inter = [x >> 16 for x in a]
        out_bits = 16
    else:
        raise WavError(f"{path}: unsupported sample width {width * 8} bits")
    # ponytail: 24/32-bit sources are truncated to 16 bits (no dither); IT stores at most 16 bits anyway.
    channels = [inter[c::nch] for c in range(nch)]
    return WavData(rate, bits, channels, out_bits, loops, root)


def write_wav(path, rate, channels, bits=16, loop=None, root_note=None):
    """Write int channel lists as PCM WAV. `loop` = (start, end_exclusive, pingpong) and `root_note`
    (0..119, C-5 = 60 = MIDI middle C) are stored in a 'smpl' chunk that samplers and read_wav understand."""
    _write_pcm(path, rate, channels, bits)
    if loop is None and root_note is None:
        return
    loops = [loop] if loop else []
    body = struct.pack("<9I", 0, 0, round(1e9 / rate), root_note if root_note is not None else 60, 0, 0, 0, len(loops), 0)
    for i, (start, end, pingpong) in enumerate(loops):
        body += struct.pack("<6I", i, 1 if pingpong else 0, start, end - 1, 0, 0)  # smpl end is inclusive
    with open(path, "r+b") as f:
        f.seek(0, 2)
        f.write(b"smpl" + struct.pack("<I", len(body)) + body)
        size = f.tell()
        f.seek(4)
        f.write(struct.pack("<I", size - 8))


def _write_pcm(path, rate, channels, bits):
    import wave
    n = len(channels[0])
    inter = array("h" if bits == 16 else "B")
    for i in range(n):
        for ch in channels:
            inter.append(ch[i] if bits == 16 else ch[i] + 128)
    if bits == 16 and sys.byteorder == "big":
        inter.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(len(channels))
        w.setsampwidth(bits // 8)
        w.setframerate(rate)
        w.writeframes(inter.tobytes())
