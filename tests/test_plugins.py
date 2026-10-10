"""OpenMPT's DMO mix plugins in the song format: compiled into the .it as OpenMPT saves them, played by libopenmpt,
automated with an SFx macro and Zxx, imported back from the .it, and refused when malformed."""
import base64
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from vulturetracker import api, plugins
from vulturetracker.itreader import module_to_song, read_it
from vulturetracker.openmpt import LoadedModule
from vulturetracker.song import SongError
from vulturetracker.wavload import write_wav

SONG = """\
module:
  title: plugins
  tempo: 125
  speed: 6
  channels: [{name: Hit, plugin: 1}]
{module_extra}samples:
  1: {file: hit.wav, name: hit}
patterns:
  p:
    rows: 64
    data: |
{rows}orders: [p]
"""
ECHO = "  plugins:\n    1: {effect: echo, name: Hit echo, wet_dry: 50, feedback: 50, left_delay: 500, right_delay: 500}\n"


def compile_song(d, module_extra=ECHO, z0="...", z1="...", channel_plugin=True):
    t = np.arange(int(0.08 * 44100)) / 44100
    write_wav(d / "hit.wav", 44100, [np.round(20000 * np.sin(2 * np.pi * 440 * t) * np.exp(-t * 60)).astype(int).tolist()])
    rows = "".join(f"      {r:02d}: {'C-5 01 ... ' + (z0 if r == 0 else z1) if r in (0, 32) else '... .. ... ...'}\n"
                   for r in range(64))
    text = SONG.replace("{module_extra}", module_extra).replace("{rows}", rows)
    if not channel_plugin:
        text = text.replace(", plugin: 1", "")
    return api.compile_song(api.from_yaml(text), d)[0]


def level(it, ms, at=0.0):
    """dBFS RMS over 50 ms, `ms` after `at` seconds: the 80 ms hit is over by 250 ms, so energy at 500 ms is the echo."""
    with LoadedModule(it) as lm:
        x = np.frombuffer(lm.render(44100, oversample=1), "<i2").reshape(-1, 2).astype(float).mean(axis=1) / 32768
    a = int((at + ms / 1000) * 44100)
    return 20 * np.log10(np.sqrt(np.mean(x[a:a + 2205] ** 2)) + 1e-12)


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_echo_plays(self):
        dry = compile_song(self.d, "", channel_plugin=False)
        wet = compile_song(self.d)
        self.assertLess(level(dry, 500), -150)
        self.assertGreater(level(wet, 500), level(wet, 0) - 6)   # the first echo, 500 ms on
        self.assertLess(level(wet, 250), -150)                  # nothing between the hit and its echo
        unrouted = compile_song(self.d, channel_plugin=False)   # a plugin no channel plays through changes nothing
        self.assertLess(level(unrouted, 500), -150)

    def test_zxx_drives_a_parameter(self):
        # SF0 set to F0F080z makes Zxx set the channel plugin's parameter 0, the echo's wet/dry: Z00 on the hit's row
        # leaves it dry, Z7F all wet
        extra = ECHO + "  macros: {SF0: F0F080z}\n"
        self.assertLess(level(compile_song(self.d, extra, z0="Z00"), 500), -150)
        self.assertGreater(level(compile_song(self.d, extra, z0="Z7F"), 500), -40)
        self.assertEqual(plugins.plugin_param_macro(0), "F0F080z")

    def test_default_macros_keep_the_filter(self):
        # an embedded configuration keeps SF0 = cutoff, so a song's Zxx filter sweeps play as before
        cfg = plugins.macro_config({1: "F0F080z"})
        sfx, fixed = plugins.read_macro_config(cfg)
        self.assertEqual(sfx, {1: "F0F080z"})
        self.assertFalse(fixed)
        self.assertEqual(cfg[9 * 32: 9 * 32 + 7], b"F0F000z")

    def test_round_trip(self):
        extra = ("  plugins:\n    1: {effect: echo, left_delay: 375, feedback: 30, output: 2}\n"
                 "    2: {effect: waves_reverb, reverb_time: 1500, reverb_mix: -6, bypass: true, gain: 1.5}\n"
                 "  macros: {SF2: F0F081z}\n")
        it = compile_song(self.d, extra)
        mod, warnings = read_it(it)
        self.assertEqual(mod.channels[0].plugin, 1)
        self.assertEqual(mod.channels[0].name, "Ch 1")
        self.assertEqual(mod.macros, {2: "F0F081z"})
        self.assertEqual(sorted(mod.plugins), [1, 2])
        song = module_to_song(mod, self.d / "back.yaml", self.d / "back")
        p = song["module"]["plugins"]
        self.assertEqual((p[1]["effect"], p[1]["left_delay"], p[1]["feedback"], p[1]["output"]), ("echo", 375, 30, 2))
        self.assertEqual((p[2]["reverb_time"], p[2]["reverb_mix"], p[2]["bypass"], p[2]["gain"]), (1500, -6, True, 1.5))
        self.assertEqual(song["module"]["macros"], {"SF2": "F0F081z"})
        self.assertEqual(song["module"]["channels"][0]["plugin"], 1)
        self.assertFalse([w for w in warnings if "plugin" in w or "macro" in w], warnings)

    def test_every_effect_compiles_with_its_defaults(self):
        extra = "  plugins:\n" + "".join(f"    {i}: {{effect: {e}}}\n" for i, e in enumerate(plugins.EFFECTS, 1))
        mod, _ = read_it(compile_song(self.d, extra))
        self.assertEqual([p["effect"] for _, p in sorted(mod.plugins.items())], list(plugins.EFFECTS))
        for p in mod.plugins.values():
            for s, v in zip(plugins.params_of(p["effect"]), p["params"]):
                self.assertAlmostEqual(v, s[4], places=6)

    def test_errors(self):
        for extra, msg in [
            ("  plugins:\n    1: {effect: phaser}\n", "'effect' must be one of"),
            ("  plugins:\n    1: {effect: echo, left_delay: 5000}\n", "out of range 1..2000"),
            ("  plugins:\n    1: {effect: echo, waveform: sine}\n", "unknown key 'waveform'"),
            ("  plugins:\n    1: {effect: echo, output: 2}\n    2: {effect: echo, output: 1}\n", "loop back"),
            ("  plugins:\n    1: {effect: echo, output: 3}\n", "is not a plugin of this song"),
            ("  plugins:\n    1: {effect: chorus, waveform: triangle}\n", "must be one of square, sine"),
            ("  plugins:\n    1: {effect: echo}\n  macros: {SF1: 'hello!'}\n", "MIDI macro text"),
            ("  plugins:\n    2: {effect: echo}\n", "'plugin' must be a plugin number"),
        ]:
            with self.subTest(msg), self.assertRaises(SongError) as cm:
                compile_song(self.d, extra)
            self.assertIn(msg, str(cm.exception))

    def test_rack_gain_roundtrip_and_bypass_audio(self):
        # The Rack sends to_song's values back on EVERY edit, including bypass/removal of another device.
        for effect in plugins.EFFECTS:
            with self.subTest(effect=effect):
                extra = f"  plugins:\n    1: {{effect: {effect}, output_gain: 1.5}}\n"
                mod, _ = read_it(compile_song(self.d, extra))
                entries = plugins.to_song(mod.plugins)
                entries[1]["bypass"] = True
                again, _ = read_it(compile_song(self.d, "  plugins: " + api.safe_dump(entries, default_flow_style=True)))
                self.assertEqual(again.plugins[1]["gain"], 1.5)
                self.assertTrue(again.plugins[1]["bypass"])
                np.testing.assert_allclose(again.plugins[1]["params"], mod.plugins[1]["params"], atol=1e-4)
        for effect, db in (("distortion", -30), ("compressor", -12), ("param_eq", -6)):
            mod, _ = read_it(compile_song(self.d, f"  plugins:\n    1: {{effect: {effect}, gain: {db}}}\n"))
            self.assertEqual(plugins.to_song(mod.plugins)[1]["gain"], db)
            self.assertEqual(mod.plugins[1].get("gain", 1.0), 1.0)
        for entry in ("effect: echo, gain: 2, output_gain: 3", "effect: distortion, output_gain: -18"):
            with self.assertRaises(SongError):
                compile_song(self.d, f"  plugins:\n    1: {{{entry}}}\n")
        def pcm(extra, routed=True):
            with LoadedModule(compile_song(self.d, extra, channel_plugin=routed)) as lm:
                return np.frombuffer(lm.render(44100, max_seconds=0.2, oversample=1), '<i2')
        dry = pcm('', False)
        wet = pcm('  plugins:\n    1: {effect: distortion}\n')
        bypass = pcm('  plugins:\n    1: {effect: distortion, bypass: true}\n')
        np.testing.assert_array_equal(bypass, dry)
        self.assertGreater(np.max(np.abs(wet.astype(int) - dry.astype(int))), 100)

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_page_engine_plays_them(self):
        # the app's live engine (libopenmpt as WebAssembly, tests/engine_check.js) renders the echo as the DLL does
        it = compile_song(self.d)
        (self.d / "song.it").write_bytes(it)
        rate = 48000
        with LoadedModule(it) as lm:
            frames = int(lm.duration() * rate)
            ref = np.frombuffer(lm.render(rate, oversample=1), "<i2").astype(int)[: 2 * frames]
        root = Path(__file__).resolve().parent.parent
        out = subprocess.run([shutil.which("node"), str(root / "tests" / "engine_check.js"), str(self.d / "song.it"),
                              str(rate), str(frames), "0", "0", "60"], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        plain = np.frombuffer(base64.b64decode(json.loads(out.stdout)["plain"]), "<i2").astype(int)
        echo = slice(2 * int(0.5 * rate), 2 * int(0.55 * rate))
        self.assertGreater(np.abs(plain[echo]).max(), 1000)
        from vulturetracker.openmpt import library_version
        if library_version().startswith("0.8.9"):  # the same build as the page's: the same samples (CI's system 0.7.x:
            self.assertLessEqual(np.abs(plain - ref).max(), 4)  # its echo is checked above, its samples not compared)

    def test_units(self):
        spec = plugins.params_of("echo")[2]
        self.assertEqual(plugins.to_unit(spec, plugins.from_unit(spec, 375)), 375)
        phase = plugins.params_of("chorus")[4]
        self.assertEqual(plugins.from_unit(phase, "90"), 0.75)
        self.assertEqual(plugins.to_unit(phase, 0.75), "90")


class RackEditTests(unittest.TestCase):
    """The RACK tab's song edits: `plugins` rewrites module.plugins / module.macros whole, `channel_plugin` sets or
    clears a channel's plugin, each keeping the rest of the file as written and undoing back to it."""

    def setUp(self):
        from tests.test_gui import RATE, SONG_BLOCK, sine
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        write_wav(self.d / "a.wav", RATE, [sine(440)], root_note=69)
        write_wav(self.d / "b.wav", RATE, [sine(880)])
        (self.d / "song.yaml").write_bytes(SONG_BLOCK.encode("utf-8"))
        self.original = SONG_BLOCK
        self.states = []

    def tearDown(self):
        from tests.test_gui import TestGui
        TestGui.tearDown(self)

    def test_rack_edits(self):
        from vulturetracker import gui
        st = gui.State(self.d / "song.yaml")
        self.states.append(st)
        read = lambda: (self.d / "song.yaml").read_bytes().decode("utf-8")  # noqa: E731
        echo = {"effect": "echo", "left_delay": 375, "feedback": 30, "output": 2}
        verb = {"effect": "waves_reverb", "reverb_time": 1500}
        st.song_edit([{"op": "plugins", "plugins": {"1": echo, "2": verb}, "macros": {"SF1": "F0F080z"}},
                      {"op": "channel_plugin", "ch": 1, "plugin": 1}])
        text = read()
        self.assertIn("  plugins:\n    1: {effect: echo, left_delay: 375, feedback: 30, output: 2}\n"
                      "    2: {effect: waves_reverb, reverb_time: 1500}\n  macros:\n    SF1: F0F080z\n", text)
        self.assertIn("    - {name: A}\n    - {name: B, pan: 40, plugin: 1}\n", text)
        f = st.facts
        self.assertEqual(f["channel_plugins"], [0, 1])
        self.assertEqual((f["plugins"][1]["left_delay"], f["plugins"][2]["reverb_time"]), (375, 1500))
        self.assertEqual(f["macros"], {"SF1": "F0F080z"})
        self.assertIn("echo", st.snapshot()["dmo"])
        # replaced in place, then the channel's plugin cleared and the plugins removed
        st.song_edit([{"op": "plugins", "plugins": {"1": {**echo, "feedback": 60}, "2": verb}}])
        self.assertIn("    1: {effect: echo, left_delay: 375, feedback: 60, output: 2}\n", read())
        st.song_edit([{"op": "channel_plugin", "ch": 1, "plugin": 0}, {"op": "plugins", "plugins": {}, "macros": None}])
        text = read()
        self.assertNotIn("plugin", text)
        self.assertNotIn("macros", text)
        self.assertIn("    - {name: B, pan: 40}\n", text)
        # a channel entry with only a name
        st.song_edit([{"op": "plugins", "plugins": {"1": verb}}, {"op": "channel_plugin", "ch": 0, "plugin": 1}])
        self.assertIn("    - {name: A, plugin: 1}\n", read())
        with self.assertRaises(Exception):  # a channel cannot name a plugin the song does not have
            st.song_edit([{"op": "channel_plugin", "ch": 0, "plugin": 7}])
        while st.snapshot()["undo"]:
            st.undo()
        self.assertEqual(read(), self.original)


if __name__ == "__main__":
    unittest.main()
