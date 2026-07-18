"""UI configuration for Free Library Events."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)

from .config import BRANCH_CONFIG_KEYS, default_config, entry_config, normalize_config
from .const import (
    CONF_BIRTH_DATE,
    CONF_CALENDAR_DURATION,
    CONF_CHILD_NAME,
    CONF_FILTER_MODE,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    MAX_CALENDAR_DURATION,
    MAX_SCAN_INTERVAL,
    MIN_CALENDAR_DURATION,
    MIN_SCAN_INTERVAL,
    NAME,
)
from .digest import FILTER_MODES


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    birth_date_key = (
        vol.Required(CONF_BIRTH_DATE, default=defaults[CONF_BIRTH_DATE])
        if CONF_BIRTH_DATE in defaults
        else vol.Required(CONF_BIRTH_DATE)
    )
    branch_fields = {
        vol.Required(config_key, default=defaults[config_key]): BooleanSelector()
        for config_key, _ in BRANCH_CONFIG_KEYS
    }
    return vol.Schema(
        {
            vol.Required(
                CONF_CHILD_NAME, default=defaults[CONF_CHILD_NAME]
            ): TextSelector(),
            birth_date_key: DateSelector(),
            **branch_fields,
            vol.Required(
                CONF_FILTER_MODE, default=defaults[CONF_FILTER_MODE]
            ): SelectSelector(SelectSelectorConfig(options=list(FILTER_MODES))),
            vol.Required(
                CONF_CALENDAR_DURATION,
                default=defaults[CONF_CALENDAR_DURATION],
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_CALENDAR_DURATION,
                    max=MAX_CALENDAR_DURATION,
                    step=15,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults[CONF_SCAN_INTERVAL],
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=900,
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


class FreeLibraryEventsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle setup from Home Assistant's integration UI."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""

        return FreeLibraryEventsOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the single integration entry."""

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = normalize_config(user_input)
            except (TypeError, ValueError) as err:
                errors["base"] = str(err) or "invalid_config"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=NAME,
                    data=data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema({**default_config(), **(user_input or {})}),
            errors=errors,
        )


class FreeLibraryEventsOptionsFlow(config_entries.OptionsFlowWithReload):
    """Edit every user-facing integration setting and reload on save."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""

        errors: dict[str, str] = {}
        current = entry_config(self.config_entry.data, self.config_entry.options)
        if user_input is not None:
            try:
                options = normalize_config(user_input)
            except (TypeError, ValueError) as err:
                errors["base"] = str(err) or "invalid_config"
            else:
                return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=_schema({**current, **(user_input or {})}),
            errors=errors,
        )
