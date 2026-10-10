"""The agent's tools: one list, run in the app's process against the open song (gui.State), reached two ways: the MCP
server (`python -m vulturetracker mcp`, mcp.py), which an agent such as Claude Code runs and which calls the running app
over its local HTTP port, and the app's optional chat panel (Chat below: Claude Code on the owner's own login, run
headless with the MCP server attached; the Anthropic API; or a local model behind an OpenAI-compatible server such as
Ollama, LM Studio or llama.cpp).

What the tools leave to the owner, as AGENTS.md has it: no tool moves a fader, a channel volume or pan, or the mix
volume (levels are the owner's); an entry marked `approved: true` (a pattern, a channel, a sample) is refused; sounds
are offered as tryout candidates, which the owner hears and picks. Every edit is one undo step in the app and marks the
patterns it writes `by: agent`. The tools measure (LUFS, true peak, correlation); they cannot hear."""
import copy
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
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
        from .gui import Handler
        # Serialize project switches with agent edits so an edit cannot land on the old song.
        with Handler.song_lock:
            if st is None and name not in ('project_status', 'create_project', 'import_project', 'open_project'):
                raise ValueError("no song is open in the app")
            if st is not None and st.closed:
                raise ValueError('project was closed; inspect the currently open project before editing')
            out = TOOLS[name][2](st, args or {})
            if name == 'open_project':
                st = Handler.state
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


def _channel(st, value):
    if type(value) is not int or not 1 <= value <= len(_channels(st)):
        raise ValueError(f"channel must be 1..{len(_channels(st))}")
    return value - 1


def _rack_guard(f, locked):
    # Master effects and macros can affect approved channels even without a channel plugin.
    if not locked:
        return None
    masters = {n: p for n, p in f.get("plugins", {}).items() if p.get("master")}
    for n in list(masters):
        for k in _chain({**f, "channel_plugins": [n]}, 0):
            masters[k] = f["plugins"][k]
    return ({c: [(n, f["plugins"][n]) for n in _chain(f, c)] for c in locked}, masters, f.get("macros", {}))


@tool("create_channel", "Append one empty channel to every pattern (maximum 64). Optional name; returns its 1-based "
      "number. Existing notes, levels and routing stay unchanged. One undo step.", {"name": {"type": "string"}})
def create_channel(st, a):
    with st.lock:
        st._need_compiled()
        name = a.get("name")
        if name is not None and (not isinstance(name, str) or not 1 <= len(name.strip()) <= 20):
            raise ValueError("channel name must be 1-20 characters")
        st.song_edit([{"op": "channel_add", **({"name": name.strip()} if name is not None else {})}])
        return {"ok": True, "channel": len(st.mod.channels), "name": st.mod.channels[-1].name,
                "summary": f"added empty channel {len(st.mod.channels)}: {st.mod.channels[-1].name}"}


@tool("edit_channel", "Rename, move or remove a channel (1-based). Moves carry its notes, Rack route, pan, volume "
      "and audition faders/mutes. Removing a populated channel requires remove_notes:true, only when the owner asked "
      "to delete its contents. Approved channels cannot be changed or shifted; approved patterns block moves/removal. "
      "Returns old-to-new channel numbers (null means removed). One undo step.",
      {"action": {"type": "string", "enum": ["rename", "move", "remove"]}, "channel": {"type": "integer"},
       "name": {"type": "string"}, "to": {"type": "integer"}, "remove_notes": {"type": "boolean"}}, ["action", "channel"])
def edit_channel(st, a):
    with st.lock:
        st._need_compiled()
        c, action = _channel(st, a["channel"]), a["action"]
        order = list(range(len(st.mod.channels)))
        op = {"op": "channel_" + action, "ch": c}
        affected = {c}
        if action == "rename":
            name = a.get("name")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 20:
                raise ValueError("channel name must be 1-20 characters")
            op["name"] = name.strip()
        elif action == "move":
            dest = _channel(st, a.get("to"))
            op["to"] = dest
            affected = set(range(min(c, dest), max(c, dest) + 1))
            order.insert(dest, order.pop(c))
        elif action == "remove":
            if any(not r[c].is_empty() for p in st.mod.patterns for r in p.rows) and a.get("remove_notes") is not True:
                raise ValueError("channel contains notes/effects; remove_notes:true is required to delete its contents")
            affected = set(range(c, len(order)))
            order.pop(c)
        else:
            raise ValueError("action must be rename, move or remove")
        if affected & _approved_channels(st):
            raise ValueError("that changes or shifts an approved channel")
        if action != "rename" and any(st.pattern_entry(p.name).get("approved") for p in st.mod.patterns):
            raise ValueError("approved patterns prevent moving/removing their channel columns")
        st.song_edit([op])
        mapping = {i + 1: order.index(i) + 1 if i in order else None for i in range(len(order) + (action == "remove"))}
        return {"ok": True, "channel_map": mapping, "summary": f"{action} channel {c + 1}"}


def _new_slot(entries, value):
    used = {int(n) for n in entries}
    n = next((i for i in range(1, 100) if i not in used), None) if value is None else value
    if type(n) is not int or not 1 <= n <= 99 or n in used:
        raise ValueError("choose an unused slot from 1..99; existing slots are never overwritten")
    return n


@tool("create_sample", "Import an audio file into a NEW sample slot; never replaces an existing sample or chooses "
      "a tryout winner. WAV is referenced, other supported formats are converted to a new WAV beside the song. "
      "Defaults to C-5 root and stereo preservation; base_note overrides the root. Does not write notes or change levels. "
      "One undo step. Use offer_samples instead when offering sounds for the owner to choose.",
      {"file": {"type": "string"}, "name": {"type": "string"}, "number": {"type": "integer"},
       "base_note": {"type": "string"}, "stereo": {"type": "boolean"}}, ["file"])
def create_sample(st, a):
    with st.lock:
        st._need_compiled()
        if set(a) - {"file", "name", "number", "base_note", "stereo"}:
            raise ValueError("only file, name, number, base_note and stereo can be set here")
        if not isinstance(a.get("file"), str) or not a["file"].strip():
            raise ValueError("give an audio file path")
        if "stereo" in a and type(a["stereo"]) is not bool:
            raise ValueError("stereo must be true or false")
        n = _new_slot(st.song.get("samples") or {}, a.get("number"))
        op = {"op": "sample_new", "num": n, "file": a["file"], "stereo": a.get("stereo", True)}
        if "name" in a:
            op["name"] = a["name"]
        if "base_note" in a:
            op["keep"] = {"base_note": a["base_note"]}
        st.song_edit([op])
        return {"ok": True, "sample": n, "entry": st.song["samples"][n], "summary": f"created sample slot {n}"}


@tool("create_instrument", "Create a NEW instrument with an optional sample or keymap (never overwrites a slot). "
      "Without a mapping it is silent. In sample mode, first creates one instrument per existing sample at the same "
      "number, so existing pattern numbers still play their original samples; this conversion is refused with approved "
      "material. Reports converted_samples. All changes are one undo step; no notes or owner levels are edited.",
      {"name": {"type": "string"}, "number": {"type": "integer"}, "sample": {"type": "integer"},
       "keymap": {"type": "array", "items": {"type": "object", "properties": {
           "notes": {"type": "string", "description": "One note or inclusive range, e.g. C-0..B-4"},
           "sample": {"type": "integer"}, "play_note": {"type": "string"},
           "transpose": {"type": "integer", "minimum": -119, "maximum": 119}}, "required": ["notes", "sample"]}}})
def create_instrument(st, a):
    with st.lock:
        st._need_compiled()
        if set(a) - {"name", "number", "sample", "keymap"}:
            raise ValueError("only name, number, sample and keymap can be set here")
        if "sample" in a and "keymap" in a:
            raise ValueError("give sample or keymap, not both")
        if "sample" in a and (type(a["sample"]) is not int or a["sample"] not in st.song.get("samples", {})):
            raise ValueError("sample must be an existing sample slot number")
        converting = st.mod.instruments is None
        used = range(1, len(st.mod.samples) + 1) if converting else (st.song.get("instruments") or {})
        n = _new_slot(used, a.get("number"))
        if converting and (_approved_channels(st) or any(st.pattern_entry(p.name).get("approved") for p in st.mod.patterns)
                           or any(e.get("approved") for e in (st.song.get("samples") or {}).values() if isinstance(e, dict))):
            raise ValueError("sample-to-instrument mode conversion affects approved material; the owner must convert it first")
        entry = {k: a[k] for k in ("name", "sample", "keymap") if k in a}
        ops = [{"op": "instruments_from_samples"}] if converting else []
        st.song_edit(ops + [{"op": "instrument_new", "num": n, "entry": entry}])
        return {"ok": True, "instrument": n, "converted_samples": len(st.mod.samples) if converting else 0,
                "entry": st.song["instruments"][n], "summary": f"created instrument {n}"}


def _slot(st, kind, value):
    st._need_compiled()
    if type(value) is not int or value not in (st.song.get(kind) or {}):
        raise ValueError(f"give an existing {kind[:-1]} slot number")
    return value


def _protected_voices(st):
    locked = _approved_channels(st)
    # A note can carry from an earlier order into an approved pattern. Conservatively protect every played voice
    # when any pattern is approved, including references in unused patterns; unused new slots remain editable.
    any_pattern = any(st.pattern_entry(p.name).get("approved") for p in st.mod.patterns)
    refs = {cell.instrument for p in st.mod.patterns for row in p.rows for c, cell in enumerate(row)
            if cell.instrument and (any_pattern or c in locked)}
    if st.mod.instruments is None:
        return {"samples": refs, "instruments": set()}
    return {"instruments": refs, "samples": {s for n in refs for _, s in st.mod.instruments[n - 1].keymap if s}}


def _voice_guard(st, kind, n):
    st._writable()
    if st.song[kind][n].get("approved") or n in _protected_voices(st)[kind]:
        raise ValueError("that sound is approved or used by approved material; nothing changed")
    mixkey = "instrument" if kind == "instruments" else "sample_volume"
    if str(n) in (st.mix().get(mixkey) or {}):
        raise ValueError("that slot has unwritten owner settings; WRITE or RESET them in the app first")


def _voice_usage(st, kind, n):
    instruments = []
    if kind == "samples" and st.mod.instruments is not None:
        names = {}
        for k in st.song["samples"]:
            names.setdefault(st.mod.samples[k - 1].name, k)
        for k, entry in st.song["instruments"].items():
            refs = ([entry["sample"]] if "sample" in entry else []) + [e["sample"] for e in entry.get("keymap", [])]
            if any((r if type(r) is int else names.get(str(r))) == n for r in refs):
                instruments.append(k)
        numbers = set(instruments)
    else:
        numbers = {n}
    cells = [{"pattern": p.name, "row": r, "channel": c + 1}
             for p in st.mod.patterns for r, row in enumerate(p.rows) for c, cell in enumerate(row)
             if cell.instrument in numbers]
    return {"instruments": instruments, "reference_count": len(cells), "references": cells[:100],
            "references_truncated": len(cells) > 100}


_ENV_SCHEMA = {"type": "object", "properties": {
    "nodes": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}},
    "loop": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
    "sustain": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
    **{k: {"type": "boolean"} for k in ("enabled", "carry", "filter")}}, "required": ["nodes"]}
_INS_FIELDS = {"name": {"type": "string"}, "sample": {"type": "integer"},
    "keymap": TOOLS["create_instrument"][1]["properties"]["keymap"],
    **{k: {"type": "integer"} for k in ("fadeout", "pitch_pan_separation", "random_volume", "random_pan",
                                       "filter_cutoff", "filter_resonance")},
    "pitch_pan_center": {"type": "string"},
    "nna": {"type": "string", "enum": ["cut", "continue", "off", "fade"]},
    "dct": {"type": "string", "enum": ["off", "note", "sample", "instrument"]},
    "dca": {"type": "string", "enum": ["cut", "off", "fade"]},
    **{k: _ENV_SCHEMA for k in ("volume_envelope", "panning_envelope", "pitch_envelope")}}
_LOOP_SCHEMA = {"type": "object", "properties": {"start": {"type": "integer"}, "end": {"type": "integer"},
                "type": {"type": "string", "enum": ["forward", "pingpong"]}}, "required": ["start", "end"]}
_SMP_FIELDS = {"name": {"type": "string"}, "file": {"type": "string", "description": "Replacement WAV, only when requested"},
    "base_note": {"type": "string"}, "c5_speed": {"type": "integer"}, "bits": {"type": "integer", "enum": [8, 16]},
    "stereo": {"type": "boolean"}, "loop": _LOOP_SCHEMA, "sustain_loop": _LOOP_SCHEMA,
    "vibrato": {"type": "object", "properties": {"type": {"type": "string", "enum": ["sine", "ramp_down", "square", "random"]},
                **{k: {"type": "integer"} for k in ("speed", "depth", "rate")}}}}


def _edit_voice(st, a, kind, fields):
    with st.lock:
        n = _slot(st, kind, a["number"])
        _voice_guard(st, kind, n)
        changes, clear = a.get("changes", {}), a.get("clear", [])
        if not isinstance(changes, dict) or not isinstance(clear, list) or any(not isinstance(k, str) for k in clear):
            raise ValueError("changes is an object and clear is a list of field names")
        if (set(changes) | set(clear)) - fields.keys():
            raise ValueError("unknown or owner-controlled field; mixer volume, static pan and approval are not editable here")
        if set(changes) & set(clear) or not (changes or clear):
            raise ValueError("give changes or clear, without setting and clearing the same field")
        entry = copy.deepcopy(st.song[kind][n])
        for key in clear:
            entry.pop(key, None)
        entry.update(copy.deepcopy(changes))
        st.song_edit([{"op": kind[:-1] + "_set", "num": n, "entry": entry}])
        return {"ok": True, "number": n, "entry": st.song[kind][n], "summary": f"edited {kind[:-1]} {n}"}


@tool("edit_instrument", "Patch one instrument's mapping, envelopes or behavior; omitted fields stay unchanged. "
      "Nested maps/envelopes are replaced as whole fields. clear removes optional fields. To switch a sample mapping "
      "to a keymap, clear sample (and vice versa). Envelopes use [tick,value] nodes and [first,last] node indices for "
      "loop/sustain; volume values 0..64, pan/pitch -32..32. Approved voices and unwritten instrument edits are "
      "protected. Static pan and global volume stay the owner's. One undo step.",
      {"number": {"type": "integer"}, "changes": {"type": "object", "properties": _INS_FIELDS},
       "clear": {"type": "array", "items": {"type": "string", "enum": list(_INS_FIELDS)}}}, ["number"])
def edit_instrument(st, a):
    return _edit_voice(st, a, "instruments", _INS_FIELDS)


@tool("edit_sample", "Patch one sample's name, tuning, loop, vibrato, stereo/bit-depth or explicitly requested WAV "
      "file replacement. Omitted fields stay; nested fields are replaced whole. clear removes optional settings. "
      "Loop endpoints are source WAV frames, end exclusive; clear loop disables it. base_note and c5_speed are "
      "alternatives: clear the old one when switching. File replacement retains settings, so clear invalid loops or "
      "retune explicitly. No source audio is overwritten. Approved sounds, unwritten gains, volume and pan are protected. "
      "Use offer_samples for sound choices. One undo step.",
      {"number": {"type": "integer"}, "changes": {"type": "object", "properties": _SMP_FIELDS},
       "clear": {"type": "array", "items": {"type": "string", "enum": list(_SMP_FIELDS)}}}, ["number"])
def edit_sample(st, a):
    return _edit_voice(st, a, "samples", _SMP_FIELDS)


@tool("delete_slot", "Remove an unused instrument or sample definition, leaving all audio files on disk and other "
      "slot numbers unchanged. Refuses references in ANY pattern (including unused patterns) or instrument mapping. "
      "Use inspect_sample/get_state/read_pattern to resolve references first; never delete notes implicitly. "
      "Approved material and unwritten slot settings are protected. One undo step.",
      {"kind": {"type": "string", "enum": ["sample", "instrument"]}, "number": {"type": "integer"}}, ["kind", "number"])
def delete_slot(st, a):
    with st.lock:
        if a["kind"] not in ("sample", "instrument"):
            raise ValueError("kind must be sample or instrument")
        kind = a["kind"] + "s"
        n = _slot(st, kind, a["number"])
        _voice_guard(st, kind, n)
        usage = _voice_usage(st, kind, n)
        if usage["instruments"] or usage["reference_count"]:
            return {"error": "slot is still referenced; no notes or mappings were removed", "usage": usage}
        st.song_edit([{"op": a["kind"] + "_delete", "num": n}])
        return {"ok": True, "summary": f"deleted {a['kind']} {n}; audio files retained"}


def _sample_span(st, n, a):
    _, _, w, x = st._sample_wav(n)
    start, end = a.get("start", 0), a.get("end", x.shape[1])
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= x.shape[1]:
        raise ValueError(f"give source-frame bounds 0 <= start < end <= {x.shape[1]} (end exclusive)")
    return start, end, w.rate


@tool("inspect_sample", "Read source WAV dimensions, settings, loop points and all usage counts (first 100 pattern "
      "references shown). Optional analysis proposes loop points or slice starts without editing. Source-frame bounds "
      "use an exclusive end. Slice mode equal uses value as count (1..60); onsets uses sensitivity (0..100). "
      "Loop analysis examines the whole sample. Analysis is measurement, not listening.",
      {"number": {"type": "integer"}, "analysis": {"type": "string", "enum": ["info", "loop", "slices"]},
       "start": {"type": "integer"}, "end": {"type": "integer"},
       "slice_mode": {"type": "string", "enum": ["equal", "onsets"]}, "value": {"type": "integer"}}, ["number"])
def inspect_sample(st, a):
    with st.lock:
        n = _slot(st, "samples", a["number"])
        start, end, _ = _sample_span(st, n, a)
        view = st.sample_view(n, start, end, n=16)
        out = {k: v for k, v in view.items() if k not in ("min", "max", "player")}
        out.update(entry=copy.deepcopy(st.song["samples"][n]), usage=_voice_usage(st, "samples", n))
        action = a.get("analysis", "info")
        if action == "loop":
            out["suggested_loop"] = st.auto_loop(n)
        elif action == "slices":
            mode, value = a.get("slice_mode", "onsets"), a.get("value", 50)
            if mode not in ("equal", "onsets") or type(value) is not int or not (1 if mode == "equal" else 0) <= value <= (60 if mode == "equal" else 100):
                raise ValueError("equal: 1..60 parts; onsets: 0..100 sensitivity")
            out["slices"] = st.slice_points(n, mode, value, start, end)
        elif action != "info":
            raise ValueError("analysis must be info, loop or slices")
        return out


_PROCESS_PARAMS = {"gain": {"db"}, "lowpass": {"hz", "slope"}, "highpass": {"hz", "slope"},
    "eq": {"hz", "db", "q"}, "loudness": {"db"}, "pitch": {"semitones"}, "stretch": {"percent"},
    "denoise": {"na", "nb", "db", "sens"}, "truncate": {"db", "min_ms", "keep_ms"}}
_PROCESS_ACTIONS = ["trim", "fade_in", "fade_out", "normalize", "reverse", "dc", "crossfade", "auto_loop", *_PROCESS_PARAMS]


@tool("process_sample", "Process one sample as one undo step, writing a uniquely named WAV and repointing only its "
      "slot; original files stay for undo. Source-frame start/end (exclusive) select a span, otherwise whole sample. "
      "trim keeps the span. auto_loop sets loop points without rewriting audio; crossfade uses frames at the current "
      "loop seam (both operate on the whole sample, no span). Effects params: gain db [-60,24]; lowpass/highpass hz, "
      "slope 12/24; eq hz,db [-24,24],q [.1,20]; loudness db [-60,0] RMS; pitch semitones [-24,24]; stretch percent "
      "[25,400]; denoise na/nb noise frames (at least 2048),db [0,60],sens [1,8]; truncate db [-120,0],min_ms,keep_ms. "
      "Gain/normalize/loudness only when the owner requests audio-level processing; mixer settings never change. "
      "Loops follow trim/stretch/full reverse; effects exceeding full scale are attenuated and reported. "
      "Refuses approved sounds and sounds used by approved material.",
      {"number": {"type": "integer"}, "action": {"type": "string", "enum": _PROCESS_ACTIONS},
       "start": {"type": "integer"}, "end": {"type": "integer"}, "frames": {"type": "integer"},
       "params": {"type": "object", "properties": {k: {"type": "integer" if k in ("na", "nb") else "number"}
                                                   for k in sorted(set().union(*_PROCESS_PARAMS.values()))}}},
      ["number", "action"])
def process_sample(st, a):
    import math
    with st.lock:
        n = _slot(st, "samples", a["number"])
        _voice_guard(st, "samples", n)
        action, params = a["action"], a.get("params", {})
        if action not in _PROCESS_ACTIONS or not isinstance(params, dict) or set(params) - _PROCESS_PARAMS.get(action, set()):
            raise ValueError("unknown action or parameters for that action")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in params.values()):
            raise ValueError("effect parameters must be finite numbers")
        start, end, _ = _sample_span(st, n, a)
        if action in ("auto_loop", "crossfade") and ("start" in a or "end" in a):
            raise ValueError("auto_loop/crossfade operate on the sample's loop, not a selected span")
        if "frames" in a and action != "crossfade":
            raise ValueError("frames is only for crossfade")
        if action == "auto_loop":
            lp = st.auto_loop(n)
            return edit_sample(st, {"number": n, "changes": {"loop": {k: lp[k] for k in ("start", "end")}}})
        if action == "crossfade" and (type(a.get("frames")) is not int or a["frames"] <= 0):
            raise ValueError("crossfade needs a positive integer frames count")
        if action == "denoise":
            _sample_span(st, n, {"start": params.get("na"), "end": params.get("nb")})
        if action == "truncate" and not (-120 <= params.get("db", -50) <= 0 and
                0 < params.get("min_ms", 200) <= 60000 and 0 <= params.get("keep_ms", 50) <= params.get("min_ms", 200)):
            raise ValueError("truncate needs db -120..0, min_ms 0..60000, and keep_ms between 0 and min_ms")
        result = st.song_edit([{"op": "sample_process", "num": n, "action": action, "a": start, "b": end,
                               "frames": a.get("frames", 0), "params": params}])
        return {"ok": True, "number": n, "entry": st.song["samples"][n], **result,
                "summary": f"{action} sample {n}; original WAV retained"}


@tool("slice_sample", "Cut a sample into new slots using explicit source-frame points and an exclusive end. "
      "Use inspect_sample analysis:slices to find points first. Original sample/notes stay unchanged. Every slice must "
      "be at least 32 frames. kit preserves source pitch; multi detects pitches and needs instrument mode. In instrument "
      "mode also creates a kit/multisample instrument. New WAVs receive a short fade at their ends. One undo step.",
      {"number": {"type": "integer"}, "points": {"type": "array", "items": {"type": "integer"}},
       "end": {"type": "integer"}, "mode": {"type": "string", "enum": ["kit", "multi"]}}, ["number", "points"])
def slice_sample(st, a):
    with st.lock:
        n = _slot(st, "samples", a["number"])
        st._writable()
        _, end, _ = _sample_span(st, n, {"end": a["end"]} if "end" in a else {})
        points = a["points"]
        if not isinstance(points, list) or not points or any(type(p) is not int for p in points):
            raise ValueError("points must be a nonempty list of integer source-frame positions")
        if points != sorted(set(points)) or points[0] < 0 or any(b - a < 32 for a, b in zip(points, points[1:] + [end])):
            raise ValueError("points must increase, stay inside the sample, and leave at least 32 frames per slice")
        old = {k: set(st.song.get(k) or {}) for k in ("samples", "instruments")}
        result = st.song_edit([{"op": "sample_slice", "num": n, "points": points, "end": end, "mode": a.get("mode", "kit")}])
        return {"ok": True, **{k: sorted(set(st.song.get(k) or {}) - old[k]) for k in old}, **result}


@tool("render_sample", "Render a pattern row range into a NEW sample slot, including current unwritten mix and "
      "instrument settings. Does not alter notes or choose a tryout candidate. order/rows are 0-based and rows inclusive; "
      "channels are 1-based. Omitted channels respect audition solo/mutes; supplied channels render only those. "
      "Tail 0..10 seconds. Source playback state is warmed up from earlier orders. One undo step.",
      {"order": {"type": "integer"}, "start_row": {"type": "integer"}, "end_row": {"type": "integer"},
       "channels": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
       "tail": {"type": "number", "minimum": 0, "maximum": 10}}, ["order", "start_row", "end_row"])
def render_sample(st, a):
    with st.lock:
        st._need_compiled()
        st._writable()
        o, r0, r1 = a["order"], a["start_row"], a["end_row"]
        if type(o) is not int or not 0 <= o < len(st.mod.orders) or st.mod.orders[o] >= len(st.mod.patterns):
            raise ValueError("order must name a playable order (0-based)")
        rows = len(st.mod.patterns[st.mod.orders[o]].rows)
        if type(r0) is not int or type(r1) is not int or not 0 <= r0 <= r1 < rows:
            raise ValueError(f"rows must be 0..{rows - 1}, start <= end")
        chans = a.get("channels")
        if chans is not None and (not isinstance(chans, list) or not chans):
            raise ValueError("channels must be a nonempty list")
        chans = [_channel(st, c) for c in chans] if chans is not None else None
        tail = a.get("tail", 2)
        if type(tail) not in (int, float) or not 0 <= tail <= 10:
            raise ValueError("tail must be 0..10 seconds")
        old = set(st.song["samples"])
        result = st.song_edit([{"op": "render_sample", "order": o, "r0": r0, "r1": r1, "chans": chans, "tail": tail}])
        return {"ok": True, "samples": sorted(set(st.song["samples"]) - old), **result}


@tool("get_state", "Read-only complete song settings, sample/instrument definitions, Rack plugins with IDs and "
      "parameters, routing, macros, audition solo/mutes/loop, unwritten mix, checkpoints and last reported window "
      "state (Rack selection, playback mode/position, pending render and engine errors). UI state is last-reported, "
      "not guaranteed live: check ui_stale and ui_age_seconds. Channels are 1-based; orders and rows are 0-based.")
def get_state(st, a):
    with st.lock:
        f = st.facts or {}
        ui = copy.deepcopy(st.ui_state)
        age = round(max(0, time.time() - ui.pop("reported_at")), 2) if ui else None
        return copy.deepcopy({"path": str(st.song_path), "error": st.error, "read_only": st.read_only,
            "external_changes": st.dirty(), "module": st.song.get("module"), "samples": st.song.get("samples"),
            "instruments": st.song.get("instruments"), "sections": st.song.get("sections") or {},
            "orders": st.song.get("orders"), "export": st.export_result,
            "synthesis": agent_sounds.synthesis_status(st, {}),
            "selection": ({**st.selection, "channels": [c + 1 for c in st.selection["channels"]]} if st.selection else None),
            "rack": {"plugins": f.get("plugins", {}), "macros": f.get("macros", {}),
                     "channel_plugins": {i + 1: p for i, p in enumerate(f.get("channel_plugins", []))}},
            "audition": {"solo": st.meta["solo"] + 1 if st.meta.get("solo") is not None else None,
                         "muted": [c + 1 for c in st.meta.get("muted", [])], "loop": st.meta.get("loop"),
                         "orders": st.meta.get("orders"), "slot": st.slot, "candidate": st.want, "mix": st.mix()},
            "ui": ui, "ui_age_seconds": age, "ui_stale": age is None or age > 3,
            "transport_request": st.cue, "undo_steps": len(st.history), "redo_steps": len(st.future),
            "checkpoints": list(st.checkpoints)})


def _transport(st, action):
    st.cue = {"id": (st.cue or {}).get("id", 0) + 1, "action": action, "expires": time.time() + 10}
    return {"ok": True, "status": "queued", "request_id": st.cue["id"],
            "summary": f"{action} requested; get_state.ui.applied_request confirms delivery to the open window"}


@tool("stop_playback", "Request a stop of both the live song engine and rendered/candidate player. Does not stop "
      "the agent chat or change the song. Requires an open app window; response is queued until "
      "get_state.ui.applied_request acknowledges request_id (request expires after 10 seconds).")
def stop_playback(st, a):
    with st.lock:
        return _transport(st, "stop")


@tool("set_audition", "Set audition solo, muted channels, or playback loop without changing mixer levels or notes. "
      "Omitted fields stay unchanged. solo:null clears solo; muted:[] clears mutes. Channels are 1-based. "
      "loop:null clears the loop; otherwise from/to are [order,row], both 0-based, end inclusive. Setting a loop "
      "also selects its orders for rendered playback and overrides live pattern-loop mode; it does not start playback.",
      {"solo": {"type": ["integer", "null"]}, "muted": {"type": "array", "items": {"type": "integer"}},
       "loop": {"type": ["object", "null"], "properties": {
           "from": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
           "to": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}}, "required": ["from", "to"]}})
def set_audition(st, a):
    with st.lock:
        st._need_compiled()
        st._writable()
        if not a or set(a) - {"solo", "muted", "loop"}:
            raise ValueError("give solo, muted and/or loop; mixer levels are not audition controls")
        meta = copy.deepcopy(st.meta)
        if "solo" in a:
            meta["solo"] = None if a["solo"] is None else _channel(st, a["solo"])
        if "muted" in a:
            if not isinstance(a["muted"], list):
                raise ValueError("muted must be a list of channel numbers")
            meta["muted"] = sorted({_channel(st, c) for c in a["muted"]})
        if "loop" in a:
            lp = a["loop"]
            if lp is not None:
                if not isinstance(lp, dict) or set(lp) != {"from", "to"}:
                    raise ValueError("loop needs from and to [order, row]")
                for pos in lp.values():
                    if (not isinstance(pos, list) or len(pos) != 2 or any(type(v) is not int for v in pos)
                            or not 0 <= pos[0] < len(st.facts["orders"])
                            or not 0 <= pos[1] < st.facts["orders"][pos[0]]["rows"]):
                        raise ValueError("loop position is outside the song")
                if lp["from"] > lp["to"]:
                    raise ValueError("loop end must follow its start")
                meta["orders"] = [lp["from"][0], lp["to"][0] + 1]
            meta["loop"] = copy.deepcopy(lp)
        old, st.meta = st.meta, meta
        try:
            st.save_meta()
        except Exception:
            st.meta = old
            raise
        st.queue_all()
        out = _transport(st, "loop" if "loop" in a else "audition")
        out["audition"] = get_state(st, {})["audition"]
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


def _edit_guard(st):
    def guard(text, loaded, meta):
        _guard_restore(st, {"text": text, "meta": meta}, compiled=loaded[0])
    return guard


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer {low}..{high}")
    return value


def _boolean(a, key, default=False):
    value = a.get(key, default)
    if type(value) is not bool:
        raise ValueError(f"{key} must be true or false")
    return value


@tool("edit_section", "Create/update/rename/delete/move/duplicate a named section. Bounds are RAW order indexes "
      "(including +++/---), start inclusive, end exclusive; to is a boundary in the original order list. Deleting "
      "removes only the name. Duplicate defaults to independent pattern copies. Jumps, sections and audition loops "
      "follow moved orders. Refuses changes to approved material. One undo step.",
      {"action": {"type": "string", "enum": ["create", "update", "rename", "delete", "move", "duplicate"]},
       "name": {"type": "string"}, "new_name": {"type": "string"}, "start": {"type": "integer"},
       "end": {"type": "integer"}, "to": {"type": "integer"}, "independent": {"type": "boolean"}}, ["action", "name"])
def edit_section(st, a):
    with st.lock:
        st._writable()
        st._need_compiled()
        action, name = a["action"], a["name"].strip()
        if action not in ("create", "update", "rename", "delete", "move", "duplicate"):
            raise ValueError("unknown section action")
        sections = st.song.get("sections") or {}
        if (action == "create") == (name in sections):
            raise ValueError("section already exists" if action == "create" else "no such section")
        body = {"action": action, "name": name}
        count = len(st.song["orders"])
        if action in ("create", "update"):
            body.update(action="save", start=_integer(a.get("start"), 0, count-1, "start"),
                        end=_integer(a.get("end"), 1, count, "end"))
        if action in ("rename", "duplicate"):
            new = (a["new_name"] if action == "rename" else a.get("new_name", name + " copy")).strip()
            if not new or len(new) > 80 or new in sections:
                raise ValueError("new_name must be a unique section name, 1-80 characters")
            body["new_name"] = new
        if action in ("move", "duplicate"):
            body["to"] = _integer(a.get("to"), 0, count, "to")
        if action == "duplicate":
            body["independent"] = _boolean(a, "independent", True)
        st.section_edit(body, guard=_edit_guard(st))
        return {"ok": True, "sections": st.song.get("sections") or {}, "orders": st.song["orders"],
                "summary": f"section {action}: {name}"}


@tool("edit_pattern", "Rename, resize (1-200 rows), delete an unused pattern, or materialize shorthand into explicit "
      "editable cells. Pattern is a NAME. Resize refuses to discard nonempty rows unless discard_rows=true. "
      "Approved patterns cannot be edited. Dependencies are compiled before saving; materialize retains authorship. "
      "One undo step. With approved channels, structural changes may require the owner to use the Pattern tab.",
      {"action": {"type": "string", "enum": ["rename", "resize", "delete", "materialize"]},
       "pattern": {"type": "string"}, "new_name": {"type": "string"}, "rows": {"type": "integer"},
       "discard_rows": {"type": "boolean"}}, ["action", "pattern"])
def edit_pattern(st, a):
    with st.lock:
        st._writable()
        if not isinstance(a["pattern"], str):
            raise ValueError("pattern must be a name (string)")
        i = _pattern_index(st, a["pattern"])
        p = st.mod.patterns[i]
        if st.pattern_entry(p.name).get("approved"):
            raise ValueError(f"pattern {p.name} is approved by the owner")
        action = a["action"]
        if action == "materialize":
            st.materialize_pattern(i, guard=_edit_guard(st))
        else:
            if action == "rename":
                op = {"op": "pattern_rename", "old": p.name, "new": a["new_name"]}
            elif action == "delete":
                op = {"op": "pattern_delete", "name": p.name}
            elif action == "resize":
                rows = _integer(a.get("rows"), 1, 200, "rows")
                if any(not c.is_empty() for row in p.rows[rows:] for c in row) and not _boolean(a, "discard_rows"):
                    raise ValueError("shortening removes nonempty rows; request discard_rows=true deliberately")
                op = {"op": "pattern_rows", "name": p.name, "rows": rows}
            else:
                raise ValueError("unknown pattern action")
            st.song_edit([op], guard=_edit_guard(st))
        return {"ok": True, "summary": f"pattern {action}: {p.name}",
                "patterns": [{"name": p.name, "rows": len(p.rows)} for p in st.mod.patterns], "orders": st.song["orders"]}


_SCOPE = {"type": "object", "properties": {"pattern": {"type": "string"}, "from_row": {"type": "integer"},
          "to_row": {"type": "integer"}, "channels": {"type": "array", "items": {"type": "integer"}}},
          "required": ["pattern"]}
_FIELDS = ("note", "instrument", "volume", "effect")
_EMPTY_FIELDS = ("...", "..", "...", "...")


def _scope(st, a):
    if not isinstance(a.get("pattern"), str):
        raise ValueError("pattern must be a name (string)")
    i = _pattern_index(st, a["pattern"])
    rows = st.mod.patterns[i].rows
    r0 = _integer(a.get("from_row", 0), 0, len(rows)-1, "from_row")
    r1 = _integer(a.get("to_row", len(rows)-1), r0, len(rows)-1, "to_row")
    chans = [_channel(st, c) for c in a.get("channels", list(range(1, len(st.mod.channels)+1)))]
    if not chans or len(set(chans)) != len(chans):
        raise ValueError("channels must be nonempty and unique")
    return i, rows, r0, r1, chans


def _write_groups(st, groups):
    from .notation import format_cell, parse_cell
    seen, checked, count = set(), [], 0
    locked = _approved_channels(st)
    for i, cells in groups:
        p = st.mod.patterns[i]
        changed = []
        for c in cells:
            r = _integer(c["row"], 0, len(p.rows)-1, "row")
            ch = _integer(c["ch"], 0, len(st.mod.channels)-1, "channel index")
            if (i, r, ch) in seen:
                raise ValueError("duplicate target cell in batch")
            seen.add((i, r, ch))
            cell = parse_cell(c["cell"])
            if cell == p.rows[r][ch]:
                continue
            if st.pattern_entry(p.name).get("approved") or ch in locked:
                raise ValueError(f"pattern {p.name}, channel {ch+1} is approved by the owner")
            changed.append({"row": r, "ch": ch, "cell": format_cell(cell)})
        if changed:
            checked.append((i, changed))
            count += len(changed)
    if checked:
        st.edit_patterns(checked, who="agent", guard=_edit_guard(st))
    return {"ok": True, "changed_cells": count, "summary": f"changed {count} cells in {len(checked)} patterns (one undo step)"}


@tool("write_patterns", "Write cells across several named patterns atomically, one undo step. Full cell replacement, "
      "not a patch: omitted fields are empty. Rejects duplicate destinations, invalid cells and approved material. "
      "Use instead of several write_cells calls when an edit must succeed or fail together.",
      {"patterns": {"type": "array", "items": {"type": "object", "properties": {
          "pattern": {"type": "string"}, "cells": TOOLS["write_cells"][1]["properties"]["cells"]},
          "required": ["pattern", "cells"]}}}, ["patterns"])
def write_patterns(st, a):
    with st.lock:
        st._writable()
        groups = []
        for group in a["patterns"]:
            i, _, _, _, _ = _scope(st, {"pattern": group["pattern"]})
            groups.append((i, [{"row": c["row"], "ch": _channel(st, c["channel"]), "cell": c["cell"]}
                               for c in group["cells"]]))
        return _write_groups(st, groups)


@tool("transform_patterns", "Transform named pattern selections atomically (one undo step), each pattern once even "
      "if repeated in orders. Inclusive row bounds; channels are 1-based. transpose clamps real notes to C-0..B-9, "
      "preserving off/cut/fade. replace matches exact field text with * and ? wildcards (case sensitive). clear uses "
      "fields (default all). groove preserves other effects and reports skipped notes. chord/euclid require one source "
      "channel; chord writes adjacent channels and needs overwrite=true for occupied destinations. layers takes slot "
      "numbers in the current instrument/sample mode. Inline/flow YAML patterns may need materializing first.",
      {"action": {"type": "string", "enum": ["transpose", "clear", "replace", "groove", "euclid", "chord", "layers"]},
       "selections": {"type": "array", "items": _SCOPE}, "semitones": {"type": "integer"},
       "fields": {"type": "array", "items": {"type": "string", "enum": list(_FIELDS)}},
       "match": {"type": "object", "properties": {k: {"type": "string"} for k in _FIELDS}},
       "replacement": {"type": "object", "properties": {k: {"type": "string"} for k in _FIELDS}},
       "ticks": {"type": "array", "items": {"type": "integer"}}, "hits": {"type": "integer"},
       "steps": {"type": "integer"}, "rotate": {"type": "integer"}, "every": {"type": "integer"},
       "probability": {"type": "integer"}, "seed": {"type": "integer"}, "shape": {"type": "string"},
       "inversion": {"type": "integer"}, "overwrite": {"type": "boolean"},
       "instruments": {"type": "array", "items": {"type": "integer"}},
       "mode": {"type": "string", "enum": ["cycle", "volume"]}}, ["action", "selections"])
def transform_patterns(st, a):
    import re
    from . import compose
    from .notation import format_cell, format_note
    with st.lock:
        st._writable()
        action, groups, seen, skipped = a["action"], [], set(), 0
        if action not in ("transpose", "clear", "replace", "groove", "euclid", "chord", "layers"):
            raise ValueError("unknown transform")
        fields = a.get("fields", list(_FIELDS))
        if not fields or any(f not in _FIELDS for f in fields):
            raise ValueError("fields must name note, instrument, volume or effect")
        match, replacement = a.get("match", {}), a.get("replacement", {})
        if action == "replace" and (not match or not replacement or any(k not in _FIELDS for k in [*match, *replacement])):
            raise ValueError("replace requires nonempty match and replacement field maps")
        for selection in a["selections"]:
            i, rows, r0, r1, chans = _scope(st, selection)
            if i in seen:
                raise ValueError("select each pattern only once")
            seen.add(i)
            cells = []
            if action == "groove":
                ticks = [_integer(t, 0, min(st.mod.speed, 16)-1, "tick") for t in a["ticks"]]
                cells, n = compose.groove(rows, chans, r0, r1, ticks, st.mod.speed)
                skipped += n
            elif action in ("euclid", "chord"):
                if len(chans) != 1:
                    raise ValueError(f"{action} requires one source channel")
                if action == "euclid":
                    steps = _integer(a.get("steps"), 1, 64, "steps")
                    cells = compose.euclid(rows, chans[0], r0, r1, _integer(a.get("hits"), 0, steps, "hits"), steps,
                        _integer(a.get("rotate", 0), -64, 64, "rotate"), _integer(a.get("every", 1), 1, 64, "every"),
                        _integer(a.get("probability", 100), 0, 100, "probability"),
                        _integer(a.get("seed", 1), 0, 2147483647, "seed"))
                else:
                    cells = compose.chord(rows, chans[0], r0, r1, a.get("shape", "maj"),
                                          _integer(a.get("inversion", 0), 0, 5, "inversion"), len(st.mod.channels))
                    if not _boolean(a, "overwrite") and any(c["ch"] != chans[0] and
                            not rows[c["row"]][c["ch"]].is_empty() and format_cell(rows[c["row"]][c["ch"]]) != c["cell"] for c in cells):
                        raise ValueError("chord would overwrite occupied destination cells; request overwrite=true")
            elif action == "layers":
                slots = st.song.get("instruments" if st.mod.instruments is not None else "samples") or {}
                numbers = a["instruments"]
                if not numbers or any(type(n) is not int or n not in slots for n in numbers):
                    raise ValueError("instruments must list existing slots in the current mode")
                def default_volume(cell):
                    n = cell.instrument
                    if st.mod.instruments is not None:
                        n = st.mod.instruments[n-1].keymap[cell.note][1] if 0 < n <= len(st.mod.instruments) else 0
                    return st.mod.samples[n-1].volume if 0 < n <= len(st.mod.samples) else None
                cells = compose.layers(rows, chans, r0, r1, numbers, a.get("mode", "cycle"), default_volume)
            else:
                semitones = _integer(a.get("semitones"), -119, 119, "semitones") if action == "transpose" else 0
                for r in range(r0, r1+1):
                    for ch in chans:
                        c = rows[r][ch]
                        parts = format_cell(c).split()
                        if action == "transpose" and c.note is not None and c.note < 120:
                            parts[0] = format_note(max(0, min(119, c.note+semitones)))
                        elif action == "clear":
                            for f in fields:
                                parts[_FIELDS.index(f)] = _EMPTY_FIELDS[_FIELDS.index(f)]
                        elif action == "replace" and all(re.fullmatch(re.escape(v).replace(r"\*", ".*").replace(r"\?", "."),
                                                                      parts[_FIELDS.index(k)]) for k, v in match.items()):
                            for f, value in replacement.items():
                                parts[_FIELDS.index(f)] = value
                        cells.append({"row": r, "ch": ch, "cell": " ".join(parts)})
            groups.append((i, cells))
        result = _write_groups(st, groups)
        result["skipped_notes"] = skipped
        return result


@tool("copy_pattern_region", "Copy/move a rectangular region to a named pattern and first destination row/channel. "
      "Source channels must be consecutive. Full cells by default; fields selects columns. mix fills empty fields only "
      "(copy only). Occupied differing destination fields require overwrite=true; out-of-bounds copies are refused, "
      "never clipped. Overlapping moves use a snapshot, clearing the source before writing the destination. Atomic, "
      "one undo step; approved sources can be copied but cannot be changed.",
      {"source": _SCOPE, "pattern": {"type": "string"}, "row": {"type": "integer"}, "channel": {"type": "integer"},
       "move": {"type": "boolean"}, "mix": {"type": "boolean"}, "overwrite": {"type": "boolean"},
       "fields": {"type": "array", "items": {"type": "string", "enum": list(_FIELDS)}}},
      ["source", "pattern", "row", "channel"])
def copy_pattern_region(st, a):
    from .notation import format_cell
    with st.lock:
        st._writable()
        src, rows, r0, r1, chans = _scope(st, a["source"])
        dst, target, _, _, _ = _scope(st, {"pattern": a["pattern"]})
        dr = _integer(a["row"], 0, len(target)-(r1-r0+1), "row")
        dc = _channel(st, a["channel"])
        if chans != list(range(chans[0], chans[0]+len(chans))) or dc+len(chans) > len(st.mod.channels):
            raise ValueError("source channels must be consecutive and destination must fit")
        move, mix, overwrite = _boolean(a, "move"), _boolean(a, "mix"), _boolean(a, "overwrite")
        if move and mix:
            raise ValueError("mix is copy-only; a move must not silently discard source fields")
        fields = a.get("fields", list(_FIELDS))
        if not fields or any(f not in _FIELDS for f in fields):
            raise ValueError("fields must name note, instrument, volume or effect")
        ids = [_FIELDS.index(f) for f in fields]
        pending = {}
        if move:
            for r in range(r0, r1+1):
                for ch in chans:
                    parts = format_cell(rows[r][ch]).split()
                    for f in ids:
                        parts[f] = _EMPTY_FIELDS[f]
                    pending[src, r, ch] = parts
        for r in range(r0, r1+1):
            for k, ch in enumerate(chans):
                key = dst, dr+r-r0, dc+k
                parts = list(pending.get(key, format_cell(target[key[1]][key[2]]).split()))
                original = format_cell(rows[r][ch]).split()
                for f in ids:
                    if mix and parts[f] != _EMPTY_FIELDS[f]:
                        continue
                    if not mix and not overwrite and parts[f] not in (_EMPTY_FIELDS[f], original[f]):
                        raise ValueError("copy would overwrite occupied fields; request overwrite=true")
                    parts[f] = original[f]
                pending[key] = parts
        groups = {}
        for (i, r, ch), parts in pending.items():
            groups.setdefault(i, []).append({"row": r, "ch": ch, "cell": " ".join(parts)})
        return _write_groups(st, list(groups.items()))


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
    with st.lock:
        st._need_compiled()
        return _set_plugins(st, a)


def _set_plugins(st, a):
    f = st.facts
    locked = _approved_channels(st)
    after = copy.deepcopy(f)
    if "plugins" in a:
        after["plugins"] = {int(n): p for n, p in a["plugins"].items()}
    if "macros" in a:
        after["macros"] = a["macros"]
    ops = []
    if "plugins" in a or "macros" in a:
        ops.append({"op": "plugins", **{k: a[k] for k in ("plugins", "macros") if k in a}})
    for ch, num in (a.get("channel_plugins") or {}).items():
        c = _channel(st, int(ch))
        if c in locked:
            raise ValueError(f"channel {ch} is approved by the owner: its chain stays")
        after["channel_plugins"][c] = int(num or 0)
        ops.append({"op": "channel_plugin", "ch": c, "plugin": int(num or 0)})
    if not ops:
        raise ValueError("nothing to change: give plugins, channel_plugins or macros")
    if _rack_guard(after, locked) != _rack_guard(f, locked):
        raise ValueError("that changes an approved channel's effects or macros: not written")
    st.song_edit(ops)
    f = st.facts
    return {"ok": True, "summary": f"{len(f['plugins'])} plugins", "plugins": f["plugins"],
            "channel_plugins": f["channel_plugins"]}


@tool("edit_effect", "Edit one Rack device while preserving every other setting. add appends an effect to a channel; "
      "update patches only the supplied parameters/name/bypass of plugin; remove reconnects its inputs to its output; "
      "move reorders plugin within channel to position (1-based). Shared devices affect every channel using them; "
      "moving shared chains is refused. Approved channels and master chains are protected. Read get_state first. One undo step.",
      {"action": {"type": "string", "enum": ["add", "update", "remove", "move"]},
       "channel": {"type": "integer", "description": "1-based, required for add/move"},
       "plugin": {"type": "integer"}, "effect": {"type": "string", "enum": list(plugins.EFFECTS)},
       "changes": {"type": "object", "description": "Only supplied effect parameters, name or bypass are changed"},
       "position": {"type": "integer", "description": "1-based destination within the channel chain"}}, ["action"])
def edit_effect(st, a):
    with st.lock:
        st._need_compiled()
        f, P, routes = st.facts, copy.deepcopy(st.facts["plugins"]), {}
        action, n = a["action"], a.get("plugin")
        if action == "add":
            ch = _channel(st, a.get("channel"))
            if a.get("effect") not in plugins.EFFECTS:
                raise ValueError("choose an effect from describe_effects")
            n = next((i for i in range(1, plugins.MAX_PLUGINS + 1) if i not in P), None)
            if n is None:
                raise ValueError("the Rack has no free plugin slots")
            chain = _chain(f, ch)
            P[n] = {"effect": a["effect"]}
            if chain:
                P[chain[-1]]["output"] = n
            else:
                routes[ch + 1] = n
        elif action in ("update", "remove", "move"):
            if type(n) is not int or n not in P:
                raise ValueError("plugin must be an existing Rack device ID from get_state")
        else:
            raise ValueError("action must be add, update, remove or move")
        if action in ("add", "update"):
            changes = a.get("changes", {})
            allowed = {"name", "bypass"} | {s[0] for s in plugins.params_of(P[n]["effect"])}
            if not isinstance(changes, dict) or set(changes) - allowed:
                raise ValueError("changes may contain only effect parameters, name and bypass")
            if action == "update" and not changes:
                raise ValueError("give the settings to change")
            P[n].update(changes)
        elif action == "remove":
            nxt = P[n].get("output", 0)
            for p in P.values():
                if p.get("output") == n:
                    if nxt:
                        p["output"] = nxt
                    else:
                        p.pop("output", None)
            routes = {i + 1: nxt for i, v in enumerate(f["channel_plugins"]) if v == n}
            del P[n]
        elif action == "move":
            ch = _channel(st, a.get("channel"))
            chain = _chain(f, ch)
            pos = a.get("position")
            if n not in chain or type(pos) is not int or not 1 <= pos <= len(chain):
                raise ValueError("plugin and position must be within the channel's chain")
            if any(set(chain) & set(_chain(f, c)) for c in range(len(f["channels"])) if c != ch):
                raise ValueError("cannot reorder a shared chain; its other channels would change")
            chain.remove(n)
            chain.insert(pos - 1, n)
            for i, k in enumerate(chain):
                P[k].pop("output", None)
                if i + 1 < len(chain):
                    P[k]["output"] = chain[i + 1]
            routes[ch + 1] = chain[0]
        result = _set_plugins(st, {"plugins": P, "channel_plugins": routes})
        return {**result, "plugin": n, "summary": f"{action} plugin {n} (one undo step)"}


@tool("export_song", "Start an export using RENDER & EXPORT's immutable snapshot. Formats: IT, WAV, MP3, OGG, FLAC. "
      "Can include aligned stems and an IT alongside audio. region is an existing named section; omit for whole song. "
      "game_loop writes loop metadata for WAV/OGG/FLAC over that section (or whole song), not the audition row loop. "
      "Defaults: saved mix, ignore audition mutes, no replacement. current mix includes unwritten faders and selected "
      "candidate; respect mutes includes solo. These choices affect only the export. replace:true only when the owner "
      "asked to replace previous outputs; source assets stay protected. Returns job_id and planned paths; use "
      "export_status until done/failed/cancelled. Warnings are not export failures.",
      {"format": {"type": "string", "enum": ["it", "wav", "mp3", "ogg", "flac"]},
       "destination": {"type": "string", "description": "Folder; relative paths are beside the song"},
       "name": {"type": "string", "description": "Filename stem without extension"},
       "region": {"type": "string"}, "game_loop": {"type": "boolean"}, "tail": {"type": "number", "minimum": 0, "maximum": 10},
       "song": {"type": "boolean"}, "stems": {"type": "boolean"}, "include_it": {"type": "boolean"},
       "mix": {"type": "string", "enum": ["saved", "current"]},
       "mutes": {"type": "string", "enum": ["ignore", "respect"]}, "replace": {"type": "boolean"}}, ["format"])
def export_song(st, a):
    with st.lock:
        if set(a) - set(TOOLS["export_song"][1]["properties"]):
            raise ValueError("unknown export option; use the tool's documented options")
        if a.get("format") not in ("it", "wav", "mp3", "ogg", "flac"):
            raise ValueError("format must be it, wav, mp3, ogg or flac")
        for k in ("game_loop", "song", "stems", "include_it", "replace"):
            if k in a and type(a[k]) is not bool:
                raise ValueError(f"{k} must be true or false")
        opts = {("fmt" if k == "format" else "loop" if k == "game_loop" else k): v for k, v in a.items()}
        st.request_export(opts)
        return {"ok": True, **export_status(st, {})}


@tool("export_status", "Inspect the current/latest export job: ID, status, progress, planned paths, published files, "
      "snapshot ID, warnings and failure reason. Only status done confirms files were exported. Optional job_id "
      "refuses accidentally inspecting a newer job; the app retains one current/latest job.", {"job_id": {"type": "string"}})
def export_status(st, a):
    with st.lock:
        result = st.export_result
        if a.get("job_id") and (not result or result.get("job_id") != a["job_id"]):
            raise ValueError("that export is not the current/latest job")
        if not result:
            return {"job": None}
        job = st.export_job
        return {"job": {**copy.deepcopy(result), "planned_files": [str(p) for p, _, _ in job["todo"]],
                        "cancel_requested": job["cancel"].is_set()}}


@tool("cancel_export", "Request cancellation of the matching queued/rendering export. Required job_id prevents "
      "cancelling someone else's newer job. Publishing is an atomic final phase and cannot be interrupted. Check "
      "export_status for the final outcome; a cancellation request is not proof that a job was cancelled.",
      {"job_id": {"type": "string"}}, ["job_id"])
def cancel_export(st, a):
    with st.lock:
        if not isinstance(a.get("job_id"), str) or not a["job_id"]:
            raise ValueError("give the export job_id to cancel")
        status = export_status(st, a)["job"]
        requested = status["status"] in ("queued", "rendering")
        if requested:
            st.cancel_export()
        return {"ok": True, "cancellation_requested": requested, **export_status(st, a)}


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


@tool("cue", "Request showing a place in the app (0-based order and row, 1-based channel), optionally playing "
      "from there. Queued until get_state.ui.applied_request acknowledges request_id; inspect playback state "
      "to confirm playing. Requires an open window; expires after 10 seconds.",
      {"order": {"type": "integer"}, "row": {"type": "integer"}, "channel": {"type": "integer"},
       "play": {"type": "boolean"}}, ["order"])
def cue(st, a):
    with st.lock:
        st._need_compiled()
        order, row = a["order"], a.get("row", 0)
        n = len(st.facts["orders"])
        if type(order) is not int or not 0 <= order < n:
            raise ValueError(f"no order {order} (0..{n - 1})")
        if type(row) is not int or not 0 <= row < st.facts["orders"][order]["rows"]:
            raise ValueError("row is outside this pattern")
        channel = _channel(st, a["channel"]) if a.get("channel") is not None else None
        result = _transport(st, "cue")
        st.cue.update(order=order, row=row, channel=channel, play=bool(a.get("play")))
        return result


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
      "sounding. Includes revision for update_listening_note. Stored channels are 0-based; update inputs are 1-based. Act on the words.")
def read_notes(st, a):
    with st.lock:
        return {"notes": [dict(copy.deepcopy(n), revision=agent_sessions._id(n)) for n in st.notes or []]}


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


@tool("undo", "Undo the last change to the song (anyone's), one step. Refuses changes to approved material or owner-controlled levels.")
def undo(st, a):
    with st.lock:
        if not st.history:
            raise ValueError("nothing to undo")
        from .history import unpack_step
        st._need_compiled()
        _guard_restore(st, unpack_step(st.history[-1]))
        st.undo()
        return {"ok": True, "summary": "undone"}


def _same_channel_levels_after_move(old, target, oldmix, newmix):
    """Recognize an exact channel permutation/addition/removal, including its faders.
    Matching the column's cells and settings prevents treating an ordinary level edit as a move.
    """
    if [p.name for p in old.patterns] != [p.name for p in target.patterns]:
        return False
    def column(m, c):
        return [[r[c] for r in p.rows] for p in m.patterns]
    a, b = oldmix or {}, newmix or {}
    remaining, pairs = set(range(len(target.channels))), []
    for i, ch in enumerate(old.channels):
        j = next((j for j in sorted(remaining) if ch == target.channels[j] and column(old, i) == column(target, j)
                  and all((a.get(k) or {}).get(str(i)) == (b.get(k) or {}).get(str(j)) for k in ('volume', 'pan'))), None)
        if j is not None:
            pairs.append((i, j))
            remaining.remove(j)
    if len(pairs) != min(len(old.channels), len(target.channels)):
        return False
    if {k: v for k, v in a.items() if k not in ('volume', 'pan')} != {k: v for k, v in b.items() if k not in ('volume', 'pan')}:
        return False
    return all((a.get(k) or {}).get(str(i)) == (b.get(k) or {}).get(str(j)) for i, j in pairs for k in ('volume', 'pan'))


def _guard_restore(st, step, compiled=None):
    from .api import from_yaml
    from .song import load_song_text
    target = from_yaml(step["text"])
    mod = compiled if compiled is not None else load_song_text(step["text"], st.base_dir, str(st.song_path))[0]
    old = st.mod
    newmix = (step.get("meta") or {}).get("mix", st.meta.get("mix"))
    channel_levels_changed = (any((a.volume, a.pan) != (b.volume, b.pan) for a, b in zip(old.channels, mod.channels))
                              or newmix != st.meta.get("mix"))
    def levels(m):
        return m.mix_volume, m.global_volume
    common = {k: set(st.song.get(k) or {}) & set(target.get(k) or {}) for k in ("samples", "instruments")}
    if (levels(mod) != levels(old)
            or (channel_levels_changed and not _same_channel_levels_after_move(old, mod, st.meta.get("mix"), newmix))
            or any((old.samples[n-1].volume, old.samples[n-1].global_volume, old.samples[n-1].pan) !=
                   (mod.samples[n-1].volume, mod.samples[n-1].global_volume, mod.samples[n-1].pan) for n in common["samples"])
            or any((old.instruments[n-1].global_volume, old.instruments[n-1].pan) !=
                   (mod.instruments[n-1].global_volume, mod.instruments[n-1].pan) for n in common["instruments"])
            ):
        raise ValueError("restoring would change the owner's mixer levels or pan; restore it in PROJECT instead")
    for kind in ("patterns", "samples"):
        for k, entry in (st.song.get(kind) or {}).items():
            if isinstance(entry, dict) and entry.get("approved") and (target.get(kind) or {}).get(k) != entry:
                raise ValueError(f"restoring would change approved {kind} {k}")
    locked = _approved_channels(st)
    target_channels = (target.get("module") or {}).get("channels") or []
    pats = {p.name: p for p in mod.patterns}
    for c in locked:
        if c >= len(target_channels) or target_channels[c] != _channels(st)[c]:
            raise ValueError(f"restoring would change approved channel {c + 1}")
        for p in old.patterns:
            q = pats.get(p.name)
            if q is None or [r[c] for r in p.rows] != [r[c] for r in q.rows]:
                raise ValueError(f"restoring would change notes in approved channel {c + 1}")
    protected_patterns = {p.name for p in old.patterns if st.pattern_entry(p.name).get("approved")}
    if any(p.name in protected_patterns and (p.name not in pats or pats[p.name].rows != p.rows) for p in old.patterns):
        raise ValueError("edit would change compiled notes in an approved pattern")
    if locked or protected_patterns:
        if (mod.instruments is None) != (old.instruments is None):
            raise ValueError("restoring would change instrument mode for approved material")
        for kind, numbers in _protected_voices(st).items():
            if any((target.get(kind) or {}).get(n) != (st.song.get(kind) or {}).get(n) for n in numbers):
                raise ValueError("restoring would change sounds used by approved material")
    target_rack = {"plugins": plugins.to_song(mod.plugins), "channel_plugins": [c.plugin for c in mod.channels],
                   "macros": {f"SF{n:X}": t for n, t in mod.macros.items()}}
    if _rack_guard(target_rack, locked) != _rack_guard(st.facts, locked):
        raise ValueError("restoring would change approved effects or macros")


@tool("checkpoint", "Named checkpoints: list, save, diff, restore or delete. Save never overwrites an existing name. "
      "Restore is one undoable step and refuses changes to current approved material or owner-controlled levels. "
      "Use diff before restore. Checkpoints include audition settings and sample fingerprints, using PROJECT's storage.",
      {"action": {"type": "string", "enum": ["list", "save", "diff", "restore", "delete"]},
       "name": {"type": "string"}}, ["action"])
def checkpoint(st, a):
    with st.lock:
        action = a["action"]
        if action == "list":
            return {"checkpoints": list(st.checkpoints), "undo_steps": len(st.history), "redo_steps": len(st.future)}
        if action not in ("save", "diff", "restore", "delete"):
            raise ValueError("unknown checkpoint action")
        name = str(a.get("name") or "").strip()
        if action == "restore" and name in st.checkpoints:
            from .history import unpack_step
            st._need_compiled()
            _guard_restore(st, unpack_step(st.checkpoints[name]))
        result = st.checkpoint(name, action)
        return {"ok": True, "summary": f"checkpoint {action}: {name}", **result}


@tool("redo", "Redo the last undone edit, one step. Refuses changes to approved material or owner-controlled levels.")
def redo(st, a):
    with st.lock:
        if not st.future:
            raise ValueError("nothing to redo")
        from .history import unpack_step
        st._need_compiled()
        _guard_restore(st, unpack_step(st.future[-1]))
        st.undo(redo=True)
        return {"ok": True, "summary": "redone"}


@tool("check", "The song's errors and warnings as the compiler reports them.")
def check(st, a):
    return {"error": st.error, "warnings": (st.facts or {}).get("warnings", [])}


from . import agent_sounds  # registers library and synthesis tools after the shared tool helpers
from . import agent_projects  # registers phrase and project workflows
from . import agent_sessions  # registers recording, notes, transport and history inspection

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
- Use capture_phrase/read_phrase/edit_phrase/render_phrase/phrase_diff for frozen alternatives, including variant -1
  with the line absent. Ratings and acceptance stay with the owner in PHRASES. Read the current ID before editing.
- Use project_status/create_project/import_project/open_project/collect_project/relink_samples for projects. Creation,
  importing and collecting do not switch songs. After open_project, discard old selections and call get_state before
  editing: subsequent tools use the newly opened song. Never claim a missing-sample or read-only project is editable.
- Use get_state for the Rack's selected channel, exact plugin settings and audition state. UI reports can be stale;
check ui_stale and never assume that a soloed channel is the selected Rack channel.
- create_channel adds empty space before write_cells can put notes there. Prefer edit_effect for individual Rack
changes so unrelated devices keep their settings. Use set_audition for solo/loop and stop_playback to stop music.
- edit_channel renames/moves/removes channels; use its returned channel_map before subsequent edits. Removing
populated channels requires the owner's request to delete those notes. create_sample adds a new slot, not a tryout
choice. create_instrument adds a voice; in sample mode it first wraps existing samples at their original numbers.
- edit_instrument/edit_sample patch existing slots; inspect_sample reports usage and source-frame bounds before
processing. process_sample writes new audio; slice_sample/render_sample create new slots. Use audio gain,
normalization or RMS loudness processing only when requested. delete_slot refuses any referenced slot and retains
audio files. No tool silently deletes notes to free a slot. Offer alternative sounds through offer_samples.
- edit_section manages named sections with RAW order bounds (including skips/end markers). edit_pattern maintains
patterns; materialize inline/flow YAML notation before cell edits. Read before shrinking; discard_rows requires an explicit
request to remove those notes. write_patterns and transform_patterns edit several patterns atomically. A repeated
pattern changes every occurrence. copy_pattern_region copies or moves selected fields; inspect occupied destinations
before requesting overwrite. Never transpose a voice merely to change its sound. Use checkpoints before experiments.
- export_song takes a frozen snapshot. Choose saved/current mix and ignore/respect mutes deliberately. Never say an
export succeeded until export_status reports done; report its published paths and distinguish warnings from failures.
cancel_export needs the matching job_id. Never enable replacement unless the owner asked to overwrite the outputs.
- Save a named checkpoint before a substantial experiment; diff it before restoring. A queued playback request is
not confirmed until get_state.ui.applied_request matches its request_id.
- search_library searches indexed file names; similar_samples compares measured timbre, not musical suitability.
index_library scans only the requested or configured roots; poll library_status with the job_id before using results.
synthesis_catalog discovers sources, installed patches and parameter names. read_sound_recipe inspects a recipe;
save_sound_recipe writes a new version (changes replace top-level fields, clear removes them), leaving the original.
render_synthesis/render_paint create new audio assets asynchronously. Poll synthesis_status until done; never present
queued or failed output as usable. cancel_synthesis prevents publication after the current renderer returns. Rendered
files are not automatically selected or added to the song: use offer_samples for alternatives, create_sample only
for an explicitly requested new slot. Do not download missing synths automatically; report the dependency.
- recording_status enumerates inputs without opening them. Use control_recording open/start only when the owner
asks to record or use their input; never enable recording just to test an edit. Stop saves a new take for the owner;
manage_take inspects, offers candidates or creates new slots/multisamples. Failed saves remain pending in memory:
retry stop, or discard only at the owner's request. Recorded takes are session-listed; WAV files persist.
- update_listening_note records the owner's words, never invented hearing. Read revision before updating/deleting;
do not remove or rewrite feedback just because you acted on it. Notes are outside song undo.
- pause_playback/resume_playback preserve playback position; stop clears that resume state. Check UI acknowledgement.
inspect_history lists snapshots nearest first and previews current-to-snapshot changes; it does not restore anything.
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


class ChatStopped(Exception):
    pass


COMPACT_PROMPT = """Summarize this conversation for continuing work on the same song. Preserve the owner's requests,
decisions, approved sounds/levels, exact pattern/channel/row references, completed edits, failures and unfinished work.
Distinguish measurements from guesses. Do not perform any actions or call tools. Return only a concise factual handoff,
ideally under 1200 words. The next turn can read the song again for details."""


class Chat:
    """One conversation with the configured model, its tools run on the State. The display list is what the panel
    shows; the history is the provider's own message list, kept append-only (thinking blocks pass back unchanged)."""

    def __init__(self):
        self.display, self.history, self.busy, self.provider = [], [], False, None
        self.session = None  # Claude Code's session id: the next message resumes it
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.process = None
        self.run_id = None
        self.compacting = False
        self.summary = ""
        self.usage = {}
        self._summary_parts = []
        self.active_tools = 0
        self.tool_done = threading.Condition(self.lock)

    def snapshot(self):
        with self.lock:
            code = self.provider and self.provider[0] == "claude_code"
            # A size estimate, not a tokenizer or a claim about the model's context-window limit.
            payload = {"messages": self.history, "tools": tool_list(), "system": SYSTEM}
            size = len(json.dumps(payload, default=lambda x: x.model_dump() if hasattr(x, "model_dump") else str(x)))
            tokens = ((self.usage["input"] + self.usage["output"]) if self.usage else None) if code else (size + 3) // 4
            context = {"tokens": tokens, "source": "last reported" if code else "estimate", **self.usage}
            return {"messages": list(self.display[-200:]), "busy": self.busy, "stopping": self.busy and self.cancel.is_set(),
                    "compacting": self.compacting, "context": context,
                    "can_compact": bool(self.history or self.session), "settings": public_settings()}

    def clear(self):
        with self.lock:
            if self.busy:
                raise ValueError("the agent is still working: wait for it to finish")
            self.display, self.history, self.provider, self.session = [], [], None, None
            self.summary, self.usage = "", {}

    def stop(self):
        with self.lock:
            if not self.busy:
                return
            self.cancel.set()
            p = self.process
        if p is not None and p.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                import signal
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def _check_stop(self):
        if self.cancel.is_set():
            raise ChatStopped()

    def _request(self, fn):
        """Release the panel promptly on Stop; an in-flight HTTP request may still finish remotely.
        Its thread only returns data: a discarded response can never execute tools or change history."""
        self._check_stop()
        done, result = threading.Event(), []
        def request():
            try:
                result.append((True, fn()))
            except Exception as e:
                result.append((False, e))
            finally:
                done.set()
        threading.Thread(target=request, daemon=True).start()
        while not done.wait(.05):
            self._check_stop()
        self._check_stop()
        ok, value = result[0]
        if not ok:
            raise value
        return value

    def _usage(self, usage):
        if not usage:
            return
        if hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        inp = usage.get("prompt_tokens", usage.get("input_tokens"))
        if inp is not None:
            self.usage = {"input": int(inp) + int(usage.get("cache_read_input_tokens") or 0)
                          + int(usage.get("cache_creation_input_tokens") or 0),
                          "output": int(usage.get("completion_tokens", usage.get("output_tokens")) or 0)}

    def compact(self, st):
        s = load_settings()
        with self.lock:
            if self.busy:
                raise ValueError("stop the agent or wait for it before compacting")
            if not (self.history or self.session):
                raise ValueError("there is no conversation to compact")
            if self.provider != (s.get("provider"), s.get("base_url", ""), s.get("model", "")):
                raise ValueError("the provider changed: start a new conversation before compacting")
            self.busy, self.compacting = True, True
            self.cancel, self.run_id = threading.Event(), uuid.uuid4().hex
        threading.Thread(target=self._run, args=(st, s, COMPACT_PROMPT), daemon=True).start()

    def send(self, st, text, context=None):
        if not text.strip():
            raise ValueError("enter a message first")
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
                self.summary, self.usage = "", {}
            self.provider, self.busy = identity, True
            self.tool_state = st
            self.cancel, self.run_id = threading.Event(), uuid.uuid4().hex
        self.display.append({"role": "you", "text": text, "context": context})
        prompt = f"[the owner's selection: {context}]\n{text}" if context else text
        threading.Thread(target=self._run, args=(st, s, prompt), daemon=True).start()

    def _say(self, role, text):
        if text and text.strip():
            if self.compacting and role == "agent":
                self._summary_parts.append(text.strip())
                return
            self.display.append({"role": role, "text": text.strip()})

    def remote_tool(self, st, name, args, run_id):
        """Reject late MCP calls from a stopped Claude subprocess; independent MCP clients use agent.run."""
        with self.lock:
            if not self.busy or run_id != self.run_id or self.cancel.is_set() or self.compacting:
                return {"error": "this agent turn was stopped; nothing changed"}
            self.active_tools += 1
        try:
            return run(st, name, args)
        finally:
            with self.tool_done:
                self.active_tools -= 1
                self.tool_done.notify_all()

    def _tool(self, st, name, args):
        st = getattr(self, 'tool_state', st)
        if self.cancel.is_set() or (st is not None and st.closed):
            return {"error": "agent stopped; nothing changed"}
        out = run(st, name, args)
        self.display.append({"role": "tool", "tool": name, "args": _short(args, 200),
                             "text": out.get("error") or out.get("summary") or _short(out, 200), "error": bool(out.get("error"))})
        return out

    def _run(self, st, s, prompt):
        try:
            if self.compacting:
                self._compact(st, s)
            else:
                {"claude_code": self._claude_code, "anthropic": self._anthropic}.get(s["provider"], self._openai)(st, s, prompt)
            self._check_stop()
        except ChatStopped:
            self._say("status", "Stopped. Completed edits remain; UNDO can reverse them.")
        except Exception as e:  # noqa: BLE001 - shown in the panel
            self.display.append({"role": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            try:
                p = self.process
                if p is not None:
                    if p.poll() is None:
                        self.stop()
                    p.wait()
                    for stream in (p.stdin, p.stdout, p.stderr):
                        stream.close()
            finally:
                with self.tool_done:
                    while self.active_tools:
                        self.tool_done.wait(.1)
                    self.busy, self.compacting, self.process = False, False, None

    def _compact(self, st, s):
        self._summary_parts = []
        if s["provider"] == "claude_code":
            self._claude_code(st, s, COMPACT_PROMPT)
            summary = "\n".join(self._summary_parts)
        elif s["provider"] == "anthropic":
            import anthropic
            messages = copy.deepcopy(self.history) + [{"role": "user", "content": COMPACT_PROMPT}]
            def request():
                with anthropic.Anthropic(api_key=s.get("api_key") or None) as client:
                    return client.messages.create(model=s.get("model") or "claude-opus-5-5", max_tokens=4096,
                                                  system=SYSTEM, messages=messages)
            resp = self._request(request)
            if resp.stop_reason != "end_turn":
                raise ValueError("summary was incomplete; the previous context was kept")
            summary = "\n".join(b.text for b in resp.content if b.type == "text")
        else:
            _, model, _ = connection(s)
            body = {"model": model, "messages": copy.deepcopy(self.history) + [{"role": "user", "content": COMPACT_PROMPT}]}
            resp = self._request(lambda: compatible_request(s, "/chat/completions", body))
            choice = resp["choices"][0]
            if choice.get("finish_reason") not in (None, "stop") or choice["message"].get("tool_calls"):
                raise ValueError("summary was incomplete; the previous context was kept")
            summary = choice["message"].get("content") or ""
        self._check_stop()
        if not summary.strip():
            raise ValueError("the model returned no summary; the previous context was kept")
        context = "Summary of earlier conversation (read the song again to verify its current state):\n" + summary.strip()
        history = ([] if s["provider"] in ("anthropic", "claude_code") else [{"role": "system", "content": SYSTEM}])
        history.append({"role": "user", "content": context})
        if s["provider"] != "claude_code" and len(json.dumps(history, default=str)) >= len(json.dumps(self.history, default=str)):
            raise ValueError("the summary did not reduce context; the previous context was kept")
        self.summary, self.session, self.usage, self.history = context, None, {}, history
        self.display.append({"role": "status", "text": "Context compacted. The visible transcript is kept.\n" + summary.strip()})

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
        server.setdefault("env", {})["VT_AGENT_RUN_ID"] = self.run_id
        args = cmd + ["-p", "--output-format", "stream-json", "--verbose", "--strict-mcp-config",
                      "--mcp-config", json.dumps({"mcpServers": {} if self.compacting else {"vulturetracker": server}}),
                      "--tools", "", "--allowedTools", "" if self.compacting else "mcp__vulturetracker",
                      "--append-system-prompt", SYSTEM]
        if s.get("model"):
            args += ["--model", s["model"]]
        if s.get("effort"):
            args += ["--effort", s["effort"]]
        if self.session:
            args += ["--resume", self.session]
            if self.compacting:
                args += ["--fork-session"]
        elif self.summary:
            prompt = self.summary + "\n\nCurrent request:\n" + prompt
        with self.lock:
            self._check_stop()
            p = self.process = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", cwd=str(Path(__file__).resolve().parent.parent),
                start_new_session=os.name != "nt", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        err = []
        threading.Thread(target=lambda: err.extend(p.stderr), daemon=True).start()
        p.stdin.write(prompt)
        p.stdin.close()
        calls, done = {}, False
        for line in p.stdout:
            self._check_stop()
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type")
            if ev.get("session_id") and not self.compacting:
                self.session = ev["session_id"]
            if kind == "system" and ev.get("subtype") == "init":
                bad = [m["name"] for m in ev.get("mcp_servers") or [] if m.get("status") not in ("connected", None)]
                if bad:
                    self._say("error", f"Claude Code could not start the song tools ({', '.join(bad)})")
            elif kind == "assistant":
                if not self.compacting:
                    self._usage((ev.get("message") or {}).get("usage"))
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
                    if self.compacting:
                        raise ValueError("compaction failed; the previous context was kept: " + str(ev.get("result") or ev.get("subtype")))
                    self._say("error", str(ev.get("result") or ev.get("subtype")))
        p.wait()
        self._check_stop()
        if p.returncode and not done:
            raise RuntimeError(f"claude exited with {p.returncode}: {''.join(err)[-600:].strip() or 'no message'}")
        if self.compacting and not done:
            raise ValueError("compaction did not finish; the previous context was kept")

    def _anthropic(self, st, s, prompt):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("the Anthropic API needs the anthropic package: pip install anthropic")
        client = anthropic.Anthropic(api_key=s.get("api_key") or None)  # else ANTHROPIC_API_KEY or an `ant auth` profile
        tools = tool_list()
        self.history.append({"role": "user", "content": prompt})
        for _ in range(40):
            self._check_stop()
            messages = copy.deepcopy(self.history)
            resp = self._request(lambda: client.beta.messages.create(
                model=s.get("model") or "claude-opus-5-5", max_tokens=16000, system=SYSTEM, tools=tools,
                messages=messages, betas=["server-side-fallback-2026-07-01"],
                # passed through extra_body: this anthropic package predates the keywords for them
                extra_body={"output_config": {"effort": s.get("effort") or "medium"}, "fallbacks": "default"}))
            self._usage(getattr(resp, "usage", None))
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
                    results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": bool(out.get("error")),
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
            self._check_stop()
            body = {"model": model, "messages": copy.deepcopy(self.history), "tools": tools}
            resp = self._request(lambda: compatible_request(s, "/chat/completions", body))
            self._usage(resp.get("usage"))
            msg = resp["choices"][0]["message"]
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
