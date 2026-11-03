"""Tests for set-up, migration and the protocol helpers."""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.neosmartblinds.api import HashSource
from custom_components.neosmartblinds.codes import (
    normalise_blind_code,
    normalise_motor_code,
    normalise_room_code,
)
from custom_components.neosmartblinds.const import DOMAIN

from .conftest import HUB_ID, blind_subentry, make_entry, setup_entry
from .fake_controller import FakeController


async def test_setup_and_unload(hass: HomeAssistant, controller: FakeController) -> None:
    """The controller is a device; blinds link to it through via_device."""
    entry = await setup_entry(hass, make_entry(controller, [blind_subentry("Front")]))
    registry = dr.async_get(hass)
    hub_device = registry.async_get_device(identifiers={(DOMAIN, HUB_ID)})
    assert hub_device is not None
    blind = registry.async_get_device(identifiers={(DOMAIN, "neosmartblinds.021.230-04.bf.1")})
    assert blind.via_device_id == hub_device.id
    assert blind.model == "Bofu (standard)"
    assert blind.name == "Front"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_blind_model_without_motor(hass: HomeAssistant, controller: FakeController) -> None:
    """Without a known motor code the model is Blind."""
    await setup_entry(hass, make_entry(controller, [blind_subentry("Front", motor_code="zz")]))
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, "neosmartblinds.021.230-04.zz.1")}
    )
    assert device.model == "Blind"


async def test_migrate_older_minor(hass: HomeAssistant, controller: FakeController) -> None:
    """Entries from 1.1 and 1.2 are brought up to 1.3."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HUB_ID,
        version=1,
        minor_version=1,
        data={"host": "127.0.0.1", "protocol": "HTTP", "hub_id": HUB_ID},
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "port": controller.http_port})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 3
    assert entry.data["protocol"] == "http"
    assert entry.state is ConfigEntryState.LOADED


def test_hash_never_repeats() -> None:
    """Hashes are 7 digits and never the same twice in a row."""
    source = HashSource()
    with patch("custom_components.neosmartblinds.api.time.time", return_value=1234.5678):
        first = source.next()
        second = source.next()
    assert first == "1234567"
    assert second == "1234568"
    assert len(second) == 7


def test_code_validation() -> None:
    """Blind, room and motor codes are checked against Neo's ranges."""
    assert normalise_blind_code(" 021.230-04 ") == "021.230-04"
    assert normalise_blind_code("255.255-15") == "255.255-15"
    assert normalise_blind_code("021.230-00") == "021.230-00"
    assert normalise_blind_code("256.230-04") is None
    assert normalise_blind_code("021.230-16") is None
    assert normalise_blind_code("021.230.04") is None
    assert normalise_room_code("021.230-15") == "021.230-15"
    assert normalise_room_code("021.230-04") is None
    assert normalise_motor_code("BF") == "bf"
    assert normalise_motor_code("bf – Bofu (standard)") == "bf"
    assert normalise_motor_code("") == ""
    assert normalise_motor_code("abc") is None
