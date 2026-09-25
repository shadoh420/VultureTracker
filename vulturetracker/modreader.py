"""MOD, S3M and XM files -> Module (IT semantics), so `import` turns them into song files like an .it.

Each reader maps its format onto what IT (and the song format) can say, the way OpenMPT converts to IT: notes to IT's
C-0..B-9 with C-5 playing a sample at its c5 speed, effects to their IT letters, format quirks written out where IT has
no equivalent, and what cannot be said dropped with a warning. The mapping is checked by rendering the original with
libopenmpt and the imported song compiled to IT (tests/test_modimport.py)."""
import math
import struct

from .itreader import ITReadError, _cstr, _sanitize
from .model import (Cell, Channel, Envelope, Instrument, Loop, Module, Pattern, Sample,
                    NOTE_CUT, NOTE_OFF, ORDER_SKIP)


class ModReadError(ValueError):
    pass


def fx(letter):
    return ord(letter) - 64


# IT volume column bytes (notation.VOLCMDS): v 0-64, a/b fine slide up/down 65/75, c/d slide up/down 85/95, p 128,
# g 193, h 203; a-d, g and h take 0-9
VOL_A, VOL_B, VOL_C, VOL_D, VOL_P, VOL_G, VOL_H = 65, 75, 85, 95, 128, 193, 203
G_SPEEDS = (0, 1, 4, 8, 16, 32, 64, 96, 128, 255)  # the volume column's tone portamento speeds


class _Warn:
    def __init__(self):
        self.counts = {}

    def __call__(self, what, n=1):
        self.counts[what] = self.counts.get(what, 0) + n

    def lines(self):
        return [f"{n} × {w}" if n > 1 else w for w, n in self.counts.items()]


def _slide(par):
    """A ProTracker-style volume slide (x up, y down; x wins when both are set) as IT's Dxy, which would read an F nibble
    or both nibbles set as a fine slide."""
    x, y = par >> 4, par & 15
    return (x << 4) if x else y


def _pt_effect(cell, eff, par, warn, fmt):
    """ProTracker effects 0-F (MOD, and XM's first sixteen) onto `cell` in IT terms."""
    x, y = par >> 4, par & 15
    if eff == 0:
        if par:
            cell.effect, cell.param = fx("J"), par
    elif eff in (1, 2):  # IT reads E0-FF as fine and extra fine slides: a coarse slide stops just under
        if par or fmt == "xm":  # ProTracker's 100/200 does nothing; XM's reuses its last value, like IT's
            cell.effect, cell.param = fx("F" if eff == 1 else "E"), min(par, 0xDF)
            if par > 0xDF:
                warn("pitch slides faster than DF per tick, slowed to DF")
    elif eff == 3:
        cell.effect, cell.param = fx("G"), par
    elif eff == 4:
        cell.effect, cell.param = fx("H"), par
    elif eff in (5, 6):
        if par or fmt == "xm":
            cell.effect, cell.param = fx("L" if eff == 5 else "K"), _slide(par)
        else:
            cell.effect, cell.param = fx("G" if eff == 5 else "H"), 0
    elif eff == 7:  # with IT's old effects (set for these imports), IT's tremolo is half as deep as ProTracker's
        cell.effect, cell.param = fx("R"), (par & 0xF0) | min(15, 2 * y)
        if y > 7:
            warn("tremolo deeper than 7 capped at IT's F")
    elif eff == 8:
        cell.effect, cell.param = fx("X"), par
    elif eff == 9:
        cell.effect, cell.param = fx("O"), par
    elif eff == 0xA:
        if par or fmt == "xm":
            cell.effect, cell.param = fx("D"), _slide(par)
    elif eff == 0xB:
        cell.effect, cell.param = fx("B"), par
    elif eff == 0xC:
        cell.volcmd = min(par, 64)
    elif eff == 0xD:  # the row as two decimal digits
        cell.effect, cell.param = fx("C"), min(63, x * 10 + y) if fmt == "mod" else x * 10 + y
    elif eff == 0xE:
        sub = {1: ("F", 0xF0), 2: ("E", 0xF0), 3: ("S", 0x10), 4: ("S", 0x30), 6: ("S", 0xB0), 7: ("S", 0x40),
               8: ("S", 0x80), 0xC: ("S", 0xC0), 0xD: ("S", 0xD0), 0xE: ("S", 0xE0)}.get(x)
        if sub and (y or x not in (1, 2)):
            cell.effect, cell.param = fx(sub[0]), sub[1] | y
        elif x == 9 and y:
            cell.effect, cell.param = fx("Q"), y
        elif x == 0xA and y:
            cell.effect, cell.param = fx("D"), (y << 4) | 0xF
        elif x == 0xB and y:
            cell.effect, cell.param = fx("D"), 0xF0 | y
        elif x in (0, 5, 0xF):
            warn({0: "Amiga filter (E0x) commands dropped", 5: "finetune (E5x) commands dropped", 0xF: "invert loop (EFx) commands dropped"}[x])
    elif eff == 0xF:
        if par == 0:
            warn("F00 (stop the song) dropped")
        else:
            cell.effect, cell.param = fx("A" if par < 32 else "T"), par


def _module(title, nch, fmt):
    mod = Module(title=title[:25])
    mod.channels = [Channel(name=f"Ch {i + 1}") for i in range(nch)]
    mod.linear_slides = False
    return mod


def _orders(mod, orders, npat):
    """Order list entries past the patterns dropped; '+++' and '---' kept."""
    out = []
    for o in orders:
        if o == 0xFF:
            break
        if o == 0xFE:
            out.append(ORDER_SKIP)
        elif o < npat:
            out.append(o)
    mod.orders = out or [0]


def _finish(mod, warn):
    warnings = warn.lines()
    _sanitize(mod, warnings)
    return mod, warnings


# ---------------------------------------------------------------- MOD

PT_PERIOD_C1 = 856  # ProTracker's C-1 (finetune 0), played at IT's C-4 (ProTracker's C-2, period 428, is IT's C-5)
AMIGA_C5 = 7093789.2 / (2 * 428)  # the rate a PAL Amiga plays period 428 at (8287 Hz), as libopenmpt does


def _mod_channels(sig):
    if sig in (b"M.K.", b"M!K!", b"M&K!", b"N.T.", b"FLT4"):
        return 4
    if sig in (b"FLT8", b"OKTA", b"OCTA", b"CD81"):
        return 8
    if sig[1:] == b"CHN" and sig[:1].isdigit():
        return int(sig[:1])
    if sig[2:] in (b"CH", b"CN") and sig[:2].isdigit():
        return int(sig[:2])
    return None


def read_mod(data: bytes):
    """A 31-sample ProTracker-style MOD (M.K. and the xCHN / xxCH family) -> (Module, warnings). Sample mode; Amiga pitch
    slides; channels panned in the Amiga's L R R L order."""
    if len(data) < 1084:
        raise ModReadError("too short for a MOD")
    nch = _mod_channels(data[1080:1084])
    if not nch or nch > 64:
        raise ModReadError(f"not a 31-sample MOD (signature {data[1080:1084]!r})")
    warn = _Warn()
    mod = _module(_cstr(data[:20]), nch, "mod")
    mod.mix_volume = 64  # libopenmpt mixes a MOD 2.5 dB louder than an IT at the default 48 (measured)
    mod.old_effects = True  # IT's old effects play ProTracker's vibrato and tremolo (depth, phase; measured)
    for i, ch in enumerate(mod.channels):
        ch.pan = 16 if i % 4 in (0, 3) else 48  # OpenMPT's Amiga panning: a quarter and three quarters
    heads = []
    for i in range(31):
        o = 20 + 30 * i
        name = _cstr(data[o:o + 22])
        length, fine, vol, lstart, llen = struct.unpack_from(">HBBHH", data, o + 22)
        fine = (fine & 15) - 16 if fine & 8 else fine & 15
        heads.append((name, 2 * length, fine, min(vol, 64), 2 * lstart, 2 * llen))
    songlen = data[950]
    table = data[952:1080]
    npat = max(table) + 1
    pos = 1084
    for p in range(npat):
        rows = []
        for r in range(64):
            row = []
            for c in range(nch):
                b0, b1, b2, b3 = data[pos:pos + 4] if pos + 4 <= len(data) else (0, 0, 0, 0)
                pos += 4
                cell = Cell()
                period = ((b0 & 15) << 8) | b1
                cell.instrument = (b0 & 0xF0) | (b2 >> 4)
                if period:
                    cell.note = max(0, min(119, 48 + round(12 * math.log2(PT_PERIOD_C1 / period))))
                _pt_effect(cell, b2 & 15, b3, warn, "mod")
                row.append(cell)
            rows.append(row)
        mod.patterns.append(Pattern(f"p{p:02d}", rows))
    for name, length, fine, vol, lstart, llen in heads:
        smp = Sample(name=name[:25], bits=8, volume=vol, c5_speed=round(AMIGA_C5 * 2 ** (fine / 96)))
        raw = data[pos:pos + length]
        pos += length
        if raw:
            smp.data = [[b - 256 if b > 127 else b for b in raw]]
            if llen > 2 and lstart < len(raw):
                smp.loop = Loop(lstart, min(len(raw), lstart + llen))
        mod.samples.append(smp)
    if pos > len(data) + 2:
        warn("the file ends inside the sample data (samples cut short)")
    _orders(mod, table[:songlen], npat)
    return _finish(mod, warn)


# ---------------------------------------------------------------- S3M

# effects that share one parameter memory in Scream Tracker 3 (a 00 reuses the last non-zero parameter of any of them)
S3M_SHARED = set("DEFIJKLQRS")


def read_s3m(data: bytes):
    """A Scream Tracker 3 module -> (Module, warnings). Sample mode; Amiga pitch slides; IT's old effects; ST3's shared
    effect memory written out as explicit parameters; AdLib instruments dropped."""
    if data[0x2C:0x30] != b"SCRM":
        raise ModReadError("not an S3M (no SCRM signature)")
    warn = _Warn()
    nord, nins, npat, flags, cwt, ffi = struct.unpack_from("<6H", data, 0x20)
    gv, speed, tempo, mv, uc, dp = data[0x30:0x36]
    chset = data[0x40:0x60]
    used = [c for c in range(32) if chset[c] < 16]
    nch = max(used) + 1 if used else 1
    mod = _module(_cstr(data[:28]), nch, "s3m")
    mod.global_volume, mod.speed = min(128, 2 * gv), speed or 6
    mod.tempo = tempo if tempo >= 32 else 125
    stereo = bool(mv & 0x80)
    # libopenmpt plays a mono S3M whose ultraclick byte is 0 2.74 dB quieter than the same file in stereo (measured)
    mod.mix_volume = round((mv & 0x7F) * (1 if stereo or uc else 0.73))
    mod.old_effects = True  # IT's old effects play ST3's vibrato and tremolo (measured)
    p = 0x60 + nord
    insptr = struct.unpack_from(f"<{nins}H", data, p)
    patptr = struct.unpack_from(f"<{npat}H", data, p + 2 * nins)
    pans = data[p + 2 * nins + 2 * npat: p + 2 * nins + 2 * npat + 32] if dp == 0xFC else b""
    for c, ch in enumerate(mod.channels):
        if chset[c] >= 16:
            ch.muted = True
        if c < len(pans) and pans[c] & 0x20:  # the file's own pan, kept in mono too (as libopenmpt does)
            ch.pan = round((pans[c] & 15) * 64 / 15)
        else:
            ch.pan = round((3 if chset[c] < 8 else 12) * 64 / 15) if stereo else 32
    for i, ptr in enumerate(insptr):
        o = 16 * ptr
        smp = Sample()
        mod.samples.append(smp)
        if o + 0x50 > len(data):
            continue
        kind = data[o]
        smp.name, smp.filename = _cstr(data[o + 0x30:o + 0x4C])[:25], _cstr(data[o + 1:o + 13])
        if kind != 1:
            if kind >= 2:
                warn("AdLib instruments dropped (silent slots)")
            continue
        seg = (data[o + 13] << 16) | struct.unpack_from("<H", data, o + 14)[0]
        length, lbeg, lend = struct.unpack_from("<3I", data, o + 0x10)
        vol, pack, sflags = data[o + 0x1C], data[o + 0x1E], data[o + 0x1F]
        c2spd = struct.unpack_from("<I", data, o + 0x20)[0]
        if pack:
            warn("packed (DP30ADPCM) samples dropped")
            continue
        is16, st = bool(sflags & 4), bool(sflags & 2)
        width = 2 if is16 else 1
        off = 16 * seg
        chans = []
        for k in range(2 if st else 1):
            raw = data[off + k * length * width: off + (k + 1) * length * width]
            if is16:
                vals = list(struct.unpack(f"<{len(raw) // 2}h", raw[:len(raw) // 2 * 2]))
                if ffi == 2:
                    vals = [(v + 32768) % 65536 - 32768 for v in vals]
            else:
                vals = [(b - 128) if ffi == 2 else (b - 256 if b > 127 else b) for b in raw]
            chans.append(vals)
        if not chans or not chans[0]:
            continue
        n = min(len(c) for c in chans)
        smp.data, smp.bits = [c[:n] for c in chans], 16 if is16 else 8
        smp.volume, smp.c5_speed = min(vol, 64), max(256, c2spd or 8363)
        if sflags & 1 and lbeg < min(lend, n):
            smp.loop = Loop(lbeg, min(lend, n))
    mem = [0] * nch  # ST3's shared memory, carried along the order list
    seen = {}
    for pi in [o for o in data[0x60:0x60 + nord] if o < npat] + list(range(npat)):
        if pi in seen:
            continue
        seen[pi] = True
    pats = [None] * npat
    for pi in seen:
        o = 16 * patptr[pi]
        rows = [[Cell() for _ in range(nch)] for _ in range(64)]
        if patptr[pi] and o + 2 <= len(data):
            end = o + 2 + struct.unpack_from("<H", data, o)[0]
            i, r = o + 2, 0
            while r < 64 and i < min(end, len(data)):
                what = data[i]
                i += 1
                if not what:
                    r += 1
                    continue
                c = what & 31
                note = ins = vol = cmd = info = None
                if what & 32:
                    note, ins = data[i], data[i + 1]
                    i += 2
                if what & 64:
                    vol = data[i]
                    i += 1
                if what & 128:
                    cmd, info = data[i], data[i + 1]
                    i += 2
                if c >= nch:
                    continue
                cell = rows[r][c]
                if note is not None and note != 255:
                    cell.note = NOTE_CUT if note == 254 else min(119, (note >> 4) * 12 + (note & 15) + 12)
                cell.instrument = ins or 0
                if vol is not None:
                    cell.volcmd = min(vol, 64)
                if cmd:
                    _s3m_effect(cell, cmd, info, mem, c, warn)
        pats[pi] = Pattern(f"p{pi:02d}", rows)
    mod.patterns = pats
    _orders(mod, data[0x60:0x60 + nord], npat)
    return _finish(mod, warn)


def _s3m_effect(cell, cmd, info, mem, c, warn):
    if not 1 <= cmd <= 26:
        return
    L = chr(64 + cmd)
    if L in S3M_SHARED:
        if info:
            mem[c] = info
        else:
            info = mem[c]
    if L == "A" and not info or L == "T" and info < 0x20:
        return
    if L == "C":
        info = (info >> 4) * 10 + (info & 15)
    elif L == "V":
        info = min(0x80, 2 * info)
    elif L == "X":
        if info == 0xA4:
            cell.effect, cell.param = fx("S"), 0x91
            return
        info = min(0xFF, 2 * info)
    elif L == "S" and info >> 4 in (0, 2, 5, 0xA, 0xF):
        warn("S3M S0x/S2x/S5x/SAx/SFx commands dropped")
        return
    cell.effect, cell.param = cmd, info


# ---------------------------------------------------------------- XM

XM_FADE = 32  # FT2's fade level starts at 32768 and loses the fadeout each tick; IT's starts at 1024
XM_VIBRATO = {0: 0, 1: 2, 2: 1, 3: 1}  # XM sine, square, ramp down, ramp up -> IT sine, square, ramp down (no ramp up)


def read_xm(data: bytes):
    """A FastTracker 2 module -> (Module, warnings). Instrument mode: XM's per-instrument samples become one global
    list, each with its relative note and finetune in its c5 speed and its panning as the sample's pan; a key-off on an
    instrument without a volume envelope cuts the note, as in FT2."""
    if data[:17] != b"Extended Module: ":
        raise ModReadError("not an XM (no 'Extended Module: ' header)")
    warn = _Warn()
    ver = struct.unpack_from("<H", data, 58)[0]
    if ver < 0x0104:
        raise ModReadError(f"XM version {ver >> 8}.{ver & 255:02d}: only 1.04 files (FastTracker 2.0x on) are read")
    hsize = struct.unpack_from("<I", data, 60)[0]
    slen, _restart, nch, npat, nins, flags, speed, bpm = struct.unpack_from("<8H", data, 64)
    mod = _module(_cstr(data[17:37]), max(1, min(64, nch)), "xm")
    mod.linear_slides = bool(flags & 1)
    mod.old_effects = True  # IT's old effects play FT2's vibrato and tremolo (measured, as for MOD)
    mod.speed, mod.tempo = min(255, speed or 6), max(32, min(255, bpm or 125))
    table = data[80:80 + min(256, slen)]
    pos = 60 + hsize
    for p in range(npat):
        plen, _pack, nrows, psize = struct.unpack_from("<IBHH", data, pos)
        pd = data[pos + plen: pos + plen + psize]
        pos += plen + psize
        if nrows > 1024:  # no tracker plays it (FT2 stops at 256, libopenmpt at 1024): left empty, not allocated
            warn("patterns with more than 1024 rows dropped (left empty)")
            nrows, pd = 64, b""
        rows = [[Cell() for _ in range(len(mod.channels))] for _ in range(max(1, nrows))]
        i = 0
        for r in range(nrows):
            for c in range(nch):
                if i >= len(pd):
                    break
                b = pd[i]
                if b & 0x80:
                    i += 1
                    vals = []
                    for bit in range(5):
                        if b & (1 << bit):
                            vals.append(pd[i] if i < len(pd) else 0)
                            i += 1
                        else:
                            vals.append(0)
                else:
                    vals = list(pd[i:i + 5]) + [0] * (5 - len(pd[i:i + 5]))
                    i += 5
                if c < 64:
                    _xm_cell(rows[r][c], *vals, warn)
        mod.patterns.append(Pattern(f"p{p:02d}", rows))
    mod.instruments = []
    for n in range(nins):
        isize = struct.unpack_from("<I", data, pos)[0]
        ins = Instrument(name=_cstr(data[pos + 4:pos + 26])[:25])
        mod.instruments.append(ins)
        nsmp = struct.unpack_from("<H", data, pos + 27)[0] if isize >= 29 else 0
        if not nsmp:
            ins.keymap = [(k, 0) for k in range(120)]
            pos += isize
            continue
        shsize = struct.unpack_from("<I", data, pos + 29)[0]
        o = pos
        keys = data[o + 33:o + 129]
        venv, penv = struct.unpack_from("<24H", data, o + 129), struct.unpack_from("<24H", data, o + 177)
        nv, np_, vsus, vls, vle, psus, pls, ple, vtype, ptype, vibt, vsweep, vdepth, vrate = data[o + 225:o + 239]
        fade = struct.unpack_from("<H", data, o + 239)[0]
        pos += isize
        heads = []
        for s in range(nsmp):
            length, lstart, llen, vol, fine, typ, pan, rel = struct.unpack_from("<IIIBbBBb", data, pos)
            heads.append((length, lstart, llen, vol, fine, typ, pan, rel, _cstr(data[pos + 18:pos + 40]), data[pos + 17]))
            pos += shsize
        first = len(mod.samples) + 1
        for length, lstart, llen, vol, fine, typ, pan, rel, name, res in heads:
            raw = data[pos:pos + length]
            pos += length
            smp = Sample(name=name[:25] or ins.name, volume=min(vol, 64), pan=round(pan * 64 / 255))
            mod.samples.append(smp)
            if res == 0xAD:
                warn("ADPCM-packed XM samples dropped")
                continue
            is16 = bool(typ & 16)
            if is16:
                vals, acc = [], 0
                for (d,) in struct.iter_unpack("<h", raw[:len(raw) // 2 * 2]):
                    acc = (acc + d + 32768) % 65536 - 32768
                    vals.append(acc)
                lstart, llen = lstart // 2, llen // 2
            else:
                vals, acc = [], 0
                for d in raw:
                    acc = (acc + d) % 256
                    vals.append(acc - 256 if acc > 127 else acc)
            if not vals:
                continue
            smp.data, smp.bits = [vals], 16 if is16 else 8
            smp.c5_speed = max(256, round(8363 * 2 ** ((rel * 128 + fine) / 1536)))
            if typ & 3 and llen > 0 and lstart < len(vals):
                smp.loop = Loop(lstart, min(len(vals), lstart + llen), (typ & 3) == 2)
            if vdepth or vrate:
                smp.vibrato_type, smp.vibrato_speed = XM_VIBRATO[vibt & 3], min(64, vrate)
                smp.vibrato_depth, smp.vibrato_rate = min(64, vdepth * 4), min(255, vsweep)
                if vibt & 3 == 3:
                    warn("XM ramp-up auto-vibrato played as ramp down")
        ins.keymap = [(k, first + keys[min(95, max(0, k - 12))] if keys[min(95, max(0, k - 12))] < nsmp else 0) for k in range(120)]
        ins.nna = 0
        ins.fadeout = min(256, (fade + XM_FADE - 1) // XM_FADE)
        if vtype & 1 and nv:
            ins.volume_envelope = _xm_env(venv, nv, vtype, vsus, vls, vle, 0)
        if ptype & 1 and np_:
            ins.panning_envelope = _xm_env(penv, np_, ptype, psus, pls, ple, -32)
    _orders(mod, table, npat)
    _xm_keyoffs(mod, warn)
    _split_long(mod, warn)
    _compact(mod, warn)
    return _finish(mod, warn)


def _split_long(mod, warn, size=192):
    """Patterns longer than IT's 200 rows as parts of `size` rows (a multiple of 16, so bars stay whole), played one after
    the other: the order list follows, a jump (Bxx) goes to where its order now starts, and a break (Cxx) that leaves a
    part early or lands past a part's end becomes a jump to the right part plus a break to the row in it (in a free effect
    slot of the row)."""
    if all(len(p.rows) <= 200 for p in mod.patterns):
        return
    parts, pats = {}, []
    for i, p in enumerate(mod.patterns):
        n = len(p.rows) if len(p.rows) <= 200 else size
        parts[i] = []
        for k in range(0, len(p.rows), n):
            parts[i].append(len(pats))
            pats.append(Pattern(p.name if n == len(p.rows) else f"{p.name}{chr(97 + k // n)}", p.rows[k:k + n]))
    orders, start = [], []
    for o in mod.orders:
        start.append(len(orders))
        orders.extend(parts[o] if o < ORDER_SKIP else [o])
    where = {}
    for pos, o in enumerate(mod.orders):
        where.setdefault(o, []).append(pos)
    for i in range(len(mod.patterns)):
        for k, pi in enumerate(parts[i]):
            for row in pats[pi].rows:
                for cell in row:
                    if cell.effect == fx("B") and cell.param < len(start):
                        cell.param = start[cell.param]
                    elif cell.effect == fx("C"):
                        pos = where.get(i, [])
                        nxt = (pos[0] + 1) % len(mod.orders) if len(pos) == 1 else None
                        long_next = nxt is not None and mod.orders[nxt] < ORDER_SKIP and len(parts[mod.orders[nxt]]) > 1
                        if k == len(parts[i]) - 1 and not (long_next and cell.param >= size):
                            continue
                        if nxt is None:
                            warn("a break in a split pattern played at several order positions kept as it is")
                            continue
                        into = cell.param // size if long_next else 0
                        target, r = start[nxt] + into, cell.param - into * size
                        cell.effect, cell.param = fx("B"), target
                        if r:
                            free = next((c for c in row if not c.effect), None)
                            if free is None:
                                warn("a break into a split pattern lands on row 0 (no free effect slot for the row)")
                            else:
                                free.effect, free.param = fx("C"), r
    warn(f"{sum(len(v) > 1 for v in parts.values())} patterns longer than 200 rows split into parts of {size}")
    mod.patterns, mod.orders = pats, orders


def _compact(mod, warn):
    """IT holds at most 99 instruments and 99 samples: past that, only what the patterns play is kept (renumbered), and
    what still does not fit goes with a warning."""
    cells = [c for p in mod.patterns for row in p.rows for c in row]
    if len(mod.instruments) > 99:
        used = sorted({c.instrument for c in cells if 0 < c.instrument <= len(mod.instruments)})
        if len(used) > 99:
            warn(f"{len(used) - 99} instruments past IT's 99 dropped")
        num = {old: k + 1 for k, old in enumerate(used[:99])}
        for c in cells:
            c.instrument = num.get(c.instrument, 0)
        mod.instruments = [mod.instruments[old - 1] for old in used[:99]]
    if len(mod.samples) > 99:
        used = sorted({s for ins in mod.instruments for _, s in ins.keymap if s})
        if len(used) > 99:
            warn(f"{len(used) - 99} samples past IT's 99 dropped")
        num = {old: k + 1 for k, old in enumerate(used[:99])}
        for ins in mod.instruments:
            ins.keymap = [(n, num.get(s, 0)) for n, s in ins.keymap]
        mod.samples = [mod.samples[old - 1] for old in used[:99]]


def _xm_keyoffs(mod, warn):
    """FT2 cuts a note at key-off when its instrument's volume envelope is off, where IT would let it play on: those
    key-offs become note cuts, following the instrument each channel plays along the order list (a pattern played under
    two instruments keeps what its first play needs)."""
    cur, done = [0] * len(mod.channels), {}
    for o in mod.orders:
        if o >= len(mod.patterns):
            continue
        for r, row in enumerate(mod.patterns[o].rows):
            for c, cell in enumerate(row):
                if cell.instrument:
                    cur[c] = cell.instrument
                key = (o, r, c)
                if key in done:
                    if cell.note in (NOTE_OFF, NOTE_CUT) and done[key] != (cur[c] and mod.instruments[cur[c] - 1].volume_envelope is None
                                                                        if cur[c] <= len(mod.instruments) else True):
                        warn("a key-off in a pattern played under instruments with and without envelopes follows the first")
                    continue
                if cell.note == NOTE_OFF:
                    ins = mod.instruments[cur[c] - 1] if 0 < cur[c] <= len(mod.instruments) else None
                    done[key] = ins is None or ins.volume_envelope is None
                    if done[key]:
                        cell.note = NOTE_CUT


def _pan4(v, warn):
    """An XM pan slide speed (256ths of the pan per tick) in IT's 64ths, at least 1."""
    if v % 4:
        warn("XM pan slides not a multiple of 4 rounded to IT's 64ths")
    return max(1, round(v / 4)) if v else 0


def _xm_env(pts, n, typ, sus, ls, le, shift):
    n = min(12, n)
    nodes = [(pts[2 * k], max(-32 if shift else 0, min(32 if shift else 64, pts[2 * k + 1] + shift))) for k in range(n)]
    env = Envelope(nodes)
    if typ & 2 and sus < n:
        env.sustain = (sus, sus)
    if typ & 4 and ls <= le < n:
        env.loop = (ls, le)
        if ls < le and nodes[le][0] - 1 > nodes[le - 1][0]:  # FT2 jumps back on reaching the loop end, IT a tick later
            nodes[le] = (nodes[le][0] - 1, nodes[le][1])
    return env


def _xm_cell(cell, note, ins, vol, eff, par, warn):
    if note == 97:
        cell.note = NOTE_OFF
    elif 1 <= note <= 96:
        cell.note = note - 1 + 12
    cell.instrument = ins
    if eff <= 0xF:
        _pt_effect(cell, eff, par, warn, "xm")
    else:
        x, y = par >> 4, par & 15
        L = {0x10: "V", 0x11: "W", 0x19: "P", 0x1B: "Q", 0x1D: "I"}.get(eff)
        if eff == 0x10:
            cell.effect, cell.param = fx("V"), min(0x80, 2 * par)
        elif eff == 0x11:
            cell.effect, cell.param = fx("W"), _slide(par)
        elif eff == 0x14:  # key off after xx ticks
            if cell.note is None:
                cell.note = NOTE_OFF
                if par:
                    cell.effect, cell.param = fx("S"), 0xD0 | min(15, par)
            else:
                warn("key-off (Kxx) on a row that has a note dropped")
        elif eff == 0x19:  # XM Pxy: x right, y left, in 256ths per tick; IT P0y right, Px0 left, in 64ths
            cell.effect, cell.param = fx("P"), _pan4(x, warn) if x else _pan4(y, warn) << 4
        elif L:
            cell.effect, cell.param = fx(L), par
        elif eff == 0x21 and x in (1, 2) and y:
            cell.effect, cell.param = fx("F" if x == 1 else "E"), 0xE0 | y
        else:
            warn(f"XM effect {chr(55 + eff) if eff >= 10 else eff}xx dropped")
    if 0x10 <= vol <= 0x50:
        if cell.volcmd is None:
            cell.volcmd = vol - 0x10
    elif vol >= 0x60:
        kind, v = vol >> 4, vol & 15
        free = not cell.effect
        if kind in (6, 7, 8, 9):  # slide down, up, fine down, fine up
            if free and v > 9:
                cell.effect, cell.param = fx("D"), {6: v, 7: v << 4, 8: 0xF0 | v, 9: (v << 4) | 0xF}[kind]
            else:
                cell.volcmd = {6: VOL_D, 7: VOL_C, 8: VOL_B, 9: VOL_A}[kind] + min(9, v)
        elif kind == 0xA:
            warn("XM volume-column vibrato speed dropped")
        elif kind == 0xB:
            if free and v > 9:
                cell.effect, cell.param = fx("H"), v
            else:
                cell.volcmd = VOL_H + min(9, v)
        elif kind == 0xC:
            cell.volcmd = VOL_P + 4 * v  # FT2 sets the pan to x * 16 of 256
        elif kind in (0xD, 0xE):
            if free:
                cell.effect, cell.param = fx("P"), (_pan4(v, warn) << 4) if kind == 0xD else _pan4(v, warn)
            else:
                warn("XM volume-column pan slide dropped (the effect column is busy)")
        elif kind == 0xF:
            if free:
                cell.effect, cell.param = fx("G"), v << 4
            else:
                cell.volcmd = VOL_G + min(range(10), key=lambda k: abs(G_SPEEDS[k] - (v << 4)))


# ---------------------------------------------------------------- any module

def match_level(mod, data, seconds=30):
    """Set `mod`'s mix volume so it plays as loud as the original `data` does in libopenmpt. libopenmpt mixes each format
    (and XMs by the tracker that saved them: FastTracker 2 and its clones, old ModPlug versions by channel count) at levels
    of its own that an IT's header cannot name, so the level is measured: both rendered for `seconds`, the median
    difference in dB over the 10 ms windows where either sounds, corrected by the mix volume (IT's 0-128). Returns the
    correction in dB (None without numpy or sound)."""
    try:
        import numpy as np
    except ImportError:
        return None
    from .itwriter import write_it
    from .openmpt import LoadedModule

    def db(d):
        with LoadedModule(d) as lm:
            x = np.frombuffer(lm.render(44100, oversample=1, max_seconds=seconds), "<i2").astype(float).reshape(-1, 2) / 32768
        e = (x ** 2).sum(axis=1)
        return 10 * np.log10(e[: len(e) // 441 * 441].reshape(-1, 441).mean(axis=1) + 1e-12)
    a, b = db(data), db(write_it(mod))
    n = min(len(a), len(b))
    loud = np.maximum(a[:n], b[:n]) > -50
    if not loud.any():
        return None
    diff = float(np.median(a[:n][loud] - b[:n][loud]))
    mod.mix_volume = max(1, min(128, round(mod.mix_volume * 10 ** (diff / 20))))
    return diff

def read_module(data: bytes):
    """IT, XM, S3M or MOD by the file's own signature -> (Module, warnings). A truncated or garbled file is a ModReadError
    (or the IT reader's ITReadError): no struct.error, IndexError or ValueError from inside a reader reaches the caller."""
    try:
        return _read_module(data)
    except (ITReadError, ModReadError):
        raise
    except (struct.error, IndexError, ValueError) as e:
        raise ModReadError(f"the file is truncated or malformed ({type(e).__name__}: {e})")


def _read_module(data: bytes):
    from .itreader import read_it
    if data[:4] == b"IMPM":
        return read_it(data)
    if data[:17] == b"Extended Module: ":
        return read_xm(data)
    if data[0x2C:0x30] == b"SCRM":
        return read_s3m(data)
    if len(data) >= 1084 and _mod_channels(data[1080:1084]):
        return read_mod(data)
    raise ModReadError("not an IT, XM, S3M or 31-sample MOD file")
