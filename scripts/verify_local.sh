#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

run_backend=1
run_frontend_static=1
run_frontend_build="${OCTOPUS_VERIFY_SKIP_BUILD:-0}"
run_full_stack="${OCTOPUS_VERIFY_SKIP_FULL_STACK:-0}"
run_full_stack_mobile="${OCTOPUS_VERIFY_FULL_STACK_MOBILE:-0}"

usage() {
  cat <<'EOF'
Usage: scripts/verify_local.sh [--full-stack-only]

Runs the local stability gate:
  - targeted backend regressions for model compatibility, team tasks, and org runs
  - frontend typecheck, lint, and build
  - full-stack Playwright smoke for FastAPI + Vite across localhost/127.0.0.1

Environment:
  PYTHON                         Python executable. Defaults to .venv/bin/python, then python3/python.
  OCTOPUS_VERIFY_SKIP_BUILD=1     Skip frontend production build.
  OCTOPUS_VERIFY_SKIP_FULL_STACK=1 Skip full-stack Playwright smoke.
  OCTOPUS_VERIFY_FULL_STACK_MOBILE=1
                                  Also run mobile full-stack Playwright smoke.
  OCTOPUS_LIVE_MODEL_SMOKE=1      Also run live OpenAI-compatible provider smoke tests.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --full-stack-only)
      run_backend=0
      run_frontend_static=0
      run_frontend_build=1
      run_full_stack=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

resolve_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    printf '%s\n' "$PYTHON"
    return
  fi
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$ROOT_DIR/.venv/bin/python"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  command -v python
}

section() {
  printf '\n==> %s\n' "$1"
}

PYTHON_BIN="$(resolve_python)"
export PYTHON="$PYTHON_BIN"

backend_tests=(
  tests/test_openai_router.py
  tests/test_openai_compat_providers.py
  tests/test_app_config_endpoints.py::TestCustomModelCompatDiagnostics
  tests/test_organization.py
  tests/test_team_tasks_router.py
)

if [[ "${OCTOPUS_LIVE_MODEL_SMOKE:-0}" == "1" ]]; then
  backend_tests+=(tests/test_openai_compat_provider_smoke.py)
fi

if [[ "$run_backend" == "1" ]]; then
  section "backend targeted stability tests"
  "$PYTHON_BIN" -m pytest "${backend_tests[@]}" -q
fi

if [[ "$run_frontend_static" == "1" ]]; then
  section "frontend typecheck"
  (cd frontend && pnpm typecheck)

  section "frontend lint"
  (cd frontend && pnpm lint)
fi

if [[ "$run_frontend_build" != "1" ]]; then
  section "frontend build"
  (cd frontend && pnpm build)
fi

if [[ "$run_full_stack" != "1" ]]; then
  section "full-stack smoke"
  (cd frontend && PYTHON="$PYTHON_BIN" pnpm e2e:full)

  if [[ "$run_full_stack_mobile" == "1" ]]; then
    section "mobile full-stack smoke"
    (cd frontend && PYTHON="$PYTHON_BIN" pnpm e2e:full:mobile)
  fi
fi
