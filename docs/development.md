# Development and releases

Use [architecture.md](architecture.md) for runtime ownership and invariants, and
[usage.md](usage.md) for the user contract. This guide owns contributor setup,
validation, and the release sequence. The commands below run from the repository
root and do not install the integration into Home Assistant or publish a release.

## Source owners

| Concern | Owner |
| --- | --- |
| Runtime code, configuration flow, actions, translations, and icons | [`custom_components/free_library_events`](../custom_components/free_library_events) |
| Integration version and runtime metadata | [`manifest.json`](../custom_components/free_library_events/manifest.json) |
| HACS distribution minimum | [`hacs.json`](../hacs.json) |
| Exact supported Core environments | [`requirements-ha-test.txt`](../requirements-ha-test.txt) and [`requirements-ha-current.txt`](../requirements-ha-current.txt) |
| Tool and harness pins, container digests, and executable checks | [`verify-release-local.sh`](../scripts/verify-release-local.sh) |
| Formatting, lint, typing, and pytest settings | [`pyproject.toml`](../pyproject.toml) |
| Hosted jobs and aggregate gate | [`validate.yaml`](../.github/workflows/validate.yaml) |
| Historical release changes and evidence | [`RELEASE_NOTES.md`](../RELEASE_NOTES.md) |

Change the implementation and its direct consumers together. Preserve stored
configuration keys, entity identity, and action response fields unless the
change includes an explicit compatibility or migration contract. User-visible
text belongs in the integration's translation and action metadata, with examples
and explanations in the usage guide.

Before each release, compare the publisher's RSS builder options with the
local age and event-type taxonomy, even when acquisition code is unchanged.
The runtime uses RSS, not protected publisher
event pages or ICS endpoints; a browser-only source inspection is separate from
the automated test suite. Adding a branch requires public metadata, feed and
parsing checks, deterministic tests, and documentation. Keep household schedules,
recipients, deployment addresses, and operational evidence outside this public
repository.

## Run validation locally

The default container backend requires Linux, Bash, Git, standard shell tools,
rootless Podman, and network access to fetch pinned images and dependencies.
It supplies Python and validation tools inside the containers.

```bash
bash scripts/verify-release-local.sh all container
```

On Windows, the PowerShell entry point uses the `Ubuntu-24.04` WSL distribution
with rootless Podman installed there. It maps both the source directory and its
actual Git directory into WSL, including linked worktrees.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-release-local.ps1
```

Select an individual lane while iterating:

```bash
bash scripts/verify-release-local.sh unit container
bash scripts/verify-release-local.sh minimum container
bash scripts/verify-release-local.sh current container
bash scripts/verify-release-local.sh release container
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-release-local.ps1 -Mode current
```

Both entry points locate the source relative to the script, so they also work
when invoked by path from another directory. `all` and `container` are the Bash
defaults. `--help` prints the supported arguments.

| Lane | Checks |
| --- | --- |
| `unit` | actionlint with ShellCheck; shell-script ShellCheck; zizmor with the auditor persona and strict collection; Ruff formatting and lint; dependency-light unit tests; compile checks; JSON, metadata, translation, icon, and whitespace contracts; public-source guard |
| `minimum` | Exact minimum Core and harness installation, dependency closure, strict mypy, and all three HA test modules |
| `current` | Exact current Core and harness installation, installed-metadata and dependency validation, and all three HA test modules |
| `release` | Hassfest only |
| `all` | Unit/static checks, both HA support lanes, then Hassfest |

The dependency-light suite covers digest behavior, metadata, public safety,
the patch-compatibility checker, and validation orchestration. The HA lanes each
run [`test_integration_ha.py`](../tests/test_integration_ha.py),
[`test_email_images.py`](../tests/test_email_images.py), and
[`test_acquisition_ha.py`](../tests/test_acquisition_ha.py). These cover real Core
integration behavior, image preparation and cleanup, acquisition failures, and
recovery. Missing supported dependencies or APIs fail collection; a test run
with skipped or uncollected HA modules does not establish HA compatibility.

For a focused digest check using a local Python 3.14 installation:

```bash
python -m unittest discover -s tests -p "test_digest.py"
```

That command does not replace the other lanes. Documentation-only changes need
checks of affected references, metadata, examples, and source claims; choose
additional product tests for the contracts being changed. Runtime changes need
the relevant behavior tests and the complete release gates before release.

### Native Linux backend

Hosted unit and HA jobs call the same Bash runner with `native`. To use it
locally, provide Linux with Python 3.14, working `venv` and pip support, Bash,
Git, and network access. The unit lane also requires Go to build pinned
actionlint; the native `release` lane requires Docker for Hassfest.

```bash
bash scripts/verify-release-local.sh all native
```

Each Python lane creates and removes a separate temporary virtual environment.
Actionlint and its ShellCheck dependency use a temporary tool environment too.
`all native` runs sequentially against the source checkout, so keep that source
stable for the duration of the run. Generated Python and tool caches may appear
in the checkout under the normal ignore rules. Windows compatibility shims are
not a supported substitute for the Linux HA harness.

### Snapshot, concurrency, and cleanup

Container runs first copy the current tracked and nonignored untracked files
into a temporary Linux source tree. They include uncommitted edits and new files,
omit deleted files and ignored content, normalize executable bits from Windows
DrvFS, and create a Git index for tools that need one. No commit, hook, signing
operation, or original Git history is copied. Keep edits stable while the
snapshot is being created. Every container receives the selected tree read-only.

After `unit` succeeds, `all container` starts the minimum and current HA lanes
concurrently in separate fresh containers. It waits for both results before
removing the shared snapshot, including when one lane fails. Hassfest runs only
after both succeed. Running a single lane remains a serial operation; choose
separate `minimum` and `current` runs if the host cannot comfortably run both.

The Podman volume `free-library-events-validation-pip` retains downloaded
packages and wheels between runs. Installed environments and check results are
never reused. Container installs defer dependency bytecode generation until
imports, mypy does not retain its cache, and the explicit product compile check
still runs. Only unit containers provision Git, because the HA-only lanes do not
use it. Disposable containers and source snapshots are removed on normal exit;
native environments have their own exit cleanup.

To discard the download cache, first ensure no local validation is using it:

```bash
podman volume rm free-library-events-validation-pip
```

A timeout or interrupted process does not prove a lane passed or that cleanup
completed. Inspect the surviving process or container before retrying, and retain
the original output when diagnosing failure. The runner's tests exercise lane
ordering, failure propagation, environment isolation, snapshot selection, and
cleanup without installing the external dependencies.

## Core support and dependency evidence

The supported-minimum lane targets **Core 2026.8.0 with harness 0.13.354**; the
current lane targets **Core 2026.9.1 with harness 0.13.364**. The harness is
`pytest-homeassistant-custom-component`. Exact Core and supporting package pins
live in the two requirements files; harness and tool pins live in the runner.
Keep the HACS minimum, those owners, workflow names, and this guide aligned when
support changes. The current lane names an exact tested target, not a promise
about every later Core release.

Each HA lane installs its harness first, then its exact requirements in a
separate step. The minimum lane runs `python -m pip check` after all dependency
installation and rejects any conflict. The current lane uses
[`check_ha_patch_compatibility.py`](../scripts/check_ha_patch_compatibility.py)
to verify the installed Core version, the harness's declared exact Core
requirement, and the result of `pip check` before tests. The configured matching
Core/harness pairs are dependency-closure lanes.

The checker also supports one narrowly defined exception for a future pin
change: a later stable patch within the minimum Core's year and month may use a
harness whose Core pin lies between that minimum and current patch. Only the
single metadata-proven harness/Core mismatch is accepted. A cross-month
mismatch, prerelease, additional conflict, or unexpected `pip check` output fails.
The exception establishes patch compatibility, not dependency closure, and
still requires the complete HA test surface to pass. It does not permit changing
installed metadata, hiding conflicts, or substituting a fake harness.

## Public-source review

[`check_public_safety.py`](../scripts/check_public_safety.py) checks candidate
file names and contents for private paths, local addresses and hostnames,
non-example email addresses, and known credential shapes. It rejects unreviewed
binary content, symbolic links, junctions, unsupported file types, and incomplete
inventory. Reviewed binary hashes are bound to exact paths in the guard.

In a Git checkout the inventory is tracked plus nonignored untracked files. A
source archive without Git uses a filesystem inventory with generated-directory
exclusions. Neither mode scans original Git history, ignored files, or remote
release assets. The container snapshot's fresh index does not change that
boundary. A passing guard is a bounded candidate-content check, not proof that
all secrets or historical private data are absent. Review the exact outgoing
content and any separately relevant history or artifacts before publication.

Examples should use fictional profiles and reserved example addresses. Keep
real diagnostics, calendar subscription URLs, personal identifiers, and private
deployment instructions out of commits and issue attachments. Preserve existing
license text and historical release facts; new validation results belong with
the exact candidate or release that produced them.

## Hosted checks and release sequence

[`Validate`](../.github/workflows/validate.yaml) runs on pull requests, pushes to
`main`, and manual dispatch. It uses Ubuntu 24.04, read-only repository
permissions, nonpersistent checkout credentials, immutable action references,
and bounded job timeouts. Its **Release gate** succeeds only when the unit,
minimum HA, current HA, Hassfest, and HACS jobs all succeed. New runs can cancel
superseded runs in the same workflow/event/ref concurrency group.

Local `all` includes Hassfest but does not run the hosted HACS public repository
metadata check or CodeQL. CodeQL is configured through GitHub's default setup
for Python and GitHub Actions, outside the checked-in Validate workflow.
Successful CodeQL execution means analysis completed; review the alerts as well.
GitHub repository settings can change independently of source, so read them back
when preparing a release. The configured `main` protection requires an up-to-date
**Release gate**, applies to administrators, and requires linear history; it does
not currently require a pull-request review count.

1. Prepare a release candidate with the manifest version, intended immutable
   `vYYYY.M.D` tag, release title, and release notes aligned. Preserve historical
   release evidence and identify any remaining source or compatibility limits.
2. Run the local checks, compare the publisher's age and event-type options with
   the local taxonomy, and open
   the release pull request. Wait for all Validate jobs and the aggregate
   **Release gate**, plus CodeQL's **Analyze (actions)**, **Analyze (python)**,
   and **CodeQL** checks. Inspect failures and findings rather than treating a
   submitted run as completed evidence.
3. Merge through the current default-branch protection without bypass, using
   squash or rebase to keep history linear. The pull request is the release
   procedure; it does not imply that repository settings require reviewers.
4. On the resulting `main` commit, require a successful Validate push run and
   CodeQL analysis. Inspect complete logs and open code-scanning alerts, and
   resolve or explicitly disposition findings introduced by the candidate.
5. Publish the immutable tag and GitHub Release from that exact validated
   `main` commit. The local validation runner does not perform either publication
   operation.

[Dependabot](../.github/dependabot.yml) proposes weekly GitHub Actions updates
after a seven-day cooldown. Python pins move with the product's Core and harness
contract rather than a separate automatic pip update stream.

HACS selection or installation, a Home Assistant configuration check, restart,
live validation, and rollback are later deployment steps. This source guide does
not establish that an installation has adopted a release. Instance backups,
delivery automations, proxy configuration, and recovery evidence remain with
the deployment owner.
