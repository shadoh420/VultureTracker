"""The mechanical part of a release. It never commits, tags, pushes, builds or publishes: it edits two files, writes the
release-notes file and prints the commands for the owner to run, in order.

  python tools/release.py X.Y.Z             bump __version__, retitle CHANGELOG.md's "## Unreleased" as X.Y.Z (today),
                                            write dist/release-notes-X.Y.Z.md (UTF-8, no BOM) and print the commands
  python tools/release.py X.Y.Z --digests   after the build: put the SHA-256 of the three dist files into the notes file
  python tools/release.py X.Y.Z --check     after publishing: compare the digests in the GitHub release body with dist/
  --dry-run                                 print what the first two modes would write, write nothing

The notes file is written from Python on purpose: PowerShell 5.1's text cmdlets gave the 0.2.1 notes a BOM and "â†’" for
"→". The three digests sit in the notes as `<hex> <file>` lines (exe, ffmpeg, zip), the order of every release so far."""
import argparse
import datetime as dt
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "vulturetracker" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
ASSETS = ("vulturetracker.exe", "ffmpeg.exe", "vulturetracker-win64.zip")
REPO = "shadoh420/VultureTracker"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
DIGEST_RE = re.compile(r"^([0-9a-f]{64}|<pending>)\s+(" + "|".join(re.escape(a) for a in ASSETS) + r")\s*$", re.M)
TRAILER = """\
**Upgrade note:** TODO write it: what changed for existing songs and modules, or "nothing else changed"

**Validation:** TODO write it: which tests ran where, and what `python tools/exe_check.py dist/vulturetracker.exe` reported

`vulturetracker-win64.zip` contains the executable, ffmpeg, licences and demos. The separate `vulturetracker.exe` and `ffmpeg.exe` assets can update an existing installation; keep them beside each other.

SHA-256:
```
<pending> vulturetracker.exe
<pending> ffmpeg.exe
<pending> vulturetracker-win64.zip
```
"""


def unwrap(section):
    """The CHANGELOG wraps its bullets at 120 columns; GitHub shows a release body's newlines, so each bullet and
    paragraph becomes one line (a non-blank line that starts neither a bullet nor a heading joins the line before)."""
    out = []
    for line in section.splitlines():
        if line.strip() and out and out[-1].strip() and not line.startswith(("- ", "#")):
            out[-1] += " " + line.strip()
        else:
            out.append(line)
    return "\n".join(out)


def read(path):
    """(text with \\n endings, the file's own newline)"""
    raw = path.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), nl


def write(path, text, nl, dry):
    if dry:
        print(f"--- would write {path.relative_to(ROOT)}:\n{text if len(text) < 3000 else text[:3000] + '...'}\n---")
    else:
        path.write_bytes(text.replace("\n", nl).encode("utf-8"))  # no BOM, the file's own endings
        print(f"wrote {path.relative_to(ROOT)}")


def current_version():
    m = re.search(r'^__version__ = "([^"]+)"', read(INIT)[0], re.M)
    if not m:
        sys.exit(f"no __version__ in {INIT}")
    return m.group(1)


def as_tuple(v):
    return tuple(int(x) for x in v.split("."))


def notes_path(version):
    return ROOT / "dist" / f"release-notes-{version}.md"


def prepare(version, dry):
    cur = current_version()
    if as_tuple(version) <= as_tuple(cur):
        sys.exit(f"{version} is not newer than the current __version__ {cur}")
    text, nl = read(CHANGELOG)
    m = re.search(r"^## Unreleased[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        sys.exit("CHANGELOG.md has no '## Unreleased' section: write the release's entry under that heading first")
    section = m.group(1).strip("\n")
    today = dt.date.today().isoformat()
    changelog = text[:m.start()] + f"## {version} ({today})\n" + text[m.start(1):]
    init, init_nl = read(INIT)
    init = init.replace(f'__version__ = "{cur}"', f'__version__ = "{version}"')
    notes = unwrap(section) + "\n\n" + TRAILER
    if not dry:
        notes_path(version).parent.mkdir(exist_ok=True)
    write(INIT, init, init_nl, dry)
    write(CHANGELOG, changelog, nl, dry)
    write(notes_path(version), notes, "\n", dry)
    np = notes_path(version).relative_to(ROOT).as_posix()
    print(f"""
{version} is prepared{' (dry run: nothing written)' if dry else ''}. The CHANGELOG section it releases:

{section}

Now run, in order (each line on its own; PowerShell 5.1 has no &&):

  git add vulturetracker/__init__.py CHANGELOG.md
  git diff --cached
  git commit -m "Version {version}"
  git tag -a v{version} -m "Version {version}"
  git push origin main v{version}
  python tools/build_exe.py
  python tools/exe_check.py dist/vulturetracker.exe
  python tools/release.py {version} --digests
  (edit {np}: replace its two TODO lines; keep it UTF-8, no BOM, no PowerShell 5.1 text cmdlets)
  gh release create v{version} dist/vulturetracker-win64.zip dist/vulturetracker.exe dist/ffmpeg.exe --title "VultureTracker {version}" --notes-file {np} --latest
  python tools/release.py {version} --check
""")


def digests_of():
    out = {}
    for name in ASSETS:
        p = ROOT / "dist" / name
        if not p.exists():
            sys.exit(f"missing {p}: build first (python tools/build_exe.py)")
        out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def digests(version, dry):
    if version != current_version():
        sys.exit(f"__version__ is {current_version()}, not {version}: prepare it first (python tools/release.py {version})")
    path = notes_path(version)
    if not path.exists():
        sys.exit(f"no {path}: prepare it first (python tools/release.py {version})")
    d = digests_of()
    text, nl = read(path)
    text, n = DIGEST_RE.subn(lambda m: f"{d[m.group(2)]} {m.group(2)}", text)
    if n != len(ASSETS):
        sys.exit(f"the notes file has {n} digest lines, expected {len(ASSETS)}: restore the SHA-256 block")
    for name, h in d.items():
        print(f"{h} {name}")
    write(path, text, nl, dry)
    if "TODO " in text:
        print(f"note: {path.relative_to(ROOT)} still has TODO lines to write before gh release create")


def check(version):
    r = subprocess.run(["gh", "api", f"repos/{REPO}/releases/tags/v{version}", "--jq", ".body"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"gh api failed: {r.stderr.strip()}")
    body = r.stdout
    bad = 0
    if body.startswith("﻿") or "â€" in body or "Ã" in body:
        print("FAIL the published body has a BOM or mojibake (the notes were not written as plain UTF-8)")
        bad += 1
    if "TODO " in body:
        print("FAIL the published body still has a TODO line (the notes' Upgrade note or Validation)")
        bad += 1
    published = {m.group(2): m.group(1) for m in DIGEST_RE.finditer(body)}
    local = digests_of()
    for name in ASSETS:
        got = published.get(name)
        if got == local[name]:
            print(f"ok {name} {got}")
        else:
            print(f"FAIL {name}: published {got or 'nothing'}, dist/ has {local[name]}")
            bad += 1
    print("release check:", "FAILED" if bad else "passed")
    return 1 if bad else 0


def main(argv=None):
    sys.stdout.reconfigure(errors="replace")  # the CHANGELOG has "→"; a cp1252 console must not stop the script
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", help="the version to release, X.Y.Z")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--digests", action="store_true", help="put the SHA-256 of the dist/ files into the notes file")
    g.add_argument("--check", action="store_true", help="verify the published release body's digests against dist/")
    ap.add_argument("--dry-run", action="store_true", help="print what would be written, write nothing")
    a = ap.parse_args(argv)
    if not VERSION_RE.match(a.version):
        ap.error(f"version must be X.Y.Z, not {a.version!r}")
    if a.check:
        return check(a.version)
    if a.digests:
        return digests(a.version, a.dry_run)
    return prepare(a.version, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
