"""The exe's launcher (tools/build_exe.py packs this; __main__.py uses relative imports). `--selfcheck` imports every
packed optional path and prints one line per item (`ok`, `FAIL`, `info`); exit 1 on any FAIL. tools/exe_check.py runs it."""
import sys
import multiprocessing
from pathlib import Path

if not getattr(sys, "frozen", False):  # `python tools/exe_entry.py` from the checkout
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def selfcheck():
    import importlib
    import shutil
    lines = []

    def check(name, fn):
        try:
            lines.append(f"ok {name} {fn()}")
        except Exception as e:  # noqa: BLE001 - every failure is a line
            lines.append(f"FAIL {name}: {type(e).__name__}: {e}")

    def info(name, fn):
        try:
            lines.append(f"info {name} {fn()}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"info {name} absent ({type(e).__name__}: {e})")

    def version(mod):
        return lambda: getattr(importlib.import_module(mod), "__version__", "present")

    check("vulturetracker", version("vulturetracker"))
    pkg = Path(importlib.import_module("vulturetracker").__file__).parent
    for name in ("gui.html", "icon.png", "SONG_FORMAT.md"):  # build_exe's --add-data (SONG_FORMAT.md sits beside the checkout)
        check(name, lambda n=name: f"{next(p for p in (pkg / n, pkg.parent / n) if p.exists()).stat().st_size} bytes")
    check("faust_examples", lambda: f"{len(list((pkg / 'faust_examples').glob('*.dsp')))} .dsp files"
          if (pkg / "faust_examples" / "pluck.dsp").exists() else _missing(pkg / "faust_examples"))
    check("web", lambda: f"{len(list((pkg / 'web').glob('*.*')))} files" if (pkg / "web" / "libopenmpt.wasm").exists() else _missing(pkg / "web"))
    for name in ("tablature.js", "tablature.css", "score-print.html", "alphaTab.min.js", "Bravura.woff2"):
        check(name, lambda n=name: f"{(pkg / 'web' / n).stat().st_size} bytes")
    check("TuxGuitar scale notice", lambda: f"{(pkg / 'web' / 'licenses' / 'TuxGuitar-scales-NOTICE.txt').stat().st_size} bytes")
    check("libopenmpt", lambda: importlib.import_module("vulturetracker.openmpt").library_version())
    check("native score audio", _native_score_check)
    check("native TG interchange", version("vulturetracker.tgimport"))
    check("PowerTab and TablEdit import", lambda: [importlib.import_module(f"vulturetracker.{m}") for m in ("tab_binary", "ptb", "tef")] and "present")
    check("collection PDF delivery", version("vulturetracker.score_pdf"))
    check("native GP5 export", version("vulturetracker.gpexport"))
    check("legacy TG and GP1/GP2 readers", lambda: [importlib.import_module(f"vulturetracker.{m}") for m in ("tglegacy", "gplegacy")] and "present")
    check("ASCII, LilyPond and MusicXML writers", lambda: [importlib.import_module(f"vulturetracker.{m}") for m in ("asciitab", "notation_export")] and "present")
    check("TuxGuitar notation notice", lambda: f"{(pkg / 'licenses' / 'TuxGuitar-notation-NOTICE.txt').stat().st_size} bytes")
    check("chord tools", version("vulturetracker.chord_tools"))
    check("chord library", version("vulturetracker.chord_library"))
    check("chord sorting", version("vulturetracker._java_priority_sort"))
    for name in ("TuxGuitar-LGPL-2.1.txt", "TuxGuitar-AUTHORS.txt", "TuxGuitar-chord-NOTICE.txt",
                 "OpenJDK-TimSort-GPL-2.0-with-classpath.txt", "OpenJDK-TimSort-NOTICE.txt"):
        check(name, lambda n=name: f"{(pkg / 'licenses' / n).stat().st_size} bytes")
    check("plugins", lambda: f"{len(importlib.import_module('vulturetracker.plugins').EFFECTS)} DMO effects")
    for mod in ("numpy", "yaml", "webview", "pedalboard", "mido", "guitarpro", "sounddevice"):
        check(mod, version(mod))
    info("faust", lambda: "faustwasm present" if importlib.import_module("vulturetracker.faust").have() else "faustwasm not fetched")
    info("node", lambda: shutil.which("node") or "not on PATH")
    info("Pillow", version("PIL"))
    exe = Path(sys.executable).parent if getattr(sys, "frozen", False) else None
    info("ffmpeg", lambda: str(exe / "ffmpeg.exe") if exe and (exe / "ffmpeg.exe").exists() else (shutil.which("ffmpeg") or "not beside the exe, not on PATH"))
    if sys.stdout:  # a --windowed exe launched without a console has no stdout
        sys.stdout.reconfigure(errors="replace")
        print("\n".join(lines))
    return 1 if any(l.startswith("FAIL") for l in lines) else 0


def _missing(p):
    raise FileNotFoundError(p)


def _native_score_check():
    """Exercise packaged tempo steps, grouped parent, gain, pitch and tail capabilities."""
    import math
    import struct
    from fractions import Fraction
    from vulturetracker.itwriter import write_it
    from vulturetracker.model import Cell, Channel, Module, Pattern, Sample, Loop
    from vulturetracker.openmpt import LoadedModule
    wave = [round(8000 * math.sin(i * 2 * math.pi / 64)) for i in range(256)]
    rows = [[Cell()] for _ in range(16)]
    rows[1][0] = Cell(effect=20, param=83)
    backing = write_it(Module(tempo=137, speed=1, channels=[Channel()], samples=[Sample(data=[wave], loop=Loop(0, 256))],
                              patterns=[Pattern('check', rows)], orders=[0]))
    event = dict(id='check', ch=0, pitch=60, source_instrument=1, volume=48, velocity=95)
    plan = dict(version=1, sample_rate=48000, tempo=137,
                tempos=[dict(at=[0, 1], bpm=137), dict(at=[1, 24], bpm=83)], duration={'frames': 2048}, events=[
        dict(event, frame=0, type='note_on', layers=[dict(pitch=60, velocity=47),
                                                  dict(pitch=60, velocity=31), dict(pitch=72, velocity=95)]),
        dict(type='pitch', id='check', frame=512, semitones=1.5),
        dict(event, frame=1024, type='note_off'),
        dict(type='pitch', id='check', frame=1536, semitones=0)])
    with LoadedModule(backing, 48000, 1, plan=plan) as player:
        pcm = player.render(48000, oversample=1, floats=True, max_seconds=Fraction(4096, 48000))
        if len(pcm) != 4096 * 8 or not player._in_tail or not any(v[0] for v in struct.iter_unpack('<f', pcm)):
            raise RuntimeError('native score did not render its scheduled note and tail')
    plan['events'] = [dict(event, id='held', frame=0, type='note_on', hold=True),
                      dict(event, id='next', frame=512, type='note_on', pitch=64),
                      dict(type='pitch', id='held', frame=768, semitones=1.5),
                      dict(event, id='held', frame=1024, type='note_off'),
                      dict(event, id='next', frame=1536, type='note_off')]
    with LoadedModule(backing, 48000, 1, plan=plan) as player:
        pcm = player.render(48000, oversample=1, floats=True, max_seconds=Fraction(4096, 48000))
        if len(pcm) != 4096 * 8 or not player._in_tail or not any(v[0] for v in struct.iter_unpack('<f', pcm)):
            raise RuntimeError('native held score did not render its overlap and tail')
    plan['events'] = [dict(event, id='pulse0', frame=0, type='note_on', context=1, context_open=True, context_close=False),
                      dict(event, id='pulse0', frame=512, type='note_off'),
                      dict(event, id='pulse1', frame=512, type='note_on', context=1, context_open=False, context_close=True),
                      dict(event, id='other', frame=512, type='note_on', context=2, context_open=True, context_close=True,
                           layers=[dict(pitch=64, velocity=47), dict(pitch=76, velocity=95)]),
                      dict(type='pitch', id='other', frame=768, semitones=1.5),
                      dict(event, id='pulse1', frame=1024, type='note_off'),
                      dict(event, id='other', frame=1536, type='note_off')]
    with LoadedModule(backing, 48000, 1, plan=plan) as player:
        pcm = player.render(48000, oversample=1, floats=True, max_seconds=Fraction(4096, 48000))
        if len(pcm) != 4096 * 8 or not player._in_tail or not any(v[0] for v in struct.iter_unpack('<f', pcm)):
            raise RuntimeError('native score contexts did not render simultaneous independent heads and tail')
    return '3 x 4096 stereo frames, tempo, grouped harmonic, held overlap, independent heads, gain/pitch/release and tail'


if __name__ == "__main__":
    # PyInstaller's spawn children must dispatch before the normal CLI starts.
    multiprocessing.freeze_support()
    if "--selfcheck" in sys.argv[1:]:
        sys.exit(selfcheck())
    from vulturetracker.__main__ import main
    sys.exit(main())
