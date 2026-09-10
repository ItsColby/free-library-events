# Architecture

Free Library Events polls selected Free Library of Philadelphia RSS feeds,
normalizes their event occurrences, and applies one person's age settings to
calendar and digest projections. Home Assistant owns configuration, entity
lifecycle, scheduling primitives, HTTP serving, and notification delivery.

This document describes the runtime contract and its limits. See the
[user guide](usage.md) for configuration and automation examples, and
[development guide](development.md) for validation and release procedures.

## Product boundary

The integration owns feed acquisition, deterministic matching, native calendar
and health entities, a response-producing digest action, and an optional
calendar subscription endpoint. Those are reusable parts of presenting the same
library data. They share one coordinator and require no second integration.

The operator owns the person's profile, branch selection, acceptable matching
mode, delivery schedule, recipients, notification service, and network exposure.
Household decisions and workflows involving other services belong in private
Home Assistant configuration. The product does not send messages, create
registrations, add events to external accounts, or track attendance or delivery.

The boundaries between source and calculation are explicit:

| Information | Owner and treatment |
| --- | --- |
| Titles, dates, start times, descriptions, links, images, and age-category labels | Publisher RSS; parsed and normalized locally |
| Branch registry | Public metadata in `digest.py`; four supported branches, not automatic discovery of every library |
| Numeric meanings of age categories and text-based fit ranks | Local rules in `digest.py`; category names come from the publisher, numeric windows do not |
| End time, venue, room, modality, and presentation highlights | Extracted from recognizable RSS wording; missing end times receive a disclosed configurable placeholder |
| Name, birth date, filter, selected branches, and Webcal settings | Private config entry; no hard-coded household profile |
| Branch distance used for email budgeting | Calculated locally from Home Assistant's coordinates and public branch coordinates; not travel time |
| Delivery, reminders, registration, and external-calendar polling | Caller, calendar client, or publisher; outside the integration's guarantees |

Runtime code lives in `custom_components/free_library_events/`:

| Module | Responsibility |
| --- | --- |
| `config.py`, `config_flow.py`, `const.py` | Settings, migrations, configuration flows, stable identifiers |
| `api.py` | Bounded RSS requests, parsed feed evidence, event-type expansion |
| `coordinator.py`, `runtime.py` | Source plan, refresh lifecycle, normalized cache, latest attempt evidence |
| `digest.py` | Parsing, occurrence identity, matching, safe links and markup, digest rendering |
| `calendar_data.py`, `calendar.py`, `webcal.py` | Shared calendar projection, native entity, iCalendar subscription |
| `sensor.py`, `button.py`, `entity.py` | Status projection, manual recovery, shared service device |
| `__init__.py`, `email_images.py` | Setup, digest action orchestration, optional temporary CID images |
| `diagnostics.py` | Redacted configuration and source-health evidence |

## Configuration and identity

There is one config entry and one service device. The entry's runtime data is
the typed `LibraryDataCoordinator`; entities do not create independent pollers.
The entry and device use the static integration name.

Config-entry version 1, minor version 2 separates required profile data from
optional behavior. Data holds the display name, birth date, and supported branch
codes in registry order. Options hold matching, placeholder duration, polling,
and Webcal controls. Legacy branch booleans remain synchronized compatibility
mirrors. Migration reads legacy options overrides, preserves effective settings,
and retains unrecognized values in their existing data or options owner.

Reconfiguration updates the profile; unchanged profile submissions do not
reload. Options use Home Assistant's reload-on-save flow. Webcal enabling or
rotation stages a complete proposed options mapping and shows its URLs before
saving. Confirmation rejects the proposal if either entry data or options
changed after staging. Disabling publication removes the token.

These identifiers are compatibility contracts:

| Surface | Stable identifier |
| --- | --- |
| Integration and config-entry unique ID | `free_library_events` |
| Service-device identifier | `("free_library_events", "free_library_events")` |
| Calendar unique ID | `free_library_events_calendar` |
| Status unique ID | `free_library_events_status` |
| Refresh-button unique ID | `free_library_events_refresh` |
| Digest action | `free_library_events.render_digest` |
| Webcal route | `/api/free_library_events/calendar/{token}.ics` |

Home Assistant entity IDs can be renamed; they are distinct from these unique
IDs. The stored `child_name` key remains for compatibility even though the
profile and user interface support a person of any age.

## Source acquisition and coverage

The supported registry contains Charles Santore (`SWK`), Independence (`IND`),
Parkway Central (`CEN`), and Philadelphia City Institute (`PCI`). Each selected
branch is queried through `eventsrss.cfm` with official age-category filters.
Runtime acquisition does not scrape event pages or fetch publisher ICS files.
Safe links to those pages may still appear in output.

Each refresh recomputes the source plan using the person's age from today
through 90 days ahead. A minor's plan includes Baby through Young Adult to find
inclusive events published under narrower labels. An adult's plan uses the
locally applicable Young Adult, Adult, or Senior windows. A window crossing
adulthood includes both sides. This horizon selects age feeds; it does not
promise 90 days of event availability.

All RSS requests share an eight-request semaphore. Each HTTP request has a
20-second timeout, accepts at most 256 KiB of decoded response data, and follows
at most two redirects. Initial and redirected URLs must use HTTPS on
`libwww.freelibrary.org` or `www.freelibrary.org`, without embedded credentials
or a nonstandard port. Parsing runs outside the event loop.

`BranchFeed` records published item count, parsed count, date ordering, final
parsed event date, and expansion evidence separately from its normalized rows.
The coverage model uses the observed ten-item RSS boundary:

- A feed with fewer than ten items and every item parsed is treated as covering
  the requested horizon, including an empty feed.
- At ten or more items, a fully parsed, ordered feed must reach a date strictly
  after the horizon. Reaching its final day is insufficient because more events
  on that day may be missing.
- An unresolved fully parsed, ordered capped feed can be expanded through the
  19 event types listed in `OFFICIAL_EVENT_TYPES`. There is no pagination loop.

The coordinator expands at most twelve sources per refresh, prioritizing
current-age windows, then the nearest supplemental windows, with deterministic
branch ordering. Each expansion has a 90-second deadline. Expansion failure
preserves the base feed; successful shards contribute rows even when other
shards fail.

Expansion proves coverage through the digest week's end only if every type
feed succeeds and covers that horizon, and the combined shards recover every
base occurrence. Individual blockers retain their reason, event type, counts,
and last date. An ordered type feed still capped before the horizon differs
from malformed, incompletely parsed, unordered, or unavailable source evidence.

These are bounded claims about the queried RSS feeds and maintained taxonomy.
They do not prove that the publisher listed every event, assigned every useful
category, or left its feed limit and taxonomy unchanged. A longer calendar
range is limited to the rows already obtained; reading it does not extend
acquisition or coverage.

## Normalization and matching

`Event` and its nested source values are immutable. The parser requires usable
event date and start time, bounds individual fields and item count, and skips
invalid rows while retaining the published-versus-parsed mismatch. It rejects
XML DTD and entity declarations. RSS description markup passes through an
allow-list sanitizer; safe HTTP(S) links, paragraphs, emphasis, and lists can
survive, while executable markup cannot. Image URLs have a narrower publisher
host allow-list.

Occurrence identity is the source link, or normalized title when no link is
available, followed by branch code, event date, and start time. Thus one series
URL can identify several distinct occurrences. Display-title shortening does
not change identity. A publisher URL change, or a title change when no URL
exists, can change identity; this is not an upstream immutable event-ID service.

`merge_events` uses a deterministic order independent of feed arrival. It unions
official age classifications and safe related links, retains richer descriptive
content, and fills available image, end-time, venue, and room data. For the same
identity, a title marked cancelled, canceled, postponed, or rescheduled takes
precedence. Calendar and digest projections omit those inactive occurrences.
No cancellation record or historic occurrence ledger is maintained.

Matching evaluates age on the event date. Recognized explicit age restrictions
take precedence, then applicable official category labels under the local age
windows, then deterministic audience wording. Explicit inclusive language can
recover an event whose category is narrower than its description. An unrelated
official category is not silently replaced by generic activity-title inference.
`Strict`, `Recommended`, and `Broad` select progressively wider fit ranks; the
user guide explains their practical use. These are deterministic relevance
rules, not eligibility or registration decisions from the publisher.

RSS start times are interpreted in `America/New_York`. An explicit matching
time range or recognized duration in the description supplies an end time only
within the parser's 15-minute to eight-hour bounds. Otherwise calendar outputs
use the configured duration and label it as a placeholder. Venue, modality,
and logistics highlights are text-derived presentation; they do not add source
taxonomy or alter age inclusion.

## Refresh, recovery, and health

The config-entry-owned Home Assistant coordinator handles polling and debounced
refresh triggers. Overlap is bounded to a running refresh and a pending
follow-up. A manual refresh or forced digest waits for a completed attempt,
including work already in flight, with a ten-minute caller deadline. Cancelling
or timing out a caller does not cancel shared acquisition. Coordinator unload
stops its scheduled work and releases waiting callers with failure.

A refresh with at least one successful base source publishes a new immutable
`LibraryData` snapshot: merged event tuples, read-only source mappings, and one
fetch timestamp. Failed sources are recorded, but their previous rows are not
merged into this new partial snapshot. When every base source fails, the update
fails and the last successful snapshot remains retained.

`RefreshAttempt` separately records the latest completed base-source attempt,
including source keys, allow-listed error categories, retryable count, completion
time, and retry decision. Repeated failures update this evidence even when Core
would suppress an unchanged failed state notification.

The first complete failure in a continuous failure streak requests one
five-minute retry only when every failure is retryable. Retryable failures are
transport failures and the selected HTTP statuses in `api.py`; TLS policy,
redirect, parsing, and size failures do not qualify. A repeated complete failure
returns to the configured polling interval. Any partial or full success resets
the allowance. Initial setup follows Core's setup retry policy.

The diagnostic status remains available while the entry is loaded:

| Raw state | Meaning for the selected digest week |
| --- | --- |
| `error` | Latest refresh failed completely |
| `partial` | A current-age source failed or lacks coverage evidence, or supplemental acquisition has an operational failure |
| `limited` | Current-age coverage is satisfied but healthy supplemental feeds remain limited |
| `ok` | No current or supplemental source issue detected by the coverage model |

`ok` does not certify publisher completeness or message delivery. Counts and
coverage attributes describe the retained cache; latest-attempt attributes
describe the most recent attempt. The refresh button also remains available
after failure and raises an error if its awaited attempt fails.

Digest selection uses Home Assistant's local date: Monday includes that Monday's
week, while Tuesday through Sunday select the following Monday through Sunday.
The sensor recalculates this projection at Tuesday local midnight without RSS
I/O, responds to timezone changes, and removes its timer and listener on unload.
Core owns the native calendar entity's current/upcoming-event scheduling.

## Calendar projections and subscriptions

`calendar_data.py` builds one age-filtered calendar model used by both native
Home Assistant calendar queries and Webcal. It includes source descriptions,
safe related links, official-details links, locations, and any placeholder-end
note. Native range queries return cached events overlapping the requested
interval. Email display budgets do not truncate this calendar model.

Webcal serializes the current model as RFC 5545 content with UTC timestamps,
escaped text, UTF-8-safe line folding, and occurrence-based UIDs. The route is
registered once per process and accepts `GET` and `HEAD`. Publication must be
enabled, the entry loaded, and the opaque token matched using constant-time
comparison. Invalid, disabled, or unloaded tokens return `404`; an otherwise
valid entry without cached data returns `503` with a retry hint.

The endpoint never refreshes sources. It can serve retained data after a
complete acquisition failure. `ETag` hashes the serialized body;
`Last-Modified` reflects the later cache/config-entry timestamp. Conditional
requests can return `304`, and HTTP caching allows five minutes before
revalidation. The iCalendar refresh hints reflect the configured source polling
interval, but clients control their own polling and cached-event removal.

The URL token is the credential for this route; Home Assistant bearer login is
not required. URL generation prefers a configured external/cloud address and
otherwise discloses an internal-only address. A generated URL does not establish
DNS, TLS, proxy, firewall, or calendar-provider reachability. `webcal://` is a
client handoff form of the HTTP(S) subscription address.

## Digest response and temporary images

`free_library_events.render_digest` is response-only and requires exactly one
loaded entry. It returns `subject`, plain-text `message`, `html`, and `metadata`.
`force_refresh` defaults to `true`; a failed forced refresh raises an error.
With `false`, the action can render the retained cache without a new attempt,
so consumers must interpret `metadata.fetched_at` as the source timestamp.

The action captures configuration and coordinator ownership before an awaited
refresh and rejects ownership or settings changes detected afterward. It then
captures one immutable data snapshot for rendering and optional image work.
Later refreshes cannot mix new rows or timestamps into that response.

Email rendering bounds descriptions, links, event count, and HTML size
(100 events and 80,000 HTML bytes). Under pressure it keeps nearer branches'
rich cards, uses compact cards, and can omit farther occurrences. Local branch
distance also prioritizes optional image downloads. Without usable coordinates,
the ordering falls back deterministically to date, branch, and title. Final
presentation stays chronological; the bodies disclose email-only omissions.
Matching counts and occurrence IDs describe the full matched set, while
email-specific counts describe its rendered subset.

The pure renderer does not perform I/O. `embed_images`, which defaults to
`false`, adds bounded image acquisition in the action layer. It attempts at
most twelve unique publisher images with four concurrent requests, a 15-second
HTTP request timeout, two trusted redirects, a 3 MiB per-image limit, and a
15 MiB stored-image total. Supported file signatures are checked; available
dimensions guide layout. Temporary request failures and aggregate limits can
fall back to remote images. Unsafe redirects, unsupported content, and
oversized individual images are omitted.

Successful downloads live in a random, marked run directory under Local Media
when configured, with a legacy `www` fallback otherwise. The response's `images`
contains local paths; `attachments` contains native SMTP media-source objects
only when a Local Media directory is available. Both select only CIDs referenced
by the final HTML. Cleanup is scheduled after one hour, stale runs are purged before
embedding, and setup purges previously marked runs from current and legacy
locations. Cleanup checks integration-owned directory names and markers and
preserves unrelated files. These files are temporary delivery inputs, not a
durable archive or a retry queue.

The caller must deliver the response using its chosen notification service.
Rendering, downloaded images, calendar links, and SMTP attachment objects do
not establish successful delivery or an external calendar subscription.

## Diagnostics and privacy

Diagnostics redact the display name, birth date, and custom calendar name.
Effective runtime configuration excludes the Webcal token. Invalid stored
settings yield `invalid_config` without returning the malformed configuration.
Source and coordinator exceptions become bounded categories rather than raw
transport errors. Diagnostics retain full finite source-expansion evidence;
entity state and response metadata bound failure/blocker examples to three.

RSS acquisition sends selected branch and category queries to the publisher,
not the stored name or birth date. Coordinates and calculated distances remain
ephemeral: they are not rendered, logged, persisted, or returned in metadata.
The digest intentionally contains the configured display name and derived age;
action traces and downstream messages therefore require private handling.
Embedded-image responses also contain local file paths.

Anyone with an enabled subscription URL can read its filtered events and
configured calendar name. Filtering can reveal interests or an approximate age
group even without including the stored birth date. Tokens are omitted from
integration diagnostics, entities, and authored logs, but HTTP access logs and
calendar clients may retain subscription URLs. Network exposure and handling
of those external records remain deployment responsibilities.
