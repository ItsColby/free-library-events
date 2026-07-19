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
