"""CLI: python -m vulturetracker {check,build,render,info,import,synth,audition,tryout,gui} ..."""
import argparse
import json
import sys
from pathlib import Path

from . import api
from .song import SongError


def _print_info(d):
    mins, secs = divmod(d["duration_seconds"], 60)
    print(f"  title:       {d['title']!r}  ({d['type']}, {d['tracker']})")
    print(f"  duration:    {int(mins)}:{secs:06.3f}")
    print(f"  channels:    {d['channels']} (used in patterns)")
    print(f"  instruments: {d['instruments']}  {d['instrument_names']}")
    print(f"  samples:     {d['samples']}  {d['sample_names']}")
    print(f"  patterns:    {d['patterns']}  rows {d['pattern_rows']}")
    print(f"  orders:      {d['orders']}")
    for w in d["warnings"]:
        print(f"  libopenmpt: {w}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vulturetracker", description="Compile YAML song files to Impulse Tracker modules.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="validate a song file")
    p.add_argument("song")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p = sub.add_parser("build", help="compile a song file to .it and verify it with libopenmpt")
    p.add_argument("song")
    p.add_argument("-o", "--output", help="output .it (default: next to the song)")
    p.add_argument("--render", metavar="WAV", help="also render to this WAV")
    p = sub.add_parser("render", help="render an .it (or a song file) to WAV")
    p.add_argument("module")
    p.add_argument("-o", "--output", help="output .wav (default: next to the input)")
    p.add_argument("--repeat", type=int, default=0, help="extra times to loop the song (default 0)")
    p.add_argument("--rate", type=int, default=44100)
    p.add_argument("--oversample", type=int, default=2,
                   help="mix at this multiple of the rate and band-limit down, so nothing aliases (default 2; 1 = off)")
    p = sub.add_parser("info", help="load a module with libopenmpt and print its metadata")
    p.add_argument("module")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("import", help="convert an existing .it, .xm, .s3m or .mod into a song file (samples extracted as WAVs)")
    p.add_argument("module")
    p.add_argument("-o", "--output", required=True, help="output song .yaml")
    p.add_argument("--samples-dir", help="where to write WAVs (default: <output stem>_samples next to the song)")
    p = sub.add_parser("synth", help="render the samples in a Surge XT sample recipe (see SAMPLING.md)")
    p.add_argument("recipe")
    p.add_argument("--only", help="render only samples whose name matches this glob")
    p = sub.add_parser("audition", help="play every Surge patch (or audio file) matching a glob into one WAV to compare them")
    p.add_argument("patches", help="e.g. 'Pads/*', '3rdparty/Cybersoda/Drums/*' or a file glob like 'tools/cc0/**/*.wav'")
    p.add_argument("-o", "--output", default="audition.wav")
    p.add_argument("--note", default="C-4")
    p.add_argument("--hold", type=float, default=1.5)
    p = sub.add_parser("tryout", help="render part of a song once per candidate sample, to compare sounds in context")
    p.add_argument("song")
    p.add_argument("--sample", type=int, required=True, help="sample slot to swap")
    p.add_argument("candidates", nargs="+", help="candidate WAVs (globs allowed)")
    p.add_argument("--orders", help="order positions to play, e.g. 2-5 (default: the whole song)")
    p.add_argument("-o", "--output", default="tryout.wav")
    p = sub.add_parser("gui", help="open the app for a song (its own window with pywebview installed, else the browser)")
    p.add_argument("song", nargs="?", help="song to open (default: the app's open-a-song screen)")
    p.add_argument("--port", type=int, default=0, help="listen port (default: 8723 when free, else any free port)")
    p.add_argument("--browser", action="store_true", help="open in the default browser instead of an app window")
    p.add_argument("--no-browser", action="store_true", help="serve only; print the URL")
    p = sub.add_parser("surge-params", help="list Surge XT parameter names usable in a recipe's params:")
    p.add_argument("filter", nargs="?", default="")
    argv = sys.argv[1:] if argv is None else list(argv)
    # Double-clicked exe (no args) or a song dropped onto it: open the GUI.
    if not argv:
        argv = ["gui"]
    elif argv[0].lower().endswith((".yaml", ".yml")):
        argv = ["gui"] + argv
    args = ap.parse_args(argv)

    try:
        if args.cmd == "check":
            res = api.check(args.song)
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                for line in res["errors"] + res["warnings"]:
                    print(line)
                if res["ok"]:
                    s = res["summary"]
                    print(f"OK: {s['title']!r}: {s['channels']} channels, {s['instruments']} instruments, "
                          f"{s['samples']} samples, {s['patterns']} patterns, {len(s['orders'])} orders")
                else:
                    print(f"{len(res['errors'])} error(s)")
            return 0 if res["ok"] else 1

        if args.cmd == "build":
            out = args.output or str(Path(args.song).with_suffix(".it"))
            res = api.build(args.song, out)
            for w in res["warnings"]:
                print(w)
            print(f"wrote {out} ({res['bytes']} bytes); libopenmpt reports:")
            _print_info(res["libopenmpt"])
            for m in res["mismatches"]:
                print(f"MISMATCH: {m}")
            if args.render:
                secs = api.render(out, args.render)
                print(f"rendered {args.render} ({secs:.2f} s)")
            return 1 if res["mismatches"] else 0

        if args.cmd == "render":
            out = args.output or str(Path(args.module).with_suffix(".wav"))
            secs = api.render(args.module, out, repeat=args.repeat, rate=args.rate, oversample=args.oversample)
            print(f"rendered {out} ({secs:.2f} s)")
            return 0

        if args.cmd == "info":
            d = api.info(args.module)
            if args.json:
                print(json.dumps(d, indent=2))
            else:
                print(args.module)
                _print_info(d)
            return 0

        if args.cmd == "synth":
            from .synth import render_recipe
            written = render_recipe(args.recipe, args.only)
            print(f"rendered {len(written)} samples")
            return 0

        if args.cmd == "audition":
            from .synth import audition
            names = audition(args.patches, args.output, note=args.note, hold=args.hold)
            print(f"wrote {args.output}: {len(names)} sounds, timestamps above")
            return 0

        if args.cmd == "tryout":
            import glob
            files = [f for c in args.candidates for f in (sorted(glob.glob(c)) or [c])]
            orders = None
            if args.orders:
                a, _, b = args.orders.partition("-")
                orders = (int(a), int(b or a) + 1)
            for t, f in api.tryout(args.song, args.sample, files, orders, args.output):
                print(f"{int(t // 60)}:{t % 60:05.2f}  {f}")
            print(f"wrote {args.output}: {len(files)} versions, timestamps above")
            return 0

        if args.cmd == "gui":
            from .gui import serve
            return serve(args.song, args.port, not args.no_browser, window=not (args.browser or args.no_browser))

        if args.cmd == "surge-params":
            from .synth import list_params
            print("\n".join(list_params(args.filter)))
            return 0

        if args.cmd == "import":
            from .itreader import import_it
            out = Path(args.output)
            sdir = Path(args.samples_dir) if args.samples_dir else out.with_name(out.stem + "_samples")
            song, warnings = import_it(args.module, out, sdir)
            for w in warnings:
                print(f"warning: {w}")
            wavs = sum(1 for smp in song["samples"].values() if "file" in smp)
            print(f"wrote {out} and {wavs} WAVs in {sdir}")
            return 0
    except SongError as e:
        for line in e.errors + e.warnings:
            print(line)
        print(f"{len(e.errors)} error(s)")
        return 1
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
