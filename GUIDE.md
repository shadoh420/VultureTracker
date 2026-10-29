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
python -m vulturetracker import bank.sf2 --preset 0 -o piano.yaml      # a SoundFont preset (or a GUS .pat) as an instrument
python -m vulturetracker index C:/samples samples                      # index WAVs by timbre (the app's MAP tab)
python -m vulturetracker tryout song.yaml --sample 3 --like kick.wav -k 8 # the 8 sounds nearest kick.wav, in the song
python -m vulturetracker export song.yaml -f ogg --section Loop --loop --stems # RENDER & EXPORT without the app
python -m vulturetracker export song.yaml -f mid                       # the notes as a MIDI file, a track per instrument
python -m vulturetracker collect song.yaml ../song-copy --zip           # PROJECT's Collect Samples without the app
python -m vulturetracker sections song.yaml save Intro 0 4              # SONG's named sections (orders 0-3) without the app
python -m vulturetracker checkpoint song.yaml save "Before the mix"     # PROJECT's checkpoints: save, diff, restore, delete
python -m vulturetracker phrase song.yaml capture --order 2 --rows 0-15 --channels 3 # PHRASES: then set, diff, render, accept
python -m vulturetracker undo song.yaml                                # the app's undo (redo; trim-history --keep N)
python -m vulturetracker synth samples.yaml --only 'bass*'             # render a sample recipe (SAMPLING.md)
python -m vulturetracker surge-params cutoff                           # Surge XT parameter names for a recipe's params:
```

The other commands: `measure` (loudness, true peak and correlation of a song), `audition` (patches or files matching a
glob into one WAV), `mcp` (the agent tools over MCP, below) and `gui` (the app). `python -m vulturetracker <command>
--help` lists each one's options.

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
MATCH LEVEL (off by default) plays each candidate as loud as the slot's current sample so the louder one does not win
by level (in its card, MATCH is the gain it gets, grey while off: the two WAVs' BS.1770 loudness, measured on the WAV
itself with a mono WAV counted on both sides, a loop's body repeated to 3 s and a hit shorter than 400 ms padded with
silence; in the mix a boost is played by lowering every other sample and raising the render, which clips, as the peak
shows, where the song is already near full scale; alone, every matched copy plays 12 dB down so a boost does not clip;
it is playback only: the song, the faders, WRITE MIX and what `U` writes stay as they are),
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
Under the order labels a strip gives each order's meters (S · r): the highest short-term loudness in it (EBU R128, the
3 s before each 0.1 s; LUFS) and the stereo correlation of its span (1 mono, 0 unrelated, below 0 out of phase); OUT
adds the loudness range of the whole render (LRA, EBU Tech 3342, LU). The agent's `measure` returns the same per
order (`per_order`). Numbers, not a verdict. REFERENCE sets another recording under it (a WAV, MP3, FLAC, OGG or anything ffmpeg reads: a track being transcribed,
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
pattern view and editor, the whole window wide. All channels are shown by default, including empty ones;
scroll horizontally to reach more channels, or choose **ACTIVE** to filter them. The cursor scrolls horizontally
as you move between channels. Larger text, channel dividers and distinct beat, measure, cursor and playback
highlights keep the grid readable. **Advanced** expands the selection, automation and composition controls;
it starts collapsed, and the editing shortcuts still work while it is closed.
**Continuous song** is on by default: the bars/patterns in the order
list stack vertically, with one scrollbar through the entire song. Several short bars fit together in the pane.
Click any visible row to edit that pattern occurrence; Up/Down and Page Up/Down continue into adjacent patterns.
Manual scrolling pauses **Follow playback**; re-enable it to follow the playing row. The song-position selector
still jumps directly to a bar. Turn off Continuous song for the single-pattern view. This is a view of the existing
patterns, not a merge: editing a repeated pattern still affects its other occurrences, using the shared Undo history.
It has a cursor (click a
cell; the arrows, Tab, Page Up/Down, Home and End move it through rows, channels and the note, instrument, volume,
effect letter and effect parameter columns) and the LIVE transport: libopenmpt compiled to WebAssembly plays, in the page's
own audio thread, the whole song as it is now with the unwritten mix. ▶ FROM CURSOR (Ctrl+F6; a second click on the button stops,
and the cursor stays where it stopped; a double-click on a row plays from there), ▶ SONG from the start (F6), ↻ PATTERN
loops the pattern at the cursor from its row (Ctrl+F7; F7 from the pattern's first row), ■ (Esc) stops; F5 plays and
pauses, F8 pauses (OpenMPT's keys: Following OpenMPT, below). The view follows what plays, the channel headers show each
channel's level, SOUNDING lists what sounds, NOTE… drops a note at the live position (N in the other tabs). Mutes and
solo from the stems rail,
the playback loop (LOOP FROM / TO) and SPEED act on it at once, without a render; a fader, the instrument panel or a
change to the song file recompiles the song and swaps it in where it plays. The piano keys (Z to M and Q to U, two
octaves from OCT) preview the PREVIEW instrument: on the song while it plays, alone while stopped; in the Pattern tab
they take the place of the app's letter keys (M, S, N, U, X), and the NOTE… button still drops notes.

**Editing patterns.** Ctrl+Space (or ● EDIT) turns on edit mode. In the note column the piano keys enter a note with the INS
instrument (and preview it) and move the cursor down by STEP rows; `1` enters a note cut (`^^^`), `` ` `` a note-off
(`===`), Shift+`` ` `` or `\` a fade (`~~~`), OpenMPT's IT-style keys (by their place on the keyboard). Digits type the instrument (two digits), the volume column takes a command letter (v p a b c d e f g h) and
two digits, the effect columns an effect letter and two hex digits; values are clamped to their range. Delete or . clears
the column under the cursor; Insert pushes the channel down from the cursor, Backspace pulls it up. Enter keeps the
field under the cursor (in the note or instrument column the note and its instrument, which becomes INS) and Space
writes it back into the same column at the cursor and moves STEP rows on (OpenMPT's Cursor Copy and Cursor Paste). Each change shows
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
pattern's notation and its internal comments; a flow-style `patterns: {...}` mapping is expanded as a whole. SPLIT
HERE makes the rows from the cursor's on (row 1 or later) a new pattern, named after this one with `_2` (or the next
free number), played right after every order that plays this one, which keeps the rows above the cursor; a section
around those orders takes the new order in, a jump (`Bxx`) follows the orders it pointed at, and an approved pattern
refuses it. One step for Ctrl+Z.

**MIDI input.** Click MIDI in the live bar to switch MIDI input on: the first time, the window asks whether the page
may use MIDI devices (Allow; the answer is kept, and MIDI stays on at the next launch until it is clicked off). A MIDI
keyboard plugged in before or while the app runs is then picked up through the page's Web MIDI, and the live bar shows
its name next to MIDI and VEL→VOL. Its keys play like the piano
keys, MIDI note 60 being C-5: a preview through the live engine (the INS instrument; in the Instruments tab the
instrument on show, in the Samples tab the slot), at the key's loudness with VEL→VOL; releasing the key releases the
note. On the Faust tab they play the Faust code instead (see there). In edit mode on the Pattern tab each key also
enters its note at the cursor with the INS instrument, and with VEL→VOL its velocity as the volume column on OpenMPT's curve (the velocity
squared: 32 gives v04, 64 v17, 96 v37, 127 v64),
then the cursor moves STEP rows. While the live engine plays the pattern on show, a key records instead: its note goes
into the cursor's channel at the row playing when it went down, and the cursor follows (the piano keys on the
computer keyboard record the same way); with QUANT above 0 it goes to the nearest multiple of QUANT rows instead
(Following OpenMPT, below). With REC OFF checked (kept for the next launch), letting go of a key in edit mode writes a
note-off on the channel its note went to (each note of a chord on its own channel): `===` in a song with instruments,
`^^^` with samples only, at the row playing while the song plays (QUANT applies) or at the cursor while it is stopped,
so a held note gets its length. It never overwrites a cell with a note, instrument or volume; a key tapped and let go
within one row while the song plays puts its note-off one row on; a release after a newer note went to that channel is
ignored. With CHORD checked, a note arriving within 60 ms of the one before joins its chord (timed from each
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
OpenMPT's source. TAB / SCORE has contextual TuxGuitar-style fret commands; Pattern keeps these OpenMPT bindings.
Continuous Up/Down and Page Up/Down follow `View_pat.cpp`'s adjacent-order row wrapping. The continuous display
extends the neighbouring-pattern view through the entire order list; selection ranges remain within one pattern.
TAB deliberately retains the app-wide F5–F8 transport instead of TuxGuitar's conflicting function-key defaults.
The piano keys go by their place on the keyboard, not the letter printed on them, as OpenMPT's
IT-style keys do (the bottom-left letter key is C on QWERTY, QWERTZ and AZERTY alike), and so do note cut (`1`),
note-off (`` ` ``) and fade (Shift+`` ` `` or `\`). CHORD joins a note struck within
60 ms of the one before (OpenMPT's Auto Chord Wait Time, 60 ms by default, timed from each note), and Shift is the chord
modifier. QUANT in the live bar is OpenMPT's record quantize (`recordQuantizeRows`, View_pat.cpp `QuantizeRow`): a note
or chord recorded while the song plays goes to the nearest multiple of QUANT rows, a tie to the later one; past the
pattern's end it goes to row 0 of the next order's pattern (of the same pattern while F7 loops it, as with OpenMPT's
pattern loop; the last row when no order follows); and where the cell
already holds a note it goes one row on (OpenMPT's grace note), voice by voice. INTERPOLATE is OpenMPT's `Interpolate`
(View_pat.cpp) for the note, instrument, volume and effect columns: its `IsInterpolationPossible` test, its rounding (C's
truncating division with a half-step bias), a two-nibble effect moved nibble by nibble, `D`, `K` and `L` sliding into one
another, and its sweep with no selection. Ctrl+J and Ctrl+K are OpenMPT's: the volume or the effect column alone, in the channels
whose selection covers that column (with no selection, only with the cursor on it). Three deliberate differences: the INTERPOLATE button interpolates every column the selection covers (OpenMPT
has a command per column, of which only volume and effect have default keys); where the note column's
start is empty, OpenMPT reads the end's note into an instrument slot, and the app takes the end's instrument; and an
empty volume end next to a note counts from that note's default volume, where OpenMPT reads the start's. GROW and
SHRINK are OpenMPT's `OnGrowSelection` and `OnShrinkSelection` (Alt+E, Alt+D, its default keys), quirks included: a
grown row dropped past the end leaves the row before its place as it was, and SHRINK's kept row takes the next row's
fields even when that row lies just past the selection. REC OFF is OpenMPT's Record Note Off (`TempStopNote`): the
note-off goes to the channel the note took, at the edit position (the row playing while recording, record quantize
applied), never over a note, instrument or volume, one row on for a key tapped within a row, skipped once the channel's
last note is another, `===` with instruments and `^^^` without (OpenMPT's choice for IT), the instrument and volume left
empty; for a piano key only while the cursor is in the note or instrument column. Two deliberate differences there: one
toggle covers the piano keys and MIDI (OpenMPT has one for each), and no `SDx` is written for the tick the key went up
on (live notes are entered on their row, never a tick, here). SPLIT HERE is OpenMPT's `OnSplitPattern`: the rows from
the cursor's on into a new pattern, the source shortened, the new pattern inserted after every order playing the
source. Two deliberate differences: no `C00` break is written, as an IT pattern here may have 1-200 rows (OpenMPT pads
an IT pattern to its 32-row minimum and breaks it early), and the view stays on the shortened pattern (OpenMPT moves to
the new order). An instrument's `filter_mode` is written as OpenMPT writes its instrument extensions
(`InstrumentExtensions.cpp`): an `XTPM` block right after the last sample's data, where `Load_it.cpp` looks for it, with
the `FM..` property (its code byte-reversed, as OpenMPT writes it), a 16-bit size and a byte per instrument (0xFF
unchanged, 0 low-pass, 1 high-pass); libopenmpt takes the mode at each note whose instrument filter is on
(`HandleNoteChangeFilter`), and the import reads the block back the way the loader does. A SoundFont preset is read as
OpenMPT's `Dlsbank.cpp` reads one: the preset's and the instrument's global zones as defaults, key ranges intersected,
a zone on the same key range as an earlier one left out unless the two are a hard-left and hard-right pair (then one
stereo sample), each key playing the last zone that covers it, the sample's root (or the zone's overriding root) and
its coarse, fine and pitch-correction tuning in 1/128 semitones folded into `c5_speed`, attenuation read at a tenth of
its centibels as the sample's global volume, loops by the zone's sample mode (1 loop, 2 ping-pong, 3 a sustain loop
too), the volume envelope from the delay, attack, hold, decay, sustain and release generators (`ConvertToMPT`, 20 ms a
tick, the sustain point where the decay ends, the release as the fadeout), a pitch envelope where the modulation
envelope moves the pitch by 50 cents or more, new notes off, duplicate notes faded; a GUS patch as `SampleFormats.cpp`'s
`ReadPATInstrument` reads one. Three deliberate differences: OpenMPT ignores velocity ranges (the first zone on a key
range wins), here the zones that sound at the highest velocity are kept and the import says how many were left out; a
drum kit (bank 128) is one instrument with every key (OpenMPT extracts one instrument per key), a zone with scale tuning
0 played at one pitch on its key as OpenMPT's note map does; and a GUS patch's key ranges sit where they sound, two
octaves below OpenMPT's (its `ReadPATInstrument` compares the keys with GF1 note numbers, middle C = 84, while tuning
the sample so C-5 plays middle C). The MIDI export writes what OpenMPT's `mod2midi.cpp` writes: type 1 at 480 ticks a
quarter, a first track with the song's name, message, time signature (rows per bar over rows per beat), each tempo
change (OpenMPT's `GetCurrentBPM`, read from libopenmpt while the song plays) and the global volume as a master-volume
SysEx; a track per instrument played (per sample without instruments) named after it; a tracker channel on MIDI channel
channel mod 15, skipping 10, its pan as CC 10; a note through the instrument's note map, its velocity the volume column
(else the channel's volume) doubled as `ProcessMidiOut` computes it, note-offs at the next note, `===`, `^^^` and `~~~`,
the note-ons of a row after its note-offs, no new note under a tone portamento. One deliberate difference: OpenMPT
plays pitch slides, vibrato and later volume and pan changes into the file as pitch bends and controllers; here they
are left out and counted. Each undo step is named for the operation it undoes, as OpenMPT's `PrepareUndo` descriptions name
its Edit menu's Undo entries (the names are the app's own words). COPY and PASTE use OpenMPT's clipboard rows; an MPTM parameter-control event (PC), which an IT module cannot
hold, pastes as `Zxx` with its value scaled to 00-7F and the rest of the cell empty, as OpenMPT converts it. The MIDI
import keeps at most 16 ticks a row, as OpenMPT's does, and the last of several tempos on one tick. A FLAC, AIFF, OGG
or MP3 sample keeps what OpenMPT's loaders keep from it (its loops; a FLAC's root note), above. The mix plugins
(`module: plugins:`, the RACK tab) are OpenMPT's nine built-in DMO effects with OpenMPT's parameters, units and defaults
(soundlib/plugins/dmo), saved in the .it as OpenMPT saves them (the FXnn and CHFX chunks of Load_it.cpp's
SaveMixPlugins, each plugin's output routed to master or to the next plugin); `module: macros:` sets the SFx macros
of the embedded MIDI configuration over OpenMPT's defaults (SF0 cutoff, Z80-Z8F resonance), and a plugin parameter's
macro is OpenMPT's `F0F` + (0x80 + the parameter's index) + `z`. The agent's first-instrument creation wraps existing
samples at their original instrument numbers, as OpenMPT's `CModDoc::ConvertSamplesToInstruments` does
([Modedit.cpp](https://github.com/OpenMPT/openmpt/blob/master/mptrack/Modedit.cpp)), with identity note maps and
OpenMPT's default fadeout (256 internally, 8 in the IT field). Unlike OpenMPT's conversion prompt, this tool converts
atomically with the new instrument and refuses conversion when material is approved. Agent transposition follows
`CViewPattern::TransposeSelection` (View_pat.cpp): real notes clamp to the format's range, while off/cut/fade stay
unchanged. Agent region copies use field-wise empty-field mixing; unlike UI clipboard clipping, a region that does
not fit is refused whole, and occupied destinations require explicit overwrite. Deliberate
differences: the MIDI import reads track names written as UTF-8 as UTF-8 (OpenMPT reads them as Latin-1, so they come
out garbled there), keeps the file's time signatures (OpenMPT imports every file as 4/4), makes a marker a named
section where OpenMPT names a pattern, and bends no drums (their keys are kit pieces here); its bends, pedal and the
module import's name character sets are OpenMPT's (above); a sample's root note (a
WAV's or a FLAC's `smpl` unity note) becomes the slot's `base_note` when the sample is put in a slot, where OpenMPT
keeps it only as a label and plays every file at its own rate on C-5. QUANT rounds by the row playing, not its tick
(the live engine reports rows), so a note struck late in a row rounds as if struck at its start and QUANT 1 changes
nothing. The piano roll (ROLL) is VultureTracker's own:
OpenMPT has none. So are a pattern's `automation:` lanes: OpenMPT has no such lanes, and a lane compiles to plain cells,
so OpenMPT and libopenmpt see an ordinary pattern. An instrument's `tuning:` reads a Scala `.scl` as OpenMPT's
`ImportScl` does (TuningDialog.cpp: `!` comments, a `.` makes cents, `a/b` or a whole number a ratio, at most 256 notes)
and, with no `.kbm`, lays it on the keys as OpenMPT's tuning does (degree 0 on C-5 at the sample's own pitch, a degree a
key). Three differences: OpenMPT plays tunings only in its own MPTM format, so the .it gets detuned copies of the sample
per degree instead; a pitch such as `-5.0` is read as cents, as Scala's format says, where OpenMPT's reader takes it for
the ratio -5 and refuses the file; and a `.kbm` keyboard map is read (Scala's format), which OpenMPT does not. So is the MAP tab; its Up and Down step through the filter's matches as the arrow keys step through
OpenMPT's tree view, but play each sound as they land on it, where OpenMPT plays a tree item on Space (`kcTreeViewPlay`;
Space here plays the song). The keys are OpenMPT's defaults (`DefaultKeyBindings.h`; its IT set changes only keys of
note entry): F5 play/pause, F6 the song from its start, Ctrl+F6 from the cursor, F7 the pattern looped from its first
row, Ctrl+F7 from the cursor, F8 pause, Esc stop (`Moddoc.cpp`: F5 after a stop plays from the song's start, after a
pause resumes with the pattern loop off), Ctrl+Space edit mode, Enter and Space cursor copy and paste, Ctrl+5 select
the pattern, Ctrl+Q / Ctrl+A transpose (with Shift an octave), Ctrl+Up / Ctrl+Down the previous / next instrument
(wrapping round), Ctrl+I the INS instrument on every selected cell with a note or an instrument
(`SetSelectionInstrument`), Ctrl+J / Ctrl+K interpolate, Shift+V paste flood, Ctrl+Alt+V push-forward paste. Shift+V
in the note column stays a chord note, as OpenMPT's note context takes the key before the paste does. PUSH is
OpenMPT's Push Forward Paste (`PatternClipboard.cpp` `pmPushForward`): before each pasted cell its channel moves a row
down from there, the last row dropping off. OVERFLOW is OpenMPT's Overflow Paste, off by default as there: a PASTE or
MIX that runs past the pattern's end goes on at row 0 of the next order's pattern (one undo step), never with flood or
push, and stops after the last order (OpenMPT adds patterns only for a multi-pattern paste). Channel and pattern names
are written into the .it as OpenMPT's `SaveIT` writes them: the `PNAM` and `CNAM` chunks after the MIDI configuration,
up to the last named one, a channel name keeping 19 characters. The Pattern tab tells a screen reader the cursor's cell
in OpenMPT's default accessibility format (`get_accName`): "Row 4, Channel 2, Instrument: 3: Bass", a special note
as Note Off, Note Cut or Note Fade, an empty column as nothing; a volume or an effect is described in the hint line's
words, not `EffectInfo`'s, and an instrument without OpenMPT's "(n: sample)". A paste goes to the selection's top-left
corner, else the cursor, as OpenMPT's `ExecutePaste` puts it; TRANSPOSE skips a channel whose note column the
selection (or the cursor) leaves out, as `TransposeSelection` does. Deliberate differences in the keys: PASTE, MIX,
FLOOD, PUSH and the interpolations work outside edit mode too (OpenMPT asks for it), as the buttons always have here;
the INS box has no "No Instrument" entry for Ctrl+Up / Ctrl+Down to stop on, and Enter on a cell without an instrument
leaves INS as it is; Space and note entry stop at the pattern's last row where OpenMPT's continuous scrolling carries
the cursor into the next order's pattern; on the Samples tab Esc first clears the waveform selection; F5, F8 and the
Ctrl variants drive the live engine, not the Tryout's rendered player (Esc stops both); VEL→VOL starts off (OpenMPT
records velocity by default). Any other difference from OpenMPT is a bug.

**Conveniences.** F5 plays and pauses, F6 plays the song from its start (Ctrl+F6 from the cursor), F7 loops the pattern
from its first row (Ctrl+F7 from the cursor), F8 pauses and Esc stops, in every tab (OpenMPT's keys; F5 no longer
reloads the page). METRO in the live bar clicks on every beat while the live engine
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
ends in, the channels between whole. Ctrl+5 selects the pattern (the channels on show), Ctrl+L the cursor's channel; a
plain move or click drops the selection. The SELECTION bar (and its keys) works on the selection, or on the cursor's
cell when there is none: COPY (Ctrl+C; also puts the rows on the system clipboard in OpenMPT's format, so OpenMPT
pastes them), CUT (Ctrl+X), PASTE at the cursor (Ctrl+V: the copied fields overwrite; rows copied in OpenMPT from an IT,
MPTM or S3M module paste too, the first pattern of several, values this notation lacks left empty and counted), MIX (Ctrl+Shift+V: only into empty fields), FLOOD (Shift+V outside the note column: the clipboard again
and again down to the end of the pattern, e.g. one bar of hats over eight), PUSH (Ctrl+Alt+V: the copied rows inserted
at the cursor, each pasted channel's rows below moved down and the last ones dropped), OVERFLOW (kept for the next
launch: PASTE and MIX go on past the pattern's end into the next order's pattern), CLEAR
(Delete), TRANSPOSE by a semitone or an octave (Ctrl+Q / Ctrl+A, with Shift an octave; INS ONLY limits it to notes whose
cell names the INS instrument; notes stay within C-0..B-9), Ctrl+I sets the INS instrument on every selected note or
instrument (Ctrl+Up / Ctrl+Down step INS), INTERPOLATE (OpenMPT's, Ctrl+J the volume column alone, Ctrl+K the effect
column alone; the button in each selected column,
note, instrument, volume and effect alike, from the first selected row to the last, where both ends carry the same
command or one end is empty and the other's value fills the span; a row holding another command is left alone; with no
selection, the cursor's column between the nearest value at or above the cursor and the next one below), GROW and
SHRINK (Alt+E, Alt+D: OpenMPT's; GROW spreads the selected rows two apart over twice the span, blanking the rows
between and overwriting what was there, and drops a row that would land past the pattern's end, counted in the bar;
SHRINK keeps every second row, packed into the first half of the span, a field left empty there taking the next row's,
and clears the rest; the selection then covers the new span; note delays `SDx` keep their ticks, which the bar says
when there are any), AUTOMATE (a
curve written as plain cells over the selected rows and channels, or the cursor's channel over the whole pattern: TARGET
`Zxx` cutoff or the SFx macro, `Xxx` pan, `Mxx` channel volume, `Vxx` global volume or `Txx` tempo (these two are
song-wide, so only the first channel gets them; `Txx` takes 20-FF, below that it is a tempo slide), or the volume column
`vNN`; FROM and TO in the target's own digits, hex for an effect as its cell shows it; SHAPE LINEAR, S-CURVE (slow at
both ends), EXP (equal ratios per row, 0 counted as 1) or STEPS (equal steps, one per written row, the last at TO; one step, when EVERY passes the selection, is FROM);
a value every EVERY rows from the first, the last selected row always at TO except with STEPS; a cell holding another
command in that column is left alone and counted; one step for Ctrl+Z; the same curve kept in the song, redone on
every compile, is a pattern's `automation:` lane (SONG_FORMAT.md section 6), whose cells the Pattern tab draws dimmed and
whose column it will not let you type over: change the lane, or MAKE EDITABLE to turn the lanes into plain cells) and AMPLIFY (the
volume column by a percentage; a note without a volume gets one, counted from 64, the usual default) and HUMANIZE
(each note's volume moved at random within ± the given amount, from 64 when it has none, kept within 1–64). LENGTH
works on the selected channels' rows (the cursor's channel over the whole pattern with no selection) and leaves an
approved pattern alone: FILL removes every note-off, cut or fade between a note (also one sounding into the selection
from above) and the next note, so the notes run legato (a volume or effect on that row stays; an end after the last
note stays, and FILL cannot tell a rest you meant from a length, so it acts on the selection only and counts); SET n
makes each note n rows long, its note-off moved there (`===` with instruments, `^^^` with samples only; a note whose
next note comes sooner sounds to it; one whose end would fall past the pattern is left alone and counted); CUT HERE
writes a note-off at the cursor's row on every selected channel where a note is sounding into it; GLUE removes a
restrike of the same note (its own instrument or none, no volume, no effect) that comes right after the note or its
note-off, with that note-off, so the two become one note (a restrike with a volume or an effect is an accent and stays).
ECHO is the
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
eighths of four-row beats; a 0 removes a delay, and a note that carries another effect keeps it undelayed. ACCENT does
the same for volume: a volume per row, repeating from the pattern's first row, written as `vNN` on every note of the
selected channels (every channel with no selection), in THIS PATTERN or the WHOLE SONG: `64 40 52 40` accents the beats
of four-row beats, and a percent takes the note's own volume (its `vNN`, else the one it plays at: its sample's
default where the cell names an instrument, or a `vNN` above it in the channel), so `100% 60%` keeps the on-beat rows'
volumes and lowers the others; a note with another volume-column command (a pan, a slide), or a percent on a bare note
whose volume the pattern does not say, is left alone and counted in the bar, and a note already at its level keeps
its cell. EUCLID makes
the selected rows of one channel (or, with no selection, the cursor's channel from the cursor down) a Euclidean rhythm
of the cell at their top: HITS spread as evenly as they go over STEPS (3 / 8 is `x..x..x.`), turned left by ROT, a step
every EVERY rows, each hit kept with the given percent (seeded: the same settings write the same cells); the other rows
are cleared. Three more fields make it change by rule. `+` layers more cycles over HITS / STEPS (`2/5 3/7`): a step
sounds where any cycle hits, at the top cell's volume where all of them hit and down to half of it where only one does
(when that volume is known: its `vNN`, else its sample's default). PHRASE restarts the cycles every so many rows,
counted from the pattern's first row, so cycles of 3, 5 and 7 steps realign at each phrase end. RULES, one per phrase
and repeating, change each phrase: `-` as is, `rev` reversed, `inv` hits and rests swapped, `rotN` turned N steps,
`+N` turned N steps more at each phrase (PHRASE 8 with RULES `+1` turns 3 / 8 from `x..x..x.` to `..x..x.x` in the
second phrase, `.x..x.x.` in the third). With WHOLE SONG, EUCLID writes the channel in every pattern the orders play,
with the cell at the top of the selection, and the phrases count on through the song from where each pattern first
plays (by pattern lengths: a jump or break that cuts a pattern short is not counted). A pattern repeated in the orders
holds one set of cells, so it plays the same rhythm each time: rhythms differ between patterns, not between repeats.
CHORD stacks each note of the selected channel (or the cursor's cell) into the chosen chord over that
channel and the ones to its right, with the note's instrument and volume, INV lowest tones moved up an octave; note-offs
are copied across so the chord ends whole, and a chord that needs more channels than the song has is refused (add them
in the SONG tab). STRUM above 0 delays the chord's voices one after another by that many ticks (`SDx`), the lowest first
(UP) or the highest (DN): a voice whose cell carries another effect stays undelayed, and a delay past 15 ticks or past
the row (speed - 1 ticks) is held there; the bar counts both. ARP plays each note of the selected channel (from the
cursor down with no selection) as the root of an arpeggio of the CHORD shape over OCT octaves: a note every EVERY rows
up to the channel's next note, note-off or cut, going UP, DOWN, UP-DOWN or DOWN-UP (the turning notes once) or RANDOM,
SKIP leaving out that percent of the steps after the first (seeded, so the same settings write the same cells); every
step keeps the root's instrument and volume, and an effect or volume already on its row; GATE 1-15 cuts each note after
that many ticks (`SCx`, where the effect column is free), OFF puts a note-off on the row after each note (`^^^` in a
song without instruments). The roots are the notes you wrote: ARP never invents one. LAYERS rewrites the instrument column of each note: CYCLE takes the listed instruments in turn, note
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
type it (a trailing comment on its line stays). MESSAGE under it is the IT song message (OpenMPT's Comments tab):
plain text, written to `module: message` as a literal block (`message: |`) exactly as typed when the box loses focus,
one step for Ctrl+Z, emptied to remove it; the line under the box counts the characters and, as `check` does, warns
when some are outside Latin-1 (stored as `?` in the .it) or past IT's 65534. ORDER LIST: click an entry to select it (a double-click, or EDIT ▸, opens
it in the Pattern tab); ◀ ▶ move it, REMOVE, DUPLICATE (the same pattern again after it), CLONE PATTERN (a copy of its
pattern under a new name takes its place, so it can change without touching the other orders that play the pattern),
INSERT or SET a pattern (or a `+++` skip, a `---` end) from the list, NEW PATTERN (empty, the given rows, after the
selected entry). PATTERNS: click a name to rename it (the order list follows) or its row count to change it (rows past a
new end are removed); CLONE; DELETE (click twice) only when no order plays it. CHANNELS: click a name to rename it;
the colour box beside it gives the channel its own colour (`color:` in its entry; the rail, the Pattern tab's header and
the roll's ghosts take it, ↺ goes back to the colour its name gives it; a song with it needs an app that knows the key,
see SONG_FORMAT.md); ▲ ▼ move a channel (its cells move in every pattern, and so do its tryout mute and unwritten faders); ✕ (click twice)
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
(2) or a span (1-3), LOOP a span, and `carry` and on/off are checkboxes. An envelope written as an `lfo:` (SONG_FORMAT.md)
shows as one line with its settings and is edited in the song file (its ✕ removes it). Under the instrument list, a
SoundFont (`.sf2`, typed or BROWSE…) lists its presets (bank:preset); ADD makes the chosen one a new instrument, its
zones new slots written as WAVs in a folder beside the song named after the file and the preset (`TimGM6mb_Violin/`),
read as OpenMPT reads a bank
(Following OpenMPT), one undo step; a GUS patch (`.pat`) the same way. SAMPLE SLOTS adds a slot for a WAV (typed or
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
length), STRETCH (percent of the length at the same pitch; loops move with the audio), TRUNCATE SILENCE (every
silence under the dBFS level and longer than MIN shortened to KEEP) and GRANULAR (a cloud of grains at the same length:
every GRAIN / DENSITY a grain of GRAIN ms read from near the same time, SPRAY ms either side at random, PITCH semitones
up or down, each JITTER semitones more or less at random; a recipe's `fx: granular` is the same effect with a `seed`
and a window `shape`). LEARN NOISE takes the selection as a stretch where
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
request to use speed 16 or less; it never wraps a delay to an earlier tick. ORIGINAL BPM is the sample's own tempo:
FIND fills it with a guess from the length sliced (240 / seconds, one bar of four beats, doubled or halved into
100-200, as LMMS's SlicerT guesses it), to be corrected by hand. With SNAP (1/4 to 1/32) FIND moves each cut to the
nearest line of that grid at ORIGINAL BPM (two on one line become one). + PATTERN ON GRID writes the pattern with each
slice on the row its place in beats reaches at the song's rows per beat, without delays, so a 170 BPM break plays on
a 165 BPM song's rows instead of drifting off them. What SLICE made is reported in the
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
The count-in uses the BPM at the accompaniment's selected start.

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
wheel zooms, a drag pans, a double-click fits the map; the filter dims what does not match a name or folder, and Up and
Down in the filter box step through the matches (all sounds with no filter), each one selected and played, the map
panned to it when it lies outside the view. From the
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
a free row), dragging a note up or down transposes it, dragging it sideways moves it in rows (onto an empty cell; its
whole cell moves, and its note-off with it where that row is free), dragging its right edge sets its length (as SET
LENGTH does: the note-off moves there, a note whose next note comes sooner sounding to it), a right-click deletes it
(its effect stays), Shift+click writes a note-off, and a click in the lane sets the note's volume. In an approved
pattern the roll refuses the length and row drags, as the SELECTION bar's LENGTH tools do. SCALE LOCK puts a click on the nearest note of the song's
key and shades the pitches outside it. GHOST FROM draws another pattern's notes, all its channels, under this one in a
third shade (amber), so a verse's bass shows under the chorus lead: the previous or the next order's pattern, or any
pattern by name. They are never editable; where the two patterns differ in length the drawing stops at the shorter
(the title says so), and a named pattern that is renamed or deleted falls back to the previous order's.
SCOPE switches between Channel / raw (all of the above) and Native track, offered when the pattern has a score.
Native track shows every note of the chosen TRACK, on all its channels and in both voices. ENTRY chooses
Grid / drag or Matrix / toggle. Notes that overlap at one
pitch get separate lanes and separate volume bars, so each is its own target. Dragging, resizing (which changes that
note's whole voice beat), right-clicking and the lane edit that source note. Other tracks, raw cells and GHOST FROM
notes stay read-only ghosts. With EDIT on, a left click on blank space enters a note on that track through the TAB's
own note entry. It goes at the GRID line at or before the pointer, with the TAB's duration controls, in the voice of
the track's last selected note (voice 1 otherwise), on the first free string that can play it. Strict placement
applies, and one Undo removes it. TuxGuitar's matrix instead adds to the beat that contains the click; snapping to
the visible grid is a deliberate difference. A click at an onset where that pitch already sounds is refused rather
than toggling the other note off in Grid / drag mode. Matrix / toggle follows the containing active-voice beat:
clicking a matching pitch removes the first match at that onset across both voices; otherwise it uses the first
free playable string. The TAB duration subdivides rests, including dotted/triplet cells and shorter final tails.
A shorter duration can shorten the containing chord and put the new note in the following rest. This is one
Undo transaction. GRID does not snap Matrix clicks. Enable TAB's Fit within measure to permit guarded shifts;
Free edit takes precedence: the new note stays on the containing beat, takes the TAB duration and leaves
following gaps visible. It can extend a unique final bar but refuses overlap with sounding notes or protected rests.
Successful Matrix entry auditions both voices of the original containing beat for 500ms. After normal
shortening/retargeting that can be the original chord rather than the new later note, as in TuxGuitar.
Deletion does not audition. An absent voice, or an implicit gap in Free edit, auditions the clicked concert
pitch without creating a note. Preview uses the assigned native samples; identical TG synth timbre/controllers
are not implied. Playback or a song change during engine startup cancels the queued audition.
unsafe peer-string collisions, tied-beat resizing, protected notation and inexact standalone IT timing refuse
without changing the song. An absent second voice needs its first authored note entered in TAB. Native implicit silence
is available without saving filler rests; exact rest spelling may differ from TG. Rows use concert pitch,
including capo, whereas TG's Matrix labels omit capo. These remain explicit differences.
Right-clicks on blank space do nothing; switch to Channel / raw to draw raw cells
or note-offs. A drag is
cancelled without an edit if the scope, track, pattern, occurrence or song revision changes before you release it.
In Native track scope, GRID (1, 2, 3, 4, 6, 8 or 16; default 2) draws guide lines that divide each meter beat:
6/8 at 3 gives lines every sixth of a quarter note. The lines follow the TAB's measures, with 4/4 groups where no
measure is written. They are guides only, as in TuxGuitar's matrix: notes keep their written durations, and the
setting is kept by the app, not in the song. On a percussion track each row shows its drum key and name
(TuxGuitar's names for keys 27–87, "Drum key N" otherwise), and scale shading does not apply.

**Agents: the AGENT panel and MCP.** An agent works on the song open in the app through one set of tools
(`vulturetracker/agent.py`): read the song and a pattern (`song_overview`, `read_pattern`), inspect native notation
and its stable IDs/revision (`read_score`), make a guarded native TAB edit with shared undo (`edit_score`), and what the compiler
says of it (`check`), read the owner's selection
(`get_selection`: the rows and channels selected in the Pattern tab, with what sounds there), write cells
(`write_cells`), set the order list (`set_orders`), add a pattern (`new_pattern`), set the tempo, speed, title, key or
the module's message (`set_module`), set the rack's plugins (`set_plugins`, with `describe_effects` listing their parameters), measure
(`measure`, below), cue a place in the app and play it (`cue`), offer WAVs as tryout candidates (`offer_samples`), read
the listening notes (`read_notes`), check the key (`key_check`), `undo` and `redo`. It can also:

- **Add an empty channel** with `create_channel` (optional name, up to 64 channels). The returned channel number is
  ready for `write_cells`; existing notes and routing stay in place.
- **Rename, colour, move or remove channels** with `edit_channel` (`color: "#rrggbb"`, `""` to remove it; the app's
  colour only). Channel numbers are 1-based; moves carry notes, routing,
  pan, volume and audition faders/mutes. The result maps old numbers to new ones. Removing notes requires
  `remove_notes:true` and the owner's request. Approved channels cannot be changed or shifted; approved patterns
  block moves/removal. Each operation is undoable.
- **Create samples and instruments** with `create_sample` and `create_instrument`. Samples import an audio file into
  an unused slot (WAVs are referenced; other supported formats become a new WAV beside the song), defaulting to
  C-5 root and stereo preservation. Set `base_note` for another root. Instruments accept a sample number or keymap;
  without either they are silent. Creating the first instrument converts existing samples to instruments at the same
  numbers before adding the new one, in one undo step. Conversion is refused with approved material. Existing slots
  are never overwritten; `offer_samples` remains the tool for proposing tryout choices.
- **Export songs and stems** with `export_song`: IT, WAV, MP3, OGG, FLAC or MIDI (`mid`), an optional named section,
  aligned stems, and optional IT alongside audio; `rate`, `depth` (16, 24 or `float`), `bitrate`, `quality` and `repeat`
  as RENDER & EXPORT takes them, and `master_lufs`/`master_ceiling` for NORMALISE (the owner's choice, so only when
  asked). Defaults are saved mix, ignored audition mutes and no replacement. Choose
  `mix:current` to include unwritten faders and the selected candidate, and `mutes:respect` to include solo/mutes.
  `game_loop:true` writes WAV/OGG/FLAC loop metadata for the whole song or named section, not the audition row loop.
  Follow the returned `job_id` with `export_status`; only `done` confirms published files, and compiler warnings are
  separate from failures. `cancel_export` requires that ID and can cancel queued/rendering work, not final publication.
  Exports use a frozen snapshot; replacing existing outputs requires explicit `replace:true`, which the tool refuses
  until the owner presses ALLOW REPLACE in the AGENT panel (it allows one export within two minutes), and source assets
  remain protected. A `destination` must be inside the song's folder. The app retains the current/latest job, also visible in RENDER & EXPORT.
- **Edit existing sounds** with `edit_instrument` (mapping, envelopes or their `lfo`, `filter_mode`, microtuning with
  `tuning` and `keymap_file`, Scala files beside the song, and note behavior) and `edit_sample`
  (name, tuning, loops, vibrato, format or an explicitly requested WAV replacement). Omitted fields stay unchanged;
  nested fields are replaced whole, and `clear` removes optional fields. Mixer volume and static pan remain the owner's.
  `delete_slot` removes only unreferenced sample/instrument definitions, without renumbering or deleting audio files.
  References in unused patterns and instrument maps also block deletion.
- **Process samples** with `inspect_sample` first: it reports source-frame dimensions, usage and optional loop/slice
  suggestions. `process_sample` exposes trim, fades, normalize, reverse, DC removal, loop crossfade/auto-loop, gain,
  low/high-pass, EQ, RMS loudness, pitch, stretch, tail truncation, denoise and granular. Frame ends are exclusive. Processing
  writes a new WAV and preserves the original; exceeding full scale causes reported attenuation. Level processing
  requires the owner's request. Approved sounds and voices used by approved material are protected (conservatively,
  any approved pattern protects all played voices because notes can carry into it).
  `inspect_sample`'s slice analysis takes SLICE's `bpm` and `snap` (the points moved to that grid; it returns the
  tempo guessed from the span's length). `slice_sample` creates kit or multisample slots from explicit frame points,
  and with `pattern:true` a pattern playing them from `channel`, on the song's grid when `grid_bpm` gives the sample's
  tempo; `render_sample` creates a slot from
  inclusive pattern rows, including current mix settings. Both retain original notes and samples. Each edit is undoable.
- **Find sounds** with `index_library`, `library_status`, `search_library` and `similar_samples`. Scans add supplied
  folders to the shared index by default; `replace_roots:true` replaces them deliberately. Only WAVs are indexed.
  Filename search uses all query words, with pagination and file-stamp freshness; similarity compares measured timbre.
  Neither chooses a candidate. Scans and similarity searches return job IDs: pass the ID to `library_status` so a
  newer UI/agent job cannot be mistaken for your result. Search does not implicitly scan a large library.
- **Synthesize sounds** with `synthesis_catalog` (sources/dependencies, installed patches, patch parameters and nearby
  recipes), `read_sound_recipe`, `save_sound_recipe` and `render_synthesis`. Recipe edits create a new version beside
  the song; `changes` replaces top-level fields, `clear` removes fields, and relative input paths keep their original
  meaning. Each render uses one entry/note and supports patch, file (a Hydrogen kit too), Faust and resynth sources
  and the numpy ones (`wave`, `sfxr`, `drum`, `additive`); `faust: NAME.dsp` falls back to the examples shipped with the
  app, which `synthesis_catalog` lists; with `mip` the job also returns the copies (`mip_files`) and its log the
  `samples:`/`keymap:` blocks to paste. `render_paint` creates
  a WAV, PNG and reusable settings JSON; optional `file` applies the picture as a spectral filter. Its `source` reloads
  saved Paint settings, with supplied fields overriding them. `read_sound_recipe` can inspect those settings too.
  Poll `synthesis_status` with the job ID; only `done` returns usable output paths. `cancel_synthesis` suppresses
  publication, but a running plugin/Faust/DSP call finishes before cleanup. The latest job is also in `get_state`.
  Outputs are new assets, outside song undo, and remain for reuse. Use `offer_samples` to audition them or explicitly
  create a new slot with `create_sample`; no render automatically selects a sound. Dependencies are reported without
  downloading. Faust recipe rendering needs Node and faustwasm; named patches need their installed synth/library.
  Patch parameter inspection returns recipe values with units, ranges and choices; `raw_value` is informational.
  Background VST renders use a separate process so plugin resets can run on its main thread.
- **Compare phrases** with `capture_phrase`, `read_phrase`, `edit_phrase`, `render_phrase` and `phrase_diff`.
  Capture one order's inclusive row range and 1-based channels, with 2–4 alternatives. Edits and renders require
  the current comparison ID; replacing a capture requires its `replace_id` and archives it. Alternatives are
  0-based; `-1` renders the line absent. Draft edits preserve the captured dimensions and song-wide timing/effects.
  `read_phrase` returns summaries, or up to 32 rows of one alternative with `offset`/`limit`. Renders use frozen
  sounds and mix; stale comparisons can still render but need recapture before editing or acceptance. These
  draft/assets operations are outside song undo. Ratings and final acceptance stay with you in PHRASES.
- **Manage projects** with `project_status`, `create_project`, `import_project`, `open_project`, `collect_project`,
  `relink_hints` (for each missing sample, same-named WAVs from the library index, `same` when the contents match the
  digest an undo step recorded) and `relink_samples`. `import_soundfont` lists a SoundFont's (or GUS patch's) presets,
  or adds one as a new instrument, one undo step (a sample-mode song is converted to instruments in the same step). Create/import/collect return new paths without switching songs. Imports use the app's
  module, Guitar Pro or MIDI importer and preserve the source; collisions get numbered output names. Collection
  uses a new external folder, optionally a ZIP, and checks frozen phrase assets. `open_project` switches the app
  and subsequent agent tools to that YAML; it refuses external changes, pending page edits or active recording/
  render/export jobs. Inspect its returned compile/read-only status before editing. `relink_samples` maps sample
  slot numbers to WAV paths in one undo step, including missing-file repair; approved sounds are protected.
  Project creation/open/import/status are also available over MCP before a song is open. Relative paths start
  at the current song folder, or the app's working directory when no song is open. Creation/opening/collection
  are not undoable song edits; a collected copy starts a new history.
- **Arrange named sections** with `edit_section`: create/update boundaries, rename, delete, move or duplicate.
  Section bounds use raw order positions (including skips and end markers), start inclusive and end exclusive.
  `to` is a boundary in the original order list. Moves remap jumps and audition loops; independent pattern copies
  are the duplication default. Shared copies with internal jumps are refused. Deleting a section removes its name,
  not its orders. Overlapping sections or changes to approved material are refused before writing.
- **Maintain patterns** with `edit_pattern`: rename, resize, delete unused patterns, materialize shorthand into
  explicit cells (automation lanes become plain cells), split (OpenMPT's Split Pattern, from `row`), or set the
  pattern's `automation:` lanes (`lanes`, replacing them; `[]` removes them; a lane on an approved channel is refused). Resizing is 1-200 rows; removing nonempty rows requires `discard_rows:true`. Materializing preserves
  authorship and approval marks. Approved patterns cannot be edited by the agent; with an approved channel, structural
  changes such as renaming/resizing/deleting patterns may require the owner to use the Pattern tab.
- **Transform selections** with `transform_patterns`: transpose, clear selected fields, wildcard find/replace,
  groove delays, Euclidean rhythms, chords (with `strum`) and instrument/sample layers, and the SELECTION bar's own
  tools through the page's code: `interpolate`, `automate`, `grow`, `shrink`, `arp`, `fill`, `set_length`, `cut_here`
  and `glue` (a lane-owned column refuses other values). Selections name each pattern once and use
  inclusive row bounds and 1-based channels; repeated orders share the edit. Chords write adjacent channels and need
  `overwrite:true` for occupied destinations. Groove keeps other effects and reports skipped notes.
  `copy_pattern_region` copies or moves rectangular regions (optionally selected fields) using a snapshot for overlaps;
  `mix:true` fills empty fields for copies. Other occupied destinations require `overwrite:true`. `write_patterns`
  writes full cells across several patterns. Each call validates the whole result before saving one undo step, marks
  edited cells' patterns with agent authorship, and protects approved material. Empty/no-op edits add no history.
- **Inspect the full Rack and state** with `get_state`: plugin IDs, every parameter, routing, macros, sample and
  instrument definitions, audition settings, unwritten mix, history, and the window's selected tab/channel and
  playback mode. A selected Rack channel is not automatically soloed. Window reports include their age and a stale flag;
  they stop updating when the window is closed or suspended.
- **Solo, mute and loop** with `set_audition`. Channels are 1-based; loop endpoints are `[order,row]`, 0-based and
  inclusive. `solo:null`, `muted:[]` and `loop:null` clear those settings; omitted fields stay unchanged. A loop selects
  its orders for rendering and overrides the live pattern loop (F7). These settings persist in the tryout sidecar, without moving
  faders or changing notes. Use `cue` with `play:true` to start; `stop_playback` stops the live and rendered players.
  Stop/audition requests report **queued**, with a request ID: `get_state.ui.applied_request` confirms window delivery.
  Playback state is reported separately; requests expire after ten seconds if no open window handles them.
- **Edit one effect** with `edit_effect`: add to a channel, patch selected parameters or bypass, remove and reconnect
  its inputs, or reorder within a channel. Other settings are retained. Shared effects affect every channel using them;
  shared-chain reordering is refused, and approved channels' effects, master chains and macros are protected.
- **Record and manage takes** with `recording_status`, `control_recording` and `manage_take`. Device inspection
  does not open an input; opening starts input metering, and recording starts only on request. Recording supports
  pre-roll, backing/section, count-in, passes and latency compensation. Stop saves a new WAV (default: keep);
  offer it as a candidate, create a tuned slot, or combine pitched takes into a multisample. Saved WAVs persist;
  the take list lasts for the session. Failed saves retain unsaved passes in memory for **RETRY SAVE** or explicit
  discard. Passes that are finished but not yet saved (a backing track's passes done, a save that failed) are also
  copied, exactly, to the user folder's `recordings/` and removed once saved or discarded (`recording_status` lists
  them as `unsaved`; `control_recording` `recover` brings one back, `forget` deletes it, only on the owner's word); passes a closed or crashed
  session left there show under UNSAVED TAKES on the RECORD tab, with RECOVER (back as the take to save, beside the
  song open now) and DISCARD, and go after 7 days. Input reopen/close and project switches refuse unsaved takes.
- **Update listening notes** with `update_listening_note`: add at an explicit order/row, update text/tag/channels,
  or delete an explicitly selected note. Read its `revision` through `read_notes` before update/delete. Updates keep
  the original sounding and playback context. Input channels are 1-based; stored note channels remain 0-based.
  These are the owner's annotations, outside song undo; the agent must not invent listening impressions.
- **Pause/resume playback** with `pause_playback` and `resume_playback`. The live engine retains its exact position
  and loop; the rendered player retains its time. Stop or a project switch clears resume. A changed rendered source
  requires a new cue. Requests need the same window acknowledgement as other transport tools.
- **Inspect detailed history** with `inspect_history`: paginated undo/redo snapshots, nearest first, stable content
  IDs, saved versions, bounded current-to-snapshot YAML/settings diffs and asset/approval restore checks. Supply the
  listed entry ID for details so a shifted stack cannot silently select another snapshot. Each step carries the
  name of the operation it undoes (redoes, on the redo stack) and when it was done, as OpenMPT's undo names its steps
  ("edit pattern 3: 4 cells", "song: orders", "WRITE MIX", "agent: write_cells"); steps written before names existed
  show none. Inspection never restores or trims it.
- **Use PROJECT checkpoints** with `checkpoint`: list, save, diff, restore and delete. Names are never overwritten.
  Restore is undoable and refuses changes to current approved material or owner-controlled levels/pan; the owner can
  restore such a checkpoint in PROJECT. Existing sample fingerprint checks still apply.

For example: “Save a checkpoint called Before flanger, create a channel called Melody, then solo it and loop order 8
rows 0–59.” The agent can do each step through the same tools in chat or MCP.

No tool moves a fader, a channel's volume or pan, or the mix volume, and approved material is protected. A path a tool
is given must lie inside the song's folder or one of the sample library's folders (MAP adds folders); anything else is
refused (`create_project` and `collect_project` write only new files, so their destinations may be anywhere). Text in
the song (names, comments, the message, listening notes) is data to the model, never instructions. Each song
edit is one undo step (audition settings and checkpoint saves are separate), and a pattern an agent writes is marked
`by: agent` (`you and agent` when it had notes before; the owner's later edit makes it that too). Two ways in:

- **Claude Code (or any MCP client):** `claude mcp add vulturetracker -- python -m vulturetracker mcp`, then ask it
  about the song open in the app. The MCP server finds the running app through `running.json` in the user folder,
  which holds its port and the token each launch makes (`--port` names another app window; its token is then the one
  `VT_TOKEN` gives, as the app's own Claude Code gets it). Its calls show in the AGENT panel's ACTIVITY.
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

  Chat loads tool definitions on demand: a small directory leads to the schemas for just the operations it needs.
  Large tool results arrive in pages; older API tool outputs become retrievable references. The latest 32 saved
  results remain available until NEW or a provider change. They are historical snapshots, so the agent must
  re-read current song state before editing. External MCP clients retain the full public tool list.

  Claude Code chat uses the app's music instructions, excludes personal/project instruction files and auto memory,
  and disables session hooks and skills. Your normal Claude Code settings/files and login remain unchanged;
  organization-managed policy still applies.

  **Context** shows an approximate token count for the conversation, system prompt and tools; hover for the last
  request's provider-reported input/output counts when available. Claude Code shows its last reported context instead,
  or unavailable until it reports usage. No model context-window limit is guessed. **STOP** interrupts the current
  turn and prevents further tool actions; an edit already underway finishes and remains undoable. A remote API request
  may still finish on the provider, but its late reply cannot edit the song. You can keep typing while it works; SEND
  becomes available when it stops. **COMPACT** asks the current model for a summary, keeping decisions, completed edits
  and unfinished work for the next turn. The summary stays private; the chat only says "Context compacted."
  The visible transcript stays. This uses a model request (normal provider
  usage applies), with song tools disabled; failed, interrupted or unreduced API summaries leave the old context intact.
  **NEW** clears the conversation. Stop the agent before opening another song.

  Agent rack routing also accepts the channel-list indentation written by module imports, so effects such as flanger
  can be assigned to an imported song's channels without rewriting its YAML by hand.

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

### Native TAB / SCORE (in development)

Imported tracker songs without authored score tracks automatically show a **read-only staff preview of the entire song order**.
Pattern occurrences appear consecutively, with labels at their boundaries; repeated patterns appear for each use.
Stored patterns outside the song order are excluded, just as in playback. The full score stays in place as playback advances.
**All parts (by sound)** is the default: channels that use one identical instrument/sample slot throughout the
song share a staff. Mixed or unknown sounds stay separate; matching names alone do not merge different slots.
Interleaved lines share a voice, equal-length simultaneous notes form chords, and overlapping rhythms use
separate voices (at most two per staff). Exact unison duplicates share a notehead; selecting one identifies its
source channels. This combines notation only: tracker channels, effects and playback remain unchanged.
Choose **All channels (separate)** or one channel in the Track selector to inspect the original parts.
Staff pitches use Pattern's octave labels (IT's C-0 numbering is converted for notation), not inferred sample tuning.
Previous/Next Pattern browses the order list. Click a staff note to select its original Pattern row/channel.
The shared playback marker moves through notes, rests and pattern boundaries; Follow playback keeps it visible as the score scrolls.
Browsing or selecting a note pauses automatic scrolling until Follow is checked again; the marker still shows the playing location.
In horizontal tracker view, vertical wheel scrolling only browses channels and keeps horizontal playback follow on;
horizontal or Shift-wheel scrolling browses time and pauses follow.
The note list below the controls belongs to the selected pattern. Edit those notes in Pattern.
Preview rhythm uses the song's rows-per-beat grid, with note lengths bounded by the next note/cut/release or
pattern end. It does not transcribe effects, sample tuning, decay or playback flow, and viewing it never converts
or saves the song. Guitar TAB still requires an explicitly configured track and fingering.
To export this preview as a PDF, click **Print preview**, choose the parts, paper size, scale and bar range,
then **Update preview** and **Print / Save PDF**. In the system print dialog, choose **Save as PDF** or
**Microsoft Print to PDF**, then choose a filename. Printing follows the current grouped/separate/channel view
and includes the full song order by default. The PDF identifies tracker rhythm as a row-grid preview;
it does not create an authored score or change the song. Native scores retain staff/TAB printing options.

Pattern displays one tracker pattern at a time; imported GP bars can be as short as12 rows.
Use **Song position**, **Previous** and **Next** to reach the entire arrangement, or scroll past the first/last
row to cross a pattern boundary. Manual scrolling/browsing pauses **Follow playback**; re-enable it to follow
the transport again. Browsing changes neither notes nor Undo history.

Percussion tracks use **Drum key** entry and a lane selector, with keys 1–100. Their engraved staff uses drum
notation; click a note or beat, select a lane and type its key. Arrow keys navigate, and Shift+Up/Down moves
the note between lanes without changing its key. Ghost, accent, heavy accent, staccato, dead and palm mute
and let-ring are available. **Drum roll** uses the repetition control at 1/8, 1/16 or 1/32; **Grace** adds a
flam at a chosen drum key1–100, duration1/16–1/64, velocity, on-/before-beat timing and optional dead grace.
The grace drum key selects its own keymapped sample/playback note. A start-of-song before-beat flam follows
TuxGuitar by delaying the main hit. Grace transitions remain notation-only. TG/current and legacy1.5 retain
these ornaments; GP4/5 retain rolls, GP3 has no roll; GP3/4 require before-beat grace and cannot preserve a
nonzero-key dead grace. Explicit GP clef, mixer and key limits remain. Native MIDI retains authored drum keys
(including grace keys under transpose); standalone IT uses strict projection or the bounded sampled-passage
fallback described under IT export, and refuses cases neither can preserve safely.
Unsupported drum pitch techniques remain disabled. Track setup identifies percussion by MIDI bank128
and requires zero tuning/capo. Populated guitar/drum conversion refuses rather than reinterpreting notes.
TG files retain these drum markings. GP3 imports ghost/dead/let-ring, GP4 adds accent/staccato/palm mute, and GP5
adds heavy accent; GP drum keys remain1–99. Native MIDI export uses
channel10, retaining authored keys, and reports incompatible controls or overlapping same-key gates.
Imported kit sounds remain synthesized placeholders.

Open **TAB / SCORE** to edit directly on the engraved tablature. Use Track setup to choose the tuning,
capo, instrument and existing tracker channel for each string. Click a TAB string at a beat, including an empty
string position, and type a fret. The editing cursor marks that string; use up/down to change strings and
left/right to move between beats and across bars. Keyboard navigation keeps the editing cursor in view. Choose
a duration, dots and tuplet ratio, then Apply duration to change an existing beat. + (Longer) and − (Shorter)
double or halve the value between whole and 64th, clearing dots and keeping the tuplet. When several beats of the
current voice are selected (Ctrl+click), Apply duration, + and − change each of them in time order as one undo step,
as TuxGuitar's duration actions do. If any one is refused, none changes; Fit within measure applies per beat.
With the TAB focused, TuxGuitar's default keys work for what the editor has: * dotted (a double dot clears),
/ triplet on or off, X dead, O ghost, H hammer, P palm mute, S slide, V vibrato, F fade-in, Ctrl+Delete clean beat,
Ctrl+1/Ctrl+2 voice, Alt+←/→ previous/next marker and Alt+Shift+←/→ first/last marker. Ctrl+A selects every beat
of the whole written track in both voices, following TuxGuitar. Repair any measure-duration errors first. The keys apply
only in the TAB; in Pattern, Ctrl+A keeps OpenMPT's transpose. Dragging across the engraved TAB, as in TuxGuitar,
selects every beat of the track (both voices) from the pressed beat to the one under the pointer. The selected
beats are shaded, and duration, Copy, Cut, Repeat, Clean beat and Remove unused voice then act on them. A drag
stays within the shown order; Ctrl+click still adds or removes single beats. The Select buttons beside Copy and
Paste work as TuxGuitar's Edit > Selection. They keep the range's first beat and move the caret one beat (◀ ▶),
to the start or end of this or the neighbouring measure (◀◀ ▶▶), or to the pattern's first or last beat (|◀ ▶|),
selecting everything in between. All is Ctrl+A, and None clears the range. Shift+click on the engraved TAB
extends the range from its first beat (or the caret) to the clicked beat, as in TuxGuitar. With editing on,
**Staff click** works as TuxGuitar's default edition mouse mode. A click on the standard-notation staff adds the
clicked pitch at the nearest onset of the current voice (inside a rest, at the nearest step of the selected
duration), or removes that pitch where it already sounds. The note goes through the piano entry. *enters notes*
follows the key signature; *enters sharps/flats* raises (or, in flat keys, lowers) the steps the key leaves
natural; *selects* only selects. Staff clicks respect the selected sounding or TuxGuitar written pitch display,
including capo; changing that display does not transpose the song.
Notes on one beat form a chord
and share its duration. Rest clears that voice's notes. The two voice selectors edit independent written rhythms.
Remove unused voice works as TuxGuitar's command. It looks at the selected beats (or the caret's beat) and takes the
last voice that is empty or a rest at all of them. In each of their measures it then removes that voice's rests,
unless the voice has a note in the measure. It is one undo step. An annotated rest refuses.
Changing an existing track's tuning, strings, capo or maximum fret in Setup retunes it, as TuxGuitar does. By
default each note keeps its pitch on the best string; with Retune keeps frets, each keeps its string and fret.
**Assign channels automatically** keeps existing string channels and appends channels for added strings.
Removing strings retains their raw Pattern channels and data. The module limit remains 64 channels; native
tracks support up to 25 strings, while individual export formats have lower limits. Uncheck this option for
explicit channel assignments. Tuning and other Apply track fields save together as one Undo step. Unsafe
harmonic-node changes or changed slide/hammer/ringing relationships refuse the whole edit. Grace and trill
alternate pitches stay fixed when keeping pitch, an intentional difference from TuxGuitar. Reallocated chord
diagrams are removed and reported; uniform compatible retunes transpose their frets.
The tuning is written as note names, top string first (standard guitar is E4 B3 G3 D3 A2 E2; MIDI numbers also
work), and Preset fills common tunings (standard, Drop D, half and whole step down, DADGAD, open G/D, 7-string,
4- and 5-string bass), as TuxGuitar's tuning dialog does. A capo works as TuxGuitar's offset and a real capo: every
note keeps its string and fret and sounds higher by the capo, which the score's header line shows (Capo 2). A
capo change takes effect at once, with no Apply: each spinner step (or typed value) is one Undo step.
The status lists what moved. **Transpose…** works as TuxGuitar's dialog: -12 to 12 semitones over the whole
track or the caret's measure. All tracks, Apply to chords and Try to keep strings are on by default, and
percussion is skipped. Notes that would leave the instrument refuse instead of being removed. Each is one undo step.
Clean beat, as in TuxGuitar, turns both voices of the track at each selected beat (or the caret's beat) into rests
of the same durations, and clears their text, chord diagram and strokes, as one undo step. Tied notes refuse
until untied. **Insert rest** (Ins) works as TuxGuitar's: at a beat of the current voice it moves that voice's
later beats right by the beat's duration within its measure. Trailing rests that would overflow are dropped,
and a note that would overflow refuses. It fills the caret with a rest of that duration. Where the voice has no
beat, it places a rest of the selected duration. A pattern played more than once changes in every use.
Their notes can overlap on the same string/channel with explicit instruments and supported source settings;
that channel's raw backing must contain only empty cells, tempo or global-volume commands. Existing tracker notes appear as read-only previews
until explicitly adopted. Previews show the exact boundary in the selected occurrence. Adoption currently requires
an explicit tracker note-off; a following attack, cut/fade or unknown ending needs clarification before adoption
so the instrument's release and overlap behavior is preserved.

The same saved song drives TAB, Pattern, piano roll and playback. Pattern pitch changes preserve valid fingerings
or choose a new playable string; out-of-range pitches remain visible. Piano-roll length changes resize the entire
authored chord; supported horizontal moves preserve single-note or whole-chord identities. All these changes use the existing
undo/redo and save history. F5–F8 retain VultureTracker's shared transport keys while TAB has its own fret/navigation
keys. This transport binding is a deliberate difference from TuxGuitar's defaults.

The engraved score shows the selected track's entire written arrangement, wrapping onto additional systems as
needed. Repeats keep their written bars and repeat signs. Click a TAB position in any bar to select its source
occurrence for editing; the Pattern cursor follows that selection. Editing a reused pattern changes every
occurrence of that pattern. **Note and beat properties · navigation** exposes the detailed controls, while
**String grid (optional)** retains the alternate grid editor. Both start collapsed so the score remains the
main editing surface. The editing cursor is separate from the playback highlight.

The optional **Fretboard** uses the same track, voice and exact score position. Click a position to insert or
replace a note; clicking an existing string/fret toggles that note off, checking both voices in voice order.
Each edit shares the song's undo history. **Audition only** or Shift+click previews the position without
writing a note. Entry and audition require stopped playback. Arrow keys move within the board; Enter/Space
uses its selected click mode. Percussion retains its lane/key controls instead of a pitched fretboard.

Select a root and one of 275 reference scales, or **None**. Reference scales, left/right orientation, labels,
font, colors and string spacing are display preferences and do not change the song. Left orientation mirrors
frets while retaining string order. Unlike TuxGuitar's fixed frets0–23 and capo-omitting labels, this board
covers the track's full maximum fret and labels/highlights concert pitch including capo.

The optional **Piano** uses the same exact caret and written-duration controls. Click a key to add a note or
toggle the first matching pitch across the two voices; a successful edit is one undo step and does not advance
the caret. Pitched entry chooses the first free string in track order, including capo, and refuses if that
string exceeds its fret limit. Percussion presents drum keys 1–100 and uses free lanes instead of guitar frets.
**Audition only** or Shift+click previews without editing. Entry is supported at authored beat starts,
exact positions in implicit gaps and inside bare written rests. A placement or duration change consumes or
splits available rests in the active voice as one undo step, retaining the exact caret and later note positions.
Annotated rests, combined note insertion and tied-note resizing, sounding-note overlap and measure crossings refuse without changing the
song. Duration-only tied edits are supported as described below. Select the start of a sustained note before adding to it. Pattern QWERTY/MIDI entry keeps its existing behavior. The piano shares the fretboard's
scale display and requires stopped playback.
Direct fret typing and fretboard insertion also use this rest-aware path. Rapid multi-digit entry retains
the same note identity; navigating or an intervening edit cancels queued digits without undoing digits
already saved.

**Fit within measure** is optional and starts unchecked. When changing an existing beat's duration,
it can move or resize following notes through explicit rests or implicit gaps, retaining expression and
authored velocity on intact notes and following the supported
TuxGuitar rebuild cases. Partial rests and several following beats are supported while the other voice stays
unchanged. If there is insufficient room, the beat keeps its previous duration; other valid selected beats
can still change. The status reports moved/resized beats and unchanged durations, and the controls show
what was actually used. Protected annotations, unsafe technique movement and tracker conflicts still refuse
the whole edit. New notes inside gaps/rests and direct fret replacement retain
their strict placement behavior. Fitting does not create another measure to make space.
When the other voice has a note there between rests, a fit can also move the following beat into a place only
that other voice occupies. Every beat of the other voice stays exactly as it was.

**Follow playback** starts enabled and scrolls to the sounding measure while the highlight moves through the
full score. It does not replace the score with the current pattern or move your editing cursor. Browsing,
selecting notes or editing pauses automatic scrolling; check it again to resume. The order context distinguishes
the editing selection from the sounding order/pass.
Changing Part, Track or Voice preserves the Follow setting. An empty editing voice still shows the part's
playback marker using its other voice. Ctrl+F6 and Ctrl+F7 start at the exact native caret position, including
notes between tracker rows.

In **TAB / SCORE > Lyrics**, edit the selected track's starting written measure and lyric text. **Apply lyrics**
saves both, **Remove lyrics** deletes the stream, and **Cancel** discards the draft. Apply and Remove require
stopped playback. Untouched text preserves its original raw line endings, including when only the starting
measure changes; editing the textarea saves line breaks as LF. Empty text retains the starting measure.
Lyrics can also be stored in native song YAML or edited through the agent's existing `edit_score` / `track_set`
operation: supply the complete track with `lyrics: {from_measure: 1, text: "words"}`; omit `lyrics` to clear it.
The raw text, including spaces, tabs and line endings, shares save/reopen and undo/redo with the score. It does not
alter playback. Placement starts at the numbered written measure, assigns one space-separated slot per non-rest
onset and requires an authored measure map without gaps. Missing maps show a diagnostic while preserving the text.
Repeats reuse the written placement; moving bars does not automatically rewrite the stored starting measure.
Score and print spacing reserves the measured width of each lyric token without changing its anchor or font.
Long words can widen measures and move systems. If a complete measure still cannot fit, the view reports
that its lyrics need more width: widen the editor, or reduce print scale/use wider paper. It does not compress
the words into one another. Widening the view restores the score and its caret/playhead positions.
Native TG files retain lyrics. GP4/5 import accepts the first lyric line and refuses additional nonempty lines.
See SONG_FORMAT.md for the exact token and measure rules.

When two written voices occupy one Pattern cell, choose the labeled source-note chip before editing one note.
An explicit rectangular selection includes both voices; a bare ambiguous cursor refuses edits and copy/cut.
ROLL gives coincident notes separate hit targets. Generated release markers navigate to their source and remain
read-only. The agent's selection report preserves the chosen note identity as well.

**Chord diagram** edits a shared annotation at the selected beat: its name, first fret, and each string's
muted, open or fretted position. Apply changes the annotation; it does not replace the played notes. String 1
is on the right in the diagram. First fret 0 keeps automatic placement; no frets are clipped to fit the window.
Remove clears the annotation and Cancel discards the dialog edits. Both voices of one beat group share it,
including a rest voice. Independent beat groups can occupy the same onset after Free editing; they retain
separate annotations, strokes and subsequent duration behavior across save/reopen and TG interchange.
Normal Insert rest, caret-rest deletion and unannotated Fit retain these groups when moving one voice.
Chords and strokes follow the last sounding voice; text stays while another voice (even a rest) remains.
Deleting a rest retains its group's text on a surviving voice. Conflicting destination annotations and
inexact standalone-IT stroke timing refuse the whole edit. Fit can move annotated note groups with the same
transfer rules; consuming annotated rests or changing a peer's timing/notes still refuses the whole edit.
Guitar Pro export accepts a redundant local group label, but refuses independent groups at the same onset:
TuxGuitar's GP reader merges them. Use TG interchange to preserve that distinction.
Whole-beat copying carries the diagram; copying individual Pattern notes does not. Removing the last sounding
note at that onset clears its diagram, while an annotation can be explicitly attached to an existing rest.

**Replace voice notes from diagram** also enters the frets as played notes in the selected voice, keeping its
written duration. It replaces that voice's notes and their effects with fresh notes at the chosen entry velocity
(initially 95) and the track instrument. Played strings replace same-onset notes on those strings in the other
voice; muted strings leave that other voice alone. The dialog previews the affected voice, strings and pattern
uses. A reused pattern changes at every occurrence. Ties touching replaced notes require the explicit remove-ties
choice; surviving continuations then become new attacks. This differs from TuxGuitar's implicit tie predecessor
lookup and avoids silently changing tie ownership. An all-muted replacement clears the selected voice if either
voice sounded and retains the diagram; it does nothing when both voices already rest. The operation is one undo step.

The diagram's custom library stores named fret shapes separately from songs. Save, rename and remove take effect
immediately, even if you later cancel the dialog. Loading a shape changes only the draft until you apply it.
Names must be nonblank and unique. Shapes retain their string count and absolute frets, without tuning or capo;
an incompatible string count or fret range is rejected. A different tuning can change the harmony of the same
shape. Concurrent or stale library edits refuse without replacing newer work. The file is `custom-chords.json`
in VultureTracker's per-user folder; malformed data is reported and left intact.

**Recognize names** proposes names for the entered frets in TuxGuitar's order. A chosen name changes only the
dialog draft; it never rewrites frets or automatically replaces your authored label. Sharp/flat changes spelling.
Names use the track tuning without capo, as TuxGuitar's chord-shape editor does. Any displayed scores are source
heuristics, not confidence probabilities. Agents use `recognize_chord` with the current revision and track ID;
recognition leaves the song, library and undo history unchanged.

**Generate shapes** uses the chosen root, quality, bass and extensions, with normal, inversions, close-voiced or
open-voiced profiles. Fret bounds, open-string preference and result count control the search. Results retain
TuxGuitar's order; choosing one copies it into the diagram draft. Use the existing annotation, note replacement
or library action to keep it. Names use tuning without capo; playable frets still respect capo, the track's
maximum fret and native pitch limits. Agents use `generate_chords` with the same revision and track ID.
Searches exceeding 1,000,000 work steps or 50,000 candidates refuse with a narrower-range suggestion rather
than return a partial result. Generated voicings are suggestions; evaluate their playability for your instrument.

Use Copy/Paste or scoped Ctrl+C/Ctrl+V to copy authored beats. Drag, Shift+click, and the Extend selection buttons
can span written measures and order occurrences; First/Last extend to the written song's ends. Repeated visits
remain distinct. Ctrl+click starts/changes a local pattern selection. Cross-occurrence selections support Copy,
Cut, Repeat, semitone changes (Shift+Left/Right) and adjacent-string shifts (Shift+Up/Down).
Delete, Cut and Rest affect the active voice in local and cross-bar selections. Cut copies both voices;
Clean Beat (Ctrl+Delete) clears both, and the explicit Delete Beat button removes the selected authored beats.
An empty active voice does not borrow notes from its peer. Rest-only Delete/Cut closes each selected rest
once, using the existing same-voice gap closure. Pitch/string shortcuts
target the active voice in local and cross-bar ranges. A semitone shortcut keeps each note on its string and
refuses the whole change if any fret is outside that string's range; it never reallocates the fingering.
**Transpose** opens
with **the selected phrase** for a cross-occurrence range; choose an interval from -12 to 12. All tracks is
disabled for this scope; whole-track and caret-measure scopes remain available. The whole range remains
selected after each successful change, with one Undo. Range pitch edits need unique, unapproved patterns and
complete ties for the affected voice; impossible frets, occupied strings (including sustained notes), unsafe boundaries and
tracker conflicts refuse atomically. Adjacent-string shifts retain sounding pitch and original playback
channels, including mixer/instrument ownership, and compensate grace/trill frets. They refuse any change to
the native performance events, such as an affected harmonic node or hammer/slide link; unrelated passages
remain editable. Selected transpose refuses harmonic nodes that cannot preserve the requested sounding
interval. This is deliberately safer than TG dropping unplaceable notes. A selected phrase also accepts
ppp..fff dynamics, an exact velocity (0..127), or clearing its authored velocity. The velocity field and visible
Mixed summary describe the selected voice. **Range articulation** explicitly chooses Set or Clear for ghost,
accent, heavy accent, staccato, palm mute and dead notes; clicking the technique then applies that choice to
every selected note in the active voice, following TuxGuitar. Switch Voice to edit the other voice; Ctrl+A and
Copy still include both voices. Beat strokes affect the selected onsets in both voices. Existing mutually
exclusive technique rules still apply. Repeating an
already applied setting makes no history entry; these commands leave the clipboard unchanged. Unique,
unapproved patterns and complete ties in the affected voice are required. The strict IT compiler checks the whole result before
saving: missing velocity required by a dynamic technique, off-tick short gates or occupied tracker cells refuse
the entire edit. It never substitutes an arbitrary velocity or rounds a gate to make the edit fit.
Cross-measure **Duration**, Longer/Shorter, dots and tuplets target **only the selected voice**, using the same
Place/Fit rules as a local beat. The caret's chosen written duration applies to each originally selected beat;
this does not stretch the phrase. +/− clear dots and retain tuplets. Without Fit, onsets stay put and shortened
notes leave plain rests. Longer notes can consume selected bare rests; a rest already consumed or rebuilt by
an earlier target is not edited twice in the same command. The resulting selected phrase includes its new
rests, ready for the next duration edit, Copy or expression change. A single caret stays a single target.
Repeated Apply is a no-op. Fit may move or resize following plain notes within each existing measure.
A beat that has insufficient room or would cross its bar end keeps its previous duration; other valid targets
still change in the same Undo step, and the status reports the kept beats. Protected notation, changes to
another voice and raw tracker conflicts still refuse atomically. No new bars or rebarring.
Standalone IT supports exact note endpoints between rows when they fall on its tick grid (for example a
thirty-second at speed 2), using note delay/keyoff commands. Silent rests need no tracker timing cells.
Notes between ticks or occupied delay/keyoff cells still refuse; timing is never rounded.
Duration edits now resize tied beats too: adjacent links stay tied, including across bars, and Fit can move
plain tied notes together within a measure. If shortening or moving a beat separates two linked notes, the
broken link is removed and the following note plays normally; the status reports how many ties were removed.
This applies TuxGuitar's separate **Fix tied note** repair immediately, rather than saving its invalid tie flags.
One Undo restores both durations and links. Single-note and range duration edits both check exact standalone
IT compatibility before saving. A shared or approved range pattern, unsafe Fit or strict IT conflict still
refuses atomically. Other individual-note edits still
need a local target. Select all spans the written track.
With an active beat selection, Ctrl+C copies beats. Without one it opens the existing measure controls;
the explicit Copy selected beats button can still copy the caret beat. A successful beat or measure copy
replaces the other clipboard kind. Failed copies and closing the controls preserve the previous valid copy.
Ctrl+V and Paste use that latest kind: measure data opens the measure Paste/Insert controls; beat data
replaces whole beats in both voices at the earliest selected onset, or at the caret when there is no selection.
Forward, backward and cross-bar selections use the same earliest position. **Paste safe** keeps the
empty-destination behavior. Pasting safely across patterns needs empty spans in the copied tracks/voices and unique destination patterns.
Explicit rests count as authored destination content. Make reused destinations unique first. Occupied/approved
spans and raw-note conflicts refuse atomically. **Paste replace** uses TuxGuitar's whole-beat timing:
clear both destination voices until the copied cohort's longest duration fits, replace all beat attributes,
then advance to the next available beat after its shortest duration. A short pasted note removes the whole
longer destination note. Unequal voices can place later copied attacks later than their original offsets.
Copy includes unwritten rests between selected beats for whole-beat replacement, including across source
bar lines. Safe/span paste and sparse selections keep the selected authored beats and their exact offsets.
Unsafe written-bar/backing-pattern overflow and insufficient song room refuse the entire operation.
**Paste span** retains the native alternative: replace only the copied lanes over the exact phrase extent,
including gaps, preserve exterior note fragments, extend compatible measures and split crossing notes with ties.
Replacement requires unique, unapproved destinations even for a local span. Changes to shared stroke/chord
metadata affecting retained voices and unsupported technique splits refuse. Surviving ties are repaired and
copied internal ties receive fresh IDs. Other tracks and raw cells stay intact; Paste span also preserves uncopied voices. Explicit Mix and Push
are native conveniences described below. Ordinary untied single-pattern safe paste retains its shared-pattern behavior. Paste assigns fresh IDs and
retains both voices, techniques, beat text/chord diagrams and internal ties. Copy omits links to notes outside
the copied phrase. A pasted phrase stays selected for the next edit. Track lyrics, raw tempo/effect
commands and measure headers are not clipboard content: destination playback headers continue to apply.
The copied payload stays unchanged after paste or later edits; the whole paste is one Undo. The score's playback marker
follows the shared transport, including rests. Shift+arrow keeps TuxGuitar's pitch/string commands.
Copy also retains the source tuning. Paste into another track, or after opening another song in the same
window, preserves sounding pitches and finds destination fingerings. It uses the destination instruments and
channels. Both voices and internal ties travel together; impossible fingering or pitched/percussion mismatches
refuse without changes. The portable clipboard survives opening another song in that window.
Cut (Ctrl+X) copies the selection and replaces deleted notes with written rests. Across occurrences it cuts whole
selected chords in both voices, preserves existing rests/timing, and requires unique unapproved source patterns.
Rest-only cross Cut closes each selected voice's local measure gaps. Repeat (Ctrl+R) across
occurrences repeats the exact phrase immediately after its end using the replacement guards above, adding
compatible bars and tied fragments when needed. The entire repeated phrase stays selected. Local Repeat retains its existing
next-beat behavior and measure extension. Both commands use one shared Undo and are disabled during playback.
Failed Cut/Repeat leaves the prior clipboard intact; source edits publish only after validation. Cut removes
incident boundary ties; fully selected internal ties travel in the clipboard. TG's replacement manager can lose later notes when
a long second-voice rest overlaps shorter first-voice beats; this path preserves exact authored timings instead.
Agents use `score_command` with the same selection, revision and approval guards for Cut/Repeat.
Across measures, Rest clears the selected voice; Delete clears selected notes in both voices, preserving their
written durations. Delete beats removes the selected onsets; Clean clears both voices and beat annotations.
Incident ties are removed in the same Undo. Pitch/expression changes still require complete connected ties.
Ctrl+Left/Right moves between measures; Ctrl+Shift+Left/Right goes to the first/last measure.
Every TAB side panel (Track setup, Lyrics, chord diagram, bend/tremolo curve, Transpose, Measures) closes the same
three ways: its button again, the ✕ Close at its top, or Escape (also from inside a field).
The **Measures** panel's top row is TuxGuitar's Measure menu, on measures numbered as the order list counts them.
It sets From/To to the caret's measure when the panel opens. Add before/after inserts Count empty measures with the
neighbouring measure's meter, without its marker or repeats. Remove deletes those measures and their time in every
track. Clean empties this track's notes and rests in them. Copy takes this track (or all tracks) and Paste replaces
from From on, adding measures at the end when needed. Insert paste puts the copy before From. Each is one undo step.
A measure plays its pattern, so editing a pattern used at other orders changes those too; the status says so.
**Move passage** moves From/To before the numbered destination; the last measure plus one means append.
**Make passage unique** gives reused patterns in From/To their own copies before further editing, in one Undo.
Measure copies contain score parts, not raw tracker cells. Map each copied track to a destination in the panel.
**Copy meter, repeats and staff headers** and **Copy markers** are independent choices. Replacing headers
requires coverage of every destination track, since meter and repeats affect the whole arrangement. Without
Copy markers, destination markers remain. Incompatible grids, protected patterns and raw conflicts refuse.
The Move beats amount accepts quarter-note units, such as `1/3`; blank uses the caret's current duration.
The amount must land exactly on the supported timing grid. Native movement keeps the requested exact offset;
TuxGuitar may repack rests differently for fractional movement.
Structural edits retain valid ties and report removed boundary links. Removing every measure and songs whose
measures divide a pattern refuse. Clear entry removes only a measure's entry (meter, marker, repeats), not its notes or time. Alternate
endings are eight checkboxes, the passes that play the measure; as in TuxGuitar's dialog, endings already taken
since the last repeat start are disabled. A meter with a new length is TuxGuitar's time signature change: the
measure (or, with "to the end", every later one too) takes the meter and the bar lines after it move, while every
note keeps its time and flows into the bar it now falls in; bars are added at the end when the music needs them.
It refuses, changing nothing, when a bar from there on is a pattern played at another order (make them unique), has
tracker commands (they would move), incompatible grids or unsupported technique splits. Plain notes crossing
new bar lines split into tied fragments without changing sounding time. Beat unit sets how the tempo is written (eighths, dotted quarters…);
the playback tempo stays, and a unit that cannot express it exactly refuses. The score's header line counts
TuxGuitar's measure errors for the current track (a voice with a gap, or ending before its bar does); hover it for
the bars. **Free edit** (beside Fit within measure) allows duration changes and Insert rest beyond a bar's end.
Free duration takes precedence over Fit and repacks this track's beat groups by the ends of their voices,
as TuxGuitar does. Both voices on a group move together; sounding notes, rests and annotations stay attached.
Free duration closes implicit gaps; write a rest when that silence should move with the phrase. Matrix Free entry keeps its original anchor
and refuses sounding overlaps. Insert rest moves the rest of the bar right. The bar grows, keeps its meter and counts as "too long" until repaired
(remove what overflows, then Apply measure with its meter shrinks it back). TuxGuitar lets an overfull bar sound over
the next one; here the following bars wait. It needs the bar to end its pattern and the pattern to play once;
Independent measures can prepare reused/divided patterns in the same Undo step. Changing meter can rebar the
overflow without changing its performed timing. Free shrinking can leave trailing silence in the measure-error list.
Authored bars with an internal gap, early ending or overflow require Free mode automatically, including after
reopening. The checked, disabled control explains why; it returns to your chosen mode when the bar becomes valid.
An entirely empty voice is valid. An unmetered pattern that grows through Free editing first records its exact
original length as a meter, so overflow stays visible and Apply measure can remove empty backing rows afterward.
**◀ Move beats / Move beats ▶** (beside Insert rest) are TuxGuitar's Beat > Move beats: this track's beats from the
caret to the end of the song move by the caret beat's duration, crossing bar lines and keeping their ties; moving
left removes the caret beat first. One undo step. A pattern played at another order refuses (make those measures
unique first). Crossing plain notes split into ties and rightward overflow adds compatible measures. Unsafe raw
tracker conflicts, incompatible grids and unsupported technique splits refuse atomically.
Ctrl+Shift+Up/Down changes tracks while preserving the musical position. The navigation buttons also provide
first/last track commands.

The measure panel's **Tempo at start** edits the selected measure's start, or the current order's start when no
measure is selected. Effective BPM shows the inherited tempo; an explicit change writes the same T command
visible in Pattern. Clear removes that command and restores inheritance. Tempo continues until the next change,
and moving a measure boundary does not move its tempo command. Reused patterns require **All uses of this pattern**,
or use SONG's **Make unique** first for one occurrence. Changes share undo/redo and retain notes and other effects.
The current range is integer quarter-note BPM 32–255 at exact tracker rows; fractional-row starts, automation-owned
tempo and rows without a free effect column refuse instead of rounding or replacing another control.
The measure's Swing control selects straight, eighth-note or sixteenth-note triplet feel. Qualifying notes
change their performed timing together in live playback and exports; their written Pattern positions stay fixed.
The score and print preview show the feel annotation. Dotted notes and tuplets retain their own written rhythm.

**Fade in** marks the selected note independently of its chord and other voice. Native playback, audio renders
and MIDI now share TuxGuitar's expression staircase: values 31 through 126, then reset to 127 at the gate end.
It affects the whole logical track, including unmarked sounding notes and release tails, composed with their
original velocity/layer gain. Tied continuation flags remain authored; only the head starts a ramp. Grace uses
the pre-grace gate; strokes/swing use the performed gate. Simultaneous callbacks retain source insertion order.
This deliberately makes fade audible in the app, beyond TuxGuitar's default live mode. Raw notes/instruments on
an expression track refuse because they lack owned voice identities; unrelated tracker channels remain intact.
Uniform fades use native engraving symbols; sparse notes keep compact string labels and parameters in tooltips.

The beat controls set **Stroke** direction and duration value, plus a separate **Pick direction**. Stroke spreads
the chord's attacks in string order; Pick direction changes only its notation. Both apply to the shared beat
across its two voices, including a rest voice. Choose None and apply to clear the marking. Pattern keeps the
written note positions, while playback highlighting follows the delayed attacks. Editor and print show the
direction glyphs and stroke duration value.

Staccato, Palm mute and Dead shorten the sounding gate while preserving written rhythm. Let ring extends it
according to the following notes and rests in the same voice, using TuxGuitar's timing rules. It works on a
selected note or chord without requiring velocity; enabling it clears Palm mute and Staccato, and either of
those clears Let ring. Gaps alone do not lengthen the sustain. Ordinary notes can overlap a ringing note on
one channel with explicit instruments and empty/global-tempo/global-volume backing. Harmonic, repetition and
grace heads can also overlap independently in this domain. Envelope carry, random source variation and raw
local conflicts currently refuse. Supported native TG and GP imports retain it;
TG export preserves it. Bend and Tremolo bar
open a curve editor with presets and editable `position:value` points; positions run from 0 to 12. Vibrato and
Slide toggle on the selected note or chord. Slides retain the next note's attack. Curve controls follow their original
note through its release tail, and edits share the same undo history as fret entry. Bend/bar/slide/dead exclude
one another when enabled; vibrato may remain written alongside a curve. See SONG_FORMAT.md for exact units and
the native receiver's pitch-range choice. MIDI export assigns independent melodic channels to pitch-controlled
notes and harmonic layers, with a 12-semitone bend range. It reports pitch-wheel rounding and refuses exhausted
channel capacity, ambiguous program ownership or unsupported percussion routing before writing output.
Native MIDI export offers transpose (-24..24) and Strip CC/PC in RENDER & EXPORT and Score collection.
Transpose follows TuxGuitar: principal notes, drums, tremolo repetitions and harmonic layers shift; grace
notes and alternate trill pitches stay fixed, even for a same-key trill. Out-of-range keys refuse instead
of clipping. Strip removes sound selection, volume/pan/expression, fades and bend-range setup while keeping
pitch-wheel events; the receiver's bend range then determines their sound. It also adds TuxGuitar's one-quarter
lead-in (0.5 seconds before the first tempo). Export options leave the song, Pattern and Undo history intact.
Collection settings can be remembered. CLI: `export song.yaml -f mid --midi-transpose 12 --midi-strip`.
The agent's `export_song` accepts `midi_export: {transpose: 12, strip: true}`. These settings require a native
score; tracker-only MIDI keeps its existing behavior. Harmonic octave creation with an instrument keymap
still refuses when no qualified sample mapping exists.
Dynamics presets and the numeric velocity box set authored MIDI velocity 0..127 independently of the Pattern
volume column. Default removes the override; zero keeps a silent voice, and 127 retains its inherited gain.
Uniform positive velocities engrave the nearest conventional dynamic. Exact custom values and mixed velocities
remain available in the controls and note tooltips; engraving does not quantize playback. TAB note previews use
the explicit velocity, including zero; notes with inherited velocity keep the default preview gain.
MIDI export preserves positive authored velocity and refuses zero because MIDI treats it as note-off.
Tap, Slap and Pop mark the selected notes; choosing one clears the other two on those notes. They do not change
sample, instrument, velocity or playback timing. Tap is separate from a tapped harmonic. Uniform chords show
T/S/P; mixed or partially marked chords use string-specific text in the editor and print. Tied continuations
retain their own markings. Standalone IT preserves their native sound and explicitly warns that the semantic
markings are omitted; they remain in the source score and its history. No tap/slap/pop sample substitution or
sound processing is added. A sampled tapping/slapping sound must already be in the authored instrument.

Ghost, Accent and Heavy accent adjust performed velocity while keeping the authored value; Hammer affects the
following note on the same string and voice. Affected attacks require explicit velocity. Beat text and colored
measure markers appear in the score and print preview; marker navigation moves the shared cursor.
Harmonic selects Natural, Artificial, Tapped, Pinch or Semi on the selected note or chord. Touch chooses the
artificial harmonic interval. These require explicit velocity; their ordered sounding layers retain independent
gain while following the same note's pitch controls and release. Written pitch and fingering stay unchanged.
Clear the type to remove the technique. Native TG and GP3–5 import retain supported harmonic types and data.
Trill alternates with an absolute fret on the same string; Tremolo picking repeats the written pitch. Set the
repetition rate and an explicit velocity, then apply to the selected note or chord. Tied continuations keep the
head note's rate and velocity. Repetition takes precedence over harmonic playback and clears incompatible pitch
techniques. Clear removes the repetition without changing written rhythm. Trills are shown per note; picking
strokes apply when the whole chord shares a representable rate, with text identifying mixed-note cases.
The quarter-note trill option works here; TuxGuitar 2.1.0 displays that option but its dialog fails to save it.
Grace controls set an absolute fret, 16th/32nd/64th duration, independent velocity, transition label,
before/on-beat timing and dead-note flag. Apply to a note or chord; Clear removes only grace. The written
note stays at its original Pattern position. Before-beat grace falls back to on-beat near song start;
unsupported overlaps refuse. Editor and print use grace-note glyphs without verbose parameter paragraphs.
Mixed timing keeps a compact "Grace (mixed timing)" label because it cannot share one grace beat honestly;
exact per-string details remain in the controls and note tooltips. Stroke direction uses its brush arrow,
with direction/rate in controls and tooltips. Authored beat text remains on the score.
Transition labels are notation only. Native TG and GP3–5 imports retain supported grace data.
Track setup also offers optional MIDI program/bank fields for file interchange. These do not change the sample
instrument you hear in VultureTracker. MIDI export writes assigned programs and banks before the first note.

**Print preview** opens the arrangement in an in-app dialog. Choose the tracks, inclusive bar range, staff/TAB layout, paper,
orientation, margins and scale, then Update preview. Select bars in Page breaks before to start new pages;
other page breaks follow the paper's available height. Print / Save PDF opens the browser's print dialog.
Choose an image page and Save SVG, PNG, JPEG or BMP for that page. SVG includes the music font and its license;
raster images render at twice the preview resolution (192 dpi). JPEG uses 95% quality; BMP is uncompressed
24-bit color. Native save dialogs choose the output location.
An excerpt identifies its source bars and numbers the extracted score from 1. Select one track for a part.
The preview uses a snapshot: close and reopen it after editing the song. Close preview or Escape returns to
the editor without changing the song or its undo history.

**Song properties** saves the full title, artist, album, author, date, copyright, lyric writer, transcriber
and comments with the native score. The short tracker title stays separate. TG retains these credits;
GP3–5 retains supported credits and reports its missing date field. Printed parts start with the saved credits
and include page numbering. A single-track print names that part. The score renderer supplies notation;
SVG/PNG preserve ordinary text fonts separately from the bundled music font.

**Save setup template** in Song properties stores the band's track/tuning setup, meter, tempo and credits
for NEW SONG. It leaves out music, raw tracker cells, lyrics and audio assets; the new song gets placeholder
sounds. Custom templates and **My tuning** presets live in this app profile and persist across songs.
Save another name for a separate preset; saving the same name updates it. Their Delete buttons remove only
the saved preset. Applying a tuning still uses the normal pitch/fret retention choice and one Undo.
Track setup can duplicate a complete part, move it up/down, or remove its notation after selecting the
delete-notes checkbox. New/duplicated tracks append independent channels; reordering does not move tracker
channels. Removal retains raw cells and sound assets. The existing 64-channel limit still applies.

**Paste mix** merges compatible rhythms and chord notes in copied voices. **Paste push** moves later
material in those voices by the exact copied length, splitting ties and adding bars where necessary.
Other voices stay in place. Incompatible string, shared-annotation, technique or tracker-cell conflicts
refuse atomically. These are native conveniences; the pinned TuxGuitar clipboard uses replacement.
**Move/Copy to other voice** applies to the selected phrase and offers Empty destination, Mix or Replace.
Copy finds free strings for simultaneous notes; impossible copies refuse. Each edit is one Undo.

**Rehearse selection** opens the REHEARSE panel with the selected bars and track. Set start/target speed
and the increment per loop (default 80% to 100% by 5), count-in and metronome. **Follow repeats and endings**
plays the complete continuous traversal within the selected bars, including a return that skips the first ending.
**One visit** selects a single completion; **Visit** chooses among available traversals. A passage never silently
includes bars outside the selection; unreachable ranges refuse. Clear **Loop passage** to play once and stop at
its exact end. Meter-aware clicks, the initial one-bar count-in and speed changes run on the audio clock. Track Solo
and Mute apply to every channel of that part while retaining the existing mixer settings. Stop cancels a
pending count-in or load. An arrangement edit stops practice and requests a restart; ordinary paused playback
retains its repeat visit after an edit reload. Rehearsal does not write tempo, notes or history; listening acceptance
is still yours. Printed pages identify the part, source bars and current section/continuation on every sheet.

The native player schedules written fractions at exact sample frames, including between tracker rows. Pattern
shows those notes as exact-position markers and ROLL draws their fractional lengths. Ordinary Pattern cells remain
editable on their row grid. Whole-song and section audio exports use the same paired tracker/score schedule,
including stems and current mix settings. A section start reconstructs preceding instrument and note state;
its end stops new attacks and effects while existing voices ring for the chosen tail. Native MIDI export preserves
exact beat positions and performed gates when the MIDI timing limit permits them. Its result lists sound/notation
losses and encoded tempo changes; unresolved tracker state or a note carried into the selected section refuses explicitly.
**IT export of a native score** (RENDER & EXPORT → IT, or `build song.yaml -o song.it`) writes a standalone,
editable module: the score's notes become tracker cells (note, instrument, note-off where nothing else ends the
note), with tracker cells the score does not own (effects, tempo) kept. An authored velocity becomes the volume
column, round(base × velocity / 127) half up, where base is the note's own volume or its sample's default volume, so
the IT plays as loud as native playback does (to the IT's 65 volume steps). The last note releases with the song's
end. IT export covers the whole song with the saved or current mix. Repeats and alternate endings expand into
ordinary IT orders/patterns using the same traversal as native playback. Performed ties and tempo resets are kept;
the authored song, shared source patterns and undo history are unchanged. Each played measure fragment gets a
pattern, up to 254; larger expansions and ties whose predecessor is skipped refuse before writing. IT tick timing
is limited to whole audio samples, while the native plan uses exact rational frames.
For unrepresentable sub-tick attacks, gates or pitch controls, the export can render short affected string/channel
passages into samples, bounded by silent rows. The export warnings and IT message name each channel and time range.
Those passages play as audio samples in another tracker; other passages remain normal editable tracker notes.
The native document keeps every note, Pattern relationship and Undo entry. This fallback uses existing samples
and the native renderer, preserves release tails, and refuses clipping, unsafe raw controls, plugins, randomized/
carried instrument state, repeated orders, missing silent boundaries or insufficient sample/instrument slots.
It is limited to ten-minute arrangements and does not apply to strict edit validation. Ordinary IT tick rounding
and volume resolution still apply to the remaining tracker notes; this is not sample-identical whole-song playback.
Percussion tracks keep their authored drum keys (1–100), instrument/sample routing and existing instrument keymaps:
the mapped sample and playback pitch stay intact, including simultaneous hits on separate channels, both voices,
per-note instruments, velocity/volume and repeats. One-shot samples and instrument-envelope releases behave as in
native playback. A drum key without a mapped sample, conflicting notes on one channel or an out-of-range key refuses
before writing; exporting does not invent a GM kit or change samples.
Ghost, accent, heavy accent and hammer-derived velocity use the native player's performed dynamics, converted
to IT volume. Staccato, palm mute, dead-note gates and let-ring use its performed key-off times, including ties and
repeat context. Key-off starts the instrument's release envelope; it is not a sample cut. A release between rows
uses NOTE OFF with SD1–SDf when it lies exactly on an IT tick and the cell is free. Strict projection refuses
nonintegral tick times, a release sharing its attack cell, conflicting commands, held overlaps on one channel,
inherited instrument/volume state and context-dependent reused patterns. Export can use the bounded sample
fallback above for sub-tick performance; it never rounds a gate merely to make it exportable.
Bends, tremolo-bar/whammy curves, vibrato and same-string shift slides consume the native player's discrete pitch controls, using IT fine
linear portamento (E/F), with the original samples, keymaps and non-carried envelopes. On-row controls retain their
event times and pitch values; IT frequency/audio-tick rounding still applies. Off-row controls round to the nearest
row only if every turning point/end value survives and the entire discrete trajectory stays within 37.5 cents of
native playback. CLI and the export result show a warning for this bounded approximation (at most half a row in
control placement). This is an admission ceiling, not an exact-parity claim: the measured 120-BPM fixture's worst
20-ms pitch-window error is 32.83 cents; measured threshold displacement reaches 22.41 ms including cycle detection.
Larger errors, an oversized single pitch step/reset, missing slide targets, raw effect conflicts, controls after
key-off, a rounded reset landing on another attack, nonlinear slides, non-cut NNA, duplicate-check actions or carried
envelopes refuse before output replacement. Separate strings/channels, ties and repeats retain their native plan;
unsupported combinations still refuse. Existing pitch envelopes are retained, not replaced by the notation curve.
Whammy retains its own native units, negative dives and per-note/string scope. The measured quarter-note dive,
rise and mixed curves at 120 BPM differ by at most 17.29 cents in 20-ms pitch windows and 16.05 ms at pitch
thresholds across 44.1/48 kHz; these examples do not guarantee that steep or deep curves fit the same bounds.
Trill and tremolo picking export the native player's actual pulse notes, pitches, velocities and releases as editable
IT attacks, including SDx delays on exact ticks. Trill rates 4/8/16/32 and picking 8/16/32 fit suitably fine rows;
multiple attacks in one cell, off-tick attacks (including ordinary 64th trills) and unsafe collisions refuse.
The final TG pulse ends one legacy tick early: only that final key-off may extend by 1/960 quarter to land exactly
on an IT tick, with an explicit CLI/UI warning (62.5/tempo milliseconds, .521 ms at 120 BPM). Other off-grid gates
refuse. At 44.1 kHz, IT's tick rounding also changes the short crossfade from the previous voice; exported audio
is not sample-identical to native playback. Original samples/keymaps/envelopes remain; cut NNA, no duplicate
checks or carried envelopes are required. Native repetition conflicts such as dead/hammer/pitch curves still refuse.
Natural, artificial, tapped, pinch and semi harmonics export the native player's ordered pitch/velocity layers.
The final, primary layer stays on the original channel; up to two extra channels per harmonic parent hold its
lower layers, including distinct same-pitch semi layers. These are ordinary editable IT notes using the existing
sample keymaps and non-carried envelopes. The extra channels inherit the saved channel volume/pan/mute and the
current export mix/solo state. New parent attacks cut unused lower lanes, including already-released envelope tails.
This does not add channels to the authored song or change native playback. The 64-channel limit, inherited or
randomized instrument state, non-cut NNA, duplicate checks, carried envelopes, instrument pan/filter overrides,
sample pan/auto-vibrato and raw local commands on harmonic parents refuse before writing. Global tempo/volume
commands and unrelated tracker channels remain intact. A harmonic ending exactly at song end needs a following
release row. Pitch curves retain the existing bounded admission rules; ties/repeats use the native performed plan.
In particular, a lower harmonic slide layer can refuse an oversized final reset even when its parent's next
plain attack would reset the parent channel; lower lanes must satisfy the reset bounds independently.
The measured five-type probe is within .017 cent; IT volume rounding changes individual layer gains by up to 2.421%.
At 44.1 kHz, tick rounding shifts the last measured attack by 108 frames and its final tail by 127 frames. A short
5-ms transition differs by 56.09% relative RMS while settled audio differs by at most 1.16%; this is not waveform-exact
parity. The musical example and owner listening remain the practical sound check.
Brush/strum strokes export the native plan's actual string attacks and gates. Up starts with the lowest string
number; down starts with the highest. Shared voice/rest cohorts and tied-in strings follow native TG timing,
without moving written anchors or changing the source. A quarter-note cohort at stroke value 4 has three IT ticks
between strings and exports exactly; a quarter triplet at value 8 has one tick. Other combinations export only
when every performed attack/release fits exact IT ticks and available cells. Ordinary quarter-cohort value 8/16/32/64
offsets refuse; a single-string stroke has no delay and can export at every rate. Gates exhausted by the offset
retain native duration, including releases in a later pattern. Same-channel overlap and unsafe inherited state
refuse. Grace, repetition, harmonic and pitch combinations keep their existing bounds: delaying a slide's target
can require an unrepresentable reset and refuse. Pick-stroke remains a separate notation mark.
The nine-attack keyed probe measures pitch error below .027 cent, settled waveform error below 1.179%, and level
difference below .860%. At 44.1 kHz the last attack/tail shifts by -54/-74 frames from integer IT tick rounding;
one plain successor's fixed first 5 ms differs by 161.76% relative RMS (13.98% over 50 ms). This short cut-ramp
phase difference is separate from settled parity; physical listening remains necessary.
Grace notes export the native plan's separate ordinary attack and delayed main attack, preserving each pitch,
velocity, keymap and release. Before-beat grace can occupy a preceding pattern's gap; at song start it falls back
to on-beat, as native playback does. The main note can retain supported harmonic, pitch or repetition effects.
16th/32nd grace lengths are supported when attacks/releases fit IT ticks and available cells. 64ths, off-grid
dead gates (such as at 120 BPM), prior-note overlap, unsafe mapping/state and occupied cells refuse atomically;
dead grace at 160 BPM is representable on a fine enough row grid. No prior note is silently shortened.
Transition none/slide/bend/hammer labels remain notation only, matching current native semantics.
In the six-attack probe, measured pitch error is below .030 cent and settled waveform/level differences below
1.50%/1.35%. At 44.1 kHz, accumulated IT tick rounding moves the last attack/tail by -54/-72 frames.
One quiet grace transition differs by 25.13% over its first 50 ms and 121.09% relative RMS over its first 5 ms,
because the preceding voice's short cut ramp has a different phase. This is not waveform-exact parity.
Eighth/sixteenth triplet feels export the native plan's performed attacks and releases while preserving written
positions. Eligible plain pairs use 16+8 or 8+4 IT ticks; dotted/tupletted values and neighboring voice/rest rules
follow native playback. Source absolute phase survives odd meters and repeats/endings. Delayed notes and releases
use exact SDx ticks where needed, with no swing rounding. Off-grid gates, overlapping voices on a channel,
occupied cells, unsafe inherited state, unplayed context and conflicting shared-pattern occurrences refuse.
Supported grace/stroke/repetition/harmonic/pitch combinations retain their existing limits.
The five-attack keyed probe measures pitch error below .030 cent, settled waveform difference below 1.052%,
and level difference below .818%. At 48 kHz attacks match exactly; at 44.1 kHz integer tick rounding shifts the
last attack/tail by -54/-72 frames. One quiet second note differs by 110.20% relative RMS over its fixed first
5 ms (27.82% over 50 ms), due to the preceding voice's short cut ramp; settled parity is not waveform-exact parity.
Standalone IT fade-in projects that shared gain trajectory into volume-column cells without replacing samples,
keymaps or envelopes. Active fade attacks must be row-aligned. Controls round to the nearest row (at most half
a row), then to integer volume; the complete composed gain trajectory must stay within 6.25 percentage points
of native gain normalized to the note's original volume. CLI and export results report the measured bound.
This is a control admission ceiling, not an instantaneous audio-error guarantee. SDx on an expression row, raw
volume/effect ownership, non-cut NNA, duplicate actions, carried envelopes, randomized volume, conflicting shared
occurrences or insufficient final-tail reset space refuse. Other previously supported techniques retain their bounds.
The quarter-note probe measures a 3.085-point control bound; settled native/IT gain differs by at most 2.593 points.
Native gain steps match their expected frames at the first observable sample; IT volume ramps settle within
15/16 frames at 44.1/48 kHz. The final tail differs by -73/0 frames from integer tick rounding. Short transitions
and existing note-on volume quantization still prevent waveform-exact parity; the musical example needs listening.
Lyrics and chord diagrams export to standalone IT with explicit notation-loss warnings. Lyrics do not synthesize
vocals and diagrams do not generate notes; existing chord notes, source/history and score/print remain intact.
Unsupported written beat timing still refuses before writing. Game-loop export warm-up still needs native support. Native SPEED changes preserve musical position by preparing
the backing and score together at the new rate. The previous playback continues until that preparation catches up;
the score marker follows the currently sounding rate. Native loops capture their starting state once and restore
it on each wrap. Initial preparation and preparation after a playback-setting change can still pause while the
starting state is reconstructed.

Native repeats keep one written score and a separate list of playback passes. Pattern and TAB edits change the
source bar, so every played visit reflects the edit. Tempo restores on repeat entry; alternate endings can span
multiple measures. Source sections and loops include all their visits when those visits are contiguous; a disjoint
selection is refused. Listening notes record the selected pass and its actual time. Measures can divide a pattern
or span adjacent patterns when their boundaries align with tracker rows. Pattern/ROLL keep the original rows;
the playback cursor and listening notes map back from each performed fragment. Non-row-aligned boundaries refuse.

This is an initial editing surface, not complete TuxGuitar parity. Unsupported raw effects, overlapping beats in
the same written voice, flow commands and structural transformations are refused with an explanation before the song is
written. Remaining guitar techniques, complete measure/repeat editing,
interchange and the remaining print-layout options remain under development. The import dialog defaults to preserving
native GP3–5 notation; unsupported source features refuse before publication. Uncheck that option for the legacy
conversion described below. The CLI opts in with `import riff.gp5 --native-tab -o riff.yaml`. Native import retains
exact written rhythm, voices, ties, fingering, dynamics, supported techniques, beat text and measure markers, with
synthesized guitar placeholders for later sound selection. It requires fresh output destinations. `BACKLOG.md` records current checks and limitations;
`TABLATURE-PARITY.md` lists the full target.

Native GP imports retain double barlines and key changes. GP3/4/5 exports preserve double barlines and
shared key changes; TG export refuses double barlines because its model has no corresponding field.
For GP5 display fields, note duration percentages, accidental swaps and non-tempo mix changes, import
follows TuxGuitar 2.1.0's reader, which ignores those settings. Original values and locations are retained
in the song message with explicit import notices. Source MIDI effects are reported but not reproduced
by synthesized placeholders. Bend and tremolo-bar points use TuxGuitar's rounding; the report retains raw
coordinates when rounding changes them. This lets ordinary GP5 files open without claiming identical
Guitar Pro sounds or an exact source-file round trip. Standalone IT export subdivides rows for dense attacks.
When sub-tick performance still cannot fit, bounded affected passages can become rendered samples (see IT export);
native playback and the editable source retain their exact score timing.

Current TuxGuitar `.tg` files (archive format 2.0) also import as native scores, from the dialog or
`import riff.tg -o riff.yaml`. No TuxGuitar or Java installation is needed. RENDER & EXPORT's TuxGuitar format,
or `export riff.yaml -f tg`, writes the supported notation subset with explicit track MIDI assignments. This
currently requires whole-song measure coverage, positive authored note velocities, saved neutral mixer settings
and no residual tracker cells except absolute tempo changes at measure starts. Quarter-note tempos 32..255 are
preserved. Repeats and alternate endings retain their authored measures. Native GP supports ending 8; TG import/export
refuses ending 8 because the pinned TG reader changes its mask when reading the file. Mid-measure tempo changes,
other tempo markings, key changes, unsupported techniques, conflicting voice text and
other unrepresentable content refuse before output. The conversion report explains that sample sounds, DSP,
native IDs and shared-pattern structure are not carried by the file; imported sounds are synthesized placeholders.
Beat timing follows TuxGuitar's own reader. When TuxGuitar opens a file it closes any gap a voice leaves before a
beat (`TGSongManager.updatePreciseStart`), so VultureTracker's `.tg` import moves such beats to where TuxGuitar
plays them, with a notice for each moved beat. It refuses beats that TuxGuitar would delete or push past the end of
their measure. TG export refuses a score that TuxGuitar would re-time on opening, and names the beat: add a rest
before it, as TuxGuitar needs written rests where a voice is silent. TG files' measure line breaks, a track's
solo or mute flag and per-measure clef and key changes are kept as score fields: `line_break` on a measure,
`solo_mute` on a track, and `staff: {track: {clef, key}}` on the measure where a change starts. Clef and key
changes show in the engraved staff. Line breaks and solo/mute are not drawn or played here; they travel back
to TuxGuitar. Legacy 1.x files list them as losses. A tempo written in another beat unit (eighths, dotted
quarters…) imports as the measure's `tempo_unit: {base, dotted, value}` and plays the quarter tempo TuxGuitar plays
for it; the writer refuses one that no longer matches the measure's playback tempo. Score and print show the
authored note symbol, augmentation dot and value, including TuxGuitar's integer rounding (61 dotted quarters
plays 91 quarter notes per minute). Measures offers TuxGuitar's eight units, including whole notes; imported
32nd/64th or other dotted units remain visible and editable as the current imported choice. A raw Pattern tempo
change can make the written unit stale: score/print then show the actual quarter-note tempo and a warning.
Apply the same Beat unit again to recalculate its value; an inexact conversion still refuses without changing
the song. Beat-unit edits affect notation only, never the shared tracker/playback clock or IT timing.
**Guitar Pro 5** in RENDER & EXPORT, or `export riff.yaml -f gp5`, writes GP5.00 notation through
the same saved-job and safe-replacement flow. This first subset supports plain notes, explicit rests, two voices,
ties, supported integral-tick tuplets, text, markers, lyrics on one track, and authored repeats/endings.
Ghost, accent, heavy accent, staccato, dead notes, palm mute and let-ring retain their note ownership
on pitched and percussion tracks. Conflicting dynamics, palm mute with staccato, and a dead flag on an
incoming tied note are refused rather than normalized.
GP3/4/5 infer bass clef for a pitched track containing a tuning pitch at MIDI34 or below, as TuxGuitar does;
the instrument program does not decide it. Import retains that bass clef. Export accepts a matching explicit
clef and refuses mismatched, alto or tenor clefs that these formats cannot preserve.
Guitar Pro text encoding is selectable on the import screen, in Score collection and for GP3–5 in RENDER &
EXPORT. Use the encoding of the receiving application/file, for example `utf-8`, `cp1251` or `shift_jis`.
The default stays `cp1252` for existing VultureTracker files; TuxGuitar defaults to UTF-8. Collection settings
apply to both import and export and can be remembered. CLI import/export uses `--gp-encoding`; agent
`import_project` and `export_song` use `gp_encoding`. GP6/7 XML retains its own declared encoding.
Only Python's ASCII-compatible text codecs are supported, not every Java charset TuxGuitar lists. Invalid
bytes under an explicit encoding, unrepresentable or ambiguous text, and encoded byte-length overflow refuse
before publication. A default GP1/2 replacement is reported. GP1/2's second credit is author. GP3/4 retain
their shared author/writer limit; native GP3–5 retains transcriber text that TuxGuitar discards. These format
and charset differences remain explicit parity limits.

Pitched GP5 export supports all six tapped harmonic intervals, natural/artificial/pinch/semi harmonics
with data 0, trill rates 16/32/64 and tremolo-picking rates 8/16/32. Tapped harmonics store the written fret
plus the selected touch interval, matching TuxGuitar's reader. Other harmonic data and unrepresentable
rates refuse. GP4 also preserves tapped/pinch/semi data0 and artificial data0/2/3; it writes the matching
source-reader code instead of TuxGuitar's GP4 writer behavior that collapses artificial data to2. GP3 keeps
natural/artificial data0 only. Artificial GP5 harmonics
use canonical GP5 payload fields: the report warns that TuxGuitar ignores those fields and other players
may interpret them differently.
Nonempty bend curves and shift slides retain their written points/flags. Empty curves and combinations
of dead notes, bend and slide that TuxGuitar would discard on import are refused.
Vibrato and hammer-on/pull-off flags remain note-local, including tied-note metadata. Combinations
that would discard hammer or other techniques on import are also refused.
Whammy-bar curves export when every note in a written voice beat has the same nonempty curve.
Different curves or a mix of curved and uncurved notes refuse, because GP5 stores one curve for that
beat. Signed values, repeated point positions and separate voice ownership are retained.
It requires complete explicit measures, no unused patterns containing authored beats, consecutive beats within each used voice, explicit track programs,
and velocities on GP's grid (15, 31, 47, 63, 79, 95, 111, 127). Unsupported techniques, spelling, routing,
clefs and timing refuse before any output is published. Sample audio and DSP are not embedded.
The conversion report names format limitations, including TuxGuitar's loss of minor-mode metadata on import.
**Guitar Pro 4** and **Guitar Pro 3** (`-f gp4`, `-f gp3`) write GP4.00 and GP3.00 through the same conversion,
with their narrower formats' refusals (one voice per measure, song-wide swing, no minor mode; GP3 also no lyrics,
accents, staccato, palm mute, trill or tremolo picking). **TuxGuitar** (`-f tg`) writes the current 2.0 format, or
with `--tg-version 1.0`–`1.5` (the agent's `tg_version`) a legacy one. **ASCII tab** (`-f tab`), **LilyPond**
(`-f ly`) and **MusicXML** (`-f musicxml`) write text as TuxGuitar's own writers do, with LF line endings.
LilyPond export offers TuxGuitar's part number, inclusive bar range, version, staff/TAB, part names, grouping,
lyrics, beat text and chord-diagram settings in both RENDER & EXPORT and collection delivery. Blank part/range
fields include everything. Remember delivery settings stores collection choices for later sessions. The same
settings use `--lilypond KEY=VALUE` on the CLI or the agent's `lilypond` object. Invalid parts/ranges refuse;
disabling both staff and TAB resets both on, as TuxGuitar does. Export writes `.ly` source: rendering that source
requires an external LilyPond installation, separate from VultureTracker's native print/PDF renderer.
What a format cannot hold is refused or listed in the export's warnings as a loss. Broader GP5 coverage remains
unfinished.
One deliberate difference from TuxGuitar: GP6 `.gpx` and GP7 `.gp` imports, and a GP1/GP2 track panned to the raw
centre 64, bind a centred source pan as 63, as GP3–GP5 imports do, so the score exports to GP3, GP4 or GP5.
TuxGuitar plays these at pan 64, so their CC10 is one step to the left of TuxGuitar's.
Native GP imports follow TuxGuitar's measure-level tempo behavior: the last traversed change applies at the
measure start. Original beat positions and transition durations are retained in source notes, with warnings
when placement or a gradual transition is normalized.
Untouched imports retain exact source MIDI volume and pan, including Guitar Pro's center value 63. Native
audio keeps the existing tracker mixer scale; TG import reports its nearest 0..64 values. Explicit volume or
pan adjustments take precedence, even choosing the same value. WRITE MIX clears only that source binding;
Undo restores it. Track name/program edits preserve both; clearing MIDI or reassigning channels removes them.
Raw Pattern M/X commands still win. TG export supports a uniform mix across each part's strings. GP3–5
support native volume/pan multiples of four and exact representable source values; other values refuse with
a specific explanation. Unequal string settings, string mute, non-neutral effects and shared TG channels
remain guarded. Native sample audio and a TuxGuitar synth are separate sound sources.
Native TG files preserve trill and tremolo picking; GP4/5 imports preserve their encoded rates. If source effect
flags conflict, imports follow that format's TuxGuitar reader order and retain the removed values in warnings
and the song message. Unsupported rates refuse before writing the song.

### Editing imported scores and local collections

TAB keeps track, voice and rhythm controls above the score. **Focus score** closes the optional inspector,
grid, fretboard, piano and help panels; panel choices are remembered in this browser. The bar field jumps
to a written measure. Keyboard help lets you change supported score-action shortcuts and reports conflicts;
fret digits, file keys and the app's transport keys remain reserved. TAB's `a`, `b`, `g` and `t` open its
chord, bend, grace-note and text controls. Pattern keys and typing in fields keep their own behavior.

**Score view** saves page/horizontal layout, 50–200% zoom (100% reset), staff/TAB, all tracks, compact spacing,
printed dynamics, sounding/TuxGuitar written staff pitch and separate chord-name/diagram choices in this browser.
New score views default to **TuxGuitar layout**: horizontal all-track staff/TAB at 80%, hidden printed dynamics and written pitch
(one octave above sounding pitch, excluding capo, following the pinned TuxGuitar notation model).
These choices never edit the song or its Undo
history; print preview keeps separate settings. Percussion always uses the staff. Set **Staff click** to
**selects** to select notes there; its default still enters notes. In all-track view, clicks, dragged ranges,
the caret and the shared playback marker belong to the selected part. Technique and velocity edits apply
to the active voice of a selected beat range, including ranges contained in one bar, through one atomic Undo.
Unsafe standalone IT timing still refuses the entire edit. **Compact spacing** uses TuxGuitar's base written
duration widths (dots and tuplets keep that base), minimum active-voice width and adjacent chord spacing.
It disables while displaying multiple tracks and resumes when one track is displayed. Native full bend/grace
glyphs retain their collision spacing; TuxGuitar's simplified compact bend drawing is a visible difference.
Full toolbar/style customization and owner engraving acceptance remain parity gaps.

**Beam group stem** applies Up, Down or Auto to the caret voice's beam group, following TuxGuitar;
Ctrl+Up/Down sets its direction. The selected range does not expand that target. Rests break groups,
and compound-meter groups use the dotted-quarter division. **Track default** removes the override.
Stem edits share Undo and leave playback, Pattern notes and standalone IT unchanged. Shared patterns
remain editable when all uses have the same group; different grouping contexts require independent measures.

Shared patterns still edit every occurrence by default. Enable **Independent measures** to isolate the
affected occurrences as part of the edit. Structural operations can then address written bars inside a
larger pattern. **Prepare independent measures** converts a fully measured score to one pattern per bar.
Preparation and the requested edit share one Undo. Exact row timing, unrelated tracker cells and plain
crossing ties are retained; gaps, off-grid boundaries, unsafe technique splits and tracker flow/automation
refuse without changing the song.

From **OPEN**, choose **SCORE COLLECTION & BATCH CONVERSION**. Enter a local folder, optionally include
subfolders, scan and filter by filename. Open a native YAML song or import a supported external score.
For conversion, select files, choose a format and an output folder. Each input gets its own fresh subfolder;
existing outputs are never replaced. Native YAML collection includes the song's samples using PROJECT's
collector. External imports keep their intermediate native song and synthesized placeholder samples.
The result for each file lists outputs, format losses and errors; a failure does not discard other results.
Cancel stops between files and before an export publishes. Converted scores can be opened from the result.

**Band package** collects the native project and samples, exports TG/GP5/MIDI/IT, renders a WAV mix and
logical-part stems, and prints a PDF score and separate parts. Individual formats can also be selected,
including WAV/FLAC/MP3/OGG and PDF. Remember delivery settings saves paper, notation, scale, audio rate/depth,
parts/stems and format in this browser; it does not retain a destination or selected files. PDF uses an
installed Edge, Chrome or Chromium in headless mode (`VT_CHROMIUM` can select its executable). It prints
the same authored-score layout as Print preview and excludes unadopted Pattern notes. Part stems combine
the channels owned by each score track; remaining raw channels get separate stems. Each delivery keeps
`delivery.json` with settings, outputs, losses and errors. Successful formats remain available if another
format refuses or the batch is cancelled; an existing destination is never overwritten.

**Native MIDI import options** on the start screen and in Score collection expose transpose (-24..24),
quantization, shortest note (quarter through64th) and maximum tuplet division. They apply only to MIDI files
with editable native score enabled. Transpose shifts all note keys, including percussion, following TuxGuitar.
Collection's Remember delivery settings stores these choices for both batch conversion and opening MIDI files.
The CLI uses `import --native-tab --midi-transpose 12 --midi-shortest 32 --midi-tuplet 3`;
`--no-midi-quantize` disables approximate duration fitting. The agent's `import_project` accepts `native_tab`
and `midi_options` (`transpose`, `quantize`, `max_duration`, `max_division`). Existing tracker import remains
available with native score disabled. Native MIDI import follows TuxGuitar's note-velocity normalization and
final whole-track volume/pan; controller automation and other losses are reported. Imported source CC7/CC10
survives native editing and external export, with the existing tracker mixer scale for audio.
Maximum divisions6/7/9/10/11/12/13 extend TuxGuitar's dialog choices1/3/5 through its existing importer;
the broader options are an explicit UI extension, not identical dialog parity.

GP6/7 native import preserves double-dotted written rhythms and per-measure clef changes, including a return
to treble. TG export retains them. GP3–5 output still has its separate duration/clef limits; unsupported
interchange refuses rather than rewriting the score. Standalone IT timing must remain exactly representable.

Native import also accepts PowerTab 1.7 (`ptab-4`, `.ptb`) and TablEdit v2/v3 (`.tef`). Source volume/pan are
retained for MIDI/TG interchange, with nearest tracker mixer values for native playback. TEF's sixteen-step
attenuation/pan conversion follows TuxGuitar exactly; its near-center settings are no longer forced to center.
WRITE MIX overrides only the explicitly touched source binding, with shared Undo/Redo. These are bounded
readers: unsupported musical constructs refuse before publication, while display losses are reported.
PTB musical directions, rhythm accompaniment, standalone grace and multibar rests; TEF reading lists,
automatic accompaniment, pitch shifts, changing instrument routes and unsupported timing/ornaments remain
unsupported. TEF3 pickup/free-time measures refuse. Imports use placeholder sounds and preserve source
programs as metadata; they do not reproduce the original synth patches.

In native TAB, **Part** under **Part sounds** and the score's **Track** dropdown share one selection:
changing either immediately displays that part. Choose an existing sound and click Assign to change
one shared-document binding with one Undo. Note sound overrides remain unless Replace note sound overrides
is checked. Audition and part mute/solo use the existing player; they do not write the mix. Add SoundFont
preset opens the existing instrument controls. Sounds must remain representable by standalone IT: pitch
techniques require cut NNA, no duplicate-check action and no carried envelopes. Adjust the instrument in
Instruments when needed; assignment never silently changes its envelopes or voice policy.

**Separate overlapping voices** explicitly moves conflicting notes onto compatible spare channels within
the selected part, retaining fingering, pitches, ties and one-step Undo. It checks written and performed
overlaps and compiles standalone IT before saving. It does not add channels. Raw cells, incompatible mix
settings or insufficient spare channels refuse. Continue/Off NNA supports non-carried volume, pan and pitch
envelopes and fadeout. Continue needs an extra lane when a release and new attack coincide, so the IT
key-off survives. Stateless Cut instruments remain supported. Cut/fade release tails, duplicate checking,
carried envelopes, randomization, filters and channel plugins still refuse with a location and remedy.
A part that already has separate channels remains unchanged.

Cross-measure range technique controls now cover existing note flags, harmonics, grace, repetition,
bend/whammy curves and beat pick/strum strokes, with one Undo and retained selection. Complete tie chains
are required for note-wide changes. Complete expressive notes can cross new bar lines during Move,
rebar, measure preparation and cross-bar paste: vibrato, staccato, palm mute, dead/hammer, fade-in,
harmonic, grace, trill, tremolo picking, bend and whammy retain their full performed span. Let-ring splits
during rebar/Move and safe strum splits preserve actual sustain and attack spacing. Partial replacement
paste can retain static expression on the surrounding fragments; a surviving trailing fragment starts afresh.
Bend/whammy fragments retain cropped curves when the written points and every retained discrete pitch step
are exact. A trailing curve restarts at its retained pitch offset. Cropping tied curves still requires the full chain.
Cross-bar let-ring paste compares its actual gate against the same destination phrase before notation splitting.
New slide cuts, fractional/changed cropped pitch steps, changed let-ring gates or strum spacing, truncated
let-ring and changes that drift off IT ticks still refuse atomically with an explanation. Shorter may insert
a rest between a slide and its target; like TuxGuitar, this keeps the slide marking but plays a plain note.
This extends structural editing; it does not make every duration change to an expressive note representable.

GP3/4/5 export retains supported grace durations and transitions with exact representable velocities.
GP3/4 require before-beat grace and dead fret zero; GP5 also supports on-beat grace. TG and GP exports
fill silent gaps and pickups with explicit rests, reporting the count without changing the source score.
GP5 also retains representable chord diagrams, pick direction and brush strokes, including metadata shared
by two voices. Neutral spare-channel assignments export through the GP track/voice routes with a warning:
the native instrument release state is not portable to GP. Standard composer/lyricist/transcriber fields
remain intact in our GP5 readback, but TuxGuitar maps those credits differently on import and can change
them on rewrite. Its GP5 writer can also pad drum strings and cap maximum fret at 24. Review conversion
warnings; use Windows-1252 when opening exported non-ASCII GP text in TuxGuitar.
TEF3 import retains supported same-string sixteenth/thirty-second grace metadata and extended frets;
longer, compound and cross-string forms refuse. Beat text and chord names reserve horizontal score space,
and chord charts space their captions. If labels still cannot fit, the view gives a width/scale remedy.

TG/GP retain written notation within their supported formats. MIDI describes performed notes: importing it
reconstructs bars, voices and fingering, so repeats, written spelling and original articulation need review.
The native-score option also applies to the normal MIDI import dialog. Sample audio and DSP are not embedded
in TG/GP/MIDI; placeholder sounds do not reproduce the source instrument. Strict IT export may refuse a
valid native score whose timing cannot fit the tracker grid, including some imported grace notes.
Exact dense rhythms can now use finer rows in the exported IT only: physical tick duration, tempo, authored
patterns and native playback stay unchanged. This covers representable triplets, short pickups, some pitch
curves and release/attack collisions. Absolute tempo, pan, raw notes and static volume survive subdivision;
tick/row effects or automation, more than1024export rows per pattern, and genuinely off-tick timings refuse.
The existing37.5-cent pitch bound and documented final repetition-tail quantization still apply.

## Finishing and sharing a song

1. **New song.** Open NEW SONG, choose a new YAML filename and a guitar, bass, drum or four-track band
   template with a bar count. Tracker pattern keeps the original channel-count workflow. The tone gets an unused filename;
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
5. **Export.** RENDER & EXPORT offers IT, WAV, MP3 (192 kbit/s), OGG (Vorbis quality 6), FLAC, MIDI and channel stems.
   For legacy songs, MIDI writes the notes as a standard MIDI file the way OpenMPT's MIDI export does (Following OpenMPT): a track per
   instrument played, each tracker channel on a MIDI channel of its own, rows timed as libopenmpt plays them; the
   effects it cannot hold are counted in the job's warnings (stems stay WAV with it). It is made from the exported
   module: muted channels (the song's, and the audition's with Respect audition mute / solo) are left out, and REPEAT
   does not apply. Native scores use their frozen exact note/tie gates and a separate MIDI channel for each sounding
   tracker channel (up to 15 melodic channels). This preserves supported tuplets without grid rounding; timing that
   exceeds MIDI's resolution refuses. Instrument inheritance, slides, ambiguous raw releases, carried section-start
   notes and other unresolved state currently refuse with a location. Destination sounds are unspecified, and MIDI
   cannot retain sample sound or score engraving; the job shows these losses. Track lyrics and their starting
   measures are omitted with an explicit job warning. Native MIDI also refuses REPEAT.
   RATE (22050 to 96000 Hz),
   DEPTH (16 bits; 24 for WAV and FLAC, rendered from libopenmpt's float mix; float for WAV), MP3 KBIT/S (32-320),
   OGG QUALITY (-1 to 10) and REPEAT (the whole song played up to 16 more times, its last pass ending where the song
   does; not for a section or a game loop) default to 44.1 kHz, 16 bits, 192 kbit/s, quality 6 and one pass, so an
   export made before them comes out the same (`export --rate --depth --bitrate --quality --repeat` without the app).
   NORMALISE TO (off by default; `export --normalize LUFS --ceiling DBTP`) turns the audio up or down to an integrated
   loudness (BS.1770, as the meters measure it), held back where the true peak would pass the ceiling (-1 dBTP by
   default): a gain measured on the whole mix and applied to the song and every stem alike, no limiter, rendered from
   libopenmpt's float mix. The job's warnings say the gain, the loudness and peak reached, and when the ceiling held it
   back. The export then differs from the module; the .it is never changed.
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
   **Windows song shortcut.** PROJECT → CREATE SONG SHORTCUT opens a native Save dialog for a `.lnk` file.
   Choose a filename ending in `.lnk`; Windows asks before replacing an existing link. Cancel writes nothing.
   The saved-path message identifies the new shortcut. It opens the current saved song in this packaged exe
   (or `pythonw -m vulturetracker` from a source workspace), without changing song/history/mix. Keep both app
   and song in place; moving them requires a new shortcut. Other platforms report this Windows-only feature.
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
   name written as `name:`, so instruments that refer to it still find it); the complete song must compile. Each
   missing sample lists up to three WAVs of its name (any case) from the sample library's index (the MAP tab's
   folders) as USE buttons, one click and one undo step each: SAME FILE first, where the contents match the digest an
   undo step recorded while the file was there, then those sharing more of its folders. Nothing is relinked unasked.

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
  `notes:` and a keymap for the rest; `check` warns when a sample's highest note lifts the top of its spectrum, where
  it comes within 60 dB of its loudest band, over `module: ceiling`, 18 kHz by default), playing a bright sample more than about three semitones below its root (`check`
  warns when the images of its lowest note come within 60 dB), and low-rate samples interpolated by the player (the module setting
  `sample_rate: 44100` resamples every sample to the playback rate at compile time, band-limited, which removes that
  imaging in every player at the cost of file size). `vulturetracker/resample.py` holds the resampler.
- `import` also reads Guitar Pro tabs (.gtp for Guitar Pro 1 and 2, .gp3, .gp4, .gp5, .gpx for GP6, .gp for GP7; `pip install pyguitarpro`, LGPL-3; the app's IMPORT A
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
- `import bank.sf2 --preset N [--bank B]` writes a song with that SoundFont preset as instrument 1 and its zones as WAVs
  (`vulturetracker/sf2.py`; without `--preset` it lists the presets; bank 128 holds the drum kits); a `.pat` (GUS
  patch) takes no preset. The import reads the bank as OpenMPT does (Following OpenMPT) and says what it left out
  (velocity layers, zones on a key range already taken). SoundFont 3 (compressed samples) is refused: convert it to SF2
  first. A bank's zones often play far below their root: `check` warns about the images that leaves (No
  anti-aliasing regressions), and `sample_rate: 88200` is the way out.
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
