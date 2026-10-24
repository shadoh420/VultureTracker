"""User-written phrase alternatives against one frozen accompaniment and sound/mixer snapshot."""
import copy
import itertools
import json
from pathlib import Path
import uuid

from . import api
from .export import snapshot, render
from .fileio import atomic_write, wav_bytes
from .history import digest, json_bytes
from .notation import format_cell, parse_cell
from .project import file_updates, replace_values, relative_meta
from .song import load_song_text


def _store(state, phrase):
    state._writable()
    meta = dict(state.meta, phrase=phrase)
    atomic_write(state.meta_path, json_bytes(relative_meta(meta, state.base_dir)))
    state.meta = meta


def _control(cell):
    fx = format_cell(parse_cell(cell)).split()[-1]
    return fx if fx[0] in 'ABCTVWXY' or fx[:2] in ('S6', 'SB', 'SE') else '...'


def _clone_occurrence(state, text, order, name):
    """Clone the residual pattern and its score, keeping this occurrence's identity."""
    from .tablature import apply_structure_edit
    doc = api.from_yaml(text)
    orders = list(doc['orders'])
    operation = {'op': 'pattern_clone', 'src': orders[order], 'name': name}
    mapped = apply_structure_edit(doc, operation)
    lines = text.splitlines(keepends=True)
    state._song_op(lines, orders, operation, [])
    text = ''.join(lines)
    if 'score' in doc:
        text = replace_values(text, [(('score',), mapped['score'])])
    orders[order] = name
    mapped = apply_structure_edit(api.from_yaml(text),
                                  {'op': 'orders', 'orders': orders, 'origins': list(range(len(orders)))})
    lines = text.splitlines(keepends=True)
    state._write_orders(lines, orders)
    text = ''.join(lines)
    if 'score' in doc:
        text = replace_values(text, [(('score',), mapped['score'])])
    load_song_text(text, state.base_dir, native_score_rate=44100)  # validate before capture writes assets
    return text


def capture(state, body):
    state._writable()
    state._need_compiled()
    if state.dirty():
        raise ValueError('Compare and RELOAD external changes before capturing a phrase')
    order = int(body['order'])
    if not 0 <= order < len(state.mod.orders) or state.mod.orders[order] >= len(state.mod.patterns):
        raise ValueError('Choose a playable order')
    pat = state.mod.patterns[state.mod.orders[order]]
    a, b = int(body['r0']), int(body['r1'])
    chans = sorted(set(map(int, body['chans'])))
    count = int(body.get('count', 3))
    if not 2 <= count <= 4 or not 0 <= a <= b < len(pat.rows) or not chans or not all(0 <= c < len(state.mod.channels) for c in chans):
        raise ValueError('Choose 2-4 alternatives, valid rows, and at least one channel')
    ident = uuid.uuid4().hex
    folder = state.base_dir / (state.song_path.stem + '.phrases') / 'assets'
    text = state.patched_text(state.want)[0] if state.want else state.text
    doc = api.from_yaml(text)
    name = next(n for n in (pat.name + '_tryout' + str(i) for i in itertools.count(1)) if n not in doc['patterns'])
    text = _clone_occurrence(state, text, order, name)
    folder.mkdir(parents=True, exist_ok=True)
    frozen, assets = {}, {}
    for num, entry in doc['samples'].items():
        if not isinstance(entry, dict) or not entry.get('file'):
            continue
        src = (state.base_dir / entry['file']).resolve()
        raw = src.read_bytes()
        sha = digest(raw)
        dst = folder / f'{sha}.wav'
        if dst.exists():
            if digest(dst.read_bytes()) != sha:
                raise ValueError(f'Frozen phrase sample changed: {dst}; restore it before capturing')
        else:
            atomic_write(dst, raw, replace=False)
        rel = dst.relative_to(state.base_dir).as_posix()
        assets[rel] = sha
        frozen[num] = rel
    text = replace_values(text, file_updates(doc, frozen))
    preview = None
    if state.mod.native_score is not None:
        from .tablature import pattern_authoring_view
        preview = pattern_authoring_view(state.song, state.mod.patterns, state.mod.orders[order],
                                         state.song['score']['order_ids'][order], view=state.mod.native_score['view'])
    grid = [[preview['display_rows'][r][c] if preview else format_cell(pat.rows[r][c])
             for c in chans] for r in range(a, b+1)]
    data = '\n'.join(' | '.join(row) for row in grid)
    phrase = {'id': ident, 'base_hash': state.text_sha(), 'version': state.version(), 'order': order,
              'pattern': pat.name, 'snapshot_pattern': name, 'r0': a, 'r1': b, 'chans': chans, 'original': grid,
              'snapshot': text, 'assets': assets,
              'source_assets': state._assets(state.text, {'selected_candidate': state.want}),
              'mix': copy.deepcopy(state.mix()), 'muted': state.silenced(), 'want': state.want,
              'absent': {'name': 'Line absent', 'stars': 0, 'note': ''},
              'variants': [{'name': chr(65+i), 'data': data, 'stars': 0, 'note': ''} for i in range(count)]}
    if preview is not None:
        from fractions import Fraction
        phrase['score_positions'] = [copy.deepcopy(p) for p in preview['positions']
                                     if p['kind'] == 'note' and p['ch'] in chans
                                     and a <= Fraction(*p['row']) < b + 1]
    previous = state.meta.get('phrase')
    if previous:
        atomic_write(folder.parent / (previous['id'] + '.json'), json_bytes(previous))
    _store(state, phrase)
    return phrase


def cells(phrase, variant):
    if variant == -1:
        rows = [[f'{"^^^" if r == 0 else "..."} .. ... {_control(cell)}' for cell in row]
                for r, row in enumerate(phrase['original'])]
    else:
        rows = [row.split('|') for row in phrase['variants'][variant]['data'].splitlines()]
    if len(rows) != len(phrase['original']) or any(len(row) != len(phrase['chans']) for row in rows):
        raise ValueError('Keep the captured row and channel counts; separate channels with |')
    out = []
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            normalized = format_cell(parse_cell(value.strip()))
            if _control(normalized) != _control(phrase['original'][r][c]):
                raise ValueError('Keep song-wide timing, jump and volume effects unchanged so accompaniment stays identical')
            out.append({'row': phrase['r0']+r, 'ch': phrase['chans'][c], 'cell': normalized})
    return out


def edited_text(state, phrase, variant, accepting=False):
    if accepting:
        if state.dirty() or state.text_sha() != phrase['base_hash'] or state.mix() != phrase['mix'] or state.silenced() != phrase['muted'] or state.want != phrase.get('want'):
            raise ValueError('The song or audition settings changed since capture; start a new comparison before accepting')
        state._check_assets({'assets': phrase['source_assets']})
        text = state.text
        names = state.song['patterns']
        name = phrase['pattern']
        orders = list(state.song['orders'])
        if orders.count(name) > 1:
            unique = next(n for n in (name+'_phrase'+str(i) for i in itertools.count(1)) if n not in names)
            text = _clone_occurrence(state, text, phrase['order'], unique)
            name = unique
    else:
        text = phrase['snapshot']
        name = phrase['snapshot_pattern']
        for path, sha in phrase['assets'].items():
            p = state.base_dir / path
            if not p.is_file() or digest(p.read_bytes()) != sha:
                raise ValueError(f'Frozen phrase sample changed or missing: {path}; capture a new comparison')
        doc = api.from_yaml(text)
        if (phrase['pattern'] in doc.get('score', {}).get('patterns', {})
                and name not in doc['score']['patterns']):
            raise ValueError('This phrase predates score-aware capture; capture a new comparison')
    mod, _ = load_song_text(text, state.base_dir, native_score_rate=44100)
    doc = api.from_yaml(text)
    index = next(i for i, p in enumerate(mod.patterns) if p.name == name)
    groups = [(index, cells(phrase, variant))]
    score = None
    if mod.native_score is not None:
        from .tablature import translate_native_pattern_edits, transform_native_selections
        if variant == -1:
            if accepting:
                raise ValueError('Accepting Line absent for a score requires an explicit score rest/duration edit')
            score, _ = transform_native_selections(doc, mod.patterns, {'action': 'clear', 'selections': [{
                'pattern': index, 'r0': phrase['r0'], 'r1': phrase['r1'],
                'cols': [[ch, ['note', 'instrument', 'volume']] for ch in phrase['chans']]}]})
            # Clear the selected authored attacks in the audition, then write the existing raw cut/control cells.
            doc['score'] = score
        else:
            score, groups = translate_native_pattern_edits(doc, mod.patterns, groups,
                occurrences={index: doc['score']['order_ids'][phrase['order']]}, view=mod.native_score['view'])
    elif mod.score_projection is not None:
        if variant == -1:
            if accepting:
                raise ValueError('Accepting Line absent for a score requires an explicit score rest/duration edit')
            # Auditions are disposable playback documents; authored acceptance never flattens the score.
            text = api.to_yaml(api.playback_document(doc, mod))
        else:
            from .tablature import translate_pattern_edits
            score, groups = translate_pattern_edits(doc, mod.score_projection, groups)
    lines = text.splitlines(keepends=True)
    for pi, changes in groups:
        pat = (mod.score_projection.raw_patterns if mod.score_projection is not None and score is not None else mod.patterns)[pi]
        state._edit_block(lines, pi, changes, nch=len(mod.channels), pat=pat)
    text = ''.join(lines)
    if score is not None:
        text = replace_values(text, [(('score',), score)])
    load_song_text(text, state.base_dir, native_score_rate=44100)
    return text


def variant_wav(state, phrase, text):
    """The captured rows of `text` (edited_text of one alternative) as a WAV, with the mix and mutes of the capture."""
    snap = snapshot(api.from_yaml(text), state.base_dir, (phrase['order'], phrase['r0'], phrase['order'], phrase['r1']),
                    phrase['mix'], phrase['muted'], tail=0)
    return wav_bytes(render(snap))


def action(state, body):
    with state.lock:
        kind = body.get('action')
        if kind == 'capture':
            capture(state, body)
            return {}
        phrase = copy.deepcopy(state.meta.get('phrase'))
        if not phrase:
            raise ValueError('Capture a phrase from selected rows/channels first')
        index = int(body.get('variant', 0))
        if not -1 <= index < len(phrase['variants']):
            raise ValueError('No such phrase alternative')
        if kind == 'update':
            if index == -1 and ('data' in body or 'name' in body):
                raise ValueError('The absent-line cells cannot be edited')
            variant = phrase['absent'] if index == -1 else phrase['variants'][index]
            for key in ('name', 'data', 'note'):
                if key in body:
                    variant[key] = str(body[key])
            if not variant['name'].strip() or len(variant['name']) > 80 or len(variant['note']) > 8000:
                raise ValueError('Use a name up to 80 characters and a note up to 8000 characters')
            if 'stars' in body:
                variant['stars'] = int(body['stars'])
                if not 0 <= variant['stars'] <= 5:
                    raise ValueError('Rate an alternative 0 to 5 stars')
            new = edited_text(state, phrase, index)
            load_song_text(new, state.base_dir, native_score_rate=44100)  # validate before saving the draft
            _store(state, phrase)
            return {}
        if kind in ('diff', 'accept'):
            text = edited_text(state, phrase, index, accepting=True)
            token = digest(text.encode())
            if kind == 'diff':
                return dict(state._diff(text, False), token=token)
            if body.get('token') and body['token'] != token:
                raise ValueError('Phrase changed after comparison; compare its diff again')
            phrase['accepted'] = index
            state._commit(text, meta=dict(state.meta, phrase=phrase))
            return {}
        if kind == 'render':
            text = edited_text(state, phrase, index)
            key = digest(json_bytes([api.RENDER_VERSION, text, phrase['mix'], phrase['muted'], phrase['order'], phrase['r0'],
                                     phrase['r1']]))[:24]
            out = state.cache_dir / f'{key}.wav'
            if not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(out, variant_wav(state, phrase, text))
            state.renders[key] = {'status': 'ready', 'file': str(out), 'error': None}
            return {'key': key, 'path': str(out)}
        raise ValueError('Unknown phrase action')
