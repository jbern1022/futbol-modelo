-- Point-in-time snapshots of what each prediction was built from (Todoist 6hf57MCf77fRr9Xf).
--
-- One append-only row per saved prediction: cutoff, input freshness, feature values,
-- missing features and (CARDS) whether a real referee was known when the slate locked.
-- Separate from predictions.context on purpose (the web "why" panel renders every
-- context key as a number). Immutable like predictions and prediction_grades (ADR-002):
-- no UPDATE or DELETE, and post-cutoff information is rejected before it gets here
-- (src/predictions/snapshot.py). Existing predictions get no row: nothing is back-filled,
-- because history must not be reconstructed from today's tables.
CREATE TABLE IF NOT EXISTS futbol.prediction_snapshots (
    prediction_id    BIGINT PRIMARY KEY REFERENCES futbol.predictions(prediction_id),
    schema_version   INT NOT NULL,
    cutoff_at        TIMESTAMPTZ NOT NULL,
    kickoff_at       TIMESTAMPTZ NOT NULL,
    inputs_through   TIMESTAMPTZ,
    n_games          INT,
    window_days      INT,
    model_tag        TEXT NOT NULL,
    feature_values   JSONB NOT NULL,
    missing_features TEXT[] NOT NULL DEFAULT '{}',
    referee_known    BOOLEAN,
    referee_name     TEXT,
    referee_used     TEXT,
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (cutoff_at < kickoff_at),
    CHECK (inputs_through IS NULL OR inputs_through <= cutoff_at)
);

CREATE OR REPLACE FUNCTION futbol.forbid_snapshot_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'prediction_snapshots are immutable (ledger integrity)';
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prediction_snapshots_no_update ON futbol.prediction_snapshots;
CREATE TRIGGER trg_prediction_snapshots_no_update
    BEFORE UPDATE OR DELETE ON futbol.prediction_snapshots
    FOR EACH ROW EXECUTE FUNCTION futbol.forbid_snapshot_mutation();
