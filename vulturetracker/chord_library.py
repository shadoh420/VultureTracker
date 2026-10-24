"""Per-user fret shapes, independent of song notes and undo history."""
import copy
import json
from pathlib import Path

from .fileio import atomic_write, lock_file, unlock_file, user_dir
from .tablature import _validate_chord


MAX_BYTES = 20 * 1024 * 1024
MAX_CHORDS = 1000


def _path(path):
    return Path(path) if path is not None else user_dir() / 'custom-chords.json'


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError('A library chord needs a nonblank name of at most 4096 characters')
    return value


def _chord(value):
    if not isinstance(value, dict):
        raise ValueError('A library chord must be a diagram mapping')
    _name(value.get('name'))
    frets = value.get('frets')
    if not isinstance(frets, list) or not 1 <= len(frets) <= 25:
        raise ValueError('A library chord needs 1..25 strings')
    _validate_chord(value, {'tuning': [0] * len(frets), 'max_fret': 36})


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate chord-library field: {key}')
        result[key] = value
    return result


def read_library(path=None):
    """Return fresh data; missing libraries are empty and are not created by reads."""
    target = _path(path)
    try:
        with target.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return {'version': 1, 'revision': 0, 'chords': []}
    try:
        if len(data) > MAX_BYTES:
            raise ValueError('Library exceeds 20 MiB')
        document = json.loads(data, object_pairs_hook=_object)
        if (not isinstance(document, dict) or set(document) != {'version', 'revision', 'chords'} or
                type(document['version']) is not int or document['version'] != 1 or
                type(document['revision']) is not int or not 0 <= document['revision'] <= 2 ** 53 - 1 or
                not isinstance(document['chords'], list) or len(document['chords']) > MAX_CHORDS):
            raise ValueError('Invalid chord-library version, revision or entries')
        names = set()
        for chord in document['chords']:
            _chord(chord)
            if chord['name'] in names:
                raise ValueError(f'Duplicate library chord name: {chord["name"]}')
            names.add(chord['name'])
        return document
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f'Cannot read {target.name}: {exc}. The saved library was not changed.') from exc


def edit_library(edit, path=None):
    """Read/validate/write under the existing OS lock; stale edits never replace newer work."""
    fields = {'add': {'chord'}, 'rename': {'name', 'new_name'}, 'remove': {'name'}}
    if not isinstance(edit, dict) or not isinstance(edit.get('op'), str) or edit['op'] not in fields:
        raise ValueError('Chord library operation must be add, rename or remove')
    if set(edit) != fields[edit['op']] | {'op', 'revision'} or type(edit['revision']) is not int:
        raise ValueError('Chord library edit needs its current revision and exact operation fields')
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    locked = lock_file(target.with_suffix('.lock'))
    if locked is None:
        raise ValueError('The chord library is being edited in another app; refresh and retry')
    try:
        document = read_library(target)
        if document['revision'] != edit['revision']:
            raise ValueError('The chord library changed; refresh and retry')
        chords = document['chords']
        names = [c['name'] for c in chords]
        if edit['op'] == 'add':
            _chord(edit['chord'])
            if edit['chord']['name'] in names:
                raise ValueError('A library chord already has that name')
            if len(chords) >= MAX_CHORDS:
                raise ValueError('The chord library is limited to 1000 shapes')
            chords.append(copy.deepcopy(edit['chord']))
        else:
            name = _name(edit['name'])
            if name not in names:
                raise ValueError('That library chord no longer exists; refresh and retry')
            index = names.index(name)
            if edit['op'] == 'remove':
                del chords[index]
            else:
                new_name = _name(edit['new_name'])
                if new_name == name:
                    return document
                if new_name in names:
                    raise ValueError('A library chord already has that name')
                chords[index]['name'] = new_name
        if document['revision'] == 2 ** 53 - 1:
            raise ValueError('Chord library revision limit reached; no changes were saved')
        document['revision'] += 1
        data = (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if len(data) > MAX_BYTES:
            raise ValueError('The chord library would exceed 20 MiB')
        atomic_write(target, data)
        return document
    finally:
        unlock_file(locked)
