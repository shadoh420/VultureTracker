"""Agent adapters for the existing PHRASES and PROJECT workflows."""
import copy
from pathlib import Path

from .agent import tool, _integer, _boolean, _approved_channels, _voice_guard
from . import phrases


def _path(st, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('give a file or folder path')
    return ((st.base_dir if st else Path.cwd()) / Path(value).expanduser()).resolve()


def _phrase(st, a):
    ph = st.meta.get('phrase')
    if not ph:
        raise ValueError('capture a phrase first')
    if a.get('phrase_id') != ph['id']:
        raise ValueError('phrase_id is not the current comparison; read_phrase again')
    return ph


def _phrase_guard(st, order, channels):
    st._writable()
    st._need_compiled()
    p = st.mod.patterns[st.mod.orders[order]]
    if st.pattern_entry(p.name).get('approved') or _approved_channels(st) & set(channels):
        raise ValueError('comparison targets approved material; leave it to the owner')


@tool('read_phrase', 'Inspect the active frozen phrase comparison, its ID, alternatives, ratings, captured mix and '
      'staleness. Optional variant is 0-based; -1 is line absent. It returns up to 32 rows starting at offset (relative '
      'to the captured range). Without variant, returns summaries only. Ratings and acceptance belong to the owner.',
      {'variant': {'type': 'integer'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}})
def read_phrase(st, a):
    with st.lock:
        ph = st.meta.get('phrase')
        if not ph:
            return {'phrase': None}
        out = {k: copy.deepcopy(ph[k]) for k in ('id', 'order', 'pattern', 'r0', 'r1', 'mix', 'muted', 'accepted') if k in ph}
        out['channels'] = [c + 1 for c in ph['chans']]
        out['muted'] = [c + 1 for c in ph['muted']]
        out['variants'] = [dict(index=i, **{k: v for k, v in item.items() if k != 'data'})
                           for i, item in enumerate(ph['variants'])]
        out['absent'] = dict(index=-1, **ph['absent'])
        out['stale'] = (st.dirty() or st.text_sha() != ph['base_hash'] or st.mix() != ph['mix']
                        or st.silenced() != ph['muted'] or st.want != ph.get('want'))
        try:
            st._check_assets({'assets': ph['source_assets']})
        except ValueError as e:
            out.update(stale=True, stale_reason=str(e))
        if 'variant' in a:
            i = _integer(a['variant'], -1, len(ph['variants'])-1, 'variant')
            offset = _integer(a.get('offset', 0), 0, len(ph['original']), 'offset')
            limit = _integer(a.get('limit', 32), 1, 32, 'limit')
            cells = phrases.cells(ph, i)
            rows = [' | '.join(c['cell'] for c in cells[r:r+len(ph['chans'])])
                    for r in range(0, len(cells), len(ph['chans']))]
            out.update(variant=i, offset=offset, rows=rows[offset:offset+limit],
                       next_offset=offset+limit if offset+limit < len(rows) else None)
        return out


@tool('capture_phrase', 'Capture 2-4 alternatives and a line-absent version from one order and inclusive rows. '
      'Channels are 1-based. Freezes current sounds, accompaniment and audition mix; song notes are unchanged. '
      'An existing comparison requires replace_id from read_phrase and is archived by PHRASES. Sidecar/assets are '
      'outside song undo. Owner ratings, acceptance and approved material are protected.',
      {'order': {'type': 'integer'}, 'r0': {'type': 'integer'}, 'r1': {'type': 'integer'},
       'channels': {'type': 'array', 'items': {'type': 'integer'}}, 'count': {'type': 'integer'},
       'replace_id': {'type': 'string'}}, ['order', 'r0', 'r1', 'channels'])
def capture_phrase(st, a):
    with st.lock:
        st._need_compiled()
        order = _integer(a['order'], 0, len(st.mod.orders)-1, 'order')
        if st.mod.orders[order] >= len(st.mod.patterns):
            raise ValueError('choose a playable order')
        rows = len(st.mod.patterns[st.mod.orders[order]].rows)
        r0 = _integer(a['r0'], 0, rows-1, 'r0')
        r1 = _integer(a['r1'], r0, rows-1, 'r1')
        if not isinstance(a['channels'], list) or not a['channels']:
            raise ValueError('choose at least one channel')
        chans = sorted({_integer(c, 1, len(st.mod.channels), 'channel')-1 for c in a['channels']})
        _phrase_guard(st, order, chans)
        old = st.meta.get('phrase')
        if old and a.get('replace_id') != old['id']:
            raise ValueError('read_phrase and provide replace_id to archive the existing comparison')
        phrases.action(st, dict(action='capture', order=order, r0=r0, r1=r1, chans=chans,
                               count=_integer(a.get('count', 3), 2, 4, 'count')))
        return {**read_phrase(st, {}), 'summary': 'captured frozen alternatives; owner chooses in PHRASES'}


@tool('edit_phrase', 'Edit a draft alternative by replacing its complete row/channel data and/or its name. '
      'variant is 0-based. One text line per captured row, channels separated with |. Keep timing and global effects '
      'unchanged. Requires current phrase_id. No ratings, acceptance or song edits; use read_phrase to inspect it.',
      {'phrase_id': {'type': 'string'}, 'variant': {'type': 'integer'}, 'name': {'type': 'string'},
       'data': {'type': 'string'}}, ['phrase_id', 'variant'])
def edit_phrase(st, a):
    with st.lock:
        ph = _phrase(st, a)
        if read_phrase(st, {})['stale']:
            raise ValueError('comparison is stale; capture a new comparison before editing')
        _phrase_guard(st, ph['order'], ph['chans'])
        i = _integer(a['variant'], 0, len(ph['variants'])-1, 'variant')
        if not {'name', 'data'} & a.keys() or a.keys() - {'phrase_id', 'variant', 'name', 'data'}:
            raise ValueError('only name and data may be edited; ratings and acceptance belong to the owner')
        phrases.action(st, {'action': 'update', 'variant': i, **{k: a[k] for k in ('name', 'data') if k in a}})
        return {'phrase_id': ph['id'], 'variant': i, 'summary': 'updated draft alternative; song unchanged'}


@tool('render_phrase', 'Render one frozen alternative (0-based variant; -1 is line absent) synchronously using '
      'PHRASES. Returns a local WAV and app audio URL. Stale comparisons remain renderable from frozen assets, '
      'but cannot be accepted. Does not start playback or select/accept a winner.',
      {'phrase_id': {'type': 'string'}, 'variant': {'type': 'integer'}}, ['phrase_id', 'variant'])
def render_phrase(st, a):
    with st.lock:
        ph = _phrase(st, a)
        i = _integer(a['variant'], -1, len(ph['variants'])-1, 'variant')
        result = phrases.action(st, {'action': 'render', 'variant': i})
        return {**result, 'phrase_id': ph['id'], 'variant': i, 'url': '/wav/' + result['key'],
                'summary': 'frozen alternative rendered; audition it in PHRASES'}


@tool('phrase_diff', 'Preview the song change for one current frozen alternative, without accepting it. '
      'Reports stale comparison errors exactly as PHRASES does. Only the owner accepts in the app.',
      {'phrase_id': {'type': 'string'}, 'variant': {'type': 'integer'}}, ['phrase_id', 'variant'])
def phrase_diff(st, a):
    with st.lock:
        ph = _phrase(st, a)
        i = _integer(a['variant'], -1, len(ph['variants'])-1, 'variant')
        return phrases.action(st, {'action': 'diff', 'variant': i})


@tool('project_status', 'Inspect the open project path, compile/read-only/external-change status and each sample '
      'file path/existence. With no song open, returns the app start screen recent/demo paths.', {})
def project_status(st, a):
    from .gui import start_snapshot
    if st is None:
        return start_snapshot()
    with st.lock:
        files = [{'slot': n, 'file': str((st.base_dir / entry['file']).resolve()),
                  'exists': (st.base_dir / entry['file']).is_file()}
                 for n, entry in (st.song.get('samples') or {}).items() if isinstance(entry, dict) and entry.get('file')]
        return {'path': str(st.song_path), 'compile_error': st.error, 'read_only': st.read_only,
                'external_changes': st.dirty(), 'samples': files, 'missing': [f for f in files if not f['exists']]}


@tool('create_project', 'Create a NEW YAML project using the app template: empty pattern, 1-64 channels and a first '
      'sample/instrument (provided WAV or generated C-5 tone). Does not switch the open song; call open_project next. '
      'Refuses an existing destination. Relative paths use the open song folder, or the app working directory.',
      {'path': {'type': 'string'}, 'channels': {'type': 'integer'}, 'sample': {'type': 'string'}}, ['path'])
def create_project(st, a):
    from .gui import create_song
    sample = _path(st, a['sample']) if a.get('sample') else None
    if sample:
        from .wavload import read_wav
        read_wav(sample)
    path = create_song(_path(st, a['path']), _integer(a.get('channels', 8), 1, 64, 'channels'), sample)
    return {'path': str(path), 'summary': 'new project created; use open_project to switch to it'}


@tool('import_project', 'Import IT/XM/S3M/MOD, Guitar Pro 3-5 or MIDI using the app importer. Writes a new YAML and '
      'sample folder beside the source, numbered on collision; preserves the source. GP/MIDI use placeholder sounds. '
      'Returns warnings. Does not switch songs; call open_project on the returned path.',
      {'file': {'type': 'string'}}, ['file'])
def import_project(st, a):
    from .gui import import_beside, GP_SUFFIXES, MIDI_SUFFIXES
    path = _path(st, a['file'])
    if path.suffix.lower() not in ('.it', '.xm', '.s3m', '.mod', *GP_SUFFIXES, *MIDI_SUFFIXES):
        raise ValueError('choose IT/XM/S3M/MOD, GP3-5 or MIDI')
    out, warnings = import_beside(path)
    return {'path': str(out), 'warnings': warnings, 'summary': 'imported a new project; use open_project to open it'}


@tool('open_project', 'Switch the app to an existing YAML project; follow-up tools use that project. Read get_state '
      'again before editing. Refuses external changes, pending UI edits, active recording/render/export jobs, and a '
      'stale source state. The destination may open read-only or with missing samples: inspect the returned status. '
      'Opening is not a song undo step. Use import_project first for modules/MIDI/tabs.',
      {'path': {'type': 'string'}}, ['path'])
def open_project(st, a):
    from .gui import Handler
    if Handler.state is not st:
        raise ValueError('the open project changed; inspect project_status again')
    path = _path(st, a['path'])
    if not path.is_file() or path.suffix.lower() not in ('.yaml', '.yml'):
        raise ValueError('open an existing YAML song; import modules first')
    if st:
        with st.lock:
            if st.dirty():
                raise ValueError('compare/reload external changes before switching projects')
            if (st.ui_state or {}).get('pending_edits'):
                raise ValueError('wait for pending page edits before switching projects')
            if any(job and job.get('status') in ('queued', 'rendering', 'cancelling', 'fetching')
                   for job in (st.synthesis_job, st.export_result, st.recipe_job)):
                raise ValueError('wait for the active render/export job before switching projects')
    Handler.open_song(path, agent_request=True)
    return {**project_status(Handler.state, {}), 'summary': 'opened project; subsequent tools target this song'}


@tool('collect_project', 'Collect the open project into a NEW folder outside its current folder, optionally ZIP. '
      'Reuses PROJECT: includes samples/candidates, recipes and file inputs, frozen phrase assets, notes and credits. '
      'Verifies the copy. Original stays intact; copy starts fresh undo history. Named synths are not bundled. '
      'Does not switch projects. Existing destinations are refused.',
      {'destination': {'type': 'string'}, 'zip': {'type': 'boolean'}}, ['destination'])
def collect_project(st, a):
    from .project import collect
    return collect(st, _path(st, a['destination']), _boolean(a, 'zip'))


@tool('relink_samples', 'Relink sample file paths as ONE undo step; links maps slot numbers to WAV paths. Works '
      'when missing files prevent compilation. Preserves sample settings and implicit names. All replacements must '
      'validate together. Approved sounds are protected; an uncompiled song with approved material needs owner repair.',
      {'links': {'type': 'object', 'additionalProperties': {'type': 'string'}}}, ['links'])
def relink_samples(st, a):
    with st.lock:
        st._writable()
        if not isinstance(a['links'], dict) or not a['links']:
            raise ValueError('links must map slot numbers to WAV paths')
        links = {}
        for n, value in a['links'].items():
            if not str(n).isdigit() or int(n) not in (st.song.get('samples') or {}):
                raise ValueError('no such sample slot')
            n = int(n)
            if n in links:
                raise ValueError('duplicate sample slot')
            if not st.error and st.mod is not None:
                _voice_guard(st, 'samples', n)
            elif (any(isinstance(e, dict) and e.get('approved') for kind in ('samples', 'instruments', 'patterns')
                      for e in (st.song.get(kind) or {}).values()) or _approved_channels(st)):
                raise ValueError('uncompiled song has approved material; relink it in PROJECT')
            links[n] = str(_path(st, value))
        st.relink(links=links)
        return {'slots': list(links), 'summary': 'relinked sample files in one undo step'}
