import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import aiosqlite

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import crud
import database
import main
from models import CustomerCreate


def _patch_db_paths(testcase, tmp_dir):
    db_path = str(Path(tmp_dir) / "test.db")
    testcase.original_paths = (
        database.DATABASE_PATH,
        crud.DATABASE_PATH,
        main.DATABASE_PATH,
    )
    database.DATABASE_PATH = db_path
    crud.DATABASE_PATH = db_path
    main.DATABASE_PATH = db_path


def _restore_db_paths(testcase):
    database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH = testcase.original_paths


class SaveEsimCodeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir_ctx = tempfile.TemporaryDirectory()
        _patch_db_paths(self, self.temp_dir_ctx.name)
        self.original_gen = main._generate_moemail_account

        async def fake_gen(domain=None):
            return {"email": "x@y", "moemail_id": None, "moemail_address": "x@y",
                    "share_link": None, "is_moemail_auto": False}

        main._generate_moemail_account = fake_gen
        await database.init_db()
        result = await main.add_customer(
            CustomerCreate(
                email="x@y",
                activation_date=date(2026, 6, 24),
                use_sim_code=False,
            )
        )
        self.customer_id = result["customer_id"]

    async def asyncTearDown(self):
        _restore_db_paths(self)
        main._generate_moemail_account = self.original_gen
        self.temp_dir_ctx.cleanup()

    async def test_save_valid_code(self):
        result = await main.save_customer_esim_code(
            self.customer_id, main.EsimCodeUpdate.model_validate({"code": "1$smpd$CODE1"})
        )
        assert result["ok"] is True
        async with aiosqlite.connect(main.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT esim_raw_code FROM customers WHERE id = ?", (self.customer_id,))
            row = await cur.fetchone()
        assert row["esim_raw_code"] == "1$smpd$CODE1"

    async def test_save_invalid_format_raises_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await main.save_customer_esim_code(
                self.customer_id, main.EsimCodeUpdate.model_validate({"code": "not-a-valid-code"})
            )
        assert ctx.exception.status_code == 400

    async def test_save_with_lpa_prefix(self):
        result = await main.save_customer_esim_code(
            self.customer_id, main.EsimCodeUpdate.model_validate({"code": "LPA:1$smpd$CODE"})
        )
        assert result["ok"] is True

    async def test_save_empty_clears_code(self):
        # First save something
        await main.save_customer_esim_code(
            self.customer_id, main.EsimCodeUpdate.model_validate({"code": "1$smpd$CODE"})
        )
        # Then clear
        result = await main.save_customer_esim_code(
            self.customer_id, main.EsimCodeUpdate.model_validate({"code": ""})
        )
        assert result["ok"] is True
        async with aiosqlite.connect(main.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT esim_raw_code FROM customers WHERE id = ?", (self.customer_id,))
            row = await cur.fetchone()
        assert row["esim_raw_code"] is None

    async def test_save_unknown_customer_404(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await main.save_customer_esim_code(
                99999, main.EsimCodeUpdate.model_validate({"code": "1$smpd$CODE"})
            )
        assert ctx.exception.status_code == 404