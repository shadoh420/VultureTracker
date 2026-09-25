"""spectral.py (a picture played as sound, a picture as a filter) and the PAINT tab's actions (State.paint)."""
import io
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from vulturetracker import spectral as sp

RATE = 44100


def peak_hz(x):
    s = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / RATE)[np.argmax(s)])


class TestSpectral(unittest.TestCase):
    def test_a_lit_row_is_a_sine_at_its_frequency_and_pan(self):
        amp = np.zeros((24, 16))
        amp[9] = 1.0                                           # notes from C-5: row 9 is A-5
        y, peak = sp.paint_render(amp, np.full_like(amp, -1.0), 1.0, RATE, fmin=60, scale="notes")
        self.assertEqual(y.shape, (2, RATE))
        self.assertAlmostEqual(peak_hz(y[0]), 440.0, delta=1.0)
        self.assertEqual(float(np.abs(y[1]).max()), 0.0)        # red: all left
        self.assertAlmostEqual(peak, 1.0, delta=0.01)
        y, _ = sp.paint_render(amp, np.zeros_like(amp), 1.0, RATE, fmin=60, scale="notes")
        self.assertTrue(np.allclose(y[0], y[1]))                # yellow: centre, equal power
        self.assertAlmostEqual(float(np.abs(y[0]).max()), np.sqrt(0.5), delta=0.01)
        half = amp * 0.5
        y2, _ = sp.paint_render(half, None, 1.0, RATE, fmin=60, scale="notes", range_db=48)
        self.assertAlmostEqual(20 * np.log10(np.abs(y2[0]).max() / np.abs(y[0]).max()), -24, delta=0.1)

    def test_a_diagonal_glides(self):
        amp = np.zeros((64, 64))
        for c in range(64):
            amp[c, c] = 1
        y, _ = sp.paint_render(amp, None, 2.0, RATE, fmin=100, fmax=6400)
        self.assertLess(abs(np.log2(peak_hz(y[0, :4096]) / 100)), 0.2)          # starts near 100 Hz
        self.assertLess(abs(np.log2(peak_hz(y[0, RATE - 2048:RATE + 2048]) / 800)), 0.1)  # halfway: 800 Hz in log
        self.assertLess(abs(np.log2(peak_hz(y[0, -4096:]) / 6400)), 0.2)
        high = np.zeros((4, 4))
        high[3] = 1
        y, peak = sp.paint_render(high, None, 0.5, RATE, fmin=5000, fmax=19000)   # the top row is over the ceiling
        self.assertLess(peak_hz(y[0]), sp.MAX_HZ)
        with self.assertRaises(ValueError):
            sp.paint_render(amp, None, 0, RATE)

    def test_the_picture_as_a_filter(self):
        rng = np.random.default_rng(0)
        x = rng.standard_normal((2, 2 * RATE)) * 0.1
        m = np.zeros((48, 8))
        fr = sp.row_freqs(48, 40, 12000)
        k = int(np.argmin(np.abs(fr - 1000)))
        m[k] = 1
        z = sp.spectral_mask(x, RATE, m, range_db=60)
        self.assertEqual(z.shape, x.shape)
        s0, s1 = (np.abs(np.fft.rfft(v[0])) ** 2 for v in (x, z))
        f = np.fft.rfftfreq(x.shape[1], 1 / RATE)
        band = (f > fr[k] * 0.97) & (f < fr[k] * 1.03)
        far = (f < 400) | (f > 3000)
        self.assertGreater(10 * np.log10(s1[band].sum() / s0[band].sum()), -2)   # -1.3 dB measured
        self.assertLess(10 * np.log10(s1[far].sum() / s0[far].sum()), -60)      # -73 dB measured
        gate = np.ones((8, 2))
        gate[:, 1] = 0                                        # open, then shut
        z = sp.spectral_mask(x, RATE, gate, range_db=60)
        db = lambda v: 20 * np.log10(np.sqrt(np.mean(v ** 2)))  # noqa: E731
        self.assertLess(abs(db(z[0, : RATE // 2]) - db(x[0, : RATE // 2])), 0.2)
        self.assertLess(db(z[0, -RATE // 2:]) - db(x[0, -RATE // 2:]), -55)
        self.assertTrue(np.allclose(sp.spectral_mask(x, RATE, np.ones((4, 4))), x, atol=1e-9))  # all light: unchanged

    def test_picture_colours(self):
        rgb = sp.picture_png(np.array([[1.0, 1.0, 1.0, 0.0]]), np.array([[-1.0, 0.0, 1.0, 0.0]]))
        self.assertEqual(rgb[0].tolist(), [[255, 0, 0], [255, 255, 0], [0, 255, 0], [0, 0, 0]])

    def test_the_paint_tab(self):
        # preview bytes, a new slot with its instrument and PNG (one undo step), a candidate, a filter of a slot
        from tests.test_gui import SONG_INS, sine
        from vulturetracker import gui
        from vulturetracker.wavload import read_wav, write_wav
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_wav(d / "a.wav", RATE, [np.round(np.random.default_rng(1).standard_normal(RATE) * 3000).astype(int).tolist()])
            write_wav(d / "b.wav", RATE, [sine(880)])
            (d / "song.yaml").write_text(SONG_INS, newline="\n")
            st = gui.State(d / "song.yaml")
            try:
                amp = np.zeros((24, 8))
                amp[9] = 1
                body = {"amp": amp.tolist(), "pan": np.zeros_like(amp).tolist(), "scale": "notes", "fmin": 60,
                        "seconds": 0.5, "name": "tone"}
                wav = st.paint({**body, "action": "preview"})
                with wave.open(io.BytesIO(wav)) as w:
                    self.assertEqual((w.getnchannels(), w.getnframes()), (1, RATE // 2))   # centred: mono
                r = st.paint({**body, "action": "slot"})
                self.assertEqual(r["report"], "paint-tone.wav (0.50 s) in new slot 03, played by instrument 03")
                self.assertTrue((d / "paint-tone.png").exists())
                self.assertEqual(st.song["instruments"][3], {"name": "paint-tone", "sample": 3})
                w = read_wav(d / "paint-tone.wav")
                self.assertAlmostEqual(max(abs(v) for v in w.channels[0]) / 32768, 0.891, delta=0.002)
                st.undo()
                self.assertNotIn(3, st.song["samples"])
                r = st.paint({**body, "action": "candidate", "pan": np.full_like(amp, 0.5).tolist()})
                self.assertIn("paint-tone-2.wav (0.50 s, stereo) added to slot 01's candidates", r["report"])
                self.assertEqual(len(st.cands()), 1)
                m = np.zeros((16, 4))
                m[8] = 1
                pre = st.paint({"action": "filter_preview", "num": 1, "amp": m.tolist(), "range_db": 60})
                self.assertEqual(pre[:4], b"RIFF")
                r = st.paint({"action": "filter", "num": 1, "amp": m.tolist(), "range_db": 60})
                self.assertEqual(st.song["samples"][1]["file"], "a-spectral_mask.wav")
                with self.assertRaises(ValueError):
                    st.paint({**body, "action": "slot", "amp": np.zeros_like(amp).tolist()})   # nothing painted
                with self.assertRaises(ValueError):
                    st.paint({**body, "action": "preview", "amp": [[2, 3], [4]]})
            finally:
                st.close()
                import time
                for _ in range(400):  # the worker finishes the render it is on before the folder goes
                    if not any(r["status"] == "rendering" for r in st.renders.values()):
                        break
                    time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
