"""The Pattern tab's composition helpers (vulturetracker/compose.py): groove, Euclidean rhythms, chords over channels,
round-robin and velocity layers, as the cells they write."""
import unittest

from vulturetracker import compose
from vulturetracker.notation import format_cell, parse_cell


def grid(*lines):
    """Rows of cells from 'cell | cell' lines."""
    return [[parse_cell(c) for c in line.split("|")] for line in lines]


def cells(out):
    return {(c["row"], c["ch"]): c["cell"] for c in out}


E = "... .. ... ..."


class TestCompose(unittest.TestCase):
    def test_euclidean_steps(self):
        show = lambda k, n, r=0: "".join("x" if s else "." for s in compose.euclid_steps(k, n, r))  # noqa: E731
        self.assertEqual(show(3, 8), "x..x..x.")          # the tresillo
        self.assertEqual(show(5, 8), "x.x.xx.x")          # a cinquillo
        self.assertEqual(show(4, 16), "x...x...x...x...")
        self.assertEqual(show(3, 8, 1), "..x..x.x")       # turned one step left
        self.assertEqual(show(0, 4), "....")
        with self.assertRaises(ValueError):
            compose.euclid_steps(5, 4)

    def test_groove_delays_notes_by_row(self):
        rows = grid(f"C-5 01 ... ... | {E}", "D-5 01 ... ... | E-5 02 ... A06", f"=== .. ... ... | {E}",
                    "F-5 01 ... SD3 | ... .. v20 ...")
        out, skipped = compose.groove(rows, [0, 1], 0, 3, [0, 2], speed=6)
        self.assertEqual(cells(out), {(1, 0): "D-5 01 ... SD2", (3, 0): "F-5 01 ... SD2"})  # the SD3 replaced
        self.assertEqual(skipped, 1)                      # E-5's A06 kept, the note left undelayed
        out, _ = compose.groove(rows, [0], 0, 3, [0], speed=6)  # 0 removes a delay
        self.assertEqual(cells(out), {(3, 0): "F-5 01 ... ..."})
        with self.assertRaises(ValueError):
            compose.groove(rows, [0], 0, 3, [0, 6], speed=6)

    def test_euclid_fills_the_selection_from_its_top_cell(self):
        rows = grid(*(["C-5 03 v48 ..."] + [E] * 6 + ["G-5 01 ... ..."]))
        out = compose.euclid(rows, 0, 0, 7, 3, 8)
        self.assertEqual(cells(out), {(3, 0): "C-5 03 v48 ...", (6, 0): "C-5 03 v48 ...", (7, 0): E})
        out = compose.euclid(rows, 0, 0, 7, 2, 2, every=2)  # a step every two rows, every step a hit
        self.assertEqual(sorted(cells(out)), [(2, 0), (4, 0), (6, 0), (7, 0)])
        a = compose.euclid(rows, 0, 0, 7, 8, 8, prob=50, seed=7)
        self.assertEqual(a, compose.euclid(rows, 0, 0, 7, 8, 8, prob=50, seed=7))  # the same seed, the same cells
        self.assertTrue(0 < sum(c["cell"] != E for c in a) < 7)
        with self.assertRaises(ValueError):
            compose.euclid(grid(E, E), 0, 0, 1, 1, 2)     # no note to play

    def test_chord_stacks_over_the_channels_to_the_right(self):
        rows = grid(f"C-5 02 v40 ... | {E} | {E} | {E}", f"{E} | {E} | {E} | {E}", f"A-4 .. ... ... | {E} | {E} | {E}",
                    f"=== .. ... ... | {E} | {E} | {E}")
        out = cells(compose.chord(rows, 0, 0, 3, "maj"))
        self.assertEqual([out.get((0, c)) for c in range(4)], [None, "E-5 02 v40 ...", "G-5 02 v40 ...", None])
        self.assertEqual([out.get((2, c)) for c in (1, 2)], ["C#5 02 ... ...", "E-5 02 ... ..."])  # its last instrument
        self.assertEqual([out.get((3, c)) for c in (1, 2)], ["=== .. ... ...", "=== .. ... ..."])  # the chord ends whole
        out = cells(compose.chord(rows, 0, 0, 0, "min7", inversion=1))  # E-flat, G, B-flat under the octave's C
        self.assertEqual([out.get((0, c)) for c in range(4)], ["D#5 02 v40 ...", "G-5 02 v40 ...", "A#5 02 v40 ...", "C-6 02 v40 ..."])
        with self.assertRaises(ValueError):
            compose.chord(rows, 2, 0, 3, "maj")          # three notes from channel 3 of 4
        with self.assertRaises(ValueError):
            compose.chord(rows, 0, 0, 3, "nope")

    def test_layers_cycle_and_by_volume(self):
        rows = grid("C-5 01 ... ...", "D-5 .. v10 ...", E, "=== .. ... ...", "E-5 01 v60 A06", "F-5 01 v33 ...")
        out = cells(compose.layers(rows, [0], 0, 5, [3, 4]))
        self.assertEqual(out, {(0, 0): "C-5 03 ... ...", (1, 0): "D-5 04 v10 ...", (4, 0): "E-5 03 v60 A06",
                               (5, 0): "F-5 04 v33 ..."})
        out = cells(compose.layers(rows, [0], 0, 5, [7, 8], mode="volume", default_volume=lambda c: 20))
        self.assertEqual(out, {(0, 0): "C-5 07 ... ...", (1, 0): "D-5 07 v10 ...", (4, 0): "E-5 08 v60 A06",
                               (5, 0): "F-5 08 v33 ..."})
        with self.assertRaises(ValueError):
            compose.layers(rows, [0], 0, 5, [])

    def test_cells_round_trip(self):
        self.assertEqual(format_cell(parse_cell("C-5 01 v64 SD2")), "C-5 01 v64 SD2")


if __name__ == "__main__":
    unittest.main()
