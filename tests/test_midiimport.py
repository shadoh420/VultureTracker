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


def _tmpdir(self):  # TestCase.enterContext is 3.11+; the floor is 3.10
    d = tempfile.TemporaryDirectory()
    self.addCleanup(d.cleanup)
    return d.name


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
            self.assertEqual((out.name, warnings), ("t.yaml", []))
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
            # the bend (500 of 8192 at 2 semitones: 8/64 semitone) as an extra-fine slide where it is, then again under the
            # next note, which starts unbent (OpenMPT's MIDI import)
            self.assertEqual((cell["b1", 4, 0], cell["b1", 4, 1], cell["b1", 5, 0]), ("G-5 01 v50 FE8", "=== .. ... ...", "A-5 01 v50 FE8"))
            self.assertEqual(cell["b2", 0, 0], "=== .. ... ...")  # the last eighth ends on the next bar line
            res = api.check(out)
            self.assertEqual((res["errors"], res["warnings"]), ([], []))

    # ---- the 0.9.0 audit (scratch/audit-100, agentC)

    def imported(self, *tracks, type=1):
        """The tracks ((absolute tick, message) lists, no names) saved as a MIDI file and imported: (song, warnings)."""
        mid = mido.MidiFile(type=type, ticks_per_beat=480)
        for t in tracks:
            mid.tracks.append(track("", *t) if t and not isinstance(t, mido.MidiTrack) else t)
        d = Path(_tmpdir(self))
        mid.save(d / "t.mid")
        out, warnings = gui.import_beside(d / "t.mid")
        self.assertEqual(api.check(out)["errors"], [])
        return api.load(out), warnings

    def test_a_played_in_file_under_90_bpm_keeps_its_delays_to_one_digit(self):
        # 87.5 BPM misses a whole tempo at speed 6: speed 17 was picked, and SD10 does not exist. OpenMPT's MIDI import
        # keeps 2-16 ticks a row for the same reason (Load_mid.cpp, ticksPerRow)
        evs = [(0, mido.MetaMessage("set_tempo", tempo=685714))]
        for i in range(32):
            evs += note(0, 60 + i % 12, i * 240 + (i * 53) % 119 + 1, 200)
        song, warnings = self.imported(evs, type=0)
        self.assertLessEqual(song["module"]["speed"], 16)
        delays = {fx for p in song["patterns"].values() for fx in p["data"].split() if fx.startswith("SD")}
        self.assertTrue(delays and all(len(fx) == 3 for fx in delays), delays)

    def test_the_last_tempo_and_time_signature_on_a_tick_count(self):
        # 130 then 120 BPM and 4/4 then 3/4, all at tick 0: the file plays 120 BPM in 3/4 (OpenMPT's MIDI import also
        # takes the last tempo at tick 0)
        evs = [(0, mido.MetaMessage("set_tempo", tempo=461538)), (0, mido.MetaMessage("set_tempo", tempo=500000)),
               (0, mido.MetaMessage("time_signature", numerator=4, denominator=4)),
               (0, mido.MetaMessage("time_signature", numerator=3, denominator=4))] + note(0, 60, 0, 240) + note(0, 64, 1440, 240)
        song, _ = self.imported(evs, type=0)
        m = song["module"]
        self.assertEqual(m["tempo"] * 24 / (m["speed"] * m["rows_per_beat"]), 120)
        self.assertEqual(m["rows_per_bar"], 3 * m["rows_per_beat"])
        self.assertEqual([song["patterns"][o]["rows"] for o in song["orders"]], [m["rows_per_bar"]] * 2)

    def test_tempo_changes_on_one_row_keep_the_last(self):
        # 100 BPM at tick 960 and 140 BPM at tick 1000 both land on row 4: the second is what plays on (OpenMPT writes
        # each change into the row, the last one staying)
        evs = [(0, mido.MetaMessage("set_tempo", tempo=500000)), (960, mido.MetaMessage("set_tempo", tempo=600000)),
               (1000, mido.MetaMessage("set_tempo", tempo=428571))]
        for i in range(16):
            evs += note(0, 60 + i % 5, i * 240, 200)
        song, _ = self.imported(evs, type=0)
        self.assertEqual(song["module"]["speed"], 12)
        tempo_cells = [c.split()[-1] for p in song["patterns"].values() for row in p["data"].splitlines()
                       for c in row.split(" | ")[-1:] if c.split()[-1].startswith("T")]
        self.assertEqual(tempo_cells, ["T8C"])

    def test_track_names_in_utf8_latin_1_or_with_a_nul(self):
        # mido reads names as latin-1; files today write UTF-8 ("Böse" came out "BA?se"); a NUL ends a name, as in
        # OpenMPT's reader; other control characters go (it_text)
        def named(raw, ch, key):
            return mido.MidiTrack([mido.MetaMessage("track_name", name=raw)] + [m for _, m in sorted(note(ch, key, 0, 480), key=lambda e: e[0])])
        utf8 = "Café Song".encode("utf-8").decode("latin-1")
        song, warnings = self.imported(mido.MidiTrack([mido.MetaMessage("track_name", name=utf8)]),
                                       named("Böse Bass".encode("utf-8").decode("latin-1"), 0, 40),
                                       named("Grüße", 1, 60), named("Lead\tSynth", 3, 67), named("Piano\x00junk", 2, 64))
        self.assertEqual(song["module"]["title"], "Cafe Song")
        self.assertEqual([c["name"] for c in song["module"]["channels"]], ["Bose Bass 1.1", "Grusse 2.1", "LeadSynth 4.1", "Piano 3.1"])

    def test_type_2_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            mid = mido.MidiFile(type=2)
            mid.tracks.append(track("x", *note(0, 60, 0, 480)))
            mid.save(Path(d) / "t.mid")
            with self.assertRaisesRegex(ValueError, "type 2"):
                gui.import_beside(Path(d) / "t.mid")


if __name__ == "__main__":
    unittest.main()
