"""0.8.0 regressions in the signal code: resampling, pitch, stretch, denoise, onsets, the recipe checks, mosaic."""
import unittest

import numpy as np

from vulturetracker import dsp, mosaic, synth
from vulturetracker.resample import resample

R = 44100


def db(a, b):
    return 10 * np.log10(a / b)


class TestRelease080Dsp(unittest.TestCase):
    def test_upsampling_leaves_no_images_above_the_source_nyquist(self):
        """Bug 26: the sinc cut exactly at the source's Nyquist frequency let images through just above it."""
        rng = np.random.default_rng(1)
        for rin in (11025, 22050, 32000):
            ny = rin / 2
            y = resample(rng.standard_normal(rin * 2), rin, R)
            p = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
            f = np.fft.rfftfreq(len(y), 1 / R)
            band = p[(f > 100) & (f < ny)].mean()
            self.assertLess(db(p[(f >= ny) & (f < ny + 250)].mean(), band), -60, rin)   # the first images, per Hz
            self.assertLess(db(p[(f >= ny) & (f < 20000)].sum(), p[f < ny].sum()), -60, rin)
            for frac in (0.5, 0.9):                                     # the passband stays flat to 0.9 of Nyquist
                x = np.sin(2 * np.pi * frac * ny * np.arange(rin) / rin)
                m = resample(x, rin, R)[R // 4: -R // 4]
                self.assertLess(abs(db(2 * np.mean(m ** 2), 1)), 0.1, (rin, frac))

    def test_pitch_of_covers_the_piano_and_ignores_a_constant(self):
        """Bug 27: 40 Hz to 2 kHz only (36.7 Hz read 40, C-8 an octave low), and a constant read 2004.5 Hz."""
        t = np.arange(R // 2) / R
        for hz in (27.5, 36.71, 2093.0, 2637.0, 4186.0):
            got = dsp.pitch_of(0.5 * np.sin(2 * np.pi * hz * t), R)
            self.assertIsNotNone(got, hz)
            self.assertLess(abs(1200 * np.log2(got / hz)), 10, hz)
        # a naive (aliased) saw whose period is no whole number of samples read two periods; a square (odd harmonics
        # only) and a missing fundamental (harmonics 2-6) keep their pitch
        cases = [(0.5 * (2 * ((hz * t) % 1) - 1), hz) for hz in (1046.5, 2093.0, 3520.0, 4186.0)]
        cases += [(0.5 * np.sign(np.sin(2 * np.pi * 200 * t)), 200), (0.5 * np.sign(np.sin(2 * np.pi * 2093 * t)), 2093),
                  (0.3 * sum(np.sin(2 * np.pi * 100 * k * t) / k for k in range(2, 7)), 100)]
        for x, hz in cases:
            got = dsp.pitch_of(x, R)
            self.assertIsNotNone(got, hz)
            self.assertLess(abs(1200 * np.log2(got / hz)), 25, hz)
        for level in (0.5, 0.3):
            self.assertIsNone(dsp.pitch_of(np.full(R, level), R))
            self.assertEqual(dsp.yin(np.full(4410, level), R), (None, 0.0))

    def test_stretch_and_pitch_keep_level_without_spikes_at_the_joins(self):
        """Bug 28: synthesis hops over half a window left dips in the window sum; dividing by them made spikes."""
        t = np.arange(R) / R
        chord = sum(0.3 * np.sin(2 * np.pi * f * t) for f in (220, 277.2, 329.6))[None]
        sine = 0.98 * np.sin(2 * np.pi * 440 * t)[None]
        for ratio in (2.5, 3.0, 4.0):
            self.assertLessEqual(np.abs(dsp.stretch(sine, ratio)).max(), 1.0, ratio)
            y = dsp.stretch(chord, ratio)[0]
            m = y[len(y) // 8: -len(y) // 8]
            self.assertLess(abs(db(np.mean(m ** 2), np.mean(chord ** 2))), 0.5, ratio)
            self.assertLess(db(np.abs(y).max() ** 2, np.abs(chord).max() ** 2), 1.0, ratio)
        for semitones in (19, 24):                                      # PITCH stretches up to 400 % on the way
            y = dsp.pitch_shift(chord, semitones)[0]
            self.assertLess(abs(db(np.mean(y[R // 8: -R // 8] ** 2), np.mean(chord ** 2))), 0.5, semitones)
            self.assertLess(db(np.abs(y).max() ** 2, np.abs(chord).max() ** 2), 1.0, semitones)

    def test_denoise_learns_the_noise_level_from_a_short_selection(self):
        """Bug 29: frames overlapping the STFT's zero padding went into the profile (2.4 dB low from 2048 frames)."""
        hum = 0.1 * np.sin(2 * np.pi * 5003.7 * np.arange(2 * R) / R)[None]   # every frame holds the same power
        for n in (2048, 2600, 4096):
            y = dsp.denoise(hum, R, hum[:, :n], reduce_db=60, sensitivity=1.0)
            self.assertLess(db(np.mean(y[:, 8192:-8192] ** 2), np.mean(hum ** 2)), -50, n)

    def test_recipe_pitch_check_reads_sines_to_c9(self):
        """Bug 30: the recipe check stopped at 2 kHz and warned about C-8 and up with a wrong root_offset."""
        for midi in range(95, 109):
            hz = 440 * 2 ** ((midi - 69) / 12)
            est = synth.estimate_pitch(0.5 * np.sin(2 * np.pi * hz * np.arange(R // 2) / R), R)
            self.assertLess(est[1], 0.1, midi)                          # sure enough that render_recipe checks it
            self.assertLess(abs(12 * np.log2(est[0] / hz)), 0.5, midi)  # and no warning

    def test_mosaic_variety_never_picks_silent_blocks(self):
        """Bug 31: a variety above the number of audible corpus blocks picked silent (infinitely far) ones."""
        t = np.arange(22050) / 22050
        target = 0.5 * np.sin(2 * np.pi * 220 * t) * (1 + np.sin(2 * np.pi * 2 * t)) / 2
        corpus = np.concatenate([0.5 * np.sin(2 * np.pi * 330 * np.arange(1500) / 22050), np.zeros(22050)])
        _, info = mosaic.resynth(target, [corpus], 22050, variety=20, seed=3)
        size = int(0.05 * 22050)
        self.assertTrue(info["picks"])
        self.assertFalse([cs for _, _, cs in info["picks"] if not np.abs(corpus[cs:cs + size]).any()])

    def test_recipe_loop_type_and_keys_are_checked(self):
        """Bug 32: `type: ping-pong` (or a misspelled key) silently made a forward loop."""
        def entry(**loop):
            return {"samples": {"pad": {"file": "pad.wav", "note": "A-4", "loop": loop}}}
        for bad in ({"start": 1, "end": 2, "type": "ping-pong"}, {"start": 1, "end": 2, "xfade": 0.1}, {"start": 1}):
            with self.assertRaisesRegex(synth.RecipeError, "sample 'pad': loop"):
                list(synth.expand(entry(**bad)))
        self.assertEqual(len(list(synth.expand(entry(start=1, end=2, crossfade=0.1, type="pingpong")))), 1)

    def test_onsets_find_a_hit_at_the_end_but_not_the_end_of_a_steady_tone(self):
        """Bug 33: the last flux frame was never a peak and the last partial hop was never seen."""
        def hit(n):
            t = np.arange(n) / R
            return 0.8 * np.sin(2 * np.pi * 150 * t) * np.exp(-t / 0.02)
        t = np.arange(R) / R
        tone = 0.5 * np.sin(2 * np.pi * 440 * t) * np.minimum(1, t / 0.05)
        for n in (R, R - 100, R - 180, R - 333):
            x = np.zeros((1, n))
            for at in (11025, 22050):
                x[0, at:at + 4000] += hit(4000)
            at = n - int(0.005 * R)                                     # 5 ms before the end
            x[0, at:] += hit(n - at)
            self.assertTrue(any(abs(p - at) < 200 for p in dsp.onsets(x, R, 50)), n)
            self.assertEqual(dsp.onsets(tone[None, :n], R, 50), [0], n)
        # the last half millisecond (the window's taper hid it), at a file's end and at a selection's inside a file;
        # a hit that rises just after the selection is not one of its points
        for ms in (0.25, 0.5):
            y = np.zeros((1, 2 * R))
            at = R - int(ms * R / 1000)
            y[0, at:at + 4000] += hit(4000)
            for pts in (dsp.onsets(y[:, :R].copy(), R, 50), dsp.onsets(y, R, 50, 0, R)):
                self.assertTrue(any(abs(p - at) < 200 for p in pts), (ms, pts))
        y = np.zeros((1, 2 * R))
        y[0, R + 22: R + 4022] += hit(4000)
        self.assertEqual(dsp.onsets(y, R, 50, 0, R), [0])

    def test_onsets_skip_a_hit_cut_off_and_find_hits_over_what_sounds(self):
        """2026-10-01: a hit cut off abruptly (a click 41 dB down) got a second point 27 ms before the cut, in its decay;
        a hit over a pad or a tail was placed where the window started."""
        t = np.arange(R) / R
        hit = 0.8 * np.sin(2 * np.pi * 150 * t[:4000]) * np.exp(-t[:4000] / 0.02)  # ends at 0.0086 (a step to 0)
        x = np.zeros((1, R))
        for at in (11025, 22050):
            x[0, at:at + 4000] += hit
        self.assertEqual(len(dsp.onsets(x, R, 50)), 3)
        noise = np.random.default_rng(1).standard_normal(8000) * np.exp(-np.arange(8000) / R / 0.02)
        pad = 0.3 * np.sin(2 * np.pi * 220 * t)
        pad[22050:30050] += 0.4 * noise
        kick = np.zeros(R)
        kick[1000:] = 0.9 * np.sin(2 * np.pi * 60 * t[:R - 1000]) * np.exp(-t[:R - 1000] / 0.15)
        kick[5410:5410 + 3000] += 0.15 * noise[:3000]                                 # a soft hat over the kick's tail
        for y, at in ((pad, 22050), (kick, 5410)):
            pts = dsp.onsets(y[None], R, 50)
            self.assertTrue(any(abs(p - at) < 200 for p in pts), (at, pts))  # was 1200-1300 frames early

    def test_stretch_of_a_short_selection_keeps_its_level(self):
        """2026-10-01: a 2048-frame window over a shorter output lost up to 30 dB (a 46 ms tone at 25 %: 13.6 dB)."""
        for ms, ratio in ((20, 0.25), (46, 0.25), (20, 0.5), (60, 0.25), (20, 2.0)):
            n = int(ms * R / 1000)
            x = 0.5 * np.sin(2 * np.pi * 440 * np.arange(n) / R)[None]
            y = dsp.stretch(x, ratio)
            self.assertEqual(y.shape[1], round(n * ratio))
            self.assertLess(abs(20 * np.log10(np.abs(y).max() / 0.5)), 1.0, (ms, ratio))


if __name__ == "__main__":
    unittest.main()
