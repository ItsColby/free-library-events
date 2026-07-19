"""Config-entry normalization for Free Library Events."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

import voluptuous as vol

from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BIRTH_DATE,
    CONF_CALENDAR_DURATION,
    CONF_CHILD_NAME,
    CONF_FILTER_MODE,
    CONF_INCLUDE_INDEPENDENCE,
    CONF_INCLUDE_PARKWAY_CENTRAL,
    CONF_INCLUDE_PCI,
    CONF_INCLUDE_SANTORE,
    CONF_SCAN_INTERVAL,
    DEFAULT_CALENDAR_DURATION,
    DEFAULT_CHILD_NAME,
    DEFAULT_FILTER_MODE,
    DEFAULT_INCLUDE_INDEPENDENCE,
    DEFAULT_INCLUDE_PARKWAY_CENTRAL,
    DEFAULT_INCLUDE_PCI,
    DEFAULT_INCLUDE_SANTORE,
    DEFAULT_SCAN_INTERVAL,
    MAX_CALENDAR_DURATION,
    MAX_SCAN_INTERVAL,
    MIN_CALENDAR_DURATION,
    MIN_SCAN_INTERVAL,
)
from .digest import BRANCHES, FILTER_MODES, Branch, normalize_child_name


BRANCH_CONFIG_KEYS = (
    (CONF_INCLUDE_SANTORE, "SWK"),
    (CONF_INCLUDE_INDEPENDENCE, "IND"),
    (CONF_INCLUDE_PARKWAY_CENTRAL, "CEN"),
    (CONF_INCLUDE_PCI, "PCI"),
)


def default_config() -> dict[str, Any]:
    """Return user-facing defaults."""

    return {
        CONF_CHILD_NAME: DEFAULT_CHILD_NAME,
        CONF_INCLUDE_SANTORE: DEFAULT_INCLUDE_SANTORE,
        CONF_INCLUDE_INDEPENDENCE: DEFAULT_INCLUDE_INDEPENDENCE,
        CONF_INCLUDE_PARKWAY_CENTRAL: DEFAULT_INCLUDE_PARKWAY_CENTRAL,
        CONF_INCLUDE_PCI: DEFAULT_INCLUDE_PCI,
        CONF_FILTER_MODE: DEFAULT_FILTER_MODE,
        CONF_CALENDAR_DURATION: DEFAULT_CALENDAR_DURATION,
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
    }


def normalize_config(values: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize selector output to stable JSON-compatible config data."""

    config = {**default_config(), **dict(values)}
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
        branch_values = {
            key: cv.boolean(config[key]) for key, _branch_code in BRANCH_CONFIG_KEYS
        }
    except (TypeError, ValueError, vol.Invalid) as err:
        raise ValueError("invalid_config") from err
    if birth_date > dt_util.now().date():
        raise ValueError("birth_date_in_future")
    if not any(branch_values.values()):
        raise ValueError("branch_required")
    if filter_mode not in FILTER_MODES:
        raise ValueError("invalid_filter_mode")
    if not MIN_CALENDAR_DURATION <= calendar_duration <= MAX_CALENDAR_DURATION:
        raise ValueError("invalid_calendar_duration")
    if not MIN_SCAN_INTERVAL <= scan_interval <= MAX_SCAN_INTERVAL:
        raise ValueError("invalid_scan_interval")

    return {
        CONF_CHILD_NAME: child_name,
        CONF_BIRTH_DATE: birth_date.isoformat(),
        CONF_INCLUDE_SANTORE: branch_values[CONF_INCLUDE_SANTORE],
        CONF_INCLUDE_INDEPENDENCE: branch_values[CONF_INCLUDE_INDEPENDENCE],
        CONF_INCLUDE_PARKWAY_CENTRAL: branch_values[CONF_INCLUDE_PARKWAY_CENTRAL],
        CONF_INCLUDE_PCI: branch_values[CONF_INCLUDE_PCI],
        CONF_FILTER_MODE: filter_mode,
        CONF_CALENDAR_DURATION: calendar_duration,
        CONF_SCAN_INTERVAL: scan_interval,
    }


def entry_config(
    entry_data: Mapping[str, Any], entry_options: Mapping[str, Any]
) -> dict[str, Any]:
    """Return effective entry config, with options overriding initial data."""

    return normalize_config({**dict(entry_data), **dict(entry_options)})


def selected_branches(config: Mapping[str, Any]) -> tuple[Branch, ...]:
    """Return configured branches in stable display order."""

    return tuple(
        BRANCHES[branch_code]
        for config_key, branch_code in BRANCH_CONFIG_KEYS
        if config[config_key]
    )
