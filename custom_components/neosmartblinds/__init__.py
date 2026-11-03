"""The Neo Smart Blinds integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import NeoClient
from .const import (
    CONF_HOST,
    CONF_HUB_ID,
    CONF_PORT,
    CONF_PROTOCOL,
    DEFAULT_PORTS,
    DOMAIN,
    PROTOCOL_HTTP,
)
from .hub import NeoHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.COVER]

CONFIG_SCHEMA = cv.platform_only_config_schema(DOMAIN)

type NeoConfigEntry = ConfigEntry[NeoHub]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up shared data for the integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NeoConfigEntry) -> bool:
    """Set up a controller from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    protocol = entry.data.get(CONF_PROTOCOL, PROTOCOL_HTTP)
    client = NeoClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        int(entry.data.get(CONF_PORT) or DEFAULT_PORTS[protocol]),
        protocol,
        entry.data.get(CONF_HUB_ID) or "",
    )
    hub = NeoHub(hass, entry, client)
    entry.runtime_data = hub

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, hub.device_identifier)},
        name=entry.title,
        manufacturer="Neo Smart Blinds",
        model="Neo Smart Controller",
    )

    await hub.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: NeoConfigEntry) -> None:
    """Reload when options or blinds change."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NeoConfigEntry) -> bool:
    """Unload a controller."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await entry.runtime_data.async_stop()
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring older 1.x entries up to minor version 3."""
    if entry.version > 1:
        return False
    if entry.minor_version < 3:
        data = dict(entry.data)
        protocol = str(data.get(CONF_PROTOCOL) or PROTOCOL_HTTP).lower()
        data[CONF_PROTOCOL] = protocol
        data.setdefault(CONF_PORT, DEFAULT_PORTS.get(protocol, DEFAULT_PORTS[PROTOCOL_HTTP]))
        data.setdefault(CONF_HUB_ID, "")
        hass.config_entries.async_update_entry(entry, data=data, minor_version=3)
        _LOGGER.debug("Migrated %s to version 1.3", entry.title)
    return True
