"""Recording from an audio input: the RECORD tab's engine. Devices come through sounddevice (PortAudio): on Windows the
WASAPI, MME and DirectSound inputs, and ASIO drivers (a Focusrite Scarlett's "Focusrite USB ASIO") when the app starts
with SD_ENABLE_ASIO=1 (sounddevice reads it when it loads). While the input is open the recorder keeps a meter per
input, a tuner on the inputs being recorded and a short pre-roll; a take is the frames between REC and STOP, returned
as float channels x frames. Monitoring is the interface's own (a Scarlett's Direct Monitor switch): nothing here plays
the input back, so there is no software latency to hear.

VT_FAKE_AUDIO=1 replaces the devices with a simulated two-input interface (a plucked G-4, 196 Hz, every 1.5 s on
input 1, a quiet hum on input 2), for the tests and for trying the tab without an interface."""
import collections
import importlib
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

# which device inputs a take keeps (0-based) and whether it stays two channels
MODES = {"1": ([0], False), "2": ([1], False), "stereo": ([0, 1], True), "mono": ([0, 1], False)}
MODE_NAMES = {"1": "input 1", "2": "input 2", "stereo": "1+2 stereo", "mono": "1+2 as mono"}


class RecordError(RuntimeError):
    pass


# ---------------------------------------------------------------- backends

class FakeStream:
    """sounddevice.InputStream's shape (start, stop, close; a callback per block) over a generated signal, in real time."""

    def __init__(self, samplerate, channels, callback, blocksize=512):
        self.rate, self.channels, self.callback, self.block = int(samplerate), channels, callback, blocksize
        self.frame = 0
        self._stop = threading.Event()
        self._thread = None

    def signal(self, n):
        t = (self.frame + np.arange(n)) / self.rate
        phase = t % 1.5                                    # a plucked G-4 (196 Hz) every 1.5 s, 1.2 s long
        env = np.where(phase < 1.2, np.minimum(1, phase * 200) * np.exp(-phase * 2.5), 0)
        pluck = 0.5 * env * (np.sin(2 * np.pi * 196 * t) + 0.3 * np.sin(2 * np.pi * 392 * t))
        hum = 0.01 * np.sin(2 * np.pi * 50 * t)
        out = np.stack([pluck, hum][: self.channels] + [np.zeros(n)] * max(0, self.channels - 2), axis=1)
        self.frame += n
        return out.astype(np.float32)

    def feed(self, seconds):
        """Deliver `seconds` of blocks at once (tests: no waiting on the clock)."""
        for _ in range(int(seconds * self.rate / self.block)):
            self.callback(self.signal(self.block), self.block, None, None)

    def start(self):
        def run():
            next_t = time.monotonic()
            while not self._stop.is_set():
                self.callback(self.signal(self.block), self.block, None, None)
                next_t += self.block / self.rate
                time.sleep(max(0, next_t - time.monotonic()))
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(1)

    def close(self):
        self.stop()


class FakeBackend:
    name = "simulated"
    realtime = True  # False in tests: the stream is not started, blocks come from FakeStream.feed

    def devices(self):
        return [{"id": 0, "name": "Simulated 2-input interface", "hostapi": "simulated", "inputs": 2, "rate": 44100}]

    def open(self, device, channels, rate, callback, exclusive=False):
        s = FakeStream(rate, channels, callback)
        if self.realtime:
            s.start()
        return s


class OnThread:
    """A stream whose stop and close run on the backend's audio thread, as its start did."""

    def __init__(self, ex, stream):
        self.ex, self.stream = ex, stream

    def stop(self):
        self.ex.submit(self.stream.stop).result()

    def close(self):
        self.ex.submit(self.stream.close).result()


class SoundDeviceBackend:
    """sounddevice, with every PortAudio call on one thread of its own: an ASIO driver (Focusrite USB ASIO) opens only on
    the thread that loaded PortAudio ('Failed to load ASIO driver' elsewhere), and the server answers each request on a
    new thread."""
    name = "sounddevice"

    def __init__(self):
        self.ex = ThreadPoolExecutor(1, thread_name_prefix="audio")
        try:
            self.sd = self.ex.submit(importlib.import_module, "sounddevice").result()
        except (ImportError, OSError) as e:  # not installed, or no PortAudio library found
            raise RecordError(f"recording needs sounddevice (pip install sounddevice): {e}")

    def devices(self):
        return self.ex.submit(self._devices).result()

    def open(self, device, channels, rate, callback, exclusive=False):
        return OnThread(self.ex, self.ex.submit(self._open, device, channels, rate, callback, exclusive).result())

    def _devices(self):
        apis = self.sd.query_hostapis()
        out = []
        for d in self.sd.query_devices():
            if d["max_input_channels"] > 0:
                out.append({"id": d["index"], "name": d["name"], "hostapi": apis[d["hostapi"]]["name"],
                            "inputs": d["max_input_channels"], "rate": int(d["default_samplerate"])})
        return out

    def _open(self, device, channels, rate, callback, exclusive):
        sd = self.sd
        info = sd.query_devices(device)
        api = sd.query_hostapis(info["hostapi"])["name"]
        extra = None
        if "WASAPI" in api:  # shared mode converts the rate for us; exclusive needs the device's own rate
            extra = sd.WasapiSettings(exclusive=exclusive, auto_convert=not exclusive)
        try:
            s = sd.InputStream(device=device, channels=channels, samplerate=rate, dtype="float32", latency="low",
                               callback=callback, extra_settings=extra)
            s.start()
        except Exception as e:  # noqa: BLE001 - PortAudio's errors name the problem (rate, channels, busy device)
            hint = (f"; EXCLUSIVE opens only at the rate the device is set to ({int(info['default_samplerate'])} Hz here: set in "
                    f"its control panel, such as Focusrite Control, or pick that RATE)") if exclusive and "WASAPI" in api else ""
            raise RecordError(f"{info['name']} ({api}) would not open at {rate} Hz with {channels} inputs: {e}{hint}")
        return s


def backend():
    """The simulated device when VT_FAKE_AUDIO is set, else sounddevice (RecordError when it cannot load)."""
    return FakeBackend() if os.environ.get("VT_FAKE_AUDIO") else SoundDeviceBackend()


# ---------------------------------------------------------------- the recorder

class Recorder:
    TUNER_FRAMES = 4096

    def __init__(self, be=None):
        self.be = be
        self.error = None
        self.lock = threading.Lock()
        self.stream = None
        self.device = self.mode = self.rate = None
        self.channels = 0
        self.recording = False
        self.chunks = []
        self.preroll = collections.deque()
        self.preroll_frames = 0
        self.preroll_s = 0.5
        self.peak = np.zeros(2)
        self.hold = np.zeros(2)
        self.clip = np.zeros(2, bool)
        self.tune = np.zeros(self.TUNER_FRAMES, np.float32)
        self.frames = 0          # frames of the take so far
        self.overflows = 0

    def _backend(self):
        if self.be is None:
            self.be = backend()
        return self.be

    def devices(self):
        return self._backend().devices()

    def open(self, device, mode="1", rate=44100, exclusive=False):
        """Open `device` (a devices() id) for `mode` (MODES) at `rate`; the meters and tuner run from here on."""
        if mode not in MODES:
            raise RecordError(f"inputs are one of {', '.join(MODES)}")
        self.close()
        be = self._backend()
        dev = next((d for d in be.devices() if d["id"] == int(device)), None)
        if dev is None:
            raise RecordError(f"no input device {device}")
        need = max(MODES[mode][0]) + 1
        if dev["inputs"] < need:
            raise RecordError(f"{dev['name']} has {dev['inputs']} input(s): pick input 1")
        channels = min(2, dev["inputs"])
        with self.lock:
            self.device, self.mode, self.rate, self.channels = int(device), mode, int(rate), channels
            self.peak[:], self.hold[:], self.clip[:] = 0, 0, False
            self.preroll.clear()
            self.preroll_frames = 0
            self.overflows = 0
        self.stream = be.open(int(device), channels, int(rate), self._callback, exclusive)
        self.error = None

    def close(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:  # noqa: BLE001 - a device unplugged mid-stream: closing is all that is left
                pass
        with self.lock:
            self.recording = False
            self.chunks = []

    def set_mode(self, mode):
        if mode not in MODES:
            raise RecordError(f"inputs are one of {', '.join(MODES)}")
        if max(MODES[mode][0]) >= self.channels:
            raise RecordError("this device has one input")
        with self.lock:
            self.mode = mode

    def _callback(self, indata, frames, time_info, status):
        if status is not None and getattr(status, "input_overflow", False):
            self.overflows += 1
        x = np.asarray(indata, np.float32)
        with self.lock:
            p = np.abs(x).max(axis=0) if len(x) else np.zeros(x.shape[1])
            k = min(2, len(p))
            self.peak[:k] = np.maximum(p[:k], self.peak[:k] * 0.85)   # a meter that falls about 25 dB a second
            self.hold[:k] = np.maximum(self.hold[:k], p[:k])
            self.clip[:k] |= p[:k] >= 0.999
            ins, _ = MODES[self.mode]
            sel = x[:, [i for i in ins if i < x.shape[1]]]
            mono = sel.mean(axis=1)
            n = min(len(mono), self.TUNER_FRAMES)
            self.tune = np.roll(self.tune, -n)
            self.tune[-n:] = mono[-n:]
            block = sel.copy()
            if self.recording:
                self.chunks.append(block)
                self.frames += len(block)
            else:
                self.preroll.append(block)
                self.preroll_frames += len(block)
                while self.preroll and self.preroll_frames - len(self.preroll[0]) >= self.preroll_s * self.rate:
                    self.preroll_frames -= len(self.preroll.popleft())

    def start(self, preroll=0.0):
        """Begin a take; the last `preroll` seconds before REC (up to 0.5) open it."""
        if self.stream is None:
            raise RecordError("open an input first")
        with self.lock:
            keep, got = [], 0
            want = int(max(0.0, min(self.preroll_s, float(preroll))) * self.rate)
            for b in reversed(self.preroll):
                if got >= want:
                    break
                keep.insert(0, b)
                got += len(b)
            head = np.concatenate(keep)[-want:] if keep and want else np.zeros((0, len(MODES[self.mode][0])), np.float32)
            self.chunks = [head] if len(head) else []
            self.frames = len(head)
            self.recording = True
            self.clip[:] = False
            self.hold[:] = 0

    def stop(self):
        """End the take: float32 channels x frames (two for stereo, else one), or None when nothing was recorded."""
        with self.lock:
            if not self.recording:
                return None
            self.recording = False
            chunks, self.chunks = self.chunks, []
            mode = self.mode
        if not chunks:
            return None
        x = np.concatenate(chunks).T
        _, keep_both = MODES[mode]
        return x if keep_both or x.shape[0] == 1 else x.mean(axis=0, keepdims=True)

    def status(self):
        """What the tab shows: the device, whether it records, the meters (dBFS peak and held peak per input, clip),
        the seconds so far and the tuner."""
        from . import dsp
        with self.lock:
            db = lambda v: round(20 * math.log10(v), 1) if v > 1e-6 else None  # noqa: E731
            out = {"open": self.stream is not None, "device": self.device, "mode": self.mode, "rate": self.rate,
                   "inputs": self.channels, "recording": self.recording, "seconds": self.frames / self.rate if self.rate else 0,
                   "peak": [db(v) for v in self.peak[: self.channels]], "hold": [db(v) for v in self.hold[: self.channels]],
                   "clip": [bool(v) for v in self.clip[: self.channels]], "overflows": self.overflows, "error": self.error}
            tune = self.tune.copy()
        out["tuner"] = None
        if out["open"] and np.abs(tune).max() > 0.01:
            hz, conf = dsp.yin(tune, self.rate)
            if hz and conf > 0.85:
                note, cents = dsp.note_of(hz)
                out["tuner"] = {"hz": round(hz, 2), "note": note, "cents": round(cents)}
        return out
