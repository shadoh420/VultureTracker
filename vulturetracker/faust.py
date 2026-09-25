"""Faust (GRAME's DSP language) as a sound source. The faustwasm package (the Faust compiler as WebAssembly with the Faust
libraries in its .data file; LGPL-3.0) is fetched on demand from npm into tools/faustwasm (the exe:
%LOCALAPPDATA%/VultureTracker/tools/faustwasm), like the synths, and never shipped. web/faust-render.mjs compiles and
renders one note offline: under node for sample recipes (`faust:`, SAMPLING.md), in the page for the FAUST tab."""
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import numpy as np

VERSION = "0.18.5"
URL = f"https://registry.npmjs.org/@grame/faustwasm/-/faustwasm-{VERSION}.tgz"
KEEP = ("package/package.json", "package/COPYING.txt", "package/README.md", "package/dist/esm/index.js",
        "package/libfaust-wasm/libfaust-wasm.js", "package/libfaust-wasm/libfaust-wasm.wasm",
        "package/libfaust-wasm/libfaust-wasm.data")
RENDER_JS = Path(__file__).with_name("web") / "faust-render.mjs"


def faust_dir():
    from .synth import TOOLS
    return Path(os.environ.get("FAUSTWASM_DIR") or TOOLS / "faustwasm")


def have():
    d = faust_dir()
    return all((d / k[len("package/"):]).exists() for k in KEEP[3:])


def extract(tgz, dest):
    """The files faustwasm needs (KEEP) from its npm tarball into `dest` (whole or not at all: unpacked beside it first)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        with tarfile.open(tgz, "r:gz") as t:
            names = set(t.getnames())
            missing = [k for k in KEEP if k not in names]
            if missing:
                raise ValueError(f"the faustwasm package lacks {', '.join(missing)}")
            for k in KEEP:
                out = Path(tmp) / "faustwasm" / k[len("package/"):]
                out.parent.mkdir(parents=True, exist_ok=True)
                src = t.extractfile(k)
                with open(out, "wb") as f:
                    shutil.copyfileobj(src, f)
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(Path(tmp) / "faustwasm", dest)
    return dest


def fetch(progress=lambda done, total: None):
    """Download faustwasm from npm and keep what renders need (about 6 MB of the 25 MB package)."""
    import urllib.request
    d = faust_dir()
    d.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=d.parent) as tmp:
        tgz = Path(tmp) / "faustwasm.tgz"
        req = urllib.request.Request(URL, headers={"User-Agent": "vulturetracker"})
        with urllib.request.urlopen(req) as r, open(tgz, "wb") as f:
            total, done = int(r.headers.get("Content-Length") or 0), 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                progress(done, total)
        return extract(tgz, d)


class FaustMissing(ValueError):
    pass


def render(code, hz=261.6256, velocity=100, hold=1.0, tail=0.5, params=None, rate=44100):
    """Faust `code` compiled and one note rendered under node (web/faust-render.mjs). Returns (float32 channels x
    frames, the DSP's controls). FaustMissing without node or faustwasm; ValueError with the compiler's message."""
    node = shutil.which("node")
    if not node:
        raise FaustMissing("rendering Faust in a recipe needs node (https://nodejs.org); the app's FAUST tab renders in "
                           "the page without it")
    if not have():
        raise FaustMissing(f"faustwasm is not in {faust_dir()}: get it from the app's FAUST tab or run python -c "
                           "\"from vulturetracker import faust; faust.fetch()\"")
    job = {"code": code, "hz": hz, "velocity": velocity, "hold": hold, "tail": tail, "params": params or {}, "rate": rate}
    with tempfile.TemporaryDirectory() as tmp:
        jf, out = Path(tmp) / "job.json", Path(tmp) / "out.f32"
        jf.write_text(json.dumps(job), encoding="utf-8")
        r = subprocess.run([node, str(RENDER_JS), str(faust_dir()), str(jf), str(out)], capture_output=True, text=True,
                           timeout=300)
        try:
            meta = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
        except ValueError:
            meta = {"error": (r.stderr or r.stdout).strip()[-400:]}
        if meta.get("error") or r.returncode:
            raise ValueError(f"Faust: {meta.get('error') or r.stderr.strip()[-400:]}")
        x = np.fromfile(out, "<f4").reshape(-1, meta["channels"]).T
    return x, meta["controls"]
