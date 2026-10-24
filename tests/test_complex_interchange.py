"""Original difficult-score fixtures for exact grace and sparse-voice interchange."""
import copy
import tempfile
import unittest
from pathlib import Path

from vulturetracker import gpimport, gui, tef, tgimport
from tests.test_gpexport_legacy import source, export, plan
from tests import test_gpx
from tests.test_band_imports import tef3_fixture, u32


def grace_song(*, value=32, transition='hammer', on_beat=False, dead=False, fret=3, velocity=79):
    song = source(3)
    song['score']['metadata']['comments'] = song['module']['message']
    for pattern in song['score']['patterns'].values():
        for beat in pattern['beats']:
            for note in beat['notes']:
                for field in set(note) - {'id', 'pitch', 'string', 'fret', 'velocity'}:
                    note.pop(field)
    note = song['score']['patterns']['m1']['beats'][2]['notes'][0]
    note['grace'] = dict(fret=fret, value=value, velocity=velocity, transition=transition,
                         on_beat=on_beat, dead=dead)
    return song


def routes(song):
    return {tid: dict(program=t['midi']['program'], bank=t['midi'].get('bank', 0))
            for tid, t in song['score']['tracks'].items()}


def sounding(song):
    """Event identity changes on format import; musical timing and expression must not."""
    events = plan(song)
    return sorted((e['type'], e['track'], e['ch'], e.get('pitch', -1), e.get('velocity', -1), e['frame'],
                   e.get('bend_value', -1), e.get('expression', -1), tuple(e.get('gains', [])))
                  for e in events)


def tef_grace_fixture(*, bars=4, duration=3, extra_fret=0, compound=False, orphan=False, pan=8):
    data = bytearray(tef3_fixture(bars=bars, techniques=False, pan=pan))
    data[data.index(b'Bass') - 17] = 2  # authored bass clef, compatible with GP's inferred clef
    data = bytes(data)
    # Second quarter on first guitar string2; metadata may follow another
    # string's component and must still attach to the correct note.
    location = u32(4 * 320 + 8)
    index = data.index(location, 256)
    note = bytearray(data[index:index + 12])
    note[4] |= 64
    note[7] = 3 | (1 << 5)  # grace fret3, hammer transition
    metadata = location + bytes([0x7d, duration, 0, 0, extra_fret, int(compound), 0, 0])
    return data[:index] + (b'' if orphan else bytes(note)) + metadata + data[index + 12:]


class TestComplexInterchange(unittest.TestCase):
    def test_tef3_grace_metadata_import_and_tg_gp_roundtrip(self):
        for code, duration, fret in ((1, 32, 3), (2, 32, 3), (3, 16, 3), (3, 16, 33)):
            with self.subTest(code=code, fret=fret):
                # TEF pan8 maps to MIDI67/native34, outside GP's exact mixer grid.
                # Keep this grace roundtrip on a pan value both formats represent.
                song, _ = tef.read_tef(tef_grace_fixture(duration=code, extra_fret=fret if fret > 31 else 0, pan=0))
                graces = [n['grace'] for p in song['score']['patterns'].values() for b in p['beats']
                          for n in b['notes'] if n.get('grace')]
                self.assertEqual(graces, [dict(value=duration, fret=fret, velocity=95,
                                               transition='hammer', on_beat=False, dead=False)])
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels=routes(song))
                self.assertEqual(sounding(tgimport.read_tg(data)[0]), sounding(song))
                data, _ = export(song, 5)
                restored = gpimport._native_gp_song(gpimport._read_native_gp(data), 'TEF grace')
                self.assertEqual(sounding(restored), sounding(song))

    def test_tef3_grace_with_inexact_gp_pan_refuses_without_source_changes(self):
        song, _ = tef.read_tef(tef_grace_fixture())
        before = copy.deepcopy(song)
        self.assertTrue(all(tgimport.track_midi_mix(song, track)['pan'] == 67
                            for track in song['score']['tracks'].values()))
        with self.assertRaisesRegex(ValueError, 'GP mixer pan requires a native multiple of four'):
            export(song, 5)
        self.assertEqual(song, before)

    def test_tef3_unsafe_grace_metadata_refuses_before_publication(self):
        for kwargs, reason in ((dict(duration=4), 'longer than a sixteenth'),
                               (dict(compound=True), 'compound grace'),
                               (dict(orphan=True), 'preceding grace')):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                source_path = folder/'bad.tef'
                source_path.write_bytes(tef_grace_fixture(**kwargs))
                with self.assertRaisesRegex(ValueError, reason):
                    gui.import_song(source_path, folder/'song.yaml', folder/'samples', native_tab=True)
                self.assertFalse((folder/'song.yaml').exists())
                self.assertFalse((folder/'samples').exists())

    def test_gp_grace_round_trip_values_transitions_dead_and_onbeat(self):
        for version in (3, 4, 5):
            for value in (16, 32, 64):
                for transition in ('none', 'slide', 'bend', 'hammer'):
                    for dead, on_beat in ((False, False), (True, False), (False, True), (True, True)):
                        if version < 5 and on_beat:
                            continue
                        with self.subTest(version=version, value=value, transition=transition,
                                          dead=dead, on_beat=on_beat):
                            song = grace_song(value=value, transition=transition, dead=dead,
                                              fret=0 if dead and version < 5 else 3, on_beat=on_beat)
                            before = copy.deepcopy(song)
                            data, report = export(song, version)
                            restored = gpimport._native_gp_song(gpimport._read_native_gp(data), song['module']['title'])
                            self.assertEqual(restored['score'], song['score'])
                            self.assertEqual(plan(restored), plan(song))
                            self.assertEqual(song, before)
                            self.assertEqual(report['generated_rests'], 0)

    def test_grace_unrepresentable_flags_and_dynamics_refuse_atomically(self):
        for version, kwargs, reason in ((3, dict(on_beat=True), 'before-beat'),
                (4, dict(dead=True, fret=3), 'dead fret0'),
                (5, dict(velocity=80), 'GP grace velocity')):
            song = grace_song(**kwargs)
            before = copy.deepcopy(song)
            with self.subTest(version=version, kwargs=kwargs), self.assertRaisesRegex(ValueError, reason):
                export(song, version)
            self.assertEqual(song, before)

    def test_sparse_pickups_and_internal_gaps_preserve_musical_timing(self):
        song = grace_song()
        # Leading silence, an internal gap and a late entry in a later bar.
        for name, index in (('m1', 0), ('m2', 1), ('m4', 0)):
            song['score']['patterns'][name]['beats'].pop(index)
        before = copy.deepcopy(song)
        for version in (3, 4, 5, '2.0', '1.5'):
            with self.subTest(version=version):
                if isinstance(version, str):
                    data, report = tgimport.native_to_tg(song, tgimport._raw(song), channels=routes(song), version=version)
                    restored, _ = tgimport.read_tg(data)
                else:
                    data, report = export(song, version)
                    restored = gpimport._native_gp_song(gpimport._read_native_gp(data), song['module']['title'])
                self.assertEqual(sounding(restored), sounding(song))
                self.assertEqual(report['generated_rests'], 3)
                self.assertTrue(any('explicit rests' in w for w in report['warnings']))
                self.assertEqual(song, before)

    def test_double_dotted_silence_is_spelled_exactly_for_gp(self):
        song = grace_song()
        first = song['score']['patterns']['m1']['beats'][0]
        first.update(at=[7, 4], written=dict(value=16, dots=0, tuplet=[1, 1]))
        song['score']['patterns']['m1']['beats'] = [first]
        data, report = export(song, 5)
        restored = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Sparse')
        self.assertEqual(report['generated_rests'], 2)
        self.assertEqual(sounding(restored), sounding(song))

    def test_real_gp6_gp7_pickup_grace_tg_roundtrip(self):
        for version, writer in ((6, test_gpx.gp6), (7, test_gpx.gp7)):
            with self.subTest(version=version):
                song, _ = test_gpx.native(writer(test_gpx.fixture(version)))
                original = copy.deepcopy(song)
                data, report = tgimport.native_to_tg(song, tgimport._raw(song), channels=routes(song))
                restored, _ = tgimport.read_tg(data)
                self.assertGreater(report['generated_rests'], 0)
                self.assertEqual(sounding(restored), sounding(song))
                self.assertEqual(song, original)
                a = [n.get('grace') for p in song['score']['patterns'].values() for b in p['beats'] for n in b['notes']]
                b = [n.get('grace') for p in restored['score']['patterns'].values() for b in p['beats'] for n in b['notes']]
                self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
