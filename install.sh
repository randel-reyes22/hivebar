#!/bin/sh
# Install Hivebar into SwiftBar's plugin folder (as a symlink, so `git pull` updates it).
# Usage: ./install.sh              install, refreshing every 30s, and open SwiftBar at login
#        ./install.sh 1m           install with another interval (10s, 1m, 5m, ...)
#        ./install.sh --no-login   don't add SwiftBar to your login items
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

login=1
interval=30s
for arg in "$@"; do
  case "$arg" in
    --no-login) login=0 ;;
    *) interval="$arg" ;;
  esac
done
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

new_dir=0
if [ -z "$dir" ]; then
  dir="${HIVEBAR_PLUGIN_DIR:-$HOME/.config/swiftbar-plugins}"
  defaults write com.ameba.SwiftBar PluginDirectory -string "$dir"
  echo "Set SwiftBar plugin folder to $dir."
  new_dir=1
fi
mkdir -p "$dir"

# Replace any earlier Hivebar link, whatever its interval.
for f in "$dir"/hivebar.*.py; do
  [ -L "$f" ] && [ "$(readlink "$f")" = "$SRC" ] && rm -f "$f"
done

chmod +x "$SRC"
ln -s "$SRC" "$dir/hivebar.$interval.py"
echo "Linked $dir/hivebar.$interval.py -> $SRC"

# A running SwiftBar only reads its plugin folder at launch.
if [ "$new_dir" = 1 ] && pgrep -x SwiftBar >/dev/null; then
  pkill -x SwiftBar; sleep 1
fi
open -a SwiftBar

# Start SwiftBar (and so Hivebar) when you log in. macOS may ask once to let your
# terminal control System Events; if you decline, nothing else changes.
if [ "$login" = 1 ]; then
  app="$(osascript -e 'POSIX path of (path to application "SwiftBar")' 2>/dev/null | sed 's:/$::')"
  if [ -n "$app" ] && osascript - "$app" >/dev/null 2>&1 <<'OSA'
on run argv
  tell application "System Events"
    if not (exists login item "SwiftBar") then make login item at end with properties {path:item 1 of argv, hidden:false}
  end tell
end run
OSA
  then
    echo "SwiftBar will open at login (System Settings > General > Login Items to change)."
  else
    echo "Couldn't add SwiftBar to login items; add it in System Settings > General > Login Items."
  fi
fi
sleep 2
open -g "swiftbar://refreshallplugins" 2>/dev/null || true
cat <<EOF

Done. Hivebar is in the menu bar, top right: a hexagon icon followed by your session count.
Not there?
  - On a MacBook with a notch, too many icons get hidden behind it. Hold Cmd and drag
    Hivebar further right, or quit some other menu-bar apps.
  - If SwiftBar asked you to choose a plugin folder, choose: $dir
  - Optional, plan usage per account: $(dirname "$SRC")/hivebar.30s.py setup-limits
EOF
