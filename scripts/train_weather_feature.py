"""
Weather as a model feature -- honest evaluation of whether it actually
sharpens the corners props model, the market most plausibly weather-
sensitive per the original ticket (wind affects delivery/long shots,
rain affects ball control -- both plausible corners drivers).

    python scripts/train_weather_feature.py

SCOPE, read before trusting any result from this script: pilot on MLS
only, and only the 29 (of 30) teams team_venues actually has city-level
coordinates for (see scripts/backfill_team_venues.py -- San Diego is
missing venue data at the source, API-Football itself, not fabricated
here). Historical weather from Open-Meteo's free archive API (no key
required), city-level precision, matched to each match's HOME venue at
the kickoff hour (rounded to the nearest hour) -- not a domed-stadium
flag, so this is a genuine limitation: several MLS venues are covered
or partially covered, and this script does not know which. Any
positive result here should be read as "weather-as-measured-outdoors
correlates with corners," not proof for domed venues specifically.

Compares the exact same corners feature set generate_slate.py's live
fit_props_model() uses, with weather features added, against a held-out
season -- same discipline as every other honest-evaluation script
written today.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pandas as pd
import psycopg2
import requests
from sklearn.metrics import mean_absolute_error

lgb: Any
try:
    import lightgbm as lgb
except ImportError:
    lgb = None

DSN = os.environ.get("FUTBOL_DSN", "host=futbol-db dbname=futbol user=futbol")
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

Q = """
SELECT f.match_id, f.team_id, m.home_team_id, m.kickoff_utc, se.label AS season,
       f.corners_for_r5, f.corners_against_r5, f.shots_for_r5, f.shots_against_r5,
       f.xg_for_r5, f.xg_against_r5, f.rest_days, f.is_home,
       tms.corners AS corners_actual
FROM futbol.team_match_features f
JOIN futbol.matches m ON m.match_id = f.match_id
JOIN futbol.seasons se ON se.season_id = m.season_id
JOIN futbol.leagues l ON l.league_id = se.league_id
JOIN futbol.team_match_stats tms ON tms.match_id = f.match_id AND tms.team_id = f.team_id
WHERE l.code = 'MLS' AND tms.corners IS NOT NULL AND f.n_prior >= 5
ORDER BY m.kickoff_utc;
"""

# generate_slate.py's live fit_props_model() uses this same set PLUS
# xg_for_r5/xg_against_r5 -- dropped here after checking directly:
# those two are 100% null for MLS specifically (Understat, the only xg
# source, doesn't cover MLS at all), so for an MLS-only comparison they
# contribute nothing but rows lost to dropna. Worth knowing on its own:
# the live MLS corners model has been training with 2 permanently-dead
# features this whole time -- LightGBM's native missing-value handling
# just silently no-ops them rather than erroring, so nothing broke, but
# they're not doing anything either.
BASE_FEATURES = ["corners_for_r5", "corners_against_r5", "shots_for_r5",
                  "shots_against_r5", "rest_days", "is_home"]
WEATHER_FEATURES = ["temp_c", "precip_mm", "wind_kmh"]
HOLDOUT_SEASON = "2025"


WEATHER_CACHE = "/tmp/futbol_weather_cache.parquet"


def fetch_venue_weather(conn) -> pd.DataFrame:
    if os.path.exists(WEATHER_CACHE):
        print(f"Loading cached weather from {WEATHER_CACHE}")
        return pd.read_parquet(WEATHER_CACHE)

    venues = pd.read_sql(
        "SELECT team_id, latitude, longitude FROM futbol.team_venues", conn)
    frames = []
    for i, v in venues.iterrows():
        for attempt in range(5):
            try:
                resp = requests.get(OPEN_METEO_ARCHIVE, params={
                    "latitude": v["latitude"], "longitude": v["longitude"],
                    "start_date": "2021-04-01", "end_date": "2026-09-10",
                    "hourly": "temperature_2m,precipitation,wind_speed_10m",
                    "timezone": "UTC",
                }, timeout=90)
                if resp.status_code == 429:
                    wait = 10 * (attempt + 1)
                    print(f"  rate-limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                print(f"  retry {attempt + 1}/5 for team_id={int(v['team_id'])}: {e}")
                time.sleep(5)
        else:
            raise SystemExit(f"failed to fetch weather for team_id={int(v['team_id'])}")
        print(f"  [{i + 1}/{len(venues)}] fetched team_id={int(v['team_id'])}")
        time.sleep(2)  # stay well under the free API's rate limit
        hourly = resp.json()["hourly"]
        df = pd.DataFrame({
            "kickoff_hour": pd.to_datetime(hourly["time"], utc=True),
            "temp_c": hourly["temperature_2m"],
            "precip_mm": hourly["precipitation"],
            "wind_kmh": hourly["wind_speed_10m"],
        })
        df["home_team_id"] = int(v["team_id"])
        frames.append(df)
    result = pd.concat(frames, ignore_index=True)
    result.to_parquet(WEATHER_CACHE)
    print(f"Cached weather to {WEATHER_CACHE}")
    return result


def main():
    if lgb is None:
        raise SystemExit("lightgbm not installed")

    conn = psycopg2.connect(DSN)
    df = pd.read_sql(Q, conn, params=())
    print(f"Fetching historical weather for {pd.read_sql('SELECT count(*) FROM futbol.team_venues', conn).iloc[0, 0]} venues...")
    weather = fetch_venue_weather(conn)
    conn.close()

    df["is_home"] = df["is_home"].astype(int)
    df["home_team_id"] = df["home_team_id"].astype(int)
    df["kickoff_hour"] = pd.to_datetime(df["kickoff_utc"], utc=True).dt.floor("h")
    df = df.merge(weather, on=["home_team_id", "kickoff_hour"], how="left")

    n_before = len(df)
    df = df.dropna(subset=BASE_FEATURES + WEATHER_FEATURES + ["corners_actual"])
    print(f"{len(df)}/{n_before} rows have both complete base features and weather "
          f"(rest dropped: outside the 29-venue coverage, or too recent for the "
          f"archive API's few-day delay)\n")

    train = df[df.season != HOLDOUT_SEASON]
    test = df[df.season == HOLDOUT_SEASON]
    print(f"Train: {len(train)} rows | Test: {len(test)} rows (held-out season {HOLDOUT_SEASON})\n")

    def fit_and_eval(features: list[str], label: str) -> float:
        model = lgb.LGBMRegressor(
            objective="poisson", n_estimators=300, learning_rate=0.03,
            num_leaves=20, min_child_samples=30, subsample=0.8,
            colsample_bytree=0.8, verbose=-1)
        model.fit(train[features], train["corners_actual"])
        pred = np.clip(model.predict(test[features]), 0.05, None)
        mae = mean_absolute_error(test["corners_actual"], pred)
        print(f"{label}: MAE {mae:.3f}")
        return mae, model

    print("--- Held-out season evaluation (MLS corners, MAE lower=better) ---\n")
    base_mae, _ = fit_and_eval(BASE_FEATURES, "Without weather")
    weather_mae, weather_model = fit_and_eval(BASE_FEATURES + WEATHER_FEATURES, "With weather   ")

    improvement_pct = (base_mae - weather_mae) / base_mae * 100
    verdict = "IMPROVES" if weather_mae < base_mae else "does NOT improve"
    print(f"\n-> Weather {verdict} corners predictions ({improvement_pct:+.1f}% MAE)\n")

    print("--- Feature importance (with-weather model) ---\n")
    for feat, imp in sorted(
            zip(BASE_FEATURES + WEATHER_FEATURES, weather_model.feature_importances_),
            key=lambda x: -x[1]):
        print(f"  {feat:20s} {imp}")


if __name__ == "__main__":
    main()
