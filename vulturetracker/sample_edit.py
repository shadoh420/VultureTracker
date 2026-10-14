"""The Samples tab's edits on a WAV's frames (process_wav: trims, fades, effects, stretch; the loops follow the audio)
and its waveform view (wav_array, wave_peaks, entry_loops), the PAINT tab's picture checked (paint_args), and the
instrument panel's view of an instrument entry (voice_of, voice_entry)."""
import functools

from .wavload import read_wav


# ---------------------------------------------------------------- the sample editor

@functools.lru_cache(maxsize=8)
def wav_array(path, stamp):
    """A WAV as (WavData, float32 array channels x frames scaled to -1..1); `stamp` keys the cache on mtime and size."""
    import numpy as np
    w = read_wav(path)
    return w, np.array(w.channels, dtype=np.float32) / (128 if w.out_bits == 8 else 32768)


def wave_peaks(x, a, b, n):
    """Frames a..b of `x` (channels x frames) as `n` columns: (min, max) per column and channel, lists rounded for JSON;
    when the span holds `n` frames or fewer, the frames themselves (min = max)."""
    import numpy as np
    seg = x[:, a:b]
    if seg.shape[1] <= n:
        mn = mx = seg
    else:
        at = np.arange(n) * seg.shape[1] // n
        mn, mx = np.minimum.reduceat(seg, at, axis=1), np.maximum.reduceat(seg, at, axis=1)
    return np.round(mn, 4).tolist(), np.round(mx, 4).tolist()


def entry_loops(entry, w):
    """The sample entry's `loop` and `sustain_loop` in the WAV's frames: {key: (start, end, pingpong) or None}
    (`from_wav` read from the WAV's smpl chunk, its end clamped to the audio as the compiler plays it)."""
    out, n = {}, len(w.channels[0])
    for k in ("loop", "sustain_loop"):
        spec = entry.get(k)
        if spec == "from_wav":
            s, e, pp = w.loops[0] if w.loops else (0, 0, False)
            out[k] = (s, min(e, n), pp) if min(e, n) > s else None
        elif isinstance(spec, dict):
            out[k] = (int(spec.get("start", 0)), int(spec.get("end", n)), spec.get("type") == "pingpong")
        else:
            out[k] = None
    return out


SAMPLE_ACTIONS = ("trim", "fade_in", "fade_out", "normalize", "reverse", "dc", "crossfade", "gain", "lowpass", "highpass",
                  "eq", "loudness", "pitch", "stretch", "truncate", "denoise", "spectral_mask", "granular")


def _splice(x, a, b, seg, loops):
    """`x` with frames a..b replaced by `seg` (another length): loops before the span stay, loops after it move with the
    audio, a loop inside it is scaled with it, one across its edge is dropped."""
    import numpy as np
    k = seg.shape[1] / max(1, b - a)
    out = {}
    for key, lp in loops.items():
        if not lp:
            out[key] = lp
        elif lp[1] <= a:
            out[key] = lp
        elif lp[0] >= b:
            d = seg.shape[1] - (b - a)
            out[key] = (lp[0] + d, lp[1] + d, lp[2])
        elif a <= lp[0] and lp[1] <= b:
            s, e = a + round((lp[0] - a) * k), a + round((lp[1] - a) * k)
            out[key] = (s, max(s + 1, e), lp[2])
        else:
            out[key] = None
    return np.concatenate([x[:, :a], seg.astype(x.dtype), x[:, b:]], axis=1), out


def process_wav(x, action, a, b, loops, frames=0, params=None, rate=44100):
    """One sample edit on frames a..b of `x` (float channels x frames; a copy is changed). `loops` ({key: (start, end,
    pingpong) or None}) follow the audio: trimmed (shifted, clipped, dropped when nothing is left) and mirrored by a
    reverse of the whole sample. The effects (dsp.py; `params` their settings, `rate` the WAV's) work on the span too:
    gain (db), lowpass / highpass (hz, slope 12 or 24), eq (hz, db, q), loudness (db: the RMS target), pitch
    (semitones, the length kept), stretch (percent, the pitch kept), denoise (the noise learned from frames na..nb of
    `x`, turned down by up to db, sens its threshold over the noise), truncate (silences under db dBFS longer than
    min_ms shortened to keep_ms) and granular (grain_ms, density, pitch_st, jitter, spray_ms, seed: dsp.granular, the
    length kept); stretch and truncate change the length, and the loops move with the audio. Crossfade: the last `frames` of the loop fade (equal power) into the audio just before
    its start, so the wrap is seamless (the synth recipes' crossfade). Returns (x, loops)."""
    import numpy as np
    x, loops, n = x.copy(), dict(loops), x.shape[1]
    seg = x[:, a:b]
    if action == "trim":
        x = seg.copy()
        for k, lp in loops.items():
            if lp:
                s, e = max(0, lp[0] - a), min(b - a, lp[1] - a)
                loops[k] = (s, e, lp[2]) if e > s else None
    elif action in ("fade_in", "fade_out"):
        ramp = np.linspace(0, 1, seg.shape[1], dtype=np.float32)
        seg *= ramp if action == "fade_in" else ramp[::-1]
    elif action == "normalize":
        peak = float(np.abs(seg).max()) if seg.size else 0
        if peak <= 0:
            raise ValueError("nothing to normalize: the selection is silent")
        seg *= 1 / peak
    elif action == "reverse":
        x[:, a:b] = seg[:, ::-1]
        if (a, b) == (0, n):
            loops = {k: lp and (n - lp[1], n - lp[0], lp[2]) for k, lp in loops.items()}
    elif action == "dc":
        seg -= seg.mean(axis=1, keepdims=True)
    elif action == "crossfade":
        lp = loops.get("loop") or loops.get("sustain_loop")
        if not lp:
            raise ValueError("crossfade needs a loop (or a sustain loop)")
        s, e = lp[0], lp[1]
        xf = min(int(frames), s, e - s)
        if xf <= 0:
            raise ValueError("crossfade needs audio before the loop start: move the loop start later")
        t = np.linspace(0, np.pi / 2, xf, endpoint=False, dtype=np.float32)
        x[:, e - xf:e] = x[:, e - xf:e] * np.cos(t) + x[:, s - xf:s] * np.sin(t)
    elif action in ("gain", "lowpass", "highpass", "eq", "loudness", "pitch", "denoise", "spectral_mask", "granular"):
        from . import dsp
        q = params or {}

        def num(k, lo, hi, default=None):
            try:
                v = float(q.get(k, default))
            except (TypeError, ValueError):
                raise ValueError(f"{action}: {k} must be a number")
            if not lo <= v <= hi:
                raise ValueError(f"{action}: {k} is {lo:g} to {hi:g}")
            return v
        nyq = rate / 2
        if action == "gain":
            y = dsp.gain(seg, num("db", -60, 24))
        elif action == "lowpass":
            y = dsp.lowpass(seg, rate, num("hz", 20, nyq), num("slope", 12, 24, 24))
        elif action == "highpass":
            y = dsp.highpass(seg, rate, num("hz", 10, nyq), num("slope", 12, 24, 24))
        elif action == "eq":
            y = dsp.peak_eq(seg, rate, num("hz", 20, nyq * 0.98), num("db", -24, 24), num("q", 0.1, 20, 1))
        elif action == "loudness":
            y = dsp.loudness(seg, num("db", -60, 0, -18))[0]
        elif action == "spectral_mask":  # the PAINT tab's picture laid over the span's spectrum (spectral.py)
            from . import spectral
            pic = paint_args(q)
            y = spectral.spectral_mask(seg, rate, pic["amp"], pic["fmin"], pic["fmax"], pic["scale"], pic["range_db"])
        elif action == "granular":
            y = dsp.granular(seg, rate, num("grain_ms", 5, 1000, 80), num("density", 1, 32, 4), num("pitch_st", -24, 24, 0),
                             num("jitter", 0, 24, 0), num("spray_ms", 0, 2000, 0), seed=int(num("seed", 0, 2 ** 31, 0)))
        elif action == "denoise":
            na, nb = int(num("na", 0, n)), int(num("nb", 0, n))
            if nb - na < 2048:
                raise ValueError("denoise: LEARN NOISE from a selection where only the noise sounds (at least 50 ms)")
            y = dsp.denoise(seg, rate, x[:, na:nb], num("db", 0, 60, 12), num("sens", 1, 8, 2))
        else:
            y = dsp.pitch_shift(seg, num("semitones", -24, 24))
        x[:, a:b] = y
    elif action in ("stretch", "truncate"):
        from . import dsp
        q = params or {}
        if action == "stretch":
            pct = float(q.get("percent", 100))
            if not 25 <= pct <= 400:
                raise ValueError("stretch: 25 to 400 %")
            new = dsp.stretch(seg, pct / 100)
        else:
            runs = dsp.silent_runs(seg, rate, float(q.get("db", -50)), float(q.get("min_ms", 200)))
            keep = max(0, int(float(q.get("keep_ms", 50)) * rate / 1000))
            if not runs:
                raise ValueError("truncate: no silence that long and that quiet in the span")
            parts, at = [], 0
            for s, e in runs:
                parts.append(seg[:, at: s + keep // 2])
                at = max(s + keep // 2, e - (keep - keep // 2))
            parts.append(seg[:, at:])
            new = np.concatenate(parts, axis=1)
            loops = {k: (lp if lp and (lp[1] <= a or lp[0] >= b) else None) for k, lp in loops.items()}
        x, loops = _splice(x, a, b, new, loops)
    else:
        raise ValueError(f"unknown sample edit '{action}' (one of {', '.join(SAMPLE_ACTIONS)})")
    if x.shape[1] == 0:
        raise ValueError("the edit leaves no audio")
    return x, loops


def paint_args(body):
    """The PAINT tab's picture and its settings from a request, checked: {amp, pan (rows x columns arrays), seconds, fmin,
    fmax, scale, range_db}."""
    import numpy as np
    try:
        amp = np.asarray(body["amp"], float)
        pan = np.asarray(body.get("pan") if body.get("pan") is not None else np.zeros_like(amp), float)
    except (KeyError, TypeError, ValueError):
        raise ValueError("paint: the picture is rows x columns of brightness 0-1 (amp) and pan -1..1 (pan)")
    if amp.ndim != 2 or pan.shape != amp.shape or not (1 <= amp.shape[0] <= 256 and 1 <= amp.shape[1] <= 1024):
        raise ValueError("paint: a picture is 1-256 rows by 1-1024 columns, with a pan of the same shape")
    scale = body.get("scale") or "log"
    if scale not in ("log", "notes"):
        raise ValueError("paint: the rows are spread in log frequency (log) or one per semitone (notes)")
    fmin, fmax = float(body.get("fmin", 40)), float(body.get("fmax", 12000))
    if scale == "notes" and not (0 <= fmin < 120):
        raise ValueError("paint: the lowest note is C-0 (0) to B-9 (119)")
    if scale == "log" and not (10 <= fmin < fmax <= 20000):
        raise ValueError("paint: the range is 10 Hz to 20 kHz, low to high")
    seconds, range_db = float(body.get("seconds", 2)), float(body.get("range_db", 48))
    if not 0.01 <= seconds <= 60 or not 6 <= range_db <= 96:
        raise ValueError("paint: 0.01-60 seconds, a 6-96 dB range")
    return {"amp": np.clip(amp, 0, 1), "pan": np.clip(pan, -1, 1), "seconds": seconds, "fmin": fmin, "fmax": fmax,
            "scale": scale, "range_db": range_db}


# ---------------------------------------------------------------- the instrument panel

# per-note movement the tracker itself plays, in the panel's terms: a volume envelope from attack and decay (ticks) and a
# sustain level, the release (the instrument's fadeout, 0-256: a fading note loses fadeout / 1024 per tick), the resonant
# low-pass (cutoff 127 and resonance 0 = off), a filter sweep (the pitch envelope in filter mode, from and to a share of
# the cutoff in 64ths: libopenmpt scales the cutoff by (value + 32) / 64, so 64 is the cutoff, 0 closed) and random volume
# per note
VOICE_GROUPS = {"volume": ("attack", "decay", "sustain"), "release": ("release",), "filter": ("cutoff", "resonance"),
                "sweep": ("sweep_from", "sweep_to", "sweep_ticks"), "random": ("random",)}


VOICE_RANGE = {"attack": (0, 64), "decay": (0, 192), "sustain": (0, 64), "release": (0, 256), "cutoff": (0, 127),
               "resonance": (0, 127), "sweep_from": (0, 64), "sweep_to": (0, 64), "sweep_ticks": (0, 192), "random": (0, 100)}


def voice_of(ins):
    """The panel's view of an instrument entry (the song's mapping). Returns (params, custom): `custom` lists the groups
    whose envelope in the song has another shape than the panel writes; the panel shows defaults for them and replaces
    that envelope only when one of its sliders moves."""
    p = {"attack": 0, "decay": 0, "sustain": 64, "release": int(ins.get("fadeout") or 0),
         "cutoff": 127 if ins.get("filter_cutoff") is None else int(ins["filter_cutoff"]),
         "resonance": int(ins.get("filter_resonance") or 0), "sweep_from": 64, "sweep_to": 64, "sweep_ticks": 0,
         "random": int(ins.get("random_volume") or 0)}
    custom = []

    def plain(env):  # enabled, no loop; the sustain as one node index (or None)
        s = env.get("sustain")
        s = s[0] if isinstance(s, list) and len(s) == 2 and s[0] == s[1] else s
        return (env.get("enabled", True) and not env.get("loop") and (s is None or isinstance(s, int)),
                [tuple(n) for n in env.get("nodes") or []], s)

    env = ins.get("volume_envelope")
    if env:
        ok, n, s = plain(env)
        shape = None
        if ok and n == [(0, 64)]:
            shape = (0, 0, 64)
        elif ok and len(n) == 2 and n[0] == (0, 0) and n[1][1] == 64 and s == 1:
            shape = (n[1][0], 0, 64)
        elif ok and len(n) == 2 and n[0] == (0, 64) and n[1][1] < 64 and s == (1 if n[1][1] else None):
            shape = (0, n[1][0], n[1][1])
        elif ok and len(n) == 3 and n[0] == (0, 0) and n[1][1] == 64 and n[2][1] < 64 and s == (2 if n[2][1] else None):
            shape = (n[1][0], n[2][0] - n[1][0], n[2][1])
        if shape:
            p["attack"], p["decay"], p["sustain"] = shape
        else:
            custom.append("volume")
    env = ins.get("pitch_envelope")
    if env:
        ok, n, s = plain(env)
        if ok and env.get("filter") and s is None and len(n) in (1, 2):
            p["sweep_from"], p["sweep_to"], p["sweep_ticks"] = n[0][1] + 32, n[-1][1] + 32, n[-1][0]
        else:
            custom.append("sweep")
    return p, custom


def voice_entry(ins, edit):
    """The instrument entry with the panel's `edit` (some of voice_of's params) written in. Only the groups the edit
    touches change, so an envelope the panel cannot show stays unless one of its sliders moved."""
    p = voice_of(ins)[0]
    p.update({k: int(v) for k, v in edit.items() if k in VOICE_RANGE})
    touched = {g for g, keys in VOICE_GROUPS.items() if any(k in edit for k in keys)}
    out = dict(ins)

    def put(key, value, keep):
        if keep:
            out[key] = value
        else:
            out.pop(key, None)

    if "volume" in touched:
        a, d, s = p["attack"], p["decay"], p["sustain"]
        nodes = [[0, 0], [a, 64]] if a else [[0, 64]]
        if s < 64:
            nodes.append([nodes[-1][0] + max(1, d), s])  # the level held until note-off; 0 lets the note die away
        put("volume_envelope", {"nodes": nodes, **({"sustain": len(nodes) - 1} if s else {})}, len(nodes) > 1)
    if "release" in touched:
        put("fadeout", p["release"], p["release"])
    sweep = (p["sweep_from"], p["sweep_to"]) != (64, 64)
    if touched & {"filter", "sweep"}:
        on = p["cutoff"] < 127 or p["resonance"] > 0 or sweep
        put("filter_cutoff", p["cutoff"], on)
        put("filter_resonance", p["resonance"], on)
    if "sweep" in touched:
        v0, v1 = p["sweep_from"] - 32, p["sweep_to"] - 32
        nodes = [[0, v0], [p["sweep_ticks"], v1]] if p["sweep_ticks"] and v0 != v1 else [[0, v1]]
        put("pitch_envelope", {"nodes": nodes, "filter": True}, sweep)
    if "random" in touched:
        put("random_volume", p["random"], p["random"])
    return out
