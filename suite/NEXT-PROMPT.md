# The next piece: a prompt to start from

Rewritten 2026-09-26 on the owner's word ("whatever we did for rift2 seems fine"). History: Nadir averaged seven tracks
and sounded jumbled; Vantage and Rift followed one track's form, layers and measured melodic shape and read as
"the musical equivalent of tracing". Rift 2 fixed it by keeping the reference's frame and sounds but dropping layers,
shortening the sections and writing the melodic lines from scratch, offered as rendered versions for the owner's pick.
That is the procedure below. `suite/METHOD-PROPOSAL.md` and `suite/TRACING-DIAGNOSIS.md` are background only.
Replace `<TRACK>` and `<piece>`.

---

This is a VultureTracker task (the tracker-music compiler at C:\Users\c\TrackerForge, origin
github.com/shadoh420/VultureTracker). Read AGENTS.md and suite/HANDOFF.md first. Read GUIDE.md and SONG_FORMAT.md only
when you need them.

Goal: an original track that could sit on the Unreal Tournament (1999) soundtrack next to <TRACK>, made the way Rift 2
was made. One reference track, never several averaged. From it we take the frame (tempo and groove, sound world,
idioms, balance). Every melodic line, the layer set and the section lengths are our own. My ear decides, in the app,
one layer at a time.

The reference: <TRACK> (C:\UnrealTournament\Music\<file>.umx, extracted in scratch/ut99-clean/modules/). Everything
measured from it stays in scratch/ (Epic's copyright, never committed). PROVENANCE.md says "inspired by", never
"based on". No audio, sample data or melodic cell is copied, and no sample is chosen by matching one of theirs.

Step 0: measure the frame with scratch/ut99-clean/analyze.py, structure.py and perchannel.py: the played tempo and
speed (from the T/A commands, not the header), the drum grid, each role's sound character (length, tail, loop,
centroid, flatness, noise floor), its idioms (echoes, offsets, gates, glides, pans), the loudness order from
per-channel power, and the harmony (roots, how they move). Do not measure its melodic lines for use: their rhythm,
cells, intervals, contour and register stay out of the piece. Write suite/<piece>/BRIEF.md, one page: the frame in
plain words and numbers, and a proposed layer set with fewer roles than the reference where one can go. Stop.

Step 1: a two-bar loop of the drums and the bass or sub only, on the frame's grid, with three to five candidate
sounds per role in the tryout (samples/local/, the Big Rusty kit, the TR-8 pack, Surge XT, VSCO, Dexed, OB-Xd; give
clean synth patches a noise floor the way gen_floor.py does). I pick with the tryout and write the slots with U. Stop.

Step 2: the melodic lines. For each, write two to four lines from scratch that differ in kind (register, rhythm,
density, shape), plus the section without the line, and render each as a short MP3 in the song. Stop for my pick.
Then three to five candidate sounds for the picked line in the tryout; stop for my pick. One line at a time, each in
its own single-sample slot. Then the remaining layers the same way, as tryout candidates.

Step 3: only when every line and sound is approved, lay out the full form with our own section lengths (not the
reference's). Render; the spectrogram (nothing above the drums' ceiling); harmony.py's clash check; the MP3; stop. I
listen in the app (python -m vulturetracker gui suite/<piece>/<piece>.yaml) and drop notes with N. Act on the notes
and their sounding lists, one round at a time, and ask nothing the report answers. If I say a passage sounds like the
reference, rewrite its notes; don't answer with measurements.

Standing rules: report measurements, never claim to have heard anything; sounds I approve stay row for row; the
balance starts at the reference's, the faders are mine; no commits or pushes unless I say so; never git add -A;
scratch/ut99-clean stays local.

Done when: Step 0's brief is written and you have stopped for my choices.
