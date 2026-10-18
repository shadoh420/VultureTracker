"""The numpy sample sources of recipes (sources.py, SAMPLING.md): wave and mip."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from vulturetracker import api, sources, synth
from vulturetracker.resample import spectral_edge
from vulturetracker.wavload import read_wav

R = 44100


def harmonics(x, k, count):
    """Magnitudes of the first `count` harmonics of a loop of `k` cycles."""
    return np.abs(np.fft.rfft(x[0]))[k * np.arange(1, count + 1)]


def recipe(text):
    d = Path(tempfile.mkdtemp())
    (d / "r.yaml").write_text("out_dir: out\nsamples:\n" + text)
    log = []
    synth.render_recipe(d / "r.yaml", log=log.append)
    return d, log


class TestWave(unittest.TestCase):
    def test_cycles_in_tune_band_limited_and_shaped(self):
        for note in (21, 60, 69, 98):
            for shape in ("pulse", "saw", "square", "triangle", "tri4"):
                x, (s, e, pp), label = sources.wave({"shape": shape}, note, R)
                k = int(label.split("(")[1].split()[0]) if "(" in label else 1
                self.assertEqual((s, e, pp), (0, x.shape[1], False))
                self.assertLess(abs(1200 * np.log2(k * R / e / sources.hz(note))), 0.1, (note, shape))
                # the edge is a bin's top, and the window leaks into one bin more
                self.assertLessEqual(spectral_edge(np.tile(x, 20)) * R, 18000 + R / 1024, (note, shape))
                self.assertLess(abs(x.mean()), 1e-9)  # no DC
        x, (_, n, _), label = sources.wave({"shape": "saw"}, 60, R)
        k = int(label.split("(")[1].split()[0])
        h = harmonics(x, k, 4)
        self.assertAlmostEqual(h[1] / h[0], 1 / 2, 3)  # a saw's harmonics fall as 1/h
        h = harmonics(sources.wave({"shape": "square"}, 60, R)[0], k, 4)
        self.assertLess(h[1] / h[0], 1e-6)             # a square has no even harmonic
        h = harmonics(sources.wave({"shape": "pulse", "duty": 0.25}, 60, R)[0], k, 4)
        self.assertLess(h[3] / h[0], 1e-6)             # a quarter pulse misses every fourth
        x = sources.wave({"shape": "saw", "ceiling": 2000}, 60, R)[0]
        self.assertLess(spectral_edge(np.tile(x, 20)) * R, 2100)

    def test_steps_tables_and_noise(self):
        x = sources.wave({"shape": "saw", "frames": 8}, 60, R)[0]
        h = harmonics(x, 9, 9)
        self.assertLess(h[7] / h[0], 1e-6)  # an 8-step staircase has no 8th harmonic
        self.assertEqual(sources.wave({"shape": "lfsr"}, 60, R)[1], (0, 32767, False))
        self.assertEqual(sources.wave({"shape": "lfsr", "short": True}, 60, R)[1], (0, 93, False))
        steps = sources._lfsr(False)
        self.assertEqual((len(steps), int((steps > 0).sum())), (32767, 16384))  # a maximal-length sequence
        gb = [0, 2, 4, 6, 8, 10, 12, 14, 15, 15, 14, 12, 10, 8, 6, 4] * 2
        self.assertEqual(sources.wave({"shape": "gb", "table": gb}, 60, R)[2], "wave gb (9 cycles)")
        self.assertEqual(sources.wave({"table": [0, 1, 0, -1]}, 60, R)[2], "wave table (9 cycles)")
        for bad in ({"shape": "gb", "table": [16] * 32}, {"shape": "gb", "table": [1] * 31}, {"shape": "table"},
                    {"shape": "sine"}, {"duty": 1}, {"shape": "saw", "frames": 1}, {"pitch": 1}):
            with self.assertRaises(sources.SourceError, msg=bad):
                sources.wave(bad, 60, R)

    def test_recipe_wave_and_its_keys(self):
        d, log = recipe("  pulse: {wave: {shape: pulse, duty: 0.25}, notes: [A-4, A-5]}\n")
        for name in ("pulse_a4", "pulse_a5"):
            w = read_wav(d / "out" / f"{name}.wav")
            self.assertEqual(w.loops, [(0, len(w.channels[0]), False)])
            self.assertEqual(w.rate, R)
        for bad in ("{wave: {shape: saw}, chord: [C-5, E-5]}", "{wave: {shape: saw}, loop: {start: 0, end: 0.1}}",
                    "{wave: {shape: nope}}", "{wave: {shape: saw}, patch: x}", "{wave: {shape: saw}, mip: {step: 0}}"):
            with self.assertRaises(synth.RecipeError, msg=bad):
                recipe(f"  x: {bad}\n")

    def test_mip_copies_pass_the_ceiling_check_where_one_cycle_fails(self):
        """Every C from C-1 to C-8 and every copy's top and boundary key: the ceiling check warns without mip and
        passes with the printed keymap."""
        keys = [f"{n}{o}" for o in range(1, 9) for n in ("C-", "B-")]
        rows = "\n".join(f"      {i:02d}: {k} 01 v64 ..." for i, k in enumerate(keys))
        for mip in (False, True):
            d, log = recipe("  saw: {wave: {shape: saw}, note: C-4" + (", mip: {octaves: 4}}\n" if mip else "}\n"))
            if mip:
                i = next(i for i, line in enumerate(log) if "paste into" in line)
                block = "\n".join(line[4:] for line in log[i + 1:])
                self.assertIn("- {notes: C-5..B-5, sample: saw_o1}", block)
                rates = [read_wav(d / "out" / f).rate for f in ("saw.wav", "saw_o1.wav", "saw_o4.wav")]
                self.assertLess(abs(rates[0] / rates[1] - 2), 0.01)
                for f in ("saw.wav", "saw_o3.wav"):  # each copy's loop still holds whole cycles, in tune
                    w = read_wav(d / "out" / f)
                    n = w.loops[0][1]
                    k = round(n * sources.hz(48) / w.rate)
                    self.assertLess(abs(1200 * np.log2(k * w.rate / n / sources.hz(48))), 1.0, f)
            else:
                block = ("samples:\n  1: {file: out/saw.wav, name: saw, base_note: C-4, loop: from_wav}\n"
                         "instruments:\n  1: {name: saw, sample: 1}")
            (d / "s.yaml").write_text("module: {title: t, channels: 1, sample_rate: 44100}\n" + block
                                      + f"\npatterns:\n  p:\n    rows: {len(keys)}\n    data: |\n" + rows + "\norders: [p]\n")
            res = api.check(str(d / "s.yaml"))
            self.assertTrue(res["ok"], res)
            ceiling = [w for w in res["warnings"] if "ceiling" in w]
            if mip:
                self.assertEqual(res["warnings"], [])
            else:
                self.assertTrue(any("B-8 plays" in w for w in ceiling), res["warnings"])


class TestSfxr(unittest.TestCase):
    def test_presets_render_reproducibly_and_band_limited(self):
        for preset in ("pickup", "laser", "explosion", "powerup", "hit", "jump", "blip"):
            x, label = sources.sfxr({"preset": preset, "seed": 3}, R)
            self.assertTrue(np.isfinite(x).all() and np.abs(x).max() > 0, preset)
            self.assertEqual(label, f"sfxr {preset} seed 3")
            self.assertTrue(np.array_equal(x, sources.sfxr({"preset": preset, "seed": 3}, R)[0]), preset)
            self.assertLess(spectral_edge(x) * R, 0.47 * R, preset)  # its 352.8 kHz stream resampled, not averaged
        self.assertFalse(np.array_equal(sources.sfxr({"preset": "laser", "seed": 1}, R)[0],
                                        sources.sfxr({"preset": "laser", "seed": 2}, R)[0]))
        self.assertEqual(sources.sfxr_params({"preset": "coin", "seed": 4}), sources.sfxr_params({"preset": "pickup", "seed": 4}))

    def test_sfxr_timing_and_pitch(self):
        """sfxr's units: base_freq 0.3 is a period of int(100 / 0.091) sub-steps, eight to the 1/44100 s frame (321.3
        Hz), and a sustain of 0.5 lasts 0.5 ** 2 * 100000 frames."""
        x, label = sources.sfxr({"wave_type": "sine", "p_base_freq": 0.3, "p_env_sustain": 0.5, "p_env_decay": 0}, 48000)
        self.assertEqual(label, "sfxr sine")
        self.assertAlmostEqual(x.shape[1] / 48000, 25000 / 44100, 3)
        from vulturetracker import dsp
        self.assertLess(abs(1200 * np.log2(dsp.pitch_of(x[0], 48000) / (8 * 44100 / 1098))), 5)
        p = sources.sfxr_params({"preset": "jump", "seed": 1, "p_hpf_freq": 0, "wave_type": "noise"})
        self.assertEqual((p["p_hpf_freq"], p["wave_type"]), (0, 3))
        for bad in ({"preset": "boom"}, {"p_env_decay": 2}, {"p_duty": -0.1}, {"wave_type": "triangle"}, {"volume": 1},
                    {"p_freq_limit": 1, "p_base_freq": 0.0}):
            with self.assertRaises(sources.SourceError, msg=bad):
                sources.sfxr(bad, R)
        self.assertEqual(sources.sfxr_params({"p_freq_ramp": -0.5})["p_freq_ramp"], -0.5)

    def test_recipe_sfxr(self):
        d, log = recipe("  zap: {sfxr: {preset: laser, seed: 5}, normalize: -1}\n")
        w = read_wav(d / "out" / "zap.wav")
        self.assertEqual((w.rate, w.loops), (R, []))
        self.assertIn("<- sfxr laser seed 5", "\n".join(log))
        self.assertNotIn("semitones from its root", "\n".join(log))  # an effect is not pitch-checked
        for bad in ("{sfxr: {preset: laser}, notes: [C-5, C-6]}", "{sfxr: {preset: laser}, wave: {shape: saw}}",
                    "{sfxr: {seed: 1, p_lpf_freq: 3}}"):
            with self.assertRaises(synth.RecipeError, msg=bad):
                recipe(f"  x: {bad}\n")


class TestAdditive(unittest.TestCase):
    def test_padsynth_bands_and_an_exact_loop(self):
        x, (s, e, pp), label = sources.additive({"harmonics": [1, 0, 0.5], "loop_seconds": 1}, 69, 48000)
        self.assertEqual((s, e, pp, x.shape[1]), (0, 48000, False, 48000))
        self.assertEqual(label, "additive 3 harmonics, 40 cents")
        p = np.abs(np.fft.rfft(x[0])) ** 2   # the loop's own spectrum: bins of 1 Hz
        band = lambda hz, w=8: p[hz - w: hz + w + 1].sum()  # noqa: E731
        self.assertGreater(band(440), 1e6 * band(880))     # the second harmonic left out
        # PADsynth's profile exp(-x * x) / bwi keeps the amplitude per Hz, so a band's power is amplitude squared over
        # its width, and the third harmonic's band is three times as wide
        self.assertAlmostEqual(10 * np.log10(band(1320, 30) / band(440, 30)), 20 * np.log10(0.5) - 10 * np.log10(3),
                               delta=0.5)
        steps = np.abs(np.diff(x[0]))
        self.assertLess(abs(x[0][0] - x[0][-1]), 4 * steps.mean())  # the end runs into the start
        spread = []
        for cents in (5, 200):
            p = np.abs(np.fft.rfft(sources.additive({"harmonics": 8, "bandwidth_cents": cents, "loop_seconds": 1}, 57, R)[0][0])) ** 2
            spread.append(p[1760 - 3: 1764].sum() / p[1700:1820].sum())   # the 8th harmonic's core, of its band
        self.assertGreater(spread[0], 0.9)
        self.assertLess(spread[1], 0.2)
        a = sources.additive({"seed": 1}, 60, R)[0]
        self.assertTrue(np.array_equal(a, sources.additive({"seed": 1}, 60, R)[0]))
        self.assertFalse(np.array_equal(a, sources.additive({"seed": 2}, 60, R)[0]))
        x = sources.additive({"harmonics": 64, "ceiling": 3000}, 60, R)[0]
        self.assertLess(spectral_edge(x) * R, 3000 + R / 1024)
        for bad in ({"harmonics": 0}, {"harmonics": [0, 0]}, {"harmonics": [1, -1]}, {"bandwidth_cents": 0},
                    {"loop_seconds": 60}, {"width": 3}, {"ceiling": 100, "harmonics": 2}):
            with self.assertRaises(sources.SourceError, msg=bad):
                sources.additive(bad, 60, R)

    def test_recipe_additive(self):
        d, log = recipe("  pad: {additive: {harmonics: 24, loop_seconds: 2}, notes: [C-4, C-5], mono: true}\n")
        for name in ("pad_c4", "pad_c5"):
            w = read_wav(d / "out" / f"{name}.wav")
            self.assertEqual(w.loops, [(0, 2 * R, False)])
        with self.assertRaises(synth.RecipeError):
            recipe("  x: {additive: {}, chord: [C-5, E-5]}\n")


KICK_DS = """[General]
Version=DrumSynth v2.0
Comment=written for this test
Tuning=0
Stretch=100
Level=0
Filter=0

[Tone]
On=1
Level=181
F1=600
F2=50
Droop=50
Phase=90
Envelope=0,100 3000,40 15000,0

[Noise]
On=1
Level=40
Slope=-50
Envelope=0,100 500,0

[Distortion]
On=0
Clipping=20
"""


def zero_crossing_hz(x):
    return np.sum(np.diff(np.signbit(x)) != 0) / 2 / (len(x) / R)


class TestDrum(unittest.TestCase):
    def test_a_ds_file_and_its_yaml_render_alike(self):
        d = Path(tempfile.mkdtemp())
        (d / "kick.ds").write_text(KICK_DS)
        x, label = sources.drum("kick.ds", d, R)
        self.assertEqual(label, "drum kick.ds")
        self.assertEqual(x.shape[1], 2400 + 1200 * (15000 // 1200))  # DrumSynth's length: the longest envelope, rounded
        y, label = sources.drum({"tone": {"level": 181, "f1": 600, "f2": 50, "droop": 50, "envelope": [[0, 100], [3000, 40], [15000, 0]]},
                                 "noise": {"level": 40, "slope": -50, "envelope": "0,100 500,0"}}, d, R)
        self.assertEqual(label, "drum tone, noise")
        self.assertTrue(np.allclose(x, y))
        self.assertGreater(np.abs(x).max(), 0.9)  # Level 181 is full scale: 181 squared over 32768
        self.assertAlmostEqual(sources.drum("kick.ds", d, 48000)[0].shape[1], x.shape[1] * 48000 / R, delta=1)
        (d / "old.ds").write_text("[General]\nVersion=Other v2.0\n")
        for bad in ("old.ds", "none.ds", {"cowbell": {}}, {"tone": {"envelope": "0,100 50,0 20,0"}},
                    {"tone": {"f1": "fast"}}, ["tone"]):
            with self.assertRaises(sources.SourceError, msg=bad):
                sources.drum(bad, d, R)

    def test_tone_tuning_droop_and_the_other_sections(self):
        hold = {"envelope": [[0, 100], [22050, 100]]}
        for tune, hz in ((0, 220), (12, 440)):
            x = sources.drum({"general": {"tuning": tune}, "tone": {"f1": 220, "f2": 220, **hold}}, ".", R)[0][0]
            self.assertAlmostEqual(zero_crossing_hz(x[2000:20000]), hz, delta=1)
        sweep = lambda droop: [zero_crossing_hz(sources.drum({"tone": {"f1": 1000, "f2": 100, "droop": droop, **hold}}, ".", R)[0][0][a:a + 1000])
                               for a in (0, 10000)]  # noqa: E731
        linear, drooped = sweep(0), sweep(80)
        self.assertGreater(linear[0], 900)        # a linear sweep starts at F1 and is halfway at half the envelope
        self.assertAlmostEqual(linear[1], 550, delta=60)
        self.assertLess(drooped[0], 300)          # a strong droop reaches F2 within the first frames
        env = "0,100 10000,0"
        for spec in ({"overtones": {"method": m, "f1": 540, "f2": 800, "wave1": w, "wave2": 3, "envelope1": env, "envelope2": env}}
                     for m in range(4) for w in (0, 2)):
            x = sources.drum(spec, ".", R)[0]
            self.assertTrue(np.isfinite(x).all() and np.abs(x).max() > 0.01, spec)
        x = sources.drum({"noiseband": {"f": 5000, "df": 30, "envelope": env}}, ".", R)[0][0]
        p = np.abs(np.fft.rfft(x)) ** 2
        f = np.fft.rfftfreq(len(x), 1 / R)
        self.assertGreater(p[(f > 4000) & (f < 6000)].sum(), p[(f < 2000) | (f > 8000)].sum())  # a band around F
        noise = {"noise": {"level": 120, "envelope": env}}
        plain = sources.drum(noise, ".", R)[0][0]
        dark = sources.drum({**noise, "general": {"filter": 1, "resonance": 0, "filterenv": "0,20 10000,20"}}, ".", R)[0][0]
        hi = lambda y: (np.abs(np.fft.rfft(y))[len(y) // 4:] ** 2).sum()  # noqa: E731  above a quarter of the rate
        self.assertLess(hi(dark), hi(plain) / 100)  # the filter on everything, low envelope: a low-pass
        self.assertTrue((sources.drum({**noise, "general": {"seed": 1}}, ".", R)[0][0] == plain).all())  # 1 is the default
        take2 = sources.drum({**noise, "general": {"seed": 2}}, ".", R)[0][0]
        self.assertFalse((take2 == plain).all())                       # another seed, another take
        self.assertAlmostEqual(np.std(take2), np.std(plain), delta=0.05 * np.std(plain))  # at the same level
        crushed = sources.drum({"tone": {"f1": 200, "f2": 200, **hold}, "distortion": {"bits": 4, "rate": 4}}, ".", R)[0][0]
        self.assertTrue((crushed[:4000].reshape(-1, 8) == crushed[:4000].reshape(-1, 8)[:, :1]).all())  # held 8 frames
        self.assertLessEqual(len(np.unique(np.round(crushed * 32768))), 2 * 32768 // 256 + 1)          # 2 ** 8 per step

    def test_recipe_drum(self):
        d = Path(tempfile.mkdtemp())
        (d / "kick.ds").write_text(KICK_DS)
        (d / "r.yaml").write_text("out_dir: out\nsamples:\n  kick: {drum: kick.ds, mono: true}\n"
                                  "  hat: {drum: {noise: {level: 90, slope: 80, envelope: '0,100 1500,0'}}, note: C-6}\n")
        log = []
        synth.render_recipe(d / "r.yaml", log=log.append)
        self.assertEqual(read_wav(d / "out" / "kick.wav").loops, [])
        self.assertIn("root C-6  <- drum noise", "\n".join(log))
        for bad in ("{drum: {tone: {}}, notes: [C-5, C-6]}", "{drum: {tone: {envelope: 'x'}}}", "{drum: {gong: {}}}"):
            with self.assertRaises(synth.RecipeError, msg=bad):
                recipe(f"  x: {bad}\n")


if __name__ == "__main__":
    unittest.main()


def h2drumkit(folder):
    """A Hydrogen kit as Hydrogen packs one: a gzipped tar of Kit/drumkit.xml (namespaced, a current instrument with a
    component of two velocity layers, an old-format one with pan_L/pan_R and its layer in the instrument) and WAVs."""
    import io
    import tarfile
    from vulturetracker.wavload import write_wav
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<drumkit_info xmlns="http://www.hydrogen-music.org/drumkit">
 <name>Test Kit</name><author>someone</author><info/><license>CC0</license>
 <instrumentList>
  <instrument><id>0</id><name>Kick</name><volume>0.5</volume><isMuted>false</isMuted><pan>-0.5</pan>
   <pitchOffset>0</pitchOffset><gain>1</gain>
   <instrumentComponent><name>Main</name><gain>0.5</gain>
    <layer><filename>kick_soft.wav</filename><min>0</min><max>0.5</max><gain>1</gain><pitch>12</pitch></layer>
    <layer><filename>kick_hard.wav</filename><min>0.5</min><max>1</max><gain>1</gain><pitch>0</pitch></layer>
   </instrumentComponent></instrument>
  <instrument><id>1</id><name>Snare</name><volume>1</volume><pan_L>1</pan_L><pan_R>0.5</pan_R><gain>1</gain>
   <layer><filename>snare.wav</filename><min>0</min><max>1</max><gain>1</gain><pitch>0</pitch></layer></instrument>
 </instrumentList>
</drumkit_info>"""
    path = Path(folder) / "test.h2drumkit"
    with tarfile.open(path, "w:gz") as tar:
        def add(name, data):
            info = tarfile.TarInfo(f"Test Kit/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        add("drumkit.xml", xml.encode())
        for name, amp in (("kick_soft.wav", 4000), ("kick_hard.wav", 16000), ("snare.wav", 8000)):
            write_wav(Path(folder) / name, R, [[amp if i % 100 < 50 else -amp for i in range(R // 10)]])
            add(name, (Path(folder) / name).read_bytes())
    return path


class TestH2Kit(unittest.TestCase):
    def test_kit_read_as_hydrogen_reads_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = sources.h2kit(h2drumkit(tmp))
            self.assertEqual((kit["name"], kit["license"], kit["xml"]), ("Test Kit", "CC0", "Test Kit"))
            kick, snare = kit["instruments"]
            self.assertEqual((kick["pan"], kick["volume"], [l["gain"] for l in kick["layers"]]), (-0.5, 0.5, [0.5, 0.5]))
            self.assertEqual((snare["pan"], snare["layers"][0]["file"]), (-0.5, "snare.wav"))  # pan_L 1, pan_R 0.5
            ins, k, layer = sources.h2kit_pick(kit, "kick")
            self.assertEqual((k, layer["file"]), (2, "kick_hard.wav"))  # the loudest layer by default
            self.assertEqual(sources.h2kit_pick(kit, 2, 1)[0]["name"], "Snare")
            for bad in ((None,), ("tom",), ("Kick", 3)):
                with self.assertRaises(sources.SourceError):
                    sources.h2kit_pick(kit, *bad)
            self.assertEqual(len(sources.h2kit_member(Path(tmp) / "test.h2drumkit", kit, layer)), (Path(tmp) / "kick_hard.wav").stat().st_size)

    def test_recipe_layers_expand_and_keys_belong_to_a_kit(self):
        names = [synth._job_root(n, s)[0] for n, s in synth.expand({"samples": {"kick": {"file": "k.h2drumkit", "instrument": "Kick", "layers": [1, 2]}}})]
        self.assertEqual(names, ["kick_l1", "kick_l2"])
        for spec in ({"file": "a.wav", "instrument": "Kick"}, {"file": "k.h2drumkit", "layer": 1, "layers": [2]},
                     {"file": "k.h2drumkit", "layers": "all"}):
            with self.assertRaises(synth.RecipeError):
                list(synth.expand({"samples": {"x": spec}}))

    @unittest.skipUnless(__import__("importlib").util.find_spec("pedalboard"), "the file: source reads audio through pedalboard")
    def test_recipe_renders_a_layer_at_its_gains(self):
        d = Path(tempfile.mkdtemp())
        h2drumkit(d)
        (d / "r.yaml").write_text("out_dir: out\nsamples:\n  kick: {file: test.h2drumkit, instrument: Kick}\n"
                                  "  soft: {file: test.h2drumkit, instrument: Kick, layer: 1}\n"
                                  "  snare: {file: test.h2drumkit, instrument: 2, layers: [1]}\n")
        log = []
        synth.render_recipe(d / "r.yaml", log=log.append)
        peak = max(abs(v) for v in read_wav(d / "out" / "kick.wav").channels[0])
        self.assertLess(abs(peak - 16000 * 0.5 * 0.5), 300)  # component gain 0.5, instrument volume 0.5
        self.assertTrue((d / "out" / "snare_l1.wav").exists())
        frames = lambda name: len(read_wav(d / "out" / f"{name}.wav").channels[0])  # noqa: E731
        self.assertLess(abs(frames("soft") - frames("kick") / 2), 50)  # the layer's pitch 12: an octave up, half as long
        self.assertTrue(any("licence: CC0" in line and "pan 16 in a song" in line for line in log), log)
