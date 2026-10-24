"""Native TablEdit v2/v3 import, based on the pinned TuxGuitar 2.1.0 readers.

Preserves written measures, tracks, exact durations and supported techniques.
Unknown musical components refuse; unrepresented presentation fields produce
explicit notices. Uses no installed TablEdit, Java, or external converter.
"""
from fractions import Fraction
from pathlib import Path
import struct

from .tab_binary import Reader, normalize, written

PERCUSSION = ((49, 41, 32), (49, 51, 42, 50), (49, 42, 50, 37, 32),
              (49, 51, 42, 50, 45, 37), (49, 51, 42, 50, 45, 37, 41))


def duration(code):
    if code in (20, 23, 26, 29):
        return written(16)
    if code in (21, 24, 27, 30):
        return written(64)
    if code == 31:
        return written(1, 1)
    dots = 2 if code > 18 else 0
    code = code - 18 if dots else code
    value = 2 ** (code // 3)
    if code % 3 == 1:
        value *= 2
        dots = dots or 1
    return written(value, dots, (3, 2) if code % 3 == 2 else (1, 1))


def effects(first, second, warnings):
    fx = {}
    flags = {1: 'hammer', 2: 'hammer', 3: 'slide', 8: 'palmMute', 9: 'tapping',
             10: 'vibrato', 15: 'deadNote'}
    if first in flags:
        fx[flags[first]] = True
    elif first in (6, 7):
        fx['harmonic'] = dict(type='N.H' if first == 6 else 'A.H', data=0)
    elif first == 11:
        fx['tremoloPicking'] = dict(duration=16)
        warnings.append('Tremolo picking uses the TuxGuitar default sixteenth rate; TEF supplies no rate.')
    elif first in (12, 13):
        fx['bend'] = [(0, 0), (6, 2), (12, 2)] if first == 12 else [(0, 0), (3, 2), (6, 2), (9, 0), (12, 0)]
    elif first:
        raise ValueError(f'TEF: unsupported note technique {first} (choke/brush/roll)')
    low, high = second & 15, second >> 4
    flags2 = {1: 'letRing', 2: 'slapping', 4: 'ghostNote', 7: 'staccato', 8: 'fadeIn'}
    if low in flags2:
        fx[flags2[low]] = True
    elif low == 10:
        warnings.append('Hidden-notation note display is not retained.')
    elif low:
        raise ValueError(f'TEF: unsupported secondary technique {low} (rasgueado/tremolo-bar/fade-out)')
    flags3 = {1: 'hammer', 2: 'hammer', 8: 'letRing', 9: 'ghostNote', 10: 'deadNote'}
    if high in flags3:
        fx[flags3[high]] = True
    elif high in (6, 7):
        fx['harmonic'] = dict(type='N.H' if high == 6 else 'A.H', data=0)
    elif high:
        raise ValueError(f'TEF: unsupported tertiary technique {high}')
    return fx


def track(data, version, count, warnings):
    r = Reader(data, f'TEF{version} track')
    strings = r.u8()
    if not 1 <= strings <= 12:
        r.fail('requires 1..12 strings')
    r.take(5)
    kind = r.u8()
    r.take(1)
    program = r.u8()
    r.take(2)
    transposition = r.u8()
    capo = r.u8()
    r.take(1)
    middle, clef = r.u8(), r.u8()
    r.take(1)
    pan, volume, flags = r.u8(), r.u8(), r.u8()
    tuning = list(r.take(strings))
    r.take(12 - strings)
    name = r.text(len(data) - r.pos)
    drums = program == 96 if version == 3 else kind == 98
    if transposition:
        r.fail('transposing instruments are not yet representable')
    if flags & (1 | 4 | 8 | 16):
        r.fail('double strings, pedal-steel, multiple output channels or rhythm tracks are not yet representable')
    if middle not in (0, 12):
        warnings.append(f'{name}: printed middle-C offset {middle} is not retained.')
    if clef & ~7:
        warnings.append(f'{name}: grand-staff/bracket layout is not retained.')
    if clef & 7 in (3, 6, 7):
        warnings.append(f'{name}: unsupported printed clef {clef & 7} is displayed as treble; sounding pitches are unchanged.')
    if pan > 15 or volume > 15:
        r.fail('pan and attenuation must be in 0..15')
    # TEF stores high-to-low pitches as offsets below MIDI96.
    result = dict(name=name or f'Track {count + 1}', program=0 if drums else program,
                  volume=(15 - volume) * 127 // 15, pan=pan * 127 // 15,
                  drums=drums, tuning=[0 if drums else 96 - n for n in tuning],
                  capo=0 if drums else capo, clef={0: 'treble', 1: 'treble', 2: 'bass', 4: 'tenor', 5: 'alto'}.get(clef & 7, 'treble'),
                  measures=[], let_ring=bool(flags & 2))
    if drums and not 3 <= strings <= 7:
        r.fail('percussion mapping requires 3..7 strings')
    return result


def add_note(tracks, ti, mi, at, string, fret, code, dynamic, fx, voice=0, tied=False, stroke=None):
    t = tracks[ti]
    if not 0 <= string < len(t['tuning']):
        raise ValueError('TEF: component string outside track')
    if t['drums']:
        fret += PERCUSSION[min(len(t['tuning']) - 3, 4)][string]
    if t['let_ring']:
        fx['letRing'] = True
    w = duration(code)
    beats = t['measures'][mi]
    found = next((b for b in beats if b['at'] == at and b.get('voice', 0) == voice), None)
    if found is None:
        found = dict(at=at, voice=voice, written=w, notes=[])
        beats.append(found)
    elif found['written'] != w:
        raise ValueError(f'TEF: different note lengths within one voice at measure {mi + 1}')
    if any(n['string'] == string + 1 for n in found['notes']):
        raise ValueError('TEF: duplicate note on one string at the same time')
    note = dict(string=string + 1, fret=fret, velocity=127 - dynamic * 16, effects=fx, tied=tied)
    found['notes'].append(note)
    if stroke:
        found['stroke'] = stroke
    return found


def _find_track(tracks, string):
    for i, t in enumerate(tracks):
        if string < len(t['tuning']):
            return i, string
        string -= len(t['tuning'])
    raise ValueError('TEF: component string outside track collection')


def _ending(header, bits):
    number = bits & 7
    if bits & 64:
        header['repeat_open'] = True
    if bits & 128 and number >= 2:
        header['repeat_close'] = number - 1
    elif number:
        header['endings'] = [number]


def _attach(tracks, ti, mi, at, field, value):
    beats = tracks[ti]['measures'][mi]
    beat = next((b for b in beats if b['at'] == at), None)
    if beat is None:
        beat = dict(at=at, written=written(64), notes=[])
        beats.append(beat)
    if field in beat and beat[field] != value:
        raise ValueError(f'TEF: conflicting {field} at one position')
    beat[field] = value


def read_v2(data):
    r, notices = Reader(data, 'TEF2'), []
    info = r.take(200).split(b'\0')
    if len(info) < 3:
        r.fail('invalid three-field song metadata')
    metadata = dict(zip(('name', 'author', 'comments'), (Reader(v, 'TEF text').text(len(v)) for v in info[:3])))
    count = r.u16()
    numerator = r.u8()
    r.take(1)
    denominator = r.u8()
    if not 1 <= count <= 254 or not numerator or denominator not in (1, 2, 4, 8, 16, 32, 64):
        r.fail('invalid measure count or meter')
    r.take(15)
    tempo = r.u16()
    repeats = r.u8()
    r.take(5)
    texts = r.u8()
    r.take(5)
    percussion, rhythms, chords = r.u8(), r.u8(), r.u8()
    r.take(1)
    has_notes = r.u8()
    r.take(1)
    strings, track_count = r.u8(), r.u8() + 1
    if not 1 <= strings <= 64 or not 1 <= track_count <= 64:
        r.fail('invalid string or track count')
    r.take(14)
    components = [r.take(6) for _ in range(r.u16())]
    if repeats:
        r.fail('TEF2 playback reading lists are not yet representable; use explicit repeat/ending components')
    extra_text = []
    for _ in range(texts):
        length = r.u8()
        value = r.take(length)
        extra_text.append(Reader(value[1:], 'TEF text').text(max(0, length - 1)))
        r.take(1)
    if extra_text:
        metadata['comments'] += '\n' + '\n'.join(extra_text)
        notices.append('Unanchored text retained in song comments.')
    if percussion or rhythms:
        r.fail('automatic percussion/rhythm accompaniment patterns are not yet representable')
    chord_data = []
    for _ in range(chords):
        frets = [n if n < 128 else -1 for n in r.take(14)]
        chord_data.append(dict(frets=frets, name=r.text(16)))
        r.take(2)
    if has_notes:
        length = r.u16()
        if length < 1:
            r.fail('invalid note text size')
        r.take(1)
        metadata['comments'] += '\n' + r.text(length - 1)
    tracks = [track(r.take(50), 2, i, notices) for i in range(track_count)]
    r.end()
    if sum(len(t['tuning']) for t in tracks) != strings:
        r.fail('track string counts disagree with header')
    headers = [dict(meter=[numerator, denominator], tempo=tempo) for _ in range(count)]
    for t in tracks:
        t['measures'] = [[] for _ in headers]
    size = 256 * numerator // denominator
    overflow, previous_measure, shift = 0, 0, 0
    anchors = []
    for c in components:
        location = int.from_bytes(c[:2], 'little') + overflow
        if location // (size * strings) < previous_measure:
            overflow += 65536
            location += 65536
        mi, rest = divmod(location, size * strings)
        string, position = divmod(rest, size)
        if mi >= count:
            r.fail('component outside measure count')
        if mi != previous_measure:
            shift = 0
        position -= shift
        previous_measure = mi
        ti, string = _find_track(tracks, string)
        kind = c[2] & 31
        if 1 <= kind <= 25:
            code, dyn = c[3] & 31, c[3] >> 5
            at = Fraction(position, 64)
            if duration(code)['tuplet'] != [1, 1]:
                at = position // 64 + Fraction((position % 64) * 4, 192)
            extended = bool(c[2] & 32)
            if c[2] & 192:
                r.fail('TEF2 grace/pitch-shift flags are not yet representable')
            add_note(tracks, ti, mi, at, string, kind - 1 + (c[5] if extended else 0), code, dyn,
                     effects(c[4], 0 if extended else c[5], notices))
        elif kind == 27:
            shift = 4 * c[3]
            den = (2 ** (c[2] >> 5)) // 2
            num = ((size // 4 - c[3]) * den) // 64
            if den not in (1, 2, 4, 8, 16, 32, 64) or not num:
                r.fail('invalid changed meter')
            headers[mi]['meter'] = [num, den]
        elif c[2] == 254:
            if position:
                r.fail('mid-measure tempo change is not yet representable')
            for header in headers[mi:]:
                header['tempo'] = c[3] + 256 * c[4]
        elif c[2] == 94:
            _ending(headers[mi], c[4])
        elif kind == 28 and not c[2] & 32:
            if c[3] >= len(chord_data):
                r.fail('unknown chord index')
            anchors.append((ti, mi, Fraction(position, 64), 'chord', chord_data[c[3]]))
        elif kind in (28, 29):
            notices.append(f'Presentation component 0x{c[2]:02x} is not retained.')
        else:
            r.fail(f'unsupported musical component 0x{c[2]:02x}')
    for anchor in anchors:
        _attach(tracks, *anchor)
    return normalize('TablEdit 2', metadata, headers, tracks, notices)


def read_v3(data):
    r, notices = Reader(data, 'TEF3'), []
    h = r.take(256)
    if h[3] != 3 or any(h[16:24]) or h[56:60] != b'tbed' or h[202:206] != b'\x04\x00\x04\x0a':
        r.fail('unrecognized TablEdit 3 header')
    u16 = lambda at: int.from_bytes(h[at:at + 2], 'little')
    u32 = lambda at: int.from_bytes(h[at:at + 4], 'little')
    tempo = u16(6)
    if u16(12):
        r.fail('global syncopation is not yet representable')
    if u16(8) or u16(10):
        notices.append(f'Source chorus {u16(8)} and reverb {u16(10)} are not reproduced by placeholder instruments.')
    metadata = dict(name=r.short_text(), author=r.short_text(), comments=r.short_text())
    notes = r.short_text()
    if notes:
        metadata['comments'] += '\n' + notes
    if u32(132):
        metadata['comments'] += '\n' + r.short_text()
    if u32(140):
        metadata['copyright'] = r.short_text()
    lyrics = r.short_text()
    if lyrics:
        metadata['comments'] += '\nLyrics: ' + lyrics
        notices.append('TEF lyric formatting/anchors retained as literal song comments, not syllable placement.')
    texts = [r.short_text() for _ in range(r.u16())] if u32(84) else []
    chords = []
    if u32(88):
        size, count = r.u16(), r.u16()
        if size < 32:
            r.fail('chord structure is too short')
        for _ in range(count):
            c = r.take(size)
            chords.append(dict(frets=[(n & 31) if n >> 5 == 0 else -1 for n in c[:7]],
                               name=Reader(c[14:31], 'TEF chord').text(17), first_fret=c[31]))
            if any(n >> 5 for n in c[:7]):
                notices.append('Chord fingering symbols are represented as muted strings.')
    size, count = r.u16() - 4, r.u16()
    r.take(4)
    if size < 8 or not 1 <= count <= 254:
        r.fail('invalid measure structure/count')
    headers = []
    for _ in range(count):
        m = r.take(size)
        if m[0] & 30:
            r.fail('free-time, pickup or ad-lib measures are not yet representable')
        if m[0]:
            notices.append('Minor-key label and barline presentation flags are not retained.')
        key = m[2] if m[2] < 128 else m[2] - 256
        headers.append(dict(meter=[m[5], m[4]], tempo=tempo, key=key))
    size, count = r.u16(), r.u16()
    if size < 33 or not 1 <= count <= 64:
        r.fail('invalid track structure/count')
    tracks = [track(r.take(size), 3, i, notices) for i in range(count)]
    for t in tracks:
        t['measures'] = [[] for _ in headers]
    print_size = r.u8()
    r.take(1)
    r.take(print_size + 256)
    notices.append('Page headers, fonts, spacing and print layout are not imported; use native print settings.')
    if u32(128):
        r.fail('playback reading lists are not yet representable; explicit repeats remain supported')
    if len(data) - r.pos < 4 or (len(data) - r.pos - 4) % 12:
        r.fail('invalid component block length')
    total_strings = sum(len(t['tuning']) for t in tracks)
    anchors = []
    last_notes = {}
    while len(data) - r.pos > 4:
        c = r.take(12)
        location = int.from_bytes(c[:4], 'little')
        stride = 32 * total_strings
        for mi, header in enumerate(headers):
            num, den = header['meter']
            if not num or den not in (1, 2, 4, 8, 16, 32, 64):
                r.fail('invalid time signature')
            size = Fraction(num * 16, den) * stride
            if location < size:
                break
            location -= size
        else:
            r.fail('component outside measures')
        position, offset = divmod(location, stride)
        if offset % 8:
            r.fail('component has an unrepresentable sub-grid location')
        ti, string = _find_track(tracks, int(offset // 8))
        at = Fraction(position, 4)
        kind = c[4]
        if 1 <= kind & 31 <= 25 and kind not in (0x33, 0x35, 0x36, 0x37, 0x38, 0x39, 0x75, 0x78, 0xb6, 0xb7):
            if kind & 128:
                r.fail('pitch-shifted notes are not yet representable')
            fx = effects(c[6] & 15, c[8], notices)
            if kind & 64:
                transition = {0: 'none', 1: 'hammer', 2: 'slide', 3: 'bend'}.get(c[7] >> 5)
                if transition is None:
                    r.fail('compound grace ornament is not yet representable')
                fx['grace'] = dict(fret=c[7] & 31, duration=32, dynamic=127 - (c[5] >> 5) * 16,
                                   transition=transition, onBeat='false', dead='false')
            voice = 1 if c[6] & 48 == 48 else 0
            if c[6] & 192 or c[9] or c[10] & 31 or c[11] & ~32:
                notices.append('Note spelling/fingering/font/stem placement is not retained; pitches and written durations are retained.')
            stroke = {1: 'up', 2: 'down'}.get(c[10] >> 5)
            if c[10] >> 5 not in (0, 1, 2):
                r.fail('unsupported stroke type')
            beat = add_note(tracks, ti, mi, at, string, (kind & 31) - 1, c[5] & 31, c[5] >> 5, fx,
                            voice, bool(c[11] & 32) or c[5] >> 5 == 7, stroke)
            last_notes[ti, string] = beat['notes'][-1]
        elif kind == 0x7d and c[5]:
            # TEF3 metadata attaches to the preceding note on this track/string,
            # not necessarily the last note or the component's own timestamp.
            note = last_notes.get((ti, string))
            if note is None or 'grace' not in note['effects']:
                r.fail('grace metadata needs a preceding grace note on the same track/string')
            if c[5] not in (1, 2, 3):
                r.fail('grace longer than a sixteenth cannot be retained exactly')
            if c[6] or c[7] & 128 or c[8] & 128 or c[9] or c[11] & ~103:
                r.fail('cross-string or compound grace metadata is not yet representable')
            grace = note['effects']['grace']
            if c[5] in (2, 3):
                grace['duration'] = {2: 32, 3: 16}[c[5]]
            if c[8]:
                grace['fret'] = c[8]
            if c[10] or c[11] or c[7]:
                notices.append('Grace fingering, spacing, spelling and slash/slur/stem appearance are not retained.')
        elif kind == 0x33:
            tracks[ti]['measures'][mi].append(dict(at=at, voice=1 if c[6] & 48 == 48 else 0,
                                                  written=duration(c[5]), notes=[]))
        elif kind == 0xfe:
            if at or c[7] & 15:
                r.fail('mid-measure or gradual tempo changes are not yet representable')
            for header in headers[mi:]:
                header['tempo'] = int.from_bytes(c[5:7], 'little')
        elif kind == 0xb7:
            _ending(headers[mi], c[6])
        elif kind == 0x35:
            index = int.from_bytes(c[5:7], 'little')
            if index >= len(chords):
                r.fail('unknown chord index')
            anchors.append((ti, mi, at, 'chord', chords[index]))
        elif kind == 0x39:
            index = int.from_bytes(c[5:7], 'little')
            if index >= len(texts):
                r.fail('unknown text index')
            anchors.append((ti, mi, at, 'text', texts[index]))
        elif kind == 0x36:
            headers[mi]['line_break'] = True
        elif kind in (0x75, 0xbd, 0xbe) or kind == 0x7d and c[5] == 0:
            notices.append(f'Presentation component 0x{kind:02x} is not retained.')
        else:
            r.fail(f'unsupported musical component 0x{kind:02x} (program/drum/volume/syncopation/ornament/direction change)')
    if r.take(4) != b'\xff' * 4:
        r.fail('missing end marker')
    for anchor in anchors:
        _attach(tracks, *anchor)
    return normalize('TablEdit 3', metadata, headers, tracks, notices)


def read_tef(data):
    """Read bytes into (native song, explicit losses); malformed files never publish."""
    return read_v3(data) if len(data) >= 60 and (data[3] == 3 or data[56:60] == b'tbed') else read_v2(data)


def import_tef(src, song_path, samples_dir):
    from .gpimport import publish_native_score
    song, notices = read_tef(Path(src).read_bytes())
    return publish_native_score(song, src, song_path, samples_dir, notices)
