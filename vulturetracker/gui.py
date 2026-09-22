"""`vulturetracker gui song.yaml`: a one-page tryout app served on localhost from the stdlib HTTP server.

The page (gui.html) polls /api/state and posts actions; renders run on one worker thread and land as WAVs in
`<song dir>/.tryout/`. The tryout section is compiled once per candidate (memoised); mutes, solo and the mixer's
faders (channel volume and pan, mix volume, sample gain) are patched into that module's header before each render, so
re-picking a candidate is instant and a fader move costs one render.
Ratings, notes, the candidate list, mutes and the unwritten mix live in `<song>.tryout.json` beside the song.
Listening notes (a tag dropped at the playhead, the channels sounding there, the listener's words) live in
`<song>.notes.json` and are rendered as `<song>.notes.md`, a report for a collaborator who cannot listen."""
import datetime
import difflib
import glob
import hashlib
import itertools
import json
import math
import os
import queue
import re
import struct
import sys
import threading
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from . import api
from .notation import format_cell, format_note
from .openmpt import LoadedModule
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
        "pan": [c.pan for c in mod.channels], "volume": [c.volume for c in mod.channels], "mix_volume": mod.mix_volume,
        "patterns": len(mod.patterns), "duration": duration, "orders": orders, "use": use,
        "samples": [{"num": i + 1, "name": s.name, "c5_speed": s.c5_speed, "length": s.length / s.c5_speed if s.c5_speed else 0,
                     "loop": s.loop is not None, "bits": s.bits} for i, s in enumerate(mod.samples)],
        "warnings": warnings,
    }


# ---------------------------------------------------------------- listening notes

def sounding_table(mod, facts):
    """Per order of `facts` (the playable orders, in order) and per row of its pattern: the channels sounding there. A
    forward pass carries each channel's last note (the sample through the instrument's keymap, the note, the order and row
    it started at, whether the sample loops); a note-off/cut/fade drops it, and a one-shot sample drops out once its
    length has played at that order's row rate. A note without an instrument keeps the channel's last instrument (a slide
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
                smp = ins
                if mod.instruments is not None:
                    smp = mod.instruments[ins - 1].keymap[c.note][1] if 0 < ins <= len(mod.instruments) else 0
                ok = 0 < smp <= len(mod.samples)
                state[ch] = {"ch": ch, "name": mod.channels[ch].name or f"Ch {ch + 1}", "sample": smp if ok else None, "note": format_note(c.note),
                             "order": oi, "loop": ok and mod.samples[smp - 1].loop is not None, "abs": abs_row + r, "secs": secs[smp - 1] if ok else None}
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
    """Each channel soloed (every other channel's header volume zeroed, the way scratch/ut99-clean/compare.py measures a
    module): RMS in dB over the whole render and over its active half-seconds, plus those seconds. Needs numpy.
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


def _write_pcm(path, pcm):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(pcm)


def _peak(pcm):
    """Peak of interleaved int16 PCM, 0..1 (1.0: libopenmpt's mixer clipped)."""
    try:
        import numpy as np
        return round(float(np.abs(np.frombuffer(pcm, "<i2")).max()) / 32768, 3)
    except (ImportError, ValueError):
        return None


# ---------------------------------------------------------------- state

class State:
    def __init__(self, song_path):
        self.song_path = Path(song_path).resolve()
        self.base_dir = self.song_path.parent
        self.cache_dir = self.base_dir / ".tryout"
        self.cache_dir.mkdir(exist_ok=True)
        self.meta_path = self.song_path.with_name(self.song_path.stem + ".tryout.json")
        self.meta = {"slot": 1, "orders": None, "candidates": {}, "ratings": {}, "muted": [], "solo": None, "mix": {}}
        if self.meta_path.exists():
            self.meta.update(json.loads(self.meta_path.read_text(encoding="utf-8")))
        self.notes_path = self.song_path.with_name(self.song_path.stem + ".notes.json")
        self.notes = json.loads(self.notes_path.read_text(encoding="utf-8")) if self.notes_path.exists() else []
        self.lock = threading.RLock()
        self.jobs = queue.PriorityQueue()  # (priority, sequence, job): what is playing first, then the song, the rest, meters last
        self._seq = itertools.count()
        self.want = None      # the candidate the page is listening to (None: the song itself), rendered first
        self.sound_table = None  # per order per row: the channels sounding there (sounding_table), rebuilt on reload
        self.renders = {}     # render key -> {"status", "error", "file", "peak"}
        self.compiled = {}    # compile key -> .it bytes of the tryout section (a candidate swapped in), patched per render
        self.meters = None    # soloed channel levels of the section with the unwritten mix applied
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

    def reload(self, archive=True):
        """Re-read the song. `archive`: notes made against another version of the song text move to their archive
        (the song changed outside the app: a rebuild); the app's own writes pass False, so a slot write mid-session
        keeps the notes."""
        with self.lock:
            raw = self.song_path.read_bytes()
            self.crlf = b"\r\n" in raw
            self.text = raw.decode("utf-8").replace("\r\n", "\n")
            self.mtime = self.song_path.stat().st_mtime
            try:
                self.mod, warnings = load_song_text(self.text, self.base_dir, str(self.song_path))
                self.facts = facts_of(self.mod, warnings)
                self.sound_table = None
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
        self.meta_path.write_text(json.dumps(self.meta, indent=1), encoding="utf-8")

    def write_song(self, text):
        """The song file, written with the line endings it had (write_text would turn every LF into CRLF on Windows)."""
        self.song_path.write_bytes(text.replace("\n", "\r\n" if self.crlf else "\n").encode("utf-8"))

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

    def mix(self):
        """The unwritten mix: {"volume": {ch: 0-64}, "pan": {ch: 0-64|surround}, "mix_volume": 0-128, "sample_volume": {slot: 0-64}}
        (keys are strings: the meta round-trips through JSON)."""
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
        with self.lock:
            self.meta["mix"] = mix
            self.save_meta()
            self.queue_all()

    def ckey(self, cand=None):
        """Compile key: song text, slot, section, the candidate swapped in (None: the song as it is) and the stamp of every
        WAV in the mix (a sample re-rendered in place under the same path must not serve the old mix)."""
        def stamp(f):
            try:
                st = Path(f).stat()
                return f"{f}={st.st_mtime}:{st.st_size}"
            except OSError:
                return f"{f}=missing"
        stamps = "|".join(stamp(f) for f in ([cand] if cand else []) + self.files)
        return hashlib.sha1(f"{self.text}|{self.slot}|{self.orders}|{stamps}".encode()).hexdigest()[:16]

    def key(self, cand=None):
        """Render cache key: the compile key plus what is patched into the module's header, mutes and the unwritten mix."""
        return hashlib.sha1(f"{self.ckey(cand)}|{self.silenced()}|{json.dumps(self.mix(), sort_keys=True)}".encode()).hexdigest()[:16]

    def meter_key(self):
        return hashlib.sha1(f"{self.ckey()}|{json.dumps(self.mix(), sort_keys=True)}".encode()).hexdigest()[:16]

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

    def compiled_it(self, cand=None):
        """The tryout section compiled with `cand` in the slot (None: the song as it is), memoised per compile key."""
        ck = self.ckey(cand)
        if ck not in self.compiled:
            with self.lock:
                base, slot = api.tryout_song(self.song, self.orders), self.slot
            if cand:
                api.swap_sample(base, slot, Path(cand).resolve())
            it = api.compile_song(base, self.base_dir)[0]
            while len(self.compiled) >= 8:
                self.compiled.pop(next(iter(self.compiled)))
            self.compiled[ck] = it
        return self.compiled[ck]

    def retry(self, path):
        with self.lock:
            k = self.key(path)
            self.renders[k] = {"status": "queued", "file": str(self.cache_dir / f"{k}.wav"), "error": None}
            self._put(1, (k, path))

    def _worker(self):
        while True:
            job = self.jobs.get()[2]
            if job[0] == "build":
                self._build(job[1])
                continue
            if job[0] == "stems":
                self._stems()
                continue
            if job[0] == "meters":
                self._meters(job[1])
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

    # ---- listening notes

    def version(self):
        """The song text the notes were made against: a short hash of the file and its modification time."""
        return {"hash": hashlib.sha1(self.text.encode()).hexdigest()[:8],
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
                    "time": round(o["start"] + o["seconds"] * row / o["rows"], 2),
                    "tag": str(body.get("tag") or "note")[:40], "text": str(body.get("text") or "")[:2000],
                    "channels": sorted({int(c) for c in body.get("channels") or []}),
                    "sounding": self.sounding(order, row),
                    "playing": {"source": str(body.get("source") or "song"), "candidate": body.get("candidate"), "slot": self.slot,
                                "section": list(self.orders) if self.orders else None, "muted": self.silenced(), "mix": self.mix()}}
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
        self.notes_path.write_text(json.dumps(self.notes, indent=1), encoding="utf-8")
        self.notes_path.with_suffix(".md").write_text(self.report(), encoding="utf-8")

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
            kept = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
            seen = {(n["id"], n.get("when")) for n in kept}
            kept += [n for n in batch if (n["id"], n.get("when")) not in seen]
            p.write_text(json.dumps(kept, indent=1), encoding="utf-8")
            p.with_suffix(".md").write_text(self.report(kept, batch[0].get("version")), encoding="utf-8")
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
            o = f["orders"][order] if f and order < len(f["orders"]) else None
            L += [f"## ord {order} `{o['pattern']}` ({fmt(o['start'])} to {fmt(o['start'] + o['seconds'])})" if o else f"## ord {order}", ""]
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
                if p.get("mix"):
                    what += ", unwritten faders " + json.dumps(p["mix"], separators=(",", ":"))
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

    ENTRY = r"^(\s+)({key})([ \t]*)(\{{.*\}})?([ \t]*(?:#.*)?)$"  # indent, key, spaces, one-line flow mapping, trailing comment

    @staticmethod
    def _redump(lines, i, m, entry, keys=None):
        """Replace the mapping at line i (`m` matched ENTRY) with `entry` in its own layout: a one-line flow mapping stays
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

    def _edit_text(self, song, samples=(), channels=(), mix_volume=None, keys=None):
        """Song text with sample slot entries `{slot: entry}`, channel entries `{index: entry}` and the module's mix_volume
        written in place (`keys`: only those scalar keys change inside a one-line entry); the rest of the document,
        comments included, is untouched. When a line cannot be found (a one-line `module:`, a block-style channel list)
        the whole `song` dict is re-dumped instead (comments lost, so the diff says so). Returns (text, redumped)."""
        samples, channels = dict(samples), dict(channels)
        lines = self.text.splitlines(keepends=True)
        pending = {("smp", k) for k in samples} | {("ch", k) for k in channels} | ({("mv",)} if mix_volume is not None else set())
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
                m = re.match(self.ENTRY.format(key=r"\d+:"), line)
                if m and int(m.group(2)[:-1]) in samples:
                    n = self._redump(lines, i, m, samples[int(m.group(2)[:-1])], keys)
                    pending.discard(("smp", int(m.group(2)[:-1])))
            elif section == "module":
                if s.startswith("channels:"):
                    sub, item, cind = "ch", -1, ind
                elif sub == "ch" and ind >= cind and s.startswith("-"):
                    item += 1
                    m = re.match(self.ENTRY.format(key="-"), line)
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
        """Song text with the unwritten mix written in: module.channels volume/pan, module.mix_volume and the samples'
        global_volume (the default note volume would be overridden by every cell that sets one)."""
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
        return self._edit_text(song, samples=smp, channels=touched, mix_volume=mix.get("mix_volume"), keys=("volume", "pan", "global_volume"))

    def _diff(self, new, redump):
        d = list(difflib.unified_diff(self.text.splitlines(), new.splitlines(), self.song_path.name, self.song_path.name, lineterm="", n=2))
        return {"lines": d, "redump": redump, "path": str(self.song_path)}

    def diff(self, cand):
        return self._diff(*self.patched_text(cand))

    def mix_diff(self):
        return self._diff(*self.mix_text())

    def apply(self, cand):
        with self.lock:
            new, _ = self.patched_text(cand)
            self.write_song(new)
            self.reload(archive=False)
        self._put(0, ("build", False))

    def apply_mix(self):
        with self.lock:
            new, _ = self.mix_text()
            self.write_song(new)
            self.meta["mix"] = {}
            self.save_meta()
            self.reload(archive=False)
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

    def request_stems(self):
        with self.lock:
            self.stems = {"status": "queued", "done": 0, "total": 0, "dir": None, "error": None}
        self._put(0, ("stems", None))

    def _stems(self):
        """One WAV per channel that plays anything, rendered with every other channel disabled, in <song>_stems/. The song
        as written: the unwritten mix is not applied."""
        with self.lock:
            f = self.facts
            out_dir = self.song_path.with_name(self.song_path.stem + "_stems")
            chans = [i for i in range(len(f["channels"])) if any(u[i] for u in f["use"])] if f else []
            self.stems = {"status": "rendering", "done": 0, "total": len(chans), "dir": str(out_dir), "error": None}
        try:
            out_dir.mkdir(exist_ok=True)
            it = api.compile_song(self.song, self.base_dir)[0]
            for n, i in enumerate(chans):
                name = re.sub(r"[^\w-]+", "_", f["channels"][i]).strip("_") or "ch"
                with LoadedModule(patch_it(it, [j for j in range(len(f["channels"])) if j != i])) as lm:
                    _write_pcm(out_dir / f"{i + 1:02d}-{name}.wav", lm.render(RATE))
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
                              "key": k, "status": r["status"], "error": r.get("error"), "peak": r.get("peak"), "meas": m,
                              "dist": distance(m, ref), "stars": rating.get("stars", 0), "rejected": rating.get("rejected", False),
                              "note": rating.get("note", ""), "current": c == cur})
            ents = self.song.get("samples", {})
            slot_meas = {}  # per slot: the three numbers the overview table shows (memoised per WAV)
            for k, v in ents.items():
                f = (self.base_dir / v["file"]).resolve() if isinstance(v, dict) and v.get("file") else None
                m = self.meas.get(str(f)) if f else None  # filled in by the warm-up thread; blank until then
                if m:
                    slot_meas[str(k)] = {x: m.get(x) for x in ("pitch", "centroid", "decay")}
            ok = self.key()
            own = self.renders.get(ok, {"status": "queued", "error": None})
            return {
                "song": {"path": str(self.song_path), "dir": str(self.base_dir), "dirty": self.dirty(), "error": self.error,
                         "mtime": self.mtime, "facts": self.facts, "sample_entries": {str(k): v for k, v in ents.items()},
                         "slot_meas": slot_meas},
                "slot": slot, "slot_entry": entry, "slot_file": cur, "ref": ref,
                "orders": list(self.orders) if self.orders else None,
                "muted": sorted(set(self.meta.get("muted") or [])), "solo": self.meta.get("solo"),
                "own": {"key": ok, "status": own["status"], "error": own.get("error"), "peak": own.get("peak")},
                "mix": self.mix(), "meters": self.meters,
                "candidates": cands, "build": self.build, "stems": self.stems,
                "cand_counts": {k: len(v) for k, v in self.meta["candidates"].items() if v},
                "notes": self.notes, "notes_path": str(self.notes_path), "version": self.version(),
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
        if path.startswith("/api/sounding/"):
            try:
                return self._send(200, {"rows": st.sounding_rows(int(path[14:]))})
            except (ValueError, IndexError, AttributeError, TypeError):
                return self._send(404, {"error": "no such order"})
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
        if path == "/api/mixdiff":
            return self._send(200, st.mix_diff())
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
            elif act == "applymix":
                st.apply_mix()
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
