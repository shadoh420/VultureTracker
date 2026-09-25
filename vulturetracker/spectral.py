"""Spectral tools in the MetaSynth manner (numpy; nothing of MetaSynth's): a picture over a log-frequency grid played as
sound (each row a sine at its frequency, each column a moment, brightness the level and colour the pan), and the same
kind of picture laid over a sample's spectrum as a filter (STFT magnitudes times the picture, the phase kept).

A picture is `amp` (rows x columns, 0-1, row 0 the lowest frequency) and, for the render, `pan` (the same shape, -1 left
to +1 right). Its rows are spread over `fmin`..`fmax`: evenly in log frequency (`scale` "log"), or one row per semitone
from the note `fmin` names ("notes": fmin and fmax are note numbers, C-5 = 60). Brightness maps to level over
`range_db`: 1 is full, 0.5 is range_db / 2 under it, 0 is silence."""
import math

import numpy as np

MAX_HZ = 18000.0  # nothing above the drums' ceiling (AGENTS.md: the anti-aliasing rule)


def row_freqs(rows, fmin, fmax, scale="log"):
    """The frequency of each row, lowest first."""
    if scale == "notes":
        return 440.0 * 2 ** ((float(fmin) + np.arange(rows) - 69) / 12)
    if not 0 < fmin < fmax:
        raise ValueError("the picture's range runs from a low frequency to a higher one")
    return float(fmin) * (float(fmax) / float(fmin)) ** (np.arange(rows) / max(1, rows - 1))


def level(amp, range_db=48.0):
    """Brightness 0-1 as a linear gain: 10 ** ((b - 1) * range_db / 20), and 0 for 0."""
    amp = np.clip(np.asarray(amp, float), 0, 1)
    return np.where(amp > 0, 10 ** ((amp - 1) * float(range_db) / 20), 0.0)


def paint_render(amp, pan, seconds, rate=44100, fmin=40.0, fmax=12000.0, scale="log", range_db=48.0, seed=0):
    """The picture played as sound: every row a sine at its frequency (a random start phase from `seed`), its level and pan
    following the row's columns over `seconds` (interpolated between column centres, so a drawn stroke fades in and out
    over a column rather than clicking), equal-power panning. Rows at or above MAX_HZ and above 0.45 x rate stay silent.
    Returns (stereo float array 2 x frames, peak): not normalised."""
    amp = np.asarray(amp, float)
    pan = np.zeros_like(amp) if pan is None else np.clip(np.asarray(pan, float), -1, 1)
    if amp.ndim != 2 or pan.shape != amp.shape:
        raise ValueError("the picture is rows x columns of brightness, with a pan of the same shape")
    rows, cols = amp.shape
    n = int(round(float(seconds) * rate))
    if not 0 < n <= rate * 60:
        raise ValueError("a painted sound lasts 0 to 60 seconds")
    freqs = row_freqs(rows, fmin, fmax, scale)
    gains = level(amp, range_db)
    t = np.arange(n) / rate
    centres = (np.arange(cols) + 0.5) * n / cols          # each column's value holds at its centre
    frame = np.arange(n)
    rng = np.random.default_rng(seed)
    phases = rng.uniform(0, 2 * np.pi, rows)
    out = np.zeros((2, n))
    for r in range(rows):
        if not gains[r].any() or freqs[r] >= min(MAX_HZ, 0.45 * rate):
            continue
        g = np.interp(frame, centres, gains[r])
        p = np.interp(frame, centres, pan[r])
        wave = np.sin(2 * np.pi * freqs[r] * t + phases[r]) * g
        out[0] += wave * np.cos((p + 1) * np.pi / 4)
        out[1] += wave * np.sin((p + 1) * np.pi / 4)
    return out, float(np.abs(out).max())


def spectral_mask(x, rate, amp, fmin=40.0, fmax=12000.0, scale="log", range_db=48.0, size=2048):
    """`x` (channels x frames) filtered by the picture: every STFT bin's magnitude times the picture's level at its
    frequency (between rows: interpolated in log frequency; under the lowest row or over the highest: that row's) and
    its moment (the columns spread over the whole of x), the phase kept. Returns x's shape."""
    from .dsp import _istft, _stft
    x = np.asarray(x, np.float64)
    amp = np.asarray(amp, float)
    if amp.ndim != 2:
        raise ValueError("the picture is rows x columns of brightness")
    rows, cols = amp.shape
    hop = size // 4
    X = _stft(x, size, hop)
    frames = X.shape[1]
    gains = level(amp, range_db)
    freqs = row_freqs(rows, fmin, fmax, scale)
    bins = np.fft.rfftfreq(size, 1 / rate)
    lf = np.log2(np.maximum(bins, 1.0))
    # per bin, the (fractional) row: bins between two rows' frequencies take both, weighted by log distance
    rpos = np.interp(lf, np.log2(freqs), np.arange(rows)) if rows > 1 else np.zeros(len(bins))
    r0 = np.floor(rpos).astype(int)
    r1 = np.minimum(r0 + 1, rows - 1)
    wr = rpos - r0
    by_row = gains[r0] * (1 - wr)[:, None] + gains[r1] * wr[:, None]        # bins x columns
    # per STFT frame, its moment in the sound (the frames are padded by a window each side)
    at = (np.arange(frames) * hop - size + size / 2) / max(1, x.shape[-1])  # 0..1 over x
    centres = (np.arange(cols) + 0.5) / cols
    g = np.stack([np.interp(at, centres, by_row[b]) for b in range(len(bins))], axis=1)  # frames x bins
    return _istft(X * g[None], size, hop, x.shape[-1])


def picture_png(amp, pan):
    """The picture as an RGB image (row 0 at the bottom): brightness as light, pan as colour (red left, yellow centre,
    green right), for a PNG beside the rendered WAV."""
    amp = np.clip(np.asarray(amp, float), 0, 1)[::-1]
    pan = np.clip(np.asarray(pan, float), -1, 1)[::-1]
    red = np.where(pan <= 0, 1.0, 1 - pan)
    green = np.where(pan >= 0, 1.0, 1 + pan)
    rgb = np.stack([red * amp, green * amp, np.zeros_like(amp)], axis=-1)
    return np.round(rgb * 255).astype(np.uint8)
