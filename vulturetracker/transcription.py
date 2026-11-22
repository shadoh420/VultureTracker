"""Prepare audio transcription takes outside the open song using the optional local runner."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading

from .fileio import atomic_write, user_dir


class TranscriptionReview:
    def __init__(self):
        self.sessions = {}
        self.status_file = None
        self.lock = threading.Lock()
        self.midi_lock = threading.Lock()

    def prepare(self, body):
        if not self.lock.acquire(blocking=False):
            raise ValueError("A transcription is already running.")
        try:
            return self._prepare(body)
        finally:
            status = self.status_file
            self.status_file = None
            if status:
                try:
                    status.unlink(missing_ok=True)
                except OSError:
                    pass
            self.lock.release()

    def stage(self):
        path = self.status_file
        if path:
            try:
                return path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        return ""

    def _prepare(self, body):
        kind = body.get("take", "mix")
        if kind not in ("mix", "drums", "stems"):
            raise ValueError("Choose full mix, separated drums or full stems.")
        runner, python, env = runtime()
        if kind == "mix":
            audio = Path(body.get("path", "")).resolve()
            if not audio.is_file():
                raise ValueError("Choose a recording first.")
            parent = audio.with_name(audio.stem + "-transcription")
            parent.mkdir(exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix="take-", dir=parent))
            session = secrets.token_hex(12)
            args = [str(audio)]
        else:
            session = body.get("session")
            work = self.sessions.get(session)
            if work is None:
                raise ValueError("Transcribe the full mix first.")
            args = ["--audition", kind]
        output = work / kind
        if not (output / "preview.wav").is_file():
            log = work / (kind + ".log")
            self.status_file = work / (kind + ".progress")
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run([str(python), str(runner), "--env", str(env), "--work", str(work), *args],
                    cwd=runner.parent.parent, stdout=stream, stderr=subprocess.STDOUT,
                    env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", VT_TRANSCRIPTION_STATUS=str(self.status_file)),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size - 1800))
                    reason = stream.read().decode("utf-8", errors="replace").strip()
                raise ValueError(f"Could not prepare this take. See {log}\n{reason}")
        self.sessions[session] = work
        return dict(session=session, take=kind, song=str(output / (kind + ".yaml")),
                    original=str(work / "mix" / "original.mid"))

    def preview(self, session, take):
        if session in self.sessions and take == "source":
            return self.sessions[session] / "mix" / "source.wav"
        if session in self.sessions and (take == "gm" or
                (take.startswith("gm-") and take[3:].isascii() and take[3:].isdigit() and len(take) <= 8)):
            return self.sessions[session] / "mix" / "gm" / (take + ".wav")
        if session in self.sessions and take in ("mix", "drums", "stems"):
            return self.sessions[session] / take / "preview.wav"

    def midi_audition(self, body):
        import mido
        session = body.get("session")
        if session not in self.sessions:
            raise ValueError("Transcribe a recording before auditioning its MIDI.")
        mix = self.sessions[session] / "mix"
        midi = mix / "original.mid"
        tracks = []
        for index, events in enumerate(mido.MidiFile(midi).tracks):
            if any(e.type == "note_on" and e.velocity for e in events):
                tracks.append(dict(id=index, name=events.name or f"Track {index + 1}"))
        solo = body.get("track")
        if solo is not None and (type(solo) is not int or solo not in [t["id"] for t in tracks]):
            raise ValueError("Choose an instrument from this MIDI.")
        key = "gm" if solo is None else f"gm-{solo}"
        output = self.preview(session, key)
        with self.midi_lock:
            if not output.is_file():
                runner, _, env = runtime()
                python = env / "torch" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                output.parent.mkdir(exist_ok=True)
                with tempfile.TemporaryDirectory(dir=output.parent) as temp:
                    wav = Path(temp) / output.name
                    cmd = [python, runner.with_name("render_gm.py"), midi, mix / "source.wav", wav]
                    if solo is not None:
                        cmd.extend(["--track", str(solo)])
                    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if result.returncode:
                        raise ValueError("MIDI audition failed: " + (result.stderr.strip() or result.stdout.strip())[-900:])
                    wav.replace(output)
        return dict(preview=key, tracks=tracks)


def register_runtime(runner, python, env):
    settings = user_dir(local=True) / "transcription.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    data = dict(runner=str(runner), python=str(python), env=str(env))
    atomic_write(settings, json.dumps(data).encode("utf-8"))


def runtime():
    repo = Path(__file__).resolve().parents[1]
    installed = user_dir(local=True) / "transcribe-env"
    env = Path(os.environ.get("VT_TRANSCRIBE_ENV") or (installed if installed.is_dir() else repo / "tools" / "transcribe-env"))
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    binary = "python.exe" if os.name == "nt" else "python"
    runner = repo / "tools" / "transcribe_audio.py"
    python = env / "vt" / bin_dir / binary
    registered = user_dir(local=True) / "transcription.json"
    if registered.is_file() and not os.environ.get("VT_TRANSCRIBE_ENV"):
        settings = json.loads(registered.read_text(encoding="utf-8"))
        runner, python, env = (Path(settings[key]) for key in ("runner", "python", "env"))
    elif not getattr(sys, "frozen", False) and not python.is_file():
        python = Path(sys.executable)
    if not (runner.is_file() and python.is_file() and (env / "torch" / bin_dir / binary).is_file()):
        raise ValueError("Run tools/transcribe_setup.cmd from the VultureTracker checkout to set up audio transcription.")
    return runner, python, env
