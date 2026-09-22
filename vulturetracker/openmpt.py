"""Minimal ctypes binding to libopenmpt: load, inspect, render."""
import ctypes as C
import os
import sys
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
    ("openmpt_module_format_pattern_row_channel", _P, [_P, C.c_int32, C.c_int32, C.c_int32, C.c_size_t, C.c_int]),
    ("openmpt_module_get_pattern_row_channel_command", C.c_uint8, [_P, C.c_int32, C.c_int32, C.c_int32, C.c_int]),
    ("openmpt_module_set_repeat_count", C.c_int, [_P, C.c_int32]),
    ("openmpt_module_ctl_set_integer", C.c_int, [_P, C.c_char_p, C.c_int64]),
    ("openmpt_module_read_interleaved_stereo", C.c_size_t, [_P, C.c_int32, C.c_size_t, C.POINTER(C.c_int16)]),
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


class LoadedModule:
    """A module loaded by libopenmpt. Use as a context manager."""

    def __init__(self, data: bytes):
        self.log = []
        self._cb = _LOG_FUNC(lambda msg, _user: self.log.append(msg.decode("utf-8", "replace")))
        err = C.c_int(0)
        errmsg = C.c_char_p()
        self._buf = C.create_string_buffer(data, len(data))
        self._mod = _lib.openmpt_module_create_from_memory2(self._buf, len(data), self._cb, None, None, None,
                                                            C.byref(err), C.byref(errmsg), None)
        if not self._mod:
            raise OpenMPTError(f"libopenmpt could not load module (error {err.value}): "
                               f"{errmsg.value.decode() if errmsg.value else ''} {' / '.join(self.log)}".strip())

    @classmethod
    def from_file(cls, path):
        return cls(Path(path).read_bytes())

    def close(self):
        if self._mod:
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
        """Seconds one pass of the song plays for, as libopenmpt computes it."""
        return _lib.openmpt_module_get_duration_seconds(self._mod)

    def order_start(self, order, row=0):
        """Second at which `row` of `order` plays in one pass of the song, as libopenmpt plays it (speed, tempo, break and
        jump effects included). Seeks the module there. A position that never plays comes back as 0.0 (libopenmpt seeks
        into the hidden subsong that starts at an order playback never enters) or as the whole duration (a skipped row)."""
        return _lib.openmpt_module_set_position_order_row(self._mod, order, row)

    def info(self):
        m = self._mod
        return {
            "title": self.metadata("title"),
            "type": self.metadata("type"),
            "tracker": self.metadata("tracker"),
            "duration_seconds": round(_lib.openmpt_module_get_duration_seconds(m), 3),
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

    def render(self, rate=44100, repeat=0, max_seconds=600, dither=0):
        """Render to interleaved int16 stereo frames (bytes). repeat=0 plays once, N repeats N more times.
        dither=0 (none) makes renders bit-identical between runs; libopenmpt's own default (1) adds random dither."""
        _lib.openmpt_module_set_repeat_count(self._mod, repeat)
        _lib.openmpt_module_ctl_set_integer(self._mod, b"dither", dither)
        chunk = 4096
        buf = (C.c_int16 * (chunk * 2))()
        out = bytearray()
        limit = rate * max_seconds
        frames = 0
        while frames < limit:
            n = _lib.openmpt_module_read_interleaved_stereo(self._mod, rate, chunk, buf)
            if n == 0:
                break
            out += bytes(buf)[: n * 4]
            frames += n
        return bytes(out)
