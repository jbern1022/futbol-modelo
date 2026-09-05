.PHONY: install lint typecheck test coverage features ingest slate grade review dq-check web-dev web-build

LEAGUE ?= MLS
DAYS ?= 21

install:
	pip install -r requirements.txt -r requirements-api.txt -r requirements-dev.txt
	cd web && npm install

lint:
	ruff check src scripts api
	cd web && npm run lint

# Scoped to the files that are actually type-hinted so far -- the real
# nightly-pipeline scripts. Expand this list as more of scripts/ gets
# hints; running mypy against the whole untyped tree today would just
# be noise.
typecheck:
	PYTHONPATH=src mypy --ignore-missing-imports scripts/generate_slate.py scripts/auto_slate.py scripts/auto_grade.py scripts/archive_old_shots.py scripts/check_model_drift.py scripts/check_pipeline_health.py scripts/daily_digest.py src/ops/ntfy.py src/ingestion/api_football.py api/judgment_filter.py

test:
	PYTHONPATH=src pytest

coverage:
	PYTHONPATH=src pytest --cov=src --cov=api --cov=scripts --cov-report=term-missing
	python scripts/make_coverage_badge.py

features:
	psql "$$FUTBOL_DSN" -f sql/features.sql

ingest:
	PYTHONPATH=src python -m ingestion.loader backfill --league $(LEAGUE)

slate:
	python scripts/auto_slate.py --league $(LEAGUE) --days $(DAYS)

grade:
	python scripts/auto_grade.py

review:
	python scripts/review_queue.py

dq-check:
	python scripts/data_quality_checks.py

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build
