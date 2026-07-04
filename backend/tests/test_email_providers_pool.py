import asyncio
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

BACKEND = "/Volumes/外置硬盘/claude code/giffgaff-reminder/backend"
sys.path.insert(0, BACKEND)

import database
from email_providers.pool import (
    pick_provider,
    record_provider_use,
    persist_provider_jwt,
    list_providers,
)


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as td:
        path = f"{td}/test.db"
        asyncio.run(_init_db(path))
        yield path


async def _init_db(path):
    database.DATABASE_PATH = path
    await database.init_db()


import json

def _make_provider_row(name, last_used_at=None, last_error=None, last_error_at=None,
                        provider_type="moemail", config_json=None):
    if config_json is None:
        config_json = json.dumps({"url": "https://test", "api_key": "k"} if provider_type == "moemail"
                                 else {"url": "https://test", "email": "a@b", "password": "p", "domain": "b"})
    conn = sqlite3.connect(database.DATABASE_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO email_providers
               (name, provider_type, config_json, last_used_at, last_error,
                last_error_at, last_jwt_token, last_jwt_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)""",
            (name, provider_type, config_json, last_used_at, last_error,
             last_error_at, datetime.now(timezone.utc).isoformat(),
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_pick_provider_returns_never_used_first(db_path):
    """Provider with NULL last_used_at sorts first."""
    _make_provider_row("a", last_used_at="2026-07-04T00:00:00")
    pid_b = _make_provider_row("b", last_used_at=None)
    pid, _ = pick_provider(db_path)
    assert pid == pid_b


def test_pick_provider_returns_oldest_used(db_path):
    """Provider with oldest last_used_at sorts next."""
    pid_a = _make_provider_row("a", last_used_at="2026-07-04T00:00:00")
    pid_b = _make_provider_row("b", last_used_at="2026-07-01T00:00:00")
    pid_c = _make_provider_row("c", last_used_at="2026-07-02T00:00:00")
    pid, _ = pick_provider(db_path)
    assert pid == pid_b


def test_pick_provider_skips_recent_errors(db_path):
    """Provider with last_error_at within 5 min is skipped."""
    recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    pid_recent = _make_provider_row("recent_err", last_error_at=recent_iso,
                                      last_used_at="2026-07-01T00:00:00")
    pid_old = _make_provider_row("old_err", last_error_at="2024-01-01T00:00:00",
                                  last_used_at="2026-07-02T00:00:00")
    pid, _ = pick_provider(db_path)
    assert pid == pid_old


def test_pick_provider_manual_override(db_path):
    """manual_provider_id wins regardless of last_used_at."""
    pid_a = _make_provider_row("a", last_used_at=None)
    pid_b = _make_provider_row("b", last_used_at="2026-07-04T00:00:00")
    pid, _ = pick_provider(db_path, manual_provider_id=pid_b)
    assert pid == pid_b


def test_pick_provider_manual_override_ignores_cooldown(db_path):
    """Manual selection even when in cooldown."""
    recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    pid_a = _make_provider_row("a", last_error_at=recent_iso,
                              last_used_at="2026-07-04T00:00:00")
    pid, _ = pick_provider(db_path, manual_provider_id=pid_a)
    assert pid == pid_a


def test_pick_provider_raises_when_none_available(db_path):
    with pytest.raises(RuntimeError):
        pick_provider(db_path)


def test_pick_provider_falls_back_when_all_recent_errors(db_path):
    """If all providers errored in the last 5 min, fall back to the oldest-used."""
    recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    pid_a = _make_provider_row("a", last_error_at=recent_iso,
                              last_used_at="2026-07-04T00:00:00")
    pid_b = _make_provider_row("b", last_error_at=recent_iso,
                              last_used_at="2026-07-01T00:00:00")
    pid, _ = pick_provider(db_path)
    # Should still pick one (fall-back to oldest)
    assert pid in (pid_a, pid_b)


def test_record_provider_use_updates_last_used_at(db_path):
    pid = _make_provider_row("a")
    record_provider_use(db_path, pid)
    providers = list_providers(db_path)
    assert providers[0]["last_used_at"] is not None


def test_record_provider_use_with_error(db_path):
    pid = _make_provider_row("a")
    record_provider_use(db_path, pid, error="network down")
    providers = list_providers(db_path)
    assert providers[0]["last_error"] == "network down"
    assert providers[0]["last_error_at"] is not None


def test_persist_provider_jwt(db_path):
    pid = _make_provider_row("a", provider_type="cloudmail")
    when = "2026-07-04T10:00:00+00:00"
    persist_provider_jwt(db_path, pid, "saved-jwt", when)
    providers = list_providers(db_path)
    assert providers[0]["last_jwt_token"] == "saved-jwt"
    assert providers[0]["last_jwt_at"] == when


def test_list_providers_returns_all(db_path):
    _make_provider_row("a")
    _make_provider_row("b")
    _make_provider_row("c")
    providers = list_providers(db_path)
    assert len(providers) == 3
