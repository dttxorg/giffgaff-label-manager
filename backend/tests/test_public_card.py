"""公开扫码页测试：
- 新建客户自动生成 public_token
- /p/{token} 返回 200 + 邮箱 + 复制按钮 + 安全头
- 错误 token → 404，不泄露其他客户
- 邮箱为空 → 404
- 公开页绕过后台口令鉴权
- Markdown 渲染：粗体、链接
- XSS 防护：script 与 javascript: 都被过滤
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
from models import CustomerCreate, CustomerUpdate


@pytest.fixture
def client():
    """独立的临时 DB；测试结束后还原原始路径。"""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        original = (database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH)
        database.DATABASE_PATH = db_path
        crud.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        asyncio.run(database.init_db())
        yield TestClient(main.app)
        database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH = original


def _create(email: str) -> int:
    return asyncio.run(crud.create_customer(CustomerCreate(
        email=email, activation_date="2026-07-11",
    )))


def test_create_customer_auto_generates_token(client):
    cid = _create("alice@giffgaff.example")
    detail = client.get(f"/api/customers/{cid}").json()
    token = detail["public_token"]
    assert token and len(token) >= 30
    # 再次创建另一个客户，token 必须不同
    cid2 = _create("bob@giffgaff.example")
    t2 = client.get(f"/api/customers/{cid2}").json()["public_token"]
    assert t2 != token


def test_public_page_renders_with_security_headers(client):
    cid = _create("alice@giffgaff.example")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/p/{token}")
    assert r.status_code == 200
    body = r.text
    assert "alice@giffgaff.example" in body
    assert "复制邮箱" in body
    # 安全头
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store, max-age=0"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'none'" in csp


def test_public_page_bogus_token_returns_404_no_leak(client):
    cid = _create("alice@giffgaff.example")
    r = client.get("/p/totally-bogus-token-value-xyz")
    assert r.status_code == 404
    assert "alice@giffgaff.example" not in r.text
    # 404 仍走同一模板（避免泄露 token 有效性）
    assert "运营尚未填写提示内容" in r.text or "暂未配置" in r.text


def test_public_page_oversized_token_returns_404(client):
    r = client.get("/p/" + "A" * 200)
    assert r.status_code == 404


def test_public_page_empty_email_returns_404(client):
    cid = _create("")  # 还没有邮箱
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/p/{token}")
    assert r.status_code == 404


def test_public_page_becomes_accessible_after_email_set(client):
    cid = _create("")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    assert client.get(f"/p/{token}").status_code == 404
    asyncio.run(crud.update_customer(cid, CustomerUpdate(email="late@giffgaff.example")))
    r = client.get(f"/p/{token}")
    assert r.status_code == 200
    assert "late@giffgaff.example" in r.text


def test_public_page_bypasses_app_password(client):
    cid = _create("alice@giffgaff.example")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    main.APP_PASSWORD = "super-secret-password"
    # 公开页不应触发 401
    r = client.get(f"/p/{token}")
    assert r.status_code == 200
    # 但其它 API 应该 401
    assert client.get("/api/customers").status_code == 401


def test_markdown_bold_and_link(client):
    cid = _create("alice@giffgaff.example")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    client.patch("/api/settings", json={
        "public_page_markdown": "请在 **Giffgaff App** 中使用 [官网](https://www.giffgaff.com) 注册。"
    })
    body = client.get(f"/p/{token}").text
    assert "<strong>Giffgaff App</strong>" in body
    assert 'href="https://www.giffgaff.com"' in body
    assert 'target="_blank"' in body
    assert 'rel="noopener noreferrer"' in body


def test_xss_in_markdown_is_escaped(client):
    cid = _create("alice@giffgaff.example")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    client.patch("/api/settings", json={
        "public_page_markdown": '<script>alert(1)</script>\n<img src=x onerror=alert(1)>\n**safe**'
    })
    body = client.get(f"/p/{token}").text
    # 关键安全保证：原始 <script> 标签不可执行
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    # 原始 <img> 标签不可执行（被实体化）
    assert "<img src=x onerror=alert(1)>" not in body
    assert "&lt;img" in body
    # 合法 Markdown 仍能渲染
    assert "<strong>safe</strong>" in body


def test_javascript_scheme_blocked(client):
    cid = _create("alice@giffgaff.example")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    client.patch("/api/settings", json={
        "public_page_markdown": "[click me](javascript:alert(1))"
    })
    body = client.get(f"/p/{token}").text
    assert "javascript:alert(1)" not in body
    # label 仍保留为纯文本
    assert "click me" in body


def test_markdown_heading_renders(client):
    cid = _create("alice@giffgaff.example")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    client.patch("/api/settings", json={"public_page_markdown": "## 标题\n\n正文"})
    body = client.get(f"/p/{token}").text
    assert "<h3>标题</h3>" in body
    assert "<p>正文</p>" in body


def test_settings_endpoint_round_trip(client):
    md = "## 标题\n\n正文 [link](https://example.com)"
    r = client.patch("/api/settings", json={"public_page_markdown": md})
    assert r.status_code == 200
    s = client.get("/api/settings").json()
    assert s["public_page_markdown"] == md


def test_list_customers_includes_public_token(client):
    _create("a@x.com")
    _create("b@x.com")
    lst = client.get("/api/customers").json()
    assert len(lst) == 2
    for c in lst:
        assert c["public_token"] is not None
        assert len(c["public_token"]) >= 30
    # 互不相同
    assert lst[0]["public_token"] != lst[1]["public_token"]


# ── 重新生成 / 版本号 / Worker 域名 / /api/public/{token}/version ──


def test_public_version_defaults_to_1(client):
    cid = _create("alice@x.com")
    d = client.get(f"/api/customers/{cid}").json()
    assert d["public_version"] == 1
    assert d["public_token"] is not None


def test_regenerate_public_link_rotates_token_and_bumps_version(client):
    cid = _create("alice@x.com")
    d1 = client.get(f"/api/customers/{cid}").json()
    token1 = d1["public_token"]
    v1 = d1["public_version"]

    r = client.post(f"/api/customers/{cid}/public-link/regenerate")
    assert r.status_code == 200
    body = r.json()
    assert body["public_token"] != token1
    assert body["public_version"] == v1 + 1

    # 客户详情已更新
    d2 = client.get(f"/api/customers/{cid}").json()
    assert d2["public_token"] == body["public_token"]
    assert d2["public_version"] == body["public_version"]


def test_regenerate_invalidates_old_token_immediately(client):
    cid = _create("alice@x.com")
    token1 = client.get(f"/api/customers/{cid}").json()["public_token"]
    # 旧 token 公开页 200
    assert client.get(f"/p/{token1}").status_code == 200
    # 重新生成
    client.post(f"/api/customers/{cid}/public-link/regenerate")
    # 旧 token 立即 404（包括 /version 和 /p）
    assert client.get(f"/api/public/{token1}/version").status_code == 404
    assert client.get(f"/p/{token1}").status_code == 404


def test_regenerate_nonexistent_customer_returns_404(client):
    r = client.post("/api/customers/999999/public-link/regenerate")
    assert r.status_code == 404


def test_public_token_version_endpoint(client):
    cid = _create("alice@x.com")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/api/public/{token}/version")
    assert r.status_code == 200
    assert r.json() == {"public_version": 1}


def test_public_token_version_after_regenerate(client):
    cid = _create("alice@x.com")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    client.post(f"/api/customers/{cid}/public-link/regenerate")
    r = client.get(f"/api/public/{token}/version")
    assert r.status_code == 404  # 旧 token 立即失效


def test_p_page_returns_x_cache_version_header(client):
    cid = _create("alice@x.com")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/p/{token}")
    assert r.headers.get("X-Cache-Version") == "1"
    # 重新生成后 v2
    client.post(f"/api/customers/{cid}/public-link/regenerate")
    new_token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/p/{new_token}")
    assert r.headers.get("X-Cache-Version") == "2"


def test_public_worker_domain_setting_round_trip(client):
    r = client.patch("/api/settings", json={"public_worker_domain": "https://card.example.com"})
    assert r.status_code == 200
    s = client.get("/api/settings").json()
    assert s["public_worker_domain"] == "https://card.example.com"


def test_public_worker_domain_rejects_bad_scheme(client):
    r = client.patch("/api/settings", json={"public_worker_domain": "ftp://x.com"})
    assert r.status_code == 400


def test_public_worker_domain_strips_trailing_slash(client):
    client.patch("/api/settings", json={"public_worker_domain": "https://card.example.com/"})
    s = client.get("/api/settings").json()
    assert s["public_worker_domain"] == "https://card.example.com"


def test_public_worker_domain_empty_clears(client):
    client.patch("/api/settings", json={"public_worker_domain": "https://card.example.com"})
    client.patch("/api/settings", json={"public_worker_domain": ""})
    s = client.get("/api/settings").json()
    assert s["public_worker_domain"] in (None, "")


def test_list_customers_includes_public_version(client):
    _create("a@x.com")
    _create("b@x.com")
    lst = client.get("/api/customers").json()
    assert all("public_version" in c for c in lst)
    assert all(c["public_version"] == 1 for c in lst)
