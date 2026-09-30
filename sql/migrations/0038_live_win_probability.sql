-- ADR-011: in-play win-probability (Todoist "futbol-modelo: in-play/
-- live win-probability updates", Phase 3). Backend-only per explicit
-- direction -- no UI yet.
--
-- Deliberately NOT the immutable predictions ledger (ADR-002): this
-- updates continuously throughout a live match (every ~60s), while a
-- prediction locks once before kickoff and never changes. A time
-- series, full history retained per user decision (2026-09-30) --
-- same precedent as match_odds_history, not match_odds' latest-only
-- shape, since how win-probability MOVED during the match is the
-- actually interesting signal for a future live chart.
CREATE TABLE IF NOT EXISTS live_win_probability (
    id              BIGSERIAL PRIMARY KEY,
    match_id        INT NOT NULL REFERENCES matches(match_id),
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    minute          INT NOT NULL,
    home_score      INT NOT NULL,
    away_score      INT NOT NULL,
    home_win_prob   NUMERIC(6,5) NOT NULL,
    draw_prob       NUMERIC(6,5) NOT NULL,
    away_win_prob   NUMERIC(6,5) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_live_winprob_match
    ON live_win_probability (match_id, computed_at);
