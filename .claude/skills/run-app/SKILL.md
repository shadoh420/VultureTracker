---
name: run-app
description: Launch the VultureTracker app (gui) on a song, for the owner or headless to check a change to gui.py, server.py or gui.html in a real page, and drive it through its API. Use for any "run/open/check the app" request in this repository.
---

# Running the app

Changes to `gui.py`, `server.py` or `gui.html` need a check in a real page (AGENTS.md "Where to start"). `gui.html` is
re-read on every request; `gui.py` and `server.py` need the server restarted.

## Opening it for the owner

```
Start-Process -FilePath pythonw.exe -ArgumentList "-m","vulturetracker","gui","<song.yaml>" -WorkingDirectory <checkout>
```

Run it from source inside the checkout. `pythonw` has no console, so never add `-WindowStyle Hidden`: Windows applies
that to the first window and the app stays invisible. Confirm a process whose `MainWindowTitle` is `VultureTracker`
exists. A port that answers does not prove the window is visible.

## Headless, to check a change

1. `python -m vulturetracker gui <song> --no-browser --port 8765` in the background. It prints the URL, which
   carries `?token=`.
2. The port and the launch's token are also in the user folder's `running.json` (`%APPDATA%\VultureTracker` on
   Windows). Every `/api/...` request needs the token as the `X-VT-Token` header or `?token=`; the page `/` needs
   `?token=`. Use `127.0.0.1`, not `localhost`.
3. Poll `GET /api/state` until it answers, then load the page: the built-in browser pane at the URL, or a pywebview
   window driven with `evaluate_js`. The page's globals are top-level `let`, so read bare `S`, not `window.S`.
   Override `window.alert` first, because a dialog blocks `evaluate_js`. `EDQ.n===0` means the queued edits are done.
4. Check the console for errors and look at the affected view. Stop the server when done.

## Driving it instead of handing the owner steps

Set features up yourself, then tell the owner only what to play and listen for:
- `POST /api/songedit` with `{"ops": [...]}` makes song edits, one undo step each.
- From the page, `act(name, body)` calls `POST /api/<name>` and refreshes.
- The `vulturetracker` MCP server (`.mcp.json`) exposes the agent tools on the open song.

Use a copy of a demo song (`demo2/iron_relay.yaml`) for tests, never the owner's song. Delete any listening notes
(`<song>.notes.json`, `.notes.md`) a test made on a real song. Close your browser-pane tab afterwards so the owner
uses the app's own window. The owner's ear decides sounds and levels: report measurements, never what something
sounds like.
