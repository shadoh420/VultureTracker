"""`vulturetracker gui song.yaml`: a one-page tryout app served on localhost from the stdlib HTTP server.

The page (gui.html) polls /api/state and posts actions; renders run on one worker thread and land as WAVs in
`<song dir>/.tryout/`. The tryout section is compiled once per candidate (memoised); mutes, solo and the mixer's
faders (channel volume and pan, mix volume, sample gain) are patched into that module's header before each render, so
re-picking a candidate is instant and a fader move costs one render. The instrument panel (the slot's instrument: volume
envelope, filter and its sweep, random volume) joins the unwritten mix and is applied when the section is compiled.
Ratings, notes, the candidate list, mutes and the unwritten mix live in `<song>.tryout.json` beside the song.
Listening notes (a tag dropped at the playhead, the channels sounding there, the listener's words) live in
`<song>.notes.json` and are rendered as `<song>.notes.md`, a report for a collaborator who cannot listen."""
import copy
import datetime
import difflib
import functools
import glob
import hashlib
import importlib
import itertools
import json
import logging
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import wave
import webbrowser
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import yaml

from . import __version__, agent, api, plugins
from .fileio import atomic_write as _atomic, lock_file, protect_outputs, save_beside, unlock_file, user_dir, wav_bytes
from .notation import format_cell, format_note
from .itwriter import write_it
from .history import SIDE_SCHEMA, History, digest, json_bytes, newer, pack_step, unpack_step, HISTORY_BYTES
from .project import collect, file_updates, replace_values, resolve_meta, relative_meta
from .arrangement import section_renamed, sections_text, occurrence_map, reorder
from .openmpt import LoadedModule, OpenMPTError, library_version
from .song import SongError, it_text, load_song_text
from .wavload import SOUND_FILES, read_wav, to_wav

HTML = Path(__file__).with_name("gui.html")
WEB = HTML.with_name("web")  # the live engine: libopenmpt 0.8.9 compiled to WebAssembly (official build) and its AudioWorklet
RATE = 44100
# the checkout (for the demo list); a frozen exe: its own folder when samples/ is there (the release zip), else one
# level up (dist/ in a checkout)
ROOT = ((lambda d: d if (d / "samples").is_dir() else d.parent)(Path(sys.executable).resolve().parent)
        if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent)
RECENT = user_dir() / "recent.json"
REC_SETTINGS = RECENT.with_name("record.json")  # the RECORD tab's ASIO choice, read before sounddevice loads
# the page is served from one address every launch when it can be, and the window keeps a WebView2 profile beside the
# recent list, so what the browser stores per address stays: the page's settings (localStorage) and the MIDI permission
PORT = 8723
# render workers: the tryout's renders (the song, each candidate), meters, builds and stems share one queue by priority.
# VT_WORKERS=3 renders three at once: measured in the cloud (4 cores, tools/bench.py --tryout 6) 15-20 % sooner for the
# song and six candidates, byte-identical, but an edit made meanwhile reached the live engine 2-4x later (the workers
# hold the GIL between libopenmpt's calls), so one worker stays the default
WORKERS = max(1, int(os.environ.get("VT_WORKERS") or 1))
PROFILE = RECENT.parent / "webview"
LOCKS = RECENT.parent / "open"  # one locked file per song open in an app (app_lock_path)
OLD_RECENT = RECENT.parent.with_name("TrackerForge") / "recent.json"  # the app's previous name
HOME_RECENT = Path.home() / "VultureTracker" / "recent.json"  # where Linux and macOS kept it before 1.0
LOG = RECENT.parent / "vulturetracker.log"
_log = logging.getLogger("vulturetracker")  # without start_log (the command line, the tests) errors go to stderr
LOGGING = False


def start_log():
    """The app's log, for the exe (a windowed program has no console): unexpected errors with their tracebacks, after a
    line naming this version, libopenmpt's and the system. At most two files of 256 KB (vulturetracker.log and .log.1)."""
    global LOGGING
    import logging.handlers
    import platform
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(LOG, maxBytes=256 * 1024, backupCount=1, encoding="utf-8")
    except OSError:
        return
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _log.addHandler(h)
    if sys.stderr:  # run from a console: there too
        _log.addHandler(logging.StreamHandler())
    _log.setLevel(logging.INFO)
    _log.info("VultureTracker %s started: libopenmpt %s, Python %s, %s", __version__, library_version(),
              platform.python_version(), platform.platform())
    sys.excepthook = lambda *exc: _log.error("Unexpected error", exc_info=exc)
    threading.excepthook = lambda a: a.exc_type is SystemExit or _log.error(
        "Unexpected error in %s", a.thread.name if a.thread else "a thread", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    LOGGING = True


def logged(error):
    """An error for the page, naming the log when the app keeps one."""
    return f"{error} (details in {LOG})" if LOGGING else error


def _atomic_text(path, text):
    """Text written as write_text writes it (the platform's line endings), through _atomic."""
    _atomic(path, text.replace("\n", os.linesep).encode("utf-8"))


def _read_json(path, default, notices, move=True):
    """A JSON file the app keeps beside the song, or `default` when there is none. One that does not parse (a write cut
    short before writes were atomic, or a hand edit) is moved aside to `<name>.corrupt` (unless not `move`: another app
    has the song open) and `default` is used, with a notice for the page, so the song still opens."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        if not move:
            notices.append(f"{path.name} could not be read ({e}); left as it is")
            return default
        bad = path.with_name(path.name + ".corrupt")
        os.replace(path, bad)
        notices.append(f"{path.name} could not be read ({e}); it was moved to {bad.name} and the app started it afresh")
        return default


def recent_songs():
    for f in (RECENT, OLD_RECENT, HOME_RECENT):
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
        for k in itertools.count(1):
            wav = path.with_name(path.stem + ('_tone' if k == 1 else f'_tone-{k}') + '.wav')
            try:
                with wav.open('xb'):
                    pass
                break
            except FileExistsError:
                continue
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
    _atomic(path, (f"# {title}: a song made in VultureTracker (the format: SONG_FORMAT.md)\nmodule:\n  title: {q(title)}\n"
                      f"  tempo: 125\n  speed: 6\n  global_volume: 128\n  mix_volume: 48\n  sample_rate: 44100\n  channels:\n{chans}"
                      f"samples:\n  1: {{file: {q(rel)}, name: {q(name)}}}\ninstruments:\n  1: {{name: {q(name)}, sample: 1}}\n"
                      f"patterns:\n  p00:\n    rows: 64\n    data: |\norders: [p00]\n").encode("utf-8"), replace=False)
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
    """A module (.it, .xm, .s3m, .mod), a Guitar Pro tab (.gp3, .gp4, .gp5: gpimport) or a MIDI file (.mid, .midi:
    midiimport; both with placeholder sounds) imported as
    <stem>.yaml beside it with its samples in <stem>_samples/ (numbered <stem>-2 and so on when either exists: nothing
    is replaced). Returns (song path, warnings)."""
    from .itreader import import_it
    src = Path(src).resolve()
    if not src.is_file():
        raise ValueError(f"no such file: {src}")
    for k in itertools.count(1):
        stem = src.stem + ("" if k == 1 else f"-{k}")
        out, sdir = src.with_name(stem + ".yaml"), src.with_name(stem + "_samples")
        if not out.exists() and not sdir.exists():
            break
    if src.suffix.lower() in GP_SUFFIXES:
        from .gpimport import import_gp
        return out, import_gp(src, out, sdir)[1]
    if src.suffix.lower() in MIDI_SUFFIXES:
        from .midiimport import import_midi
        return out, import_midi(src, out, sdir)[1]
    return out, import_it(src, out, sdir)[1]


GP_SUFFIXES = (".gp3", ".gp4", ".gp5")
MIDI_SUFFIXES = (".mid", ".midi")


def start_snapshot():
    return {"song": None, "recent": recent_songs(), "demos": demo_songs(), "version": __version__}


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


DMO = plugins.describe()  # the rack's effects and their parameters


def _key_report(mod):
    try:
        from .compose import key_report
        return key_report(mod)
    except (ImportError, ValueError):
        return None
CHAT = agent.Chat()       # the chat panel's conversation (one per app)


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
        "title": mod.title, "tempo": mod.tempo, "speed": mod.speed, "bpm": round(mod.tempo * 24 / mod.speed / (mod.row_highlight[0] or 4), 2),
        "highlight": [mod.row_highlight[0] or 4, rows_per_bar],
        "channels": [c.name or f"Ch {i + 1}" for i, c in enumerate(mod.channels)],
        "pan": [c.pan for c in mod.channels], "volume": [c.volume for c in mod.channels], "mix_volume": mod.mix_volume,
        "channel_plugins": [c.plugin for c in mod.channels], "plugins": plugins.to_song(mod.plugins),
        "macros": {f"SF{n:X}": t for n, t in sorted(mod.macros.items())},
        "key": mod.key, "key_report": _key_report(mod),
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
                last_ins[ch] = c.instrument or last_ins[ch]
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
    """Each channel soloed (every other channel disabled so volume commands cannot unmute it): RMS in dB over the whole render and over its active half-seconds, plus those seconds. Needs numpy.
    `cancel()` true between channels abandons the pass (returns None)."""
    import numpy as np
    out = []
    for ch in range(nch):
        if cancel is not None and cancel():
            return None
        d = patch_it(data, [other for other in range(nch) if other != ch])
        with LoadedModule(d) as lm:
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
    return _spectrogram_of(*_wav_mono(path), scale, cols, rows, n)


def _wav_mono(path):
    """A 16-bit WAV as (mono float32 array, rate)."""
    import numpy as np
    with wave.open(str(path), "rb") as w:
        rate, nch = w.getframerate(), w.getnchannels()
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32).reshape(-1, nch).mean(axis=1) / 32768, rate


def _spectrogram_of(x, rate, scale="log", cols=1200, rows=256, n=4096):
    """spectrogram() of a mono float array."""
    import numpy as np
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
    col_of = np.minimum(np.arange(frames, dtype=np.int64) * hop * cols // max(length, 1), cols - 1)  # numpy 1 on Windows: int32 overflows past ~40 s
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
    db, _ = spectrogram(path, scale)
    return _colour_png((db - SPEC_DB[0]) / (SPEC_DB[1] - SPEC_DB[0]), SPEC_STOPS)


def _colour_png(v, stops):
    """A PNG of `v` (rows x cols, 0..1, row 0 the lowest band, drawn at the bottom) through the colour `stops`."""
    import numpy as np
    v = np.clip(v[::-1], 0, 1)
    stops, pos = np.array(stops, float), np.linspace(0, 1, len(stops))
    return png_rgb(np.stack([np.interp(v, pos, stops[:, k]) for k in range(3)], axis=-1).astype(np.uint8))


# the reference: another recording (any sound file ffmpeg reads) set under the render that plays, for the SPECTRUM tab's
# REF and DELTA views. The offset is how much later the song starts than the reference, in ms: reference time = song
# time - offset. DELTA is the song's level minus the reference's in each cell, the reference's overall level matched to
# the song's first; red = louder in the song, blue = quieter
DELTA_DB = 30
DELTA_STOPS = [[30, 80, 200], [120, 160, 225], [235, 235, 235], [230, 130, 110], [205, 35, 35]]
DELTA_RANGE = 80  # cells more than this many dB under the loudest of both count as silence in both


def reference_wav(src, folder):
    """`src` decoded by ffmpeg to 16-bit stereo at RATE in `folder` (a WAV too: another depth or rate would not line up
    with the render), decoded again when the source changes."""
    src = Path(src).resolve()
    st = src.stat()
    out = Path(folder) / f"reference-{hashlib.sha1(f'{src}|{st.st_mtime}|{st.st_size}'.encode()).hexdigest()[:12]}.wav"
    if not out.exists():
        tmp = out.with_name(out.stem + ".part.wav")
        r = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-map", "0:a:0", "-ac", "2", "-ar", str(RATE),
                            "-c:a", "pcm_s16le", str(tmp)], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"{src.name}: ffmpeg could not read it ({r.stderr.decode(errors='replace').strip()[-300:]})")
        os.replace(tmp, out)
    return out


def _cut(y, length, start):
    """`length` samples of `y` from sample `start`; silence where that runs outside it."""
    import numpy as np
    out = np.zeros(length, np.float32)
    a, b = max(0, start), min(len(y), start + length)
    if b > a:
        out[a - start:b - start] = y[a:b]
    return out


@functools.lru_cache(maxsize=4)
def reference_compare(render, rstamp, ref, fstamp, offset_ms, start, scale="log"):
    """The render (a section `start` seconds into the song) against the reference cut to the same span: (song dB,
    reference dB, delta dB, mean |delta| per column (None where both are silent), the gain put on the reference in dB,
    the share of the render the reference covers). The stamps key the cache on the files' mtime and size."""
    import numpy as np
    x, rate = _wav_mono(render)
    y, _ = _wav_mono(ref)
    at = int(round((start - offset_ms / 1000) * rate))
    a = max(0, -at)
    b = max(a, min(len(x), len(y) - at))  # the part of the render the reference covers
    y = _cut(y, len(x), at)
    rx, ry = (float(np.sqrt(np.mean(v[a:b] ** 2))) if b > a else 0.0 for v in (x, y))
    gain = rx / ry if rx > 0 and ry > 0 else 1.0
    s, _ = _spectrogram_of(x, rate, scale)
    r, _ = _spectrogram_of(y * gain, rate, scale)
    floor = max(SPEC_DB[0], max(s.max(), r.max()) - DELTA_RANGE)
    s, r = np.maximum(s, floor), np.maximum(r, floor)
    d = s - r
    live = (s > floor) | (r > floor)
    n = live.sum(axis=0)
    cols = [round(float(v), 1) if k else None for v, k in zip(np.abs(d * live).sum(axis=0) / np.maximum(n, 1), n)]
    return s, r, np.where(live, d, np.nan), cols, round(20 * math.log10(gain), 1), round((b - a) / max(1, len(x)), 3)


def reference_align(render, ref, offset_ms, start, reach=30.0):
    """The offset (ms) that lines the reference up with the render: the onset strength (dsp.novelty) of both,
    cross-correlated (by FFT, to the hop: 6 ms) within `reach` seconds of the current offset. Returns (offset_ms,
    correlation 0-1). Music repeats, so a beat or a bar away can score nearly as well: check by ear, nudge OFFSET."""
    import numpy as np
    from .dsp import novelty
    x, rate = _wav_mono(render)
    y, _ = _wav_mono(ref)
    pad = int(reach * rate)
    at = int(round((start - offset_ms / 1000) * rate)) - pad  # the reference from `reach` before where the render sits now
    fx, hop = novelty(x, rate)
    fy, _ = novelty(_cut(y, len(x) + 2 * pad, at), rate)
    fx, fy = fx - fx.mean(), fy - fy.mean()
    size = 1 << int(np.ceil(np.log2(len(fy) + len(fx))))
    c = np.fft.irfft(np.fft.rfft(fy, size) * np.conj(np.fft.rfft(fx, size)), size)[: len(fy) - len(fx) + 1]
    k = int(np.argmax(c))
    seg = fy[k:k + len(fx)]
    corr = float(seg @ fx) / (float(np.linalg.norm(seg) * np.linalg.norm(fx)) or 1.0)
    return round((start - (at + k * hop) / rate) * 1000), round(max(0.0, corr), 2)


def worklet_js():
    """/engine-worklet.js: the libopenmpt glue (a classic script) wrapped as loadGlue(), then the engine core and the
    processor, as one module for audioWorklet.addModule (a worklet cannot load scripts itself)."""
    glue = (WEB / "libopenmpt.js").read_text(encoding="utf-8")
    return ("const loadGlue = function (libopenmpt, require, __dirname) {\n" + glue + "\nreturn Module;\n};\n"
            + (WEB / "engine-core.js").read_text(encoding="utf-8") + (WEB / "engine-worklet.js").read_text(encoding="utf-8")).encode("utf-8")


def _wav_bytes(y, rate):
    """Float channels x frames (full scale 1.0) as the bytes of a 16-bit WAV file."""
    import io
    import numpy as np
    pcm = np.clip(np.round(np.asarray(y).T * 32767), -32768, 32767).astype("<i2")
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())
    return b.getvalue()


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
        raise OSError("MP3/OGG/FLAC export, and FLAC, AIFF, OGG and MP3 samples, need ffmpeg: ffmpeg.exe beside "
                      "vulturetracker.exe, pip install imageio-ffmpeg, or ffmpeg on PATH")
    return exe


def _encode(path, pcm, fmt, loop=None):
    """Interleaved int16 stereo PCM at RATE to `fmt` (a key of ENCODE) through ffmpeg (no console window on Windows);
    `loop` = (start, end_exclusive) frames as the LOOPSTART and LOOPLENGTH tags game engines read from OGG and FLAC."""
    tags = ["-metadata", f"LOOPSTART={loop[0]}", "-metadata", f"LOOPLENGTH={loop[1] - loop[0]}"] if loop else []
    r = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(RATE), "-ac", "2", "-i", "-",
                        *ENCODE[fmt], *tags, str(path)], input=pcm, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode:
        raise OSError(f"ffmpeg failed: {r.stderr.decode(errors='replace').strip()[-400:]}")


@functools.lru_cache(maxsize=32)
def _mix_numbers(path, stamp):
    import numpy as np
    from . import dsp
    pcm = np.frombuffer(Path(path).read_bytes()[44:], "<i2").reshape(-1, 2).T.astype(np.float32) / 32768
    return dsp.measure_mix(pcm, RATE)


def mix_numbers(path):
    """A render's loudness (LUFS), true peak, sample peak and stereo correlation (dsp.measure_mix), memoised per file
    stamp; None when it cannot be read."""
    try:
        st = os.stat(path)
        return _mix_numbers(str(path), (st.st_mtime_ns, st.st_size))
    except (OSError, ValueError, ImportError):
        return None


def _peak(pcm):
    """Peak of interleaved int16 PCM, 0..1 (1.0: libopenmpt's mixer clipped)."""
    try:
        import numpy as np
        return round(float(np.abs(np.frombuffer(pcm, "<i2").astype(np.int32)).max()) / 32768, 3)
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
    (`from_wav` read from the WAV's smpl chunk, its end clamped to the audio as the compiler plays it)."""
    out, n = {}, len(w.channels[0])
    for k in ("loop", "sustain_loop"):
        spec = entry.get(k)
        if spec == "from_wav":
            s, e, pp = w.loops[0] if w.loops else (0, 0, False)
            out[k] = (s, min(e, n), pp) if min(e, n) > s else None
        elif isinstance(spec, dict):
            out[k] = (int(spec.get("start", 0)), int(spec.get("end", n)), spec.get("type") == "pingpong")
        else:
            out[k] = None
    return out


SAMPLE_ACTIONS = ("trim", "fade_in", "fade_out", "normalize", "reverse", "dc", "crossfade", "gain", "lowpass", "highpass",
                  "eq", "loudness", "pitch", "stretch", "truncate", "denoise", "spectral_mask")


def _splice(x, a, b, seg, loops):
    """`x` with frames a..b replaced by `seg` (another length): loops before the span stay, loops after it move with the
    audio, a loop inside it is scaled with it, one across its edge is dropped."""
    import numpy as np
    k = seg.shape[1] / max(1, b - a)
    out = {}
    for key, lp in loops.items():
        if not lp:
            out[key] = lp
        elif lp[1] <= a:
            out[key] = lp
        elif lp[0] >= b:
            d = seg.shape[1] - (b - a)
            out[key] = (lp[0] + d, lp[1] + d, lp[2])
        elif a <= lp[0] and lp[1] <= b:
            s, e = a + round((lp[0] - a) * k), a + round((lp[1] - a) * k)
            out[key] = (s, max(s + 1, e), lp[2])
        else:
            out[key] = None
    return np.concatenate([x[:, :a], seg.astype(x.dtype), x[:, b:]], axis=1), out


def process_wav(x, action, a, b, loops, frames=0, params=None, rate=44100):
    """One sample edit on frames a..b of `x` (float channels x frames; a copy is changed). `loops` ({key: (start, end,
    pingpong) or None}) follow the audio: trimmed (shifted, clipped, dropped when nothing is left) and mirrored by a
    reverse of the whole sample. The effects (dsp.py; `params` their settings, `rate` the WAV's) work on the span too:
    gain (db), lowpass / highpass (hz, slope 12 or 24), eq (hz, db, q), loudness (db: the RMS target), pitch
    (semitones, the length kept), stretch (percent, the pitch kept), denoise (the noise learned from frames na..nb of
    `x`, turned down by up to db, sens its threshold over the noise) and truncate (silences under db dBFS longer than
    min_ms shortened to keep_ms); the last two change the length, and the loops move with the audio. Crossfade: the last `frames` of the loop fade (equal power) into the audio just before
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
    elif action in ("gain", "lowpass", "highpass", "eq", "loudness", "pitch", "denoise", "spectral_mask"):
        from . import dsp
        q = params or {}

        def num(k, lo, hi, default=None):
            try:
                v = float(q.get(k, default))
            except (TypeError, ValueError):
                raise ValueError(f"{action}: {k} must be a number")
            if not lo <= v <= hi:
                raise ValueError(f"{action}: {k} is {lo:g} to {hi:g}")
            return v
        nyq = rate / 2
        if action == "gain":
            y = dsp.gain(seg, num("db", -60, 24))
        elif action == "lowpass":
            y = dsp.lowpass(seg, rate, num("hz", 20, nyq), num("slope", 12, 24, 24))
        elif action == "highpass":
            y = dsp.highpass(seg, rate, num("hz", 10, nyq), num("slope", 12, 24, 24))
        elif action == "eq":
            y = dsp.peak_eq(seg, rate, num("hz", 20, nyq * 0.98), num("db", -24, 24), num("q", 0.1, 20, 1))
        elif action == "loudness":
            y = dsp.loudness(seg, num("db", -60, 0, -18))[0]
        elif action == "spectral_mask":  # the PAINT tab's picture laid over the span's spectrum (spectral.py)
            from . import spectral
            pic = paint_args(q)
            y = spectral.spectral_mask(seg, rate, pic["amp"], pic["fmin"], pic["fmax"], pic["scale"], pic["range_db"])
        elif action == "denoise":
            na, nb = int(num("na", 0, n)), int(num("nb", 0, n))
            if nb - na < 2048:
                raise ValueError("denoise: LEARN NOISE from a selection where only the noise sounds (at least 50 ms)")
            y = dsp.denoise(seg, rate, x[:, na:nb], num("db", 0, 60, 12), num("sens", 1, 8, 2))
        else:
            y = dsp.pitch_shift(seg, num("semitones", -24, 24))
        x[:, a:b] = y
    elif action in ("stretch", "truncate"):
        from . import dsp
        q = params or {}
        if action == "stretch":
            pct = float(q.get("percent", 100))
            if not 25 <= pct <= 400:
                raise ValueError("stretch: 25 to 400 %")
            new = dsp.stretch(seg, pct / 100)
        else:
            runs = dsp.silent_runs(seg, rate, float(q.get("db", -50)), float(q.get("min_ms", 200)))
            keep = max(0, int(float(q.get("keep_ms", 50)) * rate / 1000))
            if not runs:
                raise ValueError("truncate: no silence that long and that quiet in the span")
            parts, at = [], 0
            for s, e in runs:
                parts.append(seg[:, at: s + keep // 2])
                at = max(s + keep // 2, e - (keep - keep // 2))
            parts.append(seg[:, at:])
            new = np.concatenate(parts, axis=1)
            loops = {k: (lp if lp and (lp[1] <= a or lp[0] >= b) else None) for k, lp in loops.items()}
        x, loops = _splice(x, a, b, new, loops)
    else:
        raise ValueError(f"unknown sample edit '{action}' (one of {', '.join(SAMPLE_ACTIONS)})")
    if x.shape[1] == 0:
        raise ValueError("the edit leaves no audio")
    return x, loops


def paint_args(body):
    """The PAINT tab's picture and its settings from a request, checked: {amp, pan (rows x columns arrays), seconds, fmin,
    fmax, scale, range_db}."""
    import numpy as np
    try:
        amp = np.asarray(body["amp"], float)
        pan = np.asarray(body.get("pan") if body.get("pan") is not None else np.zeros_like(amp), float)
    except (KeyError, TypeError, ValueError):
        raise ValueError("paint: the picture is rows x columns of brightness 0-1 (amp) and pan -1..1 (pan)")
    if amp.ndim != 2 or pan.shape != amp.shape or not (1 <= amp.shape[0] <= 256 and 1 <= amp.shape[1] <= 1024):
        raise ValueError("paint: a picture is 1-256 rows by 1-1024 columns, with a pan of the same shape")
    scale = body.get("scale") or "log"
    if scale not in ("log", "notes"):
        raise ValueError("paint: the rows are spread in log frequency (log) or one per semitone (notes)")
    fmin, fmax = float(body.get("fmin", 40)), float(body.get("fmax", 12000))
    if scale == "notes" and not (0 <= fmin < 120):
        raise ValueError("paint: the lowest note is C-0 (0) to B-9 (119)")
    if scale == "log" and not (10 <= fmin < fmax <= 20000):
        raise ValueError("paint: the range is 10 Hz to 20 kHz, low to high")
    seconds, range_db = float(body.get("seconds", 2)), float(body.get("range_db", 48))
    if not 0.01 <= seconds <= 60 or not 6 <= range_db <= 96:
        raise ValueError("paint: 0.01-60 seconds, a 6-96 dB range")
    return {"amp": np.clip(amp, 0, 1), "pan": np.clip(pan, -1, 1), "seconds": seconds, "fmin": fmin, "fmax": fmax,
            "scale": scale, "range_db": range_db}


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

def app_lock_path(song_path):
    """The file the app holds locked while a song is open in it: beside the recent-songs list, not in the song's folder
    (Windows would refuse to rename or move a folder holding an open file)."""
    key = os.path.normcase(str(Path(song_path).resolve()))
    return LOCKS / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".lock")


def open_in_app(song_path):
    """Whether a running app has the song open: it keeps the song's history and tryout settings in memory and writes
    them over a change made beside it (a checkpoint saved from the command line would vanish)."""
    p = app_lock_path(song_path)
    if not p.exists():
        return False
    f = lock_file(p)
    if f is None:
        return True
    unlock_file(f)
    return False


LOCK_WAITS = (0.1, 0.2, 0.4, 0.8, 1.5)  # seconds an app opening a song waits for a command that is changing it
_HELD = {}  # app_lock_path -> [the locked file, how many of this process's States have the song open]
_HELD_GUARD = threading.Lock()


def take_app_lock(song_path):
    """Lock the song for this process while a State has it open (the same song opened again shares the lock), waiting
    LOCK_WAITS for a command that holds it; False when another app or a command holds it all that time."""
    p = app_lock_path(song_path)
    for wait in (*LOCK_WAITS, None):
        with _HELD_GUARD:
            if p in _HELD:
                _HELD[p][1] += 1
                return True
            LOCKS.mkdir(parents=True, exist_ok=True)
            f = lock_file(p)
            if f:
                _HELD[p] = [f, 1]
                return True
        if wait is None:
            return False
        time.sleep(wait)


def release_app_lock(song_path):
    p = app_lock_path(song_path)
    with _HELD_GUARD:
        held = _HELD.get(p)
        if held and held[1] > 1:
            held[1] -= 1
        elif held:
            del _HELD[p]
            unlock_file(held[0])
            try:
                p.unlink()
            except OSError:  # another app or a command took it this moment: it stays, unlocked
                pass


class State:
    READ_ONLY = ("{name} is open in another VultureTracker window or being changed by a command-line tool, so it opened "
                 "read-only: it plays, but edits, checkpoints and tryout settings are not saved. Close the other (or let "
                 "the command finish), then open the song again to edit it.")
    NEWER = ("{names} beside {name} {were} written by a newer VultureTracker, so the song opened read-only: it plays, but "
             "nothing is saved, so that version's files are not written over. Open the song in that version, or update "
             "this one (https://github.com/shadoh420/VultureTracker/releases).")

    def __init__(self, song_path, headless=False, passive=False):
        """`headless` (the command line): no workers, no .tryout cache, no lock, notes left where they are. `passive`:
        another process has the song open; the files beside it are read as they are (an interrupted save's journal and a
        file that does not parse are its to reconcile). An app that cannot take the song's lock opens it read-only."""
        self.song_path = Path(song_path).resolve()
        self._app_lock = not headless and take_app_lock(self.song_path)  # the command line's tools see the song is open here
        self.read_only = None if headless or self._app_lock else self.READ_ONLY.format(name=self.song_path.name)
        try:
            self._open(headless, passive or bool(self.read_only))
        except BaseException:
            self.release_lock()
            raise

    def _open(self, headless, passive):
        self.base_dir = self.song_path.parent
        self.headless = headless
        self.cache_dir = self.base_dir / ".tryout"
        self.meta_path = self.song_path.with_name(self.song_path.stem + ".tryout.json")
        self.meta = {"slot": 1, "orders": None, "candidates": {}, "ratings": {}, "muted": [], "solo": None, "mix": {}}
        self.closed = False
        self.notices = []     # what the page should tell once: a meta or notes file that could not be read
        if self.read_only:
            self.notices.append(self.read_only)
        self.history_store = History(self.song_path, self.notices, passive)
        self.checkpoints = {}
        self._history_ready = False
        self._asset_hashes = {}
        meta = _read_json(self.meta_path, {}, self.notices, move=not passive)
        self.notes_path = self.song_path.with_name(self.song_path.stem + ".notes.json")
        notes = _read_json(self.notes_path, [], self.notices, move=not passive)
        saved = self.history_store.load()
        late = [p.name for p, v in ((self.meta_path, meta), (self.notes_path, notes)) if newer(v)]
        late += [self.history_store.path.name] if self.history_store.newer else []
        if late:  # read nothing from them, write nothing over them
            self.read_only = self.NEWER.format(names=" and ".join(late), name=self.song_path.name, were="were" if len(late) > 1 else "was")
            self.notices.append(self.read_only)
            meta = notes = saved = None
        self.meta.update(resolve_meta(meta, self.base_dir) if isinstance(meta, dict) else {})
        notes = notes.get("notes") if isinstance(notes, dict) else notes  # a list: notes from before 1.0
        self.notes = notes if isinstance(notes, list) else []
        self.lock = threading.RLock()
        self.jobs = queue.PriorityQueue()  # (priority, sequence, job): what is playing first, then the song, the rest, meters last
        self._seq = itertools.count()
        self.want = self.meta.get("selected_candidate")  # the candidate the page is listening to (None: the song itself), rendered first
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
        self.takes = []       # this session's recorded takes, newest first (save_take)
        self.selection = None  # the page's pattern selection or cursor: {order, pattern, rows [a, b], channels [a, b]}
        self.cue = None        # an agent's request to show (and play) a place: {id, order, row, channel, play}
        self.agent_log = []    # the agent tools' calls (agent.run): what an agent did, for the page
        self.agent_measures = {}  # the last measure per scope, for the next one's change
        self.build = None     # last build/export result
        self.export_job = None
        self.export_result = None
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
        self.it_stamps = None
        self.it = None        # its .it bytes: the whole song as it is, which the live engine plays unless the panel edits it
        self.reload(archive=not headless)
        if saved:
            self.checkpoints = saved['checkpoints']
            if saved['head'] == digest(self._raw):
                self.history, self.future = saved['undo'], saved['redo']
            else:
                self.notices.append('External edits since the last session: undo/redo start fresh; named checkpoints remain available for comparison.')
        self._history_ready = True
        if headless:
            return
        self.cache_dir.mkdir(exist_ok=True)
        for _ in range(WORKERS):
            threading.Thread(target=self._worker, daemon=True).start()

    # ---- song

    def reload(self, archive=True, loaded=None):
        """Re-read the song. `archive`: notes made against another version of the song text move to their archive
        (the song changed outside the app: a rebuild); the app's own writes pass False, so a slot write mid-session
        keeps the notes. `loaded`: the (module, warnings) of this very text, already compiled by the caller."""
        with self.lock:
            raw = self.song_path.read_bytes()
            if archive and self.text and raw != self._raw:
                self.history.clear()
                self.future.clear()
                self.notices.append('External reload: undo and redo start a new history boundary.')
            self._raw = raw
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
            for sec in ("module", "samples", "instruments", "patterns"):  # the compiler reports one that is not a map
                if sec in self.song and not isinstance(self.song[sec], dict):
                    self.song[sec] = {}
            for sec in ("samples", "instruments"):  # a quoted key ('08', '8') reads as a string here; the compiler reads 8
                if isinstance(self.song.get(sec), dict):
                    self.song[sec] = {int(k) if isinstance(k, str) and k.isdigit() else k: v for k, v in self.song[sec].items()}
            files = self.files = [str((self.base_dir / v["file"]).resolve()) for v in (self.song.get("samples") or {}).values()
                     if isinstance(v, dict) and v.get("file")]
            self.it_stamps = "|".join(_stamp(f) for f in files)  # the WAVs self.it was compiled from
            threading.Thread(target=lambda: [self.measured(f) for f in files if Path(f).exists()], daemon=True).start()
            if self.meta["slot"] not in (self.song.get("samples") or {}):
                self.meta["slot"] = min(self.song.get("samples") or {1: 0})
            if archive and not self.read_only:
                self._archive_old_notes()
                if self._history_ready:
                    _atomic(self.history_store.path, self.history_store.data(self._raw, self.history, self.future, self.checkpoints))
            if self.notes and not self.headless and not self.read_only:
                try:
                    self.save_notes()
                except OSError as e:
                    self.notices.append(f'Song loaded; listening-note report could not be refreshed: {e}')
            self.queue_all()

    def dirty(self):
        try:
            return self.song_path.read_bytes() != self._raw
        except OSError:
            return True

    def save_meta(self):
        if self.read_only:  # the settings stay in this window (the notice says so)
            return
        _atomic_text(self.meta_path, json.dumps(relative_meta(self.meta, self.base_dir), indent=1))

    def _writable(self):
        if self.read_only:
            raise ValueError(self.read_only)

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
            self.meta["selected_candidate"] = cand
            self.save_meta()
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

    def cand(self, i):
        """Candidate `i` of the slot's list; a ValueError outside it (a negative index would pick from the end)."""
        i = int(i)
        if not 0 <= i < len(self.cands()):
            raise ValueError(f"no candidate {i}")
        return self.cands()[i]

    def pattern_at(self, index):
        """Pattern index `index` of the compiled module, checked (a negative one would pick from the end)."""
        i = int(index)
        if self.mod is None or not 0 <= i < len(self.mod.patterns):
            raise ValueError(f"no pattern {i}")
        return i

    @staticmethod
    def _chan(items, i):
        """Channel index `i` of the song's channel lines, checked (a negative one would pick from the end)."""
        i = int(i)
        if not 0 <= i < len(items):
            raise ValueError(f"no channel {i + 1}")
        return i

    # ---- the reference recording (SPECTRUM tab)

    def section_start(self):
        """Where the rendered section starts in the song, in seconds (the order times of the facts)."""
        f, o = self.facts, self.orders
        return f["orders"][o[0]]["start"] if f and o and o[0] < len(f["orders"]) else 0.0

    def set_reference(self, path, body):
        """The reference: `path` sets it (decoded once to check that ffmpeg reads it; the offset is kept), `offset` (ms)
        moves it, `align` with the render `key` that plays sets the offset that lines it up, `clear` drops it."""
        ref = dict(self.meta.get("reference") or {})
        if body.get("clear"):
            ref = None
        if path:
            src = (self.base_dir / Path(path).expanduser()).resolve()
            if not src.is_file():
                raise ValueError(f"no such file: {src}")
            reference_wav(src, self.cache_dir)
            ref = {"file": str(src), "offset_ms": ref.get("offset_ms", 0) if ref else 0}
        if ref and body.get("offset") is not None:
            ref["offset_ms"] = round(float(body["offset"]))
        out = {}
        if ref and body.get("align"):
            r = self.renders.get(body.get("key") or "")
            if not r or r["status"] != "ready":
                raise ValueError("ALIGN needs a render that is playing: wait for it to finish")
            ref["offset_ms"], out["corr"] = reference_align(r["file"], reference_wav(ref["file"], self.cache_dir), ref["offset_ms"],
                                                            self.section_start())
        with self.lock:
            self.meta["reference"] = ref
            self.save_meta()
        return {"reference": ref, **out}

    def reference_compare(self, key, scale="log"):
        """reference_compare() for the render `key` against the reference; ValueError when either is missing."""
        r, ref = self.renders.get(key), self.meta.get("reference")
        if not ref:
            raise ValueError("no reference set")
        if not r or r["status"] != "ready":
            raise ValueError("not rendered")
        stamp = lambda f: f"{Path(f).stat().st_mtime}:{Path(f).stat().st_size}"  # noqa: E731
        w = reference_wav(ref["file"], self.cache_dir)
        return reference_compare(r["file"], stamp(r["file"]), str(w), stamp(w), ref["offset_ms"], self.section_start(), scale)

    def reference_png(self, key, view, scale="log"):
        s, r, d, *_ = self.reference_compare(key, scale)
        if view == "delta":
            import numpy as np
            n = len(DELTA_STOPS)  # the colour stops below the scale's bottom: black, for cells silent in both
            v = (np.clip((d + DELTA_DB) / (2 * DELTA_DB), 0, 1) * (n - 1) + 1) / n
            return _colour_png(np.nan_to_num(v, nan=0.0), [[0, 0, 0]] + DELTA_STOPS)
        return _colour_png((r - SPEC_DB[0]) / (SPEC_DB[1] - SPEC_DB[0]), SPEC_STOPS)

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
            if any(not 0 <= int(i) < 64 for i in d):
                raise ValueError("a channel is 0-63")
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
        return hashlib.sha1(f"{api.RENDER_VERSION}|{self.text_sha()}|{self.slot}|{self.orders}|{stamps}|{inst}".encode()).hexdigest()[:16]

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
            files = sorted(f for f in glob.glob(pat, recursive=True) if Path(f).suffix.lower() in (".wav", *SOUND_FILES)) or [pat]
            for f in files:
                f = str(self.as_wav(Path(f).resolve())[0])
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
            if whole and not cand and self.it and self.it_stamps == (self._stamps or "|".join(_stamp(f) for f in self.files)) and not any(int(n) in (self.song.get("instruments") or {}) for n in inst):
                return self.it  # the song as reload compiled it: the same bytes as compiling it again from the dict
        ck = self.ckey(cand) + ("|whole" if whole else "")
        if ck not in self.compiled:
            with self.lock:
                span = None
                if not whole and self.orders and self.facts:
                    a, b = self.orders
                    playable = self.facts['orders']
                    if not 0 <= a < b <= len(playable):
                        raise ValueError('Selected order range is no longer valid')
                    span = (playable[a]['order'], playable[b-1]['order']+1)
                base, slot = api.tryout_song(self.song, span), self.slot
                inst = self.mix().get("instrument") or {}
            for n, edit in inst.items():
                if int(n) in (base.get("instruments") or {}):
                    base["instruments"][int(n)] = voice_entry(base["instruments"][int(n)], edit)
            if cand:
                api.swap_sample(base, slot, Path(cand).resolve())
            it = api.compile_song(base, self.base_dir)[0]
            with self.lock:  # several workers: the memo changes under the lock only
                while len(self.compiled) >= 8:
                    self.compiled.pop(next(iter(self.compiled)))
                self.compiled[ck] = it
            return it
        return self.compiled.get(ck) or self.compiled_it(cand, whole)

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
        self.release_lock()
        for _ in range(WORKERS):
            self._put(-1, ("close",))

    def release_lock(self):
        """Give the song's lock back (another song replaced this one, or it failed to open)."""
        if self._app_lock:
            self._app_lock = False
            release_app_lock(self.song_path)

    def _worker(self):
        while not self.closed:
            job = self.jobs.get()[2]
            if job[0] == "close":
                return
            if job[0] in ("export", "build", "meters", "recipe", "fetch"):
                try:
                    if job[0] == 'export':
                        from .export import run
                        run(job[1], _encode)
                    elif job[0] == "build":
                        self._build(job[1])
                    elif job[0] == "meters":
                        self._meters(job[1])
                    elif job[0] == "recipe":
                        self._recipe_render(*job[1])
                    else:
                        self._fetch_synth(job[1])
                except Exception as e:  # noqa: BLE001 - what a job's own handler did not expect: it fails alone, the worker goes on
                    self._job_failed(job, f"{type(e).__name__}: {e}")
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
                if cand is None or cand == self.want:
                    mix_numbers(out)  # measured now, so the page's next poll does not wait for it
                self._prune()
            except Exception as e:  # noqa: BLE001 - shown in the UI, worker must survive
                with self.lock:
                    self.renders[k].update(status="failed", error=f"{type(e).__name__}: {e}")

    def _job_failed(self, job, error):
        """The job ends in its own failed state with the message, as the page shows it."""
        _log.exception("A %s job failed", job[0])
        error = logged(error)
        with self.lock:
            if job[0] == "export":
                job[1]["result"].update(status="failed", error=error)
            elif job[0] == "build":
                self.build = {"status": "failed", "error": error}
            elif job[0] == "meters" and self.meters:
                self.meters.update(status="failed", error=error)
            elif job[0] in ("recipe", "fetch") and self.recipe_job:
                self.recipe_job.update(status="failed", error=error)

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
                except (RecipeError, yaml.YAMLError, RecursionError, OSError, UnicodeDecodeError, ValueError, TypeError, KeyError, AttributeError):
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
                            self._recipe_memo[key] = api.safe_dump(recipe_entry(rec, name)[0], default_flow_style=False,
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
            spec = api.from_yaml(text or "")  # numbers as the recipe file reads them (0100 is a hundred)
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
        if kind not in FETCH and kind != "faust":
            raise ValueError(f"no download for '{kind}'")
        with self.lock:
            self.recipe_job = {"status": "fetching", "error": None, "log": [], "file": None, "need": kind, "got": 0, "size": 0}
        self._put(0, ("fetch", kind))

    def _fetch_synth(self, kind):
        """Download a synth the recipe panel's last render missed, then render that entry again."""
        from .synth import fetch_synth
        if kind == "faust":
            from .faust import fetch as fetch_synth  # noqa: F811 - faustwasm, from npm
        try:
            fetch_synth(*([] if kind == "faust" else [kind]), lambda got, size: self.recipe_job.update(got=got, size=size))
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
        self._writable()
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
        self._writable()
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
        if self.read_only:  # another window's notes, or a newer app's file: not written over (add_note says so)
            return
        _atomic_text(self.notes_path, json.dumps({"schema": SIDE_SCHEMA, "notes": self.notes}, indent=1))
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
            if newer(kept):  # a newer app's archive is left as it is; these notes stay in the active file
                old = [n for n in old if n not in batch]
                continue
            kept = kept.get("notes", []) if isinstance(kept, dict) else kept if isinstance(kept, list) else []
            seen = {(n["id"], n.get("when")) for n in kept}
            kept += [n for n in batch if (n["id"], n.get("when")) not in seen]
            _atomic_text(p, json.dumps({"schema": SIDE_SCHEMA, "notes": kept}, indent=1))
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
             f"`{self.song_path.name}` version {v['hash']} ({v['mtime']}), {len(notes)} note{'s' if len(notes) != 1 else ''}; "
             f"VultureTracker {__version__}.",
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
                stars = r.get("stars") if type(r.get("stars")) is int else 0  # a hand-edited .tryout.json: no stars
                if stars or r.get("rejected") or r.get("note"):
                    rated.append(f"- slot {slot}: {Path(c).stem} " + ("rejected" if r.get("rejected") else "*" * stars)
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
            lines[i] = f"{indent}{key}{sp}{api.safe_dump(entry, default_flow_style=True, width=10 ** 6, sort_keys=False).strip()}{tail}{nl}"
            return 1
        j = State._span(lines, i)
        block = [f"{indent}  {b}\n" for b in api.safe_dump(entry, default_flow_style=False, width=10 ** 6, sort_keys=False).splitlines()]
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
            meta = copy.deepcopy(self.meta)
            meta['candidates'].pop(str(self.slot), None)
            meta['selected_candidate'] = None
            self._commit(new, loaded, meta=meta)
            if self.want == cand:
                self.want = None
        self._put(0, ("build", False))

    def apply_mix(self):
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the write does not overwrite that change")
            new, _ = self.mix_text()
            loaded = load_song_text(new, self.base_dir, str(self.song_path))
            self._commit(new, loaded, meta=dict(self.meta, mix={}))
        self._put(0, ("build", False))

    # ---- build / export

    def request_export(self, options, target='export_result'):
        from .export import prepare
        with self.lock:
            if self.export_job and self.export_job['result']['status'] in ('queued', 'rendering', 'publishing'):
                raise ValueError('An export is active; wait or cancel it first')
            job = prepare(self, options)
            self.export_job = job
            self.export_result = job['result']
            setattr(self, target, job['result'])
            self._put(0, ('export', job))

    def cancel_export(self):
        if self.export_job:
            self.export_job['cancel'].set()

    def request_build(self, render):
        # The legacy buttons now use the same immutable snapshot and safe publication as the export panel.
        try:
            self.request_export({'fmt': 'wav' if render else 'it', 'include_it': render, 'replace': True}, 'build')
        except (SongError, OSError, ValueError) as e:
            self.build = {'status': 'failed', 'error': str(e)}

    def _build(self, render):
        from .export import prepare, run
        try:
            job = prepare(self, {'fmt': 'wav' if render else 'it', 'include_it': render, 'replace': True})
            self.build = run(job, _encode)
        except (SongError, OSError, ValueError) as e:
            self.build = {'status': 'failed', 'error': str(e)}

    def request_stems(self, fmt='wav', song=False, stems=True):
        try:
            self.request_export({'fmt': fmt, 'song': song, 'stems': stems, 'replace': True}, 'stems')
        except (SongError, OSError, ValueError) as e:
            self.stems = {'status': 'failed', 'error': str(e), 'dir': None}

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

    def edit_patterns(self, groups, who=None):
        """Write each (pattern index, cells) of `groups` in place, all as one undoable step. The whole song is compiled
        first: an edit that breaks it is refused (SongError) and nothing is written. Refused too when the song changed on
        disk since it was read (reload first). `who` "agent": the patterns are marked `by: agent` (one that had notes
        and no mark becomes `you and agent`); the owner's edit of a pattern marked `agent` makes it `you and agent`."""
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the edit does not overwrite that change")
            self._need_compiled()
            lines = self.text.splitlines(keepends=True)
            for index, cells in groups:
                self._edit_block(lines, int(index), cells)
            for index in {int(i) for i, _ in groups}:
                pat = self.mod.patterns[index]
                cur = self.pattern_entry(pat.name).get("by")
                if who == "agent":
                    blank = all(c.is_empty() for row in pat.rows for c in row)
                    new = "agent" if cur == "agent" or (cur is None and blank) else "you and agent"
                else:
                    new = "you and agent" if cur == "agent" else cur
                if new != cur:
                    try:
                        self._pattern_mark(lines, pat.name, {"by": new})
                    except ValueError:  # a pattern written as one block carries no marks
                        pass
            self._commit("".join(lines))  # compiled first (SongError: nothing is written)

    def pattern_entry(self, name):
        """The song file's entry of pattern `name` as a dict ({} when it is written as one block)."""
        pats = self.song.get("patterns") or {}
        e = next((v for k, v in pats.items() if str(k) == str(name)), None)
        return e if isinstance(e, dict) else {}

    def _pattern_mark(self, lines, name, fields):
        """Pattern `name`'s marks (`by`, `approved`) set in `lines`; a value of None or False removes the key."""
        j = self._pattern_key(lines, name)
        if lines[j].split("#")[0].split(":", 1)[1].strip():
            raise ValueError(f"pattern '{name}' is written as one block: give it 'rows:' and 'data: |' to mark it")
        kids = self._children(lines, j)
        ind = " " * (self._ind(lines[kids[0][0]]) if kids else self._ind(lines[j]) + 2)
        for key, value in fields.items():
            at = next((i for i, k in self._children(lines, j) if k == key), None)
            if value is None or value is False:
                if at is not None:
                    del lines[at]
                continue
            text = "true" if value is True else self._yname(str(value))
            if at is not None:
                lines[at] = f"{ind}{key}: {text}\n"
            else:
                lines.insert(j + 1, f"{ind}{key}: {text}\n")

    def materialize_pattern(self, index):
        """Make the compiled cells explicit; one undo restores the original pattern notation."""
        with self.lock:
            self._need_compiled()
            pat = self.mod.patterns[self.pattern_at(index)]
            lines = self.text.splitlines(keepends=True)
            data = ''.join(f"{r:02d}: {' | '.join(format_cell(c) for c in row)}\n"
                           for r, row in enumerate(pat.rows))
            entry = {'rows': len(pat.rows), 'data': data}
            top = self._top(lines, 'patterns')
            if lines[top].split(':', 1)[1].strip().startswith('{'):
                key = next(k for k in self.song['patterns'] if str(k) == pat.name)  # `1:` is the int 1, compiled as '1'
                patterns = dict(self.song['patterns'])
                patterns[key] = entry
                lines[top:self._span(lines, top)] = api.to_yaml({'patterns': patterns}).splitlines(keepends=True)
            else:
                at = self._pattern_key(lines, pat.name)
                indent = ' ' * self._ind(lines[at])
                block = api.to_yaml({pat.name: entry})
                lines[at:self._span(lines, at)] = [indent + line + '\n' for line in block.splitlines()]
            self._commit(''.join(lines))

    def _need_compiled(self):
        if self.mod is None or self.error:
            raise ValueError("the song does not compile (RENDER & EXPORT lists the errors): fix it in the YAML first")

    def _edit_block(self, lines, index, cells, nch=None, pat=None):
        """`cells` written into pattern `index`'s rows in `lines` (in place). `nch`: the channel count when an edit of the
        same step added channels."""
        pat = pat or self.mod.patterns[self.pattern_at(index)]
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

    MODULE_KEYS = {"title": None, "key": None, "tempo": (32, 255), "speed": (1, 255), "global_volume": (0, 128), "mix_volume": (0, 128),
                   "separation": (0, 128), "rows_per_beat": (1, 255), "rows_per_bar": (1, 255)}

    def _encoded(self, text, crlf=None, bom=None):
        crlf = self.crlf if crlf is None else crlf
        bom = self.bom if bom is None else bom
        return (b'\xef\xbb\xbf' if bom else b'') + text.replace('\n', '\r\n' if crlf else '\n').encode('utf-8')

    def _asset_paths(self, text, meta=None):
        paths = set()
        try:
            doc = api.from_yaml(text)
        except yaml.YAMLError:  # a song that is no valid YAML (a checkpoint brings back one that is): no files to name
            doc = None
        doc = doc if isinstance(doc, dict) else {}
        for entry in (doc.get('samples') or {}).values():
            if not isinstance(entry, dict) or not entry.get('file'):
                continue
            paths.add((self.base_dir / str(entry['file'])).resolve())
        meta = meta or {}
        for entries in (meta.get('candidates') or {}).values():
            paths.update((self.base_dir / p).resolve() for p in entries)
        if meta.get('selected_candidate'):
            paths.add((self.base_dir / meta['selected_candidate']).resolve())
        paths.update((self.base_dir / p).resolve() for p in (meta.get('phrase') or {}).get('assets', {}))
        return paths

    def _assets(self, text, meta=None):
        assets = {}
        for path in self._asset_paths(text, meta):
            if not path.is_file():
                assets[str(path)] = None  # relinking is allowed; restoring an originally missing asset is refused
                continue
            stat = path.stat()
            key = (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
            if key not in self._asset_hashes:
                self._asset_hashes[key] = digest(path.read_bytes())
            assets[str(path)] = self._asset_hashes[key]
        return assets

    def _step(self, meta=None):
        return pack_step({'text': self.text, 'meta': copy.deepcopy(meta), 'assets': self._assets(self.text, meta),
                          'crlf': self.crlf, 'bom': self.bom, 'version': self.version()})

    def _check_assets(self, step):
        step = unpack_step(step)
        if 'text' in step:
            required = {str(p) for p in self._asset_paths(step['text'], step.get('meta'))}
            if not required.issubset(step.get('assets', {})):
                raise ValueError('Cannot restore: history is missing source asset fingerprints; compare the checkpoint text instead.')
        for path, expected in step.get('assets', {}).items():
            asset = self.base_dir / path
            if expected is None or not asset.is_file() or digest(asset.read_bytes()) != expected:
                raise ValueError(f'Cannot restore: source asset changed or is missing: {path}. Relink or restore the original asset first.')

    def _write_step(self, new, meta, history, future):
        self._writable()
        if self.dirty():
            raise ValueError('the song changed on disk: compare and RELOAD first')
        raw = self._encoded(new)
        saved, history, future = self.history_store.bounded(raw, history, future, self.checkpoints)
        self.history_store.write(raw, relative_meta(meta, self.base_dir), saved, lambda: self.write_song(new), self._raw)
        return history, future

    def checkpoint(self, name, action='save'):
        with self.lock:
            name = str(name).strip()
            if not name or len(name) > 80:
                raise ValueError('Give the checkpoint a name of 1-80 characters')
            if action != 'diff':
                self._writable()
            if self.dirty():
                raise ValueError('Compare and RELOAD external edits first')
            if action in ('diff', 'restore', 'delete') and name not in self.checkpoints:
                raise ValueError(f'No checkpoint named {name}')
            if action == 'diff':
                return self._diff(unpack_step(self.checkpoints[name])['text'], False)
            if action == 'restore':
                step = unpack_step(self.checkpoints[name])
                self._check_assets(step)
                self._commit(step['text'], meta=dict(self.meta, **(step.get('meta') or {})))
                return {}
            checkpoints = copy.deepcopy(self.checkpoints)
            if action == 'delete':
                del checkpoints[name]
            elif action == 'save':
                if name in checkpoints:
                    raise ValueError('A checkpoint with that name exists; choose another name')
                if len(checkpoints) >= 32:
                    raise ValueError('At most 32 checkpoints; delete one before saving another')
                checkpoints[name] = self._step(self._meta_view())
            else:
                raise ValueError('unknown checkpoint action')
            try:
                data, history, future = self.history_store.bounded(self._raw, self.history, self.future, checkpoints)
            except ValueError:
                if action != 'delete':
                    raise
                # Legacy checkpoints may together exceed the new budget. Let each deletion reduce them.
                data = self.history_store.data(self._raw, self.history, self.future, checkpoints)
                history, future = self.history, self.future
            _atomic(self.history_store.path, data)
            self.history, self.future, self.checkpoints = history, future, checkpoints
            return {}

    def trim_history(self, keep=0):
        with self.lock:
            self._writable()
            if self.dirty():
                raise ValueError('Compare and RELOAD external edits first')
            if not str(keep).strip():  # an emptied field is no 0: CLEAR UNDO / REDO is the way to drop every step
                raise ValueError('Type how many recent undo steps to keep (0-200)')
            keep = int(keep)
            if not 0 <= keep <= self.UNDO_LIMIT:
                raise ValueError('Keep between 0 and 200 undo steps')
            history = self.history[-keep:] if keep else []
            data, history, future = self.history_store.bounded(self._raw, history, [], self.checkpoints)
            _atomic(self.history_store.path, data)
            self.history, self.future = history, future

    def relink(self, num=None, path=None, links=None):
        with self.lock:
            moved = {}
            for num, path in (links if links is not None else {num: path}).items():
                num = int(num)
                entry = (self.song.get('samples') or {}).get(num)
                if not isinstance(entry, dict) or not entry.get('file'):
                    raise ValueError('Select a sample with a file to relink')
                path = (self.base_dir / str(path)).resolve()
                read_wav(path)
                try:
                    rel = Path(os.path.relpath(path, self.base_dir)).as_posix()
                except ValueError:
                    rel = path.as_posix()
                moved[num] = rel
            if not moved:
                raise ValueError('Provide replacement paths for the missing samples')
            self._commit(replace_values(self.text, file_updates(self.song, moved)))

    def external_diff(self):
        raw = self.song_path.read_bytes()
        text = raw.decode('utf-8-sig').replace('\r\n', '\n')
        return dict(self._diff(text, False), token=digest(raw))

    def _commit(self, new, loaded=None, meta=None):
        """Compile, write, then publish one undo step. A failed write consumes no history or settings; an edit that
        changes nothing (channel 1 moved up) adds no step and keeps the redo steps."""
        meta = copy.deepcopy(self.meta if meta is None else meta)
        if new == self.text and meta == self.meta:
            return
        loaded = loaded or load_song_text(new, self.base_dir, str(self.song_path))
        changed = {k: copy.deepcopy(self.meta.get(k)) for k in self.META_KEYS if self.meta.get(k) != meta.get(k)}
        back = self._step(changed or None)
        history = (self.history + [back])[-self.UNDO_LIMIT:]
        self.history, self.future = self._write_step(new, meta, history, [])
        self.meta = meta
        self.want = meta.get("selected_candidate")
        self.reload(archive=False, loaded=loaded)

    META_KEYS = ("candidates", "muted", "solo", "mix", "orders", "loop", "phrase", "selected_candidate")  # the tryout settings a song write may change
    UNDO_LIMIT = 200     # undo steps kept (the oldest go first)

    def _meta_view(self):
        import copy
        return copy.deepcopy({k: self.meta.get(k) for k in self.META_KEYS})

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
                    cells = [p.strip() for p in parts]
                    cells += ['... .. ... ...'] * (len(self.mod.channels) - len(cells))
                    lines[i] = self._rejoin(head, parts, fn(cells), tail)

    def _channel_lines(self, lines):
        mod = self._top(lines, "module")
        for j, k in self._children(lines, mod):
            if k == "channels":
                if lines[j].split("#")[0].split(":", 1)[1].strip():
                    raise ValueError("module.channels is written on one line: write one '- {name: ...}' per channel to edit channels here")
                items = [i for i in range(j + 1, self._span(lines, j)) if lines[i].lstrip().startswith("-")]
                if any(not (entry := self._entry(lines[i], '-')) or not entry.group(4) for i in items):
                    raise ValueError("Use one-line '- {name: ..., pan: ..., volume: ...}' channel entries before editing channels here")
                return j, items
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
            i, name = self._chan(items, op["ch"]), str(op["name"]).strip()[:20]
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
            i = self._chan(items, op["ch"])
            if len(items) < 2:
                raise ValueError("a song needs a channel")
            self._map_rows(lines, lambda c: c[:i] + c[i + 1:])
            head, items = self._channel_lines(lines)
            del lines[items[i]]
            remap.append(lambda k: None if k == i else k - 1 if k > i else k)
        elif kind == "channel_move":
            head, items = self._channel_lines(lines)
            a, b = self._chan(items, op["ch"]), int(op["to"])
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
        elif kind == "render_sample":
            self._render_sample(lines, orders, op, remap)
        elif kind == "sample_slice":
            self._slice(lines, orders, op, remap)
        elif kind == "sample_file":  # the slot pointed at another WAV (dropped on it), as the tryout's apply does it
            import copy
            num, f = int(op["num"]), Path(str(op["file"]))
            f = (f if f.is_absolute() else self.base_dir / f).resolve()
            if not f.exists():
                raise ValueError(f"no such WAV: {f}")
            f = self._wav_for_op(f)
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
            y, loops = process_wav(x, str(op["action"]), a, b, entry_loops(entry, w), op.get("frames") or 0,
                                   op.get("params"), w.rate)
            full = 128 if w.out_bits == 8 else 32768
            peak = float(np.abs(y).max()) if y.size else 0.0
            if peak > 1:  # STRETCH, PITCH or a boost past full scale: scaled under it, never clipped
                y = y / peak
                self._report.append(f"{20 * math.log10(peak):.1f} dB down to stay under full scale")
            chans = np.clip(np.round(y * full), -full, full - 1).astype(np.int32).tolist()
            out = self._new_wav(path, str(op["action"]))
            self._created.append(out)  # before the write: a write that fails halfway is removed too
            write_wav(out, w.rate, chans, bits=w.out_bits, loop=loops.get("loop") or loops.get("sustain_loop"), root_note=w.root)
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
                f = self._wav_for_op(f)
                try:
                    rel = os.path.relpath(f.resolve(), self.base_dir).replace(os.sep, "/")
                except ValueError:
                    rel = f.resolve().as_posix()
                entry = {"file": rel, "name": it_text(op.get("name") or f.stem, 25), **({"stereo": True} if op.get("stereo") else {}),
                         **(op.get("keep") or {})}  # keep: settings carried over (a slice keeps its source's pitch)
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
                flow = api.safe_dump(entry, default_flow_style=True, width=10 ** 6, sort_keys=False).strip()
                lines.insert(at, f"{ind}{num}: {flow}\n")
        elif kind == "instrument_delete":
            num = int(op["num"])
            j = next((j for j, k in self._children(lines, self._top(lines, "instruments")) if k == str(num)), None)
            if j is None:
                raise ValueError(f"no instrument {num}")
            del lines[j:self._span(lines, j)]
        elif kind == "plugins":  # module.plugins {number: entry} and/or module.macros {SFx: text}, each rewritten
            #                        whole (empty or null removes it): the rack's edits
            mod = self._top(lines, "module")
            if lines[mod].split("#")[0].split(":", 1)[1].strip():
                raise ValueError("module is written on one line: write it as a block to edit its plugins here")
            for key in ("plugins", "macros"):
                if key not in op:
                    continue
                value = op[key] or {}
                if key == "plugins":
                    value = {int(k): v for k, v in sorted(value.items(), key=lambda kv: int(kv[0]))}
                kids = self._children(lines, mod)
                ind = " " * (self._ind(lines[kids[0][0]]) if kids else 2)
                block = [f"{ind}{key}:\n"] + [
                    f"{ind}  {k}: " + (api.safe_dump(v, default_flow_style=True, width=10 ** 6, sort_keys=False).strip()
                                      if isinstance(v, dict) else self._yname(str(v))) + "\n" for k, v in value.items()]
                at = next((i for i, k in kids if k == key), None)
                if at is not None:
                    lines[at:self._span(lines, at)] = block if value else []
                elif value:
                    end = self._span(lines, mod)
                    lines[end:end] = block
        elif kind == "mark":  # `approved` (true/false) on a pattern, channel or sample (`what`, `key`); `by` on a pattern
            what, key = op.get("what"), op.get("key")
            if what == "pattern":
                self._pattern_mark(lines, str(key), {k: op[k] for k in ("approved", "by") if k in op})
            elif what == "channel":
                head, items = self._channel_lines(lines)
                i = self._chan(items, key)
                if op.get("approved"):
                    self._redump(lines, items[i], self._entry(lines[items[i]], "-"), {"approved": "true"}, keys=("approved",))
                else:
                    lines[items[i]] = re.sub(r",\s*approved:\s*\w+|approved:\s*\w+\s*,?\s*", "", lines[items[i]], count=1)
            elif what == "sample":
                entry = dict((self.song.get("samples") or {}).get(int(key)) or {})
                if not entry:
                    raise ValueError(f"no sample {key}")
                if op.get("approved"):
                    entry["approved"] = True
                else:
                    entry.pop("approved", None)
                self._song_op(lines, orders, {"op": "sample_set", "num": int(key), "entry": entry}, remap)
            else:
                raise ValueError("a mark goes on a pattern, a channel or a sample")
        elif kind == "channel_plugin":  # the plugin a channel plays through (0: none)
            head, items = self._channel_lines(lines)
            i, num = self._chan(items, op["ch"]), int(op.get("plugin") or 0)
            m = self._entry(lines[items[i]], "-")
            if num:
                self._redump(lines, items[i], m, {"plugin": num}, keys=("plugin",))
            else:
                lines[items[i]] = re.sub(r",\s*plugin:\s*\d+|plugin:\s*\d+\s*,?\s*", "", lines[items[i]], count=1)
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

        def carry(c, vol, ins):  # the source channel's volume and instrument after cell c
            if c.instrument:
                ins, dv = c.instrument, default_volume(c.instrument, c.note)
                vol = dv if dv is not None else vol
            if c.volcmd is not None and c.volcmd <= 64:
                vol = c.volcmd
            return vol, ins

        # a pattern starts with the volume and instrument the channel has where it first plays (orders in turn, as the
        # sounding list reads them): a note there without an instrument plays the one carried over
        entry, vol, last_ins = {}, 64, 0
        for o in mod.orders:
            if o < len(mod.patterns):
                entry.setdefault(o, (vol, last_ins))
                for row in mod.patterns[o].rows:
                    vol, last_ins = carry(row[src], vol, last_ins)
        written = past = skipped = lost = 0
        idxs = [self.pattern_at(op["pattern"])] if op.get("pattern") is not None else range(len(mod.patterns))
        for idx in idxs:
            pat = mod.patterns[idx]
            n = len(pat.rows)
            r0 = max(0, int(op.get("r0") or 0)) if op.get("pattern") is not None else 0
            r1 = min(n - 1, int(op["r1"])) if op.get("pattern") is not None and op.get("r1") is not None else n - 1
            (vol, last_ins), cells = entry.get(idx, (64, 0)), []
            for r in range(0, r1 + 1):  # rows before r0 only set the channel's volume and instrument
                c = pat.rows[r][src]
                vol, last_ins = carry(c, vol, last_ins)
                if r < r0 or c.is_empty():
                    continue
                note_on = c.note is not None and c.note < 120
                e = Cell(c.note, last_ins if note_on else c.instrument, None, 0, 0)
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

    def render_rows(self, order, r0, r1, chans=None, tail=2.0):
        """Rows r0..r1 of the pattern at module order `order` rendered as they play in the song (everything before them
        sets the state: tempo, volumes, instruments), with the unwritten mix and the instrument panel, `chans` alone
        audible (None: the channels the mixer lets through), then `tail` seconds of the notes ringing on with nothing
        new struck; the ring-out ends at the first silence. Returns (int16 stereo PCM bytes, seconds of the rows)."""
        import numpy as np
        self._need_compiled()
        mod = self.mod
        if not (0 <= order < len(mod.orders) and mod.orders[order] < len(mod.patterns)):
            raise ValueError(f"order {order} plays no pattern")
        pat = mod.patterns[mod.orders[order]]
        r1 = min(int(r1), len(pat.rows) - 1)
        r0 = max(0, min(int(r0), r1))
        tail = max(0.0, min(10.0, float(tail)))
        nch = len(mod.channels)
        silenced = [c for c in range(nch) if c not in set(chans)] if chans is not None else self.silenced()
        if len(silenced) >= nch:
            raise ValueError("no channel to render: every one is muted or left out")
        with self.lock:
            base = api.tryout_song(self.song, (0, order + 1))  # the orders up to this one, jumps kept inside them
            inst, mix = self.mix().get("instrument") or {}, self.mix()
        for n, edit in inst.items():
            if int(n) in (base.get("instruments") or {}):
                base["instruments"][int(n)] = voice_entry(base["instruments"][int(n)], edit)
        names = set(base["patterns"])
        rn = next(n for n in (f"render{k}" for k in itertools.count()) if n not in names)
        base["patterns"][rn] = {"rows": r1 + 1, "data": "\n".join(" | ".join(format_cell(c) for c in row)
                                                                  for row in pat.rows[:r1 + 1]) + "\n"}
        base["patterns"][rn + "_tail"] = {"rows": 200, "data": ""}  # 200 rows last 2 s at the fastest speed and tempo
        base["orders"] = list(base["orders"][:order]) + [rn] + [rn + "_tail"] * (1 + int(tail / 1.9))
        it = patch_it(api.compile_song(base, self.base_dir)[0], silenced, mix)
        with LoadedModule(it) as lm:
            end = lm.order_start(order + 1)
            start = lm.order_start(order, r0)  # the render starts here: libopenmpt plays the song up to it to get its state
            pcm = lm.render(RATE, max_seconds=end - start + tail)
        x = np.frombuffer(pcm, "<i2").reshape(-1, 2)
        rows_end = min(len(x), round((end - start) * RATE))
        loud = np.nonzero(np.abs(x[rows_end:].astype(np.int32)).max(axis=1) > 2)[0]  # the ring-out stops at its last frame above 2 LSB (int32: abs(-32768))
        return x[: rows_end + (loud[-1] + 1 if len(loud) else 0)].tobytes(), end - start

    def _render_sample(self, lines, orders, op, remap):
        """The `render_sample` op: render_rows of op's order, r0, r1, chans and tail, written as a WAV beside the song
        (stereo when the channels differ) and added as a new sample slot; part of the song edit's one undo step."""
        import numpy as np
        from .wavload import write_wav
        order, r0, r1 = int(op["order"]), int(op.get("r0") or 0), int(op.get("r1") if op.get("r1") is not None else 199)
        pcm, secs = self.render_rows(order, r0, r1, op.get("chans"), op.get("tail", 2.0))
        x = np.frombuffer(pcm, "<i2").reshape(-1, 2)
        if not x.any():
            raise ValueError("the render is silent: nothing plays on those rows and channels")
        stereo = bool((x[:, 0] != x[:, 1]).any())
        name = self.mod.patterns[self.mod.orders[order]].name
        stem = re.sub(r"[^\w.-]+", "_", f"{self.song_path.stem}-{name}-{r0}-{r1}")
        out = next(p for p in (self.base_dir / f"render-{stem}{'' if k == 1 else f'-{k}'}.wav" for k in itertools.count(1))
                   if not p.exists())
        self._created.append(out)
        write_wav(out, RATE, [x[:, c].tolist() for c in range(2 if stereo else 1)])
        num = max((int(k) for k in (self.song.get("samples") or {})), default=0) + 1
        self._song_op(lines, orders, {"op": "sample_new", "num": num, "file": str(out), "stereo": stereo,
                                      "name": f"{name} {r0}-{r1}"[:25]}, remap)
        self._report.append(f"rows {r0}-{min(r1, len(self.mod.patterns[self.mod.orders[order]].rows) - 1)} of "
                            f"'{name}' ({secs:.2f} s, {len(x) / RATE:.2f} s with the ring-out) rendered into new slot "
                            f"{num:02d}: {out.name}")

    def _slice(self, lines, orders, op, remap):
        """The `sample_slice` op: slot `num`'s WAV cut at `points` (start frames, ascending) up to `end` (default: the
        WAV's end), each slice written as its own WAV beside the song (a 1 ms fade at its end, so the cut does not click)
        and added as a new slot. `mode` kit (default): each slot keeps the source slot's pitch settings and, in a song
        with instruments, a new instrument plays slice 1 on C-5, slice 2 on C#5 and so on, each at its own pitch (a drum
        kit). `mode` multi: each slice's note is found (dsp.pitch_of; slices without one are left out), its slot tuned
        to the cent (c5_speed) and a new instrument plays each slice over the keys nearest its note (compose.key_splits),
        so a set of recorded notes becomes one playable instrument. `pattern`: also a new pattern (not in the order list)
        whose cells play the slices in order at their original timing at the song's tempo and speed (compose.slice_rows:
        rows plus SDx delays), from channel `ch`. One undo step."""
        import numpy as np
        from . import compose, dsp
        from .notation import format_note
        from .wavload import write_wav
        num, mode = int(op["num"]), op.get("mode") or "kit"
        if mode not in ("kit", "multi"):
            raise ValueError("slices become a kit (one per key from C-5) or a multisample (each around its note)")
        entry, path, w, x = self._sample_wav(num)
        n = x.shape[1]
        end = max(1, min(n, int(op.get("end") or n)))
        pts = sorted({int(p) for p in op.get("points") or [] if 0 <= int(p) < end})
        bounds = [(s, e) for s, e in zip(pts, pts[1:] + [end]) if e - s >= 32]
        have = sorted(int(k) for k in (self.song.get("samples") or {}))
        first = max(have, default=0) + 1
        insts = self.mod.instruments is not None
        if len(bounds) < 1:
            raise ValueError("no slices: give at least one start point before the end")
        if mode == "multi" and not insts:
            raise ValueError("a multisample is an instrument: this song plays samples directly (no instruments)")
        notes = [None] * len(bounds)
        if mode == "multi":
            for k, (s, e) in enumerate(bounds):
                hz = dsp.pitch_of(x[:, s:e], w.rate)
                if hz:
                    notes[k] = (hz, dsp.note_of(hz)[0])
            keep_k = [k for k, v in enumerate(notes) if v and 0 <= v[1] < 120]
            if not keep_k:
                raise ValueError("no slice holds a note to map (drums? slice them as a kit)")
        else:
            keep_k = list(range(len(bounds)))
        if first + len(keep_k) - 1 > 99:
            raise ValueError(f"{len(keep_k)} slices from slot {first} would pass slot 99: slice fewer, or clean up unused slots")
        if mode == "kit" and len(keep_k) > 120 - 60:
            raise ValueError("an instrument maps C-5 upwards: at most 60 slices")
        full = 128 if w.out_bits == 8 else 32768
        fade = min(max(1, w.rate // 1000), 32)
        keep = {k: entry[k] for k in ("base_note", "c5_speed", "volume", "global_volume", "stereo", "bits") if k in entry}
        stem = re.sub(r"-slice\d+(-\d+)?$", "", path.stem)
        nums, slot_of = [], {}
        for k in keep_k:
            s, e = bounds[k]
            y = x[:, s:e].copy()
            y[:, -fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
            out = next(p for p in (self.base_dir / f"{stem}-slice{k + 1:02d}{'' if j == 1 else f'-{j}'}.wav" for j in itertools.count(1))
                       if not p.exists())
            root = notes[k][1] if mode == "multi" else w.root
            self._created.append(out)
            write_wav(out, w.rate, np.clip(np.round(y * full), -full, full - 1).astype(np.int32).tolist(), bits=w.out_bits,
                      root_note=root)
            n_slot = first + len(nums)
            k_keep = dict(keep)
            name = f"{entry.get('name') or path.stem} {k + 1}"
            if mode == "multi":  # the note found plays true: C-5 at the rate that makes this slice sound C-5
                k_keep = {q: v for q, v in keep.items() if q not in ("base_note", "c5_speed")}
                k_keep["c5_speed"] = max(1, round(w.rate * 440 * 2 ** (-9 / 12) / notes[k][0]))
                name = f"{entry.get('name') or path.stem} {format_note(notes[k][1])}"
            self._song_op(lines, orders, {"op": "sample_new", "num": n_slot, "file": str(out), "keep": k_keep,
                                          "name": name[:25]}, remap)
            nums.append(n_slot)
            slot_of[k] = n_slot
        msg = f"slot {num:02d} cut into {len(bounds)} slices: slots {nums[0]:02d}-{nums[-1]:02d}"
        ins = None
        if insts:
            ins = max((int(i) for i in (self.song.get("instruments") or {})), default=0) + 1
            if mode == "multi":
                splits = compose.key_splits([notes[k][1] for k in keep_k])
                keymap = [{"notes": format_note(a) if a == b else f"{format_note(a)}..{format_note(b)}",
                           "sample": nums[i]} for i, a, b in splits]
                label = f"{entry.get('name') or path.stem} multi"
                msg += (f"; instrument {ins:02d} plays each over the keys nearest its note "
                        f"({', '.join(format_note(notes[keep_k[i]][1]) for i, _, _ in splits)})")
                if len(keep_k) < len(bounds):
                    msg += f"; {len(bounds) - len(keep_k)} without a note left out"
                if len(splits) < len(keep_k):
                    msg += f"; {len(keep_k) - len(splits)} repeating a note get a slot but no keys"
            else:
                keymap = [{"notes": format_note(60 + i), "sample": s, "play_note": "C-5"} for i, s in enumerate(nums)]
                label = f"{entry.get('name') or path.stem} slices"
                msg += f"; instrument {ins:02d} plays them from C-5 up"
            self._song_op(lines, orders, {"op": "instrument_new", "num": ins, "entry": {"name": it_text(label, 25), "keymap": keymap}}, remap)
        if op.get("pattern"):
            msg += "; " + self._slice_pattern(lines, orders, remap, [bounds[k][0] for k in keep_k], w.rate, nums,
                                              [notes[k][1] if mode == "multi" else 60 + i if ins else 60
                                               for i, k in enumerate(keep_k)],
                                              ins, int(op.get("ch") or 0), f"{stem}_slices")
        self._report.append(msg)

    def _slice_pattern(self, lines, orders, remap, starts, rate, nums, keys, ins, ch, base):
        """A new pattern that plays the slices (their start frames `starts` in the source, their slots `nums`, played
        with instrument `ins` on `keys`, or each slot at C-5 in a song without instruments) in order at their original
        timing, from channel `ch`; not added to the order list. Returns the report's words."""
        from . import compose
        from .model import Cell
        from .notation import format_cell
        mod = self.mod
        nch = len(mod.channels)
        ch = max(0, min(nch - 1, ch))
        placed, rows, dropped = compose.slice_rows(starts, rate, mod.tempo, mod.speed, ch, nch)
        if any(delay > 15 for _, _, _, delay in placed):
            raise ValueError('Slice timing needs a delay above 15 ticks; choose a song speed of 16 or less before creating a pattern')
        name = re.sub(r"[^\w.-]+", "_", base)
        name = name if re.match(r"[A-Za-z]", name) else "s" + name
        names = {k for _, k in self._children(lines, self._top(lines, "patterns"))}
        name = next(c for c in (name if k == 1 else f"{name}{k}" for k in itertools.count(1)) if c not in names)
        rows = max(rows, 1)
        self._song_op(lines, orders, {"op": "pattern_new", "name": name, "rows": rows}, remap)
        grid = [["... .. ... ..."] * nch for _ in range(rows)]
        for k, row, c, delay in placed:
            cell = Cell(note=keys[k], instrument=ins if ins else nums[k], effect=compose.S_EFFECT if delay else 0,
                        param=0xD0 | delay if delay else 0)
            grid[row][c] = format_cell(cell)
        first, _ = self._pattern_block(lines, name)
        ind = " " * (self._ind(lines[first - 1]) + 2)
        lines[first:first] = [f"{ind}{r:02d}: {' | '.join(cells)}\n" for r, cells in enumerate(grid)]
        words = (f"pattern '{name}' plays them at their timing ({rows} rows at tempo {mod.tempo} speed {mod.speed}; "
                 f"not in the order list: INSERT it in the Song tab)")
        if dropped:
            words += f", {len(dropped)} left out (past 200 rows, or every channel taken on their row)"
        return words

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
        for idx in range(len(mod.patterns)) if whole else [self.pattern_at(op["pattern"])]:
            rows = mod.patterns[idx].rows
            r0 = 0 if whole else max(0, int(op.get("r0") or 0))
            r1 = len(rows) - 1 if whole or op.get("r1") is None else min(len(rows) - 1, int(op["r1"]))
            if kind == "groove":
                cells, s = compose.groove(rows, chans, r0, r1, op.get("ticks") or [], mod.speed)
                skipped += s
            elif kind == "euclid":
                if not 1 <= int(op["steps"]) <= 64:
                    raise ValueError("a Euclidean rhythm has 1-64 steps")
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

    def section_edit(self, body):
        with self.lock:
            self._need_compiled()
            name, action = str(body.get('name', '')).strip(), body.get('action', 'save')
            sections = copy.deepcopy(self.song.get('sections') or {})
            if action == 'save':
                sections[name] = [int(body['start']), int(body['end'])]
                self._commit(sections_text(self.text, sections))
                return
            if name not in sections:
                raise ValueError('Select a named section first')
            a, b = sections[name]
            if action == 'delete':
                del sections[name]
                self._commit(sections_text(self.text, sections))
                return
            if action == 'rename':
                new = str(body.get('new_name') or '').strip()
                if not new or len(new) > 80:
                    raise ValueError('Name the section 1-80 characters')
                if new in sections:
                    raise ValueError(f'A section is named {new} already')
                self._commit(section_renamed(self.text, name, new))
                return
            meta = copy.deepcopy(self.meta)
            if action in ('select', 'loop'):
                playable = [i for i, o in enumerate(self.facts['orders']) if a <= o['order'] < b]
                if not playable:
                    raise ValueError('The section has no playable orders')
                meta['orders'] = [playable[0], playable[-1]+1]
                if action == 'loop':
                    meta['loop'] = {'from': [playable[0], 0], 'to': [playable[-1], self.facts['orders'][playable[-1]]['rows']-1]}
                self._commit(self.text, meta=meta)
                return
            before = [str(o) for o in self.song['orders']]
            at = int(body.get('to', len(before)))
            if not 0 <= at <= len(before):
                raise ValueError('Destination is an order boundary from 0 to the order count')
            lines = self.text.splitlines(keepends=True)
            clones = {}
            if action == 'move':
                if a <= at <= b:
                    return
                origins = [i for i in range(len(before)) if not a <= i < b]
                insert = at if at < a else at - (b-a)
                origins[insert:insert] = list(range(a, b))
                after = [before[i] for i in origins]
            elif action == 'duplicate':
                insert = at
                independent = bool(body.get('independent', True))
                names = set(self.song['patterns'])
                for src in dict.fromkeys(before[a:b]):
                    if src in ('+++', '---'):
                        continue
                    first, end = self._pattern_block(lines, src)
                    if not independent and any(a <= int(m.group(1), 16) < b for line in lines[first:end]
                                              for m in api._JUMP.finditer(line.partition(';')[0])):
                        raise ValueError('Shared copy has jumps into its section; choose independent patterns to keep those jumps inside the copy')
                    if independent:
                        clone = next(n for n in (src + '_copy' + str(i) for i in itertools.count(1)) if n not in names)
                        names.add(clone)
                        self._song_op(lines, list(before), {'op': 'pattern_clone', 'src': src, 'name': clone}, [])
                        clones[src] = clone
                segment = [clones.get(p, p) for p in before[a:b]]
                after = before[:at] + segment + before[at:]
                origins = list(range(at)) + [None] * (b-a) + list(range(at, len(before)))
            else:
                raise ValueError('unknown section action')
            mapping = reorder(self, lines, before, after, origins, meta)
            if action == 'duplicate':
                for clone in clones.values():
                    first, end = self._pattern_block(lines, clone)
                    inside = {mapping[i]: insert + i-a for i in range(a, b)}
                    for i in range(first, end):
                        data, sep, comment = lines[i].partition(';')
                        lines[i] = api._JUMP.sub(lambda m: f'B{inside.get(int(m.group(1), 16), int(m.group(1), 16)):02X}', data) + sep + comment
                sections = api.from_yaml(''.join(lines)).get('sections') or {}
                new_name = str(body.get('new_name') or name + ' copy')
                if new_name in sections:
                    new_name = next(f'{new_name} {i}' for i in itertools.count(2) if f'{new_name} {i}' not in sections)
                sections[new_name] = [insert, insert + b-a]
                lines = sections_text(''.join(lines), sections).splitlines(keepends=True)
            self._write_orders(lines, after)
            self._commit(''.join(lines), meta=meta)

    def _wav_for_op(self, f):
        """An edit's sound file as a WAV (as_wav); one written for it goes again when the edit is refused."""
        f, new = self.as_wav(f)
        if new:
            self._created.append(f)
        return f.resolve()

    def song_edit(self, ops):
        """Apply `ops` (dicts with `op`: orders, pattern_new, pattern_clone, pattern_rename, pattern_delete, pattern_rows,
        channel_rename, channel_add, channel_remove, channel_move, module, instrument_set / new / delete, sample_new,
        sample_set (the whole entry), sample_file (the slot pointed at another WAV), sample_delete, sample_process (an edit of the slot's audio written as a new WAV beside the song,
        the slot pointed at it), echo, groove, euclid, chord, layers, render_sample (rows rendered into a new slot), sample_slice) to the song text as one undo step. The tryout's
        channel mutes and unwritten faders follow a channel that moves or goes; its section and loop are dropped when they
        fall outside a changed order list."""
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the edit does not overwrite that change")
            lines = self.text.splitlines(keepends=True)
            meta = copy.deepcopy(self.meta)
            before = [str(o) for o in (self.song.get("orders") or [])]
            orders, remap = list(before), []
            self._created = []  # WAVs written by sample edits: removed again when the edit is refused
            self._report = []   # what an op tells the page (the echo's counts)
            try:
                for op in ops:
                    self._song_op(lines, orders, op, remap)
                if orders != before:
                    explicit = [op['origins'] for op in ops if op.get('op') == 'orders' and 'origins' in op]
                    origins = explicit[-1] if explicit else (list(range(len(before))) if all(op.get('op') == 'pattern_rename' for op in ops)
                                                            else occurrence_map(before, orders))
                    # A replacement at one position (e.g. Make unique) retains that occurrence's identity.
                    if len(before) == len(orders):
                        origins = [i if o is None and i not in origins else o for i, o in enumerate(origins)]
                    reorder(self, lines, before, orders, origins, meta)
                    self._write_orders(lines, orders)
                loaded = load_song_text("".join(lines), self.base_dir, str(self.song_path))
            except Exception:
                for f in self._created:
                    f.unlink(missing_ok=True)
                raise
            for f in remap:
                mix = meta.get("mix") or {}
                for k in ("volume", "pan"):
                    if mix.get(k):
                        mix[k] = {str(f(int(c))): v for c, v in mix[k].items() if f(int(c)) is not None}
                meta["muted"] = sorted(f(c) for c in meta.get("muted") or [] if f(c) is not None)
                if meta.get("solo") is not None:
                    meta["solo"] = f(meta["solo"])
            n = len(orders)
            if meta.get("orders") and meta["orders"][1] > n:
                meta["orders"] = None
            if meta.get("loop") and max(meta["loop"]["from"][0], meta["loop"]["to"][0]) >= n:
                meta["loop"] = None
            try:
                self._commit(''.join(lines), loaded, meta=meta)
            except Exception:
                for f in self._created:
                    f.unlink(missing_ok=True)
                raise
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
            step = unpack_step(src[-1])
            meta = step.get("meta")
            self._check_assets(step)
            back = self._step({k: self.meta.get(k) for k in meta} if meta else None)
            target = copy.deepcopy(self.meta)
            if meta:
                target.update(copy.deepcopy(meta))
            loaded = load_song_text(step['text'], self.base_dir, str(self.song_path))
            history, future = (dst + [back], src[:-1]) if redo else (src[:-1], dst + [back])
            self.history, self.future = self._write_step(step['text'], target, history, future)
            self.meta = target
            self.want = target.get("selected_candidate")
            self.reload(archive=False, loaded=loaded)

    # ---- sample editor

    def _sample_wav(self, num):
        entry = (self.song.get("samples") or {}).get(int(num))
        if not isinstance(entry, dict) or not entry.get("file"):
            raise ValueError(f"sample slot {num} has no WAV")
        path = (self.base_dir / str(entry["file"])).resolve()
        st = path.stat()
        return entry, path, *wav_array(str(path), (st.st_mtime, st.st_size))

    @property
    def takes_dir(self):
        return self.base_dir / "takes"

    def save_take(self, x, rate, opts=None):
        """A recorded take (float channels x frames) written as a 16-bit WAV in <song dir>/takes/<name>-NN.wav: its
        silent edges trimmed (`trim`, under `trim_db` dBFS, 10 ms kept before the first sound), its pitch found
        (`root`: written as the WAV's root note), then sent on (`dest`): `candidate` adds it to the slot's tryout
        candidates (U writes it, as with any candidate), `slot` adds a new sample slot tuned to the cent (its c5_speed
        makes the detected note play true), `keep` leaves it in the list. Returns the take's entry, newest first in
        State.takes."""
        import numpy as np
        from . import dsp
        from .notation import format_note
        from .wavload import write_wav
        opts = opts or {}
        if opts.get("trim", True):
            a, b = dsp.trim_edges(x, rate, float(opts.get("trim_db", -50)))
            if b <= a:
                raise ValueError(f"the take is silent (nothing above {opts.get('trim_db', -50)} dBFS): nothing saved")
            x = x[:, a:b]
        hz = dsp.pitch_of(x, rate) if opts.get("root", True) else None
        note, cents = dsp.note_of(hz) if hz else (None, 0.0)
        note = note if note is not None and 0 <= note < 120 else None
        self.takes_dir.mkdir(exist_ok=True)
        stem = re.sub(r"[^\w.-]+", "_", str(opts.get("name") or "take"))[:40] or "take"
        out = next(p for p in (self.takes_dir / f"{stem}-{k:02d}.wav" for k in itertools.count(1)) if not p.exists())
        pcm = np.clip(np.round(x * 32768), -32768, 32767).astype(np.int32).tolist()
        write_wav(out, rate, pcm, root_note=note)
        peak = float(np.abs(x).max())
        take = {"file": out.name, "path": str(out), "seconds": round(x.shape[1] / rate, 3), "channels": x.shape[0],
                "peak": round(20 * math.log10(peak), 1) if peak > 0 else None, "clipped": peak >= 0.999,
                "hz": hz or None, "note": format_note(note) if note is not None else None,
                "cents": round(cents), "rate": rate, "dest": None, "slot": None}
        self.takes.insert(0, take)
        return self.send_take(out.name, opts.get("dest") or "candidate")

    def send_take(self, name, dest):
        """Take `name` (of State.takes) sent on: `candidate` of the current slot, a new `slot` tuned to the cent (its
        c5_speed makes the detected note play true; a song with instruments gets one that plays it), or `keep`
        (nothing). Returns the take's entry."""
        take = next((x for x in self.takes if x["file"] == name), None)
        if take is None:
            raise ValueError(f"no take {name} in this session")
        out = Path(take["path"])
        if dest == "candidate":
            with self.lock:
                if str(out) not in self.cands():
                    self.cands().append(str(out))
                self.save_meta()
            take["slot"] = self.slot
            self.queue_all()
        elif dest == "slot":
            from .notation import parse_note
            num = max((int(k) for k in (self.song.get("samples") or {})), default=0) + 1
            keep = {"stereo": True} if take["channels"] == 2 else {}
            if take["hz"] and take["note"]:  # the detected note plays true: its speed scaled by the cents it was off
                note = parse_note(take["note"])
                keep["c5_speed"] = round(take["rate"] * 2 ** ((60 - note) / 12) * 440 * 2 ** ((note - 69) / 12) / take["hz"])
            ops = [{"op": "sample_new", "num": num, "file": str(out), "name": out.stem[:25], "keep": keep}]
            if self.song.get("instruments"):  # cells play instruments: one that plays the slot, else it cannot be heard
                take["instrument"] = max(int(i) for i in self.song["instruments"]) + 1
                ops.append({"op": "instrument_new", "num": take["instrument"], "entry": {"name": it_text(out.stem, 25), "sample": num}})
            self.song_edit(ops)
            take["slot"] = num
        elif dest != "keep":
            raise ValueError("a take goes to the slot's candidates, a new slot, or stays in the list")
        take["dest"] = dest
        return take

    def takes_multisample(self, names=None):
        """This session's takes that hold a note (or those in `names`) made one instrument: a new slot per take, tuned to
        the cent (its c5_speed plays the note found true), and a new instrument playing each over the keys nearest its
        note (compose.key_splits; a repeated note gets a slot but no keys). One undo step. Returns the report."""
        from . import compose
        from .notation import format_note, parse_note
        takes = [t for t in reversed(self.takes) if (names is None or t["file"] in names) and t.get("note") and t.get("hz")]
        if not takes:
            raise ValueError("no take holds a note: record single notes with FIND THE NOTE on")
        if not self.song.get("instruments"):
            raise ValueError("a multisample is an instrument: this song plays samples directly (no instruments)")
        num = max((int(k) for k in (self.song.get("samples") or {})), default=0) + 1
        if num + len(takes) - 1 > 99:
            raise ValueError(f"{len(takes)} takes from slot {num} would pass slot 99")
        ins = max(int(i) for i in self.song["instruments"]) + 1
        ops = []
        for k, t in enumerate(takes):
            keep = {"c5_speed": max(1, round(t["rate"] * 440 * 2 ** (-9 / 12) / t["hz"])), **({"stereo": True} if t["channels"] == 2 else {})}
            ops.append({"op": "sample_new", "num": num + k, "file": t["path"], "name": Path(t["file"]).stem[:25], "keep": keep})
        splits = compose.key_splits([parse_note(t["note"]) for t in takes])
        keymap = [{"notes": format_note(a) if a == b else f"{format_note(a)}..{format_note(b)}", "sample": num + i}
                  for i, a, b in splits]
        ops.append({"op": "instrument_new", "num": ins, "entry": {"name": "takes multi", "keymap": keymap}})
        self.song_edit(ops)
        for k, t in enumerate(takes):
            t.update(dest="multi", slot=num + k, instrument=ins)
        rep = (f"{len(takes)} takes in slots {num:02d}-{num + len(takes) - 1:02d}; instrument {ins:02d} plays each over the "
               f"keys nearest its note ({', '.join(takes[i]['note'] for i, _, _ in splits)})")
        return rep + (f"; {len(takes) - len(splits)} repeating a note get no keys" if len(splits) < len(takes) else "")

    def paint(self, body):
        """The PAINT tab (spectral.py): `action` preview (the picture played as sound: WAV bytes, peak at -1 dBFS),
        slot (written as a WAV beside the song, `paint-<name>.wav` with the picture as a PNG beside it, and added as a
        new slot, with an instrument in a song with instruments: one undo step), candidate (written the same way and
        added to the tryout slot's candidates), filter_preview (slot `num`'s WAV through the picture: WAV bytes) or filter
        (the same as an edit of slot `num`: a new WAV, one undo step). Returns bytes for the previews, else a report."""
        import numpy as np
        from . import spectral
        from .wavload import write_wav
        act = body.get("action")
        pic = paint_args(body)
        if act in ("filter", "filter_preview"):
            num = int(body["num"])
            if act == "filter":
                self.song_edit([{"op": "sample_process", "num": num, "action": "spectral_mask",
                                 "params": {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in pic.items() if k != "pan"}}])
                return {"report": f"slot {num:02d} filtered through the picture: {Path(self.current_file_of(num)).name}"}
            with self.lock:
                _, _, w, x = self._sample_wav(num)
            y = spectral.spectral_mask(x, w.rate, pic["amp"], pic["fmin"], pic["fmax"], pic["scale"], pic["range_db"])
            return _wav_bytes(y, w.rate)
        y, peak = spectral.paint_render(pic["amp"], pic["pan"], pic["seconds"], RATE, pic["fmin"], pic["fmax"],
                                        pic["scale"], pic["range_db"], int(body.get("seed") or 0))
        if peak <= 0:
            raise ValueError("paint: the picture is dark (nothing painted, or only above the 18 kHz ceiling)")
        y *= 0.891 / peak
        stereo = bool(np.abs(y[0] - y[1]).max() > 1e-6)
        y = y if stereo else y[:1]
        if act == "preview":
            return _wav_bytes(y, RATE)
        if act not in ("slot", "candidate"):
            raise ValueError("paint: preview, slot, candidate, filter or filter_preview")
        stem = re.sub(r"[^\w.-]+", "_", str(body.get("name") or "paint"))[:40] or "paint"
        out = next(p for p in (self.base_dir / f"paint-{stem}{'' if k == 1 else f'-{k}'}.wav" for k in itertools.count(1))
                   if not p.exists() and not p.with_suffix(".png").exists())
        write_wav(out, RATE, np.clip(np.round(y * 32768), -32768, 32767).astype(np.int32).tolist())
        out.with_suffix(".png").write_bytes(png_rgb(spectral.picture_png(pic["amp"], pic["pan"])))
        try:
            words = self.place_wav(out, act, stereo)
        except Exception:
            out.unlink(missing_ok=True)
            out.with_suffix(".png").unlink(missing_ok=True)
            raise
        return {"report": f"{out.name} ({pic['seconds']:.2f} s{', stereo' if stereo else ''}) {words}", "file": str(out)}

    def place_wav(self, out, dest, stereo=False):
        """A WAV the app wrote beside the song, sent on: `candidate` (added to the tryout slot's candidates) or `slot` (a
        new slot, with an instrument in a song with instruments: one undo step; its root note, from the WAV's smpl chunk,
        as the base note). Returns the report's words."""
        out = Path(out)
        if dest == "candidate":
            with self.lock:
                if str(out) not in self.cands():
                    self.cands().append(str(out))
                self.save_meta()
            self.queue_all()
            return f"added to slot {self.slot:02d}'s candidates"
        if dest != "slot":
            raise ValueError("a new WAV goes to the slot's candidates or a new slot")
        num = max((int(k) for k in (self.song.get("samples") or {})), default=0) + 1
        root = read_wav(out).root
        keep = {"base_note": format_note(root)} if root is not None and 0 <= root < 120 and root != 60 else {}
        ops = [{"op": "sample_new", "num": num, "file": str(out), "name": out.stem[:25], "stereo": stereo, "keep": keep}]
        if self.song.get("instruments"):
            ops.append({"op": "instrument_new", "num": max(int(i) for i in self.song["instruments"]) + 1,
                        "entry": {"name": it_text(out.stem, 25), "sample": num}})
        self.song_edit(ops)
        return f"in new slot {num:02d}" + (f", played by instrument {ops[1]['num']:02d}" if len(ops) > 1 else "")

    def faust_recipe(self, wav, faust):
        """The FAUST tab's save made reproducible: a `faust:` entry named after `wav` in faust.yaml beside the song (made
        when missing) that renders it again (the code, NOTE, HOLD, TAIL, VELOCITY and the sliders; no trim or fade, as the
        tab renders), so the RECIPE box shows it for the slot, renders it again and edits it. Returns the report's words."""
        from .synth import RecipeError, expand
        notes = [format_note(int(n)) for n in faust.get("notes") or []] or ["C-5"]
        spec = {"faust": str(faust.get("code") or ""), **({"chord": notes} if len(notes) > 1 else {"note": notes[0]}),
                "hold": float(faust.get("hold") or 1), "tail": float(faust.get("tail") or 0),
                "velocity": int(faust.get("velocity") or 100),
                **({"params": {str(k): float(v) for k, v in faust["params"].items()}} if faust.get("params") else {}),
                "trim": False, "fade_out": 0}
        path, name = self.base_dir / "faust.yaml", Path(wav).stem
        dump = lambda d: yaml.dump(d, Dumper=api._Dumper, sort_keys=False, width=120, allow_unicode=True)  # noqa: E731
        text = path.read_text(encoding="utf-8") if path.exists() else (
            "# Sounds saved from the FAUST tab: each entry renders its WAV again (SAMPLING.md, faust:)\nout_dir: .\nsamples:\n")
        try:
            doc = yaml.load(text, Loader=api._Loader)
            new = name not in ((doc or {}).get("samples") or {})
            if new:
                text += ("" if text.endswith("\n") else "\n") + "".join(f"  {line}\n" for line in dump({name: spec}).splitlines())
                doc = yaml.load(text, Loader=api._Loader)
                list(expand(doc))
        except (RecipeError, yaml.YAMLError, AttributeError) as e:
            return f" (its faust: entry was not written: {path.name}: {e})"
        if new:
            if (doc["samples"].get(name) != spec or list(doc).index("samples") != len(doc) - 1
                    or (self.base_dir / str(doc.get("out_dir", "."))).resolve() != self.base_dir.resolve()):
                return f" (its faust: entry was not written: {path.name} is not laid out as the app writes it)"
            _atomic(path, text.encode("utf-8"))
        with self.lock:
            self.meta.setdefault("recipe_of", {})[str(Path(wav).resolve())] = {"recipe": str(path), "name": name, "note": None,
                                                                               "spec": dump(doc["samples"][name])}
            self.save_meta()
        return f"; its faust: entry is in {path.name}"

    def current_file_of(self, num):
        f = ((self.song.get("samples") or {}).get(int(num)) or {}).get("file")
        return str((self.base_dir / f).resolve()) if f else ""

    def find_similar(self, lib, query, k=8):
        """The `k` sounds of the library `lib` nearest WAV `query` by timbre (library.Library.nearest, after a scan when
        the last is over a minute old), added to the slot's candidates; the slot's own WAV and the candidates it already
        has are passed over. Each is remembered with the query and its distance (meta `found`). Returns {"added",
        "report"}."""
        with self.lock:
            slot, skip = self.slot, [*self.cands(), self.current_file() or ""]
        lib.fresh()
        near = lib.nearest(query, max(1, min(50, int(k))), exclude=skip)
        with self.lock:
            cands = self.meta["candidates"].setdefault(str(slot), [])
            found = self.meta.setdefault("found", {})
            for p, d in near:
                if p not in cands:
                    cands.append(p)
                found[p] = [Path(query).stem, round(d, 2)]
            self.save_meta()
        self.queue_all()
        if not near:
            return {"added": [], "report": f"nothing like {Path(query).name} in the library ({lib.count()} sounds indexed)"}
        return {"added": [p for p, _ in near], "report": f"{len(near)} sounds like {Path(query).name} added to slot "
                f"{slot:02d}'s candidates (distance {near[0][1]:.2f}-{near[-1][1]:.2f})"}

    def auto_loop(self, num):
        """Loop points AUTO LOOP proposes for slot `num`: {start, end (exclusive), hz} in the WAV's frames, or an error
        naming why none (the sound does not hold steady, or holds no pitch and no match)."""
        from . import dsp
        with self.lock:
            _, _, w, x = self._sample_wav(num)
        hz = dsp.pitch_of(x, w.rate)
        lp = dsp.find_loop(x, w.rate, hz)
        if lp is None:
            raise ValueError("no loop found: the sound does not hold steady for 0.2 s (a drum or a short hit?)")
        return {"start": lp[0], "end": lp[1], "hz": round(hz, 2) if hz else None}

    def slice_points(self, num, mode="onsets", value=50, a=None, b=None):
        """Where SLICE would cut slot `num`'s WAV, frames a..b (default: all of it): at its hits (`onsets`, value the
        sensitivity 0-100) or into `equal` parts (value the count). {"points": the slices' start frames, "end"}."""
        from . import dsp
        with self.lock:
            _, _, w, x = self._sample_wav(num)
        n = x.shape[1]
        a = max(0, min(n - 1, int(a or 0)))
        b = max(a + 1, min(n, int(b) if b not in (None, "") else n))
        if mode == "equal":
            pts = dsp.equal_parts(a, b, int(value))
        elif mode == "onsets":
            pts = dsp.onsets(x, w.rate, value, a, b)
        else:
            raise ValueError("slices go at the hits (onsets) or in equal parts")
        return {"points": [int(p) for p in pts], "end": b}

    def sample_view(self, num, a=0, b=None, n=1000):
        """The editor's view of slot `num`: the WAV (frames, rate, channels, bits), its loops in the WAV's frames, the
        peaks of frames a..b in `n` columns, and what previews it in the live engine: [instrument index as libopenmpt
        counts (0-based; the sample in a song without instruments), note], preferring the note that plays the WAV at its own
        speed (its base_note, or the note its c5_speed puts there: a recorded take is heard as it was played)."""
        with self.lock:
            entry, path, w, x = self._sample_wav(num)
            frames = x.shape[1]
            a = max(0, min(frames - 1, int(a)))
            b = frames if b is None else max(a + 1, min(frames, int(b)))
            mn, mx = wave_peaks(x, a, b, max(16, min(4000, int(n))))
            if entry.get("c5_speed"):
                root = round(60 - 12 * math.log2(int(entry["c5_speed"]) / w.rate))
            else:
                from .notation import parse_note
                root = parse_note(str(entry.get("base_note") or "C-5"))
            player = [int(num) - 1, root]
            if self.mod and self.mod.instruments is not None:
                hits = [(played != root, i, note) for i, ins in enumerate(self.mod.instruments)
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
        stem = re.sub(rf"-({'|'.join(SAMPLE_ACTIONS)})(-\d+)?$", "", src.stem)
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
        """A sound file dropped on the page (its bytes: the page cannot know the file's path) saved beside the song as
        <name>.wav, numbered so no other file is replaced; an identical copy already there is reused. A FLAC, AIFF, OGG or
        MP3 becomes that WAV (as_wav). Returns the path."""
        if Path(name).suffix.lower() in SOUND_FILES and data[:4] != b"RIFF":
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / f"upload{Path(name).suffix.lower()}"
                src.write_bytes(data)
                return self.as_wav(src, name)[0]
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise ValueError(f"{name}: not a WAV, FLAC, AIFF, OGG or MP3 file")
        p, new = save_beside(self.base_dir, Path(name).stem, ".wav", data)
        if new:
            try:
                read_wav(p)
            except (OSError, ValueError):
                p.unlink()
                raise
        return p

    def as_wav(self, path, name=None):
        """(`path`, False) for a WAV; a FLAC, AIFF, OGG or MP3 becomes a WAV beside the song, never over a file there, with
        the loops and root note OpenMPT keeps from it (wavload.to_wav): (that WAV, whether it was written now)."""
        if Path(path).suffix.lower() not in SOUND_FILES:
            return Path(path), False
        return to_wav(path, self.base_dir, ffmpeg_exe(), name)

    # ---- pattern view

    def pattern_rows(self, index):
        """One pattern as read-only tracker rows; each cell in the 'C-5 01 v64 A06' layout libopenmpt prints."""
        pat = self.mod.patterns[self.pattern_at(index)]
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
                              "note": rating.get("note", ""), "current": c == cur,
                              "found": (self.meta.get("found") or {}).get(c)})
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
                         "mtime": self.mtime, "stamps": hashlib.sha1((self._stamps or "").encode()).hexdigest()[:8], "facts": self.facts, "sample_entries": {str(k): v for k, v in ents.items()},
                         "slot_meas": slot_meas},
                "slot": slot, "slot_entry": entry, "slot_file": cur, "ref": ref, "selected_candidate": self.want,
                "orders": list(self.orders) if self.orders else None, "loop": self.meta.get("loop"),
                "muted": sorted(set(self.meta.get("muted") or [])), "solo": self.meta.get("solo"),
                "own": {"key": ok, "status": own["status"], "error": own.get("error"), "peak": own.get("peak"),
                        "numbers": mix_numbers(own["file"]) if own["status"] == "ready" else None},
                "chosen_numbers": next((mix_numbers(self.renders[c["key"]]["file"]) for c in cands
                                        if c["path"] == self.want and c["status"] == "ready"), None),
                "mix": self.mix(), "meters": self.meters, "voice": voice, "spec": {"db": SPEC_DB, "stops": SPEC_STOPS, "nyquist": RATE / 2},
                "reference": self.meta.get("reference"), "delta": {"db": DELTA_DB, "stops": DELTA_STOPS},
                "voice_range": VOICE_RANGE, "dmo": DMO,
                "candidates": cands, "build": self.build, "stems": self.stems, "export": self.export_result,
                "cand_counts": {k: len(v) for k, v in self.meta["candidates"].items() if v},
                "notes": self.notes, "notes_path": str(self.notes_path), "version": self.version(),
                "faust_code": self.meta.get("faust_code"),
                "undo": len(self.history), "redo": len(self.future), "unused": self.unused(),
                "cue": self.cue, "agent_log": self.agent_log[-40:], "chat": CHAT.snapshot(),
                "marks": {"patterns": {p.name: {k: v for k, v in self.pattern_entry(p.name).items() if k in ("by", "approved")}
                                       for p in (self.mod.patterns if self.mod else [])},
                          "channels": [bool(isinstance(c, dict) and c.get("approved"))
                                       for c in ((self.song.get("module") or {}).get("channels") or [])
                                       ] if isinstance((self.song.get("module") or {}).get("channels"), list) else [],
                          "samples": [int(k) for k, v in (self.song.get("samples") or {}).items()
                                      if isinstance(v, dict) and v.get("approved")]},
                "checkpoints": list(self.checkpoints),
                "history_bytes": self.history_store.path.stat().st_size if self.history_store.path.exists() else 0,
                "history_limit": HISTORY_BYTES,
                "phrase": {k: v for k, v in (self.meta.get("phrase") or {}).items() if k not in ("snapshot", "assets", "source_assets", "original")},
                "project_settings": self.meta.get('project_settings') or {},
                "missing": {str(k): v['file'] for k, v in ents.items() if isinstance(v, dict) and v.get('file')
                            and not (self.base_dir / str(v['file'])).is_file()},
                "notices": self.notices,
                "recipe": self._recipe_snapshot(),
                "instruments": {str(k): v for k, v in (self.song.get("instruments") or {}).items()},
                "sections": self.song.get("sections") or {},
                "structure": {"orders": [str(o) for o in self.song.get("orders") or []],
                              "patterns": [{"name": p.name, "rows": len(p.rows), "index": i,
                                            "used": sum(1 for o in self.song.get("orders") or [] if str(o) == p.name)}
                                           for i, p in enumerate(self.mod.patterns)] if self.mod else [],
                              "module": {k: (self.mod.row_highlight[0] or 4) if k == 'rows_per_beat' else
                                               (self.mod.row_highlight[1] or 16) if k == 'rows_per_bar' else
                                               getattr(self.mod, k) for k in self.MODULE_KEYS} if self.mod else {}},
                "archives": sorted(p.name for p in self.base_dir.glob(glob.escape(self.song_path.stem) + ".notes-*.md")),
                "queue": sum(1 for r in self.renders.values() if r["status"] in ("queued", "rendering")),
                "cache": sum(1 for r in self.renders.values() if r["status"] == "ready"),
            }


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    state: State = None
    window = None  # pywebview window, when the UI runs in one

    recorder = None      # record.Recorder, made on the RECORD tab's first request
    rec_devices = None   # the input devices, listed once (again on REFRESH)
    library = None       # library.Library, read on the first FIND SIMILAR or MAP request
    faust_job = None     # the faustwasm download: {"status", "got", "size", "error"}

    @classmethod
    def fetch_faust(cls):
        from . import faust
        if cls.faust_job and cls.faust_job["status"] == "fetching":
            return cls.faust_job
        job = cls.faust_job = {"status": "fetching", "got": 0, "size": 0, "error": None}

        def run():
            try:
                faust.fetch(lambda got, size: job.update(got=got, size=size))
                job["status"] = "done"
            except (OSError, ValueError) as e:
                job.update(status="failed", error=f"{type(e).__name__}: {e}")
        threading.Thread(target=run, daemon=True).start()
        return job

    @classmethod
    def rec(cls):
        if cls.recorder is None:
            from .record import Recorder
            if _read_json(REC_SETTINGS, {}, []).get("asio"):  # sounddevice loads its ASIO build only when this is set first
                os.environ.setdefault("SD_ENABLE_ASIO", "1")
            cls.recorder = Recorder()
        return cls.recorder

    @classmethod
    def rec_snapshot(cls, devices=False):
        """The RECORD tab's state: the input devices, the recorder's meters and tuner, the song's takes."""
        from .record import MODE_NAMES, RecordError
        r = cls.rec()
        out = {"available": True, "error": None, "fake": bool(os.environ.get("VT_FAKE_AUDIO")),
               "asio": bool(os.environ.get("SD_ENABLE_ASIO")), "asio_saved": bool(_read_json(REC_SETTINGS, {}, []).get("asio")),
               "modes": MODE_NAMES}
        try:
            if devices or cls.rec_devices is None:
                cls.rec_devices = r.devices()
                cls.rec_outputs = r.outputs()
            out["devices"] = cls.rec_devices
            out['outputs'] = getattr(cls, 'rec_outputs', [])
        except RecordError as e:
            out.update(available=False, error=str(e), devices=[])
        out["status"] = r.status()
        out["takes"] = cls.state.takes if cls.state else []
        return out

    @classmethod
    def rec_command(cls, body):
        """POST /api/rec: {cmd: open (device, mode, rate, exclusive) | mode | close | start (preroll) | stop (name, trim,
        trim_db, root, dest: candidate / slot / keep) | discard}."""
        from .record import RecordError
        r, cmd = cls.rec(), body.get("cmd")
        try:
            if cmd == "open":
                r.open(int(body["device"]), str(body.get("mode") or "1"), int(body.get("rate") or 44100),
                       bool(body.get("exclusive")))
            elif cmd == "mode":
                r.set_mode(str(body["mode"]))
            elif cmd == "close":
                r.close()
            elif cmd == "start":
                if cls.state is None:
                    raise RecordError("open a song first: takes are saved beside it")
                if r.recording:
                    raise RecordError('Stop the current take first')
                if body.get('backing'):
                    from .export import snapshot, render
                    from .resample import resample
                    import numpy as np
                    st = cls.state
                    with st.lock:
                        st._need_compiled()
                        if st.dirty():
                            raise RecordError('Compare and RELOAD external edits before recording')
                        region = None
                        if body.get('section'):
                            a, b = st.song['sections'][body['section']]
                            playable = [i for i in range(a, b) if st.mod.orders[i] < len(st.mod.patterns)]
                            if not playable:
                                raise RecordError('The selected section has no playable orders')
                            a, b = playable[0], playable[-1]
                            region = (a, 0, b, len(st.mod.patterns[st.mod.orders[b]].rows)-1)
                        snap = snapshot(st.song, st.base_dir, region, st.mix(), st.silenced(), tail=0)
                        bpm = st.facts['bpm']
                    pcm = np.frombuffer(render(snap), dtype='<i2').astype(np.float32).reshape(-1, 2) / 32768
                    if r.rate != RATE:
                        pcm = np.stack([resample(pcm[:, c], RATE, r.rate) for c in range(2)], axis=1)
                    if cls.state is not st:
                        raise RecordError('The song changed while preparing playback; start again')
                    r.start_backing(pcm, body['output'], countin=body.get('countin', 4), bpm=bpm,
                                    loops=body.get('loops', 1), latency_ms=body.get('latency_ms', 0))
                else:
                    r.start(float(body.get("preroll") or 0))
            elif cmd == 'calibrate':
                from .record import calibration_signal
                if not r.rate:
                    raise RecordError('Open an input first')
                r.start_backing(calibration_signal(r.rate), body['output'], countin=0, calibration=True)
            elif cmd == "asio":  # takes effect at the next start: sounddevice has loaded its PortAudio already
                REC_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
                _atomic_text(REC_SETTINGS, json.dumps({"asio": bool(body.get("on"))}))
                now = bool(os.environ.get("SD_ENABLE_ASIO"))
                return {} if now == bool(body.get("on")) else {"error": "saved: restart the app to switch the ASIO driver "
                                                                        + ("on" if body.get("on") else "off")}
            elif cmd == "send":
                return {"take": cls.state.send_take(str(body["file"]), str(body.get("dest") or "candidate"))}
            elif cmd == "multisample":  # the session's takes with a note as one instrument
                return {"report": cls.state.takes_multisample(body.get("files"))}
            elif cmd in ("stop", "discard"):
                takes, plan = r.stop_takes()
                if cmd == 'stop' and takes:
                    if plan and plan['calibration']:
                        from .record import measure_latency
                        return {'latency_ms': measure_latency(plan['pcm'], takes[0], r.rate)}
                    saved = []
                    for i, x in enumerate(takes):
                        opts = dict(body)
                        if plan:
                            opts['trim'] = False  # preserve placement against the backing track
                            if plan['loops'] > 1:
                                opts['name'] = str(body.get('name') or 'take') + f'-pass{i+1}'
                        saved.append(cls.state.save_take(x, r.rate, opts))
                    return {'take': saved[-1], 'takes': saved}
            else:
                raise RecordError(f"unknown recorder command {cmd!r}")
        except (RecordError, ValueError) as e:
            return {"error": str(e)}
        return {}

    @classmethod
    def lib(cls):
        """The sample library's index (library.py), read on first use."""
        if cls.library is None:
            from .library import Library, default_index
            cls.library = Library(default_index())
        return cls.library

    @classmethod
    def lib_snapshot(cls):
        from .library import default_roots
        lib = cls.library
        if lib is None:
            return {"loaded": False}
        return {"loaded": True, "index": str(lib.path), "roots": lib.data["roots"], "default_roots": default_roots(),
                "status": lib.status, "count": lib.count(), "generation": lib.generation,
                "busy": bool(lib.job and lib.job.is_alive())}

    @classmethod
    def open_song(cls, path):
        if cls.recorder is not None and cls.recorder.recording:
            raise ValueError('Save or discard the recording before opening another song')
        old, cls.state = cls.state, State(path)  # the same song opened again shares the old state's lock
        if old is not None:
            old.close()
        remember_song(cls.state.song_path)

    @classmethod
    def browse(cls, wav=False, module=False):
        """Native file dialog, returning the chosen song (or, with `wav`, WAV; with `module`, module) path or None."""
        kind, pat = ("Sound files", ";".join(f"*{x}" for x in (".wav", *SOUND_FILES))) if wav else ("Modules, tabs and MIDI", "*.it;*.xm;*.s3m;*.mod;*.gp3;*.gp4;*.gp5;*.mid;*.midi") if module else ("Song files", "*.yaml;*.yml")
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

    def _guarded(fn):
        """An unexpected error is logged and answered with a 500 and its message: the page is never left without one."""
        @functools.wraps(fn)
        def run(self):
            try:
                return fn(self)
            except ConnectionError:
                raise
            except Exception as e:  # noqa: BLE001
                _log.exception("%s %s failed", self.command, self.path.split("?")[0])
                try:
                    self._send(500, {"error": logged(f"{type(e).__name__}: {e}")})
                except OSError:
                    pass
        return run

    @_guarded
    def do_GET(self):
        if self._foreign():
            return self._send(403, {"error": "not this app's page"})
        st = self.state
        path = self.path.split("?")[0]
        if path == "/":
            return self._send(200, HTML.read_bytes().replace(b"<title>VultureTracker</title>", f"<title>VultureTracker {__version__}</title>".encode()),
                              "text/html; charset=utf-8")
        if path == "/engine-worklet.js":
            return self._send(200, worklet_js(), "text/javascript; charset=utf-8")
        if path == "/web/libopenmpt.wasm":
            return self._send(200, WEB.joinpath("libopenmpt.wasm").read_bytes(), "application/wasm")
        if path == "/icon.png":
            return self._send(200, HTML.with_name("icon.png").read_bytes(), "image/png")
        if path == "/api/state":
            return self._send(200, {**(st.snapshot() if st else start_snapshot()), "library": self.lib_snapshot()})
        if path == "/api/library":
            self.lib()
            return self._send(200, self.lib_snapshot())
        if path == "/api/libmap":
            return self._send(200, self.lib().map())
        if path == "/api/libnear":  # the nearest sounds of an indexed one, for the map (nothing is added)
            from urllib.parse import parse_qs
            q = {k: v[0] for k, v in parse_qs(self.path.partition("?")[2]).items()}
            lib = self.lib()
            if not lib.has(q.get("path", "")):
                return self._send(404, {"error": "not in the library"})
            return self._send(200, {"near": lib.nearest(q["path"], max(1, min(50, int(q.get("k") or 8))))})
        if path == "/api/faust":
            from . import faust
            return self._send(200, {"have": faust.have(), "dir": str(faust.faust_dir()), "version": faust.VERSION,
                                    "job": Handler.faust_job})
        if path == "/web/faust-render.mjs":
            return self._send(200, WEB.joinpath("faust-render.mjs").read_bytes(), "text/javascript; charset=utf-8")
        if path.startswith("/faust/"):  # the fetched faustwasm files, nothing else
            from . import faust
            base = faust.faust_dir().resolve()
            f = (base / path[7:]).resolve()
            if not f.is_relative_to(base) or not f.is_file():
                return self._send(404, {"error": "not found"})
            kind = {".js": "text/javascript; charset=utf-8", ".wasm": "application/wasm"}.get(f.suffix, "application/octet-stream")
            return self._send(200, f.read_bytes(), kind)
        if path == "/libwav":
            from urllib.parse import parse_qs
            f = parse_qs(self.path.partition("?")[2]).get("path", [""])[0]
            if not self.lib().has(f):  # a sound of the index, nothing else
                return self._send(404, {"error": "not in the library"})
            return self._send_file(f, "audio/wav")
        if path == "/api/effects":
            return self._send(200, effect_help())
        if path == "/api/tools":  # the agent tools (agent.py), for the MCP server
            return self._send(200, {"tools": agent.tool_list(), "song": str(self.state.song_path) if self.state else None})
        if path == "/api/start":
            return self._send(200, start_snapshot())
        if path == "/api/rec":
            return self._send(200, self.rec_snapshot("devices=1" in self.path))
        if st is None:
            return self._send(404, {"error": "no song open"})
        if path.startswith("/take/"):
            f = st.takes_dir / Path(unquote(path[6:])).name  # a file of the song's takes folder, nothing else
            return self._send_file(f, "audio/wav")
        if path.startswith("/api/autoloop/"):
            try:
                return self._send(200, st.auto_loop(int(path[14:])))
            except (ValueError, OSError, ImportError) as e:
                return self._send(404, {"error": f"{type(e).__name__}: {e}"})
        if path.startswith("/api/pattern/"):
            try:
                return self._send(200, st.pattern_rows(int(path[13:])))
            except (ValueError, IndexError, AttributeError):
                return self._send(404, {"error": "no such pattern"})
        if path.startswith("/api/slices/"):
            from urllib.parse import parse_qs
            q = {k: v[0] for k, v in parse_qs(self.path.partition("?")[2]).items()}
            try:
                return self._send(200, st.slice_points(int(path[12:]), q.get("mode", "onsets"), float(q.get("value", 50)),
                                                       q.get("a"), q.get("b")))
            except (ValueError, OSError, ImportError) as e:
                return self._send(404, {"error": f"{type(e).__name__}: {e}"})
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
        if path.startswith("/refspec/"):  # ?view=ref|delta&scale=log|lin
            try:
                png = st.reference_png(path[9:], "delta" if "view=delta" in self.path else "ref", "lin" if "scale=lin" in self.path else "log")
            except (OSError, ImportError, wave.Error, ValueError) as e:
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return self._send(200, png, "image/png")
        if path.startswith("/api/refdiff/"):
            try:
                *_, cols, gain, covered = st.reference_compare(path[13:])
            except (OSError, ImportError, wave.Error, ValueError) as e:
                return self._send(400, {"error": f"{type(e).__name__}: {e}"})
            live = sorted(v for v in cols if v is not None)
            return self._send(200, {"cols": cols, "median": live[len(live) // 2] if live else None, "gain_db": gain, "covered": covered})
        if path.startswith("/raw/"):
            try:
                c = st.cand(path[5:])
            except (ValueError, IndexError):
                return self._send(404, {"error": "no such candidate"})
            return self._send_file(c, "audio/wav")
        if path.startswith("/api/diff/") or path == "/api/mixdiff":
            try:
                return self._send(200, st.mix_diff() if path == "/api/mixdiff" else st.diff(st.cand(path[10:])))
            except (KeyError, ValueError, IndexError, TypeError, AttributeError, OSError) as e:
                return self._send(400, {"error": f"{type(e).__name__}: {e}"})
        if path == "/api/it":
            try:
                return self._send(200, st.live_it(), "application/octet-stream")
            except (SongError, OSError, ValueError, OpenMPTError) as e:
                return self._send(400, {"error": "\n".join(getattr(e, "errors", []) or [str(e)])})
        self._send(404, {"error": "not found"})

    @_guarded
    def do_POST(self):
        if self._foreign():
            return self._send(403, {"error": "not this app's page"})
        st = self.state
        n = int(self.headers.get("Content-Length") or 0)
        if n > 512 << 20:  # a size from the request is what rfile.read allocates
            return self._send(413, {"error": "the request is over 512 MiB"})
        act = self.path.split("?")[0].rsplit("/", 1)[-1]
        if act == "upload":  # raw WAV bytes, ?name=
            from urllib.parse import parse_qs
            try:
                name = parse_qs(self.path.partition("?")[2]).get("name", ["dropped.wav"])[0]
                return self._send(200, {"path": str(st.save_upload(name, self.rfile.read(n)))})
            except (AttributeError, ValueError, OSError, struct.error) as e:
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
            elif act == "rec":
                return self._send(200, self.rec_command(body))
            elif act == "fetchfaust":  # faustwasm from npm, on a thread; GET /api/faust reports it
                return self._send(200, self.fetch_faust())
            elif act == "library":  # roots: the folders to index (saved); then a scan, waited for a moment
                lib = self.lib()
                if body.get("roots") is not None:
                    if lib.job and lib.job.is_alive():
                        raise ValueError("the library is busy: wait for the scan to finish")
                    lib.set_roots(body["roots"])
                res = lib.run(lib.scan, 0.5) if body.get("scan", True) else None
                return self._send(200, {"result": res, **self.lib_snapshot()})
            elif act == "tool":  # an agent tool run on the open song (the MCP server's calls)
                return self._send(200, agent.run(st, str(body.get("name")), body.get("args") or {}))
            elif act == "chatsettings":
                return self._send(200, agent.save_settings(body))
            elif act == "browse":
                p = self.browse()
                if p:
                    self.open_song(p)
                return self._send(200, {"path": p})
            elif st is None:
                return self._send(404, {"error": "no song open"})
            elif act == "selection":
                st.selection = body.get("selection")
                return self._send(200, {"ok": True})
            elif act == "chat":
                if body.get("clear"):
                    CHAT.clear()
                else:
                    CHAT.send(st, str(body.get("text") or "").strip(), body.get("context"))
            elif act == "slot":
                if not 1 <= int(body["slot"]) <= 99:
                    raise ValueError("a slot is 1-99")
                st.meta["slot"] = int(body["slot"])
                st.save_meta()
                st.queue_all()
            elif act == "orders":
                o = body.get("orders")
                if o is not None and not (isinstance(o, list) and len(o) == 2 and all(type(x) is int for x in o) and 0 <= o[0] < o[1]):
                    raise ValueError("the section is null or [first order, last order + 1]")
                st.meta["orders"] = o
                st.save_meta()
                st.queue_all()
            elif act == "loop":
                st.set_loop(body)
            elif act == "reference":  # path or browse sets it, offset (ms) moves it, align (with key) lines it up, clear
                return self._send(200, st.set_reference(self.browse(wav=True) if body.get("browse") else body.get("path"), body))
            elif act == "mute":
                muted, solo = sorted({int(i) for i in body.get("muted", [])}), None if body.get("solo") is None else int(body["solo"])
                if any(not 0 <= i < 64 for i in muted + ([solo] if solo is not None else [])):  # patch_it writes header byte 0x40 + i
                    raise ValueError("a channel is 0-63")
                st.meta["muted"], st.meta["solo"] = muted, solo
                st.save_meta()
                st.queue_all()
            elif act == "add":
                return self._send(200, {"added": st.add_candidates(body["globs"])})
            elif act == "remove":
                st.remove_candidate(st.cand(body["id"]))
            elif act == "rate":
                c = st.cand(body["id"])
                if "stars" in body and (type(body["stars"]) is not int or not 0 <= body["stars"] <= 5):
                    raise ValueError("stars are a whole number 0-5")
                r = st.meta["ratings"].setdefault(c, {})
                for k, kind in (("stars", int), ("rejected", bool), ("note", str)):
                    if k in body:
                        r[k] = kind(body[k])
                st.save_meta()
            elif act == "similar":  # the slot's WAV, a candidate (id) or any WAV (path): its nearest become candidates
                q = body.get("path") or (st.cand(body["id"]) if body.get("id") is not None else st.current_file())
                if not q or not Path(q).exists():
                    raise ValueError("nothing to compare: the slot has no WAV on disk")
                lib = self.lib()
                res = lib.run(lambda: st.find_similar(lib, q, body.get("k") or 8), max(0.0, min(60.0, float(body.get("wait", 20)))))
                if res and res.get("error"):
                    return self._send(400, res)
                return self._send(200, res or {"pending": True, "report": lib.status.get("message")})
            elif act == "paint":  # the PAINT tab: previews answer with WAV bytes, the rest with a report
                res = st.paint(body)
                if isinstance(res, bytes):
                    return self._send(200, res, "audio/wav")
                return self._send(200, res)
            elif act == "place":  # a WAV the page uploaded (the FAUST tab's render): to the candidates or a new slot
                f = Path(str(body["path"])).resolve()
                if f.parent != st.base_dir or f.suffix.lower() != ".wav":
                    raise ValueError("only a WAV beside the song")
                report = f"{f.name} " + st.place_wav(f, body.get("dest"), bool(body.get("stereo")))
                if isinstance(body.get("faust"), dict):  # the FAUST tab's code and settings: its recipe entry
                    report += st.faust_recipe(f, body["faust"])
                return self._send(200, {"report": report})
            elif act == "faustcode":  # the FAUST tab's code as it is typed, kept with the song
                st.meta["faust_code"] = str(body.get("code") or "")[:200000]
                st.save_meta()
            elif act == "want":
                st.set_want(st.cand(body["id"]) if body.get("id") is not None else None)
            elif act == "note":
                return self._send(200, st.add_note(body))
            elif act == "noteedit":
                st.edit_note(int(body["id"]), body)
            elif act == "retry":
                st.retry(st.cand(body["id"]))
            elif act == "apply":
                st.apply(st.cand(body["id"]))
            elif act == "mix":
                st.set_mix(body)
            elif act == "edit":  # one pattern (pattern, cells) or several in one step (patterns: [{pattern, cells}])
                st.edit_patterns([(g["pattern"], g["cells"]) for g in body["patterns"]] if "patterns" in body
                                 else [(body["pattern"], body["cells"])])
            elif act == "phrase":
                from .phrases import action
                return self._send(200, action(st, body))
            elif act == "section":
                st.section_edit(body)
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
            elif act == "external":
                return self._send(200, st.external_diff())
            elif act == "collect":
                return self._send(200, collect(st, body['destination'], bool(body.get('zip')), body.get('browser')))
            elif act == "relink":
                st.relink(body.get('num'), body.get('path'), body.get('links'))
            elif act == "projectsettings":
                settings = body.get('settings')
                if not isinstance(settings, dict) or len(json.dumps(settings)) > 2 * 1024 * 1024:
                    raise ValueError('Project browser settings must be an object under 2 MiB')
                st.meta['project_settings'] = settings
                st.save_meta()
            elif act == "materialize":
                st.materialize_pattern(body['pattern'])
            elif act == "trimhistory":
                st.trim_history(body.get('keep', 0))
            elif act == "checkpoint":
                return self._send(200, st.checkpoint(body.get('name', ''), body.get('action', 'save')))
            elif act == "reload":
                if body.get('token') and digest(st.song_path.read_bytes()) != body['token']:
                    raise ValueError('The external file changed again; compare it again before reloading')
                st.reload()
            elif act == 'export':
                st.request_export(body)
            elif act == 'cancelexport':
                st.cancel_export()
            elif act == "build":
                st.request_build(bool(body.get("render")))
            elif act == "stems":
                st.request_stems(body.get("fmt", "wav"), body.get("song", False), body.get("stems", True))
            else:
                return self._send(404, {"error": "unknown action"})
        except (KeyError, ValueError, IndexError, TypeError, AttributeError, OSError, SongError, OpenMPTError, struct.error) as e:
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})  # a bad request is answered, never dropped
        self._send(200, {"ok": True})


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False  # on Windows SO_REUSEADDR would let a second app take a port the first still listens on

    def handle_error(self, request, client_address):
        """A page that went away mid-answer (closed, reloaded, a seek that cancelled a request) is no error to print."""
        if not isinstance(sys.exc_info()[1], ConnectionError):
            _log.exception("A request from %s failed", client_address[0])


def make_server(port=0):
    """The HTTP server on `port`; 0 means PORT when it is free (a second app window gets any free port)."""
    if not port:
        try:
            return _Server(("127.0.0.1", PORT), Handler)
        except OSError:
            pass
    return _Server(("127.0.0.1", port), Handler)


def no_webview2():
    """True when pywebview would draw the window with Internet Explorer (Windows without the WebView2 runtime): that
    engine cannot run the page (no CSS variables, no modern script), so the app opens in the browser instead."""
    if sys.platform != "win32":
        return False
    try:
        from webview.platforms import winforms
    except Exception:
        return False
    return getattr(winforms, "renderer", "") == "mshtml"


WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def serve(song_path=None, port=0, open_browser=True, window=True):
    """Serve the UI. With pywebview installed (and `window`), it opens in a native window; else the default
    browser. `song_path` may be None: the UI then starts on its open-a-song screen."""
    start_log()
    for p in LOCKS.glob("*.lock"):  # left by sessions that ended (the system let go of their locks)
        f = lock_file(p)
        if f:
            unlock_file(f)
            try:
                p.unlink()
            except OSError:  # another app window took it this moment
                pass
    if song_path:
        Handler.open_song(song_path)
    srv = make_server(port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    agent.announce(srv.server_address[1])
    if window:
        try:
            import webview
        except ImportError:
            webview = None
        if webview and no_webview2():
            msg = (f"This PC lacks Microsoft's WebView2 runtime, so VultureTracker opened in your browser:\n{url}\n\n"
                   f"Install WebView2 for the app window (free, from Microsoft):\n{WEBVIEW2_URL}\n\n"
                   "Click OK to quit VultureTracker.")
            print(msg)
            webbrowser.open(url)
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, f"VultureTracker {__version__}", 0x40)  # the windowed exe's way to quit
            return 0
        if webview:
            Handler.window = webview.create_window(f"VultureTracker {__version__}", url, width=1400, height=900, min_size=(1000, 600), background_color="#0a0c0d")
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
