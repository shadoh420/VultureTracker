"""Immutable render snapshots shared by phrase comparisons and export jobs."""
import copy
import glob
import itertools
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import uuid

from . import api
from .model import ORDER_END
from .notation import format_cell
from .openmpt import LoadedModule
from .fileio import atomic_write, device_name, link_new, protect_outputs, wav_bytes
from .history import digest

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
    from .gui import patch_it
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
    from .gui import patch_it, voice_entry
    base = copy.deepcopy(song)
    base.pop('sections', None)
    assets = {p.resolve(): digest(p.read_bytes()) for p in api.output_sources(base, folder)}
    mix = copy.deepcopy(mix or {})
    for num, edit in (mix.get('instrument') or {}).items():
        if int(num) in (base.get('instruments') or {}):
            base['instruments'][int(num)] = voice_entry(base['instruments'][int(num)], edit)
    whole, mod, warnings = api.compile_song(base, folder)
    it = patch_it(whole, muted, mix)
    with LoadedModule(it) as lm:
        duration = lm.duration()
    seek = None
    tail = float(tail)
    if not 0 <= tail <= 10:
        raise ValueError('Tail must be between 0 and 10 seconds')
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


def render(snapshot, silenced=(), cancel=None):
    from .gui import patch_it
    with LoadedModule(patch_it(snapshot['render_it'], silenced)) as lm:
        if snapshot['seek'] is not None:
            lm.order_start(*snapshot['seek'])
        pcm = lm.render(RATE, max_seconds=snapshot['frames']/RATE, cancel=cancel)
    length = snapshot['frames'] * 4
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


def prepare(state, options):
    """Compile before queueing so later edits, faders and WAV changes cannot alter this job."""
    with state.lock:
        state._need_compiled()
        if state.dirty():
            raise ValueError('Compare and RELOAD external edits before exporting')
        fmt = str(options.get('fmt', 'wav')).lower()
        if fmt not in ('it', 'wav', 'mp3', 'ogg', 'flac'):
            raise ValueError('Choose IT, WAV, MP3, OGG or FLAC')
        region_name = options.get('region') or ''
        loop = bool(options.get('loop'))
        if loop and fmt not in ('wav', 'ogg', 'flac'):
            raise ValueError('A game loop is exported as WAV (smpl chunk), OGG or FLAC (LOOPSTART and LOOPLENGTH tags)')
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
        mix = state.mix() if mode == 'current' else {}
        silenced = state.silenced() if mutes == 'respect' else []
        base = api.from_yaml(state.patched_text(state.want)[0]) if mode == 'current' and state.want else state.song
        snap = snapshot(base, state.base_dir, region, mix, silenced, options.get('tail', 2), loop)
        folder = (state.base_dir / Path(options.get('destination') or '.').expanduser()).resolve()  # relative: beside the song
        name = str(options.get('name') or state.song_path.stem)
        if name in ('.', '..') or not name.strip() or re.search(r'[\\/:*?"<>|]', name) or device_name(name):
            raise ValueError('Output name must be a filename without directories or reserved characters, and not a '
                             'Windows device name (CON, PRN, AUX, NUL, COM1-9, LPT1-9)')
        chans = [i for i in range(snap['channels']) if any(u[i] for u in state.facts['use'])] if options.get('stems') else []
        stemfmt = 'wav' if fmt == 'it' else fmt
        todo = [(folder / (name+'.'+fmt), None, fmt)] if options.get('song', True) else []
        if options.get('include_it') and fmt != 'it':
            todo.insert(0, (folder / (name+'.it'), None, 'it'))
        stemdir = folder / (name+'_stems')
        for i in chans:
            label = re.sub(r'[^\w-]+', '_', state.facts['channels'][i]).strip('_') or 'ch'
            todo.append((stemdir / f'{i+1:02d}-{label}.{stemfmt}', i, stemfmt))
        if not todo:
            raise ValueError('Choose song or stems to export')
        protected = sources(state)
        protect_outputs([p for p, _, _ in todo], protected)
        existing = {str(p): digest(p.read_bytes()) if p.exists() else None for p, _, _ in todo}
        if not options.get('replace', False) and any(v is not None for v in existing.values()):
            raise ValueError('An output exists. Choose another destination/name or enable Replace previous exports')
        return {'snapshot': snap, 'todo': todo, 'sources': protected, 'existing': existing,
                'cancel': threading.Event(), 'folder': folder, 'region': region_name, 'mix': mode,
                'result': {'job_id': uuid.uuid4().hex, 'status': 'queued', 'done': 0, 'total': len(todo), 'dir': str(stemdir) if chans else None,
                           'song': str(todo[0][0]) if options.get('song', True) else None, 'fmt': fmt, 'error': None,
                           'files': [], 'seconds': snap['frames']/RATE, 'snapshot': digest(snap['it'])[:12],
                           'warnings': snap['warnings'], 'mismatches': [], 'bytes': len(snap['it']), 'loop': snap['loop']}}


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
        staged = []
        for i, (path, ch, fmt) in enumerate(job['todo']):
            if cancel():
                raise ValueError('Export cancelled')
            tmp = stage / f'{i}.{fmt}'
            if fmt == 'it':
                atomic_write(tmp, job['snapshot']['it'])
            else:
                silenced = [] if ch is None else [c for c in range(job['snapshot']['channels']) if c != ch]
                pcm = render(job['snapshot'], silenced, cancel)
                if fmt == 'wav':
                    atomic_write(tmp, wav_bytes(pcm, loop=job['snapshot']['loop']))
                else:
                    encode(tmp, pcm, fmt, job['snapshot']['loop'])
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
