"""Audio analysis and edits for the Samples tab (numpy): where a recording's hits start (onsets, for slicing).
Signals are float arrays, channels x frames, full scale 1.0."""
import numpy as np


def _mono(x):
    x = np.asarray(x, float)
    return x.mean(axis=0) if x.ndim == 2 else x


def novelty(x, rate, hop=256, size=1024):
    """Spectral flux: per hop, how much louder the spectrum got (the positive log-magnitude differences, summed).
    Returns (flux, hop)."""
    m = _mono(x)
    if len(m) < size:
        m = np.pad(m, (0, size - len(m)))
    frames = 1 + (len(m) - size) // hop
    idx = np.arange(size)[None, :] + hop * np.arange(frames)[:, None]
    mag = np.log1p(100 * np.abs(np.fft.rfft(m[idx] * np.hanning(size), axis=1)))
    flux = np.maximum(0, np.diff(mag, axis=0, prepend=mag[:1])).sum(axis=1)
    return flux, hop


def zero_crossing(m, at, reach):
    """The frame nearest `at` (within `reach` frames, looking back first) where the signal crosses zero, else `at`."""
    lo = max(1, at - reach)
    seg = m[lo - 1: at + reach + 1]
    cross = np.nonzero(np.signbit(seg[:-1]) != np.signbit(seg[1:]))[0] + lo
    if not len(cross):
        return at
    return int(cross[np.argmin(np.abs(cross - at) + (cross > at) * 0.5)])


def onsets(x, rate, sensitivity=50, a=0, b=None, min_gap=0.05):
    """Where hits start in frames a..b of `x` (channels x frames): peaks of the spectral flux above an adaptive threshold
    (sensitivity 0-100: higher finds softer hits), at least `min_gap` seconds apart, each placed 1 ms before its hit
    reaches a fifth of its level and moved onto a zero crossing. The first point is always `a`."""
    x = np.asarray(x, float)
    b = x.shape[-1] if b is None else b
    seg = x[..., a:b]
    m = _mono(seg)
    if len(m) < 64:
        return [a]
    size = 1024
    flux, hop = novelty(seg, rate, size=size)
    flux = flux / (flux.max() or 1)
    w = max(1, int(0.1 * rate / hop))  # the local level the threshold rides on: a 0.2 s moving median
    pad = np.pad(flux, w, mode="edge")
    local = np.median(np.lib.stride_tricks.sliding_window_view(pad, 2 * w + 1), axis=1)[: len(flux)]
    delta = 0.06 + 0.44 * (1 - max(0, min(100, sensitivity)) / 100) ** 2
    gap = max(1, int(min_gap * rate / hop))
    peaks = [i for i in range(1, len(flux) - 1)
             if flux[i] >= flux[i - 1] and flux[i] > flux[i + 1] and flux[i] > local[i] + delta]
    out, last = [a], -gap
    ms = max(1, rate // 1000)
    env = np.sqrt(np.convolve(m * m, np.ones(ms) / ms, mode="same"))  # a 1 ms RMS envelope
    for i in peaks:
        if i - last < gap:
            continue
        last = i
        lo, hi = max(0, i * hop - size // 2), min(len(m), i * hop + size + hop)  # where the window saw the rise
        rise = np.nonzero(env[lo:hi] >= 0.2 * env[lo:hi].max())[0]
        at = max(0, lo + (int(rise[0]) if len(rise) else size // 2) - ms)  # 1 ms before the hit reaches a fifth of its level
        at = zero_crossing(m, at, 2 * ms)
        if at - (out[-1] - a) >= int(min_gap * rate / 2) and at > 0:
            out.append(a + at)
    return out


def equal_parts(a, b, n):
    """`n` equal slices of frames a..b: their start frames."""
    n = max(1, min(99, int(n)))
    return [a + (b - a) * k // n for k in range(n)]


# ---------------------------------------------------------------- effects (the Samples tab's EFFECTS → NEW WAV)
# Filters here are zero-phase (applied to the magnitude spectrum of the whole selection): offline, no phase shift
# between bands, at the cost of a little ringing before sharp attacks at steep settings.

def gain(x, db):
    return x * 10 ** (float(db) / 20)


def _spectral(x, response):
    """`x` (channels x frames) filtered by the real magnitude `response(freq in cycles per frame)`, zero-phase."""
    n = x.shape[-1]
    size = 1 << int(np.ceil(np.log2(max(2, 2 * n))))  # padded: the filter's ringing does not wrap around
    f = np.fft.rfftfreq(size)
    y = np.fft.irfft(np.fft.rfft(x, size, axis=-1) * response(f), size, axis=-1)[..., :n]
    return y.astype(x.dtype, copy=False)


def lowpass(x, rate, hz, slope=24):
    """Butterworth-shaped low-pass magnitude (12 or 24 dB per octave above `hz`)."""
    order, fc = (2 if slope <= 12 else 4), float(hz) / rate
    return _spectral(x, lambda f: 1 / np.sqrt(1 + (f / fc) ** (2 * order)))


def highpass(x, rate, hz, slope=24):
    order, fc = (2 if slope <= 12 else 4), float(hz) / rate
    return _spectral(x, lambda f: 1 / np.sqrt(1 + (fc / np.maximum(f, 1e-12)) ** (2 * order)))


def peak_eq(x, rate, hz, db, q=1.0):
    """One bell band: `db` of boost or cut at `hz`, width `q` (the RBJ cookbook's peaking filter, magnitude only)."""
    A, w0 = 10 ** (float(db) / 40), 2 * np.pi * float(hz) / rate
    alpha = np.sin(w0) / (2 * max(0.05, float(q)))
    b = np.array([1 + alpha * A, -2 * np.cos(w0), 1 - alpha * A])
    a = np.array([1 + alpha / A, -2 * np.cos(w0), 1 - alpha / A])

    def response(f):
        z = np.exp(-2j * np.pi * f)
        return np.abs((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z))
    return _spectral(x, response)


def loudness(x, target_db=-18.0):
    """Gain that brings the RMS of the part that sounds (10 ms blocks within 40 dB of the loudest) to `target_db` dBFS,
    held back so the peak stays under full scale. Returns (x, the gain in dB)."""
    m = np.asarray(x, float)
    blk = 441
    n = m.shape[-1] // blk * blk
    if n == 0:
        raise ValueError("too short to measure")
    e = (m[..., :n] ** 2).mean(axis=0).reshape(-1, blk).mean(axis=1)
    live = e[e > e.max() * 1e-4]
    rms = np.sqrt(live.mean()) if len(live) else 0
    if rms <= 0:
        raise ValueError("nothing to level: the selection is silent")
    g = 10 ** (float(target_db) / 20) / rms
    peak = float(np.abs(m).max())
    g = min(g, 0.999 / peak) if peak else g
    return x * g, 20 * np.log10(g)


def stretch(x, ratio, size=2048):
    """`x` (channels x frames) made `ratio` times as long at the same pitch: a phase vocoder with identity phase locking
    (each bin keeps its phase relation to the nearest spectral peak, which keeps partials coherent), the phases run on
    the channels' mid so a stereo image holds."""
    x = np.asarray(x, np.float64)
    ratio = float(ratio)
    if not 0.25 <= ratio <= 4:
        raise ValueError("a stretch is 25-400 %")
    n = x.shape[-1]
    ha = size // 4
    hs = ha * ratio
    win = np.hanning(size + 1)[:size]
    pad = np.pad(x, ((0, 0), (size, size + ha)))
    frames = 1 + (pad.shape[-1] - size) // ha
    idx = np.arange(size)[None, :] + ha * np.arange(frames)[:, None]
    X = np.fft.rfft(pad[:, idx] * win, axis=-1)          # channels x frames x bins
    mid = X.mean(axis=0)
    mag, ph = np.abs(mid), np.angle(mid)
    bins = np.arange(X.shape[-1])
    omega = 2 * np.pi * bins * ha / size
    syn = np.empty_like(ph)
    syn[0] = ph[0]
    for t in range(1, frames):
        d = ph[t] - ph[t - 1] - omega
        d -= 2 * np.pi * np.round(d / (2 * np.pi))
        adv = (omega + d) * (hs / ha)
        m = mag[t]
        peaks = np.nonzero((m[1:-1] > m[:-2]) & (m[1:-1] >= m[2:]))[0] + 1
        if len(peaks):                                   # identity phase locking around each peak
            nearest = peaks[np.clip(np.searchsorted((peaks[1:] + peaks[:-1]) / 2, bins), 0, len(peaks) - 1)]
            syn[t] = syn[t - 1][nearest] + adv[nearest] + ph[t] - ph[t][nearest]
        else:
            syn[t] = syn[t - 1] + adv
    Y = np.abs(X) * np.exp(1j * (syn[None] + np.angle(X) - ph[None]))
    out_len = int(round((frames - 1) * hs)) + size
    y = np.zeros((x.shape[0], out_len))
    norm = np.zeros(out_len)
    frames_y = np.fft.irfft(Y, size, axis=-1) * win
    for t in range(frames):
        at = int(round(t * hs))
        y[:, at:at + size] += frames_y[:, t]
        norm[at:at + size] += win ** 2
    y /= np.maximum(norm, 1e-3 * norm.max())
    start = int(round(size * ratio))
    return y[:, start:start + int(round(n * ratio))]


def pitch_shift(x, semitones):
    """`x` moved `semitones` up or down at the same length: stretched by the pitch ratio, then resampled back."""
    from .resample import resample
    r = 2 ** (float(semitones) / 12)
    if not 0.25 <= r <= 4:
        raise ValueError("a pitch shift is -24 to +24 semitones")
    n = x.shape[-1]
    y = stretch(x, r)
    out = np.stack([resample(c, y.shape[-1], n) for c in y])  # from len(y) frames down (or up) to n
    return out[:, :n] if out.shape[-1] >= n else np.pad(out, ((0, 0), (0, n - out.shape[-1])))


def silent_runs(x, rate, db=-50.0, min_ms=200):
    """Spans (start, end) where every 10 ms block is below `db` dBFS for at least `min_ms`."""
    m = np.abs(np.asarray(x, float)).max(axis=0)
    blk = max(1, rate // 100)
    nb = len(m) // blk
    quiet = m[: nb * blk].reshape(nb, blk).max(axis=1) < 10 ** (float(db) / 20)
    runs, start = [], None
    for i, q in enumerate(list(quiet) + [False]):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * 10 >= min_ms:
                runs.append((start * blk, i * blk))
            start = None
    return runs
