"""GUI state tests: measurement, the order/channel usage map, header patching, meters and the in-place YAML writes.
No HTTP, no browser."""
import json
import math
import struct
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from vulturetracker import gui
from vulturetracker.wavload import write_wav

RATE = 44100


def sine(freq, seconds=0.3, amp=20000):
    return [round(amp * math.sin(2 * math.pi * freq * i / RATE) * (1 - i / (RATE * seconds))) for i in range(int(RATE * seconds))]


SONG = """\
# a comment that must survive the apply
module: {title: T, tempo: 125, speed: 6, channels: [{name: A}, {name: B}]}
samples:
  1: {file: a.wav, name: A tone}
  2: {file: b.wav, name: B tone}
patterns:
  p1:
    rows: 4
    data: |
      00: C-5 01 ... ... | ... .. ... ...
      01: ... .. ... ... | ... .. ... ...
      02: ... .. ... ... | C-5 02 ... ...
      03: ... .. ... ... | ... .. ... ...
  p2:
    rows: 4
    data: |
      00: C-5 02 ... ... | ... .. ... ...
      01: ... .. ... ... | ... .. ... ...
      02: ... .. ... ... | ... .. ... ...
      03: ... .. ... ... | ... .. ... ...
orders: [p1, p2]
"""
# the same song with a block-style module: the mixer writes its lines in place
SONG_BLOCK = SONG.replace("module: {title: T, tempo: 125, speed: 6, channels: [{name: A}, {name: B}]}\n",
                          "module:\n  title: T\n  tempo: 125\n  speed: 6\n  channels:\n    - {name: A}\n    - {name: B, pan: 40}\n")


class TestGui(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_wav(self.dir / "a.wav", RATE, [sine(440)], root_note=69)
        write_wav(self.dir / "b.wav", RATE, [sine(880)])
        write_wav(self.dir / "cand.wav", RATE, [sine(660)], root_note=64)
        (self.dir / "song.yaml").write_bytes(SONG.encode("utf-8"))  # LF on every platform (write_text would give CRLF on Windows)
        self.states = []

    def state(self):
        """A State whose worker is drained before the temp dir goes (it compiles and measures on its own thread)."""
        st = gui.State(self.dir / "song.yaml")
        self.states.append(st)
        return st

    def tearDown(self):
        for st in self.states:
            for _ in range(400):
                busy = st.jobs.qsize() or any(r["status"] in ("queued", "rendering") for r in st.renders.values())                     or (st.meters and st.meters["status"] in ("queued", "measuring"))
                if not busy:
                    break
                time.sleep(0.05)
        self.tmp.cleanup()

    def test_measure(self):
        m = gui.measure(self.dir / "a.wav")
        self.assertAlmostEqual(m["duration"], 0.3, places=3)
        self.assertEqual(m["root"], "A-5")
        self.assertTrue(m["wave"].count(",") == 200)
        if m["centroid"] is not None:  # numpy present
            self.assertEqual(m["pitch"], "A-5")
            self.assertLess(abs(m["centroid"] - 440), 60)

    def test_facts_usage_map(self):
        f = gui.song_facts(SONG, self.dir, "song")
        self.assertEqual(f["channels"], ["A", "B"])
        self.assertEqual(f["use"], [[[1], [2]], [[2], []]])
        self.assertAlmostEqual(f["orders"][0]["seconds"], 4 * 6 * 2.5 / 125)

    def test_render_diff_apply(self):
        st = self.state()
        st.meta["slot"] = 1
        st.add_candidates("cand.wav")
        for _ in range(100):
            snap = st.snapshot()
            if snap["candidates"][0]["status"] == "ready":
                break
            time.sleep(0.05)
        self.assertEqual(snap["candidates"][0]["status"], "ready", snap["candidates"][0]["error"])
        self.assertTrue(Path(snap["candidates"][0]["key"] and st.renders[snap["candidates"][0]["key"]]["file"]).exists())
        d = st.diff(str(self.dir / "cand.wav"))
        self.assertFalse(d["redump"])
        self.assertIn("+  1: {file: cand.wav, name: cand, base_note: E-5}", d["lines"])
        st.apply(str(self.dir / "cand.wav"))
        text = (self.dir / "song.yaml").read_text(encoding="utf-8")
        self.assertIn("# a comment that must survive the apply", text)
        self.assertIn("  1: {file: cand.wav, name: cand, base_note: E-5}\n", text)
        self.assertIn("  2: {file: b.wav, name: B tone}", text)
        meta = json.loads((self.dir / "song.tryout.json").read_text())
        self.assertNotIn("1", meta["candidates"])  # the choice is made: U clears the slot's list
        self.assertEqual(st.snapshot()["candidates"], [])

    def test_pattern_rows_and_mutes(self):
        from vulturetracker import api
        st = self.state()
        self.assertEqual(st.pattern_rows(1)["rows"][0], ["C-5 02 ... ...", "... .. ... ..."])
        self.assertEqual(st.facts["orders"][1]["index"], 1)
        self.assertEqual(st.facts["pan"], [32, 32])
        cand = str(self.dir / "cand.wav")
        k = st.key(cand)
        st.meta["solo"] = 1
        self.assertEqual(st.silenced(), [0])
        self.assertNotEqual(st.key(cand), k)  # mutes are part of the render cache key
        # the IT channel-disable bit, patched into the compiled module's header, silences a channel in libopenmpt's render
        from vulturetracker.openmpt import LoadedModule
        it = api.compile_song(api.tryout_song(self.dir / "song.yaml"), self.dir)[0]
        with LoadedModule(gui.patch_it(it, [0, 1])) as lm:
            self.assertEqual(set(lm.render(RATE)), {0})
        with LoadedModule(gui.patch_it(it, [1])) as lm:
            self.assertNotEqual(set(lm.render(RATE)), {0})

    def test_mix_patch_meters_and_write(self):
        (self.dir / "song.yaml").write_text(SONG_BLOCK, encoding="utf-8")
        st = self.state()
        k = st.key()
        st.set_mix({"volume": {"0": 32}, "pan": {"1": 0}, "mix_volume": 100, "sample_volume": {"2": 40}})
        self.assertNotEqual(st.key(), k)  # the faders are part of the render cache key
        d = gui.patch_it(st.compiled_it(), [], st.mix())
        self.assertEqual((d[0x80], d[0x81], d[0x40], d[0x41], d[0x31]), (32, 64, 32, 0, 100))
        nord, nins, nsmp = struct.unpack_from("<HHH", d, 0x20)
        off = struct.unpack_from("<I", d, 0xC0 + nord + 4 * nins + 4)[0]  # sample 2's header
        self.assertEqual(d[off:off + 4], b"IMPS")
        self.assertEqual(d[off + 0x11], 40)
        # meters: each channel soloed, both play something in the section
        levels = gui.channel_levels(d, 2)
        self.assertEqual([l["active_db"] is not None and l["active_db"] < 0 for l in levels], [True, True])
        self.assertLess(levels[0]["db"], levels[0]["active_db"])  # the whole render includes its silence
        for _ in range(200):  # the worker measures the same thing for the page
            if st.meters and st.meters["status"] in ("ready", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(st.meters["status"], "ready", st.meters)
        self.assertEqual(st.meters["levels"], levels)
        # writing the mix edits the lines in place, keeps the comment, adds a missing mix_volume
        new, redump = st.mix_text()
        self.assertFalse(redump)
        self.assertIn("# a comment that must survive the apply", new)
        self.assertIn("module:\n  mix_volume: 100\n  title: T\n", new)
        self.assertIn("    - {name: A, volume: 32}\n    - {name: B, pan: 0}\n", new)
        st2 = self.state()  # a hand-aligned, commented line keeps its spacing: only the value changes
        st2.text = st2.text.replace("    - {name: B, pan: 40}\n", "    - {name: B,     pan: 40, volume: 64}  # right\n")
        st2.meta["mix"] = {"pan": {"1": 8}}
        self.assertIn("    - {name: B,     pan: 8, volume: 64}  # right\n", st2.mix_text()[0])
        self.assertIn("  2: {file: b.wav, name: B tone, global_volume: 40}\n", new)
        self.assertEqual(st.mix_diff()["redump"], False)
        st.apply_mix()
        self.assertEqual(st.mix(), {})
        self.assertEqual((st.facts["volume"], st.facts["pan"], st.facts["mix_volume"]), ([32, 64], [32, 0], 100))
        self.assertEqual(st.song["samples"][2]["global_volume"], 40)

    def test_facts_timing_follows_effects(self):
        row = 6 * 2.5 / 125

        def timeline(text):  # per order (start, seconds) in rows, and the duration in rows
            f = gui.song_facts(text, self.dir, "song")
            return [(round(o["start"] / row, 3), round(o["seconds"] / row, 3)) for o in f["orders"]], round(f["duration"] / row, 3)

        # p1 breaks to p2 after one row
        self.assertEqual(timeline(SONG.replace("00: C-5 01 ... ... |", "00: C-5 01 ... C00 |")), ([(0, 1), (1, 4)], 5))
        # p1 breaks into row 2 of p2 after two rows
        self.assertEqual(timeline(SONG.replace("01: ... .. ... ... | ... .. ... ...\n      02: ... .. ... ... | C-5 02",
                                               "01: ... .. ... C02 | ... .. ... ...\n      02: ... .. ... ... | C-5 02")), ([(0, 2), (2, 2)], 4))
        # p1 jumps to order 2 after one row; order 1 never plays
        self.assertEqual(timeline(SONG.replace("00: C-5 01 ... ... |", "00: C-5 01 ... B02 |").replace("orders: [p1, p2]", "orders: [p1, p2, p2]")),
                         ([(0, 1), (5, 0), (1, 4)], 5))

    def test_key_stamps_every_sample_in_the_mix(self):
        st = self.state()
        cand = str(self.dir / "cand.wav")
        k = st.key(cand)
        write_wav(self.dir / "b.wav", RATE, [sine(770, seconds=0.2)])  # another slot's WAV re-rendered in place
        self.assertNotEqual(st.key(cand), k)

    def test_patch_keeps_block_mapping_and_comments(self):
        text = SONG.replace("  2: {file: b.wav, name: B tone}\n",
                            "  2:\n    file: b.wav  # the B tone\n    name: B tone\n  # slot 3 would come next\n")
        (self.dir / "song.yaml").write_text(text, encoding="utf-8")
        st = self.state()
        st.meta["slot"] = 2
        new, redump = st.patched_text(str(self.dir / "cand.wav"))
        self.assertFalse(redump)
        self.assertIn("# a comment that must survive the apply", new)
        self.assertIn("  1: {file: a.wav, name: A tone}\n  2:\n    file: cand.wav\n    name: cand\n    base_note: E-5\n"
                      "  # slot 3 would come next\npatterns:", new)

    def test_stems_export(self):
        st = self.state()
        st.request_stems()
        for _ in range(200):
            if st.stems["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(st.stems["status"], "done", st.stems)
        self.assertEqual(sorted(p.name for p in (self.dir / "song_stems").glob("*.wav")), ["01-A.wav", "02-B.wav"])
        self.assertGreater((self.dir / "song_stems" / "02-B.wav").stat().st_size, 1000)

    def test_sounding(self):
        st = self.state()
        # a.wav and b.wav last 0.3 s and a row is 0.12 s, so a hit sounds for three rows
        s = st.sounding(0, 1)
        self.assertEqual([(x["ch"], x["sample"], x["ago"], x["note"]) for x in s], [(0, 1, 1, "C-5")])
        self.assertEqual([(x["ch"], x["sample"], x["ago"]) for x in st.sounding(0, 3)], [(1, 2, 1)])  # A's hit is over
        # order 1 row 0: A restarts with sample 2, B's hit from order 0 row 2 is still ringing
        self.assertEqual([(x["ch"], x["sample"], x["ago"], x["order"]) for x in st.sounding(1, 0)], [(0, 2, 0, 1), (1, 2, 2, 0)])
        self.assertEqual(st.sounding_rows(1)[0], [[0, 2, 0], [1, 2, 0]])
        # a note-off silences the channel from there on
        st.mod.patterns[1].rows[0][1].note = 255
        st.sound_table = None
        self.assertEqual([x["ch"] for x in st.sounding(1, 0)], [0])
        # a note without an instrument keeps the channel's last instrument (a slide target)
        st.mod.patterns[0].rows[1][0].note = 62
        st.sound_table = None
        self.assertEqual([(x["ch"], x["sample"], x["ago"], x["note"]) for x in st.sounding(0, 1)], [(0, 1, 0, "D-5")])

    def test_notes_file_and_report(self):
        st = self.state()
        n = st.add_note({"order": 0, "row": 2, "tag": "too loud", "channels": [1], "source": "song"})
        self.assertEqual([x["ch"] for x in n["sounding"]], [0, 1])
        self.assertAlmostEqual(n["time"], 2 * 6 * 2.5 / 125, places=2)
        notes = json.loads((self.dir / "song.notes.json").read_text(encoding="utf-8"))
        self.assertEqual((len(notes), notes[0]["tag"], notes[0]["pattern"], notes[0]["version"]["hash"]), (1, "too loud", "p1", st.version()["hash"]))
        md = (self.dir / "song.notes.md").read_text(encoding="utf-8")
        self.assertIn("- **TOO LOUD** at 0:00.2, row 02: A 01, **B 02**. Playing the song.", md)
        st.edit_note(n["id"], {"text": "the B tone", "channels": [0]})
        md = (self.dir / "song.notes.md").read_text(encoding="utf-8")
        self.assertIn('**A 01**, B 02. Playing the song. "the B tone"', md)
        self.assertEqual(st.snapshot()["notes"][0]["text"], "the B tone")
        st.notes[0]["sounding"] = []  # a rebuilt table recomputes the sounding list of a note made against this song text
        st.sound_table = None
        st.sounding(1, 0)
        self.assertEqual([x["ch"] for x in st.notes[0]["sounding"]], [0, 1])
        self.assertIn("**A 01**, B 02", (self.dir / "song.notes.md").read_text(encoding="utf-8"))  # channel A is the picked one
        st.edit_note(n["id"], {"delete": True})
        self.assertEqual(json.loads((self.dir / "song.notes.json").read_text(encoding="utf-8")), [])
        self.assertEqual(st.snapshot()["cand_counts"], {})

    def test_apply_keeps_line_endings(self):
        st = self.state()
        st.meta["slot"] = 1
        st.apply(str(self.dir / "cand.wav"))
        self.assertNotIn(b"\r\n", (self.dir / "song.yaml").read_bytes())  # an LF file stays LF
        (self.dir / "song.yaml").write_bytes(SONG.replace("\n", "\r\n").encode("utf-8"))
        st2 = self.state()
        st2.meta["slot"] = 2
        st2.apply(str(self.dir / "cand.wav"))
        data = (self.dir / "song.yaml").read_bytes()
        self.assertEqual(data.count(b"\r\n"), data.count(b"\n"))  # a CRLF file stays CRLF
        self.assertIn(b"  2: {file: cand.wav, name: cand, base_note: E-5}\r\n", data)

    def test_notes_archive_when_the_song_changes_outside_the_app(self):
        st = self.state()
        st.add_note({"order": 0, "row": 2, "tag": "keep"})
        old = st.version()["hash"]
        st.apply(str(self.dir / "cand.wav"))          # the app's own write keeps the notes (the report marks their version)
        self.assertEqual(len(st.notes), 1)
        self.assertIn(f"(made against version {old})", (self.dir / "song.notes.md").read_text(encoding="utf-8"))
        (self.dir / "song.yaml").write_bytes(SONG.replace("title: T", "title: T2").encode("utf-8"))
        st.reload()                                   # a change from outside archives them
        self.assertEqual(st.notes, [])
        self.assertEqual(len(json.loads((self.dir / f"song.notes-{old}.json").read_text(encoding="utf-8"))), 1)
        self.assertIn(f"version {old}", (self.dir / f"song.notes-{old}.md").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((self.dir / "song.notes.json").read_text(encoding="utf-8")), [])
        self.assertEqual(st.snapshot()["archives"], [f"song.notes-{old}.md"])
        st.add_note({"order": 0, "row": 0, "tag": "keep"})   # ids restart with the version
        self.assertEqual(st.notes[0]["id"], 1)

    def test_want_and_priorities(self):
        st = self.state()
        st.meta["slot"] = 1
        st.add_candidates("cand.wav")
        cand = str((self.dir / "cand.wav").resolve())
        st.set_want(cand)
        self.assertEqual(st.want, cand)
        self.assertEqual(st.snapshot()["cand_counts"], {"1": 1})
        st.set_want(None)
        self.assertIsNone(st.want)
        self.assertIsNone(gui.channel_levels(b"", 2, cancel=lambda: True))  # a cancelled pass renders nothing


if __name__ == "__main__":
    unittest.main()
