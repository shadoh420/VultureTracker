# Security

## Reporting

Report a vulnerability privately through GitHub: on https://github.com/shadoh420/VultureTracker open the Security tab
and choose "Report a vulnerability". Do not open a public issue for it.

## Supported version

The latest release on GitHub ([releases](https://github.com/shadoh420/VultureTracker/releases/latest)) is the only
supported one; a fix ships as a new release.

## What the software does with the outside world

- The app is an HTTP server bound to 127.0.0.1 only. Requests whose Host is not the local machine or whose Origin is
  another page are refused (`vulturetracker/gui.py`), since the POSTs open, create and write files.
- The importers read untrusted files: IT, XM, S3M and MOD modules, Guitar Pro tabs, MIDI files and WAV, FLAC, AIFF,
  OGG and MP3 samples. A malformed file is meant to be reported as an error, never run; a crash on one is a bug worth
  reporting.
- The downloads the app offers (Surge XT, Dexed, faustwasm) are fetched from pinned URLs and verified against pinned
  SHA-256 digests before they are unpacked.
- The AGENT panel's chat sends the open song's text to the provider you configured (the Anthropic API, a local
  OpenAI-compatible server, or Claude Code on your own login) and to nothing else; its settings and any API key are
  kept in your user folder, not beside the song. The app makes no other network calls and has no telemetry.
- Each release lists the SHA-256 of `vulturetracker.exe`, `ffmpeg.exe` and the zip; the exe is not code-signed.
