"""dsp.measure_mix against ITU-R BS.1770-4's own calibration (a 0 dBFS 997 Hz sine in one channel reads -3.01 LUFS),
gating, true peak between samples and stereo correlation; api.measure on a song with one channel soloed."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from vulturetracker import api, dsp
from vulturetracker.wavload import write_wav


def sine(hz, rate, secs, amp=1.0, phase=0.0):
    t = np.arange(int(rate * secs)) / rate
    return amp * np.sin(2 * np.pi * hz * t + phase)


class MeasureTests(unittest.TestCase):
    def test_bs1770_calibration(self):
        for rate in (44100, 48000):
            s = sine(997, rate, 5)
            self.assertAlmostEqual(dsp.measure_mix(np.vstack([s, 0 * s]), rate)["lufs"], -3.01, delta=0.05)
            self.assertAlmostEqual(dsp.measure_mix(np.vstack([s, s]) * 0.1, rate)["lufs"], -20.0, delta=0.05)

    def test_gating_ignores_silence(self):
        # half the time silent: the absolute gate drops those blocks, so the reading is the tone's (the three blocks
        # that straddle its end pass the gates and pull it 0.17 dB down, as BS.1770's gating does)
        rate = 48000
        s = np.concatenate([sine(997, rate, 4) * 0.1, np.zeros(rate * 4)])
        self.assertAlmostEqual(dsp.measure_mix(np.vstack([s, s]), rate)["lufs"], -20.17, delta=0.03)

    def test_true_peak_and_correlation(self):
        rate = 44100
        s = sine(rate / 4, rate, 1, phase=np.pi / 4)   # every sample at 0.707, the wave's crests between them
        m = dsp.measure_mix(np.vstack([s, s]), rate)
        self.assertAlmostEqual(m["peak_dbfs"], -3.01, delta=0.01)
        self.assertAlmostEqual(m["true_peak_dbtp"], 0.0, delta=0.15)
        self.assertEqual(dsp.measure_mix(np.vstack([s, -s]), rate)["correlation"], -1.0)
        n = np.random.default_rng(1).standard_normal((2, rate)) * 0.1
        self.assertLess(abs(dsp.measure_mix(n, rate)["correlation"]), 0.05)

    def test_api_measure_solo(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", 44100, [np.round(16000 * sine(440, 44100, 1)).astype(int).tolist()])
            song = d / "s.yaml"
            song.write_text("module: {title: m, channels: [{name: A, pan: 0}, {name: B}]}\nsamples:\n  1: {file: a.wav}\n"
                            "patterns:\n  p:\n    rows: 16\n    data: |\n      00: C-5 01 ... ... | C-5 01 ... ...\n"
                            "orders: [p]\n", newline="\n")
            both, left = api.measure(song), api.measure(song, channels=[0])
            self.assertIsNotNone(both["lufs"])
            self.assertLess(left["lufs"], both["lufs"])
            self.assertIsNone(left["correlation"])   # channel A alone sits hard left: no right channel to relate to
            self.assertGreater(both["correlation"], 0)
            self.assertIsNotNone(api.measure(d / "a.wav")["lufs"])


if __name__ == "__main__":
    unittest.main()
