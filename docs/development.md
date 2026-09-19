# Changing and validating the integration

A contribution needs evidence for the behavior it changes and for the environment
in which that behavior runs. This guide explains how to choose that evidence,
reproduce it locally, and carry it into a release. For the data model and runtime
boundaries, read [Architecture](architecture.md); for caller behavior and examples,
read the [user guide](usage.md).

## Select validation for the change

The default runner mode is `affected`. Preview an exact candidate comparison
before running it:

```powershell
.\scripts\verify-release-local.ps1 -Base <base-commit> -Head HEAD -PlanOnly
.\scripts\verify-release-local.ps1 -Base <base-commit> -Head HEAD
```

For a working edit, use `-ChangedPath scripts/verify-release-local.sh` instead of
refs. On Linux, use `bash scripts/verify-release-local.sh affected container ""`
with `--base <base-commit> --head HEAD`, or repeated `--path <relative-path>`;
add `--plan-only` to inspect the JSON plan without snapshots or installations.
Planning and container snapshot admission use an existing host Python 3.14
(`python3.14`, an installed uv runtime, or `VALIDATION_PYTHON`). The public-safety
guard's link policy runs before planning reads input sources and before snapshot
copying. The planner, guard, and interpreter remain trusted executable tooling.
Planning parses input source without importing the integration. Neither step
downloads a runtime; HA execution keeps its isolated Python 3.14 lane.
Explicit paths describe the complete change being accepted. The refs mode
requires the checked-out candidate as its head; it does not include uncommitted
edits. An empty verified comparison selects no jobs. Missing comparison input
and unmapped changes fail with an unresolved applicability message.

The product-owned planner traces local Python imports and reviewed direct-file
consumers. Changed tests run in their native collector; runtime changes include
the affected success, failure, and recovery consumers in both maintained HA
environments. A support requirements change selects that environment. Minimum
requirements also select current compatibility, which reads both requirements
files, without selecting unchanged current tests or typing. Runner and workflow
dependency declarations are compared against the supplied base, or HEAD for
working-path selections;
changed harness, Python image, action, and tool pins select their actual consumers.
An unavailable dependency comparison remains unresolved. The Bash runner remains
the owner of exact local tool versions. Tooling, workflow, public-content and
metadata checks are selected independently of product tests. Configuration
changes without a reviewed tool-specific mapping need explicit review, rather
than an automatic complete run.

Pull requests and main pushes use this same selection. The stable Release gate
requires the planning job and every selected job to succeed, and accepts skipped
jobs only when the plan excludes them. Manual workflow dispatch explicitly runs
the complete lanes. `all`, `unit`, `minimum`, `current`, and `release` remain
explicit complete-lane requests. Reuse evidence whose source and environment
have not changed; a merge alone does not invalidate it. Local checks do not
replace HACS, authorize publication, or establish live behavior.

When both Home Assistant lanes are selected locally, the container runner starts
them together after selected static checks pass and waits for both before any
selected Hassfest check or snapshot cleanup. Single-lane selections and native
runs remain sequential. To limit local concurrency, run selected lanes separately
with `--only minimum` and `--only current` on the Bash affected route.

## Start with the affected contract

| Change | Implementation and evidence to inspect together |
| --- | --- |
| Settings or entry lifecycle | `config.py`, `config_flow.py`, `__init__.py`; config-flow, migration, reload, and unload cases in `test_integration_ha.py` |
| RSS requests, taxonomy, or source coverage | `api.py`, `coordinator.py`; `test_acquisition_ha.py` and acquisition cases in `test_integration_ha.py` |
| Parsing, matching, deduplication, or email presentation | `digest.py`; `test_digest.py`, plus HA action tests for response orchestration |
| Calendar or subscription behavior | `calendar_data.py`, `calendar.py`, `webcal.py`; native calendar and HTTP cases in `test_integration_ha.py` |
| Image download, attachment, or cleanup behavior | `email_images.py`, `__init__.py`; `test_email_images.py` and digest-action cases in `test_integration_ha.py` |
| Help text or public metadata | `translations/en.json`, `services.yaml`, `icons.json`, `manifest.json`, `hacs.json`; `test_metadata.py` and affected flow/render tests |
| Validation itself | `scripts/`, `.github/workflows/validate.yaml`, requirements files, and `pyproject.toml`; runner, parallel-lane, compatibility, and public-safety tests |

Python modules are under `custom_components/free_library_events/`; tests are
under `tests/`. Keep identity, settings storage, action-response fields, and their
consumers aligned. A changed schema or unique ID needs a migration or explicit
compatibility decision, not just updated descriptions. Use public synthetic test
inputs. Household recipients, profiles, subscription tokens, deployment routes,
and operational records belong outside this repository.

To support another branch, extend the public registry in `digest.py` and verify
that its feeds parse correctly. Include deterministic coverage for the addition
and update the supported-branch documentation before treating it as supported.

## Run the checks for the selected work

The normal local entry point is the repository's container runner in `affected`
mode. From the repository root on Windows, supply the candidate comparison:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-release-local.ps1 -Base <base-commit> -Head HEAD
```

It requires the `Ubuntu-24.04` WSL distribution with rootless Podman, Bash, Git,
the Python 3.14 locator above, and access to the image registries and package
sources. The wrapper resolves
both the worktree and its Git directory before invoking Linux validation.

On Linux with rootless Podman:

```bash
bash scripts/verify-release-local.sh affected container "" --base <base-commit> --head HEAD
```

Either script can also be invoked by path from another directory. Bash defaults
to `affected container`; `--help` prints its argument contract. The PowerShell wrapper
accepts `-Mode`, comparison refs or changed paths, and always uses containers for execution.

| Mode | Work performed |
| --- | --- |
| `affected` (default) | Only checks selected from the supplied comparison or explicit changed paths; unresolved applicability stops the run |
| `unit` | actionlint with ShellCheck, shell-script ShellCheck, zizmor, Ruff format/lint, seven dependency-light test modules, compile checks, and public-content validation |
| `minimum` | Minimum Core environment, dependency check, strict mypy, and the complete HA test surface |
| `current` | Current Core environment, metadata/dependency compatibility check, and the complete HA test surface |
| `release` | Hassfest |
| `all` | `unit`, both HA modes, then Hassfest |

The other modes deliberately request complete lanes without comparison arguments.
For example, use `-Mode unit` on Windows or
`bash scripts/verify-release-local.sh unit container` on Linux. Use `-Mode all`
or `bash scripts/verify-release-local.sh all container` only for an explicit
complete local check. The name `release` means the Hassfest lane alone; it is
not a complete release check or a publication command.

During a small parser/render change, this dependency-light command gives quick
feedback using Python 3.14:

```bash
python -m unittest discover -s tests -p "test_digest.py"
```

For documentation changes, validate claims against their source owners, check
links and examples, and run metadata or behavior tests affected by the wording.
For runtime work, exercise the changed success/failure paths and both maintained
HA environments. The three HA modules are `test_integration_ha.py`,
`test_email_images.py`, and `test_acquisition_ha.py`; a dependency-light pass
cannot stand in for their collection and execution.

### What a local run uses

Container validation snapshots tracked files and nonignored new files from the
working tree, including uncommitted edits. Deleted files are omitted. Keep edits
stable during snapshot creation. The snapshot is mounted read-only and receives
a fresh Git index for tools that require one; it does not inherit commit history,
commit hooks, or signing. Windows executable-bit artifacts are normalized.

Each Python lane installs dependencies into a fresh container. Package downloads
and wheels are reused through the Podman volume
`free-library-events-validation-pip`; installed environments and pass results
are not reused. Container bytecode and tool caches stay outside the snapshot.
Mypy does not retain a cache, and the explicit `compileall` check still executes.
Git is installed only in the unit container, where tools and fixtures use it.

In `all container`, unit validation must succeed before the minimum and current
HA lanes start in parallel. The runner waits for both, even if one fails, before
removing their shared snapshot. Hassfest starts only if both pass. Run the two
HA modes separately when the host should not run them concurrently.

Disposable containers and the source snapshot have exit cleanup. To remove only
the reusable download cache, first ensure no validation process is using it:

```bash
podman volume rm free-library-events-validation-pip
```

On a handled interrupt or termination signal, the container runner waits for
active lanes before removing their shared source snapshot and skips later gates.
Forced termination can still leave work running. Check for surviving work before
retrying and preserve the failure output needed for diagnosis.

### Running without Podman

The hosted unit and HA jobs use the same runner's native Linux backend:

```bash
bash scripts/verify-release-local.sh affected native "" --base <base-commit> --head HEAD
```

Provide Python 3.14 with pip and `venv`, Bash, Git, and network access. Unit mode
also needs Go to install pinned actionlint; native Hassfest needs Docker.
Each Python lane and the actionlint tooling get temporary environments with
exit cleanup. Native `all` runs sequentially against the actual checkout, which
must stay stable throughout the run. Normal ignored caches may be written there.
The real Home Assistant harness runs on Linux; Windows import shims are not a
supported compatibility test.

## Interpret the result precisely

A successful runner finishes with `Local validation passed: <mode> (<backend>)`.
Earlier dependency installation or an individual passing module does not prove
that the requested mode completed. Exact commands, tool versions, harness pins,
and image digests are owned by
[`verify-release-local.sh`](../scripts/verify-release-local.sh). Formatting,
lint, and strict typing policy live in [`pyproject.toml`](../pyproject.toml).

The two maintained environments are:

| Lane | Exact target | Core and supporting requirements |
| --- | --- | --- |
| Minimum | Core 2026.8.0 with harness 0.13.354 | [`requirements-ha-test.txt`](../requirements-ha-test.txt) |
| Current | Core 2026.9.2 with harness 0.13.365 | [`requirements-ha-current.txt`](../requirements-ha-current.txt) |

The harness is `pytest-homeassistant-custom-component`. Keep these targets,
workflow job names, requirements, runner pins, and the minimum in
[`hacs.json`](../hacs.json) consistent when support changes. An exact current
lane is evidence for that Core version, not an assurance about every newer one.

The harness is installed first and the selected requirements afterward. Minimum
mode also installs mypy, then runs `python -m pip check` before typing and tests.
Current mode invokes
[`check_ha_patch_compatibility.py`](../scripts/check_ha_patch_compatibility.py),
which checks the installed Core and the harness's exact Core requirement and
runs `pip check` in that environment. The configured matching pairs are intended
to be dependency-closed.

The checker can recognize a single harness/Core pin conflict when a newer stable
patch is tested within the minimum's own year/month and the harness pin falls
within that patch window. That exceptional result proves patch compatibility,
not dependency closure. Cross-month pin conflicts, prereleases, additional
conflicts, unexpected metadata, and unrecognized dependency-check failures fail.
The exception never permits skipped HA tests or failed collection.

The public-safety guard examines candidate paths and contents for private
addresses/paths, non-example emails, and recognized credential formats. It also
rejects unreviewed binary files, symlinks, junctions, and unsupported file types.
Its inventory is tracked plus nonignored new files in a checkout, or a filesystem
walk with generated-directory exclusions in an archive. An unavailable checkout
inventory fails the guard. See
[`check_public_safety.py`](../scripts/check_public_safety.py) for exact rules.
The guard does not inspect original Git history, ignored files, or release assets;
a passing result is not a universal proof that no private information exists.
Review the actual outgoing content and any relevant historical or external
artifacts separately.

## Carry evidence into a release

The [Validate workflow](../.github/workflows/validate.yaml) runs for pull requests,
`main` pushes, and manual dispatch. Its unit, minimum, current, Hassfest, and HACS
jobs feed the **Release gate** through the applicability plan. A selected job
that skips or fails blocks the aggregate; an excluded job must be skipped.
Jobs have bounded timeouts and read-only permissions; checkouts
do not persist credentials. Action references are pinned, and
[Dependabot](../.github/dependabot.yml) proposes weekly updates after a seven-day
cooldown. Python pins move with the supported Core/harness environments.

Local `all` does not run hosted HACS validation or CodeQL. GitHub's default CodeQL
setup covers Python and Actions separately from the checked-in workflow. Read
back repository settings when preparing a release: currently `main` requires an
up-to-date **Release gate**, including for administrators, and linear history.
It does not require a review count. Analysis success alone says nothing about
whether CodeQL found alerts.

For a release, set the manifest version to `YYYY.M.D`, with an optional `.N`
suffix for a same-day patch (for example, `2026.9.10.2`). Derive the release title
and immutable tag as `v` followed by that exact manifest value. Record the change
and its actual
validation evidence in [release notes](../RELEASE_NOTES.md), preserving previous
release facts and the [license](../LICENSE). Compare the publisher's RSS builder
age/type options with the local taxonomy before every release, including when
local acquisition code has not changed.

Inspect the builder through a browser when its access challenge requires one.
This is a release-time source review; the builder is not a runtime polling
dependency. The integration's acquisition boundary remains the RSS endpoint.

Use a release pull request and require terminal success for the planning job,
every selected Validate job, and **Release gate**. Accept a skipped job only when
the candidate's applicability plan excludes it; a selected job that skips blocks
release. Inspect CodeQL's **Analyze (actions)**, **Analyze (python)**, and **CodeQL**
checks. Merge with squash or rebase through branch protection without bypass.
On the resulting `main` commit, require its Validate push run to satisfy the same
plan-based success rule and CodeQL analysis to succeed; review complete logs and
resolve or explicitly disposition candidate-introduced alerts. Publish the
immutable tag and GitHub Release only from that exact validated commit.

Source validation, public publication, HACS installation, and live Home Assistant
adoption are separate results. The runner performs none of the latter three.
Backups, configuration checks, restart, live readback, delivery tests, and rollback
belong to the installation's deployment procedure.
