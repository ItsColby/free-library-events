# Free Library Events

Find Free Library of Philadelphia events for one person's age in Home Assistant. Choose the branches to follow, view matching events on a calendar, and optionally send a weekly email digest or subscribe from another calendar app.

Matching runs locally against published age ranges, categories, and descriptions. Library feeds can omit events or stop before the dates you need; check the integration's coverage status and the official event details before making plans.

## Is this integration for you?

You need Home Assistant **2026.8.0 or newer** and internet access to the library's public feeds. No library account or API key is required. One integration entry supports one person, from infancy through adulthood, and any selection of these four branches:

| Branch | Official calendar |
| --- | --- |
| Charles Santore Library | [View events](https://libwww.freelibrary.org/calendar/?location_code=SWK) |
| Independence Library | [View events](https://libwww.freelibrary.org/calendar/?location_code=IND) |
| Parkway Central Library | [View events](https://libwww.freelibrary.org/calendar/?location_code=CEN) |
| Philadelphia City Institute | [View events](https://libwww.freelibrary.org/calendar/?location_code=PCI) |

The integration supplies a **Calendar**, a **Status** sensor, a **Refresh events** button, and the `free_library_events.render_digest` action. Email delivery uses your own Home Assistant notification setup; the integration does not create a schedule or send mail itself.

## Install and add your profile

With [HACS installed](https://hacs.xyz/docs/use/download/download/):

1. In HACS, open the three-dot menu and select **Custom repositories**. Add `https://github.com/ItsColby/free-library-events` with type **Integration**. See [HACS custom repository instructions](https://hacs.xyz/docs/faq/custom_repositories/).
2. Find **Free Library Events**, download it, and restart Home Assistant when prompted. HACS explains the [download and restart steps](https://hacs.xyz/docs/use/repositories/dashboard/).
3. In **Settings > Devices & services**, select **Add integration**, then **Free Library Events**.
4. Enter **Person's display name**, **Person's birth date**, and **Library branches**. All four branches are selected initially; keep at least one. Submit the form.

For a manual installation, copy the release's `custom_components/free_library_events` directory into the `custom_components` directory inside your Home Assistant configuration directory. Restart Home Assistant, then complete steps 3–4. Configure the integration through the UI; there is no `free_library_events:` YAML configuration.

The name personalizes the digest. The birth date determines age on each event date. Both are stored in Home Assistant and are not sent to the library. Selected branches and age categories are sent as feed query parameters.

## Choose how to use the results

| You want to… | Start here |
| --- | --- |
| Browse matching events in Home Assistant | Open the integration's **Calendar**; see [calendar behavior](docs/usage.md#use-the-calendar). |
| Change the person, branches, or age matching | See [settings and matching](docs/usage.md#adjust-your-profile-and-matching). |
| Follow events in another calendar app | Enable the optional [calendar subscription](docs/usage.md#subscribe-from-another-calendar-app). |
| Send a weekly digest | Use the [render and email examples](docs/usage.md#render-and-send-a-weekly-digest). |
| Investigate missing or outdated events | Read [coverage and recovery](docs/usage.md#check-coverage-and-recover). |

Events refresh every six hours by default. Start with the default **Recommended** match mode. A calendar subscription is off until you enable it; its URL grants access without a Home Assistant login, so keep it private.

For data handling and uninstall steps, see [privacy and removal](docs/usage.md#privacy-and-removal). Developers can start with [architecture](docs/architecture.md) and [development](docs/development.md). Report reproducible integration problems in the [issue tracker](https://github.com/ItsColby/free-library-events/issues), without names, birth dates, subscription URLs, or private Home Assistant details.

Licensed under the [MIT License](LICENSE). Previous changes and recorded release evidence are in [Release notes](RELEASE_NOTES.md).
