"""Tests for importing the old YAML set-up."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component

from custom_components.neosmartblinds.const import DOMAIN

from .conftest import HUB_ID, blind_subentry, make_entry
from .fake_controller import FakeController


def _yaml(controller: FakeController, **overrides) -> dict:
    config = {
        "platform": DOMAIN,
        "host": "127.0.0.1",
        "name": "Front blind",
        "blind_code": "021.230-04",
        "close_time": 20,
        "hub_id": HUB_ID,
        "protocol": "http",
        "port": controller.http_port,
        "rail": 1,
        "percent_support": 0,
        "motor_code": "bf",
    }
    config.update(overrides)
    return config


async def _setup_yaml(hass: HomeAssistant, entries: list[dict]) -> None:
    assert await async_setup_component(hass, "cover", {"cover": entries})
    await hass.async_block_till_done()
    await hass.async_block_till_done()


async def test_import_creates_entry_and_keeps_entities(
    hass: HomeAssistant, controller: FakeController
) -> None:
    """One entry per controller, a subentry per blind, same entity and area."""
    area = ar.async_get(hass).async_create("Lounge")
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "cover", DOMAIN, "neosmartblinds.021.230-04.bf.1", suggested_object_id="old_front"
    )
    registry.async_update_entity(old.entity_id, area_id=area.id)

    await _setup_yaml(
        hass,
        [
            _yaml(controller, start_position=30, parent_group="021.230-15"),
            _yaml(
                controller,
                name="Side blind",
                blind_code="021.230-05",
                motor_code=None,
                percent_support=2,
                parent_group="021.230-15",
            ),
        ],
    )
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.unique_id == HUB_ID
    assert entry.title == "Neo Smart Controller (127.0.0.1)"
    assert entry.data == {
        "host": "127.0.0.1",
        "protocol": "http",
        "port": controller.http_port,
        "hub_id": HUB_ID,
    }
    subentries = {s.unique_id: s for s in entry.subentries.values()}
    assert set(subentries) == {
        "neosmartblinds.021.230-04.bf.1",
        "neosmartblinds.021.230-05..1",
    }
    front = subentries["neosmartblinds.021.230-04.bf.1"]
    assert front.title == "Front blind"
    assert front.data["tilt"] is False
    assert front.data["startup_sync"] == "none"
    assert front.data["start_position"] == 30
    assert front.data["parent_group"] == "021.230-15"

    entity = registry.async_get("cover.old_front")
    assert entity is not None
    assert entity.id == old.id
    assert entity.config_entry_id == entry.entry_id
    assert entity.config_subentry_id == front.subentry_id
    assert hass.states.get("cover.old_front") is not None
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device.area_id == area.id
    assert hass.states.get("cover.side_blind") is not None

    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, "deprecated_yaml") is not None


async def test_import_into_existing_entry(hass: HomeAssistant, controller: FakeController) -> None:
    """Missing blinds are added to an existing entry; existing ones are skipped."""
    # Home Assistant reads the YAML when it starts, with the entry already there.
    entry = make_entry(controller, [blind_subentry("Front")])
    entry.add_to_hass(hass)
    await _setup_yaml(
        hass,
        [
            _yaml(controller, name="Duplicate"),
            _yaml(controller, name="Back blind", blind_code="021.230-06"),
        ],
    )
    await hass.async_block_till_done()
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    titles = sorted(s.title for s in entry.subentries.values())
    assert titles == ["Back blind", "Front"]
    assert hass.states.get("cover.back_blind") is not None


async def test_import_tcp_any_case(hass: HomeAssistant, controller: FakeController) -> None:
    """Protocol may be any case; without an ID the host is the unique ID."""
    config = _yaml(controller, protocol="TCP", port=controller.tcp_port)
    config.pop("hub_id")
    await _setup_yaml(hass, [config])
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == "127.0.0.1"
    assert entry.data["protocol"] == "tcp"
    assert entry.data["hub_id"] == ""


async def test_import_defaults(hass: HomeAssistant, controller: FakeController) -> None:
    """Missing values take the old defaults."""
    config = {
        "platform": DOMAIN,
        "host": "127.0.0.1",
        "name": "Plain",
        "blind_code": "021.230-04",
        "hub_id": HUB_ID,
    }
    await _setup_yaml(hass, [config])
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data["port"] == 8838
    assert entry.data["protocol"] == "http"
    data = next(iter(entry.subentries.values())).data
    assert data["close_time"] == 20
    assert data["rail"] == 1
    assert data["percent_support"] == 0
    assert data["motor_code"] == ""


async def test_import_failure_issue(hass: HomeAssistant, controller: FakeController) -> None:
    """A bad entry raises a repair issue naming it and the reason."""
    await _setup_yaml(
        hass,
        [
            _yaml(controller, name="Broken", blind_code="21-230-04"),
            _yaml(controller, name="Good"),
        ],
    )
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "yaml_import_failed_broken")
    assert issue is not None
    assert issue.translation_key == "yaml_import_failed"
    assert issue.translation_placeholders["name"] == "Broken"
    assert "blind code" in issue.translation_placeholders["reason"]
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert [s.title for s in entry.subentries.values()] == ["Good"]


async def test_import_missing_hub_id_for_http(
    hass: HomeAssistant, controller: FakeController
) -> None:
    """HTTP without a controller ID can't be imported."""
    config = _yaml(controller, name="No id")
    config.pop("hub_id")
    await _setup_yaml(hass, [config])
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "yaml_import_failed_no_id")
    assert issue is not None
    assert not hass.config_entries.async_entries(DOMAIN)
