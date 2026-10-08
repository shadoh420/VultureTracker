"""Rift, layer 2 of BRIEF.md's layer plan: the lead call, written the way Nether Animal writes its lead (measured with
scratch/ut99-clean/melodic.py and checked against the cells; only the idioms and the sample character are taken, the
notes are ours).

`python suite/rift/gen_lead.py` makes the slot-9 candidates from the screened raw renders (samples/local/rift-cand/lead/,
each rooted at D-4) the way Nether's lead sample measures:
  - a one-shot, 5.57 s, starting at full level (0/10 ms to -10/-3 dB), decaying by itself (-8.5 dB/s, a 5 s tail),
    near-pure (2nd partial -23 dB), with an irregular slow vibrato (21 cents peak to peak around 2.1 Hz) and level
    wobble (3.3 dB around 1.6 Hz) and a floor of -19.9 dB
    (melodic.py's floor over the first 1.5 s from -3 dB), stored at 4.2 kHz (so nothing above 2.1 kHz) and played
    4-24 semitones up.
  - So each candidate sounds D-4 exactly (resampled from its measured pitch), is band-limited at 2.1 kHz, starts with a
    2 ms fade-in, is cut to 5.57 s from its onset with a 50 ms fade at the end, gets an irregular vibrato of 21 cents
    around 2.1 Hz when its own is under 10 and an irregular level wobble of 3 dB around 1.6 Hz when its own is under 2
    (both from band-limited noise, as melodic.py measures them), a floor shaped like its spectrum and following its
    envelope up to -19.9 dB when it is cleaner, and a level that puts its call 10.6 dB under the sub in the song. The
    decay and the partials are the source's own (the screen chose them for that).
  - Stored at 44.1 kHz, as the sequence is (the compiler's resampling clicked at loop points; these do not loop).
`python suite/rift/gen_lead.py pattern` writes the call into rift.yaml (channels 12-13, slot 9, instrument 9):
  - One call per pattern, in its first bar: three notes on the 8ths from row 2 (rows 2, 4, 6), alternating two
    channels, so each new note on a channel cuts the one before it; each channel then re-strikes its last note 4 and
    8 rows later at -6.6 and -11.5 dB (volumes in the reference's 30/14/8 ratio); both channels cut on row 32. In
    loop_b the call carries on instead: two new notes on rows 8 and 10 at the -6.6 dB level, each re-struck once 4
    rows later at -11.5 dB (the reference's variant). Each note fades on its own channel as the reference's do: the
    call's notes slide down 3 a tick for three rows (a fading gate before the next), the first re-strikes 1 a tick, the
    row-12 re-strike from two rows on; the last rings to the cut. Both channels centred: the reference's lead renders
    centred (its sample's own pan overrides the channel's).
  - Our notes, A minor: the call falls E C A (E-5 C-5 A-4); the variant goes on to D and G (D-5 G-4). (E D A was
    dropped: its two intervals open one of the reference's calls.)
  - Volumes are the reference's (30/14/8); the samples' gain sets the level (faders stay at 64): the call 10.6 dB under
    the sub, as in the reference.
Channels 1-11 are not touched.
Since Step 3 (the form) rift.yaml has no `loop`/`loop_b`: gen_form.py writes it from this writer's pattern
functions (figure(), or the form's variants beside it where there are any), and `pattern` stops there with a
message; pattern(path) still writes the loop song, rift_loop.yaml.
"""
import math
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "suite" / "nadir"))
from vulturetracker.resample import fir_filter, lowpass_fir, resample  # noqa: E402
from vulturetracker.wavload import read_wav, write_wav  # noqa: E402
from gen_floor import envelope_spectrum, shaped_noise  # noqa: E402
from gen_seq import f0_near, ensure_channels, write_columns  # noqa: E402

OUT = ROOT / "samples" / "local" / "rift-cand"
RAW = OUT / "lead"
RATE = 44100
ROOT_NOTE, F_ROOT = 50, 440 * 2 ** ((50 - 69) / 12)      # D-4: 146.83 Hz
SECS, FADE = 5.57, 0.05
BANDWIDTH = 2110.0
VIB_HZ, VIB_CENTS = 2.1, 21.0
TREM_HZ, TREM_DB = 1.6, 3.0                                # the reference's level movement: 1.6 Hz, 3.3 dB spread over its decay
FLOOR_DB = -19.9
RMS_DB = -10.1                                            # the call 10.6 dB under the sub at the reference's v30

# candidate -> raw (relative to RAW), five of the sixteen finalists of three screens (about 1100 patches and files measured
# against the class: a one-shot at D-4, -3 dB within ~20 ms, falling 4-15 dB/s by itself, 2nd partial -15 to -35 dB, no
# partials off the series); no factory voice passed as is, so each is trimmed. The recipes that made them:
# lead/dexed/lead_dexed.yaml (Dexed params), lead/surge/recipe.yaml with the edited copies in lead/surge/fxp/ (all FX off,
# the amp EG a one-shot; Surge re-applies a loaded patch over host params, so the edits live in the .fxp), OB-Xd by name.
# The glasses were left out: the sequence's glass came from the same VCSL set.
CANDS = {
    "lead_cry": "dexed/dx_cry.wav",             # Dexed SynprezFM_04 Annie'sCry trimmed: the purest (2nd -20, 3rd -41 dB),
                                                # its own 19 c vibrato at 2.4 Hz, falls 15 dB in 1 s then slower, tail 3.4 s
    "lead_rhodes": "dexed/dx_rhodes.wav",       # Dexed SynprezFM_02 FmRhodes18 trimmed: FM piano, 2nd -16 dB, 7 dB/s, 5.1 s
    "lead_suffer": "surge/lead_suffer.wav",     # Surge Zoozither Suffer as a one-shot: 2nd -31, 3rd -27 dB, its own 14-18 c
                                                # of pitch wander (no clear rate), 10.7 dB/s, 3.6 s
    "lead_harp": "obxd_cc0/cc0_harp_f4.wav",    # VSCO 2 harp F4 (CC0), recorded: KSHarp_F4_mf.wav resampled -15 semitones
                                                # to sound D3, the finger noise before the pluck cut; 2nd/3rd -18/-17 dB, 7 dB/s
    "lead_tile": "obxd_cc0/obxd_tile_drop.wav",  # OB-Xd 005 Keys "Tile Drop": a self-resonant filter ping with its own noise
                                                # floor, 3rd over 2nd (-21/-31 dB), 12 dB/s, 3.3 s (takes vary: this take)
}

# per candidate, dB so each call sits 10.6 dB under the sub in the song (measured); the harp's pluck and the tile's ping
# reach the -1 dBFS peak limit first, so those two stay a little under
GAIN = {"lead_rhodes": 0.9, "lead_harp": 1.9}


def floor_db(x, rate):
    """melodic.py's floor: per third-octave band from 100 Hz, the median bin stands for the floor, against the whole."""
    n = min(4096, 1 << int(np.log2(max(len(x), 256))))
    hop = n // 2
    P = np.zeros(n // 2 + 1)
    for i in range(max(1, (len(x) - n) // hop + 1)):
        s = x[i * hop: i * hop + n]
        P += np.abs(np.fft.rfft(np.pad(s, (0, n - len(s))) * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / rate)
    fl = tot = 0.0
    lo = 100.0
    while lo * 2 ** (1 / 3) < 0.9 * rate / 2:
        sel = (f >= lo) & (f < lo * 2 ** (1 / 3))
        if sel.sum() >= 3:
            fl += min(np.median(P[sel]) * sel.sum(), P[sel].sum())
            tot += P[sel].sum()
        lo *= 2 ** (1 / 3)
    return 10 * np.log10(fl / tot + 1e-30)


def floor_stored(y):
    """The floor as melodic.py measured the reference (a 4096-point FFT on a sample stored at 4.2 kHz, 1 Hz bins): the
    steady part decimated to 4.41 kHz first, which loses nothing under the 2.1 kHz band limit."""
    return floor_db(resample(steady(y), RATE, 4410), 4410)


def steady(y):
    """melodic.py's steady part of a one-shot: from -3 dB of its peak, up to 1.5 s."""
    hop = RATE // 100
    env = np.sqrt(np.convolve(y * y, np.ones(hop) / hop, mode="same"))
    a = int(np.nonzero(env >= env.max() * 10 ** (-3 / 20))[0][0])
    return y[a: a + int(1.5 * RATE)]


def yin(x, rate, fmin=15.0, fmax=2500.0, thr=0.12):
    """f0 (Hz) and aperiodicity (0 = periodic) of a frame, by YIN's cumulative mean normalised difference (the same code as
    scratch/ut99-clean/melodic.py, so the vibrato is measured the way the reference's was)."""
    x = np.asarray(x, float) - np.mean(x)
    W = len(x) // 2
    tmax = min(W - 1, int(rate / fmin) + 1)
    tmin = max(2, int(rate / fmax))
    if tmax <= tmin + 2 or not x.any():
        return None, 1.0
    m = 1 << int(math.ceil(math.log2(2 * len(x))))
    corr = np.fft.irfft(np.fft.rfft(x, m) * np.conj(np.fft.rfft(x[:W], m)), m)[:tmax]
    e = np.concatenate([[0.0], np.cumsum(x * x)])
    tau = np.arange(tmax)
    d = e[W] + (e[tau + W] - e[tau]) - 2 * corr
    d[0] = 0
    c = np.ones(tmax)
    c[1:] = d[1:] * tau[1:] / np.maximum(np.cumsum(d[1:]), 1e-12)
    below = np.nonzero(c[tmin:] < thr)[0]
    if len(below):
        t = below[0] + tmin
        while t + 1 < tmax and c[t + 1] < c[t]:
            t += 1
    else:
        t = int(np.argmin(c[tmin:])) + tmin
    shift = 0.0
    if 1 <= t < tmax - 1:
        a, b, cc = c[t - 1], c[t], c[t + 1]
        den = a - 2 * b + cc
        shift = 0.5 * (a - cc) / den if den else 0.0
    return rate / (t + shift), float(c[t])


def vibrato_cents(y):
    """Vibrato over the steady part as melodic.py measures it: a YIN track (140 ms frames, 10 ms hop, aperiodicity under
    0.25), detrended; depth = its spread as a sine's peak to peak, rate = its strongest 2-12 Hz component."""
    s = steady(y)
    fl, hop = int(0.14 * RATE), int(0.01 * RATE)
    tr = [(i / RATE, *yin(s[i: i + fl], RATE)) for i in range(0, max(1, len(s) - fl), hop)]
    tr = [(t, f) for t, f, ap in tr if f and ap < 0.25]
    t, f = np.array([a for a, _ in tr]), np.array([b for _, b in tr])
    c = 1200 * np.log2(f / np.median(f))
    t, c = t[np.abs(c) < 300], c[np.abs(c) < 300]
    det = c - np.polyval(np.polyfit(t, c, 1), t)
    spec = np.abs(np.fft.rfft(det * np.hanning(len(det)), 1024))
    fr = np.fft.rfftfreq(1024, 0.01)
    k = int(np.argmax(spec * ((fr >= 2) & (fr <= 12))))
    return 2 * np.sqrt(2) * np.std(det), fr[k]


def wander(n, lo, hi, seed):
    """A smooth irregular movement: noise at a 100 Hz control rate kept between `lo` and `hi` Hz, unit spread, `n`
    audio samples long. The reference's movement is irregular (its vibrato's prominence is 3, a sine's is 10 or more)."""
    m = int(n / RATE * 100) + 2
    spec = np.fft.rfft(np.random.default_rng(seed).standard_normal(m))
    fr = np.fft.rfftfreq(m, 0.01)
    w = np.fft.irfft(spec * ((fr >= lo) & (fr <= hi)), m)
    w /= np.std(w) + 1e-12
    return np.interp(np.arange(n) / RATE * 100, np.arange(m), w)


def add_vibrato(y, cents, seed):
    """Pitch moved by `cents` peak to peak (as melodic.py measures it: 2.8 x the spread) around VIB_HZ, irregularly:
    the sample read at a varying speed."""
    dev = wander(len(y), VIB_HZ * 0.7, VIB_HZ * 1.4, seed) * cents / (2 * np.sqrt(2))
    ratio = 2 ** (dev / 1200)
    pos = np.cumsum(ratio) - ratio[0]
    return np.interp(pos, np.arange(len(y)), y, right=0.0)


def level_dev(y):
    """melodic.py's level deviation: the 10 ms envelope in dB over the steady part, a line taken out, its spread."""
    s = steady(y)
    hop = RATE // 100
    e = 10 * np.log10(np.array([np.mean(s[i: i + hop] ** 2) for i in range(0, len(s) - hop, hop)]) + 1e-20)
    live = e > e.max() - 40
    tt = np.arange(len(e))[live]
    return float(np.std(e[live] - np.polyval(np.polyfit(tt, e[live], 1), tt)))


def add_wobble(y, db, seed):
    """Level moved irregularly around TREM_HZ with a spread of `db` dB, faded in over 0.4 s so the onset stays the
    loudest point (the reference's peak is at its start)."""
    g = wander(len(y), TREM_HZ * 0.6, TREM_HZ * 1.4, seed) * db * np.minimum(1, np.arange(len(y)) / (0.4 * RATE))
    return y * 10 ** (g / 20)


def make(cand, raw, gain_db=0.0):
    w = read_wav(RAW / raw)
    x = np.asarray(w.channels, float).mean(axis=0) / 2 ** (w.bits - 1)
    on = int(np.nonzero(np.abs(x) > np.abs(x).max() * 10 ** (-30 / 20))[0][0])
    f0 = f0_near(x[on + int(0.1 * w.rate): on + int(0.6 * w.rate)], w.rate, F_ROOT)
    y = resample(x[on:], w.rate * F_ROOT / f0, RATE)                        # relabelled so it sounds D-4, then stored
    y = fir_filter(y, lowpass_fir(BANDWIDTH / RATE))
    fi = round(0.002 * RATE)                                                 # 2 ms in (the reference rises over 1-2 ms)
    y[:fi] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(fi) / fi)
    n = round(SECS * RATE)
    y = np.pad(y, (0, max(0, n - len(y))))[:n]
    seed = sum(map(ord, cand))
    vib, vhz = vibrato_cents(y)
    if vib < 10:
        y = add_vibrato(y, VIB_CENTS, seed)
    lev = level_dev(y)
    if lev < 2:
        y = add_wobble(y, TREM_DB, seed + 1)
    own = floor_stored(y)
    g_db = None
    if own < FLOOR_DB - 1:
        f, S = envelope_spectrum(y, RATE)
        noise = fir_filter(shaped_noise(len(y), RATE, f, S, seed=len(y)), lowpass_fir(BANDWIDTH / RATE))
        hop = RATE // 100
        env = np.sqrt(np.convolve(y * y, np.ones(hop) / hop, mode="same"))
        noise *= env / (np.sqrt(np.mean(noise ** 2)) + 1e-12)                # follows the envelope, at the tone's level
        lo, hi = -60.0, 0.0
        for _ in range(30):                                                  # the gain that puts the floor at FLOOR_DB
            g_db = (lo + hi) / 2
            z = y + noise * 10 ** (g_db / 20)
            lo, hi = (g_db, hi) if floor_stored(z) < FLOOR_DB else (lo, g_db)
        y = y + noise * 10 ** (g_db / 20)
    fl = floor_stored(y)
    fade = round(FADE * RATE)
    y[-fade:] *= np.linspace(1, 0, fade)
    y *= 10 ** ((RMS_DB + gain_db) / 20) / np.sqrt(np.mean(y[:RATE] ** 2))
    peak = np.abs(y).max()
    if peak > 10 ** (-1 / 20):
        y *= 10 ** (-1 / 20) / peak
    pcm = np.clip(np.round(y * 32767), -32768, 32767).astype(int).tolist()
    write_wav(OUT / f"{cand}.wav", RATE, [pcm], 16, root_note=ROOT_NOTE)
    print(f"{cand:14s} <- {raw:28s} {len(y) / RATE:.2f} s, was {1200 * np.log2(f0 / F_ROOT):+.1f} c, own vibrato {vib:.0f} c "
          f"at {vhz:.1f} Hz" + (f" -> {VIB_CENTS:.0f} c around {VIB_HZ} Hz added" if vib < 10 else "")
          + f", level wobble {lev:.1f} dB" + (f" -> {TREM_DB} dB around {TREM_HZ} Hz added" if lev < 2 else "")
          + f", own floor {own:.1f} dB"
          + (f", noise at {g_db:+.1f} dB" if g_db is not None else "") + f", floor now {fl:.1f} dB")


# ------------------------------------------------------------------------------------------------ the pattern

CALL = ["E-5", "C-5", "A-4"]                          # rows 2, 4, 6 of the first bar, channels A B A
MORE = ["D-5", "G-4"]                                 # loop_b: rows 8 and 10, channels B A
VOL = 30                                              # the reference's volumes, 30/14/8; the level comes from the samples' gain
LEVELS = (1.0, 14 / 30, 8 / 30)
# the fade written after each note on its own channel (the reference's, the same in all its calls): the call's notes
# slide down 3 a tick for three rows, the first re-strikes 1 a tick, the row-12 re-strike from two rows on for four
FADES = {2: ["D03", "D00", "D00"], 4: ["D03", "D00", "D00"], 6: ["D03", "D00", "D00"], 8: ["D01", "D00", "D00"],
         10: ["D01", "D00", "D00"], 12: [None, "D01", "D00", "D00", "D00"]}
PATTERNS = ["loop", "loop_b"]
CHANNELS = """    - {name: Lead A, pan: 32, volume: 64}
    - {name: Lead B, pan: 32, volume: 64}
"""


def figure():
    v = [max(1, round(VOL * k)) for k in LEVELS]
    cols = {p: [dict(), dict()] for p in PATTERNS}
    for p in PATTERNS:
        a, b = cols[p]
        a[2], b[4], a[6] = f"{CALL[0]} 09 v{v[0]:02d}", f"{CALL[1]} 09 v{v[0]:02d}", f"{CALL[2]} 09 v{v[0]:02d}"
        if p == "loop":                                # each channel re-strikes its last note +4 and +8 rows
            b[8], a[10] = f"{CALL[1]} 09 v{v[1]:02d}", f"{CALL[2]} 09 v{v[1]:02d}"
            b[12], a[14] = f"{CALL[1]} 09 v{v[2]:02d}", f"{CALL[2]} 09 v{v[2]:02d}"
        else:                                          # the variant: two new notes, each re-struck once
            b[8], a[10] = f"{MORE[0]} 09 v{v[1]:02d}", f"{MORE[1]} 09 v{v[1]:02d}"
            b[12], a[14] = f"{MORE[0]} 09 v{v[2]:02d}", f"{MORE[1]} 09 v{v[2]:02d}"
        for ch in (a, b):
            for r0 in sorted(ch):
                for k, fx in enumerate(FADES.get(r0, []), start=1):
                    if fx and r0 + k not in ch:
                        ch[r0 + k] = f"... .. ... {fx}"
        a[32] = b[32] = "^^^"
    return cols


def pattern(path=HERE / "rift.yaml", first_sample="lead_placeholder.wav"):
    b = path.read_bytes()
    crlf = b"\r\n" in b
    t = b.decode("utf-8").replace("\r\n", "\n")
    t = ensure_channels(t, CHANNELS, r"    - \{name: Seq copy 3[^\n]*\n")   # the owner's lines stay
    if "\n  9: {file:" not in t:
        line9 = f"  9: {{file: ../../samples/local/rift-cand/{first_sample}, base_note: D-4, name: {Path(first_sample).stem}}}\n"
        anchor = "\n\ninstruments:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + line9 + "\ninstruments:\n", 1)
    if "\n  9: {name: Lead" not in t:
        ins9 = "  9: {name: Lead, sample: 9}   # sample mode, as in the reference: the call's movement is in the pattern\n"
        anchor = "\n\npatterns:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + ins9 + "\npatterns:\n", 1)
    t = write_columns(t, 11, figure())
    if crlf:
        t = t.replace("\n", "\r\n")
    path.write_bytes(t.encode("utf-8"))
    print(f"wrote channels 12-13 into {path.name}: call {' '.join(CALL)}, variant + {' '.join(MORE)}, v{VOL}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["pattern"]:
        pattern(first_sample=next(iter(CANDS), "lead_placeholder") + ".wav")
    else:
        for cand, raw in CANDS.items():
            if not sys.argv[1:] or cand in sys.argv[1:]:
                make(cand, raw, GAIN.get(cand, 0.0))
