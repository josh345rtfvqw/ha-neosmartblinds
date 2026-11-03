"""Blind and room covers for Neo Smart Blinds."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.cover import (
    ATTR_POSITION,
    PLATFORM_SCHEMA as COVER_PLATFORM_SCHEMA,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_CLOSED, STATE_OPEN
from homeassistant.core import CALLBACK_TYPE, CoreState, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_platform,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from . import NeoConfigEntry
from .codes import build_command, normalise_action
from .const import (
    ATTR_COMMAND,
    CONF_BLIND_CODE,
    CONF_CLOSE_TIME,
    CONF_HOST,
    CONF_HUB_ID,
    CONF_MOTOR_CODE,
    CONF_NAME,
    CONF_PARENT_GROUP,
    CONF_PERCENT_SUPPORT,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_RAIL,
    CONF_START_POSITION,
    DEFAULT_POSITION,
    DOMAIN,
    MODE_MOTOR_POSITION,
    POSITION_CLOSE_BELOW,
    POSITION_OPEN_ABOVE,
    SERVICE_SEND_COMMAND,
    SUBENTRY_BLIND,
    SYNC_CLOSE,
    SYNC_NONE,
    SYNC_OPEN,
)
from .entity import blind_device_info, room_device_info
from .hub import NeoHub, Room
from .settings import BlindSettings
from .yaml_import import async_import_yaml_blind

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

OPEN = 1
CLOSE = -1

# Old YAML set-up. Values are checked during import so a bad entry becomes a
# repair issue instead of a config error.
PLATFORM_SCHEMA = COVER_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_BLIND_CODE): cv.string,
        vol.Optional(CONF_CLOSE_TIME): vol.Any(cv.positive_float, cv.string),
        vol.Optional(CONF_HUB_ID): cv.string,
        vol.Optional(CONF_PROTOCOL): cv.string,
        vol.Optional(CONF_PORT): vol.Any(cv.port, cv.string),
        vol.Optional(CONF_RAIL): vol.Any(int, cv.string),
        vol.Optional(CONF_PERCENT_SUPPORT): vol.Any(int, cv.string),
        vol.Optional(CONF_MOTOR_CODE): vol.Any(cv.string, None),
        vol.Optional(CONF_START_POSITION): vol.Any(int, float, cv.string),
        vol.Optional(CONF_PARENT_GROUP): vol.Any(cv.string, None),
    },
    extra=vol.ALLOW_EXTRA,
)

SEND_COMMAND_SCHEMA: dict[Any, Any] = {vol.Required(ATTR_COMMAND): cv.string}


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: Any,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Import a blind from old YAML. Creates no entities itself."""
    await async_import_yaml_blind(hass, config)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up blind and room covers for a controller."""
    hub = entry.runtime_data
    blinds: dict[str, NeoBlindCover] = {}
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_BLIND:
            continue
        settings = BlindSettings.from_subentry(subentry)
        cover = NeoBlindCover(hub, settings)
        blinds[settings.unique_id] = cover
        async_add_entities([cover], config_subentry_id=subentry.subentry_id)

    blind_codes = {blind.blind_code for blind in hub.blinds}
    rooms = [
        NeoRoomCover(hub, room, [blinds[member.unique_id] for member in room.members])
        for room in hub.rooms.values()
        if room.code not in blind_codes
    ]
    if rooms:
        async_add_entities(rooms)
    _remove_stale_room_devices(hass, entry, {room.room.unique_id for room in rooms})

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEND_COMMAND, SEND_COMMAND_SCHEMA, "async_send_raw_command"
    )


def _remove_stale_room_devices(
    hass: HomeAssistant, entry: NeoConfigEntry, keep: set[str]
) -> None:
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier.endswith(".room") and identifier not in keep:
                registry.async_update_device(
                    device.id, remove_config_entry_id=entry.entry_id
                )


def _raw_action(command: str) -> str:
    action = normalise_action(command)
    if action is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="invalid_raw_command",
            translation_placeholders={"command": str(command)},
        )
    return action


@dataclass
class _StoredBlind(ExtraStoredData):
    """What a blind remembers across restarts."""

    position: float | None
    closed: bool | None

    def as_dict(self) -> dict[str, Any]:
        """Return a dict for storage."""
        return {"position": self.position, "closed": self.closed}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _StoredBlind:
        """Read stored data."""
        return cls(data.get("position"), data.get("closed"))


class NeoBlindCover(CoverEntity, RestoreEntity):
    """One blind (one rail of one blind code)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_assumed_state = True
    _attr_should_poll = False

    def __init__(self, hub: NeoHub, settings: BlindSettings) -> None:
        """Set up the cover from blind settings."""
        self._hub = hub
        self.settings = settings
        self._attr_unique_id = settings.unique_id
        self._attr_device_info = blind_device_info(hub, settings)
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if settings.has_position:
            features |= CoverEntityFeature.SET_POSITION
        if settings.has_tilt:
            features |= CoverEntityFeature.OPEN_TILT | CoverEntityFeature.CLOSE_TILT
        self._attr_supported_features = features

        self._position: float | None = None
        self._closed: bool | None = None
        # Movement: direction, where it started, when, and where it will stop.
        self._direction = 0
        self._origin = 0.0
        self._started = 0.0
        self._target: float | None = None
        self._unsub_finish: CALLBACK_TYPE | None = None
        self._unsub_tick: CALLBACK_TYPE | None = None
        self._listeners: list[CALLBACK_TYPE] = []

    # State --------------------------------------------------------------

    @property
    def current_cover_position(self) -> int | None:
        """Return the estimated position, percent open."""
        if not self.settings.has_position:
            return None
        return round(self._estimate())

    @property
    def is_closed(self) -> bool | None:
        """Return True when the blind is (believed to be) closed."""
        if not self.settings.has_position:
            return self._closed
        return self.current_cover_position == 0

    @property
    def is_opening(self) -> bool:
        """Return True while moving up."""
        return self._direction == OPEN

    @property
    def is_closing(self) -> bool:
        """Return True while moving down."""
        return self._direction == CLOSE

    @property
    def extra_restore_state_data(self) -> _StoredBlind:
        """Return what to remember across restarts."""
        position = self._estimate() if self.settings.has_position else None
        return _StoredBlind(position, self._closed)

    @callback
    def async_add_room_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call listener after this blind's state is written."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    @callback
    def _update(self) -> None:
        if self.hass is None or self.platform is None:
            return
        self.async_write_ha_state()
        for listener in list(self._listeners):
            listener()

    async def async_added_to_hass(self) -> None:
        """Restore the last position and handle the startup re-sync."""
        await super().async_added_to_hass()
        await self._async_restore()
        self._apply_imported_area()

        if self.settings.startup_sync != SYNC_NONE:
            if self.hass.state is CoreState.running:
                _LOGGER.debug("Skipping re-sync for %s on reload", self.entity_id)
            else:
                self.async_on_remove(
                    self.hass.bus.async_listen_once(
                        EVENT_HOMEASSISTANT_STARTED, self._async_startup_sync
                    )
                )

    async def async_will_remove_from_hass(self) -> None:
        """Freeze any movement so the saved position is the estimate."""
        if self._direction:
            self._position = self._estimate()
        self._cancel_timers()
        self._direction = 0

    async def _async_restore(self) -> None:
        stored = await self.async_get_last_extra_data()
        data = _StoredBlind.from_dict(stored.as_dict()) if stored else None
        last_state = await self.async_get_last_state()
        position_override = self.hass.data.get(DOMAIN, {}).get("positions", {}).pop(
            self.settings.unique_id, None
        )

        if self.settings.has_position:
            position: float | None = position_override
            if position is None and data is not None:
                position = data.position
            if position is None and last_state is not None:
                position = last_state.attributes.get("current_position")
            if position is None:
                position = self.settings.start_position
            if position is None:
                position = DEFAULT_POSITION
            self._position = max(0.0, min(100.0, float(position)))
            return

        if position_override is not None:
            self._closed = position_override == 0
        elif data is not None and data.closed is not None:
            self._closed = data.closed
        elif last_state is not None and last_state.state in (STATE_OPEN, STATE_CLOSED):
            self._closed = last_state.state == STATE_CLOSED

    @callback
    def _apply_imported_area(self) -> None:
        areas = self.hass.data.get(DOMAIN, {}).get("areas", {})
        area_id = areas.pop(self.settings.unique_id, None)
        if not area_id or self.registry_entry is None or not self.registry_entry.device_id:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get(self.registry_entry.device_id)
        if device is not None and device.area_id is None:
            registry.async_update_device(device.id, area_id=area_id)

    async def _async_startup_sync(self, _event: Event) -> None:
        try:
            if self.settings.startup_sync == SYNC_OPEN:
                await self.async_open_cover()
            elif self.settings.startup_sync == SYNC_CLOSE:
                await self.async_close_cover()
        except HomeAssistantError as err:
            _LOGGER.warning("Startup re-sync of %s failed: %s", self.entity_id, err)

    # Movement model ------------------------------------------------------

    def _travel_time(self, direction: int) -> float:
        return self.settings.open_time if direction == OPEN else self.settings.close_time

    def _estimate(self) -> float:
        """Return the estimated position now, percent open."""
        if self._position is None:
            return float(DEFAULT_POSITION)
        if not self._direction:
            return self._position
        elapsed = dt_util.utcnow().timestamp() - self._started
        moved = elapsed / self._travel_time(self._direction) * 100
        position = self._origin + self._direction * moved
        end = self._end_point()
        if self._direction == OPEN:
            position = min(position, end)
        else:
            position = max(position, end)
        return max(0.0, min(100.0, position))

    def _end_point(self) -> float:
        if self._target is not None:
            return self._target
        return 100.0 if self._direction == OPEN else 0.0

    def _cancel_timers(self) -> None:
        if self._unsub_finish is not None:
            self._unsub_finish()
            self._unsub_finish = None
        if self._unsub_tick is not None:
            self._unsub_tick()
            self._unsub_tick = None

    @callback
    def _freeze(self, position: float | None = None) -> None:
        """Stop tracking movement and hold the position."""
        self._position = self._estimate() if position is None else position
        self._direction = 0
        self._target = None
        self._cancel_timers()

    @callback
    def _begin_move(self, direction: int, target: float | None) -> None:
        """Start tracking a move from the current estimate."""
        origin = self._estimate()
        self._cancel_timers()
        self._origin = origin
        self._position = origin
        self._started = dt_util.utcnow().timestamp()
        self._direction = direction
        self._target = target
        self._schedule_finish()
        self._unsub_tick = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=1)
        )

    @callback
    def _retarget(self, target: float | None) -> None:
        """Change where the current move ends, without stopping."""
        self._target = target
        if self._unsub_finish is not None:
            self._unsub_finish()
            self._unsub_finish = None
        self._schedule_finish()

    @callback
    def _schedule_finish(self) -> None:
        end = self._end_point()
        distance = abs(end - self._origin)
        total = distance / 100 * self._travel_time(self._direction)
        elapsed = dt_util.utcnow().timestamp() - self._started
        self._unsub_finish = async_call_later(
            self.hass, max(0.0, total - elapsed), self._async_finish
        )

    @callback
    def _tick(self, _now: Any) -> None:
        self._update()

    async def _async_finish(self, _now: Any) -> None:
        """The move time has passed."""
        self._unsub_finish = None
        target = self._target
        direction = self._direction
        end = self._end_point()
        self._freeze(end)
        self._update()
        if (
            target is not None
            and direction
            and self.settings.mode != MODE_MOTOR_POSITION
        ):
            # Timed mode: stop the blind at the target.
            try:
                await self._send(self.settings.actions.stop)
            except HomeAssistantError as err:
                _LOGGER.warning("Stopping %s failed: %s", self.entity_id, err)

    # Commands ------------------------------------------------------------

    async def _send(self, action: str) -> None:
        await self._hub.async_send_action(self.settings, action)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the blind fully."""
        if not self.settings.has_position:
            await self._send(self.settings.actions.open)
            self._closed = False
            self._update()
            return
        await self._async_move_to_end(OPEN)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the blind fully."""
        if not self.settings.has_position:
            await self._send(self.settings.actions.close)
            self._closed = True
            self._update()
            return
        await self._async_move_to_end(CLOSE)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the blind."""
        await self._send(self.settings.actions.stop)
        if self._direction:
            self._freeze()
        self._update()

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Micro-step up."""
        if self.settings.actions.tilt_open:
            await self._send(self.settings.actions.tilt_open)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Micro-step down."""
        if self.settings.actions.tilt_close:
            await self._send(self.settings.actions.tilt_close)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move to a position (percent open)."""
        if not self.settings.has_position:
            return
        target = float(kwargs[ATTR_POSITION])
        if target > POSITION_OPEN_ABOVE:
            await self._async_move_to_end(OPEN)
            return
        if target < POSITION_CLOSE_BELOW:
            await self._async_move_to_end(CLOSE)
            return

        current = self._estimate()
        direction = OPEN if target > current else CLOSE if target < current else 0
        moving = self._direction

        if self.settings.mode == MODE_MOTOR_POSITION:
            if moving and direction and direction != moving:
                await self._send(self.settings.actions.stop)
                self._freeze()
            await self._send(f"{100 - round(target):02d}")
            if direction:
                self._begin_move(direction, target)
            else:
                self._freeze(target)
            self._update()
            return

        # Timed mode.
        if moving:
            if direction == moving:
                self._retarget(target)
                self._update()
                return
            await self._send(self.settings.actions.stop)
            self._freeze()
            current = self._estimate()
            direction = OPEN if target > current else CLOSE if target < current else 0
        if not direction:
            self._update()
            return
        await self._send(self._direction_action(direction))
        self._begin_move(direction, target)
        self._update()

    def _direction_action(self, direction: int) -> str:
        actions = self.settings.actions
        return actions.open if direction == OPEN else actions.close

    async def _async_move_to_end(self, direction: int) -> None:
        """Send a plain open or close with no stop, so the motor hits its end stop."""
        moving = self._direction
        if moving and moving != direction:
            await self._send(self.settings.actions.stop)
            self._freeze()
        elif moving == direction and self.settings.mode != MODE_MOTOR_POSITION:
            # Already heading that way: just stop no longer.
            self._retarget(None)
            self._update()
            return
        await self._send(self._direction_action(direction))
        self._begin_move(direction, None)
        self._update()

    async def async_press_favourite(self, action: str) -> None:
        """Send a favourite position. The estimate is left alone."""
        await self._send(action)

    async def async_send_raw_command(self, command: str) -> None:
        """Send any two-character action to this blind."""
        action = _raw_action(command)
        await self._hub.async_send(
            build_command(self.settings.blind_code, action, self.settings.motor_code),
            key=self.settings.unique_id,
            name=self.settings.name,
        )


class NeoRoomCover(CoverEntity):
    """All blinds sharing a room code, moved together."""

    _attr_has_entity_name = True
    _attr_translation_key = "room"
    _attr_assumed_state = True
    _attr_should_poll = False

    def __init__(self, hub: NeoHub, room: Room, members: list[NeoBlindCover]) -> None:
        """Set up the room cover."""
        self._hub = hub
        self.room = room
        self._members = members
        self._attr_unique_id = room.unique_id
        self._attr_device_info = room_device_info(hub, room)
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if all(member.settings.has_position for member in members):
            features |= CoverEntityFeature.SET_POSITION
        self._attr_supported_features = features

    async def async_added_to_hass(self) -> None:
        """Follow the member blinds."""
        for member in self._members:
            self.async_on_remove(member.async_add_room_listener(self._member_changed))

    @callback
    def _member_changed(self) -> None:
        self.async_write_ha_state()

    @property
    def current_cover_position(self) -> int | None:
        """Return the average position of the blinds that have one."""
        positions = [
            member.current_cover_position
            for member in self._members
            if member.current_cover_position is not None
        ]
        if not positions:
            return None
        return round(sum(positions) / len(positions))

    @property
    def is_closed(self) -> bool | None:
        """Return True when every blind is closed."""
        states = [member.is_closed for member in self._members]
        if any(state is None for state in states):
            return None
        return all(states)

    @property
    def is_opening(self) -> bool:
        """Return True while any blind is opening."""
        return any(member.is_opening for member in self._members)

    @property
    def is_closing(self) -> bool:
        """Return True while any blind is closing."""
        return any(member.is_closing for member in self._members)

    async def _async_all(self, calls: list[Any]) -> None:
        results = await asyncio.gather(*calls, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open every blind in the room."""
        await self._async_all([member.async_open_cover() for member in self._members])

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close every blind in the room."""
        await self._async_all([member.async_close_cover() for member in self._members])

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop every blind in the room."""
        await self._async_all([member.async_stop_cover() for member in self._members])

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move every blind in the room to a position."""
        position = kwargs[ATTR_POSITION]
        await self._async_all(
            [
                member.async_set_cover_position(position=position)
                for member in self._members
                if member.settings.has_position
            ]
        )

    async def async_send_raw_command(self, command: str) -> None:
        """Send any two-character action to the room code."""
        action = _raw_action(command)
        motor_codes = list(dict.fromkeys(m.settings.motor_code for m in self._members))
        for motor_code in motor_codes:
            await self._hub.async_send(
                build_command(self.room.code, action, motor_code),
                key=self.room.unique_id,
                name=self.room.label,
            )
