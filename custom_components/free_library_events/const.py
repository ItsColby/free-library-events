"""Constants for the Free Library Events integration."""

from __future__ import annotations

DOMAIN = "free_library_events"
NAME = "Free Library Events"

CONF_CHILD_NAME = "child_name"
CONF_BIRTH_DATE = "birth_date"
CONF_INCLUDE_SANTORE = "include_charles_santore"
CONF_INCLUDE_INDEPENDENCE = "include_independence"
CONF_INCLUDE_PARKWAY_CENTRAL = "include_parkway_central"
CONF_INCLUDE_PCI = "include_philadelphia_city_institute"
CONF_FILTER_MODE = "filter_mode"
CONF_CALENDAR_DURATION = "calendar_duration_minutes"
CONF_SCAN_INTERVAL = "scan_interval_seconds"

DEFAULT_CHILD_NAME = "Child"
DEFAULT_INCLUDE_SANTORE = True
DEFAULT_INCLUDE_INDEPENDENCE = True
DEFAULT_INCLUDE_PARKWAY_CENTRAL = True
DEFAULT_INCLUDE_PCI = True
DEFAULT_FILTER_MODE = "Recommended"
DEFAULT_CALENDAR_DURATION = 60
DEFAULT_SCAN_INTERVAL = 6 * 60 * 60

MIN_CALENDAR_DURATION = 15
MAX_CALENDAR_DURATION = 240
MIN_SCAN_INTERVAL = 15 * 60
MAX_SCAN_INTERVAL = 24 * 60 * 60

SERVICE_RENDER_DIGEST = "render_digest"
ATTR_FORCE_REFRESH = "force_refresh"
