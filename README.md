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
- Custom official branch-and-age RSS queries with duplicate consolidation
- Coverage-aware partial operation when a selected source is unavailable or its
  result boundary cannot prove the full digest week was returned
- Redacted integration diagnostics
- Response-only `free_library_events.render_digest` action returning:
  - subject
  - plain-text message
  - responsive HTML email
  - bounded generation metadata
- Each included event leads with the official description and includes a linked
  location name, linked title and image, and a prefilled Google Calendar link
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
for each selected branch and relevant published age category. The birth date
and child name are not included in those requests. All supported branches are
enabled by default and can be disabled individually.

### Match modes

- **Strict** includes explicit numeric or developmental-stage matches.
- **Recommended** adds clearly inclusive and likely-fit children's events.
- **Broad** also includes general child/family events without a specific age.

Published numeric age ranges override the official feed category and general
wording such as “all ages.” When an event appears in more than one relevant
official age feed, it is shown once and retains all of those classifications.

## Calendar

The integration creates one calendar containing only events that match the
configured child and mode. Each calendar event includes:

- the official title and description
- the branch address
- the official event page
- a disclosed placeholder end time when the feed omits one

The calendar entity does not send email or create Google Calendar events.

## Weekly email action

`free_library_events.render_digest` refreshes the selected feeds by default and
returns a complete email payload. It must be called with `response_variable`.

The digest states the child's conversational age once: weeks before 2 completed
months, months through 23 months, half-years near the half-year mark below age
5, and years thereafter. Each event keeps its description primary without
repeating the matching rationale. An end time
appears beside the start time only when the RSS description contains an explicit
range matching the published start; otherwise it is omitted. The location name
links to Google Maps, while the title and image link to the official event.

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

- `ok` when every selected source loaded and coverage evidence reaches beyond
  the upcoming digest week
- `partial` when at least one source loaded but another failed, parsed
  incompletely, or reached its item limit before full-week coverage was proven
- `error` after a complete refresh failure

If one selected feed fails, the calendar and digest retain the successful
branch and disclose the unavailable source. If every selected feed fails,
`render_digest` raises an error before returning an email payload.

Diagnostics redact the child name and birth date. They include per-branch and
age-category published/parsed counts, ordering and coverage-boundary evidence,
source availability, bounded errors, last refresh time, and cached event count.

## Source limitations

- The official custom RSS feeds return at most ten items. The integration uses
  the narrowest relevant branch-and-age feeds, consolidates duplicate events,
  and treats a capped feed as complete only when its final ordered event is
  after the digest week. Otherwise the status becomes `partial` and the digest
  names the unresolved source while retaining full-calendar links.
- The feeds provide start times but no structured end times, topic tags,
  registration links, or cost fields. The public event pages are protected by a
  browser challenge and are not a reliable Home Assistant data source. The
  digest therefore uses an explicit time range from the RSS description when
  available, omits unavailable fields, and keeps the official event link. Google
  Calendar links disclose any configured placeholder duration they use.
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
