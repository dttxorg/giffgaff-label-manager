import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import database
import main
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        original = (database.DATABASE_PATH, main.DATABASE_PATH)
        database.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        asyncio.run(database.init_db())
        main.APP_PASSWORD = ""
        main.AGENT_API_TOKEN = ""
        c = TestClient(main.app)
        yield c
        database.DATABASE_PATH = original[0]


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
