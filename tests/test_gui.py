"""GUI state tests: measurement, the order/channel usage map, and the in-place YAML apply. No HTTP, no browser."""
import json
import math
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


class TestGui(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_wav(self.dir / "a.wav", RATE, [sine(440)], root_note=69)
        write_wav(self.dir / "b.wav", RATE, [sine(880)])
        write_wav(self.dir / "cand.wav", RATE, [sine(660)], root_note=64)
        (self.dir / "song.yaml").write_text(SONG, encoding="utf-8")

    def tearDown(self):
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
        st = gui.State(self.dir / "song.yaml")
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
        self.assertEqual(meta["candidates"]["1"], [str((self.dir / "cand.wav").resolve())])

    def test_pattern_rows_and_mutes(self):
        from vulturetracker import api
        st = gui.State(self.dir / "song.yaml")
        self.assertEqual(st.pattern_rows(1)["rows"][0], ["C-5 02 ... ...", "... .. ... ..."])
        self.assertEqual(st.facts["orders"][1]["index"], 1)
        self.assertEqual(st.facts["pan"], [32, 32])
        cand = str(self.dir / "cand.wav")
        k = st.key(cand)
        st.meta["solo"] = 1
        self.assertEqual(st.silenced(), [0])
        self.assertNotEqual(st.key(cand), k)  # mutes are part of the render cache key
        # the IT channel-disable bit silences a channel in libopenmpt's render
        base = gui.mute_channels(api.tryout_song(self.dir / "song.yaml"), [0, 1])
        self.assertEqual(set(api.tryout_render(base, 1, cand, self.dir, RATE)), {0})
        base = gui.mute_channels(api.tryout_song(self.dir / "song.yaml"), [1])
        self.assertNotEqual(set(api.tryout_render(base, 1, cand, self.dir, RATE)), {0})

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
        st = gui.State(self.dir / "song.yaml")
        cand = str(self.dir / "cand.wav")
        k = st.key(cand)
        write_wav(self.dir / "b.wav", RATE, [sine(770, seconds=0.2)])  # another slot's WAV re-rendered in place
        self.assertNotEqual(st.key(cand), k)

    def test_patch_keeps_block_mapping_and_comments(self):
        text = SONG.replace("  2: {file: b.wav, name: B tone}\n",
                            "  2:\n    file: b.wav  # the B tone\n    name: B tone\n  # slot 3 would come next\n")
        (self.dir / "song.yaml").write_text(text, encoding="utf-8")
        st = gui.State(self.dir / "song.yaml")
        st.meta["slot"] = 2
        new, redump = st.patched_text(str(self.dir / "cand.wav"))
        self.assertFalse(redump)
        self.assertIn("# a comment that must survive the apply", new)
        self.assertIn("  1: {file: a.wav, name: A tone}\n  2:\n    file: cand.wav\n    name: cand\n    base_note: E-5\n"
                      "  # slot 3 would come next\npatterns:", new)

    def test_stems_export(self):
        st = gui.State(self.dir / "song.yaml")
        st.request_stems()
        for _ in range(200):
            if st.stems["status"] in ("done", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(st.stems["status"], "done", st.stems)
        self.assertEqual(sorted(p.name for p in (self.dir / "song_stems").glob("*.wav")), ["01-A.wav", "02-B.wav"])
        self.assertGreater((self.dir / "song_stems" / "02-B.wav").stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
