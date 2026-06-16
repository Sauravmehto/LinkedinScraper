"""Disk cache for Apollo async phone reveal jobs."""

from __future__ import annotations

import json
import time
from pathlib import Path

from gtm.linkedin_scraper.io_utils import OUTPUT_DIR

CACHE_DIR = OUTPUT_DIR / "cache" / "apollo_phones"
PENDING_PATH = CACHE_DIR / "pending.json"
RESULTS_DIR = CACHE_DIR / "results"


def _ensure_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_pending() -> dict[str, dict]:
    _ensure_dirs()
    if not PENDING_PATH.exists():
        return {}
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_pending(pending: dict[str, dict]) -> None:
    _ensure_dirs()
    PENDING_PATH.write_text(json.dumps(pending, indent=2), encoding="utf-8")


def save_result(request_id: str, payload: dict) -> None:
    _ensure_dirs()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(request_id))
    path = RESULTS_DIR / f"{safe}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_result(request_id: str) -> dict | None:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(request_id))
    path = RESULTS_DIR / f"{safe}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def record_job(
    *,
    linkedin_key: str,
    request_id: str,
    work_email: str,
    person_name: str,
    status: str = "pending",
) -> None:
    pending = load_pending()
    pending[linkedin_key] = {
        "request_id": request_id,
        "work_email": work_email,
        "person_name": person_name,
        "status": status,
        "submitted_at": time.time(),
    }
    save_pending(pending)


def update_job_status(linkedin_key: str, status: str) -> None:
    pending = load_pending()
    if linkedin_key in pending:
        pending[linkedin_key]["status"] = status
        pending[linkedin_key]["updated_at"] = time.time()
        save_pending(pending)
