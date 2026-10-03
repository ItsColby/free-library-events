# Changing and validating the integration

A contribution needs evidence for the behavior it changes and for the environment
in which that behavior runs. This guide explains how to choose that evidence,
reproduce it locally, and carry it into a release. For the data model and runtime
boundaries, read [Architecture](architecture.md); for caller behavior and examples,
read the [user guide](usage.md).

## Validation lanes

Every pull request and `main` push runs the [Validate workflow](../.github/workflows/validate.yaml):
static checks, both maintained Home Assistant environments, Hassfest, and HACS.
Manual workflow dispatch runs the same jobs. The stable **Release gate**
requires all of them to succeed. Local checks do not replace HACS, authorize
publication, or establish live behavior.

## Start with the affected contract

| Change | Implementation and evidence to inspect together |
| --- | --- |
| Settings or entry lifecycle | `config.py`, `config_flow.py`, `__init__.py`; config-flow, migration, reload, and unload cases in `test_integration_ha.py` |
| RSS requests, taxonomy, or source coverage | `api.py`, `coordinator.py`; `test_acquisition_ha.py` and acquisition cases in `test_integration_ha.py` |
| Parsing, matching, deduplication, or email presentation | `digest.py`; `test_digest.py`, plus HA action tests for response orchestration |
| Calendar or subscription behavior | `calendar_data.py`, `calendar.py`, `webcal.py`; native calendar and HTTP cases in `test_integration_ha.py` |
| Image download, attachment, or cleanup behavior | `email_images.py`, `__init__.py`; `test_email_images.py` and digest-action cases in `test_integration_ha.py` |
| Help text or public metadata | `translations/en.json`, `services.yaml`, `icons.json`, `manifest.json`, `hacs.json`; `test_metadata.py` and affected flow/render tests |
| Validation itself | `.github/workflows/validate.yaml`, `.pre-commit-config.yaml`, `.gitleaks.toml`, requirements files, and `pyproject.toml` |

Python modules are under `custom_components/free_library_events/`; tests are
under `tests/`. Keep identity, settings storage, action-response fields, and their
consumers aligned. A changed schema or unique ID needs a migration or explicit
compatibility decision, not just updated descriptions. Use public synthetic test
inputs. Household recipients, profiles, subscription tokens, deployment routes,
and operational records belong outside this repository.

To support another branch, extend the public registry in `digest.py` and verify
that its feeds parse correctly. Include deterministic coverage for the addition
and update the supported-branch documentation before treating it as supported.

## Run the checks locally

Install the static checks once and run them before pushing:

```bash
python -m pip install --group dev
pre-commit install
pre-commit run --all-files
```

They run Ruff, ShellCheck, actionlint, zizmor, JSON and whitespace hygiene, and
Gitleaks over the current tree and Git history. Formatting, lint, and strict
typing policy live in [`pyproject.toml`](../pyproject.toml).

The Home Assistant tests need Linux (or WSL) and Python 3.14. Use a separate
virtual environment for each maintained environment and install it the way its
workflow job does: the harness and mypy pins first, then the requirements file,
then `python -m pip check`. Then run `python -m mypy custom_components/free_library_events`
and `python -m pytest tests`, or name individual test modules while iterating.
Hassfest and HACS run only in CI.

For documentation changes, validate claims against their source owners, check
links and examples, and run metadata or behavior tests affected by the wording.
For runtime work, exercise the changed success/failure paths and both maintained
HA environments.

The two maintained environments are the supported minimum Core in
[`requirements-ha-test.txt`](../requirements-ha-test.txt) and the current target
in [`requirements-ha-current.txt`](../requirements-ha-current.txt), each paired
with its `pytest-homeassistant-custom-component` harness in the workflow. Keep
these targets, workflow job names, and the minimum in [`hacs.json`](../hacs.json)
consistent when support changes. An exact current lane is evidence for that Core
version, not an assurance about every newer one.

Gitleaks uses its default credential rules plus the repository's
[`.gitleaks.toml`](../.gitleaks.toml) rules for private paths, addresses,
hostnames, and non-example email addresses. It does not inspect ignored files
or release assets; a passing result is not a universal proof that no private
information exists. Review the actual outgoing content as well.

## Carry evidence into a release

Jobs have bounded timeouts and read-only permissions; checkouts do not persist
credentials. Action references are pinned, and
[Dependabot](../.github/dependabot.yml) proposes weekly updates after a seven-day
cooldown. Python pins move with the supported Core/harness environments.
GitHub's default CodeQL setup covers Python and Actions separately from the
checked-in workflow; read back the branch protection settings when preparing a
release. Analysis success alone says nothing about whether CodeQL found alerts.

For a release, set the manifest version to `YYYY.M.D`, with an optional `.N`
suffix for a same-day patch (for example, `2026.9.10.2`). Derive the release title
and immutable tag as `v` followed by that exact manifest value. Record the change
and its actual validation evidence in the GitHub Release body. Compare the
publisher's RSS builder age/type options with the local taxonomy before every release, including when
local acquisition code has not changed.

Inspect the builder through a browser when its access challenge requires one.
This is a release-time source review; the builder is not a runtime polling
dependency. The integration's acquisition boundary remains the RSS endpoint.

Use a release pull request and require terminal success for every Validate job
and **Release gate**. Inspect CodeQL's **Analyze (actions)**, **Analyze (python)**, and **CodeQL**
checks. Merge with squash or rebase through branch protection without bypass.
On the resulting `main` commit, require every job in its Validate push run to
succeed and CodeQL analysis to succeed; review complete logs and
resolve or explicitly disposition candidate-introduced alerts. Publish the
immutable tag and GitHub Release only from that exact validated commit.

Source validation, public publication, HACS installation, and live Home Assistant
adoption are separate results. Validation performs none of the latter three.
Backups, configuration checks, restart, live readback, delivery tests, and rollback
belong to the installation's deployment procedure.
