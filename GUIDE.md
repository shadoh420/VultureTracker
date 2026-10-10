# VultureTracker guide

The short version is [README.md](README.md); this is the long one: the app, the demos, samples, tests and notes.

Write sample-based tracker music as a readable YAML text file and compile it to a real Impulse
Tracker module (`.it`). Every note, instrument, envelope and effect stays visible and editable, by
hand or by an AI.

```
song.yaml ──build──▶ song.it ──render──▶ song.wav
```

## Setup

```
git clone https://github.com/shadoh420/VultureTracker.git
cd VultureTracker
pip install -e ".[all]"
```

Python 3.10+. `pip install -e .` alone installs PyYAML, all that compiling songs needs. The extras add the rest: `gui`
(pywebview, the app in its own window, else it opens in the browser; numpy for measurements, the spectrogram, the
sample editor and resampling; imageio-ffmpeg, the ffmpeg the MP3 / OGG / FLAC export and the FLAC, AIFF, OGG and MP3
samples run), `record` (sounddevice, the RECORD tab), `synth` (pedalboard and mido: `synth` and the app's RECIPE box,
SAMPLING.md), `gp` (PyGuitarPro, the Guitar Pro import), `midi` (mido, the MIDI import), `all` (every one) and `test`
(what the tests need). node runs `faust:` recipes on the command line. On Windows x64, libopenmpt (used to verify and
render) is included in `vendor/`. Elsewhere, install libopenmpt (e.g. `apt install libopenmpt0t64`) or set
`LIBOPENMPT` to its path. `pip install pyinstaller && python tools/build_exe.py` builds `dist/vulturetracker.exe` with
`dist/ffmpeg.exe` beside it. `vulturetracker --version` prints the version; the window title and the start screen show
it too.

**Platforms.** The Windows exe (Windows 10 and 11, x64) is the product. Linux runs from source and is tested on every
push (Ubuntu 24.04, its libopenmpt 0.7; pywebview there needs GTK or Qt, see its docs). macOS is untested. Windows
only: the exe, the RECIPE box's download of Surge XT and Dexed (elsewhere install them: the app finds them in the
platform's VST3 folder and Surge's patches where its installer puts them, or set `SURGE_XT_DIR`, `DEXED_VST3`,
`OBXD_VST3`) and the RECORD tab's ASIO. The app keeps its recent list, library index, window profile and log in
`%APPDATA%\VultureTracker` (macOS `~/Library/Application Support/VultureTracker`, Linux `~/.config/VultureTracker`) and
the downloads in `%LOCALAPPDATA%\VultureTracker` (Linux `~/.local/share/VultureTracker`); the `%APPDATA%` and
`%LOCALAPPDATA%` folders named below are Windows'.

**When something fails.** The app writes what fails unexpectedly, with its traceback, to
`%APPDATA%\VultureTracker\vulturetracker.log` (at most two files of 256 KB; the first line of each start names the
version, libopenmpt's and the system), and the error the page shows ends with that path. Attach the file to a bug
report.

## Usage

```
python -m vulturetracker check demo/arena.yaml                        # validate; errors show file:line
python -m vulturetracker build demo/arena.yaml -o demo/arena.it       # compile, then verify with libopenmpt
python -m vulturetracker build demo/arena.yaml --render demo/arena.wav # compile and render in one go
python -m vulturetracker render demo/arena.it -o demo/arena.wav --repeat 1
python -m vulturetracker info demo/arena.it                           # what libopenmpt sees
python -m vulturetracker import some.xm -o some.yaml                  # existing .it/.xm/.s3m/.mod -> song file + WAVs
python -m vulturetracker import riff.gp5 -o riff.yaml                 # a Guitar Pro tab, with placeholder sounds
python -m vulturetracker import song.mid -o song.yaml                  # a MIDI file, with placeholder sounds
python -m vulturetracker index C:/samples samples                      # index WAVs by timbre (the app's MAP tab)
python -m vulturetracker tryout song.yaml --sample 3 --like kick.wav -k 8 # the 8 sounds nearest kick.wav, in the song
python -m vulturetracker export song.yaml -f ogg --section Loop --loop --stems # RENDER & EXPORT without the app
python -m vulturetracker collect song.yaml ../song-copy --zip           # PROJECT's Collect Samples without the app
python -m vulturetracker sections song.yaml save Intro 0 4              # SONG's named sections (orders 0-3) without the app
python -m vulturetracker checkpoint song.yaml save "Before the mix"     # PROJECT's checkpoints: save, diff, restore, delete
python -m vulturetracker phrase song.yaml capture --order 2 --rows 0-15 --channels 3 # PHRASES: then set, diff, render, accept
python -m vulturetracker undo song.yaml                                # the app's undo (redo; trim-history --keep N)
```

`pip install -e .` also installs a `vulturetracker` command.

## GUI: choosing samples in context

```
python -m vulturetracker gui demo2/iron_relay.yaml
```

opens the app in its own window (`pip install pywebview`; without it, or with `--browser`, it opens in your
default browser instead; either way it is served on localhost and nothing leaves your machine). Run it with
no song to get the open-a-song screen with recent songs and the demos; its NEW SONG makes a song file at the path
given (never over an existing file) with the channels asked for, an empty 64-row pattern and one instrument playing a
one-second tone written beside the song as `<name>_tone.wav` (numbered when that name exists), with `sample_rate: 44100`, and opens it in the Pattern tab. Pick a sample slot and
a section of the song, add candidate WAVs by path or glob, and each candidate is rendered inside the song with
only that slot swapped. Keys `1`–`0` switch candidates without losing the playback position, `S`/`M` toggle
SAMPLE ALONE (the candidate's WAV by itself) vs. IN MIX, SOLO IN SONG mutes every channel that never plays the slot,
stars/reject/notes are kept per candidate beside the song (`<song>.tryout.json`), and `U` shows the YAML change before
writing it; once written, that slot's candidate list is cleared (the choice is made; a file's rating is remembered if it
is added again). With no candidate picked, SONG plays the song itself. Slots that have candidates are marked in the slot list
(`24 arp ▸ 5 candidates`); rejected candidates sink to the bottom of the list (their number keys stay). When a sample
recipe (SAMPLING.md) in the song's folder writes the slot's WAV, a RECIPE box under the candidate input shows that
sample's entry as YAML: edit it (a hold, a note, `params:`, an `fx:` chain) and RENDER CANDIDATE renders it into a new
WAV beside the slot's (`<name>-r1.wav`, `-r2`, …, never over the recipe's own file) and adds it to the candidates, in the
background; WRITE TO RECIPE (click twice) writes the entry as it stands into the recipe file in place (a one-line
entry stays one line with its comment). A candidate rendered this way remembers its entry, so after `U` the box shows
it. Rendering needs what `synth` needs: pedalboard (inside the exe) and the synth. When Surge XT or Dexed is
missing, the box offers GET SURGE XT (a 300 MB download) or GET DEXED (10 MB): the app unpacks it (the exe and a pip install into
`%LOCALAPPDATA%/VultureTracker/tools/`, a checkout into `tools/`) and renders the entry again; OB-Xd is an installer,
linked from the message. The candidate
you are listening to renders first; after a mute or fader change the old render keeps playing until the new one lands
and the player says so. Under the progress bar (click or drag to seek) SOUNDING lists the channels sounding at the
playhead with the slot each plays (a looped tone until its note-off, a one-shot until its sample runs out); click one
to solo it (playback rewinds a second when the soloed render lands, so the moment you clicked on is heard soloed).
SPEED slows playback to 75, 50, 33, 25 or 20 % with the pitch kept (type… takes any value from 10 to 200 %). The
strip just above the progress bar is the playback loop: drag on it to loop a span of what plays (snapped to rows),
click it to clear the loop; LOOP FROM / TO under SECTION TO LOOP takes the span as order and row numbers (the orders
of the song, `to` inclusive). The loop is playback only: the render stays the section, so switching candidates or
moving a fader keeps the loop and no render waits on it; it works for the song and for every candidate whenever the
span lies inside the rendered section (otherwise it says so), jumps back within a few milliseconds of its end, is kept
in `<song>.tryout.json` and recorded with listening notes. The SPECTRUM tab is the spectrogram of the render that is
playing (the song or a candidate in it, with the mutes and the unwritten mix), computed by the app from that WAV: time
across with the order boundaries marked, aligned with the playhead (click or drag to seek), frequency up in Hz on a
LOG axis (20 Hz to 22 kHz) or a LIN one (where imaging and aliasing near the top show), colour = level in dBFS from
-100 to -10 (a full-scale sine is 0 dB); each band shows its loudest bin, so a narrow tone between bands is not lost.
REFERENCE sets another recording under it (a WAV, MP3, FLAC, OGG or anything ffmpeg reads: a track being transcribed,
or a mix to match), kept with the tryout settings. OFFSET is how much later the song starts than the reference, in ms
(reference time = song time − offset; negative: earlier); ALIGN finds it by cross-correlating the onsets of what plays
and of the reference within 30 s of the current offset (music repeats, so a beat or a bar off can score nearly as well:
check by ear and nudge it). REF shows the reference over the span that plays (a section is cut from where it starts),
its overall level matched to the song's; DELTA shows the song's level minus the reference's in each cell, −30 to +30 dB
(red: louder in the song, blue: quieter, black: silent in both), with the mean |Δ| of each order at the top and the
median of the whole span, the gain put on the reference and how much of the span it covers beside CLEAR. DELTA
compares sound, not notes: placeholder or different sounds differ even where every note is right
(`tools/transcription_diff.py` scores the notes).
The Song Overview tab has a stems rail that is also a mixer: mute or solo channels, a volume and pan fader per
channel, a MIX VOL master with the peak of what is playing, and a GAIN fader per sample slot in the slot table (click
any fader's number, or an instrument-panel value, to type it: Enter applies it the way the fader would, clamped to the
song format's range, Escape cancels; a pan takes 0–64, L50, R20, C or S for surround); every
move re-renders the tryout at once (the section is compiled once and the values are patched into the module's header),
and the meter next to each channel is that channel soloed, its RMS in dB over the active part of the section (the way
the suite's comparison script measures a module: `compare.py` in `scratch/ut99-clean/`, which is local only and not in
the repository). Nothing is written until WRITE MIX → SONG, which shows the YAML
change first (`module.channels` volume/pan, `mix_volume`, the sample's `global_volume`, edited in place).
EXPORT STEMS and EXPORT SONG AS open the unified RENDER & EXPORT panel: choose destination, format, region, mix,
audition mute/solo behavior and tail before starting. The tab also has the arrangement grid and the slot table. The Pattern tab is the
pattern view and editor, the whole window wide, following the selected order and the playhead. It has a cursor (click a
cell; the arrows, Tab, Page Up/Down, Home and End move it through rows, channels and the note, instrument, volume,
effect letter and effect parameter columns) and the LIVE transport: libopenmpt compiled to WebAssembly plays, in the page's
own audio thread, the whole song as it is now with the unwritten mix. ▶ FROM CURSOR (Space, F7; Space again stops,
and the cursor stays where it stopped; a double-click on a row plays from there), ▶ SONG from the start, ↻ PATTERN
(F6) loops the pattern at the cursor, ■ (F8) stops. The view follows what plays, the channel headers show each
channel's level, SOUNDING lists what sounds, NOTE… drops a note at the live position (N in the other tabs). Mutes and
solo from the stems rail,
the playback loop (LOOP FROM / TO) and SPEED act on it at once, without a render; a fader, the instrument panel or a
change to the song file recompiles the song and swaps it in where it plays. The piano keys (Z to M and Q to U, two
octaves from OCT) preview the PREVIEW instrument: on the song while it plays, alone while stopped; in the Pattern tab
they take the place of the app's letter keys (M, S, N, U, X), and the NOTE… button still drops notes.

**Editing patterns.** Esc (or ● EDIT) turns on edit mode. In the note column the piano keys enter a note with the INS
instrument (and preview it) and move the cursor down by STEP rows; `1` enters a note cut (`^^^`), `` ` `` a note-off
(`===`), Shift+`` ` `` or `\` a fade (`~~~`), OpenMPT's IT-style keys (by their place on the keyboard). Digits type the instrument (two digits), the volume column takes a command letter (v p a b c d e f g h) and
two digits, the effect columns an effect letter and two hex digits; values are clamped to their range. Delete or . clears
the column under the cursor; Insert pushes the channel down from the cursor, Backspace pulls it up. Each change shows
at once and is written into the song file in place: only that row's cell changes (the other cells, the row label, the
comments and every other line stay as they are; rows the pattern leaves implied are written out when a later row is
edited). Before anything is written the whole song is compiled: a change the song format refuses (an instrument that
does not exist, say) is not written and the bar says why. Ctrl+Z / Ctrl+Y (↶ ↷) undo and redo the edits of this
session and previous launches (up to 200 steps). An undo also puts back the tryout settings the step changed: after a channel is removed or moved its mutes and
unwritten faders are back on the channel they were set on, WRITE MIX undone brings the unwritten mix back, U undone the
slot's candidate list. Edits are refused while the song file has changed on disk (RELOAD first), so they never overwrite a change
made elsewhere. While the live engine plays, each edit is swapped in where it plays (about 0.35 s for Nadir) and the
view stays on the pattern being edited. A song whose patterns are written by a generator loses these edits when the
generator is rerun. For quoted or compact patterns, click MAKE EDITABLE to write their compiled cells as a
literal `data: |` block. This is one undo step; undo restores the original notation. Conversion replaces that
pattern's notation and its internal comments; a flow-style `patterns: {...}` mapping is expanded as a whole.

**MIDI input.** Click MIDI in the live bar to switch MIDI input on: the first time, the window asks whether the page
may use MIDI devices (Allow; the answer is kept, and MIDI stays on at the next launch until it is clicked off). A MIDI
keyboard plugged in before or while the app runs is then picked up through the page's Web MIDI, and the live bar shows
its name next to MIDI and VEL→VOL. Its keys play like the piano
keys, MIDI note 60 being C-5: a preview through the live engine (the INS instrument; in the Instruments tab the
instrument on show, in the Samples tab the slot), at the key's loudness with VEL→VOL; releasing the key releases the
note. On the Faust tab they play the Faust code instead (see there). In edit mode on the Pattern tab each key also
enters its note at the cursor with the INS instrument, and with VEL→VOL its velocity as the volume column (v01-v64),
then the cursor moves STEP rows. While the live engine plays the pattern on show, a key records instead: its note goes
into the cursor's channel at the row playing when it went down, and the cursor follows (the piano keys on the
computer keyboard record the same way). With CHORD checked, a note arriving within 60 ms of the one before joins its chord (timed from each
note, so a rolled chord stays one), and the chord is captured together, lowest first, across consecutive channels starting at the
cursor, the computer's piano keys too; with Shift held (OpenMPT's chord modifier) every key struck joins the chord,
written when Shift is let go, CHORD checked or not. The chord is one undo step and advances STEP only once. If it
needs more channels than remain, nothing is written and the selection bar explains why. Uncheck CHORD for
one-note-at-a-time entry. The app serves its page from port 8723 when that is free (another app window takes any free
port) and keeps the window's browser profile in `%APPDATA%\VultureTracker\webview`, so the page's own settings (speed,
latency, hex rows, MIDI, UI scale) and the MIDI permission
carry over from one launch to the next. UI SCALE, at the right of the top bar and on the start screen, makes the whole
app larger or smaller (90 to 200 %): the app's window has no Ctrl+wheel or Ctrl+= zoom of its own (pywebview turns
WebView2's off), and the page's sizes are fixed pixels.

**Following OpenMPT.** Where the app does something OpenMPT also does, it does it OpenMPT's way, checked against
OpenMPT's source. The piano keys go by their place on the keyboard, not the letter printed on them, as OpenMPT's
IT-style keys do (the bottom-left letter key is C on QWERTY, QWERTZ and AZERTY alike), and so do note cut (`1`),
note-off (`` ` ``) and fade (Shift+`` ` `` or `\`). CHORD joins a note struck within
60 ms of the one before (OpenMPT's Auto Chord Wait Time, 60 ms by default, timed from each note), and Shift is the chord
modifier. COPY and PASTE use OpenMPT's clipboard rows; an MPTM parameter-control event (PC), which an IT module cannot
hold, pastes as `Zxx` with its value scaled to 00-7F and the rest of the cell empty, as OpenMPT converts it. The MIDI
import keeps at most 16 ticks a row, as OpenMPT's does, and the last of several tempos on one tick. A FLAC, AIFF, OGG
or MP3 sample keeps what OpenMPT's loaders keep from it (its loops; a FLAC's root note), above. The mix plugins
(`module: plugins:`, the RACK tab) are OpenMPT's nine built-in DMO effects with OpenMPT's parameters, units and defaults
(soundlib/plugins/dmo), saved in the .it as OpenMPT saves them (the FXnn and CHFX chunks of Load_it.cpp's
SaveMixPlugins, each plugin's output routed to master or to the next plugin); `module: macros:` sets the SFx macros
of the embedded MIDI configuration over OpenMPT's defaults (SF0 cutoff, Z80-Z8F resonance), and a plugin parameter's
macro is OpenMPT's `F0F` + (0x80 + the parameter's index) + `z`. Deliberate
differences: the MIDI import reads track names written as UTF-8 as UTF-8 (OpenMPT reads them as Latin-1, so they come
out garbled there), keeps the file's time signatures (OpenMPT imports every file as 4/4), makes a marker a named
section where OpenMPT names a pattern, and bends no drums (their keys are kit pieces here); its bends, pedal and the
module import's name character sets are OpenMPT's (above); a sample's root note (a
WAV's or a FLAC's `smpl` unity note) becomes the slot's `base_note` when the sample is put in a slot, where OpenMPT
keeps it only as a label and plays every file at its own rate on C-5. The piano roll (ROLL) is VultureTracker's own:
OpenMPT has none. Any other difference from OpenMPT is a bug.

**Conveniences.** F5 plays the song from its start, F6 loops the pattern at the cursor, F7 plays from the cursor and F8
stops, in every tab (F5 no longer reloads the page). METRO in the live bar clicks on every beat while the live engine
plays, higher on the first row of each bar, by the song's row highlight (rows per beat and per bar, which also draw the
pattern's row lines). Set rows per beat and rows per bar in SONG (1-255 each); the displayed BPM uses that
beat spacing, and these values round-trip through IT imports and exports. They change the grid and metronome,
not playback speed. The click is mixed in the engine, so it lands within a millisecond of the row. The small scope
beside it shows the engine's output. The Pattern tab's hint line says what the volume command and the effect under the
cursor do (from this file's tables in SONG_FORMAT.md). The Song tab's CLEAN-UP lists what the order list never plays:
patterns outside it, instruments no played pattern names, samples no used instrument maps; ✕ removes one (refused, and
the bar says why, while something still uses it), REMOVE ALL UNUSED (click twice) removes them all as one undo step.
WAVs dragged from the file manager can be dropped on a slot in the Samples tab (or on its waveform) to replace the slot's
WAV the way the Tryout's apply does, on the slot list (Samples tab, or SAMPLE SLOTS in the Instruments tab) for new
slots, or on the Tryout's candidate list to try them in the slot. A dropped WAV is saved beside the song under its own
name (the page cannot see where it came from; an identical copy already there is reused, a different one is numbered).
FLAC, AIFF, Ogg Vorbis, Opus and MP3 files are taken wherever a WAV is (dropped, added as candidates by path or glob,
picked for a new slot): each becomes a 16-bit WAV beside the song in the same way, through the ffmpeg the export uses,
and the source file is never touched. What OpenMPT keeps from them besides the audio comes along in the WAV's `smpl`
chunk: from a FLAC the loops and root note of a sampler's embedded RIFF chunks, or its `LOOPSTART` and `LOOPLENGTH`
tags; from an AIFF its sustain and release loops (the release loop is the normal one; like OpenMPT, its base note is
not used); from Ogg, Opus and MP3 nothing (OpenMPT reads no loop tags there).

**Selections and commands.** Drag over cells, or hold Shift with the arrows (and Page Up/Down, Home, End), to select a
block the way trackers do: the first channel from the column the selection starts in, the last up to the column it
ends in, the channels between whole. Ctrl+A selects the pattern (the channels on show), Ctrl+L the cursor's channel; a
plain move or click drops the selection. The SELECTION bar (and its keys) works on the selection, or on the cursor's
cell when there is none: COPY (Ctrl+C; also puts the rows on the system clipboard in OpenMPT's format, so OpenMPT
pastes them), CUT (Ctrl+X), PASTE at the cursor (Ctrl+V: the copied fields overwrite; rows copied in OpenMPT from an IT,
MPTM or S3M module paste too, the first pattern of several, values this notation lacks left empty and counted), MIX (Ctrl+Shift+V: only into empty fields), FLOOD (Ctrl+Alt+V: the clipboard again and again down to the
end of the pattern, e.g. one bar of hats over eight), CLEAR
(Delete), TRANSPOSE by a semitone or an octave (Ctrl+Up/Down, with Shift an octave; INS ONLY limits it to notes whose
cell names the INS instrument; notes stay within C-0..B-9), INTERPOLATE (Ctrl+I: the volume column and the effect,
from the first selected row to the last, per channel, where both ends carry the same command) and AMPLIFY (the
volume column by a percentage; a note without a volume gets one, counted from 64, the usual default) and HUMANIZE
(each note's volume moved at random within ± the given amount, from 64 when it has none, kept within 1–64). ECHO is the
tracker delay: the selected channel's notes (or, with no selection, the cursor's whole channel) are copied into another
channel ROWS later (and TICKS later on top, as `SDx` on each note), each at the given percent of its volume (its own
`vNN`, else the sample's default volume where the cell names an instrument, else the channel's last); in THIS PATTERN or
the channel's notes in every pattern of the WHOLE SONG. The target is a new channel added at the end (`<name> echo`,
panned LEFT, CENTRE or RIGHT; its fader moves it after) or an existing one, where cells that are not empty are left
alone. Song-wide effects (speed, tempo, jumps, breaks, global volume, pattern loops and delays) and pan commands are not
copied, and a copy that would land past its pattern's end is dropped; the bar reports the counts. Run it twice into
channels panned apart (say 3 rows at 60 % to the left, 6 rows at 35 % to the right) for a stereo echo; one or two ticks
with no rows doubles a lead instead. Each ECHO is one step for Ctrl+Z, the channel it adds included. COMPOSE writes plain
cells too, each command one step for Ctrl+Z with a count in the bar. GROOVE delays notes (note-offs too) by a tick count
per row, repeating from the pattern's first row, as `SDx`: `0 2` swings every other row by two ticks, `0 0 2 2` the
eighths of four-row beats; a 0 removes a delay, and a note that carries another effect keeps it undelayed. EUCLID makes
the selected rows of one channel (or, with no selection, the cursor's channel from the cursor down) a Euclidean rhythm
of the cell at their top: HITS spread as evenly as they go over STEPS (3 / 8 is `x..x..x.`), turned left by ROT, a step
every EVERY rows, each hit kept with the given percent (seeded: the same settings write the same cells); the other rows
are cleared. CHORD stacks each note of the selected channel (or the cursor's cell) into the chosen chord over that
channel and the ones to its right, with the note's instrument and volume, INV lowest tones moved up an octave; note-offs
are copied across so the chord ends whole, and a chord that needs more channels than the song has is refused (add them
in the SONG tab). LAYERS rewrites the instrument column of each note: CYCLE takes the listed instruments in turn, note
by note down each channel (round-robin), BY VOLUME picks by the note's volume, the list running quietest to loudest.
GROOVE and LAYERS work on the selected channels (every channel with no selection), in THIS PATTERN or the WHOLE SONG.
RENDER → SLOT renders the selected rows and channels (with no selection: the whole pattern, the channels the mixer lets
through) as they play in the song, with everything before them setting the state and the unwritten mix applied, then
lets the notes ring on for up to TAIL seconds with nothing new struck (cut at the first silence); the WAV is saved beside
the song (`render-<song>-<pattern>-<rows>.wav`, stereo when the channels differ) and added as a new sample slot, ready to
play, slice or edit (resampling). One step for Ctrl+Z. FIND… (Ctrl+F)
finds cells by note, instrument, volume and effect (`*` any characters, `?` one, an empty field anything; F3 or NEXT
the next match, in this pattern or the whole song, on the channels on show) and REPLACE ALL writes the given fields
into every match. Every command is one step for Ctrl+Z, a song-wide replace included.

**The Song tab** edits the song's structure, each change written into the song file in place and undone by Ctrl+Z (or ↶)
in the Pattern tab. SONG SETTINGS: click the title, tempo, speed, global volume, mix volume or stereo separation to
type it (a trailing comment on its line stays). ORDER LIST: click an entry to select it (a double-click, or EDIT ▸, opens
it in the Pattern tab); ◀ ▶ move it, REMOVE, DUPLICATE (the same pattern again after it), CLONE PATTERN (a copy of its
pattern under a new name takes its place, so it can change without touching the other orders that play the pattern),
INSERT or SET a pattern (or a `+++` skip, a `---` end) from the list, NEW PATTERN (empty, the given rows, after the
selected entry). PATTERNS: click a name to rename it (the order list follows) or its row count to change it (rows past a
new end are removed); CLONE; DELETE (click twice) only when no order plays it. CHANNELS: click a name to rename it;
▲ ▼ move a channel (its cells move in every pattern, and so do its tryout mute and unwritten faders); ✕ (click twice)
removes it and its cells in every pattern; + CHANNEL adds one at the end. The order list is written in the layout it
has: on one line (`orders: [a, b]`), or as a block with one `- name` per line, where an entry that stays keeps its
trailing comment and the comment lines above it (a flow list across several lines becomes one line, and is refused when
it holds comments). Patterns are to be written as `name:` with `rows:` and `data: |`, channels one `- {...}` entry per
line and the module as a block, which is how the songs here are written; anything else is refused with the reason.

**The Instruments tab** edits the song's instruments and adds sample slots, each change written into the instrument's
entry in place (one step for Ctrl+Z in the Pattern tab) and swapped into the live engine, so the piano keys (Z to M, Q to
U, from the Pattern tab's OCT) play the instrument on show as it now is. NEW (playing the chosen slot), CLONE and DELETE
(click twice; refused while a pattern plays it). Every field of the song format: name, fadeout, global volume, pan,
random volume and pan, filter cutoff and resonance, pitch-pan separation and centre (click to type; an empty value
turns an optional one off), NNA, DCT and DCA. NOTES → SAMPLE SLOTS: one slot for every note, or USE A KEYMAP for
ranges (C-0..B-4) each playing a slot at its own pitch, transposed (+12) or at one pitch (C-5, for drums); the strip
shows the slot every one of the 120 notes plays. The volume, panning and pitch (or, with `filter`, filter-cutoff)
envelopes are graphs: drag a node, click empty space to add one, right-click a node to remove it; SUSTAIN takes a node
(2) or a span (1-3), LOOP a span, and `carry` and on/off are checkboxes. SAMPLE SLOTS adds a slot for a WAV (typed or
BROWSE…); swapping a slot's WAV stays the Tryout tab's job. Settings the Tryout's INSTRUMENT panel holds unwritten for
an instrument are written or reset there first. A pattern with no notes, and every pattern in edit mode, shows all
its channels.

**The Samples tab** edits a slot's WAV and its entry. The waveform is drawn from peaks the server computes for the span
on show (both channels of a stereo WAV); the mouse wheel zooms around the pointer, Shift+wheel or the bar under it
scrolls, VIEW ALL / SELECTION / LOOP / + / − set the span, and past one frame per pixel the frames themselves are drawn.
Drag on the waveform to select; the info line gives the frames, the selection (frames and time) and the frame under the
pointer. The LOOP (blue, `L`) and SUSTAIN LOOP (amber, `S`) lines are dragged to move them, typed (START, END: frames of
the WAV, as in the song file), set from the selection (SELECTION → LOOP), or switched between off, forward, ping-pong and
the WAV's own loop (`from_wav`); each change is written into the sample's entry in place (a one-line entry keeps its
layout when only plain values change) and is one step for Ctrl+Z (here too). ▶ HOLD plays the slot through the live
engine, with the instrument that plays it (at the note that plays the WAV at its own speed: its base_note, or the
note its c5_speed puts there, C-5 when neither is set) and the song as written, so a loop just
moved is heard once the engine has swapped the song in (the bar says so while it does); letting go is the note-off, so a
sustain loop ends. The piano keys play it too. EDIT → NEW WAV: TRIM TO SELECTION, FADE IN, FADE OUT, NORMALIZE (peak to
full scale), REVERSE and REMOVE DC work on the selection, or on the whole sample when there is none; CROSSFADE LOOP fades
the end of the loop into the audio just before its start (equal power, the length in ms; it needs that much audio before
the loop start). Each writes a new WAV beside the song (`<name>-trim.wav`, numbered, never over an existing file, the
source untouched), points the slot at it and keeps the loops with the audio (a trim moves them, a reverse of the whole
sample mirrors them); undo points the slot back, and the WAVs stay on disk. EFFECTS → NEW WAV work the same way, on the
selection or the whole sample: GAIN (dB), LOW-PASS and HIGH-PASS (Hz, 12 or 24 dB per octave), EQ (one bell band: Hz,
dB, Q), LOUDNESS (the RMS of what sounds brought to a dBFS target, never past full scale), PITCH (semitones at the same
length), STRETCH (percent of the length at the same pitch; loops move with the audio) and TRUNCATE SILENCE (every
silence under the dBFS level and longer than MIN shortened to KEEP). LEARN NOISE takes the selection as a stretch where
only the noise sounds (hiss, hum, the room; at least 50 ms) and DENOISE then turns down every frequency of the selection
(else the whole sample) that is not well above that noise, by up to REDUCE dB (SENS: how far over the noise a sound must
be to stay, 2 = 6 dB); the gain is smoothed so what is left does not warble, the same for both channels, and the phase
is kept. The filters are zero-phase; PITCH and STRETCH are a
phase vocoder with phase locking, the stereo image kept (steep stretches smear sharp attacks a little: slice a drum
loop instead). SLICE cuts the WAV (the selection, else all of
it) AT THE HITS (sensitivity 0–100: higher finds softer hits; each cut 1 ms before its hit, on a zero crossing) or into
EQUAL PARTS: FIND shows the cuts on the waveform, numbered, and SLICE → SLOTS writes exactly those, each slice its own
WAV beside the song (`<name>-slice01.wav`, a 1 ms fade at its end) and a new slot. AS KIT (C-5 UP): each slot keeps the
source's base note, volume and bits, and in a song with instruments a new instrument plays slice 1 on C-5, slice 2 on
C#5 and so on, each at its own pitch (a kit to play the pieces from the pattern). AS MULTISAMPLE: each slice's note is
found, its slot tuned to the cent, and a new instrument plays each slice over the keys nearest its note (slices without
a note are left out; a repeated note gets a slot but no keys), so a recording of single notes becomes one playable
instrument. + PATTERN also writes a new pattern (`<name>_slices`, not put in the order list: INSERT it in the Song tab)
whose cells play the slices in order at their original timing: each on the row its start reaches at the song's tempo
and speed, the ticks left over as a note delay (SDx), from the Pattern tab cursor's channel (two on one row: the next
channel); the timing is kept to the nearest tick (measured: within 8 ms at tempo 125 speed 6, where a tick is 20 ms).
IT note delays hold at most 15 ticks. If the chosen timing needs more, pattern creation is refused with a
request to use speed 16 or less; it never wraps a delay to an earlier tick. What SLICE made is reported in the
tab's top line. One step for Ctrl+Z. A hard cut in the recording (a sound that stops
dead) less than 50 ms before a hit can be taken for the hit (the cut then sits up to that much early): lower the
sensitivity, or slice a selection that starts at the hit (a selection's start is always a cut). PROPERTIES: name, base note or c5 speed
(either replaces the other), default volume, global volume (refused while the Tryout mixer holds an unwritten GAIN for
the slot), default pan, bits, stereo, and the auto-vibrato (type, speed, depth, rate). A value the song format refuses
is not written and the bar says why.

The render
player and the live engine never play at once. LATENCY LOW measured 8 ms of output latency in WebView2 (the status
shows base plus output); LATENCY SAFE (40 ms) is there if playback crackles. Render & Export builds the `.it` (and a WAV)
and verifies it with libopenmpt. Renders are cached in `<song dir>/.tryout/` (the newest 60). They run one at a time;
the environment variable `VT_WORKERS=3` renders three at once (the same bytes, measured 15-20 % sooner for a song and six
candidates, but edits made while they render reach the live engine later).

**The Tuner tab** is a chromatic tuner on the input the Record tab chooses (INPUT, INPUTS, RATE; OPEN on either tab
opens it): the nearest note in scientific pitch (a guitar's low string is E2, a five-string bass's low B is B0), the
same note as a pattern names it (E-3, B-1), a needle from -50 to +50 cents with the green band within 5, and the
frequency. A = 440 Hz; it reads 27 Hz to 4.2 kHz. Between notes the last reading stays, dimmed.

**The Record tab** records from an audio input (an interface such as a Focusrite Scarlett 2i2, or any input Windows
lists) into takes beside the song. INPUT lists the devices with their drivers (on Windows WASAPI, MME and DirectSound;
tick ASIO to list ASIO drivers too, such as a Scarlett's Focusrite USB ASIO, the lowest latency: it takes effect when the
app next starts), INPUTS picks what a take keeps (input 1, input 2, both as stereo, or both mixed to mono), RATE the
sample rate, EXCLUSIVE WASAPI's exclusive mode (the app alone on the device, at its own rate). OPEN starts the meters
(peak per input with a held peak, amber from -6 dBFS, CLIP when a sample reached full scale) and the tuner; the input is
not played back: monitor through the interface itself (a
Scarlett's DIRECT MONITOR switch), so there is no delay to hear. ● REC and ■ STOP make a take, with up to PRE-ROLL
seconds from before the click. Each take is written as a 16-bit WAV in `takes/` beside the song (`<name>-01.wav`,
numbered), its silent edges trimmed (TRIM SILENCE UNDER, keeping 10 ms before the first sound) and its note found (FIND
THE NOTE: written as the WAV's root note), then goes where THEN says: a CANDIDATE OF THE SLOT in the Tryout (heard in
the song, rated, written with U like any candidate), a NEW SAMPLE SLOT (tuned to the cent: its c5 speed makes the note
found play true; in a song with instruments, a new instrument plays it), or KEEP IN THE LIST. TAKES → MULTISAMPLE makes
every take of the session that holds a note a new slot tuned to the cent and one new instrument that plays each over
the keys nearest its note: record single notes (a few across the range), then play them as one instrument. TAKES THIS SESSION lists them (▶ plays one; → CANDIDATE and → NEW SLOT send it on
later). In the Samples tab, AUTO LOOP proposes loop points for a sustained sound (a whole number of its periods late in
its steady part, on rising zero crossings where the waveform matches best); CROSSFADE LOOP then smooths the wrap.
**PLAY ALONG** plays the saved song with the current mixer and mutes through the selected OUTPUT while
recording. Choose the whole song or a named section, 0-16 count-in beats and 1-16 passes. Input and output
must use the same driver/host API and a supported rate. A single duplex stream times playback and capture;
each pass becomes a separate take. PRE-ROLL and silence trimming are disabled in this mode so take starts
retain their placement. At the end, click SAVE TAKES; STOP early keeps the recorded part of the final pass.
The count-in uses the song's initial BPM.

LATENCY MS removes the measured round-trip delay from recorded starts. For CALIBRATE LOOPBACK, connect the
selected output to the selected input, click the button, then MEASURE LATENCY after the pulse finishes. A
clear correlated signal is required; silence is refused. Calibration does not create a take. Disconnect the
loopback to record an instrument, and recalibrate after changing devices, drivers, rate or buffer settings.
The fake-audio backend tests frame alignment and calibration; physical interface latency still needs a
hardware check.

Recording needs `pip install sounddevice` in a source checkout (the exe carries it); `VT_FAKE_AUDIO=1` swaps in a
simulated two-input interface to try the tab without one.

**Finding sounds: FIND SIMILAR and the MAP tab.** The app keeps an index of the WAVs under a few folders (the MAP
tab's FOLDERS INDEXED; until others are added, the checkout's `samples/` and `tools/cc0`), in `library.json` beside the
recent-songs list (`%APPDATA%/VultureTracker`, or `$VT_LIBRARY`). Each WAV is measured once from its first 10 s: its
timbre (the mean and spread of 12 MFCCs), spectral centroid, flatness, attack (10 % to 90 % of its peak), duration,
pitch and, when it holds a pitch, the levels of its first eight harmonics; INDEX NOW (or `vulturetracker index`) reads
only files that are new or changed since (by date and size) and drops files that are gone; folders starting with a dot
(the app's `.tryout` renders) are left out. In the Tryout tab, ≈ LIKE SLOT adds the sounds nearest the slot's own
sample (as many as the number beside it) to the slot's candidates, and ≈ FIND SIMILAR TO THIS (under the chosen
candidate) the sounds nearest that candidate; the slot's sample, the candidates it already has and exact copies are
passed over, and each found candidate shows its distance and what it was found from (≈ 1.41 from kick; under about 2
is close). Distances weigh each feature by its spread over the library; the pitch counts for little (half a unit per
octave), a pitched sound against an unpitched one for more. The MAP tab draws every indexed WAV as a point, placed by
the first two principal components of the same features (near means alike, though two dimensions cannot keep every
distance), coloured by folder; rings mark the slot's sample, its candidates, and the sounds nearest the one chosen.
Click a point to hear it and list its nearest sounds; → CANDIDATE OF SLOT adds it, ≈ ADD ITS NEAREST adds them. The
wheel zooms, a drag pans, a double-click fits the map; the filter dims what does not match a name or folder. From the
command line, `tryout --like WAV -k N` adds the N nearest to the candidates given (or renders them alone). A sample
recipe can also rebuild a sound from blocks of other sounds (`resynth:`, SAMPLING.md); the RECIPE box renders its
edits as candidates like any other entry.

**The Paint tab** (MetaSynth's idea) draws a sound as a picture: rows are frequencies (lowest at the bottom, spread
evenly in log frequency from LOW to HIGH Hz, or ONE ROW PER SEMITONE up from a LOW note), columns are moments over
LENGTH seconds (the tab shows how many of the song's rows that is). BRUSH paints (SIZE is its radius in cells), LINE
draws a straight stroke (a glide), ERASE and a right-drag erase; BRIGHT is the level (full at 100, RANGE dB under
full at 0) and PAN the colour: red left, yellow centre, green right. LOAD IMAGE… (or an image dropped on the grid)
draws any picture over it: its light is the level, red and green the pan. ▶ PREVIEW plays the picture: every row a
sine at its frequency, its level and pan following the row's cells (smoothly between cells), nothing above 18 kHz;
→ NEW SLOT writes it beside the song (`paint-<name>.wav`, peak at -1 dBFS, stereo when the colours differ, the picture
as `paint-<name>.png` beside it) as a new slot (with an instrument in a song with instruments; one undo step) and
→ CANDIDATE adds it to the tryout slot's candidates. AS A FILTER lays the same picture over a sample's spectrum instead:
dark turns that frequency down at that moment (the columns spread over the whole sample, the phase kept); ▶ plays the
slot through it and FILTER SLOT writes it as a new WAV (`<name>-spectral_mask.wav`) and points the slot at it (one undo
step). The picture and its settings are kept in the browser per song. Ctrl+Z undoes a stroke, CLEAR, LOAD IMAGE or a resize (↶ ↷ beside CLEAR; Ctrl+Y or Ctrl+Shift+Z redoes);
the steps last while the app is open.

**The Faust tab** takes [Faust](https://faust.grame.fr) code (EXAMPLE puts back a two-saw voice with a resonant
filter) and compiles it in the page (COMPILE, or Ctrl+Enter; the compiler's message appears under the code). The code
plays polyphonically, a voice per note, the way Faust does it: the controls whose paths end in `freq`, `gain` and
`gate` get each voice's pitch, velocity / 127 and key; every other slider of the code appears under CONTROLS and acts on
all voices (an `effect = ...;` in the code runs once on their sum). NOTE is a note or a chord (`C-5 E-5 G-5`; the first
note is the WAV's root), HOLD holds the gates down, TAIL goes on after their release, VELOCITY is the velocity. ▶ PREVIEW
renders it and plays it; → NEW SLOT writes `faust-<name>.wav` beside the song as a new slot (its base note the first
note; with an instrument in a song with instruments; one undo step), → CANDIDATE adds it to the tryout slot's
candidates. Renders are made offline at 44100 Hz, a voice per note (never stealing one); one over full scale is scaled under it
(the message says so). Each save also writes a `faust:` entry named after the WAV into `faust.yaml` beside the song
(made the first time; SAMPLING.md): the code, NOTE, HOLD, TAIL, VELOCITY and the sliders, with no trim or fade, as the
tab rendered it. So the sound can be rendered again, and the slot's RECIPE box shows the entry, renders it anew and
writes an edit of it, as for any recipe sample. The code in the box is kept with the song (in `<song>.tryout.json`, as
it is typed), so each song opens with its own. Code that does not compile, an `effect` included, gives its error under
the code; the keys and MIDI give it again rather than compiling the same code at every note.

COMPILE also builds a live instrument from the code: the piano keys (Z to M and Q to U, two octaves from OCT) play it
at their own pitch with VELOCITY, a voice per key held (two keys on one pitch, a piano key and a MIDI key, each
keep their own), released when the key is let go; a slider moved while notes
sound acts on them at once. With MIDI on, a MIDI keyboard plays it while the Faust tab is open (and only then: elsewhere
MIDI does what it always does): note on and off with its velocity (VEL→VOL off: VELOCITY), and the pitch wheel and
controllers reach the controls the code maps with Faust's `[midi:pitchwheel]` and `[midi:ctrl n]` (the EXAMPLE's `bend`
follows the wheel, two semitones), and the sustain pedal (CC 64) holds the notes let go, the piano keys' too, until it
comes up (a key struck again under it sounds anew). A controller moves its control's slider too, so PREVIEW and the saves render
what was heard; leaving the tab puts a pitch-wheel control back to its slider, wherever the wheel was let go. It has 16 voices unless the code declares others (`declare options
"[nvoices:8]";`, 1 to 64); a note beyond them takes the oldest voice in release, else the oldest sounding one. It runs at the
sound device's rate and the LATENCY setting of the live bar. ■ silences it at once; leaving the tab or the song releases its
notes (each voice's own release), cut 3 s later. A COMPILE while notes sound releases them on the old code. The compiler (faustwasm, LGPL-3.0, about 6
MB) is fetched from npm on first use with GET FAUST, into `tools/faustwasm` (the exe and a pip install:
`%LOCALAPPDATA%/VultureTracker/tools/faustwasm`). A sample recipe renders the same code with `faust:` (SAMPLING.md; needs
node), chords and phrases too.

**Instrument panel.** Under SLOT, INSTRUMENT shows the instrument that plays the slot (through `sample:`) and what the
tracker does to every note it plays: a volume envelope (ATTACK and DECAY in ticks, SUSTAIN held until note-off; 0 lets
the note die away), RELEASE (the instrument's `fadeout`: how fast a replaced or released note fades), a resonant
low-pass (CUTOFF, 127 = off, labelled with its approximate -6 dB point; RESONANCE) with a SWEEP on every note (FROM and
TO a share of the cutoff, over TIME ticks), and RANDOM VOL per note. The curve above the sliders draws the volume
envelope and the sweep. The settings apply to the song and to every candidate in the slot, re-render the tryout on each
move and belong to the unwritten mix: kept in `<song>.tryout.json`, recorded with listening notes, dropped by RESET (or
RESET MIX) and written into the instrument's line (`volume_envelope`, `fadeout`, `filter_cutoff`, `filter_resonance`,
`pitch_envelope` with `filter: true`, `random_volume`) by WRITE (or WRITE MIX), which shows the change first. An
envelope in the song that the panel cannot draw (more nodes, a loop) is marked custom and stays until one of its
sliders moves. The header folds the panel.

**Listening notes.** NOTE… (`N`) in the bar under the player drops a note at the playhead. A note records the time, order and row, what was playing (the song or a candidate, the
mutes, the unwritten mix) and the channels sounding there (each channel's last note cell with its sample number;
`~` marks a looped tone held from an earlier note); click the chip of the channel you mean and add words if you like.
Notes live in `<song>.notes.json` and are rendered as `<song>.notes.md`, a report grouped by order (the tryout ratings
at the end) for a collaborator who cannot listen; the NOTES tab lists and edits them. Nothing touches the song file.
Notes belong to the version of the song they were made against: when the song changes outside the app (a rebuild), the
notes on the old version move to `<song>.notes-<hash>.json` and `.md` beside it and the NOTES tab starts empty; the
app's own writes keep them, and the report marks their version.

**The Rack tab** shows each channel's chain of mix plugins as devices: OpenMPT's nine built-in DirectX effects
(chorus, compressor, distortion, echo, flanger, gargle, I3DL2 reverb, parametric EQ, Waves reverb; SONG_FORMAT.md
section 3.1). Pick a channel on the left, + ADD EFFECT puts one at the end of its chain; a knob turns by dragging up or
down (Shift: finer) and writes when let go, its number takes a typed value, B bypasses a device, ◀ ▶ move it in the
chain, ✕ (twice) removes it and the chain closes up. A device fed by two channels is a bus: it says which channels share
it, and a change there changes theirs. AUTO under a knob of a channel's first device gives that parameter an SFx macro:
SFx and then Zxx (00-7F) in the channel set it row by row, as OpenMPT does. Each change is one undo step. Only OpenMPT
and libopenmpt play the plugins; other trackers play those channels dry.

**The piano roll.** ROLL in the live bar shows the cursor's channel as a piano roll over the pattern's rows (pitches
up, rows across, bar and beat lines from the song's rows per beat and bar), the other channels' notes dimmed behind it
(GHOSTS) and a lane under it for the volume column. It is the same cells as the tracker grid, edited the same way:
with EDIT on, a click places a note with the INS instrument (dragging right gives it a length, ending in a note-off on
a free row), dragging a note up or down transposes it, a right-click deletes it (its effect stays), Shift+click writes
a note-off, and a click in the lane sets the note's volume. SCALE LOCK puts a click on the nearest note of the song's
key and shades the pitches outside it.

**Agents: the AGENT panel and MCP.** An agent works on the song open in the app through one set of tools
(`vulturetracker/agent.py`): read the song and a pattern, read the owner's selection (the rows and channels selected in
the Pattern tab, with what sounds there), write cells, set the order list, add a pattern, set the tempo, speed, title
or key, set the rack's plugins, measure (below), cue a place in the app and play it, offer WAVs as tryout candidates,
read the listening notes, check the key, undo. No tool moves a fader, a channel's volume or pan, or the mix volume, and
an entry marked approved is refused. Every edit is one undo step, and a pattern an agent writes is marked `by: agent`
(`you and agent` when it had notes before; the owner's later edit of an agent's pattern makes it that too). Two ways in:

- **Claude Code (or any MCP client):** `claude mcp add vulturetracker -- python -m vulturetracker mcp`, then ask it
  about the song open in the app. The MCP server finds the running app through `running.json` in the user folder
  (`--port` names another). Its calls show in the AGENT panel's ACTIVITY.
- **The AGENT panel** (top right): a chat with a model of your choice, optional. SETTINGS picks **Claude Code (your
  subscription)**: the `claude` you are signed in to, run headless with this song's tools as its only tools (no API key,
  no per-token bill; it counts toward your plan's usage; install Claude Code and sign in once first), or the Anthropic API
  (Claude; a stored key, or ANTHROPIC_API_KEY, or an `ant auth login` profile; billed per token; `pip install
  anthropic`) or a local model behind an OpenAI-compatible server with tool calling (Ollama, LM Studio, llama.cpp's
  server: free). A key you enter is kept in the OS credential store (Windows Credential Manager, macOS Keychain, a
  Linux secret service) under the provider's name when the `keyring` package is installed (`pip install keyring`);
  otherwise it sits in plain text in `agent.json` in the user folder, never beside a song, and moves into the store
  the next time the app reads it after keyring is installed. The panel says which. It warns when the base URL is
  remote and not https: the key would travel in clear. With rows selected in the Pattern tab, a message carries
  them ("on 07 Bass · pattern intro · rows 00-15"). The chips under the messages are starting points. The agent's replies show as
  markdown (bold, code, lists, headings, tables); links show their address and are not clickable.

**Free cloud and local chat setup.** In AGENT → SETTINGS, the existing Claude Code, Anthropic API and custom
OpenAI-compatible server choices remain available. The additional presets are:

- **Gemini (free tier available):** create a key at https://aistudio.google.com/apikey, using a project on Google's
  Free tier, paste it in API KEY and SAVE. The default model is `gemini-3.8-flash`; you can type another compatible
  model. Availability and limits depend on Google's current model, region and project quota. Enabling billing on
  that project can incur charges; this preset cannot force a paid project to be free. Google may use free-tier
  inputs and outputs to improve its products. See https://ai.google.dev/gemini-api/docs/pricing. With no stored key,
  the app uses `GOOGLE_API_KEY`, then `GEMINI_API_KEY`. Quota errors stop the request; there is no automatic paid fallback.
- **Ollama:** install from https://ollama.com, download a local model that supports tool calling and start Ollama.
  Select Ollama here, click FIND MODELS, choose a model and SAVE. The default URL is `http://localhost:11434/v1`.
  Avoid cloud models if you want local-only operation. Local inference uses your computer's memory and processing power.
- **LM Studio:** install from https://lmstudio.ai, download and load a model with tool calling, and start the server
  in its Developer tab. Select LM Studio here, click FIND MODELS, choose a model and SAVE. The default URL is
  `http://localhost:1234/v1`. No key is normally needed for either local server; enter one if server authentication
  is enabled. Both URLs are editable. The custom server option still supports llama.cpp and other compatible servers.

FIND MODELS reads the server's model list without sending song data, running inference or saving settings. It confirms
connectivity, not the model's ability to edit correctly. Chat uses the same song tools, approved-content guards and
undo as the other providers. Changing provider, model or server starts a fresh model conversation. Keys remain separate
by provider in the OS credential store, or in the settings file when that store is unavailable. Draft settings stay in
place while the app refreshes.

**Approved and by.** ✓ beside a channel (SONG tab), a pattern (SONG tab's patterns) or a sample slot (SAMPLES tab)
marks it `approved: true` in the song file: the agent tools leave it alone. The patterns table's BY column and the
Pattern tab's title show who wrote a pattern. The marks change nothing in the module.

**Loudness.** OUT in the bar under the player measures the render playing: integrated loudness (LUFS, ITU-R BS.1770-4:
K-weighted, gated), true peak (dBTP, 4x oversampled; red at -0.1 and above) and the stereo correlation of the part that
sounds. `python -m vulturetracker measure song.yaml [--channels 3,5] [--json]` measures a song, module or WAV the same
way; the agents' measure tool also reports the change since its last measure of the same channels and orders. They are
numbers, not a verdict.

**Key, TAP and ALL OFF.** The SONG tab's `key` (e.g. `A minor`, `D dorian`; `module: key:`) is for people and agents:
under it the tab shows the share of the notes in that key and an estimate from the channels that strike three or more
pitches (Krumhansl-Kessler; a channel of drum hits on fixed keys reads low, and its hover lists every channel). TAP
there, tapped four times or more, sets the tempo from the taps for the song's speed and rows per beat. ALL OFF in the
bar under the player stops every sound the app is making.

**Standalone binary:** `pip install pyinstaller && python tools/build_exe.py` produces `dist/vulturetracker.exe`,
the whole CLI with libopenmpt bundled: `vulturetracker.exe gui song.yaml`. Double-clicking it opens the app on its
open-a-song screen; dropping a song file onto it opens that song. Synth rendering (`synth`, `audition`)
still needs the plugins and packs from `tools/` next to a checkout, as described in SAMPLING.md.

## Finishing and sharing a song

1. **New song.** Open NEW SONG, choose a new YAML filename and channels. The tone gets an unused filename;
   existing songs and source WAVs are never replaced. Edit notes in PATTERN; every valid edit saves immediately.
2. **Arrange.** In SONG, name a section with a first order and an exclusive end (0–4 means orders 0 through 3).
   SELECT and LOOP use the whole section; RENAME gives the selected one the Name typed above, where it stands in the
   file. MOVE inserts before the chosen order boundary. DUPLICATE offers shared
   pattern references or independent pattern copies. Repeated names share their notes; **MAKE THIS OCCURRENCE
   UNIQUE** clones just the selected occurrence. Section operations are undoable. `Bxx` jumps follow their original
   target occurrences; independent section copies retarget internal jumps into the copy. Removing a jump destination,
   splitting a named section, or sharing a copy whose internal jumps require different destinations is refused with
   an explanation. Playback loops that cannot remain contiguous are cleared. Historical listening notes keep their
   original song version, position and sounding list.
3. **Compare phrases.** Select rows/channels in PATTERN, open PHRASES and capture two to four alternatives. Without
   a selection, the cursor's channel for the whole pattern is captured. Initially all alternatives contain the same
   cells: write and name your own lines in the textarea (one row per line, `|` between channels). SAVE validates them.
   The absent-line version cuts held notes on the first selected row and adds no notes. Every version keeps the same
   accompaniment, frozen source WAVs, audition mix and mutes; song-wide effects cannot differ. Audition with the
   buttons, record ratings/notes, then YAML DIFF / ACCEPT. Accepting changes only the selected cells, making that
   occurrence unique when needed, as one undo step. A changed song, source WAV or audition setting requires a new
   comparison before acceptance. Changing sounds comes afterwards in TRYOUT. No lines are generated automatically.
4. **Mix and checkpoint.** Set faders, compare, and WRITE MIX when ready. Failed song or related-settings writes
   retain the old document, candidates, mixer and history. In PROJECT save a named checkpoint before a substantial
   change. COMPARE / RESTORE shows its text diff and restores it as one undo step.
5. **Export.** RENDER & EXPORT offers IT, WAV, MP3 (192 kbit/s), OGG (Vorbis quality 6), FLAC and channel stems.
   Choose a destination folder and output name, whole song or named section, saved mix/sounds or current audition
   mix/selected sample, and whether to respect audition mute/solo. A relative destination is taken from the song's
   folder (empty: beside the song). Saved channel mute flags always apply. Playback
   speed and metronome clicks are not exported. Audio can cut at the boundary or keep a fixed ring-out of 0–10 seconds
   (for the whole song when it ends on its last order, a loop back there included; a jump elsewhere ends it in silence);
   stems have identical start frames and lengths, including silent padding. Section audio warms up preceding orders
   for player state. An IT section is an ordinary standalone order slice using the song's initial settings; it does
   not embed already sounding notes from earlier orders. Tail options affect audio, not IT playback.
   **Game loop** exports the section (the whole song without one) for a game engine to loop: the audio is the region's
   second pass, so it starts with what its own end leaves ringing and the seam is continuous; the tail after it is the
   release. WAV marks the loop in a `smpl` chunk, OGG and FLAC in `LOOPSTART` and `LOOPLENGTH` tags (frames);
   MP3 and IT cannot carry it. A region with a position jump (Bxx) before its last pattern is refused.
   The job compiles its snapshot when queued, so later edits and faders cannot change it. Every output is prepared
   before publication; source paths, symlinks and hardlinks are protected. Existing exports require the Replace
   option. An encoder failure or cancellation preserves previous files. Cancellation is checked while rendering and
   before the short publication step; it does not interrupt that step halfway. If a filesystem error prevents rollback,
   the error identifies the folder retaining the previous files. Legacy build and export endpoints use the same guards.
6. **Collect.** PROJECT → Save Copy / Collect Samples creates a new folder (a relative path is taken from the song's
   folder, so `../My copy` lands beside it), optionally `<folder name>.zip` next to it, with relative WAV
   paths, candidates/ratings, current phrase comparison, notes and their archives, and supported sample recipes with
   their file inputs and Faust DSP files. Adjacent attribution/provenance/license files are kept in `credits/`, with
   their asset associations in `project.json`. Duplicate basenames are numbered. Existing destinations are refused. The
   original stays untouched. The new copy starts a fresh undo/checkpoint history; those records remain with the source.
   Named synth patches still require their synth and patch library on the receiving computer. No plugin installers,
   recordings from outside the project references, or sample-library indexes are bundled. Missing samples must be
   relinked first (a missing tryout candidate must instead be removed in TRYOUT or restored): supply explicit
   replacement WAVs in PROJECT, then RELINK (or all missing samples together). This
   changes only `file:` paths, keeping tuning, loop settings and comments (a slot named after its file gets that
   name written as `name:`, so instruments that refer to it still find it); the complete song must compile.

**From the command line.** `sections`, `checkpoint` and `phrase` do what SONG, PROJECT and PHRASES do, and `undo`,
`redo` and `trim-history [--keep N]` what the app's undo, redo and PROJECT's history trim do, on a song the app does not
have open. Without an action they list (sections with their orders; checkpoints with the undo and redo counts; the
phrase comparison with each alternative's cells); `--json` prints the listing (after the action, and a diff as
`diff`) as JSON instead. `sections SONG save|delete|move|duplicate|rename NAME [orders]` (save takes FIRST END, move
and duplicate the order boundary TO; `--shared`; `--as NAME` names the copy, or the new name for rename, which keeps
the section's place and comment in the file); `checkpoint SONG
save|diff|restore|delete NAME`; `phrase SONG capture --order N --rows A-B --channels C[,D] [--count 2-4]`, then
`phrase SONG set|diff|render|accept A-D|absent` (alternatives by place; set takes `--cells FILE` (`-` reads standard input) with one row per
line and `|` between channels, `--name`, `--stars`, `--note`; render writes `-o FILE.wav`, replacing one only with `--replace`). Orders and rows count
from 0, channels from 1, as the app shows them. Each change is an undo step in `<song>.history.json`, so the app
opens on it and can undo it. While the app has the song open, or another command is changing it, the commands that write are refused (exit
code 1; `undo` and `redo` with nothing to take back are too): the app keeps the history and tryout settings in memory
and would write over them. `--wait SECONDS` asks again until then instead of failing at once. Listings, diffs and renders
still work and leave the app's files alone. What the app would show as a notice (undo steps dropped after an external
edit, a damaged history moved aside) the commands print as `note:` lines. The other way round, an app opening a song
that a command is changing, or that another app window has open, waits a moment, then opens it read-only with a
notice: it plays, but edits, checkpoints and settings are not saved.

**Persistence and external files.** The YAML remains the musical source of truth, with comments, BOM and line endings
retained by app writes. `<song>.tryout.json` holds audition settings, candidates and phrase choices;
`<song>.history.json` holds at most 200 compressed undo/redo steps and 32 named checkpoints within a 16 MiB
storage budget. The oldest available undo/redo steps are pruned to fit; named checkpoints are never
automatically deleted. If checkpoints alone fill the budget, delete one in PROJECT. PROJECT displays storage
usage and offers TRIM HISTORY (keep the latest N undo steps, clear redo) and CLEAR UNDO / REDO (keep
checkpoints). Version 0.6 history is read and migrated on the next write; the compressed format requires 0.7.0
or later.
`<song>.recovery.json` is a temporary save journal. On reopening, it only reconciles sidecars when all files match
that transaction; recovery never writes over the YAML. Malformed or conflicting recovery files are kept under unique
`.corrupt-N` or `.external-conflict-N` names with a notice. Restoring history/checkpoints validates source WAV content,
and refuses missing or changed assets rather than silently substituting sounds. History is tied to the song's absolute
location: moving files manually starts a new history and preserves the old sidecar for inspection.

External edits are detected by file content, including edits retaining the same timestamp. COMPARE / RELOAD shows the
app's text against the current disk version. Reload uses the disk version and starts a fresh undo/redo boundary;
named checkpoints remain, and can be explicitly compared/restored. Reopening after an external edit follows the same
rule. Restores never automatically undo newer external work. Historical notes keep their own version context.

**Browser-held settings.** Display/playback preferences, the Faust draft and the Paint picture normally live in that
browser's localStorage (per server address; Paint also per song path). PROJECT can save them into the project sidecar,
and collection includes the current browser's copy. RESTORE PROJECT SETTINGS explicitly applies them in the receiving
browser and reloads the page. Device/MIDI permissions, interface choices and library folders stay local; they are not
portable. New phrase captures share frozen WAVs by content hash under `<song>.phrases/assets/`; unchanged
samples are stored once across captures and slots. Earlier per-capture folders remain readable. Frozen files
are retained for archived comparisons and checkpoints; they are project data, not the disposable `.tryout/`
render cache. Starting another comparison archives the previous comparison there. Ratings are measurements/notes for
your decision, not an automated quality judgment.

## Making samples: synths, recordings, printed effects

`vulturetracker synth recipe.yaml` renders samples from a YAML recipe. A sample comes from a free synth
(Surge XT, Dexed's DX7 or OB-Xd's Oberheim: patch, notes or phrases, hold time) or from a recorded audio file,
such as the CC0 libraries that `tools/fetch_cc0.py` downloads or a royalty-free drum-machine pack. A recipe can print an effects chain into each
sample (reverb, delay, chorus, distortion, 8-bit / low-rate lo-fi) and bake in crossfaded loops.
`vulturetracker audition 'Pads/*'` (or a file glob) lets you hear a whole set of candidates in one WAV, and
`vulturetracker tryout` plays part of a song once per candidate sample, so you can choose sounds in context.
Setup and the recipe format are in **[SAMPLING.md](SAMPLING.md)**:

```
pip install pedalboard mido
python tools/fetch_surge.py            # Windows: portable Surge XT into tools/surge-xt/
python tools/fetch_instruments.py --install-obxd   # Dexed, OB-Xd, drum-machine samples
python tools/fetch_cc0.py              # CC0 recordings into tools/cc0/
python -m vulturetracker synth demo3/kit.yaml
```

## Writing songs

The song format is documented in **[SONG_FORMAT.md](SONG_FORMAT.md)**. It's the full reference,
written so an AI can compose from it alone. A song has `module` settings, numbered `samples`
(WAV files), `instruments` (keymaps and envelopes), named `patterns`, and an `orders` list. Pattern
rows use OpenMPT-style cells:

```yaml
patterns:
  main:
    rows: 16
    data: |
      00: C-5 01 v64 ... | E-3 02 ... ...
      01: ...            | ===
```

Four demos, and a suite:

- `suite/nadir/nadir.yaml`: "Nadir", 3:47 and loopable, the first piece of a suite where each piece is inspired by one
  stylistic group of the Unreal Tournament (1999) soundtrack, this one by its dark, sub-heavy tracks: a driving grid at
  144 BPM (tempo 120, speed 5, 16-row bars) under a dark mood, a sub drone under everything, one pedal throughout
  (G Dorian over one pitch collection), open-fifth synth and recorded string beds, a soft synth lead doubled by a
  violin section as the melody, one moving line at a time under it (a dark arp or a portamento riff with an echo), a
  choir call, and drums with booms and a recorded drum bar chopped in surround. 20 channels, 34 patterns; v6 is the
  last pass, built from the listener's notes (`suite/HANDOFF.md`). Its sounds are additive models (`gen_samples.py`),
  CC0 drums (`gen_drums.py`), CC0 string sections (`gen_strings.py`) and Surge XT patches picked by measurement and
  by ear in the tryout (`cand*.yaml`, `measure.py`, `kit.yaml`, then `gen_floor.py`); `gen_patterns.py` lays out the
  patterns. `PROVENANCE.md` says what it takes from its reference group (descriptions only); `suite/NEXT-PROMPT.md`
  is how the next pieces are meant to be made (one reference track each).
- `demo4/vantage.yaml`: "Vantage", 3:03 and loopable, E minor at 168 BPM (tempo 140, speed 5), in the style of a
  late-90s arena-shooter module: a sub-bass drone holds the tonic under everything, a synth riff on three
  round-robin channels rides over it, chord samples sit low (a minor bed, a major bed that swells once per pattern,
  a three-chord motif with an echo), a choir calls in the build and the break, drums arrive a minute in and leave
  for the break, and there is no lead melody and no chord progression. 16 channels, 32 patterns. The riff and sub
  bass are additive models (`demo4/gen_samples.py`); the beds, motif chords and choir are Surge XT patches rendered
  by `demo4/kit.yaml`; the rhythm bed is a one-bar break played by the CC0 Big Rusty Drums kit (`demo4/gen_break.py`)
  under MusicRadar drum-machine hits (`demo4/drums.yaml`) and demo3's TR-8 renders. Patterns are laid out by
  `demo4/gen_patterns.py`. UT99's Foregone Destruction was the reference for its grid and layer plan;
  `PROVENANCE.md` says what was taken from it and what was changed.
- `demo3/undertow.yaml`: "Undertow", 3:12 and loopable, E minor at 125 BPM, built on what the Unreal
  Tournament (1999) soundtrack modules measure: 16 channels in sample mode at speed 6 (4 rows per beat,
  4-bar patterns), 16-bit samples at 11 kHz (pads) to 22 kHz (bass, lead), 21 distinct patterns over 25
  orders. Its sounds were picked by ear with `tryout`: Roland TR-8 drums, an OB-Xd analog bass and gated
  string machine, a Dexed DX7 string pad, a soft DX7 Rhodes lead with chorus and a long reverb printed in,
  and CC0 cymbals (`demo3/kit.yaml`, `demo3/drums.yaml`). It shows hard-panned L/R channel pairs with small
  `Oxx` offsets (drums) or a one-tick `SD1` delay (lead) for width, per-hit `S8x` hat panning, volume-slide
  (`Dxy`) gating of a sustained chord, and `FF1`/`EF1` detune between pairs. Its patterns are laid out by
  `demo3/gen_patterns.py`. The drum samples can't be redistributed, so building it needs
  `tools/fetch_instruments.py` and `synth demo3/drums.yaml` first.
- `demo2/iron_relay.yaml`: "Iron Relay", 55 s, D minor at 140 BPM, modelled on late-90s
  arena-shooter modules. It has 16 channels at speed 3 (32nd-note grid). Its 15 samples are
  rendered from Surge XT by `demo2/kit.yaml`. It shows the classic techniques: a sequenced arp
  phrase chopped with `Oxx` and transposed per chord, `Zxx` filter sweeps, a multisampled bass
  with portamento slides, crossfade-looped stereo pads, a reverse-cymbal riser, `Qxy` snare rolls,
  note-delay swing, and echo channels. Its patterns are laid out by `demo2/gen_patterns.py`.
- `demo/arena.yaml`: the first, simpler 42-second demo with procedurally generated placeholder
  samples. Its patterns are laid out by `demo/gen_demo.py`.

Each generator holds the musical choices (chords, rhythms, melodies) as Python data and rewrites the
patterns in its song file. The song file is the source of truth and the generator is its scaffold: rerunning it
discards any hand edits made to the patterns since, so either keep composing in the generator or stop rerunning it.

## Using your own samples

The WAVs in `samples/surge/` are rendered from Surge XT, those in `samples/demo3/` from OB-Xd, Dexed
and CC0 recordings (credited in `samples/demo3/ATTRIBUTION.md`), and those in `samples/demo4/` are additive
models measured on a reference module plus a break played by a CC0 drum kit (`samples/demo4/ATTRIBUTION.md`);
see above. `samples/local/` holds renders of
samples that may not be redistributed and is gitignored. The ones directly in `samples/`
are procedurally generated placeholders (`samples/gen_placeholders.py`).
To use real ones, change a sample's `file` in the song. Also set `base_note` to the pitch recorded
in the WAV, and `loop` if it should sustain (`loop: from_wav` uses loop points saved by a sample
editor). Then `check` and `build`.

## Provenance

`PROVENANCE.md` tracks every sound or figure that was derived by measuring material we do not own (the UT99
reference modules for demo4), how far each is from the original, and what replaces it before a release.

## Tests

```
python -m unittest discover tests
python tests/fetch_fixtures.py   # optional: downloads OpenMPT's IT test modules for the import round-trip test
```

## Notes

- Output is IT 2.14 format (instrument mode when the song has `instruments:`, else sample mode) with uncompressed 8/16-bit samples, playable in
  OpenMPT, Schism Tracker, Impulse Tracker and anything built on libopenmpt.
- Anti-aliasing. WAV renders are mixed at twice the output rate and band-limited back down with a windowed-sinc
  low-pass (`render --oversample 1` turns it off), so content the mixer produces above the output's Nyquist frequency
  is removed instead of folding into the audible range. Two things still create false frequencies inside a module:
  playing a sample far above what its content allows (its bandwidth times the transposition ratio should stay under
  about 18 kHz: a sample 4.5 kHz wide may play two octaves up, one 9 kHz wide one octave; render multisamples with
  `notes:` and a keymap for the rest), playing a bright sample more than about three semitones below its root (`check`
  warns when the images of its lowest note come within 60 dB), and low-rate samples interpolated by the player (the module setting
  `sample_rate: 44100` resamples every sample to the playback rate at compile time, band-limited, which removes that
  imaging in every player at the cost of file size). `vulturetracker/resample.py` holds the resampler.
- `import` also reads Guitar Pro tabs (.gp3, .gp4, .gp5; `pip install pyguitarpro`, LGPL-3; the app's IMPORT A
  MODULE OR A TAB takes them too), with placeholder sounds to swap in the tryout (`vulturetracker/gpimport.py`): a
  plucked-string multisample for guitars (basses a darker one; a sample every octave, played at most 2 semitones under
  and 9 over its root) and a small synthesised kit on the General MIDI drum keys. A pitched track gets a channel per
  string it uses, a drum track one per note of its fullest beat, a tempo change a channel of its own (Txx). The grid is
  the coarsest that holds every beat (4 rows a quarter for sixteenths, 6 or 12 with triplets, up to 48), with speed and
  tempo chosen so a row lasts what it lasts in the tab (the header's BPM readout assumes 4 rows a beat, so it reads
  high on a finer grid). Measures become patterns (identical ones shared) and the repeats and alternate endings are
  played out into the order list. A note lasts its beat (a note-off where it ends) unless it rings on or is tied; palm
  mutes and staccato last half, dead notes are cut after a tick (SC1), ghost notes are quieter; velocity goes to the
  volume column; bends and the whammy bar become pitch slides row by row (E and F), slides between notes E and F over
  the first note (a legato slide's target not struck again), hammer-ons and pull-offs a GFF on the next note, vibrato
  H, natural harmonics their pitch. Grace notes, trills, tremolo picking and mix-table volume and pan are left out and
  counted in the warnings.
- `import` also reads MIDI files (.mid, .midi, type 0 and 1; `pip install mido`; the app's import takes them too) with
  the same placeholder sounds (`vulturetracker/midiimport.py`; basses, programs 33-40, get the darker one, drums on MIDI
  channel 10 the kit). Each MIDI channel of a track gets as many channels as it sounds notes at once, drums a channel per
  key, a tempo change a channel of its own. A quantised file gets the coarsest grid that holds every note start and bar
  line (up to 12 rows a quarter); a played-in one gets sixteenths at speed 6 with each note delayed (SDx) to the nearest
  of 24 ticks a quarter. Bars (from the time signatures, 4/4 without one) become patterns, identical ones shared; a note
  ends with a note-off at the row nearest its end; velocity goes to the volume column, a channel's volume and pan
  before its first note to the channel. Past 64 channels the least used are left out. As OpenMPT's MIDI import does,
  pitch bends become E (down) and F (up) slides on the rows where the bend changes, while a note sounds: extra-fine
  under a quarter semitone, fine under a semitone, else over the row's ticks, each row making up what the slides
  before it rounded off; the bend range comes from RPN 0 (2 semitones until it is set; CC 121 resets it and the bend),
  and a note struck under a bend starts on the bend's nearest semitone. The sustain pedal (CC 64 at 64 or more) holds a
  note that is let go until the pedal comes up, an all-notes-off (CC 120 or 123), or the same key is struck again.
  Markers and cue points become named sections, each from its bar to the next one's (OpenMPT names the pattern they
  fall in; here bars that sound alike share a pattern, so the name goes on the span). Later volume, pan and other
  controller changes are left out and counted in the warnings.
- `import` keeps patterns, instruments, envelopes and samples, and names as written (IT, S3M and XM names read in CP437,
  or Windows-1252 when OpenMPT saved them, MOD names in the Amiga's Latin-1, as OpenMPT reads them; letters IT cannot
  hold lose their accents, ß becomes ss). It keeps OpenMPT's mix plugins when they are its built-in DMO effects, the
  SFx macros and OpenMPT's channel names; it drops other plugins, fixed Zxx macros other than the default resonance
  ones, other OpenMPT-only extensions, an IT's edit history,
  its MIDI pitch wheel depth and its instruments' MIDI channel, program and bank (all for MIDI output), each with a
  warning. It also reads XM, S3M and 31-sample MOD files (`vulturetracker/modreader.py`,
  told apart by their headers; the app's start screen has IMPORT A MODULE, which writes `name.yaml` and `name_samples/`
  beside the module and opens it). Each is mapped onto IT the way it plays in libopenmpt, measured against it
  (`tests/test_modimport.py` renders small modules both ways): ProTracker and FastTracker 2 effects to their IT letters,
  notes to IT's C-5 = the sample's c5 speed (MOD samples at the PAL Amiga rate, 8287 Hz), IT's old-effects mode for
  vibrato and tremolo, MOD channels at a quarter and three quarters of the pan, Scream Tracker 3's shared effect memory
  written out, XM's per-instrument samples as one list with relative note and finetune in each c5 speed, XM key-offs on
  instruments without a volume envelope as note cuts, XM envelope loops a tick shorter, patterns longer than IT's 200
  rows split into 192-row parts (the order list, jumps and breaks follow), and only what the song plays kept when it has
  more than 99 instruments or samples. The mix volume is measured: libopenmpt mixes each format (and XMs by the tracker
  that saved them) at a level of its own, so the import renders the original and the converted module and sets the mix
  volume to match. What IT cannot say is dropped and listed at the top of the song file (Amiga filter, finetune and
  invert-loop commands, AdLib instruments, slow XM pan slides rounded); a pan law of its own (MilkyTracker files) and
  XM vibrato phases a tick apart are not converted. Measured locally on 7 MODs, 7 S3Ms and 19 XMs from the Mod Archive
  and elsewhere (those files are not in the repository, so this cannot be re-run from a checkout; `tests/test_modimport.py`
  is what can), the imported songs play within a median 0.3 dB of libopenmpt's level (the worst file 1.3 dB) over their
  first minute. IT patterns longer than 200 rows (libopenmpt plays up to 1024) are split the same way, and references
  to instruments or samples above 99 are dropped with a warning.
- Renders are as long as the song: its duration times the passes (`render --repeat N`), plus a few seconds for the
  tail. Only a render that repeats forever stops, at ten minutes.
- `vulturetracker/api.py` exposes plain functions (`new_song`, `add_sample`, `add_instrument`,
  `set_pattern`, `set_orders`, `check`, `build`, `render`) for tools and agents.
- The writer follows [ITTECH.TXT](https://github.com/schismtracker/schismtracker/wiki/ITTECH.TXT)
  and was checked against OpenMPT's
  [Load_it.cpp](https://github.com/OpenMPT/openmpt/blob/master/soundlib/Load_it.cpp).
- Bundled libopenmpt is BSD-licensed; see `vendor/LICENSE.txt` and `vendor/Licenses/`.
