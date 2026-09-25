"""`vulturetracker gui song.yaml`: a one-page tryout app served on localhost from the stdlib HTTP server.

The page (gui.html) polls /api/state and posts actions; renders run on one worker thread and land as WAVs in
`<song dir>/.tryout/`. The tryout section is compiled once per candidate (memoised); mutes, solo and the mixer's
faders (channel volume and pan, mix volume, sample gain) are patched into that module's header before each render, so
re-picking a candidate is instant and a fader move costs one render. The instrument panel (the slot's instrument: volume
envelope, filter and its sweep, random volume) joins the unwritten mix and is applied when the section is compiled.
Ratings, notes, the candidate list, mutes and the unwritten mix live in `<song>.tryout.json` beside the song.
Listening notes (a tag dropped at the playhead, the channels sounding there, the listener's words) live in
`<song>.notes.json` and are rendered as `<song>.notes.md`, a report for a collaborator who cannot listen."""
import datetime
import difflib
import functools
import glob
import hashlib
import importlib
import itertools
import json
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import wave
import webbrowser
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from . import api
from .notation import format_cell, format_note
from .itwriter import write_it
from .openmpt import LoadedModule
from .song import SongError, load_song_text
from .wavload import read_wav

HTML = Path(__file__).with_name("gui.html")
WEB = HTML.with_name("web")  # the live engine: libopenmpt 0.8.9 compiled to WebAssembly (official build) and its AudioWorklet
RATE = 44100
# the checkout (for the demo list); a frozen exe looks beside itself and one level up (dist/ in a checkout)
ROOT = Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
RECENT = Path(os.environ.get("APPDATA", Path.home())) / "VultureTracker" / "recent.json"
# the page is served from one address every launch when it can be, and the window keeps a WebView2 profile beside the
# recent list, so what the browser stores per address stays: the page's settings (localStorage) and the MIDI permission
PORT = 8723
PROFILE = RECENT.parent / "webview"
OLD_RECENT = RECENT.parent.with_name("TrackerForge") / "recent.json"  # the app's previous name


def _atomic(path, data):
    """`data` (bytes) as the file at `path`, written to a temporary file beside it and moved over it, so a crash or a
    power loss mid-write leaves the old file or the new one, never a truncated one."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _atomic_text(path, text):
    """Text written as write_text writes it (the platform's line endings), through _atomic."""
    _atomic(path, text.replace("\n", os.linesep).encode("utf-8"))


def _read_json(path, default, notices):
    """A JSON file the app keeps beside the song, or `default` when there is none. One that does not parse (a write cut
    short before writes were atomic, or a hand edit) is moved aside to `<name>.corrupt` and `default` is used, with a
    notice for the page, so the song still opens."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        bad = path.with_name(path.name + ".corrupt")
        os.replace(path, bad)
        notices.append(f"{path.name} could not be read ({e}); it was moved to {bad.name} and the app started it afresh")
        return default


def recent_songs():
    for f in (RECENT, OLD_RECENT):
        try:
            return [p for p in json.loads(f.read_text(encoding="utf-8")) if Path(p).exists()]
        except (OSError, ValueError):
            continue
    return []


def remember_song(path):
    RECENT.parent.mkdir(parents=True, exist_ok=True)
    lst = [str(path)] + [p for p in recent_songs() if p != str(path)]
    RECENT.write_text(json.dumps(lst[:12], indent=1), encoding="utf-8")


def demo_songs():
    # songs only (recipes like drums.yaml have no orders)
    return sorted(str(p) for p in ROOT.glob("demo*/*.yaml")
                  if p.is_file() and re.search(r"^orders:", p.read_text(encoding="utf-8", errors="replace"), re.M))


def create_song(path, channels=8, sample=None):
    """A new song file at `path` (refused when it exists), laid out the way the app edits songs: a block module with one
    channel entry per line, one sample slot (`sample`, a WAV, or a one-second C-5 sine written beside the song as
    <stem>_tone.wav) played by instrument 1, one empty 64-row pattern, the order list on one line. Written with LF endings."""
    path = Path(path).resolve()
    if path.suffix.lower() not in (".yaml", ".yml"):
        path = path.with_suffix(".yaml")
    if path.exists():
        raise ValueError(f"{path} exists already: open it, or pick another name")
    path.parent.mkdir(parents=True, exist_ok=True)
    if sample:
        wav = Path(sample).resolve()
        if not wav.exists():
            raise ValueError(f"no such WAV: {wav}")
    else:
        from .wavload import write_wav
        wav = path.with_name(path.stem + "_tone.wav")
        n = RATE
        write_wav(wav, RATE, [[round(12000 * math.sin(2 * math.pi * 261.6256 * i / RATE) * min(1, (n - i) / 2000)) for i in range(n)]], root_note=60)
    try:
        rel = os.path.relpath(wav, path.parent).replace(os.sep, "/")
    except ValueError:  # another drive
        rel = wav.as_posix()
    title = re.sub(r"[^ -~]", "", path.stem)[:25] or "Untitled"
    name = re.sub(r"[^ -~]", "", wav.stem)[:25] or "sample"
    q = State._yname
    chans = "".join(f"    - {{name: Ch {i + 1}}}\n" for i in range(max(1, min(64, int(channels)))))
    path.write_bytes((f"# {title}: a song made in VultureTracker (the format: SONG_FORMAT.md)\nmodule:\n  title: {q(title)}\n"
                      f"  tempo: 125\n  speed: 6\n  global_volume: 128\n  mix_volume: 48\n  channels:\n{chans}"
                      f"samples:\n  1: {{file: {q(rel)}, name: {q(name)}}}\ninstruments:\n  1: {{name: {q(name)}, sample: 1}}\n"
                      f"patterns:\n  p00:\n    rows: 64\n    data: |\norders: [p00]\n").encode("utf-8"))
    return path


@functools.lru_cache(maxsize=1)
def effect_help():
    """The song format's volume-column, effect and S-subcommand tables (SONG_FORMAT.md, beside the checkout or bundled
    with the exe) as {"v": {letter: text}, "e": {letter: text}, "s": {"S3": text, "S73": text, ...}}: the Pattern tab's
    effect help."""
    out = {"v": {}, "e": {}, "s": {}}
    src = next((p for p in (ROOT / "SONG_FORMAT.md", HTML.with_name("SONG_FORMAT.md")) if p.exists()), None)
    for line in (src.read_text(encoding="utf-8").splitlines() if src else []):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        codes = re.findall(r"`([^`]+)`", cells[0]) if len(cells) >= 2 and cells[0].startswith("`") else []
        if not codes:
            continue
        if re.fullmatch(r"[a-z]NN", codes[0]) and len(cells) >= 3:
            out["v"][codes[0][0]] = f"{cells[2]} ({cells[1]})"
        elif re.fullmatch(r"[A-Z]x[xy]", codes[0]) and len(cells) >= 3:
            out["e"][codes[0][0]] = f"{cells[1]}: {cells[2]}"
        elif re.fullmatch(r"S[0-9A-F][0-9A-Fx]", codes[0]):
            for c in codes:
                out["s"][c[:-1] if c.endswith("x") else c] = cells[1]
    return out


def import_beside(src):
    """A module (.it, .xm, .s3m, .mod) imported as <stem>.yaml beside it with its samples in <stem>_samples/ (numbered
    <stem>-2 and so on when either exists: nothing is replaced). Returns (song path, warnings)."""
    from .itreader import import_it
    src = Path(src).resolve()
    if not src.is_file():
        raise ValueError(f"no such file: {src}")
    for k in itertools.count(1):
        stem = src.stem + ("" if k == 1 else f"-{k}")
        out, sdir = src.with_name(stem + ".yaml"), src.with_name(stem + "_samples")
        if not out.exists() and not sdir.exists():
            break
    return out, import_it(src, out, sdir)[1]


def start_snapshot():
    return {"song": None, "recent": recent_songs(), "demos": demo_songs()}


# ---------------------------------------------------------------- measurements

def _envelope(mono, bins):
    """Peak per bin, 0..1, over `bins` equal slices (pure Python: fine for a few seconds of audio)."""
    n = len(mono)
    if n == 0:
        return [0.0] * bins
    peak = max(1, max(abs(x) for x in mono))
    out = []
    for i in range(bins):
        seg = mono[n * i // bins: max(n * (i + 1) // bins, n * i // bins + 1)]
        out.append(max(abs(x) for x in seg) / peak)
    return out


def wave_points(env, height=24):
    """SVG polygon for a symmetric peak envelope in a 100 x `height` box."""
    mid = height / 2
    top = [f"{100 * i / (len(env) - 1):.1f},{mid - e * mid:.1f}" for i, e in enumerate(env)]
    bot = [f"{100 * i / (len(env) - 1):.1f},{mid + e * mid:.1f}" for i, e in reversed(list(enumerate(env)))]
    return " ".join(top + bot)


def measure(path) -> dict:
    """Duration, root, loop and (with numpy) pitch, spectral centroid, decay and attack of a WAV."""
    w = read_wav(path)
    n = len(w.channels[0])
    mono = w.channels[0] if len(w.channels) == 1 else [sum(c[i] for c in w.channels) // len(w.channels) for i in range(n)]
    m = {
        "duration": n / w.rate, "rate": w.rate, "bits": w.bits, "stereo": len(w.channels) > 1,
        "root": format_note(w.root) if w.root is not None else None,
        "loop": bool(w.loops), "wave": wave_points(_envelope(mono, 100)),
        "pitch": None, "cents": None, "centroid": None, "decay": None, "attack": None, "flatness": None, "bands": None,
    }
    try:
        import numpy as np
        from .synth import estimate_pitch
    except ImportError:
        return m
    x = np.asarray(mono, dtype=float) / 32768
    if not x.any():
        return m
    peak = np.abs(x).max()
    # 10 ms RMS envelope: attack = time to reach the peak, decay = time until it stays under -40 dB of the peak
    hop = max(1, w.rate // 100)
    env = np.sqrt(np.convolve(x * x, np.ones(hop) / hop, mode="same"))
    ipk = int(np.argmax(env))
    m["attack"] = ipk / w.rate
    below = np.nonzero(env[ipk:] < env[ipk] * 10 ** (-40 / 20))[0]
    m["decay"] = (below[0] / w.rate) if len(below) else None
    m["decay_curve"] = [float(v) for v in np.interp(np.linspace(0, len(env) - 1, 40), np.arange(len(env)), env / max(env.max(), 1e-9))]
    # spectrum of the first second (pitched content is at the start)
    seg = x[: w.rate]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    freqs = np.fft.rfftfreq(len(seg), 1 / w.rate)
    power = spec ** 2
    if power.sum() > 0:
        m["centroid"] = float((freqs * power).sum() / power.sum())
        m["flatness"] = float(np.exp(np.mean(np.log(power[1:] + 1e-12))) / (np.mean(power[1:]) + 1e-12))
        bands = []
        for lo in (31.25 * 2 ** i for i in range(9)):
            sel = (freqs >= lo) & (freqs < lo * 2)
            bands.append(float(power[sel].sum()) if sel.any() else 0.0)
        top = max(bands) or 1.0
        m["bands"] = [math.sqrt(b / top) for b in bands]
    est = estimate_pitch(x[int(0.02 * w.rate):], w.rate)
    if est and est[1] < 0.3 and est[0] > 0:
        midi = 69 + 12 * math.log2(est[0] / 440)
        note = int(round(midi))
        if 0 <= note < 120:
            m["pitch"] = format_note(note)
            m["cents"] = int(round((midi - note) * 100))
    return m


def distance(a, b):
    """Rough perceptual distance between two measurements (0 = same); None when either lacks numbers."""
    if not a or not b or a.get("centroid") is None or b.get("centroid") is None:
        return None
    d = (abs(math.log2(max(a["duration"], 0.01) / max(b["duration"], 0.01))) * 2
         + abs(math.log2(a["centroid"] / b["centroid"])) * 3)
    if a.get("decay") is not None and b.get("decay") is not None:
        d += abs(math.log2(max(a["decay"], 0.01) / max(b["decay"], 0.01))) * 2
    if a.get("pitch") and b.get("pitch"):
        from .notation import parse_note
        d += abs(parse_note(a["pitch"]) - parse_note(b["pitch"])) * 0.5
    return round(d, 1)


# ---------------------------------------------------------------- song facts

def song_facts(text, base_dir, name):
    """Compile once for the overview: channels, order timing and which samples each order/channel plays."""
    return facts_of(*load_song_text(text, base_dir, name))


def facts_of(mod, warnings, it=None):
    """`it`: the module's .it bytes, when the caller wrote them already."""
    rows_per_bar = mod.row_highlight[1] or 16
    orders = []
    use = []  # per order: per channel: sorted sample numbers triggered
    # order timing comes from libopenmpt, so speed, tempo, break and jump effects count; an order that playback
    # never reaches lasts 0 s
    with LoadedModule(it or write_it(mod)) as lm:
        duration = lm.duration()
        starts = {i: lm.order_start(i) for i, o in enumerate(mod.orders) if o < 254}
        for i, t in starts.items():
            if t <= 0.0 and i != min(starts):  # never entered: libopenmpt seeks into the hidden subsong starting there
                starts[i] = duration
            elif t >= duration:  # row 0 is skipped by a break into the pattern: it starts at its first row that plays
                rows = len(mod.patterns[mod.orders[i]].rows)
                starts[i] = next((v for v in (lm.order_start(i, r) for r in range(1, rows)) if v < duration), duration)
    points = sorted({*starts.values(), duration})
    for i, o in enumerate(mod.orders):
        if o >= 254:
            continue
        pat = mod.patterns[o]
        per_ch = [set() for _ in mod.channels]
        for row in pat.rows:
            for ch, cell in enumerate(row):
                if cell.note is None or cell.note >= 120 or not cell.instrument:
                    continue
                if mod.instruments is None:
                    per_ch[ch].add(cell.instrument)
                elif cell.instrument <= len(mod.instruments):
                    smp = mod.instruments[cell.instrument - 1].keymap[cell.note][1]
                    if smp:
                        per_ch[ch].add(smp)
        start = starts[i]
        secs = next((p for p in points if p > start), start) - start
        orders.append({"pattern": pat.name, "index": o, "order": i, "rows": len(pat.rows), "bars": len(pat.rows) / rows_per_bar, "start": start, "seconds": secs})
        use.append([sorted(s) for s in per_ch])
    return {
        "title": mod.title, "tempo": mod.tempo, "speed": mod.speed, "bpm": round(mod.tempo * 24 / mod.speed / 4),
        "highlight": [mod.row_highlight[0] or 4, rows_per_bar],
        "channels": [c.name or f"Ch {i + 1}" for i, c in enumerate(mod.channels)],
        "pan": [c.pan for c in mod.channels], "volume": [c.volume for c in mod.channels], "mix_volume": mod.mix_volume,
        "patterns": len(mod.patterns), "duration": duration, "orders": orders, "use": use,
        "instruments": [i.name for i in mod.instruments] if mod.instruments else [],
        "samples": [{"num": i + 1, "name": s.name, "c5_speed": s.c5_speed, "length": s.length / s.c5_speed if s.c5_speed else 0,
                     "loop": s.loop is not None, "bits": s.bits} for i, s in enumerate(mod.samples)],
        "warnings": warnings,
    }


# ---------------------------------------------------------------- listening notes

def sounding_table(mod, facts):
    """Per order of `facts` (the playable orders, in order) and per row of its pattern: the channels sounding there. A
    forward pass carries each channel's last note (the sample through the instrument's keymap, the note, the order and row
    it started at, whether the sample loops); a note-off/cut/fade drops it, and a one-shot sample drops out once its
    length has played at the note's rate, at that order's row rate. A note without an instrument keeps the channel's last instrument (a slide
    target, the tracker convention). Entry: ch, name, sample, note, order, loop, ago (rows since it started)."""
    secs = [s.length / s.c5_speed if s.c5_speed else 0 for s in mod.samples]
    state, last_ins = [None] * len(mod.channels), [0] * len(mod.channels)
    table, abs_row = [], 0
    for oi, mo in enumerate(k for k, o in enumerate(mod.orders) if o < 254):
        pat = mod.patterns[mod.orders[mo]]
        o = facts["orders"][oi] if oi < len(facts["orders"]) else None
        row_s = o["seconds"] / len(pat.rows) if o and pat.rows else 0
        rows = []
        for r, row in enumerate(pat.rows):
            for ch, c in enumerate(row):
                if c.note is None:
                    continue
                if c.note >= 120:  # note off / cut / fade
                    state[ch] = None
                    continue
                ins = last_ins[ch] = c.instrument or last_ins[ch]
                smp, played = ins, c.note
                if mod.instruments is not None:
                    played, smp = mod.instruments[ins - 1].keymap[c.note] if 0 < ins <= len(mod.instruments) else (c.note, 0)
                ok = 0 < smp <= len(mod.samples)
                state[ch] = {"ch": ch, "name": mod.channels[ch].name or f"Ch {ch + 1}", "sample": smp if ok else None, "note": format_note(c.note),
                             "order": oi, "loop": ok and mod.samples[smp - 1].loop is not None, "abs": abs_row + r,
                            "secs": secs[smp - 1] / 2 ** ((played - 60) / 12) if ok else None}
            out = []
            for s in state:
                if s is None:
                    continue
                ago = abs_row + r - s["abs"]
                if s["loop"] or s["secs"] is None or ago * row_s < s["secs"]:
                    out.append({k: v for k, v in s.items() if k not in ("abs", "secs")} | {"ago": ago})
            rows.append(out)
        table.append(rows)
        abs_row += len(pat.rows)
    return table


def _stamp(f):
    """A file's path, modification time and size as text (render cache keys)."""
    try:
        st = Path(f).stat()
        return f"{f}={st.st_mtime}:{st.st_size}"
    except OSError:
        return f"{f}=missing"


def patch_it(data, silenced=(), mix=None):
    """The compiled module with channels `silenced` disabled (the IT channel-disable bit, which libopenmpt honours) and a
    mix written into its header: channel volumes (header bytes 0x80..) and pans (0x40..), the mix volume (0x31) and per-slot
    sample global volumes (the sample headers, via the offset table). Exactly what writing those values into the song
    would render, without recompiling it."""
    d = bytearray(data)
    mix = mix or {}
    for i, v in (mix.get("volume") or {}).items():
        d[0x80 + int(i)] = int(v)
    for i, p in (mix.get("pan") or {}).items():
        d[0x40 + int(i)] = (d[0x40 + int(i)] & 0x80) | (100 if p == "surround" else int(p))
    for i in silenced:
        d[0x40 + i] |= 0x80
    if mix.get("mix_volume") is not None:
        d[0x31] = int(mix["mix_volume"])
    if mix.get("sample_volume"):
        nord, nins, nsmp = struct.unpack_from("<HHH", d, 0x20)
        for slot, g in mix["sample_volume"].items():
            if 1 <= int(slot) <= nsmp:
                off = struct.unpack_from("<I", d, 0xC0 + nord + 4 * nins + 4 * (int(slot) - 1))[0]
                d[off + 0x11] = int(g)
    return bytes(d)


def channel_levels(data, nch, cancel=None):
    """Each channel soloed (every other channel's header volume zeroed, the way the suite's local-only
    scratch/ut99-clean/compare.py measures a module): RMS in dB over the whole render and over its active half-seconds, plus those seconds. Needs numpy.
    `cancel()` true between channels abandons the pass (returns None)."""
    import numpy as np
    out = []
    for ch in range(nch):
        if cancel is not None and cancel():
            return None
        d = bytearray(data)
        for other in range(nch):
            if other != ch:
                d[0x80 + other] = 0
        with LoadedModule(bytes(d)) as lm:
            x = np.frombuffer(lm.render(RATE, oversample=1), dtype="<i2").astype(np.float32).reshape(-1, 2) / 32768
        e = np.mean(x ** 2, axis=1)
        w = RATE // 2
        seg = e[: len(e) // w * w].reshape(-1, w).mean(axis=1)
        active = seg[seg > 1e-7]
        db = lambda p: round(float(10 * np.log10(p + 1e-12)), 1)  # noqa: E731
        out.append({"db": db(e.mean()) if len(e) else None, "active_db": db(active.mean()) if len(active) else None,
                    "active_s": len(active) / 2})
    return out


# the spectrogram of what is playing: the colour scale's window in dBFS (a full-scale sine reads 0 dB) and its colours,
# black -> purple -> red -> orange -> white (scratch/ut99-clean/spectrogram.py's map)
SPEC_DB = (-100, -10)
SPEC_STOPS = [[0, 0, 0], [60, 0, 90], [160, 20, 110], [220, 60, 40], [250, 160, 40], [255, 255, 220]]


def spectrogram(path, scale="log", cols=1200, rows=256, n=4096):
    """A 16-bit render's spectrogram: level in dBFS per column (`cols` equal slices of the file, the mean power of the
    frames centred in each, so column c covers c/cols..(c+1)/cols of the duration) and per row (`rows` bands from 20 Hz,
    or 0 Hz when `scale` is "lin", up to the Nyquist frequency, log- or evenly spaced; the loudest bin in each band, so a
    narrow image between two bands is not lost). Returns (db [rows x cols], band edges in Hz), row 0 the lowest band."""
    import numpy as np
    with wave.open(str(path), "rb") as w:
        rate, nch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32).reshape(-1, nch).mean(axis=1) / 32768
    length = len(x)
    hop = max(64, min(n // 2, length // cols))
    x = np.concatenate([np.zeros(n // 2, np.float32), x, np.zeros(n, np.float32)])  # frame i is centred on sample i * hop
    frames = max(1, -(-length // hop))
    cols = max(1, min(cols, frames))
    nyq = rate / 2
    edges = np.geomspace(20, nyq, rows + 1) if scale != "lin" else np.linspace(0, nyq, rows + 1)
    idx = np.minimum((edges[:-1] * n / rate).astype(int), n // 2)
    win = np.hanning(n).astype(np.float32)
    acc, cnt = np.zeros((cols, rows)), np.zeros(cols)
    col_of = np.minimum(np.arange(frames) * hop * cols // max(length, 1), cols - 1)
    for a in range(0, frames, 256):
        fr = np.lib.stride_tricks.sliding_window_view(x, n)[a * hop:(a + 256) * hop:hop][: frames - a]
        power = np.abs(np.fft.rfft(fr * win, axis=1)) ** 2
        np.add.at(acc, col_of[a:a + len(fr)], np.maximum.reduceat(power, idx, axis=1))
        np.add.at(cnt, col_of[a:a + len(fr)], 1)
    power = acc / np.maximum(cnt, 1)[:, None] / (win.sum() / 2) ** 2  # a full-scale sine peaks at 1
    return (10 * np.log10(power + 1e-20)).T, edges


def png_rgb(rgb):
    """A PNG of an h x w x 3 uint8 array (stdlib zlib: the exe does not need Pillow)."""
    h, w, _ = rgb.shape
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))  # noqa: E731
    raw = b"".join(b"\x00" + row.tobytes() for row in rgb)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


@functools.lru_cache(maxsize=12)
def spectrogram_png(path, stamp, scale="log"):
    """The spectrogram as a PNG, the highest band at the top (`stamp` keys the cache on the file's mtime and size)."""
    import numpy as np
    db, _ = spectrogram(path, scale)
    v = np.clip((db[::-1] - SPEC_DB[0]) / (SPEC_DB[1] - SPEC_DB[0]), 0, 1)
    stops, pos = np.array(SPEC_STOPS, float), np.linspace(0, 1, len(SPEC_STOPS))
    return png_rgb(np.stack([np.interp(v, pos, stops[:, k]) for k in range(3)], axis=-1).astype(np.uint8))


def worklet_js():
    """/engine-worklet.js: the libopenmpt glue (a classic script) wrapped as loadGlue(), then the engine core and the
    processor, as one module for audioWorklet.addModule (a worklet cannot load scripts itself)."""
    glue = (WEB / "libopenmpt.js").read_text(encoding="utf-8")
    return ("const loadGlue = function (libopenmpt, require, __dirname) {\n" + glue + "\nreturn Module;\n};\n"
            + (WEB / "engine-core.js").read_text(encoding="utf-8") + (WEB / "engine-worklet.js").read_text(encoding="utf-8")).encode("utf-8")


def _write_pcm(path, pcm):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(pcm)


# export formats encoded by ffmpeg: MP3 192 kbit/s (LAME), Ogg Vorbis at quality 6 (about 192 kbit/s; Ogg loops gaplessly,
# what a game engine wants), FLAC (lossless); WAV is written directly
ENCODE = {"mp3": ["-c:a", "libmp3lame", "-b:a", "192k"], "ogg": ["-c:a", "libvorbis", "-q:a", "6"], "flac": ["-c:a", "flac"]}


def ffmpeg_exe():
    """ffmpeg for the encoded exports: an ffmpeg.exe beside the frozen exe (tools/build_exe.py puts one in dist/), else
    imageio-ffmpeg's own binary, else one on PATH. imageio_ffmpeg is imported by name at run time so PyInstaller's hook for
    it does not also pack its 88 MB binary into the exe, which would be unpacked to %TEMP% on every launch."""
    beside = Path(sys.executable).with_name("ffmpeg.exe")
    if getattr(sys, "frozen", False) and beside.exists():
        return str(beside)
    try:
        exe = importlib.import_module("imageio_ffmpeg").get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        exe = shutil.which("ffmpeg")
    if not exe:
        raise OSError("MP3/OGG/FLAC export needs ffmpeg: ffmpeg.exe beside vulturetracker.exe, pip install imageio-ffmpeg, "
                      "or ffmpeg on PATH")
    return exe


def _encode(path, pcm, fmt):
    """Interleaved int16 stereo PCM at RATE to `fmt` (a key of ENCODE) through ffmpeg (no console window on Windows)."""
    r = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(RATE), "-ac", "2", "-i", "-",
                        *ENCODE[fmt], str(path)], input=pcm, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode:
        raise OSError(f"ffmpeg failed: {r.stderr.decode(errors='replace').strip()[-400:]}")


def _peak(pcm):
    """Peak of interleaved int16 PCM, 0..1 (1.0: libopenmpt's mixer clipped)."""
    try:
        import numpy as np
        return round(float(np.abs(np.frombuffer(pcm, "<i2")).max()) / 32768, 3)
    except (ImportError, ValueError):
        return None


# ---------------------------------------------------------------- the sample editor

@functools.lru_cache(maxsize=8)
def wav_array(path, stamp):
    """A WAV as (WavData, float32 array channels x frames scaled to -1..1); `stamp` keys the cache on mtime and size."""
    import numpy as np
    w = read_wav(path)
    return w, np.array(w.channels, dtype=np.float32) / (128 if w.out_bits == 8 else 32768)


def wave_peaks(x, a, b, n):
    """Frames a..b of `x` (channels x frames) as `n` columns: (min, max) per column and channel, lists rounded for JSON;
    when the span holds `n` frames or fewer, the frames themselves (min = max)."""
    import numpy as np
    seg = x[:, a:b]
    if seg.shape[1] <= n:
        mn = mx = seg
    else:
        at = np.arange(n) * seg.shape[1] // n
        mn, mx = np.minimum.reduceat(seg, at, axis=1), np.maximum.reduceat(seg, at, axis=1)
    return np.round(mn, 4).tolist(), np.round(mx, 4).tolist()


def entry_loops(entry, w):
    """The sample entry's `loop` and `sustain_loop` in the WAV's frames: {key: (start, end, pingpong) or None}
    (`from_wav` read from the WAV's smpl chunk)."""
    out = {}
    for k in ("loop", "sustain_loop"):
        spec = entry.get(k)
        if spec == "from_wav":
            out[k] = w.loops[0] if w.loops else None
        elif isinstance(spec, dict):
            n = len(w.channels[0])
            out[k] = (int(spec.get("start", 0)), int(spec.get("end", n)), spec.get("type") == "pingpong")
        else:
            out[k] = None
    return out


SAMPLE_ACTIONS = ("trim", "fade_in", "fade_out", "normalize", "reverse", "dc", "crossfade")


def process_wav(x, action, a, b, loops, frames=0):
    """One sample edit on frames a..b of `x` (float channels x frames; a copy is changed). `loops` ({key: (start, end,
    pingpong) or None}) follow the audio: trimmed (shifted, clipped, dropped when nothing is left) and mirrored by a
    reverse of the whole sample. Crossfade: the last `frames` of the loop fade (equal power) into the audio just before
    its start, so the wrap is seamless (the synth recipes' crossfade). Returns (x, loops)."""
    import numpy as np
    x, loops, n = x.copy(), dict(loops), x.shape[1]
    seg = x[:, a:b]
    if action == "trim":
        x = seg.copy()
        for k, lp in loops.items():
            if lp:
                s, e = max(0, lp[0] - a), min(b - a, lp[1] - a)
                loops[k] = (s, e, lp[2]) if e > s else None
    elif action in ("fade_in", "fade_out"):
        ramp = np.linspace(0, 1, seg.shape[1], dtype=np.float32)
        seg *= ramp if action == "fade_in" else ramp[::-1]
    elif action == "normalize":
        peak = float(np.abs(seg).max()) if seg.size else 0
        if peak <= 0:
            raise ValueError("nothing to normalize: the selection is silent")
        seg *= 1 / peak
    elif action == "reverse":
        x[:, a:b] = seg[:, ::-1]
        if (a, b) == (0, n):
            loops = {k: lp and (n - lp[1], n - lp[0], lp[2]) for k, lp in loops.items()}
    elif action == "dc":
        seg -= seg.mean(axis=1, keepdims=True)
    elif action == "crossfade":
        lp = loops.get("loop") or loops.get("sustain_loop")
        if not lp:
            raise ValueError("crossfade needs a loop (or a sustain loop)")
        s, e = lp[0], lp[1]
        xf = min(int(frames), s, e - s)
        if xf <= 0:
            raise ValueError("crossfade needs audio before the loop start: move the loop start later")
        t = np.linspace(0, np.pi / 2, xf, endpoint=False, dtype=np.float32)
        x[:, e - xf:e] = x[:, e - xf:e] * np.cos(t) + x[:, s - xf:s] * np.sin(t)
    else:
        raise ValueError(f"unknown sample edit '{action}' (one of {', '.join(SAMPLE_ACTIONS)})")
    if x.shape[1] == 0:
        raise ValueError("the edit leaves no audio")
    return x, loops


# ---------------------------------------------------------------- the instrument panel

# per-note movement the tracker itself plays, in the panel's terms: a volume envelope from attack and decay (ticks) and a
# sustain level, the release (the instrument's fadeout, 0-256: a fading note loses fadeout / 1024 per tick), the resonant
# low-pass (cutoff 127 and resonance 0 = off), a filter sweep (the pitch envelope in filter mode, from and to a share of
# the cutoff in 64ths: libopenmpt scales the cutoff by (value + 32) / 64, so 64 is the cutoff, 0 closed) and random volume
# per note
VOICE_GROUPS = {"volume": ("attack", "decay", "sustain"), "release": ("release",), "filter": ("cutoff", "resonance"),
                "sweep": ("sweep_from", "sweep_to", "sweep_ticks"), "random": ("random",)}
VOICE_RANGE = {"attack": (0, 64), "decay": (0, 192), "sustain": (0, 64), "release": (0, 256), "cutoff": (0, 127),
               "resonance": (0, 127), "sweep_from": (0, 64), "sweep_to": (0, 64), "sweep_ticks": (0, 192), "random": (0, 100)}


def voice_of(ins):
    """The panel's view of an instrument entry (the song's mapping). Returns (params, custom): `custom` lists the groups
    whose envelope in the song has another shape than the panel writes; the panel shows defaults for them and replaces
    that envelope only when one of its sliders moves."""
    p = {"attack": 0, "decay": 0, "sustain": 64, "release": int(ins.get("fadeout") or 0),
         "cutoff": 127 if ins.get("filter_cutoff") is None else int(ins["filter_cutoff"]),
         "resonance": int(ins.get("filter_resonance") or 0), "sweep_from": 64, "sweep_to": 64, "sweep_ticks": 0,
         "random": int(ins.get("random_volume") or 0)}
    custom = []

    def plain(env):  # enabled, no loop; the sustain as one node index (or None)
        s = env.get("sustain")
        s = s[0] if isinstance(s, list) and len(s) == 2 and s[0] == s[1] else s
        return (env.get("enabled", True) and not env.get("loop") and (s is None or isinstance(s, int)),
                [tuple(n) for n in env.get("nodes") or []], s)

    env = ins.get("volume_envelope")
    if env:
        ok, n, s = plain(env)
        shape = None
        if ok and n == [(0, 64)]:
            shape = (0, 0, 64)
        elif ok and len(n) == 2 and n[0] == (0, 0) and n[1][1] == 64 and s == 1:
            shape = (n[1][0], 0, 64)
        elif ok and len(n) == 2 and n[0] == (0, 64) and n[1][1] < 64 and s == (1 if n[1][1] else None):
            shape = (0, n[1][0], n[1][1])
        elif ok and len(n) == 3 and n[0] == (0, 0) and n[1][1] == 64 and n[2][1] < 64 and s == (2 if n[2][1] else None):
            shape = (n[1][0], n[2][0] - n[1][0], n[2][1])
        if shape:
            p["attack"], p["decay"], p["sustain"] = shape
        else:
            custom.append("volume")
    env = ins.get("pitch_envelope")
    if env:
        ok, n, s = plain(env)
        if ok and env.get("filter") and s is None and len(n) in (1, 2):
            p["sweep_from"], p["sweep_to"], p["sweep_ticks"] = n[0][1] + 32, n[-1][1] + 32, n[-1][0]
        else:
            custom.append("sweep")
    return p, custom


def voice_entry(ins, edit):
    """The instrument entry with the panel's `edit` (some of voice_of's params) written in. Only the groups the edit
    touches change, so an envelope the panel cannot show stays unless one of its sliders moved."""
    p = voice_of(ins)[0]
    p.update({k: int(v) for k, v in edit.items() if k in VOICE_RANGE})
    touched = {g for g, keys in VOICE_GROUPS.items() if any(k in edit for k in keys)}
    out = dict(ins)

    def put(key, value, keep):
        if keep:
            out[key] = value
        else:
            out.pop(key, None)

    if "volume" in touched:
        a, d, s = p["attack"], p["decay"], p["sustain"]
        nodes = [[0, 0], [a, 64]] if a else [[0, 64]]
        if s < 64:
            nodes.append([nodes[-1][0] + max(1, d), s])  # the level held until note-off; 0 lets the note die away
        put("volume_envelope", {"nodes": nodes, **({"sustain": len(nodes) - 1} if s else {})}, len(nodes) > 1)
    if "release" in touched:
        put("fadeout", p["release"], p["release"])
    sweep = (p["sweep_from"], p["sweep_to"]) != (64, 64)
    if touched & {"filter", "sweep"}:
        on = p["cutoff"] < 127 or p["resonance"] > 0 or sweep
        put("filter_cutoff", p["cutoff"], on)
        put("filter_resonance", p["resonance"], on)
    if "sweep" in touched:
        v0, v1 = p["sweep_from"] - 32, p["sweep_to"] - 32
        nodes = [[0, v0], [p["sweep_ticks"], v1]] if p["sweep_ticks"] and v0 != v1 else [[0, v1]]
        put("pitch_envelope", {"nodes": nodes, "filter": True}, sweep)
    if "random" in touched:
        put("random_volume", p["random"], p["random"])
    return out


# ---------------------------------------------------------------- state

class State:
    def __init__(self, song_path):
        self.song_path = Path(song_path).resolve()
        self.base_dir = self.song_path.parent
        self.cache_dir = self.base_dir / ".tryout"
        self.meta_path = self.song_path.with_name(self.song_path.stem + ".tryout.json")
        self.meta = {"slot": 1, "orders": None, "candidates": {}, "ratings": {}, "muted": [], "solo": None, "mix": {}}
        self.closed = False
        self.notices = []     # what the page should tell once: a meta or notes file that could not be read
        meta = _read_json(self.meta_path, {}, self.notices)
        self.meta.update(meta if isinstance(meta, dict) else {})
        self.notes_path = self.song_path.with_name(self.song_path.stem + ".notes.json")
        notes = _read_json(self.notes_path, [], self.notices)
        self.notes = notes if isinstance(notes, list) else []
        self.lock = threading.RLock()
        self.jobs = queue.PriorityQueue()  # (priority, sequence, job): what is playing first, then the song, the rest, meters last
        self._seq = itertools.count()
        self.want = None      # the candidate the page is listening to (None: the song itself), rendered first
        self.sound_table = None  # per order per row: the channels sounding there (sounding_table), rebuilt on reload
        self.renders = {}     # render key -> {"status", "error", "file", "peak"}
        self.compiled = {}    # compile key -> .it bytes of the tryout section (a candidate swapped in), patched per render
        self.meters = None    # soloed channel levels of the section with the unwritten mix applied
        self.meas = {}        # wav path -> measurement (memo, kept while the file's stamp holds: meas_stamp)
        self.meas_stamp = {}
        # before each app write of the song (undo) and after an undo (redo): {"text": the song text, "meta": the tryout
        # settings that write changed (a channel's mutes and faders remapped, the mix written, the slot's candidates
        # cleared by U), as they were, or None}
        self.history, self.future = [], []
        self.build = None     # last build/export result
        self.stems = None     # stems export progress
        self.recipe_job = None  # the recipe panel's last render, write or synth download: {"status", "error", "log", "file", "need"}
        self._recipe_retry = None  # the render a missing synth stopped, run again once fetch_synth has it
        self._recipe_memo = {}  # (recipe path, mtime, size) -> recipe_outputs, or None for a YAML file that is no recipe
        self.error = None
        self.text = ""
        self._sha = (None, "")       # (text, its sha1): every poll hashes the text once per candidate otherwise
        self._stamps = None          # the mix's WAV stamps while a snapshot runs (it asks once per candidate)
        self.mtime = 0.0
        self.facts = None
        self.mod = None       # compiled model of the last good load (pattern view)
        self.it = None        # its .it bytes: the whole song as it is, which the live engine plays unless the panel edits it
        self.reload()
        self.cache_dir.mkdir(exist_ok=True)
        threading.Thread(target=self._worker, daemon=True).start()

    # ---- song

    def reload(self, archive=True, loaded=None):
        """Re-read the song. `archive`: notes made against another version of the song text move to their archive
        (the song changed outside the app: a rebuild); the app's own writes pass False, so a slot write mid-session
        keeps the notes. `loaded`: the (module, warnings) of this very text, already compiled by the caller."""
        with self.lock:
            raw = self.song_path.read_bytes()
            self.crlf = b"\r\n" in raw
            self.bom = raw.startswith(b"\xef\xbb\xbf")  # older Notepad; kept on write, but not in the text the editors read
            self.text = raw[3 if self.bom else 0:].decode("utf-8").replace("\r\n", "\n")
            self.mtime = self.song_path.stat().st_mtime
            try:
                self.mod, warnings = loaded or load_song_text(self.text, self.base_dir, str(self.song_path))
                self.it = write_it(self.mod)
                self.facts = facts_of(self.mod, warnings, self.it)
                self.sound_table = None
                self.error = None
            except SongError as e:
                self.error = e.errors
                self.it = None
            try:
                self.song = api.from_yaml(self.text)
            except yaml.YAMLError:  # a syntax error: it is in self.error already, and the app opens on it
                self.song = None
            if not isinstance(self.song, dict):
                self.song = {}
            for sec in ("samples", "instruments"):  # a key written 08: reads as the string "08" here; the compiler reads 8
                if isinstance(self.song.get(sec), dict):
                    self.song[sec] = {int(k) if isinstance(k, str) and k.isdigit() else k: v for k, v in self.song[sec].items()}
            files = self.files = [str((self.base_dir / v["file"]).resolve()) for v in (self.song.get("samples") or {}).values()
                     if isinstance(v, dict) and v.get("file")]
            threading.Thread(target=lambda: [self.measured(f) for f in files if Path(f).exists()], daemon=True).start()
            if self.meta["slot"] not in (self.song.get("samples") or {}):
                self.meta["slot"] = min(self.song.get("samples") or {1: 0})
            if archive:
                self._archive_old_notes()
            if self.notes:
                self.save_notes()  # the report's header and version labels follow the song text
            self.queue_all()

    def dirty(self):
        try:
            return self.song_path.stat().st_mtime != self.mtime
        except OSError:
            return False

    def save_meta(self):
        _atomic_text(self.meta_path, json.dumps(self.meta, indent=1))

    def write_song(self, text):
        """The song file, written with the line endings (and the byte-order mark) it had (write_text would turn every LF into
        CRLF on Windows), atomically."""
        _atomic(self.song_path, (b"\xef\xbb\xbf" if self.bom else b"") + text.replace("\n", "\r\n" if self.crlf else "\n").encode("utf-8"))

    def _put(self, prio, job):
        self.jobs.put((prio, next(self._seq), job))

    def set_want(self, cand):
        """The candidate the page is listening to (None: the song): its pending render jumps the queue."""
        with self.lock:
            self.want = cand
            k = self.key(cand)
            if self.renders.get(k, {}).get("status") == "queued":
                self._put(1, (k, cand))

    # ---- candidates

    @property
    def slot(self):
        return self.meta["slot"]

    @property
    def orders(self):
        o = self.meta.get("orders")
        return tuple(o) if o else None

    def set_loop(self, body):
        """The playback loop: `from` and `to` as [order, row] in the facts' order list (`to` inclusive), clamped to the song
        and put in order; a body without them clears it. Playback only: the page loops that span of whichever render plays
        (the song or a candidate, when the span lies inside the rendered section), so no render key changes."""
        f, lp = self.facts, None
        if f and body.get("from") is not None and body.get("to") is not None:
            def at(p):
                o = max(0, min(len(f["orders"]) - 1, int(p[0])))
                return [o, max(0, min(f["orders"][o]["rows"] - 1, int(p[1])))]
            a, b = sorted([at(body["from"]), at(body["to"])])
            lp = {"from": a, "to": b}
        with self.lock:
            self.meta["loop"] = lp
            self.save_meta()

    def cands(self):
        return self.meta["candidates"].setdefault(str(self.slot), [])

    def current_file(self):
        f = ((self.song.get("samples") or {}).get(self.slot) or {}).get("file")
        return str((self.base_dir / f).resolve()) if f else None

    def silenced(self):
        """Channel indices muted in tryout renders: all but the solo channel, else the muted set."""
        if self.meta.get("solo") is not None and self.facts:
            return [i for i in range(len(self.facts["channels"])) if i != self.meta["solo"]]
        return sorted(set(self.meta.get("muted") or []))

    def mix(self):
        """The unwritten mix: {"volume": {ch: 0-64}, "pan": {ch: 0-64|surround}, "mix_volume": 0-128, "sample_volume": {slot: 0-64},
        "instrument": {number: {panel param: value}}} (keys are strings: the meta round-trips through JSON)."""
        return self.meta.get("mix") or {}

    def set_mix(self, m):
        mix = {}
        for k, hi in (("volume", 64), ("pan", 64), ("sample_volume", 64)):
            d = {str(int(i)): "surround" if k == "pan" and v == "surround" else max(0, min(hi, int(v)))
                 for i, v in (m.get(k) or {}).items()}
            if d:
                mix[k] = d
        if m.get("mix_volume") is not None:
            mix["mix_volume"] = max(0, min(128, int(m["mix_volume"])))
        inst = {}
        for n, edit in (m.get("instrument") or {}).items():  # a value back at the song's own is no change
            ins = (self.song.get("instruments") or {}).get(int(n))
            if not isinstance(ins, dict):
                continue
            now, custom = voice_of(ins)
            keep = {k for g in custom for k in VOICE_GROUPS[g]}
            e = {k: max(VOICE_RANGE[k][0], min(VOICE_RANGE[k][1], int(v))) for k, v in edit.items() if k in VOICE_RANGE}
            e = {k: v for k, v in e.items() if v != now[k] or k in keep}
            if e:
                inst[str(int(n))] = e
        if inst:
            mix["instrument"] = inst
        with self.lock:
            self.meta["mix"] = mix
            self.save_meta()
            self.queue_all()

    def text_sha(self):
        """sha1 of the song text, computed once per text."""
        if self._sha[0] is not self.text:
            self._sha = (self.text, hashlib.sha1(self.text.encode()).hexdigest())
        return self._sha[1]

    def ckey(self, cand=None):
        """Compile key: song text, slot, section, the candidate swapped in (None: the song as it is) and the stamp of every
        WAV in the mix (a sample re-rendered in place under the same path must not serve the old mix)."""
        stamps = self._stamps or "|".join(_stamp(f) for f in self.files)
        if cand:
            stamps = f"{_stamp(cand)}|{stamps}"
        inst = json.dumps(self.mix().get("instrument"), sort_keys=True)  # the instrument panel is compiled in, not patched
        return hashlib.sha1(f"{self.text_sha()}|{self.slot}|{self.orders}|{stamps}|{inst}".encode()).hexdigest()[:16]

    def key(self, cand=None):
        """Render cache key: the compile key plus what is patched into the module's header, mutes and the unwritten mix."""
        return hashlib.sha1(f"{self.ckey(cand)}|{self.silenced()}|{json.dumps(self.mix(), sort_keys=True)}".encode()).hexdigest()[:16]

    def meter_key(self):
        return hashlib.sha1(f"{self.ckey()}|{json.dumps(self.mix(), sort_keys=True)}".encode()).hexdigest()[:16]

    def measured(self, path):
        try:
            st = Path(path).stat()
            stamp = (st.st_mtime, st.st_size)
        except OSError:
            stamp = None
        if path not in self.meas or self.meas_stamp.get(path) != stamp:
            self.meas_stamp[path] = stamp
            try:
                self.meas[path] = measure(path)
            except (OSError, ValueError) as e:
                self.meas[path] = {"error": str(e)}
        return self.meas[path]

    def add_candidates(self, globs):
        added = []
        for g in re.split(r"[\r\n;]+", globs):
            g = g.strip().strip('"')
            if not g:
                continue
            pat = g if os.path.isabs(g) else str(self.base_dir / g)
            files = sorted(f for f in glob.glob(pat, recursive=True) if Path(f).suffix.lower() == ".wav") or [pat]
            for f in files:
                f = str(Path(f).resolve())
                if f not in self.cands():
                    self.cands().append(f)
                    added.append(f)
        self.save_meta()
        self.queue_all()
        return added

    def remove_candidate(self, path):
        with self.lock:
            if path in self.cands():
                self.cands().remove(path)
            self.save_meta()

    def queue_all(self):
        with self.lock:
            for c in [None, *self.cands()]:  # the song as it is first, then the candidates
                k = self.key(c)
                if k not in self.renders:
                    f = self.cache_dir / f"{k}.wav"
                    if f.exists():
                        self.renders[k] = {"status": "ready", "file": str(f), "error": None, "peak": _peak(f.read_bytes()[44:])}
                    else:
                        self.renders[k] = {"status": "queued", "file": str(f), "error": None}
                        self._put(1 if c == self.want else 2 if c is None else 3, (k, c))
            mk = self.meter_key()
            if self.facts and (not self.meters or self.meters["key"] != mk):
                self.meters = {"key": mk, "status": "queued", "levels": None, "mix": self.mix(), "error": None}
                self._put(4, ("meters", mk))

    def compiled_it(self, cand=None, whole=False):
        """The tryout section (`whole`: the whole song) compiled with `cand` in the slot (None: the song as it is), memoised
        per compile key."""
        with self.lock:
            inst = self.mix().get("instrument") or {}
            if whole and not cand and self.it and not any(int(n) in (self.song.get("instruments") or {}) for n in inst):
                return self.it  # the song as reload compiled it: the same bytes as compiling it again from the dict
        ck = self.ckey(cand) + ("|whole" if whole else "")
        if ck not in self.compiled:
            with self.lock:
                base, slot = api.tryout_song(self.song, None if whole else self.orders), self.slot
                inst = self.mix().get("instrument") or {}
            for n, edit in inst.items():
                if int(n) in (base.get("instruments") or {}):
                    base["instruments"][int(n)] = voice_entry(base["instruments"][int(n)], edit)
            if cand:
                api.swap_sample(base, slot, Path(cand).resolve())
            it = api.compile_song(base, self.base_dir)[0]
            while len(self.compiled) >= 8:
                self.compiled.pop(next(iter(self.compiled)))
            self.compiled[ck] = it
        return self.compiled[ck]

    def live_it(self):
        """What the live engine plays: the whole song as it is now with the unwritten mix (faders patched into the header,
        the instrument panel compiled in); mutes are the engine's own."""
        return patch_it(self.compiled_it(whole=True), (), self.mix())

    def retry(self, path):
        with self.lock:
            k = self.key(path)
            self.renders[k] = {"status": "queued", "file": str(self.cache_dir / f"{k}.wav"), "error": None}
            self._put(1, (k, path))

    def close(self):
        """Another song replaced this one in the app: the worker stops after the job it is on (it would keep rendering
        into this song's cache and prune it against the new state's writes)."""
        self.closed = True
        self._put(-1, ("close",))

    def _worker(self):
        while not self.closed:
            job = self.jobs.get()[2]
            if job[0] == "close":
                return
            if job[0] == "build":
                self._build(job[1])
                continue
            if job[0] == "stems":
                self._stems(*(job[1] or ()))
                continue
            if job[0] == "meters":
                self._meters(job[1])
                continue
            if job[0] == "recipe":
                self._recipe_render(*job[1])
                continue
            if job[0] == "fetch":
                self._fetch_synth(job[1])
                continue
            k, cand = job
            with self.lock:
                if self.renders.get(k, {}).get("status") != "queued":
                    continue
                if self.key(cand) != k:  # settings changed since queueing; queue_all has queued the current key
                    self.renders.pop(k, None)
                    continue
                self.renders[k]["status"] = "rendering"
                silenced, mix = self.silenced(), self.mix()
            try:
                with LoadedModule(patch_it(self.compiled_it(cand), silenced, mix)) as lm:
                    pcm = lm.render(RATE)
                out = self.cache_dir / f"{k}.wav"
                _write_pcm(out, pcm)
                with self.lock:
                    self.renders[k].update(status="ready", file=str(out), peak=_peak(pcm))
                self._prune()
            except Exception as e:  # noqa: BLE001 - shown in the UI, worker must survive
                with self.lock:
                    self.renders[k].update(status="failed", error=f"{type(e).__name__}: {e}")

    def _meters(self, mk):
        with self.lock:
            if not self.meters or self.meters["key"] != mk:
                return
            self.meters["status"] = "measuring"
            mix, nch = self.meters["mix"], len(self.facts["channels"])
        try:
            levels = channel_levels(patch_it(self.compiled_it(), (), mix), nch, cancel=lambda: self.meters["key"] != mk)
            with self.lock:
                if levels is not None and self.meters["key"] == mk:
                    self.meters.update(status="ready", levels=levels)
        except Exception as e:  # noqa: BLE001
            with self.lock:
                if self.meters["key"] == mk:
                    self.meters.update(status="failed", error=f"{type(e).__name__}: {e}")

    def _prune(self, keep=60):
        """Every mute or fader change leaves a render in the cache: keep the newest `keep` WAVs, re-queue what is current."""
        with self.lock:
            for p in sorted(self.cache_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime)[:-keep]:
                p.unlink(missing_ok=True)
                self.renders.pop(p.stem, None)
            self.queue_all()

    # ---- the recipe panel: a slot whose WAV a sample recipe (SAMPLING.md) in the song's folder writes can be rendered again
    # from the app with its entry edited, as a new candidate for the slot (never over the recipe's own WAV); the entry that
    # made a candidate can be written back into the recipe

    def recipes(self):
        """[(recipe path, recipe_outputs)] of the sample recipes in the song's folder: YAML files with `samples:` and no
        `module:`. Memoised per file stamp."""
        from .synth import RecipeError, recipe_outputs
        out = []
        for p in sorted(self.base_dir.iterdir()):
            if p.suffix.lower() not in (".yaml", ".yml") or p == self.song_path or not p.is_file():
                continue
            st = p.stat()
            key = (str(p), st.st_mtime, st.st_size)
            if key not in self._recipe_memo:
                try:
                    head = yaml.safe_load(p.read_text(encoding="utf-8"))
                    ok = isinstance(head, dict) and "samples" in head and "module" not in head
                    self._recipe_memo[key] = recipe_outputs(p) if ok else None
                except (RecipeError, yaml.YAMLError, OSError, UnicodeDecodeError, ValueError, TypeError, KeyError, AttributeError):
                    self._recipe_memo[key] = None
            if self._recipe_memo[key]:
                out.append((p, self._recipe_memo[key]))
        return out

    def slot_recipe(self):
        """The recipe entry behind the slot's WAV: {"recipe", "name", "note", "spec" (the entry as YAML text), "wav"}, or
        None. A WAV the panel rendered carries the entry that made it (meta "recipe_of")."""
        from .synth import RecipeError, recipe_entry
        cur = self.current_file()
        if not cur:
            return None
        made = (self.meta.get("recipe_of") or {}).get(cur)
        if made and Path(made["recipe"]).exists():
            return {**made, "wav": cur}
        for rec, outs in self.recipes():
            for wav, name, note in outs:
                if str(wav) == cur:
                    st = rec.stat()
                    key = (str(rec), st.st_mtime, st.st_size, name)
                    if key not in self._recipe_memo:
                        try:
                            self._recipe_memo[key] = yaml.safe_dump(recipe_entry(rec, name)[0], default_flow_style=False,
                                                                    sort_keys=False, width=100)
                        except RecipeError:
                            self._recipe_memo[key] = None
                    if self._recipe_memo[key] is None:
                        return None
                    return {"recipe": str(rec), "name": name, "note": note, "wav": cur, "spec": self._recipe_memo[key]}
        return None

    @staticmethod
    def _recipe_spec(text):
        try:
            spec = yaml.safe_load(text or "")
        except yaml.YAMLError as e:
            raise ValueError(f"the sample entry is not YAML: {e}")
        if not isinstance(spec, dict):
            raise ValueError("the sample entry is a YAML mapping (patch: ..., note: ..., hold: ...)")
        return spec

    def request_recipe_render(self, text):
        """Render the slot's recipe entry as `text` (YAML) says, as a new candidate for the slot (a job on the worker)."""
        rec = self.slot_recipe()
        if not rec:
            raise ValueError(f"slot {self.slot}'s WAV is not written by a sample recipe in the song's folder")
        spec = self._recipe_spec(text)
        with self.lock:
            self.recipe_job = {"status": "queued", "error": None, "log": [], "file": None}
        self._put(0, ("recipe", (rec, spec, text, self.slot)))

    def _recipe_render(self, rec, spec, text, slot):
        from .synth import RecipeError, SynthMissing, render_one
        with self.lock:
            self.recipe_job.update(status="rendering", error=None, need=None)
        src = Path(rec["wav"])
        stem = re.sub(r"-r\d+$", "", src.stem)
        out = next(q for q in (src.with_name(f"{stem}-r{k}.wav") for k in itertools.count(1)) if not q.exists())
        try:
            render_one(rec["recipe"], rec["name"], spec, rec["note"], out, log=lambda s: self.recipe_job["log"].append(s))
        except ImportError as e:
            return self._recipe_failed(f"rendering needs pedalboard and the synths (SAMPLING.md, Setup): {e}")
        except SynthMissing as e:  # the page offers the download (fetch_synth) and renders again after it
            self._recipe_retry = (rec, spec, text, slot)
            return self._recipe_failed(str(e), need=e.kind)
        except (RecipeError, OSError, ValueError, KeyError, TypeError) as e:
            return self._recipe_failed(f"{type(e).__name__}: {e}")
        with self.lock:
            self.meta.setdefault("recipe_of", {})[str(out.resolve())] = {k: rec[k] for k in ("recipe", "name", "note")} | {"spec": text}
            if self.slot == slot:
                self.add_candidates(str(out))
            else:
                self.meta["candidates"].setdefault(str(slot), []).append(str(out.resolve()))
                self.save_meta()
            self.recipe_job.update(status="done", file=str(out))

    def _recipe_failed(self, error, need=None):
        with self.lock:
            self.recipe_job.update(status="failed", error=error, need=need)

    def request_fetch_synth(self, kind):
        from .synth import FETCH
        if kind not in FETCH:
            raise ValueError(f"no download for '{kind}'")
        with self.lock:
            self.recipe_job = {"status": "fetching", "error": None, "log": [], "file": None, "need": kind, "got": 0, "size": 0}
        self._put(0, ("fetch", kind))

    def _fetch_synth(self, kind):
        """Download a synth the recipe panel's last render missed, then render that entry again."""
        from .synth import fetch_synth
        try:
            fetch_synth(kind, lambda got, size: self.recipe_job.update(got=got, size=size))
        except (OSError, ValueError) as e:  # urllib's errors are OSErrors; a bad zip is a ValueError
            return self._recipe_failed(f"the download failed: {type(e).__name__}: {e}", need=kind)
        retry, self._recipe_retry = self._recipe_retry, None
        if retry:
            self._recipe_render(*retry)
        else:
            with self.lock:
                self.recipe_job.update(status="fetched")

    def recipe_write(self, text):
        """The slot's recipe entry replaced by `text` (YAML) in the recipe file, in place: a one-line entry stays one line
        (its trailing comment kept), a block entry is re-dumped as a block; the rest of the recipe is untouched."""
        rec = self.slot_recipe()
        if not rec:
            raise ValueError(f"slot {self.slot}'s WAV is not written by a sample recipe in the song's folder")
        spec = self._recipe_spec(text)
        from .synth import RecipeError, expand
        try:
            list(expand({"samples": {rec["name"]: spec}}))
        except RecipeError as e:
            raise ValueError(str(e))
        path = Path(rec["recipe"])
        raw = path.read_bytes()
        crlf = b"\r\n" in raw
        lines = raw.decode("utf-8").replace("\r\n", "\n").splitlines(keepends=True)
        j = next((j for j, k in self._children(lines, self._top(lines, "samples")) if k == rec["name"]), None)
        m = self._entry(lines[j], re.escape(rec["name"]) + ":") if j is not None else None
        if m is None:
            raise ValueError(f"the recipe's entry '{rec['name']}' is not written as one mapping the app can replace")
        self._redump(lines, j, m, spec)
        _atomic(path, "".join(lines).replace("\n", "\r\n" if crlf else "\n").encode("utf-8"))
        with self.lock:
            self.meta.setdefault("recipe_of", {})[self.current_file()] = {k: rec[k] for k in ("recipe", "name", "note")} | {"spec": text}
            self.save_meta()
            self.recipe_job = {"status": "written", "error": None, "log": [], "file": None}

    # ---- listening notes

    def version(self):
        """The song text the notes were made against: a short hash of the file and its modification time."""
        return {"hash": self.text_sha()[:8],
                "mtime": datetime.datetime.fromtimestamp(self.mtime).isoformat(timespec="seconds")}

    def sounding(self, order, row):
        """The channels sounding at (order, row) of the facts' order list (see sounding_table)."""
        with self.lock:
            if self.sound_table is None:
                self.sound_table = sounding_table(self.mod, self.facts)
                self._rescan_notes()
            rows = self.sound_table[order] if 0 <= order < len(self.sound_table) else []
            return rows[min(row, len(rows) - 1)] if rows else []

    def _rescan_notes(self):
        """Notes made against this very song text get their sounding lists recomputed from the fresh table (the rule can
        improve; the listener's tag, words and picked channels are untouched)."""
        v, changed = self.version()["hash"], False
        for n in self.notes:
            if (n.get("version") or {}).get("hash") == v and 0 <= n["order"] < len(self.sound_table):
                rows = self.sound_table[n["order"]]
                new = rows[min(n["row"], len(rows) - 1)] if rows else []
                if new != n.get("sounding"):
                    n["sounding"], changed = new, True
        if changed:
            self.save_notes()

    def sounding_rows(self, order):
        """One order for the page's live strip: per row, [channel, sample, looped] triples."""
        self.sounding(order, 0)
        rows = self.sound_table[order] if 0 <= order < len(self.sound_table) else []
        return [[[e["ch"], e["sample"], int(e["loop"])] for e in r] for r in rows]

    def add_note(self, body):
        """A note at (order, row) of the facts' order list with what was playing; the channels sounding there and the song
        version are filled in here. Saves the JSON and rewrites the report. Returns the note."""
        f = self.facts
        if not f:
            raise ValueError("the song does not compile")
        order = max(0, min(len(f["orders"]) - 1, int(body.get("order") or 0)))
        o = f["orders"][order]
        row = max(0, min(o["rows"] - 1, int(body.get("row") or 0)))
        with self.lock:
            note = {"id": max((n["id"] for n in self.notes), default=0) + 1, "when": datetime.datetime.now().isoformat(timespec="seconds"),
                    "version": self.version(), "order": order, "pattern": o["pattern"], "row": row,
                    "span": [o["start"], o["seconds"]],  # the order's place in this version (an archive's report uses it)
                    "time": round(o["start"] + o["seconds"] * row / o["rows"], 2),
                    "tag": str(body.get("tag") or "note")[:40], "text": str(body.get("text") or "")[:2000],
                    "channels": sorted({int(c) for c in body.get("channels") or []}),
                    "sounding": self.sounding(order, row),
                    "playing": {"source": str(body.get("source") or "song"), "candidate": body.get("candidate"), "slot": self.slot,
                                "section": list(self.orders) if self.orders else None, "loop": self.meta.get("loop"),
                                "muted": self.silenced(), "mix": self.mix()}}
            self.notes.append(note)
            self.save_notes()
        return note

    def edit_note(self, nid, body):
        with self.lock:
            for n in self.notes:
                if n["id"] == nid:
                    if body.get("delete"):
                        self.notes.remove(n)
                    else:
                        for k in ("text", "tag"):
                            if k in body:
                                n[k] = str(body[k])[:2000]
                        if "channels" in body:
                            n["channels"] = sorted({int(c) for c in body["channels"]})
                    break
            self.save_notes()

    def save_notes(self):
        _atomic_text(self.notes_path, json.dumps(self.notes, indent=1))
        _atomic_text(self.notes_path.with_suffix(".md"), self.report())

    def _archive_old_notes(self):
        """Notes made against another version of the song text move to `<song>.notes-<hash>.json` and `.md` beside it,
        so the active file and the NOTES tab hold only notes on the song as it is now; an archive's report keeps that
        version's stamp."""
        v = self.version()["hash"]
        old = [n for n in self.notes if (n.get("version") or {}).get("hash") != v]
        if not old:
            return
        for h in sorted({(n.get("version") or {}).get("hash") or "unknown" for n in old}):
            batch = [n for n in old if ((n.get("version") or {}).get("hash") or "unknown") == h]
            p = self.song_path.with_name(f"{self.song_path.stem}.notes-{h}.json")
            kept = _read_json(p, [], self.notices)
            seen = {(n["id"], n.get("when")) for n in kept}
            kept += [n for n in batch if (n["id"], n.get("when")) not in seen]
            _atomic_text(p, json.dumps(kept, indent=1))
            _atomic_text(p.with_suffix(".md"), self.report(kept, batch[0].get("version")))
        self.notes = [n for n in self.notes if n not in old]
        self.save_notes()

    def report(self, notes=None, version=None):
        """<song>.notes.md (or an archive's): the notes grouped by order, each with its tag, the channels the listener
        pointed at in bold, what was sounding there, what was playing and their words; then the tryout ratings. For a
        collaborator who cannot listen."""
        f, v, notes = self.facts, version or self.version(), self.notes if notes is None else notes
        fmt = lambda t: f"{int(t // 60)}:{t % 60:04.1f}"  # noqa: E731
        L = [f"# Listening notes: {f['title'] if f else self.song_path.stem}", "",
             f"`{self.song_path.name}` version {v['hash']} ({v['mtime']}), {len(notes)} note{'s' if len(notes) != 1 else ''}.",
             "Time is the position in the whole song where the listener clicked (allow up to a second of reaction delay); ord is",
             "the order index, row the row in its pattern. **Bold** channels are the ones the listener pointed at; the others are",
             "what was sounding there (sample number after the name; `~` marks a looped tone still held from an earlier note).", ""]
        by = {}
        for n in notes:
            by.setdefault(n["order"], []).append(n)
        for order in sorted(by):
            # the order as the notes' own version had it (an archive's notes were made on another order list); notes from
            # before the span was kept fall back to the current song for notes on this version, else to the pattern name
            n0 = next((n for n in by[order] if n.get("span")), None)
            o = {"pattern": n0["pattern"], "start": n0["span"][0], "seconds": n0["span"][1]} if n0 else (
                f["orders"][order] if f and order < len(f["orders"]) and version is None else None)
            name = o["pattern"] if o else by[order][0].get("pattern")
            L += [f"## ord {order} `{name}` ({fmt(o['start'])} to {fmt(o['start'] + o['seconds'])})" if o
                  else f"## ord {order} `{name}`" if name else f"## ord {order}", ""]
            for n in sorted(by[order], key=lambda n: (n["row"], n["id"])):
                picked = set(n.get("channels") or [])
                snd = []
                for s in n.get("sounding") or []:
                    txt = f"{s['name']} {s['sample']:02d}" if s.get("sample") else s["name"]
                    txt += "~" if s.get("loop") and s.get("ago", 0) > 0 else ""
                    snd.append(f"**{txt}**" if s["ch"] in picked else txt)
                p = n.get("playing") or {}
                what = {"song": "the song", "candidate": f"candidate {p.get('candidate')} in slot {p.get('slot')}",
                        "sample alone": f"the sample alone ({p.get('candidate')}, so the position is the section start)"}.get(p.get("source"), p.get("source") or "")
                if p.get("muted") and f:
                    what += ", muted: " + ", ".join(f["channels"][i] for i in p["muted"] if i < len(f["channels"]))
                if p.get("loop"):
                    what += ", looping ord {} row {} to ord {} row {}".format(*p["loop"]["from"], *p["loop"]["to"])
                if p.get("mix"):
                    what += ", unwritten mix " + json.dumps(p["mix"], separators=(",", ":"))
                old = "" if (n.get("version") or {}).get("hash") == v["hash"] else f" (made against version {(n.get('version') or {}).get('hash')})"
                L.append(f"- **{n['tag'].upper()}** at {fmt(n['time'])}, row {n['row']:02d}{old}: " + (", ".join(snd) or "nothing sounding")
                         + f". Playing {what}." + (f' "{n["text"]}"' if n.get("text") else ""))
            L.append("")
        rated = []
        for slot, cands in self.meta.get("candidates", {}).items():
            for c in cands:
                r = self.meta["ratings"].get(c) or {}
                if r.get("stars") or r.get("rejected") or r.get("note"):
                    rated.append(f"- slot {slot}: {Path(c).stem} " + ("rejected" if r.get("rejected") else "*" * int(r.get("stars") or 0))
                                 + (f' "{r["note"]}"' if r.get("note") else ""))
        if rated:
            L += ["## Tryout ratings", ""] + rated + [""]
        return "\n".join(L)

    # ---- writing the song

    class _Entry:
        def __init__(self, groups):
            self._g = groups

        def groups(self):
            return self._g

        def group(self, k):
            return self._g[k - 1]

    @classmethod
    def _entry(cls, line, key):
        """A mapping entry `key` on `line` as (indent, key, spaces, one-line flow mapping or None, trailing spaces and
        comment); the flow mapping ends at the brace that closes it (quotes and nesting followed), so a `}` in a trailing
        comment is never taken for part of it. None when the line is not such an entry. The result has .groups() and
        .group(k) like a match."""
        m = re.match(rf"^(\s+)({key})([ \t]*)(.*?)$", line.rstrip("\n"))
        if not m:
            return None
        indent, k, sp, rest = m.groups()
        if not rest.startswith("{"):
            return cls._Entry((indent, k, sp, None, rest)) if re.fullmatch(r"[ \t]*(#.*)?", rest) else None
        depth, quote, j = 0, None, 0
        while j < len(rest):
            c = rest[j]
            if quote:
                if c == "\\" and quote == '"':
                    j += 1
                elif c == quote:
                    quote = None
            elif c in "'\"":
                quote = c
            elif c in "{[":
                depth += 1
            elif c in "}]":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        flow, tail = rest[:j + 1], rest[j + 1:]
        if depth != 0 or not re.fullmatch(r"[ \t]*(#.*)?", tail):
            return None
        return cls._Entry((indent, k, sp, flow, tail))

    @staticmethod
    def _redump(lines, i, m, entry, keys=None):
        """Replace the mapping at line i (`m` from _entry) with `entry` in its own layout: a one-line flow mapping stays
        one line (with `keys`, only those scalar values are substituted inside it, so a hand-aligned line keeps its
        spacing), a block (the deeper-indented lines that follow) is re-dumped as a block. Returns the number of lines
        the entry now occupies."""
        indent, key, sp, flow, tail = m.groups()
        nl = "\n" if lines[i].endswith("\n") else ""
        if flow and keys:
            for k in (k for k in keys if k in entry):
                flow, n = re.subn(rf"(\b{k}:\s*)[^,}}]*", rf"\g<1>{entry[k]}", flow)
                if not n:
                    flow = f"{{{k}: {entry[k]}}}" if flow.strip() == "{}" else flow[:-1].rstrip() + f", {k}: {entry[k]}}}"
            lines[i] = f"{indent}{key}{sp}{flow}{tail}{nl}"
            return 1
        if flow:
            lines[i] = f"{indent}{key}{sp}{yaml.safe_dump(entry, default_flow_style=True, width=10 ** 6, sort_keys=False).strip()}{tail}{nl}"
            return 1
        j = i + 1
        while j < len(lines) and lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) > len(indent):
            j += 1
        block = [f"{indent}  {b}\n" for b in yaml.safe_dump(entry, default_flow_style=False, width=10 ** 6, sort_keys=False).splitlines()]
        lines[i:j] = [lines[i]] + block
        return 1 + len(block)

    def _edit_text(self, song, samples=(), channels=(), mix_volume=None, keys=None, instruments=()):
        """Song text with sample slot entries `{slot: entry}`, channel entries `{index: entry}`, instrument entries
        `{number: entry}` and the module's mix_volume written in place (`keys`: only those scalar keys change inside a
        one-line sample or channel entry; an instrument entry is re-dumped whole, its envelopes being nested); the rest of
        the document, comments included, is untouched. When a line cannot be found (a one-line `module:`, a block-style
        channel list) the whole `song` dict is re-dumped instead (comments lost, so the diff says so). Returns (text,
        redumped)."""
        samples, channels, instruments = dict(samples), dict(channels), dict(instruments)
        lines = self.text.splitlines(keepends=True)
        pending = ({("smp", k) for k in samples} | {("ch", k) for k in channels} | {("ins", k) for k in instruments}
                   | ({("mv",)} if mix_volume is not None else set()))
        section = sub = None
        item = cind = mod_line = -1
        i = 0
        while i < len(lines):
            line = lines[i]
            ind, s, n = len(line) - len(line.lstrip()), line.strip(), 1
            if not s or s.startswith("#"):
                i += 1
                continue
            if ind == 0:
                section, sub = line.split(":")[0], None
                mod_line = i if section == "module" else mod_line
            elif section == "samples":
                m = self._entry(line, r"\d+:")
                if m and int(m.group(2)[:-1]) in samples:
                    n = self._redump(lines, i, m, samples[int(m.group(2)[:-1])], keys)
                    pending.discard(("smp", int(m.group(2)[:-1])))
            elif section == "instruments":
                m = self._entry(line, r"\d+:")
                if m and int(m.group(2)[:-1]) in instruments:
                    n = self._redump(lines, i, m, instruments[int(m.group(2)[:-1])])
                    pending.discard(("ins", int(m.group(2)[:-1])))
            elif section == "module":
                if s.startswith("channels:"):
                    sub, item, cind = "ch", -1, ind
                elif sub == "ch" and ind >= cind and s.startswith("-"):
                    item += 1
                    m = self._entry(line, "-")
                    if item in channels and m:
                        n = self._redump(lines, i, m, channels[item], keys)
                        pending.discard(("ch", item))
                elif sub == "ch" and ind <= cind:
                    sub = None
                if mix_volume is not None and s.startswith("mix_volume:"):
                    lines[i] = re.sub(r"(mix_volume:\s*)\S+", rf"\g<1>{mix_volume}", line)
                    pending.discard(("mv",))
            i += n
        if ("mv",) in pending and 0 <= mod_line < len(lines) - 1 and re.match(r"^module:\s*$", lines[mod_line]):
            ind = len(lines[mod_line + 1]) - len(lines[mod_line + 1].lstrip())
            lines.insert(mod_line + 1, " " * ind + f"mix_volume: {mix_volume}\n")
            pending.discard(("mv",))
        if pending:
            return api.to_yaml(song), True
        return "".join(lines), False

    def patched_text(self, cand):
        """Song text with the slot pointed at `cand` (see _edit_text)."""
        import copy
        song = copy.deepcopy(self.song)
        entry = api.swap_sample(song, self.slot, cand)
        entry["file"] = os.path.relpath(cand, self.base_dir).replace(os.sep, "/")
        return self._edit_text(song, samples={self.slot: entry})

    def mix_text(self):
        """Song text with the unwritten mix written in: module.channels volume/pan, module.mix_volume, the samples'
        global_volume (the default note volume would be overridden by every cell that sets one) and the instrument panel's
        fields on their instruments."""
        import copy
        mix, song = self.mix(), copy.deepcopy(self.song)
        chans = song["module"]["channels"]
        if isinstance(chans, int):
            chans = song["module"]["channels"] = [{"name": f"Ch {i + 1}"} for i in range(chans)]
        touched = {}
        for k in ("volume", "pan"):
            for i, v in (mix.get(k) or {}).items():
                if int(i) < len(chans):
                    chans[int(i)] = touched[int(i)] = {**(chans[int(i)] or {}), k: v}
        if mix.get("mix_volume") is not None:
            song["module"]["mix_volume"] = mix["mix_volume"]
        smp = {}
        for s, g in (mix.get("sample_volume") or {}).items():
            if int(s) in song["samples"]:
                song["samples"][int(s)]["global_volume"] = g
                smp[int(s)] = song["samples"][int(s)]
        ins = {}
        for n, edit in (mix.get("instrument") or {}).items():
            if int(n) in (song.get("instruments") or {}):
                song["instruments"][int(n)] = ins[int(n)] = voice_entry(song["instruments"][int(n)], edit)
        return self._edit_text(song, samples=smp, channels=touched, mix_volume=mix.get("mix_volume"),
                               keys=("volume", "pan", "global_volume"), instruments=ins)

    def _diff(self, new, redump):
        d = list(difflib.unified_diff(self.text.splitlines(), new.splitlines(), self.song_path.name, self.song_path.name, lineterm="", n=2))
        return {"lines": d, "redump": redump, "path": str(self.song_path)}

    def diff(self, cand):
        return self._diff(*self.patched_text(cand))

    def mix_diff(self):
        return self._diff(*self.mix_text())

    def apply(self, cand):
        """The slot pointed at `cand` in the song file: the way every edit is written (refused while the song changed on
        disk, compiled whole first, one undo step)."""
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the write does not overwrite that change")
            new, _ = self.patched_text(cand)
            loaded = load_song_text(new, self.base_dir, str(self.song_path))  # SongError: nothing is written
            before = self._meta_view()
            self.meta["candidates"].pop(str(self.slot), None)  # the choice is made: the slot's list goes (ratings stay, keyed by file)
            if self.want == cand:
                self.want = None
            self.save_meta()
            self._commit(new, loaded)
            self._attach_meta(before)
        self._put(0, ("build", False))

    def apply_mix(self):
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the write does not overwrite that change")
            new, _ = self.mix_text()
            loaded = load_song_text(new, self.base_dir, str(self.song_path))
            before = self._meta_view()
            self.meta["mix"] = {}
            self.save_meta()
            self._commit(new, loaded)
            self._attach_meta(before)
        self._put(0, ("build", False))

    # ---- build / export

    def request_build(self, render):
        with self.lock:
            self.build = {"status": "queued", "render": render}
        self._put(0, ("build", render))

    def _build(self, render):
        with self.lock:
            self.build = {"status": "building", "render": render}
        out_it = self.song_path.with_suffix(".it")
        try:
            r = api.build(self.song_path, out_it)
            r["it"] = str(out_it)
            if render:
                out_wav = self.song_path.with_suffix(".wav")
                r["seconds"] = api.render(out_it, out_wav)
                r["wav"] = str(out_wav)
            r["status"] = "done"
        except (SongError, OSError, ValueError) as e:
            r = {"status": "failed", "error": "\n".join(getattr(e, "errors", []) or [str(e)])}
        with self.lock:
            self.build = r

    # ---- stems

    def request_stems(self, fmt="wav", song=False, stems=True):
        with self.lock:
            self.stems = {"status": "queued", "done": 0, "total": 0, "dir": None, "song": None, "fmt": fmt, "error": None}
        self._put(0, ("stems", (fmt if fmt in ENCODE else "wav", bool(song), bool(stems))))

    def _stems(self, fmt="wav", song=False, stems=True):
        """One file per channel that plays anything, rendered with every other channel disabled, in <song>_stems/, and with
        `song` the whole song as <song>.<fmt> beside it; `fmt` "mp3", "ogg" or "flac" encodes through ffmpeg (ENCODE). The song as
        written: the unwritten mix is not applied."""
        with self.lock:
            f = self.facts
            out_dir = self.song_path.with_name(self.song_path.stem + "_stems")
            chans = [i for i in range(len(f["channels"])) if any(u[i] for u in f["use"])] if f and stems else []
            whole = self.song_path.with_suffix("." + fmt) if song else None
            self.stems = {"status": "rendering", "done": 0, "total": len(chans) + bool(whole), "dir": str(out_dir) if chans else None,
                          "song": str(whole) if whole else None, "fmt": fmt, "error": None}
        try:
            write = (lambda p, pcm: _encode(p, pcm, fmt)) if fmt in ENCODE else _write_pcm
            if fmt in ENCODE:
                ffmpeg_exe()  # before anything renders
            it = api.compile_song(self.song, self.base_dir)[0]
            todo = [(whole, [])] if whole else []
            for i in chans:
                name = re.sub(r"[^\w-]+", "_", f["channels"][i]).strip("_") or "ch"
                todo.append((out_dir / f"{i + 1:02d}-{name}.{fmt}", [j for j in range(len(f["channels"])) if j != i]))
            if chans:
                out_dir.mkdir(exist_ok=True)
            for n, (path, silenced) in enumerate(todo):
                with LoadedModule(patch_it(it, silenced)) as lm:
                    write(path, lm.render(RATE))
                with self.lock:
                    self.stems["done"] = n + 1
            with self.lock:
                self.stems["status"] = "done"
        except (SongError, OSError, ValueError) as e:
            with self.lock:
                self.stems.update(status="failed", error="\n".join(getattr(e, "errors", []) or [str(e)]))

    # ---- pattern editing: each edit is a small in-place change of the pattern's `data: |` rows (the other cells of a row,
    # its label, its comment and every other line stay as they are), checked by compiling the whole song before anything is
    # written; the song texts before each write are the undo history

    @staticmethod
    def _pattern_block(lines, name):
        """The literal block holding pattern `name`'s rows: (first line index, end index). The pattern is `name:` with a
        `data: |` under it, or `name: |` itself. ValueError when it is written another way (flow or quoted data)."""
        section, key_ind, i = None, None, 0
        while i < len(lines):
            line = lines[i]
            s, ind = line.strip(), len(line) - len(line.lstrip())
            if s and not s.startswith("#") and ind == 0:
                section = line.split(":")[0].strip()
            elif section == "patterns" and s and not s.startswith("#") and key_ind is None:
                m = re.match(r"^(\s+)(['\"]?)(.+?)\2\s*:\s*(\|[-+]?)?\s*(#.*)?$", line.rstrip("\n"))
                if m and m.group(3) == name:
                    key_ind = ind
                    if m.group(4):
                        return State._block_end(lines, i, ind)
            elif key_ind is not None:
                if s and ind <= key_ind:
                    break
                if re.match(r"^\s+data\s*:\s*\|[-+]?\s*(#.*)?$", line.rstrip("\n")):
                    return State._block_end(lines, i, ind)
            i += 1
        raise ValueError(f"pattern '{name}': its rows are not a literal block (data: |); edit it in the YAML")

    @staticmethod
    def _block_end(lines, i, ind):
        j = i + 1
        while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > ind):
            j += 1
        while j > i + 1 and not lines[j - 1].strip():  # trailing blank lines are not the block's
            j -= 1
        return i + 1, j

    @staticmethod
    def _put_cell(line, ch, cell):
        """Row line `line` with channel `ch`'s cell replaced by `cell` (the note ins vol fx text); its neighbours keep their
        text and spacing; missing cells up to `ch` are filled with empty ones."""
        nl = "\n" if line.endswith("\n") else ""
        body, sc, comment = line.rstrip("\n").partition(";")
        m = re.match(r"^(\s*)(\d+\s*:)?(\s*\|?)(.*?)(\|?\s*)$", body)
        ind, label, pre, inner, post = m.group(1), m.group(2) or "", m.group(3), m.group(4), m.group(5)
        parts = inner.split("|") if inner.strip() else []
        while len(parts) <= ch:
            if parts and not parts[-1].endswith(" "):
                parts[-1] += " "
            parts.append(" ... .. ... ...")
        old = parts[ch]
        lead, trail = old[: len(old) - len(old.lstrip())], old[len(old.rstrip()):]
        if ch == 0 and not lead and label and not pre:
            lead = " "
        parts[ch] = f"{lead}{cell}{trail if trail or ch == len(parts) - 1 else ' '}"
        return f"{ind}{label}{pre}{'|'.join(parts)}{post}{sc}{comment}{nl}"

    def edit_cells(self, index, cells):
        """Write `cells` ([{row, ch, cell}], cell the 'C-5 01 v64 A06' text) into pattern `index` of the compiled song, in
        place, as one undoable step (see edit_patterns)."""
        self.edit_patterns([(index, cells)])

    def edit_patterns(self, groups):
        """Write each (pattern index, cells) of `groups` in place, all as one undoable step. The whole song is compiled
        first: an edit that breaks it is refused (SongError) and nothing is written. Refused too when the song changed on
        disk since it was read (reload first)."""
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the edit does not overwrite that change")
            self._need_compiled()
            lines = self.text.splitlines(keepends=True)
            for index, cells in groups:
                self._edit_block(lines, int(index), cells)
            self._commit("".join(lines))  # compiled first (SongError: nothing is written)

    def _need_compiled(self):
        if self.mod is None:
            raise ValueError("the song does not compile (RENDER & EXPORT lists the errors): fix it in the YAML first")

    def _edit_block(self, lines, index, cells, nch=None):
        """`cells` written into pattern `index`'s rows in `lines` (in place). `nch`: the channel count when an edit of the
        same step added channels."""
        pat = self.mod.patterns[index]
        nch, nrows = nch or len(self.mod.channels), len(pat.rows)
        first, end = self._pattern_block(lines, pat.name)
        rows = [i for i in range(first, end) if lines[i].split(";", 1)[0].strip()]
        labels = [re.match(r"^\s*(\d+)\s*:", lines[i]) for i in rows]
        width, labelled = next((len(m.group(1)) for m in labels if m), 2), any(labels) or not rows
        ind = next((lines[i][: len(lines[i]) - len(lines[i].lstrip())] for i in range(first, end) if lines[i].strip()),
                   " " * (len(lines[first - 1]) - len(lines[first - 1].lstrip()) + 2))
        for c in sorted(cells, key=lambda c: int(c["row"])):
            r, ch, text = int(c["row"]), int(c["ch"]), str(c["cell"]).strip()
            if not (0 <= r < nrows and 0 <= ch < nch):
                raise ValueError(f"row {r}, channel {ch + 1} is outside pattern '{pat.name}' ({nrows} rows, {nch} channels)")
            while len(rows) <= r:  # rows the block leaves implied (empty) are written out up to this one
                at = rows[-1] + 1 if rows else end
                label = f"{len(rows):0{width}d}: " if labelled else ""
                lines.insert(at, f"{ind}{label}{' | '.join(['... .. ... ...'] * nch)}\n")
                end += 1
                rows.append(at)
            lines[rows[r]] = self._put_cell(lines[rows[r]], ch, text)

    # ---- song structure: the order list, patterns, channels and module settings, edited in the song text in place (the
    # layout the songs use: `orders: [..]` on one line, patterns as `name:` + `rows:` + `data: |`, channels one `- {..}`
    # per line, module settings as `key: value` lines); a batch of ops is one undo step, compiled before it is written

    MODULE_KEYS = {"title": None, "tempo": (32, 255), "speed": (1, 255), "global_volume": (0, 128), "mix_volume": (0, 128),
                   "separation": (0, 128)}

    def _commit(self, new, loaded=None):
        """`new` as the song, if the whole of it compiles (SongError otherwise: nothing written); one undo step. `loaded`:
        the (module, warnings) of `new`, when the caller compiled it already."""
        loaded = loaded or load_song_text(new, self.base_dir, str(self.song_path))
        self.history.append({"text": self.text, "meta": None})
        del self.history[:-self.UNDO_LIMIT]  # a song text each: a long session of edits on a big song adds up
        self.future.clear()
        self.write_song(new)
        self.reload(archive=False, loaded=loaded)

    META_KEYS = ("candidates", "muted", "solo", "mix", "orders", "loop")  # the tryout settings a song write may change
    UNDO_LIMIT = 200     # undo steps kept (the oldest go first)

    def _meta_view(self):
        import copy
        return copy.deepcopy({k: self.meta.get(k) for k in self.META_KEYS})

    def _attach_meta(self, before):
        """The tryout settings the last write changed, as they were, kept with its undo step (see undo)."""
        changed = {k: v for k, v in before.items() if v != self.meta.get(k)}
        if changed and self.history:
            self.history[-1]["meta"] = changed

    @staticmethod
    def _ind(line):
        return len(line) - len(line.lstrip())

    @staticmethod
    def _span(lines, i):
        """End (exclusive) of the entry whose key is on line i: up to the next line at its indentation or less; blank lines
        and outdented comments at the end belong to what follows."""
        ind, j = State._ind(lines[i]), i + 1
        while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("#") or State._ind(lines[j]) > ind):
            j += 1
        while j > i + 1 and (not lines[j - 1].strip() or (lines[j - 1].lstrip().startswith("#") and State._ind(lines[j - 1]) <= ind)):
            j -= 1
        return j

    @staticmethod
    def _top(lines, key):
        for i, line in enumerate(lines):
            if re.match(rf"^{re.escape(key)}\s*:", line):
                return i
        raise ValueError(f"the song has no top-level '{key}:'")

    @staticmethod
    def _children(lines, i):
        """(line index, key) of the entries directly under the mapping key on line i."""
        end, out, ind = State._span(lines, i), [], None
        for j in range(i + 1, end):
            s = lines[j].strip()
            if not s or s.startswith("#"):
                continue
            ind = State._ind(lines[j]) if ind is None else ind
            if State._ind(lines[j]) == ind:
                m = re.match(r"^\s*(['\"]?)(.+?)\1\s*:", lines[j])
                out.append((j, m.group(2) if m else None))
        return out

    @staticmethod
    def _yname(s):
        """`s` as a YAML scalar in a flow list or mapping: plain when that reads back as the same string, else quoted."""
        plain = (re.fullmatch(r"[A-Za-z_][\w .+()/'-]*|\+\+\+|---", s) and not s.endswith(" ")
                 and s.lower() not in ("true", "false", "yes", "no", "on", "off", "null", "y", "n"))
        return s if plain else json.dumps(s)

    def _pattern_key(self, lines, name):
        for j, k in self._children(lines, self._top(lines, "patterns")):
            if k == name:
                return j
        raise ValueError(f"no pattern '{name}'")

    @staticmethod
    def _row(line):
        """A row line as (head: indent, label and any leading pipe; the cells' texts with their spacing; tail: trailing
        pipe, spaces, comment, newline)."""
        nl = "\n" if line.endswith("\n") else ""
        body, sc, comment = line.rstrip("\n").partition(";")
        m = re.match(r"^(\s*)(\d+\s*:)?(\s*\|?)(.*?)(\|?\s*)$", body)
        return m.group(1) + (m.group(2) or "") + m.group(3), (m.group(4).split("|") if m.group(4).strip() else []), m.group(5) + sc + comment + nl

    @staticmethod
    def _rejoin(head, parts, cells, tail):
        """The row with `cells` (stripped texts) in the slots of `parts`, each slot keeping its spacing."""
        out = []
        for k, c in enumerate(cells):
            if k < len(parts):
                old = parts[k]
                out.append(old[: len(old) - len(old.lstrip())] + c + old[len(old.rstrip()):])
            else:
                if out and not out[-1].endswith(" "):
                    out[-1] += " "
                out.append(" " + c)
        return head + "|".join(out) + tail

    def _map_rows(self, lines, fn):
        """Every row of every pattern with its cells' texts passed through `fn` (a channel removed or moved)."""
        self._need_compiled()
        for pat in self.mod.patterns:
            first, end = self._pattern_block(lines, pat.name)
            for i in range(first, end):
                if lines[i].split(";", 1)[0].strip():
                    head, parts, tail = self._row(lines[i])
                    lines[i] = self._rejoin(head, parts, fn([p.strip() for p in parts]), tail)

    def _channel_lines(self, lines):
        mod = self._top(lines, "module")
        for j, k in self._children(lines, mod):
            if k == "channels":
                if lines[j].split("#")[0].split(":", 1)[1].strip():
                    raise ValueError("module.channels is written on one line: write one '- {name: ...}' per channel to edit channels here")
                return j, [i for i in range(j + 1, self._span(lines, j)) if lines[i].lstrip().startswith("-")]
        raise ValueError("module has no 'channels:' list")

    def _song_op(self, lines, orders, op, remap):
        kind, E = op.get("op"), "... .. ... ..."
        if kind == "orders":
            orders[:] = [str(o) for o in op["orders"]]
        elif kind in ("pattern_new", "pattern_clone"):
            name = str(op["name"]).strip()
            if not re.fullmatch(r"[A-Za-z][\w.-]*", name):
                raise ValueError(f"'{name}': a pattern name starts with a letter (letters, digits, _ . -)")
            if any(k == name for _, k in self._children(lines, self._top(lines, "patterns"))):
                raise ValueError(f"there is already a pattern '{name}'")
            if kind == "pattern_clone":
                j = self._pattern_key(lines, op["src"])
                end = self._span(lines, j)
                block = lines[j:end]
                block[0] = re.sub(r"^(\s*)(['\"]?).+?\2(\s*:)", lambda m: m.group(1) + self._yname(name) + m.group(3), block[0], count=1)
                lines[end:end] = block
            else:
                top = self._top(lines, "patterns")
                kids = self._children(lines, top)
                ind = " " * (self._ind(lines[kids[0][0]]) if kids else 2)
                end = self._span(lines, top)
                rows = max(1, min(200, int(op.get("rows") or 64)))
                lines[end:end] = [f"{ind}{name}:\n", f"{ind}  rows: {rows}\n", f"{ind}  data: |\n"]
        elif kind == "pattern_rename":
            old, name = str(op["old"]), str(op["new"]).strip()
            if not re.fullmatch(r"[A-Za-z][\w.-]*", name):
                raise ValueError(f"'{name}': a pattern name starts with a letter (letters, digits, _ . -)")
            if name != old and any(k == name for _, k in self._children(lines, self._top(lines, "patterns"))):
                raise ValueError(f"there is already a pattern '{name}'")
            j = self._pattern_key(lines, old)
            lines[j] = re.sub(r"^(\s*)(['\"]?).+?\2(\s*:)", lambda m: m.group(1) + self._yname(name) + m.group(3), lines[j], count=1)
            orders[:] = [name if o == old else o for o in orders]
        elif kind == "pattern_delete":
            name = str(op["name"])
            if name in orders:
                raise ValueError(f"pattern '{name}' is in the order list: take it out of the orders first")
            j = self._pattern_key(lines, name)
            del lines[j:self._span(lines, j)]
        elif kind == "pattern_rows":
            name, rows = str(op["name"]), max(1, min(200, int(op["rows"])))
            j = self._pattern_key(lines, name)
            kids = self._children(lines, j)
            at = next((i for i, k in kids if k == "rows"), None)
            if at is not None:
                lines[at] = re.sub(r"(rows\s*:\s*)\d+", rf"\g<1>{rows}", lines[at], count=1)
            elif kids:
                lines.insert(kids[0][0], f"{' ' * self._ind(lines[kids[0][0]])}rows: {rows}\n")
            else:
                raise ValueError(f"pattern '{name}' is written as one block: give it 'rows:' and 'data: |' in the YAML")
            first, end = self._pattern_block(lines, name)
            data = [i for i in range(first, end) if lines[i].split(";", 1)[0].strip()]
            for i in reversed(data[rows:]):  # rows past the new length go
                del lines[i]
        elif kind == "channel_rename":
            head, items = self._channel_lines(lines)
            i, name = int(op["ch"]), str(op["name"]).strip()[:20]
            m = self._entry(lines[items[i]], "-")
            if not m or not m.group(4):
                raise ValueError(f"channel {i + 1} is not a one-line '- {{...}}' entry: rename it in the YAML")
            self._redump(lines, items[i], m, {"name": self._yname(name) if name else '""'}, keys=("name",))
        elif kind == "channel_add":
            head, items = self._channel_lines(lines)
            if len(items) >= 64:
                raise ValueError("IT has at most 64 channels")
            ind = " " * (self._ind(lines[items[-1]]) if items else self._ind(lines[head]) + 2)
            at = items[-1] + 1 if items else head + 1
            name = str(op.get("name") or f"Ch {len(items) + 1}").strip()[:20]
            pan = "" if op.get("pan") is None else f", pan: {max(0, min(64, int(op['pan'])))}"
            lines.insert(at, f"{ind}- {{name: {self._yname(name)}{pan}}}\n")
        elif kind == "channel_remove":
            head, items = self._channel_lines(lines)
            i = int(op["ch"])
            if len(items) < 2:
                raise ValueError("a song needs a channel")
            self._map_rows(lines, lambda c: c[:i] + c[i + 1:])
            head, items = self._channel_lines(lines)
            del lines[items[i]]
            remap.append(lambda k: None if k == i else k - 1 if k > i else k)
        elif kind == "channel_move":
            head, items = self._channel_lines(lines)
            a, b = int(op["ch"]), int(op["to"])
            if not (0 <= b < len(items)) or a == b:
                return
            lo, hi = min(a, b), max(a, b)

            def move(c):
                c = c + [E] * (hi + 1 - len(c))
                c.insert(b, c.pop(a))
                while len(c) > 1 and c[-1] == E:  # no trailing empty cells added
                    c.pop()
                return c
            self._map_rows(lines, move)
            head, items = self._channel_lines(lines)
            texts = [lines[k] for k in items]
            texts.insert(b, texts.pop(a))
            for k, t in zip(items, texts):
                lines[k] = t
            order = list(range(len(items)))
            order.insert(b, order.pop(a))
            remap.append(lambda k, order=order: order.index(k))
        elif kind == "echo":
            self._echo(lines, orders, op, remap)
        elif kind in ("groove", "euclid", "chord", "layers"):
            self._compose(lines, op)
        elif kind == "sample_file":  # the slot pointed at another WAV (dropped on it), as the tryout's apply does it
            import copy
            num, f = int(op["num"]), Path(str(op["file"]))
            f = (f if f.is_absolute() else self.base_dir / f).resolve()
            if not f.exists():
                raise ValueError(f"no such WAV: {f}")
            entry = api.swap_sample(copy.deepcopy(self.song), num, f)
            frames = len(read_wav(f).channels[0])
            for k in ("loop", "sustain_loop"):  # loop points past the new WAV's end go
                if isinstance(entry.get(k), dict) and int(entry[k].get("end", 0)) > frames:
                    del entry[k]
            try:
                entry["file"] = os.path.relpath(f, self.base_dir).replace(os.sep, "/")
            except ValueError:
                entry["file"] = f.as_posix()
            self._song_op(lines, orders, {"op": "sample_set", "num": num, "entry": entry}, remap)
        elif kind == "sample_delete":
            num = int(op["num"])
            j = next((j for j, k in self._children(lines, self._top(lines, "samples")) if k == str(num)), None)
            if j is None:
                raise ValueError(f"no sample {num}")
            del lines[j:self._span(lines, j)]
        elif kind == "sample_process":
            import numpy as np
            from .wavload import write_wav
            num = int(op["num"])
            entry, path, w, x = self._sample_wav(num)
            n = x.shape[1]
            a = max(0, min(n - 1, int(op.get("a") or 0)))
            b = max(a + 1, min(n, int(op["b"]) if op.get("b") is not None else n))
            y, loops = process_wav(x, str(op["action"]), a, b, entry_loops(entry, w), op.get("frames") or 0)
            full = 128 if w.out_bits == 8 else 32768
            chans = np.clip(np.round(y * full), -full, full - 1).astype(np.int32).tolist()
            out = self._new_wav(path, str(op["action"]))
            write_wav(out, w.rate, chans, bits=w.out_bits, loop=loops.get("loop") or loops.get("sustain_loop"), root_note=w.root)
            self._created.append(out)
            try:
                rel = os.path.relpath(out, self.base_dir).replace(os.sep, "/")
            except ValueError:
                rel = out.as_posix()
            entry = dict(entry, file=rel)
            for k, lp in loops.items():
                if lp:
                    entry[k] = {"start": lp[0], "end": lp[1], **({"type": "pingpong"} if lp[2] else {})}
                else:
                    entry.pop(k, None)
            self._song_op(lines, orders, {"op": "sample_set", "num": num, "entry": entry}, remap)
        elif kind in ("instrument_set", "instrument_new", "sample_new", "sample_set"):
            section = "samples" if kind.startswith("sample") else "instruments"
            try:
                top = self._top(lines, section)
            except ValueError:
                raise ValueError("the song has no instruments: its cells play samples directly") if section == "instruments" else None
            if lines[top].split("#")[0].split(":", 1)[1].strip() not in ("", "{}"):
                raise ValueError(f"{section} is written on one line: write one entry per line to edit it here")
            if lines[top].split("#")[0].split(":", 1)[1].strip() == "{}":
                lines[top] = f"{section}:\n"
            kids = [(j, int(k)) for j, k in self._children(lines, top) if k and k.isdigit()]
            if kind == "sample_set":
                num, entry = int(op["num"]), op["entry"]
                old = (self.song.get("samples") or {}).get(num)
                if not isinstance(entry, dict) or not isinstance(old, dict):
                    raise ValueError(f"no sample {num}" if not isinstance(old, dict) else "a sample entry is a mapping")
                if str(num) in (self.mix().get("sample_volume") or {}) and entry.get("global_volume") != old.get("global_volume"):
                    raise ValueError(f"slot {num} has an unwritten GAIN in the tryout's mixer: WRITE MIX or RESET MIX first")
                j = next((j for j, n in kids if n == num), None)
                m = self._entry(lines[j], r"\d+:")
                if m is None:
                    raise ValueError(f"sample {num} is written across several lines: write it on one line, or as a block, to edit it here")
                # a one-line entry whose changed values are all scalars (and none removed) keeps its layout: only those
                # values are replaced; anything else re-dumps the entry
                changed = [k for k in entry if entry[k] != old.get(k)]
                scalar = m.group(4) and not set(old) - set(entry) and all(isinstance(entry[k], (int, str)) for k in changed)
                if scalar:
                    self._redump(lines, j, m, {k: self._yname(v) if isinstance(v, str) else v for k, v in entry.items()}, keys=changed)
                else:
                    self._redump(lines, j, m, entry)
                return
            if kind == "sample_new":
                f = Path(str(op["file"]))
                f = f if f.is_absolute() else self.base_dir / f
                if not f.exists():
                    raise ValueError(f"no such WAV: {f}")
                try:
                    rel = os.path.relpath(f.resolve(), self.base_dir).replace(os.sep, "/")
                except ValueError:
                    rel = f.resolve().as_posix()
                entry = {"file": rel, "name": str(op.get("name") or f.stem)[:25]}
            else:
                entry = op["entry"]
                if not isinstance(entry, dict):
                    raise ValueError("an instrument entry is a mapping")
            num = int(op.get("num") or max((n for _, n in kids), default=0) + 1)
            if kind == "instrument_set":
                if str(num) in (self.mix().get("instrument") or {}):
                    raise ValueError(f"instrument {num} has unwritten settings in the tryout's INSTRUMENT panel: WRITE or RESET them there first")
                j = next((j for j, n in kids if n == num), None)
                if j is None:
                    raise ValueError(f"no instrument {num}")
                m = self._entry(lines[j], r"\d+:")
                if m is None:
                    raise ValueError(f"instrument {num} is written across several lines: write it on one line, or as a block, to edit it here")
                self._redump(lines, j, m, entry)
            else:
                if any(n == num for _, n in kids):
                    raise ValueError(f"{section[:-1]} {num} exists already")
                if not 1 <= num <= 99:
                    raise ValueError("IT has at most 99 samples and 99 instruments")
                ind = " " * (self._ind(lines[kids[0][0]]) if kids else 2)
                after = [j for j, n in kids if n < num]
                at = self._span(lines, max(after)) if after else (kids[0][0] if kids else top + 1)
                flow = yaml.safe_dump(entry, default_flow_style=True, width=10 ** 6, sort_keys=False).strip()
                lines.insert(at, f"{ind}{num}: {flow}\n")
        elif kind == "instrument_delete":
            num = int(op["num"])
            j = next((j for j, k in self._children(lines, self._top(lines, "instruments")) if k == str(num)), None)
            if j is None:
                raise ValueError(f"no instrument {num}")
            del lines[j:self._span(lines, j)]
        elif kind == "module":
            key, value = str(op["key"]), op["value"]
            if key not in self.MODULE_KEYS:
                raise ValueError(f"'{key}' is not a module setting edited here")
            rng = self.MODULE_KEYS[key]
            text = self._yname(str(value)[:25]) if rng is None else str(max(rng[0], min(rng[1], int(value))))
            mod = self._top(lines, "module")
            if lines[mod].split("#")[0].split(":", 1)[1].strip():
                raise ValueError("module is written on one line: write it as a block to edit its settings here")
            kids = self._children(lines, mod)
            at = next((i for i, k in kids if k == key), None)
            if at is not None:
                lines[at] = re.sub(rf"^(\s*{key}\s*:\s*)([^#\n]*?)(\s*(#.*)?\n?)$", lambda m: m.group(1) + text + m.group(3), lines[at])
            else:
                lines.insert(mod + 1, f"{' ' * (self._ind(lines[kids[0][0]]) if kids else 2)}{key}: {text}\n")
        else:
            raise ValueError(f"unknown song edit '{kind}'")

    # effects an echo copy leaves out: song-wide ones (speed, jumps, breaks, tempo, global volume, pattern loops and
    # delays), which would act twice, and pan (the echo channel's pan is its own, set on its fader)
    ECHO_SKIP = set("ABCTVWXY")
    ECHO_SKIP_S = {0x6, 0x8, 0x9, 0xB, 0xE}

    def _echo(self, lines, orders, op, remap):
        """The `echo` op: the notes of channel `ch` copied into channel `to` (or a new channel, `to` null: "<name> echo",
        added at the end) `rows` rows later and `ticks` ticks late (SDx on each note), each volume at `level` percent.
        `pattern`: a pattern index, with `r0`..`r1` its rows (default all); null: every pattern, whole. `pan`: the new
        channel's pan (0-64). A volume is the
        cell's own, else the one the note starts at (the sample's default volume when the cell names an instrument, else
        the channel's last); the echo channel's pan is its fader's, so pan commands are not copied, nor song-wide
        effects. A copy that lands past its pattern's end is dropped, and one onto a cell that is not empty is skipped,
        each counted in the report. Part of the song edit's one undo step."""
        from .model import Cell, NOTE_FADE
        self._need_compiled()
        mod, nch = self.mod, len(self.mod.channels)
        src, delay, ticks = int(op["ch"]), int(op.get("rows") or 0), int(op.get("ticks") or 0)
        level = max(0.0, min(400.0, float(op.get("level", 60)))) / 100
        if not 0 <= src < nch:
            raise ValueError(f"no channel {src + 1}")
        if not (0 <= delay < 200 and 0 <= ticks <= 15) or delay + ticks == 0:
            raise ValueError("an echo is 0-199 rows and 0-15 ticks late, and later than the note")
        if ticks >= mod.speed:
            raise ValueError(f"at speed {mod.speed} a row has {mod.speed} ticks: a delay of {ticks} would skip the note")
        if op.get("to") is None:
            names = [c.name for c in mod.channels]
            base = f"{names[src]} echo"[:20]
            name = next(n for n in (base if k == 1 else f"{base[:17]} {k}" for k in itertools.count(1)) if n not in names)
            self._song_op(lines, orders, {"op": "channel_add", "name": name, "pan": op.get("pan")}, remap)
            to, width, new = nch, nch + 1, True
        else:
            to, width, new = int(op["to"]), nch, False
            if not 0 <= to < nch or to == src:
                raise ValueError("the echo goes into another channel of the song")
        insmode = mod.instruments is not None

        def default_volume(ins, note):
            if not ins:
                return None
            if insmode:
                if ins > len(mod.instruments) or note is None or note >= 120:
                    return None
                smp = mod.instruments[ins - 1].keymap[note][1]
            else:
                smp = ins
            return mod.samples[smp - 1].volume if 0 < smp <= len(mod.samples) else None

        written = past = skipped = lost = 0
        idxs = [int(op["pattern"])] if op.get("pattern") is not None else range(len(mod.patterns))
        for idx in idxs:
            pat = mod.patterns[idx]
            n = len(pat.rows)
            r0 = max(0, int(op.get("r0") or 0)) if op.get("pattern") is not None else 0
            r1 = min(n - 1, int(op["r1"])) if op.get("pattern") is not None and op.get("r1") is not None else n - 1
            vol, last_ins, cells = 64, 0, []
            for r in range(0, r1 + 1):  # rows before r0 only set the channel's volume and instrument
                c = pat.rows[r][src]
                if c.instrument:
                    last_ins = c.instrument
                    dv = default_volume(c.instrument, c.note)
                    vol = dv if dv is not None else vol
                if c.volcmd is not None and c.volcmd <= 64:
                    vol = c.volcmd
                if r < r0 or c.is_empty():
                    continue
                e = Cell(c.note, c.instrument, None, 0, 0)
                note_on = c.note is not None and c.note < 120
                if c.volcmd is not None and c.volcmd <= 64 or note_on:
                    e.volcmd = max(0, min(64, round(vol * level)))
                elif c.volcmd is not None and not 128 <= c.volcmd <= 192:  # slides, portamento, vibrato; not pan
                    e.volcmd = c.volcmd
                letter = chr(64 + c.effect) if c.effect else ""
                keep = letter and letter not in self.ECHO_SKIP and not (letter == "S" and c.param >> 4 in self.ECHO_SKIP_S)
                if keep:
                    e.effect, e.param = c.effect, c.param
                if ticks and c.note is not None:
                    lost += bool(keep and not (letter == "S" and c.param >> 4 == 0xD))
                    e.effect, e.param = 19, 0xD0 | ticks  # SDx
                if e.is_empty():
                    continue
                at = r + delay
                if at >= n:
                    past += 1
                    continue
                if not new and not pat.rows[at][to].is_empty():
                    skipped += 1
                    continue
                if e.note == NOTE_FADE or e.note is not None and e.note >= 120:
                    e.instrument = 0
                cells.append({"row": at, "ch": to, "cell": format_cell(e)})
            if cells:
                self._edit_block(lines, idx, cells, width)
                written += len(cells)
        if not written:
            raise ValueError("nothing to echo: no notes on that channel in the rows given" + (
                f" ({past} would land past the pattern's end, {skipped} on cells that are not empty)" if past or skipped else ""))
        name = f"new channel {to + 1}" if new else f"channel {to + 1}"
        msg = f"echo of channel {src + 1} into {name}: {written} cells"
        msg += f", {past} past a pattern's end dropped" if past else ""
        msg += f", {skipped} skipped (the cell there was not empty)" if skipped else ""
        msg += f", {lost} effects replaced by the tick delay" if lost else ""
        self._report.append(msg)

    def _compose(self, lines, op):
        """The selection bar's composition ops (compose.py), written into the song text: `groove` (ticks: the per-row
        delays) and `layers` (instruments, mode cycle / volume) over `chans` (None: every channel) in pattern `pattern`
        rows r0..r1, or in every pattern (pattern null); `euclid` (ch, hits, steps, rotate, every, prob, seed) and `chord`
        (ch, shape, inversion) in one pattern. Part of the song edit's one undo step, with a report of what changed."""
        from . import compose
        self._need_compiled()
        mod, kind, nch = self.mod, op["op"], len(self.mod.channels)
        whole = op.get("pattern") is None
        if whole and kind in ("euclid", "chord"):
            raise ValueError(f"{kind} works on a selection in one pattern")
        chans = [int(c) for c in op["chans"]] if op.get("chans") is not None else list(range(nch))
        ch = int(op.get("ch", chans[0] if chans else 0))
        if not chans or not all(0 <= c < nch for c in chans + [ch]):
            raise ValueError(f"the song has channels 1-{nch}")
        insmode = mod.instruments is not None

        def default_volume(cell):  # the volume a note without a volume command starts at: its sample's default
            if not cell.instrument:
                return None
            smp = cell.instrument
            if insmode:
                if cell.instrument > len(mod.instruments):
                    return None
                smp = mod.instruments[cell.instrument - 1].keymap[cell.note][1]
            return mod.samples[smp - 1].volume if 0 < smp <= len(mod.samples) else None

        written = skipped = 0
        for idx in range(len(mod.patterns)) if whole else [int(op["pattern"])]:
            rows = mod.patterns[idx].rows
            r0 = 0 if whole else max(0, int(op.get("r0") or 0))
            r1 = len(rows) - 1 if whole or op.get("r1") is None else min(len(rows) - 1, int(op["r1"]))
            if kind == "groove":
                cells, s = compose.groove(rows, chans, r0, r1, op.get("ticks") or [], mod.speed)
                skipped += s
            elif kind == "euclid":
                cells = compose.euclid(rows, ch, r0, r1, int(op["hits"]), int(op["steps"]), int(op.get("rotate") or 0),
                                       int(op.get("every") or 1), float(op.get("prob", 100)), int(op.get("seed", 1)))
            elif kind == "chord":
                cells = compose.chord(rows, ch, r0, r1, op.get("shape") or "maj", int(op.get("inversion") or 0), nch)
            else:
                cells = compose.layers(rows, chans, r0, r1, op.get("instruments") or [], op.get("mode") or "cycle",
                                       default_volume)
            if cells:
                self._edit_block(lines, idx, cells)
                written += len(cells)
        where = "the song" if whole else f"pattern '{mod.patterns[int(op['pattern'])].name}'"
        if not written:
            raise ValueError(f"{kind}: nothing to change in {where}" + (
                f" ({skipped} notes carry another effect, which a delay would replace)" if skipped else ""))
        msg = f"{kind}: {written} cell{'s' if written != 1 else ''} in {where}"
        msg += f", {skipped} notes left undelayed (they carry another effect)" if skipped else ""
        self._report.append(msg)

    def _write_orders(self, lines, orders):
        """The order list `orders` written in `lines` in the layout it has: a one-line flow list stays one line (its
        trailing comment kept); a block list (`- name` per line) stays a block, each entry that survives keeping its line
        (its trailing comment) and the comment lines above it, new entries written in the block's indentation. A flow
        list written across several lines becomes one line, refused when comments inside it would be lost."""
        i = self._top(lines, "orders")
        head = lines[i].rstrip("\n")
        m = re.match(r"^orders\s*:\s*\[.*\]\s*(#.*)?$", head)
        if m:
            lines[i] = f"orders: [{', '.join(self._yname(o) for o in orders)}]" + (f"  {m.group(1)}" if m.group(1) else "") + "\n"
            return
        end = self._span(lines, i)
        body = lines[i + 1:end]
        if re.match(r"^orders\s*:\s*\[", head):  # a flow list across several lines
            if any("#" in x for x in [head] + body):
                raise ValueError("the order list is a flow list across several lines with comments in it: write it on one "
                                 "line, or as a block (one '- name' per line), to edit it here without losing them")
            lines[i:end] = [f"orders: [{', '.join(self._yname(o) for o in orders)}]\n"]
            return
        if head.split("#")[0].split(":", 1)[1].strip():
            raise ValueError("the order list is written in a way the app cannot edit in place: write it on one line")
        groups, pending = [], []  # (name, [comment lines above it + its own line])
        for line in body:
            s = line.strip()
            if not s or s.startswith("#"):
                pending.append(line)
                continue
            em = re.match(r"^\s*-\s*(['\"]?)(.*?)\1\s*(#.*)?$", line.rstrip("\n"))
            if not em or not em.group(2) or em.group(2).startswith(("[", "{")):
                raise ValueError("the order list has an entry the app cannot edit in place: write one '- name' per line")
            groups.append((em.group(2), pending + [line]))
            pending = []
        ind = next((g[1][-1][: self._ind(g[1][-1])] for g in groups), "  ")
        used, out = set(), []
        for name in orders:
            k = next((k for k, g in enumerate(groups) if g[0] == name and k not in used), None)
            if k is None:
                out.append(f"{ind}- {self._yname(name)}\n")
            else:
                used.add(k)
                out += groups[k][1]
        out += pending
        out = [x if x.endswith("\n") else x + "\n" for x in out]
        if body and not body[-1].endswith("\n") and out:  # the file ended without a newline: it still does
            out[-1] = out[-1][:-1]
        lines[i + 1:end] = out

    def song_edit(self, ops):
        """Apply `ops` (dicts with `op`: orders, pattern_new, pattern_clone, pattern_rename, pattern_delete, pattern_rows,
        channel_rename, channel_add, channel_remove, channel_move, module, instrument_set / new / delete, sample_new,
        sample_set (the whole entry), sample_file (the slot pointed at another WAV), sample_delete, sample_process (an edit of the slot's audio written as a new WAV beside the song,
        the slot pointed at it), echo, groove, euclid, chord, layers) to the song text as one undo step. The tryout's
        channel mutes and unwritten faders follow a channel that moves or goes; its section and loop are dropped when they
        fall outside a changed order list."""
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the edit does not overwrite that change")
            lines = self.text.splitlines(keepends=True)
            meta_before = self._meta_view()
            before = [str(o) for o in (self.song.get("orders") or [])]
            orders, remap = list(before), []
            self._created = []  # WAVs written by sample edits: removed again when the edit is refused
            self._report = []   # what an op tells the page (the echo's counts)
            try:
                for op in ops:
                    self._song_op(lines, orders, op, remap)
                if orders != before:
                    self._write_orders(lines, orders)
                self._commit("".join(lines))
            except Exception:
                for f in self._created:
                    f.unlink(missing_ok=True)
                raise
            meta = self.meta
            for f in remap:
                mix = meta.get("mix") or {}
                for k in ("volume", "pan"):
                    if mix.get(k):
                        mix[k] = {str(f(int(c))): v for c, v in mix[k].items() if f(int(c)) is not None}
                meta["muted"] = sorted(f(c) for c in meta.get("muted") or [] if f(c) is not None)
                if meta.get("solo") is not None:
                    meta["solo"] = f(meta["solo"])
            n = len(self.facts["orders"]) if self.facts else 0
            if meta.get("orders") and meta["orders"][1] > n:
                meta["orders"] = None
            if meta.get("loop") and max(meta["loop"]["from"][0], meta["loop"]["to"][0]) >= n:
                meta["loop"] = None
            self._attach_meta(meta_before)
            self.save_meta()
            self.queue_all()
            return {"report": "; ".join(self._report)} if self._report else {}

    def undo(self, redo=False):
        """Back to the song text before the last write (or forward again). The tryout settings that write changed (mutes
        and faders following a channel that moved or went, the mix WRITE MIX cleared, the candidates U cleared, a section
        or loop dropped with the orders) go back with it, so a mute stays on the channel it was set on."""
        import copy
        with self.lock:
            src, dst = (self.future, self.history) if redo else (self.history, self.future)
            if not src:
                return
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first (the undo history is for the song the app wrote)")
            step = src.pop()
            meta = step.get("meta")
            dst.append({"text": self.text, "meta": copy.deepcopy({k: self.meta.get(k) for k in meta}) if meta else None})
            self.write_song(step["text"])
            if meta:
                self.meta.update(copy.deepcopy(meta))
                self.save_meta()
            self.reload(archive=False)

    # ---- sample editor

    def _sample_wav(self, num):
        entry = (self.song.get("samples") or {}).get(int(num))
        if not isinstance(entry, dict) or not entry.get("file"):
            raise ValueError(f"sample slot {num} has no WAV")
        path = (self.base_dir / str(entry["file"])).resolve()
        st = path.stat()
        return entry, path, *wav_array(str(path), (st.st_mtime, st.st_size))

    def sample_view(self, num, a=0, b=None, n=1000):
        """The editor's view of slot `num`: the WAV (frames, rate, channels, bits), its loops in the WAV's frames, the
        peaks of frames a..b in `n` columns, and what previews it in the live engine: [instrument index as libopenmpt
        counts (0-based; the sample in a song without instruments), note], preferring the note that plays it at C-5."""
        with self.lock:
            entry, path, w, x = self._sample_wav(num)
            frames = x.shape[1]
            a = max(0, min(frames - 1, int(a)))
            b = frames if b is None else max(a + 1, min(frames, int(b)))
            mn, mx = wave_peaks(x, a, b, max(16, min(4000, int(n))))
            player = [int(num) - 1, 60]
            if self.mod and self.mod.instruments is not None:
                hits = [(played != 60, i, note) for i, ins in enumerate(self.mod.instruments)
                        for note, (played, smp) in enumerate(ins.keymap) if smp == int(num)]
                player = [min(hits)[1], min(hits)[2]] if hits else None
            loops = entry_loops(entry, w)
            return {"num": int(num), "file": str(path), "frames": frames, "rate": w.rate, "channels": x.shape[0], "bits": w.bits,
                    "root": format_note(w.root) if w.root is not None and 0 <= w.root < 120 else None,
                    "a": a, "b": b, "min": mn, "max": mx, "player": player,
                    "loops": {k: list(v) if v else None for k, v in loops.items()},
                    "wav_loop": list(w.loops[0]) if w.loops else None}

    def _new_wav(self, src, action):
        """A path beside the song for an edited copy of `src`: <stem>-<action>.wav, numbered so no file is ever replaced."""
        stem = re.sub(r"-(trim|fade_in|fade_out|normalize|reverse|dc|crossfade)(-\d+)?$", "", src.stem)
        for k in itertools.count(1):
            p = self.base_dir / f"{stem}-{action}{'' if k == 1 else f'-{k}'}.wav"
            if not p.exists():
                return p

    def unused(self):
        """What the order list never plays: patterns outside it, instruments no cell of its patterns names, samples that no
        used instrument maps (or, without instruments, no cell names). Memoised per song text."""
        if getattr(self, "_unused", (None,))[0] == self.text:
            return self._unused[1]
        mod, out = self.mod, {"patterns": [], "instruments": [], "samples": []}
        if mod:
            played = {o for o in mod.orders if o < 254}
            cells = {c.instrument for i in played for row in mod.patterns[i].rows for c in row if c.instrument}
            out["patterns"] = [p.name for i, p in enumerate(mod.patterns) if i not in played]
            if mod.instruments is not None:
                used = {n for n in cells if 0 < n <= len(mod.instruments)}
                out["instruments"] = [n for n in (self.song.get("instruments") or {}) if int(n) not in used]
                cells = {smp for n in used for _, smp in mod.instruments[n - 1].keymap if smp}
            out["samples"] = [n for n in (self.song.get("samples") or {}) if int(n) not in cells]
        self._unused = (self.text, out)
        return out

    def save_upload(self, name, data):
        """A WAV dropped on the page (its bytes: the page cannot know the file's path) saved beside the song as <name>.wav,
        numbered so no other file is replaced; an identical copy already there is reused. Returns the path."""
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise ValueError(f"{name}: not a WAV file")
        stem = re.sub(r"[^\w.-]+", "_", Path(name).stem)[:60] or "dropped"
        for k in itertools.count(1):
            p = self.base_dir / f"{stem}{'' if k == 1 else f'-{k}'}.wav"
            if p.exists() and p.read_bytes() == data:
                return p
            if not p.exists():
                p.write_bytes(data)
                try:
                    read_wav(p)
                except (OSError, ValueError):
                    p.unlink()
                    raise
                return p

    # ---- pattern view

    def pattern_rows(self, index):
        """One pattern as read-only tracker rows; each cell in the 'C-5 01 v64 A06' layout libopenmpt prints."""
        pat = self.mod.patterns[index]
        return {"name": pat.name, "index": index, "rows": [[format_cell(c) for c in row] for row in pat.rows]}

    # ---- snapshot for the page

    def _recipe_snapshot(self):
        try:
            rec = self.slot_recipe()
        except OSError:
            rec = None
        if rec:
            rec = dict(rec, recipe_name=Path(rec["recipe"]).name)
        return {"slot": rec, "job": self.recipe_job}

    def snapshot(self):
        with self.lock:
            self._stamps = "|".join(_stamp(f) for f in self.files)  # read once for every key this snapshot takes
            try:
                return self._snapshot()
            finally:
                self._stamps = None

    def _snapshot(self):
        with self.lock:
            slot = self.slot
            entry = (self.song.get("samples") or {}).get(slot, {})
            cur = self.current_file()
            ref = self.measured(cur) if cur and Path(cur).exists() else None
            cands = []
            for i, c in enumerate(self.cands()):
                k = self.key(c)
                r = self.renders.get(k, {"status": "queued", "file": None, "error": None})
                m = self.measured(c) if Path(c).exists() else {"error": "file not found"}
                rating = self.meta["ratings"].get(c, {})
                cands.append({"id": i, "path": c, "name": Path(c).stem, "src": os.path.relpath(c, self.base_dir).replace(os.sep, "/"),
                              "key": k, "status": r["status"], "error": r.get("error"), "peak": r.get("peak"), "meas": m,
                              "dist": distance(m, ref), "stars": rating.get("stars", 0), "rejected": rating.get("rejected", False),
                              "note": rating.get("note", ""), "current": c == cur})
            ents = self.song.get("samples") or {}
            slot_meas = {}  # per slot: the three numbers the overview table shows (memoised per WAV)
            for k, v in ents.items():
                f = (self.base_dir / v["file"]).resolve() if isinstance(v, dict) and v.get("file") else None
                m = self.meas.get(str(f)) if f else None  # filled in by the warm-up thread; blank until then
                if m:
                    slot_meas[str(k)] = {x: m.get(x) for x in ("pitch", "centroid", "decay")}
            ok = self.key()
            own = self.renders.get(ok, {"status": "queued", "error": None})
            voice = []  # the instruments that play this slot through the `sample:` shorthand (a keymap is the song's to edit)
            for n, ins in (self.song.get("instruments") or {}).items():
                if isinstance(ins, dict) and ins.get("sample") is not None and ins.get("sample") in (slot, entry.get("name")):
                    params, custom = voice_of(ins)
                    voice.append({"num": n, "name": ins.get("name", ""), "song": params, "custom": custom,
                                  "edit": (self.mix().get("instrument") or {}).get(str(n), {})})
            return {
                "song": {"path": str(self.song_path), "dir": str(self.base_dir), "dirty": self.dirty(), "error": self.error,
                         "mtime": self.mtime, "facts": self.facts, "sample_entries": {str(k): v for k, v in ents.items()},
                         "slot_meas": slot_meas},
                "slot": slot, "slot_entry": entry, "slot_file": cur, "ref": ref,
                "orders": list(self.orders) if self.orders else None, "loop": self.meta.get("loop"),
                "muted": sorted(set(self.meta.get("muted") or [])), "solo": self.meta.get("solo"),
                "own": {"key": ok, "status": own["status"], "error": own.get("error"), "peak": own.get("peak")},
                "mix": self.mix(), "meters": self.meters, "voice": voice, "spec": {"db": SPEC_DB, "stops": SPEC_STOPS, "nyquist": RATE / 2},
                "voice_range": VOICE_RANGE,
                "candidates": cands, "build": self.build, "stems": self.stems,
                "cand_counts": {k: len(v) for k, v in self.meta["candidates"].items() if v},
                "notes": self.notes, "notes_path": str(self.notes_path), "version": self.version(),
                "undo": len(self.history), "redo": len(self.future), "unused": self.unused(),
                "notices": self.notices,
                "recipe": self._recipe_snapshot(),
                "instruments": {str(k): v for k, v in (self.song.get("instruments") or {}).items()},
                "structure": {"orders": [str(o) for o in self.song.get("orders") or []],
                              "patterns": [{"name": p.name, "rows": len(p.rows), "index": i,
                                            "used": sum(1 for o in self.song.get("orders") or [] if str(o) == p.name)}
                                           for i, p in enumerate(self.mod.patterns)] if self.mod else [],
                              "module": {k: getattr(self.mod, k) for k in self.MODULE_KEYS} if self.mod else {}},
                "archives": sorted(p.name for p in self.base_dir.glob(self.song_path.stem + ".notes-*.md")),
                "queue": sum(1 for r in self.renders.values() if r["status"] in ("queued", "rendering")),
                "cache": sum(1 for r in self.renders.values() if r["status"] == "ready"),
            }


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    state: State = None
    window = None  # pywebview window, when the UI runs in one

    @classmethod
    def open_song(cls, path):
        old, cls.state = cls.state, State(path)
        if old is not None:
            old.close()
        remember_song(cls.state.song_path)

    @classmethod
    def browse(cls, wav=False, module=False):
        """Native file dialog, returning the chosen song (or, with `wav`, WAV; with `module`, module) path or None."""
        kind, pat = ("WAV files", "*.wav") if wav else ("Modules", "*.it;*.xm;*.s3m;*.mod") if module else ("Song files", "*.yaml;*.yml")
        if cls.window is not None:
            import webview
            r = cls.window.create_file_dialog(webview.OPEN_DIALOG, file_types=(f"{kind} ({pat})", "All files (*.*)"))
            return r[0] if r else None
        from tkinter import Tk, filedialog
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        r = filedialog.askopenfilename(parent=root, title="VultureTracker", filetypes=[(kind, pat.replace(";", " ")), ("All files", "*")])
        root.destroy()
        return r or None

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        p = Path(path)
        try:
            f = p.open("rb")
        except OSError:
            return self._send(404, {"error": "not found"})
        with f:
            self._send_range(f, os.fstat(f.fileno()).st_size, ctype)

    def _send_range(self, f, size, ctype):
        """The open file `f`, or the byte range the request names, read and sent in pieces (a render is tens of MB, and
        the page asks for it range by range as it plays and seeks)."""
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        code = 200
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].strip().partition("-")  # one range: the first of a list
            try:
                if a:
                    start, end = int(a), min(int(b), end) if b else end
                elif b:  # the last b bytes
                    start = max(0, size - int(b))
                else:
                    raise ValueError
            except ValueError:
                return self._send(400, {"error": f"bad Range header: {rng}"})
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        f.seek(start)
        left = end - start + 1
        while left > 0:
            piece = f.read(min(left, 1 << 20))
            if not piece:
                break
            self.wfile.write(piece)
            left -= len(piece)

    def _foreign(self):
        """A request from another web page (its Origin is not this server's), or one that reached the server under another
        host name (a DNS-rebinding page): refused, since the POSTs open, create and write files. The page's own requests
        carry this origin; local tools (the tests, scripts) send none."""
        port = self.server.server_address[1]
        if (self.headers.get("Host") or "").rsplit(":", 1)[0] not in ("127.0.0.1", "localhost"):
            return True
        origin = self.headers.get("Origin")
        return origin is not None and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def do_GET(self):
        if self._foreign():
            return self._send(403, {"error": "not this app's page"})
        st = self.state
        path = self.path.split("?")[0]
        if path == "/":
            return self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if path == "/engine-worklet.js":
            return self._send(200, worklet_js(), "text/javascript; charset=utf-8")
        if path == "/web/libopenmpt.wasm":
            return self._send(200, WEB.joinpath("libopenmpt.wasm").read_bytes(), "application/wasm")
        if path == "/icon.png":
            return self._send(200, HTML.with_name("icon.png").read_bytes(), "image/png")
        if path == "/api/state":
            return self._send(200, st.snapshot() if st else start_snapshot())
        if path == "/api/effects":
            return self._send(200, effect_help())
        if path == "/api/start":
            return self._send(200, start_snapshot())
        if st is None:
            return self._send(404, {"error": "no song open"})
        if path.startswith("/api/pattern/"):
            try:
                return self._send(200, st.pattern_rows(int(path[13:])))
            except (ValueError, IndexError, AttributeError):
                return self._send(404, {"error": "no such pattern"})
        if path.startswith("/api/wave/"):
            from urllib.parse import parse_qs
            q = {k: v[0] for k, v in parse_qs(self.path.partition("?")[2]).items()}
            try:
                return self._send(200, st.sample_view(int(path[10:]), q.get("a", 0), q.get("b"), q.get("n", 1000)))
            except (ValueError, OSError, ImportError) as e:
                return self._send(404, {"error": f"{type(e).__name__}: {e}"})
        if path.startswith("/api/sounding/"):
            try:
                return self._send(200, {"rows": st.sounding_rows(int(path[14:]))})
            except (ValueError, IndexError, AttributeError, TypeError):
                return self._send(404, {"error": "no such order"})
        if path.startswith("/wav/"):
            k = path[5:]
            r = st.renders.get(k)
            return self._send_file(r["file"], "audio/wav") if r and r["status"] == "ready" else self._send(404, {"error": "not rendered"})
        if path.startswith("/spec/"):
            r = st.renders.get(path[6:])
            if not r or r["status"] != "ready":
                return self._send(404, {"error": "not rendered"})
            p = Path(r["file"])
            try:
                png = spectrogram_png(str(p), f"{p.stat().st_mtime}:{p.stat().st_size}", "lin" if "scale=lin" in self.path else "log")
            except (OSError, ImportError, wave.Error, ValueError) as e:
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return self._send(200, png, "image/png")
        if path.startswith("/raw/"):
            try:
                c = st.cands()[int(path[5:])]
            except (ValueError, IndexError):
                return self._send(404, {"error": "no such candidate"})
            return self._send_file(c, "audio/wav")
        if path.startswith("/api/diff/") or path == "/api/mixdiff":
            try:
                return self._send(200, st.mix_diff() if path == "/api/mixdiff" else st.diff(st.cands()[int(path[10:])]))
            except (KeyError, ValueError, IndexError, TypeError, AttributeError, OSError) as e:
                return self._send(400, {"error": f"{type(e).__name__}: {e}"})
        if path == "/api/it":
            try:
                return self._send(200, st.live_it(), "application/octet-stream")
            except (SongError, OSError, ValueError) as e:
                return self._send(400, {"error": "\n".join(getattr(e, "errors", []) or [str(e)])})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self._foreign():
            return self._send(403, {"error": "not this app's page"})
        st = self.state
        n = int(self.headers.get("Content-Length") or 0)
        act = self.path.split("?")[0].rsplit("/", 1)[-1]
        if act == "upload":  # raw WAV bytes, ?name=
            from urllib.parse import parse_qs
            try:
                name = parse_qs(self.path.partition("?")[2]).get("name", ["dropped.wav"])[0]
                return self._send(200, {"path": str(st.save_upload(name, self.rfile.read(n)))})
            except (AttributeError, ValueError, OSError) as e:
                return self._send(400, {"error": f"{type(e).__name__}: {e}"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("the request body must be a JSON object")
            if act == "open":
                self.open_song(body["path"])
            elif act == "new":
                self.open_song(create_song(body["path"], body.get("channels") or 8, body.get("sample") or None))
            elif act == "import":  # a module converted beside itself and opened; `browse` picks it in a dialog
                src = self.browse(module=True) if body.get("browse") else body.get("path")
                if not src:
                    return self._send(200, {"path": None})
                out, warnings = import_beside(src)
                self.open_song(out)
                return self._send(200, {"path": str(out), "warnings": warnings})
            elif act == "browsewav":
                return self._send(200, {"path": self.browse(wav=True)})
            elif act == "browse":
                p = self.browse()
                if p:
                    self.open_song(p)
                return self._send(200, {"path": p})
            elif st is None:
                return self._send(404, {"error": "no song open"})
            elif act == "slot":
                st.meta["slot"] = int(body["slot"])
                st.save_meta()
                st.queue_all()
            elif act == "orders":
                st.meta["orders"] = body.get("orders")
                st.save_meta()
                st.queue_all()
            elif act == "loop":
                st.set_loop(body)
            elif act == "mute":
                st.meta["muted"] = sorted({int(i) for i in body.get("muted", [])})
                st.meta["solo"] = None if body.get("solo") is None else int(body["solo"])
                st.save_meta()
                st.queue_all()
            elif act == "add":
                return self._send(200, {"added": st.add_candidates(body["globs"])})
            elif act == "remove":
                st.remove_candidate(st.cands()[int(body["id"])])
            elif act == "rate":
                c = st.cands()[int(body["id"])]
                r = st.meta["ratings"].setdefault(c, {})
                for k in ("stars", "rejected", "note"):
                    if k in body:
                        r[k] = body[k]
                st.save_meta()
            elif act == "want":
                st.set_want(st.cands()[int(body["id"])] if body.get("id") is not None else None)
            elif act == "note":
                return self._send(200, st.add_note(body))
            elif act == "noteedit":
                st.edit_note(int(body["id"]), body)
            elif act == "retry":
                st.retry(st.cands()[int(body["id"])])
            elif act == "apply":
                st.apply(st.cands()[int(body["id"])])
            elif act == "mix":
                st.set_mix(body)
            elif act == "edit":  # one pattern (pattern, cells) or several in one step (patterns: [{pattern, cells}])
                st.edit_patterns([(g["pattern"], g["cells"]) for g in body["patterns"]] if "patterns" in body
                                 else [(body["pattern"], body["cells"])])
            elif act == "songedit":
                return self._send(200, {"ok": True, **(st.song_edit(body["ops"]) or {})})
            elif act in ("undo", "redo"):
                st.undo(redo=act == "redo")
            elif act == "applymix":
                st.apply_mix()
            elif act == "reciperender":
                st.request_recipe_render(body.get("spec"))
            elif act == "recipewrite":
                st.recipe_write(body.get("spec"))
            elif act == "fetchsynth":
                st.request_fetch_synth(body.get("kind"))
            elif act == "reload":
                st.reload()
            elif act == "build":
                st.request_build(bool(body.get("render")))
            elif act == "stems":
                st.request_stems(body.get("fmt", "wav"), body.get("song", False), body.get("stems", True))
            else:
                return self._send(404, {"error": "unknown action"})
        except (KeyError, ValueError, IndexError, TypeError, AttributeError, OSError, SongError) as e:
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})  # a bad request is answered, never dropped
        self._send(200, {"ok": True})


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False  # on Windows SO_REUSEADDR would let a second app take a port the first still listens on

    def handle_error(self, request, client_address):
        """A page that went away mid-answer (closed, reloaded, a seek that cancelled a request) is no error to print."""
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


def make_server(port=0):
    """The HTTP server on `port`; 0 means PORT when it is free (a second app window gets any free port)."""
    if not port:
        try:
            return _Server(("127.0.0.1", PORT), Handler)
        except OSError:
            pass
    return _Server(("127.0.0.1", port), Handler)


def serve(song_path=None, port=0, open_browser=True, window=True):
    """Serve the UI. With pywebview installed (and `window`), it opens in a native window; else the default
    browser. `song_path` may be None: the UI then starts on its open-a-song screen."""
    if song_path:
        Handler.open_song(song_path)
    srv = make_server(port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if window:
        try:
            import webview
        except ImportError:
            webview = None
        if webview:
            Handler.window = webview.create_window("VultureTracker", url, width=1400, height=900, min_size=(1000, 600), background_color="#0a0c0d")
            webview.start(private_mode=False, storage_path=str(PROFILE))
            return 0
    print(f"VultureTracker GUI: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0
