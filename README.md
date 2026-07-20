# Free Library Events for Home Assistant

Free Library Events is a Home Assistant custom integration that turns selected
Free Library of Philadelphia branches into an age-aware calendar and a response
action for weekly email digests.

The integration currently supports:

- Charles Santore Library (`SWK`)
- Independence Library (`IND`)
- Parkway Central Library (`CEN`)
- Philadelphia City Institute (`PCI`)

It uses deterministic parsing and age-matching rules. No LLM or external AI
service is used at runtime.

## Features

- Native **Settings > Devices & services** setup and options flow
- One age-filtered Home Assistant calendar
- Optional token-protected, dynamically generated iCalendar subscription feed
- `Strict`, `Recommended`, and `Broad` age-match modes
- Configurable child name and birth date
- Configurable branch selection, refresh interval, and placeholder duration
- Manual refresh button and diagnostic status sensor
- Official branch-and-age RSS queries for every category in the configured
  person's current life-stage group, with duplicate consolidation
- Coverage-aware operation that distinguishes source failures from the observed
  ten-item boundary and adaptively expands unresolved feeds at or above that
  boundary through official event-type filters
- Redacted integration diagnostics
- Response-only `free_library_events.render_digest` action returning:
  - subject
  - plain-text message
  - responsive HTML email
  - bounded generation and source-coverage metadata
- Optional LLM-free SMTP image embedding with bounded publisher downloads,
  notifier-ready CID attachments, and automatic temporary-file cleanup
- Each included event uses an orientation-aware responsive card: landscape
  artwork spans the card, while square/portrait artwork uses a centered poster
  row above the full-width title, time, location, audience, and planning
  highlights; the description and prefilled Google Calendar link follow below
- Safe contextual links embedded in official RSS descriptions remain clickable;
  non-HTTP links are discarded
- An explicitly named off-site venue in published RSS text replaces the branch
  as the map/calendar destination, while a specifically named room refines the
  branch location; an off-site listing still names its hosting branch
- Event images preserve their published aspect ratio rather than being cropped
- A muted `Library age listing:` line shows every official age category, while
  compact
  highlights show only useful, nonredundant context proved by reliable RSS
  wording: secondary activities, accessibility, participation, take-home
  materials, weather or supply cautions, and registration. At most five are
  shown, ordered as action needed, logistics, then secondary topics
- Explicit online and hybrid wording changes location treatment without
  turning incidental phrases such as “online play” into a virtual event

## Installation through HACS

[Open this repository in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=ItsColby&repository=free-library-events&category=integration)

1. In HACS, open **Custom repositories**.
2. Add this repository as an **Integration**:

   ```text
   https://github.com/ItsColby/free-library-events
   ```

3. Download **Free Library Events**.
4. Restart Home Assistant.
5. Go to **Settings > Devices & services > Add integration** and add
   **Free Library Events**.

HACS installs custom integrations under Home Assistant's
`custom_components` directory and provides release selection, update entities,
redownload, and pending-restart handling.

## Configuration

The setup flow asks for:

- the person's display name
- the person's birth date
- one or more supported library branches in one multi-select field

The display name and birth date stay in the Home Assistant config entry and are
used only for local filtering and rendering. They are redacted from
downloadable diagnostics. Network requests download official custom RSS feeds
for each selected branch and every published age category in the configured
person's current life-stage group. For minors, that means the Baby through
Young Adult categories. At adulthood it follows only the Adult, Senior, or
overlapping Young Adult windows that actually apply; a forward source window
that crosses adulthood uses both sides of the transition. This recovers
publisher classifications without putting the birth date,
display name, or calculated age in any request. All supported branches are
enabled by default. Use the integration's **Reconfigure** action to change the
person or selected branches.

The **Configure** menu separates optional behavior from required profile data:

- **Matching and timing** changes the age-match mode. Home Assistant's
  **Show advanced options** control reveals the placeholder event duration and
  source refresh interval when those technical defaults actually need tuning.
- **Calendar subscription** enables or disables the private feed and controls
  the name shown by calendar clients.
- **Regenerate calendar subscription URL** appears only while publishing is
  enabled and uses a separate confirmation step because it invalidates every
  existing subscriber.

The options flow can also publish the filtered calendar at a private,
unguessable subscription URL. Publishing is disabled by default. When enabled,
Home Assistant shows both the canonical HTTP(S) URL and the `webcal://`
convenience URL before saving. It also distinguishes an external or Home
Assistant Cloud URL from an internal-only URL without claiming that an
unverified proxy is reachable. Regenerating the URL immediately invalidates the
old token after reload; disabling publishing removes it.

### Match modes

- **Strict** includes explicit numeric or developmental-stage matches.
- **Recommended** adds clearly inclusive and likely-fit children's events.
- **Broad** also includes general child/family events without a specific age.

Published numeric age ranges override the official feed category and general
wording such as “all ages.” A matching official age category is a best match;
when a category is too narrow, explicit inclusive wording such as “smallest
kiddo,” “littlest littles,” or “range of ages” can still qualify the event.
Generic family wording alone does not override a nonmatching category. When an
event appears in more than one feed, it is shown once and retains all published
age classifications plus any richer safe fields from either copy.

## Calendar

The integration creates one calendar containing only events that match the
configured child and mode. Each calendar event includes:

- the official title and description
- the explicit off-site venue or branch address, plus a specifically named or
  numbered room when published in the RSS description
- safe contextual links published inside the description
- the official event page
- a disclosed placeholder end time when the feed omits one

The calendar entity does not send email or create Google Calendar events.

### Calendar subscriptions

Enable **Publish a private calendar subscription feed** under
**Settings > Devices & services > Free Library Events > Configure** to subscribe
from Apple Calendar, Outlook, Google Calendar, or another iCalendar client.
The feed is generated from the same current coordinator cache as the native Home
Assistant calendar. Calendar clients periodically fetch the URL; the endpoint
does not force a publisher refresh or push events to clients.

The subscription route is available beneath the Home Assistant URL in either
form:

```text
https://home-assistant.example/api/free_library_events/calendar/<token>.ics
webcal://home-assistant.example/api/free_library_events/calendar/<token>.ics
```

The opaque token is the feed credential because calendar subscription clients
generally cannot sign in through Home Assistant's interactive authentication.
Treat the full URL as a password. It may appear in Home Assistant or reverse
proxy access logs. The feed contains only filtered public event information and
does not include the configured child name, birth date, or calculated age.
Invalid, disabled, and unloaded tokens return `404` without identifying which
part failed. External subscriptions require the configured Home Assistant URL
and proxy to route this path to Home Assistant over HTTPS; no additional public
port is required when the existing proxy forwards all paths. For a DuckDNS
deployment, the generated HTTPS URL uses the configured DuckDNS external URL.

## Weekly email action

`free_library_events.render_digest` refreshes the selected feeds by default and
returns an email payload plus explicit source-coverage metadata. It must be
called with `response_variable`.

The digest states the child's conversational age once: weeks before 2 completed
months, months through 23 months, half-years near the half-year mark below age
5, and years thereafter. Each event keeps its description primary without
repeating the matching rationale. Source paragraph boundaries are preserved so
multi-paragraph descriptions do not collapse into one dense block. Landscape
artwork uses a full-width hero row; square and portrait artwork uses a centered,
fluid poster row above full-width metadata without cropping. This stacked base
structure remains readable even when a mobile email client ignores responsive
CSS. The full description uses the card width below. Official age categories
appear once in a muted
`Library age listing:`
line directly with the title, time, and location. Strongly evidenced secondary
activities, accessibility, participation, take-home materials, and planning
details appear there as compact highlights, but a format already obvious in the
title is not repeated. Action items are shown first, followed by logistics and
then secondary topics, with a five-highlight cap. Negated or
audience-qualified claims are not promoted. A
more specific highlight suppresses its broader equivalent, and a generic breadth
label is omitted when the published audience already conveys it. Generic
event-page labels such as Family Programs, Storytimes, Children, and Family are
also omitted. An end time appears beside the start time only when the RSS
description contains an explicit range matching the published start, including
ranges whose first meridiem is unambiguous from that start, or a conservative
whole-event duration such as a “90-minute class”; otherwise it is omitted. The
location pin remains plain text while the location label links to Google Maps;
the title and image link to the official event. An explicitly online event uses
`Online` with no misleading map link. A hybrid event retains the physical
destination and visibly names its online option.

When the RSS text explicitly names an off-site park, square, playground,
garden, museum, community/recreation center, school, theater, studio, gallery,
plaza, courtyard, field, pool, market, pavilion, campus, or center, that venue
replaces the hosting branch as the map and calendar destination. Specifically
named/numbered rooms and floor locations are shown with their branch. An
off-site location line also identifies the hosting branch without making that
context part of the Maps link.

Contextual links embedded by the library remain linked in HTML and are listed
after the description in plain text. The email-client-safe calendar button opens
a prefilled Google Calendar event. The linked event title and image remain the
route to the official details page, with functional image alternative text that
names that destination. When the feed has no end time, both email bodies visibly
disclose the configured placeholder used by the calendar link.

For SMTP, set `embed_images: true` to make image display independent of the
recipient's remote-image setting. This deterministic mode downloads only the
unique publisher images used by the selected events, follows at most two
publisher-hosted HTTPS redirects, validates signatures and dimensions, stores
them in an integration-owned random run directory under
Home Assistant's `www` directory, rewrites the matching HTML sources to SMTP
`cid:` references, and returns the local paths as `digest.images`. It does not
use an LLM. Downloads are limited to 12 images, 3 MiB per image, 15 MiB in
total, four concurrent requests, and 15 seconds per request. A trusted original
URL remains available as a remote-image fallback for transient transport/server,
storage, digest count/total-size limits, and publisher challenge or rate-limit
responses. Unsupported content, untrusted or excessive redirects, oversized
individual files, and true missing-image responses are omitted rather than
relaxed. Image failure never suppresses its event; bounded failure details
remain in response metadata.

The HTML body is capped at 80,000 UTF-8 bytes. Long descriptions and calendar
details are independently bounded. If a large week needs compact cards, Home
Assistant's configured home coordinates prioritize which branches retain rich
cards; the digest never stores or returns the home coordinates or calculated
distances, and it keeps the visible events chronological. Farthest overflow is
omitted only when compact cards cannot fit, with a visible link to the full
branch calendars. Recurring events remain distinct in both the digest and the
native Home Assistant calendar by branch, date, and start time even when
multiple occurrences share one official series URL.

The caller must pass `digest.images` to an SMTP notify service that supports the
legacy `data.html` and `data.images` fields in the immediately following action.
The newer SMTP notify entity currently sends plain text and is not compatible
with this HTML/CID flow. Every run is scheduled for deletion after one hour,
expired runs are purged before later renders, and abandoned runs from a prior
Home Assistant process are removed during integration setup. The dedicated
directory and ownership marker prevent cleanup from deleting other `www`
content.

Example automation fragment:

```yaml
actions:
  - action: free_library_events.render_digest
    data:
      force_refresh: true
      embed_images: true
    response_variable: digest

  # Replace notify.email with your HTML/images-capable SMTP notify service.
  - action: notify.email
    data:
      title: "{{ digest.subject }}"
      message: "{{ digest.message }}"
      data:
        html: "{{ digest.html }}"
        images: "{{ digest.images }}"
```

The automation or script calling the action owns its schedule, recipient, and
email notifier. This integration deliberately does not store email addresses
or send mail directly. Leave `embed_images` false for non-SMTP notifiers or any
caller that does not pass the returned `images` list; the default HTML continues
to use the publisher's HTTPS image URLs and creates no local files.

## Diagnostics and failures

The status sensor reports:

- `ok` when every selected source loaded and both current-age and supplemental
  age-category coverage are proven through the upcoming digest week
- `limited` when every source is healthy but an official ten-item supplemental
  age feed remains unable to prove that later broadly inclusive events were
  returned after bounded event-type expansion
- `partial` when a current or supplemental source failed, parsed incompletely,
  or was unordered
- `error` after a complete refresh failure

If one selected feed fails, the calendar and digest retain the successful
branch and disclose the unavailable source. If every selected feed fails,
`render_digest` raises an error before returning an email payload.

Diagnostics redact the child name and birth date. They include per-branch and
age-category published/parsed counts, ordering and coverage-boundary evidence,
adaptive type-feed request/failure counts, discovered-event counts, source
availability, bounded errors, last refresh time, next-week match count, and
cached event counts by branch.

## Source limitations

- The official custom RSS feeds return at most ten items. The integration asks
  for each official age category in the configured person's life-stage group,
  then consolidates duplicate copies. This retains the publisher's complete
  available age provenance and discovers clearly inclusive events even when
  they were assigned to a narrower child category, without mixing in an
  unclassified all-events feed. The RSS endpoint ignores `page=2`, so an
  unresolved capped feed is instead queried through all official event-type
  filters and deduplicated. Expansion is bounded to twelve feeds per refresh,
  enough for all four branches when three official age windows overlap, and
  prioritizes every current-age source before the nearest supplemental age
  windows. All RSS traffic shares an eight-request ceiling. Each
  decoded RSS response is capped at 256 KiB. Coverage is proven only when every
  type shard covers the digest horizon and recovers the capped base prefix. A
  stalled source expansion stops after 90 seconds and retains its base events
  with an explicit coverage warning. A healthy supplemental category that
  remains unresolved produces the honest
  `limited` status; operational failures remain `partial`. Relevant current-age
  coverage problems and operational supplemental failures are also disclosed in
  the rendered digest; known cap limitations stay out of the event-focused email
  but remain available in status, diagnostics, and render-response metadata.
- One malformed RSS item is skipped without discarding the rest of its feed.
  Remote item counts and field sizes are also bounded. The
  published-versus-parsed count remains visible as `partial` source health.
- Blank image fields are omitted instead of resolving to the feed URL. The
  publisher's unusual but working dot-prefixed image paths (for example,
  `.../.jpg`) are retained. Email clients auto-load images only from the Free
  Library's HTTPS hosts, and valid event photos retain their full aspect ratio.
- The feeds provide start times but no structured end times, event-type/series
  tags,
  registration links, or cost fields. The public event pages are protected by a
  browser challenge: direct tests with Home Assistant's asynchronous HTTP
  clients returned challenge responses even when browser and command-line
  clients could load the same URL. They are therefore not a reliable portable
  Home Assistant data source. The
  digest therefore uses an explicit time range from the RSS description when
  available, omits unavailable fields, and keeps the official event link.
  Official structured event-page taxonomy is not fetched at runtime. Official
  age categories come from the feeds, and deterministic presentation highlights
  are derived only from reliable RSS title, description, and explicit-venue
  wording. Highlights are suppressed when they merely repeat the title. Google
  Calendar links disclose any configured placeholder duration they use.
- RSS description hyperlinks, explicit off-site venue names, and specifically
  named rooms are retained because they arrive through the same reliable feed;
  unsafe link schemes and ambiguous location wording are ignored.
- Events whose published title says they are cancelled, canceled, postponed,
  or rescheduled are omitted from the actionable calendar and digest instead of
  being recommended at a stale occurrence.
- The Home Assistant calendar is feed-backed and therefore continues to use and
  disclose the configured placeholder duration.
- Age matching is a deterministic convenience filter, not developmental or
  medical advice. Check the official event page before attending.

## Removing the integration

Remove the config entry from **Settings > Devices & services**, then remove the
repository from HACS. Removing the integration removes its entities and stops
future refreshes. Automations that call `free_library_events.render_digest`
must be removed or updated separately.

## Development and validation

Python 3.14 is required for the Home Assistant 2026.7 test boundary.

```powershell
python -m unittest discover -s tests -p "test_digest.py"
python -m unittest discover -s tests -p "test_public_safety.py"
python -m compileall -q custom_components\free_library_events tests scripts
python scripts\check_public_safety.py
python -m pip install -r requirements-ha-test.txt
python -m pytest tests\test_integration_ha.py tests\test_email_images.py -q
```

GitHub validation also runs Hassfest and the HACS Action. See
[`docs/architecture.md`](docs/architecture.md) for ownership and release
boundaries.

## License

MIT
