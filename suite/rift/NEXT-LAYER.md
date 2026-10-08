DONE (2026-09-24, about 05:35): layer 9's check rounds 3 and 4 are finished. Round 3 (19 items; the generator lens run
again as checks/round3_generatorb/ after its first run was cut short) was fixed and rebuilt: the movements solved
without the floor noise, the onset against one whole period at 25 ms on the whole fine grid, level_track over three
periods, the vibrato knots refit after the onset search, GAIN -5.3 for badnews, organ and sine (files 04:19-04:27, song
04:30, x4 renders 04:31; the eighteen regenerated, the same five chosen). Round 4 (13 items, none reaching the audio:
the five, their logs, the builds, the song and the choice reproduced byte for byte) was fixed in text. HANDOFF's layer-9
entry holds both rounds. Stopped for the owner's pick in slot 15 (second_badnews is the placeholder; listen to
suite/rift/<cand>_x4.mp3). What follows is the resume prompt as it stood before round 3's fixes.

VultureTracker task (C:\Users\c\TrackerForge; not ArenaPrototype, even if the session starts in an ArenaPrototype
folder: work only there with absolute paths). Read suite/HANDOFF.md item 2 from "Follow the references" on (layers 1-9;
the layer-9 entry has two placeholders, ROUND3 and ROUND3DETAIL), then suite/rift/BRIEF.md's layer plan and its
corrections at the end (the layer-9 ones last).

Where things stand (2026-09-24, about 03:10): layer 9 (the second line, slot 15) is built, checked in rounds 1 and 2,
and rebuilt with every fix of both rounds: the five are second_badnews (the placeholder, in the song and first in the
tryout's list), second_blown, second_organ, second_pulse, second_sine (samples/local/rift-cand/second_<cand>.wav, 02:41;
song rift.yaml/.it/.wav/.mp3 02:42; x4 renders suite/rift/<cand>_x4.mp3; all five 10.3 dB under the sub). The choice
(samples/local/rift-cand/second/finalists.py -> finalists.txt) was rerun on the final generator's output of all eighteen
(second/gen/): the same five. Check round 3 (two independent read-only agents: the generator lens and the choice/text
lens) was launched about 03:00; their reports go to samples/local/rift-cand/second/checks/round3_generator/report.txt
and round3_choice/report.txt. If a report is missing or cut short, run that lens again with a fresh general-purpose
agent (read-only; its scripts and outputs only in a new folder checks/round3_<lens>b/; scope below).

Round 3's scope (what round 2 changed; round 2's reports: checks/round2_generator/report.txt, round2_choice/report.txt):
in suite/rift/gen_second.py the pre-loop levels read by level_track() on a 20 ms Hann-weighted mean square at melodic's
10 ms block centres (the blocks beat with our A#3: 1.0-1.4 dB on a steady tone), early_ranges from 25 ms, targets
re-read by `gen_second.py ref` (early 1.07, early2 2.11 at a new 0.41 s knot, am1-am4 4.05/3.29/3.05/3.06, slope_pre
-1.78), the AM knots AM_T (am4 held to 2.32 s, full at 2.43 s), four vibrato knots fm1-fm4 solved to the reference's
pitch spans 1.77/3.02/6.57/5.06 c, the onset read against its own 10-20 ms level (onset_means: the reference's 0.32 /
4.90 ms) with its two stages searched together on a grid after the rest (onset_search, read at the file's nominal
length: its -10 dB crossing is marginal, and a prefix's FFT resample differs slightly from the whole file's),
GAIN re-measured; finalists.py (robustness over the
32 metric variants only, each pick's leave-out apart, what decides the pick said plainly, flatness read with the
generator's floor); the text (gen_second.py's docstring and CANDS comments, measure.py's two round-0 sentences,
dx_obxd/screen.txt's slot-candidates note, BRIEF's last paragraph, HANDOFF's layer-9 entry). The patches are kept in
samples/local/rift-cand/second/checks/ (patch_gs9/10/11.py, patch_doc12.py, patch_fin13.py, patch_handoff14.py); the
final build's logs in checks/logs_build7/ (`python checks/table7.py` prints them side by side).

Finish layer 9, then stop for the owner's pick:
1. Read both round-3 reports. Fix what they find, except matching Nether's partial table, noise curve or decay (report
   those). A fix that changes audio: patch gen_second.py through a Write-tool patch script (exact replacements that
   assert one match; keep the file's CRLF endings), test on one take with `python checks/gen_into.py <folder>
   <name>=<take>:<gain>` (make() into another folder, the slot's files untouched), then regenerate the five
   (`python suite/rift/gen_second.py <cand>`, one process each, about 2-5 min in parallel), rebuild them
   (`python scratch/ut99-clean/rifttools/cand_builds.py 15 "second line" <cands>`), `python checks/levels_all.py <cands>`
   (set GAIN so each reads 10.3 dB under the sub, no peak limiting; regenerate and rebuild once more), then the suite:
   melodic.py (`python scratch/ut99-clean/melodic.py scratch/ut99-clean/lines.json rift_<cand> ...`), compare.py against
   Nether into checks/logs_build7/compare_<cand>.txt, checks/solo_spec.py, checks/onsets.py (ref_onsets.py for the
   reference), `python suite/rift/clash.py suite/rift/rift.yaml`, loopscope and `python -m vulturetracker check` on
   temporary copies of rift.yaml with sample 15 swapped (sed on the sample-15 line; delete the copies after), every
   `suite/rift/gen_*.py pattern` leaving the song byte for byte, checks/listen.py (x4), the song's WAV and MP3 (`python -m
   vulturetracker build suite/rift/rift.yaml --render suite/rift/rift.wav`, MP3 through imageio_ffmpeg at 192k), and
   checks that rift.it equals the badnews build. If the loop's figures could change, regenerate the eighteen into a new
   folder with gen_into.py (four processes), swap it in as second/gen/ and rerun finalists.py and checks/choose5_fixed.py.
   A round that rebuilds needs another check round (fresh read-only agents, scoped to what changed).
2. Fill HANDOFF's ROUND3 (the entry's header) and ROUND3DETAIL (the end of its Checks paragraph) with what round 3 found
   and what was done; update any figure a rebuild changed (from table7.py, the compare/melodic/onset outputs).
3. Update the rift-reference-layers memory (and its line in MEMORY.md) with the final state; put a DONE line at the top of
   this file.
4. Stop for the owner's pick in slot 15. End with counts and status only (N findings fixed, rebuilt or not, the pick
   pending).

Lessons from this layer (apply them): read level shapes on a smooth window, not on 10 ms blocks, whenever a tone's
period does not divide the block (the blocks' own beat can be matched in place of a movement), and make the window a
whole number of periods long (a 20 ms Hann still beat 0.1-0.3 dB at our A#3; three periods do not); read the onset
against its own settled level over one whole period, not the file's loudest block (a later tremolo crest) nor a 10 ms
block (it beats too); a reading that steps with a block grid needs the same resampling as the final reading (a marginal
crossing flips with any change of FFT length); search a quantised, knife-edged reading over the whole grid and keep its
target exact (a coarse-to-fine search missed the best point; a rounded target can prefer a neighbouring step); solve a
movement before the loop separately from the loop's (the loop's slope added from the onset doubled a take's own early
decay); solve the movements on the file without an added floor noise shaped like the take (its random wobble reads as
movement, where the reference's white floor reads as almost none); YIN's first frames hold the onset, so fit the vibrato
knots again with the final onset, to a fixed point (neighbouring knots share a span); when the finished file reads
otherwise than what was solved, log both; a pool without an unchosen take cannot change a fixed-unit choice (do not
count it as robustness); say what decides a tied choice (here the pref sum picks three of five); a choice read on
generated files reads the generator's noise seed and gain, not the song's files (check it on the slot files too); on
Windows, `mv` of a folder fails with "Device or resource busy" while the shell's working directory is inside it (cd out
first); background regenerations compete for the CPU (four to five processes at most). And the earlier layers' lessons
in HANDOFF's layer 6-9 entries.

Boundaries: approved sounds and their levels stay; don't ask about them. Our sub stays on A. Nothing from the UT99
modules goes into our songs or samples; report measurements, never claim to have heard anything. No commits or pushes
unless the owner says so; never git add -A. scratch/, samples/local/, suite/rift/ and BRIEF.md stay uncommitted; the
owner's uncommitted instrument panel (gui.py, gui.html, tests/test_gui.py, GUIDE.md), AGENTS.md, suite/HANDOFF.md and
suite/NEXT-PROMPT.md must survive. Big Python patches go through Write-tool script files, not heredocs. PROVENANCE.md
needs a Rift section before any Rift commit. Keep any channel volume or mix change the owner makes in the app (check
suite/rift/rift.tryout.json's "mix" and the song's channel lines before rewriting anything).

Done when: round 3's findings are fixed (and a further round has run if round 3's fixes rebuilt), HANDOFF and memory
are updated, stopped for the owner's pick in slot 15.
