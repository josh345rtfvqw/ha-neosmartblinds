"""Importing blinds from the old `cover: - platform: neosmartblinds` YAML."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util import slugify

from .const import (
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
    CONF_STARTUP_SYNC,
    CONF_TDBU_EXTENDED,
    CONF_TILT,
    DEFAULT_CLOSE_TIME,
    DEFAULT_PORTS,
    DOMAIN,
    ISSUE_DEPRECATED_YAML,
    MODE_OPEN_CLOSE,
    PROTOCOL_HTTP,

    RAIL_TOP,
    SYNC_NONE,
)
from .settings import BlindValidationError, unique_id_for, validate_blind
from .validation import ControllerValidationError, validate_controller

_LOGGER = logging.getLogger(__name__)

IMPORT_LOCK = "import_lock"

REASONS = {
    "invalid_blind_code": "the blind code must look like 021.230-04 (IDs 000 to 255, channel 00 to 15)",
    "invalid_motor_code": "the motor code must be two letters or digits",
    "invalid_rail": "rail must be 1, 2 or 3",
    "invalid_mode": "percent_support must be 0, 1 or 2",
    "position_not_supported": "percent_support 1 needs the top rail and a motor code that accepts positions",
    "extended_not_supported": "the extended top-down/bottom-up commands need motor code mb, ra, ap or db",
    "invalid_time": "close_time must be a positive number of seconds",
    "invalid_start_position": "start_position must be between 0 and 100",
    "invalid_room_code": "parent_group must be a room code ending in -15",
    "invalid_sync": "invalid re-sync option",
    "invalid_host": "host is missing",
    "invalid_protocol": "protocol must be http or tcp",
    "invalid_port": "port must be a number from 1 to 65535",
    "hub_id_required": "hub_id is required for HTTP",
    "invalid_hub_id": "hub_id must be the 24 character controller ID",
}


def parse_yaml_blind(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (controller data, blind subentry data) from one YAML entry."""
    protocol = str(config.get(CONF_PROTOCOL) or PROTOCOL_HTTP).strip().lower()
    controller = validate_controller(
        {
            CONF_HOST: config.get(CONF_HOST, ""),
            CONF_PROTOCOL: protocol,
            CONF_PORT: config.get(CONF_PORT)
            or DEFAULT_PORTS.get(protocol, DEFAULT_PORTS[PROTOCOL_HTTP]),
            CONF_HUB_ID: config.get(CONF_HUB_ID) or "",
        }
    )
    blind = validate_blind(
        {
            CONF_BLIND_CODE: config.get(CONF_BLIND_CODE, ""),
            CONF_MOTOR_CODE: config.get(CONF_MOTOR_CODE) or "",
            CONF_RAIL: config.get(CONF_RAIL, RAIL_TOP),
            CONF_TDBU_EXTENDED: False,
            CONF_TILT: False,
            CONF_PERCENT_SUPPORT: config.get(CONF_PERCENT_SUPPORT, MODE_OPEN_CLOSE),
            CONF_CLOSE_TIME: config.get(CONF_CLOSE_TIME, DEFAULT_CLOSE_TIME),
            CONF_STARTUP_SYNC: SYNC_NONE,
            CONF_START_POSITION: config.get(CONF_START_POSITION),
            CONF_PARENT_GROUP: config.get(CONF_PARENT_GROUP) or "",
        }
    )
    return controller, blind


async def async_import_yaml_blind(hass: HomeAssistant, config: dict[str, Any]) -> None:
    """Import one YAML blind into a controller entry."""
    data = hass.data.setdefault(DOMAIN, {})
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_DEPRECATED_YAML,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_DEPRECATED_YAML,
        translation_placeholders={"domain": DOMAIN},
    )

    name = str(config.get(CONF_NAME) or config.get(CONF_BLIND_CODE) or "unnamed")
    issue_id = f"yaml_import_failed_{slugify(name)}"
    try:
        controller, blind = parse_yaml_blind(config)
    except (BlindValidationError, ControllerValidationError) as err:
        _LOGGER.warning("Could not import YAML blind %s: %s", name, err.error)
        _create_failed_issue(hass, issue_id, name, REASONS.get(err.error, err.error))
        return

    unique_id = unique_id_for(blind)
    entity_id = er.async_get(hass).async_get_entity_id("cover", DOMAIN, unique_id)
    if entity_id is not None:
        entity = er.async_get(hass).async_get(entity_id)
        if entity is not None and entity.config_entry_id is None and entity.area_id:
            data.setdefault("areas", {})[unique_id] = entity.area_id

    lock: asyncio.Lock = data.setdefault(IMPORT_LOCK, asyncio.Lock())
    async with lock:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={"controller": controller, "blinds": [{"title": name, "data": blind}]},
        )
    if result["type"] is FlowResultType.ABORT and result["reason"] not in (
        "already_configured",
        "single_instance_allowed",
    ):
        _create_failed_issue(hass, issue_id, name, str(result["reason"]))
        return
    ir.async_delete_issue(hass, DOMAIN, issue_id)


def _create_failed_issue(hass: HomeAssistant, issue_id: str, name: str, reason: str) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="yaml_import_failed",
        translation_placeholders={"name": name, "reason": reason},
    )



