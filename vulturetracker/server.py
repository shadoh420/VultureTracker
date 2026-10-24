"""The app's HTTP side: the request handler (the page's GETs and POSTs, the Host, Origin and API token checks), the
server and its port, and the lock an app holds on each song it has open (app_lock_path). The State it serves lives in
gui.py: gui and server import each other as modules and reach each other's names at call time, so either may be
imported first."""
import base64
import functools
import hashlib
import hmac
import json
import os
import secrets
import struct
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote

from . import __version__, agent, gui
from .fileio import lock_file, unlock_file, user_dir
from .history import LABEL, digest
from .measure import RATE, _meters, spectrogram_png
from .openmpt import OpenMPTError
from .project import collect
from .song import SongError
from .wavload import SOUND_FILES

# the page is served from one address every launch when it can be, so what the browser stores per address stays (the
# window's WebView2 profile, gui.PROFILE): the page's settings (localStorage) and the MIDI permission
PORT = 8723
BODY_BYTES = 8 << 20      # the most a request body may claim (JSON: edits, settings, the FAUST tab's code) ...
UPLOAD_BYTES = 512 << 20  # ... and an upload's (a dropped or rendered WAV)
LOCKS = user_dir() / "open"  # one locked file per song open in an app (app_lock_path), beside the recent-songs list


def _score_log_fields(source):
    """Only diagnostic identifiers/timing, never arbitrary score or request content."""
    if not isinstance(source, dict):
        return {}
    out = {}
    for key in ('action', 'op', 'occurrence', 'beat', 'track', 'pattern', 'revision', 'fit', 'free', 'voice', 'id'):
        value = source.get(key)
        if isinstance(value, (str, int, bool)):
            out[key] = value[:160] if isinstance(value, str) else value
    for key in ('at', 'tuplet', 'amount'):
        value = source.get(key)
        if isinstance(value, list) and len(value) == 2 and all(type(v) is int for v in value):
            out[key] = value
    written = source.get('written')
    if isinstance(written, dict):
        out['written'] = {k: written[k] for k in ('value', 'dots') if type(written.get(k)) is int}
        out['written'].update(_score_log_fields({'tuplet': written.get('tuplet')}))
    return out


def _score_request(st, body, endpoint):
    """One bounded completion event, with the pre-edit selection held under the song lock."""
    body = dict(body)
    ui_context = body.pop('ui_context', None)
    ui_context = {k: ui_context[k] for k in ('action', 'occurrence', 'beat', 'written', 'fit', 'free', 'voice')
                  if k in ui_context} if isinstance(ui_context, dict) else {}
    with st.lock:
        before = st.text_sha()
        event = dict(endpoint=endpoint, song=str(st.song_path)[:1024], request=_score_log_fields(body),
                     ui_context=_score_log_fields(ui_context), before_revision=before, selected=[], selected_total=0)
        score = st.song.get('score', {})
        occurrences = dict(zip(score.get('order_ids', []), st.song.get('orders', [])))
        groups = body.get('selection')
        if not isinstance(groups, list):
            beat = body.get('beat')
            ids = body.get('beats', [beat.get('id')] if isinstance(beat, dict) else [beat] if isinstance(beat, str) else [])
            groups = [dict(occurrence=body.get('occurrence'), pattern=body.get('pattern'), beats=ids)]
            if isinstance(beat, dict):
                event['request']['placed'] = _score_log_fields(beat)
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get('beats'), list):
                continue
            ids = group['beats']
            event['selected_total'] += len(ids)
            occurrence = group.get('occurrence')
            name = occurrences.get(occurrence) if isinstance(occurrence, str) else group.get('pattern')
            pattern = score.get('patterns', {}).get(str(name), {})
            for identity in ids[:max(0, 32 - len(event['selected']))]:
                item = _score_log_fields(dict(occurrence=occurrence, id=identity))
                current = next((b for b in pattern.get('beats', []) if b.get('id') == identity), None)
                if current is not None:
                    item.update(_score_log_fields(current), rest=not bool(current.get('notes')))
                event['selected'].append(item)
        event['selected_truncated'] = event['selected_total'] - len(event['selected'])
        try:
            if endpoint == 'score_command':
                result = st.score_command(body)
            else:
                result = st.score_edit(body) or dict(ok=True, revision=st.text_sha())
            event['outcome'] = 'noop' if st.text_sha() == before else 'changed'
            if body.get('action') == 'set_duration':
                kept = result.get('kept_durations', [])
                event['duration_result'] = dict(kept_total=len(kept),
                    kept=[dict(_score_log_fields(item), reason=item.get('reason')) for item in kept[:32]
                          if item.get('reason') in ('bar_end', 'no_space')],
                    consumed_rests=len(result.get('consumed_rests', [])),
                    removed_ties=len(result.get('removed_ties', [])))
            return result
        except Exception as e:
            event.update(outcome='refused', error=f'{type(e).__name__}: {e}'[:512])
            raise
        finally:
            event['after_revision'] = st.text_sha()
            gui._log.info('TAB edit %s', json.dumps(event, ensure_ascii=True, separators=(',', ':')))


def start_snapshot():
    return {"song": None, "recent": gui.recent_songs(), "demos": gui.demo_songs(), "version": __version__}


def worklet_js():
    """/engine-worklet.js: the libopenmpt glue (a classic script) wrapped as loadGlue(), then the engine core and the
    processor, as one module for audioWorklet.addModule (a worklet cannot load scripts itself)."""
    glue = (gui.WEB / "libopenmpt.js").read_text(encoding="utf-8")
    return ("const loadGlue = function (libopenmpt, require, __dirname) {\n" + glue + "\nreturn Module;\n};\n"
            + (gui.WEB / "engine-core.js").read_text(encoding="utf-8") + (gui.WEB / "engine-worklet.js").read_text(encoding="utf-8")).encode("utf-8")


def app_lock_path(song_path):
    """The file the app holds locked while a song is open in it: beside the recent-songs list, not in the song's folder
    (Windows would refuse to rename or move a folder holding an open file)."""
    key = os.path.normcase(str(Path(song_path).resolve()))
    return LOCKS / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".lock")


def open_in_app(song_path):
    """Whether a running app has the song open: it keeps the song's history and tryout settings in memory and writes
    them over a change made beside it (a checkpoint saved from the command line would vanish)."""
    p = app_lock_path(song_path)
    if not p.exists():
        return False
    f = lock_file(p)
    if f is None:
        return True
    unlock_file(f)
    return False


LOCK_WAITS = (0.1, 0.2, 0.4, 0.8, 1.5)  # seconds an app opening a song waits for a command that is changing it


_HELD = {}  # app_lock_path -> [the locked file, how many of this process's States have the song open]


_HELD_GUARD = threading.Lock()


def take_app_lock(song_path):
    """Lock the song for this process while a State has it open (the same song opened again shares the lock), waiting
    LOCK_WAITS for a command that holds it; False when another app or a command holds it all that time."""
    p = app_lock_path(song_path)
    for wait in (*LOCK_WAITS, None):
        with _HELD_GUARD:
            if p in _HELD:
                _HELD[p][1] += 1
                return True
            LOCKS.mkdir(parents=True, exist_ok=True)
            f = lock_file(p)
            if f:
                _HELD[p] = [f, 1]
                return True
        if wait is None:
            return False
        time.sleep(wait)


def release_app_lock(song_path):
    p = app_lock_path(song_path)
    with _HELD_GUARD:
        held = _HELD.get(p)
        if held and held[1] > 1:
            held[1] -= 1
        elif held:
            del _HELD[p]
            unlock_file(held[0])
            try:
                p.unlink()
            except OSError:  # another app or a command took it this moment: it stays, unlocked
                pass


STEP_NAMES = {"apply": "write candidate (U)", "applymix": "WRITE MIX", "relink": "relink samples",
              "materialize": "materialize pattern", "phrase": "accept phrase", "checkpoint": "restore checkpoint"}


def _step_label(act, body):
    """The undo step name for a request: what it does, in the page's words."""
    if act == "edit":
        groups = [g for g in (body.get("patterns") if isinstance(body.get("patterns"), list) else [body])
                  if isinstance(g, dict)]
        cells = sum(len(g["cells"]) for g in groups if isinstance(g.get("cells"), list))
        names = ", ".join(str(g.get("pattern")) for g in groups[:4]) + (", …" if len(groups) > 4 else "")
        return f"edit pattern {names}: {cells} cell{'s' * (cells != 1)}"
    if act == "songedit" and isinstance(body.get("ops"), list):
        return "song: " + ", ".join(dict.fromkeys(str(o.get("op")).replace("_", " ") for o in body["ops"]
                                                  if isinstance(o, dict)))
    if act == "section":
        return f"section {body.get('action', 'save')} {body.get('name', '')}".strip()
    return STEP_NAMES.get(act, act)


class Handler(BaseHTTPRequestHandler):
    # TODO: Handler.state, Handler.library and Handler.song_lock are class attributes (one app per process, and
    # the tests patch them there); move them onto the server instance
    state: "gui.State" = None
    song_lock = threading.RLock()
    pending_recording = None  # unsaved passes retained in memory until saved or explicitly discarded
    window = None  # pywebview window, when the UI runs in one

    recorder = None      # record.Recorder, made on the RECORD tab's first request
    rec_devices = None   # the input devices, listed once (again on REFRESH)
    library = None       # library.Library, read on the first FIND SIMILAR or MAP request
    faust_job = None     # the faustwasm download: {"status", "got", "size", "error"}
    collection_job = None
    collection_cancel = threading.Event()
    collection_lock = threading.RLock()

    @classmethod
    def collection(cls, body=None):
        from . import score_collection
        with cls.collection_lock:
            if body is None:
                return json.loads(json.dumps(cls.collection_job))
            action = body.get('action', 'scan')
            if action == 'scan':
                return score_collection.scan(body.get('folder', ''), bool(body.get('recursive')))
            if action == 'cancel':
                cls.collection_cancel.set()
                return cls.collection_job
            if action != 'convert':
                raise ValueError('Choose scan, convert or cancel')
            if cls.collection_job and cls.collection_job['status'] == 'running':
                raise ValueError('A score conversion is already running')
            settings = score_collection.options(body)
            cls.collection_cancel = threading.Event()
            job = cls.collection_job = dict(status='running', results=[], total=len(settings['paths']), destination=settings['destination'])
            cancel = cls.collection_cancel

        def progress(item):
            with cls.collection_lock:
                job['results'] = [r for r in job['results'] if r['source'] != item['source']] + [item]

        def work():
            try:
                results = score_collection.convert(settings, progress, cancel)
                with cls.collection_lock:
                    job['results'] = results
                    job['status'] = 'cancelled' if cancel.is_set() else 'finished'
            except Exception as exc:
                with cls.collection_lock:
                    job.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        threading.Thread(target=work, name='score conversion', daemon=True).start()
        return job

    @classmethod
    def fetch_faust(cls):
        from . import faust
        if cls.faust_job and cls.faust_job["status"] == "fetching":
            return cls.faust_job
        job = cls.faust_job = {"status": "fetching", "got": 0, "size": 0, "error": None}

        def run():
            try:
                faust.fetch(lambda got, size: job.update(got=got, size=size))
                job["status"] = "done"
            except (OSError, ValueError) as e:
                job.update(status="failed", error=f"{type(e).__name__}: {e}")
        threading.Thread(target=run, daemon=True).start()
        return job

    @classmethod
    def rec(cls):
        if cls.recorder is None:
            from .record import Recorder
            if gui._read_json(gui.REC_SETTINGS, {}, []).get("asio"):  # sounddevice loads its ASIO build only when this is set first
                os.environ.setdefault("SD_ENABLE_ASIO", "1")
            cls.recorder = Recorder()
        return cls.recorder

    @classmethod
    def rec_snapshot(cls, devices=False, spill=True):
        """The RECORD tab's state: the input devices, the recorder's meters and tuner, the song's takes. With `spill`,
        finished passes not saved yet are first kept on disk (record.spill), so GET /api/rec passes False: no GET
        writes."""
        from .record import MODE_NAMES, RecordError
        r = cls.rec()
        out = {"available": True, "error": None, "fake": bool(os.environ.get("VT_FAKE_AUDIO")),
               "asio": bool(os.environ.get("SD_ENABLE_ASIO")), "asio_saved": bool(gui._read_json(gui.REC_SETTINGS, {}, []).get("asio")),
               "modes": MODE_NAMES}
        try:
            if devices or cls.rec_devices is None:
                cls.rec_devices = r.devices()
                cls.rec_outputs = r.outputs()
            out["devices"] = cls.rec_devices
            out['outputs'] = getattr(cls, 'rec_outputs', [])
        except RecordError as e:
            out.update(available=False, error=str(e), devices=[])
        out["status"] = r.status()
        out["takes"] = cls.state.takes if cls.state else []
        out["status"]["pending_save"] = bool(cls.pending_recording)
        from . import record
        if spill and out["status"]["finished"] and not r.spill_id and cls.state is not None:  # backing passes done, not saved yet
            try:
                takes, plan = r.peek_takes()
                if takes:
                    r.spill_id = record.spill(takes, r.rate, cls.state.song_path, plan["loops"] if plan else 0)
            except OSError:
                pass
        live = {r.spill_id, (cls.pending_recording or {}).get("spill")}
        out["unsaved"] = [s for s in record.spilled() if s["id"] not in live]
        return out

    @classmethod
    def rec_command(cls, body):
        with cls.song_lock:
            return cls._rec_command(body)

    @classmethod
    def _rec_command(cls, body):
        """POST /api/rec: {cmd: open (device, mode, rate, exclusive) | mode | close | start (preroll) | stop (name, trim,
        trim_db, root, dest: candidate / slot / keep) | discard}."""
        from .record import RecordError
        r, cmd = cls.rec(), body.get("cmd")
        try:
            if cmd in ('open', 'mode', 'close', 'start', 'calibrate', 'recover') and (cls.pending_recording or r.recording):
                raise RecordError('Save or discard the current take first')
            if cmd == 'recover':  # passes an earlier session kept, back as the take to save (the song open now)
                from .record import load_spill
                if cls.state is None:
                    raise RecordError('open a song first: takes are saved beside it')
                takes, rate, loops = load_spill(str(body.get('id')))
                cls.pending_recording = dict(takes=takes, rate=rate, saved=[], file=None, spill=str(body['id']),
                                             plan={'loops': loops, 'calibration': False} if loops else None)
                return {}
            if cmd == 'forget':  # kept passes thrown away
                from .record import unspill
                unspill(str(body.get('id')))
                return {}
            if cmd in ('start', 'stop', 'send', 'multisample'):
                if cls.state is None:
                    raise RecordError('open a song first')
                cls.state._writable()
            if cmd == "open":
                r.open(int(body["device"]), str(body.get("mode") or "1"), int(body.get("rate") or 44100),
                       bool(body.get("exclusive")))
            elif cmd == "mode":
                r.set_mode(str(body["mode"]))
            elif cmd == "close":
                r.close()
            elif cmd == "start":
                if cls.state is None:
                    raise RecordError("open a song first: takes are saved beside it")
                if r.recording:
                    raise RecordError('Stop the current take first')
                if body.get('backing'):
                    from .export import snapshot, render
                    from .resample import resample
                    import numpy as np
                    st = cls.state
                    with st.lock:
                        st._need_compiled()
                        if st.dirty():
                            raise RecordError('Compare and RELOAD external edits before recording')
                        region = None
                        if body.get('section'):
                            a, b = st.song['sections'][body['section']]
                            playable = [i for i in range(a, b) if st.mod.orders[i] < len(st.mod.patterns)]
                            if not playable:
                                raise RecordError('The selected section has no playable orders')
                            a, b = playable[0], playable[-1]
                            region = (a, 0, b, len(st.mod.patterns[st.mod.orders[b]].rows)-1)
                        snap = snapshot(st.song, st.base_dir, region, st.mix(), st.silenced(), tail=0)
                        bpm = st.facts['bpm']
                        if snap.get('plan') is not None:
                            from .tablature import TempoClock
                            plan = snap['plan']
                            bpm = TempoClock(plan['tempo'], plan.get('tempos')).tempo_at(snap['range_at'][0])
                    render_rate = r.rate if snap.get('plan') is not None else RATE
                    pcm = np.frombuffer(render(snap, rate=render_rate), dtype='<i2').astype(np.float32).reshape(-1, 2) / 32768
                    if r.rate != render_rate:
                        pcm = np.stack([resample(pcm[:, c], render_rate, r.rate) for c in range(2)], axis=1)
                    if cls.state is not st:
                        raise RecordError('The song changed while preparing playback; start again')
                    r.start_backing(pcm, body['output'], countin=body.get('countin', 4), bpm=bpm,
                                    loops=body.get('loops', 1), latency_ms=body.get('latency_ms', 0))
                else:
                    r.start(float(body.get("preroll") or 0))
            elif cmd == 'calibrate':
                from .record import calibration_signal
                if not r.rate:
                    raise RecordError('Open an input first')
                r.start_backing(calibration_signal(r.rate), body['output'], countin=0, calibration=True)
            elif cmd == "asio":  # takes effect at the next start: sounddevice has loaded its PortAudio already
                gui.REC_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
                gui._atomic_text(gui.REC_SETTINGS, json.dumps({"asio": bool(body.get("on"))}))
                now = bool(os.environ.get("SD_ENABLE_ASIO"))
                return {} if now == bool(body.get("on")) else {"error": "saved: restart the app to switch the ASIO driver "
                                                                        + ("on" if body.get("on") else "off")}
            elif cmd == "send":
                return {"take": cls.state.send_take(str(body["file"]), str(body.get("dest") or "candidate"))}
            elif cmd == "multisample":  # the session's takes with a note as one instrument
                return {"report": cls.state.takes_multisample(body.get("files"))}
            elif cmd in ("stop", "discard"):
                if cmd == 'discard':
                    from .record import unspill
                    unspill(r.spill_id)
                    unspill((cls.pending_recording or {}).get('spill'))
                    r.stop_takes()
                    r.spill_id = None
                    cls.pending_recording = None
                    return {}
                if cls.pending_recording is None:
                    takes, plan = r.stop_takes()
                    if plan and plan['calibration'] and takes:
                        from .record import measure_latency
                        return {'latency_ms': measure_latency(plan['pcm'], takes[0], r.rate)}
                    if not takes:
                        return {}
                    sid = r.spill_id
                    if sid is None:  # kept in the user folder until saved: a failed save or a crash keeps the passes
                        from .record import spill
                        try:
                            sid = spill(takes, r.rate, cls.state.song_path, plan['loops'] if plan else 0)
                        except OSError:
                            sid = None
                    r.spill_id = None
                    cls.pending_recording = dict(takes=takes, plan=plan, rate=r.rate, saved=[], file=None, spill=sid)
                pending = cls.pending_recording
                while len(pending['saved']) < len(pending['takes']):
                    i = len(pending['saved'])
                    opts, plan = dict(body), pending['plan']
                    if plan:
                        opts['trim'] = False  # preserve placement against the backing track
                        if plan['loops'] > 1:
                            opts['name'] = str(body.get('name') or 'take') + f'-pass{i+1}'
                    if pending['file'] is None:
                        take = cls.state.save_take(pending['takes'][i], pending['rate'], dict(opts, dest='keep'))
                        pending['file'] = take['file']
                    take = cls.state.send_take(pending['file'], body.get('dest') or 'candidate')
                    pending['saved'].append(take)
                    pending['file'] = None
                cls.pending_recording = None
                from .record import unspill
                unspill(pending.get('spill'))
                return {'take': pending['saved'][-1], 'takes': pending['saved']}
            else:
                raise RecordError(f"unknown recorder command {cmd!r}")
        except (RecordError, ValueError, OSError) as e:
            return {"error": str(e)}
        return {}

    @classmethod
    def lib(cls):
        """The sample library's index (library.py), read on first use."""
        if cls.library is None:
            from .library import Library, default_index
            cls.library = Library(default_index())
        return cls.library

    @classmethod
    def lib_snapshot(cls):
        from .library import default_roots
        lib = cls.library
        if lib is None:
            return {"loaded": False}
        return {"loaded": True, "index": str(lib.path), "roots": lib.data["roots"], "default_roots": default_roots(),
                "status": lib.status, "count": lib.count(), "generation": lib.generation,
                "busy": bool(lib.job and lib.job.is_alive())}

    @classmethod
    def open_song(cls, path, agent_request=False):
        with cls.song_lock:
            if gui.CHAT.busy and not agent_request:
                raise ValueError('Stop the agent before opening another song')
            if cls.pending_recording or (cls.recorder is not None and cls.recorder.recording):
                raise ValueError('Save or discard the recording before opening another song')
            old, cls.state = cls.state, gui.State(path)  # the same song opened again shares the old state's lock
            if agent_request:
                gui.CHAT.tool_state = cls.state
            if old is not None:
                old.close()
            gui.remember_song(cls.state.song_path)

    @classmethod
    def browse(cls, wav=False, module=False, sf2=False):
        """Native file dialog, returning the chosen song (or, with `wav`, WAV; with `module`, module; with `sf2`,
        SoundFont) path or None."""
        kind, pat = ("Sound files", ";".join(f"*{x}" for x in (".wav", *SOUND_FILES))) if wav else ("Module tab and MIDI files", "*.it;*.xm;*.s3m;*.mod;*.gtp;*.gp3;*.gp4;*.gp5;*.gpx;*.gp;*.tg;*.ptb;*.tef;*.mid;*.midi") if module else ("SoundFonts and GUS patches", "*.sf2;*.pat") if sf2 else ("Song files", "*.yaml;*.yml")
        if cls.window is not None:
            import webview
            r = cls.window.create_file_dialog(webview.OPEN_DIALOG, file_types=(f"{kind} ({pat})", "All files (*.*)"))
            return r[0] if r else None
        from tkinter import Tk, filedialog
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        r = filedialog.askopenfilename(parent=root, title="VultureTracker", filetypes=[(kind, pat.replace(";", " ")), ("All files", "*")])
        root.destroy()
        return r or None

    @classmethod
    def save_score_export(cls, body):
        """Save one rendered score page chosen in the native dialog, without changing the song."""
        from .fileio import atomic_write, protect_outputs
        from xml.etree import ElementTree
        state = cls.state
        if state is None:
            raise ValueError('Open a song first')
        def current():
            if cls.state is not state or body.get('song') != str(state.song_path) or body.get('revision') != state.text_sha() or state.dirty():
                raise ValueError('The song changed; refresh the print preview before exporting')
        with cls.song_lock, state.lock:
            current()
        fmt = body.get('format')
        if fmt not in ('svg', 'png', 'jpg', 'bmp'):
            raise ValueError('Choose SVG, PNG, JPEG or BMP')
        try:
            data = base64.b64decode(body.get('data', ''), validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid score image data') from exc
        limit = (24 if fmt == 'bmp' else 6) << 20
        if not data or len(data) > limit:
            raise ValueError(f'Score image must be between1 byte and{limit >> 20} MiB')
        if fmt == 'png':
            if not data.startswith(b'\x89PNG\r\n\x1a\n') or not data.endswith(b'IEND\xaeB`\x82'):
                raise ValueError('Invalid PNG score image')
        elif fmt == 'jpg':
            if not data.startswith(b'\xff\xd8\xff') or not data.endswith(b'\xff\xd9'):
                raise ValueError('Invalid JPEG score image')
        elif fmt == 'bmp':
            import struct
            if len(data) < 54 or data[:2] != b'BM':
                raise ValueError('Invalid BMP score image')
            size, offset, dib, width, height, planes, bits, compression = (
                struct.unpack_from('<I', data, 2)[0], *struct.unpack_from('<IIiiHHI', data, 10))
            if (size != len(data) or offset != 54 or dib != 40 or width <= 0 or height <= 0 or
                    planes != 1 or bits != 24 or compression != 0 or
                    54 + ((width * 3 + 3) & ~3) * height != len(data)):
                raise ValueError('Invalid BMP score dimensions or pixel data')
        else:
            try:
                root = ElementTree.fromstring(data)
            except ElementTree.ParseError as exc:
                raise ValueError('Invalid SVG score image') from exc
            if root.tag != '{http://www.w3.org/2000/svg}svg':
                raise ValueError('Invalid SVG score image')
        name = Path(str(body.get('name') or 'score-page')).stem + '.' + fmt
        if cls.window is not None:
            import webview
            chosen = cls.window.create_file_dialog(webview.SAVE_DIALOG, directory=str(state.base_dir),
                save_filename=name, file_types=(f'{fmt.upper()} score (*.{fmt})',))
        else:
            from tkinter import Tk, filedialog
            dialog = Tk(); dialog.withdraw(); dialog.attributes('-topmost', True)
            try:
                chosen = filedialog.asksaveasfilename(parent=dialog, title='Save score page',
                    initialdir=str(state.base_dir), initialfile=name, defaultextension='.' + fmt,
                    filetypes=[(fmt.upper() + ' score', '*.' + fmt)], confirmoverwrite=True)
            finally:
                dialog.destroy()
        if isinstance(chosen, (tuple, list)):
            chosen = chosen[0] if chosen else None
        if not chosen:
            return {'path': None}
        path = Path(chosen).resolve()
        if path.suffix.lower() != '.' + fmt:
            raise ValueError('Choose a .' + fmt + ' file')
        with cls.song_lock, state.lock:
            current()
            sources = [state.song_path] + [state.base_dir / s['file'] for s in state.song.get('samples', {}).values() if s.get('file')]
            protect_outputs([path], sources)
            atomic_write(path, data)
        return {'path': str(path)}

    @classmethod
    def save_song_shortcut(cls):
        if sys.platform != 'win32':
            raise ValueError('Song shortcuts are available on Windows only')
        state = cls.state
        if state is None:
            raise ValueError('Open a song first')
        filename = state.song_path.stem + '.lnk'
        if cls.window is not None:
            import webview
            chosen = cls.window.create_file_dialog(webview.SAVE_DIALOG, directory=str(state.base_dir),
                        save_filename=filename, file_types=('Windows shortcut (*.lnk)',))
        else:
            from tkinter import Tk, filedialog
            root = Tk(); root.withdraw(); root.attributes('-topmost', True)
            try:
                chosen = filedialog.asksaveasfilename(parent=root, title='Create song shortcut',
                    initialdir=str(state.base_dir), initialfile=filename, defaultextension='.lnk',
                    filetypes=[('Windows shortcut', '*.lnk')], confirmoverwrite=True)
            finally:
                root.destroy()
        if isinstance(chosen, (tuple, list)):
            chosen = chosen[0] if chosen else None
        if not chosen:
            return {'path': None}
        with cls.song_lock:
            if cls.state is not state:
                raise ValueError('The open song changed while choosing the shortcut; try again')
            from .project import song_shortcut
            return {'path': song_shortcut(state, chosen)}

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        p = Path(path)
        try:
            f = p.open("rb")
        except OSError:
            return self._send(404, {"error": "not found"})
        with f:
            self._send_range(f, os.fstat(f.fileno()).st_size, ctype)

    def _send_range(self, f, size, ctype):
        """The open file `f`, or the byte range the request names, read and sent in pieces (a render is tens of MB, and
        the page asks for it range by range as it plays and seeks)."""
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        code = 200
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].strip().partition("-")  # one range: the first of a list
            try:
                if a:
                    start, end = int(a), min(int(b), end) if b else end
                elif b:  # the last b bytes
                    start = max(0, size - int(b))
                else:
                    raise ValueError
            except ValueError:
                return self._send(400, {"error": f"bad Range header: {rng}"})
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        f.seek(start)
        left = end - start + 1
        while left > 0:
            piece = f.read(min(left, 1 << 20))
            if not piece:
                break
            self.wfile.write(piece)
            left -= len(piece)

    def _foreign(self):
        """A request from another web page (its Origin is not this server's), or one that reached the server under another
        host name (a DNS-rebinding page): refused, since the POSTs open, create and write files. The page's own requests
        carry this origin; local tools (the tests, scripts) send none."""
        port = self.server.server_address[1]
        if (self.headers.get("Host") or "").rsplit(":", 1)[0] not in ("127.0.0.1", "localhost"):
            return True
        origin = self.headers.get("Origin")
        return origin is not None and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _authorized(self):
        """The request carries this launch's token (_Server.token): the X-VT-Token header, which the page's fetches and
        the MCP bridge send, or token= in the query, which the app's own window address carries and the page adds to
        what it loads by URL (an <audio> or <img> sends no header). It keeps out what the Origin check cannot see: a
        page's <img> or <audio> request carries no Origin, and another local account can reach 127.0.0.1 too."""
        got = self.headers.get("X-VT-Token") or parse_qs(self.path.partition("?")[2]).get("token", [""])[0]
        return hmac.compare_digest(got.encode(), self.server.token.encode())

    # what the page loads before its script runs; none of it holds anything of a song
    OPEN_PATHS = ("/engine-worklet.js", "/icon.png")

    def _guarded(fn):
        """An unexpected error is logged and answered with a 500 and its message: the page is never left without one."""
        @functools.wraps(fn)
        def run(self):
            try:
                return fn(self)
            except ConnectionError:
                raise
            except Exception as e:  # noqa: BLE001
                gui._log.exception("%s %s failed", self.command, self.path.split("?")[0])
                try:
                    self._send(500, {"error": gui.logged(f"{type(e).__name__}: {e}")})
                except OSError:
                    pass
        return run

    @_guarded
    def do_GET(self):
        if self._foreign():
            return self._send(403, {"error": "not this app's page"})
        st = self.state
        path = self.path.split("?")[0]
        if not (path in self.OPEN_PATHS or path.startswith(("/web/", "/faust/")) or self._authorized()):
            if path == "/":
                return self._send(401, b"<p>This address lacks the token VultureTracker makes each launch. Use the app's "
                                       b"window, or the address it opened in your browser; running.json in your user folder "
                                       b"(%APPDATA%\\VultureTracker on Windows) holds the port and the token: "
                                       b"http://127.0.0.1:PORT/?token=TOKEN</p>", "text/html; charset=utf-8")
            return self._send(401, {"error": "no token: this app's page and its MCP bridge send this launch's"})
        if path == "/":
            return self._send(200, gui.HTML.read_bytes().replace(b"<title>VultureTracker</title>", f"<title>VultureTracker {__version__}</title>".encode())
                              .replace(b'<meta name="vt-token" content="">', f'<meta name="vt-token" content="{self.server.token}">'.encode()),
                              "text/html; charset=utf-8")
        if path == "/score-print":
            return self._send(200, gui.WEB.joinpath("score-print.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/engine-worklet.js":
            return self._send(200, worklet_js(), "text/javascript; charset=utf-8")
        if path == "/web/libopenmpt.wasm":
            return self._send(200, gui.WEB.joinpath("libopenmpt.wasm").read_bytes(), "application/wasm")
        tab_assets = {"/web/tablature.js": "text/javascript; charset=utf-8",
                      "/web/engine-core.js": "text/javascript; charset=utf-8",
                      "/web/tablature.css": "text/css; charset=utf-8",
                      "/web/alphaTab.min.js": "text/javascript; charset=utf-8",
                      "/web/Bravura.woff2": "font/woff2",
                      "/web/licenses/Bravura-OFL.txt": "text/plain; charset=utf-8"}
        if path in tab_assets:
            return self._send(200, gui.WEB.joinpath(path.removeprefix('/web/')).read_bytes(), tab_assets[path])
        if path == "/icon.png":
            return self._send(200, gui.HTML.with_name("icon.png").read_bytes(), "image/png")
        if path == "/api/state":
            return self._send(200, {**(st.snapshot() if st else start_snapshot()), "library": self.lib_snapshot()})
        if path == "/api/score":
            if not st:
                return self._send(400, {"error": "Open a song first"})
            return self._send(200, st.score_view())
        if path == "/api/chord_library":
            from .chord_library import read_library
            try:
                return self._send(200, read_library())
            except (ValueError, OSError) as exc:
                return self._send(400, {"error": str(exc)})
        if path == "/api/library":
            self.lib()
            return self._send(200, self.lib_snapshot())
        if path == "/api/libmap":
            return self._send(200, self.lib().map())
        if path == "/api/libnear":  # the nearest sounds of an indexed one, for the map (nothing is added)
            from urllib.parse import parse_qs
            q = {k: v[0] for k, v in parse_qs(self.path.partition("?")[2]).items()}
            lib = self.lib()
            if not lib.has(q.get("path", "")):
                return self._send(404, {"error": "not in the library"})
            return self._send(200, {"near": lib.nearest(q["path"], max(1, min(50, int(q.get("k") or 8))))})
        if path == "/api/faust":
            from . import faust
            return self._send(200, {"have": faust.have(), "dir": str(faust.faust_dir()), "version": faust.VERSION,
                                    "job": Handler.faust_job})
        if path == "/web/faust-render.mjs":
            return self._send(200, gui.WEB.joinpath("faust-render.mjs").read_bytes(), "text/javascript; charset=utf-8")
        if path.startswith("/faust/"):  # the fetched faustwasm files, nothing else
            from . import faust
            base = faust.faust_dir().resolve()
            f = (base / path[7:]).resolve()
            if not f.is_relative_to(base) or not f.is_file():
                return self._send(404, {"error": "not found"})
            kind = {".js": "text/javascript; charset=utf-8", ".wasm": "application/wasm"}.get(f.suffix, "application/octet-stream")
            return self._send(200, f.read_bytes(), kind)
        if path == "/libwav":
            from urllib.parse import parse_qs
            f = parse_qs(self.path.partition("?")[2]).get("path", [""])[0]
            if not self.lib().has(f):  # a sound of the index, nothing else
                return self._send(404, {"error": "not in the library"})
            return self._send_file(f, "audio/wav")
        if path == "/api/effects":
            return self._send(200, gui.effect_help())
        if path == "/api/tools":  # the agent tools (agent.py), for the MCP server
            return self._send(200, {"tools": agent.tool_list(), "song": str(self.state.song_path) if self.state else None})
        if path == "/api/start":
            return self._send(200, start_snapshot())
        if path == '/api/score_collection':
            return self._send(200, self.collection())
        if path == "/api/rec":
            return self._send(200, self.rec_snapshot("devices=1" in self.path, spill=False))
        if st is None:
            return self._send(404, {"error": "no song open"})
        if path.startswith("/take/"):
            f = st.takes_dir / Path(unquote(path[6:])).name  # a file of the song's takes folder, nothing else
            return self._send_file(f, "audio/wav")
        if path.startswith("/api/autoloop/"):
            try:
                return self._send(200, st.auto_loop(int(path[14:])))
            except (ValueError, OSError, ImportError) as e:
                return self._send(404, {"error": f"{type(e).__name__}: {e}"})
        if path.startswith("/api/pattern/"):
            try:
                from urllib.parse import parse_qs
                occurrences = parse_qs(self.path.partition("?")[2]).get("occurrence", [])
                if len(occurrences) > 1:
                    raise ValueError('Give one occurrence')
                return self._send(200, st.pattern_rows(int(path[13:]), occurrences[0] if occurrences else None))
            except (ValueError, IndexError, AttributeError):
                return self._send(404, {"error": "no such pattern"})
        if path.startswith("/api/slices/"):
            from urllib.parse import parse_qs
            q = {k: v[0] for k, v in parse_qs(self.path.partition("?")[2]).items()}
            try:
                return self._send(200, st.slice_points(int(path[12:]), q.get("mode", "onsets"), float(q.get("value", 50)),
                                                       q.get("a"), q.get("b"), q.get("bpm"), q.get("snap")))
            except (ValueError, OSError, ImportError) as e:
                return self._send(404, {"error": f"{type(e).__name__}: {e}"})
        if path.startswith("/api/wave/"):
            from urllib.parse import parse_qs
            q = {k: v[0] for k, v in parse_qs(self.path.partition("?")[2]).items()}
            try:
                return self._send(200, st.sample_view(int(path[10:]), q.get("a", 0), q.get("b"), q.get("n", 1000)))
            except (ValueError, OSError, ImportError) as e:
                return self._send(404, {"error": f"{type(e).__name__}: {e}"})
        if path.startswith("/api/sounding/"):
            try:
                from urllib.parse import parse_qs
                q = {k: v[0] for k, v in parse_qs(self.path.partition('?')[2]).items()}
                return self._send(200, {"rows": st.sounding_rows(int(path[14:]), play_id=q.get('play_id'), revision=q.get('revision'))})
            except (ValueError, IndexError, AttributeError, TypeError) as exc:
                return self._send(404, {"error": str(exc) or "no such order"})
        if path.startswith("/wav/"):
            k = path[5:]
            r = st.renders.get(k)
            return self._send_file(r["file"], "audio/wav") if r and r["status"] == "ready" else self._send(404, {"error": "not rendered"})
        if path.startswith("/spec/"):
            r = st.renders.get(path[6:])
            if not r or r["status"] != "ready":
                return self._send(404, {"error": "not rendered"})
            p = Path(r["file"])
            try:
                png = spectrogram_png(str(p), f"{p.stat().st_mtime}:{p.stat().st_size}", "lin" if "scale=lin" in self.path else "log")
            except (OSError, ImportError, wave.Error, ValueError) as e:
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return self._send(200, png, "image/png")
        if path.startswith("/api/meters/"):  # a render's short-term loudness and stereo sums every 0.1 s (dsp.meter_series)
            r = st.renders.get(path[12:])
            if not r or r["status"] != "ready":
                return self._send(404, {"error": "not rendered"})
            p = Path(r["file"])
            try:
                return self._send(200, _meters(str(p), (p.stat().st_mtime_ns, p.stat().st_size)))
            except (OSError, ImportError, ValueError) as e:
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
        if path.startswith("/refspec/"):  # ?view=ref|delta&scale=log|lin
            try:
                png = st.reference_png(path[9:], "delta" if "view=delta" in self.path else "ref", "lin" if "scale=lin" in self.path else "log")
            except (OSError, ImportError, wave.Error, ValueError) as e:
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return self._send(200, png, "image/png")
        if path.startswith("/api/refdiff/"):
            try:
                *_, cols, gain, covered = st.reference_compare(path[13:])
            except (OSError, ImportError, wave.Error, ValueError) as e:
                return self._send(400, {"error": f"{type(e).__name__}: {e}"})
            live = sorted(v for v in cols if v is not None)
            return self._send(200, {"cols": cols, "median": live[len(live) // 2] if live else None, "gain_db": gain, "covered": covered})
        if path.startswith("/raw/"):
            try:
                c = st.raw_file(path[5:])  # with MATCH LEVEL on: a copy at the matched gain
            except (ValueError, IndexError):
                return self._send(404, {"error": "no such candidate"})
            except OSError as e:
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return self._send_file(c, "audio/wav")
        if path.startswith("/api/diff/") or path == "/api/mixdiff":
            try:
                return self._send(200, st.mix_diff() if path == "/api/mixdiff" else st.diff(st.cand(path[10:])))
            except (KeyError, ValueError, IndexError, TypeError, AttributeError, OSError) as e:
                return self._send(400, {"error": f"{type(e).__name__}: {e}"})
        if path == "/api/playback":
            from urllib.parse import parse_qs
            try:
                rates = parse_qs(self.path.partition("?")[2]).get("sample_rate", [])
                if len(rates) != 1:
                    raise ValueError('Give one sample_rate: the actual audio mixer rate')
                bundle = st.prepared_playback(int(rates[0]), whole=True)
                return self._send(200, {**bundle, "backing_it": base64.b64encode(bundle["backing_it"]).decode("ascii")})
            except (SongError, OSError, ValueError, OpenMPTError) as e:
                return self._send(400, {"error": "\n".join(getattr(e, "errors", []) or [str(e)])})
        if path == "/api/it":
            try:
                return self._send(200, st.live_it(), "application/octet-stream")
            except (SongError, OSError, ValueError, OpenMPTError) as e:
                return self._send(400, {"error": "\n".join(getattr(e, "errors", []) or [str(e)])})
        self._send(404, {"error": "not found"})

    @_guarded
    def do_POST(self):
        if self._foreign():
            return self._send(403, {"error": "not this app's page"})
        if not self._authorized():
            return self._send(401, {"error": "no token: this app's page and its MCP bridge send this launch's"})
        st = self.state
        n = int(self.headers.get("Content-Length") or 0)
        act = self.path.split("?")[0].rsplit("/", 1)[-1]
        cap = UPLOAD_BYTES if act == "upload" else BODY_BYTES
        if act == 'score_export':
            cap = (32 << 20) + 8192  # bounded 24-MiB BMP as base64 plus its JSON envelope
        if n > cap:  # a size from the request is what rfile.read allocates
            return self._send(413, {"error": f"the request is over {cap >> 20} MiB"})
        if act == "upload":  # raw WAV bytes, ?name=
            from urllib.parse import parse_qs
            try:
                name = parse_qs(self.path.partition("?")[2]).get("name", ["dropped.wav"])[0]
                return self._send(200, {"path": str(st.save_upload(name, self.rfile.read(n)))})
            except (AttributeError, ValueError, OSError, struct.error) as e:
                return self._send(400, {"error": f"{type(e).__name__}: {e}"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("the request body must be a JSON object")
            LABEL.name = _step_label(act, body)
            if act == "open":
                self.open_song(body["path"])
            elif act == 'score_collection':
                return self._send(200, self.collection(body))
            elif act == "chord_library":
                from .chord_library import edit_library
                return self._send(200, edit_library(body))
            elif act == "new":
                self.open_song(gui.create_song(body["path"], body.get("channels") or 8, body.get("sample") or None,
                                               template=body.get('template'), bars=body.get('bars', 4)))
            elif act == "import":  # a module converted beside itself and opened; `browse` picks it in a dialog
                src = self.browse(module=True) if body.get("browse") else body.get("path")
                if not src:
                    return self._send(200, {"path": None})
                native_tab = body.get('native_tab', False)
                if type(native_tab) is not bool:
                    raise ValueError('native_tab must be boolean')
                out, warnings = gui.import_beside(src, native_tab=native_tab, midi_options=body.get('midi_options'),gp_encoding=body.get('gp_encoding'))
                self.open_song(out)
                return self._send(200, {"path": str(out), "warnings": warnings})
            elif act == "browsewav":
                return self._send(200, {"path": self.browse(wav=True)})
            elif act == "relinkhints" and st is not None:  # PROJECT's missing samples: same-named WAVs in the library
                return self._send(200, st.relink_hints(self.lib()))
            elif act == "sf2presets":  # a SoundFont's presets for the Instruments tab (`browse` picks the bank first)
                from .sf2 import presets
                p = self.browse(sf2=True) if body.get("browse") else body.get("path")
                if not p:
                    return self._send(200, {"path": None})
                data = Path(str(p)).read_bytes()
                found = [[0, 0, "the patch"]] if data[:8] == b"GF1PATCH" else [list(x) for x in presets(data)]
                return self._send(200, {"path": str(p), "presets": found})
            elif act == "rec":  # {cmd: status} is the RECORD tab's poll (it may keep finished passes on disk)
                if body.get("cmd") == "status":
                    return self._send(200, self.rec_snapshot(bool(body.get("devices"))))
                return self._send(200, self.rec_command(body))
            elif act == "fetchfaust":  # faustwasm from npm, on a thread; GET /api/faust reports it
                return self._send(200, self.fetch_faust())
            elif act == "library":  # roots: the folders to index (saved); then a scan, waited for a moment
                lib = self.lib()
                if body.get("roots") is not None:
                    if lib.job and lib.job.is_alive():
                        raise ValueError("the library is busy: wait for the scan to finish")
                    lib.set_roots(body["roots"])
                res = lib.run(lib.scan, 0.5) if body.get("scan", True) else None
                return self._send(200, {"result": res, **self.lib_snapshot()})
            elif act == "tool":  # an agent tool run on the open song (the MCP server's calls)
                if body.get("run_id") is not None:
                    return self._send(200, gui.CHAT.remote_tool(st, str(body.get("name")), body.get("args") or {}, body["run_id"]))
                return self._send(200, agent.run(st, str(body.get("name")), body.get("args") or {}))
            elif act == "chatsettings":
                return self._send(200, agent.save_settings(body))
            elif act == "chatmodels":
                return self._send(200, agent.discover_models(body))
            elif act == "browse":
                p = self.browse()
                if p:
                    self.open_song(p)
                return self._send(200, {"path": p})
            elif st is None:
                return self._send(404, {"error": "no song open"})
            elif act == 'songshortcut':
                return self._send(200, self.save_song_shortcut())
            elif act == "agentallow":  # ALLOW REPLACE: the agent's next export_song may replace earlier exports
                if body.get("what") != "replace":
                    raise ValueError("only replace can be allowed")
                st.agent_allow["replace"] = time.monotonic() + 120
            elif act == "selection":
                st.selection = body.get("selection")
                return self._send(200, {"ok": True})
            elif act == "uistate":
                if body.get("song") != str(st.song_path):
                    raise ValueError("UI report belongs to another song")
                report = body.get("state")
                if not isinstance(report, dict) or len(json.dumps(report)) > 8192:
                    raise ValueError("invalid UI state report")
                with st.lock:
                    st.ui_state = {**report, "reported_at": time.time()}
                    return self._send(200, {"cue": st.cue})
            elif act == "chat":
                if body.get("stop"):
                    gui.CHAT.stop()
                elif body.get("compact"):
                    gui.CHAT.compact(st)
                elif body.get("clear"):
                    gui.CHAT.clear()
                else:
                    gui.CHAT.send(st, str(body.get("text") or "").strip(), body.get("context"))
            elif act == "slot":
                if not 1 <= int(body["slot"]) <= 99:
                    raise ValueError("a slot is 1-99")
                st.meta["slot"] = int(body["slot"])
                st.save_meta()
                st.queue_all()
            elif act == "orders":
                o = body.get("orders")
                if o is not None and not (isinstance(o, list) and len(o) == 2 and all(type(x) is int for x in o) and 0 <= o[0] < o[1]):
                    raise ValueError("the section is null or [first order, last order + 1]")
                if o is not None and st.mod is not None and st.mod.native_score is not None:
                    st._order_region(o)
                st.meta["orders"] = o
                st.save_meta()
                st.queue_all()
            elif act == "loop":
                st.set_loop(body)
            elif act == "reference":  # path or browse sets it, offset (ms) moves it, align (with key) lines it up, clear
                return self._send(200, st.set_reference(self.browse(wav=True) if body.get("browse") else body.get("path"), body))
            elif act == "mute":
                muted, solo = sorted({int(i) for i in body.get("muted", [])}), None if body.get("solo") is None else int(body["solo"])
                if any(not 0 <= i < 64 for i in muted + ([solo] if solo is not None else [])):  # patch_it writes header byte 0x40 + i
                    raise ValueError("a channel is 0-63")
                st.meta["muted"], st.meta["solo"] = muted, solo
                st.save_meta()
                st.queue_all()
            elif act == "add":
                return self._send(200, {"added": st.add_candidates(body["globs"])})
            elif act == "remove":
                st.remove_candidate(st.cand(body["id"]))
            elif act == "rate":
                c = st.cand(body["id"])
                if "stars" in body and (type(body["stars"]) is not int or not 0 <= body["stars"] <= 5):
                    raise ValueError("stars are a whole number 0-5")
                r = st.meta["ratings"].setdefault(c, {})
                for k, kind in (("stars", int), ("rejected", bool), ("note", str)):
                    if k in body:
                        r[k] = kind(body[k])
                st.save_meta()
            elif act == "similar":  # the slot's WAV, a candidate (id) or any WAV (path): its nearest become candidates
                q = body.get("path") or (st.cand(body["id"]) if body.get("id") is not None else st.current_file())
                if not q or not Path(q).exists():
                    raise ValueError("nothing to compare: the slot has no WAV on disk")
                lib = self.lib()
                res = lib.run(lambda: st.find_similar(lib, q, body.get("k") or 8), max(0.0, min(60.0, float(body.get("wait", 20)))))
                if res and res.get("error"):
                    return self._send(400, res)
                return self._send(200, res or {"pending": True, "report": lib.status.get("message")})
            elif act == "paint":  # the PAINT tab: previews answer with WAV bytes, the rest with a report
                res = st.paint(body)
                if isinstance(res, bytes):
                    return self._send(200, res, "audio/wav")
                return self._send(200, res)
            elif act == "place":  # a WAV the page uploaded (the FAUST tab's render): to the candidates or a new slot
                f = Path(str(body["path"])).resolve()
                if f.parent != st.base_dir or f.suffix.lower() != ".wav":
                    raise ValueError("only a WAV beside the song")
                report = f"{f.name} " + st.place_wav(f, body.get("dest"), bool(body.get("stereo")))
                if isinstance(body.get("faust"), dict):  # the FAUST tab's code and settings: its recipe entry
                    report += st.faust_recipe(f, body["faust"])
                return self._send(200, {"report": report})
            elif act == "faustcode":  # the FAUST tab's code as it is typed, kept with the song
                st.meta["faust_code"] = str(body.get("code") or "")[:200000]
                st.save_meta()
            elif act == "want":
                st.set_want(st.cand(body["id"]) if body.get("id") is not None else None)
            elif act == "match":  # MATCH LEVEL: playback only
                st.set_match(body.get("on"))
            elif act == "note":
                return self._send(200, st.add_note(body))
            elif act == "noteedit":
                st.edit_note(int(body["id"]), body)
            elif act == "retry":
                st.retry(st.cand(body["id"]))
            elif act == "apply":
                st.apply(st.cand(body["id"]))
            elif act == "mix":
                st.set_mix(body)
            elif act == "edit":  # one pattern (pattern, cells) or several in one step (patterns: [{pattern, cells}])
                groups = body["patterns"] if "patterns" in body else [body]
                occurrences = {}
                for group in groups:
                    index, occurrence = int(group["pattern"]), group.get("occurrence")
                    if occurrence is not None:
                        if index in occurrences and occurrences[index] != occurrence:
                            raise ValueError('One Pattern edit must use one occurrence per pattern')
                        occurrences[index] = occurrence
                with st.lock:
                    st.edit_patterns([(g["pattern"], g["cells"]) for g in groups],
                                     occurrences=occurrences,
                                     revision=body.get("revision"))
                    result = {"ok": True, "revision": st.text_sha()}
                return self._send(200, result)
            elif act == "transform":
                with st.lock:
                    st.edit_patterns([], transform=body, revision=body.get("revision"))
                    result = {"ok": True, "revision": st.text_sha()}
                return self._send(200, result)
            elif act == "pattern_copy":
                return self._send(200, st.pattern_clipboard(body))
            elif act == "pattern_paste":
                return self._send(200, st.paste_pattern_clipboard(body))
            elif act == "score":
                return self._send(200, _score_request(st, body, act))
            elif act == "score_command":
                return self._send(200, _score_request(st, body, act))
            elif act == "score_instrument":
                return self._send(200, st.score_instrument(body))
            elif act == "chord_recognize":
                return self._send(200, st.chord_suggestions(body))
            elif act == "chord_generate":
                return self._send(200, st.chord_suggestions(body, generate=True))
            elif act == "score_copy":
                return self._send(200, st.score_clipboard(body))
            elif act == "measure_copy":
                from .tablature import measure_segment
                with st.lock:
                    if body.get('revision') != st.text_sha() or st.dirty():
                        raise ValueError('The song changed; refresh before copying measures')
                    st._need_compiled()
                    return self._send(200, {'segment': measure_segment(st.song, body['from'], body['to'],
                        body.get('track'), copy_markers=body.get('copy_markers', False),
                        independent=body.get('independent', False), raw_patterns=st.mod.patterns)})
            elif act == 'score_template':
                from .tablature import score_template
                with st.lock:
                    if body.get('revision') != st.text_sha() or st.dirty():
                        raise ValueError('The song changed; refresh before saving a template')
                    return self._send(200, {'template': score_template(st.song)})
            elif act == "score_export":
                return self._send(200, self.save_score_export(body))
            elif act == "phrase":
                from .phrases import action
                return self._send(200, action(st, body))
            elif act == "section":
                st.section_edit(body)
            elif act == "songedit":
                return self._send(200, {"ok": True, **(st.song_edit(body["ops"]) or {})})
            elif act in ("undo", "redo"):
                st.undo(redo=act == "redo")
            elif act == "applymix":
                st.apply_mix()
            elif act == "reciperender":
                st.request_recipe_render(body.get("spec"))
            elif act == "recipewrite":
                st.recipe_write(body.get("spec"))
            elif act == "fetchsynth":
                st.request_fetch_synth(body.get("kind"))
            elif act == "external":
                return self._send(200, st.external_diff())
            elif act == "collect":
                return self._send(200, collect(st, body['destination'], bool(body.get('zip')), body.get('browser')))
            elif act == "relink":
                st.relink(body.get('num'), body.get('path'), body.get('links'))
            elif act == "projectsettings":
                settings = body.get('settings')
                if not isinstance(settings, dict) or len(json.dumps(settings)) > 2 * 1024 * 1024:
                    raise ValueError('Project browser settings must be an object under 2 MiB')
                st.meta['project_settings'] = settings
                st.save_meta()
            elif act == "materialize":
                st.materialize_pattern(body['pattern'])
            elif act == "trimhistory":
                st.trim_history(body.get('keep', 0))
            elif act == "checkpoint":
                return self._send(200, st.checkpoint(body.get('name', ''), body.get('action', 'save')))
            elif act == "reload":
                if body.get('token') and digest(st.song_path.read_bytes()) != body['token']:
                    raise ValueError('The external file changed again; compare it again before reloading')
                st.reload()
            elif act == 'export':
                st.request_export(body)
            elif act == 'cancelexport':
                st.cancel_export()
            elif act == "build":
                st.request_build(bool(body.get("render")))
            elif act == "stems":
                st.request_stems(body.get("fmt", "wav"), body.get("song", False), body.get("stems", True))
            else:
                return self._send(404, {"error": "unknown action"})
        except (KeyError, ValueError, IndexError, TypeError, AttributeError, OSError, SongError, OpenMPTError, struct.error) as e:
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})  # a bad request is answered, never dropped
        self._send(200, {"ok": True})


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False  # on Windows SO_REUSEADDR would let a second app take a port the first still listens on
    # Rapid edits replace WAV/score/image requests together while compilation holds the GIL.
    # The stdlib's five pending connections dropped localhost bursts before handlers could accept them.
    request_queue_size = 64

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.token = secrets.token_urlsafe(32)  # this launch's API token (Handler._authorized), in running.json and the URL

    def handle_error(self, request, client_address):
        """A page that went away mid-answer (closed, reloaded, a seek that cancelled a request) is no error to print."""
        if not isinstance(sys.exc_info()[1], ConnectionError):
            gui._log.exception("A request from %s failed", client_address[0])


def make_server(port=0):
    """The HTTP server on `port`; 0 means PORT when it is free (a second app window gets any free port). Each one makes
    its own API token (`token`)."""
    if not port:
        try:
            return _Server(("127.0.0.1", PORT), Handler)
        except OSError:
            pass
    return _Server(("127.0.0.1", port), Handler)
