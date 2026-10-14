# Working on VultureTracker (for people and AI agents)

Read this first. It says what this repository is, what it is not, where things live, and the rules the owner
(shadoh420) has set. `suite/HANDOFF.md` holds the current state of the music work; this file holds what does not change.
On the owner's PC, `AGENTS.local.md` (untracked, ignored by git) adds what only holds there: the checkout's path, the
retired remote and its backup branch, the owner's own folders and the UT99 analysis method; read it too when it exists.

## Names, folders and what this is not

- **The project is VultureTracker.** It was called TrackerForge until 2026-09-21, and a checkout's folder may still
  carry that name: the package is `vulturetracker/`, the exe is `dist/vulturetracker.exe`, the remote is
  https://github.com/shadoh420/VultureTracker. Any "TrackerForge" you meet in paths, notes or old chat is this same
  project; do not rename a checkout's folder (tryout state and recent-song lists hold absolute paths).
- **Other projects.** A session may be launched from another project's folder and still be asked to work here: then
  work only in this repository's folder, with absolute paths, and apply this repository's rules only, never that
  project's.

## What the software does

A song is a YAML file (`SONG_FORMAT.md`); `python -m vulturetracker build song.yaml --render song.wav` compiles it to
an Impulse Tracker `.it`, verifies it with libopenmpt and renders WAV. `synth` renders samples from free synths and
recordings by recipe (`SAMPLING.md`), `import` turns an existing module (IT, XM, S3M, MOD), a Guitar Pro 3-5 tab or a MIDI file into a song file, and `gui` is the app
(`GUIDE.md`): the tryout (candidate samples rendered inside the song, rated, written with `U`), the mixer, listening
notes (`N`, written to `<song>.notes.json` and `.md` beside the song), the pattern view, stems export.
`python -m vulturetracker --help` lists the commands.

## Layout

| Path | What | In git? |
|---|---|---|
| `vulturetracker/` | the package: `song.py` + `model.py` + `itwriter.py` (compiler), `itreader.py` + `modreader.py` (import of IT, XM, S3M, MOD), `openmpt.py` (libopenmpt), `gui.py` + `gui.html` (the app: the open song's State, its render workers and the page), `server.py` (the app's HTTP side: the request handler with the Host, Origin and API token checks, the server and its port, and the lock an app holds on each song it has open; gui.py keeps the State it serves), `measure.py` (a WAV's measurements, spectrograms and the SPECTRUM tab's reference compare, a render's loudness, the mixer's header patch (patch_it) and soloed channel levels), `sample_edit.py` (the Samples tab's edits on a WAV's frames and its waveform view, the PAINT tab's picture checked, the instrument panel's view of an instrument entry), `web/` (the live engine: libopenmpt 0.8.9 as WebAssembly and its AudioWorklet; `tests/test_engine.py` checks it under node), `resample.py`, `synth.py`, `sources.py` (the recipe sources computed in numpy: `wave:` cycles, `sfxr:`, `drum:` (DrumSynth), PADsynth `additive:`, the `mip` copies, and Hydrogen kits for `file:`), `faust_examples/` (the `.dsp` files a recipe's `faust: NAME.dsp` falls back to; packed like `web/`), `notation.py`, `wavload.py`, `api.py`, `compose.py` (the Pattern tab's GROOVE, EUCLID, CHORD and STRUM, ARP, LAYERS, and the SELECTION bar's INTERPOLATE, AUTOMATE, GROW/SHRINK and LENGTH tools), `dsp.py` (the Samples tab's onsets for SLICE, its EFFECTS, and a take's pitch, edges and loop), `record.py` (the RECORD tab: sounddevice input, `VT_FAKE_AUDIO=1` simulates a two-input interface), `library.py` (the sample index by timbre: features, the JSON index cached on file stamps, nearest sounds, the MAP tab's PCA; `index` and `tryout --like` on the command line), `mosaic.py` (the recipe source `resynth:`: a target rebuilt from blocks of a corpus), `spectral.py` (the PAINT tab: a picture played additively, or laid over a sample's spectrum as a filter), `gpimport.py` (Guitar Pro tabs through PyGuitarPro, optional), `sf2.py` (a SoundFont 2 preset or a GUS `.pat` as one instrument, read as OpenMPT's loaders read them: `import` and the Instruments tab), `midiimport.py` (MIDI files through mido, optional), `faust.py` + `web/faust-render.mjs` (Faust code rendered by faustwasm, fetched into the ignored `tools/faustwasm`: under node for `faust:` recipes, in the page for the FAUST tab), `fileio.py` (atomic writes, output guards, the per-user folder), `history.py` (persistent undo/redo, checkpoints, the save journal), `project.py` (PROJECT's Collect Samples), `arrangement.py` (named sections, order remapping), `phrases.py` (the PHRASES tab), `export.py` (the RENDER & EXPORT jobs), `plugins.py` (OpenMPT's DMO mix plugins: their parameters, the song format's `plugins:`/`macros:`, the .it chunks; the RACK tab), `agent.py` (the agent tools on the open song, their path guard, and the AGENT panel's chat: Claude Code, the Anthropic API, Gemini or an OpenAI-compatible server), `agent_context.py` (the chat's small tool directory and its bounded, retrievable tool output), `agent_sounds.py` (the tools on the library, recipes and PAINT), `agent_projects.py` (the tools on PHRASES and PROJECT), `agent_sessions.py` (the tools on recording, listening notes, playback and history), `mcp.py` (`python -m vulturetracker mcp`: those tools over MCP, bridged to the running app) | yes |
| `tests/` | `python -m unittest tests.test_gui tests.test_pipeline tests.test_resample tests.test_engine tests.test_modimport tests.test_compose tests.test_record tests.test_library tests.test_mosaic tests.test_spectral tests.test_gpimport tests.test_midiimport tests.test_faust tests.test_workflow tests.test_release070 tests.test_release080 tests.test_release080_import tests.test_release080_dsp tests.test_import tests.test_synth tests.test_sources tests.test_release100 tests.test_stems_to_song tests.test_plugins tests.test_measure tests.test_agent tests.test_agent_projects tests.test_agent_sessions tests.test_malformed tests.test_docs tests.test_vendor` (about 300 s; `test_engine` needs node; `test_docs` checks this list against CI's); `test_page`, `test_workflow_page`, `test_release070_page`, `test_release080_page`, `test_features080_page`, `test_release100_page` and `test_features_page` drive the page in Playwright's Chromium (`VT_CHROMIUM` names another; on Windows Edge works); `test_synth`/`test_import` skip without the plugins and fixtures; `.github/workflows/tests.yml` runs both sets on Linux | yes (fixtures ignored) |
| `demo/`, `demo2/`, `demo3/`, `demo4/` | the demo songs with their generators; `demo4/vantage.yaml` is the piece the owner likes best | yaml and scripts yes, `.it`/`.wav` ignored |
| `suite/` | the UT99 tribute suite: `HANDOFF.md` (current state), `NEXT-PROMPT.md` (how the next piece is to be made), `nadir/` (the first piece) | yes, renders ignored |
| `samples/` | committed samples per demo and piece with an `ATTRIBUTION.md` each; `samples/local/` is scratch and ignored | partly |
| `tools/` | `build_exe.py` (with `exe_entry.py`, the exe's launcher), `demo_video.py`, `bench.py` (times compile, render and an edit on the demos), `take_view_bench.py` (the Samples tab's waveform view on a long take) and `worklet_bench.js` (the live engine's audio-thread cost of its position message), `dmo_spike.py` (OpenMPT's DMO effects written into an .it and measured in both libopenmpt builds; not in the compiler), `transcribe_audio.py` (a recording to a song: demucs stems, notes by basic-pitch or YourMT3+ (`yourmt3_transcribe.py`), ADTOF drums, merged by `stems_to_midi.py`, scored by `transcription_diff.py`; `stems_to_song.py` plays such a transcription on samples cut from the recording's own stems (drum hits, notes, or the stems in sections); `tempo_check.py` says whether a recording sits on a steady grid (its BPM, row 0, how far each stretch is off it); `make_notes.py` writes a transcription's notes as a MIDI file and a Guitar Pro 5 tab on the recording's grid (bar lines on a given downbeat, a 2/4 bar where a recording gains half a bar, frets by the least hand movement, the parts that are no guitar or bass as notation tracks); `transcription_checks.py` checks a run (downbeats by beat_this, the transcribers against their stems, the tab read back, the exported .it's DELTA, the rows with sound but no note); `--setup [--cuda] [--yourmt3]` makes its Python 3.11 environments in `tools/transcribe-env`; `transcribe_setup.cmd` and `transcribe.cmd` do it all on a Windows PC with nothing installed, `uv.exe` in the ignored `tools/bin`), fetchers; `tools/cc0`, `tools/surge-xt`, `tools/synths`, `tools/royalty-free`, `tools/faustwasm`, `tools/libopenmpt-js`, `tools/transcribe-env` are downloaded and ignored | scripts yes |
| `scratch/` | local only, never committed (reference material that may not be shared, such as the extracted UT99 modules; `AGENTS.local.md` says what is there) | no |
| `vendor/` | libopenmpt DLLs for Windows | yes |
| `.claude/` | `hooks/session-start.sh`: cloud sessions install libopenmpt (Ubuntu's 0.7.x) and `requirements-test.txt` (the pinned, hashed packages CI installs) and set `VT_CHROMIUM`, so the tests run at once | yes |
| `requirements-test.txt`, `requirements-build.txt` | the test and the exe build environments, every package pinned with its SHA-256 (the command that made each is in its header) | yes |
| `AGENTS.local.md` | the owner's local notes for agents (above) | no |
| `docs_ref/`, `build/`, `dist/`, `.tryout/`, `*.tryout.json` | generated or reference material | no |

## Rules the owner has set

- **Commits are the owner's call.** Commit only when told ("let's commit", "go ahead and commit"); push and release only
  when told. Stage exact paths; never `git add -A`, `git add .` or `commit -am`. Review `git diff --cached` before
  committing. Keep `scratch/`, `samples/local/` and every render out.
- **Copyright.** Nothing from the UT99 modules is copied: no audio, no sample data, no melodic cell, no sample chosen by
  matching one of theirs. What a piece takes is described in `PROVENANCE.md`, and the wording is "inspired by" or "in
  the style of", never "based on". The extracted modules stay in `scratch/`. The 2024 Epic freeware release covers the
  games, not the music. How a piece is built against its reference (what may be measured from it, what is always
  written from scratch) is in `suite/NEXT-PROMPT.md` and, on the owner's PC, `AGENTS.local.md`.
- **The owner's ear decides.** An agent cannot listen; it measures (spectrograms, soloed channel levels, the analysis
  scripts) and reports measurements as measurements, never as something it heard. Sounds are offered as tryout candidates and the owner picks them in the app; levels are the owner's (the
  faders and WRITE MIX), not the agent's. Feedback arrives as listening notes (`<song>.notes.md`): read the words and
  the sounding list of each note, act on them, and do not ask what the report already answers.
- **Our own lines.** Every melodic line in a piece is written from scratch, never derived from a reference's melody,
  rhythm, cells, contour or register; when the owner says a passage sounds like the reference, rewrite its notes. Drums,
  sub and other sounds the owner has approved stay as they are unless the owner says otherwise.
- **No anti-aliasing regressions.** Songs set `module: sample_rate: 44100` and renders are oversampled. A sample may be
  played as far above its root as its content allows: its bandwidth times the transposition ratio stays under about
  18 kHz and under the drums' ceiling (a sample 4.5 kHz wide may play two octaves up, one 9 kHz wide one octave up).
  Storing a sample at a low rate and playing it octaves up, as the references do, is fine. Playing a bright sample more
  than about three semitones below its root is not: libopenmpt's 8-tap interpolator lets images of the top of its band
  through under 20 kHz (about -20 dB for full-band content). `check` warns when a sample's lowest note leaves images
  within 60 dB of it; play it higher, add a lower multisample, or set `sample_rate: 88200`. It also warns when a
  sample's highest note lifts its content (where its spectrum comes within 60 dB of its loudest band) over `module:
  ceiling`, 18 kHz unless the song sets the drums' own. The spectrogram check stays:
  nothing above the drums' ceiling. (Until 2026-09-22 the limit was about seven semitones above the root.)
- **Follow OpenMPT (since 2026-10-01).** Where the app does something OpenMPT also does (note and chord entry, the
  keyboard, the clipboard, what an effect means, how a module imports), it behaves as OpenMPT does, checked against
  OpenMPT's source (github.com/OpenMPT/openmpt; local copies of `View_pat.cpp`, `PatternClipboard.cpp`,
  `CommandSet.cpp` and `DefaultKeyBindings.h` in `scratch/080`), not from memory. GUIDE.md's "Following OpenMPT"
  paragraph lists what has been matched: add to it when you match another behaviour, and name any deliberate
  difference there.

## Working conventions and pitfalls

- Git's index is LF and the system git config has `core.autocrlf=true`, so "LF will be replaced by CRLF" warnings are
  normal. Check a file's endings with Python bytes, not grep. `Path.write_text` writes CRLF on Windows: the app writes
  the song with the file's own endings (`State.write_song`); do the same in scripts (`write_bytes`, or
  `write_text(..., newline="\n")`).
- Edit with small exact-string replacements (a Python patch script that asserts one match) rather than sed; long
  heredocs have failed in agent shells.
- The app server is HTTP on localhost. To verify the page without a display: `python -m vulturetracker gui <song>
  --no-browser --port 8765`, poll `/api/state`, then drive a pywebview window with `evaluate_js` (the page's globals are
  top-level `let`, so poll bare `S`, not `window.S`) and grab the client rect; `tools/demo_video.py` has the pieces.
  `gui.html` is re-read per request, `gui.py` and `server.py` need a restart. Delete any notes the harness made on a real song.
- Release recipe: write the release's entry under `## Unreleased` in CHANGELOG.md, then run `python tools/release.py X.Y.Z`
  and follow its printed commands in order. It bumps `__version__` in `vulturetracker/__init__.py` (the one place;
  pyproject.toml reads it), retitles that section as the version with the date, and writes `dist/release-notes-X.Y.Z.md`
  itself, from Python as UTF-8 without BOM: never make or touch that file with PowerShell 5.1 text cmdlets (the 0.2.1
  notes came out with "â†’" for "→" and a BOM that way). It never commits, tags, pushes, builds or publishes: those are
  the printed commands (commit "Version X.Y.Z", `git tag -a vX.Y.Z`, push `main` and the tag, `python tools/build_exe.py`,
  which copies ffmpeg beside the exe for the MP3/OGG/FLAC export, shipped as its own file; it refuses to build when the
  installed packages differ from `requirements-build.txt`'s hashed pins). `python tools/exe_check.py
  dist/vulturetracker.exe` replaces the manual smoke test: it starts the exe headless on `demo2/iron_relay.yaml`, waits for
  `/api/state` and the page, then runs the exe's `--selfcheck` (every packed module and data file, one line each).
  `release.py X.Y.Z --digests` puts the three SHA-256 digests into the notes file after the build; paste the sha256 of
  `vulturetracker.exe` into the release notes and README (its Install section names the current release's); after `gh release
  create` (its command is printed too), `release.py X.Y.Z --check` fetches the published body and verifies the digests
  against `dist/` (`tests/test_docs.py` plants a wrong digest to keep it honest). `--dry-run` prints without writing.
  Pushing the tag also starts `.github/workflows/build.yml`: the same build and `exe_check` on a clean Windows runner,
  the three files uploaded as the run's artifact with their digests in the log. **The published exe is still the owner's
  local build**; the CI build proves the tag builds and runs from the repository and PyPI alone (PyInstaller output is
  not byte-reproducible, so its digests differ). Publishing the CI build instead, which code signing would need
  (`scratch/audit-2026-10-08/SIGNING.md`), means downloading its artifact into `dist/` before `--digests`; that is the
  owner's call.
- Windows PowerShell 5.1 is the host shell: no `&&`, no `??`; Git Bash is available for POSIX syntax.
- Python 3.14 (`AGENTS.local.md` says where); `pyyaml`, `numpy`, `pywebview`, `pywin32`, `Pillow`, `imageio-ffmpeg` (its ffmpeg
  makes the MP3s), `pedalboard` + `mido` (the synth host: sample generators and the RECIPE box; packed into the exe, which makes the exe GPL-3, THIRD_PARTY.md).

## Reusable scripts

- Check `tools/` for a suitable existing script before writing an ad-hoc script; prefer reuse where practical.
- When a non-trivial ad-hoc script has a concrete likely future use, briefly offer at the end of the reply to retain it
  in `tools/`, stating that use. Require explicit approval unless retention was already requested. Temporary task
  scripts do not require this additional approval.
- Retained scripts accept parameters for session-specific inputs, contain no embedded secrets, and provide usage help
  and clear errors for invalid arguments. Keep generalization minimal.

## Where to start

1. `suite/HANDOFF.md` for the state of the music, then the task at hand.
2. `GUIDE.md`, `SONG_FORMAT.md`, `SAMPLING.md` only when the task needs them.
3. Before changing the app: run the portable tests (the command in the layout table); after changing `gui.py`/`server.py`/`gui.html`: tests plus a check in the
   real window; before any commit: the owner's word.
