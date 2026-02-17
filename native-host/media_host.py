#!/usr/bin/env python3
"""
Native messaging host that creates a separate MPRIS D-Bus player
for each active media tab in Firefox.

Dependencies: python-dbus-next (AUR) or pip install dbus-next
"""

import asyncio
import json
import struct
import sys
import signal
import logging
import threading
from typing import Optional

from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method, dbus_property, signal as dbus_signal  # noqa: F401
from dbus_next import Variant, BusType, PropertyAccess

logging.basicConfig(
    level=logging.INFO,
    filename="/tmp/firefox-mpris-host.log",
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("media_host")

MPRIS_PATH = "/org/mpris/MediaPlayer2"


# ---------------------------------------------------------------------------
# MPRIS Interface Definitions
# ---------------------------------------------------------------------------

class MediaPlayer2Interface(ServiceInterface):
    """org.mpris.MediaPlayer2 — root interface."""

    def __init__(self, identity: str):
        super().__init__("org.mpris.MediaPlayer2")
        self._identity = identity

    @method()
    def Raise(self):
        pass

    @method()
    def Quit(self):
        pass

    @dbus_property(access=PropertyAccess.READ)
    def CanQuit(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def CanRaise(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def HasTrackList(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> "s":
        return self._identity

    @dbus_property(access=PropertyAccess.READ)
    def DesktopEntry(self) -> "s":
        return "firefox"

    @dbus_property(access=PropertyAccess.READ)
    def SupportedUriSchemes(self) -> "as":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def SupportedMimeTypes(self) -> "as":
        return []


class PlayerInterface(ServiceInterface):
    """org.mpris.MediaPlayer2.Player — per-tab player."""

    def __init__(self, tab_id: int, send_command_fn):
        super().__init__("org.mpris.MediaPlayer2.Player")
        self._tab_id = tab_id
        self._send_command = send_command_fn

        self._playback_status = "Stopped"
        self._metadata: dict = {
            "mpris:trackid": Variant("o", "/org/mpris/MediaPlayer2/NoTrack"),
        }
        self._volume = 1.0
        self._position = 0  # microseconds
        self._duration = 0  # microseconds

    # -- Methods --

    @method()
    def Next(self):
        self._send_command(self._tab_id, "Next")

    @method()
    def Previous(self):
        self._send_command(self._tab_id, "Previous")

    @method()
    def Pause(self):
        self._send_command(self._tab_id, "Pause")

    @method()
    def PlayPause(self):
        self._send_command(self._tab_id, "PlayPause")

    @method()
    def Stop(self):
        self._send_command(self._tab_id, "Stop")

    @method()
    def Play(self):
        self._send_command(self._tab_id, "Play")

    @method()
    def Seek(self, offset: "x"):
        self._send_command(self._tab_id, "Seek", offset=offset)

    @method()
    def SetPosition(self, track_id: "o", position: "x"):
        self._send_command(self._tab_id, "SetPosition", position=position)

    @method()
    def OpenUri(self, uri: "s"):
        pass

    # -- Signals --

    @dbus_signal()
    def Seeked(self, position: "x"):
        pass

    # -- Properties --

    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> "s":
        return self._playback_status

    @dbus_property(access=PropertyAccess.READ)
    def Rate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> "a{sv}":
        return self._metadata

    @dbus_property()
    def Volume(self) -> "d":
        return self._volume

    @Volume.setter
    def Volume(self, value: "d"):
        self._volume = max(0.0, min(1.0, value))
        self._send_command(self._tab_id, "Volume", volume=self._volume)

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "x":
        return self._position

    @dbus_property(access=PropertyAccess.READ)
    def MinimumRate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def MaximumRate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def CanGoNext(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanGoPrevious(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanPlay(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanPause(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanSeek(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanControl(self) -> "b":
        return True

    # -- State update from extension --

    def update_state(self, state: dict):
        """Update state from extension. Returns dict of changed property
        names -> raw values for emit_properties_changed."""
        changed_props = {}

        new_status = "Playing" if state.get("playing") else "Paused"
        if new_status != self._playback_status:
            self._playback_status = new_status
            changed_props["PlaybackStatus"] = new_status

        new_pos = int(state.get("position", 0) * 1_000_000)
        self._position = new_pos

        duration = state.get("duration", 0)
        if duration and duration != float("inf"):
            self._duration = int(duration * 1_000_000)
        else:
            self._duration = 0

        new_vol = state.get("volume", 1.0)
        if state.get("muted"):
            new_vol = 0.0
        if abs(new_vol - self._volume) > 0.01:
            self._volume = new_vol
            changed_props["Volume"] = new_vol

        title = state.get("title") or state.get("tabTitle") or "Unknown"
        artist = state.get("artist") or ""
        art_url = state.get("artUrl") or ""
        url = state.get("url") or state.get("tabUrl") or ""

        track_id = f"/org/mpris/MediaPlayer2/tab/{self._tab_id}"

        new_metadata = {
            "mpris:trackid": Variant("o", track_id),
            "xesam:title": Variant("s", title),
            "xesam:url": Variant("s", url),
        }
        if artist:
            new_metadata["xesam:artist"] = Variant("as", [artist])
        if art_url:
            new_metadata["mpris:artUrl"] = Variant("s", art_url)
        if self._duration > 0:
            new_metadata["mpris:length"] = Variant("x", self._duration)

        if new_metadata != self._metadata:
            self._metadata = new_metadata
            changed_props["Metadata"] = new_metadata

        return changed_props


# ---------------------------------------------------------------------------
# Per-tab player — each gets its OWN bus connection to avoid path conflicts
# ---------------------------------------------------------------------------

class TabPlayer:
    """Wraps a pair of MPRIS interfaces for one tab on its own bus connection."""

    def __init__(self, tab_id: int, send_command_fn):
        self.tab_id = tab_id
        self.bus: Optional[MessageBus] = None
        self.bus_name = f"org.mpris.MediaPlayer2.firefox_tab_{tab_id}"

        identity = f"Firefox Tab {tab_id}"
        self.root_iface = MediaPlayer2Interface(identity)
        self.player_iface = PlayerInterface(tab_id, send_command_fn)

    async def register(self):
        """Connect to session bus, export interfaces, request name."""
        self.bus = await MessageBus(bus_type=BusType.SESSION).connect()
        self.bus.export(MPRIS_PATH, self.root_iface)
        self.bus.export(MPRIS_PATH, self.player_iface)
        await self.bus.request_name(self.bus_name)
        log.info("Registered MPRIS player: %s", self.bus_name)

    async def unregister(self):
        """Release bus name and disconnect."""
        try:
            if self.bus:
                self.bus.unexport(MPRIS_PATH, self.root_iface)
                self.bus.unexport(MPRIS_PATH, self.player_iface)
                await self.bus.release_name(self.bus_name)
                self.bus.disconnect()
            log.info("Unregistered MPRIS player: %s", self.bus_name)
        except Exception as e:
            log.warning("Error unregistering %s: %s", self.bus_name, e)

    def update(self, state: dict):
        """Update player state and emit PropertiesChanged."""
        changed = self.player_iface.update_state(state)
        if changed:
            try:
                self.player_iface.emit_properties_changed(changed)
            except Exception as e:
                log.warning("Error emitting PropertiesChanged: %s", e)


# ---------------------------------------------------------------------------
# Native Messaging I/O — thread-based stdin reader
# ---------------------------------------------------------------------------

def read_native_messages_thread(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    """Read native messaging messages from stdin in a thread.
    Puts parsed dicts into the asyncio queue."""
    try:
        while True:
            raw_len = sys.stdin.buffer.read(4)
            if not raw_len or len(raw_len) < 4:
                loop.call_soon_threadsafe(queue.put_nowait, None)
                return

            msg_len = struct.unpack("<I", raw_len)[0]

            if msg_len > 10 * 1024 * 1024:
                log.error("Message too large: %d bytes", msg_len)
                loop.call_soon_threadsafe(queue.put_nowait, None)
                return

            raw_msg = sys.stdin.buffer.read(msg_len)
            if not raw_msg or len(raw_msg) < msg_len:
                loop.call_soon_threadsafe(queue.put_nowait, None)
                return

            msg = json.loads(raw_msg.decode("utf-8"))
            loop.call_soon_threadsafe(queue.put_nowait, msg)

    except Exception as e:
        log.error("Stdin reader thread error: %s", e)
        loop.call_soon_threadsafe(queue.put_nowait, None)


def write_native_message(msg: dict):
    """Write a single native messaging message to stdout."""
    encoded = json.dumps(msg).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


# ---------------------------------------------------------------------------
# Main host
# ---------------------------------------------------------------------------

class MprisHost:
    def __init__(self):
        self.players: dict[int, TabPlayer] = {}
        self.running = True

    def send_command(self, tab_id: int, action: str, **kwargs):
        """Send a command back to the extension."""
        msg = {"type": "command", "tabId": tab_id, "action": action}
        msg.update(kwargs)
        try:
            write_native_message(msg)
        except Exception as e:
            log.error("Error writing command: %s", e)

    async def handle_message(self, msg: dict):
        """Process a message from the extension."""
        msg_type = msg.get("type")

        if msg_type == "tabState":
            tab_id = msg.get("tabId")
            if tab_id is None:
                return

            if tab_id not in self.players:
                player = TabPlayer(tab_id, self.send_command)
                await player.register()
                self.players[tab_id] = player
                log.info("New tab player: %d (total: %d)", tab_id, len(self.players))

            self.players[tab_id].update(msg)

        elif msg_type == "tabRemoved":
            tab_id = msg.get("tabId")
            if tab_id and tab_id in self.players:
                await self.players[tab_id].unregister()
                del self.players[tab_id]
                log.info("Removed tab player: %d (total: %d)", tab_id, len(self.players))

    async def run(self):
        """Main loop."""
        log.info("Starting MPRIS host")

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        reader_thread = threading.Thread(
            target=read_native_messages_thread,
            args=(queue, loop),
            daemon=True,
        )
        reader_thread.start()

        try:
            while self.running:
                msg = await queue.get()
                if msg is None:
                    break
                try:
                    await self.handle_message(msg)
                except Exception as e:
                    log.error("Error processing message: %s", e, exc_info=True)
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Remove all MPRIS players and disconnect."""
        log.info("Cleaning up %d players", len(self.players))
        for player in list(self.players.values()):
            await player.unregister()
        self.players.clear()
        log.info("MPRIS host shut down")


def main():
    host = MprisHost()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: setattr(host, "running", False))

    try:
        loop.run_until_complete(host.run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
