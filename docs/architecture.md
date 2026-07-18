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
- `api.py` reads official custom branch-and-age RSS feeds through Home
  Assistant's shared HTTP session and records the evidence needed to evaluate
  the ten-item source boundary.
- `coordinator.py` derives the relevant official age categories from the local
  birth date, refreshes each selected branch/category pair concurrently,
  consolidates duplicate events while retaining their official classifications,
  and preserves partial source success. It fails the update only when every
  selected source fails.
- `digest.py` is a deterministic, side-effect-free parser, age matcher, and
  HTML/plain-text renderer. Explicit numeric ranges take precedence, followed
  by official age-feed classifications and then text inference. Age
  classification controls inclusion and ordering; it is not repeated as
  per-event presentation copy. An end time is accepted only from an explicit RSS
  description range that matches the published start; the digest and HA calendar
  both use that same evidence. It does not call an LLM.
- `calendar.py`, `sensor.py`, and `button.py` expose the native user-facing
  calendar, diagnostic status, and manual refresh surfaces.
- `__init__.py` registers the response-only `render_digest` action. The caller
  owns scheduling, recipient selection, and email delivery; no parallel sender
  or scheduler exists inside the integration.
- `diagnostics.py` redacts child name and birth date and exposes only bounded
  per-source counts, ordering, coverage boundaries, and health.

## Supported Source Boundary

The supported source set is intentionally limited to the Charles Santore
(`SWK`), Independence (`IND`), Parkway Central (`CEN`), and Philadelphia City
Institute (`PCI`) Free Library of Philadelphia branch feeds. Adding a branch
requires public source metadata, parsing/feed validation, config-flow and
translation changes, deterministic tests, and documentation. All supported
sources default on and can be disabled individually in the config entry.

For every selected branch, the coordinator requests the official age categories
that overlap the child's age across its forward source horizon. A feed below the
ten-item limit is complete. At the limit, its parsed order and last event must
prove coverage beyond the target digest week; otherwise the diagnostic sensor
and rendered digest disclose unresolved coverage rather than silently treating
the result as complete.

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
