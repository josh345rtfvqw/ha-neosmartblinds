"""Tests for the raw command action, favourites, notifications, connection and diagnostics."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.components.persistent_notification import (
    _async_get_or_create_notifications,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.neosmartblinds.const import DOMAIN
from custom_components.neosmartblinds.diagnostics import async_get_config_entry_diagnostics

from .conftest import HUB_ID, blind_subentry, make_entry, setup_entry
from .fake_controller import FakeController

SENSOR = "binary_sensor.neo_smart_controller_127_0_0_1_connection"


async def _wait_for(condition, timeout: float = 2.0) -> None:
    """Wait for a background task (like the 5 minute check) to finish."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not condition():
        assert loop.time() < end, "timed out waiting"
        await asyncio.sleep(0.01)


def _notices(hass: HomeAssistant) -> dict:
    return _async_get_or_create_notifications(hass)


async def _open(hass: HomeAssistant, entity_id: str = "cover.front") -> None:
    await hass.services.async_call(
        "cover", "open_cover", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def test_raw_command(hass: HomeAssistant, controller: FakeController) -> None:
    """send_command sends <code>-<command>!<motor> to blinds and rooms."""
    blinds = [
        blind_subentry("Left", parent_group="021.230-15", percent_support=2, start_position=30),
        blind_subentry("Right", blind_code="021.230-05", parent_group="021.230-15"),
    ]
    await setup_entry(hass, make_entry(controller, blinds))
    await hass.services.async_call(
        DOMAIN,
        "send_command",
        {ATTR_ENTITY_ID: ["cover.left", "cover.room_021_230_15_blinds"], "command": "I1"},
        blocking=True,
    )
    assert sorted(controller.commands) == ["021.230-04-i1!bf", "021.230-15-i1!bf"]
    assert hass.states.get("cover.left").attributes["current_position"] == 30

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "send_command",
            {ATTR_ENTITY_ID: "cover.left", "command": "abc"},
            blocking=True,
        )


async def test_favourite_buttons(hass: HomeAssistant, controller: FakeController) -> None:
    """Favourites send gp and i2 and leave the estimated position alone."""
    await setup_entry(
        hass,
        make_entry(
            controller, [blind_subentry("Front", motor_code="no", percent_support=1, start_position=40)]
        ),
    )
    registry = er.async_get(hass)
    for number in (1, 2):
        entity_id = registry.async_get_entity_id(
            "button", DOMAIN, f"neosmartblinds.021.230-04.no.1.favourite_{number}"
        )
        registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(next(iter(hass.config_entries.async_entries(DOMAIN))).entry_id)
    await hass.async_block_till_done()

    for number in (1, 2):
        await hass.services.async_call(
            "button",
            "press",
            {ATTR_ENTITY_ID: f"button.front_favourite_position_{number}"},
            blocking=True,
        )
    assert controller.commands == ["021.230-04-gp!no", "021.230-04-i2!no"]
    assert hass.states.get("cover.front").attributes["current_position"] == 40


async def test_command_failed_notice(hass: HomeAssistant, controller: FakeController) -> None:
    """A refused command raises, adds one notice per blind, and clears on the next send."""
    await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    controller.statuses.append(400)
    with pytest.raises(HomeAssistantError, match="021.230-04-up!bf"):
        await _open(hass)
    notices = [n for key, n in _notices(hass).items() if "_command_" in key]
    assert len(notices) == 1
    assert "Front" in notices[0]["message"]
    assert "021.230-04-up!bf" in notices[0]["message"]
    # The controller answered, so it is still connected.
    assert hass.states.get(SENSOR).state == STATE_ON

    await _open(hass)
    assert not [key for key in _notices(hass) if "_command_" in key]


async def test_hash_conflict_retried(hass: HomeAssistant, controller: FakeController) -> None:
    """409 is retried once with a new hash."""
    await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    controller.statuses.append(409)
    await _open(hass)
    assert controller.commands == ["021.230-04-up!bf", "021.230-04-up!bf"]
    assert controller.received[0].hash != controller.received[1].hash

    controller.clear()
    controller.statuses.extend([409, 409])
    with pytest.raises(HomeAssistantError):
        await _open(hass)
    assert len(controller.commands) == 2


async def test_other_status_reported(hass: HomeAssistant, controller: FakeController) -> None:
    """Any other status is reported in the error."""
    await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    controller.statuses.append(503)
    with pytest.raises(HomeAssistantError, match="503"):
        await _open(hass)


async def test_controller_not_answering(hass: HomeAssistant, controller: FakeController) -> None:
    """One notice per controller while it doesn't answer; clears when it does."""
    entry = await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    assert hass.states.get(SENSOR).state == STATE_ON
    await controller.stop()

    with pytest.raises(HomeAssistantError):
        await _open(hass)
    with pytest.raises(HomeAssistantError):
        await _open(hass)
    offline = [key for key in _notices(hass) if key.endswith("_offline")]
    assert offline == [f"{DOMAIN}_{entry.entry_id}_offline"]
    assert hass.states.get(SENSOR).state == STATE_OFF

    # Back on the same ports: the 5 minute check finds it.
    await controller.start()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    await _wait_for(lambda: hass.states.get(SENSOR).state == STATE_ON)
    assert not [key for key in _notices(hass) if key.endswith("_offline")]


async def test_periodic_check_sends_no_command(
    hass: HomeAssistant, controller: FakeController
) -> None:
    """The 5 minute check only opens a connection."""
    await setup_entry(hass, make_entry(controller, [blind_subentry("Front")], protocol="tcp"))
    before = controller.connections
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5, seconds=1))
    await hass.async_block_till_done()
    await _wait_for(lambda: controller.connections > before)
    await asyncio.sleep(0.05)
    assert controller.commands == []


async def test_room_failure_notice(hass: HomeAssistant, controller: FakeController) -> None:
    """A failed room command names the room."""
    blinds = [
        blind_subentry("Left", parent_group="021.230-15"),
        blind_subentry("Right", blind_code="021.230-05", parent_group="021.230-15"),
    ]
    await setup_entry(hass, make_entry(controller, blinds))
    controller.statuses.append(400)
    with pytest.raises(HomeAssistantError):
        await _open(hass, "cover.room_021_230_15_blinds")
    notices = [n for key, n in _notices(hass).items() if "_command_" in key]
    assert len(notices) == 1
    assert "Room 021.230-15 Blinds" in notices[0]["message"]


async def test_diagnostics(hass: HomeAssistant, controller: FakeController) -> None:
    """Diagnostics hold settings, status and commands, without host or ID."""
    entry = await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    await _open(hass)
    controller.statuses.append(400)
    with pytest.raises(HomeAssistantError):
        await _open(hass)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diagnostics)
    assert "127.0.0.1" not in text
    assert HUB_ID not in text
    assert diagnostics["blinds"][0]["data"]["blind_code"] == "021.230-04"
    assert diagnostics["controller"]["connected"] is True
    commands = diagnostics["controller"]["commands"]
    assert [c["result"] for c in commands][-2:][0] == "ok"
    assert "400" in commands[-1]["result"]


async def test_history_limited(hass: HomeAssistant, controller: FakeController) -> None:
    """Only the last 20 commands are kept."""
    entry = await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    for _ in range(22):
        await _open(hass)
    assert len(entry.runtime_data.history) == 20
