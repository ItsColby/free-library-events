# Free Library Events v2026.8.11

## Fixed

- Distinguish a healthy publisher event-type ceiling from successful shards
  whose parsed, ordering, or boundary evidence is unusable. Healthy ceilings
  remain `limited`; integrity failures now remain operationally `partial`.
- Preserve whether the official event-type feeds recovered every capped
  base-feed item instead of flattening every unresolved expansion into one
  generic limitation.

## Diagnostics

- Record each unresolved event type with a stable reason, published and parsed
  counts, and last event date. On-demand diagnostics retain the complete bounded
  set; status and action metadata retain the count and three examples.
- Explain healthy source limitations with the exact capped event types and
  observed publisher boundaries so operators can review the official calendar
  without mistaking the publisher ceiling for an integration failure.

# Free Library Events v2026.8.10

## Fixed

- Remove the deprecated Home Assistant advanced-mode dependency from the
  matching and timing options form before Core removes that API.
- Avoid reloading the integration and requesting every source when an unchanged
  profile reconfigure form is submitted.

## Changed

- Keep matching and both bounded timing controls directly available in one
  small options form, and mark the options-flow factory as a Home Assistant
  callback.

# Free Library Events v2026.8.8

## Fixed

- Reevaluate the diagnostic status from cached coordinator data at the exact
  Tuesday local-midnight boundary where the next-week digest window advances,
  without performing feed I/O or duplicating Home Assistant's calendar timers.
- Reschedule that projection when Home Assistant's timezone changes, handle
  local DST boundaries, avoid unchanged state writes, and cancel the timer and
  timezone listener when the entity unloads.
- Raise a translated Home Assistant update error after complete source failure
  while retaining only bounded source-error categories.
- Reject initial and redirected publisher image URLs that specify a non-default
  HTTPS port.
- Abort a pending WebCal preview without saving or reloading when another flow
  or external update changes config-entry data or options before confirmation.
- Preserve future and unrecognized fields when reconfiguring profile data,
  saving behavior or WebCal options, and migrating older combined entries.
- Normalize overlapping event rows independently of feed order and let an
  inactive publisher title win so an older duplicate cannot hide a cancelled,
  postponed, or rescheduled occurrence.
- Reject digest generation when a concurrent reconfigure or reload supersedes
  the config-entry settings and coordinator during an awaited source refresh,
  instead of mixing source data and filtering settings from different
  generations.

## Changed

- Publish deeply immutable coordinator snapshots by detaching and freezing the
  source-count, source-status, and source-error mappings alongside the existing
  frozen event tuple.
## Validation

- Retain the dependency-closed Core 2026.8.0 supported-minimum lane and add a
  separate exact Core 2026.8.1 same-month compatibility lane. The latter runs
  the complete HA tests only after a bounded checker accepts either clean
  dependency closure or the single metadata-proven test-harness/Core pin
  mismatch.
- Cover immutable nested snapshots, translated total-source failure, captured
  status evaluation clocks, Tuesday-boundary reevaluation, timezone changes,
  DST behavior, no-op Recorder writes, rescheduling, and unload cleanup.
- Cover competing options flows and external profile updates during WebCal
  preview, token rotation and disable behavior, unrelated coordinator-result
  changes, and future-field preservation across every replacement path.
- Fail Home Assistant test collection when a required Core or harness import is
  unavailable instead of silently skipping the complete integration-test module.
- Install Home Assistant's exact Camera, TTS, and TTS-owned FFmpeg dependencies
  in both HA test lanes because the SMTP MIME-contract test imports those
  optional Core components transitively.
- Keep historical-clock Home Assistant tests deterministic by owning their
  projection timers instead of letting a past synthetic deadline fire against
  the runner's wall clock.

# Free Library Events v2026.8.5

## Fixed

- Replace raw source, image-transport, storage, and coordinator exception text
  with bounded allow-listed categories or fixed safe summaries in logs,
  diagnostics, status evidence, and action-response metadata.
- Translate all user-visible `render_digest` action errors through Home
  Assistant's exception translation contract.
- Keep one coordinator snapshot stable across every digest projection and image
  download await so a concurrent refresh cannot mix event generations in one
  response.
- Make the manual refresh button raise a translated Home Assistant error when
  the requested source refresh fails.
- Refuse to save a WebCal token when Home Assistant cannot provide either an
  internal or external base URL.
- Remove lower-level transport and private config values from safe wrapper
  exception chains, and keep every source-health value on the allow-listed
  category contract.
- Replace the public-safety guard's potentially exponential local-hostname
  regular expression with a linear token scan and an adversarial regression
  test.
- Install the Home Assistant test harness before upgrading to the exact Core
  release under test, avoiding resolver failures when the newest harness still
  declares a matching beta Core dependency.
- Reject DTD and entity declarations before parsing RSS, including multibyte
  UTF-16 and UTF-32 payloads, while continuing to accept benign UTF-16 feeds.

## Changed

- Return Local Media-backed `digest.attachments` ready for Home Assistant's
  native `smtp.send_message` action while retaining rollback-compatible
  `digest.images` output for existing consumers.
- Move service-action and entity icons into Home Assistant's current metadata
  owner, translate the `render_digest` action and its fields, and expose the
  diagnostic status as a translated enum without changing its raw automation
  values.

## Validation and security

- Align the HACS minimum and the single Home Assistant compatibility lane with
  the maintained runtime, Core `2026.8.0`.
- Guard the two-step harness/Core installation order with a static regression
  test so future dependency updates cannot silently restore the resolver
  failure.
- Reconcile services and entity translation keys with current icon metadata,
  validate every integration JSON file, and prove ordinary and embedded-image
  action responses remain JSON-serializable.
- Align HA-lane assertions with the safe source-category contract and cover
  concurrent snapshot replacement, refresh-button failure, missing URL setup,
  and exception-cause redaction.
- Run the latest Ruff, ShellCheck, actionlint, and zizmor releases in validation;
  enable Ruff's stable native, blind-exception, and Pylint convention checks;
  retain ambiguous-Unicode detection; add focused network, cryptography, and
  comprehension checks; and ratchet complexity to the current demonstrated
  ceiling.
- Enforce Ruff's exception-name suffix rule and align the private image-download
  exception name without changing its fallback behavior.
- Add zero-baseline Ruff Bugbear, timezone-awareness, and logging checks while
  retaining the existing debugger-statement rule.
- Validate Core `2026.8.0` with test harness `0.13.354`, whose
  dependency metadata now targets that final release directly.
- Let the latest Home Assistant test harness own its compatible pytest version
  instead of overriding it with a redundant direct pin, and fail validation
  when `pip check` finds an inconsistent dependency environment.
- Pin every third-party GitHub Action to a full commit SHA, disable persisted
  checkout credentials, bound job runtimes, add weekly validation and
  Dependabot Actions and Python dependency updates, and expose one stable
  `Release gate` check.

# Free Library Events v2026.7.29

## Fixed

- Serve standards-compatible `HEAD` responses for the private calendar feed so
  subscription services can validate the URL without downloading the body.
- Add representation-derived `ETag` and coordinator-derived `Last-Modified`
  validators. Conditional `GET` and `HEAD` requests now return `304` when the
  cached calendar is unchanged, while a newly fetched event snapshot produces
  a new validator.

## Documentation

- Identify the canonical HTTPS URL as the form to paste into Google Calendar
  and reserve `webcal://` for client/OS subscription handoff.
- Document that every published DNS address must reach the reverse proxy and
  that the calendar path must bypass interactive or proxy Basic Auth. The
  opaque feed token remains the sole credential for this narrowly scoped path.

# Free Library Events v2026.7.28

## Added

- Add an opt-in, token-protected iCalendar subscription generated dynamically
  from the same current, age-filtered coordinator cache as the native Home
  Assistant calendar. The flow presents canonical HTTPS and `webcal://` URLs,
  supports a user-defined calendar name, and does not force a publisher refresh
  when a calendar client polls the feed.

## Changed

- Separate required profile data from optional behavior: setup and Reconfigure
  own the person's display name, birth date, and a registry-generated branch
  multi-select, while Configure provides matching, advanced timing, and calendar
  subscription menus.
- Add a backward-compatible version-1.2 config-entry migration that preserves
  existing profile, branch, matching, timing, and WebCal values while moving
  them to their native data or options owner. Synchronized legacy branch fields
  preserve selected branches if the integration is downgraded to v2026.7.26.
- Show whether the subscription URL uses an external/cloud or internal-only
  Home Assistant base URL. Regenerating an active URL now requires an explicit
  confirmation and immediately invalidates the prior token after reload.

## Security

- Follow at most two RSS redirects and require every source and redirect target
  to remain HTTPS on the trusted Free Library publisher hosts.
- Keep the WebCal capability token out of entities, diagnostics,
  integration-authored logs, and public fixtures. Disabled, invalid, and
  unloaded subscription URLs fail closed with `404`, and the feed contains only
  filtered public event information—not the configured name, birth date, or
  calculated age.

## Fixed

- Keep the map pin as plain text while preserving the Google Maps link on the
  location label, so Gmail cannot style the pin as part of the linked target.

# Free Library Events v2026.7.26

## Fixed

- Render square and portrait event artwork in a centered poster row above the
  full-width title and metadata. The safe base table no longer depends on a
  Gmail mobile media query to avoid a cramped image/title split, while clients
  that honor responsive CSS can still expand the poster to the card width.

# Free Library Events v2026.7.25

## Fixed

- Preserve trusted publisher image URLs when Home Assistant receives a
  Cloudflare challenge or rate-limit response while embedding them, so the
  email retains its photo elements for clients that can load the trusted URLs
  instead of removing the images entirely. Unsafe redirects, unsupported
  content, oversized files, and true missing-image responses remain omitted.
- Keep the map pin inside the linked location on narrow email clients so it
  cannot be stranded on a line by itself.

# Free Library Events v2026.7.24

## Changed

- Refine the weekly email for phone-first reading with a concise subject and
  header, separate time and location lines, larger touch targets and body copy,
  edge-to-edge event artwork, useful source-backed highlights, the clearer
  `Library age listing:` label, responsive branch-calendar links, and no visible
  home-relative distance.
- Return only CID image paths still referenced by the final budgeted HTML, so
  compacted or omitted cards do not create unused SMTP attachments.
- Use exact occurrence identities as native Home Assistant calendar UIDs so a
  recurring series that shares one publisher URL cannot collapse separate
  dates in calendar consumers.

# Free Library Events v2026.7.23

## Changed

- Add opt-in, LLM-free SMTP image embedding to `render_digest`: bounded
  publisher downloads are validated, stored under an integration-owned random
  Home Assistant `www` run, rewritten to matching CID references, and returned
  as notifier-ready local paths. Individual image failures omit only the image
  and remain visible in bounded response metadata.
- Rework each digest card into a wider full-column image beside scan-first
  title, time, location, audience, and highlights, followed by a divided
  full-width description and action row. Landscape artwork becomes an
  edge-to-edge full-width hero while square/portrait artwork uses a wider side
  column and fills stacked narrow cards; both preserve the publisher's aspect
  ratio without cropping or artificial gutters.
- Preserve safe publisher paragraphs, links, bold/emphasis, and list structure
  while stripping scripts, styles, event handlers, and unsafe URLs.
- Show all official age categories in one muted `Listed for:` audience line and
  derive only useful, nonredundant highlights from reliable RSS wording. More
  specific take-home details suppress broader activity labels, generic breadth
  labels are omitted when the published audience already conveys them, and
  source-backed provided materials remain visible. Activity labels already
  obvious in the title and generic event-page taxonomy are omitted. Cap each
  card at five highlights, prioritizing required actions, logistics, then
  secondary topics, and reject negated or audience-qualified claims, including
  both spellings of canceled/cancelled and explicit no-materials wording.
- Bound display titles, descriptions, Google Calendar details/URLs, event count,
  and final HTML at 80,000 UTF-8 bytes. When compaction is required, use
  ephemeral distance from Home Assistant's configured location to public branch
  coordinates to preserve rich cards for nearby branches without returning or
  storing coordinates/distances; keep visible order chronological and disclose
  any farthest overflow omission.
- Preserve distinct recurring occurrences when a series reuses one event URL by
  including branch, date, and start time in its identity; retain both the simple
  publisher event IDs and exact occurrence IDs in response metadata.
- Recognize explicit online and hybrid events, broader confidently named venue
  types, rooms, and floors; omit misleading map links for online-only events and
  retain the physical destination plus unlinked online context for hybrid
  events. Keep off-site hosting context in compact as well as rich cards.
- Restore a generic title after whitespace cleanup and match dynamic event icons
  on whole words so titles such as `Community Party` and `Bread Making` do not
  receive unrelated art/book icons.
- Keep Google Calendar as the single direct calendar action and put one precise
  placeholder-duration disclosure in the footer when any included event lacks
  a published end time.
- Keep an explicit off-site venue as the Maps/calendar destination while visibly
  identifying the hosting branch outside the Maps link.
- Replace technical source-health detail in the recipient body with one concise
  completeness warning; retain errors, warnings, and supplemental evidence in
  response metadata and diagnostics.
- Add a complementary schedule-and-action preheader; improve highlight
  size/contrast, harden preheader hiding, card/day spacing, and the calendar
  button's touch target across email clients, use compatible percentage line
  heights, give linked images functional alternative text, and hide decorative
  event emoji from assistive technology.

## Maintenance

- Delete embedded-image runs one hour after rendering, purge expired runs before
  later renders, and clear abandoned prior-process runs during setup. Strict run
  names and ownership markers keep cleanup confined to integration-owned files.
- Omit truly blank image fields instead of resolving them to the RSS endpoint,
  while retaining the publisher's working dot-prefixed image paths; auto-load
  event photos only from the Free Library's HTTPS hosts.
- Follow at most two trusted publisher HTTPS image redirects, classify validated
  image dimensions for layout, and use the original trusted remote URL only for
  transient transport/server, storage, and digest-level count/total-size
  failures. Unsafe redirects, unsupported content, permanent HTTP failures, and
  individually oversized images remain omitted.
- Keep image tests in the Home Assistant dependency job while the
  dependency-light unit job remains runnable with only Ruff installed.

# Free Library Events v2026.7.22

## Added

- Query every official age category in the configured person's current
  life-stage group so explicitly inclusive events remain discoverable and every
  cached event retains publisher age provenance.
- Expand an unresolved feed at or above the observed ten-item boundary across
  the publisher's official event-type filters, recovering later events even
  though the RSS endpoint ignores `page=2`.

## Changed

- Let strong published inclusion wording override a nonmatching feed category
  while keeping numeric age ranges authoritative and rejecting generic family
  wording alone.
- Distinguish the official ten-item supplemental age-feed limit (`limited`) from
  operational source or parsing failures (`partial`).
- Bound adaptive type expansion to twelve capped feeds per refresh so even three
  overlapping current-age categories cover all four branches before the nearest
  supplemental age windows; share an eight-request ceiling across all RSS
  traffic.
- Replace ambiguous status attributes with the next-week event count, cached
  events by branch, and separate current-age and supplemental-age coverage
  indicators.
- Use an explicitly named off-site venue as the Maps and calendar destination,
  and show a specifically named or numbered room with its branch when either is
  published in the RSS description.
- Preserve safe contextual links embedded in official RSS descriptions across
  the HTML digest, plain text, Google Calendar links, and the HA calendar.
- Consolidate duplicate feed copies before matching and rendering, retaining
  richer safe fields instead of allowing a later copy to overwrite them.
- Omit published occurrences whose title marks them cancelled, canceled,
  postponed, or rescheduled instead of presenting stale activities.
- Recognize an explicit end range whose first meridiem is omitted only when the
  event's published start makes that range unambiguous.
- Recognize a conservative whole-event duration statement such as a “90-minute
  class” as a confident end time without inferring from unrelated timing text.
- Return supplemental-age failures and feed-cap limitations in render-response
  metadata so native Home Assistant traces retain completeness evidence without
  adding diagnostic clutter to the email.
- Expose each expanded source's discovered-event count, type-feed request count,
  bounded failure summary, and proven coverage boundary in the status sensor and
  render-response metadata; retain the complete failure list in on-demand
  diagnostics.
- Add the source refresh timestamp to render-response metadata so a native Home
  Assistant trace proves which coordinator snapshot produced the payload.

## Maintenance

- Skip malformed individual RSS items instead of discarding their whole feed,
  bound remote item and field sizes, and retain published-versus-parsed evidence
  in diagnostics.
- Suppress structurally empty image filenames from the official feed instead of
  rendering a broken image; auto-load event photos only from the Free Library's
  HTTPS hosts, while preserving their full aspect ratio.
- Reject malformed, credential-bearing, or non-HTTP event and contextual URLs;
  require publisher-hosted HTTPS images and resolve safe relative URLs against
  the official Free Library source.
- Reject RSS responses over 256 KiB, propagate refresh cancellation, coerce
  non-UI boolean values safely, and keep every RSS request under the same global
  concurrency ceiling; stop a stalled capped-source expansion after 90 seconds
  while retaining its base events and reporting unresolved coverage.
- Normalize the configured display name to one bounded line before it reaches an
  email subject or HTML body.
- Recognize mixed-unit and newborn numeric age ranges while keeping the child's
  configured birth date as the only household input to age calculations.
- Prefer the more informative official description when duplicate feed copies
  disagree instead of retaining whichever nonempty description arrived first.
- Stop polling the Senior source for younger adults; adult source selection now
  follows only the official age windows that actually overlap.
- Prevent room extraction from crossing description line boundaries and
  misreading a later schedule date as a room number.
- Keep protected event-page and ICS scraping out of the runtime after native HA
  HTTP-client replay proved those routes return browser challenges; unavailable
  fields remain omitted rather than guessed.
