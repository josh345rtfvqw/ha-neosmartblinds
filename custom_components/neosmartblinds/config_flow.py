"""Config flow, options flow and blind subentry flow for Neo Smart Blinds."""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.util import dt as dt_util

from .api import NeoConnectionError, async_check_connection
from .codes import build_command
from .const import (
    CONF_BLIND_CODE,
    CONF_CLOSE_TIME,
    CONF_HOST,
    CONF_HUB_ID,
    CONF_MOTOR_CODE,
    CONF_NAME,
    CONF_OPEN_TIME,
    CONF_PARENT_GROUP,
    CONF_PERCENT_SUPPORT,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_RAIL,
    CONF_ROOM_NAMES,
    CONF_START_POSITION,
    CONF_STARTUP_SYNC,
    CONF_TDBU_EXTENDED,
    CONF_TILT,
    DEFAULT_CLOSE_TIME,
    DEFAULT_PORTS,
    DOMAIN,
    MODE_OPEN_CLOSE,
    MOTOR_NAMES,
    POSITION_MODES,
    PROTOCOL_HTTP,
    PROTOCOLS,
    RAIL_TOP,
    RAILS,
    SUBENTRY_BLIND,
    SYNC_NONE,
    SYNC_OPTIONS,
)
from .hub import rooms_for_entry
from .settings import BlindSettings, BlindValidationError, unique_id_for, validate_blind
from .validation import ControllerValidationError, validate_controller, validate_hub_id

_LOGGER = logging.getLogger(__name__)


def entry_title(host: str) -> str:
    """Return the title for a controller entry."""
    return f"Neo Smart Controller ({host})"


def _unique_id(data: dict[str, Any]) -> str:
    return data.get(CONF_HUB_ID) or data[CONF_HOST]


def _step1_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST): TextSelector(),
            vol.Required(CONF_PROTOCOL, default=PROTOCOL_HTTP): SelectSelector(
                SelectSelectorConfig(
                    options=list(PROTOCOLS),
                    mode=SelectSelectorMode.LIST,
                    translation_key="protocol",
                )
            ),
        }
    )


def _step2_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PORT): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_HUB_ID): TextSelector(),
        }
    )


@callback
def _migrate_controller_identifier(
    hass: HomeAssistant, entry: ConfigEntry, new_identifier: str
) -> None:
    """Keep the controller device and sensor when the unique ID changes."""
    old_identifier = entry.unique_id or entry.entry_id
    if old_identifier == new_identifier:
        return
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, old_identifier)})
    if device is not None and dev_reg.async_get_device(
        identifiers={(DOMAIN, new_identifier)}
    ) is None:
        dev_reg.async_update_device(device.id, new_identifiers={(DOMAIN, new_identifier)})
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{old_identifier}.connection"
    )
    if entity_id and not ent_reg.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{new_identifier}.connection"
    ):
        ent_reg.async_update_entity(entity_id, new_unique_id=f"{new_identifier}.connection")


class NeoSmartBlindsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Neo Smart Controller."""

    VERSION = 1
    MINOR_VERSION = 3

    def __init__(self) -> None:
        """Start with nothing entered."""
        self._host = ""
        self._protocol = PROTOCOL_HTTP

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Blinds are subentries of a controller."""
        return {SUBENTRY_BLIND: BlindSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Room names."""
        return RoomNamesOptionsFlow()

    # New controller -----------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: host and protocol."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = str(user_input[CONF_HOST]).strip()
            self._protocol = user_input[CONF_PROTOCOL]
            if not self._host:
                errors[CONF_HOST] = "invalid_host"
            else:
                return await self.async_step_connection()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_step1_schema(), user_input or {}),
            errors=errors,
        )

    async def async_step_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: port and controller ID."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await self._async_validate_connection(user_input)
            if data is not None:
                await self.async_set_unique_id(_unique_id(data))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=entry_title(data[CONF_HOST]), data=data)
        suggested = user_input or {CONF_PORT: DEFAULT_PORTS[self._protocol]}
        return self.async_show_form(
            step_id="connection",
            data_schema=self.add_suggested_values_to_schema(_step2_schema(), suggested),
            errors=errors,
            description_placeholders={"host": self._host, "protocol": self._protocol.upper()},
        )

    async def _async_validate_connection(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        try:
            data = validate_controller(
                {
                    CONF_HOST: self._host,
                    CONF_PROTOCOL: self._protocol,
                    CONF_PORT: user_input.get(CONF_PORT),
                    CONF_HUB_ID: user_input.get(CONF_HUB_ID),
                }
            )
        except ControllerValidationError as err:
            return None, {err.field if err.field != CONF_HOST else "base": err.error}
        try:
            await async_check_connection(data[CONF_HOST], data[CONF_PORT])
        except NeoConnectionError:
            return None, {"base": "cannot_connect"}
        return data, {}

    # Reconfigure --------------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host and protocol."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = str(user_input[CONF_HOST]).strip()
            self._protocol = user_input[CONF_PROTOCOL]
            if not self._host:
                errors[CONF_HOST] = "invalid_host"
            else:
                return await self.async_step_reconfigure_connection()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _step1_schema(), user_input or dict(entry.data)
            ),
            errors=errors,
        )

    async def async_step_reconfigure_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change port and controller ID."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = await self._async_validate_connection(user_input)
            if data is not None:
                new_unique_id = _unique_id(data)
                if self._unique_id_taken(new_unique_id, entry):
                    return self.async_abort(reason="already_configured")
                _migrate_controller_identifier(self.hass, entry, new_unique_id)
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=new_unique_id,
                    title=entry_title(data[CONF_HOST]),
                    data=data,
                )
        if user_input is None:
            suggested: dict[str, Any] = {CONF_HUB_ID: entry.data.get(CONF_HUB_ID, "")}
            if entry.data.get(CONF_PROTOCOL) == self._protocol:
                suggested[CONF_PORT] = entry.data.get(CONF_PORT)
            else:
                suggested[CONF_PORT] = DEFAULT_PORTS[self._protocol]
        else:
            suggested = user_input
        return self.async_show_form(
            step_id="reconfigure_connection",
            data_schema=self.add_suggested_values_to_schema(_step2_schema(), suggested),
            errors=errors,
            description_placeholders={"host": self._host, "protocol": self._protocol.upper()},
        )

    def _unique_id_taken(self, unique_id: str, current: ConfigEntry) -> bool:
        return any(
            other.unique_id == unique_id and other.entry_id != current.entry_id
            for other in self._async_current_entries(include_ignore=False)
        )

    # Re-authentication --------------------------------------------------

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """The controller said the ID was not found (HTTP 401)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the controller ID again."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            protocol = entry.data.get(CONF_PROTOCOL, PROTOCOL_HTTP)
            try:
                hub_id = validate_hub_id(user_input.get(CONF_HUB_ID), protocol)
            except ControllerValidationError as err:
                errors[CONF_HUB_ID] = err.error
            else:
                data = {**entry.data, CONF_HUB_ID: hub_id}
                new_unique_id = _unique_id(data)
                if self._unique_id_taken(new_unique_id, entry):
                    return self.async_abort(reason="already_configured")
                _migrate_controller_identifier(self.hass, entry, new_unique_id)
                return self.async_update_reload_and_abort(
                    entry, unique_id=new_unique_id, data=data
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HUB_ID): TextSelector()}),
                user_input or {CONF_HUB_ID: entry.data.get(CONF_HUB_ID, "")},
            ),
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )

    # YAML import --------------------------------------------------------

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import a controller and blinds from old YAML."""
        controller: dict[str, Any] = import_data["controller"]
        blinds: list[dict[str, Any]] = import_data["blinds"]
        unique_id = _unique_id(controller)
        await self.async_set_unique_id(unique_id, raise_on_progress=False)

        for entry in self._async_current_entries(include_ignore=False):
            if entry.unique_id != unique_id:
                continue
            existing = {subentry.unique_id for subentry in entry.subentries.values()}
            for blind in blinds:
                blind_unique_id = unique_id_for(blind["data"])
                if blind_unique_id in existing:
                    continue
                self.hass.config_entries.async_add_subentry(
                    entry,
                    ConfigSubentry(
                        data=MappingProxyType(blind["data"]),
                        subentry_type=SUBENTRY_BLIND,
                        title=blind["title"],
                        unique_id=blind_unique_id,
                    ),
                )
                existing.add(blind_unique_id)
            return self.async_abort(reason="already_configured")

        subentries = []
        seen: set[str] = set()
        for blind in blinds:
            blind_unique_id = unique_id_for(blind["data"])
            if blind_unique_id in seen:
                continue
            seen.add(blind_unique_id)
            subentries.append(
                {
                    "data": blind["data"],
                    "subentry_type": SUBENTRY_BLIND,
                    "title": blind["title"],
                    "unique_id": blind_unique_id,
                }
            )
        return self.async_create_entry(
            title=entry_title(controller[CONF_HOST]),
            data=controller,
            subentries=subentries,
        )


class RoomNamesOptionsFlow(OptionsFlow):
    """Name the rooms (room codes shared by two or more blinds)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """One text field per room code."""
        rooms = rooms_for_entry(self.config_entry)
        if not rooms:
            return self.async_abort(reason="no_rooms")
        current: dict[str, str] = dict(self.config_entry.options.get(CONF_ROOM_NAMES, {}))
        if user_input is not None:
            names = dict(current)
            for code in rooms:
                name = str(user_input.get(code) or "").strip()
                if name:
                    names[code] = name
                else:
                    names.pop(code, None)
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_ROOM_NAMES: names}
            )
        schema = vol.Schema(
            {
                vol.Optional(code, description={"suggested_value": current.get(code, "")}): str
                for code in sorted(rooms)
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "rooms": ", ".join(
                    f"{code} ({len(room.members)} blinds)" for code, room in sorted(rooms.items())
                )
            },
        )


def _blind_schema() -> vol.Schema:
    motor_options = [
        SelectOptionDict(value=code, label=f"{code} – {name}") for code, name in MOTOR_NAMES.items()
    ]
    seconds = NumberSelectorConfig(
        min=1, max=600, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="s"
    )
    return vol.Schema(
        {
            vol.Required(CONF_NAME): TextSelector(),
            vol.Required(CONF_BLIND_CODE): TextSelector(),
            vol.Optional(CONF_MOTOR_CODE): SelectSelector(
                SelectSelectorConfig(
                    options=motor_options, custom_value=True, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required(CONF_RAIL, default=str(RAIL_TOP)): SelectSelector(
                SelectSelectorConfig(
                    options=[str(rail) for rail in RAILS],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="rail",
                )
            ),
            vol.Required(CONF_TDBU_EXTENDED, default=False): BooleanSelector(),
            vol.Required(CONF_TILT, default=False): BooleanSelector(),
            vol.Required(CONF_PERCENT_SUPPORT, default=str(MODE_OPEN_CLOSE)): SelectSelector(
                SelectSelectorConfig(
                    options=[str(mode) for mode in POSITION_MODES],
                    mode=SelectSelectorMode.LIST,
                    translation_key="percent_support",
                )
            ),
            vol.Required(CONF_CLOSE_TIME, default=DEFAULT_CLOSE_TIME): NumberSelector(seconds),
            vol.Optional(CONF_OPEN_TIME): NumberSelector(seconds),
            vol.Required(CONF_STARTUP_SYNC, default=SYNC_NONE): SelectSelector(
                SelectSelectorConfig(
                    options=list(SYNC_OPTIONS),
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="startup_sync",
                )
            ),
            vol.Optional(CONF_START_POSITION): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="%")
            ),
            vol.Optional(CONF_PARENT_GROUP): TextSelector(),
        }
    )


def _form_values(title: str, data: dict[str, Any]) -> dict[str, Any]:
    """Turn subentry data into form values."""
    values: dict[str, Any] = {CONF_NAME: title}
    for key, value in data.items():
        if value is None or value == "":
            continue
        if key in (CONF_RAIL, CONF_PERCENT_SUPPORT):
            value = str(value)
        values[key] = value
    return values


class BlindSubentryFlow(ConfigSubentryFlow):
    """Add or change a blind on a controller."""

    def __init__(self) -> None:
        """Start a fresh flow."""
        self._measure_started = 0.0
        self._close_time: float | None = None

    def _validate(
        self, user_input: dict[str, Any], current: ConfigSubentry | None
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        name = str(user_input.get(CONF_NAME) or "").strip()
        if not name:
            return None, {CONF_NAME: "invalid_name"}
        try:
            data = validate_blind(user_input)
        except BlindValidationError as err:
            return None, {err.field: err.error}
        unique_id = unique_id_for(data)
        for subentry in self._get_entry().subentries.values():
            if current is not None and subentry.subentry_id == current.subentry_id:
                continue
            if subentry.unique_id == unique_id:
                return None, {"base": "already_configured"}
        return data, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Add a blind."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(user_input, None)
            if data is not None:
                return self.async_create_entry(
                    title=str(user_input[CONF_NAME]).strip(),
                    data=data,
                    unique_id=unique_id_for(data),
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_blind_schema(), user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose between settings and measuring times."""
        return self.async_show_menu(step_id="reconfigure", menu_options=["settings", "measure"])

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a blind's settings, keeping its entity."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(user_input, subentry)
            if data is not None:
                unique_id = unique_id_for(data)
                if subentry.unique_id and unique_id != subentry.unique_id:
                    _migrate_blind_identifier(self.hass, subentry.unique_id, unique_id)
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=str(user_input[CONF_NAME]).strip(),
                    data=data,
                    unique_id=unique_id,
                )
        values = user_input or _form_values(subentry.title, dict(subentry.data))
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(_blind_schema(), values),
            errors=errors,
        )

    # Measuring ----------------------------------------------------------

    def _blind(self) -> BlindSettings:
        return BlindSettings.from_subentry(self._get_reconfigure_subentry())

    async def _async_send(self, action: str) -> bool:
        entry = self._get_entry()
        hub = getattr(entry, "runtime_data", None)
        if hub is None:
            return False
        blind = self._blind()
        try:
            await hub.async_send(
                build_command(blind.blind_code, action, blind.motor_code),
                key=blind.unique_id,
                name=blind.name,
            )
        except HomeAssistantError:
            return False
        return True

    async def async_step_measure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Explain, then open the blind fully."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if await self._async_send(self._blind().actions.open):
                return await self.async_step_measure_opened()
            errors["base"] = "command_failed"
        return self.async_show_form(
            step_id="measure",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"name": self._blind().name},
        )

    async def async_step_measure_opened(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Once fully open, send close and start timing."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if await self._async_send(self._blind().actions.close):
                self._measure_started = dt_util.utcnow().timestamp()
                return await self.async_step_measure_closing()
            errors["base"] = "command_failed"
        return self.async_show_form(
            step_id="measure_opened", data_schema=vol.Schema({}), errors=errors
        )

    async def async_step_measure_closing(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Submit when it stops: records the close time, then opens and times that."""
        errors: dict[str, str] = {}
        if user_input is not None:
            elapsed = dt_util.utcnow().timestamp() - self._measure_started
            if await self._async_send(self._blind().actions.open):
                self._close_time = elapsed
                self._measure_started = dt_util.utcnow().timestamp()
                return await self.async_step_measure_opening()
            errors["base"] = "command_failed"
        return self.async_show_form(
            step_id="measure_closing", data_schema=vol.Schema({}), errors=errors
        )

    async def async_step_measure_opening(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Submit when it stops: records the open time and saves both."""
        if user_input is None:
            return self.async_show_form(step_id="measure_opening", data_schema=vol.Schema({}))
        open_time = dt_util.utcnow().timestamp() - self._measure_started
        close_time = self._close_time or DEFAULT_CLOSE_TIME
        subentry = self._get_reconfigure_subentry()
        # The blind finishes fully open.
        self.hass.data.setdefault(DOMAIN, {}).setdefault("positions", {})[
            subentry.unique_id
        ] = 100
        self._async_update_times(subentry, round(close_time, 1), round(open_time, 1))
        return self.async_abort(
            reason="measured",
            description_placeholders={
                "close_time": f"{close_time:.1f}",
                "open_time": f"{open_time:.1f}",
            },
        )

    @callback
    def _async_update_times(
        self, subentry: ConfigSubentry, close_time: float, open_time: float
    ) -> None:
        self.hass.config_entries.async_update_subentry(
            self._get_entry(),
            subentry,
            data={
                **subentry.data,
                CONF_CLOSE_TIME: max(close_time, 0.1),
                CONF_OPEN_TIME: max(open_time, 0.1),
            },
        )


@callback
def _migrate_blind_identifier(hass: HomeAssistant, old: str, new: str) -> None:
    """Move a blind's entities and device to a new unique ID so they are kept."""
    ent_reg = er.async_get(hass)
    for domain, suffix in (("cover", ""), ("button", ".favourite_1"), ("button", ".favourite_2")):
        entity_id = ent_reg.async_get_entity_id(domain, DOMAIN, f"{old}{suffix}")
        if entity_id and not ent_reg.async_get_entity_id(domain, DOMAIN, f"{new}{suffix}"):
            ent_reg.async_update_entity(entity_id, new_unique_id=f"{new}{suffix}")
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, old)})
    if device is not None and dev_reg.async_get_device(identifiers={(DOMAIN, new)}) is None:
        dev_reg.async_update_device(device.id, new_identifiers={(DOMAIN, new)})
