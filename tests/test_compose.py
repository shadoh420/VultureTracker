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
        with self.assertRaises(ValueError):
            compose.groove(rows, [0], 0, 3, [0, 16], speed=32)  # SDx holds 0-15 (16 would write SD0)

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

    def test_interpolate_rounds_as_openmpt(self):
        """compose.interpolate is OpenMPT's Interpolate: C's truncating division with the half-step bias (a falling v64 to
        v00 over 7 rows is 64 55 46 37 27 18 9 0, as View_pat.cpp computes it), only empty or same-command fields
        written, one empty end filled from the other."""
        rows = grid("C-5 01 v64 ...", *[E] * 3, "... .. v32 ...", *[E] * 2, "... .. v00 ...")
        out = cells(compose.interpolate(rows, [(0, [2])], 0, 7))
        self.assertEqual([out[(r, 0)][7:10] for r in range(1, 7)], ["v55", "v46", "v37", "v27", "v18", "v09"])
        rows = grid("... .. v64 ...", "... .. p32 ...", E, E)  # an empty end: the start held; the p32 kept
        self.assertEqual(cells(compose.interpolate(rows, [(0, [2])], 0, 3)),
                         {(2, 0): "... .. v64 ...", (3, 0): "... .. v64 ..."})
        rows = grid("C-5 01 ... ...", E, "... .. v00 ...")  # an empty start on a note: from its default volume
        self.assertEqual(cells(compose.interpolate(rows, [(0, [2])], 0, 2, lambda c: 40)),
                         {(0, 0): "C-5 01 v40 ...", (1, 0): "... .. v20 ..."})

    def test_interpolate_notes_instruments_and_effects(self):
        rows = grid("C-5 03 ... ...", E, E, E, "E-5 .. ... ...")  # notes: the line, the start's instrument filled in
        self.assertEqual(cells(compose.interpolate(rows, [(0, [0])], 0, 4)),
                         {(1, 0): "C#5 03 ... ...", (2, 0): "D-5 03 ... ...", (3, 0): "D#5 03 ... ..."})  # E-5 names no instrument: kept
        rows = grid("C-5 03 ... ...", E, "=== .. ... ...")  # a note to a note-off: nothing
        self.assertEqual(compose.interpolate(rows, [(0, [0])], 0, 2), [])
        rows = grid("... 02 ... ...", E, E, "... 08 ... ...")
        self.assertEqual([cells(compose.interpolate(rows, [(0, [1])], 0, 3))[(r, 0)][4:6] for r in (1, 2)], ["04", "06"])
        rows = grid("... .. ... H00", E, "... .. ... SD3", "... .. ... H48")  # nibble by nibble; another effect kept
        self.assertEqual(cells(compose.interpolate(rows, [(0, [3])], 0, 3)), {(1, 0): "... .. ... H13"})
        rows = grid("... .. ... D10", E, "... .. ... K30")  # D, K and L slide into one another
        self.assertEqual(cells(compose.interpolate(rows, [(0, [3])], 0, 2)), {(1, 0): "... .. ... D20"})

    def test_interpolate_sweep_with_no_selection(self):
        rows = grid("... .. v10 ...", E, E, "... .. v40 ...", E)
        self.assertEqual(compose.sweep(rows, 0, 1, 2), (0, 3))  # the cursor between two values
        self.assertIsNone(compose.sweep(rows, 0, 0, 2))           # on the start value: a one-row span, nothing
        self.assertIsNone(compose.sweep(rows, 0, 4, 3))           # no effect above

    def test_automate_writes_a_curve(self):
        rows = grid(*[f"{E} | {E}"] * 8)
        out, skipped = compose.automate(rows, [0], 0, 7, "Z", 0x00, 0x70, "linear", every=3)
        self.assertEqual(cells(out), {(0, 0): "... .. ... Z00", (3, 0): "... .. ... Z30", (6, 0): "... .. ... Z60",
                                      (7, 0): "... .. ... Z70"})  # every 3 rows, the last row always at TO
        out, _ = compose.automate(rows, [0], 0, 7, "v", 64, 0, "steps", every=3)
        self.assertEqual(cells(out), {(0, 0): "... .. v64 ...", (3, 0): "... .. v32 ...", (6, 0): "... .. v00 ..."})
        self.assertEqual(cells(compose.automate(rows, [0], 0, 7, "v", 64, 0, "steps", every=8)[0]), {(0, 0): "... .. v64 ..."})
        out, _ = compose.automate(rows, [0], 0, 4, "M", 0x40, 0x04, "exp")  # equal ratios: 64 32 16 8 4
        self.assertEqual([cells(out)[(r, 0)][-2:] for r in range(5)], ["40", "20", "10", "08", "04"])
        out, _ = compose.automate(rows, [0], 0, 4, "X", 0, 0xFF, "scurve")
        self.assertEqual([cells(out)[(r, 0)][-2:] for r in range(5)], ["00", "28", "80", "D7", "FF"])
        out, _ = compose.automate(rows, [0, 1], 0, 1, "T", 0x80, 0x90)  # tempo is song-wide: the first channel only
        self.assertEqual(sorted(cells(out)), [(0, 0), (1, 0)])
        rows = grid("C-5 01 ... SD2", "... .. p20 ...", E)
        out, skipped = compose.automate(rows, [0], 0, 2, "Z", 0x10, 0x30)
        self.assertEqual((sorted(cells(out)), skipped), ([(1, 0), (2, 0)], 1))  # the SD2 left alone and counted
        out, skipped = compose.automate(rows, [0], 0, 2, "v", 10, 30)
        self.assertEqual((cells(out)[(0, 0)], skipped), ("C-5 01 v10 SD2", 1))  # the p20 left alone
        for bad in (("T", 0x10, 0x80, "linear", 1), ("Z", 0, 0x80, "linear", 1), ("Q", 0, 1, "linear", 1),
                    ("Z", 0, 1, "sine", 1), ("Z", 0, 1, "linear", 0)):
            with self.assertRaises(ValueError, msg=bad):
                compose.automate(rows, [0], 0, 2, *bad)

    def test_grow_and_shrink_as_openmpt(self):
        """compose.grow/shrink are OpenMPT's OnGrowSelection/OnShrinkSelection, quirks included."""
        rows = grid("A-5 01 ... ...", "B-5 01 ... ...", "C-5 01 ... SD2", *[E] * 5)
        out, dropped, last = compose.grow(rows, [(0, [0, 1, 2, 3])], 0, 2)
        self.assertEqual(cells(out), {(1, 0): E, (2, 0): "B-5 01 ... ...", (4, 0): "C-5 01 ... SD2"})
        self.assertEqual((dropped, last), (0, 4))
        rows = grid(*[E] * 4, "E-5 01 ... ...", "F-5 01 ... ...", "G-5 01 ... ...", "A-5 01 ... ...")
        out, dropped, last = compose.grow(rows, [(0, [0, 1, 2, 3])], 4, 7)  # G and A would land on rows 8 and 10
        self.assertEqual(cells(out), {(5, 0): E, (6, 0): "F-5 01 ... ..."})  # row 7 keeps its A-5, as in OpenMPT
        self.assertEqual((dropped, last), (2, 7))
        out, _, _ = compose.grow(grid("C-5 01 v20 A06", "D-5 01 v30 ...", E), [(0, [2])], 0, 1)  # the volumes alone
        self.assertEqual(cells(out), {(1, 0): "D-5 01 ... ...", (2, 0): "... .. v30 ..."})
        rows = grid("C-5 01 ... ...", "... .. v20 ...", "D-5 01 ... ...", "E-5 02 ... A06", E, "F-5 01 ... ...")
        out, last = compose.shrink(rows, [(0, [0, 1, 2, 3])], 0, 5)
        self.assertEqual(cells(out), {(0, 0): "C-5 01 v20 ...", (1, 0): "D-5 01 ... A06", (2, 0): "F-5 01 ... ...",
                                      (3, 0): E, (5, 0): E})  # the odd rows' fields merged where there was room
        self.assertEqual(last, 2)
        out, _ = compose.shrink(rows, [(0, [0])], 0, 5)  # the note column alone: volumes and effects stay put
        self.assertEqual(cells(out), {(1, 0): "D-5 .. v20 ...", (2, 0): "F-5 01 ... ...", (3, 0): "... 02 ... A06",
                                      (5, 0): "... 01 ... ..."})

    def test_arp_from_the_written_roots(self):
        rows = grid("C-5 01 v40 ...", E, E, E, "A-4 01 ... ...", E, E, E)
        out = cells(compose.arp(rows, 0, 0, 7, "maj"))
        self.assertEqual([out.get((r, 0), "")[:10] for r in range(8)],
                         ["", "E-5 01 v40", "G-5 01 v40", "C-5 01 v40", "", "C#5 01 ...", "E-5 01 ...", "A-4 01 ..."])
        out = cells(compose.arp(rows, 0, 0, 3, "5", octaves=2, direction="updown"))  # C G c g, then back: G-6 C-6
        self.assertEqual([out.get((r, 0), "")[:3] for r in range(4)], ["", "G-5", "C-6", "G-6"])
        out = cells(compose.arp(rows, 0, 0, 3, "maj", direction="down", gate=3))
        self.assertEqual([out[(r, 0)] for r in range(4)],
                         ["G-5 01 v40 SC3", "E-5 01 v40 SC3", "C-5 01 v40 SC3", "G-5 01 v40 SC3"])
        out = cells(compose.arp(rows, 0, 0, 3, "maj", every=2, gate="off"))
        self.assertEqual(out, {(1, 0): "=== .. ... ...", (2, 0): "E-5 01 v40 ...", (3, 0): "=== .. ... ..."})
        a = compose.arp(rows, 0, 0, 7, "min7", direction="random", skip=40, seed=7)
        self.assertEqual(a, compose.arp(rows, 0, 0, 7, "min7", direction="random", skip=40, seed=7))  # seeded
        self.assertEqual(cells(compose.arp(rows, 0, 0, 7, "maj", skip=100)), {})  # each root kept, every step left out
        for bad in ({"direction": "sideways"}, {"octaves": 5}, {"gate": 16}, {"every": 0}):
            with self.assertRaises(ValueError, msg=bad):
                compose.arp(rows, 0, 0, 7, "maj", **bad)

    def test_strum_delays_the_voices(self):
        rows = grid("C-5 01 ... ... | E-5 01 ... ... | G-5 01 ... A06", f"{E} | {E} | {E}")
        out, skipped, held = compose.strum(rows, 0, 0, 1, 3, 2, speed=6)
        self.assertEqual((cells(out), skipped, held), ({(0, 1): "E-5 01 ... SD2"}, 1, 0))  # G-5's A06 kept
        out, skipped, held = compose.strum(rows, 0, 0, 1, 3, 4, speed=6, down=True)  # from the top: G, E, C
        self.assertEqual((cells(out), skipped, held), ({(0, 1): "E-5 01 ... SD4", (0, 0): "C-5 01 ... SD5"}, 0, 1))

    def test_note_lengths(self):
        rows = grid("C-5 01 ... ...", E, "=== .. v10 ...", "D-5 01 ... ...", E, "=== .. ... ...", E, E)
        out, n = compose.fill(rows, [0], 0, 7)  # legato: the end between C and D goes, its v10 stays; the last end stays
        self.assertEqual((cells(out), n), ({(2, 0): "... .. v10 ..."}, 1))
        self.assertEqual(cells(compose.fill(rows, [0], 2, 7)[0]), {(2, 0): "... .. v10 ..."})  # C sounds into row 2
        out, skipped = compose.set_length(rows, [0], 0, 7, 1)
        self.assertEqual((cells(out), skipped), ({(1, 0): "=== .. ... ...", (2, 0): "... .. v10 ...",
                                                  (4, 0): "=== .. ... ...", (5, 0): E}, 0))
        out, skipped = compose.set_length(rows, [0], 0, 7, 5, off_note=254)  # C runs into D; D would end past row 7
        self.assertEqual((cells(out), skipped), ({(2, 0): "... .. v10 ..."}, 1))
        self.assertEqual(cells(compose.cut_here(rows, [0], 1)), {(1, 0): "=== .. ... ..."})
        self.assertEqual(compose.cut_here(rows, [0], 6), [])  # nothing sounds after the end on row 5
        rows = grid("C-5 01 ... ...", "=== .. ... ...", "C-5 .. ... ...", "C-5 01 v20 ...", "D-5 01 ... ...")
        out, n = compose.glue(rows, [0], 0, 4)  # the plain restrike joins; the one with v20 is an accent and stays
        self.assertEqual((cells(out), n), ({(1, 0): E, (2, 0): E}, 1))
        with self.assertRaises(ValueError):
            compose.set_length(rows, [0], 0, 4, 0)

    def test_slice_rows_keep_the_timing(self):
        # tempo 125 speed 6: a tick is 20 ms, a row 120 ms. Slices at 0, 140 ms (row 1 + 1 tick), 245 ms (row 2 + 0: 12.25
        # ticks round to 12), 250 ms (the same row: the next channel), 30 s (past 200 rows: dropped)
        r = 44100
        placed, rows, dropped = compose.slice_rows([1000, 1000 + int(0.14 * r), 1000 + int(0.245 * r),
                                                    1000 + int(0.25 * r), 1000 + 30 * r], r, 125, 6, ch=1, nch=3)
        self.assertEqual(placed, [(0, 0, 1, 0), (1, 1, 1, 1), (2, 2, 1, 0), (3, 2, 2, 0)])
        self.assertEqual((rows, dropped), (3, [4]))
        placed, _, dropped = compose.slice_rows([0, 10, 20], r, 125, 6, ch=0, nch=2)  # three on one row, two channels
        self.assertEqual((len(placed), dropped), (2, [2]))
        # on the grid: a 170 BPM loop's slices at beats 0, 1/4, 1 and 1.5 land on rows 0, 1, 4 and 6 at 4 rows a beat,
        # whatever the song's tempo, without delays
        beat = 60 / 170 * r
        placed, rows, _ = compose.slice_rows([500 + round(b * beat) for b in (0, 0.25, 1, 1.5)], r, 125, 6, grid=(170, 4))
        self.assertEqual(([(row, d) for _, row, _, d in placed], rows), ([(0, 0), (1, 0), (4, 0), (6, 0)], 7))

    def test_slice_tempo_guess_and_snap(self):
        from vulturetracker import dsp
        self.assertEqual([dsp.bpm_guess(s) for s in (1.5, 4.0, 0.5, 0.6)], [160.0, 120.0, 120.0, 200.0])  # 240 / s, folded
        # a 1/16 at 120 BPM is 0.125 s: cuts at 0.13 s and 0.24 s go to 0.125 and 0.25; two on one line become one
        r = 1000
        self.assertEqual(dsp.snap_points([0, 130, 240, 260], 0, r, 120, 16), [0, 125, 250])

    def test_key_splits(self):
        # E-4 (52), A-4 (57), D-5 (62), a repeat of A-4, G-5 (67): each note plays the keys nearest it
        self.assertEqual(compose.key_splits([57, 52, 62, 57, 67]),
                         [(1, 0, 54), (0, 55, 59), (2, 60, 64), (4, 65, 119)])
        self.assertEqual(compose.key_splits([60]), [(0, 0, 119)])

    def test_cells_round_trip(self):
        self.assertEqual(format_cell(parse_cell("C-5 01 v64 SD2")), "C-5 01 v64 SD2")


if __name__ == "__main__":
    unittest.main()
