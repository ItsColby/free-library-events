# Free Library Events v2026.7.21

## Added

- Add Parkway Central Library and Philadelphia City Institute as selectable
  sources.
- Enable all supported sources by default for new and existing entries.
- Use official branch-and-age RSS feeds, with coverage diagnostics for the Free
  Library's result limit.

## Changed

- Derive the relevant official age feeds from the configured birth date on
  every refresh and match age on each event date.
- Consolidate duplicate events returned by overlapping age feeds while
  retaining their official classifications.
- Group weekly digest events by day and simplify each event around its title,
  time, location, description, official details, map, and Google Calendar link.
- Show conversational age once per digest, preserve event-image aspect ratios,
  and show an end-time range only when the source publishes a matching explicit
  range.
- Omit unavailable registration, cost, and end-time placeholders, redundant
  rationale, unreliable tags, addresses, phone numbers, and duplicate action
  buttons.
- Keep source-coverage and partial-failure disclosures consistent across HTML,
  plain text, status, and diagnostics.
- Use confident source end times in the Home Assistant calendar; otherwise
  retain the configured calendar placeholder.

## Maintenance

- Remove the public digest action's testing-only date override and simplify
  config-entry runtime ownership.
- Keep maintainer-specific exact-value privacy review local while retaining the
  generic public self-scan and nested-repository protection.
