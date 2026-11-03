"""Runtime state for one controller: the command queue, rooms and notices."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import const
from .api import NeoAuthError, NeoClient, NeoCommandError, NeoConnectionError, NeoError
from .codes import build_command, room_unique_id
from .const import (
    CONF_HOST,
    CONF_ROOM_NAMES,
    DOMAIN,
    HISTORY_LENGTH,
    SUBENTRY_BLIND,
)
from .settings import BlindSettings

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _Pending:
    member: str
    action: str
    motor_code: str
    blind_code: str
    name: str
    future: asyncio.Future[None]


@dataclass(slots=True)
class Room:
    """A room code shared by two or more blinds on one controller."""

    code: str
    name: str
    members: list[BlindSettings] = field(default_factory=list)

    @property
    def unique_id(self) -> str:
        """Return the room's unique ID."""
        return room_unique_id(self.code)

    @property
    def label(self) -> str:
        """Return the name used for the room cover and in notices."""
        return f"{self.name} Blinds"


class RoomBatcher:
    """Collects blind commands for 250 ms and merges them into a room command."""

    def __init__(self, hub: NeoHub, room: Room) -> None:
        """Set up an empty window."""
        self._hub = hub
        self.room = room
        self._members = {blind.unique_id for blind in room.members}
        self._pending: dict[str, _Pending] = {}
        self._timer: asyncio.TimerHandle | None = None

    def submit(self, blind: BlindSettings, action: str) -> asyncio.Future[None]:
        """Queue a command for a blind and return a future for its result."""
        if blind.unique_id in self._pending:
            # A second command for the same blind closes the current window.
            self._flush()
        future: asyncio.Future[None] = self._hub.hass.loop.create_future()
        self._pending[blind.unique_id] = _Pending(
            blind.unique_id, action, blind.motor_code, blind.blind_code, blind.name, future
        )
        if self._timer is None:
            # A plain loop timer: this is a short debounce, not a wall-clock event.
            self._timer = self._hub.hass.loop.call_later(const.ROOM_WINDOW, self._on_timer)
        return future

    @callback
    def _on_timer(self) -> None:
        self._timer = None
        self._flush()

    @callback
    def _flush(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        batch, self._pending = self._pending, {}
        if batch:
            self._hub.entry.async_create_background_task(
                self._hub.hass, self._send(batch), f"{DOMAIN} room {self.room.code}"
            )

    def cancel(self) -> None:
        """Drop anything waiting, for unload."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.cancel()
        self._pending = {}

    async def _send(self, batch: dict[str, _Pending]) -> None:
        try:
            await self._send_batch(batch)
        finally:
            # If the send was cancelled (for example on unload), don't leave callers waiting.
            for item in batch.values():
                if not item.future.done():
                    item.future.cancel()

    async def _send_batch(self, batch: dict[str, _Pending]) -> None:
        commands = {(item.action, item.motor_code) for item in batch.values()}
        if set(batch) == self._members and len(commands) == 1:
            action, motor_code = next(iter(commands))
            try:
                await self._hub.async_send(
                    build_command(self.room.code, action, motor_code),
                    key=self.room.unique_id,
                    name=self.room.label,
                )
            except HomeAssistantError as err:
                for item in batch.values():
                    _set_exception(item.future, err)
                return
            for item in batch.values():
                _set_result(item.future)
            return
        for item in batch.values():
            try:
                await self._hub.async_send(
                    build_command(item.blind_code, item.action, item.motor_code),
                    key=item.member,
                    name=item.name,
                )
            except HomeAssistantError as err:
                _set_exception(item.future, err)
            else:
                _set_result(item.future)


def _set_result(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


def _set_exception(future: asyncio.Future[None], err: Exception) -> None:
    if not future.done():
        future.set_exception(err)


def find_rooms(
    blinds: list[BlindSettings], room_names: dict[str, str]
) -> dict[str, Room]:
    """Return the room codes shared by two or more blinds."""
    grouped: dict[str, list[BlindSettings]] = {}
    for blind in blinds:
        if blind.parent_group:
            grouped.setdefault(blind.parent_group, []).append(blind)
    return {
        code: Room(code, room_names.get(code) or f"Room {code}", members)
        for code, members in grouped.items()
        if len(members) >= 2
    }


def rooms_for_entry(entry: ConfigEntry) -> dict[str, Room]:
    """Return the rooms for a controller entry from its subentries."""
    blinds = [
        BlindSettings.from_subentry(subentry)
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_BLIND
    ]
    return find_rooms(blinds, entry.options.get(CONF_ROOM_NAMES, {}))


class NeoHub:
    """One controller: serialises commands, tracks the connection, sends notices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: NeoClient) -> None:
        """Set up the hub from a config entry."""
        self.hass = hass
        self.entry = entry
        self.client = client
        self.connected: bool | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LENGTH)
        self.blinds = [
            BlindSettings.from_subentry(subentry)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_BLIND
        ]
        self.rooms = find_rooms(self.blinds, entry.options.get(CONF_ROOM_NAMES, {}))
        self._batchers = {code: RoomBatcher(self, room) for code, room in self.rooms.items()}
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0
        self._listeners: list[Callable[[], None]] = []
        self._unsub_interval: CALLBACK_TYPE | None = None

    @property
    def device_identifier(self) -> str:
        """Return the identifier used for the controller device."""
        return self.entry.unique_id or self.entry.entry_id

    @property
    def host(self) -> str:
        """Return the controller's host."""
        return self.entry.data[CONF_HOST]

    async def async_start(self) -> None:
        """Start the periodic connection check."""
        self._unsub_interval = async_track_time_interval(
            self.hass,
            self._async_interval_check,
            timedelta(seconds=const.CONNECTION_CHECK_INTERVAL),
            cancel_on_shutdown=True,
        )
        self.entry.async_create_background_task(
            self.hass, self.async_check_connection(), f"{DOMAIN} first connection check"
        )

    async def async_stop(self) -> None:
        """Stop timers and drop queued room commands."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        for batcher in self._batchers.values():
            batcher.cancel()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call listener whenever the connection state changes."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    async def _async_interval_check(self, _now: Any) -> None:
        await self.async_check_connection()

    async def async_check_connection(self) -> bool:
        """Check a TCP connection can be opened, without sending a command."""
        async with self._lock:
            try:
                await self.client.async_check()
            except NeoConnectionError as err:
                _LOGGER.debug("Controller %s not answering: %s", self.host, err)
                self._set_connected(False, str(err))
                return False
        self._set_connected(True)
        return True

    @callback
    def _set_connected(self, connected: bool, reason: str = "") -> None:
        notice_id = f"{DOMAIN}_{self.entry.entry_id}_offline"
        if connected:
            persistent_notification.async_dismiss(self.hass, notice_id)
        elif self.connected is not False:
            persistent_notification.async_create(
                self.hass,
                (
                    f"Neo Smart Controller at {self.host} is not answering"
                    f" ({reason}). Check it is powered on and connected to"
                    " the network. This notice clears when it answers again."
                ),
                title="Neo Smart Blinds: controller not answering",
                notification_id=notice_id,
            )
        if connected != self.connected:
            self.connected = connected
            for listener in list(self._listeners):
                listener()

    def _command_notice_id(self, key: str) -> str:
        return f"{DOMAIN}_{self.entry.entry_id}_command_{key}"

    async def async_send(self, command: str, *, key: str, name: str) -> None:
        """Send a command now (after pacing). Raises HomeAssistantError on failure."""
        persistent_notification.async_dismiss(self.hass, self._command_notice_id(key))
        loop = self.hass.loop
        async with self._lock:
            wait = self._next_allowed - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                await self.client.async_send(command)
            except NeoError as err:
                error = err
            else:
                error = None
            finally:
                self._next_allowed = loop.time() + const.COMMAND_SPACING

        self.history.append(
            {
                "time": dt_util.utcnow().isoformat(),
                "target": name,
                "command": command,
                "result": "ok" if error is None else str(error),
            }
        )
        if error is None:
            self._set_connected(True)
            return

        if isinstance(error, NeoAuthError):
            self._set_connected(True)
            self.entry.async_start_reauth(self.hass)
        else:
            if isinstance(error, NeoConnectionError):
                self._set_connected(False, str(error))
            elif isinstance(error, NeoCommandError):
                self._set_connected(True)
            persistent_notification.async_create(
                self.hass,
                (
                    f"Command `{command}` to {name} failed: {error}. This notice"
                    " clears the next time a command is sent to it."
                ),
                title=f"Neo Smart Blinds: command to {name} failed",
                notification_id=self._command_notice_id(key),
            )
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={
                "command": command,
                "name": name,
                "error": str(error),
            },
        ) from error

    async def async_send_action(self, blind: BlindSettings, action: str) -> None:
        """Send an action to a blind, merging into a room command if possible."""
        batcher = self._batchers.get(blind.parent_group) if blind.parent_group else None
        if batcher is None:
            await self.async_send(
                build_command(blind.blind_code, action, blind.motor_code),
                key=blind.unique_id,
                name=blind.name,
            )
            return
        await batcher.submit(blind, action)

    def diagnostics(self) -> dict[str, Any]:
        """Return connection state and recent commands."""
        return {
            "connected": self.connected,
            "protocol": self.client.protocol,
            "port": self.client.port,
            "rooms": {
                code: {"name": room.name, "members": [b.unique_id for b in room.members]}
                for code, room in self.rooms.items()
            },
            "commands": list(self.history),
        }

