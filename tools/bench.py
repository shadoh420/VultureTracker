"""Time the app's compile and edit path on a song: what an edit costs before the live engine plays it.

    python tools/bench.py [song.yaml ...] [--repeat N] [--json out.json]

Stages (median of N runs, milliseconds):
  compile cold   load_song_text with every memo emptied (samples read and resampled)
  compile warm   load_song_text again (what each edit and reload pays)
  write_it       the compiled model to .it bytes
  facts          facts_of: order timing through libopenmpt
  render 1x/2x   the whole song through libopenmpt, at 44.1 kHz and 2x oversampled
  edit           State.edit_patterns of one cell: compile, write, reload (the app's step before the page asks for /api/it)
  live_it        State.live_it right after that edit: the module the page's engine loads
  edit->live     edit + live_it: the server's share of an edit's latency
  state          State.snapshot() and its JSON, as each /api/state poll serves it
  tryout K       (with --tryout K) from opening the song to the song and K candidates of its first slot rendered by the
                 app's render workers (gui.WORKERS; VT_WORKERS=1 for one at a time), once; the renders' sha1 goes to
                 --json, so runs with different worker counts can be compared byte for byte

The edit stages run on a copy of the song beside it (so relative sample paths hold), with the render worker stopped, and
the copy, its meta and its cache files are removed afterwards. A sample file missing here (a render kept in
samples/local/) is played by samples/kick.wav, so the timings hold even without it. Default songs: the demos."""
import argparse
import os
import re
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vulturetracker import gui, notation, song as songmod  # noqa: E402
from vulturetracker.itwriter import write_it  # noqa: E402
from vulturetracker.openmpt import LoadedModule  # noqa: E402

DEMOS = ["demo/arena.yaml", "demo2/iron_relay.yaml", "demo3/undertow.yaml", "demo4/vantage.yaml"]


def clear_memos():
    for name in ("_WAVS", "_RESAMPLED", "_DATA", "_IMAGES", "_PATTERNS"):
        memo = getattr(songmod, name, None)
        if isinstance(memo, dict):
            memo.clear()
    fields = getattr(notation, "_cell_fields", None)
    if fields is not None:
        fields.cache_clear()


def timed(fn, n, before=None):
    out = []
    for _ in range(n):
        if before:
            before()
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return statistics.median(out)


STANDIN = ROOT / "samples" / "kick.wav"


def standins(text, base):
    """`text` with each sample file that is missing here (renders kept in samples/local/, say) pointed at a committed
    stand-in WAV, so the song compiles with the same slots and patterns; and how many were replaced."""
    missing = 0

    def sub(m):
        nonlocal missing
        if (base / m.group(2)).is_file():
            return m.group(0)
        missing += 1
        return m.group(1) + os.path.relpath(STANDIN, base).replace(os.sep, "/")
    return re.sub(r"(\bfile:\s*)([^,}\n]+?)(?=\s*[,}\n])", sub, text), missing


def tryout(copy, text, k):
    """Seconds from opening `copy` (the song text with a unique comment, so no cached render serves it) to the song and
    `k` candidates of its first slot rendered, and {candidate: sha1 of its render}."""
    import hashlib
    copy.write_bytes((text + f"\n# bench {time.time()}\n").encode("utf-8"))
    pool = sorted(str(p) for p in (ROOT / "samples").rglob("*.wav") if "local" not in p.parts)
    t = time.perf_counter()
    st = gui.State(copy)
    try:
        slot = min(st.song["samples"])
        st.meta["slot"] = slot
        cur = st.current_file()
        cands = [c for c in pool if c != cur][:k]
        st.add_candidates("\n".join(cands))
        keys = {c: st.key(c) for c in [None, *cands]}
        while not all(st.renders.get(key, {}).get("status") in ("ready", "failed") for key in keys.values()):
            time.sleep(0.005)
        secs = time.perf_counter() - t
        out = {}
        for c, key in keys.items():
            r = st.renders[key]
            out[Path(c).name if c else "(song)"] = (hashlib.sha1(Path(r["file"]).read_bytes()).hexdigest()[:16]
                                                    if r["status"] == "ready" else r["error"])
        return secs * 1000, out
    finally:
        st.close()
        for f in (copy.with_name(copy.stem + ".tryout.json"),):
            f.unlink(missing_ok=True)


def bench(path, n, k=0):
    path = Path(path).resolve()
    base = path.parent
    text, missing = standins(path.read_text(encoding="utf-8"), base)
    res = {"song": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), "kb": round(len(text) / 1024),
           "standins": missing}
    res["compile cold"] = timed(lambda: songmod.load_song_text(text, base, str(path)), n, clear_memos)
    res["compile warm"] = timed(lambda: songmod.load_song_text(text, base, str(path)), n)
    mod, warnings = songmod.load_song_text(text, base, str(path))
    res["write_it"] = timed(lambda: write_it(mod), n)
    res["facts"] = timed(lambda: gui.facts_of(mod, warnings), n)
    it = write_it(mod)

    def render(over):
        with LoadedModule(it) as lm:
            lm.render(44100, oversample=over)
    res["render 1x"] = timed(lambda: render(1), max(1, n // 2))
    res["render 2x"] = timed(lambda: render(2), max(1, n // 2))

    copy = path.with_name(f"_bench_{path.name}")
    copy.write_bytes(text.encode("utf-8"))
    st = None
    try:
        st = gui.State(copy)
        st.close()
        if st.mod is None:
            raise SystemExit(f"{path}: does not compile: {st.error}")
        vols = iter(range(65))

        def edit():  # a new text each time (v00, v01, ...), as real edits are: no compile memo can serve it
            st.edit_patterns([(st.mod.orders[0], [{"row": 0, "ch": 0, "cell": f"... .. v{next(vols):02d} ..."}])])
        edits, lives = [], []
        for _ in range(n):
            t = time.perf_counter()
            edit()
            t1 = time.perf_counter()
            st.live_it()
            t2 = time.perf_counter()
            edits.append((t1 - t) * 1000)
            lives.append((t2 - t1) * 1000)
        res["edit"] = statistics.median(edits)
        res["live_it"] = statistics.median(lives)
        res["edit->live"] = statistics.median(a + b for a, b in zip(edits, lives))
        res["state"] = timed(lambda: json.dumps(st.snapshot()), n)
        if k:
            res[f"tryout {k}"], res["renders"] = tryout(copy, text, k)
            res["workers"] = gui.WORKERS
    finally:
        for f in (copy, copy.with_name(copy.stem + ".tryout.json"), copy.with_name(copy.stem + ".notes.json"),
                  copy.with_name(copy.stem + ".notes.md")):
            f.unlink(missing_ok=True)
        if st is not None:
            for f in st.cache_dir.glob("*"):
                if f.suffix in (".wav", ".png") and f.stat().st_mtime >= START:
                    f.unlink(missing_ok=True)
    return res


START = time.time()
COLS = ["compile cold", "compile warm", "write_it", "facts", "render 1x", "render 2x", "edit", "live_it", "edit->live",
        "state"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("songs", nargs="*", default=[str(ROOT / s) for s in DEMOS])
    ap.add_argument("--repeat", type=int, default=5, help="runs per stage (at most 32 edits)")
    ap.add_argument("--json", help="also write the results here")
    ap.add_argument("--tryout", type=int, default=0, metavar="K", help="also time the song and K candidates rendered")
    a = ap.parse_args()
    a.repeat = max(1, min(32, a.repeat))
    rows = []
    for s in a.songs:
        p = Path(s).resolve()
        try:
            songmod.load_song_text(standins(p.read_text(encoding="utf-8"), p.parent)[0], p.parent, str(p))
        except songmod.SongError as e:
            print(f"{s}: skipped, it does not compile here ({e.errors[0]})", file=sys.stderr)
            continue
        rows.append(bench(s, a.repeat, a.tryout))
    cols = COLS + ([f"tryout {a.tryout}"] if a.tryout else [])
    print(f"{'song':<24}{'KB':>5}" + "".join(f"{c:>14}" for c in cols))
    for r in rows:
        print(f"{Path(r['song']).name:<24}{r['kb']:>5}" + "".join(f"{r[c]:>14.1f}" for c in cols)
              + (f"   ({r['standins']} missing samples played by {STANDIN.name})" if r["standins"] else ""))
    print("(milliseconds, median of", a.repeat, "runs" + (f"; tryout once, {gui.WORKERS} render workers)" if a.tryout else ")"))
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
