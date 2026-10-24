"""Strict authored GP5.00, GP4.00 and GP3.00 export. Produces bytes, never files or rendered audio."""
from fractions import Fraction
import io

from .tablature import TempoClock, authoring_view, duration_quarters, playback_plan, repeat_projection, _has_distinct_cohorts


def _fail(where, reason):
    raise ValueError(f'Native GP5: {where}: {reason}')


def _encoded_text(value, limit, where, encoding):
    if not isinstance(value, str):
        _fail(where, 'text must be a string')
    try:
        encoded = value.encode(encoding)
        if encoded.decode(encoding) != value:
            _fail(where, f'text does not round-trip in {encoding}')
    except UnicodeEncodeError:
        _fail(where, f'text is not representable in {encoding}')
    if len(encoded) > limit:
        _fail(where, f'text exceeds {limit} encoded bytes')
    return value


def native_to_gp5(song, raw_patterns, *, channels, encoding=None):
    return native_to_gp(song, raw_patterns, channels=channels, version=5, encoding=encoding)


def native_to_gp(song, raw_patterns, *, channels, version, encoding=None):
    """Return (GP3.00/GP4.00/GP5.00 bytes, report); GP3/4 add the refusals of their
    narrower formats (one voice, song-wide swing, no minor mode; GP3 beat-level
    harmonic/vibrato and dip-only tremolo bar). Messages name the target version."""
    if version not in (3, 4, 5):
        raise ValueError(f'Native GP export: unsupported version {version}')
    try:
        from .gpimport import guitar_pro_encoding
        return _native_to_gp(song, raw_patterns, channels, version, guitar_pro_encoding(encoding))
    except ValueError as e:
        if version != 5 and str(e).startswith('Native GP5: '):
            raise ValueError(f'Native GP{version}: ' + str(e)[len('Native GP5: '):]) from None
        raise


def _native_to_gp(song, raw_patterns, channels, version, encoding):
    """Return (GP bytes, report), preserving the admitted written subset.

    channels maps every native track to explicit {program, bank}. The first
    slice supports note flags, bend/bar/shift-slide and bounded harmonics/repetition,
    authored rests/ties, two voices and headers.
    Unsupported notation refuses before serialization. Exact silent gaps become
    reported export-only rests for GP's consecutive voice representation.
    """
    from guitarpro import models as M
    from guitarpro.gp3 import GP3File
    from guitarpro.gp4 import GP4File
    from guitarpro.gp5 import GP5File
    from .gpimport import _read_native_gp, _native_gp_song
    from .tgimport import _fill_export_silence, track_midi_mix

    def _text(value, limit, where):
        return _encoded_text(value, limit, where, encoding)

    repeated = repeat_projection(song, raw_patterns, 44100)
    if repeated is None:
        playback_plan(song, raw_patterns, 44100)
    view = repeated.source_view if repeated else authoring_view(song, raw_patterns)
    score, module = song['score'], song.get('module', {})
    arranged = {str(name) for name in song['orders']}
    for name, pattern in score['patterns'].items():
        if name not in arranged and pattern.get('beats'):
            _fail(name, 'unarranged authored beats cannot be represented')
        if _has_distinct_cohorts(pattern.get('beats', [])):
            _fail(name, 'GP reimport merges independent beat groups at the same onset; use TG to preserve their identity')
    if set(channels) != set(score['tracks']):
        _fail('tracks', 'explicit program/bank mapping is required for every track')
    if any(not c.is_empty() and not (c.note is None and not c.instrument and c.volcmd is None
                                    and c.effect == 20 and 32 <= c.param <= 255)
           for p in raw_patterns for row in p.rows for c in row):
        _fail('backing', 'residual tracker commands cannot be represented')
    for field, default in (('global_volume', 128), ('mix_volume', 48), ('separation', 128)):
        if module.get(field, default) != default:
            _fail('mix', f'non-neutral {field} cannot be represented')
    mixes = {tid: track_midi_mix(song, track) for tid, track in score['tracks'].items()}
    if module.get('key'):
        _fail('key', 'free-form module key is unsupported; use track key signatures')
    occurrences = {o['id']: Fraction(*o['at']) for o in view['occurrences']}
    measures = sorted((occurrences[m['from']['occurrence']] + Fraction(*m['from']['at']),
                       occurrences[m['to']['occurrence']] + Fraction(*m['to']['at']), m)
                      for m in score.get('measures', []))
    if not 1 <= len(measures) <= 254:
        _fail('measures', 'requires 1..254 explicit measures')
    if measures[0][0] != 0 or measures[-1][1] != Fraction(*view['duration']) or any(
            a[1] != b[0] for a, b in zip(measures, measures[1:])):
        _fail('measures', 'explicit measures must cover the complete arrangement without gaps')
    starts = {a for a, _, _ in measures}
    step = Fraction(*view['row_step'])
    for p in raw_patterns:
        rows = [i for i, row in enumerate(p.rows) if any(c.effect == 20 for c in row)]
        visits = [o for o in view['occurrences'] if o['pattern'] == p.name]
        if rows and not visits:
            _fail(p.name, 'unused tempo commands cannot be represented')
        if any(Fraction(*o['at']) + row * step not in starts for o in visits for row in rows):
            _fail(p.name, 'midmeasure tempo commands are unsupported, including no-op changes')
    clock = TempoClock(module.get('tempo', 125), view.get('tempos'))
    keys = {(t.get('key', {}).get('fifths', 0), int(t.get('key', {}).get('mode', 'major') == 'minor'))
            for t in score['tracks'].values()}
    if len(keys) != 1:
        _fail('key', 'GP5 requires one shared key signature')
    key = M.KeySignature(next(iter(keys)))
    if version < 5:
        if key.value[1]:
            _fail('key', f'GP{version} cannot store minor mode')
        swings = {m.get('swing', 'none') for _, _, m in measures}
        if len(swings) > 1 or swings - {'none', 'eighth'}:
            _fail('measures', f'GP{version} stores one song-wide swing, none or eighth only')
    credits = score.get('metadata', {})
    comments = credits.get('comments', module.get('message', ''))
    target = M.Song(versionTuple=(version, 0, 0), tracks=[], measureHeaders=[],
                    title=_text(credits.get('title', module.get('title', '')), 255, 'title'),
                    artist=_text(credits.get('artist', ''), 255, 'artist'), album=_text(credits.get('album', ''), 255, 'album'),
                    music=_text(credits.get('author', ''), 255, 'author'), words=_text(credits.get('writer', ''), 255, 'writer'),
                    copyright=_text(credits.get('copyright', ''), 255, 'copyright'), tab=_text(credits.get('transcriber', ''), 255, 'transcriber'),
                    notice=[_text(line, 255, 'comments') for line in
                            (comments.splitlines() if 'comments' in credits else [comments] if comments else [])],
                    tempo=clock.tempo_at(0), key=key)
    if version < 5:
        _text(GP3File.packAuthor(None, target), 255, 'combined author/writer')
    active_keys = {tid: track.get('key', {'fifths': 0, 'mode': 'major'}) for tid, track in score['tracks'].items()}
    for index, (a, b, m) in enumerate(measures, 1):
        for tid, change in m.get('staff', {}).items():
            if 'clef' in change and change['clef'] != score['tracks'][tid].get('clef', 'treble'):
                _fail(m['id'], 'GP cannot preserve explicit clef changes')
            if 'key' in change:
                active_keys[tid] = change['key']
        measure_keys = {(k.get('fifths', 0), int(k.get('mode', 'major') == 'minor')) for k in active_keys.values()}
        if len(measure_keys) != 1:
            _fail(m['id'], 'GP requires one shared key signature')
        measure_key = M.KeySignature(next(iter(measure_keys)))
        if version < 5 and measure_key.value[1]:
            _fail(m['id'], f'GP{version} cannot store minor mode')
        if (a * 960).denominator != 1 or (b * 960).denominator != 1:
            _fail(m['id'], 'measure boundaries require integral GP ticks')
        header = M.MeasureHeader(number=index, start=960 + int(a * 960), keySignature=measure_key,
            timeSignature=M.TimeSignature(m['meter'][0], M.Duration(m['meter'][1])),
            isRepeatOpen=m.get('repeat_open', False), repeatClose=m.get('repeat_close', -1),
            hasDoubleBar=m.get('double_bar', False),
            repeatAlternative=sum(1 << (n - 1) for n in m.get('endings', [])),
            tripletFeel=M.TripletFeel[m.get('swing', 'none')])
        if m.get('marker') is not None:
            color = m['marker'].get('color', '#000000')
            header.marker = M.Marker(_text(m['marker']['title'], 255, m['id'] + ' marker'),
                                     M.Color(*(int(color[i:i + 2], 16) for i in (1, 3, 5))))
        target.measureHeaders.append(header)

    resolved = {p['id']: p for p in view['positions'] if p['kind'] == 'note'}
    tied_in = {(t['to']['occurrence'], t['to']['note']) for t in score.get('ties', [])}
    melodic_routes = iter([ch for ch in range(16) if ch != 9])
    drums, lyric_tracks, note_count, generated_rests = 0, 0, 0, 0
    artificial_harmonics = False
    fade_in = False
    rerouted_notes = 0
    routes = []
    for number, (tid, track) in enumerate(score['tracks'].items(), 1):
        assignment = channels[tid]
        if (set(assignment) != {'program', 'bank'} or type(assignment['program']) is not int
                or not 0 <= assignment['program'] <= 127 or type(assignment['bank']) is not int):
            _fail(tid, 'channel mapping requires integer program0..127 and bank')
        bank = assignment['bank']
        if bank not in (0, 128) or (bank == 128) != (track.get('midi', {}).get('bank') == 128):
            _fail(tid, 'GP5 supports bank0 or matching percussion bank128 only')
        if len(track['tuning']) > 7:
            _fail(tid, 'GP5 supports at most seven lanes')
        # GP5 carries no clef selector. TuxGuitar infers bass from any string
        # at or below MIDI34, except percussion channels always infer treble.
        inferred_clef = 'bass' if bank != 128 and any(pitch <= 34 for pitch in track['tuning']) else 'treble'
        if track.get('clef', 'treble') != inferred_clef:
            _fail(tid, f'GP5 infers {inferred_clef} clef from tuning and percussion routing; source clef is {track.get("clef", "treble")}')
        if track.get('stem', 'auto') != 'auto':
            _fail(tid, 'track stem direction is unsupported')
        gp_mix = {}
        specs = module['channels']
        for field, default in (('volume', 64), ('pan', 32)):
            value = specs[track['channels'][0]].get(field, default) if isinstance(specs, list) else default
            if value % 4:
                _fail(tid, f'GP mixer {field} requires a native multiple of four (0..64)')
            binding = track.get('midi', {}).get('source_' + field)
            if binding and binding['mixer_' + field] == value and mixes[tid][field] != max(value * 2 - 1, 0):
                _fail(tid, f'bound source {field} is not an exact GP mixer step')
            gp_mix[field] = value * 2
        if bank == 128:
            drums += 1
            if drums > 1:
                _fail(tid, 'multiple logical drum tracks need qualified shared GP routing')
            primary = secondary = 9
        else:
            try:
                primary, secondary = next(melodic_routes), next(melodic_routes)
            except StopIteration:
                _fail(tid, 'more than seven independent melodic channel pairs')
        routes.append(dict(track=tid, primary=primary, secondary=secondary, program=assignment['program'], bank=bank))
        color = track.get('color', '#ff0000')
        t = M.Track(target, number=number, name=_text(track.get('name', tid), 40, tid + ' name'),
            strings=[M.GuitarString(i + 1, pitch) for i, pitch in enumerate(track['tuning'])],
            offset=track.get('capo', 0), fretCount=track.get('max_fret', 29), isPercussionTrack=bank == 128,
            clefTranspose=0, clefTransposeSecondary=0,
            channel=M.MidiChannel(channel=primary, effectChannel=secondary,
                                 instrument=assignment['program'], volume=gp_mix['volume'], balance=gp_mix['pan']),
            color=M.Color(*(int(color[i:i + 2], 16) for i in (1, 3, 5))))
        target.tracks.append(t)
        if 'lyrics' in track:
            if version == 3:
                _fail(tid, 'GP3 cannot store lyrics')
            lyric_tracks += 1
            if lyric_tracks > 1:
                _fail(tid, 'GP5 can retain lyrics on only one target track')
            lyric = track['lyrics']
            target.lyrics.trackChoice = number
            target.lyrics.lines[0] = M.LyricLine(lyric['from_measure'],
                _text(lyric['text'], 65536, tid + ' lyrics'))
        grouped = [[[], []] for _ in measures]
        for oid, pname in zip(score['order_ids'], song['orders']):
            for beat in score['patterns'].get(str(pname), {}).get('beats', []):
                if beat['track'] != tid:
                    continue
                at = occurrences[oid] + Fraction(*beat['at'])
                end = at + duration_quarters(beat['written'])
                mi = next((i for i, (a, b, _) in enumerate(measures) if a <= at < b), None)
                if mi is None or end > measures[mi][1]:
                    _fail(beat['id'], 'written beat crosses a measure boundary')
                unsupported = set(beat) - {'id', 'track', 'voice', 'at', 'written', 'notes', 'text', 'stem',
                                           'chord', 'stroke', 'pick_stroke', 'cohort'}
                if unsupported:
                    _fail(beat['id'], f'unsupported beat metadata {sorted(unsupported)}')
                if beat.get('stem', 'auto') != 'auto':
                    _fail(beat['id'], 'beat stem direction is unsupported')
                if version < 5 and beat.get('voice', 0):
                    _fail(beat['id'], f'GP{version} stores one voice per measure')
                grouped[mi][beat.get('voice', 0)].append((at, oid, beat))
        for mi, (a, b, measure) in enumerate(measures):
            for vi, entries in enumerate(grouped[mi]):
                grouped[mi][vi], count = _fill_export_silence(entries, a, f'{tid}-m{mi + 1}-v{vi}', max_dots=1)
                generated_rests += count
            shared = {}
            for vi, entries in enumerate(grouped[mi]):
                for at, _, beat in entries:
                    shared.setdefault(at, {})[vi] = beat
            for voices in shared.values():
                annotated = [vi for vi, beat in voices.items() if beat.get('text')]
                if annotated and annotated != [min(voices)]:
                    _fail(tid, 'TG shares beat text; only the first present voice may own its annotation')
            for vi, entries in enumerate(grouped[mi]):
                voice = t.measures[mi].voices[vi]
                cursor = a
                for at, oid, beat in sorted(entries, key=lambda entry: entry[0]):
                    if at != cursor:
                        _fail(beat['id'], 'voice must start at measure start and be consecutive; no filler rests')
                    written = beat['written']
                    ratio = tuple(written.get('tuplet', [1, 1]))
                    length = duration_quarters(written)
                    if (written.get('dots', 0) > 1 or ratio not in M.Tuplet.supportedTuplets or
                            (length * 960).denominator != 1):
                        _fail(beat['id'], 'duration needs one dot at most, supported tuplet and integral GP ticks')
                    g = M.Beat(voice, start=960 + int(at * 960),
                        status=M.BeatStatus.normal if beat['notes'] else M.BeatStatus.rest,
                        duration=M.Duration(written['value'], bool(written.get('dots', 0)), M.Tuplet(*ratio)),
                        text=_text(beat['text'], 255, beat['id'] + ' text') if beat.get('text') else None)
                    # TG owns these fields on the shared onset, not on either
                    # voice. Emit once on the first present voice, including
                    # when native metadata is attached only to voice two.
                    where = f'{track.get("name", tid)}, bar {mi + 1}, voice {vi + 1}, beat {beat["id"]}'
                    cohort = shared[at]
                    if vi == min(cohort):
                        metadata = {key: entry[key] for entry in cohort.values()
                                    for key in ('chord', 'stroke', 'pick_stroke') if entry.get(key) is not None}
                        chord = metadata.get('chord')
                        if chord is not None:
                            if not any(fret >= 0 for fret in chord['frets']):
                                _fail(where, 'GP drops name-only/all-muted chord diagrams; use beat text for the label or add a played diagram string')
                            if version == 3 and len(chord['frets']) > 6:
                                _fail(where, 'GP3 chord diagrams have at most six strings; export GP4/GP5 instead')
                            g.effect.chord = M.Chord(len(track['tuning']), newFormat=True,
                                name=_text(chord['name'], 22 if version == 3 else 21, where + ' chord name'),
                                firstFret=chord['first_fret'], strings=list(chord['frets']))
                        stroke = metadata.get('stroke')
                        if stroke is not None:
                            g.effect.stroke = M.BeatStroke(M.BeatStrokeDirection[stroke['direction']], stroke['value'])
                        pick = metadata.get('pick_stroke')
                        if pick is not None:
                            if version == 3:
                                _fail(where, 'GP3 cannot store pick direction; export GP4/GP5 instead')
                            g.effect.pickStroke = M.BeatStrokeDirection[pick]
                    fades = [n.get('fade_in', False) for n in beat['notes']]
                    techniques = [next((i for i, flag in enumerate(('tapping', 'slapping', 'popping'), 1)
                                        if n.get(flag)), 0) for n in beat['notes']]
                    if len(set(fades)) > 1:
                        _fail(beat['id'], 'GP5 fade-in requires identical flags on every note in its voice beat')
                    if len(set(techniques)) > 1:
                        _fail(beat['id'], 'GP5 tap/slap/pop requires identical techniques on every note in its voice beat')
                    g.effect.fadeIn = fades[0] if fades else False
                    g.effect.slapEffect = M.SlapEffect(techniques[0] if techniques else 0)
                    fade_in |= g.effect.fadeIn
                    bars = [n.get('tremolo_bar') for n in beat['notes']]
                    if bars and any(bar != bars[0] for bar in bars[1:]):
                        _fail(beat['id'], 'GP5 tremolo bar requires identical curves on every note in its voice beat')
                    bar = bars[0] if bars else None
                    if bar is not None:
                        if not bar['points']:
                            _fail(beat['id'], 'GP5 tremolo bar needs at least one point')
                        g.effect.tremoloBar = M.BendEffect(type=M.BendType.bend, value=0,
                            points=[M.BendPoint(p['position'], p['value'] * 2, False) for p in bar['points']])
                        if version == 3:
                            # GP3 stores one dip depth; TG reads (0,0),(6,-depth/50),(12,0).
                            shape = [(p['position'], p['value']) for p in bar['points']]
                            if (len(shape) != 3 or shape[0] != (0, 0) or shape[2] != (12, 0) or shape[1][0] != 6
                                    or not shape[1][1]):
                                _fail(beat['id'], 'GP3 tremolo bar stores only a dip (0,0),(6,v),(12,0), v nonzero')
                            if g.effect.slapEffect != M.SlapEffect.none:
                                _fail(beat['id'], 'GP3 stores tremolo bar and tap/slap/pop in one field')
                            g.effect.tremoloBar = M.BendEffect(type=M.BendType.dip, value=-50 * shape[1][1])
                    if version == 3:
                        for field in ('harmonic', 'vibrato'):
                            if len({repr(n.get(field) or None) for n in beat['notes']}) > 1:
                                _fail(beat['id'], f'GP3 stores {field} per beat; every note in it must match')
                    lane_order = []
                    for note in beat['notes']:
                        supported = {'id', 'pitch', 'string', 'fret', 'velocity', 'volume', 'instrument', 'channel',
                                     'ghost', 'accent', 'heavy_accent', 'staccato', 'dead', 'palm_mute', 'let_ring',
                                     'harmonic', 'trill', 'tremolo_picking', 'bend', 'slide', 'vibrato', 'hammer',
                                     'tremolo_bar', 'fade_in', 'tapping', 'slapping', 'popping', 'grace'}
                        if version < 5:
                            supported -= {'heavy_accent'} | ({'accent', 'staccato', 'palm_mute', 'trill',
                                                             'tremolo_picking'} if version == 3 else set())
                        unsupported = [k for k in set(note) - supported if note[k] is not None and note[k] is not False]
                        if unsupported:
                            _fail(note['id'], f'unsupported note metadata {sorted(unsupported)}')
                        incoming = (oid, note['id']) in tied_in
                        if incoming and note.get('dead'):
                            _fail(note['id'], 'incoming tie and dead cannot share a GP note type')
                        if sum(bool(note.get(k)) for k in ('ghost', 'accent', 'heavy_accent')) > 1:
                            _fail(note['id'], 'multiple dynamics would be normalized by GP')
                        if note.get('palm_mute') and note.get('staccato'):
                            _fail(note['id'], 'palm_mute and staccato would be normalized by GP')
                        bend = note.get('bend')
                        if bend is not None and not bend['points']:
                            _fail(note['id'], 'GP5 bend needs at least one point')
                        if sum(bool(note.get(k)) for k in ('dead', 'slide', 'hammer', 'bend', 'tremolo_bar')) > 1:
                            _fail(note['id'], 'pitch/dead effect combination would be normalized by GP')
                        if note.get('volume') is not None or 'instrument' in note:
                            _fail(note['id'], 'per-note tracker volume/instrument is unsupported')
                        r = resolved[f'{oid}/{note["id"]}']
                        if r['string'] is None or r['fret'] is None:
                            _fail(note['id'], 'export needs resolved lane/fret')
                        if note.get('channel', r['ch']) != track['channels'][r['string'] - 1]:
                            specs = module.get('channels', [])
                            if (r['ch'] not in track['channels'] or isinstance(specs, list) and
                                    any(c.get('plugin') for c in specs)):
                                _fail(where, 'per-note channel override needs a neutral spare channel within the same part; plugin/external routes cannot be exported')
                            # Native spare lanes only separate overlapping voices.
                            # GP uses track/voice MIDI routes; samples and their
                            # release state are already explicitly replaced.
                            rerouted_notes += 1
                        if note.get('velocity') not in range(15, 128, 16):
                            _fail(note['id'], 'explicit velocity must be on the GP grid15,31,47,63,79,95,111,127')
                        if bank == 128 and not 1 <= r['fret'] <= 99:
                            _fail(note['id'], 'GP percussion key must be1..99; key100 is normalized by TG')
                        harmonic = note.get('harmonic')
                        if harmonic is not None:
                            kind, data = harmonic['type'], harmonic.get('data',0)
                            allowed = ('natural','artificial','tapped','pinch','semi') if version>=4 else ('natural','artificial')
                            data_values = range(6) if version==5 and kind=='tapped' else (0,2,3) if version==4 and kind=='artificial' else (0,)
                            if kind not in allowed or data not in data_values:
                                _fail(note['id'], f'GP{version} harmonic data cannot roundtrip: '+
                                      ('tapped data0..5; other harmonic data0 only' if version==5 else
                                       'artificial data0/2/3; other harmonic data0 only' if version==4 else
                                       'natural/artificial harmonic data0 only'))
                        trill = note.get('trill')
                        if trill is not None and trill['value'] not in (16, 32, 64):
                            _fail(note['id'], 'GP5 trill rate must be16,32,64')
                        grace = note.get('grace')
                        if grace is not None:
                            if grace['velocity'] not in range(15, 128, 16):
                                _fail(note['id'], 'GP grace velocity must be one of15,31,47,63,79,95,111,127')
                            if version < 5 and (grace.get('on_beat') or
                                                (grace.get('dead') and grace['fret'] != 0)):
                                _fail(note['id'], f'GP{version} grace requires before-beat timing and dead fret0')
                        lane_order.append(r['string'])
                        written_note = M.Note(g, value=r['fret'], string=r['string'], velocity=note['velocity'],
                            type=M.NoteType.tie if incoming else M.NoteType.dead if note.get('dead') else M.NoteType.normal,
                            effect=M.NoteEffect(ghostNote=note.get('ghost', False),
                                accentuatedNote=note.get('accent', False),
                                heavyAccentuatedNote=note.get('heavy_accent', False),
                                staccato=note.get('staccato', False), palmMute=note.get('palm_mute', False),
                                letRing=note.get('let_ring', False), vibrato=note.get('vibrato', False),
                                hammer=note.get('hammer', False)))
                        if bend is not None:
                            written_note.effect.bend = M.BendEffect(type=M.BendType.bend, value=0,
                                points=[M.BendPoint(p['position'], p['value'], False) for p in bend['points']])
                        if note.get('slide'):
                            written_note.effect.slides = [M.SlideType.shiftSlideTo]
                        if harmonic is not None:
                            if harmonic['type'] == 'natural':
                                written_note.effect.harmonic = M.NaturalHarmonic()
                            elif harmonic['type'] == 'artificial':
                                data = harmonic.get('data',0)
                                written_note.effect.harmonic = M.ArtificialHarmonic(
                                    M.PitchClass((written_note.realValue+(7 if version==4 and data==2 else 0)) % 12),
                                    M.Octave.quindicesima if version==4 and data==3 else M.Octave.ottava)
                                artificial_harmonics = True
                            elif harmonic['type'] == 'tapped':
                                written_note.effect.harmonic = M.TappedHarmonic(r['fret']+(12,9,5,7,4,3)[harmonic.get('data',0)])
                            elif harmonic['type'] == 'pinch':
                                written_note.effect.harmonic = M.PinchHarmonic()
                            else:
                                written_note.effect.harmonic = M.SemiHarmonic()
                        if trill is not None:
                            written_note.effect.trill = M.TrillEffect(
                                fret=trill['fret'], duration=M.Duration(value=trill['value']))
                        picking = note.get('tremolo_picking')
                        if picking is not None:
                            written_note.effect.tremoloPicking = M.TremoloPickingEffect(
                                duration=M.Duration(value=picking['value']))
                        if grace is not None:
                            written_note.effect.grace = M.GraceEffect(
                                fret=grace['fret'], duration=grace['value'], velocity=grace['velocity'],
                                transition=M.GraceEffectTransition[grace.get('transition', 'none')],
                                isDead=grace.get('dead', False), isOnBeat=grace.get('on_beat', False))
                        g.notes.append(written_note)
                        note_count += 1
                    if lane_order != sorted(lane_order):
                        _fail(beat['id'], 'noncanonical chord lane order would be changed by GP')
                    voice.beats.append(g)
                    cursor += length
                if not entries:
                    voice.beats.append(M.Beat(voice, status=M.BeatStatus.empty, duration=M.Duration(1)))

    # TG applies the last traversed mix-table tempo to the complete measure.
    # Emit only one boundary change, on an existing authored beat.
    for mi, (a, _, measure) in enumerate(measures):
        bpm = clock.tempo_at(a)
        if mi and bpm != clock.tempo_at(measures[mi - 1][0]):
            eligible = [beat for t in target.tracks for v in t.measures[mi].voices for beat in v.beats
                        if beat.status != M.BeatStatus.empty and beat.start == 960 + int(a * 960)]
            if not eligible:
                _fail(measure['id'], 'tempo change needs an authored beat at the measure start')
            eligible[0].effect.mixTableChange = M.MixTableChange(tempo=M.MixTableItem(bpm, duration=0))

    if version < 5:
        # TG's GP3/GP4 readers take endings as a cumulative ordinal: passes
        # 1..n minus those already claimed since the last repeat open.
        existing = 0
        for header in target.measureHeaders:
            if header.isRepeatOpen:
                existing = 0
            mask = header.repeatAlternative
            if mask and ((1 << mask.bit_length()) - 1) & ~existing != mask:
                _fail(f'm{header.number}', f'GP{version} endings are cumulative ordinals; mask {mask:#x} after '
                                           f'{existing:#x} cannot be stored')
            existing |= mask

    class NativeGP5Writer(GP5File):
        def writeMeasureHeaderValues(self, header, flags):
            # GP5 beams precede the alternate mask; installed 0.11 reverses
            # these fields. Matches the retained source-qualified fixture.
            self.writeU8(flags)
            if flags & 1:
                self.writeI8(header.timeSignature.numerator)
            if flags & 2:
                self.writeI8(header.timeSignature.denominator.value)
            if flags & 8:
                self.writeU8(header.repeatClose + 1)
            if flags & 0x20:
                self.writeMarker(header.marker)
            if flags & 0x40:
                self.writeI8(header.keySignature.value[0])
                self.writeI8(header.keySignature.value[1])
            if flags & 3:
                for beam in header.timeSignature.beams:
                    self.writeU8(beam)
            if flags & 0x10:
                self.writeRepeatAlternative(header.repeatAlternative)
            else:
                self.placeholder(1)
            self.writeU8(header.tripletFeel.value)

    def ordinal(writer, value):  # PyGuitarPro writes the end of the FIRST run of bits
        writer.writeU8(value.bit_length())

    def legacy_grace(writer, grace):
        # TG's GP3/4 format uses transition BEFORE duration; the dependency
        # writes these in reverse order. Dead grace is the unsigned 255 fret.
        writer.writeU8(255 if grace.isDead else grace.fret)
        writer.writeU8(writer.packVelocity(grace.velocity))
        writer.writeU8(grace.transition.value)
        writer.writeU8({64: 1, 32: 2, 16: 3}[grace.duration])

    legacy_methods = dict(writeRepeatAlternative=ordinal, writeGrace=legacy_grace)
    def gp3_header_flags(writer, header, previous=None):
        flags = GP3File.packMeasureHeaderFlags(writer, header, previous)
        if previous is None or header.keySignature != previous.keySignature:
            flags |= 0x40
        return flags | (0x80 if header.hasDoubleBar else 0)

    def gp3_header_values(writer, header, flags):
        GP3File.writeMeasureHeaderValues(writer, header, flags)
        if flags & 0x40:
            writer.writeI8(header.keySignature.value[0])
            writer.writeI8(header.keySignature.value[1])

    writer = {5: NativeGP5Writer, 4: type('NativeGP4Writer', (GP4File,), legacy_methods),
              3: type('NativeGP3Writer', (GP3File,), {**legacy_methods,
                  'packMeasureHeaderFlags': gp3_header_flags, 'writeMeasureHeaderValues': gp3_header_values})}[version]
    output = io.BytesIO()
    writer(output, encoding, version=f'FICHIER GUITAR PRO v{version}.00', versionTuple=(version, 0, 0)).writeSong(target)
    data = output.getvalue()
    _native_gp_song(_read_native_gp(data, encoding), target.title)
    warnings = [
            'Sample audio, keymaps, envelopes and DSP are not embedded; explicit GP programs replace their sounds.',
            'Native identities, instrument slots and pattern sharing are not GP data; authored measures, ties and repeats are retained.',
            'GP mixer steps retain native volume/pan multiples of four; source MIDI controllers use max(step*8-1,0).',
            f'Text uses {encoding}; choose the same Guitar Pro import encoding in TuxGuitar.']
    if key.value[1]:  # GP5 only; GP3/4 refused above
        warnings.append('The GP5 file retains minor mode, but installed TuxGuitar discards the mode byte when importing it.')
    if credits.get('date'):
        warnings.append('Song date is not stored in Guitar Pro 3-5.')
    if len(comments.splitlines()) > 1:
        warnings.append('Guitar Pro retains separate comment lines; TuxGuitar 2.1 concatenates them without line breaks on import.')
    if version == 5 and any(credits.get(k) for k in ('author', 'writer', 'transcriber')):
        warnings.append('GP5 retains composer/lyricist/transcriber in its standard music/words/tab fields. '
                        'TuxGuitar 2.1 reads words as author and tab as writer, and discards music; '
                        'those credits may change or disappear if this file is rewritten in TuxGuitar.')
    if rerouted_notes:
        warnings.append(f'{rerouted_notes} notes on native spare channels use their GP track/voice routing; '
                        'notation and musical timing are retained, but native instrument release tails and channel identities are not GP data.')
    if artificial_harmonics and version == 5:
        warnings.append('Artificial harmonics use canonical GP5 pitch/octave fields; TuxGuitar ignores those fields '
                        'and plays native harmonic data0. Other Guitar Pro players may interpret them differently.')
    if fade_in:
        warnings.append('Fade-in follows track-wide MIDI expression in Guitar Pro/TuxGuitar; '
                        'source synthesizer timbre and sample-engine levels are not reproduced by the file.')
    if generated_rests:
        warnings.append(f'{generated_rests} explicit rests added in the export to preserve silent gaps and pickup timing; the native score is unchanged.')
    return data, dict(format=f'Guitar Pro {version}.00', encoding=encoding, tracks=len(target.tracks), measures=len(measures),
                     notes=note_count, generated_rests=generated_rests, channels=routes, warnings=warnings)
