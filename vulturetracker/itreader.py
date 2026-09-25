""".it file -> Module, and Module -> song YAML + WAV files, so existing modules can be edited as text."""
import os
import re
import struct
from pathlib import Path

from . import notation
from .model import (Cell, Channel, Envelope, Instrument, Loop, Module, Pattern, Sample,
                    NOTE_FADE, ORDER_END, ORDER_SKIP)
from .song import DCA, DCT, NNA, VIBRATO
from .wavload import write_wav


class ITReadError(ValueError):
    pass


def _cstr(raw):
    text = raw.split(b"\0", 1)[0].decode("latin-1")
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in text).rstrip()


# ---------------------------------------------------------------- IT 2.14 / 2.15 sample decompression

def _decompress(data, pos, length, is16, it215):
    """Decode one channel of IT-compressed sample data. Returns (samples, new_pos)."""
    out = []
    full = 17 if is16 else 9
    block_frames = 0x4000 if is16 else 0x8000
    bits = 16 if is16 else 8
    while len(out) < length:
        if pos + 2 > len(data):
            raise ITReadError("compressed sample data is truncated")
        block_len = struct.unpack_from("<H", data, pos)[0]
        block = data[pos + 2: pos + 2 + block_len]
        pos += 2 + block_len
        bitpos = 0

        def read(n):
            nonlocal bitpos
            v = 0
            for i in range(n):
                byte = bitpos >> 3
                if byte < len(block) and block[byte] >> (bitpos & 7) & 1:
                    v |= 1 << i
                bitpos += 1
            return v

        width = full
        d1 = d2 = 0
        todo = min(block_frames, length - len(out))
        while todo:
            if bitpos > 8 * len(block):
                raise ITReadError("compressed sample block overrun")
            v = read(width)
            if width < 7:                              # method 1: 1..6 bits
                if v == 1 << (width - 1):
                    v = read(4 if is16 else 3) + 1
                    width = v if v < width else v + 1
                    continue
            elif width < full:                         # method 2: 7..16 (or 7..8) bits
                border = ((0xFFFF >> (17 - width)) - 8) if is16 else ((0xFF >> (9 - width)) - 4)
                if border < v <= border + (16 if is16 else 8):
                    v -= border
                    width = v if v < width else v + 1
                    continue
            else:                                      # method 3: full width
                if v & (1 << bits):
                    width = (v + 1) & 0xFF
                    if not 1 <= width <= full:
                        raise ITReadError("invalid bit width in compressed sample")
                    continue
            shift = max(0, bits - width)               # sign-extend a width-bit value
            v = (v << shift) & ((1 << bits) - 1)
            if v >= 1 << (bits - 1):
                v -= 1 << bits
            v >>= shift
            d1 = (d1 + v) & ((1 << bits) - 1)
            d2 = (d2 + d1) & ((1 << bits) - 1)
            s = d2 if it215 else d1
            out.append(s - (1 << bits) if s >= 1 << (bits - 1) else s)
            todo -= 1
    return out, pos


# ---------------------------------------------------------------- reading

def _read_envelope(data, off, signed):
    flags, num, lpb, lpe, slb, sle = struct.unpack_from("<6B", data, off)
    num = min(num, 25)
    nodes = []
    for i in range(num):
        value, tick = struct.unpack_from("<bH" if signed else "<BH", data, off + 6 + 3 * i)
        nodes.append((tick, value))
    return Envelope(nodes, bool(flags & 1),
                    (lpb, lpe) if flags & 2 else None,
                    (slb, sle) if flags & 4 else None,
                    bool(flags & 0x80) if signed else False,
                    bool(flags & 8))


def _read_samples_data(data, off, length, flags, cvt):
    is16 = bool(flags & 2)
    nch = 2 if flags & 4 else 1
    chans = []
    pos = off
    for _ in range(nch):
        if flags & 8:
            ch, pos = _decompress(data, pos, length, is16, bool(cvt & 4))
        else:
            width = 2 if is16 else 1
            raw = data[pos: pos + length * width]
            if len(raw) < length * width:
                raise ITReadError("sample data is truncated")
            pos += length * width
            if is16:
                ch = list(struct.unpack(("<" if not cvt & 2 else ">") + f"{length}h", raw))
            else:
                ch = list(struct.unpack(f"{length}b", raw))
            if not cvt & 1:  # unsigned
                half = 32768 if is16 else 128
                ch = [((v + half) & (2 * half - 1)) - half for v in ch]
            if cvt & 4:  # delta-encoded PCM
                acc, lim = 0, (1 << (16 if is16 else 8))
                for i, v in enumerate(ch):
                    acc = (acc + v) % lim
                    ch[i] = acc - lim if acc >= lim // 2 else acc
        chans.append(ch)
    return chans


def read_it(data: bytes):
    """Parse an .it file into a Module. Returns (module, warnings)."""
    warnings = []
    if data[:4] != b"IMPM" or len(data) < 0xC0:
        raise ITReadError("not an Impulse Tracker module (missing IMPM header)")
    mod = Module()
    mod.title = _cstr(data[4:30])[:25]
    mod.row_highlight = (data[0x1E], data[0x1F])
    ordnum, insnum, smpnum, patnum, cwtv, cmwt, flags, special = struct.unpack_from("<8H", data, 0x20)
    gv, mv, speed, tempo, sep, _pwd, msglen, msgoff = struct.unpack_from("<6BHI", data, 0x30)
    if flags & 4 and cmwt < 0x200:
        raise ITReadError("old (pre-IT 2.00) instrument format is not supported")
    if flags & 0x80 or special & 8:
        warnings.append("the module embeds MIDI macros; they are not carried over (Zxx/SFx use the default filter macros)")
    if cwtv >= 0x5000:
        warnings.append("saved by OpenMPT; OpenMPT-only extensions (swing, extra instrument properties, "
                        "playback compatibility flags) are not carried over")
    mod.global_volume, mod.mix_volume, mod.separation = min(gv, 128), min(mv, 128), min(sep, 128)
    mod.speed, mod.tempo = max(speed, 1), max(tempo, 32)
    mod.linear_slides, mod.old_effects, mod.compatible_gxx = bool(flags & 8), bool(flags & 16), bool(flags & 32)
    if special & 1 and msglen and msgoff:
        mod.message = data[msgoff: msgoff + msglen].split(b"\0", 1)[0].decode("latin-1").replace("\r", "\n")
    chnpan, chnvol = data[0x40:0x80], data[0x80:0xC0]

    pos = 0xC0
    orders = list(data[pos: pos + ordnum])
    pos += ordnum
    ins_ptrs = struct.unpack_from(f"<{insnum}I", data, pos)
    pos += 4 * insnum
    smp_ptrs = struct.unpack_from(f"<{smpnum}I", data, pos)
    pos += 4 * smpnum
    pat_ptrs = struct.unpack_from(f"<{patnum}I", data, pos)

    for p in smp_ptrs:
        smp = Sample()
        if p == 0 or p + 0x50 > len(data):
            mod.samples.append(smp)
            continue
        (sflags, vol) = data[p + 0x12], data[p + 0x13]
        smp.global_volume = min(data[p + 0x11], 64)
        smp.volume = min(vol, 64)
        smp.name = _cstr(data[p + 0x14: p + 0x2E])[:25]
        smp.filename = _cstr(data[p + 4: p + 0x10])
        cvt, dfp = data[p + 0x2E], data[p + 0x2F]
        smp.pan = min(dfp & 0x7F, 64) if dfp & 0x80 else None
        length, lb, le, c5, sb, se, ptr = struct.unpack_from("<7I", data, p + 0x30)
        smp.vibrato_speed, smp.vibrato_depth, smp.vibrato_rate, smp.vibrato_type = data[p + 0x4C: p + 0x50]
        smp.vibrato_speed, smp.vibrato_depth = min(smp.vibrato_speed, 64), min(smp.vibrato_depth, 64)
        smp.vibrato_type &= 3
        smp.c5_speed = c5 if c5 >= 256 else 8363
        if sflags & 1 and length:
            smp.bits = 16 if sflags & 2 else 8
            try:
                smp.data = _read_samples_data(data, ptr, length, sflags, cvt)
            except (ITReadError, struct.error) as e:
                warnings.append(f"sample {len(mod.samples) + 1} '{smp.name}': {e}; left empty")
                smp.data = []
            if sflags & 0x10 and lb < le <= length:
                smp.loop = Loop(lb, le, bool(sflags & 0x40))
            if sflags & 0x20 and sb < se <= length:
                smp.sustain_loop = Loop(sb, se, bool(sflags & 0x80))
        mod.samples.append(smp)

    if flags & 4:
        mod.instruments = []
        for p in ins_ptrs:
            ins = Instrument()
            if p == 0 or p + 554 > len(data):
                mod.instruments.append(ins)
                continue
            ins.filename = _cstr(data[p + 4: p + 0x10])
            ins.nna, ins.dct, ins.dca = min(data[p + 0x11], 3), min(data[p + 0x12], 3), min(data[p + 0x13], 2)
            fadeout, pps, ppc, gbv, dfp, rv, rp = struct.unpack_from("<HbBBBBB", data, p + 0x14)
            if fadeout > 256:
                warnings.append(f"instrument {len(mod.instruments) + 1}: fadeout {fadeout} clamped to 256")
            ins.fadeout = min(fadeout, 256)
            ins.pitch_pan_separation, ins.pitch_pan_center = max(-32, min(32, pps)), min(ppc, 119)
            ins.global_volume = min(gbv, 128)
            ins.pan = min(dfp, 64) if not dfp & 0x80 else None
            ins.random_volume, ins.random_pan = min(rv, 100), min(rp, 64)
            ins.name = _cstr(data[p + 0x20: p + 0x3A])[:25]
            ifc, ifr = data[p + 0x3A], data[p + 0x3B]
            ins.filter_cutoff = ifc & 0x7F if ifc & 0x80 else None
            ins.filter_resonance = ifr & 0x7F if ifr & 0x80 else None
            ins.keymap = [(min(data[p + 0x40 + 2 * i], 119), data[p + 0x41 + 2 * i]) for i in range(120)]
            ins.volume_envelope = _read_envelope(data, p + 0x130, False)
            ins.panning_envelope = _read_envelope(data, p + 0x182, True)
            ins.pitch_envelope = _read_envelope(data, p + 0x1D4, True)
            mod.instruments.append(ins)

    max_ch = 0
    for p in pat_ptrs:
        if p == 0:
            mod.patterns.append(None)
            continue
        plen, rows = struct.unpack_from("<HH", data, p)
        if not 1 <= rows <= 1024:  # libopenmpt drops such a pattern too; and 65535 rows would be a 500 MB grid
            warnings.append(f"pattern {len(mod.patterns)}: {rows} rows is not a valid IT pattern; left empty")
            mod.patterns.append(None)
            continue
        pd = data[p + 8: p + 8 + plen]
        grid = [[Cell() for _ in range(64)] for _ in range(rows)]
        masks = [0] * 64
        last = [Cell() for _ in range(64)]
        i = row = 0
        while row < rows and i < len(pd):
            cv = pd[i]
            i += 1
            if cv == 0:
                row += 1
                continue
            ch = (cv - 1) & 63
            if cv & 0x80:
                masks[ch] = pd[i]
                i += 1
            m = masks[ch]
            c = grid[row][ch]
            if m & 1:
                last[ch].note = pd[i]
                i += 1
            if m & 2:
                last[ch].instrument = pd[i]
                i += 1
            if m & 4:
                last[ch].volcmd = pd[i]
                i += 1
            if m & 8:
                last[ch].effect, last[ch].param = pd[i], pd[i + 1]
                i += 2
            if m & 0x11:
                c.note = last[ch].note
            if m & 0x22:
                c.instrument = last[ch].instrument
            if m & 0x44:
                c.volcmd = last[ch].volcmd
            if m & 0x88:
                c.effect, c.param = last[ch].effect, last[ch].param
            if m & 0x0F or m & 0xF0:
                max_ch = max(max_ch, ch + 1)
        mod.patterns.append(Pattern(f"p{len(mod.patterns):02d}", grid))

    num_ch = max(max_ch, 1)
    for idx, pat in enumerate(mod.patterns):
        if pat is None:  # a zero pointer means an empty 64-row pattern
            mod.patterns[idx] = Pattern(f"p{idx:02d}", [[Cell() for _ in range(num_ch)] for _ in range(64)])
        else:
            pat.rows = [r[:num_ch] for r in pat.rows]
    for ch in range(num_ch):
        pan = chnpan[ch]
        mod.channels.append(Channel(f"Ch {ch + 1}", 100 if pan & 0x7F == 100 else min(pan & 0x7F, 64),
                                    min(chnvol[ch], 64), bool(pan & 0x80)))

    while orders and orders[-1] == ORDER_END:
        orders.pop()
    for o in orders:
        if o < 200 and o >= len(mod.patterns):
            while len(mod.patterns) <= o:
                mod.patterns.append(Pattern(f"p{len(mod.patterns):02d}", [[Cell() for _ in range(num_ch)] for _ in range(64)]))
    mod.orders = [o for o in orders if o < 200 or o in (ORDER_SKIP, ORDER_END)]
    _sanitize(mod, warnings)
    return mod, warnings


def _sanitize(mod, warnings):
    """Drop what the song format can't express, with a warning for each kind."""
    dropped = {}
    for pat in mod.patterns:
        for row in pat.rows:
            for cell in row:
                if cell.note is not None and 120 <= cell.note < 254 and cell.note != NOTE_FADE:
                    cell.note = NOTE_FADE
                if cell.volcmd is not None:
                    try:
                        notation.format_volcmd(cell.volcmd)
                    except notation.NotationError:
                        dropped["volume column bytes outside IT's ranges"] = dropped.get("volume column bytes outside IT's ranges", 0) + 1
                        cell.volcmd = None
                letter = chr(64 + cell.effect) if 1 <= cell.effect <= 26 else ""
                if cell.effect > 26 or (cell.effect == 0 and cell.param):
                    dropped["non-IT effect commands"] = dropped.get("non-IT effect commands", 0) + 1
                    cell.effect = cell.param = 0
                elif (letter == "V" and cell.param > 0x80) or (letter == "M" and cell.param > 0x40)                         or (letter == "B" and cell.param >= len(mod.orders)) or (letter == "C" and cell.param >= 200):
                    key = f"out-of-range {letter}xx effects (IT ignores them)"
                    dropped[key] = dropped.get(key, 0) + 1
                    cell.effect = cell.param = 0
    for what, n in dropped.items():
        warnings.append(f"dropped {n} {what}")
    for i, ins in enumerate(mod.instruments or []):
        for env in (ins.volume_envelope, ins.panning_envelope, ins.pitch_envelope):
            if env is None:
                continue
            fixed = False
            for j in range(1, len(env.nodes)):
                if env.nodes[j][0] <= env.nodes[j - 1][0]:
                    env.nodes[j] = (env.nodes[j - 1][0] + 1, env.nodes[j][1])
                    fixed = True
            if env.nodes and env.nodes[0][0] != 0:
                env.nodes[0] = (0, env.nodes[0][1])
                fixed = True
            n = len(env.nodes)
            for attr in ("loop", "sustain"):
                v = getattr(env, attr)
                if v and not (0 <= v[0] <= v[1] < n):
                    setattr(env, attr, None)
                    fixed = True
            if fixed:
                warnings.append(f"instrument {i + 1} '{ins.name}': repaired an envelope (non-increasing ticks or bad loop points)")


# ---------------------------------------------------------------- Module -> song dict

def _keymap_entries(ins, sample_ok):
    """Compress the 120-entry note table into ranges: runs with a constant transpose, or runs that
    all play one fixed note (drum-kit style), whichever is longer."""
    km = ins.keymap
    out = []
    n = 0
    while n < 120:
        note, smp = km[n]
        if not smp or not sample_ok(smp):
            n += 1
            continue
        t = note - n
        end_t = n + 1
        while end_t < 120 and km[end_t][1] == smp and km[end_t][0] - end_t == t:
            end_t += 1
        end_f = n + 1
        while end_f < 120 and km[end_f] == (note, smp):
            end_f += 1
        end = max(end_t, end_f)
        rng = notation.format_note(n) if end - n == 1 else f"{notation.format_note(n)}..{notation.format_note(end - 1)}"
        e = {"notes": rng, "sample": smp}
        if end_f > end_t:
            e["play_note"] = notation.format_note(note)
        elif t:
            e["transpose"] = t
        out.append(e)
        n = end
    return out


def _env_dict(env, default_value):
    if env is None or not env.nodes:
        return None
    # IT stores a flat two-node envelope even when unused; skip those.
    if not env.enabled and all(v == default_value for _, v in env.nodes) and not env.loop and not env.sustain:
        return None
    d = {"nodes": [[t, v] for t, v in env.nodes]}
    if env.sustain:
        d["sustain"] = env.sustain[0] if env.sustain[0] == env.sustain[1] else list(env.sustain)
    if env.loop:
        d["loop"] = list(env.loop)
    if not env.enabled:
        d["enabled"] = False
    if env.carry:
        d["carry"] = True
    if env.filter:
        d["filter"] = True
    return d


def _loop_dict(loop):
    d = {"start": loop.start, "end": loop.end}
    if loop.pingpong:
        d["type"] = "pingpong"
    return d


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:24] or "sample"


def module_to_song(mod: Module, song_path, samples_dir) -> dict:
    """Write each sample as a WAV and return the song dict (paths relative to song_path)."""
    song_path, samples_dir = Path(song_path), Path(samples_dir)
    samples_dir.mkdir(parents=True, exist_ok=True)
    rel = Path(os.path.relpath(samples_dir.resolve(), song_path.resolve().parent))

    module = {"title": mod.title, "tempo": mod.tempo, "speed": mod.speed,
              "global_volume": mod.global_volume, "mix_volume": mod.mix_volume}
    if mod.separation != 128:
        module["separation"] = mod.separation
    if not mod.linear_slides:
        module["linear_slides"] = False
    if mod.old_effects:
        module["old_effects"] = True
    if mod.compatible_gxx:
        module["compatible_gxx"] = True
    chans = []
    for ch in mod.channels:
        c = {"name": ch.name, "pan": "surround" if ch.pan == 100 else ch.pan}
        if ch.volume != 64:
            c["volume"] = ch.volume
        if ch.muted:
            c["muted"] = True
        chans.append(c)
    module["channels"] = chans
    if mod.message:
        module["message"] = mod.message

    used = {c.instrument for p in mod.patterns for row in p.rows for c in row if c.instrument}
    if mod.instruments is None:
        used_samples = used
    else:
        used_samples = {s for ins in mod.instruments for _, s in ins.keymap if s}
        while len(mod.instruments) < max(used, default=0):
            mod.instruments.append(Instrument())  # patterns may name instruments past the end
    while len(mod.samples) < max(used_samples, default=0):
        mod.samples.append(Sample())
    samples = {}
    for i, smp in enumerate(mod.samples, 1):
        if not smp.data:
            if smp.name or i in used_samples:
                samples[i] = {"name": smp.name}  # empty slot (IT files often use sample names as text)
            continue
        fname = f"{i:02d}_{_safe(smp.name or smp.filename)}.wav"
        write_wav(samples_dir / fname, smp.c5_speed, smp.data, smp.bits)
        s = {"file": (rel / fname).as_posix(), "name": smp.name}
        if smp.volume != 64:
            s["volume"] = smp.volume
        if smp.global_volume != 64:
            s["global_volume"] = smp.global_volume
        if smp.pan is not None:
            s["pan"] = smp.pan
        if smp.loop:
            s["loop"] = _loop_dict(smp.loop)
        if smp.sustain_loop:
            s["sustain_loop"] = _loop_dict(smp.sustain_loop)
        if smp.vibrato_depth or smp.vibrato_speed or smp.vibrato_rate:
            s["vibrato"] = {"type": list(VIBRATO)[smp.vibrato_type], "speed": smp.vibrato_speed,
                            "depth": smp.vibrato_depth, "rate": smp.vibrato_rate}
        if len(smp.data) == 2:
            s["stereo"] = True
        samples[i] = s

    song = {"module": module, "samples": samples}
    if mod.instruments is not None:
        insts = {}
        names = {v: k for k, v in NNA.items()}, {v: k for k, v in DCT.items()}, {v: k for k, v in DCA.items()}
        for i, ins in enumerate(mod.instruments, 1):
            d = {"name": ins.name}
            km = _keymap_entries(ins, lambda s: s <= len(mod.samples) and s in samples)
            if len(km) == 1 and km[0]["notes"] == "C-0..B-9" and set(km[0]) == {"notes", "sample"}:
                d["sample"] = km[0]["sample"]
            elif km:
                d["keymap"] = km
            elif not ins.name and i not in used:
                continue  # unused empty slot
            if ins.fadeout:
                d["fadeout"] = ins.fadeout
            d["nna"] = names[0][ins.nna]
            if ins.dct:
                d["dct"] = names[1][ins.dct]
                d["dca"] = names[2][ins.dca]
            if ins.global_volume != 128:
                d["global_volume"] = ins.global_volume
            if ins.pan is not None:
                d["pan"] = ins.pan
            if ins.pitch_pan_separation:
                d["pitch_pan_separation"] = ins.pitch_pan_separation
                d["pitch_pan_center"] = notation.format_note(ins.pitch_pan_center)
            if ins.random_volume:
                d["random_volume"] = ins.random_volume
            if ins.random_pan:
                d["random_pan"] = ins.random_pan
            if ins.filter_cutoff is not None:
                d["filter_cutoff"] = ins.filter_cutoff
            if ins.filter_resonance is not None:
                d["filter_resonance"] = ins.filter_resonance
            for key, env, default in (("volume_envelope", ins.volume_envelope, 64),
                                      ("panning_envelope", ins.panning_envelope, 0),
                                      ("pitch_envelope", ins.pitch_envelope, 0)):
                e = _env_dict(env, default)
                if e:
                    d[key] = e
            insts[i] = d
        song["instruments"] = insts

    patterns = {}
    for pat in mod.patterns:
        lines = [f"{r:02d}: " + " | ".join(notation.format_cell(c) for c in row) for r, row in enumerate(pat.rows)]
        while lines and all(c.is_empty() for c in pat.rows[len(lines) - 1]):
            lines.pop()
        patterns[pat.name] = {"rows": len(pat.rows), "data": "\n".join(lines) + "\n" if lines else ""}
    song["patterns"] = patterns
    song["orders"] = [{ORDER_SKIP: "+++", ORDER_END: "---"}.get(o) or mod.patterns[o].name for o in mod.orders]
    return song


def import_it(it_path, song_path, samples_dir):
    """Convert a module (.it, or .xm / .s3m / .mod through modreader, told apart by their headers) to a song YAML plus
    WAVs. Returns (song dict, warnings)."""
    from .api import save
    from .modreader import match_level, read_module
    data = Path(it_path).read_bytes()
    mod, warnings = read_module(data)
    if data[:4] != b"IMPM":
        want = mod.mix_volume
        diff = match_level(mod, data)
        if diff is not None and abs(diff) > 0.5 and mod.mix_volume in (1, 128):
            warnings.append(f"the level is {diff:+.1f} dB from libopenmpt's and the mix volume stops at {mod.mix_volume}")
        elif diff is not None and mod.mix_volume != want:
            warnings.append(f"mix volume {mod.mix_volume}: the level libopenmpt plays the original at ({diff:+.1f} dB)")
    song = module_to_song(mod, song_path, samples_dir)
    header = f"# Imported from {Path(it_path).name} by vulturetracker import\n"
    for w in warnings:
        header += f"# import warning: {w}\n"
    save(song, song_path)
    Path(song_path).write_text(header + Path(song_path).read_text(encoding="utf-8"), encoding="utf-8")
    return song, warnings
