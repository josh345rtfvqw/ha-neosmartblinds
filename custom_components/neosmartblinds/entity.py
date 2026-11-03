"""Shared entity helpers."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, NAME
from .hub import NeoHub, Room
from .settings import BlindSettings

MANUFACTURER = NAME


def controller_device_info(hub: NeoHub) -> DeviceInfo:
    """Return device info for the controller."""
    return DeviceInfo(
        identifiers={(DOMAIN, hub.device_identifier)},
        name=hub.entry.title,
        manufacturer=MANUFACTURER,
        model="Neo Smart Controller",
    )


def blind_device_info(hub: NeoHub, blind: BlindSettings) -> DeviceInfo:
    """Return device info for a blind."""
    return DeviceInfo(
        identifiers={(DOMAIN, blind.unique_id)},
        name=blind.name,
        manufacturer=MANUFACTURER,
        model=blind.model,
        via_device=(DOMAIN, hub.device_identifier),
    )


def room_device_info(hub: NeoHub, room: Room) -> DeviceInfo:
    """Return device info for a room."""
    return DeviceInfo(
        identifiers={(DOMAIN, room.unique_id)},
        name=room.name,
        manufacturer=MANUFACTURER,
        model="Room",
        via_device=(DOMAIN, hub.device_identifier),
    )
