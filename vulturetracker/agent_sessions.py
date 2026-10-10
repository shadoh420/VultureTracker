"""Agent access to recording, listening notes and history; playback uses the page transport."""
import copy
import difflib
import hashlib
import json
import math
from urllib.parse import quote

from .agent import tool, _integer, _boolean, _transport, _voice_guard, _guard_restore
from .history import unpack_step


def _id(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:20]


@tool('recording_status', 'Inspect recording inputs/outputs, current input meters/tuner, unsaved recording and this '
      'session\'s saved takes. Enumeration does not open an input. Take files remain on disk across restarts, but the '
      'take list is session-only; older files can be imported with create_sample.',
      {'refresh_devices': {'type': 'boolean'}})
def recording_status(st, a):
    from .gui import Handler
    if Handler.state is not st:
        raise ValueError('inspect the currently open project first')
    return copy.deepcopy(Handler.rec_snapshot(_boolean(a, 'refresh_devices')))


def _number(a, key, default, low, high):
    value = a.get(key, default)
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{key} must be a number {low}..{high}')
    return value


@tool('control_recording', 'Control RECORD: open an input, change mode, start, stop/save, discard, or close. Only '
      'open/start when the owner asks to use their input; open activates meters and input capture. Choose device IDs '
      'from recording_status. Start supports pre-roll or backing/section/count-in/loop passes/latency compensation. '
      'Stop saves NEW WAVs, default keep (no sound selection); manage_take offers or creates slots separately. A failed '
      'save stays in memory for another stop or explicit discard. Close/reopen cannot discard an unsaved take. '
      'Request stop_playback first and wait for its UI acknowledgement before recording against silence.',
      {'action': {'enum': ['open', 'mode', 'start', 'stop', 'discard', 'close']},
       'device': {'type': 'integer'}, 'mode': {'enum': ['1', '2', 'mono', 'stereo']},
       'rate': {'type': 'integer'}, 'exclusive': {'type': 'boolean'}, 'preroll': {'type': 'number'},
       'backing': {'type': 'boolean'}, 'output': {'type': 'integer'}, 'section': {'type': 'string'},
       'countin': {'type': 'integer'}, 'loops': {'type': 'integer'}, 'latency_ms': {'type': 'number'},
       'name': {'type': 'string'}, 'trim': {'type': 'boolean'}, 'trim_db': {'type': 'number'},
       'root': {'type': 'boolean'}}, ['action'])
def control_recording(st, a):
    from .gui import Handler
    if Handler.state is not st:
        raise ValueError('the project changed; inspect recording_status first')
    act = a['action']
    if act not in ('open', 'mode', 'start', 'stop', 'discard', 'close'):
        raise ValueError('unknown recording action')
    b = {'cmd': act}
    if act in ('open', 'mode'):
        mode = a.get('mode', '1')
        if mode not in ('1', '2', 'mono', 'stereo'):
            raise ValueError('invalid input mode')
        b['mode'] = mode
    if act == 'open':
        b.update(device=_integer(a['device'], 0, 65535, 'device'),
                 rate=_integer(a.get('rate', 44100), 8000, 192000, 'rate'), exclusive=_boolean(a, 'exclusive'))
    if act in ('start', 'stop'):
        st._writable()
        if st.dirty():
            raise ValueError('reload external changes before recording')
    if act == 'start':
        b.update(preroll=_number(a, 'preroll', 0, 0, .5), backing=_boolean(a, 'backing'))
        if b['backing']:
            b.update(output=_integer(a['output'], 0, 65535, 'output'),
                     countin=_integer(a.get('countin', 4), 0, 16, 'countin'),
                     loops=_integer(a.get('loops', 1), 1, 16, 'loops'),
                     latency_ms=_number(a, 'latency_ms', 0, 0, 2000))
            if a.get('section'):
                if a['section'] not in (st.song.get('sections') or {}):
                    raise ValueError('no such named section')
                b['section'] = a['section']
    if act == 'stop':
        name = a.get('name', 'take')
        if not isinstance(name, str) or not name.strip() or len(name) > 40:
            raise ValueError('name must contain 1-40 characters')
        b.update(name=name, trim=_boolean(a, 'trim', True), root=_boolean(a, 'root', True),
                 trim_db=_number(a, 'trim_db', -50, -120, 0), dest='keep')
    result = Handler.rec_command(b)
    return {**result, 'summary': result.get('error') or f'recording {act} completed'}


@tool('manage_take', 'Inspect/preview one saved session take, offer it as a candidate of the current slot, create '
      'a NEW tuned sample/instrument slot, or combine selected pitched takes into a multisample instrument. '
      'inspect returns a WAV URL; does not play or choose a sound. Originals remain. New slots/multisample are one '
      'song undo step; candidate offers and saved WAVs are outside song undo.',
      {'action': {'enum': ['inspect', 'candidate', 'slot', 'multisample']}, 'file': {'type': 'string'},
       'files': {'type': 'array', 'items': {'type': 'string'}}}, ['action'])
def manage_take(st, a):
    with st.lock:
        act = a['action']
        takes = {t['file']: t for t in st.takes}
        if act == 'multisample':
            names = a.get('files')
            if not isinstance(names, list) or not names or len(set(names)) != len(names) or any(n not in takes for n in names):
                raise ValueError('files must name distinct takes from recording_status')
            if any(not takes[n].get('hz') or not takes[n].get('note') for n in names):
                raise ValueError('each selected take must have a detected pitch')
            st._writable()
            return {'summary': st.takes_multisample(names)}
        if act not in ('inspect', 'candidate', 'slot') or a.get('file') not in takes:
            raise ValueError('choose inspect/candidate/slot and an existing session take file')
        take = takes[a['file']]
        if act != 'inspect':
            st._writable()
            if act == 'candidate':
                _voice_guard(st, 'samples', st.slot)
            take = st.send_take(a['file'], act)
        return {'take': copy.deepcopy(take), 'url': '/take/' + quote(take['file']),
                'summary': 'take inspected' if act == 'inspect' else f'take sent to {act}'}


@tool('update_listening_note', 'Add, update or delete a listening note using NOTES. Use the owner\'s actual words; '
      'never invent listening impressions. Add requires explicit playable order/row (0-based). Channels are 1-based. '
      'Updates preserve original position/sounding/audition context. Update/delete requires revision from read_notes '
      'to avoid overwriting a newer note. Notes are sidecars outside song undo; song notes/audio are unchanged.',
      {'action': {'enum': ['add', 'update', 'delete']}, 'note_id': {'type': 'integer'}, 'revision': {'type': 'string'},
       'order': {'type': 'integer'}, 'row': {'type': 'integer'}, 'text': {'type': 'string'}, 'tag': {'type': 'string'},
       'channels': {'type': 'array', 'items': {'type': 'integer'}}}, ['action'])
def update_listening_note(st, a):
    with st.lock:
        st._writable()
        if st.dirty():
            raise ValueError('reload external changes before annotating')
        act = a['action']
        b = {}
        for k, limit in [('text', 2000), ('tag', 40)]:
            if k in a:
                if not isinstance(a[k], str) or len(a[k]) > limit:
                    raise ValueError(f'{k} must be text up to {limit} characters')
                b[k] = a[k]
        if 'channels' in a:
            if not isinstance(a['channels'], list):
                raise ValueError('channels must be a list')
            st._need_compiled()
            b['channels'] = [_integer(c, 1, len(st.mod.channels), 'channel')-1 for c in a['channels']]
        if act == 'add':
            st._need_compiled()
            if not b.get('text', '').strip():
                raise ValueError('give the listening note text')
            order = _integer(a['order'], 0, len(st.facts['orders'])-1, 'order')
            row = _integer(a['row'], 0, st.facts['orders'][order]['rows']-1, 'row')
            note = st.add_note(dict(b, order=order, row=row, source='agent annotation'))
        elif act in ('update', 'delete'):
            nid = _integer(a.get('note_id'), 1, 2147483647, 'note_id')
            note = next((n for n in st.notes if n['id'] == nid), None)
            if not note or a.get('revision') != _id(note):
                raise ValueError('note changed or missing; read_notes again for its revision')
            if act == 'update' and not b:
                raise ValueError('give text, tag or channels to update')
            st.edit_note(note['id'], {'delete': True} if act == 'delete' else b)
        else:
            raise ValueError('choose add, update or delete')
        return {'note': None if act == 'delete' else dict(copy.deepcopy(note), revision=_id(note)),
                'summary': f'listening note {act} completed'}


@tool('pause_playback', 'Pause live or rendered/candidate playback without changing its position or loop. Queued '
      'window request; get_state.ui.applied_request acknowledges delivery, not audible verification.', {})
def pause_playback(st, a):
    with st.lock:
        return _transport(st, 'pause')


@tool('resume_playback', 'Resume playback previously paused through pause_playback. Live playback retains engine '
      'position; rendered playback retains time. Stop, project switch or changed rendered audio clears/refuses resume. '
      'Queued window request; inspect get_state UI acknowledgement/errors.', {})
def resume_playback(st, a):
    with st.lock:
        return _transport(st, 'resume')


@tool('inspect_history', 'Read undo or redo snapshots, nearest step first (index 0). Paginated summaries include '
      'entry IDs and saved versions; history has no reliable operation labels or timestamps. For detail, supply '
      'index and matching entry_id: returns a bounded CURRENT-to-snapshot YAML diff, changed saved settings and '
      'asset/approval restore checks. Does not restore or trim history. Metadata omitted by an old snapshot stays '
      'unchanged on restore. Use undo/redo/checkpoint tools separately.',
      {'stack': {'enum': ['undo', 'redo']}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'},
       'index': {'type': 'integer'}, 'entry_id': {'type': 'string'}, 'max_lines': {'type': 'integer'}})
def inspect_history(st, a):
    with st.lock:
        kind = a.get('stack', 'undo')
        if kind not in ('undo', 'redo'):
            raise ValueError('stack must be undo or redo')
        steps = list(reversed(st.history if kind == 'undo' else st.future))
        offset = _integer(a.get('offset', 0), 0, len(steps), 'offset')
        limit = _integer(a.get('limit', 20), 1, 50, 'limit')
        entries = []
        for i in range(offset, min(len(steps), offset+limit)):
            s = unpack_step(steps[i])
            entries.append({'index': i, 'entry_id': _id(steps[i]), 'version': s.get('version'),
                            'text_bytes': len(s['text'].encode()), 'asset_count': len(s.get('assets', {})),
                            'saved_settings': sorted((s.get('meta') or {}).keys())})
        out = {'stack': kind, 'total': len(steps), 'entries': entries,
               'next_offset': offset+limit if offset+limit < len(steps) else None}
        if 'index' in a:
            i = _integer(a['index'], 0, len(steps)-1, 'index')
            if a.get('entry_id') != _id(steps[i]):
                raise ValueError('history changed; inspect_history again for the entry_id')
            s = unpack_step(steps[i])
            lines = st._diff(s['text'], False)['lines']
            count = _integer(a.get('max_lines', 200), 1, 400, 'max_lines')
            changes = {k: {'current': st.meta.get(k), 'snapshot': v} for k, v in (s.get('meta') or {}).items()
                       if st.meta.get(k) != v}
            reason = None
            try:
                st._writable()
                if st.dirty():
                    raise ValueError('external song changes need reload')
                st._check_assets(s)
                _guard_restore(st, s)
            except (ValueError, OSError) as e:
                reason = str(e)
            out['detail'] = {'index': i, 'entry_id': a['entry_id'], 'lines': lines[:count],
                             'total_lines': len(lines), 'truncated': len(lines) > count,
                             'changed_settings': sorted(changes), 'restorable': reason is None,
                             'restore_error': reason}
            settings = list(difflib.unified_diff(
                json.dumps({k: v['current'] for k, v in changes.items()}, indent=2, sort_keys=True).splitlines(),
                json.dumps({k: v['snapshot'] for k, v in changes.items()}, indent=2, sort_keys=True).splitlines(),
                'current settings', 'snapshot settings', lineterm='')) if changes else []
            out['detail'].update(settings_lines=settings[:count], settings_total_lines=len(settings),
                                 settings_truncated=len(settings) > count)
        return out
