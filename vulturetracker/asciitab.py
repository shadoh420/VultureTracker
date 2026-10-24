"""ASCII tablature (.tab) from a TuxGuitar 2.0 file, as TuxGuitar's own ASCII writer draws it.

A port of ASCIITabOutputStream and ASCIIOutputStream (TuxGuitar-ascii, pinned
2c46e2a1cccdfdfa6e6f2692f241bd60bf418129, LGPL-2.1; licenses/TuxGuitar-notation-NOTICE.txt) that reads the TG 2.0
XML VultureTracker's own .tg export writes, so its measures and beats are the ones TuxGuitar reads.
Lines end in LF; TuxGuitar's println ends them in the platform's separator (CRLF on Windows).
"""
from fractions import Fraction

from .tgimport import QUARTER, _xml

TONIC_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
MAX_LINE_LENGTH = 80
QUARTER_TIME = 960   # TGDuration.QUARTER_TIME, also the first measure's start tick


class _Out:
    """ASCIIOutputStream: text plus the column (x) the drawing has reached."""
    def __init__(self):
        self.parts, self.x = [], 0

    def chord(self, name):
        self.parts.append(name); self.x += len(name)
        return len(name)

    def segments(self, count):
        count = max(0, count); self.x += count; self.parts.append('-' * count)

    def tune(self, tune, width):
        self.space(width - len(tune)); self.x += len(tune); self.parts.append(tune)

    def bar(self):
        self.x += 1; self.parts.append('|')

    def line(self, text=''):
        self.x = 0; self.parts.append(text + '\n')

    def space(self, count=1):
        self.x += count; self.parts.append(' ' * max(0, count))   # Java moves x even by a negative count


def _movements(points):
    """TGEffectBend.updateMovements: amplitudes of the bend's (+) and release's (-) movements."""
    values, movements = [p[1] for p in points], []
    if len(values) < 2:
        return movements
    start, current = values[0], values[1]
    for following in values[2:]:
        if (following - current) * (current - start) < 0:
            movements.append(current if current - start > 0 else -start)
            start = current
        current = following
    if current - start > 0:
        movements.append(current)
    elif current - start < 0:
        movements.append(-start)
    return movements


def _note_text(note, following):
    """ASCIIOutputStream.drawNote's text for a note (None draws nothing)."""
    if note is None:
        return ''
    fret, text = note['fret'], ''
    bend = note['bend']
    if note['dead']:
        text = 'X'
    elif bend is not None and not _movements(bend):
        text = 'H'
    else:
        text = str(fret)
    if note['hammer'] and following is not None:
        text += 'h' if following['fret'] > fret else 'p'
    if note['slide'] and following is not None:
        text += '/' if following['fret'] > fret else '\\'
    if bend is not None:
        movements = _movements(bend)
        if movements:
            target = fret + abs(movements[0]) // 2   # Java int division of a nonnegative value
            text = f'{target}r{text}' if movements[0] < 0 else f'{text}b{target}'
    return text


def _text(node, name):
    child = node.find(name)
    return '' if child is None or child.text is None else child.text


def _model(song):
    starts, start, numerator, denominator = [], QUARTER_TIME, 4, 4
    for header in song.findall('TGMeasureHeader'):
        signature = header.find('timeSignature')   # absent: the previous header's, 4/4 at first (as TG's reader)
        if signature is not None:
            numerator, denominator = int(signature.get('numerator')), int(signature.get('denominator'))
        length = numerator * (QUARTER_TIME * 4 // denominator)
        starts.append((start, length)); start += length
    tracks = []
    for number, track in enumerate(song.findall('TGTrack'), 1):
        strings = [int(s.text) for s in track.findall('TGString')]
        measures = []
        for (mstart, mlength), measure in zip(starts, track.findall('TGMeasure')):
            beats = []
            for beat in measure.findall('TGBeat'):
                tick = QUARTER_TIME * Fraction(int(beat.find('preciseStart').text), QUARTER)   # TGDuration.toTime
                chord = beat.find('chord')
                voices = []
                for voice in beat.findall('voice'):
                    if voice.get('empty') == 'true':
                        voices.append(None)
                        continue
                    notes = []
                    for n in voice.findall('note'):
                        bend = n.find('bend')
                        notes.append(dict(string=int(n.get('string')), fret=int(n.get('value')),
                                          dead=n.find('deadNote') is not None, hammer=n.find('hammer') is not None,
                                          slide=n.find('slide') is not None,
                                          bend=None if bend is None else [(int(p.get('position')), int(p.get('value')))
                                                                          for p in bend.findall('point')]))
                    voices.append(notes)
                beats.append(dict(start=int(tick), chord=None if chord is None else _text(chord, 'name'), voices=voices))
            measures.append(dict(start=mstart, length=mlength, beats=beats))
        tracks.append(dict(number=number, name=_text(track, 'name'), strings=strings, measures=measures))
    return dict(name=_text(song, 'name'), artist=_text(song, 'artist'), album=_text(song, 'album'),
                author=_text(song, 'author'), tracks=tracks)


def _first(beats):
    return min(beats, key=lambda b: b['start']) if beats else None   # min keeps the first of equal starts


def _next(beats, beat):
    later = [b for b in beats if b['start'] > beat['start']]
    return min(later, key=lambda b: b['start']) if later else None


def _note(beat, string):
    """TGMeasureManager.getNote: the first nonempty voice's note on that string."""
    if beat is None:
        return None
    for notes in beat['voices']:
        if notes is not None:
            for note in notes:
                if note['string'] == string:
                    return note
    return None


def _spacing(length):
    for limit, spacing in ((QUARTER_TIME // 8, 1), (QUARTER_TIME // 4, 2), (QUARTER_TIME // 2, 3),
                           (QUARTER_TIME, 4), (QUARTER_TIME * 2, 5)):
        if length <= limit:
            return spacing
    return 6


def _widest(beat, following, strings):
    widest = len(beat['chord']) if beat['chord'] is not None else 0
    for s in range(1, strings + 1):
        widest = max(widest, len(_note_text(_note(beat, s), _note(following, s))))
    return widest


def _width(measure, beat, following, strings):
    length = (following['start'] if following else measure['start'] + measure['length']) - beat['start']
    width = _spacing(length)
    return max(width, _widest(beat, following, strings) + 1)


def _draw_measure(out, measure, string, strings):
    out.bar(); out.segments(1)
    beat = _first(measure['beats'])
    while beat is not None:
        following = _next(measure['beats'], beat)
        text = _note_text(_note(beat, string + 1), _note(following, string + 1))
        out.parts.append(text); out.x += len(text)
        out.segments(_width(measure, beat, following, strings) - len(text))
        beat = following


def _draw_track(out, track):
    out.line()
    out.line(f"Track {track['number']}: {track['name']}")
    tuning = [TONIC_NAMES[value % 12] for value in track['strings']]
    width = max([1, *map(len, tuning)])
    strings, measures = len(tuning), track['measures']
    following, eof = 0, False
    while not eof:
        out.line()
        index = following
        out.tune('', width)
        for measure in measures[index:]:
            out.space(); out.space()
            beat = _first(measure['beats'])
            while beat is not None:
                after = _next(measure['beats'], beat)
                drawn = out.chord(beat['chord'] or '')
                out.space(_width(measure, beat, after, strings) - drawn)
                beat = after
            if out.x > MAX_LINE_LENGTH:
                break
        out.line()
        for string in range(strings):
            out.tune(tuning[string], width)
            for j in range(index, len(measures)):
                _draw_measure(out, measures[j], string, strings)
                following = j + 1
                eof = j == len(measures) - 1
                if out.x > MAX_LINE_LENGTH:
                    break
            out.bar()
            out.line()
        out.line()
        if not measures:
            break   # TuxGuitar always has a measure; never loop on an empty track
    out.line()


def tg_to_ascii(data):
    """The ASCII tab text of a TuxGuitar 2.0 file's bytes."""
    song = _model(_xml(data))
    out = _Out()
    for label in ('Title', 'Artist', 'Album', 'Author'):
        out.line(f"{label}: {song[label.lower() if label != 'Title' else 'name']}")
    for track in song['tracks']:
        out.line()
        _draw_track(out, track)
        out.line()
    return ''.join(out.parts)
