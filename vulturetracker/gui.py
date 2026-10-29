"""`vulturetracker gui song.yaml`: a one-page tryout app served on localhost from the stdlib HTTP server.

The page (gui.html) polls /api/state and posts actions; renders run on one worker thread and land as WAVs in
`<song dir>/.tryout/`. The tryout section is compiled once per candidate (memoised); mutes, solo and the mixer's
faders (channel volume and pan, mix volume, sample gain) are patched into that module's header before each render, so
re-picking a candidate is instant and a fader move costs one render. The instrument panel (the slot's instrument: volume
envelope, filter and its sweep, random volume) joins the unwritten mix and is applied when the section is compiled.
Ratings, notes, the candidate list, mutes and the unwritten mix live in `<song>.tryout.json` beside the song.
Listening notes (a tag dropped at the playhead, the channels sounding there, the listener's words) live in
`<song>.notes.json` and are rendered as `<song>.notes.md`, a report for a collaborator who cannot listen."""
import copy
import datetime
import difflib
import functools
import glob
import hashlib
import importlib
import itertools
import json
import logging
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
import webbrowser
from bisect import bisect_right
from pathlib import Path
from fractions import Fraction

import yaml

from . import __version__, agent, api, plugins, server
from .fileio import atomic_write as _atomic, lock_file, protect_outputs, save_beside, unlock_file, user_dir, wav_bytes
from .model import Cell
from .notation import format_cell, format_note, parse_cell
from .itwriter import write_it
from .measure import (DELTA_DB, DELTA_STOPS, RATE, SPEC_DB, SPEC_STOPS, _colour_png, _peak, channel_levels, distance,
                      match_level, measure, mix_numbers, patch_it, png_rgb, reference_align, reference_compare, reference_wav,
                      scale_pcm)
from .sample_edit import (SAMPLE_ACTIONS, VOICE_GROUPS, VOICE_RANGE, entry_loops, paint_args, process_wav, voice_entry,
                          voice_of, wav_array, wave_peaks)
from .history import LABEL, SIDE_SCHEMA, History, digest, json_bytes, newer, pack_step, unpack_step, HISTORY_BYTES
from .project import file_updates, replace_values, resolve_meta, relative_meta
from .arrangement import section_renamed, sections_text, occurrence_map, reorder
from .openmpt import LoadedModule, library_version
from .song import SongError, it_text, load_song_text
from .wavload import SOUND_FILES, read_wav, run_ffmpeg, to_wav

HTML = Path(__file__).with_name("gui.html")
WEB = HTML.with_name("web")  # the live engine: libopenmpt 0.8.9 compiled to WebAssembly (official build) and its AudioWorklet
# the checkout (for the demo list); a frozen exe: its own folder when samples/ is there (the release zip), else one
# level up (dist/ in a checkout)
ROOT = ((lambda d: d if (d / "samples").is_dir() else d.parent)(Path(sys.executable).resolve().parent)
        if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent)
RECENT = user_dir() / "recent.json"
REC_SETTINGS = RECENT.with_name("record.json")  # the RECORD tab's ASIO choice, read before sounddevice loads
CACHE_BYTES = 2 << 30     # the most a song's render cache (.tryout) keeps, besides its newest WAVs by count
# render workers: the tryout's renders (the song, each candidate), meters, builds and stems share one queue by priority.
# VT_WORKERS=3 renders three at once: measured in the cloud (4 cores, tools/bench.py --tryout 6) 15-20 % sooner for the
# song and six candidates, byte-identical, but an edit made meanwhile reached the live engine 2-4x later (the workers
# hold the GIL between libopenmpt's calls), so one worker stays the default
WORKERS = max(1, int(os.environ.get("VT_WORKERS") or 1))
PROFILE = RECENT.parent / "webview"  # the window's WebView2 profile: what the page stores at its address (server.PORT)
OLD_RECENT = RECENT.parent.with_name("TrackerForge") / "recent.json"  # the app's previous name
HOME_RECENT = Path.home() / "VultureTracker" / "recent.json"  # where Linux and macOS kept it before 1.0
LOG = RECENT.parent / "vulturetracker.log"
_log = logging.getLogger("vulturetracker")  # without start_log (the command line, the tests) errors go to stderr
LOGGING = False


def start_log():
    """The app's log, for the exe (a windowed program has no console): unexpected errors with their tracebacks, after a
    line naming this version, libopenmpt's and the system. At most two files of 256 KB (vulturetracker.log and .log.1)."""
    global LOGGING
    import logging.handlers
    import platform
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(LOG, maxBytes=256 * 1024, backupCount=1, encoding="utf-8")
    except OSError:
        return
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _log.addHandler(h)
    if sys.stderr:  # run from a console: there too
        _log.addHandler(logging.StreamHandler())
    _log.setLevel(logging.INFO)
    _log.info("VultureTracker %s started: libopenmpt %s, Python %s, %s", __version__, library_version(),
              platform.python_version(), platform.platform())
    sys.excepthook = lambda *exc: _log.error("Unexpected error", exc_info=exc)
    threading.excepthook = lambda a: a.exc_type is SystemExit or _log.error(
        "Unexpected error in %s", a.thread.name if a.thread else "a thread", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    LOGGING = True


def logged(error):
    """An error for the page, naming the log when the app keeps one."""
    return f"{error} (details in {LOG})" if LOGGING else error


def _atomic_text(path, text):
    """Text written as write_text writes it (the platform's line endings), through _atomic."""
    _atomic(path, text.replace("\n", os.linesep).encode("utf-8"))


def _read_json(path, default, notices, move=True):
    """A JSON file the app keeps beside the song, or `default` when there is none. One that does not parse (a write cut
    short before writes were atomic, or a hand edit) is moved aside to `<name>.corrupt` (unless not `move`: another app
    has the song open) and `default` is used, with a notice for the page, so the song still opens."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        if not move:
            notices.append(f"{path.name} could not be read ({e}); left as it is")
            return default
        bad = path.with_name(path.name + ".corrupt")
        os.replace(path, bad)
        notices.append(f"{path.name} could not be read ({e}); it was moved to {bad.name} and the app started it afresh")
        return default


def recent_songs():
    for f in (RECENT, OLD_RECENT, HOME_RECENT):
        try:
            return [p for p in json.loads(f.read_text(encoding="utf-8")) if Path(p).exists()]
        except (OSError, ValueError):
            continue
    return []


def remember_song(path):
    RECENT.parent.mkdir(parents=True, exist_ok=True)
    lst = [str(path)] + [p for p in recent_songs() if p != str(path)]
    _atomic_text(RECENT, json.dumps(lst[:12], indent=1))


def demo_songs():
    # songs only (recipes like drums.yaml have no orders)
    return sorted(str(p) for p in ROOT.glob("demo*/*.yaml")
                  if p.is_file() and re.search(r"^orders:", p.read_text(encoding="utf-8", errors="replace"), re.M))


def create_song(path, channels=8, sample=None, template=None, bars=4):
    """A new song file at `path` (refused when it exists), laid out the way the app edits songs: a block module with one
    channel entry per line, one sample slot (`sample`, a WAV, or a one-second C-5 sine written beside the song as
    <stem>_tone.wav) played by instrument 1, one empty 64-row pattern, the order list on one line. Written with LF endings."""
    path = Path(path).resolve()
    if path.suffix.lower() not in (".yaml", ".yml"):
        path = path.with_suffix(".yaml")
    if path.exists():
        raise ValueError(f"{path} exists already: open it, or pick another name")
    native = None
    if template is not None:
        from .tablature import new_score_song
        native = new_score_song(re.sub(r"[^ -~]", "", path.stem)[:25] or 'Untitled', 'placeholder.wav', template, bars)
    path.parent.mkdir(parents=True, exist_ok=True)
    if sample:
        wav = Path(sample).resolve()
        if not wav.exists():
            raise ValueError(f"no such WAV: {wav}")
    else:
        from .wavload import write_wav
        for k in itertools.count(1):
            wav = path.with_name(path.stem + ('_tone' if k == 1 else f'_tone-{k}') + '.wav')
            try:
                with wav.open('xb'):
                    pass
                break
            except FileExistsError:
                continue
        n = RATE
        write_wav(wav, RATE, [[round(12000 * math.sin(2 * math.pi * 261.6256 * i / RATE) * min(1, (n - i) / 2000)) for i in range(n)]], root_note=60)
    try:
        rel = os.path.relpath(wav, path.parent).replace(os.sep, "/")
    except ValueError:  # another drive
        rel = wav.as_posix()
    title = re.sub(r"[^ -~]", "", path.stem)[:25] or "Untitled"
    name = re.sub(r"[^ -~]", "", wav.stem)[:25] or "sample"
    if native is not None:
        native['samples'][1].update(file=rel, name=name)
        api.compile_song(native, path.parent)
        _atomic(path, (api.written_by_line() + api.to_yaml(native)).encode('utf-8'), replace=False)
        return path
    q = State._yname
    chans = "".join(f"    - {{name: Ch {i + 1}}}\n" for i in range(max(1, min(64, int(channels)))))
    _atomic(path, (f"# {title}: a song made in VultureTracker (the format: SONG_FORMAT.md)\n{api.written_by_line()}module:\n  title: {q(title)}\n"
                      f"  tempo: 125\n  speed: 6\n  global_volume: 128\n  mix_volume: 48\n  sample_rate: 44100\n  channels:\n{chans}"
                      f"samples:\n  1: {{file: {q(rel)}, name: {q(name)}}}\ninstruments:\n  1: {{name: {q(name)}, sample: 1}}\n"
                      f"patterns:\n  p00:\n    rows: 64\n    data: |\norders: [p00]\n").encode("utf-8"), replace=False)
    return path


@functools.lru_cache(maxsize=1)
def effect_help():
    """The song format's volume-column, effect and S-subcommand tables (SONG_FORMAT.md, beside the checkout or bundled
    with the exe) as {"v": {letter: text}, "e": {letter: text}, "s": {"S3": text, "S73": text, ...}}: the Pattern tab's
    effect help."""
    out = {"v": {}, "e": {}, "s": {}}
    src = next((p for p in (ROOT / "SONG_FORMAT.md", HTML.with_name("SONG_FORMAT.md")) if p.exists()), None)
    for line in (src.read_text(encoding="utf-8").splitlines() if src else []):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        codes = re.findall(r"`([^`]+)`", cells[0]) if len(cells) >= 2 and cells[0].startswith("`") else []
        if not codes:
            continue
        if re.fullmatch(r"[a-z]NN", codes[0]) and len(cells) >= 3:
            out["v"][codes[0][0]] = f"{cells[2]} ({cells[1]})"
        elif re.fullmatch(r"[A-Z]x[xy]", codes[0]) and len(cells) >= 3:
            out["e"][codes[0][0]] = f"{cells[1]}: {cells[2]}"
        elif re.fullmatch(r"S[0-9A-F][0-9A-Fx]", codes[0]):
            for c in codes:
                out["s"][c[:-1] if c.endswith("x") else c] = cells[1]
    return out


def import_beside(src, *, native_tab=False, midi_options=None, gp_encoding=None):
    """A module (.it, .xm, .s3m, .mod), a Guitar Pro tab (.gp3, .gp4, .gp5: gpimport) or a MIDI file (.mid, .midi:
    midiimport; both with placeholder sounds) imported as
    <stem>.yaml beside it with its samples in <stem>_samples/ (numbered <stem>-2 and so on when either exists: nothing
    is replaced). Returns (song path, warnings)."""
    src = Path(src).resolve()
    if not src.is_file():
        raise ValueError(f"no such file: {src}")
    for k in itertools.count(1):
        stem = src.stem + ("" if k == 1 else f"-{k}")
        out, sdir = src.with_name(stem + ".yaml"), src.with_name(stem + "_samples")
        if not out.exists() and not sdir.exists():
            break
    return import_song(src, out, sdir, native_tab=native_tab, midi_options=midi_options,gp_encoding=gp_encoding)


def import_song(src, out, sdir, *, native_tab=False, midi_options=None, gp_encoding=None):
    """Import through the same readers to explicit fresh song/sample destinations."""
    from .itreader import import_it
    src, out, sdir = Path(src).resolve(), Path(out), Path(sdir)
    if not src.is_file():
        raise ValueError(f"no such file: {src}")
    for destination in (out, sdir):
        if destination.exists() or destination.is_symlink():
            raise ValueError(f'import needs a fresh destination: {destination}')
    if src.suffix.lower() == '.tg':
        from .tgimport import import_tg
        return out, import_tg(src, out, sdir)[1]
    if src.suffix.lower() == '.ptb':
        from .ptb import import_ptb
        return out, import_ptb(src, out, sdir)[1]
    if src.suffix.lower() == '.tef':
        from .tef import import_tef
        return out, import_tef(src, out, sdir)[1]
    if src.suffix.lower() in GP_SUFFIXES:
        from .gpimport import import_gp
        return out, import_gp(src, out, sdir, native=native_tab,encoding=gp_encoding)[1]
    if src.suffix.lower() in MIDI_SUFFIXES:
        from .midiimport import import_midi, import_midi_score, score_import_options
        if native_tab:
            return out, import_midi_score(src,out,sdir,**score_import_options(midi_options))[1]
        if midi_options is not None:
            raise ValueError('MIDI score options require native score import')
        return out, import_midi(src,out,sdir)[1]
    return out, import_it(src, out, sdir)[1]


GP_SUFFIXES = (".gtp", ".gp3", ".gp4", ".gp5", ".gpx", ".gp")   # .gtp: GP1/GP2 (gplegacy); .gpx/.gp: GP6/GP7 (gpx)
MIDI_SUFFIXES = (".mid", ".midi")


# ---------------------------------------------------------------- song facts

def song_facts(text, base_dir, name):
    """Compile once for the overview: channels, order timing and which samples each order/channel plays."""
    return facts_of(*load_for_state(text, base_dir, name))


def load_for_state(text, base_dir=".", name="<song>"):
    """State validates exact scores at a reference rate; each player prepares its actual mixer rate separately."""
    loaded = load_song_text(text, base_dir, name, native_score_rate=44100)
    mod = loaded[0]
    if mod.native_score is not None:
        song = api.from_yaml(text)
        kind = 'instruments' if mod.instruments is not None else 'samples'
        missing = voice_references(song, mod) - {int(n) for n in song.get(kind, {})}
        if missing:
            raise SongError([f'{name}: score references missing {kind}: {sorted(missing)}'])
    return loaded


def score_notes(song):
    """Authored notes, including unused patterns; never infer their presence from residual tracker cells."""
    from .tablature import _resolved_notes
    score = song.get('score') or {}
    for name, pattern in score.get('patterns', {}).items():
        for beat in pattern['beats']:
            track = score['tracks'][beat['track']]
            for note in _resolved_notes(score, beat):
                yield name, beat, track, note


def score_context(song, name):
    """Score content protected by a pattern mark, including its tracks and occurrence notation."""
    score = song.get('score') or {}
    pattern = score.get('patterns', {}).get(name)
    tracks = {b['track']: score['tracks'][b['track']] for b in (pattern or {}).get('beats', [])}
    ids, orders = score.get('order_ids', []), list(map(str, song.get('orders', [])))
    notation = []
    for collection in ('measures', 'ties'):
        for item in score.get(collection, []):
            a, b = (ids.index(item[side]['occurrence']) for side in ('from', 'to'))
            uses = range(a, b + 1) if collection == 'measures' else (a, b)
            if any(orders[i] == name for i in uses):
                notation.append((collection, item))
    return pattern, tracks, notation


def score_channel_content(song, channel):
    """Semantic channel identity for approval/restore guards; includes unused authored patterns."""
    content = []
    for name, beat, track, note in score_notes(song):
        if note['channel'] == channel:
            content.append((name, {k: v for k, v in beat.items() if k != 'notes'},
                            {k: v for k, v in track.items() if k != 'channels'},
                            {k: v for k, v in note.items() if k != 'channel'}))
    score = song.get('score') or {}
    note_ids = {(name, n['id']) for name, _, _, n in score_notes(song) if n['channel'] == channel}
    orders = dict(zip(score.get('order_ids', []), map(str, song.get('orders', []))))
    ties = [tie for tie in score.get('ties', []) if any(
        (orders.get(tie[side]['occurrence']), tie[side]['note']) in note_ids for side in ('from', 'to'))]
    return content, ties


def voice_references(song, mod, *, played=False, channels=None):
    """Voice slots referenced by raw cells or score notes, plus resolved played instrument memory."""
    names = {mod.patterns[o].name for o in mod.orders if o < 254} if played else None
    allowed = lambda ch: channels is None or ch in channels
    refs = {c.instrument for p in mod.patterns if names is None or p.name in names
            for row in p.rows for ch, c in enumerate(row) if c.instrument and allowed(ch)}
    refs.update(n.get('instrument', track['instrument']) for name, _, track, n in score_notes(song)
                if (names is None or name in names) and allowed(n['channel']))
    if mod.native_score:
        refs.update(e['instrument'] for e in mod.native_score['plan']['events']
                    if e['type'] == 'note_on' and allowed(e['ch']))
    return refs - {0}


def native_actions(mod):
    """Raw and score parent-channel actions on one exact timeline, resolving their shared instrument memory."""
    mod = mod.playback_backing()
    plan, actions = mod.native_score['plan'], []
    step = Fraction(*plan['row_step'])
    for order, occurrence in enumerate(plan['occurrences']):
        for row, cells in enumerate(mod.patterns[mod.orders[order]].rows):
            at = Fraction(*occurrence['at']) + row * step
            for ch, cell in enumerate(cells):
                if cell.instrument or cell.note is not None:
                    actions.append((at, 1, ch, {'order': order, 'cell': cell}))
    starts = [Fraction(*o['at']) for o in plan['occurrences']]
    for event in plan['events']:
        if event['type'] not in ('note_on', 'note_off'):
            continue  # Pitch controls do not retrigger parent-note activity or instrument memory.
        at = Fraction(*event['at'])
        order = max(0, min(len(starts) - 1, bisect_right(starts, at) - 1))
        actions.append((at, 0 if event['type'] == 'note_off' else 2, event['ch'],
                        {**event, 'order': order}))
    memory, result = {}, []
    for at, kind, ch, item in sorted(actions, key=lambda a: a[:3]):
        if kind == 1:
            cell = item['cell']
            memory[ch] = cell.instrument or memory.get(ch, 0)
            if cell.note is None:
                continue
            item = {'type': 'note_on' if cell.note < 120 else 'note_off', 'pitch': cell.note,
                    'instrument': memory[ch], 'order': item['order'], 'id': None}
        elif kind == 2:
            memory[ch] = item['instrument']
        result.append({**item, 'at': at, 'ch': ch})
    return result


def native_sounding_table(mod):
    """Parent-note activity at exact row boundaries; release/NNA tails remain unmeasured, as in the legacy estimate."""
    mod = mod.playback_backing()
    from .tablature import TempoClock
    plan = mod.native_score['plan']
    clock = TempoClock(plan['tempo'], plan.get('tempos'))
    actions = iter(native_actions(mod))
    pending = next(actions, None)
    current, table = {}, []
    step = Fraction(*mod.native_score['plan']['row_step'])
    for order, occurrence in enumerate(mod.native_score['plan']['occurrences']):
        rows = []
        for row in range(len(mod.patterns[mod.orders[order]].rows)):
            at = Fraction(*occurrence['at']) + row * step
            while pending is not None and pending['at'] <= at:
                ch = pending['ch']
                if pending['type'] == 'note_off':
                    if pending.get('id') is None:
                        for key, event in list(current.items()):
                            if key[0] == ch and not (event.get('hold') or 'context' in event):
                                current.pop(key)
                    else:
                        current.pop((ch, pending['id']), None)
                else:
                    for key, event in list(current.items()):
                        if key[0] == ch and not (event.get('hold') or 'context' in event):
                            current.pop(key)
                    current[ch, pending.get('id')] = pending
                pending = next(actions, None)
            sounding = []
            for (ch, _), event in current.items():
                ins, pitch = event['instrument'], event['pitch']
                played, smp = ((pitch, ins) if mod.instruments is None else
                               mod.instruments[ins - 1].keymap[pitch] if 0 < ins <= len(mod.instruments) else (pitch, 0))
                sample = mod.samples[smp - 1] if 0 < smp <= len(mod.samples) else None
                age = at - event['at']
                if sample is not None and not sample.loop and sample.c5_speed and (
                        float(clock.seconds_at(at) - clock.seconds_at(event['at'])) >= sample.length / sample.c5_speed / 2 ** ((played - 60) / 12)):
                    continue
                sounding.append({'ch': ch, 'name': mod.channels[ch].name or f'Ch {ch + 1}',
                                 'sample': smp or None, 'note': format_note(pitch), 'order': event['order'],
                                 'loop': bool(sample and sample.loop), 'ago': float(age / step),
                                 'basis': 'parent-note activity; release tails unmeasured'})
            rows.append(sounding)
        table.append(rows)
    return table


DMO = plugins.describe()  # the rack's effects and their parameters


def _key_report(mod):
    if mod.native_score is not None:
        return None  # A residual-only harmonic report would omit the score.
    try:
        from .compose import key_report
        return key_report(mod)
    except (ImportError, ValueError):
        return None
CHAT = agent.Chat()       # the chat panel's conversation (one per app)


def facts_of(mod, warnings, it=None):
    """`it`: the module's .it bytes, when the caller wrote them already."""
    rows_per_bar = mod.row_highlight[1] or 16
    orders = []
    use = []  # per order: per channel: sorted sample numbers triggered
    # order timing comes from libopenmpt, so speed, tempo, break and jump effects count; an order that playback
    # never reaches lasts 0 s
    native = mod.native_score
    playback_orders = []
    repeated = bool(native and native['plan'].get('repeat_projection'))
    if native:
        from .tablature import TempoClock
        plan = native['plan']
        clock = TempoClock(plan['tempo'], plan.get('tempos'))
        duration = float(Fraction(*plan['duration']['seconds']))
        source_occurrences = native['view']['occurrences']
        source_clock = TempoClock(mod.tempo, native['view'].get('tempos')) if repeated else clock
        starts = {i: float(source_clock.seconds_at(Fraction(*o['at'])))
                  for i, o in enumerate(source_occurrences)}
        if repeated:
            backing = mod.playback_backing()
            step = Fraction(*plan['row_step'])
            for i, occurrence in enumerate(plan['occurrences']):
                origin, length = Fraction(*occurrence['at']), Fraction(*occurrence['duration'])
                start = clock.seconds_at(origin)
                rows = len(backing.patterns[backing.orders[i]].rows)
                playback_orders.append({**occurrence, 'order': i, 'index': backing.orders[i], 'rows': rows,
                    'start': float(start), 'seconds': float(clock.seconds_at(origin + length) - start),
                    'row_times': [float(clock.seconds_at(origin + row * step) - start) for row in range(rows + 1)]})
    else:
        with LoadedModule(it or write_it(mod)) as lm:
            duration = lm.duration()
            starts = {i: lm.order_start(i) for i, o in enumerate(mod.orders) if o < 254}
            for i, t in starts.items():
                if t <= 0.0 and i != min(starts):
                    starts[i] = duration
                elif t >= duration:
                    rows = len(mod.patterns[mod.orders[i]].rows)
                    starts[i] = next((v for v in (lm.order_start(i, r) for r in range(1, rows)) if v < duration), duration)
    points = sorted({*starts.values(), duration})
    native_onsets = native_actions(mod) if native else []
    resolved_positions = {p['id']: p for p in native['plan']['positions']} if native else {}
    for i, o in enumerate(mod.orders):
        if o >= 254:
            continue
        pat = mod.patterns[o]
        per_ch = [set() for _ in mod.channels]
        for row in pat.rows:
            for ch, cell in enumerate(row):
                if cell.note is None or cell.note >= 120 or not cell.instrument:
                    continue
                if mod.instruments is None:
                    per_ch[ch].add(cell.instrument)
                elif cell.instrument <= len(mod.instruments):
                    smp = mod.instruments[cell.instrument - 1].keymap[cell.note][1]
                    if smp:
                        per_ch[ch].add(smp)
        if native:
            for event in native_onsets:
                event_order = plan['occurrences'][event['order']].get('source_order', event['order'])
                if event['type'] != 'note_on' or event_order != i:
                    continue
                ins, pitch = event['instrument'], event['pitch']
                smp = (ins if mod.instruments is None else mod.instruments[ins - 1].keymap[pitch][1]
                       if 0 < ins <= len(mod.instruments) else 0)
                if smp:
                    per_ch[event['ch']].add(smp)
            occurrence = source_occurrences[i]['id']
            for position in native['view']['positions']:
                if position['kind'] != 'note' or position['occurrence'] != occurrence:
                    continue
                resolved = resolved_positions.get(position['id'])
                if resolved is None:
                    continue  # Unplayed endings have no performed instrument state.
                ins, pitch = resolved['instrument'], position['pitch']
                smp = ins if mod.instruments is None else mod.instruments[ins - 1].keymap[pitch][1]
                if smp:
                    per_ch[position['ch']].add(smp)
        start = starts[i]
        secs = next((p for p in points if p > start), start) - start
        orders.append({"pattern": pat.name, "index": o, "order": i, "rows": len(pat.rows), "bars": len(pat.rows) / rows_per_bar, "start": start, "seconds": secs})
        if native:
            orders[-1]['occurrence'] = source_occurrences[i]['id']
            if repeated:
                orders[-1]['authored_timing'] = True
                orders[-1]['start'] = orders[-1]['seconds'] = None
                from .tablature import resolve_source_region
                try:
                    a, r0, b, r1 = resolve_source_region(plan, (i, 0, i, len(pat.rows) - 1))
                    orders[-1]['playback_loop'] = {'from': [a, r0], 'to': [b, r1]}
                except ValueError as exc:
                    orders[-1]['playback_loop_error'] = str(exc)
            elif plan.get('tempos'):
                origin = Fraction(*source_occurrences[i]['at'])
                step = Fraction(*plan['row_step'])
                origin_seconds = clock.seconds_at(origin)
                orders[-1]['row_times'] = [float(clock.seconds_at(origin + row * step) - origin_seconds)
                                           for row in range(len(pat.rows) + 1)]
        use.append([sorted(s) for s in per_ch])
    return {
        "title": mod.title, "tempo": mod.tempo, "speed": mod.speed,
        "score": native is not None or mod.score_projection is not None,
        "native_score": native is not None,
        "bpm": mod.tempo if native is not None or mod.score_projection is not None else round(mod.tempo * 24 / mod.speed / (mod.row_highlight[0] or 4), 2),
        "highlight": [mod.row_highlight[0] or 4, rows_per_bar],
        "channels": [c.name or f"Ch {i + 1}" for i, c in enumerate(mod.channels)],
        "pan": [c.pan for c in mod.channels], "volume": [c.volume for c in mod.channels], "mix_volume": mod.mix_volume,
        "channel_plugins": [c.plugin for c in mod.channels], "plugins": plugins.to_song(mod.plugins),
        "channel_colors": [c.color for c in mod.channels],
        "macros": {f"SF{n:X}": t for n, t in sorted(mod.macros.items())},
        "key": mod.key, "key_report": _key_report(mod),
        "patterns": len(mod.patterns), "duration": duration, "orders": orders, "use": use,
        **({'playback_orders': playback_orders} if repeated else {}),
        "instruments": [i.name for i in mod.instruments] if mod.instruments else [],
        "samples": [{"num": i + 1, "name": s.name, "c5_speed": s.c5_speed, "length": s.length / s.c5_speed if s.c5_speed else 0,
                     "loop": s.loop is not None, "bits": s.bits} for i, s in enumerate(mod.samples)],
        "warnings": warnings,
    }


# ---------------------------------------------------------------- listening notes

def sounding_table(mod, facts):
    """Per order of `facts` (the playable orders, in order) and per row of its pattern: the channels sounding there. A
    forward pass carries each channel's last note (the sample through the instrument's keymap, the note, the order and row
    it started at, whether the sample loops); a note-off/cut/fade drops it, and a one-shot sample drops out once its
    length has played at the note's rate, at that order's row rate. A note without an instrument keeps the channel's last instrument (a slide
    target, the tracker convention). Entry: ch, name, sample, note, order, loop, ago (rows since it started)."""
    if mod.native_score is not None:
        return native_sounding_table(mod)
    secs = [s.length / s.c5_speed if s.c5_speed else 0 for s in mod.samples]
    state, last_ins = [None] * len(mod.channels), [0] * len(mod.channels)
    table, abs_row = [], 0
    for oi, mo in enumerate(k for k, o in enumerate(mod.orders) if o < 254):
        pat = mod.patterns[mod.orders[mo]]
        o = facts["orders"][oi] if oi < len(facts["orders"]) else None
        row_s = o["seconds"] / len(pat.rows) if o and pat.rows else 0
        rows = []
        for r, row in enumerate(pat.rows):
            for ch, c in enumerate(row):
                last_ins[ch] = c.instrument or last_ins[ch]
                if c.note is None:
                    continue
                if c.note >= 120:  # note off / cut / fade
                    state[ch] = None
                    continue
                ins = last_ins[ch] = c.instrument or last_ins[ch]
                smp, played = ins, c.note
                if mod.instruments is not None:
                    played, smp = mod.instruments[ins - 1].keymap[c.note] if 0 < ins <= len(mod.instruments) else (c.note, 0)
                ok = 0 < smp <= len(mod.samples)
                state[ch] = {"ch": ch, "name": mod.channels[ch].name or f"Ch {ch + 1}", "sample": smp if ok else None, "note": format_note(c.note),
                             "order": oi, "loop": ok and mod.samples[smp - 1].loop is not None, "abs": abs_row + r,
                            "secs": secs[smp - 1] / 2 ** ((played - 60) / 12) if ok else None}
            out = []
            for s in state:
                if s is None:
                    continue
                ago = abs_row + r - s["abs"]
                if s["loop"] or s["secs"] is None or ago * row_s < s["secs"]:
                    out.append({k: v for k, v in s.items() if k not in ("abs", "secs")} | {"ago": ago})
            rows.append(out)
        table.append(rows)
        abs_row += len(pat.rows)
    return table


MATCH_PAD = 12  # dB under the matched level that SAMPLE ALONE plays at with MATCH LEVEL on (State.raw_file)


def _stamp(f):
    """A file's path, modification time and size as text (render cache keys)."""
    try:
        st = Path(f).stat()
        return f"{f}={st.st_mtime}:{st.st_size}"
    except OSError:
        return f"{f}=missing"


def _wav_bytes(y, rate):
    """Float channels x frames (full scale 1.0) as the bytes of a 16-bit WAV file."""
    import io
    import numpy as np
    pcm = np.clip(np.round(np.asarray(y).T * 32767), -32768, 32767).astype("<i2")
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())
    return b.getvalue()


def _write_pcm(path, pcm):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(pcm)


# export formats encoded by ffmpeg: MP3 192 kbit/s (LAME), Ogg Vorbis at quality 6 (about 192 kbit/s; Ogg loops gaplessly,
# what a game engine wants), FLAC (lossless); WAV is written directly
ENCODE = {"mp3": ["-c:a", "libmp3lame", "-b:a", "192k"], "ogg": ["-c:a", "libvorbis", "-q:a", "6"], "flac": ["-c:a", "flac"]}


def ffmpeg_exe():
    """ffmpeg for the encoded exports: an ffmpeg.exe beside the frozen exe (tools/build_exe.py puts one in dist/), else
    imageio-ffmpeg's own binary, else one on PATH. imageio_ffmpeg is imported by name at run time so PyInstaller's hook for
    it does not also pack its 88 MB binary into the exe, which would be unpacked to %TEMP% on every launch."""
    beside = Path(sys.executable).with_name("ffmpeg.exe")
    if getattr(sys, "frozen", False) and beside.exists():
        return str(beside)
    try:
        exe = importlib.import_module("imageio_ffmpeg").get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        exe = shutil.which("ffmpeg")
    if not exe:
        raise OSError("MP3/OGG/FLAC export, and FLAC, AIFF, OGG and MP3 samples, need ffmpeg: ffmpeg.exe beside "
                      "vulturetracker.exe, pip install imageio-ffmpeg, or ffmpeg on PATH")
    return exe


def _encode(path, pcm, fmt, loop=None, rate=RATE, depth=16, bitrate=None, quality=None):
    """Interleaved stereo PCM (int16, or float32 at `depth` 24) at `rate` to `fmt` (a key of ENCODE) through ffmpeg (no
    console window on Windows): MP3 at `bitrate` kbit/s, OGG at Vorbis `quality`, FLAC at 16 or 24 bits; `loop` =
    (start, end_exclusive) frames as the LOOPSTART and LOOPLENGTH tags game engines read from OGG and FLAC."""
    tags = ["-metadata", f"LOOPSTART={loop[0]}", "-metadata", f"LOOPLENGTH={loop[1] - loop[0]}"] if loop else []
    args = list(ENCODE[fmt])
    if fmt == "mp3" and bitrate:
        args[-1] = f"{int(bitrate)}k"
    if fmt == "ogg" and quality is not None:
        args[-1] = f"{float(quality):g}"
    if fmt == "flac" and depth == 24:
        args += ["-sample_fmt", "s32", "-bits_per_raw_sample", "24"]
    r = run_ffmpeg([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "s16le" if depth == 16 else "f32le", "-ar", str(rate),
                    "-ac", "2", "-i", "-", *args, *tags, str(path)], input=pcm)  # -nostdin leaves "-i -" reading the PCM
    if r.returncode:
        raise OSError(f"ffmpeg failed: {r.stderr.decode(errors='replace').strip()[-400:]}")


# ---------------------------------------------------------------- state


class State:
    READ_ONLY = ("{name} is open in another VultureTracker window or being changed by a command-line tool, so it opened "
                 "read-only: it plays, but edits, checkpoints and tryout settings are not saved. Close the other (or let "
                 "the command finish), then open the song again to edit it.")
    NEWER = ("{names} beside {name} {were} written by a newer VultureTracker, so the song opened read-only: it plays, but "
             "nothing is saved, so that version's files are not written over. Open the song in that version, or update "
             "this one (https://github.com/shadoh420/VultureTracker/releases).")

    def __init__(self, song_path, headless=False, passive=False):
        """`headless` (the command line): no workers, no .tryout cache, no lock, notes left where they are. `passive`:
        another process has the song open; the files beside it are read as they are (an interrupted save's journal and a
        file that does not parse are its to reconcile). An app that cannot take the song's lock opens it read-only."""
        self.song_path = Path(song_path).resolve()
        self._app_lock = not headless and server.take_app_lock(self.song_path)  # the command line's tools see the song is open here
        self.read_only = None if headless or self._app_lock else self.READ_ONLY.format(name=self.song_path.name)
        try:
            self._open(headless, passive or bool(self.read_only))
        except BaseException:
            self.release_lock()
            raise

    def _open(self, headless, passive):
        self.base_dir = self.song_path.parent
        self.headless = headless
        self.cache_dir = self.base_dir / ".tryout"
        self.meta_path = self.song_path.with_name(self.song_path.stem + ".tryout.json")
        self.meta = {"slot": 1, "orders": None, "candidates": {}, "ratings": {}, "muted": [], "solo": None, "mix": {}}
        self.closed = False
        self.notices = []     # what the page should tell once: a meta or notes file that could not be read
        if self.read_only:
            self.notices.append(self.read_only)
        self.history_store = History(self.song_path, self.notices, passive)
        self.checkpoints = {}
        self._history_ready = False
        self._asset_hashes = {}
        meta = _read_json(self.meta_path, {}, self.notices, move=not passive)
        self.notes_path = self.song_path.with_name(self.song_path.stem + ".notes.json")
        notes = _read_json(self.notes_path, [], self.notices, move=not passive)
        saved = self.history_store.load()
        late = [p.name for p, v in ((self.meta_path, meta), (self.notes_path, notes)) if newer(v)]
        late += [self.history_store.path.name] if self.history_store.newer else []
        if late:  # read nothing from them, write nothing over them
            self.read_only = self.NEWER.format(names=" and ".join(late), name=self.song_path.name, were="were" if len(late) > 1 else "was")
            self.notices.append(self.read_only)
            meta = notes = saved = None
        self.meta.update(resolve_meta(meta, self.base_dir) if isinstance(meta, dict) else {})
        notes = notes.get("notes") if isinstance(notes, dict) else notes  # a list: notes from before 1.0
        self.notes = notes if isinstance(notes, list) else []
        self.lock = threading.RLock()
        self.jobs = queue.PriorityQueue()  # (priority, sequence, job): what is playing first, then the song, the rest, meters last
        self._seq = itertools.count()
        self.want = self.meta.get("selected_candidate")  # the candidate the page is listening to (None: the song itself), rendered first
        self.sound_table = None  # per order per row: the channels sounding there (sounding_table), rebuilt on reload
        self.renders = {}     # render key -> {"status", "error", "file", "peak"}
        self.compiled = {}    # compile key -> .it bytes of the tryout section (a candidate swapped in), patched per render
        self.prepared = {}    # playback key -> inseparable backing/plan at the requested actual mixer rate
        self.meters = None    # soloed channel levels of the section with the unwritten mix applied
        self.meas = {}        # wav path -> measurement (memo, kept while the file's stamp holds: meas_stamp)
        self.meas_stamp = {}
        # before each app write of the song (undo) and after an undo (redo): {"text": the song text, "meta": the tryout
        # settings that write changed (a channel's mutes and faders remapped, the mix written, the slot's candidates
        # cleared by U), as they were, or None}
        self.history, self.future = [], []
        self.takes = []       # this session's recorded takes, newest first (save_take)
        self.selection = None  # the page's pattern selection or cursor: {order, pattern, rows [a, b], channels [a, b]}
        self.ui_state = None   # last window report; agent inspection includes its age rather than claiming live state
        self.cue = None        # an agent's request to show (and play) a place: {id, order, row, channel, play}
        self.agent_allow = {}  # the owner's go-ahead for one agent action: {"replace": monotonic deadline} (ALLOW REPLACE)
        self.agent_log = []    # the agent tools' calls (agent.run): what an agent did, for the page
        self.agent_measures = {}  # the last measure per scope, for the next one's change
        self.build = None     # last build/export result
        self.export_job = None
        self.export_result = None
        self.stems = None     # stems export progress
        self.recipe_job = None  # the recipe panel's last render, write or synth download: {"status", "error", "log", "file", "need"}
        self.synthesis_job = None  # agent render; outputs are new assets, never an automatic tryout choice
        self._recipe_retry = None  # the render a missing synth stopped, run again once fetch_synth has it
        self._recipe_memo = {}  # (recipe path, mtime, size) -> recipe_outputs, or None for a YAML file that is no recipe
        self.error = None
        self.text = ""
        self._sha = (None, "")       # (text, its sha1): every poll hashes the text once per candidate otherwise
        self._stamps = None          # the mix's WAV stamps while a snapshot runs (it asks once per candidate)
        self.mtime = 0.0
        self.facts = None
        self.mod = None       # compiled model of the last good load (pattern view)
        self.it_stamps = None
        self.it = None        # its .it bytes: the whole song as it is, which the live engine plays unless the panel edits it
        self._to_measure = None  # the newest reload's sample files, for the measuring thread (_measure_later)
        self._measuring = False
        self._measure_guard = threading.Lock()
        self.reload(archive=not headless)
        if saved:
            self.checkpoints = saved['checkpoints']
            if saved['head'] == digest(self._raw):
                self.history, self.future = saved['undo'], saved['redo']
            else:
                self.notices.append('External edits since the last session: undo/redo start fresh; named checkpoints remain available for comparison.')
        self._history_ready = True
        if headless:
            return
        self.cache_dir.mkdir(exist_ok=True)
        for _ in range(WORKERS):
            threading.Thread(target=self._worker, daemon=True).start()

    # ---- song

    def reload(self, archive=True, loaded=None):
        """Re-read the song. `archive`: notes made against another version of the song text move to their archive
        (the song changed outside the app: a rebuild); the app's own writes pass False, so a slot write mid-session
        keeps the notes. `loaded`: the (module, warnings) of this very text, already compiled by the caller."""
        with self.lock:
            raw = self.song_path.read_bytes()
            if archive and self.text and raw != self._raw:
                self.history.clear()
                self.future.clear()
                self.notices.append('External reload: undo and redo start a new history boundary.')
            self._raw = raw
            self.crlf = b"\r\n" in raw
            self.bom = raw.startswith(b"\xef\xbb\xbf")  # older Notepad; kept on write, but not in the text the editors read
            self.text = raw[3 if self.bom else 0:].decode("utf-8").replace("\r\n", "\n")
            self.mtime = self.song_path.stat().st_mtime
            try:
                if loaded is not None and loaded[0].score_projection is not None:
                    loaded = None  # A strict export result cannot become State's residual/score model.
                mod, warnings = loaded or load_for_state(self.text, self.base_dir, str(self.song_path))
                it = None if mod.native_score is not None else write_it(mod)
                facts = facts_of(mod, warnings, it)
                self.mod, self.it, self.facts = mod, it, facts
                self.sound_table = None
                self.error = None
            except SongError as e:
                self.error = e.errors
                self.it = None
            try:
                self.song = api.from_yaml(self.text)
            except yaml.YAMLError:  # a syntax error: it is in self.error already, and the app opens on it
                self.song = None
            if not isinstance(self.song, dict):
                self.song = {}
            for sec in ("module", "samples", "instruments", "patterns"):  # the compiler reports one that is not a map
                if sec in self.song and not isinstance(self.song[sec], dict):
                    self.song[sec] = {}
            for sec in ("samples", "instruments"):  # a quoted key ('08', '8') reads as a string here; the compiler reads 8
                if isinstance(self.song.get(sec), dict):
                    self.song[sec] = {int(k) if isinstance(k, str) and k.isdigit() else k: v for k, v in self.song[sec].items()}
            files = self.files = [str((self.base_dir / v["file"]).resolve()) for v in (self.song.get("samples") or {}).values()
                     if isinstance(v, dict) and v.get("file")]
            self.it_stamps = "|".join(_stamp(f) for f in files)  # the WAVs self.it was compiled from
            self._measure_later(files)
            if self.meta["slot"] not in (self.song.get("samples") or {}):
                self.meta["slot"] = min(self.song.get("samples") or {1: 0})
            if archive and not self.read_only:
                self._archive_old_notes()
                if self._history_ready:
                    _atomic(self.history_store.path, self.history_store.data(self._raw, self.history, self.future, self.checkpoints))
            if self.notes and not self.headless and not self.read_only:
                try:
                    self.save_notes()
                except OSError as e:
                    self.notices.append(f'Song loaded; listening-note report could not be refreshed: {e}')
            self.queue_all()

    def _measure_later(self, files):
        """The sample files measured ahead of the page asking, on one thread per State: a reload while it runs leaves
        its list for that thread (replacing a list not yet started) instead of starting another. The hand-over has a
        lock of its own: with State.lock the thread waiting for it held up the edit that had just reloaded (tools/bench.py:
        edit->live about 2x on demo2 and demo3)."""
        with self._measure_guard:
            self._to_measure = files
            if self._measuring:
                return
            self._measuring = True
        threading.Thread(target=self._measure_files, name=f"measure {self.song_path}", daemon=True).start()

    def _measure_files(self):
        while True:
            with self._measure_guard:
                files, self._to_measure = self._to_measure, None
                if files is None:
                    self._measuring = False
                    return
            for f in files:
                try:
                    if Path(f).exists():
                        self.measured(f)
                except Exception:  # noqa: BLE001 - logged; the thread lives on for the next reload's list
                    _log.exception("Measuring %s failed", f)

    def dirty(self):
        try:
            return self.song_path.read_bytes() != self._raw
        except OSError:
            return True

    def save_meta(self):
        if self.read_only:  # the settings stay in this window (the notice says so)
            return
        _atomic_text(self.meta_path, json.dumps(relative_meta(self.meta, self.base_dir), indent=1))

    def _writable(self):
        if self.read_only:
            raise ValueError(self.read_only)

    def write_song(self, text):
        """The song file, written with the line endings (and the byte-order mark) it had (write_text would turn every LF into
        CRLF on Windows), atomically."""
        _atomic(self.song_path, (b"\xef\xbb\xbf" if self.bom else b"") + text.replace("\n", "\r\n" if self.crlf else "\n").encode("utf-8"))

    def _put(self, prio, job):
        self.jobs.put((prio, next(self._seq), job))

    def set_want(self, cand):
        """The candidate the page is listening to (None: the song): its pending render jumps the queue."""
        with self.lock:
            self.want = cand
            self.meta["selected_candidate"] = cand
            self.save_meta()
            k = self.key(cand)
            if self.renders.get(k, {}).get("status") == "queued":
                self._put(1, (k, cand))

    # ---- candidates

    @property
    def slot(self):
        return self.meta["slot"]

    @property
    def orders(self):
        o = self.meta.get("orders")
        return tuple(o) if o else None

    def set_loop(self, body):
        """The playback loop: `from` and `to` as [order, row] in the facts' order list (`to` inclusive), clamped to the song
        and put in order; a body without them clears it. Playback only: the page loops that span of whichever render plays
        (the song or a candidate, when the span lies inside the rendered section), so no render key changes."""
        f, lp = self.facts, None
        if f and body.get("from") is not None and body.get("to") is not None:
            def at(p):
                o = max(0, min(len(f["orders"]) - 1, int(p[0])))
                return [o, max(0, min(f["orders"][o]["rows"] - 1, int(p[1])))]
            a, b = sorted([at(body["from"]), at(body["to"])])
            lp = {"from": a, "to": b}
            if f.get('playback_orders'):
                self._resolved_playback_span((f['orders'][a[0]]['order'], a[1], f['orders'][b[0]]['order'], b[1]))
        with self.lock:
            self.meta["loop"] = lp
            self.save_meta()

    def cands(self):
        return self.meta["candidates"].setdefault(str(self.slot), [])

    def cand(self, i):
        """Candidate `i` of the slot's list; a ValueError outside it (a negative index would pick from the end)."""
        i = int(i)
        if not 0 <= i < len(self.cands()):
            raise ValueError(f"no candidate {i}")
        return self.cands()[i]

    def pattern_at(self, index):
        """Pattern index `index` of the compiled module, checked (a negative one would pick from the end)."""
        i = int(index)
        if self.mod is None or not 0 <= i < len(self.mod.patterns):
            raise ValueError(f"no pattern {i}")
        return i

    def _need_tracker_operation(self, operation):
        """Cell-only operations must never silently edit just the backing of a native score."""
        self._need_compiled()
        if self.mod.native_score is not None:
            raise ValueError(f'{operation} requires exact score-aware editing; use TAB note/beat edits for this song')

    @staticmethod
    def _chan(items, i):
        """Channel index `i` of the song's channel lines, checked (a negative one would pick from the end)."""
        i = int(i)
        if not 0 <= i < len(items):
            raise ValueError(f"no channel {i + 1}")
        return i

    # ---- the reference recording (SPECTRUM tab)

    def section_start(self):
        """Where the rendered section starts in the song, in seconds (the order times of the facts)."""
        f, o = self.facts, self.orders
        if f and f.get('playback_orders') and o:
            return self._resolved_playback_span(self._order_region(o))['start']
        return f["orders"][o[0]]["start"] if f and o and o[0] < len(f["orders"]) else 0.0

    def set_reference(self, path, body):
        """The reference: `path` sets it (decoded once to check that ffmpeg reads it; the offset is kept), `offset` (ms)
        moves it, `align` with the render `key` that plays sets the offset that lines it up, `clear` drops it."""
        ref = dict(self.meta.get("reference") or {})
        if body.get("clear"):
            ref = None
        if path:
            src = (self.base_dir / Path(path).expanduser()).resolve()
            if not src.is_file():
                raise ValueError(f"no such file: {src}")
            reference_wav(src, self.cache_dir)
            ref = {"file": str(src), "offset_ms": ref.get("offset_ms", 0) if ref else 0}
        if ref and body.get("offset") is not None:
            ref["offset_ms"] = round(float(body["offset"]))
        out = {}
        if ref and body.get("align"):
            r = self.renders.get(body.get("key") or "")
            if not r or r["status"] != "ready":
                raise ValueError("ALIGN needs a render that is playing: wait for it to finish")
            ref["offset_ms"], out["corr"] = reference_align(r["file"], reference_wav(ref["file"], self.cache_dir), ref["offset_ms"],
                                                            self.section_start())
        with self.lock:
            self.meta["reference"] = ref
            self.save_meta()
        return {"reference": ref, **out}

    def reference_compare(self, key, scale="log"):
        """reference_compare() for the render `key` against the reference; ValueError when either is missing."""
        r, ref = self.renders.get(key), self.meta.get("reference")
        if not ref:
            raise ValueError("no reference set")
        if not r or r["status"] != "ready":
            raise ValueError("not rendered")
        stamp = lambda f: f"{Path(f).stat().st_mtime}:{Path(f).stat().st_size}"  # noqa: E731
        w = reference_wav(ref["file"], self.cache_dir)
        return reference_compare(r["file"], stamp(r["file"]), str(w), stamp(w), ref["offset_ms"], self.section_start(), scale)

    def reference_png(self, key, view, scale="log"):
        s, r, d, *_ = self.reference_compare(key, scale)
        if view == "delta":
            import numpy as np
            n = len(DELTA_STOPS)  # the colour stops below the scale's bottom: black, for cells silent in both
            v = (np.clip((d + DELTA_DB) / (2 * DELTA_DB), 0, 1) * (n - 1) + 1) / n
            return _colour_png(np.nan_to_num(v, nan=0.0), [[0, 0, 0]] + DELTA_STOPS)
        return _colour_png((r - SPEC_DB[0]) / (SPEC_DB[1] - SPEC_DB[0]), SPEC_STOPS)

    def current_file(self):
        f = ((self.song.get("samples") or {}).get(self.slot) or {}).get("file")
        return str((self.base_dir / f).resolve()) if f else None

    def silenced(self):
        """Channel indices muted in tryout renders: all but the solo channel, else the muted set."""
        if self.meta.get("solo") is not None and self.facts:
            return [i for i in range(len(self.facts["channels"])) if i != self.meta["solo"]]
        return sorted(set(self.meta.get("muted") or []))

    def mix(self):
        """The unwritten mix: {"volume": {ch: 0-64}, "pan": {ch: 0-64|surround}, "mix_volume": 0-128, "sample_volume": {slot: 0-64},
        "instrument": {number: {panel param: value}}} (keys are strings: the meta round-trips through JSON)."""
        return self.meta.get("mix") or {}

    def set_mix(self, m):
        mix = {}
        for k, hi in (("volume", 64), ("pan", 64), ("sample_volume", 64)):
            d = {str(int(i)): "surround" if k == "pan" and v == "surround" else max(0, min(hi, int(v)))
                 for i, v in (m.get(k) or {}).items()}
            if any(not 0 <= int(i) < 64 for i in d):
                raise ValueError("a channel is 0-63")
            if d:
                mix[k] = d
        if m.get("mix_volume") is not None:
            mix["mix_volume"] = max(0, min(128, int(m["mix_volume"])))
        inst = {}
        for n, edit in (m.get("instrument") or {}).items():  # a value back at the song's own is no change
            ins = (self.song.get("instruments") or {}).get(int(n))
            if not isinstance(ins, dict):
                continue
            now, custom = voice_of(ins)
            keep = {k for g in custom for k in VOICE_GROUPS[g]}
            e = {k: max(VOICE_RANGE[k][0], min(VOICE_RANGE[k][1], int(v))) for k, v in edit.items() if k in VOICE_RANGE}
            e = {k: v for k, v in e.items() if v != now[k] or k in keep}
            if e:
                inst[str(int(n))] = e
        if inst:
            mix["instrument"] = inst
        with self.lock:
            self.meta["mix"] = mix
            self.save_meta()
            self.queue_all()

    def text_sha(self):
        """sha1 of the song text, computed once per text."""
        if self._sha[0] is not self.text:
            self._sha = (self.text, hashlib.sha1(self.text.encode()).hexdigest())
        return self._sha[1]

    def ckey(self, cand=None):
        """Compile key: song text, slot, section, the candidate swapped in (None: the song as it is) and the stamp of every
        WAV in the mix (a sample re-rendered in place under the same path must not serve the old mix)."""
        stamps = self._stamps or "|".join(_stamp(f) for f in self.files)
        if cand:
            stamps = f"{_stamp(cand)}|{stamps}"
        inst = json.dumps(self.mix().get("instrument"), sort_keys=True)  # the instrument panel is compiled in, not patched
        native = '|native-v1' if 'score' in self.song else ''
        return hashlib.sha1(f"{api.RENDER_VERSION}|{self.text_sha()}|{self.slot}|{self.orders}|{stamps}|{inst}{native}".encode()).hexdigest()[:16]

    def key(self, cand=None):
        """Render cache key: the compile key plus what is patched into the module's header, mutes, the unwritten mix and,
        for a candidate, MATCH LEVEL (its gain follows from the WAVs' stamps in the compile key)."""
        match = "|match" if cand and self.meta.get("match_level") else ""
        ending = "|native-ending-v2" if 'score' in self.song else ""
        return hashlib.sha1(f"{self.ckey(cand)}|{self.silenced()}|{json.dumps(self.mix(), sort_keys=True)}{match}{ending}".encode()).hexdigest()[:16]

    # ---- MATCH LEVEL: each candidate played as loud as the slot's current sample. Playback only: the gain never reaches
    # the song, the mix or what U writes

    def match_db(self, cand):
        """The gain in dB that brings `cand` to the loudness of the slot's current sample (measure.sample_lufs: both WAVs
        play from the same slot, so pitch, envelopes and volume commands cancel); None when either cannot be measured."""
        cur = self.current_file()
        a = self.measured(cur).get("lufs") if cur and Path(cur).exists() else None
        b = self.measured(cand).get("lufs") if Path(cand).exists() else None
        return round(a - b, 1) if a is not None and b is not None else None

    def set_match(self, on):
        with self.lock:
            self.meta["match_level"] = bool(on)
            self.save_meta()
            self.queue_all()

    def raw_file(self, i):
        """What SAMPLE ALONE plays for candidate `i`: its WAV, or with MATCH LEVEL on a copy at the matched gain less
        MATCH_PAD dB (nothing else plays then, so the pad changes no comparison and keeps a boost from clipping)."""
        c = self.cand(i)
        db = self.match_db(c) if self.meta.get("match_level") else None
        if db is None:
            return c
        out = self.cache_dir / "match" / f"{hashlib.sha1(f'{_stamp(c)}|{db}'.encode()).hexdigest()[:16]}.wav"
        if not out.exists():  # ponytail: never pruned (_prune globs the cache's own WAVs); one small copy per candidate and gain
            import numpy as np
            w = read_wav(c)
            x = np.asarray(w.channels if len(w.channels) > 1 else w.channels * 2, float) * (256 if w.out_bits == 8 else 1)
            x = np.clip(np.round(x * 10 ** ((db - MATCH_PAD) / 20)), -32768, 32767).astype("<i2")
            out.parent.mkdir(exist_ok=True)
            _atomic(out, wav_bytes(x[:2].T.tobytes(), w.rate))
        return str(out)

    def meter_key(self):
        return hashlib.sha1(f"{self.ckey()}|{json.dumps(self.mix(), sort_keys=True)}".encode()).hexdigest()[:16]

    def measured(self, path):
        try:
            st = Path(path).stat()
            stamp = (st.st_mtime, st.st_size)
        except OSError:
            stamp = None
        if path not in self.meas or self.meas_stamp.get(path) != stamp:
            self.meas_stamp[path] = stamp
            try:
                self.meas[path] = measure(path)
            except (OSError, ValueError) as e:
                self.meas[path] = {"error": str(e)}
        return self.meas[path]

    def add_candidates(self, globs):
        found = []
        for g in re.split(r"[\r\n;]+", globs):
            g = g.strip().strip('"')
            if not g:
                continue
            pat = g if os.path.isabs(g) else str(self.base_dir / g)
            files = sorted(f for f in glob.glob(pat, recursive=True) if Path(f).suffix.lower() in (".wav", *SOUND_FILES))
            found += [str(self.as_wav(Path(f).resolve())[0]) for f in files]  # a decode by ffmpeg runs outside the lock
        added = []
        with self.lock:
            for f in found:
                if f not in self.cands():
                    self.cands().append(f)
                    added.append(f)
            self.save_meta()
            self.queue_all()
        return added

    def remove_candidate(self, path):
        with self.lock:
            if path in self.cands():
                self.cands().remove(path)
            self.save_meta()

    def queue_all(self):
        with self.lock:
            for c in [None, *self.cands()]:  # the song as it is first, then the candidates
                k = self.key(c)
                if k not in self.renders:
                    f = self.cache_dir / f"{k}.wav"
                    if f.exists():
                        self.renders[k] = {"status": "ready", "file": str(f), "error": None, "peak": _peak(f.read_bytes()[44:])}
                    else:
                        self.renders[k] = {"status": "queued", "file": str(f), "error": None}
                        self._put(1 if c == self.want else 2 if c is None else 3, (k, c))
            mk = self.meter_key()
            if self.facts and (not self.meters or self.meters["key"] != mk):
                self.meters = {"key": mk, "status": "queued", "levels": None, "mix": self.mix(), "error": None}
                self._put(4, ("meters", mk))

    def compiled_it(self, cand=None, whole=False):
        """The tryout section (`whole`: the whole song) compiled with `cand` in the slot (None: the song as it is), memoised
        per compile key."""
        with self.lock:
            inst = self.mix().get("instrument") or {}
            if whole and not cand and self.it and self.it_stamps == (self._stamps or "|".join(_stamp(f) for f in self.files)) and not any(int(n) in (self.song.get("instruments") or {}) for n in inst):
                return self.it  # the song as reload compiled it: the same bytes as compiling it again from the dict
        ck = self.ckey(cand) + ("|whole" if whole else "")
        if ck not in self.compiled:
            with self.lock:
                span = None
                if not whole and self.orders and self.facts:
                    a, b = self.orders
                    playable = self.facts['orders']
                    if not 0 <= a < b <= len(playable):
                        raise ValueError('Selected order range is no longer valid')
                    span = (playable[a]['order'], playable[b-1]['order']+1)
                base, slot = api.tryout_song(self.song, span, compiled=self.mod), self.slot
                inst = self.mix().get("instrument") or {}
            for n, edit in inst.items():
                if int(n) in (base.get("instruments") or {}):
                    base["instruments"][int(n)] = voice_entry(base["instruments"][int(n)], edit)
            if cand:
                api.swap_sample(base, slot, Path(cand).resolve())
            it = api.compile_song(base, self.base_dir)[0]
            with self.lock:  # several workers: the memo changes under the lock only
                while len(self.compiled) >= 8:
                    self.compiled.pop(next(iter(self.compiled)))
                self.compiled[ck] = it
            return it
        return self.compiled.get(ck) or self.compiled_it(cand, whole)

    def live_it(self):
        """What the live engine plays: the whole song as it is now with the unwritten mix (faders patched into the header,
        the instrument panel compiled in); mutes are the engine's own."""
        return patch_it(self.compiled_it(whole=True), (), self.mix())

    def _order_region(self, orders):
        """The selected playable order span as the exporter's inclusive rows."""
        if not orders:
            return None
        a, b = orders
        playable = self.facts['orders'] if self.facts else []
        if not 0 <= a < b <= len(playable):
            raise ValueError('Selected order range is no longer valid')
        region = playable[a]['order'], 0, playable[b-1]['order'], playable[b-1]['rows']-1
        if self.facts.get('playback_orders'):
            self._resolved_playback_span(region)
        return region

    def _resolved_playback_span(self, region):
        """Resolve authored inclusive rows without broadening disjoint repeated selections."""
        from .tablature import resolve_source_region, TempoClock
        plan = self.mod.native_score['plan']
        a, r0, b, r1 = resolve_source_region(plan, region)
        step = Fraction(*plan['row_step'])
        start = Fraction(*plan['occurrences'][a]['at']) + r0 * step
        end = Fraction(*plan['occurrences'][b]['at']) + (r1 + 1) * step
        clock = TempoClock(plan['tempo'], plan.get('tempos'))
        return dict(revision=self.text_sha(), **{'from': [a, r0], 'to': [b, r1]},
                    start=float(clock.seconds_at(start)), end=float(clock.seconds_at(end)))

    def _playback_selection(self):
        if not self.facts or not self.facts.get('playback_orders'):
            return {}
        region, loop, error = None, None, None
        try:
            if self.orders:
                region = self._resolved_playback_span(self._order_region(self.orders))
            if self.meta.get('loop'):
                a, r0 = self.meta['loop']['from']
                b, r1 = self.meta['loop']['to']
                orders = self.facts['orders']
                loop = self._resolved_playback_span((orders[a]['order'], r0, orders[b]['order'], r1))
        except (ValueError, IndexError) as exc:
            error = str(exc) or 'Playback selection is no longer valid'
        return dict(playback_revision=self.text_sha(), playback_region=region, playback_loop=loop, playback_selection_error=error)

    def prepared_playback(self, sample_rate, cand=None, whole=False):
        """Capture and prepare one playback revision.

        `sample_rate` is the actual mixer rate, including offline oversampling. Whole-song playback leaves mutes to
        the live engine; tryout playback includes mute/solo. Apply the returned `gain` to rendered PCM for MATCH LEVEL.
        Native selections retain the full backing/plan and an exporter snapshot for replay-to-start and exact end.
        """
        if type(sample_rate) is not int or not 8000 <= sample_rate <= 384000:
            raise ValueError('sample_rate must be an integer mixer rate in 8000..384000')
        if type(whole) is not bool:
            raise ValueError('whole must be a boolean')
        candidate = str(Path(cand).resolve()) if cand else None
        with self.lock:
            if self.closed:
                raise ValueError('The song was closed before playback preparation')
            text, revision, song_path = self.text, self.text_sha(), str(self.song_path)
            base = api.from_yaml(text)
            if not isinstance(base, dict):
                raise ValueError('Playback requires a song mapping')
            slot, orders = self.slot, copy.deepcopy(self.orders)
            mix, silenced = copy.deepcopy(self.mix()), tuple(self.silenced())
            matching = bool(self.meta.get('match_level'))
            span, region = None, None
            if not whole and orders:
                a, b = orders
                playable = self.facts['orders'] if self.facts else []
                if not 0 <= a < b <= len(playable):
                    raise ValueError('Selected order range is no longer valid')
                if 'score' in base:
                    region = self._order_region(orders)
                else:
                    span = (playable[a]['order'], playable[b - 1]['order'] + 1)
            samples = base.get('samples') or {}
            files = [str((self.base_dir / entry['file']).resolve())
                     for entry in (samples.values() if isinstance(samples, dict) else ())
                     if isinstance(entry, dict) and isinstance(entry.get('file'), str)]
            if candidate:
                files.append(candidate)
            stamps = tuple(_stamp(path) for path in files)  # Do not reuse snapshot's temporarily cached _stamps.
            db = self.match_db(candidate) if candidate and matching else None
            key = hashlib.sha1(json.dumps([api.RENDER_VERSION, song_path, revision, sample_rate, whole,
                                          slot, orders, candidate, mix, silenced if not whole else (), db, stamps],
                                         sort_keys=True).encode()).hexdigest()[:16]
            if key in self.prepared:
                return copy.deepcopy(self.prepared[key])
        base = api.tryout_song(base, span)
        for number, edit in (mix.get('instrument') or {}).items():
            if int(number) in (base.get('instruments') or {}):
                base['instruments'][int(number)] = voice_entry(base['instruments'][int(number)], edit)
        if candidate:
            api.swap_sample(base, slot, Path(candidate))
        snapshot = None
        if region is not None:
            from .export import snapshot as export_snapshot, _plan_at_rate
            # The instrument panel was applied above; the snapshot patches only
            # the remaining mixer fields, so envelopes are not edited twice.
            snapshot = export_snapshot(base, self.base_dir, region=region,
                                       mix={k: v for k, v in mix.items() if k != 'instrument'},
                                       muted=silenced, tail=0)
            snapshot['plan'] = _plan_at_rate(snapshot['plan'], sample_rate)
            prepared = dict(backing_it=snapshot['render_it'], plan=snapshot['plan'])
            data = prepared['backing_it']
        else:
            prepared = api.prepare_playback(base, self.base_dir, sample_rate)
            data = patch_it(prepared['backing_it'], () if whole else silenced, mix)
        gain = 1.0
        if db:
            data, gain = match_level(data, slot, db)
        bundle = dict(key=key, revision=revision, song=song_path, sample_rate=sample_rate,
                      backing_it=data, plan=prepared['plan'], gain=gain)
        if snapshot is not None:
            snapshot['render_it'] = data
            bundle['snapshot'] = snapshot
        with self.lock:
            if (self.closed or str(self.song_path) != song_path or self.text != text or self.slot != slot or self.orders != orders or self.mix() != mix or
                    tuple(self.silenced()) != silenced or bool(self.meta.get('match_level')) != matching or
                    tuple(_stamp(path) for path in files) != stamps):
                raise ValueError('Playback inputs changed during preparation; retry with the current song and mix')
            while len(self.prepared) >= 8:
                self.prepared.pop(next(iter(self.prepared)))
            self.prepared[key] = bundle
            return copy.deepcopy(bundle)

    def retry(self, path):
        with self.lock:
            k = self.key(path)
            self.renders[k] = {"status": "queued", "file": str(self.cache_dir / f"{k}.wav"), "error": None}
            self._put(1, (k, path))

    def close(self):
        """Another song replaced this one in the app: the worker stops after the job it is on (it would keep rendering
        into this song's cache and prune it against the new state's writes)."""
        with self.lock:
            self.closed = True
            if self.synthesis_job and self.synthesis_job['status'] in ('queued', 'rendering', 'cancelling'):
                self.synthesis_job['cancel'] = True
                self.synthesis_job['status'] = 'cancelled' if self.synthesis_job['status'] == 'queued' else 'cancelling'
        self.release_lock()
        for _ in range(WORKERS):
            self._put(-1, ("close",))

    def release_lock(self):
        """Give the song's lock back (another song replaced this one, or it failed to open)."""
        if self._app_lock:
            self._app_lock = False
            server.release_app_lock(self.song_path)

    def _worker(self):
        while not self.closed:
            job = self.jobs.get()[2]
            if job[0] == "close":
                return
            if job[0] in ("export", "build", "meters", "recipe", "fetch", "synthesis"):
                try:
                    if job[0] == 'export':
                        from .export import run
                        run(job[1], _encode)
                    elif job[0] == "build":
                        self._build(job[1])
                    elif job[0] == "meters":
                        self._meters(job[1])
                    elif job[0] == "synthesis":
                        agent.agent_sounds.render_job(self, job[1])
                    elif job[0] == "recipe":
                        self._recipe_render(*job[1])
                    else:
                        self._fetch_synth(job[1])
                except Exception as e:  # noqa: BLE001 - what a job's own handler did not expect: it fails alone, the worker goes on
                    self._job_failed(job, f"{type(e).__name__}: {e}")
                continue
            k, cand = job
            with self.lock:
                if self.renders.get(k, {}).get("status") != "queued":
                    continue
                if self.key(cand) != k:  # settings changed since queueing; queue_all has queued the current key
                    self.renders.pop(k, None)
                    continue
                self.renders[k]["status"] = "rendering"
                silenced, mix, slot = self.silenced(), self.mix(), self.slot
                db = self.match_db(cand) if cand and self.meta.get("match_level") else None
            try:
                if self.mod is not None and self.mod.native_score is not None:
                    bundle = self.prepared_playback(RATE * 2, cand)
                    data, gain, plan = bundle['backing_it'], bundle['gain'], bundle['plan']
                else:
                    data, gain, plan = patch_it(self.compiled_it(cand), silenced, mix), 1.0, None
                    if db:
                        data, gain = match_level(data, slot, db)
                if plan is not None and bundle.get('snapshot') is not None:
                    from .export import render
                    pcm = render(bundle['snapshot'], cancel=lambda: self.closed or self.key(cand) != k)
                else:
                    with LoadedModule(data, rate=RATE, oversample=2, plan=plan) as lm:
                        pcm = lm.render(RATE)
                if gain != 1.0:
                    pcm = scale_pcm(pcm, gain)
                out = self.cache_dir / f"{k}.wav"
                _write_pcm(out, pcm)
                with self.lock:
                    if self.key(cand) != k:
                        self.renders.pop(k, None)
                        continue
                    self.renders[k].update(status="ready", file=str(out), peak=_peak(pcm))
                if cand is None or cand == self.want:
                    mix_numbers(out)  # measured now, so the page's next poll does not wait for it
                self._prune()
            except Exception as e:  # noqa: BLE001 - shown in the UI, worker must survive
                with self.lock:
                    self.renders[k].update(status="failed", error=f"{type(e).__name__}: {e}")

    def _job_failed(self, job, error):
        """The job ends in its own failed state with the message, as the page shows it."""
        _log.exception("A %s job failed", job[0])
        error = logged(error)
        with self.lock:
            if job[0] == "export":
                job[1]["result"].update(status="failed", error=error)
            elif job[0] == "build":
                self.build = {"status": "failed", "error": error}
            elif job[0] == "meters" and self.meters:
                self.meters.update(status="failed", error=error)
            elif job[0] in ("recipe", "fetch") and self.recipe_job:
                self.recipe_job.update(status="failed", error=error)
            elif job[0] == "synthesis":
                job[1].update(status="failed", error=error)

    def _meters(self, mk):
        with self.lock:
            if not self.meters or self.meters["key"] != mk:
                return
            self.meters["status"] = "measuring"
            mix, nch = self.meters["mix"], len(self.facts["channels"])
        try:
            snapshot = None
            if self.mod is not None and self.mod.native_score is not None:
                if self.orders:
                    from .export import snapshot as export_snapshot
                    with self.lock:
                        base, region = copy.deepcopy(self.song), self._order_region(self.orders)
                    snapshot = export_snapshot(base, self.base_dir, region=region, mix=mix, tail=0)
                    data, plan = snapshot['render_it'], snapshot['plan']
                else:
                    bundle = self.prepared_playback(RATE, whole=True)
                    data, plan = bundle['backing_it'], bundle['plan']
            else:
                data, plan = patch_it(self.compiled_it(), (), mix), None
            levels = channel_levels(data, nch, cancel=lambda: self.meters["key"] != mk,
                                    plan=plan, snapshot=snapshot)
            with self.lock:
                if levels is not None and self.meters["key"] == mk:
                    self.meters.update(status="ready", levels=levels)
        except Exception as e:  # noqa: BLE001
            with self.lock:
                if self.meters["key"] == mk:
                    self.meters.update(status="failed", error=f"{type(e).__name__}: {e}")

    def _prune(self, keep=60, limit=None):
        """Every mute or fader change leaves a render in the cache: keep the newest `keep` WAVs and, of those, no more
        than `limit` bytes (CACHE_BYTES; the newest always stays), re-queue what is current."""
        limit = CACHE_BYTES if limit is None else limit
        with self.lock:
            total = 0
            for i, (_, size, p) in enumerate(sorted(((s.st_mtime, s.st_size, p) for p in self.cache_dir.glob("*.wav")
                                                     for s in [p.stat()]), reverse=True)):
                total += size
                if i >= keep or (i and total > limit):
                    p.unlink(missing_ok=True)
                    self.renders.pop(p.stem, None)
            self.queue_all()

    # ---- the recipe panel: a slot whose WAV a sample recipe (SAMPLING.md) in the song's folder writes can be rendered again
    # from the app with its entry edited, as a new candidate for the slot (never over the recipe's own WAV); the entry that
    # made a candidate can be written back into the recipe

    def recipes(self):
        """[(recipe path, recipe_outputs)] of the sample recipes in the song's folder: YAML files with `samples:` and no
        `module:`. Memoised per file stamp."""
        from .synth import RecipeError, recipe_outputs
        out = []
        for p in sorted(self.base_dir.iterdir()):
            if p.suffix.lower() not in (".yaml", ".yml") or p == self.song_path or not p.is_file():
                continue
            st = p.stat()
            key = (str(p), st.st_mtime, st.st_size)
            if key not in self._recipe_memo:
                try:
                    head = yaml.safe_load(p.read_text(encoding="utf-8"))
                    ok = isinstance(head, dict) and "samples" in head and "module" not in head
                    self._recipe_memo[key] = recipe_outputs(p) if ok else None
                except (RecipeError, yaml.YAMLError, RecursionError, OSError, UnicodeDecodeError, ValueError, TypeError, KeyError, AttributeError):
                    self._recipe_memo[key] = None
            if self._recipe_memo[key]:
                out.append((p, self._recipe_memo[key]))
        return out

    def slot_recipe(self):
        """The recipe entry behind the slot's WAV: {"recipe", "name", "note", "spec" (the entry as YAML text), "wav"}, or
        None. A WAV the panel rendered carries the entry that made it (meta "recipe_of")."""
        from .synth import RecipeError, recipe_entry
        cur = self.current_file()
        if not cur:
            return None
        made = (self.meta.get("recipe_of") or {}).get(cur)
        if made and Path(made["recipe"]).exists():
            return {**made, "wav": cur}
        for rec, outs in self.recipes():
            for wav, name, note in outs:
                if str(wav) == cur:
                    st = rec.stat()
                    key = (str(rec), st.st_mtime, st.st_size, name)
                    if key not in self._recipe_memo:
                        try:
                            self._recipe_memo[key] = api.safe_dump(recipe_entry(rec, name)[0], default_flow_style=False,
                                                                    sort_keys=False, width=100)
                        except RecipeError:
                            self._recipe_memo[key] = None
                    if self._recipe_memo[key] is None:
                        return None
                    return {"recipe": str(rec), "name": name, "note": note, "wav": cur, "spec": self._recipe_memo[key]}
        return None

    @staticmethod
    def _recipe_spec(text):
        try:
            spec = api.from_yaml(text or "")  # numbers as the recipe file reads them (0100 is a hundred)
        except yaml.YAMLError as e:
            raise ValueError(f"the sample entry is not YAML: {e}")
        if not isinstance(spec, dict):
            raise ValueError("the sample entry is a YAML mapping (patch: ..., note: ..., hold: ...)")
        return spec

    def request_recipe_render(self, text):
        """Render the slot's recipe entry as `text` (YAML) says, as a new candidate for the slot (a job on the worker)."""
        rec = self.slot_recipe()
        if not rec:
            raise ValueError(f"slot {self.slot}'s WAV is not written by a sample recipe in the song's folder")
        spec = self._recipe_spec(text)
        with self.lock:
            self.recipe_job = {"status": "queued", "error": None, "log": [], "file": None}
        self._put(0, ("recipe", (rec, spec, text, self.slot)))

    def _recipe_render(self, rec, spec, text, slot):
        from .synth import RecipeError, SynthMissing, render_one
        with self.lock:
            self.recipe_job.update(status="rendering", error=None, need=None)
        src = Path(rec["wav"])
        stem = re.sub(r"-r\d+$", "", src.stem)
        out = next(q for q in (src.with_name(f"{stem}-r{k}.wav") for k in itertools.count(1)) if not q.exists())
        try:
            render_one(rec["recipe"], rec["name"], spec, rec["note"], out, log=lambda s: self.recipe_job["log"].append(s))
        except ImportError as e:
            return self._recipe_failed(f"rendering needs pedalboard and the synths (SAMPLING.md, Setup): {e}")
        except SynthMissing as e:  # the page offers the download (fetch_synth) and renders again after it
            self._recipe_retry = (rec, spec, text, slot)
            return self._recipe_failed(str(e), need=e.kind)
        except (RecipeError, OSError, ValueError, KeyError, TypeError) as e:
            return self._recipe_failed(f"{type(e).__name__}: {e}")
        with self.lock:
            self.meta.setdefault("recipe_of", {})[str(out.resolve())] = {k: rec[k] for k in ("recipe", "name", "note")} | {"spec": text}
            if self.slot == slot:
                self.add_candidates(str(out))
            else:
                self.meta["candidates"].setdefault(str(slot), []).append(str(out.resolve()))
                self.save_meta()
            self.recipe_job.update(status="done", file=str(out))

    def _recipe_failed(self, error, need=None):
        with self.lock:
            self.recipe_job.update(status="failed", error=error, need=need)

    def request_fetch_synth(self, kind):
        from .synth import FETCH
        if kind not in FETCH and kind != "faust":
            raise ValueError(f"no download for '{kind}'")
        with self.lock:
            self.recipe_job = {"status": "fetching", "error": None, "log": [], "file": None, "need": kind, "got": 0, "size": 0}
        self._put(0, ("fetch", kind))

    def _fetch_synth(self, kind):
        """Download a synth the recipe panel's last render missed, then render that entry again."""
        from .synth import fetch_synth
        if kind == "faust":
            from .faust import fetch as fetch_synth  # noqa: F811 - faustwasm, from npm
        try:
            fetch_synth(*([] if kind == "faust" else [kind]), lambda got, size: self.recipe_job.update(got=got, size=size))
        except (OSError, ValueError) as e:  # urllib's errors are OSErrors; a bad zip is a ValueError
            return self._recipe_failed(f"the download failed: {type(e).__name__}: {e}", need=kind)
        retry, self._recipe_retry = self._recipe_retry, None
        if retry:
            self._recipe_render(*retry)
        else:
            with self.lock:
                self.recipe_job.update(status="fetched")

    def recipe_write(self, text):
        """The slot's recipe entry replaced by `text` (YAML) in the recipe file, in place: a one-line entry stays one line
        (its trailing comment kept), a block entry is re-dumped as a block; the rest of the recipe is untouched."""
        rec = self.slot_recipe()
        if not rec:
            raise ValueError(f"slot {self.slot}'s WAV is not written by a sample recipe in the song's folder")
        spec = self._recipe_spec(text)
        from .synth import RecipeError, expand
        try:
            list(expand({"samples": {rec["name"]: spec}}))
        except RecipeError as e:
            raise ValueError(str(e))
        path = Path(rec["recipe"])
        raw = path.read_bytes()
        crlf = b"\r\n" in raw
        lines = raw.decode("utf-8").replace("\r\n", "\n").splitlines(keepends=True)
        j = next((j for j, k in self._children(lines, self._top(lines, "samples")) if k == rec["name"]), None)
        m = self._entry(lines[j], re.escape(rec["name"]) + ":") if j is not None else None
        if m is None:
            raise ValueError(f"the recipe's entry '{rec['name']}' is not written as one mapping the app can replace")
        self._redump(lines, j, m, spec)
        _atomic(path, "".join(lines).replace("\n", "\r\n" if crlf else "\n").encode("utf-8"))
        with self.lock:
            self.meta.setdefault("recipe_of", {})[self.current_file()] = {k: rec[k] for k in ("recipe", "name", "note")} | {"spec": text}
            self.save_meta()
            self.recipe_job = {"status": "written", "error": None, "log": [], "file": None}

    # ---- listening notes

    def version(self):
        """The song text the notes were made against: a short hash of the file and its modification time."""
        return {"hash": self.text_sha()[:8],
                "mtime": datetime.datetime.fromtimestamp(self.mtime).isoformat(timespec="seconds")}

    def _played_order(self, order, play_id=None, revision=None, row=None):
        visits = (self.facts or {}).get('playback_orders')
        if not visits:
            return order
        if not 0 <= order < len(self.facts['orders']):
            raise ValueError('No such authored order')
        source = self.facts['orders'][order]
        matches = [v for v in visits if v['source_order'] == source['order'] and
                   v['source_occurrence'] == source['occurrence'] and (play_id is None or v['id'] == play_id)]
        if row is not None:
            step = Fraction(*self.mod.native_score['plan']['row_step'])
            matches = [v for v in matches if Fraction(*v['source_from']) <= row * step < Fraction(*v['source_to'])]
        if play_id is not None and revision != self.text_sha():
            raise ValueError('Playback revision changed; resolve the current pass again')
        if len(matches) != 1:
            raise ValueError('Select a reachable playback pass for this authored order')
        return matches[0]['order']

    def _played_position(self, order, row, play_id=None, revision=None):
        played = self._played_order(order, play_id, revision, row)
        if self.facts.get('playback_orders'):
            visit = self.facts['playback_orders'][played]
            offset = Fraction(*visit['source_from']) / Fraction(*self.mod.native_score['plan']['row_step'])
            if offset.denominator != 1:
                raise ValueError('Playback fragment is not aligned to a source row')
            row -= int(offset)
        return played, row

    def sounding(self, order, row, *, play_id=None, revision=None):
        """The channels sounding at (order, row) of the facts' order list (see sounding_table)."""
        with self.lock:
            order, row = self._played_position(order, row, play_id, revision)
            if self.sound_table is None:
                self.sound_table = sounding_table(self.mod, self.facts)
                self._rescan_notes()
            rows = self.sound_table[order] if 0 <= order < len(self.sound_table) else []
            return rows[min(row, len(rows) - 1)] if rows else []

    def _rescan_notes(self):
        """Notes made against this very song text get their sounding lists recomputed from the fresh table (the rule can
        improve; the listener's tag, words and picked channels are untouched)."""
        v, changed = self.version()["hash"], False
        for n in self.notes:
            order = n.get('play_order', n['order'])
            if (n.get("version") or {}).get("hash") == v and 0 <= order < len(self.sound_table):
                rows = self.sound_table[order]
                row = n.get('play_row', n['row'])
                new = rows[row] if 0 <= row < len(rows) else []
                if new != n.get("sounding"):
                    n["sounding"], changed = new, True
        if changed:
            self.save_notes()

    def sounding_rows(self, order, *, play_id=None, revision=None):
        """One order for the page's live strip: per row, [channel, sample, looped] triples."""
        with self.lock:
            order = self._played_order(order, play_id, revision)
            if self.sound_table is None:
                self.sound_table = sounding_table(self.mod, self.facts)
                self._rescan_notes()
            rows = self.sound_table[order] if 0 <= order < len(self.sound_table) else []
            return [[[e["ch"], e["sample"], int(e["loop"])] for e in r] for r in rows]

    def add_note(self, body):
        """A note at (order, row) of the facts' order list with what was playing; the channels sounding there and the song
        version are filled in here. Saves the JSON and rewrites the report. Returns the note."""
        f = self.facts
        self._writable()
        if not f:
            raise ValueError("the song does not compile")
        order = max(0, min(len(f["orders"]) - 1, int(body.get("order") or 0)))
        o = f["orders"][order]
        row = max(0, min(o["rows"] - 1, int(body.get("row") or 0)))
        played, play_row = self._played_position(order, row, body.get('play_id'), body.get('revision'))
        timing = f['playback_orders'][played] if f.get('playback_orders') else o
        row_time = timing["row_times"][play_row] if "row_times" in timing else timing["seconds"] * play_row / timing["rows"]
        with self.lock:
            note = {"id": max((n["id"] for n in self.notes), default=0) + 1, "when": datetime.datetime.now().isoformat(timespec="seconds"),
                    "version": self.version(), "order": order, "pattern": o["pattern"], "row": row,
                    "span": [timing["start"], timing["seconds"]],
                    "time": round(timing["start"] + row_time, 2),
                    **({'play_order': played, 'play_row': play_row, 'play_id': timing['id'], 'pass': timing['pass'],
                        'source_occurrence': timing['source_occurrence']} if f.get('playback_orders') else {}),
                    "tag": str(body.get("tag") or "note")[:40], "text": str(body.get("text") or "")[:2000],
                    "channels": sorted({int(c) for c in body.get("channels") or []}),
                    "sounding": self.sounding(order, row, play_id=body.get('play_id'), revision=body.get('revision')),
                    "playing": {"source": str(body.get("source") or "song"), "candidate": body.get("candidate"), "slot": self.slot,
                                "section": list(self.orders) if self.orders else None, "loop": self.meta.get("loop"),
                                "muted": self.silenced(), "mix": self.mix()}}
            self.notes.append(note)
            self.save_notes()
        return note

    def edit_note(self, nid, body):
        self._writable()
        with self.lock:
            for n in self.notes:
                if n["id"] == nid:
                    if body.get("delete"):
                        self.notes.remove(n)
                    else:
                        for k in ("text", "tag"):
                            if k in body:
                                n[k] = str(body[k])[:2000]
                        if "channels" in body:
                            n["channels"] = sorted({int(c) for c in body["channels"]})
                    break
            self.save_notes()

    def save_notes(self):
        if self.read_only:  # another window's notes, or a newer app's file: not written over (add_note says so)
            return
        _atomic_text(self.notes_path, json.dumps({"schema": SIDE_SCHEMA, "notes": self.notes}, indent=1))
        _atomic_text(self.notes_path.with_suffix(".md"), self.report())

    def _archive_old_notes(self):
        """Notes made against another version of the song text move to `<song>.notes-<hash>.json` and `.md` beside it,
        so the active file and the NOTES tab hold only notes on the song as it is now; an archive's report keeps that
        version's stamp."""
        v = self.version()["hash"]
        old = [n for n in self.notes if (n.get("version") or {}).get("hash") != v]
        if not old:
            return
        for h in sorted({(n.get("version") or {}).get("hash") or "unknown" for n in old}):
            batch = [n for n in old if ((n.get("version") or {}).get("hash") or "unknown") == h]
            p = self.song_path.with_name(f"{self.song_path.stem}.notes-{h}.json")
            kept = _read_json(p, [], self.notices)
            if newer(kept):  # a newer app's archive is left as it is; these notes stay in the active file
                old = [n for n in old if n not in batch]
                continue
            kept = kept.get("notes", []) if isinstance(kept, dict) else kept if isinstance(kept, list) else []
            seen = {(n["id"], n.get("when")) for n in kept}
            kept += [n for n in batch if (n["id"], n.get("when")) not in seen]
            _atomic_text(p, json.dumps({"schema": SIDE_SCHEMA, "notes": kept}, indent=1))
            _atomic_text(p.with_suffix(".md"), self.report(kept, batch[0].get("version")))
        self.notes = [n for n in self.notes if n not in old]
        self.save_notes()

    def report(self, notes=None, version=None):
        """<song>.notes.md (or an archive's): the notes grouped by order, each with its tag, the channels the listener
        pointed at in bold, what was sounding there, what was playing and their words; then the tryout ratings. For a
        collaborator who cannot listen."""
        f, v, notes = self.facts, version or self.version(), self.notes if notes is None else notes
        fmt = lambda t: f"{int(t // 60)}:{t % 60:04.1f}"  # noqa: E731
        L = [f"# Listening notes: {f['title'] if f else self.song_path.stem}", "",
             f"`{self.song_path.name}` version {v['hash']} ({v['mtime']}), {len(notes)} note{'s' if len(notes) != 1 else ''}; "
             f"VultureTracker {__version__}.",
             "Time is the position in the whole song where the listener clicked (allow up to a second of reaction delay); ord is",
             "the order index, row the row in its pattern. **Bold** channels are the ones the listener pointed at; the others are",
             "what was sounding there (sample number after the name; `~` marks a looped tone still held from an earlier note).", ""]
        by = {}
        for n in notes:
            by.setdefault((n["order"], n.get('play_order', -1)), []).append(n)
        for key in sorted(by):
            order, played = key
            group = by[key]
            # the order as the notes' own version had it (an archive's notes were made on another order list); notes from
            # before the span was kept fall back to the current song for notes on this version, else to the pattern name
            n0 = next((n for n in group if n.get("span")), None)
            o = {"pattern": n0["pattern"], "start": n0["span"][0], "seconds": n0["span"][1]} if n0 else (
                f["orders"][order] if f and order < len(f["orders"]) and version is None else None)
            name = o["pattern"] if o else group[0].get("pattern")
            label = f"ord {order}" + (f" pass {group[0]['pass']} (played {played})" if played >= 0 else '')
            L += [f"## {label} `{name}` ({fmt(o['start'])} to {fmt(o['start'] + o['seconds'])})" if o and o['start'] is not None
                  else f"## ord {order} `{name}`" if name else f"## ord {order}", ""]
            for n in sorted(group, key=lambda n: (n["row"], n["id"])):
                picked = set(n.get("channels") or [])
                snd = []
                for s in n.get("sounding") or []:
                    txt = f"{s['name']} {s['sample']:02d}" if s.get("sample") else s["name"]
                    txt += "~" if s.get("loop") and s.get("ago", 0) > 0 else ""
                    snd.append(f"**{txt}**" if s["ch"] in picked else txt)
                p = n.get("playing") or {}
                what = {"song": "the song", "candidate": f"candidate {p.get('candidate')} in slot {p.get('slot')}",
                        "sample alone": f"the sample alone ({p.get('candidate')}, so the position is the section start)"}.get(p.get("source"), p.get("source") or "")
                if p.get("muted") and f:
                    what += ", muted: " + ", ".join(f["channels"][i] for i in p["muted"] if i < len(f["channels"]))
                if p.get("loop"):
                    what += ", looping ord {} row {} to ord {} row {}".format(*p["loop"]["from"], *p["loop"]["to"])
                if p.get("mix"):
                    what += ", unwritten mix " + json.dumps(p["mix"], separators=(",", ":"))
                old = "" if (n.get("version") or {}).get("hash") == v["hash"] else f" (made against version {(n.get('version') or {}).get('hash')})"
                L.append(f"- **{n['tag'].upper()}** at {fmt(n['time'])}, row {n['row']:02d}{old}: " + (", ".join(snd) or "nothing sounding")
                         + f". Playing {what}." + (f' "{n["text"]}"' if n.get("text") else ""))
            L.append("")
        rated = []
        for slot, cands in self.meta.get("candidates", {}).items():
            for c in cands:
                r = self.meta["ratings"].get(c) or {}
                stars = r.get("stars") if type(r.get("stars")) is int else 0  # a hand-edited .tryout.json: no stars
                if stars or r.get("rejected") or r.get("note"):
                    rated.append(f"- slot {slot}: {Path(c).stem} " + ("rejected" if r.get("rejected") else "*" * stars)
                                 + (f' "{r["note"]}"' if r.get("note") else ""))
        if rated:
            L += ["## Tryout ratings", ""] + rated + [""]
        return "\n".join(L)

    # ---- writing the song

    class _Entry:
        def __init__(self, groups):
            self._g = groups

        def groups(self):
            return self._g

        def group(self, k):
            return self._g[k - 1]

    @classmethod
    def _entry(cls, line, key):
        """A mapping entry `key` on `line` as (indent, key, spaces, one-line flow mapping or None, trailing spaces and
        comment); the flow mapping ends at the brace that closes it (quotes and nesting followed), so a `}` in a trailing
        comment is never taken for part of it. None when the line is not such an entry. The result has .groups() and
        .group(k) like a match."""
        m = re.match(rf"^(\s+)({key})([ \t]*)(.*?)$", line.rstrip("\n"))
        if not m:
            return None
        indent, k, sp, rest = m.groups()
        if not rest.startswith("{"):
            return cls._Entry((indent, k, sp, None, rest)) if re.fullmatch(r"[ \t]*(#.*)?", rest) else None
        depth, quote, j = 0, None, 0
        while j < len(rest):
            c = rest[j]
            if quote:
                if c == "\\" and quote == '"':
                    j += 1
                elif c == quote:
                    quote = None
            elif c in "'\"":
                quote = c
            elif c in "{[":
                depth += 1
            elif c in "}]":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        flow, tail = rest[:j + 1], rest[j + 1:]
        if depth != 0 or not re.fullmatch(r"[ \t]*(#.*)?", tail):
            return None
        return cls._Entry((indent, k, sp, flow, tail))

    @staticmethod
    def _redump(lines, i, m, entry, keys=None):
        """Replace the mapping at line i (`m` from _entry) with `entry` in its own layout: a one-line flow mapping stays
        one line (with `keys`, only those scalar values are substituted inside it, so a hand-aligned line keeps its
        spacing), a block (the deeper-indented lines that follow) is re-dumped as a block. Returns the number of lines
        the entry now occupies."""
        indent, key, sp, flow, tail = m.groups()
        nl = "\n" if lines[i].endswith("\n") else ""
        if flow and keys:
            for k in (k for k in keys if k in entry):
                flow, n = re.subn(rf"(\b{k}:\s*)[^,}}]*", rf"\g<1>{entry[k]}", flow)
                if not n:
                    flow = f"{{{k}: {entry[k]}}}" if flow.strip() == "{}" else flow[:-1].rstrip() + f", {k}: {entry[k]}}}"
            lines[i] = f"{indent}{key}{sp}{flow}{tail}{nl}"
            return 1
        if flow:
            lines[i] = f"{indent}{key}{sp}{api.safe_dump(entry, default_flow_style=True, width=10 ** 6, sort_keys=False).strip()}{tail}{nl}"
            return 1
        j = State._span(lines, i)
        block = [f"{indent}  {b}\n" for b in api.safe_dump(entry, default_flow_style=False, width=10 ** 6, sort_keys=False).splitlines()]
        lines[i:j] = [lines[i]] + block
        return 1 + len(block)

    def _edit_text(self, song, samples=(), channels=(), mix_volume=None, keys=None, instruments=()):
        """Song text with sample slot entries `{slot: entry}`, channel entries `{index: entry}`, instrument entries
        `{number: entry}` and the module's mix_volume written in place (`keys`: only those scalar keys change inside a
        one-line sample or channel entry; an instrument entry is re-dumped whole, its envelopes being nested); the rest of
        the document, comments included, is untouched. When a line cannot be found (a one-line `module:`, a block-style
        channel list) the whole `song` dict is re-dumped instead (comments lost, so the diff says so). Returns (text,
        redumped)."""
        samples, channels, instruments = dict(samples), dict(channels), dict(instruments)
        lines = self.text.splitlines(keepends=True)
        pending = ({("smp", k) for k in samples} | {("ch", k) for k in channels} | {("ins", k) for k in instruments}
                   | ({("mv",)} if mix_volume is not None else set()))
        section = sub = None
        item = cind = mod_line = -1
        i = 0
        while i < len(lines):
            line = lines[i]
            ind, s, n = len(line) - len(line.lstrip()), line.strip(), 1
            if not s or s.startswith("#"):
                i += 1
                continue
            if ind == 0:
                section, sub = line.split(":")[0], None
                mod_line = i if section == "module" else mod_line
            elif section == "samples":
                m = self._entry(line, r"\d+:")
                if m and int(m.group(2)[:-1]) in samples:
                    n = self._redump(lines, i, m, samples[int(m.group(2)[:-1])], keys)
                    pending.discard(("smp", int(m.group(2)[:-1])))
            elif section == "instruments":
                m = self._entry(line, r"\d+:")
                if m and int(m.group(2)[:-1]) in instruments:
                    n = self._redump(lines, i, m, instruments[int(m.group(2)[:-1])])
                    pending.discard(("ins", int(m.group(2)[:-1])))
            elif section == "module":
                if s.startswith("channels:"):
                    sub, item, cind = "ch", -1, ind
                elif sub == "ch" and ind >= cind and s.startswith("-"):
                    item += 1
                    m = self._entry(line, "-")
                    if item in channels and m:
                        n = self._redump(lines, i, m, channels[item], keys)
                        pending.discard(("ch", item))
                elif sub == "ch" and ind <= cind:
                    sub = None
                if mix_volume is not None and s.startswith("mix_volume:"):
                    lines[i] = re.sub(r"(mix_volume:\s*)\S+", rf"\g<1>{mix_volume}", line)
                    pending.discard(("mv",))
            i += n
        if ("mv",) in pending and 0 <= mod_line < len(lines) - 1 and re.match(r"^module:\s*$", lines[mod_line]):
            ind = len(lines[mod_line + 1]) - len(lines[mod_line + 1].lstrip())
            lines.insert(mod_line + 1, " " * ind + f"mix_volume: {mix_volume}\n")
            pending.discard(("mv",))
        if pending:
            return api.to_yaml(song), True
        return "".join(lines), False

    def patched_text(self, cand):
        """Song text with the slot pointed at `cand` (see _edit_text)."""
        import copy
        song = copy.deepcopy(self.song)
        entry = api.swap_sample(song, self.slot, cand)
        entry["file"] = os.path.relpath(cand, self.base_dir).replace(os.sep, "/")
        return self._edit_text(song, samples={self.slot: entry})

    def mix_text(self):
        """Song text with the unwritten mix written in: module.channels volume/pan, module.mix_volume, the samples'
        global_volume (the default note volume would be overridden by every cell that sets one) and the instrument panel's
        fields on their instruments."""
        import copy
        mix, song = self.mix(), copy.deepcopy(self.song)
        chans = song["module"]["channels"]
        if isinstance(chans, int):
            chans = song["module"]["channels"] = [{"name": f"Ch {i + 1}"} for i in range(chans)]
        touched = {}
        for k in ("volume", "pan"):
            for i, v in (mix.get(k) or {}).items():
                if int(i) < len(chans):
                    chans[int(i)] = touched[int(i)] = {**(chans[int(i)] or {}), k: v}
        if mix.get("mix_volume") is not None:
            song["module"]["mix_volume"] = mix["mix_volume"]
        smp = {}
        for s, g in (mix.get("sample_volume") or {}).items():
            if int(s) in song["samples"]:
                song["samples"][int(s)]["global_volume"] = g
                smp[int(s)] = song["samples"][int(s)]
        ins = {}
        for n, edit in (mix.get("instrument") or {}).items():
            if int(n) in (song.get("instruments") or {}):
                song["instruments"][int(n)] = ins[int(n)] = voice_entry(song["instruments"][int(n)], edit)
        new, redump = self._edit_text(song, samples=smp, channels=touched, mix_volume=mix.get("mix_volume"),
                                     keys=("volume", "pan", "global_volume"), instruments=ins)
        score_changed = False
        for track in song.get('score', {}).get('tracks', {}).values():
            midi = track.get('midi', {})
            for field in ('pan', 'volume'):
                touched_channels = {int(ch) for ch in mix.get(field, {})}
                if 'source_' + field in midi and touched_channels.intersection(track['channels']):
                    del midi['source_' + field]
                    score_changed = True
        if score_changed:
            new = replace_values(new, [(('score',), song['score'])])
        return new, redump

    def _diff(self, new, redump):
        d = list(difflib.unified_diff(self.text.splitlines(), new.splitlines(), self.song_path.name, self.song_path.name, lineterm="", n=2))
        return {"lines": d, "redump": redump, "path": str(self.song_path)}

    def diff(self, cand):
        return self._diff(*self.patched_text(cand))

    def mix_diff(self):
        return self._diff(*self.mix_text())

    def apply(self, cand):
        """The slot pointed at `cand` in the song file: the way every edit is written (refused while the song changed on
        disk, compiled whole first, one undo step)."""
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the write does not overwrite that change")
            new, _ = self.patched_text(cand)
            loaded = load_for_state(new, self.base_dir, str(self.song_path))  # SongError: nothing is written
            meta = copy.deepcopy(self.meta)
            meta['candidates'].pop(str(self.slot), None)
            meta['selected_candidate'] = None
            self._commit(new, loaded, meta=meta)
            if self.want == cand:
                self.want = None
        self._put(0, ("build", False))

    def apply_mix(self):
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the write does not overwrite that change")
            new, _ = self.mix_text()
            loaded = load_for_state(new, self.base_dir, str(self.song_path))
            self._commit(new, loaded, meta=dict(self.meta, mix={}))
        self._put(0, ("build", False))

    # ---- build / export

    def request_export(self, options, target='export_result'):
        from .export import prepare
        with self.lock:
            if self.export_job and self.export_job['result']['status'] in ('queued', 'rendering', 'publishing'):
                raise ValueError('An export is active; wait or cancel it first')
            job = prepare(self, options)
            self.export_job = job
            self.export_result = job['result']
            setattr(self, target, job['result'])
            self._put(0, ('export', job))

    def cancel_export(self):
        if self.export_job:
            self.export_job['cancel'].set()

    def request_build(self, render):
        # The legacy buttons now use the same immutable snapshot and safe publication as the export panel.
        try:
            self.request_export({'fmt': 'wav' if render else 'it', 'include_it': render, 'replace': True}, 'build')
        except (SongError, OSError, ValueError) as e:
            self.build = {'status': 'failed', 'error': str(e)}

    def _build(self, render):
        from .export import prepare, run
        try:
            job = prepare(self, {'fmt': 'wav' if render else 'it', 'include_it': render, 'replace': True})
            self.build = run(job, _encode)
        except (SongError, OSError, ValueError) as e:
            self.build = {'status': 'failed', 'error': str(e)}

    def request_stems(self, fmt='wav', song=False, stems=True):
        try:
            self.request_export({'fmt': fmt, 'song': song, 'stems': stems, 'replace': True}, 'stems')
        except (SongError, OSError, ValueError) as e:
            self.stems = {'status': 'failed', 'error': str(e), 'dir': None}

    # ---- pattern editing: each edit is a small in-place change of the pattern's `data: |` rows (the other cells of a row,
    # its label, its comment and every other line stay as they are), checked by compiling the whole song before anything is
    # written; the song texts before each write are the undo history

    @staticmethod
    def _pattern_block(lines, name):
        """The literal block holding pattern `name`'s rows: (first line index, end index). The pattern is `name:` with a
        `data: |` under it, or `name: |` itself. ValueError when it is written another way (flow or quoted data)."""
        section, key_ind, i = None, None, 0
        while i < len(lines):
            line = lines[i]
            s, ind = line.strip(), len(line) - len(line.lstrip())
            if s and not s.startswith("#") and ind == 0:
                section = line.split(":")[0].strip()
            elif section == "patterns" and s and not s.startswith("#") and key_ind is None:
                m = re.match(r"^(\s+)(['\"]?)(.+?)\2\s*:\s*(\|[-+]?)?\s*(#.*)?$", line.rstrip("\n"))
                if m and m.group(3) == name:
                    key_ind = ind
                    if m.group(4):
                        return State._block_end(lines, i, ind)
            elif key_ind is not None:
                if s and ind <= key_ind:
                    break
                if re.match(r"^\s+data\s*:\s*\|[-+]?\s*(#.*)?$", line.rstrip("\n")):
                    return State._block_end(lines, i, ind)
            i += 1
        raise ValueError(f"pattern '{name}': its rows are not a literal block (data: |); edit it in the YAML")

    @staticmethod
    def _block_end(lines, i, ind):
        j = i + 1
        while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > ind):
            j += 1
        while j > i + 1 and not lines[j - 1].strip():  # trailing blank lines are not the block's
            j -= 1
        return i + 1, j

    @staticmethod
    def _put_cell(line, ch, cell):
        """Row line `line` with channel `ch`'s cell replaced by `cell` (the note ins vol fx text); its neighbours keep their
        text and spacing; missing cells up to `ch` are filled with empty ones."""
        nl = "\n" if line.endswith("\n") else ""
        body, sc, comment = line.rstrip("\n").partition(";")
        m = re.match(r"^(\s*)(\d+\s*:)?(\s*\|?)(.*?)(\|?\s*)$", body)
        ind, label, pre, inner, post = m.group(1), m.group(2) or "", m.group(3), m.group(4), m.group(5)
        parts = inner.split("|") if inner.strip() else []
        while len(parts) <= ch:
            if parts and not parts[-1].endswith(" "):
                parts[-1] += " "
            parts.append(" ... .. ... ...")
        old = parts[ch]
        lead, trail = old[: len(old) - len(old.lstrip())], old[len(old.rstrip()):]
        if ch == 0 and not lead and label and not pre:
            lead = " "
        parts[ch] = f"{lead}{cell}{trail if trail or ch == len(parts) - 1 else ' '}"
        return f"{ind}{label}{pre}{'|'.join(parts)}{post}{sc}{comment}{nl}"

    def edit_cells(self, index, cells):
        """Write `cells` ([{row, ch, cell}], cell the 'C-5 01 v64 A06' text) into pattern `index` of the compiled song, in
        place, as one undoable step (see edit_patterns)."""
        self.edit_patterns([(index, cells)])

    def edit_patterns(self, groups, who=None, guard=None, *, occurrences=None, revision=None, transform=None):
        """Write each (pattern index, cells) of `groups` in place, all as one undoable step. The whole song is compiled
        first: an edit that breaks it is refused (SongError) and nothing is written. Refused too when the song changed on
        disk since it was read (reload first). `who` "agent": the patterns are marked `by: agent` (one that had notes
        and no mark becomes `you and agent`); the owner's edit of a pattern marked `agent` makes it `you and agent`."""
        with self.lock:
            self._writable()
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the edit does not overwrite that change")
            self._need_compiled()
            if self.mod.native_score is not None and revision != self.text_sha():
                raise ValueError('The song changed before this Pattern edit; refresh and try again')
            lines = self.text.splitlines(keepends=True)
            score = None
            residual = groups
            if self.mod.native_score is not None:
                from .tablature import translate_native_pattern_edits, transform_native_selections
                if transform is not None:
                    score, residual = transform_native_selections(self.song, self.mod.patterns, transform)
                    groups = residual
                else:
                    score, residual = translate_native_pattern_edits(self.song, self.mod.patterns, groups,
                                                                      occurrences=occurrences,
                                                                      view=self.mod.native_score['view'])
                for index, _ in groups:
                    name = self.mod.patterns[self.pattern_at(index)].name
                    if self.pattern_entry(name).get('approved'):
                        raise ValueError(f"pattern '{name}' is approved: clear its mark before editing")
            elif transform is not None:
                raise ValueError('exact selection transforms require a native score')
            elif self.mod.score_projection is not None:
                from .tablature import translate_pattern_edits
                score, residual = translate_pattern_edits(self.song, self.mod.score_projection, groups)
            for index, cells in residual:
                self._edit_block(lines, int(index), cells)
            for index in {int(i) for i, _ in groups}:
                pat = self.mod.patterns[index]
                cur = self.pattern_entry(pat.name).get("by")
                if who == "agent":
                    blank = (all(c.is_empty() for row in pat.rows for c in row) and
                             not self.song.get('score', {}).get('patterns', {}).get(pat.name, {}).get('beats'))
                    new = "agent" if cur == "agent" or (cur is None and blank) else "you and agent"
                else:
                    new = "you and agent" if cur == "agent" else cur
                if new != cur:
                    try:
                        self._pattern_mark(lines, pat.name, {"by": new})
                    except ValueError:  # a pattern written as one block carries no marks
                        pass
            new = "".join(lines)
            if score is not None:
                new = replace_values(new, [(('score',), score)])
            self._commit(new, guard=guard)  # compiled first (SongError: nothing is written)

    def score_view(self):
        """The saved score and its compiled links; the renderer owns no song or playback state."""
        from .tablature import Projection, raw_note_view, native_raw_note_view, measure_errors, tracker_staff_groups
        with self.lock:
            self._need_compiled()
            if self.mod.native_score is not None:
                view = copy.deepcopy(self.mod.native_score['view'])
                return {**view, "score": copy.deepcopy(self.song.get('score')), "revision": self.text_sha(),
                        "measure_errors": measure_errors(self.song, {p.name: len(p.rows) for p in self.mod.patterns}),
                        "title": self.song.get('score', {}).get('metadata', {}).get('title', self.mod.title), "song": str(self.song_path), "native": True,
                        "raw_positions": native_raw_note_view(self.song, self.mod.patterns, view=view),
                        "orders": list(self.song.get('orders') or []),
                        "pattern_names": [p.name for p in self.mod.patterns],
                        "rows": [len(p.rows) for p in self.mod.patterns],
                        "channels": [c.name for c in self.mod.channels], "tempo": self.mod.tempo,
                        "editable": not bool(self.read_only or self.dirty())}
            projection = self.mod.score_projection
            return {"score": self.song.get("score"), "revision": self.text_sha(),
                    "title": self.mod.title, "song": str(self.song_path),
                    "positions": projection.positions if projection else [],
                    "raw_positions": raw_note_view(self.song, projection or Projection(self.mod.patterns, self.mod.patterns)),
                    "diagnostics": projection.diagnostics if projection else [],
                    "orders": list(self.song.get("orders") or []),
                    "pattern_names": [p.name for p in self.mod.patterns],
                    "rows": [len(p.rows) for p in self.mod.patterns],
                    "channels": [c.name for c in self.mod.channels],
                    "row_step": [self.mod.speed, 24], "tempo": self.mod.tempo,
                    "rows_per_beat": self.mod.row_highlight[0] or 4,
                    "staff_groups": tracker_staff_groups(self.mod),
                    "editable": not bool(self.read_only or self.dirty())}

    def score_clipboard(self, body):
        from .tablature import capture_score_clipboard
        with self.lock:
            self._need_compiled()
            if body.get('revision') != self.text_sha():
                raise ValueError('The song changed before this copy; refresh and try again')
            model = self.mod if self.mod.native_score is not None else self.mod.score_projection
            if model is None:
                raise ValueError('score copy requires an existing score pattern name')
            raw = model.raw_patterns if hasattr(model, 'raw_patterns') else model.patterns
            return {'clipboard': capture_score_clipboard(self.song, body.get('pattern'), body.get('beats'),
                                                        body.get('occurrence'), selection=body.get('selection'),
                                                        raw_patterns=raw, complete_silence=True), 'revision': self.text_sha()}

    def pattern_clipboard(self, body, who=None, guard=None):
        """Capture first; publish a cut clipboard only after the one deletion commits."""
        from .tablature import capture_native_clipboard
        with self.lock:
            self._need_compiled()
            if self.mod.native_score is None:
                raise ValueError('native Pattern clipboard requires a score')
            if body.get('revision') != self.text_sha() or self.dirty():
                raise ValueError('The song changed before this copy; refresh and try again')
            cut = body.get('cut', False)
            if type(cut) is not bool:
                raise ValueError('cut must be a boolean')
            clipboard = capture_native_clipboard(self.song, self.mod.patterns, body['selection'])
            if cut:
                self.edit_patterns([], who=who, guard=guard, revision=body['revision'],
                                   transform=dict(action='cut', selections=[body['selection']]))
            return dict(ok=True, clipboard=clipboard, revision=self.text_sha())

    def paste_pattern_clipboard(self, body, who=None, guard=None):
        with self.lock:
            self.edit_patterns([], who=who, guard=guard, revision=body.get('revision'),
                               transform=dict(body, action='paste'))
            return dict(ok=True, revision=self.text_sha())

    def chord_suggestions(self, body, *, generate=False):
        """Read-only names or voicings against the open track's unoffset tuning."""
        from .chord_tools import generate_chords, recognize_chord
        from .tablature import _keys
        fields = (('spec', 'profile', 'min_fret', 'max_fret', 'open_strings', 'count') if generate
                  else ('chord', 'sharp', 'incomplete'))
        _keys(body, ('revision', 'track', *fields), 'chord suggestions')
        with self.lock:
            self._need_compiled()
            if self.dirty() or body.get('revision') != self.text_sha():
                raise ValueError('The song changed since this chord request; refresh and retry')
            identity = body.get('track')
            if not isinstance(identity, str):
                raise ValueError('Chord suggestions need a track ID')
            track = self.song.get('score', {}).get('tracks', {}).get(identity)
            if track is None:
                raise ValueError('Choose an existing TAB track')
            if generate:
                result = generate_chords(track, body.get('spec'),
                                         **{key: body[key] for key in fields if key != 'spec' and key in body})
                return dict(revision=self.text_sha(), track=identity, **result)
            proposals = recognize_chord(track, body.get('chord'), sharp=body.get('sharp', True),
                                        incomplete=body.get('incomplete', 4))
            return dict(revision=self.text_sha(), track=identity, proposals=proposals,
                        naming='Fret-shape names use track tuning without capo; scores are source heuristics, not probabilities.')

    def score_edit(self, edit, who=None, guard=None):
        """A native TAB edit is a single existing song/history transaction."""
        from .tablature import apply_score_edit, resize_beat, move_note, move_beat, promote_pattern, paste_score_clipboard, tempo_edit
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first")
            self._need_compiled()
            if edit.get("revision") != self.text_sha():
                raise ValueError("The song changed since this TAB edit; refresh and try again")
            name = edit.get("pattern")
            if type(name) is int:
                name = self.mod.patterns[self.pattern_at(name)].name
                if edit.get('op') not in ('beat_resize', 'note_move', 'beat_move', 'beats_paste'):
                    edit = {**edit, 'pattern': name}
            if name is not None and self.pattern_entry(name).get("approved"):
                raise ValueError(f"pattern '{name}' is approved: clear its mark in the SONG tab first")
            residual = []
            paste_report = {}
            model = self.mod if self.mod.native_score is not None else self.mod.score_projection
            if edit.get('op') == 'tempo_set':
                if self.mod.native_score is None:
                    raise ValueError('TAB tempo editing requires native score timing')
                residual = tempo_edit(self.song, self.mod.patterns,
                                      {k: v for k, v in edit.items() if k != 'revision'})
                if not residual:
                    return
                candidate = self.song
            elif edit.get('op') == 'notes_set':
                patches = edit.get('notes')
                if not isinstance(patches, list) or not 1 <= len(patches) <= 1024:
                    raise ValueError('notes_set requires 1..1024 note patches')
                candidate, seen = self.song, set()
                for patch in patches:
                    if (not isinstance(patch, dict) or set(patch) != {'beat', 'note'} or
                            not isinstance(patch.get('note'), dict)):
                        raise ValueError('each note patch needs a beat ID and note mapping')
                    identity = patch.get('beat'), patch['note'].get('id')
                    if not all(isinstance(key, str) for key in identity) or identity in seen:
                        raise ValueError('note patches need distinct beat/note identities')
                    seen.add(identity)
                    candidate = apply_score_edit(candidate, dict(op='note_set', pattern=name,
                                                                 beat=patch['beat'], note=patch['note']))
            elif edit.get('op') == 'promote_pattern':
                if model is None:
                    raise ValueError('Set up a TAB track before adopting Pattern notes')
                index = next((i for i, p in enumerate(self.mod.patterns) if p.name == name), None)
                if index is None:
                    raise ValueError('Choose an existing pattern to adopt')
                candidate, residual = promote_pattern(self.song, model, index, edit['track'], edit.get('cells'),
                                                       occurrence=edit.get('occurrence'))
            elif edit.get('op') == 'beat_resize':
                candidate = resize_beat(self.song, model, self.pattern_at(edit['pattern']),
                                        edit['beat'], edit['end_row'])
            elif edit.get('op') == 'note_move':
                candidate = move_note(self.song, model, self.pattern_at(edit['pattern']),
                                      edit['note'], edit['to_row'], edit.get('pitch'))
            elif edit.get('op') == 'beat_move':
                candidate = move_beat(self.song, model, self.pattern_at(edit['pattern']),
                                      edit['beat'], edit['to_row'])
            elif edit.get('op') == 'beats_paste':
                candidate = paste_score_clipboard(self.song, model, self.pattern_at(edit['pattern']),
                                                 edit['row'], edit['clipboard'], edit.get('occurrence'),
                                                 across=edit.get('across', False), replace=edit.get('replace', False),
                                                 track_map=edit.get('track_map'), mode=edit.get('mode'), voice_map=edit.get('voice_map'),
                                                 independent=edit.get('independent', False), report=paste_report)
            else:
                candidate = apply_score_edit(self.song, {k: v for k, v in edit.items() if k != 'revision'})
            if not residual and candidate['score'] == self.song.get('score'):
                return  # A semantic no-op must not reformat YAML or consume undo history.
            lines = self.text.splitlines(keepends=True)
            for index, cells in residual:
                raw_patterns = self.mod.patterns if self.mod.native_score is not None else self.mod.score_projection.raw_patterns
                self._edit_block(lines, index, cells, pat=raw_patterns[index])
            updates = [(('score',), candidate['score'])]
            if edit.get('op') == 'beats_paste':
                api.compile_song(candidate, self.base_dir)
                updates.extend((('patterns', name), entry) for name, entry in candidate['patterns'].items()
                               if name not in self.song['patterns'])
                if candidate['orders'] != self.song['orders']:
                    updates.append((('orders',), candidate['orders']))
            new = replace_values(''.join(lines), updates)
            loaded = load_for_state(new, self.base_dir, str(self.song_path))
            paste_selection = paste_report.get('selection')
            if paste_selection is None and edit.get('op') == 'beats_paste' and edit.get('occurrence') and loaded[0].native_score is not None:
                from .tablature import authoring_view, duration_quarters
                tracks = {(edit.get('track_map') or {}).get(b['track'], b['track']) for b in edit['clipboard']['beats']}
                if len(tracks) == 1:
                    track = next(iter(tracks))
                    view = authoring_view(candidate, loaded[0].patterns)
                    own = next(o for o in view['occurrences'] if o['id'] == edit['occurrence'])
                    row = Fraction(*edit['row']) if isinstance(edit['row'], list) else Fraction(edit['row'])
                    start = Fraction(*own['at']) + row * Fraction(*view['row_step'])
                    stop = start + max(Fraction(*b['at']) + duration_quarters(b['written'])
                                       for b in edit['clipboard']['beats'])
                    groups = []
                    for occurrence in view['occurrences']:
                        ids = [b['id'] for b in candidate['score']['patterns'].get(occurrence['pattern'], {}).get('beats', [])
                               if b['track'] == track and start <= Fraction(*occurrence['at']) + Fraction(*b['at']) < stop]
                        if ids:
                            groups.append(dict(occurrence=occurrence['id'], beats=ids))
                    first = next(o for o in view['occurrences'] if o['id'] == groups[0]['occurrence'])
                    at = start - Fraction(*first['at'])
                    paste_selection = dict(occurrence=first['id'], track=track,
                        voice=edit['clipboard']['beats'][0].get('voice', 0), at=[at.numerator, at.denominator],
                        beats=groups[0]['beats'], range=groups)
            old_score, new_score = self.song.get('score', {}), candidate['score']
            changed = set()
            for pi, pattern in enumerate(self.mod.patterns):
                before = old_score.get('patterns', {}).get(pattern.name)
                after = new_score.get('patterns', {}).get(pattern.name)
                if (before != after or pattern != loaded[0].patterns[pi] or
                        score_context(self.song, pattern.name) != score_context(candidate, pattern.name)):
                    changed.add(pattern.name)
                    if self.pattern_entry(pattern.name).get('approved'):
                        raise ValueError(f"pattern '{pattern.name}' is approved: clear its mark in the SONG tab first")
            if who == 'agent':
                lines = new.splitlines(keepends=True)
                for pi, pattern in enumerate(self.mod.patterns):
                    if pattern.name in changed:
                        current = self.pattern_entry(pattern.name).get('by')
                        blank = (all(c.is_empty() for row in pattern.rows for c in row) and
                                 not old_score.get('patterns', {}).get(pattern.name, {}).get('beats'))
                        mark = 'agent' if current == 'agent' or current is None and blank else 'you and agent'
                        self._pattern_mark(lines, pattern.name, {'by': mark})
                new = ''.join(lines)
            self._commit(new, loaded=loaded, guard=guard)

            if paste_selection is not None:
                return dict(ok=True, selection=paste_selection, revision=self.text_sha())

    def score_instrument(self, body, guard=None):
        """Bind an existing sound to a logical part, through the shared score and history."""
        with self.lock:
            if not isinstance(body, dict) or set(body) - {'revision', 'track', 'instrument', 'replace_overrides'}:
                raise ValueError('Part sound needs revision, track, instrument and optional replace_overrides')
            if self.dirty():
                raise ValueError('the song changed on disk: RELOAD first')
            self._need_compiled()
            if body.get('revision') != self.text_sha():
                raise ValueError('The song changed since this sound assignment; refresh and try again')
            if self.mod.native_score is None:
                raise ValueError('Part sound assignment requires native score timing')
            identity, number = body.get('track'), body.get('instrument')
            tracks = self.song['score']['tracks']
            if not isinstance(identity, str) or identity not in tracks:
                raise ValueError('Choose an existing score part')
            sounds = self.song.get('instruments') if self.mod.instruments is not None else self.song.get('samples')
            if type(number) is not int or number not in (sounds or {}):
                raise ValueError('Choose an existing instrument or sample slot from this song')
            replace = body.get('replace_overrides', False)
            if type(replace) is not bool:
                raise ValueError('replace_overrides must be boolean')
            candidate = copy.deepcopy(self.song)
            track = candidate['score']['tracks'][identity]
            track['instrument'] = number
            overrides = 0
            for pattern in candidate['score']['patterns'].values():
                for beat in pattern['beats']:
                    if beat['track'] != identity:
                        continue
                    for note in beat['notes']:
                        if 'instrument' in note:
                            overrides += 1
                            if replace:
                                del note['instrument']
            result = dict(ok=True, track=identity, instrument=number,
                          overrides_replaced=overrides if replace else 0,
                          overrides_preserved=0 if replace else overrides)
            if candidate == self.song:
                return dict(result, revision=self.text_sha(), report='Part sound is unchanged.')
            channels = set(track['channels'])
            for pattern in self.mod.patterns:
                if any(row[ch].note is not None and row[ch].note < 120 and not row[ch].instrument
                       for row in pattern.rows for ch in channels):
                    raise ValueError('Raw notes inherit sound memory on this part; give those notes explicit instruments first')
                if (score_context(self.song, pattern.name) != score_context(candidate, pattern.name) or
                        self.song['score']['patterns'].get(pattern.name) != candidate['score']['patterns'].get(pattern.name)):
                    if self.pattern_entry(pattern.name).get('approved'):
                        raise ValueError(f"pattern '{pattern.name}' is approved: clear its mark in the SONG tab first")
            # The native plan, tracker export and live engine all consume this same binding.
            api.compile_song(candidate, self.base_dir)
            new = replace_values(self.text, [(('score',), candidate['score'])])
            loaded = load_for_state(new, self.base_dir, str(self.song_path))
            self._commit(new, loaded=loaded, guard=guard)
            detail = f'{overrides} note sound overrides ' + ('replaced.' if replace else 'preserved.')
            return dict(result, revision=self.text_sha(), report=f'Assigned sound {number:02d} to {identity}. {detail}')

    def score_command(self, body, who='user', guard=None):
        """Score commands publish their result only after one guarded commit."""
        from .tablature import score_command, MEASURE_ACTIONS
        if body.get('action') in MEASURE_ACTIONS:
            return self.measure_edit(body, guard=guard)
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first")
            self._need_compiled()
            if body.get('revision') != self.text_sha():
                raise ValueError("The song changed since this TAB command; refresh and try again")
            if self.mod.native_score is None:
                raise ValueError('TAB commands require native score timing')
            candidate, result = score_command(self.song, self.mod.patterns, body)
            if body.get('action') == 'route_voices' and candidate != self.song:
                channels = self.song['score']['tracks'][body['track']]['channels']
                silenced, mix = set(self.silenced()), self.mix()
                states = {(ch in silenced, mix.get('volume', {}).get(str(ch), self.mod.channels[ch].volume),
                           mix.get('pan', {}).get(str(ch), self.mod.channels[ch].pan)) for ch in channels}
                if len(states) != 1:
                    raise ValueError('This part has different channel mix or mute settings; align them before separating voices')
                api.compile_song(candidate, self.base_dir)
            if candidate == self.song and list(candidate.get('score', {}).get('tracks', {})) == list(self.song.get('score', {}).get('tracks', {})):
                return dict(ok=True, **result, revision=self.text_sha())
            duration_edit = body.get('action') == 'set_duration'
            if body.get('action') == 'place':
                name = str(self.song['orders'][self.song['score']['order_ids'].index(body['occurrence'])])
                previous = next((b for b in self.song['score']['patterns'].get(name, {}).get('beats', [])
                                 if b['id'] == body['beat']['id']), None)
                duration_edit = previous is not None and previous['written'] != body['beat']['written']
            if body.get('action') in ('matrix_entry', 'shift_pitch', 'set_expression', 'cut', 'repeat', 'rest', 'delete', 'delete_beats', 'clean_beat', 'move_beats', 'transfer_voice', 'track_add', 'track_clone', 'track_remove', 'track_move') or duration_edit:
                # Single-beat and range duration edits promise the same exact standalone IT timing.
                api.compile_song(candidate, self.base_dir)
            changes = [(('score',), candidate['score'])]
            if candidate['module'] != self.song['module']:
                changes.append((('module',), candidate['module']))
            if candidate.get('instruments') != self.song.get('instruments'):
                changes.append((('instruments',), candidate['instruments']))
            changed = []
            for name, entry in candidate['patterns'].items():
                before = self.song['score']['patterns'].get(str(name))
                after = candidate['score']['patterns'].get(str(name))
                if (before != after or score_context(self.song, str(name)) != score_context(candidate, str(name))):
                    if self.pattern_entry(str(name)).get('approved'):
                        raise ValueError(f"pattern '{name}' is approved: clear its mark in the SONG tab first")
                    changed.append(str(name))
                if name not in self.song['patterns']:
                    changes.append((('patterns', name), entry))
            if candidate['orders'] != self.song['orders']:
                changes.append((('orders',), candidate['orders']))
            new = replace_values(self.text, changes)
            # A command may grow a pattern (free-edit Insert rest): its rows are written as the Song tab writes them.
            grown = [str(n) for n, e in candidate['patterns'].items() if n in self.song['patterns'] and isinstance(e, dict)
                     and isinstance(self.song['patterns'][n], dict) and e.get('rows') != self.song['patterns'][n].get('rows')]
            if grown:
                lines = new.splitlines(keepends=True)
                for n in grown:
                    self._song_op(lines, [str(o) for o in self.song['orders']],
                                  {'op': 'pattern_rows', 'name': n, 'rows': candidate['patterns'][n]['rows']}, [])
                new = ''.join(lines)
            if who == 'agent':
                lines = new.splitlines(keepends=True)
                for name in changed:
                    previous = self.pattern_entry(name).get('by')
                    old = self.song['score']['patterns'].get(name, {}).get('beats', [])
                    raw = next((p for p in self.mod.patterns if p.name == name), None)
                    blank = not old and (raw is None or all(c.is_empty() for row in raw.rows for c in row))
                    mark = 'agent' if previous == 'agent' or previous is None and blank else 'you and agent'
                    self._pattern_mark(lines, name, {'by': mark})
                new = ''.join(lines)
            loaded = load_for_state(new, self.base_dir, str(self.song_path))
            self._commit(new, loaded=loaded, guard=guard)
            return dict(ok=True, **result, revision=self.text_sha())

    def measure_edit(self, body, guard=None):
        """TuxGuitar's Measure menu (tablature.measure_command) as one undo step: new patterns are written as Song tab
        patterns are, the order list through arrangement.reorder (sections, jumps, the loop), then the score."""
        from .tablature import measure_command
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first")
            self._need_compiled()
            if body.get('revision') != self.text_sha():
                raise ValueError("The song changed since this TAB command; refresh and try again")
            if self.mod.native_score is None:
                raise ValueError('TAB commands require native score timing')
            raw = self.mod.score_projection.raw_patterns if self.mod.score_projection else self.mod.patterns
            raw_last = {p.name: max((r for r, row in enumerate(p.rows) if any(not c.is_empty() for c in row)), default=-1)
                        for p in raw}
            plan = measure_command(self.song, body, raw_last, raw)
            for name in plan['changed'] + plan['deleted'] + list(plan['resized']):
                if self.pattern_entry(name).get('approved'):
                    raise ValueError(f"pattern '{name}' is approved: clear its mark in the SONG tab first")
            before = [str(o) for o in self.song['orders']]
            lines, meta, orders = self.text.splitlines(keepends=True), copy.deepcopy(self.meta), list(before)
            if body.get('independent') or body.get('action') == 'prepare_measures':
                after = plan['orders']
                if after != before:
                    reorder(self, lines, before, after, plan['origins'], meta, widen=True, shrink=True)
                # Order indices alone cannot retain a loop inside a newly split pattern.
                # Carry its exact row endpoints through bar preparation and then the requested edit.
                if self.meta.get('loop'):
                    endpoints = {}
                    for side, (order, row) in self.meta['loop'].items():
                        position = plan['source_spans'][order] + row
                        if body.get('action') == 'measure_meter':
                            offset, mapped = 0, None
                            for index, name in enumerate(after):
                                count = plan['song']['patterns'][name]['rows']
                                if offset <= position < offset + count:
                                    mapped = [index, position - offset]
                                    break
                                offset += count
                        else:
                            old = next((i for i, (a, b) in enumerate(plan['source_bars']) if a <= position < b), None)
                            index = next((i for i, origin in enumerate(plan['bar_origins']) if origin == old), None) if old is not None else None
                            mapped = [index, position - plan['source_bars'][old][0]] if index is not None else None
                            if mapped and mapped[1] >= plan['song']['patterns'][after[index]]['rows']:
                                mapped = None
                        endpoints[side] = mapped
                    meta['loop'] = endpoints if all(endpoints.values()) and endpoints['from'] <= endpoints['to'] else None
                new = replace_values(''.join(lines), [(('patterns',), plan['song']['patterns']),
                    (('orders',), after), (('score',), plan['song']['score'])])
                if new == self.text:
                    return dict(ok=True, report=plan['report'], revision=self.text_sha())
                api.compile_song(api.from_yaml(new), self.base_dir)
                loaded = load_for_state(new, self.base_dir, str(self.song_path))
                self._commit(new, loaded=loaded, meta=meta, guard=guard)
                return dict(ok=True, report=plan['report'], revision=self.text_sha())
            for name, spec in plan['created'].items():
                self._song_op(lines, orders, {'op': 'pattern_clone', 'src': spec['clone'], 'name': name} if spec['clone']
                              else {'op': 'pattern_new', 'name': name, 'rows': spec['rows']}, [])
            for name, rows in plan['resized'].items():
                self._song_op(lines, orders, {'op': 'pattern_rows', 'name': name, 'rows': rows}, [])
            after = plan['orders']
            if after != before:
                reorder(self, lines, before, after, plan['origins'], meta, widen=True, shrink=True)
                self._write_orders(lines, after)
            for name in plan['deleted']:
                self._song_op(lines, after, {'op': 'pattern_delete', 'name': name}, [])
            new = replace_values(''.join(lines), [(('score',), plan['song']['score'])])
            if new == self.text:
                return dict(ok=True, report=plan['report'], revision=self.text_sha())
            api.compile_song(api.from_yaml(new), self.base_dir)
            loaded = load_for_state(new, self.base_dir, str(self.song_path))
            self._commit(new, loaded=loaded, meta=meta, guard=guard)
            return dict(ok=True, report=plan['report'], revision=self.text_sha())

    def pattern_entry(self, name):
        """The song file's entry of pattern `name` as a dict ({} when it is written as one block)."""
        pats = self.song.get("patterns") or {}
        e = next((v for k, v in pats.items() if str(k) == str(name)), None)
        return e if isinstance(e, dict) else {}

    def _pattern_mark(self, lines, name, fields):
        """Pattern `name`'s marks (`by`, `approved`) set in `lines`; a value of None or False removes the key."""
        j = self._pattern_key(lines, name)
        if lines[j].split("#")[0].split(":", 1)[1].strip():
            if self.mod is not None and self.mod.native_score is not None:
                current = api.from_yaml(''.join(lines))
                key = next(k for k in current['patterns'] if str(k) == str(name))
                entry = current['patterns'][key]
                if isinstance(entry, dict):
                    for field, value in fields.items():
                        if value is None or value is False:
                            entry.pop(field, None)
                        else:
                            entry[field] = value
                    lines[:] = replace_values(''.join(lines), [(('patterns', key), entry)]).splitlines(keepends=True)
                    return
            raise ValueError(f"pattern '{name}' is written as one block: give it 'rows:' and 'data: |' to mark it")
        kids = self._children(lines, j)
        ind = " " * (self._ind(lines[kids[0][0]]) if kids else self._ind(lines[j]) + 2)
        for key, value in fields.items():
            at = next((i for i, k in self._children(lines, j) if k == key), None)
            if value is None or value is False:
                if at is not None:
                    del lines[at]
                continue
            text = "true" if value is True else self._yname(str(value))
            if at is not None:
                lines[at] = f"{ind}{key}: {text}\n"
            else:
                lines.insert(j + 1, f"{ind}{key}: {text}\n")

    def materialize_pattern(self, index, guard=None):
        """Make the compiled cells explicit; one undo restores the original pattern notation."""
        with self.lock:
            self._need_compiled()
            idx = self.pattern_at(index)
            pat = (self.mod.score_projection.raw_patterns if self.mod.score_projection else self.mod.patterns)[idx]
            lines = self.text.splitlines(keepends=True)
            data = ''.join(f"{r:02d}: {' | '.join(format_cell(c) for c in row)}\n"
                           for r, row in enumerate(pat.rows))
            entry = {'rows': len(pat.rows), 'data': data}
            entry.update({k: v for k, v in self.pattern_entry(pat.name).items() if k in ('by', 'approved')})
            top = self._top(lines, 'patterns')
            if lines[top].split(':', 1)[1].strip().startswith('{'):
                key = next(k for k in self.song['patterns'] if str(k) == pat.name)  # `1:` is the int 1, compiled as '1'
                patterns = dict(self.song['patterns'])
                patterns[key] = entry
                lines[top:self._span(lines, top)] = api.to_yaml({'patterns': patterns}).splitlines(keepends=True)
            else:
                at = self._pattern_key(lines, pat.name)
                indent = ' ' * self._ind(lines[at])
                block = api.to_yaml({pat.name: entry})
                lines[at:self._span(lines, at)] = [indent + line + '\n' for line in block.splitlines()]
            self._commit(''.join(lines), guard=guard)

    def _need_compiled(self):
        if self.mod is None or self.error:
            raise ValueError("the song does not compile (RENDER & EXPORT lists the errors): fix it in the YAML first")

    def _edit_block(self, lines, index, cells, nch=None, pat=None):
        """`cells` written into pattern `index`'s rows in `lines` (in place). `nch`: the channel count when an edit of the
        same step added channels."""
        pat = pat or self.mod.patterns[self.pattern_at(index)]
        nch, nrows = nch or len(self.mod.channels), len(pat.rows)
        try:
            first, end = self._pattern_block(lines, pat.name)
        except ValueError:
            # Native score-only patterns commonly start with empty, inline data. Expand that raw source, not score cells.
            if self.mod.native_score is None:
                raise
            current = api.from_yaml(''.join(lines))
            entry = next(v for k, v in current['patterns'].items() if str(k) == pat.name)
            if not isinstance(entry, dict) or not isinstance(entry.get('data', ''), str):
                raise
            entry['data'] = (entry.get('data') or
                             ''.join(f"{r:02d}: {' | '.join(['... .. ... ...'] * nch)}\n" for r in range(nrows)))
            entry['data'] = entry['data'].rstrip('\n') + '\n'
            at = self._pattern_key(lines, pat.name)
            indent = ' ' * self._ind(lines[at])
            lines[at:self._span(lines, at)] = [indent + line + '\n' for line in api.to_yaml({pat.name: entry}).splitlines()]
            first, end = self._pattern_block(lines, pat.name)
        rows = [i for i in range(first, end) if lines[i].split(";", 1)[0].strip()]
        labels = [re.match(r"^\s*(\d+)\s*:", lines[i]) for i in rows]
        width, labelled = next((len(m.group(1)) for m in labels if m), 2), any(labels) or not rows
        ind = next((lines[i][: len(lines[i]) - len(lines[i].lstrip())] for i in range(first, end) if lines[i].strip()),
                   " " * (len(lines[first - 1]) - len(lines[first - 1].lstrip()) + 2))
        for c in sorted(cells, key=lambda c: int(c["row"])):
            r, ch, text = int(c["row"]), int(c["ch"]), str(c["cell"]).strip()
            if not (0 <= r < nrows and 0 <= ch < nch):
                raise ValueError(f"row {r}, channel {ch + 1} is outside pattern '{pat.name}' ({nrows} rows, {nch} channels)")
            if (r, ch) in getattr(pat, "lanes", {}):  # an automation lane's column: its value as compiled may pass (left out of the text,
                col, lane = pat.lanes[(r, ch)]  # the lane writes it), any other value is refused for every writer
                new, old = parse_cell(text), pat.rows[r][ch]
                if col == "v" and new.volcmd not in (None, old.volcmd) or col == "e" and (new.effect, new.param) not in ((0, 0), (old.effect, old.param)):
                    raise ValueError(f"pattern '{pat.name}', row {r}, channel {ch + 1}: the {'volume' if col == 'v' else 'effect'} "
                                     f"column is automation lane {lane}'s; change the lane (its 'automation:' entry), or MAKE "
                                     f"EDITABLE to turn the lanes into plain cells")
                text = format_cell(Cell(new.note, new.instrument, None if col == "v" else new.volcmd,
                                        new.effect if col == "v" else 0, new.param if col == "v" else 0))
            while len(rows) <= r:  # rows the block leaves implied (empty) are written out up to this one
                at = rows[-1] + 1 if rows else end
                label = f"{len(rows):0{width}d}: " if labelled else ""
                lines.insert(at, f"{ind}{label}{' | '.join(['... .. ... ...'] * nch)}\n")
                end += 1
                rows.append(at)
            lines[rows[r]] = self._put_cell(lines[rows[r]], ch, text)

    # ---- song structure: the order list, patterns, channels and module settings, edited in the song text in place (the
    # layout the songs use: `orders: [..]` on one line, patterns as `name:` + `rows:` + `data: |`, channels one `- {..}`
    # per line, module settings as `key: value` lines); a batch of ops is one undo step, compiled before it is written

    MODULE_KEYS = {"title": None, "key": None, "tempo": (32, 255), "speed": (1, 255), "global_volume": (0, 128), "mix_volume": (0, 128),
                   "separation": (0, 128), "rows_per_beat": (1, 255), "rows_per_bar": (1, 255), "message": None}

    @staticmethod
    def _block_scalar(key, value, ind):
        """`key: |` and `value` as a YAML literal block at indentation `ind`: `|-` without a final newline, `|+` keeping
        several, an indentation indicator when the first line starts with a space."""
        chomp = "" if value.endswith("\n") and not value.endswith("\n\n") else "+" if value.endswith("\n") else "-"
        body = (value[:-1] if value.endswith("\n") else value).split("\n")
        first = next((t for t in body if t.strip()), "")
        head = f"{' ' * ind}{key}: |{'2' if first.startswith(' ') else ''}{chomp}\n"
        return [head] + [f"{' ' * (ind + 2)}{t}\n" if t else "\n" for t in body]

    def _encoded(self, text, crlf=None, bom=None):
        crlf = self.crlf if crlf is None else crlf
        bom = self.bom if bom is None else bom
        return (b'\xef\xbb\xbf' if bom else b'') + text.replace('\n', '\r\n' if crlf else '\n').encode('utf-8')

    def _asset_paths(self, text, meta=None):
        paths = set()
        try:
            doc = api.from_yaml(text)
        except yaml.YAMLError:  # a song that is no valid YAML (a checkpoint brings back one that is): no files to name
            doc = None
        doc = doc if isinstance(doc, dict) else {}
        for entry in (doc.get('samples') or {}).values():
            if not isinstance(entry, dict) or not entry.get('file'):
                continue
            paths.add((self.base_dir / str(entry['file'])).resolve())
        meta = meta or {}
        for entries in (meta.get('candidates') or {}).values():
            paths.update((self.base_dir / p).resolve() for p in entries)
        if meta.get('selected_candidate'):
            paths.add((self.base_dir / meta['selected_candidate']).resolve())
        paths.update((self.base_dir / p).resolve() for p in (meta.get('phrase') or {}).get('assets', {}))
        return paths

    def _assets(self, text, meta=None):
        assets = {}
        for path in self._asset_paths(text, meta):
            if not path.is_file():
                assets[str(path)] = None  # relinking is allowed; restoring an originally missing asset is refused
                continue
            stat = path.stat()
            key = (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
            if key not in self._asset_hashes:
                self._asset_hashes[key] = digest(path.read_bytes())
            assets[str(path)] = self._asset_hashes[key]
        return assets

    def _step(self, meta=None, name=None, when=None):
        """The current song as an undo step, named for what moves away from it (the request's or agent tool's
        LABEL unless given) with the time it did."""
        return pack_step({'text': self.text, 'meta': copy.deepcopy(meta), 'assets': self._assets(self.text, meta),
                          'crlf': self.crlf, 'bom': self.bom, 'version': self.version(),
                          'name': str(name if name is not None else getattr(LABEL, 'name', None) or 'edit')[:80],
                          'time': when if when is not None else round(time.time(), 1)})

    def _check_assets(self, step):
        step = unpack_step(step)
        if 'text' in step:
            required = {str(p) for p in self._asset_paths(step['text'], step.get('meta'))}
            if not required.issubset(step.get('assets', {})):
                raise ValueError('Cannot restore: history is missing source asset fingerprints; compare the checkpoint text instead.')
        for path, expected in step.get('assets', {}).items():
            asset = self.base_dir / path
            if expected is None or not asset.is_file() or digest(asset.read_bytes()) != expected:
                raise ValueError(f'Cannot restore: source asset changed or is missing: {path}. Relink or restore the original asset first.')

    def _write_step(self, new, meta, history, future):
        self._writable()
        if self.dirty():
            raise ValueError('the song changed on disk: compare and RELOAD first')
        raw = self._encoded(new)
        saved, history, future = self.history_store.bounded(raw, history, future, self.checkpoints)
        self.history_store.write(raw, relative_meta(meta, self.base_dir), saved, lambda: self.write_song(new), self._raw)
        return history, future

    def checkpoint(self, name, action='save'):
        with self.lock:
            name = str(name).strip()
            if not name or len(name) > 80:
                raise ValueError('Give the checkpoint a name of 1-80 characters')
            if action != 'diff':
                self._writable()
            if self.dirty():
                raise ValueError('Compare and RELOAD external edits first')
            if action in ('diff', 'restore', 'delete') and name not in self.checkpoints:
                raise ValueError(f'No checkpoint named {name}')
            if action == 'diff':
                return self._diff(unpack_step(self.checkpoints[name])['text'], False)
            if action == 'restore':
                step = unpack_step(self.checkpoints[name])
                self._check_assets(step)
                self._commit(step['text'], meta=dict(self.meta, **(step.get('meta') or {})))
                return {}
            checkpoints = copy.deepcopy(self.checkpoints)
            if action == 'delete':
                del checkpoints[name]
            elif action == 'save':
                if name in checkpoints:
                    raise ValueError('A checkpoint with that name exists; choose another name')
                if len(checkpoints) >= 32:
                    raise ValueError('At most 32 checkpoints; delete one before saving another')
                checkpoints[name] = self._step(self._meta_view(), name)
            else:
                raise ValueError('unknown checkpoint action')
            try:
                data, history, future = self.history_store.bounded(self._raw, self.history, self.future, checkpoints)
            except ValueError:
                if action != 'delete':
                    raise
                # Legacy checkpoints may together exceed the new budget. Let each deletion reduce them.
                data = self.history_store.data(self._raw, self.history, self.future, checkpoints)
                history, future = self.history, self.future
            _atomic(self.history_store.path, data)
            self.history, self.future, self.checkpoints = history, future, checkpoints
            return {}

    def trim_history(self, keep=0):
        with self.lock:
            self._writable()
            if self.dirty():
                raise ValueError('Compare and RELOAD external edits first')
            if not str(keep).strip():  # an emptied field is no 0: CLEAR UNDO / REDO is the way to drop every step
                raise ValueError('Type how many recent undo steps to keep (0-200)')
            keep = int(keep)
            if not 0 <= keep <= self.UNDO_LIMIT:
                raise ValueError('Keep between 0 and 200 undo steps')
            history = self.history[-keep:] if keep else []
            data, history, future = self.history_store.bounded(self._raw, history, [], self.checkpoints)
            _atomic(self.history_store.path, data)
            self.history, self.future = history, future

    def relink_hints(self, lib, k=3):
        """For each sample slot whose file is missing, up to `k` WAVs of the same name (any case) in the sample library's
        index (`lib`, library.Library): first those whose contents match the digest an undo step recorded for the
        missing file ("same": the same file moved), then those sharing more of its folders. Nothing is relinked here.
        {"hints": {slot: [{"path", "same"}]}, "indexed": files in the index}."""
        with self.lock:
            missing = {int(n): (self.base_dir / str(v["file"])).resolve() for n, v in (self.song.get("samples") or {}).items()
                       if isinstance(v, dict) and v.get("file") and not (self.base_dir / str(v["file"])).is_file()}
            steps = list(self.history)
        with lib.lock:
            files = list(lib.data["files"])
        by_name = {}
        for p in files:
            by_name.setdefault(Path(p).name.lower(), []).append(Path(p))
        hints = {}
        for num, gone in missing.items():
            found = [p for p in by_name.get(gone.name.lower(), []) if p.is_file() and p.resolve() != gone]
            if not found:
                continue
            known = None
            for step in reversed(steps):  # the newest digest recorded while the file was there
                known = (unpack_step(step).get("assets") or {}).get(str(gone))
                if known:
                    break
            tail = lambda p: next((i for i, (a, b) in enumerate(zip(reversed(p.parts), reversed(gone.parts))) if a.lower() != b.lower()),
                                  min(len(p.parts), len(gone.parts)))
            same = {p: bool(known) and digest(p.read_bytes()) == known for p in found}
            found.sort(key=lambda p: (not same[p], -tail(p), str(p)))
            hints[num] = [{"path": str(p), "same": same[p]} for p in found[:k]]
        return {"hints": hints, "indexed": len(files)}

    def relink(self, num=None, path=None, links=None):
        with self.lock:
            moved = {}
            for num, path in (links if links is not None else {num: path}).items():
                num = int(num)
                entry = (self.song.get('samples') or {}).get(num)
                if not isinstance(entry, dict) or not entry.get('file'):
                    raise ValueError('Select a sample with a file to relink')
                path = (self.base_dir / str(path)).resolve()
                read_wav(path)
                try:
                    rel = Path(os.path.relpath(path, self.base_dir)).as_posix()
                except ValueError:
                    rel = path.as_posix()
                moved[num] = rel
            if not moved:
                raise ValueError('Provide replacement paths for the missing samples')
            self._commit(replace_values(self.text, file_updates(self.song, moved)))

    def external_diff(self):
        raw = self.song_path.read_bytes()
        text = raw.decode('utf-8-sig').replace('\r\n', '\n')
        return dict(self._diff(text, False), token=digest(raw))

    def _commit(self, new, loaded=None, meta=None, guard=None):
        """Compile, write, then publish one undo step. A failed write consumes no history or settings; an edit that
        changes nothing (channel 1 moved up) adds no step and keeps the redo steps. A `# written by VultureTracker`
        line naming another version is brought to this one (api.refresh_written_by; a song without one gets none)."""
        meta = copy.deepcopy(self.meta if meta is None else meta)
        if new == self.text and meta == self.meta:
            return
        new = api.refresh_written_by(new)  # a comment, in place: what `loaded` compiled stays line for line the same
        if loaded is not None and loaded[0].score_projection is not None:
            loaded = None
        loaded = loaded or load_for_state(new, self.base_dir, str(self.song_path))
        if loaded[0].native_score is not None:
            facts_of(*loaded)  # Validate derived State before any file/history publication.
        if guard is not None:
            guard(new, loaded, meta)
        changed = {k: copy.deepcopy(self.meta.get(k)) for k in self.META_KEYS if self.meta.get(k) != meta.get(k)}
        back = self._step(changed or None)
        history = (self.history + [back])[-self.UNDO_LIMIT:]
        self.history, self.future = self._write_step(new, meta, history, [])
        self.meta = meta
        self.want = meta.get("selected_candidate")
        self.reload(archive=False, loaded=loaded)

    META_KEYS = ("candidates", "muted", "solo", "mix", "orders", "loop", "phrase", "selected_candidate")  # the tryout settings a song write may change
    UNDO_LIMIT = 200     # undo steps kept (the oldest go first)

    def _meta_view(self):
        import copy
        return copy.deepcopy({k: self.meta.get(k) for k in self.META_KEYS})

    @staticmethod
    def _ind(line):
        return len(line) - len(line.lstrip())

    @staticmethod
    def _span(lines, i):
        """End (exclusive) of the entry whose key is on line i: up to the next line at its indentation or less; blank lines
        and outdented comments at the end belong to what follows."""
        ind, j = State._ind(lines[i]), i + 1
        while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("#") or State._ind(lines[j]) > ind):
            j += 1
        while j > i + 1 and (not lines[j - 1].strip() or (lines[j - 1].lstrip().startswith("#") and State._ind(lines[j - 1]) <= ind)):
            j -= 1
        return j

    @staticmethod
    def _top(lines, key):
        for i, line in enumerate(lines):
            if re.match(rf"^{re.escape(key)}\s*:", line):
                return i
        raise ValueError(f"the song has no top-level '{key}:'")

    @staticmethod
    def _children(lines, i):
        """(line index, key) of the entries directly under the mapping key on line i."""
        end, out, ind = State._span(lines, i), [], None
        for j in range(i + 1, end):
            s = lines[j].strip()
            if not s or s.startswith("#"):
                continue
            ind = State._ind(lines[j]) if ind is None else ind
            if State._ind(lines[j]) == ind:
                m = re.match(r"^\s*(['\"]?)(.+?)\1\s*:", lines[j])
                out.append((j, m.group(2) if m else None))
        return out

    @staticmethod
    def _yname(s):
        """`s` as a YAML scalar in a flow list or mapping: plain when that reads back as the same string, else quoted."""
        plain = (re.fullmatch(r"[A-Za-z_][\w .+()/'-]*|\+\+\+|---", s) and not s.endswith(" ")
                 and s.lower() not in ("true", "false", "yes", "no", "on", "off", "null", "y", "n"))
        return s if plain else json.dumps(s)

    def _pattern_key(self, lines, name):
        for j, k in self._children(lines, self._top(lines, "patterns")):
            if k == name:
                return j
        raise ValueError(f"no pattern '{name}'")

    @staticmethod
    def _row(line):
        """A row line as (head: indent, label and any leading pipe; the cells' texts with their spacing; tail: trailing
        pipe, spaces, comment, newline)."""
        nl = "\n" if line.endswith("\n") else ""
        body, sc, comment = line.rstrip("\n").partition(";")
        m = re.match(r"^(\s*)(\d+\s*:)?(\s*\|?)(.*?)(\|?\s*)$", body)
        return m.group(1) + (m.group(2) or "") + m.group(3), (m.group(4).split("|") if m.group(4).strip() else []), m.group(5) + sc + comment + nl

    @staticmethod
    def _rejoin(head, parts, cells, tail):
        """The row with `cells` (stripped texts) in the slots of `parts`, each slot keeping its spacing."""
        out = []
        for k, c in enumerate(cells):
            if k < len(parts):
                old = parts[k]
                out.append(old[: len(old) - len(old.lstrip())] + c + old[len(old.rstrip()):])
            else:
                if out and not out[-1].endswith(" "):
                    out[-1] += " "
                out.append(" " + c)
        return head + "|".join(out) + tail

    def _map_rows(self, lines, fn):
        """Every row of every pattern with its cells' texts passed through `fn` (a channel removed or moved)."""
        self._need_compiled()
        current = api.from_yaml(''.join(lines))
        channels = current['module']['channels']
        width = len(channels)
        mapped = fn(list(range(width)))
        automation = []
        for name, entry in current['patterns'].items():
            if isinstance(entry, dict):
                for index, lane in enumerate(entry.get('automation', [])):
                    channel = lane.get('channel', 1)
                    old = channel - 1 if type(channel) is int else next(i for i, c in enumerate(channels) if str(c.get('name', '')) == str(channel))
                    if old not in mapped:
                        raise ValueError(f"pattern '{name}': remove automation lane {index + 1} before deleting its channel")
                    if type(channel) is int:
                        target = mapped.index(old) + 1
                        if 'channel' in lane:
                            automation.append((('patterns', name, 'automation', index, 'channel'), target))
                        else:
                            automation.append((('patterns', name, 'automation', index), dict(lane, channel=target)))
                if not entry.get('data') and set(entry) <= {'rows', 'data', 'by', 'approved', 'automation'}:
                    continue  # Empty residual source; score and automation have their own mappings.
            elif not entry:
                continue
            first, end = self._pattern_block(lines, str(name))
            for i in range(first, end):
                if lines[i].split(";", 1)[0].strip():
                    head, parts, tail = self._row(lines[i])
                    cells = [p.strip() for p in parts]
                    cells += ['... .. ... ...'] * (width - len(cells))
                    lines[i] = self._rejoin(head, parts, fn(cells), tail)
        if automation:
            lines[:] = replace_values(''.join(lines), automation).splitlines(keepends=True)

    def _channel_lines(self, lines):
        mod = self._top(lines, "module")
        for j, k in self._children(lines, mod):
            if k == "channels":
                if lines[j].split("#")[0].split(":", 1)[1].strip():
                    raise ValueError("module.channels is written on one line: write one '- {name: ...}' per channel to edit channels here")
                # YAML permits the sequence dashes at the same indentation as `channels:` (our importer writes this).
                end, indent = j + 1, self._ind(lines[j])
                while end < len(lines):
                    text = lines[end].strip()
                    if text and not text.startswith('#') and (self._ind(lines[end]) < indent or
                            (self._ind(lines[end]) == indent and not text.startswith('- '))):
                        break
                    end += 1
                items = [i for i in range(j + 1, end) if lines[i].lstrip().startswith("-")]
                if any(not (entry := self._entry(lines[i], '-')) or not entry.group(4) for i in items):
                    raise ValueError("Use one-line '- {name: ..., pan: ..., volume: ...}' channel entries before editing channels here")
                return j, items
        raise ValueError("module has no 'channels:' list")

    def _song_op(self, lines, orders, op, remap):
        kind, E = op.get("op"), "... .. ... ..."
        if kind == "orders":
            orders[:] = [str(o) for o in op["orders"]]
        elif kind in ("pattern_new", "pattern_clone"):
            name = str(op["name"]).strip()
            if not re.fullmatch(r"[A-Za-z][\w.-]*", name):
                raise ValueError(f"'{name}': a pattern name starts with a letter (letters, digits, _ . -)")
            if any(k == name for _, k in self._children(lines, self._top(lines, "patterns"))):
                raise ValueError(f"there is already a pattern '{name}'")
            if kind == "pattern_clone":
                j = self._pattern_key(lines, op["src"])
                end = self._span(lines, j)
                block = lines[j:end]
                block[0] = re.sub(r"^(\s*)(['\"]?).+?\2(\s*:)", lambda m: m.group(1) + self._yname(name) + m.group(3), block[0], count=1)
                lines[end:end] = block
            else:
                top = self._top(lines, "patterns")
                kids = self._children(lines, top)
                ind = " " * (self._ind(lines[kids[0][0]]) if kids else 2)
                end = self._span(lines, top)
                rows = max(1, min(200, int(op.get("rows") or 64)))
                lines[end:end] = [f"{ind}{name}:\n", f"{ind}  rows: {rows}\n", f"{ind}  data: |\n"]
        elif kind == "pattern_rename":
            old, name = str(op["old"]), str(op["new"]).strip()
            if not re.fullmatch(r"[A-Za-z][\w.-]*", name):
                raise ValueError(f"'{name}': a pattern name starts with a letter (letters, digits, _ . -)")
            if name != old and any(k == name for _, k in self._children(lines, self._top(lines, "patterns"))):
                raise ValueError(f"there is already a pattern '{name}'")
            j = self._pattern_key(lines, old)
            lines[j] = re.sub(r"^(\s*)(['\"]?).+?\2(\s*:)", lambda m: m.group(1) + self._yname(name) + m.group(3), lines[j], count=1)
            orders[:] = [name if o == old else o for o in orders]
        elif kind == "pattern_split":  # OpenMPT's Split Pattern: the rows from `row` on become a new pattern, played after
            # each order that plays the source; sections around those orders widen to take it, jumps (Bxx) follow
            from types import SimpleNamespace
            self._need_compiled()
            idx = self.pattern_at(op["pattern"])
            pat = (self.mod.score_projection.raw_patterns if self.mod.score_projection else self.mod.patterns)[idx]
            row, n = int(op.get("row") or 0), len(pat.rows)
            if not 1 <= row < n:
                raise ValueError(f"split at a row from 1 to {n - 1}: the rows from it go to a new pattern")
            if self.pattern_entry(pat.name).get("approved"):
                raise ValueError(f"pattern '{pat.name}' is approved: clear its mark in the SONG tab before splitting it")
            names = {k for _, k in self._children(lines, self._top(lines, "patterns"))}
            new = next(f"{pat.name}_{i}" for i in itertools.count(2) if f"{pat.name}_{i}" not in names)
            self._song_op(lines, orders, {"op": "pattern_new", "name": new, "rows": n - row}, remap)
            self._edit_block(lines, None, [{"row": r - row, "ch": ch, "cell": format_cell(c)} for r in range(row, n)
                                           for ch, c in enumerate(pat.rows[r]) if not c.is_empty()],
                             pat=SimpleNamespace(name=new, rows=range(n - row)))
            self._song_op(lines, orders, {"op": "pattern_rows", "name": pat.name, "rows": row}, remap)
            k = orders.count(pat.name)
            orders[:] = [x for o in orders for x in ([o, new] if o == pat.name else [o])]
            self._report.append(f"split: '{pat.name}' keeps rows 0-{row - 1}, '{new}' has the {n - row} from row {row}, "
                                f"after each of its {k} order{'s' * (k != 1)}")
        elif kind == "pattern_automation":  # the pattern's `automation:` lanes replaced (none: the key goes); the compile
            # that follows checks them (song.py _lanes); the page has no lane editor, the agent's edit_pattern writes them
            name, lanes = str(op["name"]), op.get("lanes") or []
            if not isinstance(lanes, list) or not all(isinstance(x, dict) for x in lanes):
                raise ValueError("lanes is a list of {target, channel, rows, from, to, shape, every}")
            j = self._pattern_key(lines, name)
            if lines[j].split("#")[0].split(":", 1)[1].strip():
                raise ValueError(f"pattern '{name}' is written as one block: give it 'rows:' and 'data: |' first")
            kids = self._children(lines, j)
            ind = " " * (self._ind(lines[kids[0][0]]) if kids else self._ind(lines[j]) + 2)
            at = next((i for i, k in kids if k == "automation"), None)
            if at is not None:
                end = self._span(lines, at)
                while end < len(lines) and self._ind(lines[end]) == len(ind) and lines[end].lstrip().startswith("- "):
                    end += 1  # a list written at the key's own indentation
                del lines[at:end]
            if lanes:
                lines[j + 1:j + 1] = [f"{ind}automation:\n"] + [
                    f"{ind}  - {yaml.safe_dump(x, default_flow_style=True, sort_keys=False, width=1000).strip()}\n" for x in lanes]
            self._report.append(f"pattern '{name}': {len(lanes)} automation lane{'s' * (len(lanes) != 1)}")
        elif kind == "pattern_delete":
            name = str(op["name"])
            if name in orders:
                raise ValueError(f"pattern '{name}' is in the order list: take it out of the orders first")
            j = self._pattern_key(lines, name)
            del lines[j:self._span(lines, j)]
        elif kind == "pattern_rows":
            name, rows = str(op["name"]), max(1, min(200, int(op["rows"])))
            if self.mod is not None and self.mod.native_score is not None:
                current = api.from_yaml(''.join(lines))
                key = next(k for k in current['patterns'] if str(k) == name)
                entry = current['patterns'][key]
                if isinstance(entry, dict) and not entry.get('data'):
                    entry['rows'] = rows
                    lines[:] = replace_values(''.join(lines), [(('patterns', key), entry)]).splitlines(keepends=True)
                    return
            j = self._pattern_key(lines, name)
            kids = self._children(lines, j)
            at = next((i for i, k in kids if k == "rows"), None)
            if at is not None:
                lines[at] = re.sub(r"(rows\s*:\s*)\d+", rf"\g<1>{rows}", lines[at], count=1)
            elif kids:
                lines.insert(kids[0][0], f"{' ' * self._ind(lines[kids[0][0]])}rows: {rows}\n")
            else:
                raise ValueError(f"pattern '{name}' is written as one block: give it 'rows:' and 'data: |' in the YAML")
            first, end = self._pattern_block(lines, name)
            data = [i for i in range(first, end) if lines[i].split(";", 1)[0].strip()]
            for i in reversed(data[rows:]):  # rows past the new length go
                del lines[i]
        elif kind == "channel_rename":
            head, items = self._channel_lines(lines)
            i, name = self._chan(items, op["ch"]), str(op["name"]).strip()[:20]
            m = self._entry(lines[items[i]], "-")
            if not m or not m.group(4):
                raise ValueError(f"channel {i + 1} is not a one-line '- {{...}}' entry: rename it in the YAML")
            self._redump(lines, items[i], m, {"name": self._yname(name) if name else '""'}, keys=("name",))
        elif kind == "channel_color":  # `color: "#rrggbb"` on the channel's entry, for the app only; "" removes it
            head, items = self._channel_lines(lines)
            i, color = self._chan(items, op["ch"]), str(op.get("color") or "").strip().lower()
            m = self._entry(lines[items[i]], "-")
            if not m or not m.group(4):
                raise ValueError(f"channel {i + 1} is not a one-line '- {{...}}' entry: colour it in the YAML")
            if color and not re.fullmatch(r"#[0-9a-f]{6}", color):
                raise ValueError(f"a colour is #rrggbb, got {color!r}")
            if color:
                self._redump(lines, items[i], m, {"color": f'"{color}"'}, keys=("color",))
            else:
                lines[items[i]] = re.sub(r",\s*color:\s*['\"][^'\"]*['\"]|color:\s*['\"][^'\"]*['\"]\s*,?\s*", "", lines[items[i]], count=1)
        elif kind == "channel_add":
            head, items = self._channel_lines(lines)
            if len(items) >= 64:
                raise ValueError("IT has at most 64 channels")
            ind = " " * (self._ind(lines[items[-1]]) if items else self._ind(lines[head]) + 2)
            at = items[-1] + 1 if items else head + 1
            name = str(op.get("name") or f"Ch {len(items) + 1}").strip()[:20]
            pan = "" if op.get("pan") is None else f", pan: {max(0, min(64, int(op['pan'])))}"
            lines.insert(at, f"{ind}- {{name: {self._yname(name)}{pan}}}\n")
        elif kind == "channel_remove":
            head, items = self._channel_lines(lines)
            i = self._chan(items, op["ch"])
            if len(items) < 2:
                raise ValueError("a song needs a channel")
            self._map_rows(lines, lambda c: c[:i] + c[i + 1:])
            head, items = self._channel_lines(lines)
            del lines[items[i]]
            remap.append(lambda k: None if k == i else k - 1 if k > i else k)
        elif kind == "channel_move":
            head, items = self._channel_lines(lines)
            a, b = self._chan(items, op["ch"]), int(op["to"])
            if not (0 <= b < len(items)) or a == b:
                return
            lo, hi = min(a, b), max(a, b)

            def move(c):
                c = c + [E] * (hi + 1 - len(c))
                c.insert(b, c.pop(a))
                while len(c) > 1 and c[-1] == E:  # no trailing empty cells added
                    c.pop()
                return c
            self._map_rows(lines, move)
            head, items = self._channel_lines(lines)
            texts = [lines[k] for k in items]
            texts.insert(b, texts.pop(a))
            for k, t in zip(items, texts):
                lines[k] = t
            order = list(range(len(items)))
            order.insert(b, order.pop(a))
            remap.append(lambda k, order=order: order.index(k))
        elif kind == "echo":
            self._echo(lines, orders, op, remap)
        elif kind in ("groove", "accent", "euclid", "chord", "layers", "interpolate", "automate", "grow", "shrink", "arp", "fill",
                      "set_length", "cut_here", "glue"):
            self._compose(lines, op)
        elif kind == "render_sample":
            self._render_sample(lines, orders, op, remap)
        elif kind == "sample_slice":
            self._slice(lines, orders, op, remap)
        elif kind == "sf2_preset":
            self._sf2_preset(lines, orders, op, remap)
        elif kind == "sample_file":  # the slot pointed at another WAV (dropped on it), as the tryout's apply does it
            import copy
            num, f = int(op["num"]), Path(str(op["file"]))
            f = (f if f.is_absolute() else self.base_dir / f).resolve()
            if not f.exists():
                raise ValueError(f"no such WAV: {f}")
            f = self._wav_for_op(f)
            entry = api.swap_sample(copy.deepcopy(self.song), num, f)
            frames = len(read_wav(f).channels[0])
            for k in ("loop", "sustain_loop"):  # loop points past the new WAV's end go
                if isinstance(entry.get(k), dict) and int(entry[k].get("end", 0)) > frames:
                    del entry[k]
            try:
                entry["file"] = os.path.relpath(f, self.base_dir).replace(os.sep, "/")
            except ValueError:
                entry["file"] = f.as_posix()
            self._song_op(lines, orders, {"op": "sample_set", "num": num, "entry": entry}, remap)
        elif kind == "sample_delete":
            num = int(op["num"])
            j = next((j for j, k in self._children(lines, self._top(lines, "samples")) if k == str(num)), None)
            if j is None:
                raise ValueError(f"no sample {num}")
            del lines[j:self._span(lines, j)]
        elif kind == "sample_process":
            import numpy as np
            from .wavload import write_wav
            num = int(op["num"])
            entry, path, w, x = self._sample_wav(num)
            n = x.shape[1]
            a = max(0, min(n - 1, int(op.get("a") or 0)))
            b = max(a + 1, min(n, int(op["b"]) if op.get("b") is not None else n))
            y, loops = process_wav(x, str(op["action"]), a, b, entry_loops(entry, w), op.get("frames") or 0,
                                   op.get("params"), w.rate)
            full = 128 if w.out_bits == 8 else 32768
            peak = float(np.abs(y).max()) if y.size else 0.0
            if peak > 1:  # STRETCH, PITCH or a boost past full scale: scaled under it, never clipped
                y = y / peak
                self._report.append(f"{20 * math.log10(peak):.1f} dB down to stay under full scale")
            chans = np.clip(np.round(y * full), -full, full - 1).astype(np.int32).tolist()
            out = self._new_wav(path, str(op["action"]))
            self._created.append(out)  # before the write: a write that fails halfway is removed too
            write_wav(out, w.rate, chans, bits=w.out_bits, loop=loops.get("loop") or loops.get("sustain_loop"), root_note=w.root)
            try:
                rel = os.path.relpath(out, self.base_dir).replace(os.sep, "/")
            except ValueError:
                rel = out.as_posix()
            entry = dict(entry, file=rel)
            for k, lp in loops.items():
                if lp:
                    entry[k] = {"start": lp[0], "end": lp[1], **({"type": "pingpong"} if lp[2] else {})}
                else:
                    entry.pop(k, None)
            self._song_op(lines, orders, {"op": "sample_set", "num": num, "entry": entry}, remap)
        elif kind == "instruments_from_samples":
            # OpenMPT CModDoc::ConvertSamplesToInstruments: preserve sample-number assignments.
            if self.mod.instruments is not None:
                raise ValueError("the song already uses instruments")
            entries = {n: {"name": s.name, "fadeout": 8, **({"sample": n} if n in self.song.get("samples", {}) else {})}
                       for n, s in enumerate(self.mod.samples, 1)}
            block = api.to_yaml({"instruments": entries}).splitlines(keepends=True)
            try:
                top = self._top(lines, "instruments")
                lines[top:self._span(lines, top)] = block
            except ValueError:
                top = self._top(lines, "patterns")
                lines[top:top] = block
        elif kind in ("instrument_set", "instrument_new", "sample_new", "sample_set"):
            section = "samples" if kind.startswith("sample") else "instruments"
            try:
                top = self._top(lines, section)
            except ValueError:
                raise ValueError("the song has no instruments: its cells play samples directly") if section == "instruments" else None
            if lines[top].split("#")[0].split(":", 1)[1].strip() not in ("", "{}"):
                raise ValueError(f"{section} is written on one line: write one entry per line to edit it here")
            if lines[top].split("#")[0].split(":", 1)[1].strip() == "{}":
                lines[top] = f"{section}:\n"
            kids = [(j, int(k)) for j, k in self._children(lines, top) if k and k.isdigit()]
            if kind == "sample_set":
                num, entry = int(op["num"]), op["entry"]
                old = (self.song.get("samples") or {}).get(num)
                if not isinstance(entry, dict) or not isinstance(old, dict):
                    raise ValueError(f"no sample {num}" if not isinstance(old, dict) else "a sample entry is a mapping")
                if str(num) in (self.mix().get("sample_volume") or {}) and entry.get("global_volume") != old.get("global_volume"):
                    raise ValueError(f"slot {num} has an unwritten GAIN in the tryout's mixer: WRITE MIX or RESET MIX first")
                j = next((j for j, n in kids if n == num), None)
                m = self._entry(lines[j], r"\d+:")
                if m is None:
                    raise ValueError(f"sample {num} is written across several lines: write it on one line, or as a block, to edit it here")
                # a one-line entry whose changed values are all scalars (and none removed) keeps its layout: only those
                # values are replaced; anything else re-dumps the entry
                changed = [k for k in entry if entry[k] != old.get(k)]
                scalar = m.group(4) and not set(old) - set(entry) and all(isinstance(entry[k], (int, str)) for k in changed)
                if scalar:
                    self._redump(lines, j, m, {k: self._yname(v) if isinstance(v, str) else v for k, v in entry.items()}, keys=changed)
                else:
                    self._redump(lines, j, m, entry)
                return
            if kind == "sample_new":
                f = Path(str(op["file"]))
                f = f if f.is_absolute() else self.base_dir / f
                if not f.exists():
                    raise ValueError(f"no such WAV: {f}")
                f = self._wav_for_op(f)
                try:
                    rel = os.path.relpath(f.resolve(), self.base_dir).replace(os.sep, "/")
                except ValueError:
                    rel = f.resolve().as_posix()
                entry = {"file": rel, "name": it_text(op.get("name") or f.stem, 25), **({"stereo": True} if op.get("stereo") else {}),
                         **(op.get("keep") or {})}  # keep: settings carried over (a slice keeps its source's pitch)
            else:
                entry = op["entry"]
                if not isinstance(entry, dict):
                    raise ValueError("an instrument entry is a mapping")
            num = int(op.get("num") or max((n for _, n in kids), default=0) + 1)
            if kind == "instrument_set":
                if str(num) in (self.mix().get("instrument") or {}):
                    raise ValueError(f"instrument {num} has unwritten settings in the tryout's INSTRUMENT panel: WRITE or RESET them there first")
                j = next((j for j, n in kids if n == num), None)
                if j is None:
                    raise ValueError(f"no instrument {num}")
                m = self._entry(lines[j], r"\d+:")
                if m is None:
                    raise ValueError(f"instrument {num} is written across several lines: write it on one line, or as a block, to edit it here")
                self._redump(lines, j, m, entry)
            else:
                if any(n == num for _, n in kids):
                    raise ValueError(f"{section[:-1]} {num} exists already")
                if not 1 <= num <= 99:
                    raise ValueError("IT has at most 99 samples and 99 instruments")
                ind = " " * (self._ind(lines[kids[0][0]]) if kids else 2)
                after = [j for j, n in kids if n < num]
                at = self._span(lines, max(after)) if after else (kids[0][0] if kids else top + 1)
                flow = api.safe_dump(entry, default_flow_style=True, width=10 ** 6, sort_keys=False).strip()
                lines.insert(at, f"{ind}{num}: {flow}\n")
        elif kind == "instrument_delete":
            num = int(op["num"])
            j = next((j for j, k in self._children(lines, self._top(lines, "instruments")) if k == str(num)), None)
            if j is None:
                raise ValueError(f"no instrument {num}")
            del lines[j:self._span(lines, j)]
        elif kind == "plugins":  # module.plugins {number: entry} and/or module.macros {SFx: text}, each rewritten
            #                        whole (empty or null removes it): the rack's edits
            mod = self._top(lines, "module")
            if lines[mod].split("#")[0].split(":", 1)[1].strip():
                raise ValueError("module is written on one line: write it as a block to edit its plugins here")
            for key in ("plugins", "macros"):
                if key not in op:
                    continue
                value = op[key] or {}
                if key == "plugins":
                    value = {int(k): v for k, v in sorted(value.items(), key=lambda kv: int(kv[0]))}
                kids = self._children(lines, mod)
                ind = " " * (self._ind(lines[kids[0][0]]) if kids else 2)
                block = [f"{ind}{key}:\n"] + [
                    f"{ind}  {k}: " + (api.safe_dump(v, default_flow_style=True, width=10 ** 6, sort_keys=False).strip()
                                      if isinstance(v, dict) else self._yname(str(v))) + "\n" for k, v in value.items()]
                at = next((i for i, k in kids if k == key), None)
                if at is not None:
                    lines[at:self._span(lines, at)] = block if value else []
                elif value:
                    end = self._span(lines, mod)
                    lines[end:end] = block
        elif kind == "mark":  # `approved` (true/false) on a pattern, channel or sample (`what`, `key`); `by` on a pattern
            what, key = op.get("what"), op.get("key")
            if what == "pattern":
                self._pattern_mark(lines, str(key), {k: op[k] for k in ("approved", "by") if k in op})
            elif what == "channel":
                head, items = self._channel_lines(lines)
                i = self._chan(items, key)
                if op.get("approved"):
                    self._redump(lines, items[i], self._entry(lines[items[i]], "-"), {"approved": "true"}, keys=("approved",))
                else:
                    lines[items[i]] = re.sub(r",\s*approved:\s*\w+|approved:\s*\w+\s*,?\s*", "", lines[items[i]], count=1)
            elif what == "sample":
                entry = dict((self.song.get("samples") or {}).get(int(key)) or {})
                if not entry:
                    raise ValueError(f"no sample {key}")
                if op.get("approved"):
                    entry["approved"] = True
                else:
                    entry.pop("approved", None)
                self._song_op(lines, orders, {"op": "sample_set", "num": int(key), "entry": entry}, remap)
            else:
                raise ValueError("a mark goes on a pattern, a channel or a sample")
        elif kind == "channel_plugin":  # the plugin a channel plays through (0: none)
            head, items = self._channel_lines(lines)
            i, num = self._chan(items, op["ch"]), int(op.get("plugin") or 0)
            m = self._entry(lines[items[i]], "-")
            if num:
                self._redump(lines, items[i], m, {"plugin": num}, keys=("plugin",))
            else:
                lines[items[i]] = re.sub(r",\s*plugin:\s*\d+|plugin:\s*\d+\s*,?\s*", "", lines[items[i]], count=1)
        elif kind == "module":
            key, value = str(op["key"]), op["value"]
            if key not in self.MODULE_KEYS:
                raise ValueError(f"'{key}' is not a module setting edited here")
            rng = self.MODULE_KEYS[key]
            text = self._yname(str(value)[:25]) if rng is None else str(max(rng[0], min(rng[1], int(value))))
            mod = self._top(lines, "module")
            if lines[mod].split("#")[0].split(":", 1)[1].strip():
                raise ValueError("module is written on one line: write it as a block to edit its settings here")
            kids = self._children(lines, mod)
            at = next((i for i, k in kids if k == key), None)
            if key == "message":  # the song message, several lines: a literal block scalar, the text exactly as typed
                value = str(value).replace("\r\n", "\n").replace("\r", "\n")
                ind = self._ind(lines[kids[0][0]]) if kids else 2
                new = self._block_scalar(key, value, ind) if value else []
                if at is not None:
                    lines[at:self._span(lines, at)] = new
                else:
                    at = self._span(lines, mod)
                    lines[at:at] = new
                if value and (api.from_yaml("".join(lines)).get("module") or {}).get("message") != value:
                    lines[at:at + len(new)] = [f"{' ' * ind}message: {json.dumps(value)}\n"]  # what a block cannot hold
            elif at is not None:
                lines[at] = re.sub(rf"^(\s*{key}\s*:\s*)([^#\n]*?)(\s*(#.*)?\n?)$", lambda m: m.group(1) + text + m.group(3), lines[at])
            else:
                lines.insert(mod + 1, f"{' ' * (self._ind(lines[kids[0][0]]) if kids else 2)}{key}: {text}\n")
        else:
            raise ValueError(f"unknown song edit '{kind}'")

    # effects an echo copy leaves out: song-wide ones (speed, jumps, breaks, tempo, global volume, pattern loops and
    # delays), which would act twice, and pan (the echo channel's pan is its own, set on its fader)
    ECHO_SKIP = set("ABCTVWXY")
    ECHO_SKIP_S = {0x6, 0x8, 0x9, 0xB, 0xE}

    def _echo(self, lines, orders, op, remap):
        """The `echo` op: the notes of channel `ch` copied into channel `to` (or a new channel, `to` null: "<name> echo",
        added at the end) `rows` rows later and `ticks` ticks late (SDx on each note), each volume at `level` percent.
        `pattern`: a pattern index, with `r0`..`r1` its rows (default all); null: every pattern, whole. `pan`: the new
        channel's pan (0-64). A volume is the
        cell's own, else the one the note starts at (the sample's default volume when the cell names an instrument, else
        the channel's last); the echo channel's pan is its fader's, so pan commands are not copied, nor song-wide
        effects. A copy that lands past its pattern's end is dropped, and one onto a cell that is not empty is skipped,
        each counted in the report. Part of the song edit's one undo step."""
        from .model import Cell, NOTE_FADE
        self._need_tracker_operation('Echo')
        mod, nch = self.mod, len(self.mod.channels)
        src, delay, ticks = int(op["ch"]), int(op.get("rows") or 0), int(op.get("ticks") or 0)
        level = max(0.0, min(400.0, float(op.get("level", 60)))) / 100
        if not 0 <= src < nch:
            raise ValueError(f"no channel {src + 1}")
        if not (0 <= delay < 200 and 0 <= ticks <= 15) or delay + ticks == 0:
            raise ValueError("an echo is 0-199 rows and 0-15 ticks late, and later than the note")
        if ticks >= mod.speed:
            raise ValueError(f"at speed {mod.speed} a row has {mod.speed} ticks: a delay of {ticks} would skip the note")
        if op.get("to") is None:
            names = [c.name for c in mod.channels]
            base = f"{names[src]} echo"[:20]
            name = next(n for n in (base if k == 1 else f"{base[:17]} {k}" for k in itertools.count(1)) if n not in names)
            self._song_op(lines, orders, {"op": "channel_add", "name": name, "pan": op.get("pan")}, remap)
            to, width, new = nch, nch + 1, True
        else:
            to, width, new = int(op["to"]), nch, False
            if not 0 <= to < nch or to == src:
                raise ValueError("the echo goes into another channel of the song")
        insmode = mod.instruments is not None

        def default_volume(ins, note):
            if not ins:
                return None
            if insmode:
                if ins > len(mod.instruments) or note is None or note >= 120:
                    return None
                smp = mod.instruments[ins - 1].keymap[note][1]
            else:
                smp = ins
            return mod.samples[smp - 1].volume if 0 < smp <= len(mod.samples) else None

        def carry(c, vol, ins):  # the source channel's volume and instrument after cell c
            if c.instrument:
                ins, dv = c.instrument, default_volume(c.instrument, c.note)
                vol = dv if dv is not None else vol
            if c.volcmd is not None and c.volcmd <= 64:
                vol = c.volcmd
            return vol, ins

        # a pattern starts with the volume and instrument the channel has where it first plays (orders in turn, as the
        # sounding list reads them): a note there without an instrument plays the one carried over
        entry, vol, last_ins = {}, 64, 0
        for o in mod.orders:
            if o < len(mod.patterns):
                entry.setdefault(o, (vol, last_ins))
                for row in mod.patterns[o].rows:
                    vol, last_ins = carry(row[src], vol, last_ins)
        written = past = skipped = lost = 0
        idxs = [self.pattern_at(op["pattern"])] if op.get("pattern") is not None else range(len(mod.patterns))
        for idx in idxs:
            pat = mod.patterns[idx]
            n = len(pat.rows)
            r0 = max(0, int(op.get("r0") or 0)) if op.get("pattern") is not None else 0
            r1 = min(n - 1, int(op["r1"])) if op.get("pattern") is not None and op.get("r1") is not None else n - 1
            (vol, last_ins), cells = entry.get(idx, (64, 0)), []
            for r in range(0, r1 + 1):  # rows before r0 only set the channel's volume and instrument
                c = pat.rows[r][src]
                vol, last_ins = carry(c, vol, last_ins)
                if r < r0 or c.is_empty():
                    continue
                note_on = c.note is not None and c.note < 120
                e = Cell(c.note, last_ins if note_on else c.instrument, None, 0, 0)
                if c.volcmd is not None and c.volcmd <= 64 or note_on:
                    e.volcmd = max(0, min(64, round(vol * level)))
                elif c.volcmd is not None and not 128 <= c.volcmd <= 192:  # slides, portamento, vibrato; not pan
                    e.volcmd = c.volcmd
                letter = chr(64 + c.effect) if c.effect else ""
                keep = letter and letter not in self.ECHO_SKIP and not (letter == "S" and c.param >> 4 in self.ECHO_SKIP_S)
                if keep:
                    e.effect, e.param = c.effect, c.param
                if ticks and c.note is not None:
                    lost += bool(keep and not (letter == "S" and c.param >> 4 == 0xD))
                    e.effect, e.param = 19, 0xD0 | ticks  # SDx
                if e.is_empty():
                    continue
                at = r + delay
                if at >= n:
                    past += 1
                    continue
                if not new and not pat.rows[at][to].is_empty():
                    skipped += 1
                    continue
                if e.note == NOTE_FADE or e.note is not None and e.note >= 120:
                    e.instrument = 0
                cells.append({"row": at, "ch": to, "cell": format_cell(e)})
            if cells:
                self._edit_block(lines, idx, cells, width)
                written += len(cells)
        if not written:
            raise ValueError("nothing to echo: no notes on that channel in the rows given" + (
                f" ({past} would land past the pattern's end, {skipped} on cells that are not empty)" if past or skipped else ""))
        name = f"new channel {to + 1}" if new else f"channel {to + 1}"
        msg = f"echo of channel {src + 1} into {name}: {written} cells"
        msg += f", {past} past a pattern's end dropped" if past else ""
        msg += f", {skipped} skipped (the cell there was not empty)" if skipped else ""
        msg += f", {lost} effects replaced by the tick delay" if lost else ""
        self._report.append(msg)

    def render_rows(self, order, r0, r1, chans=None, tail=2.0):
        """Rows r0..r1 of the pattern at module order `order` rendered as they play in the song (everything before them
        sets the state: tempo, volumes, instruments), with the unwritten mix and the instrument panel, `chans` alone
        audible (None: the channels the mixer lets through), then `tail` seconds of the notes ringing on with nothing
        new struck; the ring-out ends at the first silence. Returns (int16 stereo PCM bytes, seconds of the rows)."""
        import numpy as np
        self._need_compiled()
        mod = self.mod
        if not (0 <= order < len(mod.orders) and mod.orders[order] < len(mod.patterns)):
            raise ValueError(f"order {order} plays no pattern")
        pat = mod.patterns[mod.orders[order]]
        r1 = min(int(r1), len(pat.rows) - 1)
        r0 = max(0, min(int(r0), r1))
        tail = max(0.0, min(10.0, float(tail)))
        nch = len(mod.channels)
        silenced = [c for c in range(nch) if c not in set(chans)] if chans is not None else self.silenced()
        if len(silenced) >= nch:
            raise ValueError("no channel to render: every one is muted or left out")
        if mod.native_score is not None:
            from .export import snapshot, render
            with self.lock:
                base, mix = copy.deepcopy(self.song), copy.deepcopy(self.mix())
            snap = snapshot(base, self.base_dir, region=(order, r0, order, r1), mix=mix,
                            muted=silenced, tail=tail)
            pcm = render(snap, cancel=lambda: self.closed)
            x = np.frombuffer(pcm, "<i2").reshape(-1, 2)
            rows_end = min(len(x), snap['frames'] - round(tail * RATE))
            loud = np.nonzero(np.abs(x[rows_end:].astype(np.int32)).max(axis=1) > 2)[0]
            return x[:rows_end + (loud[-1] + 1 if len(loud) else 0)].tobytes(), snap['seconds']
        with self.lock:
            base = api.tryout_song(self.song, (0, order + 1), compiled=self.mod)  # the orders up to this one, jumps kept inside them
            inst, mix = self.mix().get("instrument") or {}, self.mix()
        for n, edit in inst.items():
            if int(n) in (base.get("instruments") or {}):
                base["instruments"][int(n)] = voice_entry(base["instruments"][int(n)], edit)
        names = set(base["patterns"])
        rn = next(n for n in (f"render{k}" for k in itertools.count()) if n not in names)
        base["patterns"][rn] = {"rows": r1 + 1, "data": "\n".join(" | ".join(format_cell(c) for c in row)
                                                                  for row in pat.rows[:r1 + 1]) + "\n"}
        base["patterns"][rn + "_tail"] = {"rows": 200, "data": ""}  # 200 rows last 2 s at the fastest speed and tempo
        base["orders"] = list(base["orders"][:order]) + [rn] + [rn + "_tail"] * (1 + int(tail / 1.9))
        it = patch_it(api.compile_song(base, self.base_dir)[0], silenced, mix)
        with LoadedModule(it) as lm:
            end = lm.order_start(order + 1)
            start = lm.order_start(order, r0)  # the render starts here: libopenmpt plays the song up to it to get its state
            pcm = lm.render(RATE, max_seconds=end - start + tail)
        x = np.frombuffer(pcm, "<i2").reshape(-1, 2)
        rows_end = min(len(x), round((end - start) * RATE))
        loud = np.nonzero(np.abs(x[rows_end:].astype(np.int32)).max(axis=1) > 2)[0]  # the ring-out stops at its last frame above 2 LSB (int32: abs(-32768))
        return x[: rows_end + (loud[-1] + 1 if len(loud) else 0)].tobytes(), end - start

    def _render_sample(self, lines, orders, op, remap):
        """The `render_sample` op: render_rows of op's order, r0, r1, chans and tail, written as a WAV beside the song
        (stereo when the channels differ) and added as a new sample slot; part of the song edit's one undo step."""
        import numpy as np
        from .wavload import write_wav
        order, r0, r1 = int(op["order"]), int(op.get("r0") or 0), int(op.get("r1") if op.get("r1") is not None else 199)
        pcm, secs = self.render_rows(order, r0, r1, op.get("chans"), op.get("tail", 2.0))
        x = np.frombuffer(pcm, "<i2").reshape(-1, 2)
        if not x.any():
            raise ValueError("the render is silent: nothing plays on those rows and channels")
        stereo = bool((x[:, 0] != x[:, 1]).any())
        name = self.mod.patterns[self.mod.orders[order]].name
        stem = re.sub(r"[^\w.-]+", "_", f"{self.song_path.stem}-{name}-{r0}-{r1}")
        out = next(p for p in (self.base_dir / f"render-{stem}{'' if k == 1 else f'-{k}'}.wav" for k in itertools.count(1))
                   if not p.exists())
        self._created.append(out)
        write_wav(out, RATE, [x[:, c].tolist() for c in range(2 if stereo else 1)])
        num = max((int(k) for k in (self.song.get("samples") or {})), default=0) + 1
        self._song_op(lines, orders, {"op": "sample_new", "num": num, "file": str(out), "stereo": stereo,
                                      "name": f"{name} {r0}-{r1}"[:25]}, remap)
        self._report.append(f"rows {r0}-{min(r1, len(self.mod.patterns[self.mod.orders[order]].rows) - 1)} of "
                            f"'{name}' ({secs:.2f} s, {len(x) / RATE:.2f} s with the ring-out) rendered into new slot "
                            f"{num:02d}: {out.name}")

    def _slice(self, lines, orders, op, remap):
        """The `sample_slice` op: slot `num`'s WAV cut at `points` (start frames, ascending) up to `end` (default: the
        WAV's end), each slice written as its own WAV beside the song (a 1 ms fade at its end, so the cut does not click)
        and added as a new slot. `mode` kit (default): each slot keeps the source slot's pitch settings and, in a song
        with instruments, a new instrument plays slice 1 on C-5, slice 2 on C#5 and so on, each at its own pitch (a drum
        kit). `mode` multi: each slice's note is found (dsp.pitch_of; slices without one are left out), its slot tuned
        to the cent (c5_speed) and a new instrument plays each slice over the keys nearest its note (compose.key_splits),
        so a set of recorded notes becomes one playable instrument. `pattern`: also a new pattern (not in the order list)
        whose cells play the slices in order at their original timing at the song's tempo and speed (compose.slice_rows:
        rows plus SDx delays), from channel `ch`. One undo step."""
        import numpy as np
        from . import compose, dsp
        from .notation import format_note
        from .wavload import write_wav
        num, mode = int(op["num"]), op.get("mode") or "kit"
        if mode not in ("kit", "multi"):
            raise ValueError("slices become a kit (one per key from C-5) or a multisample (each around its note)")
        entry, path, w, x = self._sample_wav(num)
        n = x.shape[1]
        end = max(1, min(n, int(op.get("end") or n)))
        pts = sorted({int(p) for p in op.get("points") or [] if 0 <= int(p) < end})
        bounds = [(s, e) for s, e in zip(pts, pts[1:] + [end]) if e - s >= 32]
        have = sorted(int(k) for k in (self.song.get("samples") or {}))
        first = max(have, default=0) + 1
        insts = self.mod.instruments is not None
        if len(bounds) < 1:
            raise ValueError("no slices: give at least one start point before the end")
        if mode == "multi" and not insts:
            raise ValueError("a multisample is an instrument: this song plays samples directly (no instruments)")
        notes = [None] * len(bounds)
        if mode == "multi":
            for k, (s, e) in enumerate(bounds):
                hz = dsp.pitch_of(x[:, s:e], w.rate)
                if hz:
                    notes[k] = (hz, dsp.note_of(hz)[0])
            keep_k = [k for k, v in enumerate(notes) if v and 0 <= v[1] < 120]
            if not keep_k:
                raise ValueError("no slice holds a note to map (drums? slice them as a kit)")
        else:
            keep_k = list(range(len(bounds)))
        if first + len(keep_k) - 1 > 99:
            raise ValueError(f"{len(keep_k)} slices from slot {first} would pass slot 99: slice fewer, or clean up unused slots")
        if mode == "kit" and len(keep_k) > 120 - 60:
            raise ValueError("an instrument maps C-5 upwards: at most 60 slices")
        full = 128 if w.out_bits == 8 else 32768
        fade = min(max(1, w.rate // 1000), 32)
        keep = {k: entry[k] for k in ("base_note", "c5_speed", "volume", "global_volume", "stereo", "bits") if k in entry}
        stem = re.sub(r"-slice\d+(-\d+)?$", "", path.stem)
        nums, slot_of = [], {}
        for k in keep_k:
            s, e = bounds[k]
            y = x[:, s:e].copy()
            y[:, -fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
            out = next(p for p in (self.base_dir / f"{stem}-slice{k + 1:02d}{'' if j == 1 else f'-{j}'}.wav" for j in itertools.count(1))
                       if not p.exists())
            root = notes[k][1] if mode == "multi" else w.root
            self._created.append(out)
            write_wav(out, w.rate, np.clip(np.round(y * full), -full, full - 1).astype(np.int32).tolist(), bits=w.out_bits,
                      root_note=root)
            n_slot = first + len(nums)
            k_keep = dict(keep)
            name = f"{entry.get('name') or path.stem} {k + 1}"
            if mode == "multi":  # the note found plays true: C-5 at the rate that makes this slice sound C-5
                k_keep = {q: v for q, v in keep.items() if q not in ("base_note", "c5_speed")}
                k_keep["c5_speed"] = max(1, round(w.rate * 440 * 2 ** (-9 / 12) / notes[k][0]))
                name = f"{entry.get('name') or path.stem} {format_note(notes[k][1])}"
            self._song_op(lines, orders, {"op": "sample_new", "num": n_slot, "file": str(out), "keep": k_keep,
                                          "name": name[:25]}, remap)
            nums.append(n_slot)
            slot_of[k] = n_slot
        msg = f"slot {num:02d} cut into {len(bounds)} slices: slots {nums[0]:02d}-{nums[-1]:02d}"
        ins = None
        if insts:
            ins = max((int(i) for i in (self.song.get("instruments") or {})), default=0) + 1
            if mode == "multi":
                splits = compose.key_splits([notes[k][1] for k in keep_k])
                keymap = [{"notes": format_note(a) if a == b else f"{format_note(a)}..{format_note(b)}",
                           "sample": nums[i]} for i, a, b in splits]
                label = f"{entry.get('name') or path.stem} multi"
                msg += (f"; instrument {ins:02d} plays each over the keys nearest its note "
                        f"({', '.join(format_note(notes[keep_k[i]][1]) for i, _, _ in splits)})")
                if len(keep_k) < len(bounds):
                    msg += f"; {len(bounds) - len(keep_k)} without a note left out"
                if len(splits) < len(keep_k):
                    msg += f"; {len(keep_k) - len(splits)} repeating a note get a slot but no keys"
            else:
                keymap = [{"notes": format_note(60 + i), "sample": s, "play_note": "C-5"} for i, s in enumerate(nums)]
                label = f"{entry.get('name') or path.stem} slices"
                msg += f"; instrument {ins:02d} plays them from C-5 up"
            self._song_op(lines, orders, {"op": "instrument_new", "num": ins, "entry": {"name": it_text(label, 25), "keymap": keymap}}, remap)
        if op.get("pattern"):
            msg += "; " + self._slice_pattern(lines, orders, remap, [bounds[k][0] for k in keep_k], w.rate, nums,
                                              [notes[k][1] if mode == "multi" else 60 + i if ins else 60
                                               for i, k in enumerate(keep_k)],
                                              ins, int(op.get("ch") or 0), f"{stem}_slices", op.get("grid_bpm"))
        self._report.append(msg)

    def _slice_pattern(self, lines, orders, remap, starts, rate, nums, keys, ins, ch, base, grid_bpm=None):
        """A new pattern that plays the slices (their start frames `starts` in the source, their slots `nums`, played
        with instrument `ins` on `keys`, or each slot at C-5 in a song without instruments) in order at their original
        timing, from channel `ch`, or with `grid_bpm` (the sample's tempo) each on the row its beat reaches at the song's
        rows per beat; not added to the order list. Returns the report's words."""
        from . import compose
        from .model import Cell
        from .notation import format_cell
        mod = self.mod
        nch = len(mod.channels)
        ch = max(0, min(nch - 1, ch))
        if grid_bpm is not None and not 20 <= float(grid_bpm) <= 999:
            raise ValueError("the sample's BPM is 20 to 999")
        beat_grid = (float(grid_bpm), mod.row_highlight[0] or 4) if grid_bpm else None
        placed, rows, dropped = compose.slice_rows(starts, rate, mod.tempo, mod.speed, ch, nch, grid=beat_grid)
        if any(delay > 15 for _, _, _, delay in placed):
            raise ValueError('Slice timing needs a delay above 15 ticks; choose a song speed of 16 or less before creating a pattern')
        name = re.sub(r"[^\w.-]+", "_", base)
        name = name if re.match(r"[A-Za-z]", name) else "s" + name
        names = {k for _, k in self._children(lines, self._top(lines, "patterns"))}
        name = next(c for c in (name if k == 1 else f"{name}{k}" for k in itertools.count(1)) if c not in names)
        rows = max(rows, 1)
        self._song_op(lines, orders, {"op": "pattern_new", "name": name, "rows": rows}, remap)
        grid = [["... .. ... ..."] * nch for _ in range(rows)]
        for k, row, c, delay in placed:
            cell = Cell(note=keys[k], instrument=ins if ins else nums[k], effect=compose.S_EFFECT if delay else 0,
                        param=0xD0 | delay if delay else 0)
            grid[row][c] = format_cell(cell)
        first, _ = self._pattern_block(lines, name)
        ind = " " * (self._ind(lines[first - 1]) + 2)
        lines[first:first] = [f"{ind}{r:02d}: {' | '.join(cells)}\n" for r, cells in enumerate(grid)]
        words = (f"pattern '{name}' plays them on the song's grid ({rows} rows, the sample at {float(grid_bpm):g} BPM; "
                 if beat_grid else f"pattern '{name}' plays them at their timing ({rows} rows at tempo {mod.tempo} speed {mod.speed}; ")
        words += "not in the order list: INSERT it in the Song tab)"
        if dropped:
            words += f", {len(dropped)} left out (past 200 rows, or every channel taken on their row)"
        return words

    def compose_cells(self, idx, op):
        """One pattern's cells for a composition op (the ops `_compose` writes; see there), computed on the compiled
        rows and not written: (cells, skipped, extra notes for the report). The agent's transform_patterns calls it too,
        so the page and the agent run one dispatch."""
        self._need_tracker_operation('Pattern transforms')
        from . import compose
        mod, kind, nch = self.mod, op["op"], len(self.mod.channels)
        whole = op.get("pattern") is None
        chans = [int(c) for c in op["chans"]] if op.get("chans") is not None else list(range(nch))
        ch = int(op.get("ch", chans[0] if chans else 0))
        if not chans or not all(0 <= c < nch for c in chans + [ch]):
            raise ValueError(f"the song has channels 1-{nch}")
        insmode = mod.instruments is not None

        def default_volume(cell):  # the volume a note without a volume command starts at: its sample's default
            if not cell.instrument:
                return None
            smp = cell.instrument
            if insmode:
                if cell.instrument > len(mod.instruments):
                    return None
                smp = mod.instruments[cell.instrument - 1].keymap[cell.note][1]
            return mod.samples[smp - 1].volume if 0 < smp <= len(mod.samples) else None

        def columns():  # [[channel, [fields 0-3]], ...]: the selection's columns per channel
            cols = [(int(c), [int(f) for f in fs]) for c, fs in op.get("cols") or []]
            if not cols or not all(0 <= c < nch and fs and all(0 <= f <= 3 for f in fs) for c, fs in cols):
                raise ValueError(f"{kind}: give the channels and their columns")
            return cols

        skipped, extra = 0, []
        rows = mod.patterns[idx].rows
        r0 = 0 if whole else max(0, int(op.get("r0") or 0))
        r1 = len(rows) - 1 if whole or op.get("r1") is None else min(len(rows) - 1, int(op["r1"]))
        if kind == "groove":
            cells, s = compose.groove(rows, chans, r0, r1, op.get("ticks") or [], mod.speed)
            skipped += s
        elif kind == "accent":
            cells, s = compose.accent(rows, chans, r0, r1, op.get("levels") or [], default_volume)
            skipped += s
        elif kind == "euclid":
            if not 1 <= int(op["steps"]) <= 64:
                raise ValueError("a Euclidean rhythm has 1-64 steps")
            template = None
            if whole:  # the WHOLE SONG plays the cell at the top of the selection in the pattern it was made in
                src = mod.patterns[self.pattern_at(op.get("src", 0))].rows
                template = src[min(len(src) - 1, max(0, int(op.get("row") or 0)))][ch]
            cells = compose.euclid(rows, ch, r0, r1, int(op["hits"]), int(op["steps"]), int(op.get("rotate") or 0),
                                   int(op.get("every") or 1), float(op.get("prob", 100)), int(op.get("seed", 1)),
                                   [(int(h), int(s)) for h, s in op.get("cycles") or []], int(op.get("phrase") or 0),
                                   op.get("rules") or [], int(op.get("start") or 0), template, default_volume)
        elif kind == "chord":
            shape = op.get("shape") or "maj"
            cells = compose.chord(rows, ch, r0, r1, shape, int(op.get("inversion") or 0), nch)
            if int(op.get("strum") or 0):  # STRUM: the chord's voices delayed one after another, on the rows as written
                from .notation import parse_cell
                tmp = [list(rw) for rw in rows]
                for c in cells:
                    tmp[c["row"]][c["ch"]] = parse_cell(c["cell"])
                more, s, held = compose.strum(tmp, ch, r0, r1, len(compose._shape(shape)), int(op["strum"]),
                                              mod.speed, bool(op.get("down")))
                cells = list({(c["row"], c["ch"]): c for c in cells + more}.values())
                skipped += s
                if held:
                    extra.append(f"{held} voice{'s' * (held != 1)} held at {min(15, mod.speed - 1)} ticks (SDx goes "
                                 f"no further at speed {mod.speed})")
        elif kind in ("fill", "set_length", "cut_here", "glue"):
            name = mod.patterns[idx].name
            if self.pattern_entry(name).get("approved"):
                raise ValueError(f"pattern '{name}' is approved: its notes keep their lengths (clear its mark in the "
                                 "SONG tab first)")
            from .model import NOTE_CUT, NOTE_OFF
            off = NOTE_OFF if insmode else NOTE_CUT
            if kind == "fill":
                cells, _ = compose.fill(rows, chans, r0, r1)
            elif kind == "set_length":
                cells, s = compose.set_length(rows, chans, r0, r1, int(op.get("length") or 0), off)
                if s:
                    extra.append(f"{s} note{'s' * (s != 1)} would end past the pattern, left alone")
            elif kind == "cut_here":
                cells = compose.cut_here(rows, chans, r0, off)
            else:
                cells, _ = compose.glue(rows, chans, r0, r1)
        elif kind == "arp":
            from .model import NOTE_CUT, NOTE_OFF
            gate = op.get("gate") or 0
            cells = compose.arp(rows, ch, r0, r1, op.get("shape") or "maj", int(op.get("octaves") or 1),
                                op.get("direction") or "up", int(op.get("every") or 1),
                                gate if gate == "off" else int(gate), int(op.get("skip") or 0), int(op.get("seed", 1)),
                                NOTE_OFF if insmode else NOTE_CUT)
        elif kind == "interpolate":
            cols = columns()
            span = compose.sweep(rows, cols[0][0], r0, cols[0][1][0]) if op.get("sweep") else (r0, r1)
            cells = compose.interpolate(rows, cols, *span, default_volume) if span else []
        elif kind == "automate":
            cells, s = compose.automate(rows, chans, r0, r1, str(op.get("target")), int(op["from"]), int(op["to"]),
                                        op.get("shape") or "linear", int(op.get("every") or 1))
            skipped += s
        elif kind in ("grow", "shrink"):
            cols = columns()
            if kind == "grow":
                cells, lost, _ = compose.grow(rows, cols, r0, r1)
                if lost:
                    extra.append(f"{lost} row{'s' * (lost != 1)} past the pattern's end dropped")
            else:
                cells, _ = compose.shrink(rows, cols, r0, r1)
            if any(compose._is_delay(rows[r][c]) for r in range(r0, r1 + 1) for c, _ in cols):
                extra.append("note delays (SDx) keep their ticks")
        else:
            cells = compose.layers(rows, chans, r0, r1, op.get("instruments") or [], op.get("mode") or "cycle",
                                   default_volume)
        return cells, skipped, extra

    def _compose(self, lines, op):
        """The selection bar's composition ops (compose.py), written into the song text: `groove` (ticks: the per-row
        delays), `accent` (levels: the per-row volumes, 0-64 or "NN%") and `layers` (instruments, mode cycle / volume) over `chans` (None: every channel) in pattern `pattern`
        rows r0..r1, or in every pattern (pattern null); `euclid` (ch, hits, steps, rotate, every, prob, seed; cycles: more
        [hits, steps] layered, phrase rows, rules per phrase), in one pattern or, with pattern null, in every pattern the
        orders play, the phrases counted on from where each first plays (the cell at row `row` of pattern `src`); `chord`
        (ch, shape, inversion; strum ticks, down) and `arp` (ch, shape, octaves, direction, every, gate, skip, seed) in one
        pattern; `fill`, `set_length` (length), `cut_here` (r0: the row) and `glue` over `chans` in one pattern, which
        an approved pattern refuses; `interpolate` (cols: [[channel, [fields 0-3]], ...]; with `sweep`, the span
        found from row r0 in the one column, as OpenMPT does with no selection) and `automate` (chans, target, from, to,
        shape, every), `grow` and `shrink` (cols, OpenMPT's) in one pattern. Part of the song edit's one undo step, with a report of what changed."""
        self._need_compiled()
        mod, kind = self.mod, op["op"]
        whole = op.get("pattern") is None
        if whole and kind in ("chord", "interpolate", "automate", "grow", "shrink", "arp", "fill", "set_length",
                              "cut_here", "glue"):
            raise ValueError(f"{kind} works on a selection in one pattern")
        written = skipped = 0
        extra = []
        starts = {}  # euclid in the whole song: each played pattern and the row of the song where it first plays
        if whole and kind == "euclid":
            # ponytail: rows counted by pattern lengths, so a Bxx/Cxx that cuts a pattern short shifts later phrases
            t = 0
            for o in mod.orders:
                if o < len(mod.patterns):
                    starts.setdefault(o, t)
                    t += len(mod.patterns[o].rows)
        for idx in starts or (range(len(mod.patterns)) if whole else [self.pattern_at(op["pattern"])]):
            cells, s, more = self.compose_cells(idx, dict(op, start=starts[idx]) if starts else op)
            skipped += s
            extra += more
            if cells:
                self._edit_block(lines, idx, cells)
                written += len(cells)
        where = "the song" if whole else f"pattern '{mod.patterns[int(op['pattern'])].name}'"
        if not written:
            raise ValueError(f"{kind}: nothing to change in {where}" + (
                f" ({skipped} notes carry another effect, which a delay would replace)" if skipped and kind == "groove" else
                f" ({skipped} hold another command there)" if skipped else "") + (
                " (each column needs a value at an end of the selection, or with no selection the cursor between two)"
                if kind == "interpolate" else ""))
        msg = f"{kind}: {written} cell{'s' if written != 1 else ''} in {where}"
        msg += (f", {skipped} notes left undelayed (they carry another effect)" if kind == "groove" else
                f", {skipped} left alone (another command there)") if skipped else ""
        msg += "".join(f", {e}" for e in extra)
        self._report.append(msg)

    def _write_orders(self, lines, orders):
        """The order list `orders` written in `lines` in the layout it has: a one-line flow list stays one line (its
        trailing comment kept); a block list (`- name` per line) stays a block, each entry that survives keeping its line
        (its trailing comment) and the comment lines above it, new entries written in the block's indentation. A flow
        list written across several lines becomes one line, refused when comments inside it would be lost."""
        i = self._top(lines, "orders")
        head = lines[i].rstrip("\n")
        m = re.match(r"^orders\s*:\s*\[.*\]\s*(#.*)?$", head)
        if m:
            lines[i] = f"orders: [{', '.join(self._yname(o) for o in orders)}]" + (f"  {m.group(1)}" if m.group(1) else "") + "\n"
            return
        end = self._span(lines, i)
        body = lines[i + 1:end]
        if re.match(r"^orders\s*:\s*\[", head):  # a flow list across several lines
            if any("#" in x for x in [head] + body):
                raise ValueError("the order list is a flow list across several lines with comments in it: write it on one "
                                 "line, or as a block (one '- name' per line), to edit it here without losing them")
            lines[i:end] = [f"orders: [{', '.join(self._yname(o) for o in orders)}]\n"]
            return
        if head.split("#")[0].split(":", 1)[1].strip():
            raise ValueError("the order list is written in a way the app cannot edit in place: write it on one line")
        groups, pending = [], []  # (name, [comment lines above it + its own line])
        for line in body:
            s = line.strip()
            if not s or s.startswith("#"):
                pending.append(line)
                continue
            em = re.match(r"^\s*-\s*(['\"]?)(.*?)\1\s*(#.*)?$", line.rstrip("\n"))
            if not em or not em.group(2) or em.group(2).startswith(("[", "{")):
                raise ValueError("the order list has an entry the app cannot edit in place: write one '- name' per line")
            groups.append((em.group(2), pending + [line]))
            pending = []
        ind = next((g[1][-1][: self._ind(g[1][-1])] for g in groups), "  ")
        used, out = set(), []
        for name in orders:
            k = next((k for k, g in enumerate(groups) if g[0] == name and k not in used), None)
            if k is None:
                out.append(f"{ind}- {self._yname(name)}\n")
            else:
                used.add(k)
                out += groups[k][1]
        out += pending
        out = [x if x.endswith("\n") else x + "\n" for x in out]
        if body and not body[-1].endswith("\n") and out:  # the file ended without a newline: it still does
            out[-1] = out[-1][:-1]
        lines[i + 1:end] = out

    def section_edit(self, body, guard=None):
        with self.lock:
            self._need_compiled()
            name, action = str(body.get('name', '')).strip(), body.get('action', 'save')
            sections = copy.deepcopy(self.song.get('sections') or {})
            if action == 'save':
                sections[name] = [int(body['start']), int(body['end'])]
                self._commit(sections_text(self.text, sections), guard=guard)
                return
            if name not in sections:
                raise ValueError('Select a named section first')
            a, b = sections[name]
            if action == 'delete':
                del sections[name]
                self._commit(sections_text(self.text, sections), guard=guard)
                return
            if action == 'rename':
                new = str(body.get('new_name') or '').strip()
                if not new or len(new) > 80:
                    raise ValueError('Name the section 1-80 characters')
                if new in sections:
                    raise ValueError(f'A section is named {new} already')
                self._commit(section_renamed(self.text, name, new), guard=guard)
                return
            meta = copy.deepcopy(self.meta)
            if action in ('select', 'loop'):
                playable = [i for i, o in enumerate(self.facts['orders']) if a <= o['order'] < b]
                if not playable:
                    raise ValueError('The section has no playable orders')
                self._order_region([playable[0], playable[-1] + 1])
                meta['orders'] = [playable[0], playable[-1]+1]
                if action == 'loop':
                    meta['loop'] = {'from': [playable[0], 0], 'to': [playable[-1], self.facts['orders'][playable[-1]]['rows']-1]}
                self._commit(self.text, meta=meta, guard=guard)
                return
            before = [str(o) for o in self.song['orders']]
            at = int(body.get('to', len(before)))
            if not 0 <= at <= len(before):
                raise ValueError('Destination is an order boundary from 0 to the order count')
            lines = self.text.splitlines(keepends=True)
            clones = {}
            if action == 'move':
                if a <= at <= b:
                    return
                origins = [i for i in range(len(before)) if not a <= i < b]
                insert = at if at < a else at - (b-a)
                origins[insert:insert] = list(range(a, b))
                after = [before[i] for i in origins]
            elif action == 'duplicate':
                insert = at
                independent = bool(body.get('independent', True))
                names = set(self.song['patterns'])
                for src in dict.fromkeys(before[a:b]):
                    if src in ('+++', '---'):
                        continue
                    raw = self.song['patterns'][src]
                    empty = isinstance(raw, dict) and not raw.get('data')
                    first, end = (0, 0) if empty else self._pattern_block(lines, src)
                    if not independent and any(a <= int(m.group(1), 16) < b for line in lines[first:end]
                                              for m in api._JUMP.finditer(line.partition(';')[0])):
                        raise ValueError('Shared copy has jumps into its section; choose independent patterns to keep those jumps inside the copy')
                    if independent:
                        clone = next(n for n in (src + '_copy' + str(i) for i in itertools.count(1)) if n not in names)
                        names.add(clone)
                        self._song_op(lines, list(before), {'op': 'pattern_clone', 'src': src, 'name': clone}, [])
                        if 'score' in self.song:
                            from .tablature import apply_structure_edit
                            current = api.from_yaml(''.join(lines))
                            mapped = apply_structure_edit(current, {'op': 'pattern_clone', 'src': src, 'name': clone})
                            lines = replace_values(''.join(lines), [(('score',), mapped['score'])]).splitlines(keepends=True)
                        clones[src] = clone
                segment = [clones.get(p, p) for p in before[a:b]]
                after = before[:at] + segment + before[at:]
                origins = list(range(at)) + [None] * (b-a) + list(range(at, len(before)))
            else:
                raise ValueError('unknown section action')
            mapping = reorder(self, lines, before, after, origins, meta)
            if action == 'duplicate':
                for clone in clones.values():
                    raw = api.from_yaml(''.join(lines))['patterns'][clone]
                    if isinstance(raw, dict) and not raw.get('data'):
                        continue
                    first, end = self._pattern_block(lines, clone)
                    inside = {mapping[i]: insert + i-a for i in range(a, b)}
                    for i in range(first, end):
                        data, sep, comment = lines[i].partition(';')
                        lines[i] = api._JUMP.sub(lambda m: f'B{inside.get(int(m.group(1), 16), int(m.group(1), 16)):02X}', data) + sep + comment
                sections = api.from_yaml(''.join(lines)).get('sections') or {}
                new_name = str(body.get('new_name') or name + ' copy')
                if new_name in sections:
                    new_name = next(f'{new_name} {i}' for i in itertools.count(2) if f'{new_name} {i}' not in sections)
                sections[new_name] = [insert, insert + b-a]
                lines = sections_text(''.join(lines), sections).splitlines(keepends=True)
            if 'score' in self.song:
                from .tablature import apply_structure_edit
                current = api.from_yaml(''.join(lines))
                mapped = apply_structure_edit(current, {'op': 'orders', 'orders': after, 'origins': origins})['score']
                if action == 'duplicate':
                    copied = dict(zip(self.song['score']['order_ids'][a:b], mapped['order_ids'][insert:insert + b-a]))
                    for collection in ('ties', 'measures'):
                        used = {item.get('id') for item in mapped.get(collection, [])}
                        for item in self.song['score'].get(collection, []):
                            inside = [item[side]['occurrence'] in copied for side in ('from', 'to')]
                            if any(inside) and not all(inside):
                                raise ValueError(f'Section boundary crosses a score {collection[:-1]}; adjust its boundaries first')
                            if all(inside):
                                duplicate = copy.deepcopy(item)
                                for side in ('from', 'to'):
                                    duplicate[side]['occurrence'] = copied[item[side]['occurrence']]
                                if 'id' in duplicate:
                                    duplicate['id'] = next(f"{item['id']}_copy{i}" for i in itertools.count(1)
                                                           if f"{item['id']}_copy{i}" not in used)
                                    used.add(duplicate['id'])
                                mapped.setdefault(collection, []).append(duplicate)
                lines = replace_values(''.join(lines), [(('score',), mapped)]).splitlines(keepends=True)
            self._write_orders(lines, after)
            self._commit(''.join(lines), meta=meta, guard=guard)

    def _sf2_preset(self, lines, orders, op, remap):
        """The `sf2_preset` op: preset `preset` of bank `bank` (default 0) of the SoundFont `path` (or the GUS patch, a
        .pat) as a new instrument, read the way OpenMPT's loaders read them (sf2.py): its zones written as WAVs in a new folder beside the song
        (`<file stem>_<preset name>/`), each a new slot, and one instrument playing them over the bank's key ranges with the
        preset's envelope. One undo step; the WAVs go again when the edit is refused."""
        from . import sf2
        from .itreader import _safe, _sanitize, module_to_song
        try:  # the instruments as the text stands in this edit (the agent converts a sample-mode song in the same step)
            written = {int(k) for _, k in self._children(lines, self._top(lines, "instruments")) if str(k).isdigit()}
        except ValueError:
            written = set()
        if self.mod.instruments is None and not written:
            raise ValueError("a SoundFont preset is an instrument: this song plays samples directly (no instruments)")
        src = Path(str(op["path"]))
        src = src if src.is_absolute() else self.base_dir / src
        if not src.is_file():
            raise ValueError(f"no such SoundFont: {src}")
        mod, warnings = sf2.bank_module(src, int(op.get("preset") or 0), int(op.get("bank") or 0))
        _sanitize(mod, warnings)
        first = max((int(k) for k in (self.song.get("samples") or {})), default=0) + 1
        if first + len(mod.samples) - 1 > 99:
            raise ValueError(f"the preset's {len(mod.samples)} samples from slot {first} would pass slot 99")
        stem = f"{_safe(src.stem)}_{_safe(mod.instruments[0].name)}"
        folder = next(p for p in (self.base_dir / (stem if j == 1 else f"{stem}-{j}") for j in itertools.count(1)) if not p.exists())
        try:
            song = module_to_song(mod, self.base_dir / "song.yaml", folder)  # only its WAVs and entries are used
        finally:
            self._created.extend(sorted(folder.glob("*.wav")))
        for i, entry in sorted(song["samples"].items()):
            entry = dict(entry)
            file, name = self.base_dir / entry.pop("file"), entry.pop("name")
            self._song_op(lines, orders, {"op": "sample_new", "num": first + i - 1, "file": str(file), "name": name,
                                          "keep": entry}, remap)
        ins = dict(song["instruments"][1])
        if "sample" in ins:
            ins["sample"] += first - 1
        for e in ins.get("keymap") or []:
            e["sample"] += first - 1
        num = max({int(k) for k in (self.song.get("instruments") or {})} | written, default=0) + 1
        self._song_op(lines, orders, {"op": "instrument_new", "num": num, "entry": ins}, remap)
        self._report.append(f"instrument {num:02d} '{ins['name']}' from {src.name}, slots {first:02d}-{first + len(mod.samples) - 1:02d} "
                            f"in {folder.name}/: " + "; ".join(warnings))

    def _wav_for_op(self, f):
        """An edit's sound file as a WAV (as_wav); one written for it goes again when the edit is refused."""
        f, new = self.as_wav(f)
        if new:
            self._created.append(f)
        return f.resolve()

    def song_edit(self, ops, guard=None):
        """Apply `ops` (dicts with `op`: orders, pattern_new, pattern_clone, pattern_rename, pattern_delete, pattern_rows,
        pattern_split, channel_rename, channel_color, channel_add, channel_remove, channel_move, module, instrument_set / new / delete, sample_new,
        sample_set (the whole entry), sample_file (the slot pointed at another WAV), sample_delete, sample_process (an edit of the slot's audio written as a new WAV beside the song,
        the slot pointed at it), echo, groove, accent, euclid, chord, layers, arp, interpolate, automate, grow, shrink, fill,
        set_length, cut_here, glue, render_sample (rows rendered into a new slot), sample_slice, sf2_preset) to the song text as one undo step. The tryout's
        channel mutes and unwritten faders follow a channel that moves or goes; its section and loop are dropped when they
        fall outside a changed order list."""
        with self.lock:
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first, so the edit does not overwrite that change")
            lines = self.text.splitlines(keepends=True)
            meta = copy.deepcopy(self.meta)
            before = [str(o) for o in (self.song.get("orders") or [])]
            orders, remap = list(before), []
            self._created = []  # WAVs written by sample edits: removed again when the edit is refused
            self._report = []   # what an op tells the page (the echo's counts)
            try:
                for op in ops:
                    mapped_score = None
                    if 'score' in self.song and op.get('op') != 'mark':
                        from .tablature import apply_structure_edit
                        current = api.from_yaml(''.join(lines))
                        current['orders'] = list(orders)
                        operation = dict(op)
                        if op.get('op') == 'pattern_split':
                            pat = self.mod.patterns[self.pattern_at(op['pattern'])]
                            names = {k for _, k in self._children(lines, self._top(lines, 'patterns'))}
                            operation.update(name=pat.name, new=next(f'{pat.name}_{i}' for i in itertools.count(2)
                                                                    if f'{pat.name}_{i}' not in names))
                        mapped_score = apply_structure_edit(current, operation)['score']
                    self._song_op(lines, orders, op, remap)
                    if mapped_score is not None:
                        lines = replace_values(''.join(lines), [(('score',), mapped_score)]).splitlines(keepends=True)
                if orders != before:
                    explicit = [op['origins'] for op in ops if op.get('op') == 'orders' and 'origins' in op]
                    origins = explicit[-1] if explicit else (list(range(len(before))) if all(op.get('op') == 'pattern_rename' for op in ops)
                                                            else occurrence_map(before, orders))
                    # A replacement at one position (e.g. Make unique) retains that occurrence's identity.
                    if len(before) == len(orders):
                        origins = [i if o is None and i not in origins else o for i, o in enumerate(origins)]
                    reorder(self, lines, before, orders, origins, meta,
                            widen=any(op.get("op") == "pattern_split" for op in ops))  # a split's part joins its sections
                    self._write_orders(lines, orders)
                loaded = load_for_state("".join(lines), self.base_dir, str(self.song_path))
            except Exception:
                for f in self._created:
                    f.unlink(missing_ok=True)
                raise
            for f in remap:
                mix = meta.get("mix") or {}
                for k in ("volume", "pan"):
                    if mix.get(k):
                        mix[k] = {str(f(int(c))): v for c, v in mix[k].items() if f(int(c)) is not None}
                meta["muted"] = sorted(f(c) for c in meta.get("muted") or [] if f(c) is not None)
                if meta.get("solo") is not None:
                    meta["solo"] = f(meta["solo"])
            n = len(orders)
            if meta.get("orders") and meta["orders"][1] > n:
                meta["orders"] = None
            if meta.get("loop") and max(meta["loop"]["from"][0], meta["loop"]["to"][0]) >= n:
                meta["loop"] = None
            try:
                self._commit(''.join(lines), loaded, meta=meta, guard=guard)
            except Exception:
                for f in self._created:
                    f.unlink(missing_ok=True)
                raise
            return {"report": "; ".join(self._report)} if self._report else {}

    def undo(self, redo=False):
        """Back to the song text before the last write (or forward again). The tryout settings that write changed (mutes
        and faders following a channel that moved or went, the mix WRITE MIX cleared, the candidates U cleared, a section
        or loop dropped with the orders) go back with it, so a mute stays on the channel it was set on."""
        import copy
        with self.lock:
            src, dst = (self.future, self.history) if redo else (self.history, self.future)
            if not src:
                return
            if self.dirty():
                raise ValueError("the song changed on disk: RELOAD first (the undo history is for the song the app wrote)")
            step = unpack_step(src[-1])
            meta = step.get("meta")
            self._check_assets(step)
            back = self._step({k: self.meta.get(k) for k in meta} if meta else None, step.get('name', ''), step.get('time'))
            target = copy.deepcopy(self.meta)
            if meta:
                target.update(copy.deepcopy(meta))
            loaded = load_for_state(step['text'], self.base_dir, str(self.song_path))
            if loaded[0].native_score is not None:
                facts_of(*loaded)
            history, future = (dst + [back], src[:-1]) if redo else (src[:-1], dst + [back])
            self.history, self.future = self._write_step(step['text'], target, history, future)
            self.meta = target
            self.want = target.get("selected_candidate")
            self.reload(archive=False, loaded=loaded)

    # ---- sample editor

    def _sample_wav(self, num):
        entry = (self.song.get("samples") or {}).get(int(num))
        if not isinstance(entry, dict) or not entry.get("file"):
            raise ValueError(f"sample slot {num} has no WAV")
        path = (self.base_dir / str(entry["file"])).resolve()
        st = path.stat()
        return entry, path, *wav_array(str(path), (st.st_mtime, st.st_size))

    @property
    def takes_dir(self):
        return self.base_dir / "takes"

    def save_take(self, x, rate, opts=None):
        """A recorded take (float channels x frames) written as a 16-bit WAV in <song dir>/takes/<name>-NN.wav: its
        silent edges trimmed (`trim`, under `trim_db` dBFS, 10 ms kept before the first sound), its pitch found
        (`root`: written as the WAV's root note), then sent on (`dest`): `candidate` adds it to the slot's tryout
        candidates (U writes it, as with any candidate), `slot` adds a new sample slot tuned to the cent (its c5_speed
        makes the detected note play true), `keep` leaves it in the list. Returns the take's entry, newest first in
        State.takes."""
        import numpy as np
        from . import dsp
        from .notation import format_note
        from .wavload import write_wav
        opts = opts or {}
        if opts.get("trim", True):
            a, b = dsp.trim_edges(x, rate, float(opts.get("trim_db", -50)))
            if b <= a:
                raise ValueError(f"the take is silent (nothing above {opts.get('trim_db', -50)} dBFS): nothing saved")
            x = x[:, a:b]
        hz = dsp.pitch_of(x, rate) if opts.get("root", True) else None
        note, cents = dsp.note_of(hz) if hz else (None, 0.0)
        note = note if note is not None and 0 <= note < 120 else None
        self.takes_dir.mkdir(exist_ok=True)
        stem = re.sub(r"[^\w.-]+", "_", str(opts.get("name") or "take"))[:40] or "take"
        out = next(p for p in (self.takes_dir / f"{stem}-{k:02d}.wav" for k in itertools.count(1)) if not p.exists())
        pcm = np.clip(np.round(x * 32768), -32768, 32767).astype(np.int32).tolist()
        write_wav(out, rate, pcm, root_note=note)
        peak = float(np.abs(x).max())
        take = {"file": out.name, "path": str(out), "seconds": round(x.shape[1] / rate, 3), "channels": x.shape[0],
                "peak": round(20 * math.log10(peak), 1) if peak > 0 else None, "clipped": peak >= 0.999,
                "hz": hz or None, "note": format_note(note) if note is not None else None,
                "cents": round(cents), "rate": rate, "dest": None, "slot": None}
        self.takes.insert(0, take)
        return self.send_take(out.name, opts.get("dest") or "candidate")

    def send_take(self, name, dest):
        """Take `name` (of State.takes) sent on: `candidate` of the current slot, a new `slot` tuned to the cent (its
        c5_speed makes the detected note play true; a song with instruments gets one that plays it), or `keep`
        (nothing). Returns the take's entry."""
        take = next((x for x in self.takes if x["file"] == name), None)
        if take is None:
            raise ValueError(f"no take {name} in this session")
        out = Path(take["path"])
        if dest == "candidate":
            with self.lock:
                if str(out) not in self.cands():
                    self.cands().append(str(out))
                self.save_meta()
            take["slot"] = self.slot
            self.queue_all()
        elif dest == "slot":
            from .notation import parse_note
            num = max((int(k) for k in (self.song.get("samples") or {})), default=0) + 1
            keep = {"stereo": True} if take["channels"] == 2 else {}
            if take["hz"] and take["note"]:  # the detected note plays true: its speed scaled by the cents it was off
                note = parse_note(take["note"])
                keep["c5_speed"] = round(take["rate"] * 2 ** ((60 - note) / 12) * 440 * 2 ** ((note - 69) / 12) / take["hz"])
            ops = [{"op": "sample_new", "num": num, "file": str(out), "name": out.stem[:25], "keep": keep}]
            if self.song.get("instruments"):  # cells play instruments: one that plays the slot, else it cannot be heard
                take["instrument"] = max(int(i) for i in self.song["instruments"]) + 1
                ops.append({"op": "instrument_new", "num": take["instrument"], "entry": {"name": it_text(out.stem, 25), "sample": num}})
            self.song_edit(ops)
            take["slot"] = num
        elif dest != "keep":
            raise ValueError("a take goes to the slot's candidates, a new slot, or stays in the list")
        take["dest"] = dest
        return take

    def takes_multisample(self, names=None):
        """This session's takes that hold a note (or those in `names`) made one instrument: a new slot per take, tuned to
        the cent (its c5_speed plays the note found true), and a new instrument playing each over the keys nearest its
        note (compose.key_splits; a repeated note gets a slot but no keys). One undo step. Returns the report."""
        from . import compose
        from .notation import format_note, parse_note
        takes = [t for t in reversed(self.takes) if (names is None or t["file"] in names) and t.get("note") and t.get("hz")]
        if not takes:
            raise ValueError("no take holds a note: record single notes with FIND THE NOTE on")
        if not self.song.get("instruments"):
            raise ValueError("a multisample is an instrument: this song plays samples directly (no instruments)")
        num = max((int(k) for k in (self.song.get("samples") or {})), default=0) + 1
        if num + len(takes) - 1 > 99:
            raise ValueError(f"{len(takes)} takes from slot {num} would pass slot 99")
        ins = max(int(i) for i in self.song["instruments"]) + 1
        ops = []
        for k, t in enumerate(takes):
            keep = {"c5_speed": max(1, round(t["rate"] * 440 * 2 ** (-9 / 12) / t["hz"])), **({"stereo": True} if t["channels"] == 2 else {})}
            ops.append({"op": "sample_new", "num": num + k, "file": t["path"], "name": Path(t["file"]).stem[:25], "keep": keep})
        splits = compose.key_splits([parse_note(t["note"]) for t in takes])
        keymap = [{"notes": format_note(a) if a == b else f"{format_note(a)}..{format_note(b)}", "sample": num + i}
                  for i, a, b in splits]
        ops.append({"op": "instrument_new", "num": ins, "entry": {"name": "takes multi", "keymap": keymap}})
        self.song_edit(ops)
        for k, t in enumerate(takes):
            t.update(dest="multi", slot=num + k, instrument=ins)
        rep = (f"{len(takes)} takes in slots {num:02d}-{num + len(takes) - 1:02d}; instrument {ins:02d} plays each over the "
               f"keys nearest its note ({', '.join(takes[i]['note'] for i, _, _ in splits)})")
        return rep + (f"; {len(takes) - len(splits)} repeating a note get no keys" if len(splits) < len(takes) else "")

    def paint(self, body):
        """The PAINT tab (spectral.py): `action` preview (the picture played as sound: WAV bytes, peak at -1 dBFS),
        slot (written as a WAV beside the song, `paint-<name>.wav` with the picture as a PNG beside it, and added as a
        new slot, with an instrument in a song with instruments: one undo step), candidate (written the same way and
        added to the tryout slot's candidates), filter_preview (slot `num`'s WAV through the picture: WAV bytes) or filter
        (the same as an edit of slot `num`: a new WAV, one undo step). Returns bytes for the previews, else a report."""
        import numpy as np
        from . import spectral
        from .wavload import write_wav
        act = body.get("action")
        pic = paint_args(body)
        if act in ("filter", "filter_preview"):
            num = int(body["num"])
            if act == "filter":
                self.song_edit([{"op": "sample_process", "num": num, "action": "spectral_mask",
                                 "params": {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in pic.items() if k != "pan"}}])
                return {"report": f"slot {num:02d} filtered through the picture: {Path(self.current_file_of(num)).name}"}
            with self.lock:
                _, _, w, x = self._sample_wav(num)
            y = spectral.spectral_mask(x, w.rate, pic["amp"], pic["fmin"], pic["fmax"], pic["scale"], pic["range_db"])
            return _wav_bytes(y, w.rate)
        y, peak = spectral.paint_render(pic["amp"], pic["pan"], pic["seconds"], RATE, pic["fmin"], pic["fmax"],
                                        pic["scale"], pic["range_db"], int(body.get("seed") or 0))
        if peak <= 0:
            raise ValueError("paint: the picture is dark (nothing painted, or only above the 18 kHz ceiling)")
        y *= 0.891 / peak
        stereo = bool(np.abs(y[0] - y[1]).max() > 1e-6)
        y = y if stereo else y[:1]
        if act == "preview":
            return _wav_bytes(y, RATE)
        if act not in ("slot", "candidate"):
            raise ValueError("paint: preview, slot, candidate, filter or filter_preview")
        stem = re.sub(r"[^\w.-]+", "_", str(body.get("name") or "paint"))[:40] or "paint"
        out = next(p for p in (self.base_dir / f"paint-{stem}{'' if k == 1 else f'-{k}'}.wav" for k in itertools.count(1))
                   if not p.exists() and not p.with_suffix(".png").exists())
        write_wav(out, RATE, np.clip(np.round(y * 32768), -32768, 32767).astype(np.int32).tolist())
        out.with_suffix(".png").write_bytes(png_rgb(spectral.picture_png(pic["amp"], pic["pan"])))
        try:
            words = self.place_wav(out, act, stereo)
        except Exception:
            out.unlink(missing_ok=True)
            out.with_suffix(".png").unlink(missing_ok=True)
            raise
        return {"report": f"{out.name} ({pic['seconds']:.2f} s{', stereo' if stereo else ''}) {words}", "file": str(out)}

    def place_wav(self, out, dest, stereo=False):
        """A WAV the app wrote beside the song, sent on: `candidate` (added to the tryout slot's candidates) or `slot` (a
        new slot, with an instrument in a song with instruments: one undo step; its root note, from the WAV's smpl chunk,
        as the base note). Returns the report's words."""
        out = Path(out)
        if dest == "candidate":
            with self.lock:
                if str(out) not in self.cands():
                    self.cands().append(str(out))
                self.save_meta()
            self.queue_all()
            return f"added to slot {self.slot:02d}'s candidates"
        if dest != "slot":
            raise ValueError("a new WAV goes to the slot's candidates or a new slot")
        num = max((int(k) for k in (self.song.get("samples") or {})), default=0) + 1
        root = read_wav(out).root
        keep = {"base_note": format_note(root)} if root is not None and 0 <= root < 120 and root != 60 else {}
        ops = [{"op": "sample_new", "num": num, "file": str(out), "name": out.stem[:25], "stereo": stereo, "keep": keep}]
        if self.song.get("instruments"):
            ops.append({"op": "instrument_new", "num": max(int(i) for i in self.song["instruments"]) + 1,
                        "entry": {"name": it_text(out.stem, 25), "sample": num}})
        self.song_edit(ops)
        return f"in new slot {num:02d}" + (f", played by instrument {ops[1]['num']:02d}" if len(ops) > 1 else "")

    def faust_recipe(self, wav, faust):
        """The FAUST tab's save made reproducible: a `faust:` entry named after `wav` in faust.yaml beside the song (made
        when missing) that renders it again (the code, NOTE, HOLD, TAIL, VELOCITY and the sliders; no trim or fade, as the
        tab renders), so the RECIPE box shows it for the slot, renders it again and edits it. Returns the report's words."""
        from .synth import RecipeError, expand
        notes = [format_note(int(n)) for n in faust.get("notes") or []] or ["C-5"]
        spec = {"faust": str(faust.get("code") or ""), **({"chord": notes} if len(notes) > 1 else {"note": notes[0]}),
                "hold": float(faust.get("hold") or 1), "tail": float(faust.get("tail") or 0),
                "velocity": int(faust.get("velocity") or 100),
                **({"params": {str(k): float(v) for k, v in faust["params"].items()}} if faust.get("params") else {}),
                "trim": False, "fade_out": 0}
        path, name = self.base_dir / "faust.yaml", Path(wav).stem
        dump = lambda d: yaml.dump(d, Dumper=api._Dumper, sort_keys=False, width=120, allow_unicode=True)  # noqa: E731
        text = path.read_text(encoding="utf-8") if path.exists() else (
            "# Sounds saved from the FAUST tab: each entry renders its WAV again (SAMPLING.md, faust:)\nout_dir: .\nsamples:\n")
        try:
            doc = yaml.load(text, Loader=api._Loader)
            new = name not in ((doc or {}).get("samples") or {})
            if new:
                text += ("" if text.endswith("\n") else "\n") + "".join(f"  {line}\n" for line in dump({name: spec}).splitlines())
                doc = yaml.load(text, Loader=api._Loader)
                list(expand(doc))
        except (RecipeError, yaml.YAMLError, AttributeError) as e:
            return f" (its faust: entry was not written: {path.name}: {e})"
        if new:
            if (doc["samples"].get(name) != spec or list(doc).index("samples") != len(doc) - 1
                    or (self.base_dir / str(doc.get("out_dir", "."))).resolve() != self.base_dir.resolve()):
                return f" (its faust: entry was not written: {path.name} is not laid out as the app writes it)"
            _atomic(path, text.encode("utf-8"))
        with self.lock:
            self.meta.setdefault("recipe_of", {})[str(Path(wav).resolve())] = {"recipe": str(path), "name": name, "note": None,
                                                                               "spec": dump(doc["samples"][name])}
            self.save_meta()
        return f"; its faust: entry is in {path.name}"

    def current_file_of(self, num):
        f = ((self.song.get("samples") or {}).get(int(num)) or {}).get("file")
        return str((self.base_dir / f).resolve()) if f else ""

    def find_similar(self, lib, query, k=8):
        """The `k` sounds of the library `lib` nearest WAV `query` by timbre (library.Library.nearest, after a scan when
        the last is over a minute old), added to the slot's candidates; the slot's own WAV and the candidates it already
        has are passed over. Each is remembered with the query and its distance (meta `found`). Returns {"added",
        "report"}."""
        with self.lock:
            slot, skip = self.slot, [*self.cands(), self.current_file() or ""]
        lib.fresh()
        near = lib.nearest(query, max(1, min(50, int(k))), exclude=skip)
        with self.lock:
            cands = self.meta["candidates"].setdefault(str(slot), [])
            found = self.meta.setdefault("found", {})
            for p, d in near:
                if p not in cands:
                    cands.append(p)
                found[p] = [Path(query).stem, round(d, 2)]
            self.save_meta()
        self.queue_all()
        if not near:
            return {"added": [], "report": f"nothing like {Path(query).name} in the library ({lib.count()} sounds indexed)"}
        return {"added": [p for p, _ in near], "report": f"{len(near)} sounds like {Path(query).name} added to slot "
                f"{slot:02d}'s candidates (distance {near[0][1]:.2f}-{near[-1][1]:.2f})"}

    def auto_loop(self, num):
        """Loop points AUTO LOOP proposes for slot `num`: {start, end (exclusive), hz} in the WAV's frames, or an error
        naming why none (the sound does not hold steady, or holds no pitch and no match)."""
        from . import dsp
        with self.lock:
            _, _, w, x = self._sample_wav(num)
        hz = dsp.pitch_of(x, w.rate)
        lp = dsp.find_loop(x, w.rate, hz)
        if lp is None:
            raise ValueError("no loop found: the sound does not hold steady for 0.2 s (a drum or a short hit?)")
        return {"start": lp[0], "end": lp[1], "hz": round(hz, 2) if hz else None}

    def slice_points(self, num, mode="onsets", value=50, a=None, b=None, bpm=None, snap=None):
        """Where SLICE would cut slot `num`'s WAV, frames a..b (default: all of it): at its hits (`onsets`, value the
        sensitivity 0-100) or into `equal` parts (value the count), moved to a grid of 1/`snap` notes at `bpm` when
        both are given. {"points": the slices' start frames, "end", "bpm": the span's tempo guessed from its length
        (dsp.bpm_guess), "rate"}."""
        from . import dsp
        with self.lock:
            _, _, w, x = self._sample_wav(num)
        n = x.shape[1]
        a = max(0, min(n - 1, int(a or 0)))
        b = max(a + 1, min(n, int(b) if b not in (None, "") else n))
        if mode == "equal":
            pts = dsp.equal_parts(a, b, int(value))
        elif mode == "onsets":
            pts = dsp.onsets(x, w.rate, value, a, b)
        else:
            raise ValueError("slices go at the hits (onsets) or in equal parts")
        if bpm and snap:
            if not 20 <= float(bpm) <= 999 or int(snap) not in (4, 8, 16, 32):
                raise ValueError("snap to 1/4, 1/8, 1/16 or 1/32 notes at 20-999 BPM")
            pts = [p for p in dsp.snap_points(pts, a, w.rate, float(bpm), int(snap)) if p < b]
        return {"points": [int(p) for p in pts], "end": b, "bpm": dsp.bpm_guess((b - a) / w.rate), "rate": w.rate}

    def sample_view(self, num, a=0, b=None, n=1000):
        """The editor's view of slot `num`: the WAV (frames, rate, channels, bits), its loops in the WAV's frames, the
        peaks of frames a..b in `n` columns, and what previews it in the live engine: [instrument index as libopenmpt
        counts (0-based; the sample in a song without instruments), note], preferring the note that plays the WAV at its own
        speed (its base_note, or the note its c5_speed puts there: a recorded take is heard as it was played)."""
        with self.lock:
            entry, path, w, x = self._sample_wav(num)
            frames = x.shape[1]
            a = max(0, min(frames - 1, int(a)))
            b = frames if b is None else max(a + 1, min(frames, int(b)))
            mn, mx = wave_peaks(x, a, b, max(16, min(4000, int(n))))
            if entry.get("c5_speed"):
                root = round(60 - 12 * math.log2(int(entry["c5_speed"]) / w.rate))
            else:
                from .notation import parse_note
                root = parse_note(str(entry.get("base_note") or "C-5"))
            player = [int(num) - 1, root]
            if self.mod and self.mod.instruments is not None:
                hits = [(played != root, i, note) for i, ins in enumerate(self.mod.instruments)
                        for note, (played, smp) in enumerate(ins.keymap) if smp == int(num)]
                player = [min(hits)[1], min(hits)[2]] if hits else None
            loops = entry_loops(entry, w)
            return {"num": int(num), "file": str(path), "frames": frames, "rate": w.rate, "channels": x.shape[0], "bits": w.bits,
                    "root": format_note(w.root) if w.root is not None and 0 <= w.root < 120 else None,
                    "a": a, "b": b, "min": mn, "max": mx, "player": player,
                    "loops": {k: list(v) if v else None for k, v in loops.items()},
                    "wav_loop": list(w.loops[0]) if w.loops else None}

    def _new_wav(self, src, action):
        """A path beside the song for an edited copy of `src`: <stem>-<action>.wav, numbered so no file is ever replaced."""
        stem = re.sub(rf"-({'|'.join(SAMPLE_ACTIONS)})(-\d+)?$", "", src.stem)
        for k in itertools.count(1):
            p = self.base_dir / f"{stem}-{action}{'' if k == 1 else f'-{k}'}.wav"
            if not p.exists():
                return p

    def unused(self):
        """What the order list never plays: patterns outside it, instruments no cell of its patterns names, samples that no
        used instrument maps (or, without instruments, no cell names). Memoised per song text."""
        if getattr(self, "_unused", (None,))[0] == self.text:
            return self._unused[1]
        mod, out = self.mod, {"patterns": [], "instruments": [], "samples": []}
        if mod and not self.error:
            played = {o for o in mod.orders if o < 254}
            cells = voice_references(self.song, mod, played=True)
            out["patterns"] = [p.name for i, p in enumerate(mod.patterns) if i not in played]
            if mod.instruments is not None:
                used = {n for n in cells if 0 < n <= len(mod.instruments)}
                out["instruments"] = [n for n in (self.song.get("instruments") or {}) if int(n) not in used]
                cells = {smp for n in used for _, smp in mod.instruments[n - 1].keymap if smp}
            out["samples"] = [n for n in (self.song.get("samples") or {}) if int(n) not in cells]
        self._unused = (self.text, out)
        return out

    def save_upload(self, name, data):
        """A sound file dropped on the page (its bytes: the page cannot know the file's path) saved beside the song as
        <name>.wav, numbered so no other file is replaced; an identical copy already there is reused. A FLAC, AIFF, OGG or
        MP3 becomes that WAV (as_wav). Returns the path."""
        if Path(name).suffix.lower() in SOUND_FILES and data[:4] != b"RIFF":
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / f"upload{Path(name).suffix.lower()}"
                src.write_bytes(data)
                return self.as_wav(src, name)[0]
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise ValueError(f"{name}: not a WAV, FLAC, AIFF, OGG or MP3 file")
        p, new = save_beside(self.base_dir, Path(name).stem, ".wav", data)
        if new:
            try:
                read_wav(p)
            except (OSError, ValueError):
                p.unlink()
                raise
        return p

    def as_wav(self, path, name=None):
        """(`path`, False) for a WAV; a FLAC, AIFF, OGG or MP3 becomes a WAV beside the song, never over a file there, with
        the loops and root note OpenMPT keeps from it (wavload.to_wav): (that WAV, whether it was written now)."""
        if Path(path).suffix.lower() not in SOUND_FILES:
            return Path(path), False
        return to_wav(path, self.base_dir, ffmpeg_exe(), name)

    # ---- pattern view

    def pattern_rows(self, index, occurrence=None):
        """One pattern as read-only tracker rows; each cell in the 'C-5 01 v64 A06' layout libopenmpt prints."""
        pat = self.mod.patterns[self.pattern_at(index)]
        if self.mod.native_score is not None:
            from .tablature import pattern_authoring_view
            view = pattern_authoring_view(self.song, self.mod.patterns, self.pattern_at(index), occurrence,
                                          view=self.mod.native_score['view'])
            return {**view, "name": pat.name, "revision": self.text_sha(), "native": True,
                    "score_positions": view['positions'],
                    "lanes": [[r, ch, col, lane] for (r, ch), (col, lane) in sorted(pat.lanes.items())]}
        projection = self.mod.score_projection
        return {"name": pat.name, "index": index, "rows": [[format_cell(c) for c in row] for row in pat.rows],
                "revision": self.text_sha(),
                "score_positions": [p for p in projection.positions if p['pattern'] == index] if projection else [],
                "lanes": [[r, ch, col, lane] for (r, ch), (col, lane) in sorted(pat.lanes.items())]}

    # ---- snapshot for the page

    def _recipe_snapshot(self):
        try:
            rec = self.slot_recipe()
        except OSError:
            rec = None
        if rec:
            rec = dict(rec, recipe_name=Path(rec["recipe"]).name)
        return {"slot": rec, "job": self.recipe_job}

    def snapshot(self):
        with self.lock:
            self._stamps = "|".join(_stamp(f) for f in self.files)  # read once for every key this snapshot takes
            try:
                return self._snapshot()
            finally:
                self._stamps = None

    def _snapshot(self):
        with self.lock:
            slot = self.slot
            entry = (self.song.get("samples") or {}).get(slot, {})
            cur = self.current_file()
            ref = self.measured(cur) if cur and Path(cur).exists() else None
            cands = []
            for i, c in enumerate(self.cands()):
                k = self.key(c)
                r = self.renders.get(k, {"status": "queued", "file": None, "error": None})
                m = self.measured(c) if Path(c).exists() else {"error": "file not found"}
                rating = self.meta["ratings"].get(c, {})
                cands.append({"id": i, "path": c, "name": Path(c).stem, "src": os.path.relpath(c, self.base_dir).replace(os.sep, "/"),
                              "key": k, "status": r["status"], "error": r.get("error"), "peak": r.get("peak"), "meas": m,
                              "dist": distance(m, ref), "match_db": self.match_db(c), "stars": rating.get("stars", 0), "rejected": rating.get("rejected", False),
                              "note": rating.get("note", ""), "current": c == cur,
                              "found": (self.meta.get("found") or {}).get(c)})
            ents = self.song.get("samples") or {}
            slot_meas = {}  # per slot: the three numbers the overview table shows (memoised per WAV)
            for k, v in ents.items():
                f = (self.base_dir / v["file"]).resolve() if isinstance(v, dict) and v.get("file") else None
                m = self.meas.get(str(f)) if f else None  # filled in by the warm-up thread; blank until then
                if m:
                    slot_meas[str(k)] = {x: m.get(x) for x in ("pitch", "centroid", "decay")}
            ok = self.key()
            own = self.renders.get(ok, {"status": "queued", "error": None})
            voice = []  # the instruments that play this slot through the `sample:` shorthand (a keymap is the song's to edit)
            for n, ins in (self.song.get("instruments") or {}).items():
                if isinstance(ins, dict) and ins.get("sample") is not None and ins.get("sample") in (slot, entry.get("name")):
                    params, custom = voice_of(ins)
                    voice.append({"num": n, "name": ins.get("name", ""), "song": params, "custom": custom,
                                  "edit": (self.mix().get("instrument") or {}).get(str(n), {})})
            return {
                "song": {"path": str(self.song_path), "dir": str(self.base_dir), "dirty": self.dirty(), "error": self.error,
                         "mtime": self.mtime, "stamps": hashlib.sha1((self._stamps or "").encode()).hexdigest()[:8], "facts": self.facts, "sample_entries": {str(k): v for k, v in ents.items()},
                         "slot_meas": slot_meas},
                "slot": slot, "slot_entry": entry, "slot_file": cur, "ref": ref, "selected_candidate": self.want,
                "orders": list(self.orders) if self.orders else None, "loop": self.meta.get("loop"),
                **self._playback_selection(),
                "match": bool(self.meta.get("match_level")),
                "muted": sorted(set(self.meta.get("muted") or [])), "solo": self.meta.get("solo"),
                "own": {"key": ok, "status": own["status"], "error": own.get("error"), "peak": own.get("peak"),
                        "numbers": mix_numbers(own["file"]) if own["status"] == "ready" else None},
                "chosen_numbers": next((mix_numbers(self.renders[c["key"]]["file"]) for c in cands
                                        if c["path"] == self.want and c["status"] == "ready"), None),
                "mix": self.mix(), "meters": self.meters, "voice": voice, "spec": {"db": SPEC_DB, "stops": SPEC_STOPS, "nyquist": RATE / 2},
                "source_pan_channels": sorted({ch for track in self.song.get('score', {}).get('tracks', {}).values()
                                               if 'source_pan' in track.get('midi', {}) for ch in track['channels']}),
                "source_volume_channels": sorted({ch for track in self.song.get('score', {}).get('tracks', {}).values()
                                                  if 'source_volume' in track.get('midi', {}) for ch in track['channels']}),
                "reference": self.meta.get("reference"), "delta": {"db": DELTA_DB, "stops": DELTA_STOPS},
                "voice_range": VOICE_RANGE, "dmo": DMO,
                "candidates": cands, "build": self.build, "stems": self.stems, "export": self.export_result,
                "cand_counts": {k: len(v) for k, v in self.meta["candidates"].items() if v},
                "notes": self.notes, "notes_path": str(self.notes_path), "version": self.version(),
                "faust_code": self.meta.get("faust_code"),
                "undo": len(self.history), "redo": len(self.future), "unused": self.unused(),
                "cue": self.cue, "agent_log": self.agent_log[-40:], "chat": CHAT.snapshot(),
                "marks": {"patterns": {p.name: {k: v for k, v in self.pattern_entry(p.name).items() if k in ("by", "approved")}
                                       for p in (self.mod.patterns if self.mod else [])},
                          "channels": [bool(isinstance(c, dict) and c.get("approved"))
                                       for c in ((self.song.get("module") or {}).get("channels") or [])
                                       ] if isinstance((self.song.get("module") or {}).get("channels"), list) else [],
                          "samples": [int(k) for k, v in (self.song.get("samples") or {}).items()
                                      if isinstance(v, dict) and v.get("approved")]},
                "checkpoints": list(self.checkpoints),
                "history_steps": {k: [{"name": s.get("name"), "time": s.get("time")} for s in reversed(v[-12:])]
                                  for k, v in (("undo", self.history), ("redo", self.future))},
                "history_bytes": self.history_store.path.stat().st_size if self.history_store.path.exists() else 0,
                "history_limit": HISTORY_BYTES,
                "phrase": {k: v for k, v in (self.meta.get("phrase") or {}).items() if k not in ("snapshot", "assets", "source_assets", "original")},
                "project_settings": self.meta.get('project_settings') or {},
                "missing": {str(k): v['file'] for k, v in ents.items() if isinstance(v, dict) and v.get('file')
                            and not (self.base_dir / str(v['file'])).is_file()},
                "notices": self.notices,
                "recipe": self._recipe_snapshot(),
                "instruments": {str(k): v for k, v in (self.song.get("instruments") or {}).items()},
                "sections": self.song.get("sections") or {},
                "structure": {"orders": [str(o) for o in self.song.get("orders") or []],
                              "patterns": [{"name": p.name, "rows": len(p.rows), "index": i,
                                            "used": sum(1 for o in self.song.get("orders") or [] if str(o) == p.name)}
                                           for i, p in enumerate(self.mod.patterns)] if self.mod else [],
                              "module": {k: (self.mod.row_highlight[0] or 4) if k == 'rows_per_beat' else
                                               (self.mod.row_highlight[1] or 16) if k == 'rows_per_bar' else
                                               getattr(self.mod, k) for k in self.MODULE_KEYS} if self.mod else {}},
                "archives": sorted(p.name for p in self.base_dir.glob(glob.escape(self.song_path.stem) + ".notes-*.md")),
                "queue": sum(1 for r in self.renders.values() if r["status"] in ("queued", "rendering")),
                "cache": sum(1 for r in self.renders.values() if r["status"] == "ready"),
            }


# ---------------------------------------------------------------- HTTP


def no_webview2():
    """True when pywebview would draw the window with Internet Explorer (Windows without the WebView2 runtime): that
    engine cannot run the page (no CSS variables, no modern script), so the app opens in the browser instead."""
    if sys.platform != "win32":
        return False
    try:
        from webview.platforms import winforms
    except Exception:
        return False
    return getattr(winforms, "renderer", "") == "mshtml"


WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def serve(song_path=None, port=0, open_browser=True, window=True):
    """Serve the UI. With pywebview installed (and `window`), it opens in a native window; else the default
    browser. `song_path` may be None: the UI then starts on its open-a-song screen."""
    start_log()
    for p in server.LOCKS.glob("*.lock"):  # left by sessions that ended (the system let go of their locks)
        f = lock_file(p)
        if f:
            unlock_file(f)
            try:
                p.unlink()
            except OSError:  # another app window took it this moment
                pass
    if song_path:
        server.Handler.open_song(song_path)
    srv = server.make_server(port)
    url = f"http://127.0.0.1:{srv.server_address[1]}/?token={srv.token}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    agent.announce(srv.server_address[1], srv.token)
    if window:
        try:
            import webview
        except ImportError:
            webview = None
        if webview and no_webview2():
            msg = (f"This PC lacks Microsoft's WebView2 runtime, so VultureTracker opened in your browser:\n{url}\n\n"
                   f"Install WebView2 for the app window (free, from Microsoft):\n{WEBVIEW2_URL}\n\n"
                   "Click OK to quit VultureTracker.")
            print(msg)
            webbrowser.open(url)
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, f"VultureTracker {__version__}", 0x40)  # the windowed exe's way to quit
            return 0
        if webview:
            server.Handler.window = webview.create_window(f"VultureTracker {__version__}", url, width=1400, height=900, min_size=(1000, 600), background_color="#0a0c0d")
            webview.start(private_mode=False, storage_path=str(PROFILE))
            return 0
    print(f"VultureTracker GUI: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0
