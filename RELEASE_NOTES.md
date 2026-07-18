# Free Library Events v2026.7.22

## Added

- Add one official all-event discovery feed per selected branch so explicitly
  inclusive events remain discoverable when their published age category is too
  narrow for the child.

## Changed

- Let strong published inclusion wording override a nonmatching feed category
  while keeping numeric age ranges authoritative and rejecting generic family
  wording alone.
- Distinguish the official ten-item discovery limit (`limited`) from operational
  source or parsing failures (`partial`).
- Replace ambiguous status attributes with the next-week event count, cached
  events by branch, and separate age-feed and discovery coverage indicators.

## Maintenance

- Skip malformed individual RSS items instead of discarding their whole feed,
  while retaining published-versus-parsed evidence in diagnostics.
- Suppress structurally empty image filenames from the official feed instead of
  rendering a broken image; valid event photos continue to preserve their full
  aspect ratio.
