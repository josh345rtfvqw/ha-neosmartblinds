"""Connection sensor for the controller."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NeoConfigEntry
from .entity import controller_device_info
from .hub import NeoHub

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the connection sensor."""
    async_add_entities([NeoConnectionSensor(entry.runtime_data)])


class NeoConnectionSensor(BinarySensorEntity):
    """On while the controller answers."""

    _attr_has_entity_name = True
    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, hub: NeoHub) -> None:
        """Set up the sensor."""
        self._hub = hub
        self._attr_unique_id = f"{hub.device_identifier}.connection"
        self._attr_device_info = controller_device_info(hub)

    @property
    def is_on(self) -> bool | None:
        """Return True while the controller answers."""
        return self._hub.connected

    async def async_added_to_hass(self) -> None:
        """Follow the hub's connection state."""
        self.async_on_remove(self._hub.async_add_listener(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()
