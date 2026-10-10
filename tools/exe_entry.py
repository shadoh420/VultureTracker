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
    check("web", lambda: f"{len(list((pkg / 'web').glob('*.*')))} files" if (pkg / "web" / "libopenmpt.wasm").exists() else _missing(pkg / "web"))
    check("libopenmpt", lambda: importlib.import_module("vulturetracker.openmpt").library_version())
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


if __name__ == "__main__":
    # PyInstaller's spawn children must dispatch before the normal CLI starts.
    multiprocessing.freeze_support()
    if "--selfcheck" in sys.argv[1:]:
        sys.exit(selfcheck())
    from vulturetracker.__main__ import main
    sys.exit(main())
