# Free Library Events for Home Assistant

Free Library Events turns public Free Library of Philadelphia RSS listings into
an age-filtered Home Assistant calendar and a weekly digest you can send through
your own automation. It supports one person's profile and these four branches:

| Branch | Source code |
| --- | --- |
| Charles Santore Library | `SWK` |
| Independence Library | `IND` |
| Parkway Central Library | `CEN` |
| Philadelphia City Institute | `PCI` |

The integration provides a **Calendar**, **Status** diagnostic sensor,
and **Refresh events** button. Optional features are a private iCalendar
subscription URL and inline images for SMTP digests. Matching and rendering use
local deterministic rules. No library account or AI service is needed.

The library owns the listings. The integration selects and presents them;
your automations own schedules, recipients, and delivery. RSS coverage is
limited, and a successful refresh does not guarantee that every library event
is included. Check the official event page for attendance details and changes.

## Install

Requires Home Assistant Core **2026.8.0 or later** and HACS.

1. [Open this repository in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=ItsColby&repository=free-library-events&category=integration).
   If needed, add `https://github.com/ItsColby/free-library-events` as an
   **Integration** under HACS **Custom repositories**.
2. Download **Free Library Events**, then restart Home Assistant.
3. Open **Settings > Devices & services > Add integration** and select
   **Free Library Events**.
4. Enter a display name, birth date, and at least one branch. All supported
   branches are selected initially.

See the [HACS custom repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/)
for the HACS controls. The minimum is declared in [`hacs.json`](hacs.json);
exact tested Core versions are documented in
[Development and validation](docs/development.md).

## Use

Open the integration's device to view its calendar, status, and refresh button.
Use **Reconfigure** to change the profile or branches. **Configure** opens the
matching, timing, and subscription settings. Defaults are **Recommended**
matching, a **six-hour** source refresh interval, a **60-minute** fallback event
duration, and subscription publishing **off**.

- [User guide](docs/usage.md): settings, match rules, subscriptions, digest
  examples, response fields, privacy, troubleshooting, and removal.
- [Architecture](docs/architecture.md): source boundaries, identities,
  projections, failure recovery, and resource ownership.
- [Development and validation](docs/development.md): local checks, support
  lanes, contribution surfaces, and release procedure.
- [Release notes](RELEASE_NOTES.md): historical changes and validation recorded
  for each release.

## Support

Start with [Troubleshooting](docs/usage.md#troubleshooting). For a reproducible
integration problem, use the [issue tracker](https://github.com/ItsColby/free-library-events/issues).
Include the integration and Core versions, selected branches, match mode, and
what you expected. Review diagnostics before sharing; keep profile data,
subscription URLs, recipients, and automation traces private.

## License

[MIT](LICENSE).
