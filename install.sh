#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NATIVE_HOST_DIR="$HOME/.mozilla/native-messaging-hosts"
NATIVE_HOST_MANIFEST="com.media_tabs.firefox.json"
HOST_SCRIPT="$SCRIPT_DIR/native-host/media_host.py"

echo "=== Firefox Per-Tab MPRIS Installer ==="
echo

# --- Check dependencies ---
echo "[1/4] Checking dependencies..."

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install it: sudo pacman -S python"
    exit 1
fi

# Resolve the real python3 path (pyenv shims don't work when Firefox
# launches the native host with a minimal PATH)
PYTHON3_PATH="$(python3 -c 'import sys; print(sys.executable)')"
echo "  Python: $PYTHON3_PATH"

if ! "$PYTHON3_PATH" -c "import dbus_next" 2>/dev/null; then
    echo "WARNING: dbus-next not found for $PYTHON3_PATH"
    echo "Install it with one of:"
    echo "  yay -S python-dbus-next   (AUR)"
    echo "  pip install dbus-next"
    echo
    read -rp "Try installing via pip now? [Y/n] " ans
    if [[ "${ans,,}" != "n" ]]; then
        pip install --user dbus-next
    else
        echo "Please install dbus-next before using the extension."
    fi
fi

if ! command -v playerctl &>/dev/null; then
    echo "NOTE: playerctl not found. Install it for CLI control:"
    echo "  sudo pacman -S playerctl"
fi

echo "  Dependencies OK."
echo

# --- Set up native messaging host ---
echo "[2/4] Installing native messaging host..."

chmod +x "$HOST_SCRIPT"

# Write a launcher wrapper with the resolved python path so it works
# regardless of the user's shell environment (pyenv, virtualenv, etc.)
LAUNCHER="$SCRIPT_DIR/native-host/media_host_launcher.sh"
cat > "$LAUNCHER" <<WRAPPER
#!/usr/bin/env bash
exec "$PYTHON3_PATH" "$HOST_SCRIPT" "\$@"
WRAPPER
chmod +x "$LAUNCHER"

mkdir -p "$NATIVE_HOST_DIR"

cat > "$NATIVE_HOST_DIR/$NATIVE_HOST_MANIFEST" <<EOF
{
  "name": "com.media_tabs.firefox",
  "description": "Firefox per-tab MPRIS native messaging host",
  "path": "$LAUNCHER",
  "type": "stdio",
  "allowed_extensions": ["firefox-mpris-per-tab@local"]
}
EOF

echo "  Manifest installed: $NATIVE_HOST_DIR/$NATIVE_HOST_MANIFEST"
echo "  Launcher: $LAUNCHER"
echo "  Host script: $HOST_SCRIPT"
echo

# --- Extension install instructions ---
echo "[3/4] WebExtension installation:"
echo
echo "  Option A — Temporary (for development/testing):"
echo "    1. Open Firefox → about:debugging → This Firefox"
echo "    2. Click 'Load Temporary Add-on...'"
echo "    3. Select: $SCRIPT_DIR/extension/manifest.json"
echo
echo "  Option B — Permanent (unsigned, requires config change):"
echo "    1. Open Firefox → about:config"
echo "    2. Set xpinstall.signatures.required = false"
echo "       (Only works in Firefox Developer Edition / Nightly / ESR)"
echo "    3. Package the extension: cd $SCRIPT_DIR/extension && zip -r ../firefox-mpris.xpi ."
echo "    4. Open about:addons → Install from file → select firefox-mpris.xpi"
echo
echo "  Option C — Publish on addons.mozilla.org (recommended for distribution):"
echo "    See: https://extensionworkshop.com/documentation/publish/"
echo

# --- Verification ---
echo "[4/4] Verification commands (run after loading extension + playing media):"
echo
echo "  playerctl -l"
echo "  playerctl -a metadata --format '{{playerName}}: {{title}} [{{status}}]'"
echo "  playerctl -p firefox_tab_<ID> play-pause"
echo "  tail -f /tmp/firefox-mpris-host.log"
echo
echo "=== Installation complete ==="
