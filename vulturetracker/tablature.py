"""Exact, optional score events over residual tracker cells (score.version = 1).

There is one authoring document. ``patterns`` contains residual tracker commands;
``score.patterns[name].beats`` owns its generated attacks/releases. Never save the
projected cells back as source. Existing songs without ``score`` are unchanged.

Times are reduced [numerator, denominator] quarter notes. A score pattern has
``row_step`` and ``beats``. Each beat is {id, track, voice, at, written, notes};
written is {value: 1|2|4|8|16|32|64, dots: 0..2, tuplet: [enters,times]}.
Optional beat.text is an anchored plain-text annotation (up to 4096 characters).
An empty notes list is a rest. Notes are {id, pitch, string?, fret?, instrument?,
volume?, velocity?, spelling?, channel?, staccato?, palm_mute?, let_ring?, dead?, vibrato?, slide?, bend?,
tremolo_bar?, ghost?, accent?, heavy_accent?, hammer?, harmonic?, trill?, tremolo_picking?, grace?,
fade_in?, tapping?, slapping?, popping?};
trill is {fret, value: 4|8|16|32|64}, picking is {value: 8|16|32}.
Grace is {fret, value: 16|32|64, velocity, transition?: none|slide|bend|hammer,
on_beat?: bool, dead?: bool}; transition is notation only. It requires explicit
source instrument state; generated attacks share the authored score volume.
Repetition needs explicit head velocity and keeps logical note ownership while
emitting unique head-id/pulse/index attacks. Curves contain points with integer position 0..12 and value
0..12 for bend or -12..12 for tremolo_bar. Pitch is VT/IT's 0..119, string is 1-based. Missing fingering
is assigned deterministically; null string/fret keeps an unplayable pitch visible.
Dynamics retain authored velocity; affected attacks require explicit MIDI velocity
and derive a separate performed value. Hammer modifies the next same-string/voice
attack via its nearest written predecessor, including tied continuations.
Tracks are {tuning: [pitches, high string first], channels: [zero-based indices],
capo: -24..24, max_fret: 0..36 (default 29), instrument: 1..99, name?: str,
color?: '#rrggbb', clef?: treble|bass|alto|tenor|percussion,
key?: {fifths: -7..7, mode: major|minor}, stem?: auto|up|down}.
Optional track.lyrics is {from_measure: 1..2147483647, text: str<=65536};
raw text and line endings remain authoritative. Written-view anchors are
derived per occurrence, not persisted or added to playback events.
Clef/key/stem/color are notation metadata only; they never transpose or retune
playback. Beat.stem optionally overrides Track.stem. Omitted/null note.spelling
means automatic spelling; a non-null spelling is an explicit checked step/alter.
Tracks permit 1..25 strings. Optional note.channel overrides its fingering's
playback channel, preserving tracker channel identity during explicit adoption.
MIDI bank128 identifies bounded percussion tracks: zero tuning/capo, authored
keys1..100, string as lane and fret equal to key. Guitar max_fret does not bound
drum keys. Rhythm/dynamics, grace hits and tremolo rolls are admitted;
unqualified pitched techniques refuse.
Promoted beats carry duration_source: tracker_boundary: notation inferred from
the next attack/note-off, not a claim about an instrument's audible decay.
``order_ids`` names each existing order occurrence. Ties are {from: {occurrence,
note}, to: {occurrence,note}}. Note and beat IDs are unique within a pattern.
Optional ``measures`` entries are {id, from: {occurrence,at}, to: {occurrence,at},
meter: [numerator,denominator], marker?: {title, color?: '#rrggbb'}}. Markers are
anchored to the measure start. Bounds, exact meter length and overlap are checked
against the compiled timing map; optional swing is none/eighth/sixteenth.
Optional repeat_open/repeat_close/endings use the opt-in repeat_projection
backing/plan pair; public linear callers refuse them until they adopt that pair.
Key changes are not yet supported.

Pure edit payloads (all replacements/patches leave their input unchanged):
  track_set: {op, track: id, value: complete track}
  track_delete: {op, track: id, remove_notes?: bool}
  measure_set: {op, measure: complete {id,from,to,meter}}
  measure_delete: {op, measure: id}
  beat_set: {op, pattern: name, beat: complete beat, row_step?: fraction}
  beat_delete: {op, pattern, beat: id, remove_ties?: bool}
  note_set: {op, pattern, beat: id, note: {id, ...changed fields}}
  note_delete: {op, pattern, beat: id, note: id, remove_ties?: bool}
  tie_set: {op, from: {occurrence,note}, to: {occurrence,note}}
  tie_delete: {op, from: {occurrence,note}, to?: {occurrence,note}}
note_set with string/fret computes pitch; with pitch alone preserves or repairs
fingering. Explicit incompatible pitch and fingering is refused. track_set keeps
pitches and repairs fingering. No automatic migration of legacy notes occurs.
Deleting a tied note/beat refuses by default. Explicit remove_ties: true removes
only incident ties; surviving continuations become attacks. Pitch/channel/voice/
instrument/volume changes that break a tie refuse atomically, never silently
retune the other notes. tie_delete removes only its explicitly selected edge.
track_delete refuses any used track unless remove_notes: true explicitly removes
all its beats/rests and incident ties. It never removes raw cells, channels,
samples/instruments or measure anchors. Measure changes only edit exact notation
boundaries; they do not stretch notes or alter tempo. Per-measure tempo remains
unsupported; absolute raw T commands supply the shared tempo map.

The first playback slice requires row_step == module.speed / 24; no regridding.
Unrepresentable timing, unsupported techniques/flow and conflicting ownership
raise ValueError before persistence. Two voices and exact ties are supported;
overlapping notes must have independent channels. Reused patterns must have the
same generated cells in every occurrence. Occurrence-dependent projections are
refused with a make-unique instruction. This is not full TuxGuitar parity.
"""
import copy
import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from fractions import Fraction
from bisect import bisect_right
import re
import struct

from .model import Cell, Pattern, Module, NOTE_OFF, NOTE_CUT
from .notation import parse_cell, format_cell


@dataclass
class Projection:
    patterns: list
    raw_patterns: list = field(default_factory=list)
    owners: dict = field(default_factory=dict)
    positions: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    orders: list | None = None  # Only standalone repeat export replaces the authored order sequence.
    channel_parents: dict = field(default_factory=dict)  # Export-only harmonic lanes -> authored channel.


@dataclass
class RepeatProjection:
    """Disposable backing and schedule; callers must adopt both atomically."""
    patterns: list
    orders: list
    plan: dict
    source_view: dict


def _has_repeats(song):
    return any(m.get('repeat_open') or m.get('repeat_close') or m.get('endings')
               for m in song.get('score', {}).get('measures', []))


def _guard_repeat_projection(song):
    if _has_repeats(song):
        raise ValueError('repeat/endings require adopting repeat_projection backing and plan together')


def _int(value, low, high, where):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{where}: expected integer {low}..{high}')
    return value


def _id(value, where):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', value):
        raise ValueError(f'{where}: expected a 1..80 character identifier')
    return value


def _keys(value, allowed, where):
    if not isinstance(value, dict):
        raise ValueError(f'{where}: expected a mapping')
    if set(value) - set(allowed):
        raise ValueError(f'{where}: unsupported fields {sorted(set(value) - set(allowed), key=str)}')


def _fraction(value, where, positive=False):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f'{where}: expected [numerator, denominator]')
    a = _int(value[0], 1 if positive else 0, 1000000, where)
    b = _int(value[1], 1, 1000000, where)
    return Fraction(a, b)


def _pair(value):
    return [value.numerator, value.denominator]


class TempoClock:
    """Exact piecewise quarter/second clock, built once per plan.

    ``tempos`` is the optional plan list of {at: [n,d], bpm: 32..255}.
    Entries start at zero and strictly increase. Coordinates stay JSON-safe;
    potentially large Fraction second prefixes are kept only inside Python.
    Public queries accept nonnegative int/Fraction values or exact pairs.
    """
    def __init__(self, tempo, tempos=None):
        tempo = _int(tempo, 32, 255, 'tempo')
        if tempos is None:
            tempos = [{'at': [0, 1], 'bpm': tempo}]
        if not isinstance(tempos, list) or not 1 <= len(tempos) <= 200000:
            raise ValueError('tempos: expected 1..200000 changes')
        self._ats, self._bpms, self._seconds = [], [], []
        for change in tempos:
            _keys(change, ('at', 'bpm'), 'tempo change')
            pair = change.get('at')
            if (not isinstance(pair, list) or len(pair) != 2 or
                    any(type(x) is not int or not 0 <= x <= 2**53 - 1 for x in pair) or pair[1] == 0):
                raise ValueError('tempo change at: expected a nonnegative JSON-safe fraction pair')
            at, bpm = Fraction(*pair), _int(change.get('bpm'), 32, 255, 'tempo change bpm')
            if not self._ats and at != 0 or self._ats and at <= self._ats[-1]:
                raise ValueError('tempos must start at zero and strictly increase')
            seconds = (self._seconds[-1] + (at - self._ats[-1]) * Fraction(60, self._bpms[-1])
                       if self._ats else Fraction(0))
            self._ats.append(at)
            self._bpms.append(bpm)
            self._seconds.append(seconds)

    @staticmethod
    def _exact(value):
        if isinstance(value, (list, tuple)) and len(value) == 2 and all(type(x) is int for x in value) and value[1] > 0:
            value = Fraction(*value)
        if not isinstance(value, (int, Fraction)) or isinstance(value, bool) or value < 0:
            raise ValueError('clock coordinate must be a nonnegative exact fraction')
        return Fraction(value)

    def seconds_at(self, quarter):
        quarter = self._exact(quarter)
        i = bisect_right(self._ats, quarter) - 1
        return self._seconds[i] + (quarter - self._ats[i]) * Fraction(60, self._bpms[i])

    def quarters_at(self, seconds):
        seconds = self._exact(seconds)
        i = bisect_right(self._seconds, seconds) - 1
        return self._ats[i] + (seconds - self._seconds[i]) * Fraction(self._bpms[i], 60)

    def tempo_at(self, quarter):
        return self._bpms[bisect_right(self._ats, self._exact(quarter)) - 1]


def _tempo_commands(raw_patterns, step):
    """Source bindings, once per pattern, including redundant T commands."""
    result = []
    for pattern in raw_patterns:
        for index, row in enumerate(pattern.rows):
            commands = [(ch, cell.param) for ch, cell in enumerate(row) if cell.effect == 20]
            if len(commands) > 1:
                raise ValueError(f'{pattern.name} row {index}: multiple T commands on one row')
            if commands:
                ch, bpm = commands[0]
                if type(bpm) is not int or not 32 <= bpm <= 255:
                    raise ValueError(f'{pattern.name}: raw tempo/speed/flow unsupported; only absolute T20..FF is supported')
                lane = pattern.lanes.get((index, ch))
                result.append(dict(pattern=pattern.name, row=index, ch=ch, at=_pair(index * step), bpm=bpm,
                                   automation=lane[1] if lane and lane[0] == 'e' else None))
    return result


def _raw_tempos(timeline, raw_patterns, tempo, *, commands=None):
    """Resolve absolute T commands in occurrence order without changing source."""
    commands = _tempo_commands(raw_patterns, timeline['step']) if commands is None else commands
    rows = {pattern.name: [] for pattern in raw_patterns}
    for command in commands:
        rows[command['pattern']].append((command['row'], command['bpm']))
    result = [{'at': [0, 1], 'bpm': _int(tempo, 32, 255, 'module.tempo')}]
    for occurrence in timeline['occurrences']:
        origin = Fraction(*occurrence['at'])
        for row, bpm in rows[occurrence['pattern']]:
            at = origin + row * timeline['step']
            if at == 0:
                result[0]['bpm'] = bpm
            elif bpm != result[-1]['bpm']:
                result.append({'at': _pair(at), 'bpm': bpm})
    return result


def _tempo_fields(tempo, tempos):
    # A row-zero override still carries its map; plan.tempo retains module.tempo.
    return {} if tempos == [{'at': [0, 1], 'bpm': tempo}] else {'tempos': tempos}


def tempo_edit(song, raw_patterns, edit):
    """Return residual Pattern cell edits for one tempo_set action; mutate nothing.

    Payload: {op:'tempo_set', occurrence, at:[n,d], bpm:int|null,
    scope?:'occurrence'|'pattern'}. Omitted scope means occurrence-only.
    State owns revision, approval, history and publication checks.
    """
    _keys(edit, ('op', 'occurrence', 'at', 'bpm', 'scope'), 'tempo edit')
    if edit.get('op') != 'tempo_set' or 'bpm' not in edit:
        raise ValueError('tempo edit requires op tempo_set and bpm (integer or null)')
    bpm = edit['bpm']
    if bpm is not None:
        _int(bpm, 32, 255, 'tempo bpm')
    scope = edit.get('scope', 'occurrence')
    if scope not in ('occurrence', 'pattern'):
        raise ValueError('tempo scope must be occurrence or pattern')
    identity = _id(edit.get('occurrence'), 'tempo occurrence')
    at = _fraction(edit.get('at'), 'tempo at')
    timeline = _score_timeline(song, raw_patterns)
    occurrence = next((o for o in timeline['occurrences'] if o['id'] == identity), None)
    if occurrence is None:
        raise ValueError(f'unknown tempo occurrence {identity}')
    name = occurrence['pattern']
    if scope == 'occurrence' and sum(o['pattern'] == name for o in timeline['occurrences']) > 1:
        raise ValueError(f'{name}: occurrence-only tempo edit affects a reused pattern; Make unique first '
                         'or choose pattern scope explicitly')
    row = at / timeline['step']
    index = next(i for i, p in enumerate(raw_patterns) if p.name == name)
    pattern = raw_patterns[index]
    if row.denominator != 1 or not 0 <= row < len(pattern.rows):
        raise ValueError(f'{name}: tempo at must resolve to an integral row inside the pattern')
    row = int(row)
    commands = _tempo_commands(raw_patterns, timeline['step'])
    existing = next((c for c in commands if c['pattern'] == name and c['row'] == row), None)
    if existing is not None:
        ch = existing['ch']
        if existing['automation'] is not None:
            raise ValueError(f'{name} row {row}: tempo is owned by automation lane {existing["automation"]}; '
                             'edit the lane or use MAKE EDITABLE first')
        if bpm == existing['bpm']:
            return []
    elif bpm is None:
        return []
    else:
        ch = next((ch for ch, cell in enumerate(pattern.rows[row])
                   if cell.effect == 0 and cell.param == 0 and
                   pattern.lanes.get((row, ch), (None,))[0] != 'e'), None)
        if ch is None:
            raise ValueError(f'{name} row {row}: no free unowned effect column for tempo')
    cell = copy.copy(pattern.rows[row][ch])
    cell.effect, cell.param = (0, 0) if bpm is None else (20, bpm)
    return [(index, [dict(row=row, ch=ch, cell=format_cell(cell))])]


def _edit_row(value, rows, where, *, endpoint=False):
    """An integer grid address or an exact row pair; floats never enter authoring."""
    if type(value) is int:
        return Fraction(_int(value, 1 if endpoint else 0, rows if endpoint else rows - 1, where))
    value = _fraction(value, where, positive=endpoint)
    if value > rows or (not endpoint and value == rows):
        raise ValueError(f'{where}: outside pattern row bounds')
    return value


def duration_quarters(written):
    """Exact written duration, retaining spelling separately in the document."""
    _keys(written, ('value', 'dots', 'tuplet'), 'written duration')
    value = _int(written.get('value'), 1, 64, 'duration value')
    if value not in (1, 2, 4, 8, 16, 32, 64):
        raise ValueError('duration value: expected a power of two through 64')
    dots = _int(written.get('dots', 0), 0, 2, 'duration dots')
    division = _fraction(written.get('tuplet', [1, 1]), 'duration tuplet', True)
    return Fraction(4, value) * (2 - Fraction(1, 2 ** dots)) / division


def _channels(song):
    value = song.get('module', {}).get('channels', 0)
    return len(value) if isinstance(value, list) else _int(value, 1, 64, 'module.channels')


def _pattern_names(song):
    return {str(k) for k in song.get('patterns', {})}


def _track(score, beat):
    try:
        return score['tracks'][beat['track']]
    except (KeyError, TypeError):
        raise ValueError(f"beat {beat.get('id')}: unknown track") from None


def is_percussion(track):
    """TG channel-bank authority; a percussion clef alone does not retune notes."""
    return isinstance(track.get('midi'), dict) and track['midi'].get('bank') == 128


def _fingering(track, note, used=()):
    """Keep a valid assignment, otherwise minimum fret then string; no transpose."""
    pitch = _int(note.get('pitch'), 0, 119, 'note pitch')
    capo, top = track.get('capo', 0), track.get('max_fret', 29)
    string, fret = note.get('string'), note.get('fret')
    if is_percussion(track):
        if not 1 <= pitch <= 100:
            return None, None  # Raw previews may contain keys outside authored admission.
        if type(string) is int and 1 <= string <= len(track['channels']) and string not in used:
            return string, pitch
        if note.get('channel') in track['channels']:
            lane = track['channels'].index(note['channel']) + 1
            if lane not in used:
                return lane, pitch
        lane = next((i for i in range(1, len(track['channels']) + 1) if i not in used), None)
        return (lane, pitch) if lane is not None else (None, None)
    if (type(string) is int and 1 <= string <= len(track['tuning']) and
            type(fret) is int and 0 <= fret <= top and
            track['tuning'][string - 1] + capo + fret == pitch and string not in used):
        return string, fret
    choices = [(pitch - p - capo, i + 1) for i, p in enumerate(track['tuning'])
               if i + 1 not in used and 0 <= pitch - p - capo <= top]
    if choices:
        fret, string = min(choices)
        return string, fret
    return None, None


def _resolved_notes(score, beat):
    track, used = _track(score, beat), set()
    out = []
    for original in beat['notes']:
        note = dict(original)
        # Explicit assignments take priority over automatic assignments in a chord.
        others = {n['string'] for n in beat['notes'] if n is not original and n.get('string') is not None}
        string, fret = _fingering(track, note, used | others)
        if original.get('string') is not None:
            string, fret = original['string'], original['fret']
        if string is None:
            available = [i for i in range(1, len(track['channels']) + 1) if i not in used | others]
            if not available:
                raise ValueError(f"beat {beat['id']}: more simultaneous notes than track channels")
            lane = available[0]
        else:
            lane = string
        if lane in used:
            raise ValueError(f"beat {beat['id']}: simultaneous notes share string/channel {lane}")
        used.add(lane)
        note.update(string=string, fret=fret, channel=note.get('channel', track['channels'][lane - 1]))
        if note.get('trill') is not None:
            if string is None:
                raise ValueError(f"note {note['id']}: trill needs resolved string/fret")
            alternate = track['tuning'][string - 1] + track.get('capo', 0) + note['trill']['fret']
            if not 0 <= alternate <= 119:
                raise ValueError(f"note {note['id']}: trill alternate exceeds native pitch range 0..119")
        if note.get('grace') is not None:
            _validate_grace(note['grace'], track)
            if string is None:
                raise ValueError(f"note {note['id']}: grace needs resolved string/fret")
            pitch = track['tuning'][string - 1] + track.get('capo', 0) + note['grace']['fret']
            if not 0 <= pitch <= 119:
                raise ValueError(f"note {note['id']}: grace exceeds native pitch range 0..119")
        out.append(note)
    return out


def _beat_strokes(beat):
    """Shared TG beat metadata; null and omission both mean none."""
    stroke, pick = beat.get('stroke'), beat.get('pick_stroke')
    if stroke is not None:
        _keys(stroke, ('direction', 'value'), 'beat stroke')
        if stroke.get('direction') not in ('up', 'down'):
            raise ValueError('beat stroke direction must be up or down')
        if type(stroke.get('value')) is not int or stroke['value'] not in (4, 8, 16, 32, 64):
            raise ValueError('beat stroke value must be 4, 8, 16, 32 or 64')
    if pick is not None and pick not in ('up', 'down'):
        raise ValueError('beat pick_stroke must be up or down')
    return stroke, pick


def _cohort_key(beat):
    """One TGBeat's voices; distinct beats may legally share an onset."""
    return beat['track'], _fraction(beat['at'], 'beat at'), beat.get('cohort', 0)


def _beat_cohorts(beats):
    groups = {}
    for beat in beats:
        groups.setdefault(_cohort_key(beat), []).append(beat)
    return [groups[key] for key in sorted(groups, key=lambda key: (key[1], key[2]))]


def _stamp_cohorts(groups, *, keep_single=False):
    """Save stable collision order after moving existing group objects."""
    counts = {}
    totals = {}
    for group in groups:
        key = _cohort_key(group[0])[:2]
        totals[key] = totals.get(key, 0) + 1
    for group in groups:
        key = _cohort_key(group[0])[:2]
        if keep_single and totals[key] == 1:
            continue
        rank = counts.get(key, 0)
        counts[key] = rank + 1
        for beat in group:
            if rank:
                beat['cohort'] = rank
            else:
                beat.pop('cohort', None)


def _has_distinct_cohorts(beats):
    onsets = {}
    for beat in beats:
        key = _cohort_key(beat)
        ranks = onsets.setdefault(key[:2], set())
        ranks.add(key[2])
        if len(ranks) > 1:
            return True
    return False


def _require_single_cohorts(beats, operation):
    if _has_distinct_cohorts(beats):
        raise ValueError(f'{operation} does not yet preserve independent coincident beat groups; no changes applied')


def _move_voice_cohort(beats, beat, destination):
    """TG moveVoicePrecise joins the first destination TGBeat, not its old rank."""
    source = [b for b in beats if _cohort_key(b) == _cohort_key(beat)]
    targets = _beat_cohorts(b for b in beats if b is not beat and b['track'] == beat['track']
                            and Fraction(*b['at']) == destination)
    target = targets[0] if targets else []
    others = [b for b in source if b is not beat]
    shared = _cohort_strokes(source)[_cohort_key(beat)]
    inherited = _cohort_strokes(target)[_cohort_key(target[0])] if target else {}
    transferred = dict(inherited)
    unique_sounding = not any(b['notes'] for b in others)
    if unique_sounding:
        for key, value in shared.items():
            if key in transferred and transferred[key] != value:
                raise ValueError(f'moving voice has conflicting {key} at its destination group')
            transferred[key] = value
    texts = [{b['text'] for b in group if b.get('text')} for group in (source, target)]
    if any(len(values) > 1 for values in texts):
        raise ValueError('moving voice cannot preserve conflicting per-voice text in one group')
    source_text, target_text = (next(iter(values), None) for values in texts)
    if not others and source_text is not None:
        if target_text is not None and target_text != source_text:
            raise ValueError('moving voice has conflicting text at its destination group')
        target_text = source_text
    occupied = [b for b in target if b.get('voice', 0) == beat.get('voice', 0)]
    if any(b['notes'] or b.get('stem', 'auto') != 'auto' or 'duration_source' in b for b in occupied):
        raise ValueError('moving voice would replace a sounding or annotated destination voice')
    rank = target[0].get('cohort', 0) if target else 0
    for other in occupied:
        beats.remove(other)
    target = [b for b in target if b not in occupied] + [beat]
    for members, values, text in ((others, {} if unique_sounding else shared, source_text),
                                  (target, transferred, target_text)):
        for member in members:
            for key in ('chord', 'stroke', 'pick_stroke', 'text'):
                member.pop(key, None)
            member.update(copy.deepcopy(values))
        if members and text is not None:
            min(members, key=lambda b: b.get('voice', 0))['text'] = text
    beat['at'] = _pair(destination)
    beat.pop('cohort', None)
    if rank:
        beat['cohort'] = rank


def _cohort_strokes(beats):
    """Resolve sparse shared metadata without mutating the authored voices."""
    cohorts = {}
    for beat in beats:
        values = cohorts.setdefault(_cohort_key(beat), {})
        for key, value in zip(('stroke', 'pick_stroke', 'chord'), (*_beat_strokes(beat), beat.get('chord'))):
            if value is not None:
                if key in values and values[key] != value:
                    raise ValueError(f"{beat['id']}: conflicting {key} across the shared beat cohort")
                values[key] = value
    return cohorts


def _validate_chord(chord, track):
    if chord is None:
        return
    if is_percussion(track):
        raise ValueError('percussion chord diagrams and diagram-to-notes are unsupported')
    _keys(chord, ('name', 'first_fret', 'frets'), 'beat chord')
    if not isinstance(chord.get('name'), str) or len(chord['name']) > 4096:
        raise ValueError('beat chord name must be a string of at most 4096 characters')
    maximum = track.get('max_fret', 29)
    first = _int(chord.get('first_fret'), 0, maximum, 'beat chord first_fret')
    frets = chord.get('frets')
    if not isinstance(frets, list) or len(frets) != len(track['tuning']):
        raise ValueError('beat chord frets must have one entry per track string')
    for fret in frets:
        _int(fret, -1, maximum, 'beat chord fret')
    positive = [f for f in frets if f > 0]
    resolved = first or max(1, min(positive, default=1))
    if any(not resolved <= fret <= resolved + 4 for fret in positive):
        raise ValueError('beat chord positive frets must fit its explicit/resolved five-fret window')


def _clear_removed_chords(before, after):
    """Final sounding-note removal clears shared annotations, not existing rests."""
    for name, spec in before.get('score', {}).get('patterns', {}).items():
        sounding = {_cohort_key(b) for b in spec['beats'] if b['notes']}
        beats = after.get('score', {}).get('patterns', {}).get(name, {}).get('beats', [])
        remaining = {_cohort_key(b) for b in beats if b['notes']}
        removed = sounding - remaining
        for beat in beats:
            if _cohort_key(beat) in removed:
                beat.pop('chord', None)


def _validate_grace(grace, track):
    _keys(grace, ('fret', 'value', 'velocity', 'transition', 'on_beat', 'dead'), 'grace')
    _int(grace.get('fret'), 1 if is_percussion(track) else 0,
         100 if is_percussion(track) else track.get('max_fret', 29), 'grace fret')
    _int(grace.get('velocity'), 0, 127, 'grace velocity')
    if type(grace.get('value')) is not int or grace['value'] not in (16, 32, 64):
        raise ValueError('grace value must be 16, 32 or 64')
    if grace.get('transition', 'none') not in ('none', 'slide', 'bend', 'hammer'):
        raise ValueError('grace transition must be none, slide, bend or hammer')
    for flag in ('on_beat', 'dead'):
        if flag in grace and type(grace[flag]) is not bool:
            raise ValueError(f'grace {flag} must be boolean')


def validate_score(song):
    """Validate source shape and identity. Projection additionally checks cells/timing."""
    if 'score' not in song:
        return
    score = song['score']
    _keys(score, ('version', 'tracks', 'patterns', 'order_ids', 'ties', 'measures', 'metadata'), 'score')
    if 'metadata' in score:
        _keys(score['metadata'], ('title', 'artist', 'album', 'author', 'date', 'copyright', 'writer', 'transcriber', 'comments'), 'score metadata')
        for key, value in score['metadata'].items():
            if not isinstance(value, str) or len(value) > (8000 if key == 'comments' else 200) or '\x00' in value:
                raise ValueError(f'score metadata {key}: expected text of at most {8000 if key == "comments" else 200} characters without NUL')
    _int(score.get('version'), 1, 1, 'score.version')
    tracks, patterns = score.get('tracks'), score.get('patterns')
    if not isinstance(tracks, dict) or not isinstance(patterns, dict):
        raise ValueError('score: tracks and patterns must be mappings')
    if len(tracks) > 64 or len(patterns) > 254:
        raise ValueError('score: track/pattern capacity exceeded')
    channel_count, owned_channels = _channels(song), set()
    for key, track in tracks.items():
        _id(key, 'track id')
        _keys(track, ('tuning', 'channels', 'capo', 'max_fret', 'instrument', 'name', 'color', 'clef', 'key', 'stem', 'midi', 'lyrics',
                      'solo_mute'), f'track {key}')
        if track.get('solo_mute', 'solo') not in ('solo', 'mute'):   # TuxGuitar's track solo/mute flag (notation metadata)
            raise ValueError(f'track {key}: solo_mute must be solo or mute')
        tuning, channels = track.get('tuning'), track.get('channels')
        if not isinstance(tuning, list) or not 1 <= len(tuning) <= 25:
            raise ValueError(f'track {key}: tuning needs 1..25 strings')
        if not isinstance(channels, list) or len(channels) != len(tuning):
            raise ValueError(f'track {key}: one channel per string is required')
        for pitch in tuning:
            _int(pitch, 0, 119, f'track {key} tuning')
        for channel in channels:
            _int(channel, 0, channel_count - 1, f'track {key} channel')
            if channel in owned_channels:
                raise ValueError(f'track {key}: channel {channel} is already assigned')
            owned_channels.add(channel)
        _int(track.get('capo', 0), -24, 24, f'track {key} capo')
        _int(track.get('max_fret', 29), 0, 36, f'track {key} max_fret')
        _int(track.get('instrument'), 1, 99, f'track {key} instrument')
        if 'lyrics' in track:
            lyrics = track['lyrics']
            _keys(lyrics, ('from_measure', 'text'), f'track {key} lyrics')
            _int(lyrics.get('from_measure'), 1, 2147483647, f'track {key} lyrics from_measure')
            if not isinstance(lyrics.get('text'), str) or len(lyrics['text']) > 65536:
                raise ValueError(f'track {key} lyrics text must be a string of at most 65536 characters')
        if 'midi' in track:
            _keys(track['midi'], ('program', 'bank', 'source_pan', 'source_volume'), f'track {key} MIDI')
            _int(track['midi'].get('program'), 0, 127, f'track {key} MIDI program')
            _int(track['midi'].get('bank', 0), 0, 16383, f'track {key} MIDI bank')
            for field in ('pan', 'volume'):
                if 'source_' + field in track['midi']:
                    binding = track['midi']['source_' + field]
                    _keys(binding, ('value', 'mixer_' + field), f'track {key} MIDI source_{field}')
                    _int(binding.get('value'), 0, 127, f'track {key} MIDI source_{field} value')
                    _int(binding.get('mixer_' + field), 0, 64, f'track {key} MIDI source_{field} mixer_{field}')
        if is_percussion(track) and (any(tuning) or track.get('capo', 0) != 0):
            raise ValueError(f'track {key}: percussion requires zero tuning and capo')
        if 'name' in track and (not isinstance(track['name'], str) or len(track['name']) > 80):
            raise ValueError(f'track {key}: invalid name')
        if 'color' in track and (not isinstance(track['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', track['color'])):
            raise ValueError(f'track {key}: color must be #rrggbb')
        if 'clef' in track and track['clef'] not in ('treble', 'bass', 'alto', 'tenor', 'percussion'):
            raise ValueError(f'track {key}: unsupported clef')
        if 'stem' in track and track['stem'] not in ('auto', 'up', 'down'):
            raise ValueError(f'track {key}: stem must be auto, up or down')
        if 'key' in track:
            signature = track['key']
            _keys(signature, ('fifths', 'mode'), f'track {key} key signature')
            _int(signature.get('fifths'), -7, 7, f'track {key} key fifths')
            if signature.get('mode', 'major') not in ('major', 'minor'):
                raise ValueError(f'track {key}: key mode must be major or minor')
    orders, order_ids = song.get('orders', []), score.get('order_ids')
    if not isinstance(order_ids, list) or len(order_ids) != len(orders):
        raise ValueError('score.order_ids must identify every order occurrence')
    for identity in order_ids:
        _id(identity, 'order occurrence')
    if len(set(order_ids)) != len(order_ids):
        raise ValueError('score.order_ids contains duplicate identities')
    measures, measure_ids = score.get('measures', []), set()
    if not isinstance(measures, list) or len(measures) > 12800:
        raise ValueError('score.measures must be a bounded list')
    for measure in measures:
        if isinstance(measure, dict) and 'tempo' in measure:
            raise ValueError('measure tempo changes are unsupported by shared playback; use module.tempo for a song-wide change')
        _keys(measure, ('id', 'from', 'to', 'meter', 'marker', 'swing',
                        'repeat_open', 'repeat_close', 'endings', 'line_break', 'double_bar', 'staff', 'tempo_unit'), 'measure')
        if 'tempo_unit' in measure:
            # TuxGuitar's written tempo: `value` beats of `base` (dotted or not) per minute. Notation only; the
            # performed quarter tempo stays the shared tempo map's, and the TG writer checks the two agree.
            unit = measure['tempo_unit']
            _keys(unit, ('base', 'dotted', 'value'), 'measure tempo_unit')
            if unit.get('base') not in (1, 2, 4, 8, 16, 32, 64) or type(unit.get('dotted', False)) is not bool:
                raise ValueError('measure tempo_unit needs base 1, 2, 4, 8, 16, 32 or 64 and boolean dotted')
            _int(unit.get('value'), 1, 10000, 'measure tempo_unit value')
        if type(measure.get('line_break', False)) is not bool:
            raise ValueError('measure line_break must be boolean')
        if type(measure.get('double_bar', False)) is not bool:
            raise ValueError('measure double_bar must be boolean')
        staff = measure.get('staff', {})   # per-track clef/key changes from this measure, as TuxGuitar stores them
        if not isinstance(staff, dict):
            raise ValueError('measure staff must map tracks to clef/key changes')
        for tid, change in staff.items():
            if tid not in score.get('tracks', {}) or not isinstance(change, dict) or not change:
                raise ValueError(f'measure staff {tid!r}: an existing track with a clef or key change')
            _keys(change, ('clef', 'key'), f'measure staff {tid}')
            if 'clef' in change and change['clef'] not in ('treble', 'bass', 'alto', 'tenor', 'percussion'):
                raise ValueError(f'measure staff {tid}: unsupported clef')
            if 'key' in change:
                _keys(change['key'], ('fifths', 'mode'), f'measure staff {tid} key')
                _int(change['key'].get('fifths'), -7, 7, f'measure staff {tid} key fifths')
                if change['key'].get('mode', 'major') not in ('major', 'minor'):
                    raise ValueError(f'measure staff {tid}: key mode must be major or minor')
        if measure.get('swing', 'none') not in ('none', 'eighth', 'sixteenth'):
            raise ValueError('measure swing must be none, eighth or sixteenth')
        if type(measure.get('repeat_open', False)) is not bool:
            raise ValueError('measure repeat_open must be boolean')
        _int(measure.get('repeat_close', 0), 0, 100, 'measure repeat_close')
        endings = measure.get('endings', [])
        if not isinstance(endings, list) or len(endings) > 8:
            raise ValueError('measure endings must be a list of unique pass numbers 1..8')
        for ending in endings:
            _int(ending, 1, 8, 'measure ending')
        if len(set(endings)) != len(endings):
            raise ValueError('measure endings must be unique')
        identity = _id(measure.get('id'), 'measure id')
        if identity in measure_ids:
            raise ValueError(f'duplicate measure id {identity}')
        measure_ids.add(identity)
        if 'marker' in measure:
            marker = measure['marker']
            _keys(marker, ('title', 'color'), f'measure {identity} marker')
            if not isinstance(marker.get('title'), str) or not 1 <= len(marker['title']) <= 4096:
                raise ValueError(f'measure {identity}: marker title needs 1..4096 characters')
            if 'color' in marker and (not isinstance(marker['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', marker['color'])):
                raise ValueError(f'measure {identity}: marker color must be #rrggbb')
        for side in ('from', 'to'):
            endpoint = measure.get(side)
            _keys(endpoint, ('occurrence', 'at'), f'measure {side}')
            if endpoint.get('occurrence') not in order_ids:
                raise ValueError(f'measure {identity}: unknown occurrence')
            _fraction(endpoint.get('at'), f'measure {identity} {side}')
        meter = measure.get('meter')
        if not isinstance(meter, list) or len(meter) != 2:
            raise ValueError(f'measure {identity}: meter is [numerator, denominator]')
        _int(meter[0], 1, 64, 'meter numerator')
        denominator = _int(meter[1], 1, 64, 'meter denominator')
        if denominator not in (1, 2, 4, 8, 16, 32, 64):
            raise ValueError('meter denominator must be a power of two through 64')
    note_ids = {}
    for name, spec in patterns.items():
        if not isinstance(name, str) or name not in _pattern_names(song):
            raise ValueError(f'score pattern {name}: no matching tracker pattern')
        _keys(spec, ('row_step', 'beats'), f'score pattern {name}')
        _fraction(spec.get('row_step'), f'{name} row_step', True)
        beats = spec.get('beats')
        if not isinstance(beats, list) or len(beats) > 12800:
            raise ValueError(f'{name}: beats must be a bounded list')
        ids, notes = set(), {}
        for beat in beats:
            _keys(beat, ('id', 'track', 'voice', 'at', 'written', 'notes', 'duration_source', 'stem', 'text',
                         'stroke', 'pick_stroke', 'chord', 'cohort'), f'{name} beat')
            identity = _id(beat.get('id'), 'beat id')
            if identity in ids:
                raise ValueError(f'{name}: duplicate beat id {identity}')
            ids.add(identity)
            if 'text' in beat and (not isinstance(beat['text'], str) or len(beat['text']) > 4096):
                raise ValueError(f'beat {identity}: text must be a string of at most 4096 characters')
            track = _track(score, beat)
            _int(beat.get('voice', 0), 0, 1, f'beat {identity} voice')
            _int(beat.get('cohort', 0), 0, 127, f'beat {identity} cohort')
            _fraction(beat.get('at'), f'beat {identity} at')
            _beat_strokes(beat)
            if is_percussion(track) and any(beat.get(k) is not None for k in ('stroke', 'pick_stroke')):
                raise ValueError(f'beat {identity}: percussion stroke/pick_stroke is unsupported')
            _validate_chord(beat.get('chord'), track)
            duration_quarters(beat.get('written'))
            if 'duration_source' in beat and beat['duration_source'] != 'tracker_boundary':
                raise ValueError(f'beat {identity}: unknown duration_source')
            if 'stem' in beat and beat['stem'] not in ('auto', 'up', 'down'):
                raise ValueError(f'beat {identity}: stem must be auto, up or down')
            if not isinstance(beat.get('notes'), list) or len(beat['notes']) > 25:
                raise ValueError(f'beat {identity}: notes must be a list of at most 25')
            for note in beat['notes']:
                _keys(note, ('id', 'pitch', 'string', 'fret', 'instrument', 'volume', 'velocity', 'spelling', 'channel',
                             'staccato', 'palm_mute', 'let_ring', 'dead', 'vibrato', 'bend', 'tremolo_bar', 'slide',
                             'ghost', 'accent', 'heavy_accent', 'hammer', 'harmonic',
                             'trill', 'tremolo_picking', 'grace', 'fade_in', 'tapping', 'slapping', 'popping'), 'note')
                if is_percussion(track):
                    _int(note.get('pitch'), 1, 100, f'note {note.get("id")} percussion key')
                    unsupported = [k for k in ('vibrato', 'slide',
                        'hammer', 'fade_in', 'tapping', 'slapping', 'popping')
                        if note.get(k)]
                    unsupported += [k for k in ('spelling', 'bend', 'tremolo_bar', 'harmonic',
                                               'trill') if note.get(k) is not None]
                    if unsupported:
                        raise ValueError(f'note {note.get("id")}: unsupported percussion technique {unsupported[0]}')
                if note.get('grace') is not None:
                    _validate_grace(note['grace'], track)
                repetitions = []
                for effect, rates in (('trill', (4, 8, 16, 32, 64)),
                                      ('tremolo_picking', (8, 16, 32))):
                    repetition = note.get(effect)
                    if repetition is None:
                        continue
                    repetitions.append(effect)
                    _keys(repetition, ('fret', 'value') if effect == 'trill' else ('value',), effect)
                    value = repetition.get('value')
                    if type(value) is not int or value not in rates:
                        raise ValueError(f'{effect}: unsupported repetition value')
                    if effect == 'trill':
                        _int(repetition.get('fret'), 0, track.get('max_fret', 29), 'trill fret')
                if repetitions and (len(repetitions) > 1 or
                        any(note.get(k) for k in ('dead', 'slide', 'hammer', 'vibrato')) or
                        any(note.get(k) is not None for k in ('bend', 'tremolo_bar'))):
                    raise ValueError('repetition conflicts with bend, tremolo_bar, slide, hammer, dead, vibrato or another repetition')
                if note.get('harmonic') is not None:
                    harmonic = note['harmonic']
                    _keys(harmonic, ('type', 'data'), 'harmonic')
                    if harmonic.get('type') not in ('natural', 'artificial', 'tapped', 'pinch', 'semi'):
                        raise ValueError('harmonic: unsupported type')
                    _int(harmonic.get('data', 0), 0, 5, 'harmonic data')
                for effect in ('staccato', 'palm_mute', 'let_ring', 'dead', 'vibrato', 'slide', 'ghost', 'accent', 'heavy_accent', 'hammer', 'fade_in', 'tapping', 'slapping', 'popping'):
                    if effect in note and type(note[effect]) is not bool:
                        raise ValueError(f'note {note.get("id")}: {effect} must be boolean')
                if sum(bool(note.get(k)) for k in ('tapping', 'slapping', 'popping')) > 1:
                    raise ValueError('tapping, slapping and popping are mutually exclusive per note')
                if note.get('let_ring') and (note.get('staccato') or note.get('palm_mute')):
                    raise ValueError('let_ring conflicts with staccato or palm_mute')
                for effect in ('bend', 'tremolo_bar'):
                    curve = note.get(effect)
                    if curve is None:
                        continue
                    _keys(curve, ('points',), effect)
                    points = curve.get('points')
                    if not isinstance(points, list) or len(points) > 129:
                        raise ValueError(f'{effect}: points must contain at most 129 entries')
                    previous = -1
                    for point in points:
                        _keys(point, ('position', 'value'), effect + ' point')
                        position = _int(point.get('position'), 0, 12, effect + ' position')
                        _int(point.get('value'), -12 if effect == 'tremolo_bar' else 0, 12, effect + ' value')
                        if position < previous:
                            raise ValueError(f'{effect}: point positions must be nondecreasing')
                        previous = position
                nid = _id(note.get('id'), 'note id')
                if nid in notes:
                    raise ValueError(f'{name}: duplicate note id {nid}')
                notes[nid] = (beat, note)
                pitch = _int(note.get('pitch'), 0, 119, f'note {nid} pitch')
                if (note.get('string') is None) != (note.get('fret') is None):
                    raise ValueError(f'note {nid}: string and fret must both be present or null')
                if note.get('string') is not None:
                    string = _int(note['string'], 1, len(track['tuning']), f'note {nid} string')
                    fret = _int(note['fret'], 1 if is_percussion(track) else 0,
                                100 if is_percussion(track) else track.get('max_fret', 29), f'note {nid} fret')
                    if track['tuning'][string - 1] + track.get('capo', 0) + fret != pitch:
                        raise ValueError(f'note {nid}: fingering does not match pitch')
                if 'instrument' in note:
                    _int(note['instrument'], 0, 99, f'note {nid} instrument')
                if 'channel' in note:
                    channel = _int(note['channel'], 0, channel_count - 1, f'note {nid} channel')
                    if channel not in track['channels']:
                        raise ValueError(f'note {nid}: playback channel must belong to its track')
                if 'volume' in note:
                    _int(note['volume'], 0, 64, f'note {nid} volume')
                if 'velocity' in note:
                    _int(note['velocity'], 0, 127, f'note {nid} velocity')
                if note.get('spelling') is not None:
                    spelling = note['spelling']
                    _keys(spelling, ('step', 'alter'), f'note {nid} spelling')
                    if spelling.get('step') not in ('C', 'D', 'E', 'F', 'G', 'A', 'B'):
                        raise ValueError(f'note {nid}: invalid spelling step')
                    alter = _int(spelling.get('alter', 0), -2, 2, f'note {nid} accidental')
                    if ('C D EF G A B'.index(spelling['step']) + alter) % 12 != pitch % 12:
                        raise ValueError(f'note {nid}: spelling does not match pitch')
            _resolved_notes(score, beat)
        _cohort_strokes(beats)
        note_ids[name] = notes
    ties = score.get('ties', [])
    if not isinstance(ties, list) or len(ties) > 12800:
        raise ValueError('score.ties must be a bounded list')
    incoming, outgoing = set(), set()
    for tie in ties:
        _keys(tie, ('from', 'to'), 'tie')
        linked = []
        for side, seen in (('from', outgoing), ('to', incoming)):
            endpoint = tie.get(side)
            _keys(endpoint, ('occurrence', 'note'), f'tie {side}')
            occurrence, nid = endpoint.get('occurrence'), endpoint.get('note')
            if not isinstance(occurrence, str) or occurrence not in order_ids:
                raise ValueError(f'tie {side}: unknown occurrence')
            name = str(orders[order_ids.index(occurrence)])
            if not isinstance(nid, str) or nid not in note_ids.get(name, {}):
                raise ValueError(f'tie {side}: unknown note {nid}')
            key = (occurrence, nid)
            if key in seen:
                raise ValueError(f'tie {side}: duplicate endpoint {key}')
            seen.add(key)
            beat, note = note_ids[name][nid]
            resolved = next(n for n in _resolved_notes(score, beat) if n['id'] == nid)
            linked.append((note['pitch'], beat['track'], beat.get('voice', 0), resolved['channel'],
                           note.get('instrument', _track(score, beat)['instrument']), note.get('volume')))
        if linked[0] != linked[1]:
            raise ValueError('tie continuity would change (pitch/channel/voice/instrument/volume); '
                             'remove or edit the tie explicitly before changing its note')


def _check_beat_span(beat, start, end, length, voices):
    """Same bounds/voice rule in row projection and exact quarter coordinates."""
    if not 0 <= start < end <= length:
        raise ValueError(f"beat {beat['id']}: outside pattern; split written duration and use a tie")
    spans = voices.setdefault((beat['track'], beat.get('voice', 0)), [])
    if any(start < b and a < end for a, b in spans):
        raise ValueError(f"beat {beat['id']}: overlapping beats in the same voice")
    spans.append((start, end))


_IT_PITCH = ('bend', 'tremolo_bar', 'vibrato', 'slide')
_IT_REPETITION = ('trill', 'tremolo_picking')
_IT_TECHNIQUES = ('staccato', 'palm_mute', 'dead', 'let_ring', 'ghost', 'accent', 'heavy_accent', 'hammer', 'harmonic', 'grace', 'fade_in') + _IT_PITCH + _IT_REPETITION
# Most effects are evaluated once on a tie chain; generated continuations do
# not repeat their attack notation. Clipped fragments have separate rules.
_SPLIT_UNSAFE = tuple(key for key in _IT_TECHNIQUES if key not in ('ghost', 'accent', 'heavy_accent'))
# Slide targets the next written beat, including a generated tied continuation.
_SPLIT_BOUNDARY_UNSAFE = ('slide',)


def sampled_timing_projection(song, module, default_volume):
    """Export-only escape for sub-tick timing: sample bounded, silent-ended passages.

    Strict document validation/editing never calls this. Keep normal notes outside
    each affected string's passage, and use the native renderer for its complete
    voice history (including release tails and note replacement ramps).
    """
    import numpy as np
    from dataclasses import replace
    from .model import Channel, Instrument, Sample, Pattern
    from .itwriter import write_it
    from .openmpt import LoadedModule

    rate = 88200
    if _has_repeats(song) or len(set(song['orders'])) != len(song['orders']):
        raise ValueError('IT sampled timing needs unique, unrepeated orders')
    if module.plugins:
        raise ValueError('IT sampled timing cannot separate routed/master plugins')
    plan = playback_plan(song, module.patterns, rate)
    attacks = [e for e in plan['events'] if e['type'] == 'note_on']
    offs = {e['id']: e for e in plan['events'] if e['type'] == 'note_off'}
    final_pulses = {}
    for e in attacks:
        if 'pulse' in e:
            final_pulses[e['source_id']] = max(final_pulses.get(e['source_id'], (-1, '')), (e['pulse'], e['id']))
    final_ids = {identity for _, identity in final_pulses.values()}
    inexact = {e['id'] for e in plan['events'] if (Fraction(*e['at']) * 24).denominator != 1 and not (
        e['type'] == 'note_off' and e['id'] in final_ids and
        (Fraction(*e['at']) * 24 + Fraction(1, 40)).denominator == 1)}
    affected = [e for e in attacks if e['id'] in inexact]
    if not affected:
        raise ValueError('IT sampled timing found no sub-tick events; original cell conflict remains unsupported')
    channels = sorted({e['ch'] for e in affected})
    if len(module.samples) + len(channels) > 99 or module.instruments is not None and len(module.instruments) + len(channels) > 99:
        raise ValueError('IT sampled timing needs free sample/instrument slots (maximum 99)')
    duration = Fraction(*plan['duration']['quarters'])
    if plan['duration']['frames'] > rate * 600:
        raise ValueError('IT sampled timing is limited to ten-minute arrangements; split the song')
    clock = TempoClock(module.tempo, plan.get('tempos'))
    step = Fraction(module.speed, 24)
    anchors = [row * step for row in range(int(duration / step) + 1)]
    frames = [round(clock.seconds_at(q) * rate) for q in anchors]
    patterns = {p.name: i for i, p in enumerate(module.patterns)}
    blank = [Pattern(p.name, [[Cell(effect=c.effect, param=c.param) if c.effect == 20 and c.param >= 32
                              else Cell() for c in row] for row in p.rows]) for p in module.patterns]
    # A one-channel backing retains global tempo commands from every source lane.
    backing = [Pattern(p.name, [[next((c for c in row if c.effect == 20), Cell())] for row in p.rows]) for p in blank]
    rendered, sampled_ids, sampled_keys = [], set(), set()
    for channel in channels:
        notes = [e for e in attacks if e['ch'] == channel]
        for e in notes:
            default_volume(e['instrument'], e['pitch'], require_harmonic=True)
            if e['instrument_inherited']:
                raise ValueError('IT sampled timing requires explicit instruments')
            ins = module.instruments[e['instrument'] - 1] if module.instruments is not None else None
            number = ins.keymap[e['pitch']][1] if ins else e['instrument']
            if len(module.samples[number - 1].data) != 1:
                raise ValueError('IT sampled timing needs mono source samples to preserve channel pan')
        if any(p.lanes or any(not c.is_empty() and not (c.effect == 20 and c.param >= 32 and
                c.note is None and not c.instrument and c.volcmd is None)
                for row in p.rows for c in [row[channel]]) for p in module.patterns):
            raise ValueError('IT sampled timing cannot replace raw notes, mix controls or automation on the affected lane')
        local = copy.deepcopy(plan)
        local['events'] = [dict(e, ch=0) for e in local['events'] if e['ch'] == channel]
        neutral = replace(module, channels=[Channel()], patterns=backing, global_volume=128,
                          mix_volume=128, separation=128, score_projection=None, native_score=None)
        with LoadedModule(write_it(neutral), rate, 1, plan=local) as player:
            pcm = np.frombuffer(player.render(rate, oversample=1, floats=True), '<f4').reshape(-1, 2).sum(axis=1)
        if not np.isfinite(pcm).all() or np.max(np.abs(pcm), initial=0) >= 1:
            raise ValueError('IT sampled timing would clip; reduce the source sample/instrument gain')
        spans = [(Fraction(*e['at']), Fraction(*offs[e['id']]['at'])) for e in notes]
        # Do not cut through a written pulse/tie source when the performed voice is momentarily silent.
        spans += [(Fraction(*p['at']), Fraction(*p['end']))
                  for p in plan['positions'] if p['ch'] == channel]
        def quiet(index):
            q, f = anchors[index], frames[index]
            window = pcm[max(0, f - rate // 100):min(len(pcm), f + rate // 100)]
            return (len(window) >= rate // 100 and np.max(np.abs(window), initial=0) == 0
                    and not any(a < q < b for a, b in spans))
        ranges = []
        for event in (e for e in affected if e['ch'] == channel):
            first, last = Fraction(*event['at']), Fraction(*offs[event['id']]['at'])
            begin = next((i for i in range(bisect_left(anchors, first)-1, -1, -1) if quiet(i)), None)
            end = next((i for i in range(bisect_right(anchors, last), len(anchors)) if quiet(i)), None)
            if begin is None or end is None:
                raise ValueError('IT sampled timing needs silent row boundaries around the affected passage')
            if ranges and begin <= ranges[-1][1]:
                ranges[-1] = (ranges[-1][0], max(end, ranges[-1][1]))
            else:
                ranges.append((begin, end))
        for begin, end in ranges:
            a, b = anchors[begin], anchors[end]
            sampled_ids.update(e['id'] for e in notes if a <= Fraction(*e['at']) < b)
            sampled_keys.update((p['pattern'], p['note']) for p in plan['positions']
                                if p['ch'] == channel and a <= Fraction(*p['at']) < b)
            rendered.append((channel, a, b, np.rint(pcm[frames[begin]:frames[end]] * 32768).astype(np.int16)))
    if len(module.samples) + len(rendered) > 99 or module.instruments is not None and len(module.instruments) + len(rendered) > 99:
        raise ValueError('IT sampled timing needs free sample/instrument slots (maximum 99)')
    filtered = dict(plan, events=[e for e in plan['events'] if e['id'] not in sampled_ids], _sampled_notes=sampled_keys)
    projection = project_score(song, module.patterns, default_volume, _plan=filtered)
    # No samples/instruments are installed until all guards and normal-note projection pass.
    samples, instruments = list(module.samples), None if module.instruments is None else list(module.instruments)
    for ch, a, b, pcm in rendered:
        occurrence = next(o for o in plan['occurrences'] if Fraction(*o['at']) <= a < Fraction(*o['at']) + Fraction(*o['duration']))
        pindex = patterns[occurrence['pattern']]
        factor = len(projection.patterns[pindex].rows) // len(module.patterns[pindex].rows)
        row = int((a - Fraction(*occurrence['at'])) / step) * factor
        cell = projection.patterns[pindex].rows[row][ch]
        if cell.note is not None or cell.instrument or cell.volcmd is not None:
            raise ValueError('IT sampled timing overlaps an existing cell at its silent boundary')
        label = f'Timed ch{ch+1} {a}-{b}'
        samples.append(Sample(name=label[:25], data=[pcm], c5_speed=rate, rate=rate))
        if instruments is not None:
            instruments.append(Instrument(name=label[:25], keymap=[(60, len(samples))] * 120))
        cell.note, cell.instrument, cell.volcmd = 60, len(instruments) if instruments is not None else len(samples), 64
        projection.diagnostics.append(f'IT timing: channel {ch+1}, quarters {a} to {b} rendered into a sample to preserve '
                                      'sub-tick attacks, gates and release tails. Other passages remain tracker notes; '
                                      'the native source keeps every editable note.')
    module.samples, module.instruments = samples, instruments
    module.message += '\n' + '\n'.join(d for d in projection.diagnostics if d.startswith('IT timing:'))
    return projection


def project_score(song, raw_patterns, default_volume=None, *, _plan=None):
    """Try the authored rows first, then subdivide only exact IT-cell collisions."""
    try:
        return _project_score(song, raw_patterns, default_volume, _plan=_plan)
    except ValueError as error:
        if _has_repeats(song):
            raise  # The expanded traversal retries its own exact cells.
        message = str(error)
        if not any(reason in message for reason in (
                'attacks share an IT cell', 'conflicting note at', 'conflicting effect at',
                'delayed technique release would delay', 'note delay beyond SDf',
                'row quantization loses a pitch', 'row-quantized pitch exceeds')):
            raise
        plan = _plan or _playback_plan(song, raw_patterns)
        speed = song.get('module', {}).get('speed', 6)
        finer = 1 if ('row quantization loses a pitch' in message or 'row-quantized pitch exceeds' in message) else speed
        final_pulses = {}
        for event in plan['events']:
            if event['type'] == 'note_on' and 'pulse' in event:
                final_pulses[event['source_id']] = max(final_pulses.get(event['source_id'], (-1, '')),
                                                      (event['pulse'], event['id']))
        final_pulse_ids = {identity for _, identity in final_pulses.values()}
        for event in plan['events']:
            if event['type'] in ('note_on', 'note_off'):
                ticks = Fraction(*event['at']) * 24
                if (event['type'] == 'note_off' and event['id'] in final_pulse_ids and
                        ticks.denominator != 1 and (ticks + Fraction(1, 40)).denominator == 1):
                    ticks += Fraction(1, 40)  # Same documented final-pulse tail as the release projector.
                if ticks.denominator != 1:
                    raise error
                finer = math.gcd(finer, int(ticks))
        if finer == speed:
            raise
        factor = speed // finer
        # Tick duration stays unchanged: envelopes, sample pitch and absolute
        # tempo retain their clock. Per-row slides/delays/automation do not.
        for pattern in raw_patterns:
            if len(pattern.rows) * factor > 1024:
                raise ValueError(f'{error}; {pattern.name}: exact IT timing needs more than 1024 rows; split the pattern') from error
            if pattern.lanes or any(
                    cell.effect and not (cell.effect == 20 and cell.param >= 32 or cell.effect == 24)
                    or cell.volcmd is not None and cell.volcmd > 64
                    for row in pattern.rows for cell in row):
                raise ValueError(f'{error}; {pattern.name}: exact IT row subdivision cannot preserve raw tick/row effects or automation') from error
        expanded = copy.deepcopy(song)
        expanded.setdefault('module', {})['speed'] = finer
        patterns = copy.deepcopy(raw_patterns)
        for pattern in patterns:
            pattern.rows = [new for row in pattern.rows for new in
                            [row] + [[Cell() for _ in row] for _ in range(factor - 1)]]
            expanded['patterns'][pattern.name]['rows'] = len(pattern.rows)
            spec = expanded['score']['patterns'].get(pattern.name)
            if spec is not None:
                spec['row_step'] = _pair(Fraction(finer, 24))
        result = _project_score(expanded, patterns, default_volume, _plan=plan)
        for pattern in result.patterns:
            slot = next((cell for cell in pattern.rows[0] if not cell.effect and not cell.param), None)
            if slot is None:
                raise ValueError(f'{pattern.name}: exact IT row subdivision needs a free row-zero effect slot') from error
            slot.effect, slot.param = 1, finer
        result.diagnostics.append(f'IT notation: exact rhythm uses {factor} export rows per authored row; '
                                  'tempo, tick duration and source patterns are unchanged.')
        return result


def _project_score(song, raw_patterns, default_volume=None, *, _plan=None):
    """Return fresh patterns and JSON-safe links; never mutate cached compiler cells.

    The standalone IT conversion. An authored velocity scales the attack's volume as native playback does (gain
    velocity/127): the volume column gets round(base * velocity / 127), half up, where base is the note's own volume or
    `default_volume(instrument, pitch)`, the default volume of the sample IT plays (64 when not given). A note whose
    release falls on the end of the song needs no note-off: the module ends there."""
    projection = Projection(copy.deepcopy(raw_patterns), raw_patterns)
    if 'score' not in song:
        return projection
    validate_score(song)
    score = song['score']
    if any(track.get('lyrics', {}).get('text') for track in score['tracks'].values()):
        projection.diagnostics.append('IT notation: lyrics omitted; lyrics do not synthesize vocals. The source score retains them.')
    if any(b.get('chord') is not None for p in score['patterns'].values() for b in p['beats']):
        projection.diagnostics.append('IT notation: chord diagrams omitted; diagrams do not generate notes. Existing chord notes and source diagrams are retained.')
    if _has_repeats(song):
        result = _project_repeated_score(song, raw_patterns, default_volume)
        result.diagnostics = list(dict.fromkeys(projection.diagnostics + result.diagnostics))
        return result
    has_swing = any(m.get('swing', 'none') != 'none' for m in score.get('measures', []))
    markings = [k for k in ('tapping', 'slapping', 'popping') if any(
        n.get(k) for p in score['patterns'].values() for b in p['beats'] for n in b['notes'])]
    if markings:
        projection.diagnostics.append('IT notation: ' + ', '.join(markings) +
            ' markings omitted; these markings do not change native playback. The source score retains them.')
    names = {p.name: i for i, p in enumerate(raw_patterns)}
    orders = [str(o) for o in song.get('orders', [])]
    if any(o not in names for o in orders):
        raise ValueError('score projection: skip/end order markers are not supported yet')
    speed = _int(song.get('module', {}).get('speed', 6), 1, 255, 'module.speed')
    for p in raw_patterns:
        for row in p.rows:
            for cell in row:
                if cell.effect in (1, 2, 3) or cell.effect == 19 and cell.param >> 4 in (6, 11, 14):
                    raise ValueError(f'{p.name}: raw speed/jump/loop/row-delay commands need an exact timing map')
    records = {}
    for name, spec in score['patterns'].items():
        if name not in names:
            raise ValueError(f'{name}: compiled pattern is missing')
        step = _fraction(spec['row_step'], f'{name} row_step', True)
        if step != Fraction(speed, 24):
            raise ValueError(f'{name}: row_step must equal module.speed/24; regridding is unsupported')
        pindex, pattern = names[name], projection.patterns[names[name]]
        voice_spans = {}
        cohorts = _cohort_strokes(spec['beats'])
        for beat in spec['beats']:
            at, duration = _fraction(beat['at'], 'beat at'), duration_quarters(beat['written'])
            start, end = at / step, (at + duration) / step
            subrow = bool(beat['notes']) and (start.denominator != 1 or end.denominator != 1)
            if subrow and ((at * 24).denominator != 1 or ((at + duration) * 24).denominator != 1):
                raise ValueError(f"beat {beat['id']}: exact timing {at}+{duration} is not representable on row_step {step}")
            _check_beat_span(beat, start, end, len(pattern.rows), voice_spans)
            # Cell coverage is conservative; at/duration retain exact musical time.
            # Silent rests need no IT cells; sounding subrow timing uses the existing SDx path.
            start, end = math.floor(start), math.ceil(end)
            base = dict(pattern=pindex, pattern_name=name, beat=beat['id'], track=beat['track'],
                        voice=beat.get('voice', 0), row=start, end_row=end, at=_pair(at), duration=_pair(duration),
                        stem=beat.get('stem', _track(score, beat).get('stem', 'auto')))
            if 'duration_source' in beat:
                base['duration_source'] = beat['duration_source']
            projection.positions.append(dict(base, kind='beat'))
            for note in _resolved_notes(score, beat):
                rec = dict(base, note=note['id'], ch=note['channel'], pitch=note['pitch'],
                           string=note['string'], fret=note['fret'], kind='note',
                           instrument=note.get('instrument', _track(score, beat)['instrument']))
                if 'volume' in note:
                    rec['volume'] = note['volume']
                if 'velocity' in note:
                    rec['velocity'] = note['velocity']
                rec['pitch_technique'] = any(note.get(k) for k in _IT_PITCH)
                rec['repetition'] = any(note.get(k) for k in _IT_REPETITION)
                rec['grace'] = note.get('grace') is not None
                rec['stroke'] = 'stroke' in cohorts[_cohort_key(beat)]
                rec['swing'] = False  # The performed plan, including source repeat phase, decides eligibility.
                rec['subrow'] = subrow
                records[name, note['id']] = rec
                projection.positions.append(rec)
                if note['string'] is None:
                    projection.diagnostics.append(f"{name}/{note['id']}: pitch {note['pitch']} has no available fingering")
    starts, cursor = [], 0
    for name in orders:
        starts.append(cursor)
        cursor += len(raw_patterns[names[name]].rows)
    occurrences = {oid: i for i, oid in enumerate(score['order_ids'])}
    _validate_measure_timeline(score, {oid: (starts[oi] * Fraction(speed, 24),
        len(raw_patterns[names[orders[oi]]].rows) * Fraction(speed, 24)) for oid, oi in occurrences.items()})
    tied_in, tied_out = set(), set()
    for tie in score.get('ties', []):
        ends = []
        for side in ('from', 'to'):
            endpoint = tie[side]
            oi = occurrences[endpoint['occurrence']]
            rec = records[orders[oi], endpoint['note']]
            ends.append((oi, rec))
        (a, left), (b, right) = ends
        if (starts[a] * Fraction(speed, 24) + Fraction(*left['at']) + Fraction(*left['duration']) !=
                starts[b] * Fraction(speed, 24) + Fraction(*right['at']) or
                left['pitch'] != right['pitch'] or left['ch'] != right['ch'] or
                left['track'] != right['track'] or left['voice'] != right['voice'] or
                left['instrument'] != right['instrument'] or left.get('volume') != right.get('volume')):
            raise ValueError('tie: endpoints must be adjacent, same pitch/channel/voice/instrument')
        tied_out.add((a, left['note']))
        tied_in.add((b, right['note']))
    # A compiled Pattern is shared by every occurrence; context-dependent cells
    # must not be inferred from whichever occurrence happens to come first.
    flags = {}
    for (name, nid), rec in records.items():
        uses = [i for i, n in enumerate(orders) if n == name]
        states = {(i, nid) in tied_in for i in uses}
        releases = {(i, nid) in tied_out for i in uses}
        if len(states) > 1 or len(releases) > 1:
            raise ValueError(f'{name}/{nid}: occurrence-dependent tie; make this pattern unique')
        flags[name, nid] = (True in states, True in releases)

    subrow_patterns = {name for (name, _), rec in records.items() if rec['subrow']}
    if subrow_patterns or has_swing or any(b.get('stroke') is not None or any(n.get(k) for n in b['notes'] for k in _IT_TECHNIQUES)
           for p in score['patterns'].values() for b in p['beats']):
        # The native plan owns TG dynamics, gate precedence, ties and let-ring lookup.
        # Repeated exports supply the original performed plan, retaining repeat-close provenance.
        if any(name not in orders and any(has_swing or name in subrow_patterns or b.get('stroke') is not None or
               any(n.get(k) for n in b['notes'] for k in _IT_TECHNIQUES) for b in spec['beats'])
               for name, spec in score['patterns'].items()):
            raise ValueError('unplayed pattern has techniques without a performed context; include it in orders')
        _plan = _plan or _playback_plan(song, raw_patterns)
        for position in _plan['positions']:
            if position.get('swing'):
                records[orders[occurrences[position['occurrence']]], position['note']]['swing'] = True
        velocities = {}
        for event in _plan['events']:
            if event['type'] == 'note_on' and event.get('role') != 'grace':
                if event['instrument_inherited']:
                    raise ValueError('standalone techniques need explicit note instruments; inherited volume state is unsupported')
                key = orders[occurrences[event['occurrence']]], event['note']
                velocities.setdefault(key, set()).add(event['velocity'])
        for key, values in velocities.items():
            if len(values) != 1:
                raise ValueError(f'{key}: occurrence-dependent technique velocity; make this pattern unique')
            value, = values
            if value is not None:
                records[key]['velocity'] = value

    retirements = []
    if _plan is not None and any('layers' in e for e in _plan['events']):
        _plan, raw_patterns, retirements = _project_harmonic_layers(
            _plan, projection, records, flags, orders, occurrences, default_volume)

    def put(pindex, row, ch, attribute, value, rec, role):
        cell = projection.patterns[pindex].rows[row][ch]
        address = (pindex, row, ch, attribute)
        default = None if attribute in ('note', 'volcmd') else 0
        if address in projection.owners or getattr(cell, attribute) != default:
            raise ValueError(f"{rec['pattern_name']}/{rec['note']}: conflicting {attribute} at pattern {pindex} row {row} channel {ch}")
        setattr(cell, attribute, value)
        projection.owners[address] = dict(pattern=rec['pattern_name'], beat=rec['beat'], note=rec['note'], role=role)

    occupied = {}
    for key, rec in records.items():
        p, start, end, ch = rec['pattern'], rec['row'], rec['end_row'], rec['ch']
        spans = occupied.setdefault((p, ch), [])
        exact_start = Fraction(*rec['at'])
        exact_end = exact_start + Fraction(*rec['duration'])
        if any(exact_start < b and a < exact_end for a, b in spans):
            raise ValueError(f"{key}: overlapping notes require independent channels")
        spans.append((exact_start, exact_end))
        for row in range(start, end):
            raw = raw_patterns[p].rows[row][ch]
            if raw.note is not None or raw.instrument:
                raise ValueError(f'{key}: raw note/instrument interrupts score-owned sustain at row {row}')
            if raw.effect == 19 and raw.param >> 4 in (12, 13):
                raise ValueError(f'{key}: raw note cut/delay needs explicit score timing')
        incoming, outgoing = flags[key]
        if _plan is not None and key in _plan.get('_sampled_notes', ()):
            continue  # Export-only rendered passage; source ownership was still validated above.
        drum_volume = None
        if is_percussion(score['tracks'][rec['track']]) and default_volume is not None:
            # Keep the authored drum key: the IT instrument's existing keymap selects sample and playback pitch.
            # Validate every drum attack/continuation, even without an authored velocity.
            drum_volume = default_volume(rec['instrument'], rec['pitch'], require_sample=True)
        if not incoming and not rec['repetition'] and not rec['grace'] and not rec['stroke'] and not rec['swing'] and not rec['subrow']:
            put(p, start, ch, 'note', rec['pitch'], rec, 'attack')
            put(p, start, ch, 'instrument', rec['instrument'], rec, 'attack')
            if 'velocity' in rec:
                base = (rec['volume'] if 'volume' in rec else drum_volume if drum_volume is not None
                        else (default_volume or (lambda *_: 64))(rec['instrument'], rec['pitch']))
                put(p, start, ch, 'volcmd', int(Fraction(base * rec['velocity'], 127) + Fraction(1, 2)), rec, 'attack')
            elif 'volume' in rec:
                put(p, start, ch, 'volcmd', rec['volume'], rec, 'attack')
    if _plan is not None:
        _project_performed_attacks(_plan, projection, records, orders, names, starts, speed, put, default_volume)
        _project_performed_releases(_plan, projection, records, orders, names, starts, speed, put)
        _project_pitch_controls(song, _plan, projection, records, orders, names, starts, speed, put, default_volume)
        _project_layer_retirements(retirements, projection, records, orders, names, starts, occurrences, speed, put)
        _project_fade_controls(_plan, projection, records, orders, names, starts, speed, put, default_volume)
        return projection
    for key, rec in records.items():
        if flags[key][1]:
            continue
        p, row, ch = rec['pattern'], rec['end_row'], rec['ch']
        destinations = {(p, row)}
        if row == len(raw_patterns[p].rows):
            uses = [i for i, name in enumerate(orders) if name == rec['pattern_name']]
            if not uses:
                raise ValueError(f'{key}: release at an unplayed pattern boundary is unsupported; leave a release row')
            destinations = {(names[orders[i + 1]], 0) for i in uses if i + 1 < len(orders)}   # at the song's end, none
        for dp, dr in destinations:
            existing = projection.owners.get((dp, dr, ch, 'note'))
            if existing and existing['role'] == 'attack':
                continue  # The next attack ends this voice without a note-off cell.
            raw_note = raw_patterns[dp].rows[dr][ch].note
            if raw_note is not None and 0 <= raw_note <= 119:
                continue  # A following residual attack is also an explicit boundary.
            if row == len(raw_patterns[p].rows):
                # Only an emitted release must be valid in every destination
                # use. An existing attack already ends the preceding voice.
                # A release at song start has no preceding voice to truncate.
                for oi, name in enumerate(orders):
                    if name == raw_patterns[dp].name and oi > 0 and orders[oi - 1] != rec['pattern_name']:
                        raise ValueError(f'{key}: occurrence-dependent boundary release; make patterns unique')
            put(dp, dr, ch, 'note', NOTE_OFF, rec, 'release')
    return projection


def _project_harmonic_layers(plan, projection, records, flags, orders, occurrences, default_volume):
    """Route the native layer list into fixed export lanes, retaining its last/primary layer on the parent."""
    attacks = {e['id']: e for e in plan['events'] if e['type'] == 'note_on'}
    offs = {e['id']: e['at'] for e in plan['events'] if e['type'] == 'note_off'}
    counts = {}
    for e in attacks.values():
        if 'layers' in e:
            if offs[e['id']] == plan['duration']['quarters']:
                raise ValueError('IT harmonic release at song end needs a following release row')
            if e['instrument_inherited'] or 'pulse' in e:
                raise ValueError('IT harmonics require explicit instruments and independent non-pulse layers')
            counts[e['ch']] = max(counts.get(e['ch'], 0), len(e['layers']) - 1)
    original = len(projection.patterns[0].rows[0])
    if original + sum(counts.values()) > 64:
        raise ValueError('IT harmonic layers exceed the 64-channel limit')
    lanes = {}
    for parent, count in sorted(counts.items()):
        lanes[parent] = list(range(original + len(projection.channel_parents),
                                   original + len(projection.channel_parents) + count))
        projection.channel_parents.update({ch: parent for ch in lanes[parent]})
        # Native group children inherit the parent's state and selected live effects. Do not silently discard it.
        for pattern in projection.raw_patterns:
            for row in pattern.rows:
                cell = row[parent]
                if cell.note is not None or cell.instrument or cell.volcmd is not None or cell.effect not in (0, 20, 22):
                    raise ValueError('IT harmonic parent has raw channel state; move it to an independent channel')
        if default_volume is not None:
            for rec in records.values():
                if rec['ch'] == parent:
                    default_volume(rec['instrument'], rec['pitch'], require_harmonic=True)
    raw = copy.deepcopy(projection.raw_patterns)
    for patterns in (raw, projection.patterns):
        for pattern in patterns:
            for row in pattern.rows:
                row.extend(Cell() for _ in projection.channel_parents)
    layers_by_key = {}
    for position in plan['positions']:
        attack = attacks.get(position['attack_id'])
        if attack is None:
            continue
        key = orders[occurrences[position['occurrence']]], position['note']
        layers = attack.get('layers')
        if key in layers_by_key and layers_by_key[key] != layers:
            raise ValueError('occurrence-dependent harmonic layers; make this pattern unique')
        layers_by_key[key] = layers
    note_ids = {}
    for key, layers in layers_by_key.items():
        if layers is None:
            continue
        source = dict(records[key])
        for index, layer in enumerate(layers):
            primary = index == len(layers) - 1
            nid = source['note'] if primary else source['note'] + f'/it-layer/{index}'
            if not primary and (key[0], nid) in records:
                raise ValueError('IT harmonic generated note identity collides with authored note')
            ch = source['ch'] if primary else lanes[source['ch']][index]
            if default_volume is not None:
                default_volume(source['instrument'], layer['pitch'], require_harmonic=True)
            records[key[0], nid] = dict(source, note=nid, ch=ch, **layer)
            flags[key[0], nid] = flags[key]
            note_ids[key, index] = nid
    events, retirements = [], []
    for event in plan['events']:
        attack = attacks[event['id']]
        layers = attack.get('layers')
        if layers is None:
            events.append(event)
        else:
            key = orders[occurrences[attack['occurrence']]], attack['note']
            for index, layer in enumerate(layers):
                primary = index == len(layers) - 1
                eid = event['id'] if primary else event['id'] + f'/it-layer/{index}'
                if not primary and eid in attacks:
                    raise ValueError('IT harmonic generated attack identity collides with native note')
                e = dict(event, id=eid, note=note_ids[key, index],
                         ch=event['ch'] if primary else lanes[event['ch']][index], **layer)
                e.pop('layers', None)
                if event['type'] == 'gain':
                    e['gains'] = [event['gains'][index]]
                events.append(e)
        if event['type'] == 'note_on' and event['ch'] in lanes:
            # Snd_fx::ConsumeEventGroupNNA retires all siblings at the next parent attack, even after key-off.
            used = len(layers) - 1 if layers else 0
            retirements.extend((event, ch) for ch in lanes[event['ch']][used:])
    return dict(plan, events=events), raw, retirements


def _project_layer_retirements(retirements, projection, records, orders, names, starts, occurrences, speed, put):
    requests = {}
    for attack, ch in retirements:
        ticks = Fraction(*attack['at']) * 24
        if ticks.denominator != 1:
            raise ValueError('IT harmonic retirement is off the IT tick grid')
        absolute, delay = divmod(int(ticks), speed)
        if delay > 15:
            raise ValueError('IT harmonic retirement needs a note delay beyond SDf')
        oi = bisect_right(starts, absolute) - 1
        p, row = names[orders[oi]], absolute - starts[oi]
        requests.setdefault((p, row, ch), []).append((oi, delay, attack))
    for (p, row, ch), values in requests.items():
        if {oi for oi, _, _ in values} != {i for i, name in enumerate(orders) if names[name] == p} or len({d for _, d, _ in values}) != 1:
            raise ValueError('occurrence-dependent harmonic retirement; make this pattern unique')
        oi, delay, attack = values[0]
        rec = records[orders[occurrences[attack['occurrence']]], attack['note']]
        cell = projection.patterns[p].rows[row][ch]
        owner = projection.owners.get((p, row, ch, 'note'))
        if cell.note == NOTE_OFF and owner and owner['role'] == 'release' and not delay and not cell.effect:
            cell.note = NOTE_CUT
        else:
            put(p, row, ch, 'note', NOTE_CUT, rec, 'layer retirement')
            if delay:
                put(p, row, ch, 'effect', 19, rec, 'layer retirement')
                put(p, row, ch, 'param', 0xD0 | delay, rec, 'layer retirement')


def _project_pitch_controls(song, plan, projection, records, orders, names, starts, speed, put, default_volume):
    """Native discrete controls -> IT fine linear slides; bounded row-time quantization, no musical re-interpretation."""
    if not any(r['pitch_technique'] for r in records.values()):
        return
    if not song.get('module', {}).get('linear_slides', True):
        raise ValueError('IT pitch techniques require linear_slides')
    step = Fraction(speed, 24)
    occurrences = {o['id']: i for i, o in enumerate(plan['occurrences'])}
    attacks = {(Fraction(*e['at']), e['ch']) for e in plan['events'] if e['type'] == 'note_on'}
    offs = {e['id']: Fraction(*e['at']) for e in plan['events'] if e['type'] == 'note_off'}
    controls = {}
    for event in plan['events']:
        if event['type'] == 'pitch':
            controls.setdefault(event['id'], []).append(event)
    requests, rounded = {}, False
    for attack in plan['events']:
        if attack['type'] != 'note_on' or attack.get('role') == 'grace':
            continue
        oi = occurrences[attack['occurrence']]
        rec = records[orders[oi], attack['note']]
        if not rec['pitch_technique']:
            continue
        events = controls.get(attack['id'], [])
        if not events:
            source = next(n for n in _beat(song['score'], orders[oi], rec['beat'])['notes'] if n['id'] == rec['note'])
            if source.get('slide'):
                # TG addSlide emits nothing when the immediate next beat has
                # no same-string note (including a rest inserted by Shorter).
                # Retain the written slide; its plain attack needs no IT bend.
                continue
            raise ValueError(f"{attack['id']}: pitch technique has no native target/control events (slide needs a following same-string target)")
        if default_volume is not None:
            default_volume(attack['instrument'], attack['pitch'], require_pitch=True)
        start, end, ch = Fraction(*attack['at']), offs[attack['id']], attack['ch']
        native, quantized = {start: 0}, {start: 0}
        for event in events:
            at, value = Fraction(*event['at']), event['bend_value'] - 64
            if at > end:
                raise ValueError(f"{attack['id']}: pitch controls after key-off need independent voice ownership")
            native[at] = value  # coincident native controls retain their final value, including resets
            row_at = int(at / step + Fraction(1, 2)) * step
            rounded |= row_at != at
            quantized[row_at] = value
        # A new attack resets the channel period. Do not apply the prior voice's final controls to that new note.
        if (end, ch) in attacks or end == Fraction(*plan['duration']['quarters']):
            quantized[end] = 0
        def turns(values):
            distinct = [v for i, v in enumerate(values) if not i or v != values[i - 1]]
            return [v for i, v in enumerate(distinct) if i in (0, len(distinct) - 1)
                    or (v - distinct[i - 1]) * (distinct[i + 1] - v) < 0]
        if turns(list(native.values())) != turns([v for _, v in sorted(quantized.items())]):
            raise ValueError(f"{attack['id']}: row quantization loses a pitch endpoint or turning point")
        # Bound the entire discrete trajectory, including collapsed changes, not just individual rounded points.
        a = b = 0
        for at in sorted(native.keys() | quantized.keys()):
            a, b = native.get(at, a), quantized.get(at, b)
            if abs(a - b) > 2 and not (at >= end and ((end, ch) in attacks or end == Fraction(*plan['duration']['quarters']))):
                raise ValueError(f"{attack['id']}: row-quantized pitch exceeds 37.5-cent trajectory bound")
        previous = 0
        for at, value in sorted(quantized.items()):
            if at >= end and ((end, ch) in attacks or end == Fraction(*plan['duration']['quarters'])):
                continue
            if at != start and (at, ch) in attacks:
                raise ValueError(f"{attack['id']}: rounded pitch control lands on another attack")
            delta = value - previous
            if not delta:
                continue
            # Fine portamento x uses 4*x linear-slide units: one native step (3/16 semitone) is FF3/EF3.
            amount = abs(delta) * 3
            if amount > 15:
                raise ValueError(f"{attack['id']}: pitch step/reset exceeds one IT fine-portamento command")
            absolute_row = int(at / step)
            target = bisect_right(starts, absolute_row) - 1
            p, row = names[orders[target]], absolute_row - starts[target]
            if projection.patterns[p].rows[row][ch].effect or projection.patterns[p].rows[row][ch].param:
                raise ValueError(f"{attack['id']}: pitch control conflicts with an existing tracker effect")
            requests.setdefault((p, row, ch), []).append((target, 6 if delta > 0 else 5, 0xF0 | amount, rec))
            previous = value
    for (p, row, ch), values in requests.items():
        uses = {i for i, name in enumerate(orders) if names[name] == p}
        if {oi for oi, *_ in values} != uses or len({(fx, param) for _, fx, param, _ in values}) != 1:
            raise ValueError('occurrence-dependent pitch controls; make this pattern unique')
        _, effect, param, rec = values[0]
        put(p, row, ch, 'effect', effect, rec, 'pitch')
        put(p, row, ch, 'param', param, rec, 'pitch')
    if rounded:
        projection.diagnostics.append('IT pitch: controls rounded to nearest tracker row (at most half a row); '
                                      'discrete trajectory error at most 37.5 cents, plus IT frequency/tick rounding')


def _project_fade_controls(plan, projection, records, orders, names, starts, speed, put, default_volume):
    """Shared expression -> owned IT volume cells; bound the full normalized gain trajectory."""
    gains = {}
    for e in plan['events']:
        if e['type'] == 'gain':
            gains.setdefault(e['id'], []).append(e)
    if not gains:
        return
    step, end = Fraction(speed, 24), Fraction(*plan['duration']['quarters'])
    occurrences = {o['id']: i for i, o in enumerate(plan['occurrences'])}
    attacks = [e for e in plan['events'] if e['type'] == 'note_on']
    parents = projection.channel_parents
    channels = {e['ch'] for e in attacks if e['id'] in gains}
    for pattern in projection.raw_patterns:
        for row in pattern.rows:
            for ch in channels:
                if ch >= len(row): continue  # Export-only harmonic lanes have no raw content.
                cell = row[ch]
                if cell.volcmd is not None or cell.effect not in (0, 13, 20, 22, 24):
                    raise ValueError('IT fade_in: raw volume/effect ownership on an expression channel is unsupported')
    requests, rounded, worst = {}, False, 0.0
    for attack in attacks:
        controls = gains.get(attack['id'])
        if not controls: continue
        start, ch = Fraction(*attack['at']), attack['ch']
        parent = parents.get(ch, ch)
        successors = [Fraction(*e['at']) for e in attacks
                      if parents.get(e['ch'], e['ch']) == parent and Fraction(*e['at']) > start]
        stop = min(successors, default=end)
        if all(e['expression'] == 127 for e in controls if Fraction(*e['at']) < stop):
            continue  # A neutral, newly struck instrument already resets its own volume.
        if (start / step).denominator != 1:
            raise ValueError('IT fade_in: affected attacks must be row-aligned; delayed volume ownership is unsupported')
        source = occurrences[attack['occurrence']]
        rec = records[orders[source], attack['note']]
        base = (default_volume or (lambda *_args, **_kw: 64))(attack['instrument'], attack['pitch'], require_fade=True)
        base = attack['volume'] if attack['volume'] is not None else base
        native, quantized = {}, {}
        for event in controls:
            at = Fraction(*event['at'])
            if at >= stop: continue  # Next parent attack retires every cut-NNA sibling/tail.
            value = event['gains'][0]
            native[at] = value
            target = int(at / step + Fraction(1, 2)) * step
            if target >= stop:
                target = stop  # Checked against every native interval below, but never written on a successor.
            rounded |= at != target
            quantized[target] = int(base * value + .5)
        if not native: continue
        a, b = native[start], quantized[start]
        for at in sorted(native.keys() | quantized.keys()):
            a, b = native.get(at, a), quantized.get(at, b)
            error = abs(a - b / base) if base else 0
            worst = max(worst, error)
            if error > 1 / 16 + 1e-12:
                raise ValueError('IT fade_in: row/volume quantization exceeds 6.25 percentage-point gain bound')
        if stop == end and base:
            final = next(e['gains'][0] for e in reversed(controls) if Fraction(*e['at']) <= end)
            last = next(v for at, v in reversed(sorted(quantized.items())) if at < end)
            if abs(final - last / base) > 1 / 16:
                raise ValueError('IT fade_in: final release tail needs a following expression row')
        for at, volume in sorted(quantized.items()):
            if at >= stop: continue
            absolute = int(at / step)
            oi = bisect_right(starts, absolute) - 1
            p, row = names[orders[oi]], absolute - starts[oi]
            requests.setdefault((p, row, ch), []).append((oi, volume, rec))
    for (p, row, ch), values in requests.items():
        if {oi for oi, _, _ in values} != {i for i, name in enumerate(orders) if names[name] == p} or len({v for _, v, _ in values}) != 1:
            raise ValueError('IT fade_in: occurrence-dependent expression; make this pattern unique')
        _, value, rec = values[0]
        cell = projection.patterns[p].rows[row][ch]
        if cell.effect == 19 and cell.param >> 4 == 13 and cell.param & 15:
            raise ValueError('IT fade_in: SDx would delay the expression volume on this release/attack row')
        address = (p, row, ch, 'volcmd')
        if address in projection.owners and projection.owners[address]['role'] == 'attack':
            projection.patterns[p].rows[row][ch].volcmd = value
        else:
            put(p, row, ch, 'volcmd', value, rec, 'fade_in')
    projection.diagnostics.append(f'IT fade_in: expression rounded to nearest row (at most half a row) and volume step; '
                                  f'maximum normalized gain error {worst * 100:.3f} percentage points (limit 6.25), '
                                  'plus IT tick and mixer ramp differences')


def _project_performed_attacks(plan, projection, records, orders, names, starts, speed, put, default_volume):
    """Project native pulses/grace/strokes/swing by performed time, retaining head source identity."""
    occurrences = {o['id']: i for i, o in enumerate(plan['occurrences'])}
    requests = {}
    for event in plan['events']:
        if event['type'] != 'note_on':
            continue
        rec = records[orders[occurrences[event['occurrence']]], event['note']]
        if 'pulse' not in event and not rec['grace'] and not rec['stroke'] and not rec['swing'] and not rec.get('subrow'):
            continue
        kind = 'grace' if rec['grace'] else 'repetition' if 'pulse' in event else 'stroke' if rec['stroke'] else 'swing' if rec['swing'] else 'duration'
        ticks = Fraction(*event['at']) * 24
        if ticks.denominator != 1:
            raise ValueError(f"{event['id']}: {kind} attack is not representable on the IT tick grid")
        absolute_row, delay = divmod(int(ticks), speed)
        if delay > 15:
            raise ValueError(f"{event['id']}: {kind} attack needs a note delay beyond SDf")
        target = bisect_right(starts, absolute_row) - 1
        p, row, ch = names[orders[target]], absolute_row - starts[target], event['ch']
        # Reuse the pitch path's explicit sample/keymap and non-carried voice ownership guard.
        extra = {'require_harmonic': True} if ch in projection.channel_parents.values() else {}
        base = default_volume(event['instrument'], event['pitch'], require_pitch=True, **extra) if default_volume else 64
        base = event['volume'] if event['volume'] is not None else base
        volume = base if event['velocity'] is None else int(Fraction(base * event['velocity'], 127) + Fraction(1, 2))
        payload = (delay, event['pitch'], event['instrument'], volume)
        requests.setdefault((p, row, ch), []).append((target, payload, rec))
    for (p, row, ch), values in requests.items():
        uses = {i for i, name in enumerate(orders) if names[name] == p}
        if len({oi for oi, _, _ in values}) != len(values):
            raise ValueError('multiple repetition/grace/stroke/swing attacks share an IT cell; use finer rows')
        if {oi for oi, _, _ in values} != uses or len({payload for _, payload, _ in values}) != 1:
            raise ValueError('occurrence-dependent repetition/grace/stroke/swing attacks; make this pattern unique')
        _, (delay, pitch, instrument, volume), rec = values[0]
        for attribute, value in (('note', pitch), ('instrument', instrument), ('volcmd', volume)):
            put(p, row, ch, attribute, value, rec, 'attack')
        if delay:
            put(p, row, ch, 'effect', 19, rec, 'attack')
            put(p, row, ch, 'param', 0xD0 | delay, rec, 'attack')


def _project_performed_releases(plan, projection, records, orders, names, starts, speed, put):
    """Exact tick keyoffs, except the explicitly warned final TG pulse's one-tick-short tail."""
    step = Fraction(speed, 24)
    occurrences = {o['id']: i for i, o in enumerate(plan['occurrences'])}
    offs = {e['id']: Fraction(*e['at']) for e in plan['events'] if e['type'] == 'note_off'}
    attacks = {(Fraction(*e['at']), e['ch']) for e in plan['events'] if e['type'] == 'note_on'}
    last_pulses = {}
    for event in plan['events']:
        if event['type'] == 'note_on' and 'pulse' in event:
            last_pulses[event['source_id']] = max(last_pulses.get(event['source_id'], (-1, '')),
                                                 (event['pulse'], event['id']))
    spans, requests = {}, {}
    rounded = False
    for event in plan['events']:
        if event['type'] != 'note_on':
            continue
        oi = occurrences[event['occurrence']]
        rec = records[orders[oi], event['note']]
        start, end, ch = Fraction(*event['at']), offs[event['id']], event['ch']
        if 'pulse' not in event and not rec['grace'] and not rec['stroke'] and not rec['swing'] and not rec.get('subrow') and start != (starts[oi] + rec['row']) * step:
            raise ValueError(f"{event['id']}: moved technique attack cannot be preserved by standalone IT")
        if ch in spans and start < spans[ch]:
            raise ValueError(f"{event['id']}: performed technique overlap needs independent IT channels")
        spans[ch] = end
        ticks = end * 24
        if (ticks.denominator != 1 and 'pulse' in event and
                last_pulses[event['source_id']][1] == event['id'] and (ticks + Fraction(1, 40)).denominator == 1):
            end += Fraction(1, 960)
            ticks = end * 24
            rounded = True
        if ticks.denominator != 1:
            raise ValueError(f"{event['id']}: technique release {end} is not representable on the IT tick grid")
        if end == Fraction(*plan['duration']['quarters']):
            continue
        absolute_row, delay = divmod(int(ticks), speed)
        if delay > 15:
            raise ValueError(f"{event['id']}: technique release needs a note delay beyond SDf")
        target_order = bisect_right(starts, absolute_row) - 1
        p, row = names[orders[target_order]], absolute_row - starts[target_order]
        cell = projection.patterns[p].rows[row][ch]
        owner = projection.owners.get((p, row, ch, 'note'))
        if (end, ch) in attacks or not delay and owner is None and cell.note is not None and cell.note < 120:
            continue  # This coincident attack ends the previous note, as in ordinary strict projection.
        requests.setdefault((p, row, ch), []).append((target_order, delay, rec))
    for (p, row, ch), values in requests.items():
        uses = {i for i, name in enumerate(orders) if names[name] == p}
        if {oi for oi, _, _ in values} != uses or len({delay for _, delay, _ in values}) != 1:
            raise ValueError('occurrence-dependent technique release; make this pattern unique')
        _, delay, rec = values[0]
        cell = projection.patterns[p].rows[row][ch]
        if delay and (cell.instrument or cell.volcmd is not None):
            raise ValueError('delayed technique release would delay an existing instrument/volume command')
        put(p, row, ch, 'note', NOTE_OFF, rec, 'release')
        if delay:
            # OpenMPT Snd_fx.cpp: SDx delays NOTE_KEYOFF through the same triggerNote path as notes.
            put(p, row, ch, 'effect', 19, rec, 'release')
            put(p, row, ch, 'param', 0xD0 | delay, rec, 'release')
    if rounded:
        projection.diagnostics.append('IT repetition: final pulse key-off extended by 1/960 quarter to an exact IT tick '
                                      '(62.5/tempo milliseconds); attacks unchanged, plus IT audio-tick rounding')


def _validate_measure_timeline(score, occurrence_spans):
    """Shared exact measure checks for strict IT projection and native planning."""
    spans = []
    for measure in score.get('measures', []):
        endpoints = []
        for side in ('from', 'to'):
            endpoint = measure[side]
            start, length = occurrence_spans[endpoint['occurrence']]
            offset = _fraction(endpoint['at'], 'measure position')
            if offset > length:
                raise ValueError(f"measure {measure['id']}: endpoint outside pattern")
            endpoints.append(start + offset)
        start, end = endpoints
        meter = measure['meter']
        # A span longer than the meter is an overfull bar, as TuxGuitar's free-edit mode leaves one (flagged by
        # measure_errors); a shorter span is refused.
        if end - start < Fraction(4 * meter[0], meter[1]):
            raise ValueError(f"measure {measure['id']}: exact span does not match its meter")
        if any(start < b and a < end for a, b, _ in spans):
            raise ValueError(f"measure {measure['id']}: overlapping measures")
        spans.append((start, end, measure))
    return spans


def _score_timeline(song, raw_patterns):
    """Validated musical coordinates, independent of IT cells or sample frames."""
    validate_score(song)
    if 'score' not in song:
        raise ValueError('exact score timeline requires a score')
    score = song['score']
    step = Fraction(_int(song.get('module', {}).get('speed', 6), 1, 255, 'module.speed'), 24)
    channels = _channels(song)
    patterns = {p.name: p for p in raw_patterns}
    if len(patterns) != len(raw_patterns):
        raise ValueError('playback plan: duplicate compiled pattern names')
    pattern_beats, written_overlap_channels = {}, set()
    for name, spec in score['patterns'].items():
        if name not in patterns:
            raise ValueError(f'{name}: raw pattern is missing')
        if _fraction(spec['row_step'], 'row_step', True) != step:
            raise ValueError(f'{name}: row_step must equal module.speed/24; raw timing cannot be reinterpreted')
        # Validate even unused authored patterns; expand occurrence identity later.
        voices, channel_spans, timed = {}, {}, []
        cohorts = _cohort_strokes(spec['beats'])
        for beat in spec['beats']:
            at = _fraction(beat['at'], 'beat at')
            beat = dict(beat, **cohorts[_cohort_key(beat)])
            end = at + duration_quarters(beat['written'])
            _check_beat_span(beat, at, end, len(patterns[name].rows) * step, voices)
            notes = _resolved_notes(score, beat)
            for note in notes:
                channel_spans.setdefault(note['channel'], []).append((at, end, note['id'], beat.get('voice', 0)))
            timed.append((beat, at, end, notes))
        for channel, intervals in channel_spans.items():
            intervals.sort()
            active = []
            for current in intervals:
                active = [previous for previous in active if previous[1] > current[0]]
                if any(previous[3] == current[3] for previous in active):
                    raise ValueError(f'{name}/{current[2]}: overlapping score notes in the same voice require independent channels')
                if active:
                    written_overlap_channels.add(channel)
                active.append(current)
        pattern_beats[name] = timed
    for pattern in raw_patterns:
        if any(len(row) != channels for row in pattern.rows):
            raise ValueError(f'{pattern.name}: raw channel count does not match module.channels')
    cursor, occurrences, spans = Fraction(0), [], {}
    for identity, name in zip(score['order_ids'], map(str, song.get('orders', []))):
        if name not in patterns:
            raise ValueError('playback plan: order skips/ends/jumps and missing patterns are unsupported')
        length = len(patterns[name].rows) * step
        if not length:
            raise ValueError(f'{name}: empty raw pattern')
        spans[identity] = (cursor, length)
        occurrences.append({'id': identity, 'pattern': name, 'at': _pair(cursor), 'duration': _pair(length)})
        cursor += length
    measures = _validate_measure_timeline(score, spans)
    records, beats, by_id, raw_actions = [], [], {}, []
    for occurrence in occurrences:
        oid, name = occurrence['id'], occurrence['pattern']
        start, _ = spans[oid]
        for beat, at, end, notes in pattern_beats.get(name, []):
            base = dict(occurrence=oid, pattern=name, beat=beat['id'], track=beat['track'],
                        voice=beat.get('voice', 0), start=start + at, end=start + end,
                        local_at=at, row=at / step, end_row=end / step)
            base.update({key: copy.deepcopy(beat[key]) for key in ('stroke', 'pick_stroke', 'chord', 'cohort')
                         if beat.get(key) is not None})
            beats.append(dict(base, id=f"{oid}/{beat['id']}", rest=not beat['notes'],
                              written=copy.deepcopy(beat['written']),
                              stem=beat.get('stem', _track(score, beat).get('stem', 'auto')),
                              **({'duration_source': beat['duration_source']} if 'duration_source' in beat else {})))
            for note in notes:
                if len(records) >= 100000:
                    raise ValueError('playback plan exceeds 100000 note occurrences; split the arrangement')
                record = dict(base, id=f"{oid}/{note['id']}", note=note['id'], ch=note['channel'],
                              pitch=note['pitch'], source_instrument=note.get('instrument', _track(score, beat)['instrument']),
                              volume=note.get('volume'), velocity=note.get('velocity'), string=note['string'], fret=note['fret'])
                record.update({k: True for k in ('staccato', 'palm_mute', 'let_ring', 'dead', 'vibrato', 'slide',
                                                'ghost', 'accent', 'heavy_accent', 'hammer') if note.get(k)})
                for key in ('fade_in', 'tapping', 'slapping', 'popping'):
                    if key in note:
                        record[key] = note[key]
                record.update({k: copy.deepcopy(note[k]) for k in
                               ('bend', 'tremolo_bar', 'harmonic', 'trill', 'tremolo_picking', 'grace')
                               if note.get(k) is not None})
                records.append(record)
                by_id[record['id']] = record
        for row_index, row in enumerate(patterns[name].rows):
            for channel, cell in enumerate(row):
                if cell.note is not None or cell.instrument:
                    raw_actions.append((start + row_index * step, channel, cell))
    by_channel = {}
    for record in records:
        by_channel.setdefault(record['ch'], []).append(record)
    for channel_records in by_channel.values():
        channel_records.sort(key=lambda r: (r['start'], r['end'], r['id']))
    conflicts = []
    heads = {ch: 0 for ch in by_channel}
    for at, ch, cell in sorted(raw_actions, key=lambda item: (item[0], item[1])):
        active = by_channel.get(ch, [])
        head = heads.get(ch, 0)
        while head < len(active) and active[head]['end'] <= at:
            head += 1
        heads[ch] = head
        if head < len(active) and active[head]['start'] <= at < active[head]['end']:
            record = active[head]
            kind = 'note/release' if cell.note is not None else 'instrument'
            conflicts.append(dict(id=record['id'], occurrence=record['occurrence'], pattern=record['pattern'],
                                  at=_pair(at), row=_pair((at - spans[record['occurrence']][0]) / step), ch=ch,
                                  fields=[field for field, present in (('note', cell.note is not None),
                                          ('instrument', bool(cell.instrument))) if present],
                                  message=f"{record['id']}: raw {kind} conflicts with score sustain at quarter {at}"))
    incoming, outgoing = {}, {}
    for tie in score.get('ties', []):
        left_id = f"{tie['from']['occurrence']}/{tie['from']['note']}"
        right_id = f"{tie['to']['occurrence']}/{tie['to']['note']}"
        if by_id[left_id]['end'] != by_id[right_id]['start']:
            raise ValueError('playback tie endpoints must be adjacent with the same resolved instrument')
        incoming[right_id], outgoing[left_id] = left_id, right_id
    return dict(step=step, duration=cursor, occurrences=occurrences, measures=measures, records=records, beats=beats,
                track_order=list(score['tracks']), written_overlap_channels=written_overlap_channels,
                by_id=by_id, raw_actions=raw_actions, conflicts=conflicts, incoming=incoming, outgoing=outgoing)


def _written_ticks(written):
    value = 3840 // written['value']
    dots = written.get('dots', 0)
    value += value // 2 if dots == 1 else 3 * value // 4 if dots == 2 else 0
    enters, times = written.get('tuplet', [1, 1])
    return value * times // enters


def _legacy_duration(head, last, beats):
    written = beats[f"{last['occurrence']}/{last['beat']}"]['written']
    # TG adds the gap between rounded beat starts when extending a tie.
    # Summing each truncated duration loses these compensating ticks.
    return int(last['start'] * 960) - int(head['start'] * 960) + _written_ticks(written)


def _repeat_visits(timeline):
    """TG's single repeat register, including inherited endings (not a stack)."""
    measures = sorted(timeline['measures'], key=lambda item: item[0])
    occurrences = timeline['occurrences']
    covered, source_index, fragments = Fraction(0), 0, []
    for start, end, measure in measures:
        if start != covered:
            raise ValueError('repeats require explicit measures covering the entire arrangement without gaps')
        covered = end
        pieces = []
        while source_index < len(occurrences):
            occurrence = occurrences[source_index]
            origin = Fraction(*occurrence['at'])
            stop = origin + Fraction(*occurrence['duration'])
            if origin >= end:
                break
            left, right = max(start, origin), min(end, stop)
            if any(((point - origin) / timeline['step']).denominator != 1 for point in (left, right)):
                raise ValueError(f"measure {measure['id']}: repeat fragment boundaries must align exactly to backing rows")
            pieces.append(dict(source_occurrence=occurrence['id'], source_order=source_index,
                source_pattern=occurrence['pattern'], source_from=_pair(left - origin),
                source_to=_pair(right - origin), source_at=_pair(left), duration=_pair(right - left)))
            if stop > end:
                break
            source_index += 1
        fragments.append(pieces)
    if not measures or covered != timeline['duration']:
        raise ValueError('repeats require explicit measures covering the entire arrangement without gaps')
    measure_index = 0
    for beat in sorted(timeline['beats'], key=lambda b: b['start']):
        while measure_index < len(measures) and measures[measure_index][1] <= beat['start']:
            measure_index += 1
        if measure_index == len(measures) or beat['end'] > measures[measure_index][1]:
            raise ValueError(f"{beat['id']}: written beat crosses a repeat measure boundary; split and tie explicitly")
    index, last_index, repeat_start, number, alternative = 0, -1, 0, 0, 0
    opened, cursor, steps, visits, measure_plays = True, Fraction(0), 0, [], 0
    while index < len(measures):
        steps += 1
        if steps > 200000:
            raise ValueError('repeat controller exceeds 200000 steps; simplify the arrangement')
        start, end, measure = measures[index]
        if index == 0:
            repeat_start, opened = index, True
        play = True
        if measure.get('repeat_open', False):
            repeat_start, opened = index, True
            if index > last_index:
                number, alternative = 0, 0
        else:
            if alternative == 0:
                alternative = sum(1 << (ending - 1) for ending in measure.get('endings', []))
            # Java int shift distance is modulo 32.
            if opened and alternative > 0 and not alternative & (1 << (number & 31)):
                play = False
                if measure.get('repeat_close', 0) > 0:
                    alternative = 0
        if play:
            if len(visits) + len(fragments[index]) > 255:
                raise ValueError('repeat backing exceeds the qualified 255 played orders')
            measure_plays += 1
            for piece in fragments[index]:
                identity = f"play_{len(visits) + 1}"
                visits.append(dict(piece, id=identity, play_id=identity,
                    measure_play_id=f'measure_play_{measure_plays}', source_measure=measure['id'],
                    at=_pair(cursor + Fraction(*piece['source_at']) - start), **{'pass': number + 1},
                    repeat_close=measure.get('repeat_close', 0)))
            cursor += end - start
            last_index = max(last_index, index)
            close = measure.get('repeat_close', 0)
            if opened and close > 0:
                if number < close or alternative > 0:
                    index = repeat_start - 1
                    number += 1
                else:
                    number, opened = 0, False
                alternative = 0
        index += 1
    if not visits:
        raise ValueError('repeat traversal has no played measures')
    return visits


def _repeat_backing(song, raw_patterns, source, visits):
    """Use one traversal for backing; restore authored entry tempo after jumps."""
    tempo = song.get('module', {}).get('tempo', 125)
    source_clock = TempoClock(tempo, _raw_tempos(source, raw_patterns, tempo))
    patterns, orders = list(raw_patterns), []
    indices = {p.name: i for i, p in enumerate(patterns)}
    variants, current = {}, tempo
    for visit in visits:
        name = visit['source_pattern']
        pattern = raw_patterns[indices[name]]
        at, length = Fraction(*visit['source_at']), Fraction(*visit['duration'])
        target = source_clock.tempo_at(at)
        row0 = int(Fraction(*visit['source_from']) / source['step'])
        row1 = int(Fraction(*visit['source_to']) / source['step'])
        reset = target if current != target and not any(cell.effect == 20 for cell in pattern.rows[row0]) else None
        index = indices[name]
        if row0 != 0 or row1 != len(pattern.rows) or reset is not None:
            key = (name, row0, row1, reset)
            if key not in variants:
                if len(patterns) >= 254:
                    raise ValueError('repeat fragments/tempo reset exceed 254 backing patterns')
                variant = Pattern(name, copy.deepcopy(pattern.rows[row0:row1]),
                    {(row - row0, ch): copy.deepcopy(value) for (row, ch), value in pattern.lanes.items()
                     if row0 <= row < row1})
                suffix = len(patterns)
                variant.name = f'repeat_backing_{suffix}'
                while variant.name in indices:
                    suffix += 1
                    variant.name = f'repeat_backing_{suffix}'
                if reset is not None:
                    slot = next((ch for ch, cell in enumerate(variant.rows[0])
                                 if not cell.effect and not cell.param), None)
                    if slot is None:
                        raise ValueError(f'{name}: repeat entry tempo reset has no free row-zero effect slot')
                    variant.rows[0][slot].effect, variant.rows[0][slot].param = 20, reset
                variants[key] = len(patterns)
                indices[variant.name] = len(patterns)
                patterns.append(variant)
            index = variants[key]
        visit.update(pattern=patterns[index].name, backing_pattern=index)
        orders.append(index)
        current = source_clock.tempo_at(at + length - source['step'])
    return patterns, orders


def _repeat_timeline(source, visits, patterns):
    """Expand source records once; retain source swing phase and close provenance."""
    source_swings = _swing_timing(source)
    grouped = {o['id']: dict(records=[], beats=[]) for o in source['occurrences']}
    for kind in ('records', 'beats'):
        for record in source[kind]:
            grouped[record['occurrence']][kind].append(record)
    result = dict(step=source['step'], occurrences=visits, measures=[], records=[], beats=[],
                  track_order=source['track_order'],
                  written_overlap_channels=source.get('written_overlap_channels', set()),
                  by_id={}, raw_actions=[], incoming={}, outgoing={}, conflicts=[], swings={})
    pattern_map = {p.name: p for p in patterns}
    for visit in visits:
        origin, source_origin = Fraction(*visit['at']), Fraction(*visit['source_at'])
        shift = origin - source_origin
        oid, played = visit['source_occurrence'], visit['id']
        local_from, local_to = Fraction(*visit['source_from']), Fraction(*visit['source_to'])
        for kind in ('records', 'beats'):
            included = [item for item in grouped[oid][kind] if local_from <= item['local_at'] < local_to]
            if len(result[kind]) + len(included) > (100000 if kind == 'records' else 200000):
                raise ValueError('repeat expansion exceeds note/beat capacity')
            for item in included:
                record = copy.deepcopy(item)
                record.update(id=f"{played}/{item.get('note', item['beat'])}",
                    occurrence=played, pattern=visit['pattern'], start=item['start'] + shift,
                    end=item['end'] + shift, play_id=played, source_occurrence=oid,
                    measure_play_id=visit['measure_play_id'],
                    source_local_at=_pair(item['local_at']), source_row=_pair(item['row']),
                    source_end_row=_pair(item['end_row']),
                    local_at=item['local_at'] - local_from,
                    row=item['row'] - local_from / source['step'],
                    end_row=item['end_row'] - local_from / source['step'],
                    source_order=visit['source_order'], source_measure=visit['source_measure'],
                    source_pattern=visit['source_pattern'], source_beat_id=f"{oid}/{item['beat']}",
                    repeat_close=visit['repeat_close'])
                if kind == 'records':
                    record['source_note_id'] = item['id']
                    result['by_id'][record['id']] = record
                elif item['id'] in source_swings:
                    result['swings'][record['id']] = source_swings[item['id']]
                result[kind].append(record)
        for row_index, row in enumerate(pattern_map[visit['pattern']].rows):
            for ch, cell in enumerate(row):
                if cell.note is not None or cell.instrument:
                    result['raw_actions'].append((origin + row_index * source['step'], ch, cell))
    result['duration'] = Fraction(*visits[-1]['at']) + Fraction(*visits[-1]['duration'])
    previous = {}
    for record in sorted(result['records'], key=lambda r: (r['start'], r['id'])):
        key = record['track'], record['voice'], record['string']
        if record['source_note_id'] in source['incoming']:
            prior = previous.get(key)
            if (prior is None or prior['source_note_id'] != source['incoming'][record['source_note_id']] or
                    prior['end'] != record['start']):
                raise ValueError(f"{record['id']}: unmatched performed tie continuation; repeat path skips its authored predecessor")
            result['incoming'][record['id']] = prior['id']
            result['outgoing'][prior['id']] = record['id']
        previous[key] = record
    return result


def _project_repeated_score(song, raw_patterns, default_volume):
    """Strict IT export of the existing performed traversal, without editing the source.

    Each played fragment gets its own tracker pattern: attacks/releases may differ by
    pass (especially ties). The native traversal owns endings, tempo resets and ties.
    """
    source = _score_timeline(song, raw_patterns)
    if source['conflicts']:
        raise ValueError(source['conflicts'][0]['message'])
    visits = _repeat_visits(source)
    if len(visits) > 254:
        raise ValueError('standalone repeat IT exceeds 254 played fragment patterns')
    backing, _ = _repeat_backing(song, raw_patterns, source, visits)
    timeline = _repeat_timeline(source, visits, backing)
    expanded = copy.deepcopy(song)
    score = expanded['score']
    score.update(patterns={}, order_ids=[], ties=[], measures=[])
    expanded.update(patterns={}, orders=[])
    patterns = []
    measure_groups = {}
    originals = {m['id']: m for m in song['score']['measures']}
    for visit in visits:
        name = visit['id']
        pattern = copy.deepcopy(backing[visit['backing_pattern']])
        pattern.name = name
        patterns.append(pattern)
        expanded['patterns'][name] = dict(rows=len(pattern.rows), data='')
        expanded['orders'].append(name)
        score['order_ids'].append(name)
        left, right = Fraction(*visit['source_from']), Fraction(*visit['source_to'])
        spec = song['score']['patterns'].get(visit['source_pattern'], dict(row_step=_pair(source['step']), beats=[]))
        beats = copy.deepcopy([b for b in spec['beats'] if left <= Fraction(*b['at']) < right])
        for beat in beats:
            beat['at'] = _pair(Fraction(*beat['at']) - left)
        score['patterns'][name] = dict(row_step=_pair(source['step']), beats=beats)
        group = measure_groups.setdefault(visit['measure_play_id'], [])
        group.append(visit)
    for identity, group in measure_groups.items():
        measure = copy.deepcopy(originals[group[0]['source_measure']])
        for key in ('repeat_open', 'repeat_close', 'endings'):
            measure.pop(key, None)
        measure.update(id=identity, **{'from': dict(occurrence=group[0]['id'], at=[0, 1]),
            'to': dict(occurrence=group[-1]['id'], at=group[-1]['duration'])})
        score['measures'].append(measure)
    for target, origin in timeline['incoming'].items():
        a, b = timeline['by_id'][origin], timeline['by_id'][target]
        score['ties'].append({'from': dict(occurrence=a['occurrence'], note=a['note']),
                              'to': dict(occurrence=b['occurrence'], note=b['note'])})
    technique_plan = (_playback_plan(song, backing, timeline=timeline)
                      if any(m.get('swing', 'none') != 'none' for m in song['score'].get('measures', [])) or
                         any(b.get('stroke') is not None or any(n.get(k) for n in b['notes'] for k in _IT_TECHNIQUES)
                             for p in song['score']['patterns'].values() for b in p['beats']) else None)
    result = project_score(expanded, patterns, default_volume, _plan=technique_plan)
    result.orders = list(range(len(patterns)))
    return result


def repeat_projection(song, raw_patterns, sample_rate=44100):
    """Opt-in repeat schedule/backing pair. Never mutate authored orders or cells.

    Linear songs return None. Repeat source requires row-aligned measures. The
    caller must use this backing with this plan, never with authored mod.orders.
    source_view keeps authored ownership; performed note overlays are read-only.
    """
    validate_score(song)
    if not _has_repeats(song):
        return None
    source = _score_timeline(song, raw_patterns)
    if source['conflicts']:
        raise ValueError(source['conflicts'][0]['message'])
    visits = _repeat_visits(source)
    patterns, orders = _repeat_backing(song, raw_patterns, source, visits)
    timeline = _repeat_timeline(source, visits, patterns)
    plan = _playback_plan(song, patterns, sample_rate, timeline=timeline)
    plan['repeat_projection'] = 1
    plan['source_occurrences'] = copy.deepcopy(source['occurrences'])
    view = _authoring_view(song, raw_patterns, source_only=True)
    bindings = {}
    visits_by_id = {v['id']: v for v in visits}
    for position in plan['positions']:
        visit = visits_by_id[position['play_id']]
        shift = Fraction(*visit['source_at']) - Fraction(*visit['at'])
        variant = dict(play_id=visit['id'], **{'pass': visit['pass']},
                       attack_id=position['attack_id'], tied_in=position['tied_in'], tied_out=position['tied_out'],
                       sounding_start=_pair(Fraction(*position.get('sounding_start', position['at'])) + shift),
                       sounding_end=_pair(Fraction(*position.get('sounding_end', position['end'])) + shift))
        bindings.setdefault(position['source_note_id'], []).append(variant)
    for position in view['positions']:
        if position['kind'] == 'note':
            variants = bindings.get(position['id'], [])
            position.update(performed_variants=variants, performed_readonly=True, performed_unplayed=not variants,
                performed_ambiguous=len({(tuple(v['sounding_start']), tuple(v['sounding_end']),
                                           v['tied_in'], v['tied_out']) for v in variants}) > 1)
    view['repeat_projection'] = 1
    view['diagnostics'].append('Repeat playback overlays are read-only; authored ownership and orders are unchanged.')
    return RepeatProjection(patterns, orders, plan, view)


def resolve_source_region(plan, region):
    """Inclusive authored (order,row,order,row) -> one inclusive played span.

    Linear plans preserve their existing region contract. A repeat selection may
    contain several visits only if the selected played rows form one continuous
    interval. No min/max over gaps and no second traversal of a truncated score.
    """
    if not plan.get('repeat_projection'):
        return region
    if not isinstance(region, (tuple, list)) or len(region) != 4 or any(type(x) is not int for x in region):
        raise ValueError('source region must be four inclusive integer order/row coordinates')
    a, r0, b, r1 = region
    source = plan['source_occurrences']
    step = Fraction(*plan['row_step'])
    if not 0 <= a <= b < len(source) or (a == b and r0 > r1):
        raise ValueError('source region order bounds are invalid')
    rows_a, rows_b = Fraction(*source[a]['duration']) / step, Fraction(*source[b]['duration']) / step
    if not 0 <= r0 < rows_a or not 0 <= r1 < rows_b:
        raise ValueError('source region row bounds are invalid')
    selected = []
    for index, visit in enumerate(plan['occurrences']):
        order = visit['source_order']
        if a <= order <= b:
            offset = int(Fraction(*visit['source_from']) / step)
            stop = int(Fraction(*visit['source_to']) / step)
            first = max(offset, r0 if order == a else 0)
            last = min(stop - 1, r1 if order == b else stop - 1)
            if first > last:
                continue
            first, last = first - offset, last - offset
            origin = Fraction(*visit['at'])
            selected.append((origin + first * step, origin + (last + 1) * step, index, first, last))
    if not selected:
        raise ValueError('source region is unreachable in the performed repeat traversal')
    if any(left[1] != right[0] for left, right in zip(selected, selected[1:])):
        raise ValueError('source region maps to disjoint played spans; select an explicit performed pass')
    return (selected[0][2], selected[0][3], selected[-1][2], selected[-1][4])


def _slide_controls(length, distance):
    """TG slide steps retain Java float32 operation order and integer tick stride."""
    f32 = lambda value: struct.unpack('f', struct.pack('f', value))[0]
    count = length // 120
    for i in range(1, count + 1):
        stride = length // count
        tone = f32(f32(f32(f32(stride) * f32(i)) * f32(distance)) / f32(length))
        yield stride * i, max(0, min(127, 64 + int(f32(tone * 5.5))))
    yield length, 64


def _pitch_controls(note, ticks, slide=None):
    """Yield (relative TG tick, 7-bit bend value), preserving coincident resets.

    TG's parser uses integer step widths and a 64-neutral bend value. The native
    receiver establishes +/-12 semitones, matching its default MIDI bend range.
    Bend takes precedence over tremolo bar, slide, then vibrato.
    """
    bend = note.get('bend')
    bar = note.get('tremolo_bar')
    if bend and bend['points'] or bar is not None:
        curve, scale = (bend, Fraction(11, 4)) if bend and bend['points'] else (bar, Fraction(11, 2))
        points = curve['points']
        for i, point in enumerate(points):
            at = ticks * point['position'] // 12
            value = max(0, min(127, 64 + int(point['value'] * scale)))
            yield at, value
            if i + 1 < len(points):
                after = points[i + 1]
                target = 64 + int(after['value'] * scale)
                if target != value:
                    width = (ticks * after['position'] // 12 - at) // abs(target - value)
                    direction = 1 if target > value else -1
                    while value != target:
                        value += direction
                        at += width
                        yield at, max(0, min(127, value))
        yield ticks, 64
    elif note.get('slide'):
        if slide is not None:
            yield from _slide_controls(*slide)
    elif note.get('vibrato'):
        at = 0
        while at < ticks:
            at = min(at + 160, ticks)
            yield at, 64
            at = min(at + 160, ticks)
            yield at, 65
        yield ticks, 64


def _performed_velocities(timeline):
    """TG getRealVelocity: previous written same-string/voice hammer, then accent.

    Lookup crosses rests/occurrences and includes tied continuations, although
    only chain heads attack. Missing MIDI velocity never becomes default 95 or
    derives from IT volume. Residual attacks have no authored voice/string.
    """
    previous, unresolved, raw_attacks, result = {}, {}, {}, {}
    for at, ch, cell in timeline['raw_actions']:
        if cell.note is not None and 0 <= cell.note < 120:
            raw_attacks.setdefault(ch, []).append(at)
    for values in raw_attacks.values():
        values.sort()
    for record in sorted(timeline['records'], key=lambda r: (r['start'], r['id'])):
        voice = (record['track'], record['voice'])
        strings = previous.setdefault(voice, {})
        unknown = unresolved.setdefault(voice, {})
        string, at = record['string'], record['start']
        old = strings.get(string)
        if record['id'] not in timeline['incoming']:
            if string is None and any(n.get('hammer') and n['start'] < at for n in strings.values()):
                raise ValueError(f"{record['id']}: hammer predecessor lookup needs resolved string/fret")
            ambiguous = [n for n in unknown.values()
                         if n['ch'] == record['ch'] and n['start'] < at
                         and (old is None or n['start'] > old['start'])]
            hammered = old is not None and old.get('hammer', False)
            if ambiguous and (hammered or any(n.get('hammer') for n in ambiguous)):
                raise ValueError(f"{record['id']}: unresolved string/fret makes hammer predecessor ambiguous")
            if hammered:
                for ch in {old['ch'], record['ch']}:
                    times = raw_attacks.get(ch, [])
                    index = bisect_right(times, old['start'])
                    if index < len(times) and times[index] <= at:
                        raise ValueError(f"{record['id']}: raw attack makes hammer predecessor "
                                         f"{old['id']} ambiguous")
            dynamic = next((k for k in ('ghost', 'accent', 'heavy_accent') if record.get(k)), None)
            if hammered or dynamic:
                value = record['velocity']
                if value is None:
                    reason = f"hammer predecessor {old['id']}" if hammered else dynamic
                    raise ValueError(f"{record['id']}: {reason} requires explicit authored MIDI velocity")
                if hammered:
                    value = max(15, value - 25)
                if dynamic:
                    value = max(15, value + {'ghost': -16, 'accent': 16, 'heavy_accent': 32}[dynamic])
                result[record['id']] = min(127, value)
        # Continuations deliberately replace the previous written note. A hammer
        # on the head does not propagate through an unmarked tied continuation.
        if string is None:
            unknown[(record['ch'], bool(record.get('hammer')))] = record
        else:
            strings[string] = record
    return result


def _harmonic_layers(record, velocity):
    """TG 2.1.0 source order: optional semi fundamental, lower layer, primary.

    Every layer shares the authored gate and pitch controls. Distinct identities
    are needed even when two layers have the same pitch. Missing velocity is not
    TG's default 95: it remains unspecified until the author assigns one.
    """
    if velocity is None:
        raise ValueError(f"{record['id']}: harmonic requires explicit authored MIDI velocity")
    harmonic, original = record['harmonic'], record['pitch']
    frequencies = ((12, 12), (9, 28), (5, 24), (7, 19), (4, 28), (3, 31))
    key, layers = original, []
    if harmonic['type'] == 'natural':
        if record['fret'] is None:
            raise ValueError(f"{record['id']}: natural harmonic needs resolved string/fret")
        for fret, offset in frequencies:
            if record['fret'] % 12 == fret % 12:
                key = original + offset - record['fret']
                break
    else:
        if harmonic['type'] == 'semi':
            layers.append(dict(pitch=original, velocity=max(15, velocity - 48)))
        key = original + frequencies[harmonic.get('data', 0)][1]
    if key - 12 > 0:
        layers.append(dict(pitch=key - 12, velocity=max(15, velocity - 64)))
    layers.append(dict(pitch=max(0, min(127, key)), velocity=velocity))
    if any(not 0 <= layer['pitch'] <= 119 for layer in layers):
        raise ValueError(f"{record['id']}: harmonic layer exceeds native pitch range 0..119")
    return layers


def _swing_timing(timeline):
    """TG's source-measure/voice neighbor rule on floored ticks; preserve exact A."""
    measures = sorted((a, b, m) for a, b, m in timeline['measures'] if m.get('swing', 'none') != 'none')
    if not measures:
        return {}
    starts = [a for a, _, _ in measures]
    voices, result = {}, {}
    for beat in timeline['beats']:
        index = bisect_right(starts, beat['start']) - 1
        if index >= 0 and beat['start'] < measures[index][1]:
            if beat['end'] > measures[index][1]:
                raise ValueError(f"{beat['id']}: beat crosses swing measure boundary; split it with an explicit tie")
            measure = measures[index][2]
            voices.setdefault((measure['id'], beat['track'], beat['voice'], measure['swing']), []).append(beat)
        elif index + 1 < len(measures) and measures[index + 1][0] < beat['end']:
            raise ValueError(f"{beat['id']}: beat crosses swing measure boundary; coverage must be unambiguous")

    def normal(beat, value):
        written = beat['written']
        return (written['value'] == value and not written.get('dots', 0) and
                written.get('tuplet', [1, 1]) == [1, 1])

    for (_, _, _, mode), beats in voices.items():
        beats.sort(key=lambda b: b['start'])
        tick_starts = [int(b['start'] * 960) for b in beats]
        value, unit = (8, 960) if mode == 'eighth' else (16, 480)
        for beat in beats:
            if not normal(beat, value):
                continue
            start = int(beat['start'] * 960)
            if start % unit == 0:
                next_index = bisect_right(tick_starts, start)
                next_beat = beats[next_index] if next_index < len(beats) else None
                if next_beat is None or int(next_beat['start'] * 960) > start + unit // 2 or normal(next_beat, value):
                    result[beat['id']] = dict(shift=0, ticks=unit * 2 // 3, mode=mode)
            elif start % (unit // 2) == 0:
                previous_index = bisect_left(tick_starts, start) - 1
                previous = beats[previous_index] if previous_index >= 0 else None
                if previous is None or int(previous['start'] * 960) < start - unit // 2 or normal(previous, value):
                    result[beat['id']] = dict(shift=unit // 6, ticks=unit // 3, mode=mode)
    return result


def _stroke_delays(timeline):
    """Shared onset/track cohort, written voice durations, untied distinct strings."""
    cohorts, beats, notes = {}, {}, {}
    for beat in timeline['beats']:
        beats[beat['id']] = beat
        cohorts.setdefault((beat['occurrence'], beat['track'], beat['start'], beat.get('cohort', 0)), []).append(beat)
    for record in timeline['records']:
        if record['id'] not in timeline['incoming']:
            notes.setdefault((record['occurrence'], record['track'], record['start'], record.get('cohort', 0)), []).append(record)
    delays = {}
    for key, voices in cohorts.items():
        stroke = voices[0].get('stroke')
        if stroke is None:
            continue
        heads = notes.get(key, [])
        if any(head['string'] is None for head in heads):
            raise ValueError('beat stroke needs resolved strings for every untied head')
        duration = min(960, *(_legacy_duration(b, b, beats) for b in voices))
        increment = (duration + stroke['value']) // (2 * stroke['value'])
        strings = sorted({head['string'] for head in heads}, reverse=stroke['direction'] == 'down')
        offsets = {string: i * increment for i, string in enumerate(strings)}
        delays.update((head['id'], offsets[head['string']]) for head in heads)
    return delays


def _performed_releases(timeline, clock):
    """TG 2.1.0 gate durations use truncated 960-tick units; written times stay exact.

    Swing supplies initial start/duration; tie/ring accounting keeps written ends.
    Let-ring scans the original ordered voice, including flags on tied notes.
    Apply initiating gates afterward: dead wins over palm mute, then staccato.
    Repeated visits retain the initiating source measure's repeat-close flag.
    A key-off starts the instrument release; it does not cut its sounding tail.
    """
    beats = {b['id']: b for b in timeline['beats']}
    swings = timeline['swings'] if 'swings' in timeline else _swing_timing(timeline)
    voice_beats, beat_notes, beat_indices = {}, {}, {}
    for beat in timeline['beats']:
        voice_beats.setdefault((beat['track'], beat['voice']), []).append(beat)
    for values in voice_beats.values():
        values.sort(key=lambda b: b['start'])
        beat_indices.update((b['id'], i) for i, b in enumerate(values))
    for record in timeline['records']:
        beat_notes.setdefault(f"{record['occurrence']}/{record['beat']}", []).append(record)

    def ring_ticks(head, chain, initial_ticks):
        if head['string'] is None:
            raise ValueError(f"{head['id']}: let_ring needs resolved string/fret")
        ticks = initial_ticks
        last_end = int(head['start'] * 960) + _legacy_duration(head, head, beats)
        ringing = head.get('let_ring', False)
        tied_ids = {n['id'] for n in chain[1:]}
        voice = voice_beats[head['track'], head['voice']]
        index = beat_indices[f"{head['occurrence']}/{head['beat']}"]
        for next_index in range(index + 1, len(voice)):
            beat = voice[next_index]
            notes = beat_notes.get(beat['id'], [])
            if not notes:  # Absent voices are not in this stream; authored rests are.
                break
            duration = _legacy_duration(notes[0], notes[0], beats)
            changed = False
            for note in notes:  # Source chord order is observable; do not sort.
                if (ringing and head.get('repeat_close', 0) > 0 and
                        beat.get('measure_play_id', beat['occurrence']) != head.get('measure_play_id', head['occurrence'])):
                    return ticks
                if ringing and not note.get('let_ring'):
                    return ticks + duration
                if note['string'] is None:
                    raise ValueError(f"{head['id']}: let_ring lookup encounters unresolved string/fret at {note['id']}")
                if note['string'] == head['string']:
                    if note['id'] not in tied_ids:
                        return ticks
                    ticks += int(beat['start'] * 960) - last_end + duration
                    last_end = int(beat['start'] * 960) + duration
                    ringing, changed = note.get('let_ring', False), True
            if ringing and not changed:
                ticks += duration
                last_end += duration
        return ticks

    strokes = _stroke_delays(timeline)
    releases = {}
    for head in timeline['records']:
        if head['id'] in timeline['incoming']:
            continue
        last, chain = head, [head]
        while last['id'] in timeline['outgoing']:
            last = timeline['by_id'][timeline['outgoing'][last['id']]]
            chain.append(last)
        ring = any(n.get('let_ring') for n in chain)
        swing = swings.get(f"{head['occurrence']}/{head['beat']}")
        written_ticks = _legacy_duration(head, head, beats)
        initial_ticks = swing['ticks'] if swing else written_ticks
        ticks = (ring_ticks(head, chain, initial_ticks) if ring else
                 _legacy_duration(head, last, beats) + initial_ticks - written_ticks)
        start = head['start'] + Fraction(swing['shift'], 960) if swing else head['start']
        if start != head['start'] and head['source_instrument'] <= 0:
            raise ValueError(f"{head['id']}: delayed swing requires an explicit source instrument; inheritance is unsupported")
        effect = next((k for k in ('dead', 'palm_mute', 'staccato') if head.get(k)), None)
        end = last['end']
        if effect:
            if effect == 'staccato':
                ticks //= 2
            else:
                tempo = clock.tempo_at(head['start'])
                ticks = min(ticks, tempo * (30 if effect == 'dead' else 60) // 60)
            if ticks <= 0 and head.get('trill') is None and head.get('tremolo_picking') is None:
                raise ValueError(f"{head['id']}: technique gate has zero performed ticks")
        if ring and ticks <= 0 and head.get('trill') is None and head.get('tremolo_picking') is None:
            raise ValueError(f"{head['id']}: let_ring has zero performed ticks")
        if effect or ring or swing:
            end = start + Fraction(ticks, 960)
        stroke = strokes.get(head['id'])
        if stroke is not None:
            if stroke and head['source_instrument'] <= 0:
                raise ValueError(f"{head['id']}: delayed stroke requires an explicit source instrument; inheritance is unsupported")
            start += Fraction(stroke, 960)
            if ticks > stroke:
                ticks -= stroke
            end = start + Fraction(ticks, 960)
        # TG mixer expression uses the real gate after stroke but before grace.
        # This descriptor is export-only; it must not alter native audio events.
        midi_fade = dict(at=_pair(start), ticks=ticks) if head.get('fade_in') else None
        grace_interval = None
        grace = head.get('grace')
        if grace is not None:
            if head['source_instrument'] <= 0:
                raise ValueError(f"{head['id']}: grace requires an explicit source instrument; inheritance is unsupported")
            length = 3840 // grace['value']
            duration = min(length, clock.tempo_at(head['start']) * 30 // 60) if grace.get('dead') else length
            end = start + Fraction(ticks, 960)
            if grace.get('on_beat') or start < Fraction(length, 960):
                if ticks <= length:
                    raise ValueError(f"{head['id']}: grace delay exhausts the main duration; requires D > L")
                grace_start = start
                start += Fraction(length, 960)
                ticks -= length
            else:
                grace_start = start - Fraction(length, 960)
            grace_interval = dict(start=grace_start, end=grace_start + Fraction(duration, 960),
                                  pitch=head['pitch'] - head['fret'] + grace['fret'])
            if ticks <= 0 or end > timeline['duration'] or grace_interval['end'] > timeline['duration']:
                raise ValueError(f"{head['id']}: grace/main duration exceeds arrangement bounds or has no performed ticks")
        releases[head['id']] = dict(end=end, gate_effect=effect, ticks=ticks,
                                    start=start, grace=grace_interval, swing=swing['mode'] if swing else None,
                                    midi_fade=midi_fade,
                                    stroke=stroke,
                                    let_ring=ring, written_end=last['end'])
    return releases


def _performed_conflicts(timeline, releases, raw_patterns, song):
    """Shared diagnostics and scoped hold admission; written ownership stays unchanged.

    An earlier ordinary ring or extended swing may survive a later ordinary attack through the
    negotiated held-score runtime. Other qualified performed overlaps use
    independent head contexts. Written ownership and source gates stay intact.
    """
    def ordinary(record):
        return record['source_instrument'] > 0 and not any(
            record.get(k) is not None for k in ('harmonic', 'trill', 'tremolo_picking', 'grace'))

    def event_end(head, release):
        repetition = head.get('trill') or head.get('tremolo_picking')
        if repetition is None:
            return release['end']
        ticks, length = release['ticks'], 3840 // repetition['value']
        return release['start'] if ticks <= 10 else release['start'] + Fraction(
            min(((ticks - 11) // length + 1) * length, ticks - 1), 960)

    written_channels = timeline.get('written_overlap_channels', set())
    if not written_channels and not any(
            release['let_ring'] or release['grace'] or release['swing'] or release.get('stroke') is not None
            for release in releases.values()):
        return []
    spans, extensions, conflicts = {}, {}, []
    context_parents = {timeline['by_id'][identity]['ch']: identity for identity in releases
                       if timeline['by_id'][identity]['ch'] in written_channels}
    for identity, release in releases.items():
        head = timeline['by_id'][identity]
        end = release['end']
        if (release['let_ring'] or release['swing'] or release.get('stroke') is not None) and end > timeline['duration']:
            conflicts.append(dict(id=identity, occurrence=head['occurrence'], pattern=head['pattern'],
                at=_pair(head['start']), row=_pair(head['row']), ch=head['ch'], fields=['note'],
                message=f"{identity}: {'stroke' if release.get('stroke') is not None else 'swing' if release['swing'] else 'let_ring'} sounding end {end} exceeds arrangement end "
                        f"{timeline['duration']}; unsupported performed duration"))
        end = event_end(head, release)
        if end > release['start']:
            spans.setdefault(head['ch'], []).append((release['start'], end, identity))
        if release['grace']:
            spans.setdefault(head['ch'], []).append((release['grace']['start'], release['grace']['end'], identity))
        if release['let_ring'] and not release['swing'] and end > release['written_end']:
            extensions.setdefault(head['ch'], []).append((release['written_end'], end, identity))
    for ch, values in spans.items():
        previous = None
        for current in sorted(values):
            start, end, identity = current
            if previous is not None and start < previous[1] and (
                    releases[previous[2]]['let_ring'] or releases[identity]['let_ring'] or
                    releases[previous[2]]['grace'] or releases[identity]['grace'] or
                    releases[previous[2]]['swing'] or releases[identity]['swing'] or
                    releases[previous[2]].get('stroke') is not None or releases[identity].get('stroke') is not None):
                head, earlier = timeline['by_id'][identity], timeline['by_id'][previous[2]]
                prior = releases[previous[2]]
                extended = prior['let_ring'] or (prior['swing'] and prior['end'] > prior['written_end'])
                if (ch not in context_parents and extended and ordinary(earlier) and ordinary(head) and
                        prior.get('stroke') is None and releases[identity].get('stroke') is None):
                    releases[previous[2]]['hold'] = True
                elif earlier['source_instrument'] > 0 and head['source_instrument'] > 0:
                    context_parents[ch] = identity
                else:
                    conflicts.append(dict(id=identity, occurrence=head['occurrence'], pattern=head['pattern'],
                        at=_pair(start), row=_pair(head['row']), ch=ch, fields=['note', 'instrument'],
                        message=f"unsupported {'stroke' if prior.get('stroke') is not None or releases[identity].get('stroke') is not None else 'grace' if earlier.get('grace') or head.get('grace') else 'swing' if releases[previous[2]]['swing'] or releases[identity]['swing'] else 'let_ring'} "
                                f"overlap on native channel {ch}: "
                                f"{previous[2]} sustains through {identity}; held overlaps require explicit "
                                "single-pitch attacks without harmonic layers, repetition or grace"))
            if previous is None or end > previous[1]:
                previous = current
    occurrences = timeline['occurrences']
    starts = [Fraction(*o['at']) for o in occurrences]
    # Keep the backing at authored time. Prefix and delayed-attack windows
    # cannot silently acquire/move channel-local instrument, volume or effects.
    patterns = {pattern.name: pattern for pattern in raw_patterns}
    for identity, release in releases.items():
        if release['grace'] is None and release['swing'] is None and release.get('stroke') is None:
            continue
        head = timeline['by_id'][identity]
        windows = []
        if release['grace']:
            low, high = min(release['grace']['start'], head['start']), release['start']
            shifted = high > head['start']
            windows.append((low, high, shifted, f"grace {'delayed attack' if shifted else 'before-beat prefix'}"))
        elif release['start'] > head['start']:
            windows.append((head['start'], release['start'], True,
                            'stroke delayed attack' if release.get('stroke') is not None else 'swing delayed attack'))
        end = event_end(head, release)
        if release['swing'] and end > release['written_end']:
            windows.append((release['written_end'], end, False, 'extended swing sustain'))
        if release.get('stroke') is not None and end > release['written_end']:
            windows.append((release['written_end'], end, False, 'extended stroke sustain'))
        for low, high, include_end, reason in windows:
            for occurrence_index in range(max(0, bisect_right(starts, low) - 1), bisect_right(starts, high)):
                occurrence = occurrences[occurrence_index]
                base = Fraction(*occurrence['at'])
                if base > high or base + Fraction(*occurrence['duration']) <= low:
                    continue
                pattern = patterns[occurrence['pattern']]
                first = max(0, (low - base) // timeline['step'])
                last = min(len(pattern.rows) - 1, (high - base) // timeline['step'])
                for row in range(first, last + 1):
                    at = base + row * timeline['step']
                    if at < low or at > high or at == high and not include_end:
                        continue
                    cell = pattern.rows[row][head['ch']]
                    fields = [field for field, present in (('note', cell.note is not None),
                              ('instrument', bool(cell.instrument)), ('volcmd', cell.volcmd is not None),
                              ('effect', cell.effect not in (0, 20, 22) or not cell.effect and bool(cell.param))) if present]
                    if fields:
                        conflicts.append(dict(id=identity, occurrence=occurrence['id'], pattern=pattern.name,
                            at=_pair(at), row=[row, 1], ch=head['ch'], fields=fields,
                            message=f"{identity}: raw {'/'.join(fields)} conflicts with {reason} "
                                    f"on native channel {head['ch']}"))
    raw_channels = {}
    for at, ch, cell in timeline['raw_actions']:
        if ch in extensions:
            raw_channels.setdefault(ch, []).append((at, cell))
    for ch, entries in raw_channels.items():
        entries.sort(key=lambda entry: entry[0])
        times = [entry[0] for entry in entries]
        for start, end, identity in extensions[ch]:
            for index in range(bisect_left(times, start), bisect_left(times, end)):
                at, cell = entries[index]
                occurrence = occurrences[bisect_right(starts, at) - 1]
                fields = [field for field, present in (('note', cell.note is not None),
                          ('instrument', bool(cell.instrument))) if present]
                conflicts.append(dict(id=identity, occurrence=occurrence['id'], pattern=occurrence['pattern'],
                    at=_pair(at), row=_pair((at - Fraction(*occurrence['at'])) / timeline['step']),
                    ch=ch, fields=fields,
                    message=f"{identity}: raw {'/'.join(fields)} conflicts with extended let_ring sustain "
                            f"on native channel {ch} at quarter {at}"))
    # Release-tail lifetime depends on sample/envelope playback. Until a state
    # trace can narrow it, the first held capability requires a clean parent
    # throughout the backing, including unused patterns that it validates.
    held = {timeline['by_id'][identity]['ch']: identity for identity, release in releases.items()
            if release.get('hold')}
    for identity in releases:
        head = timeline['by_id'][identity]
        if head['ch'] in held and not ordinary(head) and head['source_instrument'] > 0:
            context_parents[head['ch']] = identity
    if context_parents:
        context_parents.update(held)
        for identity, release in releases.items():
            release.pop('hold', None)
            if timeline['by_id'][identity]['ch'] in context_parents:
                release['context'] = True
        held = {}
    timeline['context_parents'] = context_parents
    protected = {**held, **context_parents}
    if protected:
        for identity in releases:
            head = timeline['by_id'][identity]
            reason = None
            if head['ch'] in context_parents:
                reason = _context_source_reason(song, head)
            elif head['ch'] in held and not ordinary(head):
                reason = 'requires explicit single-pitch attacks without harmonic layers, repetition or grace throughout the arrangement'
            if reason:
                conflicts.append(dict(id=head['id'], occurrence=head['occurrence'], pattern=head['pattern'],
                    at=_pair(head['start']), row=_pair(head['row']), ch=head['ch'], fields=['note', 'instrument'],
                    message=f"{head['id']}: {'context' if head['ch'] in context_parents else 'held swing' if releases[held[head['ch']]]['swing'] else 'held let_ring'} parent {reason}"))
        for pattern in raw_patterns:
            uses = [o for o in occurrences if o['pattern'] == pattern.name]
            for row, cells in enumerate(pattern.rows):
                for ch, identity in protected.items():
                    cell = cells[ch]
                    fields = [field for field, present in (('note', cell.note is not None),
                              ('instrument', bool(cell.instrument)), ('volcmd', cell.volcmd is not None),
                              ('effect', cell.effect not in (0, 20, 22) or not cell.effect and bool(cell.param))) if present]
                    if fields:
                        for occurrence in uses or [None]:
                            at = (Fraction(*occurrence['at']) if occurrence else 0) + row * timeline['step']
                            conflicts.append(dict(id=identity, occurrence=occurrence['id'] if occurrence else None,
                                pattern=pattern.name, at=_pair(at), row=[row, 1], ch=ch, fields=fields,
                                message=f"{identity}: {'context' if ch in context_parents else 'held swing' if releases[identity]['swing'] else 'held let_ring'} overlap cannot share raw {'/'.join(fields)} "
                                        f"on native channel {ch}; the entire backing must contain only empty/T/V cells"))
    return conflicts


def _context_source_reason(song, head):
    """Early source-visible exclusions; the engine also checks compiled maps."""
    source = head['source_instrument']
    if source <= 0:
        return 'requires explicit source for every executed head throughout the arrangement'
    instruments, samples = song.get('instruments') or {}, song.get('samples') or {}
    instrument = instruments.get(source, instruments.get(str(source), {}))
    for key in ('volume_envelope', 'panning_envelope', 'pitch_envelope'):
        if isinstance(instrument.get(key), dict) and instrument[key].get('carry'):
            return f'refuses {key} carry until context source behavior is qualified'
    if instrument.get('random_volume') or instrument.get('random_pan'):
        return 'refuses random instrument swing until context source behavior is qualified'
    refs = [instrument.get('sample')] * 120 if instruments else [source]
    if instrument.get('keymap'):
        from .song import Ctx, _Bad, _note_range
        context = Ctx('<native head context>')
        for entry in instrument['keymap']:
            try:
                low, high = _note_range(context, entry.get('notes'), 0, 'context source keymap')
            except _Bad:
                return 'has an invalid source keymap'
            refs[low:high + 1] = [entry.get('sample')] * (high - low + 1)
    for ref in refs:
        if ref is None:
            continue
        sample = samples.get(ref, samples.get(str(ref)))
        if sample is None:
            sample = next((s for s in samples.values() if s.get('name') == ref), {})
        if isinstance(sample.get('vibrato'), dict) and sample['vibrato'].get('type') == 'random':
            return 'refuses random sample auto-vibrato in the source mapping'
    return None


def _source_ordinals(timeline):
    """Written insertion order, independent of swung/stroked/grace attack times."""
    occurrence_order = {o['id']: i for i, o in enumerate(timeline['occurrences'])}
    track_order = {track: i for i, track in enumerate(timeline['track_order'])}
    record_order = {r['id']: i for i, r in enumerate(timeline['records'])}
    return {r['id']: i for i, r in enumerate(sorted(timeline['records'],
        key=lambda r: (occurrence_order[r['occurrence']], track_order[r['track']], r['start'], r['voice'],
                       record_order[r['id']])))}


def _context_schedule(events, timeline):
    """Annotate final scheduled attacks; closes occur after the frame's batch."""
    parents = timeline.get('context_parents', {})
    if not parents and not any(b.get('stroke') is not None for b in timeline['beats']):
        return
    source_order = _source_ordinals(timeline)
    def order(event):
        head = event.get('source_id', event['id'])
        grace = bool(timeline['by_id'][head].get('grace'))
        attack = 0 if event.get('role') == 'grace' else event.get('pulse', 0) + grace
        return source_order[head], attack
    ranks = {'note_off': 0, 'note_on': 1, 'pitch': 2}
    events.sort(key=lambda e: (e['frame'], ranks[e['type']], *order(e)))
    if not parents:
        return
    attacks = [e for e in events if e['type'] == 'note_on']
    final = {e.get('source_id', e['id']): e for e in attacks if e['ch'] in parents}
    keys, active, closing, frame_heads, frame_count, frame = {}, set(), set(), set(), 0, None
    for event in attacks:
        if event['frame'] != frame:
            active.difference_update(closing)
            closing, frame_heads, frame_count, frame = set(), set(), 0, event['frame']
        frame_count += 1
        if frame_count > 64:
            raise ValueError('native context plan exceeds 64 attacks in one frame')
        if event['ch'] not in parents:
            continue
        head = event.get('source_id', event['id'])
        if head in frame_heads:
            raise ValueError(f'{head}: multiple attacks of the same head round to one frame')
        frame_heads.add(head)
        opened = head not in keys
        if opened:
            if len(active) >= 64:
                raise ValueError('native context plan exceeds 64 live contexts before end-frame closes')
            keys[head] = len(keys) + 1
            active.add(head)
        event.update(context=keys[head], context_open=opened, context_close=event is final[head])
        event.pop('hold', None)
        if event['context_close']:
            closing.add(head)


def _lyric_tokens(text):
    """TG literal-space split: CR and LF each separate; trailing blanks vanish."""
    tokens = text.replace('\r', ' ').replace('\n', ' ').split(' ')
    if text:
        while tokens and tokens[-1] == '':
            tokens.pop()
    return tokens


def _lyrics_projection(score, timeline):
    """Disposable written anchors; incomplete meter maps do not disable audio."""
    anchors, errors = [], []
    measures = sorted(timeline['measures'], key=lambda entry: entry[0])
    cursor, mapped = Fraction(0), bool(measures)
    for start, end, _ in measures:
        mapped &= start == cursor
        cursor = end
    mapped &= cursor == timeline['duration']
    cohorts = {}
    for beat in timeline['beats']:
        if not beat['rest'] and 'lyrics' in score['tracks'][beat['track']]:
            key = beat['track'], beat['start'], beat.get('cohort', 0)
            if key not in cohorts or beat['voice'] < cohorts[key]['voice']:
                cohorts[key] = beat
    by_track = {}
    for beat in sorted(cohorts.values(), key=lambda b: (b['start'], b.get('cohort', 0), b['id'])):
        by_track.setdefault(beat['track'], []).append(beat)
    trim_chars = ''.join(map(chr, range(33)))  # Java trim, not Unicode strip.
    for identity, track in score['tracks'].items():
        if 'lyrics' not in track:
            continue
        lyrics = track['lyrics']
        tokens = _lyric_tokens(lyrics['text'])
        if not lyrics['text'] or not tokens:
            continue  # Empty source has zero lyric height; retain its metadata.
        if not mapped:
            errors.append(dict(track=identity, code='lyrics_measure_map',
                message=f'Track {identity}: lyrics require authored measures covering the written arrangement without gaps.'))
            continue
        measure_index, slot = 0, 0
        for beat in by_track.get(identity, []):
            while measure_index < len(measures) and beat['start'] >= measures[measure_index][1]:
                measure_index += 1
            if measure_index + 1 < lyrics['from_measure']:
                continue
            if slot == len(tokens):
                break
            token = tokens[slot]
            anchors.append(dict(track=identity, occurrence=beat['occurrence'], pattern=beat['pattern'],
                beat=beat['beat'], voice=beat['voice'], measure=measures[measure_index][2]['id'],
                measure_number=measure_index + 1, slot=slot, at=_pair(beat['start']),
                local_at=_pair(beat['local_at']), text=token, display_text=token.strip(trim_chars)))
            slot += 1
    return dict(anchors=anchors, errors=errors)


def authoring_view(song, raw_patterns):
    if _has_repeats(song):
        return repeat_projection(song, raw_patterns).source_view
    return _authoring_view(song, raw_patterns)


def _authoring_view(song, raw_patterns, *, source_only=False):
    """JSON-safe exact notation view; no generated tracker cells or playback claim.

    Returns version=1, row_step, duration (quarter pairs), occurrences (id,
    pattern, at, duration), positions, ownership, conflicts and diagnostics.
    Each position has kind ('beat' or 'note'), id=occurrence/local-id (unique
    within its kind), occurrence, pattern name, beat, track, voice, absolute
    at/end/duration, local_at, row/end_row: all times are reduced quarter pairs,
    except row/end_row which are reduced local row pairs. Beat positions add
    rest, written, stem and optional duration_source. Note positions add note,
    ch, pitch, source_instrument, nullable volume, string/fret, attack_id and
    tied_in/tied_out. Instrument inheritance is deliberately NOT resolved here.
    Ownership lists note intervals with attack/release flags and source command
    fields; conflicts name residual note/instrument cells inside those intervals.
    Absolute raw T20..FF controls provide the optional tempos map and
    tempo_commands source bindings (once per pattern, including redundant T).
    Other raw
    controls remain diagnostics, with no playback-safety claim. Invalid score semantics raise;
    conflicts remain visible for authoring repair. Inputs are never mutated.
    Optional lyrics={anchors,errors} maps raw track streams over the full written
    arrangement. Anchors include blank slots and source beat/occurrence identity;
    missing/gapped measure coverage reports a view error without disabling audio.
    """
    timeline = _score_timeline(song, raw_patterns)
    tempo = song.get('module', {}).get('tempo', 125)
    commands = _tempo_commands(raw_patterns, timeline['step'])
    tempos = _raw_tempos(timeline, raw_patterns, tempo, commands=commands)
    releases = {} if source_only else _performed_releases(timeline, TempoClock(tempo, tempos))
    if not source_only:
        timeline['conflicts'].extend(_performed_conflicts(timeline, releases, raw_patterns, song))
    incoming, outgoing = timeline['incoming'], timeline['outgoing']
    roots = {}
    for record in sorted(timeline['records'], key=lambda r: r['start']):
        identity = record['id']
        roots[identity] = roots[incoming[identity]] if identity in incoming else identity
    positions, ownership, diagnostics = [], [], []
    for kind, records in (('beat', timeline['beats']), ('note', timeline['records'])):
        for record in records:
            position = {key: value for key, value in record.items()
                        if key not in ('start', 'end', 'local_at', 'row', 'end_row')}
            position.update(kind=kind, at=_pair(record['start']), end=_pair(record['end']),
                            duration=_pair(record['end'] - record['start']),
                            **{key: _pair(record[key]) for key in ('local_at', 'row', 'end_row')})
            if kind == 'note':
                identity = record['id']
                position.update(attack_id=roots[identity], tied_in=identity in incoming, tied_out=identity in outgoing)
                release = releases.get(roots[identity], dict(gate_effect=None, let_ring=False, grace=None, swing=None))
                if release['gate_effect'] or release['let_ring'] or release['grace'] or release['swing'] or release.get('context') or release.get('stroke') is not None:
                    position['sounding_end'] = _pair(release['end'])
                if release.get('context'):
                    position['sounding_start'] = _pair(release['start'])
                if release.get('stroke') is not None:
                    position.update(sounding_start=_pair(release['start']),
                                    stroke_delay=_pair(Fraction(release['stroke'], 960)))
                if release['swing']:
                    position.update(sounding_start=_pair(release['start']), swing=release['swing'])
                if release['grace']:
                    position.update(sounding_start=_pair(release['start']),
                                    grace_start=_pair(release['grace']['start']),
                                    grace_end=_pair(release['grace']['end']))
                if release['gate_effect']:
                    position['gate_effect'] = release['gate_effect']
                ownership.append({key: position[key] for key in ('id', 'occurrence', 'pattern', 'beat', 'note',
                                                                 'ch', 'at', 'end', 'row', 'end_row', 'attack_id')})
                ownership[-1].update(attack=identity not in incoming, release=identity not in outgoing,
                                     fields=['note', 'instrument'] + (['volume'] if record['volume'] is not None else []))
                if record['string'] is None:
                    diagnostics.append(f"{identity}: pitch {record['pitch']} has no available fingering")
            positions.append(position)
    positions.sort(key=lambda p: (Fraction(*p['at']), p['kind'], p['id']))
    for pattern in raw_patterns:
        if any((c.effect or c.param) and not (c.effect == 20 and 32 <= c.param <= 255)
               or c.volcmd is not None for row in pattern.rows for c in row):
            diagnostics.append(f'{pattern.name}: raw controls retained; authoring coordinates are not a playback timing map')
    diagnostics.extend(c['message'] for c in timeline['conflicts'])
    lyrics = None
    if any('lyrics' in track for track in song['score']['tracks'].values()):
        lyrics = _lyrics_projection(song['score'], timeline)
        diagnostics.extend(error['message'] for error in lyrics['errors'])
    return dict(version=1, row_step=_pair(timeline['step']), duration=_pair(timeline['duration']),
                occurrences=timeline['occurrences'], positions=positions, ownership=ownership,
                conflicts=timeline['conflicts'], diagnostics=diagnostics, tempo_commands=commands,
                **_tempo_fields(tempo, tempos), **({'lyrics': lyrics} if lyrics is not None else {}))


def pattern_authoring_view(song, raw_patterns, pattern_index, occurrence, *, view=None):
    """One played occurrence's exact notation plus disposable, aligned cell fields.

    rows contains formatted raw cells; display_rows overlays only integral boundaries.
    positions/ownership retain authoring_view's rational coordinates and are filtered
    by occurrence. bindings are {row,ch,field,role,occurrence,pattern,beat,note,value}:
    field is Cell's note/instrument/volcmd, with numeric values (including instrument
    0 and NOTE_OFF). Identity names the SOURCE segment; row/ch address THIS displayed
    occurrence, including a previous occurrence's release at row zero. A final
    arrangement release has no cell binding. No generated cells are persisted.

    A raw field is never overwritten. Conflicts stay visible, with additional field
    collisions reported alongside authoring conflicts. Missing occurrence refuses
    rather than guessing tie state. Optional view must be the same song/raw snapshot's
    authoring_view, allowing callers to reuse its validation and timeline.
    """
    _int(pattern_index, 0, len(raw_patterns) - 1, 'pattern index')
    if occurrence is None:
        raise ValueError('pattern authoring view requires an explicit played occurrence')
    _id(occurrence, 'occurrence')
    ids = song.get('score', {}).get('order_ids', [])
    if occurrence not in ids:
        raise ValueError('pattern authoring view: unknown occurrence')
    order = ids.index(occurrence)
    pattern = raw_patterns[pattern_index]
    if order >= len(song.get('orders', [])) or str(song['orders'][order]) != pattern.name:
        raise ValueError('pattern index does not match occurrence')
    view = authoring_view(song, raw_patterns) if view is None else view
    if (view.get('version') != 1 or order >= len(view.get('occurrences', [])) or
            view['occurrences'][order]['id'] != occurrence or
            view['occurrences'][order]['pattern'] != pattern.name):
        raise ValueError('authoring view does not match occurrence')
    source = view['occurrences'][order]
    start, step = Fraction(*source['at']), Fraction(*view['row_step'])
    if step <= 0 or Fraction(*source['duration']) != len(pattern.rows) * step:
        raise ValueError('authoring view does not match pattern rows')
    display = copy.deepcopy(pattern.rows)
    positions = copy.deepcopy([p for p in view['positions'] if p['occurrence'] == occurrence])
    ownership = copy.deepcopy([p for p in view['ownership'] if p['occurrence'] == occurrence])
    conflicts = copy.deepcopy([c for c in view['conflicts'] if c['occurrence'] == occurrence])
    bindings, addresses = [], {}
    notes = [p for p in positions if p['kind'] == 'note']
    attacks = {}
    for p in notes:
        if not p['tied_in']:
            attacks.setdefault((Fraction(*p['row']), p['ch']), []).append(p)

    def bind(position, row, field, value, role):
        ch = position['ch']
        raw_value = getattr(pattern.rows[row][ch], field)
        if raw_value != (0 if field == 'instrument' else None):
            # Existing authoring conflicts cover note/instrument collisions at attacks.
            if not any(c['row'] == [row, 1] and c['ch'] == ch and field in c['fields'] for c in conflicts):
                conflicts.append(dict(id=position['id'], occurrence=occurrence, pattern=pattern.name,
                                      at=_pair(start + row * step), row=[row, 1], ch=ch, fields=[field],
                                      message=f"{position['id']}: raw {field} conflicts with score {role} "
                                              f"at {occurrence} row {row}"))
            return
        address = row, ch, field
        binding = dict(row=row, ch=ch, field=field, role=role, value=value,
                       **{key: position[key] for key in ('id', 'occurrence', 'pattern', 'beat', 'note', 'track', 'voice')})
        if role == 'release':
            binding['readonly'] = True
            at = start + row * step
            if any(
                other['kind'] == 'note' and other['ch'] == ch and
                other['attack_id'] != position['attack_id'] and
                Fraction(*other.get('sounding_start', other['at'])) <= at <
                Fraction(*other.get('sounding_end', other['end']))
                for other in view['positions']):
                binding['sounding_overlap'] = True
            if position.get('performed_readonly'):
                binding['performed_ambiguous'] = position['performed_ambiguous']
        addresses.setdefault(address, []).append(binding)

    for position in notes:
        row = Fraction(*position['row'])
        if position['tied_in'] or row.denominator != 1:
            continue
        row = int(row)
        bind(position, row, 'note', position['pitch'], 'attack')
        bind(position, row, 'instrument', position['source_instrument'], 'attack')
        if position['volume'] is not None:
            bind(position, row, 'volcmd', position['volume'], 'attack')
    previous = view['occurrences'][order - 1]['id'] if order else None
    for position in view['positions']:
        if position['kind'] != 'note':
            continue
        if 'sounding_end' in position:
            if position['tied_in']:
                continue
            end = position['sounding_end']
        else:
            if position['tied_out'] or position['occurrence'] not in (occurrence, previous):
                continue
            end = position['end']
        row = (Fraction(*end) - start) / step
        if row.denominator != 1 or not 0 <= row < len(pattern.rows):
            continue
        ch, row = position['ch'], int(row)
        raw_note = pattern.rows[row][ch].note
        coincident = attacks.get((row, ch), [])
        if (coincident and all(p['voice'] == position['voice'] for p in coincident) or
                raw_note is not None and 0 <= raw_note <= 119):
            continue  # Same-voice adjacency retains the usual tracker attack display.
        bind(position, row, 'note', NOTE_OFF, 'release')
    # One voice's coincident releases (a held note ending with its successor) share one
    # read-only NOTE_OFF; releases of different voices stay a visible collision.
    for owners in addresses.values():
        if len(owners) > 1 and all(o['role'] == 'release' and (o['track'], o['voice']) ==
                                   (owners[0]['track'], owners[0]['voice']) for o in owners):
            owners[1:] = []
    collided = {(row, ch) for (row, ch, field), owners in addresses.items() if len(owners) > 1}
    collisions = {}
    for (row, ch, field), owners in addresses.items():
        if (row, ch) in collided:
            group = collisions.setdefault((row, ch), {})
            for owner in owners:
                key = owner['id'], owner['role']
                entry = group.setdefault(key, dict(
                    **{k: owner[k] for k in ('id', 'occurrence', 'pattern', 'beat', 'note', 'track', 'voice', 'role')},
                    fields=[], values={}))
                entry['fields'].append(field)
                entry['values'][field] = owner['value']
        else:
            bindings.append({key: value for key, value in owners[0].items() if key not in ('id', 'track', 'voice')})
            if not owners[0].get('sounding_overlap'):
                setattr(display[row][ch], field, owners[0]['value'])
    collision_list = [dict(row=row, ch=ch, owners=list(owners.values()))
                      for (row, ch), owners in sorted(collisions.items())]
    bindings.sort(key=lambda b: (b['row'], b['ch'], b['field']))
    return dict(version=1, index=pattern_index, pattern=pattern.name, occurrence=occurrence,
                row_step=list(view['row_step']), rows=[[format_cell(c) for c in row] for row in pattern.rows],
                display_rows=[[format_cell(c) for c in row] for row in display],
                positions=positions, ownership=ownership, bindings=bindings, collisions=collision_list, conflicts=conflicts,
                diagnostics=list(view['diagnostics']))


def playback_plan(song, raw_patterns, sample_rate=44100):
    _guard_repeat_projection(song)
    return _playback_plan(song, raw_patterns, sample_rate)


def fade_expression_streams(fades, tracks, duration):
    """TG track expression callbacks, shared by native audio, MIDI and standalone IT."""
    streams, identities, ordinals, count = {}, set(), set(), 0
    if not isinstance(fades, list) or len(fades) > 100000:
        raise ValueError('fade_in: invalid or excessive ramp list')
    for fade in fades:
        if (not isinstance(fade, dict) or not isinstance(fade.get('id'), str) or not fade['id'] or
                fade['id'] in identities or fade.get('track') not in tracks or
                type(fade.get('ticks')) is not int or not 0 <= fade['ticks'] <= 2147483647 or
                type(fade.get('ordinal')) is not int or fade['ordinal'] < 0 or fade['ordinal'] in ordinals):
            raise ValueError('fade_in: invalid source identity, track, duration or insertion ordinal')
        at = _fraction(fade.get('at'), 'fade_in start')
        if at < 0 or at > duration:
            raise ValueError('fade_in: start outside arrangement')
        identities.add(fade['id']); ordinals.add(fade['ordinal'])
        stream = streams.setdefault(fade['track'], [(Fraction(0), -1, 127)])
        ticks = fade['ticks']
        count += 97 if ticks else 1
        if count + len(streams) > 200000:
            raise ValueError('fade_in: more than 200000 logical expression events; split the arrangement')
        if ticks:
            stream.extend((at + Fraction(i * (ticks // 96), 960), fade['ordinal'], 31 + i) for i in range(96))
        stream.append((at + Fraction(ticks, 960), fade['ordinal'], 127))
    for stream in streams.values():
        stream.sort(key=lambda e: (e[0], e[1]))
    return streams


def _fade_gain_events(events, streams, clock, end, raw_actions):
    """Compose expression with each score identity's original gain, including released tails."""
    affected = [e for e in events if e['type'] == 'note_on' and e['track'] in streams]
    parents = {e['ch'] for e in affected}
    if any(ch in parents and (cell.note is not None or cell.instrument) for _, ch, cell in raw_actions):
        raise ValueError('fade_in: raw notes/instruments on an expression track need owned voice identities')
    for attack in affected:
        values = {at: value for at, _, value in streams[attack['track']]}  # Last source callback wins at a tick.
        start = Fraction(*attack['at'])
        preceding = [at for at in values if at <= start]
        controls = {start: values[max(preceding)] if preceding else 127}
        controls.update({at: value for at, value in values.items() if start < at <= end})
        velocities = [layer['velocity'] for layer in attack['layers']] if 'layers' in attack else [attack.get('velocity')]
        for at, expression in sorted(controls.items()):
            if len(events) >= 200000:
                raise ValueError('fade_in: more than 200000 routed native events; split the arrangement')
            fields = {key: attack[key] for key in ('id', 'occurrence', 'pattern', 'beat', 'note', 'track', 'ch')}
            events.append(dict(fields, **clock(at), type='gain', expression=expression,
                               gains=[(127 if v is None else v) * expression / (127 * 127) for v in velocities]))
    events.sort(key=lambda e: (e['frame'], {'note_off': 0, 'note_on': 1, 'pitch': 2, 'gain': 3}[e['type']]))


def _playback_plan(song, raw_patterns, sample_rate=44100, *, timeline=None):
    """Build a JSON-safe exact score schedule, without changing strict IT projection.

The plan schedules score-owned notes only. Its caller must merge it with raw
tracker playback on the SAME channel/instrument state, not independently mix a
second song. Raw attacks outside score sustains are retained in the backing
module and are not emitted a second time. No renderer is selected or invoked.

Integer module.tempo and row-aligned absolute T20..FF changes. Qualified Xxx, M00..M40, Dxx, V00..V80 and
ordinary volume-column v00..v64 stay in the backing and are executed by the
shared parent batch mixer. Raw speed/tempo slides/flow and all other effect or
volume-column commands refuse explicitly. Raw instrument fields and attacks before score notes
seed channel instrument memory. Instrument 0 resolves from that memory (including
prior score attacks) or refuses; it never picks a sample. volume=None means no
explicit volume command: the matched mixer must honor the resolved instrument's
defaults/inheritance, not substitute a made-up velocity. source_instrument and
instrument_inherited retain the distinction needed by that mixer.

Output: {version,sample_rate,tempo,tempos?,row_step,duration,occurrences,events,positions,
diagnostics}. Optional tempos is [{at:[n,d],bpm:32..255}], starting at zero.
It resolves raw absolute T commands in arrangement order; a row-zero override
is explicit in the map while tempo retains module.tempo. Every time is a reduced fraction pair. duration has quarters,
seconds,frames; each event has type note_on/note_off/pitch/gain, id, occurrence, pattern,
beat,note,track,voice,ch,pitch,instrument,source_instrument,instrument_inherited,
volume,at (absolute quarters),seconds,frame. id is occurrence/note (both IDs forbid
slashes); a tied chain shares its first note's event id. positions includes every
written segment, its attack_id, rational local row and exact end, even if tied.
Pitch events add semitones (absolute voice offset) and bend_value (TG 64-neutral
controller value); curve timing follows TG legacy ticks while onsets stay exact.
Gain events contain one composed gain per layer from shared track expression, including released tails.

Frames round absolute rational seconds to nearest, half up; deltas never
accumulate rounding. Events sort by frame, then note_off, note_on, pitch, gain, then
stable identity; coincident controls for one identity retain source order.
Sub-frame notes rounding to zero frames refuse. Occurrence ties
may differ for reused patterns. Final-boundary note-offs are explicit events.
Written beats still fit their pattern; qualified cross-voice overlaps use contexts. Arbitrary
positive rational starts/durations need not lie on an IT row/tick boundary.
"""
    _int(sample_rate, 8000, 384000, 'sample rate')
    validate_score(song)
    if 'score' not in song:
        raise ValueError('exact playback planning requires a score; legacy songs retain their existing player')
    score, module = song['score'], song.get('module', {})
    tempo = _int(module.get('tempo', 125), 32, 255, 'module.tempo')
    for pattern in raw_patterns:
        for row in pattern.rows:
            for cell in row:
                if cell.effect in (1, 2, 3) or cell.effect == 20 and not 32 <= cell.param <= 255 or cell.effect == 19 and cell.param >> 4 in (6, 11, 14):
                    raise ValueError(f'{pattern.name}: raw tempo/speed/flow commands unsupported; only absolute T20..FF is supported')
                control = (cell.effect in (4, 24) and 0 <= cell.param <= 255 or
                           cell.effect == 20 and 32 <= cell.param <= 255 or
                           cell.effect == 13 and 0 <= cell.param <= 64 or
                           cell.effect == 22 and 0 <= cell.param <= 128)
                volume = cell.volcmd is None or type(cell.volcmd) is int and 0 <= cell.volcmd <= 64
                if not volume or (cell.effect or cell.param) and not control:
                    raise ValueError(f'{pattern.name}: raw effect/volume commands require shared mixer semantics; playback plan refused')
    timeline = _score_timeline(song, raw_patterns) if timeline is None else timeline
    tempos = _raw_tempos(timeline, raw_patterns, tempo)
    tempo_clock = TempoClock(tempo, tempos)
    releases = _performed_releases(timeline, tempo_clock)
    timeline['conflicts'].extend(_performed_conflicts(timeline, releases, raw_patterns, song))
    if timeline['conflicts']:
        raise ValueError(timeline['conflicts'][0]['message'])
    patterns_by_name = {p.name: p for p in raw_patterns}
    for record in timeline['records']:
        row = record['row']
        if (record['volume'] is not None and record['id'] not in timeline['incoming'] and
                row.denominator == 1 and patterns_by_name[record['pattern']].rows[int(row)][record['ch']].volcmd is not None):
            raise ValueError(f"{record['id']}: raw volume conflicts with score-owned attack volume")
    step, cursor, occurrences = timeline['step'], timeline['duration'], timeline['occurrences']
    records, by_id, raw_actions = timeline['records'], timeline['by_id'], timeline['raw_actions']
    instrument_entries = song.get('instruments') if song.get('instruments') else song.get('samples', {})
    declared = {int(key) for key in instrument_entries if isinstance(key, (str, int)) and str(key).isdigit()}
    memory = {}
    actions = [(at, 0, ch, cell) for at, ch, cell in raw_actions]
    actions.extend((r['start'], 1, r['ch'], r) for r in records)
    for at, kind, ch, item in sorted(actions, key=lambda item: (item[0], item[1], item[2])):
        if kind == 0:
            if item.instrument:
                _int(item.instrument, 1, 99, 'raw instrument')
                if item.instrument not in declared:
                    raise ValueError(f'raw instrument {item.instrument} has no declared instrument/sample slot')
                memory[ch] = item.instrument
        else:
            source = item['source_instrument']
            instrument = source or memory.get(ch)
            if instrument is None:
                raise ValueError(f"{item['id']}: instrument inheritance 0 has no preceding channel instrument; assign one explicitly")
            if instrument not in declared:
                raise ValueError(f"{item['id']}: instrument {instrument} has no declared instrument/sample slot")
            item['instrument'] = instrument
            item['instrument_inherited'] = source == 0
            memory[ch] = instrument
    incoming, outgoing = timeline['incoming'], timeline['outgoing']
    for right_id, left_id in incoming.items():
        left, right = by_id[left_id], by_id[right_id]
        if left['instrument'] != right['instrument']:
            raise ValueError('playback tie endpoints must be adjacent with the same resolved instrument')

    def clock(at):
        seconds = tempo_clock.seconds_at(at)
        frames = seconds * sample_rate
        frame = frames.numerator // frames.denominator + (2 * (frames.numerator % frames.denominator) >= frames.denominator)
        return {'at': _pair(at), 'seconds': _pair(seconds), 'frame': frame}

    events, positions = [], []
    velocities = _performed_velocities(timeline)
    # TG stops at the first following authored voice, even a rest or a chord
    # without this string; absent voices do not stop the search.
    voice_beats, beat_notes, next_beat = {}, {}, {}
    for b in timeline['beats']:
        voice_beats.setdefault((b['track'], b['voice']), []).append(b)
    for r in records:
        beat_notes.setdefault(f"{r['occurrence']}/{r['beat']}", []).append(r)
    for values in voice_beats.values():
        values.sort(key=lambda b: b['start'])
        next_beat.update((a['id'], b) for a, b in zip(values, values[1:]))
    for record in sorted(records, key=lambda r: (r['start'], r['id'])):
        if record['id'] in incoming:
            continue
        chain, current = [record], record
        while current['id'] in outgoing:
            current = by_id[outgoing[current['id']]]
            chain.append(current)
        performed = releases[record['id']]
        sounding_end, gate_effect = performed['end'], performed['gate_effect']
        onset, release = clock(performed['start']), clock(sounding_end)
        repetition = record.get('trill') or record.get('tremolo_picking')
        if repetition is None and onset['frame'] == release['frame']:
            raise ValueError(f"{record['id']}: note rounds to zero sample frames at {sample_rate} Hz")
        fields = {key: record[key] for key in ('id', 'occurrence', 'pattern', 'beat', 'note', 'track', 'voice',
                  'ch', 'pitch', 'instrument', 'source_instrument', 'instrument_inherited', 'volume', 'velocity')}
        fields.update({key: record[key] for key in ('play_id', 'source_occurrence', 'source_order',
                       'source_measure', 'source_pattern', 'source_note_id', 'source_beat_id',
                       'measure_play_id', 'stroke', 'pick_stroke') if key in record})
        if performed['grace']:
            grace = performed['grace']
            grace_on, grace_off = clock(grace['start']), clock(grace['end'])
            if grace_on['frame'] >= grace_off['frame']:
                raise ValueError(f"{record['id']}: grace rounds to zero sample frames at {sample_rate} Hz")
            if len(events) + 2 > 200000:
                raise ValueError('native score plan exceeds 200000 events; split the arrangement')
            grace_fields = dict(fields, id=f"{record['id']}/grace", source_id=record['id'], role='grace',
                                pitch=grace['pitch'], velocity=record['grace']['velocity'],
                                authored_velocity=record['grace']['velocity'])
            events.append(dict(grace_fields, type='note_on', **grace_on))
            events.append(dict(grace_fields, type='note_off', **grace_off))
        attack = dict(fields, type='note_on', **onset)
        if performed.get('hold'):
            attack['hold'] = True
        if record['id'] in velocities:
            attack.update(authored_velocity=record['velocity'], velocity=velocities[record['id']])
        if repetition is None and record.get('harmonic') is not None:
            attack['layers'] = _harmonic_layers(record, attack['velocity'])
        ticks = performed['ticks']
        if repetition is not None:
            if record['velocity'] is None:
                raise ValueError(f"{record['id']}: repetition requires explicit authored MIDI velocity")
            alternate = record['pitch']
            if record.get('trill') is not None:
                track = song['score']['tracks'][record['track']]
                alternate = track['tuning'][record['string'] - 1] + track.get('capo', 0) + repetition['fret']
            tick, pulse, length = 0, 0, 3840 // repetition['value']
            # TG 2.1.0: omit tails of at most ten ticks; clip only the last
            # pulse. Preserve the exact native onset and the tied tick carry.
            while tick + 10 < ticks:
                if len(events) + 2 > 200000:
                    raise ValueError('native score plan exceeds 200000 events; split the arrangement')
                if tick + length >= ticks:
                    length = ticks - tick - 1
                pulse_fields = dict(fields, id=f"{record['id']}/pulse/{pulse}",
                                    source_id=record['id'], pulse=pulse,
                                    pitch=alternate if pulse % 2 else record['pitch'],
                                    authored_velocity=record['velocity'], velocity=attack['velocity'])
                events.append(dict(pulse_fields, type='note_on',
                                   **clock(performed['start'] + Fraction(tick, 960))))
                events.append(dict(pulse_fields, type='note_off',
                                   **clock(performed['start'] + Fraction(tick + length, 960))))
                tick += length
                pulse += 1
        else:
            if len(events) + 2 > 200000:
                raise ValueError('native score plan exceeds 200000 events; split the arrangement')
            events.append(attack)
            events.append(dict(fields, type='note_off', **release))
        slide = None
        if record.get('slide'):
            if record['string'] is None:
                raise ValueError(f"{record['id']}: slide needs resolved string/fret")
            following = next_beat.get(f"{record['occurrence']}/{record['beat']}")
            target = next((r for r in beat_notes.get(following['id'], [])
                           if r['string'] == record['string']), None) if following else None
            if target is not None:
                slide = (int(target['start'] * 960) - int(record['start'] * 960),
                         target['fret'] - record['fret'])
        for tick, value in (() if repetition is not None else _pitch_controls(record, ticks, slide)):
            # TG slide lookup stays anchored to the written beat, unlike bend,
            # bar and vibrato. Refuse controls preceding a grace-delayed main.
            at = (record['start'] if slide is not None else performed['start']) + Fraction(tick, 960)
            if at < performed['start']:
                technique = 'grace' if performed['grace'] else 'stroke' if performed.get('stroke') is not None else 'swing'
                raise ValueError(f"{record['id']}: {technique} with slide controls before the main attack is unsupported")
            if at > cursor:
                raise ValueError(f"{record['id']}: pitch control exceeds the arrangement")
            events.append(dict(fields, type='pitch', semitones=(value - 64) * 3 / 16,
                               bend_value=value, **clock(at)))
            if len(events) > 200000:
                raise ValueError('native score plan exceeds 200000 events; split the arrangement')
        for segment in chain:
            position = {key: segment[key] for key in ('id', 'occurrence', 'pattern', 'beat', 'note', 'track', 'voice',
                        'ch', 'pitch', 'instrument', 'source_instrument', 'instrument_inherited', 'volume', 'velocity', 'string', 'fret')}
            position.update({key: segment[key] for key in ('play_id', 'source_occurrence', 'source_order',
                            'source_measure', 'source_pattern', 'source_note_id', 'source_beat_id',
                            'measure_play_id', 'source_local_at', 'source_row', 'source_end_row',
                            'stroke', 'pick_stroke', 'fade_in', 'chord', 'tapping', 'slapping', 'popping') if key in segment})
            position.update(clock(segment['start']), end=_pair(segment['end']), end_frame=clock(segment['end'])['frame'],
                            local_at=_pair(segment['local_at']), row=_pair(segment['row']), end_row=_pair(segment['end_row']),
                            attack_id=record['id'], tied_in=segment['id'] in incoming, tied_out=segment['id'] in outgoing)
            if gate_effect or performed['let_ring'] or performed['grace'] or performed['swing'] or performed.get('context') or performed.get('stroke') is not None:
                position['sounding_end'] = _pair(sounding_end)
            if performed.get('context'):
                position.update(sounding_start=_pair(performed['start']), sounding_start_frame=onset['frame'])
            if performed.get('stroke') is not None:
                position.update(sounding_start=_pair(performed['start']), sounding_start_frame=onset['frame'],
                                stroke_delay=_pair(Fraction(performed['stroke'], 960)))
            if performed['swing']:
                position.update(sounding_start=_pair(performed['start']),
                                sounding_start_frame=onset['frame'], swing=performed['swing'])
            if 'play_id' in segment:
                position.update(sounding_start=_pair(performed['start']), sounding_end=_pair(sounding_end),
                                sounding_start_frame=onset['frame'])
            if performed['grace']:
                position.update(sounding_start=_pair(performed['start']),
                                sounding_start_frame=onset['frame'],
                                grace_start=_pair(performed['grace']['start']),
                                grace_end=_pair(performed['grace']['end']))
            if gate_effect:
                position['gate_effect'] = gate_effect
            positions.append(position)
    priority = {'note_off': 0, 'note_on': 1, 'pitch': 2}
    events.sort(key=lambda event: (event['frame'], priority[event['type']], event['id']))
    _context_schedule(events, timeline)
    positions.sort(key=lambda position: (Fraction(*position['at']), position['id']))
    end = clock(cursor)
    diagnostics = ['Residual raw note/instrument cells are backing playback, not duplicated in score events.'] if raw_actions else []
    midi_fades = []
    if any(release['midi_fade'] is not None for release in releases.values()):
        ordinals = _source_ordinals(timeline)
        midi_fades = [dict(id=identity, track=by_id[identity]['track'], ordinal=ordinals[identity],
                          **release['midi_fade'])
                      for identity, release in releases.items() if release['midi_fade'] is not None]
        midi_fades.sort(key=lambda fade: fade['ordinal'])
        streams = fade_expression_streams(midi_fades, timeline['track_order'], cursor)
        _fade_gain_events(events, streams, clock, cursor, raw_actions)
    return {'version': 1, 'sample_rate': sample_rate, 'tempo': tempo, 'row_step': _pair(step),
            'duration': {'quarters': end['at'], 'seconds': end['seconds'], 'frames': end['frame']},
            'occurrences': occurrences, 'events': events, 'positions': positions, 'diagnostics': diagnostics,
            'midi_fades': midi_fades,
            **_tempo_fields(tempo, tempos)}


def _new_score(song):
    return {'version': 1, 'tracks': {}, 'patterns': {},
            'order_ids': [f'occ_{i + 1}' for i in range(len(song.get('orders', [])))], 'ties': [], 'measures': []}


def _beat(score, pattern, identity):
    try:
        return next(b for b in score['patterns'][pattern]['beats'] if b['id'] == identity)
    except (KeyError, StopIteration, TypeError):
        raise ValueError(f'{pattern}: unknown beat {identity}') from None


def _repair_fingering(score, beat):
    track = _track(score, beat)
    for note in beat['notes']:
        if is_percussion(track) and note.get('string') is not None:
            note['fret'] = note['pitch']
        if _fingering(track, note) != (note.get('string'), note.get('fret')):
            note.pop('string', None)
            note.pop('fret', None)
    resolved = _resolved_notes(score, beat)
    for note, value in zip(beat['notes'], resolved):
        note.update(string=value['string'], fret=value['fret'])


def validate_tuning_preset(value):
    """A reusable tuning has no channel, instrument or file bindings."""
    _keys(value, ('name', 'tuning', 'capo', 'max_fret'), 'tuning preset')
    tuning = value.get('tuning')
    if not isinstance(tuning, list) or not 1 <= len(tuning) <= 25:
        raise ValueError('tuning preset needs 1..25 pitches, highest string first')
    result = dict(tuning=[_int(p, 0, 119, 'tuning pitch') for p in tuning],
                  capo=_int(value.get('capo', 0), -24, 24, 'tuning capo'),
                  max_fret=_int(value.get('max_fret', 29), 0, 36, 'tuning max_fret'))
    if 'name' in value:
        if not isinstance(value['name'], str) or not value['name'].strip() or len(value['name']) > 80:
            raise ValueError('tuning preset name needs 1..80 nonblank characters')
        result['name'] = value['name']
    return result


def score_template(song):
    """Reusable setup only: no notes, source routing, raw cells, lyrics or sample paths."""
    validate_score(song)
    if not song.get('score', {}).get('tracks'):
        raise ValueError('a score template needs at least one native track')
    score = song['score']
    tracks = {tid: {k: copy.deepcopy(v) for k, v in track.items()
                    if k not in ('channels', 'instrument', 'lyrics', 'solo_mute')}
              for tid, track in score['tracks'].items()}
    for track in tracks.values():
        track.get('midi', {}).pop('source_pan', None)
        track.get('midi', {}).pop('source_volume', None)
    return dict(version=1, tracks=tracks, meter=copy.deepcopy(score.get('measures', [{}])[0].get('meter', [4, 4])
                if score.get('measures') else [4, 4]), tempo=song.get('module', {}).get('tempo', 120),
                metadata=copy.deepcopy(score.get('metadata', {})))


def new_score_song(title, sample, template='guitar', bars=4, meter=None, tempo=None):
    """Construct an empty, playable native score using one caller-created placeholder sample."""
    from . import api
    guitar = dict(name='Guitar', tuning=[64, 59, 55, 50, 45, 40], capo=0, max_fret=24,
                  clef='treble', midi=dict(program=25, bank=0))
    bass = dict(name='Bass', tuning=[43, 38, 33, 28], capo=0, max_fret=24,
                clef='bass', midi=dict(program=33, bank=0))
    drums = dict(name='Drums', tuning=[0, 0, 0], capo=0, max_fret=24,
                 clef='percussion', midi=dict(program=0, bank=128))
    if isinstance(template, str):
        setups = {'guitar': dict(guitar=guitar), 'bass': dict(bass=bass), 'drums': dict(drums=drums),
                  'band': dict(guitar=guitar, guitar2=dict(guitar, name='Rhythm guitar'), bass=bass, drums=drums)}
        if template not in setups:
            raise ValueError('native template must be guitar, bass, drums, band or a saved score setup')
        template = dict(version=1, tracks=setups[template], meter=[4, 4], tempo=120, metadata={})
    _keys(template, ('version', 'tracks', 'meter', 'tempo', 'metadata'), 'score template')
    _int(template.get('version'), 1, 1, 'score template version')
    tracks = copy.deepcopy(template.get('tracks'))
    if not isinstance(tracks, dict) or not 1 <= len(tracks) <= 64:
        raise ValueError('score template requires 1..64 tracks')
    bars = _int(bars, 1, 128, 'new score bars')
    meter = copy.deepcopy(template.get('meter', [4, 4]) if meter is None else meter)
    if not isinstance(meter, list) or len(meter) != 2:
        raise ValueError('new score meter is [numerator, denominator]')
    num, den = _int(meter[0], 1, 64, 'meter numerator'), _int(meter[1], 1, 64, 'meter denominator')
    if den not in (1, 2, 4, 8, 16, 32, 64):
        raise ValueError('meter denominator must be a power of two through 64')
    length, rows = Fraction(num * 4, den), Fraction(num * 48, den)
    if rows.denominator != 1 or not 1 <= rows <= 200:
        raise ValueError('new score meter must fit 1..200 exact tracker rows')
    tempo = _int(template.get('tempo', 120) if tempo is None else tempo, 32, 255, 'new score tempo')
    channels = []
    for tid, track in tracks.items():
        _id(tid, 'template track')
        if not isinstance(track, dict) or any(k in track for k in ('channels', 'instrument', 'lyrics', 'solo_mute')):
            raise ValueError('score template tracks contain setup only, without channel/instrument/lyrics bindings')
        tuning = track.get('tuning')
        if not isinstance(tuning, list) or not 1 <= len(tuning) <= 25:
            raise ValueError('score template track needs 1..25 tuning pitches')
        track['channels'] = list(range(len(channels), len(channels) + len(tuning)))
        channels.extend(dict(name=f'{track.get("name", tid)} {i+1}', pan=32) for i in range(len(tuning)))
        track['instrument'] = list(tracks).index(tid) + 1
        track.get('midi', {}).pop('source_pan', None)
        track.get('midi', {}).pop('source_volume', None)
    if len(channels) > 64:
        raise ValueError('score template exceeds 64 tracker channels')
    song = api.new_song(title=title, channels=len(channels), tempo=tempo, speed=2)
    song['module'].update(channels=channels, sample_rate=44100)
    song['samples'] = {1: dict(file=sample, name='Placeholder tone', base_note='C-5')}
    song['instruments'] = {track['instrument']: dict(name=track.get('name', tid), **(
        dict(keymap=[dict(notes='C-0..B-9', sample=1, play_note='C-5')]) if is_percussion(track) else dict(sample=1)))
        for tid, track in tracks.items()}
    song['score'] = dict(version=1, tracks=tracks, patterns={}, order_ids=[], ties=[], measures=[])
    if template.get('metadata'):
        song['score']['metadata'] = copy.deepcopy(template['metadata'])
    for i in range(bars):
        name, oid = f'bar{i+1}', f'occ_{i+1}'
        song['orders'].append(name)
        song['patterns'][name] = dict(rows=int(rows), data='')
        song['score']['order_ids'].append(oid)
        beats = []
        for tid in tracks:
            at = Fraction(0)
            for j, written in enumerate(_split_written(length)):
                beats.append(dict(id=f'{tid}_rest{j}', track=tid, voice=0, at=_pair(at), written=written, notes=[]))
                at += duration_quarters(written)
        song['score']['patterns'][name] = dict(row_step=[1, 12], beats=beats)
        song['score']['measures'].append(dict(id=f'm{i+1}', meter=meter.copy(), **{
            'from': dict(occurrence=oid, at=[0, 1]), 'to': dict(occurrence=oid, at=_pair(length))}))
    validate_score(song)
    return song


def track_command(song, raw_patterns, edit):
    """Track ordering is notation ordering; appended channels never displace existing tracker cells."""
    _keys(edit, ('action', 'track', 'new_track', 'name', 'value', 'to', 'remove_notes', 'revision'), 'track command')
    validate_score(song)
    candidate = copy.deepcopy(song)
    score, action = candidate['score'], edit.get('action')
    tracks, identity, added = score['tracks'], edit.get('track'), 0
    if action in ('track_add', 'track_clone'):
        if action == 'track_clone':
            if identity not in tracks:
                raise ValueError('Clone track needs an existing track')
            value = copy.deepcopy(tracks[identity])
            new_id = edit.get('new_track') or _local_id(identity + '_copy', set(tracks))
            if 'name' in edit:
                value['name'] = edit['name']
        else:
            value = copy.deepcopy(edit.get('value'))
            new_id = identity or _local_id('track', set(tracks))
        _id(new_id, 'new track id')
        if new_id in tracks or not isinstance(value, dict):
            raise ValueError('New track needs a distinct id and a complete track setup')
        tuning = value.get('tuning')
        if not isinstance(tuning, list) or not 1 <= len(tuning) <= 25:
            raise ValueError('New track needs 1..25 tuning pitches')
        old_count, added = _channels(candidate), len(tuning)
        if old_count + added > 64:
            raise ValueError('Adding this track exceeds 64 channels; existing raw channels are preserved')
        channels = candidate['module']['channels']
        if not isinstance(channels, list):
            channels = [dict(name=f'Ch {i+1}', pan=32) for i in range(old_count)]
            candidate['module']['channels'] = channels
        previous = list(value.get('channels', []))
        value['channels'] = list(range(old_count, old_count + added))
        for i in range(added):
            channel = copy.deepcopy(channels[previous[i]]) if action == 'track_clone' else dict(pan=32)
            channel['name'] = f'{value.get("name", new_id)} {i+1}'
            channels.append(channel)
        tracks[new_id] = value
        # Validate track bounds before copying notes or indexing its routing.
        probe = copy.deepcopy(candidate)
        probe['score']['patterns'], probe['score']['ties'], probe['score']['measures'] = {}, [], []
        validate_score(probe)
        if action == 'track_clone':
            remap = {}
            channel_map = dict(zip(previous, value['channels']))
            for name, pattern in score['patterns'].items():
                taken = {b['id'] for b in pattern['beats']} | {n['id'] for b in pattern['beats'] for n in b['notes']}
                for original in list(pattern['beats']):
                    if original['track'] != identity:
                        continue
                    beat = copy.deepcopy(original)
                    beat.update(id=_local_id(new_id + '_' + beat['id'], taken), track=new_id)
                    taken.add(beat['id'])
                    for note in beat['notes']:
                        old = note['id']
                        note['id'] = _local_id(new_id + '_' + old, taken)
                        taken.add(note['id']); remap[name, old] = note['id']
                        if 'channel' in note:
                            note['channel'] = channel_map[note['channel']]
                    pattern['beats'].append(beat)
            by_occurrence = dict(zip(score['order_ids'], map(str, candidate['orders'])))
            for tie in list(score.get('ties', [])):
                if all((by_occurrence[e['occurrence']], e['note']) in remap for e in tie.values()):
                    score['ties'].append({side: dict(occurrence=e['occurrence'], note=remap[by_occurrence[e['occurrence']], e['note']])
                                          for side, e in tie.items()})
            for measure in score.get('measures', []):
                if identity in measure.get('staff', {}):
                    measure['staff'][new_id] = copy.deepcopy(measure['staff'][identity])
        identity = new_id
    elif action == 'track_remove':
        candidate = apply_score_edit(candidate, dict(op='track_delete', track=identity,
            remove_notes=edit.get('remove_notes', False)))
    elif action == 'track_move':
        if identity not in tracks:
            raise ValueError('Move track needs an existing track')
        destination = _int(edit.get('to'), 0, len(tracks) - 1, 'track destination')
        order = list(tracks)
        order.remove(identity); order.insert(destination, identity)
        score['tracks'] = {tid: tracks[tid] for tid in order}
    else:
        raise ValueError('track action must be track_add, track_clone, track_remove or track_move')
    validate_score(candidate)
    raw = copy.deepcopy(raw_patterns)
    for pattern in raw:
        for row in pattern.rows:
            row.extend(Cell() for _ in range(added))
    checked = authoring_view(candidate, raw)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    return candidate, dict(track=identity, channels_added=added, report={
        'track_add': 'Added track with independent channels.', 'track_clone': 'Cloned track, notation and ties with independent channels.',
        'track_remove': 'Removed track notation; existing channels, raw cells and sounds are retained.',
        'track_move': 'Moved track; tracker channels retain their positions.'}[action])


def apply_score_edit(song, edit):
    """Apply a bounded event edit to a deep copy; projection remains the final preflight."""
    if not isinstance(edit, dict):
        raise ValueError('score edit must be a mapping')
    result = copy.deepcopy(song)
    score = result.setdefault('score', _new_score(result))
    op = edit.get('op')
    if op == 'chord_notes':
        _keys(edit, ('op', 'pattern', 'beat', 'chord', 'velocity', 'remove_ties'), op)
        validate_score(result)
        name = edit.get('pattern')
        if not isinstance(name, str) or name not in score['patterns']:
            raise ValueError('chord_notes requires an existing score pattern')
        selected = _beat(score, name, edit.get('beat'))
        track = _track(score, selected)
        chord = edit.get('chord')
        if chord is None:
            raise ValueError('chord_notes requires a complete nonnull chord diagram')
        _validate_chord(chord, track)
        velocity = _int(edit.get('velocity', 95), 0, 127, 'chord_notes velocity')
        remove_ties = edit.get('remove_ties', False)
        if type(remove_ties) is not bool:
            raise ValueError('chord_notes remove_ties must be boolean')
        cohort = [b for b in score['patterns'][name]['beats'] if _cohort_key(b) == _cohort_key(selected)]
        played = {i + 1 for i, fret in enumerate(chord['frets']) if fret >= 0}
        if not played and not any(b['notes'] for b in cohort):
            return result  # TG does nothing when both beat and diagram are silent.
        removed = [(selected['id'], n['id']) for n in selected['notes']]
        for member in cohort:
            if member is selected or not played:
                continue
            for note in _resolved_notes(score, member):
                if note['string'] is None:
                    raise ValueError(f"chord_notes: other-voice note {note['id']} has no resolved string")
                if note['string'] in played:
                    removed.append((member['id'], note['id']))
        _delete_incident_ties(result, name, {nid for _, nid in removed}, remove_ties)
        used = {n['id'] for b in score['patterns'][name]['beats'] for n in b['notes']}
        notes = []
        for string in sorted(played):
            fret = chord['frets'][string - 1]
            pitch = _int(track['tuning'][string - 1] + track.get('capo', 0) + fret,
                         0, 119, f'chord_notes string {string} pitch')
            identity = _local_id(f"chord_{selected['id']}_s{string}", used)
            used.add(identity)
            notes.append(dict(id=identity, pitch=pitch, string=string, fret=fret, velocity=velocity))
        # Private intermediate candidates never reach history or playback. Delete
        # first so an all-muted final replacement can explicitly reattach its
        # diagram after the normal final-sounding-note cleanup has run.
        for bid, nid in removed:
            result = apply_score_edit(result, dict(op='note_delete', pattern=name, beat=bid, note=nid))
        replacement = copy.deepcopy(_beat(result['score'], name, selected['id']))
        replacement.update(notes=notes, chord=copy.deepcopy(chord))
        return apply_score_edit(result, dict(op='beat_set', pattern=name, beat=replacement))
    elif op == 'metadata_set':
        _keys(edit, ('op', 'value'), op)
        score['metadata'] = copy.deepcopy(edit.get('value'))
    elif op == 'track_set':
        _keys(edit, ('op', 'track', 'value'), op)
        identity = _id(edit.get('track'), 'track id')
        previous = score['tracks'].get(identity, {})
        score['tracks'][identity] = copy.deepcopy(edit.get('value'))
        # Check track bounds before using its tuning to repair existing notes.
        probe = copy.deepcopy(result)
        probe['score']['patterns'], probe['score']['ties'] = {}, []
        validate_score(probe)
        track = score['tracks'][identity]
        if previous and is_percussion(previous) != is_percussion(track) and any(
                b['track'] == identity and b['notes'] for p in score['patterns'].values() for b in p['beats']):
            raise ValueError('populated pitched/percussion track conversion is unsupported')
        if previous and previous.get('channels') != track['channels']:
            track.get('midi', {}).pop('source_pan', None)
            track.get('midi', {}).pop('source_volume', None)
        if (previous.get('tuning'), previous.get('capo', 0), previous.get('max_fret', 29)) != (
                track['tuning'], track.get('capo', 0), track.get('max_fret', 29)):
            for spec in score['patterns'].values():
                for beat in spec['beats']:
                    if beat['track'] == identity:
                        _repair_fingering(score, beat)
    elif op == 'track_delete':
        _keys(edit, ('op', 'track', 'remove_notes'), op)
        identity = _id(edit.get('track'), 'track id')
        if identity not in score['tracks']:
            raise ValueError(f'unknown score track {identity}')
        remove = edit.get('remove_notes', False)
        if type(remove) is not bool:
            raise ValueError('track_delete remove_notes must be a boolean')
        used = any(b['track'] == identity for spec in score['patterns'].values() for b in spec['beats'])
        if used and not remove:
            raise ValueError('track contains score beats/rests; use remove_notes: true to remove them and their incident ties')
        for name, spec in score['patterns'].items():
            removed = [b for b in spec['beats'] if b['track'] == identity]
            if removed:
                _delete_incident_ties(result, name, {n['id'] for b in removed for n in b['notes']}, True)
                spec['beats'] = [b for b in spec['beats'] if b['track'] != identity]
        del score['tracks'][identity]
        for measure in score.get('measures', []):
            measure.get('staff', {}).pop(identity, None)
            if measure.get('staff') == {}:
                measure.pop('staff', None)
    elif op in ('measure_set', 'measure_delete'):
        _keys(edit, ('op', 'measure'), op)
        measure = copy.deepcopy(edit.get('measure'))
        if op == 'measure_set' and not isinstance(measure, dict):
            raise ValueError('measure_set requires a complete measure mapping')
        identity = _id(measure.get('id') if op == 'measure_set' else measure, 'measure id')
        measures = score.setdefault('measures', [])
        old = next((i for i, entry in enumerate(measures) if entry['id'] == identity), None)
        if op == 'measure_delete':
            if old is None:
                raise ValueError(f'unknown measure {identity}')
            measures.pop(old)
        elif old is None:
            measures.append(measure)
        else:
            measures[old] = measure
    elif op in ('tie_set', 'tie_delete'):
        _keys(edit, ('op', 'from', 'to'), op)
        source = edit.get('from')
        _keys(source, ('occurrence', 'note'), 'tie from')
        ties = score.setdefault('ties', [])
        old = next((i for i, tie in enumerate(ties) if tie['from'] == source), None)
        if op == 'tie_delete':
            if old is None or 'to' in edit and edit['to'] != ties[old]['to']:
                raise ValueError('tie_delete: no matching tie')
            ties.pop(old)
        else:
            target = edit.get('to')
            _keys(target, ('occurrence', 'note'), 'tie to')
            tie = {'from': copy.deepcopy(source), 'to': copy.deepcopy(target)}
            if old is None:
                ties.append(tie)
            else:
                ties[old] = tie
    elif op in ('beat_set', 'beat_delete', 'note_set', 'note_delete'):
        _keys(edit, ('op', 'pattern', 'beat', 'note', 'row_step', 'remove_ties'), op)
        if 'remove_ties' in edit and (op not in ('beat_delete', 'note_delete') or type(edit['remove_ties']) is not bool):
            raise ValueError('remove_ties must be a boolean on note_delete or beat_delete')
        name = edit.get('pattern')
        if not isinstance(name, str) or name not in _pattern_names(result):
            raise ValueError(f'unknown pattern {name}')
        if op == 'beat_set':
            beat = copy.deepcopy(edit.get('beat'))
            if not isinstance(beat, dict):
                raise ValueError('beat_set requires a complete beat mapping')
            identity = _id(beat.get('id'), 'beat id')
            spec = score['patterns'].setdefault(name, {'row_step': edit.get('row_step',
                _pair(Fraction(result.get('module', {}).get('speed', 6), 24))), 'beats': []})
            if 'row_step' in edit and spec['row_step'] != edit['row_step']:
                raise ValueError('beat_set cannot change an existing timing grid')
            old = next((i for i, b in enumerate(spec['beats']) if b['id'] == identity), None)
            previous_beat = spec['beats'][old] if old is not None else None
            if previous_beat and previous_beat['notes'] and (
                    is_percussion(_track(score, previous_beat)) != is_percussion(_track(score, beat))):
                raise ValueError('populated pitched/percussion beat conversion is unsupported')
            _beat_strokes(beat)
            _validate_chord(beat.get('chord'), _track(score, beat))
            shared = _cohort_strokes(spec['beats'])
            target_key = _cohort_key(beat)
            previous_key = _cohort_key(previous_beat) if previous_beat else target_key
            if previous_key[:2] != target_key[:2]:
                # A temporal move joins the destination beat, never a source-local rank.
                destination = [b for b in spec['beats'] if b['id'] != identity and
                               _cohort_key(b)[:2] == target_key[:2]]
                ranks = {b.get('cohort', 0) for b in destination}
                if len(ranks) > 1:
                    raise ValueError('moving beat has multiple distinct destination cohorts')
                beat.pop('cohort', None)
                if ranks and next(iter(ranks)):
                    beat['cohort'] = next(iter(ranks))
                target_key = _cohort_key(beat)
            inherited = shared.get(previous_key, {})
            metadata = tuple(beat.get(key, inherited.get(key)) for key in ('stroke', 'pick_stroke'))
            cohort = [b for b in spec['beats'] if b['id'] != identity and _cohort_key(b) == target_key]
            moving = previous_beat is not None and (
                previous_beat['track'] != beat.get('track') or
                _fraction(previous_beat['at'], 'beat at') != _fraction(beat.get('at'), 'beat at'))
            target_metadata = tuple(shared.get(target_key, {}).get(key) for key in ('stroke', 'pick_stroke'))
            if moving and cohort and target_metadata != metadata:
                raise ValueError('moving beat has conflicting stroke/pick_stroke at the destination cohort')
            source_others = [b for b in spec['beats'] if b['id'] != identity and
                             _cohort_key(b) == previous_key]
            chord = beat.get('chord', inherited.get('chord'))
            if moving:
                transfer = not any(b['notes'] for b in source_others)
                if not transfer:
                    chord = None
                target_chord = shared.get(target_key, {}).get('chord')
                if chord is not None and target_chord is not None and chord != target_chord:
                    raise ValueError('moving beat has conflicting chord at the destination cohort')
                for member in source_others:
                    if transfer or inherited.get('chord') is None:
                        member.pop('chord', None)
                    else:
                        member['chord'] = copy.deepcopy(inherited['chord'])
                if chord is None:
                    chord = target_chord
            for member in [beat, *cohort]:
                if chord is None:
                    member.pop('chord', None)
                else:
                    member['chord'] = copy.deepcopy(chord)
                for key, value in zip(('stroke', 'pick_stroke'), metadata):
                    if value is None:
                        member.pop(key, None)
                    else:
                        member[key] = copy.deepcopy(value)
            if old is None:
                spec['beats'].append(beat)
            else:
                spec['beats'][old] = beat
        else:
            beat = _beat(score, name, edit.get('beat'))
            if op == 'beat_delete':
                _delete_incident_ties(result, name, {n['id'] for n in beat['notes']}, edit.get('remove_ties', False))
                shared = _cohort_strokes(score['patterns'][name]['beats'])
                key = _cohort_key(beat)
                chord = shared[key].get('chord')
                if chord is not None:
                    for member in score['patterns'][name]['beats']:
                        if _cohort_key(member) == key:
                            member['chord'] = copy.deepcopy(chord)
                score['patterns'][name]['beats'].remove(beat)
            elif op == 'note_delete':
                nid = edit.get('note')
                note = next((n for n in beat['notes'] if n['id'] == nid), None)
                if note is None:
                    raise ValueError(f'unknown note {nid}')
                _delete_incident_ties(result, name, {nid}, edit.get('remove_ties', False))
                beat['notes'].remove(note)
            else:
                patch = edit.get('note')
                if not isinstance(patch, dict):
                    raise ValueError('note_set requires a note mapping')
                nid = _id(patch.get('id'), 'note id')
                note = next((n for n in beat['notes'] if n['id'] == nid), None)
                if note is None:
                    note = {'id': nid}
                    beat['notes'].append(note)
                old_pitch = note.get('pitch')
                if patch.get('staccato') is True and patch.get('palm_mute') is True:
                    raise ValueError('choose staccato or palm_mute, not both in one note edit')
                if patch.get('let_ring') is True and (patch.get('staccato') is True or patch.get('palm_mute') is True):
                    raise ValueError('choose let_ring or staccato/palm_mute, not both in one note edit')
                for key in ('bend', 'tremolo_bar', 'trill', 'tremolo_picking'):
                    if patch.get(key) is not None and not isinstance(patch[key], dict):
                        raise ValueError(f'{key} must be a mapping or null')
                repetitions = [k for k in ('trill', 'tremolo_picking') if patch.get(k) is not None]
                repetition_conflicts = ([k for k in ('bend', 'tremolo_bar') if patch.get(k) is not None] +
                                        [k for k in ('dead', 'slide', 'hammer', 'vibrato') if patch.get(k) is True])
                if repetitions and (len(repetitions) > 1 or repetition_conflicts):
                    raise ValueError('choose one repetition or conflicting effect change at a time')
                pitched = [k for k in ('bend', 'tremolo_bar') if patch.get(k) is not None and
                           (k == 'tremolo_bar' or patch[k].get('points'))]
                exclusive = pitched + [k for k in ('dead', 'slide', 'hammer') if patch.get(k) is True]
                if len(exclusive) > 1:
                    raise ValueError('choose one bend, tremolo_bar, slide, dead-note or hammer change at a time')
                dynamics = [k for k in ('ghost', 'accent', 'heavy_accent') if patch.get(k) is True]
                if len(dynamics) > 1:
                    raise ValueError('choose one ghost, accent or heavy_accent change at a time')
                techniques = [k for k in ('tapping', 'slapping', 'popping') if patch.get(k) is True]
                if len(techniques) > 1:
                    raise ValueError('choose one tapping, slapping or popping change at a time')
                note.update(copy.deepcopy(patch))
                if 'velocity' in patch and patch['velocity'] is None:
                    note.pop('velocity', None)
                if 'harmonic' in patch and patch['harmonic'] is None:
                    note.pop('harmonic', None)
                if 'grace' in patch and patch['grace'] is None:
                    note.pop('grace', None)
                for key in ('trill', 'tremolo_picking'):
                    if key in patch and patch[key] is None:
                        note.pop(key, None)
                if repetitions:
                    for key in ('trill', 'tremolo_picking', 'bend', 'tremolo_bar',
                                'dead', 'slide', 'hammer', 'vibrato'):
                        if key != repetitions[0]:
                            note.pop(key, None)
                elif repetition_conflicts:
                    note.pop('trill', None)
                    note.pop('tremolo_picking', None)
                if patch.get('staccato') is True:
                    note.pop('palm_mute', None)
                    note.pop('let_ring', None)
                elif patch.get('palm_mute') is True:
                    note.pop('staccato', None)
                    note.pop('let_ring', None)
                elif patch.get('let_ring') is True:
                    note.pop('staccato', None)
                    note.pop('palm_mute', None)
                if exclusive:
                    for key in ('bend', 'tremolo_bar', 'dead', 'slide', 'hammer'):
                        if key != exclusive[0]:
                            note.pop(key, None)
                if dynamics:
                    for key in ('ghost', 'accent', 'heavy_accent'):
                        if key != dynamics[0]:
                            note.pop(key, None)
                if techniques:
                    for key in ('tapping', 'slapping', 'popping'):
                        if key != techniques[0]:
                            note.pop(key, None)
                track = _track(score, beat)
                if ('string' in patch or 'fret' in patch) and note.get('string') is not None and note.get('fret') is not None:
                    string = _int(note['string'], 1, len(track['tuning']), 'note string')
                    fret = _int(note['fret'], 1 if is_percussion(track) else 0,
                                100 if is_percussion(track) else track.get('max_fret', 29), 'note fret')
                    pitch = track['tuning'][string - 1] + track.get('capo', 0) + fret
                    if 'pitch' not in patch:
                        note['pitch'] = pitch
                    elif pitch != note['pitch']:
                        raise ValueError('note_set: pitch conflicts with requested fingering')
                elif 'pitch' in patch:
                    _repair_fingering(score, beat)
                if note.get('pitch') != old_pitch and 'spelling' not in patch:
                    note.pop('spelling', None)
    else:
        raise ValueError(f'unsupported score edit {op}')
    _clear_removed_chords(song, result)
    validate_score(result)
    if op == 'beat_set':
        # Text, stem, timing and dynamics edits must not materialize implicit
        # fingering. Only changed note geometry or track needs repair.
        if (previous_beat is None or previous_beat['track'] != beat['track'] or
                [[n.get(k) for k in ('id', 'pitch', 'string', 'fret')] for n in previous_beat['notes']] !=
                [[n.get(k) for k in ('id', 'pitch', 'string', 'fret')] for n in beat['notes']]):
            _repair_fingering(score, beat)
    return result


def _delete_incident_ties(song, pattern, note_ids, remove):
    score = song['score']
    occurrences = {oid for oid, name in zip(score['order_ids'], song['orders']) if str(name) == pattern}
    incident = [tie for tie in score.get('ties', []) if any(
        endpoint['occurrence'] in occurrences and endpoint['note'] in note_ids for endpoint in tie.values())]
    if incident and not remove:
        raise ValueError('cannot delete a tied note/beat: use tie_delete first or remove_ties: true '
                         'to remove its incident ties; surviving continuations will become attacks')
    if incident:
        score['ties'] = [tie for tie in score['ties'] if tie not in incident]


def transform_native_selections(song, raw_patterns, edit):
    """Transform source attacks in inclusive row spans, including fractional starts.

    Each selection is {pattern: index, r0, r1, cols: [[channel, fields]]};
    fields are note/instrument/volume/effect. Reused patterns change once in all
    occurrences. Optional notes lists exact local note IDs and excludes raw
    cells (for a fractional cursor target). This returns the same score/residual
    pair as cell translation.
    """
    import math
    import random
    action = edit.get('action')
    if action == 'paste':
        return paste_native_clipboard(song, raw_patterns, edit)
    if action not in ('transpose', 'clear', 'cut', 'volume', 'amplify', 'humanize'):
        raise ValueError('native selection supports transpose, clear/cut, volume, amplify and humanize')
    fields = ('note', 'instrument', 'volume', 'effect')
    if action == 'transpose':
        amount = _int(edit.get('semitones'), -119, 119, 'semitones')
    elif action == 'volume':
        amount = _int(edit.get('volume'), 0, 64, 'volume')
    elif action == 'amplify':
        amount = edit.get('percent', 100)
        if type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0:
            raise ValueError('percent must be a finite nonnegative number')
    elif action == 'humanize':
        amount = _int(edit.get('amount', 6), 1, 32, 'humanize amount')
    rng = random.Random(_int(edit.get('seed', 1), 0, 2147483647, 'seed'))
    only = edit.get('instrument')
    if only is not None:
        _int(only, 1, 255, 'instrument filter')
    selections = edit.get('selections')
    if not isinstance(selections, list) or not selections:
        raise ValueError('selections must be a nonempty list')
    result, raw = copy.deepcopy(song), copy.deepcopy(raw_patterns)
    scopes, selected = {}, {}
    for selection in selections:
        pi = _int(selection.get('pattern'), 0, len(raw) - 1, 'pattern index')
        if pi in scopes:
            raise ValueError('select each pattern only once')
        pattern = raw[pi]
        r0 = _int(selection.get('r0', 0), 0, len(pattern.rows) - 1, 'r0')
        r1 = _int(selection.get('r1', len(pattern.rows) - 1), r0, len(pattern.rows) - 1, 'r1')
        cols = selection.get('cols')
        if not isinstance(cols, list) or not cols:
            raise ValueError('cols must select channels and fields')
        columns = {}
        for ch, fs in cols:
            _int(ch, 0, _channels(song) - 1, 'channel')
            if ch in columns or not isinstance(fs, list) or not fs or any(f not in fields for f in fs):
                raise ValueError('cols requires unique channels and nonempty named fields')
            columns[ch] = set(fs)
        occurrence = selection.get('occurrence')
        if occurrence is not None and not any(
                oid == occurrence and str(name) == pattern.name
                for oid, name in zip(song['score']['order_ids'], song['orders'])):
            raise ValueError('selection occurrence does not name this pattern')
        spec = result['score']['patterns'].get(pattern.name)
        targets = selection.get('notes')
        if targets is not None:
            known = {n['id'] for b in (spec or {}).get('beats', []) for n in b['notes']}
            if (not isinstance(targets, list) or not targets or
                    any(not isinstance(n, str) or n not in known for n in targets) or len(set(targets)) != len(targets)):
                raise ValueError('notes must list unique existing local note IDs')
        scopes[pi] = r0, r1, columns, targets
        if spec is None:
            continue
        if 'all_heads' in selection and type(selection['all_heads']) is not bool:
            raise ValueError('all_heads must be boolean')
        step = _fraction(spec['row_step'], 'row_step', True)
        if targets is None and not selection.get('all_heads'):
            addressed = set()
            for beat in spec['beats']:
                at = _fraction(beat['at'], 'beat at') / step
                if not r0 <= at < r1 + 1:
                    continue
                for note in _resolved_notes(result['score'], beat):
                    if not columns.get(note['channel'], set()) & {'note', 'instrument', 'volume'}:
                        continue
                    address = at, note['channel']
                    if address in addressed:
                        raise ValueError('multiple source heads: select exact notes or an explicit all_heads range')
                    addressed.add(address)
        for beat in spec['beats']:
            row = _fraction(beat['at'], 'beat at') / step
            if not r0 <= row < r1 + 1:
                continue
            for note, resolved in zip(beat['notes'], _resolved_notes(result['score'], beat)):
                if targets is not None and note['id'] not in targets:
                    continue
                fs = columns.get(resolved['channel'], set())
                if (action == 'transpose' and 'note' in fs and
                        (only is None or note.get('instrument', _track(result['score'], beat)['instrument']) == only)
                        or action in ('clear', 'cut') and fs
                        or action in ('volume', 'amplify') and 'volume' in fs
                        or action == 'humanize' and fs & {'volume', 'note'}):
                    selected[pattern.name, note['id']] = pi, beat, note, resolved, row, fs

    if action == 'transpose' and amount and any(is_percussion(_track(result['score'], b))
                                               for _, b, _, _, _, _ in selected.values()):
        raise ValueError('percussion musical transpose is unsupported; edit a drum key explicitly')
    # A source selection cannot quietly change notes outside its scope or detach
    # a surviving tied continuation. Whole chains are transformed in one batch.
    occurrence_names = dict(zip(song['score']['order_ids'], map(str, song['orders'])))
    removed = {key for key, value in selected.items()
               if action in ('clear', 'cut') and 'note' in value[-1]}
    changed_pitch = set(selected) if action in ('transpose', 'volume', 'amplify', 'humanize') else {
        key for key, value in selected.items() if value[-1] & {'note', 'instrument', 'volume'}}
    ties = []
    chains = {}
    for tie in result['score'].get('ties', []):
        ends = [(occurrence_names[tie[side]['occurrence']], tie[side]['note']) for side in ('from', 'to')]
        chain = chains.get(ends[0], {ends[0]}) | chains.get(ends[1], {ends[1]})
        for key in chain:
            chains[key] = chain
        if any(key in changed_pitch for key in ends) and not all(key in changed_pitch for key in ends):
            raise ValueError('selection crosses a tie: include the complete tied chain')
        if not all(key in removed for key in ends):
            ties.append(tie)
    if removed:
        result['score']['ties'] = ties

    offsets = {}

    def volume(value, key=None):
        if action == 'volume':
            return amount
        if action == 'amplify':
            return math.floor(min(64, value * (amount / 100)) + .5)
        if key is not None:
            key = min(chains.get(key, {key}))
        if key is None or key not in offsets:
            delta = math.floor(rng.uniform(-amount, amount) + .5)
            if key is not None:
                offsets[key] = delta
        else:
            delta = offsets[key]
        return max(1, min(64, value + delta))

    # Transform actual residual cells, never the generated display/release cells.
    for pi, (r0, r1, columns, targets) in scopes.items():
        if targets is not None:
            continue
        for row in range(r0, r1 + 1):
            for ch, fs in columns.items():
                cell = raw[pi].rows[row][ch]
                pitched = cell.note is not None and 0 <= cell.note <= 119
                if action == 'transpose' and 'note' in fs and pitched and (only is None or cell.instrument == only):
                    if amount and any(is_percussion(t) and ch in t['channels']
                                      for t in result['score']['tracks'].values()):
                        raise ValueError('percussion musical transpose is unsupported; edit a drum key explicitly')
                    cell.note = max(0, min(119, cell.note + amount))
                elif action in ('clear', 'cut'):
                    for field in fs:
                        if field == 'effect':
                            cell.effect = cell.param = 0
                        else:
                            setattr(cell, {'volume': 'volcmd'}.get(field, field), 0 if field == 'instrument' else None)
                elif ((action in ('volume', 'amplify') and 'volume' in fs or
                       action == 'humanize' and fs & {'note', 'volume'} and pitched)
                      and (cell.volcmd is not None and 0 <= cell.volcmd <= 64 or pitched and cell.volcmd is None)):
                    cell.volcmd = volume(64 if cell.volcmd is None else cell.volcmd)
    for key, (pi, beat, note, resolved, row, fs) in selected.items():
        if key in removed:
            beat['notes'].remove(note)
        elif action == 'transpose':
            pitch = max(0, min(119, note['pitch'] + amount))
            if pitch == note['pitch']:
                continue
            if resolved['string'] is not None:
                track = _track(result['score'], beat)
                fret = pitch - track['tuning'][resolved['string'] - 1] - track.get('capo', 0)
                if not 0 <= fret <= track.get('max_fret', 29):
                    raise ValueError('transpose exceeds the selected string: choose new fingering explicitly')
                note.update(string=resolved['string'], fret=fret)
            note['pitch'] = pitch
            note.pop('spelling', None)
        elif action in ('clear', 'cut'):
            if 'instrument' in fs:
                note['instrument'] = 0
            if 'volume' in fs:
                note.pop('volume', None)
        elif action in ('volume', 'amplify', 'humanize'):
            # An aligned raw v command keeps its existing source ownership.
            if row.denominator == 1:
                original = raw_patterns[pi].rows[int(row)][resolved['channel']]
                if original.volcmd is not None:
                    if scopes[pi][-1] is not None:
                        raise ValueError('this attack uses a raw volume command; select its volume column')
                    if action == 'humanize' and original.note is None and 0 <= original.volcmd <= 64:
                        raw[pi].rows[int(row)][resolved['channel']].volcmd = volume(original.volcmd, key)
                    continue
            note['volume'] = volume(note.get('volume', 64), key)
    _clear_removed_chords(song, result)
    checked = authoring_view(result, raw)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    groups = [(pi, [dict(row=r, ch=c, cell=format_cell(cell))
                    for r, row in enumerate(raw[pi].rows) for c, cell in enumerate(row)
                    if cell != raw_patterns[pi].rows[r][c]]) for pi in scopes]
    return (result['score'] if result['score'] != song['score'] else None), groups


def translate_native_pattern_edits(song, raw_patterns, groups, *, occurrences=None, view=None):
    """Translate displayed aligned fields without constructing an IT Projection.

    groups is [(pattern_index, [{row,ch,cell}, ...])]. occurrences maps indices to
    played occurrence IDs; omitted indices infer context only for a single use.
    Cell strings are compared to pattern_authoring_view.display_rows. Bound
    attacks update/delete their source note; untouched bound fields are restored
    to raw values before returning residual groups. Releases and inferred moves
    refuse: callers must use explicit musical operations. All changes are checked
    together against the exact authoring timeline, without mutating any input.
    Returns (changed_score_or_None, residual_groups). view, if given, must describe
    the same song/raw snapshot as in pattern_authoring_view.
    """
    if occurrences is not None and not isinstance(occurrences, dict):
        raise ValueError('native Pattern occurrences must map pattern indices to occurrence IDs')
    contexts = occurrences or {}
    view = authoring_view(song, raw_patterns) if view is None else view
    result, candidate_raw = copy.deepcopy(song), copy.deepcopy(raw_patterns)
    snapshots, changes = {}, {}
    for pi, cells in groups:
        _int(pi, 0, len(raw_patterns) - 1, 'pattern index')
        if pi not in snapshots:
            if pi in contexts:
                occurrence = contexts[pi]
            else:
                uses = [oid for oid, name in zip(song['score']['order_ids'], song['orders'])
                        if str(name) == raw_patterns[pi].name]
                if len(uses) != 1:
                    raise ValueError(f'{raw_patterns[pi].name}: an explicit occurrence is required for '
                                     'repeated or unplayed patterns')
                occurrence = uses[0]
            snapshot = pattern_authoring_view(song, raw_patterns, pi, occurrence, view=view)
            snapshots[pi] = snapshot, {(b['row'], b['ch'], b['field']): b for b in snapshot['bindings']}
        snapshot, bindings = snapshots[pi]
        for change in cells:
            row = _int(change.get('row'), 0, len(raw_patterns[pi].rows) - 1, 'row')
            ch = _int(change.get('ch'), 0, len(raw_patterns[pi].rows[row]) - 1, 'channel')
            address = pi, row, ch
            if address in changes:
                raise ValueError('duplicate cell edits must be combined before score translation')
            changes[address] = (parse_cell(snapshot['display_rows'][row][ch]), parse_cell(change.get('cell', '')))
            old, new = changes[address]
            if (any(c['row'] == row and c['ch'] == ch for c in snapshot['collisions']) and
                    any(getattr(old, field) != getattr(new, field) for field in ('note', 'instrument', 'volcmd'))):
                raise ValueError('multiple source owners: choose a source note or an explicit all_heads range; cell edit refused')

    deleting, inserting = False, False
    for (pi, row, ch), (old, new) in changes.items():
        owner = snapshots[pi][1].get((row, ch, 'note'))
        deleting |= bool(owner and owner['role'] == 'attack' and new.note is None)
        inserting |= bool(not owner and new.note is not None and 0 <= new.note <= 119 and new.note != old.note)
    if deleting and inserting:
        raise ValueError('ambiguous score-note deletion with raw-note insertion: use an explicit note_move; '
                         'mixed Pattern cut/paste is unsupported')

    patches, deleted = {}, set()
    output = {}
    for (pi, row, ch), (old, new) in changes.items():
        raw = raw_patterns[pi].rows[row][ch]
        for field in ('note', 'instrument', 'volcmd'):
            owner = snapshots[pi][1].get((row, ch, field))
            if owner is None:
                continue
            value = getattr(new, field)
            if value != getattr(old, field):
                if owner['role'] == 'release':
                    raise ValueError('generated release: use an explicit score duration/tie edit; '
                                     'partial chord duration and cell release moves are unsupported')
                key = owner['pattern'], owner['beat'], owner['note']
                if key in deleted:
                    pass  # Clearing the complete displayed attack deletes the note, including owned volume.
                elif field == 'note' and value is None:
                    deleted.add(key)
                elif field == 'note' and not 0 <= value <= 119:
                    raise ValueError('replace a score attack with a rest using note_delete')
                elif field == 'volcmd' and (value is None or not 0 <= value <= 64):
                    raise ValueError('score volume must be v00..v64; use a score edit to change its ownership')
                else:
                    patches.setdefault(key, {'id': owner['note']})[
                        {'note': 'pitch', 'instrument': 'instrument', 'volcmd': 'volume'}[field]] = value
            setattr(new, field, getattr(raw, field))
        if new != raw:
            output.setdefault(pi, []).append(dict(row=row, ch=ch, cell=format_cell(new)))
            candidate_raw[pi].rows[row][ch] = new
    for name, bid, nid in sorted(deleted):
        result = apply_score_edit(result, dict(op='note_delete', pattern=name, beat=bid, note=nid))
    for key, patch in patches.items():
        if key not in deleted:
            name, bid, _ = key
            result = apply_score_edit(result, dict(op='note_set', pattern=name, beat=bid, note=patch))
    checked = authoring_view(result, candidate_raw)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    residual = list(output.items())
    return (result['score'] if result['score'] != song['score'] else None), residual


def translate_pattern_edits(song, projection, groups):
    """Return (new_score_or_None, residual_groups), preserving source formatting.

groups is [(compiled_pattern_index, [{row, ch, cell: text}, ...]), ...]. Owned
    attack pitch/instrument/volume fields update their event. Unowned fields remain
    ordinary tracker edits. Removing an owned attack deletes that note. A complete
    batch moving every release of one chord resizes its written beat atomically.
    Other generated-release changes require a score duration edit. New unowned attacks remain raw
tracker events (no invented written duration). The caller must project/compile
the combined candidate before persisting it.
"""
    result, residual = copy.deepcopy(song), []
    groups = [(pi, [dict(c) for c in cells]) for pi, cells in groups]
    result, moved_releases = _release_moves(result, projection, groups)
    seen = set()
    for pi, cells in groups:
        _int(pi, 0, len(projection.patterns) - 1, 'pattern index')
        output = []
        pattern = projection.patterns[pi]
        for change in cells:
            row = _int(change.get('row'), 0, len(pattern.rows) - 1, 'row')
            ch = _int(change.get('ch'), 0, len(pattern.rows[row]) - 1, 'channel')
            if (pi, row, ch) in seen:
                raise ValueError('duplicate cell edits must be combined before score translation')
            seen.add((pi, row, ch))
            new, old = parse_cell(change.get('cell', '')), pattern.rows[row][ch]
            changed = {}
            deleted = set()
            for attribute in ('note', 'instrument', 'volcmd'):
                owner = projection.owners.get((pi, row, ch, attribute))
                if owner is None:
                    continue
                value = getattr(new, attribute)
                if value != getattr(old, attribute):
                    if owner['role'] == 'release':
                        if (pi, row, ch) in moved_releases:
                            setattr(new, attribute, None)
                            continue
                        raise ValueError('generated note-off: edit the score duration/tie instead')
                    key = (owner['pattern'], owner['beat'], owner['note'])
                    if attribute == 'note' and value is None:
                        deleted.add(key)
                    elif attribute == 'note' and not 0 <= value <= 119:
                        raise ValueError('replace a score attack with a rest using note_delete')
                    elif attribute == 'volcmd' and (value is None or not 0 <= value <= 64):
                        raise ValueError('score volume must be v00..v64; other commands belong to residual fields')
                    else:
                        changed.setdefault(key, {'id': owner['note']})[{'note': 'pitch', 'instrument': 'instrument', 'volcmd': 'volume'}[attribute]] = value
                setattr(new, attribute, None if attribute in ('note', 'volcmd') else 0)
            if (pi, row, ch) in moved_releases:
                new.note = None
            for name, bid, nid in deleted:
                result = apply_score_edit(result, dict(op='note_delete', pattern=name, beat=bid, note=nid))
            for key, patch in changed.items():
                if key not in deleted:
                    name, bid, _ = key
                    result = apply_score_edit(result, dict(op='note_set', pattern=name, beat=bid, note=patch))
            if new != projection.raw_patterns[pi].rows[row][ch]:
                output.append(dict(row=row, ch=ch, cell=format_cell(new)))
        if output:
            residual.append((pi, output))
    return result.get('score'), residual


def resize_beat(song, projection, pattern, beat_id, end_row):
    """Resize a complete untied chord/rest in one pattern, returning a candidate.

``projection`` needs only .patterns (a native backing Module is accepted).
``pattern`` is the pattern index; ``end_row`` is an integer or rational pair,
exclusive. The
smallest deterministic TuxGuitar written spelling is chosen; exact input never
rounds. Caller must compile the returned candidate before persistence.
"""
    _int(pattern, 0, len(projection.patterns) - 1, 'pattern index')
    end_row = _edit_row(end_row, len(projection.patterns[pattern].rows), 'end row', endpoint=True)
    name = projection.patterns[pattern].name
    beat = copy.deepcopy(_beat(song['score'], name, beat_id))
    nids = {n['id'] for n in beat['notes']}
    occurrences = {oid for oid, n in zip(song['score']['order_ids'], song['orders']) if str(n) == name}
    if any(endpoint['occurrence'] in occurrences and endpoint['note'] in nids
           for tie in song['score'].get('ties', []) for endpoint in tie.values()):
        raise ValueError('resizing a tied beat requires an explicit tie edit')
    step = _fraction(song['score']['patterns'][name]['row_step'], 'row_step', True)
    duration = end_row * step - _fraction(beat['at'], 'beat at')
    if duration <= 0:
        raise ValueError('end row must be after the beat attack')
    if duration != duration_quarters(beat['written']):
        beat['written'] = _written_for(duration)
        beat.pop('duration_source', None)
    return apply_score_edit(song, {'op': 'beat_set', 'pattern': name, 'beat': beat})


def _written_for(duration):
    divisions = ((1, 1), (3, 2), (5, 4), (6, 4), (7, 4), (9, 8), (10, 8), (11, 8), (12, 8), (13, 8))
    candidates = ({'value': v, 'dots': dots, 'tuplet': list(division)}
                  for division in divisions for dots in range(3) for v in (1, 2, 4, 8, 16, 32, 64))
    written = next((w for w in candidates if duration_quarters(w) == duration), None)
    if written is None:
        raise ValueError(f'duration {duration}: needs multiple tied written values; operation refused without rounding')
    return written


def promote_pattern(song, projection, pattern, track, cells=None, *, occurrence=None):
    """Explicitly adopt residual pitched attacks, returning (candidate, residual_groups).

``pattern`` is a compiled index, ``track`` an existing score track ID. ``cells``
optionally selects [{row,ch}, ...]; None selects every raw pitched attack on the
track's channels in that pattern. The returned candidate changes ONLY score;
install it and apply residual_groups through the existing raw-cell writer in one
transaction. Never persist the candidate without those residual removals.

Length is inferred from the next pitched attack or NOTE_OFF on the same channel,
within this pattern. Missing endings, cut/fade endings, unspellable durations,
more than two overlapping written voices and playback conflicts refuse the whole
operation. No final-pattern note-off is invented. Original instrument fields
(including zero/inheritance), volume/effects and automation are preserved. An
explicit note.channel decouples fingering from the original playback channel.
Every cell of the composed projection must equal the original before returning.

Native backing Modules use exact occurrence boundaries instead. Initial native
adoption requires an explicit raw NOTE_OFF ending: inserting a release before
the next attack could change NNA/continuation behavior. Unknown, cut/fade and
occurrence-dependent endings refuse. Native candidates are replanned, never projected.
"""
    _int(pattern, 0, len(projection.patterns) - 1, 'pattern index')
    validate_score(song)
    score = song.get('score', {})
    if not isinstance(track, str) or track not in score.get('tracks', {}):
        raise ValueError('promotion requires an existing score track; configure its tuning/channels first')
    native = getattr(projection, 'native_score', None)
    raw_patterns = projection.patterns if native is not None else projection.raw_patterns
    raw = raw_patterns[pattern]
    played = projection.patterns[pattern]
    previews = None
    if native is not None:
        uses = [o['id'] for o in native['view']['occurrences'] if o['pattern'] == raw.name]
        if occurrence is None:
            if len(uses) != 1:
                raise ValueError('native adoption requires an explicit played occurrence for a reused or unplayed pattern')
            occurrence = uses[0]
        if occurrence not in uses:
            raise ValueError('native adoption occurrence does not match the selected pattern')
        previews = native_raw_note_view(song, raw_patterns, view=native['view'])
    allowed = score['tracks'][track]['channels']
    if cells is None:
        selected = [(r, ch) for r, row in enumerate(raw.rows) for ch in allowed
                    if row[ch].note is not None and 0 <= row[ch].note <= 119]
    else:
        if not isinstance(cells, list) or len(cells) > 12800:
            raise ValueError('promotion cells must be a bounded list of {row,ch}')
        selected = []
        for cell in cells:
            _keys(cell, ('row', 'ch'), 'promotion cell')
            r = _int(cell.get('row'), 0, len(raw.rows) - 1, 'promotion row')
            ch = _int(cell.get('ch'), 0, len(raw.rows[r]) - 1, 'promotion channel')
            if ch not in allowed:
                raise ValueError('promotion channel does not belong to the selected track')
            selected.append((r, ch))
    if len(set(selected)) != len(selected):
        raise ValueError('promotion contains duplicate cells')
    if not selected:
        raise ValueError('no raw pitched attacks to promote on this track')
    result = copy.deepcopy(song)
    step = Fraction(_int(song.get('module', {}).get('speed', 6), 1, 255, 'module.speed'), 24)
    spec = result['score']['patterns'].setdefault(raw.name, {'row_step': _pair(step), 'beats': []})
    if _fraction(spec['row_step'], 'row_step', True) != step:
        raise ValueError('promotion cannot change the existing score timing grid')
    used_beats = {b['id'] for b in spec['beats']}
    used_notes = {n['id'] for b in spec['beats'] for n in b['notes']}
    staged_raw = copy.deepcopy(raw_patterns)
    changed, groups = set(), {}
    for row, ch in sorted(selected):
        source = raw.rows[row][ch]
        if (source.note is None or not 0 <= source.note <= 119 or
                native is None and (pattern, row, ch, 'note') in projection.owners):
            raise ValueError(f'row {row} channel {ch}: select a raw pitched attack, not a generated note or release')
        if native is not None:
            entries = [p for p in previews if p['pattern'] == pattern and p['row'] == row and p['ch'] == ch]
            chosen = next(p for p in entries if p['occurrence'] == occurrence)
            if any((p.get('end_row'), p.get('boundary')) != (chosen.get('end_row'), chosen.get('boundary'))
                   for p in entries):
                raise ValueError('raw note has occurrence-dependent boundaries; make the pattern unique before adoption')
            if chosen.get('boundary') != 'raw_note_off':
                raise ValueError('native adoption needs an explicit raw note-off; a next attack cannot preserve NNA release semantics')
            end = int(Fraction(*chosen['end_row']))
        else:
            end = next((r for r in range(row + 1, len(played.rows)) if played.rows[r][ch].note is not None), None)
        if end is None:
            raise ValueError(f'row {row} channel {ch}: unknown duration; add an explicit note-off before the pattern ends')
        ending = played.rows[end][ch].note
        if not (0 <= ending <= 119 or ending == NOTE_OFF):
            raise ValueError(f'row {row} channel {ch}: cut/fade ending cannot be promoted as a note-off')
        written = _written_for((end - row) * step)
        nid = _local_id(f'adopt_n_{row}_{ch}', used_notes)
        used_notes.add(nid)
        groups.setdefault((row, end), (written, []))[1].append(
            {'id': nid, 'pitch': source.note, 'instrument': source.instrument, 'channel': ch})
        staged_raw[pattern].rows[row][ch].note = None
        staged_raw[pattern].rows[row][ch].instrument = 0
        changed.add((row, ch))
        if raw.rows[end][ch].note == NOTE_OFF:
            staged_raw[pattern].rows[end][ch].note = None
            changed.add((end, ch))
    spans = {v: [(_fraction(b['at'], 'beat at'), _fraction(b['at'], 'beat at') + duration_quarters(b['written']))
                 for b in spec['beats'] if b['track'] == track and b.get('voice', 0) == v] for v in (0, 1)}
    for (row, end), (written, notes) in sorted(groups.items()):
        at, until = row * step, end * step
        voice = next((v for v in (0, 1) if not any(at < b and a < until for a, b in spans[v])), None)
        if voice is None:
            raise ValueError(f'row {row}: promotion needs more than two written voices; select a smaller part')
        bid = _local_id(f'adopt_b_{row}_{end}', used_beats)
        used_beats.add(bid)
        beat = {'id': bid, 'track': track, 'voice': voice, 'at': _pair(at), 'written': written,
                'notes': notes, 'duration_source': 'tracker_boundary'}
        _repair_fingering(result['score'], beat)
        spec['beats'].append(beat)
        spans[voice].append((at, until))
    if native is not None:
        repeated = repeat_projection(result, staged_raw, native['plan']['sample_rate'])
        after = repeated.plan if repeated is not None else playback_plan(result, staged_raw, native['plan']['sample_rate'])
        previous = {e['id']: [] for e in native['plan']['events']}
        for event in after['events']:
            if event['id'] in previous:
                previous[event['id']].append(event)
        for identity, events in previous.items():
            if events != [e for e in native['plan']['events'] if e['id'] == identity]:
                raise ValueError('adoption would change existing score playback; no source was adopted')
    else:
        after = project_score(result, staged_raw)
        if after.patterns != projection.patterns:
            raise ValueError('promotion would change projected tracker cells; no source was adopted')
    residual = [{'row': r, 'ch': ch, 'cell': format_cell(staged_raw[pattern].rows[r][ch])}
                for r, ch in sorted(changed) if staged_raw[pattern].rows[r][ch] != raw.rows[r][ch]]
    return result, [(pattern, residual)] if residual else []


def _local_id(base, used):
    result, suffix = base[:80], 2
    while result in used:
        tail = f'_{suffix}'
        result, suffix = base[:80 - len(tail)] + tail, suffix + 1
    return result


def _split_written(length):
    """Spell an exact edited span without quantizing its endpoints."""
    try:
        return [_written_for(length)]
    except ValueError:
        pass
    values = {}
    for division in ((1, 1), (3, 2), (5, 4), (6, 4), (7, 4), (9, 8),
                     (10, 8), (11, 8), (12, 8), (13, 8)):
        for dots in range(3):
            for value in (1, 2, 4, 8, 16, 32, 64):
                written = dict(value=value, dots=dots, tuplet=list(division))
                duration = duration_quarters(written)
                if length.denominator % duration.denominator == 0:
                    values.setdefault(duration, written)
    pieces = []
    while length:
        duration = next((d for d in sorted(values, reverse=True) if d <= length), None)
        if duration is None or len(pieces) >= 512:
            raise ValueError('edited boundary needs an unsupported written subdivision; no rounding applied')
        pieces.append(copy.deepcopy(values[duration]))
        length -= duration
    return pieces


def _place_measure_bounds(score, timeline, name, start, left, right):
    spans = {o['id']: (Fraction(*o['at']), Fraction(*o['duration'])) for o in timeline['occurrences']}
    measures = [(spans[m['from']['occurrence']][0] + Fraction(*m['from']['at']),
                 spans[m['to']['occurrence']][0] + Fraction(*m['to']['at']))
                for m in score.get('measures', [])]
    bounds = None
    for use in timeline['occurrences']:
        if use['pattern'] != name:
            continue
        origin, size = spans[use['id']]
        if not 0 <= left < right <= size:
            raise ValueError('place interval or affected rest crosses a pattern boundary')
        absolute = origin + start
        measure = next(((a, b) for a, b in measures if a <= absolute < b), None)
        if measure is None:
            cuts = sorted({origin, origin + size, *(x for m in measures for x in m if origin < x < origin + size)})
            measure = next(((a, b) for a, b in zip(cuts, cuts[1:]) if a <= absolute < b), None)
        local = (measure[0] - origin, measure[1] - origin) if measure else None
        if local is None or not local[0] <= left < right <= local[1]:
            raise ValueError('place interval or affected rest crosses a measure boundary')
        if bounds is not None and local != bounds:
            raise ValueError('place has different measure bounds in shared occurrences; make the pattern unique first')
        bounds = local
    return bounds


def _repair_duration_ties(score, timeline):
    """Keep adjacent edges; a gap introduced by a duration edit starts a new attack.

    TG's duration action leaves invalid tied-note flags until its explicit Fix
    tied note command. Native score cannot save such silent dangling links.
    Inspect the completed candidate, so Fit can move both ends together.
    """
    if not score.get('ties'):
        return []
    uses = {o['id']: (o['pattern'], Fraction(*o['at'])) for o in timeline['occurrences']}
    notes = {(name, n['id']): b for name, spec in score['patterns'].items()
             for b in spec['beats'] for n in b['notes']}
    kept, removed = [], []
    for tie in score['ties']:
        ends = []
        for side in ('from', 'to'):
            endpoint = tie[side]
            name, origin = uses[endpoint['occurrence']]
            beat = notes[name, endpoint['note']]
            ends.append(origin + Fraction(*beat['at']) +
                        (duration_quarters(beat['written']) if side == 'from' else 0))
        (kept if ends[0] == ends[1] else removed).append(tie)
    score['ties'] = kept
    return removed


def _place_score_beat(song, raw_patterns, edit, *, timeline=None):
    """Place at an exact caret, consuming bare rests without moving notes."""
    _keys(edit, ('action', 'occurrence', 'beat', 'revision'), 'place')
    timeline = timeline or _score_timeline(song, raw_patterns)
    score = song['score']
    occurrence = next((o for o in timeline['occurrences'] if o['id'] == edit.get('occurrence')), None)
    if occurrence is None:
        raise ValueError('place needs a played occurrence')
    placed = copy.deepcopy(edit.get('beat'))
    _keys(placed, ('id', 'track', 'voice', 'at', 'written', 'notes', 'duration_source',
                  'stem', 'text', 'stroke', 'pick_stroke', 'chord', 'cohort'), 'place beat')
    identity = _id(placed.get('id'), 'place beat id')
    _track(score, placed)
    track, voice = placed['track'], _int(placed.get('voice', 0), 0, 1, 'place voice')
    start = _fraction(placed.get('at'), 'place at')
    end = start + duration_quarters(placed.get('written'))
    if not isinstance(placed.get('notes'), list):
        raise ValueError('place notes must be a list')
    for note in placed['notes']:
        if not isinstance(note, dict):
            raise ValueError('place note must be a mapping')
        _id(note.get('id'), 'place note id')
    name = occurrence['pattern']
    beats = score['patterns'].get(name, {}).get('beats', [])
    previous = next((b for b in beats if b['id'] == identity), None)
    if previous is not None:
        if (previous['track'], previous.get('voice', 0), Fraction(*previous['at'])) != (track, voice, start):
            raise ValueError('place cannot relocate an existing beat ID')
        # This command resizes or appends one note, never deletes/revoices a chord.
        if placed['notes'][:len(previous['notes'])] != previous['notes'] or len(placed['notes']) > len(previous['notes']) + 1:
            raise ValueError('place must preserve existing notes and may append only one note')
        ignored = {'at', 'voice', 'written', 'notes', 'duration_source'}
        if {k: v for k, v in previous.items() if k not in ignored} != {
                k: v for k, v in placed.items() if k not in ignored}:
            raise ValueError('place must preserve existing beat metadata')
        old_end = start + duration_quarters(previous['written'])
        if placed.get('duration_source') != previous.get('duration_source') and not (
                old_end != end and 'duration_source' not in placed):
            raise ValueError('place cannot change duration provenance without resizing')
        if old_end != end:
            placed.pop('duration_source', None)
            nids = {n['id'] for n in previous['notes']}
            uses = {o['id'] for o in timeline['occurrences'] if o['pattern'] == name}
            if placed['notes'] != previous['notes'] and any(
                    e['occurrence'] in uses and e['note'] in nids
                    for tie in score.get('ties', []) for e in tie.values()):
                raise ValueError('place cannot append notes while resizing an incident tied beat')
    else:
        old_end = end
        if 'duration_source' in placed:
            raise ValueError('place cannot invent tracker duration provenance')

    active = [b for b in beats if b['track'] == track and b.get('voice', 0) == voice]
    touched = [b for b in active if b is not previous and
               Fraction(*b['at']) < end and start < Fraction(*b['at']) + duration_quarters(b['written'])]
    if any(b['notes'] for b in touched):
        blocker = next(b for b in touched if b['notes'])
        raise ValueError(f"place overlaps sounding beat {blocker['id']}; no note shifting")

    def annotated(beat):
        return (bool(beat.get('text')) or beat.get('stem', 'auto') != 'auto' or
                'duration_source' in beat or
                any(beat.get(k) is not None for k in ('chord', 'stroke', 'pick_stroke')))

    changed_rests = touched + ([previous] if previous is not None and not previous['notes'] else [])
    for rest in changed_rests:
        if annotated(rest):
            raise ValueError(f"place cannot restructure annotated rest {rest['id']}")
    # Rest subtraction must not transfer annotations belonging to a peer voice.
    changed_onsets = {start, *(Fraction(*b['at']) for b in touched)}
    for peer in beats:
        if peer is not previous and peer['track'] == track and Fraction(*peer['at']) in changed_onsets and annotated(peer):
            raise ValueError(f"place cannot restructure annotated cohort {peer['id']}")
    if annotated(placed) and previous is None:
        raise ValueError('place cannot add annotated beat metadata; use an explicit metadata edit')

    left = min([start, *(Fraction(*b['at']) for b in touched)])
    right = max([end, old_end, *(Fraction(*b['at']) + duration_quarters(b['written']) for b in touched)])
    _place_measure_bounds(score, timeline, name, start, left, right)

    candidate = copy.deepcopy(song)
    pattern = candidate['score']['patterns'].setdefault(name, dict(row_step=_pair(timeline['step']), beats=[]))
    affected = {b['id'] for b in touched}
    if previous is not None:
        affected.add(previous['id'])
    retained = [b for b in pattern['beats'] if b['id'] not in affected]
    used = {b['id'] for b in beats} | {identity}
    # Replacing the start of an existing rest retains its source identity.
    if previous is None:
        at_start = next((b for b in touched if Fraction(*b['at']) == start), None)
        if at_start is not None:
            placed['id'] = at_start['id']

    def rest_pieces(a, b, original=None, keep_id=False):
        if a >= b:
            return
        for i, written in enumerate(_split_written(b - a)):
            rest = copy.deepcopy(original) if original is not None else dict(track=track, voice=voice, notes=[])
            base = original['id'] if original is not None else placed['id']
            rest['id'] = base if keep_id and i == 0 else _local_id('rest_' + base, used)
            used.add(rest['id'])
            rest.update(at=_pair(a), written=written)
            rest.pop('duration_source', None)
            retained.append(rest)
            a += duration_quarters(written)

    for rest in touched:
        a, b = Fraction(*rest['at']), Fraction(*rest['at']) + duration_quarters(rest['written'])
        rest_pieces(a, min(start, b), rest, keep_id=True)
        rest_pieces(max(end, a), b, rest, keep_id=a >= start and rest['id'] != placed['id'])
    if previous is not None and old_end > end:
        rest_pieces(end, old_end)
    # Keep the old target for beat_set's metadata/fingering checks; all other
    # overlapping rests have already been removed in this unpublished candidate.
    if previous is not None:
        retained.append(copy.deepcopy(previous))
    pattern['beats'] = retained
    candidate = apply_score_edit(candidate, dict(op='beat_set', pattern=name, beat=placed))
    removed_ties = _repair_duration_ties(candidate['score'], timeline)
    actual = _beat(candidate['score'], name, placed['id'])
    if previous is not None and actual['notes'][:len(previous['notes'])] != previous['notes']:
        raise ValueError('place would change existing note fingering or metadata')
    unchanged = {b['id']: b for b in beats if b['id'] not in affected}
    after = {b['id']: b for b in candidate['score']['patterns'][name]['beats']}
    if any(after.get(identity) != original for identity, original in unchanged.items()):
        raise ValueError('place would change another beat or shared annotation')
    other_lanes = {n['string'] for b in beats if b['track'] == track and b.get('voice', 0) != voice
                   and Fraction(*b['at']) == start for n in _resolved_notes(score, b)}
    if any(n['string'] in other_lanes for n in _resolved_notes(candidate['score'], actual)):
        raise ValueError('place destination string is occupied by the other voice')
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    return candidate, dict(removed_ties=removed_ties,
                          selection=dict(occurrence=occurrence['id'], track=track, voice=voice,
                                         at=_pair(start), beats=[actual['id']],
                                         notes=[n['id'] for n in actual['notes']]))


def _fit_score_beat(song, raw_patterns, edit):
    """Opt-in rest shifts/rebuilds and the two qualified no-space outcomes."""
    _keys(edit, ('action', 'occurrence', 'beat', 'revision', 'fit'), 'place fit')
    mode = edit['fit']
    if mode not in ('tg_insert', 'tg_duration'):
        raise ValueError('place fit must be tg_insert or tg_duration')
    timeline = _score_timeline(song, raw_patterns)
    occurrence = next((o for o in timeline['occurrences'] if o['id'] == edit.get('occurrence')), None)
    if occurrence is None:
        raise ValueError('place fit needs a played occurrence')
    requested = copy.deepcopy(edit.get('beat'))
    if not isinstance(requested, dict):
        raise ValueError('place fit requires a complete beat mapping')
    name, score = occurrence['pattern'], song['score']
    previous = _beat(score, name, requested.get('id'))
    length = duration_quarters(requested.get('written'))
    old_length = duration_quarters(previous['written'])
    if mode == 'tg_duration' and requested.get('notes') != previous['notes']:
        raise ValueError('duration fit must keep the complete note list unchanged')
    if mode == 'tg_insert' and (not isinstance(requested.get('notes'), list) or
                               len(requested['notes']) != len(previous['notes']) + 1):
        raise ValueError('insertion fit must append exactly one note')
    exact_edit = {k: v for k, v in edit.items() if k != 'fit'}
    # Validate the same requested note/metadata at the old duration first. This
    # is also the sole fallback candidate, never a catch-all exception retry.
    base_edit = copy.deepcopy(exact_edit)
    base_edit['beat']['written'] = copy.deepcopy(previous['written'])
    if 'duration_source' in previous:
        base_edit['beat']['duration_source'] = previous['duration_source']
    baseline, base_result = _place_score_beat(song, raw_patterns, base_edit)

    def finish(candidate, result, outcome):
        actual = _beat(candidate['score'], name, previous['id'])
        result['fit'] = dict(requested=copy.deepcopy(requested['written']),
                             applied=copy.deepcopy(actual['written']), outcome=outcome)
        return candidate, result

    track, voice, start = previous['track'], previous.get('voice', 0), Fraction(*previous['at'])
    end = start + length
    bounds = _place_measure_bounds(score, timeline, name, start, start, max(end, start + old_length))
    if requested == previous:
        return finish(copy.deepcopy(song), base_result, 'unchanged')
    beats = score['patterns'][name]['beats']
    following = sorted((b for b in beats if b['track'] == track and b.get('voice', 0) == voice
                        and start < Fraction(*b['at']) < bounds[1]), key=lambda b: Fraction(*b['at']))
    blockers = [b for b in following if b['notes'] and Fraction(*b['at']) < end]
    if not blockers:
        candidate, result = _place_score_beat(song, raw_patterns, exact_edit)
        return finish(candidate, result, 'unchanged' if candidate == song else 'exact')

    # An omitted silence is the same available time as a bare written rest.
    # Materialize only this measure's exact gaps in the unpublished candidate;
    # a no-space outcome must still return the untouched original document.
    active = sorted((b for b in beats if b['track'] == track and b.get('voice', 0) == voice
                     and Fraction(*b['at']) < bounds[1] and bounds[0] <
                     Fraction(*b['at']) + duration_quarters(b['written'])), key=lambda b: Fraction(*b['at']))
    cursor, gaps = bounds[0], []
    for beat in active:
        at = Fraction(*beat['at'])
        if at > cursor:
            gaps.append((cursor, at))
        cursor = at + duration_quarters(beat['written'])
    if cursor < bounds[1]:
        gaps.append((cursor, bounds[1]))
    if gaps and mode == 'tg_duration':
        filled = copy.deepcopy(song)
        target = filled['score']['patterns'][name]['beats']
        used = {b['id'] for b in beats}
        for at, until in gaps:
            for written in _split_written(until - at):
                identity = _local_id('rest_' + previous['id'], used)
                used.add(identity)
                target.append(dict(id=identity, track=track, voice=voice, at=_pair(at), written=written, notes=[]))
                at += duration_quarters(written)
        candidate, result = _fit_score_beat(filled, raw_patterns, edit)
        if result['fit']['outcome'] == 'unchanged':
            return finish(copy.deepcopy(song), base_result, 'unchanged')
        if result['fit']['outcome'] == 'old_duration':
            return finish(baseline, base_result, 'old_duration')
        return candidate, result

    # The movement algorithm below now sees an exact active-voice partition.
    cursor = start + old_length
    for beat in following:
        if Fraction(*beat['at']) != cursor:
            raise ValueError('place fit needs continuous explicit active-voice coverage')
        cursor += duration_quarters(beat['written'])
    if cursor != bounds[1]:
        raise ValueError('place fit needs continuous explicit active-voice coverage through measure end')
    debt = end - Fraction(*following[0]['at'])
    moved, consumed, inspected = {}, set(), [previous]
    partial = False
    for beat in following:
        if debt <= 0:
            break
        inspected.append(beat)
        if beat['notes']:
            moved[beat['id']] = Fraction(*beat['at']) + debt
        else:
            debt -= duration_quarters(beat['written'])
            consumed.add(beat['id'])
            partial = debt < 0
    if debt > 0 and mode == 'tg_duration':
        return finish(copy.deepcopy(song), base_result, 'unchanged')

    peers = []
    if partial:
        measure_beats = [b for b in beats if b['track'] == track and
                         Fraction(*b['at']) < bounds[1] and bounds[0] <
                         Fraction(*b['at']) + duration_quarters(b['written'])]
        measure_beats.sort(key=lambda b: Fraction(*b['at']))
        peers = sorted((b for b in measure_beats if b.get('voice', 0) != voice),
                       key=lambda b: Fraction(*b['at']))
        active = [b for b in measure_beats if b.get('voice', 0) == voice]
        cursor = bounds[0]
        for beat in active:
            if Fraction(*beat['at']) != cursor:
                raise ValueError('partial rest fit needs ordered explicit coverage of the whole measure')
            cursor += duration_quarters(beat['written'])
        if cursor != bounds[1]:
            raise ValueError('partial rest fit needs ordered explicit coverage of the whole measure')
        if any(b['notes'] and Fraction(*b['at']) in moved.values() for b in active):
            raise ValueError('partial rest fit cannot replace a sounding move destination')
        # TG's shift loop removes *all* later rests, including after the debt
        # becomes negative. Every later note may also move during realignment.
        inspected = [previous, *following, *peers]
        consumed.update(b['id'] for b in following if not b['notes'])

    uses = {o['id'] for o in timeline['occurrences'] if o['pattern'] == name}
    nids = {n['id'] for b in inspected for n in b['notes']}
    if mode != 'tg_duration' and any(e['occurrence'] in uses and e['note'] in nids
           for tie in score.get('ties', []) for e in tie.values()):
        raise ValueError('place fit cannot move or resize incident tied notes')
    onsets = {Fraction(*b['at']) for b in inspected} | set(moved.values())
    cohorts = [b for b in beats if b['track'] == track and Fraction(*b['at']) in onsets]
    consumed_groups = {_cohort_key(b) for b in beats if b['id'] in consumed}
    for beat in cohorts:
        annotated = beat.get('text') or any(beat.get(k) is not None for k in ('chord', 'stroke', 'pick_stroke'))
        if (beat.get('stem', 'auto') != 'auto' or 'duration_source' in beat or
                annotated and _cohort_key(beat) in consumed_groups):
            raise ValueError(f"place fit cannot restructure annotated cohort {beat['id']}")
    # Moving intact notes keeps their expression. The normal authoring check
    # below validates changed technique targets, gates and peer-voice ownership.
    if debt > 0:
        if mode == 'tg_duration':
            return finish(copy.deepcopy(song), base_result, 'unchanged')
        return finish(baseline, base_result, 'old_duration')

    shifted = copy.deepcopy(song)
    shifted_beats = shifted['score']['patterns'][name]['beats']
    shifted_beats[:] = [b for b in shifted_beats if b['id'] not in consumed]
    for beat in sorted(list(shifted_beats), key=lambda b: Fraction(*b['at']), reverse=True):
        if beat['id'] in moved:
            _move_voice_cohort(shifted_beats, beat, moved[beat['id']])
    # Voice moves can legitimately transfer shared annotations. Subsequent
    # rest rebuilding/repacking must preserve these resulting peer records.
    expected_peers = {b['id']: copy.deepcopy(b) for b in shifted_beats
                      if b['track'] == track and b.get('voice', 0) != voice} if partial else {}
    if partial:
        # New destination cohorts are appended by moveVoicePrecise. Retain
        # that order for tryChangeSilenceAfter's first-sounding-voice lookup.
        local = {b['id']: b for b in shifted_beats}
        stored = [local[b['id']] for b in measure_beats
                  if b['id'] not in consumed and b['id'] not in moved]
        for original in measure_beats:
            if original['id'] in moved:
                beat = local[original['id']]
                cohort = next((i for i, b in enumerate(stored) if b['at'] == beat['at']), len(stored))
                stored.insert(cohort, beat)
        next_start = next((Fraction(*b['at']) for b in stored
                           if b.get('voice', 0) == voice and Fraction(*b['at']) > start and b['notes']), bounds[1])
        fill = next_start - end
        if fill:
            # TG createSilences reuses an existing voice at each fill onset,
            # even a moved sounding voice. Reuse the importer's pinned exact
            # duration splitter; no separate approximate rhythm engine.
            from .midiimport import WHOLE, _split
            unit = Fraction(WHOLE, 4)
            remaining = fill % length
            precise, maximum = remaining * unit, (bounds[1] - bounds[0]) * unit
            if precise.denominator != 1 or maximum.denominator != 1:
                raise ValueError('partial rest fit needs exact supported written subdivisions')
            durations = _split(int(precise), int(maximum))
            if durations is None:
                precise = fill * unit
                durations = _split(int(precise), int(maximum)) if precise.denominator == 1 else None
                preferred = []
            else:
                preferred = [copy.deepcopy(requested['written']) for _ in range(fill // length)]
            if durations is None or len(durations) + len(preferred) > 512:
                raise ValueError('partial rest fit needs exact supported written subdivisions')
            written = preferred + [dict(value=v, dots=2 if double else int(dot), tuplet=[enters, times])
                                   for v, dot, double, enters, times in durations]
            cursor, used = end, {b['id'] for b in beats}
            for spelling in written:
                recipient = next((b for b in stored if b.get('voice', 0) == voice and Fraction(*b['at']) == cursor), None)
                if recipient is None:
                    recipient = dict(id=_local_id('rest_' + previous['id'], used), track=track, voice=voice,
                                     at=_pair(cursor), notes=[])
                    used.add(recipient['id'])
                    stored.append(recipient)
                    shifted_beats.append(recipient)
                recipient['written'] = spelling
                cursor += duration_quarters(spelling)
        local[previous['id']]['written'] = copy.deepcopy(requested['written'])
        if mode == 'tg_duration' and sum(duration_quarters(b['written']) for b in stored
                                        if b.get('voice', 0) == voice) != bounds[1] - bounds[0]:
            # changeDuration alone realigns an invalid measure after rebuilding.
            ends = {0: bounds[0], 1: bounds[0]}
            cohorts = _beat_cohorts(stored)
            for cohort in cohorts:
                at = max(ends[b.get('voice', 0)] for b in cohort)
                for beat in cohort:
                    beat['at'] = _pair(at)
                    ends[beat.get('voice', 0)] = at + duration_quarters(beat['written'])
            _stamp_cohorts(cohorts, keep_single=True)
    # All movement is installed together; the strict path places the target
    # and rechecks raw ownership, shared bounds and unchanged peer records.
    candidate, result = _place_score_beat(shifted, raw_patterns, exact_edit, timeline=timeline)
    final = candidate['score']['patterns'][name]['beats']
    if peers:
        final_peers = {b['id']: b for b in final if b['track'] == track and b.get('voice', 0) != voice}
        if final_peers != expected_peers:
            raise ValueError('partial rest fit would change a peer record')
    changed = set(moved) | ({b['id'] for b in inspected} if peers else set())
    for beat in final:
        if beat['id'] not in changed or beat.get('voice', 0) != voice:
            continue
        lanes = {n['string'] for n in _resolved_notes(candidate['score'], beat)}
        if any(lanes & {n['string'] for n in _resolved_notes(candidate['score'], peer)}
               for peer in final if peer['track'] == track and peer.get('voice', 0) != voice
               and Fraction(*peer['at']) == Fraction(*beat['at'])):
            raise ValueError('place fit moved string is occupied by the other voice')
    return finish(candidate, result, 'shifted')


def _set_duration_range(song, raw_patterns, edit):
    """TuxGuitar's SetDuration on a beat range (TGSetDurationAction, pinned 2c46e2a1): every selected beat of the
    selected track and voice takes the written duration, in time order, through the same Place (or its
    tg_duration fit) a single beat uses. One candidate: any refusal leaves the song unchanged."""
    _keys(edit, ('action', 'occurrence', 'track', 'voice', 'beats', 'selection', 'written', 'fit', 'free', 'revision'), 'set_duration')
    if 'free' in edit and type(edit['free']) is not bool:
        raise ValueError('set_duration free must be boolean')
    fit = edit.get('fit')
    if fit not in (None, 'tg_duration'):
        raise ValueError("set_duration fit must be 'tg_duration'")
    written = copy.deepcopy(edit.get('written'))
    length = duration_quarters(written)
    voice = _int(edit.get('voice', 0), 0, 1, 'selected voice')
    cross = 'selection' in edit
    if cross:
        _, timeline, records = _score_range(song, raw_patterns, edit)
        _unique_range(song, records)
    else:
        identities = edit.get('beats')
        if not isinstance(identities, list) or not 1 <= len(identities) <= 1024 or len(set(identities)) != len(identities):
            raise ValueError('set_duration selects 1..1024 distinct beats')
        timeline = _score_timeline(song, raw_patterns)
        own = next((o for o in timeline['occurrences'] if o['id'] == edit.get('occurrence')), None)
        if own is None:
            raise ValueError('set_duration needs a played occurrence')
        selected = [_beat(song['score'], own['pattern'], identity) for identity in identities]
        if any(b['track'] != edit.get('track') or b.get('voice', 0) != voice for b in selected):
            raise ValueError('set_duration beats must belong to the selected track and voice')
        records = [(own, b, Fraction(*own['at']) + Fraction(*b['at'])) for b in selected]
    active = sorted((r for r in records if r[1].get('voice', 0) == voice), key=lambda r: r[2])
    if not active:
        raise ValueError('duration range has no beats in the selected voice')
    if edit.get('free') is True:
        return _set_duration_free(song, raw_patterns, edit, timeline, active, records)
    candidate, outcomes, kept, consumed, removed_ties = song, [], [], [], []
    rebuilt_targets, automatic_patterns = set(), set()
    for own, original, _ in active:
        name = own['pattern']
        current = next((b for b in candidate['score']['patterns'][name]['beats'] if b['id'] == original['id']), None)
        if current is None:
            if original['notes']:
                raise ValueError('duration Fit would remove a selected sounding beat')
            consumed.append(dict(occurrence=own['id'], beat=original['id']))
            outcomes.append('consumed')
            continue
        if _automatic_free(candidate, raw_patterns, own['id'], edit['track'], Fraction(*current['at'])):
            now = next(o for o in timeline['occurrences'] if o['id'] == own['id'])
            target = [(now, current, Fraction(*now['at']) + Fraction(*current['at']))]
            candidate, result = _set_duration_free(candidate, raw_patterns, edit, timeline, target, target)
            size = candidate['patterns'][name]['rows'] * Fraction(*candidate['score']['patterns'][name]['row_step'])
            raw_patterns = _grow_free_measure(candidate, raw_patterns, now, size, Fraction(*now['duration']))
            timeline = _score_timeline(candidate, raw_patterns)
            outcomes.extend(result['outcomes']); removed_ties.extend(result['removed_ties'])
            automatic_patterns.add(name)
            continue
        if not original['notes'] and ((own['id'], original['id']) in rebuilt_targets or
                                     current['at'] != original['at'] or current['written'] != original['written']):
            # Earlier targets rebuilt this silence. Its surviving fragment is
            # selected for the next command, not edited twice in this command.
            outcomes.append('rebuilt')
            continue
        if current['written'] == written:
            outcomes.append('unchanged')
            continue
        start = Fraction(*current['at'])
        bounds = _place_measure_bounds(candidate['score'], timeline, name, start,
                                       start, start + duration_quarters(current['written']))
        reason = 'bar_end' if start + length > bounds[1] else None
        if reason is None and not fit and any(b['id'] != current['id'] and b['track'] == edit['track']
                and b.get('voice', 0) == voice and b['notes'] and Fraction(*b['at']) < start + length
                and start < Fraction(*b['at']) + duration_quarters(b['written'])
                for b in candidate['score']['patterns'][name]['beats']):
            reason = 'no_space'
        if reason:
            kept.append(dict(occurrence=own['id'], beat=current['id'], written=copy.deepcopy(current['written']), reason=reason))
            outcomes.append('unchanged')
            continue
        beat = copy.deepcopy(current)
        next_note = min((Fraction(*b['at']) for b in candidate['score']['patterns'][name]['beats']
                         if b['track'] == edit['track'] and b.get('voice', 0) == voice and b['notes']
                         and Fraction(*b['at']) > start), default=bounds[1])
        rebuilt = {(own['id'], b['id']) for b in candidate['score']['patterns'][name]['beats']
                   if b['track'] == edit['track'] and b.get('voice', 0) == voice and not b['notes']
                   and start < Fraction(*b['at']) < next_note}
        if duration_quarters(beat['written']) != length:
            beat.pop('duration_source', None)
        beat['written'] = copy.deepcopy(written)
        step = dict(action='place', occurrence=own['id'], beat=beat)
        if fit:
            candidate, result = _fit_score_beat(candidate, raw_patterns, dict(step, fit=fit))
            outcomes.append(result['fit']['outcome'])
            if result['fit']['applied'] != written:
                kept.append(dict(occurrence=own['id'], beat=current['id'],
                                 written=result['fit']['applied'], reason='no_space'))
        else:
            candidate, result = _place_score_beat(candidate, raw_patterns, step)
            outcomes.append('placed')
        if _beat(candidate['score'], name, current['id'])['written'] != current['written']:
            # TG recreates the following silence interval even when shrinking.
            # Native may keep a fragment's ID, but it is no longer an original
            # target of this action. Its spelling can change on the next action.
            rebuilt_targets.update(rebuilt)
        removed_ties.extend(result['removed_ties'])
    for name in {o['pattern'] for o, _, _ in records}:
        def peers(s):
            # Fit's moveVoice path owns shared annotation transfer. The range
            # guard still protects every peer note, timing and voice field,
            # and all fields of other tracks; strict Place permits no transfer.
            return [{k: v for k, v in b.items() if not (fit and b['track'] == edit['track'] and
                        k in ('text', 'chord', 'stroke', 'pick_stroke'))}
                    for b in s['score']['patterns'][name]['beats']
                    if b['track'] != edit['track'] or b.get('voice', 0) != voice]
        if name not in automatic_patterns and peers(candidate) != peers(song):
            raise ValueError('duration Fit would change another voice or track')
    retained = []
    for own, before, _ in records:
        after = next((b for b in candidate['score']['patterns'][own['pattern']]['beats'] if b['id'] == before['id']), None)
        if after is not None:
            retained.append((own, after, Fraction(*own['at']) + Fraction(*after['at'])))
        elif before['notes']:
            raise ValueError('duration Fit would remove a selected sounding beat')
    # A phrase remains a complete phrase after rest splitting. This makes the
    # returned selection usable by Copy/expression/transpose as well as duration.
    # A single local caret stays a single caret.
    if cross or len(records) > 1:
        first = min(r[2] for r in records + retained)
        end = max(at + duration_quarters(b['written']) for _, b, at in records + retained)
        selected = {(o['id'], b['id']) for o, b, _ in retained}
        for own in {o['id']: o for o, _, _ in records}.values():
            for b in candidate['score']['patterns'][own['pattern']]['beats']:
                at = Fraction(*own['at']) + Fraction(*b['at'])
                if (b['track'] == edit['track'] and (b.get('voice', 0) == voice and not b['notes']
                                                   or cross and b.get('voice', 0) != voice)
                        and first <= at < end and (own['id'], b['id']) not in selected):
                    retained.append((own, b, at))
        retained.sort(key=lambda r: (r[2], r[1].get('voice', 0), r[1]['id']))
    own, first, _ = min(retained, key=lambda r: r[2])
    groups = {}
    for o, b, _ in retained:
        groups.setdefault(o['id'], []).append(b['id'])
    selection = dict(occurrence=own['id'], track=edit['track'], voice=voice,
                     at=first['at'], beats=groups[own['id']])
    if cross:
        selection['range'] = [dict(occurrence=oid, beats=ids) for oid, ids in groups.items()]
    return candidate, dict(outcomes=outcomes, removed_ties=removed_ties, consumed_rests=consumed,
                          kept_durations=kept, selection=selection, automatic_free=bool(automatic_patterns))


def _grow_free_measure(candidate, raw_patterns, occurrence, need, right):
    """Extend the existing final-bar backing pattern without reinterpreting raw rows."""
    name = occurrence['pattern']
    size = Fraction(*occurrence['duration'])
    if need <= right:
        return raw_patterns
    if right != size:
        raise ValueError('Free edit overflow needs a measure ending its pattern; enable Independent measures first')
    if sum(str(n) == name for n in candidate['orders']) != 1:
        raise ValueError(f'Free edit overflow: pattern {name} is reused; make this measure unique with Independent measures first')
    step = Fraction(*candidate['score']['patterns'][name]['row_step'])
    rows = max(candidate['patterns'][name]['rows'], int(-(-need // step)))
    if rows > 200:
        raise ValueError('Free edit overflow exceeds 200 tracker rows; split the passage into measures first')
    previous_size = candidate['patterns'][name]['rows'] * step
    measures = candidate['score'].setdefault('measures', [])
    if not any(m['from']['occurrence'] == occurrence['id'] == m['to']['occurrence'] and
               Fraction(*m['from']['at']) < right <= Fraction(*m['to']['at']) for m in measures):
        # Preserve the unmetered pattern interval used by this command before
        # growth changes its inferred length. Never guess a rounded meter.
        left = max((Fraction(*m['to']['at']) for m in measures
                    if m['to']['occurrence'] == occurrence['id'] and Fraction(*m['to']['at']) < right), default=Fraction(0))
        meter = next(([int((right-left)*d/4), d] for d in (4,8,16,32,64,2,1)
                      if ((right-left)*d/4).denominator == 1 and 1 <= (right-left)*d/4 <= 64), None)
        if meter is None:
            raise ValueError('Free overflow needs an exact authored meter; set up Measures first')
        measures.append(dict(id=_local_id('free_measure', {m['id'] for m in measures}), meter=meter,
            **{'from':dict(occurrence=occurrence['id'],at=_pair(left)),
               'to':dict(occurrence=occurrence['id'],at=_pair(right))}))
    candidate['patterns'][name]['rows'] = rows
    for measure in candidate['score'].get('measures', []):
        if measure['to']['occurrence'] == occurrence['id'] and Fraction(*measure['to']['at']) == previous_size:
            measure['to']['at'] = _pair(rows * step)
    return [Pattern(p.name, p.rows + [[Cell() for _ in p.rows[0]] for _ in range(rows - len(p.rows))])
            if p.name == name else p for p in raw_patterns]


def _set_duration_free(song, raw_patterns, edit, timeline, active, records):
    """TG changeDuration: resize, then repack whole beat cohorts by their voice ends."""
    candidate = copy.deepcopy(song)
    track, written = edit['track'], edit['written']
    measures, targets, outcomes = {}, {}, []
    for own, original, _ in active:
        name = own['pattern']
        if song['patterns'][name].get('approved'):
            raise ValueError(f"pattern '{name}' is approved: clear its mark in the SONG tab first")
        start = Fraction(*original['at'])
        left, right = _place_measure_bounds(song['score'], timeline, name, start, start,
                                           start + duration_quarters(original['written']))
        key = (name, left, right)
        targets[name, original['id']] = key
        if key in measures:
            continue
        if left < 0 or right > Fraction(*own['duration']):
            raise ValueError('Free duration needs complete measures in a pattern; enable Independent measures first')
        source = candidate['score']['patterns'][name]['beats']
        selected = [b for b in source if b['track'] == track and left <= Fraction(*b['at']) < right]
        measures[key] = (own, _beat_cohorts(selected))

    def repack(groups, left):
        groups.sort(key=lambda group: Fraction(*group[0]['at']))
        ends = [left, left]
        for index, group in enumerate(groups):
            start = left if index == 0 else max(ends[b.get('voice', 0)] for b in group)
            for beat in group:
                beat['at'] = _pair(start)
                ends[beat.get('voice', 0)] = start + duration_quarters(beat['written'])
            if index == 0:
                minimum = min(start + duration_quarters(b['written']) for b in group)
                ends = [max(end, minimum) for end in ends]

    for own, original, _ in active:
        name = own['pattern']
        key = targets[name, original['id']]
        _, groups = measures[key]
        beat = _beat(candidate['score'], name, original['id'])
        changed = beat['written'] != written
        beat['written'] = copy.deepcopy(written)
        if changed:
            beat.pop('duration_source', None)
        # changeDuration calls updateBeatsPreciseStart both in its Free branch
        # and at its end. The second sort matters when the voices reorder.
        repack(groups, key[1]); repack(groups, key[1])
        outcomes.append('placed' if changed else 'unchanged')
    for (name, left, right), (own, groups) in measures.items():
        _stamp_cohorts(groups)
        source = candidate['score']['patterns'][name]['beats']
        changed = source != song['score']['patterns'][name]['beats']
        if changed:
            need = max(Fraction(*b['at']) + duration_quarters(b['written']) for group in groups for b in group)
            raw_patterns = _grow_free_measure(candidate, raw_patterns, own, need, right)
    untied = dict(candidate, score=dict(candidate['score'], ties=[]))
    removed = _repair_duration_ties(candidate['score'], _score_timeline(untied, raw_patterns))
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    groups = {}
    for own, beat, _ in records:
        groups.setdefault(own['id'], []).append(beat['id'])
    own, original, _ = active[0]
    beat = _beat(candidate['score'], own['pattern'], original['id'])
    selection = dict(occurrence=own['id'], track=track, voice=edit.get('voice', 0),
                     at=beat['at'], beats=groups[own['id']])
    if 'selection' in edit:
        selection['range'] = [dict(occurrence=oid, beats=ids) for oid, ids in groups.items()]
    return candidate, dict(outcomes=outcomes, removed_ties=removed, consumed_rests=[], kept_durations=[],
                          selection=selection, free=True)


def _resize_free_anchored(song, raw_patterns, edit, timeline, active, records):
    """Matrix addNoteWithoutControl retains the original anchor; refuse overlap."""
    candidate = copy.deepcopy(song)
    written = edit['written']
    length = duration_quarters(written)
    targets = {(own['pattern'], b['id']) for own, b, _ in active}
    spans, outcomes = {}, []
    for own, original, _ in active:
        name = own['pattern']
        beat = _beat(candidate['score'], name, original['id'])
        start = Fraction(*beat['at'])
        bounds = _place_measure_bounds(song['score'], timeline, name, start, start,
                                       start + duration_quarters(original['written']))
        if beat['written'] == written:
            outcomes.append('unchanged')
            continue
        raw_patterns = _grow_free_measure(candidate, raw_patterns, own, start + length, bounds[1])
        beat['written'] = copy.deepcopy(written)
        beat.pop('duration_source', None)
        spans.setdefault(name, []).append((start, start + length))
        outcomes.append('placed')
    for name, intervals in spans.items():
        beats = candidate['score']['patterns'][name]['beats']
        used = {b['id'] for b in beats}
        for beat in list(beats):
            if ((name, beat['id']) in targets or beat['track'] != edit['track'] or
                    beat.get('voice', 0) != edit.get('voice', 0)):
                continue
            left = Fraction(*beat['at'])
            right = left + duration_quarters(beat['written'])
            remaining = [(left, right)]
            for a, b in intervals:
                remaining = [(x, y) for lo, hi in remaining for x, y in
                             ((lo, min(hi, a)), (max(lo, b), hi)) if x < y]
            if remaining == [(left, right)]:
                continue
            if beat['notes'] or any(beat.get(k) for k in ('text', 'chord', 'stroke', 'pick_stroke')):
                raise ValueError(f"Free duration overlaps beat {beat['id']}; move it or shorten the requested duration")
            beats.remove(beat)
            for a, b in remaining:
                for position, piece in _split_moved_beat(beat, a, [], end=b):
                    piece['at'] = _pair(position)
                    piece['id'] = _local_id('rest_' + beat['id'], used)
                    used.add(piece['id'])
                    beats.append(piece)
    removed = _repair_duration_ties(candidate['score'], _score_timeline(candidate, raw_patterns))
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    groups = {}
    for own, beat, _ in records:
        groups.setdefault(own['id'], []).append(beat['id'])
    own, beat, _ = active[0]
    selection = dict(occurrence=own['id'], track=edit['track'], voice=edit.get('voice', 0),
                     at=beat['at'], beats=groups[own['id']])
    if 'selection' in edit:
        selection['range'] = [dict(occurrence=oid, beats=ids) for oid, ids in groups.items()]
    return candidate, dict(outcomes=outcomes, removed_ties=removed, consumed_rests=[], kept_durations=[],
                          selection=selection, free=True)


def _remove_unused_voice(song, raw_patterns, edit):
    """TuxGuitar's Remove unused voice (TGRemoveUnusedVoiceAction + removeMeasureVoices, pinned 2c46e2a1).
    Of the voices that are empty or rests at every selected beat's onset, the last is chosen; in each measure a
    selected beat lies in, that voice's rests are removed unless the voice has a note somewhere in that measure.
    Measures are Place's (authored, else the unauthored span). Annotated rests refuse, as Place's do."""
    _keys(edit, ('action', 'occurrence', 'track', 'beats', 'revision'), 'remove_unused_voice')
    identities = edit.get('beats')
    if not isinstance(identities, list) or not 1 <= len(identities) <= 1024 or len(set(identities)) != len(identities):
        raise ValueError('remove_unused_voice selects 1..1024 distinct beats')
    timeline = _score_timeline(song, raw_patterns)
    occurrence = next((o for o in timeline['occurrences'] if o['id'] == edit.get('occurrence')), None)
    if occurrence is None:
        raise ValueError('remove_unused_voice needs a played occurrence')
    name, score, track = occurrence['pattern'], song['score'], edit.get('track')
    selected = [_beat(score, name, identity) for identity in identities]
    if any(b['track'] != track for b in selected):
        raise ValueError('remove_unused_voice beats must belong to the selected track')
    records = [b for b in score['patterns'][name]['beats'] if b['track'] == track]
    selected_cohorts = {_cohort_key(b) for b in selected}
    unused = [v for v in (0, 1) if not any(b.get('voice', 0) == v and b['notes'] and _cohort_key(b) in selected_cohorts
                                           for b in records)]
    result = dict(voice=None, removed=[], selection=dict(occurrence=occurrence['id'], track=track, beats=list(identities)))
    if not unused:
        return song, result
    voice = unused[-1]
    measures = {_place_measure_bounds(score, timeline, name, Fraction(*b['at']), Fraction(*b['at']),
                                      Fraction(*b['at']) + duration_quarters(b['written'])) for b in selected}
    removed = []
    for left, right in sorted(measures):
        inside = [b for b in records if b.get('voice', 0) == voice and left <= Fraction(*b['at']) < right]
        if any(b['notes'] for b in inside):
            continue
        for b in inside:
            if any(b.get(k) not in (None, '', []) for k in ('text', 'chord', 'stroke', 'pick_stroke')):
                raise ValueError('an unused-voice rest carries an annotation; clear it first')
        removed += [b['id'] for b in inside]
    if not removed:
        return song, dict(result, voice=voice)
    candidate = copy.deepcopy(song)
    beats = candidate['score']['patterns'][name]['beats']
    beats[:] = [b for b in beats if b['id'] not in set(removed)]
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    keep = [i for i in identities if i not in set(removed)]
    return candidate, dict(result, voice=voice, removed=removed, selection=dict(result['selection'], beats=keep))


def _clean_beats(song, raw_patterns, edit):
    """TuxGuitar's Clean beat (TGCleanBeatAction + cleanBeat, pinned 2c46e2a1): at each selected beat's onset the
    track's beats in both voices lose their notes, text, chord, stroke and pick stroke and stay as rests of the
    same written duration. Tied notes refuse (untie first) rather than silently dropping ties."""
    _keys(edit, ('action', 'occurrence', 'track', 'beats', 'revision'), 'clean_beat')
    identities = edit.get('beats')
    if not isinstance(identities, list) or not 1 <= len(identities) <= 1024 or len(set(identities)) != len(identities):
        raise ValueError('clean_beat selects 1..1024 distinct beats')
    occurrence = next((o for o in _score_timeline(song, raw_patterns)['occurrences']
                       if o['id'] == edit.get('occurrence')), None)
    if occurrence is None:
        raise ValueError('clean_beat needs a played occurrence')
    name, track = occurrence['pattern'], edit.get('track')
    selected = [_beat(song['score'], name, identity) for identity in identities]
    if any(b['track'] != track for b in selected):
        raise ValueError('clean_beat beats must belong to the selected track')
    cohorts = {_cohort_key(b) for b in selected}
    candidate = copy.deepcopy(song)
    cleaned = [b for b in candidate['score']['patterns'][name]['beats'] if _cohort_key(b) in cohorts]
    _delete_incident_ties(candidate, name, {n['id'] for b in cleaned for n in b['notes']}, False)
    for b in cleaned:
        b['notes'] = []
        for key in ('text', 'chord', 'stroke', 'pick_stroke'):
            b.pop(key, None)
    result = dict(cleaned=[b['id'] for b in cleaned],
                  selection=dict(occurrence=occurrence['id'], track=track, beats=list(identities)))
    if candidate == song:
        return song, result
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    return candidate, result


def _keep_tied_strings(song, assigned, onsets, strings, verb):
    """Ties keep one string: a continuation follows its head when that string is free and in range, else refuse.
    assigned maps (pattern, note id) -> (string, fret, pitch); onsets -> (pattern, onset, track);
    strings maps a track to (string pitches, max fret)."""
    score = song['score']
    names = {oid: str(n) for oid, n in zip(score.get('order_ids', []), song.get('orders', []))}
    for _ in range(len(score.get('ties', [])) + 1):
        stable = True
        for tie in score.get('ties', []):
            head = (names[tie['from']['occurrence']], tie['from']['note'])
            tail = (names[tie['to']['occurrence']], tie['to']['note'])
            if head not in assigned or tail not in assigned or assigned[head][0] == assigned[tail][0]:
                continue
            string = assigned[head][0]
            values, top = strings[onsets[tail][2]]
            taken = {v[0] for k, v in assigned.items() if k != tail and onsets[k] == onsets[tail]}
            fret = assigned[tail][2] - values[string - 1]
            if string in taken or not 0 <= fret <= top:
                raise ValueError(f'{verb} would move tied note {tail[0]}/{tail[1]} off its string; remove the tie first')
            assigned[tail] = (string, fret, assigned[tail][2])
            stable = False
        if stable:
            return


def _retune_track(song, raw_patterns, edit):
    """TuxGuitar's Change track tuning (TGChangeTrackTuningAction + TGTrackManager.allocateNotesToStrings and
    transposeNotes, pinned 2c46e2a1). keep='pitch' (default) keeps every sounding pitch: when every string moves by
    one interval, each note stays on its string (fret += old - new); otherwise each onset's notes (both voices) go
    to the closest new string by string pitch, all or nothing, else to the lowest fret, highest pitch first, and
    the chord diagram is removed. keep='frets' is an explicit transposition: string and fret stay, pitch follows.
    String values include the capo. A capo change keeps strings and frets in both modes, as TG's offset does: the
    sound follows the capo. Differences from TG, by the owner's rule: notes TG would drop refuse the
    change; tied notes are kept on one string or refuse; trill and grace frets keep their pitch; an onset that cannot stay on its strings in a uniform
    change is reallocated as a whole (TG moves single notes to the next string)."""
    _keys(edit, ('action', 'track', 'tuning', 'channels', 'capo', 'max_fret', 'keep', 'revision',
                 'auto_channels', 'setup'), 'retune')
    score = song.get('score') or {}
    identity = edit.get('track')
    if identity not in score.get('tracks', {}):
        raise ValueError('retune needs an existing track')
    keep = edit.get('keep', 'pitch')
    if keep not in ('pitch', 'frets'):
        raise ValueError("retune keep must be 'pitch' or 'frets'")
    old = score['tracks'][identity]
    new = copy.deepcopy(old)
    setup = edit.get('setup', {})
    _keys(setup, ('name', 'color', 'clef', 'key', 'stem', 'midi', 'instrument'), 'retune setup')
    new.update(copy.deepcopy(setup))
    if new.get('midi') is None:
        new.pop('midi', None)
    for key in ('tuning', 'channels', 'capo', 'max_fret'):
        if key in edit:
            new[key] = copy.deepcopy(edit[key])
    automatic = edit.get('auto_channels', False)
    if type(automatic) is not bool:
        raise ValueError('auto_channels must be boolean')
    candidate = copy.deepcopy(song)
    added = []
    if automatic:
        if 'channels' in edit:
            raise ValueError('Choose automatic channels or explicit channels, not both')
        tuning = new.get('tuning')
        if not isinstance(tuning, list) or not 1 <= len(tuning) <= 25:
            raise ValueError('retune needs 1..25 tuning pitches')
        count = len(tuning)
        previous_count = _channels(song)
        added = list(range(previous_count, previous_count + max(0, count - len(old['channels']))))
        if previous_count + len(added) > 64:
            raise ValueError('Adding strings exceeds 64 channels; existing raw channels are preserved')
        new['channels'] = old['channels'][:count] + added
        if added:
            channels = candidate['module']['channels']
            if not isinstance(channels, list):
                channels = [dict(name=f'Ch {i+1}', pan=32) for i in range(previous_count)]
                candidate['module']['channels'] = channels
            for i, channel in enumerate(added, len(old['channels'])):
                settings = copy.deepcopy(channels[old['channels'][-1]])
                settings['name'] = f'{new.get("name", identity)} {i+1}'
                channels.append(settings)
    if new.get('channels') != old.get('channels'):   # as track_set: reassigned channels drop an imported pan binding
        new.get('midi', {}).pop('source_pan', None)
        new.get('midi', {}).pop('source_volume', None)
    if isinstance(new['tuning'], list) and len(new['tuning']) != len(old['tuning']):
        if is_percussion(old):
            raise ValueError('percussion lane count changes need drum-map allocation; unsupported')
        if 'channels' not in edit and not automatic:
            raise ValueError('retune changes the string count: give one module channel per string')
    if is_percussion(old) != is_percussion(new) and any(
            b['track'] == identity and b['notes'] for p in score['patterns'].values() for b in p['beats']):
        raise ValueError('populated pitched/percussion track conversion is unsupported')
    probe = copy.deepcopy(candidate)
    probe['score']['tracks'][identity] = new
    probe['score']['patterns'], probe['score']['ties'] = {}, []
    validate_score(probe)
    result = dict(track=identity, keep=keep, moved=[], repitched=[], chords_removed=[], chords_transposed=[],
                  spellings_cleared=[], added_channels=added,
                  retired_channels=[ch for ch in old['channels'] if ch not in new['channels']])
    if new == old:
        return song, result
    cs = candidate['score']
    cs['tracks'][identity] = new
    count, top = len(new['tuning']), new.get('max_fret', 29)
    old_eff = [p + old.get('capo', 0) for p in old['tuning']]
    new_eff = [p + new.get('capo', 0) for p in new['tuning']]
    # A capo (TG's offset) keeps strings and frets on a real guitar and in TuxGuitar: the sound rises with it. So
    # keep='pitch' compares tunings at the new capo and moves every target pitch by the capo change.
    dcapo = new.get('capo', 0) - old.get('capo', 0) if keep == 'pitch' else 0
    if keep == 'pitch':
        old_eff = [p + new.get('capo', 0) for p in old['tuning']]
    deltas = {o - n for o, n in zip(old_eff, new_eff)}
    uniform = len(old_eff) == count and len(deltas) == 1 and not is_percussion(old)
    shift = deltas.pop() if uniform else None
    unplaced, assigned, onsets = [], {}, {}  # (pattern, note id) -> (string, fret, pitch) / its onset
    kept = set()  # (pattern, onset) cohorts a uniform change keeps on their strings

    def fits(note, string, fret, s_old):
        if not 0 <= fret <= top:
            return False
        for effect in ('grace', 'trill'):
            if note.get(effect) is not None and s_old is not None and not 0 <= (
                    old_eff[s_old - 1] + note[effect]['fret'] - new_eff[string - 1]) <= top:
                return False
        return True

    for name, spec in score['patterns'].items():
        cohorts = {}
        for b in spec['beats']:
            if b['track'] == identity:
                cohorts.setdefault(Fraction(*b['at']), []).append(b)
        for at, members in cohorts.items():
            members.sort(key=lambda b: b.get('voice', 0))
            notes = [(b, n, r['string'], r['fret']) for b in members
                     for n, r in zip(b['notes'], _resolved_notes(score, b))]
            onsets.update(((name, n['id']), (name, at, identity)) for _, n, _, _ in notes)
            if not notes:
                if uniform:
                    kept.add((name, at))
                continue
            if is_percussion(old):
                continue  # Same lane count; keys and lanes are unchanged.
            if keep == 'frets':
                for b, n, s, f in notes:
                    pitch = new_eff[s - 1] + f if s is not None and s <= count and f <= top else None
                    if pitch is None or not 0 <= pitch <= 119:
                        unplaced.append(f"{name}/{n['id']}")
                    else:
                        assigned[name, n['id']] = (s, f, pitch)
                continue
            chosen = None
            if uniform and all(s is not None and fits(n, s, f + shift, s) for _, n, s, f in notes):
                chosen = [(s, f + shift) for _, n, s, f in notes]
                kept.add((name, at))
            if chosen is None and all(s is not None for _, _, s, _ in notes):
                free, chosen = set(range(1, count + 1)), []
                for _, n, s, _ in notes:
                    distances = [abs(old_eff[s - 1] - v) for v in new_eff]
                    target = distances.index(min(distances)) + 1
                    fret = n['pitch'] + dcapo - new_eff[target - 1]
                    if target not in free or not fits(n, target, fret, s):
                        chosen = None
                        break
                    free.discard(target)
                    chosen.append((target, fret))
            if chosen is None:
                free, picks = set(range(1, count + 1)), {}
                for voice in (0, 1):
                    order = sorted((i for i, (b, _, _, _) in enumerate(notes) if b.get('voice', 0) == voice),
                                   key=lambda i: -notes[i][1]['pitch'])
                    for i in order:
                        _, n, s, _ = notes[i]
                        options = [(n['pitch'] + dcapo - new_eff[j - 1], j) for j in sorted(free)
                                   if fits(n, j, n['pitch'] + dcapo - new_eff[j - 1], s)]
                        if options:
                            fret, string = min(options)
                            picks[i] = (string, fret)
                            free.discard(string)
                chosen = [picks.get(i) for i in range(len(notes))]
            for (b, n, s, f), pick in zip(notes, chosen):
                if pick is None:
                    unplaced.append(f"{name}/{n['id']}")
                else:
                    assigned[name, n['id']] = (*pick, n['pitch'] + dcapo)
    if unplaced:
        raise ValueError(f'retune cannot place {len(unplaced)} note(s) on the new strings (TuxGuitar would drop '
                         f'them): {", ".join(unplaced[:8])}')
    _keep_tied_strings(song, assigned, onsets, {identity: (new_eff, top)}, 'retune')
    for name, spec in cs['patterns'].items():
        for b in spec['beats']:
            if b['track'] != identity:
                continue
            original = next(x for x in score['patterns'][name]['beats'] if x['id'] == b['id'])
            before = {n['id']: (r['string'], r['fret']) for n, r in zip(original['notes'], _resolved_notes(score, original))}
            for n in b['notes']:
                if (name, n['id']) not in assigned:
                    continue
                string, fret, pitch = assigned[name, n['id']]
                s_old, f_old = before[n['id']]
                if (string, fret) != (s_old, f_old):
                    result['moved'].append(f"{name}/{n['id']}")
                if pitch != n['pitch']:
                    result['repitched'].append(f"{name}/{n['id']}")
                    if n.pop('spelling', None) is not None:
                        result['spellings_cleared'].append(f"{name}/{n['id']}")
                if 'channel' in n and s_old is not None and n['channel'] == old['channels'][s_old - 1]:
                    if new['channels'][string - 1] != n['channel']:
                        n.pop('channel')  # It named its string's channel: it follows the string.
                elif 'channel' in n and (string != s_old or n['channel'] not in new['channels']):
                    raise ValueError(f"note {name}/{n['id']} has an explicit playback channel; clear it before "
                                     'moving it to another string')
                if keep == 'pitch' and s_old is not None:
                    for effect in ('grace', 'trill'):
                        if n.get(effect) is not None:
                            n[effect]['fret'] = old_eff[s_old - 1] + n[effect]['fret'] - new_eff[string - 1]
                if 'string' in n or (string, fret, pitch) != (s_old, f_old, n['pitch']) or new_eff != old_eff:
                    n.update(pitch=pitch, string=string, fret=fret)  # Untouched automatic fingerings stay automatic.
            chord = b.get('chord')
            if chord is None:
                continue
            on_strings = (name, Fraction(*b['at'])) in kept  # Only a uniform change keeps cohorts.
            frets = [f + shift if f >= 0 else f for f in chord['frets']] if on_strings else None
            if keep == 'pitch' and (not on_strings or not all(
                    0 <= f + shift <= top for f in chord['frets'] if f >= 0)):
                b.pop('chord')  # TG removes the diagram of every reallocated beat.
                result['chords_removed'].append(f"{name}/{b['id']}")
            elif keep == 'pitch' and shift:
                b['chord'] = dict(chord, frets=frets, first_fret=0, name='')  # TG resets first fret and name.
                result['chords_transposed'].append(f"{name}/{b['id']}")
            else:
                try:
                    _validate_chord(chord, new)
                except ValueError:
                    b.pop('chord')
                    result['chords_removed'].append(f"{name}/{b['id']}")
    validate_score(candidate)
    candidate_raw = copy.deepcopy(raw_patterns) if added else raw_patterns
    for pattern in candidate_raw if added else ():
        for row in pattern.rows:
            row.extend(Cell() for _ in added)
    checked = authoring_view(candidate, candidate_raw)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    # Retuning changes fingering and optionally pitch, not the musical meaning
    # of a harmonic node or same-string slide/hammer/let-ring relationship.
    shifts = {(name, n['id']): assigned[name, n['id']][2] - n['pitch']
              for name, pattern in score['patterns'].items() for beat in pattern['beats']
              for n in beat['notes'] if (name, n['id']) in assigned}
    def performed(value, original=False):
        events = []
        raw = raw_patterns if original else candidate_raw
        repeated = repeat_projection(value, raw)
        plan = repeated.plan if repeated else playback_plan(value, raw)
        for event in plan['events']:
            event = copy.deepcopy(event)
            event.pop('ch', None)  # String allocation is validated separately.
            if setup.get('instrument', old['instrument']) != old['instrument'] and event.get('track') == identity:
                for key in ('instrument', 'source_instrument', 'instrument_inherited'):
                    event.pop(key, None)
            if original and 'pitch' in event:
                event['pitch'] += shifts.get((event.get('source_pattern', event.get('pattern')), event.get('note')), 0)
            events.append(event)
        return sorted(events, key=lambda e: (e['frame'], e['id'], e['type']))
    if performed(song, True) != performed(candidate):
        raise ValueError('retune cannot preserve this harmonic or string-dependent technique; '
                         'choose a compatible tuning/fingering or remove its marking first')
    return candidate, result


def _tg_transpose_strings(frets, values, shift, keep_string, top):
    """TGMeasureManager.transposeNotes(beat, ...) with transposeNote / transposeChordNote (pinned 2c46e2a1) on one
    onset: frets is a list of [string, fret, key] (both voices, or a diagram's played strings); values are the
    string pitches. Strings are visited from the far end of the transposition's direction; a note that cannot
    keep its string moves to the next string that way, displacing (shift 0) a note already there. Returns the keys
    TG would remove."""
    order = sorted(range(1, len(values) + 1), key=lambda s: values[s - 1] if shift > 0 else -values[s - 1])
    dropped = []

    def owner(string):
        return next((n for n in reversed(frets) if n[0] == string), None)

    def move(note, step, force):
        fret = note[1] + step
        can = 0 <= fret <= top
        if can and not force and keep_string:
            note[1] = fret
            return True
        value = values[note[0] - 1] + note[1] + step
        for following in order[order.index(note[0]) + 1:]:
            target = value - values[following - 1]
            if 0 <= target <= top:
                other = owner(following)
                if other is not None and not move(other, 0, not can):
                    other = None
                if other is None or other[0] != following:
                    note[0], note[1] = following, target
                    return True
        if not force and can:
            note[1] = fret
            return True
        frets.remove(note)
        dropped.append(note[2])
        return False

    for string in reversed(order):
        note = owner(string)
        if note is not None:
            move(note, shift, False)
    return dropped


def _transpose_score(song, raw_patterns, edit):
    """TuxGuitar's Transpose (TGTransposeDialog + TGTransposeAction, pinned 2c46e2a1): -12..12 semitones on the
    context track or every track (percussion skipped), over the whole track or the measure at occurrence/at, with
    try_keep_strings and apply_to_chords (both default on, as the dialog). Fingering follows transposeNote per
    onset; a diagram's strings follow transposeChordNote, then its first fret and name are reset. Differences,
    by the owner's rule: notes TG would remove, or whose pitch would leave 0..119, refuse; a diagram string TG
    mutes is reported; grace and trill frets move with their note's pitch; a tie leaving the scope refuses; a
    measure of a pattern played more than once transposes every use (the result names them)."""
    _keys(edit, ('action', 'semitones', 'track', 'all_tracks', 'scope', 'occurrence', 'at',
                 'apply_to_chords', 'try_keep_strings', 'revision', 'selection', 'voice'), 'transpose')
    shift = _int(edit.get('semitones'), -12, 12, 'transpose semitones')
    flags = {}
    for key in ('all_tracks', 'apply_to_chords', 'try_keep_strings'):
        flags[key] = edit.get(key, key != 'all_tracks')
        if type(flags[key]) is not bool:
            raise ValueError(f'transpose {key} must be boolean')
    scope = edit.get('scope', 'track')
    if scope not in ('track', 'measure', 'selection'):
        raise ValueError("transpose scope must be 'track', 'measure' or 'selection'")
    score = song.get('score') or {}
    context = edit.get('track')
    if context not in score.get('tracks', {}):
        raise ValueError('transpose needs an existing context track')
    tracks = [t for t in (score['tracks'] if flags['all_tracks'] else [context]) if not is_percussion(score['tracks'][t])]
    window = names = selected = None
    if scope == 'selection':
        if flags['all_tracks']:
            raise ValueError('selected-range transpose applies to its selected track only')
        _, _, records = _score_range(song, raw_patterns, edit)
        _unique_range(song, records)
        selected = {(o['pattern'], b['id']) for o, b, _ in records}
        names = {name for name, _ in selected}
    if scope == 'measure':
        timeline = _score_timeline(song, raw_patterns)
        occurrence = next((o for o in timeline['occurrences'] if o['id'] == edit.get('occurrence')), None)
        if occurrence is None:
            raise ValueError('transpose measure scope needs a played occurrence')
        at = _fraction(edit.get('at'), 'transpose measure position')
        # Place's measure bounds take an interval; a vanishing one names the measure that contains at.
        window = _place_measure_bounds(score, timeline, occurrence['pattern'], at, at, at + Fraction(1, 2 ** 40))
        names = {occurrence['pattern']}
    result = dict(semitones=shift, tracks=tracks, transposed=[], moved=[], spellings_cleared=[],
                  chords_transposed=[], chords_removed=[], chord_strings_muted=[],
                  occurrences=[oid for oid, n in zip(score.get('order_ids', []), song.get('orders', []))
                               if names is None or str(n) in names])
    if selected is not None:
        result['selection'] = _range_selection(edit, records)
    if not shift or not tracks:
        return song, result
    candidate = copy.deepcopy(song)
    assigned, onsets, unplaced, strings, before = {}, {}, [], {}, {}
    for identity in tracks:
        track = score['tracks'][identity]
        values = [p + track.get('capo', 0) for p in track['tuning']]
        top = track.get('max_fret', 29)
        strings[identity] = (values, top)
        for name, spec in candidate['score']['patterns'].items():
            if names is not None and name not in names:
                continue
            cohorts = {}
            for b in spec['beats']:
                at = Fraction(*b['at'])
                if b['track'] == identity and (window is None or window[0] <= at < window[1]) and (
                        selected is None or (name, b['id']) in selected):
                    cohorts.setdefault(at, []).append(b)
            for at, members in cohorts.items():
                members.sort(key=lambda b: b.get('voice', 0))
                original = {b['id']: _resolved_notes(score, _beat(score, name, b['id'])) for b in members}
                frets, fixed = [], {}
                for b in members:
                    for n, r in zip(b['notes'], original[b['id']]):
                        onsets[name, n['id']] = (name, at, identity)
                        if r['string'] is None:
                            fixed[n['id']] = None  # Unfingered: its pitch moves, fingering stays automatic.
                        else:
                            fixed[n['id']] = (r['string'], r['fret'])
                            frets.append([r['string'], r['fret'], n['id']])
                dropped = _tg_transpose_strings(frets, values, shift, flags['try_keep_strings'], top)
                unplaced += [f'{name}/{key}' for key in dropped]
                placed = {key: (s, f) for s, f, key in frets}
                for b in members:
                    for n in b['notes']:
                        key, pitch = n['id'], n['pitch'] + shift
                        if not 0 <= pitch <= 119:
                            unplaced.append(f'{name}/{key}')
                            continue
                        if key not in placed:
                            if fixed[key] is None:
                                n['pitch'] = pitch
                                result['transposed'].append(f'{name}/{key}')
                            continue
                        string, fret = placed[key]
                        for effect in ('grace', 'trill'):
                            if n.get(effect) is not None:
                                moved_fret = values[fixed[key][0] - 1] + n[effect]['fret'] + shift - values[string - 1]
                                if not 0 <= moved_fret <= top:
                                    unplaced.append(f'{name}/{key} ({effect})')
                                n[effect]['fret'] = moved_fret
                        assigned[name, key] = (string, fret, pitch)
                        before[name, key] = (fixed[key][0], track['channels'][fixed[key][0] - 1])
                        if (string, fret) != (fixed[key][0], fixed[key][1] + shift):
                            result['moved'].append(f'{name}/{key}')
                    chord = b.get('chord') if flags['apply_to_chords'] else None
                    if chord is None:
                        continue
                    played = [[i + 1, f, i + 1] for i, f in enumerate(chord['frets']) if f >= 0]
                    muted = _tg_transpose_strings(played, values, shift, flags['try_keep_strings'], top)
                    frets = [-1] * len(values)
                    for s, f, _ in played:
                        frets[s - 1] = f
                    b['chord'] = dict(chord, frets=frets, first_fret=0, name='')
                    result['chord_strings_muted'] += [f"{name}/{b['id']}/{s}" for s in muted]
                    try:
                        _validate_chord(b['chord'], track)
                        result['chords_transposed'].append(f"{name}/{b['id']}")
                    except ValueError:
                        b.pop('chord')
                        result['chords_removed'].append(f"{name}/{b['id']}")
    if unplaced:
        raise ValueError(f'transpose cannot place {len(unplaced)} note(s) (TuxGuitar would remove them): '
                         f'{", ".join(unplaced[:8])}')
    names_of = {oid: str(n) for oid, n in zip(score.get('order_ids', []), song.get('orders', []))}
    for tie in score.get('ties', []):
        ends = [(names_of[tie[s]['occurrence']], tie[s]['note']) for s in ('from', 'to')]
        if (ends[0] in onsets) != (ends[1] in onsets):
            raise ValueError(f'transpose scope cuts the tie {ends[0][0]}/{ends[0][1]} -> {ends[1][0]}/{ends[1][1]}; '
                             'transpose both ends or remove the tie first')
    _keep_tied_strings(song, assigned, onsets, strings, 'transpose')
    for name, spec in candidate['score']['patterns'].items():
        for b in spec['beats']:
            for n in b['notes']:
                if (name, n['id']) not in assigned:
                    continue
                string, fret, pitch = assigned[name, n['id']]
                result['transposed'].append(f"{name}/{n['id']}")
                if n.pop('spelling', None) is not None:
                    result['spellings_cleared'].append(f"{name}/{n['id']}")
                old_string, default = before[name, n['id']]
                if selected is not None and string != old_string:
                    n['channel'] = n.get('channel', default)
                elif 'channel' in n and string != old_string:
                    if n['channel'] != default:
                        raise ValueError(f"note {name}/{n['id']} has an explicit playback channel; clear it before "
                                         'moving it to another string')
                    n.pop('channel')  # It named its string's channel: it follows the string.
                n.update(pitch=pitch, string=string, fret=fret)
    validate_score(candidate)
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    if selected is not None:
        result['selection'] = _range_selection(edit, records)
        _check_range_strings(candidate, raw_patterns, records)
        for own, beat, _ in records:
            after = _resolved_notes(candidate['score'], _beat(candidate['score'], own['pattern'], beat['id']))
            for old, new in zip(_resolved_notes(score, beat), after):
                if old.get('harmonic'):
                    expected = [dict(layer, pitch=layer['pitch'] + shift) for layer in _harmonic_layers(old, old.get('velocity'))]
                    if _harmonic_layers(new, new.get('velocity')) != expected:
                        raise ValueError('selected transpose cannot preserve the requested interval of this harmonic; '
                                         'choose a compatible harmonic node or remove its marking first')
    return candidate, result


def _insert_rest(song, raw_patterns, edit):
    """TuxGuitar's Insert rest (TGInsertRestBeatAction, pinned 2c46e2a1), outside free-edit mode. Without a beat of
    the voice at the caret it places a rest of the selected duration there (addSilence, through strict Place).
    Otherwise moveVoicesPrecise moves that voice's beats from the caret right by the caret beat's duration inside
    its measure: trailing rests that would leave the measure are dropped (an annotated one is kept), anything else
    that would leave it refuses, and a rest of that duration fills the caret. A shared pattern changes every use."""
    _keys(edit, ('action', 'occurrence', 'track', 'voice', 'at', 'written', 'rest_id', 'free', 'revision'), 'insert_rest')
    timeline = _score_timeline(song, raw_patterns)
    occurrence = next((o for o in timeline['occurrences'] if o['id'] == edit.get('occurrence')), None)
    if occurrence is None:
        raise ValueError('insert_rest needs a played occurrence')
    name, score, track = occurrence['pattern'], song['score'], edit.get('track')
    if track not in score.get('tracks', {}):
        raise ValueError('insert_rest needs an existing track')
    voice = _int(edit.get('voice', 0), 0, 1, 'insert_rest voice')
    start = _fraction(edit.get('at'), 'insert_rest at')
    rest_id = _id(edit.get('rest_id'), 'insert_rest rest_id')
    records = [b for b in score['patterns'].get(name, {}).get('beats', [])
               if b['track'] == track and b.get('voice', 0) == voice]
    head = next((b for b in records if Fraction(*b['at']) == start), None)
    if head is None:
        rest = dict(id=rest_id, track=track, voice=voice, at=_pair(start), written=copy.deepcopy(edit.get('written')), notes=[])
        return _place_score_beat(song, raw_patterns, dict(action='place', occurrence=occurrence['id'], beat=rest))
    length = duration_quarters(head['written'])
    left, right = _place_measure_bounds(score, timeline, name, start, start, start + length)
    if edit.get('free') is True or _automatic_free(song, raw_patterns, occurrence['id'], track, start):
        return _insert_rest_free(song, timeline, occurrence, head, length, right, rest_id, raw_patterns)
    later = sorted((b for b in records if start <= Fraction(*b['at']) < right), key=lambda b: Fraction(*b['at']))
    end = lambda b: Fraction(*b['at']) + duration_quarters(b['written'])
    annotated = lambda b: any(b.get(k) not in (None, '', []) for k in ('text', 'chord', 'stroke', 'pick_stroke'))
    dropped = []
    while later and not later[-1]['notes'] and not annotated(later[-1]) and end(later[-1]) + length > right:
        dropped.append(later.pop()['id'])
    if later and end(later[-1]) + length > right:
        raise ValueError('Insert rest needs room in this measure: a later note would pass its end. TuxGuitar also leaves a '
                         'full measure unchanged outside free-edit mode; shorten or remove a later beat first')
    candidate = copy.deepcopy(song)
    beats = candidate['score']['patterns'][name]['beats']
    moved = {b['id'] for b in later}
    beats[:] = [b for b in beats if b['id'] not in set(dropped)]
    for b in sorted(list(beats), key=lambda b: Fraction(*b['at']), reverse=True):
        if b['id'] in moved:
            destination = Fraction(*b['at']) + length
            _move_voice_cohort(beats, b, destination)
    rest = dict(id=rest_id, track=track, voice=voice, at=_pair(start), written=copy.deepcopy(head['written']), notes=[])
    targets = _beat_cohorts(b for b in beats if b['track'] == track and Fraction(*b['at']) == start)
    if targets and targets[0][0].get('cohort', 0):
        rest['cohort'] = targets[0][0]['cohort']
    beats.append(rest)
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    return candidate, dict(moved=sorted(moved), dropped=dropped,
                           selection=dict(occurrence=occurrence['id'], track=track, voice=voice, at=_pair(start), beats=[rest_id]))


def _insert_rest_free(song, timeline, occurrence, head, length, right, rest_id, raw_patterns):
    """TGMeasureManager.insertRestBeatWithoutControl (free-edit mode): every beat of the track's measure from the caret
    on (both voices) moves right by the caret beat's duration without any check, and a rest of that duration fills
    the caret. The bar may overflow, as TG's does; here a bar's length is its pattern's rows, so the pattern grows to
    hold it while the measure keeps its meter (measure_errors calls it 'long'). TG lets the overflow sound over the next
    bar; here the next bars wait. Growing needs the bar to end its pattern and the pattern to play once; else it refuses."""
    name, score, track = occurrence['pattern'], song['score'], head['track']
    start = Fraction(*head['at'])
    moved = [b for b in score['patterns'][name]['beats'] if b['track'] == track and start <= Fraction(*b['at']) < right]
    need = max(Fraction(*b['at']) + duration_quarters(b['written']) for b in moved) + length
    candidate = copy.deepcopy(song)
    spec = candidate['score']['patterns'][name]
    ids = {b['id'] for b in moved}
    for b in spec['beats']:
        if b['id'] in ids:
            b['at'] = _pair(Fraction(*b['at']) + length)
    spec['beats'].append(dict(id=rest_id, track=track, voice=head.get('voice', 0), at=_pair(start),
                              written=copy.deepcopy(head['written']), notes=[]))
    raw_patterns = _grow_free_measure(candidate, raw_patterns, occurrence, need, right)
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    return candidate, dict(moved=sorted(ids), dropped=[], overfull=need > right,
                           selection=dict(occurrence=occurrence['id'], track=track, voice=head.get('voice', 0),
                                          at=_pair(start), beats=[rest_id]))


def _crop_phrase_curve(note, effect, offset, length, total):
    """Crop only when both the written curve and TG's discrete controls stay exact."""
    points = note[effect]['points']
    if not points:
        return copy.deepcopy(note[effect])
    left, right = offset * 12 / total, (offset + length) * 12 / total
    def value_at(position):
        before = next((p for p in reversed(points) if p['position'] <= position), None)
        after = next((p for p in points if p['position'] > position), None)
        if before is None:
            return Fraction(0)
        if after is None:
            return Fraction(before['value'])
        return before['value'] + (position - before['position']) * Fraction(
            after['value'] - before['value'], after['position'] - before['position'])
    cropped = [dict(position=left, value=value_at(left)),
               *(copy.deepcopy(p) for p in points if left < p['position'] < right),
               dict(position=right, value=value_at(right))]
    for point in cropped:
        position = (point['position'] - left) * 12 / (right - left)
        value = Fraction(point['value'])
        if position.denominator != 1 or value.denominator != 1:
            raise ValueError(f'{effect} crop needs fractional curve points; choose an existing curve boundary')
        point['position'], point['value'] = int(position), int(value)
    curve = dict(points=cropped)
    ticks, first, count = int(total * 960), int(offset * 960), int(length * 960)
    def trajectory(controls, begin, size):
        at_tick = dict(controls)
        current = 64
        answer = []
        for tick in range(begin + size):
            current = at_tick.get(tick, current)
            if tick >= begin:
                answer.append(current)
        return answer
    if trajectory(_pitch_controls({effect: note[effect]}, ticks), first, count) != trajectory(
            _pitch_controls({effect: curve}, count), 0, count):
        raise ValueError(f'{effect} crop changes discrete pitch steps; choose another curve boundary')
    return curve


def _split_moved_beat(beat, start, boundaries, *, end=None, continuation=False, check_ring=False, source_offset=Fraction(0)):
    """Exact fragments of a moved/re-barred beat, with annotations only on its head."""
    length = duration_quarters(beat['written'])
    end = start + length if end is None else end
    clipped = end - start != length
    cuts = [start, *sorted({x for x in boundaries if start < x < end}), end]
    # A clipped tail is a new attack; curves retain their original pitch path.
    if clipped:
        beat = copy.deepcopy(beat)
        for note in beat['notes']:
            for effect in ('bend', 'tremolo_bar'):
                if note.get(effect):
                    note[effect] = _crop_phrase_curve(note, effect, source_offset, end - start, length)
    unsafe = ('slide', 'let_ring') if clipped else _SPLIT_BOUNDARY_UNSAFE
    if not check_ring:
        unsafe += ('let_ring',)
    if (clipped or len(cuts) > 2) and any(n.get(key) for n in beat['notes'] for key in unsafe):
        effects = sorted({k for n in beat['notes'] for k in unsafe if n.get(k)})
        raise ValueError(f"part {beat['track']}, beat {beat['id']}: splitting a technique ({', '.join(effects)}) "
                         'would change its target or curve; include the complete beat or choose another boundary')
    parts = []
    for left, right in zip(cuts, cuts[1:]):
        position = left
        for written in ([beat['written']] if len(cuts) == 2 and not clipped else _split_written(right - left)):
            piece = copy.deepcopy(beat)
            piece['written'] = copy.deepcopy(written)
            if len(cuts) > 2 or clipped:
                piece.pop('duration_source', None)
            if parts or continuation:
                piece.pop('text', None)
                piece.pop('chord', None)
                piece.pop('pick_stroke', None)
                piece.pop('stroke', None)
                # Playback reads these from the tie head. Repeating them on
                # generated continuations creates duplicate engraving. Hammer
                # stays: TG's following-note velocity reads its last predecessor.
                for note in piece['notes']:
                    for key in (_SPLIT_UNSAFE if parts else ('grace', 'fade_in')):
                        if key not in ('hammer', 'let_ring'):
                            note.pop(key, None)
            parts.append((position, piece))
            position += duration_quarters(written)
    if beat.get('stroke') and parts and not continuation:
        # TG caps spread at a quarter note, then rounds by the stroke value.
        # Keep the attack's spread when the first fragment becomes shorter.
        before = (min(960, _written_ticks(beat['written'])) + beat['stroke']['value']) // (2 * beat['stroke']['value'])
        after = (min(960, _written_ticks(parts[0][1]['written'])) + beat['stroke']['value']) // (2 * beat['stroke']['value'])
        if before != after:
            raise ValueError(f"part {beat['track']}, beat {beat['id']}: split strum changes its attack spacing; "
                             'choose a boundary leaving at least a quarter note before the cut')
    if not clipped and len(parts) > 1 and any(n.get(k) for n in beat['notes'] for k in _SPLIT_UNSAFE):
        last_at, last = parts[-1]
        ticks = int(last_at * 960) - int(start * 960) + _written_ticks(last['written'])
        if ticks != _written_ticks(beat['written']):
            raise ValueError(f"beat {beat['id']}: split technique changes its performed tick duration")
    return parts


def _check_reflow_gates(song, candidate, remap, raw_patterns=None, candidate_raw=None):
    """Rebar/Move may split the neighbor that TG uses to end a ringing note.

    Check the actual gate and strum delay through the existing playback planner;
    comparing written tie lengths alone misses that neighboring-beat dependency.
    Only these boundary-dependent effects need this check, and raw cells remain
    validated by the calling command's normal ownership/compile path.
    """
    if not any(b.get('stroke') or any(n.get('let_ring') for n in b['notes'])
               for p in song['score']['patterns'].values() for b in p['beats']):
        return
    if raw_patterns is None and any(p.get('data', '').strip() for p in song['patterns'].values()):
        raise ValueError('let-ring/strum reflow needs the compiled raw tempo map; edit through the score command')
    def gates(source, raw, tempos=None):
        if raw is None:
            raw = [Pattern(str(name), [[Cell() for _ in range(_channels(source))] for _ in range(p['rows'])])
                   for name, p in source['patterns'].items()]
        timeline = _score_timeline(source, raw)
        tempo = source.get('module', {}).get('tempo', 125)
        tempos = _raw_tempos(timeline, raw, tempo) if tempos is None else tempos
        return timeline, _performed_releases(timeline, TempoClock(tempo, tempos)), tempos
    before, old, tempos = gates(song, raw_patterns)
    # Rebar and Prepare preserve absolute time and forbid relocating raw cells.
    # Move has its own staged raw patterns, whose real tempo map is authoritative.
    after, new, _ = gates(candidate, candidate_raw, tempos if candidate_raw is None else None)
    for identity, gate in old.items():
        if not gate['let_ring'] and gate.get('stroke') is None:
            continue
        note = before['by_id'][identity]
        key = (note['occurrence'], note['note'])
        path = remap.get(key)
        if key in remap and not path:
            continue  # Move left explicitly deleted this attack, even if its ID is reused.
        target = f"{path[0]['occurrence']}/{path[0]['note']}" if path else identity
        if target not in new:
            continue  # Move left explicitly deleted this attack.
        other = new[target]
        if (gate['end'] - gate['start'], gate['start'] - note['start']) != (
                other['end'] - other['start'], other['start'] - after['by_id'][target]['start']):
            effect = 'let-ring' if gate['let_ring'] else 'strum'
            bar = next(i + 1 for i, own in enumerate(before['occurrences']) if own['id'] == note['occurrence'])
            raise ValueError(f"part {note['track']}, bar {bar}, beat {note['beat']}: "
                             f"{effect} timing changes at the new boundary; choose a boundary that keeps its "
                             'following beat intact or clear that technique first')


def _move_beats(song, raw_patterns, edit):
    """TuxGuitar's Beat > Move beats left/right (TGMoveBeatsLeft/RightAction, TGTrackManager.moveTrackBeats, pinned
    2c46e2a1): every beat of the track (both voices) from the caret to the end of the song moves by the caret voice's
    duration, or explicit positive `amount` quarter notes (TGMoveBeatsAction). Custom amounts must be exact IT ticks.
    Moving left first removes the beats in the moved span. Beats cross into the bars they land in, keeping
    their ties. A bar's beats live in its pattern, so every pattern from the caret's order on must play only there
    (SYNC-04): a pattern played at another order refuses until those measures are made unique. Trailing measures
    are added as needed; crossing notes split exactly with ties when their full-chain performance can be retained,
    and separated/deleted tie links are removed."""
    _keys(edit, ('action', 'occurrence', 'track', 'voice', 'at', 'direction', 'amount', 'revision'), 'move_beats')
    timeline = _score_timeline(song, raw_patterns)
    occurrences = timeline['occurrences']
    k = next((i for i, o in enumerate(occurrences) if o['id'] == edit.get('occurrence')), None)
    if k is None:
        raise ValueError('Move beats needs a played occurrence')
    score, track = song['score'], edit.get('track')
    if track not in score.get('tracks', {}):
        raise ValueError('Move beats needs an existing track')
    voice = _int(edit.get('voice', 0), 0, 1, 'move_beats voice')
    if edit.get('direction') not in ('left', 'right'):
        raise ValueError('Move beats direction is left or right')
    start = _fraction(edit.get('at'), 'move_beats at')
    origin = lambda o: Fraction(*o['at'])
    head = next((b for b in score['patterns'].get(occurrences[k]['pattern'], {}).get('beats', [])
                 if b['track'] == track and b.get('voice', 0) == voice and Fraction(*b['at']) == start), None)
    if head is None:
        raise ValueError('Move beats needs a note or rest of this voice at the caret')
    size = (_fraction(edit['amount'], 'move_beats amount', True) if 'amount' in edit
            else duration_quarters(head['written']))
    if size > 256:
        raise ValueError('Move beats supports at most 256 quarter notes at once')
    if 'amount' in edit and (size * 24).denominator != 1:
        raise ValueError('Move beats amount must land on an exact tracker tick (1/24 quarter note)')
    move = size if edit['direction'] == 'right' else -size
    move_start = origin(occurrences[k]) + start
    later = occurrences[k:]
    for o in later:
        others = [i + 1 for i, x in enumerate(occurrences) if x['pattern'] == o['pattern'] and x['id'] != o['id']]
        if others:
            raise ValueError(f"pattern {o['pattern']} also plays at order {others[0]}: moving these beats would change that "
                             'use too. Make the measures from here on unique first (Song tab)')
    entries = [(o, b, origin(o) + Fraction(*b['at'])) for o in later
               for b in score['patterns'].get(o['pattern'], {}).get('beats', []) if b['track'] == track]
    entries = [e for e in entries if e[2] >= move_start]
    removed = [e for e in entries if move < 0 and e[2] < move_start - move]
    moving = [e for e in entries if e not in removed]
    measures = sorted((origin(next(o for o in occurrences if o['id'] == m['from']['occurrence'])) + Fraction(*m['from']['at']),
                       origin(next(o for o in occurrences if o['id'] == m['to']['occurrence'])) + Fraction(*m['to']['at']))
                      for m in score.get('measures', []))
    candidate = copy.deepcopy(song)
    staged_raw = list(raw_patterns)
    needed = max((at + move + duration_quarters(b['written']) for _, b, at in moving), default=Fraction(0))
    song_end = origin(occurrences[-1]) + Fraction(*occurrences[-1]['duration'])
    if needed > song_end:
        last_length = measure_units(song)[-1]['length']
        count = math.ceil((needed - song_end) / last_length)
        plan = measure_command(song, dict(action='measure_add', at=len(song['orders']), count=count))
        candidate = plan['song']
        for name, entry in plan['created'].items():
            staged_raw.append(Pattern(name, [[Cell() for _ in range(_channels(song))] for _ in range(entry['rows'])]))
        timeline = _score_timeline(candidate, staged_raw)
        occurrences = timeline['occurrences']
        later = occurrences[k:]
        measures = sorted((origin(next(o for o in occurrences if o['id'] == m['from']['occurrence'])) + Fraction(*m['from']['at']),
                           origin(next(o for o in occurrences if o['id'] == m['to']['occurrence'])) + Fraction(*m['to']['at']))
                          for m in candidate['score'].get('measures', []))
    patterns = candidate['score']['patterns']
    gone = {(o['pattern'], b['id']) for o, b, _ in removed + moving}
    for name in {o['pattern'] for o in later}:
        if name in patterns:
            patterns[name]['beats'] = [b for b in patterns[name]['beats'] if (name, b['id']) not in gone]
    remap, split_ties = {}, []
    moved_groups = {}
    retained_groups = {name: _beat_cohorts(patterns[name]['beats']) for name in {o['pattern'] for o in later}
                       if name in patterns}
    boundaries = {x for m in measures for x in m} | {origin(o) for o in later}
    for o, b, at in sorted(moving, key=lambda e: (e[2], e[1].get('cohort', 0))):
        paths = {n['id']: [] for n in b['notes']}
        for new_at, beat in _split_moved_beat(b, at + move, boundaries, check_ring=True):
            target = next((x for x in later if origin(x) <= new_at < origin(x) + Fraction(*x['duration'])), None)
            if target is None:
                raise ValueError('moved beat has no destination measure')
            spec = patterns.setdefault(target['pattern'], dict(row_step=patterns[o['pattern']]['row_step'], beats=[]))
            used = {x['id'] for x in spec['beats']} | {n['id'] for x in spec['beats'] for n in x['notes']}
            beat['at'] = _pair(new_at - origin(target))
            if beat['id'] in used:
                beat['id'] = _local_id('moved', used)
            used.add(beat['id'])
            for note in beat['notes']:
                old = note['id']
                if note['id'] in used:
                    note['id'] = _local_id('moved', used)
                used.add(note['id'])
                paths[old].append(dict(occurrence=target['id'], note=note['id']))
            spec['beats'].append(beat)
            group_key = target['pattern'], o['id'], _cohort_key(b), new_at
            moved_groups.setdefault(group_key, []).append(beat)
        for old, path in paths.items():
            remap[o['id'], old] = path
            split_ties.extend({'from': x, 'to': y} for x, y in zip(path, path[1:]))
    for name, groups in retained_groups.items():
        groups += [group for key, group in moved_groups.items() if key[0] == name]
        groups.sort(key=lambda group: Fraction(*group[0]['at']))
        _stamp_cohorts(groups)
    dropped = {(o['id'], n['id']) for o, b, _ in removed for n in b['notes']}
    ties, removed_ties = [], []
    for tie in candidate['score'].get('ties', []):
        ends = [(tie[side]['occurrence'], tie[side]['note']) for side in ('from', 'to')]
        lost = [e in dropped for e in ends]
        if any(lost):
            removed_ties.append(tie)
        else:
            ties.append({side: copy.deepcopy(remap[e][-1 if side == 'from' else 0]) if e in remap else copy.deepcopy(tie[side])
                         for side, e in zip(('from', 'to'), ends)})
    candidate['score']['ties'] = ties + split_ties
    removed_ties.extend(_repair_duration_ties(candidate['score'], timeline))
    checked = authoring_view(candidate, staged_raw)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    _check_reflow_gates(song, candidate, {**remap, **dict.fromkeys(dropped, [])}, raw_patterns, staged_raw)
    return candidate, dict(moved=len(moving), removed=[b['id'] for _, b, _ in removed], removed_ties=removed_ties,
                           selection=dict(occurrence=occurrences[k]['id'], track=track, voice=voice, at=_pair(start)))


def _score_range(song, raw_patterns, edit):
    """Resolve the existing qualified clipboard selection, including tie boundaries."""
    groups = edit['selection']
    timeline = _score_timeline(song, raw_patterns)
    track = edit.get('track')
    voice = _int(edit.get('voice', 0), 0, 1, 'selected voice')
    source = song
    if edit.get('action') in ('transpose', 'shift_pitch', 'shift_strings', 'set_expression'):
        # Copy can detach a phrase from its outside ties; pitch/expression still need the full chain.
        selected_beats = {(g['occurrence'], bid) for g in groups for bid in g['beats']}
        selected_notes = {(o['id'], n['id']) for o in timeline['occurrences']
                          for b in song['score']['patterns'].get(o['pattern'], {}).get('beats', [])
                          if (o['id'], b['id']) in selected_beats and
                          (edit.get('action') == 'transpose' or b['voice'] == voice or
                           edit.get('action') == 'set_expression' and
                           any(k in edit.get('changes', {}) for k in ('stroke', 'pick_stroke')))
                          for n in b['notes']}
        if any(sum((e['occurrence'], e['note']) in selected_notes for e in t.values()) == 1
               for t in song['score'].get('ties', [])):
            raise ValueError('range pitch/expression needs complete ties; include the linked notes')
    clipboard = capture_score_clipboard(source, selection=groups, raw_patterns=raw_patterns)
    if any(b['track'] != track for b in clipboard['beats']):
        raise ValueError('score command selection must belong to one track')
    selected = {(g['occurrence'], identity) for g in groups for identity in g['beats']}
    records = [(o, b, Fraction(*o['at']) + Fraction(*b['at']))
               for o in timeline['occurrences']
               for b in song['score']['patterns'].get(o['pattern'], {}).get('beats', [])
               if (o['id'], b['id']) in selected]
    first, last = min(r[2] for r in records), max(r[2] for r in records)
    for o in timeline['occurrences']:
        for b in song['score']['patterns'].get(o['pattern'], {}).get('beats', []):
            if b['track'] == track and first <= Fraction(*o['at']) + Fraction(*b['at']) <= last:
                if (o['id'], b['id']) not in selected:
                    if (edit.get('action') == 'set_duration' and not b['notes'] and
                            not any(b.get(k) for k in ('text', 'chord', 'stroke', 'pick_stroke')) and
                            b.get('stem', 'auto') == 'auto' and 'duration_source' not in b):
                        continue  # Place's generated plain rests are not newly selected edit targets.
                    raise ValueError('range command needs every onset of the track, both voices, between its endpoints')
    return clipboard, timeline, records


def _unique_range(song, records):
    for o, _, _ in records:
        name = o['pattern']
        if sum(str(n) == name for n in song['orders']) != 1:
            raise ValueError('range edits need unique source patterns; make each selected occurrence unique first')
        if song['patterns'][name].get('approved'):
            raise ValueError(f"pattern '{name}' is approved: clear its mark in the SONG tab first")


def _range_selection(edit, records):
    own, beat, _ = min(records, key=lambda r: r[2])
    groups = copy.deepcopy(edit['selection'])
    return dict(occurrence=own['id'], track=edit['track'], voice=edit.get('voice', beat.get('voice', 0)), at=beat['at'],
                beats=next(g['beats'] for g in groups if g['occurrence'] == own['id']), range=groups)


def _shift_range_pitch(song, raw_patterns, edit):
    """TG semitone shortcut: preflight every active-voice fret, never reallocate strings."""
    _keys(edit, ('action', 'selection', 'track', 'voice', 'direction', 'revision'), 'shift_pitch')
    direction = _int(edit.get('direction'), -1, 1, 'pitch direction')
    if not direction:
        raise ValueError('pitch direction must be -1 or 1')
    _, _, records = _score_range(song, raw_patterns, edit)
    targets = [r for r in records if r[1]['voice'] == edit.get('voice', 0)]
    _unique_range(song, targets)
    track = song['score']['tracks'][edit['track']]
    if is_percussion(track):
        raise ValueError('semitone shifts need a pitched track')
    candidate = copy.deepcopy(song)
    for own, beat, _ in targets:
        moved = _beat(candidate['score'], own['pattern'], beat['id'])
        for n, old in zip(moved['notes'], _resolved_notes(song['score'], beat)):
            if old['string'] is None or not 0 <= old['fret'] + direction <= track.get('max_fret', 29):
                raise ValueError('semitone shift is outside this string fret range')
            n.update(pitch=old['pitch'] + direction, string=old['string'], fret=old['fret'] + direction)
            n.pop('spelling', None)
            if old.get('harmonic'):
                expected = [dict(layer, pitch=layer['pitch'] + direction) for layer in _harmonic_layers(old, old.get('velocity'))]
                if _harmonic_layers(n, n.get('velocity')) != expected:
                    raise ValueError('semitone shift cannot preserve the requested interval of this harmonic')
    validate_score(candidate)
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    return candidate, dict(selection=_range_selection(edit, records))


def _shift_range_strings(song, raw_patterns, edit):
    _keys(edit, ('action', 'selection', 'track', 'voice', 'direction', 'revision'), 'shift_strings')
    direction = _int(edit.get('direction'), -1, 1, 'string direction')
    if not direction:
        raise ValueError('string direction must be -1 or 1')
    _, _, records = _score_range(song, raw_patterns, edit)
    targets = [r for r in records if r[1]['voice'] == edit.get('voice', 0)]
    _unique_range(song, targets)
    track = song['score']['tracks'][edit['track']]
    if is_percussion(track):
        raise ValueError('pitch-preserving string shifts need a pitched track')
    candidate = copy.deepcopy(song)
    for own, beat, _ in targets:
        moved = _beat(candidate['score'], own['pattern'], beat['id'])
        for n, resolved in zip(moved['notes'], _resolved_notes(song['score'], beat)):
            old = resolved['string']
            new = old + direction if old is not None else 0
            if not 1 <= new <= len(track['tuning']):
                raise ValueError('there is no adjacent string in that direction')
            delta = track['tuning'][old - 1] - track['tuning'][new - 1]
            fret = resolved['fret'] + delta
            if not 0 <= fret <= track.get('max_fret', 29):
                raise ValueError('string shift is outside the adjacent string fret range')
            for effect in ('grace', 'trill'):
                if n.get(effect) is not None:
                    n[effect]['fret'] += delta
                    if not 0 <= n[effect]['fret'] <= track.get('max_fret', 29):
                        raise ValueError(f'string shift cannot preserve the {effect} fret')
            # Fingering is notation; keep the actual voice's mixer/instrument memory ownership.
            n.update(string=new, fret=fret, channel=resolved['channel'])
    _check_range_strings(candidate, raw_patterns, targets)
    validate_score(candidate)
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    if playback_plan(song, raw_patterns)['events'] != playback_plan(candidate, raw_patterns)['events']:
        raise ValueError('string shift changes native playback (harmonic, slide, hammer or other string-dependent linkage); '
                         'include its linked notes or keep the original fingering')
    return candidate, dict(selection=_range_selection(edit, records))


def _range_expression(song, raw_patterns, edit):
    """The local note_set semantics, over an immutable qualified selection."""
    _keys(edit, ('action', 'selection', 'track', 'voice', 'changes', 'revision'), 'set_expression')
    changes = edit.get('changes')
    flags = ('ghost', 'accent', 'heavy_accent', 'staccato', 'palm_mute', 'dead',
             'let_ring', 'fade_in', 'vibrato', 'slide', 'hammer', 'tapping', 'slapping', 'popping')
    effects = ('bend', 'tremolo_bar', 'harmonic', 'trill', 'tremolo_picking', 'grace')
    _keys(changes, ('velocity', *flags, *effects, 'stroke', 'pick_stroke'), 'range expression changes')
    if not changes:
        raise ValueError('range expression needs a velocity, technique or stroke change')
    for key, value in changes.items():
        if key == 'velocity':
            if value is not None:
                _int(value, 0, 127, 'velocity')
        elif key in flags and type(value) is not bool:
            raise ValueError(f'{key} must be boolean')
    _, _, records = _score_range(song, raw_patterns, edit)
    strokes = {key: value for key, value in changes.items() if key in ('stroke', 'pick_stroke')}
    note_changes = {key: value for key, value in changes.items() if key not in strokes}
    voice = edit.get('voice', 0)
    targets = [(own, beat, at) for own, beat, at in records if beat['voice'] == voice or strokes]
    _unique_range(song, targets)
    if sum(len(b['notes']) for _, b, _ in targets if b['voice'] == voice) > 1024:
        raise ValueError('range expression supports at most 1024 selected notes')
    candidate = song
    # Tablature.getCurrentNoteRange/Selector filters the active voice. Beat strokes
    # belong to their shared onset and retain the existing all-voice beat semantics.
    for own, beat, _ in records:
        for note in beat['notes'] if beat['voice'] == voice else []:
            patch = {key: value for key, value in note_changes.items()
                     if value is not None and value is not False or key in note}
            if patch:
                candidate = apply_score_edit(candidate, dict(op='note_set', pattern=own['pattern'], beat=beat['id'],
                                                            note=dict(id=note['id'], **patch)))
        if strokes:
            changed = copy.deepcopy(_beat(candidate['score'], own['pattern'], beat['id']))
            changed.update(copy.deepcopy(strokes))
            candidate = apply_score_edit(candidate, dict(op='beat_set', pattern=own['pattern'], beat=changed))
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    return candidate, dict(selection=_range_selection(edit, records))


def _check_range_strings(song, raw_patterns, records):
    """An explicit audio channel must not conceal a physically occupied string."""
    touched = {(o['id'], b['id']) for o, b, _ in records}
    spans = {}
    for own in _score_timeline(song, raw_patterns)['occurrences']:
        for beat in song['score']['patterns'].get(own['pattern'], {}).get('beats', []):
            at = Fraction(*own['at']) + Fraction(*beat['at'])
            for note in _resolved_notes(song['score'], beat):
                if note['string'] is None:
                    continue
                key = beat['track'], note['string']
                changed = (own['id'], beat['id']) in touched
                end = at + duration_quarters(beat['written'])
                for old_at, old_end, old_changed in spans.get(key, []):
                    if (changed or old_changed) and at < old_end and old_at < end:
                        raise ValueError('range pitch edit collides with another note on the same string')
                spans.setdefault(key, []).append((at, end, changed))


def _stem_group(timeline, caret):
    """Written TGMeasureImpl.canJoin groups, with implicit gaps acting as rests."""
    measure = next((m for m in timeline['measures'] if m[0] <= caret['start'] < m[1]), None)
    if measure is None:
        own = next(o for o in timeline['occurrences'] if o['id'] == caret['occurrence'])
        origin = Fraction(*own['at'])
        cuts = sorted({origin, origin + Fraction(*own['duration']),
                       *(v for m in timeline['measures'] for v in m[:2]
                         if origin < v < origin + Fraction(*own['duration']))})
        left, right = next((a, b) for a, b in zip(cuts, cuts[1:]) if a <= caret['start'] < b)
        measure = left, right, dict(meter=[4, 4])
    left, right, metadata = measure
    numerator, denominator = metadata['meter']
    division = Fraction(3, 2) if denominator == 8 and numerator % 3 == 0 else Fraction(1)
    groups, group, previous = [], [], None
    for b in sorted((b for b in timeline['beats'] if b['track'] == caret['track'] and b['voice'] == caret['voice']
                     and left <= b['start'] < right), key=lambda b: b['start']):
        if b['rest']:
            group, previous = [], None
            continue
        joined = (previous is not None and previous['end'] == b['start'] and
                  previous['written']['value'] >= 8 and b['written']['value'] >= 8 and
                  (previous['start'] - left) // division == (b['start'] - left) // division)
        if not joined:
            group = []
            groups.append(group)
        group.append(b)
        previous = b
    return next(g for g in groups if caret in g)


def _set_stem_group(song, raw_patterns, edit):
    """TGSetVoiceUp/Down/Auto: the caret voice's TGMeasureImpl beam group."""
    _keys(edit, ('action', 'occurrence', 'track', 'beat', 'stem', 'revision'), 'set_stem')
    stem = edit.get('stem')
    if stem not in ('auto', 'up', 'down', 'inherit'):
        raise ValueError('stem must be auto, up, down or inherit')
    timeline = _score_timeline(song, raw_patterns)
    caret = next((b for b in timeline['beats'] if b['occurrence'] == edit.get('occurrence') and
                  b['beat'] == edit.get('beat') and b['track'] == edit.get('track')), None)
    if caret is None:
        raise ValueError('stem group needs an authored beat in a played occurrence')
    result = dict(selection=dict(occurrence=caret['occurrence'], track=caret['track'], voice=caret['voice'],
                                at=_pair(caret['local_at']), beats=[caret['beat']]), changed_beats=[])
    if caret['rest']:
        return song, result
    targets = _stem_group(timeline, caret)
    changed = [b for b in targets if
               (('stem' in _beat(song['score'], b['pattern'], b['beat'])) if stem == 'inherit' else
                _beat(song['score'], b['pattern'], b['beat']).get('stem') != stem)]
    if not changed:
        return song, result
    identities = {(b['pattern'], b['beat']) for b in targets}
    changed_ids = {(b['pattern'], b['beat']) for b in changed}
    for b in timeline['beats']:
        if (b['pattern'], b['beat']) in changed_ids:
            if song['patterns'][b['pattern']].get('approved'):
                raise ValueError(f"pattern '{b['pattern']}' is approved: clear its mark in the SONG tab first")
            if {(p['pattern'], p['beat']) for p in _stem_group(timeline, b)} != identities:
                raise ValueError('shared pattern has different beam groups; make the selected occurrence unique first')
    candidate = copy.deepcopy(song)
    for b in changed:
        target = _beat(candidate['score'], b['pattern'], b['beat'])
        if stem == 'inherit':
            target.pop('stem', None)
        else:
            target['stem'] = stem
    checked = authoring_view(candidate, raw_patterns)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    result['changed_beats'] = [dict(occurrence=b['occurrence'], beat=b['beat']) for b in changed]
    return candidate, result


def _range_score_command(song, raw_patterns, edit):
    """Phrase commands share clipboard qualification, exact timing and one candidate."""
    clipboard, timeline, records = _score_range(song, raw_patterns, edit)
    track, voice, action = edit['track'], edit.get('voice', 0), edit['action']
    removed_ties = []
    if action == 'repeat':
        destination = max(at + duration_quarters(b['written']) for _, b, at in records)
        own = next((o for o in timeline['occurrences'] if Fraction(*o['at']) <= destination <
                    Fraction(*o['at']) + Fraction(*o['duration'])), timeline['occurrences'][-1])
        pi = next(i for i, p in enumerate(raw_patterns) if p.name == own['pattern'])
        at = destination - Fraction(*own['at'])
        candidate = paste_score_clipboard(song, Module(patterns=raw_patterns), pi,
            _pair(at / timeline['step']), clipboard, own['id'], across=True, replace=True)
        staged_raw = list(raw_patterns)
        known = {p.name for p in staged_raw}
        for name, entry in candidate['patterns'].items():
            if str(name) not in known:
                staged_raw.append(Pattern(str(name), [[Cell() for _ in range(_channels(song))]
                                                     for _ in range(entry['rows'])]))
        timeline = _score_timeline(candidate, staged_raw)
        stop = destination + max(Fraction(*b['at']) + duration_quarters(b['written']) for b in clipboard['beats'])
        fresh = []
        for o in timeline['occurrences']:
            ids = [b['id'] for b in candidate['score']['patterns'].get(o['pattern'], {}).get('beats', [])
                   if b['track'] == track and destination <= Fraction(*o['at']) + Fraction(*b['at']) < stop]
            if ids:
                fresh.append(dict(occurrence=o['id'], beats=ids))
        first = next(o for o in timeline['occurrences'] if o['id'] == fresh[0]['occurrence'])
        result_selection = dict(occurrence=first['id'], track=track, voice=voice,
                                at=_pair(destination - Fraction(*first['at'])),
                                beats=fresh[0]['beats'], range=fresh)
    else:
        targets = [r for r in records if action not in ('cut', 'delete', 'rest') or r[1].get('voice', 0) == voice]
        _unique_range(song, targets)
        candidate = copy.deepcopy(song)
        removed_notes = set()
        if action in ('cut', 'delete') and targets and not any(b['notes'] for _, b, _ in targets):
            # Reuse local Cut's same-voice gap closure, from right to left so IDs remain stable.
            # TG's rest-only range action reuses the caret voice; native closes each
            # selected rest once rather than repeatedly removing that same object.
            for o, b, _ in sorted(targets, key=lambda r: r[2], reverse=True):
                candidate, _ = score_command(candidate, raw_patterns, dict(action='cut', occurrence=o['id'],
                    track=track, voice=b.get('voice', 0), beats=[b['id']], at=b['at']))
            first, beat, _ = min(targets, key=lambda r: r[2])
            result_selection = dict(occurrence=first['id'], track=track, voice=voice,
                                    at=beat['at'], beats=[], range=[])
        else:
            for o, b, _ in targets:
                removed_notes.update((o['id'], n['id']) for n in b['notes'])
                target = _beat(candidate['score'], o['pattern'], b['id'])
                if action == 'delete_beats':
                    candidate['score']['patterns'][o['pattern']]['beats'].remove(target)
                else:
                    target['notes'] = []
                    if action == 'clean_beat':
                        for key in ('text', 'chord', 'stroke', 'pick_stroke'):
                            target.pop(key, None)
            removed_ties = [t for t in song['score'].get('ties', [])
                            if any((e['occurrence'], e['note']) in removed_notes for e in t.values())]
            candidate['score']['ties'] = [t for t in song['score'].get('ties', []) if t not in removed_ties]
            _clear_removed_chords(song, candidate)
            result_selection = _range_selection(edit, records)
            if action == 'delete_beats':
                result_selection.update(beats=[], range=[])
        staged_raw = raw_patterns
    checked = authoring_view(candidate, staged_raw)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    result = dict(selection=result_selection, removed_ties=removed_ties)
    if action in ('cut', 'repeat'):
        result['clipboard'] = clipboard
    return candidate, result


def _matrix_entry(song, raw_patterns, edit):
    """TG Matrix hit routing on one unpublished candidate; no separate roll data."""
    _keys(edit, ('action', 'occurrence', 'track', 'voice', 'at', 'pitch', 'written', 'fit', 'free', 'revision'), 'matrix entry')
    timeline = _score_timeline(song, raw_patterns)
    score = song['score']
    occurrence = next((o for o in timeline['occurrences'] if o['id'] == edit.get('occurrence')), None)
    if occurrence is None:
        raise ValueError('matrix entry needs a played occurrence')
    track = edit.get('track')
    if track not in score['tracks']:
        raise ValueError('matrix entry needs an existing track')
    voice = _int(edit.get('voice', 0), 0, 1, 'matrix voice')
    click = _fraction(edit.get('at'), 'matrix position')
    written = copy.deepcopy(edit.get('written'))
    length = duration_quarters(written)
    if type(edit.get('fit', False)) is not bool:
        raise ValueError('matrix fit must be boolean')
    if type(edit.get('free', False)) is not bool:
        raise ValueError('matrix free must be boolean')
    if _automatic_free(song, raw_patterns, occurrence['id'], track, click):
        edit = dict(edit, free=True)
    spec = score['tracks'][track]
    drums = is_percussion(spec)
    pitch = _int(edit.get('pitch'), 1 if drums else 0, 100 if drums else 119, 'matrix pitch')
    name = occurrence['pattern']
    bounds = _place_measure_bounds(score, timeline, name, click, click, click + Fraction(1, 960))
    beats = score['patterns'].get(name, {}).get('beats', [])
    active = sorted((b for b in beats if b['track'] == track and b.get('voice', 0) == voice
                     and bounds[0] <= Fraction(*b['at']) < bounds[1]), key=lambda b: Fraction(*b['at']))
    audition = dict(pitch=pitch, instrument=spec.get('instrument', 1))
    if voice and not active:
        return copy.deepcopy(song), dict(matrix='absent_voice', audition=[audition])
    if song['patterns'][name].get('approved'):
        raise ValueError(f"pattern '{name}' is approved: clear its mark in the SONG tab first")
    containing = next((b for b in active if Fraction(*b['at']) <= click <
                       Fraction(*b['at']) + duration_quarters(b['written'])), None)
    if edit.get('free') and containing is None:
        return copy.deepcopy(song), dict(matrix='absent_voice', audition=[audition])
    if containing is not None:
        anchor = Fraction(*containing['at'])
    else:
        # The normal TG editor completes silence before Matrix sees it. Project
        # that subdivision without saving filler rests or creating an absent voice.
        anchor = max([bounds[0], *(Fraction(*b['at']) + duration_quarters(b['written'])
                                  for b in active if Fraction(*b['at']) <= click)])
        stop = min([bounds[1], *(Fraction(*b['at']) for b in active if Fraction(*b['at']) > click)])
        for part in _split_written(stop - anchor):
            if anchor + duration_quarters(part) > click:
                break
            anchor += duration_quarters(part)
    cohort_rank = containing.get('cohort', 0) if containing is not None else 0
    cohort = sorted((b for b in beats if b['track'] == track and Fraction(*b['at']) == anchor
                     and b.get('cohort', 0) == cohort_rank),
                    key=lambda b: b.get('voice', 0))
    for beat in cohort:
        match = next((n for n in beat['notes'] if n['pitch'] == pitch), None)
        if match:
            candidate = apply_score_edit(song, dict(op='note_delete', pattern=name, beat=beat['id'], note=match['id']))
            return candidate, dict(matrix='deleted', selection=dict(occurrence=occurrence['id'], track=track,
                voice=beat.get('voice', 0), at=_pair(anchor), beats=[beat['id']], notes=[], string=match['string']))
    used = {n['string'] for b in cohort for n in _resolved_notes(score, b)}
    string = next((i for i, open_pitch in enumerate(spec['tuning'], 1) if i not in used and
                   (drums or pitch >= open_pitch + spec.get('capo', 0))), None)
    if string is None:
        raise ValueError('No unused string or lane can hold this matrix note')
    fret = pitch if drums else pitch - spec['tuning'][string - 1] - spec.get('capo', 0)
    if not drums and fret > spec.get('max_fret', 29):
        raise ValueError('The first available string exceeds its fret limit')
    audition_anchor = anchor
    candidate = song
    report = {}
    if edit.get('free'):
        target = [(occurrence, containing, Fraction(*occurrence['at']) + anchor)]
        candidate, report = _resize_free_anchored(song, raw_patterns, dict(action='set_duration',
            occurrence=occurrence['id'], track=track, voice=voice, beats=[containing['id']], written=written, free=True),
            timeline, target, target)
        raw_patterns = _grow_free_measure(candidate, raw_patterns, occurrence, anchor + length, bounds[1])
        timeline = _score_timeline(candidate, raw_patterns)
        containing = _beat(candidate['score'], name, containing['id'])
    elif containing is not None and containing['notes']:
        if duration_quarters(containing['written']) != length:
            ids = {n['id'] for n in containing['notes']}
            uses = {o['id'] for o in timeline['occurrences'] if o['pattern'] == name}
            if any(e['occurrence'] in uses and e['note'] in ids for t in score.get('ties', []) for e in t.values()):
                raise ValueError('matrix entry cannot resize an incident tied beat')
            resized = copy.deepcopy(containing)
            resized['written'] = written
            resized.pop('duration_source', None)
            command = dict(action='place', occurrence=occurrence['id'], beat=resized)
            if edit.get('fit'):
                candidate, report = _fit_score_beat(song, raw_patterns, dict(command, fit='tg_duration'))
            else:
                candidate, report = _place_score_beat(song, raw_patterns, command, timeline=timeline)
        containing = _beat(candidate['score'], name, containing['id'])
        if anchor + duration_quarters(containing['written']) <= click:
            anchor += duration_quarters(containing['written'])
            containing = None
    else:
        containing = None
    if containing is None:
        active_after = [b for b in candidate['score']['patterns'].get(name, {}).get('beats', [])
                        if b['track'] == track and b.get('voice', 0) == voice]
        stop = min([bounds[1], *(Fraction(*b['at']) for b in active_after
                                if b['notes'] and Fraction(*b['at']) > anchor)])
        count, remainder = divmod(stop - anchor, length)
        if count > 512:
            raise ValueError('matrix rest subdivision is too large')
        try:
            parts = [written] * int(count) + (_split_written(remainder) if remainder else [])
        except ValueError:
            parts = _split_written(stop - anchor)
        for part in parts:
            if anchor <= click < anchor + duration_quarters(part):
                written = part
                break
            anchor += duration_quarters(part)
        else:
            raise ValueError('matrix click has no containing duration cell')
    else:
        written = containing['written']
    current = candidate['score']['patterns'].get(name, {}).get('beats', [])
    # Matrix's upstream addNote resolves a different beat for a later peer onset
    # and may delete that peer. Never let our chosen string overwrite it.
    if any(b['track'] == track and b.get('voice', 0) != voice and Fraction(*b['at']) == anchor
           and any(n['string'] == string for n in _resolved_notes(candidate['score'], b)) for b in current):
        raise ValueError('matrix destination string is occupied by the other voice')
    note = dict(id=_local_id('matrix_note', {n['id'] for b in current for n in b['notes']}),
                pitch=pitch, string=string, fret=fret)
    placed = copy.deepcopy(containing) if containing is not None else dict(
        id=_local_id('matrix_beat', {b['id'] for b in current}), track=track, voice=voice, at=_pair(anchor), notes=[])
    placed['written'] = copy.deepcopy(written)
    placed['notes'].append(note)
    candidate, result = _place_score_beat(candidate, raw_patterns,
        dict(action='place', occurrence=occurrence['id'], beat=placed), timeline=timeline)
    result.update(matrix='added', **{k: v for k, v in report.items() if k != 'selection'})
    result['selection']['string'] = string
    # TG's modified-note hook previews the original context beat, including both
    # voices, even when normal Matrix entry retargeted the new note to a later rest.
    result['audition'] = [dict(pitch=n['pitch'], **{k: n[k] for k in ('velocity', 'instrument') if k in n},
                               **({} if 'instrument' in n else dict(instrument=spec.get('instrument', 1))))
        for b in candidate['score']['patterns'][name]['beats'] if b['track'] == track and Fraction(*b['at']) == audition_anchor
        and b.get('cohort', 0) == cohort_rank
        for n in b['notes']]
    return candidate, result


def score_command(song, raw_patterns, edit):
    """Native Cut/Repeat/Place, as one immutable candidate and selection result.

    Beat IDs delimit a contiguous range in one occurrence/track. Cut deletes the
    explicit note IDs, or the current string in each selected voice; an omitted
    string selects complete chords. Pitched voices keep their duration as rests.
    Cutting a pre-existing rest closes its same-voice gap only in its measure.
    Repeat copies the complete contiguous beat range (both voices), moves to the
    next current-voice beat and replaces the destination. Measure and occurrence
    crossings get exact written pieces and ties, never rounded tracker cells.
    An occurrence-qualified selection uses the bounded range clipboard path:
    Cut keeps note durations/rests; Repeat replaces existing spans after its end.
    """
    if 'independent' in edit and type(edit['independent']) is not bool:
        raise ValueError('independent must be boolean')
    if edit.get('independent') and edit.get('action') in ('matrix_entry', 'set_stem', 'place', 'set_duration', 'remove_unused_voice', 'clean_beat',
            'insert_rest', 'move_beats', 'transfer_voice', 'cut', 'repeat', 'rest', 'delete', 'delete_beats'):
        selected = [g['occurrence'] for g in edit.get('selection', [])]
        if edit.get('occurrence'):
            selected.append(edit['occurrence'])
        if selected:
            ids = song['score']['order_ids']
            # Moving/inserting material can touch following bars, including an existing tie tail.
            if edit.get('action') in ('matrix_entry', 'set_duration', 'place', 'move_beats', 'insert_rest', 'repeat'):
                selected = ids[min(ids.index(o) for o in selected):]
            song, raw_patterns = independent_score_occurrences(song, raw_patterns, selected)
    edit = {k: v for k, v in edit.items() if k != 'independent'}
    action = edit.get('action')
    if action == 'matrix_entry':
        return _matrix_entry(song, raw_patterns, edit)
    if action == 'set_stem':
        return _set_stem_group(song, raw_patterns, edit)
    if 'selection' in edit and action in ('cut', 'repeat', 'rest', 'delete', 'delete_beats', 'clean_beat'):
        return _range_score_command(song, raw_patterns, edit)
    if action == 'place':
        if 'fit' in edit:
            return _fit_score_beat(song, raw_patterns, edit)
        return _place_score_beat(song, raw_patterns, edit)
    if action == 'set_duration':
        return _set_duration_range(song, raw_patterns, edit)
    if action == 'remove_unused_voice':
        return _remove_unused_voice(song, raw_patterns, edit)
    if action == 'clean_beat':
        return _clean_beats(song, raw_patterns, edit)
    if action == 'insert_rest':
        return _insert_rest(song, raw_patterns, edit)
    if action == 'move_beats':
        return _move_beats(song, raw_patterns, edit)
    if action == 'transfer_voice':
        return transfer_score_voice(song, raw_patterns, edit)
    if action == 'route_voices':
        from .score_routing import route_voices
        return route_voices(song, raw_patterns, edit)
    if action in ('track_add', 'track_clone', 'track_remove', 'track_move'):
        return track_command(song, raw_patterns, edit)
    if action == 'retune':
        return _retune_track(song, raw_patterns, edit)
    if action == 'transpose':
        return _transpose_score(song, raw_patterns, edit)
    if action == 'shift_strings':
        return _shift_range_strings(song, raw_patterns, edit)
    if action == 'shift_pitch':
        return _shift_range_pitch(song, raw_patterns, edit)
    if action == 'set_expression':
        return _range_expression(song, raw_patterns, edit)
    if action not in ('cut', 'repeat'):
        raise ValueError('score command action must be cut, repeat, place, set_duration, remove_unused_voice, '
                         'clean_beat, retune or transpose')
    if 'selection' in edit:
        return _range_score_command(song, raw_patterns, edit)
    timeline = _score_timeline(song, raw_patterns)
    score = song['score']
    oid = edit.get('occurrence')
    occurrences = copy.deepcopy(timeline['occurrences'])
    occurrence = next((o for o in occurrences if o['id'] == oid), None)
    if occurrence is None:
        raise ValueError('score command needs a played occurrence')
    name = occurrence['pattern']
    track = edit.get('track')
    if track not in score['tracks']:
        raise ValueError('score command needs an existing track')
    voice = _int(edit.get('voice', 0), 0, 1, 'selected voice')
    identities = edit.get('beats')
    if not isinstance(identities, list) or not 1 <= len(identities) <= 1024 or len(set(identities)) != len(identities):
        raise ValueError('score command selects 1..1024 distinct beats')
    anchors = [_beat(score, name, identity) for identity in identities]
    if any(b['track'] != track for b in anchors):
        raise ValueError('score command selection must belong to one track')
    first = min(Fraction(*b['at']) for b in anchors)
    last = max(Fraction(*b['at']) for b in anchors)
    source_beats = [b for b in score['patterns'][name]['beats']
                    if b['track'] == track and first <= Fraction(*b['at']) <= last]
    # CopyAction captures whole beats even when DeleteNoteOrRestAction addresses
    # individual strings. Repeat always operates on the complete beat range.
    clipboard = capture_score_clipboard(song, name, [b['id'] for b in source_beats], oid)
    note_ids = edit.get('notes')
    if note_ids is not None:
        available = {n['id'] for b in anchors for n in b['notes']}
        if not isinstance(note_ids, list) or any(n not in available for n in note_ids):
            raise ValueError('selected note IDs must belong to the selected beats')
        note_ids = set(note_ids)
    selected_string = edit.get('string')
    if selected_string is not None:
        _int(selected_string, 1, len(score['tracks'][track]['tuning']), 'selected string')
    candidate = copy.deepcopy(song)
    staged_raw = list(raw_patterns)
    step = timeline['step']
    spans = {o['id']: (Fraction(*o['at']), Fraction(*o['duration'])) for o in occurrences}
    measures = []
    for m in score.get('measures', []):
        ends = [spans[m[k]['occurrence']][0] + Fraction(*m[k]['at']) for k in ('from', 'to')]
        measures.append((*ends, m['meter']))
    # Unmetered portions retain the existing order-occurrence boundary.
    boundaries = sorted({Fraction(0), timeline['duration'],
                         *(x for a, b, _ in measures for x in (a, b)),
                         *(x for a, d in spans.values() for x in (a, a + d))})
    authored = list(measures)
    measures.extend((a, b, None) for a, b in zip(boundaries, boundaries[1:])
                    if not any(x <= a and b <= y for x, y, _ in authored))
    measures.sort()
    records = []
    for o in occurrences:
        origin = spans[o['id']][0]
        occurrence_beats = score['patterns'].get(o['pattern'], {}).get('beats', [])
        cohorts = _cohort_strokes(occurrence_beats)
        for b in occurrence_beats:
            at = origin + Fraction(*b['at'])
            normalized = dict(b, **cohorts[_cohort_key(b)])
            records.append(dict(oid=o['id'], name=o['pattern'], beat=copy.deepcopy(normalized),
                                start=at, end=at + duration_quarters(b['written']), fresh=False))
    original = copy.deepcopy(records)

    def measure_at(at):
        return next((m for m in measures if m[0] <= at < m[1]), None)

    def extend(until):
        end = max(a + d for a, d in spans.values())
        meter = measures[-1][2] if measures else None
        length = Fraction(4 * meter[0], meter[1]) if meter else spans[occurrences[-1]['id']][1]
        # Backing rows remain integral; multiple short measures can share one
        # backing pattern. No rounded endpoint enters the authored score.
        count = (length / step).denominator
        size = length * count
        rows = int(size / step)
        if not 1 <= rows <= 200:
            raise ValueError('appended measure exceeds backing pattern capacity')
        while end < until:
            new_name = _local_id('repeat', set(map(str, candidate['patterns'])))
            new_oid = _fresh_id(set(candidate['score']['order_ids']))
            candidate['patterns'][new_name] = dict(rows=rows, data='')
            candidate['orders'].append(new_name)
            candidate['score']['order_ids'].append(new_oid)
            candidate['score']['patterns'][new_name] = dict(row_step=_pair(step), beats=[])
            staged_raw.append(Pattern(new_name, [[Cell() for _ in range(_channels(song))] for _ in range(rows)]))
            occurrences.append(dict(id=new_oid, pattern=new_name, at=_pair(end), duration=_pair(size)))
            spans[new_oid] = (end, size)
            for i in range(count):
                a, b = end + i * length, end + (i + 1) * length
                measures.append((a, b, meter))
                if meter:
                    mid = _local_id('repeat_measure', {m['id'] for m in candidate['score'].get('measures', [])})
                    candidate['score'].setdefault('measures', []).append(
                        dict(id=mid, meter=list(meter), **{
                            'from': dict(occurrence=new_oid, at=_pair(i * length)),
                            'to': dict(occurrence=new_oid, at=_pair((i + 1) * length))}))
            end += size

    origin = spans[oid][0]
    inserted = []
    if action == 'cut':
        cut_beats = anchors if note_ids else [b for b in anchors if b.get('voice', 0) == voice]
        for b in sorted(cut_beats, key=lambda b: Fraction(*b['at']), reverse=True):
            record = next(r for r in records if r['oid'] == oid and r['beat']['id'] == b['id'])
            if b['notes']:
                resolved = {n['id']: n for n in _resolved_notes(score, b)}
                record['beat']['notes'] = [
                    n for n in b['notes'] if not
                    (n['id'] in note_ids if note_ids is not None else
                     selected_string is None or resolved[n['id']]['string'] == selected_string)]
            elif note_ids is None or not note_ids:
                bounds = measure_at(record['start'])
                if bounds is None or record['end'] > bounds[1]:
                    raise ValueError('cut rest crosses a measure boundary; split its written duration first')
                for use in occurrences:
                    if use['pattern'] == name:
                        other_origin = spans[use['id']][0]
                        other = measure_at(other_origin + Fraction(*b['at']))
                        if other is None or (other[0] - other_origin, other[1] - other_origin) != (
                                bounds[0] - origin, bounds[1] - origin):
                            raise ValueError('cut rest has different measure bounds in shared occurrences; make the pattern unique first')
                following = [r for r in records if r['beat']['track'] == track and
                             r['beat'].get('voice', 0) == b.get('voice', 0) and
                             record['start'] < r['start'] < bounds[1]]
                distance = min((r['start'] for r in following), default=record['end']) - record['start']
                peers = [r['beat'] for r in records if r is not record and r['oid'] == oid and
                         _cohort_key(r['beat']) == _cohort_key(record['beat'])]
                if peers and record['beat'].get('text'):
                    text = record['beat']['text']
                    if any(p.get('text', text) != text for p in peers):
                        raise ValueError('cut rest cannot preserve conflicting per-voice text in one group')
                    min(peers, key=lambda p: p.get('voice', 0))['text'] = text
                records.remove(record)
                local_records = [r for r in records if r['beat']['track'] == track and
                                 bounds[0] <= r['start'] < bounds[1]]
                # A written measure can span backing patterns. Use performed
                # positions while regrouping, then restore each source offset.
                for r in local_records:
                    r['beat']['at'] = _pair(r['start'])
                local = [r['beat'] for r in local_records]
                for r in sorted(following, key=lambda r: r['start']):
                    _move_voice_cohort(local, r['beat'], r['start'] - distance)
                    r['start'] -= distance
                    r['end'] -= distance
                removed = {id(r['beat']) for r in local_records} - {id(b) for b in local}
                records[:] = [r for r in records if id(r['beat']) not in removed]
                for r in local_records:
                    r['beat']['at'] = _pair(r['start'] - spans[r['oid']][0])
                # moveVoicesPrecise fills one caret-duration rest after the
                # shifted voice when it fits, reusing the first beat there.
                last = max((r['end'] for r in records if r['beat']['track'] == track and
                            r['beat'].get('voice', 0) == b.get('voice', 0) and
                            bounds[0] <= r['start'] < bounds[1]), default=record['start'] + distance)
                fill = duration_quarters(b['written'])
                if last + fill <= bounds[1]:
                    rest = dict(id=_local_id('rest_' + b['id'], {r['beat']['id'] for r in records}),
                        track=track, voice=b.get('voice', 0), at=_pair(last - origin),
                        written=copy.deepcopy(b['written']), notes=[])
                    targets = _beat_cohorts(r['beat'] for r in records if r['oid'] == oid and
                                            r['beat']['track'] == track and r['start'] == last)
                    if targets and targets[0][0].get('cohort', 0):
                        rest['cohort'] = targets[0][0]['cohort']
                    records.append(dict(oid=oid,name=name,beat=rest,start=last,end=last+fill,fresh=False))
    else:
        duration = max(Fraction(*b['at']) + duration_quarters(b['written'])
                       for b in source_beats) - first
        final = max((b for b in anchors if b.get('voice', 0) == voice),
                    key=lambda b: Fraction(*b['at']), default=max(anchors, key=lambda b: Fraction(*b['at'])))
        after = origin + Fraction(*final['at'])
        bounds = measure_at(after)
        following = sorted((r for r in records if r['beat']['track'] == track and
                            r['beat'].get('voice', 0) == voice and after < r['start'] < bounds[1]),
                           key=lambda r: r['start'])
        final_end = after + duration_quarters(final['written'])
        # Gaps in native notation are implicit rests; they are real caret stops.
        destination = min(following[0]['start'], final_end) if following else min(final_end, bounds[1])
        extend(destination + duration)
        until = destination + duration
        retained = []
        for r in records:
            if r['beat']['track'] != track or r['end'] <= destination or r['start'] >= until:
                retained.append(r)
                continue
            if r['start'] < destination:
                if r['beat']['notes']:
                    raise ValueError('repeat starts inside a sustained voice; select its beat boundary')
                before = copy.deepcopy(r)
                before['end'] = destination
                retained.append(before)
            if r['end'] > until:
                after_record = copy.deepcopy(r)
                after_record['start'] = until
                after_record['beat']['notes'] = []
                after_record['beat'].pop('text', None)
                after_record['beat'].pop('chord', None)
                retained.append(after_record)
        records = retained
        for b in clipboard['beats']:
            at = destination + Fraction(*b['at'])
            r = dict(oid=oid, name=name, beat=copy.deepcopy(b), start=at,
                     end=at + duration_quarters(b['written']), fresh=True)
            records.append(r)
            inserted.append(r)

    # Only changed occurrence versions are materialized. Shared pattern source
    # changes affect every use, as other TAB edits do; differing edits to the same
    # shared source must be made unique explicitly.
    old_by_occ = {o['id']: [r for r in original if r['oid'] == o['id']] for o in occurrences}
    parts = {o['id']: [] for o in occurrences}
    used_b = {n: {b['id'] for b in p['beats']} for n, p in candidate['score']['patterns'].items()}
    used_n = {n: {v['id'] for b in p['beats'] for v in b['notes']}
              for n, p in candidate['score']['patterns'].items()}
    endpoint_paths, generated_ties, fresh_paths = {}, [], {}
    for r in records:
        old = next((v for v in old_by_occ[r['oid']] if v['beat']['id'] == r['beat']['id']), None)
        if not r['fresh'] and old == r:
            parts[r['oid']].append(copy.deepcopy(r['beat']))
            for n in r['beat']['notes']:
                endpoint_paths[(r['oid'], n['id'])] = [dict(occurrence=r['oid'], note=n['id'])]
            continue
        cuts = sorted({r['start'], r['end'],
                       *(x for a, b, _ in measures for x in (a, b) if r['start'] < x < r['end']),
                       *(a for a, _ in spans.values() if r['start'] < a < r['end'])})
        paths = {n['id']: [] for n in r['beat']['notes']}
        piece_index = 0
        for a, b in zip(cuts, cuts[1:]):
            position = a
            for written in _split_written(b - a):
                dest = next(o for o in occurrences if spans[o['id']][0] <= position <
                            sum(spans[o['id']]))
                target = dest['pattern']
                used_b.setdefault(target, set())
                used_n.setdefault(target, set())
                piece = copy.deepcopy(r['beat'])
                keep = (not r['fresh'] and not piece_index and target == r['name'] and
                        not any(p['id'] == r['beat']['id'] for p in parts[dest['id']]))
                piece['id'] = r['beat']['id'] if keep else _local_id('copy_' + r['beat']['id'], used_b[target])
                used_b[target].add(piece['id'])
                piece['at'] = _pair(position - spans[dest['id']][0])
                piece['written'] = (copy.deepcopy(r['beat']['written'])
                                    if len(cuts) == 2 and b - a == duration_quarters(r['beat']['written'])
                                    else written)
                piece.pop('duration_source', None)
                if piece_index:
                    piece.pop('text', None)
                    piece.pop('chord', None)
                for n in piece['notes']:
                    old_id = n['id']
                    n['id'] = old_id if keep else _local_id('copy_' + old_id, used_n[target])
                    used_n[target].add(n['id'])
                    paths[old_id].append(dict(occurrence=dest['id'], note=n['id']))
                parts[dest['id']].append(piece)
                if r['fresh']:
                    fresh_paths.setdefault(dest['id'], []).append(piece['id'])
                position += duration_quarters(written)
                piece_index += 1
        for nid, path in paths.items():
            endpoint_paths[(('copy' if r['fresh'] else r['oid']), nid)] = path
            generated_ties.extend({'from': left, 'to': right} for left, right in zip(path, path[1:]))
    changed = {}
    for o in occurrences:
        version = sorted(parts[o['id']], key=lambda b: (Fraction(*b['at']), b['track'], b.get('voice', 0), b['id']))
        before = sorted((r['beat'] for r in old_by_occ[o['id']]),
                        key=lambda b: (Fraction(*b['at']), b['track'], b.get('voice', 0), b['id']))
        if version == before:
            continue
        if o['pattern'] in changed and changed[o['pattern']][1] != version:
            raise ValueError('command has different results in shared occurrences; make the pattern unique first')
        changed[o['pattern']] = (o['id'], version)
        candidate['score']['patterns'].setdefault(o['pattern'], dict(row_step=_pair(step)))['beats'] = version
    # Map old ties in every affected use. Moving tied material between reused
    # patterns would require ambiguous occurrence remapping and is refused.
    def old_path(endpoint):
        old_oid, nid = endpoint['occurrence'], endpoint['note']
        pname = next(o['pattern'] for o in occurrences if o['id'] == old_oid)
        if pname not in changed:
            return [endpoint]
        selected_oid = changed[pname][0]
        path = endpoint_paths.get((selected_oid, nid), [])
        if any(e['occurrence'] != selected_oid for e in path) and old_oid != selected_oid:
            raise ValueError('moving tied material across shared occurrences needs unique patterns')
        return [dict(e, occurrence=old_oid) if e['occurrence'] == selected_oid else e for e in path]
    ties = []
    for tie in score.get('ties', []):
        left, right = old_path(tie['from']), old_path(tie['to'])
        if bool(left) != bool(right):
            raise ValueError('command would leave an external tie dangling; select both endpoints or remove the tie first')
        if left:
            ties.append({'from': left[-1], 'to': right[0]})
    if action == 'repeat':
        for tie in clipboard['ties']:
            ties.append({'from': endpoint_paths['copy', tie['from']][-1],
                         'to': endpoint_paths['copy', tie['to']][0]})
    # Internal copied/split edges are duplicated only when they lie wholly in
    # one shared pattern. Cross-pattern copies require unique destinations.
    copied = [t for t in ties if t not in score.get('ties', [])]
    for tie in generated_ties:
        if tie not in ties:
            ties.append(tie)
            copied.append(tie)
    for tie in copied:
        lo, ro = tie['from']['occurrence'], tie['to']['occurrence']
        lp = next(o['pattern'] for o in occurrences if o['id'] == lo)
        rp = next(o['pattern'] for o in occurrences if o['id'] == ro)
        uses = [o['id'] for o in occurrences if o['pattern'] == lp]
        if lo != ro and (len(uses) > 1 or sum(o['pattern'] == rp for o in occurrences) > 1):
            raise ValueError('cross-pattern tied Repeat needs unique destination patterns')
        if lo == ro:
            for use in uses:
                edge = {side: dict(e, occurrence=use) for side, e in tie.items()}
                if edge not in ties:
                    ties.append(edge)
    candidate['score']['ties'] = ties
    if action == 'cut':
        _clear_removed_chords(song, candidate)
    checked = authoring_view(candidate, staged_raw)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    selected_oid = next(iter(fresh_paths), oid) if action == 'repeat' else oid
    selected = dict(occurrence=selected_oid, track=track, voice=voice,
                    at=_pair(destination - spans[selected_oid][0]) if action == 'repeat' else
                    _pair(_fraction(edit['at'], 'caret position') if 'at' in edit else first),
                    beats=fresh_paths.get(selected_oid, []) if action == 'repeat' else identities,
                    notes=sorted(note_ids) if note_ids is not None and action == 'cut' else [])
    return candidate, dict(clipboard=clipboard, selection=selected)


def capture_native_clipboard(song, raw_patterns, selection):
    """Capture a Pattern selection without reducing authored notes to cells."""
    # Reuse the selection validator; a zero transpose leaves all sources intact.
    transform_native_selections(song, raw_patterns,
                                dict(action='transpose', semitones=0, selections=[selection]))
    pi = selection['pattern']
    pattern = raw_patterns[pi]
    r0, r1 = selection.get('r0', 0), selection.get('r1', len(pattern.rows)-1)
    columns = {ch: set(fs) for ch, fs in selection['cols']}
    first_channel = min(columns)
    spec = song['score']['patterns'].get(pattern.name, {})
    step = Fraction(song.get('module', {}).get('speed', 6), 24)
    exact = selection.get('notes')
    chosen, masks, resolved = {}, {}, {}
    for beat in spec.get('beats', []):
        row = _fraction(beat['at'], 'beat at') / step
        if not r0 <= row < r1 + 1:
            continue
        for note in _resolved_notes(song['score'], beat):
            fs = columns.get(note['channel'], set()) & {'note', 'instrument', 'volume'}
            if fs and (exact is None or note['id'] in exact):
                chosen.setdefault(beat['id'], set()).add(note['id'])
                masks[note['id']] = sorted(fs)
                resolved[note['id']] = note
    origin = min((_fraction(b['at'], 'beat at') / step for b in spec.get('beats', [])
                  if b['id'] in chosen), default=Fraction(r0)) if exact else Fraction(r0)
    score_clip = None
    if chosen:
        source = copy.deepcopy(song)
        ids = set(masks)
        occurrences = {oid for oid, name in zip(song['score']['order_ids'], song['orders'])
                       if str(name) == pattern.name}
        source['score']['ties'] = [tie for tie in source['score'].get('ties', [])
                                  if any(e['occurrence'] in occurrences and e['note'] in ids
                                         for e in tie.values())]
        if any(not all(e['occurrence'] in occurrences and e['note'] in ids for e in tie.values())
               for tie in source['score']['ties']):
            raise ValueError('native copy needs both selected tie endpoints')
        # Keep unselected source notes during validation, then filter the copied
        # beats. Only selected notes' ties may enter this native clipboard.
        score_clip = capture_score_clipboard(source, pattern.name, list(chosen), selection.get('occurrence'))
        earliest = min(_fraction(_beat(song['score'], pattern.name, bid)['at'], 'beat at') for bid in chosen)
        for beat in score_clip['beats']:
            beat.pop('chord', None)
            beat['at'] = _pair(_fraction(beat['at'], 'relative at') + earliest - origin * step)
            beat['notes'] = [n for n in beat['notes'] if n['id'] in chosen[beat['id']]]
            for note in beat['notes']:
                value = resolved[note['id']]
                note['channel'] = value['channel'] - first_channel
                note['instrument'] = value.get('instrument', _track(song['score'], beat)['instrument'])
                if value['string'] is not None:
                    note.update(string=value['string'], fret=value['fret'])
        for tie in score_clip['ties']:
            if any(tie[side] not in ids for side in ('from', 'to')):
                raise ValueError('native copy needs both selected tie endpoints')
    raw = []
    if exact is None:
        keys = ('note', 'instrument', 'volume', 'effect')
        for row in range(r0, r1 + 1):
            for ch, fs in columns.items():
                values = dict(zip(keys, format_cell(pattern.rows[row][ch]).split()))
                raw.append(dict(row=_pair(Fraction(row) - origin), channel=ch-first_channel,
                                fields={field: values[field] for field in fs}))
    return dict(version=1, kind='native-pattern', origin=_pair(origin), score=score_clip,
                masks=masks, raw=raw)


def paste_native_clipboard(song, raw_patterns, edit):
    """Paste exact authored notes and residual selected fields, or refuse atomically."""
    from types import SimpleNamespace
    if any(edit.get(mode) for mode in ('overwrite', 'mix', 'push', 'flood', 'overflow')):
        raise ValueError('native clipboard overwrite/mix/push/flood/overflow paste is not supported yet')
    clip = edit.get('clipboard')
    _keys(clip, ('version', 'kind', 'origin', 'score', 'masks', 'raw'), 'native clipboard')
    if clip.get('version') != 1 or clip.get('kind') != 'native-pattern':
        raise ValueError('unsupported native Pattern clipboard')
    pi = _int(edit.get('pattern'), 0, len(raw_patterns)-1, 'pattern index')
    pattern = raw_patterns[pi]
    row = _edit_row(edit.get('row'), len(pattern.rows), 'paste row')
    channel = _int(edit.get('channel'), 0, _channels(song)-1, 'paste channel')
    masks, residual = clip.get('masks'), clip.get('raw')
    if not isinstance(masks, dict) or not isinstance(residual, list) or len(residual) > 65536:
        raise ValueError('invalid native clipboard fields')
    result, raw = copy.deepcopy(song), copy.deepcopy(raw_patterns)
    fields = ('note', 'instrument', 'volume', 'effect')
    seen = set()
    for entry in residual:
        _keys(entry, ('row', 'channel', 'fields'), 'clipboard raw cell')
        at = row + _fraction(entry.get('row'), 'relative raw row')
        ch = channel + _int(entry.get('channel'), 0, 63, 'relative channel')
        if at.denominator != 1:
            raise ValueError('raw clipboard cells need integral destination rows; no rounding applied')
        r = _int(int(at), 0, len(pattern.rows)-1, 'destination row')
        _int(ch, 0, _channels(song)-1, 'destination channel')
        if (r, ch) in seen:
            raise ValueError('duplicate clipboard raw cell')
        seen.add((r, ch))
        patch = entry.get('fields')
        if not isinstance(patch, dict) or not patch or any(k not in fields for k in patch):
            raise ValueError('invalid clipboard raw field mask')
        parts = format_cell(raw[pi].rows[r][ch]).split()
        for field, value in patch.items():
            index = fields.index(field)
            if parts[index] != ('...', '..', '...', '...')[index] and parts[index] != value:
                raise ValueError('native paste destination is occupied; overwrite is not supported yet')
            parts[index] = value
        raw[pi].rows[r][ch] = parse_cell(' '.join(parts))
    score_clip = copy.deepcopy(clip.get('score'))
    if score_clip is not None:
        _keys(score_clip, ('version', 'beats', 'ties', 'track_kinds', 'track_specs'), 'score clipboard')
        beats = score_clip.get('beats')
        if not isinstance(beats, list) or not 1 <= len(beats) <= 1024:
            raise ValueError('native clipboard needs 1..1024 beats')
        _check_clipboard_track_kinds(result['score'], score_clip)
        step = Fraction(song.get('module', {}).get('speed', 6), 24)
        spec = result['score']['patterns'].setdefault(pattern.name, dict(row_step=_pair(step), beats=[]))
        additions, copied = [], set()
        for beat in beats:
            if beat.get('chord') is not None:
                raise ValueError('native Pattern clipboard cannot carry chord diagrams; copy whole beats instead')
            at = row * step + _fraction(beat.get('at'), 'relative beat at')
            notes = []
            for note in beat.get('notes', []):
                nid = note.get('id')
                fs = masks.get(nid)
                if (not isinstance(fs, list) or not fs or any(f not in fields[:3] for f in fs)
                        or nid in copied):
                    raise ValueError('invalid or duplicate native note field mask')
                copied.add(nid)
                note['channel'] = channel + _int(note.get('channel'), 0, 63, 'relative note channel')
                _int(note['channel'], 0, _channels(song)-1, 'destination note channel')
                destination = next((t for t in result['score']['tracks'].values()
                                    if note['channel'] in t['channels']), None)
                if destination is not None and is_percussion(destination) != is_percussion(_track(result['score'], beat)):
                    raise ValueError('pitched/percussion clipboard routing conversion is unsupported')
                targets = [(b, n) for b in spec['beats'] if _fraction(b['at'], 'beat at') == at
                           for n in _resolved_notes(result['score'], b) if n['channel'] == note['channel']]
                if 'note' in fs:
                    if targets:
                        raise ValueError('native paste destination is occupied; overwrite is not supported yet')
                    if 'instrument' not in fs:
                        note.pop('instrument', None)
                    if 'volume' not in fs:
                        note.pop('volume', None)
                    notes.append(note)
                else:
                    if len(targets) != 1:
                        raise ValueError('pasting score instrument/volume alone needs an exact destination note')
                    target_beat, target = targets[0]
                    actual = next(n for n in target_beat['notes'] if n['id'] == target['id'])
                    for field in fs:
                        if field in actual and actual[field] != note.get(field):
                            raise ValueError('native paste destination field is occupied; overwrite is not supported yet')
                        if field in note:
                            actual[field] = copy.deepcopy(note[field])
            if notes:
                beat['notes'] = notes
                additions.append(beat)
        if set(masks) != copied:
            raise ValueError('native clipboard has unmatched field masks')
        ties = score_clip.get('ties', [])
        new_ids = {n['id'] for b in additions for n in b['notes']}
        if any(t[side] not in new_ids for t in ties for side in ('from', 'to')):
            raise ValueError('native paste ties need both complete note fields')
        if additions:
            previous = {b['id'] for b in spec['beats']}
            score_clip['beats'] = additions
            result = paste_score_clipboard(result, SimpleNamespace(patterns=raw_patterns),
                                          pi, _pair(row), score_clip, edit.get('occurrence'))
            spec = result['score']['patterns'][pattern.name]
            for beat in list(spec['beats']):
                if beat['id'] in previous:
                    continue
                # Partial chords join a compatible existing beat; do not invent
                # a simultaneous second beat in the same voice.
                matches = [b for b in spec['beats'] if b is not beat and b['id'] in previous
                           and all(b.get(k) == beat.get(k) for k in ('at', 'track', 'voice', 'written', 'stem', 'duration_source', 'text',
                                                                    'stroke', 'pick_stroke'))]
                if len(matches) == 1:
                    matches[0]['notes'].extend(beat['notes'])
                    spec['beats'].remove(beat)
    elif masks:
        raise ValueError('native clipboard masks need score notes')
    checked = authoring_view(result, raw)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    groups = [(pi, [dict(row=r, ch=c, cell=format_cell(cell))
                    for r, cells in enumerate(raw[pi].rows) for c, cell in enumerate(cells)
                    if cell != raw_patterns[pi].rows[r][c]])]
    return (result['score'] if result['score'] != song['score'] else None), groups


def _check_clipboard_track_kinds(score, clipboard):
    kinds = clipboard.get('track_kinds')
    if kinds is not None and (not isinstance(kinds, dict) or len(kinds) > 64 or
                              any(v not in ('pitched', 'percussion') for v in kinds.values())):
        raise ValueError('score clipboard track_kinds must map tracks to pitched/percussion')
    for beat in clipboard['beats']:
        if not isinstance(beat, dict) or not isinstance(beat.get('track'), str):
            raise ValueError('score clipboard beat must name its source track')
        track = _track(score, beat)
        kind = 'percussion' if is_percussion(track) else 'pitched'
        if kinds is None:
            if kind == 'percussion':
                raise ValueError('percussion paste requires source clipboard track_kinds')
        elif kinds.get(beat['track']) != kind:
            raise ValueError('pitched/percussion clipboard track conversion is unsupported')


def _clipboard_beats(score, pattern, beat_ids):
    if not isinstance(pattern, str) or pattern not in score.get('patterns', {}):
        raise ValueError('score copy requires an existing score pattern name')
    if not isinstance(beat_ids, list) or not 1 <= len(beat_ids) <= 1024:
        raise ValueError('score copy selects 1..1024 complete beats')
    for identity in beat_ids:
        _id(identity, 'selected beat id')
    if len(set(beat_ids)) != len(beat_ids):
        raise ValueError('score copy contains duplicate beat IDs')
    selected = [copy.deepcopy(_beat(score, pattern, identity)) for identity in beat_ids]
    cohorts = _cohort_strokes(score['patterns'][pattern]['beats'])
    for beat in selected:
        beat.update(copy.deepcopy(cohorts[_cohort_key(beat)]))
    _stamp_cohorts(_beat_cohorts(selected))
    return selected


def _clipboard_tracks(score, beats):
    return {b['track']: dict(tuning=copy.deepcopy(score['tracks'][b['track']]['tuning']),
                            capo=score['tracks'][b['track']].get('capo', 0),
                            max_fret=score['tracks'][b['track']].get('max_fret', 29),
                            percussion=is_percussion(score['tracks'][b['track']])) for b in beats}


def remap_score_clipboard(song, clipboard, track_map):
    """Portable phrase -> destination instruments, using TG's closest-string/lowest-fret allocation.

    Explicit mapping owns routing: source instrument/channel overrides never cross it.
    The payload contains geometry, not source samples. Native preserves every pitch or
    refuses; TG may remove notes that cannot fit. Internal ties retain one string.
    """
    _keys(clipboard, ('version', 'beats', 'ties', 'track_kinds', 'track_specs'), 'score clipboard')
    if (not isinstance(clipboard.get('beats'), list) or not 1 <= len(clipboard['beats']) <= 1024 or
            any(not isinstance(b, dict) or not isinstance(b.get('track'), str) for b in clipboard['beats'])):
        raise ValueError('portable clipboard requires 1..1024 complete beats naming their source tracks')
    result = copy.deepcopy(clipboard)
    sources = {b['track'] for b in result['beats']}
    tracks = song.get('score', {}).get('tracks', {})
    if (not isinstance(track_map, dict) or set(track_map) != sources or
            any(not isinstance(t, str) or t not in tracks for t in track_map.values()) or
            len(set(track_map.values())) != len(track_map)):
        raise ValueError('clipboard track_map must map every source track to a distinct existing destination track')
    specs = result.get('track_specs')
    if not isinstance(specs, dict) or len(specs) > 64 or set(specs) != sources:
        raise ValueError('cross-track/song paste requires portable source track_specs; copy the phrase again')
    assigned, onsets, strings, old_notes = {}, {}, {}, {}
    source_beats = {source: [b for b in result['beats'] if b['track'] == source] for source in sources}
    for identity, destination in track_map.items():
        spec = specs[identity]
        _keys(spec, ('tuning', 'capo', 'max_fret', 'percussion'), 'clipboard track specification')
        tuning = spec.get('tuning')
        if not isinstance(tuning, list) or not 1 <= len(tuning) <= 25:
            raise ValueError('clipboard track tuning requires 1..25 strings')
        for pitch in tuning:
            _int(pitch, 0, 119, 'clipboard string pitch')
        capo = _int(spec.get('capo', 0), -24, 24, 'clipboard capo')
        _int(spec.get('max_fret', 29), 0, 36, 'clipboard maximum fret')
        percussion = spec.get('percussion')
        target = tracks[destination]
        if type(percussion) is not bool or percussion != is_percussion(target):
            raise ValueError('pitched/percussion clipboard track conversion is unsupported')
        kinds = result.get('track_kinds')
        if ((kinds is not None and (not isinstance(kinds, dict) or
                kinds.get(identity) != ('percussion' if percussion else 'pitched'))) or
                (percussion and (any(tuning) or capo))):
            raise ValueError('clipboard source track kind and geometry disagree')
        source = dict(tuning=tuning, capo=capo, max_fret=spec.get('max_fret', 29),
                      channels=list(range(len(tuning))))
        if percussion:
            source['midi'] = {'bank': 128}
        old_values = [p + capo for p in tuning]
        values = [p + target.get('capo', 0) for p in target['tuning']]
        top = target.get('max_fret', 29)
        strings[destination] = ([0] * len(values), 100) if percussion else (values, top)
        cohorts = {}
        for b in source_beats[identity]:
            cohorts.setdefault(Fraction(*b['at']), []).append(b)

        def fits(n, string, fret, old_string):
            if not 0 <= fret <= top:
                return False
            for effect in ('grace', 'trill'):
                if n.get(effect) is not None and (old_string is None or not 0 <=
                        old_values[old_string - 1] + n[effect]['fret'] - values[string - 1] <= top):
                    return False
            # Natural harmonics depend on the source open string and node fret.
            if (n.get('harmonic') or {}).get('type') == 'natural' and (
                    old_string is None or old_values[old_string - 1] != values[string - 1]):
                return False
            return True

        for at, members in cohorts.items():
            members.sort(key=lambda b: b.get('voice', 0))
            notes = [(b, n, resolved['string']) for b in members
                     for n, resolved in zip(b['notes'], _resolved_notes({'tracks': {identity: source}}, b))]
            free, chosen = set(range(1, len(values) + 1)), []
            for b, n, old_string in notes:
                n.pop('channel', None); n.pop('instrument', None)
                if percussion:
                    string, fret = _fingering(target, n, set(range(1, len(values) + 1)) - free)
                else:
                    distances = [abs(old_values[old_string - 1] - p) for p in values] if old_string else []
                    string = distances.index(min(distances)) + 1 if distances else None
                    fret = n['pitch'] - values[string - 1] if string else None
                if string not in free or (not percussion and not fits(n, string, fret, old_string)):
                    chosen = None
                    break
                chosen.append((string, fret)); free.remove(string)
            if chosen is None:
                if percussion:
                    raise ValueError(f'clipboard has more simultaneous drum notes than destination {destination} lanes')
                free, picks = set(range(1, len(values) + 1)), {}
                for i in sorted(range(len(notes)), key=lambda i: (notes[i][0].get('voice', 0), -notes[i][1]['pitch'])):
                    _, n, old_string = notes[i]
                    options = [(n['pitch'] - values[s - 1], s) for s in free
                               if fits(n, s, n['pitch'] - values[s - 1], old_string)]
                    if not options:
                        raise ValueError(f"clipboard cannot place note {n['id']} (pitch {n['pitch']}) on destination {destination}")
                    fret, string = min(options); free.remove(string); picks[i] = (string, fret)
                chosen = [picks[i] for i in range(len(notes))]
            for (b, n, old_string), (string, fret) in zip(notes, chosen):
                key = ('clipboard', n['id'])
                if key in assigned:
                    raise ValueError('score clipboard contains duplicate note IDs')
                assigned[key] = (string, fret, n['pitch'])
                onsets[key] = ('clipboard', at, destination)
                old_notes[key] = (n, old_string, old_values, target)
            for b in members:
                if old_values != values or percussion:
                    b.pop('chord', None)
                else:
                    try:
                        _validate_chord(b.get('chord'), target)
                    except ValueError:
                        b.pop('chord', None)
                b['track'] = destination
    tie_song = dict(orders=['clipboard'], score=dict(order_ids=['clipboard'], ties=[
        {side: dict(occurrence='clipboard', note=t[side]) for side in ('from', 'to')}
        for t in result.get('ties', [])]))
    _keep_tied_strings(tie_song, assigned, onsets, strings, 'clipboard paste')
    for key, (string, fret, pitch) in assigned.items():
        n, old_string, old_values, target = old_notes[key]
        n.pop('channel', None); n.pop('instrument', None)
        if not is_percussion(target):
            if (n.get('harmonic') or {}).get('type') == 'natural' and (
                    old_string is None or old_values[old_string - 1] !=
                    target['tuning'][string - 1] + target.get('capo', 0)):
                raise ValueError('clipboard tied fingering cannot preserve natural harmonic pitch')
            for effect in ('grace', 'trill'):
                if n.get(effect) is not None:
                    alternate = old_values[old_string - 1] + n[effect]['fret']
                    n[effect]['fret'] = alternate - target['tuning'][string - 1] - target.get('capo', 0)
                    if not 0 <= n[effect]['fret'] <= target.get('max_fret', 29):
                        raise ValueError('clipboard tied fingering cannot preserve grace/trill pitch')
        n.update(string=string, fret=fret)
    result['track_kinds'] = {t: 'percussion' if is_percussion(tracks[t]) else 'pitched' for t in track_map.values()}
    result['track_specs'] = _clipboard_tracks(song['score'], result['beats'])
    return result


def _clipboard_silences(selected, authored, measures):
    """Copy implicit source rests, without copying deliberately unselected beats.

    TG completes each source measure before storing whole beats. Offsets alone
    cannot retain silence in its sequential replacement operation. Complete only
    the selected lanes and retain rests whose starts fall inside the selection.
    """
    used = {b['id'] for b in selected}
    for track, voice in sorted({(b['track'], b.get('voice', 0)) for b in selected}):
        chosen = [Fraction(*b['at']) for b in selected if b['track'] == track]
        first, last = min(chosen), max(chosen)
        lane = sorted((b for b in authored if b['track'] == track and b.get('voice', 0) == voice),
                      key=lambda b: Fraction(*b['at']))
        for left, right in measures:
            if right <= first or left > last:
                continue
            cursor = left
            for beat in [*(b for b in lane if Fraction(*b['at']) < right and
                          Fraction(*b['at']) + duration_quarters(b['written']) > left), None]:
                stop = Fraction(*beat['at']) if beat else right
                if cursor < stop and cursor <= last and stop > first:
                    for written in _split_written(stop - cursor):
                        if first <= cursor <= last:
                            if len(selected) >= 1024:
                                raise ValueError('score copy selects 1..1024 complete beats including silence')
                            peers = [b for b in selected if b['track'] == track and Fraction(*b['at']) == cursor]
                            rank = min((b.get('cohort', 0) for b in peers), default=0)
                            identity = _local_id('copy_silence', used)
                            used.add(identity)
                            selected.append(dict(id=identity, track=track, voice=voice, at=_pair(cursor),
                                                 written=written, notes=[], **({'cohort': rank} if rank else {})))
                        cursor += duration_quarters(written)
                if beat:
                    cursor = max(cursor, Fraction(*beat['at']) + duration_quarters(beat['written']))


def capture_score_clipboard(song, pattern=None, beat_ids=None, occurrence=None, *, selection=None, raw_patterns=None,
                            complete_silence=False):
    """Copy selected beats into a self-contained JSON score clipboard (version 1).

Suggested request: {op: beats_copy, pattern: name, beats: [ids], occurrence?: id}.
Returns {version: 1, beats: [relative-at beat mappings], ties: [{from: note_id,
to: note_id}], track_kinds: {track_id: pitched|percussion}, track_specs: {track_id: geometry}}.
Geometry includes tuning/capo/max_fret/percussion, never source samples or channel bindings.
No source mutation, raw cells, order references or new IDs are
stored. Beat/note IDs inside the clipboard are local references only; paste
allocates fresh ones. Selection is bounded to 1024 complete beats.

The legacy pattern form keeps local IDs. The selection form supplies occurrence/
beat groups and raw_patterns, assigning distinct local IDs to each written visit.
Only ties with both endpoints selected are copied; a fragment starts and ends
independently of its source chain. Relative times follow written orders, not performed repeats.
Interactive copies also retain implicit_rests for sequential whole-beat paste;
span paste and internal sparse copies retain precisely the selected authored beats.
"""
    validate_score(song)
    score = song.get('score', {})
    if selection is not None:
        if raw_patterns is None:
            raise ValueError('score range copy requires the compiled pattern timeline')
        if not isinstance(selection, list) or not 1 <= len(selection) <= 1024:
            raise ValueError('score range copy requires 1..1024 occurrence selections')
        timeline = _score_timeline(song, raw_patterns)
        occurrences = {o['id']: o for o in timeline['occurrences']}
        selected, seen, note_map, used_beats, used_notes = [], set(), {}, set(), set()
        for visit, group in enumerate(selection):
            _keys(group, ('occurrence', 'beats'), 'score range selection')
            oid = _id(group.get('occurrence'), 'source occurrence')
            if oid not in occurrences or oid in seen:
                raise ValueError('score range copy needs distinct existing source occurrences')
            seen.add(oid)
            own = occurrences[oid]
            for beat in _clipboard_beats(score, own['pattern'], group.get('beats')):
                if len(selected) >= 1024:
                    raise ValueError('score copy selects 1..1024 complete beats')
                beat['at'] = _pair(Fraction(*own['at']) + Fraction(*beat['at']))
                beat['id'] = _local_id(f'visit{visit}_{beat["id"]}', used_beats)
                used_beats.add(beat['id'])
                for note in beat['notes']:
                    old = note['id']; note['id'] = _local_id(f'visit{visit}_{old}', used_notes)
                    used_notes.add(note['id']); note_map[oid, old] = note['id']
                selected.append(beat)
        edges = []
        for tie in score.get('ties', []):
            keys = [(tie[side]['occurrence'], tie[side]['note']) for side in ('from', 'to')]
            if not any(k in note_map for k in keys):
                continue
            if not all(k in note_map for k in keys):
                continue  # A copied fragment starts/ends independently of its source chain.
            edges.append(dict(zip(('from', 'to'), (note_map[k] for k in keys))))
        authored = [dict(b, at=_pair(Fraction(*o['at']) + Fraction(*b['at'])))
                    for o in timeline['occurrences'] for b in score['patterns'].get(o['pattern'], {}).get('beats', [])]
        measures = [(a, b) for a, b, _ in timeline['measures']] or [
            (Fraction(*o['at']), Fraction(*o['at']) + Fraction(*o['duration'])) for o in timeline['occurrences']]
        silences = []
        if complete_silence:
            completed = list(selected)
            _clipboard_silences(completed, authored, sorted(measures))
            silences = completed[len(selected):]
        origin = min(Fraction(*b['at']) for b in selected)
        for beat in [*selected, *silences]:
            beat['at'] = _pair(Fraction(*beat['at']) - origin)
        selected.sort(key=lambda b: (Fraction(*b['at']), b['track'], b.get('voice', 0), b['id']))
        return {'version': 1, 'beats': selected, 'ties': edges, **({'implicit_rests': silences} if silences else {}),
                'track_specs': _clipboard_tracks(score, selected),
                'track_kinds': {b['track']: 'percussion' if is_percussion(_track(score, b)) else 'pitched' for b in selected}}
    selected = _clipboard_beats(score, pattern, beat_ids)
    notes = {n['id'] for b in selected for n in b['notes']}
    occurrences = {oid for oid, name in zip(score['order_ids'], song['orders']) if str(name) == pattern}
    if occurrence is not None and occurrence not in occurrences:
        raise ValueError('score copy occurrence does not refer to the selected pattern')
    touching = [tie for tie in score.get('ties', []) if any(
        e['occurrence'] in occurrences and e['note'] in notes for e in tie.values())]
    if touching and occurrence is None:
        if len(occurrences) != 1:
            raise ValueError('score copy has occurrence-dependent ties; select the source occurrence explicitly')
        occurrence = next(iter(occurrences))
    edges = []
    for tie in touching:
        if not any(e['occurrence'] == occurrence and e['note'] in notes for e in tie.values()):
            continue
        if not all(e['occurrence'] == occurrence and e['note'] in notes for e in tie.values()):
            continue
        edges.append({'from': tie['from']['note'], 'to': tie['to']['note']})
    authored = score['patterns'][pattern]['beats']
    end = max(Fraction(*b['at']) + duration_quarters(b['written']) for b in authored)
    boundaries = {Fraction(0), end}
    for measure in score.get('measures', []):
        for edge in ('from', 'to'):
            anchor = measure[edge]
            if anchor['occurrence'] in occurrences:
                boundaries.add(Fraction(*anchor['at']))
    ordered = sorted(boundaries)
    silences = []
    if complete_silence:
        completed = list(selected)
        _clipboard_silences(completed, authored, list(zip(ordered, ordered[1:])))
        silences = completed[len(selected):]
    origin = min(_fraction(b['at'], 'beat at') for b in selected)
    for beat in [*selected, *silences]:
        beat['at'] = _pair(_fraction(beat['at'], 'beat at') - origin)
    selected.sort(key=lambda b: (_fraction(b['at'], 'beat at'), b['track'], b.get('voice', 0), b['id']))
    return {'version': 1, 'beats': selected, 'ties': edges, **({'implicit_rests': silences} if silences else {}),
            'track_specs': _clipboard_tracks(score, selected),
            'track_kinds': {b['track']: 'percussion' if is_percussion(_track(score, b)) else 'pitched'
                            for b in selected}}


def _check_paste_split_gates(song, raw, groups):
    """Compare split notation with the same pasted beats before bar-line splitting.

    Reuse the native gate calculation, including neighboring voice beats, tempo
    and ties. This reference exists only in memory; no overlong beat is saved.
    """
    if not groups:
        return
    actual = _score_timeline(song, raw)
    if not any(n.get('let_ring') for n in actual['records']):
        return
    reference = copy.deepcopy(actual)
    removed_beats, remap = set(), {}
    for original, pieces in groups:
        ids = [f"{oid}/{bid}" for oid, bid, _ in pieces]
        head = next(b for b in reference['beats'] if b['id'] == ids[0])
        head['written'] = copy.deepcopy(original['written'])
        head['end'] = head['start'] + duration_quarters(original['written'])
        removed_beats.update(ids[1:])
        for index, note in enumerate(original['notes']):
            first = pieces[0][0] + '/' + pieces[0][2][index]
            for oid, _, notes in pieces:
                remap[oid + '/' + notes[index]] = first
            record = reference['by_id'][first]
            record['end'] = head['end']
    reference['beats'] = [b for b in reference['beats'] if b['id'] not in removed_beats]
    reference['records'] = [n for n in reference['records'] if remap.get(n['id'], n['id']) == n['id']]
    reference['by_id'] = {n['id']: n for n in reference['records']}
    reference['outgoing'] = {remap.get(a, a): remap.get(b, b) for a, b in reference['outgoing'].items()
                             if remap.get(a, a) != remap.get(b, b)}
    reference['incoming'] = {b: a for a, b in reference['outgoing'].items()}
    tempo = song.get('module', {}).get('tempo', 125)
    clock = TempoClock(tempo, _raw_tempos(actual, raw, tempo))
    before, after = _performed_releases(reference, clock), _performed_releases(actual, clock)
    for identity, gate in before.items():
        if gate['let_ring'] and (gate['start'], gate['end']) != (after[identity]['start'], after[identity]['end']):
            raise ValueError(f'{identity}: pasted let-ring timing changes at a new bar line; '
                             'include its following beat or choose another destination')


def _paste_score_span(song, projection, pattern, row, clipboard, occurrence, *, replace, extend, mode='safe'):
    """Materialize one exact phrase across unique orders, retaining material outside its span."""
    if occurrence is None:
        raise ValueError('cross-measure paste requires an explicit destination occurrence')
    result = copy.deepcopy(song)
    raw = list(projection.raw_patterns if isinstance(projection, Projection) else projection.patterns)
    timeline = _score_timeline(result, raw)
    spans = timeline['occurrences']
    own = next(o for o in spans if o['id'] == occurrence)
    spec = result['score']['patterns'].get(own['pattern'])
    step = Fraction(*spec['row_step']) if spec else Fraction(result.get('module', {}).get('speed', 6), 24)
    origin = Fraction(*own['at']) + row * step
    finish = origin + max(Fraction(*b['at']) + duration_quarters(b['written']) for b in clipboard['beats'])
    extent = finish - origin
    lanes = {(b['track'], b.get('voice', 0)) for b in clipboard['beats']}
    needed = finish
    if mode == 'push':
        needed = max([finish, *(Fraction(*o['at']) + Fraction(*b['at']) + duration_quarters(b['written']) + extent
            for o in spans for b in result['score']['patterns'].get(o['pattern'], {}).get('beats', [])
            if (b['track'], b.get('voice', 0)) in lanes and
            Fraction(*o['at']) + Fraction(*b['at']) + duration_quarters(b['written']) > origin)])
    while needed > Fraction(*spans[-1]['at']) + Fraction(*spans[-1]['duration']):
        if not extend:
            raise ValueError('score paste exceeds the existing song; enable cross-measure paste')
        if len(result['orders']) >= 256:
            raise ValueError('score paste exceeds the 256 order limit')
        added = measure_command(result, dict(action='measure_add', at=len(result['orders']), count=1))
        result = added['song']
        for name, spec in added['created'].items():
            raw.append(Pattern(name, [[Cell() for _ in range(_channels(result))] for _ in range(spec['rows'])]))
        spans = _score_timeline(result, raw)['occurrences']
    score = result['score']
    by_oid = {o['id']: o for o in spans}
    touched = [o for o in spans if Fraction(*o['at']) < needed and
               Fraction(*o['at']) + Fraction(*o['duration']) > origin]
    for o in touched:
        if sum(str(name) == o['pattern'] for name in result['orders']) != 1:
            raise ValueError('cross-measure paste needs unique destination patterns; make every touched occurrence unique first')
        if result['patterns'][o['pattern']].get('approved'):
            raise ValueError(f"pattern '{o['pattern']}' is approved: clear its mark in the SONG tab first")
    used_b = {name: {b['id'] for b in p['beats']} for name, p in score['patterns'].items()}
    used_n = {name: {n['id'] for b in p['beats'] for n in b['notes']} for name, p in score['patterns'].items()}
    cuts = {Fraction(*o['at']) for o in spans}
    for m in score.get('measures', []):
        cuts.update(Fraction(*by_oid[m[side]['occurrence']]['at']) + Fraction(*m[side]['at'])
                    for side in ('from', 'to'))
    entries = [(o, b) for o in touched for b in list(score['patterns'].get(o['pattern'], {}).get('beats', []))]
    if mode in ('mix', 'push'):
        _require_single_cohorts(clipboard['beats'], mode.capitalize() + ' paste')
        for o in touched:
            _require_single_cohorts((b for b in score['patterns'].get(o['pattern'], {}).get('beats', [])
                                    if (b['track'], b.get('voice', 0)) in lanes), mode.capitalize() + ' paste')
    if _has_distinct_cohorts(clipboard['beats']) and any(
            origin + Fraction(*b['at']) < cut < origin + Fraction(*b['at']) + duration_quarters(b['written'])
            for b in clipboard['beats'] for cut in cuts):
        raise ValueError('Paste splitting does not yet preserve independent coincident beat groups; no changes applied')
    if mode == 'mix':
        for o, b in entries:
            if (b['track'], b.get('voice', 0)) in lanes:
                left = Fraction(*o['at']) + Fraction(*b['at'])
                cuts.update((left, left + duration_quarters(b['written'])))
        for b in clipboard['beats']:
            left = origin + Fraction(*b['at'])
            cuts.update((left, left + duration_quarters(b['written'])))
    generated, remap, split_groups = [], {}, []

    def materialize(original, start, end, *, retain=False, continuation=False, merge=False, source_offset=Fraction(0)):
        paths = {n['id']: [] for n in original['notes']}
        pieces = []
        if end - start != duration_quarters(original['written']) and any(
                n.get('bend') or n.get('tremolo_bar') for n in original['notes']):
            ids = set(paths)
            if any(edge['note'] in ids and by_oid[edge['occurrence']]['pattern'] ==
                   next((o['pattern'] for o, b in entries if b is original), None)
                   for tie in score.get('ties', []) for edge in tie.values()):
                raise ValueError('cropping a tied pitch curve needs its complete chain; include the tied beats')
        for index, (position, piece) in enumerate(_split_moved_beat(
                original, start, cuts, end=end, continuation=continuation, source_offset=source_offset,
                check_ring=mode != 'mix')):
            dest = next(o for o in spans if Fraction(*o['at']) <= position <
                        Fraction(*o['at']) + Fraction(*o['duration']))
            name = dest['pattern']
            spec = score['patterns'].setdefault(name, dict(row_step=_pair(step), beats=[]))
            used_b.setdefault(name, set()); used_n.setdefault(name, set())
            keep = retain and index == 0
            piece['id'] = original['id'] if keep else _local_id('copy_' + original['id'], used_b[name])
            used_b[name].add(piece['id'])
            piece['at'] = _pair(position - Fraction(*dest['at']))
            for n in piece['notes']:
                old = n['id']
                n['id'] = old if keep else _local_id('copy_' + old, used_n[name])
                used_n[name].add(n['id'])
                paths[old].append(dict(occurrence=dest['id'], note=n['id']))
            pieces.append((dest['id'], piece['id'], [n['id'] for n in piece['notes']]))
            cohort = next((b for b in spec['beats'] if b['track'] == piece['track'] and
                b.get('voice', 0) == piece.get('voice', 0) and b['at'] == piece['at']), None) if merge else None
            if cohort is None:
                spec['beats'].append(piece)
            else:
                if duration_quarters(cohort['written']) != duration_quarters(piece['written']):
                    raise ValueError('Mix paste needs compatible exact voice subdivisions')
                for key in ('text', 'chord', 'stroke', 'pick_stroke', 'stem'):
                    old, new = cohort.get(key), piece.get(key)
                    if old not in (None, '', 'auto') and new not in (None, '', 'auto') and old != new:
                        raise ValueError(f'Mix paste has conflicting {key}; choose Replace or another location')
                    if old in (None, '', 'auto') and new is not None:
                        cohort[key] = copy.deepcopy(new)
                cohort['notes'].extend(piece['notes'])
        for path in paths.values():
            generated.extend({'from': a, 'to': b} for a, b in zip(path, path[1:]))
        if len(pieces) > 1 and mode != 'mix' and end - start == duration_quarters(original['written']):
            split_groups.append((original, pieces))
        return paths

    for o, existing in entries:
        name, start = o['pattern'], Fraction(*o['at'])
        spec = score['patterns'].get(name)
        left = start + Fraction(*existing['at'])
        right = left + duration_quarters(existing['written'])
        if (existing['track'], existing.get('voice', 0)) not in lanes or right <= origin or left >= needed:
            continue
        if not replace and mode not in ('mix', 'push'):
            raise ValueError('cross-measure paste requires an empty destination span; use Paste replace')
        spec['beats'].remove(existing)
        if mode == 'mix':
            path = materialize(existing, left, right, retain=True)
            leading = trailing = path
        elif mode == 'push':
            leading = materialize(existing, left, origin, retain=True) if left < origin else {}
            trailing = materialize(existing, max(left, origin) + extent, right + extent, continuation=left < origin,
                                   source_offset=max(left, origin) - left)
            if left >= origin:
                leading = trailing
        else:
            leading = materialize(existing, left, origin, retain=True) if left < origin else {}
            trailing = materialize(existing, finish, right, retain=left >= origin, continuation=True,
                                   source_offset=finish - left) if right > finish else {}
        for n in existing['notes']:
            # Preserve incoming/outgoing ties only at the original exterior edge.
            remap[o['id'], n['id']] = (leading.get(n['id'], []), trailing.get(n['id'], []))
    old_ties = []
    for tie in score.get('ties', []):
        endpoints = {}
        for side, edge in tie.items():
            changed = remap.get((edge['occurrence'], edge['note']))
            path = changed[1 if side == 'from' else 0] if changed is not None else [edge]
            if path:
                endpoints[side] = path[-1 if side == 'from' else 0]
        if len(endpoints) == 2:
            old_ties.append(endpoints)
    copied, beat_ids = {}, set()
    for original in clipboard['beats']:
        bid = _id(original.get('id'), 'clipboard beat id')
        if bid in beat_ids:
            raise ValueError('score clipboard contains duplicate beat IDs')
        beat_ids.add(bid)
        notes = original.get('notes')
        if not isinstance(notes, list) or len(notes) > 25:
            raise ValueError('clipboard beat notes must be a list of at most 25')
        for n in notes:
            nid = _id(n.get('id'), 'clipboard note id')
            if nid in copied:
                raise ValueError('score clipboard contains duplicate note IDs')
            copied[nid] = None
        start = origin + Fraction(*original['at'])
        copied.update(materialize(original, start, start + duration_quarters(original['written']), merge=mode == 'mix'))
    for tie in clipboard.get('ties', []):
        _keys(tie, ('from', 'to'), 'clipboard tie')
        left, right = tie.get('from'), tie.get('to')
        if not isinstance(left, str) or not isinstance(right, str) or left not in copied or right not in copied:
            raise ValueError('score clipboard has a dangling/external tie; both endpoints must be copied notes')
        if left == right:
            raise ValueError('score clipboard tie cannot refer to itself')
        old_ties.append({'from': copied[left][-1], 'to': copied[right][0]})
    score['ties'] = old_ties + generated
    if mode == 'push':
        _repair_duration_ties(score, _score_timeline(result, raw))
    for name, original in song['score']['patterns'].items():
        before, after = _cohort_strokes(original['beats']), _cohort_strokes(score['patterns'][name]['beats'])
        retained = {b['id'] for b in score['patterns'][name]['beats']}
        for b in original['beats']:
            key = _cohort_key(b)
            if b['id'] in retained and before.get(key, {}) != after.get(key, {}):
                raise ValueError('replacement changes retained voice shared stroke/chord metadata; include both voices or edit that metadata first')
    validate_score(result)
    _check_paste_split_gates(result, raw, split_groups)
    checked = authoring_view(result, raw)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    if isinstance(projection, Projection):
        project_score(result, raw)
    return result


def _paste_tg_cohorts(song, projection, row, clipboard, occurrence, report=None):
    """TGTrackManager.replaceBeats, inside one unpublished, validated candidate.

    Reserve by minimum destination duration, replace both voices, then find the
    next cohort after the minimum source duration. Never reproduce TG's partial
    clear on failure or its invalid ties on a measure overflow.
    """
    raw = list(projection.raw_patterns if isinstance(projection, Projection) else projection.patterns)
    timeline = _score_timeline(song, raw)
    spans = timeline['occurrences']
    own = next((o for o in spans if o['id'] == occurrence), None)
    if own is None:
        raise ValueError('whole-beat paste requires an explicit destination occurrence')
    step = Fraction(*song['score']['patterns'][own['pattern']]['row_step'])
    origin = Fraction(*own['at']) + row * step
    measures = sorted((a, b) for a, b, _ in timeline['measures'])
    if not measures:
        measures = [(Fraction(*o['at']), Fraction(*o['at']) + Fraction(*o['duration'])) for o in spans]
    result = copy.deepcopy(song)
    score = result['score']
    inserted, selected = {}, []
    used_b = {name: {b['id'] for b in p['beats']} for name, p in score['patterns'].items()}
    used_n = {name: {n['id'] for b in p['beats'] for n in b['notes']} for name, p in score['patterns'].items()}
    source_ids, note_ids = set(), set()
    for beat in clipboard['beats']:
        bid = _id(beat.get('id'), 'clipboard beat id')
        if bid in source_ids:
            raise ValueError('score clipboard contains duplicate beat IDs')
        source_ids.add(bid)
        for note in beat['notes']:
            nid = _id(note.get('id'), 'clipboard note id')
            if nid in note_ids:
                raise ValueError('score clipboard contains duplicate note IDs')
            note_ids.add(nid)

    def bounds(at):
        found = next((m for m in measures if m[0] <= at < m[1]), None)
        if found is None:
            raise ValueError('whole-beat paste has insufficient room; no notes were cleared')
        return found

    for track in dict.fromkeys(b['track'] for b in clipboard['beats']):
        # A record keeps its original identity separately from temporary rests
        # and copied voices. Only affected measures are written back.
        records = [dict(at=Fraction(*o['at']) + Fraction(*b['at']), beat=copy.deepcopy(b),
                        original=(o['id'], b['id']), source=None)
                   for o in spans for b in score['patterns'].get(o['pattern'], {}).get('beats', [])
                   if b['track'] == track]

        def cohorts():
            groups = {}
            for record in records:
                groups.setdefault((record['at'], record['beat'].get('cohort', 0)), []).append(record)
            return [(at, group) for (at, rank), group in sorted(groups.items())]

        def complete(measure):
            left, right = measure
            present = [r for r in records if left <= r['at'] < right]
            voices = {r['beat'].get('voice', 0) for r in present} or {0}
            for voice in voices:
                cursor = left
                active = sorted((r for r in present if r['beat'].get('voice', 0) == voice), key=lambda r: r['at'])
                for record in [*active, None]:
                    stop = record['at'] if record else right
                    if cursor < stop:
                        for written in _split_written(stop - cursor):
                            peers = [r for r in records if r['at'] == cursor]
                            ranks = sorted({r['beat'].get('cohort', 0) for r in peers})
                            rank = next((rank for rank in ranks if not any(r['beat'].get('voice', 0) == voice
                                and r['beat'].get('cohort', 0) == rank for r in peers)), max(ranks, default=-1) + 1)
                            records.append(dict(at=cursor, original=None, source=None,
                                beat=dict(id='paste_rest', track=track, voice=voice, at=[0, 1], written=written, notes=[],
                                          **({'cohort': rank} if rank else {}))))
                            cursor += duration_quarters(written)
                    if record:
                        cursor = max(cursor, record['at'] + duration_quarters(record['beat']['written']))

        def clean(measure):
            left, right = measure
            groups = [(at, group) for at, group in cohorts() if left <= at < right]
            sounding = [(at, max(at + duration_quarters(r['beat']['written']) for r in group))
                        for at, group in groups if any(r['beat']['notes'] for r in group)]
            for at, group in groups:
                end = max(at + duration_quarters(r['beat']['written']) for r in group)
                if not any(r['beat']['notes'] for r in group) and any(at < b and end > a for a, b in sounding):
                    for record in group:
                        records.remove(record)

        for measure in measures:
            complete(measure)
        source = {}
        for beat in clipboard['beats']:
            if beat['track'] == track:
                source.setdefault((Fraction(*beat['at']), beat.get('cohort', 0)), []).append(beat)
        cursor = origin
        affected = set()
        for _, group in sorted(source.items()):
            available = [(at, cohort) for at, cohort in cohorts() if at >= cursor]
            if not available:
                raise ValueError('whole-beat paste has insufficient room; no notes were cleared')
            start, first = available[0]
            measure = bounds(start)
            maximum = max(duration_quarters(b['written']) for b in group)
            if start + maximum > measures[-1][1]:
                raise ValueError('whole-beat paste has insufficient room; no notes were cleared')
            if start + maximum > measure[1]:
                raise ValueError('whole-beat paste crosses a written measure; use Paste span for exact tied splitting')
            cleared, chosen = Fraction(0), []
            for at, cohort in available:
                chosen.extend(cohort)
                cleared += min(duration_quarters(r['beat']['written']) for r in cohort)
                affected.add(bounds(at))
                if cleared >= maximum:
                    break
            if cleared < maximum:
                raise ValueError('whole-beat paste has insufficient room; no notes were cleared')
            for record in chosen:
                record['beat']['notes'] = []
            for record in first:
                records.remove(record)
            for b in group:
                copied = copy.deepcopy(b)
                copied.pop('cohort', None)
                if first[0]['beat'].get('cohort', 0):
                    copied['cohort'] = first[0]['beat']['cohort']
                records.append(dict(at=start, beat=copied, original=None, source=b['id']))
            clean(measure)
            for changed in sorted(affected):
                complete(changed)
                clean(changed)
            cursor = start + min(duration_quarters(b['written']) for b in group)

        for o in spans:
            left = Fraction(*o['at'])
            affected_measures = [m for m in affected if m[0] < left + Fraction(*o['duration']) and m[1] > left]
            if not affected_measures:
                continue
            name = o['pattern']
            if sum(str(n) == name for n in result['orders']) != 1:
                raise ValueError('whole-beat paste needs unique destination patterns; make touched occurrences unique first')
            if result['patterns'][name].get('approved'):
                raise ValueError(f"pattern '{name}' is approved: clear its mark in the SONG tab first")
            spec = score['patterns'].setdefault(name, dict(row_step=_pair(step), beats=[]))
            used_b.setdefault(name, set()); used_n.setdefault(name, set())
            in_selected = lambda at: any(a <= at < b for a, b in affected_measures)
            spec['beats'] = [b for b in spec['beats'] if b['track'] != track or not in_selected(left + Fraction(*b['at']))]
            for record in records:
                at, beat = record['at'], copy.deepcopy(record['beat'])
                if not left <= at < left + Fraction(*o['duration']) or not in_selected(at):
                    continue
                if at + duration_quarters(beat['written']) > left + Fraction(*o['duration']):
                    raise ValueError('whole-beat paste crosses a backing pattern; use Paste span for exact tied splitting')
                beat['at'] = _pair(at - left)
                if record['original'] is None:
                    beat['id'] = _local_id('copy_' + beat['id'], used_b[name]); used_b[name].add(beat['id'])
                    for note in beat['notes']:
                        old = note['id']
                        note['id'] = _local_id('copy_' + old, used_n[name]); used_n[name].add(note['id'])
                        inserted[old] = dict(occurrence=o['id'], note=note['id'])
                    if record['source'] is not None:
                        selected.append((at, o['id'], beat))
                spec['beats'].append(beat)
    retained = {(o['id'], n['id']) for o in spans for b in score['patterns'].get(o['pattern'], {}).get('beats', []) for n in b['notes']}
    score['ties'] = [tie for tie in score.get('ties', []) if all((e['occurrence'], e['note']) in retained for e in tie.values())]
    for tie in clipboard.get('ties', []):
        _keys(tie, ('from', 'to'), 'clipboard tie')
        if any(tie.get(side) not in inserted for side in ('from', 'to')) or tie['from'] == tie['to']:
            raise ValueError('score clipboard has a dangling/external tie; both endpoints must be copied notes')
        score['ties'].append({side: inserted[tie[side]] for side in ('from', 'to')})
    validate_score(result)
    checked = authoring_view(result, raw)
    if checked['conflicts']:
        raise ValueError(checked['conflicts'][0]['message'])
    if isinstance(projection, Projection):
        project_score(result, raw)
    if report is not None and len({b['track'] for b in clipboard['beats']}) == 1:
        selected.sort(key=lambda r: (r[0], r[2].get('voice', 0)))
        groups = {}
        for _, oid, beat in selected:
            groups.setdefault(oid, []).append(beat['id'])
        _, oid, first = selected[0]
        report['selection'] = dict(occurrence=oid, track=first['track'], voice=first.get('voice', 0),
            at=first['at'], beats=groups[oid], range=[dict(occurrence=k, beats=v) for k, v in groups.items()])
    return result


def paste_score_clipboard(song, projection, pattern, to_row, clipboard, occurrence=None, *, across=False, replace=False,
                          track_map=None, mode=None, voice_map=None, independent=False, report=None):
    """Paste score beats into an existing pattern, returning an immutable candidate.

Suggested edit: {op: beats_paste, pattern: compiled_index, row: integer_or_pair,
clipboard: capture_result, occurrence?: id}. Every paste allocates fresh IDs;
exact relative starts, durations, voices, fingering and note properties survive.
Raw source fields are untouched. Caller MUST compile against raw_patterns before
persisting, to refuse collisions/timing/capacity problems in one transaction.
across=True extends the song with compatible measures and splits crossing beats
exactly with ties. Every touched destination pattern must be unique. Legacy
single-pattern pastes retain their shared-pattern behavior. No external ties are
inferred and no source measure headers or raw fields are copied.
replace=True replaces the copied track/voice lanes over the phrase extent,
including gaps, retaining exterior beat fragments and repairing boundary ties.
The second argument needs only .patterns; pass the native backing Module for
exact timing. Projection callers retain the strict IT grid check.
Explicit track_map maps every source track to a distinct destination, preserving
sounding pitch and reassigning playable frets and destination audio routing.
mode safe|replace|mix|push selects empty-only, replacement, additive chords or
insertion shifting the affected voice lanes. These explicit native mix/push modes
do not claim TG's replaceBeats behavior. voice_map maps string keys '0'/'1' to
destination voice integers, retaining internal ties. Unmapped voices stay unchanged.
tg_replace replaces entire two-voice cohorts using TG's reserve/advance rules;
unsafe measure overflow and insufficient room refuse the whole transaction.
"""
    if type(independent) is not bool:
        raise ValueError('independent must be boolean')
    if independent:
        ids = song['score']['order_ids']
        if occurrence not in ids:
            raise ValueError('independent paste needs an existing destination occurrence')
        raw = projection.raw_patterns if isinstance(projection, Projection) else projection.patterns
        song, raw = independent_score_occurrences(song, raw, ids[ids.index(occurrence):])
        projection = Module(patterns=raw)
        name = str(song['orders'][ids.index(occurrence)])
        pattern = next(i for i, p in enumerate(raw) if p.name == name)
    validate_score(song)
    if type(across) is not bool:
        raise ValueError('across must be a boolean')
    if type(replace) is not bool:
        raise ValueError('replace must be a boolean')
    if mode is None:
        mode = 'replace' if replace else 'safe'
    if mode not in ('safe', 'replace', 'mix', 'push', 'tg_replace') or (replace and mode not in ('replace', 'tg_replace')):
        raise ValueError('paste mode must be safe, replace, mix, push or tg_replace; do not combine conflicting modes')
    replace = mode == 'replace'
    _int(pattern, 0, len(projection.patterns) - 1, 'pattern index')
    rows = len(projection.patterns[pattern].rows)
    to_row = _edit_row(to_row, rows + int(across), 'paste row')
    if to_row > rows:
        raise ValueError('paste row exceeds the destination pattern')
    _keys(clipboard, ('version', 'beats', 'ties', 'track_kinds', 'track_specs', 'implicit_rests'), 'score clipboard')
    _int(clipboard.get('version'), 1, 1, 'clipboard version')
    if 'implicit_rests' in clipboard:
        clipboard = copy.deepcopy(clipboard)
        silences = clipboard.pop('implicit_rests')
        if (not isinstance(silences, list) or len(silences) > 1024 or
                any(not isinstance(b, dict) or b.get('notes') != [] for b in silences)):
            raise ValueError('clipboard implicit rests must be a bounded list of empty beats')
        if mode == 'tg_replace' and isinstance(clipboard.get('beats'), list):
            clipboard['beats'].extend(silences)
    beats, ties = clipboard.get('beats'), clipboard.get('ties', [])
    if not isinstance(beats, list) or not 1 <= len(beats) <= 1024:
        raise ValueError('score clipboard requires 1..1024 complete beats')
    if not isinstance(ties, list) or len(ties) > 25600:
        raise ValueError('score clipboard ties must be a bounded list')
    if track_map is not None:
        clipboard = remap_score_clipboard(song, clipboard, track_map)
        beats, ties = clipboard['beats'], clipboard.get('ties', [])
    if voice_map is not None:
        if (not isinstance(voice_map, dict) or not voice_map or
                any(k not in ('0', '1') or type(v) is not int or v not in (0, 1) for k, v in voice_map.items())):
            raise ValueError("voice_map maps '0'/'1' to voice 0 or 1")
        present = {b.get('voice', 0) for b in beats}
        mapped = {v: voice_map.get(str(v), v) for v in present}
        if len(set(mapped.values())) != len(mapped):
            raise ValueError('voice_map cannot collapse both copied voices into one')
        clipboard = copy.deepcopy(clipboard)
        for b in clipboard['beats']:
            b['voice'] = mapped[b.get('voice', 0)]
        beats, ties = clipboard['beats'], clipboard.get('ties', [])
    _check_clipboard_track_kinds(song.get('score', {}), clipboard)
    name = projection.patterns[pattern].name
    if name not in _pattern_names(song):
        raise ValueError('score paste requires an existing destination pattern')
    result = copy.deepcopy(song)
    score = result.setdefault('score', _new_score(result))
    step = Fraction(_int(song.get('module', {}).get('speed', 6), 1, 255, 'module.speed'), 24)
    spec = score['patterns'].setdefault(name, {'row_step': _pair(step), 'beats': []})
    step = _fraction(spec['row_step'], 'row_step', True)
    occurrences = {oid for oid, n in zip(score['order_ids'], song['orders']) if str(n) == name}
    if occurrence is not None and occurrence not in occurrences:
        raise ValueError('score paste occurrence does not refer to the destination pattern')
    # Reserve even removed identities: replacement is a new pasted phrase.
    used_beats = {n: {b['id'] for b in p['beats']} for n, p in score['patterns'].items()}
    used_notes = {n: {v['id'] for b in p['beats'] for v in b['notes']} for n, p in score['patterns'].items()}
    # Preserve established single-pattern paste (including its shared-pattern
    # semantics). Occurrence routing is needed only when the phrase extends out.
    ends = []
    for b in beats:
        relative = _fraction(b.get('at'), 'clipboard relative position')
        if relative < 0:
            raise ValueError('clipboard relative position must not be negative')
        _int(b.get('voice', 0), 0, 1, 'clipboard voice')
        ends.append(relative + duration_quarters(b.get('written')))
    extent = max(ends)
    if mode == 'tg_replace':
        return _paste_tg_cohorts(song, projection, to_row, clipboard, occurrence, report)
    crosses_measure = across and any(
        endpoint['occurrence'] == occurrence and
        any(to_row * step + Fraction(*b['at']) < Fraction(*endpoint['at']) <
            to_row * step + Fraction(*b['at']) + duration_quarters(b['written']) for b in beats)
        for measure in score.get('measures', []) for endpoint in (measure['from'], measure['to']))
    if mode != 'safe' or crosses_measure or (across and to_row * step + extent > len(projection.patterns[pattern].rows) * step):
        return _paste_score_span(song, projection, pattern, to_row, clipboard, occurrence, replace=replace,
                                 extend=across, mode=mode)
    if ties:
        if len(occurrences) != 1:
            raise ValueError('pasting internal ties needs one destination occurrence; make the pattern unique first')
        occurrence = next(iter(occurrences))
    beat_map, note_map = {}, {}
    for original in beats:
        if not isinstance(original, dict):
            raise ValueError('clipboard beat must be a mapping')
        old_id = _id(original.get('id'), 'clipboard beat id')
        if old_id in beat_map:
            raise ValueError('score clipboard contains duplicate beat IDs')
        beat = copy.deepcopy(original)
        relative = _fraction(beat.get('at'), 'clipboard relative position')
        at = to_row * step + relative
        target, target_pattern, target_occurrence = name, pattern, occurrence
        used_beats.setdefault(target, {b['id'] for b in spec['beats']})
        used_notes.setdefault(target, {n['id'] for b in spec['beats'] for n in b['notes']})
        beat['id'] = _local_id(f'copy_{old_id}', used_beats[target])
        beat_map[old_id] = beat['id']
        used_beats[target].add(beat['id'])
        end = at + duration_quarters(beat.get('written'))
        if isinstance(projection, Projection) and ((at / step).denominator != 1 or (end / step).denominator != 1):
            raise ValueError('score paste timing is not representable on the destination grid; no rounding applied')
        if end > len(projection.patterns[target_pattern].rows) * step:
            raise ValueError('a pasted beat crosses the destination pattern boundary; align its start or split it before copying')
        beat['at'] = _pair(at)
        notes = beat.get('notes')
        if not isinstance(notes, list) or len(notes) > 25:
            raise ValueError('clipboard beat notes must be a list of at most 25')
        for note in notes:
            if not isinstance(note, dict):
                raise ValueError('clipboard note must be a mapping')
            old_note = _id(note.get('id'), 'clipboard note id')
            if old_note in note_map:
                raise ValueError('score clipboard contains duplicate note IDs')
            note['id'] = _local_id(f'copy_{old_note}', used_notes[target])
            note_map[old_note] = {'occurrence': target_occurrence, 'note': note['id']}
            used_notes[target].add(note['id'])
        spec['beats'].append(beat)
    for tie in ties:
        _keys(tie, ('from', 'to'), 'clipboard tie')
        left, right = tie.get('from'), tie.get('to')
        if not isinstance(left, str) or not isinstance(right, str) or left not in note_map or right not in note_map:
            raise ValueError('score clipboard has a dangling/external tie; both endpoints must be copied notes')
        if left == right:
            raise ValueError('score clipboard tie cannot refer to itself')
        score.setdefault('ties', []).append({'from': note_map[left], 'to': note_map[right]})
    validate_score(result)
    return result


def transfer_score_voice(song, raw_patterns, edit):
    """Move/copy selected complete beats to the other voice as one native transaction."""
    from types import SimpleNamespace
    _keys(edit, ('action', 'track', 'from_voice', 'to_voice', 'copy', 'mode', 'selection',
                 'occurrence', 'beats', 'voice', 'at', 'notes', 'revision'), 'transfer_voice')
    source_voice = _int(edit.get('from_voice', edit.get('voice', 0)), 0, 1, 'source voice')
    target_voice = _int(edit.get('to_voice', 1 - source_voice), 0, 1, 'destination voice')
    if source_voice == target_voice:
        raise ValueError('voice transfer needs a different destination voice')
    copying = edit.get('copy', False)
    if type(copying) is not bool:
        raise ValueError('voice transfer copy must be boolean')
    mode = edit.get('mode', 'safe')
    if mode not in ('safe', 'replace', 'mix'):
        raise ValueError('voice transfer mode must be safe, replace or mix')
    timeline = _score_timeline(song, raw_patterns)
    visits = {o['id']: o for o in timeline['occurrences']}
    groups = edit.get('selection') or [dict(occurrence=edit.get('occurrence'), beats=edit.get('beats'))]
    # Capture validates occurrence/beat identities before filtering the active voice.
    capture_score_clipboard(song, selection=groups, raw_patterns=raw_patterns)
    records, selected = [], []
    for group in groups:
        own = visits[group['occurrence']]
        beats = [_beat(song['score'], own['pattern'], identity) for identity in group['beats']]
        if any(b['track'] != edit.get('track') for b in beats):
            raise ValueError('voice transfer selection must belong to the selected track')
        beats = [b for b in beats if b.get('voice', 0) == source_voice]
        if beats:
            selected.append(dict(occurrence=own['id'], beats=[b['id'] for b in beats]))
        records.extend((own, b, Fraction(*own['at']) + Fraction(*b['at'])) for b in beats)
    if not records:
        raise ValueError('the selected source voice has no beats')
    _unique_range(song, records)
    clip = capture_score_clipboard(song, selection=selected, raw_patterns=raw_patterns)
    first = min(records, key=lambda r: r[2])
    start = first[2]
    stop = start + max(Fraction(*b['at']) + duration_quarters(b['written']) for b in clip['beats'])
    if mode == 'safe':
        for own in visits.values():
            for beat in song['score']['patterns'].get(own['pattern'], {}).get('beats', []):
                at = Fraction(*own['at']) + Fraction(*beat['at'])
                if beat['track'] == edit['track'] and beat.get('voice', 0) == target_voice and beat['notes'] and (
                        at < stop and at + duration_quarters(beat['written']) > start):
                    raise ValueError('destination voice contains notes; choose Mix or Replace explicitly')
    candidate = copy.deepcopy(song)
    removed = []
    if not copying:
        gone = {(o['id'], n['id']) for o, b, _ in records for n in b['notes']}
        removed = [t for t in candidate['score'].get('ties', [])
                   if any((e['occurrence'], e['note']) in gone for e in t.values())]
        candidate['score']['ties'] = [t for t in candidate['score'].get('ties', []) if t not in removed]
        for own, beat, _ in records:
            candidate['score']['patterns'][own['pattern']]['beats'] = [
                b for b in candidate['score']['patterns'][own['pattern']]['beats'] if b['id'] != beat['id']]
    else:
        # Independent simultaneous copies need another playable string/channel.
        track = song['score']['tracks'][edit['track']]
        held = []
        for own in visits.values():
            for b in song['score']['patterns'].get(own['pattern'], {}).get('beats', []):
                if b['track'] == edit['track']:
                    at = Fraction(*own['at']) + Fraction(*b['at'])
                    held.extend((at, at + duration_quarters(b['written']), n['string'])
                                for n in _resolved_notes(song['score'], b) if n['string'] is not None)
        assigned, onsets = {}, {}
        for b in clip['beats']:
            at = start + Fraction(*b['at']); end = at + duration_quarters(b['written'])
            used = {s for left, right, s in held if left < end and at < right}
            for n, resolved in zip(b['notes'], _resolved_notes(song['score'], b)):
                string, fret = _fingering(track, {'pitch': n['pitch']}, used)
                if string is None:
                    raise ValueError(f"voice copy cannot place note {n['id']} on a free string; move it instead")
                old_string = resolved['string']
                if (n.get('harmonic') or {}).get('type') == 'natural' and string != old_string:
                    raise ValueError('voice copy cannot relocate a natural harmonic; move it instead')
                for effect in ('grace', 'trill'):
                    if n.get(effect) is not None:
                        n[effect]['fret'] += track['tuning'][old_string - 1] - track['tuning'][string - 1]
                n.update(string=string, fret=fret)
                n.pop('channel', None)
                used.add(string); held.append((at, end, string))
                assigned['clipboard', n['id']] = (string, fret, n['pitch'])
                onsets['clipboard', n['id']] = ('clipboard', at, edit['track'])
        # A continuation must use its copied head's assignment; the final validator
        # checks occupancy against the retained original voice, too.
        tied = dict(orders=['clipboard'], score=dict(order_ids=['clipboard'], ties=[
            {side: dict(occurrence='clipboard', note=t[side]) for side in ('from', 'to')} for t in clip['ties']]))
        values = [p + track.get('capo', 0) for p in track['tuning']]
        _keep_tied_strings(tied, assigned, onsets, {edit['track']: (values, track.get('max_fret', 29))}, 'voice copy')
        for b in clip['beats']:
            for n in b['notes']:
                string, fret, _ = assigned['clipboard', n['id']]
                if n['string'] != string and any(n.get(e) is not None for e in ('grace', 'trill')):
                    raise ValueError('voice copy tied fingering cannot preserve grace/trill pitch')
                n.update(string=string, fret=fret)
    own, beat, _ = first
    pi = next(i for i, p in enumerate(raw_patterns) if p.name == own['pattern'])
    step = Fraction(*song['score']['patterns'][own['pattern']]['row_step'])
    candidate = paste_score_clipboard(candidate, SimpleNamespace(patterns=raw_patterns), pi,
        _pair(Fraction(*beat['at']) / step), clip, own['id'], across=True,
        mode='replace' if mode == 'safe' else mode, voice_map={str(source_voice): target_voice})
    selected = []
    for visit in visits.values():
        ids = [b['id'] for b in candidate['score']['patterns'].get(visit['pattern'], {}).get('beats', [])
               if b['track'] == edit['track'] and b.get('voice', 0) == target_voice and
               start <= Fraction(*visit['at']) + Fraction(*b['at']) < stop]
        if ids:
            selected.append(dict(occurrence=visit['id'], beats=ids))
    return candidate, dict(transferred=len(records), copied=copying, removed_ties=removed,
        selection=dict(occurrence=own['id'], track=edit['track'], voice=target_voice, at=beat['at'],
                       beats=selected[0]['beats'], range=selected))


def move_beat(song, projection, pattern, beat_id, to_row):
    """Move a complete untied chord/rest, preserving every beat/note identity.

The second argument needs only .patterns (a native backing Module is accepted).
``pattern`` is its index; ``to_row`` is an integer or rational pair. All notes retain
their exact written duration, channels, pitches, instruments and fingering. Raw
effects/automation stay at their existing rows; no raw fields are copied/moved.
A beat containing any tied note is refused. The caller compiles the candidate to
check destination voice/channel/raw-command conflicts before one atomic save.
"""
    _int(pattern, 0, len(projection.patterns) - 1, 'pattern index')
    to_row = _edit_row(to_row, len(projection.patterns[pattern].rows), 'destination row')
    _id(beat_id, 'beat id')
    validate_score(song)
    name = projection.patterns[pattern].name
    score = song.get('score', {})
    source = _beat(score, name, beat_id)
    note_ids = {note['id'] for note in source['notes']}
    occurrences = {oid for oid, n in zip(score['order_ids'], song['orders']) if str(n) == name}
    if any(endpoint['occurrence'] in occurrences and endpoint['note'] in note_ids
           for tie in score.get('ties', []) for endpoint in tie.values()):
        raise ValueError('moving a beat with a tied note requires an explicit tie edit; remove or reshape the tie first')
    step = _fraction(score['patterns'][name]['row_step'], 'row_step', True)
    at = to_row * step
    if at + duration_quarters(source['written']) > len(projection.patterns[pattern].rows) * step:
        raise ValueError('moved beat would cross the pattern boundary; split its written duration and use a tie')
    moved = copy.deepcopy(source)
    moved.update(copy.deepcopy(_cohort_strokes(score['patterns'][name]['beats'])[_cohort_key(source)]))
    moved['at'] = _pair(at)
    return apply_score_edit(song, {'op': 'beat_set', 'pattern': name, 'beat': moved})


def move_note(song, projection, pattern, note_id, to_row, pitch=None):
    """Move an untied single-note beat with stable IDs and exact written duration.

The second argument needs only .patterns (a native backing Module is accepted).
``pattern`` is an index; ``to_row`` is an integer or rational pair. Optional
pitch uses the usual deterministic fingering repair. Partial chords and tied notes
need explicit musical operations and are refused. The caller compiles the candidate
before persisting it, which checks destination voice/channel/raw-command conflicts.
"""
    _int(pattern, 0, len(projection.patterns) - 1, 'pattern index')
    _edit_row(to_row, len(projection.patterns[pattern].rows), 'destination row')
    _id(note_id, 'note id')
    if pitch is not None:
        _int(pitch, 0, 119, 'note pitch')
    validate_score(song)
    name = projection.patterns[pattern].name
    score = song.get('score', {})
    spec = score.get('patterns', {}).get(name)
    if spec is None:
        raise ValueError(f'{name}: no score note {note_id}')
    source = next((beat for beat in spec['beats'] if any(n['id'] == note_id for n in beat['notes'])), None)
    if source is None:
        raise ValueError(f'{name}: unknown score note {note_id}')
    if len(source['notes']) != 1:
        raise ValueError('moving one chord note is unsupported; split it into a separate beat/voice first')
    result = move_beat(song, projection, pattern, source['id'], to_row)
    if pitch is not None:
        result = apply_score_edit(result, {'op': 'note_set', 'pattern': name, 'beat': source['id'],
                                          'note': {'id': note_id, 'pitch': pitch}})
    return result


def _release_moves(song, projection, groups):
    """Recognize only unambiguous complete release moves, never infer note moves."""
    changes = {}
    for pi, cells in groups:
        _int(pi, 0, len(projection.patterns) - 1, 'pattern index')
        pattern = projection.patterns[pi]
        for cell in cells:
            row = _int(cell.get('row'), 0, len(pattern.rows) - 1, 'row')
            ch = _int(cell.get('ch'), 0, len(pattern.rows[row]) - 1, 'channel')
            address = (pi, row, ch)
            if address in changes:
                raise ValueError('duplicate cell edits must be combined before score translation')
            changes[address] = parse_cell(cell.get('cell', ''))
    deleting_score_note = any(cell.note is None and
        projection.owners.get((*address, 'note'), {}).get('role') == 'attack'
        for address, cell in changes.items())
    adding_raw_note = any(cell.note is not None and 0 <= cell.note <= 119 and
        (*address, 'note') not in projection.owners and
        cell.note != projection.patterns[address[0]].rows[address[1]][address[2]].note
        for address, cell in changes.items())
    if deleting_score_note and adding_raw_note:
        raise ValueError('ambiguous score-note deletion with raw-note insertion: use note_move to preserve identity; '
                         'mixed Pattern cut/paste is unsupported')
    moved, handled = set(), set()
    for address, new in changes.items():
        owner = projection.owners.get((*address, 'note'))
        if not owner or owner['role'] != 'release' or new.note == NOTE_OFF:
            continue
        if new.note is not None:
            raise ValueError('generated note-off: edit the score duration/tie instead')
        attacks = [a[:3] for a, o in projection.owners.items() if a[3] == 'note' and
                   o['role'] == 'attack' and o['pattern'] == owner['pattern'] and o['note'] == owner['note']]
        if len(attacks) == 1 and attacks[0] in changes and changes[attacks[0]].note is None:
            moved.add(address)  # A ROLL delete removes attack and derived release together.
            continue
        key = (owner['pattern'], owner['beat'])
        if key in handled:
            continue
        handled.add(key)
        pi = address[0]
        if projection.patterns[pi].name != owner['pattern']:
            raise ValueError('moving a cross-pattern release requires an explicit tie edit')
        beat = _beat(song['score'], *key)
        expected = {a[:3] for a, o in projection.owners.items() if a[3] == 'note' and
                    o['role'] == 'release' and (o['pattern'], o['beat']) == key}
        if len(expected) != len(beat['notes']):
            raise ValueError('chord duration edit requires explicit beat resize; some releases coincide with attacks')
        targets = []
        for source in expected:
            if source not in changes or changes[source].note is not None:
                raise ValueError('chord duration edit must move all generated note-offs atomically')
            possible = [a for a, cell in changes.items() if a[0] == pi and a[2] == source[2] and
                        cell.note == NOTE_OFF and projection.patterns[a[0]].rows[a[1]][a[2]].note is None and
                        (*a, 'note') not in projection.owners and a not in moved]
            if len(possible) != 1:
                raise ValueError('generated note-off: provide exactly one new release per chord channel')
            targets.append(possible[0])
        if len({a[1] for a in targets}) != 1:
            raise ValueError('chord duration edit must give every note the same end row')
        song = resize_beat(song, projection, pi, owner['beat'], targets[0][1])
        moved.update(expected)
        moved.update(targets)
    return song, moved


def score_view(song, projection):
    """A JSON-serializable snapshot; caller may add its own document revision."""
    return {'score': copy.deepcopy(song.get('score')), 'positions': copy.deepcopy(projection.positions),
            'raw_positions': raw_note_view(song, projection), 'diagnostics': list(projection.diagnostics)}


def raw_note_view(song, projection):
    """Read-only previews of residual attacks, with no fabricated score identities.

Each record has pattern/index/name, row, ch, pitch, source='raw', editable=False,
track/string/fret when assignable, at/duration/written when inferable, and reason.
Use {pattern,row,ch} to select explicit promotion; never send these to note_set.
These are notation hints, not inferred audible note lengths. No state is changed.
"""
    tracks = song.get('score', {}).get('tracks', {})
    step = Fraction(song.get('module', {}).get('speed', 6), 24)
    timing_known = not any(c.effect in (1, 2, 3) or c.effect == 19 and c.param >> 4 in (6, 11, 14)
                           for p in projection.patterns for row in p.rows for c in row)
    result = []
    for pi, pattern in enumerate(projection.raw_patterns):
        for row, cells in enumerate(pattern.rows):
            for ch, cell in enumerate(cells):
                if cell.note is None or not 0 <= cell.note <= 119 or (pi, row, ch, 'note') in projection.owners:
                    continue
                track_id = next((name for name, track in tracks.items() if ch in track['channels']), None)
                string, fret = _fingering(tracks[track_id], {'pitch': cell.note, 'channel': ch}) if track_id else (None, None)
                end = next((r for r in range(row + 1, len(pattern.rows))
                            if projection.patterns[pi].rows[r][ch].note is not None), None)
                entry = dict(pattern=pi, pattern_name=pattern.name, row=row, ch=ch, pitch=cell.note,
                             source='raw', editable=False, track=track_id, string=string, fret=fret,
                             at=_pair(row * step) if timing_known else None, duration=None, written=None)
                if not timing_known:
                    entry['reason'] = 'raw timing/flow commands require an exact timing map'
                elif end is None:
                    entry['reason'] = 'unknown duration: no following note boundary in this pattern'
                else:
                    entry['end_row'] = end
                    entry['duration'] = _pair((end - row) * step)
                    if projection.patterns[pi].rows[end][ch].note not in (*range(120), NOTE_OFF):
                        entry['reason'] = 'cut/fade boundary requires explicit notation'
                    else:
                        try:
                            entry['written'] = _written_for((end - row) * step)
                            entry['reason'] = 'duration inferred from tracker boundary; adopt to edit notation'
                        except ValueError:
                            entry['reason'] = 'duration needs multiple tied written values'
                result.append(entry)
    return result


def native_raw_note_view(song, raw_patterns, *, view=None, occurrence=None):
    """Occurrence-addressed raw previews bounded by exact raw AND score parent-note events.

Raw row remains an integer source address. end_row, at and duration are rational
pairs; occurrence identifies the played context. Boundary hints do not describe
audible decay/NNA tails. Unplayed patterns retain visible source notes but no
inferred duration. No Projection or rounded score cells are constructed.
"""
    view = authoring_view(song, raw_patterns) if view is None else view
    if occurrence is not None and occurrence not in {o['id'] for o in view['occurrences']}:
        raise ValueError('raw preview: unknown occurrence')
    tracks, step = song['score']['tracks'], Fraction(*view['row_step'])
    timing_known = not any(c.effect in (1, 2, 3, 20) or c.effect == 19 and c.param >> 4 in (6, 11, 14)
                           for p in raw_patterns for row in p.rows for c in row)
    result = []
    for pi, pattern in enumerate(raw_patterns):
        uses = [o for o in view['occurrences'] if o['pattern'] == pattern.name]
        if not uses:
            uses = [None]
        for use in uses:
            oid = use['id'] if use else None
            positions = [p for p in view['positions'] if p['kind'] == 'note' and p['occurrence'] == oid]
            for row, cells in enumerate(pattern.rows):
                for ch, cell in enumerate(cells):
                    if cell.note is None or not 0 <= cell.note <= 119:
                        continue
                    track_id = next((name for name, track in tracks.items() if ch in track['channels']), None)
                    string, fret = _fingering(tracks[track_id], {'pitch': cell.note, 'channel': ch}) if track_id else (None, None)
                    entry = dict(pattern=pi, pattern_name=pattern.name, occurrence=oid, row=row, ch=ch,
                                 pitch=cell.note, source='raw', editable=False, track=track_id,
                                 string=string, fret=fret, at=_pair(row * step), duration=None, written=None,
                                 adoptable=False)
                    boundaries = [(Fraction(r), 'raw_note_off' if c.note == NOTE_OFF else
                                   'raw_attack' if c.note < 120 else 'raw_cut_fade')
                                  for r in range(row + 1, len(pattern.rows))
                                  if (c := pattern.rows[r][ch]).note is not None]
                    for position in positions:
                        if position['ch'] != ch:
                            continue
                        if not position['tied_in'] and Fraction(*position['row']) > row:
                            boundaries.append((Fraction(*position['row']), 'score_attack'))
                        if not position['tied_out'] and Fraction(*position['end_row']) > row:
                            boundaries.append((Fraction(*position['end_row']), 'score_release'))
                    if track_id is not None and is_percussion(tracks[track_id]) and not 1 <= cell.note <= 100:
                        entry['reason'] = 'percussion key outside authored range 1..100'
                    elif not timing_known:
                        entry['reason'] = 'raw timing/flow commands require an exact timing map'
                    elif use is None:
                        entry['reason'] = 'unplayed pattern: choose a played occurrence for boundary inference'
                    elif not boundaries:
                        entry['reason'] = 'unknown duration: no following note boundary in this pattern'
                    else:
                        end, boundary = min(boundaries)
                        entry.update(end_row=_pair(end), duration=_pair((end - row) * step), boundary=boundary)
                        if boundary == 'raw_cut_fade':
                            entry['reason'] = 'cut/fade boundary requires explicit notation'
                        else:
                            try:
                                entry['written'] = _written_for((end - row) * step)
                                entry['reason'] = 'notation boundary from raw/score events; audible tails are not inferred'
                                if boundary == 'raw_note_off':
                                    entry['adoptable'] = True
                                elif boundary in ('raw_attack', 'score_attack'):
                                    entry['reason'] += '; adoption needs an explicit raw note-off to preserve NNA'
                            except ValueError:
                                entry['reason'] = 'duration needs multiple tied written values'
                    result.append(entry)
    shared = {}
    for entry in result:
        shared.setdefault((entry['pattern'], entry['row'], entry['ch']), []).append(entry)
    for peers in shared.values():
        first = peers[0]
        if any((p.get('end_row'), p.get('boundary')) != (first.get('end_row'), first.get('boundary')) for p in peers[1:]):
            for entry in peers:
                entry['adoptable'] = False
                entry['reason'] = 'occurrence-dependent boundaries: make the pattern unique before adoption'
    return [p for p in result if occurrence is None or p['occurrence'] == occurrence]


def tg_quarter_tempo(value, base, dotted):
    """TGTempo.setValueBase: the quarter tempo TuxGuitar plays for `value` beats of `base` (dotted) per minute."""
    quarter = value * 4 // base
    return 3 * quarter // 2 if dotted else quarter


def measure_errors(song, rows):
    """TGMeasureManager.getMeasureErrors' duration checks per bar, track and voice: a gap before or between written
    beats is 'gap' (VOICE_DISCONTINUOUS), a voice ending before its meter does is 'short' (VOICE_TOO_SHORT), after it
    'long' (VOICE_TOO_LONG: an overfull bar left by free-edit mode). Overlapping voices cannot be stored here. Bars are
    the measure entries inside one order, or every order when the song has none (`rows`: pattern name to rows). An
    empty voice is no error, as in TG."""
    score = song['score']
    orders, ids = [str(o) for o in song.get('orders', [])], score.get('order_ids', [])
    pattern_of, speed = dict(zip(ids, orders)), Fraction(song.get('module', {}).get('speed', 6), 24)
    measures = score.get('measures') or []
    if measures:
        bars = [(m['from']['occurrence'], Fraction(*m['from']['at']), Fraction(*m['to']['at']),
                 Fraction(*m['from']['at']) + Fraction(4 * m['meter'][0], m['meter'][1])) for m in measures
                if m['from']['occurrence'] == m['to']['occurrence']]
    else:
        def length(name):
            spec = score['patterns'].get(name)
            return rows.get(name, 0) * (_fraction(spec['row_step'], 'row_step', True) if spec else speed)
        bars = [(oid, Fraction(0), length(name), length(name)) for oid, name in zip(ids, orders)]
    found = []
    for number, (oid, a, b, nominal) in enumerate(bars, 1):
        beats = score['patterns'].get(pattern_of.get(oid), {}).get('beats', [])
        for track, voice in sorted({(x['track'], x['voice']) for x in beats}):
            spans = sorted((Fraction(*x['at']), duration_quarters(x['written'])) for x in beats
                           if x['track'] == track and x['voice'] == voice and a <= Fraction(*x['at']) < b)
            errors, end, discontinuous = [], a, False
            for at, duration in spans:
                if at > end and 'gap' not in errors:
                    errors.append('gap')
                if at > end and end > a:
                    discontinuous = True
                end = max(end, at + duration)
            if spans and end < nominal:
                errors.append('short')
            elif spans and end > nominal:
                errors.append('long')
            if errors:
                found.append(dict(bar=number, occurrence=oid, track=track, voice=voice, errors=errors,
                                  at=_pair(a), end=_pair(b), automatic_free=bool(measures) and
                                  ('short' in errors or 'long' in errors or discontinuous)))
    return found


def _automatic_free(song, raw_patterns, occurrence, track, at):
    """TG invalid-bar mode for authored bars; an empty voice is valid."""
    return any(e['automatic_free'] and e['occurrence'] == occurrence and e['track'] == track
               and Fraction(*e['at']) <= at < Fraction(*e['end'])
               for e in measure_errors(song, {p.name: len(p.rows) for p in raw_patterns}))


MEASURE_ACTIONS = ('measure_add', 'measure_remove', 'measure_clean', 'measure_paste', 'measure_meter', 'measure_move',
                   'measure_unique', 'prepare_measures')


def independent_score_occurrences(song, raw_patterns, occurrences):
    """Detach explicitly requested reused occurrences without changing their identities or raw source."""
    result, raw = copy.deepcopy(song), list(raw_patterns)
    ids, orders = result['score']['order_ids'], result['orders']
    if any(oid not in ids for oid in occurrences):
        raise ValueError('independent editing needs existing occurrence identities')
    used = set(map(str, result['patterns']))
    by_name = {p.name: p for p in raw}
    for oid in dict.fromkeys(occurrences):
        index = ids.index(oid)
        old = str(orders[index])
        if sum(str(n) == old for n in orders) < 2:
            continue
        if result['patterns'][old].get('approved'):
            raise ValueError(f"pattern '{old}' is approved: clear its mark in the SONG tab first")
        name = _local_id(old + '_independent', used)
        used.add(name)
        result['patterns'][name] = copy.deepcopy(result['patterns'][old])
        if old in result['score']['patterns']:
            result['score']['patterns'][name] = copy.deepcopy(result['score']['patterns'][old])
        clone = copy.deepcopy(by_name[old]); clone.name = name
        raw.append(clone); by_name[name] = clone
        orders[index] = name
    return result, raw


def prepare_score_measures(song, raw_patterns=None):
    """Exact native bar isolation; the returned candidate alone owns the remapped source."""
    if raw_patterns is None:
        if any(p.get('data') or p.get('automation') for p in song['patterns'].values()):
            raise ValueError('preparing measures with tracker data needs the compiled residual patterns')
        raw_patterns = [Pattern(str(n), [[Cell() for _ in range(_channels(song))] for _ in range(p['rows'])])
                        for n, p in song['patterns'].items()]
    timeline = _score_timeline(song, raw_patterns)
    measures = sorted(timeline['measures'], key=lambda m: m[0])
    if (not measures or measures[0][0] != 0 or measures[-1][1] != timeline['duration'] or
            any(a[1] != b[0] for a, b in zip(measures, measures[1:]))):
        raise ValueError('Prepare measures needs complete, contiguous authored bar coverage')
    if len(measures) > 256:
        raise ValueError('Prepare measures exceeds the 256 order limit')
    step = timeline['step']
    bounds = [a for a, _, _ in measures]
    if any((x / step).denominator != 1 for a, b, _ in measures for x in (a, b)):
        raise ValueError('Prepare measures needs bar boundaries on exact tracker rows')
    result = copy.deepcopy(song)
    score = result['score']
    used_names, used_ids = set(map(str, result['patterns'])), set(score['order_ids'])
    source_raw = {p.name: p for p in raw_patterns}
    spans = timeline['occurrences']
    flat = []
    for own in spans:
        pattern = source_raw[own['pattern']]
        start, end = Fraction(*own['at']), Fraction(*own['at']) + Fraction(*own['duration'])
        unchanged = sum(str(n) == own['pattern'] for n in song['orders']) == 1 and any(
            a == start and b == end for a, b, _ in measures)
        if not unchanged:
            entry = song['patterns'][own['pattern']]
            if entry.get('approved'):
                raise ValueError(f"pattern '{own['pattern']}' is approved: clear its mark in the SONG tab first")
            extra = set(entry) - {'rows', 'data', 'by', 'approved'}
            if extra:
                raise ValueError(f"Prepare measures needs literal raw patterns; {own['pattern']} has {', '.join(sorted(extra))}")
        if pattern.lanes or any(c.effect in (2, 3) or c.effect == 19 and c.param >> 4 == 11
                                for row in pattern.rows for c in row):
            raise ValueError('Prepare measures refuses tracker jumps, breaks, pattern loops and automation')
        flat.extend(copy.deepcopy(pattern.rows))
    orders, ids, origins, created, remap, split_ties, used, used_notes = [], [], [], {}, {}, [], {}, {}
    for index, (start, end, measure) in enumerate(measures):
        own_index = next(i for i, o in enumerate(spans) if Fraction(*o['at']) <= start <
                         Fraction(*o['at']) + Fraction(*o['duration']))
        own = spans[own_index]
        rows = int((end - start) / step)
        if not 1 <= rows <= 200:
            raise ValueError('Prepare measures needs 1..200 exact tracker rows per bar')
        whole = start == Fraction(*own['at']) and end - start == Fraction(*own['duration'])
        old = own['pattern']
        if result['patterns'][old].get('approved') and (not whole or sum(str(n) == old for n in song['orders']) > 1):
            raise ValueError(f"pattern '{old}' is approved: clear its mark in the SONG tab first")
        name = old if whole and sum(str(n) == old for n in song['orders']) == 1 else _local_id('measure', used_names)
        used_names.add(name)
        oid = own['id'] if start == Fraction(*own['at']) else _fresh_id(used_ids)
        used_ids.add(oid)
        origins.append(own_index if start == Fraction(*own['at']) else None)
        orders.append(name); ids.append(oid)
        if name != old:
            data = flat[int(start / step):int(end / step)]
            entry = dict(rows=rows, data=''.join(f"{i:02d}: {' | '.join(format_cell(c) for c in row)}\n"
                         for i, row in enumerate(data) if any(not c.is_empty() for c in row)))
            if song['patterns'][old].get('by'):
                entry['by'] = song['patterns'][old]['by']
            result['patterns'][name] = entry
            created[name] = dict(rows=rows, clone=None)
        score['patterns'][name] = dict(row_step=_pair(step), beats=[])
        used[name] = set()
        used_notes[name] = set()
        measure = copy.deepcopy(measure)
        measure['from'], measure['to'] = dict(occurrence=oid, at=[0, 1]), dict(occurrence=oid, at=_pair(end - start))
        score['measures'][index] = measure
    for own in spans:
        for original in song['score']['patterns'].get(own['pattern'], {}).get('beats', []):
            paths = {n['id']: [] for n in original['notes']}
            for position, beat in _split_moved_beat(original, Fraction(*own['at']) + Fraction(*original['at']), bounds, check_ring=True):
                index = max(i for i, start in enumerate(bounds) if start <= position)
                name, oid = orders[index], ids[index]
                beat['at'] = _pair(position - bounds[index])
                beat['id'] = _local_id(beat['id'], used[name]); used[name].add(beat['id'])
                for note in beat['notes']:
                    old = note['id']; note['id'] = _local_id(old, used_notes[name]); used_notes[name].add(note['id'])
                    paths[old].append(dict(occurrence=oid, note=note['id']))
                score['patterns'][name]['beats'].append(beat)
            for old, path in paths.items():
                remap[own['id'], old] = path
                split_ties.extend({'from': a, 'to': b} for a, b in zip(path, path[1:]))
    score['ties'] = [{side: copy.deepcopy(remap[t[side]['occurrence'], t[side]['note']][0 if side == 'to' else -1])
                     for side in ('from', 'to')} for t in song['score'].get('ties', [])] + split_ties
    score['order_ids'], result['orders'] = ids, orders
    deleted = [n for n in dict.fromkeys(map(str, song['orders'])) if n not in orders]
    for name in deleted:
        result['patterns'].pop(name, None)
        score['patterns'].pop(name, None)
    validate_score(result)
    _check_reflow_gates(song, result, remap, raw_patterns)
    changed = [n for n in song['score']['patterns'] if score['patterns'].get(n) != song['score']['patterns'][n]]
    return dict(song=result, orders=orders, origins=origins, created=created, resized={}, deleted=deleted, changed=changed,
                source_spans=[int(Fraction(*o['at']) / step) for o in spans],
                source_bars=[(int(a / step), int(b / step)) for a, b, _ in measures],
                bar_origins=list(range(len(measures))),
                removed_ties=[], report=f'Prepared {len(measures)} independent measures; sounding timing retained.')


def measure_units(song):
    """TuxGuitar's measures as whole order occurrences, in order: [{pattern, occurrence, rows, row_step, length,
    measure}]. Native imports write one pattern and one order per measure; a measure entry that divides a pattern or
    spans orders refuses, since adding or removing it would mean moving tracker rows inside a pattern."""
    score = song['score']
    orders, ids = [str(o) for o in song.get('orders', [])], list(score.get('order_ids', []))
    if any(o in ('+++', '---') for o in orders):
        raise ValueError('measure editing needs an order list without +++/--- markers')
    speed = Fraction(song.get('module', {}).get('speed', 6), 24)
    units = []
    for name, oid in zip(orders, ids):
        raw = song['patterns'].get(name)
        if not isinstance(raw, dict) or type(raw.get('rows')) is not int:
            raise ValueError(f'pattern {name} needs rows: to edit its measures')
        spec = score['patterns'].get(name)
        step = _fraction(spec['row_step'], 'row_step', True) if spec else speed
        units.append(dict(pattern=name, occurrence=oid, rows=raw['rows'], row_step=step, length=raw['rows'] * step,
                          measure=None))
    by_occurrence = {u['occurrence']: u for u in units}
    for m in score.get('measures', []):
        u = by_occurrence.get(m['from']['occurrence'])
        if (u is None or m['to']['occurrence'] != u['occurrence'] or Fraction(*m['from']['at']) != 0 or
                Fraction(*m['to']['at']) != u['length'] or u['measure'] is not None):
            raise ValueError(f"measure {m['id']} divides a pattern or spans orders. Measure editing works on songs with "
                             'one measure per order, as imported tabs are; use the Pattern tab for this song')
        u['measure'] = m
    return units


def measure_segment(song, first, last, track=None, copy_markers=False, *, independent=False, raw_patterns=None):
    """Detached, portable native measures. None selects all tracks; raw tracker cells are not portable."""
    if type(independent) is not bool:
        raise ValueError('independent must be boolean')
    if independent:
        song = prepare_score_measures(song, raw_patterns)['song']
    validate_score(song)
    units = measure_units(song)
    first = _int(first, 0, len(units) - 1, 'first measure')
    last = _int(last, first, len(units) - 1, 'last measure')
    if type(copy_markers) is not bool:
        raise ValueError('copy_markers must be boolean')
    score = song['score']
    tracks = list(score['tracks']) if track is None else [track]
    if any(t not in score['tracks'] for t in tracks):
        raise ValueError('Copy measures needs existing tracks')
    selected, included = [], set()
    for index, unit in enumerate(units[first:last + 1]):
        pattern = score['patterns'].get(unit['pattern'], {})
        beats = copy.deepcopy([b for b in pattern.get('beats', []) if b['track'] in tracks])
        for beat in beats:
            for original, resolved in zip(beat['notes'], _resolved_notes(score, beat)):
                original.update({k: resolved[k] for k in ('string', 'fret') if resolved.get(k) is not None})
                included.add((unit['occurrence'], original['id']))
        header = copy.deepcopy(unit['measure'])
        if header is not None:
            for key in ('id', 'from', 'to', *(() if copy_markers else ('marker',))):
                header.pop(key, None)
            if 'staff' in header:
                header['staff'] = {t: v for t, v in header['staff'].items() if t in tracks}
        selected.append(dict(rows=unit['rows'], row_step=_pair(unit['row_step']), beats=beats, measure=header))
    by_occurrence = {u['occurrence']: i for i, u in enumerate(units[first:last + 1])}
    ties = [{side: dict(unit=by_occurrence[e['occurrence']], note=e['note']) for side, e in tie.items()}
            for tie in score.get('ties', []) if all((e['occurrence'], e['note']) in included for e in tie.values())]
    specs = {t: dict(tuning=list(score['tracks'][t]['tuning']), capo=score['tracks'][t].get('capo', 0),
                     max_fret=score['tracks'][t].get('max_fret', 29), percussion=is_percussion(score['tracks'][t]))
             for t in tracks}
    return dict(version=1, tracks=tracks, track_specs=specs, all_tracks=track is None, units=selected, ties=ties)


def measure_command(song, edit, raw_last=None, raw_patterns=None):
    """TuxGuitar's Measure menu (Add, Remove, Clean, Paste) on whole-order measures, as one candidate.

    Measures are numbered by order (0-based here). measure_add {at, count} inserts empty measures before `at`
    (TGSongManager.addNewMeasure: a copy of the previous measure's meter and swing, or the first's at the start; no
    marker, repeat or ending). measure_remove {from, to} removes those measures in every track and their time; removing
    them all refuses, as TG ignores it. measure_clean {from, to, track} removes the track's beats there
    (TGMeasureManager.cleanMeasure). measure_paste {at, count, mode: replace|insert, segment, track} pastes a Copy
    segment: replace overwrites the copied tracks' beats from `at`, adding measures at the end when needed; insert puts
    new measures before `at` (TGSongSegmentHelper). A one-track segment pastes into `track`. A measure plays its
    pattern, so an edit to a pattern used at other orders changes them too, as every pattern edit does; the report
    names them. Removed or separated tie endpoints lose their link; surviving notes play normally.
    measure_move {from, to, at} moves a whole passage before the original order boundary `at` (0..order count),
    carrying its raw cells, measure headers and occurrence IDs. A destination inside the passage is unchanged.
    measure_unique {from, to} clones shared patterns for those occurrences, preserving occurrence IDs and ties.
    Portable measure_segment payloads reallocate copied notes into destination `track_map` instruments. Paste's
    copy_headers (insert default true, replace false) copies meter, swing, repeats, endings, line breaks and staff;
    replacement requires all destination tracks. copy_markers independently replaces markers (default false).
    Raw tracker cells and tempo-unit notation are not transferred by portable segments.
    measure_meter {at, meter, to_end?} is TG's time signature change (TGSongManager.changeTimeSignature): the
    measure, or it and every later one, gets the meter; bar lines move and every note of every track keeps its time,
    flowing into the bar it now falls in, with bars added at the end as TG adds them. It refuses, changing nothing,
    when a pattern from there on plays elsewhere, when those bars hold tracker commands (`raw_last`: pattern name to
    the last row with a residual tracker cell) or mixed grids. Crossing notes split into exactly spelled tied
    fragments; head effects retain their full tied duration. Strums and let-ring split when their actual
    attack spacing and gates stay unchanged. Slide cuts, changed neighboring let-ring gates and changed
    performed tick durations refuse with the affected part/beat and a boundary remedy.

    Returns {song, orders, origins, created: {name: {rows, clone}}, resized: {name: rows}, deleted: [names],
    changed: [names], report}.
    """
    action = edit.get('action')
    if 'independent' in edit and type(edit['independent']) is not bool:
        raise ValueError('independent must be boolean')
    if action == 'prepare_measures' or edit.get('independent'):
        prepared = prepare_score_measures(song, raw_patterns)
        if action == 'prepare_measures':
            return prepared
        raw_last = dict(raw_last or {})
        for n in prepared['created']:
            raw_last[n] = max((int(line.split(':', 1)[0]) for line in prepared['song']['patterns'][n]['data'].splitlines()),
                              default=-1)
        prepared_raw = None
        if raw_patterns is not None:
            by_name = {p.name: p for p in raw_patterns}
            rows = [row for name in song['orders'] for row in by_name[str(name)].rows]
            prepared_raw = [Pattern(name, rows[a:b]) for name, (a, b) in
                            zip(prepared['song']['orders'], prepared['source_bars'])]
            played = set(prepared['song']['orders'])
            prepared_raw.extend(p for p in raw_patterns if p.name in prepared['song']['patterns'] and p.name not in played)
        plan = measure_command(prepared['song'], {k: v for k, v in edit.items() if k != 'independent'}, raw_last, prepared_raw)
        plan['bar_origins'] = list(plan['origins'])
        plan['source_spans'], plan['source_bars'] = prepared['source_spans'], prepared['source_bars']
        plan['origins'] = [prepared['origins'][i] if i is not None else None for i in plan['origins']]
        plan['report'] = prepared['report'] + ' ' + plan['report']
        return plan
    edit = {k: v for k, v in edit.items() if k != 'independent'}
    _keys(edit, ('action', 'at', 'count', 'from', 'to', 'track', 'mode', 'segment', 'meter', 'to_end', 'revision',
                 'track_map', 'copy_headers', 'copy_markers'), action)
    result = copy.deepcopy(song)
    score = result['score']
    units = measure_units(result)
    n = len(units)
    if not n:
        raise ValueError('the song has no orders to edit')
    orders = [u['pattern'] for u in units]
    ids = [u['occurrence'] for u in units]
    origins = list(range(n))
    measures = list(score.get('measures', []))
    created, resized, report, removed_ties = {}, {}, [], []
    used_patterns = set(map(str, result['patterns'])) | set(score['patterns'])
    used_occurrences = set(ids)
    used_measures = {m['id'] for m in measures}

    def fresh(prefix, used):
        i = 1
        while f'{prefix}{i}' in used:
            i += 1
        used.add(f'{prefix}{i}')
        return f'{prefix}{i}'

    def span():
        a = _int(edit.get('from'), 0, n - 1, 'first measure')
        return a, _int(edit.get('to'), a, n - 1, 'last measure')

    def length_of(name):
        spec = score['patterns'].get(name)
        step = _fraction(spec['row_step'], 'row_step', True) if spec else Fraction(result['module'].get('speed', 6), 24)
        return result['patterns'][name]['rows'], step

    def header(m, keep):
        return None if m is None else {k: copy.deepcopy(v) for k, v in m.items() if k in keep}

    def insert(at, specs):
        for k, spec in enumerate(specs):
            name, oid = fresh('bar', used_patterns), fresh('occ_', used_occurrences)
            created[name] = dict(rows=spec['rows'], clone=spec.get('clone'))
            result['patterns'][name] = dict(rows=spec['rows'], data='')
            score['patterns'][name] = dict(row_step=_pair(spec['row_step']), beats=spec.get('beats', []))
            orders.insert(at + k, name)
            ids.insert(at + k, oid)
            origins.insert(at + k, None)
            if spec.get('measure') is not None:
                measures.append(dict(spec['measure'], id=fresh('m', used_measures),
                                     **{'from': dict(occurrence=oid, at=[0, 1]),
                                        'to': dict(occurrence=oid, at=_pair(spec['rows'] * spec['row_step']))}))

    def clear(names, tracks, what):
        """Remove the tracks' beats and incident ties; surviving continuations become attacks."""
        gone = {(name, n['id']) for name in names for b in score['patterns'].get(name, {}).get('beats', [])
                if b['track'] in tracks for n in b['notes']}
        pattern_of = dict(zip(ids, orders))
        kept = []
        for tie in score.get('ties', []):
            ends = [(pattern_of.get(tie[side]['occurrence']), tie[side]['note']) in gone for side in ('from', 'to')]
            (removed_ties if any(ends) else kept).append(tie)
        score['ties'] = kept
        for name in names:
            if name in score['patterns']:
                score['patterns'][name]['beats'] = [b for b in score['patterns'][name]['beats'] if b['track'] not in tracks]

    def shared(names, inside):
        others = sorted({name for name in names if orders.count(name) > inside.count(name)})
        if others:
            report.append(f"pattern{'s' * (len(others) > 1)} {', '.join(others)} also play{'s' * (len(others) == 1)} "
                          'at other orders: those measures changed too')

    if action == 'measure_add':
        at = _int(edit.get('at'), 0, n, 'insert position')
        count = _int(edit.get('count', 1), 1, 100, 'measure count')
        t = units[at - 1] if at else units[0]
        insert(at, [dict(rows=t['rows'], row_step=t['row_step'], measure=header(t['measure'], ('meter', 'swing')))
                    for _ in range(count)])
        report.append(f"Added {count} measure{'s' * (count > 1)} at {at + 1}.")
    elif action == 'measure_remove':
        a, b = span()
        if a == 0 and b == n - 1:
            raise ValueError('Removing every measure is refused, as in TuxGuitar: keep at least one')
        gone = set(ids[a:b + 1])
        kept = []
        for tie in score.get('ties', []):
            ends = [tie[side]['occurrence'] in gone for side in ('from', 'to')]
            (removed_ties if any(ends) else kept).append(tie)
        score['ties'] = kept
        measures = [m for m in measures if m['from']['occurrence'] not in gone]
        del orders[a:b + 1], ids[a:b + 1], origins[a:b + 1]
        report.append(f"Removed measure{'s' * (b > a)} {a + 1}{f'–{b + 1}' * (b > a)}.")
    elif action == 'measure_move':
        a, b = span()
        at = _int(edit.get('at'), 0, n, 'move destination')
        if a <= at <= b + 1:
            report.append('Measures already at that position.')
        else:
            destination = at - (b - a + 1) if at > b else at
            for values in (orders, ids, origins):
                passage = values[a:b + 1]
                del values[a:b + 1]
                values[destination:destination] = passage
            report.append(f"Moved measure{'s' * (b > a)} {a + 1}{f'–{b + 1}' * (b > a)} "
                          f"to {destination + 1}.")
    elif action == 'measure_unique':
        a, b = span()
        for i in range(a, b + 1):
            old = orders[i]
            if orders.count(old) <= 1:
                continue
            name = fresh('bar', used_patterns)
            created[name] = dict(rows=result['patterns'][old]['rows'], clone=old)
            result['patterns'][name] = copy.deepcopy(result['patterns'][old])
            if old in score['patterns']:
                score['patterns'][name] = copy.deepcopy(score['patterns'][old])
            orders[i] = name
        report.append(f"Made {len(created)} measure{'s' * (len(created) != 1)} independent; notes and ties preserved.")
    elif action == 'measure_clean':
        a, b = span()
        track = edit.get('track')
        if track not in score['tracks']:
            raise ValueError('Clean measure needs an existing track')
        names = list(dict.fromkeys(orders[a:b + 1]))
        clear(names, {track}, 'cleaned')
        shared(names, orders[a:b + 1])
        report.insert(0, f"Cleaned measure{'s' * (b > a)} {a + 1}{f'–{b + 1}' * (b > a)} of {track}.")
    elif action == 'measure_paste':
        mode, count = edit.get('mode'), _int(edit.get('count', 1), 1, 100, 'paste count')
        segment = edit.get('segment')
        if mode not in ('replace', 'insert'):
            raise ValueError('paste mode is replace or insert')
        if not isinstance(segment, dict) or not isinstance(segment.get('units'), list) or not 1 <= len(segment['units']) <= 256:
            raise ValueError('Copy measures first')
        tracks = segment.get('tracks')
        if not isinstance(tracks, list) or not tracks or any(not isinstance(t, str) for t in tracks) or len(set(tracks)) != len(tracks):
            raise ValueError('the copied tracks must be distinct track names')
        target = edit.get('track_map', {tracks[0]: edit.get('track')} if len(tracks) == 1 else {t: t for t in tracks})
        if (not isinstance(target, dict) or set(target) != set(tracks) or
                any(t not in score['tracks'] for t in target.values()) or len(set(target.values())) != len(tracks)):
            raise ValueError('Map every copied track to a distinct existing destination track')
        portable = 'track_specs' in segment
        if portable and (not isinstance(segment['track_specs'], dict) or set(segment['track_specs']) != set(tracks)):
            raise ValueError('portable measures need a track specification for every copied track')
        if not portable:
            for source, destination in target.items():
                if source not in score['tracks']:
                    raise ValueError('the copied tracks no longer exist; copy again for portable transfer')
                a_t, b_t = score['tracks'][source], score['tracks'][destination]
                if (a_t['tuning'], a_t.get('capo', 0), is_percussion(a_t)) != (b_t['tuning'], b_t.get('capo', 0), is_percussion(b_t)):
                    raise ValueError('paste into a track with the copied track\'s tuning and capo')
        for key in ('copy_headers', 'copy_markers'):
            if key in edit and type(edit[key]) is not bool:
                raise ValueError(f'{key} must be boolean')
        copy_headers = edit.get('copy_headers', mode == 'insert')
        copy_markers = edit.get('copy_markers', False)
        if mode == 'replace' and copy_headers and set(target.values()) != set(score['tracks']):
            raise ValueError('Replacing structural headers needs every destination track selected')
        seg_units = []
        for u in segment['units']:
            _keys(u, ('rows', 'row_step', 'beats', 'measure', 'pattern'), 'copied measure')
            rows, step = _int(u.get('rows'), 1, 200, 'copied rows'), _fraction(u.get('row_step'), 'copied row_step', True)
            beats = u.get('beats')
            if not isinstance(beats, list) or any(not isinstance(b, dict) or b.get('track') not in target for b in beats):
                raise ValueError('the copied measures hold beats of other tracks')
            seg_units.append(dict(rows=rows, row_step=step, beats=beats, measure=u.get('measure'), pattern=u.get('pattern')))
        seg_ties = segment.get('ties', [])
        if not isinstance(seg_ties, list):
            raise ValueError('copied ties must be a list')
        if portable and any(u['beats'] for u in seg_units):
            # Reuse phrase allocation over the entire segment, so ties retain one fingering across its bars.
            flat, note_keys, offset = [], {}, Fraction(0)
            for unit, u in enumerate(seg_units):
                for original in u['beats']:
                    b = copy.deepcopy(original)
                    b['id'] = f"unit{unit}_{b['id']}"
                    b['at'] = _pair(offset + Fraction(*b['at']))
                    for note in b['notes']:
                        old = note['id']
                        note['id'] = f'unit{unit}_{old}'
                        note_keys[unit, old] = note['id']
                    flat.append(b)
                offset += u['rows'] * u['row_step']
            edges = []
            for tie in seg_ties:
                _keys(tie, ('from', 'to'), 'copied measure tie')
                ends = []
                for side in ('from', 'to'):
                    e = tie.get(side)
                    _keys(e, ('unit', 'note'), 'copied measure tie endpoint')
                    key = (_int(e.get('unit'), 0, len(seg_units) - 1, 'copied tie unit'), e.get('note'))
                    if key not in note_keys:
                        raise ValueError('copied measure tie refers to a missing note')
                    ends.append(note_keys[key])
                edges.append(dict(zip(('from', 'to'), ends)))
            active = {b['track'] for b in flat}
            adapted = remap_score_clipboard(result, dict(version=1, beats=flat, ties=edges,
                track_specs={t: segment['track_specs'][t] for t in active}), {t: target[t] for t in active})
            by_id = {b['id']: b for b in adapted['beats']}
            for unit, u in enumerate(seg_units):
                u['beats'] = [dict(by_id[f"unit{unit}_{b['id']}"], id=b['id'], at=copy.deepcopy(b['at']),
                                  notes=[dict(n, id=old['id']) for n, old in zip(by_id[f"unit{unit}_{b['id']}"]['notes'], b['notes'])])
                              for b in u['beats']]
        def copied_header(u, inserting=False):
            keep = ('meter', 'swing') if inserting else ()
            if copy_headers:
                keep += ('meter', 'swing', 'repeat_open', 'repeat_close', 'endings', 'line_break', 'double_bar')
            if copy_markers:
                keep += ('marker',)
            h = header(u['measure'], keep)
            if h is not None and copy_headers and u['measure'].get('staff'):
                h['staff'] = {target[t]: copy.deepcopy(v) for t, v in u['measure']['staff'].items() if t in target}
            return h
        width = len(seg_units)
        if mode == 'replace':
            at = _int(edit.get('at'), 0, n - 1, 'paste position')
        else:
            at = _int(edit.get('at'), 0, n, 'paste position')
        total = width * count
        if mode == 'replace' and at + total > n:   # TG adds measures at the end for the rest
            last = units[-1]
            insert(len(orders), [dict(rows=last['rows'], row_step=last['row_step'],
                                      measure=header(last['measure'], ('meter', 'swing'))) for _ in range(at + total - n)])
        elif mode == 'insert':
            insert(at, [dict(rows=u['rows'], row_step=u['row_step'], beats=[],
                             # All tracks copied: the measure's raw tracker cells (tempo, effects) come too.
                             clone=u['pattern'] if not portable and segment.get('all_tracks') is True and u['pattern'] in song['patterns'] else None,
                             measure=copied_header(u, True))
                        for _ in range(count) for u in seg_units])
        names = orders[at:at + total]
        if mode == 'replace':
            twice = sorted({x for x in names if names.count(x) > 1})
            if twice:
                raise ValueError(f"the target measures play pattern {', '.join(twice)} more than once; make them unique first")
            for k, name in enumerate(names):
                rows, step = length_of(name)
                u = seg_units[k % width]
                if copy_headers and u['measure'] is None:
                    raise ValueError('copied measure has no authored header; turn off Copy structural headers')
                if (rows * step != u['rows'] * u['row_step'] or step != u['row_step']) and not copy_headers:
                    raise ValueError(f'measure {at + k + 1} has a different length or grid than the copied measure')
                if copy_headers and (rows != u['rows'] or step != u['row_step']):
                    if orders.count(name) > 1:
                        raise ValueError('make the destination measures unique before changing their length or grid')
                    if (raw_last or {}).get(name, -1) >= 0:
                        raise ValueError('replacing meter or grid over tracker commands is refused')
                    result['patterns'][name]['rows'] = u['rows']
                    resized[name] = u['rows']
                    score['patterns'][name]['row_step'] = _pair(u['row_step'])
                if copy_headers or copy_markers:
                    old = next((m for m in measures if m['from']['occurrence'] == ids[at + k]), None)
                    if old is None:
                        old = dict(id=fresh('m', used_measures), meter=copy.deepcopy((u['measure'] or {}).get('meter', [4, 4])),
                                   **{'from': dict(occurrence=ids[at + k], at=[0, 1]),
                                      'to': dict(occurrence=ids[at + k], at=_pair(u['rows'] * u['row_step']))})
                        measures.append(old)
                    if copy_headers:
                        for key in ('meter', 'swing', 'repeat_open', 'repeat_close', 'endings', 'line_break', 'double_bar', 'staff'):
                            old.pop(key, None)
                        old['to']['at'] = _pair(u['rows'] * u['row_step'])
                    if copy_markers:
                        old.pop('marker', None)
                    old.update(copied_header(u) or {})
            clear(names, set(target.values()), 'pasted')
        new_note = {}
        for k, name in enumerate(names):
            u = seg_units[k % width]
            spec = score['patterns'][name]
            used = {b['id'] for b in spec['beats']} | {x['id'] for b in spec['beats'] for x in b['notes']}
            for b in u['beats']:
                b = copy.deepcopy(b)
                b['id'], b['track'] = fresh('pb', used), b['track'] if portable else target[b['track']]
                for note in b['notes']:
                    old, note['id'] = note['id'], fresh('pn', used)
                    new_note[k, old] = note['id']
                spec['beats'].append(b)
        for tie in seg_ties:   # ties inside the copied measures, as {from|to: {unit, note}}
            for c in range(count):
                ends = [(c * width + tie[side]['unit'], tie[side]['note']) for side in ('from', 'to')]
                if all(e in new_note for e in ends):
                    score.setdefault('ties', []).append({side: dict(occurrence=ids[at + e[0]], note=new_note[e])
                                                         for side, e in zip(('from', 'to'), ends)})
        if mode == 'replace':
            shared(names, names)
        report.insert(0, f"Pasted {total} measure{'s' * (total > 1)} at {at + 1} ({mode}).")
    elif action == 'measure_meter':
        # TGSongManager.changeTimeSignature: the bar (or, to the end, every later bar too) takes the meter, later bar
        # lines move, and every beat keeps its time: TGMeasureManager.moveOutOfBoundsBeatsToNewMeasure puts each beat
        # in the bar its start now falls in, adding bars at the end while the music needs them. Here a bar is a
        # pattern, so the bars from `at` on are rebuilt with the same notes at the same times.
        at = _int(edit.get('at'), 0, n - 1, 'measure')
        meter, to_end = edit.get('meter'), edit.get('to_end', False) is True
        if not isinstance(meter, list) or len(meter) != 2:
            raise ValueError('meter is [numerator, denominator]')
        num, den = _int(meter[0], 1, 64, 'meter numerator'), _int(meter[1], 1, 64, 'meter denominator')
        if den not in (1, 2, 4, 8, 16, 32, 64):
            raise ValueError('meter denominator must be 1, 2, 4, 8, 16, 32 or 64')
        length, tail = Fraction(num * 4, den), list(range(at, n))
        for i in tail:
            name = orders[i]
            if orders.count(name) > 1:
                raise ValueError(f'pattern {name} plays at more than one order: re-barring from measure {at + 1} would change '
                                 'its other use too. Make the measures from here on unique first (Song tab)')
            if (raw_last or {}).get(name, -1) >= 0:
                raise ValueError(f'measure {i + 1} (pattern {name}) has tracker commands: re-barring would move them. '
                                 'Clear them first, or change the time signature from a later bar')
        steps = {length_of(orders[i])[1] for i in tail}
        if len(steps) > 1:
            raise ValueError(f'the bars from measure {at + 1} on use different tracker grids; re-barring needs one')
        step = steps.pop()

        def meter_of(u):
            if u['measure']:
                return list(u['measure']['meter'])
            if u['length'].denominator != 1:
                raise ValueError(f"measure {units.index(u) + 1} has no meter to keep; give it a measure entry first")
            return [int(u['length']), 4]
        bars = [dict(length=length if i == at or to_end else units[i]['length'],
                     meter=[num, den] if i == at or to_end else meter_of(units[i])) for i in tail]
        entries, offset = [], Fraction(0)
        for i in tail:
            for b in score['patterns'].get(orders[i], {}).get('beats', []):
                entries.append((offset + Fraction(*b['at']), b, ids[i]))
            offset += units[i]['length']
        needed = max((a + duration_quarters(b['written']) for a, b, _ in entries), default=Fraction(0))
        while sum(bar['length'] for bar in bars) < needed:   # TG adds bars like the last one at the end
            if len(bars) - len(tail) >= 256:
                raise ValueError('re-barring would add more than 256 measures')
            bars.append(dict(bars[-1]))
        for bar in bars:
            rows = bar['length'] / step
            if rows.denominator != 1 or not 1 <= rows <= 200:
                raise ValueError(f"{bar['meter'][0]}/{bar['meter'][1]} is not a whole number of rows (1-200) on this grid")
            bar['rows'] = int(rows)
        last = units[-1]['measure']
        insert(len(orders), [dict(rows=bar['rows'], row_step=step,
                                  measure=dict(header(last, ('swing',)) or {}, meter=bar['meter'])) for bar in bars[len(tail):]])
        slots = tail + list(range(n, len(orders)))
        for i in tail:
            score['patterns'].setdefault(orders[i], dict(row_step=_pair(step), beats=[]))['beats'] = []
        starts, remap, used, split_ties = [], {}, {}, []
        for bar in bars:
            starts.append(sum(b['length'] for b in bars[:len(starts)]))
        for a, b, oid in sorted(entries, key=lambda e: (e[0], e[1].get('voice', 0))):
            paths = {n['id']: [] for n in b['notes']}
            for position, beat in _split_moved_beat(b, a, starts, check_ring=True):
                k = max(j for j, s0 in enumerate(starts) if s0 <= position)
                name = orders[slots[k]]
                taken = used.setdefault(name, set())
                beat['at'] = _pair(position - starts[k])
                if beat['id'] in taken:
                    beat['id'] = _local_id(beat['id'], taken)
                taken.add(beat['id'])
                for note in beat['notes']:
                    old = note['id']
                    if note['id'] in taken:
                        note['id'] = _local_id(note['id'], taken)
                    taken.add(note['id'])
                    paths[old].append(dict(occurrence=ids[slots[k]], note=note['id']))
                score['patterns'][name]['beats'].append(beat)
            for old, path in paths.items():
                remap[oid, old] = path
                split_ties.extend({'from': x, 'to': y} for x, y in zip(path, path[1:]))
        score['ties'] = [{side: copy.deepcopy(remap[(t[side]['occurrence'], t[side]['note'])][0 if side == 'to' else -1])
                         if (t[side]['occurrence'], t[side]['note']) in remap else copy.deepcopy(t[side])
                         for side in ('from', 'to')} for t in score.get('ties', [])] + split_ties
        for k, i in enumerate(tail):
            name, rows = orders[i], bars[k]['rows']
            if rows != units[i]['rows']:
                resized[name] = rows
            result['patterns'][name]['rows'] = rows
            m = next((m for m in measures if m['from']['occurrence'] == ids[i]), None)
            if m is None:
                m = {'id': fresh('m', used_measures), 'from': dict(occurrence=ids[i], at=[0, 1])}
                measures.append(m)
            m['meter'], m['to'] = bars[k]['meter'], dict(occurrence=ids[i], at=_pair(bars[k]['length']))
        added = len(bars) - len(tail)
        report.insert(0, f"Time signature {num}/{den} from measure {at + 1}{' to the end' if to_end else ''}; notes keep "
                         f"their times{f', {added} measure' + 's' * (added > 1) + ' added' if added else ''}.")
    else:
        raise ValueError(f'measure action must be one of {", ".join(MEASURE_ACTIONS)}')
    score['order_ids'] = ids
    position = {oid: i for i, oid in enumerate(ids)}
    if 'measures' in score or measures:
        score['measures'] = sorted(measures, key=lambda m: position[m['from']['occurrence']])
    result['orders'] = list(orders)
    deleted = [name for name in dict.fromkeys(u['pattern'] for u in units) if name not in orders]
    for name in deleted:
        result['patterns'].pop(name, None)
        score['patterns'].pop(name, None)
    occurrences, offset = [], Fraction(0)
    for oid, name in zip(ids, orders):
        occurrences.append(dict(id=oid, pattern=name, at=_pair(offset)))
        rows, step = length_of(name)
        offset += rows * step
    removed_ties.extend(_repair_duration_ties(score, dict(occurrences=occurrences)))
    if action == 'measure_meter':
        _check_reflow_gates(song, result, remap, raw_patterns)
    if removed_ties:
        report.append(f"{len(removed_ties)} tie{'s' * (len(removed_ties) != 1)} removed; surviving notes play normally.")
    changed = [name for name in score['patterns'] if name in song['score']['patterns'] and
               score['patterns'][name] != song['score']['patterns'][name]]
    return dict(song=result, orders=list(orders), origins=origins, created=created, resized=resized, deleted=deleted,
                changed=changed, removed_ties=removed_ties, report=' '.join(report))


def apply_structure_edit(song, operation):
    """Return a candidate with score-only structural changes (raw source untouched).

Call on the document BEFORE the corresponding raw operation, then install its
score in the raw-edited candidate and compile once. Supported payloads follow
State: pattern_rename {old,new}, pattern_clone {src,name}, pattern_delete {name},
channel_move {ch,to}, channel_remove {ch}, orders {orders,origins}. origins maps
each new position to a distinct old index or None. New occurrences get fresh IDs.
pattern_split uses explicit {name,new,row}; unlike State's generated name, both
names must be supplied. It refuses crossing beats/ties instead of inventing a
new written spelling. pattern_rows {name,rows} refuses truncation of score beats.
Unrelated sample/mixer operations leave the score unchanged. Other structural
operations are refused while a score exists; the caller must not skip this gate.
"""
    result = copy.deepcopy(song)
    if 'score' not in result:
        return result
    validate_score(song)
    if not isinstance(operation, dict):
        raise ValueError('structural operation must be a mapping')
    score, op = result['score'], operation.get('op')
    patterns = score['patterns']
    if op == 'pattern_rename':
        old, new = operation.get('old'), operation.get('new')
        if not isinstance(old, str) or not isinstance(new, str) or not new:
            raise ValueError('pattern_rename requires old and new names')
        if old != new and new in patterns:
            raise ValueError(f'score pattern {new} already exists')
        if old in patterns and old != new:
            patterns[new] = patterns.pop(old)
    elif op == 'pattern_clone':
        old, new = operation.get('src'), operation.get('name')
        if not isinstance(old, str) or not isinstance(new, str) or not new:
            raise ValueError('pattern_clone requires src and name')
        if new in patterns:
            raise ValueError(f'score pattern {new} already exists')
        if old in patterns:
            # IDs are pattern-local. Their qualified identities are new even
            # when the local component stays unchanged. No occurrence tie copied.
            patterns[new] = copy.deepcopy(patterns[old])
    elif op == 'pattern_delete':
        name = operation.get('name')
        if name in map(str, song.get('orders', [])):
            raise ValueError('remove pattern occurrences before deleting the pattern')
        patterns.pop(name, None)
    elif op == 'pattern_rows':
        name = operation.get('name')
        rows = _int(operation.get('rows'), 1, 200, 'pattern rows')
        if name in patterns:
            step = _fraction(patterns[name]['row_step'], 'row_step', True)
            for beat in patterns[name]['beats']:
                if _fraction(beat['at'], 'beat at') + duration_quarters(beat['written']) > rows * step:
                    raise ValueError('pattern resize would truncate a score beat; edit/delete it first')
    elif op == 'pattern_split':
        old, new = operation.get('name'), operation.get('new')
        row = _int(operation.get('row'), 1, 199, 'split row')
        if not isinstance(old, str) or not isinstance(new, str) or not new or new in patterns:
            raise ValueError('score split requires existing name and unused explicit new name')
        if score.get('ties') or score.get('measures'):
            raise ValueError('pattern split with occurrence ties/measure anchors is unsupported; preserve the unsplit source')
        if old in patterns:
            spec = patterns[old]
            cut = row * _fraction(spec['row_step'], 'row_step', True)
            left, right = [], []
            for beat in spec['beats']:
                at = _fraction(beat['at'], 'beat at')
                if at < cut < at + duration_quarters(beat['written']):
                    raise ValueError(f"split crosses beat {beat['id']}; split its written duration explicitly first")
                if at >= cut:
                    beat['at'] = _pair(at - cut)
                    right.append(beat)
                else:
                    left.append(beat)
            spec['beats'] = left
            patterns[new] = {'row_step': list(spec['row_step']), 'beats': right}
        ids, used = [], set(score['order_ids'])
        for oid, name in zip(score['order_ids'], song['orders']):
            ids.append(oid)
            if str(name) == old:
                fresh = _fresh_id(used)
                used.add(fresh)
                ids.append(fresh)
        score['order_ids'] = ids
    elif op in ('channel_move', 'channel_remove'):
        count = _channels(song)
        channel = _int(operation.get('ch'), 0, count - 1, 'channel')
        ordering = list(range(count))
        ordering.pop(channel)
        if op == 'channel_move':
            target = _int(operation.get('to'), 0, count - 1, 'channel destination')
            ordering.insert(target, channel)
        for track in score['tracks'].values():
            if op == 'channel_remove' and channel in track['channels']:
                raise ValueError('channel is assigned to a score track; reassign its strings first')
            track['channels'] = [ordering.index(ch) for ch in track['channels']]
        for spec in patterns.values():
            for beat in spec['beats']:
                for note in beat['notes']:
                    if 'channel' in note:
                        note['channel'] = ordering.index(note['channel'])
    elif op == 'orders':
        after, origins = operation.get('orders'), operation.get('origins')
        before, old_ids = song['orders'], score['order_ids']
        if not isinstance(after, list) or not isinstance(origins, list) or len(after) != len(origins):
            raise ValueError('score order edits require explicit origins for every occurrence')
        used_origins = set()
        for origin in origins:
            if origin is not None:
                _int(origin, 0, len(before) - 1, 'order origin')
                if origin in used_origins:
                    raise ValueError('duplicate order origin: new occurrence needs origin None')
                used_origins.add(origin)
        ids, used_ids = [], set(old_ids)
        for origin in origins:
            identity = old_ids[origin] if origin is not None else _fresh_id(used_ids)
            used_ids.add(identity)
            ids.append(identity)
        for tie in score.get('ties', []):
            for endpoint in tie.values():
                identity = endpoint['occurrence']
                if identity not in ids:
                    raise ValueError('order removal would orphan a tie; edit its endpoints first')
                old = old_ids.index(identity)
                new = ids.index(identity)
                # A replacement keeps the tie only when its note is still there, as in a clone made unique.
                replacement = score['patterns'].get(str(after[new]), {}).get('beats', [])
                if (str(before[old]) != str(after[new]) and
                        not any(n['id'] == endpoint['note'] for b in replacement for n in b['notes'])):
                    raise ValueError('replacing a tied occurrence needs explicit tie remapping')
        for measure in score.get('measures', []):
            for side in ('from', 'to'):
                if measure[side]['occurrence'] not in ids:
                    raise ValueError('order removal would orphan a measure; edit its anchors first')
        score['order_ids'] = ids
    elif op in ('channel_add', 'channel_rename', 'channel_color', 'sample_file', 'sample_set',
                'sample_new', 'sample_delete', 'sample_process', 'instrument_set', 'instrument_new',
                'instrument_delete', 'module', 'pattern_new', 'pattern_automation', 'render_sample', 'sf2_preset'):
        pass  # The combined compile checks capacity, referenced instruments and timing.
    else:
        raise ValueError(f'{op}: score structural mapping is not implemented; source unchanged')
    return result


def _fresh_id(used):
    i = 1
    while f'occ_{i}' in used:
        i += 1
    return f'occ_{i}'
