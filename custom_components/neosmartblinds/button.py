"""Favourite position buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NeoConfigEntry
from .const import ACTION_FAVOURITE_1, ACTION_FAVOURITE_2, SUBENTRY_BLIND
from .entity import blind_device_info
from .hub import NeoHub
from .settings import BlindSettings

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add favourite buttons for each blind."""
    hub = entry.runtime_data
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_BLIND:
            continue
        settings = BlindSettings.from_subentry(subentry)
        buttons = [NeoFavouriteButton(hub, settings, 1, ACTION_FAVOURITE_1)]
        if settings.has_favourite_2:
            buttons.append(NeoFavouriteButton(hub, settings, 2, ACTION_FAVOURITE_2))
        async_add_entities(buttons, config_subentry_id=subentry.subentry_id)


class NeoFavouriteButton(ButtonEntity):
    """Sends a favourite position. Off by default: the controller can't say if one is saved."""

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False
    _attr_should_poll = False

    def __init__(self, hub: NeoHub, settings: BlindSettings, number: int, action: str) -> None:
        """Set up the button."""
        self._hub = hub
        self._settings = settings
        self._action = action
        self._attr_translation_key = f"favourite_{number}"
        self._attr_unique_id = f"{settings.unique_id}.favourite_{number}"
        self._attr_device_info = blind_device_info(hub, settings)

    async def async_press(self) -> None:
        """Send the favourite. The cover's estimated position is not changed."""
        await self._hub.async_send_action(self._settings, self._action)

