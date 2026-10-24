"""Native GP3.00 / GP4.00 export (gpexport.native_to_gp) and GP4 4.00/4.06/L4.06, GP5 5.00/5.10 read coverage.

Fixtures are PyGuitarPro models written here and imported natively; none comes from a real tab."""
import copy
import unittest

try:
    import guitarpro
    from guitarpro import models as M
except ImportError:  # pragma: no cover
    guitarpro = None

from vulturetracker import gpimport


def source(version):
    """One track, one voice, four measures |: a [1. b :| [2. c | d, using what `version` can store."""
    from tests.test_gpimport import write_repeat_gp
    gp = M.Song()
    gp.title, gp.tempo = 'Legacy export', 120
    gp.measureHeaders = [M.MeasureHeader(number=i + 1, start=960 + i * 3840) for i in range(4)]
    h = gp.measureHeaders
    h[0].isRepeatOpen, h[1].repeatAlternative, h[1].repeatClose, h[2].repeatAlternative = True, 1, 1, 2
    h[3].marker = M.Marker('Coda', M.Color(10, 20, 30))
    track = gp.tracks[0]
    track.name, track.channel.volume, track.channel.instrument = 'Lead', 128, 27
    track.strings = [M.GuitarString(i + 1, p) for i, p in enumerate((64, 59, 55, 50, 45, 40))]
    track.measures = [M.Measure(track, header) for header in h]

    def add(mi, notes, **beat_fx):
        voice = track.measures[mi].voices[0]
        start = h[mi].start + sum(b.duration.time for b in voice.beats)
        beat = M.Beat(voice, start=start, duration=M.Duration(4), status=M.BeatStatus.normal if notes else M.BeatStatus.rest)
        for key, value in beat_fx.items():
            setattr(beat.effect, key, value)
        for string, fret, fx in notes:
            note = M.Note(beat, value=fret, string=string, velocity=95, type=fx.pop('type', M.NoteType.normal))
            for key, value in fx.items():
                setattr(note.effect, key, value)
            beat.notes.append(note)
        voice.beats.append(beat)
        return beat

    add(0, [(1, 5, dict(ghostNote=True)), (2, 5, dict(letRing=True))])
    add(0, [(1, 7, dict(bend=M.BendEffect(type=M.BendType.bend, value=0,
                                         points=[M.BendPoint(0, 0), M.BendPoint(6, 4), M.BendPoint(12, 4)])))])
    add(0, [(1, 5, dict(hammer=True))])
    add(0, [(1, 7, dict(slides=[M.SlideType.shiftSlideTo]))])
    add(1, [(1, 9, {}), (3, 0, dict(type=M.NoteType.dead))])
    add(1, [(1, 5, dict(vibrato=True)), (2, 5, dict(vibrato=True))])
    add(1, [(1, 12, dict(harmonic=M.NaturalHarmonic())), (2, 12, dict(harmonic=M.NaturalHarmonic()))])
    add(1, [(1, 5, {})], fadeIn=True)
    add(2, [(2, 3, {})], slapEffect=M.SlapEffect.tapping)
    bar = M.BendEffect(type=M.BendType.bend, value=0, points=[M.BendPoint(0, 0), M.BendPoint(6, -8), M.BendPoint(12, 0)])
    add(2, [(2, 3, {})], tremoloBar=bar)
    add(2, [(2, 3, dict(type=M.NoteType.tie))])
    add(2, [])
    first = add(3, [(1, 5, {})])
    first.effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(140, duration=0))
    first.text = 'coda'
    if version == 4:
        add(3, [(1, 5, dict(staccato=True)), (2, 5, dict(palmMute=True)), (3, 5, dict(accentuatedNote=True))])
        add(3, [(1, 5, dict(trill=M.TrillEffect(fret=7, duration=M.Duration(16)))),
                (2, 5, dict(tremoloPicking=M.TremoloPickingEffect(duration=M.Duration(16))))])
        add(3, [(1, 5, dict(harmonic=M.ArtificialHarmonic(M.PitchClass(69 % 12), M.Octave.ottava)))])
        gp.lyrics.trackChoice = 1
        gp.lyrics.lines[0] = M.LyricLine(1, 'la la')
    else:
        add(3, [(1, 5, {})])
        add(3, [(1, 5, {})])
        add(3, [(1, 5, {})])
    song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), gp.title)
    song['module']['message'] = 'Legacy export fixture'
    song['score']['metadata']['comments'] = 'Legacy export fixture'
    return song


def export(song, version, raw=None):
    from vulturetracker import gpexport, tgimport
    return gpexport.native_to_gp(song, tgimport._raw(song) if raw is None else raw, version=version, channels={
        tid: dict(program=t['midi']['program'], bank=t['midi']['bank']) for tid, t in song['score']['tracks'].items()})


def plan(song):
    from vulturetracker import tablature, tgimport
    projected = tablature.repeat_projection(song, tgimport._raw(song), 44100)
    return projected.plan['events'] if projected else tablature.playback_plan(song, tgimport._raw(song))['events']


@unittest.skipIf(guitarpro is None, 'PyGuitarPro not installed')
class TestLegacyExport(unittest.TestCase):
    def test_gp3_and_gp4_round_trip_written_score_and_playback(self):
        for version in (3, 4):
            with self.subTest(version=version):
                song = source(version)
                before = copy.deepcopy(song)
                data, report = export(song, version)
                self.assertEqual(data[1:25], f'FICHIER GUITAR PRO v{version}.00'.encode())
                self.assertEqual(report['format'], f'Guitar Pro {version}.00')
                restored = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Legacy export')
                self.assertEqual(restored['score'], song['score'])
                self.assertEqual(plan(restored), plan(song))
                self.assertEqual(song, before)

    def test_version_specific_refusals_do_not_mutate(self):
        def note(song, mi=1, bi=0, ni=0):
            return song['score']['patterns'][f'm{mi}']['beats'][bi]['notes'][ni]

        def second_voice(song):
            beat = copy.deepcopy(song['score']['patterns']['m1']['beats'][0])
            beat.update(id='extra', voice=1)
            for n in beat['notes']:
                n['id'] += 'x'
            song['score']['patterns']['m1']['beats'].append(beat)

        cases = [
            ((3, 4), 'one voice per measure', second_voice),
            ((3, 4), 'cannot store minor mode',
             lambda s: [t['key'].update(mode='minor') for t in s['score']['tracks'].values()]),
            ((3, 4), 'one song-wide swing', lambda s: s['score']['measures'][1].update(swing='eighth')),
            ((3, 4), 'one song-wide swing', lambda s: [m.update(swing='sixteenth') for m in s['score']['measures']]),
            ((3, 4), "unsupported note metadata \\['heavy_accent'\\]", lambda s: note(s).update(heavy_accent=True)),
            ((3,), "unsupported note metadata \\['staccato'\\]", lambda s: note(s).update(staccato=True)),
            ((3,), "unsupported note metadata \\['accent'\\]", lambda s: note(s).update(accent=True)),
            ((3,), 'stores vibrato per beat', lambda s: note(s, 2, 1, 1).pop('vibrato')),
            ((3,), 'stores harmonic per beat', lambda s: note(s, 2, 2, 1).pop('harmonic')),
            ((3,), 'stores only a dip', lambda s: note(s, 3, 1)['tremolo_bar']['points'][1].update(position=5)),
            ((3,), 'cannot store lyrics', lambda s: s['score']['tracks']['t1'].update(lyrics=dict(from_measure=1, text='x'))),
            ((3, 4), 'cumulative ordinals', lambda s: s['score']['measures'][1].update(endings=[2])),
        ]
        for versions, reason, change in cases:
            for version in versions:
                song = source(version)
                change(song)
                before = copy.deepcopy(song)
                from vulturetracker import tgimport
                raw = tgimport._raw(song)
                with self.subTest(version=version, reason=reason), self.assertRaisesRegex(ValueError, f'Native GP{version}: .*{reason}'):
                    export(song, version, raw)
                self.assertEqual(song, before)

    def test_unsupported_version_refuses(self):
        with self.assertRaisesRegex(ValueError, 'unsupported version 2'):
            export(source(3), 2)


@unittest.skipIf(guitarpro is None, 'PyGuitarPro not installed')
class TestHeaderVariantsRead(unittest.TestCase):
    def test_gp4_400_406_l406_and_gp5_500_510_read_identically(self):
        from tests.test_gpimport import write_repeat_gp
        gp4, _ = export(source(4), 4)
        variants = {name: gp4[:1] + name.encode() + gp4[25:] for name in
                    ('FICHIER GUITAR PRO v4.00', 'FICHIER GUITAR PRO v4.06', 'FICHIER GUITAR PRO L4.06')}
        scores = {name: gpimport._native_gp_song(gpimport._read_native_gp(data), 'v')['score'] for name, data in variants.items()}
        self.assertEqual(len({repr(s) for s in scores.values()}), 1)
        song = source(5)
        gp = gpimport._read_native_gp(export(song, 5)[0])
        self.assertEqual(gp.versionTuple, (5, 0, 0))
        five_ten = gpimport._read_native_gp(write_repeat_gp(gp, 5))
        self.assertEqual(five_ten.versionTuple, (5, 1, 0))
        self.assertEqual(gpimport._native_gp_song(five_ten, 'v')['score'], song['score'])


if __name__ == '__main__':
    unittest.main()
