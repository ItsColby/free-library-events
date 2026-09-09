#!/usr/bin/env bash
set -euo pipefail
mode="${1:-all}"
backend="${2:-container}"
source_git_dir="${3:-}"
usage() {
  echo "Usage: bash scripts/verify-release-local.sh [all|unit|minimum|current|release] [container|native] [git-dir]"
}
if [[ "$mode" == --help || "$mode" == -h ]]; then
  usage
  exit 0
fi
if (( $# > 3 )); then
  usage >&2
  exit 2
fi
case "$mode" in
  all|unit|minimum|current|release) ;;
  *) echo "Unknown mode: $mode" >&2; usage >&2; exit 2 ;;
esac
case "$backend" in
  container|native) ;;
  *) echo "Unknown backend: $backend" >&2; usage >&2; exit 2 ;;
esac
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$source_root"
if [[ "$backend" == container ]]; then
  repo_root="$(mktemp -d)"
  trap 'rm -rf "$repo_root"' EXIT
  source_git=(git -C "$source_root")
  if [[ -n "$source_git_dir" ]]; then
    source_git=(git --git-dir="$source_git_dir" --work-tree="$source_root")
  fi
  "${source_git[@]}" ls-files --cached --others --exclude-standard -z |
    while IFS= read -r -d '' path; do
      if [[ -e "$source_root/$path" || -L "$source_root/$path" ]]; then
        printf '%s\0' "$path"
      fi
    done |
    tar -C "$source_root" --null --files-from=- --create --file=- |
    tar -C "$repo_root" --extract --file=-
  # The pinned Actionlint image runs as an unprivileged user.
  chmod a+rx "$repo_root"
  # DrvFS exposes regular files as executable unless metadata is enabled.
  find "$repo_root" -type f -exec chmod a-x {} +
  git -C "$repo_root" init -q
  # Index the complete selected tree without inheriting global ignore rules or
  # invoking commit hooks/signing; source checks need an index, not fake history.
  git -C "$repo_root" add --force --all
fi

python_image="docker.io/library/python@sha256:a7fb1e634c4a578f9e0bd6327f11a3cde11b7a9395f48e24360c0988bcc5c2bc"
actionlint_image="docker.io/rhysd/actionlint@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"
hassfest_image="ghcr.io/home-assistant/hassfest@sha256:8cd7bdb8f82430c2c13703290b1fc38dcc99957dd76ad3f230035ecee70b672d"
run_python() (
  if [[ "$backend" == native ]]; then
    # Each lane gets its own environment, including when `all native` is used.
    venv="$(mktemp -d)"
    trap 'rm -rf "$venv"' EXIT
    python -m venv "$venv"
    cd "$repo_root"
    VIRTUAL_ENV="$venv" PATH="$venv/bin:$PATH" bash -euo pipefail -c "$1"
  else
    podman run --rm -e HOME=/tmp/home -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
      -e PIP_ROOT_USER_ACTION=ignore -e DEBIAN_FRONTEND=noninteractive \
      -e PYTHONPYCACHEPREFIX=/tmp/pycache -e XDG_CACHE_HOME=/tmp/cache \
      -e RUFF_CACHE_DIR=/tmp/ruff-cache -e MYPY_CACHE_DIR=/tmp/mypy-cache \
      -e 'PYTEST_ADDOPTS=-p no:cacheprovider' \
      -v "$repo_root:/workspace" -w /workspace "$python_image" bash -euo pipefail -c \
      'apt-get update -qq; apt-get install -y -qq --no-install-recommends git >/dev/null; eval "$1"' \
      local-validation "$1"
  fi
)
run_actionlint() (
  cd "$repo_root"
  if [[ "$backend" == native ]]; then
    bin="$(mktemp -d)"
    trap 'rm -rf "$bin"' EXIT
    python -m venv "$bin"
    "$bin/bin/python" -m pip install "shellcheck-py==0.11.0.1"
    GOBIN="$bin/bin" go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
    PATH="$bin/bin:$PATH" "$bin/bin/actionlint"
  else
    podman run --rm -v "$repo_root:/repo:ro" -w /repo "$actionlint_image"
  fi
)
run_unit() {
  run_actionlint
  run_python '
    python -m pip install "ruff==0.16.2" "shellcheck-py==0.11.0.1" "zizmor==1.29.0"
    shellcheck scripts/verify-release-local.sh
    zizmor --strict-collection --persona auditor .
    python -m ruff format --check custom_components tests scripts
    python -m ruff check custom_components tests scripts
    python -m unittest discover -s tests -p "test_digest.py"
    python -m unittest discover -s tests -p "test_metadata.py"
    python -m unittest discover -s tests -p "test_public_safety.py"
    python -m unittest discover -s tests -p "test_ha_patch_compatibility.py"
    python -m unittest discover -s tests -p "test_validation_runner.py"
    python -m compileall -q custom_components/free_library_events tests scripts
    python scripts/check_public_safety.py
  '
}
run_minimum() {
  run_python '
    python -m pip install "pytest-homeassistant-custom-component==0.13.354"
    python -m pip install --upgrade -r requirements-ha-test.txt
    python -m pip install "mypy==2.3.0"
    python -m pip check
    python -m mypy custom_components/free_library_events
    pytest tests/test_integration_ha.py tests/test_email_images.py tests/test_acquisition_ha.py -q
  '
}
run_current() {
  run_python '
    python -m pip install "pytest-homeassistant-custom-component==0.13.364"
    python -m pip install --upgrade -r requirements-ha-current.txt
    python scripts/check_ha_patch_compatibility.py --minimum requirements-ha-test.txt --current requirements-ha-current.txt
    pytest tests/test_integration_ha.py tests/test_email_images.py tests/test_acquisition_ha.py -q
  '
}
run_release() {
  if [[ "$backend" == native ]]; then
    docker run --rm -v "$repo_root:/github/workspace:ro" "$hassfest_image"
  else
    podman run --rm -v "$repo_root:/github/workspace:ro" "$hassfest_image"
  fi
}
case "$mode" in
  all) run_unit; run_minimum; run_current; run_release ;;
  unit) run_unit ;;
  minimum) run_minimum ;;
  current) run_current ;;
  release) run_release ;;
esac
printf 'Local validation passed: %s (%s)\n' "$mode" "$backend"
if [[ "$mode" == all || "$mode" == release ]]; then
  echo "HACS and hosted release checks remain separate; this command does not publish."
fi
