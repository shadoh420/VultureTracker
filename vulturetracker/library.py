"""Sample discovery (numpy): a feature index of the WAVs under a few folders, the nearest sounds by timbre, and a 2D
map of the library (Samplebrain, AudioStellar and FluCoMa as ideas, nothing of theirs copied).

Each WAV gets one vector: the mean and spread of 12 MFCCs (a 40-band log-mel spectrum folded by a DCT, loudness
coefficient left out), the spectral centroid, the flatness, the attack time, the duration, the pitch (dsp.pitch_of) and,
for a pitched sound, the levels of its first eight harmonics (a timbre measure that does not move with the pitch).
The index is one JSON file holding every file's stamp (mtime and size), vector and a few readable numbers, so a new scan
reads only files that are new or changed. Distances weigh groups of features (timbre first) on the library's own
spread of each feature; the map is the first two principal components of the same weighted vectors."""
import json
import math
import os
import struct
import sys
import threading
import time
from pathlib import Path

import numpy as np

# the checkout (a frozen exe: one level above its folder, dist/ in a checkout), whose samples/ and tools/cc0 are indexed
# when no folders were chosen
ROOT = (Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent)
VERSION = 2            # bump when the vector changes: every file is read again
MAX_SECONDS = 10.0     # what is analysed of a longer file (its start)
N_MFCC, N_MELS = 13, 40
# the vector's layout: name -> slice; the groups' weights sum the squared distance a group can add (in library z-scores)
LAYOUT = {"mfcc_mean": slice(0, 12), "mfcc_std": slice(12, 24), "centroid": slice(24, 25), "flatness": slice(25, 26),
          "attack": slice(26, 27), "duration": slice(27, 28), "pitch": slice(28, 29), "harmonics": slice(29, 37)}
SIZE = 37
N_HARM = 8
# set on the families of tests/test_library.py (sine, saw, square, noise, kick, hat, pad; six members each over four
# octaves and 0.25-2 s): of the three nearest, 0.62 were of the same family with the MFCCs, centroid, flatness, attack
# and duration (1.0) alone, 0.84 with the harmonics, 0.90 with these weights
WEIGHTS = {"mfcc_mean": 4.0, "mfcc_std": 2.5, "centroid": 1.5, "flatness": 1.0, "attack": 1.0, "duration": 0.2}
TIMBRE_END = LAYOUT["pitch"].start   # the groups above: compared for every pair
HARM_WEIGHT = 5.0      # the harmonics' levels: compared when both sounds hold a pitch
PITCH_WEIGHT = 0.5     # per octave between two pitched sounds (capped at 2 octaves)
UNPITCHED = 1.0        # one pitched sound and one not


# ---------------------------------------------------------------- reading

def read_audio(path, max_seconds=None):
    """A WAV as (mono float64 array, rate, info) with numpy, reading only the first `max_seconds` of its data: PCM 8/16/24/32
    and float 32/64, WAVE_FORMAT_EXTENSIBLE, any channel count (averaged). info: frames (the whole file), channels, root
    (the smpl chunk's unity note or None)."""
    with open(path, "rb") as f:
        head = f.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise ValueError("not a RIFF/WAVE file")
        fmt = data = None
        root = None
        while True:
            h = f.read(8)
            if len(h) < 8:
                break
            cid, size = struct.unpack("<4sI", h)
            if cid == b"fmt ":
                fmt = f.read(size)
                f.seek(size & 1, 1)
            elif cid == b"data":
                data = (f.tell(), size)
                f.seek(size + (size & 1), 1)
            elif cid == b"smpl" and size >= 16:
                body = f.read(size)
                root = struct.unpack_from("<I", body, 12)[0]
                f.seek(size & 1, 1)
            else:
                f.seek(size + (size & 1), 1)
        if fmt is None or data is None or len(fmt) < 16:
            raise ValueError("missing fmt or data chunk")
        tag, nch, rate, _, align, bits = struct.unpack_from("<HHIIHH", fmt, 0)
        if tag == 0xFFFE and len(fmt) >= 26:
            tag = struct.unpack_from("<H", fmt, 24)[0]
        if tag not in (1, 3) or nch < 1 or align < nch or rate < 1:
            raise ValueError(f"unsupported WAV (format tag {tag}, {nch} channels)")
        width = align // nch
        frames = data[1] // align
        take = frames if max_seconds is None else min(frames, int(max_seconds * rate))
        f.seek(data[0])
        raw = f.read(take * align)
    take = len(raw) // align
    raw = raw[: take * align]
    if tag == 3:
        if width not in (4, 8):
            raise ValueError(f"unsupported float width {width * 8}")
        x = np.frombuffer(raw, "<f4" if width == 4 else "<f8").astype(np.float64)
    elif width == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float64) - 128) / 128
    elif width == 2:
        x = np.frombuffer(raw, "<i2") / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        x = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 8) / 8388608.0
    elif width == 4:
        x = np.frombuffer(raw, "<i4") / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width {width * 8} bits")
    x = x.reshape(-1, nch).mean(axis=1)
    return x, rate, {"frames": frames, "channels": nch, "root": root if root is not None and root < 120 else None}


# ---------------------------------------------------------------- features

def _mel(n_fft, rate, n_mels=N_MELS, fmin=30.0, fmax=11025.0):
    """A triangular mel filterbank (n_mels x bins) from fmin to fmax in Hz (bands past the file's Nyquist stay empty, so
    files at different rates compare on the same bands)."""
    def mel(f):
        return 2595 * np.log10(1 + f / 700)
    edges = 700 * (10 ** (np.linspace(mel(fmin), mel(fmax), n_mels + 2) / 2595) - 1)
    freqs = np.fft.rfftfreq(n_fft, 1 / rate)
    fb = np.zeros((n_mels, len(freqs)))
    for i in range(n_mels):
        lo, c, hi = edges[i], edges[i + 1], edges[i + 2]
        fb[i] = np.clip(np.minimum((freqs - lo) / (c - lo), (hi - freqs) / (hi - c)), 0, None)
    return fb


def _dct(n_out, n_in):
    k, n = np.arange(n_out)[:, None], np.arange(n_in)[None, :]
    m = np.cos(np.pi * k * (2 * n + 1) / (2 * n_in)) * np.sqrt(2 / n_in)
    m[0] /= np.sqrt(2)
    return m


def frames_of(x, rate):
    """The analysis frames: (power spectra frames x bins, n_fft, hop); a 46 ms Hann window, half overlapping."""
    n_fft = 1 << int(round(math.log2(max(64, 0.046 * rate))))
    hop = n_fft // 2
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    n = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    return np.abs(np.fft.rfft(x[idx] * np.hanning(n_fft), axis=1)) ** 2, n_fft, hop


def mel_frames(power, n_fft, rate):
    """Per frame: 40 log-mel levels (dB, floored 80 dB under the loudest) and the 13 MFCCs over them."""
    mel = power @ _mel(n_fft, rate).T
    db = 10 * np.log10(mel + 1e-12)
    db = np.maximum(db, db.max() - 80)
    return db, db @ _dct(N_MFCC, N_MELS).T


def harmonics(x, rate, hz, n=N_HARM):
    """Levels of harmonics 1..n of `hz`: dB under the strongest of them (floored at -60), each the peak within 3 % (at
    least a bin and a half) of its frequency, in one spectrum of the loudest half second (zero-padded to at least 8
    periods per bin, so a low note's harmonics fall in separate bins); a harmonic above Nyquist: -60."""
    size = min(len(x), int(0.5 * rate))
    ms = max(1, rate // 100)
    e = np.convolve(x * x, np.ones(size), mode="valid")[::ms] if len(x) > size else np.zeros(1)
    a = int(np.argmax(e)) * ms
    seg = x[a:a + size]
    nfft = 1 << int(math.ceil(math.log2(max(len(seg), 8 * rate / hz, 64))))
    power = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), nfft)) ** 2
    freqs = np.fft.rfftfreq(nfft, 1 / rate)
    width = max(1.5 * rate / nfft, 0)
    out = np.full(n, -200.0)
    for h in range(1, n + 1):
        sel = np.abs(freqs - h * hz) <= max(0.03 * h * hz, width)
        if sel.any() and h * hz < rate / 2:
            out[h - 1] = 10 * math.log10(power[sel].max() + 1e-20)
    return np.maximum(out - out.max(), -60.0)


def features(x, rate, frames=None):
    """The feature vector (SIZE floats; pitch NaN when the sound holds none) and readable numbers of a mono signal."""
    from . import dsp
    duration = (frames or len(x)) / rate
    info = {"duration": round(duration, 4), "rate": rate}
    vec = np.full(SIZE, np.nan)
    if not len(x) or not np.any(x):
        raise ValueError("silent")
    power, n_fft, hop = frames_of(x, rate)
    energy = power.sum(axis=1)
    loud = energy >= energy.max() * 1e-5          # frames within 50 dB of the loudest
    _, mfcc = mel_frames(power[loud], n_fft, rate)
    vec[LAYOUT["mfcc_mean"]] = mfcc[:, 1:].mean(axis=0)
    vec[LAYOUT["mfcc_std"]] = mfcc[:, 1:].std(axis=0)
    freqs = np.fft.rfftfreq(n_fft, 1 / rate)
    p = power[loud]
    centroid = float((p * freqs).sum() / max(p.sum(), 1e-20))
    flat = np.exp(np.log(p[:, 1:] + 1e-20).mean(axis=1)) / (p[:, 1:].mean(axis=1) + 1e-20)
    flatness = float(np.average(flat, weights=energy[loud]))
    ms = max(1, rate // 200)                        # a 5 ms RMS envelope: attack = from 10 % of its peak to 90 %
    env = np.sqrt(np.convolve(x * x, np.ones(ms) / ms, mode="same"))
    top = env.max()
    attack = (int(np.argmax(env >= 0.9 * top)) - int(np.argmax(env >= 0.1 * top))) / rate
    hz = dsp.pitch_of(x[: int(4 * rate)], rate)
    vec[LAYOUT["centroid"]] = math.log2(max(centroid, 20.0))
    vec[LAYOUT["flatness"]] = math.log10(max(flatness, 1e-6))
    vec[LAYOUT["attack"]] = math.log10(attack + 0.002)
    vec[LAYOUT["duration"]] = math.log10(max(duration, 0.01))
    info.update(centroid=round(centroid), flatness=round(flatness, 4), attack=round(attack, 4))
    if hz:
        note, cents = dsp.note_of(hz)
        vec[LAYOUT["pitch"]] = 69 + 12 * math.log2(hz / 440)
        vec[LAYOUT["harmonics"]] = harmonics(x, rate, hz)
        from .notation import format_note
        info.update(pitch=format_note(note) if 0 <= note < 120 else None, cents=round(cents), hz=round(hz, 2))
    return vec, info


def file_features(path):
    """features() of a WAV file's first MAX_SECONDS (the duration is the whole file's)."""
    x, rate, meta = read_audio(path, MAX_SECONDS)
    vec, info = features(x, rate, meta["frames"])
    info.update(channels=meta["channels"])
    if meta["root"] is not None:
        from .notation import format_note
        info["root"] = format_note(meta["root"])
    return vec, info


def stamp(path):
    st = os.stat(path)
    return [st.st_mtime_ns, st.st_size]


# ---------------------------------------------------------------- distances and the map

def weights(vecs):
    """Per dimension: (centre, scale) that turns a vector into weighted z-scores over `vecs` (the library), so that each
    group of WEIGHTS adds at most about its weight to a squared distance between two typical sounds."""
    v = np.asarray(vecs, float)
    centre = np.nanmean(v, axis=0) if len(v) else np.zeros(SIZE)
    spread = np.nanstd(v, axis=0) if len(v) > 1 else np.ones(SIZE)
    floor = {"mfcc_mean": 1.0, "mfcc_std": 0.5, "centroid": 0.25, "flatness": 0.1, "attack": 0.1, "duration": 0.1,
             "harmonics": 6.0}
    scale = np.ones(SIZE)
    for g, w in [*WEIGHTS.items(), ("harmonics", HARM_WEIGHT)]:
        s = LAYOUT[g]
        n = s.stop - s.start
        scale[s] = np.sqrt(w / n) / np.maximum(np.nan_to_num(spread[s], nan=1.0), floor[g])
    return np.nan_to_num(centre), scale


def distances(q, vecs, centre, scale):
    """Distance from vector `q` to each row of `vecs`: the weighted z-score distance of the timbre groups; between two
    pitched sounds also their harmonics' levels and the octaves between them (PITCH_WEIGHT each, capped at 2 octaves);
    between a pitched sound and one without, UNPITCHED."""
    v = np.asarray(vecs, float)
    t, h = TIMBRE_END, LAYOUT["harmonics"]
    d2 = (((v[:, :t] - q[:t]) * scale[:t]) ** 2).sum(axis=1)
    pq, pv = q[t], v[:, t]
    both = ~np.isnan(pv) & (not math.isnan(pq))
    one = np.isnan(pv) != math.isnan(pq)
    octaves = np.minimum(np.abs(np.nan_to_num(pv) - (0 if math.isnan(pq) else pq)) / 12, 2) * PITCH_WEIGHT
    harm = ((np.nan_to_num(v[:, h] - q[h]) * scale[h]) ** 2).sum(axis=1)
    d2 = d2 + np.where(both, octaves ** 2 + harm, 0.0) + np.where(one, UNPITCHED ** 2, 0.0)
    return np.sqrt(d2)


def pca2(vecs, centre, scale):
    """The first two principal components of the weighted vectors (pitch as the octave, the library's mean pitch where a
    sound has none, plus a pitched flag), each scaled to 0..1. Returns an n x 2 array."""
    v = np.asarray(vecs, float)
    if len(v) == 0:
        return np.zeros((0, 2))
    t, h = TIMBRE_END, LAYOUT["harmonics"]
    p = v[:, t]
    fill = np.nanmean(p) if np.any(~np.isnan(p)) else 60.0
    hv = np.where(np.isnan(v[:, h]), np.nan_to_num(centre[h]), v[:, h])  # a sound without a pitch: the library's mean
    m = np.column_stack([(v[:, :t] - centre[:t]) * scale[:t], (np.where(np.isnan(p), fill, p) - fill) / 12 * PITCH_WEIGHT,
                         np.isnan(p) * UNPITCHED, (hv - np.nan_to_num(centre[h])) * scale[h]])
    m = m - m.mean(axis=0)
    if len(v) < 3:
        xy = np.column_stack([np.linspace(0, 1, len(v)), np.full(len(v), 0.5)])
        return xy
    _, _, vt = np.linalg.svd(m, full_matrices=False)
    xy = m @ vt[:2].T
    for k in range(2):
        if xy[np.argmax(np.abs(xy[:, k])), k] < 0:  # a stable orientation: the largest excursion points up/right
            xy[:, k] = -xy[:, k]
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    return (xy - lo) / np.where(hi > lo, hi - lo, 1)


# ---------------------------------------------------------------- the index

def default_index():
    """Where the index lives: $VT_LIBRARY, else library.json beside the app's recent-songs list."""
    return Path(os.environ.get("VT_LIBRARY") or Path(os.environ.get("APPDATA", Path.home())) / "VultureTracker" / "library.json")


def default_roots():
    """The folders indexed until others are chosen: the checkout's samples/ and the CC0 packs under tools/cc0."""
    return [str(p) for p in (ROOT / "samples", ROOT / "tools" / "cc0") if p.is_dir()]


def walk(roots):
    """Every *.wav under `roots` (dot folders, like the app's .tryout renders, left out), sorted, as absolute paths."""
    out = []
    for r in roots:
        r = Path(r)
        if r.is_file() and r.suffix.lower() == ".wav":
            out.append(str(r.resolve()))
            continue
        for d, dirs, files in os.walk(r):
            dirs[:] = sorted(x for x in dirs if not x.startswith("."))
            out += [str(Path(d, f).resolve()) for f in sorted(files) if f.lower().endswith(".wav")]
    return sorted(set(out))


class Library:
    """The index at `path` (JSON): {"version", "roots", "files": {abs path: {"stamp", "vec" | "error", "info"}}}."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = {"version": VERSION, "roots": [], "files": {}}
        self.status = {"state": "idle", "done": 0, "total": 0, "message": ""}
        self._memo = {}      # features of query files outside the index: path -> (stamp, vec, info)
        self._model = None   # (generation, paths, vecs, centre, scale, xy)
        self.generation = 0
        self.job = None      # the running scan or search (run)
        self.result = None   # what the last job returned, or {"error"}
        self.scanned = 0.0   # time.time() of the last finished scan
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("files"), dict):
                self.data["roots"] = [str(r) for r in d.get("roots") or []]
                if d.get("version") == VERSION:
                    self.data["files"] = d["files"]
        except (OSError, ValueError):
            pass

    @property
    def roots(self):
        return list(self.data["roots"]) or default_roots()

    def set_roots(self, roots):
        with self.lock:
            self.data["roots"] = [str(Path(r).resolve()) for r in dict.fromkeys(str(r).strip() for r in roots) if r]
            self.save()

    def save(self):
        with self.lock:
            text = json.dumps(self.data, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.path)

    def scan(self, roots=None, progress=None, cancel=None):
        """Bring the index up to date with the WAVs under `roots` (default: the saved roots): new and changed files read,
        files gone dropped, the rest kept as they are. Returns {"files", "read", "dropped", "errors"}."""
        with self.lock:
            if roots is not None:
                self.set_roots(roots)
            roots = self.roots
            self.status = {"state": "scanning", "done": 0, "total": 0, "message": "listing files"}
        paths = walk([r for r in roots if Path(r).exists()])
        files = self.data["files"]
        todo = []
        for p in paths:
            try:
                s = stamp(p)
            except OSError:
                continue
            e = files.get(p)
            if not e or e.get("stamp") != s:
                todo.append((p, s))
        with self.lock:
            gone = [p for p in files if p not in set(paths)]
            for p in gone:
                del files[p]
            self.status.update(total=len(todo), message=f"reading {len(todo)} of {len(paths)} files")
        errors = 0
        for i, (p, s) in enumerate(todo):
            if cancel and cancel():
                break
            try:
                vec, info = file_features(p)
                entry = {"stamp": s, "vec": [None if math.isnan(v) else round(float(v), 5) for v in vec], "info": info}
            except (OSError, ValueError, MemoryError) as e:
                entry = {"stamp": s, "error": str(e)[:200]}
                errors += 1
            with self.lock:
                files[p] = entry
                self.status["done"] = i + 1
            if progress:
                progress(i + 1, len(todo), p)
            if (i + 1) % 200 == 0:
                self.save()
        with self.lock:
            self.generation += 1
            self.scanned = time.time()
            self.save()
            n = sum(1 for e in files.values() if "vec" in e)
            self.status = {"state": "idle", "done": len(todo), "total": len(todo),
                           "message": f"{n} sounds indexed ({len(todo)} read, {len(gone)} gone, {errors} unreadable)"}
        return {"files": n, "read": len(todo), "dropped": len(gone), "errors": errors}

    def run(self, fn, wait=0.0):
        """`fn()` on a thread of its own (one job at a time: a scan, or a search that may scan first), waited for up to
        `wait` seconds. Returns its result, {"error"} when it raised, or None while it still runs (then `result` later)."""
        with self.lock:
            if self.job and self.job.is_alive():
                raise ValueError(f"the library is busy: {self.status.get('message') or 'working'}")
            self.result = None

            def go():
                try:
                    self.result = fn()
                except Exception as e:  # noqa: BLE001 - a job's failure is reported to the page, never lost
                    self.result = {"error": f"{type(e).__name__}: {e}"}
                    with self.lock:
                        self.status = {"state": "idle", "done": 0, "total": 0, "message": self.result["error"]}
            self.job = threading.Thread(target=go, daemon=True)
            self.job.start()
        self.job.join(wait)
        return None if self.job.is_alive() else self.result

    def fresh(self, age=60.0):
        """scan() unless one finished in the last `age` seconds (a search does not walk a large library every time)."""
        if time.time() - self.scanned > age:
            self.scan()

    def count(self):
        with self.lock:
            return sum(1 for e in self.data["files"].values() if "vec" in e)

    def model(self):
        """(paths, vecs, centre, scale, xy) of the indexed sounds, rebuilt when the index changed."""
        with self.lock:
            if self._model and self._model[0] == self.generation:
                return self._model[1:]
            items = sorted((p, e) for p, e in self.data["files"].items() if "vec" in e)
            paths = [p for p, _ in items]
            vecs = np.array([[np.nan if v is None else v for v in e["vec"]] for _, e in items], float).reshape(-1, SIZE)
            centre, scale = weights(vecs)
            xy = pca2(vecs, centre, scale)
            self._model = (self.generation, paths, vecs, centre, scale, xy)
            return self._model[1:]

    def features_of(self, path):
        """(vec, info) of any WAV: from the index when its stamp holds, else read (and memoised on its stamp)."""
        path = str(Path(path).resolve())
        s = stamp(path)
        e = self.data["files"].get(path)
        if e and e.get("stamp") == s and "vec" in e:
            return np.array([np.nan if v is None else v for v in e["vec"]], float), e["info"]
        m = self._memo.get(path)
        if not m or m[0] != s:
            m = self._memo[path] = (s, *file_features(path))
        return m[1], m[2]

    def nearest(self, query, k=8, exclude=()):
        """The `k` indexed sounds nearest `query` (a WAV path) by timbre: [(path, distance)], nearest first; the query
        itself, paths in `exclude` and exact copies of the query (distance 0 and the same duration) left out."""
        paths, vecs, centre, scale, _ = self.model()
        if not paths:
            return []
        q, info = self.features_of(query)
        d = distances(q, vecs, centre, scale)
        skip = {str(Path(p).resolve()) for p in exclude} | {str(Path(query).resolve())}
        out = []
        for i in np.argsort(d, kind="stable"):
            p = paths[i]
            if p in skip:
                continue
            if d[i] < 0.01 and self.data["files"][p]["info"].get("duration") == info.get("duration"):
                continue
            out.append((p, float(d[i])))
            if len(out) >= k:
                break
        return out

    def map(self):
        """The map for the page: {"points": [[x, y], ...] (0..1), "paths", "names", "groups" (the folder under its root),
        "info"}; memoised with the model."""
        paths, _, _, _, xy = self.model()
        roots = sorted(self.roots, key=len, reverse=True)

        def group(p):
            for r in roots:
                if p.startswith(r.rstrip("/\\") + os.sep) or p.startswith(r.rstrip("/\\") + "/"):
                    rel = Path(p).relative_to(r).parts
                    return f"{Path(r).name}/{rel[0]}" if len(rel) > 1 else Path(r).name
            return Path(p).parent.name
        return {"points": np.round(xy, 4).tolist(), "paths": paths, "names": [Path(p).stem for p in paths],
                "groups": [group(p) for p in paths], "info": [self.data["files"][p]["info"] for p in paths],
                "generation": self.generation}

    def has(self, path):
        e = self.data["files"].get(str(path))
        return bool(e and "vec" in e)
