"""Fixtures for Neo Smart Blinds tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.neosmartblinds.const import DOMAIN

from .fake_controller import FakeController

HUB_ID = "A" * 24


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components in every test."""


@pytest.fixture(autouse=True)
def fast_pacing() -> Any:
    """Don't wait 0.7 s between commands in tests."""
    with patch("custom_components.neosmartblinds.const.COMMAND_SPACING", 0):
        yield


@pytest.fixture
async def controller(socket_enabled: None) -> AsyncGenerator[FakeController]:
    """Run a fake controller on localhost."""
    fake = FakeController(hub_id=HUB_ID)
    await fake.start()
    yield fake
    await fake.stop()


def blind_data(**overrides: Any) -> dict[str, Any]:
    """Return subentry data for a blind with defaults."""
    data: dict[str, Any] = {
        "blind_code": "021.230-04",
        "motor_code": "bf",
        "rail": 1,
        "tdbu_extended": False,
        "tilt": False,
        "percent_support": 0,
        "close_time": 20,
        "open_time": None,
        "startup_sync": "none",
        "start_position": None,
        "parent_group": "",
    }
    data.update(overrides)
    return data


def blind_subentry(title: str, **overrides: Any) -> dict[str, Any]:
    """Return subentry_data for MockConfigEntry."""
    data = blind_data(**overrides)
    return {
        "data": data,
        "subentry_type": "blind",
        "title": title,
        "unique_id": f"neosmartblinds.{data['blind_code']}.{data['motor_code']}.{data['rail']}",
    }


def make_entry(
    controller: FakeController,
    blinds: list[dict[str, Any]] | None = None,
    *,
    protocol: str = "http",
    options: dict[str, Any] | None = None,
    hub_id: str = HUB_ID,
) -> MockConfigEntry:
    """Build a controller entry pointing at the fake controller."""
    port = controller.http_port if protocol == "http" else controller.tcp_port
    unique_id = hub_id or "127.0.0.1"
    return MockConfigEntry(
        domain=DOMAIN,
        title="Neo Smart Controller (127.0.0.1)",
        unique_id=unique_id,
        version=1,
        minor_version=3,
        data={"host": "127.0.0.1", "protocol": protocol, "port": port, "hub_id": hub_id},
        options=options or {},
        subentries_data=blinds or [],
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Add and set up an entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def advance(hass: HomeAssistant, freezer: Any, seconds: float) -> None:
    """Move time forward and run timers that are due.

    Timers fire a few times so that timers started by other timers (such as
    the 250 ms room window after a timed stop) also run under frozen time.
    """
    freezer.tick(timedelta(seconds=seconds))
    for _ in range(4):
        async_fire_time_changed(hass, dt_util.utcnow())
        for _ in range(5):
            await asyncio.sleep(0)
    await hass.async_block_till_done()


async def run_frozen(hass: HomeAssistant, freezer: Any, coro: Any) -> None:
    """Run a service call that waits on the room window while time is frozen."""
    task = hass.async_create_task(coro)
    for _ in range(10):
        await asyncio.sleep(0)
    await advance(hass, freezer, 0.3)
    await task
