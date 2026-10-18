"""PostToolUse (Edit, Write): after an edit to a file tests/test_docs.py checks (the docs, CI's workflows, release.py,
a test module CI must list), run that test (well under a second). Exit 2 shows a failure to the agent."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKED = {"AGENTS.md", "README.md", "GUIDE.md", "SONG_FORMAT.md", "SAMPLING.md", "tools/release.py"}


def checked(path):
    try:
        rel = Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:  # another checkout or folder
        return False
    return rel in CHECKED or rel.startswith(".github/") or (rel.startswith("tests/test_") and rel.endswith(".py"))


if __name__ == "__main__":
    path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
    if path and checked(path):
        run = subprocess.run([sys.executable, "-m", "unittest", "tests.test_docs"], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
        if run.returncode:
            print(f"tests.test_docs fails after this edit:\n{run.stderr[-3000:]}", file=sys.stderr)
            sys.exit(2)
