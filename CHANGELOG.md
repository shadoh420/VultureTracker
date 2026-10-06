# Changelog

What changed in each VultureTracker release (the GitHub release notes, without their download and checksum parts). Newest first.

## 1.1.0 (2026-10-05)

A recording can sit under the song in the SPECTRUM tab, to compare the two cell by cell, and new tools outside the app
turn a recording into a song, a MIDI file and a Guitar Pro tab.

- **A reference in the SPECTRUM tab.** REFERENCE sets another recording (WAV, MP3, FLAC, OGG…) under what plays: REF
  shows its spectrogram over the same span, its level matched to the song's, and DELTA the song minus the reference in
  each cell (red: louder in the song), with the mean |Δ| per order and the span's median. OFFSET (ms) and ALIGN (the
  onsets of both cross-correlated) line it up; a section is compared with the part of the reference it covers.
- **Transcribing a recording** (`tools/transcribe_audio.py`, with `stems_to_midi.py`, `yourmt3_transcribe.py` and
  `transcription_diff.py`): stems by demucs or a RoFormer model, notes by basic-pitch and/or YourMT3+ (each makes its own
  song; the bass optionally by VultureTracker's YIN), drums by ADTOF, merged on the track's own beat grid into a MIDI
  file, imported and rendered, and scored against the recording. The tools run in their own Python environments
  (`--setup`, with `--cuda` for an NVIDIA card and `--yourmt3` for its model); `tools/transcribe_setup.cmd` and
  `transcribe.cmd` set up and run it all on a Windows PC with nothing installed. `tools/stems_to_song.py` then plays such a
  transcription on samples cut from the recording's own stems: drum hits sliced and grouped into types, notes on a sample
  per pitch, or a stem itself in sections, with a tempo channel that keeps the render on the recording's grid.
  `tools/tempo_check.py` says first whether a recording sits on a steady grid: its BPM, where row 0 falls, and how far
  each stretch of it is off the grid. `tools/make_notes.py` writes the transcribed notes as a MIDI file and a Guitar Pro 5
  tab on that grid, the bar lines on a given downbeat: guitar and bass on the standard tuning their lowest notes need,
  frets chosen so the hand moves least, and the drums. Nothing is added to the app or the exe.
- Fixed: under numpy 1.x on Windows the SPECTRUM view (and DELTA) went blank past about 40 s of a render: a 32-bit
  column index overflowed. The exe and numpy 2 were not affected.

**Upgrade note:** song files, history and checkpoints are unchanged from 1.0.0, and so are renders. The reference is
kept with the tryout settings beside the song. The transcription tools are not in the exe: they run from a source
checkout in their own Python environments (`python tools/transcribe_audio.py --setup`, 3 to 6 GB).

## 1.0.0 (2026-10-01)

A song, its history and its exports stay right from version to version, and the first things a new user reaches for
work: other sample formats, imports that keep more, a command line on a par with the app, Faust sounds that can be
made again, and a UI scale.

- **Songs stay readable across versions** (SONG_FORMAT.md, section 10). 1.x opens every song that 0.6 or later wrote,
  unchanged, and compiles it to the same module: the demos whose samples are in git are held to their exact `.it`
  bytes. A song can name the oldest app that reads it, `requires: "1.2"`; an older app then says only that, instead of
  listing the keys it does not know. The files beside the song carry a `schema` number, and one written by a newer
  VultureTracker opens the song read-only with a notice naming it, instead of being written over (a newer history was
  moved aside as corrupt). `<song>.notes.json` is now `{"schema": 1, "notes": [...]}`; the older list is read, and an
  app before this one reads the new file as empty. A listening note in a read-only window is refused, as edits are,
  instead of being written over the other window's notes.
- **The app says its version**: `vulturetracker --version`, the window title, the start screen and the listening-notes
  report. It is set in one place, `vulturetracker/__init__.py`, which a pip install reads too.
- **A log for bug reports.** The exe has no console, so what failed unexpectedly went nowhere. The app now writes it,
  with the traceback, to `vulturetracker.log` in its settings folder (`%APPDATA%\VultureTracker`; two files of 256 KB
  at most, each start naming the version, libopenmpt's and the system), and the error the page shows ends with the path.
- **Installing from source** goes through extras: `pip install -e ".[all]"` (or `gui`, `record`, `synth`, `gp`, `midi`,
  `test`); CI installs `.[test]`, so the package test runs there too.
- **Linux and macOS paths.** The settings, library index, window profile and log live where each system keeps an
  application's (`~/.config/VultureTracker` on Linux, `~/Library/Application Support/VultureTracker` on macOS; they were
  in `~/VultureTracker`, whose recent list is still read), the downloads in `~/.local/share/VultureTracker`, and
  installed Surge XT, Dexed and OB-Xd are found in the system's VST3 folders. GUIDE.md's Platforms says what stays
  Windows-only.
- **FLAC, AIFF, OGG and MP3 samples.** Wherever the app takes a WAV (a drop, a candidate path or glob, a new slot, a
  slot's file) it now takes these too: each becomes a 16-bit WAV beside the song through the ffmpeg the export uses,
  never over a file there, with the loops and root note OpenMPT keeps from it (a FLAC's embedded sampler chunks or its
  LOOPSTART/LOOPLENGTH tags, an AIFF's loops; nothing from Ogg or MP3).
- **The command line does what the app does to a song's history**: `undo`, `redo` and `trim-history --keep N`;
  `sections rename NAME --as NEW` (also in the app's `section_edit`; the section keeps its place and comment);
  `--json` on `sections`, `checkpoint` and `phrase`; and `--wait SECONDS` on all of them, to wait for a song the app or
  another command has open instead of failing at once.
- **Imports keep more, as OpenMPT does.** A MIDI file's pitch bends become E/F slides (with its RPN bend range), its
  sustain pedal holds notes until it comes up, and its markers become named sections. Module names keep their letters
  (`Böse` is `Bose`, read in the character set OpenMPT reads them in; it was `B?se`), and what an import drops without
  a sound (an IT's edit history, MIDI pitch wheel depth, instruments' MIDI channel, program and bank) is now listed
  with the other warnings.
- **Faust sounds can be made again.** Each FAUST tab save also writes a `faust:` entry for its WAV (the code, the
  notes, hold, tail, velocity and sliders) into `faust.yaml` beside the song, so `synth` and the RECIPE box render it
  again and edit it. The code being typed is kept with each song (it was one draft per browser). The sustain pedal
  (CC 64) holds notes on the FAUST tab. Leaving the tab, or COMPILE while notes sound, now lets the notes ring out on
  their release: faustwasm's soft all-notes-off was a hard one (CC 123) and cut them at once.
- **UI SCALE** (top bar and start screen, 90-200 %): the whole app larger or smaller, kept in the browser with the
  other page settings. The app's window has no Ctrl+wheel or Ctrl+= zoom (pywebview turns WebView2's off).
- **Faust plays chords, live and from MIDI.** The FAUST tab's code is now a polyphonic instrument, a voice per note in
  Faust's own way (`freq`, `gain` and `gate` set per voice; an `effect` in the code runs once on the sum). NOTE takes a
  chord (`C-5 E-5 G-5`) for PREVIEW and the saves. The piano keys play the code live at their real pitch (before, one
  render was replayed faster or slower) and hold the note until let go; sliders act on the notes sounding; with the
  tab open a MIDI keyboard plays it, with velocity, and pitch bend and controllers reach the controls the code maps
  with `[midi:...]`. Recipes: `faust:` samples take `chord:` and `phrase:` like synth patches.

- **Following OpenMPT** (GUIDE.md, "Following OpenMPT"; where the app does what OpenMPT does, it does it OpenMPT's
  way): the piano keys go by their place on the keyboard, so QWERTZ and AZERTY play what QWERTY does; the edit keys are
  OpenMPT's IT-style ones: `1` a note cut, `` ` `` a note-off, Shift+`` ` `` or `\` a fade (they were `1` note-off,
  `` ` `` fade, `\` cut); CHORD joins a key
  or MIDI note struck within 60 ms of the one before (OpenMPT's auto-chord wait; it was 50 ms from the first), so a
  rolled chord stays on one row; an MPTM parameter-control (PC) event pastes as `Zxx`, as OpenMPT converts it (it
  pasted its plugin number as an instrument).
- **The command line and the app share a song safely.** `sections`, `checkpoint` and `phrase` hold the song's lock for
  the whole command: a second command at the same time, or one while the app has the song open, is refused (exit 1)
  instead of losing a change while saying it saved. An app opening a song that a command is changing, or that another
  app window has open, waits a moment, then opens it read-only with a notice. Commands that only read leave the app's
  files alone, and the commands print what the app would show as a notice as `note:` lines.

Fixes, from an audit of 0.9.0 (36 bugs, each with a regression test): a background job that failed unexpectedly (a
RECIPE entry `chord: []`) stopped every later render, build and export until a restart; it now fails alone. Game loops
are frame-exact at every tempo (only tempos dividing 1500 were: at tempo 137 a 3.5 s loop was 114 frames short), and so
are whole-song lengths and phrase renders. Checkpoints save and restore a song whose text is not valid YAML. A phrase
render can no longer overwrite the notes report, its archives, the phrase comparisons or the recovery journal. Deleting
a section no longer leaves a blank line. A phrase's stars outside 0-5 are refused, an output path that is a folder or in
a missing folder is named in the error, and `api.save` writes LF in one atomic write.

Recipes: a render over full scale is scaled just under it, and the log says so, instead of clipped (unless
`normalize:` is set); an empty chord or phrase, a missing or zero `bpm`, a short phrase note or a velocity outside
1-127 is an error naming the key (some stopped the command with a traceback). Faust: a render's release no longer starts
up to 127 samples late; a note of zero length is released after one frame instead of sounding to the end; an `effect`
that does not compile is an error instead of being dropped; two overlapping notes of one pitch each end on their own
key-off; renders never steal a voice; on the FAUST tab a MIDI controller moves its slider (PREVIEW and the saves
rendered the slider's old value), leaving the tab puts a pitch-wheel control back, and code that does not compile is
not compiled again at every key.

Imports: a MIDI file played in without a click and slower than about 90 BPM got note delays the format lacks (`SD10`
and up) and did not compile; of several tempos or time signatures on one tick the last counts, and of tempo changes
landing on one row the last stays; track names written as UTF-8 read as such ("Böse" became "BA?se"), a name ends at a
NUL and names lose control characters. Guitar Pro: a capo raises the pitch (capo tabs imported too low, harmonics too),
and long or transliterated track names keep their " str N" numbers. Modules with a pattern over 200 rows: a jump past
the order list is dropped (it landed on a split part and changed the loop), and a jump and a break on one row land on
the row they name.

Install and tests: a pip-installed package has the Pattern tab's effect help and keeps the synth and Faust downloads in
`%LOCALAPPDATA%/VultureTracker/tools`, not in site-packages; the page tests and the Guitar Pro tests skip without
Playwright or PyGuitarPro; a test that failed about one run in 19 no longer does.

**Upgrade note:** the note-off, note cut and fade keys moved to OpenMPT's (above). Song files, history and checkpoints
are unchanged from 0.9.0, and so are renders. The listening notes (`<song>.notes.json`) are written in a new layout
when the next note is made: 0.9.0 and older read that file as empty, and a note added there replaces the others, so
keep a song's notes in 1.0. On Linux and macOS the settings, the library index and the window profile move to the
system's folder (the recent list is read from the old `~/VultureTracker`; the library is indexed again). Song lengths
are now taken at the rate the audio is mixed at, so a game loop's length and a song's reported length can differ from
0.9.0's by a few hundredths of a percent. A MIDI file imported again comes out with its bends, pedal and markers (and
one played in under about 90 BPM at speed 16 or less), and a module's names keep their letters. A recipe that clipped
renders a little quieter, unclipped.

## 0.9.0 (2026-10-01)

The finishing workflows on the command line, chords the OpenMPT way, and a second pass over the 0.7.0 audit.

- **Chords from the computer keyboard follow OpenMPT:** with CHORD checked, keys struck within 50 ms are one chord,
  written as the keys go down (0.8.0 waited until they were let go); holding Shift, OpenMPT's chord modifier, gathers
  any keys into one chord, written when Shift is let go.
- **Names from non-ASCII file names are transliterated:** `Böse Bass.wav` becomes the sample name "Bose Bass" instead
  of "B?se Bass"; imported titles and track names likewise. What has no ASCII form still becomes `?`.
- **Sections, checkpoints and phrases from the command line:** `sections`, `checkpoint` and `phrase` list, save,
  move, duplicate, diff, restore, capture, render and accept as SONG, PROJECT and PHRASES do, each change an undo step
  the app opens with. While the app has the song open, the commands that would change it are refused (the app would
  write its own history over theirs).

Fixes: a pattern loop across the 192-row split of a long imported pattern plays as the original (its part ends after
the loop, and a loop longer than any part is played out); an XM restart position whose last row has no free effect
slot gets a channel of its own; SLICE finds a hit in the last half millisecond of a selection; a naive (aliased) saw
high up is no longer read an octave low (the sample library reads its pitches again once).

More fixes, from the audit's unconfirmed suspicions (16 of 26 confirmed, each with a regression test): sample edits on
a `loop: from_wav` whose loop runs past the audio work (FADE, REVERSE and CROSSFADE were refused, and a refused edit
could leave a WAV behind); an edit that changes nothing (▲ on channel 1) adds no undo step and keeps the redo steps;
TRIM HISTORY with the keep field emptied no longer clears every undo step; export names and dropped WAVs called CON,
NUL, COM1 or another Windows device name are refused or renamed (an export called CON froze the app run from a
terminal); a rating outside 0-5 is refused, and a bad one in a hand-edited `.tryout.json` no longer stops the notes
report. Imports: an S3M or XM order entry past the last pattern becomes `+++` (a later jump could skip a whole
pattern), an IT `---` that a jump aims at is kept, a beat highlight with no bar gives bars of four beats, and the song
is written LF in one atomic write. SLICE skips a hit's abrupt end (a click) and places a hit over a pad or a tail at
its start (up to 30 ms early before; a point now needs the level to rise about 3 dB over what sounds just before it,
so a softer hit inside a louder sound is no longer one); STRETCH of a selection shorter than about 90 ms keeps its
level (it lost up to 30 dB); recipes read `0100` as a hundred and a sample `010` writes `010.wav`, as song files read
them; a name such as "08" stays "08" when the app writes it; the sample library reads an unfinished WAV's real length
(it reads every file again once); Ctrl+Alt+V floods on layouts where AltGr+V types `@`; a ring-out ending on a
full-scale negative peak is no longer cut short.

**Upgrade note:** song files, history and checkpoints are unchanged from 0.8.0. The sample library reads every file
again once. SLICE's automatic points and STRETCH on short selections can differ from 0.8.0's (see above). In a sample
recipe, numbers with leading zeros read as decimals and a sample named `01` writes `01.wav` (it wrote `1.wav`).

## 0.8.0 (2026-10-01)

Getting music and sounds in and out.

- **Game loop export:** RENDER & EXPORT's Game loop (and `export --loop`) writes a section, or the whole song, for a
  game engine to loop: the region's second pass, so it starts with what its own end leaves ringing and the seam is
  continuous, then the tail as its release. WAV marks the loop in a `smpl` chunk, OGG and FLAC in `LOOPSTART` and
  `LOOPLENGTH` tags.
- **MIDI file import:** `.mid` and `.midi` (type 0 and 1) become song files with the Guitar Pro import's placeholder
  sounds, from the command line and the app's import. Quantised files get the coarsest grid that holds every note;
  played-in ones get sixteenths with note delays (SDx). Needs `pip install mido`.
- **OpenMPT clipboard both ways:** COPY puts the rows on the system clipboard in OpenMPT's format; Ctrl+V pastes rows
  copied in OpenMPT from an IT or MPTM module.
- **Command-line export and collect:** `export` (formats, sections, stems, game loops, the app's current mix) and
  `collect` (with `--zip`) without opening the app; neither writes anything beside the song.
- **Chords from the computer keyboard:** with CHORD, piano keys struck within 100 ms of each other go in as one chord.
- **Continuous integration** on GitHub Actions runs the portable and browser tests; this changelog.

Fixes: the 55 defects of an audit of 0.7.0, each with a regression test (`tests/test_release080*.py`): file writes
(the Tryout's keys no longer act from the Pattern tab; export and collect destinations relative to the song's folder),
crashes (sample keys, sections, library scans, non-ASCII and corrupt imports), silent wrong output (whole-song
ring-out, phrase renders, ECHO across patterns, live MIDI chords, imported loops and breaks, the resampler's images
above the source Nyquist: 128 taps, cut at 0.95), and the page against GUIDE.md.

## 0.7.0 (2026-09-30)

Longer editing sessions and performance capture, with fixes for 22 reproduced audit defects.

- **Bounded history:** compressed undo/redo and recovery data, a 16 MiB history budget, and PROJECT controls to trim or clear undo/redo while keeping named checkpoints. Large songs no longer hit the old recovery-journal limit after a short editing session.
- **Record alongside playback:** play the saved song or a named section with the current mixer and mutes, count in, record separate loop passes, and compensate round-trip latency using a loopback calibration. Input and output use one duplex stream and must share a driver/host API.
- **MIDI chords:** capture notes arriving within 50 ms across consecutive channels, as one undo step. Chords that exceed the remaining channels are refused without partial writes.
- **MAKE EDITABLE:** convert quoted or compact patterns to literal tracker rows; undo restores the original notation.
- **Beat spacing:** set rows per beat and bar in SONG. The grid, metronome and BPM display use these values, which round-trip through IT import/export.
- **Shared phrase samples:** frozen WAVs are stored once by content hash across new captures. Existing phrase folders remain readable.

Fixes include source-file overwrite protection in CLI tryout; section deletion/recreation; channel-row and YAML edits; inherited sample names and ECHO instruments; unsigned IT samples and pattern orders above 199; Guitar Pro Unicode titles; slice-delay overflow; mosaic tails; recorder pre-roll; Unicode take playback; song-switch cursor state; sounding-note reports; channel level measurement; full-scale peak detection; leading-zero decimal values; and the missing-candidate collection remedy.

**Upgrade note:** 0.6.0 history and checkpoints are read and migrated on the next write. The resulting compressed history format requires 0.7.0 or later. Named checkpoints are never automatically discarded; PROJECT explains when one must be removed to fit the storage budget. Song YAML remains the musical source of truth.

**Validation:** 230 tests passed; one optional synth test was skipped because Dexed is not installed. Browser and native-window checks passed. The packaged executable loaded the bundled demo, saved a checkpoint, changed and undid beat spacing, measured a simulated 50 ms loopback, and exported IT and MP3 using the companion ffmpeg. Physical-interface latency remains unvalidated; calibrate the actual device/rate/driver combination before recording.

Deferred proposals are tracked in [BACKLOG.md](https://github.com/shadoh420/VultureTracker/blob/v0.7.0/BACKLOG.md).

## 0.6.0 (2026-09-27)

**Finishing and sharing a song.** Four new tabs and a safer save underneath (walkthrough: GUIDE.md, "Finishing and sharing a song").

- **PROJECT:** undo/redo now survives restarts (200 steps), plus up to 32 named checkpoints you can compare and restore. When the song changes on disk, COMPARE / RELOAD shows the difference before reloading. Save Copy / Collect Samples writes a self-contained copy of the project (optionally a ZIP) with its samples, candidates, notes, recipes and credits. Missing samples can be relinked.
- **SONG:** named sections over the order list. Select, loop, move or duplicate a section (shared or independent pattern copies), and `Bxx` jumps follow their targets. MAKE THIS OCCURRENCE UNIQUE clones one order's pattern. Sections are stored as a `sections:` key (SONG_FORMAT.md).
- **PHRASES:** capture a selection, write two to four versions of a line yourself, and play them against the same frozen accompaniment and mix, with a version where the line is absent. Rate and note them, then diff and accept one (one undo step).
- **RENDER & EXPORT:** one panel for IT, WAV, MP3, OGG, FLAC and aligned stems. You choose the destination, the name, the whole song or a section, the saved or current mix, whether audition mutes apply, and the tail. A job is fixed when queued, can be cancelled, and never overwrites a source sample. Existing files are only replaced when you ask.
- Fixes: exports and builds can no longer overwrite a sample the song plays; a new song's tone never replaces an existing WAV; the song, its tryout settings and its history are saved together, and an interrupted save is recovered on reopening.

## 0.5.3 (2026-09-26)

**New: one download.** `vulturetracker-win64.zip` holds the exe, ffmpeg, the licences and two demo songs (Arena and Iron Relay) with all their samples. Unzip it anywhere, run `vulturetracker.exe`, and the start screen lists the demos.

- Fix: a downloaded exe looked for demos and `samples/` one folder above its own and found none. It now looks in its own folder first (still one level up for `dist/` in a checkout). The sample library's default folders follow the same rule.
- README: Install starts with the download.

## 0.5.2 (2026-09-26)

VultureTracker 0.5.2 fixes what a code review of 0.5.1 turned up: two ways to lose work, and a set of smaller correctness bugs.

- **Export never overwrites a sample.** Exporting `song.yaml` as `song.wav` used to replace a sample of the same name without warning. The export now stops and names the file.
- **RECORD keeps the take.** Changing INPUTS during a take could throw the whole take away. INPUTS is now locked while recording.
- **S3M import.** 16-bit samples (stored unsigned, the S3M default) now import correctly. They used to come out as full-scale noise.
- **Undo.** An undo whose write fails (Windows sometimes holds the file a moment) no longer loses its step. Saves now retry briefly when that happens.
- **Live playback follows the samples.** A WAV re-rendered in place now reaches the live engine without a RELOAD.
- **Piano keys on PAINT and FAUST.**
  - Keys pressed while a sound renders share one render and play in order, each at the pitch it had when pressed.
  - Nothing plays once you leave the tab, and ■ stops the keys too.
- **Smaller fixes.**
  - A song section of the wrong shape (such as `samples: [1]`) shows as an error instead of breaking the app.
  - GROOVE rejects delays over 15 ticks, which SDx cannot hold.
  - Memory no longer grows with every compile.
  - Two settings saved at the same moment no longer collide.
  - 8-bit WAVs of odd length keep their loop and root note.
- **Guitar Pro placeholders are in tune.** The pluck model played up to 35 cents flat on high notes. Import a tab again to get the new placeholder sounds.

## 0.5.1 (2026-09-26)

VultureTracker 0.5.1 fixes what the first listening pass over 0.5.0 turned up.

- **Piano keys on the PAINT and FAUST tabs.** Z–M and Q–U now play the painted picture (as C-5) or the Faust note (at NOTE), pitched per key. The sound is rendered again after every change.
- **RECIPE box.** It grows to fit the whole entry, so keys further down (such as a `resynth:` entry's `block:`) are no longer hidden.
- **Guitar Pro import.**
  - A track at full mixer volume no longer fails to compile (the volume came out as 65 of 64).
  - The placeholder guitar and bass no longer hiss. The string model had a bug, and each note started with a burst of unfiltered noise. Import a tab again to get the new placeholder sounds.

## 0.5.0 (2026-09-25)

VultureTracker 0.5.0 finds and makes sounds. Your sample folders are indexed by timbre so the Tryout can offer the nearest sounds, two new tabs make sounds in the app, and Guitar Pro tabs import as songs.

- **Finding sounds.**
  - Your WAV folders are indexed by timbre, brightness, attack, length, pitch and harmonics. A rescan reads only new or changed files.
  - In the Tryout, ≈ LIKE SLOT and ≈ FIND SIMILAR TO THIS add the library's nearest sounds as candidates, each with its distance.
  - The MAP tab lays the library out by likeness: click a point to hear it, zoom, pan, filter by name, and send it to the candidates. FOLDERS INDEXED chooses what is indexed.
  - On the command line: `index [folders] --like WAV` and `tryout --like WAV`.
- **PAINT tab.** Paint over frequency and time (brightness is level, colour is pan), then play it, send it to a new slot or a candidate, or lay it over a sample as a filter. LOAD IMAGE paints from a picture.
- **FAUST tab.** Write [Faust](https://faust.grame.fr) code, compile it in the page and render notes into a new slot or a candidate. GET FAUST downloads the compiler (about 6 MB) on first use. Recipes can use `faust:` too (needs node).
- **Recipe source `resynth:`.** Rebuilds a target WAV from short blocks of other WAVs, matched by timbre.
- **Guitar Pro import.** GP3, GP4 and GP5 tabs become song files with placeholder sounds to swap in the Tryout: ties, hammer-ons, slides, bends, vibrato, dead and palm-muted notes, harmonics, triplets, tempo changes, repeats and alternate endings. IMPORT A MODULE OR A TAB on the start screen, or `import tab.gp5`. GP6+ files are not read yet.
- **Samples tab.**
  - SLICE AS MULTISAMPLE maps each pitched slice over the keys nearest its note. + PATTERN writes the slices as a pattern at their original timing.
  - LEARN NOISE and DENOISE reduce steady background noise.
  - SLICE's report shows in the tab; after STRETCH, TRUNCATE SILENCE or TRIM the view shows the whole new WAV.
- **RECORD tab.** TAKES → MULTISAMPLE turns recorded takes into one multisampled instrument.
- **Speed.** Faster library indexing on Windows. `VT_WORKERS=3` renders tryout candidates on three workers (15-20 % sooner, but edits reach the live engine later, so it is off by default).

## 0.4.0 (2026-09-25)

VultureTracker 0.4.0 records. A new RECORD tab takes audio from an interface into the song, and the Samples and Pattern tabs gain tools to cut, process and compose with what you record.

- **RECORD tab.**
  - Records from any audio input Windows lists: WASAPI (shared or exclusive), MME, DirectSound, or ASIO. Tick ASIO and restart the app to list drivers such as Focusrite USB ASIO.
  - Takes input 1, input 2, both as stereo, or both mixed to mono. It shows a peak meter per input with clip, a tuner, and up to 0.5 s of pre-roll.
  - Each take is saved beside the song with its silence trimmed and its note found. It then becomes a tryout candidate for the slot, or a new slot tuned to the cent with an instrument that plays it, or stays in the list.
  - Tested on a Focusrite Scarlett Solo (3rd Gen) under WASAPI shared and exclusive and under ASIO, in the exe. Monitoring is the interface's own; the app does not play the input back.
- **Samples tab.**
  - AUTO LOOP proposes loop points for a sustained sound; CROSSFADE LOOP smooths the wrap.
  - SLICE cuts a sample at its hits or into equal parts, as new slots plus a kit instrument.
  - EFFECTS → NEW WAV: gain, low-pass and high-pass, an EQ band, loudness, pitch at the same length, stretch at the same pitch, truncate silence.
  - ▶ HOLD plays a slot at its own note (its base note, or the note its speed sets).
- **Pattern tab.**
  - COMPOSE: GROOVE (a note delay per row for swing), EUCLID (Euclidean rhythms), CHORD (a chord over the channels to the right, 17 shapes with inversions), LAYERS (round-robin or velocity layers).
  - RENDER → SLOT renders the selected rows as they play in the song into a new slot, with their ring-out.
- **Speed.**
  - An edit compiles in about a sixth of the time.
  - Oversampled renders are about three times faster and bit-identical.
  - Faders are heard in the live engine while they move.

## 0.3.0 (2026-09-25)

VultureTracker is now a tracker as well as a compiler: a live engine, pattern and sample editors, MIDI input, and import of MOD, S3M and XM. The RECIPE box renders new samples from Surge XT or Dexed straight from the exe.

- **Live engine.** libopenmpt runs as WebAssembly in the page and plays the song as it stands, unwritten mix included, from any order and row. It has mutes, solo, a metronome, an oscilloscope and pattern loop.
- **Editing.**
  - The Pattern tab edits in place: notes, instruments, volumes and effects, with selections, copy, paste, flood, transpose, interpolate, amplify, find and undo.
  - HUMANIZE moves note volumes at random.
  - ECHO copies a channel's notes into another channel, later and quieter: a tracker delay, in one undo step.
  - The Song, Instruments and Samples tabs edit orders, instruments (envelopes, keymaps) and samples (trim, loops, processing).
- **MIDI.**
  - A keyboard previews notes and, in edit mode, enters them at the cursor, with velocity as the volume.
  - While the pattern plays, notes land on the row that is playing.
- **RECIPE box.**
  - When a sample recipe in the song's folder writes a slot's WAV, the Tryout tab shows its entry. Edit it, render it as a new candidate (never over the original), or write it back into the recipe.
  - If Surge XT (300 MB) or Dexed (10 MB) is missing, the box offers the download. It goes into `%LOCALAPPDATA%\VultureTracker\tools`, then the render runs again.
- **Import.** MOD, S3M and XM as well as IT.
- **Anti-aliasing.**
  - Looped samples are resampled as they play, so loops stay seamless at any storage rate.
  - `check` warns when a note plays a sample far enough below its root to image.
- **Robustness.**
  - The fixes from a full audit, with a test for each: undo covers mix and tryout changes, files are written atomically, and malformed songs, modules and WAVs are reported instead of crashing.
  - The server refuses requests from other web pages and host names.

## 0.2.2 (2026-09-22)

Patch release for the listening loop: the pattern view has its own tab, the notes bar is one button, and a written candidate choice clears its list.

- PATTERN is its own tab: the read-only pattern view, the whole window wide, following the selected order and the playhead. It was a narrow rail in the Song Overview where a few channels fit.
- The notes bar keeps only NOTE… (`N`). Every note lands at the playhead with the channels sounding there; the words are yours.
- `U` (use this candidate for the slot) clears that slot's candidate list once the song is written: the choice is made. Ratings are remembered per file, so a rejected sound shows as rejected if it is added again.
- The repository now carries the first piece of the UT99 tribute suite (`suite/nadir/`) with its generators, samples and listening notes; the exe is unchanged by that.

`synth` and `audition` still need a source checkout with the plugins and packs from `tools/`, as SAMPLING.md describes; the exe does not include them.

## 0.2.1 (2026-09-22)

Patch release for the listening loop: the song file keeps its line endings, notes belong to the version they were made on, a solo lands where you clicked, and playback can be slowed down.

- Fixed: writing the song from the app (U, WRITE MIX → SONG) turned every line ending into CRLF on Windows. The file is now written back with the endings it had. The 0.2.0 exe has this bug; the content it wrote is otherwise correct.
- Listening notes belong to the version of the song they were made against. When the song changes outside the app (a rebuild), the notes on the old version move to `<song>.notes-<hash>.json` and `.md` beside it and the NOTES tab starts empty; the app's own writes keep them, and the report marks their version.
- Soloing or muting while playing (the SOUNDING chips, the stems rail, SOLO IN SONG, UNMUTE) rewinds a second when the new render lands, so the moment you clicked on is heard with the change, even when the render takes a few seconds.
- SPEED in the player slows playback to 75, 50, 33, 25 or 20 % with the pitch kept; the setting survives switching candidates and is remembered.

`synth` and `audition` still need a source checkout with the plugins and packs from `tools/`, as SAMPLING.md describes; the exe does not include them.

## 0.2.0 (2026-09-22)

Anti-aliased renders, a mixer in the app, and listening notes: a way to say what you hear at the playhead without having to describe it.

- Renders are anti-aliased: the mixer runs at twice the output rate and the result is band-limited back down with a windowed sinc (`render --oversample 1` turns it off). A song can set `module: sample_rate: 44100` to resample every sample at compile time, band-limited, so playback in any player neither images nor aliases.
- The Song Overview's stems rail is a mixer: a volume and pan fader per channel, a MIX VOL master showing the peak of what is playing, a GAIN fader per sample slot, and a meter per channel measured with that channel soloed. Every move re-renders the tryout at once (the section is compiled once and the values are patched into the module header). WRITE MIX → SONG shows the YAML change and edits the song in place; EXPORT STEMS writes one WAV per playing channel.
- Listening notes: while the song or a candidate plays, click TOO LOUD, TOO QUIET, HATE THIS SOUND, TOO BUSY, KEEP or NOTE… (`N`). The note records the time, order and row, what was playing, and the channels sounding there with the slot each plays; click the one you mean and add words. Notes live in `<song>.notes.json` and are rendered as `<song>.notes.md`, a report grouped by section for a collaborator who cannot listen; the NOTES tab lists and edits them. Nothing touches the song file.
- The player: a SOUNDING strip under the progress bar shows the channels sounding at the playhead (click one to solo it); the bar seeks on click or drag; SAMPLE ALONE (the candidate's WAV by itself) and SOLO IN SONG (every channel that never plays the slot muted) replace the old SOLO; the slot list marks slots that have candidates; rejected candidates sink to the bottom; the render you are listening to goes first in the queue, a stale meters pass stops itself, and the player says when the old render is still playing while a new one lands.
- Compiles are memoised per sample file, so a song with `sample_rate` compiles in a fraction of a second after the first time; `tryout_song` accepts a song dict.

`synth` and `audition` still need a source checkout with the plugins and packs from `tools/`, as SAMPLING.md describes; the exe does not include them.

## 0.1.1 (2026-09-22)

Patch release: the app's comparisons and overview are now trustworthy on their own promise, and the first-run demo works from a bare checkout.

- The render cache key now stamps every WAV in the mix, not just the candidate. A kit re-rendered in place under the same paths no longer plays back from the old mix. Existing `.tryout/` renders are redone once.
- Order timing in the Song Overview comes from libopenmpt, so speed and tempo changes, pattern breaks (including into the middle of a pattern) and jumps count; an order that never plays reads as 0 s.
- Applying a candidate patches a block-mapping sample slot in place as well as a one-line flow mapping, so comments elsewhere in the song survive. The full re-dump is only the fallback when the slot's lines cannot be found, and the diff still says when that happens.
- The README and GUIDE open `demo2/iron_relay.yaml` first: every sample it needs is in the repository. `demo4/vantage.yaml` still needs the drum renders that live in the gitignored `samples/local/`, as its header explains.
- The song file is the source of truth and each pattern generator is its scaffold: rerunning a generator discards hand edits made to the patterns since (GUIDE, the Vantage header, the generator docstring).

`synth` and `audition` need a source checkout with the plugins and packs from `tools/`, as SAMPLING.md describes; the exe does not include them.

## 0.1.0 (2026-09-21)

First release under the new name. Write tracker music as a YAML file, compile it to an Impulse Tracker module (`.it`), render it to WAV, and audition candidate samples inside the song from the app.

- The tryout app: candidate WAVs rendered inside a section of the song with only one slot swapped, keys 1 to 0 to switch without losing the position, stars, reject and notes per candidate, and a one-line YAML apply with a diff preview.
- Song Overview: a stems rail with mute and solo (the section re-renders without those channels), the arrangement grid and slot table with measurements, a read-only pattern view that follows the selected order and the playhead, and stems export (one WAV per playing channel).
- Render & Export builds the `.it` and verifies it with libopenmpt.
- CLI: `check`, `build`, `render`, `info`, `import`, `synth`, `audition`, `tryout`.
- Four demo songs; the song format is in SONG_FORMAT.md and sample making in SAMPLING.md.

`synth` and `audition` need a source checkout with the plugins and packs from `tools/`, as SAMPLING.md describes; the exe does not include them.
