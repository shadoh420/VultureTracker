"""Sample sources computed in numpy, for recipes (SAMPLING.md):

- sfxr: DrPetter's sfxr (MIT), its seven generators reproducible by seed, rendered at its own eight sub-steps per
  frame and resampled;
- drum: Paul Kellett's DrumSynth 2.0 (MIT): tone, noise, overtones, two noise bands, distortion and filter as YAML, or
  a .ds file;
- wave: one looped cycle of a chip or drawn waveform (pulse, saw, square, triangle, the NES triangle's 4-bit steps, an
  LFSR noise period, a Game Boy wave table, any table), summed from its harmonics under a ceiling so it is band-limited
  by construction and the loop is exact;
- additive: Nasca Octavian Paul's PADsynth (public domain): harmonics as Gaussian bands, random phases, one inverse FFT,
  an exact loop;
- mip: per-step copies of any source, each band-limited for the keys it serves and stored at a rate to match, with the
  `samples:`/`keymap:` blocks to paste into a song;
- a Hydrogen drum kit (.h2drumkit) read for `file:`: its drumkit.xml, one instrument's layer and its gains.
"""
import math

import numpy as np

SOURCES = ("wave", "sfxr", "drum", "additive")  # recipe keys rendered here
WAVE_KEYS = {"shape": None, "duty": 0.5, "table": None, "frames": None, "short": False, "ceiling": 18000.0}
WAVE_SHAPES = ("pulse", "saw", "square", "triangle", "tri4", "lfsr", "gb", "table")
MIP_KEYS = {"octaves": 3, "ceiling": 18000.0, "step": 12}


class SourceError(ValueError):
    pass


def hz(note):
    """A tracker note number's frequency (C-5 = 60 = MIDI middle C, A-5 = 440 Hz)."""
    return 440.0 * 2 ** ((note - 69) / 12)


def _keys(spec, allowed, what):
    if not isinstance(spec, dict):
        raise SourceError(f"{what} is a mapping of {', '.join(allowed)}; got {spec!r}")
    bad = set(spec) - set(allowed)
    if bad:
        raise SourceError(f"{what}: unknown keys {sorted(bad)} (allowed: {', '.join(allowed)})")
    return {**allowed, **spec}


def _lfsr(short):
    """One period of the NES noise channel's 15-bit LFSR as +-1: feedback from bits 0 and 1 (32767 steps), or from
    bits 0 and 6 in its short mode (93 steps from the power-on state)."""
    reg, tap, out = 1, 6 if short else 1, []
    while True:
        out.append(1.0 if reg & 1 else -1.0)
        reg = (reg >> 1) | (((reg ^ (reg >> tap)) & 1) << 14)
        if reg == 1:
            return np.array(out)


def _steps(w):
    """The cycle as a step table (each entry one equal step), or None for a shape with a closed form."""
    shape, frames = w["shape"], w["frames"]
    if shape == "tri4":  # the NES triangle: 32 steps of 4 bits, 15 down to 0 and back up
        return (np.r_[np.arange(15, -1, -1), np.arange(16)] - 7.5) / 7.5
    if shape == "lfsr":
        return _lfsr(bool(w["short"]))
    if shape in ("gb", "table"):
        t = w["table"]
        if not isinstance(t, list) or len(t) < 2 or not all(isinstance(v, (int, float)) for v in t):
            raise SourceError(f"wave: {shape} needs table: a list of two numbers or more")
        t = np.asarray(t, float)
        if shape == "gb":  # the Game Boy's wave channel: 32 samples of 4 bits
            if len(t) != 32 or t.min() < 0 or t.max() > 15 or (t != np.round(t)).any():
                raise SourceError("wave: gb's table is 32 whole numbers 0-15")
            return (t - 7.5) / 7.5
        lo, hi = t.min(), t.max()
        return (t - (lo + hi) / 2) / ((hi - lo) / 2 or 1)
    if frames is None:
        return None
    n = int(frames)
    if not 2 <= n <= 65536:
        raise SourceError(f"wave: frames is 2-65536 steps per cycle; got {frames}")
    return _shape_at((np.arange(n) + 0.5) / n, shape, w["duty"])


def _shape_at(t, shape, duty):
    """The ideal shape at phases `t` (0-1)."""
    if shape == "saw":
        return 2 * t - 1
    if shape in ("pulse", "square"):
        return np.where(t < (0.5 if shape == "square" else duty), 1.0, -1.0)
    return 1 - 4 * np.abs(((t + 0.25) % 1) - 0.5)  # triangle, rising through 0 at t = 0


def _coefficients(w, steps, h):
    """Complex Fourier coefficients c_h (x(t) = sum 2 Re c_h e^(2 pi i h t)) of the cycle for harmonics `h`."""
    if steps is not None:  # a staircase: the table's DFT, each step held (sinc) and centred half a step on
        n = len(steps)
        return np.fft.fft(steps)[h % n] / n * np.exp(-1j * np.pi * h / n) * np.sinc(h / n)
    shape = w["shape"]
    if shape == "saw":
        return 1j / (np.pi * h)
    if shape in ("pulse", "square"):
        d = 0.5 if shape == "square" else float(w["duty"])
        return (1 - np.exp(-2j * np.pi * h * d)) / (1j * np.pi * h)
    odd = h % 2 == 1  # triangle
    return np.where(odd, -4j / (np.pi ** 2 * h ** 2) * (-1.0) ** ((h - 1) // 2), 0)


def _cycles(f0, rate, most=64):
    """(cycles, frames): the fewest whole cycles that fit whole frames within 0.1 cent, or the closest within `most`."""
    best = None
    for k in range(1, most + 1):
        n = max(2, round(k * rate / f0))
        cents = abs(1200 * math.log2(n * f0 / (k * rate)))
        if best is None or cents < best[0] - 1e-9:
            best = (cents, k, n)
        if cents < 0.1:
            break
    return best[1], best[2]


def wave(spec, root, rate, ceiling=None):
    """The `wave:` source: (1 x frames float array, (0, frames, False) loop, label). One period of the shape, or the
    fewest that keep it in tune, summed from the harmonics at or under `ceiling` Hz (the spec's, unless a mip copy
    passes its own) and under half the rate; no DC. An lfsr or table cycle is the table's steps, one sample each for an
    lfsr (its period at the recipe's rate, the root only naming the pitch it plays at)."""
    w = _keys(spec, WAVE_KEYS, "wave")
    if w["shape"] is None:
        w["shape"] = "table" if w["table"] is not None else "pulse"
    if w["shape"] not in WAVE_SHAPES:
        raise SourceError(f"wave: shape is one of {', '.join(WAVE_SHAPES)}; got {w['shape']!r}")
    if not 0 < float(w["duty"]) < 1:
        raise SourceError(f"wave: duty is between 0 and 1; got {w['duty']}")
    top = float(w["ceiling"] if ceiling is None else ceiling)
    if not 20 <= top:
        raise SourceError(f"wave: ceiling is in Hz, 20 or more; got {top}")
    steps = _steps(w)
    if w["shape"] == "lfsr":
        k, n = 1, len(steps)
    else:
        k, n = _cycles(hz(root), rate)
    hmax = int(min(top * n / (k * rate), (n // 2) / k))  # harmonic h sits in bin k*h at k*h*rate/n Hz
    if hmax < 1:
        raise SourceError(f"wave: no harmonic of {hz(root):.1f} Hz is under {top:.0f} Hz")
    h = np.arange(1, hmax + 1)
    spectrum = np.zeros(n // 2 + 1, complex)
    spectrum[k * h] = _coefficients(w, steps, h) * n
    x = np.fft.irfft(spectrum, n)
    label = f"wave {w['shape']}" + (f" ({k} cycles)" if k > 1 else "")
    return x[None, :], (0, n, False), label


def mip_plan(spec, rate, root):
    """`mip:` -> [(copy, rate, ceiling Hz, lowest key, highest key)]: copy 0 serves every key up to root + step - 1,
    copy c the keys from root + c * step, the boundary key going to the narrower copy; each is band-limited so its
    highest key lifts it to the ceiling, and stored at twice that width (so the resampler's own low-pass makes it)."""
    m = _keys(spec if spec is not True else {}, MIP_KEYS, "mip")
    octaves, step, top = int(m["octaves"]), int(m["step"]), float(m["ceiling"])
    if not 1 <= octaves <= 8 or not 1 <= step <= 24 or not 1000 <= top <= 24000:
        raise SourceError(f"mip: octaves 1-8, step 1-24 semitones, ceiling 1000-24000 Hz; got {m}")
    plan = []
    for c in range(octaves + 1):
        lo, hi = (0 if c == 0 else root + c * step), root + (c + 1) * step - 1
        if lo > 119:
            break
        width = top / 2 ** ((hi - root) / 12)
        plan.append((c, max(1000, round(2 * width)), width, lo, min(hi, 119)))
    return plan


def mip_blocks(copies, name):
    """The `samples:` and `keymap:` YAML to paste for [(file path text, root note text, lowest, highest)]."""
    from .notation import format_note
    lines = ["samples:                    # renumber to free slots"]
    for i, (file, base, _, _) in enumerate(copies, 1):
        lines.append(f"  {i}: {{file: {file}, name: {_name(name, i - 1)}, base_note: {base}, loop: from_wav}}")
    lines += ["instruments:", "  1:", f"    name: {name[:25]}", "    keymap:"]
    for i, (_, _, lo, hi) in enumerate(copies):
        lines.append(f"      - {{notes: {format_note(lo)}..{format_note(hi)}, sample: {_name(name, i)}}}")
    return lines


def _name(name, copy):
    return name[:25] if copy == 0 else f"{name[:22]}_o{copy}"

# sfxr: Tomas Pettersson's (DrPetter's) sfxr, MIT licence (drpetter.se/project_sfxr.html), its synthesis and the seven
# generators reimplemented from his main.cpp; parameters by its (and jsfxr's) names, all 0-1 or -1-1.
SFXR_PARAMS = {"wave_type": 0, "p_env_attack": 0.0, "p_env_sustain": 0.3, "p_env_punch": 0.0, "p_env_decay": 0.4,
               "p_base_freq": 0.3, "p_freq_limit": 0.0, "p_freq_ramp": 0.0, "p_freq_dramp": 0.0, "p_vib_strength": 0.0,
               "p_vib_speed": 0.0, "p_arp_mod": 0.0, "p_arp_speed": 0.0, "p_duty": 0.0,
               "p_duty_ramp": 0.0, "p_repeat_speed": 0.0, "p_pha_offset": 0.0, "p_pha_ramp": 0.0, "p_lpf_freq": 1.0,
               "p_lpf_ramp": 0.0, "p_lpf_resonance": 0.0, "p_hpf_freq": 0.0, "p_hpf_ramp": 0.0}
SFXR_SIGNED = {"p_freq_ramp", "p_freq_dramp", "p_arp_mod", "p_duty_ramp", "p_pha_offset", "p_pha_ramp", "p_lpf_ramp",
               "p_hpf_ramp"}  # -1 to 1; the others 0 to 1
SFXR_WAVES = {"square": 0, "saw": 1, "sawtooth": 1, "sine": 2, "noise": 3}
SFXR_PRESETS = ("pickup", "coin", "laser", "shoot", "explosion", "powerup", "hit", "hurt", "jump", "blip", "select")


def _sfxr_preset(name, seed):
    """sfxr's generator buttons: the preset's parameters drawn from `seed` (rnd(n) is 0..n, frnd(x) is 0..x)."""
    import random
    r = random.Random(seed)
    rnd, frnd = (lambda n: r.randint(0, n)), (lambda x: r.random() * x)
    p = dict(SFXR_PARAMS)
    if name in ("pickup", "coin"):
        p.update(p_base_freq=0.4 + frnd(0.5), p_env_attack=0.0, p_env_sustain=frnd(0.1), p_env_decay=0.1 + frnd(0.4),
                 p_env_punch=0.3 + frnd(0.3))
        if rnd(1):
            p.update(p_arp_speed=0.5 + frnd(0.2), p_arp_mod=0.2 + frnd(0.4))
    elif name in ("laser", "shoot"):
        p["wave_type"] = rnd(2)
        if p["wave_type"] == 2 and rnd(1):
            p["wave_type"] = rnd(1)
        p["p_base_freq"] = 0.5 + frnd(0.5)
        p["p_freq_limit"] = max(0.2, p["p_base_freq"] - 0.2 - frnd(0.6))
        p["p_freq_ramp"] = -0.15 - frnd(0.2)
        if rnd(2) == 0:
            p.update(p_base_freq=0.3 + frnd(0.6), p_freq_limit=frnd(0.1), p_freq_ramp=-0.35 - frnd(0.3))
        if rnd(1):
            p.update(p_duty=frnd(0.5), p_duty_ramp=frnd(0.2))
        else:
            p.update(p_duty=0.4 + frnd(0.5), p_duty_ramp=-frnd(0.7))
        p.update(p_env_attack=0.0, p_env_sustain=0.1 + frnd(0.2), p_env_decay=frnd(0.4))
        if rnd(1):
            p["p_env_punch"] = frnd(0.3)
        if rnd(2) == 0:
            p.update(p_pha_offset=frnd(0.2), p_pha_ramp=-frnd(0.2))
        if rnd(1):
            p["p_hpf_freq"] = frnd(0.3)
    elif name == "explosion":
        p["wave_type"] = 3
        if rnd(1):
            p.update(p_base_freq=0.1 + frnd(0.4), p_freq_ramp=-0.1 + frnd(0.4))
        else:
            p.update(p_base_freq=0.2 + frnd(0.7), p_freq_ramp=-0.2 - frnd(0.2))
        p["p_base_freq"] *= p["p_base_freq"]
        if rnd(4) == 0:
            p["p_freq_ramp"] = 0.0
        if rnd(2) == 0:
            p["p_repeat_speed"] = 0.3 + frnd(0.5)
        p.update(p_env_attack=0.0, p_env_sustain=0.1 + frnd(0.3), p_env_decay=frnd(0.5))
        if rnd(1) == 0:
            p.update(p_pha_offset=-0.3 + frnd(0.9), p_pha_ramp=-frnd(0.3))
        p["p_env_punch"] = 0.2 + frnd(0.6)
        if rnd(1):
            p.update(p_vib_strength=frnd(0.7), p_vib_speed=frnd(0.6))
        if rnd(2) == 0:
            p.update(p_arp_speed=0.6 + frnd(0.3), p_arp_mod=0.8 - frnd(1.6))
    elif name == "powerup":
        if rnd(1):
            p["wave_type"] = 1
        else:
            p["p_duty"] = frnd(0.6)
        if rnd(1):
            p.update(p_base_freq=0.2 + frnd(0.3), p_freq_ramp=0.1 + frnd(0.4), p_repeat_speed=0.4 + frnd(0.4))
        else:
            p.update(p_base_freq=0.2 + frnd(0.3), p_freq_ramp=0.05 + frnd(0.2))
            if rnd(1):
                p.update(p_vib_strength=frnd(0.7), p_vib_speed=frnd(0.6))
        p.update(p_env_attack=0.0, p_env_sustain=frnd(0.4), p_env_decay=0.1 + frnd(0.4))
    elif name in ("hit", "hurt"):
        p["wave_type"] = rnd(2)
        if p["wave_type"] == 2:
            p["wave_type"] = 3
        if p["wave_type"] == 0:
            p["p_duty"] = frnd(0.6)
        p.update(p_base_freq=0.2 + frnd(0.6), p_freq_ramp=-0.3 - frnd(0.4), p_env_attack=0.0,
                 p_env_sustain=frnd(0.1), p_env_decay=0.1 + frnd(0.2))
        if rnd(1):
            p["p_hpf_freq"] = frnd(0.3)
    elif name == "jump":
        p.update(wave_type=0, p_duty=frnd(0.6), p_base_freq=0.3 + frnd(0.3), p_freq_ramp=0.1 + frnd(0.2),
                 p_env_attack=0.0, p_env_sustain=0.1 + frnd(0.3), p_env_decay=0.1 + frnd(0.2))
        if rnd(1):
            p["p_hpf_freq"] = frnd(0.3)
        if rnd(1):
            p["p_lpf_freq"] = 1.0 - frnd(0.6)
    elif name in ("blip", "select"):
        p["wave_type"] = rnd(1)
        if p["wave_type"] == 0:
            p["p_duty"] = frnd(0.6)
        p.update(p_base_freq=0.2 + frnd(0.4), p_env_attack=0.0, p_env_sustain=0.1 + frnd(0.1), p_env_decay=frnd(0.2),
                 p_hpf_freq=0.1)
    return p


def sfxr_params(spec):
    """`sfxr:` -> sfxr's parameters: the preset's (drawn from `seed`, default 0), then the ones the spec names."""
    if not isinstance(spec, dict):
        raise SourceError(f"sfxr is a mapping: {{preset, seed, ...sfxr's parameters}}; got {spec!r}")
    bad = set(spec) - set(SFXR_PARAMS) - {"preset", "seed"}
    if bad:
        raise SourceError(f"sfxr: unknown keys {sorted(bad)} (preset, seed, {', '.join(SFXR_PARAMS)})")
    preset = spec.get("preset")
    if preset is not None and preset not in SFXR_PRESETS:
        raise SourceError(f"sfxr: preset is one of {', '.join(SFXR_PRESETS)}; got {preset!r}")
    p = _sfxr_preset(preset, int(spec.get("seed", 0))) if preset else dict(SFXR_PARAMS)
    for k, v in spec.items():
        if k in ("preset", "seed"):
            continue
        if k == "wave_type":
            v = SFXR_WAVES.get(v, v)
            if v not in (0, 1, 2, 3):
                raise SourceError(f"sfxr: wave_type is square, saw, sine or noise (0-3); got {spec[k]!r}")
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or not (-1 if k in SFXR_SIGNED else 0) <= v <= 1:
            raise SourceError(f"sfxr: {k} is a number from {-1 if k in SFXR_SIGNED else 0} to 1; got {v!r}")
        p[k] = v
    return p


SFXR_RATE = 44100 * 8  # sfxr's frames are 1/44100 s, each eight sub-steps of its oscillator, filters and phaser


def sfxr(spec, rate):
    """The `sfxr:` source: (1 x frames float array at `rate`, label). sfxr's synthesis (SynthSample) frame by frame, its
    eight sub-steps per frame kept as a stream at 352.8 kHz (sfxr averages them, which folds what lies above 22 kHz)
    and resampled to `rate`, band-limited."""
    import random
    from .resample import resample
    p = sfxr_params(spec)
    noise = random.Random(int(spec.get("seed", 0)) + 1)
    wave = int(p["wave_type"])

    def freq_state():  # ResetSample's part that a repeat restarts
        fperiod = 100.0 / (p["p_base_freq"] ** 2 + 0.001)
        arp = p["p_arp_mod"]
        return (fperiod, 100.0 / (p["p_freq_limit"] ** 2 + 0.001), 1.0 - p["p_freq_ramp"] ** 3 * 0.01,
                -p["p_freq_dramp"] ** 3 * 0.000001, 0.5 - p["p_duty"] * 0.5, -p["p_duty_ramp"] * 0.00005,
                1.0 - arp ** 2 * 0.9 if arp >= 0 else 1.0 + arp ** 2 * 10.0,
                0 if p["p_arp_speed"] == 1.0 else int((1.0 - p["p_arp_speed"]) ** 2 * 20000 + 32))

    fperiod, fmaxperiod, fslide, fdslide, duty, duty_slide, arp_mod, arp_limit = freq_state()
    arp_time = phase = 0
    fltp = fltdp = fltphp = 0.0
    fltw = p["p_lpf_freq"] ** 3 * 0.1
    fltw_d = 1.0 + p["p_lpf_ramp"] * 0.0001
    fltdmp = min(0.8, 5.0 / (1.0 + p["p_lpf_resonance"] ** 2 * 20.0) * (0.01 + fltw))
    flthp = p["p_hpf_freq"] ** 2 * 0.1
    flthp_d = 1.0 + p["p_hpf_ramp"] * 0.0003
    vib_phase, vib_speed, vib_amp = 0.0, p["p_vib_speed"] ** 2 * 0.01, p["p_vib_strength"] * 0.5
    env_length = [int(p[k] ** 2 * 100000) for k in ("p_env_attack", "p_env_sustain", "p_env_decay")]
    env_stage = env_time = 0
    fphase = math.copysign(p["p_pha_offset"] ** 2 * 1020.0, p["p_pha_offset"])
    fdphase = math.copysign(p["p_pha_ramp"] ** 2, p["p_pha_ramp"])
    phaser, ipp = [0.0] * 1024, 0
    noise_buffer = [noise.random() * 2 - 1 for _ in range(32)]
    rep_limit = 0 if p["p_repeat_speed"] == 0 else int((1.0 - p["p_repeat_speed"]) ** 2 * 20000 + 32)
    rep_time = 0
    lowpass, punch = p["p_lpf_freq"] != 1.0, p["p_env_punch"]
    out = []
    # ponytail: a Python loop, eight sub-steps per frame (sfxr's sounds last under 7 s: a few seconds at worst)
    while True:
        rep_time += 1
        if rep_limit and rep_time >= rep_limit:
            rep_time = 0
            fperiod, fmaxperiod, fslide, fdslide, duty, duty_slide, arp_mod, arp_limit = freq_state()
            arp_time = 0
        arp_time += 1
        if arp_limit and arp_time >= arp_limit:
            arp_limit = 0
            fperiod *= arp_mod
        fslide += fdslide
        fperiod *= fslide
        if fperiod > fmaxperiod:
            fperiod = fmaxperiod
            if p["p_freq_limit"] > 0:
                break
        rfperiod = fperiod
        if vib_amp > 0:
            vib_phase += vib_speed
            rfperiod = fperiod * (1.0 + math.sin(vib_phase) * vib_amp)
        period = max(8, int(rfperiod))
        duty = min(0.5, max(0.0, duty + duty_slide))
        env_time += 1
        if env_time > env_length[env_stage]:
            env_time = 0
            env_stage += 1
            if env_stage == 3:
                break
        length = max(1, env_length[env_stage])  # sfxr divides by a zero length here for one frame
        env_vol = (env_time / length if env_stage == 0 else
                   1.0 + (1.0 - env_time / length) * 2.0 * punch if env_stage == 1 else 1.0 - env_time / length)
        fphase += fdphase
        iphase = min(1023, abs(int(fphase)))
        if flthp_d != 0:
            flthp = min(0.1, max(0.00001, flthp * flthp_d))
        for _ in range(8):
            phase += 1
            if phase >= period:
                phase %= period
                if wave == 3:
                    noise_buffer = [noise.random() * 2 - 1 for _ in range(32)]
            fp = phase / period
            if wave == 0:
                sample = 0.5 if fp < duty else -0.5
            elif wave == 1:
                sample = 1.0 - fp * 2
            elif wave == 2:
                sample = math.sin(fp * 2 * math.pi)
            else:
                sample = noise_buffer[phase * 32 // period]
            pp = fltp
            fltw = min(0.1, max(0.0, fltw * fltw_d))
            if lowpass:
                fltdp += (sample - fltp) * fltw
                fltdp -= fltdp * fltdmp
            else:
                fltp, fltdp = sample, 0.0
            fltp += fltdp
            fltphp += fltp - pp
            fltphp -= fltphp * flthp
            sample = fltphp
            phaser[ipp & 1023] = sample
            sample += phaser[(ipp - iphase + 1024) & 1023]
            ipp = (ipp + 1) & 1023
            out.append(sample * env_vol)
    if not out:
        raise SourceError("sfxr: the parameters end the sound before its first frame")
    x = resample(np.asarray(out), SFXR_RATE, rate)
    names = {v: k for k, v in SFXR_WAVES.items() if k != "sawtooth"}
    return x[None, :], f"sfxr {spec.get('preset') or names[wave]}" + (f" seed {spec['seed']}" if "seed" in spec else "")

# drum: Paul Kellett's DrumSynth 2.0 (mda-vst.com; released by him under the MIT licence in 2007,
# sourceforge.net/projects/drumsynth), its .ds sections and their meaning reimplemented from his ds2wav renderer and
# help file. Times are frames at 44100 Hz and levels 0-100, as in a .ds file.
DRUM_SECTIONS = ("general", "tone", "noise", "overtones", "noiseband", "noiseband2", "distortion")
DRUM_RATE = 44100
_TWO_PI = 2 * math.pi


def _ds_file(path):
    """A .ds file (an INI file) -> {section: {key: text}}, lower-case names. DrumSynth versions 1 and 2."""
    import configparser
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        ini.read_string(path.read_text(encoding="latin-1"))
    except (OSError, configparser.Error) as e:
        raise SourceError(f"drum: {path.name}: {e}")
    sections = {s.lower(): dict(ini[s]) for s in ini.sections()}
    version = sections.get("general", {}).get("version", "")
    if not version.startswith("DrumSynth") or version[11:12] not in ("1", "2"):
        raise SourceError(f"drum: {path.name} is no DrumSynth 1 or 2 file (its [General] Version is {version!r})")
    return sections


def _ds_value(sections, section, key, default, what=float):
    """A section's value as DrumSynth reads it: a missing or empty key takes the default; a number's leading part counts
    (so '181' and '181 ' are 181)."""
    v = sections.get(section, {}).get(key)
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return what(v)
    import re
    m = re.match(r"\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?" if what is float else r"\s*[-+]?\d+", str(v))
    if not m:
        raise SourceError(f"drum: [{section}] {key} is a number; got {v!r}")
    return what(float(m.group())) if what is int else float(m.group())


def _ds_envelope(sections, section, key="envelope"):
    """An envelope -> (times, levels): a .ds string 'time,level time,level ...' or a list of [time, level] pairs;
    DrumSynth's default is '0,0 100,0'."""
    v = sections.get(section, {}).get(key, "0,0 100,0")
    try:
        pts = ([[float(a) for a in p.split(",")] for p in str(v).split()] if isinstance(v, str)
               else [[float(a), float(b)] for a, b in v])
    except (TypeError, ValueError):
        raise SourceError(f"drum: [{section}] {key} is 'time,level time,level ...' or [[time, level], ...]; got {v!r}")
    if not pts or any(len(p) != 2 for p in pts) or any(b[0] < a[0] for a, b in zip(pts, pts[1:])):
        raise SourceError(f"drum: [{section}] {key} needs time,level points in time order; got {v!r}")
    t, lv = np.array(pts).T
    return t, np.clip(lv, 0, 100) * 0.01


def drum_sections(spec, base):
    """`drum:` -> {section: {key: value}}: a .ds file beside the recipe, or a mapping of the sections (a section given
    in the mapping is on unless it says on: 0)."""
    from pathlib import Path
    if isinstance(spec, str):
        f = Path(base, spec)
        if not f.is_file():
            raise SourceError(f"drum: no such file {f}")
        return _ds_file(f)
    if not isinstance(spec, dict):
        raise SourceError(f"drum is a .ds file or a mapping of its sections ({', '.join(DRUM_SECTIONS)}); got {spec!r}")
    out = {}
    for name, keys in spec.items():
        if str(name).lower() not in DRUM_SECTIONS or not isinstance(keys, dict):
            raise SourceError(f"drum: sections are {', '.join(DRUM_SECTIONS)}, each a mapping; got {name!r}")
        out[str(name).lower()] = {"on": 1, **{str(k).lower(): v for k, v in keys.items()}}
    return out


def _waveform(ph, form):
    """DrumSynth's overtone waves: sine, rectified sine, triangle, saw, square."""
    if form == 0:
        return np.sin(np.fmod(ph, _TWO_PI))
    if form == 1:
        return np.abs(2 * np.sin(np.fmod(0.5 * ph, _TWO_PI))) - 1
    if form == 2:
        w = 0.6366197 * np.mod(ph, _TWO_PI) - 1
        return np.where(w > 1, 2 - w, w)
    if form == 3:
        return np.fmod(ph, _TWO_PI) / math.pi - 1
    return np.where(np.sin(np.fmod(ph, _TWO_PI)) > 0, 1.0, -1.0)


def drum(spec, base, rate):
    """The `drum:` source: (1 x frames float array at `rate`, label). DrumSynth's sections summed at 44100 Hz (its
    rate: a .ds file's times are frames of it) as its renderer does, in 1200-frame blocks, then resampled to `rate`."""
    from .resample import resample
    s = drum_sections(spec, base)
    v = lambda sec, key, d, what=float: _ds_value(s, sec, key, d, what)  # noqa: E731
    on = lambda sec: v(sec, "on", 0, int) == 1  # noqa: E731
    stretch = min(10.0, max(0.2, 0.01 * v("general", "stretch", 100.0)))
    gain = 10 ** (0.05 * v("general", "level", 0.0))
    tune = 1.0594631 ** v("general", "tuning", 0.0)
    w = lambda hz: tune * _TWO_PI * hz / DRUM_RATE  # noqa: E731  Hz -> radians per frame
    envs = {sec: _ds_envelope(s, sec) for sec in ("tone", "noise", "noiseband", "noiseband2")}
    envs["ot1"], envs["ot2"] = _ds_envelope(s, "overtones", "envelope1"), _ds_envelope(s, "overtones", "envelope2")
    envs["filter"] = _ds_envelope(s, "general", "filterenv")
    last = {k: t[-1] * stretch for k, (t, _) in envs.items()}
    owner = {"tone": "tone", "noise": "noise", "ot1": "overtones", "ot2": "overtones", "noiseband": "noiseband",
             "noiseband2": "noiseband2"}
    longest = max([last[k] for k, sec in owner.items() if on(sec)], default=0.0)
    n = 2400 + 1200 * int(longest / 1200)
    t = np.arange(n, dtype=float)

    def env(k, cut):
        """The envelope over the render; after its last point a section stops at the end of that 1200-frame block
        (cut), the overtones' envelopes drop to 0, the filter's holds."""
        times, levels = envs[k]
        e = np.interp(t, times * stretch, levels)
        if cut == "block":
            e[t >= 1200 * math.ceil(last[k] / 1200)] = 0
        elif cut == "zero":
            e[t >= last[k]] = 0
        return e

    rng = np.random.default_rng(1)  # DrumSynth fixes its random sequence too
    out = np.zeros(n)
    levels = {}
    if on("noise"):
        lv = v("noise", "level", 0, int)
        levels["noise"] = lv
        nl, slope = float(lv * lv), v("noise", "slope", 0, int)
        x = rng.uniform(-1, 1, n)
        x1, x2 = np.r_[0, x[:-1]], np.r_[0, 0, x[:-2]]
        if slope < 0:  # tilted down: a one-pole low-pass
            a, d, g = 1 + slope / 105, -slope / 105, (1 + 0.0005 * slope * slope) * nl
            y, acc = a * x, 0.0
            for i in range(n):  # ponytail: a Python loop, frames of a drum (seconds at most)
                acc = y[i] + d * acc
                y[i] = acc
        else:  # tilted up: a short FIR
            y, g = x - slope / 50 * x1 + abs(slope) / 100 * x2, nl
        out += y * g * env("noise", "block")
    f1 = w(v("tone", "f1", 200.0))
    f1 = math.copysign(max(abs(f1), 0.001), f1) if f1 else 0.001
    f2 = w(v("tone", "f2", 120.0))
    tmax = max(1.0, last["tone"])
    droop = v("tone", "droop", 0.0)
    if droop > 0:
        rate_ = 10 ** ((droop - 20) / 30) * -4 / tmax
        f2 = f1 + (f2 - f1) / (1 - math.exp(rate_ * tmax))
        sweep = f2 + (f1 - f2) * np.exp(t * rate_)
    else:
        sweep = f1 + t / tmax * (f2 - f1)
    phase0 = v("tone", "phase", 90.0) / 57.29578
    tone_on = on("tone")
    tone_active = t < 1200 * math.ceil(last["tone"] / 1200) if tone_on else np.zeros(n, bool)
    track = phase0 + np.cumsum(np.where(tone_active, sweep, f2))  # the tone's phase, which overtones may follow
    if tone_on:
        lv = v("tone", "level", 128, int)
        levels["tone"] = lv
        out += lv * lv * env("tone", "block") * np.sin(np.fmod(track, _TWO_PI))
    for band in ("noiseband", "noiseband2"):
        if not on(band):
            continue
        lv = v(band, "level", 128, int)
        levels[band] = lv
        bf, df = w(v(band, "f", 1000.0)), v(band, "df", 50, int)
        bq = df * df / (10000 - 6600 * (math.sqrt(max(bf, 0)) - 0.19))
        step = max(1, 1 + int((40 - df / 2.5) / (bq + 1 + bf)))
        jitter = np.repeat(rng.random(n // step + 1) - 0.5, step)[:n]  # a new random offset every `step` frames
        out += np.cos(np.fmod(_TWO_PI / 8 + np.cumsum(bf + bq * jitter), _TWO_PI)) * env(band, "block") * lv * lv
    ot = np.zeros(n)
    if on("overtones"):
        lv = v("overtones", "level", 128, int)
        levels["overtones"] = lv
        ol = float(lv * lv)
        mode = v("overtones", "method", 2, int)
        of1, of2 = w(v("overtones", "f1", 200.0)), w(v("overtones", "f2", 120.0))
        w1, w2 = v("overtones", "wave1", 0, int), v("overtones", "wave2", 0, int)
        bal2 = float(v("overtones", "param", 50, int))
        drive, bal2 = bal2 ** 3 / 50.0 ** 3, bal2 * 0.01
        bal1 = 1 - bal2
        e1, e2 = env("ot1", "zero"), env("ot2", "zero")
        if v("overtones", "track1", 0, int) == 1 and tone_on:
            of1 /= f1
            ph1 = track * of1
        else:
            ph1 = phase0 + (t + 1) * of1
        if v("overtones", "track2", 0, int) == 1 and tone_on:
            of2 /= f1
            ph2 = track * of2
        else:
            ph2 = phase0 + (t + 1) * of2
        if mode == 0:  # add
            ot = ol * (bal1 * e1 * _waveform(ph1, w1) + bal2 * e2 * _waveform(ph2, w2))
        elif mode == 1:  # FM: the second wave modulates the first's phase
            ot = ol * e1 * _waveform(ph1 + drive * e2 * _waveform(ph2, w2), w1)
        elif mode == 2:  # ring modulation
            ot = ol * e1 * _waveform(ph1, w1) * ((1 - drive / 8) + drive / 8 * e2 * _waveform(ph2, w2))
        else:  # the 808 cymbal: six pulse trains between the two periods, through a band-pass swept by envelope 2
            ca = 0.28 + bal1 * bal1
            cq, cf = ca * ca, (1.8 - 0.7 * ca * ca) * 0.92
            p1, p2 = _TWO_PI / of1, _TWO_PI / of2
            periods = [p1 + (p2 - p1) * 0.2 * i for i in range(6)]
            counts = list(periods)
            lo = band_ = prev = 0.0
            for i in range(n):  # ponytail: a Python loop over the drum's frames
                hit = 0.0
                for j in range(6):
                    counts[j] += 1
                    if counts[j] > periods[j]:
                        counts[j] -= periods[j]
                        hit = ol * e1[i]
                f = e2[i] * cf
                lo += f * band_
                band_ += f * (hit + prev - cq * band_ - lo)
                prev = hit
                ot[i] = band_
    main = 2 * v("general", "filter", 0, int)
    if main == 0:
        main = v("overtones", "filter", 0, int)
    if main in (1, 2):  # the resonant filter, on the overtones (1) or on everything (2); HighPass subtracts its input
        fe = env("filter", None)
        fb = np.where(fe > 0.2, 1.001 - 10 ** (fe - 1), 0.999 - 0.7824 * fe)
        res = math.sqrt(0.0101 * min(100.0, max(0.0, v("general", "resonance", 0.0))))
        hp = v("general", "highpass", 0, int)
        src = ot if main == 1 else out + ot
        y = np.empty(n)
        fin = fout = 0.0
        for i in range(n):  # ponytail: a Python loop over the drum's frames
            k = fb[i]
            tmp = src[i] + res * (1 + 1 / k) * (fin - fout)
            fin = k * (fin - tmp) + tmp
            fout = k * (fout - fin) + fin
            y[i] = fout
        out = out + y - hp * ot if main == 1 else y - hp * src
    else:
        out = out + ot
    clip = 32700.0
    if on("distortion"):  # clipping, fewer bits, a lower rate (each block of frames held at its mean)
        loudest = max([levels[k] for k in levels], default=0)
        clip = min(32700.0, float(int(gain * loudest * loudest)))
        atten = 2.0 ** (2 * v("distortion", "bits", 0, int))
        gain = atten * gain * 10 ** (0.05 * v("distortion", "clipping", 0, int))
        out = gain * np.trunc(out / atten)
        hold = {5: 8, 6: 10, 7: 20}.get(1 + v("distortion", "rate", 0, int), 1 + v("distortion", "rate", 0, int))
        if hold > 1:
            out = np.repeat(out.reshape(-1, hold).mean(axis=1), hold) if n % hold == 0 else out
    else:
        out = out * gain
    out = np.clip(out, -clip, clip) / 32768
    if not np.isfinite(out).all():
        raise SourceError("drum: the settings render no finite sound")
    x = resample(out, DRUM_RATE, rate) if rate != DRUM_RATE else out
    return x[None, :], "drum " + (spec if isinstance(spec, str) else ", ".join(k for k in DRUM_SECTIONS[1:] if on(k)))

# additive: Nasca Octavian Paul's PADsynth algorithm (public domain, zynaddsubfx.sourceforge.io/doc/PADsynth), from its
# description: each harmonic a Gaussian band in one spectrum, random phases, one inverse FFT, so the loop is exact.
ADDITIVE_KEYS = {"harmonics": 16, "bandwidth_cents": 40.0, "bandwidth_scale": 1.0, "loop_seconds": 3.0, "seed": 0,
                 "ceiling": 18000.0}


def additive(spec, root, rate):
    """The `additive:` source: (1 x frames float array, (0, frames, False) loop, label). The harmonics of the note,
    each spread as a Gaussian band bandwidth_cents wide at the first harmonic (times h ** bandwidth_scale at the h-th;
    never under one bin), the spectrum's bins given random phases from `seed`, and loop_seconds of it made by one
    inverse FFT: the end runs into the start. Harmonics, and bins, over `ceiling` Hz are left out."""
    a = _keys(spec, ADDITIVE_KEYS, "additive")
    h = a["harmonics"]
    if isinstance(h, int) and not isinstance(h, bool) and 1 <= h <= 512:
        amps = [1 / k for k in range(1, h + 1)]
    elif (isinstance(h, list) and 1 <= len(h) <= 512 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                              and v >= 0 for v in h) and any(h)):
        amps = [float(v) for v in h]
    else:
        raise SourceError(f"additive: harmonics is a count 1-512 (amplitudes 1/h) or a list of amplitudes (0 or more, "
                          f"one not 0); got {h!r}")
    bw, scale, seconds = float(a["bandwidth_cents"]), float(a["bandwidth_scale"]), float(a["loop_seconds"])
    top = float(a["ceiling"])
    if not 0 < bw <= 2400 or not -2 <= scale <= 4 or not 0.1 <= seconds <= 30 or not 20 <= top:
        raise SourceError("additive: bandwidth_cents is above 0 to 2400, bandwidth_scale -2 to 4, loop_seconds 0.1-30, "
                          f"ceiling 20 Hz or more; got {a}")
    n = 2 * round(seconds * rate / 2)
    f = hz(root)
    bins = np.arange(n // 2 + 1) / n  # each bin's frequency as a fraction of the rate
    spectrum = np.zeros(len(bins))
    for k, amp in enumerate(amps, 1):
        if not amp or f * k > min(top, rate / 2):
            continue
        width = max((2 ** (bw / 1200) - 1) * f * k ** scale / (2 * rate), 1 / n)  # PADsynth's bwi, a bin at least
        near = np.abs(bins - f * k / rate) < 6 * width  # exp(-36): nothing past six widths
        spectrum[near] += np.exp(-(((bins[near] - f * k / rate) / width) ** 2)) / width * amp
    spectrum[bins * rate > top] = 0
    spectrum[0] = 0
    if not spectrum.any():
        raise SourceError(f"additive: no harmonic of {f:.1f} Hz is under {top:.0f} Hz")
    phases = np.random.default_rng(int(a["seed"])).uniform(0, 2 * np.pi, len(bins))
    x = np.fft.irfft(spectrum * np.exp(1j * phases), n)
    x /= np.abs(x).max()
    return x[None, :], (0, n, False), f"additive {len(amps)} harmonics, {bw:g} cents"


# ---------------------------------------------------------------- Hydrogen drum kits

def _xml_children(node, tag):
    return [c for c in node if c.tag.rsplit("}", 1)[-1] == tag]


def _xml_text(node, tag, default=None):
    found = _xml_children(node, tag)
    return found[0].text.strip() if found and found[0].text and found[0].text.strip() else default


def _xml_float(node, tag, default):
    try:
        return float(_xml_text(node, tag, default))
    except (TypeError, ValueError):
        return default


def h2kit(path):
    """A Hydrogen drum kit (.h2drumkit: a tar archive, usually gzipped, holding `<kit>/drumkit.xml` and its samples, as
    Hydrogen's Drumkit.cpp packs it) read as its drumkit.xml says (data/xsd/drumkit.xsd and Instrument.cpp,
    InstrumentComponent.cpp, InstrumentLayer.cpp): {name, author, license, xml (the member's folder), instruments: [{id,
    name, volume, gain, pan (-1 left .. 1 right; the old pan_L/pan_R pair converted as Sampler::getRatioPan does),
    pitch, layers: [{file, min, max, gain, pitch}]}]}. A kit of the old format keeps its layers in the instrument itself,
    or one `filename` there; each layer's gain includes its component's."""
    import tarfile
    from xml.etree import ElementTree
    try:
        with tarfile.open(path, "r:*") as tar:
            xmls = sorted((m for m in tar.getmembers() if m.isfile() and m.name.rsplit("/", 1)[-1] == "drumkit.xml"),
                          key=lambda m: m.name.count("/"))
            if not xmls:
                raise SourceError(f"{path}: no drumkit.xml in the archive")
            root = ElementTree.fromstring(tar.extractfile(xmls[0]).read())
    except (tarfile.TarError, OSError, ElementTree.ParseError) as e:
        raise SourceError(f"{path}: not a Hydrogen drum kit ({e})")
    folder = xmls[0].name.rsplit("/", 1)[0] if "/" in xmls[0].name else ""
    lists = [n for n in root.iter() if n.tag.rsplit("}", 1)[-1] == "instrumentList"]
    out = []
    for ins in _xml_children(lists[0], "instrument") if lists else []:
        pan = _xml_text(ins, "pan")
        if pan is not None:
            pan = _xml_float(ins, "pan", 0.0)
        else:
            left, right = _xml_float(ins, "pan_L", 1.0), _xml_float(ins, "pan_R", 1.0)
            pan = 0.0 if left < 0 or right < 0 or left == right == 0 else (right / left - 1 if left >= right else 1 - left / right)
        layers = []
        parts = [(c, _xml_float(c, "gain", 1.0)) for c in _xml_children(ins, "instrumentComponent")] or [(ins, 1.0)]
        for part, gain in parts:
            for layer in _xml_children(part, "layer"):
                if _xml_text(layer, "filename"):
                    layers.append({"file": _xml_text(layer, "filename"), "min": _xml_float(layer, "min", 0.0),
                                   "max": _xml_float(layer, "max", 1.0), "gain": gain * _xml_float(layer, "gain", 1.0),
                                   "pitch": _xml_float(layer, "pitch", 0.0)})
        if not layers and _xml_text(ins, "filename"):
            layers.append({"file": _xml_text(ins, "filename"), "min": 0.0, "max": 1.0, "gain": 1.0, "pitch": 0.0})
        out.append({"id": _xml_text(ins, "id"), "name": _xml_text(ins, "name", ""), "volume": _xml_float(ins, "volume", 1.0),
                    "gain": _xml_float(ins, "gain", 1.0), "pan": max(-1.0, min(1.0, pan)),
                    "pitch": _xml_float(ins, "pitchOffset", 0.0), "layers": layers})
    return {"name": _xml_text(root, "name", ""), "author": _xml_text(root, "author", ""),
            "license": _xml_text(root, "license", ""), "xml": folder, "instruments": out}


def h2kit_pick(kit, instrument, layer=None):
    """(instrument, layer number from 1, layer) of a kit: `instrument` by name (any case) or number from 1, `layer` by
    number, by default the loudest (the one reaching the highest velocity)."""
    names = ", ".join(i["name"] for i in kit["instruments"])
    if instrument is None:
        raise SourceError(f"a .h2drumkit needs instrument: (a name or a number from 1); this kit has: {names}")
    found = [i for i in kit["instruments"] if str(i["name"]).lower() == str(instrument).lower()]
    if not found and isinstance(instrument, int) and 1 <= instrument <= len(kit["instruments"]):
        found = [kit["instruments"][instrument - 1]]
    if not found:
        raise SourceError(f"no instrument '{instrument}' in kit '{kit['name']}' (it has: {names})")
    ins = found[0]
    if not ins["layers"]:
        raise SourceError(f"instrument '{ins['name']}' has no sample")
    if layer is None:
        k = max(range(len(ins["layers"])), key=lambda j: (ins["layers"][j]["max"], ins["layers"][j]["min"]))
    elif isinstance(layer, int) and 1 <= layer <= len(ins["layers"]):
        k = layer - 1
    else:
        raise SourceError(f"instrument '{ins['name']}' has layers 1-{len(ins['layers'])}, not {layer}")
    return ins, k + 1, ins["layers"][k]


def h2kit_member(path, kit, layer):
    """The layer's sample file as bytes, read from the archive (beside drumkit.xml; nothing is extracted to disk)."""
    import tarfile
    name = f"{kit['xml']}/{layer['file']}" if kit["xml"] else layer["file"]
    with tarfile.open(path, "r:*") as tar:
        try:
            member = tar.getmember(name)
        except KeyError:
            raise SourceError(f"{path}: the kit names {layer['file']}, which the archive does not hold")
        return tar.extractfile(member).read()
