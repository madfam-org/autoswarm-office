.PHONY: dev worker build test lint clean docker-up docker-down db-migrate setup generate-assets generate-variants post-process generate-map

# ── Development ─────────────────────────────────────
dev:
	pnpm dev & uv run --directory apps/nexus-api uvicorn nexus_api.main:app --host 0.0.0.0 --port 4300 --reload & uv run --directory apps/workers python -m autoswarm_workers

worker:
	uv run --directory apps/workers python -m autoswarm_workers

build:
	pnpm build
	uv build

test:
	pnpm test
	uv run pytest

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
	pnpm clean
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true

# ── Docker ──────────────────────────────────────────
docker-up:
	docker compose -f infra/docker/docker-compose.yml up -d

docker-down:
	docker compose -f infra/docker/docker-compose.yml down

docker-dev:
	docker compose -f infra/docker/docker-compose.dev.yml up -d

# ── Database ────────────────────────────────────────
db-migrate:
	uv run --directory apps/nexus-api alembic upgrade head

db-seed:
	uv run python scripts/seed-agents.py

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

# ── Setup ───────────────────────────────────────────
setup:
	bash scripts/setup.sh

install:
	pnpm install
	uv sync
