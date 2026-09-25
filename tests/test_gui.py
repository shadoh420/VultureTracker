"""GUI state tests: measurement, the order/channel usage map, header patching, meters and the in-place YAML writes.
No HTTP, no browser."""
import json
import math
import struct
import tempfile
import textwrap
import time
import unittest
from unittest import mock
from pathlib import Path

from vulturetracker import api, gui
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
# the same song played through instruments (the instrument panel edits them): A plain, B with an envelope of its own
SONG_INS = SONG.replace("patterns:\n", "instruments:\n  1: {name: A, sample: 1, fadeout: 128}  # the lead\n"
                        "  2: {name: B, sample: 2, volume_envelope: {nodes: [[0, 64], [3, 50], [9, 20], [20, 0]]}}\npatterns:\n")
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
        # each playable order keeps its index in the module (the live engine reports that), past a +++ marker too
        g = gui.song_facts(SONG.replace("orders: [p1, p2]", "orders: [p1, +++, p2]"), self.dir, "song")
        self.assertEqual([o["order"] for o in g["orders"]], [0, 2])

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

    def wait_export(self, st):
        for _ in range(400):
            if st.stems["status"] in ("done", "failed"):
                return
            time.sleep(0.05)

    def test_mp3_export(self):
        try:
            gui.ffmpeg_exe()
        except OSError:
            self.skipTest("no ffmpeg (imageio-ffmpeg or PATH)")
        st = self.state()
        st.request_stems("mp3", song=True, stems=True)
        self.wait_export(st)
        self.assertEqual(st.stems["status"], "done", st.stems)
        self.assertEqual((st.stems["total"], st.stems["song"]), (3, str(self.dir / "song.mp3")))
        self.assertEqual(sorted(p.name for p in (self.dir / "song_stems").iterdir()), ["01-A.mp3", "02-B.mp3"])
        for p in (self.dir / "song.mp3", self.dir / "song_stems" / "02-B.mp3"):
            head = p.read_bytes()[:3]
            self.assertTrue(head == b"ID3" or head[0] == 0xFF, (p, head))  # an ID3 tag or an MPEG frame sync
        for fmt, magic in (("ogg", b"OggS"), ("flac", b"fLaC")):  # the other encoded formats, the song alone
            st.request_stems(fmt, song=True, stems=False)
            self.wait_export(st)
            self.assertEqual((st.stems["status"], st.stems["total"]), ("done", 1), st.stems)
            self.assertEqual((self.dir / f"song.{fmt}").read_bytes()[:4], magic)
        # the song alone, and a missing ffmpeg says what it needs instead of rendering
        (self.dir / "song.mp3").unlink()
        from unittest import mock
        with mock.patch.object(gui, "ffmpeg_exe", side_effect=OSError("MP3 export needs ffmpeg")):
            st.request_stems("mp3", song=True, stems=False)
            self.wait_export(st)
        self.assertEqual((st.stems["status"], st.stems["error"], st.stems["dir"]), ("failed", "MP3 export needs ffmpeg", None))
        self.assertFalse((self.dir / "song.mp3").exists())

    def test_ffmpeg_beside_the_exe_comes_first(self):
        from unittest import mock
        (self.dir / "vulturetracker.exe").write_bytes(b"")
        (self.dir / "ffmpeg.exe").write_bytes(b"")
        with mock.patch.object(gui.sys, "frozen", True, create=True), \
                mock.patch.object(gui.sys, "executable", str(self.dir / "vulturetracker.exe")):
            self.assertEqual(gui.ffmpeg_exe(), str(self.dir / "ffmpeg.exe"))

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
        # a one-shot lasts its length at the note's rate: two octaves up, the 0.3 s hit is over within a row
        st.mod.patterns[0].rows[1][0].note = 84
        st.sound_table = None
        self.assertEqual([x["ch"] for x in st.sounding(0, 1)], [0])
        self.assertEqual([x["ch"] for x in st.sounding(0, 2)], [1])

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

    def test_apply_and_write_mix_are_checked_and_undoable(self):
        # U and WRITE MIX are written the way every edit is: refused while the song changed on disk (the hand edit would
        # be lost), compiled whole before anything is written, and one undo step each
        import os
        (self.dir / "song.yaml").write_bytes(SONG_BLOCK.encode("utf-8"))
        st = self.state()
        st.set_mix({"volume": {"0": 32}})
        time.sleep(0.02)
        (self.dir / "song.yaml").write_bytes(SONG_BLOCK.replace("title: T", "title: T2").encode("utf-8"))
        os.utime(self.dir / "song.yaml", None)
        with self.assertRaises(ValueError):
            st.apply_mix()
        with self.assertRaises(ValueError):
            st.apply(str(self.dir / "cand.wav"))
        self.assertIn("title: T2", (self.dir / "song.yaml").read_text(encoding="utf-8"))  # the hand edit is still there
        st.reload()
        st.apply_mix()
        self.assertEqual((st.facts["volume"], st.mix(), len(st.history)), ([32, 64], {}, 1))
        write_wav(self.dir / "hi.wav", RATE, [sine(660)], root_note=125)  # a smpl root above B-9 is no base_note (C2)
        st.apply(str(self.dir / "hi.wav"))
        self.assertNotIn("~~~", (self.dir / "song.yaml").read_text(encoding="utf-8"))
        self.assertEqual((st.error, len(st.history)), (None, 2))
        before = (self.dir / "song.yaml").read_bytes()
        with mock.patch.object(gui, "load_song_text", side_effect=gui.SongError(["broken"], [])):
            with self.assertRaises(gui.SongError):  # a write that does not compile: nothing is written
                st.apply(str(self.dir / "cand.wav"))
        self.assertEqual(((self.dir / "song.yaml").read_bytes(), len(st.history)), (before, 2))
        st.apply(str(self.dir / "cand.wav"))
        self.assertEqual((st.song["samples"][1]["file"], len(st.history)), ("cand.wav", 3))
        st.undo()
        st.undo()
        st.undo()
        self.assertEqual((self.dir / "song.yaml").read_text(encoding="utf-8"), SONG_BLOCK.replace("title: T", "title: T2"))

    def test_a_song_that_does_not_parse_or_compile_still_opens(self):
        (self.dir / "song.yaml").write_bytes((SONG + "patterns: [\n").encode("utf-8"))  # a YAML syntax error
        st = self.state()
        self.assertIn("YAML syntax", st.error[0])
        self.assertEqual((st.facts, st.song, st.snapshot()["song"]["error"]), (None, {}, st.error))
        with self.assertRaises(ValueError):  # edits need the compiled song: refused with the reason
            st.edit_cells(0, [{"row": 0, "ch": 0, "cell": "... .. ... ..."}])
        (self.dir / "song.yaml").write_bytes(b"module: {channels: 1}\npatterns: {p: 'C-5 01'}\norders: [p]\n")  # no samples
        st2 = self.state()
        self.assertTrue(st2.snapshot()["song"]["error"])
        with self.assertRaises(ValueError):
            st2.edit_cells(0, [{"row": 0, "ch": 0, "cell": "... .. ... ..."}])
        (self.dir / "empty").mkdir()  # a path that does not exist leaves nothing behind
        with self.assertRaises(OSError):
            gui.State(self.dir / "empty" / "ghost.yaml")
        self.assertEqual(list((self.dir / "empty").iterdir()), [])

    def test_zero_padded_slot_numbers(self):
        # 08: is a legal slot key (the compiler reads it as 8); the app's dict of the song must read it the same way
        text = SONG.replace("  2: {file: b.wav, name: B tone}\n", "  08: {file: b.wav, name: B tone}\n").replace("C-5 02", "C-5 08")
        (self.dir / "song.yaml").write_bytes(text.encode("utf-8"))
        (self.dir / "song.tryout.json").write_text('{"slot": 3}', encoding="utf-8")  # a slot the song no longer has
        st = self.state()
        self.assertEqual((st.error, list(st.song["samples"]), st.slot), (None, [1, 8], 1))
        st.meta["slot"] = 8
        self.assertEqual(st.snapshot()["slot_entry"]["name"], "B tone")
        self.assertEqual(st.sample_view(8)["frames"], 13230)
        st.set_mix({"sample_volume": {"8": 40}})
        new, redump = st.mix_text()
        self.assertFalse(redump)
        self.assertIn("  08: {file: b.wav, name: B tone, global_volume: 40}\n", new)

    def test_entries_written_across_lines_are_refused(self):
        (self.dir / "song.yaml").write_bytes(SONG.replace("  2: {file: b.wav, name: B tone}\n", "  2: {file: b.wav,\n      name: B tone}\n").encode("utf-8"))
        st = self.state()
        self.assertIsNone(st.error)
        with self.assertRaises(ValueError):
            st.song_edit([{"op": "sample_set", "num": 2, "entry": {"file": "b.wav", "name": "B", "volume": 50}}])
        self.assertIn("  2: {file: b.wav,\n      name: B tone}\n", (self.dir / "song.yaml").read_text(encoding="utf-8"))

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

    def test_voice_params(self):
        ins = {"name": "Call", "sample": 7, "nna": "fade", "fadeout": 128}
        self.assertEqual(gui.voice_of(ins), ({"attack": 0, "decay": 0, "sustain": 64, "release": 128, "cutoff": 127,
                                              "resonance": 0, "sweep_from": 64, "sweep_to": 64, "sweep_ticks": 0,
                                              "random": 0}, []))
        e = gui.voice_entry(ins, {"attack": 2, "decay": 10, "sustain": 40, "cutoff": 90, "resonance": 30,
                                  "sweep_from": 26, "sweep_ticks": 16, "random": 20})
        self.assertEqual(e["volume_envelope"], {"nodes": [[0, 0], [2, 64], [12, 40]], "sustain": 2})  # held until note-off
        self.assertEqual(e["pitch_envelope"], {"nodes": [[0, -6], [16, 32]], "filter": True})  # 26/64 of the cutoff, opening
        self.assertEqual((e["filter_cutoff"], e["filter_resonance"], e["random_volume"], e["nna"]), (90, 30, 20, "fade"))
        p, custom = gui.voice_of(e)
        self.assertEqual((p["attack"], p["decay"], p["sustain"], p["sweep_from"], p["sweep_to"], p["sweep_ticks"], custom),
                         (2, 10, 40, 26, 64, 16, []))  # the panel reads back what it wrote
        self.assertEqual(gui.voice_entry(e, {"attack": 0, "sustain": 64, "cutoff": 127, "resonance": 0, "sweep_from": 64,
                                             "random": 0}), ins)  # all back at rest: the fields go
        self.assertNotIn("sustain", gui.voice_entry(ins, {"sustain": 0, "decay": 8})["volume_envelope"])  # dies away
        sub = {"name": "Sub", "sample": 4, "volume_envelope": {"nodes": [[0, 64], [6, 58], [40, 38], [140, 0]]}}
        self.assertEqual(gui.voice_of(sub)[1], ["volume"])  # a shape the panel cannot show
        self.assertEqual(gui.voice_entry(sub, {"cutoff": 80})["volume_envelope"], sub["volume_envelope"])  # kept
        self.assertNotIn("volume_envelope", gui.voice_entry(sub, {"attack": 0}))  # moving its slider replaces it

    def test_instrument_panel_compile_and_write(self):
        import numpy as np
        from vulturetracker.openmpt import LoadedModule
        (self.dir / "song.yaml").write_bytes(SONG_INS.encode("utf-8"))
        st = self.state()
        st.meta["slot"] = 1
        self.assertEqual([(v["num"], v["name"], v["custom"], v["edit"]) for v in st.snapshot()["voice"]], [(1, "A", [], {})])
        before = st.compiled_it()
        k = st.ckey()

        def power_near(it, hz):  # A's tone: the 440 Hz file (root A-5) played on C-5 sounds 262 Hz
            with LoadedModule(it) as lm:
                x = np.frombuffer(lm.render(RATE), "<i2").astype(float).reshape(-1, 2).mean(axis=1)
            f = np.fft.rfftfreq(len(x), 1 / RATE)
            return float((np.abs(np.fft.rfft(x)) ** 2)[(f > hz - 10) & (f < hz + 10)].sum())
        st.set_mix({"instrument": {"1": {"cutoff": 0}}})
        self.assertLess(power_near(st.compiled_it(), 261.6), 0.25 * power_near(before, 261.6))  # the closed filter
        st.set_mix({"instrument": {"1": {"cutoff": 0, "attack": 4, "random": 25, "release": 128, "sweep_to": 99},
                                   "2": {"cutoff": 60}}})
        self.assertEqual(st.mix()["instrument"], {"1": {"cutoff": 0, "attack": 4, "random": 25}, "2": {"cutoff": 60}})
        # sweep_to 99 is clamped to 64 and the release is 128: both the song's own values, so no change
        self.assertNotEqual(st.ckey(), k)  # compiled in, so part of the compile key
        self.assertNotEqual(st.live_it(), gui.patch_it(st.it, (), st.mix()))  # the live engine plays the panel too
        d = st.compiled_it()
        nord = struct.unpack_from("<H", d, 0x20)[0]
        off = struct.unpack_from("<I", d, 0xC0 + nord)[0]  # instrument 1's header
        self.assertEqual(d[off:off + 4], b"IMPI")
        self.assertEqual((d[off + 0x3A], d[off + 0x1A]), (0x80, 25))  # filter cutoff 0 (enabled bit), random volume
        self.assertEqual(d[off + 0x130] & 5, 5)  # the volume envelope, enabled, with a sustain point
        new, redump = st.mix_text()
        self.assertFalse(redump)
        self.assertIn("  1: {name: A, sample: 1, fadeout: 128, volume_envelope: {nodes: [[0, 0], [4, 64]], sustain: 1}, "
                      "filter_cutoff: 0, filter_resonance: 0, random_volume: 25}  # the lead\n", new)
        self.assertIn("filter_cutoff: 60", new)
        self.assertIn("volume_envelope: {nodes: [[0, 64], [3, 50], [9, 20], [20, 0]]}", new)  # B's own envelope stays
        st.apply_mix()
        self.assertEqual(st.mix(), {})
        self.assertEqual(st.song["instruments"][1]["filter_cutoff"], 0)
        self.assertEqual(st.snapshot()["voice"][0]["song"]["attack"], 4)


    def test_spectrogram(self):
        import numpy as np
        # 2 s of a full-scale 1 kHz sine, then 1 s of silence: the level, the band and the time axis
        x = np.round(32767 * np.sin(2 * np.pi * 1000 * np.arange(2 * RATE) / RATE)).astype("<i2")
        pcm = np.repeat(np.concatenate([x, np.zeros(RATE, "<i2")]), 2).tobytes()
        gui._write_pcm(self.dir / "r.wav", pcm)
        for scale in ("log", "lin"):
            db, edges = gui.spectrogram(self.dir / "r.wav", scale, cols=300, rows=200)
            self.assertEqual(db.shape, (200, 300))
            row = int(db[:, 100].argmax())
            self.assertLessEqual(edges[row] - 45, 1000)  # the loudest band holds 1 kHz (within a bin's width)
            self.assertGreaterEqual(edges[row + 1] + 45, 1000)
            self.assertGreater(db[row, 100], -1.5)        # a full-scale sine reads about 0 dBFS
            self.assertLess(db[:, 260:].max(), -120)      # the last third is silent: columns follow time
            self.assertGreater(db[row, 195], -6)          # still sounding just before 2 s
        png = gui.spectrogram_png(str(self.dir / "r.wav"), "t", "log")
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (1200, 256))  # width, height


    def test_typed_values_clamp_to_the_song_format(self):
        # a typed value goes through the fader's path (set_mix): out of range, it lands on the song format's limit
        ins = SONG_INS[SONG_INS.index("instruments:"):SONG_INS.index("patterns:")]
        (self.dir / "song.yaml").write_bytes(SONG_BLOCK.replace("patterns:\n", ins + "patterns:\n").encode("utf-8"))
        st = self.state()
        st.set_mix({"volume": {"0": 99}, "pan": {"0": "surround", "1": -7}, "mix_volume": 500, "sample_volume": {"2": 80},
                    "instrument": {"1": {"release": 999, "cutoff": -4, "random": 101}}})
        self.assertEqual(st.mix(), {"volume": {"0": 64}, "pan": {"0": "surround", "1": 0}, "mix_volume": 128,
                                    "sample_volume": {"2": 64}, "instrument": {"1": {"release": 256, "cutoff": 0, "random": 100}}})
        self.assertEqual(st.snapshot()["voice_range"]["release"], (0, 256))  # the page clamps to the same ranges
        new, redump = st.mix_text()
        self.assertFalse(redump)
        self.assertIn("    - {name: A, volume: 64, pan: surround}\n    - {name: B, pan: 0}\n", new)
        self.assertIn("mix_volume: 128", new)
        self.assertIn("fadeout: 256", new)


    def test_playback_loop(self):
        st = self.state()
        k, section = st.key(), st.orders
        st.set_loop({"from": [1, 9], "to": [0, 2]})  # reversed and past the pattern's end: clamped and put in order
        self.assertEqual(st.snapshot()["loop"], {"from": [0, 2], "to": [1, 3]})
        self.assertEqual((st.key(), st.orders), (k, section))  # playback only: no render key or section changes
        self.assertEqual(json.loads((self.dir / "song.tryout.json").read_text())["loop"], {"from": [0, 2], "to": [1, 3]})
        note = st.add_note({"order": 0, "row": 2})
        self.assertEqual(note["playing"]["loop"], {"from": [0, 2], "to": [1, 3]})
        self.assertIn("looping ord 0 row 2 to ord 1 row 3", st.report())
        st.set_loop({})
        self.assertIsNone(st.snapshot()["loop"])


    def test_swap_keeps_a_name_an_instrument_refers_to(self):
        # a keymap that names the slot ("A tone") must still resolve with a candidate in it, rendered and written
        (self.dir / "song.yaml").write_bytes(SONG_INS.replace("{name: A, sample: 1, fadeout: 128}",
                                                              "{name: A, keymap: [{notes: C-5, sample: A tone}]}").encode("utf-8"))
        st = self.state()
        cand = str(self.dir / "cand.wav")
        self.assertTrue(st.compiled_it(cand).startswith(b"IMPM"))
        self.assertIn("+  1: {file: cand.wav, name: A tone, base_note: E-5}", st.diff(cand)["lines"])
        st.meta["slot"] = 2  # slot 2 is referenced by number only: it takes the WAV's name
        self.assertIn("+  2: {file: cand.wav, name: cand, base_note: E-5}", st.diff(cand)["lines"])


    def test_live_engine_serves_the_whole_song_with_the_mix(self):
        from vulturetracker.openmpt import LoadedModule
        st = self.state()
        st.meta["orders"] = [1, 2]  # a tryout section does not narrow what the live engine plays
        st.set_mix({"volume": {"1": 20}, "mix_volume": 90})
        d = st.live_it()
        self.assertEqual((d[0x81], d[0x31]), (20, 90))  # the unwritten mix is in the header
        with LoadedModule(d) as lm:
            self.assertEqual(lm.info()["orders"], [0, 1])
        st.set_mix({})
        self.assertIs(st.compiled_it(whole=True), st.it)  # the song as reload compiled it, not a second compile
        self.assertEqual(st.it, api.compile_song(api.tryout_song(st.song, None), self.dir)[0])
        js = gui.worklet_js().decode("utf-8")
        self.assertTrue(js.startswith("const loadGlue = function (libopenmpt, require, __dirname) {"))
        self.assertIn("function openmptEngine(", js)
        self.assertIn("registerProcessor('vt-engine', VTEngine);", js)


    def test_pattern_edit_in_place_and_undo(self):
        # p1 as the generators write it (labels, a comment row, a trailing comment), two rows given of eight; p2 bare
        text = SONG.replace("""  p1:
    rows: 4
    data: |
      00: C-5 01 ... ... | ... .. ... ...
      01: ... .. ... ... | ... .. ... ...
      02: ... .. ... ... | C-5 02 ... ...
      03: ... .. ... ... | ... .. ... ...
""", """  p1:
    rows: 8
    data: |
      ; a        | b
      000: C-5 01 ... ... | ... .. ... ...  ; the hit
      001: ... .. ... ... |   ...   .. ...   ...
""")
        (self.dir / "song.yaml").write_bytes(text.encode("utf-8"))
        st = self.state()
        st.edit_cells(0, [{"row": 0, "ch": 1, "cell": "E-5 02 v40 ..."}])
        new = (self.dir / "song.yaml").read_bytes().decode("utf-8")
        self.assertIn("      000: C-5 01 ... ... | E-5 02 v40 ...  ; the hit\n", new)
        self.assertIn("      001: ... .. ... ... |   ...   .. ...   ...\n", new)  # the untouched row keeps its spacing
        st.edit_cells(0, [{"row": 4, "ch": 0, "cell": "===" + " .. ... ..."}, {"row": 1, "ch": 0, "cell": "D-5 01 ... A06"}])
        new = (self.dir / "song.yaml").read_bytes().decode("utf-8")
        self.assertIn("      001: D-5 01 ... A06 |   ...   .. ...   ...\n"
                      "      002: ... .. ... ... | ... .. ... ...\n      003: ... .. ... ... | ... .. ... ...\n"
                      "      004: === .. ... ... | ... .. ... ...\n  p2:", new)  # implied rows written out, labels in their width
        self.assertEqual(st.pattern_rows(0)["rows"][4][0], "=== .. ... ...")
        self.assertEqual(st.snapshot()["undo"], 2)
        # a cell the song format refuses is not written
        before = (self.dir / "song.yaml").read_bytes()
        with self.assertRaises(gui.SongError):
            st.edit_cells(1, [{"row": 0, "ch": 1, "cell": "C-5 01 v99 ..."}])
        self.assertEqual((self.dir / "song.yaml").read_bytes(), before)
        # an unlabelled block, a new cell beyond the row's two
        st.edit_cells(1, [{"row": 2, "ch": 1, "cell": "G-5 02 ... ..."}])
        self.assertEqual(st.pattern_rows(1)["rows"][2], ["... .. ... ...", "G-5 02 ... ..."])
        # undo walks back to the original text, redo forward again
        st.undo()
        st.undo()
        st.undo()
        self.assertEqual((self.dir / "song.yaml").read_bytes().decode("utf-8"), text)
        self.assertEqual(st.snapshot()["redo"], 3)
        st.undo(redo=True)
        self.assertIn("E-5 02 v40", (self.dir / "song.yaml").read_bytes().decode("utf-8"))
        # a change on disk since the app read the song blocks edits and undo
        time.sleep(0.02)
        (self.dir / "song.yaml").write_bytes(text.encode("utf-8"))
        import os
        os.utime(self.dir / "song.yaml", None)
        with self.assertRaises(ValueError):
            st.edit_cells(0, [{"row": 0, "ch": 0, "cell": "... .. ... ..."}])


    def test_edits_across_patterns_are_one_undo_step(self):
        st = self.state()
        st.edit_patterns([(0, [{"row": 1, "ch": 0, "cell": "E-5 01 ... ..."}]), (1, [{"row": 3, "ch": 1, "cell": "G-5 02 ... ..."}])])
        self.assertEqual((st.pattern_rows(0)["rows"][1][0], st.pattern_rows(1)["rows"][3][1]), ("E-5 01 ... ...", "G-5 02 ... ..."))
        self.assertEqual(st.snapshot()["undo"], 1)
        # one refused cell refuses the whole step
        with self.assertRaises(gui.SongError):
            st.edit_patterns([(0, [{"row": 0, "ch": 1, "cell": "D-5 02 ... ..."}]), (1, [{"row": 0, "ch": 1, "cell": "D-5 07 ... ..."}])])
        self.assertEqual(st.pattern_rows(0)["rows"][0][1], "... .. ... ...")
        st.undo()
        self.assertEqual((self.dir / "song.yaml").read_bytes().decode("utf-8"), SONG)


    def test_undo_keeps_the_newest_steps(self):
        st = self.state()
        st.UNDO_LIMIT = 3
        for v in range(5):
            st.edit_cells(0, [{"row": 1, "ch": 0, "cell": f"... .. v{v:02d} ..."}])
        self.assertEqual(st.snapshot()["undo"], 3)
        for _ in range(3):
            st.undo()
        self.assertEqual(st.pattern_rows(0)["rows"][1][0], "... .. v01 ...")  # back three steps, and no further

    def test_song_structure_edits(self):
        (self.dir / "song.yaml").write_bytes(SONG_BLOCK.encode("utf-8"))
        st = self.state()
        read = lambda: (self.dir / "song.yaml").read_bytes().decode("utf-8")  # noqa: E731
        st.song_edit([{"op": "orders", "orders": ["p1", "p2", "p1"]}])
        self.assertIn("orders: [p1, p2, p1]\n", read())
        # a new pattern and a clone, placed in the order list in the same step
        st.song_edit([{"op": "pattern_new", "name": "p3", "rows": 8}, {"op": "pattern_clone", "src": "p1", "name": "p1b"},
                      {"op": "orders", "orders": ["p1", "p3", "p2", "p1b"]}])
        text = read()
        self.assertIn("  p3:\n    rows: 8\n    data: |\norders: [p1, p3, p2, p1b]", text)
        self.assertIn("  p1b:\n    rows: 4\n    data: |\n      00: C-5 01 ... ... |", text)
        self.assertEqual([o["pattern"] for o in st.facts["orders"]], ["p1", "p3", "p2", "p1b"])
        st.edit_cells(st.facts["orders"][1]["index"], [{"row": 2, "ch": 1, "cell": "D-5 02 ... ..."}])
        self.assertEqual(st.pattern_rows(st.facts["orders"][1]["index"])["rows"][2][1], "D-5 02 ... ...")
        # rename (the order list follows), resize (rows past the end go), delete (only when unused)
        st.song_edit([{"op": "pattern_rename", "old": "p2", "new": "verse"}, {"op": "pattern_rows", "name": "p1", "rows": 2},
                      {"op": "orders", "orders": ["p1", "p3", "verse"]}, {"op": "pattern_delete", "name": "p1b"}])
        text = read()
        self.assertIn("  verse:\n", text)
        self.assertIn("orders: [p1, p3, verse]", text)
        self.assertIn("  p1:\n    rows: 2\n    data: |\n      00: C-5 01 ... ... | ... .. ... ...\n      01: ... .. ... ... | ... .. ... ...\n  verse:", text)
        self.assertNotIn("p1b", text)
        with self.assertRaises(ValueError):
            st.song_edit([{"op": "pattern_delete", "name": "p1"}])
        # channels: rename, add, move (cells, mutes and faders follow), remove
        st.set_mix({"volume": {"0": 30}})
        st.song_edit([{"op": "channel_rename", "ch": 1, "name": "Bass line"}, {"op": "channel_add", "name": "Pad"}])
        self.assertIn("    - {name: Bass line, pan: 40}\n    - {name: Pad}\n", read())
        st.song_edit([{"op": "channel_move", "ch": 0, "to": 2}])
        self.assertEqual(st.facts["channels"], ["Bass line", "Pad", "A"])
        self.assertEqual(st.pattern_rows(st.facts["orders"][0]["index"])["rows"][0], ["... .. ... ...", "... .. ... ...", "C-5 01 ... ..."])
        self.assertEqual(st.mix()["volume"], {"2": 30})
        st.song_edit([{"op": "channel_remove", "ch": 1}])
        self.assertEqual(st.facts["channels"], ["Bass line", "A"])
        self.assertEqual(st.pattern_rows(st.facts["orders"][0]["index"])["rows"][0], ["... .. ... ...", "C-5 01 ... ..."])
        self.assertEqual(st.mix()["volume"], {"1": 30})
        # module settings keep their comments and layout
        st.song_edit([{"op": "module", "key": "tempo", "value": 400}, {"op": "module", "key": "title", "value": "New: title"}])
        text = read()
        self.assertIn("  tempo: 255\n", text)
        self.assertIn('  title: "New: title"\n', text)
        self.assertEqual(st.facts["title"], "New: title")
        # every step undoes back to the original text
        while st.snapshot()["undo"]:
            st.undo()
        self.assertEqual(read(), SONG_BLOCK)


    def test_new_song_and_instrument_edits(self):
        p = gui.create_song(self.dir / "fresh", channels=3)
        self.assertEqual(p.name, "fresh.yaml")
        self.assertTrue((self.dir / "fresh_tone.wav").exists())
        self.assertNotIn(b"\r\n", p.read_bytes())
        with self.assertRaises(ValueError):
            gui.create_song(p)  # never over an existing file
        st = gui.State(p)
        self.states.append(st)
        self.assertEqual((st.facts["channels"], st.error), (["Ch 1", "Ch 2", "Ch 3"], None))
        read = lambda: p.read_bytes().decode("utf-8")  # noqa: E731
        st.song_edit([{"op": "sample_new", "file": str(self.dir / "a.wav")},
                      {"op": "instrument_new", "entry": {"name": "Lead", "sample": 2, "nna": "fade"}}])
        self.assertIn("  2: {file: a.wav, name: a}\ninstruments:\n  1: {name: fresh_tone, sample: 1}\n  2: {name: Lead, sample: 2, nna: fade}\n", read())
        env = {"nodes": [[0, 64], [8, 32], [20, 0]], "sustain": 1}
        st.song_edit([{"op": "instrument_set", "num": 2, "entry": {"name": "Lead", "keymap": [{"notes": "C-0..B-4", "sample": 1},
                      {"notes": "C-5..B-9", "sample": 2, "transpose": -12}], "volume_envelope": env, "fadeout": 32}}])
        ins = st.mod.instruments[1]
        self.assertEqual((ins.keymap[40][1], ins.keymap[70], ins.fadeout), (1, (58, 2), 32))
        self.assertEqual(st.song["instruments"][2]["volume_envelope"], env)
        with self.assertRaises(gui.SongError):  # a sustain node that does not exist is refused, nothing written
            st.song_edit([{"op": "instrument_set", "num": 2, "entry": {"name": "Lead", "sample": 2, "volume_envelope": {"nodes": [[0, 64]], "sustain": 3}}}])
        st.set_mix({"instrument": {"1": {"cutoff": 40}}})
        with self.assertRaises(ValueError):  # unwritten tryout settings on the instrument come first
            st.song_edit([{"op": "instrument_set", "num": 1, "entry": {"name": "x", "sample": 1}}])
        st.set_mix({})
        st.edit_cells(0, [{"row": 0, "ch": 0, "cell": "C-5 02 ... ..."}])
        with self.assertRaises(gui.SongError):  # a pattern plays instrument 2
            st.song_edit([{"op": "instrument_delete", "num": 2}])
        st.edit_cells(0, [{"row": 0, "ch": 0, "cell": "... .. ... ..."}])
        st.song_edit([{"op": "instrument_delete", "num": 2}])
        self.assertEqual(list(st.song["instruments"]), [1])

    def test_sample_editor(self):
        (self.dir / "song.yaml").write_bytes(SONG_INS.encode("utf-8"))
        st = self.state()
        song, src = self.dir / "song.yaml", (self.dir / "a.wav").read_bytes()
        original = song.read_bytes()
        read = lambda: song.read_bytes().decode("utf-8")  # noqa: E731
        v = st.sample_view(1, 0, None, 100)
        self.assertEqual((v["frames"], v["rate"], v["channels"], len(v["max"][0]), v["player"]), (13230, RATE, 1, 100, [0, 60]))
        self.assertGreater(v["max"][0][0], 0.3)
        z = st.sample_view(1, 100, 150, 100)  # zoomed in past one frame per column: the frames themselves
        self.assertEqual((len(z["min"][0]), z["min"], z["a"], z["b"]), (50, z["max"], 100, 150))
        # loop points and properties are written into the entry in place, one undo step each
        st.song_edit([{"op": "sample_set", "num": 1, "entry": {"file": "a.wav", "name": "A tone", "loop": {"start": 1000, "end": 5000}}}])
        self.assertIn("  1: {file: a.wav, name: A tone, loop: {start: 1000, end: 5000}}\n", read())
        self.assertEqual((st.mod.samples[0].loop.start, st.mod.samples[0].loop.end), (1000, 5000))
        e = dict(st.song["samples"][1], base_note="A-5", name="Lead A")  # scalars only: the line keeps its layout
        st.song_edit([{"op": "sample_set", "num": 1, "entry": e}])
        self.assertIn("  1: {file: a.wav, name: Lead A, loop: {start: 1000, end: 5000}, base_note: A-5}\n", read())
        self.assertEqual(st.mod.samples[0].c5_speed, round(RATE * 2 ** (-9 / 12)))
        before = read()
        with self.assertRaises(gui.SongError):  # a loop past the end is refused, nothing written
            st.song_edit([{"op": "sample_set", "num": 1, "entry": dict(e, loop={"start": 0, "end": 99999})}])
        self.assertEqual(read(), before)
        st.set_mix({"sample_volume": {"1": 30}})
        with self.assertRaises(ValueError):  # an unwritten GAIN on the slot comes first
            st.song_edit([{"op": "sample_set", "num": 1, "entry": dict(e, global_volume=40)}])
        st.set_mix({})
        # edits of the audio write a new WAV beside the song and point the slot at it; the source is never touched
        st.song_edit([{"op": "sample_process", "num": 1, "action": "trim", "a": 500, "b": 10500}])
        self.assertEqual(st.song["samples"][1]["file"], "a-trim.wav")
        self.assertEqual(st.song["samples"][1]["loop"], {"start": 500, "end": 4500})
        self.assertEqual(st.sample_view(1)["frames"], 10000)
        st.song_edit([{"op": "sample_process", "num": 1, "action": "crossfade", "frames": 400}])
        self.assertEqual(st.song["samples"][1]["file"], "a-crossfade.wav")
        x = st._sample_wav(1)[3][0]
        y = gui.wav_array(str(self.dir / "a-trim.wav"), 0)[1][0]
        self.assertLess(abs(x[4499] - y[499]), 0.01)  # the loop's last frame now leads into its start
        self.assertEqual(x[4099], y[4099])
        st.song_edit([{"op": "sample_process", "num": 1, "action": "reverse"}])
        self.assertEqual(st.song["samples"][1]["loop"], {"start": 5500, "end": 9500})
        for action in ("fade_in", "fade_out", "normalize", "dc"):
            st.song_edit([{"op": "sample_process", "num": 1, "action": action, "a": 0, "b": 2000}])
        self.assertAlmostEqual(float(abs(st._sample_wav(1)[3][0][:2000]).max()), 1.0, places=3)
        wavs = sorted(p.name for p in self.dir.glob("*.wav"))
        with self.assertRaises(ValueError):  # a crossfade with no audio before the loop start: refused, no file left
            st.song_edit([{"op": "sample_process", "num": 2, "action": "crossfade", "frames": 100}])
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.wav")), wavs)
        while st.history:
            st.undo()
        self.assertEqual((song.read_bytes(), (self.dir / "a.wav").read_bytes()), (original, src))


    def test_import_beside_the_module(self):
        from tests.test_modimport import EMPTY4, TONE, grid, write_mod
        mod = self.dir / "old.mod"
        mod.write_bytes(write_mod([("tone", TONE, 64, 0, 0, 4000)], [grid([(0, 0, (428, 1, 0, 0))], EMPTY4)], [0]))
        out, warnings = gui.import_beside(mod)
        self.assertEqual((out.name, (self.dir / "old_samples" / "01_tone.wav").exists(), warnings[:0]), ("old.yaml", True, []))
        st = gui.State(out)
        self.states.append(st)
        self.assertEqual((st.error, len(st.facts["channels"]), st.pattern_rows(0)["rows"][0][0]), (None, 4, "C-5 01 ... ..."))
        self.assertEqual(gui.import_beside(mod)[0].name, "old-2.yaml")  # never over the first import

    def test_other_pages_are_refused(self):
        import threading
        import urllib.error
        import urllib.request
        srv = gui._Server(("127.0.0.1", 0), gui.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def call(path, data=None, **headers):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers)
            try:
                return urllib.request.urlopen(req, timeout=5).status
            except urllib.error.HTTPError as e:
                return e.code
        try:
            self.assertEqual(call("/api/start"), 200)  # a local tool: no Origin
            self.assertEqual(call("/api/start", Origin=f"http://127.0.0.1:{port}"), 200)  # the page itself
            self.assertEqual(call("/api/new", b'{"path": "x.yaml"}', Origin="https://example.com"), 403)  # another page's form post
            self.assertEqual(call("/api/start", Host="attacker.example"), 403)  # DNS rebinding
            self.assertFalse(Path("x.yaml").exists())
        finally:
            srv.shutdown()
            srv.server_close()

    def test_bad_requests_are_answered(self):
        # a body the action cannot use gets a 400 with the reason; the connection is never dropped without an answer
        import threading
        import urllib.error
        import urllib.request
        gui.Handler.state = self.state()
        srv = gui._Server(("127.0.0.1", 0), gui.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def call(path, data=None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data)
            try:
                return urllib.request.urlopen(req, timeout=5).status
            except urllib.error.HTTPError as e:
                return e.code
        try:
            for path, data in (("/api/slot", b'{"slot": []}'), ("/api/slot", b"not json"), ("/api/mute", b"[1, 2]"),
                               ("/api/edit", b'{"pattern": 0, "cells": 5}')):
                self.assertEqual(call(path, data), 400, (path, data))
            self.assertEqual(call("/api/diff/7"), 400)
            self.assertEqual(call("/api/mixdiff"), 200)
        finally:
            srv.shutdown()
            srv.server_close()
            gui.Handler.state = None

    # ---- the September 2026 audit's findings, each pinned

    def serve(self, state):
        """The HTTP server on a free port with `state` open; returns (port, stop)."""
        import threading
        gui.Handler.state = state
        srv = gui._Server(("127.0.0.1", 0), gui.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        def stop():
            srv.shutdown()
            srv.server_close()
            gui.Handler.state = None
        return srv.server_address[1], stop

    @staticmethod
    def fetch(port, path, data=None, **headers):
        """(status, headers, body) of a request to the local server."""
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_undo_brings_the_tryout_settings_back(self):
        # F3: removing a channel moves the mutes and faders of the channels after it; undo puts them back on the channel
        # they were set on (and redo moves them again); undo of WRITE MIX brings the unwritten mix back, of U the list
        (self.dir / "song.yaml").write_bytes(SONG_BLOCK.encode("utf-8"))
        st = self.state()
        st.song_edit([{"op": "channel_add", "name": "C"}])
        st.meta["muted"] = [2]
        st.save_meta()
        st.set_mix({"volume": {"2": 10}})
        st.song_edit([{"op": "channel_remove", "ch": 1}])
        self.assertEqual((st.meta["muted"], st.mix()["volume"]), ([1], {"1": 10}))
        st.undo()
        self.assertEqual((st.facts["channels"], st.meta["muted"], st.mix()["volume"]), (["A", "B", "C"], [2], {"2": 10}))
        st.undo(redo=True)
        self.assertEqual((st.facts["channels"], st.meta["muted"], st.mix()["volume"]), (["A", "C"], [1], {"1": 10}))
        st.apply_mix()
        self.assertEqual(st.mix(), {})
        st.undo()
        self.assertEqual(st.mix()["volume"], {"1": 10})
        st.add_candidates("cand.wav")
        st.apply(str(self.dir / "cand.wav"))
        self.assertEqual(st.cands(), [])
        st.undo()
        self.assertEqual(st.cands(), [str((self.dir / "cand.wav").resolve())])
        # an edit that changes no tryout setting leaves them alone on undo (a fader moved since stays)
        st.edit_cells(0, [{"row": 1, "ch": 0, "cell": "D-5 01 ... ..."}])
        st.set_mix({"volume": {"0": 20}})
        st.undo()
        self.assertEqual(st.mix()["volume"], {"0": 20})

    def test_sample_process_undo_keeps_the_new_wav(self):
        # T6: undo of an edit of a slot's audio points the slot back at its WAV; the new WAV stays beside the song
        (self.dir / "song.yaml").write_bytes(SONG_INS.encode("utf-8"))
        st = self.state()
        st.song_edit([{"op": "sample_process", "num": 1, "action": "reverse"}])
        new = self.dir / st.song["samples"][1]["file"]
        self.assertEqual(new.name, "a-reverse.wav")
        st.undo()
        self.assertEqual((st.song["samples"][1]["file"], new.exists()), ("a.wav", True))

    def test_a_tryout_section_with_a_jump_outside_it_renders(self):
        # F4: the loop idiom (B00 at the end of the last pattern) jumps outside a section that does not hold order 0;
        # the section's copy drops that jump (and renumbers one inside the slice) instead of failing to compile
        song = SONG.replace("      03: ... .. ... ... | ... .. ... ...\norders", "      03: ... .. ... ... | ... .. ... B00\norders")
        song = song.replace("orders: [p1, p2]", "orders: [p1, p1, p2]").replace("      02: ... .. ... ... | C-5 02 ... ...",
                                                                                "      02: ... .. ... B02 | C-5 02 ... ...")
        d = api.from_yaml(song)
        self.assertEqual(api.tryout_song(d, (2, 3))["patterns"]["p2"]["data"].splitlines()[3], "03: ... .. ... ... | ... .. ... ...")
        cut = api.tryout_song(d, (1, 3))
        self.assertIn("02: ... .. ... B01 | C-5 02 ... ...", cut["patterns"]["p1"]["data"])  # order 2 is the slice's 1
        api.compile_song(cut, self.dir)
        (self.dir / "song.yaml").write_bytes(song.encode("utf-8"))
        st = self.state()
        st.meta["orders"] = [2, 3]
        st.queue_all()
        for _ in range(100):
            r = st.renders.get(st.key())
            if r and r["status"] in ("ready", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(r["status"], "ready", r.get("error"))

    def test_a_block_order_list_keeps_its_layout_and_comments(self):
        # F5: an order list written one '- name' per line stays so; an entry that survives keeps its comments
        block = "orders:\n  - p1  # intro\n  # the drop\n  - p2\n"
        (self.dir / "song.yaml").write_bytes(SONG.replace("orders: [p1, p2]\n", block).encode("utf-8"))
        st = self.state()
        st.song_edit([{"op": "orders", "orders": ["p2", "p1", "p1"]}])
        self.assertTrue((self.dir / "song.yaml").read_text(encoding="utf-8").endswith(
            "orders:\n  # the drop\n  - p2\n  - p1  # intro\n  - p1\n"))
        self.assertEqual([o["pattern"] for o in st.facts["orders"]], ["p2", "p1", "p1"])
        st.song_edit([{"op": "orders", "orders": ["p1"]}])
        self.assertTrue((self.dir / "song.yaml").read_text(encoding="utf-8").endswith("orders:\n  - p1  # intro\n"))
        (self.dir / "song.yaml").write_bytes(SONG.replace("orders: [p1, p2]\n", "orders: [p1,  # a\n  p2]\n").encode("utf-8"))
        st.reload()
        with self.assertRaisesRegex(ValueError, "comments"):
            st.song_edit([{"op": "orders", "orders": ["p2"]}])

    def test_a_byte_order_mark_is_kept_and_does_not_hide_module(self):
        # F8: a song saved with a BOM before `module:` is edited in place and keeps its BOM
        (self.dir / "song.yaml").write_bytes(b"\xef\xbb\xbf" + SONG_BLOCK.split("\n", 1)[1].encode("utf-8"))  # module: first
        st = self.state()
        st.set_mix({"volume": {"0": 32}})
        self.assertFalse(st.mix_text()[1])  # written in place, not re-dumped
        st.apply_mix()
        st.song_edit([{"op": "module", "key": "tempo", "value": 140}])
        data = (self.dir / "song.yaml").read_bytes()
        self.assertTrue(data.startswith(b"\xef\xbb\xbfmodule:\n  title: T\n  tempo: 140\n"))
        self.assertEqual((st.facts["tempo"], st.facts["volume"][0]), (140, 32))

    def test_corrupt_meta_and_notes_files_are_moved_aside(self):
        # F7: the files are written whole or not at all; one that does not parse no longer blocks opening the song
        (self.dir / "song.tryout.json").write_text('{"slot": 1, "cand', encoding="utf-8")
        (self.dir / "song.notes.json").write_text("[{", encoding="utf-8")
        st = self.state()
        self.assertEqual(len(st.snapshot()["notices"]), 2)
        self.assertTrue((self.dir / "song.tryout.json.corrupt").exists() and (self.dir / "song.notes.json.corrupt").exists())
        st.add_note({"order": 0, "row": 0, "tag": "ok"})
        self.assertEqual(len(json.loads((self.dir / "song.notes.json").read_text(encoding="utf-8"))), 1)
        self.assertEqual([p.name for p in self.dir.glob("*.tmp")], [])  # no temporary file left behind

    def test_an_archive_reports_the_orders_its_notes_were_made_on(self):
        # F9: the archive's report names each order's pattern and time as the notes' version had them
        st = self.state()
        st.add_note({"order": 1, "row": 0, "tag": "second order"})
        old = st.version()["hash"]
        (self.dir / "song.yaml").write_bytes(SONG.replace("orders: [p1, p2]", "orders: [p2, p1]").encode("utf-8"))
        st.reload()
        md = (self.dir / f"song.notes-{old}.md").read_text(encoding="utf-8")
        self.assertIn("## ord 1 `p2` (0:00.5 to 0:01.0)", md)
        st.add_note({"order": 1, "row": 0, "tag": "now p1"})
        self.assertIn("## ord 1 `p1`", (self.dir / "song.notes.md").read_text(encoding="utf-8"))
        # T9: a second batch of notes on that version merges into its archive
        st.notes.append(dict(st.notes[0], id=7, when="x", version={"hash": old, "mtime": "x"}))
        st._archive_old_notes()
        self.assertEqual(len(json.loads((self.dir / f"song.notes-{old}.json").read_text(encoding="utf-8"))), 2)

    def test_a_brace_in_a_trailing_comment_is_not_the_entry(self):
        # F12: a fader written into a one-line channel entry whose comment holds a `}` lands in the entry
        (self.dir / "song.yaml").write_bytes(SONG_BLOCK.replace("    - {name: A}\n", "    - {name: A}  # pan: 40 }\n").encode("utf-8"))
        st = self.state()
        st.set_mix({"pan": {"0": 10}})
        st.apply_mix()
        self.assertIn("    - {name: A, pan: 10}  # pan: 40 }\n", (self.dir / "song.yaml").read_text(encoding="utf-8"))
        self.assertEqual(st.mix(), {})

    def test_a_one_line_module_is_re_dumped_and_keeps_its_values(self):
        # T8: the mixer's fallback when the lines cannot be found (a one-line module): the whole song re-dumped, which
        # compiles and keeps every value
        st = self.state()
        st.set_mix({"volume": {"1": 20}, "mix_volume": 90})
        text, redump = st.mix_text()
        self.assertTrue(redump)
        mod = gui.load_song_text(text, self.dir)[0]
        before = st.mod
        self.assertEqual(([c.volume for c in mod.channels], mod.mix_volume, mod.tempo, [p.name for p in mod.patterns],
                          [len(p.rows) for p in mod.patterns]),
                         ([64, 20], 90, before.tempo, [p.name for p in before.patterns], [len(p.rows) for p in before.patterns]))

    def test_http_routes_and_ranges(self):
        # S3 and T2: every GET route through the server, a Range the file cannot satisfy, and uploads and imports through
        # do_POST
        st = self.state()
        st.add_candidates("cand.wav")
        for _ in range(100):
            if all(r["status"] == "ready" for r in st.renders.values()) and st.renders:
                break
            time.sleep(0.05)
        port, stop = self.serve(st)
        try:
            key = st.key()
            code, h, body = self.fetch(port, f"/wav/{key}")
            size = len(body)
            self.assertEqual((code, body[:4]), (200, b"RIFF"))
            code, h, body = self.fetch(port, f"/wav/{key}", Range="bytes=0-999999999")
            self.assertEqual((code, len(body), h["Content-Range"]), (206, size, f"bytes 0-{size - 1}/{size}"))
            self.assertEqual(self.fetch(port, f"/wav/{key}", Range="bytes=-10")[2], (self.dir / ".tryout" / f"{key}.wav").read_bytes()[-10:])
            self.assertEqual(self.fetch(port, f"/wav/{key}", Range="bytes=abc-")[0], 400)
            code, h, _ = self.fetch(port, f"/wav/{key}", Range=f"bytes={size}-")
            self.assertEqual((code, h["Content-Range"]), (416, f"bytes */{size}"))
            self.assertEqual(self.fetch(port, "/raw/0")[2], (self.dir / "cand.wav").read_bytes())
            self.assertEqual(self.fetch(port, "/raw/5")[0], 404)
            self.assertEqual(self.fetch(port, f"/spec/{key}")[2][:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(json.loads(self.fetch(port, "/api/wave/1?a=0&b=100&n=20")[2])["frames"], 13230)
            self.assertEqual(json.loads(self.fetch(port, "/api/pattern/0")[2])["name"], "p1")
            self.assertEqual(self.fetch(port, "/api/pattern/9")[0], 404)
            self.assertEqual(len(json.loads(self.fetch(port, "/api/sounding/0")[2])["rows"]), 4)
            self.assertEqual(self.fetch(port, "/api/it")[2][:4], b"IMPM")
            code, _, body = self.fetch(port, "/api/upload?name=dropped%20one.wav", (self.dir / "b.wav").read_bytes())
            self.assertEqual((code, Path(json.loads(body)["path"]).name), (200, "dropped_one.wav"))
            self.assertEqual(self.fetch(port, "/api/upload?name=x.wav", b"not a wav")[0], 400)
            (self.dir / "m.it").write_bytes(api.compile_song(api.from_yaml(SONG), self.dir)[0])
            code, _, body = self.fetch(port, "/api/import", json.dumps({"path": str(self.dir / "m.it")}).encode())
            self.assertEqual((code, Path(json.loads(body)["path"]).name), (200, "m.yaml"))
            self.assertTrue(st.closed)  # S5: the song it replaced stopped its worker
        finally:
            stop()

    def test_opening_another_song_stops_the_old_worker(self):
        # S5: the old state's worker thread ends instead of rendering on into its cache
        import threading
        gui.Handler.state = None
        try:
            gui.Handler.open_song(self.dir / "song.yaml")
            old = gui.Handler.state
            self.states.append(old)
            n = threading.active_count()
            gui.Handler.open_song(self.dir / "song.yaml")
            self.states.append(gui.Handler.state)
            for _ in range(100):
                if not any(t.is_alive() and t is not threading.current_thread() and getattr(t, "_target", None) == old._worker
                           for t in threading.enumerate()):
                    break
                time.sleep(0.02)
            self.assertTrue(old.closed)
            self.assertLessEqual(threading.active_count(), n + 1)
        finally:
            gui.Handler.state = None

    def test_prune_keeps_the_newest_renders(self):
        # T9: the cache keeps the newest `keep` WAVs and forgets the renders it removed
        st = self.state()
        for _ in range(100):  # the song's own render first: it is the newest file
            if st.renders.get(st.key(), {}).get("status") == "ready":
                break
            time.sleep(0.05)
        for k in range(5):
            p = st.cache_dir / f"old{k}.wav"
            p.write_bytes(b"RIFF")
            st.renders[f"old{k}"] = {"status": "ready", "file": str(p), "error": None}
            import os
            os.utime(p, (k, k))
        st._prune(keep=3)
        self.assertEqual(sorted(p.stem for p in st.cache_dir.glob("old*.wav")), ["old3", "old4"])
        self.assertEqual(sorted(k for k in st.renders if k.startswith("old")), ["old3", "old4"])
        self.assertEqual(st.renders[st.key()]["status"], "ready")

    def test_report_ratings_and_a_new_song_with_a_sample(self):
        # T9: the report's ratings section; create_song with a first sample
        st = self.state()
        st.add_candidates("cand.wav")
        st.meta["ratings"][str((self.dir / "cand.wav").resolve())] = {"stars": 3, "note": "warm"}
        self.assertIn('## Tryout ratings\n\n- slot 1: cand *** "warm"', st.report())
        p = gui.create_song(self.dir / "new" / "made.yaml", 4, str(self.dir / "a.wav"))
        self.assertTrue(api.check(p)["ok"])
        self.assertIn("a.wav", p.read_text(encoding="utf-8"))

    def test_recipe_panel(self):
        # a slot whose WAV a recipe beside the song writes: its entry is shown, rendered again with an edit as a new
        # candidate (never over the recipe's WAV), and written back into the recipe in place
        try:
            import pedalboard  # noqa: F401
        except ImportError:
            self.skipTest("pedalboard not installed (the recipe renders need it)")
        from vulturetracker import synth
        recipe = self.dir / "kit.yaml"
        recipe.write_bytes(b"# the kit\nout_dir: .\nsamples:\n  tone: {file: a.wav, note: A-5, gain: -3}  # the lead\n  other: {file: b.wav}\n")
        synth.render_recipe(recipe, log=lambda s: None)
        (self.dir / "song.yaml").write_bytes(SONG.replace("1: {file: a.wav, name: A tone}", "1: {file: tone.wav, name: A tone}").encode("utf-8"))
        st = self.state()
        rec = st.snapshot()["recipe"]["slot"]
        self.assertEqual((rec["recipe_name"], rec["name"], rec["note"], rec["spec"]), ("kit.yaml", "tone", None, "file: a.wav\nnote: A-5\ngain: -3\n"))
        before = (self.dir / "tone.wav").read_bytes()
        with self.assertRaises(ValueError):
            st.request_recipe_render("[not, a, mapping]")
        st.request_recipe_render("file: a.wav\nnote: A-5\ngain: -9\n")
        for _ in range(200):
            if st.recipe_job["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(st.recipe_job["status"], "done", st.recipe_job["error"])
        new = self.dir / "tone-r1.wav"
        self.assertEqual((st.cands(), (self.dir / "tone.wav").read_bytes()), ([str(new.resolve())], before))
        import numpy as np
        peak = lambda f: np.abs(np.array(gui.read_wav(f).channels[0])).max()  # noqa: E731
        self.assertAlmostEqual(20 * math.log10(peak(new) / peak(self.dir / "tone.wav")), -6, delta=0.1)
        st.apply(str(new))  # the slot now plays the render: its entry is the one that made it
        self.assertEqual(st.slot_recipe()["spec"], "file: a.wav\nnote: A-5\ngain: -9\n")
        st.recipe_write("file: a.wav\nnote: A-5\ngain: -9\n")
        self.assertEqual(st.recipe_job["status"], "written")  # the panel says so until the next render
        self.assertEqual(recipe.read_text(encoding="utf-8"),
                         "# the kit\nout_dir: .\nsamples:\n  tone: {file: a.wav, note: A-5, gain: -9}  # the lead\n  other: {file: b.wav}\n")
        with self.assertRaises(ValueError):
            st.recipe_write("note: A-5\n")  # neither patch nor file
        # a patch whose synth is not installed: the job names it, the download runs, then the same render again
        def wait():
            for _ in range(200):
                if st.recipe_job["status"] in ("failed", "done"):
                    return st.recipe_job
                time.sleep(0.05)
        with mock.patch.object(synth, "DEFAULT_SURGE", self.dir / "nowhere"), \
                mock.patch.object(synth, "fetch_synth", side_effect=lambda kind, progress: progress(5, 10)) as fetch:
            st.request_recipe_render("patch: Pads/Anything\nnote: C-5\n")
            self.assertEqual((wait()["status"], wait()["need"]), ("failed", "surge"))
            st.request_fetch_synth("surge")
            job = wait()  # downloaded, then rendered again (and missed again: the stub installs nothing)
            self.assertEqual((fetch.call_args[0][0], job["status"], job["need"], job["got"]), ("surge", "failed", "surge", 5))
        with self.assertRaises(ValueError):
            st.request_fetch_synth("obxd")  # an installer, not a download

    def test_echo(self):
        # tracker delay: a channel's notes copied into another channel, later and quieter, as one undo step with the
        # channel it adds; song-wide effects and pan are not copied, a tick delay is SDx, copies past the pattern's end
        # are dropped and cells that are not empty are left alone
        song = SONG_BLOCK.replace("      00: C-5 01 ... ... | ... .. ... ...\n      01: ... .. ... ... | ... .. ... ...\n",
                                  "      00: C-5 01 ... A04 | ... .. ... ...\n      01: D-5 .. v40 H44 | ... .. ... ...\n", 1)
        song = song.replace("      03: ... .. ... ... | ... .. ... ...\n  p2:", "      03: E-5 .. p10 X20 | ... .. ... ...\n  p2:")
        (self.dir / "song.yaml").write_bytes(song.encode("utf-8"))
        st = self.state()
        read = lambda: (self.dir / "song.yaml").read_text(encoding="utf-8")  # noqa: E731
        r = st.song_edit([{"op": "echo", "ch": 0, "to": None, "pan": 12, "pattern": 0, "rows": 1, "level": 50}])
        self.assertEqual(r, {"report": "echo of channel 1 into new channel 3: 2 cells, 1 past a pattern's end dropped"})
        self.assertIn("    - {name: A echo, pan: 12}\n", read())
        self.assertEqual(st.facts["channels"], ["A", "B", "A echo"])
        rows = st.pattern_rows(0)["rows"]
        self.assertEqual([r[2] for r in rows], ["... .. ... ...", "C-5 01 v32 ...", "D-5 .. v20 H44", "... .. ... ..."])
        self.assertTrue(all(not line.endswith(" \n") for line in read().splitlines(keepends=True)))
        # into the existing echo channel two ticks late: the note there is left alone, the rest delayed with SD2; the
        # E-5's pan command (p10, X20) is not copied, its volume is the channel's last (v40)
        r = st.song_edit([{"op": "echo", "ch": 0, "to": 2, "pattern": 0, "rows": 0, "ticks": 2, "level": 25}])
        self.assertEqual(r["report"], "echo of channel 1 into channel 3: 2 cells, 1 skipped (the cell there was not empty), "
                                      "1 effects replaced by the tick delay")
        self.assertEqual([r[2] for r in st.pattern_rows(0)["rows"]], ["C-5 01 v16 SD2", "C-5 01 v32 ...", "D-5 .. v20 H44", "E-5 .. v10 SD2"])
        # the whole song: every pattern, the second echo named apart
        st.song_edit([{"op": "echo", "ch": 1, "to": None, "pattern": None, "rows": 1, "level": 100}])
        self.assertEqual(st.facts["channels"][3], "B echo")
        self.assertEqual([st.pattern_rows(0)["rows"][r][3] for r in range(4)], ["... .. ... ..."] * 3 + ["C-5 02 v64 ..."])
        self.assertEqual([st.pattern_rows(1)["rows"][r][3] for r in range(4)], ["... .. ... ..."] * 4)  # p2's B is empty
        for bad in ({"ch": 0, "to": 0}, {"ch": 0, "to": 2, "rows": 0, "ticks": 6}, {"ch": 0, "to": 3, "rows": 0},
                    {"ch": 1, "to": 3, "pattern": 1}):
            with self.assertRaises(ValueError, msg=bad):
                st.song_edit([{"op": "echo", "pattern": 0, "rows": 1, **bad}])
        while st.snapshot()["undo"]:
            st.undo()
        self.assertEqual(read(), song)

    def test_composition_ops(self):
        # groove, euclid, chord and layers (compose.py) written into the song text, each one undo step with a report
        (self.dir / "song.yaml").write_bytes(SONG_BLOCK.encode("utf-8"))
        st = self.state()
        read = lambda: (self.dir / "song.yaml").read_text(encoding="utf-8")  # noqa: E731
        col = lambda p, ch: [r[ch] for r in st.pattern_rows(p)["rows"]]  # noqa: E731
        r = st.song_edit([{"op": "euclid", "pattern": 0, "ch": 0, "r0": 0, "r1": 3, "hits": 3, "steps": 4}])
        self.assertEqual(r, {"report": "euclid: 2 cells in pattern 'p1'"})
        self.assertEqual(col(0, 0), ["C-5 01 ... ...", "... .. ... ...", "C-5 01 ... ...", "C-5 01 ... ..."])
        r = st.song_edit([{"op": "groove", "pattern": None, "ticks": [0, 2]}])  # the whole song, every channel
        self.assertEqual(r, {"report": "groove: 1 cell in the song"})
        self.assertEqual(col(0, 0)[3], "C-5 01 ... SD2")
        st.song_edit([{"op": "layers", "pattern": 0, "chans": [0], "r0": 0, "r1": 3, "instruments": [2, 1]}])
        self.assertEqual([c[:6] for c in col(0, 0)], ["C-5 02", "... ..", "C-5 01", "C-5 02"])
        with self.assertRaises(ValueError):  # a triad from channel 1 needs three channels; the song has two
            st.song_edit([{"op": "chord", "pattern": 0, "ch": 0, "shape": "maj"}])
        st.song_edit([{"op": "chord", "pattern": 0, "ch": 0, "r0": 0, "r1": 0, "shape": "5"}])  # a power chord fits
        self.assertEqual(st.pattern_rows(0)["rows"][0][:2], ["C-5 02 ... ...", "G-5 02 ... ..."])
        for bad in ({"op": "groove", "pattern": 0, "ticks": [6]}, {"op": "euclid", "pattern": None, "ch": 0, "hits": 1,
                    "steps": 2}, {"op": "layers", "pattern": 1, "chans": [5], "instruments": [1]}):
            with self.assertRaises(ValueError, msg=bad):
                st.song_edit([bad])
        while st.snapshot()["undo"]:
            st.undo()
        self.assertEqual(read(), SONG_BLOCK)

    def test_the_page_keeps_its_address(self):
        import socket
        with socket.socket() as s:  # a free port stands in for PORT
            s.bind(("127.0.0.1", 0))
            free = s.getsockname()[1]
        old, gui.PORT = gui.PORT, free
        try:
            a = gui.make_server()
            self.assertEqual(a.server_address[1], free)
            b = gui.make_server()  # taken: a second app window gets another port, never the same one
            self.assertNotEqual(b.server_address[1], free)
            for srv in (a, b):
                srv.server_close()
        finally:
            gui.PORT = old

    def test_conveniences(self):
        h = gui.effect_help()  # the song format's tables
        self.assertEqual((h["v"]["v"], h["e"]["O"][:13], h["s"]["S73"][:16]), ("set note volume (00–64)", "sample offset", "set this note's "))
        self.assertEqual(len(h["e"]), 26)
        song = SONG_INS.replace("patterns:\n", "patterns:\n  spare:\n    rows: 2\n    data: |\n      00: C-5 03 ... ... | ... .. ... ...\n")
        song = song.replace("  2: {file: b.wav, name: B tone}\n", "  2: {file: b.wav, name: B tone}\n  3: {file: cand.wav, name: C}\n")
        song = song.replace("patterns:\n  spare", "  3: {name: C, sample: 3}\npatterns:\n  spare")
        (self.dir / "song.yaml").write_bytes(song.encode("utf-8"))
        st = self.state()
        self.assertEqual(st.facts["highlight"], [4, 16])
        self.assertEqual(st.unused(), {"patterns": ["spare"], "instruments": [3], "samples": [3]})
        with self.assertRaises(gui.SongError):  # the unused pattern still names instrument 3
            st.song_edit([{"op": "instrument_delete", "num": 3}])
        st.song_edit([{"op": "pattern_delete", "name": "spare"}, {"op": "instrument_delete", "num": 3}, {"op": "sample_delete", "num": 3}])
        self.assertEqual((st.unused(), len(st.history)), ({"patterns": [], "instruments": [], "samples": []}, 1))
        self.assertNotIn("cand.wav", st.text)
        # a dropped WAV: saved beside the song, an identical copy reused, another numbered, anything else refused
        (self.dir / "src").mkdir()
        write_wav(self.dir / "src" / "short.wav", RATE, [sine(660, 0.1)], root_note=64)
        data = (self.dir / "src" / "short.wav").read_bytes()
        p = st.save_upload("My Drop.wav", data)
        self.assertEqual((p.name, st.save_upload("My Drop.wav", data)), ("My_Drop.wav", p))
        self.assertEqual(st.save_upload("My Drop.wav", (self.dir / "b.wav").read_bytes()).name, "My_Drop-2.wav")
        with self.assertRaises(ValueError):
            st.save_upload("x.wav", b"not a wav")
        self.assertFalse((self.dir / "x.wav").exists())
        # dropped on a slot: the slot plays it (the tryout's swap rules), a loop past its end goes
        e = dict(st.song["samples"][1], loop={"start": 0, "end": 13000})
        st.song_edit([{"op": "sample_set", "num": 1, "entry": e}])
        st.song_edit([{"op": "sample_file", "num": 1, "file": str(p)}])
        self.assertEqual(st.song["samples"][1], {"file": "My_Drop.wav", "name": "My_Drop", "base_note": "E-5"})


if __name__ == "__main__":
    unittest.main()
