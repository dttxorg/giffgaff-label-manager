"""公开扫码页测试：
- 新建客户自动生成 public_token
- /p/{token} 返回 200 + 邮箱 + 复制按钮 + 安全头
- 错误 token → 404，不泄露其他客户
- 邮箱为空 → 404
- 公开页绕过后台口令鉴权
- 固定运营内容与安全富文本渲染
- XSS 防护：script 与 javascript: 都被过滤
"""
from __future__ import annotations

import asyncio
import os
import re
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
        asyncio.run(database.init_db())
        yield TestClient(main.app)
        database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH = original


def _create(email: str) -> int:
    return asyncio.run(crud.create_customer(CustomerCreate(
        email=email, activation_date="2026-07-11",
    )))


async def _clear_public_token(customer_id: int) -> None:
    """模拟新增公开页功能之前创建、尚无 token 的存量客户。"""
    import aiosqlite
    async with aiosqlite.connect(database.DATABASE_PATH) as db:
        await db.execute(
            "UPDATE customers SET public_token = NULL, public_version = 1 WHERE id = ?",
            (customer_id,),
        )
        await db.commit()


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
    asyncio.run(crud.update_customer(cid, CustomerUpdate(phone_number="447400123456")))
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/p/{token}")
    assert r.status_code == 200
    body = r.text
    assert "alice@giffgaff.example" in body
    assert "复制邮箱" in body
    assert "giffgaff 已激活号码资料" in body
    assert "号码与初始邮箱" in body
    assert "giffgaff 套餐充值服务" in body
    assert "ChatGPT Plus" in body
    assert "ChatGPT 5x Pro" in body
    assert "ChatGPT 20x Pro" in body
    assert "giffgaff 手机号码（官网账号）" in body
    assert "初始注册邮箱（官网登录密码）" in body
    assert "账号登录信息" not in body
    assert "请勿在京东咨询" in body
    assert "号码保号提醒服务" in body
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
    from public_routes import _markdown_to_safe_html
    body = _markdown_to_safe_html(
        "请在 **Giffgaff App** 中使用 [官网](https://www.giffgaff.com) 注册。"
    )
    assert "<strong>Giffgaff App</strong>" in body
    assert 'href="https://www.giffgaff.com"' in body
    assert 'target="_blank"' in body
    assert 'rel="noopener noreferrer"' in body


def test_xss_in_markdown_is_escaped(client):
    from public_routes import _markdown_to_safe_html
    body = _markdown_to_safe_html(
        '<script>alert(1)</script>\n<img src=x onerror=alert(1)>\n**safe**'
    )
    # 关键安全保证：原始 <script> 标签不可执行
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    # 原始 <img> 标签不可执行（被实体化）
    assert "<img src=x onerror=alert(1)>" not in body
    assert "&lt;img" in body
    # 合法 Markdown 仍能渲染
    assert "<strong>safe</strong>" in body


def test_javascript_scheme_blocked(client):
    from public_routes import _markdown_to_safe_html
    body = _markdown_to_safe_html("[click me](javascript:alert(1))")
    assert "javascript:alert(1)" not in body
    # label 仍保留为纯文本
    assert "click me" in body


def test_markdown_heading_renders(client):
    from public_routes import _markdown_to_safe_html
    body = _markdown_to_safe_html("## 标题\n\n正文")
    assert "<h3>标题</h3>" in body
    assert "<p>正文</p>" in body


def test_rich_markdown_components_render_safely(client):
    from public_routes import _markdown_to_safe_html
    body = _markdown_to_safe_html(
            "## 快速开始\n\n"
            "1. 复制邮箱\n2. 打开应用\n3. 完成设置\n\n"
            "- 永久有效\n- 请妥善保存\n\n"
            "> 建议先截图保存\n\n"
            ":::promo 推荐内容\n这是一个 **宣传卡片**。\n:::\n\n"
            ":::warning 注意事项\n不要把验证码发给陌生人。\n:::\n\n"
            "[查看教程](https://example.com/guide)"
    )

    assert '<ol class="content-list content-steps">' in body
    assert '<ul class="content-list">' in body
    assert "<blockquote>建议先截图保存</blockquote>" in body
    assert 'class="callout callout-promo"' in body
    assert 'class="callout callout-warning"' in body
    assert "<strong>宣传卡片</strong>" in body
    assert 'href="https://example.com/guide"' in body
    assert 'target="_blank"' in body


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


def test_ensure_public_link_lazily_fills_legacy_customer(client):
    cid = _create("legacy@x.com")
    asyncio.run(_clear_public_token(cid))

    r = client.post(f"/api/customers/{cid}/public-link/ensure")

    assert r.status_code == 200
    body = r.json()
    assert body["public_token"]
    assert len(body["public_token"]) >= 30
    assert body["public_version"] == 1
    assert client.get(f"/p/{body['public_token']}").status_code == 200


def test_ensure_public_link_does_not_rotate_existing_token(client):
    cid = _create("existing@x.com")
    before = client.get(f"/api/customers/{cid}").json()

    first = client.post(f"/api/customers/{cid}/public-link/ensure").json()
    second = client.post(f"/api/customers/{cid}/public-link/ensure").json()

    assert first == second
    assert first["public_token"] == before["public_token"]
    assert first["public_version"] == before["public_version"]


def test_public_token_version_endpoint(client):
    cid = _create("alice@x.com")
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/api/public/{token}/version")
    assert r.status_code == 200
    assert r.json() == {"public_version": 3_000_001}


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
    assert r.headers.get("X-Cache-Version") == "3000001"
    # 重新生成后 v2
    client.post(f"/api/customers/{cid}/public-link/regenerate")
    new_token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/p/{new_token}")
    assert r.headers.get("X-Cache-Version") == "3000002"


def test_contact_markdown_change_bumps_all_cache_versions_without_rotating_tokens(client):
    first_id = _create("first@x.com")
    second_id = _create("second@x.com")
    first = client.get(f"/api/customers/{first_id}").json()
    second = client.get(f"/api/customers/{second_id}").json()

    client.patch("/api/settings", json={"public_page_markdown": "新说明"})

    first_after = client.get(f"/api/customers/{first_id}").json()
    second_after = client.get(f"/api/customers/{second_id}").json()
    assert first_after["public_token"] == first["public_token"]
    assert second_after["public_token"] == second["public_token"]
    assert first_after["public_version"] == first["public_version"] + 1
    assert second_after["public_version"] == second["public_version"] + 1

    # 相同内容再次保存不会继续制造缓存版本。
    client.patch("/api/settings", json={"public_page_markdown": "新说明"})
    assert client.get(f"/api/customers/{first_id}").json()["public_version"] == first_after["public_version"]


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
    """单字段生成器也只能返回核验地址池里的真实值。"""
    from uk_random import (
        generate_first_name, generate_last_name, generate_address,
        generate_postcode, generate_random_identity, REAL_UK_ADDRESSES,
    )
    assert isinstance(generate_first_name(), str) and len(generate_first_name()) > 0
    assert isinstance(generate_last_name(), str) and len(generate_last_name()) > 0
    assert generate_address() in {item["address"] for item in REAL_UK_ADDRESSES}
    pc = generate_postcode()
    assert pc in {item["postcode"] for item in REAL_UK_ADDRESSES}
    # 正确 UK 邮编格式：空格后必须是“数字 + 两个字母”。
    assert re.fullmatch(r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$", pc), f"bad postcode: {pc!r}"
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


def test_random_identity_uses_verified_location_as_an_indivisible_tuple():
    """连续生成时，地址、城市和邮编必须完整命中同一条核验记录。"""
    from uk_random import generate_random_identity, REAL_UK_ADDRESSES

    verified = {
        (item["address"], item["city"], item["postcode"])
        for item in REAL_UK_ADDRESSES
    }
    assert len(verified) >= 500
    assert len(verified) == len(REAL_UK_ADDRESSES)
    assert len({item["city"] for item in REAL_UK_ADDRESSES}) >= 25

    for _ in range(500):
        ident = generate_random_identity()
        location = (ident["address"], ident["city"], ident["postcode"])
        assert location in verified, f"生成了地址池外或错配的地址组合：{location!r}"


def test_verified_postcode_pool_uses_real_uk_format_and_prefix_filter():
    """地址池邮编格式正确；前缀筛选绝不能回退到随机伪造。"""
    from uk_random import generate_postcode, REAL_UK_ADDRESSES

    postcode_pattern = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$")
    assert all(postcode_pattern.fullmatch(item["postcode"]) for item in REAL_UK_ADDRESSES)

    ec2_postcodes = {
        item["postcode"] for item in REAL_UK_ADDRESSES
        if item["postcode"].startswith("EC2")
    }
    assert generate_postcode(" ec2 ") in ec2_postcodes
    with pytest.raises(ValueError):
        generate_postcode("ZZ99")


def test_address_pool_csv_has_unique_official_source_ids():
    """生成数据必须可追溯到唯一 FHRS 记录，不能退化成人工拼接列表。"""
    import csv
    from uk_random import ADDRESS_DATA_PATH

    with ADDRESS_DATA_PATH.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) >= 500
    assert len({row["source_id"] for row in rows}) == len(rows)
    assert all(row["source_id"].isdigit() for row in rows)


def test_fhrs_builder_normalizes_and_filters_public_premises():
    """构建器只接收有完整邮编和门牌号的公开营业场所。"""
    scripts_dir = BACKEND_DIR.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from build_uk_address_pool import establishment_to_row

    sample = {
        "FHRSID": 123456,
        "BusinessType": "Restaurant/Cafe/Canteen",
        "AddressLine1": "10 - 12 Market Street",
        "AddressLine2": "Leicester",
        "AddressLine3": "",
        "AddressLine4": "",
        "PostCode": "le1 6dp ",
    }
    assert establishment_to_row(sample, "Leicester", ("Leicester",)) == {
        "address": "10 - 12 Market Street",
        "city": "Leicester",
        "postcode": "LE1 6DP",
        "source_id": "123456",
    }

    mobile = dict(sample, BusinessType="Mobile caterer")
    assert establishment_to_row(mobile, "Leicester", ("Leicester",)) is None
    no_house_number = dict(sample, AddressLine1="Market Street")
    assert establishment_to_row(no_house_number, "Leicester", ("Leicester",)) is None


# ── Markdown 变量替换 ──


def test_substitute_simple_var():
    from public_routes import _substitute_variables
    assert _substitute_variables("Hello {name}", {"name": "Alice"}) == "Hello Alice"
    assert _substitute_variables("Phone: {phone}", {"phone": "447400123456"}) == "Phone: 447400123456"


def test_substitute_missing_var_replaced_with_empty():
    from public_routes import _substitute_variables
    assert _substitute_variables("Phone: {phone}", {}) == "Phone: "


def test_substitute_multiple_vars_in_one_line():
    from public_routes import _substitute_variables
    out = _substitute_variables(
        "{first_name} {last_name} 在 {city} {postcode}",
        {"first_name": "Emma", "last_name": "Smith", "city": "London", "postcode": "NW1 6XE"},
    )
    assert out == "Emma Smith 在 London NW1 6XE"


def test_substitute_unknown_var_returns_empty():
    from public_routes import _substitute_variables
    # {xxx} 不在 vars 里，替换为空（不显示 {xxx}）
    assert _substitute_variables("Test {unknown}", {}) == "Test "


def test_substitute_escapes_braces_correctly():
    from public_routes import _substitute_variables
    # 含连字符的「变量名」不匹配正则（要求字母数字下划线），所以原样保留
    assert _substitute_variables("Test {a-b}", {"a-b": "x"}) == "Test {a-b}"


def test_substitute_none_values():
    from public_routes import _substitute_variables
    assert _substitute_variables("Phone: {x}", {"x": None}) == "Phone: "


def test_build_substitution_vars_includes_customer_fields():
    """客户字段（phone/email/name/address/...）都能被引用。"""
    from public_routes import _build_substitution_vars
    row = {
        "email": "alice@x.com", "phone_number": "447400123456",
        "first_name": "Emma", "last_name": "Smith",
        "address": "42 Baker Street", "city": "London", "postcode": "NW1 6XE",
        "sim_activation_code": "ABC123", "initial_password": "Pwd123",
        "share_link": "https://share", "activation_date": "2026-07-14",
        "phone_status": "激活", "shipping_address": "上海",
        "moemail_address": "alice@x.com",
    }
    vars_ = _build_substitution_vars(row)
    assert vars_["phone_number"] == "447400123456"
    assert vars_["first_name"] == "Emma"
    assert vars_["last_name"] == "Smith"
    assert vars_["full_name"] == "Smith Emma"
    assert vars_["email"] == "alice@x.com"
    assert vars_["full_address"] == "42 Baker Street, London, NW1 6XE"
    assert vars_["sim_activation_code"] == "ABC123"
    assert vars_["phone_status"] == "激活"


def test_custom_public_vars_round_trip(client):
    """全局自定义变量可以保存和读取。"""
    r = client.patch("/api/settings", json={
        "custom_public_vars": '{"support_phone": "400-123-4567", "telegram": "@myname"}'
    })
    assert r.status_code == 200
    s = client.get("/api/settings").json()
    assert "support_phone" in s["custom_public_vars"]
    assert "400-123-4567" in s["custom_public_vars"]


def test_custom_public_vars_invalid_json_rejected(client):
    r = client.patch("/api/settings", json={"custom_public_vars": "{bad json"})
    assert r.status_code == 400


def test_custom_public_vars_not_object_rejected(client):
    r = client.patch("/api/settings", json={"custom_public_vars": "[1, 2, 3]"})
    assert r.status_code == 400


def test_custom_public_vars_invalid_name_rejected(client):
    r = client.patch("/api/settings", json={
        "custom_public_vars": '{"bad-name": "x"}'  # 含连字符
    })
    assert r.status_code == 400


def test_activated_page_ignores_legacy_custom_markdown(client):
    """旧数据库里的自定义说明不再控制公开页，避免排版失控。"""
    cid = _create("initial.email@example.com")
    asyncio.run(crud.update_customer(cid, CustomerUpdate(phone_number="447400123456")))
    client.patch("/api/settings", json={
        "public_page_markdown": "LEGACY_CUSTOM_PAGE {first_name}",
    })

    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    body = client.get(f"/p/{token}").text

    assert "LEGACY_CUSTOM_PAGE" not in body
    assert "initial.email@example.com" in body
    assert "447400123456" in body
    assert "giffgaff 已激活号码使用说明" in body


def test_activated_page_ignores_legacy_custom_vars(client):
    cid = _create("a@x.com")
    client.patch("/api/settings", json={
        "custom_public_vars": '{"support_phone": "400-123-4567", "telegram": "@myname"}',
        "public_page_markdown": "LEGACY_SUPPORT {support_phone} {telegram}",
    })
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    body = client.get(f"/p/{token}").text

    assert "LEGACY_SUPPORT" not in body
    assert "400-123-4567" not in body
    assert "@myname" not in body
    assert "ChatGPT Plus" in body


def test_public_page_shows_phone_when_set(client):
    """客户有手机号时，公开页面应显示手机号行。"""
    import crud
    from models import CustomerCreate, CustomerUpdate
    cid = asyncio.run(crud.create_customer(CustomerCreate(email='a@x.com', activation_date='2026-07-14')))
    asyncio.run(crud.update_customer(cid, CustomerUpdate(phone_number='447400123456')))
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/p/{token}")
    assert r.status_code == 200
    body = r.text
    assert 'id="phone-row"' in body
    assert 'data-phone="447400123456"' in body
    assert '已复制手机号' in body


def test_public_page_hides_phone_when_empty(client):
    """客户没手机号时，phone-row 整段不渲染。"""
    import crud
    from models import CustomerCreate
    cid = asyncio.run(crud.create_customer(CustomerCreate(email='a@x.com', activation_date='2026-07-14')))
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/p/{token}")
    assert r.status_code == 200
    body = r.text
    # phone-row 整段被替换为空字符串
    assert 'id="phone-row"' not in body
    assert 'data-phone=' not in body
    # 模板里有 '已复制手机号' 的 inline script 字符串，但 phone-row 相关的 button 应不存在
    assert 'id="phone-copy-btn"' not in body


def test_public_page_email_still_shown(client):
    """回归：email 仍正常显示。"""
    import crud
    from models import CustomerCreate
    cid = asyncio.run(crud.create_customer(CustomerCreate(email='a@x.com', activation_date='2026-07-14')))
    token = client.get(f"/api/customers/{cid}").json()["public_token"]
    r = client.get(f"/p/{token}")
    body = r.text
    assert 'data-email="a@x.com"' in body
    assert '已复制邮箱' in body


def test_public_page_disables_cloudflare_email_obfuscation(client):
    """主邮箱和 Markdown 邮箱都必须避开 Cloudflare Email Obfuscation。"""
    from public_routes import _render_card
    body = _render_card(
        "real.customer@example.com",
        "联系支持：support@example.net",
        {},
    )
    main_email = re.search(
        r'<!--email_off-->\s*'
        r'<code id="email" data-email="real\.customer@example\.com"[^>]*>'
        r'real\.customer@example\.com</code>\s*'
        r'<!--/email_off-->',
        body,
    )
    assert main_email, "主邮箱元素必须由 email_off 标记完整包裹"

    hint = re.search(
        r'<div class="hint" id="hint">\s*<!--email_off-->(.*?)<!--/email_off-->\s*</div>',
        body,
        re.DOTALL,
    )
    assert hint, "Markdown 渲染区域必须由 email_off 标记完整包裹"
    assert "support@example.net" in hint.group(1)

    assert body.count("<!--email_off-->") == 2
    assert body.count("<!--/email_off-->") == 2
    assert 'data-email="real.customer@example.com"' in body
    assert "copyFromEl('email', '已复制邮箱')" in body
    assert "navigator.clipboard.writeText(value)" in body
