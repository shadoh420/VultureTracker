"""Render a Dettato performance MIDI, or one of its tracks, with FluidSynth and a GM SoundFont."""
import argparse
import ctypes as c
import ctypes.util
from contextlib import ExitStack
import io
import math
import os
from pathlib import Path
import shutil
import wave


def fluid_library():
    override = os.environ.get("VT_FLUIDSYNTH")
    if override:
        return override
    if os.name == "nt":
        directories = []
        cli = shutil.which("fluidsynth")
        if cli:
            directories.append(Path(cli).parent)
        directories.append(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "tuxguitar")
        for directory in directories:
            for name in ("libfluidsynth-3.dll", "fluidsynth-3.dll"):
                if (directory / name).is_file():
                    return str(directory / name)
    library = ctypes.util.find_library("fluidsynth")
    if not library:
        raise ValueError("FluidSynth is needed for direct MIDI audition. Set VT_FLUIDSYNTH to its shared library.")
    return library


def performance(path, track):
    import mido
    data = path.read_bytes()
    mid = mido.MidiFile(file=io.BytesIO(data))
    length = mid.length
    if track is None:
        return data, length
    if not 0 <= track < len(mid.tracks):
        raise ValueError("Unknown MIDI track")
    # Keep the original tempo map, controllers, programs and all rests. Mute only the other tracks' notes.
    for index, events in enumerate(mid.tracks):
        if index == track:
            continue
        kept = mido.MidiTrack()
        delay = 0
        for event in events:
            delay += event.time
            if event.type not in ("note_on", "note_off", "polytouch"):
                kept.append(event.copy(time=delay))
                delay = 0
        mid.tracks[index] = kept
    output = io.BytesIO()
    mid.save(file=output)
    return output.getvalue(), length


def render(midi, source, output, track):
    from importlib.metadata import distribution
    import soundfile
    bank = Path(os.environ.get("VT_GM_SOUNDFONT") or
                distribution("pretty-midi").locate_file("pretty_midi/TimGM6mb.sf2"))
    if not bank.is_file():
        raise ValueError("Cannot find TimGM6mb.sf2. Set VT_GM_SOUNDFONT to a General MIDI SoundFont.")
    data, length = performance(midi, track)
    # The source may continue after the last MIDI note. Preserve that silence for synchronized A/B playback.
    rate = 44100
    remaining = math.ceil(rate * max(soundfile.info(str(source)).duration, length + 1.0))
    with ExitStack() as resources:
        library = fluid_library()
        if os.name == "nt" and Path(library).is_absolute():
            resources.enter_context(os.add_dll_directory(str(Path(library).parent)))
        fluid = c.CDLL(library)
        ptr, integer, string = c.c_void_p, c.c_int, c.c_char_p
        def bind(name, result, *args):
            function = getattr(fluid, name)
            function.restype, function.argtypes = result, args
            return function
        def allocate(name, *args):
            handle = bind("new_fluid_"+name, ptr, *([ptr]*len(args)))(*args)
            if not handle:
                raise ValueError("Could not create FluidSynth "+name)
            resources.callback(bind("delete_fluid_"+name, None, ptr), handle)
            return handle
        settings = allocate("settings")
        bind("fluid_settings_setnum", integer, ptr, string, c.c_double)(settings, b"synth.sample-rate", rate)
        bind("fluid_settings_setstr", integer, ptr, string, string)(settings, b"player.timing-source", b"sample")
        synth = allocate("synth", settings)
        if bind("fluid_synth_sfload", integer, ptr, string, integer)(synth, os.fsencode(bank), 1) < 0:
            raise ValueError(f"FluidSynth could not load {bank}")
        player = allocate("player", synth)
        if bind("fluid_player_add_mem", integer, ptr, string, c.c_size_t)(player, data, len(data)) != 0:
            raise ValueError("FluidSynth could not load the MIDI events")
        if bind("fluid_player_play", integer, ptr)(player) != 0:
            raise ValueError("FluidSynth could not start MIDI playback")
        write = bind("fluid_synth_write_s16", integer, ptr, integer, ptr, integer, integer, ptr, integer, integer)
        frames = (c.c_int16 * 8192)()
        with wave.open(str(output), "wb") as wav:
            wav.setparams((2, 2, rate, 0, "NONE", ""))
            while remaining:
                count = min(4096, remaining)
                if write(synth, count, frames, 0, 2, frames, 1, 2) != 0:
                    raise ValueError("FluidSynth could not render the audio")
                wav.writeframesraw(memoryview(frames).cast("B")[:count*4])
                remaining -= count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("midi", "source", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--track", type=int)
    args = parser.parse_args()
    render(args.midi, args.source, args.output, args.track)
