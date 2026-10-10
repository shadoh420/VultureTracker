"""Agent access to the existing library, recipe renderer and spectral painter.

Recipes are saved as new versions; renders publish new assets, never song edits or tryout choices.
The State worker owns rendering, so closing a song or cancelling a job cannot publish a late result.
"""
import copy
import json
import math
import re
import shutil
import uuid
from pathlib import Path

from .agent import tool, _integer, _boolean
from . import api, synth


def _path(st, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('give a file or folder path')
    return (st.base_dir / value).resolve()


def _page(a, items):
    offset = _integer(a.get('offset', 0), 0, 1000000, 'offset')
    limit = _integer(a.get('limit', 30), 1, 100, 'limit')
    return {'results': items[offset:offset+limit], 'total': len(items),
            'next_offset': offset+limit if offset+limit < len(items) else None}


_PAGE = {'query': {'type': 'string'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}}


@tool('library_status', 'Read the shared sample index: effective roots, count, progress, latest job ID and result. '
      'Provide job_id when polling to reject results belonging to a newer UI/agent job. Scans and similarity searches '
      'are asynchronous; done means this job finished, and error means it failed.', {'job_id': {'type': 'string'}})
def library_status(st, a):
    from .gui import Handler
    lib = Handler.lib()
    with lib.lock:
        job_id = getattr(lib, 'job_id', None)
        if 'job_id' in a and a['job_id'] != job_id:
            raise ValueError('this is not the current library job')
        busy = bool(lib.job and lib.job.is_alive())
        return copy.deepcopy({**Handler.lib_snapshot(), 'roots': lib.roots, 'job_id': job_id,
                              'done': bool(job_id) and not busy, 'result': None if busy else lib.result})


@tool('index_library', 'Refresh the WAV library index on a background job. With roots omitted, scan configured roots. '
      'Provided roots are ADDED by default; replace_roots=true deliberately replaces the shared library folders. '
      'Files must exist; no downloads. Poll library_status with the returned job_id. This updates the shared index, '
      'not the song, and is not song undo history.',
      {'roots': {'type': 'array', 'items': {'type': 'string'}}, 'replace_roots': {'type': 'boolean'}})
def index_library(st, a):
    from .gui import Handler
    lib = Handler.lib()
    roots = None
    replace = _boolean(a, 'replace_roots')
    if replace and 'roots' not in a:
        raise ValueError('replace_roots requires roots')
    if 'roots' in a:
        if not isinstance(a['roots'], list) or not a['roots']:
            raise ValueError('roots must be a nonempty list')
        paths = [_path(st, r) for r in a['roots']]
        if any(not p.is_dir() and not (p.is_file() and p.suffix.lower() == '.wav') for p in paths):
            raise ValueError('each root must be an existing folder or WAV')
        roots = list(dict.fromkeys(([] if replace else lib.roots) + [str(p) for p in paths]))
    with lib.lock:
        lib.run(lambda: lib.scan(roots), wait=0)
        return {'status': 'queued', 'job_id': lib.job_id, 'summary': 'library scan queued; poll library_status'}


@tool('search_library', 'Search indexed WAV names and paths by case-insensitive text (all query words must match). '
      'Returns measured metadata and whether its file stamp is current. No implicit scan or candidate selection. '
      'Use index_library first if empty/stale; use similar_samples for measured timbre similarity.', _PAGE)
def search_library(st, a):
    from .gui import Handler
    from .library import stamp
    lib = Handler.lib()
    words = str(a.get('query', '')).casefold().split()
    with lib.lock:
        items = [(p, copy.deepcopy(e)) for p, e in sorted(lib.data['files'].items())
                 if 'vec' in e and all(w in p.casefold() for w in words)]
        generation = lib.generation
    page = _page(a, items)
    results = []
    for p, entry in page['results']:
        try:
            current = stamp(p) == entry.get('stamp')
        except OSError:
            continue
        results.append({'file': p, 'name': Path(p).stem, 'current': current, **entry.get('info', {})})
    return {**page, 'results': results, 'generation': generation,
            'summary': f'{len(results)} indexed sounds returned (filename search)'}


@tool('similar_samples', 'Queue measured timbre similarity against the current index. Give exactly one WAV file '
      'or sample slot. Does not scan, select or add candidates; poll library_status with job_id, then offer_samples '
      'for the owner to audition. Distance is a feature-space measurement, not a musical-quality score.',
      {'file': {'type': 'string'}, 'slot': {'type': 'integer'}, 'limit': {'type': 'integer'}})
def similar_samples(st, a):
    from .gui import Handler
    lib = Handler.lib()
    if ('file' in a) == ('slot' in a):
        raise ValueError('give exactly one file or slot')
    with st.lock:
        if 'slot' in a:
            slot = _integer(a['slot'], 1, 99, 'slot')
            if slot not in (st.song.get('samples') or {}):
                raise ValueError('no such sample slot')
            query = Path(st.current_file_of(slot)).resolve()
        else:
            query = _path(st, a['file'])
    if not query.is_file():
        raise ValueError('query WAV does not exist')
    k = _integer(a.get('limit', 8), 1, 100, 'limit')
    def find():
        return {'results': [{'file': p, 'distance': round(d, 6)} for p, d in lib.nearest(query, k) if Path(p).is_file()],
                'query': str(query), 'summary': 'measured timbre matches; owner decides by ear'}
    with lib.lock:
        lib.run(find, wait=0)
        return {'status': 'queued', 'job_id': lib.job_id, 'summary': 'similarity search queued; poll library_status'}


@tool('synthesis_catalog', 'Inspect source types/dependencies, search installed patch names, list nearby recipe files, '
      'or inspect a patch parameter list. action=parameters loads the named patch and returns matching parameter names '
      'with value/type/units/range for recipe params (raw_value is normalized and is not the recipe value). '
      'It creates no audio. Never downloads dependencies. query is case-insensitive text.',
      {**_PAGE, 'action': {'type': 'string', 'enum': ['sources', 'patches', 'parameters', 'recipes']},
       'patch': {'type': 'string'}}, ['action'])
def synthesis_catalog(st, a):
    from . import faust
    action = a['action']
    query = str(a.get('query', '')).casefold()
    if action == 'sources':
        try:
            surge = str(synth.surge_paths()[0])
        except synth.SynthMissing:
            surge = None
        return {'sources': ['patch', 'file', 'faust', 'resynth', 'paint'], 'sample_keys': synth.SAMPLE_KEYS,
                'resynth_defaults': synth.RESYNTH_KEYS,
                'dependencies': {'surge': surge, 'dexed': str(synth.DEXED_VST3) if synth.DEXED_VST3.exists() else None,
                    'obxd': str(synth.OBXD_VST3) if synth.OBXD_VST3.exists() else None,
                    'faustwasm': faust.have(), 'node': shutil.which('node')},
                'summary': 'recipes render new files; offer candidates for the owner to choose'}
    if action == 'patches':
        return _page(a, [{'patch': name, 'synth': entry[0]} for name, entry in sorted(synth.patch_index().items())
                         if query in name.casefold()])
    if action == 'recipes':
        with st.lock:
            return _page(a, [{'recipe': str(path), 'entry': name, 'note': note, 'file': str(wav)}
                            for path, outputs in st.recipes() for wav, name, note in outputs
                            if query in (str(path) + ' ' + name).casefold()])
    if action == 'parameters':
        host = synth.Synths()
        host.load(a['patch'])
        page = _page(a, [(name, p) for name, p in host.plugin.parameters.items() if query in name.casefold()])
        page['results'] = [{'name': name, 'value': p.type(getattr(host.plugin, name)), 'type': p.type.__name__,
                            'units': p.label, 'min': p.min_value, 'max': p.max_value,
                            'choices': p.valid_values[:64] if p.type is str else None,
                            'choice_count': len(p.valid_values) if p.type is str else None,
                            'raw_value': float(p.raw_value)} for name, p in page['results']]
        return page
    raise ValueError('unknown synthesis catalog action')


@tool('read_sound_recipe', 'Read a recipe file and optionally one entry with its defaults, sample rate and output '
      'names. Relative paths resolve from the song folder. Reads do not render or modify anything.',
      {'recipe': {'type': 'string'}, 'entry': {'type': 'string'}}, ['recipe'])
def read_sound_recipe(st, a):
    path = _path(st, a['recipe'])
    if path.suffix.lower() == '.json':
        return {'recipe': str(path), 'paint': json.loads(path.read_text(encoding='utf-8'))}
    doc, rate, out = synth._load_recipe(path)
    result = {'recipe': str(path), 'sample_rate': rate, 'out_dir': str(out)}
    if 'entry' in a:
        spec, defaults = synth.recipe_entry(path, a['entry'])
        result.update(entry=a['entry'], spec=spec, defaults=defaults)
    else:
        result['entries'] = list((doc.get('samples') or {}).keys())
        result['defaults'] = doc.get('defaults') or {}
    return result


def _spec(st, a):
    """A frozen, single-output spec, with input paths anchored before saving beside the song."""
    if ('recipe' in a) == ('spec' in a):
        raise ValueError('give exactly one spec or recipe (with entry)')
    base, rate = st.base_dir, 44100
    if 'recipe' in a:
        path = _path(st, a['recipe'])
        _, rate, _ = synth._load_recipe(path)
        entry, defaults = synth.recipe_entry(path, a['entry'])
        spec, base = {**defaults, **entry}, path.parent
    else:
        spec = copy.deepcopy(a['spec'])
    if not isinstance(spec, dict):
        raise ValueError('spec must be a recipe entry mapping')
    spec = copy.deepcopy(spec)
    changes = a.get('changes', {})
    if not isinstance(changes, dict):
        raise ValueError('changes must be a mapping')
    spec.update(copy.deepcopy(changes))
    json.dumps(spec, allow_nan=False)  # reject non-finite values in nested synth/effect parameters too
    for key in a.get('clear', []):
        if key not in synth.SAMPLE_KEYS:
            raise ValueError(f'unknown recipe field {key}')
        spec.pop(key, None)
    rate = _integer(a.get('sample_rate', rate), 8000, 192000, 'sample_rate')
    jobs = list(synth.expand({'samples': {'sound': spec}}))
    if 'note' in a:
        jobs = [j for j in jobs if str(j[1].get('note')) == a['note']]
    if len(jobs) != 1:
        raise ValueError('render one note at a time; select note for a notes list')
    spec = jobs[0][1]
    spec.pop('_name_by_root', None)
    synth._job_root('sound', spec)
    # Bound sample jobs, including numeric NaNs, before a plugin or numpy allocates the render.
    for key in ('hold', 'tail', 'fx_tail', 'start', 'length', 'fade_out'):
        if key in spec and (not isinstance(spec[key], (int, float)) or not math.isfinite(spec[key]) or not 0 <= spec[key] <= 60):
            raise ValueError(f'{key} must be finite, 0..60 seconds for an agent render')
    if 'patch' in spec or 'faust' in spec:
        events, seconds, _ = synth._events(spec, 'sound')
        if not 0 < seconds <= 60 or len(events) > 128 or any(not 0 <= start < end <= 60 for _, _, start, end in events):
            raise ValueError('render 0..60 seconds and at most 128 notes with positive lengths')
    def paths(value):
        return [str((base / p).resolve()) for p in value] if isinstance(value, list) else str((base / value).resolve())
    if 'file' in spec:
        spec['file'] = paths(spec['file'])
    if 'resynth' in spec:
        rs = spec['resynth']
        rs['target'], rs['corpus'] = paths(rs['target']), paths(rs['corpus'])
        seconds = float(rs.get('corpus_seconds', 120))
        if not 0 < seconds <= 120:
            raise ValueError('corpus_seconds must be 0..120')
        for key, low, high in [('block', .005, 2), ('overlap', 1, 16), ('variety', 1, 100),
                               ('reuse', 0, 10), ('level', 0, 1), ('mix', 0, 1), ('gate', -120, 0)]:
            value = float(rs.get(key, synth.RESYNTH_KEYS[key]))
            if not low <= value <= high:
                raise ValueError(f'resynth {key} must be {low}..{high}')
    if 'faust' in spec and '\n' not in str(spec['faust']) and str(spec['faust']).strip().lower().endswith('.dsp'):
        spec['faust'] = (base / spec['faust'].strip()).read_text(encoding='utf-8')
    if 'patch' in spec and (base / spec['patch']).is_file():
        spec['patch'] = str((base / spec['patch']).resolve())
    return spec, rate


_RECIPE = {'recipe': {'type': 'string'}, 'entry': {'type': 'string'}, 'spec': {'type': 'object'},
           'changes': {'type': 'object'}, 'clear': {'type': 'array', 'items': {'type': 'string'}},
           'note': {'type': 'string'}, 'sample_rate': {'type': 'integer'}, 'name': {'type': 'string'}}


def _asset(st, name, suffix):
    name = re.sub(r'[^\w.-]+', '_', str(name or 'sound'))[:40].strip('.') or 'sound'
    return st.base_dir / f'agent-{name}-{uuid.uuid4().hex[:12]}{suffix}'


def _save_recipe(path, spec, rate):
    text = api.safe_dump({'sample_rate': rate, 'out_dir': '.', 'samples': {path.stem: spec}}, sort_keys=False)
    f = path.open('x', encoding='utf-8', newline='\n')
    try:
        with f:
            f.write(text)
    except Exception:
        path.unlink(missing_ok=True)
        raise


@tool('save_sound_recipe', 'Create a reproducible recipe or edit an existing entry into a NEW version beside the song. '
      'Give spec, or recipe+entry with optional changes/clear. Changes replace top-level fields; nested maps replace '
      'whole. Original recipes/WAVs stay intact. Returns recipe and entry for render_synthesis. This creates an asset '
      '(outside song undo); it does not choose a sound or change notes. Paths in an edited recipe retain its base folder.', _RECIPE)
def save_sound_recipe(st, a):
    with st.lock:
        st._writable()
        spec, rate = _spec(st, a)
        path = _asset(st, a.get('name'), '.yaml')
        _save_recipe(path, spec, rate)
        return {'recipe': str(path), 'entry': path.stem, 'spec': spec, 'sample_rate': rate,
                'summary': 'saved a new recipe version; original retained'}


def _queue(st, data):
    with st.lock:
        st._writable()
        if st.closed:
            raise ValueError('song is closed')
        if st.synthesis_job and st.synthesis_job['status'] in ('queued', 'rendering', 'cancelling'):
            raise ValueError('a synthesis job is still running; inspect or cancel it first')
        job = {'job_id': uuid.uuid4().hex, 'status': 'queued', 'error': None, 'log': [], 'file': None,
               'recipe': None, 'cancel': False, 'data': data}
        st.synthesis_job = job
        st._put(0, ('synthesis', job))
        return {'job_id': job['job_id'], 'status': 'queued', 'summary': 'synthesis queued; poll synthesis_status'}


@tool('render_synthesis', 'Render one recipe entry or spec to a NEW WAV and frozen recipe on the song worker. '
      'Supports installed synth patches, file processing, Faust and resynth. Edits can use changes/clear. No automatic '
      'download, slot replacement or candidate selection. Poll synthesis_status with job_id; only done publishes files. '
      'Then offer_samples to audition, or create_sample for an explicitly requested new slot. One note per notes-list '
      'call; at most 60 seconds of notes and 128 events. Cancelling prevents publication after the renderer returns.', _RECIPE)
def render_synthesis(st, a):
    with st.lock:
        st._writable()
        spec, rate = _spec(st, a)
        return _queue(st, {'kind': 'recipe', 'spec': spec, 'rate': rate, 'name': a.get('name')})


_MATRIX = {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'number'}}}
@tool('render_paint', 'Render a spectral picture to a NEW WAV, PNG and reusable settings JSON, using PAINT audio '
      'synthesis. amp and optional pan are rows (low to high frequency) by time columns; brightness 0..1, pan -1..1. '
      'scale=log uses fmin/fmax Hz; scale=notes uses fmin as IT note number. No slot/candidate selection. '
      'Poll synthesis_status; peak normalization matches PAINT (-1 dBFS). Optional file filters that WAV through '
      'the picture instead, retaining its rate/root/loop and attenuating only overload. source reloads saved settings '
      'JSON; supplied fields override it. Use read_sound_recipe to inspect that JSON.',
      {'amp': _MATRIX, 'pan': _MATRIX, 'seconds': {'type': 'number'}, 'fmin': {'type': 'number'},
       'fmax': {'type': 'number'}, 'scale': {'type': 'string', 'enum': ['log', 'notes']},
       'range_db': {'type': 'number'}, 'seed': {'type': 'integer'}, 'name': {'type': 'string'},
       'source': {'type': 'string'}, 'file': {'type': ['string', 'null']}})
def render_paint(st, a):
    from .gui import paint_args
    import numpy as np
    if 'source' in a:
        a = {**json.loads(_path(st, a['source']).read_text(encoding='utf-8')), **a}
    pic = paint_args(a)
    if not np.isfinite(pic['amp']).all() or not np.isfinite(pic['pan']).all():
        raise ValueError('paint values must be finite')
    data = {k: v.tolist() if hasattr(v, 'tolist') else v for k, v in pic.items()}
    data['seed'] = _integer(a.get('seed', 0), 0, 2147483647, 'seed')
    if a.get('file') is not None:
        path = _path(st, a['file'])
        if not path.is_file():
            raise ValueError('filter source WAV does not exist')
        data['file'] = str(path)
    return _queue(st, {'kind': 'paint', 'picture': data, 'name': a.get('name')})


@tool('synthesis_status', 'Inspect the latest synthesis job. Provide job_id to reject a newer job. done supplies '
      'published paths; failed supplies error/need; queued/rendering/cancelling are not completed outputs.',
      {'job_id': {'type': 'string'}})
def synthesis_status(st, a):
    with st.lock:
        job = st.synthesis_job
        if 'job_id' in a and (not job or job['job_id'] != a['job_id']):
            raise ValueError('this is not the current synthesis job')
        return copy.deepcopy({k: v for k, v in job.items() if k not in ('data', 'cancel')} if job else {'status': 'idle'})


@tool('cancel_synthesis', 'Cancel the matching synthesis job. A running plugin/Faust/DSP call finishes before cleanup; '
      'status stays cancelling until then. No partial audio is published. Completed files are not deleted.',
      {'job_id': {'type': 'string'}}, ['job_id'])
def cancel_synthesis(st, a):
    with st.lock:
        synthesis_status(st, a)
        job = st.synthesis_job
        if job['status'] not in ('queued', 'rendering', 'cancelling'):
            raise ValueError('job is already finished')
        job['cancel'] = True
        job['status'] = 'cancelling'
        return {'job_id': job['job_id'], 'status': job['status']}


def render_job(st, job):
    """Publish only after a complete render; cleanup is limited to files reserved by this job."""
    from .gui import paint_args, png_rgb
    from . import spectral
    from .wavload import write_wav, read_wav
    import numpy as np
    paths, terminal = [], None
    def log(message):
        with st.lock:
            job['log'].append(str(message))
            del job['log'][:-40]
    try:
        with st.lock:
            if job['cancel'] or st.closed:
                job['status'] = 'cancelled'
                return
            job['status'] = 'rendering'
            data = job['data']
            out = _asset(st, data.get('name'), '.wav')
        # An exclusive reservation prevents accidental overwrites, even on UUID collision.
        with out.open('xb'):
            pass
        paths.append(out)
        if data['kind'] == 'recipe':
            source = out.with_suffix('.yaml')
            _save_recipe(source, data['spec'], data['rate'])
            paths.append(source)
            synth.render_one(source, source.stem, out=out, log=log)
        else:
            pic = paint_args(data['picture'])
            rate, root, loop = 44100, None, None
            if data['picture'].get('file'):
                w = read_wav(data['picture']['file'])
                rate, root, loop = w.rate, w.root, w.loops[0] if w.loops else None
                if len(w.channels[0]) > rate*60:
                    raise ValueError('spectral filter accepts at most 60 seconds')
                x = np.asarray(w.channels, dtype=float) / (1 << (w.bits-1))
                y = spectral.spectral_mask(x, rate, pic['amp'], pic['fmin'], pic['fmax'], pic['scale'], pic['range_db'])
                peak = float(np.abs(y).max())
                if peak > .999:
                    y *= .999/peak
                    log(f'{20*math.log10(peak/.999):.2f} dB attenuation to prevent clipping')
            else:
                y, peak = spectral.paint_render(**pic, rate=rate, seed=data['picture']['seed'])
                if not math.isfinite(peak) or peak <= 0:
                    raise ValueError('paint is silent or invalid')
                y *= .891 / peak
                if np.abs(y[0]-y[1]).max() <= 1e-6:
                    y = y[:1]
            write_wav(out, rate, np.clip(np.round(y*32768), -32768, 32767).astype(np.int32).tolist(), root_note=root, loop=loop)
            source = out.with_suffix('.json')
            with source.open('x', encoding='utf-8') as f:
                paths.append(source)
                json.dump(data['picture'], f)
            png = out.with_suffix('.png')
            with png.open('xb') as f:
                paths.append(png)
                f.write(png_rgb(spectral.picture_png(pic['amp'], pic['pan'])))
        wav = read_wav(out)
        with st.lock:
            if job['cancel'] or st.closed:
                terminal = 'cancelled'
            else:
                job.update(status='done', file=str(out), recipe=str(source), files=[str(p) for p in paths],
                           root=wav.root, sample_rate=wav.rate, frames=len(wav.channels[0]),
                           summary='new audio assets ready; offer_samples for the owner to audition')
                paths = []
    except Exception as e:  # one render failure must not stop the song worker
        with st.lock:
            terminal = 'cancelled' if job['cancel'] or st.closed else 'failed'
            job.update(error=f'{type(e).__name__}: {e}', need=getattr(e, 'kind', None))
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
        if terminal:
            with st.lock:
                job['status'] = terminal
