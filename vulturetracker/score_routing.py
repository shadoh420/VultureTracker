"""Explicit, bounded voice separation using a part's existing tracker channels."""
import copy
import json


def route_voices(song, raw_patterns, edit):
    from .tablature import _score_timeline, playback_plan

    track = edit.get('track')
    if track not in song.get('score', {}).get('tracks', {}):
        raise ValueError('Choose an existing part to separate its voices')
    score = song['score']
    timeline = _score_timeline(song, raw_patterns)
    records = [r for r in timeline['records'] if r['track'] == track]
    if not records:
        return song, dict(report='This part has no notes to separate.', moved=0)
    # Every occurrence of one authored note, and every tied continuation, must
    # use one channel. Reused patterns therefore participate in the same graph.
    keys = {(r['pattern'], r['note']) for r in records}
    parents = {key: key for key in keys}

    def root(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for left, right in timeline['outgoing'].items():
        a, b = timeline['by_id'][left], timeline['by_id'][right]
        if a['track'] == track:
            parents[root((b['pattern'], b['note']))] = root((a['pattern'], a['note']))
    owners = {key: root(key) for key in keys}
    preferred = {owners[r['pattern'], r['note']]: r['ch'] for r in records}
    edges = {key: set() for key in preferred}
    instruments = song.get('instruments', {})
    continued = {owners[r['pattern'], r['note']] for r in records
                 if instruments.get(r['source_instrument'], instruments.get(str(r['source_instrument']), {})).get('nna') == 'continue'}

    def conflicts(spans, releases=False):
        active = []
        for start, end, key in sorted(spans):
            # A Continue instrument needs an explicit IT key-off even when its
            # next attack starts at that same tick. Give the attack another lane.
            active = [(stop, other) for stop, other in active
                      if stop > start or releases and stop == start and other in continued]
            for stop, other in active:
                if other == key:
                    raise ValueError('A reused note overlaps itself; make its occurrences independent first')
                edges[key].add(other)
                edges[other].add(key)
            active.append((end, key))

    # Written spans cover strict IT ownership. Performed spans additionally cover
    # grace, swing and ringing notes, including repeated visits.
    conflicts((r['start'], r['end'], owners[r['pattern'], r['note']]) for r in records)
    before = playback_plan(song, raw_patterns)
    active, spans = {}, []
    for event in before['events']:
        if event.get('track') != track:
            continue
        if event['type'] == 'note_on':
            key = event.get('source_pattern', event['pattern']), event['note']
            active[event['id']] = event['frame'], owners[key]
        elif event['type'] == 'note_off' and event['id'] in active:
            start, key = active.pop(event['id'])
            spans.append((start, event['frame'], key))
    conflicts(spans, releases=True)
    if not any(preferred[a] == preferred[b] for a in edges for b in edges[a]):
        return song, dict(report='The part already uses separate channels for overlapping notes.', moved=0)
    channels = score['tracks'][track]['channels']
    raw = {ch for ch in channels if any(not row[ch].is_empty() for p in raw_patterns for row in p.rows)}
    specs = song['module']['channels']
    if isinstance(specs, int):
        specs = [{} for _ in range(specs)]
    # Removing an isolated native voice context can change release tails and
    # duplicate-note handling even when every note event remains identical.
    # Continue/off NNA leaves already-released tails alone. Cut/fade NNA and
    # duplicate checks can instead change them at the next attack on the lane.
    instrument_ids = {n.get('instrument', score['tracks'][track]['instrument'])
                      for p in score['patterns'].values() for b in p['beats']
                      if b['track'] == track for n in b['notes']}
    for ident in instrument_ids:
        ins = song.get('instruments', {}).get(ident, song.get('instruments', {}).get(str(ident), {}))
        envelopes = ('volume_envelope', 'panning_envelope', 'pitch_envelope')
        stateful = any(ins.get(k) for k in ('fadeout', *envelopes))
        reason = None
        if not ident:
            reason = 'an inherited instrument'
        elif ins.get('dct', 'off') != 'off':
            reason = 'duplicate checking'
        elif ins.get('nna', 'cut') not in ('cut', 'continue', 'off') or (stateful and ins.get('nna', 'cut') == 'cut'):
            reason = 'cut/fade NNA with release tails'
        elif any(isinstance(ins.get(k), dict) and ins[k].get('carry') for k in envelopes):
            reason = 'carried envelopes'
        elif ins.get('random_volume') or ins.get('random_pan'):
            reason = 'random instrument variation'
        elif (any(ins.get(k) is not None for k in ('filter_cutoff', 'filter_resonance')) or
              isinstance(ins.get('pitch_envelope'), dict) and ins['pitch_envelope'].get('filter')):
            reason = 'filter state'
        if reason:
            record = next((r for r in records if r['source_instrument'] == ident), None)
            label = score['tracks'][track].get('name', track)
            location = f"bar {record['occurrence']}" if record else 'unplayed pattern'
            raise ValueError(f"Part {label}, {location}, instrument {ident} "
                f"({ins.get('name', ident)}): voice separation cannot preserve instrument release or voice state "
                f"with {reason}; use a separate instrument with Continue/Off NNA, duplicate checking off and "
                "non-carried envelopes, or a stateless Cut instrument")
    if any(isinstance(specs[ch], dict) and specs[ch].get('plugin') for ch in channels):
        raise ValueError('Voice separation cannot preserve plugin channel state')

    def sound(ch):
        spec = specs[ch] if isinstance(specs[ch], dict) else {}
        return tuple(spec.get(k, default) for k, default in
                     (('pan', 32), ('volume', 64), ('muted', False), ('plugin', 0)))

    assigned = {}
    # Stable largest-degree-first coloring keeps existing channels where possible.
    # No channel, sample, mixer or raw tracker command is created or rewritten.
    for key in sorted(edges, key=lambda k: (-len(edges[k]), k)):
        old = preferred[key]
        used = {assigned[n] for n in edges[key] if n in assigned}
        choices = [old] + [ch for ch in channels if ch != old and ch not in raw
                           and old not in raw and sound(ch) == sound(old)]
        channel = next((ch for ch in choices if ch not in used), None)
        if channel is None:
            record = next(r for r in records if owners[r['pattern'], r['note']] == key)
            label = score['tracks'][track].get('name', track)
            raise ValueError(f"Part {label}, bar {record['occurrence']}, note {record['note']}: "
                'no compatible spare channel; clear raw channel conflicts or simplify the overlapping voices. '
                'Continue NNA also needs a separate lane for an attack at a previous note release')
        assigned[key] = channel
    candidate, moved = copy.deepcopy(song), 0
    for name, pattern in candidate['score']['patterns'].items():
        for beat in pattern['beats']:
            if beat['track'] == track:
                for note in beat['notes']:
                    key = str(name), note['id']
                    if key in owners and assigned[owners[key]] != preferred[owners[key]]:
                        note['channel'] = assigned[owners[key]]
                        moved += 1
    # Changing routing must not change musical events. Strict IT compilation by
    # the State transaction additionally checks tick, effect and release limits.
    after = playback_plan(candidate, raw_patterns)
    routing = {'ch', 'context', 'context_open', 'context_close'}
    musical = lambda plan: sorted(json.dumps({k: v for k, v in e.items() if k not in routing}, sort_keys=True)
                                  for e in plan['events'])
    if musical(before) != musical(after):
        raise ValueError('Channel separation would change performed music; the edit was not applied')
    return candidate, dict(report=f'Separated overlapping voices: routed {moved} notes to compatible spare channels.', moved=moved)
