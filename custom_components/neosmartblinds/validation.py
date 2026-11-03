"""Checking controller settings."""

from __future__ import annotations

import re
from typing import Any

from .const import (
    CONF_HOST,
    CONF_HUB_ID,
    CONF_PORT,
    CONF_PROTOCOL,
    HUB_ID_LENGTH,
    PROTOCOL_HTTP,
    PROTOCOLS,
)

_HUB_ID = re.compile(rf"^[A-Za-z0-9]{{{HUB_ID_LENGTH}}}$")


class ControllerValidationError(Exception):
    """Invalid controller settings. Holds a form field and an error key."""

    def __init__(self, field: str, error: str) -> None:
        """Store the field and error key."""
        super().__init__(f"{field}: {error}")
        self.field = field
        self.error = error


def validate_hub_id(value: Any, protocol: str) -> str:
    """Return the cleaned controller ID, or raise ControllerValidationError."""
    hub_id = str(value or "").strip()
    if not hub_id:
        if protocol == PROTOCOL_HTTP:
            raise ControllerValidationError(CONF_HUB_ID, "hub_id_required")
        return ""
    if not _HUB_ID.match(hub_id):
        raise ControllerValidationError(CONF_HUB_ID, "invalid_hub_id")
    return hub_id


def validate_controller(data: dict[str, Any]) -> dict[str, Any]:
    """Return clean controller entry data, or raise ControllerValidationError."""
    host = str(data.get(CONF_HOST) or "").strip()
    if not host:
        raise ControllerValidationError(CONF_HOST, "invalid_host")
    protocol = str(data.get(CONF_PROTOCOL) or "").strip().lower()
    if protocol not in PROTOCOLS:
        raise ControllerValidationError(CONF_PROTOCOL, "invalid_protocol")
    try:
        port = int(data.get(CONF_PORT))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ControllerValidationError(CONF_PORT, "invalid_port") from None
    if not 1 <= port <= 65535:
        raise ControllerValidationError(CONF_PORT, "invalid_port")
    hub_id = validate_hub_id(data.get(CONF_HUB_ID), protocol)
    return {CONF_HOST: host, CONF_PROTOCOL: protocol, CONF_PORT: port, CONF_HUB_ID: hub_id}
