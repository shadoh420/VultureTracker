"""Build a standalone vulturetracker.exe (Windows) with PyInstaller: `pip install pyinstaller && python tools/build_exe.py`.

The exe is the whole CLI; `vulturetracker.exe gui song.yaml` opens the app in its own window (pywebview), or in the
default browser without it.
Bundled: the package, gui.html, the vendored libopenmpt DLLs, pedalboard + mido (the synth host, GPL-3: the exe is
therefore distributed under GPL-3, THIRD_PARTY.md) and sounddevice with its PortAudio DLLs (the RECORD tab, MIT).
Not bundled: Surge XT, Dexed, OB-Xd and the sample packs; the app's RECIPE box downloads Surge XT and Dexed into
%LOCALAPPDATA%/VultureTracker/tools when a recipe needs them.
ffmpeg (for the MP3/OGG/FLAC export) is copied beside the exe as dist/ffmpeg.exe from imageio-ffmpeg, not packed into it:
a packed file is unpacked to %TEMP% on every launch. Ship both files; its build is GPL-3 (THIRD_PARTY.md)."""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sep = ";" if sys.platform == "win32" else ":"
ICO = ROOT / "assets" / "vulturetracker.ico"
try:  # refresh the exe icon from the master PNG when Pillow is installed (build-time only)
    from PIL import Image
    Image.open(ROOT / "assets" / "vulturetracker.png").save(ICO, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
except ImportError:
    pass
cmd = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--name", "vulturetracker",
    "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
    "--add-data", f"{ROOT / 'vulturetracker' / 'gui.html'}{sep}vulturetracker",
    "--add-data", f"{ROOT / 'vulturetracker' / 'icon.png'}{sep}vulturetracker",
    "--add-data", f"{ROOT / 'SONG_FORMAT.md'}{sep}vulturetracker",  # the Pattern tab's effect help reads its tables
    "--add-data", f"{ROOT / 'vulturetracker' / 'web'}{sep}vulturetracker/web",  # the live engine (libopenmpt wasm, worklet)
    "--icon", str(ICO),
    "--collect-submodules", "vulturetracker",
    "--collect-all", "pedalboard", "--hidden-import", "mido",  # the synth host for the RECIPE box (GPL-3)
    # numpy is optional at runtime (measurements degrade without it); bundle it when present so the exe measures.
    "--hidden-import", "numpy",
    "--collect-all", "webview",  # pywebview: native app window (Edge WebView2 on Windows)
    str(ROOT / "tools" / "exe_entry.py"),  # absolute-import launcher; __main__.py uses relative imports
]
for dll in (ROOT / "vendor").glob("*.dll"):
    cmd += ["--add-binary", f"{dll}{sep}vendor"]
# the RECORD tab's audio input (sounddevice, MIT): on Windows its wheel carries PortAudio in _sounddevice_data, both the
# plain DLL and the ASIO one; without sounddevice installed the exe builds and the tab says what is missing
if importlib.util.find_spec("sounddevice"):
    cmd += ["--hidden-import", "sounddevice"]
    if importlib.util.find_spec("_sounddevice_data"):
        cmd += ["--collect-all", "_sounddevice_data"]
# Guitar Pro import (PyGuitarPro, LGPL-3.0, and attrs, MIT): packed when installed at build time, else the import says
# what is missing
if importlib.util.find_spec("guitarpro"):
    cmd += ["--collect-submodules", "guitarpro", "--hidden-import", "attr"]
print(" ".join(cmd))
code = subprocess.call(cmd, cwd=ROOT)
try:
    import shutil
    import imageio_ffmpeg
    shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(), ROOT / "dist" / "ffmpeg.exe")
    print("copied ffmpeg beside the exe: dist/ffmpeg.exe")
except (ImportError, RuntimeError, OSError) as e:
    print(f"no ffmpeg beside the exe ({e}): the exe exports MP3/OGG/FLAC only with ffmpeg on PATH")
sys.exit(code)
