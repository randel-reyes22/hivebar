#!/bin/sh
# Install Hivebar into SwiftBar's plugin folder (as a symlink, so `git pull` updates it).
# Usage: ./install.sh              install, refreshing every 30s
#        ./install.sh 1m           install with another interval (10s, 1m, 5m, ...)
#        ./install.sh --uninstall
set -eu

SRC="$(CDPATH= cd -- "$(dirname -- "$0")" >/dev/null && pwd)/hivebar.30s.py"

[ "$(uname -s)" = "Darwin" ] || { echo "Hivebar needs macOS (it runs inside SwiftBar)."; exit 1; }

dir="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"

if [ "${1:-}" = "--uninstall" ]; then
  # Status lines point at this checkout; put the originals back before it can be deleted.
  python3 "$SRC" setup-limits --undo || true
  [ -n "$dir" ] || { echo "SwiftBar has no plugin folder set; nothing to remove."; exit 0; }
  removed=0
  for f in "$dir"/hivebar.*.py; do
    if [ -L "$f" ] && [ "$(readlink "$f")" = "$SRC" ]; then
      rm -f "$f" && echo "Removed $f" && removed=1
    fi
  done
  [ "$removed" = 1 ] || echo "No Hivebar symlink found in $dir."
  exit 0
fi

interval="${1:-30s}"
case "$interval" in
  *[!0-9smhd]*|"") echo "Interval must look like 30s, 1m or 5m."; exit 1 ;;
esac

command -v python3 >/dev/null 2>&1 || { echo "python3 not found. Install Xcode Command Line Tools: xcode-select --install"; exit 1; }

if ! open -Ra SwiftBar 2>/dev/null; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installing SwiftBar..."
    brew install --cask swiftbar
  else
    echo "Install SwiftBar first: https://swiftbar.app (or: brew install --cask swiftbar)"; exit 1
  fi
fi

if [ -z "$dir" ]; then
  dir="${HIVEBAR_PLUGIN_DIR:-$HOME/.config/swiftbar-plugins}"
  defaults write com.ameba.SwiftBar PluginDirectory -string "$dir"
  echo "Set SwiftBar plugin folder to $dir (restart SwiftBar if it was already running)."
fi
mkdir -p "$dir"

# Replace any earlier Hivebar link, whatever its interval.
for f in "$dir"/hivebar.*.py; do
  [ -L "$f" ] && [ "$(readlink "$f")" = "$SRC" ] && rm -f "$f"
done

chmod +x "$SRC"
ln -s "$SRC" "$dir/hivebar.$interval.py"
echo "Linked $dir/hivebar.$interval.py -> $SRC"

open -a SwiftBar
open -g "swiftbar://refreshallplugins" 2>/dev/null || true
echo "Done. Look for the hexagon in your menu bar."
