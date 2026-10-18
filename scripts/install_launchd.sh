#!/bin/sh
# Install the daily ECC download as a macOS LaunchAgent (runs as your user, no sudo).
# Usage: sh scripts/install_launchd.sh        Uninstall: sh scripts/install_launchd.sh --remove
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv)"
LABEL=de.powermarginlab.ecc-download
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
if [ "${1:-}" = "--remove" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$TARGET"; echo "removed $TARGET"; exit 0
fi
mkdir -p "$REPO/data/logs" "$HOME/Library/LaunchAgents"
sed -e "s#__UV__#$UV#g" -e "s#__REPO__#$REPO#g" "$REPO/ops/$LABEL.plist.template" > "$TARGET"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET"
echo "installed $TARGET (runs Mon-Fri 22:15; log: $REPO/data/logs/ecc_download.log)"
echo "test now with: launchctl kickstart -k gui/$(id -u)/$LABEL"
