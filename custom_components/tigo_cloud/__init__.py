"""The init."""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_SYSTEMID, DOMAIN
from .take_over import async_take_over
from .tigo import TigoConfigEntry, TigoCoordinator, TigoData, create_session

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: TigoConfigEntry) -> bool:
    """Set up the element."""
    system_id = entry.data[CONF_SYSTEMID]
    # Entries from before the config flow set a unique id; backfill it unless it would clash
    if entry.unique_id is None and not hass.config_entries.async_entry_for_domain_unique_id(
        DOMAIN, system_id
    ):
        hass.config_entries.async_update_entry(entry, unique_id=system_id)

    # Before the sensors are added, so they continue the legacy integration's ones
    await async_take_over(hass, entry)

    data = TigoData(
        create_session(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        system_id,
    )
    coordinator = TigoCoordinator(hass, entry, data)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Add entities
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: TigoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
