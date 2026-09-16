#!/usr/bin/env bash
set -euo pipefail
mode="${1:-affected}"
backend="${2:-container}"
source_git_dir="${3:-}"
usage() {
  echo "Usage: bash scripts/verify-release-local.sh [affected|all|unit|minimum|current|release] [container|native] [git-dir]"
}
if [[ "$mode" == --help || "$mode" == -h ]]; then
  usage
  exit 0
fi
if [[ "$mode" != affected ]] && (( $# > 3 )); then
  usage >&2
  exit 2
fi
case "$mode" in
  all|unit|minimum|current|release|affected) ;;
  *) echo "Unknown mode: $mode" >&2; usage >&2; exit 2 ;;
esac
case "$backend" in
  container|native) ;;
  *) echo "Unknown backend: $backend" >&2; usage >&2; exit 2 ;;
esac
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$source_root"
validation_python="${VALIDATION_PYTHON:-}"
if [[ "$mode" == affected && -z "$validation_python" ]]; then
  if command -v python3.14 >/dev/null 2>&1; then
    validation_python="$(command -v python3.14)"
  elif command -v uv >/dev/null 2>&1; then
    validation_python="$(uv python find 3.14 --no-python-downloads)"
  elif [[ -x "$HOME/.local/bin/uv" ]]; then
    validation_python="$("$HOME/.local/bin/uv" python find 3.14 --no-python-downloads)"
  else
    echo "Affected planning requires Python 3.14; set VALIDATION_PYTHON to an existing interpreter." >&2
    exit 2
  fi
fi
affected_args=()
affected_only=""
affected_plan=""
if [[ "$mode" == affected ]]; then
  if (( $# >= 3 )); then shift 3; else shift "$#"; fi
  plan_only=false
  while (( $# )); do
    case "$1" in
      --only) affected_only="${2:?Missing lane}"; shift 2 ;;
      --plan-only) plan_only=true; shift ;;
      *) affected_args+=("$1"); shift ;;
    esac
  done
  if [[ -n "$source_git_dir" ]]; then affected_args+=(--git-directory "$source_git_dir"); fi
  affected_plan="$("$validation_python" "$source_root/scripts/plan_validation.py"  "${affected_args[@]}")"

  if [[ -n "$affected_only" && "$affected_only" != unit && "$affected_only" != minimum && "$affected_only" != current && "$affected_only" != release ]]; then
    echo "Unknown affected lane: $affected_only" >&2; exit 2
  fi
  if [[ -n "$affected_only" && "$(printf '%s' "$affected_plan" | "$validation_python" -c 'import json,sys; print(str(json.load(sys.stdin)["jobs"][sys.argv[1]]).lower())' "$affected_only")" != true ]]; then
    echo "Plan did not select $affected_only" >&2; exit 2
  fi
  if [[ "$plan_only" == true ]]; then printf '%s\n' "$affected_plan"; exit 0; fi
  if [[ "$(printf '%s' "$affected_plan" | "$validation_python" -c 'import json,sys; print(any(json.load(sys.stdin)["jobs"].values()))')" == False ]]; then
    echo "No validation jobs apply to the verified empty comparison."; exit 0
  fi
fi

if [[ "$backend" == container ]]; then
  repo_root="$(mktemp -d)"
  # A signal can interrupt `wait` while the parallel lanes still own this tree.
  # Reap them before cleanup, and suppress later gates after an interruption.
  trap 'trap "" INT TERM; wait; rm -rf "$repo_root"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
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
  # HA-only lanes opt out of Git provisioning needed by unit tooling/fixtures.
  local needs_git="${2:-true}"
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
      -e PIP_COMPILE=0 -e PIP_CACHE_DIR=/pip-cache \
      -e PYTHONPYCACHEPREFIX=/tmp/pycache -e XDG_CACHE_HOME=/tmp/cache \
      -e RUFF_CACHE_DIR=/tmp/ruff-cache -e MYPY_CACHE_DIR=/dev/null \
      -e 'PYTEST_ADDOPTS=-p no:cacheprovider' \
      -v "$repo_root:/workspace:ro" -w /workspace \
      --mount type=volume,source=free-library-events-validation-pip,target=/pip-cache \
      "$python_image" bash -euo pipefail -c \
      'if [[ "$1" == true ]]; then apt-get update -qq; apt-get install -y -qq --no-install-recommends git >/dev/null; fi; eval "$2"' \
      local-validation "$needs_git" "$1"
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
    python -m unittest discover -s tests -p "test_parallel_validation.py"
    python -m unittest discover -s tests -p "test_validation_selection.py"
    python -m compileall -q custom_components/free_library_events tests scripts
    python scripts/check_public_safety.py
  '
}
run_minimum() {
  local checks='    python -m pip install "mypy==2.3.0"
    python -m pip check
    python -m mypy custom_components/free_library_events
    pytest tests -q --ignore=tests/test_digest.py --ignore=tests/test_metadata.py --ignore=tests/test_public_safety.py --ignore=tests/test_ha_patch_compatibility.py --ignore=tests/test_validation_runner.py --ignore=tests/test_parallel_validation.py --ignore=tests/test_validation_selection.py'
  if [[ "$mode" == affected ]]; then
    checks="$("$validation_python" "$source_root/scripts/plan_validation.py"  "${affected_args[@]}" --command minimum)"
  fi
  run_python '
    python -m pip install "pytest-homeassistant-custom-component==0.13.354" || exit "$?"
    python -m pip install --upgrade -r requirements-ha-test.txt || exit "$?"
'"$checks" false
}
run_current() {
  local checks='    python scripts/check_ha_patch_compatibility.py --minimum requirements-ha-test.txt --current requirements-ha-current.txt
    pytest tests -q --ignore=tests/test_digest.py --ignore=tests/test_metadata.py --ignore=tests/test_public_safety.py --ignore=tests/test_ha_patch_compatibility.py --ignore=tests/test_validation_runner.py --ignore=tests/test_parallel_validation.py --ignore=tests/test_validation_selection.py'
  if [[ "$mode" == affected ]]; then
    checks="$("$validation_python" "$source_root/scripts/plan_validation.py"  "${affected_args[@]}" --command current)"
  fi
  run_python '
    python -m pip install "pytest-homeassistant-custom-component==0.13.364" || exit "$?"
    python -m pip install --upgrade -r requirements-ha-current.txt || exit "$?"
'"$checks" false
}
run_ha_matrix() {
  if [[ "$backend" == native ]]; then
    run_minimum
    run_current
  else
    # Containers read one immutable payload; installed environments stay separate.
    local minimum_pid current_pid minimum_status=0 current_status=0
    run_minimum & minimum_pid=$!
    run_current & current_pid=$!
    # Always reap both lanes before the parent can remove the payload.
    wait "$minimum_pid" || minimum_status=$?
    wait "$current_pid" || current_status=$?
    printf 'Home Assistant lanes: minimum=%s current=%s\n' "$minimum_status" "$current_status"
    (( minimum_status == 0 && current_status == 0 ))
  fi
}
run_release() {
  if [[ "$backend" == native ]]; then
    docker run --rm -v "$repo_root:/github/workspace:ro" "$hassfest_image"
  else
    podman run --rm -v "$repo_root:/github/workspace:ro" "$hassfest_image"
  fi
}

run_affected() {
  local lane selected command
  for lane in unit minimum current release; do
    [[ -z "$affected_only" || "$lane" == "$affected_only" ]] || continue
    selected="$(printf '%s' "$affected_plan" | "$validation_python" -c 'import json,sys; print(str(json.load(sys.stdin)["jobs"][sys.argv[1]]).lower())' "$lane")"
    if [[ "$selected" != true ]]; then
      if [[ -n "$affected_only" ]]; then echo "Plan did not select $lane" >&2; return 2; fi
      continue
    fi
    case "$lane" in
      unit)
        if [[ "$(printf '%s' "$affected_plan" | "$validation_python" -c 'import json,sys; print(str(json.load(sys.stdin)["workflow"]).lower())')" == true ]]; then
          run_actionlint
        fi
        command="$("$validation_python" "$source_root/scripts/plan_validation.py"  "${affected_args[@]}" --command unit)"
        run_python "$command"
        ;;
      minimum) run_minimum ;;
      current) run_current ;;
      release) run_release ;;
    esac
  done
}

case "$mode" in
  affected) run_affected ;;
  all) run_unit; run_ha_matrix; run_release ;;
  unit) run_unit ;;
  minimum) run_minimum ;;
  current) run_current ;;
  release) run_release ;;
esac
printf 'Local validation passed: %s (%s)\n' "$mode" "$backend"
if [[ "$mode" == all || "$mode" == release ]]; then
  echo "HACS and hosted release checks remain separate; this command does not publish."
fi
