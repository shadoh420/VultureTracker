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
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vulturetracker import agent, gui, mcp
from vulturetracker.wavload import write_wav

from tests.test_gui import RATE, SONG_BLOCK, sine


class Fake(BaseHTTPRequestHandler):
    """Answers POSTs with the next of `answers`, keeping the request bodies in `seen`."""
    answers, seen, headers_seen = [], [], []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append((self.path, body))
        type(self).headers_seen.append(dict(self.headers))
        out = json.dumps(type(self).answers.pop(0)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        type(self).seen.append((self.path, None))
        type(self).headers_seen.append(dict(self.headers))
        out = json.dumps(type(self).answers.pop(0)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class FakeKeyring:
    """A dict-backed stand-in for the keyring module. `broken` raises on every call (Linux without a secret service);
    `dropping` accepts a key and forgets it (the null backend)."""

    def __init__(self, broken=False, dropping=False):
        self.store, self.broken, self.dropping = {}, broken, dropping

    def get_password(self, service, account):
        if self.broken:
            raise RuntimeError("No recommended backend was available")
        return self.store.get((service, account))

    def set_password(self, service, account, password):
        if self.broken:
            raise RuntimeError("No recommended backend was available")
        if not self.dropping:
            self.store[(service, account)] = password

    def delete_password(self, service, account):
        if self.broken or (service, account) not in self.store:
            raise RuntimeError("PasswordDeleteError")
        del self.store[(service, account)]


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write_wav(self.dir / "a.wav", RATE, [sine(440)], root_note=69)
        write_wav(self.dir / "b.wav", RATE, [sine(880)])
        (self.dir / "song.yaml").write_bytes(SONG_BLOCK.encode("utf-8"))
        self.states = []
        self._settings, self._keyring = agent.settings_path, agent.keyring
        agent.settings_path = lambda: self.dir / "agent.json"   # never the user's own settings
        agent.keyring = None                                    # nor the user's own credential store

    def tearDown(self):
        agent.settings_path, agent.keyring = self._settings, self._keyring
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
        Fake.answers, Fake.seen, Fake.headers_seen = list(answers), [], []
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

    def file(self):
        return json.loads((self.dir / "agent.json").read_text(encoding="utf-8"))

    def test_settings_key_in_file_without_keyring(self):
        pub = agent.save_settings({"provider": "anthropic", "api_key": " k1 "})
        self.assertEqual((pub["key_store"], pub["has_key"]), ("file", True))
        self.assertEqual(self.file()["api_key"], "k1")
        self.assertEqual(agent.load_settings()["api_key"], "k1")
        pub = agent.save_settings({"clear_key": True})
        self.assertFalse(pub["has_key"])
        self.assertNotIn("api_key", self.file())

    def test_settings_key_in_keyring(self):
        agent.keyring = fake = FakeKeyring()
        pub = agent.save_settings({"provider": "openai", "api_key": "k2"})
        self.assertEqual((pub["key_store"], pub["has_key"]), ("keyring", True))
        self.assertEqual(fake.store, {("VultureTracker", "openai"): "k2"})
        self.assertNotIn("api_key", self.file())
        self.assertEqual(agent.load_settings()["api_key"], "k2")   # what the chat's readers see
        agent.save_settings({"model": "m"})                        # a later save never copies it back
        self.assertNotIn("api_key", self.file())
        self.assertEqual(self.file()["model"], "m")
        # a key saved before keyring was installed moves into the store on the next load
        fake.store.clear()
        (self.dir / "agent.json").write_text(json.dumps({"provider": "openai", "api_key": "legacy"}), encoding="utf-8")
        self.assertEqual(agent.load_settings()["api_key"], "legacy")
        self.assertEqual(fake.store[("VultureTracker", "openai")], "legacy")
        self.assertNotIn("api_key", self.file())
        pub = agent.save_settings({"clear_key": True})
        self.assertEqual((pub["has_key"], fake.store), (False, {}))
        agent.save_settings({"clear_key": True})                   # nothing stored: no error
        self.assertFalse(agent.public_settings()["has_key"])

    def test_settings_keyring_failures_fall_back_to_the_file(self):
        agent.keyring = FakeKeyring(broken=True)
        pub = agent.save_settings({"provider": "anthropic", "api_key": "k3"})
        self.assertEqual((pub["key_store"], pub["has_key"], self.file()["api_key"]), ("file", True, "k3"))
        agent.keyring = FakeKeyring(dropping=True)
        pub = agent.save_settings({"api_key": "k4"})
        self.assertEqual((pub["key_store"], pub["has_key"], self.file()["api_key"]), ("file", True, "k4"))

    def test_base_url_warning(self):
        warn = "the key would travel in clear: base_url is neither localhost nor https"
        for url, expect in [("http://10.0.0.5:11434/v1", warn), ("http://localhost:11434/v1", ""),
                            ("http://[::1]:8080/v1", ""), ("https://api.example.com/v1", ""), ("", "")]:
            self.assertEqual(agent.save_settings({"base_url": url})["base_url_warning"], expect, url)

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

    def test_compatible_providers_edit_refuse_and_undo(self):
        for provider in ("gemini", "ollama", "lmstudio", "openai"):
            with self.subTest(provider=provider):
                st = self.state()
                st.song_edit([{"op": "mark", "what": "pattern", "key": "p1", "approved": True}])
                original = self.read()
                def call(n, name, args):
                    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                        {"id": str(n), "type": "function", "function": {"name": name, "arguments": json.dumps(args)},
                         "extra_content": {"google": {"thought_signature": "opaque-signature"}}}]}}]}
                port = self._fake([
                    call(1, "write_cells", {"pattern": "p2", "cells": [{"row": 1, "channel": 2, "cell": "E-5 02 v40 ..."}]}),
                    call(2, "read_pattern", {"pattern": "p2", "from_row": 1, "to_row": 1}),
                    call(3, "write_cells", {"pattern": "p1", "cells": [{"row": 0, "channel": 1, "cell": "D-5 01 ... ..."}]}),
                    call(4, "undo", {}),
                    {"choices": [{"message": {"role": "assistant", "content": "Edited, checked protection, then undone."}}]}])
                # Keep the real HTTP serialization/tool loop; redirect only Google's fixed endpoint to our fixture.
                real_connection = agent.connection
                def local_connection(s):
                    _, model, key = real_connection(s)
                    return f"http://127.0.0.1:{port}/v1", model, key
                agent.save_settings({"provider": provider, "model": "test-model", "api_key": "fixture-key"})
                with mock.patch.object(agent, "connection", side_effect=local_connection):
                    chat = self._chat(st, "Edit one note, check it, refuse approved notes, and undo")
                self.assertFalse(chat.busy)
                self.assertEqual(chat.display[-1]["text"], "Edited, checked protection, then undone.", chat.display)
                self.assertEqual(len(Fake.seen), 5)
                self.assertEqual(Fake.headers_seen[0]["Authorization"], "Bearer fixture-key")
                result = lambda i: json.loads(Fake.seen[i][1]["messages"][-1]["content"])
                self.assertTrue(result(1)["ok"])
                self.assertIn("E-5 02 v40 ...", result(2)["rows"][0])
                self.assertIn("approved", result(3)["error"])
                self.assertEqual(self.read(), original)
                self.assertEqual(Fake.seen[1][1]["messages"][-2]["tool_calls"][0]["extra_content"],
                                 {"google": {"thought_signature": "opaque-signature"}})
                self.assertTrue(any(m.get("error") for m in chat.display if m["role"] == "tool"))

    def test_model_discovery_does_not_save_or_reuse_another_providers_key(self):
        agent.save_settings({"provider": "gemini", "api_key": "private-key"})
        before = self.file()
        port = self._fake([{"data": [{"id": "local-b"}, {"id": "local-a"}, {"id": "local-a"}]}])
        out = agent.discover_models({"provider": "ollama", "base_url": f"http://127.0.0.1:{port}/v1"})
        self.assertEqual(out, {"models": ["local-a", "local-b"]})
        self.assertEqual(Fake.seen, [("/v1/models", None)])
        self.assertNotIn("Authorization", Fake.headers_seen[0])
        self.assertEqual(self.file(), before)

    def test_provider_switch_does_not_carry_file_key_or_endpoint(self):
        agent.save_settings({"provider": "gemini", "api_key": "private-key", "base_url": "https://old.example/v1"})
        agent.save_settings({"provider": "ollama"})
        self.assertFalse(agent.public_settings()["has_key"])
        self.assertEqual(agent.connection(agent.load_settings()), ("http://localhost:11434/v1", "", ""))
        agent.save_settings({"provider": "gemini"})
        self.assertEqual(agent.load_settings()["api_key"], "private-key")
        agent.keyring = FakeKeyring()
        agent.save_settings({"provider": "gemini", "api_key": "stored-key"})
        agent.save_settings({"provider": "lmstudio"})
        self.assertFalse(agent.public_settings()["has_key"])
        agent.save_settings({"provider": "gemini"})
        self.assertEqual(agent.load_settings()["api_key"], "stored-key")

    def test_gemini_rack_maps_and_invalid_arguments(self):
        st = self.state()
        original = self.read()
        def answer(name, args):
            return {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": name, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}
        replies = [answer("set_plugins", {"plugins": json.dumps({"1": {"effect": "echo"}}),
                                          "channel_plugins": json.dumps({"1": 1})}),
                   answer("undo", []),  # malformed arguments must not accidentally undo the edit
                   answer("song_overview", {}), answer("undo", {}),
                   {"choices": [{"message": {"role": "assistant", "content": "done"}}]}]
        agent.save_settings({"provider": "gemini", "api_key": "fixture"})
        with mock.patch.object(agent, "compatible_request", side_effect=replies) as request:
            chat = self._chat(st, "change the rack then undo")
        self.assertEqual(chat.display[-1]["text"], "done", chat.display)
        self.assertEqual(self.read(), original)
        results = [json.loads(m["content"]) for m in chat.history if m["role"] == "tool"]
        self.assertTrue(results[0]["ok"])
        self.assertIn("nothing changed", results[1]["error"])
        self.assertEqual(results[2]["channels"][0]["effects"], ["echo"])
        tools = {t["function"]["name"]: t["function"] for t in request.call_args.args[2]["tools"]}
        self.assertNotIn("parameters", tools["song_overview"])
        self.assertEqual(tools["set_module"]["parameters"]["properties"]["value"]["anyOf"],
                         [{"type": "string"}, {"type": "integer"}])
        self.assertEqual(agent.TOOLS["set_plugins"][1]["properties"]["plugins"], {"type": "object"})

    def test_gemini_defaults_and_actionable_errors(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "API key"):
                agent.connection({"provider": "gemini"})
        s = {"provider": "gemini", "api_key": "secret", "base_url": "http://unrelated.example/v1"}
        self.assertEqual(agent.connection(s), ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash", "secret"))
        for code, text in [(429, "quota"), (401, "API key"), (400, "tool-calling")]:
            with mock.patch.object(agent.urllib.request, "urlopen", side_effect=agent.urllib.error.HTTPError(
                    "https://example.com", code, "bad", {}, io.BytesIO(b'secret'))):
                with self.assertRaisesRegex(RuntimeError, text) as ctx:
                    agent.compatible_request(s, "/chat/completions", {})
                self.assertNotIn("secret", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
