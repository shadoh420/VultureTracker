"""Sampling workflow tests. The Surge render test is skipped when Surge XT / pedalboard are unavailable."""
import random
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

    def test_a_render_over_full_scale_is_scaled_under_it_not_clipped(self):
        # audit-100 A4: without normalize: a source over full scale (a chord's voices summed) was hard-clipped to 16 bits
        rate, said = 1000, []
        x = np.vstack([np.sin(2 * np.pi * 7.3 * np.arange(2000) / rate) * 2.0])
        pcm, _ = _post(x.copy(), {"trim": False, "fade_out": 0}, rate, said.append)  # _post scales in place
        self.assertEqual(int(np.abs(pcm).max()), round(0.999 * 32767))
        self.assertTrue(np.allclose(pcm / 32767, x * 0.999 / np.abs(x).max(), atol=1e-4))  # the wave's shape, no plateau
        self.assertEqual(said, ["  6.0 dB down to stay under full scale"])
        pcm, _ = _post(x * 0.25, {"trim": False, "fade_out": 0}, rate, said.append)  # under full scale: as it was
        self.assertEqual((int(np.abs(pcm).max()), len(said)), (round(np.abs(x * 0.25).max() * 32767), 1))
        pcm, _ = _post(x, {"trim": False, "fade_out": 0, "normalize": -6}, rate, said.append)  # normalize: decides
        self.assertEqual((int(np.abs(pcm).max()), len(said)), (round(10 ** (-6 / 20) * 32767), 1))


class TestRecipeValues(unittest.TestCase):
    def test_note_chord_and_phrase_values_are_refused_by_name(self):
        # audit-100 A5: these crashed with IndexError, ZeroDivisionError or KeyError (the app's render worker with them),
        # or rendered a velocity outside MIDI's (patches refuse above 127; velocity 0 is a note-off)
        from vulturetracker.synth import _events
        for spec, key in (({"chord": []}, "chord"), ({"chord": "C-5 E-5"}, "chord"),
                          ({"phrase": {"bpm": 120, "notes": []}}, "phrase"), ({"phrase": {"notes": [["C-5", 0, 1]]}}, "bpm"),
                          ({"phrase": {"bpm": 0, "notes": [["C-5", 0, 1]]}}, "bpm"),
                          ({"phrase": {"bpm": 120, "notes": [["C-5", 0]]}}, "phrase"),
                          ({"note": "C-5", "velocity": 0}, "velocity"), ({"note": "C-5", "velocity": 128}, "velocity"),
                          ({"phrase": {"bpm": 120, "notes": [["C-5", 0, 1, 200]]}}, "velocity")):
            with self.assertRaises(RecipeError, msg=spec) as e:
                _events(spec, "sample 's'")
            self.assertIn(key, str(e.exception))
        self.assertEqual(_events({"chord": ["C-5", "E-5"], "velocity": 127}, "s")[0], [(60, 127, 0.0, 1.0), (64, 127, 0.0, 1.0)])
        self.assertEqual(_events({"phrase": {"bpm": 120, "notes": [["C-5", 0, 1, 1]]}, "tail": 0}, "s"), ([(60, 1, 0.0, 0.5)], 0.5, 60))

    def test_downloads_go_to_the_per_user_folder_outside_a_checkout(self):
        # audit-100 D9: a pip install (no pyproject.toml beside the package) wrote Surge, Dexed and faustwasm into
        # site-packages; a checkout keeps them in its tools/
        from vulturetracker import synth
        self.assertEqual(synth.tools_dir(synth.ROOT), synth.ROOT / "tools")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(synth.tools_dir(Path(tmp)).parts[-2:], ("VultureTracker", "tools"))
            self.assertNotEqual(synth.tools_dir(Path(tmp)).parent.parent, Path(tmp))


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
        with self.assertRaises(RecipeError):
            fx_chain([{"resample": {"quality": "Nearest"}}])
        with self.assertRaises(RecipeError):
            fx_chain(["iir_filter"])  # pedalboard's base class raises RuntimeError when built

    def test_fx_enum_strings(self):
        """A YAML string reaches a pybind11 enum parameter: ZeroOrderHold aliases (5 kHz at an 8 kHz rate folds to
        3 kHz), the default windowed sinc removes what is above the new Nyquist frequency."""
        from vulturetracker.synth import fx_chain
        self.assertIn("HPF24", repr(fx_chain([{"ladder_filter": {"mode": "HPF24"}}])))
        fx_chain([{"gsm_full_rate_compressor": {"quality": "Linear"}}])
        rate = 44100
        x = (0.5 * np.sin(2 * np.pi * 5000 * np.arange(rate) / rate)).astype(np.float32)[None]
        f = np.fft.rfftfreq(rate, 1 / rate)
        zoh = np.abs(np.fft.rfft(fx_chain([{"resample": {"target_sample_rate": 8000,
                                                         "quality": "ZeroOrderHold"}}])(x, rate)[0]))
        self.assertAlmostEqual(f[zoh.argmax()], 3000, delta=5)
        sinc = fx_chain([{"resample": {"target_sample_rate": 8000}}])(x, rate)[0]
        self.assertLess(sinc.std(), 0.05)  # 0.35 before: only the edges ring

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


@unittest.skipIf(np is None, "numpy not installed")
class TestPrintedFx(unittest.TestCase):
    """The numpy effects of `fx:` (dsp.PRINTED), measured: where echoes land, what a curve does to a sine, where a
    shift moves a partial, that an all-pass keeps the spectrum's level."""
    R = 44100

    def tone(self, hz=1000, ch=2):
        t = np.arange(self.R) / self.R
        return (0.5 * np.sin(2 * np.pi * hz * t)).astype(np.float32)[None].repeat(ch, 0)

    def run_fx(self, item, x):
        from vulturetracker.synth import fx_chain
        y = fx_chain([item])(x, self.R)
        self.assertTrue(np.isfinite(y).all())
        self.assertEqual(y.shape, x.shape)
        return y

    def peak_hz(self, y):
        return np.fft.rfftfreq(y.shape[-1], 1 / self.R)[1 + np.abs(np.fft.rfft(y[0]))[1:].argmax()]  # not DC

    def test_multitap(self):
        x = np.zeros((2, self.R), np.float32)
        x[:, 0] = 1
        y = self.run_fx({"multitap": {"bpm": 120, "step": "3/16", "taps": [[-6], [-12, None, -1]]}}, x)
        d = int(round(0.375 * self.R))  # a dotted eighth at 120
        self.assertAlmostEqual(float(y[0, d]), 10 ** (-6 / 20), places=3)
        d2 = int(round(0.75 * self.R))
        self.assertAlmostEqual(float(y[1, d2]), 0, places=3)               # the second tap panned hard left
        self.assertAlmostEqual(float(y[0, d2]), np.sqrt(2) * 10 ** (-12 / 20), places=3)
        y = self.run_fx({"multitap": {"bpm": 120, "step": "3/16", "count": 2, "pingpong": True, "lowpass_hz": 2000}}, x)
        self.assertGreater(abs(y[1, d:d + 50]).max(), 10 * abs(y[0, d:d + 50]).max())  # the first tap right
        out, _ = _post(np.eye(1, self.R // 10), {"fx": [{"multitap": {"bpm": 60, "step": "1/4", "count": 3}}],
                                                 "fx_tail": 0.1, "trim": False}, self.R)
        self.assertGreaterEqual(out.shape[1], 3 * self.R)                    # fx_tail stretched to the third tap

    def test_waveshape_and_slew(self):
        x = self.tone()
        self.assertTrue(np.allclose(self.run_fx({"waveshape": {"curve": [[0, 0], [1, 1]]}}, x), x, atol=1e-6))
        self.assertEqual(self.peak_hz(self.run_fx({"waveshape": {"shape": "rectify"}}, x)), 2000)  # full-wave: 2f
        folded = self.run_fx({"waveshape": {"shape": "foldback", "drive_db": 12}}, x)
        self.assertLessEqual(abs(folded).max(), 1.0 + 1e-6)
        slow = self.run_fx({"slew": {"up_db": -40, "down_db": -40}}, x)
        self.assertLessEqual(np.abs(np.diff(slow[0])).max(), 0.01 + 1e-6)
        from vulturetracker.synth import fx_chain
        for bad in ({"waveshape": {}}, {"waveshape": {"curve": [[0, 0], [0, 1]]}}, {"slew": {"shape": "x"}}):
            with self.assertRaises(RecipeError):
                fx_chain([bad])

    def test_shift_stereo_dispersion(self):
        x = self.tone()
        self.assertEqual(self.peak_hz(self.run_fx({"shift": {"hz": 100}}, x)), 1100)
        ring = np.abs(np.fft.rfft(self.run_fx({"shift": {"hz": 100, "ring": 1}}, x)[0]))
        self.assertGreater(ring[900], 100 * ring[1000])                          # ring modulation: f -/+ 100
        self.assertAlmostEqual(ring[900], ring[1100], delta=ring[900] * 0.01)
        x2 = np.stack([x[0], np.roll(x[0], 300)])
        mono = self.run_fx({"stereo": {"width": 0}}, x2)
        self.assertTrue(np.allclose(mono[0], mono[1]))
        haas = self.run_fx({"stereo": {"haas_ms": 10}}, x)
        self.assertTrue(np.allclose(haas[1, 441:], x[1, :-441]))
        self.assertTrue(np.allclose(self.run_fx({"stereo": {"swap": True}}, x2), x2[::-1]))
        with self.assertRaises(ValueError):
            from vulturetracker import dsp
            dsp.stereo(x[:1], self.R)
        click = np.zeros((1, self.R), np.float32)
        click[0, 100] = 1
        smeared = self.run_fx({"dispersion": {"stages": 128, "hz": 1000, "q": 0.7}}, click)
        self.assertLess(abs(smeared).max(), 0.5)                                  # the click spread out in time
        level = lambda y: np.abs(np.fft.rfft(y[0], 4 * self.R))[100:8000]        # noqa: E731
        self.assertTrue(np.allclose(level(smeared), level(click), rtol=0.02))     # at every frequency's own level

    def test_bandlimit_is_what_check_measures(self):
        """bandlimit leaves a sample as wide as asked by check's own measure (resample.spectral_edge, -60 dB of the
        loudest bin); white noise measures full band, and a short sample's abrupt ends do not widen it."""
        from vulturetracker.resample import spectral_edge
        noise = np.random.default_rng(0).uniform(-0.5, 0.5, (2, self.R)).astype(np.float32)
        self.assertAlmostEqual(spectral_edge(noise) * self.R, self.R / 2, delta=30)
        self.assertAlmostEqual(spectral_edge(self.run_fx({"bandlimit": {"hz": 9000}}, noise)) * self.R, 9000, delta=300)
        self.assertAlmostEqual(spectral_edge(self.tone(1000)[:, :3000]) * self.R, 1000, delta=400)

    def test_granular(self):
        x = self.tone()
        up = self.run_fx({"granular": {"pitch_st": 12, "seed": 3}}, x)
        self.assertEqual(self.peak_hz(up), 2000)
        again = self.run_fx({"granular": {"pitch_st": 12, "seed": 3, "jitter": 0}}, x)
        self.assertTrue(np.array_equal(up, again))                               # the seed repeats the cloud
        cloud = self.run_fx({"granular": {"jitter": 2, "spray_ms": 50, "seed": 1}}, x)
        self.assertFalse(np.array_equal(cloud, up))

    def test_order_matters(self):
        """The dispatcher runs numpy and pedalboard effects in list order."""
        try:
            import pedalboard  # noqa: F401
        except ImportError:
            self.skipTest("pedalboard not installed")
        x = self.tone(3000)
        a = self.run_fx({"waveshape": {"shape": "rectify"}}, x)
        from vulturetracker.synth import fx_chain
        b = fx_chain([{"lowpass_filter": {"cutoff_frequency_hz": 1000}}, {"waveshape": {"shape": "rectify"}}])(x, self.R)
        c = fx_chain([{"waveshape": {"shape": "rectify"}}, {"lowpass_filter": {"cutoff_frequency_hz": 1000}}])(x, self.R)
        self.assertFalse(np.allclose(b, c, atol=1e-3))
        self.assertEqual(self.peak_hz(a), 6000)


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


class TestJuceBase64(unittest.TestCase):
    def test_matches_the_whole_blob_formula(self):
        from vulturetracker.synth import _JUCE_B64, _juce_base64
        rng = random.Random(1)
        for size in (0, 1, 2, 3, 4, 5, 6, 7, 8, 100, 4097):  # every remainder mod 3, short and long
            data = rng.randbytes(size)
            n = int.from_bytes(data, "little")  # the original: one integer for the blob, shifted once per character
            old = f"{size}." + "".join(_JUCE_B64[(n >> (6 * i)) & 63] for i in range((size * 8 + 5) // 6))
            self.assertEqual(_juce_base64(data), old, size)


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

    def test_background_recipe_render_uses_plugin_main_thread(self):
        import os
        from concurrent.futures import ThreadPoolExecutor
        from unittest import mock
        from vulturetracker.synth import render_one, SynthMissing
        with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(1) as worker:
            recipe = Path(tmp) / 'source.yaml'
            recipe.write_text('defaults: {hold: 0.2, tail: 0.1, trim: false}\n'
                              'samples:\n  saw: {patch: Leads/Moogy Saw, notes: [C-5, D-5]}\n')
            out = Path(tmp) / 'chosen.wav'
            logs = []
            for _ in range(2):
                file, root, loop = worker.submit(render_one, recipe, 'saw', None, 'D-5', out, logs.append).result(60)
                wav = read_wav(file)
                self.assertEqual((file, root, loop), (out, 62, None))
                self.assertEqual((wav.root, wav.rate), (62, 44100))
                self.assertGreater(max(map(abs, wav.channels[0])), 100)
            self.assertTrue(any('chosen.wav' in line for line in logs))
            with self.assertRaisesRegex(RecipeError, 'unknown patch'):
                worker.submit(render_one, recipe, 'saw', {'patch': 'Leads/No Such Patch', 'note': 'C-5'}).result(60)
            with mock.patch.dict(os.environ, {'SURGE_XT_DIR': str(Path(tmp) / 'not-installed')}):
                with self.assertRaises(SynthMissing) as error:
                    worker.submit(render_one, recipe, 'saw', None, 'D-5', out).result(60)
                self.assertEqual(error.exception.kind, 'surge')

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
