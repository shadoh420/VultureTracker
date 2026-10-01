"""0.8.0 import and compile regressions: modules built here byte by byte (or with the IT writer), read back and rendered
by libopenmpt beside the original, in disposable directories."""
import math
import struct
import tempfile
import unittest
from pathlib import Path

from vulturetracker import api, openmpt
from vulturetracker.itreader import import_it, read_it
from vulturetracker.itwriter import write_it
from vulturetracker.model import Cell, Channel, Loop, Module, Pattern, Sample
from vulturetracker.modreader import read_module
from vulturetracker.notation import format_cell
from vulturetracker.wavload import write_wav
from tests.test_modimport import C4, E_XM, EMPTY4, TONE, compare, grid, imported, write_mod, write_xm

try:
    import guitarpro
    from guitarpro import models as M
except ImportError:
    guitarpro = None

XM_INS = {"data": TONE, "loop": (0, 4000)}
SONG = """module:
  title: T
  channels: 1
{extra}samples:
  1: {{file: t.wav{sample}}}
{instruments}patterns:
{patterns}orders: [a]
"""


def pcm(data, repeat=0):
    with openmpt.LoadedModule(data) as lm:
        return lm.render(44100, repeat=repeat, oversample=1)


def it_module(nch=1):
    """A sample-mode IT module of `nch` channels with one looped tone and no patterns yet."""
    m = Module(title="x", channels=[Channel() for _ in range(nch)], speed=2)
    m.samples = [Sample(name="t", data=[[round(8000 * math.sin(2 * math.pi * i / 100)) for i in range(4000)]],
                        c5_speed=44100, loop=Loop(0, 4000))]
    return m


class TestRelease080Import(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        write_wav(self.dir / "t.wav", 44100, [[round(8000 * math.sin(2 * math.pi * i / 100)) for i in range(4410)]], 16)

    def tearDown(self):
        self._tmp.cleanup()

    def song(self, extra="", sample="", instruments="", patterns="  a: |\n    C-5 01\n"):
        return SONG.format(extra=extra, sample=sample, instruments=instruments, patterns=patterns)

    # 20: the highlight bytes need the header's special bit 4
    def test_row_highlight_sets_the_special_bit_and_is_read_only_with_it(self):
        it = api.compile_song(self.song(extra="  rows_per_beat: 8\n  rows_per_bar: 32\n"), self.dir)[0]
        self.assertTrue(struct.unpack_from("<H", it, 0x2E)[0] & 4)
        self.assertEqual(read_it(it)[0].row_highlight, (8, 32))
        b = bytearray(it)
        b[0x2E] &= ~4
        self.assertEqual(read_it(bytes(b))[0].row_highlight, (4, 16))  # without the bit, trackers use their defaults

    # 21: a 3/4 tab's bar is three beats
    @unittest.skipIf(guitarpro is None, "PyGuitarPro not installed")
    def test_guitar_pro_bar_follows_the_time_signature(self):
        from vulturetracker.gpimport import import_gp
        song = M.Song()
        song.tempo, song.title = 100, "waltz"
        hdrs = [M.MeasureHeader(number=i + 1, start=960 * (1 + 3 * i)) for i in range(2)]
        for h in hdrs:
            h.timeSignature = M.TimeSignature(numerator=3, denominator=M.Duration(value=4))
        song.measureHeaders = hdrs
        g = song.tracks[0]
        g.measures = [M.Measure(g, h) for h in hdrs]
        for m in g.measures:
            for q in range(3):
                b = M.Beat(m.voices[0], duration=M.Duration(value=4), start=m.start + q * 960, status=M.BeatStatus.normal)
                b.notes.append(M.Note(b, value=3, string=5, type=M.NoteType.normal, velocity=M.Velocities.forte))
                m.voices[0].beats.append(b)
        guitarpro.write(song, str(self.dir / "waltz.gp5"))
        doc, _ = import_gp(self.dir / "waltz.gp5", self.dir / "waltz.yaml", self.dir / "gp")
        self.assertEqual((doc["module"]["rows_per_beat"], doc["module"]["rows_per_bar"]), (1, 3))

    # 25a: a break in a split pattern keeps its row, on every path (XM and IT)
    def test_break_in_a_split_pattern_keeps_its_row(self):
        long = grid([(0, 0, (C4, 1, 0, 0, 0)), (100, 0, (0, 0, 0, 0xD, 0x16))], E_XM, rows=256)
        short = grid([(0, 1, (C4 + 7, 1, 0, 0, 0)), (16, 2, (C4 + 12, 1, 0, 0, 0))], E_XM, rows=64)
        data = write_xm([XM_INS], [long, short], [0, 1], speed=2)
        row = read_module(data)[0].patterns[0].rows[100]
        self.assertEqual([format_cell(c)[-3:] for c in row], ["B02", "C10", "...", "..."])
        r = compare(data, "xm")
        self.assertEqual(r["secs"][0], r["secs"][1])
        m = it_module(2)
        rows = [[Cell(), Cell()] for _ in range(256)]
        rows[0][0], rows[100][0] = Cell(note=60, instrument=1), Cell(effect=3, param=0x10)
        m.patterns, m.orders = [Pattern("a", rows), Pattern("b", [[Cell(), Cell(note=72, instrument=1)] for _ in range(64)])], [0, 1]
        mod, _ = read_it(write_it(m))
        self.assertEqual([format_cell(c)[-3:] for c in mod.patterns[0].rows[100]], ["B02", "C10"])

    # 25b: a pattern loop across the 192-row cut starts its part instead
    def test_pattern_loop_across_the_split_plays_as_the_original(self):
        long = grid([(0, 0, (C4, 1, 0, 0, 0)), (150, 0, (C4 + 7, 1, 0, 0xE, 0x60)), (250, 0, (0, 0, 0, 0xE, 0x61))], E_XM, rows=256)
        data = write_xm([XM_INS], [long], [0], speed=2)
        it, song, _ = imported(data, "xm")
        self.assertEqual(len(pcm(it)), len(pcm(data)))
        self.assertEqual([song["patterns"][p]["rows"] for p in song["orders"]], [150, 106])
        loop = grid([(0, 0, (C4, 1, 0, 0, 0)), (250, 0, (0, 0, 0, 0xE, 0x61))], E_XM, rows=256)  # no E60: from row 0
        self.assertTrue(any("pattern loop" in w for w in read_module(write_xm([XM_INS], [loop], [0], speed=2))[1]))

    # 25c: the XM restart position, on a copy of the last pattern when it is played twice
    def test_xm_restart_position(self):
        a = grid([(0, 0, (C4, 1, 0, 0, 0))], E_XM, rows=16)
        b = grid([(0, 0, (C4 + 12, 1, 0, 0, 0))], E_XM, rows=16)
        for orders in ([0, 1], [0, 1, 0]):
            data = bytearray(write_xm([XM_INS], [a, b], orders))
            struct.pack_into("<H", data, 66, 1)  # restart at order 1
            data = bytes(data)
            it, song, _ = imported(data, "xm")
            with self.subTest(orders=orders):
                self.assertEqual(pcm(it, 1), pcm(data, 1))
                self.assertEqual(len(song["patterns"]), len(set(orders)) + (orders.count(orders[-1]) > 1))

    # 25d: XM Cxx and a volume-column command in one cell: both kept
    def test_xm_set_volume_beside_a_volume_column_command(self):
        for vol, fx in ((0x62, "D02"), (0x72, "D20"), (0xC0, "X00"), (0xB4, "H04")):
            data = write_xm([XM_INS], [grid([(0, 0, (C4, 1, vol, 0xC, 0x10))], E_XM, rows=4)], [0])
            r = compare(data, "xm")
            with self.subTest(vol=hex(vol)):
                self.assertEqual(r["song"]["patterns"]["p00"]["data"].splitlines()[0][4:18], "C-5 01 v16 " + fx)
                self.assertEqual(r["song"]["module"]["mix_volume"], 48)
                self.assertLess(r["diff"], 0.5)

    # 25e: an IT loop end past the sample is clamped, as libopenmpt plays it
    def test_it_loop_end_past_the_sample_is_clamped(self):
        m = it_module()
        rows = [[Cell()] for _ in range(64)]
        rows[0][0] = Cell(note=60, instrument=1)
        m.patterns, m.orders = [Pattern("a", rows)], [0]
        it = bytearray(write_it(m))
        smp = struct.unpack_from("<I", it, 0xC0 + 2)[0]
        struct.pack_into("<I", it, smp + 0x38, 4001)  # loop end
        struct.pack_into("<II", it, smp + 0x40, 0, 4001)  # sustain loop 0-4001
        it[smp + 0x12] |= 0x20
        (self.dir / "loop.it").write_bytes(bytes(it))
        song, _ = import_it(self.dir / "loop.it", self.dir / "loop.yaml", self.dir / "loop_samples")
        self.assertEqual(song["samples"][1].get("loop"), {"start": 0, "end": 4000})
        self.assertEqual(song["samples"][1].get("sustain_loop"), {"start": 0, "end": 4000})
        self.assertEqual(pcm(api.compile_song(self.dir / "loop.yaml")[0]), pcm(bytes(it)))

    # 25f: FLT8 stores each 8-channel pattern as two 4-channel halves
    def test_flt8_mod_matches_libopenmpt_cell_by_cell(self):
        halves = [grid([(s, s % 4, (428 >> (s % 2), 1, 0, 0)), (10 + s, 3 - s % 4, (214, 1, 0, 0))], EMPTY4) for s in range(4)]
        data = bytearray(write_mod([("tone", TONE, 64, 0, 0, 4000)], halves, [2, 0]))
        data[1080:1084] = b"FLT8"
        data = bytes(data)
        mod, _ = read_module(data)
        with openmpt.LoadedModule(data) as lm:
            info = lm.info()
            self.assertEqual((mod.orders, len(mod.patterns), len(mod.channels)), (info["orders"], info["patterns"], 8))
            for p in range(info["patterns"]):
                for r in range(64):
                    self.assertEqual([format_cell(c)[:3] for c in mod.patterns[p].rows[r]],
                                     [lm.cell_text(p, r, c)[:3] for c in range(8)], (p, r))

    # 36a: the message is stored as Latin-1, as the importer reads it
    def test_message_is_latin1(self):
        it, mod, warnings = api.compile_song(self.song(extra="  message: café ☃\n"), self.dir)
        self.assertIn(b"caf\xe9 ?\0", it)
        self.assertEqual(read_it(it)[0].message, "café ?")
        self.assertTrue(any("Latin-1" in w for w in warnings))

    # 36b: libopenmpt trims a name's trailing spaces: no mismatch for that
    def test_build_ignores_trailing_spaces_in_names(self):
        (self.dir / "s.yaml").write_text(self.song(sample=", name: 'kick '", instruments="instruments:\n  1: {sample: 1, name: 'lead  '}\n"),
                                         encoding="utf-8")
        self.assertEqual(api.build(str(self.dir / "s.yaml"), str(self.dir / "s.it"))["mismatches"], [])

    # 36c: a song file without a .yaml suffix is a path, not YAML text
    def test_song_path_without_yaml_suffix(self):
        p = self.dir / "song.txt"
        p.write_text(self.song(), encoding="utf-8")
        for arg in (p, str(p)):
            self.assertTrue(api.check(arg)["ok"], arg)

    # 36d: pattern keys 1 and '1' are one name
    def test_pattern_keys_int_and_str_collide(self):
        r = api.check(self.song(patterns="  1: |\n    C-5 01\n  '1': |\n    D-5 01\n").replace("orders: [a]", "orders: [1]"), self.dir)
        self.assertFalse(r["ok"])
        self.assertTrue(any("pattern '1' has the same name as pattern 1 " in e for e in r["errors"]), r["errors"])


if __name__ == "__main__":
    unittest.main()
