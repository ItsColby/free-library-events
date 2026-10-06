# Changing and validating the integration

A contribution needs evidence for the behavior it changes and for the environment
in which that behavior runs. This guide explains how to choose that evidence,
and reproduce it locally. For the data model and runtime
boundaries, read [Architecture](architecture.md); for caller behavior and examples,
read the [user guide](usage.md).

## Validation lanes

The [Validate workflow](../.github/workflows/validate.yaml) defines the CI jobs
and the **Release gate** that requires them,
[`.pre-commit-config.yaml`](../.pre-commit-config.yaml) the static hooks, and
[`.github/dependabot.yml`](../.github/dependabot.yml) the dependency update
policy. The [Dependabot auto-merge workflow](../.github/workflows/dependabot-auto-merge.yaml)
merges its Actions and pre-commit updates once required checks pass. Local
checks do not replace HACS, authorize publication, or establish
live behavior.

## Start with the affected contract

| Change | Implementation and evidence to inspect together |
| --- | --- |
| Settings or entry lifecycle | `config.py`, `config_flow.py`, `__init__.py`; config-flow, migration, reload, and unload cases in `test_integration_ha.py` |
| RSS requests, taxonomy, or source coverage | `api.py`, `coordinator.py`; `test_acquisition_ha.py` and acquisition cases in `test_integration_ha.py` |
| Parsing, matching, deduplication, or email presentation | `model.py`, `matching.py`, `email_render.py`, `digest.py`; `test_digest.py`, plus HA action tests for response orchestration |
| Calendar or subscription behavior | `calendar_data.py`, `calendar.py`, `webcal.py`; native calendar and HTTP cases in `test_integration_ha.py` |
| Image download, attachment, or cleanup behavior | `email_images.py`, `__init__.py`; `test_email_images.py` and digest-action cases in `test_integration_ha.py` |
| Help text or public metadata | `translations/en.json`, `services.yaml`, `icons.json`, `manifest.json`, `hacs.json`; `test_metadata.py` and affected flow/render tests |
| Validation itself | `.github/workflows/validate.yaml`, `.pre-commit-config.yaml`, `.gitleaks.toml`, and `pyproject.toml` (including its `dev`, `ha-minimum`, and `ha-current` dependency groups) |

Python modules are under `custom_components/free_library_events/`; tests are
under `tests/`. Keep identity, settings storage, action-response fields, and their
consumers aligned. A changed schema or unique ID needs a migration or explicit
compatibility decision, not just updated descriptions. Use public synthetic test
inputs. Household recipients, profiles, subscription tokens, deployment routes,
and operational records belong outside this repository.

To support another branch, extend the public registry in `model.py` and verify
that its feeds parse correctly. Include deterministic coverage for the addition
and update the supported-branch documentation before treating it as supported.

## Run the checks locally

Install the static checks once and run them before pushing:

```bash
python -m pip install --group dev
pre-commit install
pre-commit run --all-files
```

Formatting, lint, and strict typing policy live in
[`pyproject.toml`](../pyproject.toml).

The Home Assistant tests need Linux (or WSL) and Python 3.14. Use a separate
virtual environment for each maintained environment. The `ha-minimum` and
`ha-current` [dependency groups](../pyproject.toml) pin the lane's Core version,
test harness and mypy together; installing only the harness does not establish
the intended Core version.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --group ha-current  # or ha-minimum
python -m pip check
python -m mypy  # ha-current only; CI runs it in the current lane
python -m pytest tests
```

Name individual test modules while iterating. Hassfest and HACS run only in CI.

For documentation changes, validate claims against their source owners, check
links and examples, and run metadata or behavior tests affected by the wording.
For runtime work, exercise the changed success/failure paths and both maintained
HA environments.

The supported minimum Core is pinned in the `ha-minimum` and the current target
in the `ha-current` [dependency group](../pyproject.toml). Keep these
targets and the minimum in [`hacs.json`](../hacs.json) consistent when support
changes. An exact current lane is evidence for that Core
version, not an assurance about every newer one.

Gitleaks uses its default credential rules plus the repository's
[`.gitleaks.toml`](../.gitleaks.toml) rules for private paths, addresses,
hostnames, and non-example email addresses. It does not inspect ignored files
or release assets; a passing result is not a universal proof that no private
information exists. Review the actual outgoing content as well.

## Prepare a release

Releases are immutable [GitHub Releases](https://github.com/ItsColby/free-library-events/releases)
whose tag matches the manifest version. Before every release, compare the
publisher's RSS builder age/type options with the local taxonomy, including when
local acquisition code has not changed. Inspect the builder through a browser
when its access challenge requires one; it is a release-time source review, not
a runtime polling dependency, and the acquisition boundary remains the RSS
endpoint.
