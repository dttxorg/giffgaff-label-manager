"""Shared pytest fixtures for desktop-client tests.

Tests in this directory do NOT launch a real browser. They mock the
Playwright Page and the AgentApi to exercise the orchestration logic
in isolation.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from giffgaff_client.api import AgentApi, ApiError
from giffgaff_client.automation import BrowserSession


@pytest.fixture
def mock_page() -> MagicMock:
    """A MagicMock stand-in for playwright.sync_api.Page."""
    page = MagicMock()
    page.url = "about:blank"
    page.locator.return_value.inner_text.return_value = ""
    return page


@pytest.fixture
def mock_agent_api() -> MagicMock:
    """A MagicMock AgentApi with successful defaults."""
    api = MagicMock(spec=AgentApi)
    api.verification_code.return_value = {"code": ""}
    api.update_result.return_value = {"ok": True}
    api.update_status.return_value = {"ok": True}
    api.add_log.return_value = {"ok": True}
    return api


@pytest.fixture
def api_error() -> type[ApiError]:
    return ApiError


@pytest.fixture
def make_session():
    """Factory that builds a BrowserSession whose heavy init is bypassed.

    Returns a function that takes optional overrides and yields a session
    ready for direct method testing.
    """

    def _make(
        *,
        task: dict | None = None,
        agent_api: MagicMock | None = None,
        config_full_auto: bool = True,
    ) -> BrowserSession:
        session = BrowserSession.__new__(BrowserSession)
        session.task = task or {
            "customer_id": 1,
            "email": "u@example.com",
            "initial_password": "Secret#1",
            "sim_activation_code": "ABC123",
        }
        session._agent_api = agent_api if agent_api is not None else MagicMock(spec=AgentApi)
        session.stop_requested = False
        session.payment_page_seen = False
        import queue as _queue
        session.commands = _queue.Queue()
        from giffgaff_client.config import AppConfig
        session.config = AppConfig(full_auto=config_full_auto)
        session.log_lines = []
        session.log = lambda msg, *args, **kwargs: session.log_lines.append(msg)
        return session

    return _make