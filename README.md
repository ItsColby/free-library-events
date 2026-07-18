# Free Library Events for Home Assistant

Free Library Events is a Home Assistant custom integration that turns selected
Free Library of Philadelphia branch feeds into an age-aware calendar and a
response action for weekly email digests.

The integration currently supports:

- Charles Santore Library (`SWK`)
- Independence Library (`IND`)

It uses deterministic parsing and age-matching rules. No LLM or external AI
service is used at runtime.

## Features

- Native **Settings > Devices & services** setup and options flow
- One age-filtered Home Assistant calendar
- `Strict`, `Recommended`, and `Broad` age-match modes
- Configurable child name and birth date
- Configurable branch selection, refresh interval, and placeholder duration
- Manual refresh button and diagnostic status sensor
- Partial-source operation when one selected branch feed is unavailable
- Redacted integration diagnostics
- Response-only `free_library_events.render_digest` action returning:
  - subject
  - plain-text message
  - responsive HTML email
  - bounded generation metadata
- Each included event contains the official description, branch contact
  details, registration/cost disclosures, directions, official event link,
  and a prefilled Google Calendar link

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
- one or both supported library branches
- the age-match mode
- the placeholder event duration
- the feed refresh interval

The child name and birth date stay in the Home Assistant config entry and are
used only for local filtering and rendering. They are redacted from
downloadable diagnostics. Network requests download only the selected official
branch feeds.

### Match modes

- **Strict** includes explicit numeric or developmental-stage matches.
- **Recommended** adds clearly inclusive and likely-fit children's events.
- **Broad** also includes general child/family events without a specific age.

Published numeric age ranges override general wording such as “all ages.”

## Calendar

The integration creates one calendar containing only events that match the
configured child and mode. Each calendar event includes:

- the official title and description
- the branch address
- the deterministic fit explanation
- the child's age on the event date
- the official event page
- a disclosed placeholder end time when the feed omits one

The calendar entity does not send email or create Google Calendar events.

## Weekly email action

`free_library_events.render_digest` refreshes the selected feeds by default and
returns a complete email payload. It must be called with `response_variable`.

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

For previews and deterministic tests, the action also accepts an optional
`reference_date`. Normal automations should omit it.

## Diagnostics and failures

The status sensor reports:

- `ok` when every selected feed loaded
- `partial` when at least one feed loaded and another failed
- `error` after a complete refresh failure

If one selected feed fails, the calendar and digest retain the successful
branch and disclose the unavailable source. If every selected feed fails,
`render_digest` raises an error before returning an email payload.

Diagnostics redact the child name and birth date. They include source counts,
source availability, bounded errors, last refresh time, and cached event count.

## Source limitations

- The official branch RSS feeds may expose only their most recent items. The
  digest warns when a feed returns ten items and links the full branch calendar.
- The feeds currently provide start times but no structured end times. Calendar
  entries therefore use the configured placeholder duration and disclose it.
- Registration, cost, and age information are inferred only from published
  event text. Missing information remains labeled as missing.
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
