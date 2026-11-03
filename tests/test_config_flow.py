"""Tests for the controller config flow, options and blind subentries."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.persistent_notification import (
    _async_get_or_create_notifications,
)
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.neosmartblinds.const import DOMAIN

from .conftest import HUB_ID, advance, blind_subentry, make_entry, setup_entry
from .fake_controller import FakeController


async def _start(hass: HomeAssistant, host: str = "127.0.0.1", protocol: str = "http"):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": host, "protocol": protocol}
    )


async def test_user_flow_http(hass: HomeAssistant, controller: FakeController) -> None:
    """Both steps create the entry; nothing is sent to the controller."""
    result = await _start(hass)
    assert result["step_id"] == "connection"
    schema = result["data_schema"].schema
    port_key = next(key for key in schema if key == "port")
    assert port_key.description["suggested_value"] == 8838

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"port": controller.http_port, "hub_id": HUB_ID}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Neo Smart Controller (127.0.0.1)"
    assert result["data"] == {
        "host": "127.0.0.1",
        "protocol": "http",
        "port": controller.http_port,
        "hub_id": HUB_ID,
    }
    assert result["result"].unique_id == HUB_ID
    await hass.async_block_till_done()
    assert controller.commands == []


async def test_user_flow_tcp(hass: HomeAssistant, controller: FakeController) -> None:
    """TCP pre-fills 8839, needs no ID and uses the host as unique ID."""
    result = await _start(hass, protocol="tcp")
    schema = result["data_schema"].schema
    assert next(k for k in schema if k == "port").description["suggested_value"] == 8839
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"port": controller.tcp_port}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "127.0.0.1"
    assert result["data"]["hub_id"] == ""


@pytest.mark.parametrize(
    ("user_input", "error"),
    [
        ({}, {"hub_id": "hub_id_required"}),
        ({"hub_id": "short"}, {"hub_id": "invalid_hub_id"}),
    ],
)
async def test_user_flow_hub_id_errors(
    hass: HomeAssistant, controller: FakeController, user_input: dict, error: dict
) -> None:
    """HTTP needs a 24 character controller ID."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"port": controller.http_port, **user_input}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == error


async def test_user_flow_cannot_connect(hass: HomeAssistant, controller: FakeController) -> None:
    """A port nobody listens on gives cannot_connect, then recovers."""
    result = await _start(hass)
    await controller.stop()
    port = controller.http_port
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"port": port, "hub_id": HUB_ID}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    await controller.start()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"port": controller.http_port, "hub_id": HUB_ID}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_empty_host(hass: HomeAssistant) -> None:
    """An empty host is refused."""
    result = await _start(hass, host="  ")
    assert result["errors"] == {"host": "invalid_host"}


async def test_user_flow_duplicates(hass: HomeAssistant, controller: FakeController) -> None:
    """Same controller ID, or same host when there's no ID, is refused."""
    MockConfigEntry(domain=DOMAIN, unique_id=HUB_ID, data={"host": "10.0.0.9"}).add_to_hass(hass)
    MockConfigEntry(domain=DOMAIN, unique_id="127.0.0.1", data={"host": "127.0.0.1"}).add_to_hass(hass)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"port": controller.http_port, "hub_id": HUB_ID}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"

    result = await _start(hass, protocol="tcp")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"port": controller.tcp_port}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass: HomeAssistant, controller: FakeController) -> None:
    """Reconfigure changes protocol, port and ID, and keeps the connection sensor."""
    entry = await setup_entry(hass, make_entry(controller))
    registry = er.async_get(hass)
    sensor = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{HUB_ID}.connection")
    assert sensor

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", "protocol": "tcp"}
    )
    assert result["step_id"] == "reconfigure_connection"
    new_id = "B" * 24
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"port": controller.tcp_port, "hub_id": new_id}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["protocol"] == "tcp"
    assert entry.data["port"] == controller.tcp_port
    assert entry.unique_id == new_id
    assert registry.async_get(sensor).unique_id == f"{new_id}.connection"


async def test_reconfigure_duplicate(hass: HomeAssistant, controller: FakeController) -> None:
    """Reconfigure can't take another controller's ID."""
    entry = await setup_entry(hass, make_entry(controller))
    MockConfigEntry(domain=DOMAIN, unique_id="C" * 24, data={"host": "10.0.0.9"}).add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", "protocol": "http"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"port": controller.http_port, "hub_id": "C" * 24}
    )
    assert result["reason"] == "already_configured"


async def test_reauth_on_401(hass: HomeAssistant, controller: FakeController) -> None:
    """HTTP 401 starts re-authentication without a notice; new ID is saved."""
    entry = await setup_entry(
        hass, make_entry(controller, [blind_subentry("Front")], hub_id="D" * 24)
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "cover", "open_cover", {"entity_id": "cover.front"}, blocking=True
        )
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == "reauth"
    assert not any("_command_" in key for key in _async_get_or_create_notifications(hass))

    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"hub_id": "bad"}
    )
    assert result["errors"] == {"hub_id": "invalid_hub_id"}
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"hub_id": HUB_ID}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data["hub_id"] == HUB_ID
    assert entry.unique_id == HUB_ID

    controller.clear()
    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": "cover.front"}, blocking=True
    )
    assert controller.commands == ["021.230-04-up!bf"]


async def test_options_room_names(hass: HomeAssistant, controller: FakeController) -> None:
    """Configure shows one field per shared room code and renames the room."""
    entry = await setup_entry(
        hass,
        make_entry(
            controller,
            [
                blind_subentry("Left", parent_group="021.230-15"),
                blind_subentry("Right", blind_code="021.230-05", parent_group="021.230-15"),
                blind_subentry("Alone", blind_code="021.231-01", parent_group="021.231-15"),
            ],
        ),
    )
    assert hass.states.get("cover.room_021_230_15_blinds") is not None
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert [str(key) for key in result["data_schema"].schema] == ["021.230-15"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"021.230-15": "Frontyard"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["room_names"] == {"021.230-15": "Frontyard"}
    state = hass.states.get("cover.room_021_230_15_blinds")
    assert state.attributes["friendly_name"] == "Frontyard Blinds"


async def test_options_no_rooms(hass: HomeAssistant, controller: FakeController) -> None:
    """Without shared room codes there is nothing to name."""
    entry = await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_rooms"


# Blind subentries -----------------------------------------------------------

BLIND_INPUT = {
    "name": "Front",
    "blind_code": "021.230-04",
    "motor_code": "bf",
    "rail": "1",
    "tdbu_extended": False,
    "tilt": False,
    "percent_support": "0",
    "close_time": 20,
    "startup_sync": "none",
}


async def _add_blind(hass: HomeAssistant, entry: MockConfigEntry, user_input: dict):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "blind"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)


async def test_add_blind(hass: HomeAssistant, controller: FakeController) -> None:
    """Adding a blind stores the fixed data keys and creates the cover."""
    entry = await setup_entry(hass, make_entry(controller))
    result = await _add_blind(hass, entry, {**BLIND_INPUT, "motor_code": "BF", "open_time": 15})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    subentry = next(iter(entry.subentries.values()))
    assert subentry.title == "Front"
    assert subentry.unique_id == "neosmartblinds.021.230-04.bf.1"
    assert dict(subentry.data) == {
        "blind_code": "021.230-04",
        "motor_code": "bf",
        "rail": 1,
        "tdbu_extended": False,
        "tilt": False,
        "percent_support": 0,
        "close_time": 20,
        "open_time": 15,
        "startup_sync": "none",
        "start_position": None,
        "parent_group": "",
    }
    assert hass.states.get("cover.front") is not None


@pytest.mark.parametrize(
    ("changes", "errors"),
    [
        ({"blind_code": "21.230-04"}, {"blind_code": "invalid_blind_code"}),
        ({"blind_code": "256.230-04"}, {"blind_code": "invalid_blind_code"}),
        ({"blind_code": "021.230-16"}, {"blind_code": "invalid_blind_code"}),
        ({"motor_code": "b!"}, {"motor_code": "invalid_motor_code"}),
        ({"tdbu_extended": True}, {"tdbu_extended": "extended_not_supported"}),
        ({"percent_support": "1"}, {"percent_support": "position_not_supported"}),
        ({"percent_support": "1", "motor_code": "no", "rail": "2"}, {"percent_support": "position_not_supported"}),
        (
            {"percent_support": "1", "motor_code": "mb", "tdbu_extended": True},
            {"percent_support": "position_not_supported"},
        ),
        ({"parent_group": "021.230-14"}, {"parent_group": "invalid_room_code"}),
        ({"name": " "}, {"name": "invalid_name"}),
    ],
)
async def test_add_blind_validation(
    hass: HomeAssistant, controller: FakeController, changes: dict, errors: dict
) -> None:
    """Bad values are refused with a field error."""
    entry = await setup_entry(hass, make_entry(controller))
    result = await _add_blind(hass, entry, {**BLIND_INPUT, **changes})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors


async def test_add_blind_schema_limits(hass: HomeAssistant, controller: FakeController) -> None:
    """The form itself refuses a start position over 100."""
    entry = await setup_entry(hass, make_entry(controller))
    with pytest.raises(InvalidData):
        await _add_blind(hass, entry, {**BLIND_INPUT, "start_position": 101})


@pytest.mark.parametrize(
    "changes",
    [
        {"percent_support": "1", "motor_code": "no"},
        {"percent_support": "1", "motor_code": "rb"},
        {"percent_support": "1", "motor_code": ""},
        {"percent_support": "2", "rail": "3"},
        {"tdbu_extended": True, "motor_code": "db", "rail": "2"},
        {"parent_group": "021.230-15"},
        {"blind_code": "021.230-15"},
        {"blind_code": "255.000-00"},
    ],
)
async def test_add_blind_accepted(
    hass: HomeAssistant, controller: FakeController, changes: dict
) -> None:
    """Valid combinations are accepted."""
    entry = await setup_entry(hass, make_entry(controller))
    data = {**BLIND_INPUT, **changes}
    if data.get("motor_code") == "":
        data.pop("motor_code")
    result = await _add_blind(hass, entry, data)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_add_blind_duplicate(hass: HomeAssistant, controller: FakeController) -> None:
    """The same blind code, motor code and rail can't be added twice."""
    entry = await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    result = await _add_blind(hass, entry, {**BLIND_INPUT, "name": "Again"})
    assert result["errors"] == {"base": "already_configured"}
    # A different rail is a different blind.
    result = await _add_blind(hass, entry, {**BLIND_INPUT, "name": "Bottom", "rail": "2"})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_blind_settings_keep_entity(hass: HomeAssistant, controller: FakeController) -> None:
    """Changing settings, including the blind code, keeps the entity."""
    entry = await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    subentry = next(iter(entry.subentries.values()))
    registry = er.async_get(hass)
    entity = registry.async_get("cover.front")

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "blind"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["settings", "measure"]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    assert result["step_id"] == "settings"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {**BLIND_INPUT, "name": "Front window", "blind_code": "021.230-07", "percent_support": "2"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    subentry = entry.subentries[subentry.subentry_id]
    assert subentry.title == "Front window"
    assert subentry.unique_id == "neosmartblinds.021.230-07.bf.1"
    moved = registry.async_get("cover.front")
    assert moved is not None and moved.id == entity.id
    assert moved.unique_id == "neosmartblinds.021.230-07.bf.1"
    assert hass.states.get("cover.front").attributes.get("current_position") is not None


async def test_measure_times(hass: HomeAssistant, controller: FakeController, freezer) -> None:
    """Measuring opens, times the close, then times the open, and saves both."""
    entry = await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    subentry = next(iter(entry.subentries.values()))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "blind"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "measure"}
    )
    assert result["step_id"] == "measure"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert result["step_id"] == "measure_opened"
    assert controller.commands == ["021.230-04-up!bf"]
    await advance(hass, freezer, 30)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert result["step_id"] == "measure_closing"
    await advance(hass, freezer, 18.4)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert result["step_id"] == "measure_opening"
    await advance(hass, freezer, 21.2)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "measured"
    assert controller.commands == ["021.230-04-up!bf", "021.230-04-dn!bf", "021.230-04-up!bf"]
    await hass.async_block_till_done()
    data = entry.subentries[subentry.subentry_id].data
    assert data["close_time"] == 18.4
    assert data["open_time"] == 21.2


async def test_delete_blind(hass: HomeAssistant, controller: FakeController) -> None:
    """Removing a blind subentry removes its entities and device."""
    entry = await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    subentry = next(iter(entry.subentries.values()))
    assert hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get("cover.front") is None
    assert hass.states.get("cover.front") is None
