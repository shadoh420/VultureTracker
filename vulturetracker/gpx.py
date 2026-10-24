"""Guitar Pro 6 .gpx (BCFZ/BCFS) and Guitar Pro 7 .gp (zip) tabs, read as TuxGuitar 2.1.0's GPX readers read them
(GPXFileSystem, GPXDocumentReader, GPXDocumentParser), into a PyGuitarPro Song for gpimport's native conversion.

Pinned source: helge17/tuxguitar 2c46e2a1, common/TuxGuitar-gpx. TG has no GPX writer. What TG ignores or
normalizes is reported in `warnings`; every gpif element TG does not read is listed by path. GP8 files share the
.gp extension; they are read only when their VERSION entry says 7.0, as TG requires."""
import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

HEADER_BCFS = 1397113666
HEADER_BCFZ = 1514554178
LIMIT = 64 << 20  # decompressed bytes; TG has no limit
VELOCITY = dict(PPP=15, PP=31, P=47, MP=63, MF=79, F=95, FF=111, FFF=127)
VALUES = {'Whole': 1, 'Half': 2, 'Quarter': 4, 'Eighth': 8, '16th': 16, '32nd': 32, '64th': 64}
NATURAL_FRETS = (12, 9, 5, 7, 4, 3)  # TGEffectHarmonic.NATURAL_FREQUENCIES[i][0]
DRUMKIT = ((36, 0, 0), (36, 0, 0), (37, 1, 2), (38, 1, 0), (41, 5, 0), (42, 10, 0), (43, 6, 0), (44, 11, 0),
           (45, 7, 0), (46, 10, 2), (47, 8, 0), (48, 9, 0), (49, 12, 0), (50, 9, 0), (51, 15, 0), (52, 16, 0),
           (53, 15, 2), (55, 14, 0), (56, 3, 0), (57, 13, 0), (59, 15, 1))  # (midi, element, variation)


class Refused(ValueError):
    pass


def _int32(data, at):
    return int.from_bytes(data[at:at + 4], 'little', signed=True)


def detect(data):
    """'gp6', 'gp7' or None, by content as TG's two detectors decide."""
    if len(data) >= 4 and _int32(data, 0) in (HEADER_BCFS, HEADER_BCFZ):
        return 'gp6'
    if data[:2] == b'PK':
        try:
            return 'gp7' if _zip_entry(data, 'VERSION')[:3] == b'7.0' else None
        except Exception:  # noqa: BLE001 - not a readable zip: not GP7
            return None
    return None


def _zip_entry(data, name):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info = [i for i in z.infolist() if i.filename == name]
        if not info:
            return None
        if info[-1].file_size > LIMIT:
            raise Refused(f'GP7 {name} exceeds {LIMIT} bytes')
        return z.read(info[-1])


class _Bits:  # GPXByteBuffer
    def __init__(self, data):
        self.data, self.pos = data, 0

    def offset(self):
        return self.pos // 8

    def end(self):
        return self.offset() >= len(self.data)

    def bit(self):
        i = self.pos // 8
        if 0 <= i < len(self.data):
            self.pos += 1
            return (self.data[i] >> (7 - (self.pos - 1) % 8)) & 1
        return -1  # TG ORs -1 into its result

    def bits(self, n):
        v = 0
        for i in range(n - 1, -1, -1):
            v |= self.bit() << i
        return v

    def reversed(self, n):
        v = 0
        for i in range(n):
            v |= self.bit() << i
        return v


def _gp6_files(data):
    header, rest = _int32(data, 0), data[4:]
    for _ in range(8):  # BCFZ may wrap BCFS; TG recurses through load()
        if header == HEADER_BCFS:
            return _bcfs(rest)
        if header != HEADER_BCFZ:
            raise Refused('GPX: this is not a GPX file')
        out = _unbcfz(rest)
        header, rest = _int32(out, 0) if len(out) >= 4 else 0, out[4:]
    raise Refused('GPX: nested compression')


def _unbcfz(rest):
    """GPXFileSystem's BCFZ loop. Like TG, it stops when the COMPRESSED offset reaches the expected length."""
    src, out = _Bits(rest), bytearray()
    expect = _int32(bytes(src.bits(8) & 0xff for _ in range(4)), 0)
    while not src.end() and src.offset() < expect:
        if src.bits(1) == 1:
            n = src.bits(4)
            offs, size = src.reversed(n), src.reversed(n)
            pos = len(out) - offs
            if pos < 0 and min(size, offs) > 0:
                raise Refused('GPX: BCFZ back-reference before the start of the data')
            for i in range(min(size, offs)):
                out.append(out[pos + i])
        else:
            for _ in range(src.reversed(2)):
                out.append(src.bits(8) & 0xff)
        if len(out) > LIMIT:
            raise Refused(f'GPX: decompressed data exceeds {LIMIT} bytes')
    return bytes(out)


def _bcfs(data):
    files, sector, offset, scans = {}, 0x1000, 0, 0

    def int_at(i):
        if i + 4 > len(data):
            raise Refused('GPX: truncated BCFS index')
        return _int32(data, i)

    while True:
        offset += sector
        if offset + 3 >= len(data):
            return files
        scans += 1
        if scans > 2 * (len(data) // sector + 1):
            raise Refused('GPX: BCFS block chain loops (TuxGuitar 2.1.0 would not finish)')
        if int_at(offset) == 2:
            name_at, size_at, blocks_at = offset + 4, offset + 0x8C, offset + 0x94
            chunks, count = [], 0
            while (block := int_at(blocks_at + 4 * count)) != 0:
                count += 1
                offset = block * sector  # TG continues its scan from the last block read
                chunks.append(data[offset:offset + sector].ljust(sector, b'\0'))
                if count * sector > LIMIT:
                    raise Refused(f'GPX: file exceeds {LIMIT} bytes')
            size, body = int_at(size_at), b''.join(chunks)
            if len(body) >= size:
                raw = data[name_at:name_at + 127]
                name = raw.split(b'\0', 1)[0].decode('latin-1')
                files.setdefault(name, body[:size])  # TG returns the first file of a name


def gpif(data):
    """(6 or 7, score.gpif bytes)."""
    kind = detect(data)
    if kind == 'gp6':
        score = _gp6_files(data).get('score.gpif')
    elif kind == 'gp7':
        score = _zip_entry(data, 'Content/score.gpif')
    else:
        raise Refused('not a Guitar Pro 6/7 file')
    if score is None:
        raise Refused(f'GP{kind[-1]}: no score.gpif')
    return int(kind[-1]), score


# ---------------------------------------------------------------- GPXDocumentReader

_WS = ''.join(map(chr, range(33)))


def _child(node, name):
    return None if node is None else node.find(name)


def _text(node, name):
    c = _child(node, name)
    return None if c is None else ''.join(c.itertext())


def _num(text):  # new BigDecimal(text).intValue()
    if text is None or not re.fullmatch(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?', text):
        raise InvalidOperation
    value = Decimal(text)
    if value and value.adjusted() > 18:  # Java wraps; refuse to build a huge int from a crafted exponent
        raise InvalidOperation
    return int(value)


def _int(node, name, default=0):
    try:
        return _num(_text(node, name))
    except InvalidOperation:
        return default


def _ints(node, name, sep=' '):
    raw = _text(node, name)
    if raw is None:
        return None
    parts = raw.strip(_WS).split(sep)
    while parts and parts[-1] == '':  # Java's split drops trailing empty strings
        parts.pop()
    out = []
    for p in parts or ['']:
        try:
            out.append(_num(p.strip(_WS)))
        except InvalidOperation:
            out.append(0)
    return out


def _attr(node, name, what):
    if node is None:
        return None
    value = node.get(name)
    if value is None:
        raise Refused(f'GPX: TuxGuitar 2.1.0 cannot read {what} without its {name!r} attribute')
    return value


def _attr_int(node, name):
    try:
        return _num(node.get(name)) if node is not None else 0
    except InvalidOperation:
        return 0


def _props(node, name='Properties'):
    return [] if _child(node, name) is None else [p for p in _child(node, name) if p.tag == 'Property']


def _read(xml, version):
    """GPXDocumentReader.read() as plain dicts."""
    root = xml
    doc = dict(score={}, automations=[], tracks=[], chords=[], masterbars=[], bars={}, voices={}, beats={},
               notes={}, rhythms={})
    score = _child(root, 'Score')
    if score is not None:
        for key in ('Title', 'SubTitle', 'Artist', 'Album', 'Words', 'Music', 'WordsAndMusic', 'Copyright',
                    'Tabber', 'Instructions', 'Notices'):
            doc['score'][key] = _text(score, key)
    master = _child(root, 'MasterTrack')
    for a in [] if _child(master, 'Automations') is None else _child(master, 'Automations'):
        if a.tag == 'Automation':
            doc['automations'].append(dict(type=_text(a, 'Type'), bar=_int(a, 'Bar'), value=_ints(a, 'Value'),
                                           linear=_text(a, 'Linear') == 'true', position=_int(a, 'Position')))

    def free(track):  # getFreeGmChannel
        ch = 0
        while True:
            ch += 1
            used = track is not None and ch in (track['gm1'], track['gm2'])
            used |= any(ch in (t['gm1'], t['gm2']) for t in doc['tracks'])
            if not used and ch != 9:
                return ch

    for t in [] if _child(root, 'Tracks') is None else _child(root, 'Tracks'):
        if t.tag != 'Track':
            continue
        name = _text(t, 'Name')
        if name is None:
            raise Refused('GPX: TuxGuitar 2.1.0 cannot read a track without Name')
        track = dict(id=_attr_int(t, 'id'), name=name.replace('\n', '').strip(_WS), color=_ints(t, 'Color'),
                     program=0, gm1=0, gm2=0, tuning=None, capo=0)
        if version == 6:
            gm = _child(t, 'GeneralMidi')
            if gm is not None:
                track['program'] = _int(gm, 'Program')
                track['gm1'] = _int(gm, 'PrimaryChannel', free(None))
                track['gm2'] = _int(gm, 'SecondaryChannel', free(track))
        else:
            conn = _child(t, 'MidiConnection')
            primary = _int(conn, 'PrimaryChannel', -1) if conn is not None else -1
            secondary = _int(conn, 'SecondaryChannel', -1) if conn is not None else -1
            for sound in [] if _child(t, 'Sounds') is None else _child(t, 'Sounds'):
                if sound.tag == 'Sound' and _child(sound, 'MIDI') is not None:
                    track['program'] = _int(_child(sound, 'MIDI'), 'Program')
            if primary >= 0 and secondary >= 0:
                track['gm1'], track['gm2'] = primary, secondary
            else:
                drums = False
                inst = _child(t, 'InstrumentSet')
                if inst is not None:
                    for key in ('Name', 'Type'):
                        value = _text(inst, key)
                        if value is None:
                            raise Refused(f'GP7: TuxGuitar 2.1.0 cannot read an InstrumentSet without {key}')
                        drums |= 'drum' in value.lower()
                if drums and track['program'] == 0:
                    track['gm1'] = track['gm2'] = 9
                else:
                    track['gm1'] = free(None)
                    track['gm2'] = free(track)
        props = _props(t) if version == 6 else _props(_child(_child(t, 'Staves'), 'Staff'))
        for p in props:
            kind = _attr(p, 'name', 'a track Property')
            if kind == 'Tuning':
                track['tuning'] = _ints(p, 'Pitches')
            elif kind == 'CapoFret':
                track['capo'] = _int(p, 'Fret', 0)
        doc['tracks'].append(track)
        for p in props:
            if _attr(p, 'name', 'a track Property') != 'DiagramCollection' or _child(p, 'Items') is None:
                continue
            for item in _child(p, 'Items'):
                diagram = _child(item, 'Diagram')
                if item.tag != 'Item' or diagram is None:
                    continue
                count = diagram.get('fretCount')
                chord = dict(id=_attr_int(item, 'id'), name=_attr(item, 'name', 'a chord Item'),
                             base=_attr_int(diagram, 'baseFret') if diagram.get('baseFret') is not None else None)
                if count is None:
                    continue
                frets = [None] * _attr_int(diagram, 'fretCount')
                for f in diagram:
                    string = _attr_int(f, 'string') if f.get('string') is not None else None
                    if f.tag == 'Fret' and string is not None and 0 < string <= len(frets):
                        frets[string - 1] = _attr_int(f, 'fret')
                chord['frets'] = frets
                doc['chords'].append(chord)
    for m in [] if _child(root, 'MasterBars') is None else _child(root, 'MasterBars'):
        if m.tag != 'MasterBar':
            continue
        bar = dict(bars=_ints(m, 'Bars'), time=_ints(m, 'Time', '/'), feel=_text(m, 'TripletFeel'),
                   start=False, count=0, accidentals=0, mode=None, endings=_ints(m, 'AlternateEndings'), marker=None)
        repeat = _child(m, 'Repeat')
        if repeat is not None:
            bar['start'] = _attr(repeat, 'start', 'a Repeat') == 'true'
            if _attr(repeat, 'end', 'a Repeat') == 'true':
                bar['count'] = _attr_int(repeat, 'count') - 1
        key = _child(m, 'Key')
        if key is not None:
            bar['accidentals'], bar['mode'] = _int(key, 'AccidentalCount'), _text(key, 'Mode')
        section = _child(m, 'Section')
        if section is not None:
            text = _text(section, 'Text')
            if text is None:
                raise Refused('GPX: TuxGuitar 2.1.0 cannot read a Section without Text')
            bar['marker'] = text.replace('\n', '').strip(_WS)
        doc['masterbars'].append(bar)
    for b in [] if _child(root, 'Bars') is None else _child(root, 'Bars'):
        if b.tag == 'Bar':
            doc['bars'].setdefault(_attr_int(b, 'id'), dict(voices=_ints(b, 'Voices'), clef=_text(b, 'Clef'),
                                                            simile=_text(b, 'SimileMark')))
    for v in [] if _child(root, 'Voices') is None else _child(root, 'Voices'):
        if v.tag == 'Voice':
            doc['voices'].setdefault(_attr_int(v, 'id'), _ints(v, 'Beats'))
    for b in [] if _child(root, 'Beats') is None else _child(root, 'Beats'):
        if b.tag != 'Beat':
            continue
        text = _text(b, 'FreeText')
        beat = dict(dynamic=_text(b, 'Dynamic'), text=text if text is not None else '',
                    rhythm=_attr_int(_child(b, 'Rhythm'), 'ref'), tremolo=_ints(b, 'Tremolo', '/'),
                    notes=_ints(b, 'Notes'), chord=_int(b, 'Chord', None), fading=_text(b, 'Fadding'),
                    grace=_text(b, 'GraceNotes'), pick='', brush='', whammy=False, slapped=False, popped=False)
        for p in _props(b):
            kind = _attr(p, 'name', 'a beat Property')
            if kind == 'PickStroke':
                beat['pick'] = _text(p, 'Direction')
            elif kind in ('WhammyBar', 'Slapped', 'Popped'):
                beat[{'WhammyBar': 'whammy', 'Slapped': 'slapped', 'Popped': 'popped'}[kind]] = _child(p, 'Enable') is not None
            elif kind.startswith('WhammyBar'):
                beat[kind] = _int(p, 'Float')
            elif kind == 'Brush':
                beat['brush'] = _text(p, 'Direction')
        doc['beats'].setdefault(_attr_int(b, 'id'), beat)
    for n in [] if _child(root, 'Notes') is None else _child(root, 'Notes'):
        if n.tag != 'Note':
            continue
        tie = _child(n, 'Tie')
        note = dict(tie=tie is not None and _attr(tie, 'destination', 'a Tie') == 'true',
                    ghost=_text(n, 'AntiAccent') == 'Normal', accent=_int(n, 'Accent'), trill=_int(n, 'Trill'),
                    let_ring=_child(n, 'LetRing') is not None, vibrato=_child(n, 'Vibrato') is not None,
                    string=-1, fret=-1, midi=-1, tone=-1, octave=-1, element=-1, variation=-1, muted=False,
                    palm=False, slide=False, slide_flags=0, tapped=False, bend=False, hammer=False,
                    harmonic_fret=-1, harmonic_type='', trill_duration=0)
        simple = dict(String=('string', 'String'), Fret=('fret', 'Fret'), Midi=('midi', 'Number'),
                      Tone=('tone', 'Step'), Octave=('octave', 'Number'), Element=('element', 'Element'),
                      Variation=('variation', 'Variation'), HarmonicFret=('harmonic_fret', 'HFret'))
        for p in _props(n):
            kind = _attr(p, 'name', 'a note Property')
            if kind in simple:
                note[simple[kind][0]] = _int(p, simple[kind][1])
            elif kind in ('Muted', 'PalmMuted', 'Tapped', 'Bended'):
                note[{'Muted': 'muted', 'PalmMuted': 'palm', 'Tapped': 'tapped', 'Bended': 'bend'}[kind]] = \
                    _child(p, 'Enable') is not None
            elif kind == 'Slide':
                note['slide'], note['slide_flags'] = True, _int(p, 'Flags')
            elif kind.startswith('Bend'):
                note[kind] = _int(p, 'Float')
            elif kind == 'HopoOrigin':
                note['hammer'] = True
            elif kind == 'HarmonicType':
                note['harmonic_type'] = _text(p, 'HType')
        for x in [] if _child(n, 'XProperties') is None else _child(n, 'XProperties'):
            if x.tag == 'XProperty' and _attr(x, 'id', 'an XProperty') == '688062467':
                note['trill_duration'] = _int(x, 'Int')
        doc['notes'].setdefault(_attr_int(n, 'id'), note)
    for r in [] if _child(root, 'Rhythms') is None else _child(root, 'Rhythms'):
        if r.tag != 'Rhythm':
            continue
        tuplet, dot = _child(r, 'PrimaryTuplet'), _child(r, 'AugmentationDot')
        doc['rhythms'].setdefault(_attr_int(r, 'id'), dict(
            value=_text(r, 'NoteValue'), den=_attr_int(tuplet, 'den') if tuplet is not None else 1,
            num=_attr_int(tuplet, 'num') if tuplet is not None else 1,
            dots=_attr_int(dot, 'count') if dot is not None else 0))
    return doc


# Elements GPXDocumentReader reads; anything else in the file is reported as not read.
_READ = {
    'Score': {'Title', 'SubTitle', 'Artist', 'Album', 'Words', 'Music', 'WordsAndMusic', 'Copyright', 'Tabber',
              'Instructions', 'Notices'},
    'MasterTrack/Automations/Automation': {'Type', 'Bar', 'Value', 'Linear', 'Position', 'Visible'},
    'Tracks/Track': {'Name', 'Color', 'GeneralMidi', 'MidiConnection', 'Sounds', 'InstrumentSet', 'Properties',
                     'Staves'},
    'MasterBars/MasterBar': {'Bars', 'Time', 'TripletFeel', 'Repeat', 'Key', 'AlternateEndings', 'Section'},
    'Bars/Bar': {'Voices', 'Clef', 'SimileMark'},
    'Voices/Voice': {'Beats'},
    'Beats/Beat': {'Dynamic', 'FreeText', 'Rhythm', 'Tremolo', 'Notes', 'Chord', 'Fadding', 'GraceNotes',
                   'Properties'},
    'Notes/Note': {'Tie', 'AntiAccent', 'Accent', 'Trill', 'LetRing', 'Vibrato', 'Properties', 'XProperties'},
    'Rhythms/Rhythm': {'NoteValue', 'PrimaryTuplet', 'AugmentationDot'},
}
_BEAT_PROPS = {'PickStroke', 'WhammyBar', 'WhammyBarOriginValue', 'WhammyBarMiddleValue', 'WhammyBarDestinationValue',
               'WhammyBarOriginOffset', 'WhammyBarMiddleOffset1', 'WhammyBarMiddleOffset2',
               'WhammyBarDestinationOffset', 'Brush', 'Slapped', 'Popped'}
_NOTE_PROPS = {'String', 'Fret', 'Midi', 'Tone', 'Octave', 'Element', 'Variation', 'Muted', 'PalmMuted', 'Slide',
               'Tapped', 'Bended', 'BendOriginValue', 'BendMiddleValue', 'BendDestinationValue', 'BendOriginOffset',
               'BendMiddleOffset1', 'BendMiddleOffset2', 'BendDestinationOffset', 'HopoOrigin', 'HopoDestination',
               'HarmonicFret', 'HarmonicType'}


def unread(root):
    """{element path: count} for gpif content TG 2.1.0's reader never looks at."""
    found = {}

    def note(path):
        found[path] = found.get(path, 0) + 1

    tops = {'Score', 'MasterTrack', 'Tracks', 'MasterBars', 'Bars', 'Voices', 'Beats', 'Notes', 'Rhythms'}
    for top in root:
        if top.tag not in tops:
            note(top.tag)
    for path, known in _READ.items():
        parent, _, leaf = path.rpartition('/')
        holders = root.findall(path) if parent else [root.find(path)]
        for node in holders:
            if node is None:
                continue
            for c in node:
                if c.tag not in known:
                    note(f'{path}/{c.tag}')
            if path == 'MasterTrack/Automations/Automation' and _text(node, 'Type') != 'Tempo':
                note(f'{path}[Type={_text(node, "Type")}]')
            if path in ('Beats/Beat', 'Notes/Note'):
                names = _BEAT_PROPS if path == 'Beats/Beat' else _NOTE_PROPS
                for p in _props(node):
                    if p.get('name') not in names:
                        note(f'{path}/Properties/Property[name={p.get("name")}]')
            if path == 'Notes/Note':
                for x in [] if _child(node, 'XProperties') is None else _child(node, 'XProperties'):
                    if x.get('id') != '688062467':
                        note(f'{path}/XProperties/XProperty[id={x.get("id")}]')
    for t in root.findall('Tracks/Track'):
        for p in _props(t) + _props(_child(_child(t, 'Staves'), 'Staff')):
            if p.get('name') not in ('Tuning', 'CapoFret', 'DiagramCollection'):
                note(f'Tracks/Track/Properties/Property[name={p.get("name")}]')
    return found


# ---------------------------------------------------------------- GPXDocumentParser

class _Effect:
    """TGNoteEffect's setters, with their mutual exclusions, for the fields native import keeps."""
    PITCH = ('bend', 'tremolo_bar', 'trill', 'tremolo_picking')

    def __init__(self):
        self.v = dict(bend=None, tremolo_bar=None, trill=None, tremolo_picking=None, harmonic=None, grace=None)

    def set(self, key, value):
        v = self.v
        v[key] = value
        if not value:
            return
        clears = dict(
            dead=('bend', 'trill', 'slide', 'hammer', 'tremolo_bar', 'tremolo_picking'),
            vibrato=('trill', 'tremolo_picking'),
            bend=('trill', 'dead', 'slide', 'hammer', 'tremolo_bar', 'tremolo_picking'),
            tremolo_bar=('bend', 'trill', 'dead', 'slide', 'hammer', 'tremolo_picking'),
            trill=('bend', 'tremolo_bar', 'tremolo_picking', 'slide', 'hammer', 'dead', 'vibrato'),
            tremolo_picking=('trill', 'bend', 'tremolo_bar', 'slide', 'hammer', 'dead', 'vibrato'),
            hammer=('trill', 'bend', 'dead', 'slide', 'tremolo_bar', 'tremolo_picking'),
            slide=('trill', 'bend', 'dead', 'hammer', 'tremolo_bar', 'tremolo_picking'),
            ghost=('accent', 'heavy_accent'), accent=('ghost', 'heavy_accent'), heavy_accent=('ghost', 'accent'),
            palm_mute=('staccato', 'let_ring'), staccato=('palm_mute', 'let_ring'), let_ring=('staccato', 'palm_mute'),
            popping=('tapping', 'slapping'), slapping=('tapping', 'popping'), tapping=('slapping', 'popping'),
        ).get(key, ())
        for k in clears:
            v[k] = None if k in self.PITCH else False


def _round(x):  # Java Math.round(float)
    return math.floor(x + 0.5)


def read(data, warnings):
    """Return (guitarpro.models.Song mirroring TG 2.1.0's GPX parser, TG's balance per track)."""
    from guitarpro import models as M

    version, score = gpif(data)
    if b'<!DOCTYPE' in score:
        raise Refused(f'GP{version}: DOCTYPE is refused (TuxGuitar 2.1.0 disallows it)')
    try:
        root = ET.fromstring(score)
    except ET.ParseError as e:
        raise Refused(f'GP{version}: invalid score.gpif ({e})') from None
    doc = _read(root, version)
    tag = f'GP{version}'

    def loss(what):
        warnings.append(f'{tag} {what}')

    for path, n in sorted(unread(root).items()):
        loss(f'{n} {path} element(s) not read by TuxGuitar 2.1.0')
    sc = doc['score']
    for key in ('SubTitle', 'Words', 'Music', 'Instructions'):
        if sc.get(key):
            loss(f'score {key} {sc[key]!r} is read but discarded by TuxGuitar 2.1.0')

    song = M.Song(versionTuple=(version, 0, 0), tracks=[], measureHeaders=[])
    song.masterEffect.volume = 100  # neutral; TG reads no GPX master volume
    song.title, song.artist, song.album = sc.get('Title') or '', sc.get('Artist') or '', sc.get('Album') or ''
    song.words, song.copyright, song.tab = sc.get('WordsAndMusic') or '', sc.get('Copyright') or '', sc.get('Tabber') or ''
    song.notice = [sc['Notices']] if sc.get('Notices') else []
    channels = {}  # gm1 -> (program, gm2) of the first track that created it
    for i, t in enumerate(doc['tracks']):
        drums = t['gm1'] == 9
        program, gm2 = (0 if drums else t['program']), (t['gm1'] if drums else t['gm2'])
        if t['gm1'] in channels:
            if channels[t['gm1']] != (program, gm2):
                loss(f'track {i + 1} shares TuxGuitar channel {t["gm1"]} with an earlier track; its program/'
                     'secondary route are replaced by that track\'s')
            program, gm2 = channels[t['gm1']]
        channels.setdefault(t['gm1'], (program, gm2))
        if not 0 <= program <= 127 or not 0 <= t['gm1'] <= 15 or not 0 <= gm2 <= 15:
            raise Refused(f'{tag} track {i + 1}: MIDI program/routes outside 0..127 / 0..15')
        track = M.Track(song, number=i + 1, name=t['name'], fretCount=29, isPercussionTrack=drums)
        track.channel = M.MidiChannel(channel=t['gm1'], effectChannel=gm2, instrument=program, volume=128, balance=64)
        if t['tuning'] is not None:
            track.strings = [M.GuitarString(s, t['tuning'][-s]) for s in range(1, len(t['tuning']) + 1)]
            track.offset = t['capo']
        else:
            track.strings = [M.GuitarString(s, p) for s, p in enumerate((0,) * 6 if drums else (64, 59, 55, 50, 45, 40), 1)]
        if t['color'] is not None and len(t['color']) == 3:
            if not all(0 <= c <= 255 for c in t['color']):
                raise Refused(f'{tag} track {i + 1}: colour outside 0..255')
            track.color = M.Color(*t['color'])
        else:
            track.color = M.Color(255, 0, 0)
        track.measures = []
        song.tracks.append(track)

    def div(a, b):  # Java int division
        return int(a / b)

    start = 960
    for i, mb in enumerate(doc['masterbars']):
        header = M.MeasureHeader(number=i + 1, start=start, isRepeatOpen=mb['start'])
        header.repeatClose = mb['count'] if mb['count'] > 0 else -1
        if mb['endings'] is not None:
            if any(not 1 <= e <= 8 for e in mb['endings']):
                raise Refused(f'{tag} measure {i + 1}: alternate ending outside 1..8')
            header.repeatAlternative = sum({1 << (e - 1) for e in mb['endings']})
        header.tripletFeel = {'Triplet8th': M.TripletFeel.eighth, 'Triplet16th': M.TripletFeel.sixteenth}.get(
            mb['feel'], M.TripletFeel.none)
        if mb['time'] is not None and len(mb['time']) == 2:
            num, den = mb['time']
            if den not in (1, 2, 4, 8, 16, 32, 64) or not 1 <= num <= 64:
                raise Refused(f'{tag} measure {i + 1}: meter {num}/{den} is unsupported')
            header.timeSignature = M.TimeSignature(num, M.Duration(den))
        auto = None
        for a in doc['automations']:
            if a['type'] == 'Tempo' and a['bar'] <= i and (auto is None or a['bar'] > auto['bar']):
                auto = a
        tempo = 120  # TGTempo default; TG does not carry the previous header's
        if auto is not None and auto['value'] is not None and len(auto['value']) == 2:
            value, base = auto['value']
            tempo = {1: div(value, 2), 3: value + div(value, 2), 4: value * 2, 5: value * 3}.get(base, value)
            if auto['bar'] == i and (auto['position'] or auto['linear']):
                loss(f'measure {i + 1}: tempo automation position {auto["position"]}, linear={auto["linear"]}; '
                     'TuxGuitar 2.1.0 applies it to the whole measure')
        header.tg_tempo = tempo
        if i == 0:
            song.tempo = tempo
        if mb['marker']:
            header.marker = M.Marker(mb['marker'], M.Color(255, 0, 0))
        acc = mb['accidentals'] if mb['accidentals'] >= 0 else 7 - mb['accidentals']
        fifths = (acc if acc <= 7 else 7 - acc) if 0 <= acc <= 14 else 0
        if not 0 <= acc <= 14:
            loss(f'measure {i + 1}: key accidental count {mb["accidentals"]} is ignored by TuxGuitar 2.1.0')
        if mb['mode'] not in (None, 'Major'):
            loss(f'measure {i + 1}: key mode {mb["mode"]!r} is discarded by TuxGuitar 2.1.0')
        header.keySignature = M.KeySignature((fifths, 0))
        song.measureHeaders.append(header)
        if mb['bars'] is None:
            raise Refused(f'{tag} measure {i + 1}: TuxGuitar 2.1.0 cannot read a MasterBar without Bars')
        for ti, track in enumerate(song.tracks):
            measure = M.Measure(track, header)
            measure.tg_clef = 'treble'  # TG creates each GPX measure with the default clef.
            track.measures.append(measure)
            index, bar = i, (doc['bars'].get(mb['bars'][ti]) if ti < len(mb['bars']) else None)
            while bar is not None and bar['simile'] is not None:
                index -= {'Simple': 1, 'FirstOfDouble': 2, 'SecondOfDouble': 2}.get(bar['simile'], 0)
                if bar['simile'] not in ('Simple', 'FirstOfDouble', 'SecondOfDouble'):
                    raise Refused(f'{tag} measure {i + 1}: simile mark {bar["simile"]!r} loops in TuxGuitar 2.1.0')
                copy = doc['masterbars'][index] if index >= 0 else None
                bar = None if copy is None or ti >= len(copy['bars']) else doc['bars'].get(copy['bars'][ti])
            if bar is not None:
                _parse_bar(M, doc, bar, measure, track, tag, loss)
        start += header.length
    # TG reads no GPX pan and plays its channel default, 64. Owner decision 2026-10-20: bind centre as 63, as
    # GP3-5 imports do, so GP3/4/5 export works; CC10 differs from TuxGuitar by one step.
    return song, [63] * len(song.tracks)


def _duration(M, rhythm, tag, where):
    if rhythm is None:
        raise Refused(f'{tag} {where}: beat refers to a missing Rhythm (TuxGuitar 2.1.0 fails)')
    if rhythm['value'] is None:
        raise Refused(f'{tag} {where}: Rhythm without NoteValue (TuxGuitar 2.1.0 fails)')
    if rhythm['num'] <= 0 or rhythm['den'] <= 0:
        raise Refused(f'{tag} {where}: tuplet {rhythm["num"]}:{rhythm["den"]} is invalid')
    value = VALUES.get(rhythm['value'], 4)
    tuplet = M.Tuplet(rhythm['num'], rhythm['den'])
    if rhythm['dots'] == 2:
        # PyGuitarPro's GP1-5 duration has only one dot. Preserve the GPX
        # written value and TG legacy tick time at this existing adapter boundary.
        duration = SimpleNamespace(value=value,isDotted=False,isDoubleDotted=True,tuplet=tuplet,
                                   time=tuplet.convertTime((M.Duration.quarterTime*4//value)*7//4))
    else:
        duration = M.Duration(value,rhythm['dots']==1,tuplet)
    return duration, rhythm['value'] in VALUES


def _curve(origin, middle, dest, o_off, m1, m2, d_off, value, position, bar):
    """GPXDocumentParser.parseBend / parseTremoloBar point lists, in TG's order."""
    points = [(0, value(origin))]
    if o_off is not None:
        points.append((position(o_off), value(origin)))
    if middle is not None:
        if bar:
            off1 = m1 if m1 is not None else 50
            if o_off is None or off1 >= o_off:
                points.append((position(off1), value(middle)))
            off2 = m2 if m2 is not None else 50
            if o_off is None or off1 >= o_off and off2 > off1:
                points.append((position(off2), value(middle)))
        else:
            for off in (m1, m2):
                if off is None or off != 12:
                    points.append((position(off if off is not None else 50), value(middle)))
    if d_off is not None and d_off < 100:
        points.append((position(d_off), value(dest)))
    points.append((12, value(dest)))
    return points


def _parse_bar(M, doc, bar, measure, track, tag, loss):
    where = f'track {track.number}, measure {measure.number}'
    measure.tg_clef = {'F4':'bass','C3':'alto','C4':'tenor'}.get(bar['clef'],'treble')
    if bar['voices'] is None:
        raise Refused(f'{tag} {where}: TuxGuitar 2.1.0 cannot read a Bar without Voices')
    shared = {}  # TG beat start -> one TG beat's stroke/pick/text/chord, and its string occupancy
    for v in range(2):
        if v >= len(bar['voices']) or bar['voices'][v] < 0 or doc['voices'].get(bar['voices'][v]) is None:
            continue
        voice = measure.voices[v]
        beat_ids = doc['voices'][bar['voices'][v]]
        if beat_ids is None:
            raise Refused(f'{tag} {where}: TuxGuitar 2.1.0 cannot read a Voice without Beats')
        at, previous, graces, previous_beat = measure.start, None, None, None
        for bi, beat_id in enumerate(beat_ids):
            gb = doc['beats'].get(beat_id)
            if gb is None:
                raise Refused(f'{tag} {where}: voice refers to a missing Beat (TuxGuitar 2.1.0 fails)')
            loc = f'{where}, voice {v + 1}, beat {bi + 1}'
            duration, known = _duration(M, doc['rhythms'].get(gb['rhythm']), tag, loc)
            if gb['grace'] is not None:
                # TG parses the grace rhythm INTO the previous beat's duration object.
                if previous_beat is not None and previous_beat.duration != duration:
                    raise Refused(f'{tag} {loc}: TuxGuitar 2.1.0 overwrites the previous beat\'s written duration '
                                  'with this grace beat\'s rhythm')
                graces = [doc['notes'][n] for n in gb['notes'] or [] if n in doc['notes']]
                previous, grace_value = gb, duration.value
                continue
            if not known:
                loss(f'{loc}: NoteValue {doc["rhythms"][gb["rhythm"]]["value"]!r} is read as a quarter by TuxGuitar 2.1.0')
            for key in ('brush', 'pick'):
                if gb[key] is None:
                    raise Refused(f'{tag} {loc}: TuxGuitar 2.1.0 cannot read a {key} property without Direction')
            beat = M.Beat(voice, start=at, duration=duration, status=M.BeatStatus.normal)
            state = shared.setdefault(at, dict(strings=set(), beats=[], text='', chord=None, stroke=None, pick=None))
            state['beats'].append(beat)
            state['stroke'] = {'Down': 'down', 'Up': 'up'}.get(gb['brush'], 'none')
            state['pick'] = {'Down': 'down', 'Up': 'up'}.get(gb['pick'], 'none')
            if gb['text']:
                state['text'] = gb['text'].strip(_WS)
            if gb['chord'] is not None:
                chord = next((c for c in doc['chords'] if c['id'] == gb['chord']), None)
                if chord is not None:
                    state['chord'] = chord
            velocity = VELOCITY.get(gb['dynamic'], 95)
            fade = gb['fading'] == 'FadeIn'
            if gb['fading'] not in (None, 'FadeIn'):
                loss(f'{loc}: fading {gb["fading"]!r} is ignored by TuxGuitar 2.1.0')
            techniques, fades = set(), False
            for nid in gb['notes'] or []:
                gn = doc['notes'].get(nid)
                if gn is None:
                    loss(f'{loc}: note id {nid} does not exist and is skipped by TuxGuitar 2.1.0')
                    continue
                value, string = -1, -1
                if gn['string'] >= 0 and gn['fret'] >= 0:
                    value, string = gn['fret'], len(track.strings) - gn['string']
                else:
                    gm = -1
                    if gn['midi'] >= 0:
                        gm = gn['midi']
                    elif gn['tone'] >= 0 and gn['octave'] >= 0:
                        gm = gn['tone'] + 12 * gn['octave'] - 12
                    elif gn['element'] >= 0:
                        for midi, element, variation in DRUMKIT:
                            if element == gn['element'] and variation == gn['variation']:
                                gm = midi
                    if gm >= 0:
                        free = next((s for s in track.strings if gm >= s.value and s.number not in state['strings']), None)
                        if free is not None:
                            value, string = gm - free.value, free.number
                if value < 0 or string <= 0:
                    loss(f'{loc}: a note TuxGuitar 2.1.0 cannot place on a string is dropped')
                    continue
                state['strings'].add(string)
                e = _Effect()
                for key, enabled in (('fade_in', fade), ('vibrato', gn['vibrato']), ('let_ring', gn['let_ring']),
                                     ('slide', gn['slide']), ('dead', gn['muted']), ('palm_mute', gn['palm']),
                                     ('tapping', gn['tapped']), ('hammer', gn['hammer']), ('ghost', gn['ghost']),
                                     ('slapping', gb['slapped']), ('popping', gb['popped']),
                                     ('staccato', gn['accent'] == 1), ('heavy_accent', gn['accent'] == 4),
                                     ('accent', gn['accent'] == 8)):
                    e.set(key, enabled)
                if gn['accent'] not in (0, 1, 4, 8):
                    loss(f'{loc}: accent flags {gn["accent"]} match none of TuxGuitar 2.1.0\'s single values; dropped')
                if gn['slide'] and gn['slide_flags'] not in (1, 2):
                    loss(f'{loc}: slide flags {gn["slide_flags"]} become a plain slide to the next note in TuxGuitar 2.1.0')
                if gn['trill'] > 0:
                    ticks = gn['trill_duration'] * 2
                    if ticks not in (240, 120, 60):
                        raise Refused(f'{tag} {loc}: trill duration {gn["trill_duration"]} is not a 16th/32nd/64th')
                    e.set('trill', (value + gn['trill'] - gn['midi'], {240: 16, 120: 32, 60: 64}[ticks]))
                if gb['tremolo'] is not None and len(gb['tremolo']) == 2:
                    e.set('tremolo_picking', 4 * gb['tremolo'][1])
                if gn['harmonic_type']:
                    kind = {'Artificial': 'artificial', 'Pinch': 'pinch'}.get(gn['harmonic_type'], 'natural')
                    data = NATURAL_FRETS.index(gn['harmonic_fret']) if gn['harmonic_fret'] in NATURAL_FRETS else 0
                    e.set('harmonic', (kind, data))
                if gn['bend'] and gn.get('BendOriginValue') is not None and gn.get('BendDestinationValue') is not None:
                    e.set('bend', _curve(gn.get('BendOriginValue'), gn.get('BendMiddleValue'), gn.get('BendDestinationValue'),
                                         gn.get('BendOriginOffset'), gn.get('BendMiddleOffset1'), gn.get('BendMiddleOffset2'),
                                         gn.get('BendDestinationOffset'), lambda x: _round(x / 25),
                                         lambda x: _round(x * 12 / 100), False))
                if gb['whammy'] and gb.get('WhammyBarOriginValue') is not None and gb.get('WhammyBarDestinationValue') is not None:
                    e.set('tremolo_bar', _curve(gb.get('WhammyBarOriginValue'), gb.get('WhammyBarMiddleValue'),
                                                gb.get('WhammyBarDestinationValue'), gb.get('WhammyBarOriginOffset'),
                                                gb.get('WhammyBarMiddleOffset1'), gb.get('WhammyBarMiddleOffset2'),
                                                gb.get('WhammyBarDestinationOffset'),
                                                lambda x: max(-12, min(12, _round(x / 50))),
                                                lambda x: _round(x * 12 / 100), True))
                if previous is not None and previous['grace'] is not None and graces is not None:
                    g = next((x for x in graces if x['string'] == gn['string']), None)
                    if g is not None:
                        e.set('grace', M.GraceEffect(
                            fret=g['fret'], velocity=VELOCITY.get(previous['dynamic'], 95),
                            duration={16: 16, 32: 32}.get(grace_value, 64),
                            transition=M.GraceEffectTransition.bend if g['bend'] else M.GraceEffectTransition.slide
                            if g['slide'] else M.GraceEffectTransition.hammer if g['hammer'] else M.GraceEffectTransition.none,
                            isDead=g['muted'], isOnBeat=previous['grace'] == 'OnBeat'))
                beat.notes.append(_note(M, beat, e.v, value, string, velocity, gn['tie'], tag, loc))
                techniques.add(next((k for k in ('tapping', 'slapping', 'popping') if e.v.get(k)), None))
                fades = e.v.get('fade_in')
            if len(techniques) > 1:
                raise Refused(f'{tag} {loc}: tap/slap/pop differs between notes of one beat; native import stores it per beat')
            if beat.notes:
                beat.effect.fadeIn = fades
                beat.effect.slapEffect = M.SlapEffect({None: 0, 'tapping': 1, 'slapping': 2, 'popping': 3}[techniques.pop()])
                bars = {repr(n._bar) for n in beat.notes}
                if len(bars) > 1:
                    raise Refused(f'{tag} {loc}: whammy bar differs between notes of one beat after TuxGuitar 2.1.0\'s '
                                  'effect exclusions')
                bar_points = beat.notes[0]._bar
                if bar_points is not None:
                    beat.effect.tremoloBar = M.BendEffect(type=M.BendType.bend, value=0,
                                                          points=[M.BendPoint(p, 2 * q, False) for p, q in bar_points])
            else:
                beat.status = M.BeatStatus.rest
            voice.beats.append(beat)
            at += duration.time
            previous, graces, previous_beat = gb, None, beat
        if previous is not None and previous['grace'] is not None:
            loss(f'{where}, voice {v + 1}: a trailing grace beat has no following note and is dropped by TuxGuitar 2.1.0')
    for at, state in shared.items():
        # One TG beat holds stroke, pick stroke, text and chord for every voice; the last voice parsed wins.
        if state['stroke'] != 'none':  # TGStroke value 0: TG plays no strum offset
            loss(f'{where}: brush {state["stroke"]} has no speed in TuxGuitar 2.1.0 (it plays unstrummed); dropped')
        for i, beat in enumerate(state['beats']):
            beat.text = state['text'] if state['text'] and i == 0 else None
            if state['pick'] != 'none':
                beat.effect.pickStroke = M.BeatStrokeDirection[state['pick']]
            if state['chord'] is not None:
                c = state['chord']
                chord = M.Chord(len(c['frets']))
                chord.name, chord.firstFret = c['name'], c['base'] if c['base'] is not None else 0
                chord.strings = [f if f is not None else -1 for f in c['frets']]
                beat.effect.chord = chord
    if measure.number == 1:  # fixFirstMeasureStartPositions
        end = max((b.start + b.duration.time for v in measure.voices for b in v.beats), default=0)
        if end < measure.start + measure.length:
            for v in measure.voices:
                for b in v.beats:
                    b.start += measure.start + measure.length - end


def _note(M, beat, v, value, string, velocity, tie, tag, loc):
    if tie and v.get('dead'):
        raise Refused(f'{tag} {loc}: a tied dead note has no single native note type')
    note = M.Note(beat, value=value, string=string, velocity=velocity,
                  type=M.NoteType.tie if tie else M.NoteType.dead if v.get('dead') else M.NoteType.normal)
    e = note.effect
    e.vibrato, e.letRing, e.palmMute, e.staccato = bool(v.get('vibrato')), bool(v.get('let_ring')), bool(v.get('palm_mute')), bool(v.get('staccato'))
    e.hammer, e.ghostNote, e.accentuatedNote = bool(v.get('hammer')), bool(v.get('ghost')), bool(v.get('accent'))
    e.heavyAccentuatedNote = bool(v.get('heavy_accent'))
    if v.get('slide'):
        e.slides = [M.SlideType.shiftSlideTo]
    if v['trill'] is not None:
        e.trill = M.TrillEffect(fret=v['trill'][0], duration=M.Duration(v['trill'][1]))
    if v['tremolo_picking'] is not None:
        e.tremoloPicking = M.TremoloPickingEffect(duration=M.Duration(v['tremolo_picking']))
    if v['harmonic'] is not None:
        kind, data = v['harmonic']
        e.harmonic = {'natural': M.NaturalHarmonic, 'artificial': M.ArtificialHarmonic, 'pinch': M.PinchHarmonic}[kind]()
        e.harmonic.tg_data = data
    if v['bend'] is not None:
        e.bend = M.BendEffect(type=M.BendType.bend, value=0, points=[M.BendPoint(p, q, False) for p, q in v['bend']])
    if v['grace'] is not None:
        e.grace = v['grace']
    note._bar = v['tremolo_bar']
    return note
