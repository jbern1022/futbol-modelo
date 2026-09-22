# dixon-coles

A small, dependency-light implementation of the Dixon-Coles model
(Dixon & Coles, 1997) for predicting football/soccer match outcomes:
a time-decayed bivariate Poisson model with a low-score dependency
correction, fit per competition from historical results.

Extracted from [futbol-modelo](https://github.com/jbern1022/futbol-modelo),
where it's the core match model behind live predictions for
EPL/Serie A/La Liga/MLS and the World Cup.

## Install

```bash
pip install ./packages/dixon-coles       # or wherever this directory lives
pip install -e ./packages/dixon-coles    # editable, for local development
```

## Usage

```python
import pandas as pd
from dixon_coles import DixonColes, derive_markets, knockout_extension

# One row per historical match. Column names are fixed.
matches = pd.DataFrame({
    "date": [...],       # datetime
    "home": [...],       # team name (str)
    "away": [...],       # team name (str)
    "hg":   [...],       # home goals (int)
    "ag":   [...],       # away goals (int)
})

model = DixonColes(xi=0.0018)   # xi: time decay per day (~0.0018 halves weight in ~13 months)
model.fit(matches)

probs = model.predict("Inter", "Napoli")   # {"matrix": <11x11 scoreline grid>, "home": ..., "away": ...}
markets = derive_markets(probs)
# {"home_win": 0.42, "draw": 0.27, "away_win": 0.31, "btts_yes": 0.51,
#  "home_clean_sheet": 0.29, "away_clean_sheet": 0.22,
#  "over_0.5": 0.87, "over_1.5": 0.64, "over_2.5": 0.41, ...,
#  "top_scorelines": [((1, 1), 0.12), ((1, 0), 0.10), ...]}

# Knockout fixture (no draw allowed): extends 90' probabilities with
# extra time + penalties.
knockout_extension(markets)
# {"advance_home": 0.58, "advance_away": 0.42}
```

### Small-sample fitting

For a small or sparse dataset (an in-progress international tournament,
say), the model can be underdetermined. Pass `reg > 0` (try 5-15) to
`fit()` for L2 (ridge) shrinkage of the attack/defence parameters
toward the average team:

```python
model.fit(matches, reg=10)
```

## What it does and doesn't model

- Outputs a full scoreline probability grid (0-10 goals each side),
  from which every match-level market derives: 1X2, total goals O/U,
  BTTS, clean sheets, exact scorelines.
- Home advantage and a low-score dependency correction (the original
  paper's `tau` adjustment for 0-0/1-0/0-1/1-1, since a plain
  independent-Poisson model systematically misprices those) are both
  fit directly from the data, not fixed constants.
- No player-level or in-play modeling — team-level, pre-match only.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
