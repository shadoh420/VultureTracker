"""Native PowerTab 1.7 (ptab-4) reader.

Binary fields follow TuxGuitar 2.1.0 PTInputStream/PTSongParser. Written repeats
remain native repeats instead of the upstream reader's flattened performance.
Unsupported musical directions/automatic accompaniment refuse explicitly.
"""
from fractions import Fraction
from pathlib import Path

from .tab_binary import Reader, normalize, written
from .tablature import duration_quarters


class PTReader(Reader):
    def string(self):
        size = self.u8()
        return self.text(self.u16() if size == 255 else size)

    def group(self, read):
        count = self.u16()
        if count:
            header = self.u16()
            if header == 65535:
                if self.u16() != 1:
                    self.fail('unsupported MFC object schema')
                self.text(self.u16())
        result = []
        for i in range(count):
            result.append(read())
            if i + 1 < count:
                self.u16()
        return result


def _info(r):
    classification = r.u8()
    m = {}
    if classification == 0:
        r.take(1)
        m['name'], m['artist'] = r.string(), r.string()
        release = r.u8()
        if release == 0:
            r.take(1)
            m['album'], m['date'] = r.string(), str(r.u16())
            r.take(1)
        elif release == 1:
            m['album'] = r.string()
            r.take(1)
        elif release == 2:
            m['album'] = r.string()
            day, month, year = r.u16(), r.u16(), r.u16()
            m['date'] = f'{year:04}-{month:02}-{day:02}'
        else:
            r.fail('unknown release type')
        if r.u8() == 0:
            m['author'] = r.string()
            lyricist = r.string()
            if lyricist:
                m['comments'] = 'Lyricist: ' + lyricist
        m['writer'] = r.string()
        m['transcriber'] = ' / '.join(filter(None, (r.string(), r.string())))
        m['copyright'] = r.string()
        m['comments'] = '\n'.join(filter(None, (m.get('comments', ''), r.string(), r.string(), r.string())))
    elif classification == 1:
        m['name'], m['album'] = r.string(), r.string()
        r.take(3)
        m['author'], m['comments'], m['copyright'] = r.string(), r.string(), r.string()
    else:
        r.fail('unknown song classification')
    return m


def _instrument(r, notices):
    number, name = r.u8(), r.string()
    program, volume, pan = r.u8(), r.u8(), r.u8()
    fx = r.take(4)
    capo = r.u8()
    r.string()
    notation = r.u8()
    tuning = list(r.take(r.u8()))
    if not 1 <= len(tuning) <= 25:
        r.fail('requires 1..25 strings per instrument')
    if volume > 127 or pan > 127:
        r.fail('volume and pan must be in 0..127')
    if any(fx):
        notices.append(f'{name}: source chorus/reverb/tremolo/phaser {list(fx)} are descriptive only; assign effects after import.')
    if notation:
        notices.append(f'{name}: music-notation offset/sharp-flat display {notation} is not retained.')
    return dict(number=number, name=name, program=program, volume=volume, pan=pan, tuning=tuning, capo=capo,
                clef='bass' if min(tuning) <= 34 else 'treble', measures=[])


def _bar(r):
    position, kind, key = r.u8(), r.u8(), r.u8()
    meter_data = r.u32() >> 24
    r.take(1)
    r.take(1)
    marker = r.string()
    result = dict(position=position, meter=[meter_data // 8 + 1, 2 ** (meter_data % 8)], marker=marker)
    if key:
        result['key_notice'] = key
    if kind >> 5 == 3:
        result['repeat_open'] = True
    if kind >> 5 == 4:
        result['close_previous'] = kind - 128
    return result


def _note(r):
    pos, flags, symbols = r.u8(), r.u16(), r.u8()
    fx = {}
    if flags & ~3:
        r.fail(f'unsupported note flags 0x{flags:04x}')
    if flags & 2:
        fx['deadNote'] = True
    for _ in range(symbols):
        symbol = r.take(4)
        if symbol[3] == 100:
            fx['slide'] = True
        elif symbol[3] == 101:
            bend = symbol[2] // 16 + 1
            curves = {1: [(0, 0), (6, 4), (12, 4)], 2: [(0, 0), (3, 4), (6, 4), (9, 0), (12, 0)],
                      3: [(0, 0), (6, 4), (12, 4)], 4: [(0, 4), (12, 4)],
                      5: [(0, 4), (4, 4), (8, 0), (12, 0)], 6: [(0, 8), (12, 8)],
                      7: [(0, 4), (4, 4), (8, 0), (12, 0)], 8: [(0, 4), (4, 4), (8, 0), (12, 0)]}
            if bend not in curves:
                r.fail('unknown bend symbol')
            fx['bend'] = curves[bend]
        else:
            r.fail(f'unsupported note symbol {symbol.hex()}')
    return dict(string=(pos >> 5) + 1, fret=pos & 31, tied=bool(flags & 1), effects=fx)


def _beat(r, staff, voice):
    position, beaming = r.u8(), r.u8() & 127
    r.take(1)
    flags = r.u8()
    r.take(1)
    flags3, value = r.u8(), r.u8()
    if flags3 & 1:
        r.fail('standalone grace beats are not yet representable')
    if flags3 & ~1 or flags & ~123:
        r.fail('unsupported beat flags')
    multirest = 1
    for _ in range(r.u8()):
        count = r.u16()
        r.take(1)
        kind = r.u8()
        if kind & 8:
            multirest = count
        else:
            r.fail(f'unsupported complex beat symbol {kind}')
    notes = r.group(lambda: _note(r))
    if flags & 24:
        for note in notes:
            note['effects']['vibrato'] = True
    result = dict(position=position, staff=staff, voice=voice, notes=notes,
                  written=written(value, 2 if flags & 2 else 1 if flags & 1 else 0,
                                  (beaming // 8 + 1, beaming % 8 + 1)), multirest=multirest)
    if flags & 96:
        result['stroke'] = 'down' if flags & 32 else 'up'
    return result


def _section(r, notices):
    r.take(16)
    last = r.u8()
    r.take(4)
    bars = [_bar(r)]
    if r.group(lambda: (r.u8(), r.take(r.u8() * 2))):
        r.fail('Da Capo/Segno/Coda/Fine directions are not yet representable')
    if r.group(lambda: r.take(7)):
        notices.append('Chord-symbol spelling without a diagram is not retained.')
    if r.group(lambda: r.take(6)):
        r.fail('rhythm slash accompaniment is not yet representable')
    beats = []
    staff_index = 0
    def staff():
        nonlocal staff_index
        i = staff_index
        staff_index += 1
        r.take(5)
        for voice in range(2):
            beats.extend(r.group(lambda: _beat(r, i, voice)))
    r.group(staff)
    bars.extend(r.group(lambda: _bar(r)))
    return dict(bars=bars, beats=beats, staffs=staff_index, final_close=last - 128 if last >> 5 == 4 else 0)


def _bank(r, notices):
    instruments = r.group(lambda: _instrument(r, notices))
    def chord():
        r.take(7)
        r.take(r.u8())
    if r.group(chord):
        notices.append('PowerTab chord-diagram library is not retained; the authored notes remain.')
    def floating():
        text = r.string()
        r.take(17)
        r.string()
        r.take(15)
        return text
    texts = r.group(floating)
    if texts:
        notices.append('Floating text retained in comments: ' + ' / '.join(texts))
    def guitar_in():
        section, staff, position = r.u16(), r.u8(), r.u8()
        r.take(1)
        return section, staff, position, r.u8()
    changes = r.group(guitar_in)
    def tempo():
        section, position, bpm, flags = r.u16(), r.u8(), r.u16(), r.u16()
        text = r.string()
        if flags & ~3:
            notices.append(f'Tempo marker options 0x{flags:04x} ({text}) are not retained.')
        return section, position, bpm, 'eighth' if flags & 1 else 'sixteenth' if flags & 2 else None
    tempos = r.group(tempo)
    if r.group(lambda: r.take(6)):
        r.fail('dynamic automation markers are not yet representable')
    symbols = r.group(lambda: (r.u16(), r.u8(), r.u32() >> 16))
    sections = r.group(lambda: _section(r, notices))
    return instruments, changes, tempos, symbols, sections


def read_ptb(data):
    r, notices = PTReader(data, 'PowerTab'), []
    if r.take(6) != b'ptab\x04\x00':
        r.fail('expected PowerTab ptab-4 format')
    metadata = _info(r)
    banks = [_bank(r, notices), _bank(r, notices)]
    r.end()
    all_tracks, global_headers = [], []
    for instruments, changes, tempos, symbols, sections in banks:
        if not sections:
            continue
        if not instruments:
            r.fail('staff data without instrument definitions')
        info_map = {t['number']: t for t in instruments}
        if len(info_map) != len(instruments):
            r.fail('duplicate instrument number')
        headers, staff_map, tempo, swing = [], {}, 120, None
        for si, section in enumerate(sections):
            for staff in range(section['staffs']):
                staff_map.setdefault(staff, min(instruments, key=lambda item: item['number']))
            positions = sorted({b['position'] for b in section['bars']} | {b['position'] for b in section['beats']} |
                               {p for s, _, p, _ in changes if s == si} | {p for s, p, _, _ in tempos if s == si} |
                               {p for s, p, _ in symbols if s == si})
            clocks, current = {}, None
            for pos in positions:
                bar = next((b for b in section['bars'] if b['position'] == pos), None)
                if bar:
                    if bar.get('close_previous'):
                        if not headers:
                            r.fail('repeat close before first bar')
                        headers[-1]['repeat_close'] = max(0, bar['close_previous'] - 1)
                    current = len(headers)
                    h = dict(meter=bar['meter'], tempo=tempo)
                    if bar.get('key_notice'):
                        notices.append(f'PowerTab key-signature code {bar["key_notice"]} is not retained.')
                    for field in ('repeat_open', 'marker'):
                        if bar.get(field):
                            h[field] = bar[field]
                    headers.append(h)
                    for t in instruments:
                        t['measures'].append([])
                    clocks = {}
                if current is None:
                    r.fail('notes/events before initial bar')
                for s, staff, p, info in changes:
                    if (s, p) == (si, pos):
                        matching = [t for number, t in info_map.items() if (1 << number) & info]
                        if len(matching) != 1:
                            r.fail('guitar-in references unknown instrument')
                        staff_map[staff] = matching[0]
                for s, p, bpm, feel in tempos:
                    if (s, p) == (si, pos):
                        if any(clocks.values()):
                            r.fail('mid-measure tempo changes are not yet representable')
                        tempo = bpm or tempo
                        swing = feel
                        headers[current]['tempo'] = tempo
                if swing:
                    headers[current]['swing'] = swing
                for s, p, mask in symbols:
                    if (s, p) == (si, pos):
                        headers[current]['endings'] = [i + 1 for i in range(7) if mask & (1 << i)]
                        if mask & ~127:
                            r.fail('ending mask exceeds supported endings 1..7')
                for beat in sorted((b for b in section['beats'] if b['position'] == pos), key=lambda b: (b['staff'], b['voice'])):
                    key = beat['staff'], beat['voice']
                    t = staff_map[beat['staff']]
                    if beat['multirest'] != 1:
                        r.fail('multi-measure rests require explicit bars; this form is not yet representable')
                    out = {k: v for k, v in beat.items() if k not in ('position', 'staff', 'multirest')}
                    out['at'] = clocks.get(key, Fraction(0))
                    clocks[key] = out['at'] + duration_quarters(out['written'])
                    t['measures'][current].append(out)
            if section['final_close']:
                headers[-1]['repeat_close'] = max(0, section['final_close'] - 1)
        if not global_headers:
            global_headers = headers
        else:
            if len(headers) != len(global_headers) or any(a['meter'] != b['meter'] for a, b in zip(headers, global_headers)):
                r.fail('guitar and bass sections disagree on written measure layout')
            for a, b in zip(global_headers, headers):
                for key in ('repeat_open', 'repeat_close', 'endings'):
                    if a.get(key) != b.get(key):
                        r.fail('guitar and bass sections disagree on repeat structure')
        all_tracks.extend(t for t in instruments if any(t['measures']))
    return normalize('PowerTab', metadata, global_headers, all_tracks, notices)


def import_ptb(src, song_path, samples_dir):
    from .gpimport import publish_native_score
    song, notices = read_ptb(Path(src).read_bytes())
    return publish_native_score(song, src, song_path, samples_dir, notices)
