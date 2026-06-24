# Activation Full-Auto Pre-Payment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the half-automatic Giffgaff Activation Client into a full-automatic flow that drives SIM code → email → verification code → password → preferences → plan → topup → address → payment page, then auto-extracts the assigned phone number after payment and reports it to the backend.

**Architecture:** Single-state-loop orchestrator in `BrowserSession._auto_run_until_payment` that classifies the current page by text matching and dispatches to existing per-step handlers (which we'll enhance with retry + polling). After the payment page is reached, a passive watcher in `_command_loop` polls for the giffgaff number on a 3s tick and calls `AgentApi.update_result` once it appears. A new "停止自动化" button in the UI lets the user interrupt cleanly.

**Tech Stack:** Python 3.11+, PySide6, Playwright (sync API), pytest, dataclasses. No backend, DB, or giffgaff API changes.

**Spec:** `docs/superpowers/specs/2026-06-24-activation-full-auto-pre-payment-design.md`

---

## File Structure

| File | Role |
|---|---|
| `desktop-client/giffgaff_client/config.py` | Add `full_auto: bool = True` field to `AppConfig` |
| `desktop-client/giffgaff_client/automation.py` | Add `_auto_run_until_payment`, `_try_poll_and_fill_verification_code`, `_wait_and_extract_phone_number`, `_report_phone_number_to_backend`, `_log_stuck`, `_page_text`. Modify `_choose_pay_as_you_go` for retry, `run()` for orchestrator hook, `_command_loop` for phone-number polling |
| `desktop-client/giffgaff_client/main_window.py` | Add `auto_running` state, `stop_automation` handler, 「停止自动化」 button, enable/disable logic for existing buttons |
| `desktop-client/tests/conftest.py` | Pytest fixtures: `mock_page` (Page mock), `mock_session` (BrowserSession subclass with isolated methods), `mock_api` (AgentApi mock) |
| `desktop-client/tests/test_choose_payg_retry.py` | Tests for retry on `_choose_pay_as_you_go` |
| `desktop-client/tests/test_phone_extract.py` | Tests for `_wait_and_extract_phone_number` regex |
| `desktop-client/tests/test_report_phone.py` | Tests for `_report_phone_number_to_backend` |
| `desktop-client/tests/test_poll_verification_code.py` | Tests for `_try_poll_and_fill_verification_code` |
| `desktop-client/tests/test_log_stuck.py` | Tests for `_log_stuck` |
| `desktop-client/tests/test_auto_run_until_payment.py` | Tests for the orchestrator dispatch loop |
| `desktop-client/pytest.ini` | Pytest config |
| `desktop-client/README.md` | Document full-auto mode + stop button |

---

## Task 1: Add `full_auto` to `AppConfig`

**Files:**
- Modify: `desktop-client/giffgaff_client/config.py` (find `AppConfig` dataclass)

- [ ] **Step 1: Add the field**

In `AppConfig` (around line 14), add `full_auto` after `auto_login_account`:

```python
@dataclass
class AppConfig:
    server_url: str = "http://localhost:8000"
    api_token: str = ""
    cf_access_client_id: str = ""
    cf_access_client_secret: str = ""
    agent_id: str = "desktop-agent"
    user_data_dir: str = ""
    channel: str = "msedge"
    proxy: str = "system"
    slow_mo: int = 0
    headless: bool = False
    auto_login_account: str = ""
    auto_login_password: str = ""
    auto_login_headless: bool = False
    full_auto: bool = True
    save_path: str = ""
```

- [ ] **Step 2: Verify**

Run: `cd desktop-client && .venv/bin/python -c "from giffgaff_client.config import AppConfig; c = AppConfig(); print(c.full_auto)"`

Expected: `True`

- [ ] **Step 3: Verify backward compat**

Run: `cd desktop-client && .venv/bin/python -c "
import json
from giffgaff_client.config import AppConfig
old = {'server_url': 'http://x', 'api_token': 'y'}
c = AppConfig(**old)
print(c.full_auto, c.server_url, c.api_token)
"`

Expected: `True http://x y`

- [ ] **Step 4: Commit**

```bash
git add desktop-client/giffgaff_client/config.py
git commit -m "feat(config): add full_auto flag (default true)"
```

---

## Task 2: Set up pytest scaffolding

**Files:**
- Create: `desktop-client/pytest.ini`
- Create: `desktop-client/tests/__init__.py`
- Create: `desktop-client/tests/conftest.py`

- [ ] **Step 1: Create pytest.ini**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -ra -q
```

- [ ] **Step 2: Create tests/__init__.py**

```python
# Empty file to mark tests as a package
```

- [ ] **Step 3: Create tests/conftest.py with shared fixtures**

```python
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
        session.commands = __import__("queue").Queue()
        from giffgaff_client.config import AppConfig
        session.config = AppConfig(full_auto=config_full_auto)
        session.log_lines = []
        session.log = lambda msg, *args, **kwargs: session.log_lines.append(msg)
        return session

    return _make
```

- [ ] **Step 4: Verify scaffolding works**

Create `tests/test_sanity.py`:

```python
def test_sanity():
    assert 1 + 1 == 2
```

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_sanity.py -v`

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add desktop-client/pytest.ini desktop-client/tests/__init__.py desktop-client/tests/conftest.py desktop-client/tests/test_sanity.py
git commit -m "test: scaffold pytest with shared fixtures"
```

---

## Task 3: Test + implement `_page_text` helper

**Files:**
- Modify: `desktop-client/giffgaff_client/automation.py` (add helper near other `_page_*` methods)
- Create: `desktop-client/tests/test_page_text.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_page_text.py
from unittest.mock import MagicMock


def test_page_text_returns_inner_text(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "hello world"
    session = make_session()
    result = session._page_text(mock_page)
    assert result == "hello world"


def test_page_text_returns_empty_on_timeout(make_session, mock_page):
    from playwright.sync_api import Error as PlaywrightError

    mock_page.locator.return_value.inner_text.side_effect = PlaywrightError("timeout")
    session = make_session()
    result = session._page_text(mock_page)
    assert result == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_page_text.py -v`

Expected: `AttributeError: 'BrowserSession' object has no attribute '_page_text'`

- [ ] **Step 3: Implement `_page_text`**

In `automation.py`, near the other `_page_has_text` helpers, add:

```python
    def _page_text(self, page: Page) -> str:
        """Return the visible text of <body>, or empty string on timeout."""
        try:
            return page.locator("body").inner_text(timeout=2000)
        except PlaywrightError:
            return ""
```

(If `PlaywrightError` is not yet imported at the top of `automation.py`, ensure `from playwright.sync_api import Error as PlaywrightError` exists or add it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_page_text.py -v`

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add desktop-client/giffgaff_client/automation.py desktop-client/tests/test_page_text.py
git commit -m "feat(automation): add _page_text helper for body text"
```

---

## Task 4: Test + implement `_log_stuck` helper

**Files:**
- Modify: `desktop-client/giffgaff_client/automation.py`
- Create: `desktop-client/tests/test_log_stuck.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_log_stuck.py


def test_log_stuck_writes_structured_message(make_session):
    session = make_session()
    session._log_stuck("邮箱验证码", "拉取 90s 未拿到")
    assert any("【卡住】邮箱验证码" in line for line in session.log_lines)
    assert any("拉取 90s 未拿到" in line for line in session.log_lines)


def test_log_stuck_calls_add_log_with_step(make_session, mock_agent_api):
    session = make_session(agent_api=mock_agent_api)
    session._log_stuck("选套餐", "重试 3 次均失败")
    mock_agent_api.add_log.assert_called_once()
    args, kwargs = mock_agent_api.add_log.call_args
    assert args[0] == 1  # customer_id
    assert "选套餐" in args[1]
    assert kwargs.get("step") == "auto_stuck"


def test_log_stuck_does_not_raise_when_api_fails(make_session, mock_agent_api):
    from giffgaff_client.api import ApiError

    mock_agent_api.add_log.side_effect = ApiError("backend down")
    session = make_session(agent_api=mock_agent_api)
    session._log_stuck("未知页面", "URL=/foo")  # should not raise
    assert any("未知页面" in line for line in session.log_lines)


def test_log_stuck_skips_add_log_when_no_customer_id(make_session, mock_agent_api):
    session = make_session(task={"customer_id": None})
    session._log_stuck("密码页", "no password")
    mock_agent_api.add_log.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_log_stuck.py -v`

Expected: `AttributeError: 'BrowserSession' object has no attribute '_log_stuck'`

- [ ] **Step 3: Implement `_log_stuck`**

Add to `automation.py`:

```python
    def _log_stuck(self, step: str, reason: str) -> None:
        """Log a structured 'stuck' event. Does NOT mark backend task as failed."""
        message = f"【卡住】{step} — {reason}。请人工处理后点「继续当前页面」恢复。"
        self.log(message)
        api = self._agent_api
        customer_id = (self.task or {}).get("customer_id")
        if api and customer_id:
            try:
                api.add_log(int(customer_id), message, step="auto_stuck")
            except (ApiError, ValueError, TypeError):
                pass
```

(Ensure `ApiError` is imported: `from .api import AgentApi, ApiError`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_log_stuck.py -v`

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add desktop-client/giffgaff_client/automation.py desktop-client/tests/test_log_stuck.py
git commit -m "feat(automation): add _log_stuck helper"
```

---

## Task 5: Test + implement phone-number extraction helper

**Files:**
- Modify: `desktop-client/giffgaff_client/automation.py` (add module-level constant)
- Create: `desktop-client/tests/test_phone_extract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_phone_extract.py
import re

from giffgaff_client.automation import PHONE_NUMBER_PATTERN


def test_pattern_matches_spaced_format():
    m = PHONE_NUMBER_PATTERN.search("Your giffgaff number is 07732 212776")
    assert m is not None
    assert re.sub(r"\D", "", m.group(0)) == "07732212776"


def test_pattern_matches_unspaced_format():
    m = PHONE_NUMBER_PATTERN.search("07732212776")
    assert m is not None


def test_pattern_matches_dashed_format():
    m = PHONE_NUMBER_PATTERN.search("Call 07732-212776 today")
    assert m is not None


def test_pattern_does_not_match_landline():
    m = PHONE_NUMBER_PATTERN.search("020 7946 0958")
    assert m is None


def test_pattern_does_not_match_random_eleven_digits():
    m = PHONE_NUMBER_PATTERN.search("Order ID 12345678901")
    assert m is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_phone_extract.py -v`

Expected: `ImportError: cannot import name 'PHONE_NUMBER_PATTERN'`

- [ ] **Step 3: Implement the constant**

At module level in `automation.py`, near the top:

```python
PHONE_NUMBER_PATTERN = re.compile(r"\b07\d{3}[\s-]?\d{6}\b")
```

(Ensure `import re` is at the top of the file. If not, add it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_phone_extract.py -v`

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add desktop-client/giffgaff_client/automation.py desktop-client/tests/test_phone_extract.py
git commit -m "feat(automation): add PHONE_NUMBER_PATTERN regex"
```

---

## Task 6: Test + implement `_wait_and_extract_phone_number`

**Files:**
- Modify: `desktop-client/giffgaff_client/automation.py`
- Create: `desktop-client/tests/test_wait_phone.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wait_phone.py
from unittest.mock import MagicMock

from giffgaff_client.automation import BrowserSession


def test_returns_phone_when_text_matches(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = (
        "Your giffgaff number is 07732 212776"
    )
    session = make_session()
    result = session._wait_and_extract_phone_number(mock_page, timeout_seconds=1)
    assert result == "07732212776"


def test_returns_empty_when_text_has_no_phone(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Loading..."
    session = make_session()
    result = session._wait_and_extract_phone_number(mock_page, timeout_seconds=1)
    assert result == ""


def test_returns_empty_on_stop_requested(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Your number is 07732 212776"
    session = make_session()
    session.stop_requested = True
    result = session._wait_and_extract_phone_number(mock_page, timeout_seconds=10)
    assert result == ""


def test_first_match_wins(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = (
        "07711 222333 / 07744 555666"
    )
    session = make_session()
    result = session._wait_and_extract_phone_number(mock_page, timeout_seconds=1)
    assert result == "07711222333"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_wait_phone.py -v`

Expected: `AttributeError: 'BrowserSession' object has no attribute '_wait_and_extract_phone_number'`

- [ ] **Step 3: Implement `_wait_and_extract_phone_number`**

```python
    def _wait_and_extract_phone_number(
        self, page: Page, *, timeout_seconds: int = 180
    ) -> str:
        """Poll page body text for a UK mobile number. Returns 11-digit string, or "" on timeout/stop."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.stop_requested:
                return ""
            text = self._page_text(page)
            if text:
                match = PHONE_NUMBER_PATTERN.search(text)
                if match:
                    digits = re.sub(r"\D", "", match.group(0))
                    if digits.startswith("07") and len(digits) >= 11:
                        return digits[:11]
            time.sleep(1)
        return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_wait_phone.py -v`

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add desktop-client/giffgaff_client/automation.py desktop-client/tests/test_wait_phone.py
git commit -m "feat(automation): add _wait_and_extract_phone_number"
```

---

## Task 7: Test + implement `_report_phone_number_to_backend`

**Files:**
- Modify: `desktop-client/giffgaff_client/automation.py`
- Create: `desktop-client/tests/test_report_phone.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_phone.py
from giffgaff_client.api import ApiError


def test_reports_phone_with_default_status(make_session, mock_agent_api):
    session = make_session(agent_api=mock_agent_api)
    session._report_phone_number_to_backend("07732212776")
    mock_agent_api.update_result.assert_called_once()
    args, kwargs = mock_agent_api.update_result.call_args
    assert args[0] == 1  # customer_id
    assert kwargs["phone_number"] == "07732212776"
    assert kwargs["status"] == "等待转 eSIM"
    assert any("07732212776" in line for line in session.log_lines)


def test_reports_phone_with_custom_status(make_session, mock_agent_api):
    session = make_session(agent_api=mock_agent_api)
    session._report_phone_number_to_backend("07732212776", status="已完成")
    args, kwargs = mock_agent_api.update_result.call_args
    assert kwargs["status"] == "已完成"


def test_logs_only_when_no_customer_id(make_session, mock_agent_api):
    session = make_session(task={"customer_id": None}, agent_api=mock_agent_api)
    session._report_phone_number_to_backend("07732212776")
    mock_agent_api.update_result.assert_not_called()
    assert any("本地记录" in line for line in session.log_lines)


def test_logs_only_when_no_api(make_session):
    session = make_session(agent_api=None)
    session._report_phone_number_to_backend("07732212776")
    assert any("本地记录" in line for line in session.log_lines)


def test_catches_api_error(make_session, mock_agent_api):
    mock_agent_api.update_result.side_effect = ApiError("network down")
    session = make_session(agent_api=mock_agent_api)
    session._report_phone_number_to_backend("07732212776")
    assert any("回传手机号失败" in line for line in session.log_lines)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_report_phone.py -v`

Expected: `TypeError: _report_phone_number_to_backend() got an unexpected keyword argument 'status'`

- [ ] **Step 3: Implement `_report_phone_number_to_backend`**

```python
    def _report_phone_number_to_backend(
        self, phone: str, *, status: str = "等待转 eSIM"
    ) -> None:
        """Push captured phone number to backend and set status."""
        customer_id = (self.task or {}).get("customer_id")
        api = self._agent_api
        if not api or not customer_id:
            self.log(f"未配置后台，仅本地记录手机号：{phone}")
            return
        try:
            api.update_result(int(customer_id), phone_number=phone, status=status)
            self.log(f"已回传手机号 {phone} 到后台，状态：{status}")
        except ApiError as exc:
            self.log(f"回传手机号失败：{exc}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_report_phone.py -v`

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add desktop-client/giffgaff_client/automation.py desktop-client/tests/test_report_phone.py
git commit -m "feat(automation): add _report_phone_number_to_backend"
```

---

## Task 8: Modify `_choose_pay_as_you_go` for retry

**Files:**
- Modify: `desktop-client/giffgaff_client/automation.py` (replace existing method)
- Create: `desktop-client/tests/test_choose_payg_retry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_choose_payg_retry.py
from unittest.mock import MagicMock

from giffgaff_client.automation import BrowserSession


def _make_page_with_text(text: str) -> MagicMock:
    page = MagicMock()
    page.locator.return_value.inner_text.return_value = text
    return page


def test_returns_false_when_page_does_not_match(make_session):
    page = _make_page_with_text("Some unrelated page")
    session = make_session()
    assert session._choose_pay_as_you_go(page) is False


def test_returns_true_on_first_attempt(make_session):
    page = _make_page_with_text("Choose a monthly plan")
    session = make_session()
    session._try_click_text = MagicMock(return_value=True)
    session._try_click_button = MagicMock(return_value=True)
    session._wait_ready = MagicMock()
    session._page_has_text = MagicMock(return_value=True)
    assert session._choose_pay_as_you_go(page) is True
    assert session._try_click_text.call_count == 1


def test_retries_then_succeeds(make_session):
    page = _make_page_with_text("Choose a monthly plan")
    session = make_session()
    session._try_click_text = MagicMock(side_effect=[False, False, True])
    session._try_click_button = MagicMock(return_value=True)
    session._wait_ready = MagicMock()
    session._page_has_text = MagicMock(return_value=True)
    assert session._choose_pay_as_you_go(page) is True
    assert session._try_click_text.call_count == 3


def test_returns_false_after_three_failures(make_session):
    page = _make_page_with_text("Choose a monthly plan")
    session = make_session()
    session._try_click_text = MagicMock(return_value=False)
    session._page_has_text = MagicMock(return_value=True)
    assert session._choose_pay_as_you_go(page) is False
    assert session._try_click_text.call_count == 3


def test_returns_early_on_stop_requested(make_session):
    page = _make_page_with_text("Choose a monthly plan")
    session = make_session()
    session.stop_requested = True
    session._page_has_text = MagicMock(return_value=True)
    session._try_click_text = MagicMock(return_value=True)
    assert session._choose_pay_as_you_go(page) is False
    session._try_click_text.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_choose_payg_retry.py -v`

Expected: Tests that expect 3 attempts will fail because the existing impl only tries once. Specifically `test_retries_then_succeeds` and `test_returns_false_after_three_failures`.

- [ ] **Step 3: Replace `_choose_pay_as_you_go`**

Find the existing method and replace it with:

```python
    def _choose_pay_as_you_go(self, page: Page) -> bool:
        if not self._page_has_text(page, [r"Choose a monthly plan", r"Other options", r"Pay as you go"]):
            return False
        for attempt in range(3):
            if self.stop_requested:
                return False
            if self._try_click_text(page, [r"No monthly plan", r"Pay as you go"]):
                self.log(f"已选择 Pay as you go（第 {attempt + 1} 次）")
                if self._try_click_button(page, [r"continue"]):
                    self._wait_ready(page)
                    return True
            time.sleep(1)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_choose_payg_retry.py -v`

Expected: `5 passed`

- [ ] **Step 5: Run full test suite to verify nothing else broke**

Run: `cd desktop-client && .venv/bin/python -m pytest -v`

Expected: All existing tests still pass (the only pre-existing tests should be `test_sanity.py`).

- [ ] **Step 6: Commit**

```bash
git add desktop-client/giffgaff_client/automation.py desktop-client/tests/test_choose_payg_retry.py
git commit -m "feat(automation): retry _choose_pay_as_you_go up to 3 times"
```

---

## Task 9: Test + implement `_try_poll_and_fill_verification_code`

**Files:**
- Modify: `desktop-client/giffgaff_client/automation.py`
- Create: `desktop-client/tests/test_poll_verification_code.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_poll_verification_code.py
from unittest.mock import MagicMock

from giffgaff_client.api import ApiError


def test_returns_true_when_code_arrives(make_session, mock_page, mock_agent_api):
    mock_agent_api.verification_code.side_effect = [
        {"code": ""},
        {"code": ""},
        {"code": "123456"},
    ]
    session = make_session(agent_api=mock_agent_api)
    session._fill_verification_code = MagicMock()
    result = session._try_poll_and_fill_verification_code(mock_page, timeout_seconds=10)
    assert result is True
    session._fill_verification_code.assert_called_once_with(mock_page, "123456")
    assert mock_agent_api.verification_code.call_count == 3


def test_returns_false_on_timeout(make_session, mock_page, mock_agent_api):
    mock_agent_api.verification_code.return_value = {"code": ""}
    session = make_session(agent_api=mock_agent_api)
    session._fill_verification_code = MagicMock()
    result = session._try_poll_and_fill_verification_code(mock_page, timeout_seconds=2)
    assert result is False
    session._fill_verification_code.assert_not_called()


def test_continues_through_api_errors(make_session, mock_page, mock_agent_api):
    mock_agent_api.verification_code.side_effect = [
        ApiError("transient"),
        {"code": ""},
        {"code": "654321"},
    ]
    session = make_session(agent_api=mock_agent_api)
    session._fill_verification_code = MagicMock()
    result = session._try_poll_and_fill_verification_code(mock_page, timeout_seconds=10)
    assert result is True
    session._fill_verification_code.assert_called_once_with(mock_page, "654321")


def test_returns_false_on_stop_requested(make_session, mock_page, mock_agent_api):
    mock_agent_api.verification_code.return_value = {"code": "777777"}
    session = make_session(agent_api=mock_agent_api)
    session._fill_verification_code = MagicMock()
    session.stop_requested = True
    result = session._try_poll_and_fill_verification_code(mock_page, timeout_seconds=10)
    assert result is False
    session._fill_verification_code.assert_not_called()


def test_logs_stuck_when_no_api(make_session, mock_page):
    session = make_session(agent_api=None)
    session._log_stuck = MagicMock()
    result = session._try_poll_and_fill_verification_code(mock_page, timeout_seconds=1)
    assert result is False
    session._log_stuck.assert_called_once()
    assert "邮箱验证码" in session._log_stuck.call_args.args[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_poll_verification_code.py -v`

Expected: `AttributeError: 'BrowserSession' object has no attribute '_try_poll_and_fill_verification_code'`

- [ ] **Step 3: Implement `_try_poll_and_fill_verification_code`**

```python
    def _try_poll_and_fill_verification_code(
        self, page: Page, *, timeout_seconds: int = 90
    ) -> bool:
        """Poll MoEmail until a verification code arrives, then fill it. Returns True on success."""
        api = self._agent_api
        if not api:
            self._log_stuck("邮箱验证码", "未配置后台 Token")
            return False
        customer_id = (self.task or {}).get("customer_id")
        if not customer_id:
            self._log_stuck("邮箱验证码", "缺少 customer_id")
            return False
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.stop_requested:
                return False
            try:
                resp = api.verification_code(int(customer_id))
                code = (resp or {}).get("code") or ""
            except ApiError as exc:
                self.log(f"拉取验证码失败：{exc}")
                time.sleep(2)
                continue
            if code:
                self._fill_verification_code(page, code)
                return True
            time.sleep(2)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_poll_verification_code.py -v`

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add desktop-client/giffgaff_client/automation.py desktop-client/tests/test_poll_verification_code.py
git commit -m "feat(automation): add _try_poll_and_fill_verification_code"
```

---

## Task 10: Test + implement `_auto_run_until_payment` orchestrator

**Files:**
- Modify: `desktop-client/giffgaff_client/automation.py`
- Create: `desktop-client/tests/test_auto_run_until_payment.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auto_run_until_payment.py
from unittest.mock import MagicMock


def _page_with_text(text: str) -> MagicMock:
    page = MagicMock()
    page.url = "https://www.giffgaff.com/activate"
    page.locator.return_value.inner_text.return_value = text
    return page


def test_stops_on_payment_page(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Card details - payment"
    session = make_session()
    session._auto_run_until_payment(mock_page)
    assert session.payment_page_seen is True
    assert any("付款页" in line for line in session.log_lines)


def test_stops_on_unknown_page(make_session, mock_page):
    mock_page.url = "https://www.giffgaff.com/foo"
    mock_page.locator.return_value.inner_text.return_value = "Random unrelated page"
    session = make_session()
    session._auto_run_until_payment(mock_page)
    assert any("未知页面" in line for line in session.log_lines)


def test_stops_immediately_when_stop_requested(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Choose a monthly plan"
    session = make_session()
    session.stop_requested = True
    session._choose_pay_as_you_go = MagicMock()
    session._auto_run_until_payment(mock_page)
    session._choose_pay_as_you_go.assert_not_called()


def test_dispatches_to_password_handler(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Create a password"
    session = make_session()
    session._continue_after_password_if_visible = MagicMock()
    # First iteration dispatches to password, second iteration we set stop
    def stop_after_first(_):
        session.stop_requested = True
    session._continue_after_password_if_visible.side_effect = stop_after_first
    session._auto_run_until_payment(mock_page)
    session._continue_after_password_if_visible.assert_called_once()


def test_dispatches_to_stay_in_touch_handler(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Let's stay in touch"
    session = make_session()
    session._continue_registration_preferences = MagicMock(side_effect=lambda p: setattr(session, "stop_requested", True))
    session._auto_run_until_payment(mock_page)
    session._continue_registration_preferences.assert_called_once()


def test_dispatches_to_payg_handler(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Choose a monthly plan"
    session = make_session()
    session._choose_pay_as_you_go = MagicMock(return_value=True)
    session._auto_run_until_payment(mock_page)
    session._choose_pay_as_you_go.assert_called_once()


def test_dispatches_to_verification_handler(make_session, mock_page, mock_agent_api):
    mock_page.locator.return_value.inner_text.return_value = "Confirm your email"
    session = make_session(agent_api=mock_agent_api)
    session._try_poll_and_fill_verification_code = MagicMock(return_value=True)
    session._auto_run_until_payment(mock_page)
    session._try_poll_and_fill_verification_code.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_auto_run_until_payment.py -v`

Expected: `AttributeError: 'BrowserSession' object has no attribute '_auto_run_until_payment'`

- [ ] **Step 3: Implement `_auto_run_until_payment`**

```python
    def _auto_run_until_payment(self, page: Page) -> None:
        """Drive activation flow until payment page. Stops on payment, stuck, or stop_requested."""
        while not self.stop_requested:
            if self._page_has_text(page, [r"Payment", r"Card details"]):
                self.log("已到达付款页，停止自动化。请人工填写信用卡信息并完成支付。")
                self.payment_page_seen = True
                return

            if self._page_has_text(page, [r"Confirm your email", r"Enter verification code"]):
                if not self._try_poll_and_fill_verification_code(page):
                    self._log_stuck("邮箱验证码", "拉取 90s 未拿到")
                    return
                continue

            if self._page_has_text(page, [r"Create a password", r"Your password"]):
                password = str((self.task or {}).get("initial_password") or "")
                if not password:
                    self._log_stuck("密码页", "客户档案缺少 initial_password")
                    return
                self._continue_after_password_if_visible(page, password)
                continue

            if self._page_has_text(page, [r"Let's stay in touch", r"Yes, please", r"No, thanks"]):
                self._continue_registration_preferences(page)
                continue

            if self._page_has_text(page, [r"Choose a monthly plan", r"Other options", r"Pay as you go"]):
                if not self._choose_pay_as_you_go(page):
                    self._log_stuck("选套餐", "Pay as you go 选择 3 次均失败")
                    return
                continue

            if self._page_has_text(page, [r"Add credit", r"How much credit"]):
                self._choose_topup_amount(page)
                continue

            if self._page_has_text(page, [r"Your details", r"First name", r"Postcode"]):
                self._fill_details_and_continue(page)
                continue

            url = page.url or ""
            if "/dashboard" in url:
                self.log("已到达 dashboard，等待跳转下一步...")
                self._wait_short(page, 2)
                continue

            self._log_stuck("未知页面", f"URL={url}")
            return
```

**Note**: The orchestrator references `_wait_short`, which may not exist in the current code. If it doesn't, add a minimal stub:

```python
    def _wait_short(self, page: Page, seconds: float) -> None:
        """Brief wait for page transitions."""
        time.sleep(seconds)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop-client && .venv/bin/python -m pytest tests/test_auto_run_until_payment.py -v`

Expected: `7 passed`

- [ ] **Step 5: Run full test suite**

Run: `cd desktop-client && .venv/bin/python -m pytest -v`

Expected: All previous + 7 new tests pass.

- [ ] **Step 6: Commit**

```bash
git add desktop-client/giffgaff_client/automation.py desktop-client/tests/test_auto_run_until_payment.py
git commit -m "feat(automation): add _auto_run_until_payment orchestrator"
```

---

## Task 11: Modify `BrowserSession.run` to call orchestrator

**Files:**
- Modify: `desktop-client/giffgaff_client/automation.py` (in `BrowserSession.run`)

- [ ] **Step 1: Find the existing `run` method**

Read `automation.py` to find the body of `BrowserSession.run` (the method that starts the Playwright browser and calls `_open_and_prefill`).

- [ ] **Step 2: Insert orchestrator call**

After the call to `self._open_and_prefill(page)` and before entering `_command_loop`, add:

```python
            if self.config.full_auto:
                self.log("已进入全自动模式，无需手动点击；可用「停止自动化」按钮随时中断。")
                self._auto_run_until_payment(page)
```

The modified method should look approximately like:

```python
    def run(self) -> None:
        user_data_dir = Path(self.config.user_data_dir).expanduser()
        user_data_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser_type = self._resolve_browser_type(playwright)
            launch_options = self._build_launch_options()
            context = browser_type.launch_persistent_context(user_data_dir=str(user_data_dir), **launch_options)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                self._open_and_prefill(page)
                if self.config.full_auto:
                    self.log("已进入全自动模式，无需手动点击；可用「停止自动化」按钮随时中断。")
                    self._auto_run_until_payment(page)
                self.log("浏览器已保持打开。你可以手动接管页面，或在客户端里继续操作。")
                self._command_loop(page)
            finally:
                self.log("关闭浏览器会话...")
                context.close()
```

(Adjust to match the actual existing structure of `run` — keep all existing logic, only insert the `if self.config.full_auto:` block.)

- [ ] **Step 3: Verify nothing broke**

Run: `cd desktop-client && .venv/bin/python -c "from giffgaff_client.automation import BrowserSession; print('import ok')"`

Expected: `import ok`

- [ ] **Step 4: Run full test suite**

Run: `cd desktop-client && .venv/bin/python -m pytest -v`

Expected: All tests still pass.

- [ ] **Step 5: Commit**

```bash
git add desktop-client/giffgaff_client/automation.py
git commit -m "feat(automation): hook orchestrator into BrowserSession.run"
```

---

## Task 12: Modify `_command_loop` to poll for phone number

**Files:**
- Modify: `desktop-client/giffgaff_client/automation.py` (in `BrowserSession._command_loop`)

- [ ] **Step 1: Locate `_command_loop`**

Read `automation.py` to find the existing `_command_loop` method.

- [ ] **Step 2: Modify the empty-queue branch**

Find the part of `_command_loop` that runs when `self.commands.get(timeout=...)` raises `queue.Empty`. Add phone-number polling logic before any existing idle behavior.

The modified shape:

```python
    def _command_loop(self, page: Page) -> None:
        phone_reported = False
        while not self.stop_requested:
            try:
                command = self.commands.get(timeout=0.25)
            except queue.Empty:
                if self.payment_page_seen and not phone_reported:
                    phone = self._wait_and_extract_phone_number(page, timeout_seconds=3)
                    if phone:
                        self._report_phone_number_to_backend(phone)
                        phone_reported = True
                        self.stop_requested = True  # exit cleanly
                        break
                self._auto_remove_saved_card_if_ready(page)
                continue
            if command.name == "stop":
                self.stop_requested = True
                break
            # ... existing command handlers unchanged
```

(If `phone_reported` tracking conflicts with existing logic, place the variable inside the existing `_command_loop` body, scoped appropriately. The key invariant: after phone is reported, the loop exits within one iteration.)

- [ ] **Step 3: Run test suite**

Run: `cd desktop-client && .venv/bin/python -m pytest -v`

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add desktop-client/giffgaff_client/automation.py
git commit -m "feat(automation): poll for phone number in _command_loop"
```

---

## Task 13: Add `auto_running` state + stop button to main window

**Files:**
- Modify: `desktop-client/giffgaff_client/main_window.py`

- [ ] **Step 1: Find the existing `_build_task_group` (or similar) method**

Read `main_window.py` to find where the existing buttons "打开并预填", "刷新验证码", "填入验证码", "继续当前页面" are constructed.

- [ ] **Step 2: Add `auto_running` instance variable**

In `MainWindow.__init__` (or near where other state vars are initialized), add:

```python
        self.auto_running = False
```

- [ ] **Step 3: Add `stop_automation` method**

Add a method that sends the stop signal:

```python
    def stop_automation(self) -> None:
        if self.browser_worker and self.browser_worker.isRunning():
            self.browser_worker.stop()
            self.log("已发送停止自动化指令。等待当前步骤完成后退出...")
            self.stop_button.setEnabled(False)
        else:
            self.log("浏览器未运行，无需停止。")
```

- [ ] **Step 4: Build the stop button**

In the same panel where the other task buttons live, add:

```python
        self.stop_button = QPushButton("停止自动化")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_automation)
        # ...add to layout alongside other buttons...
```

(Adjust layout code to match existing style.)

- [ ] **Step 5: Add enable/disable logic**

In the handler that starts the browser worker (likely called by "打开并预填"), set:

```python
        self.auto_running = True
        self.stop_button.setEnabled(True)
        self.prefill_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.fill_button.setEnabled(False)
        self.continue_button.setEnabled(False)
```

In the handler that runs when the browser worker finishes (likely in `BrowserWorker.finished.connect(...)` or similar), set:

```python
        self.auto_running = False
        self.stop_button.setEnabled(False)
        self.prefill_button.setEnabled(True)
        # Refresh / Fill / Continue are conditionally re-enabled
        # based on whether current_task is still set
        self.refresh_button.setEnabled(self.current_task is not None)
        self.fill_button.setEnabled(bool(self.last_code))
        self.continue_button.setEnabled(self.current_task is not None)
```

(Adjust method/variable names to match the existing code structure.)

- [ ] **Step 6: Verify import surface**

Run: `cd desktop-client && .venv/bin/python -c "from giffgaff_client.main_window import MainWindow; print('import ok')"`

Expected: `import ok`

- [ ] **Step 7: Run full test suite**

Run: `cd desktop-client && .venv/bin/python -m pytest -v`

Expected: All tests still pass (these are pure UI changes; existing tests don't touch main_window).

- [ ] **Step 8: Commit**

```bash
git add desktop-client/giffgaff_client/main_window.py
git commit -m "feat(ui): add stop automation button and enable/disable logic"
```

---

## Task 14: Update README

**Files:**
- Modify: `desktop-client/README.md`

- [ ] **Step 1: Add a new section after the existing "使用说明"**

Find the section that currently explains the half-automatic flow and add a new section:

```markdown
## 全自动模式（v1.1+）

默认开启。点击「打开并预填」后，客户端会自动驱动以下步骤：
- 填写 SIM 码 + 邮箱 + 密码
- 轮询 MoEmail 邮箱，拉取 6 位验证码并自动填入
- 选择「No, thanks」+ Continue（注册偏好页）
- 选择 Pay as you go（最多重试 3 次）
- 选择充值金额
- 填写详细地址
- 到达付款页后停下

中途随时可点 **「停止自动化」** 按钮中断。停止后按钮恢复可点。

付款完成后，客户端会轮询页面寻找分配给你的 giffgaff 手机号（`07XXXXXXXXX`），抓到后自动回传到后台并将任务状态置为「等待转 eSIM」。

### 卡住行为

每种「卡住」会在 UI 日志里输出具体 step 名，例如：

> 【卡住】选套餐 — Pay as you go 选择 3 次均失败。请人工处理后点「继续当前页面」恢复。

后台任务不会被自动标为失败 — 由人工决定继续 / 失败 / 重试。

### 关闭全自动

在配置文件 `config.json` 中将 `full_auto` 设为 `false` 即可退回半自动模式：

```json
{
  ...
  "full_auto": false
}
```
```

- [ ] **Step 2: Commit**

```bash
git add desktop-client/README.md
git commit -m "docs: document full-auto mode and stop button"
```

---

## Task 15: Final integration smoke test

This task verifies everything wired together.

- [ ] **Step 1: Run full test suite**

Run: `cd desktop-client && .venv/bin/python -m pytest -v`

Expected: All tests pass. Note the count — should be roughly 30+ tests.

- [ ] **Step 2: Smoke-test the GUI loads**

Run: `cd desktop-client && timeout 10 .venv/bin/python -c "
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication
from giffgaff_client.main_window import MainWindow
app = QApplication([])
w = MainWindow()
print('window opened')
print('stop button:', w.stop_button.text())
print('auto_running:', w.auto_running)
print('stop button enabled:', w.stop_button.isEnabled())
" || echo "GUI load may need display — non-fatal if QT_QPA_PLATFORM error"`

Expected: `window opened`, `stop button: 停止自动化`, `auto_running: False`, `stop button enabled: False`

- [ ] **Step 3: Manual end-to-end against real giffgaff**

In `desktop-client`:

```bash
.venv/bin/python run.py
```

Expected flow:
1. Connect to backend with CF Service Token
2. Claim a real activation task
3. Click "Open & prefill" — observe log: "已进入全自动模式..."
4. Wait 30-90s while automation runs through steps
5. Reach payment page — observe log: "已到达付款页..."
6. Manually pay with your own card
7. Wait ~30s — observe log: "已回传手机号 ... 到后台"
8. Client exits cleanly

If any step fails, capture the log line and report it.

- [ ] **Step 4: Final commit (if any straggling fixes)**

```bash
git status
# If anything is dirty:
git add -A && git commit -m "chore: integration fixes from smoke test"
```

---

## Self-Review

- **Spec coverage**:
  - §3.1 `full_auto` → Task 1 ✓
  - §3.2.1 `PHONE_NUMBER_PATTERN` → Task 5 ✓
  - §3.2.2 `_choose_pay_as_you_go` retry → Task 8 ✓
  - §3.2.3 `_try_poll_and_fill_verification_code` → Task 9 ✓
  - §3.2.4 `_auto_run_until_payment` → Task 10 ✓
  - §3.2.5 `_log_stuck` → Task 4 ✓
  - §3.2.6 `_wait_and_extract_phone_number` → Task 6 ✓
  - §3.2.7 `_page_text` → Task 3 ✓
  - §3.2.8 `_report_phone_number_to_backend` → Task 7 ✓
  - §3.2.9 `run()` modification → Task 11 ✓
  - §3.2.10 `_command_loop` modification → Task 12 ✓
  - §3.3.1-3.3.4 UI changes → Task 13 ✓
  - §3.4 Tests → Tasks 3-10 cover all required test files ✓
  - README update → Task 14 ✓

- **Placeholder scan**: No TBD / TODO. Every step has concrete code or concrete commands.

- **Type consistency**: `update_result` (not `update_activation_result`) used throughout — matches the real AgentApi signature. `customer_id`, `phone`, `status` types consistent.

- **Open question resolution**: Spec §6 mentioned verifying `update_activation_result` signature; plan correctly uses `update_result` after inspection.