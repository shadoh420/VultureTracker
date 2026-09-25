"""Faust as a sound source (faust.py, web/faust-render.mjs, the recipe source `faust:`). Extraction runs everywhere; the
renders need node and faustwasm (tools/faustwasm, or $FAUSTWASM_DIR; the cloud hook fetches it) and are skipped
without them."""
import io
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

import numpy as np

from vulturetracker import dsp, faust, synth
from vulturetracker.library import read_audio

READY = bool(shutil.which("node")) and faust.have()
SINE = 'import("stdfaust.lib"); freq = hslider("freq", 440, 20, 4000, 0.01); gate = button("gate"); ' \
       'level = hslider("level", 0.5, 0, 1, 0.01); process = os.osc(freq) * en.asr(0.002, 1, 0.05, gate) * level;'


class TestFaustFetch(unittest.TestCase):
    def test_extract_keeps_what_renders_need(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tgz = d / "p.tgz"
            with tarfile.open(tgz, "w:gz") as t:
                for name in faust.KEEP + ("package/src/big.ts",):
                    data = name.encode()
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    t.addfile(info, io.BytesIO(data))
            out = faust.extract(tgz, d / "faustwasm")
            self.assertEqual(sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()),
                             sorted(k[len("package/"):] for k in faust.KEEP))
            self.assertEqual((out / "dist/esm/index.js").read_text(), "package/dist/esm/index.js")
            with tarfile.open(d / "bad.tgz", "w:gz") as t:
                pass
            with self.assertRaises(ValueError):
                faust.extract(d / "bad.tgz", d / "faustwasm")
            self.assertTrue((out / "package.json").exists())  # a failed extract leaves the old folder as it was


@unittest.skipUnless(READY, "needs node and faustwasm (python -c \"from vulturetracker import faust; faust.fetch()\")")
class TestFaustRender(unittest.TestCase):
    def test_one_note(self):
        x, controls = faust.render(SINE, hz=440.0, hold=0.5, tail=0.25)
        self.assertEqual(x.shape, (1, round(0.75 * 44100)))
        self.assertEqual([c["label"] for c in controls], ["freq", "gate", "level"])
        self.assertAlmostEqual(dsp.pitch_of(x[:, :20000], 44100), 440.0, delta=0.5)
        self.assertAlmostEqual(float(np.abs(x[0, 1000:20000]).max()), 0.5, delta=0.01)
        self.assertLess(float(np.abs(x[0, -2000:]).max()), 1e-3)          # released: the gate went down after 0.5 s
        y, _ = faust.render(SINE, hz=440.0, hold=0.3, tail=0.1, params={"level": 0.25})
        self.assertAlmostEqual(float(np.abs(y[0, 1000:10000]).max()), 0.25, delta=0.01)
        with self.assertRaises(ValueError) as e:
            faust.render(SINE, params={"nope": 1})
        self.assertIn('no control named "nope"', str(e.exception))
        with self.assertRaises(ValueError) as e:
            faust.render("process = foo;")
        self.assertIn("undefined symbol : foo", str(e.exception))

    def test_the_recipe_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "tone.dsp").write_text(SINE)
            (d / "r.yaml").write_text("out_dir: out\nsamples:\n  tone: {faust: tone.dsp, notes: [A-4, A-5], hold: 0.4, tail: 0.1}\n"
                                      "  inline:\n    faust: |\n      " + SINE + "\n    note: E-5\n    params: {level: 0.9}\n")
            files = synth.render_recipe(d / "r.yaml", log=lambda m: None)
            self.assertEqual([(f.name, root) for f, root, _ in files], [("tone_a4.wav", 57), ("tone_a5.wav", 69), ("inline.wav", 64)])
            for f, root, _ in files:
                x, rate, info = read_audio(f)
                self.assertEqual(info["root"], root)
                hz = dsp.pitch_of(x[None, : rate // 3], rate)
                self.assertLess(abs(1200 * np.log2(hz / (440 * 2 ** ((root - 69) / 12)))), 3, f)
            (d / "bad.yaml").write_text("samples:\n  x: {faust: tone.dsp, chord: [C-5, E-5]}\n")
            with self.assertRaises(synth.RecipeError):
                synth.render_recipe(d / "bad.yaml", log=lambda m: None)


if __name__ == "__main__":
    unittest.main()
