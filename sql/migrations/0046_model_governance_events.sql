-- Model-governance event log (Todoist 6hqqP99w59C6F7vf, ADR-021): one champion per league/market cohort,
-- isolated shadow challengers, no automatic promotion. APPEND-ONLY (no UPDATE/DELETE), like the ledger.
-- The database refuses an incomplete promotion (named approver, rollback version, head-to-head evidence,
-- >= 1,250 graded predictions) and a promotion after a failure without a root cause approved AFTER the
-- failure. Nothing reads this yet: slate routing is still the single hard-coded model per cohort, so
-- applying this changes no behaviour.
CREATE TABLE IF NOT EXISTS futbol.model_governance_events (
    event_id                 BIGSERIAL PRIMARY KEY,
    occurred_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    league                   TEXT NOT NULL,
    market                   TEXT NOT NULL,
    event_type               TEXT NOT NULL CHECK (event_type IN (
                                 'CHAMPION_ASSIGNED', 'CHALLENGER_REGISTERED', 'CHALLENGER_RETIRED',
                                 'PROMOTED', 'RELEGATED', 'SUSPENDED', 'ROOT_CAUSE_APPROVED')),
    model_version_id         INT REFERENCES futbol.model_versions(model_version_id),
    rollback_model_version_id INT REFERENCES futbol.model_versions(model_version_id),
    approved_by              TEXT,
    root_cause_category      TEXT,           -- free text until the owner approves a taxonomy (ADR-021)
    evidence                 JSONB NOT NULL DEFAULT '{}',
    notes                    TEXT,
    -- DB-enforced completeness. COALESCE(..., false) because a CHECK passes on NULL.
    CONSTRAINT governance_event_complete CHECK (COALESCE(CASE event_type
        WHEN 'CHAMPION_ASSIGNED'     THEN approved_by IS NOT NULL AND model_version_id IS NOT NULL
        WHEN 'CHALLENGER_REGISTERED' THEN model_version_id IS NOT NULL
        WHEN 'CHALLENGER_RETIRED'    THEN model_version_id IS NOT NULL
        WHEN 'RELEGATED'             THEN notes IS NOT NULL
        WHEN 'SUSPENDED'             THEN notes IS NOT NULL
        WHEN 'ROOT_CAUSE_APPROVED'   THEN approved_by IS NOT NULL AND root_cause_category IS NOT NULL
        WHEN 'PROMOTED'              THEN approved_by IS NOT NULL AND model_version_id IS NOT NULL
                                          AND rollback_model_version_id IS NOT NULL
                                          AND evidence ? 'head_to_head'
                                          AND CASE WHEN (evidence->>'challenger_graded_n') ~ '^[0-9]+$'
                                                   THEN (evidence->>'challenger_graded_n')::int >= 1250
                                                   ELSE false END
        END, false))
);
CREATE INDEX IF NOT EXISTS idx_governance_events_cohort ON futbol.model_governance_events (league, market, event_id);

CREATE OR REPLACE FUNCTION futbol.forbid_governance_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'model_governance_events are immutable (ledger integrity)';
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION futbol.check_governance_event() RETURNS trigger AS $$
DECLARE
    last_state_id BIGINT;
    last_state_type TEXT;
    last_root_cause BIGINT;
BEGIN
    IF NEW.event_type = 'PROMOTED' THEN
        SELECT event_id, event_type INTO last_state_id, last_state_type
        FROM futbol.model_governance_events
        WHERE league = NEW.league AND market = NEW.market
          AND event_type IN ('CHAMPION_ASSIGNED', 'PROMOTED', 'RELEGATED', 'SUSPENDED')
        ORDER BY event_id DESC LIMIT 1;
        IF last_state_type IN ('RELEGATED', 'SUSPENDED') THEN
            SELECT max(event_id) INTO last_root_cause FROM futbol.model_governance_events
            WHERE league = NEW.league AND market = NEW.market AND event_type = 'ROOT_CAUSE_APPROVED';
            IF last_root_cause IS NULL OR last_root_cause < last_state_id THEN
                RAISE EXCEPTION 'promotion after a failure needs an approved root cause recorded after the failure';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_governance_events_no_update ON futbol.model_governance_events;
CREATE TRIGGER trg_governance_events_no_update
    BEFORE UPDATE OR DELETE ON futbol.model_governance_events
    FOR EACH ROW EXECUTE FUNCTION futbol.forbid_governance_mutation();
DROP TRIGGER IF EXISTS trg_governance_events_rules ON futbol.model_governance_events;
CREATE TRIGGER trg_governance_events_rules
    BEFORE INSERT ON futbol.model_governance_events
    FOR EACH ROW EXECUTE FUNCTION futbol.check_governance_event();

-- Current state per cohort, derived from the log: ACTIVE with a champion, or SUSPENDED with none.
CREATE OR REPLACE VIEW futbol.v_cohort_state AS
SELECT DISTINCT ON (league, market)
       league, market, event_id, event_type, occurred_at, approved_by,
       CASE WHEN event_type IN ('CHAMPION_ASSIGNED', 'PROMOTED') THEN 'ACTIVE' ELSE 'SUSPENDED' END AS state,
       CASE WHEN event_type IN ('CHAMPION_ASSIGNED', 'PROMOTED') THEN model_version_id END AS champion_model_version_id,
       CASE WHEN event_type = 'PROMOTED' THEN rollback_model_version_id END AS rollback_model_version_id
FROM futbol.model_governance_events
WHERE event_type IN ('CHAMPION_ASSIGNED', 'PROMOTED', 'RELEGATED', 'SUSPENDED')
ORDER BY league, market, event_id DESC;

-- Registered challengers that are neither retired nor since promoted. They run in isolation: never published.
CREATE OR REPLACE VIEW futbol.v_cohort_shadows AS
SELECT r.league, r.market, r.model_version_id
FROM futbol.model_governance_events r
WHERE r.event_type = 'CHALLENGER_REGISTERED'
  AND NOT EXISTS (
      SELECT 1 FROM futbol.model_governance_events x
      WHERE x.league = r.league AND x.market = r.market AND x.model_version_id = r.model_version_id
        AND x.event_type IN ('CHALLENGER_RETIRED', 'PROMOTED') AND x.event_id > r.event_id);
