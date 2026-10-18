---
name: release
description: Release VultureTracker X.Y.Z with tools/release.py, the exe build, exe_check and the digest checks.
argument-hint: X.Y.Z
disable-model-invocation: true
---

Release VultureTracker $ARGUMENTS. AGENTS.md's "Release recipe" is the source; this is its order with the stops.

1. **Check before anything is written.** `git status`: on `main`, nothing unrelated staged, and the work being released
   is committed. `CHANGELOG.md` has a `## Unreleased` section describing this release; if it is empty or missing,
   draft it from `git log v<last>..HEAD` and show it to the owner before going on. Check that CI is green on `HEAD`
   (`gh run list --branch main --limit 3`). Do not rerun the full suite locally: CI covers it.
2. `python tools/release.py $ARGUMENTS --dry-run`, then without `--dry-run`. It bumps `__version__`, retitles the
   CHANGELOG section and writes `dist/release-notes-$ARGUMENTS.md`, then prints the remaining commands. Follow the
   printed commands in order, one per call (PowerShell 5.1 has no `&&`).
3. **Stop before the commit:** show `git diff --cached` (only `vulturetracker/__init__.py` and `CHANGELOG.md`) and
   ask the owner to confirm. Then commit "Version $ARGUMENTS" (the attribution lines from the conversation apply)
   and tag it with `git tag -a`.
4. **Stop before the push:** the repository is public, so pushing `main` and the tag publishes it. Ask first. The
   tag push also starts `.github/workflows/build.yml`.
5. Build: `python tools/build_exe.py` (run it in the background; it refuses when installed packages differ from
   `requirements-build.txt`), then `python tools/exe_check.py dist/vulturetracker.exe`. A failed check stops the release.
6. `python tools/release.py $ARGUMENTS --digests`. Replace the notes file's two TODO lines by editing it with the edit
   tool. Never touch it with PowerShell 5.1 text cmdlets (that gave the 0.2.1 notes a BOM and mojibake). Put the
   exe's sha256 in README's Install section.
7. **Stop before `gh release create`:** show the notes and ask. Then run the printed `gh release create` and
   `python tools/release.py $ARGUMENTS --check`. Report the check's lines as printed.
8. The README digest edit is a new change: commit it only when the owner says so (stage the exact path).

The published exe is the owner's local build, not the CI artifact, unless the owner decides otherwise.
