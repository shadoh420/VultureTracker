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
    meta = dict(state.meta, phrase=phrase)
    atomic_write(state.meta_path, json_bytes(relative_meta(meta, state.base_dir)))
    state.meta = meta


def _control(cell):
    fx = format_cell(parse_cell(cell)).split()[-1]
    return fx if fx[0] in 'ABCTVWXY' or fx[:2] in ('S6', 'SB', 'SE') else '...'


def capture(state, body):
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
    folder.mkdir(parents=True, exist_ok=True)
    text = state.patched_text(state.want)[0] if state.want else state.text
    doc = api.from_yaml(text)
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
    # Only this order occurrence changes, even when earlier orders use the same pattern.
    lines = text.splitlines(keepends=True)
    name = next(n for n in (pat.name + '_tryout' + str(i) for i in itertools.count(1)) if n not in doc['patterns'])
    orders = list(doc['orders'])
    state._song_op(lines, orders, {'op': 'pattern_clone', 'src': pat.name, 'name': name}, [])
    orders[order] = name
    state._write_orders(lines, orders)
    grid = [[format_cell(pat.rows[r][c]) for c in chans] for r in range(a, b+1)]
    data = '\n'.join(' | '.join(row) for row in grid)
    phrase = {'id': ident, 'base_hash': state.text_sha(), 'version': state.version(), 'order': order,
              'pattern': pat.name, 'snapshot_pattern': name, 'r0': a, 'r1': b, 'chans': chans, 'original': grid,
              'snapshot': ''.join(lines), 'assets': assets,
              'source_assets': state._assets(state.text, {'selected_candidate': state.want}),
              'mix': copy.deepcopy(state.mix()), 'muted': state.silenced(), 'want': state.want,
              'absent': {'name': 'Line absent', 'stars': 0, 'note': ''},
              'variants': [{'name': chr(65+i), 'data': data, 'stars': 0, 'note': ''} for i in range(count)]}
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
        lines = state.text.splitlines(keepends=True)
        names = state.song['patterns']
        name = phrase['pattern']
        orders = list(state.song['orders'])
        if orders.count(name) > 1:
            unique = next(n for n in (name+'_phrase'+str(i) for i in itertools.count(1)) if n not in names)
            state._song_op(lines, orders, {'op': 'pattern_clone', 'src': name, 'name': unique}, [])
            orders[phrase['order']] = unique
            state._write_orders(lines, orders)
            name = unique
        mod, _ = load_song_text(''.join(lines), state.base_dir)
    else:
        lines = phrase['snapshot'].splitlines(keepends=True)
        name = phrase['snapshot_pattern']
        for path, sha in phrase['assets'].items():
            p = state.base_dir / path
            if not p.is_file() or digest(p.read_bytes()) != sha:
                raise ValueError(f'Frozen phrase sample changed or missing: {path}; capture a new comparison')
        mod, _ = load_song_text(phrase['snapshot'], state.base_dir)
    pat = next(p for p in mod.patterns if p.name == name)
    state._edit_block(lines, 0, cells(phrase, variant), nch=len(mod.channels), pat=pat)
    return ''.join(lines)


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
                variant['stars'] = max(0, min(5, int(body['stars'])))
            new = edited_text(state, phrase, index)
            load_song_text(new, state.base_dir)  # including sample/instrument references, before saving the draft
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
                snap = snapshot(api.from_yaml(text), state.base_dir,
                                (phrase['order'], phrase['r0'], phrase['order'], phrase['r1']),
                                phrase['mix'], phrase['muted'], tail=0)
                atomic_write(out, wav_bytes(render(snap)))
            state.renders[key] = {'status': 'ready', 'file': str(out), 'error': None}
            return {'key': key, 'path': str(out)}
        raise ValueError('Unknown phrase action')
