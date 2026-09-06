-- NBA vertical slice, step 1: league row + 30 team entities. Adds
-- nba_team_id the same way fbref_id/understat_id/api_football_id/
-- nfl_abbr already exist on teams -- nba_api's own numeric team id
-- (e.g. 1610612737) is the stable key its endpoints report everywhere,
-- more so than the 3-letter tricode (which the same static module also
-- provides on lookup, so nothing is lost by keying on the id instead).

ALTER TABLE futbol.teams ADD COLUMN IF NOT EXISTS nba_team_id BIGINT UNIQUE;

INSERT INTO futbol.leagues (code, name, is_international, sport)
VALUES ('NBA', 'National Basketball Association', false, 'basketball')
ON CONFLICT (code) DO NOTHING;

INSERT INTO futbol.teams (name, country, is_national, nba_team_id) VALUES
    ('Atlanta Hawks', 'USA', false, 1610612737),
    ('Boston Celtics', 'USA', false, 1610612738),
    ('Brooklyn Nets', 'USA', false, 1610612751),
    ('Charlotte Hornets', 'USA', false, 1610612766),
    ('Chicago Bulls', 'USA', false, 1610612741),
    ('Cleveland Cavaliers', 'USA', false, 1610612739),
    ('Dallas Mavericks', 'USA', false, 1610612742),
    ('Denver Nuggets', 'USA', false, 1610612743),
    ('Detroit Pistons', 'USA', false, 1610612765),
    ('Golden State Warriors', 'USA', false, 1610612744),
    ('Houston Rockets', 'USA', false, 1610612745),
    ('Indiana Pacers', 'USA', false, 1610612754),
    ('Los Angeles Clippers', 'USA', false, 1610612746),
    ('Los Angeles Lakers', 'USA', false, 1610612747),
    ('Memphis Grizzlies', 'USA', false, 1610612763),
    ('Miami Heat', 'USA', false, 1610612748),
    ('Milwaukee Bucks', 'USA', false, 1610612749),
    ('Minnesota Timberwolves', 'USA', false, 1610612750),
    ('New Orleans Pelicans', 'USA', false, 1610612740),
    ('New York Knicks', 'USA', false, 1610612752),
    ('Oklahoma City Thunder', 'USA', false, 1610612760),
    ('Orlando Magic', 'USA', false, 1610612753),
    ('Philadelphia 76ers', 'USA', false, 1610612755),
    ('Phoenix Suns', 'USA', false, 1610612756),
    ('Portland Trail Blazers', 'USA', false, 1610612757),
    ('Sacramento Kings', 'USA', false, 1610612758),
    ('San Antonio Spurs', 'USA', false, 1610612759),
    ('Toronto Raptors', 'USA', false, 1610612761),
    ('Utah Jazz', 'USA', false, 1610612762),
    ('Washington Wizards', 'USA', false, 1610612764)
ON CONFLICT (nba_team_id) DO NOTHING;
