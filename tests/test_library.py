"""library.py: the feature index (cached on each file's stamp), nearest sounds by timbre, the map, and `tryout --like`."""
import io
import json
import math
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

from vulturetracker import library
from vulturetracker.wavload import write_wav

RATE = 44100


def _write(path, x, rate=RATE, stereo=False):
    x = np.clip(np.round(np.asarray(x) * 32767), -32768, 32767).astype(int)
    write_wav(path, rate, [x.tolist(), (x // 2).tolist()] if stereo else [x.tolist()])


def family(kind, k):
    """Member `k` (0-5) of a family of sounds: different pitches and lengths, the same kind of timbre."""
    rng = np.random.default_rng(1000 * len(kind) + k)
    n = int(RATE * (0.25 + 0.15 * k))
    t = np.arange(n) / RATE
    f = 110 * 2 ** ((k * 5) / 12)                  # 110 Hz up in fourths
    if kind == "sine":
        x = np.sin(2 * np.pi * f * t) * np.exp(-t * 3)
    elif kind == "saw":
        x = sum(np.sin(2 * np.pi * f * h * t) / h for h in range(1, int(10000 / f))) * np.exp(-t * 3) * 0.5
    elif kind == "square":
        x = sum(np.sin(2 * np.pi * f * h * t) / h for h in range(1, int(10000 / f), 2)) * np.minimum(1, t * 20) * 0.6
    elif kind == "noise":
        x = rng.standard_normal(n) * np.exp(-t * 2) * 0.3
    elif kind == "kick":
        ph = 2 * np.pi * np.cumsum(45 + (150 + 10 * k) * np.exp(-t * 30)) / RATE
        x = np.sin(ph) * np.exp(-t * (8 - k * 0.5))
    elif kind == "hat":
        x = np.diff(rng.standard_normal(n + 1)) * np.exp(-t * (60 - 6 * k)) * 0.3
    elif kind == "pad":
        x = sum(np.sin(2 * np.pi * f * h * t * (1 + d)) / h for h in range(1, 12) for d in (-0.004, 0.004))
        x = x * np.minimum(1, t / (0.15 + 0.03 * k)) * 0.15
    else:
        raise ValueError(kind)
    return x / np.abs(x).max() * 0.8


FAMILIES = ("sine", "saw", "square", "noise", "kick", "hat", "pad")


def make_library(d):
    """Six WAVs of each family in <d>/<family>/, mixed rates and channel counts."""
    paths = {}
    for kind in FAMILIES:
        (d / kind).mkdir(parents=True, exist_ok=True)
        for k in range(6):
            p = d / kind / f"{kind}{k}.wav"
            _write(p, family(kind, k), rate=RATE if k % 3 else 22050 if kind != "hat" else 32000, stereo=k == 4)
            paths[str(p.resolve())] = kind
    return paths


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_audio_matches_every_format(self):
        # the numpy reader against the stdlib one the compiler uses: 8/16/24/32-bit PCM and float, stereo averaged
        import struct
        import wave
        x = np.sin(np.arange(2000) * 0.05) * 0.5
        for bits, tag in ((8, 1), (16, 1), (24, 1), (32, 1), (32, 3)):
            p = self.dir / f"f{bits}{tag}.wav"
            if tag == 3:
                data = np.repeat(x, 2).astype("<f4").tobytes()
            elif bits == 8:
                data = np.repeat(np.round(x * 127) + 128, 2).astype(np.uint8).tobytes()
            else:
                v = np.repeat(np.round(x * (2 ** (bits - 1) - 1)), 2).astype(np.int64)
                data = b"".join(int(s).to_bytes(bits // 8, "little", signed=True) for s in v)
            fmt = struct.pack("<HHIIHH", tag, 2, 22050, 22050 * bits // 4, bits // 4, bits)
            body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(data)) + data
            p.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
            y, rate, info = library.read_audio(p)
            self.assertEqual((rate, info["frames"], info["channels"]), (22050, 2000, 2), bits)
            self.assertLess(np.abs(y - x).max(), 0.01 if bits == 8 else 1e-4, bits)
        y, _, info = library.read_audio(self.dir / "f161.wav", max_seconds=0.01)  # only the start is read
        self.assertEqual((len(y), info["frames"]), (220, 2000))
        with wave.open(str(self.dir / "w.wav"), "wb") as w:  # and a WAV written by the stdlib, with a smpl root
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(b"\0\1" * 100)
        write_wav(self.dir / "r.wav", RATE, [[0, 1000, -1000] * 100], root_note=64)
        self.assertEqual(library.read_audio(self.dir / "r.wav")[2]["root"], 64)

    def test_features_measure_what_they_name(self):
        t = np.arange(RATE) / RATE
        vec, info = library.features(np.sin(2 * np.pi * 440 * t) * 0.5, RATE)
        self.assertEqual(len(vec), library.SIZE)
        self.assertEqual(info["pitch"], "A-5")
        self.assertAlmostEqual(info["centroid"], 440, delta=15)
        self.assertLess(info["flatness"], 0.01)
        noise = np.random.default_rng(0).standard_normal(RATE) * 0.3
        _, ninfo = library.features(noise, RATE)
        self.assertIsNone(ninfo.get("pitch"))
        self.assertGreater(ninfo["flatness"], 0.5)
        self.assertGreater(ninfo["centroid"], 8000)
        slow = np.sin(2 * np.pi * 220 * t) * np.minimum(1, t / 0.3)
        self.assertAlmostEqual(library.features(slow, RATE)[1]["attack"], 0.24, delta=0.01)  # 10 % to 90 % of a 0.3 s ramp
        with self.assertRaises(ValueError):
            library.features(np.zeros(1000), RATE)

    def test_nearest_finds_the_same_family(self):
        # precision of the three nearest within a family of six (pitches over two octaves, lengths 0.25-1 s, rates
        # 22050 and 44100 Hz, one stereo member each): the measurement the weights were set on
        paths = make_library(self.dir / "lib")
        lib = library.Library(self.dir / "index.json")
        res = lib.scan([self.dir / "lib"])
        self.assertEqual((res["files"], res["read"], res["errors"]), (42, 42, 0))
        hits = {k: 0 for k in FAMILIES}
        for p, kind in paths.items():
            near = lib.nearest(p, 3)
            self.assertNotIn(p, [q for q, _ in near])
            self.assertEqual(sorted(d for _, d in near), [d for _, d in near])
            hits[kind] += sum(paths[q] == kind for q, _ in near)
        precision = {k: v / 18 for k, v in hits.items()}
        self.assertGreaterEqual(sum(hits.values()) / (42 * 3), 0.85, precision)  # 0.90 when written
        self.assertTrue(all(v >= 2 / 3 for v in precision.values()), precision)
        m = lib.map()
        self.assertEqual(len(m["points"]), 42)
        self.assertTrue(all(0 <= c <= 1 for pt in m["points"] for c in pt))
        self.assertEqual(sorted(set(m["groups"])), sorted(f"lib/{k}" for k in FAMILIES))

    def test_the_index_rereads_only_what_changed(self):
        make_library(self.dir / "lib")
        idx = self.dir / "index.json"
        lib = library.Library(idx)
        lib.scan([self.dir / "lib"])
        first = json.loads(idx.read_text())
        self.assertEqual(first["version"], library.VERSION)
        again = library.Library(idx)  # from the file: nothing read
        self.assertEqual(again.scan()["read"], 0)
        p = self.dir / "lib" / "saw" / "saw2.wav"
        _write(p, family("noise", 2))
        os.utime(p, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
        (self.dir / "lib" / "hat" / "hat0.wav").unlink()
        (self.dir / "lib" / "bad.wav").write_bytes(b"RIFF....WAVEjunk")
        (self.dir / "lib" / ".tryout").mkdir()
        _write(self.dir / "lib" / ".tryout" / "render.wav", family("sine", 1))  # the app's renders: never indexed
        res = again.scan()
        self.assertEqual((res["read"], res["dropped"], res["errors"], res["files"]), (2, 1, 1, 41))
        near = again.nearest(p, 3)  # the changed file now sits with the noises
        self.assertTrue(all("noise" in q for q, _ in near), near)
        self.assertEqual(again.scan()["read"], 0)  # the unreadable file is remembered on its stamp too
        stale = json.loads(idx.read_text())
        stale["version"] = 0
        idx.write_text(json.dumps(stale))
        self.assertEqual(library.Library(idx).scan()["read"], 42)  # another feature version: everything read again

    def test_a_query_outside_the_index_and_exact_copies(self):
        make_library(self.dir / "lib")
        lib = library.Library(self.dir / "index.json")
        lib.scan([self.dir / "lib"])
        q = self.dir / "query.wav"
        _write(q, family("kick", 3))
        near = lib.nearest(q, 3)
        self.assertTrue(all("kick" in p for p, _ in near), near)
        self.assertNotIn(str((self.dir / "lib" / "kick" / "kick3.wav").resolve()), [p for p, _ in near])  # its copy
        self.assertEqual(lib.nearest(q, 3, exclude=[p for p, _ in near[:2]])[0][0], near[2][0])

    def test_tryout_like_on_the_command_line(self):
        from tests.test_gui import SONG, sine
        from vulturetracker.__main__ import main
        make_library(self.dir / "lib")
        write_wav(self.dir / "a.wav", RATE, [sine(440)], root_note=69)
        write_wav(self.dir / "b.wav", RATE, [sine(880)])
        (self.dir / "song.yaml").write_bytes(SONG.encode())
        idx = str(self.dir / "index.json")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["index", str(self.dir / "lib"), "--index", idx]), 0)
            self.assertEqual(main(["tryout", str(self.dir / "song.yaml"), "--sample", "1", "--like",
                                   str(self.dir / "lib" / "kick" / "kick1.wav"), "-k", "3", "--index", idx,
                                   "-o", str(self.dir / "t.wav")]), 0)
        lines = out.getvalue().splitlines()
        like = [ln for ln in lines if ln.startswith("like kick1.wav")]
        self.assertEqual(len(like), 3, lines)
        self.assertTrue(all("kick" in ln.rsplit("/", 1)[-1] for ln in like), like)
        self.assertIn("3 versions", lines[-1])

    def test_find_similar_in_the_app(self):
        # POST similar from the slot's WAV and from a candidate: the nearest join the slot's candidates, remembered with
        # their distance; the map and a sound's nearest come from GET; /libwav serves only indexed files
        import threading
        import urllib.error
        import urllib.parse
        import urllib.request
        from tests.test_gui import SONG
        from vulturetracker import gui
        make_library(self.dir / "lib")
        _write(self.dir / "a.wav", family("saw", 2))
        _write(self.dir / "b.wav", family("hat", 2))
        (self.dir / "song.yaml").write_bytes(SONG.encode())
        st = gui.Handler.state = gui.State(self.dir / "song.yaml")
        gui.Handler.library = library.Library(self.dir / "index.json")
        gui.Handler.library.set_roots([self.dir / "lib"])
        srv = gui._Server(("127.0.0.1", 0), gui.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"

        def call(path, body=None):
            req = urllib.request.Request(url + path, json.dumps(body).encode() if body is not None else None,
                                         {"content-type": "application/json"})
            with urllib.request.urlopen(req) as r:
                data = r.read()
            return json.loads(data) if r.headers.get("content-type", "").startswith("application/json") else data
        try:
            res = call("/api/similar", {"k": 4})
            self.assertEqual(len(res["added"]), 4, res)
            self.assertTrue(all("/saw/" in p.replace(os.sep, "/") for p in res["added"]), res)
            self.assertIn("slot 01", res["report"])
            snap = call("/api/state")
            self.assertEqual([c["path"] for c in snap["candidates"]], res["added"])
            self.assertEqual(snap["candidates"][0]["found"][0], "a")
            self.assertEqual(snap["library"]["count"], 42)
            again = call("/api/similar", {"id": 0, "k": 3})  # from a candidate: the ones listed already are passed over
            self.assertTrue(set(again["added"]).isdisjoint(res["added"]), again)
            self.assertEqual(len(st.cands()), 7)
            m = call("/api/libmap")
            self.assertEqual(len(m["paths"]), 42)
            near = call("/api/libnear?k=2&path=" + urllib.parse.quote(m["paths"][0]))["near"]
            self.assertEqual(len(near), 2)
            self.assertEqual(call("/libwav?path=" + urllib.parse.quote(m["paths"][0]))[:4], b"RIFF")
            with self.assertRaises(urllib.error.HTTPError) as e:
                call("/libwav?path=" + urllib.parse.quote(str(self.dir / "song.yaml")))
            self.assertEqual(e.exception.code, 404)
            lib = call("/api/library", {"roots": [str(self.dir / "lib" / "kick")]})  # fewer folders: a scan drops the rest
            for _ in range(100):
                if not call("/api/library")["busy"]:
                    break
                time.sleep(0.05)
            self.assertEqual((call("/api/library")["count"], lib["roots"]), (6, [str((self.dir / "lib" / "kick").resolve())]))
        finally:
            srv.shutdown()
            srv.server_close()
            gui.Handler.state = gui.Handler.library = None
            st.close()
            for _ in range(400):  # the worker finishes the render it is on before the folder goes
                if not any(r["status"] == "rendering" for r in st.renders.values()):
                    break
                time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
