"""Small shared file-safety helpers for song writes and exports."""
import io
import itertools
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import wave


def user_dir(local=False):
    """VultureTracker's folder for this user, where each platform keeps an application's: the recent list, the library
    index, the window's browser profile and the log; `local`: the downloaded synths and faustwasm. Windows %APPDATA%
    (%LOCALAPPDATA%), macOS ~/Library/Application Support, elsewhere $XDG_CONFIG_HOME (~/.config) and $XDG_DATA_HOME
    (~/.local/share)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA" if local else "APPDATA")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME" if local else "XDG_CONFIG_HOME") or Path.home() / (".local/share" if local else ".config")
    return Path(base or Path.home()) / "VultureTracker"


def save_beside(folder, stem, suffix, data):
    """`data` saved in `folder` as <stem><suffix>, numbered (-2, -3, ...) so no other file is replaced; an identical file
    already there is reused. Returns (its path, whether it was written now)."""
    stem = re.sub(r"[^\w.-]+", "_", stem)[:60] or "dropped"
    stem = "_" + stem if device_name(stem) else stem  # CON.wav, NUL.wav: Windows devices, not files
    for k in itertools.count(1):
        p = folder / f"{stem}{'' if k == 1 else f'-{k}'}{suffix}"
        if p.exists() and p.read_bytes() == data:
            return p, False
        if not p.exists():
            atomic_write(p, data, replace=False)
            return p, True


def atomic_write(path, data, *, replace=True):
    """Flush a sibling temporary file, then publish it; replace=False requires an unused path."""
    path = Path(path)
    if path.is_dir():  # checked first: the errors would name the temporary file
        raise IsADirectoryError(f'{path} is a folder: name a file to write')
    if not path.parent.is_dir():
        raise FileNotFoundError(f'{path.parent} does not exist: no folder to write {path.name} in')
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if not replace:
            link_new(tmp, path)
            return
        for wait in (0.05, 0.1, 0.2, 0.4, None):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if wait is None:
                    raise
                time.sleep(wait)
    finally:
        tmp.unlink(missing_ok=True)


def link_new(src, dst):
    """`src` published at `dst` without replacing anything there: a hard link, or an exclusive copy where the filesystem
    has no hard links (FAT32, exFAT: USB sticks)."""
    try:
        os.link(src, dst)
    except FileExistsError:
        raise FileExistsError(f'{dst} exists already') from None
    except OSError:
        with open(src, 'rb') as s, open(dst, 'xb') as d:
            shutil.copyfileobj(s, d)


DEVICES = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


def device_name(name):
    """A Windows device name (CON, NUL, COM1, ... in any case, with any extension): Windows opens the device, not a
    file, so an export called CON waits on the console and one called NUL vanishes."""
    return str(name).split('.')[0].strip().upper() in DEVICES


def lock_file(path):
    """`path` opened and locked for this process, or None when another process (or another handle here) holds it.
    The system lets go when the process ends, so a crash leaves no stale lock. unlock_file gives it back."""
    f = open(path, 'a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def unlock_file(f):
    if os.name == 'nt':
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    f.close()


def protect_outputs(outputs, sources):
    """Reject paths (including symlinks and hardlinks) that alias an input or each other."""
    seen = [Path(p) for p in sources]
    for path in map(Path, outputs):
        for src in seen:
            same = os.path.normcase(path.resolve()) == os.path.normcase(src.resolve())
            if same or (path.exists() and src.exists() and os.path.samefile(path, src)):
                raise ValueError(f'{path} is a source asset or duplicate output: exporting would overwrite it')
        seen.append(path)


def wav_bytes(pcm, rate=44100, loop=None):
    """Interleaved int16 stereo PCM as a WAV; `loop` = (start, end_exclusive) frames, stored in a 'smpl' chunk."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    if loop is None:
        return buf.getvalue()
    from .wavload import add_smpl
    return add_smpl(buf.getvalue(), rate, (loop[0], loop[1], False))
