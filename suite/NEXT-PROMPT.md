# The next piece: a prompt to start from

Written 2026-09-22 after Nadir v6, at the user's request. Nadir was synthesized from a group of seven tracks and never
sounded right to them; Vantage was built against one reference (Foregone Destruction) and they called it great. The
prompt below follows the Vantage way, one reference at a time, with the user's ear deciding every sound in the app
before anything is arranged. Replace `<TRACK>` and `<piece>`; Nether Animal or Run are the natural next references
(the tracks the user named first).

---

This is a VultureTracker task (the tracker-music compiler at C:\Users\c\TrackerForge, origin
github.com/shadoh420/VultureTracker; not ArenaPrototype). Read suite/HANDOFF.md first, then suite/NEXT-PROMPT.md.
Read GUIDE.md and SONG_FORMAT.md only when you need them.

Goal: an original track that could sit on the Unreal Tournament (1999) soundtrack next to <TRACK>, built the way
Vantage was built against Foregone Destruction (one reference, measured, and I called the result great), not the way
Nadir was built from a group of seven tracks (which never sounded right to me). One reference track; one piece; my
ear decides, in the app, one layer at a time. Never average several tracks into one.

The reference: <TRACK> (C:\UnrealTournament\Music\<file>.umx, extracted in scratch/ut99-clean/modules/). Everything
measured from it stays in scratch/ (Epic's copyright, never committed). PROVENANCE.md wording is "inspired by", never
"based on"; no audio, sample data or melodic cell is copied; sounds are chosen by measured character for the
reference's roles, not by matching its samples.

Step 0, before any sound: measure the reference with scratch/ut99-clean/analyze.py and structure.py and the
per-channel method used for Foregone (the played tempo and speed from the T/A commands, not the header; the form
map with section lengths in patterns; per channel its role, its sample's character (length, tail, loop, centroid,
flatness, noise floor), its volume idioms (fades, echoes, retriggers, sample offsets), panning and surround; the
loudness order of the layers from per-channel power, not mid-based RMS; the harmony, how many roots and how they
move; the drum grid in rows). Write it as a one-page brief in plain words and numbers, suite/<piece>/BRIEF.md, and
stop. I will say which traits the piece must keep.

Step 1: a two-bar loop of the drums and the bass or sub layer only, on the reference's grid, with three to five
candidate sounds per role loaded in the tryout (samples/local/, the Big Rusty kit, the TR-8 pack, Surge XT, VSCO,
Dexed, OB-Xd; never a chiptune-clean patch, give it a floor the way gen_floor.py does). I pick by ear with the
tryout, SOLO IN SONG and the faders and write the slots with U. Then stop.

Step 2: one layer at a time (the bed, then the line, then the calls or FX), each offered as candidates in the tryout,
each stopped for my pick. Nothing goes into the song that I did not choose.

Step 3: only when every sound is approved, lay out the full form by the reference's form map (section lengths, where
layers enter and leave, the arcs), with the reference's number of roots and never more; melodic lines subdued and
dream-like, one moving line at a time, no arpeggio or sequence figures unless the reference has them, no bells,
plucks, squares, flutes, saws, gongs or orchestral rolls. Render; compare.py against the reference alone; the
spectrogram (nothing above the drums' ceiling); harmony.py's clash check; the MP3; stop. I listen in the app
(python -m vulturetracker gui suite/<piece>/<piece>.yaml) and drop notes with N; you act on the notes and their
sounding lists only, one round at a time, and ask nothing the report answers.

Standing rules: report measurements, never claim to have heard anything; drums I approve stay row for row; every
melodic voice in its own single-sample slot so the tryout can swap it; levels are mine (the faders), not yours;
no commits or pushes unless I say so; never git add -A; scratch/ut99-clean stays local.

Done when: Step 0's brief is written and you have stopped for my choices.
