"""Run inside the optional transcription environment, where Dettato and pretty_midi live."""
import argparse
import os
from pathlib import Path


def report_stage(message):
    print(message, flush=True)
    status = os.environ.get("VT_TRANSCRIPTION_STATUS")
    if status:
        try:
            Path(status).write_text(message, encoding="utf-8")
        except OSError:
            pass  # progress display is optional


def replace_drums(original, drums, output):
    """Dettato writes one constant-tempo MIDI with a dedicated channel-10 track per drum kit."""
    import mido

    take = mido.MidiFile(original)
    alternate = mido.MidiFile(drums)
    def clock(mid):
        return mid.ticks_per_beat, [(m.time, m.tempo) for m in mid.tracks[0] if m.type == "set_tempo"]
    if clock(take) != clock(alternate):
        raise ValueError("The drum stem and full mix use different MIDI clocks.")
    def drum_track(track):
        return any(m.type == "note_on" and m.channel == 9 and m.velocity for m in track)
    tracks = [t for t in alternate.tracks if drum_track(t)]
    if not tracks:
        raise ValueError("Dettato found no hits in the drum stem.")
    take.tracks = [t for t in take.tracks if not drum_track(t)] + tracks
    take.save(output)


def combine_stems(parts):
    import pretty_midi

    take = pretty_midi.PrettyMIDI()
    programs = {"bass": 33, "vocals": 52, "guitar": 29, "piano": 0}
    for stem, path in parts.items():
        for track in pretty_midi.PrettyMIDI(str(path)).instruments:
            if not track.notes or track.is_drum != (stem == "drums"):
                continue
            if stem in programs:
                track.name, track.program = stem, programs[stem]
            elif stem != "drums":
                track.name = stem + " / " + track.name
            take.instruments.append(track)
    return take


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["mix", "drums", "stems"])
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--original", type=Path)
    args = parser.parse_args()
    try:
        from dettato.pipeline import Dettato
    except ModuleNotFoundError as exc:
        raise SystemExit(f"Missing transcription dependency {exc.name}. Run tools/transcribe_setup.cmd or --setup.") from exc
    report_stage("Loading Dettato models")
    model = Dettato.from_pretrained()
    if args.kind == "mix":
        report_stage("Finding notes, instruments and drums in the full mix")
        model.transcribe(str(args.inputs[0])).save_midi(str(args.output / "original.mid"))
        return
    parts = {}
    for index, wav in enumerate(args.inputs, 1):
        report_stage(f"Transcribing {wav.stem} ({index} of {len(args.inputs)} stems)")
        path = args.output / (wav.stem + ".mid")
        model.transcribe(str(wav)).save_midi(str(path))
        parts[wav.stem] = path
    output = args.output / "take.mid"
    if args.kind == "drums":
        replace_drums(args.original, parts["drums"], output)
    else:
        combine_stems(parts).write(str(output))


if __name__ == "__main__":
    main()
