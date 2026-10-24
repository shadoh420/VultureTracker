"""Native score -> LilyPond and MusicXML text, as TuxGuitar 2.1.0 writes them (ASCII tab: asciitab.py).

Writers ported 2026-10-20 from TuxGuitar 2c46e2a1cccdfdfa6e6f2692f241bd60bf418129, LGPL-2.1.
Copyright (C) 2005-2022 Julian Casadesus; 2023-2025 guiv42, helge17; MusicXML lyrics Menno Vossen.
Sources: common/TuxGuitar-lilypond
(LilypondOutputStream, LilypondSettings), desktop/TuxGuitar-musicxml (MusicXMLWriter,
MusicXMLLyricWriter), TuxGuitar-lib (TGMusicKeyUtils, TGDuration, TGLyric) and
TuxGuitar-gm-utils (GMChannelRouter).
License: https://github.com/helge17/tuxguitar/blob/2c46e2a1cccdfdfa6e6f2692f241bd60bf418129/docs/LICENSE
The native document is read
into the TG song shape the .tg reader would build from tgimport.native_to_tg, then
each writer is ported as written. Every function returns (text, report); report
lists each native feature the format does not carry as a loss, never silently.
Text uses LF line endings; callers write it with newline='\\n'.
"""
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
import xml.etree.ElementTree as ET

import numpy

from .tablature import TempoClock, authoring_view, duration_quarters, is_percussion, repeat_projection

QUARTER_TIME = 960


@dataclass
class _Voice:
    index: int
    empty: bool = True
    value: int = 4
    dots: int = 0
    enters: int = 1
    times: int = 1
    notes: list = field(default_factory=list)
    beat: object = None

    def time(self):
        # TGDuration.getTime, integer arithmetic order kept
        t = int(QUARTER_TIME * (4.0 / self.value))
        if self.dots == 1:
            t += t // 2
        elif self.dots == 2:
            t += (t // 4) * 3
        return t * self.times // self.enters

    def same_duration(self, other):
        return (self.value, self.dots, self.enters, self.times) == (other.value, other.dots, other.enters, other.times)

    def is_rest(self):
        return not self.notes


@dataclass
class _Note:
    string: int
    fret: int
    velocity: int
    tied: bool
    fx: dict
    voice: object = None


@dataclass
class _Beat:
    start: int
    voices: list
    chord: dict = None
    text: str = None
    stroke: dict = None
    pick: str = None
    measure: object = None

    def is_rest(self):
        return all(v.empty or v.is_rest() for v in self.voices)


@dataclass
class _Measure:
    number: int
    start: int
    numerator: int
    denominator: int
    tempo: int
    clef: str
    key: int
    repeat_open: bool = False
    repeat_close: int = 0
    alternative: int = 0
    marker: str = None
    beats: list = field(default_factory=list)
    track: object = None

    def length(self):
        return QUARTER_TIME * 4 * self.numerator // self.denominator


@dataclass
class _Track:
    number: int
    name: str
    strings: list
    offset: int
    percussion: bool
    lyrics_from: int
    lyrics: str
    tid: str = None
    measures: list = field(default_factory=list)


class _Losses:
    """One entry per (scope, feature); scope is 'song', 'measures' or a track id, first names one place."""
    def __init__(self):
        self.entries = {}

    def add(self, where, feature, reason):
        if where.startswith('track '):
            scope = where.split(' beat ')[0].removeprefix('track ')
        else:
            scope = 'measures' if where.startswith('measure ') else where
        entry = self.entries.setdefault((scope, feature), dict(scope=scope, feature=feature, reason=reason,
                                                               count=0, first=where))
        entry['count'] += 1

    def report(self):
        return list(self.entries.values())


def _model(song, raw_patterns):
    """TG song shape from the native document; raises only for structure TG cannot hold."""
    if 'score' not in song:
        raise ValueError('Notation export: song has no native score')
    repeated = repeat_projection(song, raw_patterns, 44100)
    view = repeated.source_view if repeated is not None else authoring_view(song, raw_patterns)
    score, module = song['score'], song.get('module', {})
    occurrences = {o['id']: Fraction(*o['at']) for o in view['occurrences']}
    spans = sorted((occurrences[m['from']['occurrence']] + Fraction(*m['from']['at']),
                    occurrences[m['to']['occurrence']] + Fraction(*m['to']['at']), m)
                   for m in score.get('measures', []))
    if not spans or spans[0][0] != 0 or spans[-1][1] != Fraction(*view['duration']) or any(
            a[1] != b[0] for a, b in zip(spans, spans[1:])):
        raise ValueError('Notation export: explicit measures must cover the complete arrangement without gaps')
    clock = TempoClock(module.get('tempo', 125), view.get('tempos'))
    resolved = {p['id']: p for p in view['positions'] if p['kind'] == 'note'}
    tied_in = {(t['to']['occurrence'], t['to']['note']) for t in score.get('ties', [])}
    seen = []   # (track id, oid, beat, notes) for the loss scan
    tracks = []
    for number, (tid, spec) in enumerate(score['tracks'].items(), 1):
        lyric = spec.get('lyrics', {'from_measure': 1, 'text': ''})
        track = _Track(number, spec.get('name', tid), list(spec['tuning']), spec.get('capo', 0),
                       is_percussion(spec), lyric['from_measure'], lyric['text'], tid)
        clef = spec.get('clef', 'treble')
        clef = 'treble' if clef == 'percussion' else clef
        fifths = spec.get('key', {}).get('fifths', 0)
        key = fifths if fifths >= 0 else 7 - fifths
        for mi, (a, _, m) in enumerate(spans):
            measure = _Measure(mi + 1, QUARTER_TIME + int(a * QUARTER_TIME), m['meter'][0], m['meter'][1],
                               clock.tempo_at(a), clef, key, bool(m.get('repeat_open')), m.get('repeat_close', 0),
                               sum(1 << (n - 1) for n in m.get('endings', [])),
                               m['marker']['title'] if m.get('marker') else None, track=track)
            track.measures.append(measure)
        slots = [{} for _ in spans]
        for oid, pname in zip(score['order_ids'], song['orders']):
            for beat in score['patterns'].get(str(pname), {}).get('beats', []):
                if beat['track'] != tid:
                    continue
                at = occurrences[oid] + Fraction(*beat['at'])
                end = at + duration_quarters(beat['written'])
                mi = next((i for i, (a, b, _) in enumerate(spans) if a <= at < b), None)
                if mi is None or end > spans[mi][1]:
                    raise ValueError(f"Notation export: {beat['id']}: written beat crosses a measure boundary")
                slots[mi].setdefault((at, beat.get('cohort', 0)), {})[beat.get('voice', 0)] = (oid, beat)
        # The TG reader keeps the first measure's one-quarter origin beat.
        if not any(at == 0 for at, _ in slots[0]):
            slots[0][(Fraction(0), 0)] = {}
        for mi, slot_map in enumerate(slots):
            measure = track.measures[mi]
            for (at, _), slot in sorted(slot_map.items()):
                beat = _Beat(QUARTER_TIME + int(at * QUARTER_TIME), [_Voice(0), _Voice(1)], measure=measure)
                for vi, voice in enumerate(beat.voices):
                    voice.beat = beat
                    if vi not in slot:
                        continue
                    oid, source = slot[vi]
                    written = source['written']
                    voice.empty = False
                    voice.value, voice.dots = written['value'], written.get('dots', 0)
                    voice.enters, voice.times = written.get('tuplet', [1, 1])
                    kept = []
                    for note in source['notes']:
                        r = resolved[f"{oid}/{note['id']}"]
                        if r['string'] is None or r['fret'] is None:
                            kept.append(None)
                            continue
                        n = _Note(r['string'], r['fret'], note.get('velocity'), (oid, note['id']) in tied_in,
                                  note, voice)
                        voice.notes.append(n)
                        kept.append(n)
                    seen.append((tid, oid, source, kept))
                    for key_name in ('chord', 'text', 'stroke', 'pick_stroke'):
                        value = source.get(key_name)
                        if value is not None and value != '':
                            setattr(beat, 'pick' if key_name == 'pick_stroke' else key_name, value)
                measure.beats.append(beat)
        tracks.append(track)
    # Midmeasure tempo changes: TG headers carry one tempo per measure.
    starts = {a for a, _, _ in spans}
    for change in view.get('tempos', [])[1:]:
        if Fraction(*change['at']) not in starts:
            seen.append(('song', None, {'tempo_change': change}, []))
    credits = score.get('metadata', {})
    return dict(song=song, view=view, tracks=tracks, spans=spans, seen=seen,
                title=credits.get('title', module.get('title', '')), credits=credits)


# Native features per format: (carried?) -> loss reason when not carried.
_NOTE_FLAGS = ('staccato', 'palm_mute', 'let_ring', 'dead', 'vibrato', 'slide', 'ghost', 'accent', 'heavy_accent',
               'hammer', 'fade_in', 'tapping', 'slapping', 'popping')
_NOTE_VALUES = ('bend', 'tremolo_bar', 'harmonic', 'trill', 'tremolo_picking', 'grace', 'spelling', 'volume',
                'instrument', 'channel')
_CARRIED = {
    'lilypond': {'staccato', 'palm_mute', 'dead', 'vibrato', 'slide', 'ghost', 'accent', 'heavy_accent', 'hammer',
                 'bend', 'harmonic', 'trill', 'tremolo_picking', 'grace', 'rhythm', 'voices', 'ties', 'rests',
                 'lyrics', 'text', 'chord_frets', 'stroke', 'clef', 'key', 'meter', 'tempo', 'repeats', 'tuning',
                 'name', 'percussion'},
    'musicxml': {'staccato', 'palm_mute', 'let_ring', 'dead', 'slide', 'ghost', 'accent', 'heavy_accent', 'hammer',
                 'tapping', 'bend', 'harmonic', 'trill', 'tremolo_picking', 'velocity', 'rhythm', 'voices', 'ties',
                 'rests', 'lyrics', 'pick_stroke', 'clef', 'key', 'meter', 'tempo', 'repeats', 'marker', 'capo',
                 'tuning', 'name', 'percussion'},
}
_REASONS = {
    'staccato': 'staccato articulation', 'palm_mute': 'palm mute', 'let_ring': 'let ring', 'dead': 'dead note',
    'vibrato': 'vibrato', 'slide': 'slide', 'ghost': 'ghost note', 'accent': 'accent', 'heavy_accent': 'heavy accent',
    'hammer': 'hammer-on/pull-off', 'fade_in': 'fade-in', 'tapping': 'tapping', 'slapping': 'slapping',
    'popping': 'popping', 'bend': 'bend curve', 'tremolo_bar': 'tremolo bar curve', 'harmonic': 'harmonic',
    'trill': 'trill', 'tremolo_picking': 'tremolo picking', 'grace': 'grace note',
    'spelling': 'explicit enharmonic spelling (the writer spells from the key signature)',
    'volume': 'tracker volume command', 'instrument': 'tracker instrument override',
    'channel': 'playback channel override', 'velocity': 'note velocity', 'rhythm': 'written durations',
    'voices': 'second voice (merged into one tab line)', 'ties': 'ties (tied notes repeat their fret)',
    'rests': 'rests', 'lyrics': 'lyrics', 'text': 'beat text', 'chord_name': 'chord name',
    'chord_frets': 'chord diagram frets', 'stroke': 'strum direction and speed', 'pick_stroke': 'pick stroke',
    'stem': 'stem direction', 'color': 'track color', 'clef': 'clef', 'key': 'key signature',
    'minor': 'minor mode (TG key signatures carry no mode)', 'meter': 'time signature', 'tempo': 'tempo',
    'tempo_change': 'midmeasure tempo change (TG holds one tempo per measure)', 'repeats': 'repeats and endings',
    'marker': 'measure marker', 'swing': 'swing feel', 'capo': 'capo', 'negative_capo': 'negative capo offset',
    'message': 'song message', 'unfingered': 'note without a string/fret (omitted)',
    'tracker': 'residual tracker commands', 'sound': 'samples, instruments and mix (not notation)',
    'velocity_default': 'note without velocity (written as TG default 95)',
    'setting_track': 'track not selected by the LilyPond track setting',
    'setting_measures': 'measures outside the LilyPond measure range',
    'setting_score': 'standard notation staff (score setting off)',
    'setting_tablature': 'tablature staff (tablature setting off)',
    'setting_text': 'beat text (text setting off)', 'setting_chords': 'chord diagrams (chord diagram setting off)',
    'setting_lyrics': 'lyrics (lyrics setting off)', 'setting_name': 'track name (track name setting off)',
}


def _losses(model, fmt, raw_patterns):
    carried, out = _CARRIED[fmt], _Losses()

    def lose(where, feature):
        if feature not in carried:
            out.add(where, feature, _REASONS[feature])

    score, module = model['song']['score'], model['song'].get('module', {})
    out.add('song', 'sound', _REASONS['sound'])
    carried_credits = ({'title', 'author', 'writer', 'copyright'} if fmt == 'musicxml'
                       else {'title', 'author'} if fmt == 'lilypond' else {'title'})
    omitted_credits = [key for key, value in score.get('metadata', {}).items() if value and key not in carried_credits]
    if module.get('message') or omitted_credits:
        out.add('song', 'message', _REASONS['message'] + (': ' + ', '.join(omitted_credits) if omitted_credits else ''))
    if any(not c.is_empty() and not (c.note is None and not c.instrument and c.volcmd is None and c.effect == 20)
           for p in raw_patterns for row in p.rows for c in row):
        out.add('song', 'tracker', _REASONS['tracker'])
    for _, _, m in model['spans']:
        where = f"measure {m['id']}"
        lose(where, 'meter')
        if m.get('repeat_open') or m.get('repeat_close') or m.get('endings'):
            lose(where, 'repeats')
        if m.get('marker'):
            lose(where, 'marker')
        if m.get('swing', 'none') != 'none':
            out.add(where, 'swing', _REASONS['swing'])
    lose('song', 'tempo')
    for tid, spec in score['tracks'].items():
        where = f'track {tid}'
        if spec.get('lyrics', {}).get('text'):
            lose(where, 'lyrics')
        if 'color' in spec:
            out.add(where, 'color', _REASONS['color'])
        if spec.get('key', {}).get('mode') == 'minor':
            out.add(where, 'minor', _REASONS['minor'])
        if spec.get('key', {}).get('fifths', 0):
            lose(where, 'key')
        if spec.get('clef', 'treble') != 'treble':
            lose(where, 'clef')
        if spec.get('stem', 'auto') != 'auto':
            out.add(where, 'stem', _REASONS['stem'])
        if spec.get('capo', 0) > 0:
            lose(where, 'capo')
        elif spec.get('capo', 0) < 0:
            out.add(where, 'negative_capo', _REASONS['negative_capo'])
    for tid, oid, beat, kept in model['seen']:
        if tid == 'song':
            out.add('song', 'tempo_change', _REASONS['tempo_change'])
            continue
        where = f"track {tid} beat {oid}/{beat['id']}"
        if beat.get('cohort', 0):
            out.add(where, 'cohort', 'independent coincident beat identity for subsequent editing')
        lose(where, 'rhythm')
        if beat.get('voice', 0):
            lose(where, 'voices')
        if not beat['notes']:
            lose(where, 'rests')
        if beat.get('text'):
            lose(where, 'text')
        if beat.get('chord') is not None:
            if beat['chord']['name']:
                lose(where, 'chord_name')
            lose(where, 'chord_frets')
        if beat.get('stroke') is not None:
            lose(where, 'stroke')
        if beat.get('pick_stroke') is not None:
            lose(where, 'pick_stroke')
        if beat.get('stem', 'auto') != 'auto':
            out.add(where, 'stem', _REASONS['stem'])
        for note, n in zip(beat['notes'], kept):
            if n is None:
                out.add(where, 'unfingered', _REASONS['unfingered'])
                continue
            if n.tied:
                lose(where, 'ties')
            lose(where, 'velocity')
            if n.velocity is None and fmt == 'musicxml':
                out.add(where, 'velocity_default', _REASONS['velocity_default'])
            for flag in _NOTE_FLAGS:
                if note.get(flag):
                    lose(where, flag)
            for value in _NOTE_VALUES:
                if note.get(value) is not None:
                    lose(where, value)
    return out.report()


def _report(model, fmt, raw_patterns, **extra):
    return dict(format=fmt, tracks=len(model['tracks']), measures=len(model['spans']),
                notes=sum(len(v.notes) for t in model['tracks'] for m in t.measures for b in m.beats
                          for v in b.voices),
                losses=_losses(model, fmt.split()[0].lower(), raw_patterns), **extra)


# ---------------------------------------------------------------- shared TG helpers

def _is_bend(fx):
    return fx.get('bend') is not None and bool(fx['bend']['points'])


def _first_beat(beats):
    first = None
    for b in beats:
        if first is None or b.start < first.start:
            first = b
    return first


def _next_beat(beats, beat):
    nxt = None
    for b in beats:
        if b.start > beat.start and (nxt is None or b.start < nxt.start):
            nxt = b
    return nxt


# ---------------------------------------------------------------- LilyPond

LILYPOND_DEFAULTS = dict(track=-1, measureFrom=-1, measureTo=-1, score=True, tablature=True, text=True, lyrics=True,
                         chordDiagram=True, trackName=True, trackGroup=False, version='2.14.0')
_LY_SHARP = ['c', 'cis', 'd', 'dis', 'e', 'f', 'fis', 'g', 'gis', 'a', 'ais', 'b']
_LY_FLAT = ['c', 'des', 'd', 'ees', 'e', 'f', 'ges', 'g', 'aes', 'a', 'bes', 'b']
_LY_KEYS = ['c', 'g', 'd', 'a', 'e', 'b', 'fis', 'cis', 'f', 'bes', 'ees', 'aes', 'des', 'ges', 'ces']


def _lily_settings(settings):
    """LilypondSettings: TG's defaults, then check() (both staves off -> both on)."""
    if settings is not None and not isinstance(settings, dict):
        raise ValueError('LilyPond settings must be an object')
    merged = dict(LILYPOND_DEFAULTS)
    unknown = set(settings or {}) - set(merged)
    if unknown:
        raise ValueError(f'LilyPond settings: unknown {sorted(unknown)}')
    for key, value in (settings or {}).items():
        default = LILYPOND_DEFAULTS[key]
        if isinstance(default, bool):
            if value in ('true', 'false'):
                value = value == 'true'
            if type(value) is not bool:
                raise ValueError(f'LilyPond setting {key}: expected a boolean')
        elif isinstance(default, int):
            if isinstance(value, str) and value.lstrip('-').isdigit():
                value = int(value)
            if type(value) is not int or value < -1:
                raise ValueError(f'LilyPond setting {key}: expected an integer >= -1')
        elif not isinstance(value, str) or not value:
            raise ValueError('LilyPond setting version: expected a version string')
        merged[key] = value
    if not merged['score'] and not merged['tablature']:
        merged['score'] = merged['tablature'] = True
    return merged


def _base26(value):
    result, base = '', value
    while base > 25:
        result = chr(base % 26 + ord('A')) + result
        base = base // 26 - 1
    return chr(base + ord('A')) + result


def _older(version, than):
    """TG compares LilyPond versions with String.compareTo."""
    return version < than


def _lily_string(value):
    """Keep user-supplied header text inside one LilyPond quoted string."""
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\r', ' ').replace('\n', ' ')


class _Lily:
    def __init__(self, model, settings):
        self.model, self.s, self.parts = model, settings, []
        self.alt_open, self.alt_number = False, 0
        self.reset()

    def reset(self):
        # LilypondTempData.reset leaves the alternative state alone.
        self.multiple, self.repeat_count, self.repeat_open, self.division_open = False, 0, False, False
        self.skipped = []

    def p(self, text):
        self.parts.append(text)

    def ln(self, text=''):
        self.parts.append(text + '\n')

    @staticmethod
    def ind(level):
        return '   ' * level

    @staticmethod
    def boolean(value):
        return '#t' if value else '#f'

    def title_on_group(self):
        return self.s['trackName'] and self.s['trackGroup'] and self.s['track'] == -1 and len(self.model['tracks']) > 1

    def write(self):
        ind, s, b = self.ind, self.s, self.boolean
        self.ln('#(define (tie::tab-clear-tied-fret-numbers grob)')
        self.ln(ind(1) + '(let* ((tied-fret-nr (ly:spanner-bound grob RIGHT)))')
        self.ln(ind(2) + "(ly:grob-set-property! tied-fret-nr 'transparent #t)))")
        self.ln()
        self.ln('\\version "' + s['version'] + '"')
        self.ln('\\paper {')
        self.ln(ind(1) + 'indent = #' + ('30' if self.title_on_group() else '0'))
        self.ln(ind(1) + ('printallheaders' if _older(s['version'], '2.11.60') else 'print-all-headers') + ' = #' + b(True))
        self.ln(ind(1) + 'ragged-right = #' + b(False))
        self.ln(ind(1) + 'ragged-bottom = #' + b(True))
        self.ln('}')
        self.ln('\\layout {')
        self.ln(ind(1) + '\\context { \\Score')
        self.ln(ind(2) + "\\override MetronomeMark #'padding = #'5")
        self.ln(ind(1) + '}')
        self.ln(ind(1) + '\\context { \\Staff')
        self.ln(ind(2) + "\\override TimeSignature #'style = #'numbered")
        self.ln(ind(2) + "\\override StringNumber #'transparent = #" + b(True))
        self.ln(ind(1) + '}')
        self.ln(ind(1) + '\\context { \\TabStaff')
        self.ln(ind(2) + "\\override TimeSignature #'style = #'numbered")
        self.ln(ind(2) + "\\override Stem #'transparent = #" + b(s['score']))
        self.ln(ind(2) + "\\override Beam #'transparent = #" + b(s['score']))
        self.ln(ind(2) + "\\override Tie  #'after-line-breaking = #tie::tab-clear-tied-fret-numbers")
        self.ln(ind(1) + '}')
        if s['score']:
            self.ln(ind(1) + '\\context { \\TabVoice')
            self.ln(ind(2) + "\\override Tie #'stencil = ##f")
            self.ln(ind(1) + '}')
        self.ln(ind(1) + '\\context { \\StaffGroup')
        self.ln(ind(2) + '\\consists "Instrument_name_engraver"')
        self.ln(ind(1) + '}')
        self.ln('}')
        if _older(s['version'], '2.13.17'):
            self.ln('deadNote = #(define-music-function (parser location note) (ly:music?)')
            self.ln(ind(1) + "(set! (ly:music-property note 'tweaks)")
            self.ln(ind(2) + "(acons 'stencil ly:note-head::print")
            self.ln(ind(3) + "(acons 'glyph-name \"2cross\"")
            self.ln(ind(4) + "(acons 'style 'special")
            self.ln(ind(5) + "(ly:music-property note 'tweaks)))))")
            self.ln(ind(1) + 'note)')
            self.ln()
            self.ln('palmMute = #(define-music-function (parser location note) (ly:music?)')
            self.ln(ind(1) + "(set! (ly:music-property note 'tweaks)")
            self.ln(ind(2) + "(acons 'style 'do (ly:music-property note 'tweaks)))")
            self.ln(ind(1) + 'note)')
            self.ln()
        for i, track in enumerate(self.model['tracks']):
            tid = 'Track' + _base26(i)
            self.reset()
            self.music(track, tid)
            self.lyrics(track, tid)
            self.staff(track, tid, tab=False)
            self.staff(track, tid, tab=True)
            self.staff_group(track, tid)
        self.song()
        return ''.join(self.parts)

    def header(self, instrument, indent):
        ind = self.ind
        self.ln(ind(indent) + '\\header {')
        self.ln(ind(indent + 1) + 'title = "' + _lily_string(self.model['title']) + '" ')
        self.ln(ind(indent + 1) + 'composer = "' + _lily_string(self.model['credits'].get('author', '')) + '" ')
        if self.s['trackName'] and not self.title_on_group() and instrument is not None:
            self.ln(ind(indent + 1) + 'instrument = "' + _lily_string(instrument) + '" ')
        self.ln(ind(indent) + '}')

    def song(self):
        tracks, s, ind = self.model['tracks'], self.s, self.ind
        grouped = s['trackGroup'] and len(tracks) > 1
        if grouped:
            self.ln('\\score {')
            if s['track'] == -1:
                self.ln(ind(1) + '<<')
        for i, track in enumerate(tracks):
            if s['track'] == -1 or s['track'] == track.number:
                if not grouped:
                    self.ln('\\score {')
                self.ln(ind(1) + '\\Track' + _base26(i) + 'StaffGroup')
                if not grouped:
                    self.header(track.name, 1)
                    self.ln('}')
        if grouped:
            if s['track'] == -1:
                self.ln(ind(1) + '>>')
            self.header(None, 1)
            self.ln('}')

    @staticmethod
    def voice_id(index, prefix):
        return prefix + 'Voice' + _base26(index) + 'Music'

    def music(self, track, tid):
        for v in range(2):
            self.ln(self.voice_id(v, tid) + ' = #(define-music-function (parser location inTab) (boolean?)')
            self.ln('#{')
            if any(not b.voices[v].empty for m in track.measures for b in m.beats):
                previous, count = None, len(track.measures)
                lo, hi = self.s['measureFrom'], self.s['measureTo']
                for i, measure in enumerate(track.measures):
                    if (lo <= measure.number or lo == -1) and (hi >= measure.number or hi == -1):
                        self.measure(measure, previous, v, 1, i == count - 1)
                        previous = measure
                self.ln(self.ind(1) + '\\bar "|."')
                self.ln(self.ind(1) + '\\pageBreak')
            self.ln('#})')

    def staff(self, track, tid, *, tab):
        s, ind = self.s, self.ind
        if tab:
            lyrics, chords, texts = s['lyrics'] and track.lyrics != '', s['chordDiagram'] and not s['score'], \
                s['text'] and not s['score']
            tuning = ''.join((str(v - 60) if _older(s['version'], '2.13.46') else ',' + self.pitch(v)) + ' '
                             for v in track.strings)
            self.ln(tid + 'TabStaff = \\new TabStaff \\with { stringTunings = #`( ' + tuning + ') } <<')
        else:
            lyrics = s['lyrics'] and not s['tablature'] and track.lyrics != ''
            chords, texts = s['chordDiagram'], s['text']
            self.ln(tid + 'Staff = \\new Staff <<')
        for v in range(2):
            vid = self.voice_id(v, tid)
            self.ln(ind(1) + '\\context ' + ('TabVoice' if tab else 'Voice') + ' = "' + vid + '" {')
            if not chords:
                self.ln(ind(2) + "\\removeWithTag #'chords")
            if not texts:
                self.ln(ind(2) + "\\removeWithTag #'texts")
            self.ln(ind(2) + '\\' + vid + ' #' + self.boolean(tab))
            self.ln(ind(1) + '}')
        if lyrics:
            self.ln(ind(1) + '\\new Lyrics \\lyricsto "' + self.voice_id(0, tid) + '" \\' + tid + 'Lyrics')
        self.ln('>>')

    def lyrics(self, track, tid):
        ind = self.ind
        self.ln(tid + 'Lyrics = \\lyricmode {')
        self.ln(ind(1) + '\\set ignoreMelismata = #' + self.boolean(True))
        if self.skipped:
            self.p(ind(1) + ''.join('\\skip ' + d + ' ' for d in self.skipped))
            self.ln()
        self.ln(ind(1) + track.lyrics)
        self.ln(ind(1) + '\\unset ignoreMelismata')
        self.ln('}')

    def staff_group(self, track, tid):
        ind = self.ind
        self.ln(tid + 'StaffGroup = \\new StaffGroup <<')
        if self.title_on_group():
            self.ln(ind(1) + '\\set StaffGroup.instrumentName = #"' + _lily_string(track.name) + '"')
        if self.s['score']:
            self.ln(ind(1) + '\\' + tid + 'Staff')
        if self.s['tablature']:
            self.ln(ind(1) + '\\' + tid + 'TabStaff')
        self.ln('>>')

    def measure(self, measure, previous, voice, indent, last):
        ind = self.ind
        if previous is None or measure.tempo != previous.tempo:
            self.ln(ind(indent) + '\\tempo 4=' + str(measure.tempo))
        if previous is None or measure.clef != previous.clef:
            self.ln(ind(indent) + '\\clef #(if inTab "tab" "' + measure.clef + '_8")')
        if (previous is None or measure.key != previous.key) and 0 <= measure.key < len(_LY_KEYS):
            self.ln(ind(indent) + '\\key ' + _LY_KEYS[measure.key] + ' \\major')
        if previous is None or (measure.numerator, measure.denominator) != (previous.numerator, previous.denominator):
            self.ln(ind(indent) + f'\\time {measure.numerator}/{measure.denominator}')
        multiple = sum(any(not b.voices[v].empty for b in measure.beats) for v in range(2)) > 1
        if previous is None or multiple != self.multiple:
            self.ln(ind(indent) + (('\\voiceOne', '\\voiceTwo')[voice] if multiple else '\\oneVoice'))
        self.multiple = multiple
        if measure.repeat_open:
            self.repeat_open_at(measure, indent)
        elif measure.number == 1:
            self.check_repeat_count(measure)
            if self.repeat_count > 0:
                self.repeat_open_at(measure, indent)
        if not measure.repeat_open and measure.alternative > 0:
            self.alternative_open(indent)
        self.p(ind(indent + 1 if self.repeat_open or self.alt_open else indent))
        self.components(measure, voice)
        self.ln()
        if self.alt_open and self.alt_number >= self.repeat_count:
            self.repeat_close(indent)
            self.alternative_close(indent)
        if measure.repeat_close > 0:
            self.repeat_close(indent)
        if last:
            self.repeat_close(indent)
            self.alternative_close(indent)

    def check_repeat_count(self, header):
        present = False
        for nxt in header.track.measures[header.number - 1:]:
            if nxt.repeat_open and nxt.number != header.number:
                break
            if nxt.number > header.number and nxt.alternative > 0:
                present = True
                self.repeat_count += 1
            elif not present and nxt.repeat_close > 0:
                self.repeat_count = nxt.repeat_close + 1
                break

    def repeat_open_at(self, measure, indent):
        self.repeat_close(indent)
        self.alternative_close(indent)
        self.check_repeat_count(measure)
        self.ln(self.ind(indent) + f'\\repeat volta {self.repeat_count} {{')
        self.repeat_open = True

    def repeat_close(self, indent):
        if self.repeat_open:
            self.ln(self.ind(indent) + '}')
        self.repeat_open = False
        if not self.alt_open:
            self.repeat_count = 0

    def alternative_open(self, indent):
        if self.repeat_open and not self.alt_open:
            self.alt_open = True
            self.repeat_close(indent)
            self.ln(self.ind(indent) + '\\alternative {')
        if self.alt_open:
            if self.alt_number > 0:
                self.ln(self.ind(indent) + '}')
            self.ln(self.ind(indent) + '{')
            self.alt_number += 1

    def alternative_close(self, indent):
        if self.alt_open:
            if self.alt_number > 0:
                self.ln(self.ind(indent) + '}')
            self.ln(self.ind(indent) + '}')
        self.alt_open, self.alt_number = False, 0
        if not self.repeat_open:
            self.repeat_count = 0

    def components(self, measure, vi):
        previous = None
        for beat in measure.beats:
            voice = beat.voices[vi]
            if voice.empty:
                continue
            division = (voice.enters, voice.times)
            if previous is not None and self.division_open and division != (previous.voices[vi].enters,
                                                                            previous.voices[vi].times):
                self.p('} ')
                self.division_open = False
            if not self.division_open and division != (1, 1):
                self.p(f'\\times {voice.times}/{voice.enters} {{')
                self.division_open = True
            self.beat(measure, beat, voice)
            previous = beat
        if previous is None:
            self.p(f'\\skip {measure.denominator}*{measure.numerator} ')
        if self.division_open:
            self.p('} ')
            self.division_open = False

    @staticmethod
    def duration(voice):
        return str(voice.value) + {1: '.', 2: '..'}.get(voice.dots, '')

    @staticmethod
    def key(key, value):
        names = _LY_SHARP if key <= 7 else _LY_FLAT
        return names[value % 12] + "'" * max(0, value // 12 - 4) + ',' * max(0, 4 - value // 12)

    def beat(self, measure, beat, voice):
        strings = measure.track.strings
        if voice.is_rest():
            skip = False
            for other in beat.voices:
                if not skip and other.index != voice.index and not other.empty and other.same_duration(voice):
                    skip = not other.is_rest() or other.index < voice.index
            self.p(('\\skip ' if skip else 'r') + self.duration(voice))
        else:
            graces = [n for n in voice.notes if n.fx.get('grace') is not None]
            if graces:
                self.p('\\grace <')
                duration = 0
                for i, n in enumerate(graces):
                    value = n.fx['grace']['value']
                    for rate in (64, 32, 16):
                        if duration < rate and value == rate:
                            duration = rate
                            break
                    self.p((' ' if i else '') + self.key(measure.key, strings[n.string - 1] + n.fx['grace']['fret'])
                           + '\\' + str(n.string))
                self.p('>' + str(duration) + ' ')
            ottava = any(strings[n.string - 1] + n.fret > 72 for n in voice.notes)
            if ottava:
                self.p(' \\ottava #1 ')
            self.p('<')
            for n in voice.notes:
                fx = n.fx
                for flag, text in (('dead', '\\deadNote '), ('palm_mute', '\\palmMute '),
                                   ('ghost', '\\parenthesize ')):
                    if fx.get(flag):
                        self.p(text)
                if _is_bend(fx):
                    self.p('\\bendAfter #+6 ')
                self.p(self.key(measure.key, strings[n.string - 1] + n.fret) + ('~' if self.tied_to(n) else '')
                       + '\\' + str(n.string) + ('\\harmonic' if fx.get('harmonic') is not None else '')
                       + (' ' if len(voice.notes) > 1 else ''))
            self.p('>' + self.duration(voice))
            picking = next((n.fx['tremolo_picking']['value'] for n in voice.notes
                            if n.fx.get('tremolo_picking') is not None), None)
            if picking is not None:
                self.p(f':{picking}')
            for flag, text in (('hammer', '_"H"'), ('slide', '\\glissando'), ('trill', '\\trill'),
                               ('vibrato', '\\prall'), ('staccato', '\\staccato'), ('accent', '->'),
                               ('heavy_accent', '-^')):
                if any(n.fx.get(flag) not in (None, False) for n in voice.notes):
                    self.p(text)
            if beat.stroke is not None:
                self.p('\\arpeggio')
            if ottava:
                self.p(' \\ottava #0')
        if beat.chord is not None and not voice.is_rest():
            if not any(not beat.voices[v].empty and not beat.voices[v].is_rest() for v in range(voice.index)):
                self.p("-\\tag #'chords ^\\markup \\fret-diagram #\"" + ''.join(
                    f"{i + 1}-{'x' if f < 0 else 'o' if f == 0 else f};" for i, f in enumerate(beat.chord['frets']))
                    + '"')
        if beat.text is not None and not any(not beat.voices[v].empty for v in range(voice.index)):
            self.p("-\\tag #'texts ^\\markup {\"" + beat.text + '"}')
        if voice.index == 0 and not voice.is_rest() and measure.track.lyrics_from > measure.number:
            self.skipped.append(self.duration(voice))
        self.p(' ')

    @staticmethod
    def tied_to(note):
        """LilypondOutputStream.isAnyTiedTo: the next same-string note in this voice is tied."""
        measure = note.voice.beat.measure
        track, beat = measure.track, _next_beat(measure.beats, note.voice.beat)
        while measure is not None:
            while beat is not None:
                voice = beat.voices[note.voice.index]
                if voice.is_rest():
                    return False
                for current in voice.notes:
                    if current.string == note.string:
                        return current.tied
                beat = _next_beat(measure.beats, beat)
            measure = track.measures[measure.number] if measure.number < len(track.measures) else None
            if measure is not None:
                beat = _first_beat(measure.beats)
        return False

    @staticmethod
    def pitch(value):
        steps = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6]
        alter = 'SHARP' if value % 12 in (1, 3, 6, 8, 10) else 'NATURAL'
        octave = -1 + max(0, value // 12 - 4) - max(0, 4 - value // 12)
        return f'(ly:make-pitch {octave} {steps[value % 12]} {alter})'


def native_to_lilypond(song, raw_patterns, *, settings=None):
    """Return (LilyPond .ly text, report). settings override LILYPOND_DEFAULTS, TG's defaults."""
    resolved = _lily_settings(settings)
    model = _model(song, raw_patterns)
    if resolved['track'] != -1 and resolved['track'] not in {t.number for t in model['tracks']}:
        raise ValueError('LilyPond part number is outside this score')
    count = len(model['tracks'][0].measures)
    first, last = (1 if resolved['measureFrom'] == -1 else resolved['measureFrom'],
                   count if resolved['measureTo'] == -1 else resolved['measureTo'])
    if not 1 <= first <= last <= count:
        raise ValueError('LilyPond bar range must be ordered and within this score')
    report = _report(model, 'LilyPond', raw_patterns, settings=resolved)
    extra = _Losses()
    for track in model['tracks']:
        if resolved['track'] not in (-1, track.number):
            extra.add(f'track {track.tid}', 'setting_track', _REASONS['setting_track'])
        lo, hi = resolved['measureFrom'], resolved['measureTo']
        if any(not ((lo <= m.number or lo == -1) and (hi >= m.number or hi == -1)) for m in track.measures):
            extra.add(f'track {track.tid}', 'setting_measures', _REASONS['setting_measures'])
        beats = [b for m in track.measures for b in m.beats]
        for flag, feature, present in (
                ('score', 'setting_score', True), ('tablature', 'setting_tablature', True),
                ('text', 'setting_text', any(b.text is not None for b in beats)),
                ('chordDiagram', 'setting_chords', any(b.chord is not None for b in beats)),
                ('lyrics', 'setting_lyrics', track.lyrics != ''), ('trackName', 'setting_name', True)):
            if present and not resolved[flag]:
                extra.add(f'track {track.tid}', feature, _REASONS[feature])
    report['losses'] += extra.report()
    return _Lily(model, resolved).write(), report


# ---------------------------------------------------------------- MusicXML

_XML_TYPES = ['whole', 'half', 'quarter', 'eighth', '16th', '32nd', '64th']
_XML_DIVISIONS = [QUARTER_TIME * 4, QUARTER_TIME * 2, QUARTER_TIME, QUARTER_TIME // 2, QUARTER_TIME // 4,
                  QUARTER_TIME // 8, QUARTER_TIME // 16]
_NATURAL_FREQUENCIES = [(12, 12), (9, 28), (5, 24), (7, 19), (4, 28), (3, 31)]

# TGMusicKeyUtils: key signature 0 none, 1..7 sharps, 8..14 flats.
_KEY_INDEXES = [[0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6], [0, 0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6],
                [6, 0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6], [0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6, 6],
                [0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6, 0], [0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6, 0]]
_KEY_TABLE = [0, 0, 0, 0, 0, 0, 1, 2, 3, 3, 3, 3, 3, 4, 5]


def _note_index(value, key):
    return _KEY_INDEXES[_KEY_TABLE[key]][value % 12]


def _spell(value, key):
    """(step, alter, octave) as TGMusicKeyUtils.noteShortName/noteAlteration/noteOctave."""
    index = _note_index(value, key)
    alter = 0
    if (7 + _note_index(value, 8) - index) % 7 == 1:
        alter = 1
    elif (7 + _note_index(value, 0) - index) % 7 == 6:
        alter = -1
    octave = value // 12 - 1
    if key == 7 and value % 12 == 0:
        octave -= 1
    elif key >= 13 and value % 12 == 11:
        octave += 1
    return 'CDEFGAB'[index], alter, octave


def _java_float(value):
    """Float.toString of a float32 (shortest repr, as JDK 19+)."""
    return str(numpy.float32(value))


def _lyric_beats(text):
    """TGLyric.getLyricBeats: String.split(' ') after CR/LF -> space (Java drops trailing empties)."""
    text = text.replace('\n', ' ').replace('\r', ' ')
    if ' ' not in text:
        return [text]
    parts = text.split(' ')
    while parts and parts[-1] == '':
        parts.pop()
    return parts


class _LyricWriter:
    """MusicXMLLyricWriter's state machine; returns (syllabic, text) per non-rest beat."""
    def __init__(self, track):
        self.start, self.lyrics, self.index, self.state = track.lyrics_from, _lyric_beats(track.lyrics), 0, 'none'

    def measure(self, measure):
        if measure.number < self.start:
            return None
        number = sum(not b.is_rest() for b in measure.beats)
        if self.index + number <= len(self.lyrics):
            words = self.lyrics[self.index:self.index + number]
        else:
            words = ['']
        self.index += number
        out = []
        for word in words:
            if self.state == 'none':
                if word.endswith('-'):
                    word, syllabic, self.state = word[:-1], 'begin', 'begin'
                else:
                    syllabic = 'single'
            elif self.state in ('begin', 'middle'):
                if word.endswith('-'):
                    word, syllabic, self.state = word[:-1], 'middle', 'middle'
                else:
                    syllabic, self.state = 'end', 'none'
            out.append((syllabic, word))
        return out


def _next_tied(note):
    """TGTrackManager.getNextTiedNote: the next non-empty beat of this voice, same string and fret."""
    beat, vi = note.voice.beat, note.voice.index
    later = [b for b in beat.measure.beats if b.start > beat.start and not b.voices[vi].empty]
    voice = min(later, key=lambda b: b.start).voices[vi] if later else None
    if voice is None:
        track, number = beat.measure.track, beat.measure.number
        if number >= len(track.measures):
            return None
        first = [b for b in track.measures[number].beats if not b.voices[vi].empty]
        if not first:
            return None
        voice = min(first, key=lambda b: b.start).voices[vi]
    return next((n for n in voice.notes if n.tied and n.string == note.string and n.fret == note.fret), None)


def _routes(model, channels):
    """GMChannelRouter default routes: percussion 9, others the next two free channels."""
    used, routes = set(), []
    for track in model['tracks']:
        if channels[track.tid]['bank'] == 128:
            routes.append(9)
            continue
        free = [c for c in range(16) if c != 9 and c not in used]
        first = free[0] if free else -1
        used.update(free[:2])
        routes.append(first)
    return routes


class _Xml:
    def __init__(self, model, channels, today):
        self.model, self.channels, self.today = model, channels, today

    @staticmethod
    def add(parent, tag, text=None, **attrs):
        node = ET.SubElement(parent, tag, {k.replace('_', '-'): v for k, v in attrs.items()})
        if text is not None:
            node.text = text
        return node

    def write(self):
        from . import __version__
        add, model = self.add, self.model
        root = ET.Element('score-partwise', version='4.0')
        add(add(root, 'work'), 'work-title', model['title'])
        identification = add(root, 'identification')
        for key, role in (('author', 'composer'), ('writer', 'lyricist')):
            if model['credits'].get(key):
                creator = add(identification, 'creator', model['credits'][key])
                creator.set('type', role)
        if model['credits'].get('copyright'):
            add(identification, 'rights', model['credits']['copyright'])
        encoding = add(identification, 'encoding')
        add(encoding, 'encoding-date', self.today.isoformat())
        add(encoding, 'software', 'VultureTracker ' + __version__)
        part_list = add(root, 'part-list')
        for track, route in zip(model['tracks'], _routes(model, self.channels)):
            part = add(part_list, 'score-part', id=f'P{track.number}')
            add(part, 'part-name', track.name)
            add(add(part, 'score-instrument', id=f'P{track.number}-I1'), 'instrument-name', track.name)
            midi = add(part, 'midi-instrument', id=f'P{track.number}-I1')
            add(midi, 'midi-channel', str(route + 1))
            add(midi, 'midi-program', str(self.channels[track.tid]['program'] + 1))
        for track in model['tracks']:
            self.track(root, track)
        ET.indent(root, '    ')
        return ('<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
                '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
                '"http://www.musicxml.org/dtds/partwise.dtd">\n' + ET.tostring(root, encoding='unicode') + '\n')

    def track(self, root, track):
        part = self.add(root, 'part', id=f'P{track.number}')
        lyrics, measures = _LyricWriter(track), track.measures
        for i, measure in enumerate(measures):
            previous = measures[i - 1] if i else None
            following = measures[i + 1] if i + 1 < len(measures) else None
            node = self.add(part, 'measure', number=str(measure.number))
            self.attributes(node, measure, previous, track.percussion)
            self.direction(node, measure, previous)
            self.barline(node, measure, previous, following)
            words = lyrics.measure(measure)
            for v in range(2):
                self.beats(node, measure, v, v == 0, False, words if v == 0 else None)
            if not track.percussion:
                self.backup(node, measure)
                for v in range(2):
                    self.beats(node, measure, v, v == 0, True, None)

    def backup(self, parent, measure):
        self.add(self.add(parent, 'backup'), 'duration', str(4 * QUARTER_TIME * measure.numerator // measure.denominator))

    @staticmethod
    def endings(measure):
        if measure is None or not measure.alternative:
            return ''
        return ','.join(str(i + 1) for i in range(8) if measure.alternative & 0xff & (1 << i))

    def barline(self, parent, measure, previous, following):
        add, start, end = self.add, None, None
        current = self.endings(measure)
        if current:
            if current != self.endings(previous):
                start = add(parent, 'barline')
                add(start, 'ending', current, number=current, type='start')
            if current != self.endings(following):
                end = add(parent, 'barline')
                add(end, 'ending', current, number=current, type='stop')
        if measure.repeat_open:
            start = start if start is not None else add(parent, 'barline')
            add(start, 'repeat', direction='forward')
        if measure.repeat_close > 0:
            end = end if end is not None else add(parent, 'barline')
            add(end, 'repeat', direction='backward', times=str(measure.repeat_close + 1))

    def attributes(self, parent, measure, previous, percussion):
        add = self.add
        key = previous is None or measure.key != previous.key
        clef = previous is None or measure.clef != previous.clef
        time = previous is None or (measure.numerator, measure.denominator) != (previous.numerator,
                                                                               previous.denominator)
        if not (previous is None or key or clef or time):
            return
        node = add(parent, 'attributes')
        if previous is None:
            add(node, 'divisions', str(QUARTER_TIME))
        if key:
            ks = measure.key
            add(add(node, 'key'), 'fifths', str((((ks - 1) % 7) + 1) * (-1 if ks > 7 else 1) if ks else 0))
        if time:
            t = add(node, 'time')
            add(t, 'beats', str(measure.numerator))
            add(t, 'beat-type', str(measure.denominator))
        add(node, 'staves', '2')
        add(node, 'part-symbol', 'none')
        if clef:
            c = add(node, 'clef')
            if previous is not None:
                c.set('after-barline', 'yes')
            if percussion:
                add(c, 'sign', 'percussion')
            else:
                c.set('number', '1')
                sign, line = {'treble': ('G', '2'), 'bass': ('F', '4'), 'tenor': ('C', '4'),
                              'alto': ('C', '3')}[measure.clef]
                add(c, 'sign', sign)
                add(c, 'line', line)
                add(c, 'clef-octave-change', '-1')
            if previous is None and not percussion:
                add(add(node, 'clef', number='2'), 'sign', 'TAB')
        if not percussion and (previous is None or measure.number == 1):
            track = measure.track
            details = add(node, 'staff-details', number='2')
            add(details, 'staff-type', 'alternate')
            add(details, 'staff-lines', str(len(track.strings)))
            for number in range(len(track.strings), 0, -1):
                tuning = add(details, 'staff-tuning', line=str(len(track.strings) - number + 1))
                self.pitch(tuning, 'tuning-', track.strings[number - 1], measure.key)
            if track.offset > 0:
                add(details, 'capo', str(track.offset))

    def pitch(self, parent, prefix, value, key):
        step, alter, octave = _spell(value, key)
        self.add(parent, prefix + 'step', step)
        if alter:
            self.add(parent, prefix + 'alter', str(alter))
        self.add(parent, prefix + 'octave', str(octave))

    def direction(self, parent, measure, previous):
        add = self.add
        direction = ET.Element('direction', placement='above')
        if previous is None or measure.tempo != previous.tempo:
            metronome = add(add(direction, 'direction-type'), 'metronome')
            add(metronome, 'beat-unit', 'quarter')
            add(metronome, 'per-minute', str(measure.tempo))
        if measure.marker is not None:
            add(add(direction, 'direction-type'), 'rehearsal', measure.marker)
        if len(direction):
            parent.append(direction)

    def duration(self, parent, voice, vi, start, stop):
        add, index = self.add, voice.value.bit_length() - 1
        value = _XML_DIVISIONS[index] * voice.times // voice.enters
        if voice.dots == 1:
            value += value // 2
        elif voice.dots == 2:
            value += (value // 4) * 3
        add(parent, 'duration', str(value))
        if stop:
            add(parent, 'tie', type='stop')
        if start:
            add(parent, 'tie', type='start')
        add(parent, 'voice', str(vi + 1))
        add(parent, 'type', _XML_TYPES[index])
        for _ in range(voice.dots):
            add(parent, 'dot')
        if (voice.enters, voice.times) != (1, 1):
            modification = add(parent, 'time-modification')
            add(modification, 'actual-notes', str(voice.enters))
            add(modification, 'normal-notes', str(voice.times))

    def rest(self, parent, voice, vi, tab):
        node = self.add(parent, 'note')
        self.add(node, 'rest')
        self.duration(node, voice, vi, False, False)
        self.add(node, 'staff', '2' if tab else '1')

    def beats(self, parent, measure, vi, measure_empty, tab, words):
        add, key = self.add, measure.key
        firsts, wrote, last_end, lyric_index, previous_on = [], False, 0, 0, {}
        for beat in measure.beats:
            voice = beat.voices[vi]
            if voice.is_rest() and not wrote:
                firsts.append(beat)
                continue
            if not measure_empty and not wrote:
                self.backup(parent, measure)
            for rest_beat in firsts:
                self.rest(parent, rest_beat.voices[vi], vi, tab)
            firsts = []
            if voice.is_rest():
                if beat.start >= last_end:
                    self.rest(parent, voice, vi, tab)
                continue
            for n, note in enumerate(voice.notes):
                fx, before = note.fx, previous_on.get(note.string)
                if not tab and fx.get('palm_mute'):
                    add(add(add(parent, 'direction', placement='below'), 'direction-type'), 'words', 'P.M.')
                node = add(parent, 'note', dynamics=_java_float(numpy.float32(self.velocity(note)) /
                                                                 numpy.float32(95) * numpy.float32(100)))
                value = measure.track.strings[note.string - 1] + note.fret
                harmonic = fx.get('harmonic')
                if not tab and harmonic is not None and harmonic['type'] == 'natural':
                    value += _NATURAL_FREQUENCIES[harmonic.get('data', 0)][1] - note.fret
                if n > 0:
                    add(node, 'chord')
                self.pitch(add(node, 'pitch'), '', value, key)
                tied_to = _next_tied(note) is not None
                self.duration(node, voice, vi, tied_to, note.tied)
                if tab:
                    add(node, 'stem', 'none')
                if fx.get('ghost'):
                    add(node, 'notehead', 'normal', parentheses='yes')
                elif not tab and fx.get('dead'):
                    add(node, 'notehead', 'x')
                add(node, 'staff', '2' if tab else '1')
                notations = add(node, 'notations')
                if not tab and (tied_to or note.tied):
                    add(notations, 'tied', orientation='over', type='start' if tied_to else 'stop')
                self.articulations(notations, fx)
                self.technical(notations, note, before, tab, n > 0)
                self.ornaments(notations, note)
                if before is not None and before.fx.get('slide'):
                    add(notations, 'slide', type='stop')
                if fx.get('slide'):
                    add(notations, 'slide', type='start')
                if not len(notations):
                    node.remove(notations)
                if fx.get('let_ring'):
                    add(node, 'tied', type='let-ring')
                if not tab and n == 0:
                    index, lyric_index = lyric_index, lyric_index + 1
                    if words is not None and index < len(words) and words[index][1]:
                        lyric = add(node, 'lyric')
                        add(lyric, 'syllabic', words[index][0])
                        add(lyric, 'text', words[index][1])
                if fx.get('dead'):
                    add(add(node, 'play'), 'mute', 'straight')
                elif fx.get('palm_mute'):
                    add(add(node, 'play'), 'mute', 'palm')
                last_end = beat.start + voice.time()
                previous_on[note.string] = note
            wrote = True
        if not wrote and measure_empty:
            for rest_beat in firsts:
                self.rest(parent, rest_beat.voices[vi], vi, tab)

    @staticmethod
    def velocity(note):
        return 95 if note.velocity is None else note.velocity

    def articulations(self, parent, fx):
        node = self.add(parent, 'articulations')
        for flag, tag in (('accent', 'accent'), ('heavy_accent', 'strong-accent'), ('staccato', 'staccato')):
            if fx.get(flag):
                self.add(node, tag)
        if not len(node):
            parent.remove(node)

    def technical(self, parent, note, before, tab, chord_note):
        add, fx = self.add, note.fx
        node = add(parent, 'technical')
        if tab:
            add(node, 'fret', str(note.fret))
            add(node, 'string', str(note.string))
        if before is not None and before.fx.get('hammer'):
            add(node, 'hammer-on', type='stop')
        if fx.get('hammer'):
            add(node, 'hammer-on', 'H', type='start')
        if fx.get('tapping'):
            add(node, 'tap')
        if not chord_note and note.voice.beat.pick is not None:
            add(node, {'up': 'up-bow', 'down': 'down-bow'}[note.voice.beat.pick])
        if fx.get('bend') is not None:
            first, previous = True, 0
            for point in fx['bend']['points']:
                value = point['value']
                if previous == value:
                    first = False
                    continue
                bend = add(node, 'bend', shape='curved')
                add(bend, 'bend-alter', _java_float(numpy.float32(value) / numpy.float32(2)))
                if first and value != 0:
                    add(bend, 'pre-bend')
                elif value == 0:
                    add(bend, 'release')
                previous, first = value, False
        harmonic = fx.get('harmonic')
        if harmonic is not None:
            h = add(node, 'harmonic')
            if harmonic['type'] == 'natural':
                add(h, 'natural')
            elif harmonic['type'] in ('artificial', 'pinch'):
                add(h, 'artificial')
        if not len(node):
            parent.remove(node)

    def ornaments(self, parent, note):
        add, fx = self.add, note.fx
        node = add(parent, 'ornaments')
        if fx.get('tremolo_picking') is not None:
            loop, marks = 4, 0
            while loop < fx['tremolo_picking']['value']:
                loop, marks = loop * 2, marks + 1
            add(node, 'tremolo', str(marks))
        if fx.get('trill') is not None:
            voice = note.voice
            beats = fx['trill']['value'] // voice.value
            if voice.dots == 1:
                beats = beats * 3 // 2
            elif voice.dots == 2:
                beats = beats * 7 // 4
            trill = add(node, 'trill-mark')
            if beats > 1:
                trill.set('beats', str(beats))
            trill.set('trill-step', {2: 'whole', 1: 'half'}.get(fx['trill']['fret'] - note.fret, 'unison'))
        if not len(node):
            parent.remove(node)


def native_to_musicxml(song, raw_patterns, *, channels, today=None):
    """Return (MusicXML 4.0 partwise text, report). channels maps every track to {program, bank}."""
    model = _model(song, raw_patterns)
    tids = list(song['score']['tracks'])
    if set(channels) != set(tids):
        raise ValueError('Notation export: an explicit program/bank mapping is required for every track')
    for tid in tids:
        channel = channels[tid]
        if (set(channel) != {'program', 'bank'} or type(channel['program']) is not int
                or not 0 <= channel['program'] <= 127 or type(channel['bank']) is not int):
            raise ValueError(f'Notation export: {tid}: channel mapping needs integer program 0..127 and bank')
        if (channel['bank'] == 128) != is_percussion(song['score']['tracks'][tid]):
            raise ValueError(f'Notation export: {tid}: channel mapping cannot change percussion classification')
    text = _Xml(model, channels, today or date.today()).write()
    return text, _report(model, 'MusicXML', raw_patterns)
