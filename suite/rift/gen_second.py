"""Rift, layer 9 of BRIEF.md's layer plan: the second line, written the way Nether Animal writes its second line (measured
with scratch/ut99-clean/melodic.py and read from its cells with rifttools/artic.py 28, counts only; only the idioms and
the sample's character are taken, the notes are ours).

The reference's sample (Nether's 28, JT-Synth3), read with melodic.character at its 9387 Hz storage rate through an FFT
resample, its DC offset (-0.087 of full scale, 13 % of its loop's power; silent when heard, but it pulls melodic's
centroid and level readings) taken off (`gen_second.py ref` prints both): 5.477 s, a ping-pong loop of 2.664 s from
2.813 s to its end, sounding D3+15c at its stored rate and played 6-18 semitones over it (its written notes against C-5,
median 13: counts from its cells); attack 0/10 ms to -10/-3 dB (means over the 93 block phases 1.07/8.10 ms against its
loudest 10 ms block, a crest at 0.54 s; 0.32/4.79 ms against its own settled level, the mean square over one whole
period centred at 25 ms; its first 2 ms blocks read -10.6/-7.5/-2.7 dB against its 10-20 ms level); over its loop a
level slope of -1.78 dB/s, a regular tremolo (2.17 Hz, 3.61 dB, prominence 23.6), a slight vibrato (2.25 Hz, 7.7 c peak
to peak, prominence 7.1) and a pitch drift of -3.06 c/s; before its loop (the level read as level_track reads it, a mean
square under a Hann window three periods long) the level falls 1.78 dB/s over the whole span (a fitted line), the
movements are shallower (the level's swing per tremolo cycle, the level less its 1 s mean, 3.73/4.05/3.28/3.05/3.05 dB
in the five cycles from 0.05 s against 8.1 in its loop and 10.9 in the cycle from 2.32 s; the level's range over its
first 0.26/0.41/0.77 s from 25 ms 1.07/2.12/3.52 dB: it falls about 1 dB by 0.1 s and rises about 3 dB to the crest at
0.54 s; the pitch's movement 1.8/3.0/6.6/5.1 c over 0-0.4/0.4-1.2/1.2-2.0/2.0-2.8 s against 8.3 in its loop) and the
pitch wanders around the loop's median; its white 8-bit floor makes almost none of these readings (doubled, its pitch
spans move at most 0.23 c and its ranges and swings 0.06 dB over four noise draws); floor -23.8 dB (-26.87 in the
third-octave band holding its fundamental, -26.84 in the bands above it), flatness -25.3 dB, centroid 227 Hz (1.53
partials), -40/-60 dB
bandwidths 2240/4694 Hz (the second at its Nyquist); partials falling about 6 dB each, odd over even +6.4 dB, harmonic.

`python suite/rift/gen_second.py [cand ...]` makes the slot-15 candidates from the screened takes
(second/{surge,dx_obxd,rec}/, each rendered at A#3, the pitch it is stored at) the reference's way:
  1. DC and everything under 20 Hz off (a 20-45 Hz ramp); tuned so melodic's median pitch over the loop's span reads A#3
     (116.54 Hz: the reference's stored pitch moved to our key) by an FFT resample; stored at 44.1 kHz with base_note
     A#3, so our notes E-4..C-5 play it 6-14 semitones up (inside the reference's 6-18).
  2. The band, on the take as it runs on (all filtering is done before the loop is formed): nothing over the reference's
     storage Nyquist (a 1023-tap low-pass, -73 dB from 4693.5 Hz), then a roll-off toward its -40/-60 dB bandwidths that
     moves melodic's centroid at most 5 % (the take's colour is its own).
  3. The movements, on the reference's measured figures where the take's own read less, each solved on the reading of
     the file without its floor noise (below) with the others in place (bisection, three rounds; read with the loop at
     its nominal place, so the turns chosen last do not move the readings): the vibrato and the tremolo on one line, the
     loop's 12th mirror line (12 half cycles in the loop: 2.252 Hz, the reference's 2.17/2.25 Hz), with a crest on the
     onset and extrema on both ping-pong turns (so each runs on unbroken through them); so the loop starts 2.886 s in,
     the first half cycle of that line after the reference's 2.813 s, and keeps the reference's 2.664 s (the file 5.550
     s). In the loop they run at the depths read over the reference's loop (vibrato 7.7 c, tremolo 3.61 dB); before it
     at the reference's depth there, which is shallower and is what most of our notes play (a 2-row note plays the first
     0.31-0.41 s of the sample: the pickup's G-4 and A-4, the figure's C-5; a 4-row note 0.51-0.77 s, the glided B-4 >
     A-4 0.73 s), each depth the least that brings its reading to the reference's (none where the take's own movement
     and the lines already reach it). The levels before the loop are read on a mean square under a Hann window three
     periods of the tone long (level_track; its nulls fall on every multiple of f0): at our A#3 melodic's 10 ms block
     holds 1.155 periods and its level beats with the waveform, 1.0-1.4 dB on a steady tone (at the reference's pitch
     0.2 dB on a sine, 1.2-2.5 dB with neighbouring partials), which the first build's solve matched in place of a
     movement, and a 20 ms Hann still beat 0.1-0.3 dB at our A#3 where neighbouring partials sound. The tremolo: held
     over the first 0.26 s at the depth that brings the level's range there to the reference's 1.07 dB, a knot at 0.41
     s for the range over the first 0.41 s (2.12 dB), then a knot at the centre of each of the next four tremolo cycles
     for its swing (4.05/3.28/3.05/3.05 dB), the last held to the end of cycle 5 (2.32 s), full from 2.43 s (the
     reference's swing steps from 3.05 dB in cycle 5 to 10.9 in cycle 6); the first cycle's swing (the reference's 3.73)
     is left as the two early knots, set for the short notes, leave it. The vibrato: a knot in each pitch span
     (0.2/0.8/1.6/2.4 s) for its movement there (1.8/3.0/6.6/5.1 c), full at the loop start; the knots are fitted once
     more after the onset (below), which YIN's first frames, and so the first span's reading, hold (sine without its
     noise read its first span 2.57 c with the solve's provisional onset and 1.42 with its final one). The pitch through
     one time map: the vibrato, the drift (to -3.06 c/s through the loop, centred on its middle; before the loop the
     pitch stays at the loop's median, as the reference's does, rising to the loop start's value over its last 0.25 s so
     nothing jumps) and the take's own slow pitch before the loop levelled to its loop's median (its pitch track's
     running median over 0.5 s taken off; a take's own blip at the onset, shorter than that, stays its own); the map's
     mean rate over the loop is 1, so the tuning holds. Then the level, pointwise (a gain plays the same on both passes
     of a ping-pong loop): the slope, through the loop to -1.78 dB/s and before it to the reference's trend there (-1.78
     dB/s, a line fitted to the level from 0.05 s to the loop start), each where the take's own falls less (the two
     lines meet at the loop start; a take's own early decay is not doubled: badnews falls 1.50 dB/s of its own before its
     loop), and the tremolo; then a floor where the take with its movements is purer between its partials than the
     reference: noise shaped like the take's spectrum, band-limited as the take, cut under 126 Hz as stored (none in the
     third-octave band holding the fundamental but what the level shaping folds back: the 10 ms level it follows beats
     at twice the fundamental and carries the tremolo, up to +1.0 dB in that band) and following the level-shaped take's
     10 ms level (which spreads a trace of it back under 104 Hz as played at the lowest note: the log prints it), its
     level solved so the floor read between the partials above that band (perchannel's measure, band by band) meets the
     reference's -26.84 dB; ours holds the movements' own sidebands in the fundamental's band, so the whole reading comes
     out over the reference's -23.83 (the log prints both parts). The movements are solved without this noise: shaped
     like the take, it sits where the partials are (7-11 dB more of it under 500 Hz than the reference's white floor at
     the same floor reading), and its random wobble reads as movement (on sine, organ and pulse 0.6-3.8 c of the pitch
     spans and up to 0.6 dB of the ranges on the final files), where the reference's floor reads as almost none; so the
     finished file reads over the reference's by the noise's own wobble (the log prints both, the file as solved and
     the finished file).
     Last, once the rest is solved, the onset from silence in two stages (without it the filters' ringing before a
     take's onset would start the file on a step): a raised cosine to a level in 1.5 ms, then another to full, the pair
     searched together over a fine grid (onset_search: the first stage 0-20 dB under full every 0.25 dB, the second
     0.5-18 ms every 0.125 ms) so the times to -10 / -3 dB of the onset's own settled level (the mean square over one
     whole period centred at 25 ms: a 10 ms block's level beats with the waveform, -0.5..+1.0 dB off the period's on
     ours), means over the 93 block phases, come nearest the reference's 0.32 / 4.79 ms. Against the file's loudest 10
     ms block, the class measure's reading, the reference reads 1.07 / 8.10 and ours 0.75-3.73 / 8.10-17.68: each file
     peaks at the tremolo's first crest, 0.39-0.49 s in (the reference's at 0.54 s), 1.4-2.7 dB over its 10-20 ms level
     (means over the 93 phases; the reference's 2.1). The first 2 ms blocks read the waveform's phase at these pitches
     (a block is 0.2-0.3 of a period), so they are not followed. Then the ping-pong turns, each within half a period of
     its place, on the frame
     where the step the tracker plays at the turn is smallest (it plays the end frame twice and the start frame once). A
     take's own movement that reads more than the reference's is kept (the class limits bound it): its own vibrato leads
     the reading's rate where it is the larger part, and its own onset stays in its first 0.4 s reading (badnews's first
     80 ms swing about -35 to +60 c, as 40 ms frames read them; its take then holds within 0.2 c, the file with its floor
     noise within a few cents).
  4. A gain per candidate (GAIN): the line (main and echo) 10.3 dB under the sub in the song (the reference's, active
     level: perchannel's sample 28 against sample 19); a -1 dBFS guard that none of the five reaches.
Every figure the log prints is read the reference's way (melodic.character at 9387 Hz, the loop as its steady part; the
movements before the loop by pre_loop(), which reads the reference's REF_PRE; `ref` prints the reference's own readings).

`python suite/rift/gen_second.py pattern` writes the line into rift.yaml (channels 25-26, slot 15, instrument 15), the
reference's idioms from its cells: its line plays in bar 1 of every second pattern (under its lead's call) on one
channel at the sample's own volume (its v16 is its sample's default volume, 16; ours is 64, so every volume below is
written x4, the same in dB: at v16 the -1 dBFS peak limit would hold the line about 5 dB under the reference's level),
the second note glided into (G54: done within a tick), the sixth held and faded by the volume column to silence 29 rows
on; in the fuller of its two patterns the held note glides on to a seventh (G20, at the fade's level there: v14, ours
v56) and a three-note pickup on rows 58-62 is faded out by the next pattern's first rows (DF2, then D00: -2 a row from
16 in 8 rows; ours DF8); an echo channel repeats every note but the pickup 3 rows later at v7 (-7.2 dB; v6 on the glide;
ours v28, v24) with its own fade; every one of its notes carries the sample's number, so each plays at the sample's
default pan, 32 (centred: an S87 the row after a note moves it for that row only), and ours are centred. The loop takes
the fuller pattern (`loop`) and the rest after it (`loop_b`: the pickup's fade); the other pattern (the same figure's
rhythm on other notes, its sixth held without the glide) is form work.
Our notes (A minor, sounding): the figure B-4 A-4 C-5 B-4 E-4 A-4, gliding on to B-4, the pickup G-4 A-4 B-4
(rifttools/secondcheck.py compares them with the reference's cells, counts only). Channels 1-24 are not touched; an
existing channel line keeps the owner's volume and pan; sample 15 keeps its picked file, its base note set here.
Since Step 3 (the form) rift.yaml has no `loop`/`loop_b`: gen_form.py writes it from this writer's pattern
functions (figure(), or the form's variants beside it where there are any), and `pattern` stops there with a
message; pattern(path) still writes the loop song, rift_loop.yaml.
"""
import importlib.util
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
import melodic  # noqa: E402
from vulturetracker.resample import fir_filter, lowpass_fir  # noqa: E402
from vulturetracker.wavload import read_wav, write_wav  # noqa: E402
from gen_floor import envelope_spectrum, shaped_noise  # noqa: E402
from gen_seq import ensure_channels, write_columns  # noqa: E402

_spec = importlib.util.spec_from_file_location("second_measure", ROOT / "samples/local/rift-cand/second/measure.py")
sm = importlib.util.module_from_spec(_spec)  # the screens' class measure (by path: suite/nadir has a measure.py too)
_spec.loader.exec_module(sm)

OUT = ROOT / "samples" / "local" / "rift-cand"
RAW = OUT / "second"
RATE, REF_RATE = 44100, sm.REF_RATE                        # 9387 Hz: the reference's storage rate
ROOT_NOTE, BASE_NOTE = 46, "A#3"                           # the stored pitch (tracker naming, C-5 = 60): 116.54 Hz
F_ROOT = sm.ROOT_HZ
LOOP_S = (sm.REF_LOOP[1] - sm.REF_LOOP[0]) / REF_RATE      # 2.664 s: the reference's loop (as stored)
HALF = 12                                                  # half cycles of the movement in the loop: 2.252 Hz
F_MOVE = HALF / (2 * LOOP_S)
START0 = math.ceil(sm.REF_LOOP[0] / REF_RATE * 2 * F_MOVE) / (2 * F_MOVE)   # 2.886 s (the reference's 2.813)
END0 = START0 + LOOP_S                                     # 5.550 s: the loop's end and the file's
S0, E0 = round(START0 * RATE), round(END0 * RATE)          # frames at 44.1 kHz
TOP = REF_RATE / 2                                         # 4693.5 Hz: the reference's storage holds nothing above it
BAND_TOP = TOP - 120.0                                     # the band limit's cutoff: its 1023-tap FIR reaches -73 dB by TOP
BW40, BW60 = 2240.18, 4693.50
CENTROID_KEEP = 0.05
LO_HZ = sm.LO_HZ                                           # 73.5 Hz as stored: 104 Hz as played at the lowest note
# the reference's figures (DC off; `gen_second.py ref` prints them): over the loop, vibrato c p-p, drift c/s, level dev dB,
# slope dB/s (sm.REF); before it, the level's trend dB/s (a line fitted to the level from 0.05 s to the loop start); the
# floor between the partials above the third-octave band holding the fundamental (perchannel's floor measure split by
# band: the reference's -23.83 dB is -26.87 in the band holding its fundamental and -26.84 above it, -48.3 under it; ours
# holds its movements' own sidebands in that band); the onset: ms to -10 and to -3 dB of its own settled level (the mean
# square over one whole period centred at BASE_AT), means over the 93 phases of melodic's 10 ms blocks (onset_means; kept
# exact: the readings step by 1/93 of a frame, and a rounded target can prefer a neighbouring step to the reference's
# own value; against the file's loudest block, the class measure's reading, the reference's read 1.07 / 8.10);
# the level's range over the file's first 0.26 and 0.41 s from 25 ms, dB (under and at our 2-row notes: they play the
# first 0.31-0.41 s of the sample); the level's swing in the tremolo cycles 2-5 from 0.05 s, dB; the pitch's movement
# over 0-0.4, 0.4-1.2, 1.2-2.0 and 2.0-2.8 s, c. Every level before the loop is read by level_track(), a mean square
# under a Hann window three periods long at the centres of melodic's 10 ms blocks: the blocks themselves hold 1.155
# periods of our A#3 and beat with it (1.0-1.4 dB on a steady tone; at the reference's pitch 0.2 dB on a sine, 1.2-2.5
# dB with neighbouring partials), and a 20 ms Hann still beat 0.1-0.3 dB at ours where neighbouring partials sound
TARGET = dict(vib=7.67, drift=-3.06, dev=3.61, slope=-1.78, slope_pre=-1.78, floor=-26.84, onset10=0.3196, onset=4.7939,
              early=1.07, early2=2.12, am1=4.05, am2=3.28, am3=3.05, am4=3.05, fm1=1.77, fm2=3.02, fm3=6.57, fm4=5.06)
READ = dict(vib="vibrato_depth_cents", drift="drift_cents_per_s", dev="level_dev_db", slope="level_slope_db_per_s")
REF_FLOOR = (-23.83, -26.87, -26.84)                       # the reference's floor: whole, its fundamental's band, above it
FUND_EDGE = 100 * 2 ** (1 / 3)                             # 126 Hz as stored: the top of the band holding our fundamental
RMS_DB = -18.0                                             # the loop's level before the per-candidate gain
RAMP = 0.25                                                # s: the drift's offset reached before the loop starts
ONSET1 = 0.0015                                            # s: the onset's first stage (a raised cosine to its solved level)
BASE_AT = 0.025                                            # s: the onset's settled level, one period of f0 centred here
EARLY = (0.26, 0.41, 0.77)                                 # s: under our 2-row notes, at the longest (C-5), a 4-row B-4
# the movements' depth before the loop (against their depth in the loop), solved per candidate on the file without its
# floor noise to the reference's readings there, each the least depth that meets its reading (the take's own movement
# counts): the tremolo held at `early` over the first 0.26 s (the level's range there), `early2` at 0.41 s (the range
# over the first 0.41 s), then a knot at the centre of each of the tremolo cycles 2-5 from 0.05 s (their swings), the
# last held to the end of cycle 5 (2.32 s), full from 2.43 s (the reference's swing steps from 3.05 dB in cycle 5 to
# 10.9 in cycle 6); the vibrato at a knot in each of the four pitch spans (their movement), full at the loop start
AM_T = (0.0, EARLY[0], EARLY[1], 0.73, 1.19, 1.64, 2.10, 2.32, 2.43)
AM_AT = ("early", "early", "early2", "am1", "am2", "am3", "am4", "am4")   # the depth at each knot but the last (full)
AM_KEYS = ("early", "early2", "am1", "am2", "am3", "am4")
FM_T = (0.2, 0.8, 1.6, 2.4, START0)
FM_KEYS = ("fm1", "fm2", "fm3", "fm4")
REF_PRE = ((1.1, 2.1, 3.5), (3.7, 4.1, 3.3, 3.0, 3.1), (1.8, 3.0, 6.6, 5.1))   # the reference's pre_loop(), for the log

# candidate -> its screened take (relative to RAW): five of the eighteen finalists of three family screens (1889 Surge
# patches, 2458 Dexed/OB-Xd sources, 660 CC0 recordings (none in class: 22 of the 23 measured fail the onset) and 310
# takes of our own models; screen.txt in each), chosen on what this generator makes of them (second/finalists.py,
# finalists.txt): the five farthest-apart kinds in kinds.py's units as the brief set them (the limit is the blown-pulse
# pair: 24 sets tie there), with the lowest-pref take of each other kind; the most frequent set over the 32 variants of
# the metric, each the most frequent take of its kind
CANDS = {
    "second_badnews": "surge/second_badnews.wav",      # Surge Bluelight "Bad News": one shaped-sine oscillator (odd partials
                                                        # 3-9 at -14 to -18 dB, evens under -50) through a 12 dB low-pass and
                                                        # a comb, its two sub wavetables muted, one unison voice, attacks at
                                                        # the minimum
    "second_blown": "rec/second_m_blown.wav",          # our own model: a blown pipe, noise exciting a comb on A#3 (loop gain
                                                        # 0.9995): the tone is the noise's resonance; its own noise floor
                                                        # (-30.8 dB between the partials) topped up like the others'
    "second_organ": "rec/second_m_organ.wav",          # our own model: two drawbars, the fundamental and its octave at
                                                        # one level (8' and 4'), nothing else
    "second_pulse": "rec/second_m_pulse.wav",          # our own model: a 20 % pulse (every 5th partial missing) under a
                                                        # 2-pole low-pass from 3 x f0
    "second_sine": "rec/second_m_sine.wav",            # our own model: a near-sine, the 2nd partial at -12 dB and the 3rd
                                                        # at -20, nothing above
}
GAIN = {"second_badnews": -5.3, "second_blown": -7.3, "second_organ": -5.3, "second_pulse": -5.3,
        "second_sine": -5.3}                          # dB: the line (main and echo) 10.3 dB under the sub (measured)


def mono(path):
    w = read_wav(path)
    return np.asarray(w.channels, float).mean(axis=0) / 2 ** (w.bits - 1), w.rate


def ref_wav():
    return mono(next((ROOT / "scratch/ut99/nether/nether_samples").glob("28_*.wav")))


def at_ref(y):
    """`y` (44.1 kHz, as stored) at the reference's rate by FFT: the same pitch, everything up to its Nyquist kept."""
    return sm.stored(y)


def char(y, s=S0, e=E0):
    """melodic.character of `y` (44.1 kHz, as stored) at the reference's storage rate, s..e (frames at 44.1 kHz) as the
    ping-pong loop (its steady part), DC off."""
    y = y - np.mean(y[:e])
    return melodic.character(at_ref(y), REF_RATE, ("pingpong", round(s * REF_RATE / RATE), round(e * REF_RATE / RATE)))


def attack_means(y):
    """ms to -10 / -3 dB of the file's loudest 10 ms block, means over the 93 block phases (the class measure's reading)."""
    return sm.attack_means(at_ref(y - np.mean(y)))


def onset_means(y, f0=F_ROOT):
    """ms to -10 / -3 dB of the onset's own settled level, means over the 93 block phases. The level: the mean square over
    one whole period of f0 centred at BASE_AT, after any onset the search tries (its second stage ends by 19.5 ms); a 10
    ms block's level beats with the waveform (at our A#3 -0.5..+1.0 dB off the period's), a whole period's does not."""
    z = at_ref(y - np.mean(y))
    c = np.concatenate([[0.0], np.cumsum(z * z)])
    per, at = REF_RATE / f0, BASE_AT * REF_RATE
    cum = lambda u: np.interp(u, np.arange(len(c)), c)
    ref = 10 * math.log10((cum(at + per / 2) - cum(at - per / 2)) / per + 1e-20)
    a10, a3 = [], []
    for ph in range(sm.HB):
        e, h = melodic.envelope_db(np.concatenate([np.zeros(ph), z[: int(0.2 * REF_RATE)]]), REF_RATE)
        a10.append(1000 * (np.nonzero(e >= ref - 10)[0][0] * h - ph) / REF_RATE)
        a3.append(1000 * (np.nonzero(e >= ref - 3)[0][0] * h - ph) / REF_RATE)
    return float(np.mean(a10)), float(np.mean(a3))


def zpad_filter(x, gain_fn):
    """Zero-phase filter of `x` by the gain function of frequency (zero-padded: no wrap)."""
    n = 1 << int(math.ceil(math.log2(len(x) + RATE)))
    return np.fft.irfft(np.fft.rfft(x, n) * gain_fn(np.fft.rfftfreq(n, 1 / RATE)), n)[: len(x)]


def highpass(x, lo=20.0, hi=45.0):
    return zpad_filter(x, lambda f: 0.5 - 0.5 * np.cos(np.pi * np.clip((f - lo) / (hi - lo), 0, 1)))


def tune(x):
    """`x` resampled so melodic's median pitch over the loop's span reads A#3 (read twice: the first move shifts the
    window a little). Returns (x, the cents it was off)."""
    was = None
    for _ in range(2):
        f0 = char(x)["f0_hz"]
        was = 1200 * math.log2(f0 / F_ROOT) if was is None else was
        x = sm.fft_resample(x, int(round(len(x) * f0 / F_ROOT)))
    return x, was


def steady_spectrum(y):
    """melodic.character's long-term spectrum of the loop's span of `y` at the reference's rate: (freqs, L)."""
    seg = at_ref(y)[round(S0 * REF_RATE / RATE): round(E0 * REF_RATE / RATE)]
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
    """The corner and slope (dB per octave) that bring the loop's -40/-60 dB bandwidths nearest the reference's (the
    least attenuation among equals) while melodic's centroid moves no more than CENTROID_KEEP; zero phase, on the take
    before the loop is formed. Returns (x, fc, slope, bandwidths before and after, centroid before and after)."""
    fq, L = steady_spectrum(x)
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
    return (zpad_filter(x, lambda f: 10 ** (rolloff_db(f, fc, slope) / 20)), fc, slope, pre, bandwidths(fq, Lg),
            (c0, float((Lg @ fq) / Lg.sum())))


def warp(x, cents):
    """`x` through one time map whose rate is 2**(cents/1200) (per frame; its mean over the loop's span 1, so the tuning
    holds): Catmull-Rom interpolation, fine for content under 4.7 kHz at 44.1 kHz."""
    r = 2 ** (cents / 1200)
    r = r / r[S0:E0].mean()
    tau = np.concatenate([[0.0], np.cumsum(r[:-1])])
    i = np.clip(np.floor(tau).astype(int), 0, len(x) - 1)
    u = np.clip(tau - i, 0.0, 1.0)
    xp = np.pad(x, (1, 3))
    p0, p1, p2, p3 = xp[i], xp[i + 1], xp[i + 2], xp[i + 3]
    return p1 + 0.5 * u * (p2 - p0 + u * (2 * p0 - 5 * p1 + 4 * p2 - p3 + u * (3 * (p1 - p2) + p3 - p0)))


def turns(y, s0=S0, e0=E0):
    """(s, e) within half a period of s0 and e0, each where the tracker's step at the turn is smallest: at the end it
    plays frame e-1 twice (the step |y[e-1] - y[e-2]| from the straight line), at the start frame s once (2 |y[s+1] - y[s]|)."""
    h = int(RATE / F_ROOT / 2)
    s = s0 - h + int(np.argmin(np.abs(np.diff(y[s0 - h: s0 + h + 1]))))
    e = e0 - h + int(np.argmin(np.abs(np.diff(y[e0 - h - 1: e0 + h])))) + 1
    return s, e


def turn_steps(y, s, e):
    """The largest second difference of the loop as the tracker plays it through each turn (the end frame twice, the start
    frame once), in % of the loop's RMS, and the loop's own 99.9th percentile of it."""
    rms = np.sqrt(np.mean(y[s:e] ** 2)) + 1e-12
    own = np.percentile(np.abs(np.diff(y[s:e], 2)), 99.9)
    at_end = np.concatenate([y[e - 4:e], y[e - 1:e - 5:-1]])                # ... e-2 e-1 e-1 e-2 ...
    at_start = np.concatenate([y[s + 4:s:-1], y[s:s + 5]])                  # ... s+1 s s+1 ...
    return (100 * np.abs(np.diff(at_start, 2)).max() / rms, 100 * np.abs(np.diff(at_end, 2)).max() / rms, 100 * own / rms)


def drift_shape(t):
    """Seconds from the loop's middle over the loop (times the drift, the pitch falls through the loop), 0 before it but
    for the last RAMP s, which rise to the loop start's value (the reference's pitch before its loop sits at its loop's
    median; a step at the loop start would jump)."""
    ramp = np.clip((t - (START0 - RAMP)) / RAMP, 0.0, 1.0) * (START0 - 0.5 * (START0 + END0))
    return np.where(t < START0, ramp, t - 0.5 * (START0 + END0))


def pitch_track(y, f0=F_ROOT):
    """melodic's YIN pitch of `y` (44.1 kHz, as stored) at the reference's rate, 140 ms frames every 10 ms: (times, cents
    against f0, A#3 for ours), a reading an octave or two off folded back (an octave pair's frames read either), frames
    still over 300 c off out."""
    z = at_ref(y - np.mean(y))
    fl, hop = int(0.14 * REF_RATE), int(0.01 * REF_RATE)
    tt, cc = [], []
    for i in range(0, len(z) - fl, hop):
        f, ap = melodic.yin(z[i:i + fl], REF_RATE)
        if f and f > 0 and ap < 0.25:                                       # (YIN can return a negative f on a glitch)
            c = 1200 * math.log2(f / f0)
            c -= 1200 * round(c / 1200)
            if abs(c) < 300:
                tt.append((i + fl / 2) / REF_RATE)
                cc.append(c)
    return np.array(tt), np.array(cc)


def pitch_level(x):
    """Cents per frame that bring the take's own slow pitch before the loop to its loop's median (the reference's sits
    there): its pitch track's running median over 0.5 s (over the frames at hand near the ends: a blip at the onset does
    not spread), less the loop's median, taken off up to RAMP before the loop start and faded out over RAMP (nothing in
    the loop). Returns (cents, the largest offset taken off)."""
    tt, cc = pitch_track(x[:E0])
    loop = (tt >= START0) & (tt < END0)
    if loop.sum() < 5 or not np.any(tt < START0):                            # nothing to read it against: left as it is
        return np.zeros(len(x)), 0.0
    med = np.median(cc[loop])
    k = 51                                                                   # 0.5 s of 10 ms frames
    dev = np.array([np.median(cc[max(0, i - k // 2): i + k // 2 + 1]) for i in range(len(cc))]) - med   # the frames at hand
    t = np.arange(len(x)) / RATE
    fix = -np.interp(t, tt, dev) * np.clip((START0 - t) / RAMP, 0.0, 1.0)
    return fix, float(np.abs(fix).max())


def onset_gain(n, gap1, second):
    """The onset from silence: a raised cosine to `gap1` dB under full in ONSET1 s, then another to full over `second` s."""
    g = np.ones(n)
    g1 = 10 ** (-gap1 / 20)
    a, b = round(ONSET1 * RATE), round(second * RATE)
    g[:a] = g1 * (0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a))
    g[a:a + b] = g1 + (1 - g1) * (0.5 - 0.5 * np.cos(np.pi * np.arange(b) / b))
    return g


def chain(pre, noise, p, fix=0.0, fixed=False, onset=True):
    """The finished file from the band-limited take `pre` and the parameters `p` (vib: c peak to peak added in the loop,
    drift: c/s added through the loop, dev: the tremolo's amplitude in dB in the loop, slope: dB/s added through the
    loop, slope_pre: dB/s added before it (the two lines meet at the loop start), floor: the noise's level in dB against
    the level-shaped take's 10 ms level, or None, onset10: the onset's first stage's level, dB under full, onset: its
    second stage, s, early/early2/am1-am4: the tremolo's depth at the knots AM_T, fm1-fm4: the vibrato's at FM_T, both
    against their depth in the loop); `fix`: the pre-loop pitch levelling (cents per frame). fixed: return the file uncut
    with the loop's nominal place (the solve's readings), else cut at the chosen turns; onset=False: no onset gain (the
    onset's search applies it). Returns (y, s, e)."""
    t = np.arange(len(pre)) / RATE
    move = np.cos(2 * np.pi * F_MOVE * t)                                    # a crest on the onset, extrema on the turns
    x = pre
    if p["vib"] or p["drift"] or np.any(fix):
        vdepth = np.interp(t, FM_T, [p[k] for k in FM_KEYS] + [1.0])
        x = warp(pre, 0.5 * p["vib"] * move * vdepth + p["drift"] * drift_shape(t) + fix)
    depth = np.interp(t, AM_T, [p[k] for k in AM_AT] + [1.0])
    line = np.where(t < START0, p["slope_pre"] * t, p["slope_pre"] * START0 + p["slope"] * (t - START0))
    y = x * 10 ** ((p["dev"] * move * depth + line) / 20)
    if p["floor"] is not None:
        hop = RATE // 100
        env = np.sqrt(np.convolve(y * y, np.ones(hop) / hop, mode="same"))
        y = y + noise * env * 10 ** (p["floor"] / 20)
    if onset:
        y = y * onset_gain(len(y), p["onset10"], p["onset"])
    if fixed:
        return y, S0, E0
    s, e = turns(y)
    return y[:e], s, e


def floor_parts(y, s, e, f0=F_ROOT):
    """perchannel.floor_db of the loop at the reference's rate, split by band: (the whole reading, the part from the
    third-octave band holding the fundamental f0, the part from the bands above it), each in dB of the whole."""
    z = at_ref(y - np.mean(y[:e]))[round(s * REF_RATE / RATE): round(e * REF_RATE / RATE)]
    n = min(4096, 1 << int(math.log2(max(len(z), 256))))
    hop = n // 2
    P = np.zeros(n // 2 + 1)
    for i in range(max(1, (len(z) - n) // hop + 1)):
        seg = z[i * hop: i * hop + n]
        P += np.abs(np.fft.rfft(np.pad(seg, (0, n - len(seg))) * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1 / REF_RATE)
    whole = fund = above = tot = 0.0
    lo = 100.0
    while lo * 2 ** (1 / 3) < 0.9 * REF_RATE / 2:
        sel = (f >= lo) & (f < lo * 2 ** (1 / 3))
        if sel.sum() >= 3:
            v = min(np.median(P[sel]) * sel.sum(), P[sel].sum())
            whole += v
            if lo <= f0 < lo * 2 ** (1 / 3):
                fund += v
            elif lo > f0:
                above += v
            tot += P[sel].sum()
        lo *= 2 ** (1 / 3)
    db = lambda v: 10 * math.log10(v / tot + 1e-30)
    return db(whole), db(fund), db(above)


def reading(y, s, e, k):
    if k == "floor":
        return floor_parts(y, s, e)[2]
    if k in ("onset10", "onset"):
        return onset_means(y)[0 if k == "onset10" else 1]
    if k in ("early", "early2"):
        return early_ranges(y)[0 if k == "early" else 1]
    if k in AM_KEYS:
        return swings(y, PRE_CYCLES[AM_KEYS.index(k) - 1: AM_KEYS.index(k)])[0]
    if k in FM_KEYS:
        a, b = PRE_SPANS[FM_KEYS.index(k)]
        return pitch_spans(y[:int((b + 0.1) * RATE)], [(a, b)])[0]
    if k == "slope_pre":
        return pre_slope(y)
    v = char(y, s, e).get(READ[k])
    return 0.0 if v is None else v


def solve(pre, noise, own, fix):
    """The parameters, each only where the take's own reading falls short of the reference's, solved one at a time at the
    loop's nominal place with the others in place (bisection; three rounds): the movements on the file without its floor
    noise (shaped like the take, it sits at the partials, and its own wobble would read as movement; the reference's
    white floor reads as almost none), the floor's level on the file with them; the onset last (onset_search), then the
    vibrato's knots once more with it (the first pitch span's reading holds the onset). Returns (p, notes)."""
    need = {k: (own[k] < TARGET[k]) if k in ("vib", "dev", "onset10", "onset") else (own[k] > TARGET[k]) if k in (
            "drift", "slope", "slope_pre") else (own[k] < TARGET[k] - 0.05) if k == "floor" else None for k in TARGET}
    p = dict(vib=math.sqrt(max(0.0, TARGET["vib"] ** 2 - own["vib"] ** 2)) if need["vib"] else 0.0,
             drift=TARGET["drift"] - own["drift"] if need["drift"] else 0.0,
             dev=math.sqrt(2 * max(0.0, TARGET["dev"] ** 2 - own["dev"] ** 2)) if need["dev"] else 0.0,
             slope=TARGET["slope"] - own["slope"] if need["slope"] else 0.0,
             slope_pre=TARGET["slope_pre"] - own["slope_pre"] if need["slope_pre"] else 0.0,
             floor=-30.0 if need["floor"] else None, onset10=8.0, onset=0.005,
             early=0.1, early2=0.3, am1=0.5, am2=0.45, am3=0.4, am4=0.4, fm1=0.2, fm2=0.35, fm3=0.8, fm4=0.6)
    for k in AM_KEYS:                                # the depths before the loop, wherever a movement is added (their
        need[k] = bool(p["dev"])                     # readings include the take's own movement: the least depth that
    for k in FM_KEYS:                                # meets them)
        need[k] = bool(p["vib"])
    need["onset10"] = need["onset"] = False          # the onset's two stages: searched together last (onset_search)
    span = dict(vib=(0.0, 4 * TARGET["vib"]), drift=(-12.0, 6.0), dev=(0.0, 4 * TARGET["dev"]), slope=(-6.0, 3.0),
                slope_pre=(-6.0, 3.0), floor=(-70.0, 0.0), **{k: (0.0, 1.5) for k in AM_KEYS + FM_KEYS})
    def fit(k):
        lo, hi = span[k]
        for _ in range(16):                                                  # every reading rises with its parameter
            p[k] = 0.5 * (lo + hi)
            q = p if k == "floor" else {**p, "floor": None}                  # the movements read without the noise
            lo, hi = (p[k], hi) if reading(*chain(pre, noise, q, fix, True), k) < TARGET[k] else (lo, p[k])

    lifted = None
    for _ in range(3):
        for k in TARGET:
            if not need[k]:
                continue
            if k == "floor":                                                 # the movements' own sidebands can lift the
                base = reading(*chain(pre, noise, {**p, "floor": None}, fix, True), k)   # reading: no noise where
                if base >= TARGET[k]:                                        # they already reach the reference's
                    p[k], lifted = None, base
                    continue
                lifted = None
            fit(k)
    p["onset10"], p["onset"], got = onset_search(chain(pre, noise, p, fix, True, onset=False)[0])
    for k in FM_KEYS:                                # the pitch spans' first frames hold the onset: the vibrato's knots
        if need[k]:                                  # once more with the onset found
            fit(k)
    j = lambda keys: "/".join(f"{p[k]:.2f}" for k in keys)
    notes = [f"vibrato {own['vib']:.2f} c of its own" + (f", a {p['vib']:.2f} c cosine added, before the loop at {j(FM_KEYS)} "
                                                        f"of its loop depth at 0.2/0.8/1.6/2.4 s" if p["vib"] else
                                                        ", none added"),
             f"drift {own['drift']:+.2f} c/s of its own" + (f", {p['drift']:+.2f} added" if p["drift"] else ", none added"),
             f"level movement {own['dev']:.2f} dB of its own" + (f", a +-{p['dev']:.2f} dB cosine added" if p["dev"] else
                                                                 ", none added"),
             f"slope {own['slope']:+.2f} dB/s of its own" + (f", {p['slope']:+.2f} added" if p["slope"] else ", none added"),
             f"before the loop {own['slope_pre']:+.2f} dB/s of its own"
             + (f", {p['slope_pre']:+.2f} added" if p["slope_pre"] else ", none added"),
             f"floor between the partials {own['floor']:.2f} dB of its own" + (
                 f", noise {-p['floor']:.2f} dB under the 10 ms level" if p["floor"] is not None else
                 f", no noise (the movements lift it to {lifted:.2f})" if lifted is not None else ", no noise"),
             f"onset to -10/-3 dB of its settled level {own['onset10']:.1f}/{own['onset']:.1f} ms of its own, the two stages "
             f"searched together: the first to {-p['onset10']:.1f} dB in {1000 * ONSET1:.1f} ms, the second {1000 * p['onset']:.2f} "
             f"ms (reading {got[0]:.2f}/{got[1]:.2f})",
             f"level range over the first {EARLY[0]}/{EARLY[1]} s {own['early']:.2f}/{own['early2']:.2f} dB of its own"
             + (f", the tremolo before the loop at {p['early']:.2f} of its depth in the loop to {EARLY[0]} s, "
                f"{p['early2']:.2f} at {EARLY[1]} s, then {j(AM_KEYS[2:])} at 0.73/1.19/1.64/2.10 s (held to 2.32 s), "
                f"full from 2.43 s" if p["dev"] else "")]
    return p, notes


def onset_search(y0):
    """The onset's two stages for the file `y0` (uncut) without its onset gain: the pair whose onset_means come nearest
    TARGET's onset10 / onset (the sum of the squared misses, ms) over the whole grid (the first stage's level 0-20 dB under
    full every 0.25 dB, the second stage 0.5-18 ms every 0.125 ms; a tie goes to the least first-stage cut, then the
    shortest second stage). A coarse grid and a finer one around its best missed a take's best point: the readings are
    marginal (in some phases a block sits within 0.01 dB of a threshold) and many points tie. Read on the whole file at
    its nominal length, not a prefix: a prefix's FFT resample differs slightly from the whole file's, which moved the
    -10 dB reading of a 0.2 s prefix by a frame (0.107 ms). The final file is cut at its turn, up to half a period from
    E0, and its vibrato knots are refit after the search; on the five it reads the same, and the whole grid re-read that
    way picks the same pair. Returns (dB, s, (a10, a3))."""
    y0 = y0[:E0]
    g = np.ones(len(y0))
    n = int(0.04 * RATE)
    best = None
    for gap1 in np.arange(0.0, 20.01, 0.25):
        for second in np.arange(0.0005, 0.01801, 0.000125):
            g[:n] = onset_gain(n, gap1, second)
            got = onset_means(y0 * g)
            miss = (got[0] - TARGET["onset10"]) ** 2 + (got[1] - TARGET["onset"]) ** 2
            if best is None or miss < best[0]:
                best = (miss, float(gap1), float(second), got)
    return best[1], best[2], best[3]


def make(cand, raw, gain_db=0.0):
    x, r = mono(RAW / raw)
    assert r == RATE, f"{raw}: {r} Hz (the screens save 44.1 kHz)"
    x = highpass(x - np.mean(x))
    on = int(np.nonzero(np.abs(x) > np.abs(x).max() * 10 ** (-60 / 20))[0][0])
    x = x[max(0, on - int(0.001 * RATE)):]
    assert len(x) >= E0 + RATE // 2, f"{raw}: too short ({len(x) / RATE:.2f} s)"
    x, was = tune(x)
    raw_c = char(x)
    x = fir_filter(x, lowpass_fir(BAND_TOP / RATE))                          # nothing over the reference's Nyquist
    x, fc, slope, bw_pre, bw_post, cen = roll_off(x)
    fix, fix_max = pitch_level(x)
    own_c = char(x)
    own = {k: own_c.get(READ[k]) or 0.0 for k in READ}
    own["floor"] = floor_parts(x, S0, E0)[2]
    own["onset10"], own["onset"] = onset_means(x)
    own["early"], own["early2"] = early_ranges(x)[:2]
    own["slope_pre"] = pre_slope(x)
    f, S = envelope_spectrum(x[S0:E0], RATE)                                  # the floor's noise: the take's spectrum,
    noise = fir_filter(shaped_noise(len(x), RATE, f, S, seed=zlib.crc32(cand.encode())), lowpass_fir(BAND_TOP / RATE))
    noise = zpad_filter(noise, lambda fr: (fr >= FUND_EDGE).astype(float))    # none in its fundamental's band (but
                                                                             # what the level shaping folds back)
    noise /= np.sqrt(np.mean(noise[S0:E0] ** 2)) + 1e-12
    p, notes = solve(x, noise, own, fix)
    quiet = chain(x, noise, {**p, "floor": None}, fix, True)[0]              # what the movements were solved on
    y, s, e = chain(x, noise, p, fix)
    y *= 10 ** ((RMS_DB + gain_db) / 20) / np.sqrt(np.mean(y[s:e] ** 2))
    peak = np.abs(y).max()
    limited = peak > 10 ** (-1 / 20)                                         # a guard: GAIN keeps every file under it
    if limited:
        y *= 10 ** (-1 / 20) / peak
    pcm = np.clip(np.round(y * 32767), -32768, 32767).astype(int)
    write_wav(OUT / f"{cand}.wav", RATE, [pcm.tolist()], 16, loop=(s, e, True), root_note=ROOT_NOTE)
    report(cand, raw, pcm / 32767, s, e, was, raw_c, notes, (fc, slope, bw_pre, bw_post, cen), fix_max, limited, quiet)


def level_track(y, f0=F_ROOT):
    """The level (dB) of `y` (44.1 kHz, as stored) at the reference's rate, DC off: its mean square under a Hann window
    three periods of f0 long (its nulls fall on every multiple of f0, so the level does not beat with the waveform: the
    blocks' own level does, at our A#3 a block holds 1.155 periods, and a 20 ms Hann still beat 0.1-0.3 dB there where
    neighbouring partials sound) at the centres of melodic's 10 ms blocks, and the centres (s)."""
    z = at_ref(y - np.mean(y))
    h = int(REF_RATE * 0.01)
    w = np.hanning(int(round(3 * REF_RATE / f0)) + 1)
    ms = np.convolve(z * z, w / w.sum(), mode="same")
    n = len(z) // h
    return 10 * np.log10(ms[((np.arange(n) + 0.5) * h).astype(int)] + 1e-18), (np.arange(n) + 0.5) * h / REF_RATE


def pre_slope(y, start=START0, f0=F_ROOT):
    """The level's trend before the loop (dB/s): a line fitted to the level from 0.05 s to the loop start."""
    e, t = level_track(y, f0)
    sel = (t >= 0.05) & (t < start)
    return float(np.polyfit(t[sel], e[sel], 1)[0])


def early_ranges(y, f0=F_ROOT):
    """The level's range (dB) over the file's first EARLY s, from 25 ms (past the window's reach into the onset)."""
    e, t = level_track(y, f0)
    return [float(np.ptp(e[(t > 0.025) & (t < span)])) for span in EARLY]


def swings(y, starts, f0=F_ROOT):
    """The level's swing per tremolo cycle (1 / 2.2 s from each start): the level less its 1 s mean (over the blocks at hand
    near the file's ends), peak to peak."""
    e, t = level_track(y, f0)
    k = int(round(1.0 / (t[1] - t[0])))
    d = e - np.convolve(e, np.ones(k), mode="same") / np.convolve(np.ones_like(e), np.ones(k), mode="same")
    return [float(np.ptp(d[(t >= a) & (t < a + 1 / 2.2)])) for a in starts]


def pitch_spans(y, spans, f0=F_ROOT):
    """The pitch's movement over each span (2 sqrt 2 std of the detrended track, c: peak to peak for a sine)."""
    tt, cc = pitch_track(y, f0)
    out = []
    for a, b in spans:
        sel = (tt >= a) & (tt < b)
        if sel.sum() < 5:                                                    # too few voiced frames to read
            out.append(float("nan"))
            continue
        c = cc[sel] - np.polyval(np.polyfit(tt[sel], cc[sel], 1), tt[sel])
        out.append(float(2 * math.sqrt(2) * np.std(c)))
    return out


PRE_CYCLES = 0.05 + np.arange(5) / 2.2                    # the five tremolo cycles from 0.05 s
PRE_SPANS = ((0.0, 0.4), (0.4, 1.2), (1.2, 2.0), (2.0, 2.8))


def pre_loop(y, f0=F_ROOT):
    """The movements before the loop read as REF_PRE reads the reference's: the level's range over the first EARLY s, its
    swing in the five tremolo cycles from 0.05 s, the pitch's movement over PRE_SPANS."""
    return early_ranges(y, f0), swings(y, PRE_CYCLES, f0), pitch_spans(y, PRE_SPANS, f0)


def report(cand, raw, y, s, e, was, raw_c, notes, ro, fix_max, limited, quiet):
    c = char(y, s, e)
    a10, a3 = attack_means(y)
    o10, o3 = onset_means(y)
    st = turn_steps(y, s, e)
    fl = floor_parts(y, s, e)
    er, sw, sp = pre_loop(y)
    fc, slope, bw_pre, bw_post, cen = ro
    zs = at_ref(y - y.mean())[round(s * REF_RATE / RATE): round(e * REF_RATE / RATE)]
    P = np.abs(np.fft.rfft(zs * np.hanning(len(zs)))) ** 2
    fq = np.fft.rfftfreq(len(zs), 1 / REF_RATE)
    lo = 10 * np.log10(P[(fq > 0) & (fq < LO_HZ)].sum() / P[fq > 0].sum() + 1e-30)
    print(f"{cand} <- {raw}: {len(y) / RATE:.3f} s, ping-pong loop {s}-{e} ({s / RATE:.3f}-{e / RATE:.3f} s, "
          f"{(e - s) / RATE:.3f} s); tuned from {was:+.1f} c, its own pitch before the loop levelled to the loop's median "
          f"(at most {fix_max:.1f} c taken off); "
          + (f"roll-off from {fc:.0f} Hz at {slope:.1f} dB per octave: bw40/60 {bw_pre[0]:.0f}/{bw_pre[1]:.0f} -> "
             f"{bw_post[0]:.0f}/{bw_post[1]:.0f} Hz ({BW40:.0f}/{BW60:.0f}), centroid {cen[0]:.0f} -> {cen[1]:.0f} Hz"
             if slope else f"no roll-off (bw40/60 {bw_pre[0]:.0f}/{bw_pre[1]:.0f} Hz: not over the reference's "
             f"{BW40:.0f}/{BW60:.0f}, or no corner keeps the centroid)")
          + "; " + "; ".join(notes) + ("; PEAK-LIMITED" if limited else ""))
    print(f"    the take's own (tuned): floor {raw_c['floor_db']:.2f} dB, flatness {raw_c['flatness_db']:.2f}, aperiodicity "
          f"{raw_c.get('aperiodicity', 0):.2f}, centroid {raw_c['centroid_hz']:.0f} Hz ({raw_c['centroid_hz'] / F_ROOT:.2f} "
          f"partials), partials {raw_c.get('partials_db')}, odd/even {raw_c.get('odd_even_db', 0):+.1f} dB")
    print(f"    now (the reference's in brackets, DC off): attack {c['attack10_ms']:.0f}/{c['attack3_ms']:.0f} ms (0/10), "
          f"over the 93 phases {a10:.1f}/{a3:.1f} ms of the file's loudest block (1.1/8.1), {o10:.2f}/{o3:.2f} ms of its "
          f"settled level ({TARGET['onset10']:.2f}/{TARGET['onset']:.2f}); floor {fl[0]:.2f} dB = {fl[1]:.2f} in the band holding "
          f"the fundamental + {fl[2]:.2f} between the partials above it ({REF_FLOOR[0]:.2f} = {REF_FLOOR[1]:.2f} + "
          f"{REF_FLOOR[2]:.2f}), flatness {c['flatness_db']:.2f} (-25.26), aperiodicity {c.get('aperiodicity', 0):.2f} "
          f"(0.00), centroid {c['centroid_hz']:.0f} Hz = {c['centroid_hz'] / F_ROOT:.2f} partials moving "
          f"{c['centroid_move_hz']:.0f} (227 = 1.53, 34), bw40/60 {c['bw40_hz']:.0f}/{c['bw60_hz']:.0f} (2240/4694), level dev "
          f"{c.get('level_dev_db', 0):.2f} dB at {c.get('tremolo_hz', 0):.2f} Hz prom {c.get('tremolo_prominence', 0):.1f} "
          f"(3.61 at 2.17, 23.6), slope {c.get('level_slope_db_per_s', 0):+.2f} dB/s (-1.78), vibrato "
          f"{c.get('vibrato_depth_cents', 0):.2f} c at {c.get('vibrato_hz', 0):.2f} Hz prom {c.get('vibrato_prominence', 0):.1f} "
          f"(7.67 at 2.25, 7.1), drift {c.get('drift_cents_per_s', 0):+.2f} c/s (-3.06), pitch {c.get('pitch')} (melodic's "
          f"scientific naming: A#2 is our A#3)")
    j = lambda v: "/".join(f"{u:.1f}" for u in v)
    print(f"    before the loop: the level's trend {pre_slope(y):+.2f} dB/s ({TARGET['slope_pre']:+.2f}), its range over the "
          f"first {'/'.join(map(str, EARLY))} s {j(er)} dB ({j(REF_PRE[0])}), "
          f"its swing per tremolo cycle from 0.05 s {j(sw)} dB ({j(REF_PRE[1])}), the pitch's movement over "
          f"0-0.4/0.4-1.2/1.2-2.0/2.0-2.8 s {j(sp)} c ({j(REF_PRE[2])})")
    qc, (qer, qsw, qsp) = char(quiet), pre_loop(quiet)
    k = lambda v: "/".join(f"{u:.2f}" for u in v)
    print(f"    as solved (the file without its floor noise, the loop at its nominal place): over the loop vibrato "
          f"{qc.get('vibrato_depth_cents', 0):.2f} c, level dev {qc.get('level_dev_db', 0):.2f} dB; before the loop the "
          f"level's trend {pre_slope(quiet):+.2f} dB/s, its range over the first {'/'.join(map(str, EARLY))} s {k(qer)} dB, "
          f"its swing per tremolo cycle {k(qsw)} dB, the pitch's movement over the spans {k(qsp)} c")
    print(f"    turns, as the tracker plays them: the largest second difference through the start {st[0]:.2f} %, through the end "
          f"{st[1]:.2f} % of the loop's RMS (the loop's own 99.9th percentile {st[2]:.2f} %); under 104 Hz as played at the "
          f"lowest note {lo:.1f} dB of the loop; peak {20 * math.log10(np.abs(y).max() + 1e-12):.1f} dBFS")


# ------------------------------------------------------------------------------------------------ the pattern

PATTERNS = ["loop", "loop_b"]
FIGURE = ["B-4", "A-4", "C-5", "B-4", "E-4", "A-4"]        # bar 1, rows 0 2 4 6 10 14 (ours); the second glided into
FIG_ROWS = [0, 2, 4, 6, 10, 14]
GLIDE = "B-4"                                              # row 18: the held sixth glides on (G20) at the fade's v14
PICKUP = ["G-4", "A-4", "B-4"]                             # rows 58 60 62, faded out by loop_b's first rows
PICK_ROWS = [58, 60, 62]
ECHO = 3                                                   # rows later, v7 (v6 on the glide): -7.2 dB, the same pan
PAN = 32                                                   # the reference's notes carry its sample's default pan, 32
SCALE = 64 / 16                                            # the reference writes its sample's own volume, 16 (its default);
                                                           # ours is 64: every volume and fine slide x4, the same in dB
# the reference's written fades (volume column, row by row): the main from row 15 (v16) to silence on row 43, the echo
# from row 18 (v7) to silence on row 42; the glide's note row carries the fade's value (v14 main, v6 echo)
MAIN_FADE = {15: 16, 16: 15, 17: 15, 18: 14, 19: 13, 20: 13, 21: 12, 22: 12, 23: 12, 24: 11, 25: 10, 26: 10, 27: 9, 28: 8,
             29: 8, 30: 8, 31: 7, 32: 7, 33: 6, 34: 5, 35: 5, 36: 4, 37: 4, 38: 4, 39: 3, 40: 2, 41: 2, 42: 1, 43: 0}
ECHO_FADE = {18: 7, 19: 7, 20: 7, 21: 6, 22: 6, 23: 6, 24: 5, 25: 5, 26: 5, 27: 4, 28: 4, 29: 4, 30: 4, 31: 3, 32: 3,
             33: 3, 34: 3, 35: 3, 36: 2, 37: 2, 38: 2, 39: 1, 40: 1, 41: 1, 42: 0}
CHANNELS = (f"    - {{name: Second, pan: {PAN}, volume: 64}}\n"
            f"    - {{name: Second echo, pan: {PAN}, volume: 64}}\n")


def line_rows():
    """The main channel's notes in `loop` as (row, note), in order (the glided ones included)."""
    return list(zip(FIG_ROWS, FIGURE)) + [(18, GLIDE)] + list(zip(PICK_ROWS, PICKUP))


def figure(fuller=True):
    """`loop` the figure (the reference's fuller pattern, its orders 43 and 47: the held sixth glided on to a seventh on
    row 18, a pickup on rows 58-62), `loop_b` the pickup's fade; fuller=False gives `loop` as the reference's other
    pattern (its orders 41 and 45: the sixth held and faded, no glide, no pickup)."""
    v = lambda ref: f"v{round(ref * SCALE):02d}"                    # the reference's volumes at our sample's own volume
    cols = {p: [dict(), dict()] for p in PATTERNS}
    main, echo = cols["loop"]
    for r, ref in MAIN_FADE.items():
        main[r] = f"... .. {v(ref)}"
    for r, ref in ECHO_FADE.items():
        echo[r] = f"... .. {v(ref)}"
    for r, note in zip(FIG_ROWS, FIGURE):
        main[r] = f"{note} .. {v(16)} G54" if r == 2 else f"{note} 15 {v(16)}"
        echo[r + ECHO] = f"{note} .. {v(7)} G54" if r == 2 else f"{note} 15 {v(7)}"
    if fuller:
        main[18], echo[18 + ECHO] = f"{GLIDE} .. {v(14)} G20", f"{GLIDE} .. {v(6)} G20"
        for r, note in zip(PICK_ROWS, PICKUP):
            main[r] = f"{note} 15 {v(16)}"
    tail, _ = cols["loop_b"]                                         # the pickup faded by the next pattern's first rows
    tail[0] = f"... .. ... DF{round(2 * SCALE):X}"
    for r in range(1, 8):
        tail[r] = "... .. ... D00"
    return cols


def close(pickup):
    """Channels 25-26 in the form's pattern after a line pattern: the pickup's fade (after the fuller pattern), then a cut
    on both channels, silent by then (the held notes faded to 0 by rows 42-43; the app's SOUNDING table follows cuts, not
    the volume column)."""
    main, echo = (figure()["loop_b"][0].copy() if pickup else {}), {}
    at = max(main) + 1 if main else 0
    main[at] = echo[at] = "^^^"
    return [main, echo]


def pattern(path=HERE / "rift.yaml", first_sample="second_placeholder.wav"):
    b = path.read_bytes()
    crlf = b"\r\n" in b
    t = b.decode("utf-8").replace("\r\n", "\n")
    t = ensure_channels(t, CHANNELS, r"    - \{name: Vocal[^\n]*\n")       # the owner's lines stay
    line = re.search(r"\n  15: \{file:[^\n]*\n", t)
    if not line:
        new = (f"  15: {{file: ../../samples/local/rift-cand/{first_sample}, base_note: {BASE_NOTE}, loop: from_wav, "
               f"name: {Path(first_sample).stem}}}\n")
        anchor = "\n\ninstruments:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + new + "\ninstruments:\n", 1)
    else:                                                      # the picked file stays; the stored note is the generator's
        fixed = re.sub(r"base_note: [A-G][-#]\d", f"base_note: {BASE_NOTE}", line.group(0))
        t = t[:line.start()] + fixed + t[line.end():]
    if "\n  15: {name: Second" not in t:
        ins = "  15: {name: Second, sample: 15}   # sample mode, as in the reference: the fades and glides are in the pattern\n"
        anchor = "\n\npatterns:\n"
        assert t.count(anchor) == 1
        t = t.replace(anchor, "\n" + ins + "\npatterns:\n", 1)
    t = write_columns(t, 24, figure())
    if crlf:
        t = t.replace("\n", "\r\n")
    path.write_bytes(t.encode("utf-8"))
    print(f"wrote channels 25-26 into {path.name}: {' '.join(FIGURE)} > {GLIDE}, pickup {' '.join(PICKUP)}; echo +{ECHO} rows "
          f"v7, pan {PAN}; sample 15 at {BASE_NOTE}")


def reference():
    x, r = ref_wav()
    for label, v in (("melodic, DC included", x), (f"DC off ({x.mean():+.4f})", x - x.mean())):
        c = melodic.character(v, r, ("pingpong",) + sm.REF_LOOP)
        print(f"reference at {r} Hz, {label}:", ", ".join(f"{k} {c[k]:.2f}" for k in sm.REF if isinstance(c.get(k), float)))
    y = sm.fft_resample(x - x.mean(), int(round(len(x) * RATE / r)))       # the chain ours go through, on the reference
    s, e = round(sm.REF_LOOP[0] * RATE / r), round(sm.REF_LOOP[1] * RATE / r)
    c = char(y, s, e)
    a10, a3 = attack_means(y)
    o10, o3 = onset_means(y, sm.REF_F0)
    print(f"the reference through 44.1 kHz and char(): centroid {c['centroid_hz']:.2f}, level dev {c['level_dev_db']:.2f}, "
          f"slope {c['level_slope_db_per_s']:+.2f}, floor {c['floor_db']:.2f}, flatness {c['flatness_db']:.2f}, bw40/60 "
          f"{c['bw40_hz']:.0f}/{c['bw60_hz']:.0f}, vibrato {c.get('vibrato_depth_cents', 0):.2f} c; attack means over the 93 "
          f"phases {a10:.2f}/{a3:.2f} ms against its loudest block, {o10:.4f}/{o3:.4f} ms against its settled level (one "
          f"period at {1000 * BASE_AT:.0f} ms: TARGET's onset10/onset); its turns' steps "
          f"{', '.join(f'{v:.2f}' for v in turn_steps(y, s, e))} % (start, end, the loop's own)")
    fl = floor_parts(y, s, e, sm.REF_F0)
    er, sw, sp = pre_loop(y, sm.REF_F0)
    loop_sw = swings(y, np.arange(sm.REF_LOOP[0] / r, sm.REF_LOOP[1] / r - 1 / 2.2, 1 / 2.2), sm.REF_F0)
    loop_sp = pitch_spans(y, [(sm.REF_LOOP[0] / r, sm.REF_LOOP[1] / r)], sm.REF_F0)[0]
    j = lambda v: " ".join(f"{u:.2f}" for u in v)
    print(f"its floor {fl[0]:.2f} dB = {fl[1]:.2f} in the band holding its fundamental + {fl[2]:.2f} above it; before its "
          f"loop (level_track: a Hann-weighted level over three periods) the level's trend "
          f"{pre_slope(y, sm.REF_LOOP[0] / r, sm.REF_F0):+.2f} dB/s, "
          f"its range over the first {'/'.join(map(str, EARLY))} s from 25 ms {j(er)} dB, the swing per tremolo cycle from "
          f"0.05 s {j(sw)} dB, in the cycle from 2.32 s {swings(y, [2.32], sm.REF_F0)[0]:.2f} (in its loop {j(loop_sw)}, mean "
          f"{np.mean(loop_sw):.2f}), the pitch's movement over 0-0.4/0.4-1.2/1.2-2.0/2.0-2.8 s {j(sp)} c (its loop "
          f"{loop_sp:.2f})")
    b = round(0.002 * RATE)
    lv = lambda a, c: 10 * math.log10(np.mean(y[a:c] ** 2) + 1e-20)
    print("its onset in 2 ms blocks against its 10-20 ms level (a 2 ms block reads the waveform's phase):",
          " ".join(f"{lv(i * b, (i + 1) * b) - lv(round(0.01 * RATE), round(0.02 * RATE)):.1f}" for i in range(5)))
    print(f"ours: the loop {START0:.3f}-{END0:.3f} s nominal ({S0}-{E0} frames), the movements' line {F_MOVE:.4f} Hz")


if __name__ == "__main__":
    if sys.argv[1:2] == ["pattern"]:
        pattern(first_sample=next(iter(CANDS), "second_placeholder") + ".wav")
    elif sys.argv[1:2] == ["ref"]:
        reference()
    else:
        for cand, raw in CANDS.items():
            if not sys.argv[1:] or cand in sys.argv[1:]:
                make(cand, raw, GAIN.get(cand, 0.0))
