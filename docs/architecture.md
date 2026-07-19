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
- `api.py` reads official custom branch RSS feeds through Home Assistant's
  shared HTTP session and records the evidence needed to evaluate the ten-item
  source boundary. Because the endpoint ignores `page=2`, it can expand one
  unresolved feed through the publisher's official event-type filters. Invalid
  individual event rows are skipped while their published-versus-parsed mismatch
  remains observable. All RSS requests share an eight-request concurrency
  ceiling, each decoded response is stopped at 256 KiB, and any one capped-source
  expansion is stopped after 90 seconds without discarding its base events.
- `coordinator.py` derives the configured person's current life-stage group from
  the local birth date, requests every official age category in that group for
  each selected branch, refreshes the plan concurrently, consolidates duplicate
  events while retaining their official classifications and richer safe fields,
  and preserves partial source success. It adaptively expands at most twelve
  unresolved capped feeds per refresh. Current-age sources come first, followed
  by the numerically nearest official age windows, with branches distributed
  deterministically within each category. A minor uses Baby through Young
  Adult; an adult uses only the Adult, Senior, or overlapping Young Adult windows
  that apply; a forward source window crossing adulthood retains both sides. It
  fails the update only when every selected source fails.
- `digest.py` is a deterministic, side-effect-free parser, age matcher, and
  HTML/plain-text renderer. Explicit numeric ranges take precedence, followed
  by matching official age-feed classifications and then explicit inclusive
  text. Strong published wording can correct an overly narrow feed category;
  generic family wording cannot. Age classification controls inclusion and
  ordering; it is not repeated as per-event presentation copy. Safe contextual
  RSS links are preserved. Email clients auto-load event images only from the
  publisher's HTTPS hosts, and explicit off-site venues or named/numbered rooms
  refine location without inventing data. An end time is
  accepted only from an explicit RSS description range that matches the
  published start or a conservative whole-event duration statement; the digest
  and HA calendar both use that same evidence. It does not call an LLM.
- `calendar.py`, `sensor.py`, and `button.py` expose the native user-facing
  calendar, diagnostic status, and manual refresh surfaces.
- `__init__.py` registers the response-only `render_digest` action. The caller
  owns scheduling, recipient selection, and email delivery; no parallel sender
  or scheduler exists inside the integration.
- `diagnostics.py` redacts child name and birth date and exposes only bounded
  per-source counts, type-expansion evidence, ordering, coverage boundaries, and
  health. High-volume shard failures remain available in on-demand diagnostics;
  entity state and action-response metadata retain a count and three examples.

## Supported Source Boundary

The supported source set is intentionally limited to the Charles Santore
(`SWK`), Independence (`IND`), Parkway Central (`CEN`), and Philadelphia City
Institute (`PCI`) Free Library of Philadelphia branch feeds. Adding a branch
requires public source metadata, parsing/feed validation, config-flow and
translation changes, deterministic tests, and documentation. All supported
sources default on and can be disabled individually in the config entry.

For every selected branch, the coordinator requests every official age category
in the configured person's current life-stage group. This preserves publisher
age provenance, avoids the noise and ambiguity of an unclassified all-events
feed, and still discovers explicitly inclusive events assigned to a narrower
category. A feed below the ten-item limit is complete. At the limit, its parsed
order and last event must prove coverage beyond the target digest week. If they
do not, the coordinator requests the stable official event-type taxonomy and
merges the resulting overlapping rows. Expansion proves coverage only when all
type shards cover the week and collectively recover the capped base prefix;
otherwise the limitation remains visible. At most twelve capped sources are
expanded in one refresh, enough for the maximum three overlapping current-age
categories across all four supported branches while the worst case stays
bounded. Current-age sources are always selected before supplemental discovery.
Current-age feed gaps are operationally `partial` and are disclosed by the
rendered digest. A healthy but still-capped supplemental age feed is `limited`:
this truthfully records that
later broadly inclusive events cannot be proven without conflating a publisher
limitation with a source failure. Render-response metadata retains supplemental
failures, cap limitations, and expansion evidence for native HA trace/readback
without adding diagnostic clutter to the email body.

Protected event HTML and ICS endpoints are deliberately outside the runtime
source boundary. Home Assistant's asynchronous HTTP clients receive the
publisher's browser challenge on those routes, so page scraping would make
refresh health dependent on an unsupported access path. The integration
retains safe embedded RSS links and explicit venue/room wording but does not
infer unavailable topic, registration, cost, or end-time fields.

The actionable calendar and digest omit items whose published title marks the
occurrence cancelled, canceled, postponed, or rescheduled. This avoids
presenting a stale dated row as an activity while leaving the official source
page available outside the integration for schedule changes.

## Release Contract

1. Use Python 3.14 and run unit, HA integration, compile, JSON, privacy,
   Hassfest, and HACS validation.
2. Compare the official RSS builder's age and event-type options with the local
   source taxonomy; the runtime builder route is browser-protected, so this is a
   release-time drift check rather than an unreliable polling dependency.
3. Keep `manifest.json` version, Git tag, and release title aligned.
4. Publish an immutable `vYYYY.M.D` release from the validated commit.
5. Install or update only through HACS using an exact release.
6. Restart Home Assistant after installation or update and verify the config
   entry, entities, action, diagnostics, logs, Repairs, and update entity.

Maintainer-specific backup, deployment readback, rollback, and household
automation procedures deliberately live outside this public repository.
