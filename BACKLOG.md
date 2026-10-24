# VultureTracker backlog

Historical (closed with 0.7.0, 2026-09-30): the focused 0.7.0 scope was fixes for the 22 reproduced audit defects, bounded history,
recording alongside playback, MIDI chord capture, conversion to editable literal patterns,
configurable beat spacing, and shared phrase-sample storage.

## Native tablature editing (requested 2026-10-19)

Owner's scope: full TuxGuitar parity, fully native inside VultureTracker, synchronized with Pattern and everything
else. This replaces the deferred read-only tab proposal. The screenshot is a visual reference, not a complete
feature specification. Status: the first native editor and shared score projection are implemented locally and
under validation. Full parity remains incomplete. The pinned-source inventory is `TABLATURE-PARITY.md`.

### Resumed under Claude Code AO workers (2026-10-20)

The owner moved this work to Claude Code AO workers: orchestrator `trackerforge-orchestrator`; an
integration owner (BACKLOG/GUIDE/CHANGELOG/TABLATURE-PARITY, `gui.html`, `tests/test_tablature_page.py`
and all other integration); a GP5-oracle worker exclusively owns `vulturetracker/gpexport.py` and
`tests/test_gpimport.py`. The Codex sessions in the table below and the Codex automation
`continue-native-tablature-integration` remain PAUSED; do not wake them. No commit, push, release,
installation or cleanup is authorized.

**Testing rule (owner, 2026-10-21): the owner only tests what a computer can't (sound, engraving looks, clutter,
feel).** Every TAB feature needs one muted page test in `tests/test_tablature_page.py` that drives the real control
as a user does (click or key) and asserts what the user perceives: visible button and panel states, the playhead on
both staves, readable values (note names, not MIDI numbers), measured render/live pitch and duration, byte-exact
Undo. Edits that TuxGuitar also has are compared with TuxGuitar 2.1.0 by `tools/tg_edit_oracle.py` (CPU lease).

### Current state: continuous Pattern follow-up (2026-10-24)

Release1.9.0 is now authorized. The owner requested the clean TuxGuitar layout as the default first;
fresh-view defaults and preserved explicit preferences pass4 focused control tests. The versioned package
passes native/IT/control smoke checks; PR CI is pending. Current handoff records publication state.
Exhaustive parity is not claimed.

The owner clarified that one bar with previous/next controls was insufficient. Pattern now defaults to a
continuous order-list view: several bars visible together, wheel/scrollbar access through the whole song,
stable channel columns, row/column selection into the existing editor and adjacent-bar keyboard navigation.
Native/repeated-pattern edits share the existing history. Source checks cover actual Boys232-bar scrolling,
last-bar playback, resize, raw/native byte-exact Undo/Redo and atomic failed Cut/Paste. Final package qualification
passes in `scratch/tab-test-fixtures/continuous-pattern`, including dragging the actual scrollbar to bar232,
retained marker/edit/native/IT/selfchecks and ZIP/shortcut finalization; see the handoff for current digests.
The clean score preset is now the fresh-view default; explicit saved preferences remain intact.
Owner visual/feel acceptance is not inferred from the automated checks.

### Previous delivered state: owner GP5 import/export and navigation fixes (2026-10-24)

All three unchanged Downloads inputs now import and play natively: Boys In The Band (232 bars/7 tracks/
5,664 notes), Advent Of Panurge (116/9/3,957), Talybont (129/10/1,942). Double barlines and key changes are
preserved; GP5 display/mix metadata is retained in source notices with TG-compatible behavior. Raw bend
coordinates are retained when rounded like TG. Identity-based tie lookup fixes four Advent ties, and
engraving now carries key/clef changes into later measures. Bounds and atomic publication guards remain.
`download-gp5` evidence:152 importer/export tests,2 focused raw/drum guards,32 syntax/docs checks, actual
UI import/edit/playback/exact Undo/Redo, and all three real-file imports/rendering/live PCM/part switches pass.
The installed TG2.1.0 probe matches all11,563 source notes (track/bar/onset/voice/string/fret/velocity/tie).
Candidate rebuilt at `scratch/tab-package-range-duration`; all three packaged import/render/native playback
checks pass in `package-native-final.log`. Retained marker/edit/Undo/IT/selfchecks pass in `package-final.log`;
ZIP/study/shortcuts/rollback pass in `delivery-final.log`. Current digests and three Play shortcuts are in handoff.
The subsequent `gp5-release-fixes/it-final.log` closes both standalone IT refusals. Boys exports5,492 tracker
attacks (32 native attacks replaced by3 short sampled passages); Advent exports3,592 (21 replaced by6 passages).
Talybont remains2,210 ordinary attacks. The owner explicitly accepted sampled passages in exported IT while
keeping every native note editable. `audio-final.log` compares all9 decoded IT samples played in standalone
libopenmpt with native-rendered passages: maximum PCM error7.63e-6, consistent with16-bit rounding. Whole-song
IT tick/volume resolution still differs; this does not claim sample-identical whole-song output.
Strict edit guards remain unchanged; source checks cover full-audio comparison and atomic output preservation.
Pattern now has order selection/previous/next and wheel navigation, with manual browsing pausing Follow.
TAB/SCORE has a TuxGuitar horizontal/all-track/written-pitch/no-dynamics preset; view changes preserve history,
and written staff entry correctly includes capo with exact Undo/Redo. Tempo-only controls no longer warn.
Matching1920x1040 before/after captures and actual232-position navigation are in `gp5-release-fixes`.
The rebuilt candidate passes all3 packaged CLI/UI exports byte-equal to source, native PCM and the new controls
(`gp5-release-fixes/package-exports.log`). Retained marker/edit/history/native/IT/selfchecks and ZIP finalization
pass in `package-final.log` and `delivery-final.log`; current digests are in the handoff.
TG export refuses double barlines; ignored GP5 mix/display settings are not claimed as reproduced audio.
Owner accepted the sound of the Boys In The Band and Advent Of Panurge exported IT files on2026-10-24.
Score readability and browsing/editing feel remain unconfirmed. No publication or Git mutation is authorized.

### Previous state: release-readiness qualification (2026-10-23)

Owner narrowed this work to bug fixes and a releasable candidate. Peripheral platform/plugin/device,
language/style breadth and external LilyPond are deferred for this release; exhaustive parity is not claimed.
The final candidate is built and automatically qualified at the current delivery location. Whole-beat Copy now
retains implicit source silence separately for sequential replacement, leaving sparse/span operations unchanged.
Four pinned-TG comparisons and actual controls pass; exact State/history/Pattern/native/IT checks pass.
`scratch/tab-test-fixtures/release-readiness` holds the audit, original failures and corrections. Broad source
qualification exposed obsolete rhythm/strict-IT test assumptions and a real repeated-pattern boundary-release
refusal. The latter now permits existing attacks and harmless song-start releases while protecting different
predecessors. Navigation wraps at narrow widths. All failures from1,692 portable and399 page/advanced checks
have passing focused reruns; original failures and corrections remain. `suite/HANDOFF.md` maps those logs.
Owner-reported Part-switch marker loss is fixed: Part/Track changes preserve Follow playback instead of
silently disabling it through edit-caret synchronization. The requested follow-up audit additionally fixed
Voice controls disabling Follow, empty voices hiding the part marker, and fractional native cursor starts
being rounded by Ctrl+F6/Ctrl+F7. Thirteen distinct browser checks and two clock/transport contract tests pass.
The expanded editing audit covers39 distinct browser tests and fixes delayed phrase/rhythm completion
reverting newer Voice navigation, plus string moves overriding a later caret. Paste/Matrix completion uses
the same submission-position guard; exact Undo/Redo and backend musical guards remain intact.
`suite/HANDOFF.md` maps original failures, harness corrections and focused passes. Final package controls,
delayed-edit navigation/history, native/WASM playback, standalone
IT (74 attacks/192 rows/9.996s reopened without a native plan), ZIP/study integrity, shortcuts and selected
rollback pass in `editing-package-final.log` and `editing-delivery-final.log`. The unchanged keyboard transport
retains its previous package qualification in `audit-keyboard-package-qualified.log`.
Current package: `scratch/tab-package-range-duration`; selected rollback remains
`scratch/tab-package-range-expression`. Mutable example: `release-readiness/Try release candidate.lnk`.
Final artifact digests are in `suite/HANDOFF.md` and `editing-delivery-final.log`. Optional Dexed and native desktop
Save are unexercised. Owner sound/engraving/feel acceptance is pending; no version bump or publication occurred.

### Previous delivered milestone: annotated Fit and GP interchange (2026-10-23)

Fit moves annotated note groups through the shared voice-transfer path. Rest rebuilding protects the peer
records after the legitimate transfer; range checks preserve every peer note/timing/voice field and every
other-track field. Consumed annotated rest groups, conflicting destination metadata and unsafe timing refuse.
Redundant GP group labels serialize identically to unlabeled input; actual independent same-onset groups
refuse with the precise GP-reader identity-loss explanation. Input songs are unchanged by export.

Evidence `scratch/tab-test-fixtures/annotated-fit`: three manager cases match in `qualified.json` (dotted
growth in ordinary/independent groups, half growth).54 of55 checks pass in `model-state-final.log`; its lone
new assertion addressed raw backing cells instead of Pattern's native projection, corrected in
`targeted-final.log`. The earlier model failures expected moved/peer text to refuse; now they verify retained
group text and unchanged peer timing/notes. Two GP tests cover six single-group version/rank combinations,
shared GP5 voices and true-collision atomic refusal in `gp-groups-final.log`; first run lacked a test import.
`page-final.log` passes actual Fit, visible chord/text/stroke/pick state, GP5 export/readback and exact Undo/Redo.
The first export fixture used implicit velocity64, outside GP's grid; corrected to95, guard unchanged.
Final package qualification passes in `package-controls-final.log` and `delivery-final.log`: actual Fit/GP5
controls, native/WASM playback, standalone IT6 attacks/96 rows/3.999s without a native plan, ZIP and shortcuts.
Current package `scratch/tab-package-range-duration`; rollback `scratch/tab-package-range-expression`.
Separate mutable example: `annotated-fit/Try annotated Fit.lnk`. Owner asked to stop here; all workers/jobs stopped.
Next explicit resume: whole-beat implicit-silence copying. Read-only evidence in
`scratch/tab-test-fixtures/whole-beat-gap-probe/result.json` shows two explicit-rest baselines matching and
two equivalent implicit-gap mismatches (local and cross-source-bar). Notes collapse to quarter1 instead of2/3;
destination notes remain that TG clears. No product edits made for this next gap. Owner acceptance remains pending.

### Previous state: shared annotation transfer verified and packaged (2026-10-23)

Insert rest and caret-rest deletion use the same group-transfer path for ordinary and independent groups.
Chords/strokes follow the last sounding voice; text stays while any peer voice remains, including a rest.
Deleting a rest preserves its shared text and fills the trailing caret-duration rest when it fits. Written
measures spanning tracker patterns retain these rules. Conflicting annotations and unsafe IT timing refuse.

Evidence `scratch/tab-test-fixtures/cohort-annotations`: six manager comparisons match in `qualified.json`,
`shared.json`, `ordinary.json` and `selected-rest.json`.44 focused model/State checks pass in
`model-state-final.log`; cross-pattern/text checks pass in `edges-corrected.log`, range-rest in
`rest-selection-final.log`. `edge-cases.log` exposed two stale expectations: trailing rests now exist, and a
normal-Fit test needs a complete authored bar (short bars require Free). Fixtures now express those behaviors.
Initial checks also had two mistyped class names, a fixture helper's unsupported dots argument and a wrong
exception class/empty-selector value; corrected final checks pass. `page-final.log` exercises actual Cut,
stroke/pick/text/chord controls and exact history. Unsafe stroke16 still refuses, retained in `first.json`.
Final package checks pass in `package-controls-final.log` and `delivery-final.log`; current package remains
`scratch/tab-package-range-duration`, selected rollback `scratch/tab-package-range-expression`, mutable example
`cohort-annotations/Try annotation transfer.lnk`. Musical delivery and owner files remain preserved.

Next: annotated Fit qualification, then safely normalizable GP cohort labels. The read-only bounded worker
confirmed GP5 import merges true independent same-onset groups; `gp-group-scope.md` records pinned sources.
It is stopped. True identity loss remains an explicit format gap, not an excluded feature. Owner acceptance pending.

### Previous state: rest/Fit voice regrouping verified and packaged (2026-10-23)

Normal Insert rest and caret-rest deletion now join the first destination TGBeat group, including a surviving
nonzero local group rank. Deletion restores the one trailing rest TG creates when it fits. Unannotated Fit
retains distinct groups and preserves peer records exactly; singleton group ranks are not needlessly rewritten.
Shared annotations during these voice moves, annotated Fit and complex ambiguous paste remain explicit guards.

Evidence `scratch/tab-test-fixtures/cohort-rest-fit`:39 affected model checks pass in `model-first.log`;
State exact history, Pattern and standalone IT pass in `state-second.log`. Four manager note outcomes match
in `raw-note-comparison.json`; three canonical comparisons match in `qualification.json`. The shortening
sequence ends with an overfull TG output requiring the raw snapshot. Current final caret deletion also matches
rests; the older range probe hit TG's already-recorded repeated-caret note-loss bug, so the actual single-caret
action has its own probe, with the original evidence retained. `page-second.log` passes actual Insert rest,
dotted Fit, Rest/Cut and exact Undo/Redo. Initial fixture title exceeded IT's25-character limit, fixed without
relaxing it. First Fit attempt rewrote a peer's singleton rank; preserving it keeps the existing peer guard.
Earlier raw comparison runs lacked the new case family's retained fields; the existing runner now saves them.
Final native/WASM/IT/controls/ZIP qualification passes in `package-controls-final.log` and `delivery-final.log`.
Current package remains `scratch/tab-package-range-duration`, rollback `scratch/tab-package-range-expression`;
mutable example is `cohort-rest-fit/Try group rest editing.lnk`. The musical study and owner files are preserved.
Next: source-qualified shared annotation transfer during voice moves; this work is not yet packaged.
All workers are stopped; owner sound, engraving and feel acceptance remains pending.

### Previous state: independent coincident beat groups verified and packaged (2026-10-23)

Free duration now retains distinct TGBeat groups when two groups land at the same onset. A bounded optional
beat `cohort` scalar stores local collision order in the shared song; there is no separate history or score model.
Save/reopen and another Free edit now match TG. Shared strokes/chords, Clean Beat, Matrix preview and notation
projection use the same group identity. Empty-destination Copy, whole-track movement and whole-beat replacement
preserve distinct source groups. Partial single-group Copy normalizes its local discriminator.

Evidence `scratch/tab-test-fixtures/cohort-identity`:14 raw-manager note outcomes match in
`raw-note-comparison.json`;11 canonical comparisons match in `qualification-final.json`, with three overfull
outputs still unreadable. The earlier repeated-edit mismatch is fixed. Twelve TG-format checks pass in
`tg-interchange-tests.log`, including XML and legacy1.1/1.2/1.3/1.5, distinct metadata, reopen/edit and overlap
refusal. State checks cover exact two-step history across reopening, Pattern/native playback/standalone IT and
atomic compile failure. `page-second.log` passes the real align/reload/second-edit/history workflow.
Affected checks:53 of54 passed in `affected-first.log`; the remaining old chord test expected an obsolete
standalone-IT refusal. It now checks unchanged projection in `targeted-final.log`.34 of35 pass in
`final-model.log`; the new guard fixture omitted required rest_id, corrected in `guard-final.log`.

Actual qualification failures were fixture/harness issues: selecting a hidden second-voice grid note, moving
metadata into an incompatible destination, testing atomic failure with an unchanged command, obsolete chord
refusal and missing rest_id. No guards were relaxed. `qualification.log` records a rejected shorthand case
argument; the existing case-list runner produced the final result. All workers completed and stopped.

Open bounds: Fit, normal Insert rest, rest-gap deletion and ambiguous Mix/Push or cross-boundary paste refuse
distinct groups until their cohort-preserving transformations are qualified. GP export still refuses this new
metadata; notation exports report editable identity loss. Other existing safety/format/platform exceptions and
owner sound, engraving and feel acceptance remain open. Mutable example: `cohort-identity/Try independent
beat groups.lnk`. Final `package-controls-final.log` passes the actual repeated-edit workflow,12 native events,
standalone IT, two written bars, live WASM and selfcheck. `delivery-final.log` verifies ZIP/listening study,
shortcuts and rollback. Next: resolve guarded rest/Fit workflows using new valid-bar cohort fixtures.

### Previous state: invalid-bar Free mode and repair verified and packaged (2026-10-23)

Authored short, long and internally discontinuous bars now require Free mode for duration, Matrix and Insert
rest. The disabled checked control explains the state and returns to the explicit preference after repair;
empty voices remain valid. Mixed ranges evaluate mode per target/bar. Overflow without authored boundaries
records the exact pre-growth pattern length as a meter, retaining overflow diagnostics and later empty-row repair.

The repair workflow exposed an important root cause in the prior milestone: filling implicit gaps on every
Free duration command turned newly created two-voice gaps into rests. Free now repacks only existing cohorts,
matching raw TG holes. Thirteen retained manager cases match note voice/onset/duration/string/fret/tie state
in `invalid-bar-free/raw-note-comparison.json`; nine canonical file comparisons match, four TG outputs are
unreadable by the existing importer (overfull or duplicate onsets), so those use raw manager snapshots only.
Repeated commands after coincident independent cohorts now have a proved mismatch: the next command merges
distinct TGBeat groups sharing an onset. `cohort-repeat.json` and its raw snapshots retain the reproducer.
Saved cohort identity, metadata and interchange are the next shared-root-cause milestone.

Focused evidence:27 model checks in `model-repack.log`;18 additional affected checks pass in `affected-final.log`
with the mixed-range fixture corrected in `mixed-range-corrected.log`. Existing State history/Pattern/IT/atomic
failure passes are included. `page-final.log` passes Matrix regression and overflow/reload/required mode/duration
repair/Apply measure with exact three-step history. Initial fixture assertions were corrected for target-bar
scope and the existing complete-range contract. Actual product failures: implicit filler blocked repair, and
repainting controls on a Free toggle reset the pending duration; both are fixed and covered. Final package
passes in `package-controls-final.log`:12 native events,6 standalone IT attacks/96 rows/3.999 seconds, two
written bars, live WASM and selfcheck. `delivery-final.log` verifies ZIP, listening study, shortcuts and rollback.
Mutable example: `invalid-bar-free/Try invalid bar repair.lnk`. Owner sound, engraving and feel remain pending.
The bounded cohort audit completed; the lead owns product edits, integration, checks and packaging.

### Previous state: Free-duration cohort repacking verified and packaged (2026-10-23)

Free duration now follows the pinned manager's two repacking passes per selected beat, retaining complete
cohorts across both voices, rests, annotations and adjacent ties. Leading/interior native silence is spelled as
export-equivalent rests; no trailing filler is invented. Matrix's anchored Free entry remains separate. Queued
duration commands capture their Free setting. One shared-document transaction retains selected IDs and caret.

Evidence `scratch/tab-test-fixtures/free-duration-repack`:17 focused model checks in `model-second.log`,
State exact history/Pattern/native playback/standalone IT plus atomic compile failure in `state-first.log`,
actual duration/Fit/Free controls and both-voice growth/shrink in `page-final.log`. Matrix controls still pass
in `page-first.log`. Initial model failure was the superseded overlap-refusal expectation; now sounding beats
move safely. Initial page fixture lacked authored measures, so growth changed its inferred nominal length and
did not report "long"; authored-meter controls pass, and that unauthored-measure diagnostic gap remains open.

Oracle `qualification.json`/`qualification.log`:six full canonical matches; direct manager snapshots in
`raw-note-comparison.json` give nine note/voice/onset/duration/string/fret/tie matches, including three overfull
outputs the TG importer cannot read. Four differences remain: automatic Free on invalid measures, and three
deliberately sparse raw-TG hole/cohort cases. Native implicit silence is preserved as rests; raw gaps can be
repacked away by TG. Coincident separate TGBeat identities and repeated commands need further qualification.
Initial and final oracle/probe logs are retained; first Java diagnostic compilation needed Iterator traversal.
Worker finished and stopped. Final package passes in `package-controls-restored.log`:12 native events,
6 standalone IT attacks/96rows/3.999seconds, two written bars, live WASM and selfcheck. First packaged check
passed the new edits but the test left the optional grid open; helper now restores it. No product change or
rebuild was needed. `delivery-final.log` verifies ZIP/listening study/shortcuts/rollback. Separate mutable
example: `free-duration-repack/Try Free duration.lnk`; owner sound/visual/feel acceptance remains pending.
Next: automatic invalid-bar mode and the unauthored measure-boundary diagnostic, then remaining parity gaps.

### Previous state: Matrix free entry and audition verified and packaged (2026-10-23)

Free Matrix entry now anchors to its containing beat, copies the caret duration without normal rest
subdivision/retargeting, and takes precedence over Fit. It reuses native Free-duration growth/overlap
safeguards in one transaction. Successful entry previews the original context beat's two voices for500ms;
normal retargeting still previews that original chord. Deletion does not preview. Absent voices and free-mode
implicit gaps audition the clicked concert pitch without editing. Unique live keys permit simultaneous notes;
engine-start previews cancel across song/transport changes. Native instrument/velocity defaults remain native.

Evidence `scratch/tab-test-fixtures/free-edit-workflow`: pinned-source `findings.md`; six installed-manager
cases in `probe-final.log` / `native-comparison.json` give five note matches and one atomic sounding-overlap
refusal. The first Java source launch encountered neighboring reference source files; explicit javac sourcepath
fixed that harness issue. Six model/State checks pass in `model-first.log`, plus free growth/Pattern/IT/exact
history in `state-growth.log`. Real controls pass in `page-controls-final.log`. First page attempts used a title over IT's
25-character limit; corrected. Later waits incorrectly required a refreshed hidden TAB after ROLL Undo and
navigation needed an explicit refresh; test synchronization was corrected. Voice diagnostics then proved the
test's ambiguous string option selected label 1 rather than stored value 1; explicit second-option selection
passes. The first cancellation harness returned an unresolved function to Playwright; the interrupted run is
`page-final.log`, corrected with a block callback. Original piano preview regression passes in `page-fourth.log`.
Real controls cover Free/Fit precedence, normal retargeting, both voices, zero velocity, 500ms note-offs,
absent-voice no-edit audition, exact history and transport cancellation during startup. Final package passes in
`package-controls-final.log`: same real controls,8 native events,4 standalone IT attacks/96rows/3.999seconds,
two written bars and live WASM/selfcheck. `delivery-final.log` verifies ZIP/listening study/shortcuts/rollback.
Separate mutable example: `free-edit-workflow/Try Matrix free entry.lnk`. Sound/visual/feel acceptance is pending.

The source worker finished and is stopped. Existing Free duration is implemented, but TG's cohort repacking
and automatic free mode for invalid measures remain genuine gaps; source implicit-rest equivalence, protected
data and overflow safety differences are not excluded. Next: source-qualified Free-duration cohort repacking;
one bounded worker owns oracle tooling and new free-duration-repack evidence. Lead owns integration.
No staging/commit/push/release/Computer Use.

### Previous state: whole-beat replacement verified and packaged (2026-10-23)

Paste/Ctrl+V and Paste replace now use whole TGBeat cohorts: both voices clear, maximum source duration
reserves minimum-duration destination cohorts, shared metadata replaces, and the next available onset
after the minimum source duration controls advancement. Paste span retains the former exact-offset,
copied-lane/exterior-fragment behavior. One unpublished candidate preserves atomic musical/IT validation.
Returned selection uses actual new beat positions, including shifted attacks; filler rests are not selected.

Evidence `scratch/tab-test-fixtures/tg-paste-replacement`: `integration-first.json/log` has seven direct
installed-TG matches, one native atomic end-of-song refusal where TG clears notes, and one unreadable
TG bar-overflow result with an invalid tie. Raw differences remain visible; no safety normalization.
Five model/State/history/Pattern/standalone-IT checks pass in `model-state-final.log`. Three actual-control
workflows pass in `page-first.log`: both voices/unequal advancement/Span/keyboard/atomic failure/exact history,
clipboard context, and repeated replacement/safe-paste controls. First model run caught a local selection
variable collision after adding the report; corrected before the passing State/control runs.

Final native/WASM/IT package and ZIP/listening/shortcut checks pass in `package-controls-final.log` and
`delivery-final.log`:28 native events,14 standalone IT attacks/96rows/3.999seconds,2written bars. First
package check flagged the deliberately asserted no-room HTTP400; the harness now exempts only that exact
checked refusal. No product rebuild was needed for that harness correction.
Current package `scratch/tab-package-range-duration`; separate mutable example `tg-paste-replacement/Try whole-beat paste.lnk`.
Written-bar/backing-pattern overflow remains refused; source implicit-gap expansion, broader uncommon
cohort/technique cases and owner acceptance remain open. Safe/Span/Mix/Push remain native alternatives.
Replacement worker stopped; lead owns integration and qualification. One bounded read-only Matrix/free-edit
source worker owns only `scratch/tab-test-fixtures/free-edit-workflow`. Next: Matrix free entry/audition;
existing free duration is already implemented but TG's cohort repacking remains a recorded difference.
No staging/commit/push/release.

### Previous state: clipboard context verified and packaged (2026-10-23)

One active native clipboard now selects beat or measure data; a successful copy clears the previous kind.
Ctrl+C without a beat selection opens existing measure controls. Ctrl+V/Paste dispatches the latest kind;
beat paste replaces copied lanes at the first selected onset, including backward/cross-bar selections.
Paste safe retains the former empty-only behavior. Explicit Copy selected beats still copies the caret beat.
Failed copy blocks dependent paste and retains the last successful clipboard. Existing raw Pattern paths
are separate. Source/UI only; backend replacement, measure copy/paste and strict IT safeguards are reused.

Evidence `scratch/tab-test-fixtures/paste-workflow-probe`: `findings.md` reconciles pinned actions and
TGClipboard; mix/push was already implemented as a native convenience, not a missing TG mode. Nine distinct
real-control checks pass across `page-first.log`(existing measure menu), `page-regression-first.log`
(replacement/safe and chord fresh IDs), `page-regression-second.log`(failed beat copy, fractional row,
Cut/Repeat/history), `page-qualified.log`(new full context/selection sequence and failed measure copy),
and `page-portable-final.log`(cross-track/cross-song). New helper checks exact Undo/Redo and the actual
posted destination. Existing replacement oracle `replacement-paste/tg-final.json` remains applicable:
one sounding-note match, one explicit-rest difference. Existing Mix/Push11 model/State checks remain in
`rehearsal-ready/phrase-model-state-final.log`; no unchanged backend suite was rerun.

Actual failures retained: first new test attached the engraving observer after rendering; corrected.
Old copy-failure regression expected an external-tie refusal that was intentionally removed earlier;
it now injects a named copy failure on a representable song. Old13-tuplet paste expected strict IT to
accept nonintegral ticks; guard retained, fractional-row check now uses an exact32nd-note/half-row target.
One new test assumed stored beat array order after replacement; it now checks the authored onset.
First portable invocation named the wrong test class (`page-portable.log`); corrected run passes.

Final package/native/WASM/standalone IT and delivery finalizer pass (`package-controls-final.log`,
`delivery-final.log`):16 native events,8 standalone attacks,96 rows/3.999 seconds. First packaged run
exposed a test wait that accepted the previous score revision after Undo; the wait now requires the
current document revision. Strict stale-edit refusal remained intact; corrected packaged sequence passes.
Current package is `scratch/tab-package-range-duration`. Separate mutable example:
`paste-workflow-probe/Try clipboard workflow.lnk`. Musical delivery and selected rollback remain unchanged.
Full TG replacement is still open: native copied-lane/exact-span behavior preserves uncopied voices and
note suffixes that TG may clear. The bounded oracle worker finished and is stopped. Nine raw comparisons
in `tg-paste-replacement/oracle-final.json` give one match, seven mismatches and one invalid-tie TG output;
`source-findings.md` describes cohort clearing/advancement and atomic safety exceptions. Lead is integrating
an explicit whole-beat policy while preserving exact-span paste as a separate option.
Owner sound/visual/editing-feel acceptance remains pending. No staging/commits/push/release/Computer Use.

### Previous state: Matrix entry verified and packaged (2026-10-23)

Native ROLL has explicit Grid / drag and Matrix / toggle modes. Matrix resolves the containing active-voice
beat, toggles the first matching pitch across both voices, chooses the first free playable string and uses
the caret duration for rest cells and chord resizing. Existing Place/Fit runs on one unpublished candidate;
one shared history transaction publishes only after strict standalone IT compilation. Grid / drag is retained.

Evidence: `scratch/tab-test-fixtures/matrix-entry`. The bounded worker's pinned-source/installed-manager
probe covers39 cases (`source-findings.md`, `probe-partitions.log`); worker completed and explicitly stopped.
`native-comparison-final.json`asserts35 matching sounding-note outcomes (including capo normalization), records
two first-free-string refusals, the demonstrated upstream peer-note deletion refusal, and native implicit
silence completion versus the unfilled-manager case. This does not equate saved explicit-rest spelling.
Four model/State tests pass in `model-state.log`: duration cells/dots/triplets, chord resize/retarget/Fit,
cross-voice toggle, capo, absent voice, atomic guards, byte-exact Undo/Redo, reopen, Pattern/native playback
and standalone IT. The initial test fixture wrongly included score.timing (`model-first.log`); corrected.
`page-first.log`found a wrong row-step lookup in the new branch; fixed. `page-second.log`exposed a test
that reselected the whole rest after setting the caret duration; corrected navigation. `page-third.log`
passes actual mode/grid/duration controls, rendered-note toggles, atomic chord retarget and exact history.
`page-peers.log`passes cross-voice toggle and actual peer-collision refusal. Existing Grid / drag insertion,
voice2 and percussion controls also pass in `page-first.log`. JavaScript syntax check passes.

`build.log`, `package-controls.log`and `delivery-final.log`pass. Packaged real Matrix controls/exact history,
6 native events at48kHz,4-second SONG,3 standalone IT attacks/96rows/3.999seconds reopened independently,
two written bars retained through navigation/playback, live WASM and final ZIP/listening/shortcuts pass.
The first finalizer invocation had a PowerShell quoting error before acquisition; corrected command passed.
Current delivery: `scratch/tab-package-range-duration`.
Separate mutable example: `matrix-entry/Try matrix entry.lnk`. Musical study and selected rollback remain.
Owner sound/engraving/feel acceptance is pending. Exceptions remain visible: concert-pitch labels include
capo; implicit silence is projected; explicit rests need not match TG spelling; Fit is opt-in; tied resize,
peer-note loss, protected metadata and nonrepresentable IT timing refuse. No full-parity claim.
Next independent research: reconcile claimed paste mix/push gaps against pinned source and existing native
clipboard code. One new read-only worker owns only `scratch/tab-test-fixtures/paste-workflow-probe`.

### Previous state: stem-group controls verified and packaged (2026-10-23)

Source now applies stem Up/Down/Auto to the caret voice's pinned-TG beam group, with Ctrl+Up/Down shortcuts.
Selection extent does not change the target. Explicit/implicit rests break groups; compound meter and
tuplets follow TGMeasureImpl.canJoin/TGSongManager.getDivisionLength. Identical shared-pattern contexts
remain editable; differing beam groups refuse before mutation. Track default remains a native extension.
`scratch/tab-test-fixtures/stem-groups/model-final.log`4 focused checks pass, including exact history,
unchanged playback/Pattern and byte-identical standalone IT. `oracle-final.log`10 installed-TG cases match;
the first oracle run's boxed-Long identity bug is retained in `oracle.log`, corrected to numeric matching.
`page-first.log`exposed omitted command routing and a range gate; both now route the stem action correctly.
`page-final.log`passes the existing shared-pattern/voice keyboard regression; its new test wrongly expected
two quarter notes to form one group. Corrected quarter singleton plus lower-voice triplet checks pass in
`page-qualified.log`, with actual keys/controls, renderer directions, rest no-op and exact history.
`build.log`, `package-controls.log`and `delivery-final.log`pass actual packaged controls,66 native events,
7.5-second SONG,33 standalone IT attacks/180 rows/7.498seconds, WAV/WASM and ZIP/listening/shortcut checks.
Current package remains `scratch/tab-package-range-duration`; mutable example:
`stem-groups/Try beam group stems.lnk`. Musical delivery and selected rollback are unchanged.
Oracle worker completed and explicitly stopped. Owner
sound/engraving/feel acceptance remains pending. Next: matrix insertion/toggle semantics, using a bounded
temporary installed-TG probe before changing the existing shared piano/Place path.

### Previous state: selection deletion and rests verified and packaged (2026-10-23)

Delete/Cut/Rest now share active-voice semantics for local and cross-bar selections. Cut's clipboard
still holds both voices. Clean Beat clears both; the explicit native Delete Beat control retains its
separate structural meaning. The oracle now obtains TGNoteRange from the selected voice instead of
incorrectly collecting both. Rest-only deletion closes each selected rest once; TG's repeated-caret
rest bug remains a documented difference. Existing shared-source, approval and exact IT guards remain.

Evidence: `scratch/tab-test-fixtures/selection-delete`. `model-first.log`16 focused checks pass, including
peer preservation, incident ties, empty voice/no-op, State exact Undo/Redo, playback/Pattern/standalone IT
and reopen. `oracle-first.log`6 comparisons pass (one explicit rest-bug reference). New real controls pass
in `page-qualified.log`. `page-first.log` records an overlong test title and obsolete external-tie refusal
expectation; title now fits IT's25-character limit and the old regression uses an approved-pattern refusal.
Its second obsolete assertion expected Repeat to stop at the song end; it now checks extension and Undo.
`page-regression-final.log`passes approved Cut/clipboard preservation, Repeat extension/history and Pattern.
`build.log`, `package-controls-final.log`, `delivery-final.log`pass real packaged controls, native/WASM,
standalone IT and ZIP/listening study/shortcuts. First `package-controls.log`passed the new controls but its
following generic navigation test changed from bass to guitar; the helper now restores guitar first.
Mutable example: `selection-delete/Try selection deletion.lnk`. Musical delivery/selected rollback unchanged.

### Previous state: selection-wide pitch editing verified and packaged (2026-10-23)

Reconciled source proved three gaps: local multi-beat pitch controls edited only the caret, cross-bar
semitone shortcuts used the general allocator/both voices, and Select All stopped at the displayed pattern.
Source now routes local/cross-bar shortcuts through active-voice operations; semitone preflights same-string
frets, string shifts preserve peer notes/audio guards, returned selections keep voice/caret, and Select All
spans the written track with TG's duration-error guard. General Transpose keeps its separate allocator.

Evidence in `scratch/tab-test-fixtures/selection-pitch`: `model-final.log`15 focused checks pass including
State history/Pattern/standalone IT/reopen. `oracle-first.log`6 installed-TG cases match, including atomic
fret-limit refusal. `page-first.log` passes whole-track active-voice expressions and the prior cross-bar pitch
workflow; old default-key fixture hit an occurrence-dependent IT release guard and now uses independent bars.
`page-qualified.log` passes the new local/whole-track pitch controls; its duration-error test targeted a hidden
grid and old shortcut rest assertion ignored coalescing. Both corrected tests pass in `page-guards-final.log`.
The new fret-limit fixture initially omitted its maximum; explicit24-fret setup now verifies the400 refusal.
`build.log`, `package-controls.log`, `delivery-final.log` pass real packaged controls, native/WASM, independent
IT and ZIP/listening study/shortcuts. Current package/rollback remain `scratch/tab-package-range-duration` /
`scratch/tab-package-range-expression`; musical study unchanged. Mutable example:
`selection-pitch/Try selection pitch editing.lnk`. Owner sound/engraving/feel remain pending.
All workers stopped; lead owns integration/validation/packaging. Next: reconcile selection Delete/Rest and
stem-group controls against pinned actions, preserving complete ties and atomic musical-data guards.

### Previous state: compact score spacing qualification (2026-10-23)

Score view's browser-local Compact spacing follows pinned TGLayout/TGMeasureImpl's base duration widths,
minimum active voice and adjacent chord spacing. Dots/tuplets keep their base width. Multiple displayed
tracks temporarily disable it, retaining the preference. The small alphaTab1.8.4 spring adapter preserves
grace rods, collision spacing and later-bar duration recomputation. Full native bend glyphs remain a visible
difference from TG's compact first-segment bend drawing; no pixel-equivalence or owner acceptance is claimed.

Evidence: `scratch/tab-test-fixtures/compact-spacing`. `page-first.log` passes initial actual controls.
`page-final.log` passes existing four-part view-mode regression but its expanded compact fixture had a dangling
tie after replacing a note. The fixture now retains that source note; `page-qualified.log` passes mixed written
durations/dots/tuplets, both voices, a later bar's shorter durations, chord/grace/bend collision floors, persisted
preferences, multitrack disable/restore, zoom/page resize, actual hit/caret/playhead and exact Undo/Redo.
`build.log`, `package-controls.log` and `delivery-final.log` pass final native/WASM/independent IT and ZIP.
Actual plain TAB gaps change from36.72/30.77/40.19 to21.10/20.09/21.10 pixels for quarter/eighth/dotted
quarter; this is measured geometry, not owner visual acceptance or GPU/frame timing. Current package remains
`scratch/tab-package-range-duration`, selected rollback `scratch/tab-package-range-expression`; musical study
and root listening shortcut are unchanged. Separate mutable `compact-spacing/Try compact score spacing.lnk`.
Compact implementation and editing-gap audit workers stopped; next workflow is recorded above.
No old workers or automations resumed.

### Previous state: active-voice expression qualification (2026-10-23)

Range note expressions and their mixed-value controls now target the active voice, matching pinned
Tablature.getCurrentNoteRange. Beat-level strokes retain both voices. Untouched peer ties no longer block
note-only edits; affected ties and strict IT release guards remain required. Ctrl+A, Copy and retained
selection include both voices; the previous local helper silently filtered out the other voice.

Evidence: `scratch/tab-test-fixtures/active-voice-expression`. `model-final.log`:13 focused model/history/IT
checks; `band-final.log`:6 band-expression checks. Existing tests that expected both voices were corrected
against source. Six installed-TG cases match in `oracle-first.log`; its seventh dead-note case hit the existing
off-tick release guard at120BPM. At160BPM it matches (`oracle-dead-final.log`); no guard changed.
`page-final.log` passes real active-voice dynamics/articulation, both-voice Copy, empty-voice disabled controls,
peer preservation and exact Undo/Redo. Initial checks exposed the Ctrl+A filtering defect, stale Undo waits
in the older phrase test, and ambiguous voice-option selection in the new harness (now explicit index).
The older phrase-expression control check also passed after its Undo waits were corrected.

`build.log`, `package-controls.log` and `delivery-final.log` pass the final packaged controls, native/WASM
playback, independent IT74attacks/192rows/9.996s, ZIP/listening study and shortcuts. Musical study,
selected rollback and owner acceptance remain as below. Separate mutable example:
`active-voice-expression/Try active voice expressions.lnk`. Next independent work is compact score spacing;
the compact renderer worker has finished; subsequent qualification is recorded above.

### Previous state: score view modes and multi-track editing qualification (2026-10-23)

Saved page/horizontal layout,50–200% zoom/reset,staff/TAB,all tracks and separate chord-name/diagram
visibility now project the shared document. Track-aware note/blank hits, range/caret/playhead references
and horizontal follow retain part identity. Staff-only selection includes ledger-line noteheads. Preferences
are browser-local, leave song/history untouched, and persist after reload; print keeps separate settings.
One-bar multi-beat expression selections now share the existing atomic phrase path (techniques, velocity,
curves, grace, repetition, harmonics and strokes), instead of silently affecting only the current chord.

Evidence: `scratch/tab-test-fixtures/score-view-modes`. `page-complete.log` passes real four-part controls,
staff/horizontal and TAB-only modes, clicked guitar/bass/drums, part-only range edits, exact Undo/Redo and
off-tick palm-mute atomic refusal. `page-regression.log` passes four existing staff-entry/percussion/
cross-bar-expression/playhead checks; its stale drag fixture was narrowed to one occurrence to retain the
IT boundary-release guard, and its rest expectation corrected for coalescing. That case passes in
`page-qualified.log`; that log's separate new-test failure was an invalid harness fill on a select, corrected.
Initial view checks needed explicit Staff click=select and ledger-note bounds; a subsequent test exposed
the one-bar expression defect. Native range model11 tests pass in `range-model.log`.

Pinned ViewMenuItem/Tablature confirm layout/layer choices and50–200% bounds. TGMeasureImpl shows compact
means per-beat minimum spacing, disabled with multiple displayed tracks; this is still open, alongside
toolbar/style/platform/plugin settings and owner engraving/feel. `build.log`, `package-controls.log` and
`delivery-final.log` pass: actual packaged controls, native/WASM playback, independent IT74attacks/192rows/
9.996s with volumes32/40/48, final ZIP/listening study and shortcuts. The current package remains
`scratch/tab-package-range-duration`, selected rollback `scratch/tab-package-range-expression`; the
separate mutable fixture is `score-view-modes/Try score view modes.lnk`. Owner sound/engraving/feel pending.
Compact-spacing source/renderer research is complete; both view-mode workers are stopped.
Subsequent active-voice and compact work is recorded above. Do not resume old workers or automations.

### Previous state: percussion rolls/flams delivered (2026-10-23)

Native percussion now supports rolls1/8–1/32 and grace drum keys1–100 with on-/before-beat timing,
1/16–1/64 durations, dynamics and dead grace. It reuses shared event/Pattern/history/playback paths;
grace hits select their own keymapped sample/play_note. Controls show Drum roll and Grace drum key,
retain disabled pitch-only techniques, and engrave grace percussion notes in editor/print. TG/current/1.5,
representable GP3/4/5 and MIDI roundtrip; GP/IT and overlapping-note safety limits remain explicit.

Evidence: `scratch/tab-test-fixtures/drum-ornaments`. Backend44 focused tests passed; actual PCM proves
grace sample2/G5 vs principal sample1/C5, exact history/Pattern identity and independent repeated IT
12attacks/384rows/6s. `model-interchange-final.log`:23 tests; `midi-regression.log`:56 tests; `legacy-guards.log`
retains pitched-fret refusal.40 installed-TG TG/GP cases match440 note callbacks (`oracle/qualified-results.json`)
including rate/duration/timing/dead cases, ties and repeats. `page-final.log`:two actual control/print/history
tests. `build.log`, `package-controls.log`, `delivery-final.log` pass final native/WASM/IT and ZIP.
Initial integration found MIDI's broad repetition refusal and legacy TG's guitar-fret check on drum keys;
both narrowed with evidence. Initial page assertion used Playwright's disabled check on an option, which
did not reflect its DOM disabled property; direct DOM property plus actual control behavior now checked.
The initial model fixture title exceeded the existing25-character IT limit; corrected fixture only.

Package/rollback remain `scratch/tab-package-range-duration` / `scratch/tab-package-range-expression`.
Root listening study unchanged. Separate mutable `drum-ornaments/Try drum rolls and flams.lnk` uses a mapped
two-sample kit. Owner sound/engraving/feel remain pending; external LilyPond and platform/plugin limits open.
The subsequent view-mode workflow is recorded above. Completed drum backend worker stopped.
No Computer Use/staging/commit/push/release/automation.

### Previous state: GP text encoding delivered (2026-10-23)

GP1–5 imports and GP3–5 exports accept explicit text encoding in app, collection, CLI and agent. Default
cp1252 preserves compatibility; UTF-8/Cyrillic/Shift-JIS and other ASCII-compatible Python text codecs are
supported with strict decoding, exact text roundtrip and encoded byte limits. GP6/7 retains XML encoding.
GP1/2's second credit now maps to author (pinned source), not artist. Native retains GP transcriber TG discards.

Evidence: `scratch/tab-test-fixtures/gp-encoding`. Backend multilingual/atomic/codec and GP harmonic regression
checks pass; `integration-first.log` passes single/batch/CLI/agent and GP1/2 metadata tests.20 installed-TG
text cases pass (`oracle/qualified-results.json`). Initial direct GP1/2 oracle hit the known null precise-start
bug; the existing GpFormatsProbe timing shim qualifies decoding only. Initial field comparison incorrectly
assumed artist/chord attribute/transcriber retention; exact source fields now compared and exceptions recorded.
`page-final.log` passes actual controls/remembered settings/exact editing history; first page run inspected
the collected YAML instead of the GP output, a corrected harness selection. `build.log`, `package-controls.log`
and `delivery-final.log` pass native/WASM/standalone IT and final ZIP (4attacks/16rows/1.999s, independently reopened).

Current package/rollback remain `scratch/tab-package-range-duration` / `scratch/tab-package-range-expression`.
Musical listening study/root shortcut unchanged; separate mutable `gp-encoding/Try GP text encodings.lnk`.
Owner sound/engraving/feel pending. Python codec availability, cp1252 default versus TG UTF-8, GP1/2 timing
shim and credit/format differences remain visible limits. Next: percussion rolls/flams across shared playback,
Pattern/history, TG/GP interchange and controls. One bounded backend worker owns tablature.py/tests; lead
owns integration/oracle/package. Old workers stopped; no Computer Use/staging/commit/push/release/automation.

### Previous state: native MIDI export settings delivered (2026-10-23)

Native MIDI export offers transpose/Strip CC/PC in app, collection, CLI and agent. Immutable snapshots retain
TuxGuitar's unchanged grace/alternate-trill keys, transpose drums/principal/tremolo/harmonic layers, and strip
controls/programs/master-volume while retaining bends with a one-quarter lead-in. Out-of-range keys still
refuse instead of source clamping; adding a harmonic lower octave through an instrument keymap remains guarded.

Evidence: `scratch/tab-test-fixtures/midi-export-options`. Backend worker's6 focused options tests and48
existing native-MIDI tests pass; `model-integration-final.log` passes batch/CLI/agent and atomic validation.
The initial agent test used headless State (no export workers), leaving the job queued; corrected fixture
uses ordinary State. Twelve installed-TG settings cases match note gates/keys/velocities/tempos, including
repeats, same-key trills, grace, harmonics and drums (`oracle/qualified-results.json`). `page-first.log` passes
actual single/batch controls, saved settings and exact editing history. `build.log`, `package-controls.log`
and `delivery-final.log` pass final native/WASM/IT controls and ZIP. Standalone IT:42attacks/240rows/8.000s,
independently reopened. The richer oracle fixture's off-row bend correctly refuses IT; the packaged example
uses fade without that bend and a trailing release bar. Initial fixture row-step mistake is retained in logs.

Package/rollback: `scratch/tab-package-range-duration` / `scratch/tab-package-range-expression`. Musical
delivery/root shortcut remain the32-bar part-adaptation study. Separate mutable test:
`scratch/tab-test-fixtures/midi-export-options/Try MIDI export.lnk`. Owner listening/engraving/feel remain pending.
Next substantial milestone is GP1–5 text encodings through import/export/collection/CLI/agent; one bounded
backend worker active, lead owns shared integration, tests and packaging. No Computer Use/staging/commit/
push/release/automation. Platform/plugin decisions and external LilyPond dependency remain open, not excluded.

### Previous state: GP4/5 harmonics delivered (2026-10-23)

GP5 exports all six tapped intervals and pinch/semi data0. GP4 exports tapped/pinch/semi data0 and artificial
data0/2/3, preserving authored values that TG's GP4 writer collapses to2. Other data and GP3 still refuse.
Evidence: `scratch/tab-test-fixtures/gp5-harmonics`: `model-gp4.log` passes11 tests;28 installed-TG GP4/5 cases
match written notes/harmonics and MIDI callbacks (`oracle*/qualified-results.json`). `page-final.log` passes
real harmonic/export controls with exact Undo/Redo. `build.log`, `package-complete.log`, `delivery-final.log`
pass the final package, native/WASM, standalone IT and distribution checks. The source-only fixture initially
had no sample; the package helper then needed to open and restore optional panels. The short musical fixture
correctly hit IT's final harmonic release-row refusal; `controls-complete` adds a trailing rest bar. Earlier
failure logs are retained. TG itself drops GP maxFret36 to29; its rewritten fret36 TG remains invalid and
correctly refuses native import. Original GP and callback checks retain those notes; no guard was weakened.

Current package/rollback remain `scratch/tab-package-range-duration` / `scratch/tab-package-range-expression`.
Listening remains `listening/part-adaptation/song.yaml` and the root shortcut. Separate controls:
`scratch/tab-test-fixtures/gp5-harmonics/Try GP4 and GP5 harmonics.lnk`. Owner sound/engraving/feel remain pending.
Next milestone underway: native MIDI export transpose/Strip CC/PC across single/batch/CLI/agent. Backend and
12 installed-TG cases pass; integration/page/package qualification pending. Workers completed and stopped;
no Computer Use/staging/commits/push/releases/automations. Full parity remains incomplete.

### Previous state: GP6/7 rhythm and clefs delivered (2026-10-23)

GP6/7 native import retains double-dotted durations and their supported tuplets, plus each measure's clef
(bass/alto/tenor/treble). The existing native rhythm/staff model drives editing, TG output and print; separate
GP3–5 and standalone IT representability guards remain. No owner musical data was rewritten.

Evidence: `scratch/tab-test-fixtures/gp-rhythm-clefs`. `model-first.log` passes6 existing GPX tests;
`model-rhythm-final.log` passes the new four-case GP6/7 plain/triplet import→TG→edit/Undo/reopen check.
The initial targeted command used the wrong test class name (`model-rhythm.log`). Four installed TG2.1.0
comparisons match written notes/durations/dots/tuplets and all four clefs (`oracle/qualified-results.json`).
The first two page attempts attached before renderer load and then expected an unchanged cache refresh to
render; `page-qualified.log` passes both formats after waiting for load and using the actual Track control.
Editor/print retain dots and clefs; note edits restore exact Undo/Redo. `build.log`, `package-controls.log`
and `delivery-final.log` pass package controls, native/WASM, standalone IT and final distribution checks.

Current package/rollback remain `scratch/tab-package-range-duration` / `scratch/tab-package-range-expression`;
the original part-adaptation listening study/root shortcut remain. Separate mutable controls:
`scratch/tab-test-fixtures/gp-rhythm-clefs/Try GP rhythm and clefs.lnk`. Owner listening/engraving/feel and
external LilyPond rendering remain pending. Next independent milestone underway: GP5 tapped/pinch/semi
harmonic export using existing source-qualified import/playback mappings. No workers/automations active;
no Computer Use/staging/commits/push/releases. Full parity is not claimed.

### Previous state: configurable native MIDI import delivered (2026-10-23)

Native MIDI import now exposes transpose, quantization, shortest-note and maximum-tuplet settings through
single import, collection-open/batch, CLI and agent. Collection settings survive reload. Final source CC7/CC10
is preserved; collapsed controller automation is explicitly reported, including a final neutral value.
Transpose includes drum keys, as TG does. Existing tracker conversion remains selectable.

Evidence: `scratch/tab-test-fixtures/midi-import-options`. `model-first.log` passes5 existing dispatch/collection
tests; `model-options.log` passes2 new publication/CLI/collection tests (28 notes retained, octave shift, exact
native edit/Undo/reopen and atomic invalid settings). `model-agent-final.log` passes3 agent/preservation/loss
checks. `page-first.log` passes actual single import, batch, collection-open, remembered settings and rendered
note Undo/Redo. Five installed TG2.1.0 settings cases match written timing/notes/ties/controllers in
`oracle/qualified-results.json`. `build.log`, `package-final.log` and `delivery-final.log` pass the final package,
real controls, native/WASM, independent standalone IT28attacks/64rows/7.998s, ZIP and shortcuts.
The first package run rejected an old-song UI report after import; the harness now requires a fresh successful
report and tolerates only that exact stale-owner refusal, as existing song-switch tests already do.

Current package/rollback remain `scratch/tab-package-range-duration` / `scratch/tab-package-range-expression`.
The32-bar part-adaptation listening delivery and root shortcut remain. New separate mutable controls:
`scratch/tab-test-fixtures/midi-import-options/Try MIDI import.lnk`. Owner sound/engraving/feel acceptance and
external LilyPond rendering remain pending. Next independently actionable milestone: GP6/7 double-dotted
rhythm and changing-clef preservation through the existing adapter; GP5 harmonic export follows. Both audit
workers are stopped. Continuous authorization remains; no Computer Use/staging/commit/push/release/automation.

### Previous state: PTB/TEF mixer delivered (2026-10-23)

PTB source volume/pan and TEF2/3 attenuation/pan now survive native import, note editing and TG/MIDI export.
They use the shared source-controller bindings and64-step native mixer; TEF no longer forces near-center
pan to center. Invalid controller values refuse before song/sample publication. Source effects/timbre remain
explicit losses. Existing songs and owner musical levels were not rewritten.

Evidence: `scratch/tab-test-fixtures/library-mixer`. `model-first.log` passes six tests including malformed
publication guards; a new test initially compared dicts to tuples, and two older tests passed source metadata
as a program/bank-only mapping. Both harness errors were corrected without relaxing exporter guards.
`model-final.log` passes both affected tests, covering160 legal-value roundtrips. `oracle/qualified-results.json`
matches all128 PTB and16 values for each TEF generation against installed TG2.1.0 active-channel fields and
controller callbacks. `page-first.log` passes actual controls in all three formats: visible imports, rendered
note edits, same-value Write Mix, exact Undo/Redo and TG/MIDI output. `build.log`, `package-controls.log` and
`delivery-final.log` pass pinned build, real controls, native/WASM, independent standalone IT, ZIP and shortcuts.

Current package remains `scratch/tab-package-range-duration`; selected rollback remains
`scratch/tab-package-range-expression`; listening song/root shortcut still target the32-bar part-adaptation
study. Separate mutable imported controls: `scratch/tab-test-fixtures/library-mixer/Try imported mix.lnk`.
Owner sound/engraving/feel acceptance and external LilyPond rendering remain pending. The next independently
actionable workflow is native MIDI import options and source controllers through single/collection import.
Read-only audit also identified GP6/7 double-dot/changing-clef adapters and GP5 harmonic export as genuine
subsequent gaps. Both bounded audit workers are stopped. No staging/commits/push/releases/Computer Use or
automations. Full parity is not claimed; platform/plugin scope and existing safety differences remain open.

### Previous state: notation delivery packaged (2026-10-23)

LilyPond's part/range, version and layout controls now work in single-file and collection delivery, with saved
collection settings. Print preview exports SVG/PNG/JPEG/BMP; raster output is192ppi, JPEG95%, BMP24-bit lossless.
Invalid part/range/settings and malformed images refuse. No song/history mutation is needed for delivery.

Evidence: `scratch/tab-test-fixtures/notation-delivery`. `model-final.log` has14 passing notation/collection
checks; the later settings-object guard passed both TestRefusalsAndPurity tests. `server.log` has8 passing
server/export checks. `page-first.log` has2 passing actual-control/image tests, including native server save,
decoded BMP equality to PNG and bounded JPEG difference. Four settings combinations match installed TG2.1.0
byte-for-byte (`oracle/qualified-results.json`). The first oracle fixture requested four bars from three and
correctly refused; corrected `oracle-final.log` passes. `build.log` and `package-final.log` pass: real controls,
four image formats/PDF, native/WASM, Pattern synchronization and standalone IT74attacks/192rows/9.996s.
Initial `package-controls.log` timed out because the new helper left EXPORT selected; returning to TAB in the
harness fixed it with the same package. `delivery-final.log` verifies final ZIP, shortcuts and artifact digests.

Current package: `scratch/tab-package-range-duration`; rollback: `scratch/tab-package-range-expression`.
Existing part-adaptation listening study and root shortcut remain. Separate mutable controls:
`scratch/tab-test-fixtures/notation-delivery/Try notation delivery.lnk`. Owner sound/engraving/editing-feel
acceptance remains pending; external LilyPond rendering is unqualified (no installed executable found).
No foreground/ear acceptance claimed. The next milestone is in progress: preserve PTB/TEF source mixers
through existing native imports, edits and exports. All160 legal-value installed-TG comparisons pass;
real controls and package qualification remain. Full parity and platform/plugin gaps remain open below.

### Previous state: mixer interchange delivered; continuous parity integration (2026-10-23)

The owner authorizes continuous related milestones in this conversation. No Computer Use, staging, commits,
pushes, releases, old-worker resumption or automations. One read-only audit worker completed and was stopped.
The dirty `main` checkout and empty index are preserved. Historical stop-after-batch instructions are superseded.

TG now imports all 0..127 volume/pan values, retaining exact CC7/CC10 alongside the native 0..64 mixer anchors.
GP1–5 also retains source volume, fixing the former CC7 rescaling loss. TG exports uniform part mixes; GP3–5
exports exact coarse mixer steps. Explicit same-value Write Mix removes only the touched controller binding;
Undo/Redo restores exact song bytes, including after reopen. Name/program edits retain bindings. Unequal string
mixes, mute, non-neutral global/effects controls, shared TG channels and inexact GP settings remain guarded.
Native/IT audio uses existing tracker mixer quantization; exact external controllers are not synth equivalence.

Evidence: `scratch/tab-test-fixtures/mixer-interchange`.
- `model-first.log`: 228 focused interchange/MIDI checks, 226 passed; two stale expectations were identified.
  `model-final.log`: 20 focused final tests pass, including both corrected failures, new mixer coverage, GP5
  export guards and CI test registration. Earlier successful unchanged format tests are reused.
- `page-first.log`: actual setup, same-value volume/pan writes, exports and exact Undo/Redo pass (2 tests).
- `oracle/qualified-results.json`, `oracle.log`: 179 installed TG2.1.0 cases match CC7/CC10 callbacks and rewrite
  fields: all128 TG values and17 GP steps in each of GP3/4/5. Source audio quantization remains explicit.
- `build.log`, `package-controls.log`: pinned package and selfcheck pass. Real controls, native/WASM playback,
  Pattern synchronization and standalone IT pass:74 attacks/192 rows/9.996s reopened independently, exact source
  IT bytes. `delivery-final.log` verifies ZIP contents, shortcuts and final artifact digests.

Actual failures were test expectations: the TG refusal fixture now uses unsupported chorus rather than admitted
volume; fade-in checks unchanged note/timing events while requiring its already-implemented gain events.
The new GP test initially passed an unserialized PyGuitarPro model with no version; it now uses a real roundtrip.

Current package remains `scratch/tab-package-range-duration`; selected rollback remains
`scratch/tab-package-range-expression`. Existing musical listening delivery and root shortcut remain
`listening/part-adaptation/song.yaml` (owner levels/notes preserved). Separate mutable four-bar mixer controls:
`scratch/tab-test-fixtures/mixer-interchange/Try mixer interchange.lnk`. Owner acceptance queued: sound,
engraving and editing feel for the current build; same-value Write Mix/Undo and imported-mix feedback in controls.
No foreground capture or listening acceptance claimed. Next independent milestone: complete exposed notation
delivery options through the existing LilyPond exporter and score-image path; verify current implementations first.

### Previous state: alternate tunings and dependable part adaptation (2026-10-23)

Implemented and stopped after one final package. Track setup defaults to automatic channel assignment:
retained strings keep their channels, added strings append independent channels, and removed strings leave
raw Pattern data intact. Tuning, name/color, clef/key/stem, sample instrument and MIDI setup changes share one
native history transaction. Explicit channel mode remains available. The performed-event guard checks
repeat-aware playback, harmonic nodes and string-dependent techniques before any write. Unplaceable notes
refuse instead of being dropped. First-track setup on legacy tracker songs uses the existing score overlay
path again, preserving raw effects. One bounded tuning-oracle worker completed and was stopped.

Evidence under `scratch/tab-test-fixtures/part-adaptation`:
- `model-final.log`: 21 focused model/history/docs checks pass, including 7/12/25 strings, reduction,
  capacity refusal, unchanged peers/raw cells, natural harmonics, repeats/negative capo and exact reopen Undo.
- `page-final-controls.log` and final executable `package-render-final.log`: real automatic setup, combined
  metadata, reduction and exact Undo/Redo pass. Rendering completes for the current revision at 7/12/25
  strings without page errors. Existing manual source-pan control passed in `page-first.log`; repaired legacy
  first-track setup passed in `page-final.log` (those logs retain other harness failures, resolved below).
- `oracle/qualified-results.json`: 14 qualified cases, nine direct TuxGuitar matches and five named native
  safety differences. `oracle/final.log` retains the unchanged passing cases; `harmonics.log` qualifies the
  corrected natural-node fixture. Grace/trill alternate pitches remain fixed; unplaceable notes and unsafe
  natural-harmonic node changes refuse atomically. Raw upstream differences are retained explicitly.
- `study-final.log`, `audio.log`: 32-bar/four-part study has a seven-string Drop D lead, five-string bass and
  21 channels. Every performed event is unchanged; opening ten seconds of native PCM match byte-for-byte at
  44.1/48 kHz. GP5 full signature matches. Two incompatible lead chord diagrams are removed and reported.
- `build.log`, `package-controls.log`, `package-study.log`: one final pinned build; packaged controls,
  native/WASM playback, standalone IT reopen and complete band export pass. IT has 721 attacks/3468 export
  rows, 90.278 seconds reopened without a plan; technique-render RMS/native ratio is 1.0057 within the
  existing comparison bound. Existing pitch/timing export warnings remain visible.
- `delivery-final.log`: actual GP5 full signature and TG events match; standalone IT equals source compile;
  full score has six pages, lead part three pages and other three parts one page each. Mix and four stems
  align at 44.1 kHz/4,070,981 stereo frames. Final EXE/ZIP digests and ZIP verification are recorded here.

Actual failures resolved: allocation initially validated against old-width raw rows; candidate raw rows now
expand without touching source cells. The new preservation guard initially used a linear plan on repeat
scores; it now uses the existing repeat projection. The legacy first-track control exposed a native-only
command refusal, repaired through the existing overlay edit. Harness fixtures initially referenced a missing
sample, waited for the read endpoint instead of the command endpoint, and constructed an invalid skipped tie;
those were corrected without relaxing product checks. The harmonic oracle initially chose a node whose
fallback retained pitch; node 7-to-9 now demonstrates the real sound change and atomic refusal.

Current/rollback remain `scratch/tab-package-range-duration` and `scratch/tab-package-range-expression`.
The root listening shortcut opens `listening/part-adaptation/song.yaml`; `Try part adaptation.lnk` opens the
separate mutable four-bar controls. Final band output was moved into the package rather than retaining a
duplicate delivered song; tests/oracle inputs and previous owner listening variants remain separate.
No Computer Use, foreground acceptance, staging, commit, push or release. Owner listening/editing/engraving
acceptance is the next action. Native tracks allow 25 strings, module capacity is 64; GP5 and other formats
retain stricter limits. Unsafe techniques refuse; channel routing still follows the selected string and
explicit assignment. Full parity is not claimed and no worker or automation should resume automatically.

### Previous milestone and cleanup: repeat-aware rehearsal (2026-10-23)

Owner-authorized cleanup after delivery removed 4,088,041,075 file bytes (3.81 GiB), across 149 exact targets.
Eleven superseded agent previews under `dist/`, three PyInstaller cache targets, one disposable PDF browser
profile, 89 `.tryout` render caches, two duplicate delivered-song folders and 43 byte-identical generated
outputs were removed. Unique song variants, samples, notes/history, source tests and regression inputs remain;
so do the current/rollback packages and published 1.8.0 distribution. Owner `test/` and unrelated references,
toolchains, recoveries and music were excluded. Both current shortcuts resolve after cleanup.
`scratch/cleanup-generated-20261023/plan.json` maps targets to keepers/recovery; `receipt.json` records all
149 successful operations with no error. Eight small metadata files were byte-verified in `unique-metadata.zip`.
The deleted `repeat-performance/band-delivery-final/song-yaml` and `advanced-rhythm/band-delivery/song-yaml`
outputs are retained under the corresponding current-package `listening/` directories. Historical evidence
links to those generated copies now refer to these keepers. Failure/final-result logs remain. The existing
guarded cleanup runner checked containment, reparse/protected markers, tracked paths, active processes,
preview inventories and duplicate/recovery content before native PowerShell deletion. No product tests were
rerun for artifact-only cleanup; no processes were stopped, workers resumed or Git publication actions taken.

Implemented, qualified, packaged and stopped. One bounded
presentation worker was used and stopped. No Computer Use, staging, commits, pushes or releases. Branch main,
index empty; unrelated dirty work, prior listening songs and the selected rollback are retained.

- Rehearsal follows the complete continuous traversal inside the chosen source bars, including returns with
  skipped endings. One visit selects an individual completion; Visit chooses a later reachable traversal.
  It never silently includes outside bars. Loop passage can be cleared for exact play-once completion.
- Count-in, meter clicks, tempo steps, pause/resume and cancellation keep using the native audio clock.
  Arrangement edits stop stale practice explicitly. Ordinary playback reloads retain a still-reachable
  performed visit instead of returning to its first appearance. Rehearsal never writes song/history.
- Every printed page identifies the part/full score, original source bars, section/continuation and page
  count, with reserved footer space. Existing per-bar clef/key overrides, page-break ties and lyric anchors
  are preserved. A proposed cumulative-clef change was removed after import/export source comparison showed
  that it would change existing saved semantics.
- Windows Edge PDF export now suppresses its compatibility relaunch, which previously returned exit0 with
  no DOM/PDF and detached a child. The exact necessary flag was isolated against the working Playwright
  launch. No sandbox bypass or dependency was added. PDF failures now include the browser exit/completion
  reason. Actual score/part rendering and cancellation checks pass.

Evidence: `scratch/tab-test-fixtures/repeat-performance`.
- `engine-final.log`: 3 tests pass, including exact tied-tail/raw backing and bend/let-ring/second-voice
  seek/play-once PCM at 80/100/125%, silence at the endpoint, repeat/endings range selection, count-in,
  stepped-loop replay and meter click frames. `compatibility.log`: 5 focused CI/standalone IT/native repeat
  checks pass. `ci-registration.log` confirms new modules are included in existing CI.
- Source real-control checks pass for full traversal, later visit, pause/resume/play-once, atomic invalid
  range refusal, edit cancellation, retained repeat visit after reload and exact Undo. Existing practice
  Solo/Mute/count-in/ramp/load-cancellation checks also pass (console results; redirected source logs are empty).
- `performance-parts-final.log`: 4 focused dense/excerpt/part page checks pass; `pdf-final.log`: 2 real PDF
  output/cancellation checks pass. `performance-parts-headless.png` and the delivered score page are artifact
  layout evidence, not foreground visual acceptance.
- `tg-comparison.log` and `tg-comparison.json`: installed TuxGuitar TG/GP5 callbacks match 1442 note-on/off events
  and all tempo changes. `study-qualified.log`: 32 written bars/four parts, 38 performed occurrences, full GP5
  signature equality. The original 659 written notes/53 ties and samples are retained; the mixed 3/4-and-7/8
  closing section now has repeat/alternate endings.
- `package-study.log` retains the actual PDF failure; `pdf-exit.log`, `browser-launch.log`,
  `browser-flags.log` and `pdf-fixed.log` document launch isolation and successful real rendering.
  The necessary PDF repair required replacing the initial candidate in the same current package directory;
  `build-final.log` records the final pinned build. There is one final current package and one selected rollback.
- `package-study-final.log` passes actual band export, imported GP5/TG edits/Undo/reexport, full GP5 readback,
  native/WASM and standalone IT 721 attacks/3468 rows/90.278 seconds, RMS/native 1.0057. Its final harness assertion
  counted expected stale-preparation retry 400s during rapid edits as errors. The corrected harness accepts
  only that exact response after checking the current engine revision is loaded and error-free; the actual
  completed band outputs are reused after verifying notation, source IT and sample equality.
- `package-controls-final.log` and `package-study-qualified.log`: final executable checks pass. The latter
  proves current-revision recovery after three superseded preparations, imported edit/Undo/round trips,
  native TAB and standalone IT. `package-study-body-stall.log` preserves the reporting stall: reading an old
  response body after navigation could block indefinitely, so remaining failures report status/URL directly.
  `package-study-closed-assets.log` retains old-song asset 404s; the checker now records closed render keys
  and can accept only those obsolete requests after successful current audio/spectrum/meters checks.
  A generic network-idle wait was rejected after the app's periodic polling timed it out
  (`package-study-networkidle.log`). The final run had no asset 404s. A fresh-shell missing browser variable
  is retained in `package-study-browser-env.log`; final checks used the installed Edge explicitly.
- `delivery-final.log`: final ZIP/EXE identity, archive CRC, portable song, shortcut targets and selected
  rollback pass. GP5 full signature and TG performed events match; the six-page score and four part PDFs
  identify every page. Mix plus four stereo stems each contain 4,070,981 frames at 44.1 kHz. Final distribution
  hashes are recorded there. No complete local suite was rerun; focused modules are registered in existing CI.

Current target remains `scratch/tab-package-range-duration`; rollback remains `scratch/tab-package-range-expression`.
Root `Listen to current preview.lnk` opens the packaged `listening/repeat-performance/song.yaml`; mutable
controls and the separate `Try repeat rehearsal.lnk` are under the evidence directory. The final ZIP includes
the study, notation exports, PDFs, mix and stems. Previous listening songs and the rollback remain preserved.

Remaining limits: ranges requiring excursions outside selected bars still refuse; count-in applies only at
initial start. Full TG traversal/scroll/style equivalence, existing rhythm/routing/interchange guards and owner
listening/editing/engraving acceptance remain open. A trial extra cropped-tie annotation encountered the existing
single-bar last-beat annotation/lyric spacing guard and was not shipped; no general dense-engraving closure is claimed.
Automatic approval review originally rejected temporary PDF diagnostic cleanup with only "blocked by policy".
The later owner-authorized reviewed cleanup removed the disposable browser profile; diagnostic logs and PDFs
remain as evidence. No automatic continuation is authorized.

### Previous state: advanced rhythm and dependable phrase rearrangement (2026-10-23)

Implemented, packaged and stopped. Owner requested minimal subagent use: one bounded timing worker was used
and explicitly stopped; integration handled the editing, controls, study and delivery. No Computer Use,
staging, commits, pushes or releases. Branch main, index empty; unrelated dirty work and previous songs retained.

- Free duration (including Longer/Shorter/dots/tuplets) now takes precedence over Fit, permits explicit
  overfull unique bars and trims bare rests without overwriting sounding notes or annotated rests. Other
  voices/raw rows stay intact. Independent measures prepares reused/divided patterns in the same transaction;
  meter changes can rebar overflow. Gaps/overfull bars remain visible, selected beats remain selected and
  history restores exact bytes. Like the prior Free Insert rest behavior, later bars wait; TG overlaps them.
- Partial replacement/Push paste crops bend and whammy curves when integer written points and every retained
  discrete pitch step are exact. The retained tail is a fresh attack at its retained pitch offset. Complete
  let-ring paste may split across bars after comparing its destination gate with unsplit notation through
  the existing playback planner. Unsafe neighbor-dependent gate changes still refuse atomically.
- Standalone IT tries the original rows first, then exact export-only subdivisions for dense rhythms,
  SDf limits, qualifying pitch curves and release/attack collisions. Physical tick duration/tempo and native
  source patterns do not change. Raw absolute tempo/pan/notes/static volume survive; tick/row effects or
  automation refuse. The envelope/raw-note qualification at48kHz is PCM-identical. Existing37.5-cent pitch
  bound and final repetition-tail1/960-quarter quantization remain; no tolerance was relaxed.

Evidence: `scratch/tab-test-fixtures/advanced-rhythm`.
- `focused-final.log`:35 model/history/IT/CI-registration checks pass. `regression.log` retains a later
  obsolete pan-collision expectation; positive exact-pan tests now cover it. `it-gp-regression.log`:65
  standalone-IT/GP checks,64 passed and one old palm-mute/pan refusal became supported. The corrected
  expectation and positive independent-tick case pass in `it-regression-final.log`; unchanged passes reused.
- `page-first.log`:actual headless Free duration, two cropped curve fragments, cross-bar ring paste,
  overfull warning and exact Undo/Redo pass without page errors. `package-controls.log` repeats those
  controls on the final executable and passes live WASM, standalone IT and selfcheck.
- `tg-third.log` / `tg/comparison.json`:installed TG rewrites preserve cropped bend/whammy notation and
  performed events; mixed pickup rebar matches written notes/rests. Free duration's dotted whole is retained
  in `tg/free-duration/result.xml`; native import correctly rejects TG's invalid overfull bar. This does
  not claim TG crops curves identically or that free-overflow playback matches TG.
- `study-qualified.log`:32bar/fourpart study retains659written notes and full GP5 signature. Bars25-32
  alternate3/4 and7/8 with dense triplets and sustained second voice; native samples unchanged.
- `build.log`:one final pinned build. `package-study-qualified.log`:actual GP5/TG imports, visible note
  edit/exact Undo/Redo and reexport, full GP5 signature, navigation/live WASM and standalone IT661attacks/
  3240rows/84.343seconds pass. Standalone IT RMS/native1.0056 retains existing quantization. It reuses the
  unchanged successful actual band-preset step in `package-study.log`, checking notation/IT bytes/samples
  before reuse. No rebuild for test-harness-only corrections.
- `delivery-final.log`:actual GP5 signature and TG performed readback,659notes/53ties, score6pages,
  parts3/1/1/1pages, stereo44100 mix and four stems each3809138frames; ZIP CRC/content and shortcut targets
  pass. The mixed-meter PDF page was inspected as a local artifact, not foreground evidence.

Real failures retained: initial cropped peak lasted1/320quarter and could not survive an IT tick; the
guard remains, and the qualifying fixture uses representable held endpoints. A large restarted pitch
offset exceeded one IT fine command; retained guard. Initial oracle fixture used numeric channels and
residual raw pan, corrected only in comparison inputs. The new study initially used a GP5-unsupported
double-dotted3.5-quarter sustain, now expressed as tied dotted-half/eighth notes. Package import harness
used the same destination for study.gp5 and study.tg; now includes the extension. Its IT timing check assumed
source row_step; now reads actual Axx speeds from the exported module. Final checks pass without altering
the final executable. No errors were bypassed by relaxed tolerances or discarded source state.

Delivery: `scratch/tab-package-range-duration/vulturetracker.exe` and `vulturetracker-win64.zip`.
Listening: `listening/advanced-rhythm/song.yaml` and sibling band outputs; root `Listen to current preview.lnk`
targets it. Separate editable fixture: `scratch/tab-test-fixtures/advanced-rhythm/controls/song.yaml`, opened
by `Try advanced rhythm.lnk` in that evidence folder. Selected rollback remains
`scratch/tab-package-range-expression`; earlier listening copies stay on disk.

Remaining limits: new slide cuts, cropped let-ring, tied curve crops, fractional curve points or changed
discrete pitch steps, changed ring/strum gates, genuinely off-IT-tick timing, raw tick/row effects/automation
during subdivision and >1024export rows per pattern refuse. Stateful routing and upstream GP rewrite
limitations from the prior milestone remain. Owner listening/editing/engraving acceptance is pending.
No work resumes automatically; keep subagent use minimal on the next authorized batch.

### Previous state: expressive arrangement editing and complete GP5 delivery (2026-10-23)

Owner authorized related fixes, subagents, focused checks and one final local package. Implemented,
packaged and stopped; all three workers are stopped. No Computer Use, staging, commits, pushes or releases.
Evidence: `scratch/tab-test-fixtures/expressive-arrangement`.

- Fit moves intact expressive notes while retaining techniques and authored velocity. Safe let-ring
  rebar/Move and strum crossings preserve actual sustain/attack spacing. Partial replacement paste keeps
  static expression on surrounding fragments; a retained trailing fragment starts afresh. Shorter on a
  slide can insert a rest and make the slide inactive, as in TG; its standalone IT bytes match a plain note.
  Gate checks use actual tempos, including raw T commands and independent preparation. Deleted Move-left
  heads are distinguished from replacement attacks reusing their IDs. All edits share exact Undo/Redo.
- Voice separation supports Continue/Off NNA with non-carried volume/pan/pitch envelopes and fadeout.
  Continue reserves a spare lane when release and attack coincide, preserving the standalone IT key-off.
  Native before/after PCM is exact across playback, repeat, seek and ranged tails; native/WASM matches at
  44.1/48kHz. Standalone IT relative PCM RMS error0.3223%, RMS/native1.003056 retains velocity quantization.
- GP5 retains chord diagrams, pick directions and brush strokes, including shared two-voice metadata.
  Neutral spare-channel routes project to GP track/voice routes with explicit sound/release warnings.
  GP5.00 import accepts TG's unset reverb=-1. Standard GP credits remain intact in our own readback;
  conversion warns about Windows-1252 and TG credit/comment handling. Band package now includes GP5.

Focused qualification:
- `rhythm/models-qualified.log`:48 model/history/IT checks; `clipboard-regression.log`:25 checks;
  `rhythm-final.log`:13 final rhythm cases, including actual-tempo and deleted-ID regression coverage.
  `page-fifth.log` passes actual Fit/Shorter/partial paste/strum rebar and exact history. `tg-qualified.log`
  plus `tg-shorter.log` cover seven installed-TG edits with equal performed events. Native keeps a
  let-ring continuation flag that TG clears; the notation difference is explicit.
- `routing/model-final.log`:8 model/audio/history cases; `routing/page.log`:2 headless control cases.
- `interchange/models-qualified.log`:46 focused cases. `interchange/cp1252/qualification.json` and
  `oracle-qualified.log`:31 installed-TG cases, full-study and GP3/4/5 brush/pick metadata, actual
  read/rewrite and note/pitch/tempo callback comparisons. Upstream credit remapping, joined comment
  lines, max-fret24 and padded drum strings are recorded differences, not claimed equal metadata.
  Both full-study GP5 imports pass note edit/Undo/Redo/reopen/reexport (`import-history.json`).
- `collection.log` and `collection-page-final.log` qualify the GP5 band preset and retained successful
  outputs after PDF failure. `ci-registration-final.log` passes; remote CI/full suite was not run.
- `build-final.log` is the pinned executable. `package-study-final.log` passes full GP5 signatures,
  both actual full-study import/edit/reexport variants, live WASM and standalone IT647attacks/1692rows/
  88.091seconds, RMS/native1.0053. It reuses the unchanged actual band-control result in `package-study.log`.
  `package-rhythm-final.log` and `package-routing.log` pass the final executable's controls/history,
  playback, standalone IT and selfcheck. The routing fixture restores17attacks and exact Undo.
- `delivery-readback.log`:GP5 retains664written notes/73ties; TG performed events match. PDF score5pages,
  parts2/1/1/1; stereo44100 mix and four stems each3974513frames. First PDF page inspected as an artifact,
  not a foreground capture. `delivery-final.log` records ZIP integrity, shortcut readback and final digests.

Real failures retained: the initial collection harness targeted its source folder; corrected to a sibling.
Rhythm logs retain stale endpoint/unsupported strum fixture and the real inactive-slide refusal, now fixed.
Routing logs retain the Continue key-off collision. GP oracle logs retain reverb, encoding and upstream
metadata differences; stale old refusal assertions were corrected. `build.log` was interrupted before
publishing a binary after a final Move-left fix; its analysis cache was invalidated before `build-final.log`.
Initial package launches competed for the shared app registry; final checks ran sequentially. A GP5-to-IT
harness race read the previous export's done status; it now waits for a new job_id before accepting completion.

Current executable/ZIP remain `scratch/tab-package-range-duration/vulturetracker.exe` and
`vulturetracker-win64.zip`. New study/deliverables: `listening/expressive-arrangement/song.yaml` and sibling
GP5/TG/MIDI/IT, PDFs, mix/stems, imports. Imported originals and TG rewrites remain separate. `Listen to
current preview.lnk` and `scratch/tab-test-fixtures/expressive-arrangement/Try expressive arrangement.lnk`
target this study. Mutable checks stay under this batch's `rhythm/check` and `routing/check` folders.
Earlier listening songs and rollback `scratch/tab-package-range-expression` are preserved; index is empty.

Remaining limits: new slide cuts, cropped bend/whammy/let-ring, cross-bar let-ring paste, changed ring gates
or strum timing, and off-grid IT refuse atomically. Stateful Cut/Fade, DCT, carried envelopes, randomness,
filters/plugins remain restricted. GP timbres do not reproduce native samples; TG rewrite differences
remain explicit. Owner listening/editing/engraving acceptance is open. No work resumes automatically.

### Previous state: complex-score editing and faithful round trips (2026-10-23)

Owner authorized subagents, related fixes, focused checks and one final local package. No Computer Use,
staging, commit, push or release. Three bounded workers completed rhythm, interchange and engraving;
integration owns voice routing, combined study, final qualification and handoff. Workers are stopped.
Evidence: `scratch/tab-test-fixtures/complex-score`. Final package qualification passed; this batch is stopped.

Part/Track acceptance follow-up (2026-10-23): Part sounds now selects through the score editor's existing
track switch. Editor selection changes update Part sounds through the shared controls path, including
refresh/Pattern selection. Both dropdowns display the same part and the correct sound. Caret changes do
not reset a pending sound choice, and part selection does not change song bytes or Undo history.
`scratch/tab-test-fixtures/part-track-sync/before.log` reproduces Part=Bass with the lead score still shown;
matched headless `before/` and `after/` captures show the corrected bass score. `after.log` passes existing
assignment/audition/mute/solo/history and SF2 tests; its new note assertion initially treated alphaTab's
closed-hi-hat articulation101 as a MIDI pitch. The corrected note comparison passes in `final.log`.
`package.log` passes the rebuilt executable's selector/engraved-note/sound-target/history assertions,
32-bar navigation/live WASM,647-attack standalone IT export and selfcheck. `build.log` is the one pinned
update build; `delivery.log` records ZIP integrity and final artifact digests. Listening data, shortcut and
the selected rollback are preserved. No foreground/Computer Use evidence; owner visual acceptance remains.

Implemented:
- Full expressive notes survive structural splitting by Move, rebar, independent preparation and full-span
  cross-bar paste: vibrato, staccato, palm mute, dead/hammer, fade-in, harmonic, grace, trill, tremolo picking,
  bend and whammy. Head effects are not duplicated. New slide/let-ring/strum cuts, truncated expressive
  pastes and tick-changing splits refuse atomically. The shared document/history path remains authoritative.
- Beat annotations/chord names reserve horizontal spring space; chord-chart captions reserve measured
  padding without changing fret geometry. Overfull labels give a width/scale remedy. Existing marker-band,
  horizontal track-name and redraw-overlay fixes remain intact. Matched headless before/after and isolated
  chord-padding captures are in `engraving/`; this is not foreground or owner visual acceptance.
- GP3/4/5 supported grace export, including the corrected legacy transition/duration byte order. GP3/4
  require before-beat timing and dead fret0; exact grace velocity steps are enforced. TG/GP add counted
  export-only rests for sparse voices/pickups. TEF3 retains supported same-string grace metadata and
  extended frets; long/compound/cross-string grace still refuses. GP6/7 pickup-to-TG now succeeds.
- Part sounds -> Separate overlapping voices uses compatible spare channels within that part. Written
  spans, performed spans, ties and reused occurrences participate in allocation; strict IT compiles before
  shared history saves. Raw cells, incompatible authored/transient mix, insufficient space, stale revision
  and approved patterns refuse. Numeric channel counts work. A reproduced release-tail difference showed
  equal event lists are insufficient: reassignment conservatively refuses envelopes, fadeout, non-cut NNA,
  duplicate checking, randomization, filters and channel plugins. No-op remains allowed.
- A real integration failure with remembered24-bit settings is fixed: collection conversion applies
  rate/depth only to audio, and24-bit only to WAV/FLAC. TG/MIDI/IT no longer inherit invalid audio depth.

Focused evidence:
- `models-integrated.log`:19 model/history/interchange/CI-registration checks. `routing/model-final.log`:
  five routing checks including exact Undo/Redo, reopen, no-op, source preservation and refusal cases.
  `routing-tail-review*.log` retain the failing envelope/duplicate-check audio experiments; supported
  stateless routing is PCM-neutral, while standalone IT retains its existing velocity quantization.
- `rhythm/`:32 focused checks,27 clipboard regressions, final effect combinations and actual rebar/Move/
  Paste controls. Installed TG vibrato/bend rebar gives zero notation/rest differences and matching native
  performance readback. This is not independently rendered TG audio.
- `interchange/qualification.json`:99 installed TG GP cases match written notes, MIDI callbacks and TG
  rewrite; GP6/7 pickup imports round-trip through TG; two original32-bar TEF3 variants each match320notes.
  Four published imports pass edit/Undo/Redo/reopen. Seven new and19 adjacent export regressions pass.
- `engraving/final.log`, `narrow-normal.log`, `later1920.log`: dense annotation/chord/lyric, selected-part
  TAB/staff print, resizing and redraw checks. Normal labels fit900px; pathological labels refuse visibly.
- `pages-integrated.log`: actual routing/rebar/Move/Paste controls pass, byte-exact Undo/Redo, no page errors.
- `delivery-depth-regression.log`:24-bit band output retains TG/MIDI/IT and24-bit WAV when PDF fails.
- `delivery.log`, `delivery-readback-final.log`:32-bar/four-track Crosscurrents study,664written notes,
  73ties,647performed attacks. Full TG readback preserves performed events. Five score pages and2/1/1/1
  part pages; stereo44100Hz mix and four stems each3974513frames including release tail. First score/lead
  pages were inspected from PDFs. Full study GP5 still refuses chord/pick-stroke metadata; its TG/MIDI/IT
  outputs remain available. Separate imported GP/TEF examples retain their own placeholder sounds.

Real failures retained: `prepare.log` (IT title limit; shortened module title), routing release-tail and
numeric-channel defects (fixed/guarded), `delivery-readback.log` (test omitted repeat projection; corrected),
`package-study.log` (GP5 preflight refusal exposed a missing harness response check), `package-study-final.log`
(remembered24-bit settings blocked TG; shared conversion fixed). Final source/package checks follow below.

Final delivery:
- `build-final.log` is the pinned final executable. The earlier candidate in `build.log` was replaced after
  the real collection-depth failure; one current executable/ZIP is retained, with no extra candidate build.
- `package-study-qualified.log` passes the final executable: saved PDF settings, four actual GP6/GP7/TEF3/
  sparse-GP5 imports and note edits with exact Undo/Redo; TG/GP5 reexports preserve performed events;
  32-bar navigation, assets and live WASM pass. Strict IT reopens647attacks over1692rows,88.091seconds,
  equal to the source compiler; measured RMS/native ratio1.0053. Selfcheck passes. The saved72% Letter
  print check makes10pages; the delivered60% A4 score has5pages.
- `package-routing.log` and `package-rhythm.log` pass actual controls, exact history and live/standalone IT
  on the preceding candidate; those modules are unchanged in the final build. Routing restores17attacks;
  rhythm restores4attacks with measured IT/native RMS0.9907. No owner listening claim.
- `source-study-final.log` retains a harmless stale-song UI-report rejection during rapid import switches.
  Final qualification explicitly checks a successful report for the current song before accepting only
  that known stale response. `package-delivery.log` retains an archive-root verification mistake;
  `package-delivery-final.log` verifies the repaired VultureTracker/ root, CRCs and executable/study bytes.
- Current executable/ZIP: `scratch/tab-package-range-duration/vulturetracker.exe` and
  `vulturetracker-win64.zip`. Original study and separate imported variants:
  `scratch/tab-package-range-duration/listening/complex-score/song.yaml` and `imports/`.
  PDFs, mix/stems and TG/MIDI/IT exports sit beside the study. All four delivered imports reopen natively.
  `Listen to current preview.lnk` and `scratch/tab-test-fixtures/complex-score/Try complex-score editing.lnk`
  target the final executable and new study, with target/arguments read back. Earlier listening songs and
  selected rollback `scratch/tab-package-range-expression` are preserved. Mutable short editing examples
  remain separate in `complex-score/routing-check` and `rhythm-check`.
- The pre-selector-fix digests remain in `complex-score/package-delivery-final.log`; current artifact
  digests are in `part-track-sync/delivery.log`. New focused modules are registered in CI; registration
  check passes, remote CI was not run. Main and
  the empty index are preserved. No staging, commit, push, release or Computer Use occurred.

Owner listening, editing, engraving/clutter acceptance remains open. Full parity, off-grid strict IT,
unsupported formats/constructs and stateful voice reassignment are not claimed complete.
Next action: owner acceptance of the new study and editing; all three subagents are stopped and no work
resumes automatically. A later milestone should target remaining complex notation/format limits using
concrete refused examples, rather than claiming general round-trip or playback parity from these fixtures.

### Previous state: mixed tab library to finished band package (2026-10-23)

Owner screenshot follow-up (2026-10-23): section markers now reserve their own effect band,
so `Opening` clears the vibrato line. Full track names are horizontal in the editor and print.
Part sounds sits above the editor. Redraws detach selection/caret/playhead overlays before
alphaTab reuses SVG containers; switching tracks no longer stretches the caret or paints
the attribution footer over notes. These changes affect display only.
`scratch/tab-test-fixtures/score-text` holds matched headless before/after captures, the
isolated marker-band capture, print/PDF inspection, `regression.log`, and `tests.log`
(dense lyrics, print and note/playhead alignment passed; the new test's initial SVG-width
wait timed out and was replaced with the existing debounced-resize wait). `build.log` is the one
updated pinned build; `package-fixed.log` passes the 32-bar packaged score/live-WASM smoke
and selfcheck. `package.log` retains a harness failure: optional band edits assumed the
`--native-it` song argument; the helper now guards those edits. `delivery.log` verifies the
updated ZIP and final digests. Five unchanged generated PDFs were refreshed; counts remain
4 for the score and 2/1/1/1 for parts. Listening YAML/audio and rollback were preserved.
Current shortcut/package paths below still apply. No Computer Use or foreground evidence;
owner visual acceptance remains pending. No workers were resumed and no Git publication occurred.

Owner authorized one substantial batch with subagents, related fixes, focused checks and one final package.
No Computer Use, staging, commit, push or release. Three bounded lanes implemented imports, expression
and instruments; integration added delivery and owns the final qualification. Evidence:
`scratch/tab-test-fixtures/band-package`.

Implemented:
- Native PTB (`ptab-4`) and TEF2/TEF3 readers, shared checked binary normalization and existing fresh-output
  publisher. GUI, CLI and collection dispatch include them; native MIDI CLI dispatch now matches the GUI.
  Six generated-fixture checks cover counts, techniques/ties, exact dotted/tuplet timing, first-string bar
  boundaries, editing, exact history, reopening, TG reexport, malformed inputs and no overwrite.
  Three installed-TG comparisons match written notes/timing/voices/fingering/velocity/techniques/ties.
  Mixer normalization and unused channel removal are comparison-only, not a timbre/mixer parity claim.
- Existing technique controls now edit cross-measure selections through one transaction: note flags,
  harmonics, grace/repetition, curves, pick and strum strokes. Complete tie chains and voice scope remain
  guarded. Ghost/accent dynamics survive safe tied splits in preparation/rebar/paste; time-dependent
  unsafe splits still refuse. Four targeted installed-TG edits match; eight real-control edits cover
  exact Undo/Redo and retained selection.
- Part sounds binds an existing instrument/sample to a logical track, optionally replaces note overrides,
  and shares native playback/Pattern/strict IT/history. The existing SF2 preset importer now works in a
  native score. Assignment, audition, mute/solo, SF2 import and exact Undo have model/page coverage.
  Fixed the discovered startup race by publishing the worklet command port only after WASM is ready.
- Collection delivery adds PDF score/parts, WAV/FLAC/MP3/OGG, logical-part stems, remembered options and
  Band package output (collected project, TG/MIDI/IT, WAV mix/stems, PDFs). Successful formats survive a
  later refusal/cancellation; each result and delivery.json records its own outputs/losses/errors.
  PDF invokes installed Chromium/Edge/Chrome headlessly using the existing renderer, without a bundled
  automation dependency. Active cancellation terminates only that owned browser process tree; a focused
  Windows profile-handle race was reproduced and fixed with bounded cleanup retries.

The combined original study retains32bars/four tracks/664written notes/72ties/647attacks, adds opening
phrase expression and a synthetic SF2 Keys lead with explicit cut NNA. Its delivered score has4PDF pages;
the four individual parts have2/1/1/1pages. The new original PTB/TEF fixtures are separate32bar/two-track
examples (PTB/TEF3:320notes/two ties; TEF2:256notes). They are not full copies of the four-track study.

Source evidence: `integration-focused.log`18checks; `expression-focused-final.log`38checks;
`expression-page-controls.log`; `expression-tg.json`; `instruments-page-fixed.log`2actual-control cases;
`instruments-32bar.json`; `import-unit.log`; `import-oracle.json`; `IMPORT-BOUNDS.md`;
`delivery-model-complete.log`7checks; `delivery-page-first.log`PDF/audio/settings controls;
`delivery-pdf-portability.log`; `delivery-pdf-cancel-fixed.log`; `delivery-study.log`complete32bar output.
The earlier failure logs are retained, including SF2 voice-policy qualification, browser cancellation
cleanup, startup synchronization and package-harness selection/refresh races.

Final qualification:
- `build.log`:one pinned final build. All later fixes were in test synchronization/selection and CI registration;
  product code and executable were unchanged.
- `package-study-diagnostic.log`:passed actual part assignment/audition/mute/solo, saved delivery settings,
  PDF generation, packaged PTB/TEF2/TEF3 import/edit/exact Undo/Redo,32bar navigation/live WASM and strict IT.
  IT reopens647attacks over1692rows,88.091s, equal to source; technique render RMS/native ratio1.0053.
- `package-expression-verified.log`:eight actual technique controls with exact history, live WASM and
  source-equal standalone IT16attacks/192rows/7.998s. Initial package failures were ambiguous filename
  filtering and a helper proceeding before Undo's asynchronous score refresh. Expected-revision waits fix
  the helper. One buffered study run was stopped for diagnosis; the unbuffered run passed.
- `delivery-final.log`:ZIP contents verified, delivered IT equals qualified source, final exe/ZIP digests,
  and shortcut readback. `score-first-page.png` is a rendered artifact inspection, not foreground evidence.
- `ci-registration-fixed.log`:the test-registration guard passes. Added this batch and previously omitted
  native workflow modules to existing CI; mixed model/page modules run only where Chromium is installed.
  Removed imported TestCase discovery duplication in the rehearsal helper. No full local suite was run.

Current executable remains `scratch/tab-package-range-duration`; selected rollback
`scratch/tab-package-range-expression` is untouched. `Listen to current preview.lnk` now opens
`scratch/tab-package-range-duration/listening/band-package/song.yaml`. That folder contains the mix,
four stems, score/part PDFs, TG/MIDI/IT, ten mixed-library sources and README/format bounds. Mutable test
songs remain in `scratch/tab-test-fixtures/band-package`; `Try band editing.lnk` opens the study there.
Workers completed and stopped; do not resume automatically. The next action is owner acceptance.
Owner listening, engraving/clutter and editing-feel acceptance remains pending. No foreground check or
Computer Use was performed. Full parity remains open: PTB/TEF unsupported musical constructs refuse;
display losses are explicit (see IMPORT-BOUNDS.md); arbitrary rhythm/effect/channel splits, all-format
settings, FTP, external plugins/services and unrestricted interchange remain incomplete.

### Previous milestone: real-world tab editing and interchange (2026-10-23)

Owner authorized one substantial milestone with subagents, related fixes, focused checks and one final
package using the 32-bar study and imported variants. No staging, commit, push or release. Three bounded
workers completed workspace, arrangement and interchange lanes, then stopped. The workspace worker also
qualified the collection workflow. Integration owns the final package and stops after this milestone.

Changed behavior:
- Compact native TAB with a bounded inspector, optional saved panels, bar navigation and supported
  configurable score-action shortcuts. `a/b/g/t` open chord/bend/grace/text; transport/file/fret keys remain
  reserved and Pattern/text-field dispatch is preserved.
- Explicit Independent measures isolates reused occurrences for supported edits and paste. Prepare
  independent measures converts complete divided/reused patterns into exact one-bar orders, preserving
  tracker cells, headers, plain crossing ties and loop positions. Preparation plus edit is one Undo.
  Divided-bar Copy is read-only; Copy/Paste and duration controls have exact history coverage.
- Local score collection scan/filter/open and sequential batch conversion reuse existing importers,
  exporters and PROJECT collection. Each source gets a fresh output subfolder, individual warnings/errors,
  and preserved successful outputs. Existing destinations refuse. Cancel is checked between files and
  before export publication. Native YAML collection includes samples; external imports use placeholders.
- Native MIDI import is available through the shared GUI dispatcher. Fixed its SMF track-end calculation,
  which counted the four-byte length field incorrectly and rejected valid exported files. Explicit import
  destinations must be fresh for both native and legacy dispatch.

Evidence: `scratch/tab-test-fixtures/real-world`.
- `arrangement-model-state-final.log`: five focused cases. `arrangement-regressions-final.log`:25 cases.
  `arrangement-page-copy.log`: Prepare, divided Copy bar2/Paste bar4, Shorter and exact Undo/Redo.
  `arrangement-unison-corrected.log`: existing keyboard case passes after its coincident second voice is
  routed to unused existing channel4, retaining same-string hit testing. Original failure was the valid
  strict-IT overlapping-channel refusal; no compiler guard was weakened.
- `workspace-final.log`: saved panels, bounded inspector, navigation, remapping/collision and context checks.
  `collection-model-first.log`:three backend cases; `collection-page-first.log`:two actual-control cases.
- `interchange-unit-final.log`:eight focused cases; `interchange-freshness-final.log`:fresh-output recheck.
  `interchange-page-final.log`: TG/GP5/MIDI note edits with exact Undo/Redo and save/reopen coverage.
- `study-tg-presets.log` and `study-tg-results.json`:nine installed-TG reads/reexports match notes, timing,
  velocity and tempo. Installed MIDI import also matches tuning/program choices when using its stock
  tuning catalog. `arrangement-tg.log/json`:two meter/tie cases match; mixed-rhythm result cannot compare
  because the TG output contains an orphan tie refused by import.
- `foreground-first.log` stopped because another app held focus. `foreground-final.log` and
  `workspace-score.png`, `workspace-inspector.png`, `collection.png` capture the loaded foreground score,
  bounded inspector and seven-file collection at1600x1000, without source changes or page errors. Owner
  then instructed **do not use Computer Use**; it stopped and no further desktop control is authorized.

Imported TG/GP5 preserve32bars/four tracks/664written notes/72ties/647attacks. MIDI reconstructs the
performed sequence as35bars/six tracks/716written notes with647attacks. GP3/4 are explicitly arranged
single-voice variants (617notes/612attacks), not silent reductions of the full study. GP6/7 retain the
small complex fixture; unsupported pickup export/off-grid-grace strict IT refuse. The established GPX
center-pan63 versus TG64 difference remains. Preparation requires complete contiguous exact-row measures
and refuses unsafe technique splits, tracker flow/automation, nonliteral or approved source material.
Individual note-property edits retain existing shared-pattern scope; the checkbox covers its named phrase
and measure commands. PDF/audio batch conversion, all-format settings, FTP/plugins and full parity remain open.

Final qualification and delivery:
- `build.log`:one final build in `scratch/tab-package-range-duration` using the pinned environment.
  No product changes or rebuild were needed after packaging; subsequent repairs were in the test harness.
- `package-study-verified.log`:passed compact workspace/preferences/shortcut checks, actual collection
  conversions/opening, note edits on five TG/GP5/MIDI/GP3/GP4 variants with exact history, live WASM,
 32-bar traversal and strict standalone IT. The IT has647attacks over1692rows,88.091seconds, equal to the
  source build; the native rendered ending is88.12501seconds against88.125 written.
- `package-arrangement-final.log`:passed Prepare/divided-bar Copy/Paste/Shorter and exact history;
  preparing the reused pattern resolves its occurrence-dependent final-release refusal. The prepared IT
  has6attacks over192rows,7.998seconds, source-equal; one Undo restores the original divided/reused song.
- Retained failures: `package-study.log` caught the scan test matching a status GET instead of its POST;
  `package-study-final.log` caught a stale test view after reopening a song. The harness now waits for the
  document identity. `package-study-complete.log` caught in-flight old-song UI reports: the server correctly
  refuses them, and the harness now requires a successful current-song report before accepting only that
  exact ownership refusal. No server guard changed. `package-arrangement.log` and diagnostic/export logs
  expose the actual unprepared shared-pattern IT boundary refusal; the final check exercises its explicit
  Prepare remedy rather than weakening strict export. `exe_check.py` now reports immediate export refusal
  and tracebacks instead of waiting for a job that was never started.
- `delivery.log`:new `listening/real-world.yaml`, samples, byte-equal qualified `real-world.it`, seven
  original interchange inputs in `listening/real-world-imports`, and concise format notes are included in
  the current ZIP. Archive contents checked; final exe/ZIP digests recorded only there. The root
  `Listen to current preview.lnk` opens the study. Separate `Try imported tabs.lnk` and
  `Try independent measures.lnk` live under `scratch/tab-test-fixtures/real-world`.

Rollback `scratch/tab-package-range-expression` and prior owner listening songs remain untouched.
Dedicated new test modules are focused local coverage and are not yet in the enumerated CI list; no full
local baseline was run. The index remains empty. No staging, commit, push, release, cleanup or memory edit.
The batch is complete and all workers are stopped. No automatic next milestone. Owner listening, engraving
preference and editing-feel acceptance remain pending; automated/foreground evidence does not replace them.

### Previous milestone: blank score to rehearsal-ready arrangement (2026-10-23)

Owner authorized the complete milestone with subagents, related fixes, focused checks and one final package
using the existing 32-bar four-track example. No staging, commit, push or release. Three bounded workers
completed setup, phrase editing, rehearsal and their focused checks, then stopped. The setup worker also
completed the integration sounding-state repair and stopped again. No automatic next milestone.

New Song offers native guitar, bass, drums and band templates, plus saved custom setup templates. Templates
retain setup/credits without notes, samples or channel ownership. Track add/clone allocates independent free
tracker channels; reorder changes logical score order; removal preserves unrelated raw tracker data/assets.
Custom tunings persist in the local profile. Song properties save full credits independently of the short IT
module title. TG and GP preserve supported fields, with explicit GP date loss. Print defaults use the saved
credits, identify parts and number pages. An SVG/PNG export bug that assigned the music font to ordinary
header text was reproduced and fixed in the shared exporter.

Mix paste combines compatible rhythm/chords; Push makes space in the affected track/voice lanes. Move/Copy
voice use the same atomic score/history path. Invalid string collisions, unsafe technique splits, raw conflicts
and unrepresentable timing refuse without partial edits. These are native conveniences; TG's replace-paste
behavior is not described as an equivalent Mix/Push command. The visible voice selector now follows a completed
voice transfer. Logical track reorder now participates in State's no-op detection.

Rehearse selection opens authored bar limits, one-bar count-in, meter-aware metronome, logical-track solo/mute
and stepped practice speed (80% to 100% by default). It loops the first reachable contiguous performed visit,
including repeat traversal, and identifies that visit. Unreachable contiguous ranges refuse. Playback speed,
practice masks and count-in leave written tempo/notes unchanged. Pause/resume and cancellation during engine
preparation are covered. A mixer change at the final loop quantum no longer loses the next practice speed.

Evidence: `scratch/tab-test-fixtures/rehearsal-ready`.
- `setup-model.log`, `setup-state-final.log`, `setup-page-final.log`:6 setup/creation cases, State exact history,
  real track/tuning controls and persistent tuning reload. `setup-tg-independent.log/json`:three TG comparisons;
  two explicitly allocate independent reference channels. Raw TG clone shares its MIDI channel, which native
  import refuses (`setup-tg.log/json`); native cloning deliberately allocates independent channels.
- `phrase-model-state-final.log`:11 focused model/State cases; `phrase-regressions.log`:27 prior cases;
  `phrase-page-final.log`:actual Mix/Push/Move/Copy controls, refusal/recovery and exact Undo/Redo.
  `phrase-semantics.md` records pinned TG source and the deliberate native convenience scope.
- `blank-arrangement-final.log`:actual New Song band setup, mapped 32-bar paste, headers/markers,664 written
  notes, performed musical equivalence, exact Undo/Redo/save/reopen and unchanged source. The initial log
  retains a harness-only repeat-projection misuse; the final helper uses the performed repeat projection.
- `rehearsal-engine-final.log`:four engine checks, exact count-in frames/meter clicks, practice ramps and tied
  loop PCM difference zero at80/90/100%. `rehearsal-page-final.log`:actual rehearsal controls, solo/mute,
  pause/resume, count-in and pending-load cancellation without song/history changes.
- `credits-state-final.log`:three metadata/whole-song history checks. `interchange-regressions-final.log`:35
  TG/GP/notation checks; `notation-credits-final.log`:quoted/grouped header guard. Initial import expectations
  and three bass-clef notation goldens were refreshed only after targeted TG confirmation. MusicXML additionally
  preserves writer as lyricist; TG omits it. LilyPond credits matched TG. No full local suite was run; the new
  dedicated rehearsal modules are explicit focused checks and are not yet added to the enumerated CI suite.
- `delivery-page-final.log`:actual properties/custom New Song setup and PDF/SVG/PNG export. Initial diagnostic
  output reproduced unreadable ordinary SVG header text (ink overlap0.722); final output passes and was inspected.
- `prepare.log`:the existing original study with saved credits,32 written bars,664 notes,647 performed attacks,
  zero measure errors and strict IT. Generated drum ring/key advisories remain. TG/GP report sample/envelope
  limitations; they do not embed the synthesized sound set.
- Initial package qualification: `package-phrases.log` counted the deliberately asserted collision refusal as
  an error; the harness now exempts exactly that response and reads failed-response bodies outside callbacks
  to avoid Playwright re-entry. `package-phrases-final.log` and `package-setup.log` pass actual controls, exact
  history, native playback, source-equal standalone IT and selfcheck. `package-example.log` exposed a harness
  wait for the optional collapsed grid; attached DOM readiness fixes it. `package-example-final.log` passes
  blank32-bar authoring, rehearsal, print and IT checks but catches a real ambiguous `/api/sounding/0` request
  during the combined workflow. `sounding-refresh-first.log` reproduces a request using the blank revision
  while the paste is in flight. The shared panel now waits for the edit and State refresh, and keys cached rows
  by song path/revision. `sounding-refresh-fixed.log` passes the identical reproduction without HTTP failures.
  `sounding-refresh-regression.log`:one permanent page case forces both asynchronous handoffs and verifies a
  fresh pass-qualified request succeeds. Final package qualification follows this shared-state repair.
- `build-final.log` replaces the same current executable after that integration fix; one final delivery is
  retained. `package-example-qualified.log` passes the combined blank-to32-bar arrangement, exact history,
  rehearsal80-to85%, count-in/cancellation, PDF/SVG/PNG, live WASM and source-equal647-attack standalone IT
  reopened without a plan. No HTTP/page failures remain. Native rendered end88.12501s versus written88.12500s.
- `package-phrases-qualified.log` and `package-setup-qualified.log` pass on that same final executable:
  real controls, exact history, live playback, standalone source-equal IT and selfcheck. `delivery.log` records
  archive integrity, final EXE/ZIP hashes, included study/samples/parts and shortcut target readback.

Packaged PDF output was inspected:8-page full score and2-page lead part, readable credits/tuning, intact closing
ties,5/4 bridge and page footers. Static PDF inspection does not replace the pending foreground app check.

Current package remains `scratch/tab-package-range-duration`; rollback remains
`scratch/tab-package-range-expression`, untouched. New study: `listening/rehearsal-ready.yaml`; separate fixtures
are under the evidence folder. Owner-edited listening songs are preserved. `Listen to current preview.lnk`
opens the32-bar study; `scratch/tab-test-fixtures/rehearsal-ready/Try rehearsal authoring.lnk` opens the separate
four-bar setup seed. The listening folder and final ZIP contain `rehearsal-ready.pdf`, the lead-guitar PDF,
page2SVG/PNG, native YAML, TG/GP5/IT and six generated samples. Rollback was not touched. Index remains empty;
no staging, commits, pushes, release or automatic continuation. All workers stopped.

Owner granted foreground time. A successful game-leased capture at10:20:32 produced `song-score.png`,
`rehearsal-controls.png` and `song-print.png`, with verified foreground title/document focus, no page errors
and unchanged song bytes. The rehearsal controls and credited four-page landscape print were inspected.
The editor capture has the inspector expanded, leaving most notation below the fold; the print capture
shows the four-part notation, credits and page footer clearly. Earlier capture-harness readiness/title
failures and later optional tighter-editor attempts are retained in `foreground*.log`; the later attempts
failed the foreground check and did not replace the successful images. The successful run's original log
path was reused by a later attempt; its exit0 and completion output remain in the conversation tool record.
Test windows closed and lease released. No product/package changes were needed. The batch is complete;
owner listening, visual preference and editing-feel acceptance remain pending. No automatic next work.

### Previous delivery: complete-song authoring and delivery (2026-10-23)

Owner authorized the whole milestone with subagents, related fixes, focused checks, one final package and
an original 32-bar four-track example. No staging, commit, push or release. Three bounded workers completed
their work and stopped. Integration completed one final package; no automatic next milestone.

Portable phrases retain tuning metadata, adapt fingerings to destination tuning/capo and use destination
instruments/channels across tracks or songs. Both voices and internal ties survive; impossible mappings and
pitched/percussion mismatches refuse atomically. The clipboard survives opening another song in the same window.
Portable measure copies map score parts to destination tracks, with independent header and marker options;
raw tracker cells are excluded. Header replacement requires coverage of the whole destination arrangement.
Make passage unique clones reused occurrences in one Undo. Move beats accepts exact fractional quarter units.
Print preview selects tracks/bar ranges and exports PDF, self-contained page SVG or 2x PNG. Excerpts identify
source bars and number from 1. GP import/export now preserves TuxGuitar's tuning-inferred bass clef.

The local HTTP accept queue was only five requests. A controlled 24-request burst reproduced 19 timeouts;
the enlarged queue accepts all24. This proves that queue limit, not every earlier intermittent fetch failure.
Real page/package results below qualify current behavior. Mix/push paste, unsupported technique splits,
raw conflicts, full engraving/style parity and JPEG/BMP remain outside this completed feature scope.

Evidence: `scratch/tab-test-fixtures/complete-song`.
- `clipboard-edges.log`:27 focused checks; `clipboard-final-guards.log`:11 final model/State checks;
  `clipboard-state-final.log`:2 closed-source transfer/history cases; `clipboard-page-first.log`:actual
  cross-track/cross-song controls and exact restoration. `clipboard-allocate-tg.log/json`:three TG matches.
- `structure-final.log`:27 checks; `structure-model-final.log`:7 new model cases;
  `arrangement-page-final.log`:32-bar/four-track composition controls and exact Undo/Redo;
  `arrangement-page-second.log`:occurrence uniquing. `structure-tg-first.log/json` and
  `structure-tg-meter.log/json`:targeted TG marker/header/meter cases. Native custom1/3 movement preserves
  the exact requested offset; TG rest repacking differs and is explicitly not claimed as a direct match.
- `server-first.log`:3 focused queue/export guards. `print-native-final.log`:4 real-control export cases,
  including native save handling, offline font, 2x PNG and PDF pagination. Earlier print failure retained:
  alphaTab's start-bar path failed on crossing ties; bounded excerpt projection now avoids it.
- `gp-clef-final.log`, `gp-clef-guard.log`, `gp-clef-tg.log`:8 focused checks and installed TG reads of six
  GP3/4/5 files verify tuning-derived bass/treble clefs independently of instrument program.
- `song-delivery-final.log`:16 transaction32-bar/four-track session, exact Undo/Redo, TG/GP5 timing/pitch/
  velocity/tie/meter/endings roundtrips and strict IT. `prepare-qualified.log`:generated delivery has664
  written notes,647 performed attacks and zero measure errors. IT sample-ring/key advisories remain for
  generated drums; TG/GP cannot embed these synthesized samples/envelopes and report their normal losses.
- `foreground-final.log`, `song-score.png`, `song-print.png`:loaded focused32-bar score and four-track
  landscape print (four pages), no page errors or song mutation. Owner listening/editing acceptance pending.
- `build.log`:one final build updated the current package in place. `package-arrangement.log` and
  `package-portable.log`:actual packaged32-bar arrangement and cross-song transfer controls pass, with exact
  restoration, playback, standalone IT and selfcheck. `package-example.log`:32written bars,647 performed
  attacks,1294 native events, rendered ending88.12501s versus88.12500s written, source-equal standalone IT
  reopened without a plan, live WASM and selfcheck. All three runs pass without logged fetch/page failures.
- Packaged print exports:8-page portrait full score,2-page lead part, page2SVG/PNG, embedded licensed font,
  offline rendering and raster ink checks. PDF pages inspected after rendering; a suspected missing title
  was an inspection false alarm, confirmed by PDF text bounds and enlarged image crop. `delivery.log`:
  exported files and six generated samples included in the final ZIP, archive integrity checked, final
  distribution hashes. `shortcuts.log`:current listening and separate authoring links read back correctly.

Current delivery remains `scratch/tab-package-range-duration`; rollback remains
`scratch/tab-package-range-expression`. New listening song: `listening/complete-song.yaml`, title
`Four tracks - whole song`:lead guitar, Drop D guitar, bass and drums, repeat endings, two voices/ties,
5/4 bridge and transposed closing passage. Separate editing/portable fixtures remain under the evidence
folder. Owner-edited songs are preserved. `Listen to current preview.lnk` opens the new study;
`scratch/tab-test-fixtures/complete-song/Try song authoring.lnk` opens the separate four-bar seed.
The listening folder also contains `complete-song.pdf`, `complete-song-lead-guitar.pdf`, TG/GP5/IT and
page2SVG/PNG. The final ZIP includes this study and its samples. Owner listening/editing acceptance remains
pending. Workers stopped; no automatic work, staging, commits, pushes or release. Index remains empty.

### Previous delivery: complete-section composition and arrangement (2026-10-23)

Owner authorized one substantial milestone with subagents, related fixes, focused checks, one final package
and an original 16-bar example. No staging, commit, push or release. Three bounded workers completed model,
page and pinned-TG work and stopped; integration completed one final package. No automatic next milestone.

Phrase Rest/Delete/Clean now work across measures; Copy omits external links and Cut repairs incident ties.
Paste/Repeat add compatible whole-order bars and split crossing plain notes into ties. Replacement preserves
exterior destination fragments and other voices. Pasted phrases stay selected for immediate Copy or editing.
The Measures panel moves From/To before a numbered destination (last+1 appends), retaining source occurrence
IDs and headers. Structural edits repair invalid boundary links. Meter changes and Move beats split crossing
plain notes; Move right can grow the song. Strict standalone IT validation precedes each saved transaction.
Shared/approved patterns, raw conflicts, incompatible grids and unsupported technique splits still refuse.
Pitch/expression requires complete ties. Mix/push paste remains open; custom Move was added in the next milestone.

The integrated control session found and fixed a real guard bug: retained cross-measure selections blocked
explicit measure commands. The returned paste selection also now reaches the shared endpoint and page.
The16-bar session repeats a4-bar two-voice phrase, moves its last passage, varies pitch/rhythm/velocity,
rebars measure2 to5/4, and inserts/removes middle bars. Exact Undo/Redo/reopen is checked. The listening study
adds written closing rests to both voices, yielding zero measure errors and unchanged sounding events.

Evidence: `scratch/tab-test-fixtures/complete-section`.
- `model-clipboard.log`:29 focused checks; `structure-final.log`:20 model/State checks.
- `range-regressions-first.log`:11 cross-range cases; `legacy-clipboard-first.log`:3 strict clipboard cases.
- `session-state-final.log`:16-bar session and phrase mutation checks; `paste-selection-final.log`:6 paste,
  previous clipboard and request-logging checks. Earlier State logs retain corrected test assumptions about
  simultaneous event order and selected transpose scope, not relaxed timing assertions.
- `page-progress.log`:real-control16-bar session, repeated selection edits, boundary Copy/Paste, Rest/Delete/
  Clean, Move-right overflow, exact Undo/Redo and no page errors. `page-first.log` retains the measure guard bug.
- `tg-final.log/json`:14 qualified cases:9 direct operation-sequence matches,5 explicitly labelled native-
  preservation/reference workflows. Raw TG loses exterior fragments/truncates extension or alters peer-rest
  timing in those cases. Exploratory raw Move-right timing and mixed-meter invalid TG ties remain unqualified.
- `prepare.log`:original16-bar study,74 native attacks, strict standalone IT without warnings.
  `example-finish-final.log`:closing rests, zero measure errors, sounding events unchanged. The initial
  finish log retains a corrected harness lookup of a nonexistent State attribute.
- `foreground.log`, `section-score.png`, `section-selection.png`:loaded foreground score and24-beat selected
  phrase, no page errors/source mutation. Captures precede final closing rests. `foreground-final.log` records
  focus switching to Firefox on the follow-up; it is not another qualified visual result.
- `build.log`:one final build updated the current delivery in place. `package-edit.log` completed the edit
  assertions but failed on one unhandled `Failed to fetch` page error. Stack/request-path diagnostics were
  added; the unchanged package passed the full session in `package-edit-diagnostic.log`, including cross-range
  Delete note, source-equal export/reopen, live WASM,18 standalone attacks over192rows/10.667s and selfcheck.
  That rerun records two WAV connection refusals without page errors. The intermittent local request failure
  is retained as an unresolved observation; no speculative networking fix or second build was made.
- `package-example.log`:final 16-bar study passes rendered SONG, live WASM, native/standalone IT export and
  source-equal reopen plus selfcheck. `shortcuts.log`:both shortcuts read back the final executable/song paths.

Current delivery remains `scratch/tab-package-range-duration`; rollback remains
`scratch/tab-package-range-expression`. New listening song: `listening/complete-section.yaml` (16bars,
two voices, tied replies,5/4 rebar and a varied final phrase). Separate editing fixture:
`scratch/tab-test-fixtures/complete-section/editing/song.yaml`. Owner-edited songs are preserved.
`Listen to current preview.lnk` opens the study. `scratch/tab-test-fixtures/complete-section/Try section
editing.lnk` opens the separate four-bar seed for composing a section. Owner listening/editing acceptance
remains pending. Workers are stopped; nothing resumes automatically. Index remains empty; no Git publication.

### Previous delivery: everyday rhythm-editing milestone (2026-10-23)

Owner authorized the milestone as one batch with subagents, related fixes, focused checks and one final
package; no staging, commit, push or release. Three bounded workers completed model, State/page and pinned
TG comparisons. Integration completed final packaging; all workers stopped. No automatic next milestone.

Longer/Shorter, explicit durations, dots and tuplets now share the duration transaction for existing beats.
Selected bare rests can be consumed; a rest consumed/rebuilt by an earlier target is skipped for that command.
The resulting selected phrase includes generated rests, so repeated edits, Copy and expression need no fresh
selection. Single carets stay single. Ordinary no-space/bar-end attempts retain that beat's duration and
report it while valid targets proceed in one Undo. Fit uses partial explicit rests and implicit gaps through
the existing TG rebuild path, retaining peer voices. No new bars, silent timing rounding or automatic regrid.
Protected notation, raw tracker conflicts, unsafe movement and nonrepresentable IT timing refuse atomically.
Tied editing from the previous batch remains supported. Full cross-range tie-boundary selection and all
free-edit/overflow behavior are not claimed by this milestone.

The continuous page session exposed a refresh race: returned selection was correct but shading disappeared
after Shorter when engraving reused an unchanged render. Explicit selection repaint fixes the responsible
layer. Read-only review also found local selection incorrectly including peer-voice rests; corrected with a
regression. Duration logs now summarize retained beat reasons, absorbed-rest and removed-tie counts, bounded
to32 detailed retained targets, alongside the existing song/control/Fit/selection context.

Evidence: `scratch/tab-test-fixtures/rhythm-editing`.
- `model-with-gaps.log`:58 focused model checks pass, including8 everyday methods. Earlier model logs retain
  stale expectations and a corrected test-variable error.
- `state-final.log`:3 methods cover both Fit modes, repeated selection/Copy/expression edits, exact
  Undo/Redo/reopen, native and standalone timing, implicit partial Fit with a peer voice and late raw collision.
  `state-regressions.log`/`state-noop.log` retain passing previous cases and one corrected test selector.
- `page-final.log`:complete real-control sequence passes, including generalized Fit/implicit gap and no-room
  control restoration. `page-regressions.log`:prior boundary/tied controls pass. Earlier page logs retain the
  actual shading failure and corrected highlight expectations now that generated rests remain selected.
- `logging.log`:4 focused logging checks pass, including bounds/redaction and unchanged-duration outcome.
- `tg-expanded.log/json`:11 direct TG2.1.0 comparisons,2 explicitly normalized live-target comparisons and1
  intentional atomic IT-timing refusal. Raw TG reuses detached selected-rest objects, moving later notes or
  underfilling the bar; native skips those stale targets. Raw outcomes/differences remain in the evidence.
  `tg-implicit.log/json`:5 more comparisons pass using equivalent explicit TG silence for native gaps;
  no-room fallback preserves the entire native source. Explicit-rest spelling differences are recorded.
- `prepare.log`:original two-bar eighth-note phrase and its flowing quarter-note reply,8 selected rests
  consumed,8 reply notes retained, strict standalone IT compilation without warnings.
- `foreground-confirmed.log`, `rhythm-before.png`, `rhythm-longer.png`, `rhythm-shorter.png`:loaded foreground
  score, same1600x1000 viewport/scroll,17 selected beats ->9 ->17 with exact Undo and no page errors.
  Earlier foreground logs retain focus failures and a hidden Copy-button harness mistake; the separate
  page session checks Copy, and the final capture used the owner's confirmed foreground slot.
- `build.log`:one final build updated the current package in place. First packaged attempts exposed test
  setup differences:collapsed inspector hid Copy; later, stale pre-Undo engraving reached a coordinate click
  before the new revision finished rendering. Their logs remain `package-edit.log` and
  `package-edit-qualified.log`; the shared helper now waits for the original score revision and its completed
  rendering after Undo before clicking coordinates. `package-edit-final.log`:all rhythm controls/history,
  live WASM, native/standalone16 attacks over192rows/10.667s, source-equal export/reopen and selfcheck pass.
- `package-example.log`:musical example rendered SONG/live WASM and standalone16 attacks over192rows,
  source-equal export/reopen and selfcheck pass. This is measured playback, not owner listening acceptance.
- `shortcuts.log`:root preview and separate editing shortcut point to the final executable and correct songs.

One final package updated the existing `scratch/tab-package-range-duration`; rollback remains
`scratch/tab-package-range-expression`. Listening example: `listening/rhythm-editing.yaml`; disposable
editing fixture: `scratch/tab-test-fixtures/rhythm-editing/editing/song.yaml`. Existing owner-edited songs
are preserved. `Listen to current preview.lnk` opens the original short phrase and flowing reply;
`scratch/tab-test-fixtures/rhythm-editing/Try rhythm editing.lnk` opens the separate test song. The test song
deliberately has an underfilled peer voice and implicit gap for preservation checks; the musical example
compiles without warnings. No extra delivery or cleanup. Index remains empty. Owner listening/editing
acceptance remains pending; stop here and do not begin another milestone automatically.

### Previous state: tied-note duration editing delivered (2026-10-23)

Owner authorized this bounded batch, focused checks, one final package and a musical example; no stage,
commit, push or release. Three bounded Codex workers finished and stopped. No automatic continuation.

Place and duration Fit now resize tied beats, locally and across selected measures. Adjacent ties remain
connected; qualified Fit moves both ends before checking them. A link made nonadjacent by shortening or
movement is removed, and the status reports it so the following note plays normally. Original selection,
other voices and one exact Undo are retained. Deliberate TG difference: its raw duration action leaves
invalid tie flags until the separate Fix tied note action; native performs that repair immediately.
All single-note and range duration edits now compile standalone IT before persistence. This closes the
discovered direct-Place gap that accepted a64th between IT ticks. No rounding, regridding or automatic bars.
Unsafe Fit/overflow, raw conflicts, approved/shared-range patterns and combined note insertion plus tied
resizing retain their guards. ROLL tied resizing and unrelated individual-note mutations are not expanded.

Evidence: `scratch/tab-test-fixtures/tied-duration`.
- `model-pass.log`:50 focused checks, including7 new tied-duration cases, pass. Earlier model logs retain
  a mistyped test selector and outdated tied-refusal expectations, corrected for the new supported behavior.
- `tg-final.log/json`:10 installed TG2.1.0 comparisons match (9 edits,1 unchanged overflow), including
  head/middle/continuation edits, Fit movement, cross-bar ties, dots and tuplets. Three cases explicitly
  repair and assert1 invalid TG flag; sounding timing and ties match, with documented explicit-rest differences.
- `state-final.log`:2 methods cover14 duration/Fit combinations plus same-bar tied-chain movement.
  Native/standalone attack counts and exact releases,44.1/48k gate windows, peers/raw cells, Undo/Redo/reopen
  and atomic sub-tick refusal pass. `state-regressions-final.log`:3 existing Place/Fit/history checks pass.
  `state-regressions.log` retains a passed previous boundary repair plus3 wrongly qualified test selectors.
- `page-final.log`: real Longer/Shorter/dots/tuplets, Fit off/on, removed-tie status, selected caret/range and
  exact Undo pass. Earlier logs retain missing default-browser setup and a corrected test assumption that
  a single caret should have range shading.
- `foreground-qualified.log`, `tied-before.png`, `tied-after.png`: loaded foreground Edge score, same viewport,
  quarter-to-half continuation with visible cross-bar tie and exact Undo. Earlier capture logs retain a
  renderer-readiness race and a console-only Unicode title-print failure; both harness issues were corrected.
- `build.log`:one final package, updating `scratch/tab-package-range-duration` in place.
  `package-edit.log`:packaged real controls/history, live WASM, export/reopen15 attacks/192rows, selfcheck pass.
  `package-example.log`:musical example live/rendered and standalone12 attacks/192rows/10.667s pass; rendered
  envelope release ends at10.8898s. No claim of listening acceptance or bit-identical native/IT audio.

Current delivery remains `scratch/tab-package-range-duration`; rollback stays
`scratch/tab-package-range-expression`. `Listen to current preview.lnk` now opens
`listening/tied-duration.yaml`: an original two-bar phrase followed by its longer tied reply, using a separate
soft sustained tone so duration differences remain audible. Existing owner-edited listening YAML and samples
are untouched. `scratch/tab-test-fixtures/tied-duration/Try tied duration editing.lnk` opens the separate test
song (its deliberately short lower voice exercises preservation). `shortcuts.log` records exact target readback.
No extra binary delivery or cleanup was made. Index remains empty. Owner listening/editing acceptance of
this batch is next; do not start another batch automatically.

### Previous state: logged duration refusals repaired (2026-10-23)

Owner reproduced six refused attempts in the diagnostic preview and requested a fix. The logged selection was
bar3's final sixteenth rest `rest_copy_visit0_beat3` plus bar4's first sixteenth note `copy_visit1_beat0`.
Shorter32 failed a whole-row projection check; Longer8 failed when the selected rest crossed the bar end,
both with Fit off/on. These are confirmed log-derived cases, replacing the earlier tentative diagnosis below.

`project_score` now admits exact integer-tick note endpoints between rows using its existing delayed
attack/keyoff path; rests do not emit IT cells and no longer require row alignment. Exact source timing drives
tie adjacency and overlap checks; row coverage remains conservative for raw-cell protection. No regridding,
tempo/speed changes or rounding. A cross-range bare rest that cannot grow beyond its bar retains its duration
as in TG while other selected beats change in the same Undo transaction. The status reports retained rests.
Annotated rests, tied resizing, consumed selected rests, unsafe Fit and raw-cell conflicts still refuse.
Sounding endpoints between IT ticks (e.g. a64th at this speed) remain unsupported, rather than rounded.

Checks under `scratch/tab-test-fixtures/range-duration`:
- `logged-refusal-replay.log`: all six exact logged requests succeeded on a disposable copy, each with
  standalone compile and byte-exact Undo. The owner's listening YAML remained untouched.
- `tg-boundary-fix.log/json`: three actual TG2.1.0 matches, including explicit selected-rest spelling for
  Longer Fit off/on and Shorter. Shorter has three other explicit-rest representation differences.
- `repair-focused-final.log`:16 focused projection/range/State cases pass. Native and standalone IT gate
  windows agree at44.1/48k; the32nd release is row1 SD1 at speed2, with all four patterns still48 rows.
  Undo/Redo/reopen, unrelated raw commands and atomic unsupported-tick/raw-collision checks pass. Worker also
  ran166 focused existing/new projection and performed-technique checks successfully.
- `repair-page-qualified.log`: real Shorter/Longer controls, Fit off/on, two retained highlights, kept-rest
  status and exact Undo pass. `repair-page.log` caught an early assertion before engraving finished; the
  helper now waits for rendering. `repair-page-final.log`/`repair-page-retry.log` preserve an overlong test-title
  setup failure; the corrected25-character title is used by the final fixture. Existing duration page case passed.
- `repair-build.log`: one final build updated the existing `scratch/tab-package-range-duration`.
  `repair-package.log`: the same repaired controls/Undo, SONG ending/live WASM, standalone IT export/reopen
  (16 attacks,192 rows,10.667s) and packaged selfcheck pass. Test song: `boundary-repair/song.yaml`.

Current/rollback remain range-duration/range-expression; shortcuts are unchanged and the owner's edited
listening song is preserved. Prior sound acceptance stands. On 2026-10-23 the owner confirmed the repaired
edits work ("Those edits work now"); acceptance of these reported duration failures is closed. Other documented
duration limits and full TuxGuitar parity remain open.
Three bounded workers finished and stopped. Index remains empty; no commit/push/release or cleanup attempted.

### Previous batch: cross-measure duration editing (2026-10-22)

Owner accepted range-expression and authorized this one-worker batch. Duration, Longer/Shorter, dots and
tuplets now apply to the selected voice through existing Place/tg_duration Fit, in chronological order. The
caret-chosen spelling applies to each originally selected beat; this is not stretch-all timing. +/- clear dots
and retain tuplets. Full qualified selection and other voice/track records survive refresh; each actual change
is one exact Undo and repeated Apply is a no-op. Clipboard remains unchanged. Generated bare rests are not
automatically selected duration targets; only duration qualification allows omitted bare rests. Other range
commands may need a fresh full selection after shortening. No saved selection metadata or parallel interpreter.

Fit can move following plain notes within existing measures (positive cross-range movement covered). Absorbing
an explicitly selected rest, changing an earlier requested result/peer, insufficient room, annotated rest/cohort,
unsafe technique movement, shared/approved patterns or strict IT conflicts refuses the entire candidate.
Existing tied-note resize refusal remains; same-duration spelling can preserve ties. Untouched other-voice
boundary ties do not block this voice's duration edit. No rebarring, added bars or silent rounding.

Evidence under `scratch/tab-test-fixtures/range-duration`:
- `model-initial.log`:5 passes and a no-op ordering failure. `model-noop-final.log` fixes that failure by skipping
  unchanged cross-range targets before Place can reorder them; local behavior unchanged. `fit-final.log`:positive
  cross-range Fit shifts a following note from1 to2, retains selected IDs, supports3/4 bounds and refuses overflow.
  Seven distinct model cases qualified including four existing local-range cases, both voices, spelling/ties,
  original-ID retention, selected-rest absorption and shared/approved/late raw guards.
- `state-late-final.log`:exact Undo/Redo/reopen/no-op, unchanged raw/other patterns and late residual collision
  rollback. Standalone IT reopened without a native plan matches attacks at rows0/12/24/36 and keyoffs6/18/30/42;
  native gates are1/2quarter, untouched lower voice1quarter. Independent settled on/off energy windows at44.1/48k
  agree within6%; this does not claim instantaneous waveform parity or physical listening. `state-initial.log`
  retains the test's wrong PCM decoder type; corrected to requesting float frames in `state-final.log`.
- `page-initial.log`:2 passes, new actual Shorter->same Apply->Longer, dots/tuplets, retained9 highlights including
  untouched voice, exact Undo/Fit refusal, plus existing local selected-duration keys regression.
- `TGDurationActions.txt`:pinned TG2.1.0 SetDuration iterates selected beats with cloned caret duration/voice;
  increment/decrement clear dots. `tg.log/json`:2 sounding-note/timing matches, explicitly8/30 rest differences.
  Native keeps the peer voice's authored rest records; this is not full rest-engraving parity.
- `capture-before.log`/`capture-after.log`:same1920x1080 loaded visible foreground, errors[].
  `duration-before-controls.png`/`duration-after-applied-controls.png`, matching `*-response.png` and
  `duration-after-score.png` show readable voice scope, dotted-eighth response and all8 original highlights.

Candidate `scratch/tab-package-range-duration`; listening contains `four-bars-range-duration.yaml`, `.it` and
accepted `soft-c.wav`. Familiar first two bars retain the phrase; the transposed/alternate-fingering response
uses dotted eighths at its original quarter-note onsets.90BPM/tempo-unit markings and full lyric phrase retained.
Editing fixture: `scratch/tab-test-fixtures/range-duration/song/song.yaml`; `prepare.log` passed. Product changes
are `tablature.py`, `gui.py`, `web/tablature.js`; existing tests/oracle/exe runner extended. Small pre-round copies
and `product-change.diff` retained. Parent reviewed source/foreground evidence with no outstanding findings.
`build.log`:single build passed. `check-package-edit.log`:bundled selected-voice Shorter/no-op/Longer/dots,
retained range and exact Undo passed. `check-package-song.log`:actual standalone IT export/reopen without a
native plan,16 attacks over192 rows/10.667s, equals the source build. Both logs pass actual rendered SONG ending,
live WASM, TAB navigation and packaged selfcheck. Scoped whitespace check passed; index remains empty.
Owner accepted the listening example on 2026-10-23 ("Sounds good") but reported that most edits refuse;
the supplied screenshot says "place interval or affected rest crosses a pattern boundary". Editing acceptance
remains open pending diagnosis of that workflow. Parent explicitly stopped the sole Codex worker after handback.
Current delivery is range-duration; accepted range-expression is the rollback. Retired range-pitch data moved
under its test-fixture folder; its binaries and the new build cache were removed (289,915,085 bytes).
`scratch/cleanup-preview-range-duration-20261022/receipt.json` records the five operations and four verified
shortcuts: root `Listen to current preview.lnk`, range-duration `Try duration editing.lnk`, and repaired older
transpose/string-shift and replacement-paste links. Test songs remain separate from the listening example.
No staging, commit, push, installation, memory edits or additional workers in that original batch.

#### Acceptance follow-up: edit diagnostics (2026-10-23)

Owner accepted the sound but reported Longer/Shorter refusals with Fit unchecked, then requested logs that
capture the operation instead of asking them to reconstruct it. Existing expected HTTP400 edit errors were
not logged. `server.py` now writes one bounded `TAB edit` JSON completion event to the existing rotating
`%APPDATA%/VultureTracker/vulturetracker.log`: song, action/control, requested duration/Fit, caret duration,
revisions, selected beat IDs/onsets/spelling/voice/rest status (first32 with total/truncation counts), and result
or refusal reason. UI diagnostic metadata is stripped before model validation; no note text/lyrics/tokens or
whole request dumps. Duration controls and keyboard steps identify Longer/Shorter/dots/tuplets explicitly.
No editing or playback semantics changed. The original click sequence cannot be recovered retroactively.

In-memory diagnosis reproduced two relevant limits: final-quarter growth crosses the bar boundary; a fresh
full selection of the listening example includes sixteenth rests, which a caret-derived eighth-note request
tries to lengthen into following notes. Uniform-quarter fixture Shorter and notes-only listening selections
worked. This is evidence of duration-selection usability limits, not proof of the owner's exact sequence.
Preserve the owner's newer listening-song edit. Next useful parity batch is duration/rest-selection behavior
and musical refusal feedback; TG's per-beat fallback differs from the current atomic range contract.

Checks: three focused logging/HTTP tests (`logging-server.log`), real-page Longer refusal logging plus existing
Shorter/dots/tuplets/no-op/Undo (`logging-page-final.log`), and one final build in the existing
`scratch/tab-package-range-duration`. `logging-package.log` records the packaged real-control refusal/log,
successful duration edits/exact Undo, SONG/live WASM and standalone IT readback (16 attacks,192 rows,10.667s).
These logs and the disposable `logging-check` song are under `scratch/tab-test-fixtures/range-duration`.
Shortcuts remain valid; range-expression remains the rollback. Automatic approval review blocked deletion of
this run's generated `.build` cache ("blocked by policy"); it remains in the current package folder.
Sound accepted; editing acceptance remains open. Two bounded workers finished and stopped. No commit/push/release.

### Previous state: cross-measure selection and Copy/Paste (2026-10-22, owner accepted)

The owner accepted the tempo-unit preview ("Looks good") and authorized this bounded round with one Codex worker.
The shared native clipboard now captures occurrence-qualified beat groups, assigning separate clipboard IDs to
repeated visits and retargeting internal cross-pattern ties. Paste routes whole beats across existing written
patterns with fresh per-pattern IDs. It preserves voices, techniques, sparse stroke cohorts, beat text/chords,
source patterns, raw cells, shared history and exact timing. There is no second document or playback state.

Rendered drag, Shift-click and Extend buttons cross order boundaries; First/Last extend across the written song.
Selection shading uses occurrence identity. Copy remains correct when its endpoint is an empty later pattern.
Other cross-range mutations explicitly refuse; a plain/Ctrl click, track change, revision or song change clears
the range. Ordinary local single-pattern untied paste retains shared-pattern semantics. Cross-pattern paste
requires unique, unapproved, empty destination spans in copied track/voice lanes, including all touched patterns
and gaps. Explicit rests are authored content. Occupied spans, raw conflicts, past-song overflow, unsafe capacity
and beats straddling pattern boundaries fail before publication. No replacement/mix/push/auto-expansion is added.
External ties refuse Copy; raw effects/tempo commands, measure headers and track lyrics are not copied.

Checks/logs under `scratch/tab-test-fixtures/cross-measure`:
- `source-final.log`: eight model/State checks pass, including cross-bar ties, repeated source visits, voices,
  sparse strokes, immutable payloads/failures, later destination guards, exact Undo/Redo/reopen and independent
  standalone IT readback with the native attack at quarter11.5 and release12.5. `model-initial.log` also passes
  the eight clipboard-filtered legacy checks (one overlaps the new malformed-payload case).
- `page-range-pass.log`: actual Shift-click/Copy, refusal, Paste, Pattern/ROLL, exact Undo and empty-endpoint case.
  `page-selection-final.log`: new drag/Extend Right and legacy local drag pass; old pattern-end expectations
  fail because Next/Last now traverse the written song. `page-checked.log` passes the final new range case;
  its remaining Last-order assertion needed the existing settled wait for host refresh. `page-buttons-final.log`
  passes the corrected existing buttons case, including exact order2 and actual written-song-end refusal.
  The unchanged fractional-row paste case passes in `page-final.log` alongside its earlier range-test failure.
- `tg-oracle-checked.log/json`: one actual match, sounding notes/durations/internal tie and source unchanged;
  one extra TG rest autofill remains. The probe uses pinned TG2.1.0 Copy/Paste managers, completing cleaned
  measures' rests before replacement as the editor does. Initial compile failure and subsequent precondition
  mismatch are retained (`tg-oracle.log`, `tg-oracle-final.log`, `tg-oracle-diagnostic.json`), not counted as passes.
- Page setup failures retained in `page-initial.log`/`page-ready.log`; real host echo selection loss diagnosed
  in `page-selection-diagnostic.log` and fixed by preserving matching source-qualified selection on refresh.
  `page-echo.log` and `page-final.log` then caught test use of Enter instead of Go and the wrong restored order.
  State initial failures were test API assumptions (read_it tuple, SongError and undo(redo=True)); fixed checks
  pass without weakening source/IT/history assertions.
- `capture-before.log` and `capture-after-final.log`: visible foreground1920x1080, same camera, no page errors.
  Images: `cross-before-selection.png`, `cross-after-selection.png`, `cross-after-paste.png`; concise score
  images `cross-after-score.png` and `cross-after-paste-score.png`. Baseline JS is served by route override from
  `tablature.js.before`; no source swap. Initial capture runner tried hidden Copy controls (`capture-after.log`);
  existing keyboard Ctrl+C/V works in the compact view.

Qualified candidate `scratch/tab-package-cross-measure` contains exe/ffmpeg/zip and clean listening assets;
test fixture/logs remain separate. `listening/four-bars-cross-measure.yaml` reuses the familiar first two bars
copied into bars3/4, accepted soft sample, full lyric phrase and tempo-unit marks. Source, `.it`, `soft-c.wav` only.
The editing fixture is `scratch/tab-test-fixtures/cross-measure/song/song.yaml` with empty bars3/4. Initial fixture
preparation retained the full technique sampler but correctly refused a new fade/delayed-stroke combination;
the focused editing example instead uses the existing plain four-bar notes, with no audio-engine changes.
No physical listening or final user editing acceptance claimed. Current delivery is cross-measure; selected
rollback is `scratch/tab-package-tempo-unit`. Parent completed the five-operation rotation: lyrics-layout
non-build data moved intact to `scratch/tab-test-fixtures/lyrics-layout/retired-preview`, its binaries and the
new build cache removed (289,856,428 bytes). Receipt: `scratch/cleanup-preview-cross-measure-20261022/receipt.json`.
Root `Listen to current preview.lnk` opens the new listening example. A separate
`scratch/tab-test-fixtures/cross-measure/Try cross-measure editing.lnk` opens the empty-destination editing
fixture in the same exe. Both shortcuts' target, quoted argument and working directory passed COM readback;
their metadata is in the same operation receipt.
The sole build passes (`build.log`). `check-package-edit.log` passes real bundled rendered selection/Copy/Paste,
editable standalone IT readback and byte-exact Undo, then actual bundled IT export of the restored source (8 attacks).
`check-package-song.log` passes actual bundled IT export of the final pasted listening piece: 16 attacks over
192 rows/10.667s, reopened without a native plan, equal to the source build, with pitches/timing, instrument/keymap
routing and duration checked against native playback. Both pass visible score/caret/navigation, rendered SONG
extent, live WASM and selfcheck. No broad suite, format sweep or unchanged audio-engine rerun was needed.
Parent reviewed the scoped diff, both package logs and matching foreground selection/paste captures; no findings
remain. Source compilation/whitespace checks pass and the index remains empty. The sole Codex worker returned
ownership and was explicitly stopped after handback; other workers and automation remain paused.

Scoped product: `vulturetracker/tablature.py`, `vulturetracker/gui.py`, `vulturetracker/web/tablature.js`.
Tests: existing model/State/page modules, `tools/tg_edit_oracle.py`, `tools/tg_edit_oracle/TgEditProbe.java`,
`tools/exe_check.py`; docs: BACKLOG/GUIDE/CHANGELOG/TABLATURE-PARITY. Pre-round untracked product copies are
`tablature.py.before` and `tablature.js.before` in the fixture directory; `product-change.diff` isolates this round.
No staging/commit/push/release/install or memory edits. Only the previously authorized preview rotation was cleaned.

### Previous state: authored tempo beat-unit engraving (2026-10-22, owner accepted)

The owner accepted dense lyric spacing and authorized the next bounded parity round. One Codex worker extends
the shared score/print projection for BAR-02; no other worker was resumed. Measures now offers all eight pinned
TuxGuitar tempo-base choices, including whole notes. Imported schema bases through 64/dotted remain displayed
and retained as an imported selector choice. The native alphaTab tempo effect draws the bundled Bravura SMuFL
metronome symbol/dot and authored value; its automation still contains the authoritative quarter BPM. Native
placement is reused, with font advance/ink measured at the actual scale. Registration is idempotent.

TG integer conversion is preserved: 61 dotted quarters plays 91 quarter BPM, and the displayed value remains 61.
Mid-bar raw T changes display their actual quarter BPM. Stale saved units warn visibly in editor/print and use
the effective quarter marking; they are not mutated by rendering. Apply of the same selected stale unit repairs
its value only when exactly representable. Valid authored values are retained. Existing inexact-unit refusal,
raw-T authority, tracker data, source/history, native events and IT timing remain unchanged.

Evidence in `scratch/tab-test-fixtures/tempo-unit/`:
- `before.log` / `layer-off.log`, `tempo-before-score.png` / `tempo-layer-off-score.png`: foreground 1920x1080
  reproduction and isolated native tempo layer. The old projection discarded measure units and drew only
  quarter90, with no later unit changes. `tablature-before.js` is the small pre-round untracked-source baseline;
  `tablature-change.diff` isolates this round's product change for review.
- `scale-pass.log`: new real unit control test passes all seven non-quarter choices, exact Undo and unchanged
  IT bytes/native events, plus 21 combined/TAB/staff print combinations at 40/80/150%. Its second test initially
  selected bar4 while bar1 was current; this fixture navigation error was corrected in the targeted follow-up.
- `stale-pass.log`: 3 passes: corrected 61/91, mid-bar raw120, imported dotted32/64, reopen, valid-value preservation,
  stale150 fallback/warning, same-unit repair/exact Undo, plus existing tempo controls and measure operations.
  Neighboring tempo labels remain separated in the tested mid-bar case. `tg-unit.log`: pinned TG integer
  read/play/write and stale-export-refusal test passes. No full suite or audio/native-dialog rerun.
- First failures retained in `focused.log` / `focused-final.log`: malformed sparse raw-row fixture and wrong
  Playwright page creation, plus an incorrect geometry assertion comparing SVG advance boxes including a
  leading space. `focused-pass.log` then exposed a real custom dotted-half small-scale ink overhang; measuring
  at the actual print scale fixed it without padding. Existing native plain-quarter small-scale contours are
  unchanged; custom-symbol ink and inter-mark spacing checks are distinct.
- `layout-final.log`: same-camera visible foreground score/full print, no page errors. Final captures are
  `tempo-final-bar1.png`, `tempo-final-score.png`, and `tempo-final-print-full.png`.

Product changes are confined to `vulturetracker/web/tablature.js`; existing page/exe runners and these docs
carry focused checks. The musical example retains the accepted soft sample, full "Soft light drifts home"
phrase and previous techniques at90BPM, with dotted-quarter60/eighth180/half45/quarter90 display marks.
Fixture: `scratch/tab-test-fixtures/tempo-unit/song/four-bars-tempo-unit.yaml`. Previous measured live/rendered
audio evidence remains applicable because this is notation-only; physical output/listening has not been
requalified. This is beat-unit engraving, not full BAR-02/TuxGuitar layout parity.

The sole build passes (`build.log`) at `scratch/tab-package-tempo-unit`; its clean listening folder contains
`four-bars-tempo-unit.yaml`, `four-bars-tempo-unit.it`, and `soft-c.wav`. `check-package.log` passes actual bundled
score/all three print modes with the expected symbols/values, lyric spacing (editor minimum gap 4.331px),
caret/navigation, live WASM and selfcheck. Actual IT export reopens without a native plan: 35 attacks over
192 rows/10.667s, equal to source build and annotation/unit-cleared IT bytes; measured RMS/native 1.0036.
No new physical-output listening or user visual acceptance is claimed. Pinned semantics evidence is
`scratch/tuxguitar-techniques/TGTempo.java` and `TGTempoBase.java`; glyph codes follow the SMuFL metronome table.

Scoped files: `vulturetracker/web/tablature.js`, `tests/test_tablature_page.py`, `tools/exe_check.py`,
`BACKLOG.md`, `GUIDE.md`, `CHANGELOG.md`, `TABLATURE-PARITY.md`. Scoped whitespace check passes; index is empty.
Parent reviewed the matching before/debug/final score and full-print captures. The sole Codex worker completed
and was explicitly stopped after handback. Parent completed the five-operation delivery rotation: older notation
non-build data moved intact to `scratch/tab-test-fixtures/notation/retired-preview`; its binaries and the new build
cache were removed (289,840,837 bytes). Current tempo-unit preview and selected `scratch/tab-package-lyrics-layout`
rollback remain. Root `Listen to current preview.lnk` opens the tempo-unit exe/example, verified by COM readback.
The single operation receipt is `scratch/cleanup-preview-tempo-unit-20261022/receipt.json`. Fixtures remain separate
from listening assets. No staging/commit/push/release/install or memory edits; other workers and automation remain
paused. Owner visual acceptance remains separate.

### Previous state: dense lyric spacing (2026-10-22)

One authorized Codex worker fixes shared score/print lyric spacing. The original full phrase "Soft light drifts
home" is restored in `scratch/tab-test-fixtures/lyrics-layout/song/four-bars-lyrics-layout.yaml`, using the accepted
soft sample and unchanged musical passage. No words, anchors, timing, fonts, saved score, tracker data, playback
or IT projection semantics were changed. alphaTab 1.8.4's native lyric glyph previously reserved only height;
the shared registration now contributes measured centered text widths to its existing beat-spacing springs.
Browser font metrics at the actual scale supplement alphaTab's approximate SVG character-width table, including
italic extents. Registration is idempotent; native wrapping, hit bounds, caret and playhead follow the new widths.

A whole measure can still be wider than the chosen page/view. Completed native lyric-band positions are checked
before offering the result: an overfull layout asks for a wider view or lower print scale/wider paper instead
of displaying crowded words. The editor restores its surface/hit targets when widened and clears only its own
old width error. Print disables output for that case. This is a bounded fit policy, not arbitrary-length lyric
typography or complete TG engraving parity. Alternating voices retain their existing separate native bands.

Evidence in `scratch/tab-test-fixtures/lyrics-layout/`:
- `before.log`, `layer-off.log`: visible foreground 1920x1080 reproduction and isolated lyric-layer removal;
  note X positions unchanged when lyrics removed. Before drifts/home gap0.707px. Matching captures are
  `lyrics-before-bar1.png`, `lyrics-before-score.png`, `lyrics-layer-off-score.png`.
- `layout-final.log`: final same-camera foreground score/full print, no page errors; drifts/home gap4.331px.
  `lyrics-final-score.png`, `lyrics-final-bar1.png`, `lyrics-final-print-full.png` show the full phrase, diagrams
  and existing techniques. No shortened-word workaround or post-SVG position adjustments.
- `source-final.log`: both focused page tests pass. Real lyric Apply/exact Undo, unchanged IT bytes/native
  events, 28 eighth/sixteenth tokens and longer words, alternating voices in musical anchor order, actual ink
  gaps by native band, measure/system boundaries, 900px view, forced480px refusal/recovery, caret/playhead,
  combined/TAB/staff print, repeated print and exact token counts. Dense print40% and landscape80% fit;
  portrait80% genuinely overfull bar refuses. Normal full phrase prints at80/150%. Existing rest/tie/voice1,
  literal hyphen/+/_/[x]/NBSP placement and stale mapping controls remain covered.
- Final dense minimum visible gaps: editor10.064px; 900px view5.604px; combined40% print3.803px,
  TAB/staff40%3.883px; landscape80%6.079px. These are fixture measurements, not universal margins.
- Real first failures retained: `focused.log` compared equivalent unreduced caret rationals; `focused-final.log`
  exposed forced print compression; `print-diagnostic2.log` measured native requested/minimum forces1.935/2.532.
  `width-guard.log`/`extent-guard.log` rejected intermediate fitting attempts; those guards were removed.
  `final-layout.log` exposed inaccurate small-scale font estimates; actual browser metrics fixed this.
  `ink-diagnostic.log` exposed overly conservative symmetric cached extents; final validation uses actual
  left/right ink and native band rows. `reviewed-final.log` assumed mixed-voice DOM order was musical order;
  test now checks anchor order separately. `reviewed-pass.log` assumed a500px viewport bypassed the app's
  minimum width; recovery now constrains the actual score pane. Earlier diagnostic logs retain a missing
  capture hook and cp1252 stdout error; these were harness errors, not product or listening evidence.

Only `vulturetracker/web/tablature.js` changes product behavior. Focused tests and `tools/exe_check.py` extend
existing runners. Audio/engine/export/shortcut code is untouched; previous notation live10.5s max PCM difference0
and rendered-control fractional-alignment RMS4.11e-6 remain applicable (`../notation/live-final.log`,
`../notation/rendered.log`). No new physical-output listening claim or broad suite/native-dialog rerun.

The single build passes (`build.log`) at `scratch/tab-package-lyrics-layout`; listening entry is
`listening/four-bars-lyrics-layout.yaml`, with its standalone IT and accepted soft sample. Selected rollback is
`scratch/tab-package-it-notation`. `check-package.log` passes bundled page/assets/selfcheck, full four-word score
spacing (minimum gap4.331px), combined/TAB/staff print (8.155/10.751/11.509px), caret/navigation, live WASM,
visible notation-loss warnings and standalone IT reopen without a native plan:35 attacks over192rows/10.667s,
equal to source build and annotation-cleared musical IT data, RMS/native1.0036. No shortcut dialogs were rerun.
Parent reviewed the matching foreground before/debug/final score and full-print captures. The sole Codex worker
completed and was explicitly stopped after handback. Parent completed the five-operation delivery rotation:
older layout non-build data moved intact to `scratch/tab-test-fixtures/articulations-layout/retired-preview`;
its binaries and the new build cache were removed (289,835,373 bytes). Current lyric-layout preview and selected
notation rollback remain; fixtures stay separate from listening assets. Root `Listen to current preview.lnk`
now opens the lyric-layout exe/example, verified by COM readback. The single operation receipt is
`scratch/cleanup-preview-lyrics-layout-20261022/receipt.json`. Scoped diff check passes and index remains empty.
No staging/commit/push/install/memory writes; other workers and automation remain paused. Owner accepted the
dense lyric spacing preview on 2026-10-22 ("Looks good, let's continue").

### Previous state: IT lyrics/diagrams and Windows song shortcuts (2026-10-22)

One authorized Codex worker extends the existing standalone IT notation-loss diagnostics to nonempty lyrics
and chord diagrams. Source/history/engraving remain intact. Lyrics do not synthesize vocals; diagrams do not
generate notes, including diagrams attached to rests; existing musical chord notes remain. This does not
activate a native technique plan or loosen timing/instrument/raw-tracker ownership guards. Repeated traversal
retains original annotation warnings and deduplicates them after expansion. Empty lyrics emit no loss warning.

PROJECT now offers CREATE SONG SHORTCUT, using the existing native Save dialog route (pywebview on the normal
Windows app, Tk fallback). It selects a literal `.lnk` path, confirms existing-file replacement, handles Cancel,
and reports the saved path. A hidden static PowerShell WScript.Shell call receives only environment data; it
never interpolates song/path into script. Packaged links target `sys.executable`, `gui` and the quoted absolute
song path; development links use adjacent pythonw with `-m vulturetracker` and workspace cwd. Existing source
asset/alias protection and atomic writes apply. Unsupported platform, malformed destination, missing launcher,
COM failure and song switch during dialog refuse without changing song/history/mix. No association/autostart,
new dependency or automatic desktop installation. App/song relocation requires recreating the shortcut.

Focused evidence lives in `scratch/tab-test-fixtures/notation/`:
- `focused.log`: three notation cases pass (individual/combined/cleared, repeats/endings/ties/rests, warnings
  through export.prepare, IT byte equality, native events/backing and actual PCM equality at44.1/48k); initial
  shortcut test error was a test snapshot treating State.mix as data instead of a method. Corrected and extended
  shortcut case passes in `shortcut-guards-final.log`, using actual COM readback and Unicode/apostrophe/&/$ in
  both song and link paths, dev/frozen targets, alias/malformed/platform/COM-failure guards and cancellation.
- `lyrics-final.log`: two affected model cases pass, including empty lyrics and unchanged repeated plans.
- `page-pass-final.log`: actual lyric and diagram controls, visible export warnings, standalone IT reopen,
  shortcut control/save-path/cancel feedback and exact Undo pass. Earlier page logs retain harness readiness,
  auto-closed lyrics panel and read_it tuple-shape mistakes; no product assertions were weakened.
- Native Save qualification is opt-in (`VT_NATIVE_DIALOG=1`) under a game lease. `native-dialog-controls.log`
  identifies modern filename Edit1001 instead of classic1148. `native-dialog-final.log` is not an automated
  overwrite pass: the owner clicked Yes while the original driver missed the nested No button. The test app
  closed afterward; only its disposable link was targeted. The corrected owned-PID driver finds the actual
  nested No button: `native-dialog-no-cancel.log` passes Save, existing-link No then Cancel, and direct Cancel.
  `pywebview-save.log` repeats those successfully in the normal real pywebview/WinForms app, not just Tk.
- Independent native/IT reopen at48k has zero attack-frame shift; at44.1k shifts[0,-12,-36,-42,-54] match integer
  IT tick rounding. Pitch error<.030cent, settled level difference<.818%, settled waveform RMS<1.052%; last
  audible tail differs+1/-72frames. Existing quiet cut-ramp transient remains110.20% relative RMS over its fixed
  first5ms at44.1k. Annotation-on/off IT and PCM equality prove these are unchanged musical conversion limits.
- Both actual muted controls cover10.5s: `live-final.log` has max PCM difference0 against native; `rendered.log`
  has fractional-alignment RMS4.11e-6 at0.2sample. Zero runs match authored rests. Initial `live.log` failed
  because the capture runner resolved a relative sample path under its temporary song; the existing runner now
  resolves its input path and reads UTF-8. No audio/native engine changes or physical-device listening claim.

The musical example uses the accepted soft sample, original lyrics "Soft light", C/F diagrams and the existing
technique passage. IT bytes/native backing/events match the same song without lyrics/diagrams. Initial four-word
lyrics crowded at adjacent short-note positions (`layout.log`, initial in-chat capture); this remains an engraving
limitation, not fixed by shortening the example. Final same-view visible/foreground score/full-print captures
are `notation-score.png` and `notation-print-full.png`, with `layout-final.log` free of page errors.

Qualified preview `scratch/tab-package-it-notation/listening/four-bars-notation.yaml` includes its standalone IT
and sample. Selected rollback: `scratch/tab-package-articulations-layout`. The single build passes (`build.log`).
`check-package.log` passes the final packaged page/assets/live WASM/selfcheck, visible lyric/diagram loss warnings,
and standalone IT reopen without a native plan: 35 attacks over 192 rows/10.667s, byte-equal to the same song with
these annotations cleared, RMS/native1.0036. The normal packaged pywebview native Save dialog passes Save,
existing-link No then Cancel, and direct Cancel without changing the link. Real COM readback confirms the
packaged exe/quoted Unicode song/working directory; a second owned hidden launch uses that exact target and
arguments and `/api/state` confirms the same song. The shortcut and all test outputs stay under fixtures.
Delivery contains only exe, ffmpeg, ZIP and listening assets. Parent reviewed the final score/full-print captures.
No broad suite, 19-case package sweep or unrelated format qualification was repeated.
Product files this round: `tablature.py`, `project.py`, `server.py`, `gui.html`; tests extend existing model/page/GUI
tests and `tools/exe_check.py`. Parent completed the five-operation rotation in
`scratch/cleanup-preview-notation-20261022/receipt.json`: older articulation non-build data moved intact to
`scratch/tab-test-fixtures/articulations/retired-preview`; its binaries and the notation build cache were removed
(289,832,125 bytes). Current notation preview and selected layout rollback remain. The initial cleanup preflight
hit PowerShell 5.1 JSON array wrapping before any mutation; corrected the existing helper and applied its reviewed
plan once. Root `Listen to current preview.lnk` now targets the notation exe/example, verified by COM readback.
The sole Codex worker completed and was explicitly stopped after handback. No staging/commit/push/install/memory
writes; other workers/automation remain paused. Scoped tracked diff check passes and index remains empty.
Owner visual/listening acceptance of the new example remains separate; the existing crowded-lyrics limitation
remains recorded above.

### Previous state: combined articulation/harmonic engraving (2026-10-22)

One authorized Codex worker fixes the reported P/S.H. collision and its T/A.H., S/N.H. siblings. The only
product change is `vulturetracker/web/tablature.js`: the shared editor/print registration reserves independent
native Tap/Harmonics effect bands, and both displays use alphaTab's supported `effectBandPaddingBottom: 10`
(default 2). alphaTab 1.8.4 had allowed shared endpoint slots; separate bands alone still left 3.79px of print
ink overlap because the native text glyphs use different baselines. The extra layout padding resolves that
remaining deficit. Original native glyphs, authored text, mixed/sparse labels, notation, source/history,
tracker, native/MIDI audio and IT data are preserved. No vendor fork, post-render offsets or font shrinking.

Evidence is in `scratch/tab-test-fixtures/articulations-layout/`. `articulation-before-score.png` and
`articulation-before-print-system.png` reproduce the collision; `articulation-layer-off-score.png` isolates
the T/S/P glyph layer. Retained band-only attempts (`after.log`, `bands.log`, `measured.log`) and the temporary
beat-text fallback (`final.log`, `focused-new-final.log`) were insufficient: TAB-only print exposed the same
baseline deficit. The fallback was removed. Final same-camera, 1920x1080 visible/foreground fully loaded
captures are `articulation-native-final-score.png`, `articulation-native-final-print-system.png` and the full
views, with no page errors in `native-final.log`. Parent visually reviewed the complete affected system.

Focused automation extends the existing page runner/tests, not a separate harness. `focused-native.log`
passes the projection case and the real-control editor/print/Undo case. Actual SVG ink gaps for the tightest
S/N.H. pair are 3.23px editor, 2.61px at 80% print, 2.21px at 40%, and 4.45px at 150%; TAB-only and combined
print pass. Repeated print is stable; authored cues survive; all five harmonic types retain native marking
projection; real Apply controls leave IT bytes/native events unchanged and three Undos restore exact source
bytes. The mixed-voices/ties/history/reopen case passes in `focused-mixed-final.log`. Earlier `focused.log`
and `focused-final.log` retained invalid probe loop length (22000 beyond the helper's13230 frames) and obsolete
fallback expectations; corrected fixture loop end8820 is valid. `focused-native.log` also retains the final
test-only expectation failure where an existing sparse fade label accompanied the authored cue; targeted
rerun asserts preservation rather than exclusivity. No backend/audio code changed, so prior articulation
audio/export evidence below is reused; no new listening or physical-device claim.

Qualified preview: `scratch/tab-package-articulations-layout`, with the reproducing musical example at
`listening/four-bars-articulations-layout.yaml` and its standalone IT. Selected rollback is
`scratch/tab-package-it-articulations`. The single build passes in `build.log`; the targeted packaged check
passes in `check-package.log`: actual bundled score/combined print/TAB-only labels, native navigation/live WASM,
and full selfcheck. IT reopens without a native plan with 35 attacks over192 rows/10.667s, equal to the source
build; measured RMS/native ratio1.0036. No full-suite or unrelated package/format sweep was repeated for this
JS-only fix. Tests and the existing `tools/exe_check.py` runner changed; current BACKLOG, CHANGELOG and parity
describe the result. Scoped tracked diff check passes and index remains empty.

Parent completed the delivery rotation: current layout preview plus articulations rollback are the only
preview builds. Fade non-build data moved to `scratch/tab-test-fixtures/fade/retired-preview`; its binaries
and the layout build cache were removed (289,823,781 bytes). Packaged runner outputs `listening/.tryout` and
`listening/native-it-export` moved under the layout fixtures as `package-tryout` and `package-native-it-export`.
The single operation receipt is `scratch/cleanup-preview-articulations-layout-20261022/receipt.json`.
Root `Listen to current preview.lnk` was updated and read back against the layout exe/example. The sole Codex
worker completed and was explicitly stopped. Owner accepted the corrected engraving ("Looks good", 2026-10-22);
audio is unchanged and prior evidence is reused. No staging/commit/push/install; other workers
and automation remain paused.

### Previous state: standalone IT tapping/slapping/popping admission (2026-10-22)

One authorized Codex worker replaces the strict tap/slap/pop refusal with an explicit notation-loss warning.
Pinned `scratch/tuxguitar-techniques/MidiSequenceParser.java` attack, duration and velocity paths do not consult
these flags; existing native/MIDI neutrality tests agree. These markings remain notation-only, distinct from
tapped harmonics. No sample substitution, gain/timing processing or native-plan activation was introduced.
`tablature.py` emits one `IT notation:` diagnostic listing active flags; `song.py` forwards it to CLI and the
existing visible export warnings. IT cannot retain the semantic markings; source/history and engraving retain
them. False/cleared flags produce no warning. Existing instrument, raw cell, timing and overlap limits remain.
Native percussion still refuses these guitar markings; admitting their sound-neutral export does not broaden
native validation. Other unsupported notation (for example chord diagrams) still refuses before publication.

Focused evidence in `scratch/tab-test-fixtures/articulations/`: `focused.log` runs six cases, with five complete
passes and two subcase failures in the combination case. Those fixtures incorrectly put guitar markings on drum
notes, already rejected by native validation. The corrected guitar-plus-unchanged-kit case passes in
`focused-final.log` across 11 previous-feature fixtures: ordinary/tied score, percussion, gates/dynamics, pitch,
whammy, repetition, harmonics, grace, strokes, swing and fade. Marked and cleared standalone IT bytes match;
native events/backing and actual marked/cleared native PCM match. Repeats/alternate endings and continuation-only
markings retain a single warning. Source/history, raw pan, keymaps and instrument state are unchanged.

Independent IT reopen/render without a native plan at 48/44.1 kHz reuses the existing whole-cycle keyed swing
probe. Five measured attack offsets are all zero at 48 kHz and [0,-12,-36,-42,-54] frames at 44.1 kHz, matching
integer tick rounding. Pitch error is below .030 cent, settled level difference below .818%, settled waveform
RMS difference below 1.052%; final audible tail differs +1/-72 frames. The existing quiet attack's fixed first
5ms transient differs by 110.20% relative RMS at 44.1 kHz (27.82% over 50ms), caused by the preceding voice's
phase-dependent cut ramp. Marked/unmarked IT identity proves this discrepancy is not introduced by the flags;
no waveform-exact or physical-device claim is made.

`page.log` passes two actual-control cases: Tap/Slap/Pop editing, visible notation-loss warning, IT export/reopen,
byte-exact Undo, mixed voices/tied flags, authored text, print and history/reopen. Uniform renderer T/S/P glyphs
remain; no generated explanation was added above the score. Initial `layout.log` and
`scratch/tab-strokes-layout-articulations-score.png` reveal an existing P plus semi-harmonic S.H. glyph collision.
This is not fixed this round. The musical example places marks on plain notes instead, retaining harmonic
passages separately. `layout-final.log` has no page errors; final 1920x1080 score/print captures are
`scratch/tab-strokes-layout-articulations-final-score.png`, `-articulations-final-print.png` and bar1/bar3 images.
The print screenshot covers the visible viewport, ending partway through the final system; the complete score
element capture shows all three separated marks. No full visual-parity claim is made for combined techniques.

Current musical delivery: `scratch/tab-package-it-articulations/listening/four-bars-articulations.yaml`,
adjacent `.it` and accepted `soft-c.wav`. It retains the fade/swing and previous technique passages and adds
readable T/S/P marks in bars 3/4; these markings deliberately do not change its sound. Both actual muted transport
captures compare 10.5 seconds. `listening-live-final.log` matches native PCM exactly. `listening-rendered.log`
has aligned RMS difference 3.344e-4, or 6.602e-6 after independently measured +.475-sample fractional alignment;
authored rests remain and neither reports playback errors. Physical output and owner listening acceptance are
not established by these measurements. The first capture invocation used a relative song path, so its temporary-copy
sample reference could not resolve and page initialization timed out; `listening-live.log` retains the failure.
The successful runs use the existing capture runner with an absolute equals-form song argument; no new harness.

All new check songs/logs remain under `scratch/tab-test-fixtures/articulations`; regression fixtures are reused
directly from `fade` and `swing`. The sole preview build passed in `scratch/tab-package-it-articulations`;
exe size is 49,512,530 bytes (internal 1.8.0), with ffmpeg and distribution ZIP. Build log:
`scratch/tab-test-fixtures/articulations/build.log`. All 19 packaged checks pass first run via
`scratch/check-package-it-articulations.cmd`; `check-*.log` files retain actual browser/selfcheck results.
This includes Place/Fit/GP5/capo, ordinary four-bars and every prior native IT fixture. The articulation case
confirms visible notation-loss warning, marked/cleared IT byte equality and independent five-attack renders at
both rates; the musical case reopens 35 attacks/192 rows/10.667s without a plan and checks compact annotations.
`check-formats.log` passes seven notation exports (LilyPond, MusicXML, GP3/4/5, ASCII TAB, TG1.5) and native
GP2/GPX/GP imports. No broad local suite or unrelated engine rerun was used for this notation-only change.
Selected rollback: `scratch/tab-package-it-fade`. The sole Codex worker completed and was explicitly stopped.
Parent completed the approved delivery rotation using `scratch/tidy-previews.ps1`: old swing non-build data
moved to `scratch/tab-test-fixtures/swing/retired-preview`, its three binaries and the new build cache removed
(289,814,029 bytes). The single operation receipt is `scratch/cleanup-preview-articulations-20261022/receipt.json`.
Only articulations/current and fade/rollback previews remain. Root `Listen to current preview.lnk` was updated
and read back against the articulations exe and listening YAML. No staging/commit/push/install; other workers
and automation remain paused. Owner listening acceptance is the remaining delivery check.
Product changes this round are only `vulturetracker/tablature.py` and `vulturetracker/song.py`; tests extend
`tests/test_tablature_sync.py`, `tests/test_tablature_page.py` and the existing `tools/exe_check.py` runner.
GUIDE, SONG_FORMAT, CHANGELOG and TABLATURE-PARITY now describe the sound-neutral admission and loss warning.
No renderer or engine code changed. Scoped diff check passes; index remains empty. Worker stops after handback.

### Previous round: audible native fade-in and bounded standalone IT (2026-10-22)

One authorized Codex worker extends the existing native plan, identity gain setters and strict IT projection.
Investigation confirmed fade was previously metadata/MIDI-only; native live/audio now intentionally applies
the same TG mixer-mode track expression. This prerequisite was reviewed and authorized before implementation.
No DLL/WASM rebuild, new musical interpreter, rendered-sample substitution or mixer change was introduced.
`fade_expression_streams` shares the existing 31..126 staircase and final 127 reset with MIDI, preserving source
callback order, ties/repeated heads and collapsed short ramps. Each owned native voice/layer composes expression
with its original gain, including released tails; subsequent attacks inherit the current track expression.
Other tracks remain isolated. Raw note/instrument attacks on affected channels refuse because they have no
score identity. Malformed gains and event/resource limits fail explicitly; stale handles never retarget.

Standalone IT reuses performed attacks/releases and harmonic lanes, writing owned volume-column controls.
Controls round to the nearest row (at most half a row) and integer volume; the entire discrete normalized gain
trajectory must remain within 6.25 percentage points of the original note volume. CLI and visible export warnings
report the actual bound. This is a control-trajectory bound, not instantaneous waveform equivalence. Active
affected attacks must be row-aligned. Unsafe NNA/carry/random state, raw volume/effect conflicts, delayed SDx
expression rows, incompatible shared-pattern requests and inadequate final-tail representation refuse before
publication. Unchanged later neutral voices keep their existing admission rules. Source/history, keymaps,
envelopes, pitch controls, raw unrelated cells and saved/current mix remain on the shared paths.

Measured full-cycle probe at 48/44.1 kHz: declared control error 3.085 percentage points; maximum sampled native/IT
gain difference 2.593 points. Native weighted expression error is below 3.14e-7; IT settled cell gain error below
.000335. Independent native gain-onset detection matches the intended frame (first usable reference sample,
0–1 frames around a zero crossing). IT volume changes settle to 95% in 16/15 frames respectively, in addition to
row placement. Final audible tail difference is 0/-73 frames, reflecting accumulated IT tick rounding at 44.1 kHz.
Released-tail gain is also measured independently; unaffected-track PCM differs by less than 1e-7. Existing
attack/cut ramp transient differences remain, so these figures do not promise waveform-exact output.

Focused checks: `scratch/it-fade-engine-final.log` passes 32 scheduler/gain/isolation cases; `it-fade-midi.log`
passes 5 existing MIDI expression cases; `it-fade-guards.log` passes 2 malformed/atomic refusal cases.
`it-fade-focused.log` has 8 passes and 3 fixture/obsolete-expectation failures; the targeted 3 pass in
`it-fade-focused-final.log`. `it-fade-isolation.log` also passes the source-order and event-cap cases; later logs
retain malformed raw-row labels and a missing test import before the final 32-pass engine result.
`scratch/tab-test-fixtures/fade/export-final.log` passes 6 focused export/regression cases; `tail-render.log`
passes the released-tail/native-WASM/standalone isolation comparison at both rates. `it-fade-native-prototype-final2.log`
passes actual Python/WASM gain, seek and replay at both rates; earlier prototype logs retain instrumentation
failures that assumed attack-only gain and omitted the new event rank. No full local baseline was run.

Real page checks drive Fade-in, visible approximation warnings, standalone IT export/reopen and byte-exact Undo.
`scratch/it-fade-page.log` passes the existing multi-voice/print case, then fails the new case's unfocused Ctrl+Z
after successful export; `it-fade-page-final.log` passes using the real Undo control. Generated uniform fade
prose initially overlapped the score and still said MIDI-only. Same-view layer-off isolation proved the cause;
uniform native glyphs now stand alone, while sparse string labels, full tooltips and authored text remain.
`scratch/tab-test-fixtures/fade/projection-final.log` passes the focused projection assertion; the initial log
retains a wrong test-class invocation. Final editor/print images were inspected at 1920x1080 with no page errors:
`scratch/tab-strokes-layout-fade-final-score.png`, `-fade-final-bar1.png`, `-fade-final-print.png`.
Before/layer-off/after captures remain, including the first element-capture race; final capture waits for layout.

Musical example: `scratch/tab-package-it-fade/listening/four-bars-fade.yaml`, adjacent `.it` and accepted
`soft-c.wav`. It adds two clear fade passages to the accepted swing example while retaining safe earlier
techniques. Both actual muted transports compare 10.5s: `scratch/tab-test-fixtures/fade/listening-live.log`
has exact PCM match; `listening-rendered.log` has aligned RMS 1.121e-4, or 8.10e-6 after measured -.15-sample
fractional alignment. Authored rests are preserved. These are transport measurements, not physical-device
or owner listening acceptance. The owner accepted swing ("it's good"); this new fade example awaits acceptance.

Single preview build: `scratch/tab-package-it-fade/vulturetracker.exe` (49,510,994 bytes), ffmpeg and ZIP;
build log `scratch/tab-test-fixtures/fade/build.log`. All 18 packaged checks pass first run, including Place,
Fit, GP5/capo, ordinary four-bars and prior native IT fixtures, through `scratch/check-package-it-fade.cmd`.
Their `scratch/tab-test-fixtures/fade/check-*.log` files retain selfcheck and actual browser results.
`check-native-it-fade.log` repeats the independent gain/tail measurements at both sample rates;
`check-native-it-listening.log` reopens 35 attacks over 192 rows/10.667s without the native plan, equals the
source build and passes compact-annotation checks. `check-formats.log` passes seven notation exports
(LilyPond, MusicXML, GP3/4/5, ASCII TAB, TG1.5) and native GP2/GPX/GP imports.
Package test songs/logs stay in `scratch/tab-test-fixtures/fade`; unchanged fixtures are reused directly from `swing`.
Final delivery rotation is complete: only `tab-package-it-fade` and rollback `tab-package-it-swing` remain.
Parent reused the guarded cleanup tool after qualification: old layout songs/evidence moved intact into
`scratch/tab-test-fixtures/strokes-layout/retired-preview`, then its three build files and the new fade `.build`
cache were removed (289,810,648 file bytes). Exact map and receipt: `scratch/cleanup-preview-fade-20261022/`.
Project-root `Listen to current preview.lnk` now opens the fade build on `listening/four-bars-fade.yaml`; its
target and arguments were read back. The delivery contains only exe, ffmpeg, ZIP and the listening folder.

Source changed this round: `tablature.py`, `song.py`, `openmpt.py`, `export.py`, `agent.py`,
`web/engine-core.js`, `web/tablature.js`; focused tests in `test_tablature.py`, `test_tablature_sync.py`,
`test_engine.py`, `engine_check.js`, `test_tablature_page.py`, plus existing `tools/exe_check.py` and docs.
Scoped diff check passes and the index remains empty. No commit/staging/push/release/install; other workers and
automation remain paused. The sole Codex worker completed and was explicitly stopped after handback.

### Previous operation: accepted swing preview and tidy delivery (2026-10-22)

Owner accepted the swing example ("it's good") and requested one current build, one rollback and separate test
songs. Current delivery remains `scratch/tab-package-it-swing`; rollback is `scratch/tab-package-it-strokes-layout`.
Both keep their original executable and listening paths. Project-root `Listen to current swing.lnk` opens the
current executable directly on `scratch/tab-package-it-swing/listening/four-bars-swing.yaml`.

Test songs and check logs now live under `scratch/tab-test-fixtures/swing`; rollback's check log is under
`scratch/tab-test-fixtures/strokes-layout`. Retired strokes songs, histories and evidence were moved intact to
`scratch/tab-test-fixtures/strokes`; its executable/ffmpeg/distribution ZIP and the current swing `.build` cache
were removed (289,801,083 file bytes). Only two `scratch/tab-package*` folders remain. Current delivery contains
only the executable, ffmpeg, distribution ZIP and `listening` folder. Published `dist/` and other scratch/reference
material were outside this cleanup. No processes were stopped or workers resumed.

The exact move/delete map and single receipt are in `scratch/cleanup-preview-layout-20261022/plan.json` and
`receipt.json`. Native PowerShell moves stayed within scratch, with reparse/protected-marker/process checks,
pre-action inventory checks and post-move verification. All non-build data was moved before deleting binaries.
`scratch/check-package-it-swing.cmd` now uses the separate fixture/log paths. All 14 runner song paths resolve
and prepare for native playback; the shortcut target/arguments were read back. An initial over-broad standalone
compile check hit the GP5 fixture's intentional pitch-quantization refusal; native playback preparation is the
appropriate relocation check and passed. No product code changed and the earlier packaged results remain valid.

Future rounds must seed fixtures from `scratch/tab-test-fixtures/swing` and keep tests/logs outside deliveries;
do not replay the historical preparation scripts that recreate fixtures inside a package. Historical paths in
the previous-round sections map to the new fixture folders. No commit, push or new build. Index remains empty.

### Previous round: standalone IT swing/triplet feel (2026-10-22)

One authorized Codex worker extends existing performed attack/release projection in `vulturetracker/tablature.py`.
Native plan positions identify eligible swung notes; no second swing interpreter or native playback change.
Written anchors, source/history, keymaps, channel mix/envelopes and unrelated raw tracker cells remain intact.
Repeat expansion uses source occurrence/absolute phase, including odd-meter fragments and alternate endings.
Existing `_swing_timing` and pinned `MidiSequenceParser.java::checkTripletFeel` remain authoritative: plain eligible
eighth pairs use 16+8 IT ticks, sixteenth pairs 8+4; dotted/tupletted beats stay straight, and same-voice neighbors,
rests and missing partners follow native behavior. Plan activation includes release-only changes and unplayed
context refusal. Actual attacks/releases require exact ticks/cells; no swing timing quantization was introduced.
Speed6/row_step1/4 SD4/SD2 attacks and releases preserve a global tempo command and raw channel fields.
Grace, strokes, repetition, harmonics, gates, ties and pitch controls reuse their existing admission bounds.
Off-grid gates, occupied cells, same-channel overlap, unsafe inherited state, unplayed patterns and differing
shared-pattern performance contexts refuse atomically. Written source timing still must fit the tracker row grid.

Focused evidence: `scratch/it-swing-model.log` passes 12 native swing cases. `it-swing-export-final.log` ran 63
strict-export/native cases: 62 passed, one old blanket-swing-refusal assertion became obsolete. It now checks
still-unsupported fade-in; `it-swing-delays-final.log` passes that case plus the added SD4/SD2 case. Thus 64 distinct
relevant cases are covered by the unchanged 62 plus the targeted two, not a claimed whole-run 64-pass log.
Initial `it-swing-focused.log` retains a malformed test fixture (raw row07 supplied as its first row); corrected
by keeping row00 first. `it-swing-page.log` passes two actual feel-control/export/print/Undo/reopen cases.
Tests and harness changes: `tests/test_tablature.py`, `tests/test_tablature_sync.py`, `tests/test_tablature_page.py`,
`tools/exe_check.py`; no edit-command semantics changed, so existing pinned native/TG vectors were reused.

Independent standalone IT renders reopen without the native plan at 48/44.1 kHz. Five measured attacks have
offsets 0 at 48 kHz and [0,-12,-36,-42,-54] frames at 44.1 kHz, independently detected against bounded waveform
search and matching accumulated integer IT-tick rounding. Pitch error is below .030 cent; settled waveform RMS
difference below 1.052%, level difference below .818%. Final audible tail shifts +1/-72 frames respectively.
One quiet second attack has a 110.20% relative RMS difference over the fixed first 5 ms (27.82% over 50 ms),
from the preceding voice's phase-dependent cut ramp. This transient is reported separately, not hidden by the
settled window. Silent reference windows are handled explicitly. No waveform-exact or physical-output claim.

Musical example: `scratch/tab-package-it-swing/listening/four-bars-swing.yaml` (adjacent `.it`, `soft-c.wav`).
It uses the accepted soft sample, eighth feel in bar1 and sixteenth feel in bar2, retaining earlier pitch/whammy,
strokes, repetition, grace and harmonic passages where safe. Both actual muted transport captures compare 10.5s:
`it-swing-listening-live.log` has exact PCM match; `it-swing-listening-rendered.log` has aligned RMS 1.15e-4,
or 7.59e-6 after measured .15-sample fractional alignment. Authored rests remain; no global nonzero assertion.
The captures are transport data measurements, not verification of the owner's physical audio device.
`it-swing-layout.log` reports no page errors. Inspected 1920x1080 score/print screenshots retain readable native
feel/technique glyphs and the previous removal of duplicate stroke/grace prose: `tab-strokes-layout-swing-bar1.png`,
`tab-strokes-layout-swing-score.png`, `tab-strokes-layout-swing-print.png`. New example listening/visual acceptance
remains with the owner; the earlier strokes example was explicitly accepted as sounding OK.

Built once: `scratch/tab-package-it-swing/vulturetracker.exe` (49,505,805 bytes, internal 1.8.0), ffmpeg and local
ZIP. Selected rollback: `scratch/tab-package-it-strokes-layout`. Fixture preparation copied only needed YAML/WAV
files from retained `tab-package-it-strokes`; no deleted preview/build was restored. Build log:
`scratch/it-swing-build.log`. All 17 packaged browser/native IT/selfcheck cases passed first run, including Place,
Fit, GP5/capo, ordinary four-bars and all prior native IT feature fixtures; `scratch/check-package-it-swing.cmd`
lists their `scratch/tab-package-it-swing/check-*.log` paths. `check-native-it-swing.log` independently measures
both sample rates. `check-native-it-listening.log` reopens 35 attacks over 192 rows/10.667s without a native plan,
equals the source build and checks compact annotations. `check-formats.log` passes seven notation exports
(LilyPond, MusicXML, GP3/4/5, ASCII TAB, TG1.5) and native GP2/GPX/GP imports.
Scoped diff check passes and index remains empty. No commit/push/release/install/cleanup; all other workers/
automation remain paused. Worker stops after final handback.

### Previous operation: preview cleanup (2026-10-22)

Owner authorized cleanup before further feature work. Removed 30 superseded `scratch/tab-package*` previews
and the two remaining previews' rebuildable `.build` caches: 8,974,955,625 bytes of files. Current delivery is
`scratch/tab-package-it-strokes-layout`; selected runnable rollback is `scratch/tab-package-it-strokes`.
Their executables, ffmpeg, ZIPs, listening songs and checks remain at the same paths. Published `dist/`, source,
owner songs, `scratch/tab-audio-review`, `scratch/tab-pitch-listening` and shared `scratch/tab-preview` fixtures
were outside the deletion list. No worker was resumed, and no processes were stopped.

Before removal, all 598 non-build files from retired previews (songs, samples, histories, logs, scripts and
interchange outputs) were preserved in `scratch/cleanup-tab-previews-20261022/old-preview-songs-and-evidence.zip`
(53,268,530 bytes), then read back and byte-content verified. Old executable/ffmpeg/distribution ZIP copies and
PyInstaller caches were intentionally discarded. `plan.json` maps exact retired paths to the archive;
`receipt.json` records successful deletion. Containment, reparse/protected markers, active-process references,
keeper presence and unchanged file inventories were checked immediately before native PowerShell removal.

Historical package links below now refer to archived evidence: extract the matching `tab-package.../` member
from that recovery ZIP if needed. Future preview work should seed from the retained strokes fixtures instead
of replaying scratch preparation chains that reference retired package folders. Product tests were not rerun
for artifact-only cleanup; source/index are untouched. Next work remains the owner's choice; corrected layout
visual acceptance remains open and the strokes listening example has positive audio acceptance.

### Previous round: stroke/grace annotation crowding (2026-10-22)

Owner listened to the strokes musical example and reported "sounds OK"; audio acceptance for that example is
positive. Their 1920x1080 screenshot exposed recurring overlapping annotation text. The responsible layer is
`notationTrack` in `vulturetracker/web/tablature.js`: generated `Stroke up/down` labels duplicate brush arrows,
and full per-string grace parameter paragraphs duplicate grace glyphs while overlapping adjacent bars and print
margins. Isolating only that text layer reproduced a clean score before the fix; no font shrinking/CSS hiding.

Minimal shared editor/print projection fix removes those duplicate labels. Native brush/grace glyphs remain;
authored beat text remains. Grace that cannot share a glyph keeps `Grace (mixed timing)` or `Grace (unassigned
string)` as a compact visible fallback. Exact grace details were already in controls/tooltips; stroke direction
and rate now join the existing note tooltip. Source notation, history, audio plan and IT compilation are unchanged.

Same-song, same-viewport evidence: `scratch/tab-strokes-layout-before-bar1.png` versus
`scratch/tab-strokes-layout-after-bar1.png` (1920x1080); isolated layer-off
`scratch/tab-strokes-layout-layer-off-bar1.png`; print `scratch/tab-strokes-layout-{before,after}-print.png`.
Direct final score-element capture: `scratch/tab-strokes-layout-after-score.png`. Inspected editor and print:
reported overlapping paragraphs are gone, brush/grace symbols remain, no page errors. The runner's before-bar3
capture was taken after the full-score layer was switched off and is diagnostic-only, not another before baseline.
Capture logs: `scratch/it-strokes-layout-{before,after}.log`.

Checks: `scratch/it-strokes-layout-projection.log` passes two focused projection tests; `it-strokes-layout-page.log`
passes four actual page/print/control tests, including authored cues, stroke/grace tooltip details, mixed-timing
fallback, retained glyphs, source/history/native-plan invariance and existing clear/Undo/reopen behavior. No test
failures this round. Previous audio/IT results remain applicable; no broad audio or sixteen-case package rerun.

Corrected preview built once: `scratch/tab-package-it-strokes-layout/vulturetracker.exe` (49,505,339 bytes,
internal 1.8.0), ffmpeg/local ZIP; `scratch/it-strokes-layout-build.log`. Affected packaged musical browser/native
IT/selfcheck passes in `scratch/tab-package-it-strokes-layout/check-listening-layout.log`, including an explicit
no-duplicate-annotations check. It reopens 31 attacks over 192 rows/10.667 seconds. Listening copy in that package
contains byte-identical `four-bars-strokes.yaml`, `soft-c.wav` and `.it`; the actual packaged IT re-export is also
byte-identical to the accepted example. No audio change or new listening requirement is implied by this layout fix.
Scoped diff check passes; index remains empty. Changed product: `vulturetracker/web/tablature.js`; focused tests:
`tests/test_tablature_page.py`, `tools/exe_check.py`; documentation: BACKLOG, GUIDE, CHANGELOG, TABLATURE-PARITY.
Selected rollback: `scratch/tab-package-it-strokes`. Owner visual acceptance of the corrected preview remains.
Worker finished and stops after handback. No commit/push/release/install/cleanup; other workers/automation stay paused.

### Previous round: standalone IT brush/strum strokes (2026-10-22)

One authorized Codex worker extends existing performed attack/release projection. Shared beat cohorts are resolved
with `_cohort_strokes`; stroke-only songs and repeat flattening request the existing native plan. No second stroke
interpreter, authoring change, native audio change or channel allocator. Written anchors, source/history, channel
mix, sample keymaps/envelopes and unrelated raw tracker content remain unchanged.

Pinned `scratch/tuxguitar-techniques/MidiSequenceParser.java::getStroke/applyStrokeDuration` and native tests are
authoritative: distinct untied strings consume steps, up ascending string number/down descending; the shortest
co-onset voice/rest duration capped at a quarter controls spacing. Quarter cohort/value4 gives 120 TG ticks = 3 IT
ticks; quarter-triplet/value8 gives 40 TG ticks = 1 IT tick. Single-string strokes have zero offset at all rates.
All other actual attacks/releases must fit exact IT ticks and cells; ordinary quarter value8/16/32/64 refuse.
The native short-gate exhaustion branch retains the full gate when delay >= gate, including a six-string staccato
release into the next pattern. Ties, repeats/endings, sparse cohort metadata, dynamics and safe grace/repetition/
harmonic/pitch combinations follow the plan. Overlap, occupied cells, unplayed technique context, invalid mapping,
non-cut NNA/carried state and existing pitch-reset bounds refuse atomically. Pick strokes remain notation only.

Focused checks: `scratch/it-strokes-export-final.log` ran 55 strict-export/native-stroke cases, 54 passed; the only
failure was the new endings fixture putting its added note on the melody's occupied string2. Using unused string6
fixes that fixture; `it-strokes-combinations-final.log` passes the complete affected case. The 54 unchanged passes
are reused. `it-strokes-page.log` passes both actual stroke controls, visible direction, IT export/reopen, source/
history invariance and independent audio. `it-strokes-render-final.log` passes keyed attack/gain/tail and dead160
render checks. Existing native/TG semantics were reused because authoring behavior did not change.

The whole-cycle probe has nine attacks, measured per original channel with the existing mixer mute path, without
a native plan on the standalone IT. Independent bounded waveform search matches predicted tick offsets within
one frame: 48 kHz all zero; 44.1 kHz down strings 1/2/3 = -5/-2/0, up = -36/-38/-41, final plain = -54 each.
Worst pitch error .027 cent, settled waveform error 1.179%, settled level difference .860%. Final audible tail
differences are <=1 frame at 48 kHz and <=74 at 44.1 kHz; short dead160 gates differ by <=2 frames. The fixed first
5-ms plain-successor cut ramp differs by up to 161.76% relative RMS at 44.1 kHz, and first50ms by 13.98%; settled
error there is .952%. This is not sample-exact parity, and no native/mix change hides the phase-dependent transient.

Retained `it-strokes-focused.log` exposes a diagnostic ambiguity: a sustained periodic sine matched both -54 and
+46 samples on the plain successor. The probe now uses the existing zero-start volume envelope to make attack
onsets identifiable; assertions still independently search and compare offsets to predicted tick rounding.
`it-strokes-listening-prepare.log` retains a valid refusal: delaying the previous slide's plain target required an
oversized fine-portamento reset. The musical copy reverses that brush to keep the target first, preserving the
pitch guard and earlier slide; `it-strokes-listening-prepare-final.log` passes.

Musical copy: `scratch/tab-package-it-strokes/listening/four-bars-strokes.yaml` plus adjacent editable `.it`, using
the accepted soft sample. Earlier pitch/whammy/repetition/harmonic/grace passages remain, with opposite-direction
chord brushes added. Actual muted live playback matches native PCM exactly over 10.5 seconds; rendered transport
matches its decoded source at .000007908 RMS after 0-frame/-.15-sample alignment. Authored rests explain zero runs;
neither capture reports page errors. Logs: `scratch/it-strokes-listening-live.log`, `it-strokes-listening-rendered.log`.
Physical listening is pending. Preview built once: `scratch/tab-package-it-strokes/vulturetracker.exe`
(49,506,219 bytes, internal 1.8.0), ffmpeg/local ZIP; `scratch/it-strokes-build.log`. All 16 packaged checks pass:
`check-{four-bars,fit,place,gp5,capo,native-it,native-it-repeats,native-it-percussion,native-it-techniques,
native-it-pitch,native-it-whammy,native-it-listening,native-it-repetition,native-it-harmonics,native-it-grace,
native-it-strokes}.log` in that folder. Place passed first attempt this round; the earlier known preparation race
is not claimed fixed. The strokes package check independently repeats both-rate keyed render assertions.
`check-formats.log` passes seven notation exports and GP2/GPX/GP native imports. Scoped diff check passes, index empty.
Product change: `vulturetracker/tablature.py`; test/harness changes: `tests/test_tablature{,_sync,_page}.py`,
`tools/exe_check.py`; docs: this handoff, GUIDE, CHANGELOG, TABLATURE-PARITY. Selected rollback:
`scratch/tab-package-it-grace`. Worker finishes and stops after handback; next action is owner listening.
No commit/push/release/install/cleanup; old workers and automation remain paused.

### Previous round: standalone IT grace notes (2026-10-22)

One authorized Codex worker extends the existing performed-attack projector; no second grace interpreter or
native playback change. Native grace/main events supply actual timing, pitch, independent velocity and keymap.
Written positions, source/history, original channel mix and raw tracker fields stay intact. Source occurrence
selects note metadata while actual event time selects destination, including grace in a preceding pattern's gap.
Main harmonic/pitch/repetition techniques remain separate from the ordinary grace voice. Existing cut-NNA,
mapping, carried-envelope, harmonic-lane retirement and pitch ownership guards still apply.

Pinned `scratch/tuxguitar-techniques/MidiSequenceParser.java` grace handling and current native vectors are reused:
16th/32nd lengths are 6/3 IT ticks; 64th is 1.5 ticks and refuses. All attacks/releases must fit exact IT ticks and
available cells. Dead grace at 120 BPM is off-grid and refuses; 160 BPM is representable on a finer row grid.
Before-beat grace uses a gap or refuses overlap; it never shortens the predecessor. Near the song origin it falls
back to on-beat. Transition none/slide/bend/hammer labels preserve notation but add no distinct audio in current
native semantics. Tied continuations retain the head grace only. Unsafe inputs refuse without replacing outputs.

Checks: `scratch/it-grace-export-final.log` has 40 strict-export tests passing; `it-grace-model.log` has 14 native
grace/dead-gate model tests passing. `it-grace-page.log` passes actual grace controls/export/reopen and independent
audio. `it-grace-focused-final.log` passes grace+vibrato/harmonic/repetition combinations and the final render metric.
Coverage includes source/history, velocity omitted on main, alternate sample/default volume, chords, ties across
patterns, repeats/endings, global tempo/volume and raw-channel preservation, atomic overlap/mapping/cell refusals.

The six-attack independent render probe reopens standalone IT without a native plan at 48/44.1 kHz. Bounded
waveform search independently detects attack offsets: all zero at 48 kHz, and 0/-5/-18/-20/-50/-54 frames at
44.1 kHz, matching floored IT tick accumulation. Worst pitch error .030 cent, settled waveform error 1.50%,
settled level difference 1.35%. Final audible tails differ by +1/-72 frames. Dead160 grace/main tail checks are
within two frames. A quiet 44.1-kHz grace transition differs by 25.13% over its first 50 ms and 121.09% relative
RMS over the fixed first 5 ms: the preceding voice's cut ramp has a different phase. Settled error there is 1.01%;
this is explicitly not waveform-exact parity. No mix/native semantics were changed to hide it.

Retained `it-grace-focused.log` initially selected -17 instead of -18 frames when fitting the preceding cut ramp,
causing 7.15% settled error. Alignment now searches the source-informed settled span after 5 ms, independently
asserts predicted tick offsets, and reports the full fixed first-5-ms transient separately. `it-grace-render-final.log`
also passes the prior repetition render regression. Earlier metric logs/page contain a zero-energy divide warning;
the final metric explicitly returns 0 for both-silent windows and infinity for unexpected sound, never NaN.

Listening: `scratch/tab-package-it-grace/listening/four-bars-grace.yaml` and adjacent `.it` use the accepted soft
sample, retaining earlier pitch/whammy/repetition/harmonics with new grace passages. Actual muted live transport
matches native PCM exactly over 10.5 seconds; rendered transport matches decoded source at .000006344 RMS after
3-frame/+.475-sample alignment. Logs: `scratch/it-grace-listening-live.log` and `it-grace-listening-rendered.log`.
Authored rests explain zero runs; no page errors. The earlier corrected pitch example was accepted by the owner;
this new grace example still needs physical listening acceptance.

Preview built once: `scratch/tab-package-it-grace/vulturetracker.exe` (49,504,686 bytes, internal 1.8.0),
with ffmpeg/local ZIP; `scratch/it-grace-build.log`. All 15 packaged cases pass: `check-{four-bars,fit,place-final,
gp5,capo,native-it,native-it-repeats,native-it-percussion,native-it-techniques,native-it-pitch,native-it-whammy,
native-it-listening,native-it-repetition,native-it-harmonics,native-it-grace}.log` in that package. The packaged
grace check independently renders both rates with the same measured bounds and silence-safe metric. The initial
`check-place.log` retains the known stale playback-preparation 400 after edits; isolated `check-place-final.log`
passes against the same binary. `check-formats.log` passes seven notation exports and GP2/GPX/GP native imports.
Scoped `git diff --check` passes; index stays empty. Product change this round is `vulturetracker/tablature.py`;
tests/harness: `tests/test_tablature{,_sync,_page}.py`, `tools/exe_check.py`; docs: this handoff, GUIDE, CHANGELOG,
TABLATURE-PARITY. Selected rollback: `scratch/tab-package-it-harmonics`. Worker finished and stops after handback.
No commit, push, release, install or cleanup. Other workers/automation stay paused. Next action is owner listening.

### Previous round: standalone IT harmonic layers (2026-10-22)

One owner-authorized Codex worker. The strict compiler consumes the native plan's existing natural/artificial/
tapped/pinch/semi layer lists, including harmonic data and duplicate-pitch semi layers. The final layer remains
on its original channel; at most two fixed appended lanes per harmonic parent receive the other layers. Original
channels, sample keymaps/data, envelopes, authored patterns, native playback and history remain unchanged. Extra
headers inherit parent volume/pan/mute; current export mix/solo/mutes expand locally to those lanes. Native audio
snapshots/stems retain their original channel count and grouped plan. Layer names identify the appended channels.

Pinned `scratch/native-score-engine/libopenmpt/libopenmpt_ext_impl.cpp::vt_parent_groups` selects the final layer
as primary; `soundlib/Snd_fx.cpp::ConsumeEventGroupNNA` retires siblings on the next parent attack. Export mirrors
that cut-NNA ownership with explicit cuts on unused lanes, including previously released but still audible envelope
tails. Reused lanes receive fresh attacks; pitch controls and key-offs use the existing strict projectors. Pulse
retirement routes by actual performed time while looking up metadata through the retained head occurrence.

Bounds/refusals: 64 total channels, explicit valid mapped instruments, cut NNA, no duplicate checks/carried
envelopes. Local raw channel state on harmonic parents, instrument pan/filter overrides, randomized instrument
state, sample pan/auto-vibrato, unsafe overlaps/cells/off-grid gates and occurrence-dependent layer reuse refuse
atomically. Harmless global tempo/volume commands and other raw channels remain untouched. A harmonic key-off
exactly at song end needs a following release row: IT's automatic end fade is not the native release envelope.
Existing pitch-curve and pulse admission/warnings remain unchanged. Native repetition precedence still applies.

Checks: `scratch/it-harmonics-focused-final.log`: 36 focused standalone-export/native-harmonic tests passed,
including previous export regressions. `it-harmonics-mapping.log`: two targeted mapping/refusal checks passed;
`it-harmonics-mix-final.log`: three targeted checks passed after strengthening original-channel snapshot assertions.
`it-harmonics-boundary.log`: tied pulses crossing patterns on a harmonic parent and atomic boundary refusals passed.
`it-harmonics-page.log`: five real harmonic type controls, data selectors, visible notation, IT export/reopen and
independent render, one passed. No authoring semantics changed, so the existing pinned native/TG semantics are reused.
`it-harmonics-pitch-final.log`: layered bend/vibrato independently render at both rates and reset to a plain
successor; a lower harmonic shift-slide requiring an oversized final reset refuses explicitly. The initial
`it-harmonics-pitch.log` retains that expected representability refusal before it was asserted by the test.

Independent IT renders reopen without a native plan. The five-type whole-cycle probe has 14 attacks; pitches
are within .017 cent of the expected sample transpositions, measured individual spectral gains within 2.421%
(the existing half-up 0..64 volume quantization), and settled waveform error at most 1.158%. At 48 kHz, measured
attack shifts and final audible-tail difference are zero. At 44.1 kHz, shifts are -18 frames per half-second,
reaching -108; final audible tail differs by -127 frames, bounded by accumulated floored IT ticks. The fixed first
5-ms transient reaches 1.21% relative RMS at 48 kHz and 56.09% at one 44.1-kHz transition. This phase-dependent
cut/ramp difference is reported separately, not asserted as exact waveform parity or hidden by the settled window.
Long release-envelope semi -> natural -> plain retirement renders differ by less than .77% after the transition,
proving unused lower voices do not leak. A second mapped sample independently preserves its own pitch and default
volume. Logs: `it-harmonics-render-final.log`, `it-harmonics-tails.log`, `it-harmonics-mapping.log`. The final
render check also asserts measured attack offsets equal the predicted IT tick-rounding shifts.

Listening copy: `scratch/tab-package-it-harmonics/listening/four-bars-harmonics.yaml` and adjacent editable `.it`,
using the accepted soft sample. Earlier pitch/whammy/repetition passages remain; fourth-bar harmonics are added.
Muted actual live transport matches native PCM exactly over 10.5 seconds across all four bars. Rendered transport
matches its decoded source at .000006334 RMS after 3-frame/+.475-sample alignment. Written rests account for zero
runs; no live errors/reloads. Logs: `scratch/it-harmonics-listening-live.log` and `-listening-rendered.log`.
The owner accepted the earlier corrected pitch example; this new harmonic example still needs owner listening.

Retained diagnostics: `scratch/it-harmonics-probe.log` exposed automatic IT end fade versus native key-off at the
last row, motivating the explicit final-release-space refusal and probe rest. `it-harmonics-mix.log` is a test-only
TypeError (snapshot channel count is an integer), corrected in the targeted final pass. Initial capture options
used spaces instead of the existing runner's equals syntax and hit its default old fixture; that unrelated capture
is `it-harmonics-listening-wrong-arguments.log`, not harmonic acceptance. Correct full-span captures are above.
The initial transient measurement accidentally shortened its 5-ms window by the negative sample alignment;
the corrected fixed full window raises its reported worst error from 29.13% to 56.09%, without changing sound
or settled assertions. `it-harmonics-sparse.log` confirms undeclared instrument slot 1 plus valid slot 2 compiles:
the YAML compiler fills the gap with an empty Instrument, so the suspected None-slot bug did not reproduce.

Preview built once: `scratch/tab-package-it-harmonics/vulturetracker.exe` (49,503,815 bytes, internal 1.8.0),
with ffmpeg/local ZIP; log `scratch/it-harmonics-build.log`. All 14 packaged cases passed: `check-{four-bars,fit,
place-final,gp5,capo,native-it,native-it-repeats,native-it-percussion,native-it-techniques,native-it-pitch,
native-it-whammy,native-it-listening,native-it-repetition,native-it-harmonics}.log` under that package.
The initial `check-place.log` retains a transient playback-preparation 400 after both Place/edit/Undo checks
passed; only that case was rerun against the same executable and passed. No rebuild. Packaged harmonic metrics
match the source checks; musical IT reopens with 26 attacks, 192 rows and 10.667 seconds, equals the source build,
and measures RMS/native 1.0031. `check-formats.log` passed seven notation exports and GP2/GPX/GP imports.
Scoped `git diff --check` passed. Next action is owner listening of the new musical example; work is complete
and this worker stops after handoff. No automatic continuation or broader test sweep is planned.
Selected rollback: `scratch/tab-package-it-repetition`. Round files: `vulturetracker/tablature.py`, `song.py`,
`export.py`, `tests/test_tablature_sync.py`, `tests/test_tablature_page.py`, `tools/exe_check.py`, and
BACKLOG/GUIDE/CHANGELOG/TABLATURE-PARITY. Existing scratch package/capture runners reused. No staging, commit,
push, release, installation or cleanup. Stop this worker after final handoff.

### Previous round: standalone IT trill and tremolo picking (2026-10-22)

One Codex worker, owner-authorized. The shared strict projection consumes the native plan's actual pulse
identities, attacks, pitches, velocities and key-offs; no second repetition interpreter or tracker retrigger.
Pulses route by performed time even when their source identity remains in a previous tied pattern. Original
sample data, instrument keymaps/envelopes, raw tracker notes/effects, authored patterns and history stay intact.

Attacks require exact IT ticks and an available cell (SDx for a delayed tick). Trill 4/8/16/32 and picking 8/16/32
are tested with suitably fine rows; ordinary 64th trill attacks are off-tick and refuse. Coarse rows with multiple
attacks in one cell, SD delays beyond 15, missing alternate sample mappings, raw effect/cell collisions, overlaps,
inherited instruments, non-cut NNA, duplicate-check actions and carried envelopes refuse before replacing output.
Existing native conflicts (dead/hammer/pitch curves with repetition) are unchanged. Other off-grid gates refuse.

**Narrow documented timing exception:** TG ends the final native pulse one legacy tick early. Only the verified
last pulse of its source identity may extend its key-off by 1/960 quarter, and only when that lands exactly on an
IT tick. Attacks and other releases never round. CLI and real export results display `IT repetition:` warning;
the musical bound is 62.5/tempo ms (.520833 ms at 120 BPM), plus IT audio-tick rounding. Coincident next attacks and
the final song boundary are covered; an injected non-final off-grid release is explicitly refused.

Independent native/standalone IT probe renders (standalone reopened without native plan): 14 attacks, including
alternate sample/volume/pitch, delayed 32nd picking attacks, plain successor and a single final pulse. At 48 kHz,
all measured attack offsets are 0 frames, pitch difference below .005 cent, level difference below .263%, settled
waveform error below .267%, and final audible tail differs by 1 sample. At 44.1 kHz, measured attack offsets reach
-54 frames at 1.5 s (72 IT ticks each floor 918.75 to 918 samples); pitch matches, level difference below .371%, settled
waveform error below 1.009%, and final audible tail differs by -72 frames (1.633 ms). Tests bound attack/tail drift by
accumulated IT tick rounding plus the specific final TG tick, not an arbitrary timing tolerance.

The full first 50 ms waveform comparison at the final 44.1 kHz attack differs by 13.992% RMS relative to that probe
window. This is retained and reported, not passed as exact parity. The preceding voice's short crossfade depends
on its phase at the rounded attack; source `scratch/native-score-engine/soundlib/MixerSettings.cpp` defines the
default 952 us ramp-down, and `Sndmix.cpp::ProcessRamping` applies it. A temporary render-only no-ramp diagnostic
reduces full error to 3.586% (remaining envelope tick-phase mismatch); after a fixed 5 ms transient window the normal
render error is 1.008%. Assertions check settled waveform/levels, actual pitch, attacks and final audible tail.
No app mixer, ramp setting, native playback or musical semantics were changed.

Checks: `scratch/it-repetition-focused-final.log`: 27 passed; `scratch/it-repetition-boundary-final.log`: final-song
boundary case, 1 passed. Relevant native repetition/let-ring/compiler modules: 57 passed in
`scratch/it-repetition-model.log`, one obsolete blanket-refusal diagnostic corrected and rerun successfully in
`scratch/it-repetition-model-final.log`. These unchanged passing cases are reused, not a full baseline sweep.
`scratch/it-repetition-page.log`: real trill/picking/rate controls, visible warning, IT export/reopen/render,
source/history unchanged, 1 passed. Dotted/truncated and one-pulse palm gates, ties across bars, independent chord
strings, let-ring, first/second endings, repeated traversal, raw tempo change and raw notes/effects are covered.

Listening example: `scratch/tab-package-it-repetition/listening/four-bars-repetition.yaml` and adjacent editable
`.it`, using the accepted soft sample. First-bar pitch and second-bar whammy remain; third-bar trill/picking are
added. Over 10.5 seconds across all four bars, muted actual live PCM matches native exactly; actual rendered
transport differs from decoded source by .00000484 RMS after 2 frames/-.475 sample alignment. No reload/prepare
commands or live errors; written rests account for zero runs. Logs: `scratch/it-repetition-listening-live.log`
and `scratch/it-repetition-listening-rendered.log`. Owner listening acceptance of this new example remains open.

Retained failures: `scratch/it-repetition-focused.log` and `-focused-2.log` exposed test fixture errors (wrong
absolute row, non-contiguous raw row text, forbidden native dead/hammer combinations, overlapping same-string
let-ring, missing math import), a 120 BPM palm gate correctly accepted instead of the intended 100 BPM refusal,
and obsolete blanket-repetition refusals. `scratch/it-repetition-render-final.log` and
`-ramp-diagnostic.log` retain the full transient assertion failure; `-ramp-isolation.log` isolates the cause.
No product tolerance was relaxed or native sound changed to make those assertions pass.

Preview built once: `scratch/tab-package-it-repetition/vulturetracker.exe` (49,499,069 bytes, internal 1.8.0),
with ffmpeg and local ZIP; log `scratch/it-repetition-build.log`. All 13 packaged checks passed:
`scratch/tab-package-it-repetition/check-{four-bars,fit,place,gp5,capo,native-it,native-it-repeats,native-it-percussion,
native-it-techniques,native-it-pitch,native-it-whammy,native-it-listening,native-it-repetition}.log`.
Reopened musical IT has 22 attacks/192 rows/10.667 seconds, equals the source build and measures RMS/native 1.0025.
Packaged pulse measurements match the source results. `check-formats.log` passed seven notation exports and
GP2/GPX/GP imports. Selected rollback: `scratch/tab-package-it-whammy`. Next action is owner listening of the
musical example; this worker is stopped after handoff. Round files: `vulturetracker/tablature.py`, `vulturetracker/song.py`,
`tests/test_tablature_sync.py`, `tests/test_tablature.py`, `tests/test_tablature_page.py`, `tools/exe_check.py`, and
BACKLOG/GUIDE/CHANGELOG/TABLATURE-PARITY. Existing scratch capture/package runners reused. No staging, commit,
push, release, installation or cleanup. Stop this worker after handoff.

### Previous round: bounded standalone IT whammy (2026-10-22)

One Codex worker, owner-authorized, extended the existing strict pitch projection to admit `tremolo_bar`.
Only the pitch admission list and blanket refusal list changed in product code (`vulturetracker/tablature.py`);
native control generation/playback, tracker data, edit commands and history are unchanged. Bar values retain
their distinct native scale (11/2 versus bend's 11/4), negative values and existing per-note/string scope and
precedence. No second interpreter, synthesized substitute sample, pitch-envelope replacement or smoothing.

The same checked bounds apply: row-aligned controls retain time/pitch values, off-row controls warn in CLI/UI,
round at most half a row and must preserve turning/end values within 37.5 cents of the native discrete trajectory.
IT frequency/tick rounding remains. Steep curves, oversized initial jumps/resets, controls after keyoff, rounded
reset/attack collisions, raw effect collisions, non-cut NNA, duplicate checks and carried envelopes refuse before
replacing an output. Existing bend/vibrato/slide tests cover the shared boundary rules. Whammy-specific atomic
refusals exercise an initial -12 dive, a rapid 0/-2/0 curve and a held -2 curve with an oversized reset.

Measured independent native/standalone IT renders (no native plan on the reopened IT) at 48/44.1 kHz:
- Quarter-note -2 dive/return, +2 rise/return and mixed -1/+1: worst 20-ms pitch-window difference 17.2863 cents,
  threshold-time displacement 16.0475 ms. Endpoint error below .06 cent; plain successor stays neutral.
- Concurrent strings with different keymaps/samples and retained pitch/volume envelopes: measured difference
  below 3.56 cents; untouched third string below .082 cent. Tied/repeated traversal, staccato+ghost keyoff/return
  sharing a cell, raw notes/effects and source/history preservation are checked.
- The whole-cycle single-tone probe's per-cycle error from its intended native controls is at most 22.44 cents,
  allowing deliberate negative pitch and exposing the prior bad-loop anomaly. This diagnostic is specific to
  sequential monophonic probe segments; it is not a global pitch estimator for chords.

Source checks: `scratch/it-whammy-focused-final.log` (24), `scratch/it-whammy-model.log` (125 targeted native
model tests), `scratch/it-whammy-page-final.log` (2 muted real-control exports: pitch regression and whammy).
Real controls set the curve, export IT, show the approximation warning, reopen/render it and leave source/history
unchanged. Existing pinned TG/OpenMPT semantics were reused; editing semantics did not change.
The musical copy `scratch/tab-package-it-whammy/listening/four-bars-whammy.yaml` retains the accepted soft sample
and first-bar pitch examples, adding whammy in the second bar. Its adjacent `.it` stays editable.
Both actual muted page transports were captured over 10.5 seconds across all four bars: live PCM matches native
exactly; rendered PCM matches the decoded source with RMS .00000262 after one-frame/-.2-sample alignment.
Logs: `scratch/it-whammy-listening-live.log`, `scratch/it-whammy-listening-rendered-final.log`. Authored rests
explain the long zero runs; there is no blanket nonzero requirement. No reload/prepare command or LV error.
These are automated measurements; new whammy listening acceptance remains the owner's.

Retained actual diagnostic failures: `scratch/it-whammy-focused.log` first expected a bare keyoff where a valid
final pitch return shares that row, used a .3-second default sine with a 22000-frame loop endpoint, and expected
the range guard before an endpoint-loss guard. Expectations/fixtures now exercise the intended safe path and
refusals without changing production bounds. `scratch/it-whammy-page.log` skipped because VT_CHROMIUM was unset;
the final log uses Edge and runs both tests. `scratch/it-whammy-listening-rendered.log` used raw correlation,
which favored the louder part of a plucked attack; the reused capture runner now minimizes alignment error.

Preview built once: `scratch/tab-package-it-whammy/vulturetracker.exe` (49,496,212 bytes, internal 1.8.0),
with its ffmpeg and local ZIP; build log `scratch/it-whammy-build.log`. All 12 reused packaged checks passed:
`scratch/tab-package-it-whammy/check-{four-bars,fit,place,gp5,capo,native-it,native-it-repeats,native-it-percussion,
native-it-techniques,native-it-pitch,native-it-whammy,native-it-listening}.log`.
Whammy packaged measurements match the source results. Musical standalone IT reopens without a native plan:
16 attacks/192 rows/10.667 seconds, byte-equal to the source build, RMS/native 1.0025. The packaged format smoke
also passed (`scratch/tab-package-it-whammy/check-formats.log`: seven notation exports and GP2/GPX/GP imports).
Selected rollback remains `scratch/tab-package-it-pitch`. Next action is owner listening of the musical copy;
this worker stops after handoff. Round files: product `vulturetracker/tablature.py`; checks
`tests/test_tablature_sync.py`, `tests/test_tablature_page.py`, `tools/exe_check.py`; these four documentation files.
The existing scratch capture runner and package preparation were reused. No commit/staging/release/cleanup.

### Accepted follow-up: in-app stutter report (2026-10-22)

Owner retest (2026-10-22): "OK it works now." The corrected listening example is accepted for this reported
stutter; this does not close unrelated technique, editing, engraving or interchange acceptance.

The owner reported stutter playing `scratch/tab-package-it-pitch/pitch-check-song/song.yaml` in the app (either
transport). **Confirmed fixture defect fixed in a separate copy; no engine dropout was reproduced.** The existing
`scratch/tab-package-it-pitch/vulturetracker.exe` is unchanged; no rebuild was needed. Open these new songs in it:
- `scratch/tab-pitch-listening/four-bars-pitch.yaml`: the familiar melodic four-bars example with its existing soft,
  unlooped sample and added bend, vibrato and downward shift slide. This is the listening example.
- `scratch/tab-pitch-listening/pitch-clean.yaml`: corrected technical probe, still deliberately two seconds of sound
  followed by its written empty two-second bar. The original reported song/sample/package remain intact as evidence.

The probe's 441-Hz sample contains 220.5 cycles in .5 seconds. Looping its entire 22050 frames reverses slope at
the seam and creates spurious cycle frequencies: -664.45 cents at .469883 s and -533.21 cents at 1.478248 s,
outside the intended pitch steps. Setting the probe's loop end to 22000 (220 complete cycles) eliminates both.
Maximum adjacent-sample jump falls from .010622 to .006911. The no-technique comparison has neither anomalous
cycle. This identifies a concrete defect in the supplied test sound, not proof that every perceived stutter or
physical-device issue is fixed. Native TG pitch stepping remains unchanged; no smoothing was inserted.

- *Automated transport evidence.* DLL and WASM PCM match exactly with 127-frame reads
  (`scratch/pitch-live-replay.log`). Actual muted page live output matches native PCM sample-for-sample over the
  first 1.95 seconds, before and after the correction; longest exact-zero run is one sample, with no reloads,
  preparation pauses or errors (`pitch-live-page-capture.log`, `pitch-clean-live-capture.log`). The existing
  worklet benchmark measured p95 8.7 us/max 157.4 us against a 2667-us quantum, zero preparation pauses
  (`pitch-live-worklet.log`, quiet lease). This is a bounded local measurement, not device-level qualification.
- *Rendered transport.* Both original and corrected songs ran through the real bottom Play control. Corrected
  capture has no exact-zero runs in the active span; matching its browser-decoded source after a .2-sample alignment
  gives RMS difference .0000181 (`scratch/pitch-clean-rendered-capture.log`). Direct phase comparison to the separate
  oversampled native render is not valid; the earlier large raw difference in `pitch-rendered-page-capture.log`
  is retained, with decoded-source alignment in `pitch-rendered-source-alignment.log`. Original/corrected captures
  show no unexpected stop/reload commands. Muted Edge/headless capture cannot prove physical WebView2/device output.
- *Regression / export.* The canonical `native_pitch_it_song()` fixture now uses the full-cycle loop; the test
  reproduces old minimum cycle -664.4536 cents and checks corrected -0.0341 cents. Native and standalone corrected
  renders have no spurious downward cycles at 44.1/48 kHz; existing curve bounds/endpoint checks still pass.
  All 21 focused export tests pass (`scratch/pitch-clean-export-tests.log`); both corrected probe and musical example
  pass the existing packaged browser/IT export/reopen runner using the unchanged exe
  (`scratch/pitch-clean-package.log`, `scratch/pitch-musical-package.log`). Editable `.it` copies are beside both songs.
- *Changes / handback.* Only `tests/test_tablature_sync.py`, `tools/exe_check.py`, this checkpoint and scoped scratch
  diagnosis/listening files changed in this follow-up; no app/audio-engine, mixer, authored owner file or pinned
  playback semantics changed. `scratch/pitch-live-seam.log` keeps the measured original/corrected comparison.
  Listening to the musical copy and physical-device output remains owner acceptance. One Codex worker finished
  this bounded round and stops; no additional work queued, commit, push, installation, cleanup or rebuild.

### Pitch-export delivery (preceding round)

**Current app binary (2026-10-22): `scratch/tab-package-it-pitch/vulturetracker.exe`**
(49,497,606 bytes, internal version 1.8.0; single build `scratch/tab-it-pitch-build.log`). One user-authorized
Codex worker; Claude/older workers and automation remain stopped/paused. No commit, push, release, install or
cleanup. Rollback `scratch/tab-package-it-techniques`. Worker stops after this round.
- *Implementation / scope.* Strict CLI and UI IT conversion consumes the existing native bend/vibrato/shift-slide
  event plan, with E/F fine linear portamento: one native 3/16-semitone step is FF3/EF3. Pinned
  `scratch/080/Snd_fx.cpp` FinePortamentoUp/Down and DoFreqSlide establish the units. No new musical interpreter,
  note/audio resampling or native-playback/edit change; existing samples, keymaps and active envelopes stay intact.
  Row-aligned event timing is exact on the IT grid. Otherwise controls round half-up to the nearest row and warn
  in both compiler and visible export results. Turning points/end values must survive; the entire discrete curve,
  including held release tails, must remain within 37.5 cents. This ceiling is not a claim of exact rendered parity.
- *Limits / safety.* Existing gate/volume, repeat/pattern/order limits remain. Nonlinear slides, non-cut NNA,
  duplicate checks, carried envelopes, inherited/unmapped instruments, missing slide targets, steps/resets beyond
  one fine command, occupied effect cells, post-keyoff controls, context-dependent shared patterns and rounded
  controls landing on another attack refuse before replacing output. Shared native-plan guards also refuse
  unsupported raw pitch/retrigger effects. Tremolo-bar, harmonics, trill/picking, grace, swing/strokes/fade and
  notation exclusions remain. This qualifies pitched bends/vibrato/shift slides, not every technique/combination.
- *Measured standalone playback (no native plan).* At 48k: bend up/down 17.2863 cents /15.7010 ms, vibrato
  0.0209 cents /0.0008 ms, slide 32.8249 cents /22.4001 ms. At 44.1k: 17.2841 /15.6999, 1.7593 /2.6644,
  32.5106 /21.5792 respectively. Cents compare 20-ms pitch windows from interpolated sine cycles; milliseconds
  compare independent pitch-threshold crossings. Timing assertion includes half a row (20.8333 ms), one 441-Hz
  carrier cycle and at most one sample per elapsed IT tick. Native rational frames versus integer IT ticks explain
  the extra 44.1k drift. These are fixture measurements, not generic listening/parity claims. Bend peak 206.25 cents
  and neutral successor are retained within 0.03 cent; vibrato depth is 18.7446/18.7427 cents versus native
  18.7497/18.7536. Separate prebend descent stable-window error <=0.030 cent; existing pitch envelope + vibrato
  <=0.106 cent. Native musical event values/endpoints were not changed to obtain those results.
- *Checks.* 554 affected model/sync/pipeline tests pass (`scratch/tab-it-pitch-model.log`). Final 20 focused IT
  tests pass (`scratch/tab-it-pitch-export-pass.log`): original four-bars/repeats/percussion/gates, both voices,
  concurrent strings, tied repeats, raw notes/effects, mapping/envelopes, atomic refusals, reset ownership and tails.
  Real-control muted page enables bend curve, vibrato and slide, exports/reopens, checks visible warning and measured
  standalone pitch (`scratch/tab-it-pitch-page.log`). No edit semantics changed; existing pinned TG evidence reused.
- *Retained failures.* `scratch/tab-it-pitch-render.log`: a threshold exactly on a discrete pitch plateau counted
  PCM rounding jitter as transitions; thresholds now lie midway between steps. `tab-it-pitch-focused-final.log`:
  down-bend endpoint sampling at .47s was inside the .5s render-end fade, not a plain successor; fixture now appends
  an actual plain note, renders to 1s and measures .53s. Reader normalizes missing envelopes into disabled defaults;
  preservation assertions compare keymaps and active volume/pitch envelopes. `tab-it-pitch-focused.log` also retains
  malformed raw-row and old refusal-fixture failures. Passing checks did not loosen pitch limits to hide these.
- *Package.* All ten existing-runner checks pass in `scratch/tab-package-it-pitch/check-*.log`: four-bars, Fit,
  Place, GP5, capo, ordinary native IT, endings, percussion, prior techniques and pitch. Pitch IT reopens with four
  attacks, 96 rows and 3.999 s, independent PCM RMS/native 1.0011; the two-rate pitch metrics above also pass against
  the packaged export, with visible warning and neutral successor checked. Format smoke passes all seven exports
  and native GP2/GPX/GP imports (`scratch/tab-package-it-pitch/format-smoke.log`).
  Nine docs checks pass (`scratch/tab-it-pitch-docs.log`). No prior package or owner fixture was changed/rebuilt.
- *Files / handback.* Product: `vulturetracker/tablature.py`, `song.py`, `export.py`. Checks:
  `tests/test_tablature_sync.py`, `tests/test_tablature_page.py`, `tools/exe_check.py`. Records: this checkpoint,
  `GUIDE.md`, `CHANGELOG.md`, `TABLATURE-PARITY.md`. Current fixture/runner are
  `scratch/prepare-it-pitch-package.py`, `scratch/check-package-it-pitch.cmd`; the previous fixture prep is reused.
  Owner listening/editing-feel acceptance remains; no additional round queued.

**Previous local delivery (2026-10-22): `scratch/tab-package-it-techniques/vulturetracker.exe`**
(49,492,681 bytes, internal version 1.8.0; build `scratch/tab-it-techniques-build.log`). The owner's one Codex
worker completed this bounded playing-technique round and stops after handback. Claude and the older Codex workers/
automation remain stopped/paused. No commit, push, release, install or cleanup.
- *Supported tranche.* Ghost, accent, heavy accent and hammer-derived velocity; staccato, palm mute, dead-note gates
  and let-ring when their performed releases fit IT exactly. The strict projection consumes the existing native
  performance plan, including its TG gate precedence, tie-chain accounting, hammer lookup and repeat-close provenance.
  Dynamic velocity uses the existing sample-volume conversion. Releases use NOTE OFF at rows or NOTE OFF + SD1–SDf
  at exact sub-row ticks, following pinned `scratch/080/Snd_fx.cpp`'s delayed triggerNote/NOTE_KEYOFF path. Native
  playback and editing semantics are unchanged; no new interpreter, sample cut substitution or audio flattening.
- *Refusals.* A nonintegral IT tick, release sharing its attack cell, occupied delay/effect/volume fields, inherited
  note instrument/volume state, held same-channel overlap, unplayed technique pattern or occurrence-dependent reused
  pattern refuses before output replacement. Palm mute at 120 BPM fits; dead at 120 BPM does not (1.5 ticks), but
  dead at 160 BPM does. Existing pitch curves/vibrato/slides, layered harmonics, trill/tremolo picking, grace, swing,
  strokes, fade-in, tap/slap/pop and notation-only exclusions remain. This is not all playing-technique support.
- *Proven.* All eight flags have independent standalone libopenmpt render comparisons WITHOUT a native plan.
  At 48 kHz (integer ticks for tested 120/160 BPM), 10 ms window RMS differs by less than 6% of reference peak,
  including attacks, sustained notes and envelope release; SD1 palm-mute key-off is exercised. Model/export checks
  cover performed velocities, dead/palm/staccato precedence, ties, both voices, percussion, repeats, raw tracker
  attacks/releases/pan, source/history preservation and atomic refusals. The muted real-control page enables ghost
  and staccato, exports and reopens their expected volume/release cells, and compares actual standalone PCM energy.
- *44.1 kHz diagnosis.* Initial mixed-tone 10 ms RMS assertions failed near transient boundaries
  (`scratch/it-techniques-focused-tests.log`): IT rounds each audio tick while native event frames use rational
  time, shifting phase and release/transient windows. The retained isolated-tone check measures actual last audible
  frames, rather than loosening that RMS bound. Native minus IT drift is 11 samples (staccato), 3 (palm mute),
  0 (dead), 38 (let-ring), below calculated bounds 16/7/6/52: at most one sample per elapsed IT tick through the gate
  and envelope release, plus frame rounding. Maximum observed drift is 0.862 ms, not a general bound.
  `scratch/it-techniques-44100-tests.log` and the final focused log retain measurements.
- *Checks.* 549 affected model/sync/pipeline tests pass (`scratch/it-techniques-model-tests-final.log`), 15 final
  export tests pass (`scratch/it-techniques-export-tests.log`), 9 docs tests pass (`scratch/it-techniques-doc-tests.log`),
  and the muted technique-control/export page passes (`scratch/it-techniques-page-tests.log`). Initial obsolete
  blanket-refusal assertions are retained in `it-techniques-model-tests.log`; the malformed extra raw-note fixture's
  failure is retained in `it-techniques-raw-fixture-failure.log` and fixed by providing its full tracker rows.
- *Package.* Built once. All nine checks pass in `scratch/tab-package-it-techniques/check-*.log`: four-bars, Fit,
  Place, GP5, capo, ordinary native IT, endings IT, percussion IT and techniques IT. The technique module reopens
  with 22 attacks, 192 rows, 5.999 s; independently rendered RMS/native = 0.9973. The existing runner checks keymaps,
  instruments, attack timing/volume, source immutability and now technique audio. Format smoke also passes
  (`format-smoke.log`). Owner fixtures were copied; no prior package was changed or rebuilt.
- *Remaining acceptance / next action.* Listening and editing feel remain owner acceptance. IT retains 65 volume
  steps and integer audio-tick rounding; repeat expansion still has its 254-fragment limit. Another playing-technique
  tranche requires explicit selection; no additional worker work is queued. Rollback: `scratch/tab-package-it-percussion`.

**Previous local delivery (2026-10-22): `scratch/tab-package-it-percussion/vulturetracker.exe`**
(49,489,049 bytes, internal version 1.8.0; build `scratch/tab-it-percussion-build.log`). The owner authorized one
Codex worker for this percussion round; it is finished and stops after handback. The Claude worker and older
Codex workers/automation remain stopped/paused. No commit, push, release, install or cleanup was performed.
- *Implementation.* Removed the blanket percussion refusal from strict `project_score`; it keeps the authored key
  and uses the existing instrument/sample keymap and channel resolver. The shared compiler validates an actual
  mapped drum sample before conversion, including notes without velocity and tied continuations. CLI build and
  RENDER & EXPORT use the same path. No new drum interpreter or audio flattening; native playback is unchanged.
- *Proven.* Mixed guitar/drums, simultaneous hits and both voices, per-note instruments, keymapped and sample-mode
  kits, boundary keys 1/100, volume/velocity (including zero), repeats, existing guitar ties and raw tracker pan.
  Reopened editable IT notes, instruments, sample/playback-pitch maps and release times match the native plan;
  source/occurrence identities, file and history remain unchanged. Unmapped keys, channel collisions and invalid
  keys refuse without replacing an existing output. Independent libopenmpt PCM rendering WITHOUT a native plan
  checks actual selected sample pitch (441 Hz, a mapped D5 and octave-down C4), velocity gain, natural one-shot
  expiry and sustained drum envelope key-off against native playback. Frequency tolerance 15 Hz; RMS agreement
  within 4% (IT volume quantization/tick alignment); no listening claim.
- *Checks.* 545 affected model/sync/pipeline tests pass (`scratch/it-percussion-model-tests.log`), 9 docs tests pass
  (`scratch/it-percussion-doc-tests.log`). The muted real-control RENDER & EXPORT page passes for mixed drums and
  repeats (`scratch/it-percussion-page-tests.log`): 22 attacks, 192 rows, about 8 s, keymaps preserved and no source
  mutation. The previous ordinary/repeated four-bars model coverage is included in the model run.
- *Packaged checks.* All eight checks pass in `scratch/tab-package-it-percussion/check-*.log`: four-bars, Fit,
  Place, GP5, capo, native IT, native IT with endings, and mixed percussion native IT. Export checks reopen without
  a native plan and now compare note instrument routing and sample/pitch maps as well as attacks/volume/timing.
  The percussion runner initially compared simultaneous native ID order with IT channel order; sorting those
  same-time tuples fixed only the runner (`check-native-it-percussion-runner-failure.log` retained). The rerun
  then hit the existing-output guard; checking Replace previous exports safely for the harness's own copied
  fixture fixes repeat runs (`check-native-it-percussion-rerun-failure.log` retained). Only the affected check was
  rerun against the same executable. Format smoke passes (`format-smoke.log`). All owner
  examples were copied; the original four-bars and old preview directories were not changed.
- *Limits/next action.* This exports existing sample-based kits; it does not invent GM sounds or add external MIDI
  routing. Existing strict refusals still apply to unsupported techniques, off-grid timing, raw control flow and
  channel collisions. Repeats retain the 254-fragment limit, IT volume has 65 steps and audio ticks round to samples.
  Listening to the exported module in OpenMPT remains owner acceptance. Next implementation requires another
  selected feature. Rollback: `scratch/tab-package-it-repeats`.

**Previous local delivery (2026-10-22): `scratch/tab-package-it-repeats/vulturetracker.exe`**
(49,489,061 bytes, internal version 1.8.0; build `scratch/tab-it-repeats-build.log`). The owner explicitly authorized
one Codex worker for this repeats/endings round; the Claude worker and the older Codex workers/automation stay stopped.
- *Implementation.* Standalone IT now expands repeats and alternate endings through the same `_repeat_visits`,
  fragment/tempo backing and performed-tie mapping used by native playback. A disposable linear score feeds the
  existing strict `project_score` conversion; `song.py` adopts its patterns and orders together. Every generated
  pattern receives the normal compiler checks. CLI `build` and RENDER & EXPORT share this path. Each played fragment
  has an independent editable IT pattern so ties and releases can differ between visits. Authored orders, shared
  patterns, source file and history remain unchanged. Native playback and repeat-edit semantics were not changed;
  the existing pinned-TG traversal/oracle evidence applies.
- *Proven.* Counts, first/second and three-pass endings, repeated ties (no extra attacks), split measures and shared
  patterns, raw tracker notes/releases/pan and repeat-entry T53 tempo restoration. Exported modules reopen with the
  IT reader and libopenmpt WITHOUT a native plan; attack pitches/times and release times match the existing native
  plan within IT integer audio-tick rounding (at most one audio sample per tick). CLI build and UI export bytes agree.
  An unmatched performed tie leaves a pre-existing output intact; order/pattern overflow refuses without source
  mutation. Affected model/sync/pipeline tests: 541 OK (`scratch/it-repeats-model-tests.log`); final focused export/docs
  tests: 17 OK (`scratch/it-repeats-export-tests.log`, includes additional raw tracker notes test). Muted real-control
  pages: ordinary four-bars and alternate endings both OK (`scratch/it-repeats-page-tests.log`).
- *Packaged checks.* four-bars, Fit, Place, GP5, capo, native IT and native IT with endings all pass in
  `scratch/tab-package-it-repeats/check-*.log`. Repeated four-bars: performed bars 1,2,1,3,4, 20 attacks, 240 rows,
  13.333 s, v48; ordinary four-bars: 16 attacks, 192 rows, 10.667 s. All use copies of the owner example.
  The initial packaged run failed in the external test runner because a local Fraction import shadowed its module
  import (`check-runner-failure.log`); removing that redundant import fixed the runner. The same executable then
  passed, without another build. Format smoke: `format-smoke.log` in the package directory.
- *Limits.* The written repeat structure becomes a performed order sequence in IT; it is not a notation round-trip.
  Up to 254 played measure fragments are exported (one independent pattern each); the shared traversal also guards
  255 played orders. Off-grid fragments, skipped tie predecessors and other previously unsupported score features
  still refuse explicitly. IT volume remains 0..64 and audio tick timing has integer-sample precision. No claim of
  full notation/IT parity or listening acceptance. Next acceptance is listening to the exported module in OpenMPT;
  next implementation work can address another explicitly selected unsupported feature. Rollback: `scratch/tab-package-it`.

**Previous local delivery (2026-10-22): `scratch/tab-package-it/vulturetracker.exe`** (49,487,174 bytes, 1.8.0; build
log `scratch/tab-it-build.log`). Owner request: native scores must export a standalone IT, four-bars included.
- *Implementation, one shared path.* `api.compile_song` (strict compile: `tablature.project_score` writes the score into
  tracker cells, then `write_it`) is used by `build` and now by RENDER & EXPORT → IT and "include IT" for native
  scores (export.prepare, refusing a section/loop export of a native IT; the saved/current mix is patched in as for
  other IT exports). project_score now converts authored velocity (it refused before): the attack's volume column gets
  round(base × velocity / 127) half up, base = the note's volume or the default volume of the sample the IT plays
  for that instrument and pitch (song.py passes it). It matches native gain velocity/127 to IT's 65 volume steps
  (worst error ½ step, about 0.8 % of full scale; velocity 95 → v48, 64 with volume 32 → v16, 1 → v1). A release
  falling on the song's end needs no note-off (the module ends there; it refused before). Raw tracker cells the score
  does not own stay as they were; ties keep one attack.
- *Refusals (nothing written).* Notation an IT cannot hold refuses by name, as before: swing, strokes, fade-in,
  tap/slap/pop, playing techniques, percussion, lyrics, chord diagrams, repeats/endings, timing off the row grid, raw
  speed/jump/loop/row-delay commands, notes interrupting raw notes. A section/loop IT export of a native score
  refuses ("covers the whole song").
- *Proven.* `tests.test_tablature_sync.TestNativeStandaloneIt` (3): a mixed native/raw song reopened with the IT reader
  and libopenmpt and no plan (attack rows/pitches/volumes, note-offs, raw X40 kept, 96 rows, 4.0 s, song and history
  untouched). The export runner writes four-bars (16 attacks, v48, 192 rows, 10.667 s) and the same attacks after a
  3/4 re-flow. A swing measure refuses with no file written. The re-flow build test now checks the export runner
  writes bytes identical to `build`. Muted page `test_render_export_it_of_a_native_score_reopens_as_tracker_notes`
  (RENDER & EXPORT → IT: "done · 1/1 files", reopened contents) plus the TG page export (`scratch/it-page-tests.log`).
  Model 349, sync 153 and workflow 111 OK. Old tests that asserted the removed refusals now assert the conversion.
  `test_workflow`'s tied phrase capture now asserts the song stays untouched; capture itself works since the
  2026-10-21 tie-remap fix. `tools/exe_check.py --native-it` (with --browser and --song copy): packaged RENDER &
  EXPORT → IT on a copy of four-bars, reopened without a plan, 16 attacks equal to the source build, 10.667 s,
  `scratch/tab-package-it/check-native-it.log`. The other packaged checks (four-bars, fit, place, gp5, `--capo`) and
  the format smoke pass (`scratch/tab-package-it/`). The owner's four-bars.yaml was only copied (unchanged since 10-21).
- *Remaining acceptance.* Opening the exported IT in OpenMPT and listening (velocity as volume, last note ringing to
  the end) is the owner's; repeats/endings and the other refused notation still need native playback or MIDI.
  Recommended rollback: `scratch/tab-package-reflow`.

**Previous local delivery (2026-10-22): `scratch/tab-package-reflow/vulturetracker.exe`** (49,486,366 bytes, 1.8.0;
includes the testing-round source; build log `scratch/tab-reflow-build.log`). Owner decisions 2026-10-22: keep the
cross-bar Move beats (deliberate difference from TuxGuitar 2.1.0's runtime, documented in TABLATURE-PARITY CMD-04);
make the time signature match TuxGuitar by keeping note times and re-barring. The owner tested bars2 and free with no
problems; priority is compatibility with tracker/Pattern/IT export.
- *Time-signature re-flow (BAR-02).* `measure_meter` (Measures panel: a new meter, optionally "to the end") now follows
  TGSongManager.changeTimeSignature: the bar or bars take the meter, bar lines after it move, every note of every
  track keeps its time and lands in the bar it now falls in (patterns rebuilt, ties carried, IDs kept unless they
  collide), bars like the last are added at the end while the music needs them. One Undo, byte-exact. It refuses,
  changing nothing: a pattern from there on played at another order (make unique), residual tracker commands in the
  re-barred bars (they would move; tempo cells included), mixed tracker grids, a note straddling a new bar line (TG
  would leave it overfull), a meter not a whole number of rows. Raw tracker content outside those bars is untouched.
- *Validation.* State: the live engine's note-on frames are identical before and after, Pattern shows the moved note
  on its new row, the backing IT with its plan plays two quarters shorter as expected, bars are added with ties
  carried, refusals leave the file byte-identical (`tests.test_tablature_sync.TestMeasureMenuState`, 10 OK; model and
  sync 498 OK). Muted real-control pages: new `test_time_signature_to_the_end_reflows_notes_keep_their_times` (four-bar
  piece, 3/4 from bar 2 to the end: status, 5 bars engraved, Pattern row, onsets unchanged, byte-exact Undo) plus the
  measure, meter, free-edit, repeat and exact-measure cases (6 OK, `scratch/reflow-page-tests.log`); the rest of the
  page module is unchanged since the testing round's 169 OK. TuxGuitar oracle (`scratch/tg-edit-oracle.json`, `.log`):
  28 cases, 22 match (time signature grow, to-the-end and shrink-with-added-bar now match), 1 mismatch (Move beats
  left: the decided difference), 5 not comparable (TuxGuitar's dangling ties / overfull bars, unchanged). Packaged
  four-bars, fit, place, gp5, `--capo` and the format smoke pass (`scratch/tab-package-reflow/check-*.log`,
  `format-smoke.log`). Measured, not listened to.
- *Standalone IT (owner acceptance check, 2026-10-22).* `test_time_signature_reflow_standalone_it_build_keeps_note_rows_
  and_the_export_runner_refuses` runs the real `python -m vulturetracker build song.yaml -o x.it` before and after a
  2/4-to-the-end re-flow (score fixture without velocities or tracker commands). It reopens both .it files with the IT
  reader and libopenmpt: the same 6 attacks on the same absolute rows, channels and notes, and 96 → 72 rows. The
  module is 1.0 s shorter, matching 24 rows at speed 2 and 120 BPM. Limits, all refusals that predate this round and
  write nothing:
  (1) RENDER & EXPORT's IT format refuses any song with a native score plan ("Native score IT export requires an
  explicit notation-aware conversion; choose audio or MIDI"), re-flowed or not.
  (2) The standalone `build` refuses scores using native-only features, e.g. on a copy of the owner's four-bars:
  "authored MIDI velocity requires native playback; standalone IT conversion is not supported". The same goes for
  swing, strokes, fade-in and tap/slap/pop.
  So for typical imported or edited scores, IT output is the backing IT plus the native plan (live engine,
  WAV/MP3/stems), not a standalone .it.
- *Limits.* Re-barring a range with tracker commands, shared patterns or straddling notes refuses rather than moving
  them; a single-bar meter change still re-flows everything after it (as TG does). Not touched this round: free-mode
  duration/paste overflow, MIDI and other parity areas. Recommended rollback: `scratch/tab-package-free`.

**Testing round (2026-10-21, no build).**
- *Control coverage.* All 196 TAB buttons and input fields are driven by a page test. 179 already were; four new user-path
  tests cover the rest: track first/last, New track, enharmonic toggle, Setup maximum fret/instrument, Transpose's three
  option boxes, Measures Add after, all-tracks Copy, the occurrence pickers, meter denominator with "to the end", and
  Move beats left. The owner's past bugs each have one: Space/play button and TAB-staff marker
  (`test_owner_fixes_…`), panels closing (`test_every_side_panel_…`), tuning shown as names
  (`test_native_setup_note_name_…`), capo audible (`test_native_capo_spinner_…`, measured render/live pitch).
- *UI audit* (`test_ui_audit_panels_labels_note_names_layout_and_whole_score`, one muted page test on a four-bar piece):
  every panel closes by button, ✕ and Escape; every TAB button has text, a title or an aria-label; pitches read as note
  names; no toolbar control overlaps, clips or leaves the page at 1400 and 1180 px (the app's own minimum width:
  `#app` is 1180 px wide at least, narrower windows scroll the whole app); the whole piece is engraved (four bars).
  Score screenshot: `scratch/ui-audit/four-bars-score.png` (looked at: four bars, staff and TAB aligned, nothing clumped).
  Fixed: four places still showed MIDI numbers (grid string headers "1 · 64", the fretboard's tuning line, raw-note
  and unassigned-note labels); they now read E4, B3…
- *TuxGuitar editing oracle* (`tools/tg_edit_oracle.py`, with `tools/tg_edit_oracle/TgEditProbe.java`; 27 cases, results in
  `scratch/tg-edit-oracle.json`): **20 match** (fret entry, durations/dots/triplets, strict Insert rest with room and in a
  full bar, clean beat, remove unused voice, measure add/remove/clean/paste replace/insert, repeats and endings, time
  signature on the last bar, transpose, retune by a step and drop D, capo), **2 mismatch**, **5 not comparable**.
  Findings, none changed this round:
  1. *Move beats.* TuxGuitar 2.1.0 re-packs each bar after moving (TGMeasureManager.updateBeatsPreciseStart), so Move
     left deletes the caret beat and closes the gap inside that bar only, and Move right changes nothing visible (only
     an overflowing rest moves on). Here the track's beats move across bar lines, as moveTrackBeats' code reads. Owner's
     call: follow TuxGuitar's runtime result or keep this.
  2. *Time signature "to the end" with music after it.* TuxGuitar keeps every note at its time and moves the bar lines
     (later notes flow into the longer bars); here each bar keeps its own notes and gains empty time. Matching TG means
     re-barring the track across patterns (the Move beats machinery could do it); not built.
  3. *Dangling ties.* TuxGuitar leaves a tied note without its predecessor after removing, pasting over or free-inserting
     before a tie, or when an ending skips the tied bar; here those edits refuse (nothing is lost). Our .tg reader also
     refuses such TuxGuitar files ("tie needs an adjacent same-pitch predecessor"); importing them as untied notes with a
     warning would be the lenient choice.
  4. *Overfull bars from TuxGuitar.* Our .tg reader cannot import a bar TuxGuitar's free-edit mode left overfull.
  5. *Rest layout.* TuxGuitar fills gaps with rests (a new measure gets a whole rest; a shortened beat leaves rests);
     here gaps may stay implicit. Notes and durations match; only rest beats differ.
Checks: full `tests.test_tablature_page` 169 OK; model/sync/tg/docs OK.

**Current local delivery (2026-10-21): `scratch/tab-package-free/vulturetracker.exe`**
(49,281,405 bytes, 1.8.0).
1. **Free edit (CMD-06).** A "Free edit" checkbox beside Fit within measure (off by default, as TG's). With it on,
   Insert rest in a full bar works as TG's insertRestBeatWithoutControl: the track's later beats in the bar move right
   past its end. The model now accepts an overfull bar (span longer than its meter; shorter still refuses): the bar's
   pattern grows, the meter stays, and the header counts it as "too long (overfull)". Repair as in TG: remove what
   overflows, then Apply measure with its meter shrinks it back. Differences: TG sounds the overflow over the next bar,
   here the following bars wait; growing refuses unless the bar ends its pattern and the pattern plays once. Notation
   exports refuse an overfull bar with one message. Other free-mode edits (duration, paste overflow) stay open.
2. **Move beats (CMD-04).** "◀ Move beats" / "Move beats ▶" beside Insert rest: TG's moveTrackBeats, this track's
   beats (both voices) from the caret to the song's end move by the caret beat's duration, crossing bar lines with
   ties kept; left removes the caret beat first. One Undo. Per SYNC-04 a pattern from the caret's order on that plays
   at another order refuses until made unique; a beat straddling a bar line or passing the song's end refuses (TG
   would add measures). The custom-amount dialog is not built.
Tests: State (free edit, repair, export refusal, move right/left, shared refusal) and muted page cases; full
`tests.test_tablature_page` 164 OK; model/sync/tg/docs OK. Packaged four-bars, fit, place, gp5, `--capo` and the
format smoke pass (`scratch/tab-package-free/`). Measured, not listened to.
What to try on four-bars (TAB, editing on): tick Free edit, click bar 2's first note, press Ins → bar 2 gets longer,
the header reads "1 measure error", hover says "too long (overfull)"; Undo. Click bar 1's second note, ◀ Move beats →
it goes and the rest of the song slides left a quarter (bar 4 ends early); Undo. Move beats ▶ first needs room:
Measures → From 4 To 4 → Add after, then click bar 1's first note and Move beats ▶. Recommended rollback:
`scratch/tab-package-bars2`.

**Previous local delivery (2026-10-21): `scratch/tab-package-bars2/vulturetracker.exe`**
(49,272,965 bytes, 1.8.0). Owner: "the Measures panel can't be closed". Root cause: each side panel had its own
open/close code; Escape only knew the forms sharing Track setup's class, and Measures/Transpose had no ✕ or toggle.
Now all six panels (Track setup, Lyrics, chord diagram, bend/tremolo curve, Transpose, Measures) go through one
path in `web/tablature.js`: `togglePanel` for their buttons, `closePanel` (with each panel's own cleanup) for every
✕/Cancel/close action and for Escape, and one ✕ Close added to the top of every panel. New muted page case opens and
closes each panel by button, ✕ and Escape (one ✕ each, file unchanged); tests that reopen Measures use an
`open_panel` helper. Full page module re-run for the measure tests; packaged four-bars, fit, place, gp5, `--capo`
and the format smoke pass (`scratch/tab-package-bars2/`). Recommended rollback: `scratch/tab-package-bars`.

**Previous local delivery (2026-10-21): `scratch/tab-package-bars/vulturetracker.exe`**
(49,271,616 bytes, 1.8.0). Measure/structure round, TuxGuitar's Measure menu and headers:
1. **Measure ranges (BAR-01).** The Measures panel's top row: From/To/Count, Add before/after, Remove, Clean (this
   track), Copy (this track or all tracks), Paste (replace, extending at the end) and Insert paste; one Undo each.
   Measures are whole orders, as imported tabs are; songs whose measures divide a pattern refuse with a message, as do
   removing every measure and ties crossing the range. Shared patterns change at every order (the status says so).
   The old "Delete measure" is now "Clear entry" (it removes the entry, not notes or time).
2. **Repeats/endings (BAR-03).** Playback expansion was already in place. Endings are now eight checkboxes; endings
   taken since the last repeat start are disabled (TGRepeatAlternativeDialog), without TG's preselection.
3. **Time signature and tempo unit (BAR-02).** A meter of a new length on a whole-order measure resizes it and moves
   later measures ("to the end" option), refusing notes or tracker cells past a shortened end (TG moves them into new
   measures). Beat unit writes the tempo in eighths, dotted quarters…, notation only; `.tg` tempo base/dotted now import
   and export exactly (the old refusal is gone) and a stale unit refuses on export.
4. **Free edit mode (CMD-06): OPEN.** Strict stays the default, as in TG. Overfull bars cannot be stored (a bar's length
   is its pattern's rows), so Insert rest in a full bar still refuses. Measure-error inspection is built: the score
   header counts this track's bars with a gap or ending early; hover lists them.
5. **Live message.** A live reload superseded by a newer edit no longer shows "compile failed: Playback inputs changed";
   it retries quietly and reports only a final failure.
Also: the phrase "New comparison" no longer refuses a tied occurrence it makes unique (the clone keeps the tied note);
eight stale page tests were brought up to date; four unlisted GET routes added to the route test.
Owner request: four-bars.yaml set back to capo 0 through the app's retune (16 notes repitched, first note C-5,
16 notes, 10.66667 s, LF kept).
Checks: full `tests.test_tablature_page` 161 OK; model/sync/tg/docs/gui/workflow suites OK. Packaged: four-bars, fit,
place, gp5, `--capo` (now relative to the song's capo; from 0: C-5 → D-5, 261.8 → 293.6 Hz, two Undo steps) and the
format smoke pass (`scratch/tab-package-bars/check-*.log`, `format-smoke.log`). Measured, not listened to.
What to try (Measures button in the TAB toolbar): on four-bars, set From 2 To 2, Count 1, Add after → a blank bar 3;
Undo. From 2 To 3 → Copy, From 4 → Insert paste; Undo. Clean on bar 2 empties the guitar there. Pick a measure in
the panel, set meter 5/4 and Apply measure → that bar gains a beat (3/4 refuses: its fourth note would be cut); Undo. Beat unit eighth → the tempo line reads
"written 180 eighths per minute". On a repeat measure, tick endings 1 and 2, then open the next measure: 1 and 2
are greyed. Recommended rollback: `scratch/tab-package-fix3`.

**Previous local delivery (2026-10-21): `scratch/tab-package-fix3/vulturetracker.exe`**
(49,250,828 bytes, 1.8.0). The owner's fix2 retest: "Capo still does nothing." What was broken: the capo only took
effect on **Apply track** at the bottom of Setup; closing the panel (✕, Escape, the toggle button) discarded it. The
owner's four-bars.yaml and its history were not written after fix2 opened it at 10:47. Once applied, the model, file,
Pattern cells, live engine and render all followed. Now, per the owner's clarification, a capo change on an existing
track takes effect at once with no Apply. Each spinner step is its own Retune and Undo step, applied in order. Typed
digits settle for 0.6 s, so "12" is one step. Only the capo is sent; other unsaved Setup fields are left alone. The
fix3 package was rebuilt in place with this. New muted page case: two spinner steps, then Escape. It checks the file,
Pattern cell +2, the live engine's note_on pitches +2, the render fundamental ratio 2^(2/12), the label and two Undo
steps back to the exact bytes; a typed "12" is one step. With the listener removed (fix2's behaviour) it fails. New `exe_check --capo
--song <copy>` does the same against the packaged exe. On fix3 it passes on four-bars (C-5 → D-5, 261.8 → 293.6 Hz,
`scratch/tab-package-fix3/check-capo.log`); on fix2 it fails. The other packaged checks and the format smoke pass.
Measured, not listened to. Recommended rollback: `scratch/tab-package-fix2`.

**Previous local delivery (2026-10-21): `scratch/tab-package-fix2/vulturetracker.exe`**
(49,249,714 bytes, 1.8.0). Fixes from the owner's retest of tab-package-fix1:
1. **Tuning shown as MIDI numbers.** Setup now shows and accepts note names, top string first (E4 B3 G3 D3 A2 E2;
   numbers still work), with a Preset list: standard, Drop D, half/whole step down, DADGAD, open G/D, 7-string,
   4- and 5-string bass. Pitches are stored as before. Custom preset save/delete (TG's dialog) is not built.
2. **Capo did nothing.** Retune kept each pitch, so a capo change moved the frets down and the sound stayed. TG's
   offset keeps frets and playback adds it; now a capo change keeps every string and fret and raises the pitch by the
   capo (unit case checks the playback plan's note_on pitches +2). The score's header line shows "Capo N".
Muted page case (presets, note names, capo, byte-exact Undo) plus five Setup regressions pass; tablature unit suite
372 OK. Packaged checks and format smoke pass (`scratch/tab-package-fix2/check-*.log`, `format-smoke.log`).
Measured, not listened to. Recommended rollback: `scratch/tab-package-fix1`.

**Previous local delivery (2026-10-21): `scratch/tab-package-fix1/vulturetracker.exe`**
(49,249,590 bytes, 1.8.0; build log `scratch/tab-fix1-build.log`). Fixes from the owner's test of tab-package-edit:
1. **Space showed Play.** The top play button followed only the `<audio>` element; live-engine playback (Space,
   F5–F8, Play here) left it paused. It now shows ❚❚ while `LV.playing`.
2. **No playhead on the TAB staff.** The marker was sized from `findBeat` (the first staff only). It now spans
   every staff of the beat (`findBeats`), using finite bounds only.
3. **Insert rest refuses in full bars.** This matches TG: in normal mode its TGInsertRestBeatAction calls
   moveVoicesPrecise, which fails in a full measure, and leaves the bar unchanged. Only free-edit mode inserts, into an
   overfull bar, which VultureTracker does not model. Nothing was changed except the message, which now says so.
4. **Panels could not be closed.** Track setup and Lyrics now toggle from their buttons, have a ✕ Close at the
   top, and close on Escape (also from their fields).
5. **Tuning/capo hard to find.** The button reads "Track setup (tuning, capo)" and opens at the tuning field.
Also fixed: Retune now drops an imported source pan when channels change, as `track_set` already did; the
regression showed up in the source-pan Setup test. Test-only fixes: the `open_setup` helper for the toggling button,
the follow-tick stub in the hand-set-playhead tests, and a stale `pattern_rows` call. Page tests: the new owner-fix
test plus 31 Setup/lyrics/playhead/track regressions; the last rerun is `scratch/owner-fixes-last.log`. The model,
sync, syntax and docs suites are OK. Packaged checks pass, muted (`scratch/tab-package-fix1/check-*.log`, including
`check-formats.log`). Recommended rollback: `scratch/tab-package-edit`.

**Previous local delivery (2026-10-21): `scratch/tab-package-edit/vulturetracker.exe`**
(49,248,216 bytes, version 1.8.0; ffmpeg and zip alongside; build log `scratch/tab-edit-build.log`). It adds
everything after tab-package-ui listed below:
- Retune and Transpose.
- Insert rest (Ins).
- Staff click entry.
- TG line break, solo/mute and per-measure clef/key fields.

Focused suites: 717 OK (`scratch/edit-round-units.log`). Packaged checks pass, muted
(`scratch/tab-package-edit/check-*.log`):
- selfcheck;
- four-bars.yaml: 4 bars, 10.66667 s;
- `--fit` and `--place`: exact Undo;
- `--gp5-export`;
- `check-formats.log`: packaged CLI exports ly/musicxml/gp3/gp4/gp5/tab/tg 1.5 byte-equal, and imports .gtp, .gpx and .gp.

Open: move beats L/R; tempo base/dotted. `midiimport.py`'s unwired, untested section is still packed. Pillow is
absent as before. No visual, audio or listening acceptance.
Recommended rollback: `scratch/tab-package-ui` (the owner may override); the older packages are untouched.

**Previous local delivery (2026-10-20): `scratch/tab-package-ui/vulturetracker.exe`**
(49,242,150 bytes, version 1.8.0; `ffmpeg.exe` and `vulturetracker-win64.zip` alongside; build log
`scratch/tab-ui-build.log`, CPU lease). It is everything in "Source after tab-package-roll" below:
- ROLL hint, grid and drum names, and blank-click insert.
- TAB range durations, Remove unused voice and Clean beat, TuxGuitar default keys, and drag/Shift/extend selection.
- The playback-stop edit fix.
- Export formats gp3/gp4/ly/musicxml/tab and the TG legacy versions.
- `.gtp`/`.gpx`/`.gp` import, the TG open-path timing rule, and the pan-63 decision.
Pre-build unit sets: 711 tests, all OK except one intermittent Windows temp-cleanup lock in
`test_stroke_shared_voice_edit_pattern_agent_history_and_reopen`, which passed twice alone
(`scratch/prebuild-units.log`). Packaged checks pass, muted (`scratch/tab-package-ui/check-*.log`):
- selfcheck, including the new legacy readers, notation writers and notice;
- four-bars.yaml: 4 bars, 10.66667 s, the example unchanged;
- `--fit` and `--place`: exact Undo;
- `--gp5-export`: 1 measure, 12 notes;
- `check-formats.log`: the packaged CLI exports ly/musicxml/gp3/gp4/gp5/tab/tg 1.5 byte-equal to the source
  writers and imports a GP2 `.gtp`.
Limitations:
- Packaged `.gpx`/`.gp` import is source-tested only.
- `vulturetracker/midiimport.py` contains about 800 lines of trackerforge-4's **unwired, untested** MIDI
  score-import code. Nothing calls it, and `test_midiimport` passes 7/7 unchanged.
- Pillow is absent from the package, as in the earlier ones.
- Staff-click note entry (TG's edition mode), Insert rest and move beats are not built.
- No visual, audio or listening acceptance, and full parity remains incomplete.
Recommended rollback (orchestrator, 2026-10-20; the owner may override): `scratch/tab-package-roll`.
`scratch/tab-package-fit` and `scratch/tab-package-fret` stay untouched.

**Previous local delivery (2026-10-20): `scratch/tab-package-roll/vulturetracker.exe`**
(49,049,295 bytes, version 1.8.0; `ffmpeg.exe` and `vulturetracker-win64.zip` alongside). Built from this
checkout with `tools/build_exe.py --output-dir scratch/tab-package-roll` under the CPU lease
(`scratch/tab-roll-build.log`). It adds these three tranches to the previous delivery:

- **ROLL native-track scope** (`gui.html`). SCOPE offers Channel / raw or Native track, with a TRACK dropdown.
  Each source note across the track's channels and both voices is its own target, with overlap lanes and
  volume bars. Ghosts are read-only and refuse blank clicks. A drag is cancelled on a scope, track or revision
  change. Fixed: every edit's pattern reload briefly left `PAT.native` undefined, which forced the scope back to
  Channel; it now forces Channel only when `PAT.native===false`. 3 new muted page cases and 12 existing ROLL
  regressions pass. Two older roll-move tests were stale against the exact-row model (`[n,d]` rows; native notes
  are in the score plan, not module cells), not broken by ROLL, and were updated
  (`scratch/native-roll-track-{first,second,third,regressions,stale-fixed}.log`; the first two keep the failures).
  Later consolidated runs exposed a test-only race: `#rollscroll`'s onscroll re-renders the roll, which detached
  a Playwright handle during `scroll_into_view_if_needed` (`native-roll-track-final{,2}.log`). The ROLL tests now
  scroll through a fresh in-page query (`roll_scroll`, `block:'nearest'`); no app code changed and no rebuild was
  needed. Final: 17/17 OK twice on the current `gui.html` (`native-roll-track-final3.log`, `final4.log`).
- **Peer-only destination fitting** (`tablature.py`). No UI change was needed: it reports the existing `shifted`
  outcome. A new page case drives it through the real Fit control, and one Undo restores the bytes
  (`scratch/native-peer-fit-ui.log`). The earlier 33 model/State results are reused.
- **GP5 uniform fade-in and tap/slap/pop** (`gpexport.py`). The production oracle passed (worker trackerforge-3,
  CPU lease, exit 0): 20 note, 0 pitch and 583 CC11 callbacks, 6 fade ramps, and exact rewrite/mixer/round-trip
  (`scratch/native-gp5-beat-flags-production.log`). Its 11 focused tests pass. `gpexport.py` and
  `tests/test_gpimport.py` were handed back to the integration owner.

Packaged checks pass, muted under the heavy lease, in `scratch/tab-package-roll/check-*.log`:
- selfcheck: packed `gui.html` 429,585 bytes and `tablature.js` 243,544 bytes, equal to the source.
- `four-bars.yaml`: all 4 written bars retained, rendered and written ending both 10.66667 s; the example is unchanged.
- `--fit` and `--place`: exact Undo.
- `--gp5-export` on a copy of the tremolo-bar song: 1 measure, 12 notes, 8 whammy curves, 3 vibrato.
Documentation tests pass 7 (`scratch/roll-peer-docs.log`).

Known limitations:
- **GP5 beat flags:** fade-in/tap/slap/pop have no packaged checker case; the exporter's production oracle covers them.
- **ROLL hint (fixed in source after this package):** when a reload turned out non-native, the scope flipped to
  Channel but `#rollhint` kept its old text. The hint now updates and the scope version is bumped, so a held drag
  cancels (`test_native_track_roll_non_native_reload_resets_scope_and_hint`; 5/5 in `scratch/roll-hint-tranche.log`).
- **Not in this package:** grid divisions, drum row names and native blank-click insertion. They were added in
  source afterwards (see "Source after tab-package-roll" below).
- **Acceptance not claimed:** foreground visual, hardware audio and listening acceptance, and full TuxGuitar parity.
Rollback (owner's decision, 2026-10-20): the selected rollback is `scratch/tab-package-fit/vulturetracker.exe`; the
current delivery is `scratch/tab-package-roll/vulturetracker.exe`. `scratch/tab-package-fret` is no longer the selected
rollback but stays untouched, as do the older packages: no deletion or cleanup is authorized. No commit, push or release.

### Source after tab-package-roll (bounded parity tranches, 2026-10-20)

The owner authorized bounded parity tranches, one at a time; no package is built per tranche. The plan is
`scratch/native-roll-matrix-tranche-plan.md`.
- **(a) ROLL hint on a non-native reload.** Fixed; see the limitation note above.
- **(b1) Grid divisions and drum row names.** Native-scope GRID (1/2/3/4/6/8/16, default 2, invalid saved value →
  2, kept in localStorage) draws guides per meter beat. The guides come from the TAB's own timeline, now exposed
  as `VultureTab.timeline` on a separate line so the Node hooks still match. Percussion rows show the pinned
  TuxGuitar names for keys 27–87 (added to the TuxGuitar notice) and skip scale shading. 2 new muted page cases plus
  17 ROLL regressions pass (`scratch/roll-b1-first.log`, where the first drum run failed on a test-helper note
  count; `roll-b1-drums.log`). `TestTablatureSyntax` passes 23 (`roll-b1-syntax-fixed.log`). One stub there was
  stale since the fretboard tranche: `markPlayhead` uses `board`/`piano`, which the stub did not declare
  (`roll-b1-syntax.log`); test-only fix.
- **(b2) Native blank-click insertion.** A left click on blank space in native scope sets the TAB editor's
  selection to the GRID line at or before it (rational, from the timeline), then calls `SCORE.editor.enterPitch`.
  That reuses strict Place, the duration controls, string allocation, refusals and one Undo. It first refreshes
  the TAB view to the current song version; the first run showed a stale view after Undo refusing a valid
  insert. A same-pitch onset refuses instead of toggling another voice's note off. The voice is the track's last
  selected note's voice, else voice 1. The grid floor is a documented difference from TG's containing-beat hit.
  The ROLL test helpers now read rects by fresh query; the first run hit a re-render race. Results: 1 new case,
  the updated ghosts/blank case and 18 ROLL regressions pass twice (`scratch/roll-b2-second.log`,
  `roll-b2-repeat.log`; the failures are in `roll-b2-first.log`). A later case covers voice-2 inheritance and a
  percussion blank click (key 38 = fret 38): `test_native_track_roll_blank_click_voice_2_and_percussion_key` passes
  with the blank-click test (`scratch/roll-b2-voice-drums.log`).
- **(c) CMD-05 duration on a beat range.** +/− already matched TG: halve/double between whole and 64th, clear
  dots, keep the tuplet. TG's `TGSetDurationAction` (pinned source, fetched) applies the duration to every beat of
  the selected range, while we changed only the caret beat. New `score_command` action `set_duration`
  (`tablature.py`): each selected beat of one track/voice takes the duration in time order through the existing
  Place, or tg_duration fit when Fit is on, as one candidate. Any refusal writes nothing. The TAB sends it when
  more than one beat of the current voice is selected; single beats keep the old path. Model: 4 new tests; the
  range result equals single-beat commands applied in order. 26 Place/Fit model tests pass
  (`scratch/set-duration-range-model.log`). Page: 1 new case plus 15 entry/duration regressions pass
  (`scratch/set-duration-range-page2.log`).
  Three older duration tests were stale and are fixed (`set-duration-range-page.log`, `stale-duration-tests.log`):
  they indexed beats by list position, which Place's re-append changed, and one read hidden text after reload.
  Not done: the agent tool description still names only cut/repeat; ties and bar overflow are not re-verified
  for ranges.
- **(d) CMD-06 Remove unused voice.** Stems were already authored, per beat and per track. A new
  `remove_unused_voice` score command follows the pinned `TGRemoveUnusedVoiceAction` and `removeMeasureVoices`
  (fetched). It takes the last voice that is empty or a rest at every selected onset, then removes that voice's
  rests in each touched measure without a note of that voice. Measures use Place's bounds; annotated rests refuse;
  one transaction. A TAB button "Remove unused voice" works on the selected beats, else the caret's beat. Model:
  4 new tests, 28 with the Place classes (`scratch/remove-unused-voice-model.log`). Page: 1 new case plus 5
  regressions (`scratch/remove-unused-voice-page.log`). `TestTablatureSyntax` passes. Still open in CMD-06: free
  editing mode and measure-error inspection.
- **(e) CMD-04 Clean beat.** A new `clean_beat` score command follows the pinned `TGCleanBeatAction`/`cleanBeat`:
  both voices of the track at each selected onset become rests of the same durations without text, chord or
  strokes, in one transaction. Tied notes refuse via `_delete_incident_ties`. A TAB "Clean beat" button shares
  the selection helper (`beatsCommand`) with Remove unused voice. Model: 2 new tests, 30 with the neighbouring
  classes (`scratch/clean-beat-model.log`). Page: 1 new case plus 4 regressions (`scratch/clean-beat-page.log`).
  Left open, recorded in PARITY CMD-04: Insert rest (a `moveVoicesPrecise` port) and move beats left/right/custom
  (`moveTrackBeats` shifts the rest of the track across shared patterns).
- **Ownership change (2026-10-20, orchestrator):** the tg-format, gp-formats, notation-export and model-commands
  workers own their files (tgimport/tg*.py; gpimport/gpexport/gp*.py and test_gpimport; notation_export; tablature.py,
  chord_tools.py, test_tablature.py, test_tablature_sync.py). The integration owner released tablature.py and keeps
  the UI, page tests, docs, CI list and wiring. Model changes go through the orchestrator.
- **(g) CMD-01/EDIT-01 TuxGuitar default keys** (UI only, `web/tablature.js`). Bound from the pinned
  `dist/tuxguitar-shortcuts.xml`: `*` dotted toggle (double dot clears), `/` normal↔triplet, x/o/h/p/s/v/f
  techniques (with percussion refusals), Ctrl+Delete clean beat, Ctrl+1/2 voice, Ctrl+A select all (track, both
  voices, shown pattern) and Alt(+Shift)+←→ markers. `test_native_tuxguitar_default_keys` passes; the first two
  runs failed on fixture details (velocity for hammer; hammer clears dead), logged in
  `scratch/tab-keys-{first,second,third}.log`, with 5 regressions OK in `first`. Not bound: Ins and Ctrl+↑↓ (no
  model op) and the a/t/b/g dialogs.
- **(h) EDIT-01 drag selection** (UI only, `web/tablature.js` and `.css`). The hit resolution is shared as
  `scoreHit`. A drag past 6 px selects every beat of the track, both voices, from the pressed beat to the hovered
  one, within the shown order (TG: `TGStart/UpdateDragSelectionAction`, `Selector`). Selected beats are shaded on
  the engraved TAB (`.vt-tab-selection`). `test_native_tab_drag_selects_the_beat_range_and_shows_it` passes
  (`scratch/tab-drag-final2.log`), and 5 score-hit/key regressions pass (`tab-drag-final.log`). The earlier
  failures were test setup: alphaTab not loaded, and a count that missed Place's fill rests.
  **Pre-existing bug found and fixed:**
  `test_score_playback_follow_orders_manual_edits_and_muted_transport` failed (`tab-drag-{first,third}.log`; it also
  failed at 09:21 in `scratch/tab-preview-ui-tests-first.log`). After Stop, the TAB kept its playhead until the
  page's next 100 ms tick and refused edits ("Wait for editing to be available") until then. Calling
  `SCORE.editor.setPlayhead(null)` made it pass (`playback-follow-exp.log`). The fix is in `lvStop`
  (`gui.html`), which now tells the TAB at once. That test plus 7 transport/playhead tests pass
  (`scratch/playback-stop-fix.log`).
- **(i) EDIT-01 extend/clear selection** (UI only, `web/tablature.js`). A Select row (|◀ ◀◀ ◀ ▶ ▶▶ ▶| All None)
  follows the pinned `TGExtendSelection{Left,Right,Previous,Next,First,Last}Action` and `TGClearSelectionAction`.
  It keeps the anchor (shared with drag and Ctrl+A) and moves the caret; measures come from `printTimeline`, and
  the range stays within the shown pattern. `test_native_extend_and_clear_selection_buttons` passes with 4
  selection/range regressions (`scratch/tab-extend-first.log`). Shift+click on the engraved TAB extends from the
  anchor or caret, per TG MouseKit (`test_native_tab_shift_click_extends_from_the_anchor` with 4 regressions,
  `scratch/tab-shift-first.log`). Next candidate: TG's default edition mouse mode, staff click add/remove pitch
  (TGMouseClickAction + EditorKit.fillCreateNoteContext); its pitch-from-staff mapping needs reading first.
- **TestNativeTg fixture fixed:** trackerforge-4 confirmed its 15:56 `tgimport.py` refusal is right. Per the pinned
  TG, opening a file closes holes in every voice (`TGMeasureManager.updateBeatsPreciseStart`), so the old export
  of that fixture opened with its last eighth at quarter 2. `TestNativeTg.state` now adds a voice-0 dotted-quarter
  rest at [2,1]; all 5 tests pass (`scratch/native-tg-fixture-rest.log`).
- **(j) Format wiring for the format workers (orchestrator request, 2026-10-20).** export.py now has `NOTATION`
  and `FORMATS`. New exports `gp3`/`gp4` (`gpexport.native_to_gp`), `ly` (with LilyPond settings) and `musicxml`
  (`notation_export`), plus `tg` with `tg_version` 1.0–1.5 (`native_to_tg(version=)`). They are wired through
  RENDER & EXPORT (menu; the app uses LilyPond defaults), the CLI (`-f`, `--tg-version`, `--lilypond KEY=VALUE`)
  and the agent tool (`tg_version`, `lilypond`). Text is UTF-8 with LF. Each report's losses become `<FMT> loss:`
  export warnings. `.gtp` (GP1/GP2, `gplegacy` through `import_gp`) is routed in `gui.GP_SUFFIXES`, the CLI
  import/`--native-tab`, the file dialog and the import box. Licensing: new
  `vulturetracker/licenses/TuxGuitar-notation-NOTICE.txt` (draft minus its ASCII lines, plus `asciitab.py`'s
  sources), a THIRD_PARTY row, and the `TuxGuitar-scales-NOTICE.txt` digest updated after the drum-names edit
  (`test_vendor` had failed on it; the b1 tranche had not run it). The exe selfcheck now lists the legacy
  readers, the notation writers and the notice. Tests: `tests.test_workflow.TestNotationExportWiring` 4 OK
  (`scratch/notation-wiring-final.log`: byte equality with each writer for ly/musicxml/gp3/gp4/gp5/tab, tg 1.5,
  LilyPond settings, refusals, loss lines, CLI, agent enum, `.gtp` through app and CLI import). Export-related
  regressions fail only on the known items (`notation-wiring-regressions.log`). PARITY LAYOUT-03 and IO-01/02/03/04/09
  updated. The CI-list change is prepared (`apply_ci_list.py` in the session artifacts) and waits for the owner's
  AGENTS.md approval.
- **GP ownership moved to the integration owner (2026-10-20):** trackerforge-5 closed; I own gpimport/gpexport/
  gplegacy/gpx.py and their tests. I applied trackerforge-4's tranche 4a/4b test changes in `test_gpimport.py`, each
  checked against the ratified TG rule:
  - the staggered TG fixture gets a voice-2 eighth rest at 0;
  - an off-origin first beat now imports with a "moved" notice instead of refusing;
  - the percussion tie test uses a different predecessor key instead of a gap that TG closes;
  - an E♯♯ spelling still refuses, while F♯ (the 1-flat key's alternative) now exports.
  `test_gpimport` passes 130/130 (`scratch/gpimport-after-4a.log`; before: `gpimport-before-4a.log`, 5 failures).
  `.gpx` (GP6) and `.gp` (GP7) are routed like `.gtp`; `TestNotationExportWiring` passes 5/5 (`scratch/gpx-wiring.log`).
- **Owner decision (b), 2026-10-20: centred source pan binds 63.** `gpx.py` (GP6/GP7) binds 63 instead of TG's
  default 64, and `gplegacy.py` maps a raw centre 64 to 63 (other raw values unchanged), as GP3–5 imports do, so
  GP3/4/5 export accepts these imports. This is a deliberate one-step CC10 difference from TuxGuitar, recorded in
  GUIDE and PARITY IO-03/IO-05. New tests `test_centre_pan_binds_63_like_gp3_to_gp5` (gpx) and
  `test_centre_balance_binds_63_like_gp3_to_gp5` (gplegacy); test_gpx + test_gplegacy + test_gpimport pass 147
  (`scratch/pan63-final.log`). Deferred until after the build: trackerforge-7's retune UI wiring request.
- **(k) Retune wiring (after tab-package-ui).** Setup sends `score_command` `retune` when an existing track's
  tuning, strings, capo or max fret change. A new "Retune keeps pitches/frets" option defaults to pitches, as
  TG's tuning change does. A `track_set` follows only if other Setup fields changed. The status lists the
  result (moved, repitched, chords removed/transposed, spellings cleared). The page case passes for both keep
  modes with byte-exact Undo, plus the percussion Setup regression (`scratch/retune-ui2.log`).
- **(l) Transpose dialog (after tab-package-ui).** A TAB "Transpose…" form sends `score_command` `transpose`
  with TG's defaults: whole track, all tracks, chords, keep strings; or the caret's measure. The page case
  passes (+2 keeps strings, frets +2, out-of-range sends nothing, byte-exact Undo; `scratch/transpose-ui.log`).
  Retune and transpose are not in any package yet.
- **(m) CMD-04 Insert rest.** New `score_command` `insert_rest`, a port of the pinned TGInsertRestBeatAction and
  moveVoicesPrecise, outside free-edit mode. The TAB has an Ins key and an Insert rest button. Model: 4 tests; page: 1 test plus
  the keys regression (`scratch/insert-rest-ui.log`). **Open: move beats L/R** (moveTrackBeats crosses measures,
  deletes on left moves and creates measures; shared patterns need occurrence uniquing), recorded in PARITY CMD-04.
- **(n) Staff click entry** (UI only, `web/tablature.js`): TG's edition mouse mode, a Staff click option
  (enters notes / sharps-flats / selects, saved per app). The page case adds and removes G4 by clicking its line,
  and select mode makes no edit (`scratch/staff-click-final.log`); the drag and selection-transport regressions
  pass (`staff-click-first.log`).
- **(o) TG 2.0 fields as native fields.** New model fields: measure `line_break` (bool) and `staff:
  {track: {clef?, key?}}`, and track `solo_mute` ('solo' or 'mute'), all validated. `tgimport` reads and writes
  `lineBreak`, `soloMute` (after name, as TG's writer) and per-measure clef/key, replacing the by-element
  refusals. The engraving draws clef/key changes. `tglegacy` lists line break and solo/mute as losses (1.x per-measure
  clef/key were already written). Undo/preservation come from the shared score edit path. Tests:
  `TestTgHeaderTrackFields` 2 (read/write/read equality, validation). Focused suites 717 OK
  (`scratch/edit-round-units.log`). No oracle run (the fields are TG's own tags, so it was not cheap enough to
  justify). **Open:** tempo beat unit/dotted base needs a tempo model field.
- **IO-01 status:** TG 2.0 read/write already exists (`tgimport.py`, `TestTgInterchange` and about 30 TG tests);
  the PARITY row's "M" is stale.
- **(f) IO-09 ASCII tab: built, ownership pending.** `vulturetracker/asciitab.py` ports TG's
  `ASCIITabOutputStream`/`ASCIIOutputStream` over the TG 2.0 XML our `.tg` export writes. Output is LF; TG writes
  the platform separator. It is byte-identical to the installed TuxGuitar 2.1.0's writer on 5 files
  (`scratch/native-ascii-oracle`: `run3` has the dense fixture plus 3 package songs; `literal` has the
  TestTgInterchange fixture). That includes line wrap, two tracks, 6/8, 3:2 and 7:4 tick truncation, chords, dead
  notes, h/p, slides, bend/release and hold. It is wired as export format `tab` (export.py, CLI, agent tool,
  export select). Tests: `TestTgInterchange.test_ascii_tab_matches_tuxguitar_writer_byte_for_byte` and
  `TestNativeTg.test_ascii_tab_export_is_tuxguitars_writer_on_the_tg_score` pass.
  **Conflict:** at 15:35 another worker created `notation_export.py` (ASCII/LilyPond/MusicXML), `gplegacy.py`,
  `tglegacy.py` and their tests in this checkout. The orchestrator was asked to choose keep-mine or use-theirs
  for ASCII and who owns export.py/`__main__.py`/agent.py. File-compatibility edits are paused until it answers.
  `test_docs.test_ci_runs_every_test_module` now fails on that worker's three unlisted test modules
  (AGENTS.md/CI list).

### Coordination (2026-10-19; historical, Codex assignments paused 2026-10-20)

The owner authorized this chat to orchestrate and create sessions as needed through completion. Lead chat:
`01a15753-2e11-7563-841f-200a2e70b4b5` (Add full tablature editing). The lead owns integration, shared schema/API
decisions, `song.py`, `gui.py`, `gui.html`, `server.py`, existing shared mutation paths, final validation and this
status. Workers share this checkout and have disjoint writable paths; do not switch branches or commit under them.
The existing commit/push/release approval requirements still apply. Preserve the unrelated Rift build log.

| Session | Current assignment | Exclusive writable paths |
|---|---|---|
| `01a15757-4301-75b0-8974-3c08a17143cd` - Tablature shared model and timing | Single-voice partial fit delivered; implement qualified peer-only destination reuse | `vulturetracker/tablature.py`, new TestPlacePeerFit classes and specifically obsolete fit expectations in model/sync tests; own scratch handback |
| `01a15757-666f-7362-b11e-67e7bb6ccd44` - Tablature native editor and engraving | Fit UI delivered; extend ROLL with explicit native-track scope and source-ID targeting | ROLL functions/toolbar only in `gui.html`, related page cases; own scratch handback. Checker returned to lead |
| `01a15757-8f49-7ab2-8554-e85870282e4a` - TuxGuitar parity and acceptance inventory | Whammy curves delivered; implement uniform GP5 fade-in/tap/slap/pop ownership | `vulturetracker/gpexport.py`, dedicated GP beat-flags class and affected older expectations in `tests/test_gpimport.py`; own scratch handback |

The lead reads worker completion with `wait_threads`, resolves dependencies, then sends bounded follow-up work.
Workers do not ask the owner to manage integration or edit another worker's files. This table is the current
coordination record; the parity inventory is the detailed feature checklist. Earlier PHRASES, print and core-engine
paths are returned to the lead. Current follow-ups are exact native editor integration, raw preview/adoption and
matched native/WASM parent-batch qualification.
The model worker completed the isolated playback-preparation tranche in `api.py`, `song.py`, `model.py`,
`itwriter.py` and `tests/test_tablature_sync.py`; those paths are handed back to the lead.

### Current implementation and checks

- **Previous local delivery, selected rollback (owner's decision 2026-10-20):** `scratch/tab-package-fit/vulturetracker.exe`
  (49,248,224 bytes; ffmpeg/archive alongside). Optional, initially unchecked Fit within measure now
  routes existing-beat duration edits and duration-changing piano additions through supported fitting.
  It reports shifted/exact/old-duration/unchanged outcomes and updates duration controls without
  retargeting the caret. Qualified single-voice partial fits can move or resize later plain notes;
  protected notation and unsupported peer/rebuild cases refuse. Strict entry remains the default.
  Model/State checks pass25 plus the2 corrected older expectations
  (`scratch/native-rest-partial-final-tests.log`, `native-rest-partial-integration-final.log`).
  UI passes2 new fit cases and3 piano/Place regressions (`scratch/native-fit-ui-final.log`,
  `native-fit-ui-regression.log`); initial fixture ordering/inspector failures are retained.
  GP5 vibrato/hammer actual output matches58 pitch/56 note callbacks and exact rewrite metadata;
  seven feature/regression tests plus root's4+1 integration checks pass, including corrected older
  unsupported assertions (`scratch/native-gp5-vibrato-hammer-handoff.md` and linked logs).
  Uniform per-voice whammy curves pass15 focused tests and actual-exporter comparison of894 pitch/
  20 note callbacks with exact saved/rewrite metadata (`scratch/native-gp5-tremolo-bar-plan.md`).
  Documentation passes9 (`scratch/fit-bar-docs.log`); CPU build passes (`scratch/tab-fit-build.log`).
  Heavy-queued package/selfcheck/muted browser checks pass (`check-fit.log`, `check-tremolo-bar.log`
  in the delivery directory). Actual checkbox/duration edit shifts through a whole rest, Undo restores
  exact bytes, and an unchanged command preserves revision/history/redo. Actual page GP5 export
  reads back1 measure/12 notes with8 whammy curves and3 vibrato flags; SONG ends at2s.
  No hardware audio, foreground visual or listening acceptance is claimed. Audio settings unchanged.
  Selected rollback is `scratch/tab-package-fret/vulturetracker.exe`; older protected packages remain.
  Full parity remains incomplete. No commit, push or release. Next production assignments are above.
- **Working integration after tab-package-fit (now in tab-package-roll, see above):** peer-cohort fitting has a retained source/runtime
  contract distinguishing duration realignment from insertion. ROLL native-track scope must preserve
  raw and foreign ghosts. GP5 beat flags have scratch qualification of20 note and583 CC11 callbacks
  across6 fade ramps (`scratch/native-gp5-beat-flags-plan.md`); actual exporter qualification remains
  required after implementation. None of these follow-up changes is in the current executable.
- **Previous local delivery (2026-10-20):** `scratch/tab-package-fret/vulturetracker.exe`
  (49,245,468 bytes; ffmpeg/archive alongside). Direct native fret typing and fretboard new-beat
  insertion now use strict rest placement. Rapid12 and drum100 retain their source identity; queued
  digits accept only the immediately preceding own successful revision, cancelling stale navigation,
  external edits and failed predecessors without undoing completed digits. Six focused muted page
  cases pass (`scratch/fret-place-first.log`, `scratch/fret-place-final.log`).
  GP5 export now includes nonempty bend curves and shift slides, refusing destructive combinations.
  Eight focused GP tests pass; actual exporter output matches69 pitch and28 note callbacks and exact
  saved/rewrite metadata (`scratch/native-gp5-remaining-effects-plan.md` and linked results).
  Root fixed unchanged score commands to return before YAML serialization: no write, history entry or
  lost redo branch. Nine fit model/State checks pass (`scratch/native-rest-fit-integration-final.log`);
  the initial failing result remains. Scoped movement/fallback review found no actionable issue
  (`scratch/native-rest-fit-review.md`). Optional exact-fit movement/fallback is backend-only:
  current editor calls remain strict, and partial-fit movement still refuses.
  Documentation checks pass9 (`scratch/fret-fit-docs.log`); CPU build passes (`scratch/tab-fret-build.log`).
  Heavy-queued actual package/selfcheck/muted browser checks pass (`check-place.log`,
  `check-bend-slide.log` in the delivery directory). Packaged rapid12 inside a rest retains exact
  IDs/caret/rest partitions and both per-digit Undo states; final Undo restores the original bytes.
  Actual page GP5 export reads back1 measure,15 notes,2 bend curves and4 slide flags. Source and
  native/WASM assets load without page errors; the test score ends at2s. No hardware audio,
  foreground visual or listening acceptance is claimed. Audio settings are unchanged.
  Selected rollback is `scratch/tab-package-rest/vulturetracker.exe`; protected older packages remain.
  Full parity remains incomplete; next assignments are recorded above. No commit, push or release.
- **Previous local delivery (2026-10-20):** `scratch/tab-package-rest/vulturetracker.exe`
  (49,238,791 bytes; ffmpeg/archive alongside). Piano insertion and native duration controls now use
  the exact bare-rest Place command: split/consume active-voice rests as one edit, preserve returned
  caret/source identities, clipboard and later notes, and refuse protected annotations/ties/overlap.
  Seven focused muted page cases pass; `scratch/native-piano-plan.md` links the failure and final
  results (`piano-place-final.log`, `piano-place-direct-final.log`, `piano-place-identity-final.log`).
  The first fixture failures were inspector visibility and controller-only selection; both corrected.
  Prior15 model/State checks and independent rest review remain applicable. Documentation passes9
  (`scratch/rest-docs.log`). CPU build passes (`scratch/tab-rest-build.log`).
  Heavy-queued actual packaged/selfcheck/muted browser checks pass (`check-place.log` and
  `check-four-bars.log` in the delivery directory). The optional existing checker `--browser --place`
  creates its own temporary fixture and rejects `--song`: an actual piano-key click splits a bare
  rest, retains exact source IDs/caret, and one Undo restores identical file bytes. The unchanged
  four-bar example retains all4 written bars and renders10.66667s. No hardware audio, foreground
  visual, listening acceptance or full parity is claimed. Audio settings were not changed.
  Direct fret typing still uses the previous insertion path; the worker above is bringing it onto
  strict Place and fixing captured-intent guards without breaking rapid multi-digit entry.
  Following-note movement, duration fallback and broader parity remain absent from this package.
  Selected rollback is `scratch/tab-package-piano/vulturetracker.exe`; older protected packages remain.
  Open this executable and the unchanged `scratch/tab-audio-review/balanced-example/four-bars.yaml`.
  No commit, push or release.
- **Fit/bend source qualification behind the current delivery:** installed manager probes qualify exact-fit
  note movement and insufficient-space insertion fallback/duration no-op. Partial fit unexpectedly
  lengthens the moved note as well as moving it; it must remain refused until reproduced faithfully
  (`scratch/native-rest-edit-plan.md`). GP5 bend/slide mapping retains69 pitch and28 note callbacks,
  exact bend point order and rewritten metadata; negative files prove dead/bend/slide normalization
  hazards (`scratch/native-gp5-remaining-effects-plan.md`). The later actual-exporter qualification
  is recorded in the current delivery above. Source ownership and next work are in the table.
- **Previous local delivery (2026-10-20):** `scratch/tab-package-piano/vulturetracker.exe`
  (49,237,631 bytes; ffmpeg/archive alongside). Adds optional native piano entry using the shared exact
  caret/revision, both voices, capo-aware string allocation, pitched keys0–119 and drum keys1–100.
  Direct engraved TAB remains primary. Four focused piano cases pass (`scratch/native-piano-final.log`);
  the corrected cross-track highlight case passes (`scratch/native-piano-track-verified.log`).
  GP5 export now retains seven note flags, natural/artificial harmonic data0, trill16/32/64 and
  tremolo-picking8/16/32. Seven-flag checks pass17 (`scratch/native-gp5-effects-export/final-tests.log`);
  pitched effects pass4 plus3 flag regressions. Installed TG callbacks and saved/rewrite metadata match:
  `scratch/native-gp5-effects-implementation.md`, `scratch/native-gp5-effects-plan.md` and
  `scratch/native-gp5-pitched-effects-plan.md`. Artificial harmonic export warns about canonical GP5
  payload and potentially different interpretation in other players; unsupported combinations refuse.
  CPU build and heavy-queued actual package/selfcheck/muted browser tests pass (`build.log`,
  `check-gp5.log`, `check-drums.log` in the delivery directory). Actual page export reads back3 bars,
  14 notes and all expected flag/technique counts. Package checks exercise120 pitched and100 drum
  keys, full-score/caret navigation and live WASM; SONG endpoints are6s and2s for those fixtures.
  No hardware audio, foreground visual or listening acceptance is claimed. Audio settings are unchanged.
  The backend exact bare-rest Place command is included but not yet connected to piano/duration UI:
  15 model/State checks pass (`scratch/native-rest-edit-final-tests.log`) including exact undo/redo,
  guarded failures and reopening. Independent bounded review found no actionable issue
  (`scratch/native-rest-edit-review.md`). UI integration is the next worker assignment above;
  this package still refuses piano insertion inside an authored beat/rest and does not shift notes.
  Selected rollback is `scratch/tab-package-gp5/vulturetracker.exe`; older protected packages remain.
  Close the previous app and open this executable with the unchanged
  `scratch/tab-audio-review/balanced-example/four-bars.yaml`. Full parity remains incomplete.
  No commit, push or release.
- **Previous local delivery (2026-10-20):** `scratch/tab-package-gp5/vulturetracker.exe`
  (49,227,974 bytes; ffmpeg/archive alongside). GP5.00 notation export now uses shared prepare/run,
  the export selector, CLI and agent formats, with existing atomic publication/cancellation/source
  guards. Supported subset: plain notes/rests, voices/ties, integral supported tuplets, metadata and
  repeats. Unsupported effects, timing, clefs and unarranged authored beats refuse; broader parity
  remains open. Existing TG publication regressions pass4 (`scratch/gp5-adapter-tg-regression.log`);
  documentation checks pass9 (`scratch/gp5-docs.log`); exporter/repeat/GP5 workflow checks pass20
  (`scratch/native-gp5-export/review-and-workflow-final.log`). Two concrete loss findings are repaired
  and independently verified in `scratch/native-gp5-export-review.md`. Native GP import now applies
  existing IT transliteration only to tracker channel names, preserving accented score-track names.
  The ROLL guard cancels stale pattern/occurrence/revision gestures before any submission; all six
  red cases pass after the fix, and valid native/raw edits, unchanged refresh and exact undo pass
  (`scratch/roll-gesture-fixed.log`, `scratch/roll-gesture-refresh-final.log`; initial failures retained).
  CPU build passes (`build.log`); heavy-queued actual packaged native/selfcheck and muted page export
  passes (`check-gp5.log`): GP5 output reads back as3 measures/14 notes, complete written score stays
  displayed, rendered SONG ends at6s, and caret/fretboard/live WASM checks pass. No foreground visual,
  listening or final external-editor acceptance is claimed. Audio settings were not changed.
  Selected rollback is `scratch/tab-package-ending/vulturetracker.exe`; older protected packages
  remain untouched. Close the older app and launch this executable to try RENDER & EXPORT → Guitar Pro5.
  Next work: use the worker contracts above to extend GP5 flags and native piano entry; no such
  follow-up production changes are in this package. No commit, push or release.
- **Previous delivery / owner ending correction (2026-10-20):**
  `scratch/tab-package-ending/vulturetracker.exe` (49,225,379 bytes, ffmpeg/archive alongside).
  The native default renderer retained its full ten-second decay allowance even after the samples became
  digitally silent. It now trims only trailing digital silence beyond the written endpoint, after
  resampling. Written rests, sample decay, finite repeats, seeks and explicit export tail lengths remain
  intact. A native render-cache version salt prevents reuse of the old padded SONG WAV.
  The unchanged balanced four-bar example now renders to10.66667s rather than20.66667s. Three renderer
  regressions pass (`scratch/native-ending-unit.log`); the actual tryout worker/meter check passes
  (`scratch/native-ending-worker.log`). The UI worker reproduced11s for a1s score, then confirmed the
  normal SONG resource and browser duration both become1s without starting playback.
  CPU-queued build and heavy-queued packaged native/selfcheck/muted browser checks pass (`build.log`,
  `check-guitar.log` in the delivery directory). The package check confirms10.66667s and all four bars,
  direct editing navigation, fretboard assets and live WASM. No sample, mixer or system volume changes.
  Close the old app, launch this executable and reopen the same four-bars.yaml to get the correction.
  Previous delivery `scratch/tab-package-fretboard` is the selected rollback; older protected packages
  remain intact. No foreground/listening acceptance or full parity claim. GP5 exporter exists internally
  but has no UI/API publication integration; next action is review its handback before exposing it.
- **Previous local delivery (2026-10-20):** `scratch/tab-package-fretboard/vulturetracker.exe`
  (49,213,201 bytes; ffmpeg/archive alongside) includes optional fretboard/scales, GP drum technique import
  and native/TG/GP percussion let-ring. CPU-queued build passed (`build.log` in that directory).
  Actual packaged GP5 import preserved2 drum notes/2 let-ring flags and keys36/42 (`check-import.log`).
  Native/selfcheck and muted browser checks passed on the unchanged balanced four-bar guitar example and
  that actual packaged-import drum score (`check-guitar.log`, `check-drums.log`). The checker exercises
  full score/caret/playback plus276 scale choices (None+275),17 roots, fretboard orientation and unchanged
  song revision. Archive contains editable scale source, attribution and full LGPL/AUTHORS.
  Nine final documentation tests pass; vendor checks passed with the new notice. Foreground visual,
  editing feel and listening acceptance remain open. Audio settings and the familiar guitar example are
  unchanged; the imported drum fixture is a muted package check, not a listening recommendation.
  Selected rollback is `scratch/tab-package-candidate/vulturetracker.exe` (49,202,114 bytes).
  Previous protected packages remain untouched. Close the older app and launch this executable to try it.
  All production was frozen for this build; next worker assignments above are absent from it.
  One subsequent source-only wording fix removes “guitar” from the generic GP placeholder warning; the
  delivered importer still uses the older wording even for correctly mapped drums.
- **Integrated in current delivery:** GP version-specific drum import handback passes37
  targeted tests;41 saved fixtures retain written data and installed callbacks through TG rewrite,16 refuse
  atomically (`scratch/percussion-gp-techniques.md`). No shared-model or synthesis changes were needed.
  Percussion let-ring's28 installed cases justify reuse of the existing scheduler;26 surrogate matches and
  two existing gapped-tie refusals now match actual bank128. Shared model/State/MIDI:36 focused checks pass,
  including atomic same-key MIDI overlap refusal; TG:18 checks and26 installed ordinary/mixer callback matches.
  First State test used nonexistent redo(); corrected to undo(redo=True), then passed. TG comparison correctly
  normalizes fresh import IDs while retaining order/fields/tie endpoints (`scratch/percussion-tg-let-ring.md`).
  Root actual-kit held overlap
  native/WASM replay passes at44.1/48kHz (`scratch/percussion-let-ring-native-wasm.log`), including same-parent
  replacement and same-key other-voice identities. Model/TG production paths are returned to the lead.
  Optional fretboard and full275-scale/17-root catalogue are now frozen. Focused source/syntax, direct-score,
  percussion let-ring, dense/raw/percussion boundaries and the final both-voice/history/stale-target test pass
  (`scratch/fretboard-ui-playhead.log`, `fretboard-ui-final.log`, prior failures retained beside them).
  Source comparison/limitations are in `scratch/fretboard-plan.md`; capo and full max-fret display differences
  are documented in GUIDE. No foreground visual or listening acceptance is claimed.
  Scale notice/editable source are included in package configuration; vendor/docs10 checks pass.
  GP let-ring22 tests pass;33 retained actual-file imports match installed callbacks and TG roundtrip, three
  gapped ties refuse (`scratch/percussion-gp-let-ring.md`). Existing normalization notices remain explicit.
  `scratch/tab-package-fretboard` passed packaging and is the current delivery above. Expanded checker
  verifies packaged scale catalogue and mirrored board without song mutation.
  Next drum-grace contract is ready (`scratch/percussion-grace.md`,21 installed cases,20 surrogate matches,
  one exhausted-head refusal); admission remains deferred, with no grace production changes.
- **Previous delivery / selected rollback (2026-10-20):** `scratch/tab-package-candidate/vulturetracker.exe`
  (49,202,114 bytes; ffmpeg/archive alongside) adds bounded percussion entry/engraving, six drum techniques,
  TG interchange and MIDI channel10 routing to the full-piece direct editor. CPU-queued build passes
  (`scratch/tab-package-candidate/build.log`). Actual packaged selfcheck and muted browser checks pass
  on the unchanged balanced four-bar guitar example and a separately imported two-bar TG drum fixture
  (`check-guitar.log`, `check-drums.log`): stable whole-piece SVG, direct caret/lane navigation and live WASM.
  Nine documentation checks pass. Close the previous app and launch this executable to try the new assets.
  The familiar listening example stays `scratch/tab-audio-review/balanced-example/four-bars.yaml`; no audio
  settings or sample changes were made. `scratch/percussion-package-check/song.yaml` is a muted-check fixture
  with placeholder sounds, not a listening recommendation. No foreground glyph/layout acceptance is claimed.
  Selected rollback is now `scratch/tab-package-next/vulturetracker.exe` (49,198,087 bytes, direct editor).
  Older protected package directories remain intact. No commits, push or release.
  Workers continue let-ring qualification, fretboard assessment and GP technique admission; these follow-ups
  are absent from this delivery. GP qualification found57 stable installed rewrite/callback cases; the
  version-specific implementation is assigned above. Continue from their scratch handbacks before widening
  admission; do not overwrite the delivered executable while the owner tries it.
- **Current owner priority (2026-10-20):** whole-piece display is now working according to the owner.
  The separate grid above it is not the intended editing workflow. Make the engraved TAB the default editor:
  click occupied or empty strings, type frets, navigate across bars and show a distinct editing caret.
  Reuse shared mutations/history and preserve full-piece rendering. Keep the grid and advanced form optional.
  UI worker owns this correction; lead owns packaged acceptance and integration. Percussion workers finish
  their bounded model/interchange slices and freeze at handback; no further percussion expansion before
  this correction is packaged. Automated browser checks remain muted; audio/mixer settings stay unchanged.
  Direct editing now passes blank strings, explicit/implicit rests, coincident voice hits, fret entry, duration,
  ties, deletion, toolbar focus and undo (`scratch/direct-tab-edit-validation.log`). Wrapped navigation keeps
  the caret visible; passive refresh does not move it. Testing exposed display metadata leaking into beat edits;
  these now clone the authored beat. Toolbar actions also restore lost editor focus after save. The original
  failures remain in `direct-tab-entry-third.log` and `direct-tab-authored-beats.log`. The final geometry/property
  run passed direct and wrapped cases but found an older stem-test call missing its explicit occurrence
  (`direct-tab-final.log`); its corrected focused rerun passes. Four-bar muted playback still passes.
  Production UI is frozen and packaged in `scratch/tab-package-next`; native/selfcheck and muted browser pass.
  No foreground after-capture or visual acceptance is claimed.
  After package success, workers resumed the bounded percussion assignments in the coordination table.
  The current executable and rollback stay immutable; the next source changes are not part of this tryout.
- **Older direct-editor preview (2026-10-20):** `scratch/tab-package-next/vulturetracker.exe`
  (49,198,087 bytes; ffmpeg/archive alongside) includes direct score editing and collapsed optional panels.
  CPU-queued build and actual packaged native/browser smoke pass (`scratch/tab-package-next/build-direct.log`,
  `check-direct.log`). The packaged check exercises actual score clicks and arrow navigation without changing
  song revision, confirms the alternate grid is collapsed, and retains all four bars through muted playback.
  User should close the previous app and launch this executable; reloading an older packaged instance does
  not update its assets. Use unchanged `scratch/tab-audio-review/balanced-example/four-bars.yaml`.
  Previous whole-piece preview `scratch/tab-package-work/vulturetracker.exe` (49,189,469 bytes) is the rollback.
  No audio/sample/mixer changes in this correction. Foreground layout acceptance remains unverified;
  no new after-captures were taken. Preserve current delivery and rollback while the owner tries them.
- **Priority correction from owner (2026-10-20):** TAB must show the entire written piece, like normal
  notation software. Replacing a selected-pattern score as playback advances does not satisfy the requirement.
  UI worker is reusing the existing full print timeline for continuous wrapped editor engraving, with
  occurrence-specific click/edit identity and a moving playback highlight/scroll. Grid selection may remain
  pattern-local, but the engraved piece must remain complete. Current API already supplies the full written
  arrangement. No new backend score model or scheduler is required. Percussion remains scratch-only while
  this user-visible correction is integrated. Foreground visual acceptance is outstanding; headless checks
  must not be presented as foreground capture evidence under the current instructions.
  Implementation now renders the full written timeline, with four bars retained through navigation/playback,
  a32-bar wrapped case and cross-occurrence click/edit/history checks. Four primary checks pass
  (`scratch/whole-score-ui-first.log`), four timing/stroke/annotation regressions pass
  (`whole-score-ui-regression.log`), and two manual-scroll checks pass (`whole-score-ui-scroll-final.log`).
  Bounded identity review found a real caret regression: global rendered beat times were treated as local
  pattern positions. Filtering/converting to the selected occurrence fixes it; three navigation checks pass
  (`whole-score-ui-navigation-final.log`). No further concrete wrong-occurrence mutation/highlight finding.
  The existing package checker now derives expected written bars and checks retained SVGs across navigation,
  plus a moving cursor across occurrences. Final packaged run passed; two final cross-system click/edit/undo
  checks also passed (`scratch/whole-score-ui-hits-final.log`). Nine documentation checks pass.
- Percussion integration after the direct-editor delivery: native/TG keys1–100,
  zero tuning/capo, stable lanes and guarded clipboard kinds. GP keys1–99 preserve raw route/flag identity;
  key100 refuses because installed TG changes it to zero. Model:50 focused tests pass. Import:seven final
  focused tests pass; six accepted cases match installed ordinary/mixer callbacks, with GP-derived TG
  save/reload checks. Root chord-tools guard rejects percussion; three State/agent/history/clipboard checks
  pass, including lane-preserving pitch edits. MIDI now routes authored keys to shared channel10, with fixed
  compatible controls and explicit same-key overlap/raw/control-change refusals;57 targeted checks and the
  additional ghost+staccato case pass. An older test expected a MIDI refusal for invalid pitched tuning on a
  drum track; it now checks the earlier shared SongError and passes. Six qualified drum techniques
  (ghost/accent/heavy-accent/staccato/dead/palm-mute) pass11 model groups and11 TG interchange tests.
  Twenty-two exported TG files preserve installed callbacks across rewrite. TG's percussion-clef alias maps
  to stored treble only for neutral0/major key, with a warning. GP technique admission remains refused.
  Imported kit keys/sample mapping and technique gates each pass native/WASM replay at44.1/48kHz
  (`scratch/percussion-native-wasm.log`, `percussion-techniques-native-wasm.log`);
  model evidence is `percussion-techniques-model.log`.
  Percussion engraving and key/lane entry now pass muted browser checks, including six controls, velocity0,
  exact undo, voices and all print modes (`scratch/percussion-ui-final.log`,5.873s). Guitar direct editing
  and22 projection/syntax checks also pass. The initial missing-explicit-velocity test failure remains in
  `percussion-ui-first.log`; its corrected controls run passes in `percussion-ui-controls.log`. The custom alphaTab articulation
  mapping retains drum keys1/100 and uses source-qualified positions/head families; foreground glyph/layout
  acceptance remains outstanding. Existing kit samples are placeholders, not listening acceptance.
  `scratch/tab-package-candidate` passed packaged guitar/drum checks and is now the current delivery above.
  Worker follow-ups resumed after that build froze; they do not change the delivered package.
  Evidence and next routing work: `scratch/percussion-contract.md`, `scratch/percussion-ui-plan.md`.
- **Earlier local preview (2026-10-20; candidate folder subsequently reused above):** `scratch/tab-package-next/vulturetracker.exe`
  (49,189,044 bytes; archive and ffmpeg alongside) contains playback-follow, readable dynamics, explicit
  preview velocity, paired stopped-preview gain and lyrics. CPU-queued build passed (`build.log`); actual
  packaged native selfcheck and muted browser TAB/assets/chord/live-WASM smoke passed on the balanced
  four-bar example (`check.log`, 32 attack/release events). Nine documentation checks pass.
  Existing delivery remains the rollback; the new candidate is the current user tryout. No autoplay.
  Full parity and the owner's listening/visual acceptance remain incomplete.
- **Current user feedback (2026-10-20):** gentle example notes play correctly, but output is too quiet even at
  maximum volume; exact-velocity labels overlap and TAB stays on the first bar while the four-bar arrangement
  continues. The screenshot contains four played quarter notes plus the quarter-note tempo symbol, not five
  beats in 4/4. UI worker reproduced stale displayed order and verbose `Velocity=64` engraving as the causes.
  Playback-follow and compact dynamics fixes pass four focused page tests, with browsing/edit/dialog guards
  and muted real transport across all four patterns. Same-score before/after captures inspected:
  `scratch/tab-preview-before.png`, `scratch/tab-preview-after.png`; isolated layer capture:
  `scratch/tab-preview-velocity-layer-off.png`. The first run exposed a lost unsaved beat-text draft,
  fixed before `scratch/tab-preview-ui-tests-final.log` passed; failure retained in the sibling first log.
  Lead advised lowering volume before a louder revision; no hardware playback or system/mixer change.
  Separate `scratch/tab-audio-review/balanced-example/four-bars.yaml` retains the same sixteen pitches,
  uses smooth unlooped tones and velocity95. Silent native/WASM PCM matches at48kHz; packaged44.1kHz/2x
  output measures -25.02dBTP, -34.46LUFS, zero clipping. This is about21.5dB above the rejected quiet example;
  it is not listening acceptance. Evidence: `balanced-example/result.json`, `balanced-example-final.log`.
  Initial generation used an overlength IT title and was corrected before validation (`balanced-example.log`).
  Existing user song and preview executable remain untouched. Next package goes to `scratch/tab-package-next`.
- TAB Preview formerly discarded authored velocity, making this candidate's first note2.52dB louder than
  transport. Explicit velocity, including zero, now reaches the existing preview API (one focused callback test
  passes). Inherited velocity remains the existing default. Preview is not a complete simulation of authored
  channel/effect semantics. A separate stopped-preview gain bypass is fixed by retaining its paired bundle gain
  and applying it once during mixing. Three silent tests pass, including unity/0.25/zero and pending/failed reload
  association. No native engine rebuild, sound-device access or user-volume changes. Measurements:
  `scratch/tab-audio-review/tab-preview-comparison.json`; no listening acceptance claimed.
- Lyrics model and interchange handbacks pass288 model and88 GP/TG tests. Eight installed TG comparisons
  preserve metadata and both callback modes; two unsupported extra-line GP cases refuse explicitly. Shared
  State/history/agent/export integration passes three new checks plus the existing approved-channel protection
  case; frozen backing/plan and MIDI bytes remain unchanged. MIDI export reports omitted lyrics, agent ranges
  filter occurrence-specific anchors. Editor/print page checks pass; owner acceptance remains. Contracts:
  `scratch/lyrics-model-plan.md`, `scratch/lyrics-contract.md`.
- **Owner listening rejection (2026-10-20):** the supplied `scratch/tab-preview/user-tryout.yaml`
  sounded like "alien nails on a chalkboard"; owner explicitly asked care with their ears. It was wrongly offered
  as a listening example: a synthetic context/technique stress fixture with chromatic overlap, trill/harmonic
  layers and an unsuitable sample loop. Its decaying 440 Hz sample wraps from frame1023 to0 with a 0.54254
  full-scale discontinuity and is incorrectly labeled with the default C-5 root (nine semitones below A-5).
  Withdraw this fixture from user listening recommendations. Preserve it and any user edits as failure evidence.
  No audible playback was triggered during diagnosis, and no user mixer/system levels were changed.
  Packaged silent render: -7.81 dBTP, no clipped samples. Native and WASM PCM match exactly for this fixture;
  those passes did not establish comfortable sound or listening acceptance.
  A separate candidate is `scratch/tab-audio-review/gentle-example/gentle-tab.yaml`: correctly tuned, low-level
  one-shot tones with smooth edges, no sample loops or technique stress combinations, four bars/16 notes.
  Its native/WASM PCM matches at48kHz; the actual packaged executable rendered it at48kHz/1x and44.1kHz/2x,
  with true peaks -46.49/-46.48 dBTP and no clipped/nonfinite samples. It is intentionally very quiet;
  this is measurement evidence, not an ear-safety or musical-quality guarantee.
  Results: `scratch/tab-audio-review/result.json`, `check-example.log`.
  Initial silent render command used a forward-slash executable path that cmd rejected; corrected to an
  absolute Windows executable path (`render-original-final.log`). No engine/source defect was demonstrated
  by this bounded comparison. Future user-facing examples must be checked for tuning, waveform edges/loops,
  content and measured output levels before being offered; never substitute smoke-test completion for listening.
- Row-aligned partial/cross-order repeat measures now use the existing measure controller and disposable
  backing slices. Model: 216 tests pass and 258 retained installed controller cases match. Root State/source-row,
  listening-note rescan, shared pattern-loop, edit/history and MIDI metadata checks pass. Ten native/WASM cases
  cover repeat fragments, contexts, before-grace, cross-order measure ring, and contiguous raw-memory PCM
  equivalence at 44.1/48 kHz. Rounded seek rows now use dispatch frame boundaries; whole-order/context regressions
  pass. Seven frontend checks and the real fragment page passed, including source row30/local row6, offline
  timing, looping, notes, edit/history/reopen and measure-edge notation. Log:
  `scratch/repeat-fragment-page-20261020-capture.log`. Assessment: `scratch/repeat-fragments.md`. Fractional-row cuts remain outside
  this tranche; no new engine ABI or authored pattern copies were needed.
- The promoted context/repeat package initially built and its expanded native selfcheck passed, but its browser check
  found repeated HTTP400 UI reports: `playPos()` included the whole playback plan and exceeded the server's
  bounded report size. A whitelist reduced the observed position/report from 33,273 to 688 characters and
  changed HTTP400 to HTTP200 (`scratch/repeat-context-uistate-20261020.log`). The rebuilt current candidate
  `scratch/tab-package/vulturetracker.exe` passes native selfcheck and browser SVG/assets/live WASM smoke on
  36 events across four repeated fragments with independent contexts. Final log:
  `scratch/tab-package/check-context-fragment-fixed.log`; retained failure: `check-context-repeat.log`.
  Three focused legacy sounding/notes tests pass; their first combined run exposed an existing direct-cell
  mutation in test_sounding leaking through the parser cache. The test now copies its probe patterns first.
- Stroke and pick-stroke are integrated: 226 model tests, 32 retained callback vectors, 73 supported installed
  interchange comparisons and 62 GP/TG tests pass. Fourteen native/WASM replay cases cover plain, dead,
  grace, harmonic, repetition, repeat and swing at both rates. Shared agent/Pattern/history/reopen and MIDI
  timing checks pass. The actual editor passed sparse metadata on either voice, edit, print, clear, undo and
  reopen; its capture was inspected. The refreshed package passes browser and native smoke:
  `scratch/tab-package/check-stroke-fixed.log`. Source contract:
  `scratch/tuxguitar-techniques/beat-stroke-contract.md`. Stroke timing uses both voices/rests and preserves
  source ordering; pick-stroke is notation only. Fade-in is a separate tranche because pinned live playback
  emits no ramp while MIDI mixer/export emits channel-wide CC11; no per-head audible equivalence is claimed.
- Written two-voice overlap is integrated. `scratch/written-voice-overlap-assessment.md` identifies
  sufficient existing context playback but unsafe single-owner Pattern assumptions. Admission must preserve
  source identities, refuse ambiguous bare-cell edits, expose both selectable voices and retain explicit-source,
  raw-channel, same-voice and strict-IT guards. Model handback passes 235 tests and 33 retained callbacks,
  including the original same-string stroke vector. Thirteen installed interchange cases and five focused tests
  pass without interchange production changes. State, source selection/read reporting, agent ranges, clipboard,
  sounding two-to-one, history/reopen and identical-pitch MIDI gates pass. Fourteen native/WASM cases pass,
  including a tied head across repeated measure fragments and an independent second voice. Initial integration
  failures were test fixture mistakes (instrument key, per-track MIDI ordering, unsplit written boundary), corrected.
  Three new page tests, three Node checks and affected selection/ROLL regressions pass. Real defects found and
  repaired: ambiguous TAB highlight, a lost ROLL note ID, missing revision in the score-edit response, and a
  misleading global release display while another head sounds. The shared backend now keeps raw display in
  that release cell and retains its read-only source binding; earlier-order release chips remain reachable.
  First page failures: `scratch/written-overlap-ui-20261020-first.log`; final:
  `scratch/written-overlap-ui-20261020-qualified.log`. Current capture was inspected. Refreshed package passes
  browser/native smoke with 44 events over four repeat fragments: `scratch/tab-package/check-written-voices.log`.
  No new runtime ABI was needed. Contract: `scratch/written-voice-overlap-contract.md`.
- Fade-in is integrated. Model handback passes 243 tests, 15 original retained fade vectors and a valid
  two-voice variant of the same-voice overlap source fixture. `note.fade_in` preserves authored flags and freezes
  compact `plan.midi_fades` descriptors without changing native events. Root MIDI routing passes literal/short
  ramps, composed static gain, logical-track fanout, pulse/range-prefix state, same-tick ramp ordering and channel
  reassignment. Native/WASM PCM is identical with flags off/on at 44.1/48 kHz; affected MIDI gain/pitch/raw regressions
  pass. Contracts: `scratch/fade-in-native-contract.md` and
  `scratch/fade-in-interchange-contract.md`. The chosen gain policy is round-half-up(base expression * logical / 127),
  retaining authored velocity; source ramps remain literal. Physical controllers follow owned gate/pitch intervals,
  with current release-before-attack policy and ordered boundary CC before each new attack.
  UI handback passes two real-page and two Node checks, including sparse chord/voice/tied metadata, print,
  unchanged event schedule, clear/history/reopen. A Playwright value-versus-label selector mistake was fixed;
  the affected earlier sparse-stroke test was corrected and rerun. Current sparse-marking capture was inspected.
  Installed interchange comparison qualifies fade metadata/default callbacks/CC11 for 21 admitted cases; four GP
  fixtures also expose a pre-existing pan 63-to-64 conversion gap, which remains unresolved and is not a full
  callback match. All 67 import tests and real GP5/TG publication checks pass. The refreshed package passes
  native/browser smoke: `scratch/tab-package/check-fade.log`. First page failure:
  `scratch/fade-ui-page-20261020-first.log`; final `scratch/fade-ui-page-20261020-qualified.log`.
- Authored chord diagrams are integrated. Source assessment: `scratch/chord-diagram-contract.md`.
  Chosen native schema is shared beat `chord: {name, first_fret, frets}` or null; first_fret0 preserves automatic
  source placement, resolved only in the disposable renderer. Positive frets must fit its five-fret window;
  all-muted remains a literal diagram, not symbol-only mode. Annotation-only edits do not generate notes.
  Whole-beat copy carries it, note-only copy does not; last sounding-note removal clears it, and explicit rest
  attachment is allowed. Voice moves follow unique-sounding-voice transfer; destination conflicts refuse.
  Separate note replacement is in progress; recognizer/library and generator actions remain pending. Root State/MIDI tests are
  passing: shared agent edit, history/reopen, whole-beat versus note-only clipboard behavior, unchanged event
  schedule/backing bytes and identical native MIDI bytes/report. The first State assertion incorrectly included
  the expected agent authorship mark in raw-pattern preservation; corrected. Model handback passes 254 tests;
  three Node checks and the real editor page pass sparse sharing, high frets, all-muted/rest anchors, copy,
  clear/history/reopen and print. The inspected capture shows string 1 on the right and the shared rest anchor.
  All 73 import tests and 18 installed metadata/default-callback comparisons pass, plus real TG/GP5 publication
  with exact saved YAML fields. Rich GP fields and lossy diagrams refuse; the earlier mixer pan gap remains.
  Refreshed package native/browser smoke passes: `scratch/tab-package/check-chord.log`.
  No runtime ABI change was needed. Model contract: `scratch/chord-diagram-implementation.md`;
  interchange: `scratch/chord-diagram-interchange.md`. Foreground/listening acceptance remains open.
- Diagram-to-notes replacement follows `scratch/chord-note-entry-contract.md`: fresh notes in the selected
  voice, chosen velocity/default95 and track instrument, preserved duration/shared beat fields, same-onset
  other-voice removal only on played strings, and explicit incident-tie removal. All-muted follows the source's
  sounding-beat versus existing-rest branches. It uses one existing score-edit/history transaction. The root's
  State/agent/Pattern/MIDI and tie-refusal checks pass, including one history step and reopen. Model handback
  passes 261 tests, including the whole-rest no-op. The real page found a State no-op bug: an unchanged score
  still reformatted YAML and consumed history. State now returns before serialization when score and residual
  cells are unchanged; the focused no-op and two normal replacement/tie tests pass. First failure is retained in
  `scratch/chord-notes-ui-page-20261020-first.log`. All three affected chord browser checks pass; inspected
  current capture shows the separate annotation/replacement actions and impact preview.
- Exact source pan is in progress, repairing the measured GP63-to-TG64 discrepancy without changing the
  0..64 audio mixer scale. Contract: `scratch/gp-pan-exact-contract.md`. `track.midi.source_pan` holds exact
  value/anchor integers; channel reassignment clears it. Model handback passes 264 tests and proves unchanged
  plans/backing. Six root tests pass all 17 GP balance positions, explicit same-value current pan precedence,
  track-wide invalidation, stale anchors, prefix/range-start X commands, independent voices/fade/muting,
  physical channel reuse and atomic WRITE MIX/undo/reopen. Source-pan metadata is separate from sound assignments.
  Import handback passes 77 tests, real GP5/TG saved metadata and 20 bounded pan checks. All 21 installed
  fade cases now match the full mixer callback stream without the former pan exception. UI setup preservation
  is passing; the real mixer check found equal-value UI edits being discarded before State. The page now uses
  authoritative `source_pan_channels` to preserve explicit same-value pan intent for bound tracks. Final actual
  pan-entry/WRITE MIX/undo passes. All five affected browser tests plus two Node checks pass; final log:
  `scratch/chord-notes-source-pan-ui-20261020-qualified.log`. The earlier mixer timeout used a wrong test selector.
  The refreshed package passes native/browser smoke: `scratch/tab-package/check-chord-notes-pan.log`.
- Tap/slap/pop is the current technique tranche. Contract: `scratch/tap-slap-pop-contract.md`; 22 installed
  source cases establish per-note ownership, TG setter order, GP voice-beat expansion and unchanged default/mixer
  callbacks. Root model/State tests pass boolean/conflict validation, separate tapped-harmonic semantics, flag
  replacement, tied-continuation metadata, clipboard/history/reopen and byte-identical native backing/MIDI with
  unchanged events. The first test run imported a nonexistent helper; corrected to the existing playback planner.
  UI handback passes two Node checks and the actual page: uniform/sparse/mixed markings, independent voices,
  ties, print, clear/history/reopen and unchanged native events. Editor/print captures were inspected; final log:
  `scratch/tap-slap-pop-ui-20261020-qualified.log`. The first Node fixture omitted the renderer's resolved string
  data; corrected without changing harmonic behavior. Interchange passes 81 tests and 22 installed comparisons
  with mixer off/on, plus real saved TG/GP5 imports. TG conflicts normalize with warnings; GP flagged rest/empty
  records refuse. No engine change was needed; package refresh will include the chord tools tranche.
- Chord tools follow `scratch/chord-tools-contract.md`: 3,924 theory and 819 recognition cases match installed
  TG. Generation now matches 168 installed Java cases, including float scores and ordering; 278 model tests pass.
  API and retained failures: `scratch/chord-tools-api.md`. All four profiles/settings are supported within
  explicit work/candidate bounds; no partial search results are returned. The OpenJDK-derived generic sorter
  is isolated in `_java_priority_sort.py`, with a comparator supplied by the independent chord module.
  All eight generator tests and 168 saved Java cases pass after this mechanical split. Full notices and
  corresponding adapted sources are included in the package; `THIRD_PARTY.md` records the distinct licenses.
  Root added revision/track-guarded POST `/api/chord_recognize` and `recognize_chord` agent tool; its State test
  proves suggestions preserve authored names, file bytes and undo history. Root added
  `chord_library.py` and GET/POST `/api/chord_library`: per-user versioned JSON, literal untuned shapes, unique
  nonblank names, existing OS lock and atomic writes, and an integer revision guard. Three focused tests pass
  persistence/clone isolation, stale/duplicate refusal, malformed-data preservation, concurrent lock refusal
  and atomic-write failure recovery. Library and recognition UI each pass three focused checks, with temporary
  user libraries and stale/delayed-response rejection. Logs: `scratch/chord-library-ui-20261020-first.log`,
  `scratch/chord-recognition-ui-20261020-qualified.log`; combined dialog capture inspected.
  Root added `/api/chord_generate` and the `generate_chords` agent tool. Its focused integration test proves
  ordered settings/results, revision/track refusal, read-only suggestions and explicit single-step application/undo.
  Generator controls pass three page tests (8.728 s): settings/profiles/order/previews, draft-only loading,
  library/annotation/note application, undo/reopen, stale responses and bounded refusal. Final log:
  `scratch/chord-generation-ui-20261020-final.log`; capture inspected. The capture helper initially toggled
  an already-open section closed and timed out; it now explicitly opens the section, with no production fix.
  Root generation integration and nine docs checks pass after the sorter split. The refreshed package passed
  CPU-queued build and heavy-queued browser/native smoke: `scratch/tab-package/check-chord-tools.log`.
  It exercises 44 score events across four fragments, native audio contexts, chord suggestion endpoints,
  local SVG/assets/live WASM, all new modules and five license notices. The archive also contains the adapted
  chord/sorting sources. Build log: `scratch/tab-package/build-current.log`.
- Lyrics source assessment is complete in `scratch/lyrics-contract.md`: one raw text stream and starting
  written measure per track, exact TG tokenization and shared-beat placement, ten installed metadata/callback
  cases. GP extra lines must not silently disappear. Model planning and percussion assessment continue in
  scratch; percussion assessment is `scratch/percussion-contract.md`. After the successful package,
  all three workers were assigned lyrics model, UI and interchange in the disjoint paths above, using
  `scratch/lyrics-model-plan.md`. Native lyrics are not yet qualified or included in the preview build.
- Repeats/endings now have a source-preserving projection: 194 model tests and 258 installed-controller
  comparisons pass. Authored orders/patterns remain unchanged; one performed visit list drives score events,
  disposable backing orders, tempo resets, runtime positions, export metadata and source selection resolution.
  The initial full-order scope has been extended by the row-aligned fragments above, retaining the 255 played-order
  and 254 backing-pattern bounds, close counts 0..100 and endings 1..8. Shared State/history/reopen,
  Pattern and agent source identity, contiguous selection/loop versus disjoint refusal, MIDI tempo/text/marker
  expansion and second-pass listening-note provenance pass focused checks. Native/WASM repeat/endings/grace
  replay matches at 44.1/48 kHz, including source position mapping and checkpoints. Real repeat controls/notation,
  live/offline pass mapping, reload, clearing, undo/reopen and linear swing regression pass. TG/GP interchange
  passes 51 affected tests and 75-source installed oracle (146 reads, no comparison failures); GP ending8 is
  preserved, while TG read/write refuses its signed-byte mask mismatch. Real publication/reload retains three
  authored orders and five visits. `scratch/tuxguitar-interchange/repeat-interchange-contract.md` records details.
  Packaged browser acceptance passes after the report fix above; foreground/listening acceptance remains unclaimed.
  API mapping: `scratch/repeat-view-mapping.md`; model/source contract: `scratch/tuxguitar-interchange/repeat-swing-contract.md`.
- Phase B ordinary/grace/repetition head-context spike passed 295 isolated and 102 interleaving/admission cases,
  7,741,702 exact native/WASM PCM samples, plus Phase A's 120 cases. Same-head NNA/DCT remains unchanged.
  A closed-primary fader/silence lifetime mismatch was found and fixed. Harmonics bring the qualified small/WASM
  matrix to 598 cases / 12,498,578 exact PCM samples; full DLL qualification passed. Root Python/JS
  context adapters and lifecycle/capability guards pass. The actual smallDLL/WASM host replay passes six
  trill/harmonic/before-grace cases at 44.1/48 kHz; MIDI preserves simultaneous independent pulse/layer gates.
  The matched full DLL/WASM and cumulative patch are promoted locally; the previous Phase A runtime is the
  selected rollback. Root full-DLL host checks passed 20 replay cases including mixed legacy/context attacks,
  repeats and model-generated heads. Vendor hashes pass. Model admission passed 205 tests and seven installed
  callback sources (14 reads); actual context page checks passed four cases plus the held regression, including
  dispatch, independent live handles, nonzero output, Pattern, history and reopen. Package integration is above.
  Carry/random sources remain explicit refusals. Details and retained failure in `scratch/native-score-engine/hold-phase-b-design.md`.
- Swing is integrated in source: model 178 tests, actual page, State/history, MIDI/tempo and native/WASM
  replay at 44.1/48 kHz pass. `score.measures[].swing` is none/eighth/sixteenth. TG/GP interchange matched
  39 supported originals and 13 expected repeat refusals (52 cases); fractional-phase oracle adds 15 vectors.
  An ordinary swing extension crossing a following same-parent note now uses the qualified hold path; the
  initial overtick-neighbor refusal is retained in `scratch/tuxguitar-interchange/swing-interop-result.json`,
  final zero-failure comparison in `swing-interop-fixed.json`. Source controls/annotations and print passed;
  the original packaged checkpoint predated swing. The measured repeat controller
  contract has 33 installed TG cases / 322 callbacks, including source-phase swing and pass-sensitive ties/ring:
  `scratch/tuxguitar-interchange/repeat-swing-contract.md`. Legacy GP repeat expansion has two demonstrated
  traversal differences and is not the native implementation oracle. Concurrent technique engine qualification
  and its promoted Phase B runtime are recorded above, including unchanged isolated same-head NNA/DCT behavior.
- Same-parent ordinary let-ring is runtime-qualified and promoted locally. The plan marks earlier protected
  attacks with `hold: true`; all played attacks on that parent must be explicit ordinary single-pitch notes, and
  its entire backing must contain only empty/T/V cells. This conservative scope accounts for unknown release-tail
  lifetime. The Python/JS hosts negotiate `vt_held_score` before PCM and use the new atomic seven-int group plus
  hold-flag dispatch; unsupported existing engines refuse rather than cutting a note. Model tests: 153 passed;
  Python batch/identity guards, JS held/group guards and fail-before-audio capability check pass. Sounding context
  now retains both held and newer same-channel identities; its focused check and legacy sounding regression pass.
  MIDI pairs by identity and reuses the existing physical-channel allocator; focused overlap, pitch, capacity,
  whole-parent scope and model-generated hold tests pass. Actual held native/WASM replay test is authored and
  passing on small/full DLL and WASM at 44.1/48 kHz, including pitch, tempo, SPEED, mixer and checkpoint replay.
  Candidate proof: 120 cases / 2,510,122 exact native/WASM PCM samples; 2,364,540 also match uninterrupted
  independent held voices. Corrected silent-background retirement and a last-slot false exhaustion; all 252
  background slots can be protected and additional allocations refuse atomically. Existing group/tempo/checkpoint
  engine regressions pass. Seven runtime artifacts plus the 13-file patch are promoted; prior tempo family is
  the selected rollback in `scratch/native-score-engine/rollback-promoted`. Vendor check and extended package
  selfcheck pass in source; refreshed package and browser smoke pass. Design/ABI and detailed checks:
  `scratch/let-ring-overlap-design.md`, `scratch/native-score-engine/hold-contract.md`.
  Actual page test also passes: observed held dispatch, distinct old/new identities, live output after replacement,
  shared Pattern endpoint and undo/redo. Log: `scratch/held-ui-page-20261020-final.log`. Initial test-hook failure
  came from AudioWorklet fetch bypassing Playwright routing; the test now observes the served worklet via addModule.
- Grace-note contract is measured against 53 installed TG cases / 441 callbacks. On-beat grace delays the main
  attack while retaining its release; before-beat grace falls back near song start. Transition labels are notation
  only. Native model/editor/print/interchange are integrated: 166 model tests, two State/history tests and two
  queued browser tests pass. Shared playback preserves written anchors, independent grace velocity and source
  identity; native/WASM replay matches at 44.1/48 kHz for plain/before/bend/repetition/harmonic cases. MIDI keeps
  performed timing and reports grace ownership; export reclocking updates delayed main frames. The installed
  interchange oracle matched 142 supported sources and seven expected refusals (149 originals plus roundtrips),
  including GP3/4's TG byte order and dead-fret sentinel. Malformed source fields refuse before files are written.
  Exhausted main durations, ambiguous inherited instruments and unsupported overlap remain bounded refusals.
  Contract/results: `scratch/tuxguitar-interchange/grace-note-contract.md`, `grace-interop-result.json`.
  Browser log: `scratch/grace-ui-page-20261020-first.log`.
- Let-ring's bounded native slice is integrated: shared ordered-voice release scanning, exact onsets and fractional
  duration rules, independent `sounding_end`, gate exclusions, editor/print engraving and TG/GP interchange.
  152 model tests passed, including eight new fractional oracle vectors. State integration passed generated Pattern
  release, unchanged written duration, raw conflict refusal, undo/redo and reopening. MIDI uses the extended gate;
  native/WASM PCM and replay/checkpoints match for plain ring, bend and picking at 44.1/48 kHz. The actual page passed
  no-velocity note/chord entry, mixed state, engraving/print, live output after the written end, exclusions, clear and
  undo. Initial page failure was an optional title returning None after clear; the assertion now accepts an absent
  attribute. Logs: `scratch/tab-preview/let-ring-page.log` and `let-ring-page-retry.log`. Installed TG matched
  47 supported interchange cases; 12 unsupported overlap/tie/repeat cases refused. Importer coverage: 43 tests
  passed, then the one obsolete blanket let-ring rejection assertion was corrected and passed. Same-parent performed
  overlaps and repeat-close provenance were subsequently extended by the context/repeat tranches above;
  beyond-arrangement sustains still refuse. Updated held interchange comparison: 54 supported / five refused, zero failures in
  `scratch/tuxguitar-interchange/let-ring-held-interop-result.json`. The packaged checkpoint below predates
  let-ring/grace; the current checkpoint below now includes them.
- Earlier held/grace package checkpoint (superseded by the current candidate above): the candidate passed
  `tools/exe_check.py --song scratch/tab-preview/package-held-grace.yaml --browser`: eight performed events,
  live playback past the overlapping attack, native held/group/tempo/gain/pitch/tail checks and bundled assets.
  Final logs: `scratch/tab-package/build-current.log`, `check-held-grace-fixed.log`. The check caught a real
  same-row/channel release projection collision: Pattern now coalesces identical generated release markers
  while preserving both score identities and refusing edits to that marker. State regression verifies later
  attack reverse editing too. The retained failed browser log is `check-held-grace-final.log` (404 Pattern).
  Earlier launch mistakes are retained in `check-current.log` (tracker-only demo) and `check-held-grace.log`
  (invalid fixture row label, corrected before the final run). No `dist/` files changed.
- Previous tempo/repetition package checkpoint passed the existing packaged selfcheck
  plus `tools/exe_check.py --browser`: bundled TAB SVG/assets, live WASM playback, and DLL tempo/group/gain/pitch/release/tail.
  Logs: `scratch/tab-package/build-current.log`, `scratch/tab-package/check-current.log`. Both jobs used the
  coordinator queue. Packaged TG export/import preserved all 166 musical events (including 12 repetition attacks), exact times/duration and the
  137/83/137 tempo map; seven placeholder WAVs were created with the expected sound-replacement warning.
  Evidence: `scratch/tab-package/interchange-repetition/result.json` and adjacent CLI logs. This qualifies the
  tempo-authoring/harmonic/repetition/interchange snapshot; it is not a release or foreground visual/listening acceptance. `dist/` was not changed.
- Annotation and ghost/accent/heavy/hammer page checks now pass, including literal escaped text, undo, native GP
  import and live playback. Optional track `midi` metadata now validates program/bank without affecting native
  sound. Metadata-only track edits preserve omitted fingering; two focused model checks pass. UI/interchange
  and the current tempo-clock integration are recorded below.
- Track MIDI controls passed the actual page check: bounds, metadata preservation, unchanged beat/playback data,
  reopen, clear and undo. MIDI bank/program output passed frozen-snapshot and parsed-event ordering checks;
  the 18 native MIDI tests pass. TG export/import is wired through CLI, GUI and existing safe publication jobs.
  Four integration tests pass, including readback, native reimport, CLI/agent dispatch and preservation of a racing file.
  Actual TG page export/report/archive/reimport/playback passed with seven samples and unchanged source;
  unsupported stems showed a refusal without output. The installed upstream reader/writer preserved two fixtures
  semantically (13:8 seed and a two-voice/tie/curve/annotation case). The 21 importer tests, final six TG checks
  and required-field regression passed. Harmonic and tempo interchange checks follow below.
- Harmonic schema/planning now retains type/data and emits ordered per-attack layers without changing authored
  pitches. Natural/artificial/tapped/pinch/semi vectors, velocity reductions, natural modulo behavior, save/reopen
  and bounds pass three focused tests, including tie-head ownership and signed-capo pitch-zero clamping.
  Controls/engraving, playback and undo passed the actual page check. A syntax test was first invoked with the wrong
  method name; the corrected `test_script_parses` invocation passed. MIDI layer routing is now qualified below;
  the separate replacement-reference discrepancy was explained by unequal inherited state, as recorded below.
- TG harmonic interchange now passes 24 importer tests. The installed TuxGuitar oracle matched 102 accepted cases,
  223 note layers, all pitches/velocities/note-on/off ticks, including every type/data pair, natural modulo cases,
  negative capo, dynamics and ties. One upper-range case correctly refuses. Results:
  `scratch/tuxguitar-interchange/harmonic-oracle-result.json`. GP harmonic mapping is qualified below.
- Native GP3/4/5 harmonic conversion passed 27 importer tests and the installed upstream readers matched
  214 fixtures / 452 note layers with zero pitch, velocity or tick mismatches. GP4 recovers source codes from
  PyGuitarPro's decoded fields; ambiguous pairs refuse. GP5 artificial fields ignored by TuxGuitar are retained
  in source notes with warnings. The TG parser also now rejects NUL-bearing XML before ElementTree can sniff
  UTF-16 and bypass the UTF-8 DTD check; a small entity fixture proves that refusal.
- Root group-engine review found full-song scanning and allocation at every grouped dispatch. Private reusable
  rollback storage and cached eligibility replaced it; live timing remains unmeasured.
- Corrected grouped small-native/WASM qualification passed 74 cases and 3,168,386 exact samples, including
  setup priming, rollback reuse and configuration invalidation. The adapters passed their 18 affected checks
  against that corrected pair, including seek/SPEED/checkpoints and ordinary velocity. Full DLL and page results
  follow; the repeated-group reference discrepancy is resolved below with equivalent inherited state.
- The corrected full grouped runtime was promoted, followed by the qualified tempo family below.
  Full DLL adapter checks passed 18 tests; vendor/docs checks passed 10. The queued real harmonic page check
  passed all five technique types, engraving, native playback, clear and undo. Full parity, foreground visual
  and listening acceptance remain open. The packaged checkpoint above includes these changes.
- Tempo playback is integrated: the first slice is raw absolute T20..FF with constant tracker speed, mapped into optional
  `plan.tempos` / authoring-view entries `{at, bpm}`. Score-owned occurrence tempo edits remain a subsequent slice.
  The Python `TempoClock` and browser `nativeScoreClock` retain rational prefixes and round absolute frames once.
  Browser boundary/inverse/SPEED vectors and constant group regression passed 11 tests. Loading the shared browser
  helper first failed because its public asset route was missing; adding the existing asset allowlist entry fixed
  it and the harmonic page regression passed. GUI facts now map order starts, row times and sounding-note age;
  two focused facts checks passed after correcting a sparse-row fixture. The real variable-tempo page check passed
  TAB/Pattern positions, seek, SPEED and exact note-boundary highlights. Its first failure counted an empty string
  cell as a note; filtering empty note IDs corrected that test query without changing playback.
- Host tempo/group integration passed at 44.1/48 kHz against the candidate small DLL/WASM, including exact PCM,
  seek, SPEED, checkpoints, tails and repeat. Its initial repeat check lost one frame through float frames/rate;
  exact render caps and export now retain Fraction(frames, rate). The related export-length check passes.
  Native full tempo qualification passed. Promotion was held for a replacement-reference discrepancy
  (0.0014870166778564453 max, first frame 86912), also reproduced without tempo commands. Diagnosis found
  CHN_WRAPPED_LOOP inherited from different old pitches in the independent-parent reference; the approved group
  semantics seed every new layer from one primary. Equivalent-seed replacement, isolated new attacks and old
  cut tails pass all 64 focused checks exactly, with same/different incoming pitches and default/disabled ramps.
  No playback workaround or widened tolerance was used. Final artifacts and cumulative patch are promoted;
  the previous group family is the selected rollback. The promoted full-DLL/WASM host integration test passed,
  as did ten vendor/docs checks. Details:
  `scratch/native-score-engine/PROOF.md` and `tempo-group-replacement-diagnostic.json`.
- Native MIDI pitch/layer routing and tempo-map export passed 36 focused exporter checks (including legacy MIDI,
  TG and audio regressions), then the final two tempo tests. The actual export page passed duplicate harmonic
  layers, bend routing, saved-file tempo events, visible report and refusal/no-output checks. Tempo engraving
  was checked in the captured alphaTab model: 120 BPM at ratio 0, 180 at ratio 0.125. Physical melodic channels
  stay owned through release and the final pitch control; capacity/percussion/program ambiguity refuses.
- TG/GP native tempo interchange passed 24 focused tests. Installed TuxGuitar matched tempo events and note gates
  for six supported import fixtures and a native-exported TG; two unsupported fixtures refused. GP normalization
  retains original beat/transition details with warnings. TG export requires tempo commands at measure starts;
  non-quarter/dotted markings, BPM outside 32..255 and mid-measure commands (including no-ops) still refuse.
- Downstream tempo review reproduced listening-note timestamps at 1.50 s instead of 1.00 s and a selected 60-BPM
  section's four-beat count-in lasting 2 s instead of 4 s. Listening notes now use row_times; recording uses
  TempoClock at the actual accompaniment start. Four focused checks and the affected notes page passed.
  Sample slicing still explicitly refuses native structural edits; render-to-slot already uses the corrected clock.
- Tempo authoring is implemented through the existing raw T authority, with no second saved tempo map.
  Root's State/agent integration passed three focused tests for Pattern synchronization, no-op history, undo/redo,
  reopening, reverse Pattern edits, clear, approval/revision/guard/write failures and agent channel protection.
  All 130 pure tablature tests passed, including seven new authoring cases. The actual measure-panel checks passed
  set/update/clear, explicit no-op versus inheritance, engraving, endpoint preservation, shared scope, fractional-row
  refusal, undo and reopen. A refusal initially erased the draft BPM during refresh; keeping it when the source revision
  and target are unchanged fixed the reproduced retry. Logs: `scratch/tab-preview/tempo-authoring-page.log` (failure)
  and `tempo-authoring-retry.log` (pass). The current packaged checkpoint includes this UI slice.
- Trill/tremolo-picking contract is confirmed against installed TG 2.1.0: 49 fixtures/370 note callbacks.
  Tie-head ownership, tempo crossings, dynamics, harmonic bypass and final-pulse cutoff are recorded in
  `scratch/tuxguitar-interchange/REPETITION-CONTRACT.md`. Fractional onset/rate/GP details and native implementation
  follow in its addendum: 24 more cases verify offered rates and rational onset offsets, including the compensating
  tick in fractional tied chains. Implementation is active with `trill: {fret,value}` and `tremolo_picking: {value}`.
  Performed pulse IDs/source_id remain separate from written note/selection identities. Root's GUI and MIDI-report
  consumers are adapted. All 141 model tests passed, including eleven new repetition groups. Root's GUI and MIDI
  checks passed: zero-pulse written positions retain instruments, tied pulses report their actual played order,
  and exported pulses retain pitches, gates, velocity and source identity. Native/WASM PCM matches at 44.1/48 kHz
  under matched read partitions, including seek/SPEED/cancellation and 64 checkpoint restores per rate.
  The first harness incorrectly required full reads across event boundaries, then expected the pitch fixture's
  96 checkpoints; correcting those fixture assumptions passed without runtime changes. Three relevant legacy
  facts/tempo/MIDI regressions also passed. Both actual repetition page tests passed entry, mixed chord edits,
  engraving, print projection, live playback, effect exclusions, clear and undo (`scratch/tab-preview/repetition-page.log`).
  TG/GP interchange passed 38 importer tests and 98 supported installed-parser/native-plan/roundtrip comparisons;
  three unsupported rate/percussion cases refused. Conflict normalization retains original values in warnings/message.
  Evidence: `scratch/tuxguitar-interchange/repetition-native-{base,fractional,gp}.json`. Initial fixture mixer/implicit-clef
  assumptions were corrected without weakening exporter guards. The scratch package rebuild, browser smoke and
  packaged TG roundtrip passed with the 166-event fixture, as recorded above. No engine changes for repetition.
- Earlier parent-batch integration (2026-10-20): the full DLL family and WASM pair were promoted locally.
  1,040 cases and 55,058,120 float32 samples matched exactly; exports, decoder dependencies and final promoted
  guards passed. Python and worklet adapters submit all same-frame releases/attacks together. A runtime backing
  conflict discards its consumer; the worklet silences the failed quantum and accepts a fresh paired load.
  Focused worklet recovery, atomic swap, seek, repeat and Python/WASM checks passed.
- Exact raw preview/adoption and structural qualification passed 146 tests. Adoption preserved PCM in 24
  comparisons at four rates, including inheritance/NNA and qualified raw controls. The planner admits X/D,
  M00..40, V00..80 and v00..64; other controls still refuse. Previews identify occurrences and exact boundaries;
  adoption requires an explicit raw note-off and rejects ambiguous/cut/fade endings. UI integration is in progress.
- A foreground native editing/playback check exposed a collapsed ROLL in a short window. Measured viewport height
  was zero; limiting the toolbar height and centering notes restored a 65px viewport with hit-testable notes.
  Same-camera captures: `scratch/tab-preview/roll-viewport-before.png` and `roll-viewport-after.png`; no console
  errors. The 432x540 playback/Stop/ROLL/TAB regression now passes at the correct occurrence, 4/13 and fret 2.
- Whole-song and selected-region native audio exports use an immutable backing/plan pair at the actual mixer
  rate. Region starts replay both streams; exclusive ends suppress subsequent attacks/effects and allow the
  captured voices to ring through the finite tail. API order-range measurement shares this path. Focused checks
  passed for replay, boundary release versus next attack, cancellation, source changes, actual song/stem files
  and alignment at 44.1/48 kHz; three legacy region/game-loop checks passed. Native game-loop warm-up and IT conversion
  remain explicit refusals; the supported native MIDI subset is described below. Browser section export passed;
  final package qualification remains open.
- Browser section export exposed a one-frame double-rounding error at tempo 137. Output lengths now subtract
  directly rounded absolute musical boundaries at the requested output rate; four-rate regression passed.
  The actual page produced song and stem WAVs with exactly 77,255 frames at 44.1 kHz, without page errors.
  Native raw-preview/adoption and occurrence-aware fractional ROLL ghost checks passed. Pattern cursor/range
  transpose, amplify, clear, humanize and undo now use the guarded native transform endpoint; both page tests passed.
  Mixed Pattern clipboard is wired to atomic native endpoints. Rapid Copy/Cut then Paste now queues the captured
  destination behind the copy result; failed cuts preserve the old clipboard and block dependent paste. The shared
  queue regression and three rapid Copy/Cut/Paste page tests pass, including seeded old clipboard, exact fractional
  destination, fresh note IDs, preserved raw fields, undo and failed-cut rollback without page errors.
- PHRASES now validates/clones/edits native documents and renders frozen alternatives through paired regions.
  Fractional notes remain authored while the text grid edits aligned notes and raw cells. Four targeted tests passed,
  including 13:8 frozen audio, shared-occurrence acceptance, undo/redo and reopen. The original Q12 case is retained
  as a refused, unchanged transaction; D07 provides the supported raw-effect acceptance case. Line-absent auditions
  retain the rest of the score; accepting absence still requires an explicit rest edit. The actual page passed
  Capture/Edit/Audition/Accept/Undo with fractional notes retained and no song write before Accept.
- Selection/region/clipboard backend handback: 247 tests passed across tablature, sync, agent and measure modules.
  Selected tryouts, row rendering, meters, render-to-slot and section selection now reuse paired regions. Mixed
  Pattern clipboard supports partial chords, exact origins, field masks, raw controls, internal ties, fresh IDs and
  atomic cut; the UI is wired and page acceptance is pending. Occupied overwrite, mix/push/flood/overflow and external
  ties still refuse. Previous model/State/server ownership is returned to lead; engine adapters are assigned for SPEED.
- Recording play-along now renders native backing directly at the recorder rate, avoiding a second boundary
  rounding during resampling. Focused native 44.1/48 kHz and legacy backing-route tests passed; the native test
  compares the actual recorder buffer with the paired export and verifies the song is unchanged.
- Native SPEED reschedules absolute rational boundaries using libopenmpt's quantized inverse factor and replaces
  playback through bounded paired replay. Twenty engine tests passed; the final pending-seek fix passed its focused
  check. Raw/native WASM comparisons passed at 44.1/48 kHz for factors .5/.75/1.3/2 within 1e-6 per sample. The
  pending legacy-load/native-wrap leak was reproduced and fixed. Position messages expose the sounding factorQ;
  the TAB marker uses this sounding clock. Three page checks passed for 130% SPEED, exact selection/boundaries and
  failed TAB Copy/Paste preserving the prior clipboard without mutation. Checkpoint integration is complete below.
- Checkpoints passed 512 restores per engine and 122,940 deterministic native/WASM samples exactly, including
  nondefault SPEED and stale identity refusal. The full DLL family passed exports/dependencies and decoder checks;
  the seven runtime artifacts and twelve-file portable patch are promoted locally. The selected rollback now holds
  the previous batch build. Eight promoted vendor/Python checks passed. Live worklet integration passed 21 engine
  tests, including over 2,000 restores, fresh identity remapping, settings invalidation and canceled loads. Prepared
  wraps restore within the quantum; initial or invalidated preparation still replays the prefix. The existing
  worklet benchmark now accepts native pairs and loops; its quiet measurement is deferred. Its own waiting runner
  was withdrawn because the all-slot queue head blocked builds/pages behind a 150-minute external heavy job.
  Required build/browser jobs keep their normal coordinator entries; other owners' jobs are untouched. No live performance or
  listening claim follows from the correctness probes.
- The existing package selfcheck now renders a scheduled native note/release and tail; source check passes.
  `exe_check.py --song` also verifies the paired playback response when opening a native score. Final package build
  waits for the active engine and editing changes; the earlier scratch executable is not current.
- Cut/Repeat now have a shared revision-guarded State/server command and queued TAB host bridge. The agent bridge
  passed its focused Cut/rest-duration, one-step undo, authored mark, stale-revision and approved-channel test.
  Three older fixture assertions failed because they expected integer positions; the editor worker corrected them
  to the rational API contract without changing musical fixtures. Eleven command tests, five fixture/syntax checks,
  and actual-page Cut/Repeat and gate-control checks pass. A longer destination rest split could reuse its ID twice;
  materialization now retains the original ID only once per occurrence, with a focused two-remnant regression passing.
- Pinned technique formulas and numeric vectors are recorded in `scratch/native-score-engine/PROOF.md`. They are
  source-derived, not an upstream runtime or listening oracle. Native identity-safe pitch control is being prototyped;
  harmonic layered voices and the remaining technique model/UI work remain open. Exact native MIDI conversion is
  being implemented from frozen snapshots with explicit refusals for unresolved tracker state or SMF limits.
- Staccato/palm-mute/dead note gates are implemented in the native model, preserving written durations and nullable
  volume. Source-derived vectors, tie-head precedence, save/clipboard/undo/reopen and twelve native PCM comparisons
  across four rates pass. The existing WASM score test now covers these flags and passes matched PCM, SPEED,
  read cuts and 64 checkpoint restores. Both affected model/sync modules passed 173 tests before a further tied-tuplet
  source correction: TG tie expansion compensates truncated durations using rounded absolute beat-start gaps.
  The new eight-segment 7:4 regression and two adjacent gate checks pass after that correction (137 gate ticks,
  not 136). A missing test import/incorrect redo call was fixed without production changes. Gate UI/engraving page
  checks pass; listening acceptance remains pending. Strict standalone IT conversion explicitly refuses these techniques.
- Exact native MIDI export is implemented from frozen snapshots: adaptive PPQ, tie/technique gates, trailing rests,
  section-end clipping, explicit sample/plain-instrument attacks and a qualified residual X/M/V subset. Seventeen
  focused checks passed, including parsed MIDI files, frozen source/mix/mutes, job guards and legacy/audio regressions;
  the final missing-release guard passed its focused rerun. Inheritance/NNA/slides, carry-start, repeat and unrepresentable
  timing still refuse with locations. Conversion reports state sound/notation/tempo losses. The export panel now shows
  previously hidden warnings and the MIDI summary. Actual-page success/refusal checks pass: saved MIDI parses with
  PPQ 12480, 13:8 timing, ties and three gates; warnings show, sources stay unchanged, and Dxx refusal writes no file.
  The initial fixture expectation used the wrong tempo-dependent gates and passed after correction. Native-agent/context checks passed;
  docs initially found the new score_command missing from GUIDE, corrected and focused docs check passed.
- Bend/tremolo-bar/vibrato source now preserves editable curve points and schedules identity-owned pitch controls
  using pinned TG integer interpolation/durations with exact native onsets. Coincident resets retain their order.
  Native uses an explicit +/-12-semitone receiver range; external TG receiver configuration may differ. Four focused
  regressions pass for numeric source vectors, gates/tie heads, malformed curves, reclocking, Repeat rest IDs and MIDI
  pitch refusal; the affected model/sync modules plus native MIDI tests pass 191 tests. Native MIDI explicitly refuses
  per-note pitch until independent channel allocation is implemented. UI and production adapter integration are active.
  Production Python/WASM adapters pass candidate integration at 44.1/48 kHz, including 192 checkpoint restores,
  SPEED/seeks/repeats/range/tail handling and released-identity controls. Cross-engine PCM differs by at most 1e-8;
  neutral and independent-channel PCM match exactly. Slide source vectors and release-tail ownership also pass.
  Scratch native/WASM pitch qualification passes 67 cases and 270,468 deterministic matched samples; checkpoint and
  batch regressions also pass. The initial WASM probe exceeded its 4096-frame read buffer; bounded probe reads fixed
  that harness failure. Full DLL ABI/dependency and IT/OXM/zlib/MP3 checks passed. The seven runtime artifacts and
  complete twelve-file patch are now promoted locally; the previous checkpoint family is the selected rollback.
  Promoted adapter/vendor checks and the source package selfcheck pass; the latter now exercises note/pitch/release/tail.
  CI requires pitch capability instead of silently skipping it. Three promoted-runtime page checks pass: measured
  live bend/bar frequency ratios match planned pitch, vibrato survives seek/loop/130% SPEED, slide shifts audio,
  curve engraving continues across authored measures, exclusions and exact undo pass. These are functional audio
  measurements, not listening or performance acceptance. Final package qualification remains open.
- A root preview opened the curve controls without console warnings/errors, but the app queued its panel because
  this chat was not active. Its narrow background capture is not foreground visual acceptance. The temporary tab
  and exact owned server PID were closed; the game lease ended. No timing or visual-fix claim follows from it.
- Active velocity/import tranche: optional authored `velocity`0..127 is separate from nullable IT `volume`.
  Root model/edit/clipboard/strict-IT guards and exact positive-velocity MIDI export pass focused checks; MIDI carries
  sample/instrument gain with rounded CC11 and restores expression when returning to derived tracker velocity.
  Gain is now promoted in the full DLL/WASM and thirteen-file source patch. 430 gain comparisons, neutral bit-exact
  output, 67 pitch cases and 512 checkpoint restores pass; eight production adapter tests pass. Existing integer
  click-suppression tails explain a retained initial ratio failure; the recurrence bound is documented in PROOF.md.
  ABI/dependencies and decoder probes pass; promoted vendor/source selfcheck passes with gain/pitch/release/tail.
  CI requires gain capability. The selected rollback is the preceding pitch family. Native GP3–5 import and legacy
  routing pass eight focused native tests and legacy tests, including actual CLI conversion and publication races.
  The complete backing/plan validates with private samples before publication. A late YAML collision preserves the
  user's file but can leave this import's sample directory. GUI/API/CLI import wiring is complete; actual-page and
  final package qualification remain open.
- Beat text and measure markers are now native anchored metadata and retained in GP3–5 import. Model checks pass
  for unchanged playback, clipboard/reopen and no repeated text on split continuations. Native MIDI carries exact
  text/marker timestamps from its frozen snapshot, including region clipping; marker colors and voice placement
  are explicit conversion losses. The focused parsed-output check passed after correcting its missing test import.
  An earlier GP test invocation used the wrong class capitalization; corrected invocation passed all three formats.
  Promoted dynamics page/audio and actual native GP GUI import passed, including seven generated samples and live
  playback. Annotation page testing exposed text-only beat_set materializing implicit fingering; the shared model
  now preserves unchanged note geometry exactly, with its regression passing. The failed page assertion remains
  for rerun. Ghost/accent/heavy/hammer model and GP conversion passed 114 model + 9 native GP checks; derived attack
  velocity leaves authored velocity unchanged. The editor controls and page checks are assigned. Root also reproduced
  and fixed a cross-channel approval gap: an unapproved hammer predecessor changed an approved target's performed
  dynamics despite unchanged target source. Common agent restore guards now compare protected performed controls;
  six native agent checks pass. Parsed MIDI checks preserve 95 then hammer+ghost 54 without mutating source.
  Fade expression and harmonic grouped voices remain incomplete.
- Current `.tg` interoperability research has a real upstream oracle: installed `C:/Program Files/tuxguitar`
  exposes TuxGuitar 2.1.0 libraries, used read-only by `scratch/tuxguitar-interchange/TgInteropProbe.java` through
  the CPU queue and existing JDK 24. The upstream writer/reader round-tripped its seed: one track/measure,
  13 exact 13:8 beats and 12 notes, text/marker/dynamics. XML confirms Unicode and escaping. The initial helper
  compile failed on the tempo setter/wildcard source lookup, then its version-string guard rejected upstream's
  `2.1` spelling; those harness mistakes were fixed. Source files are pinned to the inventory commit. No `.tg`
  production import/export has completed validation yet; the model worker is implementing the bounded current
  archive format with explicit refusals and shared safe publication. Java is only the test oracle.

- Optional `score.version: 1` stores rational written time, stable beat/note/occurrence IDs, tracks, fingering,
  two voices, rests, ties and basic measure bounds. Residual raw tracker fields stay in `patterns`; the compiler
  overlays owned notes/releases without saving duplicate cells. Legacy songs retain their original path.
- TAB / SCORE uses a bundled alphaTab 1.8.4 renderer and Bravura font, with native controls and the existing
  live audio engine, edit queue, cursor and undo history. Fret/pitch and chord-duration edits synchronize with
  Pattern/ROLL. Supported single-note and whole-chord roll moves retain IDs. Approved patterns and stale revisions
  are guarded. Raw notes have read-only previews and explicit sound-preserving adoption. Agent read_score/edit_score
  use the same State operations and protections. Native clipboard UI supports Ctrl+click multibeat selection and
  Copy/Paste with fresh IDs. The SVG playback marker follows the shared transport, including rests.
- Pattern rename/clone/channel remapping, section move/duplicate and phrase capture/accept preserve score
  references on supported operations. Unsupported tie/structural operations refuse before persistence.
  Selected tryout and export transforms use a disposable playback projection, retaining saved notation.
- Checks: 67 model tests passed through exact authoring-view extraction, playback-plan and spelling-preservation tranches; shared-state tests and the CI
  command-list guard passed, including approved-pattern/channel guards and adoption with identical IT bytes. Phrase tests cover selected/unselected
  notes, releases, raw effects, undo/redo and reopen. The first leased Edge TAB edit/history/reload test passed.
  The initial browser fixture failed to compile because its first row label was 08; corrected to 00 and verified
  through State before the passing rerun. Section tests exposed a YAML separator bug in `replace_values`, now fixed.
  A broader TAB page run found two fast-digit failures: scoreCommit resolved before a concurrently started scoreRefresh.
  The shared in-flight refresh promise now prevents that race; both failing tests passed after the fix. Other new
  TAB cases passed. Three focused browser cases for clipboard, score marker and whole-chord movement passed.
  Measure edits now respect approved patterns and agent provenance; targeted State tests passed. SONG New pattern
  and agent order creation now supply occurrence mappings; the agent creation/reorder/undo regression passed.
  All 16 State sync cases passed before the subsequent clone/remapping regression. A bounded mutation audit proved
  clone+channel-move could strand raw cells and numeric automation lanes. `_map_rows` now reads current transaction
  patterns/width and remaps lane channels; clone/lane/undo plus legacy structure tests passed. Its initial test fixture
  refused an unrelated unplayed final tied release; the corrected fixture isolates the remapping behavior.
  Enharmonic spelling and +/- duration controls passed two focused browser cases and syntax checks.
  Track notation, measure controls, deletion and actual New Pattern passed six focused browser cases; initial
  harness failures from lazy renderer loading and color representation were corrected before passing reruns.
  Legacy corpus compilation still matches its recorded module bytes.
- Visible inspection: the local app loaded the score without console errors. A generated-rest 12:1 label was traced
  to arbitrary duration spelling and replaced by standard tuplets/rests. The viewport changed during inspection;
  same-camera comparison and owner acceptance remain open. Unmetered pattern display is now labelled explicitly.
  A later foreground inspection again had no console errors, showed quarter-note BPM and unmetered engraving;
  its narrow 368px panel limits that observation. Temporary preview tab/process were closed and desktop lease released.
- Exact timing: a scratch-only libopenmpt 0.8.9 extension passed native onset/release/mute-routing probes while the
  unrelated tracker voice's 6,000 frames remained identical. This is a bounded prototype, not production parity.
  Source/patch/probe results are in `scratch/native-score-engine/`. The owner approved local Emscripten 4.0.13 setup
  there on 2026-10-20 for a matching WASM proof; no system PATH change or production binary replacement is authorized
  by that toolchain approval. The timing worker is building the candidate; lead owns integration after review.
  `tablature.playback_plan` now provides occurrence-aware absolute rational events without changing production's
  strict projector. The lead's scratch `plan_probe.py` scheduled 13:8 eighths at tempo 137 on their exact frames,
  with identical PCM for 127/4096-frame host blocks. This only proves scheduling on auxiliary voices.
  Tempo 137 exposed tracker clock drift (88 frames by row 16 at 48kHz); opt-in clock correction is in progress.
  More seriously, raw-score-raw probes proved auxiliary playback leaves parent instrument memory stale, misses
  NNA cuts, and can make unspecified-volume notes 4x louder. Production must execute through normal parent-channel
  note semantics; the auxiliary adapter must not be promoted. `parent_state_probe.py` retains these expected
  mismatches for later validation. Native/WASM boundary diagnostics and 304,660 float samples now match exactly;
  this baseline still reproduces clock drift and parent-state failures. The opt-in Classic clock correction now
  matches native/WASM over 1,023 rows at tempo 137, factor changes and rewind, preserving the default-mode trace.
  Logical-parent dispatch now passes native memory/default-volume, NNA, stale-release, envelope and unrelated-channel
  checks; WASM comparison remains in progress. Five existing instrument tests pass on the candidate DLL. The real
  preparation-to-parent-plan check plays 13:8 tuples with exact onsets and identical 127/4096-frame reads at 44.1,
  48, 88.2 and 96 kHz when release is inside the arrangement. Releases exactly at arrangement end fail preparation
  at all four rates (`scratch/native-score-engine/parent-plan-results.json`). An explicit native tail now fixes
  that failure: all eight actual preparation/13:8 cases pass at four rates and both block sizes
  (`parent-plan-tail-results.json`). The engine's 48 tail cases and 2,383,824 native/WASM samples also match.
  Most raw effect-column ordering remains unqualified; restrictions stay in place except V00..V80 below.
  The V00..V80 experiment exposed a separate default-ramping failure even with no controls: at 96 kHz, error
  reaches 0.0420213 full scale from frame 21022. The same captured fixture matches exactly with ramps disabled;
  this is diagnostic evidence, not a permitted workaround. See `scratch/tab-raw-controls/RESULTS.md`. The engine
  worker confirmed and repaired duplicate note-start processing; the four-rate no-control comparison and
  367,120 native/WASM samples now match. V00..V80 is admitted after the control matrix: all comparisons match
  when reference/candidate use identical read partitions. Three 96-kHz cases inherit ordinary OpenMPT global-volume
  smoothing's small block-partition differences; no tolerance was relaxed or block invariance claimed for V.
  Two focused model preservation/negative-control tests pass. All other raw controls remain refused.
  `api.prepare_playback` now pairs residual IT with a rate-specific exact plan and authoring view; ordinary
  `write_it` refuses a native backing Module. Existing compiler defaults/callers remain strict. 125 focused model,
  sync and compiler tests passed. Actual loading then exposed unnamed score-only channels shrinking from six to
  one; native backing now retains full CNAM length without dummy notes. Three focused backing/legacy/export-guard
  tests passed, including actual loads with 6 and 64 unnamed channels.
  The qualified full Windows DLL and four decoder companions plus matching WASM pair are now vendored locally.
  `tools/native-score-engine.patch` and THIRD_PARTY.md retain the portable source changes and build recipe.
  Vendor digests, docs guard and the actual Python/WASM paired-plan check pass. Linux CI now builds the patched
  shared library and requires native capability; that Linux build and the final package remain unrun.
  Optional-plan `LoadedModule` and browser `engine-core.Song` split reads at exact events and arrangement end,
  preserve int64 identities and enter explicit tail before final releases. Python paired seek reconstructs both
  streams with bounded scratch and cancellation; six candidate checks pass, and eight legacy comparisons match HEAD.
  Browser core gains exact rational row/frame coordinates and bounded fresh replay. The worklet accepts the pair
  atomically, prepares deep seeks while paused, catches edit swaps up from zero, and wraps at exact whole-song/range
  frame boundaries. The native seek/swap/cancel/restart/range test passes with actual WASM; two legacy load/swap
  tests pass. Range preparation can stall a very short loop far into a song; this is a known unresolved real-time
  limit, not a gapless-loop claim. Native SPEED changes still refuse pending rescheduling. The live host now requests
  the paired endpoint at the actual AudioContext rate; State activation and native view integration are in progress.
  Neither adapter authorizes relaxing planner restrictions.
  Native offline `render(repeat=...)` now restarts the backing and event stream together at the exact arrangement
  end, with bounded infinite-repeat output and a tail only after the final pass. The 1/2/infinite-repeat PCM check
  passes against fresh single-pass renders; consumer and cancellation guards pass. This does not add region exports.
  State.prepared_playback and authenticated `/api/playback?sample_rate=...` now return one revision-bound pair
  plus MATCH LEVEL gain, with fresh sample stamps and changes-during-preparation rejection. Five focused tests pass;
  native selected ranges explicitly refuse until paired region/tail rendering is integrated. Host routing validates
  song path, revision and rate before sending the backing bytes, exact plan and gain together.
  Live-load request IDs are now assigned before fetch; stale song/mix responses and stale errors are discarded.
  The out-of-order-response check passes. A leased foreground IAB check on the real TAB fixture started shared
  playback, stopped it, changed fret 0 to 2 and showed F#5 in Pattern with a healthy live-engine status. No browser
  errors occurred; alphaTab logged its expected hidden-container sizing warning while switching tabs. Screenshot:
  `scratch/tab-preview/live-load-after.png`. This verifies the existing strict-projection live route, not the new
  paired endpoint. The temporary browser/server were closed and the desktop lease released.
  Pattern now requests occurrence-specific views and retains raw rows separately from integral display bindings.
  Fractional score markers and ROLL rectangles retain exact source identity; move/resize gestures send rational
  coordinates, and native velocity edits address the score note. The shared cursor keeps its exact score selection
  beside the containing tracker row. Rapid Pattern edits rebase revisions only through successful mutations and
  stop dependent edits after a refusal. Focused cursor, queue, gesture and paired native/WASM playback checks pass.
  The latest syntax/fixture run retains three failures because original page fixtures use raw effects currently
  refused by the native planner. Those fixtures were not weakened. The native batch prototype passes 1,024 exact
  PCM comparisons and 16 invalid-input checks for X/M/D/V; matching WASM qualification is queued. No new effect
  allowance or binary promotion is authorized by the native-only result. Latest native browser acceptance is open.
  The final batch native/WASM matrix now passes 1,040 cases and 55,058,120 float32 samples exactly, including
  same-frame raw instrument inheritance. Full DLL build/decoder qualification is queued before promotion.
  Exact fractional cursor playback and live position reporting pass the actual WASM seek/swap test; TAB consumes
  sample-frame boundaries so a rounded onset cannot highlight the preceding beat. Native whole-song API WAV
  rendering and immutable audio export snapshots now use the paired schedule at the actual oversampled rate.
  Repeat, mute, cancellation, source-change and legacy export checks pass. Region/game-loop and notation-aware
  IT/MIDI conversions remain open and refuse explicitly; residual backing bytes cannot be exported as a song.
- Print preview uses the full occurrence timeline. The authenticated `/score-print` shell
  loads one snapshot and rejects a changed song/revision; the TAB host supplies its current identity. Route/token
  and asset checks passed. Preview now opens in an in-app dialog with Close/Escape rather than an external browser.
  Seven focused browser checks and four syntax/projection checks passed, including selected tracks, pagination,
  generated PDF page counts, stale snapshots and shortcut isolation. Foreground inspection showed both staves,
  but found unreachable left-side content at narrow widths from flex centering. Safe alignment repaired it;
  the same 368px foreground view now shows the first bar, clefs and labels with no console errors/warnings
  (`scratch/tab-preview/print-preview.png` and `print-preview-after.png`). Actual WebView2 print-dialog launch remains
  unexercised. Measure/track navigation and narrow-page geometry passed four focused browser checks, including
  repeated occurrences and unchanged song/history. Parent engine builds were admitted by the coordinator;
  the protected PRNG diagnostic compile failure was repaired and the native build passed.
  The owner has other jobs running and explicitly prefers waiting in the shared queue; do not ask them to close apps.
  Plain Left/Right now crosses written rests, empty patterns and repeated occurrences while retaining track,
  voice/string and shared cursor. Three focused browser checks and syntax validation passed; markers and
  selection modes remain open.
- Remaining acceptance: further changed browser interactions, final candidate packaged smoke and the
  owner's editing/engraving/listening judgement. Full CI has not run on these uncommitted changes.
  The existing package builder accepts --output-dir. One scratch/tab-package candidate built with pinned packages
  and passed exe_check on the TAB fixture, including all four notation assets. This candidate predates the later
  remapping fix and continuing work; rebuild it after final integration. The current dist was not replaced.
- Known implementation limits: the native pair supports exact tuplets and final releases, while standalone IT
  conversion still has tracker-grid limits. Many flow/effect commands refuse; overlapping voices need independent
  channels. Initial or invalidated loop preparation may pause while its destination is reconstructed. Techniques, complete
  measure/repeat tools, interchange and the remaining parity inventory are open. No parity claim or release is made.

### Shared editing contract

- TAB, score and Pattern/ROLL edit one saved song. All views share instruments/samples, arrangement, tempo,
  playback, mixer, selection/playhead and the existing persistent undo/redo. Agent and MIDI edits use the same path.
- A tab edit updates the pattern and playback; a pattern or roll edit updates the tab. Saving/reopening and undo/redo
  preserve both musical content and notation choices. No export/reimport step or independent tab playback engine.
- Preserve chosen strings/frets, tuning/capo, voices, written durations, rests/ties, enharmonic spelling and techniques.
  Pitch alone cannot recover fingering. Preserve valid existing assignments; new tracker notes need deterministic,
  editable assignments. Unplayable notes stay visible and retain their pitch rather than being silently transposed.
- Keep raw tracker effects that have no notation equivalent. Changing a fret must not erase unrelated effects,
  automation or instrument settings. A bend's generated commands need ownership so later edits cannot leave stale slides.
- Pattern reuse and score measures must have explicit correspondence: editing a shared pattern affects its uses;
  editing only one occurrence must explicitly make it independent. Repeats/endings must survive, not just be flattened.
- Preserve exact written timing. Tuplets, mixed meters, swing, note delays, tempo/speed changes and notes crossing
  patterns need an explicit timing map. The current IT row/channel limits are implementation constraints to solve,
  not permission to quantize silently or drop voices. Lossy format exports report their specific losses.

### Current integration points and gaps

Checked on main at d521a74. `vulturetracker/model.py` is an IT playback model: Cell stores note, instrument, volume
and effect, not a score. `notation.py` parses tracker text, not staff notation. `gpimport.py` imports GP3/4/5 into
rows/channels, expands repeats, and documents omitted grace notes, trills, tremolo picking, mix changes, swing and
lyrics. `tools/make_notes.py` has reusable fingering and GP5-writing logic but assumes a transcription grid; it is
not a general score editor. Do not use either conversion as the lossless authoring document.

Extend the saved song with structured score information and stable links to editable events; keep existing songs
working unchanged. Reuse `gui.State.edit_patterns`, `_commit`, `history.py`, the existing edit queue and arrangement
mapping. Audit structural edits and all mutation callers as well as single-cell edits. The exact schema and timing
projection must be proven by round-trip tests before committing to the renderer or broad UI work. Keep IT-specific
Cell semantics intact; do not turn every compiled cell into a second independently mutable score.

### Implementation order and acceptance

1. **Shared document and edit path.** Prove fret -> pattern -> pitch edit -> tab, duration changes, shared patterns,
   undo/redo and save/reopen with one small guitar/bass song. Include an unrelated tracker effect and a sample swap.
   Test exact triplet timing and a cross-measure tie before selecting a schema that only handles straight sixteenths.
2. **Native usable editor.** Tab and staff layout, mouse/keyboard fret entry, navigation, chords/rests/durations,
   selection, clipboard, delete/insert, tuning/capo/string counts, track/measure editing and synchronized transport.
   Evaluate an existing notation renderer against the required editing/hit-testing behavior before building engraving.
   It must run locally in the packaged app and use VultureTracker's shared state and audio.
3. **Rhythm, notation and techniques.** Multiple voices, tuplets/dots/ties, time/key signatures, repeats/endings,
   dynamics, bends/whammy, slides, hammer-ons/pull-offs, harmonics, vibrato, grace notes, trills, tremolo picking,
   palm/dead/ghost notes, let ring, strokes/picking, chord diagrams, text/lyrics and percussion. Check both engraving
   and playback for each behavior; symbols alone do not establish parity.
4. **File and workflow parity.** Enumerate TuxGuitar's import/export formats and editing/tools/printing commands
   against a pinned release, including old/new TG formats and GP generations. Track each behavior as implemented,
   tested, acceptance pending or missing; none are implicitly excluded by this outline. Verify edit/save/reopen in
   both applications for supported interchange features. Add print/PDF layout and remaining tools from that inventory.

Reference starting point: [TuxGuitar 2.1.0 source](https://github.com/helge17/tuxguitar/tree/2.1.0), specifically
[TGNote](https://github.com/helge17/tuxguitar/blob/2.1.0/common/TuxGuitar-lib/src/main/java/app/tuxguitar/song/models/TGNote.java)
and [TGDuration](https://github.com/helge17/tuxguitar/blob/2.1.0/common/TuxGuitar-lib/src/main/java/app/tuxguitar/song/models/TGDuration.java).
These confirm explicit string/fret/voice/tie information and precise rhythmic subdivisions. The full command,
playback and format comparison is still outstanding; development-version documentation is only an inventory aid.

Validation: focused model/edit/round-trip tests, the affected real app page and packaged dependency smoke checks
when relevant; existing CI for the full suite. The owner decides visual editing feel and listening acceptance.
Next action: integrate the bounded native GP5 exporter after its readback/callback qualification; use the
matrix and drum-grace contracts to assign the next disjoint slices without changing the delivered package.
The coordination table and current-delivery entry at the top are authoritative for path ownership and builds.
Preserve the current delivery, selected rollback and older protected artifacts; do not overwrite the owner's
`scratch/tab-preview/user-tryout.yaml`.
The first supplied example failed the owner's listening check, and the second was too quiet. Use the separate
balanced candidate above only
when they choose to audition it. Foreground editing feel and listening acceptance remain the owner's;
headless checks do not close them. Do not autoplay audio during further investigation.
Requeue the deferred idle-PC loop measurement when it will not block builds/pages. Full parity remains the target.
The user requested continued session coordination and a ready-to-try build notification. A quiet 30-minute
thread continuation (`continue-native-tablature-integration`) is active; it follows this handoff and the same
resource queue. It reports meaningful build completion/failure or required input, not unchanged status.

## Deferred proposals

- **Game-loop target engine.** 0.8.0 marks a loop by the export format (WAV `smpl` chunk, OGG/FLAC `LOOPSTART`/`LOOPLENGTH`; MP3 and IT refuse a loop). Whether to target a particular engine or middleware (its own loop metadata, a sidecar file) is deferred by the owner. Source: `vulturetracker/export.py` and `gui._encode`.

Done in 0.8.0 (CHANGELOG.md): game-engine loop export, OpenMPT clipboard both ways, CLI export and collect,
computer-keyboard chord entry, continuous integration and the changelog, MIDI file import.
Done in 0.9.0 (CHANGELOG.md): command-line sections, checkpoints and phrase comparisons.
Done since (CHANGELOG.md, Unreleased): Faust polyphony, MIDI and the live node.

## Owner-declined proposals

Phrase generation, automatic composition and quality scores were declined (2026-09-25); they are recorded here to
avoid proposing them again, not queued for implementation. DMO/plugin hosting was declined the same day, reversed on
2026-10-07 and shipped in 1.3.0 (mix plugins and the RACK tab, CHANGELOG.md).
