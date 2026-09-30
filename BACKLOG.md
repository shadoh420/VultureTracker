# VultureTracker backlog

The focused 0.7.0 scope is: fixes for the 22 reproduced audit defects, bounded history,
recording alongside playback, MIDI chord capture, conversion to editable literal patterns,
configurable beat spacing, and shared phrase-sample storage.

## Deferred proposals

- **CLI access to editing and finishing workflows.** Expose export, stems, sample collection, sections, checkpoints and phrase comparisons without requiring the page. Source: `vulturetracker/__main__.py` command list versus `gui.py` routes; deferred to keep 0.7.0 focused on interactive workflows.
- **Game-engine loop export.** Export an explicitly selected musical loop with loop boundaries and a separate release tail. Source: `vulturetracker/export.py` regions and tails; deferred until the target engine and metadata format are chosen.
- **Faust polyphony, MIDI and live audio.** Extend the current single-voice preview to multiple voices, MIDI control and a live audio node. Source: `suite/HANDOFF.md` Faust backlog and `web/faust-render.mjs`; deferred because voice allocation needs separate design and audio validation.
- **Guitar Pro tab view, fretboard entry and GPX support.** Add a read-only tab view first, then fretboard editing and GPX import alongside the existing importer. Source: `suite/HANDOFF.md` Guitar Pro backlog and `vulturetracker/gpimport.py`; deferred because round-trip editing needs a richer model than imported cells.

- **OpenMPT clipboard paste.** Accept the `ModPlug Tracker IT` clipboard format in the pattern editor. Source: the analysis draft and `vulturetracker/gui.html` copy/paste handlers; deferred pending explicit notation conversion and round-trip cases.
- **Continuous integration and a changelog.** Automate the portable test suite and keep release changes in `CHANGELOG.md`. Source: the analysis draft, the absence of `.github` workflows and GitHub-only release notes; deferred from the focused application scope.
- **Computer-keyboard chord entry.** Extend chord capture beyond MIDI to the computer piano keys. Source: the draft MIDI/piano-key chord proposal and `GUIDE.md` entry controls; 0.7.0 implements MIDI chords only.

## Owner-declined proposals

DMO/plugin hosting, phrase generation, automatic composition and quality scores were declined;
they are recorded here to avoid proposing them again, not queued for implementation.
