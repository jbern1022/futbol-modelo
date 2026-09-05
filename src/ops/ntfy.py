"""
Shared ntfy posting helper for scripts/check_model_drift.py,
scripts/check_pipeline_health.py, and scripts/daily_digest.py.
Gracefully no-ops (prints, doesn't post) if NTFY_URL/NTFY_TOPIC aren't
set in the environment -- alerting is optional, never a hard
dependency for any of these scripts to run.
"""
import os

import requests

NTFY_URL = os.environ.get("NTFY_URL")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")


def post_to_ntfy(message: str, title: str, priority: str | None = None) -> None:
    if not NTFY_URL or not NTFY_TOPIC:
        print("(NTFY_URL/NTFY_TOPIC not set -- skipping notification, printed above only)")
        return
    headers = {"Title": title}
    if priority:
        headers["Priority"] = priority
    try:
        requests.post(f"{NTFY_URL.rstrip('/')}/{NTFY_TOPIC}", data=message.encode("utf-8"),
                      headers=headers, timeout=10)
        print("Posted to ntfy.")
    except Exception as e:
        print(f"ntfy POST failed (non-fatal): {e}")
