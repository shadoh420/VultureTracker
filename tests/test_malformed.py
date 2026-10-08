"""Malformed input to the importers (what tools/fuzz_import.py found, kept as regressions): every bad file is a
ValueError (ITReadError, ModReadError, WavError, a plain ValueError from the MIDI and Guitar Pro imports) with a
message, raised at once, never a hang, a gigabyte grid or an exception the app does not catch."""
import struct
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vulturetracker.itreader import ITReadError, import_it
from vulturetracker.modreader import ModReadError, read_module
from vulturetracker.wavload import WavError, read_wav

try:
    import mido
except ImportError:  # pragma: no cover
    mido = None
try:
    import guitarpro
except ImportError:  # pragma: no cover
    guitarpro = None


def it_header(**fields):
    """An IT header (0xC0 bytes) with the counts in `fields` (ordnum, insnum, smpnum, patnum)."""
    h = bytearray(0xC0)
    h[:4] = b"IMPM"
    struct.pack_into("<8H", h, 0x20, fields.get("ordnum", 0), fields.get("insnum", 0), fields.get("smpnum", 0),
                     fields.get("patnum", 0), 0x214, 0x214, 0, 0)
    h[0x30:0x36] = bytes((128, 48, 6, 125, 128, 0))
    return bytes(h)


def xm_header(npat=0, nins=0, nch=4):
    return (b"Extended Module: " + b"t".ljust(20) + b"\x1a" + b"t".ljust(20) +
            struct.pack("<HI8H", 0x0104, 276, 1, 0, nch, npat, nins, 0, 6, 125) + bytes(256))


def s3m_header(nins=0, npat=0):
    h = bytearray(0x60)
    h[0x1C], h[0x1D] = 0x1A, 16
    struct.pack_into("<6H", h, 0x20, 0, nins, npat, 0, 0x1320, 2)
    h[0x2C:0x30] = b"SCRM"
    h[0x30:0x34] = bytes((64, 6, 125, 0x30))
    h[0x40:0x60] = bytes(range(4)) + bytes([255] * 28)
    return bytes(h)


def midi(tracks, division=480, kind=1):
    """A MIDI file from raw track bodies (end-of-track appended)."""
    out = b"MThd" + struct.pack(">IHHH", 6, kind, len(tracks), division)
    for body in tracks:
        body += b"\0\xff\x2f\0"
        out += b"MTrk" + struct.pack(">I", len(body)) + body
    return out


class Clean(unittest.TestCase):
    """The error is one of the family the app catches, and it says something."""

    def assertClean(self, fn, *args, kind=ValueError):
        t = time.monotonic()
        with self.assertRaises(kind) as cm:
            fn(*args)
        self.assertTrue(str(cm.exception).strip(), f"{type(cm.exception).__name__} without a message")
        self.assertLess(time.monotonic() - t, 15, "took too long")  # XM allocates up to the budget before refusing
        return cm.exception

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def file(self, name, data):
        p = self.dir / name
        p.write_bytes(data)
        return p


class TestSanity(Clean):
    def test_modules_empty_and_header_only(self):
        for name, data in (("it", it_header()), ("xm", xm_header()), ("s3m", s3m_header()),
                           ("mod", bytes(1080) + b"M.K.")):
            for cut in (b"", data[:1], data):
                with self.subTest(name, size=len(cut)):
                    try:
                        read_module(cut)  # a bare header may be an empty but readable module
                    except (ITReadError, ModReadError) as e:
                        self.assertTrue(str(e))
            self.assertClean(import_it, self.file("x." + name, data[:1]), self.dir / "x.yaml", self.dir / "x_s")

    def test_wav_empty_and_header_only(self):
        for data in (b"", b"R", b"RIFF\0\0\0\0WAVE", b"RIFF\x04\0\0\0WAVEfmt \x10\0\0\0"):
            self.assertClean(read_wav, self.file("x.wav", data), kind=WavError)

    @unittest.skipIf(mido is None, "mido not installed")
    def test_midi_empty_and_header_only(self):
        from vulturetracker.midiimport import import_midi
        for data in (b"", b"M", b"MThd" + struct.pack(">IHHH", 6, 1, 1, 480), midi([b""])):
            self.assertClean(import_midi, self.file("x.mid", data), self.dir / "x.yaml", self.dir / "x_s")

    @unittest.skipIf(guitarpro is None, "PyGuitarPro not installed")
    def test_gp_empty_and_header_only(self):
        from vulturetracker.gpimport import import_gp
        for data in (b"", b"\x18", b"\x18FICHIER GUITAR PRO v5.00".ljust(31, b"\0")):
            self.assertClean(import_gp, self.file("x.gp5", data), self.dir / "x.yaml", self.dir / "x_s")


class TestCounts(Clean):
    """Headers claiming more than a module can hold used to take minutes and gigabytes before _sanitize dropped it."""

    def test_it_instrument_and_sample_counts(self):
        e = self.assertClean(read_module, it_header(insnum=65535), kind=ITReadError)
        self.assertIn("65535 instruments", str(e))
        self.assertClean(read_module, it_header(smpnum=65535), kind=ITReadError)

    def test_it_pattern_cells(self):
        n = 200  # 200 pointers at one 1024-row pattern header: 13 million cells on the 64-wide grid
        head = it_header(patnum=n)
        ptrs = struct.pack(f"<{n}I", *([len(head) + 4 * n] * n))
        e = self.assertClean(read_module, head + ptrs + struct.pack("<HHI", 0, 1024, 0), kind=ITReadError)
        self.assertIn("million cells", str(e))
        # zero pointers: each an empty 64-row pattern on every channel the others use (here 64: a note on channel 64)
        n = 65535
        head = it_header(patnum=n)
        data = head + struct.pack("<I", len(head) + 4 * n) + bytes(4 * (n - 1)) + struct.pack("<HHI", 3, 1, 0) + b"\xc0\x01\x3c"
        e = self.assertClean(read_module, data, kind=ITReadError)
        self.assertIn("million cells", str(e))

    def test_it_sample_frames(self):
        n = 2000  # 2000 pointers at one 20000-frame stereo sample header
        head = it_header(smpnum=n)
        p = len(head) + 4 * n
        smp = bytearray(0x50)
        smp[:4], smp[0x12] = b"IMPS", 1 | 4
        struct.pack_into("<7I", smp, 0x30, 20000, 0, 0, 8363, 0, 0, p + 0x50)
        e = self.assertClean(read_module, head + struct.pack(f"<{n}I", *([p] * n)) + bytes(smp), kind=ITReadError)
        self.assertIn("million frames", str(e))

    def test_xm_counts(self):
        e = self.assertClean(read_module, xm_header(nins=65535) + bytes(1 << 16), kind=ModReadError)
        self.assertIn("65535 instruments", str(e))
        e = self.assertClean(read_module, xm_header(npat=2000) + struct.pack("<IBHH", 9, 0, 1024, 0) * 2000, kind=ModReadError)
        self.assertIn("million cells", str(e))
        ins = struct.pack("<I", 263) + b"i".ljust(22, b"\0") + b"\0" + struct.pack("<HI", 5000, 40) + bytes(263 - 33)
        e = self.assertClean(read_module, xm_header(nins=1) + ins, kind=ModReadError)
        self.assertIn("5000 samples", str(e))

    def test_s3m_counts(self):
        for data in (s3m_header(npat=65535) + bytes(1 << 20), s3m_header(nins=65535) + bytes(1 << 20)):
            e = self.assertClean(read_module, data, kind=ModReadError)
            self.assertIn("65535", str(e))
        n = 2000  # 2000 instrument pointers at one stereo 20000-frame sample header
        head = s3m_header(nins=n)
        o = len(head) + 2 * n
        o += (-o) % 16
        smp = bytearray(0x50)
        smp[0], smp[0x1F] = 1, 2
        struct.pack_into("<3I", smp, 0x10, 20000, 0, 0)
        data = head + struct.pack(f"<{n}H", *([o // 16] * n))
        e = self.assertClean(read_module, data.ljust(o, b"\0") + bytes(smp) + bytes(16384), kind=ModReadError)
        self.assertIn("million frames", str(e))

    def test_libopenmpt_refusing_the_original_is_a_warning(self):
        # a file our reader reads and libopenmpt refuses (the fuzzer's: an S3M with its file type byte off): the import
        # still writes the song, saying the level was not matched (OpenMPTError is not one the app catches)
        from tests.test_modimport import C5, E_S3M, TONE, grid, write_s3m
        from vulturetracker.openmpt import OpenMPTError
        d = write_s3m([("tone", TONE, 64, 8363, (0, 4000))], [grid([(0, 0, (C5, 1, None, 0, 0))], E_S3M)], [0])
        with mock.patch("vulturetracker.modreader.match_level", side_effect=OpenMPTError("could not load module")):
            song, warnings = import_it(self.file("x.s3m", d), self.dir / "x.yaml", self.dir / "x_s")
        self.assertTrue(any("libopenmpt cannot load" in w for w in warnings), warnings)
        self.assertTrue((self.dir / "x.yaml").exists())


@unittest.skipIf(mido is None, "mido not installed")
class TestMidi(Clean):
    def run_midi(self, data):
        from vulturetracker.midiimport import import_midi
        return import_midi(self.file("x.mid", data), self.dir / "x.yaml", self.dir / "x_s")

    def test_header_chunk_size_is_not_preallocated(self):
        # a header claiming 4 GB: read from memory, not file.read(size), so no allocation of what it claims
        data = midi([b"\0\x90\x3c\x64\x60\x80\x3c\0"])
        self.assertClean(self.run_midi, data[:4] + b"\xff\xff\0\x06" + data[8:])

    def test_zero_division_and_tempo(self):
        note = b"\0\x90\x3c\x64\x60\x80\x3c\0"
        e = self.assertClean(self.run_midi, midi([note], division=0))
        self.assertIn("time division", str(e))
        song, warnings = self.run_midi(midi([b"\0\xff\x51\x03\0\0\0" + note]))  # set_tempo 0: no tempo, 120 BPM
        self.assertEqual(song["module"]["tempo"], 120)

    def test_tiny_bars_with_a_far_note_end_quickly(self):
        # a 4/2^255 time signature makes a bar one tick long; a note 2^27 ticks out used to loop over every tick
        t = time.monotonic()
        song, warnings = self.run_midi(midi([b"\0\xff\x58\x04\x04\xff\x18\x08" + b"\0\x90\x3c\x64" + b"\xff\xff\xff\x7f\x80\x3c\0"]))
        self.assertLess(time.monotonic() - t, 5)
        self.assertTrue(any("bars" in w for w in warnings), warnings)


@unittest.skipIf(guitarpro is None, "PyGuitarPro not installed")
class TestGuitarPro(Clean):
    def test_tempo_zero(self):
        from tests.test_gpimport import tab
        from vulturetracker.gpimport import import_gp
        tab(self.dir / "t.gp5")
        song = guitarpro.parse(str(self.dir / "t.gp5"))
        song.tempo = 0
        guitarpro.write(song, str(self.dir / "z.gp5"))
        out, warnings = import_gp(self.dir / "z.gp5", self.dir / "z.yaml", self.dir / "z_s")
        self.assertTrue(any("tempo is 0" in w for w in warnings), warnings)


if __name__ == "__main__":
    unittest.main()
