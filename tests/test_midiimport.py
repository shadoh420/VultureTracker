"""MIDI import: a small type 1 file made with mido (no fixture), imported, checked cell by cell and compiled."""
import tempfile
import unittest
from pathlib import Path

try:
    import mido
except ImportError:
    mido = None

from vulturetracker import api, gui


def track(name, *events):
    """A mido track from (absolute tick, message) pairs."""
    t = mido.MidiTrack([mido.MetaMessage("track_name", name=name)])
    now = 0
    for tick, msg in sorted(events, key=lambda e: e[0]):
        t.append(msg.copy(time=tick - now))
        now = tick
    return t


def note(ch, key, start, length, vel=100):
    return [(start, mido.Message("note_on", channel=ch, note=key, velocity=vel)),
            (start + length, mido.Message("note_off", channel=ch, note=key))]


@unittest.skipIf(mido is None, "needs mido")
class TestMidiImport(unittest.TestCase):
    def test_a_midi_file_becomes_a_song(self):
        mid = mido.MidiFile(type=1, ticks_per_beat=480)
        mid.tracks.append(track("Song", (0, mido.MetaMessage("set_tempo", tempo=600000)),  # 100 BPM
                                (0, mido.MetaMessage("time_signature", numerator=3, denominator=4))))
        mid.tracks.append(track("Keys", (0, mido.Message("control_change", channel=0, control=7, value=100)),
                                (0, mido.Message("control_change", channel=0, control=10, value=127)),
                                *note(0, 60, 0, 960), *note(0, 64, 0, 960),                # a chord: two channels
                                *note(0, 67, 960, 240), *note(0, 69, 1200, 240),           # eighths on the first
                                (1000, mido.Message("pitchwheel", channel=0, pitch=500))))
        mid.tracks.append(track("Drums", *note(9, 36, 0, 60), *note(9, 38, 480, 60),
                                *note(9, 36, 1440, 60), *note(9, 36, 2880, 60), *note(9, 36, 4320, 60)))
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            mid.save(d / "t.mid")
            out, warnings = gui.import_beside(d / "t.mid")
            self.assertEqual((out.name, warnings), ("t.yaml", ["1 pitch bends left out"]))
            song = api.load(out)
            m = song["module"]
            self.assertEqual((m["title"], m["speed"], m["tempo"], m["rows_per_beat"], m["rows_per_bar"]), ("Song", 12, 100, 2, 6))
            self.assertEqual([c["name"] for c in m["channels"]], ["Keys 1.1", "Keys 1.2", "Drums kick", "Drums snare"])
            self.assertEqual((m["channels"][0]["volume"], m["channels"][0]["pan"]), (50, 64))
            self.assertEqual(song["orders"], ["b1", "b2", "b3", "b3"])  # the last two bars are the same
            cell = {(p, i, c): " ".join(row.split(": ", 1)[1].split(" | ")[c].split())
                    for p, pat in song["patterns"].items() for i, row in enumerate(pat["data"].splitlines()) for c in range(4)}
            self.assertEqual([cell["b1", 0, c] for c in range(4)], ["C-5 01 v50 ...", "E-5 01 v50 ...", "C-3 02 v50 ...", "... .. ... ..."])
            self.assertEqual(cell["b1", 2, 3], "D-3 02 v50 ...")
            self.assertEqual((cell["b1", 4, 0], cell["b1", 4, 1], cell["b1", 5, 0]), ("G-5 01 v50 ...", "=== .. ... ...", "A-5 01 v50 ..."))
            self.assertEqual(cell["b2", 0, 0], "=== .. ... ...")  # the last eighth ends on the next bar line
            res = api.check(out)
            self.assertEqual((res["errors"], res["warnings"]), ([], []))

    def test_type_2_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            mid = mido.MidiFile(type=2)
            mid.tracks.append(track("x", *note(0, 60, 0, 480)))
            mid.save(Path(d) / "t.mid")
            with self.assertRaisesRegex(ValueError, "type 2"):
                gui.import_beside(Path(d) / "t.mid")


if __name__ == "__main__":
    unittest.main()
