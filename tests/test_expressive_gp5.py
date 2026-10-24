"""Shared chord/pick/brush metadata through native GP delivery."""
import copy
import unittest

from tests.test_complex_interchange import grace_song, sounding
from tests.test_gpexport_legacy import export, plan
from vulturetracker import gpimport, tablature


def metadata(song):
    return [(mi, tablature._cohort_strokes(pattern['beats']))
            for mi, pname in enumerate(song['orders'])
            for pattern in [song['score']['patterns'][pname]]]


def gp5_signature(song):
    """Musical/notation invariants independent of format-local IDs and samples.

    Explicit gap rests and authored route IDs are not interchange identity.
    Includes shared diagrams/brushes, all note techniques, ties and performed
    events; use on both the native source and the reopened GP/TG document.
    """
    score = song['score']
    def normalized(value):
        if isinstance(value, dict):
            return {k: normalized(v) for k, v in value.items() if v is not None and v is not False}
        if isinstance(value, list):
            return [normalized(v) for v in value]
        return value
    tracks = {tid: i for i, tid in enumerate(score['tracks'])}
    notes, labels, endpoints = [], [], {}
    for mi, (oid, pname) in enumerate(zip(score['order_ids'], song['orders'])):
        beats = score['patterns'][pname]['beats']
        for (tid, at, cohort), fields in tablature._cohort_strokes(beats).items():
            if fields:
                labels.append((mi, tracks[tid], at, cohort, fields))
        for beat in beats:
            if beat.get('text'):
                labels.append((mi, tracks[beat['track']], tuple(beat['at']), beat.get('cohort', 0), dict(text=beat['text'])))
            for note in beat['notes']:
                key = (mi, tracks[beat['track']], beat['voice'], tuple(beat['at']), note['string'])
                endpoints[(oid, note['id'])] = key
                notes.append((key, beat['written'], normalized({k: v for k, v in note.items()
                    if k not in ('id', 'instrument', 'channel')})))
    ties = sorted((endpoints[(t['from']['occurrence'], t['from']['note'])],
                   endpoints[(t['to']['occurrence'], t['to']['note'])]) for t in score.get('ties', []))
    events = sorted((e['type'], tracks[e['track']], e.get('voice', 0), e.get('pitch', -1),
                     e.get('velocity', -1), tuple(e['at']), e.get('bend_value', -1),
                     e.get('expression', -1), tuple(e.get('gains', [])))
                    for e in plan(song))
    return dict(notes=sorted(notes, key=repr), labels=sorted(labels, key=repr), ties=ties, events=events,
                tracks=[{key: track.get(key, default) for key, default in (
                    ('name', ''), ('tuning', []), ('capo', 0), ('key', dict(fifths=0, mode='major')),
                    ('clef', 'treble'), ('max_fret', 29), ('color', '#ff0000'), ('lyrics', None))}
                        for track in score['tracks'].values()],
                measures=[{k: v for k, v in m.items() if k not in ('id', 'from', 'to')}
                          for m in score['measures']],
                credits={key: score.get('metadata', {}).get(key, default) for key, default in (
                    ('title', song['module'].get('title', '')), ('artist', ''), ('album', ''),
                    ('author', ''), ('writer', ''), ('transcriber', ''), ('copyright', ''),
                    ('comments', song['module'].get('message', '')))})


def metadata_song(*, direction='down', value=16, second_voice=False):
    song = grace_song()
    beats = song['score']['patterns']['m1']['beats']
    first = beats[0]
    first.update(chord=dict(name='Café G', first_fret=0, frets=[3, 0, 0, 0, 2, 3]),
                 stroke=dict(direction=direction, value=value), pick_stroke=direction)
    if second_voice:
        second = copy.deepcopy(first)
        second.update(id='other-voice', voice=1)
        second['notes'] = [dict(id='other-note', pitch=48, string=6, fret=8, velocity=95)]
        beats.append(second)
        # A sparse annotation is shared, even if the other voice uses nulls.
        for field in ('stroke', 'pick_stroke', 'chord'):
            first[field] = None
    return song


class TestExpressiveGP5(unittest.TestCase):
    def test_chord_pick_brush_directions_speeds_and_sparse_shared_voices(self):
        for version in (3, 4, 5):
            for direction in ('up', 'down'):
                for value in (4, 8, 16, 32, 64):
                    for second_voice in ((False, True) if version == 5 else (False,)):
                        with self.subTest(version=version, direction=direction, value=value, voices=second_voice):
                            song = metadata_song(direction=direction, value=value, second_voice=second_voice)
                            if version == 3:
                                song['score']['patterns']['m1']['beats'][0].pop('pick_stroke')
                            before = copy.deepcopy(song)
                            data, _ = export(song, version)
                            restored = gpimport._native_gp_song(gpimport._read_native_gp(data), song['module']['title'])
                            self.assertEqual(metadata(restored), metadata(song))
                            self.assertEqual(sounding(restored), sounding(song))
                            self.assertEqual(song, before)

    def test_chord_on_rest_and_maximum_encoded_name(self):
        for version in (3, 4, 5):
            song = metadata_song()
            beat = song['score']['patterns']['m1']['beats'][0]
            beat['notes'] = []
            beat.pop('pick_stroke')
            beat.pop('stroke')
            beat['chord']['name'] = 'é' * (22 if version == 3 else 21)
            data, _ = export(song, version)
            restored = gpimport._native_gp_song(gpimport._read_native_gp(data), song['module']['title'])
            self.assertEqual(metadata(restored), metadata(song))

    def test_tg_unset_reverb_only_accepts_gp500_sentinel(self):
        data, _ = export(metadata_song(), 5)
        parsed = gpimport._read_native_gp(data)
        parsed.masterEffect.reverb = -1
        gpimport._native_gp_song(parsed, 'TG rewrite')
        for version, reverb in (((5, 0, 0), 1), ((5, 1, 0), -1)):
            parsed.versionTuple, parsed.masterEffect.reverb = version, reverb
            parsed.masterEffect.volume = 100
            with self.subTest(version=version, reverb=reverb), self.assertRaisesRegex(ValueError, 'master volume/reverb'):
                gpimport._native_gp_song(parsed, 'Effect')

    def test_native_spare_channels_keep_music_and_report_replaced_voice_state(self):
        song = metadata_song(second_voice=True)
        original = copy.deepcopy(song)
        note = song['score']['patterns']['m1']['beats'][-1]['notes'][0]
        note['channel'] = song['score']['tracks']['t1']['channels'][3]
        data, report = export(song, 5)
        restored = gpimport._native_gp_song(gpimport._read_native_gp(data), song['module']['title'])
        self.assertEqual(gp5_signature(restored), gp5_signature(original))
        self.assertTrue(any('native spare channels' in w for w in report['warnings']))
        song['module']['channels'][3]['plugin'] = 1
        with self.assertRaisesRegex(ValueError, 'plugin/external routes'):
            export(song, 5)

    def test_standard_gp_credits_survive_with_explicit_tg_warning(self):
        song = metadata_song()
        credits = dict(author='Composer', writer='Lyricist', transcriber='Engraver')
        song['score']['metadata'].update(credits)
        data, report = export(song, 5)
        restored = gpimport._native_gp_song(gpimport._read_native_gp(data), song['module']['title'])
        self.assertEqual({k: restored['score']['metadata'][k] for k in credits}, credits)
        self.assertTrue(any('discards music' in w for w in report['warnings']))

    def test_unrepresentable_metadata_refuses_without_source_changes(self):
        for version, change, reason in (
                (3, lambda b: None, 'bar 1.*pick direction.*GP4/GP5'),
                (5, lambda b: b['chord'].update(name='x' * 22), 'bar 1.*chord name.*21 encoded bytes'),
                (5, lambda b: b['chord'].update(frets=[-1] * 6), 'bar 1.*name-only/all-muted.*beat text')):
            song = metadata_song()
            change(song['score']['patterns']['m1']['beats'][0])
            before = copy.deepcopy(song)
            with self.subTest(version=version, reason=reason), self.assertRaisesRegex(ValueError, reason):
                export(song, version)
            self.assertEqual(song, before)


if __name__ == '__main__':
    unittest.main()
