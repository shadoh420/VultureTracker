"""Original generated PTB/TEF byte fixtures; no third-party songs are included."""
from fractions import Fraction
from pathlib import Path
import struct
import tempfile
import unittest

from vulturetracker import api, export, gui, ptb, tef, tgimport
from tests import test_real_interchange


def u16(n):
    return struct.pack('<H', n)


def u32(n):
    return struct.pack('<I', n)


def text(s):
    b = s.encode('utf-8')
    return (bytes([len(b)]) if len(b) < 255 else b'\xff' + u16(len(b))) + b


def group(values):
    return u16(len(values)) + (u16(0) + u16(0).join(values) if values else b'')


def ptb_fixture(*, bars=4, techniques=True, repeats=False, volume=127, pan=64):
    """Two staves, chord notes, two voices, ties, tempo, and supported techniques."""
    info = b'\x01' + text('Original band import study') + text('Generated fixture') + b'\0\0\0' + text('VultureTracker') + text('Original music') + text('CC0 fixture')
    def instrument(number, name, tuning, program):
        return bytes([number]) + text(name) + bytes([program, volume, pan, 0, 0, 0, 0, 0]) + text('Standard') + bytes([0, len(tuning), *tuning])
    instruments = [instrument(0, 'Guitar', [64, 59, 55, 50, 45, 40], 25),
                   instrument(1, 'Bass', [43, 38, 33, 28], 33)]
    def bar(pos, open_repeat=False):
        return bytes([pos, 96 if open_repeat else 0, 0]) + u32(26 << 24) + b'\x04\0' + text('')
    def beat(pos, voice, string, fret, value=4, tied=False, effect=None):
        symbol = b'' if effect is None else bytes([0, 0, 0, effect])
        note = bytes([(string - 1) * 32 + fret]) + u16(1 if tied else 0) + bytes([bool(symbol)]) + symbol
        return bytes([pos, 0, 0, 0, 0, 0, value, 0]) + group([note])
    staves = []
    for ti in range(2):
        notes = []
        for mi in range(bars):
            for q in range(4):
                # The tied chain has the same fret at bar1 end and bar2 start.
                fret = (mi * 4 + q) % 5
                if mi == 1 and q == 0:
                    fret = 3
                notes.append(beat(mi * 5 + 1 + q, 0, 2, fret, tied=mi == 1 and q == 0,
                                  effect=100 if techniques and mi == 2 and q == 0 else None))
        lower = [beat(mi * 5 + 1, 1, 3, 0, 1) for mi in range(bars)]
        staves.append(b'\0' * 5 + group(notes) + group(lower))
    section = b'\0' * 16 + bytes([130 if repeats else 0]) + b'\0' * 4 + bar(0, repeats)
    section += group([]) * 3 + group(staves) + group([bar(mi * 5) for mi in range(1, bars)])
    tempo = u16(0) + bytes([0]) + u16(120) + u16(0) + text('')
    changes = [u16(0) + bytes([i, 0, 0, 1 << i]) for i in range(2)]
    bank = group(instruments) + group([]) * 2 + group(changes) + group([tempo]) + group([]) * 2 + group([section])
    return b'ptab\x04\0' + info + bank + group([]) * 8


def te_track(name, tuning, program, version=3, *, volume=0, pan=8):
    b = bytearray(50)
    b[0], b[8], b[14], b[15], b[17], b[18] = len(tuning), program, 12, 1, pan, volume
    b[20:20 + len(tuning)] = bytes(96 - p for p in tuning)
    name = name.encode('ascii')[:15]
    b[32:32 + len(name)] = name
    return bytes(b)


def tef2_fixture(*, bars=4, techniques=True, volume=0, pan=8):
    header = bytearray(256)
    info = b'Original TEF2 study\0VultureTracker\0CC0 fixture\0'
    header[:len(info)] = info
    header[200:202], header[202], header[204] = u16(bars), 4, 4
    header[220:222], header[240], header[241] = u16(120), 10, 1
    components = []
    for mi in range(bars):
        for string in (1, 7):
            for q in range(4):
                loc = (mi * 10 + string) * 256 + q * 64
                effect = 8 if techniques and mi == 2 and q == 0 else 0
                components.append(u16(loc % 65536) + bytes([1 + (mi + q) % 5, 6 | (2 << 5), effect, 0]))
    return bytes(header) + u16(len(components)) + b''.join(components) + te_track('Guitar', [64, 59, 55, 50, 45, 40], 25, 2, volume=volume, pan=pan) + te_track('Bass', [43, 38, 33, 28], 33, 2, volume=volume, pan=pan)


def tef3_fixture(*, bars=4, techniques=True, repeats=False, volume=0, pan=8):
    header = bytearray(256)
    header[3], header[6:8] = 3, u16(120)
    header[56:60], header[202:206] = b'tbed', b'\x04\0\x04\x0a'
    def st(s):
        b = s.encode('utf-8') + b'\0'
        return u16(len(b)) + b
    metadata = b''.join(st(s) for s in ('Original TEF3 study', 'VultureTracker', 'CC0 fixture', '', ''))
    measures = u16(12) + u16(bars) + b'\0' * 4 + bytes([0, 0, 0, 48, 4, 4, 0, 0]) * bars
    tracks = u16(50) + u16(2) + te_track('Guitar', [64, 59, 55, 50, 45, 40], 25, volume=volume, pan=pan) + te_track('Bass', [43, 38, 33, 28], 33, volume=volume, pan=pan)
    components = []
    stride = 320
    for mi in range(bars):
        for string in (1, 7):
            for q in range(4):
                loc = (mi * 16 + q * 4) * stride + string * 8
                fret = (mi * 4 + q) % 5
                if mi == 1 and q == 0:
                    fret = 3
                fx = 8 if techniques and mi == 2 and q == 0 else 0
                tied = mi == 1 and q == 0
                components.append(u32(loc) + bytes([fret + 1, 6 | (2 << 5), fx, 0, 0, 0, 0, 32 if tied else 0]))
            loc = mi * 16 * stride + (string + 1) * 8
            components.append(u32(loc) + bytes([1, 0 | (3 << 5), 48, 0, 0, 0, 0, 0]))
    if repeats:
        components += [u32(8) + bytes([0xb7, 1, 64, 0, 0, 0, 0, 0]),
                       u32(((bars - 1) * 16) * stride + 8) + bytes([0xb7, 1, 128 | 2, 0, 0, 0, 0, 0])]
    components.sort(key=lambda c: int.from_bytes(c[:4], 'little'))
    return bytes(header) + metadata + measures + tracks + b'\x01\x01\0' + b'\0' * 256 + b''.join(components) + b'\xff' * 4


class TestBandImports(unittest.TestCase):
    def test_source_mix_survives_import_and_tg_roundtrip(self):
        for name, reader, fixture, maximum in (
                ('ptb', ptb.read_ptb, ptb_fixture, 127),
                ('tef2', tef.read_tef, tef2_fixture, 15),
                ('tef3', tef.read_tef, tef3_fixture, 15)):
            for value in range(maximum + 1):
                with self.subTest(format=name, value=value):
                    song, notices = reader(fixture(volume=value, pan=value))
                    expected = (value, value) if name == 'ptb' else ((15-value)*127//15, value*127//15)
                    for track in song['score']['tracks'].values():
                        self.assertEqual(tgimport.track_midi_mix(song, track), dict(zip(('volume','pan'),expected)))
                        for channel in track['channels']:
                            self.assertEqual(tuple(song['module']['channels'][channel][k] for k in ('volume','pan')),
                                             tuple((n*64+63)//127 for n in expected))
                    routes = {tid: {k:v for k,v in t['midi'].items() if k in ('program','bank')} for tid,t in song['score']['tracks'].items()}
                    data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels=routes)
                    again, _ = tgimport.read_tg(data)
                    self.assertEqual([tgimport.track_midi_mix(again,t) for t in again['score']['tracks'].values()], [dict(zip(('volume','pan'),expected))]*2)
                    self.assertFalse(any('descriptive only' in n or 'normalized to center' in n for n in notices))

    def test_invalid_source_mix_refuses_before_publication(self):
        for name, fixture, maximum in (('ptb',ptb_fixture,127),('tef2',tef2_fixture,15),('tef3',tef3_fixture,15)):
            for control in ('volume','pan'):
                with self.subTest(format=name,control=control), tempfile.TemporaryDirectory() as temporary:
                    folder=Path(temporary)
                    source=folder/('source.ptb' if name=='ptb' else 'source.tef')
                    source.write_bytes(fixture(**{control:maximum+1}))
                    with self.assertRaisesRegex(ValueError,'must be in'):
                        gui.import_song(source,folder/'song.yaml',folder/'samples')
                    self.assertFalse((folder/'song.yaml').exists())
                    self.assertFalse((folder/'samples').exists())

    def test_counts_timing_voices_techniques_and_ties(self):
        for name, reader, fixture, count, ties in (
                ('ptb', ptb.read_ptb, ptb_fixture, 40, 2),
                ('tef2', tef.read_tef, tef2_fixture, 32, 0),
                ('tef3', tef.read_tef, tef3_fixture, 40, 2)):
            with self.subTest(name=name):
                song, notices = reader(fixture())
                score = song['score']
                self.assertEqual((len(score['tracks']), len(score['measures'])), (2, 4))
                notes = [n for p in score['patterns'].values() for b in p['beats'] for n in b['notes']]
                self.assertEqual(len(notes), count)
                self.assertEqual(len(score['ties']), ties)
                self.assertTrue(notices[0].endswith('sounds are not reproduced.'))
                self.assertTrue(any(n.get('slide' if name == 'ptb' else 'palm_mute') for n in notes))
                self.assertEqual([t['midi']['program'] for t in score['tracks'].values()], [25, 33])
                self.assertEqual(score['measures'][-1]['to']['at'], [4, 1])

    def test_import_edit_reopen_tg_export_and_no_overwrite(self):
        for name, fixture in (('ptb', ptb_fixture), ('tef2', tef2_fixture), ('tef3', tef3_fixture)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                source = folder / ('source.ptb' if name == 'ptb' else 'source.tef')
                source.write_bytes(fixture())
                target, notices = gui.import_song(source, folder/'score.yaml', folder/'samples')
                state = gui.State(target, headless=True)
                try:
                    self.assertFalse(state.error, state.error)
                    routes = {tid: {k:v for k,v in t['midi'].items() if k in ('program','bank')} for tid, t in state.song['score']['tracks'].items()}
                    data, report = tgimport.native_to_tg(state.song, state.mod.patterns, channels=routes)
                    again, _ = tgimport.read_tg(data)
                    self.assertEqual(len(again['score']['ties']), len(state.song['score']['ties']))
                finally:
                    state.close()
                test_real_interchange.TestRealInterchange.exercise_edit(self, target)
                before = target.read_bytes()
                with self.assertRaisesRegex(ValueError, 'fresh destination'):
                    gui.import_song(source, target, folder/'samples')
                self.assertEqual(before, target.read_bytes())

    def test_truncation_unknown_fields_and_atomic_publication(self):
        for reader, fixture in ((ptb.read_ptb, ptb_fixture), (tef.read_tef, tef2_fixture), (tef.read_tef, tef3_fixture)):
            data = fixture()
            for cut in (0, 4, 120, len(data) - 1, len(data) - 20):
                with self.subTest(reader=reader.__name__, cut=cut), self.assertRaises(ValueError):
                    reader(data[:cut])
        bad = bytearray(tef3_fixture())
        bad[-16 + 4] = 0x7e  # program change: must never silently disappear
        with self.assertRaisesRegex(ValueError, 'unsupported musical component'):
            tef.read_tef(bytes(bad))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder/'bad.tef'; source.write_bytes(bad)
            with self.assertRaises(ValueError):
                gui.import_song(source, folder/'bad.yaml', folder/'samples')
            self.assertFalse((folder/'bad.yaml').exists())
            self.assertFalse((folder/'samples').exists())

    def test_repeat_structure_is_written_not_flattened(self):
        for reader, fixture in ((ptb.read_ptb, ptb_fixture), (tef.read_tef, tef3_fixture)):
            song, _ = reader(fixture(repeats=True))
            self.assertEqual(len(song['score']['measures']), 4)
            self.assertTrue(song['score']['measures'][0]['repeat_open'])
            self.assertEqual(song['score']['measures'][-1]['repeat_close'], 1)

    def test_tef2_exact_dots_and_triplets(self):
        source = tef2_fixture(techniques=False)
        count = int.from_bytes(source[256:258], 'little')
        records = [source[258 + i * 6:264 + i * 6] for i in range(count)]
        # First track/string2: three eighth triplets, dotted quarter, eighth,
        # quarter. The source's triplet positions use the documented 4/3 warp.
        records = [c for c in records if not 256 <= int.from_bytes(c[:2], 'little') < 512]
        for pos, code in ((0, 11), (16, 11), (32, 11), (64, 4), (160, 9), (192, 6)):
            records.append(u16(256 + pos) + bytes([3, code | (2 << 5), 0, 0]))
        records.sort(key=lambda c: int.from_bytes(c[:2], 'little'))
        changed = source[:256] + u16(len(records)) + b''.join(records) + source[258 + count * 6:]
        song, _ = tef.read_tef(changed)
        beats = [b for b in song['score']['patterns']['m1']['beats'] if b['track'] == 't1']
        self.assertEqual([b['at'] for b in beats], [[0, 1], [1, 3], [2, 3], [1, 1], [5, 2], [3, 1]])
        self.assertEqual(beats[0]['written'], dict(value=8, dots=0, tuplet=[3, 2]))
        self.assertEqual(beats[3]['written'], dict(value=4, dots=1, tuplet=[1, 1]))

    def test_tef3_next_bar_first_string_boundary_is_not_previous_bar(self):
        source = bytearray(tef3_fixture(techniques=False))
        # Locate one second-bar first-voice string2 note, move to string1.
        position = u32(16 * 320 + 8)
        offset = source.find(position, 256)
        self.assertGreater(offset, 256)
        source[offset:offset + 4] = u32(16 * 320)
        source[offset + 11] = 0  # detach the original same-string tie
        song, _ = tef.read_tef(bytes(source))
        beat = next(b for b in song['score']['patterns']['m2']['beats'] if b['track'] == 't1' and b['voice'] == 0 and b['at'] == [0, 1])
        self.assertEqual(beat['notes'][0]['string'], 1)
        self.assertEqual(len(song['score']['ties']), 1)


if __name__ == '__main__':
    unittest.main()
