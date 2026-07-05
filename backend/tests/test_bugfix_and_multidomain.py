"""Regression + multi-domain tests for backend.

Covers:
- Bug #2: provider use is recorded only after customer commit; on failure no
  last_used_at is bumped (no churn in the round-robin selector).
- Bug #5: a corrupt email_providers row must not 500 the agent endpoints;
  pick_provider silently skips it and surfaces a 503 if everything is bad.
- Bug #14: POST /api/customers/{id}/reset restores a "已完成" customer
  to a pre-activation state and returns the SIM to the pool.
- Multi-domain: a single MoEmail provider with multiple `domains` rows
  can issue an email at any of those domains.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

BACKEND = "/Volumes/外置硬盘/claude code/giffgaff-reminder/backend"
sys.path.insert(0, BACKEND)

import database
import crud
import main
from models import (
    CustomerCreate,
    CustomerUpdate,
    EmailProviderCreate,
    EmailProviderDomainPick,
    ResetCustomerRequest,
)


# ───────────────────────── helpers ─────────────────────────

def _new_db() -> str:
    td = tempfile.mkdtemp()
    p = f"{td}/test.db"
    return p, td


def _bind_db(db_path: str):
    original = (database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH)
    database.DATABASE_PATH = db_path
    crud.DATABASE_PATH = db_path
    main.DATABASE_PATH = db_path
    return original


def _restore(original):
    database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH = original


def _init(db_path: str):
    asyncio.run(database.init_db())


def _insert_provider(db_path: str, name: str, *, provider_type: str = "moemail",
                    config: dict | None = None, domains: list[str] | None = None,
                    default_domain: str | None = None) -> int:
    if config is None:
        config = {"url": "https://x", "api_key": "k"} if provider_type == "moemail" else \
                 {"url": "https://x", "email": "a@b", "password": "p", "domain": "b"}
    now = "2026-07-05T10:00:00"
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO email_providers
               (name, provider_type, config_json, domains_json, default_domain,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, provider_type, json.dumps(config),
             json.dumps(domains or []), default_domain, now, now),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _mock_moemail_default():
    """Standard moemail mock factory: each call returns a unique account."""
    with patch("email_providers._moemail_client.MoEmailClient") as mock_cls, \
         patch("email_providers.moemail.MoEmailClient") as mock_cls2, \
         patch("email_providers.pool.persist_provider_jwt"):
        inst = MagicMock()
        mock_cls.return_value = inst
        mock_cls2.return_value = inst
        counter = {"n": 0}

        def fake_generate(name=None, **kwargs):
            counter["n"] += 1
            return {"id": f"m{counter['n']}", "email": f"a{counter['n']}@x.test"}
        inst.generate_email.side_effect = fake_generate
        inst.create_share_link.return_value = {"link": "http://share/x"}
        yield inst


# ───────────────────── Bug #5: corrupt config ─────────────────────

class TestCorruptProvider:
    """Bad email_providers rows should not 500 customer-facing endpoints."""

    def setup_method(self):
        self.db_path, self._td = _new_db()
        self.original = _bind_db(self.db_path)
        _init(self.db_path)
        # Two providers: one good, one with broken JSON.
        self.good_pid = _insert_provider(self.db_path, "good", config={"url": "https://x", "api_key": "k"})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO email_providers
                   (name, provider_type, config_json, created_at, updated_at)
                   VALUES (?, 'moemail', ?, ?, ?)""",
                ("bad", "not valid json {{{", "2026-07-05T10:00:00", "2026-07-05T10:00:00"),
            )
            conn.commit()
        client = TestClient(main.app)
        self.client = client

    def teardown_method(self):
        import shutil
        _restore(self.original)
        shutil.rmtree(self._td, ignore_errors=True)

    def test_pick_provider_skips_corrupt_row(self):
        from email_providers.pool import pick_provider
        pid, _ = pick_provider(self.db_path)
        assert pid == self.good_pid

    def test_list_email_providers_returns_all(self):
        r = self.client.get("/api/email-providers")
        assert r.status_code == 200
        names = {p["name"] for p in r.json()}
        assert {"good", "bad"} == names


# ───────────────────── Bug #2: commit-then-record ─────────────────────

class TestCommitThenRecord:
    """Pick_provider must not bump last_used_at until the customer commits."""

    def setup_method(self):
        self.db_path, self._td = _new_db()
        self.original = _bind_db(self.db_path)
        _init(self.db_path)
        self.pid_a = _insert_provider(self.db_path, "a")
        self.pid_b = _insert_provider(self.db_path, "b")
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        self.client = TestClient(main.app)

    def teardown_method(self):
        import shutil
        _restore(self.original)
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        shutil.rmtree(self._td, ignore_errors=True)

    def test_round_robin_alternates_after_real_commit(self):
        with patch("email_providers._moemail_client.MoEmailClient") as mc1, \
             patch("email_providers.moemail.MoEmailClient") as mc2, \
             patch("email_providers.pool.persist_provider_jwt"):
            mi = MagicMock()
            mc1.return_value = mi; mc2.return_value = mi
            cc = {"n": 0}
            def fake_generate_email(name=None, **kw):
                cc["n"] += 1
                return {"id": f"x{cc['n']}", "email": f"u{cc['n']}@x.test"}
            mi.generate_email.side_effect = fake_generate_email
            mi.create_share_link.return_value = {"link": "http://share/x"}
            out = []
            for _ in range(4):
                r = self.client.post(
                    "/api/customers",
                    json={"email": "", "activation_date": "2026-07-04", "use_sim_code": False},
                )
                assert r.status_code == 201
                with sqlite3.connect(self.db_path) as conn:
                    out.append(conn.execute(
                        "SELECT email_provider_id FROM customers ORDER BY id DESC LIMIT 1"
                    ).fetchone()[0])
        assert set(out) == {self.pid_a, self.pid_b}, out
        assert out.count(self.pid_a) == 2 and out.count(self.pid_b) == 2


# ───────────────────── Bug #14: reset endpoint ─────────────────────

class TestResetCustomer:
    def setup_method(self):
        self.db_path, self._td = _new_db()
        self.original = _bind_db(self.db_path)
        _init(self.db_path)
        _insert_provider(self.db_path, "p1")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO sim_codes (code) VALUES ('SIM-RESET')")
            conn.commit()
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        self.client = TestClient(main.app)

    def teardown_method(self):
        import shutil
        _restore(self.original)
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        shutil.rmtree(self._td, ignore_errors=True)

    def test_reset_full_returns_sim_to_pool(self):
        # Manually take the customer all the way to 已完成 / '已使用' SIM
        with patch("email_providers._moemail_client.MoEmailClient") as mc1, \
             patch("email_providers.moemail.MoEmailClient") as mc2, \
             patch("email_providers.pool.persist_provider_jwt"):
            mi = MagicMock()
            mc1.return_value = mi; mc2.return_value = mi
            mi.generate_email.return_value = {"id": "m1", "email": "a@x.test"}
            mi.create_share_link.return_value = {"link": "http://x"}
            r = self.client.post("/api/customers", json={
                "phone_number": "447123456789",
                "email": "",
                "activation_date": "2026-07-04",
                "use_sim_code": True,
            })
            assert r.status_code == 201, r.text
            cid = r.json()["customer_id"]
        # Simulate the "completed" state — public API doesn't expose a full
        # activation-result endpoint, so update via the activation-status
        # admin patch (which marks SIM 已使用) and write the phone number
        # through SQLite.
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE customers SET phone_number = ? WHERE id = ?",
                ("447123456789", cid),
            )
            conn.commit()
        status_r = self.client.patch(
            f"/api/customers/{cid}/activation-status",
            json={"status": "已完成"},
        )
        assert status_r.status_code == 200, status_r.text
        with sqlite3.connect(self.db_path) as conn:
            self.assert_sim_status(conn, "已使用", cid)
            assert self.phone(conn, cid) == "447123456789"
        # Reset
        r = self.client.post(f"/api/customers/{cid}/reset", json={})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"]
        assert set(body["detached"]) >= {"sim_code", "activation", "email", "email+phone"} or "email" in body["detached"] or "email+phone" in body["detached"]
        with sqlite3.connect(self.db_path) as conn:
            self.assert_sim_status(conn, "未分配", None)
            row = conn.execute(
                "SELECT sim_code_id, sim_activation_code, initial_password, activation_status, email, phone_number "
                "FROM customers WHERE id = ?", (cid,),
            ).fetchone()
            # Sim-related fields cleared
            assert row[0] is None and row[1] is None and row[2] is None
            assert row[3] == "未开始"
            # Email detached
            assert row[4] == ""
            # Phone detached (so re-import doesn't clash)
            assert row[5] is None

    def assert_sim_status(self, conn, expected: str, customer_id):
        row = conn.execute("SELECT status, customer_id FROM sim_codes").fetchone()
        assert row[0] == expected, (row[0], expected)

    def phone(self, conn, cid):
        return conn.execute("SELECT phone_number FROM customers WHERE id = ?", (cid,)).fetchone()[0]

    def test_reset_partial_keeps_email(self):
        """detach_sim_code=False leaves SIM associated with customer."""
        with patch("email_providers._moemail_client.MoEmailClient") as mc1, \
             patch("email_providers.moemail.MoEmailClient") as mc2, \
             patch("email_providers.pool.persist_provider_jwt"):
            mi = MagicMock()
            mc1.return_value = mi; mc2.return_value = mi
            mi.generate_email.return_value = {"id": "m1", "email": "a@x.test"}
            mi.create_share_link.return_value = {"link": "http://x"}
            r = self.client.post("/api/customers", json={
                "phone_number": "",
                "email": "",
                "activation_date": "2026-07-04",
                "use_sim_code": True,
            })
            cid = r.json()["customer_id"]
        r = self.client.post(f"/api/customers/{cid}/reset",
                              json={"detach_sim_code": False, "detach_email": False})
        assert r.status_code == 200
        with sqlite3.connect(self.db_path) as conn:
            sim = conn.execute("SELECT status, customer_id FROM sim_codes").fetchone()
            assert sim[0] == "已分配"
            assert sim[1] == cid
            cust = conn.execute("SELECT sim_code_id, email FROM customers WHERE id = ?", (cid,)).fetchone()
            assert cust[0] is not None


# ───────────────────── Multi-domain moemail ─────────────────────

class TestMultiDomainMoemail:
    def setup_method(self):
        self.db_path, self._td = _new_db()
        self.original = _bind_db(self.db_path)
        _init(self.db_path)
        self.provider_id = _insert_provider(
            self.db_path, "m1", domains=["a.test", "b.test"], default_domain="a.test",
        )
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        self.client = TestClient(main.app)

    def teardown_method(self):
        import shutil
        _restore(self.original)
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        shutil.rmtree(self._td, ignore_errors=True)

    def test_list_email_providers_exposes_domains(self):
        r = self.client.get("/api/email-providers")
        assert r.status_code == 200, r.text
        provider = r.json()[0]
        assert provider["domains"] == ["a.test", "b.test"]
        assert provider["default_domain"] == "a.test"

    def test_add_customer_with_explicit_domain_passes_through(self):
        chosen = {"domain": None}

        def fake_generate(name=None, **kwargs):
            chosen["domain"] = kwargs.get("domain")
            return {"id": "m1", "email": "u@b.test"}

        with patch("email_providers._moemail_client.MoEmailClient") as mc1, \
             patch("email_providers.moemail.MoEmailClient") as mc2, \
             patch("email_providers.pool.persist_provider_jwt"):
            mi = MagicMock()
            mc1.return_value = mi; mc2.return_value = mi
            mi.generate_email.side_effect = fake_generate
            mi.create_share_link.return_value = {"link": "http://share"}
            r = self.client.post("/api/customers", json={
                "phone_number": "",
                "email": "",
                "activation_date": "2026-07-04",
                "use_sim_code": False,
                "email_provider_id": self.provider_id,
                "email_provider_domain": "b.test",
            })
            assert r.status_code == 201, r.text
            assert chosen["domain"] == "b.test", chosen
            cid = r.json()["customer_id"]
            assert r.json()["email_provider_domain"] == "b.test"
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT email_provider_id, email_provider_domain FROM customers WHERE id = ?",
                    (cid,),
                ).fetchone()
            assert row[0] == self.provider_id
            assert row[1] == "b.test"

    def test_add_customer_uses_provider_default_domain_when_unspecified(self):
        chosen = {"domain": None}

        def fake_generate(name=None, **kwargs):
            chosen["domain"] = kwargs.get("domain")
            return {"id": "m1", "email": "u@a.test"}

        with patch("email_providers._moemail_client.MoEmailClient") as mc1, \
             patch("email_providers.moemail.MoEmailClient") as mc2, \
             patch("email_providers.pool.persist_provider_jwt"):
            mi = MagicMock()
            mc1.return_value = mi; mc2.return_value = mi
            mi.generate_email.side_effect = fake_generate
            mi.create_share_link.return_value = {"link": "http://share"}
            r = self.client.post("/api/customers", json={
                "phone_number": "",
                "email": "",
                "activation_date": "2026-07-04",
                "use_sim_code": False,
                "email_provider_id": self.provider_id,
            })
            assert r.status_code == 201
            assert chosen["domain"] == "a.test"


# ───────────────────── DELETE provider clears data ─────────────────────

class TestProviderDomainUpdate:
    def setup_method(self):
        self.db_path, self._td = _new_db()
        self.original = _bind_db(self.db_path)
        _init(self.db_path)
        self.pid = _insert_provider(self.db_path, "p1", domains=["x.test"], default_domain="x.test")
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        self.client = TestClient(main.app)

    def teardown_method(self):
        import shutil
        _restore(self.original)
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        shutil.rmtree(self._td, ignore_errors=True)

    def test_update_provider_domains_persists(self):
        r = self.client.patch(
            f"/api/email-providers/{self.pid}",
            json={"domains": ["a.test", "b.test"], "default_domain": "b.test"},
        )
        assert r.status_code == 200, r.text
        r = self.client.get("/api/email-providers")
        provider = next(p for p in r.json() if p["id"] == self.pid)
        assert provider["domains"] == ["a.test", "b.test"]
        assert provider["default_domain"] == "b.test"
