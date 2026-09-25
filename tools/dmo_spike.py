"""Spike (chunk 7a, not part of the compiler): do OpenMPT's built-in DMO effects play from an .it we write?

OpenMPT saves mix plugins in an IT file as chunks between the pointer tables and the first instrument: `CHFX` (per channel,
the plugin it plays through: 0 none, 1.. the plugin) and `FX00`, `FX01`, ... (per plugin: a 128-byte SNDMIXPLUGININFO,
then its data: for the emulated DMO effects a type word 0 and every parameter as a float 0-1, then a modular-data length
0). libopenmpt emulates the DirectX Media Objects (Chorus, Compressor, Distortion, Echo, Flanger, Gargle, I3DL2Reverb,
ParamEq, WavesReverb) on every platform. Zxx drives a plugin parameter through the embedded MIDI macro configuration
(special bit 3): an SFx macro "F0F0 nn z" with nn = 0x80 + the parameter's index sets it to z / 127.

This tool writes such chunks into a module the compiler made (every file offset after them shifted), and measures a
one-channel song with an echo in libopenmpt 0.7.3 (ctypes, the system library in the cloud) and 0.8.9 (the app's wasm,
under node). Run: python tools/dmo_spike.py. Nothing here is used by the app or the compiler: the owner decides whether
the song format gets plugins (only OpenMPT and libopenmpt play them)."""
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DMO_MAGIC = int.from_bytes(b"DXMO", "little")
DMO = {  # name: (CLSID Data1, parameter count, defaults as OpenMPT's emulation sets them)
    "Echo": (0xEF3E932C, [0.5, 0.5, (500 - 1) / 1999, (500 - 1) / 1999, 0.0]),  # wet/dry, feedback, left ms, right ms, pan
    "Chorus": (0xEFE6629C, None), "Compressor": (0xEF011F79, None), "Distortion": (0xEF114C90, None),
    "Flanger": (0xEFCA3D92, None), "Gargle": (0xDAFD8210, None), "I3DL2Reverb": (0xEF985E71, None),
    "ParamEq": (0x120CED89, None), "WavesReverb": (0x87FC0268, None),
}


def plugin_chunk(index, name, params, gain=10):
    """`FXnn`: SNDMIXPLUGININFO (plugin ids, routing 0, mix mode 0, gain / 10, output routing 0 = master, name, library
    name), then the plugin data (type 0 and the parameters as floats), then an empty modular-data block."""
    clsid = DMO[name][0]
    info = struct.pack("<IIBBBBII3I", DMO_MAGIC, clsid, 0, 0, gain, 0, 0, 0, 0, 0, 0)
    info += name.encode().ljust(32, b"\0") + name.encode().ljust(64, b"\0")
    assert len(info) == 128
    data = struct.pack("<I", 0) + b"".join(struct.pack("<f", float(p)) for p in params)
    body = info + struct.pack("<I", len(data)) + data + struct.pack("<I", 0)
    return f"FX{index:02d}".encode() + struct.pack("<I", len(body)) + body


def midi_config(sfx=None):
    """The embedded MIDI macro configuration (4896 bytes: 9 global, 16 SFx and 128 fixed Zxx macros of 32 characters),
    OpenMPT's defaults for the global ones, `sfx` {n: macro} for SF0-SFF."""
    glb = ["FF", "FC", "", "9c n v", "9c n 0", "", "", "", "Cc p"]
    parts = [m.encode().ljust(32, b"\0") for m in glb]
    parts += [(sfx or {}).get(n, "").encode().ljust(32, b"\0") for n in range(16)]
    parts += [b"\0" * 32] * 128
    out = b"".join(parts)
    assert len(out) == 4896
    return out


def add_plugins(it, channel_plugins, plugins, sfx=None):
    """`it` with the chunks inserted after its pointer tables: `channel_plugins` [plugin number per channel (0 none,
    1 = FX00)], `plugins` [(name, params)], `sfx` a MIDI macro config ({n: macro}; special bit 3 set). Every offset after
    the insert moves: the instrument, sample header and pattern pointers, the message offset and each sample's data
    pointer."""
    it = bytearray(it)
    ordnum, insnum, smpnum, patnum = struct.unpack_from("<4H", it, 0x20)
    at = 0xC0 + ordnum + 4 * (insnum + smpnum + patnum)
    blob = midi_config(sfx) if sfx is not None else b""
    chfx = b"".join(struct.pack("<I", p) for p in channel_plugins)
    blob += b"CHFX" + struct.pack("<I", len(chfx)) + chfx
    for i, (name, params) in enumerate(plugins):
        blob += plugin_chunk(i, name, params)
    n = len(blob)
    base = 0xC0 + ordnum
    ptrs = [struct.unpack_from("<I", it, base + 4 * k)[0] for k in range(insnum + smpnum + patnum)]
    for k, p in enumerate(ptrs):
        struct.pack_into("<I", it, base + 4 * k, p + n if p >= at else p)
    for k in range(smpnum):  # each sample header's data pointer (offset 0x48 in IMPS)
        h = ptrs[insnum + k]
        data = struct.unpack_from("<I", it, h + 0x48)[0]
        if data >= at:
            struct.pack_into("<I", it, h + 0x48, data + n)
    special = struct.unpack_from("<H", it, 0x2E)[0]
    if special & 1:
        msg = struct.unpack_from("<I", it, 0x38)[0]
        struct.pack_into("<I", it, 0x38, msg + n if msg >= at else msg)
    if sfx is not None:
        struct.pack_into("<H", it, 0x2E, special | 0x08)
    return bytes(it[:at] + blob + it[at:])


SONG = """\
module:
  title: dmo spike
  tempo: 125
  speed: 6
  channels: [{name: Hit}]
samples:
  1: {file: hit.wav, name: hit}
patterns:
  p:
    rows: 64
    data: |
{rows}orders: [p]
"""


def compile_song(d, z0="...", z1="..."):
    from vulturetracker import api
    from vulturetracker.wavload import write_wav
    t = np.arange(int(0.08 * 44100)) / 44100
    write_wav(d / "hit.wav", 44100, [np.round(20000 * np.sin(2 * np.pi * 440 * t) * np.exp(-t * 60)).astype(int).tolist()])
    rows = "".join(f"      {r:02d}: {'C-5 01 ... ' + (z0 if r == 0 else z1) if r in (0, 32) else '... .. ... ...'}\n"
                   for r in range(64))
    return api.compile_song(api.from_yaml(SONG.replace("{rows}", rows)), d)[0]


def render_py(it):
    from vulturetracker.openmpt import LoadedModule
    with LoadedModule(it) as lm:
        pcm = lm.render(44100, oversample=1)
    return np.frombuffer(pcm, "<i2").reshape(-1, 2).astype(float) / 32768


NODE_JS = r"""
const fs = require('fs'), path = require('path'), WEB = process.argv[2];
const glue = new Function('libopenmpt', 'require', '__dirname', fs.readFileSync(path.join(WEB, 'libopenmpt.js'), 'utf8') + '\nreturn Module;');
const {loadOpenmpt} = require(path.join(WEB, 'engine-core.js'));
(async () => {
  const E = await loadOpenmpt(cfg => glue(cfg, require, WEB), fs.readFileSync(path.join(WEB, 'libopenmpt.wasm')));
  const out = {version: E.version};
  for (const f of process.argv.slice(3)) {
    const s = new E.Song(new Uint8Array(fs.readFileSync(f))), n = 44100 * 8, L = new Float32Array(n), R = new Float32Array(n);
    for (let i = 0; i < n; i += 1024) s.read(44100, Math.min(1024, n - i), L.subarray(i), R.subarray(i));
    out[path.basename(f)] = Buffer.from(L.buffer).toString('base64');
  }
  console.log(JSON.stringify(out));
})();
"""


def render_node(files):
    node = shutil.which("node")
    if not node:
        return None
    web = ROOT / "vulturetracker" / "web"
    with tempfile.TemporaryDirectory() as tmp:
        js = Path(tmp) / "r.js"
        js.write_text(NODE_JS)
        out = subprocess.run([node, str(js), str(web), *map(str, files)], capture_output=True, text=True, timeout=120)
    if out.returncode:
        raise RuntimeError(out.stderr)
    r = json.loads(out.stdout)
    return r.pop("version", None), {k: np.frombuffer(__import__("base64").b64decode(v), "<f4").astype(float) for k, v in r.items()}


def echo_params(wet=50, feedback=50, left_ms=500, right_ms=500, pan_delay=False):
    """The Echo's five parameters as OpenMPT stores them (0-1): wet/dry % and feedback % over 100, delays (1-2000 ms)."""
    return [wet / 100, feedback / 100, (left_ms - 1) / 1999, (right_ms - 1) / 1999, 1.0 if pan_delay else 0.0]


def levels(x, rate=44100, at=0.0, times=(0, 250, 500, 750, 1000, 1500)):
    """Level (dBFS RMS over 50 ms) at these ms after `at` seconds: the dry hit lasts 80 ms, so energy at 500 and 1000
    ms is the echo (500 ms delay), none at 250 or 750."""
    m = x if x.ndim == 1 else x.mean(axis=1)
    a = int(at * rate)
    return {ms: round(float(20 * np.log10(np.sqrt(np.mean(m[a + int(ms * rate / 1000):][:2205] ** 2)) + 1e-12)), 1)
            for ms in times}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        dry = compile_song(d)
        wet = add_plugins(dry, [1], [("Echo", echo_params())])
        # Zxx: SF0 drives the echo's wet/dry (parameter 0): Z7F all wet after the first hit, Z00 all dry after the second
        auto = add_plugins(compile_song(d, "Z7F", "Z00"), [1], [("Echo", echo_params())], sfx={0: "F0F080z"})
        files = {"dry.it": dry, "wet.it": wet, "auto.it": auto}
        for k, v in files.items():
            (d / k).write_bytes(v)
        from vulturetracker.openmpt import library_version
        print(f"libopenmpt {library_version()} (ctypes):")
        for k, v in files.items():
            x = render_py(v)
            print(f"  {k:8s} dBFS after hit 1 {levels(x)}  after hit 2 {levels(x, at=32 * 6 * 2.5 / 125)}")
        r = render_node([d / k for k in files])
        if r:
            ver, got = r
            print(f"libopenmpt {ver} (wasm, node):")
            for k, x in got.items():
                print(f"  {k:8s} dBFS after hit 1 {levels(x)}  after hit 2 {levels(x, at=32 * 6 * 2.5 / 125)}")


if __name__ == "__main__":
    main()
