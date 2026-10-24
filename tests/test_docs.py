"""The docs name what the code has: SONG_FORMAT's effect and volume tables match what the compiler accepts, every
command is in README or GUIDE, every agent tool is in GUIDE's agent section. The release tooling too: the exe build job
on tags, and `release.py --check` failing on a planted mismatch."""
import hashlib
import importlib.util
import io
import re
import tempfile
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock
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
    """The text from `start` to the next `end` (or to the end of the text)."""
    i = text.index(start)
    j = text.find(end, i + len(start))
    return text[i:j if j >= 0 else None]


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

    def test_every_printed_effect_is_in_sampling(self):
        from vulturetracker import dsp
        table = section(read("SAMPLING.md"), "## Printed effects", "\n## ")
        self.assertEqual([n for n in dsp.PRINTED if f"| `{n}` |" not in table], [])

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
        page = next(s["run"] for s in flow["jobs"]["tests"]["steps"] if s.get("name") == "Page tests").split()
        modules = {f"tests.{p.stem}" for p in (ROOT / "tests").glob("test_*.py")}
        self.assertEqual(modules - set(portable) - set(page), set())
        # Native workflow regression modules run together with their browser
        # cases in the Chromium job. Windows model coverage is also run locally.
        mixed = {'tests.test_rehearsal_delivery', 'tests.test_real_interchange', 'tests.test_rehearsal_playback',
                 'tests.test_complex_rhythm', 'tests.test_complex_interchange', 'tests.test_complex_routing',
                 'tests.test_expressive_gp5', 'tests.test_advanced_rhythm', 'tests.test_advanced_timing', 'tests.test_repeat_rehearsal', 'tests.test_part_adaptation'}
        self.assertTrue(all(m.endswith("_page") or m in mixed for m in page if m.startswith("tests.")))
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


def release_tool():
    spec = importlib.util.spec_from_file_location("release", ROOT / "tools" / "release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestReleaseTools(unittest.TestCase):
    def test_build_job_on_tags_checks_and_uploads_the_release_files(self):
        """build.yml: on v* tags and by hand, Windows and the exe's Python, build_exe then exe_check on the built exe,
        and the files release.py publishes uploaded; AGENTS.md says which exe is published."""
        import yaml
        flow = yaml.safe_load(read(".github/workflows/build.yml"))
        on = flow.get("on", flow.get(True))  # YAML 1.1 reads a bare `on` key as True
        self.assertEqual(on["push"]["tags"], ["v*"])
        self.assertIn("workflow_dispatch", on)
        job, = flow["jobs"].values()
        self.assertEqual(job["runs-on"], "windows-latest")
        runs = [s.get("run", "") for s in job["steps"]]
        python = [s["with"]["python-version"] for s in job["steps"] if "setup-python" in s.get("uses", "")]
        self.assertEqual(python, ["3.14"])
        build = next(i for i, r in enumerate(runs) if "tools/build_exe.py" in r)
        check = next(i for i, r in enumerate(runs) if "tools/exe_check.py dist/vulturetracker.exe" in r)
        self.assertLess(build, check)
        upload = next(s for s in job["steps"] if "upload-artifact" in s.get("uses", ""))
        self.assertEqual(upload["with"]["path"].split(), [f"dist/{a}" for a in release_tool().ASSETS])
        self.assertTrue(".github/workflows/build.yml" in read("AGENTS.md"), "AGENTS.md names the build job")

    def test_release_check_fails_on_a_planted_mismatch(self):
        """--check against a published body: the right digests pass; one wrong digest, a missing line, a BOM or a
        leftover TODO each fail, naming what is wrong."""
        rel = release_tool()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "dist").mkdir()
            digest = {}
            for name in rel.ASSETS:
                data = f"pretend {name}".encode()
                (Path(tmp) / "dist" / name).write_bytes(data)
                digest[name] = hashlib.sha256(data).hexdigest()
            good = "Notes.\n\n```\n" + "".join(f"{digest[a]} {a}\n" for a in rel.ASSETS) + "```\n"

            def run(body):
                out = io.StringIO()
                with mock.patch.object(rel, "ROOT", Path(tmp)), redirect_stdout(out), mock.patch.object(
                        rel.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=body, stderr="")):
                    return rel.check("9.9.9"), out.getvalue()

            code, out = run(good)
            self.assertEqual(code, 0, out)
            self.assertIn("release check: passed", out)
            planted = good.replace(digest["ffmpeg.exe"], "0" * 64)
            code, out = run(planted)
            self.assertEqual(code, 1)
            self.assertRegex(out, r"FAIL ffmpeg\.exe: published 0{64}")
            self.assertNotIn("FAIL vulturetracker.exe", out)
            code, out = run(good.replace(f"{digest['vulturetracker-win64.zip']} vulturetracker-win64.zip\n", ""))
            self.assertEqual(code, 1)
            self.assertIn("FAIL vulturetracker-win64.zip: published nothing", out)
            self.assertEqual(run("\ufeff" + good)[0], 1)
            self.assertEqual(run(good + "**Validation:** TODO write it\n")[0], 1)


if __name__ == "__main__":
    unittest.main()
