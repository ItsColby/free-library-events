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
- Bound adaptive type expansion to four capped feeds per refresh and prioritize
  the configured person's current age categories before supplemental discovery.
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
  failures, and proven coverage boundary in the status sensor, diagnostics, and
  render-response metadata.

## Maintenance

- Skip malformed individual RSS items instead of discarding their whole feed,
  while retaining published-versus-parsed evidence in diagnostics.
- Suppress structurally empty image filenames from the official feed instead of
  rendering a broken image; valid event photos continue to preserve their full
  aspect ratio.
- Reject non-HTTP event, image, and contextual URLs while resolving safe
  relative URLs against the official Free Library source.
- Prevent room extraction from crossing description line boundaries and
  misreading a later schedule date as a room number.
- Keep protected event-page and ICS scraping out of the runtime after native HA
  HTTP-client replay proved those routes return browser challenges; unavailable
  fields remain omitted rather than guessed.
