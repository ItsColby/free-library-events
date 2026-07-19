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
- `Strict`, `Recommended`, and `Broad` age-match modes
- Configurable child name and birth date
- Configurable branch selection, refresh interval, and placeholder duration
- Manual refresh button and diagnostic status sensor
- Official branch-and-age RSS queries for every category in the configured
  person's current life-stage group, with duplicate consolidation
- Coverage-aware operation that distinguishes source failures from the official
  ten-item limit and adaptively expands unresolved capped feeds through official
  event-type filters
- Redacted integration diagnostics
- Response-only `free_library_events.render_digest` action returning:
  - subject
  - plain-text message
  - responsive HTML email
  - bounded generation metadata
- Each included event leads with the official description and includes a linked
  location name, linked title and image, and a prefilled Google Calendar link
- Safe contextual links embedded in official RSS descriptions remain clickable;
  non-HTTP links are discarded
- Explicitly named off-site venues and rooms in published RSS text replace the
  less-specific branch location when the wording is unambiguous
- Event images preserve their published aspect ratio rather than being cropped

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

- the child's first name
- the child's birth date
- one or more supported library branches
- the age-match mode
- the placeholder event duration
- the feed refresh interval

The child name and birth date stay in the Home Assistant config entry and are
used only for local filtering and rendering. They are redacted from
downloadable diagnostics. Network requests download official custom RSS feeds
for each selected branch and every published age category in the configured
person's current life-stage group. For minors, that means the Baby through
Young Adult categories. At adulthood it switches to Adult and Senior while
retaining Young Adult only for as long as that official category still overlaps
the person's age; a forward source window that crosses adulthood uses both
groups. This recovers publisher classifications without putting the birth date,
child name, or calculated age in any request. All supported branches are
enabled by default and can be disabled individually.

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

## Weekly email action

`free_library_events.render_digest` refreshes the selected feeds by default and
returns a complete email payload. It must be called with `response_variable`.

The digest states the child's conversational age once: weeks before 2 completed
months, months through 23 months, half-years near the half-year mark below age
5, and years thereafter. Each event keeps its description primary without
repeating the matching rationale. An end time appears beside the start time only
when the RSS description contains an explicit range matching the published
start, including ranges whose first meridiem is unambiguous from that start, or a
conservative whole-event duration such as a “90-minute class”; otherwise it is
omitted. The location name
links to Google Maps, while the title and image link to the official event.
When the RSS text explicitly names an off-site park, square, playground,
garden, or museum, that venue replaces the hosting branch as the map and
calendar destination. Specifically named or numbered rooms are shown with their
branch.
Contextual links embedded by the library remain linked in HTML and are listed
after the description in plain text.

Example automation fragment:

```yaml
actions:
  - action: free_library_events.render_digest
    data:
      force_refresh: true
    response_variable: digest

  # Replace notify.email with your configured email notifier.
  - action: notify.email
    data:
      title: "{{ digest.subject }}"
      message: "{{ digest.message }}"
      data:
        html: "{{ digest.html }}"
```

The automation or script calling the action owns its schedule, recipient, and
email notifier. This integration deliberately does not store email addresses
or send mail directly.

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
  filters and deduplicated. Expansion is bounded to four feeds per refresh,
  shares an eight-request type-shard concurrency ceiling, and prioritizes
  current-age categories. Coverage is proven only when every type shard covers
  the digest horizon and recovers the capped base prefix. A healthy
  supplemental category that remains unresolved produces the honest `limited`
  status; operational failures remain `partial`. Relevant current-age coverage
  problems and operational supplemental failures are also disclosed in the
  rendered digest; known cap limitations stay out of the event-focused email but
  remain available in status, diagnostics, and render-response metadata.
- One malformed RSS item is skipped without discarding the rest of its feed.
  The published-versus-parsed count remains visible as `partial` source health.
- Structurally empty image filenames from the official feed are omitted instead
  of rendering a broken image. Valid event photos retain their full aspect
  ratio.
- The feeds provide start times but no structured end times, topic tags,
  registration links, or cost fields. The public event pages are protected by a
  browser challenge: direct tests with Home Assistant's asynchronous HTTP
  clients returned challenge responses even when browser and command-line
  clients could load the same URL. They are therefore not a reliable portable
  Home Assistant data source. The
  digest therefore uses an explicit time range from the RSS description when
  available, omits unavailable fields, and keeps the official event link. Google
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
python -m pytest tests\test_integration_ha.py -q
```

GitHub validation also runs Hassfest and the HACS Action. See
[`docs/architecture.md`](docs/architecture.md) for ownership and release
boundaries.

## License

MIT
