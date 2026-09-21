"""Reader tests: .it -> song YAML -> .it must render bit-identically in libopenmpt.

The optional fixture test runs over third-party IT files placed in tests/fixtures/ (not committed).
Fetch OpenMPT's IT playback test modules (as mirrored by libxmp) with:
    python tests/fetch_fixtures.py
"""
import tempfile
import unittest
from pathlib import Path

from vulturetracker import api
from vulturetracker.itreader import import_it
from vulturetracker.openmpt import LoadedModule

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
# Files whose libopenmpt render is random (random waveforms), or that use features the song format
# does not carry (embedded MIDI macros, OpenMPT-only extensions). The importer warns about the latter.
EXPECTED_DIFFERENT = {
    "RandomWaveform.it", "tremolo.it", "vibrato.it", "vibrato-oldfx.it", "gxsmp.it", "gxsmp2.it",
    "GlobalVolume-Macro.it", "MacroExtendedParam.it", "MultiZxx.it", "Volume-Macro-Letters.it",
    "extreme-filter-test-2.it", "macro-lastnote.it",
    "InstrumentNumberChange.it", "PortaInsNumCompat.it", "PortaSampleCompat.it", "RandomPan.it",
    "swing1.it", "swing3.it", "swing4.it", "swing5.it",
}


def render(data):
    with LoadedModule(data) as m:
        return m.render(max_seconds=120)


def roundtrip(it_bytes, tmp: Path, stem="song"):
    src = tmp / f"{stem}.it"
    src.write_bytes(it_bytes)
    song, warnings = import_it(src, tmp / f"{stem}.yaml", tmp / f"{stem}_samples")
    data, _, _ = api.compile_song(tmp / f"{stem}.yaml")
    return data, song, warnings


class TestImport(unittest.TestCase):
    def test_demo_roundtrip_is_identical(self):
        original, _, _ = api.compile_song(ROOT / "demo" / "arena.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            data, song, warnings = roundtrip(original, Path(tmp))
            self.assertEqual(warnings, [])
            self.assertEqual(len(song["instruments"]), 4)
            drum = song["instruments"][1]
            self.assertEqual([e["notes"] for e in drum["keymap"]], ["C-5", "D-5", "F#5", "A#5"])
            self.assertEqual(render(data), render(original))

    def test_keymap_ranges_compress(self):
        from vulturetracker.itreader import _keymap_entries
        from vulturetracker.model import Instrument
        ins = Instrument()
        ins.keymap = [(n, 1) for n in range(60)] + [(60, 2)] * 12 + [(n + 12, 3) for n in range(72, 120) if n + 12 < 120] \
            + [(119, 3)] * 12
        entries = _keymap_entries(ins, lambda s: True)
        self.assertEqual(entries[0], {"notes": "C-0..B-4", "sample": 1})
        self.assertEqual(entries[1], {"notes": "C-5..B-5", "sample": 2, "play_note": "C-5"})
        self.assertEqual(entries[2], {"notes": "C-6..B-8", "sample": 3, "transpose": 12})
        self.assertEqual(entries[3], {"notes": "C-9..B-9", "sample": 3, "play_note": "B-9"})

    @unittest.skipUnless(FIXTURES.is_dir(), "no tests/fixtures (run tests/fetch_fixtures.py)")
    def test_fixture_modules_roundtrip(self):
        files = sorted(FIXTURES.glob("*.it"))
        failures = []
        with tempfile.TemporaryDirectory() as tmp:
            for f in files:
                if f.name in EXPECTED_DIFFERENT:
                    continue
                try:
                    data, _, _ = roundtrip(f.read_bytes(), Path(tmp), f.stem)
                    if render(data) != render(f.read_bytes()):
                        failures.append(f"{f.name}: render differs")
                except Exception as e:  # report every file, not just the first
                    failures.append(f"{f.name}: {type(e).__name__}: {e}")
        self.assertEqual(failures, [])
        self.assertGreater(len(files), 50)


if __name__ == "__main__":
    unittest.main()
