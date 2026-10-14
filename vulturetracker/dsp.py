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
    size, hop = 1024, 256
    # half a window past the selection (the file's own sound where it goes on, else silence), so a hit in its last
    # milliseconds sits mid-window, not under the window's taper
    tail = x[..., b:b + size // 2]
    seg = np.concatenate([seg, tail, np.zeros(seg.shape[:-1] + (size // 2 - tail.shape[-1],))], axis=-1)
    n, m = len(m), _mono(seg)  # a hit counts where it rises inside the selection's n frames
    skip = max(0, seg.shape[-1] - size) % hop  # the frames end where the extended selection does
    flux, hop = novelty(seg[..., skip:], rate, hop, size)
    flux = flux / (flux.max() or 1)
    # the local level the threshold rides on: a 0.2 s moving median, reflected at the end (a hit in the last frame is
    # not its own level)
    w = max(1, int(0.1 * rate / hop))
    pad = np.pad(np.pad(flux, (w, 0), mode="edge"), (0, w), mode="reflect")
    local = np.median(np.lib.stride_tricks.sliding_window_view(pad, 2 * w + 1), axis=1)[: len(flux)]
    delta = 0.06 + 0.44 * (1 - max(0, min(100, sensitivity)) / 100) ** 2
    gap = max(1, int(min_gap * rate / hop))
    after = np.append(flux[1:], -1)  # nothing follows the last frame
    peaks = [i for i in range(1, len(flux))
             if flux[i] >= flux[i - 1] and flux[i] > after[i] and flux[i] > local[i] + delta]
    out, last = [a], -gap
    ms = max(1, rate // 1000)
    env = np.sqrt(np.convolve(m * m, np.ones(ms) / ms, mode="same"))  # a 1 ms RMS envelope
    blk = max(1, rate // 100)  # the window's level in 10 ms blocks: free of a low tone's ripple
    for i in peaks:
        if i - last < gap:
            continue
        last = i
        # where the window saw the rise: its biggest step up, from the quietest block before it. A sound decaying from
        # the window's start, or one cut off in it (a click 40 dB down), only steps down: no hit
        lo, hi = max(0, skip + i * hop - size // 2), min(len(m), skip + i * hop + size + hop)
        lv = np.array([np.abs(m[j:j + blk]).max() for j in range(lo, hi, blk)])
        k = int(np.argmax(lv - np.minimum.accumulate(lv)))
        q = int(np.argmin(lv[:k + 1]))
        if lv[k] < 1.4 * lv[q] + 1e-6:
            continue
        e = env[lo + q * blk:hi]
        base = e[:blk].max()  # what sounds in the quiet block (a pad, a tail) is not the hit's own level
        rise = q * blk + int(np.argmax(e >= base + 0.2 * (e.max() - base)))
        r = lo + rise  # where the hit reaches a fifth of its level over what sounded before
        at = zero_crossing(m, max(0, r - ms), 2 * ms)  # 1 ms before that
        # a window reaching past the selection counts only a hit that rises in it: a held sound cut off there (the
        # silence after a file's end) is not one
        rose = skip + i * hop + size <= n or rise > 0
        if at - (out[-1] - a) >= int(min_gap * rate / 2) and at > 0 and r < n and rose:
            out.append(a + at)
    return out


def bpm_guess(seconds):
    """A loop's tempo guessed from its length, as SlicerT guesses it: 240 / seconds (one bar of four beats), doubled or
    halved into 100-200 BPM. A guess for the owner to correct, not a measurement."""
    if seconds <= 0:
        return 120.0
    v = 240.0 / seconds
    while v < 100:
        v *= 2
    while v > 200:
        v /= 2
    return round(v, 2)


def snap_points(points, a, rate, bpm, division):
    """Slice starts moved to the nearest line of a grid of 1/`division` notes at `bpm` from frame `a` (a 1/16 is a
    quarter of a beat); two that land on one line become one."""
    step = rate * 240.0 / (bpm * division)
    return sorted({a + round(round((p - a) / step) * step) for p in points})


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
    """`x` (channels x frames) filtered by `response(freq in cycles per frame)`: a real magnitude filters zero-phase,
    a complex one (dispersion's all-passes) also delays each frequency by its own amount."""
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
    # a window no longer than the output (256 at least): a 46 ms tone squeezed to 25 % in 2048 frames lost 13.6 dB
    size = int(min(size, max(256, 2 ** np.floor(np.log2(max(1.0, n * ratio))))))
    # the synthesis hop hs stays near size / 4: four windows overlap at any ratio, no dips in their sum at the joins
    ha = size // 4 if ratio <= 1 else max(1, round(size / (4 * ratio)))
    hs = ha * ratio
    win = np.hanning(size + 1)[:size]
    pad = np.pad(x, ((0, 0), (size, size + ha)))
    frames = 1 + (pad.shape[-1] - size) // ha
    bins = np.arange(size // 2 + 1)
    omega = 2 * np.pi * bins * ha / size
    out_len = int(round((frames - 1) * hs)) + size
    y = np.zeros((x.shape[0], out_len))
    norm = np.zeros(out_len)
    for t in range(frames):                              # a frame at a time: the memory is the output's, at any ratio
        X = np.fft.rfft(pad[:, t * ha: t * ha + size] * win, axis=-1)     # channels x bins
        mid = X.mean(axis=0)
        m, ph = np.abs(mid), np.angle(mid)
        if t == 0:
            syn = ph
        else:
            d = ph - prev - omega
            d -= 2 * np.pi * np.round(d / (2 * np.pi))
            adv = (omega + d) * (hs / ha)
            peaks = np.nonzero((m[1:-1] > m[:-2]) & (m[1:-1] >= m[2:]))[0] + 1
            if len(peaks):                               # identity phase locking around each peak
                nearest = peaks[np.clip(np.searchsorted((peaks[1:] + peaks[:-1]) / 2, bins), 0, len(peaks) - 1)]
                syn = syn[nearest] + adv[nearest] + ph - ph[nearest]
            else:
                syn = syn + adv
        prev = ph
        at = int(round(t * hs))
        y[:, at:at + size] += np.fft.irfft(np.abs(X) * np.exp(1j * (syn + np.angle(X) - ph)), size, axis=-1) * win
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


def _stft(x, size, hop):
    """Frames of `x` (channels x frames, padded by a window each side) as spectra: channels x frames x bins."""
    pad = np.pad(np.asarray(x, np.float64), ((0, 0), (size, size + hop)))
    n = 1 + (pad.shape[-1] - size) // hop
    idx = np.arange(size)[None, :] + hop * np.arange(n)[:, None]
    return np.fft.rfft(pad[:, idx] * np.hanning(size + 1)[:size], axis=-1)


def _istft(X, size, hop, length):
    """The inverse of _stft: windowed overlap-add, divided by the summed squared window; `length` frames."""
    win = np.hanning(size + 1)[:size]
    frames = np.fft.irfft(X, size, axis=-1) * win
    n = X.shape[1]
    out = np.zeros((X.shape[0], (n - 1) * hop + size))
    norm = np.zeros(out.shape[-1])
    for t in range(n):
        out[:, t * hop:t * hop + size] += frames[:, t]
        norm[t * hop:t * hop + size] += win ** 2
    out /= np.maximum(norm, 1e-3 * norm.max())
    return out[:, size:size + length]


def denoise(x, rate, noise, reduce_db=12.0, sensitivity=2.0, size=2048):
    """Spectral noise reduction: the noise's average power per frequency bin is learned from `noise` (channels x frames:
    a stretch of the same recording where only the noise sounds), then every bin of `x` whose power is not well above it
    is turned down, by up to `reduce_db`. A bin keeps the share of its power that stands over `sensitivity` times the
    noise's level (in amplitude: 2 = 6 dB over), and the gains are smoothed over three frames and three bins, so what is
    left of the noise does not warble. The gain is the same for every channel (the stereo image holds) and the phase is
    kept. Returns x's shape."""
    x = np.asarray(x, np.float64)
    noise = np.asarray(noise, np.float64)
    hop = size // 4
    if noise.shape[-1] < size:
        raise ValueError(f"learn the noise from at least {1000 * size / rate:.0f} ms of it")
    if not 0 <= float(reduce_db) <= 60:
        raise ValueError("reduce by 0 to 60 dB")
    N = _stft(noise, size, hop)[:, size // hop: noise.shape[-1] // hop + 1]   # the frames clear of _stft's padding
    profile = (np.abs(N) ** 2).mean(axis=(0, 1))                # per bin, over channels and frames
    X = _stft(x, size, hop)
    power = (np.abs(X) ** 2).mean(axis=0)                       # linked: one gain for all channels
    g = np.clip(1 - float(sensitivity) ** 2 * profile / np.maximum(power, 1e-20), 0, 1)
    k = np.ones(3) / 3
    g = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 0, g)   # over time
    g = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), 1, g)   # over frequency
    floor = 10 ** (-float(reduce_db) / 20)
    g = floor + (1 - floor) * g
    return _istft(X * g[None], size, hop, x.shape[-1])


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


# ---------------------------------------------------------------- recorded takes: pitch, edges, loop points

def yin(x, rate, fmin=40.0, fmax=4200.0, threshold=0.15):
    """The pitch of `x` (a short stretch: at least two periods of `fmin`) by YIN: the cumulative-mean-normalised
    difference function's first dip under `threshold`, refined by a parabola. Returns (hz, confidence 0-1) or
    (None, 0) for silence, a constant or noise."""
    m = _mono(x)
    tmax, tmin = int(rate / fmin), max(2, int(rate / fmax))
    w = len(m) - tmax
    if w < tmax // 2 or not np.ptp(m):
        return None, 0.0
    m = m - m.mean()
    size = 1 << int(np.ceil(np.log2(len(m) + w)))
    corr = np.fft.irfft(np.fft.rfft(m, size) * np.conj(np.fft.rfft(m[:w], size)), size)[: tmax + 1]
    e = np.concatenate([[0], np.cumsum(m * m)])
    energy = e[np.arange(tmax + 1) + w] - e[np.arange(tmax + 1)]
    d = energy[0] + energy - 2 * corr
    d[0] = 0
    cm = np.cumsum(d[1:])
    cmnd = np.ones(tmax + 1)
    cmnd[1:] = d[1:] * np.arange(1, tmax + 1) / np.maximum(cm, 1e-20)
    below = np.nonzero(cmnd[tmin:] < threshold)[0]
    if len(below):
        t = tmin + below[0]
        while t + 1 <= tmax and cmnd[t + 1] < cmnd[t]:
            t += 1
    else:
        t = tmin + int(np.argmin(cmnd[tmin:]))
        if cmnd[t] > 0.4:
            return None, 0.0
    if 1 <= t < tmax:
        a, b, c = cmnd[t - 1], cmnd[t], cmnd[t + 1]
        shift = 0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0.0
    else:
        shift = 0.0
    return rate / (t + max(-0.5, min(0.5, shift))), float(max(0.0, 1 - cmnd[t]))


def note_of(hz):
    """(note number as the song format counts them: C-5 = 60, A-5 = 440 Hz = 69; cents off it)."""
    exact = 69 + 12 * np.log2(hz / 440.0)
    n = int(round(exact))
    return n, float(100 * (exact - n))


def pitch_of(x, rate, fmin=27.5, fmax=4200.0):
    """The pitch a take holds (27.5 Hz to 4.2 kHz by default: the piano's A-1 to C-9): the median of YIN over frames of
    its louder half that YIN is sure of, each 2.5 periods of `fmin` long. Returns hz or None (a drum, noise,
    silence)."""
    m = _mono(x)
    # a take under 2.5 periods of fmin: from the lowest pitch it holds 2.5 periods of (40 Hz when shorter, as before)
    fmin = max(fmin, min(40.0, 2.5 * rate / max(1, len(m))))
    size = max(int(rate * 0.05), int(2.5 * rate / fmin))
    if len(m) < size:
        return None
    hop = size // 2
    starts = range(0, len(m) - size + 1, hop)
    level = np.array([np.sqrt(np.mean(m[s:s + size] ** 2)) for s in starts])
    loud = level >= np.median(level)
    found = [yin(m[s:s + size], rate, fmin, fmax) for s, ok in zip(starts, loud) if ok]
    hz = [h for h, conf in found if h and conf > 0.8]
    if len(hz) < max(1, len(found) // 3):
        return None
    hz = float(np.median(hz))
    # YIN takes two periods when one is no whole number of samples (a naive saw high up): then the spectrum holds the
    # even harmonics of what it read and not the odd ones, which a real pitch (a square, a missing fundamental) keeps
    if 2 * hz <= fmax and _odd_even(m[max(0, len(m) // 2 - rate // 2):][:rate], rate, hz) < 0.3:
        hz *= 2
    return hz


def _odd_even(m, rate, hz):
    """The spectrum's strongest odd harmonic of `hz` (1, 3, 5) over its strongest even one (2, 4, 6), each the peak within
    3 % of the harmonic; inf without even ones."""
    spec = np.abs(np.fft.rfft((m - m.mean()) * np.hanning(len(m))))
    f = np.fft.rfftfreq(len(m), 1 / rate)

    def level(k):
        band = (f > k * hz * 0.97) & (f < k * hz * 1.03)
        return spec[band].max() if k * hz < rate / 2 and band.any() else 0.0
    even = max(level(k) for k in (2, 4, 6))
    return max(level(k) for k in (1, 3, 5)) / even if even else float("inf")


def trim_edges(x, rate, db=-50.0, pre_ms=10, post_ms=50):
    """The span of `x` that sounds: from `pre_ms` before the first frame above `db` dBFS to `post_ms` after the last.
    Returns (a, b), or (0, 0) when nothing is that loud."""
    m = np.abs(np.asarray(x, float)).max(axis=0)
    loud = np.nonzero(m > 10 ** (float(db) / 20))[0]
    if not len(loud):
        return 0, 0
    return max(0, loud[0] - int(pre_ms * rate / 1000)), min(len(m), loud[-1] + 1 + int(post_ms * rate / 1000))


def find_loop(x, rate, hz=None, min_s=0.2):
    """Loop points for a sustained sound: its end a little before the sound fades (where it is still within 6 dB of its
    body), its start a whole number of periods earlier (the pitch from `hz`, else pitch_of), both on rising zero
    crossings, the pair picked for the best match of the waveform around them. Returns (start, end) with end
    exclusive, or None when no stretch holds steady long enough."""
    m = _mono(x)
    n = len(m)
    hz = hz or pitch_of(x, rate)
    blk = max(1, rate // 50)
    nb = n // blk
    if nb < 4:
        return None
    env = np.sqrt((m[: nb * blk].reshape(nb, blk) ** 2).mean(axis=1))
    body = np.median(env[env > env.max() * 0.05]) if np.any(env > env.max() * 0.05) else 0
    steady = np.nonzero(env > body / 2)[0]
    if not len(steady) or body <= 0:
        return None
    lo, hi = int(steady[0] + (steady[-1] - steady[0]) * 0.3) * blk, int(steady[-1]) * blk
    if (hi - lo) / rate < min_s:
        return None
    rising = np.nonzero((m[:-1] < 0) & (m[1:] >= 0))[0] + 1
    rising = rising[(rising >= lo) & (rising <= hi)]
    if len(rising) < 2:
        return None
    period = rate / hz if hz else None
    w = int(period * 2) if period else int(0.005 * rate)

    def match(s, e):
        a, b = m[max(0, s - w): s + w], m[max(0, e - w): e + w]
        k = min(len(a), len(b))
        a, b = a[-k:] if s - w < 0 else a[:k], b[:k]
        den = np.sqrt((a * a).sum() * (b * b).sum())
        return float((a * b).sum() / den) if den else -1.0
    ends = rising[rising >= rising[0] + int(min_s * rate)][-8:]
    best = None
    for e in ends:
        want = e - max(min_s * rate, (e - lo) * 0.8)
        if period:
            want = e - round((e - want) / period) * period
        cands = rising[(rising >= lo) & (rising <= e - min_s * rate)]
        if not len(cands):
            continue
        near = cands[np.argsort(np.abs(cands - want))[:6]]
        for s in near:
            score = match(int(s), int(e))
            if best is None or score > best[0]:
                best = (score, int(s), int(e))
    return (best[1], best[2]) if best else None


# ---------------------------------------------------------------- loudness, as ITU-R BS.1770-4 and EBU R 128 measure it

def _biquad_mag(f, b, a):
    z = np.exp(-2j * np.pi * f)
    return np.abs((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z))


def k_weighting(rate, taps=8191):
    """BS.1770's K-weighting (a high shelf, +4 dB above about 1.7 kHz, then a high-pass near 38 Hz) as a linear-phase
    FIR with the filters' magnitude at `rate`: the two biquads designed for any rate as pyloudnorm does (bilinear
    transform of the analogue prototypes), their magnitude sampled and windowed. Block energies only need magnitude."""
    G, f0, Q = 3.999843853973347, 1681.974450955533, 0.7071752369554196
    K, Vh = np.tan(np.pi * f0 / rate), 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    shelf = ([(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0],
             [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0])
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = np.tan(np.pi * f0 / rate)
    a0 = 1 + K / Q + K * K
    hp = ([1, -2, 1], [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0])
    f = np.fft.rfftfreq(taps + 1)
    mag = _biquad_mag(f, *shelf) * _biquad_mag(f, *hp)
    h = np.roll(np.fft.irfft(mag, taps + 1), taps // 2)[:taps] * np.blackman(taps)
    return h


def meter_series(x, rate, hop=0.1, ms=None):
    """A mix's meters over time (`x`: channels x frames, full scale 1.0), every `hop` seconds: the short-term loudness
    (EBU R128: K-weighted over the 3 s ending there, over what there is in the first 3 s; None under -70 LUFS) and, for
    two channels, each hop's sums of L*R, L*L and R*R, from which span_numbers takes the correlation of any span exactly.
    `ms`: the K-weighted squares per channel when the caller has them."""
    from .resample import fir_filter
    x = np.atleast_2d(np.asarray(x, float))
    if ms is None:
        h = k_weighting(rate)
        ms = [fir_filter(c, h) ** 2 for c in x]
    step, win = max(1, round(hop * rate)), round(3 * rate)
    n = x.shape[1] // step
    ends = (np.arange(n) + 1) * step
    starts = np.maximum(0, ends - win)
    z = sum((c[ends] - c[starts]) / (ends - starts) for c in (np.concatenate([[0.0], np.cumsum(m)]) for m in ms)) if n else np.zeros(0)
    short = -0.691 + 10 * np.log10(np.maximum(z, 1e-20))
    out = {"hop": hop, "short": [round(float(v), 2) if v > -70 else None for v in short], "full_from": win // step - 1}
    if x.shape[0] == 2 and n:
        seg = x[:, :n * step].reshape(2, n, step)
        g = lambda v: [float(f"{s:.5g}") for s in v]  # noqa: E731
        out.update(ab=g((seg[0] * seg[1]).sum(1)), aa=g((seg[0] ** 2).sum(1)), bb=g((seg[1] ** 2).sum(1)))
    return out


def loudness_range(series):
    """EBU Tech 3342's loudness range (LU) from meter_series: the short-term values of full 3 s windows, gated at
    -70 LUFS and 20 LU under their power mean, the 95th minus the 10th percentile; None with fewer than two."""
    v = np.array([s for s in series["short"][series.get("full_from", 0):] if s is not None], float)
    if len(v) < 2:
        return None
    v = v[v >= 10 * np.log10(np.mean(10 ** (v / 10))) - 20]
    return round(float(np.percentile(v, 95) - np.percentile(v, 10)), 2) if len(v) >= 2 else None


def span_numbers(series, t0, t1):
    """The meters of seconds t0..t1 from meter_series: the highest short-term loudness ending in it (`lufs_s`) and the
    stereo correlation of its hops (None for silence or one channel)."""
    hop = series["hop"]
    a, b = int(round(t0 / hop)), max(int(round(t0 / hop)) + 1, int(round(t1 / hop)))
    short = [s for s in series["short"][a:b] if s is not None]
    corr = None
    if "ab" in series and b > a:
        ab, aa, bb = (sum(series[k][a:b]) for k in ("ab", "aa", "bb"))
        corr = round(ab / (aa * bb) ** 0.5, 3) if aa > 1e-9 and bb > 1e-9 else None
    return {"lufs_s": max(short) if short else None, "correlation": corr}


def measure_mix(x, rate):
    """A mix's numbers (`x`: channels x frames, full scale 1.0): integrated loudness in LUFS (BS.1770-4: K-weighted,
    400 ms blocks every 100 ms, gated at -70 LUFS and 10 LU under the ungated mean), true peak in dBTP (4x
    oversampled), sample peak in dBFS, the stereo correlation of the sounding part (1 mono, 0 unrelated, -1 out of
    phase) and the loudness range in LU (EBU Tech 3342, `lra`). Measurements, not judgements: what they say about the
    sound is the listener's call."""
    from .resample import fir_filter, lowpass_fir
    x = np.atleast_2d(np.asarray(x, float))
    h = k_weighting(rate)
    ms = [fir_filter(c, h) ** 2 for c in x]
    block, hop = int(0.4 * rate), int(0.1 * rate)
    n = max(0, (x.shape[1] - block) // hop + 1)
    if n:
        cs = [np.concatenate([[0.0], np.cumsum(m)]) for m in ms]
        starts = np.arange(n) * hop
        z = sum((c[starts + block] - c[starts]) / block for c in cs)  # BS.1770's channel weights are 1 for L and R
        lk = -0.691 + 10 * np.log10(np.maximum(z, 1e-20))
        z = z[lk > -70]
        lufs = None
        if len(z):
            rel = -0.691 + 10 * np.log10(z.mean()) - 10
            z = z[-0.691 + 10 * np.log10(z) > rel]
            lufs = round(float(-0.691 + 10 * np.log10(z.mean())), 2) if len(z) else None
    else:
        lufs = None
    up = np.zeros((x.shape[0], x.shape[1] * 4))
    up[:, ::4] = x
    lp = lowpass_fir(0.125 * 0.98, 255) * 4
    tp = max(float(np.abs(fir_filter(c, lp)).max()) for c in up) if x.shape[1] else 0.0
    sp = float(np.abs(x).max()) if x.size else 0.0
    corr = None
    if x.shape[0] == 2:
        loud = (np.abs(x[0]) + np.abs(x[1])) > 10 ** (-60 / 20)
        a, b = x[0][loud], x[1][loud]
        den = np.sqrt((a * a).sum() * (b * b).sum())
        corr = round(float((a * b).sum() / den), 3) if den else None
    db = lambda v: round(20 * float(np.log10(v)), 2) if v > 0 else None  # noqa: E731
    return {"lufs": lufs, "true_peak_dbtp": db(tp), "peak_dbfs": db(sp), "correlation": corr,
            "lra": loudness_range(meter_series(x, rate, ms=ms)), "seconds": round(x.shape[1] / rate, 2)}


# ---------------------------------------------------------------- printed effects for a recipe's `fx:` (synth.py)
# Each takes the padded take (channels x frames, peak -1 dBFS) and the rate, and returns the same shape. `tail(**p)` is
# the seconds of padding an effect needs after the take, so `fx_tail` covers it. Ideas from LMMS's MultitapEcho,
# WaveShaper, SlewDistortion, FrequencyShifter, StereoEnhancer/StereoMatrix, Dispersion and GranularPitchShifter,
# reimplemented from the algorithms; no LMMS code.

def _fraction(v, what):
    """3/16, '3/16', 0.1875 -> 0.1875."""
    if isinstance(v, str) and "/" in v:
        a, _, b = v.partition("/")
        v = float(a) / float(b)
    v = float(v)
    if not 0 < v <= 16:
        raise ValueError(f"{what} is a note length in whole notes, e.g. 3/16 (a dotted eighth), got {v}")
    return v


def _pan_gains(pan):
    """Equal-power gains (left, right) for pan -1 (left) to 1 (right), 1 each in the centre."""
    a = (min(1.0, max(-1.0, float(pan))) + 1) * np.pi / 4
    return np.sqrt(2) * np.cos(a), np.sqrt(2) * np.sin(a)


def _one_pole(f, hz, rate, times=1):
    """A one-pole low-pass's magnitude at f (cycles per frame), `times` in series; hz None or 0: flat."""
    return 1.0 if not hz else (1 / np.sqrt(1 + (f * rate / float(hz)) ** 2)) ** times


def _taps(bpm, step, taps, count, decay_db_per_tap, lowpass_hz, pingpong):
    if taps is None:
        if not count:
            raise ValueError("multitap: give taps: [[gain_db, lowpass_hz, pan], ...] or count:")
        taps = [[decay_db_per_tap * (k + 1), lowpass_hz, (1 if k % 2 == 0 else -1) if pingpong else 0]
                for k in range(int(count))]
    if not 1 <= len(taps) <= 32:
        raise ValueError("multitap: 1 to 32 taps")
    out = []
    for t in taps:
        t = list(t) + [None, 0][len(t) - 1:] if isinstance(t, (list, tuple)) and 1 <= len(t) <= 3 else None
        if t is None:
            raise ValueError("multitap: each tap is [gain_db] or [gain_db, lowpass_hz] or [gain_db, lowpass_hz, pan]")
        out.append((float(t[0]), t[1] and float(t[1]), float(t[2] or 0)))
    return out


def multitap(x, rate, bpm, step, taps=None, count=None, decay_db_per_tap=-6.0, lowpass_hz=None, pingpong=False):
    """Echoes every `step` (a note length in whole notes at `bpm` quarter notes a minute): tap k at (k + 1) steps with
    its own gain, one-pole low-pass and pan (`taps`), or `count` taps each `decay_db_per_tap` quieter and low-passed
    once more than the one before, alternating right and left with `pingpong`. The dry take stays."""
    if not 20 <= float(bpm) <= 999:
        raise ValueError("multitap: bpm is 20 to 999")
    gap = _fraction(step, "multitap: step") * 4 * 60 / float(bpm)
    plan = _taps(bpm, step, taps, count, decay_db_per_tap, lowpass_hz, pingpong)
    n, out = x.shape[1], x.astype(np.float64)
    size = 1 << int(np.ceil(np.log2(max(2, 2 * n))))
    X, f = np.fft.rfft(x, size, axis=-1), np.fft.rfftfreq(size)
    for k, (db, hz, pan) in enumerate(plan):
        d = int(round((k + 1) * gap * rate))
        if d >= n:
            break
        times = k + 1 if taps is None else 1
        echo = np.fft.irfft(X * _one_pole(f, hz, rate, times), size, axis=-1)[:, :n - d] * 10 ** (db / 20)
        if x.shape[0] == 2 and pan:
            gl, gr = _pan_gains(pan)
            echo = echo * np.array([[gl], [gr]])
        out[:, d:] += echo
    return out.astype(x.dtype)


def _multitap_tail(bpm, step, taps=None, count=None, **_):
    return _fraction(step, "multitap: step") * 4 * 60 / float(bpm) * (len(taps) if taps is not None else int(count or 0))


SHAPES = {
    "tanh": np.tanh,
    "sine": lambda u: np.sin(np.pi / 2 * np.clip(u, -1, 1)),
    "foldback": lambda u: 1 - np.abs(np.mod(u + 1, 4) - 2),
    "rectify": lambda u: np.minimum(np.abs(u), 1),
    "half_rectify": lambda u: np.clip(u, 0, 1),
    "soft": lambda u: u / (1 + np.abs(u)),
}


def waveshape(x, rate, curve=None, shape=None, drive_db=0.0, mix=1.0):
    """Each sample through a transfer curve: `curve` [[in, out], ...] from 0 to 1 (linear between points, the sign
    kept), or a named `shape` (SHAPES), after `drive_db` of gain; `mix` of it over the dry take."""
    if (curve is None) == (shape is None):
        raise ValueError(f"waveshape: give curve: [[0, 0], [0.3, 0.6], [1, 1]] or shape: one of {', '.join(SHAPES)}")
    u = x.astype(np.float64) * 10 ** (float(drive_db) / 20)
    if shape is not None:
        if shape not in SHAPES:
            raise ValueError(f"waveshape: shape is one of {', '.join(SHAPES)}, got {shape!r}")
        y = SHAPES[shape](u)
    else:
        pts = np.asarray(curve, float)
        if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 2 or np.any(np.diff(pts[:, 0]) <= 0) \
                or pts[0, 0] < 0 or pts[-1, 0] > 1:
            raise ValueError("waveshape: curve is two or more [in, out] points with rising inputs from 0 to 1")
        y = np.sign(u) * np.interp(np.minimum(np.abs(u), 1), pts[:, 0], pts[:, 1])
    m = float(mix)
    return (m * y + (1 - m) * x).astype(x.dtype)


def slew(x, rate, up_db=0.0, down_db=0.0, drive_db=0.0, shape=None):
    """Each sample may rise at most 10^(up_db/20) and fall at most 10^(down_db/20) from the one before (full scale 1:
    -20 dB allows 0.1 a frame), the soft corners of a slow amplifier; then `drive_db` and an optional SHAPES `shape`."""
    if shape is not None and shape not in SHAPES:
        raise ValueError(f"slew: shape is one of {', '.join(SHAPES)}, got {shape!r}")
    up, down = 10 ** (float(up_db) / 20), 10 ** (float(down_db) / 20)
    y = np.empty(x.shape, np.float64)
    for c, ch in enumerate(x.astype(np.float64)):
        prev, row = 0.0, y[c]
        for i, v in enumerate(ch.tolist()):  # ponytail: a Python loop, a few seconds of sample per second; numba if slow
            d = v - prev
            prev += up if d > up else -down if d < -down else d
            row[i] = prev
    y *= 10 ** (float(drive_db) / 20)
    return (SHAPES[shape](y) if shape else y).astype(x.dtype)


def _analytic(x, size):
    """The analytic signal (Hilbert transform by FFT): the negative frequencies zeroed, the positive doubled."""
    X = np.fft.fft(x, size, axis=-1)
    h = np.zeros(size)
    h[0] = 1
    h[1:(size + 1) // 2] = 2
    if size % 2 == 0:
        h[size // 2] = 1
    return np.fft.ifft(X * h, axis=-1)


def shift(x, rate, hz, mix=1.0, ring=0.0):
    """Every partial moved by `hz` (a frequency shifter: inharmonic, unlike a pitch shift; negative moves down), with
    `ring` (0 to 1) of ring modulation by a `hz` sine crossfaded in, and `mix` of the result over the dry take."""
    n = x.shape[1]
    t = np.arange(n) / rate
    carrier = np.exp(2j * np.pi * float(hz) * t)
    shifted = np.real(_analytic(x.astype(np.float64), 1 << int(np.ceil(np.log2(max(2, 2 * n)))))[:, :n] * carrier)
    r, m = float(ring), float(mix)
    if not (0 <= r <= 1 and 0 <= m <= 1):
        raise ValueError("shift: ring and mix are 0 to 1")
    wet = (1 - r) * shifted + r * x * np.cos(2 * np.pi * float(hz) * t)
    return (m * wet + (1 - m) * x).astype(x.dtype)


def stereo(x, rate, width=1.0, haas_ms=0.0, swap=False, matrix=None):
    """A stereo take reshaped: `matrix` [[ll, lr], [rl, rr]] (out = matrix x in), then the side scaled by `width`
    (0 mono, 1 as is, 2 twice as wide), then the right channel delayed `haas_ms` (0 to 30), then `swap`."""
    if x.shape[0] != 2:
        raise ValueError("stereo: the take is mono here (mono: true or a mono source with mono kept); it needs two channels")
    y = x.astype(np.float64)
    if matrix is not None:
        mt = np.asarray(matrix, float)
        if mt.shape != (2, 2):
            raise ValueError("stereo: matrix is [[ll, lr], [rl, rr]]")
        y = mt @ y
    w = float(width)
    if not 0 <= w <= 4:
        raise ValueError("stereo: width is 0 to 4")
    mid, side = (y[0] + y[1]) / 2, (y[0] - y[1]) / 2 * w
    y = np.stack([mid + side, mid - side])
    d = int(round(float(haas_ms) * rate / 1000))
    if not 0 <= float(haas_ms) <= 30:
        raise ValueError("stereo: haas_ms is 0 to 30")
    if d:
        y[1] = np.concatenate([np.zeros(d), y[1]])[:y.shape[1]]
    return (y[::-1] if swap else y).astype(x.dtype)


def dispersion(x, rate, stages=8, hz=1000.0, q=0.7):
    """`stages` second-order all-passes (the RBJ cookbook's) at `hz` in series: every frequency kept at its level and
    delayed by its own amount, so a transient becomes a chirp. Applied as one complex response (_spectral)."""
    stages, hz, q = int(stages), float(hz), float(q)
    if not (1 <= stages <= 256 and 20 <= hz < rate / 2 and 0.05 <= q <= 20):
        raise ValueError("dispersion: stages 1 to 256, hz 20 to below half the rate, q 0.05 to 20")
    w0 = 2 * np.pi * hz / rate
    alpha = np.sin(w0) / (2 * q)
    b = np.array([1 - alpha, -2 * np.cos(w0), 1 + alpha])
    a = b[::-1]

    def response(f):
        z = np.exp(-2j * np.pi * f)
        return ((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)) ** stages
    return _spectral(x, response)


def _dispersion_tail(stages=8, hz=1000.0, q=0.7, **_):
    return int(stages) * 2 * float(q) / (np.pi * float(hz)) * 4  # four times the group delay at hz


GRAIN_SHAPES = {"hann": np.hanning, "triangle": np.bartlett, "rect": np.ones}


def granular(x, rate, grain_ms=80.0, density=4.0, pitch_st=0.0, jitter=0.0, spray_ms=0.0, shape="hann", seed=0):
    """A cloud of grains: every grain_ms / density a grain of `grain_ms` read from near the same time (`spray_ms`
    either side at random), played `pitch_st` semitones up or down (each `jitter` semitones more or less at random),
    shaped by a `shape` window and overlap-added; the length stays. Linear interpolation between frames: low-pass
    what a pitch up would lift over the ceiling first. `seed` makes the cloud repeatable."""
    g = int(float(grain_ms) * rate / 1000)
    if not (5 <= float(grain_ms) <= 1000 and 1 <= float(density) <= 32 and -24 <= float(pitch_st) <= 24
            and 0 <= float(jitter) <= 24 and 0 <= float(spray_ms) <= 2000):
        raise ValueError("granular: grain_ms 5 to 1000, density 1 to 32, pitch_st -24 to 24, jitter 0 to 24, "
                         "spray_ms 0 to 2000")
    if shape not in GRAIN_SHAPES:
        raise ValueError(f"granular: shape is one of {', '.join(GRAIN_SHAPES)}")
    n = x.shape[1]
    win = GRAIN_SHAPES[shape](g) if g > 1 else np.ones(1)
    hop = max(1, int(g / float(density)))
    rng = np.random.default_rng(int(seed))
    src = x.astype(np.float64)
    out, norm = np.zeros((x.shape[0], n + g)), np.zeros(n + g)
    spray = float(spray_ms) * rate / 1000
    for t in range(0, n, hop):
        ratio = 2 ** ((float(pitch_st) + rng.uniform(-1, 1) * float(jitter)) / 12)
        pos = min(max(0.0, t + rng.uniform(-1, 1) * spray), n - 1) + np.arange(g) * ratio
        ok = pos < n - 1
        i = pos.astype(int).clip(0, n - 2)
        frac = pos - i
        grain = (src[:, i] * (1 - frac) + src[:, i + 1] * frac) * (win * ok)
        out[:, t:t + g] += grain
        norm[t:t + g] += win
    return (out[:, :n] / np.maximum(norm[:n], 1e-3 * win.max())).astype(x.dtype)


def bandlimit(x, rate, hz):
    """Nothing above `hz` left: the compiler's own linear-phase sinc (resample.lowpass_fir, 1023 taps, a transition
    about 0.5 % of the rate wide, the stop band under -74 dB), steep enough that `check`'s upward ceiling measures the
    sample as `hz` wide. pedalboard's filters and resample leave more above their cutoff than that."""
    from .resample import fir_filter, lowpass_fir
    if not 100 <= float(hz) < rate / 2:
        raise ValueError("bandlimit: hz is 100 to below half the rate")
    h = lowpass_fir(float(hz) / rate)
    return np.stack([fir_filter(ch, h) for ch in x]).astype(x.dtype)


# name -> (function, tail in seconds from its parameters or None)
PRINTED = {"bandlimit": (bandlimit, None), "multitap": (multitap, _multitap_tail), "waveshape": (waveshape, None), "slew": (slew, None),
           "shift": (shift, None), "stereo": (stereo, lambda haas_ms=0, **_: float(haas_ms) / 1000),
           "dispersion": (dispersion, _dispersion_tail), "granular": (granular, None)}
