"""Recording (vulturetracker/record.py) on the simulated two-input interface, the take analysis in dsp.py (pitch,
edges, loop points), and takes saved into a song (State.save_take) and through the RECORD tab's routes. No audio
hardware is needed: the simulated device's blocks are fed by hand."""
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from vulturetracker import dsp, gui, record
from vulturetracker.wavload import read_wav, write_wav

from tests.test_gui import RATE, SONG, sine


def fake_recorder():
    be = record.FakeBackend()
    be.realtime = False  # the test feeds the blocks
    return record.Recorder(be)


class TestTakeAnalysis(unittest.TestCase):
    def test_yin_pitch(self):
        t = np.arange(int(0.1 * RATE)) / RATE
        for hz in (55, 110, 196, 440, 987.77):
            x = np.sin(2 * np.pi * hz * t) + 0.3 * np.sin(2 * np.pi * 2 * hz * t)
            got, conf = dsp.yin(x, RATE)
            self.assertAlmostEqual(got, hz, delta=hz * 0.002)
            self.assertGreater(conf, 0.9)
        self.assertEqual(dsp.yin(np.random.default_rng(1).normal(size=4410), RATE), (None, 0.0))
        self.assertEqual(dsp.note_of(440)[0], 69)                     # A-5 in the song format's numbering
        self.assertAlmostEqual(dsp.note_of(440 * 2 ** (20 / 1200))[1], 20, places=6)

    def test_edges_pitch_and_loop_of_a_take(self):
        t = np.arange(2 * RATE) / RATE
        tone = np.sin(2 * np.pi * 196 * t) * np.minimum(1, t * 20) * np.exp(-t * 0.3) * 0.6
        take = np.concatenate([np.zeros(RATE // 2), tone, np.zeros(RATE // 2)])[None]
        a, b = dsp.trim_edges(take, RATE)
        self.assertAlmostEqual(a / RATE, 0.49, delta=0.001)
        self.assertAlmostEqual(b / RATE, 2.55, delta=0.001)
        self.assertAlmostEqual(dsp.pitch_of(take, RATE), 196, delta=0.2)
        s, e = dsp.find_loop(take, RATE)
        self.assertGreater((e - s) / RATE, 0.2)
        self.assertAlmostEqual((e - s) * 196 / RATE, round((e - s) * 196 / RATE), delta=0.05)  # whole periods
        self.assertTrue(take[0, s - 1] < 0 <= take[0, s] and take[0, e - 1] < 0 <= take[0, e])  # rising crossings
        self.assertIsNone(dsp.find_loop(np.zeros((1, RATE)), RATE))


class TestRecorder(unittest.TestCase):
    def test_takes_from_the_simulated_interface(self):
        r = fake_recorder()
        self.assertEqual(r.devices()[0]["inputs"], 2)
        with self.assertRaises(record.RecordError):
            r.start()                                   # nothing open
        r.open(0, "1", RATE)
        r.stream.feed(0.5)                              # the input runs: meters, tuner and the pre-roll fill
        st = r.status()
        self.assertTrue(st["open"])
        self.assertGreater(st["peak"][0], -20)          # the pluck on input 1, decaying (-15 dBFS 0.5 s in)
        self.assertLess(st["peak"][1], -35)             # the hum on input 2, at -40 dBFS
        self.assertEqual(st["tuner"]["note"], 55)       # G-4, 196 Hz
        r.start(preroll=0.2)
        r.stream.feed(1.0)
        x = r.stop()
        self.assertEqual(x.shape[0], 1)
        self.assertAlmostEqual(x.shape[1] / RATE, 1.2, delta=0.02)  # the second recorded and 0.2 s from before REC
        self.assertIsNone(r.stop())                     # no take running
        r.set_mode("stereo")
        r.start()
        r.stream.feed(0.3)
        x = r.stop()
        self.assertEqual(x.shape[0], 2)
        self.assertGreater(np.abs(x[0]).max(), 10 * np.abs(x[1]).max())
        with self.assertRaises(record.RecordError):
            r.open(5, "1", RATE)                        # no such device
        r.close()
        self.assertFalse(r.status()["open"])


class TestTakesInTheSong(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_wav(self.dir / "a.wav", RATE, [sine(440)], root_note=69)
        write_wav(self.dir / "b.wav", RATE, [sine(880)])
        (self.dir / "song.yaml").write_bytes(SONG.encode("utf-8"))
        self.st = gui.State(self.dir / "song.yaml")

    def tearDown(self):
        self.st.close()
        gui.Handler.state = None
        gui.Handler.recorder = None
        gui.Handler.rec_devices = None
        os.environ.pop("VT_FAKE_AUDIO", None)
        self.tmp.cleanup()

    def take(self, cents=0.0, seconds=1.0):
        t = np.arange(int(seconds * RATE)) / RATE
        hz = 196 * 2 ** (cents / 1200)
        return np.concatenate([np.zeros(RATE // 4), 0.5 * np.sin(2 * np.pi * hz * t) * np.exp(-t), np.zeros(RATE // 4)])[None]

    def test_save_take_as_candidate_and_as_a_tuned_slot(self):
        st = self.st
        t = st.save_take(self.take(), RATE, {"name": "guitar", "dest": "candidate"})
        self.assertEqual((t["file"], t["note"], t["slot"]), ("guitar-01.wav", "G-4", 1))
        self.assertAlmostEqual(t["seconds"], 1.06, delta=0.01)  # the silent edges trimmed (10 ms before, 50 ms after)
        self.assertIn(t["path"], st.cands())
        self.assertEqual(read_wav(t["path"]).root, 55)
        t = st.save_take(self.take(cents=30), RATE, {"name": "guitar", "dest": "slot"})
        self.assertEqual((t["file"], t["cents"], t["slot"]), ("guitar-02.wav", 30, 3))
        entry = st.song["samples"][3]
        self.assertEqual(entry["file"], "takes/guitar-02.wav")
        # G-4 plays true: the recording 30 cents sharp is slowed by 30 cents
        self.assertAlmostEqual(entry["c5_speed"], RATE * 2 ** ((60 - 55) / 12) * 2 ** (-30 / 1200), delta=2)
        with self.assertRaises(ValueError):
            st.save_take(np.zeros((1, RATE)), RATE, {})
        self.assertEqual([x["file"] for x in st.takes], ["guitar-02.wav", "guitar-01.wav"])

    def test_record_routes(self):
        os.environ["VT_FAKE_AUDIO"] = "1"
        gui.Handler.state = self.st
        H = gui.Handler
        snap = H.rec_snapshot(devices=True)
        self.assertTrue(snap["available"] and snap["fake"])
        self.assertEqual(snap["devices"][0]["name"], "Simulated 2-input interface")
        self.assertEqual(H.rec_command({"cmd": "open", "device": 0, "mode": "1"}), {})
        H.recorder.stream.stop()                   # the simulated stream runs in real time: stop it, feed by hand
        H.recorder.stream.feed(0.2)
        self.assertEqual(H.rec_command({"cmd": "start"}), {})
        H.recorder.stream.feed(1.5)
        r = H.rec_command({"cmd": "stop", "name": "pluck", "dest": "keep"})
        self.assertEqual((r["take"]["file"], r["take"]["note"]), ("pluck-01.wav", "G-4"))
        self.assertTrue((self.dir / "takes" / "pluck-01.wav").exists())
        self.assertEqual(H.rec_snapshot()["takes"][0]["file"], "pluck-01.wav")
        self.assertIn("error", H.rec_command({"cmd": "bogus"}))
        H.rec_command({"cmd": "close"})
        saved = gui.REC_SETTINGS
        gui.REC_SETTINGS = self.dir / "record.json"  # never the user's own settings
        try:
            os.environ.pop("SD_ENABLE_ASIO", None)
            self.assertIn("restart the app", H.rec_command({"cmd": "asio", "on": True})["error"])
            self.assertTrue(H.rec_snapshot()["asio_saved"])
            self.assertEqual(H.rec_command({"cmd": "asio", "on": False}), {})
        finally:
            gui.REC_SETTINGS = saved


if __name__ == "__main__":
    unittest.main()
