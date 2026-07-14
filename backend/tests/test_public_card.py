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


# ── 支付信息持久化（save_payment_check_result）──


def test_payment_fields_default_to_none(client):
    cid = _create("a@x.com")
    d = client.get(f"/api/customers/{cid}").json()
    assert d["payment_changed_at"] is None
    assert d["payment_updated_at"] is None
    assert d["payment_last_checked_at"] is None


def test_list_customers_includes_payment_fields(client):
    _create("a@x.com")
    lst = client.get("/api/customers").json()
    assert all("payment_changed_at" in c for c in lst)
    assert all("payment_updated_at" in c for c in lst)
    assert all("payment_last_checked_at" in c for c in lst)


def test_save_payment_check_result_persists(client):
    """直接调用 crud.save_payment_check_result 验证持久化（无需真 MoEmail）。"""
    import crud
    cid = _create("a@x.com")
    ok = asyncio.run(crud.save_payment_check_result(
        customer_id=cid,
        changed_at="2026-07-13T10:30:00+00:00",
        updated_at=None,
        checked_at="2026-07-14T08:00:00+00:00",
    ))
    assert ok
    d = client.get(f"/api/customers/{cid}").json()
    assert d["payment_changed_at"] == "2026-07-13T10:30:00+00:00"
    assert d["payment_updated_at"] is None
    assert d["payment_last_checked_at"] == "2026-07-14T08:00:00+00:00"


def test_save_payment_check_result_only_updated(client):
    """只查到 updated 邮件（信用卡更新过、未解除）的状态。"""
    import crud
    cid = _create("a@x.com")
    asyncio.run(crud.save_payment_check_result(
        customer_id=cid,
        changed_at=None,
        updated_at="2026-07-12T08:00:00+00:00",
        checked_at="2026-07-14T08:00:00+00:00",
    ))
    d = client.get(f"/api/customers/{cid}").json()
    assert d["payment_changed_at"] is None
    assert d["payment_updated_at"] == "2026-07-12T08:00:00+00:00"
    assert d["payment_last_checked_at"] == "2026-07-14T08:00:00+00:00"


def test_save_payment_check_result_empty_inbox(client):
    """什么都没查到时，也应写入 last_checked_at，以便首页区分「未查过」和「查过无结果」。"""
    import crud
    cid = _create("a@x.com")
    asyncio.run(crud.save_payment_check_result(
        customer_id=cid,
        changed_at=None,
        updated_at=None,
        checked_at="2026-07-14T08:00:00+00:00",
    ))
    d = client.get(f"/api/customers/{cid}").json()
    assert d["payment_changed_at"] is None
    assert d["payment_updated_at"] is None
    assert d["payment_last_checked_at"] == "2026-07-14T08:00:00+00:00"


def test_save_payment_check_result_overwrites_previous(client):
    """再次查询会覆盖之前的结果（用最新邮件的时间戳）。"""
    import crud
    cid = _create("a@x.com")
    asyncio.run(crud.save_payment_check_result(
        cid, "2026-07-01T00:00:00+00:00", None, "2026-07-10T00:00:00+00:00"
    ))
    asyncio.run(crud.save_payment_check_result(
        cid, "2026-07-13T10:30:00+00:00", None, "2026-07-14T09:00:00+00:00"
    ))
    d = client.get(f"/api/customers/{cid}").json()
    assert d["payment_changed_at"] == "2026-07-13T10:30:00+00:00"
    assert d["payment_last_checked_at"] == "2026-07-14T09:00:00+00:00"


def test_save_payment_check_result_nonexistent_returns_false(client):
    import crud
    ok = asyncio.run(crud.save_payment_check_result(99999, None, None, "x"))
    assert ok is False


# ── UK 随机身份（姓名 / 地址 / 邮编）──


def test_uk_random_module_generates_valid_data():
    """uk_random 模块的每个生成函数都返回非空字符串。"""
    from uk_random import (
        generate_first_name, generate_last_name, generate_address,
        generate_postcode, generate_random_identity,
    )
    assert isinstance(generate_first_name(), str) and len(generate_first_name()) > 0
    assert isinstance(generate_last_name(), str) and len(generate_last_name()) > 0
    assert isinstance(generate_address(), str) and len(generate_address()) > 0
    # UK postcode: 字母数字 + 空格 + 字母数字字母
    pc = generate_postcode()
    import re
    assert re.match(r"^[A-Z]{1,2}\d{1,2} [A-Z]\d[A-Z]{2}$", pc), f"bad postcode: {pc!r}"
    # 全套生成
    identity = generate_random_identity()
    assert set(identity.keys()) == {"first_name", "last_name", "address", "city", "postcode"}


def test_customer_creation_auto_fills_identity(client):
    """新建客户时自动填充 first_name / last_name / address / city / postcode。"""
    body = {"email": "a@x.com", "activation_date": "2026-07-14", "use_sim_code": False}
    r = client.post("/api/customers", json=body)
    assert r.status_code == 201
    cid = r.json()["customer_id"]

    d = client.get(f"/api/customers/{cid}").json()
    # regen_identity was called, so all 5 fields should be filled
    for field in ("first_name", "last_name", "address", "city", "postcode"):
        assert d.get(field), f"{field} should be auto-filled, got {d[field]!r}"


def test_list_customers_includes_identity_fields(client):
    _create("a@x.com")
    lst = client.get("/api/customers").json()
    assert all("first_name" in c for c in lst)
    assert all("last_name" in c for c in lst)
    assert all("address" in c for c in lst)
    assert all("city" in c for c in lst)
    assert all("postcode" in c for c in lst)


def test_regenerate_identity_changes_values(client):
    """POST /identity/regenerate 后 5 个字段都更新。"""
    cid = _create("a@x.com")
    d1 = client.get(f"/api/customers/{cid}").json()
    # Run regenerate a few times and verify at least one field changes (statistical)
    changed_any = False
    for _ in range(5):
        r = client.post(f"/api/customers/{cid}/identity/regenerate")
        assert r.status_code == 200
        d2 = client.get(f"/api/customers/{cid}").json()
        if d2["address"] != d1["address"] or d2["city"] != d1["city"] or d2["postcode"] != d1["postcode"]:
            changed_any = True
            break
        d1 = d2
    assert changed_any, "regenerate should sometimes produce different values"


def test_regenerate_identity_nonexistent_returns_404(client):
    r = client.post("/api/customers/99999/identity/regenerate")
    assert r.status_code == 404


def test_customer_update_accepts_identity_fields(client):
    """PATCH 可更新 5 个身份字段（运营手动编辑）。"""
    cid = _create("a@x.com")
    r = client.patch(f"/api/customers/{cid}", json={
        "first_name": "Alice",
        "last_name": "Smith",
        "address": "10 Downing Street",
        "city": "London",
        "postcode": "SW1A 2AA",
    })
    assert r.status_code == 200
    d = client.get(f"/api/customers/{cid}").json()
    assert d["first_name"] == "Alice"
    assert d["last_name"] == "Smith"
    assert d["address"] == "10 Downing Street"
    assert d["city"] == "London"
    assert d["postcode"] == "SW1A 2AA"


def test_customer_create_response_includes_identity(client):
    """POST /api/customers 返回值里直接带 5 个身份字段（前端立即可显示可复制）。"""
    body = {"email": "manual@x.com", "activation_date": "2026-07-14", "use_sim_code": False}
    r = client.post("/api/customers", json=body)
    assert r.status_code == 201
    data = r.json()
    for field in ("first_name", "last_name", "address", "city", "postcode"):
        assert data.get(field), f"create response should include {field}"


def test_random_identity_postcode_matches_city():
    """邮编前缀必须对应城市——跑 100 次验证一致。"""
    from uk_random import generate_random_identity, CITY_POSTCODES

    for _ in range(100):
        ident = generate_random_identity()
        city = ident["city"]
        postcode = ident["postcode"]
        # 提取 postcode 前缀（第一个空格前的字母数字部分）
        prefix = postcode.split(" ")[0]
        # 提取真正的字母部分（去掉开头的数字）
        prefix_letters = ""
        for ch in prefix:
            if ch.isalpha():
                prefix_letters += ch
            elif prefix_letters:
                break
        assert prefix_letters in CITY_POSTCODES[city], \
            f"postcode {postcode!r} prefix {prefix_letters!r} 不在 {city!r} 的邮编区 {CITY_POSTCODES[city]}"
