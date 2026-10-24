"""Minimal ctypes binding to libopenmpt: load, inspect, render."""
import ctypes as C
import copy
import os
import sys
from fractions import Fraction
from pathlib import Path

# In a PyInstaller build the DLLs are unpacked next to the bundled package (see tools/build_exe.py).
_VENDOR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "vendor"
_LOG_FUNC = C.CFUNCTYPE(None, C.c_char_p, C.c_void_p)


def _load_lib():
    override = os.environ.get("LIBOPENMPT")
    if override:
        return C.CDLL(override)
    if sys.platform == "win32":
        os.add_dll_directory(str(_VENDOR))
        return C.CDLL(str(_VENDOR / "libopenmpt.dll"))
    for name in ("libopenmpt.so.0", "libopenmpt.so", "libopenmpt.dylib"):
        try:
            return C.CDLL(name)
        except OSError:
            pass
    raise OSError("libopenmpt not found; set LIBOPENMPT to the library path")


_lib = _load_lib()
_P = C.c_void_p
for fname, res, args in [
    ("openmpt_module_create_from_memory2", _P, [_P, C.c_size_t, _LOG_FUNC, _P, _P, _P, C.POINTER(C.c_int), C.POINTER(C.c_char_p), _P]),
    ("openmpt_module_destroy", None, [_P]),
    ("openmpt_free_string", None, [_P]),
    ("openmpt_get_library_version", C.c_uint32, []),
    ("openmpt_module_get_duration_seconds", C.c_double, [_P]),
    ("openmpt_module_set_position_order_row", C.c_double, [_P, C.c_int32, C.c_int32]),
    ("openmpt_module_get_metadata", _P, [_P, C.c_char_p]),
    ("openmpt_module_get_num_channels", C.c_int32, [_P]),
    ("openmpt_module_get_num_instruments", C.c_int32, [_P]),
    ("openmpt_module_get_num_samples", C.c_int32, [_P]),
    ("openmpt_module_get_num_patterns", C.c_int32, [_P]),
    ("openmpt_module_get_num_orders", C.c_int32, [_P]),
    ("openmpt_module_get_order_pattern", C.c_int32, [_P, C.c_int32]),
    ("openmpt_module_get_pattern_num_rows", C.c_int32, [_P, C.c_int32]),
    ("openmpt_module_get_instrument_name", _P, [_P, C.c_int32]),
    ("openmpt_module_get_sample_name", _P, [_P, C.c_int32]),
    ("openmpt_module_get_pattern_name", _P, [_P, C.c_int32]),
    ("openmpt_module_get_channel_name", _P, [_P, C.c_int32]),
    ("openmpt_module_format_pattern_row_channel", _P, [_P, C.c_int32, C.c_int32, C.c_int32, C.c_size_t, C.c_int]),
    ("openmpt_module_get_pattern_row_channel_command", C.c_uint8, [_P, C.c_int32, C.c_int32, C.c_int32, C.c_int]),
    ("openmpt_module_set_repeat_count", C.c_int, [_P, C.c_int32]),
    ("openmpt_module_set_render_param", C.c_int, [_P, C.c_int, C.c_int32]),
    ("openmpt_module_ctl_set_integer", C.c_int, [_P, C.c_char_p, C.c_int64]),
    ("openmpt_module_read_interleaved_stereo", C.c_size_t, [_P, C.c_int32, C.c_size_t, C.POINTER(C.c_int16)]),
    ("openmpt_module_read_interleaved_float_stereo", C.c_size_t, [_P, C.c_int32, C.c_size_t, C.POINTER(C.c_float)]),
    ("openmpt_module_get_current_order", C.c_int32, [_P]),
    ("openmpt_module_get_current_row", C.c_int32, [_P]),
    ("openmpt_module_get_current_estimated_bpm", C.c_double, [_P]),
    ("openmpt_module_get_current_speed", C.c_int32, [_P]),
]:
    f = getattr(_lib, fname)
    f.restype, f.argtypes = res, args


def _str(ptr):
    if not ptr:
        return ""
    try:
        return C.string_at(ptr).decode("utf-8", "replace")
    finally:
        _lib.openmpt_free_string(ptr)


def library_version():
    v = _lib.openmpt_get_library_version()
    return f"{v >> 24}.{(v >> 16) & 0xFF}.{v & 0xFFFF}"


class OpenMPTError(Exception):
    pass


class _Ctl(C.Structure):
    _fields_ = [("ctl", C.c_char_p), ("value", C.c_char_p)]


class _ExactClock(C.Structure):
    _fields_ = [("configure", C.CFUNCTYPE(C.c_int, _P, C.c_int))]


class _ParentBatch(C.Structure):
    _fields_ = [("dispatch", C.CFUNCTYPE(C.c_int, _P, C.c_int32, C.c_int32, C.POINTER(C.c_int64),
                                        C.c_int32, C.POINTER(C.c_int32), C.POINTER(C.c_int64)))]

class _ParentGroups(C.Structure):
    _fields_ = [("dispatch", C.CFUNCTYPE(C.c_int, _P, C.c_int32, C.c_int32, C.POINTER(C.c_int64),
                                        C.c_int32, C.POINTER(C.c_int32), C.c_int32, C.POINTER(C.c_int64)))]

class _HeldScore(C.Structure):
    _fields_ = [("dispatch", C.CFUNCTYPE(C.c_int, _P, C.c_int32, C.c_int32, C.POINTER(C.c_int64),
                                        C.c_int32, C.POINTER(C.c_int32), C.POINTER(C.c_int32),
                                        C.c_int32, C.POINTER(C.c_int64)))]


class _ScoreContexts(C.Structure):
    _fields_ = [("dispatch", C.CFUNCTYPE(C.c_int, _P, C.c_int32, C.c_int32, C.POINTER(C.c_int64),
                                        C.c_int32, C.POINTER(C.c_int64), C.c_int32, C.POINTER(C.c_int64),
                                        C.POINTER(C.c_int32), C.c_int32, C.POINTER(C.c_int64)))]


class _Tail(C.Structure):
    _fields_ = [("begin", C.CFUNCTYPE(C.c_int, _P))]


class _Pitch(C.Structure):
    _fields_ = [("set", C.CFUNCTYPE(C.c_int, _P, C.c_int64, C.c_double))]


class _Gain(C.Structure):
    _fields_ = [("set", C.CFUNCTYPE(C.c_int, _P, C.c_int64, C.c_double))]


# libopenmpt computes a song's duration when asked, at the rate it mixes at (timed_at), not once at load at 48 kHz
_INITIAL = (_Ctl * 2)(_Ctl(b"load.skip_subsongs_init", b"1"), _Ctl(None, None))


def mix_rate(rate, oversample):
    """The rate libopenmpt mixes at for a render at `rate`: `oversample` times it, when numpy is there to band-limit it
    back down (LoadedModule.render)."""
    try:
        import numpy  # noqa: F401
        from . import resample  # noqa: F401
    except ImportError:
        return rate
    return rate * max(1, int(oversample))


class LoadedModule:
    """A module loaded by libopenmpt. Use as a context manager."""

    def __init__(self, data: bytes, rate=44100, oversample=2, *, plan=None):
        """`plan` must accompany its prepared backing IT and use the actual mix_rate(rate, oversample).
        Native order seeks reconstruct both backing and score state from the start."""
        self._mod = self._ext = None
        self._native = plan is not None
        if self._native:
            self._set_plan(plan, mix_rate(rate, oversample))
        self.log = []
        self._cb = _LOG_FUNC(lambda msg, _user, log=self.log: log.append(msg.decode("utf-8", "replace")))
        err = C.c_int(0)
        errmsg = C.c_char_p()
        self._buf = C.create_string_buffer(data, len(data))
        try:
            create = _lib.openmpt_module_create_from_memory2
            if self._native:
                for name, result, args in [
                    ('create_from_memory', _P, create.argtypes),
                    ('get_module', _P, [_P]), ('destroy', None, [_P]),
                    ('get_interface', C.c_int, [_P, C.c_char_p, _P, C.c_size_t]),
                ]:
                    function = getattr(_lib, 'openmpt_module_ext_' + name, None)
                    if function is None:
                        raise OpenMPTError('Native score playback requires libopenmpt extension support')
                    function.restype, function.argtypes = result, args
                create = _lib.openmpt_module_ext_create_from_memory
            handle = create(self._buf, len(data), self._cb, None, None, None,
                            C.byref(err), C.byref(errmsg), C.cast(_INITIAL, _P))
            if self._native:
                self._ext = handle
                self._mod = _lib.openmpt_module_ext_get_module(handle) if handle else None
            else:
                self._mod = handle
            if not self._mod:
                raise OpenMPTError(f"libopenmpt could not load module (error {err.value}): "
                                   f"{errmsg.value.decode() if errmsg.value else ''} {' / '.join(self.log)}".strip())
            if self._native:
                clock = self._interface(b'vt_exact_clock', _ExactClock)
                self._parent = self._interface(b'vt_parent_batch', _ParentBatch)
                self._tail = self._interface(b'vt_tail', _Tail)
                self._pitch = self._interface(b'vt_pitch', _Pitch) if self._has_pitch else None
                self._gain = self._interface(b'vt_gain', _Gain) if self._has_gain else None
                self._groups = self._interface(b'vt_parent_groups', _ParentGroups) if self._has_groups else None
                self._held = self._interface(b'vt_held_score', _HeldScore) if self._has_holds else None
                self._contexts = self._interface(b'vt_score_contexts', _ScoreContexts) if self._has_contexts else None
                channels = _lib.openmpt_module_get_num_channels(self._mod)
                if any(e['ch'] >= channels for e in self._events if e['type'] == 'note_on'):
                    raise ValueError('Native score channel is absent from its backing IT')
                if not clock.configure(self._ext, 1):
                    raise OpenMPTError('Native score exact clock configuration failed')
            self.timed_at(rate, oversample)
            if self._native and self._has_groups:
                # Groups require an initialized stereo mixer, without preparing
                # the first row or consuming PCM.
                zero = (C.c_int16 * 2)()
                _lib.openmpt_module_read_interleaved_stereo(self._mod, self._native_rate, 0, zero)
                result = (self._contexts.dispatch(self._ext, self._native_rate, 0, self._batch_offs,
                                                 0, self._batch_closes, 0, self._batch_keys, self._batch_notes, 0, self._batch_ids)
                          if self._has_contexts else
                          self._held.dispatch(self._ext, self._native_rate, 0, self._batch_offs,
                                             0, self._batch_notes, self._batch_holds, 0, self._batch_ids)
                          if self._has_holds else
                          self._groups.dispatch(self._ext, self._native_rate, 0, self._batch_offs,
                                                0, self._batch_notes, 0, self._batch_ids))
                if result != 1:
                    raise OpenMPTError('Native score group initialization failed')
        except BaseException:
            self.close()
            raise
        finally:
            if errmsg:
                _lib.openmpt_free_string(C.cast(errmsg, _P))

    def _set_plan(self, plan, mixed):
        from .tablature import TempoClock
        if plan.get('version') != 1 or type(plan.get('sample_rate')) is not int:
            raise ValueError('Invalid native score plan version/sample rate')
        self._native_rate = plan['sample_rate']
        if not 8000 <= self._native_rate <= 384000 or self._native_rate != mixed:
            raise ValueError('Native score plan sample rate must match actual mixer rate (including oversampling)')
        self._native_end = plan['duration']['frames']
        if type(self._native_end) is not int or not 1 <= self._native_end <= 2**53 - 1:
            raise ValueError('Invalid native score duration')
        self._events = tuple(copy.deepcopy(event) for event in plan['events'])
        if len(self._events) > 200000:
            raise ValueError('Native score plan has too many events')
        active, seen, previous = {}, set(), (-1, -1)
        ranks = {'note_off': 0, 'note_on': 1, 'pitch': 2, 'gain': 3}
        self._last_owned, self._has_pitch = {}, False
        self._has_gain = self._has_groups = self._has_holds = self._has_contexts = False
        contexts, closing, frame_heads, last_context = {}, set(), set(), 0
        context_parents = {e.get('ch') for e in self._events if 'context' in e}
        layer_counts = {}
        parents, off_count = set(), 0
        for index, event in enumerate(self._events):
            frame, kind, identity = event['frame'], event['type'], event['id']
            if (type(frame) is not int or not 0 <= frame <= self._native_end or
                    not isinstance(kind, str) or kind not in ranks or not isinstance(identity, str) or not identity):
                raise ValueError('Invalid native score event')
            key = (frame, ranks[kind])
            if key < previous:
                raise ValueError('Native score events must be ordered by frame, releases, attacks, pitch')
            if frame != previous[0]:
                for context in closing:
                    contexts.pop(context)
                closing, frame_heads = set(), set()
                parents, off_count = set(), 0
            previous = key
            self._last_owned[identity] = index
            if kind != 'note_on' and 'layers' in event:
                raise ValueError('Native score layers belong only to attacks')
            if 'hold' in event and (kind != 'note_on' or type(event['hold']) is not bool):
                raise ValueError('Native score hold must be a boolean on an attack')
            if any(k in event for k in ('context', 'context_open', 'context_close')):
                if (kind != 'note_on' or type(event.get('context')) is not int or not 1 <= event['context'] <= 2147483647 or
                        type(event.get('context_open')) is not bool or type(event.get('context_close')) is not bool):
                    raise ValueError('Invalid native score context fields')
            if kind == 'pitch':
                semitones = event.get('semitones')
                if identity not in seen or type(semitones) not in (int, float) or not -12 <= semitones <= 12:
                    raise ValueError('Invalid native score pitch control identity/semitones')
                self._has_pitch = True
                continue
            if kind == 'gain':
                gains = event.get('gains')
                if (identity not in seen or not isinstance(gains, list) or len(gains) != layer_counts[identity] or
                        any(type(g) not in (int, float) or not 0 <= g <= 1 for g in gains)):
                    raise ValueError('Invalid native score gain control identity/values')
                self._has_gain = True
                continue
            for field, low, high in [('ch', 0, 63), ('pitch', 0, 119), ('source_instrument', 0, 99)]:
                if type(event[field]) is not int or not low <= event[field] <= high:
                    raise ValueError('Invalid native score ' + field)
            volume = event['volume']
            if volume is not None and (type(volume) is not int or not 0 <= volume <= 64):
                raise ValueError('Invalid native score volume')
            if kind == 'note_on':
                context = event.get('context')
                if context is not None:
                    self._has_contexts = self._has_groups = True
                    if context in frame_heads or not event['source_instrument'] or event.get('hold'):
                        raise ValueError('Native score context requires one explicit attack per head/frame, without hold')
                    binding = (event['ch'], event['source_instrument'])
                    if event['context_open']:
                        if context <= last_context or len(contexts) >= 64:
                            raise ValueError('Native score context key/capacity violation')
                        contexts[context], last_context = binding, context
                    elif contexts.get(context) != binding:
                        raise ValueError('Native score context is closed or its parent/source changed')
                    frame_heads.add(context)
                    if event['context_close']:
                        closing.add(context)
                elif event['ch'] in context_parents:
                    raise ValueError('Every attack on a context parent needs its own head context')
                if event.get('hold'):
                    if not event['source_instrument'] or 'layers' in event or 'source_id' in event:
                        raise ValueError('Native score hold requires an explicit ordinary attack')
                    self._has_holds = self._has_groups = True
                if 'layers' in event:
                    layers = event['layers']
                    if (not isinstance(layers, list) or not 1 <= len(layers) <= 3 or
                            any(not isinstance(layer, dict) or set(layer) != {'pitch', 'velocity'} or
                                type(layer['pitch']) is not int or not 0 <= layer['pitch'] <= 119 or
                                type(layer['velocity']) is not int or not 0 <= layer['velocity'] <= 127
                                for layer in layers)):
                        raise ValueError('Invalid native score layers')
                    self._has_groups = self._has_gain = True
                velocity = event.get('velocity')
                if velocity is not None:
                    if type(velocity) is not int or not 0 <= velocity <= 127:
                        raise ValueError('Invalid native score velocity')
                    self._has_gain = True
                parent = ('context', context) if context is not None else ('parent', event['ch'])
                if identity in seen or frame == self._native_end or parent in parents or len(parents) >= 64:
                    raise ValueError('Invalid native score attack identity/boundary')
                parents.add(parent)
                active[identity] = frame
                layer_counts[identity] = len(event.get('layers', (None,)))
                seen.add(identity)
            elif identity not in active or frame <= active.pop(identity):
                raise ValueError('Native score release must follow its attack')
            else:
                off_count += layer_counts[identity]
                if off_count > 256:
                    raise ValueError('Too many simultaneous native score releases')
        if active:
            raise ValueError('Native score plan is missing releases')
        if set(contexts) - closing:
            raise ValueError('Native score plan is missing context closes')
        if self._has_contexts and self._has_holds:
            raise ValueError('Native score context plans must include held parents as contexts')
        # Keep only the paired scheduler inputs, independently of the caller's mutable song/view.
        self._native_plan = dict(version=1, sample_rate=self._native_rate,
                                 duration={'frames': self._native_end}, events=self._events,
                                 **copy.deepcopy({key: plan[key] for key in ('tempo', 'tempos', 'row_step', 'occurrences') if key in plan}))
        self._native_clock = TempoClock(plan.get('tempo', 125), plan.get('tempos'))
        self._event_index = self._native_frame = 0
        self._handles = {}
        self._in_tail = False
        self._native_stop = None
        self._batch_offs = (C.c_int64 * 256)()
        self._batch_notes = (C.c_int32 * (512 if self._has_contexts else 448 if self._has_groups else 256))()
        self._batch_ids = (C.c_int64 * (192 if self._has_groups else 64))()
        self._batch_holds = (C.c_int32 * 64)()
        self._batch_keys = (C.c_int64 * 64)()
        self._batch_closes = (C.c_int64 * 64)()

    def _interface(self, name, structure):
        interface = structure()
        if not _lib.openmpt_module_ext_get_interface(self._ext, name, C.byref(interface), C.sizeof(interface)) or not all(
                getattr(interface, field) for field, _ in structure._fields_):
            raise OpenMPTError('Native score playback requires patched libopenmpt interface ' + name.decode())
        return interface

    def _native_boundary(self):
        frame = self._native_frame
        if self._in_tail:
            return
        due = self._event_index < len(self._events) and self._events[self._event_index]['frame'] == frame
        ending = frame == (self._native_stop if self._native_stop is not None else self._native_end)
        if frame != 0 and not due and not ending:
            return
        if ending:
            if not self._tail.begin(self._ext):
                raise OpenMPTError('Native score tail transition failed')
            self._in_tail = True
        stop, off_count, note_count, close_count = self._event_index, 0, 0, 0
        while stop < len(self._events) and self._events[stop]['frame'] == frame:
            stop += 1
        grouped = self._has_contexts or self._has_holds or not ending and any('layers' in e for e in self._events[self._event_index:stop])
        for event in self._events[self._event_index:stop]:
            if event['type'] == 'note_on':
                if ending:
                    continue  # The range's exclusive endpoint must not attack a note from the next region.
                volume = -1 if event['volume'] is None else event['volume']
                if grouped:
                    pitches = [layer['pitch'] for layer in event['layers']] if 'layers' in event else [event['pitch']]
                    stride = 8 if self._has_contexts else 7
                    self._batch_notes[note_count * stride:note_count * stride + 7] = (
                        event['ch'], event['source_instrument'], volume, len(pitches), *(pitches + [0] * (3 - len(pitches))))
                    if self._has_contexts:
                        self._batch_keys[note_count] = event.get('context', 0)
                        self._batch_notes[note_count * stride + 7] = (1 if event['context_open'] else 2) if 'context' in event else 0
                        if event.get('context_close'):
                            self._batch_closes[close_count] = event['context']
                            close_count += 1
                else:
                    self._batch_notes[note_count * 4:note_count * 4 + 4] = (
                        event['ch'], event['pitch'], event['source_instrument'], volume)
                self._batch_holds[note_count] = int(event.get('hold', False))
                note_count += 1
            elif event['type'] == 'note_off':
                handles = self._handles.get(event['id'], 0)
                for handle in handles if isinstance(handles, tuple) else (handles,):
                    self._batch_offs[off_count] = handle
                    off_count += 1
        # One call owns releases, row-note injection and ordinary raw effects in their native order.
        result = (self._contexts.dispatch(self._ext, self._native_rate, off_count, self._batch_offs,
                                         close_count, self._batch_closes, note_count, self._batch_keys,
                                         self._batch_notes, note_count * 3, self._batch_ids) if self._has_contexts else
                  self._held.dispatch(self._ext, self._native_rate, off_count, self._batch_offs,
                                     note_count, self._batch_notes, self._batch_holds, note_count * 3, self._batch_ids)
                  if self._has_holds else
                  self._groups.dispatch(self._ext, self._native_rate, off_count, self._batch_offs,
                                       note_count, self._batch_notes, note_count * 3, self._batch_ids) if grouped else
                  self._parent.dispatch(self._ext, self._native_rate, off_count, self._batch_offs,
                                        note_count, self._batch_notes, self._batch_ids))
        if result != 1:
            self.close()  # Runtime backing conflicts may have advanced the boundary; this consumer cannot be reused.
            raise OpenMPTError('Native score event batch failed')
        note_index = 0
        while self._event_index < stop:
            event = self._events[self._event_index]
            if event['type'] == 'note_on':
                if ending:
                    self._event_index += 1
                    continue
                layers = event.get('layers')
                offset = note_index * 3 if grouped else note_index
                handles = tuple(self._batch_ids[offset:offset + len(layers)]) if layers else (self._batch_ids[offset],)
                if any(handle < 0 for handle in handles) or any(handles) and not all(handles):
                    self.close()
                    raise OpenMPTError('Native score note failed: ' + event['id'])
                self._handles[event['id']] = handles if layers else handles[0]
                note_index += 1
                for i, handle in enumerate(handles):
                    velocity = layers[i]['velocity'] if layers else event.get('velocity')
                    if handle and velocity is not None and self._gain.set(self._ext, handle, velocity / 127) != 1:
                        self.close()  # The parent batch already advanced; never emit unscaled PCM or retry.
                        raise OpenMPTError('Native score gain initialization failed: ' + event['id'])
            elif event['type'] == 'pitch':
                handles = self._handles.get(event['id'], 0)
                if isinstance(handles, tuple):
                    self._handles[event['id']] = tuple(handle if handle and self._pitch.set(self._ext, handle, event['semitones'])
                                                       else 0 for handle in handles)
                elif handles and not self._pitch.set(self._ext, handles, event['semitones']):
                    self._handles.pop(event['id'], None)  # Retired voice; never redirect to a reused parent slot.
            elif event['type'] == 'gain':
                handles = self._handles.get(event['id'], 0)
                group = handles if isinstance(handles, tuple) else (handles,)
                updated = tuple(handle if handle and self._gain.set(self._ext, handle, gain) else 0
                                for handle, gain in zip(group, event['gains']))
                self._handles[event['id']] = updated if isinstance(handles, tuple) else updated[0]
            if self._last_owned[event['id']] == self._event_index:
                self._handles.pop(event['id'], None)
            self._event_index += 1
        if ending:
            self._event_index = len(self._events)  # Ring the captured voices without later arrangement events.

    def _native_read(self, read, count, buf):
        """One bounded read, shared by rendering and discard-only seek replay."""
        self._native_boundary()
        if not self._in_tail:
            boundary = self._events[self._event_index]['frame'] if self._event_index < len(self._events) else self._native_end
            if self._native_stop is not None:
                boundary = min(boundary, self._native_stop)
            count = min(count, boundary - self._native_frame)
        n = read(self._mod, self._native_rate, count, buf)
        if n == 0 and not self._in_tail:
            raise OpenMPTError('Native score backing ended before the planned tail boundary')
        self._native_frame += n
        self._native_boundary()
        return n

    def _native_order_frame(self, order, row):
        plan = self._native_plan
        occurrences = plan.get('occurrences', ())
        if isinstance(row, (list, tuple)) and len(row) == 2 and all(type(x) is int for x in row) and row[1] > 0:
            row = Fraction(*row)
        if type(order) is not int or not isinstance(row, (int, Fraction)) or isinstance(row, bool) or not 0 <= order <= len(occurrences) or row < 0:
            raise ValueError('Invalid native score order/row seek')
        if not occurrences:
            raise ValueError('Native score seek requires occurrence coordinates')
        if order == len(occurrences) and row == 0:
            return self._native_end
        if order == len(occurrences):
            raise ValueError('Native score end position has no rows')
        step = Fraction(*plan['row_step'])
        occurrence = occurrences[order]
        local = row * step
        if step <= 0 or local >= Fraction(*occurrence['duration']):
            raise ValueError('Native score seek row is outside its occurrence')
        exact = self._native_clock.seconds_at(Fraction(*occurrence['at']) + local) * self._native_rate
        frame = exact.numerator // exact.denominator + (2 * (exact.numerator % exact.denominator) >= exact.denominator)
        if not 0 <= frame <= self._native_end:
            raise ValueError('Native score seek is outside its arrangement')
        return frame

    def timed_at(self, rate=44100, oversample=2):
        """Positions and durations from here on as a render at `rate` (and `oversample`) plays them. libopenmpt counts each
        tick in whole samples of the rate it mixes at and takes positions and durations at the last rate it mixed at
        (48 kHz before any read): at most tempos (all but those dividing 1500) a position taken at another rate drifts
        from the audio, by 0.07 % at tempo 137 (a game loop 114 frames short in 3.5 s). A read of no frames sets it."""
        if self._native:
            if mix_rate(rate, oversample) != self._native_rate:
                raise ValueError('Native score plan sample rate must match actual mixer rate (including oversampling)')
            return
        buf = (C.c_int16 * 2)()
        _lib.openmpt_module_read_interleaved_stereo(self._mod, mix_rate(rate, oversample), 0, buf)

    @classmethod
    def from_file(cls, path):
        return cls(Path(path).read_bytes())

    def close(self):
        if self._ext:
            _lib.openmpt_module_ext_destroy(self._ext)
            self._ext = self._mod = None
        elif self._mod:
            _lib.openmpt_module_destroy(self._mod)
            self._mod = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def metadata(self, key):
        return _str(_lib.openmpt_module_get_metadata(self._mod, key.encode()))

    def cell_text(self, pattern, row, channel):
        """Pattern cell as libopenmpt formats it, e.g. 'C-5 01 v64 A06'."""
        return _str(_lib.openmpt_module_format_pattern_row_channel(self._mod, pattern, row, channel, 0, 1))

    def cell(self, pattern, row, channel):
        """Raw cell values as libopenmpt stores them: note is IT note + 1 (0 = none, 255 = off, 254 = cut),
        volume is the volume-column value; effect letter comes from the formatted text."""
        g = lambda cmd: _lib.openmpt_module_get_pattern_row_channel_command(self._mod, pattern, row, channel, cmd)
        text = self.cell_text(pattern, row, channel)
        return {"note": g(0), "instrument": g(1), "volume": g(4), "effect_text": text[-3:], "param": g(5), "text": text}

    def duration(self):
        """Seconds one pass of the song plays for, as libopenmpt computes it (at the rate of timed_at)."""
        return self._native_end / self._native_rate if self._native else _lib.openmpt_module_get_duration_seconds(self._mod)

    def order_start(self, order, row=0, *, cancel=None):
        """Second at which `row` of `order` plays in one pass of the song, as libopenmpt plays it (speed, tempo, break and
        jump effects included). Seeks the module there. A position that never plays comes back as 0.0 (libopenmpt seeks
        into the hidden subsong that starts at an order playback never enters) or as the whole duration (a skipped row).
        Native plans instead replay both streams to the exact rational frame; invalid positions refuse.
        Cancellation during native replay leaves this module's old position and voices intact."""
        if self._native:
            target = self._native_order_frame(order, row)
            if cancel is not None and cancel():
                raise ValueError('Export cancelled')
            with LoadedModule(self._buf.raw, self._native_rate, 1, plan=self._native_plan) as replay:
                _lib.openmpt_module_set_render_param(replay._mod, 3, 8)
                _lib.openmpt_module_set_repeat_count(replay._mod, 0)
                _lib.openmpt_module_ctl_set_integer(replay._mod, b'dither', 0)
                buf = (C.c_float * (4096 * 2))()
                while replay._native_frame < target:
                    if cancel is not None and cancel():
                        raise ValueError('Export cancelled')
                    replay._native_read(_lib.openmpt_module_read_interleaved_float_stereo,
                                        min(4096, target - replay._native_frame), buf)
                replay._native_boundary()  # Frame-zero events and events exactly at the target are ready for the next read.
                if cancel is not None and cancel():
                    raise ValueError('Export cancelled')
                self.close()
                self.__dict__.update(replay.__dict__)
                replay._mod = replay._ext = None  # Ownership transferred; its context manager must not destroy our module.
            return target / self._native_rate
        return _lib.openmpt_module_set_position_order_row(self._mod, order, row)

    def row_starts(self, rate=44100, oversample=2, block=16):
        """[(second, order, row, bpm, speed)] for every row as one pass of the song plays it (jumps, breaks and loops as
        libopenmpt plays them), at the timing of a render at `rate` and `oversample`: the module is played through in
        blocks of `block` frames and a row is timed where it is first seen (at most a block late: 0.2 ms at 16 frames
        of 88.2 kHz). `bpm` is libopenmpt's estimate while the row plays (OpenMPT's GetCurrentBPM)."""
        if self._native:
            raise ValueError('Native score row scanning requires paired replay and is not supported')
        # ponytail: plays the song through (about 2 s for 3 minutes); a tick-exact time needs a libopenmpt position call
        mixed = mix_rate(rate, oversample)
        _lib.openmpt_module_set_repeat_count(self._mod, 0)
        self.timed_at(rate, oversample)
        end = _lib.openmpt_module_get_duration_seconds(self._mod)  # libopenmpt plays into the row it loops back to
        buf = (C.c_int16 * (block * 2))()
        frames, last, rows = 0, None, []
        while frames < end * mixed:
            cur = (_lib.openmpt_module_get_current_order(self._mod), _lib.openmpt_module_get_current_row(self._mod))
            if cur != last:
                rows.append([frames / mixed, *cur, None, None])
                last = cur
            n = _lib.openmpt_module_read_interleaved_stereo(self._mod, mixed, block, buf)
            if rows[-1][3] is None:  # the row's tempo, once it plays (before, libopenmpt's estimate is the last row's)
                rows[-1][3] = _lib.openmpt_module_get_current_estimated_bpm(self._mod)
                rows[-1][4] = max(1, _lib.openmpt_module_get_current_speed(self._mod))
            if not n:
                break
            frames += n
        self.end = min(end, frames / mixed)
        return [tuple(r) for r in rows if r[0] < self.end]

    def info(self):
        m = self._mod
        return {
            "title": self.metadata("title"),
            "type": self.metadata("type"),
            "tracker": self.metadata("tracker"),
            "duration_seconds": round(self.duration(), 3),
            "channels": _lib.openmpt_module_get_num_channels(m),
            "instruments": _lib.openmpt_module_get_num_instruments(m),
            "samples": _lib.openmpt_module_get_num_samples(m),
            "patterns": _lib.openmpt_module_get_num_patterns(m),
            # libopenmpt uses 65534/65535 internally for the IT '+++' (254) and '---' (255) markers
            "orders": [{65534: 254, 65535: 255}.get(o, o) for o in
                       (_lib.openmpt_module_get_order_pattern(m, i) for i in range(_lib.openmpt_module_get_num_orders(m)))],
            "pattern_rows": [_lib.openmpt_module_get_pattern_num_rows(m, i) for i in range(_lib.openmpt_module_get_num_patterns(m))],
            "instrument_names": [_str(_lib.openmpt_module_get_instrument_name(m, i)) for i in range(_lib.openmpt_module_get_num_instruments(m))],
            "sample_names": [_str(_lib.openmpt_module_get_sample_name(m, i)) for i in range(_lib.openmpt_module_get_num_samples(m))],
            "warnings": list(self.log),
        }

    ENDLESS_SECONDS = 600       # what a render that repeats forever (repeat=-1) stops at
    SAFETY_SECONDS = 3 * 3600   # the longest render of a song that ends

    def render(self, rate=44100, repeat=0, max_seconds=None, dither=0, oversample=2, cancel=None, floats=False, end=None):
        """Render to interleaved int16 stereo frames (bytes), or with `floats` float32 ones (libopenmpt's float mix, full
        scale 1.0, for 24-bit and float exports). repeat=0 plays once, N repeats N more times.
        `max_seconds` caps the render; None renders the whole song: its duration times the passes, plus a margin for
        the tail, never more than SAFETY_SECONDS; repeat=-1 (forever) stops at ENDLESS_SECONDS.
        dither=0 (none) makes renders bit-identical between runs; libopenmpt's own default (1) adds random dither.
        `oversample` > 1 mixes at that multiple of `rate` and band-limits the result back down (a windowed-sinc
        low-pass at 0.45 of `rate`, then decimation), so whatever the mixer puts above the Nyquist frequency of `rate`
        (samples played above their own rate, interpolation images) is removed instead of folding back into the audible
        range as aliasing. It needs numpy; without it the module is mixed at `rate` directly. The mixer's own
        interpolation is set to its longest filter (an 8-tap windowed sinc).
        Native renders continue from the current paired position; their default cap covers the remaining arrangement
        and tail. `end=(order,row)` sets a native range's exclusive endpoint: no later attacks or effects, while
        captured voices ring through the finite tail. Default finite native renders discard only digital silence
        after the written endpoint; explicit lengths retain their padding. Oversampled ranges retain per-render
        filter edge handling."""
        if self._native:
            self.timed_at(rate, oversample)
            if type(repeat) is not int or repeat < -1:
                raise ValueError('Native score repeat must be -1 or a nonnegative integer')
            if end is not None:
                stop = self._native_order_frame(*end)
                if repeat or self._in_tail or stop <= self._native_frame:
                    raise ValueError('Native score range must end after its current position and cannot repeat')
                self._native_stop = stop
        elif end is not None:
            raise ValueError('Exact range endpoints require a native score plan')
        _lib.openmpt_module_set_render_param(self._mod, 3, 8)      # OPENMPT_MODULE_RENDER_INTERPOLATIONFILTER_LENGTH
        _lib.openmpt_module_set_repeat_count(self._mod, 0 if self._native else repeat)
        _lib.openmpt_module_ctl_set_integer(self._mod, b"dither", dither)
        mixed = mix_rate(rate, oversample)
        trim_after = None
        if self._native and max_seconds is None and repeat >= 0:
            endpoint = self._native_stop if self._native_stop is not None else self._native_end
            written_frames = max(0, endpoint + repeat * self._native_end - self._native_frame)
            trim_after = (written_frames * rate + mixed - 1) // mixed

        def finish(pcm):
            if trim_after is not None:
                samples = memoryview(pcm).cast('f' if floats else 'h')
                last = len(samples) // 2
                while last > trim_after and samples[last * 2 - 2] == 0 and samples[last * 2 - 1] == 0:
                    last -= 1
                return bytes(samples[:last * 2])
            return bytes(pcm)

        chunk = 4096
        buf = (C.c_float if floats else C.c_int16) * (chunk * 2)
        buf = buf()
        read = _lib.openmpt_module_read_interleaved_float_stereo if floats else _lib.openmpt_module_read_interleaved_stereo
        out = bytearray()
        if max_seconds is None:
            passes = repeat + 1 if repeat >= 0 else 0
            dur = self.duration()
            max_seconds = min(self.SAFETY_SECONDS, dur * passes + 10) if passes else self.ENDLESS_SECONDS
            if self._native:
                if self._native_stop is not None:
                    max_seconds = (self._native_stop / mixed) + 10
                max_seconds = max(0, max_seconds - self._native_frame / mixed)
        limit = int(mixed * max_seconds)
        frames = 0
        remaining_repeats = repeat
        while frames < limit:
            if cancel is not None and cancel():
                raise ValueError('Export cancelled')
            if self._native:
                if self._native_frame >= self._native_end and remaining_repeats != 0:
                    self.order_start(0, cancel=cancel)
                    _lib.openmpt_module_ctl_set_integer(self._mod, b'dither', dither)
                    if remaining_repeats > 0:
                        remaining_repeats -= 1
                count = min(chunk, limit - frames)
                if remaining_repeats != 0:
                    count = min(count, self._native_end - self._native_frame)
                n = self._native_read(read, count, buf)
            else:
                n = read(self._mod, mixed, chunk, buf)
            if n == 0:
                break
            out += memoryview(buf)[: n * 2]
            frames += n
        if mixed == rate:
            return finish(out)
        import numpy as np
        from .resample import decimate, lowpass_fir
        if floats:
            y = decimate(np.frombuffer(out, dtype=np.float32).reshape(-1, 2), mixed // rate, lowpass_fir(0.45 * rate / mixed))
            return finish(y.astype("<f4").tobytes())
        # what resample(x, mixed, rate) does for a whole factor, both channels at once and at the output rate
        y = decimate(np.frombuffer(out, dtype=np.int16).reshape(-1, 2), mixed // rate, lowpass_fir(0.45 * rate / mixed))
        np.rint(y, out=y)
        np.clip(y, -32768, 32767, out=y)
        return finish(y.astype("<i2").tobytes())
