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


EXPORT_SONG = """module: {title: Out, tempo: 125, speed: 6, rows_per_beat: 4, rows_per_bar: 12, channels: [{name: A}, {name: B, pan: 16}]}
samples:
  1: {file: a.wav, name: A}
  2: {file: a.wav, name: B, volume: 48}
instruments:
  1: {name: Lead, keymap: [{notes: C-0..B-8, sample: 1, transpose: 12}]}
  2: {name: Bass, sample: 2}
patterns:
  p:
    rows: 8
    data: |
      00: C-5 01 v32 ... | E-5 02 ... ...
      01: ... .. ... ... | ... .. ... D01
      02: === .. ... ... | G-5 .. ... SD3
      03: D-5 01 ... T96 | ... .. ... ...
      04: ... .. ... ... | A-5 .. ... G04
orders: [p]
"""


@unittest.skipIf(mido is None, "needs mido")
class TestMidiExport(unittest.TestCase):
    def test_song_to_midi_as_openmpt_exports_it(self):
        from vulturetracker.export import to_midi
        from vulturetracker.wavload import write_wav
        d = Path(_tmpdir(self))
        write_wav(d / "a.wav", 22050, [[(i % 50 - 25) * 800 for i in range(22050)]])
        it = api.compile_song(api.from_yaml(EXPORT_SONG), d)[0]
        data, warnings = to_midi(it)
        f = mido.MidiFile(file=__import__("io").BytesIO(data))
        self.assertEqual((f.type, f.ticks_per_beat, [t.name for t in f.tracks]), (1, 480, ["Out", "Lead", "Bass"]))
        events = []
        for t in f.tracks:
            now = 0
            for m in t:
                now += m.time
                events.append((t.name, now, m))
        tempos = [(n, round(m.tempo)) for _, n, m in events if m.type == "set_tempo"]
        self.assertEqual(tempos, [(0, 480000), (360, 400000)])  # T96 = 150 BPM on row 3 (120 ticks a row at 125)
        self.assertEqual([(m.numerator, m.denominator) for _, _, m in events if m.type == "time_signature"], [(3, 4)])
        notes = [(name, n, m.type, m.channel, m.note, m.velocity) for name, n, m in events if m.type in ("note_on", "note_off")]
        lead = [x[1:] for x in notes if x[0] == "Lead"]  # the keymap's note (+12); v32 doubled, else the sample's 64
        self.assertEqual(lead[:3], [(0, "note_on", 0, 72, 64), (240, "note_off", 0, 72, 0), (360, "note_on", 0, 74, 127)])
        self.assertEqual(lead[3][1:3], ("note_off", 0))  # at the song's end
        bass = [x[1:] for x in notes if x[0] == "Bass"]
        self.assertEqual(bass[:3], [(0, "note_on", 1, 64, 96), (300, "note_off", 1, 64, 0), (300, "note_on", 1, 67, 96)])  # SD3: 3 ticks of 20
        self.assertEqual(len(bass), 4, bass)  # G04's A-5 slides the note: no new one
        self.assertIn(("control_change", 1, 10, 32), [(m.type, m.channel, m.control, m.value) for _, _, m in events if m.type == "control_change"])
        self.assertEqual(warnings, ["MIDI: left out 1 Dxx, 1 Gxx (effects a MIDI file does not hold)"])
