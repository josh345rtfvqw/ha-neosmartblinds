"""Blind settings: validation and a typed view of a blind subentry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .codes import (
    ActionSet,
    action_set,
    blind_unique_id,
    extended_allowed,
    normalise_blind_code,
    normalise_motor_code,
    normalise_room_code,
    position_mode_allowed,
)
from .const import (
    CONF_BLIND_CODE,
    CONF_CLOSE_TIME,
    CONF_MOTOR_CODE,
    CONF_OPEN_TIME,
    CONF_PARENT_GROUP,
    CONF_PERCENT_SUPPORT,
    CONF_RAIL,
    CONF_START_POSITION,
    CONF_STARTUP_SYNC,
    CONF_TDBU_EXTENDED,
    CONF_TILT,
    DEFAULT_CLOSE_TIME,
    FAVOURITE_2_MOTORS,
    MODE_OPEN_CLOSE,
    MOTOR_NAMES,
    POSITION_MODES,
    RAIL_TOP,
    RAILS,
    SYNC_NONE,
    SYNC_OPTIONS,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigSubentry


class BlindValidationError(Exception):
    """Invalid blind settings. Holds a form field and an error key."""

    def __init__(self, field: str, error: str) -> None:
        """Store the field and error key."""
        super().__init__(f"{field}: {error}")
        self.field = field
        self.error = error


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def validate_blind(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return clean subentry data, or raise BlindValidationError.

    The name is not part of the data (it is the subentry title).
    """
    blind_code = normalise_blind_code(user_input.get(CONF_BLIND_CODE, ""))
    if blind_code is None:
        raise BlindValidationError(CONF_BLIND_CODE, "invalid_blind_code")

    motor_code = normalise_motor_code(user_input.get(CONF_MOTOR_CODE))
    if motor_code is None:
        raise BlindValidationError(CONF_MOTOR_CODE, "invalid_motor_code")

    try:
        rail = int(user_input.get(CONF_RAIL, RAIL_TOP))
    except (TypeError, ValueError):
        rail = -1
    if rail not in RAILS:
        raise BlindValidationError(CONF_RAIL, "invalid_rail")

    extended = bool(user_input.get(CONF_TDBU_EXTENDED, False))
    if extended and not extended_allowed(motor_code):
        raise BlindValidationError(CONF_TDBU_EXTENDED, "extended_not_supported")

    try:
        mode = int(user_input.get(CONF_PERCENT_SUPPORT, MODE_OPEN_CLOSE))
    except (TypeError, ValueError):
        mode = -1
    if mode not in POSITION_MODES:
        raise BlindValidationError(CONF_PERCENT_SUPPORT, "invalid_mode")
    if not position_mode_allowed(mode, rail, extended, motor_code):
        raise BlindValidationError(CONF_PERCENT_SUPPORT, "position_not_supported")

    try:
        close_time = _number(user_input.get(CONF_CLOSE_TIME, DEFAULT_CLOSE_TIME))
        open_time = _number(user_input.get(CONF_OPEN_TIME))
    except (TypeError, ValueError):
        raise BlindValidationError(CONF_CLOSE_TIME, "invalid_time") from None
    if close_time is None or close_time <= 0:
        raise BlindValidationError(CONF_CLOSE_TIME, "invalid_time")
    if open_time is not None and open_time <= 0:
        raise BlindValidationError(CONF_OPEN_TIME, "invalid_time")

    sync = str(user_input.get(CONF_STARTUP_SYNC) or SYNC_NONE).lower()
    if sync not in SYNC_OPTIONS:
        raise BlindValidationError(CONF_STARTUP_SYNC, "invalid_sync")

    try:
        start_position = _number(user_input.get(CONF_START_POSITION))
    except (TypeError, ValueError):
        raise BlindValidationError(CONF_START_POSITION, "invalid_start_position") from None
    if start_position is not None:
        if not 0 <= start_position <= 100:
            raise BlindValidationError(CONF_START_POSITION, "invalid_start_position")
        start_position = int(round(start_position))

    parent_group = str(user_input.get(CONF_PARENT_GROUP) or "").strip()
    if parent_group:
        room_code = normalise_room_code(parent_group)
        if room_code is None:
            raise BlindValidationError(CONF_PARENT_GROUP, "invalid_room_code")
        parent_group = room_code

    return {
        CONF_BLIND_CODE: blind_code,
        CONF_MOTOR_CODE: motor_code,
        CONF_RAIL: rail,
        CONF_TDBU_EXTENDED: extended,
        CONF_TILT: bool(user_input.get(CONF_TILT, False)),
        CONF_PERCENT_SUPPORT: mode,
        CONF_CLOSE_TIME: close_time,
        CONF_OPEN_TIME: open_time,
        CONF_STARTUP_SYNC: sync,
        CONF_START_POSITION: start_position,
        CONF_PARENT_GROUP: parent_group,
    }


def unique_id_for(data: dict[str, Any]) -> str:
    """Return the unique ID for clean subentry data."""
    return blind_unique_id(data[CONF_BLIND_CODE], data[CONF_MOTOR_CODE], data[CONF_RAIL])


@dataclass(frozen=True, slots=True)
class BlindSettings:
    """A blind's settings, read from its subentry."""

    subentry_id: str
    name: str
    blind_code: str
    motor_code: str
    rail: int
    extended: bool
    tilt: bool
    mode: int
    close_time: float
    open_time: float
    startup_sync: str
    start_position: int | None
    parent_group: str

    @classmethod
    def from_data(cls, subentry_id: str, name: str, data: dict[str, Any]) -> BlindSettings:
        """Build settings from subentry data, filling in defaults."""
        close_time = float(data.get(CONF_CLOSE_TIME) or DEFAULT_CLOSE_TIME)
        open_time = data.get(CONF_OPEN_TIME)
        return cls(
            subentry_id=subentry_id,
            name=name,
            blind_code=data[CONF_BLIND_CODE],
            motor_code=data.get(CONF_MOTOR_CODE) or "",
            rail=int(data.get(CONF_RAIL, RAIL_TOP)),
            extended=bool(data.get(CONF_TDBU_EXTENDED, False)),
            tilt=bool(data.get(CONF_TILT, False)),
            mode=int(data.get(CONF_PERCENT_SUPPORT, MODE_OPEN_CLOSE)),
            close_time=close_time,
            open_time=float(open_time) if open_time else close_time,
            startup_sync=data.get(CONF_STARTUP_SYNC) or SYNC_NONE,
            start_position=data.get(CONF_START_POSITION),
            parent_group=data.get(CONF_PARENT_GROUP) or "",
        )

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> BlindSettings:
        """Build settings from a blind subentry."""
        return cls.from_data(subentry.subentry_id, subentry.title, dict(subentry.data))

    @property
    def unique_id(self) -> str:
        """Return the blind's unique ID."""
        return blind_unique_id(self.blind_code, self.motor_code, self.rail)

    @property
    def actions(self) -> ActionSet:
        """Return the actions this blind uses."""
        return action_set(self.rail, self.extended)

    @property
    def has_tilt(self) -> bool:
        """Return True when tilt is on and the rail has tilt actions."""
        return self.tilt and self.actions.has_tilt

    @property
    def has_position(self) -> bool:
        """Return True in positioning modes 1 and 2."""
        return self.mode != MODE_OPEN_CLOSE

    @property
    def has_favourite_2(self) -> bool:
        """Return True when the motor has favourite position 2."""
        return self.motor_code in FAVOURITE_2_MOTORS

    @property
    def model(self) -> str:
        """Return the device model: the motor name, or "Blind"."""
        return MOTOR_NAMES.get(self.motor_code, "Blind")

