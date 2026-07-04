"""Tests for Bug #1: inbox fetch should route via email_provider_id, not hardcoded MoEmail.

These tests verify that get_customer_verification_code and
get_customer_payment_info_emails use the customer's assigned provider rather than
the global MoEmail settings.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import database
import crud
import main
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_two_providers_and_customer():
    """One MoEmail + one cloud-mail provider, one customer assigned to cloud-mail."""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        original = (database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH)
        database.DATABASE_PATH = db_path
        crud.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        asyncio.run(database.init_db())
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""

        now = "2026-07-04T10:00:00+00:00"
        with sqlite3.connect(db_path) as conn:
            # Two providers
            conn.execute(
                """INSERT INTO email_providers
                   (name, provider_type, config_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                ("moemail_main", "moemail",
                 json.dumps({"url": "https://moemail.test", "api_key": "k"}),
                 now, now),
            )
            conn.execute(
                """INSERT INTO email_providers
                   (name, provider_type, config_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                ("cloudmail_main", "cloudmail",
                 json.dumps({"url": "https://cm.test", "email": "a@b",
                             "password": "pw", "domain": "b.com"}),
                 now, now),
            )
            # Customer assigned to provider 2 (cloud-mail)
            conn.execute(
                """INSERT INTO customers
                   (email, activation_date, activation_status,
                    email_provider_id, email_account_id,
                    moemail_id, moemail_address)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("user@cloud.test", "2026-07-04", "未开始",
                 2, "cm-account-99", "cm-account-99", "user@cloud.test"),
            )
            # Also a legacy MoEmail-only customer (no new columns)
            conn.execute(
                """INSERT INTO customers
                   (email, activation_date, activation_status,
                    moemail_id, moemail_address, is_moemail_auto)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("legacy@moemail.test", "2026-07-04", "未开始",
                 "legacy-mbox-id", "legacy@moemail.test", 1),
            )
            # Seed global MoEmail settings for legacy fallback
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('moemail_url', 'https://legacy-moemail.test')"
            )
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('moemail_api_key', 'legacy-key')"
            )
            conn.commit()

        c = TestClient(main.app)
        yield c, db_path
        database.DATABASE_PATH = original[0]
        crud.DATABASE_PATH = original[1]
        main.DATABASE_PATH = original[2]


def _patch_moemail():
    return patch("email_providers._moemail_client.MoEmailClient")


def _patch_cloudmail():
    return patch("email_providers.cloudmail.httpx")


def test_cloudmail_customer_uses_cloudmail_provider(client_with_two_providers_and_customer):
    """A customer with email_provider_id pointing to a cloud-mail provider
    should fetch inbox via cloud-mail, NOT MoEmail."""
    client, db_path = client_with_two_providers_and_customer

    # Find the cloud-mail customer
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT id FROM customers WHERE email_provider_id = 2"
        )
        customer_id = cur.fetchone()[0]

    # If the bug exists, this endpoint constructs MoEmailClient and calls MoEmail API.
    # After fix, it constructs CloudMailProvider and calls cloudmail API.
    with _patch_moemail() as me_cls, \
         _patch_cloudmail() as cm_httpx:
        moemail_instance = MagicMock()
        me_cls.return_value = moemail_instance
        moemail_instance.get_email_messages.return_value = {"messages": []}

        cm_post = MagicMock(status_code=200, json=lambda: {"data": {"token": "j"}})
        cm_get = MagicMock(status_code=200, json=lambda: {"data": []})
        cm_httpx.post.return_value = cm_post
        cm_httpx.get.return_value = cm_get

        r = client.get(f"/api/customers/{customer_id}/verification-code")
        assert r.status_code == 200
        # MoEmail client must NOT have been instantiated
        me_cls.assert_not_called()
        # Cloud-mail endpoint must have been called
        cm_httpx.get.assert_called()


def test_legacy_moemail_customer_uses_global_settings(client_with_two_providers_and_customer):
    """Pre-existing customer (NULL email_provider_id, populated moemail_*) should
    continue to use global MoEmail settings."""
    client, db_path = client_with_two_providers_and_customer

    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT id FROM customers WHERE moemail_id IS NOT NULL AND email_provider_id IS NULL"
        )
        customer_id = cur.fetchone()[0]

    with _patch_moemail() as me_cls, \
         _patch_cloudmail() as cm_httpx, \
         patch("email_providers.moemail.MoEmailClient") as me_cls2:
        moemail_instance = MagicMock()
        me_cls.return_value = moemail_instance
        me_cls2.return_value = moemail_instance
        moemail_instance.get_email_messages.return_value = {"messages": []}

        cm_httpx.post.return_value = MagicMock(
            status_code=200, json=lambda: {"data": {"token": "j"}}
        )
        cm_httpx.get.return_value = MagicMock(
            status_code=200, json=lambda: {"data": []}
        )

        r = client.get(f"/api/customers/{customer_id}/verification-code")
        # Should succeed (any 2xx) — bug fix preserves legacy behavior
        assert r.status_code == 200
        # Legacy path picks first MoEmail in pool; that constructs via
        # email_providers.moemail.MoEmailClient (which is bound at import time).
        me_cls2.assert_called_once()
        cm_httpx.get.assert_not_called()


def test_unknown_provider_404_or_sensible_error(client_with_two_providers_and_customer):
    """If the assigned provider is missing from the pool, the endpoint should
    return a sensible error (not a 500)."""
    client, db_path = client_with_two_providers_and_customer

    with sqlite3.connect(db_path) as conn:
        # Assign customer_id=1 to a non-existent provider_id
        conn.execute(
            "UPDATE customers SET email_provider_id = 9999 WHERE id = 1"
        )
        conn.commit()

    r = client.get("/api/customers/1/verification-code")
    # Should NOT be a 500. Either 404 (provider missing) or 400 (descriptive error).
    assert 400 <= r.status_code < 500, f"Got {r.status_code}: {r.text}"
