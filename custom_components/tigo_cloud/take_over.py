"""Take over the systems of the legacy Tigo integration (domain tigo).

Its entities move over with their entity ids, so their history, their statistics
and the energy dashboard carry on.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_RESTORED, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .const import CONF_SYSTEMID, DOMAIN, OLD_DOMAIN

_LOGGER = logging.getLogger(__name__)

# The unique ids of both integrations start with their domain and "tigo."
_OLD_PREFIX = OLD_DOMAIN + "tigo."
_NEW_PREFIX = DOMAIN + "tigo."
_SUMMARY = "summary."


def old_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return the entries of the legacy integration, not of others named tigo."""
    return [
        entry
        for entry in hass.config_entries.async_entries(OLD_DOMAIN, include_ignore=False)
        if {CONF_SYSTEMID, CONF_USERNAME, CONF_PASSWORD} <= entry.data.keys()
    ]


def _new_unique_id(unique_id: str, system_id: str) -> str | None:
    """Return the unique id of an entity of the legacy integration in this one."""
    if not unique_id.startswith(_OLD_PREFIX):
        return None
    key = unique_id.removeprefix(_OLD_PREFIX)
    if key.startswith(_SUMMARY):
        # The legacy integration had a single system, so its summary ids lack it
        key = _SUMMARY + system_id + "." + key.removeprefix(_SUMMARY)
    return _NEW_PREFIX + key


async def async_take_over(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move the entities of the legacy integration's system to entry.

    Its entry is removed afterwards. If entities of the system exist here already,
    e.g. as the system was added again by hand, nothing is moved and a repair issue
    tells the user.
    """
    system_id = entry.data[CONF_SYSTEMID]
    issue_id = f"take_over_{system_id}"
    registry = er.async_get(hass)
    for old in old_entries(hass):
        if old.data[CONF_SYSTEMID] != system_id:
            continue

        moves = [
            (entity, _new_unique_id(entity.unique_id, system_id))
            for entity in er.async_entries_for_config_entry(registry, old.entry_id)
        ]
        if clashes := [
            entity.entity_id
            for entity, unique_id in moves
            if unique_id is None
            or registry.async_get_entity_id(entity.domain, DOMAIN, unique_id)
        ]:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="take_over_clash",
                translation_placeholders={
                    CONF_SYSTEMID: system_id,
                    "entities": ", ".join(clashes),
                },
            )
            continue

        if old.state in (
            ConfigEntryState.SETUP_IN_PROGRESS,
            ConfigEntryState.UNLOAD_IN_PROGRESS,
        ):
            # Both integrations start at the same time; retried shortly
            raise ConfigEntryNotReady(f"Waiting for the {OLD_DOMAIN} integration")
        if old.state.recoverable:
            # Entities can only move while they are not loaded
            await hass.config_entries.async_unload(old.entry_id)

        for entity, unique_id in moves:
            # Unloaded entities leave an unavailable placeholder, which blocks the move
            state = hass.states.get(entity.entity_id)
            if state is not None and state.attributes.get(ATTR_RESTORED):
                hass.states.async_remove(entity.entity_id)
            try:
                registry.async_update_entity_platform(
                    entity.entity_id,
                    DOMAIN,
                    new_config_entry_id=entry.entry_id,
                    new_unique_id=unique_id,
                )
            except ValueError as err:
                # The moved entities stay moved, the retry continues with the others
                raise ConfigEntryNotReady(
                    f"Cannot take over {entity.entity_id}: {err}"
                ) from err

        await hass.config_entries.async_remove(old.entry_id)
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        _LOGGER.info(
            "Took over system %s with %d entities from the %s integration",
            system_id,
            len(moves),
            OLD_DOMAIN,
        )
