"""The agent tools (agent.py) on an open song: what they read, the edits they make as one undo step with the pattern
marked `by: agent`, what they refuse (approved entries, levels), measure's change between calls; the MCP server's
JSON-RPC; and the chat panel's loop against stand-in servers for the Anthropic API and an OpenAI-compatible local model
(no network, no tokens spent)."""
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vulturetracker import agent, gui, mcp
from vulturetracker.wavload import write_wav

from tests.test_gui import RATE, SONG_BLOCK, sine


class Fake(BaseHTTPRequestHandler):
    """Answers POSTs with the next of `answers`, keeping the request bodies in `seen`."""
    answers, seen = [], []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append((self.path, body))
        out = json.dumps(type(self).answers.pop(0)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_wav(self.dir / "a.wav", RATE, [sine(440)], root_note=69)
        write_wav(self.dir / "b.wav", RATE, [sine(880)])
        (self.dir / "song.yaml").write_bytes(SONG_BLOCK.encode("utf-8"))
        self.states = []
        self._settings = agent.settings_path
        agent.settings_path = lambda: self.dir / "agent.json"   # never the user's own settings

    def tearDown(self):
        agent.settings_path = self._settings
        from tests.test_gui import TestGui
        TestGui.tearDown(self)

    def state(self):
        st = gui.State(self.dir / "song.yaml")
        self.states.append(st)
        return st

    def read(self):
        return (self.dir / "song.yaml").read_bytes().decode("utf-8")

    def test_tools_read_edit_and_refuse(self):
        st = self.state()
        ov = agent.run(st, "song_overview", {})
        self.assertEqual([c["name"] for c in ov["channels"]], ["A", "B"])
        self.assertEqual(ov["orders"][0]["pattern"], "p1")
        rows = agent.run(st, "read_pattern", {"pattern": "p1", "to_row": 1})["rows"]
        self.assertEqual(rows[0], "00: C-5 01 ... ... | ... .. ... ...")
        out = agent.run(st, "write_cells", {"pattern": "p2", "cells": [{"row": 1, "channel": 2, "cell": "E-5 02 v40 ..."}]})
        self.assertTrue(out.get("ok"), out)
        self.assertIn("  p2:\n    by: you and agent\n", self.read())   # p2 had notes: the owner's and the agent's now
        self.assertEqual(st.pattern_rows(1)["rows"][1][1], "E-5 02 v40 ...")
        st.undo()
        self.assertNotIn("by:", self.read())
        # an approved channel or pattern is refused, and nothing is written
        st.song_edit([{"op": "mark", "what": "channel", "key": 1, "approved": True},
                      {"op": "mark", "what": "pattern", "key": "p1", "approved": True}])
        text = self.read()
        self.assertIn("    - {name: B, pan: 40, approved: true}\n", text)
        self.assertIn("  p1:\n    approved: true\n", text)
        self.assertIn("approved", agent.run(st, "write_cells", {"pattern": "p2", "cells": [{"row": 0, "channel": 2, "cell": "C-5 01 ... ..."}]})["error"])
        self.assertIn("approved", agent.run(st, "write_cells", {"pattern": "p1", "cells": [{"row": 0, "channel": 1, "cell": "C-5 01 ... ..."}]})["error"])
        self.assertEqual(self.read(), text)
        # a level is not a setting the tools set; a new pattern is the agent's
        self.assertIn("levels", agent.run(st, "set_module", {"key": "mix_volume", "value": 20})["error"])
        self.assertTrue(agent.run(st, "new_pattern", {"name": "p9", "rows": 4, "insert_at": 1}).get("ok"))
        self.assertIn("  p9:\n    by: agent\n", self.read())
        self.assertEqual(agent.run(st, "song_overview", {})["orders"][1]["pattern"], "p9")
        self.assertTrue(agent.run(st, "set_module", {"key": "key", "value": "A minor"}).get("ok"))
        self.assertEqual(agent.run(st, "key_check", {})["key"], "A minor")
        self.assertEqual(len(st.agent_log), 10)   # every call logged, the refused ones too

    def test_plugins_respect_approved_channels(self):
        st = self.state()
        st.song_edit([{"op": "mark", "what": "channel", "key": 0, "approved": True}])
        out = agent.run(st, "set_plugins", {"plugins": {"1": {"effect": "echo"}}, "channel_plugins": {"2": 1}})
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(st.facts["channel_plugins"], [0, 1])
        self.assertIn("approved", agent.run(st, "set_plugins", {"channel_plugins": {"1": 1}})["error"])

    def test_measure_reports_the_change(self):
        st = self.state()
        first = agent.run(st, "measure", {})
        self.assertIsNotNone(first["numbers"]["lufs"])
        self.assertNotIn("change_since_last", first)
        st.song_edit([{"op": "channel_add", "name": "C"}])
        second = agent.run(st, "measure", {})
        self.assertEqual(second["change_since_last"]["lufs"], 0.0)   # an empty channel changes nothing
        solo = agent.run(st, "measure", {"channels": [1]})
        self.assertLess(solo["numbers"]["lufs"], first["numbers"]["lufs"])

    def test_selection_and_cue(self):
        st = self.state()
        self.assertIsNone(agent.run(st, "get_selection", {})["selection"])
        st.selection = {"order": 0, "pattern": "p1", "rows": [0, 1], "channels": [0, 0]}
        sel = agent.run(st, "get_selection", {})
        self.assertEqual(sel["cells"], ["00: C-5 01 ... ...", "01: ... .. ... ..."])
        self.assertEqual(sel["sounding_at_first_row"][0]["name"], "A")
        agent.run(st, "cue", {"order": 1, "row": 2, "play": True})
        self.assertEqual(st.cue, {"id": 1, "order": 1, "row": 2, "channel": None, "play": True})

    def test_mcp_without_the_app(self):
        out = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(out["result"]["serverInfo"]["name"], "vulturetracker")
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        tools = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, port=1)["result"]["tools"]
        self.assertIn("write_cells", [t["name"] for t in tools])
        self.assertIn("inputSchema", tools[0])
        call = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "song_overview"}}, port=1)
        self.assertTrue(call["result"]["isError"])
        out = io.StringIO()
        mcp.serve(1, io.StringIO('{"jsonrpc":"2.0","id":4,"method":"ping"}\nnot json\n'), out)
        lines = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(lines[0], {"jsonrpc": "2.0", "id": 4, "result": {}})
        self.assertEqual(lines[1]["error"]["code"], -32700)

    def _fake(self, answers):
        Fake.answers, Fake.seen = list(answers), []
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def _chat(self, st, text, context=None):
        chat = agent.Chat()
        chat.send(st, text, context)
        for _ in range(200):
            if not chat.busy:
                break
            time.sleep(0.05)
        return chat

    def test_chat_anthropic(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("needs the anthropic package")
        st = self.state()
        msg = lambda content, stop: {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",  # noqa: E731
                                     "content": content, "stop_reason": stop, "stop_sequence": None,
                                     "usage": {"input_tokens": 1, "output_tokens": 1}}
        port = self._fake([msg([{"type": "text", "text": "Looking."},
                                {"type": "tool_use", "id": "tu_1", "name": "song_overview", "input": {}}], "tool_use"),
                           msg([{"type": "text", "text": "Two channels, A and B."}], "end_turn")])
        agent.save_settings({"provider": "anthropic", "api_key": "test-key"})
        old = os.environ.get("ANTHROPIC_BASE_URL")
        os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
        try:
            chat = self._chat(st, "what channels are there?", "channel 01 A")
        finally:
            if old is None:
                os.environ.pop("ANTHROPIC_BASE_URL")
            else:
                os.environ["ANTHROPIC_BASE_URL"] = old
        self.assertEqual([m["role"] for m in chat.display], ["you", "agent", "tool", "agent"], chat.display)
        self.assertEqual(chat.display[-1]["text"], "Two channels, A and B.")
        first, second = Fake.seen[0][1], Fake.seen[1][1]
        self.assertEqual(first["model"], "claude-opus-5-5")
        self.assertEqual(first["fallbacks"], "default")
        self.assertEqual(first["output_config"], {"effort": "medium"})
        self.assertIn("[the owner's selection: channel 01 A]", first["messages"][0]["content"])
        result = second["messages"][2]["content"][0]
        self.assertEqual((result["type"], result["tool_use_id"]), ("tool_result", "tu_1"))
        self.assertEqual(json.loads(result["content"])["channels"][0]["name"], "A")
        self.assertNotIn("api_key", agent.public_settings())
        self.assertTrue(agent.public_settings()["has_key"])

    def test_chat_claude_code(self):
        # a stand-in for `claude -p --output-format stream-json`: it records its arguments and stdin and prints the
        # events Claude Code prints (init, a tool call, its result, the answer, the result line)
        fake = self.dir / "fake_claude.py"
        fake.write_text(
            "import json, sys\n"
            "from pathlib import Path\n"
            "Path(sys.argv[1]).write_text(json.dumps({'argv': sys.argv[2:], 'stdin': sys.stdin.read()}))\n"
            "for ev in [{'type': 'system', 'subtype': 'init', 'session_id': 's1', 'mcp_servers': [{'name': 'vulturetracker', 'status': 'connected'}]},\n"
            "           {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'mcp__vulturetracker__song_overview', 'input': {}}]}},\n"
            "           {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': [{'type': 'text', 'text': json.dumps({'title': 'T', 'summary': 'two channels'})}]}]}},\n"
            "           {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'It has two channels.'}]}},\n"
            "           {'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's1', 'result': 'It has two channels.'}]:\n"
            "    print(json.dumps(ev), flush=True)\n", encoding="utf-8")
        seen = self.dir / "seen.json"
        old = agent.claude_command, agent.PORT
        agent.claude_command = lambda: [sys.executable, str(fake), str(seen)]
        agent.PORT = 8765
        try:
            st = self.state()
            agent.save_settings({"provider": "claude_code"})
            chat = agent.Chat()
            chat.send(st, "how many channels?")
            for _ in range(200):
                if not chat.busy:
                    break
                time.sleep(0.05)
            self.assertEqual([m["role"] for m in chat.display], ["you", "tool", "agent"], chat.display)
            self.assertEqual((chat.display[1]["tool"], chat.display[1]["text"]), ("song_overview", "two channels"))
            got = json.loads(seen.read_text())
            self.assertEqual(got["stdin"], "how many channels?")
            argv = got["argv"]
            self.assertIn("-p", argv)
            self.assertEqual(argv[argv.index("--tools") + 1], "")            # no built-in tools: only the song's
            self.assertEqual(argv[argv.index("--allowedTools") + 1], "mcp__vulturetracker")
            cfg = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]["vulturetracker"]
            self.assertEqual(cfg["args"][-2:], ["--port", "8765"])
            self.assertNotIn("--resume", argv)
            self.assertEqual(chat.session, "s1")
            chat.send(st, "and the tempo?")                                   # the next message resumes the session
            for _ in range(200):
                if not chat.busy:
                    break
                time.sleep(0.05)
            argv = json.loads(seen.read_text())["argv"]
            self.assertEqual(argv[argv.index("--resume") + 1], "s1")
        finally:
            agent.claude_command, agent.PORT = old

    def test_chat_local_model(self):
        st = self.state()
        port = self._fake([
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "key_check", "arguments": "{\"key\": \"C major\"}"}}]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "All in C major."}}]}])
        agent.save_settings({"provider": "openai", "model": "local", "base_url": f"http://127.0.0.1:{port}/v1"})
        chat = self._chat(st, "is it in C?")
        self.assertEqual([m["role"] for m in chat.display], ["you", "tool", "agent"], chat.display)
        self.assertEqual(Fake.seen[0][0], "/v1/chat/completions")
        self.assertEqual(Fake.seen[0][1]["messages"][0]["role"], "system")
        self.assertEqual(Fake.seen[1][1]["messages"][-1]["role"], "tool")
        self.assertEqual(json.loads(Fake.seen[1][1]["messages"][-1]["content"])["key"], "C major")


if __name__ == "__main__":
    unittest.main()
