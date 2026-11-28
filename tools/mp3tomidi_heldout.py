"""Score mp3tomidi-independent against the Dettato port on demo songs it was not tuned on.

The tuning passes for mp3tomidi-independent were scored on iron_relay and vantage, so those cannot tell
whether a change generalises. This scores the standalone binary and the Dettato port (`--mode parity`,
plus its `--enhance-midi` and `--hybrid-midi` passes) on demo/arena.yaml and demo3/undertow.yaml against
their exact YAML notes, with tools/symbolic_diff.py's metrics.

The answer key, fixed from the songs' samples, not from any transcriber's output:
- Undertow's Gate L/R channels are skipped: their sample is a chord, so one written note is several pitches.
- Undertow's L/R channel pairs are deduplicated: one event per (time, pitch) or (time, drum class).
- Each song is also scored with its echo channels counted (symbolic_diff always drops them).
- Notes are scored at their written pitch. Undertow's bass sample sounds an octave below its written
  notes (its lowest peak is about 20 Hz), so read its bass alongside the octave-free (chroma) columns.

The Dettato port takes about 7 minutes on CPU, so its MIDIs are kept in --out and reused until
--rerun-dettato; the standalone binary is re-run every time. Run it under a coord `cpu` lease.

Usage (from the repository root, in the environment that has pretty_midi and soundfile):
  tools/transcribe-env/bp/Scripts/python.exe tools/mp3tomidi_heldout.py
  tools/transcribe-env/bp/Scripts/python.exe tools/mp3tomidi_heldout.py --standalone path/to/candidate
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

SONGS = {
    "arena": dict(yaml=ROOT / "demo/arena.yaml", wav=ROOT / "demo/arena.wav", skip=set()),
    "undertow": dict(yaml=ROOT / "demo3/undertow.yaml", wav=ROOT / "demo3/undertow.wav", skip={"gate l", "gate r"}),
}
DETTATO_MODES = ("parity", "enhanced", "hybrid")


def run(cmd: list, exe: Path) -> float:
    t = time.perf_counter()
    p = subprocess.run([str(c) for c in cmd], executable=str(exe), capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(f"error: {Path(exe).name} failed (exit {p.returncode}):\n{p.stdout}\n{p.stderr}")
    return round(time.perf_counter() - t, 2)


def transcribe(args, out: Path) -> dict:
    times = {}
    for name, c in SONGS.items():
        d = out / name
        d.mkdir(parents=True, exist_ok=True)
        mp3 = d / "source.mp3"
        if not mp3.exists():  # both transcribers read MP3, as in the original benchmark
            subprocess.run([str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(c["wav"]),
                            "-b:a", "192k", str(mp3)], check=True)
        t = {"standalone": run([args.standalone, mp3, "-o", d / "standalone.mid"], args.standalone)}
        if args.rerun_dettato or not all((d / f"{m}.mid").exists() for m in DETTATO_MODES):
            t["parity"] = run([args.dettato, mp3, "-o", d / "parity.mid", "--mode", "parity",
                               "--weights-dir", args.weights_dir], args.dettato)
            t["enhanced"] = run([args.dettato, "--enhance-midi", mp3, d / "parity.mid", "-o", d / "enhanced.mid"], args.dettato)
            t["hybrid"] = run([args.dettato, "--hybrid-midi", mp3, d / "parity.mid", "-o", d / "hybrid.mid"], args.dettato)
        times[name] = t
        print(f"{name}: seconds {t}", flush=True)
    return times


def truth(sd, vsong, c: dict, with_echo: bool):
    orig = vsong.load_song

    def patched(path):
        m, x = orig(path)
        for ch in m.channels:  # symbolic_diff drops any channel named "echo"; rename so they count
            ch.name = ch.name.replace("echo", "ech0").replace("Echo", "Ech0")
        return m, x

    if with_echo:
        vsong.load_song = patched
    try:
        p, d, end = sd.load_yaml_ground_truth(c["yaml"], 0.0, None, c["skip"], {})
    finally:
        vsong.load_song = orig
    pm = {}
    for a, b, k, v in p:
        key = (round(a, 3), k)
        if key not in pm or b > pm[key][1]:
            pm[key] = (a, b, k, v)
    dm = {(round(a, 3), cls): (a, cls, k, v) for a, cls, k, v in d}
    return sorted(pm.values()), sorted(dm.values(), key=lambda z: (z[0], z[2])), end


def score(out: Path) -> dict:
    import soundfile as sf
    import symbolic_diff as sd
    from vulturetracker import song as vsong

    res = {}
    print(f"\n{'':23s}{'Note':>7s}{'NoteChr':>8s}{'Frame':>7s}{'FrmChr':>7s}  {'B/M/H frame':14s}{'Drums':>6s}  K/S/H")
    for name, c in SONGS.items():
        d = out / name
        dur = sf.info(str(c["wav"])).duration
        has_echo = any("echo" in ch.name.lower() for ch in vsong.load_song(str(c["yaml"]))[0].channels)
        for with_echo in (False, True) if has_echo else (False,):
            rp, rd, end = truth(sd, vsong, c, with_echo)
            dur_s = min(end, dur)
            tag = name + (" +echo" if with_echo else "")
            res[tag] = {"truth": {"pitched": len(rp), "drums": len(rd), "seconds": round(dur_s, 2)}}
            for lbl in ("standalone",) + DETTATO_MODES:
                mid = d / f"{lbl}.mid"
                if not mid.exists():
                    continue
                ep, ed = sd.load_midi_events(mid, 0.0, dur_s)
                s = sd.score_symbolic(rp, rd, ep, ed, dur_s, "", "")
                res[tag][lbl] = s
                f1 = lambda k: s[k]["F1"]
                print(f"{tag + ' ' + lbl:23s}{f1('note_onset_pitch_50ms'):7.3f}{f1('note_onset_chroma_50ms'):8.3f}"
                      f"{f1('frame_20ms_pitch'):7.3f}{f1('frame_20ms_chroma'):7.3f}  "
                      f"{f1('frame_bass_le44'):.2f}/{f1('frame_mid_45_63'):.2f}/{f1('frame_high_ge64'):.2f}     "
                      f"{f1('drums_any_35ms'):6.3f}  {f1('drums_kick_35ms'):.2f}/{f1('drums_snare_35ms'):.2f}/"
                      f"{f1('drums_hats_35ms'):.2f}")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--standalone", type=Path, default=ROOT / "build" / "mp3tomidi-independent",
                    help="mp3tomidi-independent binary to score (default: build/mp3tomidi-independent)")
    ap.add_argument("--dettato", type=Path, default=ROOT / "build" / "mp3tomidi",
                    help="Dettato-port binary (default: build/mp3tomidi)")
    ap.add_argument("--weights-dir", type=Path, default=ROOT / "build" / "weights")
    ap.add_argument("--ffmpeg", type=Path, default=ROOT / "dist" / "ffmpeg.exe")
    ap.add_argument("--out", type=Path, default=ROOT / "scratch" / "mp3tomidi-heldout",
                    help="folder for the MP3s, MIDIs and scores.json (default: scratch/mp3tomidi-heldout)")
    ap.add_argument("--rerun-dettato", action="store_true", help="transcribe with the Dettato port again")
    ap.add_argument("--score-only", action="store_true", help="score the MIDIs already in --out")
    args = ap.parse_args()

    need = [c[k] for c in SONGS.values() for k in ("yaml", "wav")]
    if not args.score_only:
        need.append(args.standalone)
        out_has_dettato = all((args.out / n / f"{m}.mid").exists() for n in SONGS for m in DETTATO_MODES)
        if args.rerun_dettato or not out_has_dettato:
            need += [args.dettato, args.weights_dir]
        if not all((args.out / n / "source.mp3").exists() for n in SONGS):
            need.append(args.ffmpeg)
    missing = [str(p) for p in need if not Path(p).exists()]
    if missing:
        ap.error("not found: " + ", ".join(missing))

    args.out.mkdir(parents=True, exist_ok=True)
    report = {"standalone": str(args.standalone)}
    if not args.score_only:
        report["seconds"] = transcribe(args, args.out)
    report["scores"] = score(args.out)
    (args.out / "scores.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out / 'scores.json'}")


if __name__ == "__main__":
    main()
