# Security

## Reporting

Report a vulnerability privately through GitHub: on https://github.com/shadoh420/VultureTracker open the Security tab
and choose "Report a vulnerability". Do not open a public issue for it.

## Supported version

The latest release on GitHub ([releases](https://github.com/shadoh420/VultureTracker/releases/latest)) is the only
supported one; a fix ships as a new release.

## What the software does with the outside world

- The app is an HTTP server bound to 127.0.0.1 only. Requests whose Host is not the local machine or whose Origin is
  another page (or `null`) are refused (`vulturetracker/server.py`), since the POSTs open, create and write files. Every
  request for the page, the API and the song's files must also carry a token made for each launch (the address the app
  opens has it; `running.json` in the user folder holds it for the MCP bridge), so a web page's `<img>` or `<audio>`,
  which sends no Origin, and another account on the same machine get nothing.
- The importers read untrusted files: IT, XM, S3M and MOD modules, Guitar Pro tabs, MIDI files and WAV, FLAC, AIFF,
  OGG and MP3 samples. A malformed file is meant to be reported as an error, never run; a crash on one is a bug worth
  reporting.
- The downloads the app offers (Surge XT, Dexed, faustwasm) are fetched from pinned URLs and verified against pinned
  SHA-256 digests before they are unpacked.
- The AGENT panel's chat sends the open song's text, your listening notes and library file names to the provider you
  configured (the Anthropic API, Gemini, a local OpenAI-compatible server, or Claude Code on your own login) and to
  nothing else; its settings are kept in your user folder, not beside the song, and the API key in the OS credential
  store when `keyring` works, else in `agent.json` as plain text (readable by your account only). The agent tools reach
  files only inside the song's folder and the sample library's folders, and text in a song is treated as data, never as
  instructions; still, a song from someone else can try to talk a model into edits, which are undoable. The app makes no other network calls and has no telemetry.
- Each release lists the SHA-256 of `vulturetracker.exe`, `ffmpeg.exe` and the zip; the exe is not code-signed.
