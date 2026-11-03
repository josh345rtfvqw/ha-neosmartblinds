"""Constants for the Neo Smart Blinds integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "neosmartblinds"
NAME: Final = "Neo Smart Blinds"

# Controller entry data keys.
CONF_HOST: Final = "host"
CONF_PROTOCOL: Final = "protocol"
CONF_PORT: Final = "port"
CONF_HUB_ID: Final = "hub_id"

# Controller options keys.
CONF_ROOM_NAMES: Final = "room_names"

# Blind subentry.
SUBENTRY_BLIND: Final = "blind"
CONF_NAME: Final = "name"
CONF_BLIND_CODE: Final = "blind_code"
CONF_MOTOR_CODE: Final = "motor_code"
CONF_RAIL: Final = "rail"
CONF_TDBU_EXTENDED: Final = "tdbu_extended"
CONF_TILT: Final = "tilt"
CONF_PERCENT_SUPPORT: Final = "percent_support"
CONF_CLOSE_TIME: Final = "close_time"
CONF_OPEN_TIME: Final = "open_time"
CONF_STARTUP_SYNC: Final = "startup_sync"
CONF_START_POSITION: Final = "start_position"
CONF_PARENT_GROUP: Final = "parent_group"

PROTOCOL_HTTP: Final = "http"
PROTOCOL_TCP: Final = "tcp"
PROTOCOLS: Final = (PROTOCOL_HTTP, PROTOCOL_TCP)

DEFAULT_PORTS: Final = {PROTOCOL_HTTP: 8838, PROTOCOL_TCP: 8839}
DEFAULT_CLOSE_TIME: Final = 20

HUB_ID_LENGTH: Final = 24

MODE_OPEN_CLOSE: Final = 0
MODE_MOTOR_POSITION: Final = 1
MODE_TIMED: Final = 2
POSITION_MODES: Final = (MODE_OPEN_CLOSE, MODE_MOTOR_POSITION, MODE_TIMED)

SYNC_NONE: Final = "none"
SYNC_OPEN: Final = "open"
SYNC_CLOSE: Final = "close"
SYNC_OPTIONS: Final = (SYNC_NONE, SYNC_OPEN, SYNC_CLOSE)

RAIL_TOP: Final = 1
RAIL_BOTTOM: Final = 2
RAIL_BOTH: Final = 3
RAILS: Final = (RAIL_TOP, RAIL_BOTTOM, RAIL_BOTH)

ROOM_CHANNEL: Final = "15"

# Motor codes from Neo's documents, in the order Neo lists them.
MOTOR_NAMES: Final[dict[str, str]] = {
    "bf": "Bofu (standard)",
    "vb": "Bofu (vertical)",
    "tb": "Bofu top-down/bottom-up",
    "no": "NEO",
    "rx": "Raex",
    "nc": "Nice F-Code",
    "nr": "Nice 0-Code",
    "k1": "A-OK (standard)",
    "k2": "A-OK v2 (Louvolite)",
    "k3": "A-OK v3 (Eclipse)",
    "dy": "Dooya (unidirectional)",
    "by": "Bofu/Dooya (deprecated)",
    "wt": "Wistar / Alpha",
    "db": "Dooya (bi-directional)",
    "sy": "Somfy RTS",
    "gp": "Gaposa",
    "ra": "Rollease ARC",
    "re": "Rollease EL",
    "ap": "AMP (Turnils)",
    "sf": "Sunfrere",
    "rc": "Ronco",
    "bl": "Alta Bliss",
    "mb": "Coulisse MotionBlinds",
    "jo": "Jiecang",
}

# Motors that accept a 01-99 position (top rail only). "rb" is listed by Neo
# here but not in its motor table, so it is accepted when typed.
POSITION_MOTORS: Final = frozenset({"no", "db", "ra", "rb", "ap", "bl", "mb", "jo"})
# Motors that can use the extended top-down/bottom-up command set.
EXTENDED_MOTORS: Final = frozenset({"mb", "ra", "ap", "db"})
# Motors that have favourite position 2. An empty motor code also qualifies.
FAVOURITE_2_MOTORS: Final = frozenset({"no", "rx", ""})

ACTION_FAVOURITE_1: Final = "gp"
ACTION_FAVOURITE_2: Final = "i2"

# Position limits: outside these a plain open or close is sent with no stop.
POSITION_CLOSE_BELOW: Final = 2
POSITION_OPEN_ABOVE: Final = 98
DEFAULT_POSITION: Final = 50

# Timing.
COMMAND_SPACING: Final = 0.7
COMMAND_TIMEOUT: Final = 10
ROOM_WINDOW: Final = 0.25
CONNECTION_CHECK_INTERVAL: Final = 300
HISTORY_LENGTH: Final = 20

SERVICE_SEND_COMMAND: Final = "send_command"
ATTR_COMMAND: Final = "command"

ISSUE_DEPRECATED_YAML: Final = "deprecated_yaml"
