"""Tests for taking over the systems of the legacy Tigo integration."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from custom_components.tigo_cloud.const import DOMAIN, OLD_DOMAIN

SYSTEM = "12345"
LOGIN = {"systemid": SYSTEM, "username": "me@example.com", "password": "secret"}


def add_old_system(hass: HomeAssistant) -> tuple[MockConfigEntry, str, str]:
    """Add a system of the legacy integration, with a panel and a summary sensor."""
    old = MockConfigEntry(domain=OLD_DOMAIN, data=LOGIN, title=f"Tigo Cloud {SYSTEM}")
    old.add_to_hass(hass)
    registry = er.async_get(hass)
    power = registry.async_get_or_create(
        "sensor",
        OLD_DOMAIN,
        "tigotigo.T1_pin",
        config_entry=old,
        suggested_object_id="a1_power",
    )
    day = registry.async_get_or_create(
        "sensor",
        OLD_DOMAIN,
        "tigotigo.summary.day",
        config_entry=old,
        suggested_object_id="daily_production",
    )
    return old, power.entity_id, day.entity_id


@pytest.mark.usefixtures("tigo")
async def test_take_over(hass: HomeAssistant) -> None:
    """The sensors of the legacy integration carry on with their entity ids."""
    old, power_id, day_id = add_old_system(hass)
    registry = er.async_get(hass)
    registry.async_update_entity(power_id, name="Roof A1")
    # What Home Assistant shows for registered entities that are not loaded
    hass.states.async_set(power_id, "unavailable", {"restored": True})
    other = MockConfigEntry(domain=OLD_DOMAIN, data={**LOGIN, "systemid": "999"})
    other.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, data=LOGIN, unique_id=SYSTEM, title=f"Tigo Cloud {SYSTEM}"
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.config_entries.async_get_entry(old.entry_id) is None
    assert hass.config_entries.async_get_entry(other.entry_id) is not None
    power = registry.async_get(power_id)
    assert power is not None
    assert power.platform == DOMAIN
    assert power.unique_id == "tigo_cloudtigo.T1_pin"
    assert power.config_entry_id == entry.entry_id
    assert power.name == "Roof A1"
    day = registry.async_get(day_id)
    assert day is not None
    assert day.platform == DOMAIN
    assert day.unique_id == f"tigo_cloudtigo.summary.{SYSTEM}.day"
    # The sensors write to the entities taken over
    assert hass.states.get(power_id).state == "100"
    assert hass.states.get(day_id).state == "2000"


@pytest.mark.usefixtures("tigo")
async def test_take_over_clash(hass: HomeAssistant) -> None:
    """Nothing is taken over if this integration has sensors of the system already."""
    old, power_id, day_id = add_old_system(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=LOGIN, unique_id=SYSTEM)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    new_power = registry.async_get_or_create(
        "sensor", DOMAIN, "tigo_cloudtigo.T1_pin", config_entry=entry
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.config_entries.async_get_entry(old.entry_id) is not None
    assert registry.async_get(power_id).platform == OLD_DOMAIN
    assert registry.async_get(day_id).platform == OLD_DOMAIN
    assert hass.states.get(new_power.entity_id).state == "100"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"take_over_{SYSTEM}")


@pytest.mark.usefixtures("tigo")
async def test_discovery(hass: HomeAssistant) -> None:
    """A system offered by the legacy integration is taken over on confirmation."""
    old, power_id, _ = add_old_system(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY}, data=dict(old.data)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "take_over"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == LOGIN
    assert hass.config_entries.async_get_entry(old.entry_id) is None
    assert er.async_get(hass).async_get(power_id).config_entry_id == (
        result["result"].entry_id
    )


async def test_discovery_configured(hass: HomeAssistant) -> None:
    """A system set up already is not offered."""
    MockConfigEntry(domain=DOMAIN, data=LOGIN, unique_id=SYSTEM).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_INTEGRATION_DISCOVERY}, data=LOGIN
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_suggests_old_system(hass: HomeAssistant) -> None:
    """Adding the integration suggests the login of the legacy integration."""
    add_old_system(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    suggested = {
        key.schema: key.description["suggested_value"]
        for key in result["data_schema"].schema
    }
    assert suggested == LOGIN
