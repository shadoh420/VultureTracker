"""Transcribe the full recording with Dettato. Keep its MIDI and render an editable VultureTracker take.

  python tools/transcribe_audio.py track.mp3 [--work NEW_FOLDER]
  python tools/transcribe_audio.py --work FOLDER --audition drums
  python tools/transcribe_audio.py --work FOLDER --audition stems

The optional takes each have their own MIDI, song and preview. The older stem-first pipeline is available with --notes:

  python tools/transcribe_audio.py --setup [--cuda] [--yourmt3]   # once: the environments (needs uv; 3 to 6 GB)
  python tools/transcribe_audio.py track.mp3 [--work DIR] [--separator htdemucs_ft|htdemucs_6s|roformer]
                                   [--stems DIR] [--notes basic-pitch yourmt3] [--bass notes|yin] [--drums adtof|bands]

Steps: the recording decoded to a WAV; stems by demucs (htdemucs_ft: bass, drums, other, vocals; htdemucs_6s adds guitar
and piano) or the BS-RoFormer SW model (audio-separator; `--setup --separator roformer` adds its environment), unless
--stems names a folder of <stem>.wav already made; the pitched stems' notes by basic-pitch and/or YourMT3+ (--notes; each
makes its own song, to compare by ear); the drums through ADTOF on the recording (or --drums bands: three band onset
detectors on the drum stem); tools/stems_to_midi.py merges them (--bass yin: the bass as one line by VultureTracker's
YIN); `vulturetracker import` and `build --render` make the song and its WAV; tools/transcription_diff.py scores it and
draws <name>-<notes>-diff.png; <name>-<notes>.mp3 is the song, lined up with the recording, to listen to. Everything
lands in --work (default: <recording>-transcription beside it). tools/stems_to_song.py then plays a version on samples
cut from the stems themselves.

On the CPU a 3-minute track takes demucs about 4 min, RoFormer about 25, YourMT3+ about 7 per stem; `--setup --cuda`
installs PyTorch for NVIDIA cards (CUDA 12.4: a GTX 10-series and newer, driver 551.61 or later) and then all of them
run on the card. The scores are lenient proxies for ranking versions, not accuracy; the ear decides
(transcription_diff.py says how they are counted).

The environments live in --env (default tools/transcribe-env, ignored by git): `torch` (PyTorch 2.5.1, demucs, ADTOF,
YourMT3+'s code), `bp` (basic-pitch with ONNX, librosa, matplotlib), `sep` (audio-separator), `yourmt3` (the model) and
`bin/ffmpeg`. tools/transcribe_setup.cmd and transcribe.cmd do all of it on a Windows PC with nothing installed."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
sys.path.insert(0, str(REPO))
from tools.dettato_takes import report_stage
WIN = os.name == "nt"
ADTOF = "adtof-pytorch @ https://github.com/xavriley/ADTOF-pytorch/archive/85c192e78f716ea0b111cc8a5ee4a8f6a3a4f8a9.zip"
DETTATO = "dettato @ https://github.com/kobimusic/dettato/archive/51ade0f09f2272f4674166026582185d26baaeaf.zip"
YOURMT3 = ("mimbres/YourMT3", "5e66c1ea173a8186e0d20432b841d3180cc015b5")  # the Hugging Face space and its revision
YOURMT3_FILES = ["*.py", "amt/src/**", "amt/logs/2024/mc13_256_g4_all_v7_mt3f_sqr_rms_moe_wf4_n8k2_silu_rope_rp_b36_nops/**"]
YOURMT3_DEPS = ["pytorch-lightning>=2.2.1", "transformers==4.45.1", "einops", "mido", "mir_eval", "deprecated", "wandb", "python-dotenv"]
PITCHED = ["bass", "other", "guitar", "vocals", "piano"]


def torch_pkgs(cuda):
    return ["torch==2.5.1", "torchaudio==2.5.1", "--index-url", f"https://download.pytorch.org/whl/{'cu124' if cuda else 'cpu'}"]


def exe(env, name, tool=None):
    """A program in an environment: its python, or another of its Scripts/bin entries."""
    folder = env / name / ("Scripts" if WIN else "bin")
    return folder / ((tool or "python") + (".exe" if WIN else ""))


def run(cmd, **kw):
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode:
        sys.exit(f"failed ({r.returncode}): {cmd[0]}")
    return r


def setup(env, args):
    uv = shutil.which("uv")
    if not uv:
        sys.exit("--setup needs uv (https://docs.astral.sh/uv/: pip install uv)")
    envs = {  # name: the installs, in order (a list per uv call)
        "torch": [torch_pkgs(args.cuda), [DETTATO, "demucs==4.1.0", "soundfile", "numpy<2"]
                  + (["librosa", "pretty_midi", ADTOF] if args.legacy or args.yourmt3 else [])
                  + (YOURMT3_DEPS if args.yourmt3 else [])],
        "bp": [["basic-pitch[onnx]==0.4.0", "setuptools<81", "matplotlib", "soundfile",  # resampy imports pkg_resources
                "pyyaml",  # stems_to_song.py imports vulturetracker
                "pyguitarpro"]],  # make_notes.py writes Guitar Pro
        "sep": [torch_pkgs(args.cuda), ["audio-separator[gpu]==0.47.0" if args.cuda else "audio-separator[cpu]==0.47.0"]],
    }
    for name in ["torch"] + (["bp"] if args.legacy or args.yourmt3 else []) + (["sep"] if args.separator == "roformer" else []):
        py = exe(env, name)
        if not py.exists():
            run([uv, "venv", "-q", "-p", "3.11", env / name])
        for pkgs in envs[name]:
            run([uv, "pip", "install", "-q", "-p", py, *pkgs])
    if args.yourmt3:  # the model's code and checkpoint (560 MB) from its Hugging Face space, no git needed
        run([exe(env, "torch"), "-c", "import sys; from huggingface_hub import snapshot_download as d; "
             "d(sys.argv[1], repo_type='space', revision=sys.argv[2], local_dir=sys.argv[3], allow_patterns=sys.argv[4:])",
             *YOURMT3, env / "yourmt3", *YOURMT3_FILES])
    ff = env / "bin" / ("ffmpeg.exe" if WIN else "ffmpeg")  # audio-separator calls `ffmpeg` by name
    if not ff.exists():
        ff.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ffmpeg(), ff)
    if args.cuda:
        run([exe(env, "torch"), "-c", "import torch; ok = torch.cuda.is_available(); "
             "print('GPU:', torch.cuda.get_device_name(0) if ok else 'none found: the models will run on the CPU')"])
    print(f"environments ready in {env}")
    from vulturetracker.transcription import register_runtime
    register_runtime(Path(__file__).resolve(), Path(sys.executable), env)


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        found = shutil.which("ffmpeg")
        if not found:
            sys.exit("ffmpeg is needed: pip install imageio-ffmpeg, or ffmpeg on PATH")
        return found


def separate(args, env, wav, work, child):
    """The stems as <work>/stems/<model>/<stem>.wav."""
    out = work / "stems" / args.separator
    if args.separator == "roformer":
        raw = work / "stems" / "roformer-raw"
        run([exe(env, "sep", "audio-separator"), wav, "-m", "BS-Roformer-SW.ckpt", "--output_dir", raw,
             "--model_file_dir", env / "models"], env=child)
        out.mkdir(parents=True, exist_ok=True)
        for f in raw.glob("*.flac"):  # <name>_(<stem>)_BS-Roformer-SW.flac
            stem = f.name.split("(")[-1].split(")")[0].lower()
            run([ffmpeg(), "-y", "-loglevel", "error", "-i", f, "-c:a", "pcm_s16le", out / f"{stem}.wav"])
    else:
        run([exe(env, "torch"), "-m", "demucs", "-n", args.separator, "-o", work / "stems", wav], env=child)
        made = work / "stems" / args.separator / wav.stem
        out.mkdir(parents=True, exist_ok=True)
        for f in made.glob("*.wav"):
            os.replace(f, out / f.name)
        made.rmdir()
    return out


def dettato_take(args, env, work, child):
    kind = args.audition or "mix"
    original = work / "mix" / "original.mid"
    source = work / "mix" / "source.wav"
    if kind == "mix":
        folder = work / kind
        try:
            folder.mkdir()  # exclusive: preserve prior MIDI, edits and renders on reruns
        except FileExistsError:
            sys.exit(f"A full-mix take already exists in {work}. Choose a new --work folder.")
        report_stage("Decoding the recording")
        run([ffmpeg(), "-n", "-loglevel", "error", "-i", args.audio, "-map", "0:a:0",
             "-c:a", "pcm_f32le", source])  # retain the source rate for Dettato's drum detector
        run([exe(env, "torch"), TOOLS / "dettato_takes.py", kind, folder, source], env=child)
        render_take(original, folder)
        print(f"Original MIDI: {original}")
    else:
        folder = work / kind
        if not (original.is_file() and source.is_file()):
            sys.exit("Choose the --work folder of a completed full-mix transcription.")
        if folder.exists():
            sys.exit(f"Take already exists: {folder}. Its MIDI and any edits were kept.")
        with tempfile.TemporaryDirectory(dir=work) as staging:
            stage = Path(staging)
            stems = args.stems or work / (args.separator + "-stems")
            if not stems.is_dir():
                report_stage("Separating instruments from the recording")
                separate(args, env, source, stage, child).rename(stems)
            names = ["drums"] if kind == "drums" else ["drums", *PITCHED]
            inputs = [stems / (s + ".wav") for s in names if (stems / (s + ".wav")).is_file()]
            if not inputs or inputs[0].stem != "drums" or (kind == "stems" and len(inputs) < 2):
                sys.exit("Need drums.wav, and for a full stem take at least one pitched stem.")
            candidate = stage / kind
            candidate.mkdir()
            run([exe(env, "torch"), TOOLS / "dettato_takes.py", kind, candidate, *inputs,
                 "--original", original], env=child)
            render_take(candidate / "take.mid", candidate)
            candidate.rename(folder)
    print(f"Song: {folder / (kind + '.yaml')}\nPreview: {folder / 'preview.wav'}")


def render_take(mid, folder):
    from vulturetracker import api
    from vulturetracker.midiimport import import_midi

    song = folder / (folder.name + ".yaml")
    report_stage("Importing MIDI notes into the tracker")
    _, warnings = import_midi(mid, song, folder / (folder.name + "_samples"))
    for message in warnings:
        print("MIDI import:", message)
    report_stage("Rendering the tracker preview")
    api.render(song, folder / "preview.wav")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("audio", nargs="?", type=Path, help="the recording: WAV, MP3, FLAC, OGG ... (anything ffmpeg reads)")
    ap.add_argument("--setup", action="store_true", help="make the environments (with --separator roformer: that one too)")
    ap.add_argument("--cuda", action="store_true", help="with --setup: PyTorch for NVIDIA cards (CUDA 12.4)")
    ap.add_argument("--yourmt3", action="store_true", help="with --setup: YourMT3+'s code and model")
    ap.add_argument("--legacy", action="store_true", help="with --setup: also install Basic Pitch and ADTOF")
    ap.add_argument("--audition", choices=["drums", "stems"], help="make an alternate in an existing full-mix --work folder")
    ap.add_argument("--env", type=Path, default=TOOLS / "transcribe-env", help="where the environments live")
    ap.add_argument("--work", type=Path, help="the folder for everything made (default: <recording>-transcription)")
    ap.add_argument("--separator", choices=["htdemucs_ft", "htdemucs_6s", "roformer"], default="htdemucs_ft")
    ap.add_argument("--stems", type=Path, help="a folder of <stem>.wav already made: separation is skipped")
    ap.add_argument("--notes", choices=["dettato", "basic-pitch", "yourmt3"], nargs="+",
                    help="default: Dettato on the full mix; choose Basic Pitch or YourMT3+ for the legacy pipeline")
    ap.add_argument("--bass", choices=["notes", "yin"], help="legacy pipeline: the bass from --notes, or one line by YIN")
    ap.add_argument("--drums", choices=["adtof", "bands"], help="legacy pipeline: drum method")
    args = ap.parse_args()
    if args.notes is None:
        args.notes = ["basic-pitch"] if args.bass or args.drums or (args.stems and not args.audition) else ["dettato"]
    if "dettato" in args.notes and (args.bass or args.drums or (args.stems and not args.audition)):
        ap.error("Dettato uses the full mix. To use separated audio, choose --audition drums or stems.")
    args.bass = args.bass or "notes"
    args.drums = args.drums or "adtof"
    env = args.env.resolve()
    if args.setup:
        setup(env, args)
        if not args.audio:
            return
    if args.audition and (args.audio or not args.work or args.notes != ["dettato"]):
        ap.error("--audition needs --work from a full-mix run, with no new recording or other note method")
    if not args.audio and not args.audition:
        ap.error("name the recording (or --setup)")
    if args.audio and not args.audio.is_file():
        ap.error(f"no such file: {args.audio}")
    if args.stems and not args.stems.is_dir():
        ap.error(f"no such folder: {args.stems}")
    if "dettato" in args.notes and args.notes != ["dettato"]:
        ap.error("run Dettato separately from the legacy note methods")
    if args.notes == ["dettato"]:
        need = ["torch"]
    else:
        need = ["bp"]
        if args.drums == "adtof" or not args.stems or "yourmt3" in args.notes:
            need.append("torch")
    if args.separator == "roformer" and not args.stems and (args.audition or args.notes != ["dettato"]):
        need.append("sep")
    missing = [n for n in need if not exe(env, n).exists()]
    if "yourmt3" in args.notes and not (env / "yourmt3" / "model_helper.py").exists():
        missing.append("yourmt3")
    if missing:
        ap.error(f"{', '.join(missing)} missing in {env}: run with --setup" + (" --legacy" if "bp" in missing else "")
                 + (" --separator roformer" if "sep" in missing else "") + (" --yourmt3" if "yourmt3" in missing else ""))

    work = (args.work or args.audio.with_name(args.audio.stem + "-transcription")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    child = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PATH=str(env / "bin") + os.pathsep + os.environ["PATH"])
    if args.notes == ["dettato"]:
        offline_weights = env / "dettato-weights"
        if offline_weights.is_dir():
            child.setdefault("DETTATO_WEIGHTS", str(offline_weights))
        if not args.work and (work / "mix").exists():
            work = Path(tempfile.mkdtemp(prefix="take-", dir=work))
        dettato_take(args, env, work, child)
        return
    name = args.audio.stem
    wav = work / f"{name}.wav"
    if not wav.exists():
        run([ffmpeg(), "-y", "-loglevel", "error", "-i", args.audio, "-map", "0:a:0", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", wav])

    print("1. stems", flush=True)
    stems = args.stems.resolve() if args.stems else separate(args, env, wav, work, child)
    print("2. notes", flush=True)
    midi_dir = work / "midi"
    midi_dir.mkdir(exist_ok=True)
    pitched = [stems / f"{s}.wav" for s in PITCHED if (stems / f"{s}.wav").is_file()]
    for f in pitched:
        (midi_dir / f"{f.stem}_basic_pitch.mid").unlink(missing_ok=True)  # basic-pitch will not write over its output
    run([exe(env, "bp", "basic-pitch"), midi_dir, *pitched], env=child, stdout=subprocess.DEVNULL)  # also the fallback
    if "yourmt3" in args.notes:
        run([exe(env, "torch"), TOOLS / "yourmt3_transcribe.py", midi_dir, *pitched, "--model-dir", env / "yourmt3"], env=child)
    drums = []
    if args.drums == "adtof":
        dm = midi_dir / "drums_adtof.mid"
        run([exe(env, "torch"), "-c", "import sys, torch; from adtof_pytorch import transcribe_to_midi as t; "
             "t(sys.argv[1], sys.argv[2], device='cuda' if torch.cuda.is_available() else 'cpu')", wav, dm], env=child)
        drums = ["--drums-midi", dm]
    made = []
    for notes in args.notes:
        print(f"3. merge, import, render ({notes})", flush=True)
        v = f"{name}-{notes}"
        mid = work / f"{v}.mid"
        run([exe(env, "bp"), TOOLS / "stems_to_midi.py", "--stems", stems, "--midi-dir", midi_dir, "--notes", notes,
             "--bass", args.bass, *drums, "--out", mid], env=child)
        offset = json.loads(mid.with_suffix(".json").read_text(encoding="utf-8"))["offset_ms"]
        song, render = work / f"{v}.yaml", work / f"{v}-song.wav"
        run([sys.executable, "-m", "vulturetracker", "import", mid, "-o", song], cwd=REPO)
        run([sys.executable, "-m", "vulturetracker", "build", song, "--render", render], cwd=REPO, stdout=subprocess.DEVNULL)
        print(f"4. diff ({notes})", flush=True)
        run([exe(env, "bp"), TOOLS / "transcription_diff.py", "--orig", wav, "--render", render, "--midi", mid, "--stems", stems,
             "--offset-ms", offset, "--png", work / f"{v}-diff.png", "--label", f"{args.stems.name if args.stems else args.separator}, notes {notes}, bass {args.bass}, drums {args.drums}"],
            env=child)
        mp3 = work / f"{v}.mp3"  # the song, starting where the recording does
        run([ffmpeg(), "-y", "-loglevel", "error", "-i", render, "-af",
             f"atrim=start={offset / 1000},asetpts=PTS-STARTPTS" if offset >= 0 else f"adelay={-offset}|{-offset}", "-b:a", "320k", mp3])
        made.append((notes, song, mp3, offset))
    print()
    for notes, song, mp3, offset in made:
        print(f"{notes}:\n  song:    {song}\n  listen:  {mp3} (lined up with the recording)\n"
              f"  diff:    {song.with_name(song.stem + '-diff.png')}\n  offset:  the song starts {offset} ms after the recording "
              "(the SPECTRUM tab's REFERENCE OFFSET)")


if __name__ == "__main__":
    main()
