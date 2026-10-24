"""Bounded TuxGuitar file-format 2.0 interchange, using only stdlib I/O.

Pinned reference: TuxGuitar 2.1.0, 2c46e2a1cccdfdfa6e6f2692f241bd60bf418129,
TGStream/TGSongReaderImpl/TGSongWriterImpl and TGMusicKeyUtils.
This is notation interchange with explicit placeholder sounds, not sample/IT export.
"""
import io
import copy
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from .model import Cell, Pattern
from .song import it_text
from .tablature import (TempoClock, authoring_view, duration_quarters, playback_plan, repeat_projection,
                        tg_quarter_tempo, _stamp_cohorts)

QUARTER = 2882880
VERSION = b'TuxGuitar_file_format 2.0'
MAX_XML = 8 * 1024 * 1024
FLAGS = {'vibrato': 'vibrato', 'deadNote': 'dead', 'slide': 'slide', 'hammer': 'hammer',
         'ghostNote': 'ghost', 'accentuatedNote': 'accent', 'heavyAccentuatedNote': 'heavy_accent',
         'palmMute': 'palm_mute', 'staccato': 'staccato', 'letRing': 'let_ring',
         'fadeIn': 'fade_in', 'tapping': 'tapping', 'slapping': 'slapping', 'popping': 'popping'}
CLEFS = ('treble', 'bass', 'alto', 'tenor')
HARMONICS = {'N.H': 'natural', 'A.H': 'artificial', 'T.H': 'tapped',
             'P.H': 'pinch', 'S.H': 'semi'}


# TGMusicKeyUtils.noteIndex: the letter (0=C..6=B) TuxGuitar writes for a pitch class under a TG key
# signature 0..14 (1..7 sharps, 8..14 = 1..7 flats).
_INDEX_TABLES = ((0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6), (0, 0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6),
                 (6, 0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6), (0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6, 6),
                 (0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6, 0), (0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6, 0))
_INDEX_KEY = (0, 0, 0, 0, 0, 0, 1, 2, 3, 3, 3, 3, 3, 4, 5)


def _tg_spelling(pitch, key, alternative):
    """TGMusicKeyUtils.noteIndex(pitch, key, altEnharmonic) as a native {step, alter}."""
    index = _INDEX_TABLES[_INDEX_KEY[key]][pitch % 12]
    if alternative:
        sharp = _INDEX_TABLES[_INDEX_KEY[7]][pitch % 12]
        index = sharp if sharp != index else _INDEX_TABLES[_INDEX_KEY[14]][pitch % 12]
    natural = (0, 2, 4, 5, 7, 9, 11)[index]
    return dict(step='CDEFGAB'[index], alter=(pitch - natural + 6) % 12 - 6)


def _fail(where, reason):
    raise ValueError(f'TG 2.0 {where}: {reason}')


def _shape(node, children=(), attrs=(), where=None):
    extra = set(node.attrib) - set(attrs)
    tags = {child.tag for child in node} - set(children)
    if extra or tags:
        _fail(where or node.tag, f'unsupported attributes/elements {sorted(extra | tags)}')
    if children and ((node.text or '').strip() or any((child.tail or '').strip() for child in node)):
        _fail(where or node.tag, 'unexpected mixed XML text')


def _one(node, name, required=False):
    found = node.findall(name)
    if len(found) > 1 or required and not found:
        _fail(node.tag, f'expected {"one" if required else "at most one"} {name}')
    return found[0] if found else None


def _text(node, name, default='', required=False):
    child = _one(node, name, required)
    if child is None:
        return default
    _shape(child)
    return child.text or ''


def _integer(value, lo, hi, where):
    try:
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError()
        n = int(value)
    except (ValueError, TypeError):
        _fail(where, 'expected an integer')
    if not lo <= n <= hi:
        _fail(where, f'integer must be {lo}..{hi}')
    return n


def _lyric_text(value, where):
    if not isinstance(value, str) or len(value) > 65536:
        _fail(where, 'lyrics text must be a string of at most 65536 codepoints')
    # XML 1.0 Char production. ElementTree otherwise emits illegal controls
    # or surrogate character references which its own reader cannot accept.
    if any(not (c in '\t\n\r' or '\x20' <= c <= '\ud7ff' or
                '\ue000' <= c <= '\ufffd' or '\U00010000' <= c <= '\U0010ffff') for c in value):
        _fail(where, 'lyrics text contains characters not representable in XML 1.0')
    return value


def _boolean(value, where):
    if value not in ('true', 'false'):
        _fail(where, 'expected true or false')
    return value == 'true'


def _pair(q):
    q = Fraction(q)
    return [q.numerator, q.denominator]


def _color(node):
    _shape(node, attrs=('R', 'G', 'B'))
    return '#' + ''.join(f'{_integer(node.get(c), 0, 255, node.tag + " " + c):02x}' for c in ('R', 'G', 'B'))


def _written(node):
    _shape(node, ('divisionType',), ('value', 'dotted'))
    dotted = node.get('dotted')
    if dotted not in (None, 'dotted', 'doubleDotted'):
        _fail('duration', 'unsupported dots')
    division = _one(node, 'divisionType')
    tuplet = [1, 1]
    if division is not None:
        _shape(division, attrs=('enters', 'times'))
        tuplet = [_integer(division.get(k), 1, 32767, 'division ' + k) for k in ('enters', 'times')]
    written = dict(value=_integer(node.get('value'), 1, 64, 'duration'),
                   dots={None: 0, 'dotted': 1, 'doubleDotted': 2}[dotted], tuplet=tuplet)
    _precise(duration_quarters(written), 'written duration')
    return written


def _precise(q, where):
    value = Fraction(q) * QUARTER
    if value.denominator != 1 or not 0 <= value <= (1 << 63) - 1:
        _fail(where, 'time is not exactly representable in TG precise units')
    return value.numerator


def _effects_compatible(note, where):
    # The upstream reader invokes setters, rather than assigning independent
    # flags. Refuse source combinations it would silently clear.
    for group in (('ghost', 'accent', 'heavy_accent'), ('palm_mute', 'staccato', 'let_ring'),
                  ('dead', 'slide', 'hammer', 'bend', 'tremolo_bar'),
                  ('tapping', 'slapping', 'popping')):
        if sum(bool(note.get(k)) for k in group) > 1:
            _fail(where, 'effect combination would be normalized by the TG reader')


def _normalize_let_ring(note, order):
    """Let-ring and its two mutually exclusive gates use last-true setter wins."""
    if not note.get('let_ring'):
        return {}
    source = {k: note[k] for k in order if note.get(k)}
    winner = next(reversed(source))
    dropped = {k: v for k, v in source.items() if k != winner}
    for key in dropped:
        note.pop(key)
    return dropped


def _normalize_repetition(note, setters):
    """Apply TG's conflicting setters in the source reader's order.

    Only repetition-bearing imports use this normalization. Return removed
    authored fields so the caller can report/preserve the source information.
    """
    exclusive = ('dead', 'slide', 'hammer', 'bend', 'tremolo_bar', 'trill', 'tremolo_picking')
    if not any(note.get(k) is not None for k in ('trill', 'tremolo_picking')):
        return {}
    source = {k: note[k] for k in (*exclusive, 'vibrato') if k in note}
    for k in source:
        note.pop(k)
    for field, value in setters:
        if not value:
            continue
        if field == 'vibrato':
            clear = ('trill', 'tremolo_picking')
        else:
            clear = tuple(k for k in exclusive if k != field)
            if field in ('trill', 'tremolo_picking'):
                clear += ('vibrato',)
        for k in clear:
            note.pop(k, None)
        note[field] = value
    return {k: v for k, v in source.items() if k not in note}


def _raw(song):
    """Fresh import scaffolds contain only an optional generated row-zero T."""
    from .notation import parse_cell
    count = len(song['module']['channels'])
    patterns = []
    for name, spec in song['patterns'].items():
        pattern = Pattern(name, [[Cell() for _ in range(count)] for _ in range(spec['rows'])])
        data = spec['data'].strip()
        if data:
            if not data.startswith('00:') or '\n' in data:
                _fail(name, 'expected a fresh import scaffold')
            pattern.rows[0][0] = parse_cell(data[3:].strip())
        patterns.append(pattern)
    return patterns


def _xml(data):
    if not isinstance(data, bytes) or len(data) > MAX_XML:
        _fail('archive', 'input must be bounded bytes')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = z.infolist()
            if len(members) != 2 or {i.filename for i in members} != {'version.txt', 'content.xml'}:
                _fail('archive', 'requires exactly version.txt and content.xml')
            if any(i.file_size > MAX_XML or i.flag_bits & 1 for i in members):
                _fail('archive', 'oversized or encrypted member')
            if z.read('version.txt') != VERSION:
                _fail('version', 'only TuxGuitar_file_format 2.0 is supported')
            text = z.read('content.xml').decode('utf-8-sig')
        # ElementTree can auto-detect UTF-16 again even after decoding to str.
        # Reject NUL-containing alternate encodings before declaration checks.
        if '\0' in text:
            _fail('XML', 'only UTF-8 XML without NUL characters is supported')
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            _fail('XML', 'DTD/entity declarations are unsupported')
        root = ET.fromstring(text)
    except (zipfile.BadZipFile, RuntimeError, UnicodeError, ET.ParseError, NotImplementedError) as e:
        _fail('archive/XML', str(e))
    _capacity(root)
    if root.tag != 'TuxGuitarFile':
        _fail('XML', 'expected TuxGuitarFile root')
    _shape(root, ('TGVersion', 'TGSong'))
    producer = _one(root, 'TGVersion')
    if producer is not None:
        _shape(producer, attrs=('major', 'minor', 'revision'))
        for key in ('major', 'minor', 'revision'):
            _integer(producer.get(key), 0, 9999, 'producer version')
    return _one(root, 'TGSong', True)


def _capacity(root):
    count, stack = 0, [(root, 0)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > 200000 or depth > 24:
            _fail('XML', 'element/depth capacity exceeded')
        stack.extend((child, depth + 1) for child in node)


def read_tg(data):
    """Read supported notation into a native song skeleton; no filesystem writes.

    The format is detected from the content, not the extension: a ZIP is the current
    TuxGuitar_file_format 2.0, a length-prefixed "TuxGuitar File Format - 1.x" header is a
    legacy binary file (tglegacy), read through the same validation below.
    Instrument slot 1 is filled by import_tg's shared placeholder publisher.
    Source sound/credit metadata stays descriptive in module.message.
    """
    from . import tglegacy
    legacy = tglegacy.version(data) if isinstance(data, bytes) and not data.startswith(b'PK') else None
    if legacy is not None:
        if len(data) > MAX_XML:
            _fail('archive', 'input must be bounded bytes')
        source, notices = tglegacy.to_xml(data)
        _capacity(source)
    else:
        source, notices = _xml(data), []
        # The manager sorts the stored beat list before placing it. Keep that
        # stable object order when placement brings separate beats together.
        for measure in source.findall('TGTrack/TGMeasure'):
            beats = measure.findall('TGBeat')
            try:
                ordered = sorted(beats, key=lambda b: int(b.findtext('preciseStart')))
            except (TypeError, ValueError):
                continue  # the format validator supplies the field-specific error
            for beat in beats:
                measure.remove(beat)
            measure.extend(ordered)
        for t, m, b, old, new, length in tglegacy.tg_starts(source):
            where = f'track {t}, measure {m}, beat {b}'
            if new is None:
                _fail(where, "TuxGuitar deletes this beat on opening: the measure's first beat has no voice")
            if new >= length:
                _fail(where, f'TuxGuitar opens this beat at quarter {new}, past the end of its measure '
                             f'(stored at {old}); its voices leave no room for it')
            notices.append(f'{where}: moved from quarter {old} to {new}; TuxGuitar places each beat '
                           'at the end of its voices on opening.')
    return read_tree(source, notices)


def read_tree(source, notices=()):
    """Validate a TuxGuitar 2.0 TGSong element into a native song (read_tg's reader; also MIDI score import)."""
    notices = list(notices)
    credit_keys =('name', 'artist', 'album', 'author', 'date', 'copyright', 'writer', 'transcriber', 'comments')
    _shape(source, (*credit_keys, 'TGChannel', 'TGMeasureHeader', 'TGTrack'))
    credits = {k: _text(source, k, required=True) for k in credit_keys}
    title = credits['name']
    metadata = [credits['comments']] if credits['comments'] else []
    if it_text(title, 25) != title:
        metadata.append('Source title: ' + title)
    metadata += [k + ': ' + credits[k] for k in credit_keys[1:-1] if credits[k]]
    metadata += notices
    channel_map = {}
    for node in source.findall('TGChannel'):
        fields = ('id', 'bank', 'program', 'volume', 'balance', 'chorus', 'reverb', 'phaser', 'tremolo', 'name')
        _shape(node, (*fields, 'TGChannelParameter'))
        cid = _integer(_text(node, 'id', required=True), 0, 32767, 'channel id')
        if cid in channel_map:
            _fail('channel', 'duplicate id')
        channel = {k: _integer(_text(node, k, required=True), 0, 16383 if k == 'bank' else 127, 'channel ' + k)
                   for k in fields[1:-1]}
        parameters = node.findall('TGChannelParameter')
        if parameters:
            routes = {}
            for parameter in parameters:
                _shape(parameter, attrs=('key', 'value'))
                key = parameter.get('key')
                if key in routes or key not in ('gm-channel-1', 'gm-channel-2') or (parameter.text or '').strip():
                    _fail(f'channel {cid}', 'unsupported MIDI channel parameter')
                routes[key] = parameter.get('value')
            if channel['bank'] == 128:
                if routes != {'gm-channel-1': '9', 'gm-channel-2': '9'}:
                    _fail(f'channel {cid}', 'only canonical percussion MIDI routes 9/9 are supported')
            else:
                # TuxGuitar's GM router stores these on melodic channels (always in files
                # converted from 1.0-1.2). They pick output MIDI channels, which the native
                # score does not store; GM channel 10 would turn the channel into drums.
                if set(routes) != {'gm-channel-1', 'gm-channel-2'} or any(
                        v not in [str(n) for n in range(16) if n != 9] for v in routes.values()):
                    _fail(f'channel {cid}', 'melodic MIDI routes must be two GM channels 0..15 other than 9')
                notice = (f'channel {cid}: TuxGuitar GM output routing {routes["gm-channel-1"]}/'
                          f'{routes["gm-channel-2"]} is not stored natively; TG export lets TuxGuitar assign routes.')
                notices.append(notice)
                metadata.append(notice)
        if any(channel[k] for k in ('chorus', 'reverb', 'phaser', 'tremolo')):
            _fail(f'channel {cid}', 'non-neutral effects cannot be preserved')
        channel['name'] = _text(node, 'name', required=True)
        channel_map[cid] = channel
    headers, start, meter, tempo = [], Fraction(0), [4, 4], 120
    for i, node in enumerate(source.findall('TGMeasureHeader')):
        _shape(node, ('timeSignature', 'tempo', 'marker', 'tripletFeel',
                      'repeatOpen', 'repeatClose', 'repeatAlternative', 'lineBreak'), where=f'measure {i + 1}')
        ts = _one(node, 'timeSignature')
        if ts is not None:
            _shape(ts, attrs=('numerator', 'denominator'))
            meter = [_integer(ts.get(k), 1, 64, 'meter ' + k) for k in ('numerator', 'denominator')]
            if meter[1] not in (1, 2, 4, 8, 16, 32, 64):
                _fail('meter', 'denominator must be a power of two')
        t = _one(node, 'tempo')
        if t is not None:
            _shape(t, attrs=('base', 'dotted'))
            # TGSongReaderImpl: base defaults to a quarter, dotted to false; TGTempo plays the quarter value.
            base, dotted = _integer(t.get('base', '4'), 1, 64, 'tempo base'), t.get('dotted', 'false') == 'true'
            if base not in (1, 2, 4, 8, 16, 32, 64):
                _fail(f'measure {i + 1}', 'tempo base must be a note value 1..64')
            raw = _integer(t.text, 1, 10000, 'tempo')
            tempo = tg_quarter_tempo(raw, base, dotted)
            if not 32 <= tempo <= 255:
                _fail(f'measure {i + 1}', f'tempo {tempo} quarter notes per minute is outside 32..255')
            unit = dict(base=base, dotted=dotted, value=raw) if (base, dotted) != (4, False) else None
        length = Fraction(meter[0] * 4, meter[1])
        header = dict(start=start, length=length, meter=list(meter), tempo=tempo)
        if t is not None and unit:
            header['tempo_unit'] = unit
        opened = _one(node, 'repeatOpen')
        if opened is not None:
            _shape(opened)
            if list(opened) or (opened.text or '').strip():
                _fail(f'measure {i + 1}', 'repeatOpen must be an empty flag')
            header['repeat_open'] = True
        close = _one(node, 'repeatClose')
        if close is not None:
            _shape(close)
            header['repeat_close'] = _integer(close.text, 0, 100, 'repeatClose')
        alternatives = _one(node, 'repeatAlternative')
        if alternatives is not None:
            _shape(alternatives, ('alternative',))
            endings = []
            for alternative in alternatives:
                _shape(alternative)
                ending = _integer(alternative.text, 1, 8, 'alternative')
                if ending in endings:
                    _fail(f'measure {i + 1}', 'duplicate ending changes the installed reader mask')
                if ending == 8:
                    _fail(f'measure {i + 1}', 'ending 8 cannot be preserved: installed TG 2.0 reader uses a signed-byte ending mask')
                endings.append(ending)
            header['endings'] = sorted(endings)
        feel = _one(node, 'tripletFeel')
        if feel is not None:
            _shape(feel)
            if feel.text not in ('none', 'eighth', 'sixteenth'):
                _fail(f'measure {i + 1}', 'invalid triplet feel')
            header['swing'] = feel.text
        marker = _one(node, 'marker')
        if marker is not None:
            header['marker'] = dict(title=marker.text or '', color=_color(marker))
        if _one(node, 'lineBreak') is not None:   # TG reads only the flag's presence
            header['line_break'] = True
        headers.append(header)
        start += length
    if not 1 <= len(headers) <= 254:
        _fail('song', 'requires 1..254 measures')
    speed = next((s for s in [6, *range(1, 6), *range(7, 256)]
                  if all((h['length'] * 24 / s).denominator == 1 and 1 <= h['length'] * 24 / s <= 200 for h in headers)), None)
    if speed is None:
        _fail('song', 'measure lengths do not fit exact backing rows')
    score = dict(version=1, tracks={}, patterns={}, order_ids=[], ties=[], measures=[])
    score['metadata'] = {('title' if key == 'name' else key): value for key, value in credits.items() if value}
    song = dict(module=dict(title=it_text(title, 25), tempo=headers[0]['tempo'], speed=speed,
                            sample_rate=44100, channels=[], global_volume=128, mix_volume=48),
                samples={}, instruments={1: {'name': 'guitar (placeholder)'}}, patterns={}, orders=[], score=score)
    for mi, h in enumerate(headers):
        name, oid = f'm{mi + 1}', f'o{mi + 1}'
        song['orders'].append(name)
        score['order_ids'].append(oid)
        song['patterns'][name] = dict(rows=int(h['length'] * 24 / speed), data='')
        if mi and h['tempo'] != headers[mi - 1]['tempo']:
            song['patterns'][name]['data'] = f"00: ... .. ... T{h['tempo']:02X}\n"
        score['patterns'][name] = dict(row_step=_pair(Fraction(speed, 24)), beats=[])
        measure = dict(id=name, meter=h['meter'], **{'from': dict(occurrence=oid, at=[0, 1]),
                                                   'to': dict(occurrence=oid, at=_pair(h['length']))})
        if 'marker' in h:
            measure['marker'] = h['marker']
        for key in ('swing', 'repeat_open', 'repeat_close', 'endings', 'line_break', 'tempo_unit'):
            if key in h:
                measure[key] = h[key]
        score['measures'].append(measure)
    used_channels = set()
    for ti, node in enumerate(source.findall('TGTrack')):
        loc, tid = f'track {ti + 1}', f't{ti + 1}'
        _shape(node, ('name', 'soloMute', 'channelId', 'offset', 'color', 'TGString', 'TGLyric', 'TGMeasure'), ('maxFret',), loc)
        solo_mute = _text(node, 'soloMute', '') or None   # TG: 'solo' or 'mute'; any other text means neither
        solo_mute = solo_mute if solo_mute in ('solo', 'mute') else None
        cid = _integer(_text(node, 'channelId', required=True), 0, 32767, loc + ' channelId')
        if cid not in channel_map:
            _fail(loc, 'unknown channelId')
        if cid in used_channels:
            _fail(loc, 'shared MIDI-channel routing across tracks cannot be preserved')
        used_channels.add(cid)
        c = channel_map[cid]
        percussion = c['bank'] == 128
        lyrics = _one(node, 'TGLyric')
        if lyrics is not None:
            _shape(lyrics, attrs=('from',))
        lyric = dict(from_measure=_integer(lyrics.get('from', '1') if lyrics is not None else '1',
                                           1, 2147483647, loc + ' lyrics start'),
                     text=_lyric_text((lyrics.text or '') if lyrics is not None else '', loc))
        tuning = []
        for string in node.findall('TGString'):
            _shape(string)
            tuning.append(_integer(string.text, 0, 119, loc + ' tuning'))
        first = len(song['module']['channels'])
        if not 1 <= len(tuning) <= 25 or first + len(tuning) > 64:
            _fail(loc, 'string/channel capacity exceeded')
        name = _text(node, 'name', required=True)
        if c['name'] and c['name'] != name:
            metadata.append(f'{loc} source channel name: {c["name"]}')
        volume = (c['volume'] * 64 + 63) // 127
        pan = (c['balance'] * 64 + 63) // 127
        song['module']['channels'] += [dict(name=it_text(f'{name} str {s + 1}', 20), volume=volume, pan=pan)
                                       for s in range(len(tuning))]
        track = dict(name=name, tuning=tuning, channels=list(range(first, first + len(tuning))), instrument=1,
                     midi=dict(program=c['program'], bank=c['bank']),
                     capo=_integer(_text(node, 'offset', '0'), -24, 24, loc + ' capo'),
                     max_fret=_integer(node.get('maxFret', '29'), 0, 36, loc + ' maxFret'),
                     color=_color(_one(node, 'color', True)))
        if percussion and (any(tuning) or track['capo']):
            _fail(loc, 'percussion requires zero tuning and capo')
        if lyric['text'] or lyric['from_measure'] != 1:
            track['lyrics'] = lyric
        for field, value, native, default in (('pan', c['balance'], pan, 64),
                                               ('volume', c['volume'], volume, 127)):
            if value != default:
                track['midi']['source_' + field] = dict(value=value, **{'mixer_' + field: native})
        if c['volume'] != 127 or c['balance'] not in (63, 64):
            notices.append(f'{loc}: source MIDI volume {c["volume"]}/pan {c["balance"]} retained for interchange; '
                           f'native audio uses tracker volume {volume}/pan {pan} on the 0..64 mixer scale.')
        score['tracks'][tid] = track
        measures = node.findall('TGMeasure')
        if len(measures) != len(headers):
            _fail(loc, 'measure count differs from headers')
        clef, key, previous = 'treble', 0, {}
        for mi, (measure, h) in enumerate(zip(measures, headers)):
            mloc = f'{loc}, measure {mi + 1}'
            _shape(measure, ('clef', 'keySignature', 'TGBeat'), where=mloc)
            clef = _text(measure, 'clef', clef)
            key = _integer(_text(measure, 'keySignature', str(key)), 0, 14, mloc + ' key')
            if clef not in CLEFS:
                _fail(mloc, 'unsupported clef')
            fifths = key if key <= 7 else 7 - key
            if mi == 0:
                track.update(clef=clef, key=dict(fifths=fifths, mode='major'))
                if solo_mute:
                    track['solo_mute'] = solo_mute
            else:   # a clef or key change: the measure's own staff override for this track
                change = {**({'clef': clef} if clef != track['clef'] else {}),
                          **({'key': dict(fifths=fifths, mode='major')} if fifths != track['key']['fifths'] else {})}
                if change:
                    score['measures'][mi].setdefault('staff', {})[tid] = change
            cohorts = []
            for bi, b in enumerate(measure.findall('TGBeat')):
                cohort = []
                bloc = f'{mloc}, beat {bi + 1}'
                _shape(b, ('preciseStart', 'text', 'stroke', 'pickStroke', 'chord', 'voice'), where=bloc)
                if percussion and any(_one(b, tag) is not None for tag in ('stroke', 'pickStroke', 'chord')):
                    _fail(bloc, 'percussion techniques/chords are unsupported')
                shared = {}
                chord = _one(b, 'chord')
                if chord is not None:
                    _shape(chord, ('name', 'firstFret', 'string'), where=bloc + ' chord')
                    frets = []
                    for string in chord.findall('string'):
                        _shape(string)
                        frets.append(-1 if string.text is None or string.text == '' else
                                     _integer(string.text, 0, track['max_fret'], bloc + ' chord fret'))
                    shared['chord'] = dict(name=_text(chord, 'name', required=True),
                        first_fret=_integer(_text(chord, 'firstFret', required=True), 0, track['max_fret'],
                                            bloc + ' chord firstFret'), frets=frets)
                stroke = _one(b, 'stroke')
                if stroke is not None:
                    _shape(stroke, attrs=('direction', 'value'), where=bloc + ' stroke')
                    direction = stroke.get('direction')
                    value = _integer(stroke.get('value'), 0, 64, bloc + ' stroke value')
                    if (stroke.text or '').strip() or direction not in ('none', 'up', 'down'):
                        _fail(bloc, 'unsupported stroke direction/content')
                    if direction == 'none':
                        if value:
                            _fail(bloc, 'none stroke must have value 0')
                    elif value not in (4, 8, 16, 32, 64):
                        _fail(bloc, 'unsupported stroke value')
                    else:
                        shared['stroke'] = dict(direction=direction, value=value)
                pick = _one(b, 'pickStroke')
                if pick is not None:
                    _shape(pick, where=bloc + ' pickStroke')
                    if pick.text not in ('up', 'down'):
                        _fail(bloc, 'unsupported pickStroke direction')
                    shared['pick_stroke'] = pick.text
                precise = _integer(_text(b, 'preciseStart', required=True), QUARTER, (1 << 63) - 1, bloc)
                absolute = Fraction(precise - QUARTER, QUARTER)
                if mi == 0 and bi == 0 and absolute:
                    _fail(bloc, 'first beat must start at the TG one-quarter origin')
                if not h['start'] <= absolute < h['start'] + h['length']:
                    _fail(bloc, 'out-of-measure beat start')
                voices = b.findall('voice')
                if len(voices) != 2:
                    _fail(bloc, 'requires two ordered voice slots')
                text = _text(b, 'text')
                text_used = False
                for vi, v in enumerate(voices):
                    vloc = f'{bloc}, voice {vi + 1}'
                    _shape(v, ('duration', 'note'), ('direction', 'empty'), vloc)
                    written = _written(_one(v, 'duration', True))
                    notes = v.findall('note')
                    empty = _boolean(v.get('empty', 'false' if notes else 'true'), vloc)
                    if empty:
                        if notes or v.get('direction'):
                            _fail(vloc, 'empty voice contains notes/direction')
                        continue
                    bid = f'{tid}_b{bi + 1}_v{vi + 1}'
                    beat = dict(id=bid, track=tid, voice=vi, at=_pair(absolute - h['start']), written=written, notes=[])
                    beat.update(copy.deepcopy(shared))
                    if v.get('direction'):
                        if v.get('direction') not in ('up', 'down'):
                            _fail(vloc, 'unsupported stem direction')
                        beat['stem'] = v.get('direction')
                    if text and not text_used:
                        beat['text'], text_used = text, True
                    velocity = 95
                    for ni, n in enumerate(notes):
                        nloc = f'{vloc}, note {ni + 1}'
                        _shape(n, (*FLAGS, 'bend', 'tremoloBar', 'harmonic', 'trill', 'tremoloPicking', 'grace',
                                   'alternativeEnharmonic'),
                               ('string', 'value', 'velocity', 'tiedNote'), nloc)
                        velocity = _integer(n.get('velocity', str(velocity)), 0, 127, nloc + ' velocity')
                        string = _integer(n.get('string'), 1, len(tuning), nloc + ' string')
                        if percussion and any(child.tag not in ('ghostNote', 'accentuatedNote', 'heavyAccentuatedNote',
                                                                'staccato', 'deadNote', 'palmMute', 'letRing', 'grace', 'tremoloPicking') for child in n):
                            _fail(nloc, 'percussion techniques are unsupported')
                        fret = _integer(n.get('value'), 1 if percussion else 0, 100 if percussion else track['max_fret'],
                                        nloc + (' percussion key' if percussion else ' fret'))
                        note = dict(id=f'{bid}_n{ni + 1}', string=string, fret=fret,
                                    pitch=tuning[string - 1] + track['capo'] + fret, velocity=velocity)
                        alternative = _one(n, 'alternativeEnharmonic')
                        if alternative is not None:
                            _shape(alternative)
                            if (alternative.text or '').strip():
                                _fail(nloc, 'alternativeEnharmonic must be an empty element')
                            spelling = _tg_spelling(note['pitch'], key, True)
                            if spelling != _tg_spelling(note['pitch'], key, False):
                                note['spelling'] = spelling
                        for tag, field in FLAGS.items():
                            flag = _one(n, tag)
                            if flag is not None:
                                _shape(flag)
                                if (flag.text or '').strip():
                                    _fail(nloc, 'effect flags must be empty elements')
                                note[field] = True
                        # TG invokes these setters in a fixed order, regardless
                        # of XML element order; each true setter clears the others.
                        techniques = [k for k in ('tapping', 'slapping', 'popping') if note.get(k)]
                        if len(techniques) > 1:
                            dropped = {k: note.pop(k) for k in techniques[:-1]}
                            notice = (f'{nloc}: TuxGuitar 2.1.0 TG reader normalized tap/slap/pop conflicts; '
                                      f'removed source fields {dropped!r}.')
                            notices.append(notice)
                            metadata.append(notice)
                        grace = _one(n, 'grace')
                        if grace is not None:
                            _shape(grace, attrs=('fret', 'duration', 'dynamic', 'transition', 'onBeat', 'dead'), where=nloc + ' grace')
                            value = _integer(grace.get('duration'), 16, 64, nloc + ' grace duration')
                            transition = grace.get('transition', 'none')
                            if value not in (16, 32, 64) or transition not in ('none', 'slide', 'bend', 'hammer') or (grace.text or '').strip():
                                _fail(nloc, 'unsupported grace duration or transition')
                            note['grace'] = dict(fret=_integer(grace.get('fret'), 1 if percussion else 0,
                                100 if percussion else track['max_fret'], nloc + ' grace fret'),
                                value=value, velocity=_integer(grace.get('dynamic'), 0, 127, nloc + ' grace dynamic'),
                                transition=transition, on_beat=_boolean(grace.get('onBeat', 'false'), nloc + ' grace onBeat'),
                                dead=_boolean(grace.get('dead', 'false'), nloc + ' grace dead'))
                        harmonic = _one(n, 'harmonic')
                        if harmonic is not None:
                            _shape(harmonic, attrs=('type', 'data'), where=nloc + ' harmonic')
                            if harmonic.get('type') not in HARMONICS or (harmonic.text or '').strip():
                                _fail(nloc, 'unsupported harmonic type/content')
                            note['harmonic'] = dict(type=HARMONICS[harmonic.get('type')],
                                                    data=_integer(harmonic.get('data'), 0, 5, nloc + ' harmonic data'))
                        for tag, field in (('bend', 'bend'), ('tremoloBar', 'tremolo_bar')):
                            curve = _one(n, tag)
                            if curve is not None:
                                _shape(curve, ('point',))
                                points = []
                                for p in curve.findall('point'):
                                    _shape(p, attrs=('position', 'value'))
                                    points.append(dict(position=_integer(p.get('position'), 0, 12, nloc),
                                                       value=_integer(p.get('value'), -12 if field == 'tremolo_bar' else 0, 12, nloc)))
                                if not points:
                                    _fail(nloc, 'empty curves are not preserved by the TG writer')
                                note[field] = dict(points=points)
                        for tag, field, rates in (('trill', 'trill', (4, 8, 16, 32, 64)),
                                                  ('tremoloPicking', 'tremolo_picking', (8, 16, 32))):
                            effect = _one(n, tag)
                            if effect is not None:
                                _shape(effect, attrs=('fret', 'duration') if tag == 'trill' else ('duration',))
                                if (effect.text or '').strip():
                                    _fail(nloc, f'{tag} must be an empty element')
                                value = _integer(effect.get('duration'), 1, 64, nloc + ' ' + tag + ' duration')
                                if value not in rates:
                                    _fail(nloc, f'unsupported {tag} duration {value}')
                                note[field] = dict(value=value)
                                if tag == 'trill':
                                    note[field]['fret'] = _integer(effect.get('fret'), 0, track['max_fret'], nloc + ' trill fret')
                        dropped = _normalize_repetition(note, [
                            (k, note.get(k)) for k in ('vibrato', 'dead', 'slide', 'hammer', 'bend',
                                                      'tremolo_bar', 'trill', 'tremolo_picking')])
                        if dropped:
                            notice = f'{nloc}: TuxGuitar 2.1.0 TG reader normalized repetition conflicts; removed source fields {dropped!r}.'
                            notices.append(notice)
                            metadata.append(notice)
                        dropped = _normalize_let_ring(note, ('palm_mute', 'staccato', 'let_ring'))
                        if dropped:
                            notice = f'{nloc}: TuxGuitar 2.1.0 TG reader normalized let-ring conflicts; removed source fields {dropped!r}.'
                            notices.append(notice)
                            metadata.append(notice)
                        _effects_compatible(note, nloc)
                        endpoint = dict(occurrence=score['order_ids'][mi], note=note['id'])
                        if _boolean(n.get('tiedNote', 'false'), nloc):
                            old = previous.get((vi, string))
                            if old is None or old[0] != absolute or old[1] != note['pitch']:
                                _fail(nloc, 'tie needs an adjacent same-pitch predecessor')
                            score['ties'].append({'from': old[2], 'to': endpoint})
                        previous[(vi, string)] = (absolute + duration_quarters(written), note['pitch'], endpoint)
                        beat['notes'].append(note)
                    score['patterns'][song['orders'][mi]]['beats'].append(beat)
                    cohort.append(beat)
                if text and not text_used:
                    _fail(bloc, 'text without an authored voice cannot be preserved')
                if shared and all(v.get('empty', 'false' if v.findall('note') else 'true') == 'true' for v in voices):
                    _fail(bloc, 'stroke/pick without an authored voice cannot be preserved')
                if cohort:
                    cohorts.append(cohort)
            _stamp_cohorts(cohorts)
    if not score['tracks'] or used_channels != set(channel_map):
        _fail('song', 'missing tracks or unused channel definitions')
    song['module']['message'] = '\n'.join(metadata)
    if len(song['module']['message']) > 65534:
        _fail('song', 'metadata exceeds module message capacity')
    raw = _raw(song)
    if repeat_projection(song, raw, 44100) is None:
        playback_plan(song, raw, 44100)
    warnings = ['TG notation imported with synthesized placeholders; source programs/banks are descriptive metadata, not reproduced sounds.', *notices]
    if song['module']['title'] != title:
        warnings.append('Backing IT title shortened/transliterated; full source title preserved in module.message.')
    return song, warnings


def import_tg(src, song_path, samples_dir):
    """Import with the shared fresh-destination placeholder publication boundary."""
    from .gpimport import publish_native_score
    song, warnings = read_tg(Path(src).read_bytes())
    return publish_native_score(song, src, song_path, samples_dir, warnings)


def _add(parent, tag, text=None, **attrs):
    node = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        node.text = str(text)
    return node


def _write_color(parent, tag, color, text=None):
    return _add(parent, tag, text, **{k: int(color[i:i + 2], 16) for k, i in zip(('R', 'G', 'B'), (1, 3, 5))})


def _fill_export_silence(entries, start, where, *, max_dots=2):
    """Consecutive export-only rests preserve sparse voices without moving notes.

    Reuse the editor's exact spelling; the native document is never modified.
    Trailing silence and entirely absent voices need no written filler.
    """
    from .tablature import _split_written
    filled, count, cursor = [], 0, start
    for at, occurrence, beat in sorted(entries, key=lambda entry: entry[0]):
        if at < cursor:
            _fail(where, 'overlapping voice cannot be represented')
        if at > cursor:
            for written in _split_written(at - cursor):
                pieces = [written]
                if written['dots'] > max_dots:
                    if max_dots != 1 or written['value'] > 16:
                        _fail(where, 'silent gap needs an unsupported written subdivision')
                    pieces = [dict(written, dots=1), dict(written, value=written['value'] * 4, dots=0)]
                for piece in pieces:
                    count += 1
                    rest = dict(id=f'{where}-rest-{count}', track=beat['track'], voice=beat.get('voice', 0),
                                written=piece, notes=[])
                    filled.append((cursor, occurrence, rest))
                    cursor += duration_quarters(piece)
        filled.append((at, occurrence, beat))
        cursor = at + duration_quarters(beat['written'])
    return filled, count


def track_midi_mix(song, track):
    """One external channel needs a uniform native part mix; untouched source CCs win."""
    specs = song['module']['channels']
    if isinstance(specs, int):
        specs = [{} for _ in range(specs)]
    parents = [specs[ch] for ch in track['channels']]
    if any(c.get('muted', False) for c in parents):
        raise ValueError('per-string mixer mute cannot be represented; use the part solo/mute setting')
    result = {}
    for field, default in (('volume', 64), ('pan', 32)):
        values = {c.get(field, default) for c in parents}
        if len(values) != 1 or not 0 <= next(iter(values)) <= 64:
            raise ValueError(f'per-string mixer {field} must be uniform within each part and cannot use surround')
        value = next(iter(values))
        binding = track.get('midi', {}).get('source_' + field)
        result[field] = (binding['value'] if binding and binding['mixer_' + field] == value
                         else (value * 127 + 32) // 64)
    return result


def native_to_tg(song, raw_patterns, *, channels, version='2.0'):
    """Return (TG bytes, explicit interchange report), without writing files.

    channels maps every track id to an explicit {program, bank}. Sound samples,
    identities, pattern sharing and instrument assignments are not TG data.
    version '2.0' writes the current ZIP format; '1.0', '1.1', '1.2', '1.3' or '1.5'
    writes that legacy binary format (tglegacy.from_xml), which refuses what it cannot
    hold and lists display-only losses in the report.
    """
    from . import tglegacy
    if version != '2.0' and version not in tglegacy.WRITABLE:
        _fail('export', f'unsupported TuxGuitar file format {version!r} (2.0, {", ".join(tglegacy.WRITABLE)})')
    repeated = repeat_projection(song, raw_patterns, 44100)
    if repeated is None:
        playback_plan(song, raw_patterns, 44100)
    view = repeated.source_view if repeated is not None else authoring_view(song, raw_patterns)
    score, module = song['score'], song.get('module', {})
    if set(channels) != set(score['tracks']):
        _fail('export', 'explicit program/bank mapping is required for every track')
    if any(not c.is_empty() and not (c.note is None and not c.instrument and c.volcmd is None
                                    and c.effect == 20 and 32 <= c.param <= 255)
           for p in raw_patterns for row in p.rows for c in row):
        _fail('export', 'residual tracker commands cannot be represented')
    for field, default in (('global_volume', 128), ('mix_volume', 48), ('separation', 128)):
        if module.get(field, default) != default:
            _fail('export', f'non-neutral {field} cannot be represented')
    mixes = {tid: track_midi_mix(song, track) for tid, track in score['tracks'].items()}
    occurrences = {o['id']: Fraction(*o['at']) for o in view['occurrences']}
    measures = []
    for m in score.get('measures', []):
        if 8 in m.get('endings', []):
            _fail('export', 'ending 8 cannot be preserved: installed TG 2.0 reader uses a signed-byte ending mask')
        a, b = (occurrences[m[k]['occurrence']] + Fraction(*m[k]['at']) for k in ('from', 'to'))
        measures.append((a, b, m))
    measures.sort(key=lambda entry: entry[0])
    if not measures or measures[0][0] != 0 or measures[-1][1] != Fraction(*view['duration']) or any(
            a[1] != b[0] for a, b in zip(measures, measures[1:])):
        _fail('export', 'explicit measures must cover the complete arrangement without gaps')
    starts = {a for a, _, _ in measures}
    step = Fraction(*view['row_step'])
    for pattern in raw_patterns:
        changed_rows = [i for i, row in enumerate(pattern.rows) if any(c.effect == 20 for c in row)]
        played = [o for o in view['occurrences'] if o['pattern'] == pattern.name]
        if changed_rows and not played:
            _fail(pattern.name, 'unused tempo commands cannot be represented')
        for occurrence in played:
            for row in changed_rows:
                if Fraction(*occurrence['at']) + row * step not in starts:
                    _fail(pattern.name, 'midmeasure tempo command cannot be represented, including no-op changes')
    # Headers describe the authored score, never a repeated performance clock.
    if any(m.get('double_bar') for _, _, m in measures):
        _fail('measures', 'TuxGuitar has no double-barline field; use GP or native YAML to preserve it')
    tempo_clock = TempoClock(module.get('tempo', 125), view.get('tempos'))
    root = ET.Element('TuxGuitarFile')
    target = _add(root, 'TGSong')
    credits = score.get('metadata', {})
    _add(target, 'name', credits.get('title', module.get('title', '')))
    for field in ('artist', 'album', 'author', 'date', 'copyright', 'writer', 'transcriber'):
        _add(target, field, credits.get(field, ''))
    _add(target, 'comments', credits.get('comments', module.get('message', '')))
    for ci, (tid, channel) in enumerate(channels.items(), 1):
        if set(channel) != {'program', 'bank'}:
            _fail(tid, 'channel mapping must contain only program and bank')
        c = _add(target, 'TGChannel')
        _add(c, 'id', ci)
        for field in ('bank', 'program'):
            value = _integer(channel[field], 0, 16383 if field == 'bank' else 127, tid + ' ' + field)
            if field == 'bank' and (value == 128) != (score['tracks'][tid].get('midi', {}).get('bank') == 128):
                _fail(tid, 'channel mapping cannot change percussion classification')
            _add(c, field, value)
        mix = mixes[tid]
        for field, value in (('volume', mix['volume']), ('balance', mix['pan']), ('chorus', 0), ('reverb', 0), ('phaser', 0), ('tremolo', 0)):
            _add(c, field, value)
        _add(c, 'name', score['tracks'][tid].get('name', tid))
        if channel['bank'] == 128:
            for key in ('gm-channel-1', 'gm-channel-2'):
                _add(c, 'TGChannelParameter', key=key, value=9)
    for a, b, m in measures:
        _precise(a, 'measure start')
        _precise(b, 'measure end')
        h = _add(target, 'TGMeasureHeader')
        _add(h, 'timeSignature', numerator=m['meter'][0], denominator=m['meter'][1])
        tempo, unit = tempo_clock.tempo_at(a), m.get('tempo_unit')
        if unit is None:
            _add(h, 'tempo', tempo)
        else:   # TGSongWriterImpl: the raw value, base only when not a quarter, dotted only when true
            if tg_quarter_tempo(unit['value'], unit['base'], unit['dotted']) != tempo:
                _fail(f"measure {m['id']}", f"written tempo {unit['value']} (1/{unit['base']}{' dotted' if unit['dotted'] else ''}) "
                      f'no longer plays the measure\'s {tempo} quarter notes per minute; set its beat unit again')
            _add(h, 'tempo', unit['value'], **({'base': unit['base']} if unit['base'] != 4 else {}),
                 **({'dotted': 'true'} if unit['dotted'] else {}))
        if m.get('repeat_open'):
            _add(h, 'repeatOpen')
        if 'repeat_close' in m:
            _add(h, 'repeatClose', m['repeat_close'])
        if 'endings' in m:
            alternatives = _add(h, 'repeatAlternative')
            for ending in sorted(m['endings']):
                _add(alternatives, 'alternative', ending)
        if 'swing' in m:
            _add(h, 'tripletFeel', m['swing'])
        if 'marker' in m:
            _write_color(h, 'marker', m['marker'].get('color', '#000000'), m['marker']['title'])
        if m.get('line_break'):
            _add(h, 'lineBreak')
    resolved = {p['id']: p for p in view['positions'] if p['kind'] == 'note'}
    tied_in = {(t['to']['occurrence'], t['to']['note']) for t in score.get('ties', [])}
    clef_warnings, generated_rests = [], 0
    for ci, tid in enumerate(channels, 1):
        track = score['tracks'][tid]
        clef = track.get('clef', 'treble')
        key = track.get('key', {'fifths': 0, 'mode': 'major'})
        if clef == 'percussion' and track.get('midi', {}).get('bank') == 128:
            if key.get('fifths', 0) != 0 or key.get('mode', 'major') != 'major':
                _fail(tid, 'percussion clef mapping requires a neutral 0/major key')
            # TG stores four conventional clefs; bank128 draws the neutral glyph.
            clef = 'treble'
            clef_warnings.append(f'Track {tid}: native percussion clef serialized as TG treble; '
                                 'bank 128 retains the neutral drum display. Reimport retains the stored treble field.')
        if clef not in CLEFS or key.get('mode', 'major') != 'major':
            _fail(tid, 'percussion clef/minor-mode metadata is not representable')
        t = _add(target, 'TGTrack', maxFret=track.get('max_fret', 29))
        _add(t, 'name', track.get('name', tid))
        if track.get('solo_mute'):
            _add(t, 'soloMute', track['solo_mute'])
        _add(t, 'channelId', ci)
        if track.get('capo', 0):
            _add(t, 'offset', track['capo'])
        _write_color(t, 'color', track.get('color', '#000000'))
        for pitch in track['tuning']:
            _add(t, 'TGString', pitch)
        lyric = track.get('lyrics', {'from_measure': 1, 'text': ''})
        _add(t, 'TGLyric', _lyric_text(lyric['text'], tid), **{'from': lyric['from_measure']})
        grouped = [{} for _ in measures]
        for oid, pname in zip(score['order_ids'], song['orders']):
            for beat in score['patterns'].get(str(pname), {}).get('beats', []):
                if beat['track'] != tid:
                    continue
                at = occurrences[oid] + Fraction(*beat['at'])
                end = at + duration_quarters(beat['written'])
                mi = next((i for i, (a, b, _) in enumerate(measures) if a <= at < b), None)
                if mi is None or end > measures[mi][1]:
                    _fail(beat['id'], 'written beat crosses a measure boundary')
                _precise(at + 1, beat['id'])
                _precise(duration_quarters(beat['written']), beat['id'])
                if beat.get('duration_source'):
                    _fail(beat['id'], 'tracker-derived duration metadata is not representable')
                slot = grouped[mi].setdefault((at, beat.get('cohort', 0)), {})
                vi = beat.get('voice', 0)
                if vi in slot:
                    _fail(beat['id'], 'duplicate voice at a timestamp')
                slot[vi] = (oid, beat)
        for mi, slots in enumerate(grouped):
            filled = {key: dict(slot) for key, slot in slots.items()}
            for vi in (0, 1):
                entries = [(at, *slot[vi]) for (at, rank), slot in sorted(slots.items()) if vi in slot]
                authored = {id(beat) for _, _, beat in entries}
                entries, count = _fill_export_silence(entries, measures[mi][0], f'{tid}-m{mi + 1}-v{vi}')
                generated_rests += count
                for at, occurrence, beat in entries:
                    if id(beat) in authored:
                        continue
                    # A generated rest may fill an unused voice slot, but may
                    # never collapse two separately authored TGBeat objects.
                    keys = sorted(key for key in filled if key[0] == at)
                    slot_key = next((key for key in keys if vi not in filled[key]),
                                    (at, max((key[1] for key in keys), default=-1) + 1))
                    filled.setdefault(slot_key, {})[vi] = (occurrence, beat)
            grouped[mi] = filled
        # An entirely empty first measure still needs TG's one-quarter origin.
        if not any(at == 0 for at, rank in grouped[0]):
            grouped[0][(Fraction(0), 0)] = {}
        for mi, slots in enumerate(grouped):
            m = _add(t, 'TGMeasure')
            own = (measures[mi][2].get('staff') or {}).get(tid, {})
            if own.get('key', {}).get('mode', 'major') != 'major' or own.get('clef', clef) not in CLEFS:
                _fail(tid, f'measure {mi + 1}: minor-mode or percussion clef change is not representable')
            mkey = own.get('key', key)
            _add(m, 'clef', own.get('clef', clef))
            _add(m, 'keySignature', mkey['fifths'] if mkey['fifths'] >= 0 else 7 - mkey['fifths'])
            for (at, rank), slot in sorted(slots.items()):
                b = _add(m, 'TGBeat')
                _add(b, 'preciseStart', _precise(at + 1, 'beat start'))
                for field in ('stroke', 'pick_stroke', 'chord'):
                    values = [beat[field] for _, beat in slot.values() if beat.get(field) is not None]
                    if any(value != values[0] for value in values[1:]):
                        _fail(tid, f'conflicting shared beat {field}')
                    if values:
                        if field == 'stroke':
                            _add(b, 'stroke', **values[0])
                        elif field == 'pick_stroke':
                            _add(b, 'pickStroke', values[0])
                        else:
                            chord = _add(b, 'chord')
                            _add(chord, 'name', values[0]['name'])
                            _add(chord, 'firstFret', values[0]['first_fret'])
                            for fret in values[0]['frets']:
                                _add(chord, 'string', fret if fret >= 0 else None)
                texts = {beat.get('text', '') for _, beat in slot.values()} - {''}
                if len(texts) > 1:
                    _fail(tid, 'two voice annotations at one timestamp cannot be represented')
                annotated = [vi for vi, (_, beat) in slot.items() if beat.get('text')]
                if annotated and annotated != [min(slot)]:
                    _fail(tid, 'TG beat text is shared; per-voice annotation ownership cannot be preserved')
                if texts:
                    _add(b, 'text', next(iter(texts)))
                for vi in (0, 1):
                    v = _add(b, 'voice')
                    if vi not in slot:
                        v.set('empty', 'true')
                        _add(v, 'duration', value=4)
                        continue
                    oid, beat = slot[vi]
                    written = beat['written']
                    d = _add(v, 'duration', value=written['value'])
                    if written.get('dots', 0):
                        d.set('dotted', ('dotted', 'doubleDotted')[written['dots'] - 1])
                    enters, times = written.get('tuplet', [1, 1])
                    _add(d, 'divisionType', enters=enters, times=times)
                    stem = beat.get('stem', track.get('stem', 'auto'))
                    if stem != 'auto':
                        v.set('direction', stem)
                    if not beat['notes']:
                        v.set('empty', 'false')
                    for note in beat['notes']:
                        supported = {'id', 'pitch', 'string', 'fret', 'velocity', 'volume', 'spelling',
                                     'instrument', 'channel', 'bend', 'tremolo_bar', 'harmonic',
                                     'trill', 'tremolo_picking', 'grace', *FLAGS.values()}
                        if set(note) - supported:
                            _fail(note['id'], f'unsupported native note metadata {sorted(set(note) - supported)}')
                        r = resolved[f'{oid}/{note["id"]}']
                        if r['string'] is None or r['fret'] is None:
                            _fail(note['id'], 'export needs resolved fingering')
                        if note.get('volume') is not None or 'instrument' in note:
                            _fail(note['id'], 'IT volume/instrument command is not representable')
                        alternative = False
                        if note.get('spelling') is not None:
                            tg_key = key['fifths'] if key['fifths'] >= 0 else 7 - key['fifths']
                            spelling = dict(step=note['spelling']['step'], alter=note['spelling'].get('alter', 0))
                            alternative = spelling != _tg_spelling(note['pitch'], tg_key, False)
                            if alternative and spelling != _tg_spelling(note['pitch'], tg_key, True):
                                _fail(note['id'], f'spelling {spelling["step"]}{spelling["alter"]:+d} is neither the '
                                      'key spelling TuxGuitar writes nor its alternative enharmonic')
                        if note.get('channel', r['ch']) != track['channels'][r['string'] - 1]:
                            _fail(note['id'], 'explicit channel override is not representable')
                        velocity = note.get('velocity')
                        if velocity is None or velocity == 0:
                            _fail(note['id'], 'export requires explicit nonzero MIDI velocity; no default is guessed')
                        _effects_compatible(note, note['id'])
                        n = _add(v, 'note', string=r['string'], value=r['fret'], velocity=velocity)
                        if alternative:
                            _add(n, 'alternativeEnharmonic')
                        if (oid, note['id']) in tied_in:
                            n.set('tiedNote', 'true')
                        for tag, field in FLAGS.items():
                            if note.get(field):
                                _add(n, tag)
                        if note.get('harmonic') is not None:
                            harmonic = note['harmonic']
                            _add(n, 'harmonic', type=next(k for k, v in HARMONICS.items() if v == harmonic['type']),
                                 data=harmonic.get('data', 0))
                        for tag, field in (('bend', 'bend'), ('tremoloBar', 'tremolo_bar')):
                            if note.get(field) is not None:
                                if not note[field]['points']:
                                    _fail(note['id'], 'empty curves are not preserved by the TG writer')
                                curve = _add(n, tag)
                                for p in note[field]['points']:
                                    _add(curve, 'point', **p)
                        if note.get('grace') is not None:
                            grace = note['grace']
                            _add(n, 'grace', fret=grace['fret'], duration=grace['value'], dynamic=grace['velocity'],
                                 transition=grace.get('transition', 'none'),
                                 onBeat=str(grace.get('on_beat', False)).lower(), dead=str(grace.get('dead', False)).lower())
                        if note.get('trill') is not None:
                            _add(n, 'trill', fret=note['trill']['fret'], duration=note['trill']['value'])
                        if note.get('tremolo_picking') is not None:
                            _add(n, 'tremoloPicking', duration=note['tremolo_picking']['value'])
    for t, m, b, old, new, _ in tglegacy.tg_starts(copy.deepcopy(target)):
        _fail(f'track {t}, measure {m}, beat {b}', 'TuxGuitar would delete this beat on opening: its measure has '
              'no beat at the start; add a rest' if new is None else f'TuxGuitar would move this beat from quarter '
              f'{old} to {new} on opening: none of its voices reaches its start; add rests')
    # XML readers normalize literal CR to LF, including inside text nodes.
    # Character references retain authored CR/CRLF without changing other text.
    xml = ET.tostring(root, encoding='utf-8', xml_declaration=True).replace(b'\r', b'&#13;')
    if len(xml) > MAX_XML:
        _fail('export', 'XML capacity exceeded')
    losses = []
    if version == '2.0':
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('version.txt', VERSION)
            z.writestr('content.xml', xml)
        data, label = output.getvalue(), 'TuxGuitar_file_format 2.0'
    else:
        data, losses = tglegacy.from_xml(target, version)
        label = 'TuxGuitar File Format ' + version
    read_tg(data)
    return data, dict(format=label, tracks=len(channels), measures=len(measures), generated_rests=generated_rests,
                      notes=len(resolved), losses=losses, warnings=[
                          'Sampled instruments and DSP are not embedded; explicit caller-selected TG programs/banks replace their sounds.',
                          'Untouched source MIDI volume/pan is retained; native audio uses the tracker mixer scale. Explicit mix edits use its rounded controller conversion.',
                          'TG uses fresh note/beat identities and authored measures; repeat/endings are retained, native pattern sharing and inheritance are not.',
                          *([f'{generated_rests} explicit rests added in the export to preserve silent gaps and pickup timing; the native score is unchanged.'] if generated_rests else []),
                          *clef_warnings, *(f'Not stored in {label}: {loss}.' for loss in losses)])
