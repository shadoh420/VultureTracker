"""Rift, layer 8 of BRIEF.md's layer plan: the vocal pad, written the way Nether Animal writes its vocal pad (sample 27,
Creepyvocals; measured with scratch/ut99-clean/melodic.py, the articulation read from its cells without its notes with
scratch/ut99-clean/rifttools/artic.py 27; only the idioms and the sample character are taken).

`python suite/rift/gen_vocal.py` makes the slot-14 candidates from the screened raw takes (samples/local/rift-cand/vocal/
{surge,dx_obxd,models}/, each our chord A-3 E-4 C-5 as it sounds, mono, 44.1 kHz, onset at 0) the way the reference's
sample measures (melodic.character on its WAV with its loop at its 8363 Hz storage rate; `gen_vocal.py ref` prints those
figures; ours are read with the same function at the same rate, our 44.1 kHz files brought to it by an FFT resample that
keeps everything up to its Nyquist, as gen_noise.py's at_ref does):
  - the reference plays its sample 11 semitones over its stored rate (its 8 notes carry one written pitch; 3.22 s
    stored, 1.70 s as played), so ours is stored 11 semitones under our chord (the take slowed by 2**(11/12) through an
    FFT resample: its tones A#2 F-3 C#4 as stored, root A#2) and played at A-3, the same relation: every figure below is
    matched on the stored file and scales the same way into as played; the sub's side (under 104 Hz as played) is under
    55.1 Hz as stored;
  - tuned so the chord's root sits on equal temperament (its power-weighted centre within 40 cents), then by the root
    band's own period over the loop (loop_period: the lag near the loop's length, scanned a little past half a root
    period either way, whose correlation of the root band across the loop is best), so the loop holds whole cycles of
    what the root band plays (a root whose partials beat or whose centre reading sits off its strongest component would
    run the blend's two parts out of phase and cancel the root band there); the other tones keep the take's own tuning
    against the root; nothing under 20 Hz (a 20-45 Hz ramp as stored); after the tuning and the wobble, nothing over the
    reference's storage Nyquist (a 1023-tap low-pass at 4061.5 Hz: -6 dB there, -73 dB from 4181.5 Hz as stored, 7.9 kHz
    as played);
  - 3.22 s as stored with a forward loop to the end from 1.043 s (the reference's), here 127 whole cycles of the stored
    root (2.180 s; the reference's loop is 2.175 s; of 125-129 cycles 127 leaves the tenth nearest whole cycles, 0.06,
    and the fifth and the tenth together nearest, 0.34 cycles off); the loop held flat band by band (loopify: the level
    slope over the loop taken out of each of four bands, under 70, 70-300, 300-700 and 700 Hz and up as stored, around
    the loop's middle, so the loop keeps its mean timbre: a take's own spectral sweep would otherwise restart at every
    wrap; the reference's loop rises 0.56 dB a second and steps down 1.2 dB at every wrap: not followed); each band's
    last 0.4 s of the loop blended into what precedes the loop start, that part first brought to the band's level at the
    loop's end by a gain that reaches 1 at the loop start (so the blend meets the loop start exactly and imports no
    level step), with gains set by how alike the two are;
  - a slow pitch wobble where the take moves less: the reference's root moves 30 c peak to peak, periodic, at 3.5 Hz as
    played (tonevib.py at its own tones over its loop played twice, share 0.44; its E 31 c at 2.5 Hz, its C 16 c at 5.2
    Hz; over the loop once its root reads 32 c at 3.6 Hz, share 0.56, its E and C 25 and 5 c; its E reads 25-48 c over
    one to three passes, its root 30-32); ours, one time map for the whole chord (all three tones move alike), periodic
    with the loop on its line nearest the reference's root line, read on the take itself over 3 s as played from the
    loop start (a tiled loop makes its own loop-periodic breath jitter read as periodic pitch movement: the finished
    loop's reading is printed as information): the smallest depth on a 2 c grid whose root reads the reference's root,
    only where the take's own reads less, no deeper than keeps each other tone at or under the larger of the reference's
    root reading and its own plus 2 c, nor than lets the floor reading pass the larger of the reference's and the take's
    own plus 0.5 dB (a wobble smears the partials and lifts the floor), none where no depth moves the root more than its
    own;
  - a floor of -7.88 dB between the partials (the reference's: breath, not a clean tone): noise shaped like the take's
    own spectrum (third-octave smoothed, so it follows the take's formants, not its partials), periodic with the loop,
    nothing under 57.2 Hz as stored (108 Hz as played) in the loop or before it, added only where the take is purer;
    before the loop it follows the take's level (30 ms) and meets the loop's noise exactly at the loop start;
  - slow movement band by band where the take moves less: over the loop, 10 ms band levels (100-300, 300-700 and
    700-2200 Hz as stored, as the drone's reading) detrended and kept at 0.6-8 Hz move 1.71/1.97/1.10 dB in the
    reference (REF['bands']; their slow parts centred at 2.8/3.3/4.0 Hz as stored by power over log rate, spread
    0.9/1.0/0.7 octave, REF['rates']; beside them a fast flicker from its breath holds most of its level movement, above
    8 Hz); three draws on the loop's lines, each line's power the reference band's own there (REF['specs']: a bump at
    the centre and spread would read faster, as the linear lines weight the top of a log bump), uncorrelated with each
    other and with each band's own movement, each band topped up over its own movement, then all depths scaled down
    together while melodic's whole level movement over the loop would pass the larger of the reference's 1.83 dB and the
    take's own, plus 0.1 (gen_noise .py's bound), read again on the finished file; only above 70 Hz as stored (132 Hz as
    played): the root's fundamental, and so the sub's side, is not moved (a wander's sidebands reach 8 Hz as stored, 15
    Hz as played); the draw whose readings come nearest the reference's (melodic's level movement and tremolo once and
    twice, the band correlations) of DRAWS, and whose loop peak, read after the roll-off, passes the -1 dBFS limit at
    the candidate's gain least (10 per dB in the score; gen_drone.py's rule);
  - the reference's swell, read on melodic.py's 10 ms blocks against the file's top (inside the loop in every phase: the
    reference's peak never falls before its loop) over all 83 block phases: its means 149.5 ms to -10 dB and 827.9 ms to
    -3 dB (phase 0: 129 / 675), its level over 0-0.3, 0.3-0.675 and 0.675-1.043 s -6.78 / -2.67 / -0.92 dB against the
    loop; ours a smooth gain curve over the take's own level through five knots (0 s, two on the rise, a crest before
    the loop as the reference's near 0.675 s, the loop start; times and levels scanned): the attack means matched, the
    span levels as near as the knot search finds (the last span as near as the -3 dB reading against the file's top
    allows: a loop whose 10 ms top sits higher over its RMS than the reference's 4.6 dB needs a higher level before the
    loop to reach it; printed), nothing before the loop over 0.3 dB under the lowest of the loop's per-phase tops (so
    the file's peak lies in the loop in every phase, as the reference's);
  - a smooth roll-off (flat to a corner, then a straight line in dB per octave, zero phase, attenuation only), solved on
    the loop before the swell (which leaves the loop alone), so the swell is read on the file as it will be written: its
    corner and slope bring melodic's -40 and -60 dB bandwidths nearest the reference's 2234 and 4177 Hz as stored
    (gen_noise.py's method) while melodic's centroid moves no more than 5 % from the take's own (a stronger roll-off
    would darken the take's colour toward the reference's spectrum); then the whole level movement read on the finished
    file, the band depths solved again while it passes the bound;
  - every filter after the loop is formed (the band split, the roll-off) runs on the sample as it plays: circular inside
    the loop, so every wrap stays as seamless as the blended take's; the part before the loop filtered with the loop
    running on after it, so the first pass steps into the loop once (printed);
  - a gain per candidate for the level 11.9 dB under the sub (the layer plan's figure, active level); the -1 dBFS peak
    limit.
  Stored at 44.1 kHz, root A#2 (played at A-3). Partials, formants, noise colour and each take's own movement stay its own:
  matching those would rebuild the reference's sample.
`python suite/rift/gen_vocal.py pattern` writes the vocal pad into rift.yaml (channel 24, slot 14 at base_note A#2,
instrument 14):
  - Nether's idiom from its cells (counts only): one breathy chord sample, one written pitch for all 8 notes, struck on
    row 0 at v5 (no legato) and swelled one step a row to v23 over 16 rows (v13 and v22 skipped: 18 steps in 16 rows),
    then restated by a legato note (GFF) at v23 on row 0 of each following pattern (three, then struck again); pan 32
    (centre) on every note; a D01 then D00 fade to silence where it ends (form work). The 8-bar loop takes a strike and
    a hold: loop swells, loop_b holds (the loop's wrap is the reference's hold -> re-strike step, its orders 44 -> 45).
  - Our chord: A minor, voiced A-3 E-4 C-5 (sounding) inside the sample, its lowest tone on our drone's lowest (the
    reference's vocal sits on its drone's lowest tone as played), written A-3.
    scratch/ut99-clean/rifttools/vocalcheck.py compares it with the reference's in sounding pitch and prints counts
    only.
Channels 1-23 keep their cells; an existing Vocal channel line stays as it is (its volume is the owner's mix).
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
sys.path.insert(0, str(ROOT / "scratch" / "ut99-clean" / "rifttools"))
from vulturetracker.resample import fir_filter, lowpass_fir, resample  # noqa: E402
from vulturetracker.wavload import read_wav, write_wav  # noqa: E402
from gen_floor import envelope_spectrum, shaped_noise  # noqa: E402
from gen_seq import ensure_channels, write_columns  # noqa: E402
import melodic  # noqa: E402  (local only: character() printed the reference's numbers; ours are read with it)
import tonevib  # noqa: E402  (per-tone pitch movement)
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("vocal_measure", ROOT / "samples/local/rift-cand/vocal/measure.py")
vm = importlib.util.module_from_spec(_spec)  # the screens' class measures (by path: suite/nadir has a measure.py too)
_spec.loader.exec_module(vm)

OUT = ROOT / "samples" / "local" / "rift-cand"
RAW = OUT / "vocal"
RATE, REF_RATE = 44100, 8363                               # ours; the reference's storage rate (its measures' scale)
PLAYED = 11                                                # semitones over the stored rate as played (the reference's)
UP = 2 ** (PLAYED / 12)                                    # as stored -> as played (frequencies)
BASE_NOTE, ROOT_NOTE = "A#2", 34                           # stored root (the tracker's C-5 is 60): A-3 played 11 under
VOICING = ["A-3", "E-4", "C-5"]                            # the chord inside the sample, sounding
SOUNDING = [45, 52, 60]                                    # its tones as played (MIDI numbers, A-3 = 45 = 110 Hz)
STORED = [t - PLAYED for t in SOUNDING]                    # as stored: A#2 F-3 C#4
F_ROOT = 440 * 2 ** ((ROOT_NOTE - 69) / 12)                # 58.27 Hz as stored
REF_LOOP = (8724, 26916)                                   # the reference's loop (stored frames at 8363 Hz): to its end
START = round(REF_LOOP[0] / REF_RATE * RATE)               # 1.043 s as stored
CYCLES = 127
LOOP = round(CYCLES * RATE / F_ROOT)                       # 2.180 s as stored (the reference's 2.175 s)
END = START + LOOP
XFADE = round(0.4 * RATE)
TOP = REF_RATE / 2                                         # 4181.5 Hz: the reference's storage holds nothing above it
BAND_TOP = TOP - 120.0                                     # the band limit's cutoff: its 1023-tap FIR reaches -73 dB by TOP
LOW_CUT = (104.0 + 4.0) / UP                               # 57.2 Hz as stored: no added noise under 108 Hz as played
MOVE_SPLIT = 70.0                                          # Hz as stored (132 as played): nothing under it is moved
SPLIT_HZ = (300.0, 700.0)                                  # the wander's bands (stored): MOVE_SPLIT-300, 300-700, 700-
READ_BANDS = ((100.0, 300.0), (300.0, 700.0), (700.0, 2200.0))   # the band movement's reading (as the drone's)
MOVE_BAND = (0.6, 8.0)                                     # Hz as stored: the slow movement's rates (read and drawn)
WOBBLE_HZ = None                                           # set by reference_figures(): the reference's root line, as stored
WOBBLE_TOL = 2.0                                           # c: the other tones' cap over the reference's root reading
WOBBLE_READ = 3.0                                          # s as played: the take's own pitch movement read over it
FLOOR_DB = -7.88
BW40, BW60 = 2233.7, 4177.4                                # the reference's -40 / -60 dB bandwidths (melodic, as stored)
HB = int(REF_RATE * 0.01)                                  # melodic's 10 ms block at the reference's rate: 83 samples
SPANS = ((0.0, 0.3), (0.3, 0.675), (0.675, REF_LOOP[0] / REF_RATE))   # the swell's level spans (s as stored)
RMS_DB = -18.0                                             # the loop's level before the per-candidate gain
CENTROID_KEEP = 0.05                                       # the roll-off moves melodic's centroid at most 5 % (under a semitone)
DRAWS = 16
REF = None                                                 # set by reference_figures()

# candidate -> raw take (relative to RAW): five of sixteen finalists of three screens (1715 measured Surge takes, 1746
# renders, of 1204 patches; 2334 Dexed/OB-Xd takes of 781 voices and programs; 943 takes of our own source-filter voice
# models: the local and upstream CC0 libraries hold no voice recordings), measured by vocal/measure.py (the reference's
# character figures as stored at its rate, the chord, pitch, hold and envelope figures as played; at least 6.1 dB from
# drone_ahhs by the timbre envelope and 3.7 dB under 1 kHz, its vowel: pitchwhisper and schwabreath fail that), screened
# by scalar class figures, never spectral likeness; the five farthest apart, at most one per kind (vocal/finalists.py
# and finalists.txt: the largest smallest pairwise distance over the figures this generator keeps and the timbre
# envelopes, 1.98 median distances; three sets tie, the fifth member by the lower pref sum). Recipes and screen.txt in
# vocal/{surge,dx_obxd,models}.
CANDS = {
    "vocal_obghost": "dx_obxd/vocal_obghost.wav",           # OB-Xd "Ghost Hunter": one saw+pulse oscillator, a 16 Hz sine+S&H
                                                            # pulse-width LFO (most of its floor: -8.1 dB with its noise off)
                                                            # and its mixer noise (osc2 off, pitch LFO off)
    "vocal_breathhum": "models/vocal_breathhum.wav",        # our model: a breathy nasal hum ("mm"), Rosenberg voices with
                                                            # aspiration 8 dB under and a nasal zero
    "vocal_oowhisper": "models/vocal_oowhisper.wav",        # our model: a whisper over a weak voice (KLGLOTT88, open quotient
                                                            # 0.85), its aspiration as loud as the voice, high-passed at 800 Hz
    "vocal_andespipe": "surge/vocal_andespipe.wav",         # Surge Dan Maurer "Andes Pipes": the noise generator into notch and
                                                            # comb filters beside a wavetable (a blown pipe)
    "vocal_bethbreath": "surge/vocal_bethbreath.wav",       # Surge Vincent Zauhar "Beth's Breath": wavetable and sine layers over
                                                            # the patch's own noise generators (its fifth-up wavetable muted)
}
# per candidate, dB so the vocal pad sits 11.9 dB under the sub in the song (active level, channels 4 and 24 soloed: 17.2
# dB under at 0 for all five, the loops sharing one RMS); a candidate whose peak meets the -1 dBFS limit sits where the
# limit holds it
GAIN = {"vocal_obghost": 5.3, "vocal_breathhum": 5.3, "vocal_oowhisper": 5.3, "vocal_andespipe": 5.3, "vocal_bethbreath": 5.3}


def mono(path):
    w = read_wav(path)
    return np.asarray(w.channels, float).mean(axis=0) / 2 ** (w.bits - 1), w.rate


def ref_wav():
    return mono(next((ROOT / "scratch/ut99/nether/nether_samples").glob("27_*.wav")))


fft_resample = vm.fft_resample                             # zero-padded FFT resample: everything up to the lower Nyquist


def at_ref(y):
    """`y` (44.1 kHz, as stored) at the reference's rate by FFT: everything up to its Nyquist kept."""
    return fft_resample(y, int(round(len(y) * REF_RATE / RATE)))


def played(y):
    """`y` (44.1 kHz, as stored) as it sounds, played 11 semitones up (44.1 kHz)."""
    return fft_resample(y, int(round(len(y) / UP)))


def ref_frames():
    return round(START * REF_RATE / RATE), round(END * REF_RATE / RATE)


def measure(y):
    """melodic.character of `y` (44.1 kHz, as stored, our loop) at the reference's storage rate."""
    return melodic.character(at_ref(y), REF_RATE, ("fwd",) + ref_frames())


def twice(y):
    """melodic.character's movement reading of our loop played twice (at the reference's rate)."""
    s, e = ref_frames()
    lz = at_ref(y[:END])[s:e]
    return melodic.character(np.tile(lz, 2), REF_RATE, ("fwd", 0, 2 * len(lz)))


def zpad_filter(x, gain_fn):
    """Zero-phase filter of `x` by the gain function of frequency (zero-padded: no wrap)."""
    n = 1 << int(math.ceil(math.log2(len(x) + RATE)))
    X = np.fft.rfft(x, n)
    return np.fft.irfft(X * gain_fn(np.fft.rfftfreq(n, 1 / RATE)), n)[: len(x)]


def loop_filter(y, gain_fn):
    """Zero-phase filter of the looped file `y` (END frames) as it plays: the loop filtered as one period (circularly, so
    every wrap stays as seamless as it was), the part before it filtered with the loop running on after it (the file, then
    the loop twice, zero-padded beyond)."""
    loop = y[START:END]
    lf = np.fft.irfft(np.fft.rfft(loop) * gain_fn(np.fft.rfftfreq(LOOP, 1 / RATE)), LOOP)
    pre = zpad_filter(np.concatenate([y[:END], loop, loop]), gain_fn)[:START]
    return np.concatenate([pre, lf])


def loop_fir(y, h):
    """The linear-phase FIR `h` over the looped file `y` as it plays (circular inside the loop, as loop_filter)."""
    loop = y[START:END]
    hc = np.zeros(LOOP)
    c = (len(h) - 1) // 2
    hc[np.arange(len(h)) - c] = h                                 # centred on frame 0 of the period
    lf = np.fft.irfft(np.fft.rfft(loop) * np.fft.rfft(hc), LOOP)
    pre = fir_filter(np.concatenate([y[:END], loop, loop]), h)[:START]
    return np.concatenate([pre, lf])


def entry_pct(y):
    """The first pass's step into the loop (the frame at the loop start against the straight line from the two before it),
    in % of the loop's RMS: filtered as it plays, the loop meets the part before it once, not at every wrap."""
    rms = np.sqrt(np.mean(y[START:END] ** 2)) + 1e-12
    return 100 * abs(y[START] - (2 * y[START - 1] - y[START - 2])) / rms


def highpass(x, lo=20.0, hi=45.0):
    """Nothing under 20 Hz, all of it over 45 Hz as stored (a raised-cosine ramp between, zero phase, zero-padded)."""
    return zpad_filter(x, lambda f: 0.5 - 0.5 * np.cos(np.pi * np.clip((f - lo) / (hi - lo), 0, 1)))


def lowpart(x, fc):
    """`x` under `fc` (linear phase, 16383 taps: flat to about fc - 7 Hz); x - lowpart(x) is the rest, exactly."""
    return fir_filter(x, lowpass_fir(fc / RATE, taps=16383))


def tone_centre(seg, t):
    """Power-weighted centre (cents from equal temperament) of the spectrum within 40 cents of MIDI note `t`, and the
    strongest peak there."""
    n = 1 << 20
    P = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n)) ** 2
    f = np.fft.rfftfreq(n, 1 / RATE)
    ft = 440 * 2 ** ((t - 69) / 12)
    sel = (f > ft * 2 ** (-40 / 1200)) & (f < ft * 2 ** (40 / 1200))
    c = 1200 * np.log2(f[sel] / ft)
    return float(np.sum(c * P[sel]) / np.sum(P[sel])), float(c[np.argmax(P[sel])])


def chord_cents(x):
    """Each stored chord tone's centre over the loop (cents from equal temperament)."""
    return [tone_centre(x[START:END], t)[0] for t in STORED]


def env_db(y, win=0.01):
    h = int(RATE * win)
    return 20 * np.log10(np.sqrt(np.convolve(y * y, np.ones(h) / h, mode="same")) + 1e-9)


# ------------------------------------------------------------------------------------------------ readings

def band_moves(y):
    """The loop's slow movement band by band (READ_BANDS as stored, FFT masks on the periodic loop): each band's 10 ms
    envelope (dB, at the reference's rate) detrended and kept at MOVE_BAND, its spread and the three pair correlations;
    `y` is the stored file at 44.1 kHz, or the reference's loop at its own rate when passed as (loop, rate)."""
    seg, rate = (y if isinstance(y, tuple) else (at_ref(y[:END])[ref_frames()[0]: ref_frames()[1]], REF_RATE))
    X = np.fft.rfft(seg)
    f = np.fft.rfftfreq(len(seg), 1 / rate)
    envs = []
    for lo, hi in READ_BANDS:
        e, h = melodic.envelope_db(np.fft.irfft(np.where((f >= lo) & (f < hi), X, 0), len(seg)), rate)
        tt = np.arange(len(e)) * h / rate
        e = e - np.polyval(np.polyfit(tt, e, 1), tt)
        E = np.fft.rfft(e)
        fr = np.fft.rfftfreq(len(e), h / rate)
        E[(fr < MOVE_BAND[0]) | (fr > MOVE_BAND[1])] = 0
        envs.append(np.fft.irfft(E, len(e)))
    return ([float(np.std(v)) for v in envs],
            [float(np.corrcoef(envs[i], envs[j])[0, 1]) for i, j in ((0, 1), (0, 2), (1, 2))], envs)


def slow_dev(seg, rate=REF_RATE):
    """The part of a loop's level movement at MOVE_BAND: melodic.py's detrended 10 ms envelope (frames within 40 dB of
    the loudest) kept at those rates, its spread in dB."""
    se, sh = melodic.envelope_db(seg, rate)
    live = se > se.max() - 40
    tt = np.arange(len(se))[live] * sh / rate
    det = se[live] - np.polyval(np.polyfit(tt, se[live], 1), tt)
    F = np.fft.rfft(det)
    fr = np.fft.rfftfreq(len(det), sh / rate)
    F[(fr < MOVE_BAND[0]) | (fr > MOVE_BAND[1])] = 0
    return float(np.std(np.fft.irfft(F, len(det))))


def our_loop(y):
    s, e = ref_frames()
    return at_ref(y[:END])[s:e]


def loop_period(x):
    """The root band's (under MOVE_SPLIT as stored) own period over the loop: the lag near LOOP (scanned a little
    past half a root period either way, so every peak is interior) at which its last 0.4 s before the loop start
    correlates best with the same span a loop later (parabolic peak); returns (the cents that make LOOP whole cycles
    of it, that correlation, the cycles it was off). A root whose partials beat or whose centre reading sits off its
    strongest component would otherwise leave the blend's two parts out of phase (bethbreath's sat half a cycle off:
    the blend cancelled its root band)."""
    lo = lowpart(x, MOVE_SPLIT)
    a = lo[START - XFADE:START]
    half = int(RATE / F_ROOT / 2) + 8                                     # past half a period: a peak there is interior
    ds = np.arange(-half, half + 1)
    cs = []
    for d in ds:
        b = lo[START - XFADE + LOOP + d: START + LOOP + d]
        cs.append(float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)))
    cs = np.array(cs)
    peaks = [k for k in range(1, len(cs) - 1) if cs[k] >= cs[k - 1] and cs[k] >= cs[k + 1]]
    k = max(peaks, key=lambda k: cs[k])                                   # the best correlation among the peaks
    den = cs[k - 1] - 2 * cs[k] + cs[k + 1]
    d = ds[k] + (0.5 * (cs[k - 1] - cs[k + 1]) / den if den else 0.0)
    return 1200 * math.log2((LOOP + d) / LOOP), float(cs[k]), float(d / (RATE / F_ROOT))


def take_wobble(x):
    """tonevib's reading of the chord's tones on the take itself (as stored, not looped): WOBBLE_READ s as played from the
    loop start, played 11 up (a tiled loop makes its own loop-periodic breath jitter read as periodic pitch movement)."""
    seg = played(x[START: START + int(round(WOBBLE_READ * UP * RATE))])
    return tonevib.moves(seg, RATE, fs=[440 * 2 ** ((t_ - 69) / 12) for t_ in SOUNDING])


def root_wobble(y):
    """tonevib's reading of the chord's tones over the loop as played (the stored loop played 11 up): per tone (depth,
    line, periodic part, share, ac)."""
    seg = played(np.tile(y[START:END], 2))                    # the loop played twice: its wrap inside the read
    return tonevib.moves(seg, RATE, fs=[440 * 2 ** ((t - 69) / 12) for t in SOUNDING])


def phase_stats(z, s0):
    """Over the 83 block phases of `z` (at the reference's rate, loop from frame s0): the attack readings against the
    file's top (ms), the share of phases whose file peak lies before the loop, and the span levels (dB against the loop)."""
    r_, before = [], 0
    for p in range(HB):
        env, h = melodic.envelope_db(np.concatenate([np.zeros(p), z]), REF_RATE)
        sb = (s0 + p) // h
        ft, lt = env.max(), env[sb + 1:].max()
        before += env[:sb].max() > lt
        r_.append(((np.nonzero(env >= ft - 10)[0][0] * h - p), (np.nonzero(env >= ft - 3)[0][0] * h - p)))
    lp = 10 * np.log10(np.mean(z[s0:] ** 2) + 1e-30)
    spans = [10 * np.log10(np.mean(z[int(a * REF_RATE): int(b * REF_RATE)] ** 2) + 1e-30) - lp for a, b in SPANS]
    return np.array(r_) * 1000 / REF_RATE, before / HB, spans


def reference_figures():
    """The reference's own figures (its WAV at its storage rate, its loop), into REF."""
    global REF
    x, r = ref_wav()
    s, e = REF_LOOP
    c = melodic.character(x, r, ("fwd", s, e))
    ph, share, spans = phase_stats(x, s)
    lp = x[s:e]
    bsp, bcc, _ = band_moves((lp, r))
    tw = melodic.character(np.tile(lp, 2), r, ("fwd", 0, 2 * len(lp)))
    y = fft_resample(np.tile(lp, 2), int(round(2 * len(lp) * RATE / (r * UP))))   # its loop twice, as played, 44.1 kHz
    import dronecheck
    tt = dronecheck.tones(y[: len(y) // 2], RATE, lo=60.0, hi=700.0, rel_db=9.0)
    wob = tonevib.moves(y, RATE, fs=[440 * 2 ** ((v - 69) / 12) for v in sorted(tt)])
    renv = band_moves((lp, r))[2]
    rates = rate_reading(renv)                                     # each band's slow movement: its rate centre and spread
    specs = []                                                     # and its own per-line power (the draws' templates)
    for e_ in renv:
        P = np.abs(np.fft.rfft(e_)) ** 2
        fr = np.fft.rfftfreq(len(e_), int(r * 0.01) / r)           # (melodic's 10 ms blocks at the reference's rate)
        specs.append((fr, P))                                      # (a smoothing spills power out of MOVE_BAND)
    REF = dict(c=c, attack=ph.mean(axis=0), attack_rng=(ph.min(axis=0), ph.max(axis=0)), before=share, spans=spans,
               bands=bsp, cc=bcc, slow=slow_dev(lp, r), twice=tw, wobble=wob, rates=rates, specs=specs,
               top=loop_top(lp, r))
    global WOBBLE_HZ
    WOBBLE_HZ = wob[0][1] / UP                                     # the root's line, as stored
    return REF


# ------------------------------------------------------------------------------------------------ the steps

def warp(x, cents):
    """`x` (as stored) through one time map whose rate is 2**(cents/1200) (cents per frame, periodic with the loop, mean
    rate over a loop 1, so the loop's length and whole cycles hold): cubic (Catmull-Rom) interpolation, fine for content
    under 4.2 kHz at 44.1 kHz."""
    r = 2 ** (cents / 1200)
    r = r / r[START:END].mean()                                   # the second-order rate bias out: a loop is LOOP frames
    tau = np.concatenate([[0.0], np.cumsum(r[:-1])])
    i = np.clip(np.floor(tau).astype(int), 0, len(x) - 1)   # (past the end: the file is cut at the loop's end anyway)
    u = np.clip(tau - i, 0.0, 1.0)
    xp = np.pad(x, (1, 3))
    p0, p1, p2, p3 = xp[i], xp[i + 1], xp[i + 2], xp[i + 3]
    return p1 + 0.5 * u * (p2 - p0 + u * (2 * p0 - 5 * p1 + 4 * p2 - p3 + u * (3 * (p1 - p2) + p3 - p0)))


def wobble_curve(n, seed):
    """A slow pitch movement (cents, unit peak to peak before scaling), periodic with the loop and aligned to its
    start: one sine on the loop's line nearest the reference's root line (as stored; its root's movement is periodic
    there), a random phase, rate mean over a loop exactly 1 through warp() (its mean in cents taken out here, warp()
    divides the rate by its loop mean)."""
    f_ = round(WOBBLE_HZ * LOOP / RATE) * RATE / LOOP              # the loop's line nearest the reference's root line
    rng = np.random.default_rng(seed)
    t = (np.arange(n) - START) % LOOP / RATE
    c = np.cos(2 * np.pi * f_ * t + 2 * np.pi * rng.random())
    c /= (c[START:END].max() - c[START:END].min()) + 1e-12
    return c - c[START:END].mean()


def loopify(x):
    """The loop formed from `x` (as stored, longer than END), band by band (under MOVE_SPLIT, MOVE_SPLIT-300, 300-700,
    700 Hz and up as stored; complementary linear-phase FIRs on the whole take, which runs past the loop's end): each band's
    slope in dB over the loop taken out around the loop's middle (the loop keeps its mean timbre; before the loop the gain
    at the loop start is held, so nothing steps there); then each band's last 0.4 s of the loop blended into what precedes
    the loop start, that part first brought to the band's level at the loop's end by a gain that reaches 1 at the loop
    start (so the blend meets the loop start exactly and imports no level step), with gains set by how alike the two are.
    Returns (the file's END frames, notes)."""
    lows = [fir_filter(x, lowpass_fir(c / RATE, taps=16383)) for c in (MOVE_SPLIT,) + SPLIT_HZ]
    parts = [lows[0], lows[1] - lows[0], lows[2] - lows[1], x - lows[2]]
    tt = np.arange(END) - START - LOOP / 2                         # frames from the loop's middle
    rr = np.linspace(0, 1, XFADE)
    y = np.zeros(END)
    slopes, g0s, rhos, pre = [], [], [], []
    for p_ in parts:
        e = env_db(p_[START:END])[::441]
        s = np.polyfit(np.arange(len(e)) * 441, e, 1)[0]
        slopes.append(s * RATE)
        q = p_[:END] * 10 ** (-s * np.maximum(tt, -LOOP / 2) / 20)  # flat around the loop's middle; before the loop the
        a, b = q[END - XFADE:END].copy(), q[START - XFADE:START].copy()   # loop start's gain held, so nothing steps
        g0 = float(np.sqrt(np.mean(a ** 2)) / (np.sqrt(np.mean(b ** 2)) + 1e-12))
        b *= g0 * (1 - rr) + rr
        rho = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
        q[END - XFADE:END] = (a * (1 - rr) + b * rr) / np.sqrt((1 - rr) ** 2 + rr ** 2 + 2 * max(rho, -0.5) * rr * (1 - rr))
        g0s.append(20 * np.log10(g0))
        pre.append(s * LOOP / 2)                                    # dB: the loop start's gain, held before the loop
        rhos.append(rho)
        y += q
    return y, [f"loop slopes by band {'/'.join(f'{v:+.1f}' for v in slopes)} dB/s flattened around the loop's middle "
               f"(before the loop the bands held {'/'.join(f'{v:+.1f}' for v in pre)} dB)",
               f"blend by band: the part before the loop brought {'/'.join(f'{v:+.1f}' for v in g0s)} dB to the loop "
               f"end's level, correlations {'/'.join(f'{v:+.2f}' for v in rhos)}"]


def loop_top(y, rate=RATE):
    """The loop's highest 10 ms block (melodic's blocks at the reference's rate, over all 83 phases) over its RMS, dB."""
    z = at_ref(y[:END])[ref_frames()[0]: ref_frames()[1]] if rate == RATE else y
    rms = 10 * np.log10(np.mean(z ** 2) + 1e-30)
    return max(melodic.envelope_db(z[p:], REF_RATE)[0].max() for p in range(HB)) - rms


def rate_reading(envs, dt=int(REF_RATE * 0.01) / REF_RATE):
    """Each band's slow movement (band_moves' envelopes) as (power-weighted centre over log rate, its spread in octaves),
    over MOVE_BAND."""
    out = []
    for e_ in envs:
        P = np.abs(np.fft.rfft(e_)) ** 2
        fr = np.fft.rfftfreq(len(e_), dt)
        sel = (fr >= MOVE_BAND[0]) & (fr <= MOVE_BAND[1])
        lf = np.log2(fr[sel])
        mu = float(np.sum(lf * P[sel]) / np.sum(P[sel]))
        out.append((2 ** mu, float(np.sqrt(np.sum((lf - mu) ** 2 * P[sel]) / np.sum(P[sel])))))
    return out


def band_wrap(y):
    """Each of the four bands' step across the loop's wrap: its 20 ms level just after the wrap against just before (the
    loop played twice, band-split as it plays), beside the 95th percentile of its own 20 ms steps inside the loop, taken at
    every 1 ms (dB). The added movement is periodic with the loop, so it adds no step there; a cancelling blend, which dips
    inside the blend region and meets the loop start exactly, shows in blend_range, not here."""
    lows = [loop_fir(y, lowpass_fir(c / RATE, taps=16383)) for c in (MOVE_SPLIT,) + SPLIT_HZ]
    h = int(0.02 * RATE)
    out = []
    for p_ in (lows[0], lows[1] - lows[0], lows[2] - lows[1], y[:END] - lows[2]):
        lp = p_[START:END]
        two = np.concatenate([lp, lp])
        before = 10 * np.log10(np.mean(two[LOOP - h:LOOP] ** 2) + 1e-30)
        after = 10 * np.log10(np.mean(two[LOOP:LOOP + h] ** 2) + 1e-30)
        c2 = np.concatenate([[0.0], np.cumsum(two ** 2)])             # the band's own 20 ms steps at every 1 ms inside
        offs = np.arange(h, LOOP - h + 1, 44)                          # the loop (sliding, not on a block grid)
        st = 10 * np.log10((c2[offs + h] - c2[offs] + 1e-30) / (c2[offs] - c2[offs - h] + 1e-30))
        out.append((after - before, float(np.percentile(np.abs(st), 95))))
    return out


def blend_range(y):
    """Each band's lowest and highest 20 ms level inside the blend region (the loop's last 0.4 s) and elsewhere in the loop
    (dB against the band's loop RMS): a cancelling blend shows as a low minimum there."""
    lows = [loop_fir(y, lowpass_fir(c / RATE, taps=16383)) for c in (MOVE_SPLIT,) + SPLIT_HZ]
    h = int(0.02 * RATE)
    out = []
    for p_ in (lows[0], lows[1] - lows[0], lows[2] - lows[1], y[:END] - lows[2]):
        lp = p_[START:END]
        n = LOOP // h
        tail = lp[LOOP - n * h:]                                       # blocks ending at the loop end: the last XFADE // h
        lv = 10 * np.log10(np.mean(tail.reshape(n, h) ** 2, axis=1) + 1e-30) - 10 * np.log10(np.mean(lp ** 2) + 1e-30)
        nb = XFADE // h                                                # of them are the blend region
        out.append((float(lv[-nb:].min()), float(lv[-nb:].max()), float(lv[:-nb].min()), float(lv[:-nb].max())))
    return out


def band_slopes(y):
    """Each of the four bands' level slope over the loop (dB/s) and its last 0.2 s against its first (dB): what a pass of
    the loop does to the timbre before it wraps."""
    lows = [loop_fir(y, lowpass_fir(c / RATE, taps=16383)) for c in (MOVE_SPLIT,) + SPLIT_HZ]
    out = []
    for p_ in (lows[0], lows[1] - lows[0], lows[2] - lows[1], y[:END] - lows[2]):
        e = env_db(p_[START:END])[::441]
        k = len(e) // 11
        out.append((np.polyfit(np.arange(len(e)) * 441 / RATE, e, 1)[0], float(np.mean(e[-k:]) - np.mean(e[:k]))))
    return out


def add_wobble(x, seed):
    """Where the take's root moves less than the reference's (periodic part, as played, read on the take itself over
    WOBBLE_READ s from the loop start: take_wobble): the smallest depth on a 2 c grid whose root reads the reference's root
    (else the one nearest it), no deeper than keeps each other tone at or under the larger of the reference's root reading
    and its own plus WOBBLE_TOL (the root's is the reference's stable reading: its E reads 25-48 c over one to three passes),
    nor than lets the floor reading pass the larger of the reference's and the take's own plus 0.5 dB (a wobble smears the
    partials and lifts the floor); none where no depth moves the root more than its own. Returns (x, depth c or None, info:
    own and chosen readings and floors)."""
    def read(z):
        return take_wobble(z), melodic.floor_db(our_loop(z), REF_RATE)
    own, own_floor = read(x)
    want = REF["wobble"][0][2]                                    # the reference's root: its periodic part (c p-p)
    info = dict(own=own, own_floor=own_floor, floor=own_floor, fin=own, why="its own root moves as much")
    if own[0][2] >= want - 1.0:
        return x, None, info
    cap = [max(want, o[2]) + WOBBLE_TOL for o in own]
    floor_cap = max(FLOOR_DB, own_floor) + 0.5
    base = wobble_curve(len(x), seed)
    best = None                                                   # (root reading, depth, readings, floor) within the caps
    n_tone = n_floor = 0
    for d in np.arange(2.0, 3.0 * want + 0.1, 2.0):               # a grid: the periodic part is not monotonic in the depth
        got, fl = read(warp(x, d * base))
        tone_ok, floor_ok = all(g[2] <= c for g, c in zip(got[1:], cap[1:])), fl <= floor_cap
        n_tone += not tone_ok
        n_floor += not floor_ok
        if not (tone_ok and floor_ok):
            continue
        if got[0][2] >= want:                                     # the smallest depth that reaches the reference's root
            best = (got[0][2], d, got, fl)
            break
        if best is None or got[0][2] > best[0]:
            best = (got[0][2], d, got, fl)
    if best is None or best[0] < own[0][2] + 1.0:                 # nothing within the caps moves the root more than its own
        info["why"] = (f"{'every depth' if best is None else 'no depth within the caps moves the root more than its own;'} "
                       f"of the grid {n_tone} past a tone cap, {n_floor} past the floor cap")
        return x, None, info
    info.update(floor=best[3], fin=best[2])
    return warp(x, best[1] * base), float(best[1]), info


def wander(n, seed, band):
    """A slow level movement periodic with the loop and aligned to its start, unit spread, `n` frames: random phases
    and Rayleigh amplitudes on the loop's whole-cycle lines, each line's mean power the reference band's own there
    (its per-line power over its loop; the two loops' lines lie 0.3 % apart), MOVE_BAND, at a 100 Hz control rate."""
    m = round(LOOP / RATE * 100)
    fr = np.arange(m // 2 + 1) * RATE / LOOP
    rng = np.random.default_rng(seed)
    amp = np.zeros(len(fr))
    sel = (fr >= MOVE_BAND[0]) & (fr <= MOVE_BAND[1])
    rf, rp = REF["specs"][band]
    amp[sel] = np.sqrt(np.interp(fr[sel], rf, rp))
    w = np.fft.irfft(amp * rng.rayleigh(1.0, len(fr)) * np.exp(2j * np.pi * rng.random(len(fr))), m)
    w /= np.std(w) + 1e-12
    t = (np.arange(n) - START) % LOOP
    return np.interp(t, np.arange(m + 1) * LOOP / m, np.append(w, w[0]))


def wrap_pct(y):
    """loopscope.py's wrap: the jump after the loop's end against a straight line, and the loop's own 99.9th percentile
    of that step, in % of the loop's RMS."""
    loop = y[START:END]
    seq = np.concatenate([loop, loop[:4]])
    jump = abs(seq[LOOP] - (2 * seq[LOOP - 1] - seq[LOOP - 2]))
    inside = np.percentile(np.abs(np.diff(loop[:-74], 2)), 99.9)
    rms = np.sqrt(np.mean(loop ** 2)) + 1e-12
    return 100 * jump / rms, 100 * inside / rms


def low_share(y, cut=104.0 / UP):
    """dB of the loop's power under `cut` Hz as stored (104 Hz as played), the periodic loop."""
    P = np.abs(np.fft.rfft(y[START:END])) ** 2
    f = np.fft.rfftfreq(LOOP, 1 / RATE)
    return float(10 * np.log10(P[(f > 0) & (f < cut)].sum() / P[f > 0].sum() + 1e-30))


def steady_spectrum(z):
    """melodic.character's long-term spectrum of the loop of `z` (at the reference's rate): (freqs, L)."""
    s, e = ref_frames()
    seg = z[s:e]
    n = min(8192, 1 << int(math.log2(max(256, len(seg)))))
    frames = [seg[i: i + n] for i in range(0, max(1, len(seg) - n + 1), n // 4)]
    P = np.array([np.abs(np.fft.rfft(f_ * np.hanning(n))) ** 2 for f_ in frames])
    return np.fft.rfftfreq(n, 1 / REF_RATE), P.mean(axis=0)


def bandwidths(fq, L):
    Ls = np.convolve(L, np.ones(9) / 9, mode="same")
    ref = Ls.max() + 1e-30
    return [float(fq[np.nonzero(Ls > ref * 10 ** (-d / 10))[0][-1]]) for d in (40, 60)]


def rolloff_db(f, fc, slope):
    return np.where(f > fc, -slope * np.log2(np.maximum(f, 1e-9) / fc), 0.0)


def roll_off(x):
    """The corner and slope (dB per octave) whose roll-off brings the loop's -40/-60 dB bandwidths nearest BW40/BW60 (read
    on the spectrum through the gain; the least attenuation among equals) while melodic's centroid of the loop moves no more
    than CENTROID_KEEP from the take's own (a roll-off that darkens the take's colour would be matching the reference's
    spectrum), applied at 44.1 kHz, zero phase, as the sample plays. Returns (x, fc, slope, the bandwidths before, the
    centroid before and after)."""
    fq, L = steady_spectrum(at_ref(x))
    pre = bandwidths(fq, L)
    c0 = float((L @ fq) / L.sum())
    best = None
    for fc in np.geomspace(200.0, 4000.0, 101):
        for slope in np.arange(0.0, 72.1, 0.5):
            Lg = L * 10 ** (rolloff_db(fq, fc, slope) / 10)
            if abs((Lg @ fq) / Lg.sum() / c0 - 1) > CENTROID_KEEP:
                continue
            b40, b60 = bandwidths(fq, Lg)
            key = (round(abs(math.log2(b40 / BW40)) + abs(math.log2(b60 / BW60)), 3), slope, -fc)
            if best is None or key < best[0]:
                best = (key, fc, slope)
    _, fc, slope = best
    Lg = L * 10 ** (rolloff_db(fq, fc, slope) / 10)
    return (loop_filter(x, lambda f: 10 ** (rolloff_db(f, fc, slope) / 20)), fc, slope, pre,
            (c0, float((Lg @ fq) / Lg.sum())))


def swell(base):
    """The gain (dB per frame, 0 from the loop start) that gives the reference's swell over the 83 block phases: a
    smooth curve over the take's own 30 ms level through five knots (0 s, two on the rise, a crest before the loop, the
    loop start; times and levels scanned from four starts): the attack means (against the file's top) matched, the span
    levels as near as the search finds; nothing before the loop over 0.3 dB under the loop's lowest per-phase top.
    Returns (gain at 44.1 kHz, the knots, phase stats)."""
    zb = at_ref(base)
    n, s0 = len(zb), ref_frames()[0]
    t = np.arange(n) / REF_RATE
    stb = s0 / REF_RATE
    c2 = np.concatenate([[0.0], np.cumsum(zb * zb)])
    idx = np.arange(n)
    es = 10 * np.log10((c2[np.clip(idx + HB - HB // 2, 0, n)] - c2[np.clip(idx - HB // 2, 0, n)]) / HB + 1e-30)
    cap_top = min(melodic.envelope_db(zb[s0 + p_:], REF_RATE)[0].max() for p_ in range(HB))   # its lowest per-phase top
    h30 = np.hanning(round(0.03 * REF_RATE))
    h30 /= h30.sum()
    own = 10 * np.log10(np.convolve(zb * zb, h30, mode="same") + 1e-30)
    loop_db = 10 * np.log10(np.mean(zb[s0:] ** 2))

    def curve(k):
        """k: (v0, t1, v1, t2, v2, tc, vc) - dB against the loop's level at 0, t1, t2 and a crest time tc, 0 at the loop
        start (the reference's blocks reach -1.9 dB of its top near 0.675 s, then fall back: a crest before the loop)."""
        v0, t1, v1, t2, v2, tc, vc = k
        T = loop_db + np.interp(t, [0.0, t1, t2, tc, stb], [v0, v1, v2, vc, 0.0])
        G = np.clip(T - own, -40, 30)
        G = np.minimum(G, (cap_top - 0.3) - es)                    # nothing before the loop over the loop's top in any phase
        G[t >= stb] = 0.0
        g = np.convolve(np.concatenate([np.full(len(h30), G[0]), G, np.full(len(h30), G[-1])]), h30, mode="same")[len(h30):-len(h30)]
        g -= np.interp(stb, t, g) * np.clip((t - (stb - 0.1)) / 0.1, 0, 1)   # exactly 0 dB at the loop start
        g[t >= stb] = 0.0
        return g

    def score(k):
        g = curve(k)
        ph, share, spans = phase_stats(zb * 10 ** (g / 20), s0)
        m_ = ph.mean(axis=0)
        return (abs(m_[0] - REF["attack"][0]) / 10 + abs(m_[1] - REF["attack"][1]) / 20
                + sum(abs(a - b) for a, b in zip(spans, REF["spans"])) + 50 * max(0.0, share - REF["before"])), (ph, share, spans)

    def search(k):
        steps = [2.0, 0.03, 2.0, 0.08, 1.0, 0.08, 1.0]
        best = score(k)
        for _ in range(8):                                         # coordinate search, steps halved each pass
            for j in range(len(k)):
                for d in (-steps[j], steps[j]):
                    kk = list(k)
                    kk[j] += d
                    if not (0.02 <= kk[1] < kk[3] - 0.05 and kk[3] < kk[5] - 0.05 and kk[5] <= stb - 0.05):
                        continue
                    sc = score(kk)
                    if sc[0] < best[0]:
                        k, best = kk, sc
            steps = [s_ / 2 for s_ in steps]
        return k, best

    runs = [search([-11.0, 0.13, v1, 0.4, v2, 0.7, vc]) for v1, v2, vc in ((-7.5, -3.0, 0.0), (-6.0, -3.0, 0.0),
                                                                          (-4.5, -3.0, 0.0), (-6.5, -4.0, 1.0))]
    k, best = min(runs, key=lambda r_: r_[1][0])                   # four starts: one knot at a time rarely moves a knot far
    g = curve(k)
    return np.interp(np.arange(len(base)) / RATE, t, g), k, best[1]


def make(cand, raw, gain_db=0.0):
    x, r = mono(RAW / raw)
    if r != RATE:
        x = resample(x, r, RATE)
    x = x - np.mean(x)
    on = int(np.nonzero(np.abs(x) > np.abs(x).max() * 10 ** (-50 / 20))[0][0])
    x = fft_resample(x[on:], int(round((len(x) - on) * UP)))           # stored: 11 semitones under, as the reference's
    x = highpass(x)
    assert len(x) >= END + RATE // 2, f"{raw}: too short as stored ({len(x) / RATE:.2f} s)"
    was = chord_cents(x)
    x = resample(x, RATE * 2 ** (-float(was[0]) / 1200), RATE)          # the root's centre on equal temperament, then
    lag_c, lag_rho, lag_cyc = loop_period(x)                            # the root band's own period over the loop: the
    x = resample(x, RATE * 2 ** (lag_c / 1200), RATE)                   # loop holds whole cycles of what it plays
    seed = zlib.crc32(cand.encode())
    own = measure(loopify(x)[0])
    own2 = twice(loopify(x)[0])
    own_bands = band_slopes(x)
    notes = [f"root band over the loop {lag_cyc:+.2f} cycles off whole (correlation {lag_rho:+.2f} at the best lag): "
             f"retuned {lag_c:+.1f} c"]
    # the pitch wobble (before the loop is cut: one time map through the whole file, periodic with the loop)
    x, wdepth, winfo = add_wobble(x, seed)
    notes.append(f"no wobble added ({winfo['why']}; its root's own periodic part {winfo['own'][0][2]:.0f} c)" if wdepth is None else
                 f"wobble {wdepth:.0f} c on the loop's line at {round(WOBBLE_HZ * LOOP / RATE) * RATE / LOOP:.3f} Hz as "
                 f"stored (floor "
                 f"{winfo['own_floor']:.2f} -> {winfo['floor']:.2f} dB)")
    x = fir_filter(x, lowpass_fir(BAND_TOP / RATE))                     # nothing over the reference's Nyquist (-73 dB)
    tone, lnotes = loopify(x)
    notes += lnotes
    # the floor: noise shaped like the take's spectrum (third-octave smoothed: its formants), one loop long (periodic),
    # nothing under LOW_CUT (cut on the loop's own lines); before the loop it follows the level and meets 1 at the start
    loop = tone[START:END]
    f, S = envelope_spectrum(np.tile(loop, 3), RATE)
    burst = fir_filter(np.tile(shaped_noise(LOOP, RATE, f, S, seed=seed % 2 ** 31), 3), lowpass_fir(BAND_TOP / RATE))[LOOP:2 * LOOP]
    B = np.fft.rfft(burst)
    B[np.fft.rfftfreq(LOOP, 1 / RATE) < LOW_CUT] = 0
    burst = np.fft.irfft(B, LOOP)
    noise = burst[(np.arange(END) - START) % LOOP] * np.sqrt(np.mean(loop ** 2)) / np.sqrt(np.mean(burst ** 2))
    k = np.minimum(10 ** (env_db(tone)[:START] / 20) / np.sqrt(np.mean(loop ** 2)), 1.5)
    hk = np.hanning(round(0.03 * RATE))
    k = np.convolve(np.concatenate([np.full(len(hk), k[0]), k, np.full(len(hk), k[-1])]), hk / hk.sum(), mode="same")[len(hk):-len(hk)]
    ramp = round(0.1 * RATE)
    k[-ramp:] = np.linspace(k[-ramp], 1.0, ramp)
    noise[:START] *= k
    noise = loop_filter(noise, lambda fr: (fr >= LOW_CUT).astype(float))  # the level-following leaves nothing under it either

    # the bands of the tone and of the noise (linear-phase FIRs over the sample as it plays: circular inside the loop, the
    # part before it with the loop running on after it; complementary, so unmoved they sum to the take exactly); under
    # MOVE_SPLIT nothing is moved
    def split(sig):
        lows = [loop_fir(sig[:END], lowpass_fir(c / RATE, taps=16383)) for c in (MOVE_SPLIT,) + SPLIT_HZ]
        return [lows[0], lows[1] - lows[0], lows[2] - lows[1], sig[:END] - lows[2]]

    tone_b, noise_b = split(tone), split(noise)

    def build(g_db, movs):
        gn = 10 ** (g_db / 20) if g_db is not None else 0.0
        return sum((tb_ + nb_ * gn) * m_ for tb_, nb_, m_ in zip(tone_b, noise_b, [np.ones(END)] + list(movs)))

    def floor_gain(movs):
        """The noise gain (dB) for the floor under the band movements, or None if the take's own floor is noisier."""
        if melodic.floor_db(our_loop(build(None, movs)), REF_RATE) >= FLOOR_DB - 0.3:
            return None
        X, N = at_ref(build(None, movs)), at_ref(build(0.0, movs) - build(None, movs))
        s_, e_ = ref_frames()
        lo, hi = -60.0, 20.0
        for _ in range(26):
            g_ = (lo + hi) / 2
            fl = melodic.floor_db((X + N * 10 ** (g_ / 20))[s_:e_], REF_RATE)
            lo, hi = (g_, hi) if fl < FLOOR_DB else (lo, g_)
        return (lo + hi) / 2

    one = [np.ones(END)] * 3
    g_db = floor_gain(one)
    base0 = build(g_db, one)
    own_b, _, own_env = band_moves(base0)
    have = slow_dev(our_loop(base0))
    need = [i for i in range(3) if own_b[i] < REF["bands"][i] - 0.05]
    own_dev = measure(base0).get("level_dev_db", 0.0)
    bound0 = bound = max(REF["c"]["level_dev_db"], own_dev) + 0.1   # the whole level movement: the reference's or the take's own
    movs, pick, depths = one, None, [0.0, 0.0, 0.0]
    if need:
        idx = (np.arange(END) - START) % LOOP
        n_env = len(own_env[0])
        own_env = [np.interp(np.arange(LOOP), (np.arange(n_env) + 0.5) * LOOP / n_env, e_, period=LOOP) for e_ in own_env]

        def orth(wv):
            segs = [w_[START:END] - w_[START:END].mean() for w_ in wv]
            out = []
            for b_, v in enumerate(segs):
                A = np.column_stack([own_env[b_] - own_env[b_].mean()] + out)
                v = v - A @ np.linalg.lstsq(A, v, rcond=None)[0]
                out.append(v)
            return [(v / (np.std(v) + 1e-12))[idx] for v in out]

        def solve(s, g_, bound):
            """Each needing band's depth over its own movement until the band reads the reference's spread (two passes:
            the bands barely interact); then all depths scaled down together while the whole level movement (melodic's,
            over the loop) would pass `bound`."""
            wv = orth([wander(END, s * 3 + b, b) for b in range(3)])
            d = [0.0, 0.0, 0.0]
            for _ in range(2):
                for i in need:
                    lo_d, hi_d = 0.0, 8.0
                    for _ in range(12):
                        d[i] = (lo_d + hi_d) / 2
                        got = band_moves(build(g_, [10 ** (w_ * d_ / 20) for w_, d_ in zip(wv, d)]))[0][i]
                        lo_d, hi_d = (d[i], hi_d) if got < REF["bands"][i] else (lo_d, d[i])
                    d[i] = hi_d

            def lev(f_):
                return measure(build(g_, [10 ** (w_ * d_ * f_ / 20) for w_, d_ in zip(wv, d)])).get("level_dev_db", 0.0)
            if lev(1.0) > bound:
                lo_f, hi_f = 0.0, 1.0
                for _ in range(10):
                    mid = (lo_f + hi_f) / 2
                    lo_f, hi_f = (lo_f, mid) if lev(mid) > bound else (mid, hi_f)
                d = [v * lo_f for v in d]
            return d, [10 ** (w_ * d_ / 20) for w_, d_ in zip(wv, d)]

        best = None
        for s in range(seed % 10007 * 31, seed % 10007 * 31 + DRAWS):
            d, mv = solve(s, g_db, bound)
            y_ = build(g_db, mv)
            m1, m2 = measure(y_), twice(y_)
            _, cc, _ = band_moves(y_)
            lp = roll_off(y_)[0][START:END]                             # the loop as it will be written
            crest_db = 20 * np.log10(np.abs(lp).max()) - 10 * np.log10(np.mean(lp ** 2))
            over = max(0.0, crest_db + RMS_DB + gain_db + 1.0)             # dB over the -1 dBFS limit at this gain
            sc = (abs(m1.get("level_dev_db", 0) - REF["c"]["level_dev_db"]) + abs(m1.get("tremolo_hz", 0) - REF["c"]["tremolo_hz"]) / 2
                  + abs(m2.get("tremolo_hz", 0) - REF["twice"].get("tremolo_hz", 0)) / 2
                  + sum(abs(p - q) for p, q in zip(cc, REF["cc"])) + 10 * over)
            if best is None or sc < best[0]:
                best = (sc, s)
        pick = best[1]
        for _ in range(2):                                         # the floor and the depths solved again under each other
            depths, movs = solve(pick, g_db, bound)
            g_db = floor_gain(movs) if g_db is not None else None
    for attempt in range(4):                                       # the level bound read on the finished file (after the
        if need:                                                   # swell and the roll-off), solved again while it passes
            depths, movs = solve(pick, g_db, bound)
        base, fc, rslope, pre, cens = roll_off(build(g_db, movs))   # (solved on the loop, which the swell leaves alone)
        g, knots, (ph, share, spans) = swell(base)                  # the swell read on the file as it will be written
        y = base * 10 ** (g / 20)
        over = measure(y).get("level_dev_db", 0.0) - bound0
        if not need or over <= 0.005 or attempt == 3:
            break
        bound -= over
    miss = f", missed by {over:.3f}" if need and over > 0.005 else ""
    if need:
        notes.append(f"band movement {'/'.join(f'{v:.2f}' for v in depths)} dB over its own "
                     f"{'/'.join(f'{v:.2f}' for v in own_b)} (draw {pick - seed % 10007 * 31} of {DRAWS}; the whole level "
                     f"movement bound {bound0:.2f} dB on the finished file, the take's own after the wobble and the floor "
                     f"{own_dev:.2f}{miss})")
    else:
        notes.append(f"no band movement added (its own {'/'.join(f'{v:.2f}' for v in own_b)})")
    notes.append("floor: none added (its own is noisier)" if g_db is None else f"floor noise at {g_db:+.1f} dB")
    notes.append("swell knots " + "/".join(f"{v:.2f}" for v in knots))
    fi = round(0.002 * RATE)
    y[:fi] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(fi) / fi)
    y *= 10 ** ((RMS_DB + gain_db) / 20) / np.sqrt(np.mean(y[START:END] ** 2))
    peak = np.abs(y).max()
    limited = peak > 10 ** (-1 / 20)
    if limited:
        y *= 10 ** (-1 / 20) / peak
    pcm = np.clip(np.round(y * 32767), -32768, 32767).astype(int).tolist()
    write_wav(OUT / f"{cand}.wav", RATE, [pcm], 16, loop=(START, END, False), root_note=ROOT_NOTE)
    report(cand, raw, np.array(pcm, float) / 32767, own, own2, was, notes, limited, (fc, rslope, pre, cens), winfo, have,
           own_bands)


def report(cand, raw, yy, own, own2, was, notes, limited, ro, winfo, have, own_bands):
    m, m2 = measure(yy), twice(yy)
    ph, share, spans = phase_stats(at_ref(yy), ref_frames()[0])
    cen = chord_cents(yy)
    wj, wo = wrap_pct(yy)
    bsp, bcc, _ = band_moves(yy)
    fc, rslope, pre, cens = ro
    pl = played(np.tile(yy[START:END], 3))                           # the loop as played, for the screens' measure
    vmm = vm.measure(pl, win=0.2)
    wfin = root_wobble(yy)                                          # the finished file's pitch movement (the loop twice:
    # information only, the loop's own periodic breath jitter reads as periodic there; the class's pitch limit is for takes)
    fails = [f_ for f_ in vm.passes(vmm) if "attack" not in f_ and "pitch movement" not in f_]   # (attack readings on the
    # tiled loop mean nothing: the swell is read over the 83 phases above)
    R = REF
    print(f"{cand} <- {raw}; added: {'; '.join(notes)}{'; PEAK-LIMITED' if limited else ''}\n"
          f"    chord as stored was {' '.join(f'{c:+.1f}' for c in was)} c (centres), now {' '.join(f'{c:+.1f}' for c in cen)}\n"
          f"    own (after the tuning, looped): floor {own['floor_db']:.1f} dB, aperiodicity {own.get('aperiodicity', 0):.2f}, level "
          f"{own.get('level_dev_db', 0):.2f} dB at {own.get('tremolo_hz', 0):.2f} Hz (prom {own.get('tremolo_prominence', 0):.1f}; twice "
          f"{own2.get('tremolo_hz', 0):.2f}), slow part after the wobble and the floor {have:.2f} dB, attack "
          f"{own['attack10_ms']:.0f}/{own['attack3_ms']:.0f} ms\n"
          f"    now: attack {m['attack10_ms']:.0f}/{m['attack3_ms']:.0f} ms (phase 0; reference 129/675), over the 83 phases means "
          f"{ph[:, 0].mean():.1f}/{ph[:, 1].mean():.1f} ms (reference {R['attack'][0]:.1f}/{R['attack'][1]:.1f}), ranges "
          f"{ph[:, 0].min():.0f}-{ph[:, 0].max():.0f} / {ph[:, 1].min():.0f}-{ph[:, 1].max():.0f} (reference "
          f"{R['attack_rng'][0][0]:.0f}-{R['attack_rng'][1][0]:.0f} / {R['attack_rng'][0][1]:.0f}-{R['attack_rng'][1][1]:.0f}); the "
          f"file's peak before the loop in {100 * share:.0f} % of phases ({100 * R['before']:.0f}); spans "
          f"{'/'.join(f'{v:+.2f}' for v in spans)} dB against the loop ({'/'.join(f'{v:+.2f}' for v in R['spans'])})\n"
          f"    floor {m['floor_db']:.2f} dB ({FLOOR_DB}), aperiodicity {m.get('aperiodicity', 0):.2f} (0.51), flatness "
          f"{m['flatness_db']:.1f} dB (-22.1), centroid {m['centroid_hz']:.0f} Hz moving {m['centroid_move_hz']:.0f} (290, 15), "
          f"level {m.get('level_dev_db', 0):.2f} dB at {m.get('tremolo_hz', 0):.2f} Hz prom {m.get('tremolo_prominence', 0):.1f} "
          f"(1.83 at 4.33, 2.4), twice {m2.get('tremolo_hz', 0):.2f} Hz prom {m2.get('tremolo_prominence', 0):.1f} "
          f"({R['twice'].get('tremolo_hz', 0):.2f}, {R['twice'].get('tremolo_prominence', 0):.1f}), slope "
          f"{m.get('level_slope_db_per_s', 0):+.2f} dB/s (+0.56, held flat), slow part {slow_dev(our_loop(yy)):.2f} dB "
          f"({R['slow']:.2f})\n"
          f"    band movement (100-300, 300-700, 700-2200 Hz as stored, {MOVE_BAND[0]}-{MOVE_BAND[1]} Hz): "
          f"{'/'.join(f'{v:.2f}' for v in bsp)} dB, correlations {'/'.join(f'{v:+.2f}' for v in bcc)} (reference "
          f"{'/'.join(f'{v:.2f}' for v in R['bands'])}, {'/'.join(f'{v:+.2f}' for v in R['cc'])})\n"
          f"    pitch movement as played (tonevib, A-3 E-4 C-5): the take's own over {WOBBLE_READ:.0f} s "
          f"{'/'.join(f'{t_[2]:.0f}' for t_ in winfo['own'])} c periodic -> with the wobble "
          f"{'/'.join(f'{t_[2]:.0f}' for t_ in winfo['fin'])}; the finished loop played twice (information: its "
          f"loop-periodic breath reads as periodic) {'/'.join(f'{t_[2]:.0f}' for t_ in wfin)} (lines "
          f"{'/'.join(f'{t_[1]:.1f}' for t_ in wfin)} Hz; reference {'/'.join(f'{t_[2]:.0f}' for t_ in R['wobble'])} c at "
          f"{'/'.join(f'{t_[1]:.1f}' for t_ in R['wobble'])} Hz); floor before/after the wobble {winfo['own_floor']:.2f}/"
          f"{winfo['floor']:.2f} dB (on its loop, before the added floor)\n"
          f"    by band (under 70, 70-300, 300-700, 700 Hz and up as stored) over the loop: slope "
          f"{'/'.join(f'{s_:+.2f}' for s_, _ in band_slopes(yy))} dB/s (the take's own before loopify "
          f"{'/'.join(f'{s_:+.2f}' for s_, _ in own_bands)}, its last 0.2 s against the first "
          f"{'/'.join(f'{d_:+.1f}' for _, d_ in own_bands)} dB); the step across the wrap "
          f"{'/'.join(f'{a_:+.1f}' for a_, _ in band_wrap(yy))} dB (their own 20 ms steps at every 1 ms inside the loop, 95th percentile "
          f"{'/'.join(f'{b_:.1f}' for _, b_ in band_wrap(yy))}); in the blend region (the loop's last 0.4 s) the 20 ms "
          f"levels {' / '.join(f'{a_:+.1f}..{b_:+.1f}' for a_, b_, _, _ in blend_range(yy))} dB, elsewhere in the loop "
          f"{' / '.join(f'{c_:+.1f}..{d_:+.1f}' for _, _, c_, d_ in blend_range(yy))}; the loop's 10 ms top {loop_top(yy):.2f} dB over its RMS "
          f"(reference {REF['top']:.2f}); the band movement's rates {'/'.join(f'{c_:.1f}' for c_, _ in rate_reading(band_moves(yy)[2]))} "
          f"Hz, spread {'/'.join(f'{o_:.2f}' for _, o_ in rate_reading(band_moves(yy)[2]))} octave (reference "
          f"{'/'.join(f'{c_:.1f}' for c_, _ in REF['rates'])}, {'/'.join(f'{o_:.2f}' for _, o_ in REF['rates'])})\n"
          f"    roll-off {'from ' + format(fc, '.0f') + ' Hz at ' + format(rslope, '.1f') + ' dB per octave' if rslope else 'none'}: "
          f"bw40/60 {pre[0]:.0f}/{pre[1]:.0f} -> {m['bw40_hz']:.0f}/{m['bw60_hz']:.0f} Hz ({BW40:.0f}/{BW60:.0f}), centroid "
          f"{cens[0]:.0f} -> {cens[1]:.0f} Hz (kept within {100 * CENTROID_KEEP:.0f} %); under 104 Hz as "
          f"played {low_share(yy):.1f} dB of the loop; wrap {wj:.2f} % (the loop's own {wo:.2f} %), the first pass into the "
          f"loop {entry_pct(yy):.2f} %; peak "
          f"{20 * math.log10(np.abs(yy).max() + 1e-12):.1f} dBFS\n"
          f"    the screens' class (vocal/measure.py on the loop as played; attack and pitch movement left out, read above): "
          f"{'all met' if not fails else '; '.join(fails)}; ahhs_db {vmm['ahhs_db']:.1f}, under 1 kHz {vmm['ahhs_lo_db']:.1f}", flush=True)


# ------------------------------------------------------------------------------------------------ the pattern

PATTERNS = ["loop", "loop_b"]
NOTES = {"loop": "A-3", "loop_b": "A-3"}                   # the note on row 0 of each pattern: one written pitch
SWELL = {"loop": (5, 23, 16), "loop_b": (23, 23, 0)}       # volume on the note row, volume reached, rows to reach it
LEGATO = {"loop": False, "loop_b": True}                   # struck in loop, restated by GFF in loop_b
PAN = 32
CHANNEL = f"    - {{name: Vocal, pan: {PAN}, volume: 64}}\n"


def figure():
    cols = {p: [dict()] for p in PATTERNS}
    for p in PATTERNS:
        v0, v1, rows = SWELL[p]
        col = cols[p][0]
        col[0] = f"{NOTES[p]} 14 v{v0:02d}" + (" GFF" if LEGATO[p] else "")
        for r in range(1, rows + 1):                         # the swell in whole steps, rounded down, as the reference's
            col[r] = f"... .. v{v0 + (v1 - v0) * r // rows:02d}"
    return cols


FADE = ["D01"] + ["D00"] * 15                               # the form's close (the reference's order 49): to silence


def fade():
    """Channel 24 in the pattern after the form's last vocal pattern, then a cut, silent by then (the app's SOUNDING table
    follows cuts, not D fades)."""
    return [{**{r: f"... .. ... {fx}" for r, fx in enumerate(FADE)}, len(FADE): "^^^"}]


def pattern(path=HERE / "rift.yaml", first_sample="vocal_placeholder.wav"):
    b = path.read_bytes()
    crlf = b"\r\n" in b
    t = b.decode("utf-8").replace("\r\n", "\n")
    t = ensure_channels(t, CHANNEL, r"    - \{name: Noise[^\n]*\n")      # the owner's lines stay
    line = re.search(r"\n  14: \{file:[^\n]*\n", t)
    if not line:
        new = (f"  14: {{file: ../../samples/local/rift-cand/{first_sample}, base_note: {BASE_NOTE}, loop: from_wav, "
               f"name: {Path(first_sample).stem}}}\n")
        anchor = "\n\ninstruments:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + new + "\ninstruments:\n", 1)
    else:                                                      # the picked file stays; the stored note is the generator's
        fixed = re.sub(r"base_note: [A-G][-#]\d", f"base_note: {BASE_NOTE}", line.group(0))
        t = t[:line.start()] + fixed + t[line.end():]
    if "\n  14: {name: Vocal" not in t:
        ins = "  14: {name: Vocal, sample: 14}   # sample mode, as in the reference: the swell is in the pattern\n"
        anchor = "\n\npatterns:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + ins + "\npatterns:\n", 1)
    t = write_columns(t, 23, figure())
    if crlf:
        t = t.replace("\n", "\r\n")
    path.write_bytes(t.encode("utf-8"))
    print(f"wrote channel 24 into {path.name}: {NOTES} (struck in loop, GFF in loop_b), swells {SWELL}, pan {PAN}, sample 14 "
          f"at {BASE_NOTE}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["pattern"]:
        pattern(first_sample=next(iter(CANDS), "vocal_placeholder") + ".wav")
        sys.exit()
    reference_figures()
    if sys.argv[1:2] == ["ref"]:                                       # the calibration: the reference's own numbers
        c = REF["c"]
        print("reference:", ", ".join(f"{k} {c[k]:.2f}" for k in ("secs", "attack10_ms", "attack3_ms", "aperiodicity", "floor_db",
                                                                     "flatness_db", "centroid_hz", "centroid_move_hz", "bw40_hz",
                                                                     "bw60_hz", "level_dev_db", "tremolo_hz", "tremolo_prominence",
                                                                     "level_slope_db_per_s")))
        print(f"reference over the 83 block phases: attack means {REF['attack'][0]:.1f}/{REF['attack'][1]:.1f} ms, ranges "
              f"{REF['attack_rng'][0][0]:.0f}-{REF['attack_rng'][1][0]:.0f} / {REF['attack_rng'][0][1]:.0f}-{REF['attack_rng'][1][1]:.0f}; "
              f"peak before the loop in {100 * REF['before']:.0f} %; spans {[round(float(v), 2) for v in REF['spans']]} dB against the "
              f"loop; band movement {[round(v, 2) for v in REF['bands']]} dB, correlations {[round(v, 2) for v in REF['cc']]}; "
              f"slow part {REF['slow']:.2f} dB; twice {REF['twice'].get('tremolo_hz', 0):.2f} Hz prom "
              f"{REF['twice'].get('tremolo_prominence', 0):.1f}; pitch movement as played at its own tones, periodic "
              f"{[round(t_[2]) for t_ in REF['wobble']]} c at {[round(t_[1], 1) for t_ in REF['wobble']]} Hz")
        x, r = ref_wav()                                               # the chain ours go through, on the reference
        y = fft_resample(x, int(round(len(x) * RATE / r)))             # its stored file at 44.1 kHz
        s, e = ref_frames()
        cy = melodic.character(at_ref(y), REF_RATE, ("fwd", REF_LOOP[0], REF_LOOP[1]))
        print(f"reference through 44.1 kHz and at_ref: bw40/60 {cy['bw40_hz']:.0f}/{cy['bw60_hz']:.0f} Hz, flatness "
              f"{cy['flatness_db']:.2f}, centroid {cy['centroid_hz']:.1f}, floor {cy['floor_db']:.2f}, level dev "
              f"{cy['level_dev_db']:.2f}; our loop frames at the reference's rate {s}-{e} ({(e - s) / REF_RATE:.3f} s)")
    else:
        for cand, raw in CANDS.items():
            if not sys.argv[1:] or cand in sys.argv[1:]:
                make(cand, raw, GAIN.get(cand, 0.0))
