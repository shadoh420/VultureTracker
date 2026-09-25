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


def decimate(x, factor, h):
    """`fir_filter(x, h)[::factor]` for each column of `x` (frames x channels, any numeric dtype), computed at the output
    rate: the filter's `factor` phases each run on every `factor`-th input frame (polyphase), by FFT overlap-save in
    blocks, so no output that decimation would drop is computed and nothing the length of `x` is copied as floats."""
    x = np.asarray(x)
    n, nch = x.shape
    m, d = len(h), (len(h) - 1) // 2
    n_out = -(-n // factor)
    # output k = sum over phases r of sum_i h[factor*i + r] * x[factor*(k - i + a_r) + b_r], with d - r = factor*a_r + b_r
    phases = [(np.asarray(h[r::factor], float), *divmod(d - r, factor)) for r in range(factor)]
    amax = max(a for _, a, _ in phases)
    taps = max(amax - a + len(hr) for hr, a, _ in phases)   # each phase's filter, delayed to the latest phase's offset
    nfft = 1 << max(12, math.ceil(math.log2(16 * taps)))
    step = nfft - taps + 1
    spectra = []
    for hr, a, b in phases:
        hp = np.zeros(taps)
        hp[amax - a: amax - a + len(hr)] = hr
        spectra.append((np.fft.rfft(hp, nfft)[:, None], b))
    y = np.empty((n_out, nch))
    seg = np.empty((nfft, nch))
    for k0 in range(0, n_out, step):
        kb = min(step, n_out - k0)
        start = k0 + amax - (taps - 1)                       # the first phase frame this block's outputs reach back to
        acc = 0
        for H, b in spectra:
            lo, hi = max(start, 0), min(start + nfft, (n - b + factor - 1) // factor)
            seg[:] = 0
            if hi > lo:
                seg[lo - start: hi - start] = x[factor * lo + b: factor * (hi - 1) + b + 1: factor]
            acc = acc + np.fft.rfft(seg, axis=0) * H
        y[k0: k0 + kb] = np.fft.irfft(acc, nfft, axis=0)[taps - 1: taps - 1 + kb]
    return y


def scale_loop(start, end, pingpong, rate_in, rate_out):
    """Where a loop of the input lands in `resample`'s output: the start rounded, the period kept as close as whole
    frames allow (forward: the loop's length; ping-pong: twice the length less one, since the tracker plays the end
    frame twice and the start frame once when it turns)."""
    scale = rate_out / rate_in
    s = round(start * scale)
    c = 0.5 if pingpong else 0
    return s, s + max(1, round((end - start - c) * scale + c)), pingpong


def place_loops(loops, rate_in, rate_out):
    """Where each (start, end, pingpong) loop of the input lands in `resample`'s output: `scale_loop`'s place, except
    that a loop starting where another ends starts on that one's next frame."""
    fits = [scale_loop(*lp, rate_in, rate_out) for lp in loops]
    ends = {lp[1]: e for lp, (_, e, _) in zip(loops, fits)}
    return [(ends.get(lp[0], s), ends.get(lp[0], s) + e - s, pp) for lp, (s, e, pp) in zip(loops, fits)]


def _sinc(xp, p, h, off):
    """`xp` interpolated at the positions `p` (counted from `xp[off]`, at least `h` frames in from either end) with a
    2h-point Blackman-windowed sinc."""
    j = np.arange(-h + 1, h + 1)
    y = np.empty(len(p))
    block = 1 << 15
    for i in range(0, len(p), block):
        q = p[i: i + block]
        k0 = np.floor(q).astype(int)
        t = q[:, None] - (k0[:, None] + j[None, :])          # distance from each tap to the output position
        w = np.sinc(t) * (0.42 + 0.5 * np.cos(np.pi * t / h) + 0.08 * np.cos(2 * np.pi * t / h))
        w /= w.sum(axis=1, keepdims=True)
        y[i: i + len(q)] = (xp[k0[:, None] + j[None, :] + off] * w).sum(axis=1)
    return y


def resample(x, rate_in, rate_out, taps=64, loops=()):
    """`x` (a 1-D float array at `rate_in`) resampled to `rate_out`, band-limited: when the rate goes down the signal is
    first low-passed at 0.45 of the new rate (so nothing folds), then every output sample is a `taps`-point
    windowed-sinc interpolation of the input (so nothing images). Integer decimation takes the fast path.

    `loops` lists (start, end, pingpong) in input frames. A loop's output frames are interpolated from the loop as it
    plays, wrapped (forward) or reflected (ping-pong) at both ends, instead of from its neighbours in the file, and
    fitted to a whole number of frames at the place `place_loops` gives, so the wrap stays seamless; the output is long
    enough to hold every loop. Every frame follows one time map through each loop's first frame and the frame after its
    last, so playback runs on without a jump into a loop and out of it, and a loop inside another (a sustain loop in the
    main loop, or the reverse) is the same frames in both, seamless in both; the inner loop keeps its own wrap. Two
    loops that only partly overlap cannot both be seamless: the shorter keeps the shared frames."""
    x = np.asarray(x, float)
    if rate_in == rate_out or len(x) == 0:
        return x.copy()
    ratio = rate_in / rate_out                       # input samples per output sample
    h = taps // 2
    fir = lowpass_fir(0.45 / ratio) if rate_out < rate_in else None
    if fir is not None and abs(ratio - round(ratio)) < 1e-9 and not loops:
        return decimate(x[:, None], int(round(ratio)), fir)[:, 0]
    xf = fir_filter(x, fir) if fir is not None else x
    n_out = int(math.floor((len(x) - 1) / ratio)) + 1
    fits = [(*lp, s, e) for lp, (s, e, _) in zip(loops, place_loops(loops, rate_in, rate_out))]
    size = max([n_out] + [e for *_, e in fits])
    p = np.arange(size) * ratio                      # the input position of every output frame
    if fits:                                         # through each loop's first frame and the frame after its last
        turn = [0.5 if pp else 0 for _, _, pp, _, _ in fits]         # ping-pong turns at start and end - 0.5
        knots = sorted([(s, start - s * ratio) for start, _, _, s, _ in fits]
                       + [(e, start + (e - s) * (end - start - c) / (e - s - c) - e * ratio)
                          for (start, end, _, s, e), c in zip(fits, turn)])
        p = p + np.interp(np.arange(size), [k for k, _ in knots], [d for _, d in knots])
    lead = h + 2 * math.ceil(ratio) + 2              # the time map moves a frame by less than two output frames
    y = np.zeros(size)
    y[:n_out] = _sinc(np.concatenate([np.zeros(lead), xf, np.zeros(lead + 1)]), p[:n_out], h, lead)
    pad = h + 2 + (len(fir) // 2 if fir is not None else 0)
    for start, end, pingpong, s, e in sorted(fits, key=lambda f: f[0] - f[1]):   # the longest first
        n = end - start
        period = 2 * n - 1 if pingpong else n
        m = np.arange(-pad, n + pad) % period               # the loop as it plays, `pad` frames past either end
        seg = x[start + np.where(m < n, m, period - m)]
        if fir is not None:
            seg = fir_filter(seg, fir)
        y[s:e] = _sinc(seg, p[s:e] - start, h, pad)
    return y


def _interpolator_response():
    """|H|^2 of libopenmpt's 8-tap interpolator against frequency in units of the sample's stored rate. Measured by
    playing a one-frame impulse five octaves down: an 8-tap Kaiser-windowed sinc (beta 9.75, cutoff 0.48 of the rate)
    matches it within 0.7 dB down to -54 dB."""
    t = (np.arange(8 * 64) - 8 * 64 / 2) / 64
    p = np.abs(np.fft.rfft(np.sinc(0.96 * t) * np.kaiser(8 * 64, 9.75), 1 << 15)) ** 2
    return np.fft.rfftfreq(1 << 15) * 64, p / p[0]


def image_level(channels, rate, ceiling=19845.0):
    """How loud the interpolation images of a sample played at `rate` frames per second are under `ceiling` Hz (the
    oversampled render's cut at 0.45 of 44.1 kHz), in dB against the sample as played; None when every image lands
    above it. A sample played slower than it is stored leaves copies of its spectrum at k * rate -/+ f; the interpolator
    weakens those least for content near the sample's own Nyquist frequency, and the render removes only what lands
    above `ceiling`. Within 1 dB of rendered white noise from 4 to 24 semitones below the root."""
    if rate >= 2 * ceiling or not len(channels[0]):
        return None
    p = sum(np.abs(np.fft.rfft(np.asarray(ch, float))) ** 2 for ch in channels)
    band = np.minimum((np.fft.rfftfreq(len(channels[0])) * 1024).astype(int), 511)
    p = np.bincount(band, p, 512)                           # 512 bands keep very low notes (many images) cheap
    nu = (np.arange(512) + 0.5) / 1024                      # band centres, cycles per stored frame
    u, h2 = _interpolator_response()
    direct = (p * np.interp(nu, u, h2)).sum()
    images = sum((p * np.interp(f, u, h2) * (f * rate < ceiling)).sum()
                 for k in range(1, int(ceiling / rate) + 2) for f in (k - nu, k + nu))
    return 10 * math.log10(images / direct + 1e-30) if direct > 0 else None


def resample_pcm(channels, rate_in, rate_out, bits=16, loops=()):
    """Integer PCM channels (lists) resampled and clipped back to `bits`; `loops` as for `resample`."""
    lim = 2 ** (bits - 1)
    out = []
    for ch in channels:
        y = resample(np.asarray(ch, float), rate_in, rate_out, loops=loops)
        out.append(np.clip(np.rint(y), -lim, lim - 1).astype(int).tolist())
    return out
