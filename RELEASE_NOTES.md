# Free Library Events v2026.7.22

## Added

- Query every official age category in the configured person's current
  life-stage group so explicitly inclusive events remain discoverable and every
  cached event retains publisher age provenance.
- Expand an unresolved ten-item feed across the publisher's official event-type
  filters, recovering later events even though the RSS endpoint ignores
  `page=2`.

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
- Reject RSS responses over 2 MiB, propagate refresh cancellation, coerce
  non-UI boolean values safely, and keep every RSS request under the same global
  concurrency ceiling.
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
