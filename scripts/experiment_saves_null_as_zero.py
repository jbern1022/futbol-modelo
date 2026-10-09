"""
Experiment: does treating NULL goalkeeper saves as 0 improve PLAYER_SAVES?
(Todoist 6hhr9v69Mw2hwmVf, 2026-10-08.)

API-Football returns goals.saves = null, not 0, for a keeper who made no
saves, so zero-save games are stored as NULL. fit_player_saves_model()
trains on `saves IS NOT NULL`, and sql/features.sql's AVG(p.saves) skips
NULLs too, so both the label and p_saves_r5 miss every zero-save game.

A NULL is relabelled 0 only when the keeper played >= 45 minutes and the
opponent's shots on target minus goals conceded is <= 1 (a keeper with
that few shots on goal faced no more than one save). Other NULLs stay
unknown. Candidate A fixes the label only; candidate B also rebuilds
p_saves_r5 with the zeros (same window as features.sql: previous 5
appearances). Both are scored against the production model on the same
held-out later games, labelled with the relabelled saves, at the 3.5 line.

Read-only against the database; models are fit in memory.

    SPLIT=2026-03-01 python scripts/experiment_saves_null_as_zero.py
"""
import os
import numpy as np
import pandas as pd
import psycopg2
import lightgbm as lgb
from scipy.stats import poisson

LEAGUES = ['EPL', 'SERIE_A', 'MLS', 'LA_LIGA']
FEATS = ['p_saves_r5', 'p_minutes_r5', 'shots_against_r5', 'corners_against_r5']
SPLIT = os.environ.get('SPLIT', '2026-03-01')
LINE = 3.5

conn = psycopg2.connect(os.environ['FUTBOL_DSN'])
conn.set_session(readonly=True)
df = pd.read_sql('''
SELECT pf.match_id, pf.player_id, pf.p_saves_r5, pf.p_minutes_r5, tf.shots_against_r5, tf.corners_against_r5,
       pms.saves, pms.goals_conceded, opp.shots_on_target AS opp_sot, m.kickoff_utc, l.code AS league
FROM futbol.player_match_features pf
JOIN futbol.matches m ON m.match_id = pf.match_id
JOIN futbol.players p ON p.player_id = pf.player_id
JOIN futbol.player_match_stats pms ON pms.match_id = pf.match_id AND pms.player_id = pf.player_id
JOIN futbol.team_match_features tf ON tf.match_id = pf.match_id AND tf.team_id = pf.team_id
JOIN futbol.seasons s ON s.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = s.league_id
LEFT JOIN futbol.team_match_stats opp ON opp.match_id = m.match_id AND opp.team_id <> pms.team_id
WHERE l.code = ANY(%(l)s) AND p.position = 'G' AND pms.minutes >= 45
''', conn, params={'l': LEAGUES})
conn.close()
for c in FEATS + ['saves', 'goals_conceded', 'opp_sot']:
    df[c] = pd.to_numeric(df[c], errors='coerce')
df['kickoff_utc'] = pd.to_datetime(df['kickoff_utc'], utc=True)

rule_zero = df['saves'].isna() & df['opp_sot'].notna() & df['goals_conceded'].notna() \
    & ((df['opp_sot'] - df['goals_conceded']) <= 1)
df['saves_clean'] = df['saves'].where(df['saves'].notna(), np.where(rule_zero, 0.0, np.nan))
df = df.dropna(subset=FEATS)

# --- rebuild p_saves_r5 with rule-zeros (same window as sql/features.sql: previous 5 appearances, any minutes)
allk = pd.read_sql('''
SELECT pms.match_id, pms.player_id, m.kickoff_utc, pms.minutes, pms.saves, pms.goals_conceded,
       opp.shots_on_target AS opp_sot
FROM futbol.player_match_stats pms
JOIN futbol.players p ON p.player_id = pms.player_id
JOIN futbol.matches m ON m.match_id = pms.match_id AND m.status = 'final'
JOIN futbol.seasons s ON s.season_id = m.season_id JOIN futbol.leagues l ON l.league_id = s.league_id
LEFT JOIN futbol.team_match_stats opp ON opp.match_id = m.match_id AND opp.team_id <> pms.team_id
WHERE p.position = 'G' AND l.code = ANY(%(l)s)
''', psycopg2.connect(os.environ['FUTBOL_DSN']), params={'l': LEAGUES})
for c in ['minutes', 'saves', 'goals_conceded', 'opp_sot']:
    allk[c] = pd.to_numeric(allk[c], errors='coerce')
az = allk['saves'].isna() & (allk['minutes'] >= 45) & allk['opp_sot'].notna() & allk['goals_conceded'].notna() \
    & ((allk['opp_sot'] - allk['goals_conceded']) <= 1)
allk['sc'] = allk['saves'].where(allk['saves'].notna(), np.where(az, 0.0, np.nan))
allk = allk.sort_values(['player_id', 'kickoff_utc'])
allk['p_saves_r5_clean'] = allk.groupby('player_id')['sc'].transform(
    lambda x: x.shift(1).rolling(5, min_periods=1).mean())
df = df.merge(allk[['match_id', 'player_id', 'p_saves_r5_clean']], on=['match_id', 'player_id'], how='left')
print('mean p_saves_r5 production:', round(df['p_saves_r5'].mean(), 3),
      '| rebuilt with zeros:', round(df['p_saves_r5_clean'].mean(), 3))

print('keeper rows with features:', len(df))
print('  saves present:', int(df['saves'].notna().sum()),
      '| NULL relabelled 0 by rule:', int(rule_zero.sum()),
      '| NULL left unknown:', int((df['saves'].isna() & ~rule_zero).sum()))

split = pd.Timestamp(SPLIT, tz='UTC')
train, test = df[df['kickoff_utc'] < split], df[df['kickoff_utc'] >= split]
test = test.dropna(subset=['saves_clean', 'p_saves_r5_clean'])
print(f'split {SPLIT}: train rows {len(train)}, test rows {len(test)} (labelled via saves_clean)')


def fit(rows, target, feats=None):
    feats = feats or FEATS
    rows = rows.dropna(subset=[target] + feats)
    m = lgb.LGBMRegressor(objective='poisson', n_estimators=300, learning_rate=0.03,
                          num_leaves=20, min_child_samples=25, verbose=-1)
    m.fit(rows[feats], rows[target])
    return m, len(rows)


FEATS2 = ['p_saves_r5_clean'] + FEATS[1:]
base, n_base = fit(train, 'saves')          # production: saves IS NOT NULL
cand, n_cand = fit(train, 'saves_clean')    # candidate A: label fix only
cand2, n_cand2 = fit(train, 'saves_clean', FEATS2)  # candidate B: label + feature fix
print('train n -> baseline', n_base, '| candidate', n_cand)

y = test['saves_clean'].to_numpy()
over = (y > LINE).astype(float)


def score(model, name, feats=None):
    mu = np.maximum(model.predict(test[feats or FEATS]), 0.1)
    dev = 2 * np.where(y > 0, y * np.log(y / mu), 0) - 2 * (y - mu)
    p = np.clip(1 - poisson.cdf(np.floor(LINE), mu), 1e-6, 1 - 1e-6)
    ll = -(over * np.log(p) + (1 - over) * np.log(1 - p))
    print(f'{name:9} mean pred saves {mu.mean():.3f} (actual {y.mean():.3f}) | '
          f'Poisson dev {dev.mean():.4f} | P(over {LINE}) mean {p.mean():.3f} (actual {over.mean():.3f}) | '
          f'logloss {ll.mean():.4f} | brier {((p - over) ** 2).mean():.4f}')
    return dev, ll


d0, l0 = score(base, 'baseline')
d1, l1 = score(cand, 'A label-only')
d2, l2 = score(cand2, 'B label+feat', FEATS2)
rng = np.random.default_rng(0)
idx = rng.integers(0, len(y), (2000, len(y)))
for name, a, b in (('Poisson dev A', d1, d0), ('logloss A', l1, l0),
                   ('Poisson dev B', d2, d0), ('logloss B', l2, l0)):
    diff = (a - b)
    boots = diff[idx].mean(axis=1)
    lo, hi = np.percentile(boots, 2.5), np.percentile(boots, 97.5)
    print(f'paired {name} diff (candidate - baseline): {diff.mean():+.4f}  '
          f'95% CI [{lo:+.4f}, {hi:+.4f}]  (negative = candidate better)')
print('test by league:', test.groupby('league').size().to_dict())
