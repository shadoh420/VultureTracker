"""Validate a built vulturetracker.exe (or the launcher under Python): start it headless on a demo song, wait for
/api/state and the page, stop it, then run its --selfcheck (every packed module and data file). Exit 1 on any failure.

  python tools/exe_check.py dist/vulturetracker.exe
  python tools/exe_check.py --cmd "python tools/exe_entry.py"      # the same checks on the source checkout
"""
import argparse
import json
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def headless(cmd, song, timeout):
    """Start `cmd gui song --no-browser --port N`, wait for /api/state, GET /, stop it. Returns the failures."""
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    log = ROOT / "build" / "exe_check.log"
    log.parent.mkdir(exist_ok=True)
    fails = []
    with open(log, "wb") as out:
        proc = subprocess.Popen(cmd + ["gui", str(song), "--no-browser", "--port", str(port)], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + timeout
            state = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    fails.append(f"the app exited early with code {proc.returncode} (see {log})")
                    break
                try:
                    status, body = get(base + "/api/state")
                    state = json.loads(body)
                    break
                except (OSError, ValueError):
                    time.sleep(0.5)
            if state is None and not fails:
                fails.append(f"/api/state did not answer within {timeout} s (see {log})")
            if state is not None:
                song_state = state.get("song") or {}
                print(f"ok /api/state on port {port}: {song_state.get('path', '?')} ({song_state.get('facts', {}).get('title', '?')})")
                try:
                    status, page = get(base + "/")
                    if status != 200 or b"<html" not in page.lower():
                        fails.append(f"GET / returned {status}, {len(page)} bytes without <html")
                    else:
                        print(f"ok GET / {len(page)} bytes")
                except OSError as e:
                    fails.append(f"GET / failed: {e}")
        finally:
            if proc.poll() is None:  # a onefile exe runs Python as a child: kill the tree, not just the bootloader
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                proc.kill()
                proc.wait(timeout=30)
    return fails


def main(argv=None):
    sys.stdout.reconfigure(errors="replace")  # selfcheck lines may carry non-ASCII paths; a cp1252 console must not stop it
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exe", nargs="?", help="the exe to check (default dist/vulturetracker.exe)")
    ap.add_argument("--cmd", help="a command instead of an exe, e.g. \"python tools/exe_entry.py\"")
    ap.add_argument("--song", default="demo2/iron_relay.yaml", help="the song to open headless (default demo2/iron_relay.yaml)")
    ap.add_argument("--timeout", type=float, default=60, help="seconds to wait for /api/state (default 60)")
    a = ap.parse_args(argv)
    if a.cmd:
        cmd = shlex.split(a.cmd, posix=sys.platform != "win32")  # POSIX mode would eat Windows backslashes
    else:
        exe = Path(a.exe or ROOT / "dist" / "vulturetracker.exe").resolve()
        if not exe.exists():
            ap.error(f"no such exe: {exe}")
        cmd = [str(exe)]
        print(("ok" if (exe.parent / "ffmpeg.exe").exists() else "FAIL") + f" ffmpeg.exe beside {exe.name}")
    song = (ROOT / a.song).resolve()
    if not song.exists():
        ap.error(f"no such song: {song}")
    fails = headless(cmd, song, a.timeout)
    r = subprocess.run(cmd + ["--selfcheck"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or "").rstrip() or "(no selfcheck output)")
    if r.returncode != 0:
        fails.append(f"--selfcheck exited {r.returncode}" + (f": {r.stderr.strip().splitlines()[-1]}" if r.stderr.strip() else ""))
    if not a.cmd and not (Path(cmd[0]).parent / "ffmpeg.exe").exists():
        fails.append("ffmpeg.exe is not beside the exe (the MP3/OGG/FLAC export needs it)")
    for f in fails:
        print("FAIL " + f)
    print("exe check:", "FAILED" if fails else "passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
