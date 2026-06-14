from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any


APP_NAME = "GiffgaffActivationClient"
DEFAULT_ACTIVATION_URL = "https://www.giffgaff.com/activate"


def app_config_dir() -> Path:
    root = os.getenv("APPDATA")
    if root:
        base = Path(root)
    else:
        base = Path.home() / ".config"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_user_data_dir() -> str:
    return str(app_config_dir() / "browser-profile")


def config_path() -> Path:
    return app_config_dir() / "config.json"


@dataclass
class ProxyConfig:
    mode: str = "none"
    proxy_type: str = "http"
    host: str = ""
    port: str = ""
    username: str = ""
    password: str = ""

    def playwright_proxy(self) -> dict[str, str] | None:
        if self.mode != "custom":
            return None
        host = self.host.strip()
        port = self.port.strip()
        if not host or not port:
            return None
        server = f"{self.proxy_type}://{host}:{port}"
        proxy: dict[str, str] = {"server": server}
        if self.username:
            proxy["username"] = self.username
        if self.password:
            proxy["password"] = self.password
        return proxy


@dataclass
class AppConfig:
    server_url: str = "http://127.0.0.1:8000"
    agent_token: str = ""
    agent_id: str = "windows-01"
    activation_url: str = DEFAULT_ACTIVATION_URL
    browser_channel: str = "msedge"
    user_data_dir: str = field(default_factory=default_user_data_dir)
    headless: bool = False
    slow_mo_ms: int = 120
    proxy: ProxyConfig = field(default_factory=ProxyConfig)


def _merge_config(raw: dict[str, Any]) -> AppConfig:
    proxy_raw = raw.get("proxy") if isinstance(raw.get("proxy"), dict) else {}
    proxy = ProxyConfig(**{k: v for k, v in proxy_raw.items() if k in ProxyConfig.__dataclass_fields__})
    values = {k: v for k, v in raw.items() if k in AppConfig.__dataclass_fields__ and k != "proxy"}
    return AppConfig(**values, proxy=proxy)


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return _merge_config(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return AppConfig()


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
