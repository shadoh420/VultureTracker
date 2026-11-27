"""Run an mp3tomidi binary against demo ground-truth songs with timbre-free symbolic diffing.

Evaluates a standalone mp3tomidi binary (default: build/mp3tomidi-independent) across
the repository's demo targets (demo2/iron_relay.yaml and demo4/vantage.yaml) and any
optional user-supplied audio slice, writing canonical tracker patterns, ASCII tabs,
ABC notation, and JSON metrics via tools/symbolic_diff.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYMBOLIC_DIFF = ROOT / "tools" / "symbolic_diff.py"


def build_demo_targets(demos_dir: Path) -> list[dict]:
    ir_dir = demos_dir / "iron_relay"
    va_dir = demos_dir / "vantage_12_24"
    return [
        {
            "name": "iron_relay_full",
            "stem": "iron_relay",
            "mp3": ir_dir / "source.mp3",
            "ref_args": [
                "--yaml", str(ROOT / "demo2" / "iron_relay.yaml"),
                "--bpm", "140.083",
                "--skip-channels", "arp,arp echo,stab,fx",
                "--title", "iron_relay_full",
            ],
            "compare": [
                ("enhanced", ir_dir / "enhanced.mid"),
                ("baseline", ROOT / "scratch" / "mp3tomidi-listen" / "baseline-backup" / "iron_relay-baseline.mid"),
            ],
        },
        {
            "name": "iron_relay_bars7_14",
            "stem": "iron_relay",
            "mp3": ir_dir / "source.mp3",
            "ref_args": [
                "--yaml", str(ROOT / "demo2" / "iron_relay.yaml"),
                "--bpm", "140.083",
                "--start-s", "10.28",
                "--duration-s", "13.706",
                "--bar-offset", "7",
                "--skip-channels", "arp,arp echo,stab,fx",
                "--title", "iron_relay_bars7_14",
            ],
            "compare": [
                ("enhanced", ir_dir / "enhanced.mid"),
                ("baseline", ROOT / "scratch" / "mp3tomidi-listen" / "baseline-backup" / "iron_relay-baseline.mid"),
            ],
        },
        {
            "name": "vantage_12_24",
            "stem": "vantage",
            "mp3": va_dir / "source.mp3",
            "ref_args": [
                "--yaml", str(ROOT / "demo4" / "vantage.yaml"),
                "--bpm", "168.114",
                "--start-s", "12.0",
                "--midi-start-s", "0.0",
                "--duration-s", "12.0",
                "--bar-offset", "9",
                "--skip-channels", "bed minor,bed major,motif,motif echo,choir,choir echo,fx",
                "--octave-shift", "bass=12",
                "--title", "vantage_12_24",
            ],
            "compare": [
                ("enhanced", va_dir / "enhanced.mid"),
                ("baseline", ROOT / "scratch" / "mp3tomidi-listen" / "baseline-backup" / "vantage-baseline.mid"),
            ],
        },
    ]


def parse_compare_arg(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise ValueError(f"Expected LABEL=PATH for --extra-compare, got {spec!r}")
    label, path_str = spec.split("=", 1)
    label = label.strip()
    if not label or not path_str.strip():
        raise ValueError(f"Invalid --extra-compare value {spec!r}; both label and path are required")
    return label, Path(path_str.strip())


def run_binary(exe: Path, mp3: Path, out_mid: Path) -> dict:
    proc = subprocess.run(
        [str(exe), str(mp3), "-o", str(out_mid)],
        executable=str(exe),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{exe.name} failed on {mp3} (exit {proc.returncode}):\n{proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Unexpected non-JSON stdout from {exe.name}: {proc.stdout[:200]!r}") from exc


def format_metrics_line(name: str, label: str, m: dict) -> str:
    np_m = m.get("note_onset_pitch_50ms", {})
    fp = m.get("frame_20ms_pitch", {})
    fc = m.get("frame_20ms_chroma", {})
    fb = m.get("frame_bass_le44", {})
    fm = m.get("frame_mid_45_63", {})
    fh = m.get("frame_high_ge64", {})
    dr = m.get("drums_any_35ms", {})
    dk = m.get("drums_kick_35ms", {})
    dsn = m.get("drums_snare_35ms", {})
    dh = m.get("drums_hats_35ms", {})
    return (
        f"  {name:20s} {label:11s} "
        f"NP={np_m.get('F1', 0):.3f}(P={np_m.get('P', 0):.2f} R={np_m.get('R', 0):.2f}) "
        f"FP={fp.get('F1', 0):.3f} FC={fc.get('F1', 0):.3f} "
        f"[B={fb.get('F1', 0):.2f} M={fm.get('F1', 0):.2f} H={fh.get('F1', 0):.2f}] "
        f"Dr={dr.get('F1', 0):.3f}(K={dk.get('F1', 0):.2f} S={dsn.get('F1', 0):.2f} H={dh.get('F1', 0):.2f})"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Run an mp3tomidi binary and evaluate it with timbre-free symbolic diffs "
            "(tools/symbolic_diff.py) across demo targets and an optional extra audio slice."
        )
    )
    ap.add_argument(
        "--bin",
        type=Path,
        default=ROOT / "build" / "mp3tomidi-independent",
        help="Path to the mp3tomidi executable (default: build/mp3tomidi-independent)",
    )
    ap.add_argument(
        "--tag",
        default="run",
        help="Subfolder name under --out-root for this run's MIDIs and diffs (default: run)",
    )
    ap.add_argument(
        "--out-root",
        type=Path,
        default=ROOT / "scratch" / "mp3tomidi-listen" / "symbolic-diff-iter",
        help="Output root folder (default: scratch/mp3tomidi-listen/symbolic-diff-iter)",
    )
    ap.add_argument(
        "--demos-dir",
        type=Path,
        default=ROOT / "scratch" / "mp3tomidi-listen" / "demos",
        help="Folder containing staged demo source.mp3 files (default: scratch/mp3tomidi-listen/demos)",
    )
    ap.add_argument(
        "--only",
        default="",
        help="Comma-separated subset of targets to run (e.g. iron_relay_full,vantage_12_24)",
    )
    ap.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to invoke tools/symbolic_diff.py (default: current Python)",
    )
    ap.add_argument("--extra-name", default="extra_slice", help="Name for optional --extra-mp3 benchmark")
    ap.add_argument("--extra-mp3", type=Path, help="Optional extra MP3 to transcribe")
    ap.add_argument("--extra-wav", type=Path, help="Reference WAV for acoustic CQT ridge comparison of --extra-mp3")
    ap.add_argument("--extra-bpm", type=float, help="Grid BPM for --extra-mp3 (required with --extra-mp3)")
    ap.add_argument("--extra-start-s", type=float, default=0.0, help="Start offset in seconds for --extra-mp3")
    ap.add_argument("--extra-duration-s", type=float, default=0.0, help="Slice duration in seconds for --extra-mp3 (0 = full)")
    ap.add_argument("--extra-bar-offset", type=int, default=1, help="First bar number for --extra-mp3")
    ap.add_argument(
        "--extra-compare",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="Optional reference MIDI to compare alongside --extra-mp3 (repeatable)",
    )
    args = ap.parse_args(argv)

    exe = args.bin.resolve()
    if not exe.is_file():
        ap.error(f"Binary not found: {exe}")
    if not SYMBOLIC_DIFF.is_file():
        ap.error(f"Required script not found: {SYMBOLIC_DIFF}")

    targets = build_demo_targets(args.demos_dir)
    if args.extra_mp3 is not None:
        if args.extra_wav is None or args.extra_bpm is None or args.extra_bpm <= 0:
            ap.error("--extra-mp3 requires both --extra-wav and a positive --extra-bpm")
        if not args.extra_mp3.is_file():
            ap.error(f"Extra MP3 not found: {args.extra_mp3}")
        if not args.extra_wav.is_file():
            ap.error(f"Extra reference WAV not found: {args.extra_wav}")
        ref_args = [
            "--audio", str(args.extra_wav),
            "--bpm", str(args.extra_bpm),
            "--start-s", str(args.extra_start_s),
            "--bar-offset", str(args.extra_bar_offset),
            "--title", args.extra_name,
        ]
        if args.extra_duration_s > 0:
            ref_args.extend(["--duration-s", str(args.extra_duration_s)])
        try:
            extra_cmp = [parse_compare_arg(s) for s in args.extra_compare]
        except ValueError as exc:
            ap.error(str(exc))
        targets.append(
            {
                "name": args.extra_name,
                "stem": args.extra_name,
                "mp3": args.extra_mp3,
                "ref_args": ref_args,
                "compare": extra_cmp,
            }
        )

    valid_names = {t["name"] for t in targets}
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    unknown = sorted(only - valid_names)
    if unknown:
        ap.error(f"Unknown target(s) in --only: {', '.join(unknown)}. Valid: {', '.join(sorted(valid_names))}")

    selected = [t for t in targets if not only or t["name"] in only]
    for t in selected:
        if not t["mp3"].is_file():
            ap.error(f"Input MP3 missing for {t['name']}: {t['mp3']}")

    out_dir = args.out_root / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)

    ran_mp3: dict[Path, Path] = {}
    meta_map: dict[str, dict] = {}
    summary: dict[str, dict] = {}

    for t in selected:
        mp3 = t["mp3"].resolve()
        if mp3 not in ran_mp3:
            out_mid = out_dir / f"{t['stem']}-ind.mid"
            meta = run_binary(exe, mp3, out_mid)
            ran_mp3[mp3] = out_mid
            meta_map[t["stem"]] = meta
            print(
                f"[RUN {t['stem']}] bpm={meta['bpm']:.3f} notes={meta['notes']} "
                f"drums={meta['drums']} (K={meta['kicks']} S={meta['snares']} "
                f"H={meta['hats']} C={meta['crashes']}) elapsed={meta['elapsed_s']:.2f}s"
            )
        ind_mid = ran_mp3[mp3]

        target_out = out_dir / t["name"]
        cmd = [args.python, str(SYMBOLIC_DIFF), *t["ref_args"]]
        for label, cpath in t["compare"]:
            if cpath.is_file():
                cmd.extend(["--midi", f"{label}={cpath}"])
        cmd.extend(["--midi", f"independent={ind_mid}", "--out-dir", str(target_out)])
        subprocess.run(cmd, check=True)

        metrics = json.loads((target_out / "symbolic-metrics.json").read_text(encoding="utf-8"))
        summary[t["name"]] = metrics["modes"]

    print(f"\n=== Summary ({args.tag}) ===")
    for name, modes in summary.items():
        for label, m in modes.items():
            print(format_metrics_line(name, label, m))

    (out_dir / "summary.json").write_text(
        json.dumps({"meta": meta_map, "targets": summary}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
