"""Sampling workflow tests. The Surge render test is skipped when Surge XT / pedalboard are unavailable."""
import tempfile
import unittest
from pathlib import Path

from vulturetracker.synth import RecipeError, _post, expand
from vulturetracker.wavload import read_wav, write_wav

try:
    import numpy as np
except ImportError:  # numpy comes with pedalboard; the sampling tools need it
    np = None


class TestWavSmpl(unittest.TestCase):
    def test_loop_and_root_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.wav"
            write_wav(path, 44100, [[0, 100, -100, 50] * 100], loop=(40, 400, False), root_note=50)
            w = read_wav(path)
            self.assertEqual(w.loops, [(40, 400, False)])
            self.assertEqual(w.root, 50)
            self.assertEqual(w.channels[0][:4], [0, 100, -100, 50])


@unittest.skipIf(np is None, "numpy not installed")
class TestPost(unittest.TestCase):
    def test_crossfade_loop_is_seamless(self):
        rate = 1000
        t = np.arange(5000) / rate
        x = np.vstack([np.sin(2 * np.pi * 7.3 * t) * 0.5])  # 7.3 Hz: a plain cut at 1 s / 4 s would click
        pcm, loop = _post(x, {"loop": {"start": 1.0, "end": 4.0, "crossfade": 0.5}, "trim": False}, rate)
        self.assertEqual(loop, (1000, 4000, False))
        self.assertEqual(pcm.shape[1], 4000)
        seam = abs(int(pcm[0, 3999]) - int(pcm[0, 1000]))
        typical = np.abs(np.diff(pcm[0, 1000:4000].astype(int))).max()
        self.assertLessEqual(seam, typical + 1)  # wrapping end -> start is no bigger than a normal step

    def test_expand_notes_and_errors(self):
        jobs = list(expand({"defaults": {"hold": 2}, "samples": {"b": {"patch": "X", "notes": ["C-3", "C-4"]}}}))
        self.assertEqual([j[1]["note"] for j in jobs], ["C-3", "C-4"])
        self.assertEqual(jobs[0][1]["hold"], 2)
        with self.assertRaises(RecipeError):
            list(expand({"samples": {"b": {"patch": "X", "not": "C-3"}}}))
        with self.assertRaises(RecipeError):
            list(expand({"samples": {"b": {"note": "C-3"}}}))


try:
    import pedalboard
except ImportError:
    pedalboard = None


@unittest.skipIf(pedalboard is None, "pedalboard not installed")
class TestFilesAndFx(unittest.TestCase):
    def test_reverb_tail_rings_past_the_dry_sound(self):
        rate = 22050
        x = np.zeros((1, rate // 10))
        x[0, 0] = 1.0  # a click
        dry, _ = _post(x, {"trim": True}, rate)
        wet, _ = _post(x, {"fx": [{"reverb": {"room_size": 0.9, "wet_level": 0.5}}], "fx_tail": 2.0}, rate)
        self.assertLess(dry.shape[1], 100)  # trimmed to the click
        self.assertEqual(wet.shape[0], 2)  # a mono source becomes stereo for the reverb
        self.assertGreater(wet.shape[1], rate // 2)  # the tail survives trimming

    def test_fx_errors(self):
        from vulturetracker.synth import fx_chain
        self.assertEqual(len(fx_chain(["chorus", {"Bitcrush": {"bit_depth": 8}}])), 2)
        with self.assertRaises(RecipeError):
            fx_chain(["shimmer"])
        with self.assertRaises(RecipeError):
            fx_chain([{"reverb": {"size": 1}}])

    def test_file_samples_mix_and_render(self):
        from vulturetracker.synth import render_recipe
        with tempfile.TemporaryDirectory() as tmp:
            t = np.arange(22050) / 22050
            tone = (np.sin(2 * np.pi * 261.63 * t) * 8000).astype(int).tolist()  # middle C, 1 s
            write_wav(Path(tmp) / "a.wav", 22050, [tone], 16)
            write_wav(Path(tmp) / "b.wav", 22050, [tone[:1000], tone[:1000]], 16)
            (Path(tmp) / "r.yaml").write_text(
                "sample_rate: 44100\nsamples:\n  mix: {file: [a.wav, b.wav], note: C-5, normalize: -1.0}\n"
                "  wet: {file: a.wav, fx: [{delay: {delay_seconds: 0.25, mix: 0.5}}], fx_tail: 0.5}\n")
            logs = []
            (mix, root, _), (wet, _, _) = render_recipe(Path(tmp) / "r.yaml", log=logs.append)
            self.assertEqual(root, 60)
            w = read_wav(mix)
            self.assertEqual((w.rate, len(w.channels)), (44100, 2))  # resampled; mono + stereo mix is stereo
            self.assertAlmostEqual(len(w.channels[0]) / 44100, 1.0, delta=0.02)
            self.assertFalse(any("warning" in line for line in logs))  # pitch check agrees with note: C-5
            self.assertGreater(len(read_wav(wet).channels[0]), 44100 * 1.2)  # the echo outlasts the dry sound
            with self.assertRaises(RecipeError):
                list(expand({"samples": {"x": {"file": "a.wav", "patch": "P"}}}))


class TestDx7(unittest.TestCase):
    def test_packed_voice_maps_to_dexed_parameters(self):
        from vulturetracker.synth import dx7_voice_names, dx7_voice_params
        voice = bytearray(128)
        op6, op1 = 0, 5 * 17                  # a packed voice stores OP6 first
        voice[op6 + 14] = 77                  # OP6 output level
        voice[op1 + 12] = (10 << 3) | 5       # OP1 detune 10 (= +3), rate scaling 5
        voice[op1 + 15] = (17 << 1) | 1       # OP1 coarse 17, fixed mode
        voice[110] = 21                       # algorithm 22 (stored 0-based)
        voice[111] = (1 << 3) | 6             # osc key sync, feedback 6
        voice[116] = (3 << 4) | (4 << 1) | 1  # pitch mod sens 3, LFO wave 4 (sine), LFO key sync
        voice[117] = 24                       # transpose: middle C
        voice[118:128] = b"TEST VOICE"
        cart = bytes(6) + bytes(voice) * 32 + bytes(2)
        p = dx7_voice_params(cart, 3)
        self.assertEqual(p["op6_output_level"], (77, 99))
        self.assertEqual((p["op1_osc_detune"], p["op1_rate_scaling"]), ((10, 14), (5, 7)))
        self.assertEqual((p["op1_f_coarse"], p["op1_mode"]), ((17, 31), (1, 1)))
        self.assertEqual((p["algorithm"], p["feedback"], p["osc_key_sync"]), ((21, 31), (6, 7), (1, 1)))
        self.assertEqual((p["lfo_wave"], p["lfo_key_sync"], p["p_mode_sens"]), ((4, 5), (1, 1), (3, 7)))
        self.assertEqual(p["transpose"], (24, 48))
        self.assertEqual(len(p), 19 + 6 * 21)
        self.assertEqual(dx7_voice_names(cart)[3], "TEST VOICE")


class TestTryout(unittest.TestCase):
    def test_renders_one_version_per_candidate(self):
        from vulturetracker import api
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name, n in (("a", 60), ("b", 64)):
                write_wav(tmp / f"{name}.wav", 22050, [[8000 if (i // 40) % 2 else -8000 for i in range(4000)]],
                          root_note=n)
            (tmp / "song.yaml").write_text(
                "module: {channels: 1}\nsamples:\n  1: {file: a.wav}\n"
                "patterns:\n  p: |\n    C-5 01\n    ...\n  q: |\n    E-5 01\n    ...\norders: [p, q]\n")
            index = api.tryout(tmp / "song.yaml", 1, [tmp / "a.wav", tmp / "b.wav"], (1, 2), tmp / "t.wav")
            self.assertEqual([f for _, f in index], [str(tmp / "a.wav"), str(tmp / "b.wav")])
            self.assertGreater(index[1][0], 0.6)  # the second version starts after the first plus the gap
            self.assertTrue((tmp / "t.wav").stat().st_size > 44)


class TestSurgeRender(unittest.TestCase):
    def setUp(self):
        try:
            from vulturetracker.synth import Synths
            self.surge = Synths()
        except Exception as e:  # no pedalboard, no Surge XT
            self.skipTest(f"Surge XT unavailable: {e}")
        if not self.surge.patches:  # the index is empty without Surge XT, Dexed or OB-Xd installed
            self.skipTest("no synth patches installed (tools/fetch_surge.py, tools/fetch_instruments.py)")

    def test_patch_renders_at_expected_pitch(self):
        from vulturetracker.synth import estimate_pitch
        self.surge.load("Leads/Moogy Saw")
        a = self.surge.render([(60, 110, 0.0, 1.0)], 1.2).mean(axis=0)
        hz, aperiodicity = estimate_pitch(a[4410:], 44100)
        self.assertLess(aperiodicity, 0.2)
        self.assertAlmostEqual(hz, 261.6, delta=3)  # tracker C-5 = MIDI 60 = middle C
        with self.assertRaises(RecipeError):
            self.surge.load("Leads/No Such Patch")

    def test_dexed_and_obxd_patches_load(self):
        from vulturetracker.synth import estimate_pitch
        for patch in ("dexed:SynprezFM_02/E.-PIANO", "obxd:001 - Bass 1/Bass Round Bass"):
            if patch not in self.surge.patches:
                self.skipTest(f"{patch.split(':')[0]} not installed")
            self.surge.load(patch)
            a = self.surge.render([(60, 110, 0.0, 0.6)], 0.8).mean(axis=0)
            hz, _ = estimate_pitch(a[2205:], 44100)
            semis = 12 * np.log2(hz / 261.6)
            self.assertAlmostEqual(semis - round(semis / 12) * 12, 0, delta=0.5, msg=patch)  # a C, in some octave


if __name__ == "__main__":
    unittest.main()
