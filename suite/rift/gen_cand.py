"""Rift, step 1: the candidate sounds for the two-bar loop (drums, sub, bass stab), written to samples/local/rift-cand/
(scratch, not in the repository; the picks move to samples/rift/ once chosen). Nothing here is measured from or
matched to the reference: the roles come from BRIEF.md, the sounds from the Big Rusty kit (CC0), the TR-8 hits of
MusicRadar's royalty-free pack (fine in songs, not redistributable as samples), Surge XT and plain synthesis.
- Breaks: one 16-row bar at the song's grid (tempo 110, speed 4 = 165 BPM), our own two-step played by the kit through
  demo4/gen_break.py's hit mixing, in four treatments: roomy, dull (5.5 kHz wide, compressed), rimshot, far (overheads).
- Hats and crashes: kit and TR-8 hits.
- Subs: a kick's attack crossfaded, in phase, into a looped cycle at A-2 (55 Hz); the loop is 11 whole cycles (8820
  frames), so it is in tune. Four attacks and cycle shapes.
- Stabs, sounding A-3: the Surge XT finalists of cand.yaml (the shortest and noisiest) and one made of noise and a
  driven tone.
The tonal samples get a noise floor (suite/nadir/gen_floor.py's add_floor) so none is chiptune-clean.
Step 2 (`beds`, `lines`, `hooks`, `calls`): the floor for the finalists rendered by bedfin.yaml, linefin.yaml, hooks.yaml
and callfin.yaml; lines, hooks and calls are also tuned (some voices play 12-18 cents off): a held note's pitch is
measured (a line's loop, a hook's first note, a call's held C-5) and the WAV's rate set so it is exact.
Run: python -m vulturetracker synth suite/rift/cand.yaml && python suite/rift/gen_cand.py          (step 1)
     python -m vulturetracker synth suite/rift/bedfin.yaml && python suite/rift/gen_cand.py beds    (step 2, bed)
     python -m vulturetracker synth suite/rift/linefin.yaml && python suite/rift/gen_cand.py lines  (step 2, line)
     python -m vulturetracker synth suite/rift/hooks.yaml && python suite/rift/gen_cand.py hooks     (step 2, calls)
     python -m vulturetracker synth suite/rift/callfin.yaml && python suite/rift/gen_cand.py calls   (step 2, calls 3)
     python suite/rift/gen_cand.py calls call_a call_b   (only those: after `synth --only`, so the rest keep one floor)
"""
import shutil
import sys
from pathlib import Path

import numpy as np
from pedalboard import Compressor, HighpassFilter, LowpassFilter, Pedalboard, Reverb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "suite" / "nadir"))
import demo4.gen_break as gb  # noqa: E402
from vulturetracker.wavload import read_wav, write_wav  # noqa: E402
import gen_drums as gd  # noqa: E402  (Nadir's load, fx and save)
from gen_floor import add_floor  # noqa: E402

RATE = 44100
OUT = gd.OUT = ROOT / "samples" / "local" / "rift-cand"
TR8 = ROOT / "tools" / "royalty-free" / "musicradar-drum-machines" / "Drum Hardware" / "Hits" / "Roland TR-8"
TEMPO, SPEED = 110, 4
ROW = SPEED * int(RATE * 2.5 / TEMPO + 0.5)          # 4008 frames: the player's row (its tick is a whole number of frames)
BAR = 16 * ROW                                        # 64128 frames = 1.454 s


def late(row):
    """A light push: beats on the grid, 8ths 6 ms late, 16ths 8 ms late."""
    return 0 if row % 4 == 0 else 6 if row % 2 == 0 else 8


# Our bar (16 rows, 4 a beat): the two-step, kicks on 0 and 10 and snares on 4 and 12; ghost snares on 2, 7 and 14;
# hats on the 8ths, softer off the beat, and a 16th pickup on 11. (row, drum, dB under the drum's hardest hit)
HITS = ([(0, "kick", 0), (10, "kick", -2), (4, "snare", 0), (12, "snare", 0),
         (2, "ghost", -16), (7, "ghost", -12), (14, "ghost", -14), (11, "hat", -15)]
        + [(r, "hat", -8 if r % 4 == 0 else -12) for r in range(0, 16, 2)])
BASE = {"kick": [("kick_24/kick/kick", 0), ("kick_24/kick/oh", -6)],
        "snare": [("snare_14/center/top", 0), ("snare_14/center/oh", -6)],
        "ghost": [("snare_14/center/top", 0), ("snare_14/center/oh", -6)],
        "hat": [("hihat_14/cl/cl", 0)]}
OVER = {"kick": [("kick_24/kick/oh", 0), ("kick_24/kick/kick", -8)],
        "snare": [("snare_14/center/oh", 0), ("snare_14/center/top", -8)],
        "ghost": [("snare_14/center/oh", 0), ("snare_14/center/top", -8)]}
BREAKS = {  # name: (mics changed from BASE, room, more effects, stored rate)
    "room": ({}, Reverb(room_size=0.4, damping=0.5, wet_level=0.3, dry_level=0.7, width=0.0), [], 22050),
    "dull": ({}, Reverb(room_size=0.4, damping=0.6, wet_level=0.28, dry_level=0.72, width=0.0),
             [LowpassFilter(cutoff_frequency_hz=4500), Compressor(threshold_db=-18, ratio=3, attack_ms=5, release_ms=80)], 11025),
    "rim": ({"snare": [("snare_14/rimshot/top", 0), ("snare_14/rimshot/oh", -6)]},
            Reverb(room_size=0.25, damping=0.5, wet_level=0.22, dry_level=0.78, width=0.0), [], 22050),
    "far": (OVER, Reverb(room_size=0.65, damping=0.45, wet_level=0.4, dry_level=0.62, width=0.0), [], 22050),
}


def breaks():
    for name, (mics, room, more, rate) in BREAKS.items():
        gb.DRUMS.update(BASE, **mics)
        x = np.zeros(2 * BAR + 2 * RATE)
        counts = {}
        for rep in range(2):                          # twice: the first bar's room rings under the kept bar's downbeat
            for row, drum, db in HITS:
                counts[drum] = n = counts.get(drum, 0) + 1
                y = gb.hit(drum, db, n)
                at = rep * BAR + round(row * ROW + late(row) * RATE / 1000)
                x[at:at + len(y)] += y[: len(x) - at]
        y = Pedalboard([room, *more])(x[np.newaxis, :].astype(np.float32), RATE)[0][BAR: 2 * BAR].astype(np.float64)
        gd.save(f"break_{name}", y, rate, loop=(0, len(y), False), max_s=None)
    gb.DRUMS.update(BASE)
    print(f"breaks: {BAR} frames at 44.1 kHz = 16 rows of {ROW}; the row-10 kick is at O{(10 * ROW - 128) // 256:02X}")


def hats():
    gb.DRUMS.update(hattip=[("hihat_14/tc/cl", 0)], hathalf=[("hihat_14/ho/cl", 0)])
    gb.BANDS.update(hattip=(2000, 10000), hathalf=(2000, 10000))
    for name, drum, secs in (("hat_rusty_closed", "hat", 0.25), ("hat_rusty_tip", "hattip", 0.3)):
        h = gb.hit(drum, -8, 1)
        n = min(len(h), round(secs * RATE))
        gd.save(name, h[:n] * np.linspace(1, 0, n) ** 0.3, 22050)
    gd.save("hat_rusty_half", gd.fx(gb.hit("hathalf", -8, 1), HighpassFilter(cutoff_frequency_hz=500), tail=0.2), 22050, max_s=0.6)
    gd.save("hat_tr8_closed", gd.fx(gd.load(TR8 / "Tr-8 Closed Hat 02.wav"), gd.ROOM, tail=0.3), 22050, max_s=0.6)
    gd.save("hat_tr8_open", gd.load(TR8 / "Tr-8 Open Hat 01.wav"), 22050, max_s=0.6)


def crashes():
    hp = HighpassFilter(cutoff_frequency_hz=300)
    gd.save("crash_rusty", gd.fx(gb.hit("crash", -3, 1), hp), 22050, max_s=4.0)
    for k in (1, 2):
        gd.save(f"crash_tr8_{k}", gd.fx(gd.load(TR8 / f"Tr-8 Crash 0{k}.wav"), hp), 22050, max_s=4.0)


F0 = 55.0                                            # A-2
LOOP_N = round(11 * RATE / F0)                       # 8820 frames: 11 whole cycles, so the loop is exactly periodic


def sub(name, attack, shape, secs, level=0.6, xfade_ms=30, floor=-30):
    """The attack's first `secs` (peak 1) crossfaded into `shape` at 55 Hz, phased to the attack's own 55 Hz component
    over the crossfade so the join does not dip; the last 11 cycles loop."""
    a = attack[: round(secs * RATE)]
    a = a / np.abs(a).max()
    nx = round(xfade_ms * RATE / 1000)
    t = np.arange(len(a) + 2 * LOOP_N) / RATE
    seg = slice(len(a) - nx, len(a))
    phase = np.angle(np.sum(a[seg] * np.exp(-2j * np.pi * F0 * t[seg]))) + np.pi / 2
    w = np.concatenate([np.ones(len(a) - nx), np.linspace(1, 0, nx), np.zeros(2 * LOOP_N)])
    y = np.pad(a, (0, 2 * LOOP_N)) * w + level * shape(2 * np.pi * F0 * t + phase) * (1 - w)
    gd.save(name, y, RATE, root="A-2", loop=(len(y) - LOOP_N, len(y), False), max_s=None)
    add_floor(OUT / f"{name}.wav", floor)


def subs():
    gb.DRUMS.update(kickclose=[("kick_24/kick/kick", 0)])
    gb.BANDS.update(kickclose=(40, 150))
    sub("sub_rusty", gb.hit("kick", 0, 1), lambda p: np.sin(p) + 0.125 * np.sin(2 * p), 0.07, floor=-32)
    sub("sub_tr8", gd.load(TR8 / "Tr-8 Kick 01.wav"), lambda p: np.sin(p) + 0.3 * np.sin(2 * p), 0.12, xfade_ms=40)
    sub("sub_round", gb.hit("kickclose", 0, 1), lambda p: np.sin(p) - np.sin(3 * p) / 9 + np.sin(5 * p) / 25, 0.09, floor=-28)
    # the 808 way: one sine whose pitch falls from 150 Hz to 55 Hz in 60 ms, driven, with a 4 ms click
    nd = round(0.06 * RATE)
    t = np.arange(nd + 3 * LOOP_N) / RATE
    f = np.full(len(t), F0)
    f[:nd] = F0 + (150 - F0) * (1 - t[:nd] / t[nd]) ** 2
    y = np.tanh(1.8 * np.sin(2 * np.pi * np.cumsum(f) / RATE)) / np.tanh(1.8)
    y += 0.3 * np.random.default_rng(1).standard_normal(len(t)) * np.exp(-t / 0.004)
    gd.save("sub_808", y, RATE, root="A-2", loop=(len(y) - LOOP_N, len(y), False), max_s=None)
    add_floor(OUT / "sub_808.wav", -30)


def stabs():
    for name in ("distorted", "helmeto", "static2", "dist1"):  # the Surge XT finalists of cand.yaml
        dst = OUT / f"stab_{name}.wav"
        shutil.copyfile(OUT / "stab" / f"{name}.wav", dst)
        add_floor(dst, -24)
    n = round(0.45 * RATE)
    t = np.arange(n) / RATE
    tone = np.tanh(1.5 * (np.sin(2 * np.pi * 110 * t) + 0.5 * np.sin(2 * np.pi * 220 * t)))
    noise = Pedalboard([HighpassFilter(cutoff_frequency_hz=120), LowpassFilter(cutoff_frequency_hz=1500)])(
        np.random.default_rng(7).standard_normal(n)[np.newaxis, :].astype(np.float32), RATE)[0].astype(np.float64)
    env = (1 - np.exp(-t / 0.003)) * np.exp(-t / 0.12)
    gd.save("stab_noise", (0.7 * tone + 0.6 * noise / np.abs(noise).max()) * env, RATE, root="A-3", max_s=None)


FLOORS = {"beds": ("bed_", -26), "lines": ("line_", -28), "hooks": ("hook_", -28),  # bedfin, linefin, hooks.yaml
          "calls": ("call_", -24)}                   # callfin.yaml: within the reference's -8 to -24 dB between partials
# each hook's first held note: Hz, and the span in beats to measure it over (the chord: its E, the strongest partial,
# over the stab and its echoes, which repeat it at the same pitch; 90 ms of the stab alone measured 26 cents off)
HOOKS = {"hook_two": (220.0, (0.3, 1.4)), "hook_fall": (329.63, (0.3, 1.4)), "hook_chord": (164.81, (0.05, 4.0)),
         "hook_swell": (220.0, (2.0, 5.5)), "hook_vox": (220.0, (1.0, 2.8))}


def tune(p, f_ref=None, beats=None, harmonics=1, centre=False):
    """Measure a held note (a line's loop, tiled; or `beats`, a (from, to) span of a hook's first note, at 165 BPM): the
    peak within half a semitone of `f_ref` (default: the root) interpolated, or the strongest of the first `harmonics`
    partials (a voice whose fundamental is weak), or with `centre` the power-weighted centre of those partials, each
    within 45 cents (a stack of detuned voices: Jim's sat at 0, +11 and +21 cents, its strongest peak on the lowest),
    then rewrite the WAV at the rate that puts it there; the song compiles every sample to 44.1 kHz, so the rate only sets
    the tuning."""
    w = read_wav(p)
    x = np.asarray(w.channels[0], float) / 32768
    f_ref = f_ref or 440 * 2 ** ((w.root - 69) / 12)
    if beats:
        y = x[round(beats[0] * 60 / 165 * w.rate): round(beats[1] * 60 / 165 * w.rate)]
    else:
        y = np.tile(x[w.loops[0][0]: w.loops[0][1]], 8)
    n = 1 << 20
    P = np.abs(np.fft.rfft(y * np.hanning(len(y)), n)) ** 2
    f = np.fft.rfftfreq(n, 1 / w.rate)
    if centre:
        num = den = 0.0
        for h in range(1, harmonics + 1):
            sel = (f > h * f_ref * 2 ** (-45 / 1200)) & (f < h * f_ref * 2 ** (45 / 1200))
            wts = np.clip(P[sel] - np.median(P[(f > h * f_ref * 0.9) & (f < h * f_ref * 1.1)]), 0, None)
            num, den = num + (wts * np.log2(f[sel] / (h * f_ref))).sum(), den + wts.sum()
        f0 = f_ref * 2 ** (num / den)
    else:
        h, k = max(((h, np.argmax(P * ((f > h * f_ref * 2 ** (-0.5 / 12)) & (f < h * f_ref * 2 ** (0.5 / 12)))))
                    for h in range(1, harmonics + 1)), key=lambda hk: P[hk[1]])
        a, b, c = np.log(P[k - 1:k + 2])
        f0 = (k + 0.5 * (a - c) / (a - 2 * b + c)) * w.rate / n / h
    rate = round(w.rate * f_ref / f0)
    loop = {"loop": (w.loops[0][0], w.loops[0][1], False)} if w.loops else {}
    write_wav(p, rate, [np.asarray(w.channels[0]).tolist()], 16, root_note=w.root, **loop)
    how = f" (centre of partials 1-{harmonics})" if centre else f" (partial {h})" if harmonics > 1 else ""
    print(f"{p.name}: {1200 * np.log2(f0 / f_ref):+.1f} cents{how} -> rate {rate}")


def floors(group, names=()):
    prefix, db = FLOORS[group]
    for p in sorted(OUT.glob(f"{prefix}*.wav")):      # fresh renders only: running twice adds the floor twice
        if names and p.stem not in names:
            continue
        add_floor(p, db)
        if group == "lines":
            tune(p)
        elif group == "hooks":
            tune(p, *HOOKS[p.stem])
        elif group == "calls":                        # the held C-5 from 0.15 to 1.0 s, the centre of partials 1-6
            tune(p, 261.63, (0.4, 2.75), harmonics=6, centre=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    if sys.argv[1:2] and sys.argv[1] in FLOORS:
        floors(sys.argv[1], sys.argv[2:])
    else:
        breaks()
        hats()
        crashes()
        subs()
        stabs()
