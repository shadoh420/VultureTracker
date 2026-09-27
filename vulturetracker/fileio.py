"""Small shared file-safety helpers for song writes and exports."""
import io
import os
from pathlib import Path
import shutil
import tempfile
import time
import wave


def atomic_write(path, data, *, replace=True):
    """Flush a sibling temporary file, then publish it; replace=False requires an unused path."""
    path = Path(path)
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
        raise
    except OSError:
        with open(src, 'rb') as s, open(dst, 'xb') as d:
            shutil.copyfileobj(s, d)


def protect_outputs(outputs, sources):
    """Reject paths (including symlinks and hardlinks) that alias an input or each other."""
    seen = [Path(p) for p in sources]
    for path in map(Path, outputs):
        for src in seen:
            same = os.path.normcase(path.resolve()) == os.path.normcase(src.resolve())
            if same or (path.exists() and src.exists() and os.path.samefile(path, src)):
                raise ValueError(f'{path} is a source asset or duplicate output: exporting would overwrite it')
        seen.append(path)


def wav_bytes(pcm, rate=44100):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()
