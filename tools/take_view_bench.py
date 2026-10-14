"""Time the Samples tab's waveform view on a long recorded take, as the app serves it (State.sample_view behind
/api/wave): the first view (the WAV read), then the whole take again, a zoom, a pan and 4000 columns, after the app has
finished compiling the song on its own thread. Measured 2026-10-14 (LMMS-review phase 6): a 15-minute stereo take reads
in 4.3 s once, then 0.1-0.2 s a view, so no peak cache was built. Rerun it after changing the sample editor or wavload.

  python tools/take_view_bench.py 5 15        minutes of synthetic stereo 16-bit 48 kHz noise, one run each
  python tools/take_view_bench.py --wav take.wav

Don't run it under tracemalloc or a profiler: they slow the read by 20-40 times."""
import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SONG = """module: {title: Bench, tempo: 125, speed: 6, channels: [{name: A}]}
samples:
  1: {file: take.wav, name: take}
patterns:
  p:
    rows: 4
    data: |
      00: C-5 01 ... ...
orders: [p]
"""


def bench(wav, label):
    from vulturetracker import gui
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "take.wav").write_bytes(Path(wav).read_bytes())
        (d / "song.yaml").write_bytes(SONG.encode())
        st = gui.State(d / "song.yaml")
        try:
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 300:  # the app compiles and measures first, holding its lock
                busy = st.jobs.qsize() or any(r["status"] in ("queued", "rendering") for r in st.renders.values()) \
                    or (st.meters and st.meters["status"] in ("queued", "measuring"))
                if not busy:
                    break
                time.sleep(0.1)
            n = st.sample_view(1, 0, 1, 16)["frames"]  # not timed: only to learn the length (this reads the WAV)
            gui.wav_array.cache_clear()
            print(f"{label}: {n} frames; the app's own compile {time.perf_counter() - t0:.1f} s")
            for name, a, b, cols in (("first view (reads the WAV)", 0, None, 1500), ("whole take again", 0, None, 1500),
                                     ("zoom to the middle tenth", n // 2, n // 2 + n // 10, 1500),
                                     ("pan by a twentieth", n // 2 + n // 20, n // 2 + n // 20 + n // 10, 1500),
                                     ("whole take, 4000 columns", 0, None, 4000)):
                t = time.perf_counter()
                st.sample_view(1, a, b, cols)
                print(f"  {name:28s} {(time.perf_counter() - t) * 1000:8.1f} ms")
        finally:
            st.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("minutes", nargs="*", type=float, help="lengths of synthetic takes to time, in minutes")
    ap.add_argument("--wav", help="time this WAV instead")
    a = ap.parse_args(argv)
    if not a.minutes and not a.wav:
        ap.error("give minutes (e.g. 5 15) or --wav FILE")
    if a.wav and not Path(a.wav).is_file():
        ap.error(f"no such file: {a.wav}")
    if any(not 0 < m <= 60 for m in a.minutes):
        ap.error("minutes are 0-60")
    if a.wav:
        bench(a.wav, a.wav)
    import numpy as np
    from vulturetracker.fileio import wav_bytes
    for m in a.minutes:
        with tempfile.TemporaryDirectory() as tmp:
            n = int(m * 60 * 48000)
            pcm = (np.random.default_rng(1).standard_normal((n, 2)) * 3000).clip(-32768, 32767).astype("<i2")
            p = Path(tmp) / "take.wav"
            p.write_bytes(wav_bytes(pcm.tobytes(), 48000))
            bench(p, f"{m:g} min stereo 48 kHz")


if __name__ == "__main__":
    main()
