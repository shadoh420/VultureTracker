"""WAV reader (stdlib only): PCM 8/16/24/32-bit, float 32/64, WAVE_FORMAT_EXTENSIBLE, any channel count.
Also reads loop points from a 'smpl' chunk if present. Other sound files become WAVs through ffmpeg (to_wav)."""
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
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
        if not all(map(math.isfinite, a)):
            raise WavError(f"{path}: the float samples hold NaN or infinite values")
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
    with open(path, "r+b") as f:
        data = add_smpl(f.read(), rate, loop, root_note)
        f.seek(0)
        f.write(data)


def add_smpl(wav, rate, loop=None, root_note=None, loops=None):
    """A RIFF WAV's bytes with a 'smpl' chunk appended: `loop` = (start, end_exclusive, pingpong), or several `loops`,
    `root_note` as in write_wav."""
    loops = loops if loops is not None else [loop] if loop else []
    body = struct.pack("<9I", 0, 0, round(1e9 / rate), root_note if root_note is not None else 60, 0, 0, 0, len(loops), 0)
    for i, (start, end, pingpong) in enumerate(loops):
        body += struct.pack("<6I", i, 1 if pingpong else 0, start, end - 1, 0, 0)  # smpl end is inclusive
    pad = b"\0" * (len(wav) % 2)  # RIFF chunks start on even offsets: an odd data chunk (8-bit, odd length) takes a pad byte
    out = bytearray(wav + pad + b"smpl" + struct.pack("<I", len(body)) + body)
    out[4:8] = struct.pack("<I", len(out) - 8)
    return bytes(out)


# ---------------------------------------------------------------- other formats

SOUND_FILES = (".flac", ".aif", ".aiff", ".aifc", ".ogg", ".oga", ".opus", ".mp3")  # what to_wav takes


def _smpl(body, got):
    """A RIFF smpl chunk as OpenMPT reads it (WAVTools.cpp, ApplySampleSettings): with two loops or more the first is
    the sustain loop and the second the normal one, else the one is the normal loop; an end of 0 is no loop; ends are
    inclusive; type 1 is pingpong. Its unity note is the root."""
    if len(body) < 36:
        return
    root, n = struct.unpack_from("<I", body, 12)[0], struct.unpack_from("<I", body, 28)[0]
    if root < 128:
        got["root"] = root
    for i, key in enumerate(("sustain", "loop") if n > 1 else ("loop",)):
        if 60 + 24 * i <= len(body):
            _id, kind, start, end = struct.unpack_from("<4I", body, 36 + 24 * i)
            if end:
                got[key] = (start, end + 1, kind == 1)


def _flac_settings(raw):
    """What OpenMPT keeps from a FLAC's metadata (SampleFormatFLAC.cpp), block by block, a later one winning: the RIFF
    chunks of APPLICATION 'riff' blocks as in a WAV (smpl; inst's unshifted note as the root when smpl gave none), and
    the Vorbis comments LOOPSTART and LOOPLENGTH as a forward loop."""
    got, pos = {}, 4
    while raw[:4] == b"fLaC" and pos + 4 <= len(raw):
        head, size = raw[pos], int.from_bytes(raw[pos + 1:pos + 4], "big")
        body = raw[pos + 4:pos + 4 + size]
        if head & 0x7F == 2 and body[:4] == b"riff" and len(body) >= 12:
            cid, n = struct.unpack_from("<4sI", body, 4)
            if cid == b"smpl":
                _smpl(body[12:12 + n], got)
            elif cid == b"inst" and n >= 1 and "root" not in got:
                got["root"] = body[12]
        elif head & 0x7F == 4 and len(body) >= 8:
            p = 8 + int.from_bytes(body[:4], "little")
            tags = {}
            for _ in range(int.from_bytes(body[p - 4:p], "little")):
                n = int.from_bytes(body[p:p + 4], "little")
                k, _, v = body[p + 4:p + 4 + n].decode("utf-8", "replace").partition("=")
                tags[k.upper()], p = v.strip(), p + 4 + n
            start, length = tags.get("LOOPSTART", ""), tags.get("LOOPLENGTH", "")
            if start.isdigit() and length.isdigit() and int(length) > 0:
                got["loop"] = (int(start), int(start) + int(length), False)
        if head & 0x80:
            break
        pos += 4 + size
    return got


def _aiff_settings(raw):
    """What OpenMPT keeps from an AIFF (SampleFormats.cpp, ReadAIFFSample): the INST chunk's sustain loop as the sustain
    loop and its release loop as the normal one, at their MARK positions (ends exclusive); play mode 1 forward, 2
    pingpong. Its base note is not used."""
    marks, inst, pos = {}, b"", 12
    while raw[:4] == b"FORM" and raw[8:12] in (b"AIFF", b"AIFC") and pos + 8 <= len(raw):
        cid, size = struct.unpack_from(">4sI", raw, pos)
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"MARK" and len(body) >= 2:
            p = 2
            for _ in range(struct.unpack_from(">H", body)[0]):
                if p + 7 > len(body):
                    break
                mid, at, n = struct.unpack_from(">hIB", body, p)
                marks[mid] = at
                p += 6 + n + 1 + (n + 1) % 2  # a pascal string, padded to an even length
        elif cid == b"INST":
            inst = body
        pos += 8 + size + (size & 1)
    got = {}
    for key, off in (("sustain", 8), ("loop", 14)):
        if len(inst) >= off + 6:
            mode, a, b = struct.unpack_from(">hhh", inst, off)
            if mode in (1, 2) and a in marks and b in marks and marks[b] > marks[a]:
                got[key] = (marks[a], marks[b], mode == 2)
    return got


def to_wav(src, folder, ffmpeg, name=None):
    """A FLAC, AIFF, Ogg Vorbis, Opus or MP3 file as a 16-bit WAV in `folder`, decoded by `ffmpeg`, with what OpenMPT
    keeps from it besides the audio in a smpl chunk: from a FLAC the loops and root note of its embedded RIFF chunks
    (or its LOOPSTART and LOOPLENGTH comments), from an AIFF its loops; from Ogg, Opus and MP3 nothing. The loops are
    written as OpenMPT writes them (a sustain loop first, then the normal one). Named after the file (or `name`),
    numbered so no other file is replaced; an identical WAV already there is reused. Returns (its path, whether it
    was written now)."""
    from .fileio import save_beside
    src = Path(src)
    raw = src.read_bytes()
    got = _flac_settings(raw) if raw[:4] == b"fLaC" else _aiff_settings(raw) if raw[:4] == b"FORM" else {}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.wav"
        r = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(src), "-map", "0:a:0", "-c:a", "pcm_s16le", "-bitexact",
                            "-map_metadata", "-1", str(out)], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode or not out.exists():
            raise WavError(f"{src.name}: ffmpeg could not read it ({r.stderr.decode(errors='replace').strip()[-300:]})")
        data = out.read_bytes()
    rate = struct.unpack_from("<I", data, 24)[0]
    if got:
        loops = [got["sustain"], got.get("loop") or (0, 1, False)] if "sustain" in got else [got["loop"]] if "loop" in got else []
        data = add_smpl(data, rate, root_note=got.get("root"), loops=loops)  # a sustain loop alone: a 0..0 dummy after it
    return save_beside(Path(folder), Path(name or src.name).stem, ".wav", data)


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
