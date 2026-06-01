# Portable docker compose: prefer v1 standalone, fall back to v2 plugin.
DOCKER_COMPOSE := $(shell command -v docker-compose 2>/dev/null || echo "docker compose")

.PHONY: dev dev-full dev-seed worker build test test-e2e lint clean docker-up docker-down db-migrate db-wait setup setup-org-config generate-assets generate-variants post-process generate-map db-backup db-restore db-verify-backup smoke-test worktree-cleanup

# ── Development ─────────────────────────────────────
dev:
	@if [ "$$LOCAL_SERVICES" != "yes" ]; then echo "Refusing to start local services without LOCAL_SERVICES=yes"; exit 1; fi
	@bash -c '\
	trap "kill 0" EXIT SIGINT SIGTERM; \
	pnpm dev & \
	uv run --directory apps/nexus-api uvicorn nexus_api.main:app --host 0.0.0.0 --port 4300 --reload & \
	uv run --directory apps/workers python -m autoswarm_workers & \
	wait'

db-wait:
	@echo "Waiting for PostgreSQL..."
	@for i in $$(seq 1 30); do \
	  if command -v pg_isready >/dev/null 2>&1; then \
	    pg_isready -h localhost -p 5432 -q 2>/dev/null && break; \
	  else \
	    python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('localhost',5432)); s.close()" 2>/dev/null && break; \
	  fi; \
	  sleep 1; \
	done
	@echo "PostgreSQL is ready."

dev-full:
	@if [ "$$LOCAL_SERVICES" != "yes" ]; then echo "Refusing full local service stack without LOCAL_SERVICES=yes"; exit 1; fi
	@if [ "$$LOCAL_DB" != "yes" ]; then echo "Refusing local database migration/seed without LOCAL_DB=yes"; exit 1; fi
	@test -f .env || (echo "Creating .env from .env.example..." && cp .env.example .env)
	@echo "Installing dependencies..."
	$(MAKE) install
	@echo "Starting infrastructure..."
	$(DOCKER_COMPOSE) -f infra/docker/docker-compose.dev.yml up -d --wait
	$(MAKE) db-wait
	@echo "Running database migrations..."
	uv run --directory apps/nexus-api alembic upgrade head
	$(MAKE) setup-org-config
	@echo "Starting all services..."
	$(MAKE) dev &
	@echo "Waiting for nexus-api to be ready..."
	@for i in $$(seq 1 30); do \
	  curl -sf http://localhost:4300/api/v1/health/health >/dev/null 2>&1 && break; \
	  sleep 1; \
	done
	@echo "Seeding departments and agents..."
	$(MAKE) dev-seed
	@echo "Running smoke test..."
	@sleep 3 && $(MAKE) smoke-test

dev-seed:
	@if [ "$$LOCAL_DB" != "yes" ]; then echo "Refusing local database seed without LOCAL_DB=yes"; exit 1; fi
	@echo "Seeding departments and agents..."
	uv run python scripts/seed-agents.py

worker:
	@if [ "$$LOCAL_WORKER" != "yes" ]; then echo "Refusing to start local worker without LOCAL_WORKER=yes"; exit 1; fi
	uv run --directory apps/workers python -m autoswarm_workers

build:
	pnpm build
	uv build

test:
	pnpm test
	uv run pytest

test-e2e:
	pnpm test:e2e

lint:
	pnpm lint
	uv run ruff check .
	uv run mypy .

typecheck:
	pnpm typecheck
	uv run mypy .

format:
	pnpm format
	uv run ruff format .

clean:
	@if [ "$$LOCAL_DESTRUCTIVE" != "yes" ]; then echo "Refusing destructive cleanup without LOCAL_DESTRUCTIVE=yes"; exit 1; fi
	pnpm clean
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true

# ── Docker ──────────────────────────────────────────
docker-up:
	@if [ "$$LOCAL_SERVICES" != "yes" ]; then echo "Refusing to start local containers without LOCAL_SERVICES=yes"; exit 1; fi
	$(DOCKER_COMPOSE) -f infra/docker/docker-compose.yml up -d

docker-down:
	@if [ "$$LOCAL_DESTRUCTIVE" != "yes" ]; then echo "Refusing to stop/remove local containers without LOCAL_DESTRUCTIVE=yes"; exit 1; fi
	$(DOCKER_COMPOSE) -f infra/docker/docker-compose.yml down

docker-dev:
	@if [ "$$LOCAL_SERVICES" != "yes" ]; then echo "Refusing to start local dev containers without LOCAL_SERVICES=yes"; exit 1; fi
	$(DOCKER_COMPOSE) -f infra/docker/docker-compose.dev.yml up -d

# ── Database ────────────────────────────────────────
db-migrate:
	@if [ "$$LOCAL_DB" != "yes" ]; then echo "Refusing database migration without LOCAL_DB=yes"; exit 1; fi
	uv run --directory apps/nexus-api alembic upgrade head

db-seed:
	@if [ "$$LOCAL_DB" != "yes" ]; then echo "Refusing database seed without LOCAL_DB=yes"; exit 1; fi
	uv run python scripts/seed-agents.py

db-backup:
	@if [ "$$LOCAL_DB_BACKUP" != "yes" ]; then echo "Refusing database backup without LOCAL_DB_BACKUP=yes"; exit 1; fi
	bash scripts/backup-postgres.sh

db-restore:
	@if [ "$$LOCAL_DB_RESTORE" != "yes" ]; then echo "Refusing database restore without LOCAL_DB_RESTORE=yes"; exit 1; fi
	bash scripts/restore-postgres.sh $(BACKUP_FILE)

db-verify-backup:
	@if [ "$$LOCAL_DB_VERIFY" != "yes" ]; then echo "Refusing backup verification without LOCAL_DB_VERIFY=yes"; exit 1; fi
	bash scripts/verify-backup.sh $(BACKUP_FILE)

# ── Assets ─────────────────────────────────────────
generate-assets:
	node scripts/generate-assets.js

generate-variants:
	node scripts/generate-variants.js
	node scripts/generate-tile-variants.js

post-process:
	bash scripts/post-process-assets.sh

generate-map:
	node scripts/generate-map.js

generate-office-map:
	node scripts/generate-office-map.js

setup-org-config:
	@mkdir -p ~/.autoswarm
	@test -f ~/.autoswarm/org-config.yaml || \
		cp data/org-config-template.yaml ~/.autoswarm/org-config.yaml
	@echo "Org config at ~/.autoswarm/org-config.yaml"

# ── Setup ───────────────────────────────────────────
setup:
	bash scripts/setup.sh

smoke-test:
	@if [ "$$LOCAL_SMOKE" != "yes" ]; then echo "Refusing smoke test without LOCAL_SMOKE=yes"; exit 1; fi
	bash scripts/smoke-test.sh

worktree-cleanup:
	@if [ "$$LOCAL_DESTRUCTIVE" != "yes" ]; then echo "Refusing worktree cleanup without LOCAL_DESTRUCTIVE=yes"; exit 1; fi
	bash scripts/cleanup-worktrees.sh

install:
	pnpm install
	uv sync
