"""Pool-based round-robin selection of email providers."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

from .base import EmailProvider
from .moemail import MoEmailProvider
from .cloudmail import CloudMailProvider


SOFT_COOLDOWN_MINUTES = 5


def _construct_provider(row: sqlite3.Row) -> EmailProvider:
    config = json.loads(row["config_json"])
    typ = row["provider_type"]
    if typ == "moemail":
        return MoEmailProvider(url=config["url"], api_key=config["api_key"])
    if typ == "cloudmail":
        return CloudMailProvider(
            url=config["url"],
            email=config["email"],
            password=config["password"],
            domain=config.get("domain", ""),
            jwt_token=row["last_jwt_token"],
            jwt_acquired_at=row["last_jwt_at"],
        )
    raise ValueError(f"unknown provider_type: {typ}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cooldown_threshold_iso() -> str:
    return (
        datetime.now(timezone.utc) - timedelta(minutes=SOFT_COOLDOWN_MINUTES)
    ).isoformat()


def list_providers(db_path: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM email_providers ORDER BY id ASC"
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_provider(db_path: str, provider_id: int):
    """Return (provider_id, provider_instance) or (None, None)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM email_providers WHERE id = ?", (provider_id,))
        row = cur.fetchone()
        if not row:
            return None, None
        return row["id"], _construct_provider(row)
    finally:
        conn.close()


def pick_provider(db_path: str, *, manual_provider_id: int | None = None) -> tuple[int, EmailProvider]:
    """Round-robin select a provider.

    Returns (provider_id, provider_instance).
    Raises RuntimeError if no usable provider is configured.
    Manual selection ignores the soft-cooldown filter.
    """
    if manual_provider_id is not None:
        pid, provider = get_provider(db_path, manual_provider_id)
        if not provider:
            raise RuntimeError(f"Manual provider id {manual_provider_id} not found")
        return pid, provider

    cooldown_iso = _cooldown_threshold_iso()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # First try: exclude recently-errored providers
        cur = conn.execute(
            """SELECT * FROM email_providers
               WHERE last_error_at IS NULL OR last_error_at < ?
               ORDER BY last_used_at IS NOT NULL, last_used_at ASC, id ASC
               LIMIT 1""",
            (cooldown_iso,),
        )
        row = cur.fetchone()
        if not row:
            # All errored out recently; pick the least-recently-errored
            cur = conn.execute(
                """SELECT * FROM email_providers
                   ORDER BY last_used_at IS NOT NULL, last_used_at ASC, id ASC
                   LIMIT 1"""
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("No email providers configured")
        return row["id"], _construct_provider(row)
    finally:
        conn.close()


def record_provider_use(db_path: str, provider_id: int, error: str | None = None) -> None:
    """Update last_used_at and (if error) last_error / last_error_at."""
    now = _now_iso()
    conn = sqlite3.connect(db_path)
    try:
        if error:
            conn.execute(
                """UPDATE email_providers
                   SET last_used_at = ?, last_error = ?, last_error_at = ?, updated_at = ?
                   WHERE id = ?""",
                (now, error, now, now, provider_id),
            )
        else:
            conn.execute(
                """UPDATE email_providers
                   SET last_used_at = ?, updated_at = ?, last_error = NULL, last_error_at = NULL
                   WHERE id = ?""",
                (now, now, provider_id),
            )
        conn.commit()
    finally:
        conn.close()


def persist_provider_jwt(db_path: str, provider_id: int, jwt: str, when_iso: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """UPDATE email_providers
               SET last_jwt_token = ?, last_jwt_at = ?, updated_at = ?
               WHERE id = ?""",
            (jwt, when_iso, _now_iso(), provider_id),
        )
        conn.commit()
    finally:
        conn.close()
