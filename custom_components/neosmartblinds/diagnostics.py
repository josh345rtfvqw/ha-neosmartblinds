"""Diagnostics for Neo Smart Blinds."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import NeoConfigEntry
from .const import CONF_HOST, CONF_HUB_ID

TO_REDACT = {CONF_HOST, CONF_HUB_ID}


def _scrub(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "**REDACTED**")
        return value
    if isinstance(value, dict):
        return {key: _scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, secrets) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NeoConfigEntry
) -> dict[str, Any]:
    """Return blind settings, connection status and recent commands."""
    hub = entry.runtime_data
    secrets = [s for s in (entry.data.get(CONF_HOST), entry.data.get(CONF_HUB_ID)) if s]
    data = {
        "entry": {
            "title": "Neo Smart Controller",
            "version": f"{entry.version}.{entry.minor_version}",
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "blinds": [
            {
                "title": subentry.title,
                "subentry_type": subentry.subentry_type,
                "unique_id": subentry.unique_id,
                "data": dict(subentry.data),
            }
            for subentry in entry.subentries.values()
        ],
        "controller": hub.diagnostics(),
    }
    return _scrub(data, secrets)
