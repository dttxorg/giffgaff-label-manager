import asyncio
import json
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


@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        original = (database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH)
        database.DATABASE_PATH = db_path
        crud.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        asyncio.run(database.init_db())
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        c = TestClient(main.app)
        yield c
        database.DATABASE_PATH, crud.DATABASE_PATH, main.DATABASE_PATH = original


def test_list_email_providers_empty(client):
    r = client.get("/api/email-providers")
    assert r.status_code == 200
    assert r.json() == []


def test_post_email_providers_moemail(client):
    body = {
        "name": "moemail_main",
        "provider_type": "moemail",
        "config": {"url": "https://moemail.test", "api_key": "k"},
    }
    r = client.post("/api/email-providers", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "moemail_main"
    assert data["provider_type"] == "moemail"


def test_post_email_providers_rejects_unknown_type(client):
    body = {"name": "x", "provider_type": "invalid", "config": {}}
    r = client.post("/api/email-providers", json=body)
    assert r.status_code == 400


def test_post_email_providers_duplicate_name(client):
    body1 = {"name": "moemail_main", "provider_type": "moemail",
             "config": {"url": "https://x", "api_key": "k"}}
    r1 = client.post("/api/email-providers", json=body1)
    assert r1.status_code == 201
    r2 = client.post("/api/email-providers", json=body1)
    assert r2.status_code == 409


def test_get_single_provider(client):
    body = {"name": "a", "provider_type": "moemail",
            "config": {"url": "https://x", "api_key": "k"}}
    r = client.post("/api/email-providers", json=body)
    pid = r.json()["id"]
    g = client.get(f"/api/email-providers/{pid}")
    assert g.status_code == 200
    assert g.json()["name"] == "a"


def test_patch_provider_renames(client):
    body = {"name": "a", "provider_type": "moemail",
            "config": {"url": "https://x", "api_key": "k"}}
    r = client.post("/api/email-providers", json=body)
    pid = r.json()["id"]
    p = client.patch(f"/api/email-providers/{pid}", json={"name": "renamed"})
    assert p.status_code == 200
    assert p.json()["ok"] is True
    # Verify the rename happened via GET
    g = client.get(f"/api/email-providers/{pid}")
    assert g.json()["name"] == "renamed"


def test_delete_provider(client):
    body = {"name": "to_delete", "provider_type": "moemail",
            "config": {"url": "https://x", "api_key": "k"}}
    r = client.post("/api/email-providers", json=body)
    pid = r.json()["id"]
    d = client.delete(f"/api/email-providers/{pid}")
    assert d.status_code == 200
    g = client.get(f"/api/email-providers/{pid}")
    assert g.status_code == 404


def test_post_test_endpoint_returns_status(client):
    body = {"name": "to_test", "provider_type": "moemail",
            "config": {"url": "https://nonexistent.invalid", "api_key": "k"}}
    r = client.post("/api/email-providers", json=body)
    pid = r.json()["id"]
    t = client.post(f"/api/email-providers/{pid}/test")
    assert t.status_code in (200, 502)


def test_add_customer_routes_through_pool(client):
    """When add_customer is called with blank email, customer row should
    have email_provider_id and email_account_id populated from the pool."""
    import json
    import sqlite3
    # Seed two MoEmail providers directly
    now = "2026-07-04T10:00:00+00:00"
    with sqlite3.connect(database.DATABASE_PATH) as conn:
        conn.execute(
            """INSERT INTO email_providers (name, provider_type, config_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("provider_a", "moemail",
             json.dumps({"url": "https://test", "api_key": "k"}), now, now),
        )
        conn.commit()

    # Monkey-patch _generate_email_account to return synthetic data
    orig_gen = main._generate_email_account

    async def fake_gen(*, manual_provider_id=None, manual_domain=None):
        return {
            "email": "synthetic@example.com",
            "email_account_id": "syn-99",
            "email_provider_id": 1,
            "share_link": None,
            "is_email_auto": True,
        }

    main._generate_email_account = fake_gen
    try:
        body = {"email": "", "activation_date": "2026-07-04", "use_sim_code": False}
        r = client.post("/api/customers", json=body)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["email"] == "synthetic@example.com"
    finally:
        main._generate_email_account = orig_gen

    # Verify customer row in DB has the new columns
    with sqlite3.connect(database.DATABASE_PATH) as conn:
        cur = conn.execute(
            "SELECT email, email_provider_id, email_account_id, moemail_id, is_moemail_auto FROM customers"
        )
        row = cur.fetchone()
    assert row[0] == "synthetic@example.com"
    assert row[1] == 1
    assert row[2] == "syn-99"
    assert row[3] == "syn-99"  # moemail_id legacy column bridges
    assert row[4] == 1
