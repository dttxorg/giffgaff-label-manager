"""激活码在线验证测试（Playwright 软依赖 + trigger 逻辑）。"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import database
import crud
import main
from fastapi.testclient import TestClient
from models import CustomerCreate, SimCodeUpdate


@pytest.fixture
def client():
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


def _import_sim(code: str) -> int:
    """导入一个 SIM 码，返回 id。"""
    async def _go():
        async with __import__("aiosqlite").connect(crud.DATABASE_PATH) as db:
            cur = await db.execute("INSERT INTO sim_codes (code) VALUES (?)", (code,))
            await db.commit()
            return cur.lastrowid
    return asyncio.run(_go())


# ── validator 模块自身 ──


def test_validator_returns_skipped_when_no_playwright():
    """没装 playwright 时返 'skipped'，不抛异常。"""
    from activation_validator import validate_activation_code

    async def _go():
        return await validate_activation_code("ABC-123")

    result = asyncio.run(_go())
    assert result["result"] in ("skipped", "error", "valid", "invalid")
    if result["result"] == "skipped":
        assert "Playwright" in (result["error"] or "")
    assert result["checked_at"]


def test_save_validation_result_persists_fields():
    """save_validation_result 把 checked_at/result/error 三个字段正确写入。"""
    from activation_validator import save_validation_result

    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "test.db")

        async def _go():
            import aiosqlite
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    """CREATE TABLE sim_codes (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       code TEXT NOT NULL UNIQUE,
                       status TEXT NOT NULL DEFAULT '未分配',
                       last_validated_at TEXT,
                       last_validation_result TEXT,
                       last_validation_error TEXT
                    )"""
                )
                cur = await db.execute("INSERT INTO sim_codes (code) VALUES ('X')")
                sim_id = cur.lastrowid
                await db.commit()
            await save_validation_result(db_path, sim_id, {
                "result": "valid",
                "error": None,
                "final_url": "https://x/activate?email",
                "checked_at": "2026-07-14T10:00:00+00:00",
            })
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                row = await (await db.execute("SELECT * FROM sim_codes WHERE id = ?", (sim_id,))).fetchone()
                return dict(row)

        row = asyncio.run(_go())
        assert row["last_validation_result"] == "valid"
        assert row["last_validated_at"] == "2026-07-14T10:00:00+00:00"
        assert row["last_validation_error"] is None


# ── trigger 逻辑（mock validator） ──


def test_customer_creation_triggers_validation_when_using_sim_code(client):
    """客户创建用激活码 → 调用 _run_sim_code_validation 一次。"""
    sid = _import_sim("ABC-CREATE-001")
    called = []

    async def fake_validator(sim_id, code):
        called.append((sim_id, code))

    with patch.object(main, "_run_sim_code_validation", side_effect=fake_validator):
        r = client.post("/api/customers", json={
            "email": "manual@x.com",  # 提供手填邮箱，避开 MoEmail 自动生成
            "activation_date": "2026-07-14",
            "use_sim_code": True,
        })
        assert r.status_code == 201, r.text

    assert len(called) == 1
    sim_id, code = called[0]
    assert sim_id == sid
    assert code == "ABC-CREATE-001"


def test_customer_creation_without_sim_code_does_not_trigger(client):
    """客户创建不用激活码 → 不触发验证。"""
    _import_sim("ABC-NO-TRIGGER")
    called = []

    async def fake_validator(sim_id, code):
        called.append((sim_id, code))

    with patch.object(main, "_run_sim_code_validation", side_effect=fake_validator):
        r = client.post("/api/customers", json={
            "email": "manual@x.com",
            "activation_date": "2026-07-14",
            "use_sim_code": False,
        })
        assert r.status_code == 201

    assert called == []


def test_sim_status_change_to_allocated_triggers_validation(client):
    """PATCH 把 SIM 码状态改为「已分配」→ 触发验证。"""
    sid = _import_sim("ABC-ALLOC-001")
    called = []

    async def fake_validator(sim_id, code):
        called.append((sim_id, code))

    with patch.object(main, "_run_sim_code_validation", side_effect=fake_validator):
        r = client.patch(f"/api/sim-codes/{sid}", json={"status": "已分配"})
        assert r.status_code == 200, r.text

    assert len(called) == 1
    assert called[0][0] == sid


def test_sim_status_change_to_other_status_does_not_trigger(client):
    """改状态为「已使用」/「失败」等 → 不触发验证（只触发已分配）。"""
    sid = _import_sim("ABC-OTHER-001")
    called = []

    async def fake_validator(sim_id, code):
        called.append((sim_id, code))

    with patch.object(main, "_run_sim_code_validation", side_effect=fake_validator):
        r = client.patch(f"/api/sim-codes/{sid}", json={"status": "作废"})
        assert r.status_code == 200

    assert called == []


def test_manual_validate_endpoint_triggers_validation(client):
    """POST /api/sim-codes/{id}/validate → 触发一次验证。"""
    sid = _import_sim("ABC-MANUAL-001")
    called = []

    async def fake_validator(sim_id, code):
        called.append((sim_id, code))

    with patch.object(main, "_run_sim_code_validation", side_effect=fake_validator):
        r = client.post(f"/api/sim-codes/{sid}/validate")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True

    assert len(called) == 1
    assert called[0] == (sid, "ABC-MANUAL-001")


def test_manual_validate_unknown_id_404(client):
    r = client.post("/api/sim-codes/99999/validate")
    assert r.status_code == 404


# ── API 透出新字段 ──


def test_sim_codes_list_includes_validation_fields(client):
    sid = _import_sim("ABC-LIST-001")

    async def _save():
        from activation_validator import save_validation_result
        await save_validation_result(crud.DATABASE_PATH, sid, {
            "result": "valid",
            "error": None,
            "final_url": None,
            "checked_at": "2026-07-14T10:00:00+00:00",
        })
    asyncio.run(_save())

    lst = client.get("/api/sim-codes").json()
    target = next(c for c in lst if c["id"] == sid)
    assert target["last_validation_result"] == "valid"
    assert target["last_validated_at"] == "2026-07-14T10:00:00+00:00"


def test_sim_codes_list_default_validation_fields_null(client):
    sid = _import_sim("ABC-NULL-001")
    lst = client.get("/api/sim-codes").json()
    target = next(c for c in lst if c["id"] == sid)
    assert target["last_validated_at"] is None
    assert target["last_validation_result"] is None
    assert target["last_validation_error"] is None
