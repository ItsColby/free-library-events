# AGENTS.md instructions for free-library-events

Apply global Codex preferences first. This file owns repo-local guidance for
the Free Library Events Home Assistant custom integration.

## Start Here

Read `docs/architecture.md` before structural, config-flow, parsing, entity,
email-rendering, or release-layout changes.

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

Use Python 3.14 and run:

```powershell
python -m unittest discover -s tests -p "test_digest.py"
python -m unittest discover -s tests -p "test_public_safety.py"
python -m compileall -q custom_components\free_library_events tests scripts
python scripts\check_public_safety.py
python -c "import json, pathlib; [json.loads(pathlib.Path(path).read_text(encoding='utf-8')) for path in ['custom_components/free_library_events/manifest.json','custom_components/free_library_events/translations/en.json','hacs.json']]"
```

Home Assistant tests require the dependencies in `requirements-ha-test.txt`:

```powershell
python -m pip install -r requirements-ha-test.txt
python -m pytest tests\test_integration_ha.py -q
```

Before reporting complete, read back `git status --short --branch` and list
any validation that could not run.
