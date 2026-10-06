"""Transcribe recordings to multi-instrument MIDI files with YourMT3+ (YPTF.MoE+Multi, noPS: arxiv 2407.04822).

Runs in the torch environment that `tools/transcribe_audio.py --setup --yourmt3` makes, which also fetches the model
(the Hugging Face space mimbres/YourMT3 with its checkpoint) into <env>/yourmt3:

  <env>/torch/Scripts/python tools/yourmt3_transcribe.py OUT_DIR rec.wav [more.wav ...] [--model-dir DIR] [--device cuda]

Writes OUT_DIR/<name>_yourmt3.mid per file (a silent file is skipped). On an NVIDIA card it runs on the GPU in full
precision (a GTX 10-series has no fast half precision); on the CPU it works but is slow (about twice the recording's
length on a recent CPU)."""
import argparse
import os
import shutil
import sys
from pathlib import Path

CKPT = "mc13_256_g4_all_v7_mt3f_sqr_rms_moe_wf4_n8k2_silu_rope_rp_b36_nops@last.ckpt"
ARGS = [CKPT, "-p", "2024", "-tk", "mc13_full_plus_256", "-dec", "multi-t5", "-nl", "26", "-enc", "perceiver-tf", "-sqr", "1",
        "-ff", "moe", "-wf", "4", "-nmoe", "8", "-kmoe", "2", "-act", "silu", "-epe", "rope", "-rp", "1", "-ac", "spec",
        "-hop", "300", "-atc", "1", "-pr", "32"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out_dir", type=Path, help="where the MIDI files go")
    ap.add_argument("audio", type=Path, nargs="+", help="the recordings (WAV)")
    ap.add_argument("--model-dir", type=Path, default=Path(__file__).resolve().parent / "transcribe-env" / "yourmt3",
                    help="the YourMT3 space checkout with its checkpoint")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    args = ap.parse_args()
    for f in args.audio:
        if not f.is_file():
            ap.error(f"no such file: {f}")
    ckpt = args.model_dir / "amt" / "logs" / "2024" / CKPT.split("@")[0] / "checkpoints" / "last.ckpt"
    if not ckpt.is_file() or ckpt.stat().st_size < 1_000_000:
        ap.error(f"the checkpoint is missing: {ckpt} (tools/transcribe_audio.py --setup --yourmt3 fetches it)")
    try:
        import torch
        import torchaudio
    except ImportError:
        sys.exit("torch is missing: run this with the torch environment's python (tools/transcribe_audio.py --setup --yourmt3)")
    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    audio, out_dir = [f.resolve() for f in args.audio], args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(args.model_dir)  # the model's code finds its checkpoint and writes its output relative to here
    sys.path[:0] = [str(args.model_dir), str(args.model_dir / "amt" / "src")]
    from model_helper import load_model_checkpoint, transcribe
    print(f"YourMT3+ on {torch.cuda.get_device_name(0) if device == 'cuda' else 'the CPU'}", flush=True)
    model = load_model_checkpoint(args=ARGS, device="cpu").to(device)
    for f in audio:
        x, _ = torchaudio.load(str(f))
        if float(x.pow(2).mean().sqrt()) < 10 ** (-50 / 20):
            print(f"{f.name}: skipped, silent")
            continue
        made = Path(transcribe(model, {"filepath": str(f), "track_name": "vt_" + f.stem}))
        shutil.move(str(made), out_dir / f"{f.stem}_yourmt3.mid")
        print(f"wrote {out_dir / (f.stem + '_yourmt3.mid')}", flush=True)


if __name__ == "__main__":
    main()
