"""Resynthesis by blocks (numpy; Samplebrain's idea, nothing of its code): a target sound is cut into overlapping
blocks, each block is matched by timbre (MFCCs, library.py's mel bands) to a block of a corpus of other sounds, and the
matched corpus blocks, each brought to the target block's level, are overlap-added into a new sound that follows the
target's rhythm and loudness with the corpus's sounds. The recipe source `resynth:` (SAMPLING.md) calls `resynth`."""
import math

import numpy as np

from . import library


def blocks(x, size, hop):
    """Start frames of the blocks of `x` (the last one reaching past the end is dropped, but there is always one)."""
    return list(range(0, max(1, len(x) - size + 1), hop))


def block_features(x, starts, size, rate):
    """Per block: (12 MFCCs without the loudness coefficient, RMS level in dB)."""
    win = np.hanning(size)
    n_fft = 1 << int(math.ceil(math.log2(size)))
    seg = np.stack([np.pad(x[s:s + size], (0, max(0, s + size - len(x)))) for s in starts])
    power = np.abs(np.fft.rfft(seg * win, n_fft, axis=1)) ** 2
    mel = power @ library._mel(n_fft, rate).T
    db = 10 * np.log10(mel + 1e-12)
    db = np.maximum(db, db.max(axis=1, keepdims=True) - 80)  # per block: its own floor, so level does not steer timbre
    mfcc = db @ library._dct(library.N_MFCC, library.N_MELS).T
    level = 10 * np.log10((seg ** 2).mean(axis=1) + 1e-12)
    return mfcc[:, 1:], level


def resynth(target, corpus, rate, block=0.05, overlap=4, variety=1, reuse=0.0, level=1.0, mix=0.0, seed=0,
            gate=-60.0):
    """`target` (mono float array) rebuilt from blocks of the `corpus` arrays (mono, same rate).

    block: seconds per block; overlap: blocks per block length (the hop is block / overlap, Hann windows, summed to a
    constant); variety: pick at random among this many nearest corpus blocks (1: always the nearest); reuse: how much a
    corpus block used in the last 8 blocks is avoided (0: not at all, 1: about the spread of a typical match); level: how
    far each block follows the target block's loudness (1: fully, 0: the corpus block's own); mix: the target itself
    blended back in (0-1); gate: target blocks quieter than this (dBFS) stay silent. Returns (float array the target's
    length, {"blocks", "corpus_blocks", "distinct", "picks": [(target frame, corpus index, corpus frame)]})."""
    size = max(64, int(round(block * rate)))
    hop = max(1, size // max(1, int(overlap)))
    target = np.asarray(target, float)
    parts = [np.asarray(c, float) for c in corpus if len(c) >= size // 2]
    if not parts:
        raise ValueError("the corpus has no sound at least half a block long")
    pieces, owners = [], []
    for k, c in enumerate(parts):
        c = np.pad(c, (0, max(0, size - len(c))))
        parts[k] = c
        s = blocks(c, size, hop)
        pieces += s
        owners += [k] * len(s)
    cf, cl = [], []
    for k, c in enumerate(parts):  # per corpus file, then stacked (block_features pads a block past the end)
        f, lv = block_features(c, blocks(c, size, hop), size, rate)
        cf.append(f)
        cl.append(lv)
    cfeat, clevel = np.concatenate(cf), np.concatenate(cl)
    starts = blocks(np.pad(target, (0, max(0, size - len(target)))), size, hop)
    tpad = np.pad(target, (0, size + hop))
    tfeat, tlevel = block_features(tpad, starts, size, rate)
    scale = cfeat.std(axis=0) + 1e-6
    audible = clevel > gate
    if not audible.any():
        raise ValueError("the corpus is silent")
    rng = np.random.default_rng(seed)
    win = np.hanning(size)
    out = np.zeros(len(tpad))
    norm = np.zeros(len(tpad))
    recent, used, picks = [], set(), []
    typical = None
    for i, s in enumerate(starts):
        norm[s:s + size] += win
        if tlevel[i] <= gate:
            continue
        d = np.sqrt((((cfeat - tfeat[i]) / scale) ** 2).mean(axis=1))
        d[~audible] = np.inf
        if typical is None:
            typical = float(np.median(d[np.isfinite(d)])) or 1.0
        if reuse and recent:
            d[recent] += float(reuse) * typical
        pick = np.argsort(d)[: max(1, int(variety))]
        j = int(pick[rng.integers(len(pick))]) if len(pick) > 1 else int(pick[0])
        recent = (recent + [j])[-8:]
        used.add(j)
        k, cs = owners[j], pieces[j]
        picks.append((s, k, cs))
        seg = parts[k][cs:cs + size]
        seg = np.pad(seg, (0, size - len(seg)))
        g = 10 ** (float(level) * (tlevel[i] - clevel[j]) / 20)
        out[s:s + size] += seg * win * min(g, 16.0)  # at most +24 dB: a quiet corpus block is not blown up into noise
    out = out / np.maximum(norm, 1e-3 * norm.max())  # Hann at 1/overlap hops sums to a constant; the edges are divided back
    if level and picks:
        # unrelated blocks overlap-added sum their power, not their amplitude (about 4 dB under the target at 4x
        # overlap): the level per hop brought to the target's, `level` of the way, the gain interpolated between hops
        centres = np.array(starts) + size // 2
        got = 10 * np.log10(np.array([np.mean(out[s:s + size] ** 2) for s in starts]) + 1e-12)
        fix = np.where(tlevel > gate, np.clip(tlevel - got, -24, 12), 0.0) * float(level)
        out *= 10 ** (np.interp(np.arange(len(out)), centres, fix) / 20)
    out = out[: len(target)]
    if mix:
        out = (1 - float(mix)) * out + float(mix) * target
    return out, {"blocks": len(starts), "corpus_blocks": len(pieces), "distinct": len(used), "picks": picks}
