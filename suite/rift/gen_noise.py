"""Rift, layer 7 of BRIEF.md's layer plan: the noise, written the way Nether Animal writes its noise swell (sample 1,
EAT1; measured with scratch/ut99-clean/melodic.py, the articulation read from its cells without its notes with
scratch/ut99-clean/rifttools/artic.py 1; only the idioms and the sample character are taken).

`python suite/rift/gen_noise.py` makes the slot-13 candidates from the screened raw takes (samples/local/rift-cand/noise/
{surge,dx_obxd,rec}/, each a mono one-shot at 44.1 kHz, onset at 0) the way the reference's sample measures
(melodic.character on its WAV at its 16217 Hz storage rate; `gen_noise.py ref` prints those figures; ours are read with
the same function at the same rate, our 44.1 kHz files brought to it by an FFT resample that keeps everything up to its
Nyquist: vulturetracker's resampler cuts at 0.45 of the new rate and read the reference's own -60 dB bandwidth as 7170 Hz):
  - the reference plays its sample 2 semitones under its stored rate (5.77 s as played against 5.14 s stored; its
    strongest resonance sounds on the key root as played), so ours is stored at B-3 and played at A-3, the same relation:
    every figure below is matched on the stored file and scales the same way into as played for ours (our render equals
    a clean play of the file), the length in seconds (5.77 s as played: 15.9 beats at our tempo, the reference's 16.9 at
    its own). The reference's as-played readings also carry its bright first 0.4 s (-24 dB above 5.6 kHz in its first
    0.1 s, falling to -43 by 0.4 s; ours read -39 to -57 there, faraway's -57 in its first 0.1 s its take's own dark
    15-45 ms up high (22-26 dB under its level from 60 ms), wind's falling centroid from 0.8 kHz its own sweep without
    that burst): its noise curve over time, reported. The raw take's strongest resonance (a peak 10 dB or more over the
    noise around it, within 15 dB of the strongest, as samples/local/rift-cand/noise/measure.py finds them) is tuned
    onto a B as stored, so it sounds on an A; the others stay the take's own (timproll's mode 48 c under the tuned one
    sits within 1 dB of it: which reads strongest changes with the movement's draw); a take with no resonance is
    unpitched and not moved;
  - the sub's side is under 104 Hz as played, 116.7 Hz as stored: nothing generated there, and the movement and the lift
    act above 125.7 Hz stored; what their gains still spill there (their first milliseconds' edge, and the take's own
    content in the splits' transition) is printed per take: -54 to -76 dB of the whole in the current build, and from
    0.1 s on 54-63 dB under the take's own there (deepnote 23: its own content there is tiny, -63 dB of the whole
    from 0.1 s on; 91 % of its -51 dB share lies in its first 0.1 s);
  - nothing under 20 Hz (a 20-45 Hz ramp) and nothing over 8.1 kHz (the reference's Nyquist: its storage holds nothing
    above it);
  - a floor of -3.5 dB between its peaks where the take is purer (none of the five is): noise shaped like the take's own
    spectrum (smoothed over a third of an octave), following its level (30 ms), then cut under 125.7 Hz stored; if even
    noise as loud as the take does not reach it, nothing is added and the miss is printed;
  - band by band slow movement where a band moves less than the reference's: over the held part (to the 200 ms level's
    first fall 10 dB under its peak, at most 4.5 s), 50 ms band levels (125.7-300, 300-700, 700-2200 Hz stored) less their
    1.5 s moving average, averaged over ten block phases, move REF_BANDS dB in the reference, nearly uncorrelated. Where a
    band's own movement (read from 40 ms in, past what the onset may cut) is less, an irregular draw (0.6-6 Hz around
    1.1 Hz; the three draws made uncorrelated, then clipped at 2.5 spreads) is added to that band alone (complementary
    linear-phase splits at 125.7, 300 and 700 Hz stored; the top band is moved as 700 Hz and up, read on 700-2200 Hz),
    its depth solved until the band reads the reference's spread; all depths then scaled down together while the whole
    sound's level movement (melodic, steady part, read on the finished file after the onset and the roll-off, solved again
    if it passes) would pass the larger of the reference's 1.76 dB and the take's own on the same frame, plus 0.1 dB; after
    the held part (over 0.3 s, from the moved take's own held end, read before the roll-off, which can move it:
    faraway's moves it 91 ms earlier; a band given no second depth can still read up to about 0.06 dB over its own there:
    deepnote's top band from the held depth's 0.3 s taper, faraway's two lower bands mostly from the band masks, taken on
    the whole file, carrying its moved held part into that span, 0.00 on the span alone past the taper) each
    moved band gets a second depth, solved so the band reads the reference's spread there (REF_AFTER), none where the take
    already moves that much (where under 1 s follows the held part, as timproll's, which runs to 4.5 s, the held depth goes
    on); of 12 draw sets the one whose onset result (before the roll-off and the fades) meets the reference's onset maxima,
    then keeps its loudest 10 ms block in its first 0.5 s (the reference's is at 0.14 s; a later one also cuts melodic's
    tail short), then has no re-swell after the held part beyond the larger of the reference's (REF_RISE) and the take's
    own plus 0.3 dB, then whose band correlations come nearest the reference's. A band already moving that much keeps its
    own movement (the printout lists the bands);
  - the onset, read on the moved file: the reference is at full level at once (on melodic's 10 ms blocks 0 ms to -10 dB
    and 10 ms to -3 dB of its peak; over all 162 block phases never later than 0 / 10 ms, means ATTACK_REF): the take
    starts at the point of its first 40 ms whose readings over all phases stay within those maxima with means nearest the
    reference's (a start spike or a slow first few ms is cut; a 1 ms fade-in there, applied last); where no start does, a
    rise that climbs steadily is lifted (within its first 60 ms, up to its first peak and never over it) when that meets
    them (the lift, like the movement, above 125.7 Hz stored only); otherwise the take keeps its own opening and the
    reason is printed;
  - last, on the file as it will be written, a smooth roll-off (flat to a corner, then a straight line in dB per octave,
    zero phase, attenuation only; corners 200-8000 Hz, slopes in 0.5 dB steps) whose corner and slope bring melodic's
    -40 and -60 dB bandwidths nearest the reference's 3.86 and 7.57 kHz (a brick wall at 3.86 kHz had left the band above it
    empty: flatness -45 to -48 dB against -21.3). Those bandwidths are read against each spectrum's strongest peak (the
    reference's is a resonance 17.9 dB over its body). In the current build the roll-off takes at most 2.8 dB at 2.2 kHz
    (faraway) and 5.1 dB at 3.86 kHz (wind) against the body; the rest of our darkness against the body at 2.2 kHz
    (faraway 5.8, wind 14, deepnote 18; saturn and timproll, with resonances and no roll-off, 10 and 9) is the takes' own
    noise curve, reported, not matched;
  - 5.14 s (a tuned take shorter than that is padded with silence first, so no filter wraps its start into its end), the
    last 0.2 s faded (the file's end; the take's own decay before it stays its own: the plan's "-30 dB decay" is the
    reference's curve, not matched);
  - a gain per candidate for the level 12.0 dB under the sub (the layer plan's figure, active level); the -1 dBFS peak limit.
  Stored at 44.1 kHz, root B-3. The take's own decay curve, noise curve (spectral shape) and resonances stay its own:
  matching those would rebuild the reference's sample (reported, never fixed). Its centroid movement (91 Hz) is half its
  bright opening darkening, half a slower swing of its bands (reported).
`python suite/rift/gen_noise.py pattern` writes the noise into rift.yaml (channel 23, slot 13 at base_note B-3, instrument 13):
  - Nether's idiom from its cells (counts only): one note on row 0 of each struck pattern, one written pitch for all 19
    notes, the sample's own volume (no volume column, no fades: the one-shot plays out), S89 (pan 38) on every note's row
    (alone on row 0 of the pattern after a strike in orders 7, 9, 34 and 38 only; nothing in the other unstruck patterns).
    It strikes every pattern in orders 0-6 (the intro and the build's first three), every second pattern in 8-18 and 24-30
    (none in B, 20-23), every fourth in C (33, 37): the 8-bar loop takes every second pattern (struck in `loop`, nothing in
    `loop_b`, as in 7 of the 8 unstruck patterns of those runs); every pattern and every fourth are form work.
  - Our note: A-3, 2 semitones under the stored B-3 (the reference's relation); where a take has a resonance, the tuned
    one sounds on an A (saturn, timproll; faraway, wind and deepnote are unpitched).
    scratch/ut99-clean/rifttools/noisecheck.py compares it with the reference's in sounding pitch and prints counts only.
Channels 1-22 keep their cells; an existing Noise channel line stays as it is (its volume is the owner's mix).
Since Step 3 (the form) rift.yaml has no `loop`/`loop_b`: gen_form.py writes it from this writer's pattern
functions (figure(), or the form's variants beside it where there are any), and `pattern` stops there with a
message; pattern(path) still writes the loop song, rift_loop.yaml.
"""
import math
import re
import sys
import zlib
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
from gen_seq import ensure_channels, write_columns  # noqa: E402
import melodic  # noqa: E402  (local only: character() printed the reference's numbers; ours are read with it)
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("noise_measure", ROOT / "samples/local/rift-cand/noise/measure.py")
nm = importlib.util.module_from_spec(_spec)  # the screens' class measures (by path: suite/nadir has a measure.py too)
_spec.loader.exec_module(nm)
from perchannel import floor_db  # noqa: E402  (melodic's floor)

OUT = ROOT / "samples" / "local" / "rift-cand"
RAW = OUT / "noise"
RATE, REF_RATE = 44100, 16217                              # ours; the reference's storage rate (its measures' scale)
BASE_NOTE, ROOT_NOTE, NOTE = "B-3", 47, "A-3"              # stored at B-3, played at A-3 (the tracker's C-5 is 60)
PLAYED = -2                                                # semitones from the stored rate as played (the reference's)
B_HZ = 440 * 2 ** ((ROOT_NOTE - 69) / 12)                  # 123.5 Hz: any B, 2 semitones over the A it sounds as
SECS, END_FADE, FADE_IN, MAX_TRIM, LIFT_T = 5.14, 0.2, 0.001, 0.04, 0.06
LEVEL_DEV = 1.76                                           # the reference's steady-part level movement (melodic)
BW40, BW60 = 3860.0, 7570.0                                # the reference's -40 / -60 dB bandwidths (melodic, storage rate)
TOP = REF_RATE / 2                                         # 8108 Hz: the reference's storage holds nothing above it
AS_STORED = 2 ** (-PLAYED / 12)                            # a frequency as played -> as stored
LOW_CUT = 104.0 * AS_STORED                                # 116.7 Hz stored: under 104 Hz as played, the sub's side
LOW_80 = 80.0 * AS_STORED                                  # 89.8 Hz stored (80 Hz as played), for the report
SPLIT = 112.0 * AS_STORED                                  # 125.7 Hz stored: the lowest split (16383 taps: flat to ~119 Hz)
FLOOR_DB = -3.5                                            # the reference's floor (melodic, storage rate)
BANDS = ((SPLIT, 300.0), (300.0, 700.0), (700.0, 2200.0))  # the band movement's bands (read); the top one moved as 700 and up
BAND_NAMES = (f"{SPLIT:.0f}-300 Hz", "300-700 Hz", "700 Hz and up")
PHASES = 10                                                # 50 ms block phases averaged (0-45 ms)
WANDER_HZ, WANDER_OCT, WANDER_BAND, CLIP = 1.1, 1.2, (0.6, 6.0), 2.5
TAPER = 0.3                                                # s: the movement's change of depth after the held part
ATTACK_REF = None                                          # set in main: the reference's attack means / maxima over phases
REF_BANDS = None                                           # set in main: the reference's band spreads and correlations
REF_AFTER = None                                           # set in main: its band spreads after the held part
REF_RISE = None                                            # set in main: its largest re-swell after the held part (dB)
HB = int(REF_RATE * 0.01)                                  # melodic's 10 ms block at the reference's rate: 162 samples

# candidate -> raw take (relative to RAW): five of eleven finalists of three screens (2331 Surge renders of 977 patches,
# 1310 Dexed/OB-Xd renders of 593 voices and programs, 1294 takes of 251 CC0 recordings; measured by noise/measure.py at
# the reference's rate, screened by scalar class figures, never spectral likeness; recipes and screen.txt in each folder),
# one per kind, the five farthest apart by the screens' figures (the nearest pair 0.86 against 0.56 for two of the same
# kind). Left out: Surge Space FM (FM sidebands on every pitch class, F# and C within 6 dB of its A), the Cybersoda sax
# model's S&H breath-noise oscillator (near layer 8's breathy pad), Sea Pipe (230 ms to -3 dB), Dexed OffTheWall (FM
# noise, 45 % of its power under 104 Hz), OB-Xd Claps and Wurlitzer noise (the filtered-noise kind faraway stands for).
CANDS = {
    "noise_faraway": "surge/noise_faraway.wav",     # Surge Inigo Kennedy "Faraway Tree", its noise generator soloed through the
                                                    # patch's own filter (an air band), no resonance
    "noise_wind": "dx_obxd/noise_wind.wav",         # OB-Xd "Wind at -50 C": noise through a key-tracked band-pass swept by a 0.16 Hz LFO
    "noise_deepnote": "surge/noise_deepnote.wav",   # Surge Rare Earth "Deep Note": six detuned window oscillators, an inharmonic
                                                    # cluster (aperiodic 0.60; weak peaks on D and F, none 10 dB over the noise)
    "noise_saturn": "surge/noise_saturn.wav",       # Surge Inigo Kennedy "Saturn V": sines ring-modulated by S&H noise, a rumble
                                                    # with one resonance (it sounds 440 Hz)
    "noise_timproll": "rec/noise_timproll.wav",     # VSCO 2 timpani roll (CC0), +4.42 st: drum-head modes, the strongest sounding 220 Hz
}
# per candidate, dB so the noise sits 12.0 dB under the sub in the song (active level, channels 4 and 23 soloed)
GAIN = {"noise_faraway": -2.5, "noise_wind": -1.3, "noise_deepnote": -1.2, "noise_saturn": -1.6, "noise_timproll": -3.2}


def mono(path):
    w = read_wav(path)
    x = np.asarray(w.channels, float).mean(axis=0) / 2 ** (w.bits - 1)
    return x, w.rate


def ref_wav():
    return mono(ROOT / "scratch/ut99/nether/nether_samples/01_EAT1_WAV.wav")


def at_ref(y):
    """`y` (44.1 kHz) at the reference's rate by FFT: everything up to its Nyquist kept."""
    m = int(round(len(y) * REF_RATE / RATE))
    X = np.fft.rfft(y)[: m // 2 + 1]
    return np.fft.irfft(X, m) * (m / len(y))


def measure(y):
    """melodic.character of `y` (44.1 kHz, a one-shot) at the reference's storage rate."""
    return melodic.character(at_ref(y), REF_RATE)


def steady(z):
    """melodic.character's steady part of a one-shot `z` (at the reference's rate)."""
    env, h = melodic.envelope_db(z, REF_RATE)
    pk = int(np.argmax(env))
    top = env[pk]
    above3 = np.nonzero(env >= top - 3)[0]
    a = (above3[0] if len(above3) else pk) * h
    live = np.nonzero(env[a // h:] < top - 30)[0]
    return z[a: min(a + (live[0] * h if len(live) else len(z) - a), a + int(1.5 * REF_RATE))]


def quick(z):
    """melodic.character's floor and level movement readings of `z` (at the reference's rate), without its pitch tracking."""
    seg = steady(z)
    out = dict(floor_db=floor_db(seg, REF_RATE))
    se, sh = melodic.envelope_db(seg, REF_RATE)
    lv = se > se.max() - 40
    if lv.sum() >= 20:
        tt = np.arange(len(se))[lv] * sh / REF_RATE
        det = se[lv] - np.polyval(np.polyfit(tt, se[lv], 1), tt)
        out["level_dev_db"] = float(np.std(det))
    return out


def attacks(z):
    """melodic's attack readings (ms to -10 / -3 dB of the peak block) of `z` (at the reference's rate) for every one of
    the 162 block phases (the first p samples dropped): (mean10, mean3, max10, max3, readings10, readings3)."""
    a10, a3 = [], []
    for p in range(HB):
        e, h = melodic.envelope_db(z[p:], REF_RATE)
        top = e.max()
        a10.append(1000 * np.nonzero(e >= top - 10)[0][0] * h / REF_RATE)
        a3.append(1000 * np.nonzero(e >= top - 3)[0][0] * h / REF_RATE)
    return float(np.mean(a10)), float(np.mean(a3)), max(a10), max(a3), a10, a3


def attack_score(r):
    """(phases over the reference's maxima, distance of the means): lower is nearer."""
    m10, m3, _, _, a10, a3 = r
    over = sum(v > ATTACK_REF[2] + 0.5 for v in a10) + sum(v > ATTACK_REF[3] + 0.5 for v in a3)
    return over, abs(m10 - ATTACK_REF[0]) + abs(m3 - ATTACK_REF[1])


def strongest_res(y):
    res = nm.resonances(y, RATE)
    return max(res, key=lambda r: r[1]) if res else None


def cents_from(f, ref_hz):
    c = 1200 * math.log2(f / ref_hz)
    return c - 1200 * round(c / 1200)


def highpass(x, lo=20.0, hi=45.0):
    """Nothing under 20 Hz, all of it over 45 Hz (a raised-cosine ramp between, zero phase, zero-padded: no wrap)."""
    n = 1 << int(math.ceil(math.log2(len(x) + RATE)))
    X = np.fft.rfft(x, n)
    f = np.fft.rfftfreq(n, 1 / RATE)
    g = np.clip((f - lo) / (hi - lo), 0, 1)
    return np.fft.irfft(X * (0.5 - 0.5 * np.cos(np.pi * g)), n)[: len(x)]


def lowpart(x, fc):
    """`x` under `fc` (linear phase, 16383 taps: flat to about fc - 7 Hz); x - lowpart(x) is the rest, exactly."""
    return fir_filter(x, lowpass_fir(fc / RATE, taps=16383))


def steady_spectrum(z):
    """melodic.character's long-term spectrum of the steady part of `z` (at the reference's rate): (freqs, L)."""
    seg = steady(z)
    n = min(8192, 1 << int(math.log2(max(256, len(seg)))))
    frames = [seg[i: i + n] for i in range(0, max(1, len(seg) - n + 1), n // 4)] or [np.pad(seg, (0, n - len(seg)))]
    P = np.array([np.abs(np.fft.rfft(np.pad(f_, (0, n - len(f_))) * np.hanning(n))) ** 2 for f_ in frames])
    return np.fft.rfftfreq(n, 1 / REF_RATE), P.mean(axis=0)


def bandwidths(fq, L):
    Ls = np.convolve(L, np.ones(9) / 9, mode="same")
    ref = Ls.max() + 1e-30
    return [float(fq[np.nonzero(Ls > ref * 10 ** (-d / 10))[0][-1]]) for d in (40, 60)]


def rolloff_db(f, fc, slope):
    return np.where(f > fc, -slope * np.log2(np.maximum(f, 1e-9) / fc), 0.0)


def roll_off(x):
    """The corner and slope (dB per octave) whose roll-off brings the steady part's -40/-60 dB bandwidths nearest BW40/BW60
    (read on the spectrum through the gain; the least attenuation among equals), applied at 44.1 kHz, zero phase.
    Returns (x, fc, slope, the bandwidths before)."""
    fq, L = steady_spectrum(at_ref(x))
    pre = bandwidths(fq, L)
    best = None
    for fc in np.geomspace(200.0, 8000.0, 121):
        for slope in np.arange(0.0, 72.1, 0.5):
            b40, b60 = bandwidths(fq, L * 10 ** (rolloff_db(fq, fc, slope) / 10))
            key = (round(abs(math.log2(b40 / BW40)) + abs(math.log2(b60 / BW60)), 3), slope, -fc)
            if best is None or key < best[0]:
                best = (key, fc, slope)
    _, fc, slope = best
    return apply_rolloff(x, fc, slope), fc, slope, pre


def apply_rolloff(x, fc, slope):
    n = 1 << int(math.ceil(math.log2(len(x) + RATE)))            # zero-padded: no wrap
    X = np.fft.rfft(x, n)
    f = np.fft.rfftfreq(n, 1 / RATE)
    return np.fft.irfft(X * 10 ** (rolloff_db(f, fc, slope) / 20), n)[: len(x)]


def onset(y, n):
    """The start within the first MAX_TRIM whose attack readings over all 162 phases (on the `n` frames it would keep) stay
    within the reference's maxima with means nearest its means (the earliest among equals); where none does, the steady
    rise lifted when that meets them; else the take's own opening, with the reason. Returns (the n frames, trim frames,
    lift dB or None, reason or None)."""
    y = np.pad(y, (0, max(0, n + int(MAX_TRIM * RATE) - len(y))))
    z = at_ref(y[: n + int(MAX_TRIM * RATE)])
    nr = int(round(n * REF_RATE / RATE))
    best = None
    for s in range(0, int(MAX_TRIM * RATE) + 1, RATE // 2000):       # 0.5 ms steps
        sr = round(s * REF_RATE / RATE)
        key = attack_score(attacks(z[sr: sr + nr]))
        if best is None or key < best[0]:
            best = (key, s)
    (over, _), s = best
    y = y[s: s + n].copy()
    if not over:
        return y, s, None, None
    lifted, D = onset_lift(y)
    if D is not None:
        return lifted, s, D, None
    e, h = melodic.envelope_db(at_ref(y), REF_RATE)
    pk = int(np.argmax(e))
    return y, s, None, (f"its first 50 ms sit {e[pk] - e[:5].max():.1f} dB under its loudest 10 ms block at "
                        f"{pk * h / REF_RATE:.2f} s (its own opening kept)")


def onset_lift(y):
    """A rise that climbs steadily lifted: within the first 60 ms and up to the rise's first peak (on the level smoothed
    over 20 ms) within 6 dB of the level the take reaches in its first 250 ms, up to D dB under that level and never over
    that peak (a smooth 5 ms gain, tapered), for the largest D (6 to 0.5 dB) whose readings over all phases meet the
    reference's maxima; (y, D), or (y, None) when no D does."""
    e = nm.level_db(y, RATE, 0.01)
    early = e[: int(0.25 * RATE)].max()
    low = lowpart(y, SPLIT)
    span, sm = int(LIFT_T * RATE), int(0.005 * RATE)
    k = 4 * sm                                                      # 20 ms: a noise's own flicker is not a peak
    es = np.convolve(np.pad(e, (k // 2, k - k // 2 - 1), mode="edge"), np.ones(k) / k, mode="valid")
    near = np.nonzero(es[:span] >= early - 6)[0]
    if len(near):                                                   # the rise ends at its first peak within 6 dB of
        span = int(near[0])                                         # the early level (a roll's first stroke): nothing
        while span + 1 < int(LIFT_T * RATE) and es[span + 1] >= es[span]:   # after it is lifted, nothing over it
            span += 1
    top_rise = es[span]
    taper = np.clip((span - np.arange(span)) / sm, 0, 1)
    for D in np.arange(6.0, 0.4, -0.5):
        g = np.zeros(len(y))
        g[:span] = np.clip(min(early - D, top_rise) - e[:span], 0, 18) * taper
        reach = np.nonzero(e[:span] >= early - D)[0]
        if len(reach):
            g[reach[0]:span] = 0.0                                  # the rise only: nothing once it gets there
        g = np.convolve(g, np.ones(sm) / sm, mode="same")
        z = low + (y - low) * 10 ** (g / 20)                    # above the split only: the sub's side is not lifted
        if not attack_score(attacks(at_ref(z)))[0]:
            return z, float(D)
    return y, None


def add_floor(y, seed):
    """Noise shaped like the take's own spectrum (third-octave smoothed), following its level (30 ms), cut under SPLIT,
    scaled until melodic's floor of the steady part reads FLOOR_DB; nothing when it already does, nor when even noise as
    loud as the take misses it (returns (y, added dB or None, a miss or None))."""
    have = quick(at_ref(y))["floor_db"]
    if have >= FLOOR_DB - 0.05:
        return y, None, None
    f, S = envelope_spectrum(y, RATE, n=4096)
    nz = shaped_noise(len(y), RATE, f, S, seed)
    lvl = np.sqrt(np.convolve(y * y, np.ones(int(0.03 * RATE)) / int(0.03 * RATE), mode="same"))
    nz = nz / (np.sqrt(np.mean(nz ** 2)) + 1e-12) * lvl
    nz = nz - lowpart(nz, SPLIT)                               # after the level-following: nothing on the sub's side
    zy, zn = at_ref(y), at_ref(nz)                             # the resampling is linear: done once for each
    if quick(zy + zn)["floor_db"] < FLOOR_DB:
        return y, None, f"floor target missed: {quick(zy + zn)['floor_db']:.1f} dB with noise as loud as the take"
    lo, hi = -60.0, 0.0
    for _ in range(22):                                        # bisect the added noise's level (dB against the take)
        mid = (lo + hi) / 2
        if quick(zy + zn * 10 ** (mid / 20))["floor_db"] < FLOOR_DB:
            lo = mid
        else:
            hi = mid
    return y + nz * 10 ** (hi / 20), hi, None


def held_end(y, rate):
    """The held part's end: the 200 ms level's first fall 10 dB under its peak, at most 4.5 s (frames)."""
    l2 = nm.level_db(y, rate, 0.2)
    pk = int(np.argmax(l2))
    b = np.nonzero(l2[pk:] < l2[pk] - 10)[0]
    return min(pk + (int(b[0]) if len(b) else len(y) - pk), int(4.5 * rate))


def band_power(y, rate):
    """The three BANDS of `y` (FFT masks, zero-padded: a loud start does not wrap into a quiet end), squared."""
    n = 1 << int(math.ceil(math.log2(2 * len(y))))
    X = np.fft.rfft(y, n)
    f = np.fft.rfftfreq(n, 1 / rate)
    return [np.fft.irfft(np.where((f >= lo) & (f < hi), X, 0), n)[: len(y)] ** 2 for lo, hi in BANDS]


def spread_stats(P, rate, a, e, G=None):
    """Over [a, e): 50 ms band levels (dB, each band's power P[i] times its gain 10**(G[i]/10) when given) less their
    1.5 s moving average (the span's length when shorter); their spreads and the three pair correlations, each averaged
    over PHASES block phases. Spans under 1 s read zeros."""
    h = int(0.05 * rate)
    sps, ccs = [], []
    for ph in range(PHASES):
        s = a + int(ph * h / PHASES)
        devs = []
        for i in range(3):
            q = P[i][s:e] * (10 ** (G[i][s:e] / 10) if G is not None else 1.0)
            c = np.concatenate([[0.0], np.cumsum(q)])
            m = len(q) // h
            if m < 20:
                return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            k = min(30, m)
            lv = 10 * np.log10((c[h: m * h + 1: h] - c[0: m * h: h]) / h + 1e-20)
            devs.append(lv - np.convolve(np.pad(lv, (k // 2, k - k // 2 - 1), mode="edge"), np.ones(k) / k, mode="valid"))
        sps.append([float(np.std(v)) for v in devs])
        ccs.append([float(np.corrcoef(devs[i], devs[j])[0, 1]) for i, j in ((0, 1), (0, 2), (1, 2))])
    return [float(v) for v in np.mean(sps, axis=0)], [float(v) for v in np.mean(ccs, axis=0)]


def band_after(y, rate):
    """The same after the held part, to the file's end fade: spreads only."""
    e = held_end(y, rate)
    end = len(y) - int(END_FADE * rate)
    return spread_stats(band_power(y[:end], rate), rate, e, end)[0]


def rise_after(y, rate):
    """The largest re-swell after the held part: over 200 ms levels every 10 ms from the held part's end to the end fade,
    the most any level rises over the lowest before it (dB)."""
    e = held_end(y, rate)
    l2 = nm.level_db(y, rate, 0.2)[e: len(y) - int(END_FADE * rate): int(0.01 * rate)]
    return float(np.max(l2 - np.minimum.accumulate(l2))) if len(l2) else 0.0


def band_moves(y, rate):
    """The held part's slow movement band by band (spread_stats over [0, held_end))."""
    e = held_end(y, rate)
    return spread_stats(band_power(y[:e], rate), rate, 0, e)


def wander(n, seed):
    """An irregular slow movement, unit spread, `n` frames: random phases and Rayleigh amplitudes on a smooth log-frequency
    bump (centred WANDER_HZ, WANDER_BAND), at a 100 Hz control rate."""
    m = int(math.ceil(n / RATE * 100)) + 1
    fr = np.fft.rfftfreq(m, 0.01)
    rng = np.random.default_rng(seed)
    band = (fr >= WANDER_BAND[0]) & (fr <= WANDER_BAND[1])
    amp = np.zeros(len(fr))
    amp[band] = np.exp(-0.25 * (np.log2(fr[band] / WANDER_HZ) / WANDER_OCT) ** 2)
    w = np.fft.irfft(amp * rng.rayleigh(1.0, len(fr)) * np.exp(2j * np.pi * rng.random(len(fr))), m)
    return w / (np.std(w) + 1e-12)


def add_movement(y, seed0, n, bound=None):
    """Where a band of the held part moves less than the reference's (read from 40 ms in): independent draws added to
    those bands alone (complementary splits at SPLIT, 300 and 700 Hz; nothing under SPLIT moved), each depth solved until
    the band reads the reference's spread; the depths scaled down together while the steady part's whole level movement
    would pass `bound` (default the larger of 1.76 dB and the take's own, plus 0.1); after the moved take's held part
    (over TAPER) each moved band's second depth, solved so the band reads REF_AFTER there (none where the take already
    moves that much; the held depth goes on where under 1 s follows the held part). Of 12 draw sets the one whose onset
    result (before the roll-off and the fades) meets the reference's maxima, then keeps its loudest 10 ms block in its
    first 0.5 s, then has no re-swell after the held part beyond the larger of REF_RISE and the take's own + 0.3 dB,
    then whose band correlations come nearest.
    Returns (onset's result, info dict)."""
    skip = int(MAX_TRIM * RATE)
    yy = y[skip:]
    he = held_end(yy, RATE)
    end = n - int(END_FADE * RATE)
    Pb = band_power(yy[:he], RATE)
    Pa = band_power(yy[:end], RATE)
    own, own_cc = spread_stats(Pb, RATE, 0, he)
    own_after = spread_stats(Pa, RATE, he, end)[0]
    need = [i for i in range(3) if own[i] < REF_BANDS[0][i] - 0.05]
    own_dev = quick(at_ref(y[: n + skip])).get("level_dev_db", 0.0)
    if bound is None:
        bound = max(LEVEL_DEV, own_dev) + 0.1
    own_rise = rise_after(y[: n + skip], RATE)
    rise_cap = max(REF_RISE, own_rise + 0.3)
    info = dict(own=own, own_cc=own_cc, own_after=own_after, need=need, own_dev=own_dev, bound=bound, own_rise=own_rise,
                rise_cap=rise_cap, depths=None, after_depths=None, scale=1.0, moved=y)
    if not need:
        return onset(y, n), info
    l1, l2, l3 = lowpart(y, SPLIT), lowpart(y, 300.0), lowpart(y, 700.0)
    parts = [l2 - l1, l3 - l2, y - l3]
    t = np.arange(len(y)) / RATE
    best = None
    for k in range(12):
        W = np.array([wander(len(t), seed0 + 97 * k + i) for i in range(3)])
        for i in range(1, 3):                                  # the three draws made uncorrelated, then clipped
            for j in range(i):
                W[i] -= W[j] * np.dot(W[i], W[j]) / np.dot(W[j], W[j])
            W[i] /= np.std(W[i]) + 1e-12
        W = np.clip(W, -CLIP, CLIP)
        W = np.array([np.interp(t, np.arange(W.shape[1]) * 0.01, w) for w in W])
        depth, after = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        for _ in range(2):                                     # the bands barely interact: two passes settle them
            for i in need:
                lo_d, hi_d = 0.0, 8.0
                for _ in range(14):
                    depth[i] = (lo_d + hi_d) / 2
                    G = [d * w[skip: skip + he] for d, w in zip(depth, W)]
                    if spread_stats(Pb, RATE, 0, he, G)[0][i] < REF_BANDS[0][i]:
                        lo_d = depth[i]
                    else:
                        hi_d = depth[i]
                depth[i] = hi_d

        ramp = np.clip((t - (skip + he) / RATE) / TAPER, 0, 1)

        def gains(f):
            return [(f * d * (1 - ramp) + a * ramp) * w for d, a, w in zip(depth, after, W)]

        def moved(f):
            return l1 + sum(p * 10 ** (g / 20) for p, g in zip(parts, gains(f)))
        scale = 1.0
        if quick(at_ref(moved(1.0)[: n + skip])).get("level_dev_db", 0.0) > bound:
            lo_f, hi_f = 0.0, 1.0
            for _ in range(10):
                mid = (lo_f + hi_f) / 2
                if quick(at_ref(moved(mid)[: n + skip])).get("level_dev_db", 0.0) > bound:
                    hi_f = mid
                else:
                    lo_f = mid
            scale = lo_f
        he2 = held_end(moved(scale)[skip:], RATE)              # the moved take's own held end (the file's, unless a
                                                               # roll-off moves it: faraway's moves it 91 ms earlier)
        ramp = np.clip((t - (skip + he2) / RATE) / TAPER, 0, 1)
        own_after2 = spread_stats(Pa, RATE, he2, end)[0]
        for i in need:                                         # after the held part: the band to REF_AFTER, where short of it
            if end - he2 < RATE:                                # no span after it to read (the held part runs to 4.5 s):
                after[i] = scale * depth[i]                    # the held depth goes on
                continue
            if own_after2[i] >= REF_AFTER[i] - 0.05:
                continue
            lo_a, hi_a = 0.0, 8.0
            for _ in range(14):
                after[i] = (lo_a + hi_a) / 2
                G = [g[skip: skip + end] for g in gains(scale)]
                if spread_stats(Pa, RATE, he2, end, G)[0][i] < REF_AFTER[i]:
                    lo_a = after[i]
                else:
                    hi_a = after[i]
            after[i] = hi_a
        z = moved(scale)
        rise = rise_after(z[: n + skip], RATE)
        o = onset(z, n)
        sp, cc = band_moves(z[skip:], RATE)
        env, h = melodic.envelope_db(at_ref(o[0]), REF_RATE)
        late = int(np.argmax(env)) * h / REF_RATE > 0.5         # the loudest block after the opening
        score = (attack_score(attacks(at_ref(o[0])))[0], late, rise > rise_cap,
                 sum(abs(a - b) for a, b in zip(cc, REF_BANDS[1])))
        if best is None or score < best[0]:
            best = (score, o, dict(info, depths={i: round(scale * depth[i], 2) for i in need},
                                   after_depths={i: round(after[i], 2) for i in need}, scale=round(scale, 2), moved=z,
                                   rise=rise, draw=k))
    return best[1], best[2]


def low_share(y, cut):
    """dB of the power under `cut` (stored Hz) against the whole, a zero-padded FFT of the whole file."""
    n = 1 << int(math.ceil(math.log2(len(y) + 1)))
    P = np.abs(np.fft.rfft(y, n)) ** 2
    f = np.fft.rfftfreq(n, 1 / RATE)
    return float(10 * np.log10(P[(f > 0) & (f < cut)].sum() / P[f > 0].sum() + 1e-30))


def low_power(y, cut):
    """(power under `cut` stored Hz, all of it), a zero-padded FFT of the whole file."""
    n = 1 << int(math.ceil(math.log2(len(y) + 1)))
    P = np.abs(np.fft.rfft(y, n)) ** 2
    f = np.fft.rfftfreq(n, 1 / RATE)
    return float(P[(f > 0) & (f < cut)].sum()) + 1e-30, float(P[f > 0].sum()) + 1e-30


def make(cand, raw, gain_db=0.0):
    x, r = mono(RAW / raw)
    if r != RATE:
        x = resample(x, r, RATE)
    x = x - np.mean(x)
    lines = [f"{cand} (from {raw}):"]
    # tuning: the strongest resonance onto a B as stored (it sounds on an A, played 2 semitones under)
    res = strongest_res(x)
    tuned = None
    if res:
        c = cents_from(res[0], B_HZ)
        x = resample(x, RATE * 2 ** (-c / 1200), RATE)
        res2 = strongest_res(x)
        tuned = res2[0]
        lines.append(f"  strongest resonance {res[0]:.1f} Hz ({res[2]:.1f} dB over its surroundings) {c:+.1f} c from a B -> "
                     f"{res2[0]:.1f} Hz stored ({cents_from(res2[0], B_HZ):+.1f} c), {res2[0] / AS_STORED:.1f} Hz as played")
    else:
        lines.append("  no resonance (unpitched): not moved")
    n, skip = int(round(SECS * RATE)), int(MAX_TRIM * RATE)
    x = np.pad(x, (0, max(0, n + skip - len(x))))               # silence after a short take first: no filter wraps it
    x = highpass(x)
    x = fir_filter(x, lowpass_fir(TOP / RATE))                  # nothing over the reference's Nyquist
    x = x[: n + skip]
    before = x.copy()
    seed = zlib.crc32(cand.encode())                            # per candidate: no two share their draws
    x, fl_db, fl_miss = add_floor(x, seed=zlib.crc32((cand + ":floor").encode()))
    floored = x
    (x, s, lift, why), mv = add_movement(floored, seed, n)
    x, fc, slope, pre = roll_off(x)
    for attempt in range(4):                                    # the level bound on the finished frame: the take through
        own_fin = quick(at_ref(apply_rolloff(before[s: s + n], fc, slope))).get("level_dev_db", 0.0)   # the same trim and
        bound = max(LEVEL_DEV, own_fin) + 0.1                                                          # roll-off
        over = quick(at_ref(x)).get("level_dev_db", 0.0) - bound
        if not mv["depths"] or over <= 0.005 or attempt == 3:
            break
        (x, s, lift, why), mv = add_movement(floored, seed, n, bound=mv["bound"] - over)
        x, fc, slope, pre = roll_off(x)
    mv["bound_fin"], mv["own_fin"], mv["bound_miss"] = bound, own_fin, max(0.0, over - 0.005)
    fade = int(END_FADE * RATE)
    shape = np.ones(n)
    shape[: int(FADE_IN * RATE)] = np.linspace(0, 1, int(FADE_IN * RATE))
    shape[-fade:] = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, fade))
    x = x * shape
    # level: the held part's RMS to -18 dBFS, then the candidate's gain, then the peak limit
    a = int(np.argmax(nm.level_db(x, RATE, 0.01) >= nm.level_db(x, RATE, 0.01).max() - 3))
    held = x[a: a + int(1.5 * RATE)]
    g = 10 ** ((-18.0 - 10 * np.log10(np.mean(held ** 2) + 1e-20)) / 20) * 10 ** (gain_db / 20)
    x = x * g
    pk = np.abs(x).max()
    limited = pk > 10 ** (-1 / 20)
    if limited:
        g *= 10 ** (-1 / 20) / pk
        x *= 10 ** (-1 / 20) / pk
    out = OUT / f"{cand}.wav"
    write_wav(out, RATE, [np.clip(np.rint(x * 32767), -32768, 32767).astype(int).tolist()], root_note=ROOT_NOTE)
    # the report
    y, _ = mono(out)
    m = measure(y)
    mm = nm.measure(y)
    m10, m3, x10, x3, a10, a3 = attacks(at_ref(y))
    sp, cc = band_moves(y, RATE)
    after = band_after(y, RATE)
    own_after_fin = band_after(apply_rolloff(before[s: s + n], fc, slope), RATE)
    miss = f", missed by {mv['bound_miss']:.3f}" if mv["bound_miss"] else ""
    plain = apply_rolloff(before[s: s + n], fc, slope) * shape * g     # the take through the same trim, filter, fades, gain
    (d104, _), (d80, _) = low_power(x - plain, LOW_CUT), low_power(x - plain, LOW_80)
    w104 = low_power(x, LOW_CUT)[1]
    (o104, _), (o80, _) = low_power(plain, LOW_CUT), low_power(plain, LOW_80)
    fmt = lambda v: [round(u, 2) for u in v]
    lines.append(f"  onset: trimmed {1000 * s / RATE:.1f} ms, {'no lift' if lift is None else f'rise lifted to {lift:.1f} dB under its early level'}; "
                 f"attack over the 162 phases means {m10:.1f}/{m3:.1f} ms, maxima {x10:.0f}/{x3:.0f} ms, phase 0 {a10[0]:.0f}/{a3[0]:.0f} "
                 f"(reference {ATTACK_REF[0]:.1f}/{ATTACK_REF[1]:.1f}, {ATTACK_REF[2]:.0f}/{ATTACK_REF[3]:.0f}, 0/10)"
                 + (f"; not met: {why}" if why else ""))
    lines.append(f"  floor {'none added' if fl_db is None else f'{fl_db:.1f} dB added'}{f' ({fl_miss})' if fl_miss else ''} "
                 f"-> {m['floor_db']:.1f} dB (reference {FLOOR_DB})")
    moved_txt = ("nothing added" if not mv["depths"] else "added " + ", ".join(
        f"{BAND_NAMES[i]} {d} dB (after the held part {mv['after_depths'][i]})" for i, d in mv["depths"].items())
                 + (f" (scaled x{mv['scale']} for the whole level bound)" if mv["scale"] < 1 else "")
                 + f", draw set {mv['draw']}")
    lines.append(f"  band movement (held part, 10 phases) own {fmt(mv['own'])} -> {fmt(sp)} dB, correlations {fmt(mv['own_cc'])} -> "
                 f"{fmt(cc)} (reference {fmt(REF_BANDS[0])}, {fmt(REF_BANDS[1])}); {moved_txt}; kept its own: "
                 f"{', '.join(BAND_NAMES[i] for i in range(3) if i not in mv['need']) or 'none'}; after the held part "
                 f"{fmt(own_after_fin) if any(own_after_fin) else 'none'} own (the take on the file's frame) -> {fmt(after) if any(after) else 'none (the held part runs to 4.5 s)'} "
                 f"(reference {fmt(REF_AFTER)}); re-swell {rise_after(y, RATE):.1f} dB (reference {REF_RISE:.1f}, "
                 f"the take's own {mv['own_rise']:.1f})")
    lines.append(f"  roll-off " + (f"from {fc:.0f} Hz at {slope:.1f} dB per octave" if slope else
                                   f"none ({'its bw40 already under the target' if pre[0] <= BW40 else 'nothing nearer'})")
                 + f", solved on the finished file: bw40/60 {pre[0]:.0f}/{pre[1]:.0f} -> {m['bw40_hz']:.0f}/{m['bw60_hz']:.0f} Hz "
                   f"({BW40:.0f}/{BW60:.0f})")
    lines.append(f"  melodic: level movement {m.get('level_dev_db', 0):.2f} dB at {m.get('tremolo_hz', 0):.2f} Hz (prominence "
                 f"{m.get('tremolo_prominence', 0):.1f}; reference 1.76 at 1.22, 4.1; the take's own on the same frame "
                 f"{mv['own_fin']:.2f}, the bound {mv['bound_fin']:.2f}{miss}), centroid "
                 f"{m['centroid_hz']:.0f} Hz moving {m['centroid_move_hz']:.0f} (401, 91), flatness {m['flatness_db']:.1f} dB (-21.3), "
                 f"aperiodicity {m['aperiodicity']:.2f} (0.59), slope {m.get('level_slope_db_per_s', 0):+.2f} dB/s (-3.13)")
    tt = "/".join("-" if v is None else f"{v:.2f}" for v in (mm["t10"], mm["t20"], mm["t30"]))
    tail = "-" if m["tail_s"] is None else f"{m['tail_s']:.2f}"
    lines.append(f"  stored: secs {m['secs']:.2f}, tail {tail} s (4.94), hold {mm['hold_s']:.2f} s (1.40), t10/20/30 {tt} s "
                 f"(2.94/4.60/4.98), hi2k2 {mm['hi2k2_db']:.1f} dB (-29.9), 10 ms peak {m['peak_dbfs']:.1f} dBFS, sample peak "
                 f"{20 * math.log10(np.abs(y).max() + 1e-12):.1f} dBFS{' (limited)' if limited else ''}; as played (2 semitones "
                 f"under): {m['secs'] * AS_STORED:.2f} s (5.77)")
    rs = strongest_res(y)
    tp = min(mm["res"], key=lambda r: abs(math.log2(r[0] / tuned)))[0] if tuned and mm["res"] else None
    N = 1 << int(math.ceil(math.log2(2 * n)))                  # the added content's low band first, then its first 10 ms
    dl = np.fft.irfft(np.fft.rfft(x - plain, N) * (np.fft.rfftfreq(N, 1 / RATE) < LOW_CUT), N)[:n]
    e10 = float(np.sum(dl[: int(0.01 * RATE)] ** 2) / (np.sum(dl ** 2) + 1e-30))
    body = slice(int(0.1 * RATE), n - fade)
    hb = np.hanning(body.stop - body.start)
    (b104, _), (bo104, _) = low_power((x - plain)[body] * hb, LOW_CUT), low_power(plain[body] * hb, LOW_CUT)
    lines.append(f"  under 104 / 80 Hz as played: {low_share(y, LOW_CUT):.1f} / {low_share(y, LOW_80):.1f} dB of the whole (the "
                 f"file's own share); what the floor, movement and lift added there {10 * math.log10(d104 / o104):.1f} / "
                 f"{10 * math.log10(d80 / o80):.1f} dB against the take's own, {10 * math.log10(d104 / w104):.1f} dB of the "
                 f"whole ({100 * e10:.0f} % of it in the first 10 ms; from 0.1 s to the fade {10 * math.log10(b104 / bo104):.1f} dB "
                 f"against the take's own); resonances stored {mm['res']}"
                 + (f"; the tuned one {tp:.1f} Hz stored ({cents_from(tp, B_HZ):+.1f} c from B), {tp / AS_STORED:.1f} Hz as played"
                    if tp else "") + (f"; strongest now {rs[0]:.1f} Hz stored ({rs[0] / AS_STORED:.1f} as played)"
                                      if rs and tp and abs(rs[0] - tp) > 0.5 else ""))
    fails = nm.passes(mm)
    lines.append(f"  the screens' class limits: {'all met' if not fails else '; '.join(fails)}")
    print("\n".join(lines), flush=True)
    return m


# ------------------------------------------------------------------------------------------------ the pattern

PATTERNS = ["loop", "loop_b"]
STRIKE = {"loop": True, "loop_b": False}                   # every second pattern: struck in loop, nothing in loop_b
PAN = "S89"                                                # pan 38, on the note's row
CHANNEL = "    - {name: Noise, pan: 32, volume: 64}\n"


def figure():
    cols = {p: [dict()] for p in PATTERNS}
    for p in PATTERNS:
        if STRIKE[p]:
            cols[p][0][0] = f"{NOTE} 13 ... {PAN}"
    return cols


def pattern(path=HERE / "rift.yaml", first_sample="noise_placeholder.wav"):
    b = path.read_bytes()
    crlf = b"\r\n" in b
    t = b.decode("utf-8").replace("\r\n", "\n")
    t = ensure_channels(t, CHANNEL, r"    - \{name: Drone[^\n]*\n")
    line = re.search(r"\n  13: \{file:[^\n]*\n", t)
    if not line:
        new = (f"  13: {{file: ../../samples/local/rift-cand/{first_sample}, base_note: {BASE_NOTE}, "
               f"name: {Path(first_sample).stem}}}\n")
        anchor = "\n\ninstruments:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + new + "\ninstruments:\n", 1)
    else:                                                      # the picked file stays; the stored note is the generator's
        fixed = re.sub(r"base_note: [A-G][-#]\d", f"base_note: {BASE_NOTE}", line.group(0))
        t = t[:line.start()] + fixed + t[line.end():]
    if "\n  13: {name: Noise" not in t:
        ins = "  13: {name: Noise, sample: 13}   # sample mode, as in the reference: a one-shot at its own volume\n"
        anchor = "\n\npatterns:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + ins + "\npatterns:\n", 1)
    t = write_columns(t, 22, figure())
    if crlf:
        t = t.replace("\n", "\r\n")
    path.write_bytes(t.encode("utf-8"))
    print(f"wrote channel 23 into {path.name}: {NOTE} {PAN} on row 0 of {[p for p in PATTERNS if STRIKE[p]]}, sample 13 at {BASE_NOTE}")


def reference_figures():
    global ATTACK_REF, REF_BANDS, REF_AFTER, REF_RISE
    x, r = ref_wav()
    m10, m3, x10, x3, _, _ = attacks(x)
    ATTACK_REF = (m10, m3, x10, x3)
    REF_BANDS = band_moves(x, r)
    REF_AFTER = band_after(x, r)
    REF_RISE = rise_after(x, r)


if __name__ == "__main__":
    if sys.argv[1:2] == ["pattern"]:
        pattern(first_sample=next(iter(CANDS), "noise_placeholder") + ".wav")
        sys.exit()
    reference_figures()
    if sys.argv[1:2] == ["ref"]:                                       # the calibration: the reference's own numbers
        x, r = ref_wav()
        c = melodic.character(x, r)
        print("reference:", ", ".join(f"{k} {c[k]:.2f}" for k in ("secs", "attack10_ms", "attack3_ms", "tail_s", "aperiodicity",
                                                                     "floor_db", "flatness_db", "centroid_hz", "centroid_move_hz",
                                                                     "bw40_hz", "bw60_hz", "level_dev_db", "tremolo_hz",
                                                                     "tremolo_prominence", "level_slope_db_per_s")))
        print(f"reference attack over the 162 block phases: means {ATTACK_REF[0]:.1f}/{ATTACK_REF[1]:.1f} ms, maxima "
              f"{ATTACK_REF[2]:.0f}/{ATTACK_REF[3]:.0f} ms; band movement (held part, 10 phases) {[round(v, 2) for v in REF_BANDS[0]]} "
              f"dB, correlations {[round(v, 2) for v in REF_BANDS[1]]}; after the held part {[round(v, 2) for v in REF_AFTER]} dB; "
              f"largest re-swell after it {REF_RISE:.1f} dB")
        y = resample(x, r, RATE)                                       # the chain ours go through, on the reference
        cy = measure(y)
        print(f"reference through 44.1 kHz and at_ref: bw40/60 {cy['bw40_hz']:.0f}/{cy['bw60_hz']:.0f} Hz, flatness "
              f"{cy['flatness_db']:.2f}, centroid {cy['centroid_hz']:.1f}, floor {cy['floor_db']:.2f}, level dev {cy['level_dev_db']:.2f}")
    else:
        for cand, raw in CANDS.items():
            if not sys.argv[1:] or cand in sys.argv[1:]:
                make(cand, raw, GAIN.get(cand, 0.0))
