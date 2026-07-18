# Free Library Events v2026.7.20

## Changed

- Rename the calendar entity from **Events** to **Calendar** so its device-owned
  frontend name is **Free Library Events Calendar**, not **Free Library Events
  Events**.
- Replace the repository privacy check with a self-scanning generic guard and
  supply maintainer-specific denylist values only through the trusted release
  environment.

## Repository maintenance

- Rebuild the reachable public Git history to remove maintainer-only data from
  an internal validation implementation and standardize Git metadata on the
  public **ItsColby** identity.

Existing source checkouts should be re-cloned instead of merged across the
rewritten history. HACS installations can update normally. Feed retrieval, age
matching, configuration, digest content, and the
`free_library_events.render_digest` action are unchanged.
