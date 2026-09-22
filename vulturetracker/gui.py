"""`vulturetracker gui song.yaml`: a one-page tryout app served on localhost from the stdlib HTTP server.

The page (gui.html) polls /api/state and posts actions; renders run on one worker thread and land as WAVs in
`<song dir>/.tryout/`, keyed by song text + slot + section + muted channels + candidate, so re-picking a candidate is
instant.
Ratings, notes and the candidate list live in `<song>.tryout.json` beside the song, per slot."""
import difflib
import glob
import hashlib
import json
import math
import os
import queue
import re
import sys
import threading
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from . import api
from .notation import format_cell, format_note
from .song import SongError, load_song_text
from .wavload import read_wav

HTML = Path(__file__).with_name("gui.html")
RATE = 44100
# the checkout (for the demo list); a frozen exe looks beside itself and one level up (dist/ in a checkout)
ROOT = Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
RECENT = Path(os.environ.get("APPDATA", Path.home())) / "VultureTracker" / "recent.json"
OLD_RECENT = RECENT.parent.with_name("TrackerForge") / "recent.json"  # the app's previous name


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


def facts_of(mod, warnings):
    rows_per_bar = mod.row_highlight[1] or 16
    orders = []
    use = []  # per order: per channel: sorted sample numbers triggered
    # order timing comes from libopenmpt, so speed, tempo, break and jump effects count; an order that playback
    # never reaches lasts 0 s
    from .itwriter import write_it
    from .openmpt import LoadedModule
    with LoadedModule(write_it(mod)) as lm:
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
        orders.append({"pattern": pat.name, "index": o, "rows": len(pat.rows), "bars": len(pat.rows) / rows_per_bar, "start": start, "seconds": secs})
        use.append([sorted(s) for s in per_ch])
    return {
        "title": mod.title, "tempo": mod.tempo, "speed": mod.speed, "bpm": round(mod.tempo * 24 / mod.speed / 4),
        "channels": [c.name or f"Ch {i + 1}" for i, c in enumerate(mod.channels)],
        "pan": [c.pan for c in mod.channels], "volume": [c.volume for c in mod.channels],
        "patterns": len(mod.patterns), "duration": duration, "orders": orders, "use": use,
        "samples": [{"num": i + 1, "name": s.name, "c5_speed": s.c5_speed, "length": s.length / s.c5_speed if s.c5_speed else 0,
                     "loop": s.loop is not None, "bits": s.bits} for i, s in enumerate(mod.samples)],
        "warnings": warnings,
    }


def mute_channels(song, idx):
    """Flag channel indices `idx` muted in a song dict (in place): the IT channel-disable bit, which libopenmpt honours."""
    chans = song["module"]["channels"]
    if isinstance(chans, int):
        chans = song["module"]["channels"] = [{} for _ in range(chans)]
    for i in idx:
        if i < len(chans):
            chans[i] = {**(chans[i] or {}), "muted": True}
    return song


# ---------------------------------------------------------------- state

class State:
    def __init__(self, song_path):
        self.song_path = Path(song_path).resolve()
        self.base_dir = self.song_path.parent
        self.cache_dir = self.base_dir / ".tryout"
        self.cache_dir.mkdir(exist_ok=True)
        self.meta_path = self.song_path.with_name(self.song_path.stem + ".tryout.json")
        self.meta = {"slot": 1, "orders": None, "candidates": {}, "ratings": {}, "muted": [], "solo": None}
        if self.meta_path.exists():
            self.meta.update(json.loads(self.meta_path.read_text(encoding="utf-8")))
        self.lock = threading.RLock()
        self.jobs = queue.Queue()
        self.renders = {}     # cache key -> {"status", "error", "file"}
        self.meas = {}        # wav path -> measurement (memo)
        self.build = None     # last build/export result
        self.stems = None     # stems export progress
        self.error = None
        self.text = ""
        self.mtime = 0.0
        self.facts = None
        self.mod = None       # compiled model of the last good load (pattern view)
        self.reload()
        threading.Thread(target=self._worker, daemon=True).start()

    # ---- song

    def reload(self):
        with self.lock:
            self.text = self.song_path.read_text(encoding="utf-8")
            self.mtime = self.song_path.stat().st_mtime
            try:
                self.mod, warnings = load_song_text(self.text, self.base_dir, str(self.song_path))
                self.facts = facts_of(self.mod, warnings)
                self.error = None
            except SongError as e:
                self.error = e.errors
            self.song = api.from_yaml(self.text)
            self.meas = {}
            files = self.files = [str((self.base_dir / v["file"]).resolve()) for v in (self.song.get("samples") or {}).values()
                     if isinstance(v, dict) and v.get("file")]
            threading.Thread(target=lambda: [self.measured(f) for f in files if Path(f).exists()], daemon=True).start()
            if self.meta["slot"] not in self.song.get("samples", {}):
                self.meta["slot"] = min(self.song.get("samples", {1: 0}))
            self.queue_all()

    def dirty(self):
        try:
            return self.song_path.stat().st_mtime != self.mtime
        except OSError:
            return False

    def save_meta(self):
        self.meta_path.write_text(json.dumps(self.meta, indent=1), encoding="utf-8")

    # ---- candidates

    @property
    def slot(self):
        return self.meta["slot"]

    @property
    def orders(self):
        o = self.meta.get("orders")
        return tuple(o) if o else None

    def cands(self):
        return self.meta["candidates"].setdefault(str(self.slot), [])

    def current_file(self):
        f = self.song["samples"][self.slot].get("file")
        return str((self.base_dir / f).resolve()) if f else None

    def silenced(self):
        """Channel indices muted in tryout renders: all but the solo channel, else the muted set."""
        if self.meta.get("solo") is not None and self.facts:
            return [i for i in range(len(self.facts["channels"])) if i != self.meta["solo"]]
        return sorted(set(self.meta.get("muted") or []))

    def key(self, cand):
        """Render cache key: song text, slot, section, mutes, the candidate, and the stamp of every WAV in the mix (a
        sample re-rendered in place under the same path must not serve the old mix)."""
        def stamp(f):
            try:
                st = Path(f).stat()
                return f"{f}={st.st_mtime}:{st.st_size}"
            except OSError:
                return f"{f}=missing"
        stamps = "|".join(stamp(f) for f in [cand, *self.files])
        return hashlib.sha1(f"{self.text}|{self.slot}|{self.orders}|{self.silenced()}|{stamps}".encode()).hexdigest()[:16]

    def measured(self, path):
        if path not in self.meas:
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
            for c in self.cands():
                k = self.key(c)
                if k not in self.renders:
                    f = self.cache_dir / f"{k}.wav"
                    if f.exists():
                        self.renders[k] = {"status": "ready", "file": str(f), "error": None}
                    else:
                        self.renders[k] = {"status": "queued", "file": str(f), "error": None}
                        self.jobs.put((k, c))

    def retry(self, path):
        with self.lock:
            k = self.key(path)
            self.renders[k] = {"status": "queued", "file": str(self.cache_dir / f"{k}.wav"), "error": None}
            self.jobs.put((k, path))

    def _worker(self):
        while True:
            job = self.jobs.get()
            if job[0] == "build":
                self._build(job[1])
                continue
            if job[0] == "stems":
                self._stems()
                continue
            k, cand = job
            with self.lock:
                if self.renders.get(k, {}).get("status") != "queued":
                    continue
                if self.key(cand) != k:  # settings changed since queueing; queue_all has queued the current key
                    self.renders.pop(k, None)
                    continue
                self.renders[k]["status"] = "rendering"
                base = mute_channels(api.tryout_song(self.song_path, self.orders), self.silenced())
                slot = self.slot
            try:
                pcm = api.tryout_render(base, slot, cand, self.base_dir, RATE)
                out = self.cache_dir / f"{k}.wav"
                with wave.open(str(out), "wb") as f:
                    f.setnchannels(2)
                    f.setsampwidth(2)
                    f.setframerate(RATE)
                    f.writeframes(pcm)
                with self.lock:
                    self.renders[k].update(status="ready", file=str(out))
            except Exception as e:  # noqa: BLE001 - shown in the UI, worker must survive
                with self.lock:
                    self.renders[k].update(status="failed", error=f"{type(e).__name__}: {e}")

    # ---- apply

    def patched_text(self, cand):
        """Song text with the slot pointed at `cand`. The slot's own lines are re-dumped in their original layout (a
        one-line flow mapping or an indented block) and the rest of the document, comments included, is untouched; only
        when the slot's lines cannot be found is the whole song re-dumped (comments lost, so the diff says so)."""
        import copy
        song = copy.deepcopy(self.song)
        entry = api.swap_sample(song, self.slot, cand)
        entry["file"] = os.path.relpath(cand, self.base_dir).replace(os.sep, "/")
        lines = self.text.splitlines(keepends=True)
        in_samples = False
        for i, line in enumerate(lines):
            if re.match(r"^\S", line):
                in_samples = line.startswith("samples:")
                continue
            m = in_samples and re.match(rf"^(\s+){self.slot}:(\s*)(\{{.*\}})?\s*$", line)
            if not m:
                continue
            indent = m.group(1)
            if m.group(3):
                flow = yaml.safe_dump(entry, default_flow_style=True, width=10 ** 6, sort_keys=False).strip()
                lines[i] = f"{indent}{self.slot}:{m.group(2)}{flow}{'\n' if line.endswith('\n') else ''}"
                return "".join(lines), False
            j = i + 1  # the block is the following lines indented deeper than the key
            while j < len(lines) and lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) > len(indent):
                j += 1
            block = yaml.safe_dump(entry, default_flow_style=False, width=10 ** 6, sort_keys=False)
            lines[i:j] = [line] + [f"{indent}  {b}\n" for b in block.splitlines()]
            return "".join(lines), False
        return api.to_yaml(song), True

    def diff(self, cand):
        new, redump = self.patched_text(cand)
        d = list(difflib.unified_diff(self.text.splitlines(), new.splitlines(), str(self.song_path.name), str(self.song_path.name), lineterm="", n=2))
        return {"lines": d, "redump": redump, "path": str(self.song_path)}

    def apply(self, cand):
        with self.lock:
            new, _ = self.patched_text(cand)
            self.song_path.write_text(new, encoding="utf-8")
            self.reload()
        self.jobs.put(("build", False))

    # ---- build / export

    def request_build(self, render):
        with self.lock:
            self.build = {"status": "queued", "render": render}
        self.jobs.put(("build", render))

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

    def request_stems(self):
        with self.lock:
            self.stems = {"status": "queued", "done": 0, "total": 0, "dir": None, "error": None}
        self.jobs.put(("stems", None))

    def _stems(self):
        """One WAV per channel that plays anything, rendered with every other channel muted, in <song>_stems/."""
        with self.lock:
            f = self.facts
            out_dir = self.song_path.with_name(self.song_path.stem + "_stems")
            chans = [i for i in range(len(f["channels"])) if any(u[i] for u in f["use"])] if f else []
            self.stems = {"status": "rendering", "done": 0, "total": len(chans), "dir": str(out_dir), "error": None}
        try:
            out_dir.mkdir(exist_ok=True)
            for n, i in enumerate(chans):
                name = re.sub(r"[^\w-]+", "_", f["channels"][i]).strip("_") or "ch"
                song = mute_channels(api.tryout_song(self.song_path), [j for j in range(len(f["channels"])) if j != i])
                api.render(song, out_dir / f"{i + 1:02d}-{name}.wav", rate=RATE, base_dir=self.base_dir)
                with self.lock:
                    self.stems["done"] = n + 1
            with self.lock:
                self.stems["status"] = "done"
        except (SongError, OSError, ValueError) as e:
            with self.lock:
                self.stems.update(status="failed", error="\n".join(getattr(e, "errors", []) or [str(e)]))

    # ---- pattern view

    def pattern_rows(self, index):
        """One pattern as read-only tracker rows; each cell in the 'C-5 01 v64 A06' layout libopenmpt prints."""
        pat = self.mod.patterns[index]
        return {"name": pat.name, "index": index, "rows": [[format_cell(c) for c in row] for row in pat.rows]}

    # ---- snapshot for the page

    def snapshot(self):
        with self.lock:
            slot = self.slot
            entry = self.song["samples"].get(slot, {})
            cur = self.current_file()
            ref = self.measured(cur) if cur and Path(cur).exists() else None
            cands = []
            for i, c in enumerate(self.cands()):
                k = self.key(c)
                r = self.renders.get(k, {"status": "queued", "file": None, "error": None})
                m = self.measured(c) if Path(c).exists() else {"error": "file not found"}
                rating = self.meta["ratings"].get(c, {})
                cands.append({"id": i, "path": c, "name": Path(c).stem, "src": os.path.relpath(c, self.base_dir).replace(os.sep, "/"),
                              "key": k, "status": r["status"], "error": r.get("error"), "meas": m,
                              "dist": distance(m, ref), "stars": rating.get("stars", 0), "rejected": rating.get("rejected", False),
                              "note": rating.get("note", ""), "current": c == cur})
            ents = self.song.get("samples", {})
            slot_meas = {}  # per slot: the three numbers the overview table shows (memoised per WAV)
            for k, v in ents.items():
                f = (self.base_dir / v["file"]).resolve() if isinstance(v, dict) and v.get("file") else None
                m = self.meas.get(str(f)) if f else None  # filled in by the warm-up thread; blank until then
                if m:
                    slot_meas[str(k)] = {x: m.get(x) for x in ("pitch", "centroid", "decay")}
            return {
                "song": {"path": str(self.song_path), "dir": str(self.base_dir), "dirty": self.dirty(), "error": self.error,
                         "mtime": self.mtime, "facts": self.facts, "sample_entries": {str(k): v for k, v in ents.items()},
                         "slot_meas": slot_meas},
                "slot": slot, "slot_entry": entry, "slot_file": cur, "ref": ref,
                "orders": list(self.orders) if self.orders else None,
                "muted": sorted(set(self.meta.get("muted") or [])), "solo": self.meta.get("solo"),
                "candidates": cands, "build": self.build, "stems": self.stems,
                "queue": sum(1 for r in self.renders.values() if r["status"] in ("queued", "rendering")),
                "cache": sum(1 for r in self.renders.values() if r["status"] == "ready"),
            }


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    state: State = None
    window = None  # pywebview window, when the UI runs in one

    @classmethod
    def open_song(cls, path):
        cls.state = State(path)
        remember_song(cls.state.song_path)

    @classmethod
    def browse(cls):
        """Native file dialog, returning the chosen song path or None."""
        if cls.window is not None:
            import webview
            r = cls.window.create_file_dialog(webview.OPEN_DIALOG, file_types=("Song files (*.yaml;*.yml)", "All files (*.*)"))
            return r[0] if r else None
        from tkinter import Tk, filedialog
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        r = filedialog.askopenfilename(parent=root, title="VultureTracker: open a song", filetypes=[("Song files", "*.yaml *.yml"), ("All files", "*")])
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
        if not p.exists():
            return self._send(404, {"error": "not found"})
        data = p.read_bytes()
        start, end = 0, len(data) - 1
        rng = self.headers.get("Range")
        code = 200
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a or 0)
            end = int(b) if b else end
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.end_headers()
        self.wfile.write(data[start:end + 1])

    def do_GET(self):
        st = self.state
        path = self.path.split("?")[0]
        if path == "/":
            return self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if path == "/icon.png":
            return self._send(200, HTML.with_name("icon.png").read_bytes(), "image/png")
        if path == "/api/state":
            return self._send(200, st.snapshot() if st else start_snapshot())
        if path == "/api/start":
            return self._send(200, start_snapshot())
        if st is None:
            return self._send(404, {"error": "no song open"})
        if path.startswith("/api/pattern/"):
            try:
                return self._send(200, st.pattern_rows(int(path[13:])))
            except (ValueError, IndexError, AttributeError):
                return self._send(404, {"error": "no such pattern"})
        if path.startswith("/wav/"):
            k = path[5:]
            r = st.renders.get(k)
            return self._send_file(r["file"], "audio/wav") if r and r["status"] == "ready" else self._send(404, {"error": "not rendered"})
        if path.startswith("/raw/"):
            try:
                c = st.cands()[int(path[5:])]
            except (ValueError, IndexError):
                return self._send(404, {"error": "no such candidate"})
            return self._send_file(c, "audio/wav")
        if path.startswith("/api/diff/"):
            return self._send(200, st.diff(st.cands()[int(path[10:])]))
        self._send(404, {"error": "not found"})

    def do_POST(self):
        st = self.state
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        act = self.path.rsplit("/", 1)[-1]
        try:
            if act == "open":
                self.open_song(body["path"])
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
            elif act == "retry":
                st.retry(st.cands()[int(body["id"])])
            elif act == "apply":
                st.apply(st.cands()[int(body["id"])])
            elif act == "reload":
                st.reload()
            elif act == "build":
                st.request_build(bool(body.get("render")))
            elif act == "stems":
                st.request_stems()
            else:
                return self._send(404, {"error": "unknown action"})
        except (KeyError, ValueError, IndexError, OSError, SongError) as e:
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})
        self._send(200, {"ok": True})


def serve(song_path=None, port=0, open_browser=True, window=True):
    """Serve the UI. With pywebview installed (and `window`), it opens in a native window; else the default
    browser. `song_path` may be None: the UI then starts on its open-a-song screen."""
    if song_path:
        Handler.open_song(song_path)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if window:
        try:
            import webview
        except ImportError:
            webview = None
        if webview:
            Handler.window = webview.create_window("VultureTracker", url, width=1400, height=900, min_size=(1000, 600), background_color="#0a0c0d")
            webview.start()
            return 0
    print(f"VultureTracker GUI: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0
