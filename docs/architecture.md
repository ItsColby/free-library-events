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

- `config_flow.py` owns the single config entry, required profile
  reconfiguration, and reload-on-save options. Version 1.2 stores the display
  name, birth date, and ordered branch-code selection in config-entry data while
  optional matching, timing, and WebCal controls live in options. Version-1
  branch booleans remain synchronized compatibility mirrors so a downgrade to
  v2026.7.26 retains the selected branches. A minor-version migration splits
  older combined entries without changing their effective behavior. Every
  replacement preserves unrecognized fields in its existing data or options
  owner. The two-step WebCal preview captures the complete accepted data and
  options mappings and aborts without saving or reloading if either changes
  before confirmation, so a concurrent flow cannot overwrite newer settings.
  Matching and timing remain one small directly accessible options form rather
  than depending on Home Assistant's deprecated profile-level advanced mode.
  Submitting an unchanged reconfigure form does not reload the integration or
  request the sources again.
- The config-entry card and service device use the static integration name;
  person identity remains only in private config data and rendered content. The
  internal `child_name` key remains unchanged for compatibility while every
  user-facing label uses person terminology.
- `api.py` reads official custom branch RSS feeds through Home Assistant's
  shared HTTP session, follows at most two HTTPS redirects that remain on the
  publisher's trusted hosts, and records the evidence needed to evaluate the
  observed ten-item source boundary. Because the endpoint ignores `page=2`, it
  can expand one unresolved feed through the publisher's official event-type
  filters. Invalid individual event rows are skipped while their
  published-versus-parsed mismatch remains observable. All RSS requests share
  an eight-request concurrency
  ceiling, each decoded response is stopped at 256 KiB, and any one capped-source
  expansion is stopped after 90 seconds without discarding its base events.
- `coordinator.py` derives the configured person's current life-stage group from
  the local birth date, requests every official age category in that group for
  each selected branch, refreshes the plan concurrently, consolidates duplicate
  events with one order-independent effective-row rule while retaining their
  official classifications and richer safe fields, and lets an inactive
  publisher title win so a cancellation cannot be hidden by an older
  overlapping feed,
  and preserves partial source success. Each completed refresh publishes one
  deeply immutable normalized snapshot: event rows are frozen tuples and every
  source-count, status, and error mapping is read-only. Home Assistant's
  config-entry-owned coordinator debouncer bounds overlapping refresh triggers
  to one running refresh plus one pending follow-up and shuts down scheduled
  work on unload. Forced digest renders and manual refreshes wait for a
  completed attempt, including a refresh already in flight, with a ten-minute
  upper bound. Cancelling one caller leaves shared source work intact; unloading
  releases waiting callers with a translated failure. Every completed
  base-source attempt also replaces one immutable privacy-safe record containing the requested source keys,
  allow-listed error categories, retryable count, completion time, and retry
  decision. That record remains distinct from the last successful normalized
  cache, so a complete source failure uses a translated update error without
  losing its current evidence. When every source in the first complete failure
  of a continuous failure streak has a retryable transport, rate-limit, or
  server failure, the update error requests one five-minute coordinator retry.
  A repeated failure returns to the configured interval; any partial or full
  success resets the allowance. Initial entry setup uses Core's setup retry
  policy and never claims an expedited polling retry. It adaptively expands at
  most twelve
  unresolved capped feeds per refresh. Current-age sources come first, followed
  by the numerically nearest official age windows, with branches distributed
  deterministically within each category. A minor uses Baby through Young
  Adult; an adult uses only the Adult, Senior, or overlapping Young Adult windows
  that apply; a forward source window crossing adulthood retains both sides. It
  fails the update only when every selected source fails.
- `digest.py` owns deterministic, side-effect-free parsing, age classification,
  and HTML/plain-text rendering. [Match modes](../README.md#match-modes) and
  [Weekly email action](../README.md#weekly-email-action) define the visible
  matching, highlight, time, venue, link, image, and omission contracts. Safe RSS
  links, paragraph boundaries, emphasis, and lists pass through one allow-list
  sanitizer; presentation highlights never change inclusion or source provenance.
  The calendar and digest share occurrence identity (source URL/title, branch,
  date, and start time), so a series URL cannot collapse distinct dates and
  shortening a display title cannot change identity. Response metadata retains
  both publisher event IDs and exact occurrence IDs.
  Titles, descriptions, calendar details/URLs, event count, and final HTML bytes
  have separate bounds. Budgeting reserves rich cards for nearer branches,
  removes farthest compact overflow only when necessary, and preserves
  chronological presentation. Both bodies disclose email-only omissions.
  Email markup uses presentation tables, percentage line heights, table-cell
  spacing, and a stacked base layout because some Gmail mobile paths ignore
  responsive rules. Square/portrait posters grow to card width on responsive
  clients and otherwise cap at 440 CSS pixels; descriptions use the full width.
  The two-column branch-calendar fallback stacks below 390 CSS pixels. A concise
  subject avoids repeating the date range, the header summarizes age and branch
  count, and a complementary hidden preheader supports inbox previews. Linked
  image alternative text identifies the official event details destination.
- `calendar_data.py` projects normalized source rows into the single shared,
  deterministic age-filtered calendar model. `calendar.py` exposes those rows
  through Home Assistant's native calendar entity. `webcal.py` serializes the
  same current coordinator cache as RFC 5545 iCalendar and serves it through an
  opt-in, token-protected, unauthenticated HTTP view for subscription clients
  that cannot send Home Assistant bearer authentication. The view never forces
  a source refresh. It serves equivalent `GET` and `HEAD` metadata plus
  representation-derived `ETag` and source/config-entry-derived `Last-Modified`
  validators; matching conditional requests return `304`. Disabled, invalid,
  and unloaded tokens fail closed as `404`.
- `calendar.py`, `sensor.py`, and `button.py` expose the native user-facing
  calendar, diagnostic status, and manual refresh surfaces. The status sensor
  is a finite Home Assistant enum whose raw automation values remain `ok`,
  `limited`, `partial`, and `error`; translations provide user-facing state
  labels. It exposes one immutable projection built from the coordinator cache
  and one captured local evaluation clock. Because the Monday digest window
  advances at Tuesday local midnight, the sensor schedules that exact
  lifecycle-owned boundary, rebuilds without feed I/O, writes only when the
  visible projection changes, reschedules after coordinator refreshes and each
  boundary, follows Home Assistant Core timezone changes, and cancels its timer
  and timezone listener on unload. Home Assistant Core continues to own native
  calendar current/upcoming start and end scheduling. `translations/en.json`
  and `icons.json` own action/entity metadata and icons instead of adding
  hard-coded presentation state to the entities.
- `config_flow.py` generates, displays, explicitly confirms rotation of, and
  removes the private webcal capability token. It presents both HTTP(S) and
  `webcal://` URL forms, identifies whether Home Assistant supplied an
  external/cloud or internal-only base URL, and lets the user name the calendar.
  The token stays only in private config-entry options and is
  excluded from diagnostics, entity state, integration-authored logs, and public
  source fixtures. Home Assistant or reverse-proxy HTTP access logs may still
  contain the requested URL and therefore require private handling.
- External DNS and reverse-proxy policy remain deployment-owned. Every
  published address family must reach Home Assistant, and only the calendar
  route may bypass interactive or proxy Basic Auth so the opaque capability
  token remains its sole credential. Google Calendar and other server-side
  importers receive the canonical HTTPS form; `webcal://` is a client/OS
  handoff convenience.
- `__init__.py` registers the process-lifetime webcal route and the response-only
  `render_digest` action. The caller
  owns scheduling, recipient selection, and email delivery; no parallel sender
  or scheduler exists inside the integration. Opt-in SMTP embedding adds
  `attachments`, rollback-compatible `images`, and bounded download and expiry
  metadata to the response, but the immediately following caller-owned notify
  action remains the delivery owner. Each render captures one complete
  config-entry owner with its coordinator, rejects a reconfigure or reload that
  supersedes either during an awaited source refresh, and then captures exactly
  one coordinator snapshot before its first image-download await. An overlapping
  refresh therefore cannot mix settings, events, coverage evidence, or
  timestamps from different generations in one response.
- `__init__.py` also calculates ephemeral branch distances from Home Assistant's
  native configured latitude/longitude and the integration's public branch
  coordinates. Distance only selects which occurrences retain rich cards when
  the HTML budget is constrained; it never renders in the email. Home
  coordinates and calculated distances are not stored, logged, included in
  response metadata, or used to reorder the chronological email.
- `email_images.py` owns publisher-image downloads, trusted redirects,
  signature/dimension validation, orientation, CID filenames, temporary storage,
  and cleanup. The [SMTP embedding contract](../README.md#weekly-email-action)
  specifies limits, expiry, and fallback versus omission behavior. Downloads use
  Home Assistant's shared HTTP session and only the selected unique images.
  Files live in random integration-owned runs under Local Media; returned
  attachments include only CIDs referenced by the final budgeted HTML. Native
  `smtp.send_message` media-source objects and legacy local paths share that
  selection. Scheduled, pre-render stale, and startup cleanup use marker and
  name checks to preserve unrelated files. A failed storage creation removes
  only a directory created by that invocation, preserving an existing path on
  collision. Remote-image rendering remains the no-storage default, so generic
  response consumers do not receive unusable CID references.
- `diagnostics.py` redacts the person's display name, birth date, and custom
  calendar name. Invalid stored settings return a fixed `invalid_config`
  category with no raw configuration or exception text. Diagnostics expose
  only bounded per-source counts, type-expansion evidence, ordering, coverage
  boundaries, and health. It labels the retained normalized cache separately
  from the latest completed base-source attempt, including compact totals,
  allow-listed error-category counts, per-source result, retryable count, and
  one-retry decision. Successful type shards that cannot prove coverage
  retain a stable reason identifier, official event type, counts, and last event
  date, while base-prefix recovery remains explicit. Source and coordinator
  failures use allow-listed categories, while unexpected image and storage
  failures use fixed bounded summaries rather than arbitrary exception text.
  Finite shard failures and blockers remain available in on-demand diagnostics;
  entity state and action-response metadata retain counts and three examples.
- The manual refresh button checks the coordinator result and raises a
  translated Home Assistant error on failure. A platform action therefore
  cannot report success when every requested source failed. It deliberately
  remains available while the config entry is loaded, independent of the last
  coordinator result, so a complete source failure cannot disable manual
  recovery.

## Supported Source Boundary

The supported source set is intentionally limited to the Charles Santore
(`SWK`), Independence (`IND`), Parkway Central (`CEN`), and Philadelphia City
Institute (`PCI`) Free Library of Philadelphia branch feeds. Adding a branch
requires public source metadata, parsing/feed validation, deterministic tests,
and documentation. All supported sources default on and are presented through
one ordered multi-select generated from the supported branch registry. Adding a
registry entry therefore does not require another persisted boolean or
translation key.

For every selected branch, the coordinator requests every official age category
in the configured person's current life-stage group. This preserves publisher
age provenance, avoids the noise and ambiguity of an unclassified all-events
feed, and still discovers explicitly inclusive events assigned to a narrower
category. A feed below the observed ten-item boundary is complete. At or above
that boundary, its parsed order and last event must prove coverage beyond the
target digest week. If they do not, the coordinator requests the stable official
event-type taxonomy and merges the resulting overlapping rows. Expansion
proves coverage only when all type shards cover the week and collectively
recover the capped base prefix. A successful, ordered shard stopped by the
publisher's item ceiling remains a healthy limitation; a parsed-incompletely,
unordered, or boundary-less shard is an operational failure. The exact bounded
blocker evidence remains visible instead of flattening both cases into one
generic limitation. At most twelve capped sources are
expanded in one refresh, enough for the maximum three overlapping current-age
categories across all four supported branches while the worst case stays
bounded. Current-age sources are always selected before supplemental discovery.
Current-age feed gaps are operationally `partial` and are disclosed by the
rendered digest. A healthy but still-capped supplemental age feed is `limited`:
this truthfully records that later broadly inclusive events cannot be proven
without conflating a publisher limitation with a source failure.
Render-response metadata retains supplemental failures, cap limitations, and
expansion evidence for native HA trace/readback without adding diagnostic
clutter to the email body.

The publisher's protected event HTML and ICS endpoints are deliberately outside
the runtime source boundary. Home Assistant's asynchronous HTTP clients receive
the publisher's browser challenge on those routes, so page scraping would make
refresh health dependent on an unsupported access path. The integration-owned
webcal route serializes the already normalized coordinator cache and never
fetches either protected publisher route. The integration retains safe embedded
RSS links and explicit venue/room wording. It does not fetch official structured
event-page taxonomy, registration, cost, or end-time fields. It may derive narrow
presentation highlights such as a secondary
activity, accessibility format, outdoor setting, participation note, or
published planning caution from reliable RSS wording; these labels do not change
inclusion or source provenance.

The actionable calendar and digest omit items whose published title marks the
occurrence cancelled, canceled, postponed, or rescheduled. This avoids
presenting a stale dated row as an activity while leaving the official source
page available outside the integration for schedule changes.

## Release Contract

1. Use Python 3.14 and run unit, compile, JSON, privacy, Ruff, strict mypy,
   actionlint with ShellCheck, zizmor auditor, Hassfest, and HACS validation.
   The Linux HA tests have two exact owners: `requirements-ha-test.txt` proves
   dependency closure at the 2026.8.0 supported minimum, while
   `requirements-ha-current.txt` targets Core 2026.9.1 with a matching harness
   and clean dependency closure. The current checker verifies exact installed
   metadata and `pip check`. Its mismatch exception is limited to a single
   metadata-proven harness/Core pin conflict within the minimum's same month;
   cross-month conflicts, prereleases, other dependency conflicts, skipped
   collection, and test failures are rejected. Such an exception proves only
   patch compatibility. Both lanes execute every HA test module, and each native
   lane uses an isolated temporary virtual environment.
2. Compare the official RSS builder's age and event-type options with the local
   source taxonomy; the runtime builder route is browser-protected, so this is a
   release-time drift check rather than an unreliable polling dependency.
3. On a release-candidate branch, align `manifest.json`, the intended immutable
   `vYYYY.M.D` tag, and release title before opening the release pull request.
4. Require terminal pull-request success for **Unit tests and static
   validation**, **Home Assistant minimum integration tests (Core 2026.8.0)**,
   **Home Assistant current integration tests (Core 2026.9.1)**,
   **Hassfest**, **HACS**, the aggregate **Release gate**, and CodeQL's **Analyze
   (actions)**, **Analyze (python)**, and **CodeQL** checks.
5. Merge through default-branch protection without bypass, using squash or
   rebase so history remains linear.
6. On the resulting `main` commit, require the **Validate** push run and CodeQL
   analysis to succeed. Inspect their complete logs and open code-scanning
   alerts; workflow success proves analysis completed, not that it found
   nothing. Resolve or explicitly disposition candidate-introduced findings.
7. Publish the immutable tag and GitHub Release only from that exact validated
   `main` commit.
8. Treat HACS selection or installation, the Home Assistant configuration
   check, restart, live validation, migration, and rollback as later, separately
   gated phases.

Maintainer-specific backup, deployment readback, rollback, and household
automation procedures deliberately live outside this public repository.
