"""The agent's tools: one list, run in the app's process against the open song (gui.State), reached two ways: the MCP
server (`python -m vulturetracker mcp`, mcp.py), which an agent such as Claude Code runs and which calls the running app
over its local HTTP port, and the app's optional chat panel (Chat below: Claude Code on the owner's own login, run
headless with the MCP server attached; the Anthropic API; or a local model behind an OpenAI-compatible server such as
Ollama, LM Studio or llama.cpp).

What the tools leave to the owner, as AGENTS.md has it: no tool moves a fader, a channel volume or pan, or the mix
volume (levels are the owner's); an entry marked `approved: true` (a pattern, a channel, a sample) is refused; sounds
are offered as tryout candidates, which the owner hears and picks. Every edit is one undo step in the app and marks the
patterns it writes `by: agent`. The tools measure (LUFS, true peak, correlation); they cannot hear."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, plugins
from .fileio import atomic_write, user_dir

TOOLS = {}  # name -> (description, JSON schema of the arguments, function(state, args))


def tool(name, description, properties=None, required=()):
    def wrap(fn):
        TOOLS[name] = (description, {"type": "object", "properties": properties or {}, "required": list(required)}, fn)
        return fn
    return wrap


def tool_list():
    return [{"name": n, "description": d, "input_schema": s} for n, (d, s, _) in TOOLS.items()]


def run(st, name, args):
    """Tool `name` run with `args` on State `st`: its JSON-able result, or {"error": message}. Logged on the State, so the
    page shows what an agent did (from the chat panel or over MCP)."""
    if name not in TOOLS:
        return {"error": f"no tool {name!r} (tools: {', '.join(TOOLS)})"}
    t0 = time.time()
    try:
        if st is None:
            raise ValueError("no song is open in the app")
        out = TOOLS[name][2](st, args or {})
    except Exception as e:  # noqa: BLE001 - a tool's failure goes back to the agent as its result
        out = {"error": str(e).replace("ValueError: ", "")}
    if st is not None:
        st.agent_log.append({"time": round(t0, 1), "tool": name, "args": _short(args), "error": out.get("error"),
                             "summary": _short(out.get("summary") or {k: v for k, v in out.items() if k != "rows"}, 160)})
        del st.agent_log[:-200]
    return out


def _short(x, n=120):
    s = json.dumps(x, separators=(",", ":"), default=str)
    return s if len(s) <= n else s[:n - 1] + "…"


# ---------------------------------------------------------------- what the song holds

def _channels(st):
    chans = (st.song.get("module") or {}).get("channels")
    return chans if isinstance(chans, list) else []


def _approved_channels(st):
    return {i for i, c in enumerate(_channels(st)) if isinstance(c, dict) and c.get("approved")}


def _chain(f, ch):
    out, n, P = [], f["channel_plugins"][ch], f.get("plugins") or {}
    while n and n in P and n not in out:
        out.append(n)
        n = P[n].get("output")
    return out


def _pattern_index(st, ref):
    """A pattern by its name, or by a play-order position (an int: the song overview's `order`)."""
    st._need_compiled()
    if isinstance(ref, int) and not isinstance(ref, bool):
        orders = st.facts["orders"]
        if not 0 <= ref < len(orders):
            raise ValueError(f"no order {ref} (the song plays {len(orders)} orders, 0..{len(orders) - 1})")
        return orders[ref]["index"]
    for i, p in enumerate(st.mod.patterns):
        if p.name == str(ref):
            return i
    raise ValueError(f"no pattern {ref!r}")


def _rows_text(st, index, r0=0, r1=None, chans=None):
    rows = st.pattern_rows(index)["rows"]
    r1 = len(rows) - 1 if r1 is None else min(int(r1), len(rows) - 1)
    pick = (lambda row: [row[c] for c in chans if c < len(row)]) if chans else (lambda row: row)
    return [f"{r:02d}: " + " | ".join(pick(rows[r])) for r in range(max(0, int(r0)), r1 + 1)]


@tool("song_overview", "The open song: title, tempo, speed, BPM, key, channels (1-based numbers, names, their effect "
      "chains, approved marks), the play order (order position, pattern, rows, start time), sections, patterns (rows, "
      "who wrote them, approved), sample slots and instruments, warnings, and the listening notes count.")
def song_overview(st, a):
    st._need_compiled()
    f, song = st.facts, st.song
    mod = song.get("module") or {}
    chans = _channels(st)
    pats = []
    for p in st.mod.patterns:
        e = st.pattern_entry(p.name)
        pats.append({"name": p.name, "rows": len(p.rows), "by": e.get("by"), "approved": bool(e.get("approved"))})
    samples = [{"slot": int(k), "name": (v or {}).get("name"), "file": (v or {}).get("file"),
                "approved": bool((v or {}).get("approved"))} for k, v in (song.get("samples") or {}).items()]
    return {
        "path": str(st.song_path), "title": f["title"], "tempo": f["tempo"], "speed": f["speed"], "bpm": f["bpm"],
        "rows_per_beat": f["highlight"][0], "rows_per_bar": f["highlight"][1], "key": mod.get("key"),
        "channels": [{"channel": i + 1, "name": n, "effects": [f["plugins"][k]["effect"] for k in _chain(f, i)],
                      "approved": bool(i < len(chans) and isinstance(chans[i], dict) and chans[i].get("approved"))}
                     for i, n in enumerate(f["channels"])],
        "orders": [{"order": i, "pattern": o["pattern"], "rows": o["rows"], "start_s": round(o["start"], 2)}
                   for i, o in enumerate(f["orders"])],
        "duration_s": round(f["duration"], 2), "sections": song.get("sections"), "patterns": pats,
        "samples": samples, "instruments": f["instruments"], "warnings": f["warnings"][:30],
        "listening_notes": len(st.notes or []), "undo_steps": len(st.history),
        "summary": f"{f['title']}: {len(f['channels'])} channels, {len(f['orders'])} orders, {round(f['duration'])} s",
    }


@tool("read_pattern", "A pattern's rows as text, one line per row: 'RR: cell | cell | ...', each cell 'note instrument "
      "volume effect' as in OpenMPT ('C-5 01 v64 A06', '...' empty, '===' note off, '^^^' cut). Rows count from 0.",
      {"pattern": {"type": ["string", "integer"], "description": "a pattern name, or a play-order position"},
       "from_row": {"type": "integer"}, "to_row": {"type": "integer"},
       "channels": {"type": "array", "items": {"type": "integer"}, "description": "1-based channel numbers (default all)"}},
      ["pattern"])
def read_pattern(st, a):
    i = _pattern_index(st, a["pattern"])
    chans = [c - 1 for c in a["channels"]] if a.get("channels") else None
    rows = _rows_text(st, i, a.get("from_row", 0), a.get("to_row"), chans)
    return {"pattern": st.mod.patterns[i].name, "channels": [c + 1 for c in chans] if chans else "all", "rows": rows,
            "summary": f"{len(rows)} rows of {st.mod.patterns[i].name}"}


@tool("get_selection", "What the owner has selected in the app's pattern view (or where the cursor is): the pattern, "
      "rows and channels, their cells, and the channels sounding at its first row. Start here when the owner says "
      "'this', 'here' or 'these bars'.")
def get_selection(st, a):
    sel = st.selection
    if not sel:
        return {"selection": None, "summary": "nothing selected in the app"}
    from .gui import sounding_table
    i = _pattern_index(st, sel["pattern"])
    r0, r1 = sel["rows"]
    c0, c1 = sel["channels"]
    chans = list(range(c0, c1 + 1))
    sounding = []
    try:
        sounding = sounding_table(st.mod, st.facts)[sel["order"]][r0]
    except (IndexError, KeyError, TypeError):
        pass
    return {"pattern": sel["pattern"], "order": sel.get("order"), "rows": [r0, r1], "channels": [c + 1 for c in chans],
            "channel_names": [st.facts["channels"][c] for c in chans if c < len(st.facts["channels"])],
            "cells": _rows_text(st, i, r0, r1, chans),
            "summary": f"{sel['pattern']} rows {r0}-{r1}, channels {c0 + 1}-{c1 + 1}",
            "sounding_at_first_row": [{"channel": s["ch"] + 1, "name": s["name"], "sample": s["sample"], "note": s["note"]}
                                      for s in sounding]}


@tool("write_cells", "Write cells into a pattern, as one undo step (the pattern is marked by: agent). Refused for an "
      "approved pattern or channel. A cell is 'note instrument volume effect', e.g. 'C-5 01 v48 ...', '... .. ... SF1' "
      "or '=== .. ... ...'; parts left out stay as they are only when you write them as '..'/'...'.",
      {"pattern": {"type": ["string", "integer"]},
       "cells": {"type": "array", "items": {"type": "object", "properties": {
           "row": {"type": "integer"}, "channel": {"type": "integer", "description": "1-based"},
           "cell": {"type": "string"}}, "required": ["row", "channel", "cell"]}}},
      ["pattern", "cells"])
def write_cells(st, a):
    i = _pattern_index(st, a["pattern"])
    name = st.mod.patterns[i].name
    if st.pattern_entry(name).get("approved"):
        raise ValueError(f"pattern {name} is approved by the owner: leave it, or ask them to clear the mark")
    locked = _approved_channels(st)
    cells = [{"row": int(c["row"]), "ch": int(c["channel"]) - 1, "cell": str(c["cell"])} for c in a["cells"]]
    bad = sorted({c["ch"] + 1 for c in cells if c["ch"] in locked})
    if bad:
        raise ValueError(f"channel{'s' if len(bad) > 1 else ''} {', '.join(map(str, bad))} approved by the owner: not written")
    st.edit_patterns([(i, cells)], who="agent")
    return {"ok": True, "summary": f"wrote {len(cells)} cells in {name} (one undo step)"}


@tool("set_orders", "The play order: a list of pattern names ('+++' skip, '---' end). One undo step.",
      {"orders": {"type": "array", "items": {"type": "string"}}}, ["orders"])
def set_orders(st, a):
    st.song_edit([{"op": "orders", "orders": [str(o) for o in a["orders"]]}])
    return {"ok": True, "summary": f"{len(a['orders'])} orders"}


@tool("new_pattern", "A new empty pattern (or a copy of `clone_from`), optionally put into the play order at "
      "`insert_at` (an order position). One undo step.",
      {"name": {"type": "string"}, "rows": {"type": "integer"}, "clone_from": {"type": "string"},
       "insert_at": {"type": "integer"}}, ["name"])
def new_pattern(st, a):
    ops = [{"op": "pattern_clone", "src": a["clone_from"], "name": a["name"]} if a.get("clone_from")
           else {"op": "pattern_new", "name": a["name"], "rows": int(a.get("rows") or 64)}]
    if not a.get("clone_from"):
        ops.append({"op": "mark", "what": "pattern", "key": a["name"], "by": "agent"})
    if a.get("insert_at") is not None:
        orders = [str(o) for o in st.song.get("orders") or []]
        orders.insert(int(a["insert_at"]), a["name"])
        ops.append({"op": "orders", "orders": orders})
    st.song_edit(ops)
    return {"ok": True, "summary": f"pattern {a['name']}"}


SETTABLE = ("tempo", "speed", "title", "rows_per_beat", "rows_per_bar", "key")


@tool("set_module", f"A song setting: one of {', '.join(SETTABLE)} (key: e.g. 'A minor', 'D dorian'). Not the "
      "levels: mix volume and global volume are the owner's. One undo step.",
      {"key": {"type": "string", "enum": list(SETTABLE)}, "value": {"type": ["string", "integer"]}}, ["key", "value"])
def set_module(st, a):
    if a["key"] not in SETTABLE:
        raise ValueError(f"settable here: {', '.join(SETTABLE)} (levels are the owner's)")
    st.song_edit([{"op": "module", "key": a["key"], "value": a["value"]}])
    return {"ok": True, "summary": f"{a['key']} = {a['value']}"}


@tool("describe_effects", "The effects the rack has (OpenMPT's built-in DMO effects): each one's parameters with their "
      "units, ranges and defaults.")
def describe_effects(st, a):
    return {"effects": plugins.describe(), "macro_for_parameter": "SFx macro F0F + (128 + index, 3 hex digits) + z: "
            "then SFx and Zxx (00-7F) in a channel set that parameter of the channel's first plugin"}


@tool("set_plugins", "The rack: `plugins` {number: {effect, name, output (next plugin's number; none = master), bypass, "
      "and parameters in their units}} replaces module.plugins whole; `channel_plugins` {channel (1-based): plugin number "
      "or 0} routes channels; `macros` {SF1..SFF: macro text} replaces module.macros. Read song_overview first and send "
      "every plugin you keep. Refused when it would change an approved channel's chain. One undo step.",
      {"plugins": {"type": "object"}, "channel_plugins": {"type": "object"}, "macros": {"type": "object"}})
def set_plugins(st, a):
    f = st.facts
    locked = _approved_channels(st)
    before = {c: [(n, f["plugins"][n]) for n in _chain(f, c)] for c in locked}
    ops = []
    if "plugins" in a or "macros" in a:
        ops.append({"op": "plugins", **{k: a[k] for k in ("plugins", "macros") if k in a}})
    for ch, num in (a.get("channel_plugins") or {}).items():
        if int(ch) - 1 in locked:
            raise ValueError(f"channel {ch} is approved by the owner: its chain stays")
        ops.append({"op": "channel_plugin", "ch": int(ch) - 1, "plugin": int(num or 0)})
    if not ops:
        raise ValueError("nothing to change: give plugins, channel_plugins or macros")
    st.song_edit(ops)
    f = st.facts
    after = {c: [(n, f["plugins"][n]) for n in _chain(f, c)] for c in locked}
    if after != before:
        st.undo()
        raise ValueError("that changes an approved channel's effects: undone")
    return {"ok": True, "summary": f"{len(f['plugins'])} plugins", "plugins": f["plugins"],
            "channel_plugins": f["channel_plugins"]}


@tool("measure", "Render what the tryout plays (the song with the owner's unwritten faders) and measure it: integrated "
      "loudness (LUFS, BS.1770), true peak (dBTP), sample peak and stereo correlation. `channels` (1-based) solo those; "
      "`orders` [start, stop) limits it to those play-order positions. Returns the change since the last measure of the "
      "same scope, so measure before and after an edit. Numbers only: they are not listening.",
      {"channels": {"type": "array", "items": {"type": "integer"}},
       "orders": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}})
def measure(st, a):
    import numpy as np
    from . import dsp
    from .gui import RATE, patch_it
    from .openmpt import LoadedModule
    st._need_compiled()
    nch = len(st.facts["channels"])
    chans = [c - 1 for c in a["channels"]] if a.get("channels") else None
    silenced = [c for c in range(nch) if c not in chans] if chans else st.silenced()
    with LoadedModule(patch_it(st.compiled_it(whole=True), silenced, st.mix())) as lm:
        x = np.frombuffer(lm.render(RATE), "<i2").reshape(-1, 2).T.astype(np.float32) / 32768
    if a.get("orders"):
        o = st.facts["orders"]
        s, e = int(a["orders"][0]), int(a["orders"][1])
        if not 0 <= s < e <= len(o):
            raise ValueError(f"orders: a span within 0..{len(o)}")
        x = x[:, int(o[s]["start"] * RATE): int((o[e - 1]["start"] + o[e - 1]["seconds"]) * RATE)]
    m = dsp.measure_mix(x, RATE)
    scope = json.dumps({"channels": a.get("channels"), "orders": a.get("orders")}, sort_keys=True)
    prev = st.agent_measures.get(scope)
    st.agent_measures[scope] = m
    out = {"numbers": m, "scope": json.loads(scope)}
    if prev:
        out["change_since_last"] = {k: round(m[k] - prev[k], 2) for k in ("lufs", "true_peak_dbtp", "peak_dbfs", "correlation")
                                    if m.get(k) is not None and prev.get(k) is not None}
    out["summary"] = f"{m['lufs']} LUFS, TP {m['true_peak_dbtp']} dBTP, corr {m['correlation']}"
    return out


@tool("cue", "Show a place in the app (the pattern view at a play-order position, row and channel) and, with play, play "
      "from there in the app so the owner hears it.",
      {"order": {"type": "integer"}, "row": {"type": "integer"}, "channel": {"type": "integer"},
       "play": {"type": "boolean"}}, ["order"])
def cue(st, a):
    n = len(st.facts["orders"])
    if not 0 <= int(a["order"]) < n:
        raise ValueError(f"no order {a['order']} (0..{n - 1})")
    st.cue = {"id": (st.cue or {}).get("id", 0) + 1, "order": int(a["order"]), "row": int(a.get("row") or 0),
              "channel": int(a["channel"]) - 1 if a.get("channel") else None, "play": bool(a.get("play"))}
    return {"ok": True, "summary": f"order {a['order']} row {a.get('row') or 0}{' playing' if a.get('play') else ''}"}


@tool("offer_samples", "Offer WAV files as tryout candidates for a sample slot: the app renders each inside the song and "
      "the owner hears, rates and picks one (U writes it). Nothing in the song changes. Refused for an approved slot.",
      {"slot": {"type": "integer"}, "files": {"type": "array", "items": {"type": "string"}}}, ["slot", "files"])
def offer_samples(st, a):
    slot = int(a["slot"])
    entry = (st.song.get("samples") or {}).get(slot)
    if not isinstance(entry, dict):
        raise ValueError(f"no sample slot {slot}")
    if entry.get("approved"):
        raise ValueError(f"slot {slot} is approved by the owner: its sound stays")
    if st.slot != slot:
        st.meta["slot"] = slot
        st.save_meta()
    added = st.add_candidates("\n".join(a["files"]))
    return {"ok": True, "added": added, "summary": f"{len(added)} candidates for slot {slot}: the owner picks"}


@tool("read_notes", "The owner's listening notes: what they said, where (time, order, row) and which channels were "
      "sounding. Act on the words.")
def read_notes(st, a):
    return {"notes": st.notes or []}


@tool("key_check", "How the song's notes sit in a key (the song's own `key` when none is given): per channel the share of "
      "note onsets in the scale (a drum channel on arbitrary keys reads low), and an estimate of the key from the "
      "pitched channels (Krumhansl-Kessler).", {"key": {"type": "string"}})
def key_check(st, a):
    from .compose import key_report
    st._need_compiled()
    r = key_report(st.mod, a.get("key"))
    share = f"{round(r['in_key'] * 100)}% in {r['key']}, " if r["key"] and r["in_key"] is not None else ""
    r["summary"] = f"{share}estimate {r['estimate']}"
    return r


@tool("undo", "Undo the last change to the song (anyone's), one step.")
def undo(st, a):
    if not st.history:
        raise ValueError("nothing to undo")
    st.undo()
    return {"ok": True, "summary": "undone"}


@tool("check", "The song's errors and warnings as the compiler reports them.")
def check(st, a):
    return {"error": st.error, "warnings": (st.facts or {}).get("warnings", [])}


# ---------------------------------------------------------------- the chat panel (optional)

SYSTEM = """You work inside VultureTracker, an Impulse Tracker composer whose songs are YAML files compiled to .it and \
played by libopenmpt. The owner is a musician who decides everything by ear. You have tools that read and edit the open \
song; every edit is one undo step in the app.

How you work here:
- You cannot hear. Report measurements (the measure tool) as measurements, never as how something sounds. Measure \
before and after an edit to report what changed.
- Levels are the owner's: no tool moves faders, channel volume or pan, or the mix volume. Suggest a level change in \
words if you think one is needed.
- An entry marked approved (a pattern, channel or sample) stays as it is.
- Sounds are offered as tryout candidates (offer_samples); the owner listens and picks.
- Every melodic line you write is your own: never copy or derive a melody, riff or cell from an existing song or a \
reference track.
- Effects and their meanings follow OpenMPT and Impulse Tracker.
- When the owner says "this" or "here", call get_selection first.
- Keep replies short: what you changed, what you measured, what the owner might listen for. Offer two or three options \
when the owner asks for ideas."""


try:
    import keyring  # optional: the OS credential store for the API key
except ImportError:
    keyring = None

KEYRING_SERVICE = "VultureTracker"


def settings_path():
    return user_dir() / "agent.json"


def _read_file():
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_file(s):
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    atomic_write(settings_path(), json.dumps(s, indent=2).encode("utf-8"))


def _account(s):
    return s.get("provider") or "anthropic"


def _keyring_get(account):
    """(key, store): the key under the OS credential store and "keyring", or (None, "file") when the keyring package
    is missing or has no working backend (Linux without a secret service raises)."""
    if keyring is not None:
        try:
            return keyring.get_password(KEYRING_SERVICE, account), "keyring"
        except Exception:
            pass
    return None, "file"


def _keyring_set(account, key):
    """True when the key is in the store and reads back (the null backend drops it without a word)."""
    try:
        keyring.set_password(KEYRING_SERVICE, account, key)
        return keyring.get_password(KEYRING_SERVICE, account) == key
    except Exception:
        return False


def load_settings():
    """The file's settings with the API key from the OS credential store when keyring works here (a key still in the
    file moves there on first load, the store's own wins), else the file's own; `key_store` says which."""
    s = _read_file()
    acct = _account(s)
    key, store = _keyring_get(acct)
    if store == "keyring" and s.get("api_key"):
        if key or _keyring_set(acct, s["api_key"]):
            key = key or s["api_key"]
            del s["api_key"]
            _write_file(s)
        else:
            store = "file"  # a backend that drops the key: the file keeps it
    if key:
        s["api_key"] = key
    s["key_store"] = store
    return s


def save_settings(new):
    """The chat panel's provider settings, kept in the user's folder (never beside a song); the key goes to the OS
    credential store under the provider's name when keyring works here, else into the file. An empty api_key keeps the
    stored one; `clear_key` drops it."""
    cur = _read_file()
    if "provider" in new and new["provider"] != cur.get("provider", ""):
        # Keep inactive file-backed keys separate, just as the OS credential store does.
        keys = cur.setdefault("provider_keys", {})
        if cur.get("api_key"):
            keys[_account(cur)] = cur.pop("api_key")
        if new.get("provider") in keys:
            cur["api_key"] = keys.pop(new["provider"])
        for k in ("model", "base_url", "effort"):
            cur.pop(k, None)
    for k in ("provider", "model", "base_url", "effort"):
        if k in new:
            cur[k] = str(new[k] or "").strip()
    acct = _account(cur)
    _, store = _keyring_get(acct)
    if new.get("clear_key"):
        cur.pop("api_key", None)
        if store == "keyring":
            try:
                keyring.delete_password(KEYRING_SERVICE, acct)
            except Exception:
                pass  # nothing stored under it
    elif new.get("api_key"):
        key = str(new["api_key"]).strip()
        if store == "keyring" and _keyring_set(acct, key):
            cur.pop("api_key", None)
        else:
            cur["api_key"] = key
    _write_file(cur)
    return public_settings()


def base_url_warning(base_url):
    """The panel's warning when a key would be sent in clear: a base_url that is neither local nor https."""
    u = urllib.parse.urlsplit(base_url or "")
    if not base_url or u.scheme == "https" or u.hostname in ("localhost", "127.0.0.1", "::1"):
        return ""
    return "the key would travel in clear: base_url is neither localhost nor https"


def public_settings():
    s = load_settings()
    return {"provider": s.get("provider", ""), "model": s.get("model", ""), "base_url": s.get("base_url", ""),
            "effort": s.get("effort", ""), "has_key": bool(s.get("api_key")), "key_store": s["key_store"],
            "base_url_warning": base_url_warning(s.get("base_url", "")), "presets": PRESETS}


PRESETS = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-3.8-flash"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": ""},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "model": ""},
    "openai": {"base_url": "http://localhost:11434/v1", "model": ""},
}


def connection(s):
    provider = s.get("provider")
    if provider not in PRESETS:
        raise ValueError("choose Gemini, Ollama, LM Studio, or an OpenAI-compatible server")
    preset = PRESETS[provider]
    # Gemini always uses Google's endpoint, even if an older server URL is still saved.
    base = (preset["base_url"] if provider == "gemini" else s.get("base_url") or preset["base_url"]).rstrip("/")
    u = urllib.parse.urlsplit(base)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("server URL must be an http(s) URL without credentials, query, or fragment")
    key = s.get("api_key") or ""
    if provider == "gemini":
        key = key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
        if not key:
            raise ValueError("Gemini needs an API key from aistudio.google.com/apikey; enter it in SETTINGS")
    return base, s.get("model") or preset["model"], key


def compatible_request(s, path, body=None, timeout=600):
    base, _, key = connection(s)
    req = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        code = e.code
        detail = ""
        try:
            error = json.loads(e.read(8192))
            if isinstance(error, list):
                error = error[0] if error else {}
            detail = str(error.get("error", {}).get("message", ""))
            if key:
                detail = detail.replace(key, "[redacted]")
            detail = detail[:800]
        except (ValueError, AttributeError, OSError):
            pass
        finally:
            e.close()
        if code == 429:
            raise RuntimeError("rate limit or quota reached; wait and check your provider's quota. "
                               "No paid fallback was used") from None
        if code in (401, 403):
            raise RuntimeError("provider refused access; check the API key and account permissions") from None
        raise RuntimeError(f"provider returned HTTP {code}; check the model name and its tool-calling support"
                           + (f": {detail}" if detail else "")) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("cannot reach the model server; start Ollama or LM Studio's Developer server, "
                           "or check your server URL and internet connection") from None


def discover_models(new):
    """Read the selected server's model list without saving settings or sending song data."""
    saved = load_settings()
    s = {k: str(new.get(k) or "").strip() for k in ("provider", "base_url", "api_key")}
    if s["provider"] not in ("ollama", "lmstudio", "openai"):
        raise ValueError("model discovery is for Ollama, LM Studio, or a custom server")
    if (not s["api_key"] and s["provider"] == saved.get("provider")
            and connection(s)[0] == connection(saved)[0]):
        s["api_key"] = saved.get("api_key", "")
    out = compatible_request(s, "/models", timeout=5)
    if not isinstance(out, dict) or not isinstance(out.get("data"), list):
        raise ValueError("the server did not return an OpenAI-compatible model list")
    models = sorted({m["id"] for m in out["data"] if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]})
    return {"models": models}


def compatible_tools(provider):
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                               "parameters": t["input_schema"]}} for t in tool_list()]
    if provider == "gemini":
        # Google's schema subset uses anyOf for unions. Open-ended rack maps travel as JSON strings.
        def schema(s):
            out = dict(s)
            if isinstance(out.get("type"), list):
                out["anyOf"] = [{"type": t} for t in out.pop("type")]
            if "properties" in out:
                out["properties"] = {k: schema(v) for k, v in out["properties"].items()}
            if "items" in out:
                out["items"] = schema(out["items"])
            if not out.get("required"):
                out.pop("required", None)
            return out
        for t in tools:
            f = t["function"]
            f["parameters"] = schema(f["parameters"])
            if f["name"] == "set_plugins":
                f["parameters"]["properties"] = {k: {"type": "string", "description": "JSON-encoded object"}
                                                  for k in f["parameters"]["properties"]}
            if not f["parameters"].get("properties"):
                del f["parameters"]
    return tools


class Chat:
    """One conversation with the configured model, its tools run on the State. The display list is what the panel
    shows; the history is the provider's own message list, kept append-only (thinking blocks pass back unchanged)."""

    def __init__(self):
        self.display, self.history, self.busy, self.provider = [], [], False, None
        self.session = None  # Claude Code's session id: the next message resumes it
        self.lock = threading.Lock()

    def snapshot(self):
        return {"messages": self.display[-200:], "busy": self.busy, "settings": public_settings()}

    def clear(self):
        with self.lock:
            if self.busy:
                raise ValueError("the agent is still working: wait for it to finish")
            self.display, self.history, self.provider, self.session = [], [], None, None

    def send(self, st, text, context=None):
        s = load_settings()
        if not s.get("provider"):
            raise ValueError("choose a provider in the chat panel's settings first (the Anthropic API, or a local model "
                             "through an OpenAI-compatible server)")
        with self.lock:
            if self.busy:
                raise ValueError("the agent is still working on the last message")
            identity = (s["provider"], s.get("base_url", ""), s.get("model", ""))
            if self.provider not in (None, identity):
                self.history, self.session = [], None  # another provider: a new conversation (each its own format)
            self.provider, self.busy = identity, True
        self.display.append({"role": "you", "text": text, "context": context})
        prompt = f"[the owner's selection: {context}]\n{text}" if context else text
        threading.Thread(target=self._run, args=(st, s, prompt), daemon=True).start()

    def _say(self, role, text):
        if text and text.strip():
            self.display.append({"role": role, "text": text.strip()})

    def _tool(self, st, name, args):
        out = run(st, name, args)
        self.display.append({"role": "tool", "tool": name, "args": _short(args, 200),
                             "text": out.get("error") or out.get("summary") or _short(out, 200), "error": "error" in out})
        return out

    def _run(self, st, s, prompt):
        try:
            {"claude_code": self._claude_code, "anthropic": self._anthropic}.get(s["provider"], self._openai)(st, s, prompt)
        except Exception as e:  # noqa: BLE001 - shown in the panel
            self.display.append({"role": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            self.busy = False

    def _claude_code(self, st, s, prompt):
        """Claude Code run headless (`claude -p`, streaming JSON) on the owner's own login (a Claude subscription, or
        whatever Claude Code is signed in with): this app's MCP server is its only tool source and its built-in tools
        are off, so it can do no more than the song tools allow. The next message resumes the same session."""
        cmd = claude_command()
        if not cmd:
            raise RuntimeError("Claude Code is not installed (no `claude` on PATH): https://claude.com/claude-code, then "
                               "sign in once with `claude` in a terminal")
        if not PORT:
            raise RuntimeError("the app's port is not known yet: restart the app")
        frozen = getattr(sys, "frozen", False)
        server = {"command": sys.executable, "args": (["mcp"] if frozen else ["-m", "vulturetracker", "mcp"]) + ["--port", str(PORT)]}
        if not frozen:
            server["env"] = {"PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
        args = cmd + ["-p", "--output-format", "stream-json", "--verbose", "--strict-mcp-config",
                      "--mcp-config", json.dumps({"mcpServers": {"vulturetracker": server}}),
                      "--tools", "", "--allowedTools", "mcp__vulturetracker", "--append-system-prompt", SYSTEM]
        if s.get("model"):
            args += ["--model", s["model"]]
        if self.session:
            args += ["--resume", self.session]
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding="utf-8", errors="replace", cwd=str(Path(__file__).resolve().parent.parent),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        err = []
        threading.Thread(target=lambda: err.extend(p.stderr), daemon=True).start()
        p.stdin.write(prompt)
        p.stdin.close()
        calls, done = {}, False
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type")
            if ev.get("session_id"):
                self.session = ev["session_id"]
            if kind == "system" and ev.get("subtype") == "init":
                bad = [m["name"] for m in ev.get("mcp_servers") or [] if m.get("status") not in ("connected", None)]
                if bad:
                    self._say("error", f"Claude Code could not start the song tools ({', '.join(bad)})")
            elif kind == "assistant":
                for b in (ev.get("message") or {}).get("content") or []:
                    if b.get("type") == "text":
                        self._say("agent", b.get("text", ""))
                    elif b.get("type") == "tool_use":
                        calls[b.get("id")] = (str(b.get("name", "")).replace("mcp__vulturetracker__", ""), b.get("input"))
            elif kind == "user":
                for b in (ev.get("message") or {}).get("content") or []:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    name, args_ = calls.pop(b.get("tool_use_id"), ("tool", {}))
                    text = b.get("content")
                    if isinstance(text, list):
                        text = "".join(c.get("text", "") for c in text if isinstance(c, dict))
                    try:
                        out = json.loads(text)
                        text = out.get("error") or out.get("summary") or _short(out, 200)
                    except (ValueError, TypeError, AttributeError):
                        text = str(text)[:200]
                    self.display.append({"role": "tool", "tool": name, "args": _short(args_, 200), "text": text,
                                         "error": bool(b.get("is_error"))})
            elif kind == "result":
                done = True
                if ev.get("is_error") or ev.get("subtype") not in (None, "success"):
                    self._say("error", str(ev.get("result") or ev.get("subtype")))
        p.wait()
        if p.returncode and not done:
            raise RuntimeError(f"claude exited with {p.returncode}: {''.join(err)[-600:].strip() or 'no message'}")

    def _anthropic(self, st, s, prompt):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("the Anthropic API needs the anthropic package: pip install anthropic")
        client = anthropic.Anthropic(api_key=s.get("api_key") or None)  # else ANTHROPIC_API_KEY or an `ant auth` profile
        tools = tool_list()
        self.history.append({"role": "user", "content": prompt})
        for _ in range(40):
            resp = client.beta.messages.create(
                model=s.get("model") or "claude-opus-5-5", max_tokens=16000, system=SYSTEM, tools=tools,
                messages=self.history, betas=["server-side-fallback-2026-07-01"],
                # passed through extra_body: this anthropic package predates the keywords for them
                extra_body={"output_config": {"effort": s.get("effort") or "medium"}, "fallbacks": "default"})
            self.history.append({"role": "assistant", "content": resp.content})
            for b in resp.content:
                if b.type == "text":
                    self._say("agent", b.text)
            if resp.stop_reason == "refusal":
                self._say("error", "the model declined this request")
                return
            if resp.stop_reason != "tool_use":
                return
            results = []
            for b in resp.content:
                if b.type == "tool_use":
                    out = self._tool(st, b.name, b.input)
                    results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": "error" in out,
                                    "content": json.dumps(out, default=str)[:60000]})
            self.history.append({"role": "user", "content": results})
        self._say("error", "stopped after 40 tool rounds")

    def _openai(self, st, s, prompt):
        """A local model through an OpenAI-compatible chat-completions server with function calling (Ollama:
        http://localhost:11434/v1, LM Studio: http://localhost:1234/v1, llama.cpp's server: http://localhost:8080/v1)."""
        _, model, _ = connection(s)
        if not model:
            raise ValueError("choose a model in SETTINGS; use FIND MODELS for Ollama or LM Studio")
        tools = compatible_tools(s["provider"])
        if not self.history:
            self.history.append({"role": "system", "content": SYSTEM})
        self.history.append({"role": "user", "content": prompt})
        for _ in range(40):
            msg = compatible_request(s, "/chat/completions", {"model": model, "messages": self.history,
                                                            "tools": tools})["choices"][0]["message"]
            self.history.append({k: v for k, v in msg.items() if v is not None})
            self._say("agent", msg.get("content") or "")
            calls = msg.get("tool_calls") or []
            if not calls:
                return
            for c in calls:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("tool arguments must be an object")
                    if s["provider"] == "gemini" and c["function"]["name"] == "set_plugins":
                        args = {k: json.loads(v) if isinstance(v, str) else v for k, v in args.items()}
                except (ValueError, TypeError):
                    self.history.append({"role": "tool", "tool_call_id": c.get("id", ""),
                                         "content": json.dumps({"error": "invalid JSON object in tool arguments; nothing changed"})})
                    continue
                out = self._tool(st, c["function"]["name"], args)
                self.history.append({"role": "tool", "tool_call_id": c.get("id", ""),
                                     "content": json.dumps(out, default=str)[:60000]})
        self._say("error", "stopped after 40 tool rounds")


# ---------------------------------------------------------------- where the running app listens (for mcp.py)

def claude_command():
    """The command that runs Claude Code, or None when it is not installed."""
    exe = shutil.which("claude")
    return [exe] if exe else None


PORT = None  # the running app's port (announce), for the MCP server the chat panel's Claude Code starts


def running_path():
    return user_dir() / "running.json"


def announce(port):
    """Write the app's port for the MCP server to find."""
    global PORT
    PORT = port
    try:
        running_path().parent.mkdir(parents=True, exist_ok=True)
        atomic_write(running_path(), json.dumps({"port": port, "version": __version__}).encode("utf-8"))
    except OSError:
        pass
