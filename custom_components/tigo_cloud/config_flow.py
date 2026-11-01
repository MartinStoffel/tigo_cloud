"""Config flow for Tigo cloud Sensor integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.typing import DiscoveryInfoType

from .const import CONF_SYSTEMID, DOMAIN
from .take_over import old_entries
from .tigo import TigoAuthError, TigoData, TigoError, TigoSystemError, create_session

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SYSTEMID): str,
        vol.Required(CONF_USERNAME): str,
        # Masked, as it is filled in when taking over the legacy integration
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)
STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def validate_input(hass: HomeAssistant, data: Mapping[str, Any]) -> dict[str, str]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    Returns the form errors, empty if the input works.
    """
    tigo = TigoData(
        create_session(hass), data[CONF_USERNAME], data[CONF_PASSWORD], data[CONF_SYSTEMID]
    )
    try:
        await tigo.async_get_panels()
    except TigoAuthError:
        return {"base": "invalid_auth"}
    except TigoSystemError:
        return {"base": "invalid_system"}
    except TigoError as err:
        _LOGGER.warning("Cannot connect to Tigo: %s", err)
        return {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected exception")
        return {"base": "unknown"}
    return {}


class TigoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tigo Cloud Sensor."""

    VERSION = 1

    _take_over_data: dict[str, Any]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        schema = STEP_USER_DATA_SCHEMA
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_SYSTEMID])
            self._abort_if_unique_id_configured()
            errors = await validate_input(self.hass, user_input)
            if not errors:
                return self.async_create_entry(
                    title=f"Tigo Cloud {user_input[CONF_SYSTEMID]}", data=user_input
                )
        else:
            # Suggest a system of the legacy integration that is not taken over yet
            configured = self._async_current_ids()
            if old := next(
                (e for e in old_entries(self.hass) if e.data[CONF_SYSTEMID] not in configured),
                None,
            ):
                schema = self.add_suggested_values_to_schema(schema, old.data)

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_integration_discovery(
        self, discovery_info: DiscoveryInfoType
    ) -> ConfigFlowResult:
        """Offer to take over a system of the legacy integration."""
        system_id = discovery_info[CONF_SYSTEMID]
        await self.async_set_unique_id(system_id)
        self._abort_if_unique_id_configured()
        self._take_over_data = {
            key: discovery_info[key] for key in (CONF_SYSTEMID, CONF_USERNAME, CONF_PASSWORD)
        }
        self.context["title_placeholders"] = {CONF_SYSTEMID: system_id}
        return await self.async_step_take_over()

    async def async_step_take_over(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm taking over the system, with the login of the legacy integration.

        Not validated: should the login fail, the reauth flow asks for the password.
        """
        system_id = self._take_over_data[CONF_SYSTEMID]
        if user_input is not None:
            return self.async_create_entry(
                title=f"Tigo Cloud {system_id}", data=self._take_over_data
            )

        return self.async_show_form(
            step_id="take_over", description_placeholders={CONF_SYSTEMID: system_id}
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a rejected login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            errors = await validate_input(self.hass, {**entry.data, **user_input})
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={CONF_USERNAME: entry.data[CONF_USERNAME]},
            errors=errors,
        )
