"""Small chat tool directory and bounded, retrievable tool output.

The public MCP tool list stays unchanged. Chat uses these three entry points;
all song operations still pass through agent.run and its existing protections.
"""
import json
import threading
import uuid

PAGE_CHARS = 6000
KEEP_RESULTS = 32


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def call_details(name, args):
    """Show the song operation in the activity log, not its chat transport wrapper."""
    if name == "call_tool" and isinstance(args, dict) and isinstance(args.get("name"), str):
        try:
            return args["name"], json.loads(args["arguments_json"])
        except (KeyError, TypeError, ValueError):
            pass
    return name, args


def tool_list():
    from .agent import TOOLS
    specs = [
        ("find_tools", "Get full argument schemas for up to four named song tools. With no names, return a short "
         "table of contents; query filters that directory. Discover a tool before calling it. Available names: "
         + ", ".join(TOOLS),
         {"names": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
          "query": {"type": "string"}}, []),
        ("call_tool", "Run one discovered song tool. arguments_json is a JSON object encoded as a string, using "
         "the schema returned by find_tools. Existing approval and undo protections apply. Large results are paged; "
         "read their result_id instead of repeating an edit.",
         {"name": {"type": "string"}, "arguments_json": {"type": "string"}}, ["name", "arguments_json"]),
        ("read_tool_result", "Read a saved tool-result snapshot without running the tool again. Offsets are "
         "characters; follow next_offset for more. These are historical results, not live song state. The latest "
         "32 saved results are available until NEW or a provider change. Never repeat an edit to recover output.",
         {"result_id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
          "limit": {"type": "integer", "minimum": 1, "maximum": PAGE_CHARS}}, ["result_id"]),
    ]
    return [{"name": n, "description": d, "input_schema": {"type": "object", "properties": p, "required": r}}
            for n, d, p, r in specs]


class ToolContext:
    def __init__(self):
        self.results = {}
        self.lock = threading.RLock()

    def clear(self):
        with self.lock:
            self.results.clear()

    def remember(self, text):
        with self.lock:
            for key, value in self.results.items():
                if value == text:
                    return key
            key = uuid.uuid4().hex
            self.results[key] = text
            while len(self.results) > KEEP_RESULTS:
                del self.results[next(iter(self.results))]
            return key

    def page(self, key, offset=0, limit=PAGE_CHARS):
        with self.lock:
            text = self.results.get(key)
        if text is None:
            raise ValueError("result expired or unknown; re-read current state if needed, never repeat an edit")
        if type(offset) is not int or not 0 <= offset <= len(text):
            raise ValueError("offset must be a character position within the saved result")
        if type(limit) is not int or not 1 <= limit <= PAGE_CHARS:
            raise ValueError(f"limit must be 1..{PAGE_CHARS}")
        end = min(offset + limit, len(text))
        return {"result_id": key, "offset": offset, "total_chars": len(text), "content": text[offset:end],
                "next_offset": end if end < len(text) else None}

    def pack(self, out):
        text = dumps(out)
        if len(text) <= PAGE_CHARS:
            return out
        page = self.page(self.remember(text))
        page["summary"] = str(out.get("summary") or "Large tool result; use read_tool_result for the remaining content")[:400]
        if out.get("error"):
            page["error"] = str(out["error"])[:500]
        return page

    def call(self, st, name, args):
        from . import agent
        try:
            if not isinstance(args, dict):
                raise ValueError("tool arguments must be a JSON object; nothing changed")
            if name == "find_tools":
                names, query = args.get("names", []), args.get("query", "")
                if not isinstance(names, list) or len(names) > 4 or any(not isinstance(n, str) for n in names):
                    raise ValueError("names must contain at most four tool names")
                if not isinstance(query, str):
                    raise ValueError("query must be text")
                if names:
                    if any(n not in agent.TOOLS for n in names):
                        raise ValueError("unknown tool name; use find_tools without names for the directory")
                    return self.pack({"tools": [t for t in agent.tool_list() if t["name"] in names]})
                words = query.lower().split()
                return self.pack({"tools": [{"name": n, "description": d.split(". ")[0][:160]}
                                            for n, (d, _, _) in agent.TOOLS.items()
                                            if all(w in (n + " " + d).lower() for w in words)]})
            if name == "read_tool_result":
                return self.page(args["result_id"], args.get("offset", 0), args.get("limit", PAGE_CHARS))
            if name == "call_tool":
                name = args["name"]
                args = json.loads(args["arguments_json"])
                if not isinstance(args, dict):
                    raise ValueError("arguments_json must encode a JSON object; nothing changed")
            # Direct names also accept older conversations, but are not advertised in new chat requests.
            if not isinstance(name, str) or name not in agent.TOOLS:
                raise ValueError("unknown song tool; use find_tools")
            return self.pack(agent.run(st, name, args))
        except (ValueError, TypeError, KeyError) as e:
            return {"error": str(e)}

    def trim_history(self, history):
        """Keep four recent tool outputs in full; replace older large ones, retaining call IDs and errors."""
        results = []
        for message in history:
            if message.get("role") == "tool":
                results.append(message)
            elif message.get("role") == "user" and isinstance(message.get("content"), list):
                results.extend(b for b in message["content"] if isinstance(b, dict) and b.get("type") == "tool_result")
        for result in results[:-4]:
            text = result.get("content")
            if not isinstance(text, str) or len(text) <= 1200:
                continue
            try:
                out = json.loads(text)
            except ValueError:
                continue
            if not isinstance(out, dict):
                continue
            # Paged responses already refer to their original snapshot, including when this is a later page.
            key = out.get("result_id") if "total_chars" in out else self.remember(text)
            brief = {"result_id": key, "summary": str(out.get("summary") or "Earlier tool output")[:400],
                     "detail": "Use read_tool_result to retrieve this historical output; re-read state before editing."}
            if out.get("error"):
                brief["error"] = str(out["error"])[:500]
            result["content"] = dumps(brief)
