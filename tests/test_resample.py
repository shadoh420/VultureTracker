"""The resampler must not image when raising a rate nor fold when lowering one, and must keep level."""
import tempfile
import unittest

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def band_db(x, rate, lo, hi):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / rate)
    sel = (f >= lo) & (f < hi)
    return 10 * np.log10(spec[sel].sum() / spec.sum() + 1e-30)


@unittest.skipIf(np is None, "numpy")
class ResampleTest(unittest.TestCase):
    def test_upsampling_does_not_image(self):
        from vulturetracker.resample import resample
        rate = 11025
        t = np.arange(rate) / rate
        x = np.sin(2 * np.pi * 1000 * t)
        y = resample(x, rate, 44100)
        self.assertAlmostEqual(len(y) / len(x), 4.0, places=2)
        self.assertLess(band_db(y[2000:-2000], 44100, 6000, 22050), -60)       # nothing above the old Nyquist
        self.assertAlmostEqual(np.sqrt(np.mean(y ** 2)), np.sqrt(np.mean(x ** 2)), places=2)

    def test_downsampling_does_not_fold(self):
        from vulturetracker.resample import resample
        rate = 88200
        t = np.arange(rate) / rate
        x = np.sin(2 * np.pi * 30000 * t) + 0.5 * np.sin(2 * np.pi * 1000 * t)
        y = resample(x, rate, 44100)
        self.assertEqual(len(y), rate // 2)
        self.assertLess(band_db(y[2000:-2000], 44100, 10000, 22050), -60)      # the 30 kHz tone is gone, not at 14.1 kHz
        self.assertGreater(band_db(y[2000:-2000], 44100, 900, 1100), -0.5)      # the 1 kHz tone is all that is left

    def test_polyphase_decimation_is_the_full_rate_filter_decimated(self):
        from vulturetracker.resample import decimate, fir_filter, lowpass_fir
        rng = np.random.default_rng(1)
        for n in (1, 5, 1000, 70001):  # shorter than the filter, and over a block boundary
            for factor in (2, 3, 4):
                x = rng.integers(-30000, 30000, (n, 2)).astype(np.int16)
                h = lowpass_fir(0.45 / factor)
                want = np.stack([fir_filter(x[:, c].astype(float), h)[::factor] for c in range(2)], axis=1)
                got = decimate(x, factor, h)
                self.assertEqual(got.shape, want.shape)
                self.assertLess(np.abs(got - want).max(), 1e-6, (n, factor))

    def test_arbitrary_ratio_keeps_pitch(self):
        from vulturetracker.resample import resample
        x = np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)
        y = resample(x, 16000, 22050)
        spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
        f = np.fft.rfftfreq(len(y), 1 / 22050)
        self.assertAlmostEqual(f[np.argmax(spec)], 440, delta=2)

    def test_compiled_loop_wraps_smoothly(self):
        """A loop running to the sample's end used to be interpolated against silence past it: a click on each pass."""
        from vulturetracker import api
        from vulturetracker.wavload import write_wav
        x = np.rint(12000 * np.sin(2 * np.pi * np.arange(512) / 32)).astype(int).tolist()   # 16 whole cycles
        with tempfile.TemporaryDirectory() as d:
            write_wav(f"{d}/tone.wav", 22050, [x])
            _, mod, _ = api.compile_song("module: {channels: 1, sample_rate: 44100}\n"
                                         "samples:\n  1: {file: tone.wav, loop: {start: 0}}\n"
                                         "patterns:\n  p: |\n    C-5 01 v64 ...\norders: [p]\n", d)
        smp = mod.samples[0]
        self.assertEqual((smp.loop.start, smp.loop.end, smp.length), (0, 1024, 1024))
        y = np.array(smp.data[0], float)
        wrap = np.abs(np.diff(np.concatenate([y[-3:], y[:3]]), 2)).max()   # second differences across the wrap
        self.assertLess(wrap, 1.05 * np.abs(np.diff(y, 2)).max())

    def test_loop_entry_and_exit_run_on(self):
        """A loop whose start lands between output frames: playback runs into it and, after a sustain loop's release,
        out of it without a jump (a pure tone's second-order prediction error stays at the interpolation's level)."""
        from vulturetracker.resample import resample
        x = 12000 * np.sin(2 * np.pi * np.arange(4000) / 32)            # 16 whole cycles in the loop below
        y = resample(x, 16000, 44100, loops=[(3120, 3632, False)])      # 3120 frames land on output frame 8599.5
        c = 2 * np.cos(2 * np.pi / 32 * 16000 / 44100)
        err = np.abs(y[2:] - c * y[1:-1] + y[:-2]) / 12000
        for edge in (8600, 8600 + 1411):                                   # the loop's first frame, the frame after its last
            self.assertLess(err[edge - 6: edge + 4].max(), 1e-3)

    def test_sustain_loop_inside_the_main_loop(self):
        """Held, the sustain loop wraps; released, the main loop plays through the sustain loop's frames: no jump in
        either (both loops hold whole cycles of the tone)."""
        from vulturetracker.resample import resample, scale_loop
        x = 12000 * np.sin(2 * np.pi * np.arange(2000) / 40)
        y = resample(x, 16000, 44100, loops=[(0, 2000, False), (1000, 1520, False)])
        (s1, e1, _), (s2, e2, _) = (scale_loop(a, b, False, 16000, 44100) for a, b in ((0, 2000), (1000, 1520)))
        c = 2 * np.cos(2 * np.pi / 40 * 16000 / 44100)
        for play in (np.concatenate([y[s1:e2], y[s2:e2], y[s2:e2]]), np.tile(y[s1:e1], 3)):
            self.assertLess((np.abs(play[2:] - c * play[1:-1] + play[:-2]) / 12000).max(), 1e-3)


if __name__ == "__main__":
    unittest.main()
