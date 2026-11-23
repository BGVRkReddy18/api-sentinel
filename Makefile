.PHONY: install up down logs seed test test-pg lint format migrate revision

install:            ## Install app + dev dependencies into the current venv
	pip install -r requirements-dev.txt

up:                 ## Start Postgres, API, demo target, Prometheus and Grafana
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api

seed:               ## Register demo endpoints (run after `make up`)
	docker compose exec api python scripts/seed_demo.py

test:               ## Fast test suite on SQLite
	pytest -m "not postgres"

test-pg:            ## Full suite against the compose Postgres (needs `make up`)
	docker compose exec db psql -U sentinel -tc "SELECT 1 FROM pg_database WHERE datname='sentinel_test'" | grep -q 1 \
	  || docker compose exec db psql -U sentinel -c "CREATE DATABASE sentinel_test"
	TEST_DATABASE_URL=postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel_test pytest --cov

lint:
	ruff check .

format:
	ruff check --fix . && ruff format .

migrate:
	alembic upgrade head

revision:           ## make revision m="add column"
	alembic revision --autogenerate -m "$(m)"
