"""Home Assistant test fixtures."""

from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request: pytest.FixtureRequest) -> None:
    """Enable the local custom integration for tests that use Home Assistant."""
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
