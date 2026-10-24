"""Plain functions over the song document (a dict mirroring the YAML), shaped so each can later
become an MCP tool. The YAML text stays the source of truth: every edit goes through a dict that
is saved back as YAML, and validation always re-parses that YAML so errors carry line numbers."""
import os
import re
from pathlib import Path

import yaml

from .itwriter import write_it
from .fileio import atomic_write, protect_outputs, wav_bytes
from .song import BoundedLoader, SongError, it_text, load_song_text, read_song_text


# ---------------------------------------------------------------- YAML round-trip

class SafeDumper(yaml.SafeDumper):
    """yaml.SafeDumper that quotes the strings the song's loader (_Loader below) reads as numbers: a name "08" is
    written '08' and comes back a string, not 8."""


SafeDumper.add_implicit_resolver('tag:yaml.org,2002:int', re.compile(r'[-+]?0[0-9]+$'), list('-+0123456789'))


def safe_dump(data, **kw):
    """yaml.safe_dump for what the song's loader reads back (sample entries, channels, recipe entries)."""
    return yaml.dump(data, Dumper=SafeDumper, **kw)


class _Dumper(SafeDumper):
    pass


def _str(dumper, s):
    style = "|" if "\n" in s else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)


def _list(dumper, seq):
    flow = all(not isinstance(x, (dict, list)) for x in seq) or all(
        isinstance(x, list) and all(not isinstance(y, (dict, list)) for y in x) for x in seq) and len(seq) <= 25
    return dumper.represent_sequence("tag:yaml.org,2002:seq", seq, flow_style=flow)


def _dict(dumper, d):
    # Small leaf mappings (loops, keymap entries, channels) read best on one line.
    flow = len(d) <= 4 and all(not isinstance(v, (dict, list)) and not (isinstance(v, str) and "\n" in v) for v in d.values())
    return dumper.represent_mapping("tag:yaml.org,2002:map", d.items(), flow_style=flow)


_Dumper.add_representer(str, _str)
_Dumper.add_representer(list, _list)
_Dumper.add_representer(dict, _dict)


def to_yaml(song: dict) -> str:
    return yaml.dump(song, Dumper=_Dumper, sort_keys=False, width=120, allow_unicode=False)


class _Loader(BoundedLoader):
    pass


def _int(loader, node):
    """An int scalar as the compiler reads it: '08', '010' and '0125' are decimal, not YAML 1.1 octal."""
    if re.fullmatch(r"[-+]?0\d+", node.value):
        return int(node.value, 10)
    return yaml.SafeLoader.construct_yaml_int(loader, node)


_Loader.add_constructor("tag:yaml.org,2002:int", _int)
_Loader.add_implicit_resolver('tag:yaml.org,2002:int', re.compile(r'[-+]?0[0-9]+$'), list('-+0123456789'))


def from_yaml(text: str) -> dict:
    return yaml.load(text, Loader=_Loader)


def load(path) -> dict:
    return from_yaml(Path(path).read_text(encoding="utf-8"))


def save(song: dict, path):
    atomic_write(Path(path), to_yaml(song).encode("utf-8"))  # LF on every platform (write_text writes CRLF on Windows)


# ---------------------------------------------------------------- editing

def new_song(title="Untitled", channels=8, tempo=125, speed=6) -> dict:
    return {
        "module": {"title": title, "tempo": tempo, "speed": speed, "global_volume": 128, "mix_volume": 48,
                   "channels": [{"name": f"Ch {i + 1}", "pan": 32} for i in range(channels)]},
        "samples": {},
        "instruments": {},
        "patterns": {},
        "orders": [],
    }


def add_sample(song, number: int, file: str, **opts):
    song.setdefault("samples", {})[number] = {"file": file, **opts}
    return song


def add_instrument(song, number: int, **spec):
    if song.get("instruments") is None:
        song["instruments"] = {}
    song["instruments"][number] = spec
    return song


def set_pattern(song, name: str, data: str, rows: int | None = None):
    pat = {"data": data if data.endswith("\n") else data + "\n"}
    if rows is not None:
        pat = {"rows": rows, **pat}
    song.setdefault("patterns", {})[name] = pat
    return song


def set_orders(song, orders: list):
    song["orders"] = list(orders)
    return song


# ---------------------------------------------------------------- compile / verify

def _load(song_or_path, base_dir=None):
    """Accepts a path to a song file, YAML text, or a song dict. Returns (text, base_dir, filename)."""
    if isinstance(song_or_path, dict):
        return to_yaml(song_or_path), Path(base_dir or "."), "<song>"
    p = Path(song_or_path)
    if isinstance(song_or_path, Path) or "\n" not in str(song_or_path) and (p.suffix.lower() in (".yaml", ".yml")
                                                                            or os.path.isfile(p)):
        return read_song_text(p), Path(base_dir) if base_dir else p.parent, str(p)
    return str(song_or_path), Path(base_dir or "."), "<song>"


_WRITTEN_BY = re.compile(r"#\s*written by VultureTracker\s+(\S+)\s*$")


def written_by(text):
    """The version a song's `# written by VultureTracker X.Y.Z` line names (among its leading comments), or None."""
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return None
        m = _WRITTEN_BY.match(s)
        if m:
            return m.group(1)
    return None


def written_by_line():
    from . import __version__
    return f"# written by VultureTracker {__version__}\n"


def refresh_written_by(text):
    """The song text with its `# written by` line naming this version, when it has one naming another: songs that never
    had the line, and those already at this version, come back as they are (no churn in a committed song's diff)."""
    from . import __version__
    old = written_by(text)
    if old is None or old == __version__:
        return text
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if _WRITTEN_BY.match(line.strip()):
            end = line[len(line.rstrip("\r\n")):]
            lines[i] = written_by_line().rstrip("\n") + end
            break
    return "".join(lines)


def check(song_or_path, base_dir=None) -> dict:
    """Validate a song: {ok, errors, warnings, summary (when ok), written_by (the version its `# written by
    VultureTracker` line names, or None)}."""
    try:
        text, bdir, name = _load(song_or_path, base_dir)
    except SongError as e:
        return {"ok": False, "errors": e.errors, "warnings": e.warnings, "written_by": None}
    try:
        mod, warnings = load_song_text(text, bdir, name)
    except SongError as e:
        return {"ok": False, "errors": e.errors, "warnings": e.warnings, "written_by": written_by(text)}
    return {"ok": True, "errors": [], "warnings": warnings, "summary": summarize(mod), "written_by": written_by(text)}


def summarize(mod) -> dict:
    return {
        "title": mod.title,
        "channels": len(mod.channels),
        "instruments": len(mod.instruments) if mod.instruments is not None else 0,
        "samples": len(mod.samples),
        "patterns": len(mod.patterns),
        "orders": [o for o in mod.orders],
        "pattern_rows": [len(p.rows) for p in mod.patterns],
        "instrument_names": [i.name for i in mod.instruments or []],
        "sample_names": [s.name for s in mod.samples],
    }


def compile_song(song_or_path, base_dir=None, *, render_timing=False):
    """Returns (it_bytes, module, warnings). Raises SongError.

    render_timing enables export-only sampled passages for bounded sub-tick
    performance. Strict editing/validation callers retain the default refusal.
    """
    text, bdir, name = _load(song_or_path, base_dir)
    mod, warnings = load_song_text(text, bdir, name, render_timing=render_timing)
    return write_it(mod), mod, warnings


def prepare_playback(song_or_path, base_dir=None, sample_rate=44100):
    """Prepare, but do not play, {backing_it, plan, view, module, warnings}.

    sample_rate is the actual mixer rate (including offline oversampling).
    Native score bytes and their exact plan are one playback input, never a
    standalone IT export. Unsupported native planning raises SongError without
    falling back to strict projection. Legacy songs return their unchanged IT
    with plan/view None. Existing loaders and compile_song remain strict.
    """
    if type(sample_rate) is not int or not 8000 <= sample_rate <= 384000:
        raise ValueError('sample_rate must be an integer mixer rate in 8000..384000')
    text, bdir, name = _load(song_or_path, base_dir)
    mod, warnings = load_song_text(text, bdir, name, native_score_rate=sample_rate)
    native = mod.native_score or {}
    return {'backing_it': write_it(mod, _native_backing=True), 'plan': native.get('plan'),
            'view': native.get('view'), 'module': mod, 'warnings': warnings}


def output_sources(song_or_path, base_dir=None):
    text, folder, name = _load(song_or_path, base_dir)
    doc = from_yaml(text)
    sources = [folder / str(v['file']) for v in (doc.get('samples') or {}).values()
               if isinstance(v, dict) and v.get('file')]
    if name != '<song>':
        sources.append(Path(name))
    return sources


def build(song_or_path, out_path, base_dir=None) -> dict:
    """Compile to .it, then load it back with libopenmpt and compare structure to the song."""
    from .openmpt import LoadedModule
    data, mod, warnings = compile_song(song_or_path, base_dir, render_timing=True)
    protect_outputs([out_path], output_sources(song_or_path, base_dir))
    expected = summarize(mod)
    with LoadedModule(data) as lm:
        got = lm.info()
    mismatches = []
    for key in ("instruments", "samples", "patterns", "pattern_rows", "instrument_names", "sample_names"):
        e, g = expected[key], got[key]
        if key.endswith("_names"):  # libopenmpt drops a name's trailing spaces
            e, g = [n.rstrip() for n in e], [n.rstrip() for n in g]
        if e != g:
            mismatches.append(f"{key}: song has {expected[key]}, libopenmpt reports {got[key]}")
    # libopenmpt shows the order list up to the end marker; skips (+++ = 254) are listed, '---' ends it.
    exp_orders = []
    for o in expected["orders"]:
        if o == 255:
            break
        exp_orders.append(o)
    if got["orders"][:len(exp_orders)] != exp_orders:
        mismatches.append(f"orders: song has {exp_orders}, libopenmpt reports {got['orders']}")
    atomic_write(out_path, data)
    return {"path": str(out_path), "bytes": len(data), "warnings": warnings, "libopenmpt": got, "mismatches": mismatches}


def render(it_or_song, wav_path, repeat=0, rate=44100, base_dir=None, oversample=2, sources=()) -> float:
    """Render an .it file (or a song file, compiled in memory) to a WAV, mixed at `oversample` times `rate` and
    band-limited down (see LoadedModule.render). Returns seconds rendered."""
    from .openmpt import LoadedModule, mix_rate
    plan = None
    p = Path(str(it_or_song))
    if isinstance(it_or_song, (str, Path)) and p.suffix.lower() in (".it", ".mod", ".xm", ".s3m", ".mptm"):
        protected = [p, *sources]
        data = p.read_bytes()
    else:
        protected = [*output_sources(it_or_song, base_dir), *sources]
        prepared = prepare_playback(it_or_song, base_dir, mix_rate(rate, oversample))
        data, plan = prepared['backing_it'], prepared['plan']
    protect_outputs([wav_path], protected)
    with LoadedModule(data, rate, oversample, plan=plan) as lm:
        pcm = lm.render(rate, repeat, oversample=oversample)
    protect_outputs([wav_path], protected)
    atomic_write(wav_path, wav_bytes(pcm, rate))
    return len(pcm) / 4 / rate


def measure(source, channels=None, orders=None, rate=44100, base_dir=None) -> dict:
    """Loudness (LUFS), true peak, sample peak and stereo correlation (dsp.measure_mix) of a WAV, a module or a song
    (compiled in memory and rendered as `render` does). `channels`: only these (0-based) play, the others disabled
    with IT's channel-disable bit; `orders`: an order slice (start, stop) of a song."""
    import numpy as np
    from . import dsp
    from .openmpt import LoadedModule, mix_rate
    plan = None
    p = Path(str(source))
    if isinstance(source, (str, Path)) and p.suffix.lower() == ".wav":
        from .wavload import read_wav
        w = read_wav(p)
        x = np.array(w.channels, dtype=np.float64) / float(1 << (w.out_bits - 1))
        return dsp.measure_mix(np.vstack([x, x]) if x.shape[0] == 1 else x, w.rate)
    if isinstance(source, (str, Path)) and p.suffix.lower() in (".it", ".mod", ".xm", ".s3m", ".mptm"):
        data = p.read_bytes()
    else:
        if orders:
            text, _, _ = _load(source, base_dir)
            if from_yaml(text).get('score') is None:
                source = tryout_song(source, orders, base_dir=base_dir)
        prepared = prepare_playback(source, base_dir, mix_rate(rate, 2))
        data, plan = prepared['backing_it'], prepared['plan']
    if channels is not None:
        d = bytearray(data)
        for ch in range(64):
            if ch not in channels:
                d[0x40 + ch] |= 0x80
        data = bytes(d)
    with LoadedModule(data, rate, 2, plan=plan) as lm:
        end = None
        if plan is not None and orders is not None:
            a, b = orders
            source = plan.get('source_occurrences', plan['occurrences'])
            if any(type(x) is not int for x in orders) or not 0 <= a < b <= len(source):
                raise ValueError('Invalid native score order range')
            from fractions import Fraction
            from .tablature import resolve_source_region
            last_row = int(Fraction(*source[b - 1]['duration']) / Fraction(*plan['row_step'])) - 1
            a, r0, b, r1 = resolve_source_region(plan, (a, 0, b - 1, last_row))
            lm.order_start(a, r0)
            end = (b + 1, 0)
        pcm = lm.render(rate, oversample=2, end=end)
    x = np.frombuffer(pcm, "<i2").reshape(-1, 2).T.astype(np.float32) / 32768
    return dsp.measure_mix(x, rate)


def playback_document(song, mod):
    """A disposable tracker projection for playback transforms; never save it as the authored score."""
    import copy
    from .notation import format_cell
    if mod.native_score is not None:
        raise ValueError('Native score playback requires its paired event plan; it cannot be flattened into residual tracker cells')
    base = copy.deepcopy(song)
    if 'score' in base:
        base.pop('score')
        base['patterns'] = {p.name: {'rows': len(p.rows), 'data': ''.join(
            f"{r:02d}: {' | '.join(format_cell(c) for c in row)}\n" for r, row in enumerate(p.rows))}
                            for p in mod.patterns}
    return base


def tryout_song(song_or_path, orders=None, base_dir=None, compiled=None) -> dict:
    """The song (a path, or a dict that is copied) cut to an order slice `(start, stop)`, or whole when `orders` is None."""
    import copy
    base = copy.deepcopy(song_or_path) if isinstance(song_or_path, dict) else load(song_or_path)
    if orders:
        if 'score' in base:
            if compiled is None:
                folder = base_dir or (Path(song_or_path).resolve().parent if not isinstance(song_or_path, dict) else None)
                if folder is None:
                    raise ValueError('A score playback slice requires its base_dir or compiled module')
                _, compiled, _ = compile_song(base, folder)
            base = playback_document(base, compiled)
        base.pop('sections', None)  # editor annotations do not affect playback of a slice
        start = orders[0]
        base["orders"] = base["orders"][orders[0]:orders[1]]
        base["patterns"] = {k: _retarget_jumps(v, start, len(base["orders"])) for k, v in base["patterns"].items()
                            if k in [str(o) for o in base["orders"]]}
    return base


RENDER_VERSION = 2  # in cached renders' keys: bump when compiling or rendering changes how a song sounds (0.8: resampler)
_JUMP = re.compile(r"(?<![^\s|])B([0-9A-F]{2})(?![^\s|])")


def _retarget_jumps(spec, start, n):
    """A pattern of a slice of the order list that starts at order `start` and holds `n` orders: each `Bxx` in its rows
    renumbered to the slice's order indices, or cleared when it jumps outside the slice (the section then runs to its
    end, and the compiler's check that a jump lands in the order list holds)."""
    def row(line):
        body, sc, comment = line.partition(";")
        body = _JUMP.sub(lambda m: f"B{int(m.group(1), 16) - start:02X}" if start <= int(m.group(1), 16) < start + n
                         else "...", body)
        return body + sc + comment

    def data(text):
        return "\n".join(row(line) for line in text.split("\n")) if isinstance(text, str) else text
    if isinstance(spec, str):
        return data(spec)
    if isinstance(spec, dict) and "data" in spec:
        return {**spec, "data": data(spec["data"])}
    return spec


def swap_sample(song: dict, slot, cand, name_from_file=True) -> dict:
    """Point sample slot `slot` at candidate WAV `cand` (in place). The WAV's smpl root sets base_note unless the
    slot pins c5_speed; a `loop: from_wav` is dropped when the WAV has no loop. The slot takes the WAV's name unless an
    instrument refers to the slot by its name (`sample:` or a keymap entry), which would then no longer resolve. Returns
    the slot entry."""
    from .notation import format_note
    from .wavload import read_wav
    old = song["samples"][slot].get("name", it_text(Path(song["samples"][slot]["file"]).stem, 25))
    refs = [ins.get("sample") for ins in (song.get("instruments") or {}).values() if isinstance(ins, dict)]
    refs += [k.get("sample") for ins in (song.get("instruments") or {}).values() if isinstance(ins, dict)
             for k in ins.get("keymap") or [] if isinstance(k, dict)]
    entry = song["samples"][slot] = {"file": str(cand), **{k: v for k, v in song["samples"][slot].items() if k != "file"}}
    if old in refs:
        entry["name"] = old
    elif name_from_file:
        entry["name"] = it_text(Path(cand).stem, 25)
    w = read_wav(cand)
    if w.root is not None and 0 <= w.root < 120 and "c5_speed" not in entry:  # a smpl unity note above B-9 is no note
        entry["base_note"] = format_note(w.root)
    if entry.get("loop") == "from_wav" and not w.loops:
        del entry["loop"]
    return entry


def tryout_render(base: dict, slot, cand, base_dir, rate=44100) -> bytes:
    """Render `base` once with slot `slot` swapped for `cand`. Returns interleaved int16 stereo PCM."""
    import copy
    from .openmpt import LoadedModule
    song = copy.deepcopy(base)
    swap_sample(song, slot, Path(cand).resolve())
    data = compile_song(song, base_dir)[0]
    with LoadedModule(data) as lm:
        return lm.render(rate)


def tryout(song_path, slot, candidates, orders=None, out_wav="tryout.wav", gap=0.6, rate=44100):
    """Render part of a song once per candidate WAV in sample slot `slot`, back to back into one WAV, so sounds
    can be compared in context. `orders` is a slice of the order list, e.g. (2, 6). Returns [(seconds, file)]."""
    candidates = list(candidates)
    sources = [*output_sources(song_path), *candidates]
    protect_outputs([out_wav], sources)
    base = tryout_song(song_path, orders)
    pcm, index, t = bytearray(), [], 0.0
    for cand in candidates:
        part = tryout_render(base, slot, cand, Path(song_path).parent, rate)
        index.append((t, str(cand)))
        pcm += part + bytes(int(gap * rate) * 4)
        t += len(part) / 4 / rate + gap
    protect_outputs([out_wav], sources)
    atomic_write(out_wav, wav_bytes(bytes(pcm), rate))
    return index


def info(it_path) -> dict:
    from .openmpt import LoadedModule
    with LoadedModule.from_file(it_path) as lm:
        return lm.info()
