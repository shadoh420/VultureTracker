"""mosaic.py (resynthesis by blocks) and the recipe source `resynth:` that calls it."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from vulturetracker import mosaic, synth
from vulturetracker.library import read_audio
from tests.test_library import RATE, _write, family


def hits(order, gap=0.25):
    """A pattern: `order` a string of k (kick) and h (hat), one hit every `gap` seconds."""
    step = int(gap * RATE)
    x = np.zeros(step * len(order) + RATE // 2)
    for i, c in enumerate(order):
        h = family("kick" if c == "k" else "hat", 1)[: step]
        x[i * step: i * step + len(h)] += h
    return x


class TestMosaic(unittest.TestCase):
    def test_a_target_rebuilt_from_itself_comes_back(self):
        x = hits("khkhkkhh")
        y, info = mosaic.resynth(x, [x], RATE, block=0.04, overlap=4)
        snr = 10 * np.log10((x ** 2).sum() / ((x - y) ** 2).sum())
        self.assertGreater(snr, 30, snr)   # every block finds itself: the overlap-add gives the signal back
        self.assertEqual(len(y), len(x))
        self.assertLess(len(info["picks"]), info["blocks"])  # blocks under the gate (-60 dBFS) stay silent: 37 dB, not more

    def test_blocks_follow_the_target_family_and_level(self):
        # a kick/hat pattern rebuilt from other kicks and hats (other members of the families): each hit's first block
        # comes from a sound of its own kind, and the output's level follows the target's, block by block
        x = hits("kkhkhhkh")
        corpus = [family("kick", 3), family("hat", 4), family("kick", 5), family("hat", 0)]
        kinds = ["k", "h", "k", "h"]
        y, info = mosaic.resynth(x, corpus, RATE, block=0.03, overlap=2)
        step = int(0.25 * RATE)
        first = {s // step: kinds[k] for s, k, _ in info["picks"] if s % step < int(0.015 * RATE)}
        self.assertEqual("".join(first[i] for i in range(8)), "kkhkhhkh", first)
        size = int(0.03 * RATE)
        lv = lambda z: 10 * np.log10(np.array([np.mean(z[i:i + size] ** 2) for i in range(0, len(x) - size, size)]) + 1e-10)
        a, b = lv(x), lv(y)
        loud = a > a.max() - 40
        self.assertGreater(np.corrcoef(a[loud], b[loud])[0, 1], 0.9)
        self.assertLess(np.median(np.abs(a[loud] - b[loud])), 1.5)   # within 1.5 dB for the typical block

    def test_variety_and_reuse_spread_the_choices(self):
        x = np.tile(family("saw", 2)[: RATE // 4], 6)
        corpus = [family("saw", k) for k in range(6)]
        one = mosaic.resynth(x, corpus, RATE, block=0.05)[1]["distinct"]
        many = mosaic.resynth(x, corpus, RATE, block=0.05, variety=6, reuse=1.0, seed=3)[1]["distinct"]
        self.assertGreater(many, one)
        a = mosaic.resynth(x, corpus, RATE, block=0.05, variety=4, seed=7)[0]
        b = mosaic.resynth(x, corpus, RATE, block=0.05, variety=4, seed=7)[0]
        self.assertTrue(np.array_equal(a, b))  # the seed makes it repeatable
        with self.assertRaises(ValueError):
            mosaic.resynth(x, [np.zeros(10)], RATE)

    def test_the_recipe_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "kit").mkdir()
            _write(d / "target.wav", hits("khkh"))
            for k in range(4):
                _write(d / "kit" / f"k{k}.wav", family("kick", k), rate=22050)
                _write(d / "kit" / f"h{k}.wav", family("hat", k))
            (d / "r.yaml").write_text("out_dir: out\nsamples:\n  mosaic:\n    resynth: {target: target.wav, corpus: [kit], "
                                      "block: 0.03, reuse: 0.5}\n    normalize: -1\n  bad:\n    resynth: {target: target.wav}\n")
            with self.assertRaises(synth.RecipeError):
                synth.render_recipe(d / "r.yaml", log=lambda m: None)   # 'bad' has no corpus: nothing is rendered
            (d / "r.yaml").write_text("out_dir: out\nsamples:\n  mosaic:\n    resynth: {target: target.wav, corpus: [kit], "
                                      "block: 0.03, reuse: 0.5}\n    normalize: -1\n")
            logs = []
            files = synth.render_recipe(d / "r.yaml", log=logs.append)
            self.assertEqual([f.name for f, _, _ in files], ["mosaic.wav"])
            y, rate, info = read_audio(d / "out" / "mosaic.wav")
            self.assertEqual(rate, 44100)
            self.assertAlmostEqual(np.abs(y).max(), 10 ** (-1 / 20), delta=0.01)
            self.assertTrue(any("resynth: " in m and "from" in m for m in logs), logs)
            with self.assertRaises(synth.RecipeError):
                synth.render_one(d / "r.yaml", "mosaic", {"resynth": {"target": "target.wav", "corpus": "nothing/*.wav"}},
                                 out=d / "x.wav", log=lambda m: None)

    def test_the_app_renders_a_resynth_entry_as_a_candidate(self):
        # the RECIPE box on a slot whose WAV a resynth recipe writes: an edit (another seed and more variety) rendered
        # into mosaic-r1.wav beside it and added to the candidates; no synth or pedalboard needed
        import time
        from tests.test_gui import SONG
        from vulturetracker import gui
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write(d / "target.wav", hits("khkh"))
            for k in range(3):
                _write(d / f"k{k}.wav", family("kick", k))
                _write(d / f"h{k}.wav", family("hat", k))
            (d / "r.yaml").write_text("out_dir: .\nsamples:\n  a: {resynth: {target: target.wav, corpus: ['?[0-9].wav']}}\n")
            synth.render_recipe(d / "r.yaml", log=lambda m: None)
            _write(d / "b.wav", family("sine", 1))
            (d / "song.yaml").write_bytes(SONG.encode())
            st = gui.State(d / "song.yaml")
            try:
                rec = st.snapshot()["recipe"]["slot"]
                self.assertEqual((rec["name"], rec["recipe_name"]), ("a", "r.yaml"))
                self.assertIn("resynth:", rec["spec"])
                st.request_recipe_render("resynth: {target: target.wav, corpus: ['?[0-9].wav'], variety: 4, seed: 2}\n")
                for _ in range(200):
                    if (st.recipe_job or {}).get("status") in ("done", "failed"):
                        break
                    time.sleep(0.05)
                self.assertEqual(st.recipe_job["status"], "done", st.recipe_job)
                self.assertEqual(Path(st.recipe_job["file"]).name, "a-r1.wav")
                self.assertIn(str((d / "a-r1.wav").resolve()), st.cands())
            finally:
                st.close()
                for _ in range(200):
                    if not any(r["status"] == "rendering" for r in st.renders.values()):
                        break
                    time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
