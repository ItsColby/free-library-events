# AGENTS.md instructions for free-library-events

Apply global Codex preferences first. This file owns repo-local guidance for
the Free Library Events Home Assistant custom integration.

## Start Here

Read `docs/architecture.md` before structural, config-flow, parsing, entity,
email-rendering, or release-layout changes.

## Optimization And Quality Target

Optimize for David's private Home Assistant runtime: correctness, privacy,
recoverability, low maintenance, Home Assistant compatibility, and clear Codex
operation. Use Home Assistant's current
[integration quality scale rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/)
as a required starting reference for holistic reviews and material design or
behavior changes, but evaluate each applicable rule by evidence and local value.
The scale is not a certification target or automatic backlog. Do not add a
quality-scale artifact, pursue a coverage percentage or strict-typing campaign,
or expand the architecture unless it closes a concrete risk or materially
improves future work.

## Public Privacy Boundary

- This repository is public. Do not commit child or household names, birth
  dates, email addresses, Home Assistant entity IDs, local paths, screenshots,
  diagnostics, logs, tokens, credentials, or local deployment evidence.
- Keep maintainer-specific deployment, HACS installation, recipient, schedule,
  automation, and live-instance workflows outside this repository.
- Use synthetic names, dates, event IDs, URLs, and descriptions in tests and
  documentation. Public Free Library branch names, addresses, phone numbers,
  URLs, and feed identifiers are allowed as integration source metadata.
- Never embed maintainer-private values in public guards, tests, fixtures, or
  metadata, including split, encoded, reversed, or hashed forms. Run exact-value
  scans only from a maintainer-controlled local publication gate; do not upload
  those private values as GitHub Actions secrets.
- Run `python scripts/check_public_safety.py` before publishing changes to
  code, tests, documentation, workflows, scripts, or metadata.

## Validation

After changing `.github/workflows`, run `actionlint` from the repository root.
Keep the latest `shellcheck` available on `PATH`; the `shellcheck-py` package
provides it and actionlint uses it automatically for Bash and `sh` `run:` steps.

For focused iteration, run the directly affected unittest module, compile the
changed package/test surface, and always run the public-safety guard when the
change touches code, tests, docs, workflows, scripts, or metadata. Example:

```powershell
python -m unittest discover -s tests -p "test_digest.py"
python -m compileall -q custom_components/free_library_events tests
python scripts/check_public_safety.py
```

Before integration or release, use Python 3.14 and run the full local tier:

```powershell
python -m pip install --upgrade ruff mypy shellcheck-py zizmor
python -m pip install --upgrade -r requirements-ha-test.txt
python -m ruff format --check custom_components tests scripts
python -m ruff check custom_components tests scripts
python -m mypy --strict custom_components/free_library_events
zizmor --persona auditor .
python -m unittest discover -s tests -p "test_digest.py"
python -m unittest discover -s tests -p "test_public_safety.py"
python -m compileall -q custom_components\free_library_events tests scripts
python scripts\check_public_safety.py
python -c "import json, pathlib; [json.loads(pathlib.Path(path).read_text(encoding='utf-8')) for path in ['custom_components/free_library_events/manifest.json','custom_components/free_library_events/translations/en.json','hacs.json']]"
```

Before creating an immutable release, wait for CodeQL analysis of the exact
candidate/default-branch commit and inspect the repository's open code-scanning
alerts. A successful CodeQL workflow proves analysis completed, not that the
result has no findings. Resolve or explicitly disposition candidate-introduced
alerts before tagging.

Home Assistant tests run against both the minimum supported Core release and
the current deployed Core release:

```powershell
python -m pip install pytest-homeassistant-custom-component==0.13.345
python -m pip install --upgrade -r requirements-ha-test.txt
python -m pytest tests\test_integration_ha.py tests\test_email_images.py -q
python -m pip install pytest-homeassistant-custom-component==0.13.354
python -m pip install --upgrade -r requirements-ha-test-current.txt
python -m pytest tests\test_integration_ha.py tests\test_email_images.py -q
```

Keep the harness and exact Core installation as separate steps. The current
harness matches stable Core directly, but the daily upstream harness can
temporarily declare a beta while the matching final Core is already released;
do not encode that transient pair in one requirements transaction.

Home Assistant's test harness imports Linux-only modules. On Windows, run each
HA lane in a Linux container instead of treating a native `fcntl` import error
as an integration failure. If neither a compatible Linux environment nor the
container runtime is available, defer the HA-specific lane to the protected
GitHub workflow and report that gap explicitly.

Before reporting complete, read back `git status --short --branch` and list
any validation that could not run.
