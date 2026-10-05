"""Constants for the Free Library Events integration."""

from __future__ import annotations

DOMAIN = "free_library_events"
NAME = "Free Library Events"
CONFIG_ENTRY_MINOR_VERSION = 3

CONF_CHILD_NAME = "child_name"
CONF_BIRTH_DATE = "birth_date"
CONF_BRANCHES = "branches"
CONF_FILTER_MODE = "filter_mode"
CONF_CALENDAR_DURATION = "calendar_duration_minutes"
CONF_SCAN_INTERVAL = "scan_interval_seconds"
CONF_PUBLISH_WEBCAL = "publish_webcal"
CONF_WEBCAL_TOKEN = "webcal_token"
CONF_WEBCAL_NAME = "webcal_name"

DEFAULT_FILTER_MODE = "Recommended"
DEFAULT_CALENDAR_DURATION = 60
DEFAULT_SCAN_INTERVAL = 6 * 60 * 60
DEFAULT_WEBCAL_NAME = NAME

MIN_CALENDAR_DURATION = 15
MAX_CALENDAR_DURATION = 240
MIN_SCAN_INTERVAL = 15 * 60
MAX_SCAN_INTERVAL = 24 * 60 * 60
MAX_WEBCAL_NAME_LENGTH = 80

SERVICE_RENDER_DIGEST = "render_digest"
ATTR_FORCE_REFRESH = "force_refresh"
ATTR_EMBED_IMAGES = "embed_images"
