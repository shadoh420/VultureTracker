"""Immutable render snapshots shared by phrase comparisons and export jobs."""
import copy
import glob
import itertools
import json
import math
import os
from fractions import Fraction
from pathlib import Path
import re
import shutil
import tempfile
import threading
import uuid
from bisect import bisect_left, bisect_right

from . import api
from .model import ORDER_END
from .notation import format_cell
from .openmpt import LoadedModule
from .fileio import atomic_write, device_name, link_new, protect_outputs, wav_bytes
from .history import digest
from .song import SongError

RATE = 44100


def map_jumps(spec, target):
    out = copy.deepcopy(spec)
    data = out.get('data', '') if isinstance(out, dict) else str(out)
    rows = []
    for row in data.splitlines(keepends=True):
        body, sep, comment = row.partition(';')
        rows.append(api._JUMP.sub(lambda m: f'B{target(int(m.group(1), 16)):02X}', body) + sep + comment)
    if isinstance(out, dict):
        out['data'] = ''.join(rows)
        return out
    return ''.join(rows)


def _ring_out(base, folder, mod, region, muted, mix, tail, loop=False):
    """(standalone IT, audio IT, seconds, seek) of `region`: the audio plays the orders before it for the player's state,
    then the region, then empty patterns through which what still sounds rings out. `loop`: the region plays twice and
    the audio starts at the second pass, so it begins with what its own end leaves ringing, as a looping game plays it."""
    from .measure import patch_it
    a, r0, b, r1 = map(int, region)
    if not 0 <= a <= b < len(mod.orders) or any(mod.orders[o] >= len(mod.patterns) for o in (a, b)):
        raise ValueError('Region endpoints must be playable orders')
    endpat = mod.patterns[mod.orders[b]]
    if not 0 <= r0 < len(mod.patterns[mod.orders[a]].rows) or not 0 <= r1 < len(endpat.rows) or (a == b and r0 > r1):
        raise ValueError('Invalid row range')
    # IT export is a standalone order slice; audio warms up all preceding orders to recover player state.
    standalone = copy.deepcopy(base)
    standalone['orders'] = list(base['orders'][a:b+1]) + ['---']
    standalone['patterns'] = {k: map_jumps(v, lambda t: t-a if a <= t <= b else b-a+1)
                              for k, v in base['patterns'].items() if k in base['orders'][a:b+1]}
    it = patch_it(api.compile_song(standalone, folder)[0], muted, mix)
    base = copy.deepcopy(base)
    base['patterns'] = {k: map_jumps(v, lambda t: t if t <= b else b+1) for k, v in base['patterns'].items()}
    base['orders'] = list(base['orders'][:b+1])
    name = next(n for n in (f'vt_end_{i}' for i in itertools.count()) if n not in base['patterns'])
    base['patterns'][name] = {'rows': r1+1, 'data': '\n'.join(' | '.join(format_cell(c) for c in row) for row in endpat.rows[:r1+1]) + '\n'}
    base['patterns'][name] = map_jumps(base['patterns'][name], lambda t: b+1)  # a jump out of it (a loop back too) ends the section
    # A break out of the last included pattern starts the empty tail at row zero.
    base['patterns'][name]['data'] = re.sub(r'(?<![^\s|])C[0-9A-F]{2}(?![^\s|])', 'C00', base['patterns'][name]['data'])
    base['patterns'][name+'_tail'] = {'rows': 200, 'data': ''}
    tails = [name+'_tail'] * (1 + int(tail / 1.9))
    s = a
    if loop:
        jumps = []
        for p in base['orders'][a:b]:
            map_jumps(base['patterns'].get(p, ''), lambda t: jumps.append(t) or t)
        if jumps:
            raise ValueError('A game loop needs a region without position jumps (Bxx) before its last pattern')
        s = b+1  # the second pass, whose end jumps on to the tail
        base['patterns'][name+'_again'] = map_jumps(base['patterns'][name], lambda t: 2*b-a+2)
        tails = list(base['orders'][a:b]) + [name+'_again'] + tails
    base['orders'] = base['orders'][:b] + [name] + tails
    render_it = patch_it(api.compile_song(base, folder)[0], muted, mix)
    with LoadedModule(render_it) as lm:
        end = lm.order_start(s+b-a+1)
        start = lm.order_start(s, r0)
    if end <= start:
        raise ValueError('The selected region does not have a forward playback span; adjust its jumps before exporting')
    return it, render_it, end-start, (s, r0)


def snapshot(song, folder, region=None, mix=None, muted=(), tail=2.0, loop=False):
    from .measure import patch_it
    from .sample_edit import voice_entry
    from .tablature import TempoClock
    base = copy.deepcopy(song)
    base.pop('sections', None)
    assets = {p.resolve(): digest(p.read_bytes()) for p in api.output_sources(base, folder)}
    mix = copy.deepcopy(mix or {})
    for num, edit in (mix.get('instrument') or {}).items():
        if int(num) in (base.get('instruments') or {}):
            base['instruments'][int(num)] = voice_entry(base['instruments'][int(num)], edit)
    prepared = api.prepare_playback(base, folder, RATE * 2)
    whole, mod, warnings = prepared['backing_it'], prepared['module'], prepared['warnings']
    tail = float(tail)
    if not 0 <= tail <= 10:
        raise ValueError('Tail must be between 0 and 10 seconds')
    if prepared['plan'] is not None:
        if loop:
            raise ValueError('Native score game-loop exports require repeated-region warm-up')
        if any(not p.is_file() or digest(p.read_bytes()) != sha for p, sha in assets.items()):
            raise ValueError('A source asset changed while compiling the export snapshot; retry after it is saved')
        plan = prepared['plan']
        start_at, end_at = Fraction(0), Fraction(*plan['duration']['quarters'])
        seek, end = None, None
        if region is not None:
            from .tablature import resolve_source_region
            region = resolve_source_region(plan, region)
            a, r0, b, r1 = region
            occurrences = plan['occurrences']
            backing = mod.playback_backing()
            if (any(type(x) is not int for x in region) or not 0 <= a <= b < len(occurrences) or
                    not 0 <= r0 < len(backing.patterns[backing.orders[a]].rows) or
                    not 0 <= r1 < len(backing.patterns[backing.orders[b]].rows) or (a == b and r0 > r1)):
                raise ValueError('Invalid native score row range')
            seek = (a, r0)
            end = (b + 1, 0) if r1 + 1 == len(backing.patterns[backing.orders[b]].rows) else (b, r1 + 1)
            start_at = Fraction(*occurrences[a]['at']) + r0 * Fraction(*plan['row_step'])
            end_at = Fraction(*occurrences[b]['at']) + (r1 + 1) * Fraction(*plan['row_step'])
        clock = TempoClock(plan['tempo'], plan.get('tempos'))
        duration = float(clock.seconds_at(end_at) - clock.seconds_at(start_at))
        range_at = [[q.numerator, q.denominator] for q in (start_at, end_at)]
        frames = _score_frame(plan, range_at[1], RATE, clock) - _score_frame(plan, range_at[0], RATE, clock)
        frames += round(Fraction(str(tail)) * RATE)
        midi_metadata = {'title': mod.title, 'message': mod.message, 'key': mod.key,
                         'channels': [c.name for c in mod.channels], 'meters': [], 'markers': [], 'texts': {},
                         'score_tracks': {ch: identity for identity, track in base['score']['tracks'].items()
                                          for ch in track['channels']},
                         'assignments': {ch: {k: v for k, v in track['midi'].items() if k in ('program', 'bank')}
                                         for track in base['score']['tracks'].values() if 'midi' in track
                                         for ch in track['channels']}}
        source_notes = {(pattern, note['id']): note
                        for pattern, spec in base['score']['patterns'].items()
                        for beat in spec.get('beats', []) for note in beat['notes']}
        midi_metadata['transpose_exempt'] = []
        midi_metadata['harmonic_attacks'] = []
        for event in plan['events']:
            if event['type'] != 'note_on':
                continue
            source = source_notes.get((event.get('source_pattern', event.get('pattern')), event.get('note')), {})
            if event.get('role') == 'grace' or event.get('pulse', 0) % 2 and 'trill' in source:
                midi_metadata['transpose_exempt'].append(event['id'])
            if 'layers' in event and 'harmonic' in source:
                midi_metadata['harmonic_attacks'].append(event['id'])
        lyrics_tracks = [identity for identity, track in base['score']['tracks'].items() if 'lyrics' in track]
        if lyrics_tracks:
            midi_metadata['lyrics_tracks'] = lyrics_tracks
        for field in ('pan', 'volume'):
            source_values, sources = {}, []
            overridden = {int(ch) for ch in mix.get(field, {})}
            for identity, track in base['score']['tracks'].items():
                binding = track.get('midi', {}).get('source_' + field)
                if binding is None:
                    continue
                channels = track['channels']
                reason = ('explicit_mix_override' if overridden.intersection(channels) else
                          'mixer_changed' if any(getattr(mod.channels[ch], field) != binding['mixer_' + field] for ch in channels)
                          else 'preserved')
                sources.append(dict(track=identity, **binding, channels=list(channels), reason=reason))
                if reason == 'preserved':
                    source_values.update({ch: binding['value'] for ch in channels})
            if sources:
                midi_metadata['source_' + field + 's'] = source_values
                midi_metadata[field + '_sources'] = sources
        source_starts = {o['id']: Fraction(*o['at']) for o in prepared['view']['occurrences']}
        for measure in base['score'].get('measures', []):
            point = measure['from']
            source_at = source_starts[point['occurrence']] + Fraction(*point['at'])
            for occurrence in plan['occurrences']:
                origin = source_starts[occurrence.get('source_occurrence', occurrence['id'])]
                local = source_at - origin - Fraction(*occurrence.get('source_from', [0, 1]))
                if not 0 <= local < Fraction(*occurrence['duration']):
                    continue
                at = Fraction(*occurrence['at']) + local
                midi_metadata['meters'].append({'at': [at.numerator, at.denominator],
                                                'meter': list(measure['meter'])})
                if 'marker' in measure:
                    midi_metadata['markers'].append(dict(at=[at.numerator, at.denominator], **measure['marker']))
        for occurrence in plan['occurrences']:
            for beat in base['score']['patterns'].get(occurrence.get('source_pattern', occurrence['pattern']), {}).get('beats', []):
                if beat.get('text'):
                    local = Fraction(*beat['at']) - Fraction(*occurrence.get('source_from', [0, 1]))
                    if not 0 <= local < Fraction(*occurrence['duration']):
                        continue
                    at = Fraction(*occurrence['at']) + local
                    track = base['score']['tracks'][beat['track']]
                    entry = midi_metadata['texts'].setdefault(beat['track'], dict(name=track.get('name', beat['track']), events=[]))
                    entry['events'].append(dict(at=[at.numerator, at.denominator], text=beat['text']))
        return {'it': None, 'render_it': patch_it(whole, muted, mix), 'plan': plan,
                'seek': seek, 'end': end, 'tail': tail, 'range_at': range_at,
                'midi_metadata': midi_metadata,
                'seconds': duration, 'frames': frames,
                'channels': len(mod.channels), 'warnings': warnings, 'loop': None}
    base = api.playback_document(base, mod)  # ring-out transforms a disposable playback projection, not score identities
    it = patch_it(whole, muted, mix)
    with LoadedModule(it) as lm:
        duration = lm.duration()
    seek = None
    if region:
        it, render_it, duration, seek = _ring_out(base, folder, mod, region, muted, mix, tail, loop)
    else:
        render_it = it
        # The whole song rings out like a section when it ends on its last order (a loop back there included); when a
        # jump elsewhere ends it, the tail stays silence.
        stop = mod.orders.index(ORDER_END) if ORDER_END in mod.orders else len(mod.orders)
        last = max((i for i in range(stop) if mod.orders[i] < len(mod.patterns)), default=None)
        if tail and last is not None:
            try:
                ring = _ring_out(base, folder, mod, (0, 0, last, len(mod.patterns[mod.orders[last]].rows) - 1), muted, mix, tail)
                if abs(ring[2] - duration) < 1e-3:
                    render_it = ring[1]
            except ValueError:
                pass
    if any(not p.is_file() or digest(p.read_bytes()) != sha for p, sha in assets.items()):
        raise ValueError('A source asset changed while compiling the export snapshot; retry after it is saved')
    return {'it': it, 'render_it': render_it, 'seek': seek, 'seconds': duration,
            'frames': round((duration+tail)*RATE), 'channels': len(mod.channels), 'warnings': warnings,
            'loop': (0, round(duration*RATE)) if loop and region else None}


PPQ = 480  # OpenMPT's MIDI export resolution


def _vlq(n):
    out = [n & 0x7F]
    while n > 0x7F:
        n >>= 7
        out.insert(0, 0x80 | (n & 0x7F))
    return bytes(out)


def _midi_track(events, end=None):
    """An MTrk from [(tick, order, bytes)]: sorted by tick, then order (meta and controllers, note-offs, note-ons, as
    OpenMPT queues a row's note-ons last), delta times, the end-of-track meta."""
    body, now = b"", 0
    for tick, _, msg in sorted(events, key=lambda e: (e[0], e[1])):
        if end is not None and (not 0 <= tick <= end or not 0 <= tick - now <= 0x0FFFFFFF):
            raise ValueError('Native MIDI: event time or delta exceeds the SMF limit')
        body += _vlq(tick - now) + msg
        now = tick
    if end is not None and not 0 <= end - now <= 0x0FFFFFFF:
        raise ValueError('Native MIDI: end-of-track delta exceeds the SMF limit')
    body += _vlq(0 if end is None else end - now) + b"\xff\x2f\0"
    if end is not None and len(body) > 0xFFFFFFFF:
        raise ValueError('Native MIDI: track exceeds the SMF chunk limit')
    return b"MTrk" + len(body).to_bytes(4, "big") + body


def _meta(kind, data):
    return bytes([0xFF, kind]) + _vlq(len(data)) + data


def to_midi(it):
    """A standard MIDI file (type 1, 480 ticks a quarter) of the module `it`, as OpenMPT's MIDI export (mod2midi.cpp)
    writes one: a first track with the song's name, message, time signature (rows per bar over rows per beat, in
    quarters), tempo at each change of libopenmpt's BPM, and the global volume as a master-volume SysEx; then a track
    per instrument played (per sample in a song without instruments), named after it. A tracker channel plays on MIDI
    channel (channel mod 15, skipping 10), its pan as CC 10 at the first note; a note is the instrument's note map,
    its velocity the volume column (or the sample's volume) doubled, a note-off at the next note, `===`, `^^^`, `~~~`
    or the song's end. Rows are timed as libopenmpt plays them (jumps and loops included); a note delayed by SDx starts
    that many ticks into its row; a tone portamento (G) holds the note it slides. Every other effect is left out and
    counted in the warnings. Muted channels are left out. Returns (bytes, warnings)."""
    from .itreader import read_it
    from .model import NOTE_CUT, NOTE_FADE, NOTE_OFF
    mod, _ = read_it(it)
    with LoadedModule(it) as lm:
        rows = lm.row_starts(RATE)
        end = lm.end
    beat, bar = (mod.row_highlight[0] or 4), (mod.row_highlight[1] or 16)
    segs, bpm0 = [], None  # (second, tick, bpm) where the tempo changes

    def tick(t):
        s = next((s for s in reversed(segs) if s[0] <= t), segs[0])
        return round(s[1] + (t - s[0]) * s[2] * PPQ / 60)
    conductor = [(0, 0, _meta(3, mod.title.encode("latin-1", "replace")))]
    if mod.message:
        conductor.append((0, 0, _meta(1, mod.message.encode("latin-1", "replace"))))
    conductor.append((0, 0, _meta(0x58, bytes([max(1, bar // beat), 2, 24, 8]))))
    gv = lambda v: (lambda m: bytes([0xF0, 0x07, 0x7F, 0x7F, 0x04, 0x01, m & 0x7F, (m >> 7) & 0x7F, 0xF7]))(2 * v * 0x3FFF // 256)
    conductor.append((0, 0, gv(mod.global_volume)))
    tracks, pans_sent, dropped = {}, {}, {}
    sounding = {}  # tracker channel -> (track key, midi channel, note)
    last_ins = {}
    ins_mode = mod.instruments is not None
    for t, order, row, bpm, speed in rows:
        if bpm and bpm != bpm0:
            segs.append((t, tick(t) if segs else 0, bpm))
            conductor.append((tick(t), 0, _meta(0x51, round(60_000_000 / bpm).to_bytes(3, "big"))))
            bpm0 = bpm
        if not 0 <= order < len(mod.orders) or mod.orders[order] >= len(mod.patterns):
            continue
        cells = mod.patterns[mod.orders[order]].rows
        if row >= len(cells):
            continue
        for ch, cell in enumerate(cells[row]):
            if ch >= len(mod.channels) or mod.channels[ch].muted:
                continue
            letter = chr(64 + cell.effect) if 1 <= cell.effect <= 26 else ""
            delay = cell.param & 0xF if letter == "S" and cell.param >> 4 == 0xD else 0
            porta = letter == "G" or (cell.volcmd is not None and 193 <= cell.volcmd <= 202)
            if letter == "V":
                conductor.append((tick(t), 0, gv(min(cell.param, 128))))
            elif letter and letter not in "ABCT" and not (letter == "S" and cell.param >> 4 == 0xD):
                dropped[letter] = dropped.get(letter, 0) + 1
            if cell.volcmd is not None and cell.volcmd > 64:
                dropped["volume column"] = dropped.get("volume column", 0) + 1
            if cell.instrument:
                last_ins[ch] = cell.instrument
            if cell.note is None or (porta and cell.note < 120):
                continue
            if delay >= speed:  # IT plays no note delayed past its row
                continue
            at = tick(t + delay * 60 / (bpm0 * beat * speed))  # a tick lasts 60 / (bpm * rows per beat * speed) s
            if ch in sounding:
                key, mch, note = sounding.pop(ch)
                tracks.setdefault(key, []).append((at, 1, bytes([0x80 | mch, note, 0])))
            if cell.note in (NOTE_OFF, NOTE_CUT, NOTE_FADE) or cell.note >= 120:
                continue
            num = last_ins.get(ch, 0)
            if ins_mode:
                if not 1 <= num <= len(mod.instruments):
                    continue
                note, smp = mod.instruments[num - 1].keymap[cell.note]
            else:
                note, smp = cell.note, num
            if not 1 <= smp <= len(mod.samples) or not mod.samples[smp - 1].data:
                continue
            vol = cell.volcmd if cell.volcmd is not None and cell.volcmd <= 64 else mod.samples[smp - 1].volume
            mch = ch % 15 + (1 if ch % 15 >= 9 else 0)
            pan = min(127, 2 * (32 if mod.channels[ch].pan == 100 else mod.channels[ch].pan))
            if pans_sent.get(mch) != pan:
                tracks.setdefault(num, []).append((at, 0, bytes([0xB0 | mch, 10, pan])))
                pans_sent[mch] = pan
            tracks.setdefault(num, []).append((at, 2, bytes([0x90 | mch, note, min(2 * vol, 127)])))
            sounding[ch] = (num, mch, note)
    for key, mch, note in sounding.values():
        tracks[key].append((tick(end), 1, bytes([0x80 | mch, note, 0])))
    names = mod.instruments if ins_mode else mod.samples
    out = [_midi_track(conductor)]
    for key in sorted(tracks):
        name = (names[key - 1].name if key <= len(names) else "") or f"{'instrument' if ins_mode else 'sample'} {key}"
        out.append(_midi_track([(0, 0, _meta(3, name.encode("latin-1", "replace")))] + tracks[key]))
    data = b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big") + len(out).to_bytes(2, "big") + PPQ.to_bytes(2, "big")
    warnings = [f"MIDI: left out {', '.join(f'{n} {k}' if len(k) > 1 else f'{n} {k}xx' for k, n in sorted(dropped.items()))} "
                f"(effects a MIDI file does not hold)"] if dropped else []
    return data + b"".join(out), warnings


def midi_export_settings(settings=None):
    """TuxGuitar's MIDI export options, with refusal instead of pitch clamping."""
    if settings is None:
        settings = {}
    if not isinstance(settings, dict) or set(settings) - {'transpose', 'strip'}:
        raise ValueError('Native MIDI export settings must be an object containing only transpose and strip')
    transpose, strip = settings.get('transpose', 0), settings.get('strip', False)
    if type(transpose) is not int or not -24 <= transpose <= 24:
        raise ValueError('Native MIDI transpose must be an integer from -24 to 24')
    if type(strip) is not bool:
        raise ValueError('Native MIDI strip must be boolean')
    return dict(transpose=transpose, strip=strip)


def native_to_midi(snap, settings=None):
    """Exact authored gates plus a bounded residual subset, from an immutable native snapshot.

    No IT projection, audio-frame clock or guessed raw note duration. Inheritance,
    NNA and raw slides need the shared engine's qualified state trace before this subset
    can grow. MIDI carries gates/controllers, not the sample renderer's sound.
    """
    from .itreader import read_it
    from .model import Channel, NOTE_OFF
    from .tablature import TempoClock
    settings = midi_export_settings(settings)
    transpose, strip = settings['transpose'], settings['strip']
    plan, metadata = snap['plan'], snap['midi_metadata']
    transpose_exempt = set(metadata.get('transpose_exempt', []))
    harmonic_attacks = set(metadata.get('harmonic_attacks', []))
    clock = TempoClock(plan['tempo'], plan.get('tempos'))
    mod, _ = read_it(snap['render_it'])
    # The IT reader trims channels with no residual cells; score-only parents
    # still have frozen mixer settings in all 64 IT header slots.
    header = snap['render_it']
    mod.channels = [Channel(name=name, pan=header[0x40 + ch] & 0x7F,
                            volume=header[0x80 + ch], muted=bool(header[0x40 + ch] & 0x80))
                    for ch, name in enumerate(metadata['channels'])]
    start, end = (Fraction(*at) for at in snap['range_at'])
    if not 0 <= start < end <= Fraction(*plan['duration']['quarters']):
        raise ValueError('Native MIDI: invalid exact export range')
    pair = lambda q: [q.numerator, q.denominator]
    report = {'mode': 'exact', 'quantized_events': 0, 'max_timing_error_quarters': [0, 1],
              'text_encoding': 'utf-8',
              'range_at': copy.deepcopy(snap['range_at']), 'channels': [], 'instruments': [],
              'clipped_releases': [], 'muted_channels': [i for i, c in enumerate(mod.channels) if c.muted],
              'omitted_audio_tail_seconds': snap['tail'], 'mix_volume': mod.mix_volume, 'separation': mod.separation,
              'losses': ['MIDI preserves note gates, not fingering, written spelling, ties as notation or other score engraving.',
                         'Sample sound, tuning, envelopes, filters, plugins and release tails are not carried in MIDI.',
                         'Volume/pan use rounded MIDI controller/velocity scales; destination synth response may differ.',
                         f'Audio mix-volume gain ({mod.mix_volume}) and stereo separation ({mod.separation}) are omitted.']}
    report.update(settings=settings, lead_in_quarters=[int(strip), 1])
    if transpose:
        report['losses'].append(f'MIDI transpose {transpose:+d} semitones applies to principal, percussion, tremolo and harmonic keys. '
                                'TuxGuitar leaves grace keys and alternate trill keys unchanged, including same-key trills; '
                                'keys outside 0..127 refuse instead of clamping.')
    if strip:
        report['losses'].append('Stripped MIDI omits all control/program changes and master-volume messages, including fades and '
                                'pitch-bend range RPN. Pitch-wheel events remain; their sound depends on the receiving synth range. '
                                'TuxGuitar flags=0 adds one quarter of silence at the SMF default 120 BPM before tempo/meter and notes.')
    if snap['tail']:
        report['losses'].append(f"Finite audio tail ({snap['tail']:g} seconds) omitted; MIDI ends at the score boundary.")
    if metadata.get('lyrics_tracks'):
        report['losses'].append('Track lyrics and their starting measures are omitted from MIDI: ' +
                                ', '.join(metadata['lyrics_tracks']) + '.')
    tempo_points = [start, *sorted({Fraction(*e['at']) for e in plan.get('tempos', [])
                                   if start < Fraction(*e['at']) < end})]
    conductor = [(Fraction(0), 0, _meta(3, metadata['title'].encode('utf-8')))]
    tempo_segments, midi_microseconds, tempo_error = [], Fraction(0), Fraction(0)
    for at, until in zip(tempo_points, [*tempo_points[1:], end]):
        bpm = clock.tempo_at(at)
        tempo = Fraction(60_000_000, bpm)
        mpqn = (tempo.numerator * 2 + tempo.denominator) // (2 * tempo.denominator)
        error = (mpqn - tempo) * (until - at)
        tempo_segments.append(dict(at=pair(at), source_bpm=bpm, microseconds_per_quarter=mpqn,
                                   effective_bpm=60_000_000 / mpqn,
                                   error_microseconds_per_quarter=pair(Fraction(mpqn) - tempo),
                                   duration_error_microseconds=pair(error)))
        conductor.append((at - start, 0, _meta(0x51, mpqn.to_bytes(3, 'big'))))
        midi_microseconds += mpqn * (until - at)
        tempo_error += error
    report['tempo'] = dict(tempo_segments[0], segments=tempo_segments,
                           duration_error_microseconds=pair(tempo_error))
    report['duration_seconds'] = float(midi_microseconds / 1_000_000)
    if any(s['error_microseconds_per_quarter'][0] for s in tempo_segments):
        report['losses'].append('MIDI tempo rounds to integer microseconds per quarter; see conversion tempo precision.')
    if metadata['message']:
        conductor.append((Fraction(0), 0, _meta(1, metadata['message'].encode('utf-8'))))
    if metadata['key']:
        conductor.append((Fraction(0), 0, _meta(1, ('Key: ' + metadata['key']).encode('utf-8'))))
        report['losses'].append('Authored key retained as text, not a MIDI key-signature event.')
    meters = sorted(metadata['meters'], key=lambda m: Fraction(*m['at']))
    initial = next((m['meter'] for m in reversed(meters) if Fraction(*m['at']) <= start), [4, 4])
    if not any(Fraction(*m['at']) <= start for m in meters):
        report['losses'].append('No authored meter at the range start: MIDI initially uses 4/4.')
    for at, meter in [(start, initial), *((Fraction(*m['at']), m['meter']) for m in meters
                                         if start < Fraction(*m['at']) < end)]:
        conductor.append((at - start, 0, _meta(0x58, bytes([meter[0], meter[1].bit_length() - 1, 24, 8]))))
    markers = [m for m in metadata.get('markers', []) if start <= Fraction(*m['at']) < end]
    for marker in markers:
        conductor.append((Fraction(*marker['at']) - start, 0, _meta(6, marker['title'].encode('utf-8'))))
    if any('color' in m for m in markers):
        report['losses'].append('MIDI markers retain their exact anchors and titles; marker colors are omitted.')

    # The raw row and the score attack share a parent transition. Only vxx and an
    # identical explicit instrument can be folded into that attack without a trace.
    def refuse(where, reason):
        raise ValueError(f'Native MIDI: {where}: {reason}')

    source_pans = metadata.get('source_pans', {})
    source_volumes = metadata.get('source_volumes', {})
    for field, values, cc_number in (('pan', source_pans, 10), ('volume', source_volumes, 7)):
        if (not isinstance(values, dict) or any(type(ch) is not int or not 0 <= ch < len(mod.channels) or
                type(value) is not int or not 0 <= value <= 127 for ch, value in values.items())):
            refuse('source ' + field, 'invalid parent or MIDI controller value')
        if metadata.get(field + '_sources'):
            report['source_' + field] = copy.deepcopy(metadata[field + '_sources'])
            report['losses'].append(f'Untouched imported {field} preserves its exact source CC{cc_number}; explicit {field} edits use the '
                                    'existing rounded mixer scale. Audio retains the mixer scale in either case.')

    # Fade belongs to the logical score track, including its unmarked strings.
    # Keep source insertion order when several ramps emit at the same tick.
    from .tablature import fade_expression_streams
    score_tracks = metadata.get('score_tracks', {})
    fades = plan.get('midi_fades', [])
    try:
        fade_streams = fade_expression_streams(fades, metadata.get('score_tracks', {}).values(),
                                               Fraction(*plan['duration']['quarters']))
    except ValueError as exc:
        refuse('fade_in', str(exc))
    fade_times = {track: [e[0] for e in stream] for track, stream in fade_streams.items()}
    fade_events = sum(len(stream) - 1 for stream in fade_streams.values())
    if fades:
        report['fade_in'] = dict(ramps=copy.deepcopy(fades), logical_events=fade_events + len(fade_streams),
            gain_policy='round_half_up(base_expression * logical_CC11 / 127)',
            boundary_policy='Seed preceding state, then ordered boundary CC11 before attack; releases precede new attacks.')
        report['losses'].append('Fade-in follows shared TG track expression in native audio and MIDI. '
                                'Physical CC11 composes the source staircase with existing static gain; '
                                'controllers follow owned gates/pitch controls, not unmeasured synth release tails.')

    score_on, attack_ids, attack_frames = {}, set(), set()
    for event in plan['events']:
        if 'hold' in event and (event['type'] != 'note_on' or type(event['hold']) is not bool):
            refuse(event['id'], 'hold must be boolean and belongs only to note_on')
        if event['type'] != 'note_on':
            if any(key in event for key in ('context', 'context_open', 'context_close')):
                refuse(event['id'], 'context fields belong only to attacks')
            continue
        if any(key in event for key in ('context', 'context_open', 'context_close')) and (
                type(event.get('context')) is not int or not 1 <= event['context'] <= 2147483647 or
                type(event.get('context_open')) is not bool or type(event.get('context_close')) is not bool):
            refuse(event['id'], 'invalid context fields')
        if event.get('hold') and any(key in event for key in ('layers', 'source_id', 'pulse')):
            refuse(event['id'], 'held gates require ordinary single-pitch attacks, not groups or repetition')
        at = Fraction(*event['at'])
        frame = clock.seconds_at(at) * plan['sample_rate']
        frame = frame.numerator // frame.denominator + (2 * (frame.numerator % frame.denominator) >= frame.denominator)
        owner = ('context', event['context']) if 'context' in event else ('parent', event['ch'])
        if event['id'] in attack_ids or (frame, owner) in attack_frames:
            refuse(event['id'], 'duplicate attack identity or same-frame parent')
        attack_ids.add(event['id'])
        attack_frames.add((frame, owner))
        score_on.setdefault((at, event['ch']), []).append(event)
    attacks = [e for values in score_on.values() for e in values]
    contexts, closing, previous_frame, opened = {}, set(), None, set()
    for event in sorted(attacks, key=lambda e: Fraction(*e['at'])):
        frame = _score_frame(plan, event['at'], plan['sample_rate'], clock)
        if frame != previous_frame:
            for key in closing:
                contexts.pop(key)
            closing, previous_frame = set(), frame
        if 'context' not in event:
            continue
        key, binding = event['context'], (event['ch'], event['source_instrument'])
        if event['context_open']:
            # MIDI retains exact onset fractions, which can order distinct heads differently from a rounded
            # audio frame's source-order tie break. Keys must be unique here, not monotonically opened.
            if key in opened or len(contexts) >= 64:
                refuse(event['id'], 'context key/capacity violation')
            contexts[key] = binding
            opened.add(key)
        elif contexts.get(key) != binding:
            refuse(event['id'], 'context is closed or its parent/source changed')
        if event['context_close']:
            closing.add(key)
    if set(contexts) - closing:
        refuse('plan', 'missing context closes')
    held_parents = {e['ch'] for e in attacks if e.get('hold')}
    context_parents = {e['ch'] for e in attacks if 'context' in e}
    for event in attacks:
        if event['ch'] not in held_parents | context_parents:
            continue
        if event['ch'] in context_parents and (type(event.get('context')) is not int or event['context'] <= 0):
            refuse(event['id'], 'every attack on a context parent needs an explicit head context')
        if event['ch'] in held_parents and any(key in event for key in ('layers', 'source_id', 'pulse')):
            refuse(event['id'], 'held overlaps require ordinary single-pitch attacks throughout the parent')
        if not event['source_instrument'] or event['source_instrument'] != event['instrument']:
            refuse(event['id'], 'inherited instrument selection on a held parent requires a qualified state trace')
    # Protection survives key-off into an unknown PCM release tail. Match the
    # engine's whole-parent backing rule even outside this MIDI export range.
    for pattern_index, pattern in enumerate(mod.patterns):
        for row, cells in enumerate(pattern.rows):
            for ch in held_parents | context_parents:
                if ch >= len(cells):
                    continue
                cell = cells[ch]
                if (cell.note is not None or cell.instrument or cell.volcmd is not None or
                        cell.effect not in (0, 20, 22) or not cell.effect and cell.param or
                        cell.effect == 20 and cell.param < 32):
                    refuse(f"pattern {pattern_index} row {row} channel {ch + 1}",
                           'held parent backing must contain only empty cells or global Txx/Vxx throughout playback')
    controls = {}
    for event in plan['events']:
        if event['type'] == 'pitch':
            controls.setdefault(event['id'], []).append(event)
    actions = [(Fraction(*e['at']), 0 if e['type'] == 'note_off' else 2, e['ch'], e['type'], e,
                e['id']) for e in plan['events'] if e['type'] in ('note_on', 'note_off')]
    step = Fraction(*plan['row_step'])
    for order, occurrence in enumerate(plan['occurrences']):
        pattern = mod.patterns[mod.orders[order]]
        for row, cells in enumerate(pattern.rows):
            at = Fraction(*occurrence['at']) + row * step
            if at > end:
                break
            for ch, cell in enumerate(cells):
                if not cell.is_empty():
                    actions.append((at, 1, ch, 'raw', cell, f"{occurrence['id']} row {row} channel {ch + 1}"))
    pans, volumes = [c.pan for c in mod.channels], [c.volume for c in mod.channels]
    global_volume = mod.global_volume
    active, tracks, slots, raw_volumes, notes = {}, {}, {}, {}, []
    assignments = metadata.get('assignments', {})
    drum_control_changes = set()
    clipped = report['clipped_releases']

    def cc(value, maximum):
        return (value * 127 * 2 + maximum) // (2 * maximum)

    midi_pans = [source_pans.get(ch, cc(pan, 64)) for ch, pan in enumerate(pans)]
    midi_volumes = [source_volumes.get(ch, cc(volume, 64)) for ch, volume in enumerate(volumes)]

    def master(value):
        value = (value * 16383 * 2 + 128) // 256
        return bytes([0xF0, 7, 0x7F, 0x7F, 4, 1, value & 127, value >> 7, 0xF7])

    def emit(ch, at, priority, msg):
        if start <= at <= end:
            tracks.setdefault(ch, []).append((at - start, priority, msg))

    def finish(ch, at, identity=None):
        if identity is None:
            matches = [n for n in active.values() if n['ch'] == ch]
            if len(matches) > 1 or any(n['held_cohort'] for n in matches):
                refuse(f'channel {ch + 1}', 'raw release conflicts with an active held cohort')
            identity = matches[0]['id'] if matches else None
            if identity is None:
                return
        if identity not in active:
            refuse(identity, 'note-off has no matching active identity')
        note = active.pop(identity)
        if note['ch'] != ch:
            refuse(identity, 'note-off conflicts with the active identity')
        if note['at'] < start < at:
            refuse(note['id'], 'note carries across the range start; retrigger policy is not enabled')
        if at <= note['at']:
            refuse(note['id'], 'collapsed or reversed note gate')
        note['release'] = min(at, end)
        if start <= note['at'] < end:
            if at > end:
                clipped.append(note['id'])

    # Initial state is emitted after evaluating the prefix, before any range-start event.
    initialized = False
    def initialize():
        nonlocal initialized
        if initialized:
            return
        initialized = True
        conductor.append((Fraction(0), 0, master(global_volume)))
        for ch, channel in enumerate(mod.channels):
            if not channel.muted:
                if pans[ch] == 100:
                    refuse(f'channel {ch + 1}', 'surround pan has no supported MIDI mapping')
                emit(ch, start, 0, bytes([0xB0, 10, midi_pans[ch]]))
                emit(ch, start, 0, bytes([0xB0, 7, midi_volumes[ch]]))

    for at, _, ch, kind, item, where in sorted(actions, key=lambda a: (a[0], a[1], a[2])):
        if at >= start:
            initialize()
        if at >= end and kind != 'note_off' and not (kind == 'raw' and at == end and item.note == NOTE_OFF):
            continue
        if kind == 'raw':
            cell = item
            matches = score_on.get((at, ch), [])
            matching = matches[0] if len(matches) == 1 else None
            if len(matches) > 1 and (cell.note is not None or cell.instrument or cell.volcmd is not None):
                refuse(where, 'raw note/instrument/volume cannot be folded into multiple head contexts')
            if at == end:  # Only an explicit release can close a raw gate at the exclusive boundary.
                if not mod.channels[ch].muted:
                    if cell.instrument or cell.volcmd is not None:
                        refuse(where, 'boundary note-off has unresolved instrument/volume side effects')
                    finish(ch, at)
                continue
            if cell.effect == 22:
                if mod.channels[ch].muted and (cell.note is not None or cell.instrument):
                    refuse(where, 'global volume on a muted note/instrument cell requires a qualified state trace')
                global_volume = min(128, cell.param)
                if at >= start:
                    conductor.append((at - start, 0, master(global_volume)))
            if cell.effect == 20 and (not 32 <= cell.param <= 255 or clock.tempo_at(at) != cell.param):
                refuse(where, 'absolute Txx disagrees with the frozen tempo clock')
            if mod.channels[ch].muted:
                continue
            if cell.effect == 4:
                refuse(where, 'Dxx slide/memory requires a qualified shared-engine control trace')
            if (cell.effect not in (0, 13, 20, 22, 24) or
                    cell.effect == 20 and cell.param < 32 or
                    cell.volcmd is not None and not 0 <= cell.volcmd <= 64):
                refuse(where, 'unsupported residual effect or volume command')
            # Absolute Txx is already captured in the frozen tempo clock. It
            # belongs to the conductor, including when its raw parent is muted.
            if cell.effect == 24:
                if start <= at < end:
                    drum_control_changes.add(ch)
                pans[ch] = Fraction(cell.param * 64, 256)
                midi_pans[ch] = int(cc(pans[ch], 64))
                emit(ch, at, 0, bytes([0xB0, 10, midi_pans[ch]]))
            elif cell.effect == 13:
                if start <= at < end:
                    drum_control_changes.add(ch)
                volumes[ch] = cell.param
                midi_volumes[ch] = int(cc(volumes[ch], 64))
                emit(ch, at, 0, bytes([0xB0, 7, midi_volumes[ch]]))
            if cell.note is None:
                if matching and cell.instrument in (0, matching['source_instrument']):
                    if cell.volcmd is not None:
                        if matching['volume'] is not None:
                            refuse(where, 'raw and score attack both own volume')
                        raw_volumes[at, ch] = cell.volcmd
                    continue
                if cell.instrument or cell.volcmd is not None:
                    refuse(where, 'instrument/volume-only state requires a qualified inheritance trace')
                continue
            if cell.note == NOTE_OFF:
                if cell.instrument or cell.volcmd is not None:
                    refuse(where, 'note-off with instrument/volume has unresolved tracker side effects')
                finish(ch, at)
                continue
            if not 0 <= cell.note < 120:
                refuse(where, 'raw cut/fade is not an ordinary MIDI note-off')
            item = {'id': where, 'pitch': cell.note, 'source_instrument': cell.instrument,
                    'instrument': cell.instrument, 'volume': cell.volcmd}
        elif mod.channels[ch].muted:
            continue
        elif kind == 'note_off':
            if at > end and item['id'] not in active:
                continue  # Its attack is outside the exported range.
            finish(ch, at, item['id'])
            continue
        prior = [n for n in active.values() if n['ch'] == ch]
        context = item.get('context')
        independent = context is not None and all(n.get('context') is not None and n['context'] != context for n in prior)
        if prior and not independent and (kind == 'raw' or any(n['raw'] or not n['hold'] for n in prior)):
            refuse(where, 'overlapping identity or raw note without an explicit held gate')
        if prior and not independent and (any(key in item for key in ('layers', 'source_id', 'pulse')) or
                      any(n['nonordinary'] for n in prior)):
            refuse(where, 'held overlaps require ordinary single-pitch attacks, not groups or repetition')
        slot = item['source_instrument']
        if not slot or slot != item['instrument']:
            refuse(where, 'inherited instrument selection requires a qualified shared-engine state trace')
        instrument = mod.instruments[slot - 1] if mod.instruments and 1 <= slot <= len(mod.instruments) else None
        if mod.instruments and instrument is None:
            refuse(where, 'instrument slot is absent')
        if instrument and (instrument.nna or instrument.dct or instrument.random_volume or instrument.random_pan
                           or instrument.pan is not None or instrument.pitch_pan_separation):
            refuse(where, 'NNA, duplicate-note checks or instrument volume/pan variation require a state trace')
        layers = []
        percussion = assignments.get(ch, {}).get('bank') == 128
        if percussion and start <= at < end:
            if kind == 'raw':
                refuse(where, 'raw percussion attacks need a qualified authored key and identity')
            if 'layers' in item:
                refuse(where, 'percussion harmonic layers are not supported')
        source_layers = item.get('layers', [dict(pitch=item['pitch'], velocity=item.get('velocity'))])
        added_lower = None
        if transpose and item['id'] in harmonic_attacks:
            # TG tests the transposed harmonic key before adding its lower octave.
            primary = source_layers[-1]
            lower_before, lower_after = primary['pitch'] > 12, primary['pitch'] + transpose > 12
            if lower_before != lower_after:
                source_layers = [dict(layer) for layer in source_layers]
                if lower_before:
                    source_layers.pop(-2)
                else:
                    if instrument:
                        refuse(where, 'new harmonic lower octave with an instrument keymap requires a qualified mapping')
                    added_lower = dict(pitch=primary['pitch'], velocity=max(15, primary['velocity'] - 64))
                    source_layers.insert(-1, added_lower)
                report['losses'].append(f"{item['id']}: transposition {'adds' if lower_after else 'removes'} the harmonic lower octave, "
                                        'following TuxGuitar\'s positive-key condition.')
        for layer in source_layers:
            pitch, sample = instrument.keymap[layer['pitch']] if instrument else (layer['pitch'], slot)
            if not 0 <= pitch <= 127 or not 1 <= sample <= len(mod.samples) or not mod.samples[sample - 1].length:
                refuse(where, 'keymap/sample cannot produce a resolved MIDI attack')
            sample = mod.samples[sample - 1]
            if sample.pan is not None:
                refuse(where, 'sample pan override requires a qualified shared-engine state trace')
            volume = item['volume']
            if volume is None:
                volume = raw_volumes.get((at, ch), sample.volume)
            gain = Fraction(volume * sample.global_volume, 64 * 64)
            if instrument:
                gain *= Fraction(instrument.global_volume, 128)
            authored_velocity = layer['velocity']
            velocity = int(cc(gain, 1)) if authored_velocity is None else authored_velocity
            if not 1 <= velocity <= 127:
                refuse(where, 'zero/sub-velocity attack cannot preserve its gate with MIDI velocity zero')
            if percussion:
                # Kit keymaps select a sample and its playback pitch. MIDI's
                # drum key selects the articulation, so retain the authored key.
                pitch = layer['pitch']
                if not 1 <= pitch <= 100:
                    refuse(where, 'percussion authored key must be in 1..100')
            if item['id'] not in transpose_exempt:
                pitch += transpose
            if layer is added_lower:
                pitch -= 12
            if not 0 <= pitch <= 127:
                refuse(where, 'transposed MIDI key is outside 0..127; clamping is not enabled')
            layers.append(dict(pitch=pitch, velocity=velocity,
                               expression=127 if authored_velocity is None else int(cc(gain, 1))))
        active[item['id']] = dict(id=item['id'], at=at, ch=ch, layers=layers, raw=kind == 'raw',
                                 hold=item.get('hold', False), held_cohort=bool(prior) or item.get('hold', False),
                                 context=context,
                                 nonordinary=any(key in item for key in ('layers', 'source_id', 'pulse')))
        active[item['id']].update({key: item[key] for key in ('source_id', 'pulse', 'role', 'source_note_id', 'source_occurrence', 'play_id') if key in item})
        notes.append(active[item['id']])
        if start <= at < end:
            slots[slot] = (instrument or sample).name
    initialize()
    for note in active.values():
        if note['raw']:
            if note['at'] < start:
                refuse(note['id'], 'note carries across the range start; retrigger policy is not enabled')
            refuse(note['id'], 'raw note has no explicit note-off before the range end')
        refuse(note['id'], 'score gate has no matching explicit note-off')
    # A physical channel owns one layer until both its gate and controls end.
    # Keep every channel's messages in one SMF track: cross-track ordering at a
    # channel reuse boundary is undefined, even when the ticks are identical.
    used = [note for note in notes if start <= note['at'] < end]
    held = [note for note in used if note['hold']]
    if held:
        report['held_gates'] = [dict(id=n['id'], source_channel=n['ch'], at=pair(n['at']),
                                    release=pair(n['release'])) for n in held]
        report['held_gate_policy'] = ('Held score gates retain their scheduled releases across parent replacement; '
                                      'melodic voices use independent MIDI channels; drums share channel 9 by key.')
    report['instruments'] = [{'slot': slot, 'name': name, 'program': None} for slot, name in sorted(slots.items())]
    routed, owners, unspecified, mappings = {}, {}, set(), set()
    drum_state, drum_keys = None, {}
    report['pitch'] = dict(range_semitones=12, max_error_semitones=[0, 1])
    report['voices'] = []
    max_pitch_error = Fraction(0)
    routed_fades = 0
    for note in sorted(used, key=lambda n: (n['at'], n['ch'])):
        ch, at, release = note['ch'], note['at'], note['release']
        name = metadata['channels'][ch] or f'Channel {ch + 1}'
        assignment = assignments.get(ch)
        sound = None if assignment is None else (assignment.get('bank', 0), assignment['program'])
        percussion = sound is not None and sound[0] == 128
        if percussion:
            if controls.get(note['id']):
                refuse(note['id'], 'percussion pitch controls are not supported')
            if ch in drum_control_changes:
                refuse(note['id'], 'percussion parent volume/pan changes in the export range are not supported')
        bends = []
        for event in sorted(controls.get(note['id'], []), key=lambda e: Fraction(*e['at'])):
            when, semitones = Fraction(*event['at']), Fraction(str(event['semitones']))
            if event['ch'] != ch or when < at or not -12 <= semitones <= 12:
                refuse(note['id'], 'invalid pitch identity, timestamp or +/-12-semitone range')
            if when > end:
                continue
            # TG's 64-neutral wheel has 1/128 steps. The frozen native plan
            # carries those offsets exactly; arbitrary native offsets round to
            # the nearest 14-bit wheel value (positive endpoint is 8191).
            value = (semitones + 12) * 8192 / 12
            value = min(16383, (value.numerator * 2 + value.denominator) // (2 * value.denominator))
            max_pitch_error = max(max_pitch_error, abs(Fraction((value - 8192) * 12, 8192) - semitones))
            bends.append((when, bytes([0xE0, value & 127, value >> 7])))
        held_until = max([release, *(when for when, _ in bends)])
        logical_track = score_tracks.get(ch)
        expression_stream = fade_streams.get(logical_track, [])
        if percussion and expression_stream:
            refuse(note['id'], 'percussion expression fades are not supported')
        expression_times = fade_times.get(logical_track, [])
        fade_begin = bisect_left(expression_times, at)
        fade_end = bisect_right(expression_times, held_until)
        logical_expression = expression_stream[fade_begin - 1][2] if fade_begin else 127
        parent_controls = sorted(tracks.get(ch, []), key=lambda e: (e[0], e[1]))
        initial = {}
        for when, _, msg in parent_controls:
            if when + start <= at:
                initial[msg[1]] = msg[2]
        for index, layer in enumerate(note['layers']):
            if percussion:
                # One fixed shared state for this bounded route. Reject rather
                # than overwrite controls needed by another sounding drum.
                state_key = (sound[1], initial[7], initial[10], layer['expression'])
                if drum_state is not None and drum_state != state_key:
                    refuse(note['id'], 'percussion tracks/parents require identical fixed program, volume, pan and expression')
                drum_state = state_key
                if drum_keys.get(layer['pitch'], at) > at:
                    refuse(note['id'], f"percussion key {layer['pitch']} overlaps another gate on channel 9")
                drum_keys[layer['pitch']] = release
            available = [9] if percussion else [channel for channel in range(16) if channel != 9 and
                         (channel not in owners or owners[channel]['until'] <= at and
                          (owners[channel]['sound'] is None) == (sound is None))]
            if not available:
                refuse(note['id'], 'more than 15 independent melodic channels or incompatible unspecified/program ownership; '
                       'multiport routing is not enabled')
            midi_ch = min(available, key=lambda channel: (
                0 if channel in owners and owners[channel]['ch'] == ch else 1 if channel not in owners else 2, channel))
            previous = owners.get(midi_ch)
            messages = routed.setdefault(midi_ch, [])
            def send(when, priority, msg):
                messages.append((when - start, priority, bytes([msg[0] | midi_ch]) + msg[1:]))
            if previous is None:
                messages.append((Fraction(0), 0, _meta(3, name.encode('utf-8'))))
            if sound is not None and (previous is None or previous['sound'] != sound):
                bank, program = sound
                if not percussion:
                    send(at, 4, bytes([0xB0, 0, bank >> 7]))
                    send(at, 4, bytes([0xB0, 32, bank & 127]))
                send(at, 4, bytes([0xC0, program]))
            state = dict(previous['controllers']) if previous is not None else {11: 127}
            if percussion and previous is None:
                for control, value in ((11, layer['expression']), (93, 0), (91, 0), (95, 0), (92, 0)):
                    send(at, 4, bytes([0xB0, control, value]))
                    state[control] = value
            for control, value in initial.items():
                if previous is None or state.get(control) != value:
                    send(at, 4, bytes([0xB0, control, value]))
                    state[control] = value
            expression = (layer['expression'] * logical_expression * 2 + 127) // 254
            initial_event = bool(expression_stream and fade_begin == 0 and expression_stream[0][0] == at)
            if not initial_event and (state[11] != expression or expression_stream and previous is None):
                send(at, 4, bytes([0xB0, 11, expression]))
                state[11] = expression
            for when, _, logical in expression_stream[fade_begin:fade_end]:
                routed_fades += 1
                if routed_fades > 200000:
                    refuse('fade_in', 'more than 200000 routed expression events; split the MIDI export')
                expression = (layer['expression'] * logical * 2 + 127) // 254
                send(when, 5 if when == at else 0, bytes([0xB0, 11, expression]))
                state[11] = expression
            # Select pitch-bend sensitivity RPN, set semitones/cents, then null
            # the RPN so later data-entry messages cannot change the range.
            if bends and (previous is None or not previous['bend_ready']):
                for control, value in ((101, 0), (100, 0), (6, 12), (38, 0), (101, 127), (100, 127)):
                    send(at, 4, bytes([0xB0, control, value]))
                send(at, 4, b'\xe0\x00\x40')
            for when, _, msg in parent_controls:
                if at < when + start <= held_until:
                    send(when + start, 0, msg)
                    state[msg[1]] = msg[2]
            send(at, 6, bytes([0x90, layer['pitch'], layer['velocity']]))
            send(release, 1, bytes([0x80, layer['pitch'], 0]))
            for when, msg in bends:
                send(when, 5 if when == at else 2, msg)
            if bends:
                send(held_until, 3, b'\xe0\x00\x40')
            owners[midi_ch] = dict(ch=ch, until=held_until, sound=sound, controllers=state,
                                  bend_ready=bool(bends) or previous is not None and previous['bend_ready'])
            if (ch, midi_ch) not in mappings:
                mapping = dict(source_channel=ch, midi_channel=midi_ch, name=name)
                if sound is not None:
                    mapping.update(bank=sound[0], program=sound[1])
                else:
                    unspecified.add(ch)
                report['channels'].append(mapping)
                mappings.add((ch, midi_ch))
            report['voices'].append(dict(id=note['id'], layer=index, source_channel=ch, midi_channel=midi_ch,
                                         pitch=layer['pitch'], velocity=layer['velocity'],
                                         at=pair(at), release=pair(release), controls_end=pair(held_until),
                                         **({'hold': True} if note['hold'] else {}),
                                         **({'context': note['context']} if note.get('context') is not None else {}),
                                         **{key: note[key] for key in ('source_id', 'pulse', 'role', 'source_note_id', 'source_occurrence', 'play_id') if key in note}))
    report['pitch']['max_error_semitones'] = pair(max_pitch_error)
    if max_pitch_error:
        report['losses'].append('Pitch offsets round to the nearest 14-bit wheel value; see pitch precision.')
    if controls:
        report['losses'].append('Pitch channels remain owned through their last in-range control, including after note-off; '
                                'destination release tails may differ from the sample renderer.')
    events = [conductor, *routed.values()]
    if unspecified:
        report['losses'].append(f'MIDI destination sounds are unspecified for source channels {sorted(unspecified)}: no bank/program assignments.')
    text_count = 0
    for text_track in metadata.get('texts', {}).values():
        annotations = [(Fraction(*e['at']) - start, 0, _meta(1, e['text'].encode('utf-8')))
                       for e in text_track['events'] if start <= Fraction(*e['at']) < end]
        if annotations:
            events.append([(Fraction(0), 0, _meta(3, text_track['name'].encode('utf-8'))), *annotations])
            text_count += len(annotations)
    report['annotations'] = dict(markers=len(markers), texts=text_count)
    if text_count:
        report['losses'].append('Beat text retains exact anchors in named notation tracks; voice and engraving placement are omitted.')
    if strip:
        events = [[(at + (0 if at == 0 and (msg[:2] == b'\xff\x03' or index == 0 and msg[:2] == b'\xff\x01') else 1), priority, msg)
                   for at, priority, msg in track if msg[0] & 0xF0 not in (0xB0, 0xC0, 0xF0) or msg[0] == 0xFF]
                  for index, track in enumerate(events)]
        report['duration_seconds'] += .5
    denominator = math.lcm((end - start).denominator, *(at.denominator for track in events for at, _, _ in track))
    if denominator > 32767:
        raise ValueError(f'Native MIDI: exact timestamps require PPQ {denominator}, exceeding 32767; no quantization enabled')
    preferred = math.lcm(PPQ, denominator)
    ppq = preferred if preferred <= 32767 else denominator
    report['ppq'] = ppq
    report['note_count'] = sum(msg[0] & 0xF0 == 0x90 for track in events for _, _, msg in track)
    out = [_midi_track([(int(at * ppq), priority, msg) for at, priority, msg in track], int((end - start + int(strip)) * ppq))
           for track in events]
    header = b'MThd' + (6).to_bytes(4, 'big') + (1).to_bytes(2, 'big') + len(out).to_bytes(2, 'big') + ppq.to_bytes(2, 'big')
    return header + b''.join(out), report


def _score_frame(plan, at, rate, clock=None):
    from .tablature import TempoClock
    clock = clock or TempoClock(plan['tempo'], plan.get('tempos'))
    value = clock.seconds_at(Fraction(*at)) * rate
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _plan_at_rate(plan, rate):
    """Reclock a captured plan from its exact musical coordinates, without re-reading song assets."""
    if plan['sample_rate'] == rate:
        return plan
    from .tablature import TempoClock
    clock = TempoClock(plan['tempo'], plan.get('tempos'))
    out = copy.deepcopy(plan)
    def frame(at):
        return _score_frame(plan, at, rate, clock)
    out['sample_rate'] = rate
    out['duration']['frames'] = frame(out['duration']['quarters'])
    starts = {}
    for event in out['events']:
        event['frame'] = frame(event['at'])
        if event['type'] == 'note_on':
            starts[event['id']] = event['frame']
        elif event['type'] == 'note_off' and event['frame'] <= starts[event['id']]:
            raise ValueError('A score note rounds to zero frames at the export sample rate')
    priority = {'note_off': 0, 'note_on': 1, 'pitch': 2, 'gain': 3}
    out['events'].sort(key=lambda e: (e['frame'], priority[e['type']]))
    for position in out['positions']:
        position['frame'], position['end_frame'] = frame(position['at']), frame(position['end'])
        if 'sounding_start' in position:
            position['sounding_start_frame'] = frame(position['sounding_start'])
    return out


def render(snapshot, silenced=(), cancel=None, rate=RATE, depth=16, repeat=0):
    """The snapshot's audio as interleaved stereo bytes at `rate`: int16, or float32 for `depth` 24 and 'float'.
    `repeat` plays the whole song that many more times (its last pass ends where the song does, the tail silence)."""
    from .measure import patch_it
    from .openmpt import mix_rate
    frames = round((snapshot['frames'] / RATE + snapshot['seconds'] * repeat) * rate)
    width = 4 if depth == 16 else 8
    plan = snapshot.get('plan')
    if plan is not None:
        plan = _plan_at_rate(plan, mix_rate(rate, 2))
        start_at, end_at = snapshot['range_at']
        frames = (_score_frame(plan, end_at, rate) - _score_frame(plan, start_at, rate)) * (repeat + 1)
        frames += round(Fraction(str(snapshot['tail'])) * rate)
    data = snapshot['it'] if repeat and plan is None else snapshot['render_it']
    with LoadedModule(patch_it(data, silenced), rate, 2, plan=plan) as lm:
        lm.timed_at(rate)
        if snapshot['seek'] is not None:
            lm.order_start(*snapshot['seek'], cancel=cancel)
        end = snapshot.get('end')
        if plan is not None and end is not None:
            if repeat:
                raise ValueError('Repeat is for whole-song exports, not a native region')
        pcm = lm.render(rate, repeat=repeat, max_seconds=Fraction(frames, rate), cancel=cancel, floats=depth != 16, end=end)
    length = frames * width
    return pcm[:length].ljust(length, b'\0')


def sources(state):
    """Every file an output must not replace: the song, its samples and candidates and the app's files beside it."""
    paths = [state.song_path, *state.files, state.meta_path, state.history_store.path, state.history_store.journal,
             state.notes_path, state.notes_path.with_suffix('.md')]
    paths.extend(state.base_dir.glob(glob.escape(state.song_path.stem) + '.notes-*'))  # the notes archives
    paths.extend((state.base_dir / (state.song_path.stem + '.phrases')).glob('*.json'))  # earlier phrase comparisons
    paths.extend(p for v in (state.meta.get('candidates') or {}).values() for p in v)
    paths.extend(state.base_dir / p for p in (state.meta.get('phrase') or {}).get('assets', {}))
    return paths


RATES = (22050, 32000, 44100, 48000, 88200, 96000)
# Score (notation) formats: the whole authored native score, no audio, as TuxGuitar's writers produce them
NOTATION = ('tg', 'gp3', 'gp4', 'gp5', 'tab', 'ly', 'musicxml')
FORMATS = ('it', 'wav', 'mp3', 'ogg', 'flac', 'mid', *NOTATION)


def loss_lines(fmt, conversion):
    """A notation report's losses as warning lines (TG's are text, the notation writers' are records)."""
    return [f'{fmt.upper()} loss: ' + (x if isinstance(x, str) else
            f"{x.get('scope')}: {x.get('feature')}: {x.get('reason')} ({x.get('count')}x, first {x.get('first')})")
            for x in conversion.get('losses', [])]


def render_settings(options, fmt, region):
    """The render settings in `options`, checked: rate (Hz), depth (16, 24 for WAV and FLAC, 'float' for WAV), bitrate
    (MP3 kbit/s), quality (OGG Vorbis -1 to 10) and repeat (more passes of the whole song, 0 to 16). The defaults are
    the export's: 44.1 kHz, 16 bits, MP3 at 192 kbit/s, OGG at quality 6, one pass."""
    rate = int(options.get('rate') or RATE)
    depth = options.get('depth') or 16
    depth = depth if depth == 'float' else int(depth)
    repeat = int(options.get('repeat') or 0)
    bitrate, quality = options.get('bitrate'), options.get('quality')
    if rate not in RATES:
        raise ValueError(f"Rate is one of {', '.join(map(str, RATES))} Hz")
    if depth not in (16, 24, 'float') or (depth == 24 and fmt not in ('wav', 'flac')) or (depth == 'float' and fmt != 'wav'):
        raise ValueError('Depth is 16 bits, 24 for WAV and FLAC, or float for WAV')
    if bitrate not in (None, '') and (fmt != 'mp3' or not 32 <= int(bitrate) <= 320):
        raise ValueError('Bitrate is for MP3: 32 to 320 kbit/s')
    if quality not in (None, '') and (fmt != 'ogg' or not -1 <= float(quality) <= 10):
        raise ValueError('Quality is for OGG: Vorbis -1 to 10')
    if not 0 <= repeat <= 16 or (repeat and region):
        raise ValueError('Repeat plays the whole song 0 to 16 more times (not a section or a game loop)')
    lufs, ceiling = options.get('master_lufs'), options.get('master_ceiling')
    if lufs not in (None, ''):
        lufs, ceiling = float(lufs), float(-1.0 if ceiling in (None, '') else ceiling)
        if fmt in ('it', 'mid', *NOTATION) or not -40 <= lufs <= -5 or not -12 <= ceiling <= 0:
            raise ValueError('Normalise is for audio: -40 to -5 LUFS, a ceiling of -12 to 0 dBTP')
    else:
        lufs = None
    return {'rate': rate, 'depth': depth, 'repeat': repeat, 'bitrate': int(bitrate) if bitrate not in (None, '') else None,
            'quality': float(quality) if quality not in (None, '') else None,
            'master': {'lufs': lufs, 'ceiling': ceiling} if lufs is not None else None}


def master_gain(pcm, rate, lufs, ceiling):
    """(gain in dB, report) that brings float32 stereo `pcm` to `lufs` integrated loudness, held back where its true
    peak would pass `ceiling` dBTP (a gain, no limiter: the sound is not changed, only its level)."""
    import numpy as np
    from .dsp import measure_mix
    m = measure_mix(np.frombuffer(pcm, '<f4').reshape(-1, 2).T, rate)
    if m['lufs'] is None or m['true_peak_dbtp'] is None:
        return 0.0, 'Normalise: the mix is silent, left as it is'
    gain = lufs - m['lufs']
    held = m['true_peak_dbtp'] + gain > ceiling
    if held:
        gain = ceiling - m['true_peak_dbtp']
    return gain, (f"Normalised by {gain:+.2f} dB: {m['lufs'] + gain:.1f} LUFS, true peak {m['true_peak_dbtp'] + gain:.1f} "
                  f"dBTP" + (f" (the {ceiling:g} dBTP ceiling held it under {lufs:g} LUFS)" if held else "")
                  + "; the export differs from the module, the .it is untouched")


def _at_depth(pcm, gain, depth):
    """Float32 stereo bytes with `gain` dB applied, as int16 bytes for `depth` 16 (rounded, clipped), else float32."""
    import numpy as np
    x = np.frombuffer(pcm, '<f4') * np.float32(10 ** (gain / 20))
    if depth == 16:
        return np.clip(np.round(x * 32768), -32768, 32767).astype('<i2').tobytes()
    return x.astype('<f4').tobytes()


def prepare(state, options):
    """Compile before queueing so later edits, faders and WAV changes cannot alter this job."""
    with state.lock:
        state._need_compiled()
        if state.dirty():
            raise ValueError('Compare and RELOAD external edits before exporting')
        fmt = str(options.get('fmt', 'wav')).lower()
        if fmt not in FORMATS:
            raise ValueError('Choose IT, WAV, MP3, OGG, FLAC, MID, TG, GP3, GP4, GP5, TAB, LY or MUSICXML')
        if options.get('tg_version') not in (None, '') and fmt != 'tg':
            raise ValueError('tg_version is for TG export')
        if options.get('lilypond') not in (None, {}) and fmt != 'ly':
            raise ValueError('LilyPond settings are for LY export')
        if options.get('gp_encoding') is not None and fmt not in ('gp3','gp4','gp5'):
            raise ValueError('Guitar Pro encoding is for GP3/4/5 export')
        midi_settings = None
        if 'midi_export' in options:
            if fmt != 'mid' or not state.song.get('score'):
                raise ValueError('Native MIDI export settings require MID export of a native score')
            midi_settings = midi_export_settings(options['midi_export'])
        region_name = options.get('region') or ''
        loop = bool(options.get('loop'))
        if loop and fmt not in ('wav', 'ogg', 'flac'):
            raise ValueError('A game loop is exported as WAV (smpl chunk), OGG or FLAC (LOOPSTART and LOOPLENGTH tags)')
        render_opts = render_settings(options, fmt, loop or bool(region_name))
        region = None
        if region_name or loop:
            orders = state.mod.orders
            if region_name:
                if region_name not in (state.song.get('sections') or {}):
                    raise ValueError(f'No section named {region_name}')
                a, b = state.song['sections'][region_name]
            else:  # a loop without a section: the whole song, its orders up to the end marker
                a, b = 0, orders.index(ORDER_END) if ORDER_END in orders else len(orders)
            playable = [i for i in range(a, b) if state.mod.orders[i] < len(state.mod.patterns)]
            if not playable:
                raise ValueError('Section has no playable orders')
            region = (playable[0], 0, playable[-1], len(state.mod.patterns[state.mod.orders[playable[-1]]].rows)-1)
        mode, mutes = options.get('mix', 'saved'), options.get('mutes', 'ignore')
        if mode not in ('saved', 'current') or mutes not in ('ignore', 'respect'):
            raise ValueError('Choose saved/current mix and ignore/respect audition mutes')
        if fmt in NOTATION and (region or loop or options.get('stems') or options.get('include_it')
                            or render_opts['repeat'] or mode != 'saved' or mutes != 'ignore'):
            raise ValueError(f'{fmt.upper()} export requires the whole score, saved mix, ignored audition mutes, no stems or repeat')
        mix = state.mix() if mode == 'current' else {}
        silenced = state.silenced() if mutes == 'respect' else []
        base = api.from_yaml(state.patched_text(state.want)[0]) if mode == 'current' and state.want else state.song
        snap = snapshot(base, state.base_dir, region, mix, silenced, options.get('tail', 2), loop)
        native_it = None
        if snap.get('plan') is not None and (fmt == 'it' or options.get('include_it')):
            # The standalone IT of a native score: the score projected into editable tracker cells, as
            # `python -m vulturetracker build` writes it. Sub-tick passages may use explicitly reported native-rendered
            # samples; all remaining unsafe cases refuse before any file is written.
            if region or loop:
                raise ValueError('IT export of a native score covers the whole song: clear the section or loop first')
            from .measure import patch_it
            try:
                compiled, compiled_mod, warnings = api.compile_song(base, state.base_dir, render_timing=True)
                parents = compiled_mod.score_projection.channel_parents
                it_mix = copy.deepcopy(mix)
                for field in ('volume', 'pan'):
                    for channel, parent in parents.items():
                        if str(parent) in it_mix.get(field, {}):
                            it_mix[field][str(channel)] = it_mix[field][str(parent)]
                it_silenced = list(silenced) + [ch for ch, parent in parents.items() if parent in silenced]
                native_it = patch_it(compiled, it_silenced, it_mix)
                snap['warnings'].extend(w for w in warnings if w not in snap['warnings'])
            except SongError as e:
                raise ValueError('IT export: ' + '; '.join(getattr(e, 'errors', None) or [str(e)])) from None
        midi_data, notation, conversion = None, None, None
        if fmt in NOTATION:
            if snap.get('plan') is None:
                raise ValueError(f'{fmt.upper()} export requires an authored native score')
            from .tablature import measure_errors
            overfull = sorted({e['bar'] for e in measure_errors(base, {p.name: len(p.rows) for p in state.mod.patterns})
                               if 'long' in e['errors']})
            if overfull:   # free edit leaves them; notation files place each bar by its meter
                raise ValueError(f"{fmt.upper()} export needs every bar within its meter: bar{'s' * (len(overfull) > 1)} "
                                 f"{', '.join(map(str, overfull))} {'are' if len(overfull) > 1 else 'is'} overfull (free edit); "
                                 'repair them first')
            assignments = {key: dict(program=track['midi']['program'], bank=track['midi'].get('bank', 0))
                           for key, track in base['score']['tracks'].items() if 'midi' in track}
            if fmt in ('tg', 'tab'):
                from .tgimport import native_to_tg
                version = str(options.get('tg_version') or '2.0')
                notation, conversion = native_to_tg(base, state.mod.patterns, channels=assignments, version=version)
                if fmt == 'tab':   # ASCII tab: TuxGuitar's ASCII writer on the same TG 2.0 score
                    from .asciitab import tg_to_ascii
                    notation = tg_to_ascii(notation).encode('utf-8')
            elif fmt in ('gp3', 'gp4', 'gp5'):
                from .gpexport import native_to_gp
                notation, conversion = native_to_gp(base, state.mod.patterns, channels=assignments, version=int(fmt[2]),encoding=options.get('gp_encoding'))
            elif fmt == 'ly':
                from .notation_export import native_to_lilypond
                text, conversion = native_to_lilypond(base, state.mod.patterns, settings=options.get('lilypond') or None)
                notation = text.encode('utf-8')   # LF line endings, as the writer returns them
            else:
                from .notation_export import native_to_musicxml
                text, conversion = native_to_musicxml(base, state.mod.patterns, channels=assignments)
                notation = text.encode('utf-8')
            conversion.setdefault('duration_seconds', snap['seconds'])
            snap['warnings'] = [*snap['warnings'], *conversion.get('warnings', []), *loss_lines(fmt, conversion),
                                f'{fmt.upper()} notation export omits the audio tail.']
        if snap.get('plan') is not None and fmt == 'mid':
            if render_opts['repeat']:
                raise ValueError('Native MIDI: repeat export is not enabled')
            midi_data, conversion = native_to_midi(snap, midi_settings)
            snap['warnings'] = [*snap['warnings'], *conversion['losses']]
        folder = (state.base_dir / Path(options.get('destination') or '.').expanduser()).resolve()  # relative: beside the song
        name = str(options.get('name') or state.song_path.stem)
        if name in ('.', '..') or not name.strip() or re.search(r'[\\/:*?"<>|]', name) or device_name(name):
            raise ValueError('Output name must be a filename without directories or reserved characters, and not a '
                             'Windows device name (CON, PRN, AUX, NUL, COM1-9, LPT1-9)')
        chans = [i for i in range(snap['channels']) if any(u[i] for u in state.facts['use'])] if options.get('stems') else []
        stemfmt = 'wav' if fmt in ('it', 'mid') else fmt
        todo = [(folder / (name+'.'+fmt), None, fmt)] if options.get('song', True) else []
        if options.get('include_it') and fmt != 'it':
            todo.insert(0, (folder / (name+'.it'), None, 'it'))
        stemdir = folder / (name+'_stems')
        if options.get('stem_mode') not in (None, 'channels', 'tracks'):
            raise ValueError('Choose channel or score-part stems')
        if options.get('stems') and options.get('stem_mode') == 'tracks' and base.get('score'):
            owned = set()
            for index, (identity, track) in enumerate(base['score']['tracks'].items(), 1):
                group = tuple(track['channels'])
                owned.update(group)
                label = re.sub(r'[^\w-]+', '_', track.get('name') or identity).strip('_') or 'part'
                todo.append((stemdir / f'{index:02d}-{label}.{stemfmt}', group, stemfmt))
            # Raw Pattern channels outside the score remain audible and get their own stems.
            chans = [i for i in chans if i not in owned]
        for i in chans:
            label = re.sub(r'[^\w-]+', '_', state.facts['channels'][i]).strip('_') or 'ch'
            todo.append((stemdir / f'ch-{i+1:02d}-{label}.{stemfmt}' if options.get('stem_mode') == 'tracks' else stemdir / f'{i+1:02d}-{label}.{stemfmt}', i, stemfmt))
        if not todo:
            raise ValueError('Choose song or stems to export')
        protected = sources(state)
        protect_outputs([p for p, _, _ in todo], protected)
        existing = {str(p): digest(p.read_bytes()) if p.exists() else None for p, _, _ in todo}
        if not options.get('replace', False) and any(v is not None for v in existing.values()):
            raise ValueError('An output exists. Choose another destination/name or enable Replace previous exports')
        identity = snap['render_it']
        if snap.get('plan') is not None:
            identity += json.dumps({key: snap[key] for key in ('plan', 'seek', 'end', 'tail', 'range_at')}, sort_keys=True).encode()
        if midi_data is not None:
            identity += midi_data
        if notation is not None:
            identity += notation
        return {'snapshot': snap, 'todo': todo, 'sources': protected, 'existing': existing, 'render': render_opts,
                'midi_data': midi_data, 'native_it': native_it, **{f'{f}_data': notation if f == fmt else None for f in NOTATION},
                'cancel': threading.Event(), 'folder': folder, 'region': region_name, 'mix': mode,
                'result': {'job_id': uuid.uuid4().hex, 'status': 'queued', 'done': 0, 'total': len(todo), 'dir': str(stemdir) if options.get('stems') else None,
                           'song': str(todo[0][0]) if options.get('song', True) else None, 'fmt': fmt, 'error': None,
                           'files': [], 'seconds': (conversion['duration_seconds'] if conversion is not None and 'duration_seconds' in conversion else
                                                   snap['frames']/RATE + snap['seconds'] * render_opts['repeat']),
                           'snapshot': digest(identity)[:12], 'rate': render_opts['rate'],
                           'warnings': snap['warnings'], 'mismatches': [], 'bytes': len(snap['render_it']),
                           'conversion': conversion,
                           'loop': (0, round(snap['seconds'] * render_opts['rate'])) if snap['loop'] else None}}


def run(job, encode):
    """Render every file privately, then publish; failed/cancelled jobs retain earlier outputs."""
    result, cancel = job['result'], job['cancel'].is_set
    stage = None
    published, backups, rendered_hashes = [], {}, {}
    try:
        if cancel():
            raise ValueError('Export cancelled')
        result['status'] = 'rendering'
        job['folder'].mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.vt-export-', dir=job['folder']))
        staged, gain = [], None
        for i, (path, ch, fmt) in enumerate(job['todo']):
            if cancel():
                raise ValueError('Export cancelled')
            tmp = stage / f'{i}.{fmt}'
            if fmt == 'it':
                if job['snapshot'].get('plan') is not None:
                    if job.get('native_it') is None:
                        raise ValueError('Native score backing bytes are not a standalone IT export')
                    atomic_write(tmp, job['native_it'])
                else:
                    atomic_write(tmp, job['snapshot']['it'])
            elif fmt in NOTATION:
                data = job.get(fmt + '_data')
                if data is None:
                    raise ValueError(f'{fmt.upper()} export requires a prepared native conversion')
                atomic_write(tmp, data)
            elif fmt == 'mid':
                if job['snapshot'].get('plan') is not None:
                    data = job.get('midi_data')
                    if data is None:
                        raise ValueError('Native score MIDI export requires a prepared exact conversion')
                else:
                    data, notes = to_midi(job['snapshot']['it'])
                    result['warnings'] = [*result['warnings'], *notes]
                atomic_write(tmp, data)
            else:
                opts = job.get('render') or {'rate': RATE, 'depth': 16, 'repeat': 0}
                audible = ch if isinstance(ch, tuple) else (ch,)
                silenced = [] if ch is None else [c for c in range(job['snapshot']['channels']) if c not in audible]
                depth = opts['depth'] if fmt in ('wav', 'flac') else 16
                if opts.get('master'):  # one gain from the whole mix, for the song and every stem alike
                    if gain is None:
                        gain, report = master_gain(render(job['snapshot'], [], cancel, opts['rate'], 'float', opts['repeat']),
                                                   opts['rate'], opts['master']['lufs'], opts['master']['ceiling'])
                        result['warnings'] = [*result['warnings'], report]
                        result['master'] = round(gain, 2)
                    pcm = _at_depth(render(job['snapshot'], silenced, cancel, opts['rate'], 'float', opts['repeat']), gain, depth)
                else:
                    pcm = render(job['snapshot'], silenced, cancel, opts['rate'], depth, opts['repeat'])
                if fmt == 'wav':
                    atomic_write(tmp, wav_bytes(pcm, opts['rate'], result['loop'], depth))
                elif opts['rate'] == RATE and depth == 16 and not opts.get('bitrate') and opts.get('quality') is None:  # unchanged
                    encode(tmp, pcm, fmt, result['loop'])
                else:
                    encode(tmp, pcm, fmt, result['loop'], opts['rate'], depth, opts.get('bitrate'), opts.get('quality'))
            rendered_hashes[path] = digest(tmp.read_bytes())
            staged.append((path, tmp))
            result['done'] = i+1
        protect_outputs([p for p, _ in staged], job['sources'])
        for i, (path, tmp) in enumerate(staged):
            current = digest(path.read_bytes()) if path.exists() else None
            if current != job['existing'][str(path)]:
                raise ValueError(f'{path} changed while rendering; previous output kept')
            if current is not None:
                backup = stage / f'{i}.previous'
                shutil.copyfile(path, backup)
                backups[path] = backup
        if cancel():
            raise ValueError('Export cancelled')
        result['status'] = 'publishing'  # short commit phase; cancellation never interrupts it halfway
        for path, tmp in staged:
            protect_outputs([path], job['sources'])
            current = digest(path.read_bytes()) if path.exists() else None
            if current != job['existing'][str(path)]:
                raise ValueError(f'{path} changed before publication; previous output kept')
            path.parent.mkdir(parents=True, exist_ok=True)
            if job['existing'][str(path)] is None:
                link_new(tmp, path)  # exclusive creation; an intervening file is never replaced
            else:
                os.replace(tmp, path)
            published.append(path)
        result['files'] = [str(p) for p, _ in staged]
        result['status'] = 'done'
        for path, ch, fmt in job['todo']:
            if ch is None and fmt in ('it', 'wav'):
                result[fmt] = str(path)
    except Exception as error:
        failed_rollback = False
        for path in reversed(published):
            try:
                if not path.exists() or digest(path.read_bytes()) != rendered_hashes[path]:
                    raise OSError('A published output changed externally; recovery copies retained')
                if path in backups:
                    atomic_write(path, backups[path].read_bytes())
                else:
                    path.unlink()
            except OSError:
                failed_rollback = True
        result.update(status='cancelled' if cancel() else 'failed', error=str(error))
        if failed_rollback:
            result['error'] += f'; rollback incomplete: previous files retained in {stage}'
            stage = None  # preserve the recovery copies
    finally:
        if stage is not None:
            shutil.rmtree(stage)
    return result
