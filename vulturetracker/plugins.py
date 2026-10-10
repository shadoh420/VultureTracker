"""OpenMPT's mix plugins, limited to the nine DirectX Media Object effects that OpenMPT and libopenmpt emulate on every
platform (soundlib/plugins/dmo in OpenMPT's source): their parameters in the units OpenMPT shows, the song file's
`module: plugins:` / channel `plugin:` / `module: macros:`, and the chunks OpenMPT saves them in (Load_it.cpp,
SaveMixPlugins and LoadMixPlugins; MIDIMacros.cpp for the embedded macro configuration).

A plugin's parameters are stored as floats 0..1; each one here maps linearly onto the unit OpenMPT displays (its
GetParamDisplay), or is a choice. Only OpenMPT and libopenmpt play the plugins: other players play the channels dry."""
import re
import struct

DMO_MAGIC = int.from_bytes(b"DXMO", "little")
MAX_PLUGINS = 250   # OpenMPT's MAX_MIXPLUGINS

# effect: (CLSID Data1, OpenMPT's name, [(key, unit, lo, hi, default 0..1)]); a choice has unit None and lo = its names,
# spread evenly over 0..1 (OpenMPT reads them back with its own thresholds: < 1 is square, < 0.5 triangle, ...)
EFFECTS = {
    "chorus": (0xEFE6629C, "Chorus", [
        ("wet_dry", "%", 0, 100, 0.5), ("depth", "%", 0, 100, 0.1), ("frequency", "Hz", 0, 10, 0.11),
        ("waveform", None, ["square", "sine"], None, 1.0), ("phase", None, ["-180", "-90", "0", "90", "180"], None, 0.75),
        ("feedback", "%", -99, 99, (25 + 99) / 198), ("delay", "ms", 0, 20, 0.8)]),
    "compressor": (0xEF011F79, "Compressor", [
        ("gain", "dB", -60, 60, 0.5), ("attack", "ms", 0.01, 500, 0.02), ("release", "ms", 50, 3000, 150 / 2950),
        ("threshold", "dB", -60, 0, 2 / 3), ("ratio", ":1", 1, 100, 0.02), ("predelay", "ms", 0, 4, 1.0)]),
    "distortion": (0xEF114C90, "Distortion", [
        ("gain", "dB", -60, 0, 0.7), ("edge", "%", 0, 100, 0.15), ("pre_lowpass", "Hz", 100, 8000, 1.0),
        ("post_eq_center", "Hz", 100, 8000, 0.291), ("post_eq_bandwidth", "Hz", 100, 8000, 0.291)]),
    "echo": (0xEF3E932C, "Echo", [
        ("wet_dry", "%", 0, 100, 0.5), ("feedback", "%", 0, 100, 0.5), ("left_delay", "ms", 1, 2000, 499 / 1999),
        ("right_delay", "ms", 1, 2000, 499 / 1999), ("pan_delay", None, ["no", "yes"], None, 0.0)]),
    "flanger": (0xEFCA3D92, "Flanger", [
        ("wet_dry", "%", 0, 100, 0.5), ("waveform", None, ["square", "sine"], None, 1.0),
        ("frequency", "Hz", 0, 10, 0.025), ("depth", "%", 0, 100, 1.0),
        ("phase", None, ["-180", "-90", "0", "90", "180"], None, 0.5), ("feedback", "%", -99, 99, (-50 + 99) / 198),
        ("delay", "ms", 0, 4, 0.5)]),
    "gargle": (0xDAFD8210, "Gargle", [
        ("rate", "Hz", 1, 1000, 0.02), ("waveform", None, ["triangle", "square"], None, 0.0)]),
    "i3dl2_reverb": (0xEF985E71, "I3DL2Reverb", [
        ("room", "mB", -10000, 0, 0.9), ("room_hf", "mB", -10000, 0, 0.99), ("rolloff", "", 0, 10, 0.0),
        ("decay_time", "s", 0.1, 20, 0.07), ("decay_hf_ratio", "", 0.1, 2, 0.3842105),
        ("reflections", "mB", -10000, 1000, 0.672545433), ("reflections_delay", "s", 0, 0.3, 0.233333333),
        ("reverb", "mB", -10000, 2000, 0.85), ("reverb_delay", "s", 0, 0.1, 0.11), ("diffusion", "%", 0, 100, 1.0),
        ("density", "%", 0, 100, 1.0), ("hf_reference", "Hz", 20, 20000, (5000 - 20) / 19980),
        ("quality", None, ["0", "1", "2", "3"], None, 2 / 3)]),
    "param_eq": (0x120CED89, "ParamEq", [
        ("center", "Hz", 80, 16000, (8000 - 80) / 15920), ("bandwidth", "semitones", 1, 36, 0.314286),
        ("gain", "dB", -15, 15, 0.5)]),
    "waves_reverb": (0x87FC0268, "WavesReverb", [
        ("in_gain", "dB", -96, 0, 1.0), ("reverb_mix", "dB", -96, 0, 1.0), ("reverb_time", "ms", 0.001, 3000, 1 / 3),
        ("high_freq_rt_ratio", "", 0.001, 0.999, 0.0)]),
}
BY_CLSID = {v[0]: k for k, v in EFFECTS.items()}
PLUGIN_KEYS = ["effect", "name", "output", "bypass", "gain", "output_gain", "dry", "master"]  # and the effect's parameters


def params_of(effect):
    return EFFECTS[effect][2]


def to_unit(spec, p):
    """A stored 0..1 value as the song file writes it: the unit's number (rounded to 4 significant digits) or the
    choice's name."""
    key, unit, lo, hi, _ = spec
    if unit is None:
        return lo[min(len(lo) - 1, max(0, round(p * (len(lo) - 1))))]
    v = lo + p * (hi - lo)
    v = float(f"{v:.4g}") if abs(v) < 1e4 else round(v)
    return int(v) if v == int(v) else v


def from_unit(spec, value):
    """The 0..1 value of a song file's number or choice name; ValueError when out of range."""
    key, unit, lo, hi, _ = spec
    if unit is None:
        names = [str(n) for n in lo]
        if isinstance(value, bool):
            value = "yes" if value else "no"
        if str(value) not in names:
            raise ValueError(f"'{key}' must be one of {', '.join(names)}, got {value!r}")
        return names.index(str(value)) / (len(names) - 1)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{key}' must be a number ({unit or 'ratio'}), got {value!r}")
    if not min(lo, hi) - 1e-9 <= value <= max(lo, hi) + 1e-9:
        raise ValueError(f"'{key}' = {value} is out of range {lo}..{hi}{' ' + unit if unit else ''}")
    return min(1.0, max(0.0, (value - lo) / (hi - lo)))


def describe():
    """The effects and their parameters for the app and agents: {effect: [{key, unit, min, max, default} or
    {key, choices, default}]}."""
    out = {}
    for name, (_, _, specs) in EFFECTS.items():
        out[name] = [dict(key=s[0], choices=list(s[2]), default=to_unit(s, s[4])) if s[1] is None else
                     dict(key=s[0], unit=s[1], min=s[2], max=s[3], default=to_unit(s, s[4])) for s in specs]
    return out


# ---------------------------------------------------------------- the MIDI macro configuration (MIDIMacros.cpp)

MACRO_RE = re.compile(r"^[0-9A-Fa-f cnvuxyzhmopabsSZ]{0,31}$")


def default_macros():
    """OpenMPT's MIDIMacroConfig::Reset(): the global macros, SF0 = cutoff (F0F000z), Z80-Z8F = resonance."""
    glb = ["FF", "FC", "", "9c n v", "9c n 0", "", "", "", "Cc p"]
    sfx = ["F0F000z"] + [""] * 15
    zxx = [f"F0F001{i * 8:02X}" if i < 16 else "" for i in range(128)]
    return glb, sfx, zxx


def plugin_param_macro(index):
    """OpenMPT's kSFxPlugParam: Zxx sets parameter `index` (0..383) of the channel's plugin to xx / 127."""
    return f"F0F{min(index, 0x17F) + 0x80:03X}z"


def macro_config(sfx):
    """The 4896-byte embedded configuration with SFx macros `sfx` {0..15: text} over OpenMPT's defaults."""
    glb, base, zxx = default_macros()
    base = [sfx.get(i, m) for i, m in enumerate(base)]
    out = b"".join(m.encode("ascii").ljust(32, b"\0")[:32] for m in glb + base + zxx)
    assert len(out) == 4896
    return out


def read_macro_config(raw):
    """(sfx {n: text} that differ from the defaults, fixed Zxx macros differ) of an embedded configuration."""
    texts = [raw[i * 32:(i + 1) * 32].split(b"\0", 1)[0].decode("latin-1").strip() for i in range(153)]
    _, sfx0, zxx0 = default_macros()
    sfx = {i: t for i, t in enumerate(texts[9:25]) if t.upper() != sfx0[i].upper()}
    return sfx, [t.upper() for t in texts[25:]] != [z.upper() for z in zxx0]


# ---------------------------------------------------------------- chunks (Load_it.cpp)

def plugin_chunk(index, plug):
    """`FXnn`: SNDMIXPLUGININFO (DXMO and the CLSID, routing flags, mix mode, gain x10, output routing, name, library
    name), the plugin data (type 0, then every parameter as a float), and the modular data DWRT (dry ratio) and PROG
    (-1), as SaveMixPlugins writes them."""
    clsid, lib, specs = EFFECTS[plug["effect"]]
    flags = (1 if plug.get("master") else 0) | (2 if plug.get("bypass") else 0)
    out = plug.get("output")
    routing = 0x80 + out - 1 if out else 0
    gain = max(1, min(255, round(plug.get("gain", 1.0) * 10)))
    info = struct.pack("<IIBBBBII3I", DMO_MAGIC, clsid, flags, 0, gain, 0, routing, 0, 0, 0, 0)
    info += (plug.get("name") or lib).encode("ascii", "replace")[:31].ljust(32, b"\0") + lib.encode().ljust(64, b"\0")
    assert len(info) == 128
    data = struct.pack("<I", 0) + b"".join(struct.pack("<f", float(p)) for p in plug["params"])
    extra = b"DWRT" + struct.pack("<f", float(plug.get("dry", 0.0))) + b"PROG" + struct.pack("<i", -1)
    body = info + struct.pack("<I", len(data)) + data + struct.pack("<I", len(extra)) + extra
    name = f"FX{index:02d}" if index < 100 else f"F{index:03d}"
    return name.encode() + struct.pack("<I", len(body)) + body


def chunks(plugins, channel_plugins):
    """The FX chunks for `plugins` {number 1..: plugin dict} and CHFX for `channel_plugins` [number or 0 per channel],
    in SaveMixPlugins' order."""
    out = b"".join(plugin_chunk(n - 1, p) for n, p in sorted(plugins.items()))
    last = max((i + 1 for i, p in enumerate(channel_plugins) if p), default=0)
    if last:
        out += b"CHFX" + struct.pack("<I", 4 * last) + b"".join(struct.pack("<I", p) for p in channel_plugins[:last])
    return out


def read_chunks(blob):
    """(plugins {number: dict as the song file writes it}, channel plugin numbers, warnings) from the chunks between an
    IT file's pointer tables (and its MIDI configuration) and its first instrument, sample or pattern."""
    plugins, chans, warnings = {}, [], []
    pos = 0
    while pos + 8 <= len(blob):
        code, size = blob[pos:pos + 4], struct.unpack_from("<I", blob, pos + 4)[0]
        if code in (b"IMPI", b"IMPS", b"XTPM", b"STPM") or pos + 8 + size > len(blob):
            break
        body = blob[pos + 8: pos + 8 + size]
        pos += 8 + size
        if code == b"CHFX":
            chans = [struct.unpack_from("<I", body, 4 * i)[0] for i in range(size // 4)]
        elif code[:1] == b"F" and (code[1:2] == b"X" or code[1:2].isdigit()) and code[2:].isdigit() and len(body) >= 132:
            num = int(code[2:]) + (int(code[1:2]) * 100 if code[1:2].isdigit() else 0) + 1
            id1, id2, flags, mix, gain, _, routing = struct.unpack_from("<IIBBBBI", body, 0)
            name = body[32:64].split(b"\0", 1)[0].decode("latin-1").strip()
            effect = BY_CLSID.get(id2) if id1 == DMO_MAGIC else None
            if not effect:
                lib = body[64:128].split(b"\0", 1)[0].decode("latin-1").strip()
                warnings.append(f"plugin {num} '{lib or name}' is not one of OpenMPT's built-in DMO effects; dropped")
                continue
            n = struct.unpack_from("<I", body, 128)[0]
            data = body[132:132 + n]
            specs = params_of(effect)
            vals = [s[4] for s in specs]
            if len(data) >= 4 + 4 * len(specs) and struct.unpack_from("<I", data)[0] == 0:
                vals = [min(1.0, max(0.0, v)) if v == v else 0.0 for v in struct.unpack_from(f"<{len(specs)}f", data, 4)]
            p = {"effect": effect, "params": vals}
            if name and name != EFFECTS[effect][1]:
                p["name"] = name
            if routing >= 0x80:
                p["output"] = routing - 0x80 + 1
            if flags & 2:
                p["bypass"] = True
            if flags & 1:
                p["master"] = True
            if gain not in (0, 10):
                p["gain"] = gain / 10
            if mix:
                warnings.append(f"plugin {num}: mix mode {mix} is not carried over (plays as the default mix)")
            q = 132 + n
            if q + 4 <= len(body):
                m = struct.unpack_from("<I", body, q)[0]
                extra, k = body[q + 4: q + 4 + m], 0
                while k + 8 <= len(extra):
                    tag = extra[k:k + 4]
                    if tag in (b"DWRT", b"PROG"):
                        if tag == b"DWRT":
                            dry = struct.unpack_from("<f", extra, k + 4)[0]
                            if dry == dry and dry > 0:
                                p["dry"] = round(min(1.0, dry), 4)
                        k += 8
                    else:
                        k += 8 + struct.unpack_from("<I", extra, k + 4)[0]
            plugins[num] = p
    return plugins, chans, warnings


def to_song(plugins):
    """Plugins as the song file writes them: the parameters by name in their units."""
    out = {}
    for num, p in sorted(plugins.items()):
        d = {"effect": str(p["effect"])}  # the compiler's location-tagged string is not YAML-dumpable
        quiet = {"name": "", "bypass": False, "master": False, "gain": 1.0, "dry": 0.0}  # the defaults, left out
        d.update({k: v for k, v in p.items() if k not in ("effect", "params") and quiet.get(k, object()) != v})
        if "gain" in d and any(s[0] == "gain" for s in params_of(p["effect"])):
            d["output_gain"] = d.pop("gain")  # keep the output multiplier separate from the effect's dB gain
        for spec, v in zip(params_of(p["effect"]), p["params"]):
            d[spec[0]] = to_unit(spec, v)
        out[num] = d
    return out
