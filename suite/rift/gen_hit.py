"""Rift, layer 3 of BRIEF.md's layer plan: the tonal hit, written the way Nether Animal writes its tonal hit (measured with
scratch/ut99-clean/melodic.py and checked against the cells and the WAV; only the idioms and the sample character are
taken).

`python suite/rift/gen_hit.py` makes the slot-10 candidates from the screened raw hits (samples/local/rift-cand/hit/, each
sounding G-5) the way Nether's hit sample measures:
  - a one-shot of 3.82 s that starts at full level (0/20 ms to -10/-3 dB) and falls about 6 dB a second; a strong
    fundamental with the octave 20 dB down and little above (-60 dB by 1.6 kHz); rough: noise between its partials (a
    floor of -8.6 dB, melodic.py's measure at its 25.8 kHz storage rate) and 63 peaks off the harmonic series; an
    unsteady pitch (31 cents peak to peak around 5.9 Hz, sagging 7 cents a second) and a level flutter (3 dB around
    12 Hz); stored a whole tone under the note it plays; pitched between the root and the minor second (43-85 cents
    above the other layers' root).
  - So each candidate is pitched to sound G-5 +60 cents (played as A-5, a tone up, it sounds A +60 cents), band-limited at
    2 kHz, cut to 3.82 s; an irregular pitch wobble around 5.9 Hz, 31 cents (topped up to that if the sound already moves
    at 4-8 Hz), then its drift measured and brought to -7 cents a second; an irregular level flutter around 12 Hz, 3.1 dB
    (the same rule, 8-16 Hz; faded in over 0.3 s); noise shaped like the sound's spectrum under the band for the floor
    (-8.6 dB, measured at 25.8 kHz) and a quiet hiss up to 9.5 kHz for the reference's share above 5 kHz as played
    (-53.1 dB), both following the envelope; the sound shifted by up to 60 frames so the offset frame is the nearer side
    of a zero crossing; a 2 ms fade-in and a 50 ms fade-out last; a level that puts the hits 12.4 dB under the sub in the
    song (the -1 dBFS peak limit counts from the offset on; the 87 ms before it, which the song never plays, is held under
    the played part's peak). All measured over melodic.py's steady part (from -3 dB of the peak, up to 1.5 s, while within
    30 dB of it). A sound's own slower movement, its partials and its decay stay its own: matching those to the
    reference's curve would rebuild its sample.
  - Stored at 44.1 kHz (the compiler's resampling clicked at loop points; these do not loop, so it is only for parity).
`python suite/rift/gen_hit.py pattern` writes the hits into rift.yaml (channels 14-15, slot 10, instrument 10):
  - One hit on row 0 of every bar, alternating two channels (so each rings two bars, until that channel's next hit), each
    started 2.3 % into the sample (O0F: 3840 frames of 44.1 kHz; the reference's O09 of its 25.8 kHz sample), one volume
    (v64), no other movement in the pattern; centred.
  - The note is A-5 (the root, detuned by the sample); the level comes from the samples' gain (faders stay at 64).
Channels 1-13 are not touched.
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
import gen_lead  # noqa: E402  (the measuring and movement helpers: floor_db, yin, wander)

OUT = ROOT / "samples" / "local" / "rift-cand"
RAW = OUT / "hit"
RATE = 44100
ROOT_NOTE = 67                                            # G-5 (the tracker's C-5 is 60)
F_G5 = 440 * 2 ** ((ROOT_NOTE - 69) / 12)                 # 392.0 Hz
DETUNE = 60.0                                             # cents over the note, between the root and the minor second
SECS, FADE = 3.82, 0.05
BANDWIDTH = 2000.0                                        # the reference's content ends near 1.6 kHz (-60 dB)
HISS_BW = 9500.0                                          # a quiet hiss up the band, stopping at 9.5 kHz (10.7 kHz as played),
HF_CUT, HF_DB = 4455.0, -53.1                             # under the drums' top (11.9 kHz), set so the share of the steady part
                                                          # above 4.46 kHz (above 5 kHz once played a tone up) is the reference's
WOB_HZ, WOB_CENTS, SAG = 5.9, 31.0, -7.0                  # pitch: irregular wobble, and a sag in cents a second
FLUT_HZ, FLUT_DB = 12.0, 3.1                              # level flutter
FLOOR_DB, FLOOR_RATE = -8.6, 25773                        # the reference's floor, measured at its storage rate
RMS_DB = -18.0

# candidate -> raw (relative to RAW): five of thirteen finalists of three screens (468 recordings and patches measured against
# the class: a pitched one-shot sounding G-5, full level within 30 ms, falling 3-10 dB/s, the fundamental strongest with the
# octave 10-30 dB down, rough by noise, inharmonic partials, beating or pitch wobble), one per kind of roughness. Recipes:
# hit/rec/recipe.yaml (recordings resampled to G-5 first), hit/surge/recipe.yaml with edited .fxp copies (FX off, the amp
# EG a one-shot), hit/dx_obxd/ (Dexed and OB-Xd with a few envelope edits).
CANDS = {
    "hit_vibes": "dx_obxd/hit_vibes.wav",            # OB-Xd 005 "Vibes OB-Xd": partials 1 and 2 only (-12 dB), beating and tremolo
    "hit_tape": "surge/hit_tape.wav",                # Surge Cybersoda "Tape Keys" as a one-shot: one sine, 17 c wobble, sagging
    "hit_kalimba": "rec/hit_rec_kalimba_noise.wav",  # VCSL kalimba D#4 tine (CC0), recorded: noisy, a tine partial near 6x
    "hit_bells": "surge/hit_handbells.wav",          # Surge John Valentine "Handbells" as a one-shot: FM, partials 32 c off the
                                                     # series, the 4th and 6th at -24/-26 dB, 8.6 dB/s (the tube bell was dropped:
                                                     # its pitch reads an octave low and it swells where the reference decays)
    "hit_mayan": "dx_obxd/hit_mayan.wav",            # Dexed SynprezFM_11 "Mayan Vibs": a smeared fundamental, 23 c wobble at 2 Hz
}
# per candidate, dB so the hits sit 12.4 dB under the sub in the song (measured with the offset: a fast pluck loses most
# of its energy in the 87 ms the offset skips)
GAIN = {"hit_vibes": -2.3, "hit_tape": -4.4, "hit_kalimba": 2.9, "hit_bells": -2.1, "hit_mayan": -2.9}
SKIP = 3840                                               # frames the pattern's offset (O0F) skips


def steady(y):
    """melodic.py's steady part of a one-shot: from -3 dB of its peak, for up to 1.5 s while within 30 dB of the peak."""
    hop = RATE // 100
    env = np.sqrt(np.convolve(y * y, np.ones(hop) / hop, mode="same"))
    top = env.max()
    a = int(np.nonzero(env >= top * 10 ** (-3 / 20))[0][0])
    low = np.nonzero(env[a::hop] < top * 10 ** (-30 / 20))[0]
    b = a + (int(low[0]) * hop if len(low) else len(y) - a)
    return y[a: min(b, a + int(1.5 * RATE))]


def floor_ref(y):
    """The floor as melodic.py measured the reference (4096-point FFT on a sample stored at 25.8 kHz)."""
    return gen_lead.floor_db(resample(steady(y), RATE, FLOOR_RATE), FLOOR_RATE)


def movement(y):
    """Over the steady part, as melodic.py measures it: pitch movement (depth: 2.8 x the spread of the detrended YIN
    track; rate: its strongest 2-12 Hz component; drift: the track's slope, cents a second) and level movement (the
    spread of the detrended 10 ms envelope in dB; rate: its strongest 1-20 Hz component)."""
    s = steady(y)
    fl, hop = int(0.14 * RATE), int(0.01 * RATE)
    tr = [(i / RATE, *gen_lead.yin(s[i: i + fl], RATE)) for i in range(0, max(1, len(s) - fl), hop)]
    tr = [(t_, f) for t_, f, ap in tr if f and ap < 0.25]
    m = dict(pitch=0.0, prate=0.0, drift=0.0)
    if len(tr) >= 8:
        tt, f = np.array([a_ for a_, _ in tr]), np.array([b_ for _, b_ in tr])
        c = 1200 * np.log2(f / np.median(f))
        tt, c = tt[np.abs(c) < 300], c[np.abs(c) < 300]
        k = np.polyfit(tt, c, 1)
        det = c - np.polyval(k, tt)
        spec = np.abs(np.fft.rfft(det * np.hanning(len(det)), 1024))
        fr = np.fft.rfftfreq(1024, 0.01)
        m.update(pitch=2 * math.sqrt(2) * float(np.std(det)), drift=float(k[0]),
                 prate=float(fr[int(np.argmax(spec * ((fr >= 2) & (fr <= 12))))]))
    e = 10 * np.log10(np.array([np.mean(s[i: i + hop] ** 2) for i in range(0, len(s) - hop, hop)]) + 1e-20)
    live = e > e.max() - 40
    tt = np.arange(len(e))[live] * 0.01
    det = e[live] - np.polyval(np.polyfit(tt, e[live], 1), tt)
    spec = np.abs(np.fft.rfft(det * np.hanning(len(det)), 2048))
    fr = np.fft.rfftfreq(2048, 0.01)
    m.update(level=float(np.std(det)), lrate=float(fr[int(np.argmax(spec * ((fr >= 1) & (fr <= 20))))]))
    return m


def flatness_ref(y):
    """melodic.py's flatness (50 Hz to 90 % of Nyquist, at most 12 kHz) of the steady part at the reference's 25.8 kHz."""
    s = resample(steady(y), RATE, FLOOR_RATE)
    n = min(8192, 1 << int(math.log2(max(256, len(s)))))
    P = np.array([np.abs(np.fft.rfft(s[i: i + n] * np.hanning(n))) ** 2 for i in range(0, max(1, len(s) - n + 1), n // 4)])
    L = P.mean(axis=0)
    fq = np.fft.rfftfreq(n, 1 / FLOOR_RATE)
    band = (fq >= 50) & (fq <= min(FLOOR_RATE / 2 * 0.9, 12000))
    return float(10 * math.log10(np.exp(np.mean(np.log(L[band] + 1e-20))) / (np.mean(L[band]) + 1e-20)))


def hf_share(y):
    """dB of the steady part's energy above HF_CUT against all of it above 50 Hz."""
    s = steady(y)
    P = np.abs(np.fft.rfft(s * np.hanning(len(s)))) ** 2
    f = np.fft.rfftfreq(len(s), 1 / RATE)
    return float(10 * np.log10(P[f >= HF_CUT].sum() / P[f >= 50].sum() + 1e-30))


def bisect(fn, target, lo, hi, steps=20):
    """The x in [lo, hi] where the rising fn(x) reaches target."""
    for _ in range(steps):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fn(mid) < target else (lo, mid)
    return (lo + hi) / 2


def make(cand, raw, gain_db=0.0):
    w = read_wav(RAW / raw)
    x = np.asarray(w.channels, float).mean(axis=0) / 2 ** (w.bits - 1)
    on = int(np.nonzero(np.abs(x) > np.abs(x).max() * 10 ** (-30 / 20))[0][0])
    f0 = f0_near(x[on + int(0.05 * w.rate): on + int(0.5 * w.rate)], w.rate, F_G5)
    target = F_G5 * 2 ** (DETUNE / 1200)
    y = resample(x[on:], w.rate * target / f0, RATE)                        # relabelled so it sounds G-5 +60 c
    y = fir_filter(y, lowpass_fir(BANDWIDTH / RATE))
    n = round(SECS * RATE)
    y = np.pad(y, (0, max(0, n - len(y))))[:n]
    seed = sum(map(ord, cand))
    tt = np.arange(n) / RATE
    m = movement(y)
    notes = []

    def bend(cents):
        ratio = 2 ** (cents / 1200)
        pos = np.cumsum(ratio) - ratio[0]
        return np.interp(pos, np.arange(n), y, right=0.0)

    # pitch: the reference wobbles around 5.9 Hz; a sound already moving there tops up to 31 cents, any other gets all 31
    # (its own slower or faster movement is its character and stays); then the drift is measured and brought to -7 c/s
    in_rate = 4 <= m["prate"] <= 8
    wob = None if in_rate and m["pitch"] >= 20 else (math.sqrt(max(WOB_CENTS ** 2 - m["pitch"] ** 2, 15.0 ** 2)) if in_rate else WOB_CENTS)
    if wob:
        y = bend(gen_lead.wander(n, WOB_HZ * 0.85, WOB_HZ * 1.2, seed) * wob / (2 * math.sqrt(2)))
        notes.append(f"wobble {wob:.0f} c around {WOB_HZ} Hz")
    drift = movement(y)["drift"]
    if abs(SAG - drift) > 1:
        y = bend((SAG - drift) * tt)
        notes.append(f"drift {drift:+.0f} -> {SAG:+.0f} c/s")
    # level: the reference flutters around 12 Hz, 3.1 dB; the same rule
    in_rate = 8 <= m["lrate"] <= 16
    flut = None if in_rate and m["level"] >= 2 else (math.sqrt(max(FLUT_DB ** 2 - m["level"] ** 2, 1.5 ** 2)) if in_rate else FLUT_DB)
    if flut:
        g = gen_lead.wander(n, FLUT_HZ * 0.85, FLUT_HZ * 1.2, seed + 1) * flut * np.minimum(1, tt / 0.3)
        y = y * 10 ** (g / 20)
        notes.append(f"flutter {flut:.1f} dB around {FLUT_HZ} Hz")
    # the floor: noise shaped like the sound's own spectrum under the band for the floor figure (-8.6 dB), and a quiet hiss
    # up to 9.5 kHz for the reference's share above 5 kHz as played (-53.1 dB), both following the envelope; two passes,
    # since each moves the other's figure. (Tried and dropped: a pink floor, -28 dB flat as played in 100 Hz-5 kHz against
    # the reference's -37; a hiss set for the reference's whole-band flatness of the stored sample, 10-13 dB too much
    # above 5 kHz as played.)
    hop = RATE // 100
    env = np.sqrt(np.convolve(y * y, np.ones(hop) / hop, mode="same"))
    f, S = envelope_spectrum(y, RATE)
    floor_n = fir_filter(shaped_noise(n, RATE, f, S, seed=n + seed), lowpass_fir(BANDWIDTH / RATE)) * env
    hiss = fir_filter(np.random.default_rng(seed + 3).standard_normal(n), lowpass_fir(HISS_BW / RATE)) * env
    floor_n /= np.sqrt(np.mean(floor_n ** 2)) / np.sqrt(np.mean(y ** 2))
    hiss /= np.sqrt(np.mean(hiss ** 2)) / np.sqrt(np.mean(y ** 2))
    own_floor, own_flat = floor_ref(y), flatness_ref(y)
    gf = gh = -120.0
    for _ in range(2):
        mix = lambda a_, b_: y + floor_n * 10 ** (a_ / 20) + hiss * 10 ** (b_ / 20)
        if floor_ref(mix(-120.0, gh)) < FLOOR_DB:
            gf = bisect(lambda d: floor_ref(mix(d, gh)), FLOOR_DB, -80.0, 10.0)
        if hf_share(mix(gf, -120.0)) < HF_DB:
            gh = bisect(lambda d: hf_share(mix(gf, d)), HF_DB, -120.0, 0.0)
    y = y + floor_n * 10 ** (gf / 20) + hiss * 10 ** (gh / 20)
    fl, ft = floor_ref(y), flatness_ref(y)
    # the offset starts the note on frame SKIP: shift the sound (by at most about 1 ms) so a zero crossing lands there
    z = np.nonzero(np.signbit(y[SKIP - 60: SKIP + 60][:-1]) != np.signbit(y[SKIP - 60: SKIP + 60][1:]))[0]
    if len(z):
        k = int(z[np.argmin(np.abs(z - 60))]) - 60 + 1                       # the first frame after the crossing
        y = np.concatenate([y[k:], np.zeros(k)]) if k > 0 else np.concatenate([np.zeros(-k), y[:n + k]])
        if abs(y[SKIP - 1]) < abs(y[SKIP]):                                   # whichever side of the crossing is nearer 0
            y = np.concatenate([[0.0], y[:-1]])
    fi = round(0.002 * RATE)                                                 # the fades last, so the file starts at 0
    y[:fi] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(fi) / fi)
    fade = round(FADE * RATE)
    y[-fade:] *= np.linspace(1, 0, fade)
    y *= 10 ** ((RMS_DB + gain_db) / 20) / np.sqrt(np.mean(y[:RATE] ** 2))
    lim = 10 ** (-1 / 20)
    peak = np.abs(y[SKIP:]).max()                                            # the part the song plays
    if peak > lim:
        y *= lim / peak
        peak = lim
    env = np.array([np.abs(y[max(0, i - 44): i + 44]).max() for i in range(SKIP)])
    if env.max() > peak:                                                     # the start the offset skips: held under the
        g = np.minimum(1, peak / env)                                        # played part's peak, rising to 1 by the offset
        y[:SKIP] *= np.minimum.accumulate(g[::-1])[::-1]
    pcm = np.clip(np.round(y * 32767), -32768, 32767).astype(int).tolist()
    write_wav(OUT / f"{cand}.wav", RATE, [pcm], 16, root_note=ROOT_NOTE)
    print(f"{cand:11s} <- {raw:28s} was {1200 * np.log2(f0 / F_G5):+.0f} c; own pitch {m['pitch']:.0f} c at {m['prate']:.1f} Hz, "
          f"level {m['level']:.1f} dB at {m['lrate']:.1f} Hz; added: {'; '.join(notes) or 'nothing'}; "
          f"floor {own_floor:.1f} -> {fl:.1f} dB, flatness {own_flat:.1f} -> {ft:.1f} dB, above 5 kHz as played {hf_share(y):.1f} dB")


# ------------------------------------------------------------------------------------------------ the pattern

NOTE, OFFSET, VOL = "A-5", "O0F", 64
PATTERNS = ["loop", "loop_b"]
CHANNELS = """    - {name: Hit A, pan: 32, volume: 64}
    - {name: Hit B, pan: 32, volume: 64}
"""


def figure():
    cols = {p: [dict(), dict()] for p in PATTERNS}
    for p in PATTERNS:
        for b in range(4):
            cols[p][b % 2][16 * b] = f"{NOTE} 10 v{VOL:02d} {OFFSET}"
    return cols


THIN = [0, 16]                                            # the form's A and the peak's first two patterns (the reference's
                                                          # orders 10-17, 24-25): two hits, bars 1 and 2, without the offset


def thin():
    """Channels 14-15 in a thinned pattern of the form."""
    cols = [dict(), dict()]
    for b, r in enumerate(THIN):
        cols[b % 2][r] = f"{NOTE} 10 v{VOL:02d}"
    return cols


def pattern(path=HERE / "rift.yaml", first_sample="hit_placeholder.wav"):
    b = path.read_bytes()
    crlf = b"\r\n" in b
    t = b.decode("utf-8").replace("\r\n", "\n")
    t = ensure_channels(t, CHANNELS, r"    - \{name: Lead B[^\n]*\n")   # the owner's lines stay
    if "\n  10: {file:" not in t:
        line = f"  10: {{file: ../../samples/local/rift-cand/{first_sample}, base_note: G-5, name: {Path(first_sample).stem}}}\n"
        anchor = "\n\ninstruments:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + line + "\ninstruments:\n", 1)
    if "\n  10: {name: Hit" not in t:
        ins = "  10: {name: Hit, sample: 10}   # sample mode, as in the reference\n"
        anchor = "\n\npatterns:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + ins + "\npatterns:\n", 1)
    t = write_columns(t, 13, figure())
    if crlf:
        t = t.replace("\n", "\r\n")
    path.write_bytes(t.encode("utf-8"))
    print(f"wrote channels 14-15 into {path.name}: {NOTE} v{VOL} {OFFSET} on row 0 of every bar, alternating")


if __name__ == "__main__":
    if sys.argv[1:2] == ["pattern"]:
        pattern(first_sample=next(iter(CANDS), "hit_placeholder") + ".wav")
    else:
        for cand, raw in CANDS.items():
            if not sys.argv[1:] or cand in sys.argv[1:]:
                make(cand, raw, GAIN.get(cand, 0.0))
