"""Rift, layer 6 of BRIEF.md's layer plan: the drone, written the way Nether Animal writes its drone (measured with
scratch/ut99-clean/melodic.py, the articulation read from its cells without its notes; only the idioms and the sample
character are taken).

`python suite/rift/gen_drone.py` makes the slot-12 candidates from the screened raw chords (samples/local/rift-cand/
drone/, each our chord A-3 E-4 A-4 C-5 held 7.5 s) the way Nether's drone sample measures (melodic.character on its WAV
with its loop, at its 8353 Hz storage rate; `gen_drone.py ref` prints those figures; ours are read with the same function
at the same rate):
  - 6.26 s, a forward loop of 3.86 s from 2.39 s to the end (the reference's 3.88 s from 2.39 s; here 425 whole cycles
    of the root, the count near 3.88 s that leaves the fifth and the tenth nearest whole cycles), the tone's last 0.4 s
    of the loop blended into what precedes its start with gains set by how alike the two are (the added noise and
    movement are periodic with the loop and need no blend);
  - the reference's swell, read on melodic.py's 10 ms blocks against the peak (a crest inside the loop), for every
    block phase at once (on a sliding 10 ms envelope: a block at any phase reads the sliding value at its centre): the
    first 40 ms near -21 dB, near -14 dB from 50 to 250 ms (the reference's median there, sliding, -13.9), steeply
    through -10 dB
    and -3 dB to a crest at 0.81 s 0.6 dB under the loop's sliding maximum (the reference's -0.59; lowered 0.1 dB at a
    time while the file's peak falls before the loop in more of the 83 phases than the reference's 13 %), then over
    0.4 s to the reference's level before its loop (its mean from there to the loop 0.7 dB under the loop's; the level
    read over 1 s so the movement passes; the reference dips to -7/-10 dB first: not followed), nothing over the lower of
    the crest and the loop's sliding maximum -1 dB until the settle ends (within 0.1 dB: the smoothing comes after the
    cap), nor over -1 dB until the last 0.2 s (where the
    loop's own crests arrive). Up to the crest the gain is
    smooth (10 ms in the first 70 ms, 30 ms after) and follows the sliding envelope's maximum over +-1 block, so no block
    at any phase rises over the curve by more than the smoothing allows (up to about 3 dB in the first 70 ms); the
    -10 and -3 dB knots are scanned until the means over all 83 block phases, against the file's top and the loop's,
    match the reference's own (284.6/572.4 ms either way; its phase-0 reading, 288/566, is one of them, and its
    readings range 280-289 and 493-616 ms over the phases);
  - band-limited at 2.2 kHz (the reference's -40 dB bandwidth; its -60 dB point is its Nyquist, 8-bit storage noise and
    images, which our band-limited sample and compile do not make); nothing under 20 Hz (a 20-45 Hz ramp);
  - a floor of -13.7 dB between the partials: noise shaped like the sound's own spectrum above the root (nothing under
    108 Hz, cut on the loop's own lines, so the wander carries the noise under 104 Hz, the sub's side, no higher than
    about -75 dB of the loop; the low band's wander moving the root's own sidebands leaves about -50 to -75 dB of the
    loop there, printed per candidate; tables' own -39 dB under 104 Hz is its source's), periodic
    with the loop, added only where the sound is purer; before the loop it follows the sound's level (smoothed over
    30 ms) and meets the loop's noise exactly at the loop start;
  - a slow wander, periodic with the loop, shaped like the reference's: its loop's level movement (the detrended 10 ms
    envelope) lies on whole-cycle lines from 0.8 to 2.6 Hz, strongest at 1.3 Hz, 1.43 dB between 0.6 and 3.2 Hz, and it
    moves band by band (100-300, 300-700, 700-2200 Hz spread 2.22/1.75/0.97 dB, nearly uncorrelated: a timbre movement,
    its centroid moving 24 Hz); melodic.py reads it over one loop as 2.06 Hz with prominence 9.4 (a window effect: over
    the loop played twice it reads 1.28 Hz). Ours: in each band (linear-phase FIRs over the sample as it plays) a smooth
    bump on the loop's lines around 1.2 Hz with random phases, the three made exactly uncorrelated over the loop, each
    band topped up over its own movement to the reference's band proportions, scaled until the whole sound's 0.6-3.2 Hz
    part reads 1.43 dB where a sound moves less there (a sound's own movement and flicker stay its own; where about 80 % or
    more of a sound's power sits under 300 Hz (79.7-94 %) its centroid moves 3-15 Hz against the reference's 24: tables, lushpwm,
    churchlike; printed);
    among 24 draws the one whose melodic.py readings (once and
    twice, the loop slope, the centroid's
    movement) come nearest the reference's and whose loop peak stays under the -1 dBFS limit at the candidate's gain;
    the floor noise and the depth solved again under it (a sound's own movement under 0.6 Hz stays its own and can lead
    melodic.py's readings: ahhs);
  - the loop's level held flat before the wander (the reference falls 0.15 dB a second); tuned so the chord's four
    tones sit on equal temperament (their median, each tone's power-weighted centre within 40 cents over the loop: a
    detuned or vibrating ensemble is tuned on its centre, not its strongest peak); a gain per candidate for the level
    9.6 dB under the sub (the layer plan's figure, over the reference's whole song; in its orders 41-48, the alternation
    the loop takes, it reads 8.7, in its v30 holds 11.2); the -1 dBFS peak limit.
  Stored at 44.1 kHz, root A-3 (the chord's lowest note). Partials (the chord's balance), noise colour and each sound's own
  movements stay its own: matching those would rebuild the reference's sample. The printout gives the loop wrap as
  loopscope.py measures it (the jump against a straight line, in % of the loop's RMS, beside the loop's own 99.9th
  percentile) and each tone's pitch movement (scratch/ut99-clean/rifttools/tonevib.py) before the noise and after.
`python suite/rift/gen_drone.py pattern` writes the drone into rift.yaml (channel 22, slot 12, instrument 12):
  - Nether's idiom (its cells, counts only): one chord sample held for the whole section, restated with the instrument
    by a legato note (GFF) on row 0 of every pattern, never retriggered and never moved: its 18 notes carry one written
    pitch. The movement is in the volume column: a v7 entry (struck, no G) swelling one step a row to v30 over 24 rows,
    nine patterns restated at a flat v30, then, while the vocal pad and the second line play, patterns alternating a
    swell from v30 to v40 over 16 rows (the note row v30) and a v40 hold; pan 29; D02 then D00 to silence where it ends.
    The 8-bar loop takes the alternation: loop swells, loop_b holds (the loop's wrap is the reference's v40 -> v30 step);
    the entry swell, the flat v30 patterns and the fade are form work (write the entry without GFF).
  - Our chord: A minor, voiced A-3 E-4 A-4 C-5 inside the sample (stored at A-3), held on A (the sub stays on A).
    scratch/ut99-clean/rifttools/dronecheck.py compares it with Nether's in sounding pitch and prints counts only: the
    same chord quality on the root and no moves on either side (the reference's idiom); our third sits an octave higher
    and the root is doubled.
Channels 1-21 are not touched.
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
from gen_seq import ensure_channels, write_columns  # noqa: E402
import melodic  # noqa: E402  (local only: character() printed the reference's numbers; ours are read with it)
sys.path.insert(0, str(ROOT / "scratch" / "ut99-clean" / "rifttools"))
import tonevib  # noqa: E402  (per-tone pitch movement)

OUT = ROOT / "samples" / "local" / "rift-cand"
RAW = OUT / "drone"
RATE, REF_RATE = 44100, 8353                              # ours; the reference's storage rate (its measures' scale)
BASE_NOTE = "A-3"                                          # the sample's root: the chord's lowest note
VOICING = ["A-3", "E-4", "A-4", "C-5"]                     # the chord inside the sample (rendered as one chord)
ROOT_NOTE = 45                                             # A-3 (the tracker's C-5 is 60)
TONES = [ROOT_NOTE + d for d in (0, 7, 12, 15)]
F_ROOT = 440 * 2 ** ((ROOT_NOTE - 69) / 12)                # 110 Hz
LOW_CUT = F_ROOT * 2 ** (-1 / 12)                          # 104 Hz: no added noise under it (cut 4 Hz higher: the
                                                           # wander, up to 4 Hz, moves the noise's sidebands down)
START = round(20000 / REF_RATE * RATE)                     # the reference's loop start, 2.394 s
LOOP = round(425 * RATE / F_ROOT)                          # 425 cycles of the root, 3.864 s (the reference's 3.880 s)
END = START + LOOP
XFADE = round(0.4 * RATE)
BANDWIDTH = 2199.0
REF_ATTACK = (284.6, 572.4)                                # ms to -10 / -3 dB, the reference's mean over its 83 block phases
HB = int(REF_RATE * 0.01)                                  # melodic's 10 ms block at the reference's rate: 83 samples
CREST_T, SETTLE = 0.81, 0.4                                # the reference's crest, then back to the sound's own level
CRESTS = tuple(-0.6 - 0.1 * k for k in range(15))          # dB under the loop's sliding 10 ms maximum (the reference's
                                                           # crest: -0.59), lowered 0.1 dB at a time while needed
REF_BEFORE = 0.13                                          # the reference's file peak lies before its loop in 13 % of
                                                           # the 83 block phases
PRE_CAP, PRE_MEAN = -1.0, -0.7                             # before the loop, after the crest: no sliding 10 ms level over
                                                           # the loop's maximum -1 dB (the reference's never over -1.79
                                                           # after 1.3 s), the level 0.7 dB under the loop's (its -0.74)
TREM = dict(one=(2.06, 9.4), twice=1.28)                   # melodic's reading of the reference's loop, once and twice
SLOW_BAND, SLOW_DB = (0.6, 3.2), 1.43                      # its level movement's part between 0.6 and 3.2 Hz
REF_SLOPE = -0.15                                          # its loop's level slope, dB/s (melodic)
WANDER_HZ, WANDER_OCT = 1.2, 0.55                          # our wander's bump on the loop's lines (centre, spread)
SPLIT_HZ = (300.0, 700.0)                                  # the wander's bands: 100-300, 300-700, 700-2200 Hz
REF_BANDS = (2.22, 1.75, 0.97)                             # the reference's band spreads (dB, 0.4-4 Hz), nearly
                                                           # uncorrelated (-0.05, -0.31, -0.04)
REF_CENMOVE = 24.0                                         # melodic.py: the reference's centroid moves 24 Hz
FLOOR_DB = -13.7
RMS_DB = -18.0                                             # the loop's level before the per-candidate gain
DRAWS = 24

# candidate -> raw (relative to RAW): five of fourteen finalists of three screens (925 Surge patches, 621 Dexed voices and
# OB-Xd programs, 204 chords from 208 CC0 recordings, measured against the class: our chord held 7.5 s, sustained, steady
# pitch, a floor from -40 to -10 dB, dark enough for the 2.2 kHz band, no tones outside the chord, nothing on our sub;
# screened by those scalar figures, never by spectral likeness to the reference's sample), one per measured character.
# Recipes and screen.txt in drone/surge, drone/dx_obxd (edits inline), drone/rec (work/chords.py builds the chords).
# After processing, OB-Xd "WindSong" (drone_obnoise, dx_obxd/drone_obnoise.wav) measured nearest drone_tables (the floor
# and the wander, set alike for all, had been what told the two dark chords apart), so the vowel pad took its place: of
# the three alternates processed and compared (churchlike, obpwmpad, ahhs) the farthest from the other four;
# `gen_drone.py drone_obnoise` still makes it. Steady pitch (the class's "vibrato <= 12 c", which YIN could not apply to a
# chord): drone/steady.py re-rendered Poly Ahhs without its LFO1 on the pitch (5.2 Hz, about 45 c peak to peak), Lush PWM
# Strings without LFO4/LFO5 on its oscillators' pitch and with its four oscillators' detune (-12.9 to +4.4 c, a 1.0-2.9 Hz
# beat) at 0 (one take of four, pwm_off take 3: the patch is modulated at random), and VOICE 2 with its carriers' -7/+7 detune at 0 and
# its modulators on whole ratios (variant b; leaving the detune, c, still beat 20 c on A-4). The fifth check then found
# Lush PWM's root moving 90 c at 2.2 Hz from the LFOs on its oscillators' shape, width and skew (its PWM): the kept take
# has them off too (steady.py's pwm_off; a static pulse and wavetable, the filter movement kept). Their own floors are
# purer than the reference's -13.7 dB (the printout's "own"), so their -13.7 dB floor is mostly the added noise.
# The recordings screen's finalists were cello-section chords only: every VSCO 2 cello take is a vibrato take (the chord
# read 31-94 c of section vibrato per tone, coherent: outside the class's steady pitch; rec/drone_cello.wav, rebuilt
# from takes Nadir's beds do not play, stays in drone/rec), and the horn chords lose their roots' fundamentals (33-40 dB
# under the octave: the chord reads with E at the bottom). The fifth slot went to the organ: of the two steady synth
# alternates, made with this code, its nearest of the other four is farther (0.64, lushpwm; obnoise 0.41, tables: the
# second check's distance features, normalised over the six); by another checker's features it sits nearest fmvoice
# (0.50, nearer than any pair of the four) where obnoise sits farther (0.93, tables). Its own 5.1 Hz rotary, which neither
# feature set reads, decided it; `gen_drone.py drone_obnoise` makes obnoise if the owner wants to hear it.
CANDS = {
    "drone_lushpwm": "drone_lushpwm_steady.wav",    # Surge Dan Maurer "Lush PWM Strings", steadied: a still pulse/wavetable pad
    "drone_tables": "surge/drone_tables.wav",       # Surge Inigo Kennedy "Tables Turning": dark wavetable atmosphere; its own 1.9 Hz
    # swing is its +-15 c octave layers beating (A-4: a periodic 11 c at the source, at the steady-pitch limit; kept)
    "drone_ahhs": "drone_ahhs_steady.wav",          # Surge "Poly Ahhs": one wavetable through a filter, a vowel (formant) pad
    "drone_fmvoice": "drone_fmvoice_b_carriers_mods.wav",   # Dexed SynprezFM_18 "VOICE 2": FM voice, a clean floor of its own
    "drone_churchlike": "surge/drone_churchlike.wav",   # Surge Malfunction "Churchlike": a noise-excited organ, its own rotary (5.1 Hz)
}
# per candidate, dB so the drone sits 9.6 dB under the sub in the song (whole-song power, channels 4 and 22 soloed:
# 9.56-9.66 dB, fmvoice the 9.66; 2.3 would read 9.56 for it; a candidate whose loop peak meets the -1 dBFS limit sits
# where the limit holds it)
GAIN = {"drone_lushpwm": 2.3, "drone_tables": 2.4, "drone_ahhs": 2.3, "drone_fmvoice": 2.2, "drone_churchlike": 2.2,
        "drone_obnoise": 2.2}


def ref_wav():
    w = read_wav(ROOT / "scratch/ut99/nether/nether_samples/24_Strong1.wav")
    return np.asarray(w.channels, float).mean(axis=0) / 2 ** (w.bits - 1), w.rate


def measure(y, loop=True):
    """melodic.character of `y` (44.1 kHz, our loop) at the reference's storage rate."""
    z = resample(y, RATE, REF_RATE)
    s = round(START * REF_RATE / RATE)
    return melodic.character(z, REF_RATE, ("fwd", s, s + round(LOOP * REF_RATE / RATE)) if loop else None)


def ref_loop(z):
    s = round(START * REF_RATE / RATE)
    return z[s: s + round(LOOP * REF_RATE / RATE)]


def twice(y):
    """melodic.character's movement reading of our loop played twice (at the reference's rate)."""
    lz = ref_loop(resample(y[:END], RATE, REF_RATE))
    return melodic.character(np.tile(lz, 2), REF_RATE, ("fwd", 0, 2 * len(lz)))


def loop_floor(y):
    """melodic.py's floor of the loop, at the reference's storage rate."""
    return melodic.floor_db(ref_loop(resample(y[:END], RATE, REF_RATE)), REF_RATE)


def wander(n, seed):
    """A slow level movement periodic with the loop and aligned to its start, unit spread, `n` frames: random phases and
    Rayleigh amplitudes on the loop's whole-cycle lines under a smooth bump (log-frequency, centred WANDER_HZ), 0.6-4 Hz,
    evaluated at a 100 Hz control rate."""
    m = round(LOOP / RATE * 100)
    fr = np.arange(m // 2 + 1) * RATE / LOOP                     # the loop's lines
    rng = np.random.default_rng(seed)
    amp = np.zeros(len(fr))
    band = (fr >= 0.6) & (fr <= 4.0)                             # (the reference's lines under 0.6 Hz: 9-21 dB down
    #                          over its whole envelope, 7-21 dB band by band, on band_moves' reading: blocks, linear detrend)
    amp[band] = np.exp(-0.25 * (np.log2(fr[band] / WANDER_HZ) / WANDER_OCT) ** 2)   # sqrt of the power bump
    spec = amp * rng.rayleigh(1.0, len(fr)) * np.exp(2j * np.pi * rng.random(len(fr)))
    w = np.fft.irfft(spec, m)
    w /= np.std(w) + 1e-12
    t = (np.arange(n) - START) % LOOP
    return np.interp(t, np.arange(m + 1) * LOOP / m, np.append(w, w[0]))


def band_moves(y):
    """The loop's slow movement band by band (100-300, 300-700, 700-2200 Hz, FFT masks on the periodic loop): each band's
    10 ms envelope (dB) detrended and kept at 0.4-4 Hz, its spread, and the correlations of the three pairs."""
    seg = y[START:END]
    X = np.fft.rfft(seg)
    f = np.fft.rfftfreq(len(seg), 1 / RATE)
    envs = []
    for lo, hi in ((100.0, SPLIT_HZ[0]), SPLIT_HZ, (SPLIT_HZ[1], 2200.0)):
        e, h = melodic.envelope_db(np.fft.irfft(np.where((f >= lo) & (f < hi), X, 0), len(seg)), RATE)
        tt = np.arange(len(e)) * h / RATE
        e = e - np.polyval(np.polyfit(tt, e, 1), tt)
        E = np.fft.rfft(e)
        fr = np.fft.rfftfreq(len(e), h / RATE)
        E[(fr < 0.4) | (fr > 4.0)] = 0
        envs.append(np.fft.irfft(E, len(e)))
    return ([float(np.std(v)) for v in envs],
            [float(np.corrcoef(envs[i], envs[j])[0, 1]) for i, j in ((0, 1), (0, 2), (1, 2))], envs)


def slow_dev(y):
    """The part of the loop's level movement between 0.6 and 3.2 Hz: melodic.py's detrended 10 ms envelope (at the
    reference's rate, frames within 40 dB of the loudest) kept in that band, its spread in dB (the reference: 1.43)."""
    z = ref_loop(resample(y[:END], RATE, REF_RATE))
    se, sh = melodic.envelope_db(z, REF_RATE)
    live = se > se.max() - 40
    tt = np.arange(len(se))[live] * sh / REF_RATE
    det = se[live] - np.polyval(np.polyfit(tt, se[live], 1), tt)
    F = np.fft.rfft(det)
    fr = np.fft.rfftfreq(len(det), sh / REF_RATE)
    F[(fr < SLOW_BAND[0]) | (fr > SLOW_BAND[1])] = 0
    return float(np.std(np.fft.irfft(F, len(det))))


def env_db(y, win=0.01):
    h = int(RATE * win)
    e = np.sqrt(np.convolve(y * y, np.ones(h) / h, mode="same"))
    return 20 * np.log10(e + 1e-9)


def highpass(x, lo=20.0, hi=45.0):
    """Nothing under 20 Hz, all of it over 45 Hz (a raised-cosine ramp between, zero phase): one source's waveform
    baseline moves with its beat (energy under 30 Hz, on the sub's channel of the mix); the chord starts at 110 Hz."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    g = np.clip((f - lo) / (hi - lo), 0, 1)
    return np.fft.irfft(X * (0.5 - 0.5 * np.cos(np.pi * g)), len(x))


def tone_centre(seg, t):
    """Power-weighted centre (cents from equal temperament) of the spectrum within 40 cents of tracker note `t`, and the
    strongest peak there."""
    n = 1 << 20
    P = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n)) ** 2
    f = np.fft.rfftfreq(n, 1 / RATE)
    ft = 440 * 2 ** ((t - 69) / 12)
    sel = (f > ft * 2 ** (-40 / 1200)) & (f < ft * 2 ** (40 / 1200))
    c = 1200 * np.log2(f[sel] / ft)
    return float(np.sum(c * P[sel]) / np.sum(P[sel])), float(c[np.argmax(P[sel])])


def chord_cents(x, spread=False):
    """Each chord tone's centre over the loop (cents from equal temperament); with `spread`, also the strongest peaks and
    the range of the centre over one-second windows."""
    cen = [tone_centre(x[START:END], t) for t in TONES]
    if not spread:
        return [c for c, _ in cen]
    win = [[tone_centre(x[a:a + RATE], t)[0] for a in range(START, END - RATE + 1, RATE // 2)] for t in TONES]
    return [c for c, _ in cen], [p for _, p in cen], [(min(w), max(w)) for w in win]


def wrap_pct(y):
    """loopscope.py's wrap: the jump after the loop's end against a straight line, and the loop's own 99.9th percentile
    of that step, in % of the loop's RMS."""
    loop = y[START:END]
    seq = np.concatenate([loop, loop[:4]])
    jump = abs(seq[LOOP] - (2 * seq[LOOP - 1] - seq[LOOP - 2]))
    inside = np.percentile(np.abs(np.diff(loop[:-74], 2)), 99.9)
    rms = np.sqrt(np.mean(loop ** 2)) + 1e-12
    return 100 * jump / rms, 100 * inside / rms


def low_share(y, window=False):
    """dB of the loop's power under 104 Hz: as played for a periodic loop, with a Hann window for the raw span before
    processing (which does not wrap)."""
    P = np.abs(np.fft.rfft(y[START:END] * (np.hanning(LOOP) if window else 1.0))) ** 2
    f = np.fft.rfftfreq(LOOP, 1 / RATE)
    return float(10 * np.log10(P[(f > 0) & (f < LOW_CUT)].sum() / P.sum() + 1e-30))


def make(cand, raw, gain_db=0.0):
    w = read_wav(RAW / raw)
    x = np.asarray(w.channels, float).mean(axis=0) / 2 ** (w.bits - 1)
    if w.rate != RATE:
        x = resample(x, w.rate, RATE)
    on = int(np.nonzero(np.abs(x) > np.abs(x).max() * 10 ** (-50 / 20))[0][0])
    x = highpass(x[on:])
    assert len(x) >= END + RATE // 4, f"{raw}: too short"
    was = chord_cents(x)
    x = resample(x, RATE * 2 ** (-float(np.median(was)) / 1200), RATE)    # the chord's centre on equal temperament
    x = fir_filter(x, lowpass_fir(BANDWIDTH / RATE))[:END].copy()
    raw_low = low_share(x, window=True)
    seed = sum(map(ord, cand))
    own = measure(x)
    own_slow = slow_dev(x)
    own2 = twice(x)
    notes = []
    # the loop's level held flat: its slope in dB taken out over the loop (1 at the loop start, so nothing jumps there)
    e = env_db(x[START:END])[::441]
    slope = np.polyfit(np.arange(len(e)) * 441, e, 1)[0]
    x[START:END] *= 10 ** (-slope * np.arange(LOOP) / 20)
    notes.append(f"loop slope {slope * RATE:+.1f} dB/s flattened")
    # the tone's wrap: the loop's last 0.4 s blend into what precedes its start
    a, b = x[END - XFADE:END].copy(), x[START - XFADE:START]
    rho = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    r = np.linspace(0, 1, XFADE)
    x[END - XFADE:END] = (a * (1 - r) + b * r) / np.sqrt((1 - r) ** 2 + r ** 2 + 2 * max(rho, -0.5) * r * (1 - r))
    notes.append(f"blend correlation {rho:+.2f}")
    tone = x
    # the floor: noise shaped like the loop's spectrum, one loop long (so periodic), nothing under 104 Hz (cut on the
    # loop's own lines); before the loop it follows the level (up to 1.5 times the loop's) and meets 1 at the loop start
    loop = tone[START:END]
    f, S = envelope_spectrum(np.tile(loop, 3), RATE)
    burst = fir_filter(np.tile(shaped_noise(LOOP, RATE, f, S, seed=LOOP + seed), 3), lowpass_fir(BANDWIDTH / RATE))[LOOP:2 * LOOP]
    B = np.fft.rfft(burst)
    B[np.fft.rfftfreq(LOOP, 1 / RATE) < LOW_CUT + 4.0] = 0
    burst = np.fft.irfft(B, LOOP)
    noise = burst[(np.arange(END) - START) % LOOP] * np.sqrt(np.mean(loop ** 2)) / np.sqrt(np.mean(burst ** 2))
    k = np.minimum(10 ** (env_db(tone)[:START] / 20) / np.sqrt(np.mean(loop ** 2)), 1.5)
    hk = np.hanning(round(0.03 * RATE))
    k = np.convolve(np.concatenate([np.full(len(hk), k[0]), k, np.full(len(hk), k[-1])]), hk / hk.sum(), mode="same")[len(hk):-len(hk)]
    ramp = round(0.1 * RATE)
    k[-ramp:] = np.linspace(k[-ramp], 1.0, ramp)
    noise[:START] *= k

    # the three bands of the tone and of the noise (linear-phase FIRs, split over the sequence as it plays: the sample, then
    # the loop again, so the band signals run on through the loop's wrap)
    def split(sig):
        ext = np.concatenate([sig[:END], sig[START:END]])
        lows = [fir_filter(ext, lowpass_fir(c / RATE, taps=4001))[:END] for c in SPLIT_HZ]
        return [lows[0], lows[1] - lows[0], sig[:END] - lows[1]]

    tone_b, noise_b = split(tone), split(noise)

    def floor_gain(movs):
        """The noise gain (dB) for the floor, under the band movements `movs` (gain curves), or None if the sound's own
        floor is noisier already."""
        X_ = sum(tb_ * m_ for tb_, m_ in zip(tone_b, movs))
        if loop_floor(X_) >= FLOOR_DB - 0.5:
            return None
        N_ = sum(nb_ * m_ for nb_, m_ in zip(noise_b, movs))
        s_, e_ = round(START * REF_RATE / RATE), round(END * REF_RATE / RATE)
        X, N = resample(X_, RATE, REF_RATE), resample(N_, RATE, REF_RATE)   # linear: resampled once
        lo, hi = -80.0, 10.0
        for _ in range(28):
            g_ = (lo + hi) / 2
            fl = melodic.floor_db((X + N * 10 ** (g_ / 20))[s_:e_], REF_RATE)
            lo, hi = (g_, hi) if fl < FLOOR_DB else (lo, g_)
        return (lo + hi) / 2

    def build(g_db, movs):
        gn = 10 ** (g_db / 20) if g_db is not None else 0.0
        return sum((tb_ + nb_ * gn) * m_ for tb_, nb_, m_ in zip(tone_b, noise_b, movs))

    one = [np.ones(END)] * 3
    g_db = floor_gain(one)
    x = build(g_db, one)
    # the slow wander, band by band (the reference's bands move on their own: 100-300, 300-700, 700-2200 Hz spread
    # 2.22/1.75/0.97 dB between 0.4 and 4 Hz, nearly uncorrelated; melodic.py reads that as its centroid moving 24 Hz):
    # three draws on the loop's lines, made uncorrelated with each other and with their band's own movement (orth), each
    # band topped up over its own movement to the scaled reference proportions (depths), scaled until the whole sound's
    # 0.6-3.2 Hz part reads the reference's 1.43 dB where the sound moves less there; the draw whose melodic.py readings (once and
    # twice, the loop slope, the centroid's movement) come nearest the reference's and whose loop peak stays under the
    # -1 dBFS limit at the candidate's gain; then the floor and the depth solved again under it, twice
    have = slow_dev(x)
    own_b, _, own_env = band_moves(x)                               # each band's own slow movement
    own_env = [np.fft.irfft(np.where(np.fft.rfftfreq(len(e_), 0.01) < 0.6, 0, np.fft.rfft(e_)), len(e_)) for e_ in own_env]
    own_env = [np.interp(np.arange(LOOP), (np.arange(len(e_)) + 0.5) * LOOP / len(e_), e_, period=LOOP) for e_ in own_env]
    # (its 0.6-4 Hz part only: a draw projected off it keeps no line under 0.6 Hz)
    movs, depth, pick = one, 0.0, None
    if have < SLOW_DB - 0.05:
        def orth(wv):
            """The three draws made uncorrelated over the loop with their own band's movement at 0.6-4 Hz as band_moves
            reads it (so each band's top-up adds in power) and with each other (a joint projection on one loop; they
            are periodic on the same lines), each of unit spread, extended periodically."""
            segs = [w_[START:END] - w_[START:END].mean() for w_ in wv]
            out = []
            for b_, v in enumerate(segs):
                A = np.column_stack([own_env[b_] - own_env[b_].mean()] + out)          # projected off jointly
                v = v - A @ np.linalg.lstsq(A, v, rcond=None)[0]
                out.append(v)
            idx = (np.arange(END) - START) % LOOP
            return [(v / (np.std(v) + 1e-12))[idx] for v in out]

        def depths(sc):
            """Each band topped up to its share of the scaled reference proportions, over its own movement."""
            return [math.sqrt(max((sc * rb) ** 2 - ob ** 2, 0.0)) for rb, ob in zip(REF_BANDS, own_b)]

        def solve(s, g_):
            wv = orth([wander(END, s * 3 + b) for b in range(3)])
            sc = math.sqrt(SLOW_DB ** 2 - have ** 2) / REF_BANDS[0]
            for _ in range(6):
                got = slow_dev(build(g_, [10 ** (w_ * d_ / 20) for w_, d_ in zip(wv, depths(sc))]))
                if abs(got - SLOW_DB) < 0.03:
                    break
                sc *= math.sqrt(max(SLOW_DB ** 2 - have ** 2, 0.01) / max(got ** 2 - have ** 2, 0.01))
            return sc, [10 ** (w_ * d_ / 20) for w_, d_ in zip(wv, depths(sc))]

        best = None
        for s in range(seed * 97, seed * 97 + DRAWS):
            sc, mv = solve(s, g_db)
            y_ = build(g_db, mv)
            m1, m2 = measure(y_), twice(y_)
            lp = y_[START:END]
            crest_db = 20 * np.log10(np.abs(lp).max()) - 10 * np.log10(np.mean(lp ** 2))
            over = max(0.0, crest_db + RMS_DB + gain_db + 1.0)             # dB over the -1 dBFS limit at this gain
            score = (abs(m1.get("tremolo_hz", 0) - TREM["one"][0]) / 0.2 + abs(m1.get("tremolo_prominence", 0) - TREM["one"][1]) / 2
                     + abs(m2.get("tremolo_hz", 0) - TREM["twice"]) / 0.2
                     + abs(m1.get("level_slope_db_per_s", 0) - REF_SLOPE) / 0.2
                     + abs(m1.get("centroid_move_hz", 0) - REF_CENMOVE) / 5 + 10 * over)
            if best is None or score < best[0]:
                best = (score, s)
        pick = best[1]
        for _ in range(2):
            depth, movs = solve(pick, g_db)
            g_db = floor_gain(movs) if g_db is not None else None
        depth, movs = solve(pick, g_db)
        dd = depths(depth)
        notes.append(f"slow wander by band {dd[0]:.2f}/{dd[1]:.2f}/{dd[2]:.2f} dB over its own {own_b[0]:.2f}/{own_b[1]:.2f}/"
                     f"{own_b[2]:.2f} (draw {pick - seed * 97} of {DRAWS})")
    else:
        notes.append(f"no wander added (its own 0.6-3.2 Hz part reads {have:.2f} dB)")
    if g_db is not None:
        notes.append(f"noise at {g_db:+.1f} dB")
    base = build(g_db, movs)
    # the swell, on a sliding 10 ms envelope at the reference's rate (every block phase at once: a block of melodic.py's
    # grid at any phase reads the sliding value at its centre) against the loop's sliding maximum
    zb = resample(base, RATE, REF_RATE)
    n = len(zb)
    t = np.arange(n) / REF_RATE
    stb = START / RATE                                             # the loop start, s
    s0 = round(START * REF_RATE / RATE)
    c2 = np.concatenate([[0.0], np.cumsum(zb * zb)])
    lo_, hi_ = np.clip(np.arange(n) - HB // 2, 0, n), np.clip(np.arange(n) + HB - HB // 2, 0, n)
    es = 10 * np.log10((c2[hi_] - c2[lo_]) / HB + 1e-30)           # sliding 10 ms power, dB
    top = es[s0:].max()                                            # the loop's sliding maximum
    pad = np.concatenate([np.full(HB, es[0]), es, np.full(HB, es[-1])])
    M = np.lib.stride_tricks.sliding_window_view(pad, 2 * HB + 1).max(axis=1)   # its maximum over +-1 block
    early = t < 0.06
    M[early] = es[early]                                           # (the first 60 ms: its own)
    hann = np.hanning(round(0.03 * REF_RATE))
    hann /= hann.sum()
    hann10 = np.hanning(round(0.01 * REF_RATE))
    hann10 /= hann10.sum()
    h1 = np.hanning(REF_RATE)
    h1 /= h1.sum()
    loop_db = 10 * np.log10(np.mean(zb[s0:] ** 2))

    def smooth(g, h):
        return np.convolve(np.concatenate([np.full(len(h), g[0]), g, np.full(len(h), g[-1])]), h, mode="same")[len(h):-len(h)]

    def lvl1(g):
        """The 1 s level (dB) of the signal under gain g (dB), read with a 1 s Hann."""
        return 10 * np.log10(smooth(zb * zb * 10 ** (g / 10), h1) + 1e-30)

    def gain_curve(k10, k3, crest):
        """dB per sample at the reference's rate: the curve over the sliding envelope's running maximum up to the crest
        (smoothed over 10 ms in the first 70 ms, 30 ms after), then from the crest the sound's own level eased (twice,
        on its 1 s level) to the reference's pre-loop level and capped under the loop's top, 0 dB from the loop start."""
        kc = max(CREST_T, k3 + 0.1)
        knots = [0.0, 0.04, 0.05, min(0.25, k10 - 0.04), k10 - 0.02, k10 + 0.02, k3 - 0.02, k3 + 0.02, kc]
        T = np.interp(t, knots, [top - 21, top - 21, top - 12.5, top - 12.5, top - 11.5, top - 8.5, top - 4.0, top - 2.0,
                                 top + crest])
        G = np.clip(T - M, -60, 36)
        after = t > kc
        w_ = np.clip((t - kc) / SETTLE, 0, 1) * np.clip((stb - t) / 0.4, 0, 1)       # the easing's weight
        gc = np.interp(kc, t, G)
        G[after] = (gc * np.clip(1 - (t - kc) / SETTLE, 0, 1))[after]
        for _ in range(2):
            G[after] += (w_ * ((loop_db + PRE_MEAN) - lvl1(np.where(t >= stb, 0.0, G))))[after]
        span_ = (t >= kc + SETTLE) & (t < stb)                   # the plain mean from the settle to the loop start
        for _ in range(2):
            got = 10 * np.log10(np.mean(zb[span_] ** 2 * 10 ** (G[span_] / 10)) + 1e-30)
            G[after] += (w_ * ((loop_db + PRE_MEAN) - got))[after]
        lim = top + np.where(t < kc + SETTLE, min(PRE_CAP, crest), PRE_CAP)
        lim = lim + (top + 0.0 - lim) * np.clip((t - (stb - 0.2)) / 0.2, 0, 1)
        G[after] = np.minimum(G, lim - M)[after]
        G[t >= stb] = 0.0
        g30, g10 = smooth(G, hann), smooth(G, hann10)
        mix = np.clip((t - 0.07) / 0.03, 0, 1)
        g = g10 * (1 - mix) + g30 * mix
        g -= np.interp(stb, t, g) * np.clip((t - (stb - 0.2)) / 0.2, 0, 1)      # exactly 0 dB at the loop start
        g[t >= stb] = 0.0
        return g

    def phase_stats(z):
        """Over the 83 block phases: the attack means against the file's top, the share of phases whose file peak lies
        before the loop, and the attack means against each phase's loop top."""
        r_, before, rl = [], 0, []
        for p in range(HB):
            env, h = melodic.envelope_db(np.concatenate([np.zeros(p), z]), REF_RATE)
            sb = (s0 + p) // h
            ft, lt = env.max(), env[sb + 1:].max()
            before += env[:sb].max() > lt
            r_.append(((np.nonzero(env >= ft - 10)[0][0] * h - p), (np.nonzero(env >= ft - 3)[0][0] * h - p)))
            rl.append(((np.nonzero(env >= lt - 10)[0][0] * h - p), (np.nonzero(env >= lt - 3)[0][0] * h - p)))
        k = 1000 / REF_RATE
        return np.array(r_) * k, before / HB, np.array(rl) * k

    def score(k10, k3):
        a, share, al = phase_stats(zb * 10 ** (gain_curve(k10, k3, crest) / 20))
        m_ = (a.mean(axis=0) + al.mean(axis=0)) / 2                # against the file's top and the loop's alike
        return abs(m_[0] - REF_ATTACK[0]) + abs(m_[1] - REF_ATTACK[1]) + 200 * max(0.0, share - REF_BEFORE)

    k10, k3 = REF_ATTACK[0] / 1000, REF_ATTACK[1] / 1000
    for crest in CRESTS:                                           # the crest as high as the reference's, lowered while
        if phase_stats(zb * 10 ** (gain_curve(k10, k3, crest) / 20))[1] <= REF_BEFORE:   # the file's peak falls
            break                                                  # before the loop more often than its
    for _ in range(2):                                             # coordinate scans over the two knots
        k3 = min(np.arange(max(0.40, k10 + 0.1), 0.72, 0.005), key=lambda v: score(k10, v))
        k10 = min(np.arange(0.14, min(0.42, k3 - 0.1), 0.005), key=lambda v: score(v, k3))
    k3 = min(np.arange(max(0.40, k10 + 0.1), 0.72, 0.005), key=lambda v: score(k10, v))
    g = gain_curve(k10, k3, crest)
    y = base.copy()
    y[:START] *= 10 ** (np.interp(np.arange(START) / RATE, t, g) / 20)
    notes.append(f"swell knots {k10 * 1000:.0f}/{k3 * 1000:.0f} ms, crest {crest:+.1f} dB")
    fi = round(0.002 * RATE)
    y[:fi] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(fi) / fi)
    y *= 10 ** ((RMS_DB + gain_db) / 20) / np.sqrt(np.mean(y[START:END] ** 2))
    peak = np.abs(y).max()
    limited = peak > 10 ** (-1 / 20)
    if limited:
        y *= 10 ** (-1 / 20) / peak
    pcm = np.clip(np.round(y * 32767), -32768, 32767).astype(int).tolist()
    write_wav(OUT / f"{cand}.wav", RATE, [pcm], 16, loop=(START, END, False), root_note=ROOT_NOTE)
    yy = np.array(pcm, float) / 32767
    m, m2 = measure(yy), twice(yy)
    zz = resample(yy, RATE, REF_RATE)
    ph, share, phl = phase_stats(zz)
    cen, strong, spread = chord_cents(yy, spread=True)
    wj, wo = wrap_pct(yy)
    tm_tone, tm = tonevib.moves(tone[START:END], RATE), tonevib.moves(yy[START:END], RATE)
    c2z = np.concatenate([[0.0], np.cumsum(zz * zz)])
    esz = 10 * np.log10((c2z[np.clip(np.arange(len(zz)) + HB - HB // 2, 0, len(zz))] - c2z[np.clip(np.arange(len(zz)) - HB // 2, 0, len(zz))]) / HB + 1e-30)
    pre_max = esz[:s0].max() - esz[s0:].max()
    crest_max = esz[: round((max(CREST_T, k3 + 0.1) + SETTLE) * REF_RATE)].max() - esz[s0:].max()
    bsp, bcc, _ = band_moves(yy)
    pre_mean = 10 * np.log10(np.mean(zz[round((CREST_T + SETTLE) * REF_RATE): s0] ** 2)) - 10 * np.log10(np.mean(zz[s0:] ** 2))
    print(f"{cand:16s} <- {raw}; added: {'; '.join(notes)}{'; PEAK-LIMITED' if limited else ''}\n"
          f"    chord was {' '.join(f'{c:+.1f}' for c in was)} c (centres), now {' '.join(f'{c:+.1f}' for c in cen)} "
          f"(strongest peaks {' '.join(f'{c:+.0f}' for c in strong)}; centres over half-overlapping 1 s windows "
          f"{' '.join(f'{a:+.0f}..{b:+.0f}' for a, b in spread)})\n"
          f"    own: floor {own['floor_db']:.1f} dB, level {own.get('level_dev_db', 0):.1f} dB at {own.get('tremolo_hz', 0):.2f} Hz "
          f"(prom {own.get('tremolo_prominence', 0):.1f}; twice {own2.get('tremolo_hz', 0):.2f} Hz), 0.6-3.2 Hz {own_slow:.2f} dB, "
          f"attack {own['attack10_ms']:.0f}/{own['attack3_ms']:.0f} ms\n    now: {fmt(m)}; twice {m2.get('tremolo_hz', 0):.2f} Hz "
          f"(prom {m2.get('tremolo_prominence', 0):.1f}); 0.6-3.2 Hz {slow_dev(yy):.2f} dB; flatness 50 Hz-2.2 kHz {ours_flat(yy):.1f} dB; "
          f"under 104 Hz {low_share(yy):.1f} dB of the loop (before processing {raw_low:.1f})\n"
          f"    attack over the 83 block phases: mean {ph[:, 0].mean():.1f}/{ph[:, 1].mean():.1f} ms against the file's top, "
          f"{phl[:, 0].mean():.1f}/{phl[:, 1].mean():.1f} against the loop's (reference {REF_ATTACK[0]}/{REF_ATTACK[1]} either way), "
          f"ranges {ph[:, 0].min():.0f}-{ph[:, 0].max():.0f} / {ph[:, 1].min():.0f}-{ph[:, 1].max():.0f} (reference 280-289 / 493-616); "
          f"the file's peak before the loop in {100 * share:.0f} % of phases (reference {100 * REF_BEFORE:.0f} %)\n"
          f"    wrap {wj:.2f} % (the loop's own {wo:.2f} %); before the loop: the crest {crest_max:+.2f} dB against the loop's "
          f"sliding top (reference -0.59), the highest anywhere before it {pre_max:+.2f}, level from 1.21 s {pre_mean:+.2f} dB "
          f"(reference -0.74)\n    slow movement by band (100-300, 300-700, 700-2200 Hz): {bsp[0]:.2f}/{bsp[1]:.2f}/{bsp[2]:.2f} dB, "
          f"correlations {bcc[0]:+.2f}/{bcc[1]:+.2f}/{bcc[2]:+.2f} (reference 2.22/1.75/0.97, -0.05/-0.31/-0.04)"
          f"{'; SHARE OVER THE REFERENCE' if share > REF_BEFORE else ''}\n"
          f"    tone pitch movement (A-3 E-4 A-4 C-5), tonevib.py: tone before the noise {tonevib.fmt(tm_tone)}; final {tonevib.fmt(tm)}; "
          f"periodic over 12 c: source {tonevib.periodic_over(tm_tone) or 'none'} (the class limit applies here), final "
          f"{tonevib.periodic_over(tm) or 'none'} (a source's own line near the limit and the added floor's jitter can read "
          f"periodic there; the reference's tones pass)")


def flat_band(z, s, e, rate=REF_RATE, lo=50.0, hi=2200.0):
    """Flatness of z[s:e] over 50 Hz-2.2 kHz at the reference's rate: melodic.py's band reaches 3.76 kHz, where our band
    limit leaves only the 16-bit floor and the reference keeps its 8-bit noise."""
    z = z[s:e]
    n = 4096
    P = np.mean([np.abs(np.fft.rfft(z[i: i + n] * np.hanning(n))) ** 2 for i in range(0, len(z) - n + 1, n // 4)], axis=0)
    fq = np.fft.rfftfreq(n, 1 / rate)
    band = (fq >= lo) & (fq <= hi)
    return float(10 * np.log10(np.exp(np.mean(np.log(P[band] + 1e-20))) / (np.mean(P[band]) + 1e-20)))


def ours_flat(y):
    s = round(START * REF_RATE / RATE)
    return flat_band(resample(y, RATE, REF_RATE), s, s + round(LOOP * REF_RATE / RATE))


def fmt(m):
    voiced = m.get("voiced_share", 0) >= 0.3 and "pitch_dev_cents" in m
    pitch = (f"pitch dev {m['pitch_dev_cents']:.1f} c (voiced {m['voiced_share']:.2f}), drift {m.get('drift_cents_per_s', 0):+.1f} c/s"
             if voiced else f"pitch n/a (voiced {m.get('voiced_share', 0):.2f}: YIN finds no common period in the chord)")
    return (f"attack {m['attack10_ms']:.0f}/{m['attack3_ms']:.0f} ms, steady {m['steady_s']:.2f} s, {pitch}, "
            f"level {m.get('level_dev_db', 0):.1f} dB at {m.get('tremolo_hz', 0):.2f} Hz (prom {m.get('tremolo_prominence', 0):.1f}), "
            f"slope {m.get('level_slope_db_per_s', 0):+.2f} dB/s, bw40 {m['bw40_hz']:.0f} Hz, bw60 {m['bw60_hz']:.0f} Hz, "
            f"centroid {m['centroid_hz']:.0f} Hz (moving {m['centroid_move_hz']:.0f}), floor {m['floor_db']:.1f} dB, flatness "
            f"{m['flatness_db']:.1f} dB, partials {m.get('partials_db', [])[:10]}, inharmonic {m.get('inharmonic_cents') or 0:.1f} c, "
            f"off-harmonic peaks {m.get('off_harmonic_peaks')}, peak {m['peak_dbfs']:.1f} dBFS")


# ------------------------------------------------------------------------------------------------ the pattern

PATTERNS = ["loop", "loop_b"]
NOTES = {"loop": "A-3", "loop_b": "A-3"}                   # the note on row 0 of each pattern: held, as the reference's
SWELL = {"loop": (30, 40, 16), "loop_b": (40, 40, 0)}      # volume on the note row, volume reached, rows to reach it
PAN = 29
CHANNEL = f"    - {{name: Drone, pan: {PAN}, volume: 64}}\n"


# the form (the reference's orders 31-49): struck without G at v7 and swelled one step a row to v30 over 24 rows, nine
# patterns restated at a flat v30, the loop's alternation (swell, hold), then faded to silence by D02, D00
FORM = {"entry": (7, 30, 24), "flat": (30, 30, 0), "swell": SWELL["loop"], "hold": SWELL["loop_b"]}
FADE = ["D02"] + ["D00"] * 15


def form_column(kind, note=NOTES["loop"]):
    """Channel 22 in one pattern: FORM's volumes on the held note (the entry struck, the others legato), or the fade."""
    if kind == "fade":                                       # then a cut, silent by then (the app's SOUNDING table follows cuts)
        return [{**{r: f"... .. ... {fx}" for r, fx in enumerate(FADE)}, len(FADE): "^^^"}]
    v0, v1, rows = FORM[kind]
    col = {0: f"{note} 12 v{v0:02d}" + ("" if kind == "entry" else " GFF")}
    for r in range(1, rows + 1):                             # the swell in whole steps, rounded down, as the reference's
        col[r] = f"... .. v{v0 + (v1 - v0) * r // rows:02d}"
    return [col]


def figure():
    return {p: form_column(k, NOTES[p]) for p, k in (("loop", "swell"), ("loop_b", "hold"))}


def pattern(path=HERE / "rift.yaml", first_sample="drone_placeholder.wav"):
    b = path.read_bytes()
    crlf = b"\r\n" in b
    t = b.decode("utf-8").replace("\r\n", "\n")
    t = ensure_channels(t, CHANNEL, r"    - \{name: Str 6[^\n]*\n")   # the owner's lines stay
    if "\n  12: {file:" not in t:
        line = (f"  12: {{file: ../../samples/local/rift-cand/{first_sample}, base_note: {BASE_NOTE}, loop: from_wav, "
                f"name: {Path(first_sample).stem}}}\n")
        anchor = "\n\ninstruments:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + line + "\ninstruments:\n", 1)
    if "\n  12: {name: Drone" not in t:
        ins = "  12: {name: Drone, sample: 12}   # sample mode, as in the reference: the swells are in the pattern\n"
        anchor = "\n\npatterns:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + ins + "\npatterns:\n", 1)
    t = write_columns(t, 21, figure())
    if crlf:
        t = t.replace("\n", "\r\n")
    path.write_bytes(t.encode("utf-8"))
    print(f"wrote channel 22 into {path.name}: {NOTES} held by GFF, swells {SWELL}, pan {PAN}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["pattern"]:
        pattern(first_sample=next(iter(CANDS), "drone_placeholder") + ".wav")
    elif sys.argv[1:] == ["drone_obnoise"]:                          # the dropped sixth (see CANDS)
        make("drone_obnoise", "dx_obxd/drone_obnoise.wav", GAIN["drone_obnoise"])
    elif sys.argv[1:2] == ["ref"]:                                    # the calibration: the reference's own numbers
        x, rate = ref_wav()
        print("reference:", fmt(melodic.character(x, rate, ("fwd", 20000, 52410))) +
              f", flatness 50 Hz-2.2 kHz {flat_band(x, 20000, 52410, rate):.1f} dB")
    else:
        for cand, raw in CANDS.items():
            if not sys.argv[1:] or cand in sys.argv[1:]:
                make(cand, raw, GAIN.get(cand, 0.0))
