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
