"""tools/stems_to_song.py: the tempo channel that keeps a render on the recording's grid, and joining held notes;
tools/stems_to_midi.py: the beat period; tools/tempo_check.py: a steady grid found, a wandering one flagged;
tools/make_notes.py: Guitar Pro durations, fingerings, the hand's path, and a tab written and read back;
tools/transcription_checks.py: downbeat runs, bar lines with a 2/4 bar, the pick of notes per stem."""
import importlib.util
import unittest
from pathlib import Path


def tool(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sts, stm, tc, mn = tool("stems_to_song"), tool("stems_to_midi"), tool("tempo_check"), tool("make_notes")
tck = tool("transcription_checks")


class TempoLane(unittest.TestCase):
    def drift(self, bpm, rows=1600, mix_rate=88200, speed=6):
        """The render's largest distance from the grid (s) over `rows` rows with the lane's tempo changes played out."""
        g = sts.Grid(bpm, 0.0, 4)
        tempo = round(bpm)
        ln = sts.tempo_lane(g, rows, tempo)
        now, t, worst = tempo, 0.0, 0.0
        for r in range(rows):
            fx = ln.cells.get(r, [None] * 4)[3]
            if fx and fx.startswith("T"):
                now = int(fx[1:], 16)
            t += speed * (mix_rate * 5 // (2 * now)) / mix_rate
            worst = max(worst, abs(t - (r + 1) * g.p))
        return worst

    def test_render_stays_on_the_grid(self):
        for bpm in (136.0, 135.999, 120.0, 174.0, 99.5):
            with self.subTest(bpm=bpm):
                self.assertLess(self.drift(bpm), 0.0012)

    def test_without_the_lane_136_drifts(self):
        row = 6 * (88200 * 5 // (2 * 136)) / 88200
        self.assertGreater(abs(1600 * (row - 60 / 136 / 4)), 0.03)  # what the lane corrects: 34 ms over 1600 rows


class MergeHeld(unittest.TestCase):
    def test_joins_only_without_an_onset(self):
        notes = [(10, 14, 43), (14, 18, 43), (18, 20, 43), (20, 24, 50)]
        self.assertEqual(sts.merge_held(notes, onsets={18 - 4}, r0=4), [(10, 18, 43), (18, 20, 43), (20, 24, 50)])


class BeatPeriod(unittest.TestCase):
    def test_frame_quantized_beats(self):
        import numpy as np
        frame = 512 / 22050  # librosa's beat times come in whole frames
        beats = np.delete(np.round((0.07 + np.arange(346) * 60 / 130) / frame) * frame, 100)  # and one beat missed
        self.assertLess(60 / np.median(np.diff(beats)), 129.5)  # what the median interval read
        self.assertAlmostEqual(60 / stm.beat_period(beats), 130, delta=0.01)


class TempoCheck(unittest.TestCase):
    def clicks(self, wander_ms=0.0, bpm=130, at0=0.042, seconds=64):
        """Decaying noise bursts on every 16th (louder on the beat), each `wander_ms` * sin(2 pi t / 50 s) off the grid."""
        import numpy as np
        rng, p = np.random.default_rng(0), 60 / bpm / 4
        x = np.zeros((seconds * sts.SR, 2))
        burst = rng.standard_normal(1323) * np.exp(-np.arange(1323) / 350)
        for k in range(int((seconds - 1) / p)):
            t = at0 + k * p + wander_ms / 1000 * np.sin(2 * np.pi * k * p / 50)
            a = int(round(t * sts.SR))
            x[a:a + 1323] += (1.0 if k % 4 == 0 else 0.5) * burst[:, None]
        return x

    def test_steady_and_wandering(self):
        bpm, at0, offs, peak = tc.grid_fit(self.clicks(), 130.05)  # a first BPM 385 ppm off
        self.assertAlmostEqual(bpm, 130, delta=0.003)
        self.assertAlmostEqual(at0, 0.042, delta=0.0015)
        self.assertLess(max(abs(o) for _, o in offs), 2)
        self.assertGreater(peak, tc.CLEAR)
        *_, offs, _ = tc.grid_fit(self.clicks(wander_ms=20), 130.0)
        self.assertGreater(max(abs(o) for _, o in offs), tc.STEADY_MS)


class MakeNotes(unittest.TestCase):
    EB = [63, 58, 54, 49, 44, 39]  # Eb standard, string 1 first

    def test_durations_fingerings_and_path(self):
        self.assertEqual(mn.split(1, 8), [(1, 3), (4, 4)])
        self.assertIn(((6, 0), (5, 2), (4, 2)), mn.fingerings([39, 46, 51], self.EB, 4))  # a power chord at the nut
        self.assertEqual(mn.playable([39, 40, 41], self.EB)[0], [39])  # one string can't take all three
        hands = [mn.hand(f) for f in mn.viterbi([mn.playable([k], self.EB)[1] for k in (51, 53, 54, 56, 58, 59)])]
        self.assertLessEqual(max(abs(a - b) for a, b in zip(hands, hands[1:]) if a is not None and b is not None), 5)

    def test_tab_written_and_read_back(self):
        import tempfile
        import guitarpro as gp
        song = gp.Song(title="t", tempo=120)
        song.measureHeaders, song.tracks = [], []
        for i in range(2):
            song.addMeasureHeader(gp.MeasureHeader(number=i + 1, start=gp.Duration.quarterTime * (1 + 4 * i)))
        self.assertEqual(mn.tab_track(song, 1, "g", self.EB, [(0, 4, 51, 100), (4, 6, 53, 90), (6, 22, 39, 80)], 0, 30, 32), (3, 0))
        with tempfile.TemporaryDirectory() as d:
            gp.write(song, f"{d}/t.gp5")
            back = gp.parse(f"{d}/t.gp5")
        got = []
        for m in back.tracks[0].measures:
            self.assertEqual(sum(b.duration.time for b in m.voices[0].beats), 4 * gp.Duration.quarterTime)  # whole bars
            got += [((b.start - gp.Duration.quarterTime) // 240, n.realValue, n.type.name) for b in m.voices[0].beats for n in b.notes]
        self.assertEqual(got, [(0, 51, "normal"), (4, 53, "normal"), (6, 39, "normal"), (12, 39, "tie"), (16, 39, "tie")])

    def test_notation_tracks(self):  # other, piano, vocals: 7 strings as wide as the part, any frets
        t = mn.notation_tuning([22, 60, 100])
        self.assertEqual((len(t), t[-1], t[0] + mn.FRETS), (7, 22, 100))  # steps of 9: fret 24 of the top string is 100
        self.assertEqual(mn.notation_tuning([40, 50])[:2], [70, 65])  # a fourth at least
        self.assertEqual(mn.playable([40, 47, 52, 61], t, (mn.FRETS,))[::2], ([40, 47, 52, 61], 0))

    def test_a_short_bar(self):  # --short-bar: a 2/4 bar at row 16, the bars after it 8 rows later
        import tempfile
        import guitarpro as gp
        self.assertEqual(sts.bar_starts(50, 16), [0, 16, 24, 40])
        song = gp.Song(title="t", tempo=120)
        song.measureHeaders, song.tracks = [], []
        for i, a in enumerate(sts.bar_starts(40, 16)):
            song.addMeasureHeader(gp.MeasureHeader(number=i + 1, start=gp.Duration.quarterTime * (4 + a) // 4,
                                                   **({"timeSignature": gp.TimeSignature(2, gp.Duration(4))} if a == 16 else {})))
        self.assertEqual(mn.tab_track(song, 1, "g", self.EB, [(14, 20, 51, 100), (24, 26, 53, 90)], 0, 30, 40), (2, 0))
        with tempfile.TemporaryDirectory() as d:
            gp.write(song, f"{d}/t.gp5")
            back = gp.parse(f"{d}/t.gp5")
        ms = back.tracks[0].measures
        self.assertEqual([sum(b.duration.time for b in m.voices[0].beats) // 240 for m in ms], [16, 8, 16])
        self.assertEqual(back.measureHeaders[1].timeSignature.numerator, 2)
        got = [((b.start - gp.Duration.quarterTime) // 240, n.realValue, n.type.name) for m in ms for b in m.voices[0].beats for n in b.notes]
        self.assertEqual(got, [(14, 51, "normal"), (16, 51, "tie"), (24, 53, "normal")])


class TranscriptionChecks(unittest.TestCase):
    def test_runs_and_bar_lines(self):
        self.assertEqual(tck.runs([0, 16, 40, 56, 64]), [(0, 16, 0, 2), (40, 56, 8, 2), (64, 64, 0, 1)])
        self.assertEqual(sorted(tck.bar_lines(0, 32, 70)), [0, 16, 32, 40, 56])  # a 2/4 bar at 32: 8 rows later after it
        self.assertEqual(sorted(tck.bar_lines(4, None, 40)), [-12, 4, 20, 36])  # make_notes' first bar line is before row 0

    def test_choose(self):  # the higher F1; quiet notes kept when within 0.02 of the rest
        self.assertEqual(tck.choose({"a": (0.90, 0.24, 0.83, 0.91), "b": (0.85, 0.26, 0.75, 0.74)}), ("b", True))
        self.assertEqual(tck.choose({"a": (0.84, 0.11, 0.73, 0.88), "c": (0.50, 0.03, None, 0.51)}), ("a", False))


if __name__ == "__main__":
    unittest.main()
