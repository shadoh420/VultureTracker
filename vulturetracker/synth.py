"""Render samples from synth patches (Surge XT, Dexed, OB-Xd) or audio files, driven by a YAML recipe
(see SAMPLING.md). Needs `pip install pedalboard mido` and the synth plugins (see SAMPLING.md, Setup).
"""
import fnmatch
import os
import re
import struct
import sys
from pathlib import Path

import yaml

from . import notation
from .wavload import write_wav

ROOT = Path(__file__).resolve().parent.parent
# the synths: tools/ of a checkout; the exe (no checkout) keeps them in %LOCALAPPDATA%/VultureTracker/tools (fetch_synth)
TOOLS = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VultureTracker" / "tools" if getattr(sys, "frozen", False)
         else ROOT / "tools")
DEFAULT_SURGE = TOOLS / "surge-xt" / "Surge Synth Team"
RECIPE_KEYS = ["out_dir", "sample_rate", "defaults", "samples"]
SAMPLE_KEYS = ["patch", "file", "resynth", "start", "length", "fx", "fx_tail", "note", "notes", "chord", "phrase", "velocity",
               "hold", "tail", "params", "gain", "normalize", "mono", "trim", "loop", "fade_out", "reverse", "root_offset"]


# `resynth:` (mosaic.resynth): a target rebuilt from blocks of a corpus; its keys and their defaults
RESYNTH_KEYS = {"target": None, "corpus": None, "block": 0.05, "overlap": 4, "variety": 1, "reuse": 0.0, "level": 1.0,
                "mix": 0.0, "seed": 0, "gate": -60.0, "corpus_seconds": 120.0}


class RecipeError(ValueError):
    pass


class SynthMissing(RecipeError):
    """A synth the recipe needs is not installed; `kind` is surge, dexed or obxd."""

    def __init__(self, kind, msg):
        super().__init__(msg)
        self.kind = kind


# ---------------------------------------------------------------- synth host (Surge XT, Dexed, OB-Xd)
#
# Patch names: Surge XT 'Category/Name' or '3rdparty/Author/Category/Name'; Dexed (DX7) 'dexed:Cartridge/Voice';
# OB-Xd 'obxd:Bank/Program'. Every patch loads by handing the plugin its own saved-state format, as a DAW would.

DEXED_VST3 = Path(os.environ.get("DEXED_VST3", TOOLS / "synths" / "dexed" / "Dexed.vst3"))
OBXD_VST3 = Path(os.environ.get("OBXD_VST3", Path(os.environ.get("COMMONPROGRAMFILES", r"C:\Program Files\Common Files"))
                                / "VST3" / "OB-Xd.vst3"))
DEXED_CARTS = [Path(os.environ.get("APPDATA", Path.home())) / "DigitalSuburban" / "Dexed" / "Cartridges",
               TOOLS / "synths" / "cartridges"]  # Dexed writes its bundled cartridges to the first on first load
OBXD_BANKS = Path.home() / "Documents" / "discoDSP" / "OB-Xd" / "Banks"


def surge_dir():
    d = Path(os.environ.get("SURGE_XT_DIR", DEFAULT_SURGE))
    if not (d / "Surge XT.vst3").exists():
        raise SynthMissing("surge", f"Surge XT not found in {d}; get it from the app's RECIPE box, run python "
                                    "tools/fetch_surge.py or set SURGE_XT_DIR")
    return d


# the Windows downloads fetch_synth unpacks into TOOLS (tools/fetch_surge.py and fetch_instruments.py do the same for a
# checkout); OB-Xd has only an installer: https://www.discodsp.com/obxd/
FETCH = {"surge": ("https://github.com/surge-synthesizer/releases-xt/releases/download/1.3.4/"
                   "surge-xt-win64-1.3.4-portable-install.zip", TOOLS / "surge-xt"),
         "dexed": ("https://github.com/asb2m10/dexed/releases/download/v1.0.1/Dexed-1.0.1-win.zip",
                   TOOLS / "synths" / "dexed")}


def fetch_synth(kind, progress=lambda done, total: None):
    """Download a synth (FETCH) and unpack it into its folder; the folder appears only once it is whole."""
    import shutil
    import tempfile
    import urllib.request
    import zipfile
    url, dest = FETCH[kind]
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        z, done = Path(tmp) / "download.zip", 0
        req = urllib.request.Request(url, headers={"User-Agent": "vulturetracker"})
        with urllib.request.urlopen(req) as r, open(z, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                progress(done, total)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(Path(tmp) / "x")
        if dest.exists():
            shutil.rmtree(dest)
        (Path(tmp) / "x").rename(dest)


def _unique(out, key, value):
    k, n = key, 2
    while k in out:
        k, n = f"{key} ({n})", n + 1
    out[k] = value


def dx7_voice_names(cart: bytes):
    """Names of the 32 voices in a DX7 bulk dump (.syx: 6-byte header + 32 packed 128-byte voices)."""
    return ["".join(chr(c) if 32 <= c < 127 else " " for c in cart[6 + i * 128 + 118: 6 + i * 128 + 128]).strip()
            for i in range(32)]


# DX7 voice parameters in Dexed's names: (name, offset in the unpacked 155-byte voice, maximum value).
# Operator N's 21 bytes start at (6 - N) * 21: a DX7 voice stores OP6 first.
_DX7_OP = [("eg_rate_1", 0, 99), ("eg_rate_2", 1, 99), ("eg_rate_3", 2, 99), ("eg_rate_4", 3, 99),
           ("eg_level_1", 4, 99), ("eg_level_2", 5, 99), ("eg_level_3", 6, 99), ("eg_level_4", 7, 99),
           ("break_point", 8, 99), ("l_scale_depth", 9, 99), ("r_scale_depth", 10, 99), ("l_key_scale", 11, 3),
           ("r_key_scale", 12, 3), ("rate_scaling", 13, 7), ("a_mod_sens", 14, 3), ("key_velocity", 15, 7),
           ("output_level", 16, 99), ("mode", 17, 1), ("f_coarse", 18, 31), ("f_fine", 19, 99), ("osc_detune", 20, 14)]
_DX7_GLOBAL = [("pitch_eg_rate_1", 126, 99), ("pitch_eg_rate_2", 127, 99), ("pitch_eg_rate_3", 128, 99),
               ("pitch_eg_rate_4", 129, 99), ("pitch_eg_level_1", 130, 99), ("pitch_eg_level_2", 131, 99),
               ("pitch_eg_level_3", 132, 99), ("pitch_eg_level_4", 133, 99), ("algorithm", 134, 31),
               ("feedback", 135, 7), ("osc_key_sync", 136, 1), ("lfo_speed", 137, 99), ("lfo_delay", 138, 99),
               ("lfo_pm_depth", 139, 99), ("lfo_am_depth", 140, 99), ("lfo_key_sync", 141, 1), ("lfo_wave", 142, 5),
               ("p_mode_sens", 143, 7), ("transpose", 144, 48)]


def dx7_unpack(packed: bytes) -> list:
    """A packed 128-byte DX7 cartridge voice -> the 155-byte unpacked (single-voice) layout."""
    u = [0] * 155
    for op in range(6):
        pk, v = packed[op * 17: op * 17 + 17], op * 21
        u[v:v + 11] = pk[0:11]
        u[v + 11], u[v + 12] = pk[11] & 3, (pk[11] >> 2) & 3
        u[v + 13], u[v + 20] = pk[12] & 7, (pk[12] >> 3) & 15
        u[v + 14], u[v + 15] = pk[13] & 3, (pk[13] >> 2) & 7
        u[v + 16] = pk[14]
        u[v + 17], u[v + 18] = pk[15] & 1, (pk[15] >> 1) & 31
        u[v + 19] = pk[16]
    u[126:134] = packed[102:110]
    u[134], u[135], u[136] = packed[110] & 31, packed[111] & 7, (packed[111] >> 3) & 1
    u[137:141] = packed[112:116]
    u[141], u[142], u[143] = packed[116] & 1, (packed[116] >> 1) & 7, (packed[116] >> 4) & 7
    u[144] = packed[117]
    u[145:155] = packed[118:128]
    return u


def dx7_voice_params(cart: bytes, index: int) -> dict:
    """Dexed parameter name -> (DX7 value, maximum) for voice `index` of a 32-voice cartridge."""
    u = dx7_unpack(cart[6 + index * 128: 6 + index * 128 + 128])
    out = {name: (min(u[off], mx), mx) for name, off, mx in _DX7_GLOBAL}
    for n in range(1, 7):
        for name, off, mx in _DX7_OP:
            out[f"op{n}_{name}"] = (min(u[(6 - n) * 21 + off], mx), mx)
    return out


def _obxd_chunk(fxb: bytes) -> bytes:
    """An OB-Xd .fxb bank: a VST2 'FBCh' header, then its JUCE state blob (VC2! + XML listing every program)."""
    if fxb[:4] != b"CcnK" or fxb[8:12] != b"FBCh":
        raise RecipeError("not an OB-Xd .fxb bank")
    return fxb[160:160 + struct.unpack(">I", fxb[156:160])[0]]


def patch_index():
    """Every installed patch -> (synth, source file, program number)."""
    import html
    out = {}
    try:
        data = surge_dir() / "SurgeXTData"
        for base, prefix in ((data / "patches_factory", ""), (data / "patches_3rdparty", "3rdparty/")):
            for p in base.rglob("*.fxp"):
                out[prefix + p.relative_to(base).with_suffix("").as_posix()] = ("surge", p, 0)
    except RecipeError:
        pass
    for base in DEXED_CARTS:
        for p in sorted(base.rglob("*.syx")) if base.is_dir() else []:
            cart = p.read_bytes()
            if len(cart) == 4104:
                for i, name in enumerate(dx7_voice_names(cart)):
                    _unique(out, f"dexed:{p.stem}/{name}", ("dexed", p, i))
    for p in sorted(OBXD_BANKS.glob("*.fx[bB]")) if OBXD_BANKS.is_dir() else []:
        names = re.findall(rb'programName="([^"]*)"', _obxd_chunk(p.read_bytes()))
        for i, name in enumerate(names):
            _unique(out, f"obxd:{p.stem}/{html.unescape(name.decode('utf-8', 'replace')).strip()}", ("obxd", p, i))
    return out


_JUCE_B64 = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"


def _juce_base64(data: bytes) -> str:
    """JUCE MemoryBlock::toBase64Encoding: '<size>.' + 6-bit little-endian chunks in JUCE's alphabet."""
    n = int.from_bytes(data, "little")
    return f"{len(data)}." + "".join(_JUCE_B64[(n >> (6 * i)) & 63] for i in range((len(data) * 8 + 5) // 6))


def _juce_xml_blob(xml: bytes) -> bytes:
    """JUCE copyXmlToBinary: 'VC2!' + little-endian size + XML + NUL."""
    return b"VC2!" + struct.pack("<I", len(xml) + 1) + xml + b"\0"


def _xml_of_blob(blob: bytes) -> bytes:
    return blob[8:8 + struct.unpack("<I", blob[4:8])[0] - 1]


class Synths:
    """Hosts Surge XT, Dexed and OB-Xd (each loaded on first use) and renders MIDI through the current patch."""

    def __init__(self, sample_rate=44100):
        self.rate = sample_rate
        self.plugins = {}
        self.plugin = None
        self.patches = patch_index()

    def _plugin(self, kind):
        from pedalboard import load_plugin
        if kind not in self.plugins:
            bundle = surge_dir() / "Surge XT.vst3" if kind == "surge" else DEXED_VST3 if kind == "dexed" else OBXD_VST3
            if not bundle.exists():
                raise SynthMissing(kind, f"{kind} plugin not found at {bundle} (see SAMPLING.md, Setup)")
            self.plugins[kind] = load_plugin(str(bundle / "Contents" / "x86_64-win" / bundle.name)
                                             if os.name == "nt" else str(bundle))
        return self.plugins[kind]

    def _set_state(self, component: bytes):
        xml = ('<?xml version="1.0" encoding="UTF-8"?> <VST3PluginState><IComponent>'
               f"{_juce_base64(component)}</IComponent></VST3PluginState>").encode()
        self.plugin.raw_state = _juce_xml_blob(xml)
        self.plugin([], duration=0.05, sample_rate=self.rate, reset=False)  # plugins apply state on the next block

    def load(self, patch):
        kind, path, program = self.patches.get(patch) or (("surge", Path(patch), 0) if Path(patch).is_file()
                                                          else (None, None, None))
        want = patch.split(":")[0] if patch.startswith(("dexed:", "obxd:")) else "surge"
        if kind is None and want == "dexed" and all(k != "dexed" for k, _, _ in self.patches.values()):
            self._plugin("dexed")  # a fresh Dexed writes its bundled cartridges on its first load
            self.patches = patch_index()
            kind, path, program = self.patches.get(patch) or (None, None, None)
        if kind is None:
            if all(k != want for k, _, _ in self.patches.values()):  # no patch of that synth at all: it is not installed
                raise SynthMissing(want, f"'{patch}' needs {dict(surge='Surge XT', dexed='Dexed', obxd='OB-Xd')[want]}, "
                                         "which is not installed (see SAMPLING.md, Setup)")
            close = [k for k in self.patches if patch.split("/")[-1].lower() in k.lower()][:5]
            raise RecipeError(f"unknown patch '{patch}'" + (f"; did you mean: {', '.join(close)}" if close else ""))
        self.plugin = self._plugin(kind)
        if kind == "surge":
            fxp = path.read_bytes()
            if fxp[:4] != b"CcnK" or fxp[8:12] != b"FPCh":
                raise RecipeError(f"{path} is not a Surge .fxp patch")
            self._set_state(fxp[60:])  # a Surge .fxp is a 60-byte VST2 preset header + the plugin's state blob
        elif kind == "dexed":
            # Dexed ignores voice data in a restored state, so set the voice through its parameters, which are
            # exactly the DX7's (a parameter's normalized value is the DX7 value / its maximum).
            for name, (value, maximum) in dx7_voice_params(path.read_bytes(), program).items():
                self.plugin.parameters[name].raw_value = value / maximum
            self.plugin([], duration=0.05, sample_rate=self.rate, reset=False)
        else:  # obxd: the bank's own state blob, with the wanted program selected
            xml = re.sub(rb'currentProgram="\d+"', b'currentProgram="%d"' % program,
                         _xml_of_blob(_obxd_chunk(path.read_bytes())), count=1)
            self._set_state(_juce_xml_blob(xml))

    def set_params(self, params):
        for name, value in (params or {}).items():
            if name not in self.plugin.parameters:
                close = [p for p in self.plugin.parameters if name.lower() in p.lower()][:6]
                raise RecipeError(f"unknown parameter '{name}'" + (f"; similar: {', '.join(close)}" if close else ""))
            setattr(self.plugin, name, value)

    def render(self, events, seconds):
        """events: [(midi_note, velocity, start_s, end_s)]. Returns float32 array (channels, frames)."""
        from mido import Message
        msgs = []
        for note, vel, start, end in events:
            msgs.append(Message("note_on", note=note, velocity=vel, time=start))
            msgs.append(Message("note_off", note=note, velocity=0, time=end))
        msgs.sort(key=lambda m: m.time)
        self.plugin.reset()  # flush voices and effect tails from the previous render; keeps the patch
        self.plugin([], duration=0.05, sample_rate=self.rate, reset=False)
        return self.plugin(msgs, duration=seconds, sample_rate=self.rate, reset=False)


# ---------------------------------------------------------------- recipe

def _note(value, where):
    try:
        n = notation.parse_note(str(value))
    except notation.NotationError as e:
        raise RecipeError(f"{where}: {e}")
    if n >= 120:
        raise RecipeError(f"{where}: '{value}' is not a pitch")
    return n


def _events(spec, where):
    """Returns (events, seconds_to_render, root_note) for note / chord / phrase specs."""
    vel = int(spec.get("velocity", 100))
    hold, tail = float(spec.get("hold", 1.0)), float(spec.get("tail", 0.5))
    if "phrase" in spec:
        ph = spec["phrase"]
        bpm = float(ph["bpm"])
        beat = 60.0 / bpm
        events = []
        for item in ph["notes"]:
            note, start, length = item[0], float(item[1]), float(item[2])
            v = int(item[3]) if len(item) > 3 else vel
            events.append((_note(note, where), v, start * beat, (start + length) * beat))
        length_beats = float(ph.get("length", max(e[3] for e in events) / beat))
        root = _note(ph.get("root", ph["notes"][0][0]), where)
        return events, length_beats * beat + tail, root
    if "chord" in spec:
        notes = [_note(n, where) for n in spec["chord"]]
        return [(n, vel, 0.0, hold) for n in notes], hold + tail, notes[0]
    n = _note(spec["note"], where)
    return [(n, vel, 0.0, hold)], hold + tail, n


def estimate_pitch(x, rate, fmin=30.0, fmax=2000.0):
    """YIN pitch estimate on a mono float array. Returns (Hz, aperiodicity 0..1); None if too short.
    ponytail: single-frame YIN, octave errors possible on sub-oscillator-heavy patches; treat as a hint."""
    import numpy as np
    tmax, tmin = int(rate / fmin), int(rate / fmax)
    w = 2 * tmax
    if len(x) < w + tmax:
        return None
    x = x[: w + tmax]
    d = np.array([np.sum((x[:w] - x[t:t + w]) ** 2) for t in range(tmax + 1)])
    cm = np.ones_like(d)
    cm[1:] = d[1:] * np.arange(1, len(d)) / np.maximum(np.cumsum(d[1:]), 1e-12)
    for t in range(tmin, tmax):
        if cm[t] < 0.12:
            while t + 1 < tmax and cm[t + 1] < cm[t]:
                t += 1
            return rate / t, float(cm[t])
    t = tmin + int(np.argmin(cm[tmin:tmax]))
    return rate / t, float(cm[t])


def load_files(files, rate, where):
    """Read one audio file (WAV, FLAC, AIFF, OGG, MP3) or mix several (e.g. close + overhead mics), resampled
    to `rate`. Returns float32 (channels, frames)."""
    import numpy as np
    from pedalboard.io import AudioFile
    parts = []
    for f in [files] if isinstance(files, (str, Path)) else files:
        if not Path(f).is_file():
            raise RecipeError(f"{where}: file not found: {f}")
        with AudioFile(str(f)).resampled_to(rate) as a:
            parts.append(a.read(a.frames))
    chans, frames = max(p.shape[0] for p in parts), max(p.shape[1] for p in parts)
    out = np.zeros((chans, frames), np.float32)
    for p in parts:
        out[:, :p.shape[1]] += p  # a mono part broadcasts to every channel
    return out


def fx_chain(fx, where="fx"):
    """`fx:` list -> pedalboard.Pedalboard. Items are an effect name or {name: {parameter: value}}; names are
    pedalboard's effect classes in any case, with or without underscores (highpass_filter = HighpassFilter)."""
    if not fx:  # nothing to print: no pedalboard needed (a numpy-only source renders without it)
        return lambda x, rate: x
    import pedalboard
    effects = {n.lower(): getattr(pedalboard, n) for n in dir(pedalboard)
               if isinstance(getattr(pedalboard, n), type) and issubclass(getattr(pedalboard, n), pedalboard.Plugin)
               and not n.startswith("_") and n not in ("Plugin", "Pedalboard", "Chain", "Mix", "PluginContainer",
                                                       "ExternalPlugin", "VST3Plugin", "AudioUnitPlugin")}
    chain = []
    for item in fx or []:
        if not isinstance(item, str) and not (isinstance(item, dict) and len(item) == 1):
            raise RecipeError(f"{where}: each fx item is one effect, e.g. {{reverb: {{room_size: 0.7}}}}; got {item}")
        name, params = (item, {}) if isinstance(item, str) else (next(iter(item)), next(iter(item.values())) or {})
        cls = effects.get(str(name).lower().replace("_", ""))  # Reverb, reverb, HighpassFilter, highpass_filter
        if cls is None:
            raise RecipeError(f"{where}: unknown effect '{name}' (available: {', '.join(sorted(effects))})")
        try:
            chain.append(cls(**params))
        except TypeError as e:
            raise RecipeError(f"{where}: {name}: {e}")
    return pedalboard.Pedalboard(chain)


def _post(audio, spec, rate):
    import numpy as np
    x = np.asarray(audio, dtype=np.float64)
    if spec.get("fx"):
        # Effects run on the take peak-normalized to -1 dBFS (so bitcrush and distortion act the same at any
        # recording level) plus fx_tail seconds of silence, so reverb and delay tails ring out; trimming below
        # then cuts whatever stays silent.
        pad = int(float(spec.get("fx_tail", 1.0)) * rate)
        x = np.pad(x, ((0, 0), (0, pad))) * (0.891 / max(np.abs(x).max(), 1e-9))
        if x.shape[0] == 1 and not spec.get("mono", False):
            x = np.repeat(x, 2, axis=0)  # stereo effects (reverb width, chorus) need two channels
        x = fx_chain(spec["fx"])(x.astype(np.float32), rate).astype(np.float64)
    if spec.get("mono", False):
        x = x.mean(axis=0, keepdims=True)
    if spec.get("reverse", False):
        x = x[:, ::-1]
    trim = spec.get("trim", True)
    if trim:
        level = np.abs(x).max(axis=0)
        thresh = level.max() * 10 ** (-60 / 20)
        idx = np.nonzero(level > thresh)[0]
        if len(idx):
            start = max(0, idx[0] - int(0.001 * rate))
            end = idx[-1] + 1 if not spec.get("loop") else x.shape[1]
            x = x[:, start:end]
    loop = None
    if spec.get("loop"):
        lp = spec["loop"]
        s, e = int(float(lp["start"]) * rate), int(float(lp["end"]) * rate)
        xf = int(float(lp.get("crossfade", 0.0)) * rate)
        if not 0 <= s < e <= x.shape[1]:
            raise RecipeError(f"loop {lp} is outside the rendered {x.shape[1] / rate:.2f} s (after trimming)")
        xf = min(xf, s, e - s)
        if xf:
            # Bake an equal-power crossfade: the end of the loop fades into the audio just before its start,
            # so wrapping from end to start is seamless.
            t = np.linspace(0, np.pi / 2, xf, endpoint=False)
            x[:, e - xf:e] = x[:, e - xf:e] * np.cos(t) + x[:, s - xf:s] * np.sin(t)
        x = x[:, :e]
        loop = (s, e, lp.get("type", "forward") == "pingpong")
    elif spec.get("fade_out", 0.01):
        n = min(x.shape[1], int(float(spec.get("fade_out", 0.01)) * rate))
        if n:
            x[:, -n:] *= np.linspace(1, 0, n)
    peak = np.abs(x).max()
    if spec.get("normalize") is not None and peak > 0:
        x *= 10 ** (float(spec["normalize"]) / 20) / peak
    x *= 10 ** (float(spec.get("gain", 0)) / 20)
    x = np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)
    return x, loop


def expand(recipe):
    """Yield (output name, merged spec) for every sample, expanding `notes:` lists."""
    defaults = recipe.get("defaults") or {}
    for name, spec in (recipe.get("samples") or {}).items():
        where = f"sample '{name}'"
        if not isinstance(spec, dict):
            raise RecipeError(f"{where} must be a mapping")
        unknown = set(spec) - set(SAMPLE_KEYS)
        if unknown:
            raise RecipeError(f"{where}: unknown keys {sorted(unknown)} (allowed: {', '.join(SAMPLE_KEYS)})")
        if sum(k in spec for k in ("patch", "file", "resynth")) != 1:
            raise RecipeError(f"{where}: needs exactly one of 'patch' (a synth), 'file' (audio file) or 'resynth' "
                              "(a target rebuilt from a corpus)")
        merged = {**defaults, **spec}
        if "resynth" in spec:
            rs = spec["resynth"]
            if not isinstance(rs, dict) or not rs.get("target") or not rs.get("corpus"):
                raise RecipeError(f"{where}: resynth needs target (a WAV) and corpus (WAVs, globs or folders)")
            bad = set(rs) - set(RESYNTH_KEYS)
            if bad:
                raise RecipeError(f"{where}: resynth: unknown keys {sorted(bad)} (allowed: {', '.join(RESYNTH_KEYS)})")
        if "file" in spec or "resynth" in spec:
            if "notes" in spec or "chord" in spec or "phrase" in spec:
                raise RecipeError(f"{where}: 'file' and 'resynth' samples take 'note' (the recorded pitch), not "
                                  "notes/chord/phrase")
            yield name, merged
            continue
        if "notes" in spec:
            for n in spec["notes"]:
                one = {k: v for k, v in merged.items() if k != "notes"}
                one["note"] = n
                one["_name_by_root"] = True
                yield name, one
        else:
            if not any(k in merged for k in ("note", "chord", "phrase")):
                raise RecipeError(f"{where}: needs one of note, notes, chord, phrase")
            yield name, merged


def _load_recipe(path):
    """(recipe dict, sample rate, output directory) of the recipe at `path`, its top level checked."""
    recipe = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(recipe, dict):
        raise RecipeError("a recipe is a mapping with out_dir, sample_rate, defaults and samples")
    unknown = set(recipe) - set(RECIPE_KEYS)
    if unknown:
        raise RecipeError(f"unknown top-level keys {sorted(unknown)} (allowed: {', '.join(RECIPE_KEYS)})")
    return recipe, int(recipe.get("sample_rate", 44100)), (Path(path).parent / recipe.get("out_dir", ".")).resolve()


def _job_root(name, spec):
    """(output name, sounding root) of one expanded job, without rendering it."""
    where = f"sample '{name}'"
    root = _note(spec.get("note", "C-5"), where) if "file" in spec or "resynth" in spec else _events(spec, where)[2]
    root += int(spec.get("root_offset", 0))  # patches that sound in a different octave than the key played
    if not 0 <= root < 120:
        raise RecipeError(f"{where}: root_offset moves the root outside C-0..B-9")
    if spec.get("_name_by_root"):  # notes: lists become name_c3.wav, name_fs4.wav, ... named by sounding pitch
        name = f"{name}_{notation.format_note(root).replace('#', 's').replace('-', '').lower()}"
    return name, root


def recipe_outputs(path):
    """What the recipe at `path` writes, without rendering: [(WAV path, sample name, the key for a `notes:` entry or
    None)]. RecipeError when the recipe is not valid."""
    recipe, _, out_dir = _load_recipe(path)
    out = []
    for name, spec in expand(recipe):
        file, _ = _job_root(name, spec)
        out.append((out_dir / f"{file}.wav", name, spec.get("note") if spec.get("_name_by_root") else None))
    return out


def recipe_entry(path, name):
    """(the sample entry `name` as the recipe writes it, the recipe's defaults)."""
    recipe, _, _ = _load_recipe(path)
    spec = (recipe.get("samples") or {}).get(name)
    if not isinstance(spec, dict):
        raise RecipeError(f"the recipe has no sample '{name}'")
    return spec, recipe.get("defaults") or {}


def render_one(path, name, spec=None, note=None, out=None, log=print):
    """Render one sample of the recipe at `path`: entry `name`, or `spec` in its place (an edited entry, merged over the
    recipe's defaults like any other); for a `notes:` entry, only the key `note`. Written to `out` (default: where the
    recipe writes it). Returns (file, root, loop)."""
    recipe, rate, out_dir = _load_recipe(path)
    entry = spec if spec is not None else (recipe.get("samples") or {}).get(name)
    jobs = list(expand({"defaults": recipe.get("defaults"), "samples": {name: entry}}))
    if note is not None:
        jobs = [j for j in jobs if str(j[1].get("note")) == str(note)]
    if len(jobs) != 1:
        raise RecipeError(f"sample '{name}': {'no key ' + str(note) if note is not None else 'a notes: list'}; give one key")
    fx_chain(jobs[0][1].get("fx"), f"sample '{name}'")
    synths = Synths(rate) if "patch" in jobs[0][1] else None
    return _render_job(Path(path), rate, synths, *jobs[0], out_dir, log, out)


def render_recipe(path, only=None, log=print):
    path = Path(path)
    recipe, rate, out_dir = _load_recipe(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = list(expand(recipe))  # validate everything before the slow part
    for name, spec in jobs:
        fx_chain(spec.get("fx"), f"sample '{name}'")
    surge = Synths(rate) if any("patch" in spec for _, spec in jobs) else None
    return [_render_job(path, rate, surge, name, spec, out_dir, log) for name, spec in jobs
            if not only or fnmatch.fnmatch(name, only)]


def _render_job(path, rate, surge, name, spec, out_dir, log, file=None):
    """One expanded sample of the recipe at `path` rendered and written (to `file`, default out_dir/<name>.wav)."""
    name, root = _job_root(name, spec)
    where = f"sample '{name}'"
    if "file" in spec:
        files = spec["file"] if isinstance(spec["file"], list) else [spec["file"]]
        source = " + ".join(Path(f).name for f in files)
        audio = load_files([path.parent / f for f in files], rate, where)
        start = int(float(spec.get("start", 0)) * rate)
        end = start + int(float(spec["length"]) * rate) if "length" in spec else None
        audio = audio[:, start:end]  # the fade_out below smooths a cut end
    elif "resynth" in spec:
        audio, source = _resynth(path, spec, rate, where, log)
    else:
        events, seconds, _ = _events(spec, where)
        source = spec["patch"]
        surge.load(spec["patch"])
        surge.set_params(spec.get("params"))
        audio = surge.render(events, seconds)
    pcm, loop = _post(audio, spec, rate)
    if not pcm.any():
        raise RecipeError(f"{where}: '{source}' rendered silence (try a longer hold or another note)")
    file = Path(file) if file else out_dir / f"{name}.wav"
    file.parent.mkdir(parents=True, exist_ok=True)
    write_wav(file, rate, [ch.tolist() for ch in pcm], 16, loop=loop, root_note=root)
    secs = pcm.shape[1] / rate
    log(f"{file.name:28s} {secs:6.2f} s  {'stereo' if pcm.shape[0] == 2 else 'mono  '}  "
        f"root {notation.format_note(root)}{'  loop %.2f-%.2f s' % (loop[0] / rate, loop[1] / rate) if loop else ''}"
        f"  <- {source}")
    mono = pcm.astype(float).mean(axis=0) / 32768
    # A file sample without a note: is taken as unpitched (drums); everything else gets its pitch checked.
    est = (None if ("file" in spec or "resynth" in spec) and "note" not in spec
           else estimate_pitch(mono[int(0.05 * rate):], rate))
    if est and est[1] < 0.1:
        off = 12 * __import__("math").log2(est[0] / (440 * 2 ** ((root - 69) / 12)))
        if abs(off) > 0.5:
            log(f"  warning: '{name}' sounds about {off:+.1f} semitones from its root "
                f"{notation.format_note(root)}; if the patch is octave-shifted set root_offset: {round(off):+d}")
    return file, root, loop


def _wavs(base, items, where):
    """WAV paths from a list of files, globs and folders (relative to `base`), sorted within each item, no repeats."""
    import glob as _glob
    from .library import walk
    out = []
    for item in [items] if isinstance(items, str) else items:
        p = Path(base, str(item))
        found = walk([p]) if p.is_dir() else sorted(f for f in _glob.glob(str(p), recursive=True)
                                                    if f.lower().endswith(".wav")) or ([str(p)] if p.is_file() else [])
        if not found:
            raise RecipeError(f"{where}: resynth: nothing matches {item}")
        out += [str(Path(f).resolve()) for f in found]
    return list(dict.fromkeys(out))


def _read_mono(f, rate, seconds=None):
    """A WAV as mono float64 at `rate` (numpy only), its first `seconds` (at its own rate) when given."""
    import numpy as np
    from .library import read_audio
    from .resample import resample
    x, r, _ = read_audio(f, seconds)
    return resample(x, r, rate) if r != rate else np.asarray(x, float)


def _resynth(path, spec, rate, where, log):
    """The `resynth:` source: its target (cut by start/length) rebuilt from blocks of its corpus (mosaic.resynth), read
    at the recipe's rate; the corpus files are read in order until corpus_seconds of them. Returns (1 x frames, label)."""
    from . import mosaic
    rs = {**RESYNTH_KEYS, **spec["resynth"]}
    target = _wavs(path.parent, rs["target"], where)
    x = _read_mono(target[0], rate)
    start = int(float(spec.get("start", 0)) * rate)
    x = x[start: start + int(float(spec["length"]) * rate) if "length" in spec else None]
    corpus, total = [], 0.0
    for f in _wavs(path.parent, rs["corpus"], where):
        if Path(f) == Path(target[0]).resolve():
            continue
        try:
            c = _read_mono(f, rate, max(0.1, float(rs["corpus_seconds"]) - total))
        except (OSError, ValueError) as e:
            log(f"  skipped {Path(f).name}: {e}")
            continue
        corpus.append(c)
        total += len(c) / rate
        if total >= float(rs["corpus_seconds"]):
            break
    try:
        y, info = mosaic.resynth(x, corpus, rate, float(rs["block"]), int(rs["overlap"]), int(rs["variety"]),
                                 float(rs["reuse"]), float(rs["level"]), float(rs["mix"]), int(rs["seed"]), float(rs["gate"]))
    except ValueError as e:
        raise RecipeError(f"{where}: resynth: {e}")
    peak = float(abs(y).max())
    if peak > 0.999:  # blocks brought to the target's level can overshoot it: scaled under full scale, never clipped
        y = y * (0.999 / peak)
    log(f"  resynth: {info['blocks']} blocks of {Path(target[0]).name} from {info['corpus_blocks']} blocks of "
        f"{len(corpus)} files ({total:.1f} s), {info['distinct']} distinct"
        + (f"; {20 * __import__('math').log10(peak / 0.999):.1f} dB down to stay under full scale" if peak > 0.999 else ""))
    return y[None, :], f"resynth {Path(target[0]).name} <- {len(corpus)} files"


def audition(pattern, out_wav, note="C-4", hold=1.5, tail=1.0, rate=44100, log=print):
    """Render every synth patch matching a glob (e.g. 'Pads/*') back to back into one WAV, with a time index.
    If the glob matches audio files on disk instead (e.g. 'tools/cc0/bigrusty/Samples/kick_24/**/*.flac'),
    those are played back to back, each cut to hold + tail seconds."""
    import glob
    import numpy as np
    files = sorted(f for f in glob.glob(pattern, recursive=True)
                   if Path(f).suffix.lower() in (".wav", ".flac", ".aif", ".aiff", ".ogg", ".mp3"))
    surge = None if files else Synths(rate)
    names = files or sorted(k for k in surge.patches if fnmatch.fnmatch(k, pattern))
    if not names:
        raise RecipeError(f"no patches or audio files match '{pattern}'")
    n = _note(note, "audition")
    parts, t = [], 0.0
    gap = np.zeros((2, int(0.4 * rate)))
    for name in names:
        if files:
            a = load_files(name, rate, "audition")[:, :int((hold + tail) * rate)]
            a = np.broadcast_to(a, (2, a.shape[1]))  # mono files play in both channels
        else:
            surge.load(name)
            a = surge.render([(n, 100, 0.0, hold)], hold + tail)
        peak = np.abs(a).max()
        if peak > 0:
            a = a / peak * 0.8
        log(f"{int(t // 60)}:{t % 60:05.2f}  {name}")
        parts += [a, gap]
        t += (a.shape[1] + gap.shape[1]) / rate
    x = np.clip(np.round(np.concatenate(parts, axis=1) * 32767), -32768, 32767).astype(np.int16)
    write_wav(out_wav, rate, [ch.tolist() for ch in x])
    return names


def list_params(filter_text=""):
    surge = Synths()
    surge.plugin = surge._plugin("surge")
    return [p for p in surge.plugin.parameters if re.search(filter_text, p, re.I)]
