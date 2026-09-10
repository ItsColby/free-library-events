# Using Free Library Events

This guide covers the installed integration. Start with the
[installation steps](../README.md#install) if it is not yet configured.

## Profile and settings

One config entry serves one person and one selection of supported branches.
Use **Reconfigure** on the integration to change its required profile:

| Setting | Meaning |
| --- | --- |
| Display name | Used in the digest subject and body; at most 80 characters after whitespace normalization. |
| Birth date | Used locally to calculate age on each event date; a future date is rejected. |
| Library branches | One or more of the four branches listed in the README. All are selected by default. |

Under **Configure**, use **Matching and timing** for these options:

| Setting | Default | Range or choices |
| --- | --- | --- |
| Age-match mode | `Recommended` | `Strict`, `Recommended`, `Broad` |
| Placeholder event duration | 60 minutes | 15–240 minutes |
| Source refresh interval | 21,600 seconds (6 hours) | 900–86,400 seconds (15 minutes–24 hours) |

**Calendar subscription** controls publication and the calendar name, which
defaults to **Free Library Events** and accepts up to 80 characters. Publishing
is off initially. **Regenerate calendar subscription URL** appears when it is
enabled. Saving settings reloads the entry; these settings changes do not need
a Home Assistant restart.

## How matching works

Matching uses age on the event date, numeric ages in the listing, official
RSS age categories, and a fixed vocabulary of audience terms. The library
publishes category names; the integration supplies their overlapping numeric
windows. Those windows are local matching rules, not library admission rules.

| Mode | Included matches |
| --- | --- |
| `Strict` | Matches ranked best by the local rules, using numeric ages, applicable RSS categories, or recognized age-stage wording. |
| `Recommended` | Strict matches plus recognized inclusive wording and likely fits, such as qualifying playgroups. |
| `Broad` | Recommended matches plus general child/family wording when no stronger category or age restriction excludes the event. |

Recognized numeric restrictions take precedence over category and general
wording. A matching category can qualify an event without an explicit age in
its description. Specific inclusive phrases can qualify an event from a
nonmatching category; generic family wording alone cannot. These are finite
text rules, so unfamiliar phrasing can be missed. For a child under three,
recognized years-only upper limits of six or greater (such as “ages 6 and under”)
are deliberately ranked `Broad`, even when the child satisfies the limit. See the
[matching implementation](../custom_components/free_library_events/digest.py)
for the exact windows and vocabulary.

The source plan requests Baby through Young Adult feeds for minors. Adults use
the applicable Adult, Senior, or overlapping Young Adult categories. A planning
window crossing adulthood includes both groups. Broader source selection helps
find inclusive events listed under a narrower category; filtering still decides
which occurrences appear. The source plan looks 90 days ahead for age-category
transitions, which does **not** guarantee 90 days of event listings.

## Calendar and event details

The **Calendar** entity presents matching occurrences from the current cache,
including dates outside the digest week when supplied by RSS. Events use
Philadelphia time (`America/New_York`). Each occurrence keeps its official
title, description, safe related links, official details URL, and location.
Distinct dates or start times remain distinct even when they share a series URL.

An explicit off-site venue replaces the hosting branch as the destination;
named rooms or floors remain with the branch. Online listings have no map
destination, and hybrid listings retain their physical location and online
context. Unclear location wording falls back to branch information.

The RSS source has no structured end-time field. When a description contains
a recognized time range matching the start, or a conservative whole-event
duration, the integration derives an end time from that wording. Otherwise the
calendar and add-to-calendar links use the configured placeholder and disclose
it. A placeholder is not a published finish time.

Titles marking an occurrence cancelled, canceled, postponed, or rescheduled
are excluded. This is title-based filtering, not a live cancellation service.
Safe links and source text remain the route to registration, price, accessibility,
and attendance details; structured event-page fields are not fetched.

### Calendar subscriptions

Enable publishing in **Configure > Calendar subscription** and choose a calendar
name. The following screen shows an HTTP(S) URL and a `webcal://` form; submit
that screen to save. An example route is:

```text
https://home-assistant.example/api/free_library_events/calendar/<token>.ics
```

Use the HTTPS form for server-side subscriptions such as Google Calendar's
**From URL**. Use `webcal://` only with a client or operating system that handles
that scheme. Subscribe to the URL for ongoing updates; importing a downloaded
file creates a separate snapshot.

The URL's token is its credential. Anyone holding it can read the filtered
events and custom calendar name without a Home Assistant login. Keep the full
URL private. It omits the profile name, birth date, and calculated age, but the
event selection can reveal interests and the custom name may identify someone.

The setup screen distinguishes an external/cloud URL from an internal-only URL.
That label does not test internet reachability. An external client needs an
HTTPS route to Home Assistant that accepts this feed without an interactive
login. Proxy routing, DNS, TLS, and access policy belong to the deployment. If a
proxy exception is necessary, scope it to `/api/free_library_events/calendar/`;
the rest of Home Assistant retains its existing access controls. Every published
address family must reach the service. Access logs can contain the credential URL.

Regeneration requires confirmation and a final save; saving the replacement
invalidates the old URL. Update subscribers afterward. Disabling publication
removes the token. Invalid, disabled, or unloaded tokens all return `404`.

Clients choose when to fetch. The feed supplies refresh hints and HTTP cache
validators (`ETag` and `Last-Modified`), but cannot force a client's cadence or
push an update. A fetch reads the cache without refreshing the library. After a
complete source failure it may still serve retained events; it has no separate
maximum-age cutoff. Rotation or removal does not erase copies retained by clients.

## Weekly digest action

`free_library_events.render_digest` returns email content. It does not send,
schedule, queue, or confirm delivery. Call it with a `response_variable` from a
script or automation, then decide what to do with the response.

The digest covers Monday through Sunday: a Monday render uses that Monday;
Tuesday through Sunday uses the following Monday. Home Assistant's local date
selects the week, while event times use Philadelphia time. The action accepts
no custom date range or per-call profile overrides.

| Input | Default | Behavior |
| --- | --- | --- |
| `force_refresh` | `true` | Wait for a completed source attempt, including shared work already in progress. Total failure stops the action; partial success may return a digest with warnings. |
| `embed_images` | `false` | When true, download selected publisher images, create temporary inline attachments, and return their references. |

Set `force_refresh: false` for a cache-only render. This can use the retained
cache after a failed refresh; there is no age cutoff. Inspect `metadata.fetched_at`
and the **Status** sensor when freshness matters. Coverage fields describe the
cached snapshot and do not independently attest to the latest failed attempt.

This script body renders without sending or writing image files:

```yaml
sequence:
  - action: free_library_events.render_digest
    data:
      force_refresh: true
      embed_images: false
    response_variable: digest
```

### Sending with SMTP

Configure a recipient in Home Assistant's [SMTP integration](https://www.home-assistant.io/integrations/smtp/)
and a Local Media directory for media-source attachments. Then use this action
sequence in your own automation, replacing the example
notify entity. It sends an email when executed; choose the trigger and recipient
in that automation.

```yaml
actions:
  - action: free_library_events.render_digest
    data:
      force_refresh: true
      embed_images: true
    response_variable: digest

  - action: smtp.send_message
    target:
      entity_id: notify.email_recipient
    data:
      title: "{{ digest.subject }}"
      message: "{{ digest.message }}"
      html: "{{ digest.html }}"
      attachments: "{{ digest.attachments }}"
```

Pass attachments in the immediately following send action. SMTP owns the
recipient and delivery result. The integration also returns legacy local paths
in `images` for existing legacy SMTP consumers; use one attachment format per
send. For other consumers, leave embedding off unless they can resolve the
returned attachments. Otherwise `cid:` images in the HTML will not display.

### Response fields

| Field | Meaning |
| --- | --- |
| `subject`, `message`, `html` | Subject, plain-text body, and HTML body. The name and conversational age appear in rendered content. |
| `metadata.week_start`, `week_end`, `filter_mode`, `fetched_at` | Rendered window, matching mode, and source-cache timestamp. |
| `metadata.scanned_count`, `included_count`, `omitted_count` | Active deduplicated occurrences in the week, age-matched occurrences, and those excluded by matching. |
| `metadata.included_event_ids`, `included_occurrence_ids` | Compatibility IDs derived from the final source-URL component (or occurrence identity without a link), and exact occurrence IDs. The first list can repeat for recurring events. |
| `metadata.email_omitted_count` | Matching occurrences left out of the email because of size/count limits; separate from age-filter exclusions. |
| `metadata.html_bytes`, `full_card_count`, `compact_card_count`, `truncated_description_count`, `full_card_event_ids`, `distance_priority_used` | Final presentation size and budgeting decisions. |
| `metadata.source_counts`, `source_errors`, `source_warnings`, `supplemental_age_failures`, `supplemental_age_limitations`, `expanded_capped_sources` | Counts and bounded coverage evidence from the cached source generation. |
| `attachments`, `images` | Present only with embedding enabled: SMTP media-source objects and legacy local paths. Lists can be empty. |
| `metadata.embedded_image_count`, `smtp_attachment_count`, `image_download_count`, `image_download_failure_count`, `image_download_failure_examples`, `image_expires_at` | Image results and expiry information when embedding is enabled. |

### Presentation and image limits

Descriptions remain primary, with preserved safe paragraphs, emphasis, lists,
and related links. Compact highlights summarize recognized planning or activity
wording; they do not alter matching or become verified structured library data.
Event titles and images open official details. A map link uses the recognized
destination. The Google Calendar button opens a prefilled event for the user to
save; it does not create or maintain an external calendar event automatically.

Email includes at most 100 matching occurrences and 80,000 UTF-8 bytes of HTML.
Long titles, descriptions, and calendar-link details have separate bounds. When
space runs short, nearby branches retain richer cards using distances calculated
from Home Assistant's configured location. Further overflow is omitted only
as needed. Presentation remains chronological; both bodies disclose email
omissions and link to branch calendars. The native calendar is not shortened by
email limits. The subject count describes all matching occurrences, including
any omitted from the body.

Without embedding, images use publisher HTTPS URLs and create no local files;
email clients control remote-image loading. Embedding attempts at most 12 unique
images, with four concurrent downloads, a 15-second request timeout, 3 MiB per
image and 15 MiB of accepted images overall. Only trusted publisher HTTPS hosts and the default
HTTPS port are accepted; at most two trusted redirects are followed. Files must
pass supported-format signature checks. Extracted dimensions guide layout;
missing dimensions alone do not reject a supported image.

Transient download, rate-limit/challenge, storage, count, or total-budget failures
can retain the trusted remote URL. Missing images, unsafe redirects, unsupported
content, and oversized individual files are omitted. An image failure never
removes its event. Inline attachments cannot guarantee display in every mail
client, and fallback images still depend on remote-image settings.

Files live in integration-owned runs under Home Assistant Local Media. If no
media directory is configured, legacy storage under `www` supplies local image
paths but `attachments` is empty; configure Local Media before using the modern
SMTP example. Cleanup is scheduled for one hour, expired runs are removed before later embedded
renders, and abandoned runs from a previous process are removed at setup.
Process downtime can delay cleanup. These are temporary send inputs, not an
email archive; delayed sends should render a new payload.

## Refresh, coverage, and status

Polling runs every six hours by default. The refresh button and default digest
action request the same bounded refresh machinery and wait at most ten minutes
for a completed attempt. The refresh button stays available while the entry is
loaded, including after total source failure. Concurrent requests are coalesced.
Initial entry setup uses Home Assistant's setup retry policy.

An observed ten-item RSS ceiling can hide later events. The integration attempts
bounded expansion by official event type: at most 12 capped branch/category
sources, each with 19 type filters. All feed requests share an eight-request
concurrency limit. A source expansion times out after 90 seconds and retains
its base rows with a coverage warning. Current-age sources take priority over
supplemental age categories. This improves coverage but cannot prove that the
publisher's full calendar was returned. Event HTML and publisher ICS endpoints
are outside the runtime acquisition boundary.

| Raw status | Meaning |
| --- | --- |
| `ok` | No source failures or coverage gaps detected for the digest window under the integration's RSS coverage rules. |
| `limited` | Current-age coverage is complete, but healthy supplemental feeds still hit a publisher coverage limit. |
| `partial` | Current-age coverage is unproven, or relevant current/supplemental sources failed or have unusable parsing/order evidence. A healthy capped current-age source can also cause this state. |
| `error` | The latest refresh failed completely. Any retained cache is older than that failed attempt. |

Home Assistant may show translated labels; automations should use the raw
values above. Zero matching events can be valid and does not imply a failed
refresh. Interpret coverage flags and cache counts alongside status and the
latest-attempt attributes.

A partially successful refresh replaces the cache with that attempt's
successful sources. It does not preserve old rows for the failed sources. Total
failure retains the previous cache; the native calendar becomes unavailable,
while status and refresh remain usable. Cache-only digest and subscription
behavior is described above.

The first total failure in a continuous streak requests one five-minute retry
only if every failed source has a retryable transport, timeout, rate-limit, or
server error. Later failures return to the configured polling interval. Any
partial or full success resets the allowance. Parsing, TLS verification, unsafe
redirects, response limits, and other deterministic failures do not trigger this
expedited retry. It is a scheduled retry, not a recovery guarantee.

The status sensor reevaluates the digest-week projection at Tuesday local
midnight without source requests. Native calendar start/end transitions are
managed by Home Assistant. Neither local projection nor a calendar-client fetch
means the publisher was contacted again.

## Privacy and diagnostics

The profile and settings are stored in Home Assistant. Feed requests send branch,
age-category, and sometimes event-type filters, never the display name, birth
date, or calculated age. The library still sees the requested filters and
requesting network address. Optional image downloads contact publisher hosts.

Digests contain the name and age; script traces, saved responses, and recipients
may therefore hold personal information. Budgeting distances are calculated
transiently from Home Assistant's location and public branch coordinates.
Home coordinates and computed distances are not stored, logged, or included in
the response; only whether priority was used is reported. Following official,
map, or calendar links uses the chosen external service.

Download diagnostics from the integration menu for source counts, parsing and
ordering evidence, expansion blockers, coverage, and the latest attempt. They
redact the profile name, birth date, and custom calendar name, and omit the
subscription token and raw event payloads. Invalid stored settings produce an
`invalid_config` category. Source errors use bounded categories, not arbitrary
exception bodies. Selected branches and source categories remain diagnostic
information: review the file before posting it publicly.

`last_refresh` describes the retained normalized cache. `last_attempt` and its
success/failure counts describe the latest completed base-source attempt even
when it failed completely. On-demand diagnostics retain the full bounded shard
evidence; entity state and action metadata expose counts and at most three
examples per expanded source.

## Troubleshooting

| Symptom | Check and next step |
| --- | --- |
| Integration will not finish loading | Check Core compatibility and feed connectivity. Initial acquisition needs at least one successful source. Inspect the bounded failure category in logs; repeated restarts do not repair an upstream feed. |
| Missing event or empty week | Confirm branches, date, age on that date, mode, inactive-title filtering, and status. The digest uses a Monday window, not the next seven days. Consult the official listing if coverage is limited. |
| `limited` persists | Inspect supplemental limits. A healthy capped publisher feed may remain limited after refresh; faster polling does not remove its item ceiling. |
| `partial` persists | Inspect the failed source or coverage blocker. Distinguish transport failure from healthy current-age truncation before changing settings. |
| `error` or refresh action failure | Inspect latest-attempt counts and error categories. Use **Refresh events** after the underlying issue clears; the button remains available. |
| Render fails after settings changed | Wait for reconfiguration/reload to finish, then render again. The action rejects a result whose accepted settings/runtime were superseded during refresh. |
| Subscription returns `404` | Confirm publication is enabled, the entry is loaded, and the subscriber uses the saved URL. A replaced token will never recover by polling. |
| Subscription is stale or unavailable externally | Check cache time, client polling, and external HTTPS/proxy/DNS routing. A URL preview does not prove external access. A valid loaded entry without cache returns `503` with a retry hint. |
| Email was not sent | Inspect the caller's trace and SMTP result. Rendering success proves a payload exists; it does not prove a send occurred. |
| Inline images are missing | Pass attachments immediately, inspect image metadata, and confirm notifier support. Render again if temporary files expired. |

For a reproducible defect, report versions, branches, mode, relevant public
event URL, expected behavior, and redacted diagnostics in the
[issue tracker](https://github.com/ItsColby/free-library-events/issues).
Do not include the private subscription URL, recipients, or unredacted traces.

## Removal

Remove the config entry from **Settings > Devices & services**, then remove the
download through HACS. Entry removal stops refresh work, removes its entities,
and makes the subscription URL unavailable. Update or remove caller automations
and external subscriptions separately. Delivered emails and events copied into
other calendars remain with those systems.
