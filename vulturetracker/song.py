"""Song file (YAML) -> Module, with line-referenced validation errors."""
import math
import re
import threading
import unicodedata
from array import array
from pathlib import Path

import yaml

from . import __version__, notation
from .model import (Cell, Channel, Envelope, Instrument, Loop, Module, Pattern, Sample,
                    MAX_CHANNELS, ORDER_END, ORDER_SKIP)
from .wavload import WavData, WavError, read_wav

NNA = {"cut": 0, "continue": 1, "off": 2, "fade": 3}
DCT = {"off": 0, "note": 1, "sample": 2, "instrument": 3}
DCA = {"cut": 0, "off": 1, "fade": 2}
VIBRATO = {"sine": 0, "ramp_down": 1, "square": 2, "random": 3}
MAX_ROWS = 200
MAX_NUMBER = 99


_LATIN = str.maketrans({"ß": "ss", "æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O", "œ": "oe", "Œ": "OE", "ł": "l", "Ł": "L",
                        "đ": "d", "Đ": "D", "þ": "th", "Þ": "Th", "ð": "d", "Ð": "D"})


def it_text(s, n):
    """`s` as IT stores a name: ASCII, at most `n` characters. Accented letters lose their accents (Böse -> Bose) and a
    few others take their usual spelling (ß -> ss); control characters go; what has no ASCII form becomes '?'."""
    s = unicodedata.normalize("NFKD", str(s).translate(_LATIN))
    return "".join(c for c in s if c >= " " and not unicodedata.combining(c)).encode("ascii", "replace").decode()[:n]


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
        if node.tag == "tag:yaml.org,2002:int" and re.fullmatch(r"[-+]?0\d+", raw):
            return int(raw, 10)  # '08', '010' are decimal here, not octal
        value = _constructor.construct_object(node)
        _constructor.constructed_objects.pop(node, None)  # the loader keeps every node it made; this one is done
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
    if isinstance(v, (list, dict)) or v not in choices:
        ctx.error(_line(m, key), f"{where}: '{key}' must be one of {', '.join(map(str, choices))}, got {v!r}")
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
               "old_effects", "compatible_gxx", "channels", "message", "sample_rate", "rows_per_beat", "rows_per_bar",
               "plugins", "macros", "key", "ceiling"]
KEY_RE = re.compile(r"([A-Ga-g])([#b]?)\s+(major|minor|ionian|dorian|phrygian|lydian|mixolydian|aeolian|locrian)", re.I)
CHANNEL_KEYS = ["name", "pan", "volume", "muted", "plugin", "approved", "color"]


def _plugins(ctx, m, mod):
    """`module: plugins:` {1..: {effect, name, output, bypass, gain, dry, master, and the effect's parameters in their
    units}} and `module: macros:` {SF0..SFF: macro text} (plugins.py)."""
    from . import plugins as P
    spec = m.get("plugins")
    if spec is not None:
        try:
            entries = _map(ctx, spec, _line(m, "plugins"), "module.plugins")
        except _Bad:
            entries = LMap()
        for key, p in entries.items():
            line = _line(entries, key)
            num = key if isinstance(key, int) and not isinstance(key, bool) else None
            if num is None or not 1 <= num <= P.MAX_PLUGINS:
                ctx.error(line, f"module.plugins: plugin numbers are 1..{P.MAX_PLUGINS}, got {key!r}")
                continue
            w = f"plugin {num}"
            try:
                p = _map(ctx, p, line, w)
                effect = p.get("effect")
                if effect not in P.EFFECTS:
                    ctx.error(_line(p, "effect") or line, f"{w}: 'effect' must be one of {', '.join(P.EFFECTS)}, got {effect!r}")
                    continue
                specs = P.params_of(effect)
                _check_keys(ctx, p, P.PLUGIN_KEYS + [s[0] for s in specs], f"{w} ({effect})")
                d = {"effect": effect, "params": [s[4] for s in specs]}
                for i, s in enumerate(specs):
                    if s[0] in p:
                        try:
                            d["params"][i] = P.from_unit(s, p[s[0]])
                        except ValueError as e:
                            ctx.error(_line(p, s[0]), f"{w}: {e}")
                d["name"] = _text(ctx, p, "name", "", 31, w)
                out = p.get("output", "master")
                if out != "master":
                    if isinstance(out, bool) or not isinstance(out, int) or not 1 <= out <= P.MAX_PLUGINS or out == num:
                        ctx.error(_line(p, "output"), f"{w}: 'output' is master or another plugin's number, got {out!r}")
                    else:
                        d["output"] = out
                d["bypass"] = _bool(ctx, p, "bypass", False, w)
                d["master"] = _bool(ctx, p, "master", False, w)
                param_gain = any(s[0] == "gain" for s in specs)
                if not param_gain and "gain" in p and "output_gain" in p:
                    ctx.error(_line(p, "output_gain"), f"{w}: use only one of 'gain' and 'output_gain' for the output multiplier")
                for key, lo, hi, default in (("gain", 0.1, 25.5, 1.0), ("dry", 0.0, 1.0, 0.0)):
                    source_key = "output_gain" if key == "gain" and (param_gain or "output_gain" in p) else key
                    v = p.get(source_key, default)
                    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                        ctx.error(_line(p, source_key), f"{w}: '{source_key}' must be a number {lo}..{hi}, got {v!r}")
                    else:
                        d[key] = float(v)
                mod.plugins[num] = d
            except _Bad:
                pass
        for num, d in mod.plugins.items():
            seen, nxt = {num}, d.get("output")
            while nxt:
                if nxt not in mod.plugins:
                    ctx.error(_line(entries, num), f"plugin {num}: 'output' {nxt} is not a plugin of this song")
                    break
                if nxt in seen:
                    ctx.error(_line(entries, num), f"plugin {num}: its outputs loop back to plugin {nxt}")
                    break
                seen.add(nxt)
                nxt = mod.plugins[nxt].get("output")
    spec = m.get("macros")
    if spec is not None:
        try:
            macros = _map(ctx, spec, _line(m, "macros"), "module.macros")
        except _Bad:
            macros = LMap()
        for key, text in macros.items():
            mt = re.fullmatch(r"SF([0-9A-Fa-f])", str(key))
            if not mt:
                ctx.error(_line(macros, key), f"module.macros: keys are SF0..SFF, got {key!r}")
            elif not isinstance(text, str) or not P.MACRO_RE.match(text):
                ctx.error(_line(macros, key), f"module.macros: {key} must be MIDI macro text like F0F080z, got {text!r}")
            else:
                mod.macros[int(mt.group(1), 16)] = text


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
    mod.ceiling = _soft(lambda: _int(ctx, m, 'ceiling', 1000, 96000, 18000, where), 18000)
    beat = _soft(lambda: _int(ctx, m, 'rows_per_beat', 1, 255, 4, where), 4)
    bar = _soft(lambda: _int(ctx, m, 'rows_per_bar', 1, 255, 16, where), 16)
    mod.row_highlight = (beat, bar)
    msg = m.get("message")
    mod.message = str(msg) if msg else ""
    if m.get("key") and not KEY_RE.fullmatch(str(m["key"]).strip()):
        ctx.error(_line(m, "key"), f"module.key: a key like 'A minor', 'F# major' or 'D dorian', got {m['key']!r}")
    elif m.get("key"):
        mod.key = str(m["key"]).strip()
    _plugins(ctx, m, mod)
    if any(ord(c) > 255 for c in mod.message):
        ctx.warn(_line(m, "message"), "module.message: characters outside Latin-1 are stored as ?")
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
            color = c.get("color")
            if "color" in c:
                if not (isinstance(color, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", color)):
                    ctx.error(_line(c, "color"), f'{w}: \'color\' is a quoted "#rrggbb" (unquoted, # starts a comment), got {color!r}')
                else:
                    ch.color = color.lower()
            _marks(ctx, c, w)
            plug = c.get("plugin", 0)
            if plug:
                if isinstance(plug, bool) or not isinstance(plug, int) or plug not in mod.plugins:
                    ctx.error(_line(c, "plugin"), f"{w}: 'plugin' must be a plugin number from module.plugins, got {plug!r}")
                else:
                    ch.plugin = plug
        except _Bad:
            pass
        mod.channels.append(ch)


SAMPLE_KEYS = ["file", "name", "volume", "global_volume", "pan", "base_note", "c5_speed", "loop",
               "sustain_loop", "vibrato", "bits", "stereo", "approved"]
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
_EDGES = {}      # Sample.source -> spectral_edge, cycles per stored frame
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
    _marks(ctx, m, where)
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
    smp.name = _text(ctx, m, "name", it_text(path.stem, 25), 25, where)
    smp.filename = path.name[:12]
    stereo = _bool(ctx, m, "stereo", False, where)
    smp.bits = _enum(ctx, m, "bits", {8: 8, 16: 16}, wav.out_bits, where)
    smp.rate = wav.rate
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
                   "filter_resonance", "filter_mode", "volume_envelope", "panning_envelope", "pitch_envelope",
                   "tuning", "keymap_file"]
FILTER_MODES = {"lowpass": 0, "highpass": 1}
KEYMAP_KEYS = ["notes", "sample", "transpose", "play_note"]
ENVELOPE_KEYS = ["nodes", "lfo", "loop", "sustain", "enabled", "carry", "filter"]
LFO_KEYS = {"shape": "sine", "period": 16, "depth": None, "centre": None, "delay": 0, "attack": 0, "points": 8, "seed": 0}
LFO_SHAPES = ("sine", "triangle", "square", "saw", "ramp", "random")


def lfo_nodes(spec, lo, hi):
    """`lfo:` -> (nodes, loop): `centre` held for `delay` ticks, the wave's depth growing over `attack` ticks, then one
    cycle of `period` ticks (`points` nodes, linear between, and the loop's end) looped for good. ValueError when it
    does not fit."""
    import math
    import random
    if not isinstance(spec, dict) or set(spec) - set(LFO_KEYS):
        raise ValueError(f"'lfo' is a mapping of {', '.join(LFO_KEYS)}; got {spec!r}")
    s = {**LFO_KEYS, **spec}
    if s["shape"] not in LFO_SHAPES:
        raise ValueError(f"lfo: shape is one of {', '.join(LFO_SHAPES)}; got {s['shape']!r}")
    for k in ("period", "delay", "attack", "points", "seed") + tuple(k for k in ("depth", "centre") if s[k] is not None):
        if isinstance(s[k], bool) or not isinstance(s[k], int):
            raise ValueError(f"lfo: {k} is a whole number; got {s[k]!r}")
    points, period, delay, attack = s["points"], s["period"], s["delay"], s["attack"]
    if not 2 <= points <= 23 or not points < period <= 9999 or not 0 <= delay <= 9999 or not 0 <= attack <= 9999:
        raise ValueError(f"lfo: points 2-23, period more than points up to 9999 ticks, delay and attack 0-9999 ticks; "
                         f"got {spec}")
    depth = s["depth"] if s["depth"] is not None else (hi - lo) // 4
    centre = s["centre"] if s["centre"] is not None else (hi - depth if lo == 0 else 0)
    if depth < 0 or not lo <= centre - depth <= centre + depth <= hi:
        raise ValueError(f"lfo: centre {centre} plus and minus depth {depth} leaves {lo}..{hi}")
    rng = random.Random(s["seed"])
    wave = {"sine": lambda p: math.sin(2 * math.pi * p), "triangle": lambda p: 1 - 4 * abs((p + 0.25) % 1 - 0.5),
            "square": lambda p: 1.0 if p < 0.5 else -1.0, "saw": lambda p: 2 * p - 1, "ramp": lambda p: 1 - 2 * p,
            }.get(s["shape"])
    cycle = [rng.uniform(-1, 1) for _ in range(points)] if wave is None else [wave(k / points) for k in range(points)]
    nodes = [(0, centre)]
    t = delay
    if delay:
        nodes.append((delay, centre))
    while True:
        full = t - delay >= attack
        for k, w in enumerate(cycle):
            tick = t + round(k * period / points)
            node = (tick, round(centre + depth * w * min(1.0, (tick - delay) / attack if attack else 1.0)))
            if tick > nodes[-1][0]:
                nodes.append(node)
            else:  # the cycle's first node takes the place of the start (or the delay's end)
                nodes[-1] = node
        if full:
            break
        t += period
    start = len(nodes) - points
    # the loop ends on the value it starts with, so it joins; its end tick plays too (IT's loops include it, as
    # libopenmpt plays them), so it sits one tick short of a whole period
    nodes.append((t + period - 1, round(centre + depth * cycle[0])))
    if len(nodes) > 25 or nodes[-1][0] > 9999:
        raise ValueError(f"lfo: {len(nodes)} nodes over {nodes[-1][0]} ticks; an envelope holds 25 over 9999 (fewer "
                         "points, a shorter attack or delay)")
    return [list(n) for n in nodes], (start, len(nodes) - 1)


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
    if "lfo" in m:
        if any(k in m for k in ("nodes", "loop", "sustain")):
            ctx.error(_line(m, "lfo"), f"{where}: 'lfo' makes its own nodes and loop: give no nodes, loop or sustain")
            raise _Bad
        try:
            made, loop = lfo_nodes(m["lfo"], lo, hi)
        except ValueError as e:
            ctx.error(_line(m, "lfo"), f"{where}: {e}")
            raise _Bad
        nodes = LSeq()
        for n in made:
            node = LSeq()
            node.extend(n)
            nodes.append(node)
        nodes.lines = [_line(m, "lfo")] * len(made)
        m2 = LMap()
        m2.update({k: v for k, v in m.items() if k != "lfo"}, loop=list(loop))
        m2.lines, m2.line = m.lines, m.line
        m = m2
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


def read_scl(text):
    """A Scala scale (huygens-fokker.org/scala/scl_format.html): lines starting with '!' are comments; the first other
    line is the description, the next the number of notes, then one pitch a line, cents when it holds a '.', else a
    ratio a/b or a whole number n (n/1), anything after it ignored. At most 256 notes, as OpenMPT's ImportScl takes.
    Returns the cents of degrees 1..N (the last is the period). ValueError on a malformed file."""
    lines = [t for t in text.splitlines() if not t.lstrip().startswith("!")]
    rest = [t.split() for t in lines[1:] if t.strip()]
    if not lines or not rest or not rest[0][0].isdigit():
        raise ValueError("a .scl has a description line, then the number of notes")
    n, pitches = int(rest[0][0]), [r[0] for r in rest[1:]]
    if n != len(pitches) or not 1 <= n <= 256:
        raise ValueError(f"the .scl says {n} notes and lists {len(pitches)} (1 to 256 notes)")
    cents = []
    for p in pitches:
        try:
            if "." in p:
                cents.append(float(p))
                continue
            a, _, b = p.partition("/")
            a, b = int(a), int(b or 1)
        except ValueError:
            raise ValueError(f"the .scl pitch {p!r} is neither cents (with a '.') nor a ratio a/b") from None
        if a <= 0 or b <= 0 or max(a, b) > 2 ** 31 - 1:
            raise ValueError(f"the .scl ratio {p} is not above 0 (or its numbers pass 2147483647)")
        cents.append(1200 * math.log2(a / b))
    return cents


def read_kbm(text):
    """A Scala keyboard mapping (.kbm): map size, first and last MIDI note to retune, the middle note (where the first
    entry goes), the reference note and its frequency, the degree that is the formal octave, then the map, one degree or
    'x' (unmapped) per key; entries left out at the end are unmapped. ValueError on a malformed file."""
    vals = [t.split()[0] for t in text.splitlines() if t.strip() and not t.lstrip().startswith("!")]
    try:
        size, first, last, middle, ref = (int(v) for v in vals[:5])
        freq, octave = float(vals[5]), int(vals[6])
        mapping = [None if v.lower() == "x" else int(v) for v in vals[7:]]
    except (ValueError, IndexError):
        raise ValueError("a .kbm has seven numbers (map size, first, last, middle and reference note, its frequency, the "
                         "formal octave degree) and then the map, a degree or x a key") from None
    if len(mapping) > size or freq <= 0:
        raise ValueError(f"the .kbm lists {len(mapping)} keys for a map of {size}" if freq > 0 else "the .kbm's frequency is not above 0")
    return {"size": size, "first": first, "last": last, "middle": middle, "ref": ref, "freq": freq, "octave": octave,
            "map": mapping + [None] * (size - len(mapping))}


def tuning_ratios(cents, kbm=None):
    """Per IT note 0-119 (C-5 = MIDI 60) the pitch of the scale (`read_scl`) laid on the keys by `kbm` (`read_kbm`), as
    a ratio to the note's 12-TET pitch at A-5 = 440 Hz; None for a key the map leaves out. Without a map, OpenMPT's way
    (CTuning, as its .scl import makes it): degree 0 on C-5 at its own pitch, a degree a key. Only scales that repeat at
    the octave over 12 keys (a 2/1 period; a map of 12 keys whose formal octave is the scale's size), so every key of a
    pitch class has one ratio. ValueError otherwise."""
    n = len(cents)
    if abs(cents[-1] - 1200) > 1e-6:
        raise ValueError(f"only scales that repeat at the octave: the last degree is {cents[-1]:.3f} cents, not 2/1 (1200)")
    if kbm is None:
        if n != 12:
            raise ValueError(f"a {n}-note scale needs a keyboard map (keymap_file: a .kbm) to lay it on the 12 keys of an octave")
        kbm = {"size": 12, "first": 0, "last": 127, "middle": 60, "ref": 60, "freq": 440 * 2 ** (-9 / 12), "octave": 12,
               "map": list(range(12))}
    if kbm["size"] != 12 or kbm["octave"] != n:
        raise ValueError(f"only keyboard maps that repeat every 12 keys with the scale's {n} degrees as their octave "
                         f"(this one: {kbm['size']} keys, formal octave degree {kbm['octave']})")
    degree = [0.0] + cents[:-1]

    def at(key):
        o, i = divmod(key - kbm["middle"], 12)
        m = kbm["map"][i]
        if m is None:
            return None
        d = m + o * n
        return degree[d % n] + d // n * 1200
    ref = at(kbm["ref"])
    if ref is None:
        raise ValueError(f"the .kbm leaves its reference note {kbm['ref']} unmapped")
    out = []
    for key in range(120):
        c = at(key) if kbm["first"] <= key <= kbm["last"] else None
        out.append(None if c is None else kbm["freq"] * 2 ** ((c - ref) / 1200) / (440 * 2 ** ((key - 69) / 12)))
    return out


def _tuning(ctx, m, keymap, base_dir, where):
    """`tuning:` (a .scl beside the song) and `keymap_file:` (a .kbm): the ratio per key, from each key's played note
    (after transpose or play_note); keys the map leaves out are made silent in `keymap`."""
    if "tuning" not in m:
        if "keymap_file" in m:
            ctx.error(_line(m, "keymap_file"), f"{where}: 'keymap_file' lays a 'tuning' on the keys; give the .scl too")
        return None
    texts = []
    for key in ("tuning", "keymap_file"):
        if m.get(key) is None:
            texts.append(None)
            continue
        p = Path(base_dir) / str(m[key])
        try:
            texts.append(p.read_text(encoding="latin-1"))
        except OSError as e:
            ctx.error(_line(m, key), f"{where}: {key}: cannot read {p}: {e.strerror or e}")
            raise _Bad
    try:
        ratios = tuning_ratios(read_scl(texts[0]), read_kbm(texts[1]) if texts[1] is not None else None)
    except ValueError as e:
        ctx.error(_line(m, "keymap_file" if "kbm" in str(e) and "keymap_file" in m else "tuning"), f"{where}: {e}")
        raise _Bad
    out = [1.0] * 120
    for key, (note, s) in enumerate(keymap):
        if s:
            r = ratios[note]
            if r is None:
                keymap[key] = (note, 0)
            else:
                out[key] = r
    return out


def _instrument(ctx, num, spec, line, samples_by_name, sample_numbers, base_dir="."):
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
    ins.tuning = _tuning(ctx, m, keymap, base_dir, where)
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
    if m.get("filter_mode") is not None:
        if m["filter_mode"] not in FILTER_MODES:
            ctx.error(_line(m, "filter_mode"), f"{where}: filter_mode is lowpass or highpass, got {m['filter_mode']!r}")
        else:
            ins.filter_mode = FILTER_MODES[m["filter_mode"]]
            if ins.filter_cutoff is None and ins.filter_resonance is None:
                ctx.warn(_line(m, "filter_mode"), f"{where}: filter_mode {m['filter_mode']} filters nothing until a "
                         "cutoff is set (filter_cutoff, filter_resonance or a Zxx)")
    for key, kind in (("volume_envelope", "volume"), ("panning_envelope", "panning"), ("pitch_envelope", "pitch")):
        setattr(ins, key, _soft(lambda: _envelope(ctx, m.get(key), _line(m, key), kind, f"{where} {key}")))
    if len(ctx.errors) > n_errors:
        raise _Bad
    return ins


_ROW_PREFIX = re.compile(r"^\s*(\d+)\s*:(.*)$")


MARKS_BY = ("you", "agent", "you and agent")


def _marks(ctx, m, where, by=False):
    """The marks an entry may carry (they change nothing in the module): `approved` (the owner's: an agent's tools leave
    it alone) and, on a pattern, `by` (who wrote it: you, agent, or you and agent)."""
    _soft(lambda: _bool(ctx, m, "approved", False, where))
    if by and m.get("by") is not None and m.get("by") not in MARKS_BY:
        ctx.error(_line(m, "by"), f"{where}: 'by' must be one of {', '.join(MARKS_BY)}, got {m.get('by')!r}")


LANE_KEYS = ["target", "channel", "rows", "from", "to", "shape", "every"]


def _lanes(ctx, m, where, grid, lines, channels):
    """A pattern's `automation:` lanes on its parsed `grid`: each lane is the Pattern tab's AUTOMATE (compose.automate,
    the same function) kept in the song and redone on every compile. A lane owns its column (the effect column, or the
    volume column for `v`) on its channel and rows: a cell written there in `data` is an error, as is a second lane
    there. Returns (rows with the lanes' cells, {(row, channel): (column, lane number)})."""
    from . import compose
    spec = m.get("automation") if m is not None else None
    if spec is None:
        return grid, {}
    if not isinstance(spec, LSeq):
        ctx.error(_line(m, "automation"), f"{where}: 'automation' is a list of lanes ({{target, channel, from, to, ...}})")
        raise _Bad
    rows, owned, names = [list(r) for r in grid], {}, [str(c.name) for c in channels]
    at = lambda r: lines[r] if r < len(lines) else _line(m, "automation")
    for i, (entry, eline) in enumerate(zip(spec, spec.lines), 1):
        w = f"{where} automation lane {i}"
        e = _map(ctx, entry, eline, w)
        _check_keys(ctx, e, LANE_KEYS, w)
        target = str(e.get("target", ""))
        if target not in compose.TARGETS:
            ctx.error(_line(e, "target") or e.line, f"{w}: 'target' is one of {', '.join(compose.TARGETS)}, got {e.get('target')!r}")
            raise _Bad
        ch = e.get("channel", 1)
        if isinstance(ch, int) and not isinstance(ch, bool) and 1 <= ch <= len(rows[0]):
            ch -= 1
        elif str(ch) in names:
            ch = names.index(str(ch))
        else:
            ctx.error(_line(e, "channel") or e.line, f"{w}: 'channel' is a channel number (1-{len(rows[0])}) or name, got {ch!r}")
            raise _Bad
        span = e.get("rows", [0, len(rows) - 1])
        if not (isinstance(span, list) and len(span) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in span)
                and 0 <= span[0] < span[1] < len(rows)):
            ctx.error(_line(e, "rows") or e.line, f"{w}: 'rows' is [first, last], two rows of the pattern's {len(rows)}, got {span!r}")
            raise _Bad
        r0, r1 = span
        frm, to = _int(ctx, e, "from", 0, 255, None, w), _int(ctx, e, "to", 0, 255, None, w)
        every = _int(ctx, e, "every", 1, 64, 1, w)
        shape = _enum(ctx, e, "shape", {s: s for s in compose.CURVES}, "linear", w)
        col = "v" if target == "v" else "e"
        chans = [ch]
        for r in range(r0, r1 + 1):
            if (r, ch) in owned and owned[(r, ch)][0] == col:
                ctx.error(eline, f"{w}: row {r}, channel {ch + 1} already belongs to lane {owned[(r, ch)][1]}")
                raise _Bad
            c = rows[r][ch]
            if (c.volcmd is not None) if col == "v" else (c.effect or c.param):
                ctx.error(at(r), f"{where}, row {r}, channel {ch + 1}: the {'volume column' if col == 'v' else 'effect column'} "
                                 f"belongs to automation lane {i} (rows {r0}-{r1}): leave it empty in 'data'")
                raise _Bad
            owned[(r, ch)] = (col, i)
        try:
            cells, _ = compose.automate(rows, chans, r0, r1, target, frm, to, shape, every)
        except ValueError as err:
            ctx.error(eline, f"{w}: {err}")
            raise _Bad
        for c in cells:
            rows[c["row"]][c["ch"]] = notation.parse_cell(c["cell"])
    return rows, owned


def _pattern(ctx, name, spec, line, num_channels, channels=()):
    where = f"pattern '{name}'"
    if isinstance(spec, LStr):
        data, rows = spec, None
        m = None
    else:
        m = _map(ctx, spec, line, where)
        _check_keys(ctx, m, ["rows", "data", "by", "approved", "automation"], where)
        _marks(ctx, m, where, by=True)
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
        rows, lanes = _lanes(ctx, m, where, hit[0], hit[1], channels)
        return Pattern(str(name), rows, lanes), hit[1]
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
    rows, lanes = _lanes(ctx, m, where, grid, lines, channels)
    return Pattern(str(name), rows, lanes), lines


def _check_pattern_refs(ctx, mod, pat, lines, where, declared, lowest, highest):
    """Cross-reference checks that need the whole module. `declared`: instrument (or, in sample
    mode, sample) numbers defined in the song. `lowest` and `highest` collect sample number -> (the lowest or highest
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
                if smp and (smp not in highest or play > highest[smp][0]):
                    highest[smp] = (play, line, at)
            letter = chr(ord("A") + cell.effect - 1) if cell.effect else ""
            if letter == "B" and cell.param >= len(mod.orders):
                ctx.error(line, f"{at}: B{cell.param:02X} jumps to order {cell.param} but the order list has {len(mod.orders)} entries")
            elif letter == "M" and cell.param > 0x40:
                ctx.error(line, f"{at}: M{cell.param:02X} channel volume must be 00..40 (hex)")
            elif letter == "V" and cell.param > 0x80:
                ctx.error(line, f"{at}: V{cell.param:02X} global volume must be 00..80 (hex)")
            elif letter == "C" and cell.param >= MAX_ROWS:
                ctx.error(line, f"{at}: C{cell.param:02X} breaks to row {cell.param}; the parameter is hex (C10 = row 16)")


def _version(text):
    """(1, 2, 0) of '1.2', '1.2.0' or the start of '1.2.0rc1'; None for anything else."""
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return m and tuple(int(g or 0) for g in m.groups())


def _requires(ctx, tree):
    """`requires: X.Y`, the oldest VultureTracker that reads the song. False when this app is older: that is then the one
    error, not the unknown keys a newer song may hold."""
    if tree.get("requires") is None:
        return True
    text, line = str(tree["requires"]).strip(), _line(tree, "requires")
    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", text):
        ctx.error(line, f"'requires' must be a version like '1.2' (quoted), got {tree['requires']!r}")
    elif _version(text) > _version(__version__):
        ctx.error(line, f"this song needs VultureTracker {tree['requires']} or newer; this is {__version__} "
                        f"(https://github.com/shadoh420/VultureTracker/releases)")
        return False
    return True


def compile_tree(tree, ctx, base_dir) -> Module:
    mod = Module()
    if not isinstance(tree, LMap):
        ctx.error(1, "the song file must be a mapping with module, samples, instruments, patterns, orders")
        return mod
    if not _requires(ctx, tree):
        return mod
    _check_keys(ctx, tree, ["module", "samples", "instruments", "patterns", "orders", "sections", "requires"], "the song file")
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
                mod.instruments[num - 1] = _instrument(ctx, num, spec, line, samples_by_name, sample_numbers, base_dir)
            except _Bad:
                mod.instruments[num - 1] = Instrument(name="(invalid)")
        for i, ins in enumerate(mod.instruments):
            if ins is None:
                mod.instruments[i] = Instrument()  # gap: empty slot
        copies = {(s, round(ins.tuning[k], 9)) for ins in mod.instruments if ins.tuning
                  for k, (_, s) in enumerate(ins.keymap) if s and abs(ins.tuning[k] - 1) > 1e-9}
        if copies and len(mod.samples) + len(copies) > MAX_NUMBER:
            ctx.error(_line(tree, "instruments"), f"the tunings need {len(copies)} detuned copies of their samples, "
                                                  f"{len(mod.samples) + len(copies)} samples in all; IT holds {MAX_NUMBER}")

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
    if len(pats) > ORDER_SKIP:
        ctx.error(_line(tree, 'patterns'), 'at most 254 patterns; order values 254 and 255 are reserved')
    for name, spec in pats.items():
        if str(name) in pat_index:
            first = next(k for k in pats if str(k) == str(name))
            ctx.error(_line(pats, name), f"pattern {name!r} has the same name as pattern {first!r} (line "
                                        f"{_line(pats, first)}): rename one")
            continue
        try:
            pat, lines = _pattern(ctx, str(name), spec, _line(pats, name), num_channels, mod.channels)
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

    from .arrangement import validate_sections
    try:
        validate_sections(tree.get('sections'), len(mod.orders))
    except ValueError as e:
        ctx.error(_line(tree, 'sections'), str(e))

    lowest, highest = {}, {}
    from .itwriter import PATTERN_BYTES, packed_size
    for pat, lines in zip(mod.patterns, pat_lines):
        _check_pattern_refs(ctx, mod, pat, lines, f"pattern '{pat.name}'",
                            instrument_numbers if mod.instruments is not None else sample_numbers, lowest, highest)
        size = packed_size(pat, len(mod.channels))
        if size > PATTERN_BYTES:
            ctx.error(_line(pats, pat.name), f"pattern '{pat.name}': {size} bytes of cell data; IT holds at most "
                                             f"{PATTERN_BYTES} per pattern (fewer rows, channels or filled cells)")
    _check_images(ctx, mod, lowest, highest)
    _check_rings(ctx, mod, lowest, highest)
    return mod


IMAGE_LIMIT = -60   # dB: the loudest interpolation images a sample's lowest note may leave under 20 kHz


def _check_images(ctx, mod, lowest, highest):
    """Warn when a note plays a sample so far below its stored rate that the player's interpolation images reach the
    audible band (resample.image_level): a bright sample stored at 44.1 kHz does from about four semitones down. And
    when a note above the root lifts the sample's content over `module: ceiling` (AGENTS.md's rule: bandwidth times the
    transposition ratio under about 18 kHz; resample.spectral_edge)."""
    try:
        from .resample import image_level, spectral_edge
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
    # ponytail: the highest note only; slides, vibrato, arpeggios and pitch envelopes that go higher are not checked
    for num, (note, line, at) in sorted(highest.items()):
        smp = mod.samples[num - 1] if num <= len(mod.samples) else None
        rate = smp.c5_speed * 2 ** ((note - 60) / 12) if smp else 0
        if not smp or not smp.data or rate <= (smp.rate or smp.c5_speed) * 1.0001:  # at or below its root
            continue
        edge = _EDGES.get(smp.source, _UNSEEN) if smp.source else _UNSEEN
        if edge is _UNSEEN:
            edge = spectral_edge(smp.data)
            if smp.source:
                _remember(_EDGES, smp.source, edge)
        top = edge * rate if edge else 0
        if top > mod.ceiling:
            up = 12 * math.log2(rate / (smp.rate or smp.c5_speed))
            ctx.warn(line, f"{at}: {notation.format_note(note)} plays sample {num:02d} '{smp.name}' {up:.0f} semitones "
                           f"above its root, which lifts its content to {top / 1000:.1f} kHz, over the ceiling of "
                           f"{mod.ceiling / 1000:g} kHz (module ceiling); play it lower, add a higher multisample, or "
                           f"store it narrower (bandlimit or resample in its recipe's fx, or a lower sample_rate)")


RING_CENTS = 30        # cents: how far a drum's ring tone may sit from the nearest tone of the song's key
KEY_CONFIDENCE = 0.7   # the Krumhansl-Kessler r under which key_report's estimate is no key to check against
_RINGS = {}            # Sample.source -> resample.ring_partials


def _check_rings(ctx, mod, lowest, highest):
    """Warn when a sample the patterns play at one note only (a drum) rings at a steady partial more than RING_CENTS
    from every tone of the song's key: `module: key`, else key_report's estimate when its r reaches KEY_CONFIDENCE.
    Partials from 50 Hz to 5 kHz as they sound at that note (resample.ring_partials); the loudest such one is named."""
    one = {n: v for n, v in lowest.items() if n in highest and highest[n][0] == v[0]}
    if not one:
        return
    try:
        from .resample import ring_partials
        from .compose import NAMES, key_report, scale_of
    except ImportError:     # no numpy, nothing to measure with
        return
    if mod.key:
        scale, said = scale_of(mod.key), f"{mod.key} (module key)"
    else:
        rep = key_report(mod)
        if not rep["estimate"] or rep["estimate_r"] < KEY_CONFIDENCE:
            return
        scale, said = scale_of(rep["estimate"]), f"{rep['estimate']} (estimated from the notes, r {rep['estimate_r']})"
    # ponytail: the note as written; slides, arpeggios, pitch envelopes and an instrument's tuning are not followed
    for num, (note, line, at) in sorted(one.items()):
        smp = mod.samples[num - 1] if num <= len(mod.samples) else None
        if not smp or not smp.data:
            continue
        parts = _RINGS.get(smp.source, _UNSEEN) if smp.source else _UNSEEN
        if parts is _UNSEEN:
            parts = ring_partials(smp.data, smp.rate or smp.c5_speed)
            if smp.source:
                _remember(_RINGS, smp.source, parts)
        rate = smp.c5_speed * 2 ** ((note - 60) / 12)
        off = []
        for nu, db in parts:
            hz = nu * rate
            if not 50 <= hz <= 5000:
                continue
            m = 12 * math.log2(hz / 440) + 69
            far = min(min((m - p) % 12, (p - m) % 12) for p in scale) * 100
            if far > RING_CENTS:
                off.append((hz, m, db, far))
        if off:
            hz, m, db, far = off[0]
            n = round(m)
            more = f" ({len(off) - 1} more such partial{'s' * (len(off) > 2)})" if len(off) > 1 else ""
            ctx.warn(line, f"{at}: sample {num:02d} '{smp.name}', played only at {notation.format_note(note)}, rings "
                           f"at {hz:.1f} Hz ({NAMES[n % 12]}{n // 12 - 1} {round((m - n) * 100):+d} cents), {abs(db):.0f} dB "
                           f"under its loudest band, {far:.0f} cents from the nearest tone of {said}{more}; it may beat "
                           f"against the pitched parts: play it at another note, retune it (c5_speed), or pick another")


MAX_YAML_DEPTH = 100  # real songs nest six levels


class BoundedLoader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    """libyaml's loader when PyYAML has it (about ten times faster; the same nodes, marks and styles, so the same module),
    refusing text nested deeper than MAX_YAML_DEPTH before composing it: libyaml's composer recurses on the C stack once
    per level, and on Windows under Python 3.10-3.13 a song 5000 levels deep overflows the main thread's 1 MB stack and
    kills the process before any RecursionError. Its parser does not recurse, so the depth is counted from its events."""

    def __init__(self, stream):
        if hasattr(yaml, "CSafeLoader") and isinstance(stream, (str, bytes)):  # pure Python raises RecursionError itself
            depth = 0
            for event in yaml.parse(stream, Loader=yaml.CSafeLoader):
                if isinstance(event, (yaml.SequenceStartEvent, yaml.MappingStartEvent)):
                    depth += 1
                    if depth > MAX_YAML_DEPTH:
                        raise yaml.composer.ComposerError(None, None, f"the YAML nests too deeply (more than "
                                                          f"{MAX_YAML_DEPTH} levels)", event.start_mark)
                elif isinstance(event, (yaml.SequenceEndEvent, yaml.MappingEndEvent)):
                    depth -= 1
        super().__init__(stream)


class _LOADER(BoundedLoader):
    pass


_LOADER.add_implicit_resolver('tag:yaml.org,2002:int', re.compile(r'[-+]?0[0-9]+$'), list('-+0123456789'))


def load_song_text(text, base_dir=".", filename="<song>"):
    """Parse and validate song YAML. Returns (Module, warnings); raises SongError listing every problem found."""
    ctx = Ctx(filename)
    try:
        node = yaml.compose(text, Loader=_LOADER)
        tree = _convert(node, ctx) if node is not None else None
    except yaml.YAMLError as e:
        mark, pos = getattr(e, "problem_mark", None), getattr(e, "position", None)
        if mark:
            line = mark.line + 1
        elif isinstance(pos, int):  # a ReaderError (a control character): libyaml counts UTF-8 bytes, PyYAML characters
            src = text.encode("utf-8") if getattr(e, "encoding", None) == "?" else text
            line = src[:pos].count(b"\n" if isinstance(src, bytes) else "\n") + 1
        else:
            line = 1
        raise SongError([f"{filename}:{line}: error: YAML syntax: {getattr(e, 'problem', e)}"])
    except RecursionError:
        raise SongError([f"{filename}:1: error: the YAML nests too deeply, or an alias refers to its own anchor"])
    if node is None:
        raise SongError([f"{filename}:1: error: the song file is empty"])
    mod = compile_tree(tree, ctx, Path(base_dir))
    if ctx.errors:
        raise SongError(ctx.errors, ctx.warnings)
    return mod, ctx.warnings


def read_song_text(path):
    """The song file's text; bytes that are not UTF-8 are a SongError at their line."""
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        line = raw.count(b"\n", 0, e.start) + 1
        raise SongError([f"{path}:{line}: error: not UTF-8 text (byte 0x{raw[e.start]:02x}): save the file as UTF-8"])


def load_song(path):
    path = Path(path)
    return load_song_text(read_song_text(path), path.parent, str(path))
