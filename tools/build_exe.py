"""Build a standalone vulturetracker.exe (Windows) with PyInstaller: `pip install pyinstaller && python tools/build_exe.py`.

The exe is the whole CLI; `vulturetracker.exe gui song.yaml` opens the tryout app in the default browser.
Bundled: the package, gui.html and the vendored libopenmpt DLLs. Not bundled: Surge XT, Dexed, OB-Xd and the
sample packs (the `synth`/`audition` verbs still need `tools/` next to a checkout, as SAMPLING.md describes)."""
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
    "--icon", str(ICO),
    "--collect-submodules", "vulturetracker",
    # synth/audition need the plugins from tools/ anyway; keep pedalboard (GPL-3) and mido out of the exe
    "--exclude-module", "pedalboard", "--exclude-module", "mido",
    # numpy is optional at runtime (measurements degrade without it); bundle it when present so the exe measures.
    "--hidden-import", "numpy",
    "--collect-all", "webview",  # pywebview: native app window (Edge WebView2 on Windows)
    str(ROOT / "tools" / "exe_entry.py"),  # absolute-import launcher; __main__.py uses relative imports
]
for dll in (ROOT / "vendor").glob("*.dll"):
    cmd += ["--add-binary", f"{dll}{sep}vendor"]
print(" ".join(cmd))
sys.exit(subprocess.call(cmd, cwd=ROOT))
