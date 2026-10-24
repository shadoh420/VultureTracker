"""Local score collections and sequential conversion through the existing publishers."""
from pathlib import Path
import os
import re
import threading
import json

from .fileio import device_name

INPUTS = frozenset(('.yaml', '.yml', '.tg', '.ptb', '.tef', '.gtp', '.gp3', '.gp4', '.gp5', '.gpx', '.gp', '.mid', '.midi', '.it', '.xm', '.s3m', '.mod'))
OUTPUTS = ('yaml', 'tg', 'gp3', 'gp4', 'gp5', 'mid', 'it', 'tab', 'ly', 'musicxml', 'wav', 'mp3', 'ogg', 'flac', 'pdf', 'band')


def scan(folder, recursive=False):
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError('Choose a score folder')
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Choose an existing score folder')
    files, examined, truncated = [], 0, False
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs.sort(key=str.casefold)
        for name in sorted(names, key=str.casefold):
            examined += 1
            if examined > 10000 or len(files) >= 1000:
                truncated = True
                break
            path = Path(directory) / name
            if path.suffix.lower() not in INPUTS:
                continue
            try:
                stamp = path.stat()
                files.append(dict(path=str(path), name=str(path.relative_to(root)), format=path.suffix[1:].lower(), bytes=stamp.st_size))
            except OSError:
                continue
        if truncated or not recursive:
            break
    return dict(folder=str(root), files=files, truncated=truncated)


def options(body):
    paths = body.get('paths')
    if not isinstance(paths, list) or not 1 <= len(paths) <= 100 or not all(isinstance(p, str) and p.strip() for p in paths):
        raise ValueError('Select between 1 and 100 score files')
    paths = [str(Path(p).expanduser().resolve()) for p in paths]
    if len({os.path.normcase(p) for p in paths}) != len(paths):
        raise ValueError('Select each source file only once')
    destination = body.get('destination')
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError('Choose an output folder')
    fmt = body.get('format', 'yaml')
    if fmt not in OUTPUTS:
        raise ValueError('Choose a supported score conversion format')
    version = str(body.get('tg_version') or '2.0')
    if version not in ('2.0', '1.0', '1.1', '1.2', '1.3', '1.5'):
        raise ValueError('Choose a supported TG version')
    paper, notation = body.get('paper', 'a4'), body.get('notation', 'both')
    scale = body.get('scale', 65)
    if paper not in ('a4', 'letter') or notation not in ('both', 'staff', 'tab'):
        raise ValueError('Choose supported PDF paper and notation settings')
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not 40 <= scale <= 150:
        raise ValueError('PDF scale must be 40–150 percent')
    rate, depth = body.get('rate', 44100), body.get('depth', 16)
    if rate not in (22050, 44100, 48000, 88200, 96000) or depth not in (16, 24):
        raise ValueError('Choose a supported audio rate and depth')
    from .notation_export import _lily_settings
    lilypond = _lily_settings(body.get('lilypond')) if fmt == 'ly' else None
    from .midiimport import score_import_options
    midi_options = score_import_options(body.get('midi_options'))
    from .export import midi_export_settings
    if body.get('midi_export') not in (None,{}) and fmt != 'mid':
        raise ValueError('Native MIDI export settings require MIDI output')
    midi_export = midi_export_settings(body.get('midi_export')) if fmt == 'mid' else None
    from .gpimport import guitar_pro_encoding
    gp_encoding = guitar_pro_encoding(body.get('gp_encoding'))
    return dict(paths=paths, destination=str(Path(destination).expanduser().resolve()), format=fmt, tg_version=version,
                paper=paper, notation=notation, scale=scale, rate=rate, depth=depth,
                parts=bool(body.get('parts', True)), stems=bool(body.get('stems', True)), lilypond=lilypond,
                midi_options=midi_options,midi_export=midi_export,gp_encoding=gp_encoding)


def convert(body, notify=lambda item: None, cancel=None):
    """One fresh folder per source; keep successes and report each failure without touching inputs."""
    from . import gui, export, project
    settings = options(body)
    cancel = cancel or threading.Event()
    destination = Path(settings['destination'])
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    for source in settings['paths']:
        item = dict(source=source, status='working', files=[], warnings=[], error=None)
        results.append(item)
        if cancel.is_set():
            item['status'] = 'cancelled'
            notify(dict(item))
            continue
        notify(dict(item))
        state = None
        owned_folder = None
        try:
            src = Path(source)
            if not src.is_file() or src.suffix.lower() not in INPUTS:
                raise ValueError('Source is missing or its format is unsupported')
            stem = re.sub(r'[^\w.-]+', '_', src.stem)[:80] or 'score'
            if device_name(stem):
                stem = '_' + stem
            folder = destination / (stem + '-' + src.suffix[1:].lower())
            if folder.exists():
                raise ValueError(f'Output folder already exists: {folder}. Choose another destination; nothing was replaced.')
            fmt = settings['format']
            if src.suffix.lower() in ('.yaml', '.yml'):
                state = gui.State(src, headless=True)
                state._need_compiled()
                if fmt in ('yaml', 'band'):
                    project.collect(state, str(folder))
                    item['files'] = [str(folder / src.name)]
                else:
                    folder.mkdir()  # exclusive ownership; exporters never merge an earlier batch
                owned_folder = folder
            else:
                folder.mkdir()
                owned_folder = folder
                native, warnings = gui.import_song(src, folder / 'song.yaml', folder / 'samples', native_tab=True,midi_options=settings['midi_options'],gp_encoding=settings['gp_encoding'])
                item['warnings'] = list(warnings)
                item['files'] = [str(native)]
                state = gui.State(native, headless=True)
                state._need_compiled()
            formats = ('tg', 'gp5', 'mid', 'it', 'wav', 'pdf') if fmt == 'band' else (() if fmt == 'yaml' else (fmt,))
            failures = []
            item['deliveries'] = []
            for target in formats:
                if cancel.is_set():
                    raise ValueError('Delivery cancelled')
                delivery = dict(format=target, files=[], warnings=[], error=None)
                item['deliveries'].append(delivery)
                try:
                    if target == 'pdf':
                        from .score_pdf import write_pdf
                        view = state.score_view()
                        delivery['files'].append(write_pdf(view, folder/'score.pdf', settings, cancel))
                        if settings['parts']:
                            for index, track in enumerate(view['score']['tracks'], 1):
                                delivery['files'].append(write_pdf(view, folder/'parts'/f'{index:02d}.pdf', settings, cancel, track))
                        if view.get('raw_positions'):
                            delivery['warnings'].append('PDF includes authored score only; unadopted Pattern notes are omitted.')
                    else:
                        opts = dict(fmt=target, destination=str(folder), name='score', replace=False)
                        if target in ('wav', 'mp3', 'ogg', 'flac'):
                            opts['rate'] = settings['rate']
                            opts['depth'] = settings['depth'] if target in ('wav', 'flac') else 16
                            opts['stems'] = settings['stems']
                            opts['stem_mode'] = 'tracks'
                        if target == 'tg':
                            opts['tg_version'] = settings['tg_version']
                        if target in ('gp3','gp4','gp5'):
                            opts['gp_encoding'] = settings['gp_encoding']
                        if target == 'ly':
                            opts['lilypond'] = settings['lilypond']
                        if target == 'mid' and settings['midi_export'] is not None and (
                                state.mod.native_score or settings['midi_export'] != dict(transpose=0,strip=False)):
                            opts['midi_export'] = settings['midi_export']
                        job = export.prepare(state, opts)
                        job['cancel'] = cancel
                        export.run(job, gui._encode)
                        delivery['warnings'].extend(job['result']['warnings'])
                        if job['result']['status'] != 'done':
                            raise ValueError(job['result'].get('error') or 'Conversion cancelled')
                        delivery['files'].extend(job['result']['files'])
                except Exception as exc:
                    delivery['error'] = f'{type(exc).__name__}: {exc}'
                    failures.append(target.upper() + ': ' + delivery['error'])
                item['files'].extend(delivery['files'])
                item['warnings'].extend(target.upper() + ': ' + warning for warning in delivery['warnings'])
                notify(dict(item))
            if failures:
                raise ValueError('; '.join(failures))
            item['status'] = 'done'
        except Exception as exc:
            item['status'] = 'cancelled' if cancel.is_set() else 'failed'
            item['error'] = f'{type(exc).__name__}: {exc}'
        finally:
            if state is not None:
                state.close()
            if owned_folder is not None and settings['format'] in ('band', 'pdf', 'wav', 'mp3', 'ogg', 'flac'):
                try:
                    # Exclusive creation also protects an externally added report during a long render.
                    with (owned_folder/'delivery.json').open('x', encoding='utf-8', newline='\n') as report:
                        json.dump(dict(settings=settings, result=item), report, ensure_ascii=False, indent=2)
                        report.write('\n')
                except OSError as exc:
                    item['warnings'].append('Could not save delivery report: ' + str(exc))
            notify(dict(item))
    return results
