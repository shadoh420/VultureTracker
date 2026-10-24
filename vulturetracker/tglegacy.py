"""Legacy binary TuxGuitar .tg (file formats 1.0, 1.1, 1.2, 1.3 and 1.5), stdlib only.

Pinned reference: TuxGuitar 2.1.0, 2c46e2a1cccdfdfa6e6f2692f241bd60bf418129, TuxGuitar-compat
io/tg/v10..v15 (TGSongReaderImpl, TGStream) and, for beat placement, TGReadSongAction's
TGSongManager.updatePreciseStart. The stream becomes the same TuxGuitarFile 2.0 element tree
that tgimport validates, so one reader decides what the native score keeps.
"""
import copy
import xml.etree.ElementTree as ET
from fractions import Fraction

PREFIX = 'TuxGuitar File Format - '
VERSIONS = {'0.7': 7, '0.8': 8, '0.9': 9, '1.0': 10, '1.1': 11, '1.2': 12, '1.3': 13, '1.5': 15}
DEVEL = {'TG_DEVEL-0.01': '0.7', 'TG_DEVEL-0.8': '0.8'}   # the 0.7/0.8 readers' header strings
WHOLE = 11531520                      # TGDuration.WHOLE_PRECISE_DURATION
PER_TICK = WHOLE // (4 * 960)         # precise units per 960-per-quarter tick
CLEFS = {1: 'treble', 2: 'bass', 3: 'tenor', 4: 'alto'}
FEELS = {1: 'none', 2: 'eighth', 3: 'sixteenth'}
STROKES = {0: 'none', 1: 'up', -1: 'down'}
HARMONICS = {1: 'N.H', 2: 'A.H', 3: 'T.H', 4: 'P.H', 5: 'S.H'}
GRACE_DURATIONS = {1: 64, 2: 32, 3: 16}
TRANSITIONS = {0: 'none', 1: 'slide', 2: 'bend', 3: 'hammer'}
# TGStream effect bits (identical values in v10..v15; let ring is absent before 1.2).
EFFECT_FLAGS = ((0x40, 'vibrato'), (0x80, 'deadNote'), (0x100, 'slide'), (0x200, 'hammer'),
                (0x400, 'ghostNote'), (0x800, 'accentuatedNote'), (0x1000, 'heavyAccentuatedNote'),
                (0x2000, 'palmMute'), (0x4000, 'staccato'), (0x8000, 'tapping'), (0x10000, 'slapping'),
                (0x20000, 'popping'), (0x40000, 'fadeIn'), (0x80000, 'letRing'))


def _fail(where, reason):
    raise ValueError(f'TG legacy {where}: {reason}')


def version(data):
    """Return the legacy format version string ('1.5') when data starts with a legacy header, else None."""
    if not isinstance(data, bytes) or not data:
        return None
    n = data[0]
    try:
        text = data[1:1 + 2 * n].decode('utf-16-be')
    except UnicodeDecodeError:
        return None
    if len(text) != n:
        return None
    return DEVEL.get(text) or (text[len(PREFIX):] if text.startswith(PREFIX) else None)


class _Stream:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            _fail('stream', f'truncated at byte {self.pos}')
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u8(self):
        return self.take(1)[0]

    def s8(self):
        v = self.u8()
        return v - 256 if v > 127 else v

    def s16(self):
        return int.from_bytes(self.take(2), 'big', signed=True)

    def chars(self, n):
        try:
            return self.take(2 * n).decode('utf-16-be')
        except UnicodeDecodeError:
            _fail('string', f'invalid UTF-16 text before byte {self.pos}')

    def short_string(self):
        return self.chars(self.u8())

    def long_string(self):
        n = int.from_bytes(self.take(4), 'big', signed=True)
        if n < 0:
            _fail('string', 'negative length')
        return self.chars(n)


def _add(parent, tag, text=None, **attrs):
    node = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        node.text = str(text)
    return node


def _duration(s, where):
    """TGSongReaderImpl.readDuration (1.0-1.5); returns (written attrs, tuplet, ticks, precise units)."""
    header, value = s.u8(), s.s8()
    tuplet = (s.s8(), s.s8()) if header & 4 else (1, 1)
    return _make_duration(value, bool(header & 1), bool(header & 2), tuplet, where)


def _write_duration(parent, duration):
    attrs, (enters, times) = duration[:2]
    node = _add(parent, 'duration', **attrs)
    _add(node, 'divisionType', enters=enters, times=times)


def _color(s, node):
    for key in ('R', 'G', 'B'):
        node.set(key, str(s.u8()))


def _effects(s, note, ver, where):
    header = (s.u8() << 16) | (s.u8() << 8) | s.u8()
    if header & 0x01:
        bend = _add(note, 'bend')
        for _ in range(s.s8()):
            _add(bend, 'point', position=s.s8(), value=s.s8())
    if header & 0x02:
        bar = _add(note, 'tremoloBar')
        for _ in range(s.s8()):
            _add(bar, 'point', position=s.s8(), value=s.s8() - 12)
    if header & 0x04:
        kind = s.s8()
        if kind not in HARMONICS:
            _fail(where, f'unknown harmonic type {kind}')
        _add(note, 'harmonic', type=HARMONICS[kind], data=0 if kind == 1 else s.s8())
    if header & 0x08:
        flags, fret, duration, dynamic, transition = s.u8(), s.s8(), s.s8(), s.s8(), s.s8()
        if duration not in GRACE_DURATIONS or transition not in TRANSITIONS:
            _fail(where, f'unknown grace duration {duration} or transition {transition}')
        _add(note, 'grace', fret=fret, duration=GRACE_DURATIONS[duration], dynamic=dynamic,
             transition=TRANSITIONS[transition], onBeat=str(bool(flags & 2)).lower(), dead=str(bool(flags & 1)).lower())
    if header & 0x10:
        _add(note, 'trill', fret=s.s8(), duration=s.s8())
    if header & 0x20:
        _add(note, 'tremoloPicking', duration=s.s8())
    for bit, tag in EFFECT_FLAGS:
        if header & bit and (tag != 'letRing' or ver >= 12):
            _add(note, tag)


def _notes(s, voice, velocity, ver, where):
    """Read a note list; velocity is the measure's per-voice running value [current]."""
    more = True
    while more:
        header = s.u8()
        more = bool(header & 1)
        fret, string = s.s8(), s.s8()
        if header & 8:
            velocity[0] = s.s8()
        note = _add(voice, 'note', string=string, value=fret, velocity=velocity[0])
        if header & 2:
            note.set('tiedNote', 'true')
        if header & 4:
            _effects(s, note, ver, where)


def _beat_extras(s, header, beat, ver, where):
    stroke_bit, chord_bit, text_bit = (0, 0x08, 0x10) if ver == 10 else (0x02, 0x04, 0x08)
    if header & stroke_bit:
        direction, value = s.s8(), s.s8()
        if direction not in STROKES:
            _fail(where, f'unknown stroke direction {direction}')
        beat['stroke'] = (STROKES[direction], value)
    if header & chord_bit:
        count = s.s8()
        if count < 0:
            _fail(where, 'negative chord string count')
        name, first = s.short_string(), s.s8()
        beat['chord'] = (name, first, [s.s8() for _ in range(count)])
    if header & text_bit:
        beat['text'] = s.short_string()


def _measure_beats(s, ver, start, where):
    """Read one measure's beats as TGBeatData does; returns beats with tick starts and voices."""
    voices = [dict(start=start, flags=0, duration=(dict(value=4), (1, 1), 960, WHOLE // 4), velocity=[95])
              for _ in range(2)]
    current, beats, more = start, [], True
    while more:
        header = s.u8()
        more = bool(header & 1)
        bloc = f'{where}, beat {len(beats) + 1}'
        beat = dict(voices=[None, None])
        if ver == 10:
            v = voices[0]
            beat['start'] = v['start']
            if header & 0x02:
                v['duration'] = _duration(s, bloc)
            notes = ET.Element('voice')
            if header & 0x04:
                _notes(s, notes, v['velocity'], ver, bloc)
            beat['voices'][0] = (v['duration'], notes, None)
            v['start'] += v['duration'][2]
        else:
            later = [v['start'] for v in voices if v['start'] > current]
            if later and min(later) > current:
                current = min(later)
            beat['start'] = current
            for i, v in enumerate(voices):
                if not header & (0x10 << 2 * i):
                    continue
                if header & (0x20 << 2 * i):
                    v['flags'] = s.u8()
                if v['flags'] & 0x02:
                    v['duration'] = _duration(s, bloc)
                notes = ET.Element('voice')
                if v['flags'] & 0x01:
                    _notes(s, notes, v['velocity'], ver, f'{bloc}, voice {i + 1}')
                direction = 'up' if v['flags'] & 0x04 else 'down' if v['flags'] & 0x08 else None
                beat['voices'][i] = (v['duration'], notes, direction)
                v['start'] += v['duration'][2]
        _beat_extras(s, header, beat, ver, bloc)
        beats.append(beat)
    return beats


def _place(beats, measure_start):
    """TGMeasureManager.updateBeatsPreciseStart: precise starts from voice ends; empty beats dropped."""
    beats = sorted(beats, key=lambda b: b['start'])
    placed, ends = [], [0, 0]
    for i, beat in enumerate(beats):
        used = [k for k, v in enumerate(beat['voices']) if v is not None]
        if i == 0:
            at = measure_start
            for k in used:
                ends[k] = at + beat['voices'][k][0][3]
            low = min((ends[k] for k in used), default=0)
            ends = [max(e, low) for e in ends]
        else:
            at = max((ends[k] for k in used), default=0)
            if at == 0:  # TG removes a beat it cannot place
                continue
            for k in used:
                ends[k] = at + beat['voices'][k][0][3]
        placed.append((at, beat))
    return placed


def tg_starts(song):
    """Apply TGReadSongAction's updatePreciseStart to a TuxGuitar 2.0 TGSong element, in place.

    TuxGuitar runs it on every song it opens, 2.0 files included: a beat is placed at the latest end of
    its own voices, so a hole before it in all of them closes up, and a measure's first beat moves to
    the measure start; when that first beat has no voices TuxGuitar deletes the measure's later beats.
    Returns [(track, measure, beat, old, new, length)] in quarters from the measure start, new None
    for a deleted beat (left in place). Malformed elements are skipped; the 2.0 validator reports them.
    """
    moves, start, meter = [], 960 * PER_TICK, (4, 4)
    starts = []
    for h in song.findall('TGMeasureHeader'):
        ts = h.find('timeSignature')
        try:
            if ts is not None:
                meter = (int(ts.get('numerator')), int(ts.get('denominator')))
            starts.append((start, Fraction(meter[0] * 4, meter[1])))
            start += meter[0] * WHOLE // meter[1]
        except (TypeError, ValueError, ZeroDivisionError):
            return moves
    for ti, track in enumerate(song.findall('TGTrack')):
        for mi, (measure, (mstart, length)) in enumerate(zip(track.findall('TGMeasure'), starts)):
            beats = []
            try:
                for b in measure.findall('TGBeat'):
                    voices = []
                    for v in b.findall('voice')[:2]:
                        if v.get('empty', 'false' if v.find('note') is not None else 'true') == 'true':
                            voices.append(None)
                            continue
                        d = v.find('duration')
                        division = d.find('divisionType')
                        tuplet = (int(division.get('enters')), int(division.get('times'))) if division is not None else (1, 1)
                        voices.append((_make_duration(int(d.get('value')), d.get('dotted') == 'dotted',
                                                      d.get('dotted') == 'doubleDotted', tuplet, 'beat'), None, None))
                    beats.append(dict(start=int(b.findtext('preciseStart')) // PER_TICK, node=b, voices=voices))
            except (TypeError, ValueError, AttributeError):
                continue
            placed = {id(beat['node']): at for at, beat in _place(beats, mstart)}
            for bi, beat in enumerate(sorted(beats, key=lambda b: b['start'])):
                node = beat['node'].find('preciseStart')
                at = placed.get(id(beat['node']))
                if any(beat['voices']) and int(node.text) != at:
                    moves.append((ti + 1, mi + 1, bi + 1, Fraction(int(node.text) - mstart, WHOLE // 4),
                                  None if at is None else Fraction(at - mstart, WHOLE // 4), length))
                    if at is not None:
                        node.text = str(at)
    return moves


def to_xml(data):
    """Parse a legacy .tg into a TGSong element plus legacy-specific notices."""
    label = version(data)
    if label is None:
        _fail('header', 'not a legacy TuxGuitar file')
    if label not in VERSIONS:
        _fail('header', f'unsupported TuxGuitar File Format {label} (supported: {", ".join(VERSIONS)})')
    ver, s, notices = VERSIONS[label], _OldStream(data), []
    s.short_string()
    if ver < 10:
        return _to_xml_old(s, ver, label, data)
    song = ET.Element('TGSong')
    credits = ('name', 'artist', 'album', 'author', 'date', 'copyright', 'writer', 'transcriber')
    for i, key in enumerate(credits):
        _add(song, key, s.short_string() if ver >= 12 or i < 4 else '')
    _add(song, 'comments', s.long_string() if ver >= 12 else '')
    channels = []
    if ver >= 13:
        for _ in range(s.s8()):
            node = ET.Element('TGChannel')
            _add(node, 'id', s.s16())
            for key in ('bank', 'program', 'volume', 'balance', 'chorus', 'reverb', 'phaser', 'tremolo'):
                _add(node, key, s.u8())
            _add(node, 'name', s.short_string())
            for _ in range(s.s16()):
                key = s.short_string()
                _add(node, 'TGChannelParameter', key=key, value=s.long_string())
            channels.append(node)
    headers, start, meter = [], 960, None
    for i in range(s.s16()):
        where = f'measure header {i + 1}'
        flags = s.u8()
        header = ET.Element('TGMeasureHeader')
        if flags & 0x01:
            numerator = s.s8()
            attrs, division, _, _ = _duration(s, where + ' time signature')
            if 'dotted' in attrs or division != (1, 1):
                _fail(where, 'dotted/tuplet time-signature denominators are unsupported')
            meter = (numerator, attrs['value'])
        if meter is None:
            _fail(where, 'first header has no time signature')
        _add(header, 'timeSignature', numerator=meter[0], denominator=meter[1])
        if flags & 0x02:
            _add(header, 'tempo', s.s16())
        elif not headers:
            _add(header, 'tempo', 120)
        if flags & 0x04:
            _add(header, 'repeatOpen')
        if flags & 0x08:
            _add(header, 'repeatClose', s.s16())
        if flags & 0x10:
            mask = s.s8()
            if mask < 0:
                _fail(where, 'ending 8 cannot be preserved: the TG 2.0 writer loops on a negative ending mask')
            alternatives = _add(header, 'repeatAlternative')
            for bit in range(7):
                if mask & (1 << bit):
                    _add(alternatives, 'alternative', bit + 1)
        if flags & 0x20:
            _color(s, _add(header, 'marker', s.short_string()))
        if flags & 0x40:
            feel = s.s8()
            if feel not in FEELS:
                _fail(where, f'unknown triplet feel {feel}')
            feel = FEELS[feel]
        else:
            feel = headers[-1][1] if headers else 'none'
        if feel != 'none':
            _add(header, 'tripletFeel', feel)
        song.append(header)
        if meter[0] < 1:
            _fail(where, 'time signature numerator must be positive')
        length = meter[0] * (3840 // meter[1])
        headers.append((start, feel))
        start += length
    routes, tracks = {}, []
    for ti in range(s.s8()):
        loc = f'track {ti + 1}'
        flags = s.u8()
        track = ET.Element('TGTrack')
        _add(track, 'name', s.short_string())
        solo = mute = False
        if ver >= 13:
            channel_id = s.s16()
        else:
            if ver == 10:
                state = s.u8()
                solo, mute = bool(state & 1), bool(state & 2)
            one, two = s.u8(), s.u8()
            values = [s.s8() for _ in range(7)]
            if one not in routes:
                node = ET.Element('TGChannel')
                _add(node, 'id', len(routes) + 1)
                _add(node, 'bank', 128 if one == 9 else 0)
                for key, value in zip(('program', 'volume', 'balance', 'chorus', 'reverb', 'phaser', 'tremolo'), values):
                    _add(node, key, value)
                _add(node, 'name', '')
                _add(node, 'TGChannelParameter', key='gm-channel-1', value=one)
                _add(node, 'TGChannelParameter', key='gm-channel-2', value=two)
                routes[one] = len(routes) + 1
                channels.append(node)
            channel_id = routes[one]
        if ver >= 11:
            solo, mute = bool(flags & 1), bool(flags & 2)
        if mute or solo:
            _add(track, 'soloMute', 'mute' if mute else 'solo')
        _add(track, 'channelId', channel_id)
        measures, clef, key = [], 1, 0
        for mi, (mstart, _) in enumerate(headers):
            mloc = f'{loc}, measure {mi + 1}'
            mflags = s.u8()
            beats = _measure_beats(s, ver, mstart, mloc)
            if mflags & 0x01:
                clef = s.s8()
            if mflags & 0x02:
                key = s.s8()
            if clef not in CLEFS:
                _fail(mloc, f'unknown clef {clef}')
            measures.append((CLEFS[clef], key, _place(beats, mstart * PER_TICK)))
        tuning = [s.s8() for _ in range(s.s8())]
        offset = s.s8() - 24
        if offset:
            _add(track, 'offset', offset)
        _color(s, _add(track, 'color'))
        for pitch in tuning:
            _add(track, 'TGString', pitch)
        lyric = _add(track, 'TGLyric', **{'from': 1})
        lyric_bit = 0x01 if ver == 10 else 0x04
        if flags & lyric_bit:
            lyric.set('from', str(s.s16()))
            lyric.text = s.long_string()
        _emit_measures(track, measures)
        tracks.append(track)
    return _finish(s, data, label, song, channels, tracks, notices)


def _finish(s, data, label, song, channels, tracks, notices):
    if s.pos != len(data):
        _fail('stream', f'{len(data) - s.pos} unexpected trailing bytes')
    # The 2.0 element order: credits, channels, headers, tracks.
    ordered = ET.Element('TGSong')
    ordered.extend([n for n in song if n.tag != 'TGMeasureHeader'] + channels +
                   [n for n in song if n.tag == 'TGMeasureHeader'] + tracks)
    if VERSIONS[label] < 13:
        notices.append(f'TuxGuitar File Format {label}: per-track channel data was read into song channels '
                       'the way TuxGuitar 2.1.0 does (tracks with one GM channel share it).')
    return ordered, notices


def _route(routes, channels, one, two, values):
    """Per-track channel of formats before 1.3: TG reuses the song channel with the same GM channel 1."""
    if one not in routes:
        node = ET.Element('TGChannel')
        _add(node, 'id', len(routes) + 1)
        _add(node, 'bank', 128 if one == 9 else 0)
        for key, value in zip(('program', 'volume', 'balance', 'chorus', 'reverb', 'phaser', 'tremolo'), values):
            _add(node, key, value)
        _add(node, 'name', '')
        _add(node, 'TGChannelParameter', key='gm-channel-1', value=one)
        _add(node, 'TGChannelParameter', key='gm-channel-2', value=two)
        routes[one] = len(routes) + 1
        channels.append(node)
    return routes[one]


def _emit_measures(track, measures):
    for clef_name, key_value, placed in measures:
        measure = _add(track, 'TGMeasure')
        _add(measure, 'clef', clef_name)
        _add(measure, 'keySignature', key_value)
        for at, beat in placed:
            node = _add(measure, 'TGBeat')
            _add(node, 'preciseStart', at)
            if 'text' in beat:
                _add(node, 'text', beat['text'])
            if 'stroke' in beat and beat['stroke'] != ('none', 0):
                _add(node, 'stroke', direction=beat['stroke'][0], value=beat['stroke'][1])
            if 'chord' in beat:
                name, first, frets = beat['chord']
                chord = _add(node, 'chord')
                _add(chord, 'name', name)
                _add(chord, 'firstFret', first)
                for fret in frets:
                    _add(chord, 'string', None if fret == -1 else fret)
            for entry in beat['voices']:
                if entry is None:
                    voice = _add(node, 'voice', empty='true')
                    _add(voice, 'duration', value=4)
                    continue
                duration, notes, direction = entry
                voice = _add(node, 'voice')
                if direction:
                    voice.set('direction', direction)
                _write_duration(voice, duration)
                if len(notes):
                    voice.extend(list(notes))
                else:
                    voice.set('empty', 'false')


class _OldStream(_Stream):
    """0.7-0.9 readers: DataInputStream.read() is unsigned; 0.7 adds int/long/boolean fields."""
    def s32(self):
        return int.from_bytes(self.take(4), 'big', signed=True)

    def s64(self):
        return int.from_bytes(self.take(8), 'big', signed=True)

    def flag(self):
        return self.u8() != 0


def _make_duration(value, dotted, double, tuplet, where):
    if dotted and double:
        _fail(where, 'duration carries both dotted and double-dotted flags')
    enters, times = tuplet
    if value not in (1, 2, 4, 8, 16, 32, 64) or enters < 1 or times < 1:
        _fail(where, f'unsupported duration {value} {enters}:{times}')
    ticks, precise = 3840 // value, WHOLE // value
    if dotted:
        ticks, precise = ticks + ticks // 2, precise * 3 // 2
    elif double:
        ticks, precise = ticks + (ticks // 4) * 3, precise * 7 // 4
    attrs = dict(value=value)
    if dotted or double:
        attrs['dotted'] = 'dotted' if dotted else 'doubleDotted'
    return attrs, (enters, times), ticks * times // enters, precise * times // enters


def _old_duration(s, ver, where, tuplet=(1, 1)):
    """readDuration of 0.7 (ints/booleans, division always) and 0.8/0.9 (flags; division kept unless flagged)."""
    if ver == 7:
        value, dotted, double = s.s32(), s.flag(), s.flag()
        return _make_duration(value, dotted, double, (s.s32(), s.s32()), where)
    header, value = s.u8(), s.u8()
    if header & 4:
        tuplet = (s.u8(), s.u8())
    return _make_duration(value, bool(header & 1), bool(header & 2), tuplet, where)


def _old_effects(s, note, ver, where):
    def bend(count, read, halve):
        node = _add(note, 'bend')
        for _ in range(count):
            position, value = read(), read()
            _add(node, 'point', position=position, value=value // 2 if halve and value > 0 else value)
    if ver == 7:
        vibrato = s.flag()
        if s.flag():
            bend(s.s32(), s.s32, True)
        flags = [vibrato, s.flag(), s.flag(), s.flag()]
        for tag, on in zip(('vibrato', 'deadNote', 'slide', 'hammer'), flags):
            if on:
                _add(note, tag)
        return
    if ver == 8:
        header = s.u8()
        if header & 0x02:
            bend(s.u8(), s.u8, True)
        for bit, tag in ((0x01, 'vibrato'), (0x04, 'deadNote'), (0x08, 'slide'), (0x10, 'hammer')):
            if header & bit:
                _add(note, tag)
        return
    header = (s.u8() << 16) | (s.u8() << 8) | s.u8()
    if header & 0x01:
        bend(s.u8(), s.u8, False)
    if header & 0x02:
        bar = _add(note, 'tremoloBar')
        for _ in range(s.u8()):
            _add(bar, 'point', position=s.u8(), value=s.u8() - 12)
    if header & 0x04:
        kind = s.u8()
        if kind not in HARMONICS:
            _fail(where, f'unknown harmonic type {kind}')
        data = s.u8() - 24 if kind == 2 else s.u8() if kind == 3 else 0
        _add(note, 'harmonic', type=HARMONICS[kind], data=data)
    if header & 0x08:
        flags, fret, duration, dynamic, transition = s.u8(), s.u8(), s.u8(), s.u8(), s.u8()
        if duration not in GRACE_DURATIONS or transition not in TRANSITIONS:
            _fail(where, f'unknown grace duration {duration} or transition {transition}')
        _add(note, 'grace', fret=fret, duration=GRACE_DURATIONS[duration], dynamic=dynamic,
             transition=TRANSITIONS[transition], onBeat=str(bool(flags & 2)).lower(), dead=str(bool(flags & 1)).lower())
    if header & 0x10:
        _add(note, 'trill', fret=s.u8(), duration=s.u8())
    if header & 0x20:
        _add(note, 'tremoloPicking', duration=s.u8())
    for bit, tag in EFFECT_FLAGS:
        if header & bit and tag != 'letRing':
            _add(note, tag)


def _old_measure_beats(s, ver, where):
    """0.8/0.9 components: one voice; a component without NEXT_BEAT adds to the current beat."""
    beats, velocity = [], 95
    for ci in range(s.s16()):
        cwhere = f'{where}, component {ci + 1}'
        header = s.u8()
        new = not beats or header & 0x10
        if new:
            previous = beats[-1]['voices'][0][0] if beats else None
            beats.append(dict(start=len(beats), voices=[[previous or _make_duration(4, False, False, (1, 1), cwhere),
                                                          ET.Element('voice'), None], None]))
        voice = beats[-1]['voices'][0]
        if header & 0x20:
            voice[0] = _old_duration(s, ver, cwhere, voice[0][1] if not new else (1, 1))
        if header & 0x01:
            if ver == 8:
                fret, velocity, string = s.u8(), s.u8(), s.u8()
            else:
                fret, string = s.u8(), s.u8()
                if header & 0x40:
                    velocity = s.u8()
            note = _add(voice[1], 'note', string=string, value=fret, velocity=velocity)
            if header & 0x04:
                note.set('tiedNote', 'true')
            if header & 0x08:
                _old_effects(s, note, ver, cwhere)
    for b in beats:
        b['voices'][0] = tuple(b['voices'][0])
    return beats


def _to_xml_old(s, ver, label, data):
    notices = []
    song = ET.Element('TGSong')
    for key in ('name', 'artist', 'album', 'author'):
        _add(song, key, s.short_string())
    for key in ('date', 'copyright', 'writer', 'transcriber', 'comments'):
        _add(song, key, '')
    channels, routes, tracks, headers, lengths = [], {}, [], [], []
    if ver >= 8:
        start, meter, tempo, feel = 960, None, 120, 'none'
        for i in range(s.s16()):
            where = f'measure header {i + 1}'
            flags, header = s.u8(), ET.Element('TGMeasureHeader')
            if flags & 0x01:
                numerator = s.u8()
                attrs, division, _, _ = _old_duration(s, ver, where + ' time signature')
                if 'dotted' in attrs or division != (1, 1):
                    _fail(where, 'dotted/tuplet time-signature denominators are unsupported')
                meter = (numerator, attrs['value'])
            if meter is None or meter[0] < 1:
                _fail(where, 'missing or empty time signature')
            _add(header, 'timeSignature', numerator=meter[0], denominator=meter[1])
            if flags & 0x02:
                tempo = s.s16()
            _add(header, 'tempo', tempo)
            if flags & 0x04:
                _add(header, 'repeatOpen')
            if flags & 0x08:
                _add(header, 'repeatClose', s.s16())
            if flags & 0x10:
                marker = _add(header, 'marker', s.short_string())
                for key in ('R', 'G', 'B'):
                    marker.set(key, str(s.s16()))
            if flags & 0x20:
                feel = FEELS.get(s.u8())
                if feel is None:
                    _fail(where, 'unknown triplet feel')
            if feel != 'none':
                _add(header, 'tripletFeel', feel)
            song.append(header)
            headers.append(start)
            start += meter[0] * (3840 // meter[1])
    count = s.s32() if ver == 7 else s.u8()
    for ti in range(count):
        loc = f'track {ti + 1}'
        track = ET.Element('TGTrack')
        if ver == 7:
            s.s64()                                   # track number: TG renumbers on add
        flags = s.u8() if ver == 9 else 0
        _add(track, 'name', s.short_string())
        if ver == 7:
            one, two, *values = (s.s16() for _ in range(9))
            solo, mute = None, None
        else:
            state = s.u8()
            solo, mute = bool(state & 1), bool(state & 2)
            one, two, *values = (s.u8() for _ in range(9))
        channel_id = _route(routes, channels, one, two, values)
        if ver == 7:
            solo, mute = s.flag(), s.flag()
        if mute or solo:
            _add(track, 'soloMute', 'mute' if mute else 'solo')
        _add(track, 'channelId', channel_id)
        measures, clef, key = [], 1, 0
        if ver == 7:
            n = s.s32()
            fresh = not headers
            for mi in range(n):
                mloc = f'{loc}, measure {mi + 1}'
                s.s32()                               # header number: TG renumbers
                mstart = 960 * s.s64() // 1000
                beats = []
                for kind in ('note', 'rest'):
                    previous = None
                    for _ in range(s.s32()):
                        if kind == 'note':
                            fret = s.s32()
                        at = 960 * s.s64() // 1000
                        if previous is None or previous['start'] != at:
                            previous = dict(start=at, voices=[None, None])
                            beats.append(previous)
                        voice = previous['voices'][0]
                        notes = voice[1] if voice else ET.Element('voice')
                        duration = _old_duration(s, ver, mloc)
                        previous['voices'][0] = (duration, notes, None)
                        if kind == 'note':
                            velocity, string, tied = s.s32(), s.s32(), s.flag()
                            note = _add(notes, 'note', string=string, value=fret, velocity=velocity)
                            if tied:
                                note.set('tiedNote', 'true')
                            _old_effects(s, note, ver, mloc)
                numerator = s.s32()
                attrs, division, _, _ = _old_duration(s, ver, mloc + ' time signature')
                tempo, clef, key, opened, close = s.s32(), s.s32(), s.s32(), s.flag(), s.s32()
                if 'dotted' in attrs or division != (1, 1) or numerator < 1:
                    _fail(mloc, 'unsupported time signature')
                header = ET.Element('TGMeasureHeader')
                _add(header, 'timeSignature', numerator=numerator, denominator=attrs['value'])
                _add(header, 'tempo', tempo)
                if opened:
                    _add(header, 'repeatOpen')
                if close:
                    _add(header, 'repeatClose', close)
                if fresh:
                    expected = headers[-1] + lengths[-1] if headers else 960
                    if mstart != expected:
                        _fail(mloc, f'measure start {mstart} does not follow the previous measure ({expected})')
                    song.append(header)
                    headers.append(mstart)
                    lengths.append(numerator * (3840 // attrs['value']))
                elif mi >= len(headers) or mstart != headers[mi] or ET.tostring(header) != ET.tostring(
                        song.findall('TGMeasureHeader')[mi]):
                    _fail(mloc, 'tracks disagree on measure headers; TuxGuitar 0.7 would keep the last track\'s')
                if clef not in CLEFS:
                    _fail(mloc, f'unknown clef {clef}')
                measures.append((CLEFS[clef], key, _place(beats, mstart * PER_TICK)))
            if n != len(headers):
                _fail(loc, 'measure count differs between tracks')
            tuning = []
            for si in range(s.s32()):
                number, value = s.s32(), s.s32()
                if number != si + 1:
                    _fail(loc, f'string numbers must be 1..n in order (found {number})')
                tuning.append(value)
            offset, color = 0, [s.s32() for _ in range(3)]
            lyric = None
        else:
            for mi, mstart in enumerate(headers):
                mloc = f'{loc}, measure {mi + 1}'
                mflags = s.u8()
                beats = _old_measure_beats(s, ver, mloc)
                if mflags & 0x01:
                    clef = s.u8()
                if mflags & 0x02:
                    key = s.u8()
                if clef not in CLEFS:
                    _fail(mloc, f'unknown clef {clef}')
                measures.append((CLEFS[clef], key, _place(beats, mstart * PER_TICK)))
            tuning = [s.u8() for _ in range(s.u8())]
            offset = s.u8() - 24
            color = [s.s16() for _ in range(3)]
            lyric = (s.s16(), s.short_string()) if flags & 0x01 else None
        if offset:
            _add(track, 'offset', offset)
        _add(track, 'color', R=color[0], G=color[1], B=color[2])
        for pitch in tuning:
            _add(track, 'TGString', pitch)
        _add(track, 'TGLyric', lyric[1] if lyric else None, **{'from': lyric[0] if lyric else 1})
        _emit_measures(track, measures)
        tracks.append(track)
    return _finish(s, data, label, song, channels, tracks, notices)


WRITABLE = ('1.0', '1.1', '1.2', '1.3', '1.5')   # TuxGuitar 2.1.0 has compat writers for these only
CLEF_CODES = {v: k for k, v in CLEFS.items()}
FEEL_CODES = {v: k for k, v in FEELS.items()}
STROKE_CODES = {v: k for k, v in STROKES.items()}
HARMONIC_CODES = {v: k for k, v in HARMONICS.items()}
GRACE_CODES = {v: k for k, v in GRACE_DURATIONS.items()}
TRANSITION_CODES = {v: k for k, v in TRANSITIONS.items()}


class _Out(bytearray):
    def int(self, value, lo, hi, size, where):
        value = int(value)
        if not lo <= value <= hi:
            _fail(where, f'value {value} is outside {lo}..{hi}')
        self += value.to_bytes(size, 'big', signed=lo < 0)

    def u8(self, value, where):
        self.int(value, 0, 255, 1, where)

    def s8(self, value, where):
        self.int(value, -128, 127, 1, where)

    def s16(self, value, where):
        self.int(value, -32768, 32767, 2, where)

    def text(self, value, where, long=False):
        units = (value or '').encode('utf-16-be', 'surrogatepass')
        if long:
            self.int(len(units) // 2, 0, 2 ** 31 - 1, 4, where)
        else:
            # TuxGuitar's writer silently cuts longer strings at 255 code units.
            self.int(len(units) // 2, 0, 255, 1, where + ' (at most 255 UTF-16 units)')
        self += units


def _xml_duration(node):
    division = node.find('divisionType')
    tuplet = (int(division.get('enters')), int(division.get('times'))) if division is not None else (1, 1)
    return int(node.get('value')), node.get('dotted'), tuplet


def _put_duration(out, duration, where):
    value, dotted, tuplet = duration
    out.u8({None: 0, 'dotted': 1, 'doubleDotted': 2}[dotted] | (4 if tuplet != (1, 1) else 0), where)
    out.s8(value, where)
    if tuplet != (1, 1):
        out.s8(tuplet[0], where)
        out.s8(tuplet[1], where)


def _put_effects(out, note, ver, where):
    header = 0
    for i, tag in enumerate(('bend', 'tremoloBar', 'harmonic', 'grace', 'trill', 'tremoloPicking')):
        if note.find(tag) is not None:
            header |= 1 << i
    for bit, tag in EFFECT_FLAGS:
        if note.find(tag) is not None:
            if tag == 'letRing' and ver < 12:
                _fail(where, 'let ring is not stored before TuxGuitar File Format 1.2')
            header |= bit
    out += header.to_bytes(3, 'big')
    for tag, offset in (('bend', 0), ('tremoloBar', 12)):
        curve = note.find(tag)
        if curve is not None:
            points = curve.findall('point')
            out.s8(len(points), where)
            for p in points:
                out.s8(p.get('position'), where)
                out.s8(int(p.get('value')) + offset, where)
    harmonic = note.find('harmonic')
    if harmonic is not None:
        kind = HARMONIC_CODES[harmonic.get('type')]
        out.s8(kind, where)
        if kind != 1:
            out.s8(harmonic.get('data'), where)
        elif harmonic.get('data', '0') != '0':
            _fail(where, 'legacy formats store no natural-harmonic data')
    grace = note.find('grace')
    if grace is not None:
        out.u8((grace.get('dead') == 'true') | (grace.get('onBeat') == 'true') << 1, where)
        out.s8(grace.get('fret'), where)
        out.s8(GRACE_CODES[int(grace.get('duration'))], where)
        out.s8(grace.get('dynamic'), where)
        out.s8(TRANSITION_CODES[grace.get('transition', 'none')], where)
    trill = note.find('trill')
    if trill is not None:
        out.s8(trill.get('fret'), where)
        out.s8(trill.get('duration'), where)
    picking = note.find('tremoloPicking')
    if picking is not None:
        out.s8(picking.get('duration'), where)


def _put_notes(out, notes, velocity, ver, where):
    for i, note in enumerate(notes):
        nwhere = f'{where}, note {i + 1}'
        v = int(note.get('velocity'))
        header = (1 if i + 1 < len(notes) else 0) | (2 if note.get('tiedNote') == 'true' else 0)
        if v != velocity[0]:
            header |= 8
            velocity[0] = v
        if len(note):
            header |= 4
        out.u8(header, nwhere)
        out.s8(note.get('value'), nwhere)
        out.s8(note.get('string'), nwhere)
        if header & 8:
            out.s8(v, nwhere)
        if header & 4:
            _put_effects(out, note, ver, nwhere)


def _authored(beat):
    return any(v.get('empty') != 'true' for v in beat.findall('voice'))


def _put_beats(out, measure, ver, where, losses):
    """TGSongWriterImpl.writeBeats for one measure; voice-less bookkeeping beats are not written."""
    beats = [b for b in measure.findall('TGBeat') if _authored(b)]
    if not beats:
        if ver == 10:
            _fail(where, 'an empty measure cannot be written in TuxGuitar File Format 1.0 without inventing a rest')
        out.u8(0, where)
        return
    state = [dict(flags=0, duration=(4, None, (1, 1)), velocity=[95]) for _ in range(2)]
    for bi, beat in enumerate(beats):
        bwhere = f'{where}, beat {bi + 1}'
        voices = beat.findall('voice')
        if beat.find('pickStroke') is not None:
            losses.append(f'{bwhere}: pick stroke {beat.find("pickStroke").text} (legacy formats have none)')
        stroke, chord, text = beat.find('stroke'), beat.find('chord'), beat.find('text')
        header = 1 if bi + 1 < len(beats) else 0
        if ver == 10:
            if voices[1].get('empty') != 'true':
                _fail(bwhere, 'TuxGuitar File Format 1.0 has one voice; voice 2 cannot be written')
            if stroke is not None:
                _fail(bwhere, 'TuxGuitar File Format 1.0 stores no strokes')
            if voices[0].get('direction'):
                losses.append(f'{bwhere}: stem direction {voices[0].get("direction")} (1.0 has none)')
            duration = _xml_duration(voices[0].find('duration'))
            notes = voices[0].findall('note')
            if duration != state[0]['duration']:
                header |= 0x02
                state[0]['duration'] = duration
            header |= (0x04 if notes else 0) | (0x08 if chord is not None else 0) | (0x10 if text is not None else 0)
            out.u8(header, bwhere)
            if header & 0x02:
                _put_duration(out, duration, bwhere)
            if notes:
                _put_notes(out, notes, state[0]['velocity'], ver, bwhere)
        else:
            plan = []
            for i, voice in enumerate(voices):
                if voice.get('empty') == 'true':
                    continue
                header |= 0x10 << 2 * i
                duration = _xml_duration(voice.find('duration'))
                notes = voice.findall('note')
                flags = 0x01 if notes else 0
                if duration != state[i]['duration']:
                    flags |= 0x02
                    state[i]['duration'] = duration
                flags |= {'up': 0x04, 'down': 0x08}.get(voice.get('direction'), 0)
                if flags != state[i]['flags']:
                    header |= 0x20 << 2 * i
                    state[i]['flags'] = flags
                plan.append((i, duration, notes))
            header |= (0x02 if stroke is not None else 0) | (0x04 if chord is not None else 0) | (0x08 if text is not None else 0)
            out.u8(header, bwhere)
            for i, duration, notes in plan:
                if header & (0x20 << 2 * i):
                    out.u8(state[i]['flags'], bwhere)
                if state[i]['flags'] & 0x02:
                    _put_duration(out, duration, bwhere)
                if state[i]['flags'] & 0x01:
                    _put_notes(out, notes, state[i]['velocity'], ver, f'{bwhere}, voice {i + 1}')
            if stroke is not None:
                out.s8(STROKE_CODES[stroke.get('direction')], bwhere)
                out.s8(stroke.get('value'), bwhere)
        if chord is not None:
            frets = chord.findall('string')
            out.s8(len(frets), bwhere)
            out.text(chord.find('name').text, bwhere + ' chord name')
            out.s8(chord.find('firstFret').text, bwhere)
            for fret in frets:
                out.s8(fret.text if fret.text else -1, bwhere)
        if text is not None:
            out.text(text.text, bwhere + ' text')


def from_xml(song, label):
    """Serialize a validated TGSong element (tgimport.native_to_tg's) as legacy file format `label`.

    Returns (bytes, losses). Anything that sounds or times differently refuses; display data the
    format cannot hold (max fret, pick strokes, stem direction in 1.0, channel names before 1.3,
    credits before 1.2) is listed in losses. The bytes are read back here: if TuxGuitar's start
    reconstruction from voice ends would move any beat, the export refuses and names it.
    """
    if label not in WRITABLE:
        _fail('export', f'TuxGuitar File Format {label} has no writer (writable: {", ".join(WRITABLE)})')
    ver, out, losses = VERSIONS[label], _Out(), []
    song = copy.deepcopy(song)
    for ti, t in enumerate(song.findall('TGTrack')):
        for note in t.iter('note'):
            flag = note.find('alternativeEnharmonic')
            if flag is not None:
                note.remove(flag)
                losses.append(f'track {ti + 1}: alternative enharmonic spellings (legacy formats spell by key)')
    losses = list(dict.fromkeys(losses))
    out.text(PREFIX + label, 'header')
    for key in ('name', 'artist', 'album', 'author'):
        out.text(song.find(key).text, key)
    late = ('date', 'copyright', 'writer', 'transcriber', 'comments')
    if ver >= 12:
        for key in late:
            out.text(song.find(key).text, key, long=key == 'comments')
    else:
        losses += [f'song {key} (stored from 1.2)' for key in late if song.find(key).text]
    channels = {c.find('id').text: c for c in song.findall('TGChannel')}
    if ver >= 13:
        out.s8(len(channels), 'channel count')
        for c in channels.values():
            out.s16(c.find('id').text, 'channel id')
            for key in ('bank', 'program', 'volume', 'balance', 'chorus', 'reverb', 'phaser', 'tremolo'):
                out.u8(c.find(key).text, 'channel ' + key)
            out.text(c.find('name').text, 'channel name')
            parameters = c.findall('TGChannelParameter')
            out.s16(len(parameters), 'channel parameters')
            for p in parameters:
                out.text(p.get('key'), 'channel parameter')
                out.text(p.get('value'), 'channel parameter', long=True)
    else:
        free, routes = iter([n for n in range(16) if n != 9]), {}
        for cid, c in channels.items():
            if c.find('bank').text not in ('0', '128'):
                _fail(f'channel {cid}', 'formats before 1.3 store no bank other than 0 or percussion')
            routes[cid] = (9, 9) if c.find('bank').text == '128' else (next(free, None),) * 2
            if routes[cid][0] is None:
                _fail('export', 'more than 15 melodic channels do not fit the GM routes of formats before 1.3')
    headers = song.findall('TGMeasureHeader')
    out.s16(len(headers), 'measure count')
    previous = None
    for i, h in enumerate(headers):
        where = f'measure header {i + 1}'
        if h.find('lineBreak') is not None:
            losses.append(f'{where}: line break (not written to legacy formats)')
        ts = h.find('timeSignature')
        meter, bpm = (ts.get('numerator'), ts.get('denominator')), h.find('tempo').text
        feel = h.find('tripletFeel').text if h.find('tripletFeel') is not None else 'none'
        if previous is None:
            flags = 0x03 | (0x40 if feel != 'none' else 0)
        else:
            flags = (0x01 if meter != previous[0] else 0) | (0x02 if bpm != previous[1] else 0) | (0x40 if feel != previous[2] else 0)
        close, alternative, marker = h.find('repeatClose'), h.find('repeatAlternative'), h.find('marker')
        flags |= (0x04 if h.find('repeatOpen') is not None else 0) | (0x08 if close is not None else 0)
        flags |= (0x10 if alternative is not None else 0) | (0x20 if marker is not None else 0)
        out.u8(flags, where)
        if flags & 0x01:
            out.s8(meter[0], where)
            _put_duration(out, (int(meter[1]), None, (1, 1)), where)
        if flags & 0x02:
            out.s16(bpm, where)
        if flags & 0x08:
            out.s16(close.text, where)
        if flags & 0x10:
            out.s8(sum(1 << (int(a.text) - 1) for a in alternative.findall('alternative')), where)
        if flags & 0x20:
            out.text(marker.text, where + ' marker')
            for key in ('R', 'G', 'B'):
                out.u8(marker.get(key), where)
        if flags & 0x40:
            out.s8(FEEL_CODES[feel], where)
        previous = (meter, bpm, feel)
    tracks = song.findall('TGTrack')
    out.s8(len(tracks), 'track count')
    for ti, t in enumerate(tracks):
        loc = f'track {ti + 1}'
        if t.get('maxFret', '29') != '29':
            percussion = channels[t.findtext('channelId')].findtext('bank') == '128'
            if not percussion and any(int(n.get('value')) > 29 for n in t.iter('note')):
                _fail(loc, 'legacy formats have no maxFret; frets above 29 would not read back')
            losses.append(f'{loc}: max fret {t.get("maxFret")} (legacy formats read 29)')
        lyric = t.find('TGLyric')
        has_lyrics = bool(lyric.text)
        if not has_lyrics and lyric.get('from', '1') != '1':
            _fail(loc, 'a lyrics start without lyrics text is not stored')
        out.u8(((0x01 if ver == 10 else 0x04) if has_lyrics else 0), loc)
        out.text(t.find('name').text, loc + ' name')
        if t.find('soloMute') is not None:
            losses.append(f'{loc}: {t.find("soloMute").text} flag (not written to legacy formats)')
        cid = t.find('channelId').text
        if ver >= 13:
            out.s16(cid, loc)
        else:
            c = channels[cid]
            if ver == 10:
                out.u8(0, loc)
            out.u8(routes[cid][0], loc)
            out.u8(routes[cid][1], loc)
            for key in ('program', 'volume', 'balance', 'chorus', 'reverb', 'phaser', 'tremolo'):
                out.s8(c.find(key).text, f'{loc} channel {key}')
            if c.find('name').text and c.find('name').text != t.find('name').text:
                losses.append(f'{loc}: channel name {c.find("name").text!r} (stored from 1.3)')
        clef = key = None
        for mi, m in enumerate(t.findall('TGMeasure')):
            mwhere = f'{loc}, measure {mi + 1}'
            m_clef = m.find('clef').text if m.find('clef') is not None else clef
            m_key = m.find('keySignature').text if m.find('keySignature') is not None else key
            flags = (0x01 if m_clef != clef else 0) | (0x02 if m_key != key else 0)
            out.u8(flags, mwhere)
            _put_beats(out, m, ver, mwhere, losses)
            if flags & 0x01:
                out.s8(CLEF_CODES[m_clef], mwhere)
            if flags & 0x02:
                out.s8(m_key, mwhere)
            clef, key = m_clef, m_key
        strings = t.findall('TGString')
        if ver < 15 and not 4 <= len(strings) <= 7:
            _fail(loc, f'TuxGuitar File Format {label} stores 4..7 strings; TuxGuitar would replace these {len(strings)}')
        out.s8(len(strings), loc)
        for s in strings:
            out.s8(s.text, loc + ' tuning')
        offset = t.find('offset')
        out.s8(int(offset.text if offset is not None else 0) + 24, loc + ' offset')
        for key in ('R', 'G', 'B'):
            out.u8(t.find('color').get(key), loc + ' color')
        if has_lyrics:
            out.s16(lyric.get('from', '1'), loc + ' lyrics start')
            out.text(lyric.text, loc + ' lyrics', long=True)
    data = bytes(out)
    readback, _ = to_xml(data)
    for ti, (a, b) in enumerate(zip(tracks, readback.findall('TGTrack'))):
        for mi, (ma, mb) in enumerate(zip(a.findall('TGMeasure'), b.findall('TGMeasure'))):
            want = [x.find('preciseStart').text for x in ma.findall('TGBeat') if _authored(x)]
            got = [x.find('preciseStart').text for x in mb.findall('TGBeat') if _authored(x)]
            if want != got:
                k = next((i for i, (x, y) in enumerate(zip(want, got)) if x != y), min(len(want), len(got)))
                _fail(f'track {ti + 1}, measure {mi + 1}, beat {k + 1}',
                      'legacy formats store no beat starts and TuxGuitar rebuilds them from voice ends; '
                      'a gap or overlap here would move the beat')
    return data, losses
