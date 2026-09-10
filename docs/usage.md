# Use Free Library Events

After [installation](../README.md#install-and-add-your-profile), use the integration's Calendar to browse matching events. Configure a subscription or an email automation only if you want those additional ways to receive them.

## Adjust your profile and matching

Open **Free Library Events** in **Settings > Devices & services**. Use **Reconfigure** to change **Person's display name**, **Person's birth date**, or **Library branches**. The name must contain 1–80 characters, the birth date must be valid and no later than today, and at least one supported branch must remain selected. Only one person and one integration entry are supported.

Use **Configure > Matching and timing** for these options. Saving changed settings reloads the integration.

| Setting | Default | Allowed values and effect |
| --- | --- | --- |
| **Age-match mode** | `Recommended` | `Strict`, `Recommended`, or `Broad`; applies to the digest and both calendars. |
| **Fallback event duration (minutes)** | `60` | Whole number from 15–240. Supplies a calendar end time only when no end time was recognized in the feed. |
| **Automatic refresh interval (seconds)** | `21600` | Whole number from 900–86400: 15 minutes to 24 hours. |

Age is calculated for each event date, so birthdays need no manual profile update. Explicit published age ranges take precedence over broader descriptions and categories. Otherwise, the integration uses overlapping local interpretations of the library's age categories and deterministic wording rules. These interpretations are not admission rules published by the library.

| Mode | What it includes |
| --- | --- |
| **Strict** | The strongest matches from an explicit age range, a matching category, or age-specific wording. |
| **Recommended** | Strict matches plus recognized inclusive wording and possible matches, such as an appropriate playgroup. |
| **Broad** | Recommended matches plus general children's or family wording when stronger evidence does not exclude the event. |

Broad does not override an explicit incompatible age range. For children under three, recognized years-only upper limits of six or greater, such as “6 and under,” receive a Broad rank even when the child meets the stated limit. For minors, the integration also checks other child and teen category feeds to discover inclusive events that were filed under a narrower category. Adult and senior feed selection advances with age. Titles marked canceled, postponed, or rescheduled are excluded. Always consult official details for eligibility, registration, availability, accessibility, and changes.

## Use the calendar

The integration creates **Calendar**, **Status**, and **Refresh events** entities. Typical entity IDs are `calendar.free_library_events_calendar`, `sensor.free_library_events_status`, and `button.free_library_events_refresh_events`; use the IDs shown in your own entity registry if they differ.

The Home Assistant calendar shows matching occurrences available in the latest cache. It is read-only and can include dates beyond the digest week; the feeds determine how far ahead it can see. Repeated events on different dates remain separate occurrences.

Event times use Philadelphia's `America/New_York` time zone. A recognized source end time is preserved. Otherwise, the configured fallback duration supplies the end and the description identifies it as a placeholder. The event description also links to official details. A one-hour entry is therefore not evidence of a published one-hour program.

The digest's Google Calendar links open a prefilled event form; an event is copied into that calendar only after you save it. That copy does not track later source updates. Use the subscription below to let a calendar app reread the integration's cache.

## Subscribe from another calendar app

1. Open **Configure > Calendar subscription**.
2. Turn on **Enable calendar subscription** and set **Calendar name** if desired. The default is `Free Library Events`; names must contain 1–80 characters.
3. Continue to **Calendar subscription URL**. Copy the HTTP(S) URL, or the `webcal://` URL for an app that supports it.
4. Select **Submit** on the URL screen to save the settings. Displaying or copying a preview does not enable it.
5. Add the URL using your calendar app's subscription or “from URL” feature.

The feed uses the same age filter and cached events as the Home Assistant calendar. Reading it does not refresh library data. The integration advertises the configured refresh interval, but each calendar app decides when to poll and when to display changes.

Home Assistant's external or cloud address is preferred; an internal address is used when no external address is available. The form identifies which it found. The subscribing app or service must be able to reach that address. An internal URL may work for a device on your network while being unreachable to a cloud calendar service. If no address can be obtained, configure a Home Assistant URL and reopen the form.

External subscribers need a reachable HTTPS route that does not require an interactive login. The token authenticates this feed. If proxy authentication needs an exception, restrict it to `/api/free_library_events/calendar/`; keep other routes protected. Deployment configuration and external reachability checks belong to the Home Assistant installation owner.

**Treat the complete subscription URL as a password.** Anyone holding it can read the feed without signing in to Home Assistant. The calendar includes event details and your chosen calendar name; it does not include the configured person's name or birth date unless you put personal information into the calendar name yourself.

To replace an exposed URL, select **Configure > Regenerate calendar subscription URL**, continue, and submit the replacement URL screen. Saving invalidates the old URL; subscribers must use the new one. To stop publication, turn off **Enable calendar subscription** and save. This removes the token. Unsubscribing or disabling publication does not erase events already copied by another app. If another settings change invalidates an open form, reopen **Configure** and try again with the current settings.

## Render and send a weekly digest

`free_library_events.render_digest` returns email content and metadata. It requires exactly one loaded integration entry. It sends nothing and accepts no recipient or date-range parameter.

The digest covers Monday through Sunday. On Monday it covers the week starting that day; Tuesday through Sunday it covers the following week. The reference date uses Home Assistant's configured time zone. For example, a Sunday run previews the next day through the following Sunday.

### Preview the response

In Home Assistant's action tool, select **Free Library Events: Render weekly digest**. In a script or automation, capture the response with `response_variable`:

```yaml
- action: free_library_events.render_digest
  data:
    force_refresh: true
    embed_images: false
  response_variable: digest
```

| Input | Default | Meaning |
| --- | --- | --- |
| `force_refresh` | `true` | Wait for a completed refresh before rendering. A complete source failure fails the action; partial success can return a digest with coverage warnings. |
| `embed_images` | `false` | When enabled, download supported publisher images and prepare temporary inline attachments. |

With `force_refresh: false`, the action uses the existing cache even after a failed refresh. It fails if no fetched data exists. Check `metadata.fetched_at` before treating a cached digest as current. A render interrupted by a reload or changed settings during its refresh fails so you can rerun with the current profile.

### Send HTML email with SMTP

Set up Home Assistant's [SMTP integration](https://www.home-assistant.io/integrations/smtp/) and a recipient first. Replace `notify.library_email` below with that recipient's notify entity. The [`smtp.send_message` action](https://www.home-assistant.io/actions/smtp.send_message/) accepts the plain-text body, HTML body, and inline attachments; the send step below actually sends mail.

This complete automation runs on Sunday at 18:00 in Home Assistant's time zone. Change the day and time to suit your schedule. Use a small initial test before enabling the weekly automation.

```yaml
alias: Weekly library events email
triggers:
  - trigger: time
    at: "18:00:00"
conditions:
  - condition: time
    weekday:
      - sun
actions:
  - action: free_library_events.render_digest
    data:
      force_refresh: true
      embed_images: false
    response_variable: digest
  - action: smtp.send_message
    target:
      entity_id: notify.library_email
    data:
      title: "{{ digest.subject }}"
      message: "{{ digest.message }}"
      html: "{{ digest.html }}"
mode: single
```

A complete refresh failure stops this sequence before the send action. Partial results are sent with their coverage warnings. If you prefer to suppress mail when there are source failures or current-age coverage warnings, add this condition between the two actions:

```yaml
- condition: template
  value_template: >-
    {{ not digest.metadata.source_errors
       and not digest.metadata.source_warnings }}
```

That condition permits healthy supplemental feed limits. Also require `not digest.metadata.supplemental_age_limitations` if you want to suppress those digests as well. Neither check proves that the publisher listed every event.

For a plain-text notification, send `digest.subject` as `title` and `digest.message` as `message` through your notification action. HTML support varies by notification integration.

### Include inline event images

To use SMTP attachments, configure [Local Media](https://www.home-assistant.io/integrations/media_source/#local-media) and ensure Home Assistant can write to the selected media directory. Change the render input to `embed_images: true` and add this field alongside `title`, `message`, and `html` in the SMTP action:

```yaml
attachments: "{{ digest.attachments }}"
```

Pass the returned list as a whole; it already contains the media-source references and matching Content-IDs. `digest.images` contains local filesystem paths for other consumers and is not the value to pass to `smtp.send_message`.

Images are stored in a managed `.free_library_events_email` directory under Local Media. If a directory with ID `local` exists, it is used; otherwise the first configured media-directory ID in alphabetical order is used. With no Local Media configured, the integration falls back to its directory under Home Assistant's `www`, and the SMTP `attachments` list is empty. Use Local Media for the SMTP example; unlike `www`, it protects served files with Home Assistant authentication.

Send immediately after rendering. Image cleanup is scheduled for one hour later, and integration startup removes its managed image runs. `metadata.image_expires_at` reports the scheduled expiry when files were stored; it is not a delivery guarantee.

At most 12 unique images are embedded, with limits of 3 MiB per image and 15 MiB in total. GIF, JPEG, PNG, and WebP are supported. Some download failures or limits leave a remote publisher image in the HTML; unsafe or invalid images are omitted. A successful digest does not guarantee that every image embedded or that the mail client displays it. With embedding off, supported images remain remote links that a mail client may fetch.

## Interpret the response

The response always contains `subject`, `message` (plain text), `html`, and `metadata`. When `embed_images: true`, it also contains `images` and `attachments`, even when those lists are empty.

Use these metadata groups according to the decision you need to make:

| Fields | Meaning |
| --- | --- |
| `week_start`, `week_end`, `filter_mode`, `fetched_at` | The requested week, match mode, and timestamp of the cached fetch used for this digest. |
| `scanned_count`, `included_count`, `omitted_count` | Active occurrences in that week, those accepted by the age filter, and those rejected by it. These are not a count of every event offered by the library. |
| `included_event_ids`, `included_occurrence_ids` | The first list contains the last source-URL component, falling back to occurrence identity without a URL; it can repeat for a series. The second list distinguishes occurrences by source, branch, date, and start time. Use occurrence IDs when separate dates matter. |
| `source_counts` | Deduplicated cached events by branch across the fetched date range, before weekly and age filtering. A missing branch is not a confirmed zero. |
| `source_errors`, `source_warnings` | Unavailable current-age feeds and current-age coverage warnings; operational supplemental failures also appear in `source_warnings`. |
| `supplemental_age_failures`, `supplemental_age_limitations` | Failures in additional age feeds, separated from healthy but incomplete feed coverage. |
| `expanded_capped_sources` | Evidence from attempts to recover events beyond a capped base feed, including remaining failures, blockers, and coverage dates. |
| `html_bytes`, `full_card_count`, `compact_card_count`, `email_omitted_count`, `truncated_description_count` | Email size and presentation limits. `email_omitted_count` means matched events omitted from the email, unlike age-filter `omitted_count`. |
| `distance_priority_used`, `full_card_event_ids` | Whether local branch distance affected space allocation, and which occurrences received full cards. |

With image embedding requested, metadata also includes `embedded_image_count`, `smtp_attachment_count`, `image_download_count`, `image_download_failure_count`, `image_download_failure_examples`, and `image_expires_at`. Compare embedded and attachment counts if SMTP images are missing; they can differ when Local Media is unavailable.

The email is limited to 80,000 HTML bytes and at most 100 events. It may shorten descriptions, compact cards, or omit matched events, with the omission disclosed in the body. When space is constrained, distance from Home Assistant's configured location helps prioritize branches locally. The subject's count and `included_count` still describe all matches; the calendars are not reduced by the email budget.

## Check coverage and recover

Open the **Status** sensor before interpreting an empty calendar or a zero-event digest. Its state describes coverage for the digest week, not the entire cached calendar range.

| Displayed state | Meaning |
| --- | --- |
| **OK** (`ok`) | No detected current-age or supplemental coverage problem for that week. It is not a guarantee of a complete library schedule. |
| **Limited** (`limited`) | Current-age coverage has no detected problem, but otherwise healthy supplemental feeds may omit later inclusive events. |
| **Partial** (`partial`) | A relevant source failed, current-age coverage is incomplete, or supplemental data has an operational or parsing problem. Usable events are still available. |
| **Error** (`error`) | The latest refresh failed completely. Earlier cached data may remain, but it is stale. |

The most useful attributes are `last_refresh` (the cached-data timestamp), `last_attempt` (the latest attempt, including failures), `next_week_events` (age matches for the digest week), and `cached_events` / `cached_events_by_branch` (unfiltered cache counts). `current_age_coverage_complete`, `supplemental_age_coverage_complete`, and the warning/failure lists explain the coverage state. Attempt counts and `last_attempt_error_categories` help distinguish current request failures from older cached results.

| Symptom | Next step |
| --- | --- |
| A known event is missing | Check its official date, branch, age wording, and cancellation status; then check coverage warnings. Try another match mode only if its inclusion rules fit what you want. |
| Status is Limited | Read the supplemental limitations and check the official branch calendar for missing later events. More frequent polling cannot remove a publisher feed cap. |
| Status is Partial or Error | Press **Refresh events** and wait for the result. Inspect `last_attempt` and its error categories if the request fails. Home Assistant retries automatically. |
| Setup is retrying and entities are absent | Inspect the integration's setup error and network access to the library feeds. Home Assistant handles initial-setup retries; the refresh button appears after setup succeeds. |
| The digest action reports unavailable data or changed settings | Wait for a successful setup/refresh or completed reload, then run it again. |
| SMTP sends text but images are missing | Check Local Media, pass `digest.attachments`, inspect image metadata, and send before cleanup. Also check the mail client's image policy. |
| A subscription does not update | Check whether its Home Assistant address is reachable by that subscriber, whether publication is enabled, and whether the URL was regenerated. The app may still be waiting for its next poll. |

A complete failure keeps the previous cache; a partially successful refresh replaces it with the successful sources from that attempt. The native Home Assistant calendar becomes unavailable after complete failure, while subscriptions and cache-only digest renders can still use the retained cache. The Status sensor and refresh button remain available for diagnosis after an established integration loses its sources. A first eligible complete runtime failure can schedule an expedited retry after five minutes; `expedited_retry_scheduled` reports that case. See [recovery mechanics](architecture.md#recovery-retains-evidence-without-concealing-failure) for retry eligibility and shared refresh timing.

For direct subscription troubleshooting, HTTP `404` means the token does not match an enabled, loaded entry; `503` means no cache is available for an otherwise valid entry; `304` means the conditional request found no change. Opening the URL successfully proves reachability from that client only.

If the problem persists, download the integration's diagnostics and report the Home Assistant version, integration version, relevant official event links, and reproduction steps in the [issue tracker](https://github.com/ItsColby/free-library-events/issues). Diagnostics redact the configured name, birth date, and calendar name, and omit the subscription token. Review any additional screenshots, traces, and logs before sharing them.

## Privacy and removal

The display name and birth date stay in Home Assistant configuration. Feed requests reveal selected branches and age categories to the library, together with ordinary network request information. The configured Home Assistant location is used locally for email layout priority; it is not sent to the library. Rendered digests contain the person's name and age, so notification recipients and retained automation traces may receive that information. A subscription exposes its selected events and calendar name to anyone holding its URL.

To remove the integration:

1. Disable any automations or scripts that render or send its digest, and remove subscriptions from calendar apps you no longer want to use.
2. In **Settings > Devices & services > Free Library Events**, use the entry's three-dot menu and select **Delete**. Its entities are unloaded, and its subscription URL no longer serves a feed.
3. In HACS, remove the downloaded repository and restart Home Assistant. For a manual installation, remove only `custom_components/free_library_events` from your Home Assistant configuration directory and restart. [HACS removal](https://hacs.xyz/docs/use/repositories/dashboard/#removing-a-repository) removes downloaded files separately from integration data.

Already delivered email, calendar copies, Home Assistant backups, and retained history or traces are not erased by these steps. Temporary managed image files normally expire after an hour; deleting the entry is not a promise of immediate file cleanup. If manually cleaning up leftovers after removal, remove only this integration's `.free_library_events_email` directory in the media directory it used and, if present, its fallback directory under `www`.
