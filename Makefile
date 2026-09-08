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
	PYTHONPATH=src mypy --ignore-missing-imports scripts/generate_slate.py scripts/generate_nfl_slate.py scripts/generate_nba_slate.py scripts/auto_slate.py scripts/auto_grade.py scripts/archive_old_shots.py scripts/check_model_drift.py scripts/check_pipeline_health.py scripts/daily_digest.py scripts/migrate.py scripts/rebuild_features.py scripts/review_queue.py scripts/data_quality_checks.py scripts/make_coverage_badge.py scripts/quick_look.py scripts/quick_look_wc.py scripts/predict_and_log_wc.py scripts/train_dixon_coles.py scripts/train_props.py scripts/train_props_corners.py scripts/train_props_goals.py scripts/train_props_player_goals.py scripts/train_props_saves.py src/ops/ntfy.py src/ingestion/api_football.py src/ingestion/nfl_data.py src/ingestion/nba_data.py src/models/nfl_power_ratings.py src/models/nba_power_ratings.py src/models/nba_player_points.py src/models/nfl_player_props.py api/judgment_filter.py

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
