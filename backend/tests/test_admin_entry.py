"""隐藏管理入口回归测试。

公开二维码路由不经过入口门禁；浏览器管理页面/API 必须先通过随机入口，
之后仍需原有 APP_PASSWORD 登录。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import crud
import database
import main


SECRET_PATH = "/entry_7LzQ0vF4mN9kR2xC8pT6wY3sH1jB5dGa"
PUBLIC_TOKEN = "public-token-12345678901234567890"


@pytest.fixture
def hidden_admin_client():
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        original = {
            "database_path": database.DATABASE_PATH,
            "crud_path": crud.DATABASE_PATH,
            "main_path": main.DATABASE_PATH,
            "app_password": main.APP_PASSWORD,
            "agent_token": main.AGENT_API_TOKEN,
            "admin_entry_path": main.ADMIN_ENTRY_PATH,
        }
        database.DATABASE_PATH = db_path
        crud.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        main.APP_PASSWORD = "test-password-that-remains-required"
        main.AGENT_API_TOKEN = ""
        main.ADMIN_ENTRY_PATH = SECRET_PATH
        asyncio.run(database.init_db())

        async def _seed_public_customer():
            import aiosqlite
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    """INSERT INTO customers (email, activation_date, public_token)
                       VALUES (?, ?, ?)""",
                    ("public@example.com", "2026-07-15", PUBLIC_TOKEN),
                )
                await db.commit()

        asyncio.run(_seed_public_customer())
        client = TestClient(main.app, base_url="https://testserver")
        try:
            yield client
        finally:
            client.close()
            database.DATABASE_PATH = original["database_path"]
            crud.DATABASE_PATH = original["crud_path"]
            main.DATABASE_PATH = original["main_path"]
            main.APP_PASSWORD = original["app_password"]
            main.AGENT_API_TOKEN = original["agent_token"]
            main.ADMIN_ENTRY_PATH = original["admin_entry_path"]


@pytest.mark.parametrize("path", [
    "/",
    "/index.html",
    "/worker_setup.js",
    "/api/customers",
    "/api/auth/status",
])
def test_management_surfaces_are_uniform_404_without_entry_cookie(hidden_admin_client, path):
    response = hidden_admin_client.get(path)

    assert response.status_code == 404
    assert response.text == "Not found"
    assert "giffgaff" not in response.text.lower()
    assert "登录" not in response.text
    assert response.headers["Cache-Control"] == "no-store, max-age=0"


def test_password_login_endpoint_is_also_hidden_without_entry_cookie(hidden_admin_client):
    response = hidden_admin_client.post(
        "/api/auth/login",
        json={"password": "test-password-that-remains-required"},
    )

    assert response.status_code == 404
    assert response.text == "Not found"


def test_secret_entry_sets_secure_signed_cookie_then_shows_password_login(hidden_admin_client):
    entry = hidden_admin_client.get(SECRET_PATH, follow_redirects=False)

    assert entry.status_code == 302
    assert entry.headers["location"] == "/index.html"
    set_cookie = entry.headers["set-cookie"]
    assert main.ADMIN_ENTRY_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie
    cookie_value = hidden_admin_client.cookies.get(main.ADMIN_ENTRY_COOKIE_NAME)
    assert cookie_value not in (None, "", "true")
    assert "." in cookie_value

    page = hidden_admin_client.get("/index.html")
    assert page.status_code == 200
    assert "访问口令" in page.text

    # 隐藏入口只解除 404 门禁，不替代原有密码认证。
    before_login = hidden_admin_client.get("/api/customers")
    assert before_login.status_code == 401
    login = hidden_admin_client.post(
        "/api/auth/login",
        json={"password": "test-password-that-remains-required"},
    )
    assert login.status_code == 200
    assert hidden_admin_client.get("/api/customers").status_code == 200


def test_public_qr_routes_work_without_admin_entry_cookie(hidden_admin_client):
    version = hidden_admin_client.get(f"/api/public/{PUBLIC_TOKEN}/version")
    page = hidden_admin_client.get(f"/p/{PUBLIC_TOKEN}")

    assert version.status_code == 200
    assert version.json() == {"public_version": 1}
    assert page.status_code == 200
    assert "public@example.com" in page.text


@pytest.mark.parametrize("forged", [
    "true",
    "forged-payload.invalid-signature",
    "A" * 43 + "." + "0" * 64,
])
def test_forged_admin_entry_cookie_is_rejected(hidden_admin_client, forged):
    response = hidden_admin_client.get(
        "/index.html",
        headers={"Cookie": f"{main.ADMIN_ENTRY_COOKIE_NAME}={forged}"},
    )

    assert response.status_code == 404
    assert response.text == "Not found"


def test_tampering_with_a_real_cookie_invalidates_it(hidden_admin_client):
    hidden_admin_client.get(SECRET_PATH, follow_redirects=False)
    real_cookie = hidden_admin_client.cookies.get(main.ADMIN_ENTRY_COOKIE_NAME)
    replacement = "0" if real_cookie[-1] != "0" else "1"
    tampered = real_cookie[:-1] + replacement

    # 显式 Cookie header 覆盖 cookie jar，验证真实签名被改一位后也不能通过。
    hidden_admin_client.cookies.clear()
    response = hidden_admin_client.get(
        "/index.html",
        headers={"Cookie": f"{main.ADMIN_ENTRY_COOKIE_NAME}={tampered}"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize("weak_path", [
    "/admin",
    "/secret",
    "/too/short",
    "missing-leading-slash-12345678901234567890",
])
def test_weak_or_malformed_admin_entry_paths_are_rejected(weak_path):
    original = main.ADMIN_ENTRY_PATH
    main.ADMIN_ENTRY_PATH = weak_path
    try:
        with pytest.raises(ValueError):
            main._validated_admin_entry_path()
    finally:
        main.ADMIN_ENTRY_PATH = original
