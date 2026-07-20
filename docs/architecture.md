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
  reconfiguration, and reload-on-save options. Version 2 stores the display
  name, birth date, and ordered branch-code selection in config-entry data while
  optional matching, timing, and WebCal controls live in options. A migration
  splits older combined entries without changing their effective behavior.
- The config-entry card and service device use the static integration name;
  person identity remains only in private config data and rendered content.
- `api.py` reads official custom branch RSS feeds through Home Assistant's
  shared HTTP session and records the evidence needed to evaluate the observed
  ten-item source boundary. Because the endpoint ignores `page=2`, it can expand
  one unresolved feed through the publisher's official event-type filters. Invalid
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
  ordering. Publisher age categories render in one muted `Library age listing:`
  line with the title, time, and location so publisher provenance remains clear.
  Time and location use separate mobile-friendly lines; only the location label,
  not its map pin, is linked, and no home-relative distance is exposed.
  Presentation highlights render in
  that same scan-first metadata area and are derived deterministically from the
  RSS title, description, or explicit venue; title-redundant activity labels,
  broader equivalents of specific take-home details, audience-redundant breadth
  labels, and generic taxonomy are omitted. At most five highlights render, with
  actionable cautions ahead of logistics and secondary topics; negated and
  audience-qualified claims are excluded. Safe contextual RSS links, paragraph
  boundaries, emphasis, and list structure are preserved through an allow-list
  sanitizer. The concise subject avoids duplicating the date range, while the
  header summarizes age matching and participating-library count. Presentation
  tables, percentage line heights, a dynamic complementary hidden preheader,
  a two-column touch-friendly branch-calendar fallback that stacks below 390
  CSS pixels, and table-cell spacing for day, card, and button layout
  improve compatibility across email rendering engines. Linked event images use
  functional alternative text that identifies their official details page. By
  default, email clients load event
  images only from the publisher's HTTPS hosts; the renderer keeps the
  publisher's working dot-prefixed image paths and does not resolve a blank
  image field to the feed URL. An explicit SMTP embedding option
  deterministically downloads only the selected events' unique images through
  Home Assistant's shared HTTP session, follows at most two HTTPS redirects that
  remain on trusted publisher hosts,
  validates signatures and dimensions, and writes them to a random
  integration-owned run under the default-allowed `www` root, substitutes
  basename-matched `cid:` sources, and returns only paths whose CIDs remain
  referenced by the final budgeted HTML to the caller's legacy
  HTML/images-capable SMTP notify action. The newer plain-text SMTP notify entity
  is outside this CID
  contract. It never calls an LLM. Each run expires after one hour. Scheduled,
  pre-render stale, and startup cleanup remove owned run directories while
  marker and name checks preserve all other files. Transient transport/server
  failures, storage failures, and digest-level count/total-size limits may
  retain the already trusted publisher URL as a remote fallback. Publisher
  challenge and rate-limit responses do the same because browser-capable email
  clients may still load those trusted URLs. Unsafe redirects, unsupported
  content, true missing-image responses, and individually oversized files are
  omitted. Landscape images use a full-width hero row;
  square and portrait images use a centered, fluid poster row above the
  scan-first metadata. The base table structure is stacked rather than relying
  on a mobile media query, because some Gmail mobile render paths preserve the
  desktop table while ignoring responsive rules. The poster grows to the card
  width on responsive clients and is capped at 440 CSS pixels otherwise;
  descriptions remain full width below. Explicit online events omit map links;
  hybrid events
  retain their physical destination and name the online option. Explicit
  off-site venues or named/numbered rooms and floor locations refine the
  map/calendar destination without inventing data, while an off-site summary
  retains unlinked hosting-branch context. An end time is accepted only from an
  explicit RSS description range that matches the published start or a
  conservative whole-event duration statement; the digest and HA calendar both
  use that same evidence. Recurring rows use an occurrence identity containing
  source URL/title, branch, date, and start time across the digest and native HA
  calendar so a shared series URL cannot collapse distinct dates. Response
  metadata retains both simple publisher event IDs and exact occurrence IDs.
  Display titles,
  descriptions, calendar details/URLs, event count, and the final HTML byte size
  have separate bounds. The renderer keeps chronological presentation, reserves
  rich cards for nearest branches when a large result requires compaction, and
  removes farthest compact overflow only when necessary to remain within 80,000
  UTF-8 bytes. It visibly discloses any email-only omission. It does not call an
  LLM.
- `calendar_data.py` projects normalized source rows into the single shared,
  deterministic age-filtered calendar model. `calendar.py` exposes those rows
  through Home Assistant's native calendar entity. `webcal.py` serializes the
  same current coordinator cache as RFC 5545 iCalendar and serves it through an
  opt-in, token-protected, unauthenticated HTTP view for subscription clients
  that cannot send Home Assistant bearer authentication. The view never forces
  a source refresh. Disabled, invalid, and unloaded tokens fail closed as `404`.
- `calendar.py`, `sensor.py`, and `button.py` expose the native user-facing
  calendar, diagnostic status, and manual refresh surfaces.
- `config_flow.py` generates, displays, explicitly confirms rotation of, and
  removes the private webcal capability token. It presents both HTTP(S) and
  `webcal://` URL forms, identifies whether Home Assistant supplied an
  external/cloud or internal-only base URL, and lets the user name the calendar.
  The token stays only in private config-entry options and is
  excluded from diagnostics, entity state, integration-authored logs, and public
  source fixtures. Home Assistant or reverse-proxy HTTP access logs may still
  contain the requested URL and therefore require private handling.
- `__init__.py` registers the process-lifetime webcal route and the response-only
  `render_digest` action. The caller
  owns scheduling, recipient selection, and email delivery; no parallel sender
  or scheduler exists inside the integration. Opt-in SMTP embedding adds
  `images` plus bounded download and expiry metadata to the response, but the
  immediately following caller-owned notify action remains the delivery owner.
- `__init__.py` also calculates ephemeral branch distances from Home Assistant's
  native configured latitude/longitude and the integration's public branch
  coordinates. Distance only selects which occurrences retain rich cards when
  the HTML budget is constrained; it never renders in the email. Home
  coordinates and calculated distances are not stored, logged, included in
  response metadata, or used to reorder the chronological email.
- `email_images.py` owns the deterministic publisher-image download limits,
  trusted redirect policy, dimension/orientation classification, CID filenames,
  integration-owned temporary storage, and guarded cleanup. Remote-image
  rendering remains the no-storage default so generic response consumers do not
  receive unusable CID references.
- `diagnostics.py` redacts child name and birth date and exposes only bounded
  per-source counts, type-expansion evidence, ordering, coverage boundaries, and
  health. High-volume shard failures remain available in on-demand diagnostics;
  entity state and action-response metadata retain a count and three examples.

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
recover the capped base prefix;
otherwise the limitation remains visible. At most twelve capped sources are
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
