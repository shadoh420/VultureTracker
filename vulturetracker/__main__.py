"""CLI: python -m vulturetracker {check,build,render,info,import,synth,audition,tryout,index,export,collect,sections,
checkpoint,phrase,undo,redo,trim-history,gui,surge-params} ..."""
import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from . import __version__, api
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


def _say(text, file=None):
    """A line that may hold what was typed in the app (names, notes): what the console cannot show becomes ?."""
    file = file or sys.stdout
    enc = getattr(file, "encoding", None) or "utf-8"
    print(str(text).encode(enc, "replace").decode(enc), file=file)


WRITES = {"sections": ("save", "delete", "move", "duplicate", "rename"), "checkpoint": ("save", "restore", "delete"),
          "phrase": ("capture", "set", "accept")}
HISTORY = ("undo", "redo", "trim-history")  # commands on the song's undo history: they always write


def _open_song(song, write, wait=0.0):
    """(the song opened headless, its lock or None); what the opening noticed goes to stderr. A command that writes holds
    the song's lock (gui.app_lock_path) to its end, so an app opening the song meanwhile waits for it or opens it
    read-only, and it is refused while an app or another command holds the lock (after `wait` seconds of asking again).
    One that reads holds it while the song is read; a song open in the app is read as it is (an interrupted save's
    journal or a file that does not parse is the app's to reconcile)."""
    from .fileio import lock_file, unlock_file
    from .gui import LOCKS, State, app_lock_path
    LOCKS.mkdir(parents=True, exist_ok=True)
    lock, until = lock_file(app_lock_path(song)), time.monotonic() + wait
    while write and lock is None and time.monotonic() < until:
        time.sleep(0.25)
        lock = lock_file(app_lock_path(song))
    if write and lock is None:
        raise ValueError(f"{Path(song).name} is open in VultureTracker or being changed by another command; the app keeps "
                         f"its history and tryout settings and would write them over this change: make it in the app, or "
                         f"open another song there (or let the command finish) first")
    try:
        st = State(song, headless=True, passive=lock is None)
    except BaseException:
        if lock:
            unlock_file(lock)
        raise
    if lock and not write:
        unlock_file(lock)
    for line in st.notices:
        _say(f"note: {line}", sys.stderr)
    return st, lock if write else None


def _song_tool(args):
    """sections, checkpoint and phrase: the app's own methods on the song opened headless. What they change goes into
    the song's history (.history.json) and tryout settings (.tryout.json) as in the app, so the app must not have the
    song open: it would write its own over them."""
    from .fileio import unlock_file
    st, lock = _open_song(args.song, args.cmd in HISTORY or args.action in WRITES[args.cmd], args.wait)
    seen = len(st.notices)
    try:
        return _song_command(args, st)
    finally:
        for line in st.notices[seen:]:
            _say(f"note: {line}", sys.stderr)
        if lock:
            unlock_file(lock)


def _song_command(args, st):
    from . import phrases
    from .export import sources
    from .fileio import atomic_write, protect_outputs
    for line in st.error or []:
        print(line)
    if args.cmd in HISTORY:
        if args.cmd == "trim-history":
            st.trim_history(args.keep)
        elif not (st.future if args.cmd == "redo" else st.history):
            raise ValueError(f"nothing to {args.cmd}")
        else:
            st.undo(redo=args.cmd == "redo")
        print({"undo": "undone", "redo": "redone", "trim-history": "trimmed"}[args.cmd]
              + f": {len(st.history)} undo and {len(st.future)} redo steps")
        return 0
    if st.error and args.cmd != "checkpoint":  # a checkpoint can bring back a song that no longer compiles
        return 1
    if args.action and args.cmd != "phrase" and not args.name:
        raise ValueError(f"{args.cmd} {args.action} needs a name")
    say = (lambda *a: None) if args.json else _say

    if args.cmd == "sections":
        if args.action:
            need = {"save": 2, "delete": 0, "move": 1, "duplicate": 1, "rename": 0}[args.action]
            if len(args.orders) != need or (args.action == "rename" and not args.new_name):
                raise ValueError({"save": "sections save NAME FIRST END: the order positions FIRST to END-1",
                                  "delete": "sections delete NAME takes no order positions",
                                  "move": "sections move NAME TO: the order boundary it goes to",
                                  "duplicate": "sections duplicate NAME TO: the order boundary the copy goes to",
                                  "rename": "sections rename NAME --as NEW"}[args.action])
            body = {"action": args.action, "name": args.name}
            if args.action == "save":
                body.update(start=args.orders[0], end=args.orders[1])
            elif args.action == "rename":
                body.update(new_name=args.new_name)
            elif args.orders:
                body.update(to=args.orders[0], independent=not args.shared, new_name=args.new_name)
            st.section_edit(body)
        orders = [str(o) for o in st.song.get("orders") or []]
        sections = st.song.get("sections") or {}
        if args.json:
            print(json.dumps({"sections": {n: {"first": a, "end": b, "orders": orders[a:b]} for n, (a, b) in sections.items()}},
                             indent=2))
        for name, (a, b) in sections.items():
            say(f"{name}: orders {a}-{b - 1} ({' '.join(orders[a:b])})")
        if not sections:
            say("no named sections")
        return 0

    if args.cmd == "checkpoint":
        res = st.checkpoint(args.name, args.action) if args.action else None
        if args.json:
            print(json.dumps({"checkpoints": {n: (s.get("version") or {}) for n, s in st.checkpoints.items()},
                              "undo": len(st.history), "redo": len(st.future),
                              **({"diff": res["lines"]} if args.action == "diff" else {})}, indent=2))
        elif not args.action:
            for name, step in st.checkpoints.items():
                v = step.get("version") or {}
                _say(f"{name}  (the song as of {v.get('mtime', '?')}, version {v.get('hash', '?')})")
            print(f"{len(st.checkpoints)} checkpoints; {len(st.history)} undo and {len(st.future)} redo steps")
        elif args.action == "diff":
            for line in res["lines"] or ["the song is as the checkpoint has it"]:
                _say(line)
        else:
            done = {"save": "saved", "restore": "restored", "delete": "deleted"}[args.action]
            _say(f"{done} checkpoint {args.name}")
        return 0

    if args.action == "capture":
        if args.order is None or not args.rows or not args.channels:
            raise ValueError("phrase capture needs --order, --rows and --channels")
        r0, _, r1 = args.rows.partition("-")
        phrases.action(st, {"action": "capture", "order": args.order, "r0": int(r0), "r1": int(r1 or r0),
                            "chans": [int(c) - 1 for c in args.channels.split(",")], "count": args.count})
    elif args.action:
        if not st.meta.get("phrase"):
            raise ValueError("capture a phrase first (phrase SONG capture --order N --rows A-B --channels C)")
        v = (args.variant or "").strip()
        index = -1 if v.lower() == "absent" else "ABCD".index(v.upper()) if len(v) == 1 and v.upper() in "ABCD" else -2
        if not -1 <= index < len(st.meta["phrase"]["variants"]):
            raise ValueError(f"name the alternative: {', '.join('ABCD'[:len(st.meta['phrase']['variants'])])} (by place) or absent")
        if args.action == "set":
            body = {"action": "update", "variant": index}
            if args.cells:
                cells = sys.stdin.read() if args.cells == "-" else Path(args.cells).read_text(encoding="utf-8")
                body["data"] = cells.strip("\n")
            body.update({k: getattr(args, k) for k in ("name", "stars", "note") if getattr(args, k) is not None})
            phrases.action(st, body)
        elif args.action == "diff":
            lines = phrases.action(st, {"action": "diff", "variant": index})["lines"]
            if args.json:
                print(json.dumps({"diff": lines}, indent=2))
            for line in lines or ["no difference"]:
                say(line)
            return 0
        elif args.action == "render":
            if not args.output:
                raise ValueError("phrase render needs -o OUTPUT.wav")
            phrase = st.meta["phrase"]
            protect_outputs([args.output], sources(st))
            atomic_write(Path(args.output), phrases.variant_wav(st, phrase, phrases.edited_text(st, phrase, index)),
                         replace=args.replace)
            print(json.dumps({"wrote": str(Path(args.output).resolve())}) if args.json else f"wrote {args.output}")
            return 0
        else:
            phrases.action(st, {"action": "accept", "variant": index})
            say(f"accepted {v.upper() if index >= 0 else 'absent'} into the song (one undo step)")
    phrase = st.meta.get("phrase")
    if args.json:
        print(json.dumps({"phrase": phrase and {k: phrase[k] for k in ("order", "pattern", "r0", "r1", "chans", "variants",
                                                                        "absent", "accepted") if k in phrase}}, indent=2))
    if not phrase:
        say("no phrase captured")
        return 0
    accepted = phrase.get("accepted")
    say(f"order {phrase['order']} (pattern {phrase['pattern']}), rows {phrase['r0']}-{phrase['r1']}, channels "
        + ",".join(str(c + 1) for c in phrase["chans"])
        + ("" if accepted is None else f"; accepted: {'ABCD'[accepted] if accepted >= 0 else 'absent'}"))
    for label, var in [*zip("ABCD", phrase["variants"]), ("absent", phrase["absent"])]:
        say(" ".join(filter(None, (f"{label}: {var['name']}", "*" * var["stars"], var["note"] and f"({var['note']})"))))
        for line in (var.get("data") or "").splitlines():
            say("    " + line)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vulturetracker", description="Compile YAML song files to Impulse Tracker modules.")
    ap.add_argument("--version", action="version", version=f"VultureTracker {__version__}")
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
    p = sub.add_parser("import", help="convert an existing .it, .xm, .s3m or .mod into a song file (samples extracted as "
                                      "WAVs), or a Guitar Pro tab (.gp3, .gp4, .gp5; needs pyguitarpro) or a MIDI file "
                                      "(.mid, .midi; needs mido) with placeholder sounds")
    p.add_argument("module")
    p.add_argument("-o", "--output", required=True, help="output song .yaml")
    p.add_argument("--samples-dir", help="where to write WAVs (default: <output stem>_samples next to the song)")
    p = sub.add_parser("synth", help="render the samples in a sample recipe: Surge XT, Dexed and OB-Xd patches, recordings, Faust code, resynthesis (see SAMPLING.md)")
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
    p.add_argument("candidates", nargs="*", help="candidate WAVs (globs allowed)")
    p.add_argument("--like", metavar="WAV", help="also the sounds of the library nearest this WAV by timbre (see index)")
    p.add_argument("-k", "--k", type=int, default=8, help="how many --like finds (default 8)")
    p.add_argument("--index", help="the library index (default: the app's, or $VT_LIBRARY)")
    p.add_argument("--orders", help="order positions to play, e.g. 2-5 (default: the whole song)")
    p.add_argument("-o", "--output", default="tryout.wav")
    p = sub.add_parser("index", help="index the WAVs under folders by timbre, for tryout --like and the app's MAP tab")
    p.add_argument("folders", nargs="*", help="folders to index (default: the ones indexed last, else samples/ and "
                                              "tools/cc0); the list is saved with the index")
    p.add_argument("--index", help="the index file (default: the app's, or $VT_LIBRARY)")
    p.add_argument("--like", metavar="WAV", help="then print the sounds nearest this WAV")
    p.add_argument("-k", "--k", type=int, default=8)
    p = sub.add_parser("export", help="render a song or a section as the app's RENDER & EXPORT does: IT, WAV, MP3, OGG or "
                                      "FLAC, aligned stems, a game loop (reads the app's .tryout.json for --mix current "
                                      "and --respect-mutes; writes nothing else beside the song)")
    p.add_argument("song")
    p.add_argument("-o", "--destination", help="output folder (default: beside the song)")
    p.add_argument("--name", help="output file name without extension (default: the song's)")
    p.add_argument("-f", "--format", default="wav", choices=["it", "wav", "mp3", "ogg", "flac"])
    p.add_argument("--section", default="", help="a named section instead of the whole song")
    p.add_argument("--tail", type=float, default=2.0, help="seconds of ring-out after the end, 0-10 (0: cut at the end)")
    p.add_argument("--stems", action="store_true", help="also a file per channel in use, all the same length")
    p.add_argument("--no-song", action="store_true", help="the stems only")
    p.add_argument("--with-it", action="store_true", help="also the .it beside the audio")
    p.add_argument("--loop", action="store_true", help="a seamless game loop: WAV smpl chunk, OGG/FLAC LOOPSTART and "
                                                       "LOOPLENGTH; the tail is its release")
    p.add_argument("--mix", choices=["saved", "current"], default="saved",
                   help="current: the app's unwritten faders and selected candidate")
    p.add_argument("--respect-mutes", action="store_true", help="apply the app's audition mute and solo")
    p.add_argument("--replace", action="store_true", help="replace earlier exports of the same names")
    p = sub.add_parser("collect", help="copy a song into a new folder with its samples, candidates, notes and recipes, "
                                       "as the app's PROJECT > Collect Samples does")
    p.add_argument("song")
    p.add_argument("destination", help="a new folder (never merged into an existing one)")
    p.add_argument("--zip", action="store_true", help="also <folder>.zip beside it")
    tool = argparse.ArgumentParser(add_help=False)  # what the commands on a song's history and settings share
    tool.add_argument("--wait", type=float, default=0, metavar="SECONDS",
                      help="while the song is open in the app or another command, ask again for this long before giving up")
    listed = argparse.ArgumentParser(add_help=False)
    listed.add_argument("--json", action="store_true", help="machine-readable output")
    p = sub.add_parser("sections", parents=[tool, listed],
                       help="list a song's named sections, or save, delete, move, duplicate or rename one as the app's "
                            "SONG OVERVIEW does (each an undo step in the app's history)")
    p.add_argument("song")
    p.add_argument("action", nargs="?", choices=["save", "delete", "move", "duplicate", "rename"])
    p.add_argument("name", nargs="?")
    p.add_argument("orders", nargs="*", type=int, help="save: FIRST END, the order positions FIRST to END-1 (0 is the "
                                                        "first); move, duplicate: TO, the order boundary it goes to")
    p.add_argument("--shared", action="store_true", help="duplicate: the copy plays the same patterns (default: copies)")
    p.add_argument("--as", dest="new_name", help="rename: the new name; duplicate: the copy's name (default: '<name> copy')")
    p = sub.add_parser("checkpoint", parents=[tool, listed],
                       help="list a song's named checkpoints, or save, diff, restore or delete one as the app's PROJECT "
                            "tab does")
    p.add_argument("song")
    p.add_argument("action", nargs="?", choices=["save", "diff", "restore", "delete"])
    p.add_argument("name", nargs="?")
    p = sub.add_parser("phrase", parents=[tool, listed],
                       help="alternatives of a line over a frozen accompaniment, as the app's PHRASES tab: capture rows "
                            "of channels, set an alternative, diff, render or accept one (no action: show the comparison)")
    p.add_argument("song")
    p.add_argument("action", nargs="?", choices=["capture", "set", "diff", "render", "accept"])
    p.add_argument("variant", nargs="?", help="A, B, C or D (by place), or absent: the line left out")
    p.add_argument("--order", type=int, help="capture: the order position (0 is the first)")
    p.add_argument("--rows", help="capture: rows FIRST-LAST of its pattern, e.g. 0-15")
    p.add_argument("--channels", help="capture: channels numbered as the app shows them (1 is the first), e.g. 2,3")
    p.add_argument("--count", type=int, default=3, help="capture: how many alternatives, 2-4 (default 3)")
    p.add_argument("--cells", help="set: a file with the alternative's rows, cells as in a pattern with | between "
                                   "channels (- reads them from stdin)")
    p.add_argument("--name", help="set: its name")
    p.add_argument("--stars", type=int, help="set: a rating 0-5")
    p.add_argument("--note", help="set: a note")
    p.add_argument("-o", "--output", help="render: the WAV to write")
    p.add_argument("--replace", action="store_true", help="render: replace an existing WAV of that name")
    for cmd, what in (("undo", "undo the song's last change, as the app's undo does (its history: <song>.history.json)"),
                      ("redo", "redo the change undo took back"),
                      ("trim-history", "drop the song's older undo steps and every redo step, as PROJECT's history "
                                       "trim does (named checkpoints stay)")):
        p = sub.add_parser(cmd, parents=[tool], help=what)
        p.add_argument("song")
        if cmd == "trim-history":
            p.add_argument("--keep", type=int, default=0, help="the most recent undo steps to keep, 0-200 (default 0)")
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
            api.protect_outputs([out] + ([args.render] if args.render else []), api.output_sources(args.song))
            res = api.build(args.song, out)
            for w in res["warnings"]:
                print(w)
            print(f"wrote {out} ({res['bytes']} bytes); libopenmpt reports:")
            _print_info(res["libopenmpt"])
            for m in res["mismatches"]:
                print(f"MISMATCH: {m}")
            if args.render:
                secs = api.render(out, args.render, sources=api.output_sources(args.song))
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
            if args.like:
                from .library import Library, default_index
                lib = Library(args.index or default_index())
                lib.scan()
                near = lib.nearest(args.like, args.k, exclude=files)
                for f, d in near:
                    print(f"like {Path(args.like).name}: {d:5.2f}  {f}")
                files += [f for f, _ in near]
            if not files:
                print("error: no candidates (give WAVs, or --like WAV with an index that holds sounds)", file=sys.stderr)
                return 1
            orders = None
            if args.orders:
                a, _, b = args.orders.partition("-")
                orders = (int(a), int(b or a) + 1)
            for t, f in api.tryout(args.song, args.sample, files, orders, args.output):
                print(f"{int(t // 60)}:{t % 60:05.2f}  {f}")
            print(f"wrote {args.output}: {len(files)} versions, timestamps above")
            return 0

        if args.cmd == "index":
            from .library import Library, default_index
            lib = Library(args.index or default_index())
            last = [0]

            def progress(done, total, path):
                if done == total or done - last[0] >= 100:
                    last[0] = done
                    print(f"  {done}/{total}  {path}")
            res = lib.scan(args.folders or None, progress)
            print(f"{lib.path}: {res['files']} sounds under {', '.join(lib.roots)} ({res['read']} read, "
                  f"{res['dropped']} gone, {res['errors']} unreadable)")
            if args.like:
                for f, d in lib.nearest(args.like, args.k):
                    print(f"{d:6.2f}  {f}")
            return 0

        if args.cmd == "gui":
            from .gui import serve
            return serve(args.song, args.port, not args.no_browser, window=not (args.browser or args.no_browser))

        if args.cmd in ("export", "collect"):
            from .gui import _encode
            st = _open_song(args.song, False)[0]
            for line in st.error or []:
                print(line)
            if st.error:
                return 1
            if args.cmd == "collect":
                from .project import collect
                res = collect(st, str(Path(args.destination).resolve()), args.zip)
                print(f"{res['report']} {res['path']}" + (f", {res['zip']}" if res["zip"] else ""))
                return 0
            from .export import RATE, prepare, run
            res = run(prepare(st, {
                "destination": str(Path(args.destination).resolve()) if args.destination else "", "name": args.name,
                "fmt": args.format, "region": args.section, "tail": args.tail, "stems": args.stems, "song": not args.no_song,
                "include_it": args.with_it, "loop": args.loop, "mix": args.mix, "replace": args.replace,
                "mutes": "respect" if args.respect_mutes else "ignore"}), _encode)
            for w in res["warnings"]:
                print(w)
            for f in res["files"]:
                print(f"wrote {f}")
            if res["loop"]:
                print(f"loop: frames {res['loop'][0]}-{res['loop'][1]}, then {res['seconds'] - res['loop'][1] / RATE:.2f} s of release")
            if res["status"] != "done":
                print(f"error: {res['error']}", file=sys.stderr)
                return 1
            return 0

        if args.cmd in ("sections", "checkpoint", "phrase", *HISTORY):
            return _song_tool(args)

        if args.cmd == "surge-params":
            from .synth import list_params
            print("\n".join(list_params(args.filter)))
            return 0

        if args.cmd == "import":
            from .itreader import import_it
            out = Path(args.output)
            sdir = Path(args.samples_dir) if args.samples_dir else out.with_name(out.stem + "_samples")
            if Path(args.module).suffix.lower() in (".gp3", ".gp4", ".gp5"):
                from .gpimport import import_gp
                song, warnings = import_gp(args.module, out, sdir)
            elif Path(args.module).suffix.lower() in (".mid", ".midi"):
                from .midiimport import import_midi
                song, warnings = import_midi(args.module, out, sdir)
            else:
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
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
