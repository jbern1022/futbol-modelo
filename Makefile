.PHONY: install lint test coverage features ingest slate grade review dq-check web-dev web-build

LEAGUE ?= MLS
DAYS ?= 21

install:
	pip install -r requirements.txt -r requirements-api.txt -r requirements-dev.txt
	cd web && npm install

lint:
	ruff check src scripts api
	cd web && npm run lint

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
