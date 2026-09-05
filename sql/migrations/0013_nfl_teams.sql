-- NFL vertical slice, step 1: league row + 32 team entities. Adds
-- nfl_abbr the same way fbref_id/understat_id/api_football_id already
-- exist on teams -- one nullable, unique per-source id column, not a
-- separate alias table. A dedicated team_aliases table only earns its
-- keep once a second NFL data source needs reconciling against this
-- one; nflverse/nfl_data_py is the only source for this sport today.
-- The 32 abbreviations match nfl_data_py's own team_abbr convention,
-- which is what the ingestion adapter (separate ticket) will look up by.

ALTER TABLE futbol.teams ADD COLUMN IF NOT EXISTS nfl_abbr TEXT UNIQUE;

INSERT INTO futbol.leagues (code, name, is_international, sport)
VALUES ('NFL', 'National Football League', false, 'football')
ON CONFLICT (code) DO NOTHING;

INSERT INTO futbol.teams (name, country, is_national, nfl_abbr) VALUES
    ('Arizona Cardinals', 'USA', false, 'ARI'),
    ('Atlanta Falcons', 'USA', false, 'ATL'),
    ('Baltimore Ravens', 'USA', false, 'BAL'),
    ('Buffalo Bills', 'USA', false, 'BUF'),
    ('Carolina Panthers', 'USA', false, 'CAR'),
    ('Chicago Bears', 'USA', false, 'CHI'),
    ('Cincinnati Bengals', 'USA', false, 'CIN'),
    ('Cleveland Browns', 'USA', false, 'CLE'),
    ('Dallas Cowboys', 'USA', false, 'DAL'),
    ('Denver Broncos', 'USA', false, 'DEN'),
    ('Detroit Lions', 'USA', false, 'DET'),
    ('Green Bay Packers', 'USA', false, 'GB'),
    ('Houston Texans', 'USA', false, 'HOU'),
    ('Indianapolis Colts', 'USA', false, 'IND'),
    ('Jacksonville Jaguars', 'USA', false, 'JAX'),
    ('Kansas City Chiefs', 'USA', false, 'KC'),
    ('Las Vegas Raiders', 'USA', false, 'LV'),
    ('Los Angeles Chargers', 'USA', false, 'LAC'),
    ('Los Angeles Rams', 'USA', false, 'LA'),
    ('Miami Dolphins', 'USA', false, 'MIA'),
    ('Minnesota Vikings', 'USA', false, 'MIN'),
    ('New England Patriots', 'USA', false, 'NE'),
    ('New Orleans Saints', 'USA', false, 'NO'),
    ('New York Giants', 'USA', false, 'NYG'),
    ('New York Jets', 'USA', false, 'NYJ'),
    ('Philadelphia Eagles', 'USA', false, 'PHI'),
    ('Pittsburgh Steelers', 'USA', false, 'PIT'),
    ('San Francisco 49ers', 'USA', false, 'SF'),
    ('Seattle Seahawks', 'USA', false, 'SEA'),
    ('Tampa Bay Buccaneers', 'USA', false, 'TB'),
    ('Tennessee Titans', 'USA', false, 'TEN'),
    ('Washington Commanders', 'USA', false, 'WAS')
ON CONFLICT (nfl_abbr) DO NOTHING;
