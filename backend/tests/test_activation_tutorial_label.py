"""未激活卡教程二维码与独立打印模板回归测试。"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

import crud
import database
import main


@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        original = (
            database.DATABASE_PATH,
            crud.DATABASE_PATH,
            main.DATABASE_PATH,
            main.APP_PASSWORD,
            main.ADMIN_ENTRY_PATH,
        )
        database.DATABASE_PATH = db_path
        crud.DATABASE_PATH = db_path
        main.DATABASE_PATH = db_path
        main.APP_PASSWORD = ""
        main.ADMIN_ENTRY_PATH = ""
        asyncio.run(database.init_db())
        test_client = TestClient(main.app)
        try:
            yield test_client
        finally:
            test_client.close()
            (
                database.DATABASE_PATH,
                crud.DATABASE_PATH,
                main.DATABASE_PATH,
                main.APP_PASSWORD,
                main.ADMIN_ENTRY_PATH,
            ) = original


def _tutorial_template(config: dict) -> dict:
    return next(t for t in config["templates"] if t["id"] == "activation-guide-50x40")


def test_default_label_config_includes_activation_tutorial_template(client):
    response = client.get("/api/label-config")

    assert response.status_code == 200
    config = response.json()
    assert config["activation_tutorial_url"] == "https://gg.681218.xyz/activation.html"
    template = _tutorial_template(config)
    assert template["name"] == "未激活卡教程 50x40"
    sources = [element["source"] for element in template["elements"]]
    assert "激活教程地址" in sources
    assert "激活教程二维码" in sources
    assert "手机号" not in sources
    assert "邮箱" not in sources


def test_existing_saved_templates_are_merged_with_tutorial_template(client):
    asyncio.run(crud.set_setting("label_templates", json.dumps([
        {
            "id": "existing-template",
            "name": "原模板",
            "width_mm": 50,
            "height_mm": 40,
            "elements": [],
        }
    ], ensure_ascii=False)))

    config = client.get("/api/label-config").json()

    ids = {template["id"] for template in config["templates"]}
    assert "existing-template" in ids
    assert "activation-guide-50x40" in ids


def test_tutorial_url_can_be_saved_independently(client):
    config = client.get("/api/label-config").json()
    config["activation_tutorial_url"] = "https://example.com/new-activation-guide"

    saved = client.put("/api/label-config", json=config)

    assert saved.status_code == 200
    reloaded = client.get("/api/label-config").json()
    assert reloaded["activation_tutorial_url"] == "https://example.com/new-activation-guide"
    assert reloaded["giffgaff_download_url"] == config["giffgaff_download_url"]


def test_system_settings_exposes_tutorial_url(client):
    response = client.patch("/api/settings", json={
        "activation_tutorial_url": "https://example.com/tutorial.html",
    })

    assert response.status_code == 200
    settings = client.get("/api/settings").json()
    assert settings["activation_tutorial_url"] == "https://example.com/tutorial.html"


@pytest.mark.parametrize("endpoint,payload", [
    ("/api/settings", {"activation_tutorial_url": "javascript:alert(1)"}),
    ("/api/label-config", {
        "giffgaff_download_url": "https://www.giffgaff.com/mobile-app",
        "activation_tutorial_url": "not-a-url",
        "templates": [],
    }),
])
def test_tutorial_url_rejects_non_http_schemes(client, endpoint, payload):
    method = client.patch if endpoint == "/api/settings" else client.put
    response = method(endpoint, json=payload)
    assert response.status_code == 400


def test_frontend_has_selectable_tutorial_sources_and_template():
    html = (ROOT_DIR / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "const DEFAULT_ACTIVATION_TUTORIAL_URL = 'https://gg.681218.xyz/activation.html';" in html
    assert "onclick=\"addLabelElement('qr', '激活教程二维码')\"" in html
    assert "case '激活教程地址':" in html
    assert "source === '激活教程二维码'" in html
    assert "id: 'activation-guide-50x40'" in html
