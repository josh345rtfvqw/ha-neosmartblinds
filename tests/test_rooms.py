"""Tests for room covers and combining commands into room commands."""

from __future__ import annotations

import asyncio

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN, CoverEntityFeature
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.neosmartblinds.const import DOMAIN

from .conftest import advance, run_frozen, blind_subentry, make_entry, setup_entry
from .fake_controller import FakeController

ROOM = "cover.room_021_230_15_blinds"


def _room_blinds(**overrides) -> list[dict]:
    return [
        blind_subentry("Left", parent_group="021.230-15", **overrides),
        blind_subentry("Right", blind_code="021.230-05", parent_group="021.230-15", **overrides),
    ]


async def _cover(hass: HomeAssistant, service: str, entity_id: str | list[str], **data) -> None:
    await hass.services.async_call(
        COVER_DOMAIN, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


async def test_room_cover_created(hass: HomeAssistant, controller: FakeController) -> None:
    """A room code shared by two blinds gets its own device and cover."""
    await setup_entry(hass, make_entry(controller, _room_blinds()))
    state = hass.states.get(ROOM)
    assert state is not None
    assert state.attributes["friendly_name"] == "Room 021.230-15 Blinds"
    assert not state.attributes[ATTR_SUPPORTED_FEATURES] & CoverEntityFeature.SET_POSITION
    entity = er.async_get(hass).async_get(ROOM)
    assert entity.unique_id == "neosmartblinds.021.230-15.room"
    device = dr.async_get(hass).async_get(entity.device_id)
    assert (DOMAIN, "neosmartblinds.021.230-15.room") in device.identifiers
    assert device.name == "Room 021.230-15"


async def test_no_room_cover_when_room_code_is_a_blind(
    hass: HomeAssistant, controller: FakeController
) -> None:
    """If the room code itself is added as a blind there is no room cover."""
    blinds = [*_room_blinds(), blind_subentry("Whole room", blind_code="021.230-15")]
    await setup_entry(hass, make_entry(controller, blinds))
    assert hass.states.get(ROOM) is None
    assert hass.states.get("cover.whole_room") is not None


async def test_room_commands_combined(hass: HomeAssistant, controller: FakeController) -> None:
    """The room cover sends one room command and updates each blind."""
    await setup_entry(hass, make_entry(controller, _room_blinds()))
    await _cover(hass, "close_cover", ROOM)
    assert controller.commands == ["021.230-15-dn!bf"]
    assert hass.states.get("cover.left").state == "closed"
    assert hass.states.get("cover.right").state == "closed"
    assert hass.states.get(ROOM).state == "closed"


async def test_same_command_to_each_blind_combined(
    hass: HomeAssistant, controller: FakeController
) -> None:
    """Commanding every blind at once within the window becomes one room command."""
    await setup_entry(hass, make_entry(controller, _room_blinds()))
    await _cover(hass, "open_cover", ["cover.left", "cover.right"])
    assert controller.commands == ["021.230-15-up!bf"]


async def test_single_blind_sent_after_wait(hass: HomeAssistant, controller: FakeController) -> None:
    """Only one blind of the room commanded: its own command after the wait."""
    await setup_entry(hass, make_entry(controller, _room_blinds()))
    loop = asyncio.get_running_loop()
    started = loop.time()
    await _cover(hass, "open_cover", "cover.left")
    assert loop.time() - started >= 0.2
    assert controller.commands == ["021.230-04-up!bf"]


async def test_different_commands_sent_separately(
    hass: HomeAssistant, controller: FakeController
) -> None:
    """Different commands in the same window go to each blind."""
    await setup_entry(hass, make_entry(controller, _room_blinds()))
    await asyncio.gather(
        _cover(hass, "open_cover", "cover.left"),
        _cover(hass, "close_cover", "cover.right"),
    )
    assert sorted(controller.commands) == ["021.230-04-up!bf", "021.230-05-dn!bf"]


async def test_mixed_motor_codes_not_combined(
    hass: HomeAssistant, controller: FakeController
) -> None:
    """Blinds with different motor codes can't share one room command."""
    blinds = [
        blind_subentry("Left", parent_group="021.230-15"),
        blind_subentry("Right", blind_code="021.230-05", motor_code="no", parent_group="021.230-15"),
    ]
    await setup_entry(hass, make_entry(controller, blinds))
    await _cover(hass, "open_cover", ROOM)
    assert sorted(controller.commands) == ["021.230-04-up!bf", "021.230-05-up!no"]


async def test_blind_without_room_sends_straight_away(
    hass: HomeAssistant, controller: FakeController
) -> None:
    """No room code: no wait."""
    await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    loop = asyncio.get_running_loop()
    started = loop.time()
    await _cover(hass, "open_cover", "cover.front")
    assert loop.time() - started < 0.2
    assert controller.commands == ["021.230-04-up!bf"]


async def test_room_position(hass: HomeAssistant, controller: FakeController, freezer) -> None:
    """Room position is the average, with a slider when every blind has positions."""
    blinds = [
        blind_subentry("Left", parent_group="021.230-15", percent_support=2, start_position=20),
        blind_subentry(
            "Right",
            blind_code="021.230-05",
            parent_group="021.230-15",
            percent_support=2,
            start_position=60,
        ),
    ]
    await setup_entry(hass, make_entry(controller, blinds))
    state = hass.states.get(ROOM)
    assert state.attributes[ATTR_SUPPORTED_FEATURES] & CoverEntityFeature.SET_POSITION
    assert state.attributes["current_position"] == 40

    await run_frozen(hass, freezer, _cover(hass, "set_cover_position", ROOM, position=80))
    # Both start with one room "up"; each then stops on its own time.
    assert controller.commands == ["021.230-15-up!bf"]
    await advance(hass, freezer, 4.1)
    assert controller.commands[-1] == "021.230-05-sp!bf"
    await advance(hass, freezer, 8)
    assert controller.commands[-1] == "021.230-04-sp!bf"
    assert hass.states.get("cover.left").attributes["current_position"] == 80
    assert hass.states.get("cover.right").attributes["current_position"] == 80
    assert hass.states.get(ROOM).attributes["current_position"] == 80


async def test_room_name_from_options(hass: HomeAssistant, controller: FakeController) -> None:
    """A named room uses the name for the device and cover."""
    entry = make_entry(controller, _room_blinds(), options={"room_names": {"021.230-15": "Frontyard"}})
    await setup_entry(hass, entry)
    state = hass.states.get("cover.frontyard_blinds")
    assert state.attributes["friendly_name"] == "Frontyard Blinds"
