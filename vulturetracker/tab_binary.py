"""Checked binary input and native-score normalization for PTB/TEF readers.

Format semantics follow TuxGuitar 2.1.0, commit
2c46e2a1cccdfdfa6e6f2692f241bd60bf418129 (LGPL-2.1-or-later).
No upstream runtime or external conversion process is required.
"""
from fractions import Fraction
import struct
import xml.etree.ElementTree as ET

from .tgimport import QUARTER, _add, read_tree


class Reader:
    def __init__(self, data, kind):
        if not isinstance(data, bytes) or len(data) > 16 * 1024 * 1024:
            raise ValueError(f'{kind}: expected at most 16 MiB of binary data')
        self.data, self.pos, self.kind = data, 0, kind

    def fail(self, message):
        raise ValueError(f'{self.kind} at byte {self.pos}: {message}')

    def take(self, count):
        if count < 0 or self.pos + count > len(self.data):
            self.fail(f'truncated field ({count} bytes required)')
        result = self.data[self.pos:self.pos + count]
        self.pos += count
        return result

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack('<H', self.take(2))[0]

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]

    def text(self, count):
        # Legacy Windows files use the ANSI codepage; newer writers use UTF-8.
        data = self.take(count).split(b'\0', 1)[0]
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return data.decode('cp1252', errors='replace')

    def short_text(self):
        return self.text(self.u16())

    def end(self):
        if self.pos != len(self.data):
            self.fail(f'unrecognized trailing data ({len(self.data) - self.pos} bytes)')


def written(value=4, dots=0, tuplet=(1, 1)):
    return dict(value=value, dots=dots, tuplet=list(tuplet))


def normalize(kind, metadata, headers, tracks, warnings):
    """Build the existing TG interchange tree, then use its exact native validator.

Headers contain meter/tempo; tracks contain measures of voices, with exact
quarter-note positions. This keeps ties, instrument allocation and publication
on the same path as existing native imports.
"""
    if not 1 <= len(headers) <= 254 or not tracks:
        raise ValueError(f'{kind}: requires tracks and 1..254 measures')
    root = ET.Element('TGSong')
    for field in ('name', 'artist', 'album', 'author', 'date', 'copyright', 'writer', 'transcriber', 'comments'):
        _add(root, field, metadata.get(field, ''))
    for index, track in enumerate(tracks):
        node = _add(root, 'TGChannel')
        for key, value in dict(id=index, bank=128 if track.get('drums') else 0,
                               program=track.get('program', 25), volume=track.get('volume', 127), balance=track.get('pan', 64),
                               chorus=0, reverb=0, phaser=0, tremolo=0, name=track['name']).items():
            _add(node, key, value)
    for header in headers:
        node = _add(root, 'TGMeasureHeader')
        _add(node, 'timeSignature', numerator=header['meter'][0], denominator=header['meter'][1])
        _add(node, 'tempo', header.get('tempo', 120))
        for key, tag in (('repeat_open', 'repeatOpen'), ('repeat_close', 'repeatClose'), ('line_break', 'lineBreak')):
            if header.get(key):
                _add(node, tag, header[key] if key == 'repeat_close' else None)
        if header.get('endings'):
            endings = _add(node, 'repeatAlternative')
            for ending in header['endings']:
                _add(endings, 'alternative', ending)
        if header.get('swing'):
            _add(node, 'tripletFeel', header['swing'])
        if header.get('marker'):
            _add(node, 'marker', header['marker'], R=0, G=0, B=0)
    for index, track in enumerate(tracks):
        node = _add(root, 'TGTrack', maxFret=36)
        _add(node, 'name', track['name'])
        _add(node, 'channelId', index)
        _add(node, 'offset', track.get('capo', 0))
        _add(node, 'color', R=40, G=90, B=180)
        for pitch in track['tuning']:
            _add(node, 'TGString', pitch)
        if track.get('lyrics'):
            _add(node, 'TGLyric', track['lyrics'], **{'from': 1})
        absolute = Fraction(0)
        for mi, header in enumerate(headers):
            measure = _add(node, 'TGMeasure')
            _add(measure, 'clef', track.get('clef', 'treble'))
            key = header.get('key', 0)
            _add(measure, 'keySignature', key if key >= 0 else 7 - key)
            groups = {}
            for beat in track['measures'][mi]:
                at = Fraction(beat['at'])
                group = groups.setdefault(at, {})
                voice = beat.get('voice', 0)
                if voice in group:
                    raise ValueError(f'{kind}: duplicate voice at measure {mi + 1}, {at}')
                group[voice] = beat
            if mi == 0:
                groups.setdefault(Fraction(0), {})
            for at, group in sorted(groups.items()):
                beat_node = _add(measure, 'TGBeat')
                precise = (absolute + at + 1) * QUARTER
                if precise.denominator != 1:
                    raise ValueError(f'{kind}: position cannot be represented exactly')
                _add(beat_node, 'preciseStart', int(precise))
                for voice in (0, 1):
                    beat = group.get(voice)
                    v = _add(beat_node, 'voice', empty='false' if beat else 'true')
                    w = beat['written'] if beat else written()
                    attrs = dict(value=w['value'])
                    if w['dots']:
                        attrs['dotted'] = ('dotted', 'doubleDotted')[w['dots'] - 1]
                    d = _add(v, 'duration', **attrs)
                    if w['tuplet'] != [1, 1]:
                        _add(d, 'divisionType', enters=w['tuplet'][0], times=w['tuplet'][1])
                    if not beat:
                        continue
                    if beat.get('text') and beat_node.find('text') is None:
                        _add(beat_node, 'text', beat['text'])
                    if beat.get('stroke') and beat_node.find('stroke') is None:
                        _add(beat_node, 'stroke', direction=beat['stroke'], value=16)
                    if beat.get('chord') and beat_node.find('chord') is None:
                        chord = beat['chord']
                        cn = _add(beat_node, 'chord')
                        _add(cn, 'name', chord['name'])
                        _add(cn, 'firstFret', chord.get('first_fret', 1))
                        for fret in chord['frets'][:len(track['tuning'])]:
                            _add(cn, 'string', fret if fret >= 0 else None)
                    for note in beat.get('notes', []):
                        n = _add(v, 'note', string=note['string'], value=note['fret'],
                                 velocity=note.get('velocity', 95), tiedNote='true' if note.get('tied') else 'false')
                        for effect, setting in note.get('effects', {}).items():
                            if isinstance(setting, list):
                                curve = _add(n, effect)
                                for position, value in setting:
                                    _add(curve, 'point', position=position, value=value)
                            elif isinstance(setting, dict):
                                _add(n, effect, **setting)
                            elif setting:
                                _add(n, effect)
            absolute += Fraction(header['meter'][0] * 4, header['meter'][1])
    song, notices = read_tree(root, [f'{kind} import: {message}' for message in dict.fromkeys(warnings)])
    notices[0] = f'{kind} notation imported with synthesized placeholders; original synthesizer sounds are not reproduced.'
    return song, notices
