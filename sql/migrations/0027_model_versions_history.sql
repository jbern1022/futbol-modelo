-- Append-only retrain history, decided 2026-09-16 (Todoist decision #7:
-- "add a separate append-only history table" over "redesign model_versions
-- itself to be append-only" -- see that ticket comment for the fuller
-- tradeoff writeup and the deferred alternative).
--
-- model_versions itself stays exactly as-is: ON CONFLICT (model_name,
-- version_tag) DO UPDATE, one row per (model_name, version_tag), because
-- predictions.model_version_id is a real FK into it and every write site
-- (generate_slate.py, generate_nfl_slate.py, generate_nba_slate.py,
-- train_dixon_coles.py, train_props.py, predict_and_log_wc.py) hardcodes
-- version_tag='v1' (or similarly static) rather than bumping it per
-- retrain -- so model_versions is correctly a "current pointer" table,
-- and every daily retrain overwrites the SAME row, permanently losing
-- yesterday's params/train_metrics. That's the exact gap that made
-- home_advantage_history need its own table (migration 0024) rather than
-- reusing model_versions -- same root cause, now fixed the same way.
--
-- model_versions_history is append-only: every write site now inserts
-- one full snapshot row here in addition to (not instead of) the
-- existing model_versions upsert, so "what changed on every retrain"
-- (the public model-changelog page, task 6hCcMX74CQc5Rh8f) has an
-- actual series to read from. No FK to model_versions.model_version_id
-- on purpose -- that id is reused/overwritten across retrains under the
-- current design, so it isn't a stable per-event identifier; trained_at
-- plus (model_name, version_tag) is what makes each row's place in the
-- series unambiguous.
CREATE TABLE futbol.model_versions_history (
    history_id       BIGSERIAL PRIMARY KEY,
    model_name       TEXT NOT NULL,
    version_tag      TEXT NOT NULL,
    training_window  TEXT,
    params           JSONB,
    train_metrics    JSONB,
    trained_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_model_versions_history_name_time
    ON futbol.model_versions_history (model_name, trained_at DESC);

GRANT SELECT ON futbol.model_versions_history TO futbol_ro;
