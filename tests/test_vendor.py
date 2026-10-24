"""The vendored third-party files (vendor/, vulturetracker/web/) are the ones THIRD_PARTY.md lists, byte for byte: its
"Vendored files" table names each file's SHA-256 (text files hashed with LF endings, as git keeps them)."""
import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWN = {"vulturetracker/web/engine-core.js", "vulturetracker/web/engine-worklet.js", "vulturetracker/web/faust-render.mjs",
       "vulturetracker/web/tablature.js", "vulturetracker/web/tablature.css", "vulturetracker/web/score-print.html"}


def digest(p):
    data = p.read_bytes()
    return hashlib.sha256(data if b"\0" in data else data.replace(b"\r\n", b"\n")).hexdigest()


class TestVendor(unittest.TestCase):
    def test_every_vendored_file_matches_its_listed_digest(self):
        table = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|", (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8"), re.M))
        present = {p.relative_to(ROOT).as_posix() for base in ("vendor", "vulturetracker/web")
                   for p in (ROOT / base).rglob("*") if p.is_file() and "__pycache__" not in p.parts}
        self.assertEqual(present - OWN, set(table), "THIRD_PARTY.md's table and the vendored files differ")
        for rel, want in table.items():
            self.assertEqual(digest(ROOT / rel), want, rel)


if __name__ == "__main__":
    unittest.main()
