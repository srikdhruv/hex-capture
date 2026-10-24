#!/usr/bin/env bash
# One-command launcher for the Blueprints bot (macOS / Linux):
#   curl -fsSL https://raw.githubusercontent.com/srikdhruv/hex-capture/main/run.sh | bash
# Extra bot options:  curl -fsSL .../run.sh | bash -s -- --save-token
# Downloads the right prebuilt "hexbot" into ~/.hexbot/ (re-downloads when a newer release exists) and runs it.
set -euo pipefail
REPO="srikdhruv/hex-capture"
BASE="https://github.com/$REPO/releases/download/latest"
DIR="$HOME/.hexbot"
mkdir -p "$DIR"

os="$(uname -s)"; arch="$(uname -m)"
case "$os" in
  Darwin) case "$arch" in arm64|aarch64) asset=hexbot-macos-arm64;; *) asset=hexbot-macos-x64;; esac;;
  Linux)  case "$arch" in x86_64|amd64) asset=hexbot-linux-x64;; *) echo "Unsupported Linux arch: $arch" >&2; exit 1;; esac;;
  *) echo "Unsupported OS: $os (on Windows use run.ps1)" >&2; exit 1;;
esac
bin="$DIR/$asset"

# Always run the newest build: compare the release sha with what the local binary reports.
remote="$(curl -fsSL "$BASE/version.txt?t=$(date +%s)" 2>/dev/null | awk '{print $1}' || true)"
local_v=""
[ -x "$bin" ] && local_v="$(HEXBOT_NO_UPDATE=1 "$bin" --version 2>/dev/null | head -1 || true)"
if [ ! -x "$bin" ] || { [ -n "$remote" ] && [ "$remote" != "$local_v" ]; }; then
  echo "Downloading $asset ${remote:+($remote)} ..." >&2
  curl -fL --progress-bar -o "$bin.part" "$BASE/$asset"
  chmod +x "$bin.part"
  mv -f "$bin.part" "$bin"
fi
if [ "$os" = "Darwin" ] && command -v xattr >/dev/null 2>&1; then
  xattr -d com.apple.quarantine "$bin" 2>/dev/null || true
fi
echo "Starting hexbot (Ctrl+C to stop). Logs: $DIR/logs" >&2
if [ ! -t 0 ] && (exec </dev/tty) 2>/dev/null; then
  exec "$bin" "$@" < /dev/tty
else
  exec "$bin" "$@"
fi
