"""Band-limited resampling with numpy: the anti-aliasing the compiler, the renderer and the sample generators need.

Two things create false frequencies in a sample-based mix. Interpolating a sample to a higher rate (a 11 kHz pad
played into a 44.1 kHz mix) mirrors its spectrum above its own Nyquist frequency unless the interpolation low-passes
it (imaging); playing content above the output's Nyquist frequency folds it back down (aliasing). The cure for both
is the same filter: a windowed sinc low-pass at the lower of the two Nyquist frequencies. `resample` applies it when
a sample's rate changes; `lowpass_fir` and `fir_filter` are the pieces a renderer uses to oversample and decimate.
"""
import math

import numpy as np


def lowpass_fir(cutoff, taps=1023):
    """A linear-phase FIR low-pass: `cutoff` is a fraction of the sample rate (0 < cutoff < 0.5), Blackman-windowed
    sinc, unity gain at DC. 1023 taps give a transition band of about 0.5 % of the rate and a stop band below -74 dB."""
    n = np.arange(taps) - (taps - 1) / 2
    h = 2 * cutoff * np.sinc(2 * cutoff * n) * np.blackman(taps)
    return h / h.sum()


def fir_filter(x, h):
    """`x` convolved with the FIR `h` by FFT overlap-add, aligned with the input and the same length."""
    x = np.asarray(x, float)
    n, m = len(x), len(h)
    block = 1 << 16
    nfft = 1 << math.ceil(math.log2(block + m - 1))
    H = np.fft.rfft(h, nfft)
    y = np.zeros(n + m - 1)
    for i in range(0, n, block):
        seg = x[i:i + block]
        y[i:i + len(seg) + m - 1] += np.fft.irfft(np.fft.rfft(seg, nfft) * H, nfft)[: len(seg) + m - 1]
    d = (m - 1) // 2
    return y[d: d + n]


def resample(x, rate_in, rate_out, taps=64):
    """`x` (a 1-D float array at `rate_in`) resampled to `rate_out`, band-limited: when the rate goes down the signal is
    first low-passed at 0.45 of the new rate (so nothing folds), then every output sample is a `taps`-point
    windowed-sinc interpolation of the input (so nothing images). Integer decimation takes the fast path."""
    x = np.asarray(x, float)
    if rate_in == rate_out or len(x) == 0:
        return x.copy()
    ratio = rate_in / rate_out                       # input samples per output sample
    if rate_out < rate_in:
        x = fir_filter(x, lowpass_fir(0.45 / ratio))
        if abs(ratio - round(ratio)) < 1e-9:
            return x[:: int(round(ratio))].copy()
    n_out = int(math.floor((len(x) - 1) / ratio)) + 1
    h = taps // 2
    xp = np.concatenate([np.zeros(h), x, np.zeros(h + 1)])
    j = np.arange(-h + 1, h + 1)
    y = np.empty(n_out)
    block = 1 << 15
    for i in range(0, n_out, block):
        p = np.arange(i, min(n_out, i + block)) * ratio
        k0 = np.floor(p).astype(int)
        t = p[:, None] - (k0[:, None] + j[None, :])          # distance from each tap to the output position
        w = np.sinc(t) * (0.42 + 0.5 * np.cos(np.pi * t / h) + 0.08 * np.cos(2 * np.pi * t / h))
        w /= w.sum(axis=1, keepdims=True)
        y[i: i + len(p)] = (xp[k0[:, None] + j[None, :] + h] * w).sum(axis=1)
    return y


def resample_pcm(channels, rate_in, rate_out, bits=16):
    """Integer PCM channels (lists) resampled and clipped back to `bits`."""
    lim = 2 ** (bits - 1)
    out = []
    for ch in channels:
        y = resample(np.asarray(ch, float), rate_in, rate_out)
        out.append(np.clip(np.rint(y), -lim, lim - 1).astype(int).tolist())
    return out
