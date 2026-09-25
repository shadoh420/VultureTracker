#!/bin/bash
# Cloud sessions (Claude Code on the web) start from a bare Linux container: install what the tests need.
# libopenmpt comes from Ubuntu (0.7.x; Windows uses vendor/'s 0.8.9 DLL), the Python packages from pip, and the page
# test drives the preinstalled Chromium through VT_CHROMIUM. Idempotent; does nothing outside the cloud.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

if ! ldconfig -p | grep -q libopenmpt.so; then
  apt-get update -qq >/dev/null 2>&1 || true   # a third-party PPA may be refused by the proxy; Ubuntu's own lists load
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq libopenmpt0t64 >/dev/null
fi

python3 -m pip install -q --disable-pip-version-check pyyaml numpy imageio-ffmpeg Pillow playwright

if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -x /opt/pw-browsers/chromium ]; then
  echo 'export VT_CHROMIUM=/opt/pw-browsers/chromium' >> "$CLAUDE_ENV_FILE"
fi
