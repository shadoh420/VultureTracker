# VultureTracker

<img src="assets/vulturetracker.png" width="88" align="right" alt="">

Tracker music as text, with a tracker built on it. A song is a readable YAML file that compiles to an Impulse Tracker
module (`.it`), checked by libopenmpt and playable in OpenMPT or Schism Tracker. The app edits that same file in place;
every change compiles before it is written and can be undone, so people, scripts and AI agents edit songs the same way.

```
song.yaml ──build──▶ song.it ──render──▶ .wav / .mp3 / .ogg / .flac / .mid
```

<p align="center"><img src="assets/screenshot-pattern.png" width="900" alt="Pattern tab: the pattern editor with coloured channels, two automation lanes drawn dimmed, and the selection and composition tools"></p>
<p align="center"><img src="assets/screenshot-tryout.png" width="900" alt="Tryout tab: candidate sounds rendered inside the song and measured against the current sample"></p>
<p align="center"><img src="assets/screenshot-spectrum.png" width="900" alt="Spectrum tab: the song's spectrogram with each order's short-term loudness and stereo correlation underneath"></p>

## What it does

- **A tracker on a text file:** patterns, instruments and the order list with OpenMPT's keys and behaviour, MIDI input,
  and a live engine that plays every edit. Automation lanes, microtuning (Scala `.scl`/`.kbm`), arpeggios, strums,
  grooves and OpenMPT's interpolate, grow and shrink.
- **Choosing sounds in context:** the Tryout renders candidate samples inside the song and measures them; a mixer,
  listening notes, and a sample library mapped by timbre.
- **Making sounds:** a sample editor with effects and slicing, recording from an audio interface, Faust, painted
  spectra, and recipes rendered from free synths or built-in sources (chip waves, sfxr, DrumSynth, PADsynth)
  ([SAMPLING.md](SAMPLING.md)).
- **Measuring, not guessing:** loudness (LUFS, true peak, LRA) per order, a spectrogram against a reference recording,
  and checks that warn before a sample aliases.
- **In and out:** imports IT, XM, S3M, MOD, Guitar Pro 3-5, MIDI, SoundFont 2 and GUS patches and common audio formats
  (and Hydrogen drum kits as sample sources); exports WAV (up to 96 kHz, 24-bit or float), MP3, OGG, FLAC, MIDI, stems
  and game loops, with optional loudness normalising.
- **Agents:** an AGENT panel and an MCP server give an AI the same tools as the page, with the owner's approved
  material protected.
- **Files that stay right:** undo history and checkpoints kept with the song, and every song from 0.6 on opening
  unchanged in every 1.x ([SONG_FORMAT.md](SONG_FORMAT.md)).

## Install

**Windows:** download `vulturetracker-win64.zip` from the [latest release](https://github.com/shadoh420/VultureTracker/releases/latest),
unzip it and run `vulturetracker.exe`.

**From source** (Python 3.10+; tested on Windows and Linux; outside Windows install libopenmpt, e.g.
`apt install libopenmpt0t64`):

```
git clone https://github.com/shadoh420/VultureTracker.git
cd VultureTracker
pip install -e ".[all]"
python -m vulturetracker gui demo2/iron_relay.yaml
```

## Use

```
python -m vulturetracker gui song.yaml                     # the app (no song: open, new song, import)
python -m vulturetracker check song.yaml                   # validate; errors show file:line
python -m vulturetracker build song.yaml --render song.wav # compile, verify with libopenmpt, render
python -m vulturetracker import some.xm -o some.yaml       # a module, tab, MIDI file or SoundFont -> song file
python -m vulturetracker --help                            # every command
```

## Privacy and security

The app is a local server on 127.0.0.1 with no telemetry. It goes online only for downloads you start (checked against
pinned SHA-256 digests) and for the AGENT panel, which sends the open song to the provider you chose. Settings and API
keys stay in your user folder. Each release lists the SHA-256 of its files (`certutil -hashfile vulturetracker.exe
SHA256` on Windows); the exe is not code-signed. [SECURITY.md](SECURITY.md) explains private vulnerability reports.

## Reporting a problem

Use the [bug form](https://github.com/shadoh420/VultureTracker/issues/new/choose) with the version, the steps and the
app's log, `%APPDATA%\VultureTracker\vulturetracker.log` on Windows (`~/Library/Application Support/VultureTracker` on
macOS, `~/.config/VultureTracker` elsewhere), and the song if you can share it. Security problems go through
[SECURITY.md](SECURITY.md) instead.

## Docs

[GUIDE.md](GUIDE.md) (the app and the command line) · [SONG_FORMAT.md](SONG_FORMAT.md) (the song format) ·
[SAMPLING.md](SAMPLING.md) (making samples) · [CHANGELOG.md](CHANGELOG.md) · [PROVENANCE.md](PROVENANCE.md) (what the
demos take from references) · [AGENTS.md](AGENTS.md) (for people and AI agents working on the code)

## Credits and licenses

VultureTracker's code is MIT licensed ([LICENSE](LICENSE)). It builds on:

- [libopenmpt](https://lib.openmpt.org) (BSD-3-Clause), which verifies and renders every module, natively and as its
  WebAssembly build in the page. The Windows build carries mpg123 (LGPL-2.1, a separate replaceable DLL), libogg and
  libvorbis (BSD-3-Clause) and zlib; license texts are in `vendor/Licenses/` and `vulturetracker/web/`.
- The exe bundles Python, pywebview, pythonnet, NumPy, PyYAML, mido, sounddevice with PortAudio, PyGuitarPro (LGPL-3.0)
  and [pedalboard](https://github.com/spotify/pedalboard) (GPL-3.0). Because of pedalboard the exe as a whole is GPL-3.0,
  while this repository stays MIT. [FFmpeg](https://ffmpeg.org) (GPL-3.0) ships beside it as a separate program.
- The demo samples credit their sources in `samples/*/ATTRIBUTION.md` (CC0 recordings by Karoryfer Samples and
  Versilian Studios; renders from Surge XT, Dexed and OB-Xd). demo4 takes UT99's Foregone Destruction (Epic Games,
  composed by Michiel van den Bos) as a stylistic reference only; [PROVENANCE.md](PROVENANCE.md) says what was taken.
- The IT writer follows [ITTECH.TXT](https://github.com/schismtracker/schismtracker/wiki/ITTECH.TXT) and OpenMPT's
  loader.

Every component, version and license text: [THIRD_PARTY.md](THIRD_PARTY.md).
