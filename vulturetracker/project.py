"""Portable project collection and precise YAML value replacement."""
import copy
import glob
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

import yaml

from . import api
from .fileio import atomic_write, link_new, protect_outputs
from .history import digest, json_bytes
from .song import it_text


def _same_key(node, key):
    """Whether YAML key `node` is `key` as the compiler reads it (`01:` is sample 1)."""
    return node.value == str(key) or (isinstance(key, int) and node.tag.endswith(':int') and api.from_yaml(node.value) == key)


def replace_values(text, replacements):
    """Replace only selected YAML node spans; comments, whitespace and other values survive. A missing last key is
    added in front of its mapping's first key, in that mapping's layout."""
    root = yaml.compose(text, Loader=api._Loader)
    edits, inserts = {}, {}
    for keys, value in replacements:
        node = root
        encoded = json.dumps(value, ensure_ascii=False)  # JSON is valid flow YAML, with unambiguous quoting
        for i, key in enumerate(keys):
            if isinstance(node, yaml.MappingNode):
                found = next((v for k, v in node.value if _same_key(k, key)), None)
                if found is None and i == len(keys) - 1 and node.value:
                    first = node.value[0][0]
                    sep = ', ' if node.flow_style else '\n' + ' ' * first.start_mark.column
                    inserts[first.start_mark.index] = inserts.get(first.start_mark.index, '') + f'{key}: {encoded}{sep}'
                    break
                if found is None:
                    raise ValueError(f'{keys}: not in the song file')
                node = found
            elif isinstance(node, yaml.SequenceNode):
                node = node.value[int(key)]
            else:
                raise ValueError(f'{keys}: not a YAML mapping or sequence')
        else:
            span = node.start_mark.index, node.end_mark.index
            if span in edits and edits[span] != encoded:
                raise ValueError('Shared YAML alias needs different values; expand that alias before editing')
            edits[span] = encoded
    for (a, b), encoded in sorted([*edits.items(), *(((a, a), t) for a, t in inserts.items())], reverse=True):
        text = text[:a] + encoded + text[b:]
    return text


def file_updates(doc, files):
    """replace_values() pairs pointing sample slots ({num: file}) at new files. A slot named after its file (no `name:`)
    keeps that name, so instruments that refer to it still resolve and the module shows the same name."""
    out = []
    for num, new in files.items():
        entry = doc['samples'][num]
        out.append((('samples', num, 'file'), new))
        old = it_text(Path(str(entry['file'])).stem, 25)
        if 'name' not in entry and it_text(Path(str(new)).stem, 25) != old:
            out.append((('samples', num, 'name'), old))
    return out


def map_meta(meta, convert):
    """The file identities in tryout metadata (not arbitrary strings such as listening notes)."""
    out = copy.deepcopy(meta)
    out['candidates'] = {str(k): [convert(p) for p in v] for k, v in (out.get('candidates') or {}).items()}
    for key in ('ratings', 'found', 'recipe_of'):
        if out.get(key):
            out[key] = {convert(k): v for k, v in out[key].items()}
    for rec in (out.get('recipe_of') or {}).values():
        if rec.get('recipe'):
            rec['recipe'] = convert(rec['recipe'])
    if out.get('phrase'):
        ph = out['phrase']
        if ph.get('want'):
            ph['want'] = convert(ph['want'])
        ph['source_assets'] = {convert(k): v for k, v in (ph.get('source_assets') or {}).items()}
    if out.get('selected_candidate'):
        out['selected_candidate'] = convert(out['selected_candidate'])
    return out


def resolve_meta(meta, folder):
    return map_meta(meta, lambda p: str((folder / p).resolve()))


def relative_meta(meta, folder):
    def relative(p):
        try:
            return Path(os.path.relpath((folder / p).resolve(), folder)).as_posix()
        except ValueError:  # another drive
            return str(p)
    return map_meta(meta, relative)


def collect(state, destination, make_zip=False, browser=None):
    """Build in a sibling temporary directory; publish only a verified, independent project."""
    destination = (state.base_dir / Path(destination).expanduser()).resolve()  # relative: from the song's folder
    if destination.exists():
        raise ValueError('Choose a new destination folder; existing folders and files are never merged or replaced')
    if destination == state.base_dir or state.base_dir in destination.parents:
        raise ValueError('Choose a destination outside the original project folder')
    archive = destination.with_name(destination.name + '.zip')  # not with_suffix: "v1.5" would lose ".5"
    if make_zip and archive.exists():
        raise ValueError(f'{archive} already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with state.lock:
        if state.dirty():
            raise ValueError('Compare and RELOAD external edits before collecting')
        text, meta, raw = state.text, copy.deepcopy(state.meta), state._raw
        recipes = state.recipes()
        notes = {p.name: p.read_bytes() for p in state.base_dir.glob(glob.escape(state.song_path.stem) + '.notes*') if p.is_file()}
    temp = Path(tempfile.mkdtemp(prefix='.vt-collect-', dir=destination.parent))
    zip_temp = None
    files, taken = {}, set()

    def copy_file(source, folder='samples', candidate=False):
        source = Path(source).resolve()
        if source in files:
            return files[source]
        if not source.is_file():
            remedy = 'remove it in TRYOUT or restore the file' if candidate else 'relink it'
            raise ValueError(f'Missing project asset: {source}; {remedy} before collecting')
        data = source.read_bytes()
        name = source.name
        rel = Path(folder) / name if folder else Path(name)
        n = 2
        while str(rel).casefold() in taken or (temp / rel).exists():
            rel = (Path(folder) if folder else Path()) / f'{source.stem}-{n}{source.suffix}'
            n += 1
        taken.add(str(rel).casefold())
        (temp / rel).parent.mkdir(parents=True, exist_ok=True)
        (temp / rel).write_bytes(data)
        if source.read_bytes() != data:
            raise ValueError(f'Asset changed during collection: {source}; retry')
        files[source] = rel.as_posix()
        return rel.as_posix()

    def recipe_text(source, text):
        doc = api.from_yaml(text)
        updates = []

        def visit(value, keys=()):
            if isinstance(value, dict):
                for key, val in value.items():
                    path = keys + (key,)
                    if key in ('file', 'target', 'corpus'):
                        patterns = val if isinstance(val, list) else [val]
                        paths = []
                        for pat in patterns:
                            src = source.parent / str(pat)
                            if src.is_dir():
                                matches = sorted(src.rglob('*.wav'))
                            else:  # the recipe's folder is a path, not a pattern; a file named like a pattern is that file
                                found = glob.glob(os.path.join(glob.escape(str(source.parent)), str(pat)), recursive=True)
                                matches = [Path(p) for p in sorted(found)] or ([src] if src.is_file() else [])
                            if not matches:
                                raise ValueError(f'Missing recipe input: {src}')
                            paths.extend(copy_file(p, 'sources') for p in matches if p.is_file())
                        updates.append((path, paths if isinstance(val, list) or len(paths) != 1 else paths[0]))
                    elif key == 'faust' and isinstance(val, str) and val.strip().endswith('.dsp'):
                        updates.append((path, copy_file(source.parent / val, 'sources')))
                    elif key == 'patch' and isinstance(val, str) and (source.parent / val).is_file():
                        updates.append((path, copy_file(source.parent / val, 'sources')))
                    else:
                        visit(val, path)
            elif isinstance(value, list):
                for i, val in enumerate(value):
                    visit(val, keys + (i,))
        visit(doc)
        if 'out_dir' in doc:
            updates.append((('out_dir',), 'samples'))
        result = replace_values(text, updates)
        return result if 'out_dir' in doc else 'out_dir: samples\n' + result

    try:
        # Reserve the song name before copying recipes or assets with the same basename.
        taken.add(state.song_path.name.casefold())
        doc, moved = api.from_yaml(text), {}
        for num, entry in (doc.get('samples') or {}).items():
            if isinstance(entry, dict) and entry.get('file'):
                moved[num] = copy_file(state.base_dir / str(entry['file']))
        collected = replace_values(text, file_updates(doc, moved))
        for paths in (meta.get('candidates') or {}).values():
            for path in paths:
                copy_file(state.base_dir / path, candidate=True)
        wanted = set(files)
        recs = {p for p, outs in recipes if any(w.resolve() in wanted for w, _, _ in outs)}
        recs.update(Path(rec['recipe']) for rec in (meta.get('recipe_of') or {}).values() if rec.get('recipe'))
        for rec in sorted(recs):
            rec = rec.resolve()
            rel = copy_file(rec, '')
            before = rec.read_bytes()
            transformed = recipe_text(rec, before.decode('utf-8-sig').replace('\r\n', '\n'))
            (temp / rel).write_bytes((b'\xef\xbb\xbf' if before.startswith(b'\xef\xbb\xbf') else b'') +
                                    transformed.replace('\n', '\r\n' if b'\r\n' in before else '\n').encode())
            for p, outs in recipes:
                if p.resolve() == rec:
                    for wav, name, note in outs:
                        if wav.resolve() in wanted:
                            meta.setdefault('recipe_of', {}).setdefault(str(wav.resolve()),
                                {'recipe': str(rec), 'name': name, 'note': note,
                                 'spec': yaml.safe_dump(api.from_yaml(before.decode('utf-8-sig'))['samples'][name], sort_keys=False)})
        # Retained ratings for retired/missing candidates are annotations, not playback dependencies.
        def convert(path):
            src = (state.base_dir / path).resolve()
            return files.get(src, 'uncollected/' + digest(str(src).encode())[:12] + '-' + src.name)
        for rec in (meta.get('recipe_of') or {}).values():
            if rec.get('spec'):
                # A candidate's editable entry can differ from the recipe on disk.
                transformed = recipe_text(Path(rec['recipe']), 'samples:\n  candidate:\n' +
                                          ''.join('    ' + line + '\n' for line in rec['spec'].splitlines()))
                rec['spec'] = yaml.safe_dump(api.from_yaml(transformed)['samples']['candidate'], sort_keys=False)
        if meta.get('phrase'):
            ph = meta['phrase']
            changes, assets = [], {}
            for num, entry in api.from_yaml(ph['snapshot'])['samples'].items():
                if isinstance(entry, dict) and entry.get('file'):
                    rel = copy_file(state.base_dir / entry['file'], 'phrase-samples')
                    assets[rel] = digest((temp / rel).read_bytes())
                    changes.append((('samples', num, 'file'), rel))
            ph['snapshot'] = replace_values(ph['snapshot'], changes)
            ph['assets'] = assets
            if ph['base_hash'] == hashlib.sha1(text.encode()).hexdigest():
                ph['base_hash'] = hashlib.sha1(collected.encode()).hexdigest()
        meta = map_meta(meta, convert)
        if browser is not None:
            meta['project_settings'] = browser
        # Keep adjacent provenance/credit documents with the assets they describe.
        credits = {}
        for source, rel in list(files.items()):
            for name in ('ATTRIBUTION.md', 'PROVENANCE.md', 'LICENSE', 'LICENSE.md', 'LICENSE.txt', 'COPYING'):
                for folder in {source.parent, state.base_dir}:
                    credit = folder / name
                    if credit.is_file() and credit != source:
                        copied = copy_file(credit, 'credits')
                        if copied not in credits.setdefault(rel, []):
                            credits[rel].append(copied)
        song = temp / state.song_path.name
        song.write_bytes(state._encoded(collected))
        (temp / state.meta_path.name).write_bytes(json_bytes(meta))
        for name, data in notes.items():
            (temp / name).write_bytes(data)
        # Compilation only reads paths inside the temporary copy, never the original locations.
        api.compile_song(song)
        manifest = {'song': song.name, 'source_version': state.version(),
                    'files': {p.relative_to(temp).as_posix(): digest(p.read_bytes()) for p in sorted(temp.rglob('*')) if p.is_file()},
                    'asset_credits': credits,
                    'history': 'New copy starts fresh; source undo and checkpoints stay with the original.',
                    'sound_sources': 'Editable recipes and file inputs included. Named synth patches still require their synth/library.'}
        (temp / 'project.json').write_bytes(json_bytes(manifest))
        if state.song_path.read_bytes() != raw:
            raise ValueError('Song changed during collection; retry')
        if make_zip:
            fd, zname = tempfile.mkstemp(prefix='.vt-collect-', suffix='.zip', dir=destination.parent)
            os.close(fd)
            zip_temp = Path(zname)
            with zipfile.ZipFile(zip_temp, 'w', zipfile.ZIP_DEFLATED) as z:
                for file in sorted(temp.rglob('*')):
                    if file.is_file():
                        z.write(file, destination.name + '/' + file.relative_to(temp).as_posix())
        # rename on Windows refuses an existing target; exclusive ZIP creation does so on every platform.
        destination.mkdir()
        try:
            for file in temp.iterdir():
                file.rename(destination / file.name)
            if zip_temp:
                link_new(zip_temp, archive)  # publish a complete ZIP without replacing a concurrent destination
        except Exception:
            shutil.rmtree(destination)
            raise
        return {'path': str(destination / song.name), 'zip': str(archive) if make_zip else None,
                'files': len(manifest['files']), 'report': f'Collected {len(manifest["files"])} files. Original untouched. Copy starts a new history.'}
    finally:
        shutil.rmtree(temp)
        if zip_temp:
            zip_temp.unlink(missing_ok=True)
