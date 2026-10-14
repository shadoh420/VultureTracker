"""SoundFont 2 presets and Gravis UltraSound patches (.pat) as one IT instrument, read the way OpenMPT's own loaders
read them (soundlib/Dlsbank.cpp: UpdateSF2PresetData, ConvertSF2ToDLS, ExtractInstrument, ExtractSample,
Envelope::ConvertToMPT; soundlib/SampleFormats.cpp: ReadPATInstrument, PatchToSample). The files are parsed with struct;
the instrument becomes a Module (one instrument, its zones as samples) that itreader.module_to_song writes as WAVs and a
song entry, the same path a module import takes.

Where OpenMPT has no rule VultureTracker sets its own, named in GUIDE.md's "Following OpenMPT": velocity layers (OpenMPT
ignores the velocity range, so the first of two zones on one key range wins; here the zones that sound at the highest
velocity are kept), and a drum kit (bank 128) is one instrument with every key, where OpenMPT extracts one per key."""
import copy
import math
import struct
from dataclasses import dataclass, field

from .model import Cell, Channel, Envelope, Instrument, Loop, Module, Pattern, Sample


class SF2Error(ValueError):
    pass


# generator operators (SoundFont 2.04 section 8.1.2), the ones OpenMPT reads, plus the velocity range
START_LOOP_FINE, END_LOOP_FINE, MODENV_TO_PITCH, PAN = 2, 3, 7, 17
DELAY_MOD, ATTACK_MOD, HOLD_MOD, DECAY_MOD, SUSTAIN_MOD, RELEASE_MOD = 25, 26, 27, 28, 29, 30
DELAY_VOL, ATTACK_VOL, HOLD_VOL, DECAY_VOL, SUSTAIN_VOL, RELEASE_VOL = 33, 34, 35, 36, 37, 38
INSTRUMENT, KEY_RANGE, VEL_RANGE, START_LOOP_COARSE, ATTENUATION, END_LOOP_COARSE = 41, 43, 44, 45, 48, 50
COARSE_TUNE, FINE_TUNE, SAMPLE_ID, SAMPLE_MODES, SCALE_TUNING, UNITY_NOTE = 51, 52, 53, 54, 56, 58


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def _s8(v):
    v &= 0xFF
    return v - 0x100 if v & 0x80 else v


def _trunc_div(a, c):  # C's integer division (toward zero), as OpenMPT's Util::muldiv
    q = abs(a) // abs(c)
    return q if (a >= 0) == (c > 0) else -q


def _muldiv(a, b, c):
    return _trunc_div(a * b, c)


def _muldivr(a, b, c):
    return _trunc_div(a * b + c // 2, c)


def _time(amount):
    """SF2 timecents to OpenMPT's 20 ms envelope units (SF2TimeToDLS)."""
    ms = int(min(1000.0 * 2.0 ** (_s16(amount) / 1200.0), 32767))
    return min(max(ms, 20), 20000) // 20


def _sustain(amount):
    """SF2 sustain (0.1% attenuation steps) to 0..128 (SF2SustainLevelToLinear)."""
    return 128 * (1000 - min(amount, 1000)) // 1000  # the unsigned 16-bit amount, as OpenMPT reads it


def _gain_to_linear(cb):  # DLS32BitRelativeGainToLinear: 0 dB = 0x10000
    return int(65536.0 * 10.0 ** (cb / (200 * 65536.0)))


def _linear_to_gain(lin):  # DLS32BitRelativeLinearToGain
    return -960 * 65536 if lin <= 0 else int(200 * 65536.0 * math.log10(lin / 65536.0))


@dataclass
class _Env:
    delay: int = 0
    attack: int = 0
    hold: int = 0
    decay: int = 0
    release: int = 0
    sustain: int = 128


@dataclass
class _Envs:
    vol: _Env = field(default_factory=_Env)
    pitch: _Env = field(default_factory=_Env)
    pitch_depth: int = 0
    pan: int = 128

    def apply(self, oper, amount):  # SFGenList::ApplyToEnvelope
        v, p = self.vol, self.pitch
        if oper == DELAY_VOL: v.delay = _time(amount)
        elif oper == ATTACK_VOL: v.attack = _time(amount)
        elif oper == HOLD_VOL: v.hold = _time(amount)
        elif oper == DECAY_VOL: v.decay = _time(amount)
        elif oper == SUSTAIN_VOL: v.sustain = _sustain(amount)
        elif oper == RELEASE_VOL: v.release = _time(amount)
        elif oper == DELAY_MOD: p.delay = _time(amount)
        elif oper == ATTACK_MOD: p.attack = _time(amount)
        elif oper == HOLD_MOD: p.hold = _time(amount)
        elif oper == DECAY_MOD: p.decay = _time(amount)
        elif oper == SUSTAIN_MOD: p.sustain = _sustain(amount)
        elif oper == RELEASE_MOD: p.release = _time(amount)
        elif oper == MODENV_TO_PITCH: self.pitch_depth = _s16(amount)


def _to_envelope(e, pitch=False, scale=3200):
    """Envelope::ConvertToMPT with tempoScale 1 (IT's classic tempo mode: a tick of 20 ms at tempo 125). Returns
    (nodes, sustain index, fadeout in OpenMPT's units or None), or None where OpenMPT leaves the envelope off."""
    if not e.attack and e.decay >= 1000 and (not e.sustain and not pitch) and e.release >= 1000:
        return None
    sc = lambda t: max(round(t), 1)  # ScaleEnvelope
    neutral = 32 if pitch else 0
    clamp = lambda v: max(0, min(255, v))
    nodes = []
    start = 0
    if e.delay:
        nodes.append((0, neutral))
        start = sc(e.delay)
    peak = clamp(neutral + _muldivr(64, scale, 3200))
    if e.attack:
        nodes.append((start, clamp(peak // (e.attack // 2 + 2) + 8)))
        nodes.append((start + sc(e.attack), peak))
    else:
        nodes.append((start, peak))
    hold_tick = start + sc(e.attack + e.hold)
    if e.hold > 0 and hold_tick > nodes[-1][0]:
        nodes.append((hold_tick, peak))
    if e.sustain > 0 or pitch:
        if e.sustain < 128:
            t0 = nodes[-1][0]
            level = -_linear_to_gain(e.sustain << 9) // 65536
            decay_time = 1
            if level > 0:
                decay_time = level * e.decay // 960
                for i in range(7):
                    f = 128 - (1 << i)
                    if f <= e.sustain:
                        break
                    lev = -_linear_to_gain(f << 9) // 65536
                    if lev > 0:
                        lt = lev * e.decay // 960
                        if 1 < lt < decay_time:
                            tick = t0 + sc(lt)
                            if tick > nodes[-1][0]:
                                nodes.append((tick, clamp(neutral + _muldivr(f, scale, 6400))))
            end = t0 + sc(decay_time)
            if end > nodes[-1][0]:
                nodes.append((end, clamp(neutral + _muldivr(e.sustain + 1, scale, 6400))))
    else:
        nodes.append((nodes[-1][0] + 1, nodes[-1][1]))
    sustain = len(nodes) - 1
    fadeout = None
    last_neutral = nodes[-1][1] > 1 and nodes[-1][1] == neutral
    if e.release and nodes[-1][1] > 1 and not last_neutral:
        release = e.release
        t0, f0 = nodes[-1]
        level = -_linear_to_gain(f0 << 10) // 65536
        decay_end = release * level // 960
        release -= decay_end
        prev = f0
        for i in range(7):
            f = 1 + ((f0 * 3) >> (i + 2))
            if f < 1 or (f == 1 and prev == 1) or f >= f0:
                continue
            prev = f
            lev = -_linear_to_gain(f << 10) // 65536
            if lev > 0:
                lt = e.release * lev // 960 - decay_end
                if 1 < lt < release:
                    tick = t0 + sc(lt)
                    if tick > nodes[-1][0]:
                        nodes.append((tick, clamp(neutral + _muldivr(f, scale, 3200))))
                        if nodes[-1][1] == neutral:
                            break
        ticks = sc(max(release, 1))
        nodes.append((t0 + ticks, neutral))
        fadeout = 32768 // ticks
    elif not last_neutral:
        nodes.append((nodes[-1][0] + 1, neutral))
    return nodes, sustain, fadeout


# ---------------------------------------------------------------- the RIFF

def _chunks(data, pos, end):
    while pos + 8 <= end:
        cid, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
        yield cid, pos + 8, min(size, end - pos - 8)
        pos += 8 + size + (size & 1)


def _records(data, off, size, fmt):
    n = struct.calcsize(fmt)
    return [struct.unpack_from(fmt, data, off + k * n) for k in range(size // n)]


def _name(raw):
    return raw.split(b"\0", 1)[0].decode("latin-1").strip()


def read_sf2(data):
    """The bank's tables: {version, presets [(name, preset, bank, first bag, bag count)], pbag, pgen, inst, ibag, igen,
    shdr, smpl (offset, size)}. Raises SF2Error for anything that is no SoundFont 2."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"sfbk":
        raise SF2Error("not a SoundFont 2 bank (no RIFF sfbk header)")
    sf = {"version": (2, 0), "smpl": (0, 0)}
    for cid, off, size in _chunks(data, 12, len(data)):
        if cid != b"LIST" or size < 4:
            continue
        kind = data[off:off + 4]
        for sub, soff, ssize in _chunks(data, off + 4, off + size):
            if kind == b"INFO" and sub == b"ifil" and ssize >= 4:
                sf["version"] = struct.unpack_from("<HH", data, soff)
            elif kind == b"sdta" and sub == b"smpl":
                sf["smpl"] = (soff, ssize)
            elif kind == b"pdta":
                fmt = {b"phdr": "<20sHHHIII", b"pbag": "<HH", b"pgen": "<HH", b"inst": "<20sH", b"ibag": "<HH",
                       b"igen": "<HH", b"shdr": "<20sIIIIIBbHH"}.get(sub)
                if fmt:
                    sf[sub.decode()] = _records(data, soff, ssize, fmt)
    for k in ("phdr", "pbag", "pgen", "inst", "ibag", "igen", "shdr"):
        if not sf.get(k):
            raise SF2Error(f"not a SoundFont 2 bank: its {k} table is missing or empty")
    if sf["version"][0] >= 3:
        raise SF2Error(f"SoundFont {sf['version'][0]} (compressed samples) is not read: convert it to SF2 first")
    ph = sf["phdr"]
    sf["presets"] = [(_name(p[0]), p[1] & 0x7F, p[2], p[3], nxt[3] - p[3] if nxt[3] > p[3] else 1)
                     for p, nxt in zip(ph, ph[1:])]
    return sf


def presets(data):
    """[(bank, preset, name)] sorted by bank and preset, as the app's preset list and `import --preset` show them."""
    return sorted((b, p, n) for n, p, b, _, _ in read_sf2(data)["presets"])


# ---------------------------------------------------------------- one preset

@dataclass
class _Region:
    lo: int = 0
    hi: int = 127
    vlo: int = 0
    vhi: int = 127
    unity: int | None = None
    fine: int = 0           # 1/128 semitone
    tuning: int = 100
    pan: int | None = None  # 0..256
    wave: int | None = None
    loop_start: int = 0
    loop_end: int = 0
    mode: int = 0           # 0 none, 1 loop, 2 ping-pong, 3 loop + sustain loop
    volume: int = 256       # 16..256
    env: _Envs | None = None

    @property
    def dummy(self):
        return self.lo == 0xFF or self.wave is None


def _intersect(lo, hi, amount):
    a, b = amount & 0xFF, amount >> 8
    if a > b:
        a, b = b, a
    lo, hi = max(lo, a), min(hi, b)
    return (lo, hi) if lo <= hi else (0xFF, 0xFF)


def _regions(sf, entry):
    """ConvertSF2ToDLS for one preset: its zones with the preset's and the instrument's global zone applied, plus the
    preset's shared envelope (melodic) or the kit's envelope (drums)."""
    _, _, bank, bag0, nbags = entry
    drums = bank >= 128
    pbag, pgen, inst, ibag, igen, shdr = (sf[k] for k in ("pbag", "pgen", "inst", "ibag", "igen", "shdr"))
    pairs, env, attn, fine = [], _Envs(), 0, 0
    for b in range(bag0, min(bag0 + nbags, len(pbag) - 1)):
        key = vel = None
        for oper, amount in pgen[pbag[b][0]:pbag[b + 1][0]]:
            v = _s16(amount)
            if oper == INSTRUMENT:
                if (amount, key, vel) not in pairs:
                    pairs.append((amount, key, vel))
                key = vel = None
            elif oper == KEY_RANGE:
                key = amount
            elif oper == VEL_RANGE:  # not read by OpenMPT; kept to choose the velocity layer
                vel = amount
            elif oper == ATTENUATION:
                attn = -v
            elif oper == COARSE_TUNE:
                fine += v * 128
            elif oper == FINE_TUNE:
                fine += _muldiv(_s8(v), 128, 100)
            else:
                env.apply(oper, amount)
    kit_env = copy.deepcopy(env)
    out = []
    for ins, key, vel in pairs:
        if ins >= len(inst) - 1:
            continue
        g = _Region(fine=fine)
        if key is not None:
            g.lo, g.hi = _intersect(0, 127, key)
        if vel is not None:
            g.vlo, g.vhi = _intersect(0, 127, vel)
        for r in range(inst[ins][1], inst[ins + 1][1]):
            if r + 1 >= len(ibag):
                break
            rgn = copy.copy(g)
            if drums:
                rgn.env = copy.deepcopy(g.env or env)
            target = rgn.env if drums else env
            region_attn, last, ls, le = 0, SAMPLE_ID, 0, 0
            for oper, amount in igen[ibag[r][0]:ibag[r + 1][0]]:
                last = oper
                v = _s16(amount)
                if oper == KEY_RANGE:
                    if rgn.lo != 0xFF:
                        rgn.lo, rgn.hi = _intersect(rgn.lo, rgn.hi, amount)
                elif oper == VEL_RANGE:
                    rgn.vlo, rgn.vhi = _intersect(rgn.vlo, rgn.vhi, amount)
                elif oper == UNITY_NOTE:
                    if amount < 128:
                        rgn.unity = amount
                elif oper == PAN:
                    rgn.pan = min(max(_muldivr(v + 500, 256, 1000), 0), 256)
                    target.pan = min(rgn.pan, 255)
                elif oper == ATTENUATION:
                    region_attn = -v
                elif oper == SAMPLE_ID:
                    if amount < len(shdr):
                        s = shdr[amount]
                        start, end, sl, el = s[1], s[2], s[3], s[4]
                        loop = (sl - start, el - start) if el > sl + 7 and sl >= start else (0, 0)
                        rgn.wave, rgn.loop_start, rgn.loop_end = amount, max(0, loop[0] + ls), max(0, loop[1] + le)
                elif oper == SAMPLE_MODES:
                    rgn.mode = amount & 3
                elif oper == COARSE_TUNE:
                    rgn.fine += v * 128
                elif oper == FINE_TUNE:
                    rgn.fine += _muldiv(_s8(v), 128, 100)
                elif oper == SCALE_TUNING:
                    rgn.tuning = min(max(amount, 0), 255)
                elif oper == START_LOOP_FINE:
                    ls += v
                elif oper == END_LOOP_FINE:
                    le += v
                elif oper == START_LOOP_COARSE:
                    ls += v * 32768
                elif oper == END_LOOP_COARSE:
                    le += v * 32768
                else:
                    target.apply(oper, amount)
            rgn.volume = min(max(_gain_to_linear(_trunc_div((attn + region_attn) * 65536, 10)) // 256, 16), 256)
            if last != SAMPLE_ID and r == inst[ins][1]:
                g = rgn
                if drums:
                    kit_env = rgn.env
            elif not rgn.dummy:
                out.append(rgn)
    return out, (kit_env if drums else env), drums


def _wave(sf, data, num):
    """Sample `num`'s frames as 16-bit ints (OpenMPT reads the 16-bit words only; sm24 is ignored) and its header."""
    name, start, end, *_rest, kind = sf["shdr"][num]
    off, size = sf["smpl"]
    if (kind & 0x7FCF) > 8 or kind & 0x10 or end < start + 4:
        return None
    a, b = off + 2 * start, min(off + 2 * end, off + size)
    if b <= a:
        return None
    return list(struct.unpack_from(f"<{(b - a) // 2}h", data, a))


def _patch_note(freq):  # PatchFreqToNote: a GF1 frequency (mHz) as OpenMPT's note number (middle C = 84)
    return math.log(freq / 2044.0) * 12.0 / math.log(2.0)


def _patch_key(freq):
    """The key (C-5 = 60) a GF1 frequency sounds at. OpenMPT compares its keys with _patch_note's numbers, two octaves
    above the pitch it tunes the sample to (middle C plays on C-5): here the ranges sit where they sound."""
    return math.floor(_patch_note(freq) + 0.5) - 24


def pat_module(data):
    """A GUS patch (.pat) as a Module with one instrument, as OpenMPT's ReadPATInstrument reads it: the first layer's
    samples, each over the keys between its low and high frequency (its root key always; the keys two octaves below
    OpenMPT's, see _patch_key), the keys left over playing the nearest sample below (or the lowest), a sample without
    scale factor at one pitch (C-5); fadeout 2048 (64 in IT's units), new notes off. Returns (module, warnings)."""
    if len(data) < 239 or data[:8] != b"GF1PATCH" or data[8:12] not in (b"110\0", b"100\0") or data[12:22] != b"ID#000002\0":
        raise SF2Error("not a GUS patch (no GF1PATCH 1.00/1.10 header)")
    ninstr, nsamples = data[82], struct.unpack_from("<H", data, 85)[0]
    name = data[131:147]
    nlayer_samples = data[129 + 63 + 6]
    if not ninstr or not nsamples or not nlayer_samples:
        raise SF2Error("the patch holds no samples")
    mod = Module(title=_name(name)[:26] or "patch", instruments=[], channels=[Channel(name="")])
    ins = Instrument(name=_name(name)[:25], fadeout=2048 >> 5, nna=2, dca=2, keymap=[(n, 0) for n in range(120)])
    warnings, keyboard, notemap = [], [0] * 120, [None] * 120
    pos, low_note, low_smp = 129 + 63 + 47, 0xFF, 0
    for _ in range(nlayer_samples):
        if pos + 96 > len(data):
            break
        (sname, _frac, length, ls, le, freq, lo_f, hi_f, root_f, _fine, balance, *_env, _ts, _tr, _td, vs, vr, vd, flags,
         _sf, scale) = struct.unpack_from("<7sBIIIHIIIhB6B6BBBBBBBBhH", data, pos)
        pos += 96
        raw = data[pos:pos + length]
        pos += length
        if flags & 1:  # 16-bit: lengths and loop points in bytes
            frames = list(struct.unpack_from(f"<{len(raw) // 2}{'H' if flags & 2 else 'h'}", raw))
            frames = [v - 32768 for v in frames] if flags & 2 else frames
            ls, le = ls // 2, le // 2
        else:
            frames = [(v - 128 if flags & 2 else (v - 256 if v > 127 else v)) * 256 for v in raw]
        if len(frames) < 8:
            continue
        if len(mod.samples) >= 99:
            raise SF2Error("the patch has more than 99 samples")
        smp = Sample(name=_name(sname)[:25] or "zone", data=[frames], bits=16, c5_speed=max(1, freq), rate=freq,
                     vibrato_type=0, vibrato_speed=min(vr // 4, 64), vibrato_depth=min(vd, 64), vibrato_rate=vs)
        pan = (balance * 256 + 8) // 15
        if pan <= 256:
            smp.pan = min(pan // 4, 64)
        if scale:
            smp.c5_speed = max(1, round(freq * 2.0 ** ((84.0 - _patch_note(root_f)) / 12.0)))
        if flags & 4 and min(le, len(frames)) > ls:
            smp.loop = Loop(start=ls, end=min(le, len(frames)), pingpong=bool(flags & 8))
        if flags & 16:
            warnings.append(f"sample '{smp.name}': its backward-loop flag is not kept (IT has none)")
        mod.samples.append(smp)
        num = len(mod.samples)
        lo = _patch_key(lo_f) if lo_f > 100 else 0
        hi = _patch_key(hi_f) if hi_f > 100 else 120
        base = _patch_key(root_f) if root_f > 100 else -1
        if not scale and nlayer_samples == 1:
            lo, hi = 0, 120
        for k in range(120):
            if k == base or (not keyboard[k] and lo <= k <= hi):
                if not scale:
                    notemap[k] = 60
                keyboard[k] = num
                if k < low_note:
                    low_note, low_smp = k, num
    if not mod.samples:
        raise SF2Error("the patch holds no samples")
    for k in range(120):  # the keys left over play the sample below them (the lowest one below the first)
        if not keyboard[k]:
            keyboard[k] = low_smp
        else:
            low_smp = keyboard[k]
        ins.keymap[k] = (k if notemap[k] is None else notemap[k], keyboard[k])
    mod.instruments.append(ins)
    mod.patterns = [Pattern(name="p0", rows=[[Cell()] for _ in range(64)])]
    mod.orders = [0]
    warnings.insert(0, f"patch '{ins.name}': {len(mod.samples)} samples")
    return mod, warnings


def bank_module(path, preset=0, bank=0):
    """The instrument in `path`: an .sf2's preset, or a .pat's patch (`preset` and `bank` unused)."""
    from pathlib import Path
    data = Path(path).read_bytes()
    return pat_module(data) if data[:8] == b"GF1PATCH" else preset_module(data, preset, bank)


def preset_module(data, preset, bank=0):
    """The preset as a Module with one instrument (and its zones as samples), and the import's warnings. A preset
    number with no bank given is looked up in bank 0 first, then in any bank."""
    sf = read_sf2(data)
    found = [e for e in sf["presets"] if e[1] == preset and e[2] == bank] or \
        ([e for e in sf["presets"] if e[1] == preset] if bank == 0 else [])
    if not found:
        have = ", ".join(f"{b}:{p}" for _, p, b, _, _ in sf["presets"][:12])
        raise SF2Error(f"no preset {preset} in bank {bank} (bank:preset here: {have}{', ...' if len(sf['presets']) > 12 else ''})")
    entry = found[0]
    regions, env, drums = _regions(sf, entry)
    warnings = []
    if not regions:
        raise SF2Error(f"preset {entry[1]} '{entry[0]}' has no zone with a sample")
    top = max(r.vhi for r in regions)
    layer = [r for r in regions if r.vhi == top]
    if len(layer) < len(regions):
        warnings.append(f"velocity layers: kept the {len(layer)} zones that sound at velocity {top}, left out "
                        f"{len(regions) - len(layer)} quieter-layer zones (an IT instrument has one sample per key)")
    regions = layer
    mod = Module(title=entry[0][:26], instruments=[], channels=[Channel(name="")])
    ins = Instrument(name=entry[0][:25], fadeout=1024 >> 5, nna=2, dct=1, dca=2,
                     keymap=[(n, 0) for n in range(120)])
    slot_of, kept_waves, stereo_pairs, dropped = [], {}, 0, 0
    for k, rgn in enumerate(regions):
        num = 0
        dup = None
        for j in range(k):
            r2 = regions[j]
            if not slot_of[j]:
                continue
            same_sample = r2.wave == rgn.wave and r2.loop_start == rgn.loop_start and r2.loop_end == rgn.loop_end and rgn.wave in kept_waves
            same_keys = (r2.lo, r2.hi) == (rgn.lo, rgn.hi)
            if same_sample or same_keys:
                dup = j
                num = 0 if same_keys else slot_of[j]
                break
        if dup is None:
            if len(mod.samples) >= 99:
                raise SF2Error(f"preset '{entry[0]}' needs more than 99 samples")
            smp = _sample(sf, data, rgn, env)
            if smp is None:
                slot_of.append(0)
                dropped += 1
                continue
            mod.samples.append(smp)
            num = len(mod.samples)
            kept_waves[rgn.wave] = num
        slot_of.append(num)
        if num:
            for key in range(max(rgn.lo, 0), min(rgn.hi, 119) + 1):
                ins.keymap[key] = (60 if drums and rgn.tuning == 0 else key, num)
        elif dup is not None:
            smp = mod.samples[slot_of[dup] - 1]
            p1, p2 = _pan(rgn, env), _pan(regions[dup], env)
            other = _wave(sf, data, rgn.wave) if len(smp.data) == 1 and ((p1 < 16 and p2 >= 240) or (p2 < 16 and p1 >= 240)) else None
            if other is not None:  # OpenMPT combines a hard-left and a hard-right zone on one key range into stereo
                n = min(len(other), len(smp.data[0]))
                smp.data = [other[:n], smp.data[0][:n]] if p1 < p2 else [smp.data[0][:n], other[:n]]
                stereo_pairs += 1
            else:
                dropped += 1
    if stereo_pairs:
        warnings.append(f"{stereo_pairs} left/right zone pairs combined into stereo samples, as OpenMPT does")
    if dropped:
        warnings.append(f"{dropped} zones left out: each shares its key range with an earlier zone (OpenMPT keeps the "
                        f"first), or its sample is compressed or empty")
    vol = _to_envelope(env.vol)
    if vol:
        nodes, sus, fade = vol
        ins.volume_envelope = Envelope(nodes=[(t, min(v, 64)) for t, v in nodes], sustain=(sus, sus))
        if fade is not None:
            ins.fadeout = min(fade >> 5, 256)
    elif drums:  # OpenMPT's default envelope for a drum
        ins.volume_envelope = Envelope(nodes=[(0, 64), (5, 64), (10, 32), (20, 0)])
    if abs(env.pitch_depth) >= 50:
        pitch = _to_envelope(env.pitch, pitch=True, scale=env.pitch_depth)
        if pitch:
            nodes, sus, _ = pitch
            ins.pitch_envelope = Envelope(nodes=[(t, min(v, 64) - 32) for t, v in nodes], sustain=(sus, sus))
    mod.instruments.append(ins)
    mod.patterns = [Pattern(name="p0", rows=[[Cell()] for _ in range(64)])]
    mod.orders = [0]
    kind = "drum kit" if drums else "preset"
    warnings.insert(0, f"{kind} {entry[2]}:{entry[1]} '{entry[0]}': {len(mod.samples)} samples from {len(regions)} zones")
    return mod, warnings


def _pan(rgn, env):  # GetPanning
    return rgn.pan if rgn.pan is not None else (rgn.env or env).pan


def _sample(sf, data, rgn, env):
    frames = _wave(sf, data, rgn.wave)
    if not frames or len(frames) < 8:
        return None
    name, _, _, _, _, rate, pitch, correction, _, _ = sf["shdr"][rgn.wave]
    unity = rgn.unity if rgn.unity is not None else pitch
    if unity > 127:
        unity = 60
    steps = (60 - unity) * 128 + rgn.fine + _muldivr(correction, 128, 100)
    smp = Sample(name=(_name(name) or "zone")[:25], data=[frames], bits=16,
                 c5_speed=max(1, round(max(rate, 1) * 2.0 ** (steps / (12 * 128)))), rate=rate,
                 global_volume=rgn.volume // 4)
    n = len(frames)
    s, e = rgn.loop_start, min(rgn.loop_end, n)
    if rgn.mode and e > s:
        loop = Loop(start=s, end=e, pingpong=rgn.mode == 2)
        smp.loop = loop
        if rgn.mode == 3:
            smp.sustain_loop = Loop(start=s, end=e)
    return smp


def import_sf2(sf2_path, song_path, samples_dir, preset=0, bank=0):
    """A song file holding the preset (or the .pat's patch) as instrument 1 and an empty pattern, its zones written as
    WAVs. Returns (song dict, warnings)."""
    from pathlib import Path
    from .api import to_yaml
    from .fileio import atomic_write
    from .itreader import _sanitize, module_to_song
    mod, warnings = bank_module(sf2_path, preset, bank)
    _sanitize(mod, warnings)
    song = module_to_song(mod, song_path, samples_dir)
    from .api import written_by_line
    header = f"# Imported from {Path(sf2_path).name} by vulturetracker import\n" + written_by_line()
    for w in warnings:
        header += f"# import: {w}\n"
    atomic_write(song_path, (header + to_yaml(song)).encode("utf-8"))
    return song, warnings
