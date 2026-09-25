"""Song file (YAML) -> Module, with line-referenced validation errors."""
import re
import threading
from array import array
from pathlib import Path

import yaml

from . import notation
from .model import (Cell, Channel, Envelope, Instrument, Loop, Module, Pattern, Sample,
                    MAX_CHANNELS, ORDER_END, ORDER_SKIP)
from .wavload import WavData, WavError, read_wav

NNA = {"cut": 0, "continue": 1, "off": 2, "fade": 3}
DCT = {"off": 0, "note": 1, "sample": 2, "instrument": 3}
DCA = {"cut": 0, "off": 1, "fade": 2}
VIBRATO = {"sine": 0, "ramp_down": 1, "square": 2, "random": 3}
MAX_ROWS = 200
MAX_NUMBER = 99


class SongError(Exception):
    def __init__(self, errors, warnings=()):
        self.errors = list(errors)
        self.warnings = list(warnings)
        super().__init__("\n".join(self.errors))


# ---------------------------------------------------------------- YAML with line numbers

class LMap(dict):
    line = 0

    def __init__(self):
        super().__init__()
        self.lines = {}


class LSeq(list):
    line = 0

    def __init__(self):
        super().__init__()
        self.lines = []


class LStr(str):
    line = 0
    style = None


_constructor = yaml.SafeLoader("")


def _convert(node, ctx):
    line = node.start_mark.line + 1
    if isinstance(node, yaml.ScalarNode):
        raw = node.value
        if node.tag == "tag:yaml.org,2002:int" and re.fullmatch(r"0\d+", raw):
            return int(raw, 10)  # '08', '010' are decimal here, not octal
        value = _constructor.construct_object(node)
        if isinstance(value, str):
            value = LStr(value)
            value.line, value.style = line, node.style
        return value
    if isinstance(node, yaml.SequenceNode):
        seq = LSeq()
        seq.line = line
        for item in node.value:
            seq.append(_convert(item, ctx))
            seq.lines.append(item.start_mark.line + 1)
        return seq
    m = LMap()
    m.line = line
    for knode, vnode in node.value:
        key = _convert(knode, ctx)
        if isinstance(key, (LMap, LSeq)):
            ctx.error(knode.start_mark.line + 1, "mapping keys must be plain values")
            continue
        key = str(key) if isinstance(key, LStr) else key
        if key in m:
            ctx.error(knode.start_mark.line + 1, f"duplicate key '{key}' (first defined on line {m.lines[key]})")
        m[key] = _convert(vnode, ctx)
        m.lines[key] = knode.start_mark.line + 1
    return m


# ---------------------------------------------------------------- validation context

class Ctx:
    def __init__(self, filename):
        self.filename = filename
        self.errors = []
        self.warnings = []

    def error(self, line, msg):
        self.errors.append(f"{self.filename}:{line}: error: {msg}")

    def warn(self, line, msg):
        self.warnings.append(f"{self.filename}:{line}: warning: {msg}")


class _Bad(Exception):
    """Raised by field readers after the error has been recorded."""


def _soft(fn, default=None):
    """Run a field reader; on error (already recorded) return default so later fields still get checked."""
    try:
        return fn()
    except _Bad:
        return default


def _line(m, key):
    return m.lines.get(key, m.line) if isinstance(m, LMap) else 0


def _check_keys(ctx, m, allowed, where):
    for key in m:
        if key not in allowed:
            ctx.error(_line(m, key), f"unknown key '{key}' in {where} (allowed: {', '.join(allowed)})")


def _map(ctx, value, line, where):
    if value is None:
        return LMap()
    if not isinstance(value, LMap):
        ctx.error(line, f"{where} must be a mapping (key: value pairs)")
        raise _Bad
    return value


def _int(ctx, m, key, lo, hi, default=None, where=""):
    if key not in m or m[key] is None:
        if default is None:
            ctx.error(m.line, f"{where}: missing required '{key}'")
            raise _Bad
        return default
    v = m[key]
    if isinstance(v, bool) or not isinstance(v, int):
        ctx.error(_line(m, key), f"{where}: '{key}' must be a whole number, got {v!r}")
        raise _Bad
    if not lo <= v <= hi:
        ctx.error(_line(m, key), f"{where}: '{key}' = {v} is out of range {lo}..{hi}")
        raise _Bad
    return v


def _bool(ctx, m, key, default, where):
    v = m.get(key, default)
    if not isinstance(v, bool):
        ctx.error(_line(m, key), f"{where}: '{key}' must be true or false")
        raise _Bad
    return v


def _enum(ctx, m, key, choices, default, where):
    v = m.get(key, default)
    if isinstance(v, bool):  # YAML 1.1 reads bare off/on/no/yes as booleans
        v = "on" if v else "off"
    if v not in choices:
        ctx.error(_line(m, key), f"{where}: '{key}' must be one of {', '.join(choices)}, got {v!r}")
        raise _Bad
    return choices[v]


def _note(ctx, m, key, default, where):
    v = m.get(key, default)
    try:
        n = notation.parse_note(str(v))
    except notation.NotationError as e:
        ctx.error(_line(m, key), f"{where}: '{key}': {e}")
        raise _Bad
    if n >= 120:
        ctx.error(_line(m, key), f"{where}: '{key}' must be a real note, not {v}")
        raise _Bad
    return n


def _text(ctx, m, key, default, maxlen, where):
    v = m.get(key, default)
    if v is None:
        v = ""
    v = str(v)
    if len(v) > maxlen:
        ctx.error(_line(m, key), f"{where}: '{key}' is {len(v)} characters; IT allows at most {maxlen}")
        raise _Bad
    try:
        v.encode("ascii")
    except UnicodeEncodeError:
        ctx.error(_line(m, key), f"{where}: '{key}' must be plain ASCII")
        raise _Bad
    return v


def _numbered(ctx, m, where):
    """Mapping of 1..99 -> spec. Returns [(number, spec, line)] sorted."""
    out = []
    for key, spec in m.items():
        line = _line(m, key)
        num = key if isinstance(key, int) and not isinstance(key, bool) else (int(key) if str(key).isdigit() else None)
        if num is None or not 1 <= num <= MAX_NUMBER:
            ctx.error(line, f"{where} keys must be numbers 1..{MAX_NUMBER}, got '{key}'")
            continue
        out.append((num, spec, line))
    return sorted(out, key=lambda t: t[0])


# ---------------------------------------------------------------- sections

MODULE_KEYS = ["title", "tempo", "speed", "global_volume", "mix_volume", "separation", "linear_slides",
               "old_effects", "compatible_gxx", "channels", "message", "sample_rate"]
CHANNEL_KEYS = ["name", "pan", "volume", "muted"]


def _module(ctx, m, mod):
    where = "module"
    _check_keys(ctx, m, MODULE_KEYS, where)
    ctx.sample_rate = _int(ctx, m, "sample_rate", 4000, 192000, None, where) if m.get("sample_rate") is not None else None
    for key, fn in [
        ("title", lambda: _text(ctx, m, "title", "", 25, where)),
        ("tempo", lambda: _int(ctx, m, "tempo", 32, 255, 125, where)),
        ("speed", lambda: _int(ctx, m, "speed", 1, 255, 6, where)),
        ("global_volume", lambda: _int(ctx, m, "global_volume", 0, 128, 128, where)),
        ("mix_volume", lambda: _int(ctx, m, "mix_volume", 0, 128, 48, where)),
        ("separation", lambda: _int(ctx, m, "separation", 0, 128, 128, where)),
        ("linear_slides", lambda: _bool(ctx, m, "linear_slides", True, where)),
        ("old_effects", lambda: _bool(ctx, m, "old_effects", False, where)),
        ("compatible_gxx", lambda: _bool(ctx, m, "compatible_gxx", False, where)),
    ]:
        try:
            setattr(mod, key, fn())
        except _Bad:
            pass
    msg = m.get("message")
    mod.message = str(msg) if msg else ""
    if len(mod.message.replace("\r\n", "\n")) + 1 > 65535:  # the writer's limit (IT's 16-bit length), one byte a character
        ctx.error(_line(m, "message"), f"module.message is {len(mod.message)} characters; IT stores at most 65534")
    chans = m.get("channels")
    if chans is None:
        ctx.error(m.line, "module: missing required 'channels' (a number 1..64 or a list)")
        return
    if isinstance(chans, int) and not isinstance(chans, bool):
        if not 1 <= chans <= MAX_CHANNELS:
            ctx.error(_line(m, "channels"), f"module: channels must be 1..{MAX_CHANNELS}")
            return
        mod.channels = [Channel() for _ in range(chans)]
        return
    if not isinstance(chans, LSeq) or not 1 <= len(chans) <= MAX_CHANNELS:
        ctx.error(_line(m, "channels"), f"module: 'channels' must be a number or a list of 1..{MAX_CHANNELS} channels")
        return
    for i, (c, line) in enumerate(zip(chans, chans.lines)):
        w = f"channel {i + 1}"
        ch = Channel()
        try:
            c = _map(ctx, c, line, w)
            c.line = c.line or line
            _check_keys(ctx, c, CHANNEL_KEYS, w)
            ch.name = _text(ctx, c, "name", "", 20, w)
            if c.get("pan") == "surround":
                ch.pan = 100
            else:
                ch.pan = _int(ctx, c, "pan", 0, 64, 32, w)
            ch.volume = _int(ctx, c, "volume", 0, 64, 64, w)
            ch.muted = _bool(ctx, c, "muted", False, w)
        except _Bad:
            pass
        mod.channels.append(ch)


SAMPLE_KEYS = ["file", "name", "volume", "global_volume", "pan", "base_note", "c5_speed", "loop",
               "sustain_loop", "vibrato", "bits", "stereo"]
LOOP_KEYS = ["start", "end", "type"]
VIBRATO_KEYS = ["type", "speed", "depth", "rate"]


def _loop(ctx, spec, line, wav, length, where):
    """Loop points in the WAV file's own frames (`length` of them)."""
    if spec is None or spec is False or spec == "none":
        return None
    if spec == "from_wav":
        if not wav.loops:
            ctx.error(line, f"{where}: 'from_wav' but the WAV file has no loop points (smpl chunk)")
            raise _Bad
        s, e, pp = wav.loops[0]
        if min(e, length) <= s:
            ctx.error(line, f"{where}: the WAV file's loop ({s}..{e}) is empty or past its {length} frames")
            raise _Bad
        return Loop(s, min(e, length), pp)
    m = _map(ctx, spec, line, where)
    _check_keys(ctx, m, LOOP_KEYS, where)
    start = _int(ctx, m, "start", 0, length, 0, where)
    end = _int(ctx, m, "end", 0, length, length, where)
    if end <= start:
        ctx.error(m.line, f"{where}: end ({end}) must be greater than start ({start}); sample length is {length}")
        raise _Bad
    pp = _enum(ctx, m, "type", {"forward": False, "pingpong": True}, "forward", where)
    return Loop(start, end, pp)


# The app compiles the same song on every edit: what a sample costs to read and convert is memoised on its file's stamp
# (path, mtime, size), as compact arrays that compiled modules share and never change in place.
_WAVS = {}       # stamp -> the WAV as read (WavData, channels as arrays)
_RESAMPLED = {}  # (stamp, rate, bits, loops) -> channels resampled to the module's sample_rate
_DATA = {}       # (stamp, rate, loops, stereo, bits) -> the channels as the module stores them (Sample.source)
_IMAGES = {}     # (Sample.source, playback rate) -> image_level (None: no image under 20 kHz)
_UNSEEN = object()
_PATTERNS = {}   # (name, data text, style, line, rows, channels) -> (rows of cells, line numbers): an edit changes one
_MEMO_SIZE = 96  # entries per memo (patterns: 8 times as many)
_MEMO_LOCK = threading.Lock()  # the app compiles on request threads and its render worker at once: reads use .get()


def _remember(memo, key, value, scale=1):
    with _MEMO_LOCK:
        while len(memo) >= scale * _MEMO_SIZE:
            memo.pop(next(iter(memo)), None)
        memo[key] = value
    return value


def _pcm(values, bits):
    return array("h" if bits == 16 else "b", values)


def _read_wav(path):
    """read_wav memoised on the file's stamp; returns (stamp, WavData with array channels)."""
    st = path.stat()
    stamp = (str(path), st.st_mtime_ns, st.st_size)
    wav = _WAVS.get(stamp)
    if wav is None:
        w = read_wav(path)
        wav = _remember(_WAVS, stamp, WavData(w.rate, w.bits, [_pcm(c, w.out_bits) for c in w.channels], w.out_bits,
                                              w.loops, w.root))
    return stamp, wav


def _resampled(stamp, wav, target, loops, resample_pcm):
    """`wav.channels` resampled to `target` with its `loops` kept seamless (memoised)."""
    k = (stamp, target, wav.out_bits, tuple(loops))
    chans = _RESAMPLED.get(k)
    if chans is None:
        chans = _remember(_RESAMPLED, k, [_pcm(c, wav.out_bits) for c in resample_pcm(wav.channels, wav.rate, target,
                                                                                       wav.out_bits, loops)])
    return chans


def _sample(ctx, num, spec, line, base_dir):
    where = f"sample {num}"
    m = _map(ctx, spec, line, where)
    _check_keys(ctx, m, SAMPLE_KEYS, where)
    if "file" not in m:
        if any(k != "name" for k in m):
            ctx.error(m.line, f"{where}: missing 'file' (path to a WAV, relative to the song file); "
                              "only an empty slot may omit it, and then only 'name' is allowed")
            raise _Bad
        return Sample(name=_text(ctx, m, "name", "", 25, where))  # empty slot
    path = (base_dir / str(m["file"])).resolve()
    if not path.is_file():
        ctx.error(_line(m, "file"), f"{where}: file not found: {path}")
        raise _Bad
    try:
        stamp, wav = _read_wav(path)
    except WavError as e:
        ctx.error(_line(m, "file"), f"{where}: {e}")
        raise _Bad
    frames = len(wav.channels[0]) if wav.channels else 0
    if frames == 0:
        ctx.error(_line(m, "file"), f"{where}: WAV file contains no audio")
        raise _Bad
    loop = _loop(ctx, m.get("loop"), _line(m, "loop"), wav, frames, f"{where} loop")
    sustain_loop = _loop(ctx, m.get("sustain_loop"), _line(m, "sustain_loop"), wav, frames, f"{where} sustain_loop")
    target = getattr(ctx, "sample_rate", None)
    wav_rate = wav.rate   # c5_speed is given for the WAV as written
    if target and target != wav.rate:   # module sample_rate: band-limited resampling, so playback neither images nor aliases
        try:
            from .resample import place_loops, resample_pcm
        except ImportError:
            ctx.error(_line(m, "file"), f"{where}: the module's sample_rate needs numpy (pip install numpy)")
            raise _Bad
        loops = [(lp.start, lp.end, lp.pingpong) for lp in (loop, sustain_loop) if lp]
        placed = iter(place_loops(loops, wav.rate, target))
        loop, sustain_loop = (lp and Loop(*next(placed)) for lp in (loop, sustain_loop))
        wav = WavData(target, wav.bits, _resampled(stamp, wav, target, loops, resample_pcm), wav.out_bits, [], wav.root)
        stamp = (stamp, target, tuple(loops))
    smp = Sample()
    smp.name = _text(ctx, m, "name", path.stem[:25], 25, where)
    smp.filename = path.name[:12]
    stereo = _bool(ctx, m, "stereo", False, where)
    smp.bits = _enum(ctx, m, "bits", {8: 8, 16: 16}, wav.out_bits, where)
    smp.source = (stamp, stereo, smp.bits)
    smp.data = _DATA.get(smp.source)
    if smp.data is None:
        chans = wav.channels
        if len(chans) > 2 or (len(chans) == 2 and not stereo):
            chans = [_pcm((round(sum(v) / len(chans)) for v in zip(*chans)), wav.out_bits)]
        if smp.bits == 8 and wav.out_bits == 16:
            chans = [_pcm((v >> 8 for v in ch), 8) for ch in chans]
        elif smp.bits == 16 and wav.out_bits == 8:
            chans = [_pcm((v << 8 for v in ch), 16) for ch in chans]
        smp.data = _remember(_DATA, smp.source, chans)
    smp.volume = _int(ctx, m, "volume", 0, 64, 64, where)
    smp.global_volume = _int(ctx, m, "global_volume", 0, 64, 64, where)
    smp.pan = _int(ctx, m, "pan", 0, 64, None, where) if m.get("pan") is not None else None
    if "c5_speed" in m:
        smp.c5_speed = round(_int(ctx, m, "c5_speed", 256, 9999999, None, where) * wav.rate / wav_rate)
        if "base_note" in m:
            ctx.error(_line(m, "base_note"), f"{where}: give either base_note or c5_speed, not both")
    else:
        base = _note(ctx, m, "base_note", "C-5", where)
        smp.c5_speed = round(wav.rate * 2 ** ((60 - base) / 12))
    smp.loop, smp.sustain_loop = loop, sustain_loop
    if m.get("vibrato") is not None:
        v = _map(ctx, m["vibrato"], _line(m, "vibrato"), f"{where} vibrato")
        w = f"{where} vibrato"
        _check_keys(ctx, v, VIBRATO_KEYS, w)
        smp.vibrato_type = _enum(ctx, v, "type", VIBRATO, "sine", w)
        smp.vibrato_speed = _int(ctx, v, "speed", 0, 64, 0, w)
        smp.vibrato_depth = _int(ctx, v, "depth", 0, 64, 0, w)
        smp.vibrato_rate = _int(ctx, v, "rate", 0, 255, 0, w)
    return smp


INSTRUMENT_KEYS = ["name", "sample", "keymap", "fadeout", "nna", "dct", "dca", "global_volume", "pan",
                   "pitch_pan_separation", "pitch_pan_center", "random_volume", "random_pan", "filter_cutoff",
                   "filter_resonance", "volume_envelope", "panning_envelope", "pitch_envelope"]
KEYMAP_KEYS = ["notes", "sample", "transpose", "play_note"]
ENVELOPE_KEYS = ["nodes", "loop", "sustain", "enabled", "carry", "filter"]


def _sample_ref(ctx, value, line, samples_by_name, sample_numbers, where):
    if isinstance(value, int) and not isinstance(value, bool):
        num = value
    elif str(value) in samples_by_name:
        num = samples_by_name[str(value)]
    else:
        ctx.error(line, f"{where}: unknown sample '{value}' (use a sample number or name)")
        raise _Bad
    if num not in sample_numbers:
        ctx.error(line, f"{where}: sample {num} is not defined")
        raise _Bad
    return num


def _note_range(ctx, value, line, where):
    text = str(value)
    parts = text.split("..")
    try:
        if len(parts) == 1:
            lo = hi = notation.parse_note(parts[0].strip())
        elif len(parts) == 2:
            lo, hi = notation.parse_note(parts[0].strip()), notation.parse_note(parts[1].strip())
        else:
            raise notation.NotationError(f"bad note range '{text}'")
    except notation.NotationError as e:
        ctx.error(line, f"{where}: 'notes': {e}; write a note (C-5) or a range (C-0..B-4)")
        raise _Bad
    if hi < lo or hi >= 120:
        ctx.error(line, f"{where}: note range '{text}' is empty or backwards")
        raise _Bad
    return lo, hi


def _envelope(ctx, spec, line, kind, where):
    if spec is None:
        return None
    m = _map(ctx, spec, line, where)
    _check_keys(ctx, m, ENVELOPE_KEYS, where)
    lo, hi = (0, 64) if kind == "volume" else (-32, 32)
    nodes = m.get("nodes")
    if not isinstance(nodes, LSeq) or not 1 <= len(nodes) <= 25:
        ctx.error(_line(m, "nodes"), f"{where}: 'nodes' must be a list of 1..25 [tick, value] pairs")
        raise _Bad
    out = []
    n_errors = len(ctx.errors)
    for i, (node, nline) in enumerate(zip(nodes, nodes.lines)):
        if not (isinstance(node, LSeq) and len(node) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in node)):
            ctx.error(nline, f"{where}: node {i} must be [tick, value], got {node!r}")
            raise _Bad
        tick, value = node
        if not lo <= value <= hi:
            ctx.error(nline, f"{where}: node {i} value {value} out of range {lo}..{hi}")
        if not 0 <= tick <= 9999:
            ctx.error(nline, f"{where}: node {i} tick {tick} out of range 0..9999")
        if i == 0 and tick != 0:
            ctx.error(nline, f"{where}: the first node must be at tick 0")
        if i > 0 and tick <= out[-1][0]:
            ctx.error(nline, f"{where}: node {i} tick {tick} must be greater than the previous tick {out[-1][0]}")
        out.append((tick, value))
    if len(ctx.errors) > n_errors:
        raise _Bad

    def pair(key):
        v = m.get(key)
        if v is None:
            return None
        if isinstance(v, int) and not isinstance(v, bool):
            v = [v, v]
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) for x in v)):
            ctx.error(_line(m, key), f"{where}: '{key}' must be a node index or [first, last] node indices")
            raise _Bad
        if not 0 <= v[0] <= v[1] < len(out):
            ctx.error(_line(m, key), f"{where}: '{key}' {list(v)} must be node indices 0..{len(out) - 1}, first <= last")
            raise _Bad
        return (v[0], v[1])

    env = Envelope(out, _bool(ctx, m, "enabled", True, where), pair("loop"), pair("sustain"))
    env.carry = _bool(ctx, m, "carry", False, where)
    if "filter" in m:
        if kind != "pitch":
            ctx.error(_line(m, "filter"), f"{where}: 'filter' only applies to the pitch envelope")
            raise _Bad
        env.filter = _bool(ctx, m, "filter", False, where)
    return env


def _instrument(ctx, num, spec, line, samples_by_name, sample_numbers):
    where = f"instrument {num}"
    m = _map(ctx, spec, line, where)
    _check_keys(ctx, m, INSTRUMENT_KEYS, where)
    ins = Instrument()
    ins.name = _text(ctx, m, "name", "", 25, where)
    keymap = [(n, 0) for n in range(120)]
    if "sample" in m:
        s = _sample_ref(ctx, m["sample"], _line(m, "sample"), samples_by_name, sample_numbers, where)
        keymap = [(n, s) for n in range(120)]
    if "keymap" in m:
        km = m["keymap"]
        if not isinstance(km, LSeq):
            ctx.error(_line(m, "keymap"), f"{where}: 'keymap' must be a list of {{notes, sample}} entries")
            raise _Bad
        for i, (entry, eline) in enumerate(zip(km, km.lines)):
            w = f"{where} keymap entry {i + 1}"
            e = _map(ctx, entry, eline, w)
            _check_keys(ctx, e, KEYMAP_KEYS, w)
            if "notes" not in e or "sample" not in e:
                ctx.error(e.line, f"{w}: needs 'notes' and 'sample'")
                raise _Bad
            lo, hi = _note_range(ctx, e["notes"], _line(e, "notes"), w)
            s = _sample_ref(ctx, e["sample"], _line(e, "sample"), samples_by_name, sample_numbers, w)
            if "play_note" in e and "transpose" in e:
                ctx.error(e.line, f"{w}: use either 'transpose' or 'play_note', not both")
                raise _Bad
            fixed = _note(ctx, e, "play_note", None, w) if "play_note" in e else None
            transpose = _int(ctx, e, "transpose", -119, 119, 0, w)
            for n in range(lo, hi + 1):
                target = fixed if fixed is not None else n + transpose
                if not 0 <= target < 120:
                    ctx.error(_line(e, "transpose"), f"{w}: transpose {transpose:+d} moves {notation.format_note(n)} outside C-0..B-9")
                    raise _Bad
                keymap[n] = (target, s)
    ins.keymap = keymap
    n_errors = len(ctx.errors)
    ins.fadeout = _soft(lambda: _int(ctx, m, "fadeout", 0, 256, 0, where), 0)
    ins.nna = _soft(lambda: _enum(ctx, m, "nna", NNA, "cut", where), 0)
    ins.dct = _soft(lambda: _enum(ctx, m, "dct", DCT, "off", where), 0)
    ins.dca = _soft(lambda: _enum(ctx, m, "dca", DCA, "cut", where), 0)
    ins.global_volume = _soft(lambda: _int(ctx, m, "global_volume", 0, 128, 128, where), 128)
    if m.get("pan") is not None:
        ins.pan = _soft(lambda: _int(ctx, m, "pan", 0, 64, None, where))
    ins.pitch_pan_separation = _soft(lambda: _int(ctx, m, "pitch_pan_separation", -32, 32, 0, where), 0)
    ins.pitch_pan_center = _soft(lambda: _note(ctx, m, "pitch_pan_center", "C-5", where), 60)
    ins.random_volume = _soft(lambda: _int(ctx, m, "random_volume", 0, 100, 0, where), 0)
    ins.random_pan = _soft(lambda: _int(ctx, m, "random_pan", 0, 64, 0, where), 0)
    if m.get("filter_cutoff") is not None:
        ins.filter_cutoff = _soft(lambda: _int(ctx, m, "filter_cutoff", 0, 127, None, where))
    if m.get("filter_resonance") is not None:
        ins.filter_resonance = _soft(lambda: _int(ctx, m, "filter_resonance", 0, 127, None, where))
    for key, kind in (("volume_envelope", "volume"), ("panning_envelope", "panning"), ("pitch_envelope", "pitch")):
        setattr(ins, key, _soft(lambda: _envelope(ctx, m.get(key), _line(m, key), kind, f"{where} {key}")))
    if len(ctx.errors) > n_errors:
        raise _Bad
    return ins


_ROW_PREFIX = re.compile(r"^\s*(\d+)\s*:(.*)$")


def _pattern(ctx, name, spec, line, num_channels):
    where = f"pattern '{name}'"
    if isinstance(spec, LStr):
        data, rows = spec, None
        m = None
    else:
        m = _map(ctx, spec, line, where)
        _check_keys(ctx, m, ["rows", "data"], where)
        rows = _int(ctx, m, "rows", 1, MAX_ROWS, None, where) if "rows" in m else None
        data = m.get("data")
        if data is None:
            data = LStr("")
            data.line, data.style = m.line, "|"
    if not isinstance(data, LStr):
        ctx.error(line, f"{where}: 'data' must be text")
        raise _Bad
    key = (str(name), str(data), data.style, data.line, rows, num_channels)
    hit = _PATTERNS.get(key)
    if hit is not None:  # parsed before, and it parsed cleanly: the same cells (shared, never changed) and line numbers
        return Pattern(str(name), hit[0]), hit[1]
    # Row line numbers are exact for literal blocks ('data: |'); other string styles report the data line.
    literal = data.style == "|"
    first_line = data.line + 1
    cells_rows = []
    ok = True
    for i, text in enumerate(data.split("\n")):
        lineno = first_line + i if literal else data.line
        text = text.split(";", 1)[0].strip()
        if not text:
            continue  # blank and comment-only lines are not rows
        row = len(cells_rows)
        pm = _ROW_PREFIX.match(text)
        if pm:
            if int(pm.group(1)) != row:
                ctx.error(lineno, f"{where}: row label {pm.group(1)} but this is row {row} "
                                  f"(a row was added or dropped above)")
                ok = False
            text = pm.group(2).strip()
        if text.startswith("|"):
            text = text[1:]
        if text.endswith("|"):
            text = text[:-1]
        parts = text.split("|")
        if len(parts) > num_channels:
            ctx.error(lineno, f"{where}, row {row}: {len(parts)} cells but the module has {num_channels} channels")
            ok = False
            parts = parts[:num_channels]
        row_cells = []
        for ch, part in enumerate(parts):
            if not part.strip():
                ctx.error(lineno, f"{where}, row {row}, channel {ch + 1}: empty cell; write '...' for an empty cell")
                ok = False
                row_cells.append(Cell())
                continue
            try:
                row_cells.append(notation.parse_cell(part))
            except notation.NotationError as e:
                ctx.error(lineno, f"{where}, row {row}, channel {ch + 1}: {e}")
                ok = False
                row_cells.append(Cell())
        row_cells += [Cell() for _ in range(num_channels - len(row_cells))]
        cells_rows.append((row_cells, lineno))
    if rows is None:
        rows = len(cells_rows)
        if rows == 0:
            ctx.error(line, f"{where}: no rows; give 'rows' or write some rows in 'data'")
            raise _Bad
    if rows > MAX_ROWS:
        ctx.error(line, f"{where}: {rows} rows; IT allows at most {MAX_ROWS}")
        raise _Bad
    if len(cells_rows) > rows:
        ctx.error(cells_rows[rows][1], f"{where}: has {len(cells_rows)} rows of data but rows = {rows}")
        raise _Bad
    lines = [ln for _, ln in cells_rows]
    grid = [c for c, _ in cells_rows] + [[Cell() for _ in range(num_channels)] for _ in range(rows - len(cells_rows))]
    if not ok:
        raise _Bad
    _remember(_PATTERNS, key, (grid, lines), 8)
    return Pattern(str(name), grid), lines


def _check_pattern_refs(ctx, mod, pat, lines, where, declared, lowest):
    """Cross-reference checks that need the whole module. `declared`: instrument (or, in sample
    mode, sample) numbers defined in the song. `lowest` collects sample number -> (the lowest
    note it plays, line, place) for `_check_images`."""
    insmode = mod.instruments is not None
    kind = "instrument" if insmode else "sample"
    last_ins = [0] * len(mod.channels)
    for r, row in enumerate(pat.rows):
        line = lines[r] if r < len(lines) else lines[-1] if lines else 0
        for ch, cell in enumerate(row):
            at = f"{where}, row {r}, channel {ch + 1}"
            if cell.instrument:
                if cell.instrument not in declared:
                    ctx.error(line, f"{at}: {kind} {cell.instrument:02d} is not defined")
                    continue
                last_ins[ch] = cell.instrument
            if cell.note is not None and cell.note < 120 and last_ins[ch]:
                play, smp = cell.note, last_ins[ch]
                if insmode:
                    ins = mod.instruments[last_ins[ch] - 1]
                    play, smp = ins.keymap[cell.note] if ins else (play, 0)
                    if ins and smp == 0:
                        ctx.warn(line, f"{at}: {notation.format_note(cell.note)} has no sample in instrument "
                                       f"{last_ins[ch]:02d} '{ins.name}' keymap (plays silence)")
                if smp and (smp not in lowest or play < lowest[smp][0]):
                    lowest[smp] = (play, line, at)
            letter = chr(ord("A") + cell.effect - 1) if cell.effect else ""
            if letter == "B" and cell.param >= len(mod.orders):
                ctx.error(line, f"{at}: B{cell.param:02X} jumps to order {cell.param} but the order list has {len(mod.orders)} entries")
            elif letter == "M" and cell.param > 0x40:
                ctx.error(line, f"{at}: M{cell.param:02X} channel volume must be 00..40 (hex)")
            elif letter == "V" and cell.param > 0x80:
                ctx.error(line, f"{at}: V{cell.param:02X} global volume must be 00..80 (hex)")
            elif letter == "C" and cell.param >= MAX_ROWS:
                ctx.error(line, f"{at}: C{cell.param:02X} breaks to row {cell.param}; the parameter is hex (C10 = row 16)")


def compile_tree(tree, ctx, base_dir) -> Module:
    mod = Module()
    if not isinstance(tree, LMap):
        ctx.error(1, "the song file must be a mapping with module, samples, instruments, patterns, orders")
        return mod
    _check_keys(ctx, tree, ["module", "samples", "instruments", "patterns", "orders"], "the song file")
    try:
        _module(ctx, _map(ctx, tree.get("module"), _line(tree, "module"), "module"), mod)
    except _Bad:
        pass
    if "module" not in tree:
        ctx.error(1, "missing 'module' section")

    # Samples
    samples_by_name = {}
    sample_numbers = set()
    instrument_numbers = set()
    try:
        entries = _numbered(ctx, _map(ctx, tree.get("samples"), _line(tree, "samples"), "samples"), "sample")
    except _Bad:
        entries = []
    if not entries:
        ctx.error(_line(tree, "samples") or 1, "no samples defined")
    mod.samples = [Sample() for _ in range(max((n for n, _, _ in entries), default=0))]
    for num, spec, line in entries:
        sample_numbers.add(num)
        try:
            mod.samples[num - 1] = _sample(ctx, num, spec, line, base_dir)
            samples_by_name.setdefault(mod.samples[num - 1].name, num)
        except _Bad:
            pass

    # Instruments (optional: without them the module is in sample mode)
    if tree.get("instruments") is not None:
        try:
            entries = _numbered(ctx, _map(ctx, tree["instruments"], _line(tree, "instruments"), "instruments"), "instrument")
        except _Bad:
            entries = []
        mod.instruments = [None] * max((n for n, _, _ in entries), default=0)
        for num, spec, line in entries:
            instrument_numbers.add(num)
            try:
                mod.instruments[num - 1] = _instrument(ctx, num, spec, line, samples_by_name, sample_numbers)
            except _Bad:
                mod.instruments[num - 1] = Instrument(name="(invalid)")
        for i, ins in enumerate(mod.instruments):
            if ins is None:
                mod.instruments[i] = Instrument()  # gap: empty slot

    # Patterns
    num_channels = len(mod.channels) or 1
    pat_index = {}
    pat_lines = []
    try:
        pats = _map(ctx, tree.get("patterns"), _line(tree, "patterns"), "patterns")
    except _Bad:
        pats = LMap()
    if not pats:
        ctx.error(_line(tree, "patterns") or 1, "no patterns defined")
    for name, spec in pats.items():
        try:
            pat, lines = _pattern(ctx, str(name), spec, _line(pats, name), num_channels)
        except _Bad:
            pat, lines = Pattern(str(name), [[Cell() for _ in range(num_channels)]]), []
        pat_index[str(name)] = len(mod.patterns)
        mod.patterns.append(pat)
        pat_lines.append(lines)

    # Orders
    orders = tree.get("orders")
    if not isinstance(orders, LSeq) or not orders:
        ctx.error(_line(tree, "orders") or 1, "'orders' must be a non-empty list of pattern names")
    else:
        if len(orders) > 255:
            ctx.error(orders.line, "at most 255 orders")
        for entry, line in zip(orders, orders.lines):
            key = str(entry)
            if key == "+++":
                mod.orders.append(ORDER_SKIP)
            elif key == "---":
                mod.orders.append(ORDER_END)
            elif key in pat_index:
                mod.orders.append(pat_index[key])
            else:
                ctx.error(line, f"orders: unknown pattern '{key}' (defined: {', '.join(pat_index) or 'none'})")
        used = {o for o in mod.orders}
        for name, idx in pat_index.items():
            if idx not in used:
                ctx.warn(_line(pats, name), f"pattern '{name}' is not used in the order list")

    lowest = {}
    from .itwriter import PATTERN_BYTES, packed_size
    for pat, lines in zip(mod.patterns, pat_lines):
        _check_pattern_refs(ctx, mod, pat, lines, f"pattern '{pat.name}'",
                            instrument_numbers if mod.instruments is not None else sample_numbers, lowest)
        size = packed_size(pat, len(mod.channels))
        if size > PATTERN_BYTES:
            ctx.error(_line(pats, pat.name), f"pattern '{pat.name}': {size} bytes of cell data; IT holds at most "
                                             f"{PATTERN_BYTES} per pattern (fewer rows, channels or filled cells)")
    _check_images(ctx, mod, lowest)
    return mod


IMAGE_LIMIT = -60   # dB: the loudest interpolation images a sample's lowest note may leave under 20 kHz


def _check_images(ctx, mod, lowest):
    """Warn when a note plays a sample so far below its stored rate that the player's interpolation images reach the
    audible band (resample.image_level): a bright sample stored at 44.1 kHz does from about four semitones down."""
    try:
        from .resample import image_level
    except ImportError:     # no numpy, nothing to measure with
        return
    # ponytail: the lowest note only; slides, vibrato and pitch envelopes that go lower are not checked
    for num, (note, line, at) in sorted(lowest.items()):
        smp = mod.samples[num - 1] if num <= len(mod.samples) else None
        rate = smp.c5_speed * 2 ** ((note - 60) / 12) if smp else 0
        k = (smp.source, rate) if smp and smp.source else None
        db = _IMAGES.get(k, _UNSEEN) if k is not None else _UNSEEN
        if db is _UNSEEN:
            db = image_level(smp.data, rate) if smp and smp.data else None
            if k is not None:
                _remember(_IMAGES, k, db)
        if db is not None and db > IMAGE_LIMIT:
            ctx.warn(line, f"{at}: {notation.format_note(note)} plays sample {num:02d} '{smp.name}' so far below its "
                           f"stored rate that its interpolation images reach {db:.0f} dB under 20 kHz (limit "
                           f"{IMAGE_LIMIT}); play it higher, add a lower multisample, or store it at a higher rate "
                           f"(module sample_rate: 88200)")


# libyaml's parser when PyYAML has it (about ten times faster; the same nodes, marks and styles, so the same module)
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load_song_text(text, base_dir=".", filename="<song>"):
    """Parse and validate song YAML. Returns (Module, warnings); raises SongError listing every problem found."""
    ctx = Ctx(filename)
    try:
        node = yaml.compose(text, Loader=_LOADER)
        tree = _convert(node, ctx) if node is not None else None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        line = mark.line + 1 if mark else 1
        raise SongError([f"{filename}:{line}: error: YAML syntax: {getattr(e, 'problem', e)}"])
    except RecursionError:
        raise SongError([f"{filename}:1: error: the YAML nests too deeply, or an alias refers to its own anchor"])
    if node is None:
        raise SongError([f"{filename}:1: error: the song file is empty"])
    mod = compile_tree(tree, ctx, Path(base_dir))
    if ctx.errors:
        raise SongError(ctx.errors, ctx.warnings)
    return mod, ctx.warnings


def load_song(path):
    path = Path(path)
    return load_song_text(path.read_text(encoding="utf-8"), path.parent, str(path))
