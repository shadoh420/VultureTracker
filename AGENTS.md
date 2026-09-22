# Working on VultureTracker (for people and AI agents)

Read this first. It says what this repository is, what it is not, where things live, and the rules the owner
(shadoh420) has set. `suite/HANDOFF.md` holds the current state of the music work; this file holds what does not change.

## Names, folders and what this is not

- **The project is VultureTracker.** It was called TrackerForge until 2026-09-21. The folder kept the old name on
  purpose: `C:\Users\c\TrackerForge` is this repository, the package is `vulturetracker/`, the exe is
  `dist/vulturetracker.exe`, the remote is https://github.com/shadoh420/VultureTracker. Any "TrackerForge" you meet in
  paths, notes or old chat is this same project; do not rename the folder (tryout state and recent-song lists hold
  absolute paths).
- **ArenaPrototype is a different project.** `C:\Users\c\ArenaPrototypeContainer` and the worktrees under `C:\tmp\arena-*`
  are a Unity game with its own `AGENTS.md`, `CLAUDE.md`, handoffs and rules (NetShift, Unity licensing, checkpoints).
  A session may be launched from one of those folders and still be asked to work here: then work only in
  `C:\Users\c\TrackerForge` with absolute paths, and do not apply the Unity project's rules to this one. The music made
  here is meant for that game eventually, which is the only link.
- **The old remote** https://github.com/shadoh420/TrackerStuff is retired (private). The public history was squashed
  once on 2026-09-21; the pre-squash history lives locally on `backup/pre-squash-20260921`.

## What the software does

A song is a YAML file (`SONG_FORMAT.md`); `python -m vulturetracker build song.yaml --render song.wav` compiles it to
an Impulse Tracker `.it`, verifies it with libopenmpt and renders WAV. `synth` renders samples from free synths and
recordings by recipe (`SAMPLING.md`), `import` turns an existing module into a song file, and `gui` is the app
(`GUIDE.md`): the tryout (candidate samples rendered inside the song, rated, written with `U`), the mixer, listening
notes (`N`, written to `<song>.notes.json` and `.md` beside the song), the pattern view, stems export.
`python -m vulturetracker --help` lists the commands.

## Layout

| Path | What | In git? |
|---|---|---|
| `vulturetracker/` | the package: `song.py` + `model.py` + `itwriter.py` (compiler), `itreader.py` (import), `openmpt.py` (libopenmpt), `gui.py` + `gui.html` (the app), `resample.py`, `synth.py`, `notation.py`, `wavload.py`, `api.py` | yes |
| `tests/` | `python -m unittest tests.test_gui tests.test_pipeline tests.test_resample` (about 3 s); `test_synth`/`test_import` need the plugins and fixtures | yes (fixtures ignored) |
| `demo/`, `demo2/`, `demo3/`, `demo4/` | the demo songs with their generators; `demo4/vantage.yaml` is the piece the owner likes best | yaml and scripts yes, `.it`/`.wav` ignored |
| `suite/` | the UT99 tribute suite: `HANDOFF.md` (current state), `NEXT-PROMPT.md` (how the next piece is to be made), `nadir/` (the first piece) | yes, renders ignored |
| `samples/` | committed samples per demo and piece with an `ATTRIBUTION.md` each; `samples/local/` is scratch and ignored | partly |
| `tools/` | `build_exe.py`, `demo_video.py`, fetchers; `tools/cc0`, `tools/surge-xt`, `tools/synths`, `tools/royalty-free` are downloaded and ignored | scripts yes |
| `scratch/` | local only, never committed: `scratch/ut99-clean/` holds the extracted Unreal Tournament modules (copyright Epic) and the analysis scripts (`analyze.py`, `structure.py`, `compare.py`, `spectrogram.py`, `GROUPS.md`) | no |
| `vendor/` | libopenmpt DLLs for Windows | yes |
| `test/` | the owner's own folder; leave it alone | no |
| `docs_ref/`, `build/`, `dist/`, `.tryout/`, `*.tryout.json` | generated or reference material | no |

## Rules the owner has set

- **Commits are the owner's call.** Commit only when told ("let's commit", "go ahead and commit"); push and release only
  when told. Stage exact paths; never `git add -A`, `git add .` or `commit -am`. Review `git diff --cached` before
  committing. Keep `scratch/`, `samples/local/` and every render out.
- **Copyright.** Nothing from the UT99 modules is copied: no audio, no sample data, no melodic cell, no sample chosen by
  matching one of theirs. What a piece takes is described in `PROVENANCE.md`, and the wording is "inspired by" or "in
  the style of", never "based on". The extracted modules stay in `scratch/`. The 2024 Epic freeware release covers the
  games, not the music.
- **The owner's ear decides.** An agent cannot listen; it measures (`scratch/ut99-clean/compare.py`, `suite/nadir/
  harmony.py`, spectrograms, soloed channel levels) and reports measurements as measurements, never as something it
  heard. Sounds are offered as tryout candidates and the owner picks them in the app; levels are the owner's (the
  faders and WRITE MIX), not the agent's. Feedback arrives as listening notes (`<song>.notes.md`): read the words and
  the sounding list of each note, act on them, and do not ask what the report already answers.
- **Taste (durable):** dark, subdued, dream-like melodic sounds; no bell, pluck, pizzicato, square, flute or buzzy saw
  leads, no orchestral rolls or gongs; gameplay drive even when dark; one moving line at a time; one pedal rather than
  colour changes or chord progressions (they read as "prog rock"); no repeating arpeggio or sequence figures unless the
  reference has them; drums the owner has approved stay row for row; every melodic voice in its own single-sample slot.
  Build a piece against **one** reference track (the way Vantage was built against Foregone Destruction), never a
  synthesis of several; `suite/NEXT-PROMPT.md` is the agreed procedure.
- **No anti-aliasing regressions.** Songs set `module: sample_rate: 44100`; no note plays a sample more than about seven
  semitones above its root; renders are oversampled; a spectrogram should be empty above the drums' ceiling.

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
  `gui.html` is re-read per request, `gui.py` needs a restart. Delete any notes the harness made on a real song.
- Release recipe: bump `version` in `pyproject.toml`, commit "Version X", `git tag -a vX`, push `main` and the tag,
  `python tools/build_exe.py`, smoke-test `dist/vulturetracker.exe gui demo2/iron_relay.yaml --no-browser --port 8766`
  (poll `/api/state`, GET `/`), `sha256sum`, then `gh release create vX dist/vulturetracker.exe --title --notes-file
  --latest`. Write the notes file as UTF-8 without BOM from Python or an editor, never through PowerShell 5.1 text
  cmdlets (the 0.2.1 notes came out with "â†’" for "→" and a BOM that way), and check the published body with
  `gh api repos/shadoh420/VultureTracker/releases/tags/vX --jq .body`.
- Windows PowerShell 5.1 is the host shell: no `&&`, no `??`; Git Bash is available for POSIX syntax.
- Python 3.14 at `C:\Python314`; `pyyaml`, `numpy`, `pywebview`, `pywin32`, `Pillow`, `imageio-ffmpeg` (its ffmpeg
  makes the MP3s), `pedalboard` (sample generators only; excluded from the exe, GPL).

## Where to start

1. `suite/HANDOFF.md` for the state of the music, then the task at hand.
2. `GUIDE.md`, `SONG_FORMAT.md`, `SAMPLING.md` only when the task needs them.
3. Before changing the app: run the three test modules; after changing `gui.py`/`gui.html`: tests plus a check in the
   real window; before any commit: the owner's word.
