"""Config-entry normalization for Free Library Events."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

import voluptuous as vol

from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BIRTH_DATE,
    CONF_BRANCHES,
    CONF_CALENDAR_DURATION,
    CONF_CHILD_NAME,
    CONF_FILTER_MODE,
    CONF_INCLUDE_INDEPENDENCE,
    CONF_INCLUDE_PARKWAY_CENTRAL,
    CONF_INCLUDE_PCI,
    CONF_INCLUDE_SANTORE,
    CONF_PUBLISH_WEBCAL,
    CONF_SCAN_INTERVAL,
    CONF_WEBCAL_NAME,
    CONF_WEBCAL_TOKEN,
    DEFAULT_CALENDAR_DURATION,
    DEFAULT_CHILD_NAME,
    DEFAULT_FILTER_MODE,
    DEFAULT_INCLUDE_INDEPENDENCE,
    DEFAULT_INCLUDE_PARKWAY_CENTRAL,
    DEFAULT_INCLUDE_PCI,
    DEFAULT_INCLUDE_SANTORE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WEBCAL_NAME,
    MAX_CALENDAR_DURATION,
    MAX_SCAN_INTERVAL,
    MAX_WEBCAL_NAME_LENGTH,
    MIN_CALENDAR_DURATION,
    MIN_SCAN_INTERVAL,
)
from .digest import BRANCHES, FILTER_MODES, Branch, normalize_child_name


LEGACY_BRANCH_CONFIG_KEYS = (
    (CONF_INCLUDE_SANTORE, "SWK"),
    (CONF_INCLUDE_INDEPENDENCE, "IND"),
    (CONF_INCLUDE_PARKWAY_CENTRAL, "CEN"),
    (CONF_INCLUDE_PCI, "PCI"),
)


def default_config() -> dict[str, Any]:
    """Return the complete safe runtime defaults."""

    return {
        CONF_CHILD_NAME: DEFAULT_CHILD_NAME,
        CONF_BRANCHES: list(BRANCHES),
        CONF_FILTER_MODE: DEFAULT_FILTER_MODE,
        CONF_CALENDAR_DURATION: DEFAULT_CALENDAR_DURATION,
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_PUBLISH_WEBCAL: False,
        CONF_WEBCAL_NAME: DEFAULT_WEBCAL_NAME,
    }


def normalize_profile(values: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize required profile and source-selection config-entry data."""

    config = {CONF_CHILD_NAME: DEFAULT_CHILD_NAME, **dict(values)}
    if CONF_BIRTH_DATE not in config:
        raise ValueError("birth_date_required")
    child_name = normalize_child_name(config[CONF_CHILD_NAME])
    birth_value = config[CONF_BIRTH_DATE]
    try:
        birth_date = (
            birth_value
            if isinstance(birth_value, date)
            else date.fromisoformat(str(birth_value))
        )
    except (TypeError, ValueError) as err:
        raise ValueError("invalid_birth_date") from err
    branch_codes = _normalize_branch_codes(config)
    if birth_date > dt_util.now().date():
        raise ValueError("birth_date_in_future")
    if not branch_codes:
        raise ValueError("branch_required")

    return {
        CONF_CHILD_NAME: child_name,
        CONF_BIRTH_DATE: birth_date.isoformat(),
        CONF_BRANCHES: list(branch_codes),
    }


def normalize_options(values: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize optional behavior and WebCal settings."""

    config = {
        CONF_FILTER_MODE: DEFAULT_FILTER_MODE,
        CONF_CALENDAR_DURATION: DEFAULT_CALENDAR_DURATION,
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_PUBLISH_WEBCAL: False,
        CONF_WEBCAL_NAME: DEFAULT_WEBCAL_NAME,
        **dict(values),
    }
    filter_mode = str(config[CONF_FILTER_MODE])
    try:
        calendar_duration = int(config[CONF_CALENDAR_DURATION])
    except (TypeError, ValueError) as err:
        raise ValueError("invalid_calendar_duration") from err
    try:
        scan_interval = int(config[CONF_SCAN_INTERVAL])
    except (TypeError, ValueError) as err:
        raise ValueError("invalid_scan_interval") from err
    try:
        publish_webcal = cv.boolean(config[CONF_PUBLISH_WEBCAL])
    except (TypeError, ValueError, vol.Invalid) as err:
        raise ValueError("invalid_config") from err
    webcal_name = config[CONF_WEBCAL_NAME]
    if not isinstance(webcal_name, str):
        raise ValueError("invalid_webcal_name")
    webcal_name = " ".join(webcal_name.split())
    if not webcal_name or len(webcal_name) > MAX_WEBCAL_NAME_LENGTH:
        raise ValueError("invalid_webcal_name")
    if filter_mode not in FILTER_MODES:
        raise ValueError("invalid_filter_mode")
    if not MIN_CALENDAR_DURATION <= calendar_duration <= MAX_CALENDAR_DURATION:
        raise ValueError("invalid_calendar_duration")
    if not MIN_SCAN_INTERVAL <= scan_interval <= MAX_SCAN_INTERVAL:
        raise ValueError("invalid_scan_interval")

    options = {
        CONF_FILTER_MODE: filter_mode,
        CONF_CALENDAR_DURATION: calendar_duration,
        CONF_SCAN_INTERVAL: scan_interval,
        CONF_PUBLISH_WEBCAL: publish_webcal,
        CONF_WEBCAL_NAME: webcal_name,
    }
    token = config.get(CONF_WEBCAL_TOKEN)
    if publish_webcal and isinstance(token, str) and token:
        options[CONF_WEBCAL_TOKEN] = token
    return options


def normalize_config(values: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize legacy or combined values to the safe runtime config."""

    return entry_config(values, {})


def entry_profile(
    entry_data: Mapping[str, Any], entry_option_values: Mapping[str, Any]
) -> dict[str, Any]:
    """Return profile data, honoring legacy version-1 options overrides."""

    return normalize_profile({**dict(entry_data), **dict(entry_option_values)})


def entry_options(
    entry_data: Mapping[str, Any], entry_option_values: Mapping[str, Any]
) -> dict[str, Any]:
    """Return optional behavior, honoring legacy version-1 data fields."""

    return normalize_options({**dict(entry_data), **dict(entry_option_values)})


def entry_config(
    entry_data: Mapping[str, Any], entry_option_values: Mapping[str, Any]
) -> dict[str, Any]:
    """Return effective entry config, with options overriding initial data."""

    profile = entry_profile(entry_data, entry_option_values)
    options = entry_options(entry_data, entry_option_values)
    options.pop(CONF_WEBCAL_TOKEN, None)
    return {**profile, **options}


def migrated_entry_config(
    entry_data: Mapping[str, Any], entry_option_values: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a version-1 combined entry into version-2 data and options."""

    return (
        entry_profile(entry_data, entry_option_values),
        entry_options(entry_data, entry_option_values),
    )


def selected_branches(config: Mapping[str, Any]) -> tuple[Branch, ...]:
    """Return configured branches in stable display order."""

    return tuple(BRANCHES[branch_code] for branch_code in config[CONF_BRANCHES])


def _normalize_branch_codes(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Return valid selected branch codes from current or legacy fields."""

    if CONF_BRANCHES in config:
        raw_codes = config[CONF_BRANCHES]
        if isinstance(raw_codes, str) or not isinstance(raw_codes, (list, tuple, set)):
            raise ValueError("invalid_branches")
        requested = {str(code) for code in raw_codes}
        if requested - BRANCHES.keys():
            raise ValueError("invalid_branches")
        return tuple(code for code in BRANCHES if code in requested)

    legacy_defaults = {
        CONF_INCLUDE_SANTORE: DEFAULT_INCLUDE_SANTORE,
        CONF_INCLUDE_INDEPENDENCE: DEFAULT_INCLUDE_INDEPENDENCE,
        CONF_INCLUDE_PARKWAY_CENTRAL: DEFAULT_INCLUDE_PARKWAY_CENTRAL,
        CONF_INCLUDE_PCI: DEFAULT_INCLUDE_PCI,
    }
    try:
        return tuple(
            branch_code
            for config_key, branch_code in LEGACY_BRANCH_CONFIG_KEYS
            if cv.boolean(config.get(config_key, legacy_defaults[config_key]))
        )
    except (TypeError, ValueError, vol.Invalid) as err:
        raise ValueError("invalid_config") from err
