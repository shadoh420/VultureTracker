"""Guitar Pro 1/2 (.gtp) native import, read as TuxGuitar 2.1.0 reads it (vulturetracker/gplegacy.py).

Fixtures are written here byte by byte from the pinned TG reader's layout; none comes from a real tab."""
import struct
import tempfile
import unittest
from pathlib import Path

try:
    import guitarpro  # noqa: F401
except ImportError:  # pragma: no cover
    guitarpro = None

from vulturetracker import gplegacy, gpimport

GP1 = ('FICHIER GUITARE PRO v1', 'FICHIER GUITARE PRO v1.01', 'FICHIER GUITARE PRO v1.02',
       'FICHIER GUITARE PRO v1.03', 'FICHIER GUITARE PRO v1.04')
GP2 = ('FICHIER GUITAR PRO v2.20', 'FICHIER GUITAR PRO v2.21')


def i32(v):
    return struct.pack('<i', v)


def sized(text, encoding='cp1252'):  # readStringByteSizeOfByte: size+1, length, bytes
    raw = text.encode(encoding)
    return bytes([len(raw) + 1, len(raw)]) + raw


def short(text, encoding='cp1252'):  # readStringByte(0): length, bytes
    raw = text.encode(encoding)
    return bytes([len(raw)]) + raw


def track(**kw):
    return dict(dict(strings=[64, 59, 55, 50, 45, 40], program=25, name='Guitar', solo=0, volume=127,
                     balance=63, chorus=0, reverb=0, offset=0, frets=29), **kw)


def beat(*notes, value=0, **kw):
    """notes: (bit, fret[, dynamic[, effect byte[, bend byte]]])."""
    return dict(dict(value=value, notes=notes), **kw)


def gtp(version, tracks, measures, *, title='Fixture', artist='Writer', third='', tempo=120, swing=0, key=0,
        encoding='cp1252'):
    """measures: dicts with beats=[per-track beat lists], meter, repeat_open, repeat_close, alternative."""
    gp1, code = version in GP1, (GP1 + GP2).index(version) % 5
    many = not gp1 or code > 2
    out = bytearray([len(version)]) + version.encode().ljust(30, b'\0')
    out += sized(title, encoding) + sized(artist, encoding) + sized(third, encoding) + i32(tempo) + i32(swing)
    if many:
        out += i32(key)
    for t in tracks:
        if not gp1 or code > 1:
            out += i32(len(t['strings']))
        out += b''.join(i32(p) for p in t['strings'])
    out += i32(len(measures))
    for t in tracks:
        out += i32(t['program'])
        if many:
            out += i32(t['frets']) + sized(t['name'], encoding) + bytes([t['solo']])
            out += b''.join(i32(t[k]) for k in ('volume', 'balance', 'chorus', 'reverb', 'offset'))
    if many:
        out += bytes(10)
    for m in measures:
        out += bytes(m.get('meter', (4, 4))) + bytes(6)
        for beats in m['beats']:
            out += bytes(2) + bytes([len(beats)]) + bytes(9)
        out += bytes(2)
        flags = (1 if m.get('repeat_open') else 0) | (2 if 'repeat_close' in m else 0) | (4 if 'alternative' in m else 0)
        out += bytes([flags])
        if flags & 2:
            out += bytes([m['repeat_close']])
        if flags & 4:
            out += bytes([m['alternative']])
        for beats in m['beats']:
            for b in beats:
                out += _beat(b, gp1, code, encoding)
    return bytes(out)


def _beat(b, gp1, code, encoding='cp1252'):
    flags = ((0x01 if 'text' in b else 0) | (0x02 if 'chord' in b else 0) | (0x04 if 'effect' in b else 0)
             | (0x08 if b.get('rest') else 0) | (0x10 if b.get('dotted') else 0) | (0x20 if b.get('triplet') else 0)
             | (0x40 if b.get('tie') else 0))
    out = bytearray(i32(0)) + struct.pack('<b', b['value']) + bytes([flags])
    if not gp1:
        out += bytes([(2 if 'mix' in b else 0) | (1 if 'stroke' in b else 0)])
        if 'mix' in b:
            tempo, others = b['mix']
            out += bytes([(0x20 if tempo else 0) | others]) + (i32(tempo) + bytes(1) if tempo else b'')
            out += bytes(2 * bin(others & 0x1e).count('1') + (others & 1))
        if 'stroke' in b:
            out += bytes(2)
    if b.get('triplet'):
        out += bytes(1)
    if 'effect' in b:
        out += bytes([b['effect']])
        if b['effect'] == 3:
            out += bytes(6) + bytes([b['bend']]) + bytes(1)
    if 'chord' in b:
        name, first, frets = b['chord']
        if gp1 and code <= 3:
            out += sized(name, encoding)
        else:
            out += short(name, encoding) + bytes(1) + i32(12) + i32(first) + (b''.join(i32(f) for f in frets) if first else b'')
    if 'text' in b:
        out += short(b['text'], encoding)
    if not b.get('tie') and not b.get('rest'):
        strings = sum(1 << n[0] for n in b['notes'])
        effects = sum(1 << n[0] for n in b['notes'] if len(n) > 3 and n[3] is not None)
        out += bytes([strings, effects])
        if not gp1:
            out += bytes([sum(1 << g for g in b.get('graces', ()))])
        for bit in range(5, -1, -1):
            for n in b['notes']:
                if n[0] != bit:
                    continue
                out += bytes([n[1]])
                if not gp1:
                    out += bytes([n[2] if len(n) > 2 else 6])
                if len(n) > 3 and n[3] is not None:
                    out += bytes([n[3]])
                    if n[3] in (5, 6):
                        out += bytes(6) + bytes([n[4]]) + bytes(1)
            if not gp1 and bit in b.get('graces', ()):
                out += bytes(3)
    return bytes(out)


def native(data):
    warnings = []
    gp, balances = gplegacy.read_gtp(data, warnings)
    song = gpimport._native_gp_song(gp, gp.title, warnings=warnings)
    for t, b in zip(song['score']['tracks'].values(), balances):
        t['midi']['source_pan']['value'] = b
    return song, warnings


def notes(song, track='t1'):
    return [(p, b['at'], n) for p, spec in song['score']['patterns'].items()
            for b in spec['beats'] if b['track'] == track for n in b['notes']]


FOUR = [beat((5, 0), value=0) for _ in range(4)]


@unittest.skipIf(guitarpro is None, 'needs pyguitarpro')
class TestGp12Read(unittest.TestCase):
    def test_every_version_string_reads_with_its_track_layout(self):
        for version in GP1 + GP2:
            with self.subTest(version=version):
                many = version not in GP1[:3]
                tracks = [track() for _ in range(8 if many else 1)]
                beats = [FOUR] + [[] for _ in tracks[1:]]
                song, warnings = native(gtp(version, tracks, [dict(beats=beats)]))
                self.assertEqual(len(song['score']['tracks']), len(tracks))
                self.assertEqual(song['score']['tracks']['t1']['tuning'], [64, 59, 55, 50, 45, 40])
                self.assertEqual(len(notes(song)), 4)
                self.assertEqual(song['score']['metadata']['author'], 'Writer')
                self.assertNotIn('artist', song['score']['metadata'])
                velocity = 95 if version in GP1 else 16 * 6 - 1
                self.assertEqual({n['velocity'] for _, _, n in notes(song)}, {velocity})
                self.assertEqual(song['score']['tracks']['t1']['name'], 'Guitar' if many else 'Track 1')
                if many:
                    self.assertTrue(any('track 8 (percussion, no notes)' in w for w in warnings))
                    self.assertEqual(song['score']['tracks']['t8']['midi']['bank'], 128)

    def test_detection_is_by_header_not_extension(self):
        data = gtp(GP1[4], [track() for _ in range(8)], [dict(beats=[FOUR] + [[]] * 7)])
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'tab.gp5'
            src.write_bytes(data)
            song, warnings = gpimport.import_gp(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples', native=True)
            self.assertEqual(len(notes(song)), 4)
            self.assertTrue((Path(tmp) / 'song.yaml').exists())
            # Legacy (non-native) import reads it too.
            song, _ = gpimport.import_gp(src, Path(tmp) / 'flat.yaml', Path(tmp) / 'flat_samples')
            self.assertTrue((Path(tmp) / 'flat.yaml').exists())
        self.assertIsNone(gplegacy.version_of(b'FICHIER'))
        self.assertNotIn(gplegacy.version_of(bytes([26]) + b'FICHIER GUITAR PRO v3.00'.ljust(30, b'\0')),
                         gplegacy.VERSIONS)

    def test_centre_balance_binds_63_like_gp3_to_gp5(self):
        # Owner decision 2026-10-20: raw centre 64 binds as 63 (GP3-5 export accepts it); CC10 is one step from TG.
        for raw, value in ((64, 63), (63, 63), (65, 65)):
            with self.subTest(raw=raw):
                song, _ = native(gtp(GP2[1], [track(balance=raw)] + [track() for _ in range(7)],
                                     [dict(beats=[FOUR] + [[]] * 7)]))
                self.assertEqual(song['score']['tracks']['t1']['midi']['source_pan']['value'], value)

    def test_metadata_tuning_capo_key_and_exact_pan(self):
        t = track(strings=[62, 57, 53, 48], offset=2, balance=40, volume=100, program=33, name='Bass')
        data = gtp(GP2[1], [t] + [track() for _ in range(7)],
                   [dict(beats=[[beat((3, 1)), beat((2, 0), value=-1), beat((3, 2))]] + [[]] * 7)],
                   title='Title', artist='Artist', third='Comment', key=9, tempo=96, swing=1)
        song, warnings = native(data)
        t1 = song['score']['tracks']['t1']
        self.assertEqual((t1['tuning'], t1['capo'], t1['name'], t1['midi']['program']), ([62, 57, 53, 48], 2, 'Bass', 33))
        self.assertEqual(t1['key'], dict(fifths=-2, mode='major'))
        self.assertEqual(t1['midi']['source_pan'], dict(value=40, mixer_pan=20))
        self.assertEqual(song['module']['tempo'], 96)
        self.assertEqual(song['score']['measures'][0]['swing'], 'eighth')
        self.assertIn('music: Artist', song['module']['message'])
        self.assertEqual(song['score']['metadata']['author'], 'Artist')
        self.assertTrue(any("'Comment'" in w for w in warnings))
        self.assertTrue(any('MIDI volume 100' in w for w in warnings))
        # bit i is string (count - i): bit 3 on four strings is string 1.
        self.assertEqual([(n['string'], n['fret'], n['pitch']) for _, _, n in notes(song)],
                         [(1, 1, 65), (2, 0, 59), (1, 2, 66)])

    def test_one_shared_effect_per_beat_accumulates_in_read_order(self):
        # Bit 5 is read first and bends. Bit 4's hammer byte clears that bend
        # (TGNoteEffect.setHammer); bit 3, without an effect byte, inherits the hammer.
        # Second beat: a slide is inherited, then a bend clears it; a dead note drops all three.
        b = beat((5, 3, 6, 5, 8 * 28), (4, 3, 6, 1), (3, 2))
        c = beat((5, 3, 6, 3), (4, 3, 6, None), (2, 1, 6, 6, 8 * 30), (1, 120))
        song, _ = native(gtp(GP1[4], [track() for _ in range(8)], [dict(beats=[[b, c, *FOUR[:2]]] + [[]] * 7)]))
        first = [n for _, at, n in notes(song) if at == [0, 1]]
        self.assertEqual([n['string'] for n in first], [1, 2, 3])
        bend = dict(points=[dict(position=0, value=0), dict(position=6, value=2), dict(position=12, value=2)])
        self.assertEqual([n.get('bend') for n in first], [bend, None, None])
        self.assertEqual([n.get('hammer', False) for n in first], [False, True, True])
        second = [n for _, at, n in notes(song) if at == [1, 1]]
        self.assertEqual([(n.get('slide', False), 'bend' in n, n.get('dead', False)) for n in second],
                         [(True, False, False), (True, False, False), (False, True, False), (False, False, True)])

    def test_beat_effects_ties_dead_notes_and_text(self):
        beats = [beat((5, 3), effect=4, text='fade'), beat((5, 3), tie=True), beat((5, 120), effect=8),
                 beat((5, 5), effect=6), beat(tie=True, effect=1), beat(rest=True, effect=2)]
        beats = [dict(b, value=1) for b in beats] + [beat((5, 0), value=1), beat((5, 0), value=1)]
        song, warnings = native(gtp(GP1[4], [track() for _ in range(8)], [dict(beats=[beats] + [[]] * 7),
                                                                            dict(beats=[[]] * 8)]))
        got = notes(song)
        self.assertTrue(got[0][2].get('fade_in'))
        self.assertEqual(len(song['score']['ties']), 2)
        self.assertNotIn('fade_in', got[1][2])
        self.assertTrue(got[2][2].get('dead') and got[2][2]['harmonic'] == dict(type='natural', data=0))
        self.assertTrue(got[3][2].get('slapping'))
        self.assertTrue(any('beat effects on tied beats' in w for w in warnings))
        self.assertTrue(any('beat effects on rests' in w for w in warnings))
        self.assertTrue(any('generated rests' in w for w in warnings))
        self.assertEqual(next(b for b in song['score']['patterns']['m1']['beats'])['text'], 'fade')

    def test_gp2_tempo_mix_dynamics_and_discarded_fields(self):
        beats1 = [beat((5, 0, 8)), beat((5, 0, 1), stroke=True), beat((5, 0), graces=(5,)), beat((5, 0))]
        beats2 = [beat((5, 0), mix=(140, 0x02)), *FOUR[:3]]
        song, warnings = native(gtp(GP2[0], [track() for _ in range(8)],
                                    [dict(beats=[beats1] + [[]] * 7), dict(beats=[beats2] + [[]] * 7)]))
        self.assertEqual([n['velocity'] for _, _, n in notes(song)][:2], [127, 15])
        self.assertEqual(song['patterns']['m2']['data'], '00: ... .. ... T8C\n')
        for text in ('stroke', 'grace notes', 'mix-table volume'):
            self.assertTrue(any(text in w for w in warnings), text)

    def test_repeats_and_alternatives(self):
        empty = [[]] * 7
        measures = [dict(beats=[FOUR] + empty, repeat_open=True), dict(beats=[FOUR] + empty, alternative=1, repeat_close=1),
                    dict(beats=[FOUR] + empty, alternative=2)]
        song, _ = native(gtp(GP1[4], [track() for _ in range(8)], measures))
        m = song['score']['measures']
        self.assertTrue(m[0]['repeat_open'])
        self.assertEqual((m[1]['endings'], m[1]['repeat_close'], m[2]['endings']), ([1], 1, [2]))

    def test_chords(self):
        b = dict(beat((5, 3)), chord=('G', 1, [3, 0, 0, 0, 2, 3]))
        named = dict(beat((5, 3)), chord=('X', 0, []))
        song, warnings = native(gtp(GP1[4], [track() for _ in range(8)], [dict(beats=[[b, named, *FOUR[:2]]] + [[]] * 7)]))
        first = song['score']['patterns']['m1']['beats'][0]
        self.assertEqual(first['chord'], dict(name='G', first_fret=1, frets=[3, 0, 0, 0, 2, 3]))
        self.assertTrue(any('name-only chord' in w for w in warnings))
        _, warnings = native(gtp(GP1[3], [track() for _ in range(8)], [dict(beats=[[dict(beat((5, 3)), chord=('G', 0, []))] + FOUR[:3]] + [[]] * 7)]))
        self.assertTrue(any('chord names discarded' in w for w in warnings))

    def test_track_8_is_percussion_after_tg_normalizer(self):
        drums = track(strings=[0] * 6, program=12)
        data = gtp(GP1[4], [track() for _ in range(7)] + [drums],
                   [dict(beats=[[]] * 7 + [[beat((5, 36)), beat((4, 38)), beat((5, 42), (3, 38)), beat((5, 36))]])])
        song, warnings = native(data)
        t8 = song['score']['tracks']['t8']
        self.assertEqual((t8['midi']['bank'], t8['midi']['program']), (128, 0))
        self.assertEqual([n['pitch'] for _, _, n in notes(song, 't8')], [36, 38, 42, 38, 36])
        self.assertTrue(any('program 12 is replaced by 0' in w for w in warnings))

    def test_refusals_are_specific(self):
        tracks = [track() for _ in range(8)]
        cases = {'track 8 is percussion': gtp(GP1[4], tracks, [dict(beats=[[]] * 7 + [FOUR])]),
                 'string bit 5 maps to string -4': gtp(GP1[4], [track(strings=[64])] + tracks[1:],
                                                        [dict(beats=[FOUR] + [[]] * 7)]),
                 'key signature 15': gtp(GP1[4], tracks, [dict(beats=[[]] * 8)], key=15),
                 'truncated': gtp(GP1[4], tracks, [dict(beats=[FOUR] + [[]] * 7)])[:-3],
                 'slide reaches time TuxGuitar 2.1.0 fills with generated rests': gtp(
                     GP1[4], tracks, [dict(beats=[[*FOUR[:3], beat((5, 3, 6, 3))]] + [[]] * 7), dict(beats=[[]] * 8),
                                      dict(beats=[FOUR] + [[]] * 7)]),
                 'unsupported isSolo': gtp(GP1[4], [track(solo=1)] + tracks[1:], [dict(beats=[FOUR] + [[]] * 7)])}
        for text, data in cases.items():
            with self.subTest(text):
                with self.assertRaisesRegex(ValueError, text):
                    native(data)


@unittest.skipIf(guitarpro is None, 'needs pyguitarpro')
class TestGp12Encoding(unittest.TestCase):
    def test_selected_encoding_preserves_all_text_fields(self):
        for version in (GP1[4], GP2[1]):
            for encoding, text in (('utf-8', '音楽'), ('cp1251', 'Песня'), ('shift_jis', '音楽')):
                tracks = [track(name=text)] + [track() for _ in range(7)]
                beats = [beat((5, 0), text=text, chord=(text, 1, [0] * 6)), *FOUR[1:]]
                data = gtp(version, tracks, [dict(beats=[beats] + [[]] * 7)], title=text, artist=text,
                           encoding=encoding)
                with self.subTest(version=version, encoding=encoding), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    src = root / 'source.gtp'
                    src.write_bytes(data)
                    song, warnings = gpimport.import_gp(src, root / 'song.yaml', root / 'samples', native=True,
                                                       encoding=encoding)
                    score = song['score']
                    self.assertEqual(score['metadata']['title'], text)
                    self.assertEqual(score['metadata']['author'], text)
                    self.assertNotIn('artist', score['metadata'])
                    self.assertEqual(score['tracks']['t1']['name'], text)
                    first = score['patterns']['m1']['beats'][0]
                    self.assertEqual(first['text'], text)
                    self.assertEqual(first['chord']['name'], text)
                    self.assertIn(f'Guitar Pro text decoded with {gpimport.guitar_pro_encoding(encoding)}.', warnings)
                    self.assertEqual(src.read_bytes(), data)

    def test_default_replacement_is_reported_explicit_encoding_is_strict(self):
        data = gtp(GP1[0], [track()], [dict(beats=[FOUR])], title='X')
        data = data[:33] + b'\x81' + data[34:]
        warnings = []
        parsed, _ = gplegacy.read_gtp(data, warnings)
        self.assertEqual(parsed.title, '\ufffd')
        self.assertTrue(any('invalid cp1252 bytes were replaced' in w for w in warnings))
        for encoding in ('cp1252', 'utf-8'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src = root / 'source.gtp'
                src.write_bytes(data)
                with self.assertRaisesRegex(ValueError, 'UnicodeDecodeError'):
                    gpimport.import_gp(src, root / 'song.yaml', root / 'samples', native=True, encoding=encoding)
                self.assertEqual(list(root.iterdir()), [src])
                self.assertEqual(src.read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
