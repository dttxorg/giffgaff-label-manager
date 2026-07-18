"""桌面自动化注册下线后的回归测试。"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

import crud
import database
import main


def test_agent_routes_models_and_frontend_controls_are_removed():
    route_paths = {getattr(route, "path", "") for route in main.app.routes}
    assert not any(path.startswith("/api/agent") for path in route_paths)
    assert "/api/settings/agent-token" not in route_paths

    settings_fields = getattr(main.SystemSettings, "model_fields", None)
    if settings_fields is None:  # Pydantic v1
        settings_fields = main.SystemSettings.__fields__
    assert "agent_api_token" not in settings_fields
    assert "agent_api_token_source" not in settings_fields

    frontend = (PROJECT_DIR / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "Agent Token" not in frontend
    assert "/settings/agent-token" not in frontend
    assert main._normalize_activation_status("等待客户端领取") == "已分配激活码"


def test_startup_migrates_legacy_agent_state_and_deletes_saved_token():
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        original = (database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH)
        database.DATABASE_PATH = db_path
        crud.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        try:
            asyncio.run(database.init_db())
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """INSERT INTO customers
                       (email, activation_date, activation_status,
                        automation_lock_owner, automation_locked_at)
                       VALUES (?, ?, '等待客户端领取', 'desktop-1', '2026-07-18T00:00:00Z')""",
                    ("legacy@example.com", "2026-07-18"),
                )
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('agent_api_token', 'legacy-secret')"
                )
                conn.commit()

            asyncio.run(database.init_db())

            with sqlite3.connect(db_path) as conn:
                status, owner, locked_at = conn.execute(
                    """SELECT activation_status, automation_lock_owner, automation_locked_at
                       FROM customers WHERE email = 'legacy@example.com'"""
                ).fetchone()
                token = conn.execute(
                    "SELECT value FROM settings WHERE key = 'agent_api_token'"
                ).fetchone()

            assert status == "已分配激活码"
            assert owner is None
            assert locked_at is None
            assert token is None
        finally:
            database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH = original
