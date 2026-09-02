.PHONY: install install-all quickstart quickstart-serve test test-fast test-unit test-integration test-sharded production-readiness production-readiness-static verify-local verify-full-stack lint lint-invariants lint-mypy lint-ruff format fix clean tree \
        security \
        dev dev-stack-start dev-stack-stop dev-stack-restart dev-stack-status dev-stack-logs bootstrap-skills \
        up up-full down logs restart ps rebuild \
        k8s-apply k8s-delete k8s-status \
        frontend-install frontend-dev frontend-build frontend-clean frontend-typecheck \
        dev-full dev-full-example \
        openapi-snapshot frontend-types refresh-model-capabilities

# ─── Toolchain ───────────────────────────────────────
# Prefer the project venv over whatever `python` resolves to on PATH. Without
# this, targets run against an unrelated interpreter that lacks the dev deps —
# e.g. `lint-mypy` failed with "No module named mypy" while .venv had mypy
# installed, so the type ratchet silently never ran and `make lint` died.
# Override with `make PYTHON=/path/to/python <target>`.
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else printf '%s' python; fi)
FAST_TEST_MARKERS := not slow and not integration and not contract and not live

# ─── Install ─────────────────────────────────────────
install:  ## Install development dependencies
	pip install -e ".[dev]"

install-all:  ## Install all optional dependencies
	pip install -e ".[dev,all]"

quickstart:  ## Bootstrap local config and run environment checks
	$(PYTHON) -m runtime quickstart --non-interactive

quickstart-serve:  ## Bootstrap local config and start the FastAPI service
	$(PYTHON) -m runtime quickstart --non-interactive --serve

# ─── Test ────────────────────────────────────────────
test:  ## Run pytest with coverage
	$(PYTHON) -m pytest --cov=runtime --cov=tools -v

test-fast:  ## Run the fast local pytest subset without coverage
	$(PYTHON) -m pytest -m "$(FAST_TEST_MARKERS)" -q

test-unit:  ## Run unit tests excluding slow, integration, contract, and live tests
	$(PYTHON) -m pytest -m "$(FAST_TEST_MARKERS)" -v

test-integration:  ## Run integration tests
	$(PYTHON) -m pytest -m integration -v

test-sharded:  ## Run unit tests in sequential shards (works around the macOS 26 allocator SIGTRAP)
	PYTHON="$(PYTHON)" bash scripts/test_sharded.sh $(SHARD_SIZE)

production-readiness:  ## Run the production readiness gate with isolated runtime state
	@mkdir -p $${OCTOPUS_READINESS_DATA_DIR:-test-results/production-readiness/data}
	OCTOPUS_HOME=$${OCTOPUS_READINESS_HOME:-test-results/production-readiness} \
	OCTOPUS_DATA_DIR=$${OCTOPUS_READINESS_DATA_DIR:-test-results/production-readiness/data} \
	$${PYTHON:-$$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else printf '%s' python; fi)} -m scripts.production_readiness_gate \
		--review-queue-path "$${OCTOPUS_READINESS_REVIEW_QUEUE:-test-results/production-readiness/data/review_queue.json}" \
		--json-output "$${OCTOPUS_READINESS_REPORT:-test-results/production-readiness/readiness_gate.json}"

production-readiness-static:  ## Run deterministic readiness checks (explicitly not release proof)
	@mkdir -p $${OCTOPUS_READINESS_DATA_DIR:-test-results/production-readiness/data}
	OCTOPUS_HOME=$${OCTOPUS_READINESS_HOME:-test-results/production-readiness} \
	OCTOPUS_DATA_DIR=$${OCTOPUS_READINESS_DATA_DIR:-test-results/production-readiness/data} \
	$${PYTHON:-$$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else printf '%s' python; fi)} -m scripts.production_readiness_gate \
		--static-only \
		--review-queue-path "$${OCTOPUS_READINESS_REVIEW_QUEUE:-test-results/production-readiness/data/review_queue.json}" \
		--json-output "$${OCTOPUS_READINESS_REPORT:-test-results/production-readiness/readiness_gate.json}"

verify-local:  ## Run backend/frontend/full-stack local stability gates
	bash scripts/verify_local.sh

verify-full-stack:  ## Run the FastAPI + Vite localhost/127 smoke only
	bash scripts/verify_local.sh --full-stack-only

# ─── Lint ────────────────────────────────────────────
lint: lint-invariants lint-fixtures lint-untracked-sources lint-mypy lint-ruff  ## Run all linters

lint-invariants:  ## Run Octopus invariant checks (active: LINT-02/03/04/05/09)
	$(PYTHON) -m tools.lint.invariant_check runtime/ tests/

lint-fixtures:  ## No test fixture input may be hidden from git by .gitignore
	$(PYTHON) -m tools.lint.fixture_visibility_check

lint-untracked-sources:  ## No source file may sit untracked in a source root (audit 2026-08-28 P0-1)
	$(PYTHON) -m tools.lint.untracked_source_check

lint-mypy:  ## Run the mypy ratchet (no NEW type errors on hot packages)
	$(PYTHON) tools/lint/mypy_ratchet.py

secret-scan:  ## Scan git history for leaked secrets (requires gitleaks)
	gitleaks git --no-banner --redact

lint-ruff:  ## Run ruff
	$(PYTHON) -m ruff check runtime/ tests/ tools/
	$(PYTHON) -m ruff format --check runtime/ tests/ tools/

format:  ## Run ruff format
	$(PYTHON) -m ruff format runtime/ tests/ tools/

fix:  ## Run ruff fixes and formatting
	$(PYTHON) -m ruff check --fix runtime/ tests/ tools/
	$(PYTHON) -m ruff format runtime/ tests/ tools/

security:  ## Run security scans (bandit + pip-audit)
	$(PYTHON) -m bandit -r runtime/ -ll -ii
	$(PYTHON) -m pip_audit

# ─── Clean ───────────────────────────────────────────
clean-noise:  ## Remove workspace noise + list stray root entries (audit A-09)
	./scripts/clean_workspace_noise.sh

clean:  ## Clean caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf build/ dist/ *.egg-info .coverage htmlcov/

# ─── Registry · local/development prompt refresh ─────
# Production ignores this mutable cache and uses the immutable bundled catalog.
bootstrap-skills:  ## Refresh local registry skills from skills.lock.json → skills/public
	$(PYTHON) -m octopus_runtime bootstrap --lockfile skills.lock.json --skills-dir skills/public

dev:  ## Run local development server with config.local.yaml and .env
	@test -f config.local.yaml || { echo "ERROR: config.local.yaml 不存在 · 先建一份真 LLM 配置（可参考 config.example.yaml 然后改 model + mock_response=null）"; exit 1; }
	@test -f .env || { echo "ERROR: .env 不存在 · 填 ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL 等"; exit 1; }
	$(PYTHON) -m runtime serve --config config.local.yaml --port 8000

dev-stack-start:  ## Start persistent macOS frontend:3888 + backend:8888 services
	$(PYTHON) tools/dev_stack.py start

dev-stack-stop:  ## Stop persistent local development services
	$(PYTHON) tools/dev_stack.py stop

dev-stack-restart:  ## Restart persistent local development services
	$(PYTHON) tools/dev_stack.py restart

dev-stack-status:  ## Show persistent local development service health
	$(PYTHON) tools/dev_stack.py status

dev-stack-logs:  ## Show recent persistent local development service logs
	$(PYTHON) tools/dev_stack.py logs

up:  ## Start the minimal single-container compose stack
	@if [ ! -f config.yaml ]; then cp config.example.yaml config.yaml; test -f .env || cp .env.example .env; echo "ERROR: created config.yaml/.env; enable oct or local_auth with a strong secret, then rerun make up"; exit 1; fi
	@test -f .env || cp .env.example .env
	@mkdir -p data
	docker compose up -d
	@echo "→ http://localhost:8000/  ·  logs: make logs"

up-full:  ## Start the full compose stack
	@if [ ! -f config.yaml ]; then cp config.example.yaml config.yaml; test -f .env || cp .env.example .env; echo "ERROR: created config.yaml/.env; enable oct or local_auth with a strong secret, then rerun make up-full"; exit 1; fi
	@test -f .env || cp .env.example .env
	@mkdir -p data data/redis data/grafana
	docker compose -f docker-compose.full.yml up -d
	@echo "→ Agent    http://localhost:8000/"
	@echo "→ Jaeger   http://localhost:16686/"
	@echo "→ Grafana  http://localhost:3000/   (admin / configured GRAFANA_PASSWORD)"

down:  ## Stop and remove containers while keeping ./data
	-docker compose down
	-docker compose -f docker-compose.full.yml down

logs:  ## Tail agent logs
	docker compose logs -f octopus-agent

restart:  ## Restart the agent container after config changes
	docker compose restart octopus-agent

ps:  ## Show compose process status
	docker compose ps

rebuild:  ## Rebuild image and restart after code changes
	docker compose build --no-cache octopus-agent
	docker compose up -d octopus-agent

k8s-apply:  ## Apply deploy/k8s with kustomize
	@if ! grep -Eq '^[[:space:]]*digest:[[:space:]]*sha256:[0-9a-fA-F]{64}[[:space:]]*$$' deploy/k8s/kustomization.yaml || grep -Eq '^[[:space:]]*digest:[[:space:]]*sha256:0{64}[[:space:]]*$$' deploy/k8s/kustomization.yaml; then echo "ERROR: set images[].digest in deploy/k8s/kustomization.yaml to a non-zero cosign-verified release digest"; exit 1; fi
	kubectl apply -k deploy/k8s/

k8s-delete:  ## Delete k8s resources; namespace PVCs may need manual cleanup
	kubectl delete -k deploy/k8s/

k8s-status:  ## Show namespace resources
	kubectl -n octopus-agent get all,pvc,cm,secret

# ─── Frontend · Vite + React ─────────────────────────
frontend-install:  ## Install frontend dependencies
	cd frontend && corepack enable && pnpm install --frozen-lockfile

frontend-dev:  ## Run the frontend dev server
	cd frontend && pnpm dev

dev-full:  ## Start backend and frontend with config.local.yaml
	cd frontend && pnpm dev:full

dev-full-example:  ## Start backend and frontend with config.example.yaml
	cd frontend && pnpm dev:full:example

frontend-build:  ## Build frontend/dist for FastAPI /ui mounting
	cd frontend && pnpm build

frontend-typecheck:  ## Run TypeScript type checking
	cd frontend && pnpm typecheck

frontend-clean:  ## Clean frontend build outputs
	rm -rf frontend/dist frontend/.vite frontend/node_modules/.vite

# ─── OpenAPI contract ────────────────────────────────
openapi-snapshot:  ## Regenerate docs/openapi-snapshot.json
	OCTOPUS_OPENAPI_WRITE=1 $(PYTHON) -m pytest tests/test_openapi_snapshot.py -q

refresh-model-capabilities:  ## Refresh resources/models/capabilities.json from models.dev
	$(PYTHON) -m tools.refresh_model_capabilities

frontend-types:  ## Generate TypeScript types from the OpenAPI snapshot
	cd frontend && pnpm exec openapi-typescript ../docs/openapi-snapshot.json -o src/core/api/openapi-types.ts

# ─── Utilities ───────────────────────────────────────
tree:  ## Show a compact tracked-file tree
	@git ls-files | xargs -I {} echo {} | head -100

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
