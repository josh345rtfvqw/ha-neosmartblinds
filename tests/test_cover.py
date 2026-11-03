"""Tests for blind covers: commands in each positioning mode."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import mock_restore_cache_with_extra_data

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    DOMAIN as COVER_DOMAIN,
    SERVICE_CLOSE_COVER,
    SERVICE_CLOSE_COVER_TILT,
    SERVICE_OPEN_COVER,
    SERVICE_OPEN_COVER_TILT,
    SERVICE_SET_COVER_POSITION,
    SERVICE_STOP_COVER,
    CoverEntityFeature,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES, STATE_CLOSED, STATE_OPEN
from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers import entity_registry as er

from .conftest import advance, blind_subentry, make_entry, setup_entry
from .fake_controller import FakeController

ENTITY = "cover.front"


async def _call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(
        COVER_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY, **data}, blocking=True
    )


def _position(hass: HomeAssistant) -> int:
    return hass.states.get(ENTITY).attributes[ATTR_CURRENT_POSITION]


async def test_mode_0_open_close_stop(hass: HomeAssistant, controller: FakeController) -> None:
    """Mode 0 sends up/sp/dn, has no position and remembers open/closed."""
    await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    state = hass.states.get(ENTITY)
    assert state.attributes.get("assumed_state") is True
    features = state.attributes[ATTR_SUPPORTED_FEATURES]
    assert not features & CoverEntityFeature.SET_POSITION
    assert not features & CoverEntityFeature.OPEN_TILT

    await _call(hass, SERVICE_OPEN_COVER)
    assert hass.states.get(ENTITY).state == STATE_OPEN
    await _call(hass, SERVICE_STOP_COVER)
    await _call(hass, SERVICE_CLOSE_COVER)
    assert hass.states.get(ENTITY).state == STATE_CLOSED
    assert controller.commands == ["021.230-04-up!bf", "021.230-04-sp!bf", "021.230-04-dn!bf"]
    assert all(item.hub_id == "A" * 24 for item in controller.received)
    hashes = [item.hash for item in controller.received]
    assert all(len(h) == 7 and h.isdigit() for h in hashes)
    assert len(set(hashes)) == len(hashes)


async def test_no_motor_code_and_tcp(hass: HomeAssistant, controller: FakeController) -> None:
    """TCP sends the command with CRLF; no motor code leaves off the !."""
    entry = make_entry(
        controller, [blind_subentry("Front", motor_code="")], protocol="tcp", hub_id=""
    )
    await setup_entry(hass, entry)
    await _call(hass, SERVICE_OPEN_COVER)
    assert controller.received[-1].protocol == "tcp"
    assert controller.commands[-1] == "021.230-04-up"


async def test_tilt_and_rails(hass: HomeAssistant, controller: FakeController) -> None:
    """Tilt sends micro-steps; the bottom rail and extended set use their actions."""
    await setup_entry(
        hass,
        make_entry(
            controller,
            [
                blind_subentry("Front", tilt=True),
                blind_subentry("Bottom", blind_code="021.230-05", rail=2, tilt=True),
                blind_subentry(
                    "Middle", blind_code="021.230-06", motor_code="mb", tdbu_extended=True, tilt=True
                ),
            ],
        ),
    )
    features = hass.states.get(ENTITY).attributes[ATTR_SUPPORTED_FEATURES]
    assert features & CoverEntityFeature.OPEN_TILT
    await _call(hass, SERVICE_OPEN_COVER_TILT)
    await _call(hass, SERVICE_CLOSE_COVER_TILT)

    for service in (SERVICE_OPEN_COVER, SERVICE_CLOSE_COVER, SERVICE_OPEN_COVER_TILT):
        await hass.services.async_call(
            COVER_DOMAIN, service, {ATTR_ENTITY_ID: "cover.bottom"}, blocking=True
        )
    middle = hass.states.get("cover.middle")
    assert not middle.attributes[ATTR_SUPPORTED_FEATURES] & CoverEntityFeature.OPEN_TILT
    for service in (SERVICE_OPEN_COVER, SERVICE_CLOSE_COVER, SERVICE_STOP_COVER):
        await hass.services.async_call(
            COVER_DOMAIN, service, {ATTR_ENTITY_ID: "cover.middle"}, blocking=True
        )
    assert controller.commands == [
        "021.230-04-mu!bf",
        "021.230-04-md!bf",
        "021.230-05-u2!bf",
        "021.230-05-d2!bf",
        "021.230-05-o2!bf",
        "021.230-06-u4!mb",
        "021.230-06-d4!mb",
        "021.230-06-x2!mb",
    ]


async def test_mode_1_sends_percent_closed(
    hass: HomeAssistant, controller: FakeController, freezer
) -> None:
    """Mode 1 sends 01-99 as percent closed, or a plain open/close near the ends."""
    await setup_entry(
        hass,
        make_entry(
            controller, [blind_subentry("Front", motor_code="no", percent_support=1, start_position=0)]
        ),
    )
    assert hass.states.get(ENTITY).attributes[ATTR_SUPPORTED_FEATURES] & CoverEntityFeature.SET_POSITION
    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 30})
    assert controller.commands == ["021.230-04-70!no"]
    await advance(hass, freezer, 3)
    assert _position(hass) == 15  # 3 s of 20 s is 15 %
    await advance(hass, freezer, 5)
    assert _position(hass) == 30

    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 99})
    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 1})
    assert controller.commands[1:] == ["021.230-04-up!no", "021.230-04-sp!no", "021.230-04-dn!no"]


async def test_mode_2_timed(hass: HomeAssistant, controller: FakeController, freezer) -> None:
    """Mode 2 sends up/down, then stop after the worked-out time."""
    await setup_entry(
        hass,
        make_entry(
            controller,
            [blind_subentry("Front", percent_support=2, close_time=20, open_time=10, start_position=0)],
        ),
    )
    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 50})
    assert controller.commands == ["021.230-04-up!bf"]
    assert hass.states.get(ENTITY).state == "opening"
    await advance(hass, freezer, 2)
    assert _position(hass) == 20  # opening uses the 10 s open time
    await advance(hass, freezer, 3.1)
    assert controller.commands == ["021.230-04-up!bf", "021.230-04-sp!bf"]
    assert _position(hass) == 50
    assert hass.states.get(ENTITY).state == STATE_OPEN

    controller.clear()
    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 25})
    await advance(hass, freezer, 2)
    assert _position(hass) == 40  # closing uses the 20 s close time
    await advance(hass, freezer, 3.1)
    assert controller.commands == ["021.230-04-dn!bf", "021.230-04-sp!bf"]
    assert _position(hass) == 25

    # Fully closing sends no stop and counts as exact once the time passes.
    controller.clear()
    await _call(hass, SERVICE_CLOSE_COVER)
    await advance(hass, freezer, 6)
    assert controller.commands == ["021.230-04-dn!bf"]
    assert _position(hass) == 0
    assert hass.states.get(ENTITY).state == STATE_CLOSED


async def test_mode_2_mid_move_changes(
    hass: HomeAssistant, controller: FakeController, freezer
) -> None:
    """Same direction extends or shortens; the other way stops and reverses."""
    await setup_entry(
        hass,
        make_entry(
            controller, [blind_subentry("Front", percent_support=2, close_time=10, start_position=0)]
        ),
    )
    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 50})
    await advance(hass, freezer, 2)  # at 20
    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 80})
    assert controller.commands == ["021.230-04-up!bf"]  # no stop, just extended
    await advance(hass, freezer, 3.1)
    assert controller.commands == ["021.230-04-up!bf"]  # still going past 50
    await advance(hass, freezer, 3)
    assert controller.commands == ["021.230-04-up!bf", "021.230-04-sp!bf"]
    assert _position(hass) == 80

    controller.clear()
    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 20})
    await advance(hass, freezer, 1)  # at 70
    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 50})
    await advance(hass, freezer, 2)  # shortened: stops at 50
    assert controller.commands == ["021.230-04-dn!bf", "021.230-04-sp!bf"]
    assert _position(hass) == 50

    controller.clear()
    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})
    await advance(hass, freezer, 1)  # at 40, heading down
    await _call(hass, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 60})
    assert controller.commands == ["021.230-04-dn!bf", "021.230-04-sp!bf", "021.230-04-up!bf"]
    await advance(hass, freezer, 2.1)
    assert controller.commands[-1] == "021.230-04-sp!bf"
    assert _position(hass) == 60


async def test_stop_freezes_estimate(
    hass: HomeAssistant, controller: FakeController, freezer
) -> None:
    """Stopping mid-move keeps the estimate where it was."""
    await setup_entry(
        hass,
        make_entry(
            controller, [blind_subentry("Front", percent_support=2, close_time=10, start_position=100)]
        ),
    )
    await _call(hass, SERVICE_CLOSE_COVER)
    await advance(hass, freezer, 3)
    await _call(hass, SERVICE_STOP_COVER)
    assert _position(hass) == 70
    await advance(hass, freezer, 10)
    assert _position(hass) == 70
    assert controller.commands == ["021.230-04-dn!bf", "021.230-04-sp!bf"]


@pytest.mark.parametrize(
    ("restored", "start_position", "expected"),
    [({"position": 35.0, "closed": None}, 80, 35), (None, 80, 80), (None, None, 50)],
)
async def test_restore_position(
    hass: HomeAssistant,
    controller: FakeController,
    restored: dict | None,
    start_position: int | None,
    expected: int,
) -> None:
    """Saved position wins, then start position, then 50."""
    if restored is not None:
        mock_restore_cache_with_extra_data(hass, [(State(ENTITY, STATE_OPEN), restored)])
    await setup_entry(
        hass,
        make_entry(
            controller,
            [blind_subentry("Front", percent_support=2, start_position=start_position)],
        ),
    )
    assert _position(hass) == expected


async def test_restore_open_closed(hass: HomeAssistant, controller: FakeController) -> None:
    """Mode 0 restores whether it was last opened or closed."""
    mock_restore_cache_with_extra_data(
        hass, [(State(ENTITY, STATE_CLOSED), {"position": None, "closed": True})]
    )
    await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    assert hass.states.get(ENTITY).state == STATE_CLOSED


async def test_startup_sync(hass: HomeAssistant, controller: FakeController) -> None:
    """Re-sync is sent when Home Assistant starts, not on reload."""
    hass.set_state(CoreState.not_running)
    entry = await setup_entry(
        hass, make_entry(controller, [blind_subentry("Front", startup_sync="close")])
    )
    assert controller.commands == []
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    hass.set_state(CoreState.running)
    await hass.async_block_till_done()
    assert controller.commands == ["021.230-04-dn!bf"]

    controller.clear()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert controller.commands == []


async def test_unique_ids(hass: HomeAssistant, controller: FakeController) -> None:
    """Unique IDs match the fixed interface."""
    await setup_entry(
        hass,
        make_entry(
            controller,
            [blind_subentry("Front"), blind_subentry("Plain", blind_code="021.230-05", motor_code="")],
        ),
    )
    registry = er.async_get(hass)
    assert registry.async_get(ENTITY).unique_id == "neosmartblinds.021.230-04.bf.1"
    assert registry.async_get("cover.plain").unique_id == "neosmartblinds.021.230-05..1"
    fav = registry.async_get_entity_id("button", "neosmartblinds", "neosmartblinds.021.230-04.bf.1.favourite_1")
    assert fav is not None
    assert registry.async_get(fav).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    # bf has no favourite 2; no motor code does.
    assert registry.async_get_entity_id(
        "button", "neosmartblinds", "neosmartblinds.021.230-04.bf.1.favourite_2"
    ) is None
    assert registry.async_get_entity_id(
        "button", "neosmartblinds", "neosmartblinds.021.230-05..1.favourite_2"
    )
    assert registry.async_get_entity_id(
        "binary_sensor", "neosmartblinds", f"{'A' * 24}.connection"
    )
