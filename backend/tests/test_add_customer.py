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


class AddCustomerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test.db")
        self.original_paths = (
            database.DATABASE_PATH,
            crud.DATABASE_PATH,
            main.DATABASE_PATH,
        )
        self.original_generate_email = main._generate_email_account
        database.DATABASE_PATH = self.db_path
        crud.DATABASE_PATH = self.db_path
        main.DATABASE_PATH = self.db_path

        async def fake_generate_email(*, manual_provider_id=None, manual_domain=None):
            return {
                "email": "auto@example.com",
                "email_account_id": "mailbox-1",
                "email_provider_id": None,
                "share_link": "https://681218.xyz/shared/token",
                "is_email_auto": True,
            }

        main._generate_email_account = fake_generate_email
        await database.init_db()

    async def asyncTearDown(self):
        database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH = self.original_paths
        main._generate_email_account = self.original_generate_email
        self.temp_dir.cleanup()

    async def test_blank_email_auto_generates_without_sim_code(self):
        result = await main.add_customer(
            CustomerCreate(
                email="",
                activation_date=date(2026, 6, 20),
                use_sim_code=False,
            )
        )

        self.assertEqual(result["email"], "auto@example.com")
        self.assertIsNone(result["sim_activation_code"])

        customer = await crud.get_customer(result["customer_id"])
        self.assertEqual(customer["email"], "auto@example.com")
        self.assertEqual(customer["moemail_id"], "mailbox-1")
        self.assertEqual(customer["is_moemail_auto"], 1)
        self.assertIsNone(customer["sim_code_id"])
        self.assertEqual(customer["activation_status"], "未开始")

    async def test_blank_email_auto_generates_with_sim_code(self):
        async with aiosqlite.connect(main.DATABASE_PATH) as db:
            await db.execute("INSERT INTO sim_codes (code) VALUES (?)", ("SIM123456",))
            await db.commit()

        result = await main.add_customer(
            CustomerCreate(
                email="",
                activation_date=date(2026, 6, 20),
                use_sim_code=True,
            )
        )

        self.assertEqual(result["email"], "auto@example.com")
        self.assertEqual(result["sim_activation_code"], "SIM123456")
        self.assertTrue(result["initial_password"])

        customer = await crud.get_customer(result["customer_id"])
        self.assertEqual(customer["email"], "auto@example.com")
        self.assertEqual(customer["sim_activation_code"], "SIM123456")
        self.assertEqual(customer["activation_status"], "已分配激活码")
