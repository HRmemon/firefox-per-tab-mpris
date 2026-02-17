# Firefox Per-Tab MPRIS

Exposes **every active media tab** in Firefox as a separate [MPRIS](https://specifications.freedesktop.org/mpris-spec/latest/) D-Bus player. Tools like `playerctl` and Waybar can see and control each tab individually.

Firefox's built-in MPRIS support only exposes a single player regardless of how many tabs have media. This project gives you per-tab control.

```
$ playerctl -l
firefox_tab_13
firefox_tab_18
firefox_tab_19

$ playerctl -a metadata --format '{{playerName}}: {{artist}} - {{title}} [{{status}}]'
firefox_tab_13: Ali Sethi - Gulon Main Rang [Playing]
firefox_tab_18: Humera Channa - Mujh Se Pehli Si Muhabbat [Paused]
firefox_tab_19: www.instagram.com - Instagram [Playing]
```

## How it works

```
┌─────────────────────────────────────────────────────────┐
│ Firefox                                                 │
│  ┌──────────┐  runtime.sendMessage  ┌────────────────┐  │
│  │content.js├──────────────────────►│ background.js  │  │
│  │(per tab) │◄──────────────────────┤                │  │
│  └──────────┘  runtime.onMessage    └───────┬────────┘  │
│   Detects <video>/<audio>                   │           │
│   Extracts metadata                  Native Messaging   │
│   Executes play/pause/seek                  │           │
└─────────────────────────────────────────────┼───────────┘
                                              │
                          ┌───────────────────▼──────────┐
                          │  media_host.py (Python)      │
                          │                              │
                          │  Tab 13 → MPRIS Player 13    │
                          │  Tab 18 → MPRIS Player 18    │
                          │  Tab 19 → MPRIS Player 19    │
                          │                              │
                          │  Each on its own D-Bus       │
                          │  session bus connection       │
                          └──────────────┬───────────────┘
                                         │
                    D-Bus Session Bus (org.mpris.MediaPlayer2.firefox_tab_*)
                                         │
                          ┌──────────────▼───────────────┐
                          │  playerctl / Waybar / etc.   │
                          └──────────────────────────────┘
```

1. **Content script** is injected into every page. Detects `<video>` and `<audio>` elements, extracts metadata (with YouTube-specific handling for title/channel/thumbnail), and reports state to the background script.

2. **Background script** aggregates media state from all tabs and relays it to the native messaging host. Routes commands back to the correct tab.

3. **Python native host** creates a separate MPRIS D-Bus player for each active media tab. Each player gets its own bus connection to avoid conflicts. Implements the full `org.mpris.MediaPlayer2.Player` interface (Play, Pause, Stop, Next, Previous, Seek, SetPosition, Volume). Cleans up when tabs close.

## Requirements

- Linux with D-Bus session bus
- Firefox
- Python 3.10+
- [dbus-next](https://github.com/altdesktop/python-dbus-next) (`pip install dbus-next` or `yay -S python-dbus-next` on Arch)
- [playerctl](https://github.com/altdesktop/playerctl) (optional, for CLI control — `sudo pacman -S playerctl`)

## Installation

```bash
git clone https://github.com/HRmemon/firefox-per-tab-mpris.git
cd firefox-per-tab-mpris
./install.sh
```

The install script will:
- Check and help install dependencies
- Create a launcher wrapper with the correct Python path
- Install the native messaging manifest to `~/.mozilla/native-messaging-hosts/`
- Print instructions for loading the WebExtension

Then load the extension in Firefox:
1. Go to `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on...**
3. Select `extension/manifest.json`

## Usage

```bash
# List all per-tab MPRIS players
playerctl -l

# Show metadata for all players
playerctl -a metadata --format '{{playerName}}: {{artist}} - {{title}} [{{status}}]'

# Control a specific tab
playerctl -p firefox_tab_13 play-pause
playerctl -p firefox_tab_13 next
playerctl -p firefox_tab_13 volume 0.5

# View native host log
tail -f /tmp/firefox-mpris-host.log
```

## Waybar integration

Add to your Waybar config (`~/.config/waybar/config.jsonc`):

```jsonc
"custom/mpris": {
    "exec": "playerctl -a metadata --format '{\"text\": \"{{playerName}}: {{markup_escape(title)}}\", \"tooltip\": \"{{playerName}}\\n{{markup_escape(title)}} - {{markup_escape(artist)}}\\n{{status}}\", \"class\": \"{{lc(status)}}\"}' -F",
    "return-type": "json",
    "max-length": 50,
    "on-click": "playerctl play-pause",
    "on-click-right": "playerctl next",
    "on-click-middle": "playerctl previous",
    "on-scroll-up": "playerctl volume 0.05+",
    "on-scroll-down": "playerctl volume 0.05-",
    "escape": true
}
```

See `waybar/config-snippet.jsonc` for CSS styling suggestions.

## Disabling Firefox's built-in MPRIS

To avoid the duplicate built-in Firefox player, set `media.hardwaremediakeys.enabled` to `false` in `about:config`.

## Project structure

```
extension/
  manifest.json     WebExtension manifest (Manifest V2)
  background.js     Background script — bridges content scripts and native host
  content.js        Content script — media detection and control per tab
native-host/
  media_host.py     Python native messaging host — per-tab MPRIS via dbus-next
waybar/
  config-snippet.jsonc          Waybar module config and CSS
install.sh                      Setup script
```

## License

MIT
