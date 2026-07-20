"""UI configuration for Free Library Events."""

from __future__ import annotations

from secrets import token_urlsafe
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
    SelectSelectorMode,
    TextSelector,
)

from .config import (
    default_config,
    entry_options,
    entry_profile,
    normalize_options,
    profile_entry_data,
)
from .const import (
    CONF_BIRTH_DATE,
    CONF_BRANCHES,
    CONF_CALENDAR_DURATION,
    CONF_CHILD_NAME,
    CONF_FILTER_MODE,
    CONF_PUBLISH_WEBCAL,
    CONF_SCAN_INTERVAL,
    CONF_WEBCAL_NAME,
    CONF_WEBCAL_TOKEN,
    DEFAULT_WEBCAL_NAME,
    DOMAIN,
    MAX_CALENDAR_DURATION,
    MAX_SCAN_INTERVAL,
    MIN_CALENDAR_DURATION,
    MIN_SCAN_INTERVAL,
    NAME,
)
from .digest import BRANCHES, FILTER_MODES
from .webcal import webcal_status, webcal_subscription_urls


def _profile_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Return required profile and source-selection fields."""

    birth_date_key = (
        vol.Required(CONF_BIRTH_DATE, default=defaults[CONF_BIRTH_DATE])
        if CONF_BIRTH_DATE in defaults
        else vol.Required(CONF_BIRTH_DATE)
    )
    child_name_key = (
        vol.Required(CONF_CHILD_NAME, default=defaults[CONF_CHILD_NAME])
        if CONF_CHILD_NAME in defaults
        else vol.Required(CONF_CHILD_NAME)
    )
    return vol.Schema(
        {
            child_name_key: TextSelector(),
            birth_date_key: DateSelector(),
            vol.Required(
                CONF_BRANCHES, default=defaults[CONF_BRANCHES]
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": code, "label": branch.name}
                        for code, branch in BRANCHES.items()
                    ],
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _behavior_schema(defaults: dict[str, Any], *, advanced: bool) -> vol.Schema:
    """Return ordinary behavior fields plus opt-in advanced tuning."""

    fields: dict[vol.Marker, object] = {
        vol.Required(
            CONF_FILTER_MODE, default=defaults[CONF_FILTER_MODE]
        ): SelectSelector(SelectSelectorConfig(options=list(FILTER_MODES))),
    }
    if advanced:
        fields.update(
            {
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
    return vol.Schema(fields)


def _webcal_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Return WebCal publication fields without exposing the token."""

    return vol.Schema(
        {
            vol.Required(
                CONF_PUBLISH_WEBCAL,
                default=bool(defaults.get(CONF_PUBLISH_WEBCAL, False)),
            ): BooleanSelector(),
            vol.Required(
                CONF_WEBCAL_NAME,
                default=defaults.get(CONF_WEBCAL_NAME, DEFAULT_WEBCAL_NAME),
            ): TextSelector(),
        }
    )


class FreeLibraryEventsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle setup from Home Assistant's integration UI."""

    VERSION = 1
    MINOR_VERSION = 2

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
                data = profile_entry_data(user_input)
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
            data_schema=_profile_schema({**default_config(), **(user_input or {})}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update required profile and branch-selection data."""

        entry = self._get_reconfigure_entry()
        current = entry_profile(entry.data, entry.options)
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                profile = profile_entry_data(user_input)
            except (TypeError, ValueError) as err:
                errors["base"] = str(err) or "invalid_config"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data=profile,
                    reason="reconfigure_successful",
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_profile_schema({**current, **(user_input or {})}),
            errors=errors,
        )


class FreeLibraryEventsOptionsFlow(config_entries.OptionsFlowWithReload):
    """Manage optional behavior and calendar publication."""

    _pending_options: dict[str, Any] | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""

        del user_input
        current = entry_options(self.config_entry.data, self.config_entry.options)
        menu_options = ["behavior", "webcal"]
        if current[CONF_PUBLISH_WEBCAL] and current.get(CONF_WEBCAL_TOKEN):
            menu_options.append("regenerate_webcal")
        return self.async_show_menu(
            step_id="init",
            menu_options=menu_options,
            description_placeholders={
                "webcal_status": webcal_status(
                    self.hass,
                    bool(current[CONF_PUBLISH_WEBCAL]),
                    current.get(CONF_WEBCAL_TOKEN),
                )
            },
        )

    async def async_step_behavior(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit filtering plus optional advanced timing controls."""

        current = entry_options(self.config_entry.data, self.config_entry.options)
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                options = normalize_options({**current, **user_input})
            except (TypeError, ValueError) as err:
                errors["base"] = str(err) or "invalid_config"
            else:
                return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="behavior",
            data_schema=_behavior_schema(
                {**current, **(user_input or {})},
                advanced=self.show_advanced_options,
            ),
            errors=errors,
        )

    async def async_step_webcal(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enable, disable, or rename the private calendar feed."""

        current = entry_options(self.config_entry.data, self.config_entry.options)
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                options = normalize_options({**current, **user_input})
            except (TypeError, ValueError) as err:
                errors["base"] = str(err) or "invalid_config"
            else:
                if not options[CONF_PUBLISH_WEBCAL]:
                    return self.async_create_entry(data=options)
                if not options.get(CONF_WEBCAL_TOKEN):
                    options[CONF_WEBCAL_TOKEN] = token_urlsafe(32)
                self._pending_options = options
                return await self.async_step_webcal_url()

        return self.async_show_form(
            step_id="webcal",
            data_schema=_webcal_schema({**current, **(user_input or {})}),
            errors=errors,
            description_placeholders={
                "webcal_status": webcal_status(
                    self.hass,
                    bool(current[CONF_PUBLISH_WEBCAL]),
                    current.get(CONF_WEBCAL_TOKEN),
                )
            },
        )

    async def async_step_regenerate_webcal(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm invalidation and replace the private feed token."""

        current = entry_options(self.config_entry.data, self.config_entry.options)
        if not current[CONF_PUBLISH_WEBCAL] or not current.get(CONF_WEBCAL_TOKEN):
            return await self.async_step_webcal()
        if user_input is not None:
            current[CONF_WEBCAL_TOKEN] = token_urlsafe(32)
            self._pending_options = current
            return await self.async_step_webcal_url()
        return self.async_show_form(
            step_id="regenerate_webcal",
            data_schema=vol.Schema({}),
        )

    async def async_step_webcal_url(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Display both subscription URL schemes before saving."""

        if self._pending_options is None:
            return await self.async_step_init()
        if user_input is not None:
            return self.async_create_entry(data=self._pending_options)
        token = self._pending_options[CONF_WEBCAL_TOKEN]
        urls = webcal_subscription_urls(self.hass, token)
        return self.async_show_form(
            step_id="webcal_url",
            data_schema=vol.Schema({}),
            description_placeholders={
                "http_url": urls.http_url,
                "webcal_url": urls.webcal_url,
                "url_scope": (
                    "Home Assistant external or cloud URL configured"
                    if urls.external_url_configured
                    else "Only a Home Assistant internal URL is configured"
                ),
            },
        )
