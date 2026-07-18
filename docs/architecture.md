# Architecture

## Ownership

- This is a public HACS-compatible Home Assistant custom integration.
- Runtime files live only under `custom_components/free_library_events/`.
- The public Git repository and immutable release tags are the canonical code
  and distribution owners. HACS downloads releases into Home Assistant's
  `custom_components` directory.
- Personal configuration belongs only in the Home Assistant config entry and
  operator-owned private automation/configuration surfaces.

## Runtime Model

- `config_flow.py` owns the single config entry and reload-on-save options.
- The config-entry card and service device use the static integration name;
  child identity remains only in private config data and rendered content.
- `api.py` reads the selected official Free Library branch RSS feeds through
  Home Assistant's shared HTTP session.
- `coordinator.py` performs one bounded concurrent refresh, preserves partial
  branch success, and fails the update when every selected source fails.
- `digest.py` is a deterministic, side-effect-free parser, age matcher, and
  HTML/plain-text renderer. It does not call an LLM.
- `calendar.py`, `sensor.py`, and `button.py` expose the native user-facing
  calendar, diagnostic status, and manual refresh surfaces.
- `__init__.py` registers the response-only `render_digest` action. The caller
  owns scheduling, recipient selection, and email delivery.
- `diagnostics.py` redacts child name and birth date and exposes only bounded
  source health and counts.

## Supported Source Boundary

The initial integration scope is intentionally limited to the Charles Santore
(`SWK`) and Independence (`IND`) Free Library of Philadelphia branch feeds.
Adding a branch requires public source metadata, parsing/feed validation,
config-flow and translation changes, deterministic tests, and documentation.

## Release Contract

1. Use Python 3.14 and run unit, HA integration, compile, JSON, privacy,
   Hassfest, and HACS validation.
2. Keep `manifest.json` version, Git tag, and release title aligned.
3. Publish an immutable `vYYYY.M.D` release from the validated commit.
4. Install or update only through HACS using an exact release.
5. Restart Home Assistant after installation or update and verify the config
   entry, entities, action, diagnostics, logs, Repairs, and update entity.

Maintainer-specific backup, deployment readback, rollback, and household
automation procedures deliberately live outside this public repository.
