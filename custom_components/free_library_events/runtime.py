"""Runtime types for Free Library Events."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from .coordinator import LibraryDataCoordinator

type LibraryConfigEntry = ConfigEntry[LibraryDataCoordinator]
