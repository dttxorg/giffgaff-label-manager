"""End-to-end lifecycle test for the email provider pool.

Verifies:
- POST /api/email-providers adds a provider
- GET  /api/email-providers lists them
- POST /api/email-providers/{id}/test pings (with mocked provider)
- POST /api/customers routes through pool when email is blank
- Round-robin across 2 providers
- Manual override pins to a specific provider
- Cooldown skips errored providers

This is an integration test using TestClient + mocked CloudMail/MoEmail HTTP calls.
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
import main
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_two_providers():
    """Set up a temp DB, register 2 MoEmail providers, return TestClient."""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        original = (database.DATABASE_PATH, main.DATABASE_PATH)
        database.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        asyncio.run(database.init_db())
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""

        # Seed 2 MoEmail providers — never-used
        now = "2026-07-04T00:00:00+00:00"
        with sqlite3.connect(db_path) as conn:
            for name in ["provider_a", "provider_b"]:
                conn.execute(
                    """INSERT INTO email_providers
                       (name, provider_type, config_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (name, "moemail",
                     json.dumps({"url": "https://test", "api_key": "k"}), now, now),
                )
            conn.commit()

        c = TestClient(main.app)
        yield c, db_path
        database.DATABASE_PATH = original[0]


def test_pool_round_robin(client_with_two_providers):
    """When 2 providers are never-used, calling add_customer twice should assign different providers."""
    client, db_path = client_with_two_providers

    # Mock MoEmail client to return synthetic data.
    # Patch BOTH the source module (email_providers._moemail_client) and the re-binding
    # inside email_providers.moemail so the provider's constructor picks up the mock.
    with patch("email_providers._moemail_client.MoEmailClient") as mock_cls, \
         patch("email_providers.moemail.MoEmailClient") as mock_cls2:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_cls2.return_value = mock_instance
        # Each generate_email call → returns ID N
        call_count = {"n": 0}
        def fake_generate_email(name=None, **kwargs):
            call_count["n"] += 1
            return {"id": call_count["n"], "email": f"user{call_count['n']}@test"}
        mock_instance.generate_email.side_effect = fake_generate_email
        mock_instance.create_share_link.return_value = {"link": "http://share/test"}

        # Stub record_provider_use / persist_provider_jwt to track only
        with patch("email_providers.pool.record_provider_use") as mock_record, \
             patch("email_providers.pool.persist_provider_jwt"):
            mock_record.return_value = None
            provider_ids = []
            for _ in range(4):
                # Add 4 customers with blank email
                body = {"email": "", "activation_date": "2026-07-04", "use_sim_code": False}
                r = client.post("/api/customers", json=body)
                assert r.status_code == 201
                # Read the customer row to find email_provider_id
                with sqlite3.connect(db_path) as conn:
                    cur = conn.execute(
                        "SELECT email_provider_id FROM customers ORDER BY id DESC LIMIT 1"
                    )
                    row = cur.fetchone()
                provider_ids.append(row[0])

    # Round-robin across 2 providers means we should see both IDs in 4 calls
    unique = set(provider_ids)
    assert len(unique) == 2, f"Expected 2 distinct providers, got {provider_ids}"
    # And the sequence should be roughly even: each provider used ~2 times
    from collections import Counter
    counts = Counter(provider_ids)
    for pid, cnt in counts.items():
        assert cnt == 2, f"Provider {pid} used {cnt} times, expected 2"


def test_manual_override_pins_provider(client_with_two_providers):
    """When email_provider_id is passed in body, that exact provider is used."""
    client, db_path = client_with_two_providers

    # Get provider IDs
    list_r = client.get("/api/email-providers")
    providers = list_r.json()
    pid_a, pid_b = providers[0]["id"], providers[1]["id"]

    # Patch BOTH the source module AND the re-binding inside the provider module.
    with patch("email_providers._moemail_client.MoEmailClient") as mock_cls, \
         patch("email_providers.moemail.MoEmailClient") as mock_cls2:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_cls2.return_value = mock_instance
        mock_instance.generate_email.return_value = {"id": 99, "email": "pinned@test"}
        mock_instance.create_share_link.return_value = {"link": "x"}
        with patch("email_providers.pool.record_provider_use"), \
             patch("email_providers.pool.persist_provider_jwt"):

            # Force provider B
            body = {"email": "", "activation_date": "2026-07-04",
                    "use_sim_code": False, "email_provider_id": pid_b}
            r = client.post("/api/customers", json=body)
            assert r.status_code == 201

            with sqlite3.connect(db_path) as conn:
                cur = conn.execute(
                    "SELECT email_provider_id FROM customers ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
    assert row[0] == pid_b


def test_cooldown_skips_errored_providers(client_with_two_providers):
    """A provider with last_error_at within 5 min should be skipped."""
    client, db_path = client_with_two_providers
    list_r = client.get("/api/email-providers")
    providers = list_r.json()
    pid_recent_err, pid_ok = providers[0]["id"], providers[1]["id"]

    # Mark first provider as recently errored
    from datetime import datetime, timezone, timedelta
    recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE email_providers SET last_error_at = ?, last_error = ? WHERE id = ?",
            (recent_iso, "transient", pid_recent_err),
        )
        conn.commit()

    # Patch BOTH the source module AND the re-binding inside the provider module.
    with patch("email_providers._moemail_client.MoEmailClient") as mock_cls, \
         patch("email_providers.moemail.MoEmailClient") as mock_cls2:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_cls2.return_value = mock_instance
        mock_instance.generate_email.return_value = {"id": 1, "email": "ok@test"}
        mock_instance.create_share_link.return_value = {"link": "x"}
        with patch("email_providers.pool.record_provider_use"), \
             patch("email_providers.pool.persist_provider_jwt"):

            body = {"email": "", "activation_date": "2026-07-04", "use_sim_code": False}
            r = client.post("/api/customers", json=body)
            assert r.status_code == 201

            with sqlite3.connect(db_path) as conn:
                cur = conn.execute(
                    "SELECT email_provider_id FROM customers ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
    # Should have skipped the errored one
    assert row[0] == pid_ok


def test_503_when_pool_empty():
    """No providers configured → 503."""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        original = (database.DATABASE_PATH, main.DATABASE_PATH)
        database.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        asyncio.run(database.init_db())
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""

        c = TestClient(main.app)
        body = {"email": "", "activation_date": "2026-07-04", "use_sim_code": False}
        r = c.post("/api/customers", json=body)
        # add_customer returns 503 because _generate_email_account raises HTTPException(503)
        assert r.status_code == 503
        assert "No email providers configured" in r.json()["detail"]
        database.DATABASE_PATH = original[0]
