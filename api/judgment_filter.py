"""
Petey's judgment-word filter, split out from api/main.py so it can be
unit-tested without importing main.py's module-level DB_POOL (which
opens a real Postgres connection at import time -- pulling in main.py
just to test a pure string function would require a live database).
Kept inside api/ rather than src/ deliberately: Dockerfile.api only
COPYs the api/ directory into the production image, so an import from
src/ would work locally but break the real container build.
"""
import re

UNSUPPORTED_JUDGMENT_WORDS = [
    "struggled", "struggling", "impressive", "poor", "weak", "strong",
    "moderate", "excellent", "great", "terrible", "solid", "decent",
    "underperformed", "outperformed", "dominant", "disappointing",
    "steady", "typical", "consistent", "normal", "stable",
    "high", "low", "good", "bad",
]

_JUDGMENT_WORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in UNSUPPORTED_JUDGMENT_WORDS) + r")\b",
    re.IGNORECASE,
)


def contains_unsupported_judgment(text: str) -> bool:
    # Word-boundary match, not plain substring -- a naive `word in text`
    # check false-positives on "low" inside "allowed" or "yellow" (a real
    # TEAM_STATS option), which would silently force every yellow-cards
    # or "allowed N goals" answer into the deterministic fallback instead
    # of Ollama's real phrasing, with no visible sign anything was wrong.
    return bool(_JUDGMENT_WORD_PATTERN.search(text))
