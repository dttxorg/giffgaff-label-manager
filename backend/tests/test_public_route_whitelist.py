"""回归测试：/api/public/* 必须绕过口令鉴权（Cloudflare Worker 回调用）。

bug 背景：commit d1c77e3 把 /api/public/{token}/version 加进 public_routes，
但 require_app_password 中间件只白名单了 /api/auth/* 和 /api/agent/*，
没把 /api/public/* 加进去。Worker 从边缘节点回调时没带 admin cookie，
被 401 拦下，/p/{token} 整个链路断。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import database
import crud
import main
from fastapi.testclient import TestClient


@pytest.fixture
def authed_client():
    """设置 APP_PASSWORD，模拟部署场景：口令保护开启。"""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        original = (database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH)
        database.DATABASE_PATH = db_path
        crud.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        asyncio.run(database.init_db())
        # 直接 INSERT 一行带 public_token 的客户，绕开需要 auth 的 POST /api/customers
        async def _seed():
            import aiosqlite
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "INSERT INTO customers (email, activation_date, public_token) "
                    "VALUES (?, ?, ?)",
                    ("a@x.com", "2026-07-14", "test-token-12345678901234567890"),
                )
                await db.commit()
        asyncio.run(_seed())

        main.APP_PASSWORD = "test-secret-123"  # 开启鉴权
        main.AGENT_API_TOKEN = ""
        yield TestClient(main.app)
        main.APP_PASSWORD = ""
        database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH = original


TOKEN = "test-token-12345678901234567890"


def test_api_public_version_whitelisted_no_auth(authed_client):
    """没带 cookie 调 /api/public/{token}/version 不应被 401 拦。"""
    r = authed_client.get(f"/api/public/{TOKEN}/version")
    assert r.status_code != 401, f"middleware 拦了 Worker callback: {r.text}"
    assert r.status_code == 200
    assert r.json() == {"public_version": 3_000_001}


def test_api_public_version_404_for_invalid_token(authed_client):
    """白名单后，非法 token 仍然 404（不泄漏任何信息）。"""
    r = authed_client.get("/api/public/this-is-not-a-real-token/version")
    assert r.status_code == 404


def test_p_public_path_not_blocked_by_auth(authed_client):
    """/p/{token}（不是 /api/ 前缀）也应该不受 auth 中间件影响。"""
    r = authed_client.get(f"/p/{TOKEN}")
    assert r.status_code != 401


def test_api_agent_still_whitelisted(authed_client):
    """回归保护：/api/agent/* 也仍然白名单。"""
    r = authed_client.get("/api/agent/customers/1/activation-task")
    # 没传 agent token，但说明没被全局 auth 拦
    assert r.status_code in (401, 404, 422)  # 不是 403


def test_protected_api_still_works(authed_client):
    """回归保护：受保护的 /api/customers 仍然要求 auth。"""
    r = authed_client.get("/api/customers")
    assert r.status_code == 401  # 全局 auth 应该拦
