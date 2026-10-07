"""`python -m vulturetracker mcp`: a Model Context Protocol server on stdin/stdout, so an agent (Claude Code, Claude
Desktop, any MCP client) can work on the song open in the running app with the tools in agent.py. It is a bridge: each
call goes to the app over its local HTTP port (written to the user folder's running.json when the app starts, or
--port), where the tool runs on the open song as one undo step, shown in the app's agent log.

Register it with Claude Code:  claude mcp add vulturetracker -- python -m vulturetracker mcp
"""
import json
import sys
import urllib.error
import urllib.request

from . import __version__
from .agent import running_path

PROTOCOL = "2025-06-18"


def _port(port=None):
    if port:
        return int(port)
    try:
        return int(json.loads(running_path().read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError):
        raise RuntimeError("VultureTracker is not running: open the song in the app first "
                           "(python -m vulturetracker gui song.yaml)")


def _http(port, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 json.dumps(body).encode("utf-8") if body is not None else None,
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"the app is not answering on port {port} ({getattr(e, 'reason', e)}): is it still open?")


def handle(msg, port=None):
    """The JSON-RPC answer to one request (None for a notification)."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notifications/initialized and the like
    try:
        if method == "initialize":
            result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion") or PROTOCOL,
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "vulturetracker", "version": __version__},
                      "instructions": "Tools for the song open in the VultureTracker app. The owner decides by ear: "
                                      "measure, don't claim to hear; levels and approved entries are the owner's; "
                                      "offer sounds as tryout candidates."}
        elif method == "tools/list":
            try:
                tools = _http(_port(port), "/api/tools")["tools"]
            except RuntimeError:
                from .agent import tool_list
                tools = tool_list()  # the list is the same; calls will say the app is not open
            result = {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]}
                                for t in tools]}
        elif method == "tools/call":
            p = msg.get("params") or {}
            try:
                out = _http(_port(port), "/api/tool", {"name": p.get("name"), "args": p.get("arguments") or {}})
            except RuntimeError as e:
                out = {"error": str(e)}
            result = {"content": [{"type": "text", "text": json.dumps(out, indent=1, default=str)}],
                      "isError": "error" in out}
        elif method == "ping":
            result = {}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}
    except Exception as e:  # noqa: BLE001 - every request gets an answer
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(port=None, stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = handle(msg, port)
        if out is not None:
            stdout.write(json.dumps(out) + "\n")
            stdout.flush()
    return 0
