"""Pure chord theory, names, recognition and source-ranked voicings.

Chord algorithms ported 2026-10-20 from TuxGuitar
2c46e2a1cccdfdfa6e6f2692f241bd60bf418129, LGPL-2.1.
Copyright (C) 2005-2022 Julian Casadesus; 2023-2025 guiv42, helge17.
Chord creator authors include Nikola Kolarovic and Julian Casadesus.
Source: desktop/TuxGuitar/src/app/tuxguitar/app/view/dialog/chord/
License: https://github.com/helge17/tuxguitar/blob/2c46e2a1cccdfdfa6e6f2692f241bd60bf418129/docs/LICENSE
Generic Java sorting is isolated in _java_priority_sort with its own notice.

Tuning is string-1-first and deliberately excludes capo, as TG's chord dialog
does. Suggestions never change an authored diagram/name or create played notes.
Scores are source heuristics, not probabilities or human playability guarantees.
Custom-library persistence is separate. Provided without warranty.
"""
import copy
import math
import struct

from .compose import CHORDS
from ._java_priority_sort import _PrioritySort
from .tablature import _int, _keys, _validate_chord, is_percussion


QUALITIES = ('M', '7', 'maj7', '6', 'm', 'm7', 'm/maj7', 'm6', 'sus2', 'sus4',
             '7sus2', '7sus4', 'dim', 'dim7', 'aug', '5')
_BASES = (CHORDS['maj'], CHORDS['7'], CHORDS['maj7'], CHORDS['6'], CHORDS['min'],
          CHORDS['min7'], (0, 3, 7, 11), CHORDS['min6'], CHORDS['sus2'],
          CHORDS['sus4'], (0, 2, 7, 10), (0, 5, 7, 10), CHORDS['dim'],
          CHORDS['dim7'], CHORDS['aug'], CHORDS['5'])
_EXTENSIONS = (0, 9, 11, 13)
_SHIFTS = (0, 1, -1)
_SHARP = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
_FLAT = ('C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B')
_PROFILES = {
    'normal': (200, 150, 200, 150, 100, 200),
    'inversions': (-100, 150, 200, 150, 50, 200),
    'close-voiced': (50, 200, 350, 150, -100, 200),
    'open-voiced': (100, 100, -80, 100, -80, 200),
}
_FLOAT = struct.Struct('f')
# Bounded full searches: exceeding either limit refuses the entire request.
_MAX_GENERATION_WORK = 1_000_000
_MAX_GENERATION_CANDIDATES = 50_000


def _boolean(value, where):
    if type(value) is not bool:
        raise ValueError(f'{where} must be boolean')
    return value


def _name(params, sharp):
    root, quality, extension, shift, bass, add, fifth, ninth, eleventh = params
    names = _SHARP if sharp else _FLAT
    name = names[root] + (QUALITIES[quality] if quality else '')
    if add:
        name += 'add'
    suffix = lambda number, adjustment: str(number) + ('', '+', '-')[adjustment]
    if extension:
        name += ('/' if name[-1].isdigit() else '') + suffix(_EXTENSIONS[extension], shift)
    for number, adjustment in ((5, fifth), (9, ninth), (11, eleventh)):
        if adjustment:
            name += '/' + suffix(number, adjustment)
    if root != bass:
        name += ' \\' + names[bass]
    return name


def _spec(params, sharp):
    root, quality, extension, shift, bass, add, fifth, ninth, eleventh = params
    return dict(root=root, quality=QUALITIES[quality], bass=bass,
                extension=_EXTENSIONS[extension], extension_shift=_SHIFTS[shift],
                fifth_shift=_SHIFTS[fifth], ninth_shift=_SHIFTS[ninth],
                eleventh_shift=_SHIFTS[eleventh], add=bool(add), sharp=sharp)


def chord_spec(spec):
    """Validate source-selectable theory; return normalized spec, name and intervals.

    Root is required (C=0..B=11); quality defaults M, bass=root, extension=0,
    shifts=0, add=False, sharp=True. Extensions are 0/9/11/13, shifts -1/0/+1.
    Returned base/extensions are zero-based semitone offsets, not voiced pitches.
    """
    _keys(spec, ('root', 'quality', 'bass', 'extension', 'extension_shift',
                 'fifth_shift', 'ninth_shift', 'eleventh_shift', 'add', 'sharp'), 'chord spec')
    root = _int(spec.get('root'), 0, 11, 'chord root')
    bass = _int(spec.get('bass', root), 0, 11, 'chord bass')
    quality = spec.get('quality', 'M')
    if quality not in QUALITIES:
        raise ValueError('unsupported chord quality')
    index = QUALITIES.index(quality)
    extension = spec.get('extension', 0)
    if type(extension) is not int or extension not in _EXTENSIONS:
        raise ValueError('chord extension must be 0, 9, 11 or 13')
    level = _EXTENSIONS.index(extension)
    shifts = [_int(spec.get(k, 0), -1, 1, f'chord {k}')
              for k in ('extension_shift', 'fifth_shift', 'ninth_shift', 'eleventh_shift')]
    add = _boolean(spec.get('add', False), 'chord add')
    sharp = _boolean(spec.get('sharp', True), 'chord sharp')
    shift, fifth, ninth, eleventh = shifts
    if (index >= 12 and (level or add or shift or ninth or eleventh) or
            index in (12, 13, 14) and fifth or
            not level and (shift or add) or
            ninth and (level < 2 or add) or eleventh and (level < 3 or add)):
        raise ValueError('chord alterations are disabled for this source quality/extension/add combination')
    expansions = []
    if level:
        selected = (2, 5, 9)[level - 1] + shift
        expansions = [selected] if add else [10, selected]
        if not add:
            expansions += [value + adjustment for value, adjustment in ((2, ninth), (5, eleventh))][:level - 1]
    base = [value + (fifth if value == 7 else 0) for value in _BASES[index]]
    base = [value for value in base if value not in expansions]
    params = [root, index, level, _SHIFTS.index(shift), bass, int(add),
              _SHIFTS.index(fifth), _SHIFTS.index(ninth), _SHIFTS.index(eleventh)]
    return dict(spec=_spec(params, sharp), name=_name(params, sharp), base=base,
                extensions=expansions, pitch_classes=sorted({(root + n) % 12 for n in base + expansions} | {bass}),
                source_parameters=params)


class _Proposal:
    def __init__(self, notes):
        self.params = [-1] * 9
        self.unusual = 0
        self.completeness = -15
        self.notes = list(notes)
        self.missing = len(notes)
        self.filled = [False] * 4
        self.shifts = [0] * 3

    def found(self, value):
        value %= 12
        for i in range(self.missing):
            if self.notes[i] == value:
                self.missing -= 1
                self.notes[i], self.notes[self.missing] = self.notes[self.missing], self.notes[i]
                return

    def is_found(self, value):
        return value % 12 in self.notes[self.missing:]

    def needed(self, value):
        return value % 12 in self.notes[:self.missing]


def _extension_logic(p):
    found, shifts = p.filled, p.shifts
    p.params[2], p.params[7], p.params[8], p.params[5], p.params[3] = 0, shifts[0], shifts[1], 0, 0
    if found[2]:
        p.params[2], p.params[3] = 3, shifts[2]
        if not found[1] or not found[0] or not found[3]:
            p.unusual -= 10
            if not found[1] and not found[0] and not found[3]:
                p.params[5] = 1
            else:
                if not found[3]:
                    p.completeness -= 25
                for i in (1, 0):
                    if not found[i]:
                        p.unusual -= 30
                        p.completeness -= 10
    elif found[1]:
        p.params[2], p.params[3], p.params[8] = 2, shifts[1], 0
        p.unusual -= 10
        if not found[0] or not found[3]:
            if not found[0] and not found[3]:
                p.params[5] = 1
            else:
                if not found[3]:
                    p.completeness -= 25
                if not found[0]:
                    p.unusual -= 30
                    p.completeness -= 10
    elif found[0]:
        p.params[2], p.params[7], p.params[8], p.params[3] = 1, 0, 0, shifts[0]
        p.unusual -= 10
        if not found[3]:
            p.params[5] = 1


def _shellsort(proposals, field):
    # Preserve TG's ordering of tied grades; Python's stable sort is different.
    gap = len(proposals) // 2
    while gap > 0:
        for i in range(gap, len(proposals)):
            item, j = proposals[i], i
            while j >= gap and getattr(item, field) > getattr(proposals[j - gap], field):
                proposals[j] = proposals[j - gap]
                j -= gap
            proposals[j] = item
        gap = 1 if gap == 2 else int(gap / 2.2)


def _validate_track(track):
    if not isinstance(track, dict):
        raise ValueError('chord track must be a mapping')
    if is_percussion(track):
        raise ValueError('Chord suggestions are unsupported for percussion tracks')
    tuning = track.get('tuning')
    if not isinstance(tuning, list) or not 1 <= len(tuning) <= 25:
        raise ValueError('chord tuning needs 1..25 strings')
    for pitch in tuning:
        _int(pitch, 0, 119, 'chord tuning pitch')
    _int(track.get('max_fret', 29), 0, 36, 'chord max_fret')
    _int(track.get('capo', 0), -24, 24, 'chord capo')
    return tuning


def recognize_chord(track, chord, *, sharp=True, incomplete=4):
    """Ordered TG name proposals; no mutation, capo offset or note generation.

    Track uses native string-1-first tuning/max_fret. Chord uses the validated
    native diagram schema. incomplete=0..100 bounds source incomplete proposals.
    """
    tuning = _validate_track(track)
    if chord is None:
        raise ValueError('chord recognition needs a nonnull diagram')
    _validate_chord(chord, track)
    sharp = _boolean(sharp, 'chord recognition sharp')
    incomplete = _int(incomplete, 0, 100, 'chord recognition incomplete')
    pitches = [(pitch + fret) % 12 for pitch, fret in zip(tuning, chord['frets']) if fret >= 0]
    notes = list(dict.fromkeys(pitches))
    if not notes:
        return []
    proposals = []
    for root in range(12):
        for index, base in enumerate(_BASES):
            p = _Proposal(notes)
            # TG compares against database length, so its intended power-chord
            # exception never fires. Only minor (index4) avoids this penalty.
            p.unusual -= 0 if index == 4 else 2 * index
            found_any = False
            for tone in base:
                if (root + tone) % 12 in notes:
                    found_any = True
                    if tone == 0:
                        p.completeness += 15
                    p.found(root + tone)
            if not found_any:
                continue
            p.params[0], p.params[1] = root, index
            count = len(p.notes) - p.missing
            if not QUALITIES[index].startswith(('dim', 'aug')) and not p.is_found(root + 7):
                if p.needed(root + 6) or p.needed(root + 8):
                    branch = copy.deepcopy(p)
                    if branch.needed(root + 8):
                        branch.params[6] = 1
                        branch.found(root + 8)
                    else:
                        branch.params[6] = 2
                        branch.found(root + 6)
                    branch.unusual -= 35
                    if count + 1 >= len(base) - 1:
                        branch.completeness -= (len(base) - count - 1) * 50
                        proposals.append(branch)
                else:
                    p.params[6] = 0
                    p.completeness += 30
            p.params[6] = 0
            if count >= len(base) - 1:
                p.completeness -= (len(base) - count) * 50
                proposals.append(p)
    admitted = []
    for p in proposals:
        bass_only = True
        for pitch in reversed(pitches):
            if p.params[4] == -1:
                p.params[4] = pitch
                if pitch != p.params[0]:
                    p.unusual -= 20
            if p.params[4] == pitch:
                bass_only = False  # Literal source: also false on the first bass.
        if p.needed(p.params[4]) and bass_only:
            p.found(p.params[4])
            p.unusual -= 20
        if p.missing > 0 and p.params[1] <= 11:
            seventh = p.params[0] + (11 if p.params[1] == 2 else 10)
            if seventh % 12 in p.notes and not p.is_found(seventh):
                p.filled[3] = True
                p.found(seventh)
            for adjustment in range(3):
                for i in (2, 1, 0):
                    tone = p.params[0] + (2, 5, 9)[i] + _SHIFTS[adjustment]
                    if p.needed(tone) and not p.filled[i]:
                        p.filled[i] = True
                        p.shifts[i] = adjustment
                        if adjustment:
                            p.unusual -= 15
                        p.found(tone)
        if not (p.filled[3] and not any(p.filled[:3])) and p.missing == 0 and p.completeness > -51:
            _extension_logic(p)
            admitted.append(p)
    _shellsort(admitted, 'completeness')
    cut = next((i + incomplete for i, p in enumerate(admitted) if p.completeness < 0), -1)
    # Preserve source's cut>0 edge: incomplete=0 at first negative does not cut.
    if 0 < cut < len(admitted):
        admitted = admitted[:cut]
    _shellsort(admitted, 'unusual')
    first_negative = 0
    result = []
    for p in admitted:
        if first_negative == 0 and p.unusual < 0:
            first_negative = p.unusual
        if p.unusual > (0 if first_negative >= 0 else first_negative) - 60:
            result.append(dict(spec=_spec(p.params, sharp), name=_name(p.params, sharp),
                               source_parameters=list(p.params), completeness=p.completeness,
                               unusualness=p.unusual, score_percent=100 + int(p.completeness * 7 / 10)))
    return result


def _float(value):
    """Round at Java float expression/assignment boundaries."""
    return _FLOAT.unpack(_FLOAT.pack(value))[0]


def _fingering(combination, strings, maximum, weight):
    positions = [-1] * strings
    for string, fret, _ in combination:
        positions[string] = fret
    positive = [f for f in positions if f > 0]
    minimum, maximum_used = min(positive, default=maximum + 2), max(positions)
    # Source maximum starts at zero; every combination contains played frets.
    max_count = positions.count(maximum_used)
    zero = 0 in positions
    # Source's openChord/zeroString branches give this same bonus in both modes.
    grade = _float(weight / 8) if zero or positions.count(minimum) >= 2 else 0.0
    distance = abs(maximum_used - minimum)
    if distance == 0:
        distance_grade = _float(weight / 5)
    elif distance == 1:
        distance_grade = _float(weight / (5 + max_count))
    elif distance == 2:
        distance_grade = _float(weight / (6 + max_count))
        if minimum < 5:
            distance_grade = _float(distance_grade * 0.9)
    elif distance == 3:
        distance_grade = _float(_float(-weight / 10) * max_count)
        if minimum < 5:
            distance_grade = _float(distance_grade * 1.3)
    elif distance == 4:
        distance_grade = _float(_float(-weight / 4) * max_count)
        if minimum <= 5:
            distance_grade = _float(distance_grade * 1.8)
    else:
        distance_grade = _float(-weight * max_count)
    grade = _float(grade + distance_grade)
    last_zero = max((i for i, f in enumerate(positions) if f == 0), default=0)
    fingers = 1 + sum(f > 0 and not (i >= last_zero and f == minimum)
                      for i, f in enumerate(positions))
    return _float(grade - weight if fingers > 4 else grade + weight * 0.1 * (15 - 2 * fingers))


def _priority(combination, tuning, theory, weights, maximum):
    bass_weight, finger_weight, contiguous_weight, base_weight, many_weight, semantic_weight = weights
    spec, base, extensions = theory['spec'], theory['base'], theory['extensions']
    n = len(tuning)
    found = len({role for _, _, role in combination if role >= 0})
    if found == len(base):
        grade = float(base_weight)
    elif (found == len(base) - 1 and len(base) != 2 and not spec['fifth_shift']
          and 'sus' in spec['quality']
          and not any((tuning[s] + f) % 12 == (spec['root'] + 7) % 12 for s, f, _ in combination)):
        grade = _float(_float(base_weight * 4) / 5)
    else:
        level = _EXTENSIONS.index(spec['extension'])
        count = found + (1 + level if level else 0) + (spec['bass'] != spec['root'])
        grade = _float(_float(_float(-base_weight * (n - count)) / n) * 2)
    semantics = 0.0
    tonic = -1
    expansion_roles = [0] * len(extensions)
    for depth, (string, fret, role) in enumerate(combination):
        pitch = tuning[string] + fret
        if tonic == -1 and role == 0:
            tonic = pitch
        if depth:
            if role == -1:
                semantics = _float(semantics - semantic_weight)
            if role < 0:
                if tonic == -1:
                    semantics = _float(semantics - _float(semantic_weight / 2))
                elif tonic + 11 > pitch:
                    semantics = _float(semantics - _float(semantic_weight / 3))
                for i, tone in enumerate(extensions):
                    if pitch % 12 == (spec['root'] + tone) % 12 and expansion_roles[i] == 0:
                        expansion_roles[i] = role
    if spec['extension']:
        essential = expansion_roles.count(-2)
        other = sum(role not in (0, -2) for role in expansion_roles)
        if essential + other == len(extensions):
            semantics = _float(semantics + semantic_weight)
        elif essential == 2:
            semantics = _float(semantics + _float(semantic_weight / 2))
        else:
            semantics = _float(semantics + _float((essential + other - len(extensions)) * semantic_weight))
            semantics = _float(semantics + _float(_float(other * semantic_weight) / 2))
    grade = _float(grade + semantics)
    contiguous = combination[-1][0] - combination[0][0] + 1 == len(combination)
    grade = _float(grade + (contiguous_weight if contiguous else -contiguous_weight))
    s, f, _ = combination[0]
    grade = _float(grade + (bass_weight if (tuning[s] + f) % 12 == spec['bass'] else -bass_weight))
    # The conditional 2 : 1.2 promotes the string-count term to Java double.
    grade = _float(grade + _float(many_weight / 3) * (len(combination) - n / (2 if many_weight > 0 else 1.2)))
    return _float(grade + _fingering(combination, n, maximum, finger_weight))


def _string_subsets(indices, size):
    # Source order: highest index outermost, recursively; not lexicographic.
    if size == 1:
        for i in indices:
            yield (i,)
    else:
        for end in range(size - 1, len(indices)):
            for prefix in _string_subsets(indices[:end], size - 1):
                yield prefix + (indices[end],)


def _priority_compare(a, b):
    return math.floor(_float(b[0] - a[0]) + 0.5)


def _take_best(ranked, count):
    try:
        _PrioritySort(ranked, _priority_compare).sort()
    except ValueError as exc:
        raise ValueError('source chord comparator violates its ordering contract; narrow the search') from exc
    best = []
    for priority, combination in ranked:
        frets = {s: f for s, f, _ in combination}
        # Literal TG suppression also rejects disjoint string sets.
        if any(not any(s in frets and frets[s] != f for s, f, _ in kept)
               for _, kept in best):
            continue
        best.append((priority, combination))
        if len(best) == count:
            break
    return best


def generate_chords(track, spec, *, profile='normal', min_fret=0, max_fret=None,
                    open_strings=False, count=30):
    """Complete bounded TG voicing search; native-safe diagrams in source order.

    Work-limit refusal never returns a partial best list. Tuning excludes capo
    for theory; candidate played pitches include capo for native range guards.
    """
    tuning = list(reversed(_validate_track(track)))
    theory = chord_spec(spec)
    if not isinstance(profile, str) or profile not in _PROFILES:
        raise ValueError('chord profile must be normal, inversions, close-voiced or open-voiced')
    minimum = _int(min_fret, 0, 15, 'chord search min_fret')
    maximum = min(15, track.get('max_fret', 29)) if max_fret is None else _int(max_fret, 0, 25, 'chord search max_fret')
    if minimum > maximum or maximum > track.get('max_fret', 29):
        raise ValueError('chord search needs min_fret <= max_fret <= track max_fret')
    opens = _boolean(open_strings, 'chord open_strings')
    count = _int(count, 1, 100, 'chord count')
    spec = theory['spec']
    potential = []
    for string, pitch in enumerate(tuning):
        notes = []
        for fret in ([0] if minimum > 0 and opens else []) + list(range(minimum, maximum + 1)):
            if not 0 <= pitch + track.get('capo', 0) + fret <= 119:
                continue
            relative = (pitch + fret - spec['root']) % 12
            if relative in theory['base']:
                notes.append((string, fret, theory['base'].index(relative)))
                continue
            matched_bass = False
            for i, tone in enumerate(theory['extensions']):
                if relative == tone:
                    notes.append((string, fret, -2 if i < 2 else -3))
                    matched_bass |= (pitch + fret) % 12 == spec['bass']
            if not matched_bass and (pitch + fret) % 12 == spec['bass']:
                notes.append((string, fret, -1))
        potential.append(notes)
    indices = [i for i, notes in enumerate(potential) if notes]
    ranked, work = [], 0
    for size in range(2, len(indices) + 1):
        for subset in _string_subsets(indices, size):
            work += 1
            combinations = [ (candidate,) for candidate in potential[subset[0]] ]
            for string in subset[1:]:
                work += len(combinations) * len(potential[string])
                if work > _MAX_GENERATION_WORK:
                    raise ValueError('chord search exceeds work limit; narrow the fret range or tuning')
                expanded = []
                for candidate in potential[string]:
                    for previous in combinations:
                        combination = previous + (candidate,)
                        frets = [f for _, f, _ in combination if f or not opens]
                        # Source seeds its bounds with first fret even if zero.
                        frets.append(combination[0][1])
                        if max(frets) - min(frets) < 5:
                            expanded.append(combination)
                            if string == subset[-1] and len(ranked) + len(expanded) > _MAX_GENERATION_CANDIDATES:
                                raise ValueError('chord search exceeds candidate limit; narrow the fret range or tuning')
                combinations = expanded
                if not combinations:
                    break
            ranked.extend((_priority(c, tuning, theory, _PROFILES[profile], maximum), c)
                          for c in combinations)
    chords = []
    for _, combination in _take_best(ranked, count):
        frets = [-1] * len(tuning)
        for string, fret, _ in combination:
            frets[len(tuning) - 1 - string] = fret
        chord = dict(name=theory['name'], first_fret=0, frets=frets)
        _validate_chord(chord, track)
        chords.append(chord)
    return dict(spec=spec, settings=dict(profile=profile, min_fret=minimum, max_fret=maximum,
                                       open_strings=opens, count=count), chords=chords)
