.PHONY: install lint test features ingest slate grade web-dev web-build

LEAGUE ?= MLS
DAYS ?= 21

install:
	pip install -r requirements.txt -r requirements-api.txt
	cd web && npm install

lint:
	ruff check src scripts api
	cd web && npm run lint

test:
	PYTHONPATH=src pytest

features:
	psql "$$FUTBOL_DSN" -f sql/features.sql

ingest:
	PYTHONPATH=src python -m ingestion.loader backfill --league $(LEAGUE)

slate:
	python scripts/auto_slate.py --league $(LEAGUE) --days $(DAYS)

grade:
	python scripts/auto_grade.py

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build
