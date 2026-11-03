"""Blind codes, motor codes and the actions each blind uses."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .const import (
    EXTENDED_MOTORS,
    MODE_MOTOR_POSITION,
    POSITION_MOTORS,
    RAIL_BOTH,
    RAIL_BOTTOM,
    RAIL_TOP,
    ROOM_CHANNEL,
)

_BLIND_CODE = re.compile(r"^(\d{3})\.(\d{3})-(\d{2})$")
_MOTOR_CODE = re.compile(r"^[a-z0-9]{2}$")
_ACTION = re.compile(r"^[a-z0-9]{2}$")


def normalise_blind_code(value: str) -> str | None:
    """Return the blind code in canonical form, or None when it is invalid."""
    code = str(value).strip().lower()
    match = _BLIND_CODE.match(code)
    if not match:
        return None
    id1, id2, channel = (int(part) for part in match.groups())
    if id1 > 255 or id2 > 255 or channel > 15:
        return None
    return code


def normalise_room_code(value: str) -> str | None:
    """Return the room code in canonical form, or None when it is invalid."""
    code = normalise_blind_code(value)
    if code is None or not code.endswith(f"-{ROOM_CHANNEL}"):
        return None
    return code


def normalise_motor_code(value: str | None) -> str | None:
    """Return the motor code lower-cased, "" for none, or None when invalid."""
    code = str(value or "").strip().lower()
    if not code:
        return ""
    # Values picked from the dropdown may arrive as "bf – Bofu (standard)".
    code = code.split(" ", 1)[0]
    if not _MOTOR_CODE.match(code):
        return None
    return code


def normalise_action(value: str) -> str | None:
    """Return a two-character action lower-cased, or None when invalid."""
    action = str(value).strip().lower()
    return action if _ACTION.match(action) else None


def build_command(code: str, action: str, motor_code: str) -> str:
    """Build a controller command from a blind or room code."""
    command = f"{code}-{action}"
    if motor_code:
        command = f"{command}!{motor_code}"
    return command


def blind_unique_id(blind_code: str, motor_code: str, rail: int) -> str:
    """Return the unique ID shared by a blind subentry and its cover."""
    return f"neosmartblinds.{blind_code}.{motor_code}.{rail}"


def room_unique_id(room_code: str) -> str:
    """Return the unique ID of a room cover and its device."""
    return f"neosmartblinds.{room_code}.room"


def room_code_of(blind_code: str) -> str:
    """Return the room code (channel 15) for the IDs of a blind code."""
    return f"{blind_code[:7]}-{ROOM_CHANNEL}"


@dataclass(frozen=True, slots=True)
class ActionSet:
    """The actions a blind uses for one rail."""

    open: str
    close: str
    stop: str
    tilt_open: str | None
    tilt_close: str | None

    @property
    def has_tilt(self) -> bool:
        """Return True when the rail has tilt (micro-step) actions."""
        return self.tilt_open is not None and self.tilt_close is not None


_STANDARD = {
    RAIL_TOP: ActionSet("up", "dn", "sp", "mu", "md"),
    RAIL_BOTTOM: ActionSet("u2", "d2", "sp", "o2", "c2"),
    RAIL_BOTH: ActionSet("u3", "d3", "sp", None, None),
}
_EXTENDED = {
    RAIL_TOP: ActionSet("u4", "d4", "x2", None, None),
    RAIL_BOTTOM: ActionSet("u2", "d2", "x2", None, None),
    RAIL_BOTH: ActionSet("u3", "d3", "x2", None, None),
}


def action_set(rail: int, extended: bool) -> ActionSet:
    """Return the action set for a rail and command set."""
    return (_EXTENDED if extended else _STANDARD)[rail]


def extended_allowed(motor_code: str) -> bool:
    """Return True when the motor can use the extended command set."""
    return motor_code in EXTENDED_MOTORS


def position_mode_allowed(
    mode: int, rail: int, extended: bool, motor_code: str
) -> bool:
    """Return True when the positioning mode suits the blind."""
    if mode != MODE_MOTOR_POSITION:
        return True
    return (
        rail == RAIL_TOP
        and not extended
        and (motor_code == "" or motor_code in POSITION_MOTORS)
    )
