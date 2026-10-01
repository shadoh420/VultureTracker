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
            for bad in ("x: {faust: tone.dsp, chord: [C-5, H-5]}", "x: {faust: tone.dsp, file: a.wav, chord: [C-5]}"):
                (d / "bad.yaml").write_text("samples:\n  " + bad + "\n")
                with self.assertRaises(synth.RecipeError):
                    synth.render_recipe(d / "bad.yaml", log=lambda m: None)

    def test_chord_and_phrase(self):
        # a voice per note: a chord's three pitches sound together, a phrase's notes start at their beats (to the frame,
        # not the 128-frame block) at their velocities (gain), and each note's own release ends it
        gained = SINE.replace("* level;", "* level * hslider(\"gain\", 1, 0, 1, 0.01);")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "tone.dsp").write_text(gained)
            (d / "r.yaml").write_text(
                "out_dir: out\ndefaults: {trim: false, params: {level: 0.25}}\nsamples:\n"
                "  triad: {faust: tone.dsp, chord: [C-5, E-5, G-5], hold: 0.5, tail: 0.2}\n"
                "  line: {faust: tone.dsp, phrase: {bpm: 120, notes: [[A-4, 0, 0.5], [E-5, 1.05, 0.5], [C-6, 2.1, 0.5, 50]]}, tail: 0.2}\n")
            (triad, root, _), (line, line_root, _) = synth.render_recipe(d / "r.yaml", log=lambda m: None)
            self.assertEqual((root, line_root), (60, 57))
            x, rate, info = read_audio(triad)
            self.assertEqual((info["root"], len(x)), (60, round(0.7 * rate)))
            seg = x[int(0.05 * rate): int(0.45 * rate)]
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 16 * len(seg)))
            hz = np.fft.rfftfreq(16 * len(seg), 1 / rate)
            peaks = [i for i in range(1, len(spec) - 1) if spec[i - 1] < spec[i] >= spec[i + 1] and spec[i] > spec.max() / 4]
            self.assertEqual(len(peaks), 3)
            for i, want in zip(peaks, (261.626, 329.628, 391.995)):
                self.assertLess(abs(1200 * np.log2(hz[i] / want)), 3)
            self.assertLess(float(np.abs(x[-500:]).max()), 1e-3)  # all three released together after 0.5 s

            y, rate, _ = read_audio(line)
            self.assertEqual(len(y), round((2.1 * 0.5 + 0.25 + 0.2) * rate))
            levels = []
            for note, start in ((57, 0.0), (64, 0.525), (72, 1.05)):
                at = round(start * rate)
                lo = max(0, at - 200)
                onset = lo + int(np.argmax(np.abs(y[lo: at + 2000]) > 0.01))
                self.assertLess(abs(onset - at), 32, (note, onset, at))
                part = y[at + int(0.02 * rate): at + int(0.24 * rate)]
                self.assertLess(abs(1200 * np.log2(dsp.pitch_of(part[None], rate) / (440 * 2 ** ((note - 69) / 12)))), 5)
                levels.append(float(np.abs(part).max()))
                self.assertLess(float(np.abs(y[at + int(0.32 * rate): at + int(0.5 * rate)]).max()), 1e-3)  # released
            self.assertAlmostEqual(levels[0], 0.25 * 100 / 127, delta=0.01)  # velocity 100 by default
            self.assertAlmostEqual(levels[2] / levels[0], 50 / 100, delta=0.02)


# a voice that plays its gate times its gain: the frames a note sounds, and which note, read straight off the output
GATE = 'process = button("gate") * hslider("gain", 1, 0, 1, 0.01);'


@unittest.skipUnless(READY, "needs node and faustwasm (python -c \"from vulturetracker import faust; faust.fetch()\")")
class TestFaustAudit100(unittest.TestCase):
    def test_a_zero_length_note_is_released(self):
        # A1: a key-off on its key-on's frame sorted first, found no voice and left the gate down to the end of the render
        x, _ = faust.render(GATE, hold=0, tail=0.5, velocity=127)
        self.assertEqual(np.nonzero(x[0] > 0.5)[0].tolist(), [0])  # one frame, as a note of any length gets at least
        x, _ = faust.render(GATE, notes=[{"note": 60, "start": 0.0, "length": 2.0, "velocity": 127},
                                         {"note": 60, "start": 0.5, "length": 0.0, "velocity": 30}], seconds=2.5)
        self.assertAlmostEqual(float(x[0, 44100]), 1.0, places=3)  # the long note is not the one released at 0.5 s
        self.assertEqual(float(x[0, round(2.1 * 44100)]), 0.0)

    def test_an_effect_that_does_not_compile_is_an_error(self):
        # A2: faustwasm compiled the voice alone when the effect failed, and the render went on without it
        self.assertAlmostEqual(float(np.abs(faust.render(GATE + "\neffect = *(0.5);", hold=0.1, tail=0)[0]).max()),
                               0.5 * 100 / 127, places=3)
        with self.assertRaises(ValueError) as e:
            faust.render(GATE + "\neffect = *(foo);", hold=0.1, tail=0)
        self.assertIn("undefined symbol : foo", str(e.exception))
        x, _ = faust.render(GATE + "\n// effect = *(0.5); left out", hold=0.1, tail=0)  # no effect is no error
        self.assertAlmostEqual(float(np.abs(x).max()), 100 / 127, places=3)

    def test_overlapping_notes_of_one_pitch_release_their_own_voice(self):
        # A3: a key-off released the oldest voice of its pitch: B (1-2 s) ending let A (0-4 s) go, and B played on
        x, _ = faust.render(GATE, notes=[{"note": 60, "start": 0.0, "length": 4.0, "velocity": 127},
                                         {"note": 60, "start": 1.0, "length": 1.0, "velocity": 30}], seconds=4.5)
        at = lambda t: float(x[0, round(t * 44100)])  # noqa: E731
        self.assertEqual([round(at(t), 3) for t in (0.5, 1.5, 3.0, 4.2)], [1.0, round(1 + 30 / 127, 3), 1.0, 0.0])

    def test_a_phrase_of_more_than_64_ringing_notes_never_steals(self):
        # A9: offline renders had 64 voices: past them a note took a ringing voice and started at the next block's middle
        ring = 'gate = button("gate"); process = (gate : max ~ *(0.99999)) * hslider("gain", 1, 0, 1, 0.01);'
        notes = [{"note": 60 + i % 12, "start": i * 0.05 + 0.0003, "length": 0.01, "velocity": 127} for i in range(70)]
        x, _ = faust.render(ring, notes=notes, seconds=3.6)
        for n in notes[63:]:
            at = round(n["start"] * 44100)
            self.assertGreater(float(x[0, at] - x[0, at - 1]), 0.9, at)  # the note's full step, on its own frame


if __name__ == "__main__":
    unittest.main()
