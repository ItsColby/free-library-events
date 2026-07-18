"""Shared entities for Free Library Events."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import DOMAIN, NAME


def service_device_info() -> DeviceInfo:
    """Return the single user-facing service device."""

    return DeviceInfo(
        identifiers={(DOMAIN, DOMAIN)},
        name=NAME,
        manufacturer="Free Library of Philadelphia",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://libwww.freelibrary.org/calendar/",
    )
