"""The docs name what the code has: SONG_FORMAT's effect and volume tables match what the compiler accepts, every
command is in README or GUIDE, every agent tool is in GUIDE's agent section."""
import re
import string
import subprocess
import sys
import unittest
from pathlib import Path

from vulturetracker import agent
from vulturetracker.notation import VOLCMDS, NotationError, parse_cell

ROOT = Path(__file__).resolve().parent.parent


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def section(text, start, end):
    """The text from the line holding `start` to the next line holding `end`."""
    i = text.index(start)
    return text[i:text.index(end, i + len(start))]


class TestDocs(unittest.TestCase):
    def test_effect_column_table_matches_the_compiler(self):
        table = section(read("SONG_FORMAT.md"), "### 6.3 Effect column", "`Sxy` subcommands")
        documented = set(re.findall(r"^\| `([A-Z])(?:xx|xy)` \|", table, re.M))
        accepted = set()
        for letter in string.ascii_letters + string.digits:
            try:
                if parse_cell(f"... .. ... {letter}00").effect:  # an effect, not a volume command (v00)
                    accepted.add(letter)
            except NotationError:
                pass
        self.assertEqual(documented, accepted)

    def test_volume_column_table_matches_the_compiler(self):
        table = section(read("SONG_FORMAT.md"), "### 6.2 Volume column", "### 6.3")
        self.assertEqual(set(re.findall(r"^\| `([a-z])NN` \|", table, re.M)), set(VOLCMDS))

    def test_every_command_is_documented(self):
        out = subprocess.run([sys.executable, "-m", "vulturetracker", "--help"], capture_output=True, text=True,
                             cwd=ROOT, check=True).stdout
        commands = re.search(r"\{([^}]+)\}", out).group(1).split(",")
        self.assertIn("build", commands)
        docs = read("README.md") + read("GUIDE.md")
        missing = [c for c in commands if not re.search(rf"vulturetracker {re.escape(c)}\b|`{re.escape(c)}[` ]", docs)]
        self.assertEqual(missing, [])

    def test_every_agent_tool_is_in_the_guide(self):
        text = section(read("GUIDE.md"), "**Agents: the AGENT panel and MCP.**", "\n## ")
        self.assertGreater(len(agent.TOOLS), 50)
        self.assertEqual([n for n in sorted(agent.TOOLS) if f"`{n}`" not in text], [])

    def test_ci_runs_every_test_module(self):
        """tests.yml: one run per ref (a newer push cancels the older), pip cached, and every tests/test_*.py in the
        portable list or the page step; AGENTS.md's command names the same portable list."""
        import yaml
        ci = read(".github/workflows/tests.yml")
        flow = yaml.safe_load(ci)
        self.assertTrue(flow["concurrency"]["cancel-in-progress"])
        setups = [s for job in flow["jobs"].values() for s in job["steps"] if "setup-python" in s.get("uses", "")]
        self.assertTrue(setups and all(s["with"].get("cache") == "pip" for s in setups))
        portable = flow["env"]["PORTABLE"].split()
        page = flow["jobs"]["tests"]["steps"][-1]["run"].split()
        modules = {f"tests.{p.stem}" for p in (ROOT / "tests").glob("test_*.py")}
        self.assertEqual(modules - set(portable) - set(page), set())
        self.assertTrue(all(m.endswith("_page") for m in page if m.startswith("tests.")))
        agents = re.search(r"`python -m unittest (tests\.[^`]+)`", read("AGENTS.md")).group(1).split()
        self.assertEqual(sorted(agents), sorted(portable))

    def test_bug_form_names_the_log(self):
        """The issue form asks for the version, the steps, the log at the path the app writes it and the song; README
        points to it."""
        import yaml
        from vulturetracker import gui
        form = yaml.safe_load(read(".github/ISSUE_TEMPLATE/bug.yml"))
        fields = {b["id"]: b for b in form["body"] if "id" in b}
        self.assertEqual(sorted(fields), ["log", "song", "steps", "version"])
        self.assertTrue(fields["version"]["validations"]["required"])
        where = rf"%APPDATA%\{gui.LOG.parent.name}\{gui.LOG.name}"
        self.assertIn(where, fields["log"]["attributes"]["description"])
        readme = section(read("README.md"), "## Reporting a problem", "\n## ")
        self.assertIn(where, readme)
        self.assertIn("SECURITY.md", readme)


if __name__ == "__main__":
    unittest.main()
