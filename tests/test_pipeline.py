"""End-to-end tests: song YAML -> .it -> libopenmpt. Run: python -m unittest discover tests"""
import math
import struct
import tempfile
import textwrap
import unittest
from array import array
from pathlib import Path

from vulturetracker import api
from vulturetracker.openmpt import LoadedModule
from vulturetracker.song import SongError, load_song_text
from vulturetracker.wavload import read_wav, write_wav

ROOT = Path(__file__).resolve().parent.parent
RATE = 44100


def sine(freq, seconds=0.5, amp=20000):
    n = int(RATE * seconds)
    return [round(amp * math.sin(2 * math.pi * freq * i / RATE)) for i in range(n)]


def left(pcm):
    a = array("h", pcm)
    return a[0::2]


def rms(xs):
    return math.sqrt(sum(x * x for x in xs) / max(1, len(xs)))


def zero_crossing_freq(xs):
    crossings = sum(1 for a, b in zip(xs, xs[1:]) if a < 0 <= b)
    return crossings * RATE / len(xs)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # 441 Hz and 2205 Hz: whole cycles in 100 / 20 samples, so a full-length loop is seamless.
        write_wav(self.dir / "low.wav", RATE, [sine(441)])
        write_wav(self.dir / "high.wav", RATE, [sine(2205)])

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, song):
        """song: YAML text (dedented here) or a song dict from the api helpers."""
        if isinstance(song, str):
            song = textwrap.dedent(song)
        data, _, _ = api.compile_song(song, self.dir)
        return data


def rows_text(rows, events):
    """Pattern data with row labels: events maps row -> cell text."""
    return "\n".join(f"{r:02d}: {events.get(r, '...')}" for r in range(rows))


class TestStructure(Base):
    def test_minimal_sample_mode(self):
        data = self.build("""
            module: {title: Minimal, tempo: 125, speed: 6, channels: 1}
            samples:
              1: {file: low.wav, loop: {start: 0}}
            patterns:
              only: |
                C-5 01 v64 ...
                ...
                ...
                ...
            orders: [only]
        """)
        with LoadedModule(data) as m:
            info = m.info()
            self.assertEqual(info["warnings"], [])
            self.assertEqual((info["instruments"], info["samples"], info["patterns"]), (0, 1, 1))
            self.assertEqual(info["pattern_rows"], [4])
            self.assertEqual(info["title"], "Minimal")
            self.assertAlmostEqual(info["duration_seconds"], 4 * 6 * 2.5 / 125, places=3)
            cell = m.cell(0, 0, 0)
            self.assertEqual((cell["note"], cell["instrument"], cell["volume"]), (61, 1, 64))

    def test_multi_pattern_instrument_song(self):
        song = """
            module:
              title: Structure
              tempo: 150
              speed: 3
              channels:
                - {name: A, pan: 16}
                - {name: B, pan: 48, volume: 40}
                - {name: C}
            samples:
              1: {file: low.wav, name: lowsine, loop: {start: 0}}
              2: {file: high.wav, name: highsine}
            instruments:
              1: {name: Low, sample: 1}
              2: {name: High, sample: 2, fadeout: 128, nna: fade}
            patterns:
              intro:
                rows: 32
                data: |
                  00: C-5 01 v64 A04 | E-5 02 p10 ...  | ...
                  01: ...            | ...             | G#4 01 ... H44
                  02: ===            | ^^^ .. ... SC2  | ... .. d05 D0F
              main:
                rows: 64
                data: |
                  C-4 02 ... T90 | ... | ... .. ... C00
            orders: [intro, main, +++, intro]
        """
        data = self.build(song)
        res = api.check(textwrap.dedent(song), self.dir)
        self.assertTrue(res["ok"], res["errors"])
        with LoadedModule(data) as m:
            info = m.info()
            self.assertEqual(info["instruments"], 2)
            self.assertEqual(info["samples"], 2)
            self.assertEqual(info["patterns"], 2)
            self.assertEqual(info["pattern_rows"], [32, 64])
            self.assertEqual(info["orders"][:4], [0, 1, 254, 0])
            self.assertEqual(info["instrument_names"], ["Low", "High"])
            self.assertEqual(info["sample_names"], ["lowsine", "highsine"])
            self.assertEqual(info["channels"], 3)
            c = m.cell(0, 0, 0)
            self.assertEqual((c["note"], c["instrument"], c["volume"], c["effect_text"], c["param"]), (61, 1, 64, "A04", 4))
            self.assertEqual(m.cell(0, 0, 1)["volume"], 10)          # p10 -> panning 10
            self.assertEqual(m.cell(0, 1, 2)["note"], 57)            # G#4 = IT note 56
            self.assertEqual(m.cell(0, 1, 2)["effect_text"], "H44")
            self.assertEqual(m.cell(0, 2, 0)["note"], 255)           # note off
            self.assertEqual(m.cell(0, 2, 1)["note"], 254)           # note cut
            self.assertEqual(m.cell(0, 2, 1)["effect_text"], "SC2")
            self.assertEqual(m.cell(0, 2, 2)["effect_text"], "D0F")
            self.assertEqual(m.cell(1, 0, 0)["effect_text"], "T90")

    def test_build_reports_no_mismatch(self):
        (self.dir / "s.yaml").write_text(textwrap.dedent("""
            module: {title: B, channels: 2}
            samples: {1: {file: low.wav}}
            instruments: {1: {name: I, sample: 1}}
            patterns: {p: {rows: 16, data: "C-5 01\\n"}}
            orders: [p]
        """))
        res = api.build(self.dir / "s.yaml", self.dir / "s.it")
        self.assertEqual(res["mismatches"], [])
        self.assertTrue((self.dir / "s.it").stat().st_size > 1000)


class TestInstruments(Base):
    def render_left(self, text):
        with LoadedModule(self.build(text)) as m:
            return left(m.render())

    def test_volume_envelope(self):
        # Speed 6, tempo 125: one tick = 20 ms. The envelope fades 64 -> 0 over 20 ticks (0.4 s).
        base = """
            module: {tempo: 125, speed: 6, channels: 1}
            samples:
              1: {file: low.wav, loop: {start: 0}}
            instruments:
              1:
                name: Env
                sample: 1
                %s
            patterns:
              p:
                rows: 64
                data: |
                  C-5 01 v64
            orders: [p]
        """
        flat = self.render_left(base % "")
        env = self.render_left(base % "volume_envelope: {nodes: [[0, 64], [20, 0]]}")
        early = slice(int(0.02 * RATE), int(0.1 * RATE))
        late = slice(int(0.6 * RATE), int(1.0 * RATE))
        self.assertGreater(rms(flat[late]), 1000)
        self.assertGreater(rms(env[early]), 0.6 * rms(flat[early]))
        self.assertLess(rms(env[late]), 5)

    def test_envelope_sustain_holds_until_note_off(self):
        song = api.new_song(channels=1)
        api.add_sample(song, 1, "low.wav", loop={"start": 0})
        api.add_instrument(song, 1, name="Sus", sample=1,
                           volume_envelope={"nodes": [[0, 64], [5, 32], [15, 0]], "sustain": 1})
        api.set_pattern(song, "p", rows_text(64, {0: "C-5 01 v64", 16: "==="}))  # note-off after 1.92 s
        api.set_orders(song, ["p"])
        with LoadedModule(self.build(song)) as m:
            out = left(m.render())
        peak = rms(out[int(0.01 * RATE):int(0.05 * RATE)])
        held = rms(out[int(1.0 * RATE):int(1.8 * RATE)])
        after = rms(out[int(2.4 * RATE):int(2.8 * RATE)])
        self.assertAlmostEqual(held / peak, 0.5, delta=0.1)   # held at node 1 (value 32 of 64)
        self.assertLess(after, 5)                             # released through the last node to 0

    def test_multisample_keymap(self):
        song = api.new_song(channels=1)
        api.add_sample(song, 1, "low.wav", loop={"start": 0})
        api.add_sample(song, 2, "high.wav", loop={"start": 0})
        api.add_instrument(song, 1, name="Split", keymap=[{"notes": "C-0..B-4", "sample": 1},
                                                          {"notes": "C-5..B-9", "sample": 2}])
        api.add_instrument(song, 2, name="Fixed", keymap=[{"notes": "C-0..B-9", "sample": "low", "play_note": "C-5"}])
        api.set_pattern(song, "p", rows_text(32, {0: "C-4 01", 8: "C-5 01", 16: "C-3 02", 24: "G-7 02"}))
        api.set_orders(song, ["p"])
        with LoadedModule(self.build(song)) as m:
            out = left(m.render())
        row = 0.12 * RATE

        def freq(r):
            return zero_crossing_freq(out[int(r * row + 0.02 * RATE):int((r + 8) * row - 0.02 * RATE)])
        self.assertAlmostEqual(freq(0), 220.5, delta=5)     # C-4 -> low.wav one octave down
        self.assertAlmostEqual(freq(8), 2205, delta=30)     # C-5 -> high.wav at its own pitch
        self.assertAlmostEqual(freq(16), 441, delta=6)      # fixed-pitch map: any note plays C-5
        self.assertAlmostEqual(freq(24), 441, delta=6)


class TestValidation(Base):
    def errors(self, text):
        with self.assertRaises(SongError) as cm:
            load_song_text(textwrap.dedent(text), self.dir, "bad.yaml")
        return cm.exception.errors

    def test_errors_have_line_numbers(self):
        errs = self.errors("""
            module: {channels: 2}
            samples:
              1: {file: low.wav}
            instruments:
              1: {name: I, sample: 1}
            patterns:
              p:
                rows: 4
                data: |
                  C-5 01 v64 ... | Cb5 01
                  C-5 03         | ...
                  C-5 01 ... 0A1 | ...
                  C-5 01 ... a01 | ...
              q:
                rows: 256
                data: |
                  ...
            orders: [p, q]
        """)
        text = "\n".join(errs)
        self.assertIn("bad.yaml:11: error: pattern 'p', row 0, channel 2: bad note 'Cb5'", text)
        self.assertIn("bad.yaml:13: error: pattern 'p', row 2, channel 1: bad effect '0A1'", text)
        self.assertIn("bad.yaml:16: error: pattern 'q': 'rows' = 256 is out of range 1..200", text)
        self.assertNotIn("a01", text)  # a01 is a valid volume command (fine volume up 1)

    def test_row_labels_catch_miscounted_rows(self):
        errs = self.errors("""
            module: {channels: 1}
            samples: {1: {file: low.wav}}
            patterns:
              p:
                rows: 8
                data: |
                  00: C-5 01
                  01: ...
                  03: ...
            orders: [p]
        """)
        self.assertIn("bad.yaml:10: error: pattern 'p': row label 03 but this is row 2", "\n".join(errs))

    def test_unknown_instrument_and_bad_effect_letter(self):
        errs = self.errors("""
            module: {channels: 1}
            samples: {1: {file: low.wav}}
            instruments: {1: {name: I, sample: 1}}
            patterns:
              p: |
                C-5 03
            orders: [p]
        """)
        text = "\n".join(errs)
        self.assertIn("bad.yaml:7: error: pattern 'p', row 0, channel 1: instrument 03 is not defined", text)
        errs = self.errors("""
            module: {channels: 1}
            samples: {1: {file: low.wav}}
            instruments: {1: {name: I, sample: 1}}
            patterns:
              p: |
                C-5 01 ... z0F
            orders: [p]
        """)
        self.assertIn("effect letters are upper case", "\n".join(errs))

    def test_schema_errors(self):
        errs = self.errors("""
            module: {channels: 1, tempo: 20, titel: x}
            samples: {1: {file: missing.wav}}
            instruments:
              1:
                sample: 1
                nna: sometimes
                volume_envelope: {nodes: [[5, 64]], sustain: [0, 3]}
            patterns: {p: "C-5 01\\n"}
            orders: [p, nothere, B00]
        """)
        text = "\n".join(errs)
        for expected in ["bad.yaml:2: error: unknown key 'titel' in module",
                         "bad.yaml:2: error: module: 'tempo' = 20 is out of range 32..255",
                         "bad.yaml:3: error: sample 1: file not found",
                         "bad.yaml:7: error: instrument 1: 'nna' must be one of",
                         "the first node must be at tick 0",
                         "bad.yaml:10: error: orders: unknown pattern 'nothere'"]:
            self.assertIn(expected, text)

    def test_writer_limits_and_yaml_loops_are_errors_not_tracebacks(self):
        # IT holds at most 65535 bytes of cell data per pattern and of message: the writer says so (a ValueError the CLI
        # and the app report), and YAML that nests without end is a SongError
        row = " | ".join(["C-5 01 v64 A06"] * 64)
        text = ("module: {channels: 64}\nsamples: {1: {file: low.wav}}\npatterns:\n  p:\n    rows: 200\n    data: |\n"
                + "".join(f"      {r:03d}: {row}\n" for r in range(150)) + "orders: [p]\n")
        with self.assertRaisesRegex(ValueError, "65535"):
            api.compile_song(text, self.dir)
        text = "module: {channels: 1, message: '" + "x" * 70000 + "'}\nsamples: {1: {file: low.wav}}\npatterns: {p: {rows: 4, data: 'C-5 01'}}\norders: [p]\n"
        with self.assertRaisesRegex(ValueError, "65535"):
            api.compile_song(text, self.dir)
        for text in ("module: &m {channels: 1, message: *m}\nsamples: {1: {file: low.wav}}\npatterns: {p: 'C-5 01'}\norders: [p]\n",
                     "module: {channels: 1}\nsamples: {1: {file: low.wav}}\npatterns: {p: 'C-5 01'}\norders: [p]\nx: " + "[" * 5000 + "]" * 5000 + "\n"):
            res = api.check(text, self.dir)
            self.assertFalse(res["ok"])
            self.assertIn("nests too deeply", res["errors"][0])

    def test_pitch_down_images_warn(self):
        write_wav(self.dir / "bright.wav", RATE, [sine(18000)])

        def warned(cell, module=""):
            text = f"""
                module: {{channels: 1{module}}}
                samples: {{1: {{file: bright.wav}}, 2: {{file: high.wav}}}}
                patterns: {{p: "{cell}\\n"}}
                orders: [p]
            """
            return any("interpolation images" in w for w in load_song_text(textwrap.dedent(text), self.dir)[1])

        self.assertFalse(warned("C-5 01"))                            # at its root every image is above 20 kHz
        self.assertTrue(warned("C-4 01"))                             # an octave down 18 kHz images at 13 kHz
        self.assertFalse(warned("C-4 01", ", sample_rate: 88200"))    # stored at twice the rate: above 20 kHz again
        self.assertFalse(warned("C-3 02"))                            # a 2.2 kHz tone two octaves down: images too weak

    def test_c5_speed_follows_resampling(self):
        # c5_speed is given for the WAV as written: resampling 22050 -> 44100 doubles it, so the pitch stays
        write_wav(self.dir / "half.wav", 22050, [sine(441)])

        def c5(module):
            text = f"""
                module: {{channels: 1{module}}}
                samples: {{1: {{file: half.wav, c5_speed: 22044}}}}
                patterns: {{p: "C-5 01\\n"}}
                orders: [p]
            """
            return load_song_text(textwrap.dedent(text), self.dir)[0].samples[0].c5_speed

        self.assertEqual(c5(""), 22044)
        self.assertEqual(c5(", sample_rate: 44100"), 44088)


class TestWav(Base):
    def test_formats(self):
        # 8-bit unsigned stereo, 24-bit mono, 32-bit float mono
        write_wav(self.dir / "s8.wav", 22050, [[-128, 0, 127], [127, 0, -128]], bits=8)
        w = read_wav(self.dir / "s8.wav")
        self.assertEqual((w.rate, w.out_bits, w.channels), (22050, 8, [[-128, 0, 127], [127, 0, -128]]))

        def raw_wav(path, tag, bits, payload, rate=48000):
            fmt = struct.pack("<HHIIHH", tag, 1, rate, rate * bits // 8, bits // 8, bits)
            body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(payload)) + payload
            path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)

        raw_wav(self.dir / "s24.wav", 1, 24, b"".join(v.to_bytes(3, "little", signed=True) for v in (-8388608, 0, 8388607)))
        self.assertEqual(read_wav(self.dir / "s24.wav").channels, [[-32768, 0, 32767]])
        raw_wav(self.dir / "f32.wav", 3, 32, struct.pack("<3f", -1.0, 0.0, 0.5))
        self.assertEqual(read_wav(self.dir / "f32.wav").channels, [[-32767, 0, 16384]])

        # Stereo source is mixed to mono unless stereo: true; both load in libopenmpt.
        for stereo in ("false", "true"):
            data = self.build(f"""
                module: {{channels: 1}}
                samples: {{1: {{file: s8.wav, stereo: {stereo}}}}}
                patterns: {{p: "C-5 01\\n"}}
                orders: [p]
            """)
            with LoadedModule(data) as m:
                self.assertEqual(m.info()["samples"], 1)


    def test_malformed_headers_are_wav_errors(self):
        # a header the reader cannot use is a WavError (which check reports by line), never a ZeroDivisionError or a
        # struct.error escaping as a crash
        from vulturetracker.wavload import WavError

        def wav(fmt, payload=b"\0" * 8):
            body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(payload)) + payload
            return b"RIFF" + struct.pack("<I", len(body)) + body

        pack = lambda tag, nch, rate, align, bits: struct.pack("<HHIIHH", tag, nch, rate, rate * align, align, bits)  # noqa: E731
        for name, fmt in (("no channels", pack(1, 0, 44100, 2, 16)), ("no alignment", pack(1, 1, 44100, 0, 16)),
                          ("width 0", pack(1, 4, 44100, 2, 16)), ("rate 0", pack(1, 1, 0, 2, 16)), ("short fmt", b"\1\0\1\0")):
            (self.dir / "bad.wav").write_bytes(wav(fmt))
            with self.assertRaises(WavError, msg=name):
                read_wav(self.dir / "bad.wav")
            res = api.check("module: {channels: 1}\nsamples: {1: {file: bad.wav}}\npatterns: {p: {rows: 4, data: 'C-5 01'}}\norders: [p]\n", self.dir)
            self.assertFalse(res["ok"], name)
            self.assertIn("bad.wav", res["errors"][0])


class TestDocs(unittest.TestCase):
    def test_song_format_minimal_example_compiles(self):
        doc = (ROOT / "SONG_FORMAT.md").read_text(encoding="utf-8")
        example = doc.split("```yaml\n", 1)[1].split("```", 1)[0]
        res = api.check(example, ROOT)
        self.assertTrue(res["ok"], res["errors"])
        self.assertEqual(res["warnings"], [])


class TestDemo(unittest.TestCase):
    def test_demo_builds_and_loops(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = api.build(ROOT / "demo" / "arena.yaml", Path(tmp) / "arena.it")
        self.assertEqual(res["mismatches"], [])
        self.assertEqual(res["warnings"], [])
        info = res["libopenmpt"]
        self.assertGreaterEqual(info["instruments"], 3)
        self.assertTrue(30 <= info["duration_seconds"] <= 60, info["duration_seconds"])

    def test_demo2_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = api.build(ROOT / "demo2" / "iron_relay.yaml", Path(tmp) / "iron_relay.it")
        self.assertEqual(res["mismatches"], [])
        self.assertEqual(res["warnings"], [])
        self.assertEqual(res["libopenmpt"]["channels"], 16)


if __name__ == "__main__":
    unittest.main()
