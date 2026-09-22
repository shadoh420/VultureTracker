"""The resampler must not image when raising a rate nor fold when lowering one, and must keep level."""
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

    def test_arbitrary_ratio_keeps_pitch(self):
        from vulturetracker.resample import resample
        x = np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)
        y = resample(x, 16000, 22050)
        spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
        f = np.fft.rfftfreq(len(y), 1 / 22050)
        self.assertAlmostEqual(f[np.argmax(spec)], 440, delta=2)


if __name__ == "__main__":
    unittest.main()
