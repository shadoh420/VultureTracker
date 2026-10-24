"""Measurements for the app: a WAV's duration, pitch, centroid and envelope (measure, distance), the compiled module
with mutes and the unwritten mix patched into its header (patch_it) and each channel soloed (channel_levels),
spectrograms as PNGs, the SPECTRUM tab's reference (reference_wav, reference_compare, reference_align) and a render's
loudness and meters (mix_numbers)."""
import functools
import hashlib
import math
import os
import struct
import wave
import zlib
from pathlib import Path

from .notation import format_note
from .openmpt import LoadedModule
from .wavload import read_wav, run_ffmpeg

RATE = 44100  # what the app renders and measures at


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
        "lufs": None,
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
    m["lufs"] = sample_lufs(w)
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


def sample_lufs(w):
    """A WAV's loudness as the tryout's MATCH LEVEL compares it (dsp.integrated_lufs): a mono WAV counted on both
    sides, as the module plays it; a loop's body repeated to 3 s, as a held note sustains it; a one-shot shorter than one
    400 ms block padded with silence (the gate then drops a silent tail and a long quiet one alike)."""
    import numpy as np
    from . import dsp
    x = np.asarray(w.channels, float) / (1 << (w.out_bits - 1))
    if len(x) == 1:
        x = np.vstack([x, x])
    if w.loops and w.loops[0][1] > w.loops[0][0]:
        a, b, _ = w.loops[0]
        reps = -(-max(0, 3 * w.rate - b) // (b - a))
        x = np.hstack([x[:, :b], np.tile(x[:, a:b], (1, reps))])
    if x.shape[1] < int(0.4 * w.rate):
        x = np.hstack([x, np.zeros((len(x), int(0.4 * w.rate) - x.shape[1]))])
    return dsp.integrated_lufs(x, w.rate)


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
        offs, copies = _sample_headers(d)
        for slot, g in mix["sample_volume"].items():
            if 1 <= int(slot) <= len(offs):
                for i in copies(int(slot)):
                    d[offs[i] + 0x11] = int(g)
    return bytes(d)


def _sample_headers(d):
    """The module's sample header offsets and copies(slot): the sample indices that play slot `slot` (a tuning's copies
    share their slot's data)."""
    nord, nins, nsmp = struct.unpack_from("<HHH", d, 0x20)
    offs = [struct.unpack_from("<I", d, 0xC0 + nord + 4 * nins + 4 * i)[0] for i in range(nsmp)]
    data = [struct.unpack_from("<I", d, off + 0x48)[0] for off in offs]
    return offs, lambda slot: [slot - 1] + ([j for j in range(nsmp) if j != slot - 1 and data[j] == data[slot - 1]] if data[slot - 1] else [])


def match_level(data, slot, db):
    """The tryout's MATCH LEVEL (playback only): the module with slot `slot` `db` louder against the rest of the mix.
    A sample's global volume only goes down from 64, so a cut lowers the slot's and a boost lowers every other sample's
    by as much, and the render is then multiplied by the factor returned. Returns (module bytes, output factor)."""
    r = 10 ** (db / 20)
    out = max(1.0, r)
    d = bytearray(data)
    offs, copies = _sample_headers(d)
    mine = set(copies(slot)) if 1 <= slot <= len(offs) else set()
    for i, off in enumerate(offs):  # ponytail: integer volumes 0-64, so a sample already near 0 quantizes coarsely
        d[off + 0x11] = min(64, round(d[off + 0x11] * (r if i in mine else 1) / out))
    return bytes(d), out


def scale_pcm(pcm, factor):
    """Interleaved int16 PCM times `factor`, clipped as libopenmpt's own output clips."""
    import numpy as np
    return np.clip(np.round(np.frombuffer(pcm, "<i2") * factor), -32768, 32767).astype("<i2").tobytes()


def channel_levels(data, nch, cancel=None, *, plan=None, snapshot=None):
    """Each channel soloed (every other channel disabled so volume commands cannot unmute it): RMS in dB over the whole render and over its active half-seconds, plus those seconds. Needs numpy.
    `cancel()` true between channels abandons the pass (returns None)."""
    import numpy as np
    out = []
    for ch in range(nch):
        if cancel is not None and cancel():
            return None
        muted = [other for other in range(nch) if other != ch]
        if snapshot is not None:
            from .export import render
            pcm = render(snapshot, silenced=muted, cancel=cancel)
        else:
            d = patch_it(data, muted)
            with LoadedModule(d, rate=RATE, oversample=1, plan=plan) as lm:
                pcm = lm.render(RATE, oversample=1)
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float32).reshape(-1, 2) / 32768
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
    from .gui import ffmpeg_exe  # at call time: gui imports this module
    src = Path(src).resolve()
    st = src.stat()
    out = Path(folder) / f"reference-{hashlib.sha1(f'{src}|{st.st_mtime}|{st.st_size}'.encode()).hexdigest()[:12]}.wav"
    if not out.exists():
        tmp = out.with_name(out.stem + ".part.wav")
        r = run_ffmpeg([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src), "-map", "0:a:0", "-ac", "2", "-ar", str(RATE),
                        "-c:a", "pcm_s16le", str(tmp)])
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


@functools.lru_cache(maxsize=32)
def _mix_numbers(path, stamp):
    import numpy as np
    from . import dsp
    pcm = np.frombuffer(Path(path).read_bytes()[44:], "<i2").reshape(-1, 2).T.astype(np.float32) / 32768
    return dsp.measure_mix(pcm, RATE)


@functools.lru_cache(maxsize=8)
def _meters(path, stamp):
    import numpy as np
    from . import dsp
    pcm = np.frombuffer(Path(path).read_bytes()[44:], "<i2").reshape(-1, 2).T.astype(np.float32) / 32768
    return dsp.meter_series(pcm, RATE)


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
