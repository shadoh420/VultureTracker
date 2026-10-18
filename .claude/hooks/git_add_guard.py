"""PreToolUse (Bash, PowerShell): refuse `git add -A`/`--all`/`.`/`:/` and `git commit -a`/`-am`/`--all`.
AGENTS.md: stage exact paths. Exit 2 blocks the call and tells the agent why."""
import json
import re
import shlex
import sys

BULK_ADD = {"-A", "--all", ".", ":/", "*"}
VALUE_FLAGS = {"-m", "-F", "-C", "-c", "-t", "--message", "--file", "--template"}  # commit flags whose value follows


def tokens(segment):
    try:
        return shlex.split(segment)
    except ValueError:  # an unbalanced quote (a PowerShell here-string): plain words are close enough
        return segment.split()


def bulk(command):
    for segment in re.split(r"&&|\|\||[;|\n]", command):
        words = tokens(segment)
        if "git" not in words:
            continue
        rest = words[words.index("git") + 1:]
        while len(rest) >= 2 and rest[0] in ("-C", "-c"):  # git -C dir / -c key=value before the subcommand
            rest = rest[2:]
        if not rest:
            continue
        sub, args = rest[0], rest[1:]
        if sub == "add" and BULK_ADD & set(args):
            return "git add with -A, --all or '.'"
        if sub == "commit":
            skip = False
            for a in args:
                if skip:
                    skip = False
                elif a in VALUE_FLAGS:
                    skip = True
                elif a == "--all" or (re.fullmatch(r"-[A-Za-z]+", a) and "a" in a[1:]):
                    return "git commit -a"
    return None


if __name__ == "__main__":
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    found = bulk(command)
    if found:
        print(f"Blocked {found}: AGENTS.md says stage exact paths (git add <path> ...), then review git diff --cached.",
              file=sys.stderr)
        sys.exit(2)
