"""Guitar Pro import (gpimport.py): the tab written with PyGuitarPro's own writer, imported, compiled and rendered.
The timing helpers run everywhere; the rest is skipped without PyGuitarPro (pip install pyguitarpro)."""
import tempfile
import types
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from vulturetracker import gpimport

try:
    import guitarpro
    from guitarpro import models as M
except ImportError:  # pragma: no cover
    guitarpro = None


def tab(path):
    """Three measures of guitar (measure 2 repeated once) and a drum track: a tied note, a hammer-on, a full bend, a
    shift slide, vibrato, a dead note, a palm mute, a let-ring chord with a tempo change to 140, a natural harmonic,
    eighth triplets."""
    song = M.Song()
    song.tempo, song.title = 100, "gp test"
    hdrs = [M.MeasureHeader(number=i + 1, start=960 * (1 + 4 * i)) for i in range(3)]
    hdrs[1].isRepeatOpen, hdrs[1].repeatClose = True, 1
    song.measureHeaders = hdrs
    g = song.tracks[0]
    g.name = "Gtr"
    g.measures = [M.Measure(g, h) for h in hdrs]
    N, T, D = M.NoteType.normal, M.NoteType.tie, M.NoteType.dead

    def beat(m, q, value, notes, tuplet=None):
        v = m.voices[0]
        b = M.Beat(v, duration=M.Duration(value=value, tuplet=tuplet or M.Tuplet()), start=m.start + int(q * 960),
                   status=M.BeatStatus.normal)
        for string, fret, kind, eff in notes:
            n = M.Note(b, value=fret, string=string, type=kind, velocity=M.Velocities.forte)
            for k, val in eff.items():
                setattr(n.effect, k, val)
            b.notes.append(n)
        v.beats.append(b)
        return b
    m1, m2, m3 = g.measures
    beat(m1, 0, 4, [(5, 3, N, {})])
    beat(m1, 1, 4, [(5, 3, T, {})])
    beat(m1, 2, 8, [(3, 5, N, {"hammer": True})])
    beat(m1, 2.5, 8, [(3, 7, N, {})])
    bend = M.BendEffect(type=M.BendType.bend, value=4, points=[M.BendPoint(0, 0), M.BendPoint(6, 4), M.BendPoint(12, 4)])
    beat(m1, 3, 4, [(2, 8, N, {"bend": bend})])
    beat(m2, 0, 4, [(1, 5, N, {"slides": [M.SlideType.shiftSlideTo]})])
    beat(m2, 1, 4, [(1, 9, N, {"vibrato": True})])
    beat(m2, 2, 4, [(6, 0, D, {})])
    beat(m2, 3, 4, [(6, 3, N, {"palmMute": True})])
    b = beat(m3, 0, 2, [(6, 0, N, {"letRing": True}), (5, 2, N, {"letRing": True}), (4, 2, N, {"letRing": True})])
    b.effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(value=140))
    beat(m3, 2, 8, [(1, 12, N, {"harmonic": M.NaturalHarmonic()})])
    beat(m3, 2.5, 8, [])
    for k in range(3):
        beat(m3, 3 + k / 3, 8, [(1, k, N, {})], tuplet=M.Tuplet(3, 2))
    dr = M.Track(song, number=2, name="Drums", isPercussionTrack=True, strings=[M.GuitarString(n, 0) for n in range(1, 7)])
    dr.channel.channel = 9
    dr.channel.volume, dr.channel.balance = 128, 128  # the mixer's top: 0-16 steps read as 0-128
    dr.measures = [M.Measure(dr, h) for h in hdrs]
    for m in dr.measures:
        for q in range(4):
            v = m.voices[0]
            bb = M.Beat(v, duration=M.Duration(value=4), start=m.start + q * 960, status=M.BeatStatus.normal)
            bb.notes.append(M.Note(bb, value=36 if q % 2 == 0 else 38, string=1, type=N))
            bb.notes.append(M.Note(bb, value=42, string=2, type=N))
            v.beats.append(bb)
    song.tracks.append(dr)
    guitarpro.write(song, str(path))


class TestTgInterchange(unittest.TestCase):
    @staticmethod
    def xml():
        # Independent literal current-format fixture, matching upstream XML.
        return '''<?xml version="1.0" encoding="UTF-8"?>
<TuxGuitarFile><TGVersion major="2" minor="1" revision="0"/><TGSong>
<name>TG fixture</name><artist/><album/><author/><date/><copyright/><writer/><transcriber/><comments/>
<TGChannel><id>1</id><bank>0</bank><program>25</program><volume>127</volume><balance>64</balance>
<chorus>0</chorus><reverb>0</reverb><phaser>0</phaser><tremolo>0</tremolo><name>Guitar</name></TGChannel>
<TGMeasureHeader><timeSignature numerator="4" denominator="4"/><tempo>137</tempo>
<marker R="23" G="45" B="67">Verse &amp; café</marker></TGMeasureHeader><TGMeasureHeader/>
<TGTrack maxFret="29"><name>Guitar</name><channelId>1</channelId><offset>2</offset>
<color R="1" G="2" B="3"/><TGString>64</TGString><TGString>59</TGString><TGLyric from="1"/>
<TGMeasure><clef>bass</clef><keySignature>8</keySignature>
<TGBeat><preciseStart>2882880</preciseStart><text>Literal &lt;tag&gt; &amp; café</text>
<voice direction="up"><duration value="2"/><note string="1" value="0" velocity="79"><ghostNote/></note>
<note string="2" value="0"/></voice><voice empty="true"><duration value="4"/></voice></TGBeat>
<TGBeat><preciseStart>8648640</preciseStart><voice><duration value="2"/>
<note string="1" value="2" velocity="95"><hammer/></note></voice><voice empty="true"><duration value="4"/></voice></TGBeat>
</TGMeasure><TGMeasure>
<TGBeat><preciseStart>14414400</preciseStart><voice><duration value="4"/>
<note string="1" value="2" velocity="95" tiedNote="true"/></voice><voice direction="down"><duration value="2"/>
<note string="2" value="0" velocity="47"/></voice></TGBeat>
<TGBeat><preciseStart>17297280</preciseStart><voice><duration value="4" dotted="dotted"/>
<note string="1" value="3" velocity="95"><accentuatedNote/><bend><point position="0" value="0"/>
<point position="6" value="4"/><point position="12" value="0"/></bend></note></voice>
<voice empty="true"><duration value="4"/></voice></TGBeat>
<TGBeat><preciseStart>21621600</preciseStart><voice><duration value="4" dotted="dotted"/>
<note string="1" value="4" velocity="111"><vibrato/><tremoloBar><point position="0" value="0"/>
<point position="6" value="-4"/><point position="12" value="0"/></tremoloBar></note></voice>
<voice empty="true"><duration value="4"/></voice></TGBeat></TGMeasure></TGTrack></TGSong></TuxGuitarFile>'''

    @staticmethod
    def archive(xml, version=b'TuxGuitar_file_format 2.0'):
        import io
        import zipfile
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('version.txt', version)
            z.writestr('content.xml', xml.encode('utf-8'))
        return out.getvalue()

    def test_ascii_tab_matches_tuxguitar_writer_byte_for_byte(self):
        from vulturetracker.asciitab import tg_to_ascii
        # TuxGuitar 2.1.0's own ASCIITabOutputStream on this fixture (scratch/native-ascii-oracle, CRLF -> LF):
        # the inherited 4/4 header, beat widths from tick lengths, h only before a following note, 3b5 from 0-4-0.
        expected = ('Title: TG fixture\nArtist: \nAlbum: \nAuthor: \n\n\nTrack 1: Guitar\n\n'
                    '                             \nE|-0----2----|-2---3b5--4----|\nB|-0---------|-0-------------|\n\n\n\n')
        self.assertEqual(tg_to_ascii(self.archive(self.xml())), expected)

    @staticmethod
    def semantics(song):
        from vulturetracker import tgimport, tablature
        view = tablature.authoring_view(song, tgimport._raw(song))
        positions = []
        for p in view['positions']:
            if p['kind'] != 'note':
                continue
            fields = ('at', 'end', 'voice', 'pitch', 'string', 'fret', 'velocity', 'ghost', 'accent',
                      'heavy_accent', 'hammer', 'vibrato', 'bend', 'tremolo_bar', 'harmonic',
                      'trill', 'tremolo_picking', 'let_ring', 'fade_in', 'tapping', 'slapping', 'popping', 'tied_in', 'tied_out')
            positions.append({k: p[k] for k in fields if k in p})
        beats = [{k: b[k] for k in ('track', 'voice', 'at', 'written', 'text', 'stem', 'stroke', 'pick_stroke', 'chord') if k in b}
                 for spec in song['score']['patterns'].values() for b in spec['beats']]
        return (song['module']['tempo'], song['score']['tracks'], song['score']['measures'], beats, positions)

    def test_literal_xml_semantic_roundtrip_and_inherited_velocity(self):
        from vulturetracker import tgimport, tablature
        song, warnings = tgimport.read_tg(self.archive(self.xml()))
        self.assertIn('placeholders', warnings[0])
        track = song['score']['tracks']['t1']
        self.assertEqual((track['key'], track['clef'], track['midi']),
                         ({'fifths': -1, 'mode': 'major'}, 'bass', {'program': 25, 'bank': 0}))
        first = song['score']['patterns']['m1']['beats'][0]
        self.assertEqual([n['velocity'] for n in first['notes']], [79, 79])
        self.assertEqual(first['text'], 'Literal <tag> & café')
        self.assertEqual(song['score']['measures'][0]['marker'], {'title': 'Verse & café', 'color': '#172d43'})
        before = self.semantics(song)
        data, report = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': track['midi']})
        restored, _ = tgimport.read_tg(data)
        self.assertEqual(self.semantics(restored), before)
        self.assertEqual((report['tracks'], report['measures'], report['notes']), (1, 2, 7))
        events = tablature.playback_plan(song, tgimport._raw(song))['events']
        self.assertEqual([e['velocity'] for e in events if e['type'] == 'note_on'], [63, 79, 95, 47, 111, 111])
        # Omitted velocity resets to 95 for each voice, then inherits within its chord.
        default, _ = tgimport.read_tg(self.archive(self.xml().replace('velocity="79"', '')))
        self.assertEqual([n['velocity'] for n in default['score']['patterns']['m1']['beats'][0]['notes']], [95, 95])

    def test_exact_thirteen_tuplets_and_two_voice_rest_distinction(self):
        from vulturetracker import tgimport
        import xml.etree.ElementTree as ET
        root = ET.fromstring(self.xml())
        track = root.find('.//TGTrack')
        for old in list(track.findall('TGMeasure')):
            track.remove(old)
        headers = root.find('TGSong').findall('TGMeasureHeader')
        root.find('TGSong').remove(headers[1])
        m = ET.SubElement(track, 'TGMeasure')
        for i in range(13):
            b = ET.SubElement(m, 'TGBeat')
            ET.SubElement(b, 'preciseStart').text = str(tgimport.QUARTER + i * 887040)
            v = ET.SubElement(b, 'voice', {'empty': 'false'} if i == 2 else {})
            d = ET.SubElement(v, 'duration', {'value': '8'})
            ET.SubElement(d, 'divisionType', {'enters': '13', 'times': '8'})
            if i != 2:
                ET.SubElement(v, 'note', {'string': '1', 'value': '0', 'velocity': '79'})
            other = ET.SubElement(b, 'voice', {'empty': 'true'})
            ET.SubElement(other, 'duration', {'value': '4'})
        song, _ = tgimport.read_tg(self.archive(ET.tostring(root, encoding='unicode')))
        beats = song['score']['patterns']['m1']['beats']
        self.assertEqual(len(beats), 13)
        self.assertEqual([Fraction(*b['at']) for b in beats], [Fraction(i * 4, 13) for i in range(13)])
        self.assertEqual(beats[2]['notes'], [])
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
        self.assertEqual(self.semantics(tgimport.read_tg(data)[0]), self.semantics(song))

    def test_unsupported_source_and_hostile_archive_refuse_without_outputs(self):
        from vulturetracker import tgimport
        mutations = [
            ('<artist/>', '', 'expected one artist'),
            ('<TGMeasureHeader/>', '<TGMeasureHeader><tempo>31</tempo></TGMeasureHeader>', '32..255'),
            ('<TGMeasureHeader/>', '<TGMeasureHeader><repeatClose>101</repeatClose></TGMeasureHeader>', '0..100'),
            ('<chorus>0</chorus>', '<chorus>100</chorus>', 'non-neutral'),
            ('<bank>0</bank>', '<bank>128</bank>', 'percussion'),
            ('<ghostNote/>', '<ghostNote/><accentuatedNote/>', 'normalized'),
            ('<ghostNote/>', '<fadeIn value="1"/>', 'unsupported'),
            ('<ghostNote/>', '<harmonic type="natural" data="0"/>', 'unsupported'),
            ('<keySignature>8</keySignature>', '<keySignature>15</keySignature>', '0..14'),
            ('<duration value="2"/>', '<duration value="8"><divisionType enters="17" times="8"/></duration>', 'exactly representable')]
        for old, new, error in mutations:
            with self.subTest(error=error), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                src = folder / 'input.tg'
                src.write_bytes(self.archive(self.xml().replace(old, new, 1)))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaisesRegex(ValueError, error):
                        tgimport.import_tg(src, folder / 'song.yaml', folder / 'samples')
                self.assertEqual(list(folder.iterdir()), [src])
        # TuxGuitar opens a measure's first beat at the measure start (updatePreciseStart): an off-origin first
        # beat imports where TuxGuitar plays it, with a notice, rather than refusing.
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            src = folder / 'input.tg'
            src.write_bytes(self.archive(self.xml().replace('<preciseStart>2882880</preciseStart>',
                                                            '<preciseStart>2882881</preciseStart>', 1)))
            _, warnings = tgimport.import_tg(src, folder / 'song.yaml', folder / 'samples')
            self.assertTrue(any('moved from quarter' in w for w in warnings), warnings)
        with self.assertRaisesRegex(ValueError, 'only TuxGuitar'):
            tgimport.read_tg(self.archive(self.xml(), b'TuxGuitar_file_format 2.1'))
        with self.assertRaisesRegex(ValueError, 'DTD/entity'):
            tgimport.read_tg(self.archive(self.xml().replace('<TuxGuitarFile>', '<!DOCTYPE x><TuxGuitarFile>', 1)))
        with self.assertRaises(ValueError):
            tgimport.read_tg(b'not a zip')
        # ET can sniff UTF-16 from NULs even after a permissive UTF-8 decode.
        # The format is UTF-8: refuse before XML entity/DTD interpretation.
        import io
        import zipfile
        xml = '<!DOCTYPE TuxGuitarFile [<!ENTITY tiny "ok">]><TuxGuitarFile>&tiny;</TuxGuitarFile>'
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr('version.txt', tgimport.VERSION)
            z.writestr('content.xml', xml.encode('utf-16-le'))
        with self.assertRaisesRegex(ValueError, 'UTF-8|NUL'):
            tgimport.read_tg(out.getvalue())

    def test_export_refuses_unrepresentable_native_state_and_does_not_mutate(self):
        import copy
        from vulturetracker import tgimport
        song, _ = tgimport.read_tg(self.archive(self.xml()))
        before = copy.deepcopy(song)
        for field, value, error in (('velocity', None, 'explicit nonzero'), ('volume', 23, 'IT volume'),
                                    ('spelling', {'step': 'E', 'alter': 2}, 'neither the key spelling'),
                                    ('instrument', 1, 'instrument command')):
            candidate = copy.deepcopy(song)
            note = candidate['score']['patterns']['m1']['beats'][0]['notes'][0]
            if value is None:
                note.pop(field)
                note.pop('ghost')
            else:
                note[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                tgimport.native_to_tg(candidate, tgimport._raw(candidate), channels={'t1': {'program': 25, 'bank': 0}})
        raw = tgimport._raw(song)
        raw[1].rows[-1][1].effect = 24
        raw[1].rows[-1][1].param = 64
        with self.assertRaisesRegex(ValueError, 'residual tracker'):
            tgimport.native_to_tg(song, raw, channels={'t1': {'program': 25, 'bank': 0}})
        with self.assertRaisesRegex(ValueError, 'every track'):
            tgimport.native_to_tg(song, tgimport._raw(song), channels={})
        candidate = copy.deepcopy(song)
        voice_one = next(b for b in candidate['score']['patterns']['m2']['beats'] if b['voice'] == 1)
        voice_one['text'] = 'Only the second voice'
        with self.assertRaisesRegex(ValueError, 'per-voice annotation ownership'):
            tgimport.native_to_tg(candidate, tgimport._raw(candidate), channels={'t1': {'program': 25, 'bank': 0}})
        candidate = copy.deepcopy(song)
        candidate['score']['tracks']['t1']['key']['mode'] = 'minor'
        with self.assertRaisesRegex(ValueError, 'minor-mode'):
            tgimport.native_to_tg(candidate, tgimport._raw(candidate), channels={'t1': {'program': 25, 'bank': 0}})
        self.assertEqual(song, before)

    def test_harmonic_type_data_roundtrip_preserves_authored_and_performed_layers(self):
        from vulturetracker import tgimport, tablature
        import io
        import zipfile
        import xml.etree.ElementTree as ET
        for tag, kind in (('N.H', 'natural'), ('A.H', 'artificial'), ('T.H', 'tapped'),
                          ('P.H', 'pinch'), ('S.H', 'semi')):
            for value in range(6):
                with self.subTest(kind=kind, data=value):
                    xml = self.xml().replace('<ghostNote/>', f'<ghostNote/><harmonic type="{tag}" data="{value}"/>')
                    song, _ = tgimport.read_tg(self.archive(xml))
                    note = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                    self.assertEqual(note['harmonic'], {'type': kind, 'data': value})
                    events = tablature.playback_plan(song, tgimport._raw(song))['events']
                    first = next(e for e in events if e['type'] == 'note_on')
                    # Source velocity 79 becomes 63 before harmonic layer attenuation.
                    self.assertEqual(first['layers'][-1]['velocity'], 63)
                    if kind == 'semi':
                        self.assertEqual(first['layers'][0], {'pitch': 66, 'velocity': 15})
                    data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                    restored, _ = tgimport.read_tg(data)
                    self.assertEqual(self.semantics(restored), self.semantics(song))
                    self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], events)
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        harmonic = ET.fromstring(z.read('content.xml')).find('.//harmonic')
                    self.assertEqual(harmonic.attrib, {'type': tag, 'data': str(value)})
        # Native omitted data has a defined zero default; TG always writes it.
        note.pop('harmonic')
        note['harmonic'] = {'type': 'artificial'}
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
        restored, _ = tgimport.read_tg(data)
        self.assertEqual(restored['score']['patterns']['m1']['beats'][0]['notes'][0]['harmonic'],
                         {'type': 'artificial', 'data': 0})

    def test_harmonic_malformed_source_refuses_before_publication(self):
        from vulturetracker import tgimport
        for harmonic in ('<harmonic type="N.H"/>', '<harmonic type="N.H" data="-1"/>',
                         '<harmonic type="N.H" data="6"/>', '<harmonic type="N.H" data="0.0"/>',
                         '<harmonic type="N.H" data="true"/>', '<harmonic type="natural" data="0"/>',
                         '<harmonic type="N.H" data="0">lost text</harmonic>',
                         '<harmonic type="N.H" data="0" other="1"/>',
                         '<harmonic type="N.H" data="0"><unknown/></harmonic>',
                         '<harmonic type="N.H" data="0"/><harmonic type="N.H" data="0"/>'):
            with self.subTest(harmonic=harmonic), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / 'invalid.tg'
                src.write_bytes(self.archive(self.xml().replace('<ghostNote/>', harmonic)))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                self.assertEqual(list(Path(tmp).iterdir()), [src])

    def test_repetition_roundtrip_keeps_written_notes_and_harmonic_metadata(self):
        import io
        import zipfile
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport, tablature
        for tag, field, rates in (('trill', 'trill', (4, 8, 16, 32, 64)),
                                  ('tremoloPicking', 'tremolo_picking', (8, 16, 32))):
            for value in rates:
                with self.subTest(effect=field, value=value):
                    effect = f'<{tag} duration="{value}"' + (' fret="7"' if tag == 'trill' else '') + '/>'
                    xml = self.xml().replace('<ghostNote/>', '<ghostNote/><harmonic type="S.H" data="0"/>' + effect)
                    song, warnings = tgimport.read_tg(self.archive(xml))
                    note = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                    self.assertEqual(note[field], dict(value=value, **({'fret': 7} if tag == 'trill' else {})))
                    self.assertEqual(note['harmonic'], dict(type='semi', data=0))
                    self.assertEqual(len(warnings), 1)
                    events = tablature.playback_plan(song, tgimport._raw(song))['events']
                    pulses = [e for e in events if e['type'] == 'note_on' and e.get('source_id') == 'o1/t1_b1_v1_n1']
                    self.assertEqual(len(pulses), value // 2)
                    self.assertTrue(all(e['velocity'] == 63 and 'layers' not in e for e in pulses))
                    data, report = tgimport.native_to_tg(song, tgimport._raw(song),
                                                        channels={'t1': {'program': 25, 'bank': 0}})
                    restored, _ = tgimport.read_tg(data)
                    self.assertEqual(self.semantics(restored), self.semantics(song))
                    self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], events)
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        content = z.read('content.xml')
                        root = ET.fromstring(content)
                    self.assertEqual(len(root.findall('.//note')), report['notes'])
                    self.assertNotIn(b'pulse', content)
                    self.assertEqual(root.find('.//' + tag).get('duration'), str(value))

    def test_repetition_tg_reader_normalizes_in_source_order_with_notice(self):
        from vulturetracker import tgimport
        effects = ('<vibrato/><deadNote/><slide/><hammer/>'
                   '<bend><point position="0" value="0"/></bend>'
                   '<tremoloBar><point position="0" value="0"/></tremoloBar>'
                   '<trill fret="7" duration="32"/><tremoloPicking duration="16"/>')
        # Child order is irrelevant: the TG reader's fixed setter order wins.
        for value in (effects, '<tremoloPicking duration="16"/>' + effects.replace('<tremoloPicking duration="16"/>', '')):
            song, warnings = tgimport.read_tg(self.archive(self.xml().replace('<ghostNote/>', value)))
            note = song['score']['patterns']['m1']['beats'][0]['notes'][0]
            self.assertEqual(note['tremolo_picking'], {'value': 16})
            for field in ('trill', 'vibrato', 'dead', 'slide', 'hammer', 'bend', 'tremolo_bar'):
                self.assertNotIn(field, note)
            notice = next(w for w in warnings if 'normalized repetition conflicts' in w)
            self.assertIn("'trill': {'value': 32, 'fret': 7}", notice)
            self.assertIn(notice, song['module']['message'])

    def test_repetition_malformed_tg_refuses_before_publication(self):
        from vulturetracker import tgimport
        for effect in ('<trill duration="16"/>', '<trill fret="-1" duration="16"/>',
                       '<trill fret="30" duration="16"/>', '<trill fret="7" duration="2"/>',
                       '<trill fret="7" duration="16.0"/>', '<trill fret="7" duration="16" dots="1"/>',
                       '<trill fret="7" duration="16"><divisionType enters="3" times="2"/></trill>',
                       '<trill fret="7" duration="16">text</trill>', '<tremoloPicking duration="64"/>',
                       '<tremoloPicking duration="16" fret="7"/>',
                       '<tremoloPicking duration="16"/><tremoloPicking duration="16"/>'):
            with self.subTest(effect=effect), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / 'invalid.tg'
                src.write_bytes(self.archive(self.xml().replace('<ghostNote/>', effect)))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                self.assertEqual(list(Path(tmp).iterdir()), [src])

    @staticmethod
    def ring_xml(kind='other', head_effects='', reverse=False):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(TestTgInterchange.xml())
        song = root.find('TGSong')
        song.remove(song.findall('TGMeasureHeader')[1])
        song.find('TGMeasureHeader/tempo').text = '120'
        track = song.find('TGTrack')
        track.find('offset').text = '0'
        for measure in track.findall('TGMeasure'):
            track.remove(measure)
        measure = ET.SubElement(track, 'TGMeasure')
        first = '<note string="1" value="5" velocity="95"><letRing/>' + head_effects + '</note>'
        other = '<note string="2" value="3" velocity="95"><letRing/></note>'
        chord = ['<note string="1" value="5" velocity="95"><letRing/></note>',
                 '<note string="2" value="3" velocity="95"/>']
        specs = [first, other]
        if kind == 'tie':
            specs = [first, '<note string="1" value="5" velocity="31" tiedNote="true"><letRing/></note>', other]
        elif kind == 'overlap':
            specs = [first, '<note string="1" value="7" velocity="95"/>']
        elif kind == 'chord':
            specs = [first, ''.join(reversed(chord) if reverse else chord)]
        for i, notes in enumerate(specs):
            beat = ET.SubElement(measure, 'TGBeat')
            ET.SubElement(beat, 'preciseStart').text = str(2882880 * (i + 1))
            voice = ET.SubElement(beat, 'voice')
            ET.SubElement(voice, 'duration', value='4')
            for note in ET.fromstring('<notes>' + notes + '</notes>'):
                voice.append(note)
            empty = ET.SubElement(beat, 'voice', empty='true')
            ET.SubElement(empty, 'duration', value='4')
        return ET.tostring(root, encoding='unicode')

    def test_let_ring_tg_roundtrip_preserves_notes_ties_and_chord_order(self):
        import io
        import zipfile
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport, tablature
        for kind, end in (('other', 2), ('tie', 3), ('chord', 1)):
            with self.subTest(kind=kind):
                song, _ = tgimport.read_tg(self.archive(self.ring_xml(kind)))
                original = self.semantics(song)
                events = tablature.playback_plan(song, tgimport._raw(song))['events']
                head = next(e for e in events if e['type'] == 'note_off' and e['note'] == 't1_b1_v1_n1')
                self.assertEqual(head['at'], [end, 1])
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                restored, _ = tgimport.read_tg(data)
                self.assertEqual(self.semantics(restored), original)
                self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], events)
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    root = ET.fromstring(z.read('content.xml'))
                self.assertGreaterEqual(len(root.findall('.//letRing')), 2)
                if kind == 'chord':
                    self.assertEqual([n.get('string') for n in root.findall('.//TGBeat')[1].findall('./voice/note')], ['1', '2'])
        # The technique itself does not require authored velocity.
        song, _ = tgimport.read_tg(self.archive(self.ring_xml()))
        song['score']['patterns']['m1']['beats'][0]['notes'][0].pop('velocity')
        tablature.playback_plan(song, tgimport._raw(song))

    def test_let_ring_tg_gate_conflicts_normalize_with_source_notice(self):
        from vulturetracker import tgimport, tablature
        for tags in ('<palmMute/>', '<staccato/>', '<staccato/><palmMute/>'):
            with self.subTest(tags=tags):
                song, warnings = tgimport.read_tg(self.archive(self.ring_xml(head_effects=tags)))
                note = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                self.assertTrue(note['let_ring'])
                self.assertNotIn('palm_mute', note)
                self.assertNotIn('staccato', note)
                notice = next(w for w in warnings if 'normalized let-ring conflicts' in w)
                self.assertIn(notice, song['module']['message'])
                events = tablature.playback_plan(song, tgimport._raw(song))['events']
                self.assertEqual(next(e['at'] for e in events if e['type'] == 'note_off' and e['note'] == note['id']), [2, 1])
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                restored, _ = tgimport.read_tg(data)
                self.assertIn(notice, restored['module']['message'])

    def test_let_ring_tg_ordinary_overlap_retains_held_identity(self):
        from vulturetracker import tgimport, tablature
        for xml in (self.ring_xml('overlap'), self.ring_xml('chord', reverse=True)):
            song, _ = tgimport.read_tg(self.archive(xml))
            plan = tablature.playback_plan(song, tgimport._raw(song))
            self.assertTrue(any(e.get('hold') for e in plan['events']))
            data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
            restored, _ = tgimport.read_tg(data)
            self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], plan['events'])

    def test_swing_tg_headers_roundtrip_written_and_performed_notes(self):
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport, tablature
        for mode, value, second, end in (('none', 8, Fraction(1, 2), Fraction(1)),
                                        ('eighth', 8, Fraction(2, 3), Fraction(1)),
                                        ('sixteenth', 16, Fraction(1, 3), Fraction(1, 2))):
            with self.subTest(mode=mode):
                root = ET.fromstring(self.ring_xml())
                ET.SubElement(root.find('.//TGMeasureHeader'), 'tripletFeel').text = mode
                for i, beat in enumerate(root.findall('.//TGBeat')):
                    beat.find('preciseStart').text = str(tgimport.QUARTER * (1 + Fraction(i * 4, value)))
                    beat.find('voice/duration').set('value', str(value))
                    for note in beat.findall('voice/note'):
                        note.remove(note.find('letRing'))
                song, _ = tgimport.read_tg(self.archive(ET.tostring(root, encoding='unicode')))
                self.assertEqual(song['score']['measures'][0]['swing'], mode)
                plan = tablature.playback_plan(song, tgimport._raw(song))
                self.assertEqual([Fraction(*e['at']) for e in plan['events']], [0, second, second, end])
                self.assertEqual(song['score']['patterns']['m1']['beats'][1]['at'], [1, value // 4])
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                restored, _ = tgimport.read_tg(data)
                self.assertEqual(restored['score']['measures'][0]['swing'], mode)
                self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], plan['events'])

    def test_swing_tg_malformed_feel_refuses_before_publication(self):
        from vulturetracker import tgimport
        for field in ('<tripletFeel>shuffle</tripletFeel>', '<tripletFeel rate="8">eighth</tripletFeel>',
                      '<tripletFeel>eighth</tripletFeel><tripletFeel>none</tripletFeel>'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / 'invalid.tg'
                src.write_bytes(self.archive(self.ring_xml().replace('</TGMeasureHeader>', field + '</TGMeasureHeader>')))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                self.assertEqual(list(Path(tmp).iterdir()), [src])

    def test_grace_tg_fields_and_performed_events_roundtrip(self):
        from vulturetracker import tgimport, tablature
        for value in (16, 32, 64):
            for transition in ('none', 'slide', 'bend', 'hammer'):
                xml = self.ring_xml().replace('<letRing />',
                    f'<grace fret="2" duration="{value}" dynamic="47" transition="{transition}" onBeat="true" dead="false"/>', 1)
                song, _ = tgimport.read_tg(self.archive(xml))
                authored = song['score']['patterns']['m1']['beats'][0]['notes'][0]['grace']
                self.assertEqual(authored, dict(fret=2, value=value, velocity=47, transition=transition, on_beat=True, dead=False))
                plan = tablature.playback_plan(song, tgimport._raw(song))
                attacks = [e for e in plan['events'] if e['type'] == 'note_on']
                self.assertEqual(attacks[0]['role'], 'grace')
                self.assertEqual(Fraction(*attacks[1]['at']), Fraction(4, value))
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                restored, _ = tgimport.read_tg(data)
                self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], plan['events'])

    def test_grace_tg_malformed_fields_refuse_before_publication(self):
        from vulturetracker import tgimport
        grace = '<grace fret="2" duration="16" dynamic="47" transition="none" onBeat="true" dead="false"/>'
        invalid = [grace.replace(old, new) for old, new in (
            ('duration="16"', 'duration="8"'), ('dynamic="47"', 'dynamic="128"'),
            ('fret="2"', 'fret="-1"'), ('transition="none"', 'transition="unknown"'),
            ('onBeat="true"', 'onBeat="yes"'), ('dead="false"', 'dead="0"'),
            ('/>', '>text</grace>'))] + [grace + grace]
        for value in invalid:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / 'invalid.tg'
                src.write_bytes(self.archive(self.ring_xml().replace('<letRing />', value, 1)))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                self.assertEqual(list(Path(tmp).iterdir()), [src])

    def test_let_ring_tg_malformed_flags_refuse_before_publication(self):
        from vulturetracker import tgimport
        invalid = [self.ring_xml().replace('<letRing />', value, 1)
                    for value in ('<letRing value="false"/>', '<letRing>text</letRing>', '<letRing/><letRing/>')]
        for xml in invalid:
            with self.subTest(xml=xml[-180:]), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / 'invalid.tg'
                src.write_bytes(self.archive(xml))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                self.assertEqual(list(Path(tmp).iterdir()), [src])

    def test_measure_tempos_roundtrip_through_raw_commands_and_real_publication(self):
        import yaml
        from vulturetracker import api, tgimport, tablature
        xml = self.xml().replace('<TGMeasureHeader/>', '<TGMeasureHeader><tempo>60</tempo></TGMeasureHeader>')
        song, _ = tgimport.read_tg(self.archive(xml))
        self.assertEqual(song['patterns']['m2']['data'], '00: ... .. ... T3C\n')
        raw = tgimport._raw(song)
        before = tablature.playback_plan(song, raw)
        self.assertEqual(before['tempos'], [{'at': [0, 1], 'bpm': 137}, {'at': [4, 1], 'bpm': 60}])
        data, _ = tgimport.native_to_tg(song, raw, channels={'t1': {'program': 25, 'bank': 0}})
        restored, _ = tgimport.read_tg(data)
        self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], before['events'])
        self.assertEqual(restored['patterns']['m2']['data'], song['patterns']['m2']['data'])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            src = folder / 'tempo.tg'
            src.write_bytes(data)
            imported, _ = tgimport.import_tg(src, folder / 'song.yaml', folder / 'samples')
            self.assertEqual(yaml.safe_load((folder / 'song.yaml').read_text(encoding='utf-8')), imported)
            self.assertEqual(api.prepare_playback(folder / 'song.yaml')['plan']['tempos'], before['tempos'])
            self.assertEqual(len(list((folder / 'samples').glob('*.wav'))), 7)

    def test_tempo_export_refuses_midmeasure_noops_and_mixed_residuals(self):
        from vulturetracker import tgimport
        from vulturetracker.model import Cell
        song, _ = tgimport.read_tg(self.archive(self.xml()))
        for value in (137, 60):
            raw = tgimport._raw(song)
            raw[0].rows[1][0] = Cell(effect=20, param=value)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'midmeasure tempo'):
                tgimport.native_to_tg(song, raw, channels={'t1': {'program': 25, 'bank': 0}})
        raw = tgimport._raw(song)
        raw[0].rows[0][0] = Cell(effect=20, param=60, volcmd=32)
        with self.assertRaisesRegex(ValueError, 'residual tracker'):
            tgimport.native_to_tg(song, raw, channels={'t1': {'program': 25, 'bank': 0}})
        # Beat units read as TGTempo plays them: 60 eighths are 30 quarters (outside the tracker's 32..255),
        # 60 dotted quarters are 90.
        with self.assertRaisesRegex(ValueError, 'outside 32..255'):
            tgimport.read_tg(self.archive(self.xml().replace('<tempo>137</tempo>', '<tempo base="8">60</tempo>')))
        dotted, _ = tgimport.read_tg(self.archive(self.xml().replace('<tempo>137</tempo>', '<tempo dotted="true">60</tempo>')))
        self.assertEqual(dotted['module']['tempo'], 90)

    def test_signature_mapping_midi_banks_and_shared_channel_refusal(self):
        import copy
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport
        for key in range(15):
            song, _ = tgimport.read_tg(self.archive(self.xml().replace('<keySignature>8', f'<keySignature>{key}')))
            self.assertEqual(song['score']['tracks']['t1']['key']['fifths'], key if key < 8 else 7 - key)
        song, _ = tgimport.read_tg(self.archive(self.xml().replace('<bank>0', '<bank>16383')))
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 16383}})
        self.assertEqual(tgimport.read_tg(data)[0]['score']['tracks']['t1']['midi']['bank'], 16383)
        root = ET.fromstring(self.xml())
        root.find('TGSong').append(copy.deepcopy(root.find('.//TGTrack')))
        with self.assertRaisesRegex(ValueError, 'track 2: shared MIDI-channel'):
            tgimport.read_tg(self.archive(ET.tostring(root, encoding='unicode')))

    def test_real_import_uses_shared_publication_and_preserves_saved_midi(self):
        from vulturetracker import tgimport, api
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / 'fixture.tg'
            source.write_bytes(self.archive(self.xml()))
            song, warnings = tgimport.import_tg(source, folder / 'song.yaml', folder / 'samples')
            self.assertEqual(api.load(folder / 'song.yaml'), song)
            self.assertEqual(len(list((folder / 'samples').glob('*.wav'))), 7)
            self.assertEqual(song['score']['tracks']['t1']['midi'], {'program': 25, 'bank': 0})
            self.assertEqual(api.prepare_playback(folder / 'song.yaml')['plan']['duration']['quarters'], [8, 1])
            with self.assertRaisesRegex(ValueError, 'fresh destination'):
                tgimport.import_tg(source, folder / 'song.yaml', folder / 'samples')


class TestTiming(unittest.TestCase):
    def test_grid_and_speed(self):
        self.assertEqual(gpimport.grid_for({0, 960, 240, 480}), 4)          # sixteenths
        self.assertEqual(gpimport.grid_for({0, 320, 240}), 12)              # triplet eighths and sixteenths
        self.assertEqual(gpimport.speed_tempo(120, 4)[:2], (6, 120))         # 24 ticks a quarter: tempo = BPM
        self.assertEqual(gpimport.speed_tempo(100, 6)[:2], (4, 100))
        s, t, exact = gpimport.speed_tempo(200, 16)                         # 16 rows a quarter: more ticks per row
        self.assertTrue(32 <= t <= 255 and abs(t - exact) / exact < 0.005, (s, t, exact))

    def test_repeats_and_alternate_endings(self):
        h = lambda o=False, c=-1, alt=0: types.SimpleNamespace(isRepeatOpen=o, repeatClose=c, repeatAlternative=alt)  # noqa: E731
        # |: 0 1 [1. 2 :| [2. 3 | 4
        hs = [h(o=True), h(), h(c=1, alt=1), h(alt=2), h()]
        self.assertEqual(gpimport.play_order(hs), [0, 1, 2, 0, 1, 3, 4])
        self.assertEqual(gpimport.play_order([h(), h(o=True), h(c=2)]), [0, 1, 2, 1, 2, 1, 2])  # played three times


def repeat_gp_tab(configs):
    """Whole-measure notes with explicit GP repeat headers, no performance expansion."""
    song = M.Song()
    song.title, song.tempo = 'Repeat fixture', 120
    song.measureHeaders = [M.MeasureHeader(number=i + 1, start=960 + i * 3840) for i in range(len(configs))]
    track = song.tracks[0]
    track.strings, track.channel.volume = [M.GuitarString(1, 64)], 128
    track.channel.instrument = 25
    track.measures = [M.Measure(track, header) for header in song.measureHeaders]
    for i, (header, config) in enumerate(zip(song.measureHeaders, configs)):
        for key, value in config.items():
            setattr(header, key, value)
        voice = track.measures[i].voices[0]
        beat = M.Beat(voice, start=header.start, duration=M.Duration(value=1), status=M.BeatStatus.normal)
        beat.notes.append(M.Note(beat, value=5 + i, string=1, velocity=95, type=M.NoteType.normal))
        voice.beats.append(beat)
    return song


def write_repeat_gp(song, version):
    """TG-source GP5 header order, scoped fixture writer; production never monkeypatches."""
    import io
    from guitarpro.gp5 import GP5File

    def header_values(writer, header, flags):
        writer.writeU8(flags)
        if flags & 1:
            writer.writeI8(header.timeSignature.numerator)
        if flags & 2:
            writer.writeI8(header.timeSignature.denominator.value)
        if flags & 8:
            writer.writeU8(header.repeatClose + 1)
        if flags & 0x20:
            writer.writeMarker(header.marker)
        if flags & 0x40:
            writer.writeI8(header.keySignature.value[0])
            writer.writeI8(header.keySignature.value[1])
        if flags & 3:
            for beam in header.timeSignature.beams:
                writer.writeU8(beam)
        if flags & 0x10:
            writer.writeRepeatAlternative(header.repeatAlternative)
        else:
            writer.placeholder(1)
        writer.writeU8(header.tripletFeel.value)

    output = io.BytesIO()
    with patch.object(GP5File, 'writeMeasureHeaderValues', header_values):
        guitarpro.write(song, output, version={3: (3, 0, 0), 4: (4, 0, 6), 5: (5, 1, 0)}[version])
    return output.getvalue()


@unittest.skipIf(guitarpro is None, 'PyGuitarPro not installed')
class TestRepeatInterchange(unittest.TestCase):
    def native(self, source, version):
        data = write_repeat_gp(source, version)
        return gpimport._native_gp_song(gpimport._read_native_gp(data), 'Repeats')

    def plan(self, song):
        from vulturetracker import tablature, tgimport
        projection = tablature.repeat_projection(song, tgimport._raw(song))
        return projection.plan if projection else tablature.playback_plan(song, tgimport._raw(song))

    def events(self, song):
        return [{key: e[key] for key in ('type', 'at', 'frame', 'seconds', 'pitch', 'velocity', 'ch', 'source_order')}
                for e in self.plan(song)['events']]

    def test_gp_versions_keep_authored_headers_and_source_controller_visits(self):
        from vulturetracker import tgimport
        configs = [dict(isRepeatOpen=True), dict(repeatAlternative=1), dict(repeatClose=1),
                   dict(repeatAlternative=2), {}]
        for version in (3, 4, 5):
            with self.subTest(version=version):
                song = self.native(repeat_gp_tab(configs), version)
                self.assertEqual(len(song['orders']), 5)
                self.assertEqual(song['score']['measures'][1]['endings'], [1])
                self.assertEqual(song['score']['measures'][3]['endings'], [2])
                plan = self.plan(song)
                self.assertEqual([o['source_order'] for o in plan['occurrences']], [0, 1, 2, 0, 3, 4])
                data, report = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                restored, _ = tgimport.read_tg(data)
                self.assertEqual(restored['score']['measures'], song['score']['measures'])
                self.assertEqual(self.events(restored), self.events(song))
                self.assertEqual(report['measures'], 5)

    def test_gp34_ordinal_masks_include_opening_header_and_never_xor_old_bits(self):
        for version in (3, 4):
            for configs, masks in [
                ([dict(isRepeatOpen=True, repeatAlternative=1), dict(repeatAlternative=2, repeatClose=1), {}], [[1], [2], []]),
                ([dict(isRepeatOpen=True), dict(repeatAlternative=3), dict(repeatAlternative=1, repeatClose=1), {}],
                 [[], [1, 2], [], []])]:
                with self.subTest(version=version, masks=masks):
                    song = self.native(repeat_gp_tab(configs), version)
                    self.assertEqual([m.get('endings', []) for m in song['score']['measures']], masks)

    def test_gp5_endings_follow_time_signature_bytes(self):
        source = repeat_gp_tab([dict(isRepeatOpen=True, repeatAlternative=2), dict(repeatClose=1), {}])
        source.measureHeaders[0].timeSignature.beams = [3, 2, 2, 1]
        song = self.native(source, 5)
        self.assertEqual(song['score']['measures'][0]['endings'], [2])
        self.assertEqual([o['source_order'] for o in self.plan(song)['occurrences']], [0, 1, 0, 1, 2])
        source = repeat_gp_tab([dict(isRepeatOpen=True), dict(repeatAlternative=1, repeatClose=1),
                                dict(repeatAlternative=2), {}])
        source.measureHeaders[1].timeSignature = M.TimeSignature(numerator=3)
        source.tracks[0].measures[1].voices[0].beats[0].duration = M.Duration(value=2, isDotted=True)
        song = self.native(source, 5)
        self.assertEqual(song['score']['measures'][1]['endings'], [1])
        self.assertEqual(song['score']['measures'][1]['meter'], [3, 4])
        visits = self.plan(song)['occurrences']
        self.assertEqual([o['source_order'] for o in visits], [0, 1, 0, 2, 3])
        self.assertEqual([o['at'] for o in visits], [[0, 1], [4, 1], [7, 1], [11, 1], [15, 1]])

    def test_gp_ending8_imports_but_tg_export_refuses_signed_reader_mismatch(self):
        from vulturetracker import tgimport
        configs = [dict(isRepeatOpen=True), dict(repeatAlternative=127, repeatClose=7),
                   dict(repeatAlternative=128), {}]
        for version in (3, 4, 5):
            with self.subTest(version=version):
                song = self.native(repeat_gp_tab(configs), version)
                self.assertEqual(song['score']['measures'][2]['endings'], [8])
                self.assertEqual([o['source_order'] for o in self.plan(song)['occurrences']], [0, 1] * 7 + [0, 2, 3])
                with self.assertRaisesRegex(ValueError, 'ending 8.*signed-byte'):
                    tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})

    def test_tg_repeat_tempo_export_uses_source_clock_and_never_expands_measures(self):
        import xml.etree.ElementTree as ET
        import zipfile
        import io
        from vulturetracker import tgimport
        source = repeat_gp_tab([dict(isRepeatOpen=True), dict(repeatClose=1), {}])
        source.tracks[0].measures[1].voices[0].beats[0].effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(60))
        source.tracks[0].measures[2].voices[0].beats[0].effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(90))
        song = self.native(source, 5)
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
        root = ET.fromstring(zipfile.ZipFile(io.BytesIO(data)).read('content.xml'))
        self.assertEqual([int(h.find('tempo').text) for h in root.findall('.//TGMeasureHeader')], [120, 60, 90])
        restored, _ = tgimport.read_tg(data)
        self.assertEqual(len(restored['orders']), 3)
        self.assertEqual(self.plan(restored)['tempos'], self.plan(song)['tempos'])
        self.assertEqual(self.events(restored), self.events(song))

    def test_tg_repeat_shape_and_ending8_refuse_before_publication(self):
        from vulturetracker import tgimport
        fields = [
            '<repeatOpen>true</repeatOpen>', '<repeatOpen/><repeatOpen/>',
            '<repeatClose>-1</repeatClose>', '<repeatClose>101</repeatClose>',
            '<repeatAlternative><alternative>0</alternative></repeatAlternative>',
            '<repeatAlternative><alternative>9</alternative></repeatAlternative>',
            '<repeatAlternative><alternative>1</alternative><alternative>1</alternative></repeatAlternative>',
            '<repeatAlternative><alternative>8</alternative></repeatAlternative>']
        for field in fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / 'source.tg'
                xml = TestTgInterchange.ring_xml().replace('</TGMeasureHeader>', field + '</TGMeasureHeader>')
                src.write_bytes(TestTgInterchange.archive(xml))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('preflight wrote samples')):
                    with self.assertRaisesRegex(ValueError, 'signed-byte' if '>8<' in field else 'TG 2.0'):
                        tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                self.assertEqual(list(Path(tmp).iterdir()), [src])

    def test_repeat_import_publishes_authored_yaml_and_reopens_native_backing(self):
        import yaml
        from vulturetracker import api, tgimport
        source = repeat_gp_tab([dict(isRepeatOpen=True), dict(repeatClose=1), {}])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            src = folder / 'source.gp5'
            src.write_bytes(write_repeat_gp(source, 5))
            saved, _ = gpimport.import_gp(src, folder / 'song.yaml', folder / 'samples', native=True)
            written = yaml.safe_load((folder / 'song.yaml').read_text(encoding='utf-8'))
            self.assertEqual(written, saved)
            self.assertEqual(written['orders'], ['m1', 'm2', 'm3'])
            self.assertEqual(written['score']['measures'][1]['repeat_close'], 1)
            compiled = api.prepare_playback(written, base_dir=folder)['module']
            self.assertEqual(len(compiled.native_score['plan']['occurrences']), 5)
            self.assertEqual(len(compiled.orders), 3)
            data, _ = tgimport.native_to_tg(written, compiled.patterns, channels={'t1': {'program': 25, 'bank': 0}})
            tg = folder / 'source.tg'
            tg.write_bytes(data)
            restored, _ = tgimport.import_tg(tg, folder / 'restored.yaml', folder / 'restored-samples')
            self.assertEqual(len(yaml.safe_load((folder / 'restored.yaml').read_text())['orders']), 3)
            self.assertEqual([o['source_order'] for o in self.plan(restored)['occurrences']], [0, 1, 0, 1, 2])


def native_tab(version=5):
    """Exact 13:8 rhythm, a cross-measure tie, rests, curves and GP5's second voice."""
    song = M.Song()
    song.title, song.artist, song.tempo = 'Native café', 'Writer', 137
    song.measureHeaders = [M.MeasureHeader(number=i + 1, start=960 + i * 3840) for i in range(2)]
    track = song.tracks[0]
    track.offset, track.name = 2, 'Lead'
    track.measures = [M.Measure(track, h) for h in song.measureHeaders]

    def add(mi, vi, duration, fret=None, kind=None):
        voice = track.measures[mi].voices[vi]
        start = track.measures[mi].start + sum(b.duration.time for b in voice.beats)
        beat = M.Beat(voice, start=start, duration=duration,
                      status=M.BeatStatus.rest if fret is None else M.BeatStatus.normal)
        if fret is not None:
            beat.notes.append(M.Note(beat, value=fret, string=vi + 1, velocity=95,
                                     type=kind or M.NoteType.normal))
        voice.beats.append(beat)
        return beat
    for i in range(13):
        add(0, 0, M.Duration(value=8, tuplet=M.Tuplet(13, 8)), None if i == 2 else 5)
    track.measures[0].voices[0].beats[0].notes[0].effect.slides = [M.SlideType.shiftSlideTo]
    add(1, 0, M.Duration(value=4), 5, M.NoteType.tie)
    add(1, 0, M.Duration(value=4))
    bend = add(1, 0, M.Duration(value=4), 7)
    bend.notes[0].velocity = 79
    bend.notes[0].effect.bend = M.BendEffect(type=M.BendType.bend, value=100,
                                           points=[M.BendPoint(0, 0), M.BendPoint(6, 4), M.BendPoint(12, 0)])
    bar = add(1, 0, M.Duration(value=4), 8)
    bar.effect.tremoloBar = M.BendEffect(type=M.BendType.dip, value=100,
                                       points=[M.BendPoint(0, 0), M.BendPoint(6, -4), M.BendPoint(12, 0)])
    if version == 5:
        add(0, 1, M.Duration(value=1))
        add(1, 1, M.Duration(value=1), 0)
    return song


def harmonic_tab(harmonics, *, fret=12, tuning=52, capo=0):
    """Small real GP fixture; harmonic objects occupy consecutive quarter notes."""
    song = M.Song()
    song.title, song.tempo = 'Harmonic fixture', 137
    count = (len(harmonics) + 3) // 4
    song.measureHeaders = [M.MeasureHeader(number=i + 1, start=960 + i * 3840) for i in range(count)]
    track = song.tracks[0]
    track.offset, track.fretCount = capo, 36
    track.clefTranspose = track.clefTransposeSecondary = 0
    track.strings = [M.GuitarString(1, tuning)]
    track.channel.instrument = 25
    track.measures = [M.Measure(track, header) for header in song.measureHeaders]
    for index, effect in enumerate(harmonics):
        voice = track.measures[index // 4].voices[0]
        beat = M.Beat(voice, start=voice.measure.start + (index % 4) * 960,
                      duration=M.Duration(value=4), status=M.BeatStatus.normal)
        note = M.Note(beat, value=fret, string=1, velocity=95, type=M.NoteType.normal)
        note.effect.harmonic = effect
        beat.notes.append(note)
        voice.beats.append(beat)
    return song


def let_ring_tab(kind='other', *, gates=(), reverse=False):
    """Real GP fixture: separate strings, an adjacent tie, or an overlap."""
    song = harmonic_tab([None] * (3 if kind == 'tie' else 2), fret=5, tuning=64)
    song.tempo = 120
    track = song.tracks[0]
    track.strings = [M.GuitarString(1, 64), M.GuitarString(2, 59)]
    track.channel.volume = 128
    beats = track.measures[0].voices[0].beats
    beats[0].notes[0].effect.letRing = True
    for gate in gates:
        setattr(beats[0].notes[0].effect, gate, True)
    for beat in beats[1:]:
        beat.notes[0].string, beat.notes[0].value = 2, 3
        beat.notes[0].effect.letRing = True
    if kind == 'tie':
        note = beats[1].notes[0]
        note.string, note.value, note.type, note.velocity = 1, 5, M.NoteType.tie, 31
    elif kind == 'overlap':
        note = beats[1].notes[0]
        note.string, note.value, note.effect.letRing = 1, 7, False
    elif kind == 'chord':
        other = beats[1].notes[0]
        other.effect.letRing = False
        same = M.Note(beats[1], string=1, value=5, velocity=95, type=M.NoteType.normal)
        same.effect.letRing = True
        beats[1].notes = [other, same] if reverse else [same, other]
    return song


@unittest.skipIf(guitarpro is None, 'PyGuitarPro not installed')
class TestNativeGpImport(unittest.TestCase):
    def test_swing_gp_versions_preserve_source_feel_and_performed_timing(self):
        from vulturetracker import tgimport, tablature
        for version in (3, 4, 5):
            for mode in (('eighth', 'sixteenth') if version == 5 else ('eighth',)):
                with self.subTest(version=version, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    fixture = let_ring_tab()
                    fixture.measureHeaders[0].tripletFeel = getattr(M.TripletFeel, mode)
                    value = 8 if mode == 'eighth' else 16
                    for beat in fixture.tracks[0].measures[0].voices[0].beats:
                        beat.duration = M.Duration(value=value)
                        beat.notes[0].effect.letRing = False
                    source = self.write(Path(tmp), fixture, version)
                    song = gpimport._native_gp_song(gpimport._read_native_gp(source.read_bytes()), 'Swing')
                    self.assertEqual(song['score']['measures'][0]['swing'], mode)
                    events = tablature.playback_plan(song, tgimport._raw(song))['events']
                    boundary, end = (Fraction(2, 3), Fraction(1)) if value == 8 else (Fraction(1, 3), Fraction(1, 2))
                    self.assertEqual([Fraction(*e['at']) for e in events], [0, boundary, boundary, end])

    def write(self, folder, song, version=5):
        source = folder / f'source.gp{version}'
        guitarpro.write(song, str(source), version={3: (3, 0, 0), 4: (4, 0, 6), 5: (5, 1, 0)}[version])
        return source

    def assert_refused(self, song, expected, version=5):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = self.write(folder, song, version)
            original = source.read_bytes()
            with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('preflight wrote samples')):
                with self.assertRaisesRegex(ValueError, expected):
                    gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
            self.assertEqual(list(folder.iterdir()), [source])
            self.assertEqual(source.read_bytes(), original)

    def test_grace_gp_reader_uses_tuxguitar_byte_order_and_dead_fret_rules(self):
        from guitarpro import gp3
        from vulturetracker import tgimport, tablature
        def write_grace(writer, grace):
            # GP3/4 source bytes per TG's reader: transition before duration.
            writer.writeU8(255 if grace.isDead else grace.fret)
            writer.writeU8(writer.packVelocity(grace.velocity))
            writer.writeU8(grace.transition.value)
            writer.writeU8({64: 1, 32: 2, 16: 3}[grace.duration])
        for version in (3, 4, 5):
            for dead in (False, True):
                with self.subTest(version=version, dead=dead), tempfile.TemporaryDirectory() as tmp:
                    fixture = let_ring_tab('other')
                    source_note = fixture.tracks[0].measures[0].voices[0].beats[0].notes[0]
                    source_note.effect.letRing = False
                    source_note.effect.grace = M.GraceEffect(fret=2, duration=16, velocity=47,
                        transition=M.GraceEffectTransition.bend, isOnBeat=version == 5, isDead=dead)
                    with patch.object(gp3.GP3File, 'writeGrace', write_grace):
                        source = self.write(Path(tmp), fixture, version)
                    decoded = gpimport._read_native_gp(source.read_bytes())
                    song = gpimport._native_gp_song(decoded, 'Grace')
                    grace = song['score']['patterns']['m1']['beats'][0]['notes'][0]['grace']
                    self.assertEqual(grace, dict(fret=0 if dead and version < 5 else 2, value=16,
                        velocity=47, transition='bend', on_beat=version == 5, dead=dead))
                    events = tablature.playback_plan(song, tgimport._raw(song))['events']
                    self.assertEqual(sum(e.get('role') == 'grace' and e['type'] == 'note_on' for e in events), 1)
                    data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                    restored, _ = tgimport.read_tg(data)
                    musical = lambda values: [{k: v for k, v in e.items() if k not in ('id', 'beat', 'note', 'source_id')}
                                               for e in values]
                    self.assertEqual(musical(tablature.playback_plan(restored, tgimport._raw(restored))['events']), musical(events))

    def test_gp3_gp4_gp5_exact_written_native_roundtrip(self):
        import yaml
        from vulturetracker import api
        for version in (3, 4, 5):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                fixture = native_tab(version)
                fixture.measureHeaders[0].marker = M.Marker(title='Verse café', color=M.Color(23, 45, 67))
                fixture.tracks[0].measures[0].voices[0].beats[0].text = 'Let it breathe <softly>'
                source = self.write(folder, fixture, version)
                before = source.read_bytes()
                song, warnings = gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(yaml.safe_load((folder / 'song.yaml').read_text(encoding='utf-8')), song)
                self.assertEqual(len(list((folder / 'samples').glob('*.wav'))), 7)
                self.assertIn('placeholder', warnings[0])
                self.assertEqual(song['module']['tempo'], 137)
                self.assertIn('Writer', song['module']['message'])
                self.assertIn('program 25, bank 0', song['module']['message'])
                score = song['score']
                self.assertEqual(score['measures'][0]['marker'], dict(title='Verse café', color='#172d43'))
                self.assertEqual(score['patterns']['m1']['beats'][0]['text'], 'Let it breathe <softly>')
                self.assertEqual(score['tracks']['t1']['capo'], 2)
                beats = score['patterns']['m1']['beats'][:13]
                self.assertEqual([Fraction(*b['at']) for b in beats], [Fraction(4 * i, 13) for i in range(13)])
                self.assertTrue(all(b['written'] == dict(value=8, dots=0, tuplet=[13, 8]) for b in beats))
                self.assertEqual(beats[2]['notes'], [])
                self.assertEqual(beats[0]['notes'][0]['pitch'], 71)
                self.assertEqual(beats[0]['notes'][0]['velocity'], 95)
                self.assertTrue(beats[0]['notes'][0]['slide'])
                self.assertNotIn('volume', beats[0]['notes'][0])
                self.assertEqual(score['ties'], [{'from': {'occurrence': 'o1', 'note': 't1_v1_b13_s1'},
                                                  'to': {'occurrence': 'o2', 'note': 't1_v1_b1_s1'}}])
                later = score['patterns']['m2']['beats']
                self.assertEqual(later[2]['notes'][0]['bend']['points'][1], dict(position=6, value=4))
                self.assertEqual(later[3]['notes'][0]['tremolo_bar']['points'][1], dict(position=6, value=-2))
                self.assertEqual(later[2]['notes'][0]['velocity'], 79)
                self.assertEqual({b['voice'] for b in later}, {0, 1} if version == 5 else {0})
                self.assertTrue(all(p['data'] == '' for p in song['patterns'].values()))
                self.assertEqual(api.load(folder / 'song.yaml'), song)
                prepared = api.prepare_playback(folder / 'song.yaml')
                self.assertEqual(prepared['plan']['duration']['quarters'], [8, 1])
                attacks = [e for e in prepared['plan']['events'] if e['type'] == 'note_on']
                self.assertTrue(attacks)
                self.assertIn(79, [e['velocity'] for e in attacks])

    def test_gates_vibrato_shift_slide_and_dotted_rest(self):
        for version in (4, 5):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                song = native_tab(version)
                beats = song.tracks[0].measures[1].voices[0].beats
                beats[2].notes[0].effect.bend = None
                beats[2].notes[0].effect.slides = [M.SlideType.shiftSlideTo]
                beats[2].notes[0].effect.palmMute = True
                beats[2].notes[0].effect.staccato = True
                beats[3].effect.tremoloBar = None
                beats[3].notes[0].effect.vibrato = True
                beats[3].notes[0].type = M.NoteType.dead
                # Shorten the rest and make the following quarter dotted: still four quarters.
                beats[1].duration = M.Duration(value=8)
                beats[2].duration.isDotted = True
                source = self.write(folder, song, version)
                converted, _ = gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
                result = converted['score']['patterns']['m2']['beats']
                note = result[2]['notes'][0]
                self.assertTrue(note['palm_mute'] and note['staccato'] and note['slide'])
                self.assertEqual(result[2]['written']['dots'], 1)
                self.assertEqual(result[2]['at'], [3, 2])
                self.assertTrue(result[3]['notes'][0]['dead'] and result[3]['notes'][0]['vibrato'])

    def test_native_dynamics_preserve_source_flags_and_velocity(self):
        from vulturetracker import api
        for version in (3, 4, 5):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                original = native_tab(version)
                notes = original.tracks[0].measures[0].voices[0].beats
                notes[0].notes[0].effect.slides = []
                notes[0].notes[0].effect.hammer = True
                notes[1].notes[0].effect.ghostNote = True
                if version == 5:
                    notes[3].notes[0].effect.accentuatedNote = True
                    notes[4].notes[0].effect.heavyAccentuatedNote = True
                source = self.write(folder, original, version)
                song, _ = gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
                beats = song['score']['patterns']['m1']['beats']
                self.assertTrue(beats[0]['notes'][0]['hammer'])
                self.assertTrue(beats[1]['notes'][0]['ghost'])
                self.assertEqual(beats[1]['notes'][0]['velocity'], 95)
                self.assertNotIn('volume', beats[1]['notes'][0])
                plan = api.prepare_playback(folder / 'song.yaml')['plan']
                attacks = {e['id']: e for e in plan['events'] if e['type'] == 'note_on'}
                self.assertEqual(attacks['o1/t1_v1_b2_s1']['velocity'], 54)
                self.assertEqual(attacks['o1/t1_v1_b2_s1']['authored_velocity'], 95)
                if version == 5:
                    self.assertTrue(beats[3]['notes'][0]['accent'])
                    self.assertTrue(beats[4]['notes'][0]['heavy_accent'])
                    self.assertEqual(attacks['o1/t1_v1_b4_s1']['velocity'], 111)
                    self.assertEqual(attacks['o1/t1_v1_b5_s1']['velocity'], 127)

    def test_native_harmonics_from_actual_gp_versions(self):
        from vulturetracker import tablature, tgimport
        groups = {
            3: [(M.NaturalHarmonic(), 'natural', 0), (M.ArtificialHarmonic(), 'artificial', 0)],
            4: [(M.NaturalHarmonic(), 'natural', 0), (M.TappedHarmonic(), 'tapped', 0),
                (M.PinchHarmonic(), 'pinch', 0), (M.SemiHarmonic(), 'semi', 0),
                (M.ArtificialHarmonic(M.PitchClass(11), M.Octave.ottava), 'artificial', 2),
                (M.ArtificialHarmonic(M.PitchClass(4), M.Octave.quindicesima), 'artificial', 3),
                (M.ArtificialHarmonic(M.PitchClass(4), M.Octave.ottava), 'artificial', 0)],
            5: [(M.NaturalHarmonic(), 'natural', 0),
                (M.ArtificialHarmonic(M.PitchClass(3), M.Octave.quindicesima), 'artificial', 0),
                (M.PinchHarmonic(), 'pinch', 0), (M.SemiHarmonic(), 'semi', 0)] +
               [(M.TappedHarmonic(12 + interval), 'tapped', i) for i, interval in enumerate((12, 9, 5, 7, 4, 3))] +
               [(M.TappedHarmonic(13), 'tapped', 0), (M.TappedHarmonic(255), 'tapped', 0)]}
        for version, cases in groups.items():
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                source = self.write(Path(tmp), harmonic_tab([h for h, _, _ in cases]), version)
                parsed = gpimport._read_native_gp(source.read_bytes())
                self.assertEqual(parsed.versionTuple[0], version)
                warnings = []
                song = gpimport._native_gp_song(parsed, parsed.title, warnings=warnings)
                notes = [n for pattern in song['score']['patterns'].values() for beat in pattern['beats'] for n in beat['notes']]
                self.assertEqual([n['harmonic'] for n in notes], [dict(type=kind, data=data) for _, kind, data in cases])
                attacks = [e for e in tablature.playback_plan(song, tgimport._raw(song))['events'] if e['type'] == 'note_on']
                self.assertEqual(len(attacks), len(cases))
                self.assertTrue(all(e.get('layers') for e in attacks))
                if version == 4:
                    decoded = [n.effect.harmonic for m in parsed.tracks[0].measures for b in m.voices[0].beats for n in b.notes][-3:]
                    self.assertEqual([(h.pitch.value, h.octave) for h in decoded],
                                     [(11, M.Octave.ottava), (4, M.Octave.quindicesima), (4, M.Octave.ottava)])
                    self.assertEqual([e['layers'][-1]['pitch'] for e in attacks[-3:]], [88, 83, 76])
                if version == 5:
                    self.assertEqual(len(warnings), 3)
                    self.assertIn('TuxGuitar 2.1.0 ignores these fields', warnings[0])
                    self.assertTrue(all(w in song['module']['message'] for w in warnings))
                else:
                    self.assertFalse(warnings)

    def test_native_repetition_actual_gp_rates_and_tg_roundtrip(self):
        from vulturetracker import tgimport, tablature
        for version in (4, 5):
            for field, cls, rates in (('trill', M.TrillEffect, (16, 32, 64)),
                                      ('tremoloPicking', M.TremoloPickingEffect, (8, 16, 32))):
                for rate in rates:
                    with self.subTest(version=version, effect=field, rate=rate), tempfile.TemporaryDirectory() as tmp:
                        source_song = harmonic_tab([M.NaturalHarmonic()], fret=5, tuning=64)
                        source_song.tracks[0].channel.volume = 128  # Neutral native mixer required by TG export.
                        effect = cls(duration=M.Duration(value=rate), **({'fret': 7} if field == 'trill' else {}))
                        setattr(source_song.tracks[0].measures[0].voices[0].beats[0].notes[0].effect, field, effect)
                        source = self.write(Path(tmp), source_song, version)
                        warnings = []
                        song = gpimport._native_gp_song(gpimport._read_native_gp(source.read_bytes()), 'repetition', warnings=warnings)
                        note = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                        native_field = 'trill' if field == 'trill' else 'tremolo_picking'
                        self.assertEqual(note[native_field]['value'], rate)
                        self.assertFalse(warnings)
                        events = tablature.playback_plan(song, tgimport._raw(song))['events']
                        ons = [e for e in events if e['type'] == 'note_on']
                        self.assertEqual(len(ons), rate // 4)
                        self.assertEqual([e['pitch'] for e in ons],
                                         [69 + (2 if field == 'trill' and i % 2 else 0) for i in range(rate // 4)])
                        self.assertTrue(all('layers' not in e for e in ons))
                        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                        restored, _ = tgimport.read_tg(data)
                        # TG materializes the GP track's implicit treble clef;
                        # compare measures, written beats and note semantics.
                        self.assertEqual(TestTgInterchange.semantics(restored)[2:], TestTgInterchange.semantics(song)[2:])

    def test_native_repetition_gp_conflict_precedence_and_preserved_source_notice(self):
        for version in (4, 5):
            for field in ('trill', 'tremoloPicking'):
                for conflict in ('hammer', 'vibrato', 'slide', 'both'):
                    with self.subTest(version=version, effect=field, conflict=conflict), tempfile.TemporaryDirectory() as tmp:
                        source_song = harmonic_tab([None], fret=5, tuning=64)
                        eff = source_song.tracks[0].measures[0].voices[0].beats[0].notes[0].effect
                        if field == 'trill' or conflict == 'both':
                            eff.trill = M.TrillEffect(fret=7, duration=M.Duration(value=16))
                        if field == 'tremoloPicking' or conflict == 'both':
                            eff.tremoloPicking = M.TremoloPickingEffect(duration=M.Duration(value=16))
                        if conflict == 'slide':
                            eff.slides = [M.SlideType.shiftSlideTo]
                        elif conflict != 'both':
                            setattr(eff, conflict, True)
                        source = self.write(Path(tmp), source_song, version)
                        warnings = []
                        song = gpimport._native_gp_song(gpimport._read_native_gp(source.read_bytes()), 'conflict', warnings=warnings)
                        note = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                        winner = ('trill' if conflict == 'both' else conflict if
                                  version == 5 and conflict in ('hammer', 'vibrato') or
                                  field == 'tremoloPicking' and conflict == 'slide' else
                                  'trill' if field == 'trill' else 'tremolo_picking')
                        for key in ('trill', 'tremolo_picking', 'slide', 'hammer', 'vibrato'):
                            self.assertEqual(key in note, key == winner)
                        self.assertEqual(len(warnings), 1)
                        self.assertIn(f'GP{version} reader normalized repetition conflicts', warnings[0])
                        self.assertIn(warnings[0], song['module']['message'])

    def test_native_repetition_invalid_gp_information_refuses(self):
        for field, effect in (
                ('trill', M.TrillEffect(fret=7, duration=M.Duration(value=8))),
                ('trill', M.TrillEffect(fret=-1, duration=M.Duration(value=16))),
                ('trill', M.TrillEffect(fret=37, duration=M.Duration(value=16))),
                ('trill', M.TrillEffect(fret=7, duration=M.Duration(value=16, isDotted=True))),
                ('tremoloPicking', M.TremoloPickingEffect(duration=M.Duration(value=64))),
                ('tremoloPicking', M.TremoloPickingEffect(duration=M.Duration(value=16, tuplet=M.Tuplet(3, 2))))):
            with self.subTest(field=field, effect=effect), tempfile.TemporaryDirectory() as tmp:
                source = self.write(Path(tmp), harmonic_tab([None], fret=5, tuning=64))
                parsed = gpimport._read_native_gp(source.read_bytes())
                setattr(parsed.tracks[0].measures[0].voices[0].beats[0].notes[0].effect, field, effect)
                with patch.object(gpimport, '_read_native_gp', return_value=parsed):
                    with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                        with self.assertRaisesRegex(ValueError, 'trill|tremolo picking'):
                            gpimport.import_gp(source, Path(tmp) / 'out.yaml', Path(tmp) / 'samples', native=True)
                self.assertEqual(list(Path(tmp).iterdir()), [source])

    def test_native_repetition_invalid_gp_bytes_refuse_before_publication(self):
        for version in (4, 5):
            for field, method, effect in (
                    ('trill', 'toTrillPeriod', M.TrillEffect(fret=7, duration=M.Duration(value=16))),
                    ('tremoloPicking', 'toTremoloValue', M.TremoloPickingEffect(duration=M.Duration(value=16)))):
                with self.subTest(version=version, effect=field), tempfile.TemporaryDirectory() as tmp:
                    source_song = harmonic_tab([None], fret=5, tuning=64)
                    setattr(source_song.tracks[0].measures[0].voices[0].beats[0].notes[0].effect, field, effect)
                    with patch('guitarpro.gp4.GP4File.' + method, return_value=4):
                        source = self.write(Path(tmp), source_song, version)
                    with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                        with self.assertRaisesRegex(ValueError, 'unsupported GP .* byte 4'):
                            gpimport.import_gp(source, Path(tmp) / 'out.yaml', Path(tmp) / 'samples', native=True)
                    self.assertEqual(list(Path(tmp).iterdir()), [source])

    def test_native_let_ring_gp_versions_ties_and_serialized_chord_order(self):
        from vulturetracker import tgimport, tablature
        for version in (3, 4, 5):
            for kind, end in (('other', 2), ('tie', 3), ('chord', 1)):
                with self.subTest(version=version, kind=kind), tempfile.TemporaryDirectory() as tmp:
                    # GP writes strings in numbered order even if the input list
                    # is reversed. Native import must follow the actual file.
                    source = self.write(Path(tmp), let_ring_tab(kind, reverse=True), version)
                    warnings = []
                    song = gpimport._native_gp_song(gpimport._read_native_gp(source.read_bytes()), 'ring', warnings=warnings)
                    self.assertFalse(warnings)
                    notes = song['score']['patterns']['m1']['beats'][0]['notes']
                    self.assertTrue(notes[0]['let_ring'])
                    events = tablature.playback_plan(song, tgimport._raw(song))['events']
                    head = next(e for e in events if e['type'] == 'note_on')
                    self.assertEqual(next(e['at'] for e in events if e['id'] == head['id'] and e['type'] == 'note_off'), [end, 1])
                    if kind == 'chord':
                        self.assertEqual([n['string'] for n in song['score']['patterns']['m1']['beats'][1]['notes']], [1, 2])
                    data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                    restored, _ = tgimport.read_tg(data)
                    self.assertEqual(TestTgInterchange.semantics(restored)[2:], TestTgInterchange.semantics(song)[2:])

    def test_native_let_ring_gp_gate_order_and_source_notices(self):
        from vulturetracker import tgimport, tablature
        for version in (4, 5):
            for gates, winner, at in ((('palmMute',), 'palm_mute', [1, 8]),
                                       (('staccato',), 'staccato', [1, 2]),
                                       (('palmMute', 'staccato'), 'staccato', [1, 2])):
                with self.subTest(version=version, gates=gates), tempfile.TemporaryDirectory() as tmp:
                    source = self.write(Path(tmp), let_ring_tab(gates=gates), version)
                    warnings = []
                    song = gpimport._native_gp_song(gpimport._read_native_gp(source.read_bytes()), 'ring', warnings=warnings)
                    note = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                    self.assertTrue(note[winner])
                    self.assertNotIn('let_ring', note)
                    self.assertFalse(note.get('palm_mute' if winner == 'staccato' else 'staccato'))
                    self.assertEqual(len(warnings), 1)
                    self.assertIn("'let_ring': True", warnings[0])
                    self.assertIn(warnings[0], song['module']['message'])
                    events = tablature.playback_plan(song, tgimport._raw(song))['events']
                    self.assertEqual(next(e['at'] for e in events if e['type'] == 'note_off' and e['note'] == note['id']), at)

    def test_native_let_ring_gp_overlap_preserves_held_gate(self):
        from vulturetracker import tgimport, tablature
        for version in (3, 4, 5):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                source = self.write(Path(tmp), let_ring_tab('overlap'), version)
                song = gpimport._native_gp_song(gpimport._read_native_gp(source.read_bytes()), 'held')
                plan = tablature.playback_plan(song, tgimport._raw(song))
                held = [e for e in plan['events'] if e.get('hold')]
                self.assertEqual(len(held), 1)
                self.assertEqual(next(e['at'] for e in plan['events'] if e['type'] == 'note_off' and e['id'] == held[0]['id']), [2, 1])

    def test_ambiguous_gp4_harmonic_refuses_with_location_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = self.write(folder, harmonic_tab([M.ArtificialHarmonic()]), 4)
            parsed = gpimport._read_native_gp(source.read_bytes())
            parsed.tracks[0].measures[0].voices[0].beats[0].notes[0].effect.harmonic = M.ArtificialHarmonic(
                M.PitchClass(1), M.Octave.ottava)
            with patch.object(gpimport, '_read_native_gp', return_value=parsed):
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('preflight wrote samples')):
                    with self.assertRaisesRegex(ValueError, 'measure 1.*beat 1.*string 1: ambiguous GP4 artificial harmonic'):
                        gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
            self.assertEqual(list(folder.iterdir()), [source])

    def test_harmonic_publication_keeps_warning_and_native_layers(self):
        import yaml
        from vulturetracker import api
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = self.write(folder, harmonic_tab([M.ArtificialHarmonic(M.PitchClass(3), M.Octave.quindicesima)]))
            song, warnings = gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
            self.assertEqual(yaml.safe_load((folder / 'song.yaml').read_text(encoding='utf-8')), song)
            self.assertEqual(len(list((folder / 'samples').glob('*.wav'))), 7)
            self.assertTrue(any('GP5 artificial harmonic' in w for w in warnings))
            prepared = api.prepare_playback(folder / 'song.yaml')
            attack = next(e for e in prepared['plan']['events'] if e['type'] == 'note_on')
            self.assertEqual(attack['layers'], [dict(pitch=64, velocity=31), dict(pitch=76, velocity=95)])

    def test_gp_measure_tempo_normalization_and_source_metadata(self):
        from vulturetracker import tablature, tgimport, api
        for version in (3, 4, 5):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source = harmonic_tab([None] * 12)
                source.tempo = 120
                beats = source.tracks[0].measures[1].voices[0].beats
                beats[0].effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(180))
                beats[2].effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(240, duration=4))
                beats[3].effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(60))
                path = self.write(folder, source, version)
                parsed = gpimport._read_native_gp(path.read_bytes())
                warnings = []
                song = gpimport._native_gp_song(parsed, parsed.title, warnings=warnings)
                self.assertEqual(song['patterns']['m2']['data'], '00: ... .. ... T3C\n')
                self.assertEqual(song['patterns']['m3']['data'], '')  # tempo inherits
                plan = tablature.playback_plan(song, tgimport._raw(song))
                self.assertEqual(plan['tempos'], [{'at': [0, 1], 'bpm': 120}, {'at': [4, 1], 'bpm': 60}])
                self.assertEqual(plan['duration']['seconds'], [10, 1])
                self.assertTrue(any('quarter 2, transition duration 4' in w for w in warnings))
                self.assertTrue(any('last traversed tempo (60 BPM)' in w for w in warnings))
                self.assertIn('voice 1, beat 3: source tempo 240 BPM at quarter 2, transition duration 4', song['module']['message'])
                if version == 5:
                    saved, notices = gpimport.import_gp(path, folder / 'song.yaml', folder / 'samples', native=True)
                    self.assertEqual(saved['score'], song['score'])
                    self.assertEqual(saved['patterns'], song['patterns'])
                    self.assertEqual(len(list((folder / 'samples').glob('*.wav'))), 7)
                    self.assertTrue(any('discards transition durations' in w for w in notices))
                    self.assertEqual(api.prepare_playback(folder / 'song.yaml')['plan']['tempos'], plan['tempos'])

    def test_gp_tempo_first_measure_override_voice_traversal_and_bounds(self):
        from vulturetracker import tablature, tgimport
        source = harmonic_tab([None] * 4)
        source.tempo = 120
        measure = source.tracks[0].measures[0]
        measure.voices[0].beats[2].effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(240))
        later_voice = measure.voices[1]
        rest = M.Beat(later_voice, start=measure.start, duration=M.Duration(value=4), status=M.BeatStatus.rest)
        rest.effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(60))
        later_voice.beats.append(rest)
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(Path(tmp), source)
            parsed = gpimport._read_native_gp(path.read_bytes())
            song = gpimport._native_gp_song(parsed, parsed.title)
            self.assertEqual(song['module']['tempo'], 120)
            self.assertEqual(song['patterns']['m1']['data'], '00: ... .. ... T3C\n')
            self.assertEqual(tablature.playback_plan(song, tgimport._raw(song))['tempos'],
                             [{'at': [0, 1], 'bpm': 60}])
            self.assertIn('voice 2, beat 1: source tempo 60 BPM', song['module']['message'])
        for version in (3, 4, 5):
            for value in (31, 256):
                invalid = harmonic_tab([None] * 4)
                invalid.tracks[0].measures[0].voices[0].beats[2].effect.mixTableChange = M.MixTableChange(
                    tempo=M.MixTableItem(value))
                with self.subTest(version=version, value=value):
                    self.assert_refused(invalid, 'tempo change must be 32..255', version)

    def test_unsupported_source_refuses_before_output(self):
        for field, value, error in (
                ('slides', [M.SlideType.legatoSlideTo], 'only shift slide'),):
            with self.subTest(field=field):
                song = native_tab()
                setattr(song.tracks[0].measures[0].voices[0].beats[0].notes[0].effect, field, value)
                self.assert_refused(song, error)
        song = native_tab()
        song.measureHeaders[0].repeatClose = 101
        self.assert_refused(song, 'measure 1: repeat open/count')
        song = native_tab()
        song.tracks[0].isPercussionTrack = True
        self.assert_refused(song, 'percussion flag contradicts primary MIDI route')
        song = native_tab()
        song.tracks[0].measures[0].voices[0].beats[0].effect.hasRasgueado = True
        self.assert_refused(song, 'track 1, measure 1, voice 1, beat 1: unsupported hasRasgueado')
        song = native_tab(3)
        song.tracks[0].measures[1].voices[0].beats[3].effect.tremoloBar.value = 75
        self.assert_refused(song, 'GP3 tremolo-bar depth cannot be represented exactly', 3)
        song = native_tab()
        song.tracks[0].measures[1].voices[0].beats[0].duration = M.Duration(value=1)
        self.assert_refused(song, 'outside pattern')
        song = native_tab()
        song.tracks[0].measures[0].voices[0].beats[0].notes[0].type = M.NoteType.tie
        self.assert_refused(song, 'tie has no adjacent')

    def test_full_bundle_validation_precedes_publication(self):
        from vulturetracker.song import SongError
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = self.write(folder, native_tab())
            with patch('vulturetracker.api.prepare_playback', side_effect=SongError(['compiler rejected candidate'], [])):
                with self.assertRaisesRegex(SongError, 'compiler rejected candidate'):
                    gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
            self.assertEqual(list(folder.iterdir()), [source])

    def test_gp5_common_display_mix_and_header_fields_are_retained(self):
        from vulturetracker import gpexport, tgimport
        fixture = harmonic_tab([None] * 9, fret=25)
        track = fixture.tracks[0]
        track.fretCount, track.clefTranspose = 24, 12
        track.channel.chorus = 16
        fixture.measureHeaders[1].hasDoubleBar = True
        fixture.measureHeaders[1].keySignature = fixture.measureHeaders[2].keySignature = M.KeySignature.DMajor
        first = track.measures[0].voices[0].beats[0]
        first.notes[0].durationPercent = .75
        first.notes[0].swapAccidentals = True
        first.effect.mixTableChange = M.MixTableChange(volume=M.MixTableItem(120))
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(Path(tmp), fixture)
            original = path.read_bytes()
            warnings = []
            song = gpimport._native_gp_song(gpimport._read_native_gp(original), 'Metadata', warnings=warnings)
            self.assertEqual(song['score']['tracks']['t1']['max_fret'], 25)
            self.assertTrue(song['score']['measures'][1]['double_bar'])
            self.assertEqual(song['score']['measures'][1]['staff']['t1']['key'], dict(fifths=2, mode='major'))
            self.assertNotIn('staff', song['score']['measures'][2])
            self.assertEqual(song['score']['patterns']['m1']['beats'][0]['written']['value'], 4)
            for field in ('durationPercent', 'swapAccidentals', 'clefTranspose', 'chorus', 'volume'):
                self.assertIn(field, song['module']['message'])
            self.assertTrue(any('not emulated' in w for w in warnings))
            song['score'].setdefault('metadata', {})['comments'] = 'Header round-trip fixture'
            for version in (3, 4, 5):
                data, _ = gpexport.native_to_gp(song, tgimport._raw(song), channels={'t1': dict(program=25, bank=0)}, version=version)
                decoded = gpimport._read_native_gp(data)
                self.assertEqual([h.keySignature for h in decoded.measureHeaders],
                                 [M.KeySignature.CMajor, M.KeySignature.DMajor, M.KeySignature.DMajor])
                self.assertEqual([h.hasDoubleBar for h in decoded.measureHeaders], [False, True, False])
            with self.assertRaisesRegex(ValueError, 'double-barline'):
                tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': dict(program=25, bank=0)})
            self.assertEqual(path.read_bytes(), original)

    def test_tied_note_lookup_uses_beat_identity(self):
        # Two otherwise equal tie beats must resolve their own preceding notes.
        fixture = harmonic_tab([None] * 4, fret=0)
        beats = fixture.tracks[0].measures[0].voices[0].beats
        for i, beat in enumerate(beats):
            beat.notes[0].value = 0 if i < 2 else 7
            if i % 2:
                beat.notes[0].type = M.NoteType.tie
        for version in (3, 4, 5):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                path = self.write(Path(tmp), fixture, version)
                parsed = gpimport._read_native_gp(path.read_bytes())
                self.assertEqual([b.notes[0].value for b in parsed.tracks[0].measures[0].voices[0].beats], [0, 0, 7, 7])
                song = gpimport._native_gp_song(parsed, 'Ties')
                self.assertEqual(len(song['score']['ties']), 2)

    def test_gp5_declared_drum_frets_do_not_limit_keys_or_relax_guitar_bounds(self):
        fixture = harmonic_tab([None], fret=42, tuning=0)
        track = fixture.tracks[0]
        track.isPercussionTrack, track.fretCount = True, 87
        track.channel.channel = track.channel.effectChannel = 9
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(Path(tmp), fixture)
            song = gpimport._native_gp_song(gpimport._read_native_gp(path.read_bytes()), 'Drums')
            self.assertEqual(song['score']['patterns']['m1']['beats'][0]['notes'][0]['pitch'], 42)
            self.assertIn("'source': 87", song['module']['message'])
        invalid = harmonic_tab([None], fret=37)
        invalid.tracks[0].fretCount = 24
        self.assert_refused(invalid, 'fret count outside native range')

    def test_publication_races_preserve_existing_user_files(self):
        for destination in ('song', 'samples'):
            with self.subTest(destination=destination), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source = self.write(folder, native_tab())
                output, samples = folder / 'song.yaml', folder / 'samples'

                def create_competing_destination(*args, **kwargs):
                    if destination == 'song':
                        output.write_bytes(b'user song')
                    else:
                        samples.mkdir()
                        (samples / 'keep.wav').write_bytes(b'user sample')
                    return {}

                with patch('vulturetracker.api.prepare_playback', side_effect=create_competing_destination):
                    with self.assertRaises(FileExistsError):
                        gpimport.import_gp(source, output, samples, native=True)
                if destination == 'song':
                    self.assertEqual(output.read_bytes(), b'user song')
                else:
                    self.assertEqual((samples / 'keep.wav').read_bytes(), b'user sample')
                    self.assertFalse(output.exists())
                self.assertFalse(list(folder.glob('.gp-native-*')))

    def test_raw_reader_rounds_like_tg_but_refuses_vibrato_and_unknown_tuplets(self):
        import struct
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = self.write(folder, native_tab())
            data = source.read_bytes()
            point = struct.pack('<ii?', 30, 100, False)
            self.assertEqual(data.count(point), 1)
            for position, value, expected in ((9, 100, (2, 4)), (30, 101, (6, 4))):
                with self.subTest(position=position, value=value):
                    changed = data.replace(point, struct.pack('<ii?', position, value, False))
                    warnings = []
                    song = gpimport._native_gp_song(gpimport._read_native_gp(changed), 'Rounded', warnings=warnings)
                    points = [p for pattern in song['score']['patterns'].values() for beat in pattern['beats']
                              for note in beat['notes'] for p in note.get('bend', {}).get('points', [])]
                    self.assertIn(dict(position=expected[0], value=expected[1]), points)
                    self.assertIn(str((position, value)), song['module']['message'])
                    self.assertTrue(any('TuxGuitar 2.1.0 rounded' in w for w in warnings))
            source.write_bytes(data.replace(point, struct.pack('<ii?', 30, 100, True)))
            with self.assertRaisesRegex(ValueError, 'per-point bend/bar vibrato'):
                gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
            self.assertFalse((folder / 'samples').exists())
            end = struct.pack('<ii?', 60, 0, False)
            self.assertIn(end, data)
            source.write_bytes(data.replace(end, struct.pack('<ii?', 29, 0, False)))
            with self.assertRaisesRegex(ValueError, 'points are out of order'):
                gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
            self.assertFalse((folder / 'samples').exists())
            # A serialized 13:8 tuplet with an unsupported count must not become 1:1.
            # Locate the duration encoding after the beat's 0x20 flag.
            marker = b'\x20\x01' + struct.pack('<i', 13)
            self.assertGreater(data.count(marker), 0)
            source.write_bytes(data.replace(marker, b'\x20\x01' + struct.pack('<i', 14), 1))
            with self.assertRaisesRegex(ValueError, 'measure 1.*unsupported written tuplet 14'):
                gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
            self.assertFalse((folder / 'samples').exists())

    def test_invalid_destinations_are_checked_before_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = self.write(folder, native_tab())
            output = folder / 'song.yaml'
            samples = folder / 'samples'
            output.write_text('keep', encoding='utf-8')
            with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('preflight wrote samples')):
                for destination in (output, folder / 'missing' / 'song.yaml', folder / 'NUL.yaml', source):
                    with self.subTest(destination=destination), self.assertRaises(ValueError):
                        gpimport.import_gp(source, destination, samples, native=True)
                with self.assertRaises(ValueError):
                    gpimport.import_gp(source, folder / 'new.yaml', output / 'samples', native=True)
            self.assertEqual(output.read_text(encoding='utf-8'), 'keep')
            self.assertFalse(samples.exists())

    def test_actual_cli_native_opt_in_and_legacy_default(self):
        import os
        import subprocess
        import sys
        from vulturetracker import api
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = self.write(folder, native_tab())
            for native in (True, False):
                output = folder / ('native.yaml' if native else 'legacy.yaml')
                command = [sys.executable, '-m', 'vulturetracker', 'import', str(source), '-o', str(output)]
                if native:
                    command.append('--native-tab')
                result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                        text=True, timeout=60,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                song = api.load(output)
                self.assertEqual(len(list(folder.glob(output.stem + '_samples/*.wav'))), 7)
                if native:
                    beats = [b for p in song['score']['patterns'].values() for b in p['beats']]
                    notes = [n for b in beats for n in b['notes']]
                    self.assertEqual((len(beats), len(notes), len(song['score']['ties'])), (19, 16, 1))
                    self.assertEqual(sorted(set(n['velocity'] for n in notes)), [79, 95])
                    self.assertTrue(all('volume' not in n for n in notes))
                    self.assertIn('placeholder', result.stdout)
                else:
                    self.assertNotIn('score', song)
                    self.assertTrue(any(p['data'] for p in song['patterns'].values()))


@unittest.skipIf(guitarpro is None, "PyGuitarPro not installed (pip install pyguitarpro)")
class TestPlaceholders(unittest.TestCase):
    def test_pluck_pitch(self):
        import numpy as np
        for hz in (65.406, 261.626, 2093.005, 4186.009):
            y = gpimport.pluck(hz, seconds=1.0)
            s = np.abs(np.fft.rfft(y * np.hanning(len(y)), 1 << 20))
            f = np.fft.rfftfreq(1 << 20, 1 / 44100)
            m = (f > hz * 0.9) & (f < hz * 1.1)
            self.assertLess(abs(1200 * np.log2(f[m][s[m].argmax()] / hz)), 2, hz)  # measured, in cents


@unittest.skipIf(guitarpro is None, "PyGuitarPro not installed (pip install pyguitarpro)")
class TestGpImport(unittest.TestCase):
    def test_a_tab_becomes_a_song(self):
        import numpy as np
        from vulturetracker import api, dsp
        from vulturetracker.library import read_audio
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tab(d / "t.gp5")
            song, warnings = gpimport.import_gp(d / "t.gp5", d / "t.yaml", d / "t_samples")
            self.assertEqual(warnings, ['Guitar Pro text decoded with cp1252.'])
            m = song["module"]
            self.assertEqual((m["tempo"], m["speed"]), (100, 4))              # triplets: 6 rows a quarter
            self.assertEqual(song["orders"], ["m1", "m2", "m2_2", "m3"])       # the repeat played out
            names = [c["name"] for c in m["channels"]]
            self.assertEqual(names, ["Gtr str 1", "Gtr str 2", "Gtr str 3", "Gtr str 4", "Gtr str 5", "Gtr str 6",
                                     "Drums drum 1", "Drums drum 2", "Tempo"])
            self.assertEqual([(c.get("volume"), c.get("pan")) for c in m["channels"][5:7]], [(52, None), (None, 64)])  # 64 is the default, left out
            cell = {}
            for name, pat in song["patterns"].items():
                for line in pat["data"].splitlines():
                    row, _, rest = line.partition(": ")
                    for ch, c in enumerate(rest.split(" | ")):
                        cell[(name, int(row), ch)] = c
            self.assertEqual(cell[("m1", 0, 4)], "C-4 01 v48 ...")           # A string, fret 3
            self.assertEqual(cell[("m1", 12, 4)], "=== .. ... ...")          # tied on for a quarter, then off
            self.assertEqual(cell[("m1", 15, 2)], "D-5 01 v48 GFF")          # hammer-on: not struck again
            self.assertEqual([cell[("m1", r, 1)][-3:] for r in range(18, 21)], ["F04", "F03", "F04"])  # the full bend
            self.assertEqual(cell[("m2", 0, 1)], "=== .. ... ...")           # the bent note ends: first pass only
            self.assertEqual(cell[("m2_2", 0, 1)], "... .. ... ...")
            self.assertEqual(cell[("m2", 6, 0)], "C#6 01 v48 H44")           # after the slide, with vibrato
            self.assertEqual(cell[("m2", 12, 5)], "E-3 01 v16 SC1")          # dead note
            self.assertEqual(cell[("m2", 21, 5)], "=== .. ... ...")          # palm mute: half its length
            self.assertEqual(cell[("m3", 0, 8)], "... .. ... T8C")           # tempo 140
            self.assertEqual(cell[("m3", 12, 0)], "E-6 01 v48 ...")          # natural harmonic at 12
            self.assertEqual([cell[("m3", r, 0)][:3] for r in (18, 20, 22)], ["E-5", "F-5", "F#5"])  # triplets
            self.assertEqual(cell[("m1", 0, 6)][:6], "C-3 02")               # kick (36) on the kit instrument
            kit = song["instruments"][2]["keymap"]
            self.assertEqual(song["samples"][next(k for k in kit if k["notes"] == "F#3")["sample"]]["name"], "kit_hat")  # 42
            res = api.check(str(d / "t.yaml"))
            self.assertEqual((res["errors"], [w for w in res["warnings"] if " rings at " not in w]), ([], []))  # no
            # anti-aliasing warnings either (the kit's kick rings at 53 Hz, G#1 +45 cents: its ring warning is expected)
            solo = api.load(d / "t.yaml")  # the guitar alone, for its pitches
            for c in solo["module"]["channels"]:
                c["muted"] = c["name"].startswith("Drums")
            api.render(solo, str(d / "t.wav"), base_dir=d)
            x, r, _ = read_audio(d / "t.wav")

            def hz(a, b):
                return dsp.pitch_of(x[int(a * r):int(b * r)][None], r)
            cents = lambda got, want: 1200 * np.log2(got / want)  # noqa: E731
            self.assertLess(abs(cents(hz(0.05, 0.5), 130.81)), 10)         # C-4
            self.assertLess(abs(cents(hz(1.53, 1.75), 293.66)), 10)        # the hammered D-5
            self.assertLess(abs(cents(hz(1.80, 1.87), 392.00)), 10)        # G-5 bent...
            self.assertLess(abs(cents(hz(2.12, 2.35), 440.00)), 10)        # ... a whole tone up

    def test_the_app_imports_a_tab_beside_it(self):
        from vulturetracker import gui
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tab(d / "riff.gp5")
            out, warnings = gui.import_beside(d / "riff.gp5")
            self.assertEqual((out.name, warnings), ("riff.yaml", ['Guitar Pro text decoded with cp1252.']))
            self.assertTrue((d / "riff_samples" / "kit_kick.wav").exists())
            out2, _ = gui.import_beside(d / "riff.gp5")
            self.assertEqual(out2.name, "riff-2.yaml")                        # nothing replaced

    # ---- the 0.9.0 audit (scratch/audit-100, agentC)

    def one_beat(self, d, name="Gtr", capo=0, notes=((5, 3),), harmonic=False):
        """A one-measure tab: a whole note of `notes` ((string, fret), ...) on a track called `name` with a capo at `capo`;
        imported, it returns the song."""
        song = M.Song()
        h = M.MeasureHeader(number=1, start=960)
        song.measureHeaders = [h]
        g = song.tracks[0]
        g.name, g.offset = name, capo
        g.measures = [M.Measure(g, h)]
        v = g.measures[0].voices[0]
        b = M.Beat(v, duration=M.Duration(value=1), start=960, status=M.BeatStatus.normal)
        for string, fret in notes:
            n = M.Note(b, value=fret, string=string, type=M.NoteType.normal, velocity=M.Velocities.forte)
            if harmonic:
                n.effect.harmonic = M.NaturalHarmonic()
            b.notes.append(n)
        v.beats.append(b)
        guitarpro.write(song, str(d / "t.gp5"))
        return gpimport.import_gp(d / "t.gp5", d / "t.yaml", d / "t_samples")[0]

    def test_a_capo_raises_the_pitch(self):
        # Guitar Pro writes frets from the capo; TuxGuitar sounds track offset + fret + string (MidiSequenceParser)
        with tempfile.TemporaryDirectory() as tmp:
            for capo, harmonic, want in ((0, False, "C-4"), (2, False, "D-4"), (2, True, "B-4")):
                song = self.one_beat(Path(tmp), capo=capo, notes=((5, 12 if harmonic else 3),), harmonic=harmonic)
                with self.subTest(capo=capo, harmonic=harmonic):
                    self.assertEqual(song["patterns"]["m1"]["data"].split()[1], want)  # A string (A-3): fret 3, or the octave harmonic

    def test_a_long_track_name_keeps_its_string_numbers(self):
        # "Großgroß..." grows by two letters when transliterated: the cut fell on " str N" and every string had one name
        with tempfile.TemporaryDirectory() as tmp:
            song = self.one_beat(Path(tmp), name="Großgroßgitarre", notes=((1, 0), (2, 0), (3, 0)))
            names = [c["name"] for c in song["module"]["channels"]]
            self.assertEqual([n[-5:] for n in names], ["str 1", "str 2", "str 3"])
            self.assertTrue(all(len(n) <= 20 and n.isascii() for n in names), names)


@unittest.skipIf(guitarpro is None, 'PyGuitarPro not installed')
class TestTapSlapPopInterchange(unittest.TestCase):
    flags = ('tapping', 'slapping', 'popping')

    @classmethod
    def tg_cases(cls):
        import xml.etree.ElementTree as ET
        for name, markings in (
                ('plain', {}), ('tap', {0: ['tapping']}), ('slap', {0: ['slapping']}),
                ('pop', {0: ['popping']}), ('mixed-chord', {0: ['tapping'], 1: ['popping']}),
                ('all-forward', {0: list(cls.flags)}), ('all-reverse', {0: list(reversed(cls.flags))}),
                ('tied-continuation', {3: ['slapping']}), ('two-voices', {3: ['tapping'], 4: ['popping']})):
            tree = ET.fromstring(TestTgInterchange.xml())
            notes = tree.findall('.//note')
            expected = [''] * len(notes)
            for index, markers in markings.items():
                for flag in markers:
                    ET.SubElement(notes[index], flag)
                expected[index] = next(flag for flag in reversed(cls.flags) if flag in markers)
            yield 'tg-' + name + '.tg', TestTgInterchange.archive(ET.tostring(tree, encoding='unicode')), 'tg-plain.tg', expected

    @classmethod
    def gp_cases(cls):
        for version in (3, 4, 5):
            for effect in ('none', *cls.flags):
                song = TestFadeInterchange.gp_song(version)
                for voice in song.tracks[0].measures[0].voices:
                    for beat in voice.beats:
                        beat.effect.fadeIn = False
                song.tracks[0].measures[0].voices[0].beats[0].effect.slapEffect = getattr(M.SlapEffect, effect)
                expected = [effect if effect != 'none' else ''] * 2 + ([''] if version == 5 else []) + ['']
                yield (f'gp{version}-{effect}.gp{version}', TestFadeInterchange.gp_bytes(version, song=song),
                       f'gp{version}-none.gp{version}', expected)
            if version == 5:
                song.tracks[0].measures[0].voices[0].beats[0].effect.slapEffect = M.SlapEffect.tapping
                song.tracks[0].measures[0].voices[1].beats[0].effect.slapEffect = M.SlapEffect.popping
                yield ('gp5-independent.gp5', TestFadeInterchange.gp_bytes(5, song=song),
                       'gp5-none.gp5', ['tapping', 'tapping', 'popping', ''])

    @classmethod
    def markings(cls, song):
        return [next((k for k in cls.flags if note.get(k)), '')
                for spec in song['score']['patterns'].values()
                for beat in sorted(spec['beats'], key=lambda b: (Fraction(*b['at']), b['voice']))
                for note in beat['notes']]

    def test_tg_per_note_flags_normalize_with_warning_and_roundtrip(self):
        import copy
        from vulturetracker import tgimport
        baseline = None
        for name, data, _, expected in self.tg_cases():
            with self.subTest(name=name):
                song, warnings = tgimport.read_tg(data)
                self.assertEqual(self.markings(song), expected)
                events = TestWrittenVoiceInterchange.plan(song)['events']
                if baseline is None:
                    baseline = events
                self.assertEqual(events, baseline)
                if 'all-' in name:
                    warning = next(w for w in warnings if 'tap/slap/pop conflicts' in w)
                    self.assertIn("'tapping': True", warning)
                    self.assertIn("'slapping': True", warning)
                    self.assertIn(warning, song['module']['message'])
                else:
                    self.assertFalse(any('tap/slap/pop conflicts' in w for w in warnings))
                exported, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                restored = tgimport.read_tg(exported)[0]
                self.assertEqual(TestTgInterchange.semantics(restored), TestTgInterchange.semantics(song))
                false = copy.deepcopy(song)
                for spec in false['score']['patterns'].values():
                    for beat in spec['beats']:
                        for note in beat['notes']:
                            for flag in self.flags:
                                note[flag] = False
                exported, _ = tgimport.native_to_tg(false, tgimport._raw(false), channels={'t1': {'program': 25, 'bank': 0}})
                self.assertEqual(self.markings(tgimport.read_tg(exported)[0]), [''] * len(expected))

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_expands_own_voice_beat_and_preserves_tied_flags(self):
        from vulturetracker import tgimport
        baselines = {}
        for name, data, baseline, expected in self.gp_cases():
            with self.subTest(name=name):
                song = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Techniques')
                self.assertEqual(self.markings(song), expected)
                events = TestWrittenVoiceInterchange.plan(song)['events']
                if name == baseline:
                    baselines[name] = events
                self.assertEqual(events, baselines[baseline])
                self.assertTrue(all(not any(k in b for k in self.flags) for p in song['score']['patterns'].values()
                                    for b in p['beats']))
                exported, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                self.assertEqual(self.markings(tgimport.read_tg(exported)[0]), expected)
        for version in (3, 4, 5):
            for flag in self.flags:
                with self.subTest(version=version, continuation=flag):
                    gp = TestFadeInterchange.gp_song(version)
                    gp.tracks[0].measures[0].voices[0].beats[1].effect.slapEffect = getattr(M.SlapEffect, flag)
                    song = gpimport._native_gp_song(gpimport._read_native_gp(
                        TestFadeInterchange.gp_bytes(version, song=gp)), 'Tie')
                    note = next(b for b in song['score']['patterns']['m1']['beats']
                                if b['voice'] == 0 and b['at'] == [1, 1])['notes'][0]
                    self.assertTrue(note[flag])
                    self.assertEqual(song['score']['ties'][0]['to']['note'], note['id'])

    def test_malformed_tg_techniques_refuse_before_publication(self):
        from vulturetracker import tgimport
        for flag in self.flags:
            for marker in (f'<{flag}>true</{flag}>', f'<{flag} value="1"/>',
                           f'<{flag}><value/></{flag}>', f'<{flag}/><{flag}/>'):
                with self.subTest(marker=marker), tempfile.TemporaryDirectory() as tmp:
                    src = Path(tmp) / 'invalid.tg'
                    src.write_bytes(TestTgInterchange.archive(TestTgInterchange.xml().replace('<ghostNote/>', marker)))
                    with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                        with self.assertRaises(ValueError):
                            tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                    self.assertEqual(list(Path(tmp).iterdir()), [src])
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                tgimport.read_tg(TestTgInterchange.archive(TestTgInterchange.xml().replace(
                    '<TGBeat>', f'<TGBeat><{flag}/>', 1)))

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_flagged_rest_empty_and_unknown_values_refuse_before_output(self):
        from guitarpro.gp3 import GP3File
        from guitarpro.gp4 import GP4File
        for version in (3, 4, 5):
            for flag in self.flags:
                for status in (M.BeatStatus.rest, M.BeatStatus.empty):
                    with self.subTest(version=version, flag=flag, status=status), tempfile.TemporaryDirectory() as tmp:
                        gp = TestFadeInterchange.gp_song(version)
                        first = gp.tracks[0].measures[0].voices[0].beats[0]
                        first.effect.fadeIn = False
                        first.effect.slapEffect = getattr(M.SlapEffect, flag)
                        first.status, first.notes = status, []
                        src = Path(tmp) / f'invalid.gp{version}'
                        src.write_bytes(TestFadeInterchange.gp_bytes(version, song=gp))
                        with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                            with self.assertRaisesRegex(ValueError, 'tap/slap/pop on a rest or empty beat'):
                                gpimport.import_gp(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples', native=True)
                        self.assertEqual(list(Path(tmp).iterdir()), [src])
            def invalid_effect(writer, beat):
                writer.writeU8(0x20)
                if version != 3:
                    writer.writeU8(0)
                writer.writeU8(4)
                if version == 3:
                    writer.writeI32(0)
            with self.subTest(version=version, unknown=4), tempfile.TemporaryDirectory() as tmp:
                with patch.object(GP3File if version == 3 else GP4File, 'writeBeatEffects', invalid_effect):
                    data = TestFadeInterchange.gp_bytes(version)
                src = Path(tmp) / f'invalid.gp{version}'
                src.write_bytes(data)
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaisesRegex(ValueError, 'SlapEffect'):
                        gpimport.import_gp(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples', native=True)
                self.assertEqual(list(Path(tmp).iterdir()), [src])


class TestSourcePanInterchange(unittest.TestCase):
    @staticmethod
    def xml(balance):
        return TestTgInterchange.xml().replace('<balance>64</balance>', f'<balance>{balance}</balance>')

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_pan_bytes_keep_mixer_and_add_exact_source_binding(self):
        from vulturetracker import tgimport
        for version in (3, 4, 5):
            for byte in range(17):
                with self.subTest(version=version, byte=byte):
                    gp = harmonic_tab([None], fret=5, tuning=64)
                    gp.tracks[0].channel.volume = 128
                    gp.tracks[0].channel.balance = byte * 8
                    source = TestFadeInterchange.gp_bytes(version, song=gp)
                    song = gpimport._native_gp_song(gpimport._read_native_gp(source), 'Pan')
                    self.assertEqual(song['module']['channels'][0]['pan'], byte * 4)
                    self.assertEqual(song['score']['tracks']['t1']['midi']['source_pan'],
                                     dict(value=max(byte * 8 - 1, 0), mixer_pan=byte * 4))
                    exported, _ = tgimport.native_to_tg(song, tgimport._raw(song),
                                                       channels={'t1': {'program': 25, 'bank': 0}})
                    restored = tgimport.read_tg(exported)[0]
                    self.assertEqual(restored['score']['tracks']['t1']['midi']['source_pan'],
                                     dict(value=max(byte * 8 - 1, 0), mixer_pan=byte * 4))
                    self.assertEqual(restored['module']['channels'][0].get('pan', 32), byte * 4)

    def test_tg_63_and_64_remain_distinct_and_do_not_change_playback(self):
        from vulturetracker import tgimport
        songs = [tgimport.read_tg(TestTgInterchange.archive(self.xml(value)))[0] for value in (63, 64)]
        self.assertEqual(songs[0]['module']['channels'], songs[1]['module']['channels'])
        self.assertEqual(TestWrittenVoiceInterchange.plan(songs[0])['events'],
                         TestWrittenVoiceInterchange.plan(songs[1])['events'])
        self.assertEqual(songs[0]['score']['tracks']['t1']['midi']['source_pan'], dict(value=63, mixer_pan=32))
        self.assertNotIn('source_pan', songs[1]['score']['tracks']['t1']['midi'])
        for song in songs:
            data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
            self.assertEqual(TestTgInterchange.semantics(tgimport.read_tg(data)[0]), TestTgInterchange.semantics(song))

    def test_tg_source_binding_obeys_anchor_and_existing_mixer_guards(self):
        import copy
        from vulturetracker import tgimport
        song = tgimport.read_tg(TestTgInterchange.archive(self.xml(63)))[0]
        stale = copy.deepcopy(song)
        stale['score']['tracks']['t1']['midi']['source_pan']['mixer_pan'] = 31
        data, _ = tgimport.native_to_tg(stale, tgimport._raw(stale), channels={'t1': {'program': 25, 'bank': 0}})
        self.assertNotIn('source_pan', tgimport.read_tg(data)[0]['score']['tracks']['t1']['midi'])
        edited = copy.deepcopy(song)
        edited['module']['channels'][0]['pan'] = 31
        with self.assertRaisesRegex(ValueError, 'per-string mixer'):
            tgimport.native_to_tg(edited, tgimport._raw(edited), channels={'t1': {'program': 25, 'bank': 0}})
        song['score']['tracks']['t1']['midi']['source_pan']['value'] = 7
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
        self.assertEqual(tgimport._xml(data).findtext('TGChannel/balance'), '7')

    def test_effects_still_refuse_before_publication(self):
        from vulturetracker import tgimport
        for balance in (0, 7, 62, 65, 127):
            with self.subTest(balance=balance), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / 'input.tg'
                src.write_bytes(TestTgInterchange.archive(self.xml(balance).replace('<chorus>0</chorus>', '<chorus>1</chorus>')))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaisesRegex(ValueError, 'non-neutral effects'):
                        tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                self.assertEqual(list(Path(tmp).iterdir()), [src])


class TestChordInterchange(unittest.TestCase):
    @staticmethod
    def xml(name='Literal & café', first=1, frets=(0, 3)):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(TestTgInterchange.xml())
        chord = ET.SubElement(root.find('.//TGBeat'), 'chord')
        ET.SubElement(chord, 'name').text = name
        ET.SubElement(chord, 'firstFret').text = str(first)
        for fret in frets:
            ET.SubElement(chord, 'string').text = str(fret) if fret >= 0 else None
        return ET.tostring(root, encoding='unicode')

    @staticmethod
    def gp_bytes(version, *, extended=None, name='Authored', first=1, frets=None,
                 strings=None, prefix=None, detail=None, second=None, empty=False, declared_size=None):
        import io
        from guitarpro.gp3 import GP3File
        from guitarpro.gp4 import GP4File
        from guitarpro.gp5 import GP5File
        extended = version == 5 if extended is None else extended
        count = 7 if extended and version != 3 else 6
        frets = list(frets if frets is not None else [0, 1, 0, 2, 3, -1] + ([-1] if count == 7 else []))
        song = harmonic_tab([None], fret=5, tuning=64)
        track = song.tracks[0]
        track.channel.volume = 128
        track.strings = [M.GuitarString(i + 1, 64 - i * 5) for i in range(strings or count)]
        beat = track.measures[0].voices[0].beats[0]
        beat.effect.chord = M.Chord(len(track.strings), name=name, firstFret=first)
        if empty:
            beat.status, beat.notes = M.BeatStatus.empty, []
        if second is not None:
            voice = track.measures[0].voices[1]
            other = M.Beat(voice, start=960, duration=M.Duration(value=4), status=M.BeatStatus.rest)
            if second != 'sparse':
                other.effect.chord = M.Chord(len(track.strings), name=second, firstFret=first)
            voice.beats.append(other)
        def write_chord(writer, chord):
            writer.writeU8(int(extended))
            if not extended:
                writer.writeIntByteSizeString(chord.name)
                writer.writeI32(first)
                if first:
                    for fret in frets:
                        writer.writeI32(fret)
                return
            basic = bytes([1, 0, 0, 0, 12, 0, 0, 255, 255, 255, 255, 0, 0, 0, 0, 0])
            writer.data.write(prefix if prefix is not None else
                              basic if version == 5 else bytes(25 if version == 3 else 16))
            width = 34 if version == 3 else 21
            encoded = chord.name.encode(writer.encoding)
            writer.writeU8(min(len(encoded), width) if declared_size is None else declared_size)
            writer.data.write(encoded[:width].ljust(width, b'\0'))
            if version != 3:
                writer.data.write(bytes(4))
            writer.writeI32(first)
            for fret in frets:
                writer.writeI32(fret)
            writer.data.write(detail if detail is not None else bytes(36 if version == 3 else 32))
        out = io.BytesIO()
        with patch.object({3: GP3File, 4: GP4File, 5: GP5File}[version], 'writeChord', write_chord):
            guitarpro.write(song, out, version={3: (3, 0, 0), 4: (4, 0, 6), 5: (5, 1, 0)}[version])
        return out.getvalue()

    def test_tg_literal_diagrams_auto_fret_empty_name_and_all_muted_roundtrip(self):
        from vulturetracker import tgimport
        baseline = tgimport.read_tg(TestTgInterchange.archive(TestTgInterchange.xml()))[0]
        for name, first, frets in (('Literal & café', 1, [0, 3]), ('', 7, [7, -1]),
                                   ('Automatic', 0, [7, 11]), ('Open', 0, [0, -1]),
                                   ('Literal muted', 0, [-1, -1]), ('N' * 4096, 24, [24, -1])):
            with self.subTest(name=name[:20], first=first):
                song = tgimport.read_tg(TestTgInterchange.archive(self.xml(name, first, frets)))[0]
                chord = song['score']['patterns']['m1']['beats'][0]['chord']
                self.assertEqual(chord, dict(name=name, first_fret=first, frets=frets))
                self.assertEqual(TestWrittenVoiceInterchange.plan(song)['events'],
                                 TestWrittenVoiceInterchange.plan(baseline)['events'])
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                self.assertEqual(TestTgInterchange.semantics(tgimport.read_tg(data)[0]), TestTgInterchange.semantics(song))

    def test_tg_shared_sparse_conflict_and_clear_export(self):
        import copy
        from vulturetracker import tgimport, tablature
        song = tgimport.read_tg(TestTgInterchange.archive(self.xml()))[0]
        beat = song['score']['patterns']['m1']['beats'][0]
        other = copy.deepcopy(beat)
        other.update(id='other', voice=1, notes=[])
        other.pop('chord')
        other.pop('text', None)
        song['score']['patterns']['m1']['beats'].append(other)
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
        restored = tgimport.read_tg(data)[0]
        simultaneous = [b for b in restored['score']['patterns']['m1']['beats'] if b['at'] == [0, 1]]
        self.assertEqual(len(simultaneous), 2)
        self.assertEqual(simultaneous[0]['chord'], simultaneous[1]['chord'])
        self.assertIsNot(simultaneous[0]['chord']['frets'], simultaneous[1]['chord']['frets'])
        other['chord'] = dict(beat['chord'], name='Conflict')
        with self.assertRaisesRegex(ValueError, 'conflicting.*chord'):
            tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
        other.pop('chord')
        cleared = tablature.apply_score_edit(song, dict(op='beat_set', pattern='m1', beat=dict(beat, chord=None)))
        data, _ = tgimport.native_to_tg(cleared, tgimport._raw(cleared), channels={'t1': {'program': 25, 'bank': 0}})
        self.assertTrue(all(b.get('chord') is None for p in tgimport.read_tg(data)[0]['score']['patterns'].values()
                            for b in p['beats']))

    def test_tg_invalid_chord_refuses_before_publication(self):
        from vulturetracker import tgimport
        cases = [self.xml(first=-1), self.xml(first=30), self.xml(frets=[1]), self.xml(frets=[1, 6]),
                 self.xml(first=0, frets=[7, 12]), self.xml(name='x' * 4097),
                 self.xml().replace('<name>Literal &amp; café</name>', '<name>A</name><name>B</name>'),
                 self.xml().replace('<string>0</string>', '<string><fret>0</fret></string>')]
        for data in cases:
            with self.subTest(xml=data[-150:]), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / 'invalid.tg'
                src.write_bytes(TestTgInterchange.archive(data))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                self.assertEqual(list(Path(tmp).iterdir()), [src])

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_basic_formats_shared_voices_and_native_tg_export(self):
        from vulturetracker import tgimport
        for version, extended in ((3, False), (3, True), (4, False), (4, True), (5, True)):
            for first in (0, 1, 7):
                if not extended and first == 0:
                    continue  # No frets are serialized by the legacy zero-first form.
                frets = [0, first or 1, -1, -1, -1, -1] + ([first or 1] if extended and version != 3 else [])
                with self.subTest(version=version, extended=extended, first=first):
                    data = self.gp_bytes(version, extended=extended, first=first, frets=frets,
                                         name='X' * 21, second='sparse' if version == 5 else None)
                    song = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Chords')
                    beats = song['score']['patterns']['m1']['beats']
                    self.assertTrue(all(b['chord'] == dict(name='X' * 21, first_fret=first, frets=frets) for b in beats))
                    exported, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                    self.assertEqual(TestTgInterchange.semantics(tgimport.read_tg(exported)[0])[3:],
                                     TestTgInterchange.semantics(song)[3:])

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_unmodified_pyguitarpro_basic_chord_defaults_are_admitted(self):
        import io
        for version in (3, 4, 5):
            with self.subTest(version=version):
                song = harmonic_tab([None], fret=5, tuning=64)
                track = song.tracks[0]
                chord = M.Chord(1, name='café', firstFret=1, strings=[0])
                track.measures[0].voices[0].beats[0].effect.chord = chord
                out = io.BytesIO()
                guitarpro.write(song, out, version={3: (3, 0, 0), 4: (4, 0, 6), 5: (5, 1, 0)}[version])
                native = gpimport._native_gp_song(gpimport._read_native_gp(out.getvalue()), 'Basic')
                self.assertEqual(native['score']['patterns']['m1']['beats'][0]['chord'],
                                 dict(name='café', first_fret=1, frets=[0]))

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_unrepresentable_chords_refuse_before_publication(self):
        cases = []
        for version in (3, 4, 5):
            cases += [(version, dict(frets=[-1] * (7 if version == 5 else 6)), 'name-only/all-muted'),
                      (version, dict(empty=True), 'chord on an empty beat'),
                      (version, dict(strings=2), 'played string outside')]
            size = 25 if version == 3 else 16
            cases.append((version, dict(extended=True, prefix=bytes([2]) + bytes(size - 1)), 'structured harmonic'))
            for position in ((0, 28) if version == 3 else (0, 16, 24, 31)):
                tail = bytearray(36 if version == 3 else 32)
                tail[position] = 1
                cases.append((version, dict(extended=True, detail=bytes(tail)), 'barres'))
        cases += [(3, dict(first=0), 'name-only/all-muted'), (4, dict(first=0), 'name-only/all-muted'),
                  (3, dict(extended=True, name='x' * 23), 'name length'),
                  (4, dict(extended=True, declared_size=22), 'name length'),
                  (5, dict(declared_size=22), 'name length'),
                  (5, dict(second='Different'), 'conflicting shared beat chord')]
        for version, kwargs, error in cases:
            with self.subTest(version=version, kwargs=kwargs), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / f'invalid.gp{version}'
                src.write_bytes(self.gp_bytes(version, **kwargs))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaisesRegex(ValueError, error):
                        gpimport.import_gp(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples', native=True)
                self.assertEqual(list(Path(tmp).iterdir()), [src])


class TestFadeInterchange(unittest.TestCase):
    @staticmethod
    def gp_song(version=5, second_voice=False):
        song = harmonic_tab([None], fret=5, tuning=64)
        song.tempo = 120
        track = song.tracks[0]
        track.channel.volume = 128
        track.strings = [M.GuitarString(1, 64), M.GuitarString(2, 59)]
        voice = track.measures[0].voices[0]
        head = voice.beats[0]
        head.notes.append(M.Note(head, value=3, string=2, velocity=95, type=M.NoteType.normal))
        head.effect.fadeIn = not second_voice
        continuation = M.Beat(voice, start=1920, duration=M.Duration(value=4), status=M.BeatStatus.normal)
        continuation.notes.append(M.Note(continuation, value=5, string=1, velocity=95, type=M.NoteType.tie))
        continuation.effect.fadeIn = True
        voice.beats.append(continuation)
        if version == 5:
            other = track.measures[0].voices[1]
            beat = M.Beat(other, start=960, duration=M.Duration(value=4), status=M.BeatStatus.normal)
            beat.notes.append(M.Note(beat, value=7, string=2, velocity=95, type=M.NoteType.normal))
            beat.effect.fadeIn = second_voice
            other.beats.append(beat)
        return song

    @staticmethod
    def gp_bytes(version=5, second_voice=False, song=None):
        import io
        out = io.BytesIO()
        guitarpro.write(song or TestFadeInterchange.gp_song(version, second_voice), out,
                        version={3: (3, 0, 0), 4: (4, 0, 6), 5: (5, 1, 0)}[version])
        return out.getvalue()

    def test_tg_fade_is_per_note_in_chords_voices_and_tied_continuations(self):
        import copy
        from vulturetracker import tgimport
        xml = TestTgInterchange.xml().replace('<ghostNote/>', '<ghostNote/><fadeIn/>').replace(
            'tiedNote="true"/>', 'tiedNote="true"><fadeIn/></note>')
        song, _ = tgimport.read_tg(TestTgInterchange.archive(xml))
        beats = song['score']['patterns']['m1']['beats']
        self.assertEqual([n.get('fade_in', False) for n in beats[0]['notes']], [True, False])
        later = song['score']['patterns']['m2']['beats']
        self.assertTrue(later[0]['notes'][0]['fade_in'])
        self.assertNotIn('fade_in', later[1]['notes'][0])
        baseline = tgimport.read_tg(TestTgInterchange.archive(TestTgInterchange.xml()))[0]
        events = TestWrittenVoiceInterchange.plan(song)['events']
        self.assertTrue(any(event['type'] == 'gain' for event in events))
        self.assertEqual([event for event in events if event['type'] != 'gain'],
                         TestWrittenVoiceInterchange.plan(baseline)['events'])
        exported, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
        restored = tgimport.read_tg(exported)[0]
        self.assertEqual(TestTgInterchange.semantics(restored), TestTgInterchange.semantics(song))
        explicit_false = copy.deepcopy(song)
        explicit_false['score']['patterns']['m1']['beats'][0]['notes'][1]['fade_in'] = False
        exported, _ = tgimport.native_to_tg(explicit_false, tgimport._raw(explicit_false),
                                           channels={'t1': {'program': 25, 'bank': 0}})
        self.assertEqual(TestTgInterchange.semantics(tgimport.read_tg(exported)[0]),
                         TestTgInterchange.semantics(song))

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_fade_expands_only_its_serialized_voice_beat(self):
        from vulturetracker import tgimport
        for version, second in ((3, False), (4, False), (5, False), (5, True)):
            with self.subTest(version=version, second_voice=second):
                gp = gpimport._read_native_gp(self.gp_bytes(version, second))
                song = gpimport._native_gp_song(gp, 'Fade')
                beats = song['score']['patterns']['m1']['beats']
                primary = [b for b in beats if b['voice'] == 0]
                self.assertEqual([n.get('fade_in', False) for n in primary[0]['notes']], [not second] * 2)
                self.assertTrue(primary[1]['notes'][0]['fade_in'])
                self.assertEqual(song['score']['ties'][0]['to']['note'], primary[1]['notes'][0]['id'])
                if version == 5:
                    other = next(b for b in beats if b['voice'] == 1)
                    self.assertEqual(other['notes'][0].get('fade_in', False), second)
                self.assertTrue(all('fade_in' not in b for b in beats))
                exported, _ = tgimport.native_to_tg(song, tgimport._raw(song),
                                                   channels={'t1': {'program': 25, 'bank': 0}})
                # GP stores voices in blocks; TG stores simultaneous voices
                # together. Compare written positions independently of storage.
                before = TestTgInterchange.semantics(song)[3:]
                after = TestTgInterchange.semantics(tgimport.read_tg(exported)[0])[3:]
                for expected, actual in zip(before, after):
                    self.assertEqual(sorted(actual, key=repr), sorted(expected, key=repr))

    def test_malformed_duplicate_and_misplaced_tg_fade_refuses_before_publication(self):
        from vulturetracker import tgimport
        for marker in ('<fadeIn>1</fadeIn>', '<fadeIn value="true"/>', '<fadeIn><curve/></fadeIn>',
                       '<fadeIn/><fadeIn/>'):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / 'invalid.tg'
                src.write_bytes(TestTgInterchange.archive(TestTgInterchange.xml().replace('<ghostNote/>', marker)))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                self.assertEqual(list(Path(tmp).iterdir()), [src])
        for marker in ('<TGBeat><fadeIn/>', '<voice direction="up"><fadeIn/>'):
            old = '<TGBeat>' if marker.startswith('<TGBeat>') else '<voice direction="up">'
            with self.subTest(marker=marker):
                with self.assertRaisesRegex(ValueError, 'unsupported'):
                    tgimport.read_tg(TestTgInterchange.archive(TestTgInterchange.xml().replace(old, marker, 1)))

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_flagged_rest_empty_and_shared_routes_refuse_before_publication(self):
        import copy
        cases = []
        for version in (3, 4, 5):
            for status in (M.BeatStatus.rest, M.BeatStatus.empty):
                song = self.gp_song(version)
                beat = song.tracks[0].measures[0].voices[0].beats[0]
                beat.status, beat.notes = status, []
                cases.append((version, status.name, song, 'fade-in on a rest or empty beat'))
            for primary, secondary, port in ((0, 1, 1), (0, 1, 2), (2, 1, 1), (1, 3, 1)):
                song = self.gp_song(version)
                other = copy.deepcopy(song.tracks[0])
                other.number, other.port = 2, port
                other.channel.channel, other.channel.effectChannel = primary, secondary
                song.tracks.append(other)
                cases.append((version, (primary, secondary, port), song, 'fade-in shares MIDI routing'))
        for version, kind, song, error in cases:
            with self.subTest(version=version, kind=kind), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / f'invalid.gp{version}'
                src.write_bytes(self.gp_bytes(version, song=song))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaisesRegex(ValueError, error):
                        gpimport.import_gp(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples', native=True)
                self.assertEqual(list(Path(tmp).iterdir()), [src])
        # Disjoint routes remain representable, and the refusal is scoped to fade.
        for fade, routes in ((True, (2, 3)), (False, (0, 1))):
            song = self.gp_song()
            other = copy.deepcopy(song.tracks[0])
            other.number = 2
            other.channel.channel, other.channel.effectChannel = routes
            song.tracks.append(other)
            if not fade:
                for track in song.tracks:
                    for voice in track.measures[0].voices:
                        for beat in voice.beats:
                            beat.effect.fadeIn = False
            result = gpimport._native_gp_song(gpimport._read_native_gp(self.gp_bytes(song=song)), 'Routes')
            self.assertEqual(len(result['score']['tracks']), 2)


class TestStrokeInterchange(unittest.TestCase):
    @staticmethod
    def gp_bytes(version, direction='down', value=16, pick='none', *, raw_stroke=None, other=None):
        import io
        from contextlib import nullcontext
        from guitarpro.gp3 import GP3File
        song = harmonic_tab([None], fret=5, tuning=64)
        song.tempo = 120
        track = song.tracks[0]
        track.channel.volume = 128
        track.strings = [M.GuitarString(1, 64), M.GuitarString(2, 59)]
        beat = track.measures[0].voices[0].beats[0]
        beat.notes.append(M.Note(beat, value=3, string=2, velocity=95, type=M.NoteType.normal))
        beat.notes[0].effect.letRing = True
        beat.effect.stroke = M.BeatStroke(getattr(M.BeatStrokeDirection, direction), value)
        beat.effect.pickStroke = getattr(M.BeatStrokeDirection, pick)
        if other is not None:
            voice = track.measures[0].voices[1]
            second = M.Beat(voice, start=960, duration=M.Duration(value=16), status=M.BeatStatus.rest)
            second.effect.stroke = M.BeatStroke(getattr(M.BeatStrokeDirection, other), 16 if other != 'none' else 0)
            voice.beats.append(second)
        def write_raw(writer, stroke):
            for byte in raw_stroke:
                writer.writeI8(byte)
        out = io.BytesIO()
        with patch.object(GP3File, 'writeBeatStroke', write_raw) if raw_stroke is not None else nullcontext():
            guitarpro.write(song, out, version={3: (3, 0, 0), 4: (4, 0, 6), 5: (5, 1, 0)}[version])
        return out.getvalue()

    def test_gp_versions_direction_rates_pick_and_tg_roundtrip(self):
        from vulturetracker import tgimport
        for version in (3, 4, 5):
            for direction in ('up', 'down'):
                for value in (4, 8, 16, 32, 64):
                    with self.subTest(version=version, direction=direction, value=value):
                        pick = 'up' if version != 3 else 'none'
                        gp = gpimport._read_native_gp(self.gp_bytes(version, direction, value, pick))
                        song = gpimport._native_gp_song(gp, 'Strokes')
                        beat = song['score']['patterns']['m1']['beats'][0]
                        self.assertEqual(beat['stroke'], dict(direction=direction, value=value))
                        self.assertEqual(beat.get('pick_stroke'), pick if version != 3 else None)
                        self.assertTrue(beat['notes'][0]['let_ring'])
                        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                        restored = tgimport.read_tg(data)[0]
                        self.assertEqual(TestTgInterchange.semantics(restored)[3:], TestTgInterchange.semantics(song)[3:])

    def test_gp_raw_byte_one_zero_and_invalid_before_publication(self):
        for version in (3, 4, 5):
            for raw, expected in (((1, 0), 64), ((0, 1), 64), ((0, 0), None)):
                with self.subTest(version=version, raw=raw):
                    gp = gpimport._read_native_gp(self.gp_bytes(version, raw_stroke=raw))
                    song = gpimport._native_gp_song(gp, 'Raw strokes')
                    stroke = song['score']['patterns']['m1']['beats'][0].get('stroke')
                    self.assertEqual(stroke['value'] if stroke else None, expected)
                    if stroke:
                        self.assertEqual(stroke['direction'], ('up' if version == 5 else 'down') if raw[0]
                                         else ('down' if version == 5 else 'up'))
            for raw in ((7, 0), (-1, 0), (4, 5)):
                with self.subTest(version=version, raw=raw), tempfile.TemporaryDirectory() as tmp:
                    folder = Path(tmp)
                    src = folder / f'in.gp{version}'
                    src.write_bytes(self.gp_bytes(version, raw_stroke=raw))
                    with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                        with self.assertRaisesRegex(ValueError, 'stroke bytes'):
                            gpimport.import_gp(src, folder / 'song.yaml', folder / 'samples', native=True)
                    self.assertEqual(list(folder.iterdir()), [src])

    def test_gp5_shared_cohort_and_conflicts_gp3_pick_loss(self):
        for version in (4, 5):
            for pick in ('none', 'up', 'down'):
                gp = gpimport._read_native_gp(self.gp_bytes(version, direction='none', value=0, pick=pick))
                song = gpimport._native_gp_song(gp, 'Pick only')
                entry = song['score']['patterns']['m1']['beats'][0]
                self.assertNotIn('stroke', entry)
                self.assertEqual(entry.get('pick_stroke'), None if pick == 'none' else pick)
        for other in ('none', 'down'):
            gp = gpimport._read_native_gp(self.gp_bytes(5, other=other))
            song = gpimport._native_gp_song(gp, 'Shared')
            beats = song['score']['patterns']['m1']['beats']
            self.assertEqual(len(beats), 2)
            self.assertTrue(all(b['stroke'] == {'direction': 'down', 'value': 16} for b in beats))
            self.assertEqual(beats[1]['notes'], [])
        gp = gpimport._read_native_gp(self.gp_bytes(5, other='up'))
        with self.assertRaisesRegex(ValueError, 'conflicting shared beat stroke'):
            gpimport._native_gp_song(gp, 'Conflict')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            src = folder / 'conflict.gp5'
            src.write_bytes(self.gp_bytes(5, other='up'))
            with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                with self.assertRaisesRegex(ValueError, 'conflicting shared beat stroke'):
                    gpimport.import_gp(src, folder / 'song.yaml', folder / 'samples', native=True)
            self.assertEqual(list(folder.iterdir()), [src])
        # GP3's writer silently discards pick metadata; reject it in a model
        # preflight, rather than pretending it can be recovered from the bytes.
        gp = gpimport._read_native_gp(self.gp_bytes(3, pick='up'))
        self.assertEqual(gp.tracks[0].measures[0].voices[0].beats[0].effect.pickStroke, M.BeatStrokeDirection.none)
        gp.tracks[0].measures[0].voices[0].beats[0].effect.pickStroke = M.BeatStrokeDirection.up
        with self.assertRaisesRegex(ValueError, 'not representable in GP3'):
            gpimport._native_gp_song(gp, 'Lost pick')

    def test_tg_shared_metadata_defaults_and_refusals(self):
        import io
        import zipfile
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport
        root = ET.fromstring(TestTgInterchange.xml())
        beat = root.find('.//TGBeat')
        ET.SubElement(beat, 'stroke', direction='down', value='16')
        ET.SubElement(beat, 'pickStroke').text = 'up'
        voice = beat.findall('voice')[1]
        voice.set('empty', 'false')
        voice.find('duration').set('value', '16')
        song, _ = tgimport.read_tg(TestTgInterchange.archive(ET.tostring(root, encoding='unicode')))
        cohort = song['score']['patterns']['m1']['beats'][:2]
        self.assertTrue(all(b['stroke'] == {'direction': 'down', 'value': 16} and b['pick_stroke'] == 'up' for b in cohort))
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            written = ET.fromstring(archive.read('content.xml')).find('.//TGBeat')
        self.assertEqual(len(written.findall('stroke')), 1)
        self.assertEqual(len(written.findall('pickStroke')), 1)
        self.assertEqual(TestTgInterchange.semantics(tgimport.read_tg(data)[0]), TestTgInterchange.semantics(song))
        # Model accepts sparse/nullable shared metadata. Export resolves one
        # nonnull value across the cohort without mutating the authoring source.
        cohort[1]['stroke'], cohort[1]['pick_stroke'] = None, None
        sparse, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
        self.assertIsNone(cohort[1]['stroke'])
        self.assertEqual(TestTgInterchange.semantics(tgimport.read_tg(sparse)[0]),
                         TestTgInterchange.semantics(tgimport.read_tg(data)[0]))
        original = TestTgInterchange.xml()
        default = original.replace('<text>', '<stroke direction="none" value="0"/><text>', 1)
        plain, _ = tgimport.read_tg(TestTgInterchange.archive(default))
        self.assertNotIn('stroke', plain['score']['patterns']['m1']['beats'][0])
        for markup in ('<stroke direction="up" value="0"/>', '<stroke direction="down" value="128"/>',
                       '<stroke direction="none" value="16"/>', '<stroke direction="side" value="16"/>',
                       '<stroke direction="up" value="16">junk</stroke>', '<pickStroke>none</pickStroke>',
                       '<pickStroke extra="x">up</pickStroke>', '<pickStroke>up</pickStroke><pickStroke>down</pickStroke>'):
            with self.subTest(markup=markup), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                src = folder / 'in.tg'
                src.write_bytes(TestTgInterchange.archive(original.replace('<text>', markup + '<text>', 1)))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(src, folder / 'song.yaml', folder / 'samples')
                self.assertEqual(list(folder.iterdir()), [src])


@unittest.skipIf(guitarpro is None, 'PyGuitarPro not installed')
class TestWrittenVoiceInterchange(unittest.TestCase):
    kinds = ('same-pitch', 'staggered', 'stroke', 'tie', 'tie-boundary', 'repeat')

    @staticmethod
    def xml(kind):
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport
        root = ET.fromstring(TestTgInterchange.xml())
        song = root.find('TGSong')
        song.remove(song.findall('TGMeasureHeader')[1])
        header = song.find('TGMeasureHeader')
        header.find('tempo').text = '120'
        if kind == 'repeat':
            ET.SubElement(header, 'repeatClose').text = '1'
        track = song.find('TGTrack')
        track.find('offset').text = '0'
        for old in track.findall('TGMeasure'):
            track.remove(old)
        measure = ET.SubElement(track, 'TGMeasure')
        def beat(at, specs, stroke=False):
            b = ET.SubElement(measure, 'TGBeat')
            ET.SubElement(b, 'preciseStart').text = str(tgimport.QUARTER * (1 + at))
            if stroke:
                ET.SubElement(b, 'stroke', direction='down', value='16')
            for vi in (0, 1):
                spec = specs.get(vi)
                v = ET.SubElement(b, 'voice', empty='false' if spec else 'true')
                ET.SubElement(v, 'duration', value=str(spec[0] if spec else 4))
                if spec:
                    for string, fret, tied in spec[1]:
                        note = ET.SubElement(v, 'note', string=str(string), value=str(fret), velocity='95')
                        if tied:
                            note.set('tiedNote', 'true')
        primary = [(1, 5, False)] + ([(2, 3, False)] if kind == 'stroke' else [])
        beat(0, {0: (1 if kind == 'tie-boundary' else 4, primary),
                 **({1: (16, [(1, 5, False)])} if kind != 'staggered' else {1: (8, [])})},  # TG closes voice holes on opening
             stroke=kind == 'stroke')
        if kind == 'staggered':
            beat(Fraction(1, 2), {1: (16, [(1, 5, False)])})
        if kind == 'tie':
            beat(1, {0: (4, [(1, 5, True)])})
        if kind == 'tie-boundary':
            ET.SubElement(song, 'TGMeasureHeader')
            measure = ET.SubElement(track, 'TGMeasure')
            beat(4, {0: (4, [(1, 5, True)]), 1: (16, [(1, 5, False)])})
        return ET.tostring(root, encoding='unicode')

    @staticmethod
    def gp_bytes(kind):
        import io
        song = harmonic_tab([None], fret=5, tuning=64)
        song.tempo = 120
        track = song.tracks[0]
        track.channel.volume = 128
        track.strings = [M.GuitarString(1, 64), M.GuitarString(2, 59)]
        measure = track.measures[0]
        first = measure.voices[0].beats[0]
        if kind == 'repeat':
            song.measureHeaders[0].repeatClose = 1
        if kind == 'stroke':
            first.effect.stroke = M.BeatStroke(M.BeatStrokeDirection.down, 16)
            first.notes.append(M.Note(first, string=2, value=3, velocity=95, type=M.NoteType.normal))
        voice = measure.voices[1]
        if kind == 'staggered':
            voice.beats.append(M.Beat(voice, start=960, duration=M.Duration(value=8), status=M.BeatStatus.rest))
        second = M.Beat(voice, start=1440 if kind == 'staggered' else 960,
                        duration=M.Duration(value=16), status=M.BeatStatus.normal)
        second.notes.append(M.Note(second, string=1, value=5, velocity=95, type=M.NoteType.normal))
        voice.beats.append(second)
        if kind == 'tie':
            voice = measure.voices[0]
            continuation = M.Beat(voice, start=1920, duration=M.Duration(value=4), status=M.BeatStatus.normal)
            continuation.notes.append(M.Note(continuation, string=1, value=5, velocity=95, type=M.NoteType.tie))
            voice.beats.append(continuation)
        if kind == 'tie-boundary':
            first.duration = M.Duration(value=1)
            header = M.MeasureHeader(number=2, start=4800)
            song.measureHeaders.append(header)
            measure = M.Measure(track, header)
            track.measures.append(measure)
            for vi, value in ((0, 4), (1, 16)):
                voice = measure.voices[vi]
                beat = M.Beat(voice, start=4800, duration=M.Duration(value=value), status=M.BeatStatus.normal)
                beat.notes.append(M.Note(beat, string=1, value=5, velocity=95,
                                         type=M.NoteType.tie if vi == 0 else M.NoteType.normal))
                voice.beats.append(beat)
        out = io.BytesIO()
        guitarpro.write(song, out, version=(5, 1, 0))
        return out.getvalue()

    @staticmethod
    def plan(song):
        from vulturetracker import tgimport, tablature
        raw = tgimport._raw(song)
        repeated = tablature.repeat_projection(song, raw, 48000)
        return repeated.plan if repeated is not None else tablature.playback_plan(song, raw, 48000)

    def test_tg_gp5_two_voice_roundtrip_identity_order_and_gates(self):
        from vulturetracker import tgimport
        for kind in self.kinds:
            for source in ('tg', 'gp5'):
                with self.subTest(kind=kind, source=source):
                    if source == 'tg':
                        song = tgimport.read_tg(TestTgInterchange.archive(self.xml(kind)))[0]
                    else:
                        parsed = gpimport._read_native_gp(self.gp_bytes(kind))
                        song = gpimport._native_gp_song(parsed, 'Two voices')
                    plan = self.plan(song)
                    attacks = [e for e in plan['events'] if e['type'] == 'note_on']
                    releases = {e['id']: Fraction(*e['at']) for e in plan['events'] if e['type'] == 'note_off'}
                    self.assertEqual(len(attacks), 4 if kind == 'repeat' else 3 if kind in ('stroke', 'tie-boundary') else 2)
                    self.assertEqual(len({e['id'] for e in attacks}), len(attacks))
                    same_parent = [e for e in attacks if e['ch'] == 0]
                    self.assertTrue(all(e.get('context') and e['context_open'] and e['context_close'] for e in same_parent))
                    self.assertEqual(len({e['context'] for e in same_parent}), len(same_parent))
                    self.assertEqual([e['voice'] for e in same_parent],
                                     [0, 1, 1] if kind == 'tie-boundary' else [0, 1] * (2 if kind == 'repeat' else 1))
                    first, second = same_parent[:2]
                    self.assertEqual(releases[first['id']], 5 if kind == 'tie-boundary' else 2 if kind == 'tie' else 1)
                    self.assertEqual(releases[second['id']], Fraction(3, 4) if kind == 'staggered' else Fraction(1, 4))
                    self.assertEqual(Fraction(*second['at']), Fraction(1, 2) if kind == 'staggered'
                                     else Fraction(1, 120) if kind == 'stroke' else 0)
                    data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                    restored = tgimport.read_tg(data)[0]
                    musical = lambda p: [(e['type'], e['at'], e['voice'], e['ch'], e['pitch'], e.get('velocity'),
                                           e.get('context'), e.get('context_open'), e.get('context_close'))
                                          for e in p['events'] if e['type'] in ('note_on', 'note_off')]
                    self.assertEqual(musical(self.plan(restored)), musical(plan))
                    self.assertEqual(len(restored['score']['ties']), len(song['score']['ties']))


class TestLyricsInterchange(unittest.TestCase):
    @staticmethod
    def xml(text='', start=1):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(TestTgInterchange.xml())
        lyric = root.find('.//TGLyric')
        lyric.set('from', str(start))
        lyric.text = text
        return ET.tostring(root, encoding='unicode').replace('\r', '&#13;')

    @staticmethod
    def gp_song(text='', start=1):
        song = harmonic_tab([None], fret=5, tuning=64)
        # Neutral mixer is required for the existing strict native TG exporter.
        song.tracks[0].channel.volume = 128
        song.lyrics.trackChoice = 1
        song.lyrics.lines[0].lyrics = text
        song.lyrics.lines[0].startingMeasure = start
        return song

    @staticmethod
    def lyrics(song, track='t1'):
        return song['score']['tracks'][track].get('lyrics', dict(from_measure=1, text=''))

    @classmethod
    def tg_cases(cls):
        # The four cases already qualified against installed TG 2.1.0.
        for name, text, start in (
                ('plain', '', 1),
                ('spaces', ' leading  blanks hy-phen + _ [literal] trailing  ', 1),
                ('crlf', 'one\r\ntwo\nthree\rfour', 2),
                ('dormant', 'beyond end', 3)):
            yield 'tg-' + name + '.tg', TestTgInterchange.archive(cls.xml(text, start)), dict(from_measure=start, text=text)

    @classmethod
    def gp_cases(cls):
        # The six existing source cases include two deliberate TG-loss cases.
        for version in (4, 5):
            for variant in ('plain', 'first', 'extra'):
                text = '' if variant == 'plain' else 'one  two\r\nhy-phen'
                song = cls.gp_song(text)
                if variant == 'extra':
                    song.lyrics.lines[1].lyrics = 'second GP line retained only in source'
                    song.lyrics.lines[1].startingMeasure = 2
                yield (f'gp{version}-{variant}.gp{version}', TestFadeInterchange.gp_bytes(version, song=song),
                       dict(from_measure=1, text=text), variant == 'extra')

    def test_tg_exact_text_start_roundtrip_and_unchanged_native_events(self):
        from vulturetracker import tgimport, tablature
        import io
        import zipfile
        import xml.etree.ElementTree as ET
        baseline = tgimport.read_tg(TestTgInterchange.archive(self.xml()))[0]
        events = tablature.playback_plan(baseline, tgimport._raw(baseline))['events']
        cases = list(self.tg_cases())
        for text, start in (('', 3), ('\t café 🎵 <&> \u00a0\u2028', 2147483647), ('🎵' * 65536, 1)):
            cases.append(('extended', TestTgInterchange.archive(self.xml(text, start)), dict(from_measure=start, text=text)))
        for name, source, expected in cases:
            with self.subTest(case=name, start=expected['from_measure']):
                song = tgimport.read_tg(source)[0]
                self.assertEqual(self.lyrics(song), expected)
                self.assertEqual(tablature.playback_plan(song, tgimport._raw(song))['events'], events)
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                restored = tgimport.read_tg(data)[0]
                self.assertEqual(self.lyrics(restored), expected)
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    xml = archive.read('content.xml')
                self.assertNotIn(b'\r', xml)
                if '\r' in expected['text']:
                    self.assertIn(b'&#13;', xml)
                node = ET.fromstring(xml).find('.//TGLyric')
                self.assertEqual(node.text or '', expected['text'])
                self.assertEqual(int(node.get('from')), expected['from_measure'])

    def test_tg_invalid_lyrics_refuse_before_publication(self):
        from vulturetracker import tgimport
        valid = self.xml('raw')
        cases = [self.xml('', start) for start in (0, -1, 2147483648, 'no')]
        cases += [self.xml('x' * 65537), valid.replace('>raw</TGLyric>', '><text>raw</text></TGLyric>'),
                  valid.replace('<TGLyric ', '<TGLyric extra="1" '),
                  valid.replace('</TGLyric>', '</TGLyric><TGLyric from="1"/>')]
        for xml in cases:
            with self.subTest(xml=xml[:80]), tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / 'invalid.tg'
                src.write_bytes(TestTgInterchange.archive(xml))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples')
                self.assertEqual(list(Path(tmp).iterdir()), [src])

    def test_tg_export_refuses_xml_illegal_text_without_mutation(self):
        import copy
        from vulturetracker import tgimport
        song = tgimport.read_tg(TestTgInterchange.archive(self.xml()))[0]
        for char in ('\0', '\x0b', '\x1f', '\ud800', '\udfff', '\ufffe', '\uffff'):
            with self.subTest(codepoint=ord(char)):
                song['score']['tracks']['t1']['lyrics'] = dict(from_measure=1, text='before' + char + 'after')
                before = copy.deepcopy(song)
                with self.assertRaisesRegex(ValueError, 'lyrics text.*XML 1.0'):
                    tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                self.assertEqual(song, before)

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_first_line_ownership_and_empty_start_metadata(self):
        import copy
        from vulturetracker import tgimport, tablature
        baseline = gpimport._native_gp_song(gpimport._read_native_gp(
            TestFadeInterchange.gp_bytes(5, song=self.gp_song())), 'Lyrics')
        for name, data, expected, refused in self.gp_cases():
            with self.subTest(case=name):
                if refused:
                    with self.assertRaisesRegex(ValueError, 'lyrics line 2.*additional'):
                        gpimport._native_gp_song(gpimport._read_native_gp(data), 'Lyrics')
                    continue
                song = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Lyrics')
                self.assertEqual(self.lyrics(song), expected)
                self.assertEqual(tablature.playback_plan(song, tgimport._raw(song))['events'],
                                 tablature.playback_plan(baseline, tgimport._raw(baseline))['events'])
                exported, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})
                self.assertEqual(self.lyrics(tgimport.read_tg(exported)[0]), expected)
        for version in (4, 5):
            for text, start in (('', 3), ('dormant', 2147483647)):
                gp = self.gp_song(text, start)
                second = copy.deepcopy(gp.tracks[0])
                second.number = 2
                second.channel.channel = second.channel.effectChannel = 1
                gp.tracks.append(second)
                gp.lyrics.trackChoice = 2
                native = gpimport._native_gp_song(gpimport._read_native_gp(
                    TestFadeInterchange.gp_bytes(version, song=gp)), 'Lyrics')
                self.assertNotIn('lyrics', native['score']['tracks']['t1'])
                self.assertEqual(self.lyrics(native, 't2'), dict(from_measure=start, text=text))

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_unsupported_lyrics_refuse_before_publication(self):
        for version in (4, 5):
            for case in ('owner0', 'owner2', 'owner_negative', 'extra', 'extra_spaces',
                         'extra_start', 'unused_start', 'start0', 'start_negative', 'oversized'):
                song, error = self.gp_song('text'), 'lyrics'
                if case.startswith('owner'):
                    song.lyrics.trackChoice = {'owner0': 0, 'owner2': 2, 'owner_negative': -1}[case]
                elif case in ('extra', 'extra_spaces'):
                    song.lyrics.lines[4].lyrics = ' ' if case == 'extra_spaces' else 'another verse'
                    error = 'lyrics line 5'
                elif case == 'extra_start':
                    song.lyrics.lines[3].startingMeasure = 2
                    error = 'lyrics line 4.*metadata'
                elif case == 'unused_start':
                    song.lyrics.trackChoice = 0
                    song.lyrics.lines[0].lyrics = ''
                    song.lyrics.lines[0].startingMeasure = 2
                    error = 'lyrics line 1.*metadata'
                elif case.startswith('start'):
                    song.lyrics.lines[0].startingMeasure = 0 if case == 'start0' else -1
                else:
                    song.lyrics.lines[0].lyrics = 'x' * 65537
                with self.subTest(version=version, case=case), tempfile.TemporaryDirectory() as tmp:
                    src = Path(tmp) / f'invalid.gp{version}'
                    data = TestFadeInterchange.gp_bytes(version, song=song)
                    src.write_bytes(data)
                    with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                        with self.assertRaisesRegex(ValueError, error):
                            gpimport.import_gp(src, Path(tmp) / 'song.yaml', Path(tmp) / 'samples', native=True)
                    self.assertEqual(list(Path(tmp).iterdir()), [src])
                    self.assertEqual(src.read_bytes(), data)

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_unused_empty_sentinels_and_xml_only_export_constraint(self):
        from vulturetracker import tgimport
        for version in (3, 4, 5):
            for start in (0, 1):
                gp = self.gp_song()
                gp.lyrics.trackChoice = 0
                for line in gp.lyrics.lines:
                    line.startingMeasure = start
                song = gpimport._native_gp_song(gpimport._read_native_gp(
                    TestFadeInterchange.gp_bytes(version, song=gp)), 'Empty')
                self.assertNotIn('lyrics', song['score']['tracks']['t1'])
        # GP/native text is not XML: retain a control character there, and
        # refuse specifically at the TG export boundary rather than stripping it.
        song = gpimport._native_gp_song(gpimport._read_native_gp(
            TestFadeInterchange.gp_bytes(5, song=self.gp_song('a\x0bb'))), 'Control')
        self.assertEqual(self.lyrics(song)['text'], 'a\x0bb')
        with self.assertRaisesRegex(ValueError, 'lyrics text.*XML 1.0'):
            tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 25, 'bank': 0}})

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_real_saved_yaml_and_tg_output_retain_raw_lyrics(self):
        import yaml
        from vulturetracker import tgimport
        text = ' leading  café\r\nhy-phen + _ [literal]\tlast  '
        for kind in ('tg', 'gp4', 'gp5'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source, output, samples = folder / ('source.' + kind), folder / 'song.yaml', folder / 'samples'
                if kind == 'tg':
                    source.write_bytes(TestTgInterchange.archive(self.xml(text, 3)))
                    song, _ = tgimport.import_tg(source, output, samples)
                else:
                    source.write_bytes(TestFadeInterchange.gp_bytes(int(kind[-1]), song=self.gp_song(text, 3)))
                    song, _ = gpimport.import_gp(source, output, samples, native=True)
                written = yaml.safe_load(output.read_text(encoding='utf-8'))
                self.assertEqual(self.lyrics(written), dict(from_measure=3, text=text))
                self.assertEqual(written, song)
                self.assertTrue(list(samples.glob('*.wav')))
                data, _ = tgimport.native_to_tg(written, tgimport._raw(written),
                                                 channels={'t1': {'program': 25, 'bank': 0}})
                saved = folder / 'roundtrip.tg'
                saved.write_bytes(data)
                self.assertEqual(self.lyrics(tgimport.read_tg(saved.read_bytes())[0]), self.lyrics(written))


class TestPercussionInterchange(unittest.TestCase):
    @staticmethod
    def written_notes(song):
        endpoints = {}
        notes = []
        for oid, name in zip(song['score']['order_ids'], song['orders']):
            for beat in song['score']['patterns'][name]['beats']:
                for note in beat['notes']:
                    identity = (oid, beat['voice'], tuple(beat['at']), note['string'],
                                note['fret'], note['pitch'], note['velocity'])
                    notes.append(identity)
                    endpoints[oid, note['id']] = identity
        ties = [(endpoints[t['from']['occurrence'], t['from']['note']],
                 endpoints[t['to']['occurrence'], t['to']['note']]) for t in song['score']['ties']]
        return sorted(notes), sorted(ties)

    @staticmethod
    def xml():
        import xml.etree.ElementTree as ET
        root = ET.fromstring(TestTgInterchange.xml())
        root.find('.//TGChannel/bank').text = '128'
        root.find('.//TGChannel/program').text = '0'
        root.find('.//TGTrack/offset').text = '0'
        for string in root.findall('.//TGString'):
            string.text = '0'
        for note, key in zip(root.findall('.//note'), (36, 42, 38, 38, 42, 1, 100)):
            for child in list(note):
                note.remove(child)
            note.set('value', str(key))
        root.find('.//TGLyric').text = 'kick  snare\r\nhat'
        headers = root.findall('.//TGMeasureHeader')
        ET.SubElement(headers[0], 'repeatOpen')
        ET.SubElement(headers[1], 'repeatClose').text = '1'
        return ET.tostring(root, encoding='unicode').replace('\r', '&#13;')

    @staticmethod
    def gp_song(key=99, version=5):
        song = TestLyricsInterchange.gp_song('drum  words' if version != 3 else '')
        track = song.tracks[0]
        track.isPercussionTrack = True
        track.channel.channel = track.channel.effectChannel = 9
        track.channel.instrument = 0
        track.strings = [M.GuitarString(1, 0), M.GuitarString(2, 0)]
        voice = track.measures[0].voices[0]
        voice.beats[0].notes[0].value = key
        tied = M.Beat(voice, start=1920, duration=M.Duration(value=4), status=M.BeatStatus.normal)
        tied.notes.append(M.Note(tied, value=key, string=1, velocity=95, type=M.NoteType.tie))
        voice.beats.append(tied)
        if version == 5:
            other = track.measures[0].voices[1]
            beat = M.Beat(other, start=960, duration=M.Duration(value=4), status=M.BeatStatus.normal)
            beat.notes.append(M.Note(beat, value=42, string=2, velocity=79, type=M.NoteType.normal))
            other.beats.append(beat)
        song.measureHeaders[0].isRepeatOpen = True
        song.measureHeaders[0].repeatClose = 1
        return song

    def test_tg_keys_lanes_voices_ties_repeats_lyrics_and_routes_roundtrip(self):
        import io
        import zipfile
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport, tablature
        song, _ = tgimport.read_tg(TestTgInterchange.archive(self.xml()))
        notes = [n for p in song['score']['patterns'].values() for b in p['beats'] for n in b['notes']]
        self.assertEqual([n['pitch'] for n in notes], [36, 42, 38, 38, 42, 1, 100])
        self.assertTrue(all(n['fret'] == n['pitch'] for n in notes))
        self.assertEqual([n['string'] for n in notes], [1, 2, 1, 1, 2, 1, 1])
        self.assertEqual(len(song['score']['ties']), 1)
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 0, 'bank': 128}})
        restored, _ = tgimport.read_tg(data)
        self.assertEqual(restored['score'], song['score'])
        before = tablature.repeat_projection(song, tgimport._raw(song)).plan
        after = tablature.repeat_projection(restored, tgimport._raw(restored)).plan
        self.assertEqual(after['events'], before['events'])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            root = ET.fromstring(archive.read('content.xml'))
        self.assertEqual({p.get('key'): p.get('value') for p in root.findall('.//TGChannelParameter')},
                         {'gm-channel-1': '9', 'gm-channel-2': '9'})
        with self.assertRaisesRegex(ValueError, 'classification'):
            tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 0, 'bank': 0}})

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_raw_key_99_ties_and_occurrences_survive_all_formats(self):
        from vulturetracker import tgimport
        for version in (3, 4, 5):
            with self.subTest(version=version):
                data = write_repeat_gp(self.gp_song(version=version), version)
                parsed = gpimport._read_native_gp(data)
                song = gpimport._native_gp_song(parsed, 'Drums')
                self.assertEqual(song['score']['tracks']['t1']['midi']['bank'], 128)
                beats = song['score']['patterns']['m1']['beats']
                self.assertEqual([b['notes'][0]['pitch'] for b in beats if b['voice'] == 0], [99, 99])
                self.assertEqual(len(song['score']['ties']), 1)
                self.assertEqual(song['score']['measures'][0]['repeat_close'], 1)
                if version != 3:
                    self.assertEqual(song['score']['tracks']['t1']['lyrics']['text'], 'drum  words')
                exported, _ = tgimport.native_to_tg(song, tgimport._raw(song),
                                                    channels={'t1': {'program': 0, 'bank': 128}})
                restored, _ = tgimport.read_tg(exported)
                self.assertEqual(self.written_notes(restored), self.written_notes(song))

    def test_tg_invalid_percussion_refuses_before_any_output(self):
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport
        for case in ('key0', 'key101', 'tuning', 'capo', 'bend', 'slide', 'routes'):
            root = ET.fromstring(self.xml())
            if case.startswith('key'):
                root.find('.//note').set('value', case[3:])
            elif case in ('tuning', 'capo'):
                root.find('.//TGString' if case == 'tuning' else './/TGTrack/offset').text = '1'
            elif case == 'routes':
                ET.SubElement(root.find('.//TGChannel'), 'TGChannelParameter', key='gm-channel-1', value='0')
            else:
                ET.SubElement(root.find('.//note'), case)
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                src = folder / 'invalid.tg'
                src.write_bytes(TestTgInterchange.archive(ET.tostring(root, encoding='unicode')))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(src, folder / 'song.yaml', folder / 'samples')
                self.assertEqual(list(folder.iterdir()), [src])

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_raw_route_contradictions_keys_and_effects_refuse_atomically(self):
        for version in (3, 4, 5):
            for case in ('flagfalse-route9', 'flagtrue-route0', 'secondary', 'key0', 'key100', 'key101',
                         'tuning', 'capo', 'bend'):
                song = self.gp_song(version=version)
                track = song.tracks[0]
                if case == 'flagfalse-route9':
                    track.isPercussionTrack = False
                elif case == 'flagtrue-route0':
                    track.channel.channel = 0
                elif case == 'secondary':
                    track.channel.effectChannel = 3
                elif case.startswith('key'):
                    track.measures[0].voices[0].beats[0].notes[0].value = int(case[3:])
                elif case == 'tuning':
                    track.strings[0].value = 1
                elif case == 'capo':
                    track.offset = 1
                else:
                    track.measures[0].voices[0].beats[0].notes[0].effect.bend = M.BendEffect(
                        type=M.BendType.bend, points=[M.BendPoint(0, 0), M.BendPoint(12, 2)])
                with self.subTest(version=version, case=case), tempfile.TemporaryDirectory() as tmp:
                    folder = Path(tmp)
                    src = folder / f'invalid.gp{version}'
                    data = write_repeat_gp(song, version)
                    src.write_bytes(data)
                    with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                        with self.assertRaises(ValueError):
                            gpimport.import_gp(src, folder / 'song.yaml', folder / 'samples', native=True)
                    self.assertEqual(list(folder.iterdir()), [src])
                    self.assertEqual(src.read_bytes(), data)

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_actual_saved_import_uses_drum_kit_and_retains_written_score(self):
        import yaml
        from vulturetracker import tgimport
        for kind in ('tg', 'gp3', 'gp4', 'gp5'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source, output, samples = folder / ('source.' + kind), folder / 'song.yaml', folder / 'samples'
                if kind == 'tg':
                    source.write_bytes(TestTgInterchange.archive(self.xml()))
                    song, _ = tgimport.import_tg(source, output, samples)
                else:
                    version = int(kind[-1])
                    source.write_bytes(write_repeat_gp(self.gp_song(version=version), version))
                    song, _ = gpimport.import_gp(source, output, samples, native=True)
                written = yaml.safe_load(output.read_text(encoding='utf-8'))
                self.assertEqual(written, song)
                self.assertEqual(written['instruments'][1]['name'], 'drums (placeholder)')
                self.assertEqual(len(list(samples.glob('*.wav'))), len(gpimport.KIT))
                self.assertTrue(all(Path(folder / sample['file']).is_file() for sample in written['samples'].values()))
                self.assertEqual(written['instruments'][1]['keymap'][0]['play_note'], 'C-5')
                data, _ = tgimport.native_to_tg(written, tgimport._raw(written),
                                                 channels={'t1': {'program': 0, 'bank': 128}})
                saved = folder / 'roundtrip.tg'
                saved.write_bytes(data)
                restored, _ = tgimport.read_tg(saved.read_bytes())
                self.assertEqual(self.written_notes(restored), self.written_notes(written))
                self.assertEqual(restored['score']['measures'], written['score']['measures'])

    def test_mixed_track_publication_keeps_distinct_guitar_and_kit_instruments(self):
        import copy
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport
        for drum_first in (True, False):
            root = ET.fromstring(self.xml())
            target = root.find('TGSong')
            channel = copy.deepcopy(target.find('TGChannel'))
            channel.find('id').text = '2'
            channel.find('bank').text = '0'
            target.append(channel)
            guitar = copy.deepcopy(target.find('TGTrack'))
            guitar.find('channelId').text = '2'
            for string in guitar.findall('TGString'):
                string.text = '64'
            for note in guitar.findall('.//note'):
                note.set('value', '0')
            target.insert(len(target) if drum_first else list(target).index(target.find('TGTrack')), guitar)
            with self.subTest(drum_first=drum_first), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source = folder / 'mixed.tg'
                source.write_bytes(TestTgInterchange.archive(ET.tostring(root, encoding='unicode')))
                song, _ = tgimport.import_tg(source, folder / 'song.yaml', folder / 'samples')
                for track in song['score']['tracks'].values():
                    expected = 'drums' if track['midi']['bank'] == 128 else 'guitar'
                    self.assertEqual(song['instruments'][track['instrument']]['name'], expected + ' (placeholder)')
                self.assertEqual(len(song['instruments']), 2)

    def test_percussion_clef_export_maps_only_neutral_bank128_and_reports_it(self):
        import copy
        from vulturetracker import tgimport
        song, _ = tgimport.read_tg(TestTgInterchange.archive(self.xml()))
        track = song['score']['tracks']['t1']
        track.update(clef='percussion', key=dict(fifths=0, mode='major'))
        original = copy.deepcopy(song)
        data, report = tgimport.native_to_tg(song, tgimport._raw(song),
                                             channels={'t1': {'program': 0, 'bank': 128}})
        self.assertEqual(song, original)
        self.assertTrue(any('native percussion clef serialized as TG treble' in w for w in report['warnings']))
        restored, _ = tgimport.read_tg(data)
        self.assertEqual(restored['score']['tracks']['t1']['clef'], 'treble')
        self.assertEqual(restored['score']['tracks']['t1']['midi']['bank'], 128)
        self.assertEqual(self.written_notes(restored), self.written_notes(song))
        for key in (dict(fifths=1, mode='major'), dict(fifths=0, mode='minor')):
            track['key'] = key
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'neutral 0/major'):
                tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 0, 'bank': 128}})
        pitched, _ = tgimport.read_tg(TestTgInterchange.archive(TestTgInterchange.xml()))
        pitched['score']['tracks']['t1']['clef'] = 'percussion'
        with self.assertRaisesRegex(ValueError, 'clef'):
            tgimport.native_to_tg(pitched, tgimport._raw(pitched), channels={'t1': {'program': 25, 'bank': 0}})

    def test_tg_percussion_dynamics_and_gates_preserve_authored_fields(self):
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport, tablature
        # Installed TG 2.1.0 vectors: 960 ticks/quarter, BPM137, half-note head.
        cases = [(tag, velocity, min(127, max(15, velocity + delta)), 1920)
                 for tag, delta in (('ghostNote', -16), ('accentuatedNote', 16), ('heavyAccentuatedNote', 32))
                 for velocity in (15, 95, 120)]
        cases += [('staccato', 95, 95, 960), ('deadNote', 95, 95, 68), ('palmMute', 95, 95, 137)]
        for tag, velocity, performed, ticks in cases:
            with self.subTest(tag=tag, velocity=velocity):
                root = ET.fromstring(self.xml())
                first = root.find('.//note')
                first.set('velocity', str(velocity))
                ET.SubElement(first, tag)
                song, _ = tgimport.read_tg(TestTgInterchange.archive(ET.tostring(root, encoding='unicode')))
                authored = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                self.assertEqual((authored['pitch'], authored['string'], authored['velocity']), (36, 1, velocity))
                self.assertTrue(authored[tgimport.FLAGS[tag]])
                plan = tablature.repeat_projection(song, tgimport._raw(song)).plan
                events = [e for e in plan['events'] if e['id'] == 'play_1/' + authored['id']]
                # Native note-off is identity/gate-only; its metadata keeps the
                # written velocity, while TG repeats performed velocity there.
                self.assertEqual([e['velocity'] for e in events], [performed, velocity])
                self.assertEqual([Fraction(*e['at']) * 960 for e in events], [0, ticks])
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song),
                                                 channels={'t1': {'program': 0, 'bank': 128}})
                restored, _ = tgimport.read_tg(data)
                self.assertEqual(restored['score'], song['score'])
                self.assertEqual(tablature.repeat_projection(restored, tgimport._raw(restored)).plan['events'],
                                 plan['events'])
        for index, release in ((2, 3360), (3, 4800)):
            root = ET.fromstring(self.xml())
            ET.SubElement(root.findall('.//note')[index], 'staccato')
            song, _ = tgimport.read_tg(TestTgInterchange.archive(ET.tostring(root, encoding='unicode')))
            plan = tablature.repeat_projection(song, tgimport._raw(song)).plan
            snare = [e for e in plan['events'] if e['pitch'] == 38 and e['type'] == 'note_off']
            self.assertEqual(Fraction(*snare[0]['at']) * 960, release)

    def test_tg_percussion_technique_conflicts_and_unsupported_flags_refuse_atomically(self):
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport
        for tags in (('ghostNote', 'accentuatedNote'), ('palmMute', 'staccato'),
                     ('hammer',), ('vibrato',), ('fadeIn',), ('harmonic',)):
            root = ET.fromstring(self.xml())
            for tag in tags:
                ET.SubElement(root.find('.//note'), tag)
            with self.subTest(tags=tags), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source = folder / 'invalid.tg'
                source.write_bytes(TestTgInterchange.archive(ET.tostring(root, encoding='unicode')))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected publication')):
                    with self.assertRaises(ValueError):
                        tgimport.import_tg(source, folder / 'song.yaml', folder / 'samples')
                self.assertEqual(list(folder.iterdir()), [source])

    def test_saved_percussion_techniques_and_clef_mapping_use_actual_output(self):
        import xml.etree.ElementTree as ET
        import yaml
        from vulturetracker import tgimport
        root = ET.fromstring(self.xml())
        for index, tag in ((0, 'ghostNote'), (1, 'palmMute'), (2, 'deadNote'), (3, 'staccato')):
            ET.SubElement(root.findall('.//note')[index], tag)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source, output = folder / 'source.tg', folder / 'song.yaml'
            source.write_bytes(TestTgInterchange.archive(ET.tostring(root, encoding='unicode')))
            song, _ = tgimport.import_tg(source, output, folder / 'samples')
            actual = yaml.safe_load(output.read_text(encoding='utf-8'))
            self.assertEqual(actual, song)
            actual['score']['tracks']['t1'].update(clef='percussion', key=dict(fifths=0, mode='major'))
            data, report = tgimport.native_to_tg(actual, tgimport._raw(actual),
                                                 channels={'t1': {'program': 0, 'bank': 128}})
            exported = folder / 'export.tg'
            exported.write_bytes(data)
            restored, _ = tgimport.read_tg(exported.read_bytes())
            actual['score']['tracks']['t1']['clef'] = 'treble'
            self.assertEqual(restored['score'], actual['score'])
            self.assertIn('stored treble field', report['warnings'][-1])

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_percussion_unqualified_techniques_remain_refused(self):
        for field in ('vibrato', 'hammer'):
            song = self.gp_song()
            note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
            setattr(note.effect, field, True)
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source = folder / 'source.gp5'
                source.write_bytes(write_repeat_gp(song, 5))
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected publication')):
                    with self.assertRaisesRegex(ValueError, 'percussion techniques'):
                        gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
                self.assertEqual(list(folder.iterdir()), [source])

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_percussion_versioned_flags_and_native_tg_roundtrip(self):
        from vulturetracker import tgimport, tablature
        fields = {'ghostNote': ('ghost', 79, 1920), 'accentuatedNote': ('accent', 111, 1920),
                  'heavyAccentuatedNote': ('heavy_accent', 127, 1920),
                  'staccato': ('staccato', 95, 960), 'dead': ('dead', 95, 68), 'palmMute': ('palm_mute', 95, 137)}
        for version in (3, 4, 5):
            allowed = ('ghostNote', 'dead') if version == 3 else tuple(
                field for field in fields if version == 5 or field != 'heavyAccentuatedNote')
            for field in allowed:
                with self.subTest(version=version, field=field):
                    source = self.gp_song(version=version)
                    note = source.tracks[0].measures[0].voices[0].beats[0].notes[0]
                    if field == 'dead':
                        note.type = M.NoteType.dead
                    else:
                        setattr(note.effect, field, True)
                    parsed = gpimport._read_native_gp(write_repeat_gp(source, version))
                    song = gpimport._native_gp_song(parsed, 'Drum techniques')
                    native_field, velocity, release = fields[field]
                    authored = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                    self.assertEqual(authored['velocity'], 95)
                    self.assertTrue(authored[native_field])
                    plan = tablature.repeat_projection(song, tgimport._raw(song)).plan
                    events = [e for e in plan['events'] if e['id'] == 'play_1/' + authored['id']]
                    self.assertEqual(events[0]['velocity'], velocity)
                    self.assertEqual([Fraction(*e['at']) * 960 for e in events], [0, release])
                    data, _ = tgimport.native_to_tg(song, tgimport._raw(song),
                                                     channels={'t1': {'program': 0, 'bank': 128}})
                    restored, _ = tgimport.read_tg(data)
                    self.assertEqual(self.written_notes(restored), self.written_notes(song))
                    self.assertTrue(restored['score']['patterns']['m1']['beats'][0]['notes'][0][native_field])
            unsupported = ('accentuatedNote', 'heavyAccentuatedNote', 'staccato', 'palmMute') if version == 3 else (
                ('heavyAccentuatedNote',) if version == 4 else ())
            for field in unsupported:
                # Test before a GP writer has irreversibly dropped/downgraded it.
                source = self.gp_song(version=version)
                source.versionTuple = (version, 0, 0)
                setattr(source.tracks[0].measures[0].voices[0].beats[0].notes[0].effect, field, True)
                with self.subTest(version=version, unsupported=field), self.assertRaisesRegex(ValueError, 'GP version'):
                    gpimport._native_gp_song(source, 'Unsupported')

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_percussion_raw_bits_conflicts_and_invalid_velocity_refuse_atomically(self):
        from guitarpro.gp3 import GP3File
        from guitarpro.gp4 import GP4File
        from guitarpro.gp5 import GP5File
        for version, reader in ((3, GP3File), (4, GP4File), (5, GP5File)):
            cases = [('velocity', 0), ('velocity', 143)]
            if version < 5:
                cases.append(('raw_bit', 0x02))
            if version == 3:
                cases.append(('raw_bit', 0x40))
            if version >= 4:
                cases += [('dynamics', 0), ('gates', 0)]
            for case, value in cases:
                source = self.gp_song(version=version)
                note = source.tracks[0].measures[0].voices[0].beats[0].notes[0]
                if case == 'velocity':
                    note.velocity = value
                elif case == 'dynamics':
                    note.effect.ghostNote = note.effect.accentuatedNote = True
                elif case == 'gates':
                    note.effect.palmMute = note.effect.staccato = True
                original_flags = reader.packNoteFlags
                def flags(writer, written):
                    return original_flags(writer, written) | (value if case == 'raw_bit' and written is note else 0)
                with patch.object(reader, 'packNoteFlags', flags):
                    data = write_repeat_gp(source, version)
                with self.subTest(version=version, case=case, value=value), tempfile.TemporaryDirectory() as tmp:
                    folder = Path(tmp)
                    path = folder / f'invalid.gp{version}'
                    path.write_bytes(data)
                    with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected output')):
                        with self.assertRaises(ValueError):
                            gpimport.import_gp(path, folder / 'song.yaml', folder / 'samples', native=True)
                    self.assertEqual(list(folder.iterdir()), [path])
                    self.assertEqual(path.read_bytes(), data)

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_saved_gp_percussion_flags_and_default_velocity(self):
        import yaml
        from guitarpro.gp3 import GP3File
        from guitarpro.gp4 import GP4File
        from guitarpro.gp5 import GP5File
        from vulturetracker import tgimport
        for version, writer in ((3, GP3File), (4, GP4File), (5, GP5File)):
            source = self.gp_song(version=version)
            note = source.tracks[0].measures[0].voices[0].beats[0].notes[0]
            note.type = M.NoteType.dead
            note.effect.ghostNote = True
            if version >= 4:
                note.effect.palmMute = True
            implicit = write_repeat_gp(source, version)
            original_flags = writer.packNoteFlags
            def flags(owner, written):
                return original_flags(owner, written) | 0x10
            with patch.object(writer, 'packNoteFlags', flags):
                explicit = write_repeat_gp(source, version)
            a = gpimport._native_gp_song(gpimport._read_native_gp(implicit), 'Same')
            b = gpimport._native_gp_song(gpimport._read_native_gp(explicit), 'Same')
            self.assertEqual(a, b)
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                path, output = folder / f'source.gp{version}', folder / 'song.yaml'
                path.write_bytes(implicit)
                song, _ = gpimport.import_gp(path, output, folder / 'samples', native=True)
                actual = yaml.safe_load(output.read_text(encoding='utf-8'))
                self.assertEqual(actual, song)
                authored = actual['score']['patterns']['m1']['beats'][0]['notes'][0]
                self.assertEqual(authored['velocity'], 95)
                self.assertTrue(authored['dead'] and authored['ghost'])
                self.assertEqual(authored.get('palm_mute', False), version >= 4)
                data, _ = tgimport.native_to_tg(actual, tgimport._raw(actual),
                                                 channels={'t1': {'program': 0, 'bank': 128}})
                saved = folder / 'roundtrip.tg'
                saved.write_bytes(data)
                restored, _ = tgimport.read_tg(saved.read_bytes())
                self.assertEqual(self.written_notes(actual), self.written_notes(restored))

    @staticmethod
    def gp_ring(kind='other', gates=()):
        song = let_ring_tab(kind, gates=gates)
        track = song.tracks[0]
        track.isPercussionTrack = True
        track.channel.channel = track.channel.effectChannel = 9
        track.channel.instrument = 0
        track.strings = [M.GuitarString(1, 0), M.GuitarString(2, 0)]
        for beat in track.measures[0].voices[0].beats:
            for note in beat.notes:
                note.value = {(1, 5): 36, (1, 7): 38, (2, 3): 42}[note.string, note.value]
        return song

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_percussion_let_ring_ties_gates_and_tg_roundtrip(self):
        from vulturetracker import tgimport, tablature
        for version in (3, 4, 5):
            for case, end, velocity in (('other', 1920, 95), ('overlap', 1920, 95),
                                        ('tie', 2880, 95), ('tie-clears', 1920, 95),
                                        ('tie-enables', 2880, 95), ('dead', 60, 95),
                                        ('ghost', 1920, 79)):
                with self.subTest(version=version, case=case):
                    source = self.gp_ring('tie' if case.startswith('tie') or case == 'dead' else
                                          'overlap' if case == 'overlap' else 'other')
                    beats = source.tracks[0].measures[0].voices[0].beats
                    if case == 'tie-clears':
                        beats[1].notes[0].effect.letRing = False
                    elif case == 'tie-enables':
                        beats[0].notes[0].effect.letRing = False
                    elif case == 'dead':
                        beats[0].notes[0].type = M.NoteType.dead
                    elif case == 'ghost':
                        beats[0].notes[0].effect.ghostNote = True
                    warnings = []
                    song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(source, version)),
                                                    'ring', warnings=warnings)
                    self.assertFalse(warnings)
                    head = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                    self.assertEqual((head['pitch'], head['string'], head['velocity']), (36, 1, 95))
                    events = tablature.playback_plan(song, tgimport._raw(song))['events']
                    played = [e for e in events if e['note'] == head['id']]
                    self.assertEqual([(e['type'], Fraction(*e['at']) * 960) for e in played],
                                     [('note_on', 0), ('note_off', end)])
                    self.assertEqual(played[0]['velocity'], velocity)
                    data, _ = tgimport.native_to_tg(song, tgimport._raw(song),
                                                     channels={'t1': {'program': 0, 'bank': 128}})
                    restored, _ = tgimport.read_tg(data)
                    self.assertEqual(self.written_notes(restored), self.written_notes(song))
                    # GP and TG use different generated IDs; retain every
                    # authored note field, including ring/dead/ghost flags.
                    notes = lambda s: [[{k: v for k, v in n.items() if k != 'id'} for n in b['notes']]
                                       for b in s['score']['patterns']['m1']['beats']]
                    self.assertEqual(notes(restored), notes(song))
                    performed = lambda es: [{k: v for k, v in e.items() if k not in ('id', 'beat', 'note')}
                                             for e in es]
                    self.assertEqual(performed(tablature.playback_plan(restored, tgimport._raw(restored))['events']),
                                     performed(events))

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_percussion_let_ring_gate_priority_and_writer_loss(self):
        from vulturetracker import tgimport, tablature
        for version in (3, 4, 5):
            for gate, field, end in (('palmMute', 'palm_mute', 120), ('staccato', 'staccato', 480)):
                with self.subTest(version=version, gate=gate):
                    warnings = []
                    source = write_repeat_gp(self.gp_ring(gates=(gate,)), version)
                    song = gpimport._native_gp_song(gpimport._read_native_gp(source), 'ring', warnings=warnings)
                    head = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                    if version == 3:  # GP3 writer drops the unsupported gate before import.
                        self.assertTrue(head['let_ring'])
                        self.assertNotIn(field, head)
                        self.assertFalse(warnings)
                        end = 1920
                    else:
                        self.assertTrue(head[field])
                        self.assertNotIn('let_ring', head)
                        self.assertEqual(len(warnings), 1)
                        self.assertIn("'let_ring': True", warnings[0])
                        self.assertIn(warnings[0], song['module']['message'])
                    events = tablature.playback_plan(song, tgimport._raw(song))['events']
                    self.assertEqual(next(Fraction(*e['at']) * 960 for e in events
                                          if e['type'] == 'note_off' and e['note'] == head['id']), end)
        for gates in (('palmMute', 'staccato'), ('ghostNote', 'accentuatedNote')):
            source = write_repeat_gp(self.gp_ring(gates=gates), 5)
            with self.subTest(gates=gates), self.assertRaisesRegex(ValueError, 'percussion technique conflict'):
                gpimport._native_gp_song(gpimport._read_native_gp(source), 'conflict')

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_gp_percussion_gapped_let_ring_ties_refuse_before_publication(self):
        for version in (3, 4, 5):
            song = self.gp_ring('tie')
            voice = song.tracks[0].measures[0].voices[0]
            for beat in voice.beats[1:]:
                beat.start += 960
            voice.beats.insert(1, M.Beat(voice, start=1920, duration=M.Duration(value=4), status=M.BeatStatus.rest))
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source = folder / f'gap.gp{version}'
                data = write_repeat_gp(song, version)
                source.write_bytes(data)
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected publication')):
                    with self.assertRaisesRegex(ValueError, 'adjacent same-pitch predecessor'):
                        gpimport.import_gp(source, folder / 'song.yaml', folder / 'samples', native=True)
                self.assertEqual(list(folder.iterdir()), [source])
                self.assertEqual(source.read_bytes(), data)

    @unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
    def test_saved_gp_percussion_let_ring_retains_kit_and_written_flags(self):
        import yaml
        from vulturetracker import tgimport
        for version in (3, 4, 5):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source, output = folder / f'ring.gp{version}', folder / 'song.yaml'
                source.write_bytes(write_repeat_gp(self.gp_ring('tie'), version))
                song, _ = gpimport.import_gp(source, output, folder / 'samples', native=True)
                written = yaml.safe_load(output.read_text(encoding='utf-8'))
                self.assertEqual(written, song)
                self.assertEqual(written['instruments'][1]['name'], 'drums (placeholder)')
                self.assertTrue(written['score']['patterns']['m1']['beats'][0]['notes'][0]['let_ring'])
                data, _ = tgimport.native_to_tg(written, tgimport._raw(written),
                                                 channels={'t1': {'program': 0, 'bank': 128}})
                restored, _ = tgimport.read_tg(data)
                self.assertEqual(self.written_notes(restored), self.written_notes(written))
                self.assertTrue(restored['score']['patterns']['m1']['beats'][0]['notes'][0]['let_ring'])

    @staticmethod
    def ring_xml(kind='other', head_effects='', reverse=False):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(TestTgInterchange.ring_xml(kind, head_effects, reverse))
        root.find('.//TGChannel/bank').text = '128'
        root.find('.//TGChannel/program').text = '0'
        for string in root.findall('.//TGString'):
            string.text = '0'
        for note in root.findall('.//note'):
            key = {(1, 5): 36, (1, 7): 38, (2, 3): 42}[int(note.get('string')), int(note.get('value'))]
            note.set('value', str(key))
        return ET.tostring(root, encoding='unicode')

    def test_tg_percussion_let_ring_roundtrip_preserves_order_ties_and_gates(self):
        from vulturetracker import tgimport, tablature
        for kind, reverse, effects in (('other', False, ''), ('tie', False, ''),
                                        ('overlap', False, ''), ('chord', False, ''),
                                        ('chord', True, ''), ('tie', False, '<deadNote/>')):
            with self.subTest(kind=kind, reverse=reverse, effects=effects):
                song, _ = tgimport.read_tg(TestTgInterchange.archive(self.ring_xml(kind, effects, reverse)))
                original = song['score']
                events = tablature.playback_plan(song, tgimport._raw(song))['events']
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song),
                                                 channels={'t1': {'program': 0, 'bank': 128}})
                restored, _ = tgimport.read_tg(data)
                self.assertEqual(restored['score'], original)
                self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], events)
                self.assertTrue(restored['score']['patterns']['m1']['beats'][0]['notes'][0]['let_ring'])

    def test_tg_percussion_let_ring_conflicts_retain_existing_source_notice(self):
        from vulturetracker import tgimport
        for tags in ('<palmMute/>', '<staccato/>', '<palmMute/><staccato/>'):
            with self.subTest(tags=tags):
                song, warnings = tgimport.read_tg(TestTgInterchange.archive(self.ring_xml(head_effects=tags)))
                head = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                self.assertTrue(head['let_ring'])
                self.assertNotIn('palm_mute', head)
                self.assertNotIn('staccato', head)
                notice = next(w for w in warnings if 'normalized let-ring conflicts' in w)
                self.assertIn(notice, song['module']['message'])
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song),
                                                 channels={'t1': {'program': 0, 'bank': 128}})
                restored, _ = tgimport.read_tg(data)
                self.assertIn(notice, restored['module']['message'])
                # Existing source normalization does not permit contradictory
                # native authoring/export flags.
                head['palm_mute'] = True
                with self.assertRaisesRegex(ValueError, 'let_ring conflicts'):
                    tgimport.native_to_tg(song, tgimport._raw(song),
                                           channels={'t1': {'program': 0, 'bank': 128}})

    def test_tg_percussion_gapped_let_ring_ties_refuse_before_publication(self):
        import xml.etree.ElementTree as ET
        from vulturetracker import tgimport
        for marked in (False, True):
            root = ET.fromstring(self.ring_xml('tie'))
            beats = root.findall('.//TGBeat')
            # A gap no longer breaks the tie: TuxGuitar closes it on opening (updatePreciseStart). A predecessor on
            # another drum key leaves the tied note without an adjacent same-pitch predecessor instead.
            beats[0].find('voice/note').set('value', '38')
            if not marked:
                note = beats[1].find('voice/note')
                note.remove(note.find('letRing'))
            with self.subTest(marked=marked), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                source = folder / 'gap.tg'
                data = TestTgInterchange.archive(ET.tostring(root, encoding='unicode'))
                source.write_bytes(data)
                with patch.object(gpimport, 'Placeholders', side_effect=AssertionError('unexpected publication')):
                    with self.assertRaisesRegex(ValueError, 'adjacent same-pitch predecessor'):
                        tgimport.import_tg(source, folder / 'song.yaml', folder / 'samples')
                self.assertEqual(list(folder.iterdir()), [source])
                self.assertEqual(source.read_bytes(), data)

    def test_saved_tg_percussion_let_ring_retains_kit_and_written_flags(self):
        import yaml
        from vulturetracker import tgimport
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source, output = folder / 'ring.tg', folder / 'song.yaml'
            source.write_bytes(TestTgInterchange.archive(self.ring_xml('overlap')))
            song, _ = tgimport.import_tg(source, output, folder / 'samples')
            written = yaml.safe_load(output.read_text(encoding='utf-8'))
            self.assertEqual(written, song)
            self.assertEqual(written['instruments'][1]['name'], 'drums (placeholder)')
            data, _ = tgimport.native_to_tg(written, tgimport._raw(written),
                                             channels={'t1': {'program': 0, 'bank': 128}})
            path = folder / 'saved.tg'
            path.write_bytes(data)
            restored, _ = tgimport.read_tg(path.read_bytes())
            self.assertEqual(restored['score'], written['score'])


@unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
class TestGp5PitchedEffectExport(unittest.TestCase):
    @staticmethod
    def fixture():
        """The qualified chord/tie/voice case, built with existing GP fixtures."""
        gp = harmonic_tab([None, None], fret=5, tuning=64)
        gp.tempo = 120
        track = gp.tracks[0]
        track.channel.volume = 128
        track.strings = [M.GuitarString(i + 1, pitch) for i, pitch in enumerate((64, 59, 55, 50, 45))]
        first, second = track.measures[0].voices
        for bi, beat in enumerate(first.beats):
            beat.notes = []
            for lane in (1, 2, 3, 4):
                kind = M.NoteType.tie if bi == 1 and lane in (1, 2) else (
                    M.NoteType.dead if bi == 0 and lane == 3 else M.NoteType.normal)
                note = M.Note(beat, string=lane, value=5, velocity=95, type=kind)
                natural = (lane in (1, 3)) == (bi == 0)
                note.effect.harmonic = M.NaturalHarmonic() if natural else M.ArtificialHarmonic(
                    M.PitchClass(note.realValue % 12), M.Octave.ottava)
                if lane == 1:
                    note.effect.trill = M.TrillEffect(fret=7 if bi == 0 else 9,
                                                     duration=M.Duration(16 if bi == 0 else 32))
                if lane == 2:
                    note.effect.tremoloPicking = M.TremoloPickingEffect(duration=M.Duration(16 if bi == 0 else 32))
                beat.notes.append(note)
        second.beats = []
        for bi in (0, 1):
            beat = M.Beat(second, start=960 + bi * 960, duration=M.Duration(4), status=M.BeatStatus.normal)
            note = M.Note(beat, string=5, value=5, velocity=95, type=M.NoteType.normal)
            if bi:
                note.effect.harmonic = M.NaturalHarmonic()
            beat.notes = [note]
            second.beats.append(beat)
        song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), 'Pitched effects')
        # Imported source diagnostics are not part of this bounded metadata
        # fixture; the exporter retains its existing 255-byte message guard.
        song['module']['message'] = 'Pitched-effect export fixture'
        song['score']['metadata']['comments'] = song['module']['message']
        return song

    @staticmethod
    def convert(song):
        from vulturetracker import gpexport, tgimport
        return gpexport.native_to_gp5(song, tgimport._raw(song), channels={
            tid: dict(program=track['midi']['program'], bank=track['midi']['bank'])
            for tid, track in song['score']['tracks'].items()})

    def test_combined_written_effects_ties_voices_and_artificial_warning(self):
        import copy
        from vulturetracker import tablature, tgimport
        song = self.fixture()
        before = copy.deepcopy(song)
        data, report = self.convert(song)
        decoded = gpimport._read_native_gp(data)
        restored = gpimport._native_gp_song(decoded, decoded.title)
        self.assertEqual(restored['score'], song['score'])
        self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'],
                         tablature.playback_plan(song, tgimport._raw(song))['events'])
        for track in decoded.tracks:
            for measure in track.measures:
                for voice in measure.voices:
                    for beat in voice.beats:
                        for note in beat.notes:
                            if isinstance(note.effect.harmonic, M.ArtificialHarmonic):
                                self.assertEqual(note.effect.harmonic.pitch.value, note.realValue % 12)
                                self.assertEqual(note.effect.harmonic.octave, M.Octave.ottava)
        self.assertEqual(sum('Artificial harmonics use canonical GP5' in w for w in report['warnings']), 1)
        self.assertEqual(song, before)

    def test_qualified_rates_and_default_harmonic_data(self):
        for field, rates in (('trill', (16, 32, 64)), ('tremolo_picking', (8, 16, 32))):
            for rate in rates:
                song = self.fixture()
                note = song['score']['patterns']['m1']['beats'][0]['notes'][0]
                note.pop('trill')
                note['harmonic'] = dict(type='natural')  # absent data means0
                note[field] = dict(value=rate, **({'fret': 7} if field == 'trill' else {}))
                with self.subTest(field=field, rate=rate):
                    data, _ = self.convert(song)
                    restored = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Rates')
                    actual = restored['score']['patterns']['m1']['beats'][0]['notes'][0]
                    self.assertEqual(actual[field], note[field])
                    self.assertEqual(actual['harmonic'], dict(type='natural', data=0))

    def test_unrepresentable_fields_and_existing_guards_refuse_without_mutation(self):
        import copy
        from vulturetracker import gpexport, tgimport
        cases = [
            ('natural data', dict(harmonic=dict(type='natural', data=1)), 'harmonic data0'),
            ('artificial data', dict(harmonic=dict(type='artificial', data=5)), 'harmonic data0'),
            ('pinch data', dict(harmonic=dict(type='pinch', data=1)), 'harmonic data0'),
            ('semi data', dict(harmonic=dict(type='semi', data=1)), 'harmonic data0'),
            ('trill4', dict(trill=dict(value=4, fret=7)), 'trill rate'),
            ('trill8', dict(trill=dict(value=8, fret=7)), 'trill rate'),
            ('trill fret', dict(trill=dict(value=16, fret=37)), 'trill fret'),
            ('picking64', dict(tremolo_picking=dict(value=64)), 'repetition value'),
            ('two repetitions', dict(trill=dict(value=16, fret=7),
                                     tremolo_picking=dict(value=16)), 'repetition conflicts'),
            ('dead repetition', dict(dead=True, trill=dict(value=16, fret=7)), 'repetition conflicts'),
            ('multiple dynamics', dict(ghost=True, accent=True), 'multiple dynamics'),
            ('two gates', dict(palm_mute=True, staccato=True), 'normalized by GP'),
            ('ring gate', dict(let_ring=True, palm_mute=True), 'let_ring conflicts'),
            ('inexact grace velocity', dict(grace=dict(fret=3, value=16, velocity=48,
                                                 transition='none', on_beat=False, dead=False)), 'GP grace velocity'),
        ]
        for name, change, reason in cases:
            song = self.fixture()
            note = song['score']['patterns']['m1']['beats'][0]['notes'][3]
            note.update(change)
            before, raw = copy.deepcopy(song), tgimport._raw(song)
            raw_before = copy.deepcopy(raw)
            with self.subTest(case=name), self.assertRaisesRegex(ValueError, reason):
                gpexport.native_to_gp5(song, raw, channels={'t1': dict(program=25, bank=0)})
            self.assertEqual(song, before)
            self.assertEqual(raw, raw_before)
        song = self.fixture()
        # A silent tied continuation must still reject lost harmonic data.
        continuation = song['score']['patterns']['m1']['beats'][1]['notes'][0]
        continuation['harmonic']['data'] = 1
        with self.assertRaisesRegex(ValueError, 'harmonic data0'):
            self.convert(song)
        continuation['harmonic']['data'] = 0
        continuation.pop('trill')
        continuation['dead'] = True
        with self.assertRaisesRegex(ValueError, 'incoming tie and dead'):
            self.convert(song)

    def test_pitched_effects_remain_refused_on_percussion(self):
        from vulturetracker import gpexport, tgimport
        for effect in (dict(harmonic=dict(type='natural', data=0)),
                       dict(trill=dict(value=16, fret=7))):
            source = TestPercussionInterchange.gp_ring()
            song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(source, 5)), 'Drums')
            song['score']['patterns']['m1']['beats'][0]['notes'][0].update(effect)
            with self.subTest(effect=effect), self.assertRaisesRegex(ValueError, 'unsupported percussion technique'):
                gpexport.native_to_gp5(song, tgimport._raw(song), channels={'t1': dict(program=0, bank=128)})


@unittest.skipIf(guitarpro is None, "PyGuitarPro not installed (pip install pyguitarpro)")
class TestGp5BendSlideExport(unittest.TestCase):
    @staticmethod
    def fixture():
        """The installed-oracle fixture: bend/tie, up/down/no-target slides, two voices."""
        gp = harmonic_tab([None] * 4, fret=5, tuning=64)
        gp.title, gp.tempo = 'Bend slide qualification', 120
        track = gp.tracks[0]
        track.channel.volume = 128
        track.strings = [M.GuitarString(i + 1, p) for i, p in enumerate((64, 59, 55, 50))]
        first, second = track.measures[0].voices
        for i, beat in enumerate(first.beats):
            head = beat.notes[0]
            if i in (0, 1):
                points = [(0, 0), (3, 4), (6, 4), (6, 8), (9, 4), (12, 0)] if i == 0 else [(0, 12), (12, 0)]
                head.effect.bend = M.BendEffect(type=M.BendType.bend, value=0,
                    points=[M.BendPoint(p, v, False) for p, v in points])
                if i == 1:
                    head.type = M.NoteType.tie
            if i != 3:
                slide = M.Note(beat, string=2, value=(5, 9, 3)[i], velocity=95, type=M.NoteType.normal)
                slide.effect.slides = [M.SlideType.shiftSlideTo]
                beat.notes.append(slide)
            else:
                head.effect.slides = [M.SlideType.shiftSlideTo]
            beat.notes.append(M.Note(beat, string=3, value=5, velocity=95, type=M.NoteType.normal))
            other = M.Beat(second, start=960 + i * 960, duration=M.Duration(4), status=M.BeatStatus.normal)
            other.notes = [M.Note(other, string=4, value=5, velocity=95, type=M.NoteType.normal)]
            second.beats.append(other)
        song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), gp.title)
        song['module']['message'] = 'Scratch bend slide qualification'
        song['score']['metadata']['comments'] = song['module']['message']
        return song

    def test_written_curves_slides_ties_voices_and_pitch_plan_roundtrip(self):
        import copy
        from vulturetracker import tablature, tgimport
        song = self.fixture()
        before = copy.deepcopy(song)
        data, report = TestGp5PitchedEffectExport.convert(song)
        decoded = gpimport._read_native_gp(data)
        restored = gpimport._native_gp_song(decoded, decoded.title)
        self.assertEqual(restored['score'], song['score'])
        plan = tablature.playback_plan(song, tgimport._raw(song))
        self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], plan['events'])
        self.assertEqual(sum(e['type'] == 'pitch' for e in plan['events']), 69)
        self.assertEqual(report['notes'], 15)
        for voice in decoded.tracks[0].measures[0].voices:
            for beat in voice.beats:
                for note in beat.notes:
                    if note.effect.bend is not None:
                        self.assertEqual((note.effect.bend.type, note.effect.bend.value), (M.BendType.bend, 0))
                        self.assertFalse(any(p.vibrato for p in note.effect.bend.points))
                    if note.effect.slides:
                        self.assertEqual(note.effect.slides, [M.SlideType.shiftSlideTo])
        self.assertEqual(song, before)

    def test_curve_limits_preserve_point_order(self):
        for points in (
            [(0, 0)], [(12, 12)], [(0, 12), (12, 0)],
            [(0, 0), (6, 4), (6, 8), (6, 8), (12, 0)],
            [(i * 12 // 128, i % 13) for i in range(129)],
        ):
            song = self.fixture()
            note = song['score']['patterns']['m1']['beats'][0]['notes'][0]
            note['bend'] = dict(points=[dict(position=p, value=v) for p, v in points])
            with self.subTest(points=len(points)):
                data, _ = TestGp5PitchedEffectExport.convert(song)
                restored = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Curve limits')
                self.assertEqual(restored['score'], song['score'])

    def test_lossy_or_invalid_effects_refuse_without_mutation(self):
        import copy
        from vulturetracker import gpexport, tgimport
        curve = lambda points: dict(bend=dict(points=[dict(position=p, value=v) for p, v in points]))
        cases = [
            (curve([]), 'at least one point'),
            (curve([(6, 0), (5, 4)]), 'nondecreasing'),
            (curve([(13, 0)]), 'position'),
            (curve([(0, -1)]), 'value'),
            (curve([(0, 13)]), 'value'),
            (curve([(0, 0)] * 130), '129'),
            (dict(dead=True), 'pitch/dead effect combination'),
            (dict(slide=True), 'pitch/dead effect combination'),
            (dict(bend=None, dead=True, slide=True), 'pitch/dead effect combination'),
            (dict(ghost=True, accent=True), 'multiple dynamics'),
            (dict(palm_mute=True, staccato=True), 'normalized by GP'),
            (dict(trill=dict(value=16, fret=7)), 'repetition conflicts'),
            (dict(hammer=True), 'pitch/dead effect combination'),
            (dict(tremolo_bar=dict(points=[dict(position=0, value=0)])), 'identical curves'),
        ]
        for change, reason in cases:
            song = self.fixture()
            song['score']['patterns']['m1']['beats'][0]['notes'][0].update(change)
            raw = tgimport._raw(song)
            channels = {'t1': dict(program=25, bank=0)}
            before = copy.deepcopy((song, raw, channels))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, reason):
                gpexport.native_to_gp5(song, raw, channels=channels)
            self.assertEqual((song, raw, channels), before)
        # Inaudible continuation metadata must still survive or explicitly refuse.
        song = self.fixture()
        continuation = song['score']['patterns']['m1']['beats'][1]['notes'][0]
        continuation['bend'] = dict(points=[])
        with self.assertRaisesRegex(ValueError, 'at least one point'):
            TestGp5PitchedEffectExport.convert(song)
        continuation.pop('bend')
        continuation['dead'] = True
        with self.assertRaisesRegex(ValueError, 'incoming tie and dead'):
            TestGp5PitchedEffectExport.convert(song)

    def test_bend_and_slide_remain_refused_on_percussion(self):
        from vulturetracker import gpexport, tgimport
        for effect in (dict(bend=dict(points=[dict(position=0, value=0)])), dict(slide=True)):
            source = TestPercussionInterchange.gp_ring()
            song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(source, 5)), 'Drums')
            song['score']['patterns']['m1']['beats'][0]['notes'][0].update(effect)
            with self.subTest(effect=effect), self.assertRaisesRegex(ValueError, 'unsupported percussion technique'):
                gpexport.native_to_gp5(song, tgimport._raw(song), channels={'t1': dict(program=0, bank=128)})


@unittest.skipIf(guitarpro is None, "PyGuitarPro not installed (pip install pyguitarpro)")
class TestGp5VibratoHammerExport(unittest.TestCase):
    @staticmethod
    def gp_fixture():
        gp = harmonic_tab([None] * 8, fret=5, tuning=64)
        gp.title, gp.tempo = 'Vibrato hammer qualification', 120
        track = gp.tracks[0]
        track.channel.volume = 128
        track.strings = [M.GuitarString(i + 1, p) for i, p in enumerate((64, 59, 55, 50))]
        for mi, measure in enumerate(track.measures):
            first, second = measure.voices
            for bi, beat in enumerate(first.beats):
                i = mi * 4 + bi
                head = beat.notes[0]
                head.value = (5, 5, 7, 2, 5, 7, 3, 5)[i]
                head.effect.vibrato = i in (0, 6)
                head.effect.hammer = i in (1, 2, 3, 6)
                if i == 1:
                    head.type = M.NoteType.tie
                if i == 3:
                    head.effect.accentuatedNote = True
                peer = M.Note(beat, string=2, value=5 + i % 3, velocity=95, type=M.NoteType.normal)
                peer.effect.vibrato = i in (0, 1)
                if i == 0:
                    peer.effect.bend = M.BendEffect(type=M.BendType.bend, value=0,
                        points=[M.BendPoint(0, 0), M.BendPoint(6, 4), M.BendPoint(12, 0)])
                if i == 1:
                    peer.effect.slides = [M.SlideType.shiftSlideTo]
                beat.notes.append(peer)
                plain = M.Note(beat, string=3, value=5, velocity=95,
                               type=M.NoteType.dead if i == 0 else M.NoteType.normal)
                plain.effect.vibrato = i == 0
                beat.notes.append(plain)
                if i == 4:
                    beat.notes = []
                    beat.status = M.BeatStatus.rest
                other = M.Beat(second, start=960 + i * 960, duration=M.Duration(4), status=M.BeatStatus.normal)
                other.notes = [M.Note(other, string=4, value=5, velocity=95, type=M.NoteType.normal)]
                second.beats.append(other)
        return gp

    @staticmethod
    def fixture():
        gp = TestGp5VibratoHammerExport.gp_fixture()
        song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), gp.title)
        song['module']['message'] = 'Vibrato hammer export fixture'
        song['score']['metadata']['comments'] = song['module']['message']
        return song

    def test_flags_and_performed_pitch_velocity_roundtrip(self):
        import copy
        from vulturetracker import tablature, tgimport
        song = self.fixture()
        before = copy.deepcopy(song)
        data, report = TestGp5PitchedEffectExport.convert(song)
        decoded = gpimport._read_native_gp(data)
        restored = gpimport._native_gp_song(decoded, decoded.title)
        self.assertEqual(restored['score'], song['score'])
        plan = tablature.playback_plan(song, tgimport._raw(song))
        self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], plan['events'])
        velocities = {tuple(e['at']): e['velocity'] for e in plan['events']
                      if e['type'] == 'note_on' and e['ch'] == 0}
        self.assertEqual(velocities, {(0, 1): 95, (2, 1): 70, (3, 1): 86,
                                      (5, 1): 70, (6, 1): 95, (7, 1): 70})
        self.assertEqual(report['notes'], 29)
        self.assertTrue(all(not beat.effect.vibrato for track in decoded.tracks
                            for measure in track.measures for voice in measure.voices for beat in voice.beats))
        self.assertEqual(song, before)

    def test_destructive_combinations_and_remaining_effects_refuse_atomically(self):
        import copy
        from vulturetracker import gpexport, tgimport
        for fields, reason in (
            (dict(hammer=True, dead=True), 'pitch/dead effect combination'),
            (dict(hammer=True, slide=True), 'pitch/dead effect combination'),
            (dict(hammer=True, bend=dict(points=[dict(position=0, value=0)])), 'pitch/dead effect combination'),
            (dict(hammer=True, trill=dict(value=16, fret=7)), 'repetition conflicts'),
            (dict(vibrato=True, tremolo_picking=dict(value=16)), 'repetition conflicts'),
            (dict(tremolo_bar=dict(points=[dict(position=0, value=0)])), 'identical curves'),
            (dict(fade_in=True), 'fade-in requires identical flags'),
            (dict(tapping=True), 'tap/slap/pop requires identical techniques'),
            (dict(hammer='yes'), 'boolean'),
            (dict(vibrato=1), 'boolean'),
        ):
            song = self.fixture()
            # Plain third-string note, away from the fixture's dead/vibrato head.
            song['score']['patterns']['m1']['beats'][2]['notes'][2].update(fields)
            raw, channels = tgimport._raw(song), {'t1': dict(program=25, bank=0)}
            before = copy.deepcopy((song, raw, channels))
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, reason):
                gpexport.native_to_gp5(song, raw, channels=channels)
            self.assertEqual((song, raw, channels), before)

    def test_percussion_stays_refused(self):
        from vulturetracker import gpexport, tgimport
        for flag in ('vibrato', 'hammer'):
            gp = TestPercussionInterchange.gp_ring()
            song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), 'Drums')
            song['score']['patterns']['m1']['beats'][0]['notes'][0][flag] = True
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'unsupported percussion technique'):
                gpexport.native_to_gp5(song, tgimport._raw(song), channels={'t1': dict(program=0, bank=128)})


@unittest.skipIf(guitarpro is None, "PyGuitarPro not installed (pip install pyguitarpro)")
class TestGp5TremoloBarExport(unittest.TestCase):
    @staticmethod
    def gp_fixture():
        gp = harmonic_tab([None] * 4, fret=5, tuning=64)
        gp.title, gp.tempo = 'Tremolo bar ownership', 120
        track = gp.tracks[0]
        track.channel.volume = 128
        track.strings = [M.GuitarString(i + 1, p) for i, p in enumerate((64, 59, 55))]
        first, second = track.measures[0].voices
        curves = {0: [(0, 0), (3, -12), (6, -12), (6, 12), (12, 0)],
                  1: [(0, 0), (12, -2)], 3: [(0, 12), (12, -12)]}
        def curve(points):
            return M.BendEffect(type=M.BendType.bend, value=0,
                points=[M.BendPoint(p, v * 2, False) for p, v in points])
        for i, beat in enumerate(first.beats):
            beat.notes.append(M.Note(beat, string=2, value=5, velocity=95, type=M.NoteType.normal))
            if i in curves:
                beat.effect.tremoloBar = curve(curves[i])
            if i == 1:
                for n in beat.notes:
                    n.type = M.NoteType.tie
            beat.notes[0].effect.vibrato = i == 0
            beat.notes[0].effect.staccato = i == 3
            other = M.Beat(second, start=960 + i * 960, duration=M.Duration(4), status=M.BeatStatus.normal)
            other.notes = [M.Note(other, string=3, value=5, velocity=95, type=M.NoteType.normal)]
            if i in (1, 2):
                other.effect.tremoloBar = curve([(0, 0), (6, -4 if i == 1 else 4), (12, 0)])
                other.notes[0].effect.vibrato = True
            second.beats.append(other)
        return gp

    @staticmethod
    def fixture():
        gp = TestGp5TremoloBarExport.gp_fixture()
        song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), gp.title)
        song['module']['message'] = 'Scratch bar ownership qualification'
        song['score']['metadata']['comments'] = song['module']['message']
        return song

    def test_signed_curves_ties_and_independent_voice_ownership_roundtrip(self):
        import copy
        from vulturetracker import tablature, tgimport
        song = self.fixture()
        before = copy.deepcopy(song)
        data, report = TestGp5PitchedEffectExport.convert(song)
        decoded = gpimport._read_native_gp(data)
        restored = gpimport._native_gp_song(decoded, decoded.title)
        self.assertEqual(restored['score'], song['score'])
        events = tablature.playback_plan(song, tgimport._raw(song))['events']
        self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'], events)
        self.assertEqual(sum(e['type'] == 'pitch' for e in events), 894)
        self.assertEqual(report['notes'], 12)
        voices = decoded.tracks[0].measures[0].voices
        self.assertIsNone(voices[1].beats[0].effect.tremoloBar)
        curve = voices[0].beats[0].effect.tremoloBar
        self.assertEqual((curve.type, curve.value), (M.BendType.bend, 0))
        self.assertEqual([(p.position, p.value, p.vibrato) for p in curve.points],
                         [(0, 0, False), (3, -24, False), (6, -24, False),
                          (6, 24, False), (12, 0, False)])
        self.assertEqual(song, before)

    def test_one_and_129_points_and_equal_distinct_curves(self):
        import copy
        for points in ([(0, -12)], [(12, 12)],
                       [(i * 12 // 128, i % 25 - 12) for i in range(129)]):
            song = self.fixture()
            curve = dict(points=[dict(position=p, value=v) for p, v in points])
            for note in song['score']['patterns']['m1']['beats'][0]['notes']:
                note['tremolo_bar'] = copy.deepcopy(curve)  # equality is by value, not object identity
            with self.subTest(count=len(points)):
                data, _ = TestGp5PitchedEffectExport.convert(song)
                restored = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Curve limits')
                self.assertEqual(restored['score'], song['score'])

    def test_partial_empty_invalid_and_conflicting_curves_refuse_atomically(self):
        import copy
        from vulturetracker import gpexport, tgimport
        for case, reason in (
            ('missing', 'identical curves'), ('null', 'identical curves'),
            ('different', 'identical curves'), ('extra-point', 'identical curves'),
            ('empty', 'at least one point'), ('descending', 'nondecreasing'),
            ('range', 'value'), ('too-many', '129'),
            ('dead', 'pitch/dead effect combination'), ('bend', 'pitch/dead effect combination'),
            ('slide', 'pitch/dead effect combination'), ('hammer', 'pitch/dead effect combination'),
            ('trill', 'repetition conflicts'), ('tremolo_picking', 'repetition conflicts'),
        ):
            song = self.fixture()
            notes = song['score']['patterns']['m1']['beats'][0]['notes']
            notes[1]['tremolo_bar'] = copy.deepcopy(notes[1]['tremolo_bar'])
            if case == 'missing':
                notes[1].pop('tremolo_bar')
            elif case == 'null':
                notes[1]['tremolo_bar'] = None
            elif case == 'different':
                notes[1]['tremolo_bar']['points'][1]['value'] = -11
            elif case == 'extra-point':
                notes[1]['tremolo_bar']['points'].insert(0, dict(position=0, value=0))
            elif case in ('empty', 'descending', 'range', 'too-many'):
                points = {'empty': [], 'descending': [(6, 0), (5, 0)],
                          'range': [(0, -13)], 'too-many': [(0, 0)] * 130}[case]
                for n in notes:
                    n['tremolo_bar'] = dict(points=[dict(position=p, value=v) for p, v in points])
            else:
                notes[0][case] = (dict(points=[dict(position=0, value=0)]) if case == 'bend' else
                                 dict(value=16, **({'fret': 7} if case == 'trill' else {}))
                                 if case in ('trill', 'tremolo_picking') else True)
            raw, channels = tgimport._raw(song), {'t1': dict(program=25, bank=0)}
            before = copy.deepcopy((song, raw, channels))
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, reason):
                gpexport.native_to_gp5(song, raw, channels=channels)
            self.assertEqual((song, raw, channels), before)

    def test_tied_metadata_and_percussion_do_not_bypass_refusal(self):
        from vulturetracker import gpexport, tgimport
        song = self.fixture()
        song['score']['patterns']['m1']['beats'][1]['notes'][1].pop('tremolo_bar')
        with self.assertRaisesRegex(ValueError, 'identical curves'):
            TestGp5PitchedEffectExport.convert(song)
        gp = TestPercussionInterchange.gp_ring()
        song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), 'Drums')
        song['score']['patterns']['m1']['beats'][0]['notes'][0]['tremolo_bar'] = dict(
            points=[dict(position=0, value=0)])
        with self.assertRaisesRegex(ValueError, 'unsupported percussion technique'):
            gpexport.native_to_gp5(song, tgimport._raw(song), channels={'t1': dict(program=0, bank=128)})


@unittest.skipIf(guitarpro is None, "PyGuitarPro not installed (pip install pyguitarpro)")
class TestGp5BeatFlagsExport(unittest.TestCase):
    @staticmethod
    def gp_fixture():
        gp = harmonic_tab([None] * 4, fret=5, tuning=64)
        gp.title, gp.tempo = 'Beat flags ownership', 120
        track = gp.tracks[0]
        track.channel.volume = 128
        track.strings = [M.GuitarString(i + 1, p) for i, p in enumerate((64, 59, 55))]
        first, second = track.measures[0].voices
        for i, beat in enumerate(first.beats):
            beat.notes.append(M.Note(beat, string=2, value=5, velocity=95, type=M.NoteType.normal))
            beat.effect.slapEffect = M.SlapEffect((1, 2, 3, 0)[i])
            beat.effect.fadeIn = i != 2
            if i == 1:
                for n in beat.notes:
                    n.type = M.NoteType.tie
            beat.notes[0].effect.staccato = i == 3
            if i == 3:
                beat.notes[1].type = M.NoteType.dead
            other = M.Beat(second, start=960 + i * 960, duration=M.Duration(4), status=M.BeatStatus.normal)
            other.notes = [M.Note(other, string=3, value=5, velocity=95, type=M.NoteType.normal)]
            other.effect.slapEffect = M.SlapEffect((3, 1, 0, 2)[i])
            other.effect.fadeIn = i in (1, 2)
            second.beats.append(other)
        return gp

    @staticmethod
    def fixture():
        gp = TestGp5BeatFlagsExport.gp_fixture()
        song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), gp.title)
        song['module']['message'] = 'Scratch beat flag ownership qualification'
        song['score']['metadata']['comments'] = song['module']['message']
        return song

    def test_independent_voice_flags_ties_and_fades_roundtrip(self):
        import copy
        from vulturetracker import tablature, tgimport
        song = self.fixture()
        before = copy.deepcopy(song)
        data, report = TestGp5PitchedEffectExport.convert(song)
        decoded = gpimport._read_native_gp(data)
        restored = gpimport._native_gp_song(decoded, decoded.title)
        self.assertEqual(restored['score'], song['score'])
        plan = tablature.playback_plan(song, tgimport._raw(song))
        after = tablature.playback_plan(restored, tgimport._raw(restored))
        self.assertEqual(after['events'], plan['events'])
        self.assertEqual(after['midi_fades'], plan['midi_fades'])
        self.assertEqual([f['ticks'] for f in plan['midi_fades']], [1920, 1920, 960, 960, 480, 60])
        voices = decoded.tracks[0].measures[0].voices
        self.assertEqual([[b.effect.slapEffect.value for b in v.beats] for v in voices],
                         [[1, 2, 3, 0], [3, 1, 0, 2]])
        self.assertEqual([[b.effect.fadeIn for b in v.beats] for v in voices],
                         [[True, True, False, True], [False, True, True, False]])
        self.assertEqual(sum('track-wide MIDI expression' in w for w in report['warnings']), 1)
        self.assertEqual(song, before)

    def test_absent_false_and_rest_do_not_acquire_flags(self):
        song = self.fixture()
        song['score']['ties'] = []
        for p in song['score']['patterns'].values():
            for beat in p['beats']:
                for n in beat['notes']:
                    for key in ('fade_in', 'tapping', 'slapping', 'popping'):
                        n[key] = False
        song['score']['patterns']['m1']['beats'][0]['notes'] = []
        data, report = TestGp5PitchedEffectExport.convert(song)
        decoded = gpimport._read_native_gp(data)
        first = decoded.tracks[0].measures[0].voices[0].beats[0]
        self.assertEqual(first.status, M.BeatStatus.rest)
        self.assertFalse(first.notes)
        for t in decoded.tracks:
            for m in t.measures:
                for v in m.voices:
                    for b in v.beats:
                        self.assertFalse(b.effect.fadeIn)
                        self.assertEqual(b.effect.slapEffect, M.SlapEffect.none)
        self.assertFalse(any('native live/audio playback' in w for w in report['warnings']))

    def test_mixed_ownership_invalid_flags_and_tied_metadata_refuse_atomically(self):
        import copy
        from vulturetracker import gpexport, tgimport
        for case, reason in (
            ('fade-false', 'fade-in requires identical flags'),
            ('fade-missing', 'fade-in requires identical flags'),
            ('tech-none', 'tap/slap/pop requires identical techniques'),
            ('tech-other', 'tap/slap/pop requires identical techniques'),
            ('tied-fade', 'fade-in requires identical flags'),
            ('tied-tech', 'tap/slap/pop requires identical techniques'),
            ('multiple', 'mutually exclusive'),
            ('bad-fade', 'boolean'), ('bad-tech', 'boolean'),
            ('inexact-grace-velocity', 'GP grace velocity'),
        ):
            song = self.fixture()
            notes = song['score']['patterns']['m1']['beats'][1 if case.startswith('tied') else 0]['notes']
            n = notes[1]
            if case in ('fade-missing', 'tied-fade'):
                n.pop('fade_in')
            elif case == 'fade-false':
                n['fade_in'] = False
            elif case in ('tech-none', 'tied-tech'):
                n.pop('slapping' if case == 'tied-tech' else 'tapping')
            elif case == 'tech-other':
                n.pop('tapping')
                n['popping'] = True
            elif case == 'multiple':
                n['popping'] = True
            elif case == 'bad-fade':
                n['fade_in'] = 1
            elif case == 'bad-tech':
                n['tapping'] = 'yes'
            else:
                n['grace'] = dict(fret=3, value=16, velocity=48, transition='none', on_beat=False, dead=False)
            raw, channels = tgimport._raw(song), {'t1': dict(program=25, bank=0)}
            before = copy.deepcopy((song, raw, channels))
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, reason):
                gpexport.native_to_gp5(song, raw, channels=channels)
            self.assertEqual((song, raw, channels), before)

    def test_percussion_flags_remain_refused(self):
        from vulturetracker import gpexport, tgimport
        for flag in ('fade_in', 'tapping', 'slapping', 'popping'):
            gp = TestPercussionInterchange.gp_ring()
            song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), 'Drums')
            song['score']['patterns']['m1']['beats'][0]['notes'][0][flag] = True
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'unsupported percussion technique'):
                gpexport.native_to_gp5(song, tgimport._raw(song), channels={'t1': dict(program=0, bank=128)})


@unittest.skipIf(guitarpro is None, 'PyGuitarPro not installed')
class TestGpInferredClef(unittest.TestCase):
    @staticmethod
    def fixture(tuning=(43, 38, 33, 28), program=33, version=5):
        gp = harmonic_tab([None], fret=5, tuning=tuning[0])
        gp.tracks[0].strings = [M.GuitarString(i + 1, pitch) for i, pitch in enumerate(tuning)]
        gp.tracks[0].channel.instrument = program
        gp.tracks[0].channel.volume = 128
        song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, version)), 'Bass clef')
        song['module']['message'] = 'Clef roundtrip'
        return song

    def test_inferred_bass_and_treble_roundtrip_actual_gp_formats_and_events(self):
        from vulturetracker import gpexport, tgimport, tablature
        for version in (3, 4, 5):
            for tuning, program, clef in (((43, 38, 33, 28), 33, 'bass'), ((64, 59), 33, 'treble'), ((43, 34), 25, 'bass')):
                with self.subTest(version=version, tuning=tuning, program=program):
                    song = self.fixture(tuning, program, version)
                    self.assertEqual(song['score']['tracks']['t1'].get('clef', 'treble'), clef)
                    data, _ = gpexport.native_to_gp(song, tgimport._raw(song),
                        channels={'t1': dict(program=program, bank=0)}, version=version)
                    restored = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Restored')
                    expected = dict(song['score'], metadata=dict(song['score']['metadata'], comments='Clef roundtrip'))
                    self.assertEqual(restored['score'], expected)
                    self.assertEqual(restored['module']['title'], 'Restored')
                    self.assertEqual(tablature.playback_plan(restored, tgimport._raw(restored))['events'],
                                     tablature.playback_plan(song, tgimport._raw(song))['events'])

    def test_mismatched_and_unsupported_clefs_still_refuse_without_mutation(self):
        import copy
        from vulturetracker import gpexport, tgimport
        for tuning, clef in (((43, 28), 'treble'), ((64, 59), 'bass'), ((43, 28), 'alto'), ((64,), 'tenor')):
            with self.subTest(tuning=tuning, clef=clef):
                song = self.fixture(tuning)
                song['score']['tracks']['t1']['clef'] = clef
                original = copy.deepcopy(song)
                with self.assertRaisesRegex(ValueError, 'infers .* clef'):
                    gpexport.native_to_gp5(song, tgimport._raw(song), channels={'t1': dict(program=33, bank=0)})
                self.assertEqual(song, original)

    def test_percussion_zero_tuning_keeps_implicit_treble(self):
        from vulturetracker import gpexport, tgimport
        gp = TestPercussionInterchange.gp_ring()
        song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), 'Drums')
        song['module']['message'] = 'Percussion clef'
        self.assertNotIn('clef', song['score']['tracks']['t1'])
        data, _ = gpexport.native_to_gp5(song, tgimport._raw(song), channels={'t1': dict(program=0, bank=128)})
        restored = gpimport._native_gp_song(gpimport._read_native_gp(data), 'Restored')
        self.assertNotIn('clef', restored['score']['tracks']['t1'])


@unittest.skipIf(guitarpro is None,'PyGuitarPro is optional')
class TestGp5ExtendedHarmonicExport(unittest.TestCase):
    @staticmethod
    def fixture(kind='tapped',data=0,fret=5):
        gp=harmonic_tab([None]*4,fret=fret,tuning=40)
        gp.title='GP5 harmonic export';gp.tempo=120
        gp.tracks[0].channel.volume=128
        gp.measureHeaders[0].isRepeatOpen=True;gp.measureHeaders[0].repeatClose=1
        gp.tracks[0].measures[0].voices[0].beats[1].notes[0].type=M.NoteType.tie
        song=gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp,5)),gp.title)
        song['module']['message']='Harmonic export fixture'
        song['score']['metadata']['comments']=song['module']['message']
        for b in song['score']['patterns']['m1']['beats']:
            for n in b['notes']:n['harmonic']=dict(type=kind,data=data)
        return song

    def test_tapped_intervals_pinch_semi_ties_repeats_and_fret_bounds(self):
        import copy
        from tests.test_gpexport_legacy import export,plan
        for kind,data in [('tapped',i) for i in range(6)]+[('pinch',0),('semi',0)]:
            for fret in (0,36):
                with self.subTest(kind=kind,data=data,fret=fret):
                    song=self.fixture(kind,data,fret);before=copy.deepcopy(song)
                    raw,_=export(song,5)
                    parsed=gpimport._read_native_gp(raw)
                    restored=gpimport._native_gp_song(parsed,song['module']['title'])
                    self.assertEqual(restored['score'],song['score'])
                    self.assertEqual(plan(restored),plan(song))
                    self.assertEqual(song,before)
                    if kind=='tapped':
                        self.assertEqual(parsed.tracks[0].measures[0].voices[0].beats[0].notes[0].effect.harmonic.fret,
                                         fret+(12,9,5,7,4,3)[data])

    def test_older_formats_and_nonrepresentable_data_still_refuse(self):
        import copy
        from tests.test_gpexport_legacy import export
        for version in (3,):
            for kind in ('tapped','pinch','semi'):
                song=self.fixture(kind);before=copy.deepcopy(song)
                with self.subTest(version=version,kind=kind),self.assertRaisesRegex(ValueError,'harmonic data0'):
                    export(song,version)
                self.assertEqual(song,before)
        for kind,data in [('tapped',1),('artificial',1),('artificial',4),('artificial',5)]:
            song=self.fixture(kind,data);before=copy.deepcopy(song)
            with self.subTest(version=4,kind=kind,data=data),self.assertRaisesRegex(ValueError,'harmonic data'):
                export(song,4)
            self.assertEqual(song,before)
        for kind in ('pinch','semi'):
            song=self.fixture(kind,1);before=copy.deepcopy(song)
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'harmonic data0'):
                export(song,5)
            self.assertEqual(song,before)

    def test_gp4_extended_harmonics_preserve_source_reader_data(self):
        from tests.test_gpexport_legacy import export,plan
        for kind,data in [('tapped',0),('pinch',0),('semi',0),('artificial',0),('artificial',2),('artificial',3)]:
            for fret in (0,36):
                with self.subTest(kind=kind,data=data,fret=fret):
                    song=self.fixture(kind,data,fret)
                    restored=gpimport._native_gp_song(gpimport._read_native_gp(export(song,4)[0]),song['module']['title'])
                    self.assertEqual(restored['score'],song['score'])
                    self.assertEqual(plan(restored),plan(song))


@unittest.skipIf(guitarpro is None, 'PyGuitarPro is optional')
class TestPercussionOrnamentInterchange(unittest.TestCase):
    @staticmethod
    def fixture(**settings):
        from tests.test_tablature import percussion_ornaments_song
        song=percussion_ornaments_song(**settings)
        track=song['score']['tracks']['drums']
        # GP infers implicit treble; percussion engraving follows bank128.
        # Keep the explicit-clef refusal for scores that actually author one.
        track.pop('clef')
        track['midi']['source_pan']=dict(value=63,mixer_pan=32)
        return song

    @staticmethod
    def performance(song):
        from vulturetracker import tgimport,tablature
        raw=tgimport._raw(song);repeated=tablature.repeat_projection(song,raw)
        plan=repeated.plan if repeated else tablature.playback_plan(song,raw)
        return [(e['type'],e['at'],e.get('pitch'),e.get('velocity'),e.get('role')) for e in plan['events'] if e['type'] in ('note_on','note_off')]

    def test_tg_gp_rolls_flams_repeats_and_format_guards(self):
        import copy
        from vulturetracker import tgimport,gpexport
        for roll,grace,on,dead in ((8,None,False,False),(16,16,True,False),(32,32,False,False),
                                    (None,64,False,False),(None,16,True,True)):
            song=self.fixture(roll=roll,grace=grace,on_beat=on,dead=dead,repeat=True)
            before=copy.deepcopy(song);channels={'drums':dict(program=0,bank=128)}
            raw=tgimport._raw(song)
            for version in ('2.0','1.5'):
                with self.subTest(tg=version,roll=roll,grace=grace,on=on,dead=dead):
                    data,_=tgimport.native_to_tg(song,raw,channels=channels,version=version)
                    restored,_=tgimport.read_tg(data)
                    self.assertEqual(self.performance(restored),self.performance(song))
            for version in (3,4,5):
                with self.subTest(gp=version,roll=roll,grace=grace,on=on,dead=dead):
                    if version<5 and grace and (on or dead) or version==3 and roll:
                        with self.assertRaises(ValueError):gpexport.native_to_gp(song,raw,channels=channels,version=version)
                    else:
                        data,_=gpexport.native_to_gp(song,raw,channels=channels,version=version)
                        restored=gpimport._native_gp_song(gpimport._read_native_gp(data),song['module']['title'])
                        self.assertEqual(self.performance(restored),self.performance(song))
            self.assertEqual(song,before)

    def test_midi_keeps_drum_grace_key_with_transposed_roll_and_stripped_lead_in(self):
        import io,mido
        from tests.test_gui import RATE,sine
        from vulturetracker import export
        from vulturetracker.wavload import write_wav
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            for name in ('a','b'):write_wav(folder/(name+'.wav'),RATE,[sine(440)])
            snap=export.snapshot(self.fixture(),folder,tail=0)
            data,_=export.native_to_midi(snap,dict(transpose=12,strip=True))
            mid=mido.MidiFile(file=io.BytesIO(data));attacks=[];controls=[]
            for track in mid.tracks:
                at=0
                for msg in track:
                    at+=msg.time
                    if msg.type=='note_on':attacks.append((Fraction(at,mid.ticks_per_beat),msg.note,msg.velocity))
                    if msg.type in ('control_change','program_change'):controls.append(msg)
            self.assertEqual(attacks,[(Fraction(1)+Fraction(i,4),50,95) for i in range(4)]+
                [(Fraction(3),42,47),(Fraction(13,4),50,95)])
            self.assertEqual(controls,[])


class TestGuitarProEncoding(unittest.TestCase):
    @staticmethod
    def fixture(text, version=5):
        gp = harmonic_tab([None] * 4, fret=5, tuning=64)
        gp.tempo = 120
        gp.tracks[0].channel.volume = 128
        song = gpimport._native_gp_song(gpimport._read_native_gp(write_repeat_gp(gp, 5)), 'Encoding')
        score = song['score']
        score['metadata'] = {key: text for key in ('title', 'artist', 'album', 'author', 'copyright', 'transcriber', 'comments')}
        # GP3/4 share one author/writer field; equal credits round-trip there.
        score['metadata']['writer'] = text
        song['module']['title'], song['module']['message'] = text, text
        track = score['tracks']['t1']
        track['name'] = text
        if version != 3:
            track['lyrics'] = dict(from_measure=1, text=text)
        score['measures'][0]['marker'] = dict(title=text, color='#000000')
        beat = score['patterns']['m1']['beats'][0]
        beat['text'] = text
        beat['chord'] = dict(name=text, first_fret=1, frets=[0])
        return song

    @staticmethod
    def convert(song, encoding, version=5):
        from vulturetracker import gpexport, tgimport
        return gpexport.native_to_gp(song, tgimport._raw(song), version=version, encoding=encoding,
                                    channels={'t1': dict(program=25, bank=0)})

    def test_canonical_names_and_unsafe_codecs(self):
        for value, expected in ((None, 'cp1252'), ('Windows-1251', 'cp1251'), (' UTF8 ', 'utf-8'),
                                ('Shift-JIS', 'shift_jis'), ('ascii', 'ascii'), ('iso2022_jp', 'iso2022_jp')):
            self.assertEqual(gpimport.guitar_pro_encoding(value), expected)
        for value in ('', 1252, {}, 'unknown-charset', 'utf-16', 'utf-16-le', 'utf-32', 'utf-8-sig',
                      'utf-7', 'base64_codec', 'hex_codec', 'rot_13', 'unicode_escape', 'raw_unicode_escape'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'ASCII-compatible text codec'):
                gpimport.guitar_pro_encoding(value)

    def test_utf8_cyrillic_japanese_all_authored_text_and_versions(self):
        import copy
        for encoding, text in (('cp1252', 'café'), ('utf-8', '音楽'), ('cp1251', 'Песня'), ('shift_jis', '音楽')):
            for version in (3, 4, 5):
                with self.subTest(encoding=encoding, version=version):
                    song = self.fixture(text, version)
                    before = copy.deepcopy(song)
                    data, report = self.convert(song, encoding, version)
                    self.assertEqual(data[1:25], f'FICHIER GUITAR PRO v{version}.00'.encode('ascii'))
                    self.assertEqual(report['encoding'], gpimport.guitar_pro_encoding(encoding))
                    parsed = gpimport._read_native_gp(data, encoding)
                    restored = gpimport._native_gp_song(parsed, text)
                    self.assertEqual(restored['score'], song['score'])
                    self.assertEqual(song, before)
                    with tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        src = root / f'source.gp{version}'
                        src.write_bytes(data)
                        imported, warnings = gpimport.import_gp(src, root / 'song.yaml', root / 'samples',
                                                               native=True, encoding=encoding)
                        self.assertEqual(imported['score'], song['score'])
                        self.assertIn(f'Guitar Pro text decoded with {report["encoding"]}.', warnings)
                        self.assertEqual(src.read_bytes(), data)

    def test_unrepresentable_ambiguous_and_byte_limit_failures_preserve_input(self):
        import copy
        for encoding, text, expected in (('cp1252', 'Песня', 'not representable'),
                                         ('shift_jis', '\u00a5', 'does not round-trip'),
                                         ('utf-8', '音' * 8, 'chord name: text exceeds 21 encoded bytes')):
            song = self.fixture(text)
            before = copy.deepcopy(song)
            with self.subTest(encoding=encoding, text=text), self.assertRaisesRegex(ValueError, expected):
                self.convert(song, encoding)
            self.assertEqual(song, before)
        for field, text in (('title', '音' * 86), ('track', '音' * 14), ('text', '音' * 86),
                            ('lyrics', '音' * 21846)):
            song = self.fixture('音')
            if field == 'track':
                song['score']['tracks']['t1']['name'] = text
            elif field == 'lyrics':
                song['score']['tracks']['t1']['lyrics']['text'] = text
            elif field == 'text':
                song['score']['patterns']['m1']['beats'][0]['text'] = text
            else:
                song['score']['metadata'][field] = text
            before = copy.deepcopy(song)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'encoded bytes'):
                self.convert(song, 'utf-8')
            self.assertEqual(song, before)

    def test_malformed_input_refuses_before_publication(self):
        data, _ = self.convert(self.fixture('Песня'), 'cp1251')
        for native in (False, True):
            with self.subTest(native=native), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src = root / 'source.gp5'
                src.write_bytes(data)
                with self.assertRaisesRegex(ValueError, 'UnicodeDecodeError'):
                    gpimport.import_gp(src, root / 'song.yaml', root / 'samples', native=native, encoding='utf-8')
                self.assertEqual(list(root.iterdir()), [src])
                self.assertEqual(src.read_bytes(), data)

    def test_combined_legacy_credit_byte_limit_cannot_truncate(self):
        import copy
        for version in (3, 4):
            song = self.fixture('音', version)
            song['score']['metadata']['author'] = '音' * 43
            song['score']['metadata']['writer'] = '楽' * 43
            before = copy.deepcopy(song)
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'combined author/writer.*255 encoded bytes'):
                self.convert(song, 'utf-8', version)
            self.assertEqual(song, before)

    def test_gpx_xml_keeps_its_declared_encoding(self):
        from tests.test_gpx import rhythm_clef_fixture, bcfs, gp7
        for version in (6, 7):
            xml = rhythm_clef_fixture(version).replace(b'GP rhythm and clefs', '音楽'.encode('utf-8'))
            data = b'BCFS' + bcfs({'score.gpif': xml}) if version == 6 else gp7(xml)
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src = root / 'source.gp'
                src.write_bytes(data)
                song, warnings = gpimport.import_gp(src, root / 'song.yaml', root / 'samples', native=True,
                                                   encoding='cp1251')
                self.assertEqual(song['score']['metadata']['title'], '音楽')
                self.assertTrue(any('XML declares its own text encoding' in w for w in warnings))
                self.assertEqual(src.read_bytes(), data)


class TestGuitarProGroupIdentity(unittest.TestCase):
    def test_redundant_group_labels_export_without_changing_bytes_or_source(self):
        import copy
        for version in (3,4,5):
            for rank in (0,7):
                with self.subTest(version=version,rank=rank):
                    song=TestGuitarProEncoding.fixture('Groups',version)
                    expected=TestGuitarProEncoding.convert(song,None,version)[0]
                    for pattern in song['score']['patterns'].values():
                        for beat in pattern['beats']:beat['cohort']=rank
                    before=copy.deepcopy(song)
                    self.assertEqual(TestGuitarProEncoding.convert(song,None,version)[0],expected)
                    self.assertEqual(song,before)
        song=TestGp5BeatFlagsExport.fixture()
        from vulturetracker import gpexport,tgimport
        convert=lambda s:gpexport.native_to_gp5(s,tgimport._raw(s),channels={'t1':dict(program=25,bank=0)})[0]
        expected=convert(song)
        for pattern in song['score']['patterns'].values():
            for beat in pattern['beats']:beat['cohort']=7
        before=copy.deepcopy(song);self.assertEqual(convert(song),expected);self.assertEqual(song,before)

    def test_distinct_groups_refuse_even_without_annotations(self):
        import copy
        from vulturetracker import gpexport,tgimport
        song=TestGp5BeatFlagsExport.fixture()
        for pattern in song['score']['patterns'].values():
            for beat in pattern['beats']:
                for key in ('text','chord','stroke','pick_stroke'):beat.pop(key,None)
                if beat.get('voice',0)==1:beat['cohort']=1
        before=copy.deepcopy(song)
        with self.assertRaisesRegex(ValueError,'GP reimport merges independent beat groups'):
            gpexport.native_to_gp5(song,tgimport._raw(song),channels={'t1':dict(program=25,bank=0)})
        self.assertEqual(song,before)


if __name__ == "__main__":
    unittest.main()
