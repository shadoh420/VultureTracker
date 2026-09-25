"""MOD, S3M and XM import (vulturetracker/modreader.py): small modules written here byte by byte, each rendered by
libopenmpt as it is and as the song the import makes of it (compiled to IT), and the two renders compared: level per
10 ms over the whole song, and the pitch where one note plays."""
import ctypes
import math
import struct
import tempfile
import unittest
from pathlib import Path

from vulturetracker import api, openmpt
from vulturetracker.itreader import ITReadError, import_it
from vulturetracker.modreader import ModReadError, read_module

RATE = 44100


def tone(n=4000, period=32, amp=100):
    """A looped-friendly wave: `n` frames of a sine `period` frames long (8-bit range)."""
    return [round(amp * math.sin(2 * math.pi * i / period)) for i in range(n)]


def render(data):
    """libopenmpt's render of a module, played once, at RATE, without its Amiga resampler emulation for MODs."""
    with openmpt.LoadedModule(data) as lm:
        f = getattr(openmpt._lib, "openmpt_module_ctl_set_boolean", None)
        if f is not None:
            f.argtypes, f.restype = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int], ctypes.c_int
            f(lm._mod, b"render.resampler.emulate_amiga", 0)
        return lm.render(RATE, oversample=1)


def imported(data, suffix):
    """The module imported into a song and compiled to IT: (it bytes, song dict, warnings)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        src = d / f"m.{suffix}"
        src.write_bytes(data)
        song, warnings = import_it(src, d / "m.yaml", d / "m_samples")
        it = api.compile_song(api.from_yaml((d / "m.yaml").read_text(encoding="utf-8")), d)[0]
    return it, song, warnings


def levels(pcm, ms=10):
    """dB per `ms` window of the mono mix, and the stereo balance (R - L energy in dB) over the whole render."""
    import numpy as np
    x = np.frombuffer(pcm, "<i2").astype(float).reshape(-1, 2) / 32768
    w = RATE * ms // 1000
    m = x.mean(axis=1)[: len(x) // w * w].reshape(-1, w)
    db = 10 * np.log10((m ** 2).mean(axis=1) + 1e-12)
    bal = 10 * np.log10(((x[:, 1] ** 2).sum() + 1e-12) / ((x[:, 0] ** 2).sum() + 1e-12))
    return db, bal


def compare(data, suffix):
    """(the largest level difference in dB over windows where either render is above -40 dB, both durations in s,
    both balances, warnings)."""
    import numpy as np
    a = render(data)
    it, song, warnings = imported(data, suffix)
    b = render(it)
    da, ba = levels(a)
    db, bb = levels(b)
    n = min(len(da), len(db))
    loud = np.maximum(da[:n], db[:n]) > -40
    diff = float(np.abs(da[:n] - db[:n])[loud].max()) if loud.any() else 0.0
    fa, fb = freq(a), freq(b)
    m = min(len(fa), len(fb))
    cents = float(np.median(np.abs(1200 * np.log2((fb[:m] + 1e-9) / (fa[:m] + 1e-9))))) if m > 1 else 0.0
    mean = float(np.abs(da[:n] - db[:n])[loud].mean()) if loud.any() else 0.0
    return {"diff": round(diff, 2), "mean": round(mean, 3), "cents": round(cents, 1), "median": round(float(np.median((db[:n] - da[:n])[loud])), 2) if loud.any() else 0.0, "secs": (len(a) / 4 / RATE, len(b) / 4 / RATE), "bal": (round(float(ba), 2), round(float(bb), 2)),
            "warnings": warnings, "song": song}


def freq(pcm, until=2.0):
    """The frequency of a single tone on a 5 ms grid (from 50 ms to `until`), from interpolated rising zero crossings."""
    import numpy as np
    x = np.frombuffer(pcm, "<i2").astype(float).reshape(-1, 2).mean(axis=1)[: int(until * RATE)]
    i = np.nonzero((x[:-1] < 0) & (x[1:] >= 0))[0]
    if len(i) < 3:
        return np.zeros(1)
    t = i + (-x[i]) / (x[i + 1] - x[i])
    return np.interp(np.arange(0.05, until - 0.05, 0.005), t[1:] / RATE, RATE / np.diff(t))


# ---------------------------------------------------------------- writers (enough of each format for the tests)

def write_mod(samples, patterns, orders, nch=4):
    """samples: (name, 8-bit data, volume, finetune, loop start, loop length); patterns: 64 rows of nch cells (period,
    sample, effect, param)."""
    b = bytearray(b"test mod".ljust(20, b"\0"))
    for i in range(31):
        if i < len(samples):
            name, d, vol, fine, ls, ll = samples[i]
            b += name.encode().ljust(22, b"\0") + struct.pack(">HBBHH", len(d) // 2, fine & 15, vol, ls // 2, max(1, ll // 2))
        else:
            b += bytes(22) + struct.pack(">HBBHH", 0, 0, 0, 0, 1)
    sig = b"M.K." if nch == 4 else f"{nch}CHN".encode()
    b += bytes([len(orders), 127]) + bytes(orders).ljust(128, b"\0") + sig
    for pat in patterns:
        for row in pat:
            for per, smp, eff, par in row:
                b += bytes([(smp & 0xF0) | (per >> 8), per & 255, ((smp & 15) << 4) | eff, par])
    for s in samples:
        b += bytes(v & 255 for v in s[1])
    return bytes(b)


def write_s3m(samples, patterns, orders, nch=4, stereo=True, gv=64, mv=0x30, pans=None):
    """samples: (name, 8-bit data, volume, c2spd, loop (start, end) or None); patterns: 64 rows of nch cells (note byte or
    None, instrument, volume or None, command 1-26 or 0, info)."""
    nord = len(orders) + (len(orders) & 1)
    head = bytearray(0x60)
    head[0:8] = b"test s3m"
    head[0x1C], head[0x1D] = 0x1A, 16
    struct.pack_into("<6H", head, 0x20, nord, len(samples), len(patterns), 0, 0x1320, 2)
    head[0x2C:0x30] = b"SCRM"
    head[0x30], head[0x31], head[0x32], head[0x33], head[0x35] = gv, 6, 125, mv | (0x80 if stereo else 0), 0xFC if pans else 0
    for c in range(32):
        head[0x40 + c] = (c // 2 if c % 2 == 0 else 8 + c // 2) if c < nch else 255
    body = head + bytes(orders) + (b"\xff" if len(orders) & 1 else b"")
    ptrs_at = len(body)
    body += bytes(2 * (len(samples) + len(patterns))) + (bytes(p | 0x20 for p in pans).ljust(32, b"\0") if pans else b"")
    ptrs = []
    heads = []
    for s in samples:  # sample headers, data pointers filled in below
        body += bytes((-len(body)) % 16)
        ptrs.append(len(body) // 16)
        heads.append(len(body))
        body += bytes(0x50)
    for pat in patterns:
        body += bytes((-len(body)) % 16)
        ptrs.append(len(body) // 16)
        pd = bytearray()
        for row in pat:
            for c, (note, ins, vol, cmd, info) in enumerate(row):
                what = c | (32 if note is not None or ins else 0) | (64 if vol is not None else 0) | (128 if cmd else 0)
                if what & 0xE0:
                    pd.append(what)
                    if what & 32:
                        pd += bytes([255 if note is None else note, ins])
                    if what & 64:
                        pd.append(vol)
                    if what & 128:
                        pd += bytes([cmd, info])
            pd.append(0)
        body += struct.pack("<H", len(pd) + 2) + pd
    for h, (name, d, vol, c2spd, loop) in zip(heads, samples):
        body += bytes((-len(body)) % 16)
        seg = len(body) // 16
        body[h] = 1
        body[h + 1:h + 13] = b"smp.raw".ljust(12, b"\0")
        body[h + 13] = seg >> 16
        struct.pack_into("<HIII", body, h + 14, seg & 0xFFFF, len(d), loop[0] if loop else 0, loop[1] if loop else 0)
        body[h + 0x1C], body[h + 0x1F] = vol, 1 if loop else 0
        struct.pack_into("<I", body, h + 0x20, c2spd)
        body[h + 0x30:h + 0x4C] = name.encode().ljust(28, b"\0")
        body[h + 0x4C:h + 0x50] = b"SCRS"
        body += bytes((v + 128) & 255 for v in d)  # unsigned
    struct.pack_into(f"<{len(ptrs)}H", body, ptrs_at, *ptrs)
    return bytes(body)


def write_xm(instruments, patterns, orders, nch=4, linear=True, speed=6, bpm=125):
    """instruments: dicts with 'data' (8-bit), optional 'volume', 'relnote', 'finetune', 'pan', 'loop' (start, len),
    'venv' ([(x, y)], sustain, (loop start, end)), 'fadeout', 'vib' (type, sweep, depth, rate); patterns: rows of nch
    cells (note, instrument, volume byte, effect, param)."""
    b = bytearray(b"Extended Module: " + b"test xm".ljust(20, b"\0") + b"\x1a" + b"VultureTracker test".ljust(20, b"\0"))
    b += struct.pack("<HI8H", 0x0104, 276, len(orders), 0, nch, len(patterns), len(instruments), 1 if linear else 0, speed, bpm)
    b += bytes(orders).ljust(256, b"\0")
    for pat in patterns:
        pd = b"".join(bytes(cell) for row in pat for cell in row)
        b += struct.pack("<IBHH", 9, 0, len(pat), len(pd)) + pd
    for ins in instruments:
        d = ins["data"]
        head = bytearray(263)
        struct.pack_into("<I", head, 0, 263)
        head[4:26] = b"ins".ljust(22, b"\0")
        struct.pack_into("<HI", head, 27, 1, 40)
        pts, sus, lp = ins.get("venv", (None, 0, None))
        if pts:
            for k, (x, y) in enumerate(pts):
                struct.pack_into("<HH", head, 129 + 4 * k, x, y)
            head[225], head[227] = len(pts), sus or 0
            head[228], head[229] = lp if lp else (0, 0)
            head[233] = 1 | (2 if sus is not None else 0) | (4 if lp else 0)
        vib = ins.get("vib", (0, 0, 0, 0))
        head[235:239] = bytes(vib)
        struct.pack_into("<H", head, 239, ins.get("fadeout", 0))
        ls, ll = ins.get("loop", (0, 0))
        smp = struct.pack("<IIIBbBBbB", len(d), ls, ll, ins.get("volume", 64), ins.get("finetune", 0), 1 if ll else 0,
                          ins.get("pan", 128), ins.get("relnote", 0), 0) + b"s".ljust(22, b"\0")
        delta, prev = bytearray(), 0
        for v in d:
            delta.append((v - prev) & 255)
            prev = v
        b += head + smp + delta
    return bytes(b)


def grid(events, empty, nch=4, rows=64):
    """`rows` rows of `nch` empty cells with (row, channel, cell) events placed."""
    out = [[empty] * nch for _ in range(rows)]
    for r, c, cell in events:
        out[r][c] = cell
    return out


def held(r0, r1, c, cell):
    return [(r, c, cell) for r in range(r0, r1)]


def L(ch):
    return ord(ch) - 64


EMPTY4, E_S3M, E_XM = (0, 0, 0, 0), (None, 0, None, 0, 0), (0, 0, 0, 0, 0)
TONE = tone(4000, period=8)  # a 1 kHz-ish tone at C-5, looped: pitch is measurable to a few cents
# (name, events, largest level difference in dB over 10 ms windows: the steep edges of a slide or a tremolo a tick apart
# reach a few dB, median pitch difference in cents); the mean level difference stays under 0.5 dB, its median
# difference stay within 0.1 dB and the stereo balance within 0.3 dB (IT pans in 64ths) of libopenmpt's
MOD_CASES = [("plain", [(0, 0, (428, 1, 0, 0))], 0.3, 1), ("vibrato", [(0, 0, (428, 1, 4, 0x48))] + held(1, 16, 0, (0, 0, 4, 0)), 0.3, 25),
             ("volume slide", [(0, 0, (428, 1, 0xA, 0x04))] + held(1, 8, 0, (0, 0, 0xA, 0x04)) + [(8, 0, (0, 0, 0xA, 0x30))], 5, 1),
             ("porta up", [(0, 0, (428, 1, 1, 4))] + held(1, 8, 0, (0, 0, 1, 4)), 0.3, 15),
             ("arpeggio", [(0, 0, (428, 1, 0, 0x37))] + held(1, 8, 0, (0, 0, 0, 0x37)), 0.3, 1),
             ("tone porta", [(0, 0, (428, 1, 0, 0)), (4, 0, (214, 0, 3, 8))] + held(5, 12, 0, (0, 0, 3, 0)), 0.3, 2),
             ("tremolo", [(0, 0, (428, 1, 7, 0x46))] + held(1, 16, 0, (0, 0, 7, 0)), 5, 1),
             ("pans", [(0, 0, (428, 1, 0, 0)), (0, 1, (214, 1, 0, 0))], 0.5, None)]
C5 = 0x40  # the ST3 note byte of IT's C-5
S3M_CASES = [("plain", [(0, 0, (C5, 1, None, 0, 0))], 0.1, 1), ("volume column", [(0, 0, (C5, 1, 32, 0, 0))], 0.1, 1),
             ("vibrato", [(0, 0, (C5, 1, None, L("H"), 0x48))] + held(1, 16, 0, (None, 0, None, L("H"), 0)), 0.3, 20),
             ("tremolo", [(0, 0, (C5, 1, None, L("R"), 0x44))] + held(1, 16, 0, (None, 0, None, L("R"), 0)), 0.2, 1),
             ("shared memory", [(0, 0, (C5, 1, None, L("D"), 0x03)), (2, 0, (None, 0, None, L("E"), 0))] + held(3, 8, 0, (None, 0, None, L("E"), 0)), 0.3, 6),
             ("porta up", [(0, 0, (C5, 1, None, L("F"), 4))] + held(1, 8, 0, (None, 0, None, L("F"), 0)), 0.3, 6),
             ("arpeggio", [(0, 0, (C5, 1, None, L("J"), 0x37))] + held(1, 8, 0, (None, 0, None, L("J"), 0)), 0.2, 1),
             ("global volume", [(0, 0, (C5, 1, None, L("V"), 0x20))], 0.1, 1),
             ("retrigger", [(0, 0, (C5, 1, None, L("Q"), 3))] + held(1, 8, 0, (None, 0, None, L("Q"), 0)), 0.1, 1),
             ("pattern break", [(0, 0, (C5, 1, None, 0, 0)), (8, 0, (None, 0, None, L("C"), 0x10))], 0.1, 1)]
C4 = 49  # the XM note of IT's C-5
XM_CASES = [("plain", {}, [(0, 0, (C4, 1, 0, 0, 0))], 0.1, 1), ("volume column", {}, [(0, 0, (C4, 1, 0x30, 0, 0))], 0.1, 1),
            ("vibrato", {}, [(0, 0, (C4, 1, 0, 4, 0x48))] + held(1, 16, 0, (0, 0, 0, 4, 0)), 0.3, 25),
            ("tremolo", {}, [(0, 0, (C4, 1, 0, 7, 0x44))] + held(1, 16, 0, (0, 0, 0, 7, 0)), 0.2, 1),
            ("volume slide", {}, [(0, 0, (C4, 1, 0, 0xA, 4))] + held(1, 8, 0, (0, 0, 0, 0xA, 0)), 0.1, 1),
            ("porta up", {}, [(0, 0, (C4, 1, 0, 1, 4))] + held(1, 8, 0, (0, 0, 0, 1, 0)), 0.2, 6),
            ("arpeggio", {}, [(0, 0, (C4, 1, 0, 0, 0x37))] + held(1, 8, 0, (0, 0, 0, 0, 0x37)), 0.1, 1),
            ("key-off, no envelope", {}, [(0, 0, (C4, 1, 0, 0, 0)), (8, 0, (97, 0, 0, 0, 0))], 0.1, None),
            ("key-off, envelope and fadeout", {"venv": ([(0, 64), (10, 40), (20, 40)], 2, None), "fadeout": 0x200},
             [(0, 0, (C4, 1, 0, 0, 0)), (16, 0, (97, 0, 0, 0, 0))], 1.0, None),
            ("envelope loop", {"venv": ([(0, 64), (8, 10), (16, 64)], None, (0, 2))}, [(0, 0, (C4, 1, 0, 0, 0))], 1.0, 1),
            ("sample pan", {"pan": 0x30}, [(0, 0, (C4, 1, 0, 0, 0))], 0.1, 1),
            ("relative note, finetune", {"relnote": 12, "finetune": 40}, [(0, 0, (C4, 1, 0, 0, 0))], 0.1, 1),
            ("auto-vibrato", {"vib": (0, 10, 8, 20)}, [(0, 0, (C4, 1, 0, 0, 0))], 0.2, 10),
            ("global volume", {}, [(0, 0, (C4, 1, 0, 0x10, 0x20))], 0.1, 1),
            ("volume column slide", {}, [(0, 0, (C4, 1, 0x62, 0, 0))] + held(1, 8, 0, (0, 0, 0x62, 0, 0)), 0.1, 1),
            ("volume column pan", {}, [(0, 0, (C4, 1, 0xC4, 0, 0))], 0.1, 1),
            ("volume column porta", {}, [(0, 0, (C4, 1, 0, 0, 0)), (4, 0, (C4 + 7, 0, 0xF4, 0, 0))] + held(5, 12, 0, (0, 0, 0xF0, 0, 0)), 0.2, 6),
            ("key-off after ticks", {}, [(0, 0, (C4, 1, 0, 0, 0)), (4, 0, (0, 0, 0, 0x14, 3))], 0.1, None)]


class TestModImport(unittest.TestCase):
    def check(self, data, suffix, name, level, cents):
        r = compare(data, suffix)
        with self.subTest(name):
            self.assertEqual(r["secs"][0], r["secs"][1])
            self.assertLess(abs(r["median"]), 0.1)
            self.assertLess(r["mean"], 0.5)
            self.assertLess(r["diff"], level)
            self.assertLess(abs(r["bal"][0] - r["bal"][1]), 0.3)  # IT pans in 64ths
            if cents is not None:
                self.assertLess(r["cents"], cents)
        return r

    def test_malformed_files_are_read_errors(self):
        # a truncated or garbled file is a ModReadError (which the CLI and the app report), never a struct.error,
        # IndexError or ValueError escaping; a pattern claiming 65535 rows is left empty, not allocated as a giant grid
        s3m = write_s3m([("tone", TONE, 64, 8363, (0, 4000))], [grid([(0, 0, (C5, 1, None, 0, 0))], E_S3M)], [0])
        xm = write_xm([{"data": TONE, "loop": (0, 4000)}], [grid([(0, 0, (C4, 1, 0, 0, 0))], E_XM)], [0])
        mod = write_mod([("tone", TONE, 64, 0, 0, 4000)], [grid([(0, 0, (428, 1, 0, 0))], EMPTY4)], [0])
        it = imported(mod, "mod")[0]
        for data in (s3m, xm, mod, it):
            for n in range(0, len(data), 13):
                try:
                    read_module(data[:n])
                except (ModReadError, ITReadError):
                    pass
        d = bytearray(xm)
        struct.pack_into("<H", d, 60 + 276 + 5, 65535)  # the first pattern's row count
        m, warnings = read_module(bytes(d))
        self.assertEqual((len(m.patterns[0].rows), any("1024 rows" in w for w in warnings)), (64, True))
        d = bytearray(it)
        nord, nins, nsmp = struct.unpack_from("<HHH", d, 0x20)
        struct.pack_into("<H", d, struct.unpack_from("<I", d, 0xC0 + nord + 4 * nins + 4 * nsmp)[0] + 2, 65535)
        m, warnings = read_module(bytes(d))
        self.assertEqual((len(m.patterns[0].rows), any("not a valid IT pattern" in w for w in warnings)), (64, True))

    def test_signatures(self):
        with self.assertRaises(ModReadError):
            read_module(b"not a module at all" * 100)
        self.assertTrue(read_module(write_mod([("t", TONE, 64, 0, 0, 4000)], [grid([], EMPTY4)], [0]))[0].old_effects)

    def test_mod_plays_like_libopenmpt(self):
        for name, events, level, cents in MOD_CASES:
            self.check(write_mod([("tone", TONE, 64, 0, 0, 4000)], [grid(events, EMPTY4)], [0]), "mod", name, level, cents)
        self.check(write_mod([("tone", TONE, 64, -3, 0, 4000)], [grid([(0, 0, (428, 1, 0, 0))], EMPTY4)], [0]), "mod", "finetune", 0.3, 1)
        self.check(write_mod([("tone", TONE, 64, 0, 0, 4000)], [grid([(0, 5, (428, 1, 0, 0))], EMPTY4, 8)], [0], nch=8), "mod", "8 channels", 0.3, 1)

    def test_s3m_plays_like_libopenmpt(self):
        smp = [("tone", TONE, 64, 8363, (0, 4000))]
        for name, events, level, cents in S3M_CASES:
            self.check(write_s3m(smp, [grid(events, E_S3M)], [0]), "s3m", name, level, cents)
        two = grid([(0, 0, (C5, 1, None, 0, 0)), (0, 1, (C5 + 16, 1, None, 0, 0))], E_S3M)
        for kw in ({"stereo": False}, {"stereo": False, "pans": [2, 13, 7, 8]}, {"pans": [2, 13, 7, 8]}, {"mv": 0x60}):
            self.check(write_s3m(smp, [two], [0], **kw), "s3m", f"mix {kw}", 0.5, None)

    def test_xm_plays_like_libopenmpt(self):
        for name, extra, events, level, cents in XM_CASES:
            ins = {"data": TONE, "loop": (0, 4000), **extra}
            for linear in (True, False) if "porta" in name else (True,):
                self.check(write_xm([ins], [grid(events, E_XM)], [0], linear=linear), "xm", f"{name} linear={linear}", level, cents)

    def test_xm_long_patterns_many_instruments_and_level(self):
        ins = {"data": TONE, "loop": (0, 4000)}
        long = grid([(0, 0, (C4, 1, 0, 0, 0)), (100, 0, (97, 0, 0, 0, 0)), (220, 1, (C4 + 12, 1, 0, 0, 0)), (230, 1, (0, 0, 0, 0xD, 0x04))], E_XM, rows=256)
        short = grid([(0, 2, (C4 + 7, 1, 0, 0, 0)), (4, 2, (0, 0, 0, 0xD, 0x10))], E_XM, rows=64)
        r = self.check(write_xm([ins], [long, short], [0, 1, 0], speed=2), "xm", "256-row pattern split", 0.5, None)
        self.assertEqual(r["song"]["orders"], ["p00a", "p00b", "p01", "p00a", "p00b"])
        self.assertTrue(any("split into parts of 192" in w for w in r["warnings"]))
        # 105 instruments, three of them played: those kept, renumbered 1-3, every cell following
        many = [{"data": tone(64 + 8 * k, period=8), "loop": (0, 64 + 8 * k)} for k in range(105)]
        pat = grid([(0, 0, (C4, 3, 0, 0, 0)), (8, 1, (C4, 50, 0, 0, 0)), (16, 2, (C4, 105, 0, 0, 0))], E_XM)
        r = self.check(write_xm(many, [pat], [0]), "xm", "105 instruments", 0.5, None)
        self.assertEqual(len(r["song"]["instruments"]), 3)
        # a MilkyTracker file: libopenmpt mixes it 3 dB louder, the import measures that into the mix volume
        d = bytearray(write_xm([ins], [grid([(0, 0, (C4, 1, 0, 0, 0))], E_XM)], [0]))
        d[38:58] = b"MilkyTracker 1.03.00"
        r = compare(bytes(d), "xm")
        self.assertLess(abs(r["median"]), 0.2)
        self.assertEqual(r["song"]["module"]["mix_volume"], 68)


class _Bits:
    """An IT 2.14 compressed block written bit by bit, least significant bit first (the reader's order)."""
    def __init__(self):
        self.v, self.n = 0, 0

    def put(self, value, width):
        self.v |= (value & ((1 << width) - 1)) << self.n
        self.n += width

    def block(self):
        body = self.v.to_bytes((self.n + 7) // 8, "little")
        return struct.pack("<H", len(body)) + body


class TestITReader(unittest.TestCase):
    def test_decompress_known_stream(self):
        # 8-bit: two deltas at the full width (9 bits), a change to width 4 (method 3), two 4-bit deltas, a change to
        # width 8 (method 1: escape, then 3 bits holding width - 1 ... read as v + 1 = 7 -> 8), two 8-bit deltas
        from vulturetracker.itreader import _decompress
        b = _Bits()
        b.put(5, 9), b.put(-3 & 0xFF, 9), b.put(0x100 | 3, 9)  # full width: bit 8 clear is a value, set a width (4)
        b.put(2, 4), b.put(-1, 4), b.put(8, 4), b.put(6, 3)  # escape to width 8
        b.put(10, 8), b.put(-20, 8)
        data = b.block()
        self.assertEqual(_decompress(data, 0, 6, False, False), ([5, 2, 4, 3, 13, -7], len(data)))
        self.assertEqual(_decompress(data, 0, 6, False, True)[0], [5, 7, 11, 14, 27, 20])  # IT 2.15: deltas of deltas
        # 16-bit at the full width (17 bits), across two blocks
        b1, b2 = _Bits(), _Bits()
        b1.put(1000, 17), b1.put(-3000 & 0xFFFF, 17)
        b2.put(32767, 17)
        out, pos = _decompress(b1.block() + b2.block(), 0, 2, True, False)
        self.assertEqual(out, [1000, -2000])
        with self.assertRaises(ITReadError):
            _decompress(b1.block()[:3], 0, 2, True, False)  # truncated

    def test_long_patterns_are_split_and_high_numbers_dropped(self):
        # an IT pattern of 300 rows (libopenmpt plays up to 1024) imports as parts the song format can hold (P5); cells
        # and keymaps naming numbers above 99 are dropped with a warning (P6), so the imported song compiles
        from vulturetracker.itreader import _sanitize, module_to_song, read_it
        it = imported(write_mod([("tone", TONE, 64, 0, 0, 4000)], [grid([(0, 0, (428, 1, 0, 0))], EMPTY4)], [0]), "mod")[0]
        d = bytearray(it)
        nord, nins, nsmp = struct.unpack_from("<HHH", d, 0x20)
        struct.pack_into("<H", d, struct.unpack_from("<I", d, 0xC0 + nord + 4 * nins + 4 * nsmp)[0] + 2, 300)
        mod, warnings = read_it(bytes(d))
        self.assertEqual([len(p.rows) for p in mod.patterns], [192, 108])
        self.assertTrue(any("longer than 200 rows" in w for w in warnings))
        mod.patterns[0].rows[1][0].instrument = 150
        w = []
        _sanitize(mod, w)
        self.assertEqual((mod.patterns[0].rows[1][0].instrument, any("above 99" in x for x in w)), (0, True))
        with tempfile.TemporaryDirectory() as tmp:
            song = module_to_song(mod, Path(tmp) / "m.yaml", Path(tmp) / "m_samples")
            self.assertTrue(api.check(api.to_yaml(song), tmp)["ok"])
