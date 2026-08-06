# Cross-project contract review

This review disposes the reusable Home Assistant custom-integration contracts
against Free Library Events. It applies contracts, not sibling product
features. The evidence is the current source, tests, workflow, and
[`architecture.md`](architecture.md); private deployment evidence remains in
its private owner and is not reproduced here.

## Aggregated contract disposition

| Contract | Disposition | Current evidence and decision |
|---|---|---|
| Typed config-entry runtime | Already satisfied | `runtime.py` defines `LibraryConfigEntry = ConfigEntry[LibraryDataCoordinator]`; setup assigns one coordinator to `entry.runtime_data`, and every platform consumes that typed owner. A runtime dataclass would add no second independently owned object. |
| Stable data, changeable options, and identity | Already satisfied | Required person profile and ordered branch identity live in config-entry data. Matching, timing, and WebCal behavior live in options with reload-on-save flows. The source registry is an explicit closed product boundary, so preserving unknown backend entity IDs and confirming physical-device/account changes are not applicable. |
| Versioned migrations and continuity | Already satisfied | Config-entry version 1.2 migrates the earlier combined contract, preserves selected branches and stable entity unique IDs, and keeps deliberately bounded branch mirrors for rollback to the documented older release. Recorder-series continuity and source-command policy are not integration features. |
| Explicit supported source boundary | Already satisfied | `digest.py` owns the four supported branches and official source metadata. `api.py` accepts only trusted publisher HTTPS RSS routes. Protected HTML/ICS scraping and unsupported structured fields remain explicitly excluded. |
| Normalize once, project many | Already satisfied and concurrency-hardened | `LibraryDataCoordinator` produces one immutable `LibraryData` snapshot containing normalized, merged events and source health. Calendar, WebCal, status, diagnostics, and digest rendering project that same cache; entity properties perform no I/O. A render action captures one snapshot before image-download awaits so an overlapping refresh cannot mix generations. |
| Partial success and capability-aware degradation | Already satisfied | Per-source successes survive sibling failures; only complete source failure fails the update. Calendar and digest retain usable events, while status, response metadata, and diagnostics distinguish `partial`, `limited`, and healthy coverage. |
| Bounded work and stale-result guards | Already satisfied; revision tokens not applicable | Requests share a concurrency ceiling, response and redirect bounds, finite timeouts, and a capped adaptive-expansion budget. The coordinator serializes refresh ownership, each render retains one coordinator generation across awaits, and isolated image runs prevent concurrent render actions from overwriting one another. The integration has no pending command or mutable statistics import that needs a revision token. |
| Helper-device linking without co-ownership | Deliberately not applicable | Free Library Events owns one service device and does not enrich or attach entities to a device owned by another integration. Adding helper-device migration would create a nonexistent ownership relationship. |
| Stable identity and dynamic discovery | Already satisfied; discovery not applicable | The single calendar, sensor, button, config entry, and service device use stable domain-based IDs. Branch membership is an explicit user-selected public registry, not cloud discovery, so automatic entity creation and missing-backend-entity recovery do not apply. |
| Compact state and rich on-demand diagnostics | Implemented by this review | Ordinary state keeps bounded counts, coverage, and at most three expansion-failure examples. Diagnostics retain finite per-source evidence while redacting profile data. Source, image, storage, and coordinator failures now expose allow-listed categories or fixed summaries instead of arbitrary exception text. |
| One action, one owner | Already satisfied | `render_digest` is response-only. It renders data and optionally prepares bounded attachments; the caller owns recipients, scheduling, and `smtp.send_message`. Source refresh remains coordinator-owned and there is no sender or scheduler in this integration. |
| Validate before side effects | Already satisfied and hardened | The action requires exactly one loaded entry, validates schema and config before rendering, and raises translated `ServiceValidationError` or `HomeAssistantError`. The manual refresh platform action also raises a translated failure instead of silently succeeding. Image writes occur only after trusted download validation; storage fallback no longer returns operating-system exception text. |
| Sensitive capability changes fail closed | Already satisfied | WebCal is off by default, token URLs remain private, rotation has an explicit confirmation step, disabling removes the token, and disabled, invalid, or unloaded routes return `404`. Enabling or rotating refuses to save when Home Assistant has no usable base URL. There is no account or command-writer boundary. |
| Actionable Repairs only | Deliberately not applicable | This integration has no persistent user-fixable mapped-entity or account inconsistency. Transient source loss is already represented by coordinator health. Creating a Repair for it would be noisy and contrary to the contract. |
| Public/private boundary and security | Already satisfied and hardened | Fixtures are synthetic; diagnostics redact profile and token fields; safe wrapper exceptions suppress lower-level transport and private config causes; the public-safety guard scans tracked and public-relevant files and reviews binaries; workflows use full-SHA Actions, read-only permissions, non-persistent checkout credentials, timeouts, concurrency cancellation, actionlint/ShellCheck, and zizmor. Weekly Python and Actions dependency updates are configured. Exact private-value scanning stays in the private publication gate. |
| Validation and release | Already satisfied locally; hosted/live gates remain separate | Python 3.14, Ruff, strict mypy, unit tests, compile, JSON, privacy, minimum/current Core lanes, Hassfest, HACS, actionlint/ShellCheck, zizmor, and a terminal release gate are owned by the repository. The Home Assistant harness and exact Core requirements install separately. GitHub default CodeQL is configured for Python and Actions, but exact-commit completion and alert disposition remain release-time hosted evidence. Publication, HACS installation, restart, and live validation remain separately gated. |

## Current Home Assistant quality-rule review

The current official
[integration quality scale rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/)
were used as evaluation prompts, not as a certification or coverage target.

- The August 2026
  [action-exceptions rule](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/action-exceptions/)
  explicitly includes platform actions. The refresh button now checks the
  coordinator result and raises a translated failure when its request fails.
- Applicable baseline rules are evidenced by native config/reconfigure/options
  flows, one unique config entry, typed runtime data, stable entity IDs and
  translated names, coordinator polling, service registration during
  `async_setup`, unloading, translated action failures, diagnostics, entity
  categories, explicit parallel-update ownership, documentation, and tests.
- Reauthentication, discovery, dynamic-device, stale-device, and repair-flow
  rules are not applicable because there are no credentials, discovered
  devices, or persistent user-fixable mapping faults.
- A config-flow connection probe is not applicable because setup selects no
  credential, account, or device endpoint. The coordinator's first refresh is
  the test-before-setup boundary and fails setup only when every selected
  official source fails.
- The async web session is injected from Home Assistant. Strict mypy is an
  existing repository contract. No quality tier is claimed: full numeric
  module/config-flow coverage, a public automation blueprint, and a
  `quality_scale.yaml` artifact were deliberately not added because the
  targeted risk tests and private caller-owned delivery workflow are the
  smaller useful owners.

## Deliberately excluded sibling machinery

Thermostat command routing, command confirmation revisions, helper-device
linking, Recorder statistics, filter-maintenance state, account replacement,
cloud-resource discovery, and source-entity Repairs solve sibling product
requirements. Free Library Events has no corresponding owner or invariant, so
adding them would violate the product boundary and create a parallel control
surface.
