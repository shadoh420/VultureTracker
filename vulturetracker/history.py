"""Bounded history and a recoverable three-file save, without replacing external song edits."""
import base64
import hashlib
import itertools
import json
from pathlib import Path
import re
import zlib

from .fileio import atomic_write

MAX_BYTES = 64 * 1024 * 1024
HISTORY_BYTES = 16 * 1024 * 1024
JOURNAL_BYTES = 8 * MAX_BYTES  # six bounded files plus base64 overhead, including legacy history


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_optional(path):
    return path.read_bytes() if path.exists() else None


def json_bytes(value, limit=MAX_BYTES):
    raw = json.dumps(value, ensure_ascii=False, indent=1).encode('utf-8')
    if len(raw) > limit:
        raise ValueError('Saved data exceeds its size limit; remove checkpoints or trim history in PROJECT.')
    return raw


def compressed(raw):
    return base64.b64encode(zlib.compress(raw, 1)).decode('ascii')


def expanded(value):
    decoder = zlib.decompressobj()
    raw = decoder.decompress(base64.b64decode(value, validate=True), MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or not decoder.eof or decoder.unused_data:
        raise ValueError('Invalid or oversized compressed history')
    return raw


def pack_step(step):
    if 'text' not in step:
        return step
    packed = dict(step)
    packed['text_z'] = compressed(packed.pop('text').encode('utf-8'))
    return packed


def unpack_step(step):
    if 'text_z' not in step:
        return step
    plain = dict(step)
    plain['text'] = expanded(plain.pop('text_z')).decode('utf-8')
    return plain


def quarantine(path, reason, notices):
    dest = next(path.with_name(path.name + f'.{reason}-{i}') for i in itertools.count(1)
                if not path.with_name(path.name + f'.{reason}-{i}').exists())
    path.rename(dest)
    notices.append(f'{path.name}: {reason}; preserved as {dest.name}. The song was not replaced.')


def validate_meta(meta):
    if meta is not None:
        if not isinstance(meta, dict):
            raise ValueError('invalid history settings')
        for k in ('mix', 'candidates', 'ratings', 'loop', 'phrase', 'project_settings'):
            if k in meta and meta[k] is not None and not isinstance(meta[k], dict):
                raise ValueError(f'invalid {k} in history')
        for k in ('muted', 'orders'):
            if k in meta and meta[k] is not None and not isinstance(meta[k], list):
                raise ValueError(f'invalid {k} in history')


def validate_step(step):
    if isinstance(step, dict):
        step = unpack_step(step)
    if not isinstance(step, dict) or not isinstance(step.get('text'), str):
        raise ValueError('invalid history step')
    validate_meta(step.get('meta'))
    assets = step.get('assets')
    if not isinstance(assets, dict) or any(not isinstance(k, str) or (v is not None and
                                           (not isinstance(v, str) or not re.fullmatch('[0-9a-f]{64}', v)))
                                           for k, v in assets.items()):
        raise ValueError('invalid history asset fingerprints')


class History:
    def __init__(self, song, notices, passive=False):
        """`passive`: another process has the song open; an interrupted save's journal and a history that does not parse
        are left for it to reconcile."""
        self.song = Path(song)
        self.path = self.song.with_suffix('.history.json')
        self.journal = self.song.with_suffix('.recovery.json')
        self.paths = [self.song, self.song.with_suffix('.tryout.json'), self.path]
        self.notices = notices
        self.passive = passive
        if not passive:
            self.recover()

    def _read(self, path):
        if path.stat().st_size > (JOURNAL_BYTES if path == self.journal else MAX_BYTES):
            raise ValueError('recovery file is too large')
        return self._decode(path.read_bytes())

    def _decode(self, raw):
        obj = json.loads(raw)
        if not isinstance(obj, dict) or obj.get('schema') not in (1, 2) or obj.get('song') != str(self.song):
            raise ValueError('unsupported schema or different song location')
        return obj

    @staticmethod
    def _validate(obj):
        for key in ('undo', 'redo'):
            if not isinstance(obj.get(key), list) or len(obj[key]) > 200:
                raise ValueError('invalid history stack')
            for step in obj[key]:
                validate_step(step)
        cps = obj.get('checkpoints')
        if not isinstance(cps, dict) or len(cps) > 32:
            raise ValueError('invalid checkpoints')
        for name, step in cps.items():
            if not isinstance(name, str) or not name or len(name) > 80:
                raise ValueError('invalid checkpoint name')
            validate_step(step)
        if not isinstance(obj.get('head'), str) or not re.fullmatch('[0-9a-f]{64}', obj['head']):
            raise ValueError('invalid history head')

    def load(self):
        if not self.path.exists():
            return None
        try:
            obj = self._read(self.path)
            self._validate(obj)
            for key in ('undo', 'redo'):
                obj[key] = [pack_step(step) for step in obj[key]]
            obj['checkpoints'] = {name: pack_step(step) for name, step in obj['checkpoints'].items()}
            return obj
        except (ValueError, TypeError, KeyError, UnicodeError, zlib.error):
            if self.passive:
                self.notices.append(f'{self.path.name} could not be read; left as it is')
            else:
                quarantine(self.path, 'corrupt', self.notices)
            return None

    def data(self, raw, undo, redo, checkpoints):
        return json_bytes({'schema': 2, 'song': str(self.song), 'head': digest(raw),
                           'undo': [pack_step(s) for s in undo], 'redo': [pack_step(s) for s in redo],
                           'checkpoints': {n: pack_step(s) for n, s in checkpoints.items()}})

    def bounded(self, raw, undo, redo, checkpoints):
        undo, redo = list(undo), list(redo)
        while True:
            try:
                data = self.data(raw, undo, redo, checkpoints)
            except ValueError:
                data = None  # an oversized legacy stack still needs to be pruned
            if data is not None and len(data) <= HISTORY_BYTES:
                return data, undo, redo
            stack = undo if len(undo) >= len(redo) else redo
            if not stack:
                raise ValueError('Named checkpoints exceed 16 MiB; delete a checkpoint in PROJECT before saving.')
            del stack[0]

    def recover(self):
        if not self.journal.exists():
            return
        try:
            obj = self._read(self.journal)
            pairs = obj['files']
            if not isinstance(pairs, list) or len(pairs) != 3 or any(not isinstance(p, list) or len(p) != 2 for p in pairs):
                raise ValueError('invalid transaction')
            decode = expanded if obj['schema'] == 2 else lambda raw: base64.b64decode(raw, validate=True)
            pairs = [[None if raw is None else decode(raw) for raw in pair] for pair in pairs]
            if any(raw is None for raw in pairs[0]) or any(pair[1] is None for pair in pairs):
                raise ValueError('invalid transaction files')
            # Validate both outcomes before touching any current sidecar.
            for raw in pairs[1]:
                if raw is not None:
                    meta = json.loads(raw)
                    if not isinstance(meta, dict):
                        raise ValueError('invalid transaction settings')
                    validate_meta(meta)
            for raw in pairs[2]:
                if raw is not None:
                    self._validate(self._decode(raw))
            if self._decode(pairs[2][1])['head'] != digest(pairs[0][1]):
                raise ValueError('transaction history does not match its song')
            current = [read_optional(p) for p in self.paths]
            side = 1 if current[0] == pairs[0][1] else 0 if current[0] == pairs[0][0] else None
            if side is None or any(raw not in pair for raw, pair in zip(current[1:], pairs[1:])):
                quarantine(self.journal, 'external-conflict', self.notices)
                return
            # Only related sidecars are reconciled. Recovery NEVER writes the YAML.
            for path, pair in zip(self.paths[1:], pairs[1:]):
                self._restore(path, pair[side])
            self.journal.unlink()
            self.notices.append('Recovered an interrupted save; history and settings match the song on disk.')
        except (ValueError, TypeError, KeyError, UnicodeError, zlib.error):
            quarantine(self.journal, 'corrupt', self.notices)

    @staticmethod
    def _restore(path, raw):
        if raw is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, raw)

    def write(self, raw, meta, history, writer, expected):
        before = [read_optional(p) for p in self.paths]
        if before[0] != expected:
            raise ValueError('The song changed while preparing the save; compare and RELOAD first')
        after = [raw, json_bytes(meta), history]
        if any(x is not None and len(x) > MAX_BYTES for x in before + after):
            raise ValueError('A save file exceeds 64 MiB; trim history in PROJECT before saving.')
        pairs = [[None if x is None else compressed(x) for x in pair] for pair in zip(before, after)]
        atomic_write(self.journal, json_bytes({'schema': 2, 'song': str(self.song), 'files': pairs}, JOURNAL_BYTES))
        try:
            if read_optional(self.song) != before[0]:
                raise ValueError('The song changed while preparing the save; compare and RELOAD first')
            writer()
            for path, old, new in zip(self.paths[1:], before[1:], after[1:]):
                if read_optional(path) != old:
                    raise ValueError(f'{path.name} changed during save; external settings preserved')
                if old != new:
                    atomic_write(path, new)
        except Exception:
            try:
                for path, old, new in zip(self.paths, before, after):
                    current = read_optional(path)
                    if current not in (old, new):
                        raise OSError(f'{path.name} changed externally during save; recovery kept for comparison')
                    if current != old:
                        self._restore(path, old)
                self.journal.unlink(missing_ok=True)
            except OSError as error:
                self.notices.append(f'Save rollback needs attention: {error}')
            raise
        try:
            self.journal.unlink()
        except OSError:
            self.notices.append('Save completed; its recovery journal will be reconciled on reopening.')
