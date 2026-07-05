"""Pool-based round-robin selection of email providers."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

from .base import EmailProvider
from .moemail import MoEmailProvider
from .cloudmail import CloudMailProvider


log = logging.getLogger(__name__)


SOFT_COOLDOWN_MINUTES = 5


def _construct_provider(row: sqlite3.Row) -> EmailProvider | None:
    """Build an EmailProvider from a DB row.

    Returns None when the row's config_json is corrupt or incompatible so
    callers can skip and try the next pool candidate instead of 500-ing.
    """
    typ = row["provider_type"]
    raw_config = row["config_json"] or "{}"
    try:
        config = json.loads(raw_config) if raw_config else {}
    except (json.JSONDecodeError, TypeError) as exc:
        log.warning("email_providers row id=%s has invalid config_json: %s", row["id"], exc)
        return None
    try:
        if typ == "moemail":
            return MoEmailProvider(
                url=config["url"],
                api_key=config["api_key"],
                domains=_decode_domains(row),
                default_domain=_decode_default_domain(row),
            )
        if typ == "cloudmail":
            domain = (
                config.get("domain")
                or _decode_default_domain(row)
                or ""
            )
            if not domain:
                log.warning("cloudmail provider id=%s has no domain", row["id"])
                return None
            return CloudMailProvider(
                url=config["url"],
                email=config["email"],
                password=config["password"],
                domain=domain,
                jwt_token=row["last_jwt_token"],
                jwt_acquired_at=row["last_jwt_at"],
            )
    except (KeyError, TypeError) as exc:
        log.warning("email_providers row id=%s missing config field: %s", row["id"], exc)
        return None
    log.warning("email_providers row id=%s has unknown provider_type=%s", row["id"], typ)
    return None


def _decode_domains(row) -> list[str]:
    raw = row["domains_json"]
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    return [str(d) for d in items if d]


def _decode_default_domain(row) -> str | None:
    value = (row["default_domain"] or "").strip()
    return value or None


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


def _candidate_pool(conn: sqlite3.Connection, cooldown_iso: str):
    """Iterate providers in round-robin order, skipping bad rows.

    Yields (provider_id, provider) tuples for rows whose config can be
    constructed. Manual selection steps out of cooldown altogether.
    """
    cur = conn.execute(
        """SELECT * FROM email_providers
           WHERE last_error_at IS NULL OR last_error_at < ?
           ORDER BY last_used_at IS NOT NULL, last_used_at ASC, id ASC""",
        (cooldown_iso,),
    )
    for row in cur.fetchall():
        provider = _construct_provider(row)
        if provider is not None:
            yield row["id"], provider


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
        first = next(_candidate_pool(conn, cooldown_iso), None)
        if first is not None:
            return first
        # All errored out recently; pick the least-recently-errored, ignoring cooldown
        cur = conn.execute(
            """SELECT * FROM email_providers
               ORDER BY last_used_at IS NOT NULL, last_used_at ASC, id ASC"""
        )
        for row in cur.fetchall():
            provider = _construct_provider(row)
            if provider is not None:
                return row["id"], provider
        raise RuntimeError("No email providers configured")
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
