"""Fuzz the importers with malformed files: truncations, byte flips, header counts of 0 / 1 / 0xFFFF / 0xFFFFFFFF
(also with the file padded so the count can be read), pointers past the end. Rerun after changing a reader.

    python tools/fuzz_import.py [--format it|xm|s3m|mod|mid|wav|gp5|all] [--seed FILE] [--cases N] [--seconds S]
                                [--out DIR] [--full-every N]

Each format runs the function the app calls (itreader.import_it, midiimport.import_midi, gpimport.import_gp,
wavload.read_wav) in one worker interpreter per format, fed the cases over a pipe. Module formats run the Python reader
alone (read_module + module_to_song) and every --full-every-th case through import_it, which also loads the mutated
file into libopenmpt (match_level, patched to render 1 s instead of 30 so a case takes milliseconds). A seed is
`--seed FILE`, else the first of demo2/iron_relay.it, demo/arena.it, tests/fixtures/*.it, a demo compiled on the spot
(it), or one the test helpers write (xm, s3m, mod, gp5 through tests/, mid through mido, wav through wavload).

Reported: any exception that is not a ValueError (ITReadError, ModReadError, WavError, ...), SongError or OSError, an
error with an empty message, a worker silent for over 5 s (killed, counted as a hang), a worker that dies (a native
crash), and a worker working set over 1 GB (best-effort: sampled a few times a second through psapi on Windows or
/proc elsewhere; a fast spike can slip through). Each distinct failure (exception type and the line it came from) is
minimised (shortest prefix, then zeroed blocks, while it still fails the same way) and saved under --out with its
traceback. Exit status 1 when anything was found."""
import argparse
import ctypes
import json
import os
import queue
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FORMATS = ("it", "xm", "s3m", "mod", "mid", "wav", "gp5")
MODULES = ("it", "xm", "s3m", "mod")
HANG_SECONDS = 5.0
MEMORY_LIMIT = 1 << 30


# ---------------------------------------------------------------- the worker (one interpreter per format)

def worker(fmt):
    """Read cases from stdin (uint32 length, a flag byte: 1 = the full app path, the bytes), run each, answer a JSON
    line: {"ok": true} or {"ok": false, "type", "msg", "tb"}; "clean" says whether an error is one the app catches."""
    from vulturetracker.song import SongError
    from vulturetracker import modreader
    orig = modreader.match_level
    modreader.match_level = lambda mod, data, seconds=1: orig(mod, data, seconds)
    work = Path(tempfile.mkdtemp(prefix="fuzz_"))
    src = work / f"case.{fmt}"
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    while True:
        head = inp.read(5)
        if len(head) < 5:
            break
        n, full = struct.unpack("<IB", head)
        data = inp.read(n)
        song, samples = work / "s.yaml", work / "s_samples"
        shutil.rmtree(samples, ignore_errors=True)
        try:
            src.write_bytes(data)
            if fmt in MODULES:
                if full:
                    from vulturetracker.itreader import import_it
                    import_it(src, song, samples)
                else:
                    from vulturetracker.itreader import module_to_song
                    mod, _ = modreader.read_module(data)
                    module_to_song(mod, song, samples)
            elif fmt == "mid":
                from vulturetracker.midiimport import import_midi
                import_midi(src, song, samples)
            elif fmt == "gp5":
                from vulturetracker.gpimport import import_gp
                import_gp(src, song, samples)
            elif fmt == "wav":
                from vulturetracker.wavload import read_wav
                read_wav(src)
            reply = {"ok": True}
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as e:  # noqa: BLE001 - everything else is what we are here to find
            clean = isinstance(e, (ValueError, OSError, SongError)) and bool(str(e).strip())
            tb = traceback.extract_tb(e.__traceback__)
            where = f"{Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else "?"
            reply = {"ok": clean, "type": type(e).__name__, "msg": str(e)[:300], "where": where,
                     "tb": "".join(traceback.format_exception(e))[-3000:]}
        out.write((json.dumps(reply) + "\n").encode())
        out.flush()
    shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- the parent

def working_set(proc):
    """The worker's resident memory in bytes (best effort), or None."""
    try:
        if sys.platform == "win32":
            class PMC(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32)] + \
                           [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                           "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                                           "PagefileUsage", "PeakPagefileUsage")]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(pmc)
            if ctypes.windll.psapi.GetProcessMemoryInfo(int(proc._handle), ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize
        else:
            return int(Path(f"/proc/{proc.pid}/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except Exception:  # noqa: BLE001
        return None


class Worker:
    def __init__(self, fmt, log):
        self.fmt, self.log = fmt, log
        self.start()

    def start(self):
        self.proc = subprocess.Popen([sys.executable, "-X", "faulthandler", __file__, "--worker", self.fmt],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(self.log, "ab"))
        self.q = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            self.q.put(line)
        self.q.put(None)

    def run(self, data, full):
        """{"ok": ..., ...} for one case; {"ok": False, "type": "hang"|"memory"|"crash", ...} when the worker had to be
        killed or died."""
        try:
            self.proc.stdin.write(struct.pack("<IB", len(data), int(full)) + data)
            self.proc.stdin.flush()
        except OSError:
            pass
        deadline, peak = time.monotonic() + HANG_SECONDS, 0
        while True:
            try:
                line = self.q.get(timeout=0.1)
                break
            except queue.Empty:
                mem = working_set(self.proc)
                peak = max(peak, mem or 0)
                if peak > MEMORY_LIMIT:
                    self.kill()
                    return {"ok": False, "type": "memory", "msg": f"working set {peak >> 20} MB", "where": "memory", "tb": ""}
                if time.monotonic() > deadline:
                    self.kill()
                    return {"ok": False, "type": "hang", "msg": f"no answer in {HANG_SECONDS:g} s", "where": "hang", "tb": ""}
        if line is None:
            tail = Path(self.log).read_bytes()[-2000:].decode("utf-8", "replace")
            self.start()
            return {"ok": False, "type": "crash", "msg": f"the worker died (exit {self.proc.returncode})", "where": "crash", "tb": tail}
        return json.loads(line)

    def kill(self):
        self.proc.kill()
        self.proc.wait()
        self.start()

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.proc.kill()


# ---------------------------------------------------------------- seeds

def make_seed(fmt, out):
    """Seed bytes for `fmt` (see the module docstring)."""
    if fmt == "it":
        demos = [p for p in (ROOT / "demo/arena.it", ROOT / "demo2/iron_relay.it") if p.is_file() and p.stat().st_size < 1 << 20]
        fixtures = sorted((ROOT / "tests/fixtures").glob("*.it"), key=lambda p: p.stat().st_size)
        if demos or fixtures:  # the smallest: a case costs its parse (demos first: instruments, plugins, a message)
            return min(demos or fixtures, key=lambda p: p.stat().st_size).read_bytes()
        subprocess.run([sys.executable, "-m", "vulturetracker", "build", "demo2/iron_relay.yaml"], cwd=ROOT, check=True)
        return (ROOT / "demo2/iron_relay.it").read_bytes()
    if fmt in ("xm", "s3m", "mod"):
        from tests import test_modimport as T
        if fmt == "xm":
            return T.write_xm([{"data": T.TONE, "loop": (0, 4000)}], [T.grid([(0, 0, (T.C4, 1, 0, 0, 0))], T.E_XM)], [0])
        if fmt == "s3m":
            return T.write_s3m([("tone", T.TONE, 64, 8363, (0, 4000))], [T.grid([(0, 0, (T.C5, 1, None, 0, 0))], T.E_S3M)], [0])
        return T.write_mod([("tone", T.TONE, 64, 0, 0, 4000)], [T.grid([(0, 0, (428, 1, 0, 0))], T.EMPTY4)], [0])
    if fmt == "mid":
        import mido
        mid = mido.MidiFile(ticks_per_beat=480)
        for ch, notes in ((0, (60, 64, 67)), (9, (36, 38))):
            tr = mido.MidiTrack()
            tr.append(mido.MetaMessage("track_name", name=f"track {ch}"))
            tr.append(mido.MetaMessage("set_tempo", tempo=500000))
            tr.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
            for n in notes * 2:
                tr.append(mido.Message("note_on", channel=ch, note=n, velocity=100, time=0))
                tr.append(mido.Message("pitchwheel", channel=ch, pitch=1000, time=120))
                tr.append(mido.Message("note_off", channel=ch, note=n, time=360))
            mid.tracks.append(tr)
        p = out / "seed.mid"
        mid.save(str(p))
        return p.read_bytes()
    if fmt == "wav":
        from vulturetracker.wavload import write_wav
        p = out / "seed.wav"
        write_wav(p, 22050, [[(i * 37) % 200 - 100 for i in range(500)], [(i * 53) % 200 - 100 for i in range(500)]], 16,
                  loop=(100, 400, False), root_note=60)
        return p.read_bytes()
    if fmt == "gp5":
        from tests import test_gpimport as T
        if T.guitarpro is None:
            return None
        p = out / "seed.gp5"
        T.tab(p)
        return p.read_bytes()
    raise ValueError(fmt)


# ---------------------------------------------------------------- mutations

def pointers(data, limit=4096):
    """(offset, width) of the 2- and 4-byte little-endian fields in the first `limit` bytes whose value lands inside
    the file: candidate counts, sizes and pointers."""
    out = []
    for off in range(0, min(limit, len(data) - 1), 2):
        if 0 < struct.unpack_from("<H", data, off)[0] < len(data):
            out.append((off, 2))
        if off + 4 <= len(data) and 0 < struct.unpack_from("<I", data, off)[0] < len(data):
            out.append((off, 4))
    return out


def put(data, off, width, value):
    d = bytearray(data)
    struct.pack_into("<H" if width == 2 else "<I", d, off, value & (0xFFFF if width == 2 else 0xFFFFFFFF))
    return bytes(d)


def mutations(seed, rng):
    """(name, bytes) cases, the kinds interleaved so a time budget covers each: truncations at the boundaries the
    file's own fields point at and over a sweep of offsets, header counts at 0 / 1 / all ones (also with the file
    padded with zeros or with its own tail repeated, so a reader can follow the count), pointers past the end, then
    random byte flips for the rest."""
    n = len(seed)
    ptrs = pointers(seed)
    bounds = set(range(0, min(n, 48))) | {n - 1} | {n * k // 64 for k in range(64)}
    for off, width in ptrs:
        v = struct.unpack_from("<H" if width == 2 else "<I", seed, off)[0]
        bounds |= {v - 1, v, v + 1} | ({16 * v, 16 * v + 1} if width == 2 else set())
    bounds = [b for b in sorted(bounds) if 0 <= b < n]

    def truncations():
        for b in bounds:
            yield f"truncate@{b}", seed[:b]

    def counts():
        for off in range(0, min(n - 4, 256), 2):
            for width, ones in ((2, 0xFFFF), (4, 0xFFFFFFFF)):
                for v in (0, 1, ones):
                    yield f"count@{off}x{width}={v}", put(seed, off, width, v)
                d = put(seed, off, width, ones)
                yield f"count@{off}x{width}=ones+zeros", d + bytes(1 << 20)
                yield f"count@{off}x{width}=ones,zeros-after", d[:off + width] + bytes(1 << 20)  # a zeroed table after it
                yield f"count@{off}x{width}=ones+tail", d + (seed[256:] or seed) * max(1, (1 << 20) // max(1, n - 256))

    def past_eof():
        for off, width in ptrs:
            for v in (n + 1, 0x7FFFFFFF if width == 4 else 0xFFFF, 0xFFFFFFF0 if width == 4 else 0xFFF0):
                yield f"ptr@{off}x{width}={v}", put(seed, off, width, v)

    def flips():
        while True:
            d = bytearray(seed)
            for _ in range(rng.choice((1, 1, 2, 4, 8, 16))):
                d[rng.randrange(n)] = rng.randrange(256)
            yield "flip", bytes(d)

    gens = [truncations(), counts(), past_eof(), flips()]
    while gens:
        for g in list(gens):
            try:
                yield next(g)
            except StopIteration:
                gens.remove(g)


# ---------------------------------------------------------------- minimising

def minimise(w, data, full, key, budget=120):
    """A shorter input failing with the same `key` (type, where): the shortest prefix by bisection, then blocks zeroed."""
    def same(d):
        r = w.run(d, full)
        return r["type"] == key[0] and (not r["tb"] or r["where"] == key[1])

    lo, hi = 0, len(data)
    tries = 0
    while hi - lo > 1 and tries < budget // 2:  # the smallest prefix that still fails this way
        mid = (lo + hi) // 2
        tries += 1
        if same(data[:mid]):
            hi = mid
        else:
            lo = mid
    data = data[:hi]
    block = max(1, len(data) // 2)
    while block >= 1 and tries < budget:
        for a in range(0, len(data), block):
            if tries >= budget:
                break
            tries += 1
            d = data[:a] + bytes(min(block, len(data) - a)) + data[a + block:]
            if d != data and same(d):
                data = d
        block //= 2
    return data


# ---------------------------------------------------------------- main

def fuzz(fmt, args, rng):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    seed = Path(args.seed).read_bytes() if args.seed else make_seed(fmt, out)
    if seed is None:
        print(f"{fmt}: no seed (PyGuitarPro not installed); skipped")
        return 0, {}
    w = Worker(fmt, out / f"{fmt}-worker.log")
    r = w.run(seed, True)
    if not r["ok"]:
        print(f"{fmt}: the seed itself fails: {r['type']}: {r['msg']}")
        w.close()
        return 0, {("seed", r["type"]): r}
    stop = time.monotonic() + args.seconds
    found, cases, clean = {}, 0, {}
    for i, (name, data) in enumerate(mutations(seed, rng)):
        if cases >= args.cases or time.monotonic() > stop:
            break
        full = fmt in MODULES and args.full_every and i % args.full_every == 0
        r = w.run(data, full)
        cases += 1
        if r["ok"]:
            if "type" in r:
                clean[r["type"]] = clean.get(r["type"], 0) + 1
            continue
        key = (r["type"], r["where"] if r["tb"] else name.split("=")[0])  # a hang has no line: keyed by the mutation
        if key in found:
            found[key]["count"] += 1
            continue
        small = minimise(w, data, full, key, budget=6 if r["where"] in ("hang", "memory", "crash") else 120)
        k = len(found) + 1
        path = out / f"{fmt}-{k}.{fmt}"
        path.write_bytes(small)
        (out / f"{fmt}-{k}.txt").write_text(f"{name} ({'full' if full else 'reader'} path), {len(small)} bytes\n{r['type']}: {r['msg']}\n{r['tb']}",
                                            encoding="utf-8")
        found[key] = {**r, "count": 1, "file": path, "case": name, "full": full}
        print(f"{fmt}: {r['type']} at {r['where']} ({name}): {r['msg'][:120]} -> {path}")
    w.close()
    summary = ", ".join(f"{t} x{c}" for t, c in sorted(clean.items()))
    print(f"{fmt}: {cases} cases, {len(found)} distinct failures; clean errors: {summary or 'none'}")
    return cases, found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--format", default="all", choices=FORMATS + ("all",), help="which importer (default all)")
    ap.add_argument("--seed", help="a file to mutate instead of the built-in seed (one format only)")
    ap.add_argument("--cases", type=int, default=3000, help="cases per format at most (default 3000)")
    ap.add_argument("--seconds", type=float, default=90, help="wall time per format at most (default 90)")
    ap.add_argument("--out", default=str(ROOT / "scratch" / "fuzz_import"), help="where reproducers and logs go (default scratch/fuzz_import)")
    ap.add_argument("--full-every", type=int, default=8, help="module formats: run every Nth case through import_it with libopenmpt (0 = never; default 8)")
    ap.add_argument("--rng-seed", type=int, default=1, help="random seed for the byte flips (default 1)")
    ap.add_argument("--worker", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.worker:
        worker(args.worker)
        return 0
    fmts = FORMATS if args.format == "all" else (args.format,)
    if args.seed and len(fmts) > 1:
        ap.error("--seed needs --format")
    total = 0
    for fmt in fmts:
        cases, found = fuzz(fmt, args, random.Random(args.rng_seed))
        total += len(found)
    print(f"{total} distinct failure{'s' if total != 1 else ''}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
