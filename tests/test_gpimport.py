"""Guitar Pro import (gpimport.py): the tab written with PyGuitarPro's own writer, imported, compiled and rendered.
The timing helpers run everywhere; the rest is skipped without PyGuitarPro (pip install pyguitarpro)."""
import tempfile
import types
import unittest
from pathlib import Path

from vulturetracker import gpimport

try:
    import guitarpro
    from guitarpro import models as M
except ImportError:  # pragma: no cover
    guitarpro = None


def tab(path):
    """Three measures of guitar (measure 2 repeated once) and a drum track: a tied note, a hammer-on, a full bend, a
    shift slide, vibrato, a dead note, a palm mute, a let-ring chord with a tempo change to 140, a natural harmonic,
    eighth triplets."""
    song = M.Song()
    song.tempo, song.title = 100, "gp test"
    hdrs = [M.MeasureHeader(number=i + 1, start=960 * (1 + 4 * i)) for i in range(3)]
    hdrs[1].isRepeatOpen, hdrs[1].repeatClose = True, 1
    song.measureHeaders = hdrs
    g = song.tracks[0]
    g.name = "Gtr"
    g.measures = [M.Measure(g, h) for h in hdrs]
    N, T, D = M.NoteType.normal, M.NoteType.tie, M.NoteType.dead

    def beat(m, q, value, notes, tuplet=None):
        v = m.voices[0]
        b = M.Beat(v, duration=M.Duration(value=value, tuplet=tuplet or M.Tuplet()), start=m.start + int(q * 960),
                   status=M.BeatStatus.normal)
        for string, fret, kind, eff in notes:
            n = M.Note(b, value=fret, string=string, type=kind, velocity=M.Velocities.forte)
            for k, val in eff.items():
                setattr(n.effect, k, val)
            b.notes.append(n)
        v.beats.append(b)
        return b
    m1, m2, m3 = g.measures
    beat(m1, 0, 4, [(5, 3, N, {})])
    beat(m1, 1, 4, [(5, 3, T, {})])
    beat(m1, 2, 8, [(3, 5, N, {"hammer": True})])
    beat(m1, 2.5, 8, [(3, 7, N, {})])
    bend = M.BendEffect(type=M.BendType.bend, value=4, points=[M.BendPoint(0, 0), M.BendPoint(6, 4), M.BendPoint(12, 4)])
    beat(m1, 3, 4, [(2, 8, N, {"bend": bend})])
    beat(m2, 0, 4, [(1, 5, N, {"slides": [M.SlideType.shiftSlideTo]})])
    beat(m2, 1, 4, [(1, 9, N, {"vibrato": True})])
    beat(m2, 2, 4, [(6, 0, D, {})])
    beat(m2, 3, 4, [(6, 3, N, {"palmMute": True})])
    b = beat(m3, 0, 2, [(6, 0, N, {"letRing": True}), (5, 2, N, {"letRing": True}), (4, 2, N, {"letRing": True})])
    b.effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(value=140))
    beat(m3, 2, 8, [(1, 12, N, {"harmonic": M.NaturalHarmonic()})])
    beat(m3, 2.5, 8, [])
    for k in range(3):
        beat(m3, 3 + k / 3, 8, [(1, k, N, {})], tuplet=M.Tuplet(3, 2))
    dr = M.Track(song, number=2, name="Drums", isPercussionTrack=True, strings=[M.GuitarString(n, 0) for n in range(1, 7)])
    dr.channel.channel = 9
    dr.measures = [M.Measure(dr, h) for h in hdrs]
    for m in dr.measures:
        for q in range(4):
            v = m.voices[0]
            bb = M.Beat(v, duration=M.Duration(value=4), start=m.start + q * 960, status=M.BeatStatus.normal)
            bb.notes.append(M.Note(bb, value=36 if q % 2 == 0 else 38, string=1, type=N))
            bb.notes.append(M.Note(bb, value=42, string=2, type=N))
            v.beats.append(bb)
    song.tracks.append(dr)
    guitarpro.write(song, str(path))


class TestTiming(unittest.TestCase):
    def test_grid_and_speed(self):
        self.assertEqual(gpimport.grid_for({0, 960, 240, 480}), 4)          # sixteenths
        self.assertEqual(gpimport.grid_for({0, 320, 240}), 12)              # triplet eighths and sixteenths
        self.assertEqual(gpimport.speed_tempo(120, 4)[:2], (6, 120))         # 24 ticks a quarter: tempo = BPM
        self.assertEqual(gpimport.speed_tempo(100, 6)[:2], (4, 100))
        s, t, exact = gpimport.speed_tempo(200, 16)                         # 16 rows a quarter: more ticks per row
        self.assertTrue(32 <= t <= 255 and abs(t - exact) / exact < 0.005, (s, t, exact))

    def test_repeats_and_alternate_endings(self):
        h = lambda o=False, c=-1, alt=0: types.SimpleNamespace(isRepeatOpen=o, repeatClose=c, repeatAlternative=alt)  # noqa: E731
        # |: 0 1 [1. 2 :| [2. 3 | 4
        hs = [h(o=True), h(), h(c=1, alt=1), h(alt=2), h()]
        self.assertEqual(gpimport.play_order(hs), [0, 1, 2, 0, 1, 3, 4])
        self.assertEqual(gpimport.play_order([h(), h(o=True), h(c=2)]), [0, 1, 2, 1, 2, 1, 2])  # played three times


@unittest.skipIf(guitarpro is None, "PyGuitarPro not installed (pip install pyguitarpro)")
class TestGpImport(unittest.TestCase):
    def test_a_tab_becomes_a_song(self):
        import numpy as np
        from vulturetracker import api, dsp
        from vulturetracker.library import read_audio
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tab(d / "t.gp5")
            song, warnings = gpimport.import_gp(d / "t.gp5", d / "t.yaml", d / "t_samples")
            self.assertEqual(warnings, [])
            m = song["module"]
            self.assertEqual((m["tempo"], m["speed"]), (100, 4))              # triplets: 6 rows a quarter
            self.assertEqual(song["orders"], ["m1", "m2", "m2_2", "m3"])       # the repeat played out
            names = [c["name"] for c in m["channels"]]
            self.assertEqual(names, ["Gtr str 1", "Gtr str 2", "Gtr str 3", "Gtr str 4", "Gtr str 5", "Gtr str 6",
                                     "Drums drum 1", "Drums drum 2", "Tempo"])
            cell = {}
            for name, pat in song["patterns"].items():
                for line in pat["data"].splitlines():
                    row, _, rest = line.partition(": ")
                    for ch, c in enumerate(rest.split(" | ")):
                        cell[(name, int(row), ch)] = c
            self.assertEqual(cell[("m1", 0, 4)], "C-4 01 v48 ...")           # A string, fret 3
            self.assertEqual(cell[("m1", 12, 4)], "=== .. ... ...")          # tied on for a quarter, then off
            self.assertEqual(cell[("m1", 15, 2)], "D-5 01 v48 GFF")          # hammer-on: not struck again
            self.assertEqual([cell[("m1", r, 1)][-3:] for r in range(18, 21)], ["F04", "F03", "F04"])  # the full bend
            self.assertEqual(cell[("m2", 0, 1)], "=== .. ... ...")           # the bent note ends: first pass only
            self.assertEqual(cell[("m2_2", 0, 1)], "... .. ... ...")
            self.assertEqual(cell[("m2", 6, 0)], "C#6 01 v48 H44")           # after the slide, with vibrato
            self.assertEqual(cell[("m2", 12, 5)], "E-3 01 v16 SC1")          # dead note
            self.assertEqual(cell[("m2", 21, 5)], "=== .. ... ...")          # palm mute: half its length
            self.assertEqual(cell[("m3", 0, 8)], "... .. ... T8C")           # tempo 140
            self.assertEqual(cell[("m3", 12, 0)], "E-6 01 v48 ...")          # natural harmonic at 12
            self.assertEqual([cell[("m3", r, 0)][:3] for r in (18, 20, 22)], ["E-5", "F-5", "F#5"])  # triplets
            self.assertEqual(cell[("m1", 0, 6)][:6], "C-3 02")               # kick (36) on the kit instrument
            kit = song["instruments"][2]["keymap"]
            self.assertEqual(song["samples"][next(k for k in kit if k["notes"] == "F#3")["sample"]]["name"], "kit_hat")  # 42
            res = api.check(str(d / "t.yaml"))
            self.assertEqual((res["errors"], res["warnings"]), ([], []))     # no anti-aliasing warnings either
            solo = api.load(d / "t.yaml")  # the guitar alone, for its pitches
            for c in solo["module"]["channels"]:
                c["muted"] = c["name"].startswith("Drums")
            api.render(solo, str(d / "t.wav"), base_dir=d)
            x, r, _ = read_audio(d / "t.wav")

            def hz(a, b):
                return dsp.pitch_of(x[int(a * r):int(b * r)][None], r)
            cents = lambda got, want: 1200 * np.log2(got / want)  # noqa: E731
            self.assertLess(abs(cents(hz(0.05, 0.5), 130.81)), 10)         # C-4
            self.assertLess(abs(cents(hz(1.53, 1.75), 293.66)), 10)        # the hammered D-5
            self.assertLess(abs(cents(hz(1.80, 1.87), 392.00)), 10)        # G-5 bent...
            self.assertLess(abs(cents(hz(2.12, 2.35), 440.00)), 10)        # ... a whole tone up

    def test_the_app_imports_a_tab_beside_it(self):
        from vulturetracker import gui
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tab(d / "riff.gp5")
            out, warnings = gui.import_beside(d / "riff.gp5")
            self.assertEqual((out.name, warnings), ("riff.yaml", []))
            self.assertTrue((d / "riff_samples" / "kit_kick.wav").exists())
            out2, _ = gui.import_beside(d / "riff.gp5")
            self.assertEqual(out2.name, "riff-2.yaml")                        # nothing replaced


if __name__ == "__main__":
    unittest.main()
