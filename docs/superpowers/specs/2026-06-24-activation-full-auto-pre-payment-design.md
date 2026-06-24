# 激活客户端全自动流程(到付款页前)+ 选 plan 重试 + 手机号抓取 — Design

**Status**: Draft, awaiting user review
**Date**: 2026-06-24
**Scope**: Desktop-client only. No backend changes. No DB schema changes. No giffgaff API changes.

## 1. Background & Goals

### Problem
The existing Giffgaff Activation Client is a half-automatic tool. The user must click multiple buttons to drive a single activation:

1. Click "Open & prefill" → fills SIM code + email
2. Click "Refresh code" → manually pull MoEmail verification code
3. Click "Fill code" → fills the code into the page
4. Click "Continue current page" → walks through stay_in_touch
5. Click "Continue current page" again → reaches plan selection
6. If `_choose_pay_as_you_go` fails, the script logs a warning and **does not retry**
7. After payment, giffgaff displays `Here's your giffgaff number: 07732 212776`, but the client **does not extract this number** and does not report it back to the backend

### Goal
After clicking "Open & prefill", the client should run **fully automatically** until the payment page, then enter a passive loop that:

- Continuously watches the page for the assigned giffgaff phone number
- Reports the number back to the backend as soon as it appears
- Auto-removes the saved credit card (existing behavior, preserved)

The user should only need to:
- Click "Open & prefill" once
- Optionally click "Stop automation" to interrupt
- Manually complete the payment (card details, 3-D Secure, eSIM conversion)

## 2. Out of Scope

- No changes to backend, DB schema, or giffgaff API
- No changes to the credit-card auto-fill behavior (already disabled by user — manual payment)
- No changes to MoEmail polling API contract (uses existing `/api/agent/customers/{id}/verification-code`)
- No changes to the existing `_open_and_prefill` shape (only adds a follow-up call)
- No changes to the `_remove_saved_card` flow (already works; we just wait for it)

## 3. Component Changes

### 3.1 `desktop-client/giffgaff_client/config.py`

Add a single field to `AppConfig`:

```python
full_auto: bool = True
```

**Backward compatibility**: When `load_config()` reads an old `config.json` that lacks `full_auto`, dataclass default `True` applies. No migration needed.

### 3.2 `desktop-client/giffgaff_client/automation.py`

#### 3.2.1 New module-level constant

```python
PHONE_NUMBER_PATTERN = re.compile(r"\b07\d{3}[\s-]?\d{6}\b")
```

Matches UK mobile numbers like `07732 212776`, `07732212776`, `07732-212776`. Word-boundary anchored to avoid matching other 11-digit strings.

#### 3.2.2 Modify `_choose_pay_as_you_go` — add retry

Current behavior: tries once, logs and returns.

New behavior: tries up to 3 times, returns `bool`.

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

#### 3.2.3 New `_try_poll_and_fill_verification_code`

```python
def _try_poll_and_fill_verification_code(self, page: Page, *, timeout_seconds: int = 90) -> bool:
    """Poll MoEmail until a verification code arrives, then fill it. Returns True on success."""
    api = self._agent_api()
    if not api:
        self._log_stuck("邮箱验证码", "未配置后台 Token")
        return False
    customer_id = int(self.task["customer_id"])
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if self.stop_requested:
            return False
        try:
            code = api.verification_code(customer_id)
        except ApiError as exc:
            self.log(f"拉取验证码失败：{exc}")
            time.sleep(3)
            continue
        if code:
            self._fill_verification_code(page, code)
            return True
        time.sleep(3)
    return False
```

#### 3.2.4 New `_auto_run_until_payment`

The main full-auto orchestrator. Walks the page in a loop, dispatches to per-step handlers, and returns when it reaches the payment page or gets stuck.

```python
def _auto_run_until_payment(self, page: Page) -> None:
    """Drive the activation flow from email-submit state to payment page. Stops on payment, on stuck, or on user request."""
    last_action = None
    while not self.stop_requested:
        if self._page_has_text(page, [r"Payment", r"Card details"]):
            self.log("已到达付款页，停止自动化。请人工填写信用卡信息并完成支付。")
            self.payment_page_seen = True
            return

        if self._page_has_text(page, [r"Confirm your email", r"Enter verification code"]):
            if not self._try_poll_and_fill_verification_code(page):
                self._log_stuck("邮箱验证码", "拉取 90s 未拿到")
                return
            last_action = "code_filled"
            continue

        if self._page_has_text(page, [r"Create a password", r"Your password"]):
            password = str(self.task.get("initial_password") or "")
            if not password:
                self._log_stuck("密码页", "客户档案缺少 initial_password")
                return
            self._continue_after_password_if_visible(page, password)
            last_action = "password_filled"
            continue

        if self._page_has_text(page, [r"Let's stay in touch", r"Yes, please", r"No, thanks"]):
            self._continue_registration_preferences(page)
            last_action = "stay_in_touch"
            continue

        if self._page_has_text(page, [r"Choose a monthly plan", r"Other options", r"Pay as you go"]):
            if not self._choose_pay_as_you_go(page):
                self._log_stuck("选套餐", "Pay as you go 选择 3 次均失败")
                return
            last_action = "plan_chosen"
            continue

        if self._page_has_text(page, [r"Add credit", r"How much credit"]):
            self._choose_topup_amount(page)
            last_action = "topup_chosen"
            continue

        if self._page_has_text(page, [r"Your details", r"First name", r"Postcode"]):
            self._fill_details_and_continue(page)
            last_action = "details_filled"
            continue

        url = page.url or ""
        if "/dashboard" in url:
            self.log("已到达 dashboard，等待跳转下一步...")
            self._wait_short(page, 2)
            continue

        # Unknown page → log and stop
        self._log_stuck("未知页面", f"URL={url}")
        return
```

#### 3.2.5 New `_log_stuck`

```python
def _log_stuck(self, step: str, reason: str) -> None:
    """Log a structured 'stuck' event. Does NOT mark the backend task as failed."""
    message = f"【卡住】{step} — {reason}。请人工处理后点「继续当前页面」恢复。"
    self.log(message)
    api = self._agent_api()
    if api and self.task.get("customer_id"):
        try:
            api.add_log(int(self.task["customer_id"]), message, step="auto_stuck")
        except (ApiError, ValueError, TypeError):
            pass
```

#### 3.2.6 New `_wait_and_extract_phone_number`

```python
def _wait_and_extract_phone_number(self, page: Page, *, timeout_seconds: int = 180) -> str:
    """Poll the page for a UK mobile number. Returns the 11-digit number, or empty string on timeout/stop."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if self.stop_requested:
            return ""
        try:
            text = self._page_text(page)
        except (PlaywrightError, PlaywrightTimeoutError):
            time.sleep(2)
            continue
        match = PHONE_NUMBER_PATTERN.search(text)
        if match:
            digits = re.sub(r"\D", "", match.group(0))
            if digits.startswith("07") and len(digits) >= 11:
                return digits[:11]
        time.sleep(3)
    return ""
```

#### 3.2.7 New `_page_text`

A thin wrapper that returns the visible text of the main frame (and falls back to body inner_text), avoiding the per-step timeout machinery used by `_page_has_text`.

```python
def _page_text(self, page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=2000)
    except (PlaywrightError, PlaywrightTimeoutError):
        return ""
```

#### 3.2.8 New `_report_phone_number_to_backend`

```python
def _report_phone_number_to_backend(self, phone: str) -> None:
    """Push the captured phone number to the backend and mark the task as 等待转 eSIM."""
    api = self._agent_api()
    customer_id = self.task.get("customer_id")
    if not customer_id:
        self.log(f"未配置 customer_id，仅本地记录手机号：{phone}")
        return
    if not api:
        self.log(f"未配置后台 Token，仅本地记录手机号：{phone}")
        return
    try:
        api.update_activation_result(int(customer_id), {
            "phone_number": phone,
            "activation_status": "等待转 eSIM",
        })
        self.log(f"已回传手机号 {phone} 到后台，状态：等待转 eSIM")
    except ApiError as exc:
        self.log(f"回传手机号失败：{exc}")
```

**Note**: `update_activation_result` is an existing method on `AgentApi`. Spec relies on its accepting `phone_number` and `activation_status` — both already part of `ActivationTaskOut`. If the existing method has a stricter signature, we adapt the call to whatever method already exists (see §6 Risks).

#### 3.2.9 Modify `BrowserSession.run`

After `_open_and_prefill` finishes (which already fills SIM + email + clicks Next on the email page), if `config.full_auto`, kick off `_auto_run_until_payment`:

```python
def run(self) -> None:
    user_data_dir = Path(self.config.user_data_dir).expanduser()
    user_data_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        # ... (unchanged launch_options + browser launch)

        context = browser_type.launch_persistent_context(...)
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

#### 3.2.10 Modify `_command_loop` — add phone-number polling

Inside the `queue.Empty` branch, after `self.payment_page_seen` becomes True, poll for the phone number in the background. Once found, report it back and **break the loop** so the worker exits cleanly.

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
                    break
            self._auto_remove_saved_card_if_ready(page)
            continue
        if command.name == "stop":
            self.stop_requested = True
            break
        # ... (existing command handlers unchanged)
```

`timeout_seconds=3` so each idle iteration is bounded; the loop checks `payment_page_seen` again on the next iteration. Total wait time is unbounded as long as the worker is alive — capped by user stopping or the giffgaff page actually showing the number.

### 3.3 `desktop-client/giffgaff_client/main_window.py`

#### 3.3.1 New state flag

```python
self.auto_running: bool = False
```

Set to `True` when `_auto_run_until_payment` starts, `False` when it returns (regardless of outcome).

#### 3.3.2 New `stop_automation` handler

```python
def stop_automation(self) -> None:
    if self.browser_worker:
        self.browser_worker.stop()
        self.log("已发送停止自动化指令。等待当前步骤完成后退出...")
    else:
        self.log("浏览器未运行，无需停止。")
```

`BrowserWorker.stop` already exists and calls `self.session.stop()`, which sets `stop_requested = True` and enqueues a `stop` command.

#### 3.3.3 UI button placement

Add a single new button next to the existing "Open & prefill" button:

| Button | Visible when | Enabled when |
|---|---|---|
| **停止自动化** (new) | `browser_worker is not None` | `auto_running is True` |
| 打开并预填 (existing) | always | `current_task is not None and not auto_running` |
| 刷新验证码 (existing) | `current_task is not None` | `not auto_running` |
| 填入验证码 (existing) | `last_code != ""` | `not auto_running` |
| 继续当前页面 (existing) | `current_task is not None` | `not auto_running` |

#### 3.3.4 State transitions

`_on_browser_started` (or wherever we kick off `_open_and_prefill`):
- Set `self.auto_running = True`
- Apply enable/disable to all task buttons
- Show 「停止自动化」 button

`_on_browser_stopped` (existing handler):
- Set `self.auto_running = False`
- Re-enable all task buttons
- Hide 「停止自动化」 button

### 3.4 Tests

#### 3.4.1 Unit test: `_choose_pay_as_you_go` retries

`tests/test_auto_payg_retry.py`:

- Mock page where `_try_click_text` fails twice then succeeds on 3rd attempt
- Verify `_choose_pay_as_you_go` returns True after 3 attempts

#### 3.4.2 Unit test: `_wait_and_extract_phone_number`

`tests/test_phone_extract.py`:

- Mock page body text `"Your giffgaff number is 07732 212776"` → returns `"07732212776"`
- Mock page body text `"07732 212776 / 07733 212777"` (two numbers) → returns first match `"07732212776"` (or document chosen behavior)
- Mock page with no number → returns `""` after deadline
- Mock page with `12345678901` (no `07` prefix) → not matched, returns `""`

#### 3.4.3 Unit test: `_report_phone_number_to_backend`

`tests/test_report_phone.py`:

- Mock `AgentApi.update_activation_result` → verify called with `phone_number` and `activation_status='等待转 eSIM'`
- Mock `AgentApi` raises `ApiError` → verify caught, log line emitted

#### 3.4.4 Integration smoke (manual)

Run the client against a real giffgaff account. Expected sequence:

1. Click "Open & prefill" → SIM code, email, password filled in
2. Client auto-clicks Next → reaches `/auth/register/validate-email`
3. Client polls MoEmail, receives code within 30s, fills it
4. Client submits → reaches `/auth/register/stay_in_touch`
5. Client clicks "No, thanks" + Continue
6. Client reaches `/auth/register/pay-monthly` (or similar)
7. Client clicks "Pay as you go" (retries up to 3 times if needed)
8. Client reaches topup amount page → clicks £10 + Pay now
9. Client reaches details page → fills first/last/postcode + address
10. Client reaches **payment page** → stops, log: "已到达付款页，停止自动化..."
11. User pays manually with own card
12. After ~30s, giffgaff shows "Here's your giffgaff number: 07732 212776"
13. Client detects, logs "已回传手机号 07732212776 到后台", exits cleanly

## 4. State Machine

```
[Idle]
   │ user clicks "Open & prefill"
   ▼
[Auto-running]
   │   auto_running = True
   │   BrowserWorker starts, _open_and_prefill runs
   │   then _auto_run_until_payment runs:
   │     loop:
   │       payment page?        → exit to [Payment-stopped]
   │       email code page?     → poll MoEmail, fill, continue
   │       password page?       → fill password, continue
   │       stay_in_touch page?  → "No, thanks" + Continue
   │       plan page?           → click "Pay as you go" (retry 3×)
   │       topup page?          → click £10 + Pay now
   │       details page?        → fill address
   │       dashboard?           → wait
   │       unknown?             → log stuck, exit to [Stuck]
   │       stop_requested?      → exit to [Idle]
   ▼
[Payment-stopped]  payment_page_seen = True
   │ _command_loop:
   │   every 0.25s check queue
   │   on Empty:
   │     poll page for 3s for phone number
   │     found → call _report_phone_number_to_backend, exit to [Done]
   │     not found → continue polling
   │   user clicks "Stop automation" → stop_requested = True → exit to [Idle]
   ▼
[Done]
   worker exits, browser closes
   backend task: phone_number filled, status='等待转 eSIM'

[Stuck]
   worker stays alive (no exit), browser still open
   user can click "Continue current page" or "Refresh code" to recover
   auto_running = False, all buttons re-enabled
   user finishes manually

[Idle]
   auto_running = False, all buttons in normal state
```

## 5. Risk Analysis

| Risk | Severity | Mitigation |
|---|---|---|
| Phone number regex matches an unrelated 11-digit string on the page | Medium | Pattern is anchored with `\b` and requires `07` prefix; further gated by `digits.startswith("07") and len(digits) >= 11` |
| Payment success page takes > 3 min to load the number | Low | `timeout_seconds=180` default; user can stop and recover |
| `_auto_run_until_payment` infinite loop if page text matches no pattern and URL changes | Medium | Every iteration includes `if self.stop_requested`; unknown pages log and exit, not loop |
| `_choose_pay_as_you_go` retries on already-clicked button and triggers double-navigation | Low | After successful click + continue, `_wait_ready` lets the page transition out of plan selection before re-evaluation |
| `update_activation_result` doesn't accept `activation_status` in one call | Medium | Use existing method's signature; if it requires two calls, call `update_status` then `update_phone` separately (see §6) |
| `full_auto=True` becomes default — old users surprised by absence of buttons | Low | Buttons re-enable when automation ends; "Stop automation" always visible while running; README documents this |
| giffgaff changes page copy / DOM | Medium | Fuzzy `_page_has_text` patterns are already tolerant; `stay_in_touch` and plan text patterns match multiple variants |
| Poll loop blocks the `_command_loop` and delays user-initiated "Stop" | Low | `stop_requested` checked at top of every iteration; polling uses `timeout=3` per call to keep responsiveness |

## 6. Open Questions Resolved by Code Inspection

These will be checked during plan execution; if any check fails, the corresponding code change adapts:

- `AgentApi.update_activation_result` exact signature → ensure phone_number + activation_status can be set in one call, otherwise split into two calls
- `AgentApi.add_log` exact signature → already used in `_payment_info_email_snapshot`, so format is known
- Whether `verification_code` returns empty string vs None when no email → use truthy check

## 7. Implementation Order

The plan (in the next phase) will follow this order, with each step preceded by a failing test:

1. Add `full_auto` to `AppConfig` (no logic change yet)
2. Modify `_choose_pay_as_you_go` for retry
3. Add `_page_text` helper
4. Add `_wait_and_extract_phone_number` + tests
5. Add `_log_stuck` helper
6. Add `_try_poll_and_fill_verification_code` + tests
7. Add `_auto_run_until_payment` (orchestrator)
8. Add `_report_phone_number_to_backend` + tests
9. Modify `BrowserSession.run` to call orchestrator when `full_auto`
10. Modify `_command_loop` to poll for phone number
11. UI: add `auto_running` flag + 「停止自动化」 button + enable/disable logic
12. README update
13. Manual E2E test on real giffgaff account

## 8. Files Changed

| File | Change type | Lines (estimate) |
|---|---|---|
| `desktop-client/giffgaff_client/config.py` | modify | +2 |
| `desktop-client/giffgaff_client/automation.py` | modify | +120, -10 |
| `desktop-client/giffgaff_client/main_window.py` | modify | +40, -10 |
| `desktop-client/tests/test_auto_payg_retry.py` | new | +60 |
| `desktop-client/tests/test_phone_extract.py` | new | +50 |
| `desktop-client/tests/test_report_phone.py` | new | +40 |
| `desktop-client/README.md` | modify | +20 |
| **Total** | | **~330 lines** |

## 9. Success Criteria

- User clicks "Open & prefill" once and walks away
- Client drives SIM code → email → code → password → preferences → plan → topup → address → payment page without further input
- Each step is logged in the client log with a `step name`
- If a step fails 3 times (plan) or times out (code poll), client logs `【卡住】{step} — {reason}` and waits for user
- User clicks "Stop automation" → current step completes, then worker exits
- After payment, phone number `07XXXXXXXXX` is auto-extracted and reported to backend within 3 min
- Backend task status changes to `等待转 eSIM` with `phone_number` filled