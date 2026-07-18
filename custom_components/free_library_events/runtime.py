"""Runtime types for Free Library Events."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .coordinator import LibraryDataCoordinator


@dataclass(slots=True)
class LibraryRuntime:
    """Runtime objects owned by one config entry."""

    coordinator: LibraryDataCoordinator


type LibraryConfigEntry = ConfigEntry[LibraryRuntime]
