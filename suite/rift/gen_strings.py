"""Rift, layer 5 of BRIEF.md's layer plan: the strings, written the way Nether Animal writes its strings (measured with
scratch/ut99-clean/melodic.py, the articulation read from its cells without its notes; only the idioms and the sample
character are taken).

`python suite/rift/gen_strings.py` makes the slot-11 candidates from the screened raw notes (samples/local/rift-cand/
strings/, each sounding A-4) the way Nether's string sample measures (melodic.character on its WAV with its loop, at its
15986 Hz storage rate; this script measures ours with the same function at the same rate):
  - 4.06 s with a forward loop of 1.85 s from 2.21 s (here 407 whole cycles of A-4, the loop's last 0.2 s blended into
    what precedes its start, the gains set by how alike the two are so the level holds through the blend); a swell
    through -24 dB at 0.1 s and -10 dB at 537 ms, reaching the loop's level at its start (the reference's -3 dB point,
    2308 ms, is 0.1 s into its loop: ours is where the loop's level wander crests), the sound's own onset and grain
    kept; band-limited at 5.3 kHz (the reference's steady part ends there at -40 dB, 25 harmonics of its note);
  - movement over the loop as melodic.py measures it: a vibrato of 7.7 cents peak to peak around 2.9 Hz and a level
    wander of 2.0 dB around 1.7 Hz, both irregular (prominence 4.6 and 3.2), added only up to those figures where the
    sound moves less (a sound already moving as much, at its own rate, keeps its own and gets none), periodic with the
    loop so the wrap stays seamless; the level wander spreads to 15 Hz only as far as the floor allows;
  - a floor of -23.9 dB between the partials: noise shaped like the sound's own spectrum, periodic with the loop, added
    where the sound is purer (a noisier sound keeps its own);
  - the loop's level held flat (the reference falls 1.2 dB a second inside its loop, a 2.2 dB step at every wrap: not
    followed); a gain per candidate for the level 8.6 dB under the sub; the -1 dBFS peak limit.
  - tuned by melodic.py's median pitch of the loop, or by the loop's harmonic lines where partials 1-3 all sit on one
    line (the partials' count is then the pitch: the comb read 408 cycles against YIN's 407).
  Stored at 44.1 kHz (the compiler's resampling used to click at loop points), root A-4. Partials, noise colour, onset
  brightness and the sound's own movements stay its own: matching those would rebuild the reference's sample. Kept
  and measured (two independent checks): viola 13 c at 3.7 Hz, fmstg 13 c at 4.1 Hz and pwm 10.5 c at 4.5 Hz vibrato
  (their own; nothing is added where a sound already moves 7.7 c), cello's own 5.5 Hz shimmer reads as its rate, the
  cello and fmstg floors (-21.6 and -17 dB), level-wander prominence where the floor forbids spreading it, the -3 dB
  fmstg's FM partials stretched (-8.5/-4.3/+1.3 c).
`python suite/rift/gen_strings.py pattern` writes the strings into rift.yaml (channels 16-21, slot 11, instrument 11):
  - Nether's idiom: two three-voice groups a pattern, one struck on row 0 (channels 16-18) and one on row 32 (19-21),
    each held 32 rows and faded from the other group's strike (D02, then D00 for 18 rows), S87 on every note (pan 29:
    the reference's six voices share one pan), the sample's own volume (no volume column).
  - Our chord: F major seventh over the A root (the reference's colour, a major seventh on the minor sixth), voiced
    F-4 C-5 A-5 on row 0 and E-4 E-5 A-5 on row 32 (5 semitones under to 12 over the stored A-4: a 5.3 kHz band reaches
    10.6 kHz, under the drums' top); as in the reference no group holds the major seventh itself, it sounds where the
    groups overlap. scratch/ut99-clean/rifttools/chordcheck.py compares the voicing with Nether's in sounding pitch and
    prints counts only: no group's interval stack is one of theirs, at most 3 of the 6 voices sit where theirs do. The
    price, kept: ours is spread wider than theirs (groups over 16-17 semitones against 7-9).
Channels 1-15 are not touched.
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
sys.path.insert(0, str(ROOT / "scratch" / "ut99-clean"))
from vulturetracker.resample import fir_filter, lowpass_fir, resample  # noqa: E402
from vulturetracker.wavload import read_wav, write_wav  # noqa: E402
from gen_floor import envelope_spectrum, shaped_noise  # noqa: E402
from gen_seq import f0_near, ensure_channels, write_columns  # noqa: E402
import melodic  # noqa: E402  (local only: character() printed the reference's numbers; ours are read with it)

OUT = ROOT / "samples" / "local" / "rift-cand"
RAW = OUT / "strings"
RATE, REF_RATE = 44100, 15986                             # ours; the reference's storage rate (its measures' scale)
ROOT_NOTE = 57                                            # A-4 (the tracker's C-5 is 60)
F_ROOT = 440 * 2 ** ((ROOT_NOTE - 69) / 12)               # 220 Hz: 11 cycles are 2205 frames exactly
START = round(2.21 * RATE / 2205) * 2205                  # the loop from 2.20 s, on a whole number of cycles
LOOP = 37 * 2205                                          # 407 cycles, 1.850 s (the reference's 1.847 s)
XFADE = round(0.2 * RATE)
BANDWIDTH = 5300.0
ATTACK10, ATTACK3 = 537.0, 2308.0                         # ms to -10 and -3 dB of the peak
VIB_HZ, VIB_C = 2.9, 7.7                                  # cents peak to peak (melodic.py: 2.8 x the spread)
TREM_HZ, TREM_DB = 1.7, 2.0                               # dB spread of the detrended 10 ms envelope
VIB_SPREAD, TREM_SPREAD = 0.35, 0.35                      # the movement's level across its band against its peak
FLOOR_DB = -23.9
RMS_DB = -16.0                                            # the loop's level before the per-candidate gain

# candidate -> raw (relative to RAW): five of seventeen finalists of three screens (1032 recordings and patches measured
# against the class: one bowed note sounding A-4, harmonic, a slow swell or one the envelope can make, a steady part of
# 2.5 s or more, a moderate floor), one per character. Recipes: strings/rec/recipe.yaml (VSCO 2 CE files pre-pitched to
# A-4; Nadir's beds use the v1 takes, this one is v2), strings/surge/recipe.yaml (edited .fxp copies: FX off, the amp EG a
# slow swell), strings/dx_obxd/recipe.yaml (Dexed and OB-Xd with inline edits).
CANDS = {
    "str_viola": "rec/str_viola_vib.wav",        # VSCO 2 viola section D3 (CC0), recorded: 11.5 c vibrato at 3.6 Hz, floor -23 dB
    "str_cello": "surge/str_cello.wav",          # Surge Dan Maurer "Overdriven Cello": noise through a resonator, a dark solo bow
    "str_fmstg": "dx_obxd/str_fmstg.wav",        # Dexed SynprezFM_19 "STG 3": FM strings, a feedback noise floor (-19.5 dB)
    "str_pwm": "dx_obxd/str_obpwm.wav",          # OB-Xd "Strings IV OB-Xa", the PWM oscillator alone: an analog section shimmer
    "str_comb": "surge/str_comb.wav",            # Surge Dan Maurer "Comb String Section": noise through a comb, breathy, no vibrato
}
# per candidate, dB so the strings sit 8.6 dB under the sub in the song (measured)
GAIN = {"str_viola": -5.4, "str_cello": -5.8, "str_fmstg": -6.0, "str_pwm": -6.8, "str_comb": -5.6}


def measure(y, loop=True):
    """melodic.character of `y` (44.1 kHz, our loop) at the reference's storage rate."""
    z = resample(y, RATE, REF_RATE)
    s = round(START * REF_RATE / RATE)
    return melodic.character(z, REF_RATE, ("fwd", s, s + round(LOOP * REF_RATE / RATE)) if loop else None)


def loop_floor(y):
    """melodic.py's floor of the loop, at the reference's storage rate."""
    s = round(START * REF_RATE / RATE)
    return melodic.floor_db(resample(y[:START + LOOP], RATE, REF_RATE)[s: s + round(LOOP * REF_RATE / RATE)], REF_RATE)


def pwander(n, lo, hi, centre, seed, crest=None, spread=0.0):
    """An irregular movement periodic with the loop, aligned to its start: noise at a 100 Hz control rate spread over
    lo-hi Hz (the band melodic.py reads it in) with a peak around `centre` (the rate it reads), unit spread, `n` frames
    long; `crest` (frames into the loop) puts its highest point there. The reference's movement is spread like that:
    its strongest component stands only 3-5 times over the band's median (a sine's stands 10-1000 times)."""
    m = round(LOOP / RATE * 100)
    fr = np.fft.rfftfreq(m, LOOP / RATE / m)
    shape = ((fr >= lo) & (fr <= hi)) * (spread + np.exp(-0.5 * ((fr - centre) / (0.3 * centre)) ** 2))
    near = np.argmin(np.abs(fr - centre))                     # the loop's line nearest the centre: the strongest one
    for s in range(seed * 64, seed * 64 + 64):                 # each seed its own range
        spec = np.fft.rfft(np.random.default_rng(s).standard_normal(m)) * shape
        a = np.sort(np.abs(spec))
        if np.argmax(np.abs(spec)) == near and a[-1] > 1.5 * a[-2]:
            break
    w = np.fft.irfft(spec, m)
    w /= np.std(w) + 1e-12
    if crest is not None:
        w = np.roll(w, round(crest / LOOP * m) - int(np.argmax(w)))
    t = (np.arange(n) - START) % LOOP
    return np.interp(t, np.arange(m + 1) * LOOP / m, np.append(w, w[0]))


def added(own, own_hz, target, lo, hi):
    """How much movement to add around the reference's rate: none if the sound already moves as much (in the band or at
    its own rate, which stays), else a top-up to the target in the band or all of it out of it."""
    if own >= target:
        return 0.0
    return math.sqrt(target ** 2 - own ** 2) if lo <= own_hz <= hi else target


def env_db(y, win=0.01):
    h = int(RATE * win)
    e = np.sqrt(np.convolve(y * y, np.ones(h) / h, mode="same"))
    return 20 * np.log10(e + 1e-9)


def make(cand, raw, gain_db=0.0):
    w = read_wav(RAW / raw)
    x = np.asarray(w.channels, float).mean(axis=0) / 2 ** (w.bits - 1)
    on = int(np.nonzero(np.abs(x) > np.abs(x).max() * 10 ** (-50 / 20))[0][0])
    f0 = f0_near(x[on + int(1.5 * w.rate): on + int(4.0 * w.rate)], w.rate, F_ROOT)
    x = resample(x[on:], w.rate * F_ROOT / f0, RATE)                         # relabelled so it sounds A-4, then stored
    end = START + LOOP
    fl = measure(x[:end])["f0_hz"]                          # tuned again on what will be the loop (melodic.py's median)
    x = resample(x, RATE * F_ROOT / fl, RATE)
    f0 *= fl / F_ROOT
    X = np.abs(np.fft.rfft(x[START:end])) ** 2                              # line c = c cycles in the loop
    cyc = max(range(403, 412), key=lambda c: sum(X[c * h] for h in range(1, 6)))
    clear = all(X[cyc * h] > 0.5 * X[(cyc - 3) * h: (cyc + 3) * h + 1].sum() for h in (1, 2, 3))   # partials 1-3 agree
    if cyc != 407 and clear:                                                 # then the partials' count wins over YIN's
        x = resample(x, RATE * 407 / cyc, RATE)
        f0 *= cyc / 407
    x = fir_filter(x, lowpass_fir(BANDWIDTH / RATE))
    assert len(x) >= end + RATE // 2, f"{raw}: too short"
    seed = sum(map(ord, cand))
    own = measure(x[:end])
    notes = []
    # movement, periodic with the loop
    vib = added(own.get("vibrato_depth_cents", 0.0), own.get("vibrato_hz", 0.0), VIB_C, 2.0, 4.0)
    if vib:
        dry, shape = x, pwander(len(x), 2.0, 12.0, VIB_HZ, seed, spread=VIB_SPREAD) / (2 * math.sqrt(2))

        def bend(c):
            ratio = 2 ** (shape * c / 1200)
            pos = np.cumsum(ratio) - ratio[0]
            pos += START - pos[START]                                         # the loop starts where it did
            return np.interp(pos, np.arange(len(dry)), dry, right=0.0)
        x = bend(vib)
        got = measure(x[:end]).get("vibrato_depth_cents", VIB_C)            # its 140 ms frames smooth the faster part:
        if got < VIB_C - 0.5:                                                 # one step towards what melodic.py reads
            vib *= VIB_C / got
            x = bend(vib)
        notes.append(f"vibrato {vib:.1f} c around {VIB_HZ} Hz")
    trem = added(own.get("level_dev_db", 0.0), own.get("tremolo_hz", 0.0), TREM_DB, 1.0, 2.7)
    if trem:
        crest = ATTACK3 / 1000 * RATE - START                                # the reference's -3 dB point, 0.1 s into its loop
        # the wander spreads up to 15 Hz only as far as the floor allows (its sidebands between the partials read as
        # floor; the noise added below makes up the rest); a sound already as noisy keeps it under 6 Hz
        dry = x
        wet = lambda sp, top: dry * 10 ** (pwander(len(dry), 1.0, top, TREM_HZ, seed + 1, crest, sp) * trem / 20)
        spread, top = 0.0, 6.0
        if own["floor_db"] < FLOOR_DB - 1:
            top, lo, hi = 15.0, 0.0, TREM_SPREAD
            for _ in range(12):
                spread = (lo + hi) / 2
                lo, hi = (spread, hi) if loop_floor(wet(spread, top)) < FLOOR_DB else (lo, spread)
            spread = lo
        x = wet(spread, top)
        notes.append(f"level wander {trem:.1f} dB around {TREM_HZ} Hz (spread {spread:.2f} to {top:.0f} Hz)")
    # the loop's level held flat: its slope in dB taken out over the loop (1 at the loop start, so nothing jumps there)
    e = env_db(x[START:end])[::441]
    tt = np.arange(len(e)) * 441
    slope = np.polyfit(tt, e, 1)[0]
    x[START:end] *= 10 ** (-slope * np.arange(LOOP) / 20)
    x[end:] *= 10 ** (-slope * LOOP / 20)
    notes.append(f"loop slope {slope * RATE:+.1f} dB/s flattened")
    # the floor: noise shaped like the loop's spectrum, periodic with the loop, following the level before it
    loop = x[START:end]
    f, S = envelope_spectrum(np.tile(loop, 3), RATE)
    burst = fir_filter(np.tile(shaped_noise(LOOP, RATE, f, S, seed=LOOP + seed), 3), lowpass_fir(BANDWIDTH / RATE))[LOOP:2 * LOOP]
    noise = burst[(np.arange(len(x)) - START) % LOOP] * np.sqrt(np.mean(loop ** 2)) / np.sqrt(np.mean(burst ** 2))
    lvl = 10 ** (env_db(x) / 20) / np.sqrt(np.mean(loop ** 2))
    noise[:START] *= np.minimum(lvl[:START], 1.5)
    own_floor = measure(x[:end])["floor_db"]
    g_db = None
    if own_floor < FLOOR_DB - 0.5:
        s, e_ = round(START * REF_RATE / RATE), round(end * REF_RATE / RATE)
        X, N = resample(x[:end], RATE, REF_RATE), resample(noise[:end], RATE, REF_RATE)   # linear: resampled once
        lo, hi = -80.0, 10.0
        for _ in range(30):
            g_db = (lo + hi) / 2
            fl = melodic.floor_db((X + N * 10 ** (g_db / 20))[s:e_], REF_RATE)
            lo, hi = (g_db, hi) if fl < FLOOR_DB else (lo, g_db)
        x = x + noise * 10 ** (g_db / 20)
        notes.append(f"noise at {g_db:+.1f} dB")
    # the wrap: the loop's last 0.2 s blend into what precedes its start (the same phase of the movement and, pitched to
    # whole cycles, of the tone)
    a, b = x[end - XFADE:end].copy(), x[START - XFADE:START]
    rho = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    r = np.linspace(0, 1, XFADE)
    x[end - XFADE:end] = (a * (1 - r) + b * r) / np.sqrt((1 - r) ** 2 + r ** 2 + 2 * max(rho, -0.5) * r * (1 - r))
    notes.append(f"blend correlation {rho:+.2f}")
    y = x[:end].copy()
    # the swell: the level before the loop bent through -24 dB (of the peak) at 0.1 s and -10 dB at ATTACK10, then straight
    # in dB to the loop's own level at its start; the knot moved until melodic.py reads ATTACK10. The -3 dB point is the loop's: the reference
    # reaches it 0.1 s into its loop, where the added level wander has its crest
    k10 = ATTACK10 / 1000
    base = y.copy()
    E = np.convolve(env_db(base), np.ones(2205) / 2205, mode="same")          # the sound's own curve, 50 ms smoothing
    top = env_db(base[START:end]).max()
    lm = E[START + 2205]
    z = resample(base, RATE, REF_RATE)                                       # the peak as melodic.py reads it (10 ms
    cap = melodic.envelope_db(z, REF_RATE)[0].max() - 3.2                    # blocks at 15986 Hz): -3 dB not before the loop
    held = np.arange(START) < START - round(0.05 * RATE)

    def swell(k, cap=cap):
        T = np.interp(np.arange(START) / RATE, [0.0, min(0.1, k / 2), k, START / RATE - 0.05, START / RATE],
                      [top - 45, top - 24, top - 10, min(lm, top - 3.2), lm])      # -3 dB not before the loop
        G = np.clip(T - E[:START], -60, 36)
        G = np.convolve(np.concatenate([np.full(1102, G[0]), G, np.full(1102, G[-1])]), np.ones(2205) / 2205, mode="valid")[:START]
        G -= G[-1] * np.clip((np.arange(START) / RATE - k) / (START / RATE - k), 0, 1)   # 0 dB at the loop start,
        # the offset taken out after the knot only, so the knots hold
        G[held] = np.minimum(G[held], (cap - E[:START])[held])               # and under the cap until the last 50 ms
        z = base.copy()
        z[:START] *= 10 ** (G / 20)
        return z

    # the -10 dB crossing moves in jumps on a flickering sound (the rise after it is slow, as the reference's): the best
    # of a few damped steps is kept
    best = None
    for _ in range(10):
        d10 = measure(swell(k10))["attack10_ms"] - ATTACK10
        if best is None or abs(d10) < abs(best[1]):
            best = (k10, d10)
        if abs(d10) < 15:
            break
        k10 = min(max(k10 - 0.7 * d10 / 1000, 0.05), 1.5)
    k10 = best[0]
    for _ in range(6):                        # a flickering sound's 10 ms blocks cross above the smoothed curve: the cap
        y = swell(k10, cap)                   # comes down until melodic.py's -3 dB point is no earlier than the last 50 ms
        if measure(y)["attack3_ms"] >= (START / RATE - 0.05) * 1000:
            break
        cap -= 0.5
    notes.append(f"swell knot {k10:.2f} s")
    fi = round(0.002 * RATE)
    y[:fi] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(fi) / fi)
    y *= 10 ** ((RMS_DB + gain_db) / 20) / np.sqrt(np.mean(y[START:end] ** 2))
    peak = np.abs(y).max()
    if peak > 10 ** (-1 / 20):
        y *= 10 ** (-1 / 20) / peak
    pcm = np.clip(np.round(y * 32767), -32768, 32767).astype(int).tolist()
    write_wav(OUT / f"{cand}.wav", RATE, [pcm], 16, loop=(START, end, False), root_note=ROOT_NOTE)
    m = measure(np.array(pcm, float) / 32767)                 # what the file holds (16 bits)
    f1 = m["f0_hz"]
    print(f"{cand:14s} <- {raw:34s} was {1200 * np.log2(f0 / F_ROOT):+.0f} c, now {1200 * np.log2(f1 / F_ROOT):+.1f} c; "
          f"added: {'; '.join(notes)}\n    own: floor {own['floor_db']:.1f} dB, vibrato {own.get('vibrato_depth_cents', 0):.1f} c "
          f"at {own.get('vibrato_hz', 0):.1f} Hz, level {own.get('level_dev_db', 0):.1f} dB at {own.get('tremolo_hz', 0):.1f} Hz, "
          f"attack {own['attack10_ms']:.0f}/{own['attack3_ms']:.0f} ms\n    now: {fmt(m)}, "
          f"flatness 50 Hz-5 kHz {flat5k(np.array(pcm, float) / 32767):.1f} dB")


def flat5k(y):
    """Flatness of the loop over 50 Hz-5 kHz at the reference's rate: melodic.py's band reaches 7.2 kHz, where our band
    limit leaves only the 16-bit floor."""
    s = round(START * REF_RATE / RATE)
    z = resample(y, RATE, REF_RATE)[s: s + round(LOOP * REF_RATE / RATE)]
    n = 8192
    P = np.mean([np.abs(np.fft.rfft(z[i: i + n] * np.hanning(n))) ** 2 for i in range(0, len(z) - n + 1, n // 4)], axis=0)
    fq = np.fft.rfftfreq(n, 1 / REF_RATE)
    band = (fq >= 50) & (fq <= 5000)
    return float(10 * np.log10(np.exp(np.mean(np.log(P[band] + 1e-20))) / (np.mean(P[band]) + 1e-20)))


def fmt(m):
    return (f"attack {m['attack10_ms']:.0f}/{m['attack3_ms']:.0f} ms, steady {m['steady_s']:.2f} s, vibrato "
            f"{m.get('vibrato_depth_cents', 0):.1f} c at {m.get('vibrato_hz', 0):.1f} Hz (prom {m.get('vibrato_prominence', 0):.1f}), "
            f"drift {m.get('drift_cents_per_s', 0):+.1f} c/s, level {m.get('level_dev_db', 0):.1f} dB at {m.get('tremolo_hz', 0):.1f} Hz "
            f"(prom {m.get('tremolo_prominence', 0):.1f}), slope {m.get('level_slope_db_per_s', 0):+.1f} dB/s, bw40 {m['bw40_hz']:.0f} Hz, "
            f"centroid {m['centroid_hz']:.0f} Hz (moving {m['centroid_move_hz']:.0f}), floor {m['floor_db']:.1f} dB, flatness "
            f"{m['flatness_db']:.1f} dB, partials {m.get('partials_db', [])[:6]}, odd/even {m.get('odd_even_db', 0):+.1f} dB, "
            f"inharmonic {m.get('inharmonic_cents') or 0:.1f} c, off-harmonic peaks {m.get('off_harmonic_peaks')}, peak {m['peak_dbfs']:.1f} dBFS")


# ------------------------------------------------------------------------------------------------ the pattern

GROUPS = [["F-4", "C-5", "A-5"], ["E-4", "E-5", "A-5"]]   # struck on rows 0 and 32
STRIKE = [0, 32]
FADE_ROWS = 19                                             # D02, then D00 for 18 rows (the reference's)
PAN = "S87"
PATTERNS = ["loop", "loop_b"]
CHANNELS = "".join(f"    - {{name: Str {i}, pan: 32, volume: 64}}\n" for i in range(1, 7))


def figure():
    cols = {p: [dict() for _ in range(6)] for p in PATTERNS}
    for p in PATTERNS:
        for g, (row, group) in enumerate(zip(STRIKE, GROUPS)):
            fade = STRIKE[1 - g]                                   # faded from the other group's strike
            for v, note in enumerate(group):
                col = cols[p][3 * g + v]
                col[row] = f"{note} 11 ... {PAN}"
                for k in range(FADE_ROWS):
                    col[fade + k] = "... .. ... " + ("D02" if k == 0 else "D00")
    return cols


def closing():
    """Channels 16-21 in the pattern after the form's last strings pattern (the reference's order 30): the row-32 group
    faded from row 0 as figure() fades it, nothing struck."""
    cols = [dict() for _ in range(6)]
    for v in range(3):
        for k in range(FADE_ROWS):
            cols[3 + v][STRIKE[0] + k] = "... .. ... " + ("D02" if k == 0 else "D00")
    for col in cols:                                           # silent by then: a cut, so the app's SOUNDING table drops them
        col[STRIKE[0] + FADE_ROWS] = "^^^"
    return cols


def pattern(path=HERE / "rift.yaml", first_sample="strings_placeholder.wav"):
    b = path.read_bytes()
    crlf = b"\r\n" in b
    t = b.decode("utf-8").replace("\r\n", "\n")
    t = ensure_channels(t, CHANNELS, r"    - \{name: Hit B[^\n]*\n")   # the owner's lines stay
    if "\n  11: {file:" not in t:
        line = (f"  11: {{file: ../../samples/local/rift-cand/{first_sample}, base_note: A-4, loop: from_wav, "
                f"name: {Path(first_sample).stem}}}\n")
        anchor = "\n\ninstruments:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + line + "\ninstruments:\n", 1)
    if "\n  11: {name: Strings" not in t:
        ins = "  11: {name: Strings, sample: 11}   # sample mode, as in the reference: the fades are in the pattern\n"
        anchor = "\n\npatterns:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + ins + "\npatterns:\n", 1)
    t = write_columns(t, 15, figure())
    if crlf:
        t = t.replace("\n", "\r\n")
    path.write_bytes(t.encode("utf-8"))
    print(f"wrote channels 16-21 into {path.name}: {GROUPS[0]} on row 0, {GROUPS[1]} on row 32, {PAN}, "
          f"faded from the other group's strike (D02 + {FADE_ROWS - 1} x D00)")


if __name__ == "__main__":
    if sys.argv[1:2] == ["pattern"]:
        pattern(first_sample=next(iter(CANDS), "strings_placeholder") + ".wav")
    elif sys.argv[1:2] == ["ref"]:                                    # the calibration: the reference's own numbers
        w = read_wav(ROOT / "scratch/ut99/nether/nether_samples/17_Golden_Beautiful_Violin.wav")
        x = np.asarray(w.channels, float).mean(axis=0) / 2 ** (w.bits - 1)
        print("reference:", fmt(melodic.character(x, w.rate, ("fwd", 35302, 64833))))
    else:
        for cand, raw in CANDS.items():
            if not sys.argv[1:] or cand in sys.argv[1:]:
                make(cand, raw, GAIN.get(cand, 0.0))
