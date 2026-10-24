"""Guitar Pro 6 .gpx / Guitar Pro 7 .gp native import, read as TuxGuitar 2.1.0 reads it (vulturetracker/gpx.py).

Fixtures are gpif documents written here and packed with this file's own BCFS/BCFZ/zip writers; none comes from a
real tab."""
import io
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from fractions import Fraction
from xml.sax.saxutils import escape

try:
    import guitarpro  # noqa: F401
except ImportError:  # pragma: no cover
    guitarpro = None

from vulturetracker import gpimport, gpx


def prop(name, inner):
    return f'<Property name="{name}">{inner}</Property>'


def gpif(version, tracks, masterbars, bars, voices, beats, notes, rhythms, automations=(), score='', extra=''):
    """Each argument is a list/dict of ready XML fragments keyed by id."""
    def items(tag, d):
        return ''.join(f'<{tag} id="{i}">{body}</{tag}>' for i, body in d.items())
    autos = ''.join(f'<Automation><Type>{t}</Type><Linear>{str(lin).lower()}</Linear><Bar>{b}</Bar>'
                    f'<Position>{pos}</Position><Visible>true</Visible><Value>{v}</Value></Automation>'
                    for t, b, v, pos, lin in automations)
    tr = ''
    for i, t in enumerate(tracks):
        props = ''.join(t.get('props', []))
        if 'tuning' in t:
            props += prop('Tuning', f'<Pitches>{" ".join(map(str, t["tuning"]))}</Pitches>')
        if t.get('capo'):
            props += prop('CapoFret', f'<Fret>{t["capo"]}</Fret>')
        if version == 6:
            midi = (f'<GeneralMidi><Program>{t["program"]}</Program><PrimaryChannel>{t["gm"][0]}</PrimaryChannel>'
                    f'<SecondaryChannel>{t["gm"][1]}</SecondaryChannel></GeneralMidi><Properties>{props}</Properties>')
        else:
            midi = (f'<MidiConnection><PrimaryChannel>{t["gm"][0]}</PrimaryChannel><SecondaryChannel>{t["gm"][1]}'
                    f'</SecondaryChannel></MidiConnection><Sounds><Sound><MIDI><Program>{t["program"]}</Program></MIDI>'
                    f'</Sound></Sounds><Staves><Staff><Properties>{props}</Properties></Staff></Staves>')
        tr += (f'<Track id="{i}"><Name>{escape(t["name"])}</Name><Color>{t.get("color", "10 20 30")}</Color>{midi}'
               f'{t.get("extra", "")}</Track>')
    return (f'<?xml version="1.0" encoding="UTF-8"?><GPIF><GPRevision>1</GPRevision><Score>{score}</Score>'
            f'<MasterTrack><Automations>{autos}</Automations></MasterTrack><Tracks>{tr}</Tracks>'
            f'<MasterBars>{"".join(f"<MasterBar>{m}</MasterBar>" for m in masterbars)}</MasterBars>'
            f'<Bars>{items("Bar", bars)}</Bars><Voices>{items("Voice", voices)}</Voices>'
            f'<Beats>{items("Beat", beats)}</Beats><Notes>{items("Note", notes)}</Notes>'
            f'<Rhythms>{items("Rhythm", rhythms)}</Rhythms>{extra}</GPIF>').encode('utf-8')


def gp7(xml, version=b'7.0'):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('VERSION', version)
        z.writestr('Content/score.gpif', xml)
    return out.getvalue()


def bcfs(files):
    """BCFS image (after its header): sector 0 unused, then one entry sector per file and its blocks."""
    sector, image = 0x1000, bytearray(0x1000)
    for name, body in files.items():
        blocks = (len(body) + sector - 1) // sector
        first = len(image) // sector + 1
        entry = bytearray(sector)
        entry[0:4] = struct.pack('<i', 2)
        entry[4:4 + len(name)] = name.encode()
        entry[0x8C:0x90] = struct.pack('<i', len(body))
        for k in range(blocks):
            entry[0x94 + 4 * k:0x98 + 4 * k] = struct.pack('<i', first + k)
        image += entry + body.ljust(blocks * sector, b'\0')
    return bytes(image)


def bcfz(raw, overlong=False):
    """TG's BCFZ bit stream: literal runs of 1..3 bytes, and zero runs as doubling back-references."""
    bits = []

    def put(value, n, reverse=False):
        order = range(n) if reverse else range(n - 1, -1, -1)
        bits.extend((value >> i) & 1 for i in order)

    i = 0
    while i < len(raw):
        zeros_before = 0
        while zeros_before < i and raw[i - 1 - zeros_before] == 0:
            zeros_before += 1
        run = 0
        while i + run < len(raw) and raw[i + run] == 0:
            run += 1
        size = min(run, zeros_before, (1 << 15) - 1)
        if size >= 4:
            # overlong: a size field past the offset; TG still copies only offs bytes.
            n = (size + overlong).bit_length()
            put(1, 1), put(n, 4), put(size, n, True), put(size + overlong, n, True)
            i += size
        else:
            chunk = raw[i:i + 3]
            put(0, 1), put(len(chunk), 2, True)
            for b in chunk:
                put(b, 8)
            i += len(chunk)
    bits += [0] * (-len(bits) % 8)
    body = bytes(int(''.join(map(str, bits[k:k + 8])), 2) for k in range(0, len(bits), 8))
    return b'BCFZ' + struct.pack('<i', len(raw)) + body


def gp6(xml, compress=True, overlong=False):
    image = b'BCFS' + bcfs({'score.gpif': xml})
    return bcfz(image, overlong) if compress else image


RHYTHMS = {0: '<NoteValue>Quarter</NoteValue>', 1: '<NoteValue>Eighth</NoteValue>',
           2: '<NoteValue>Eighth</NoteValue><PrimaryTuplet num="3" den="2"/>',
           3: '<NoteValue>Quarter</NoteValue><AugmentationDot count="1"/>', 4: '<NoteValue>Half</NoteValue>',
           5: '<NoteValue>16th</NoteValue>', 6: '<NoteValue>Whole</NoteValue>',
           7: '<NoteValue>Quarter</NoteValue><AugmentationDot count="2"/>'}


def note(string, fret, *props, tie=False, **children):
    body = ''.join(f'<{k}>{v}</{k}>' if v is not True else f'<{k}/>' for k, v in children.items())
    if tie:
        body += '<Tie origin="false" destination="true"/>'
    return body + '<Properties>' + prop('String', f'<String>{string}</String>') + prop('Fret', f'<Fret>{fret}</Fret>') + \
        ''.join(props) + '</Properties>'


def enable(name):
    return prop(name, '<Enable/>')


def beat(rhythm, notes=None, *props, **children):
    body = f'<Rhythm ref="{rhythm}"/>' + (f'<Notes>{" ".join(map(str, notes))}</Notes>' if notes else '')
    body += ''.join(f'<{k}>{v}</{k}>' for k, v in children.items())
    return body + (f'<Properties>{"".join(props)}</Properties>' if props else '')


def fixture(version=6):
    """Guitar + drums, three measures: pickup, effects, repeat/ending."""
    guitar = dict(name='Lead', program=29, gm=(0, 1), tuning=[40, 45, 50, 55, 59, 64], capo=0,
                  extra='<Lyrics><Line><Text>la</Text></Line></Lyrics>')
    drums = dict(name='Drums', program=0, gm=(9, 9))
    whammy = (enable('WhammyBar') + prop('WhammyBarOriginValue', '<Float>0</Float>') +
              prop('WhammyBarMiddleValue', '<Float>-100</Float>') + prop('WhammyBarDestinationValue', '<Float>0</Float>'))
    bend = (enable('Bended') + prop('BendOriginValue', '<Float>0</Float>') + prop('BendDestinationValue', '<Float>50</Float>')
            + prop('BendDestinationOffset', '<Float>60</Float>'))
    notes = {
        0: note(5, 0), 1: note(5, 2, enable('PalmMuted')), 2: note(4, 2, Accent=1),
        3: note(5, 3, prop('HopoOrigin', '<Enable/>')), 4: note(5, 3, tie=True),
        5: note(4, 7, prop('Slide', '<Flags>1</Flags>')), 6: note(4, 9, bend),
        7: note(3, 7, prop('HarmonicType', '<HType>Natural</HType>'), prop('HarmonicFret', '<HFret>7</HFret>')),
        8: note(2, 5, Vibrato='Slight'), 9: note(1, 5, AntiAccent='Normal'), 10: note(0, 5, Accent=8),
        11: note(5, 3, enable('Muted')), 12: note(2, 3, LetRing=True), 13: note(3, 2, Accent=4),
        14: note(2, 5, prop('Midi', '<Number>60</Number>'), Trill=62) + '<XProperties><XProperty id="688062467"><Int>60</Int></XProperty></XProperties>',
        15: note(1, 3), 16: note(4, 7), 17: note(4, 1), 18: note(4, 3),
        30: '<Properties>' + prop('Element', '<Element>0</Element>') + prop('Variation', '<Variation>0</Variation>') + '</Properties>',
        31: '<Properties>' + prop('Element', '<Element>1</Element>') + prop('Variation', '<Variation>0</Variation>') + '</Properties>',
        32: '<Properties>' + prop('Midi', '<Number>42</Number>') + '</Properties>',
    }
    beats = {
        # m1 (pickup: TG shifts it to the end of the bar)
        0: beat(0, [0], Dynamic='MF', FreeText='go'), 1: beat(1, [1, 2]),
        # m2
        2: beat(0, [3]), 3: beat(1, [4]), 4: beat(1, [5]), 5: beat(1, [16], GraceNotes='BeforeBeat'),
        6: beat(0, [6], Fadding='FadeIn'), 7: beat(2, [7]), 8: beat(2, [8]), 9: beat(2, [9, 10]),
        # m3
        10: beat(3, [11, 12], Tremolo='1/8'), 11: beat(1, [13]), 12: beat(0, [14]), 13: beat(0, None),
        14: beat(0, [15], whammy), 15: beat(0, [17], enable('Slapped')),
        # drums
        20: beat(4, [30, 32]), 21: beat(4, [31]), 22: beat(6, [30]), 23: beat(6, [31]),
    }
    voices = {0: '<Beats>0 1</Beats>', 1: '<Beats>2 3 4 5 6 7 8 9</Beats>', 2: '<Beats>10 11 12 13</Beats>',
              3: '<Beats>20</Beats>', 4: '<Beats>21 20</Beats>', 5: '<Beats>22</Beats>', 6: '<Beats>14 15</Beats>'}
    bars = {0: '<Voices>0 -1 -1 -1</Voices>', 1: '<Voices>1 -1 -1 -1</Voices>', 2: '<Voices>2 6 -1 -1</Voices>',
            10: '<Voices>3 -1 -1 -1</Voices>', 11: '<Voices>4 -1 -1 -1</Voices>', 12: '<Voices>5 -1 -1 -1</Voices>'}
    masterbars = ['<Key><AccidentalCount>-2</AccidentalCount><Mode>Major</Mode></Key><Time>3/4</Time><Bars>0 10</Bars>',
                  '<Key><AccidentalCount>-2</AccidentalCount><Mode>Major</Mode></Key><Time>4/4</Time><Bars>1 11</Bars>'
                  '<Repeat start="true" end="false" count="0"/><Section><Text>Verse</Text></Section>',
                  '<Key><AccidentalCount>-2</AccidentalCount><Mode>Major</Mode></Key><Time>4/4</Time><Bars>2 12</Bars>'
                  '<Repeat start="false" end="true" count="2"/><AlternateEndings>1</AlternateEndings>']
    xml = gpif(version, [guitar, drums], masterbars, bars, voices, beats, notes, RHYTHMS,
               automations=[('Tempo', 0, '120 2', 0, False), ('Tempo', 2, '70 4', 0, False)],
               score='<Title>GPX fixture</Title><Artist>Writer</Artist><SubTitle>Sub</SubTitle>')
    return xml


def rhythm_clef_fixture(version=6,tuplet=False):
    """Four fully measured bars, double dots and each pitched clef; original notes."""
    tracks=[dict(name='Changing clefs',program=25,gm=(0,1),tuning=[40,45,50,55,59,64])]
    masterbars=[f'<Time>4/4</Time><Bars>{i}</Bars>' for i in range(4)]
    bars={i:f'<Clef>{clef}</Clef><Voices>{i} -1</Voices>' for i,clef in enumerate(('F4','C3','C4','G2'))}
    voices={i:f'<Beats>{4*i} {4*i+1} {4*i+2} {4*i+3}</Beats>' for i in range(4)}
    rhythms={0:'<NoteValue>Quarter</NoteValue><AugmentationDot count="2"/>'+( '<PrimaryTuplet num="3" den="2"/>' if tuplet else ''),
             1:'<NoteValue>Quarter</NoteValue>',2:'<NoteValue>'+('Eighth' if tuplet else '16th')+'</NoteValue>'}
    beats={i:beat(0 if i%4==0 or tuplet and i%4<3 else 2 if i%4==3 else 1,[i]) for i in range(16)}
    notes={i:note(5,i%5) for i in range(16)}
    return gpif(version,tracks,masterbars,bars,voices,beats,notes,rhythms,score='<Title>GP rhythm and clefs</Title>')


def native(data):
    warnings = []
    gp, balances = gpx.read(data, warnings)
    song = gpimport._native_gp_song(gp, gp.title, warnings=warnings)
    for t, b in zip(song['score']['tracks'].values(), balances):
        t['midi']['source_pan']['value'] = b
    return song, warnings


def all_notes(song, track='t1'):
    return [n for spec in song['score']['patterns'].values() for b in spec['beats'] if b['track'] == track
            for n in b['notes']]


@unittest.skipIf(guitarpro is None, 'needs pyguitarpro')
class TestGpxRead(unittest.TestCase):
    def test_containers_detect_by_content(self):
        xml = fixture(6)
        self.assertEqual(gpx.detect(gp6(xml)), 'gp6')
        self.assertEqual(gpx.detect(gp6(xml, compress=False)), 'gp6')
        self.assertEqual(gpx.detect(gp7(fixture(7))), 'gp7')
        self.assertIsNone(gpx.detect(gp7(fixture(7), b'8.0')))
        self.assertEqual(gpx.gpif(gp6(xml)), (6, xml))
        self.assertEqual(gpx.gpif(gp6(xml, compress=False)), (6, xml))
        self.assertEqual(gpx.gpif(gp6(xml, overlong=True)), (6, xml))
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'tab.bin'
            src.write_bytes(gp6(xml))
            song, _ = gpimport.import_gp(src, Path(tmp) / 'n.yaml', Path(tmp) / 'n', native=True)
            self.assertTrue((Path(tmp) / 'n.yaml').exists())
            gpimport.import_gp(src, Path(tmp) / 'flat.yaml', Path(tmp) / 'flat')
            self.assertTrue((Path(tmp) / 'flat.yaml').exists())

    def test_bcfz_back_reference_longer_than_its_offset_copies_offset_bytes(self):
        # TG copies min(size, offs) bytes: 'ab' + ref(offs=2, size=5) gives 'abab', not 'ababa'.
        bits = '0' + '10' + format(ord('a'), '08b') + '0' + '10' + format(ord('b'), '08b')  # size 1, LSB first
        bits += '1' + format(3, '04b') + format(2, '03b')[::-1] + format(5, '03b')[::-1]
        bits += '0' * (-len(bits) % 8)
        body = bytes(int(bits[k:k + 8], 2) for k in range(0, len(bits), 8))
        self.assertEqual(gpx._unbcfz(struct.pack('<i', 100) + body), b'abab')
        self.assertEqual(gpx._unbcfz(struct.pack('<i', 4) + body), b'')  # TG's offset counts these 4 bytes
        root = gpx.ET.fromstring('<A><B>1E+999999999</B></A>')
        self.assertEqual(gpx._int(root, 'B', 7), 7)  # a crafted exponent is unparseable, not a huge int

    def test_centre_pan_binds_63_like_gp3_to_gp5(self):
        # TG reads no GPX pan (channel default 64); owner decision 2026-10-20: bind 63 as GP3-5 imports do.
        for data in (gp6(fixture(6)), gp7(fixture(7))):
            song, _ = native(data)
            self.assertEqual({t['midi']['source_pan']['value'] for t in song['score']['tracks'].values()}, {63})

    def test_gp6_and_gp7_give_the_same_score(self):
        six, _ = native(gp6(fixture(6)))
        seven, _ = native(gp7(fixture(7)))
        self.assertEqual(six['score'], seven['score'])

    def test_written_content(self):
        song, warnings = native(gp6(fixture(6)))
        t1, t2 = song['score']['tracks']['t1'], song['score']['tracks']['t2']
        self.assertEqual((t1['tuning'], t1['midi']['program'], t1['color']), ([64, 59, 55, 50, 45, 40], 29, '#0a141e'))
        self.assertEqual((t2['midi']['bank'], t2['tuning']), (128, [0] * 6))
        self.assertEqual(t1['key'], dict(fifths=-2, mode='major'))
        m = song['score']['measures']
        self.assertEqual((m[0]['meter'], m[1].get('repeat_open'), m[1]['marker']['title'], m[2]['repeat_close'],
                          m[2]['endings']), ([3, 4], True, 'Verse', 1, [1]))
        self.assertEqual(song['module']['tempo'], 120)  # "120 2": base 2 (quarter) keeps it; "70 4" doubles
        self.assertEqual(song['patterns']['m3']['data'], '00: ... .. ... T8C\n')
        first = [b for b in song['score']['patterns']['m1']['beats'] if b['track'] == 't1']
        self.assertEqual([b['at'] for b in first], [[3, 2], [5, 2]])  # pickup moved to the bar's end
        self.assertEqual(first[0]['text'], 'go')
        def find(string, fret, key):
            return [n.get(key) for n in all_notes(song) if (n['string'], n['fret']) == (string, fret) and key in n]
        self.assertEqual(find(1, 2, 'palm_mute'), [True])
        self.assertEqual(find(2, 2, 'staccato'), [True])
        self.assertEqual(find(3, 7, 'harmonic'), [dict(type='natural', data=3)])
        self.assertEqual(len(find(2, 9, 'bend')), 1)
        self.assertEqual(find(1, 3, 'dead'), [])  # TG: the beat's tremolo picking, set later, clears dead
        self.assertEqual(find(1, 3, 'tremolo_picking'), [dict(value=32)])
        self.assertEqual(find(1, 3, 'hammer'), [True])  # the HopoOrigin note, not the muted one
        self.assertEqual(find(3, 2, 'heavy_accent'), [True])
        self.assertEqual(find(4, 5, 'trill'), [dict(value=32, fret=7)])
        self.assertEqual(find(2, 9, 'grace')[0]['value'], 64)
        self.assertEqual(find(5, 3, 'tremolo_bar'), [dict(points=[dict(position=0, value=0), dict(position=6, value=-2), dict(position=6, value=-2), dict(position=12, value=0)])])
        self.assertTrue(any('Lyrics' in w and 'not read' in w for w in warnings))
        self.assertTrue(any("SubTitle 'Sub'" in w for w in warnings))
        drums = sorted(n['pitch'] for n in all_notes(song, 't2'))
        self.assertEqual(drums, [36, 36, 36, 38, 42, 42])

    def test_tg_effect_exclusions_and_refusals(self):
        xml = fixture(6)
        cases = {
            'overwrites the previous beat': xml.replace(b'<Rhythm ref="1"/><Notes>16</Notes><GraceNotes>',
                                                        b'<Rhythm ref="0"/><Notes>16</Notes><GraceNotes>'),
            'missing Rhythm': xml.replace(b'<Rhythm ref="4"/><Notes>30 32', b'<Rhythm ref="99"/><Notes>30 32'),
            'DOCTYPE': xml.replace(b'<GPIF>', b'<!DOCTYPE GPIF><GPIF>'),
            'alternate ending outside': xml.replace(b'<AlternateEndings>1<', b'<AlternateEndings>9<'),
            'without its \'end\'': xml.replace(b' end="false"', b''),
        }
        for text, data in cases.items():
            with self.subTest(text), self.assertRaisesRegex(ValueError, text):
                native(gp6(data))

    def test_double_dots_and_changing_clefs_roundtrip_and_native_edit(self):
        from vulturetracker import api,gui,tgimport,tablature
        from tests.test_real_interchange import TestRealInterchange
        for version,pack in ((6,gp6),(7,gp7)):
            for tuplet in (False,True):
                with self.subTest(version=version,tuplet=tuplet),tempfile.TemporaryDirectory() as temporary:
                    source=pack(rhythm_clef_fixture(version,tuplet))
                    song,warnings=native(source)
                    self.assertFalse(any('native import keeps the track clef' in w for w in warnings))
                    track=song['score']['tracks']['t1'];self.assertEqual(track['clef'],'bass')
                    clefs=[m.get('staff',{}).get('t1',{}).get('clef',track['clef']) for m in song['score']['measures']]
                    self.assertEqual(clefs,['bass','alto','tenor','treble'])
                    first=song['score']['patterns']['m1']['beats'][0]
                    self.assertEqual(first['written']['dots'],2)
                    self.assertEqual(tablature.duration_quarters(first['written']),Fraction(7,6 if tuplet else 4))
                    data,_=tgimport.native_to_tg(song,tgimport._raw(song),channels={'t1':dict(program=25,bank=0)})
                    again,_=tgimport.read_tg(data)
                    self.assertEqual([b['written'] for p in again['score']['patterns'].values() for b in p['beats']],
                                     [b['written'] for p in song['score']['patterns'].values() for b in p['beats']])
                    self.assertEqual([m.get('staff') for m in again['score']['measures']],[m.get('staff') for m in song['score']['measures']])
                    folder=Path(temporary);src=folder/('source.gpx' if version==6 else 'source.gp');src.write_bytes(source)
                    target,_=gui.import_song(src,folder/'song.yaml',folder/'samples',native_tab=True)
                    api.compile_song(target)
                    TestRealInterchange().exercise_edit(target)
                    self.assertEqual(src.read_bytes(),source)


if __name__ == '__main__':
    unittest.main()
