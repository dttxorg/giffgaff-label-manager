from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import queue
import re
import time
from typing import Callable, Iterable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .api import AgentApi, ApiError
from .config import AppConfig


LogCallback = Callable[[str], None]


@dataclass
class BrowserCommand:
    name: str
    value: str = ""


class BrowserSession:
    def __init__(self, config: AppConfig, task: dict, log: LogCallback):
        self.config = config
        self.task = task
        self.log = log
        self.commands: queue.Queue[BrowserCommand] = queue.Queue()
        self.stop_requested = False
        self.payment_page_seen = False
        self.saved_card_removed = False

    def enqueue(self, command: BrowserCommand) -> None:
        self.commands.put(command)

    def stop(self) -> None:
        self.stop_requested = True
        self.commands.put(BrowserCommand("stop"))

    def run(self) -> None:
        user_data_dir = Path(self.config.user_data_dir).expanduser()
        user_data_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            launch_options = {
                "headless": self.config.headless,
                "slow_mo": max(0, int(self.config.slow_mo_ms or 0)),
            }
            proxy = self.config.proxy.playwright_proxy()
            if proxy:
                launch_options["proxy"] = proxy
                self.log(f"使用代理：{proxy['server']}")
            elif self.config.proxy.mode == "system":
                self.log("使用系统代理模式：浏览器将按系统/浏览器默认网络环境启动")

            browser_type = playwright.chromium
            channel = (self.config.browser_channel or "").strip()
            if channel and channel != "chromium":
                launch_options["channel"] = channel

            self.log("启动浏览器...")
            context = browser_type.launch_persistent_context(str(user_data_dir), **launch_options)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                self._open_and_prefill(page)
                self.log("浏览器已保持打开。你可以手动接管页面，或在客户端里继续刷新/填入验证码。")
                self._command_loop(page)
            finally:
                self.log("关闭浏览器会话...")
                context.close()

    def _command_loop(self, page: Page) -> None:
        while not self.stop_requested:
            try:
                command = self.commands.get(timeout=0.25)
            except queue.Empty:
                self._auto_remove_saved_card_if_ready(page)
                continue
            if command.name == "stop":
                self.stop_requested = True
                break
            try:
                if command.name == "fill_code":
                    self._fill_verification_code(page, command.value)
                elif command.name == "continue":
                    self._continue_from_current_page(page)
                elif command.name == "remove_card":
                    self._remove_saved_card(page)
            except Exception as exc:
                self.log(f"执行 {command.name} 指令失败：{exc}；浏览器会保持打开，可等待页面稳定后再点“继续当前页面”")

    def _open_and_prefill(self, page: Page) -> None:
        url = self.config.activation_url.strip() or "https://www.giffgaff.com/activate"
        self.log(f"打开激活页面：{url}")
        navigation_timed_out = False
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self._page_timeout())
        except PlaywrightTimeoutError:
            navigation_timed_out = True
            self.log("打开激活页面超时，但浏览器会保持打开；页面加载完成后可点击“继续当前页面”")
        if navigation_timed_out:
            self._wait_short(page, 1)
        else:
            self._wait_ready(page)
        self._maybe_accept_cookies(page)

        sim_code = str(self.task.get("sim_activation_code") or "")
        email = str(self.task.get("email") or "")
        password = str(self.task.get("initial_password") or "")

        if sim_code:
            filled = self._try_fill_any_frame(
                page,
                sim_code,
                labels=[r"activation code", r"SIM code", r"code"],
                placeholders=[r"activation", r"code"],
                selectors=[
                    "input[name*='activation' i]",
                    "input[id*='activation' i]",
                    "input[name*='code' i]",
                    "input[id*='code' i]",
                ],
            )
            self.log("已尝试填写 SIM 激活码" if filled else "未找到 SIM 激活码输入框，请手动填写")
            if filled:
                self._try_click_button(page, [r"continue", r"activate", r"next", r"start"])
                self._wait_ready(page)

        if email:
            filled = self._try_fill_any_frame(
                page,
                email,
                labels=[r"email", r"e-mail"],
                placeholders=[r"email", r"e-mail"],
                selectors=["input[type='email']", "input[name*='email' i]", "input[id*='email' i]"],
            )
            self.log("已尝试填写邮箱" if filled else "未找到邮箱输入框")
            if filled and self._page_has_text(page, [r"What.?s your email address", r"Your email"]):
                if self._try_click_button(page, [r"next"]):
                    self.log("已点击邮箱页 Next，等待邮箱验证码")
                    self._wait_ready(page)

        if password:
            self._continue_after_password_if_visible(page, password)

        address = str(self.task.get("shipping_address") or "")
        if address:
            self.log(f"客户收货地址：{address}")

    def _fill_verification_code(self, page: Page, code: str) -> None:
        code = (code or "").strip()
        if not code:
            self.log("验证码为空，跳过填写")
            return
        filled = self._try_fill_any_frame(
            page,
            code,
            labels=[r"verification code", r"security code", r"code"],
            placeholders=[r"verification", r"security", r"code"],
            selectors=[
                "input[name*='verification' i]",
                "input[id*='verification' i]",
                "input[name*='security' i]",
                "input[id*='security' i]",
                "input[name*='code' i]",
                "input[id*='code' i]",
                "input[inputmode='numeric']",
            ],
        )
        self.log(f"已尝试填写验证码 {code}" if filled else "未找到验证码输入框，请手动填写")
        if filled and self._try_click_button(page, [r"confirm", r"continue", r"next"]):
            self.log("已提交邮箱验证码")
            self._wait_ready(page)
            password = str(self.task.get("initial_password") or "")
            if password:
                self._continue_after_password_if_visible(page, password)

    def _continue_from_current_page(self, page: Page) -> None:
        self.log("开始从当前页面继续自动化...")
        self._wait_ready(page)
        self._maybe_accept_cookies(page)
        sim_code = str(self.task.get("sim_activation_code") or "")
        email = str(self.task.get("email") or "")
        password = str(self.task.get("initial_password") or "")

        if sim_code and self._page_has_text(page, [r"Let's activate your SIM", r"activation code"]):
            filled = self._try_fill_any_frame(
                page,
                sim_code,
                labels=[r"activation code", r"SIM code", r"code"],
                placeholders=[r"activation", r"code"],
                selectors=[
                    "input[name*='activation' i]",
                    "input[id*='activation' i]",
                    "input[name*='code' i]",
                    "input[id*='code' i]",
                ],
            )
            if filled and self._try_click_button(page, [r"activate your SIM", r"continue", r"activate", r"next"]):
                self.log("已从激活码页继续")
                self._wait_ready(page)

        if email and self._page_has_text(page, [r"What.?s your email address", r"Your email"]):
            filled = self._try_fill_any_frame(
                page,
                email,
                labels=[r"email", r"e-mail"],
                placeholders=[r"email", r"e-mail"],
                selectors=["input[type='email']", "input[name*='email' i]", "input[id*='email' i]"],
            )
            if filled and self._try_click_button(page, [r"next"]):
                self.log("已从邮箱页继续，等待验证码页")
                self._wait_ready(page)

        if self._page_has_text(page, [r"Confirm your email", r"Enter verification code"]):
            existing_code = self._first_input_value(
                page,
                [
                    "input[name*='verification' i]",
                    "input[id*='verification' i]",
                    "input[name*='code' i]",
                    "input[id*='code' i]",
                    "input[inputmode='numeric']",
                    "input[type='tel']",
                ],
            )
            if re.search(r"\d{6}", existing_code or ""):
                if self._try_click_button(page, [r"confirm", r"continue", r"next"]):
                    self.log("检测到验证码已填写，已提交并继续")
                    self._wait_ready(page)
            else:
                self.log("当前在邮箱验证码页：请先刷新/填入验证码，再点“继续当前页面”或“填入验证码”")
                return

        if password:
            self._continue_after_password_if_visible(page, password)

        self._continue_registration_preferences(page)
        self._continue_activation_checkout(page)

        if self._page_has_text(page, [r"Payment", r"Card details"]):
            self._fill_payment_details(page)
            return

        self._auto_remove_saved_card_if_ready(page)
        self.log("继续当前页面执行完毕；如页面仍未完成，请等待加载后再次点击“继续当前页面”。")

    def _continue_after_password_if_visible(self, page: Page, password: str) -> None:
        if not self._page_has_text(page, [r"Create a password", r"Your password"]):
            return
        filled = self._try_fill_any_frame(
            page,
            password,
            labels=[r"password"],
            placeholders=[r"password"],
            selectors=["input[type='password']", "input[name*='password' i]", "input[id*='password' i]"],
        )
        self.log("已填写初始密码，已在后台记录" if filled else "未找到密码输入框")
        if filled and self._try_click_button(page, [r"register"]):
            self.log("已点击 Register")
            self._wait_ready(page)
            self._continue_registration_preferences(page)
            self._continue_activation_checkout(page)

    def _continue_registration_preferences(self, page: Page) -> None:
        if not self._page_has_text(page, [r"Let's stay in touch", r"Yes, please", r"No, thanks"]):
            return
        if self._try_click_text(page, [r"No, thanks"]):
            self.log("已选择营销联系偏好：No, thanks")
        self._try_click_button(page, [r"continue"])
        self._wait_ready(page)

    def _continue_activation_checkout(self, page: Page) -> None:
        self._choose_pay_as_you_go(page)
        self._choose_topup_amount(page)
        self._fill_details_and_continue(page)
        self._fill_payment_details(page)

    def _choose_pay_as_you_go(self, page: Page) -> None:
        if not self._page_has_text(page, [r"Choose a monthly plan", r"Other options", r"Pay as you go"]):
            return
        self._try_click_text(page, [r"No monthly plan", r"Pay as you go"])
        self.log("已选择 Pay as you go / No monthly plan")
        if self._try_click_button(page, [r"continue"]):
            self._wait_ready(page)

    def _choose_topup_amount(self, page: Page) -> None:
        if not self._page_has_text(page, [r"Add credit", r"How much credit"]):
            return
        amount = re.sub(r"[^\d]", "", self.config.activation_defaults.topup_amount or "10") or "10"
        self._try_click_text(page, [rf"£\s*{re.escape(amount)}", rf"{re.escape(amount)}"])
        self.log(f"已选择 Pay as you go 充值金额：£{amount}")
        if self._try_click_button(page, [r"pay now"]):
            self._wait_ready(page)

    def _fill_details_and_continue(self, page: Page) -> None:
        defaults = self.config.activation_defaults
        if not self._page_has_text(page, [r"Your details", r"First name", r"Postcode"]):
            return
        first_name = defaults.first_name.strip()
        last_name = defaults.last_name.strip()
        postcode = defaults.postcode.strip()
        if first_name:
            self._try_fill_any_frame(page, first_name, labels=[r"first name"], placeholders=[], selectors=[
                "input[name*='first' i]", "input[id*='first' i]",
            ])
        if last_name:
            self._try_fill_any_frame(page, last_name, labels=[r"last name"], placeholders=[], selectors=[
                "input[name*='last' i]", "input[id*='last' i]",
            ])
        if postcode:
            filled = self._try_fill_any_frame(page, postcode, labels=[r"postcode"], placeholders=[], selectors=[
                "input[name*='postcode' i]", "input[id*='postcode' i]", "input[autocomplete='postal-code']",
            ])
            if filled:
                self.log(f"已填写 UK postcode：{postcode}")
                self._select_address_suggestion(page, max(1, defaults.address_choice_index))
        self._fill_manual_address_fallback(page)
        if self._try_click_button(page, [r"continue"]):
            self.log("已提交开户地址，进入支付页")
            self._wait_ready(page)

    def _select_address_suggestion(self, page: Page, choice_index: int) -> None:
        choice_index = max(1, choice_index)
        deadline = time.monotonic() + self._step_timeout() / 1000
        self._wait_short(page, 1)
        # Prefer clicking a visible Loqate/listbox option. Slow connections can delay this list.
        while time.monotonic() < deadline:
            timeout = self._remaining_timeout(deadline, cap=1200)
            if not timeout:
                break
            try:
                option = page.get_by_role("option").nth(choice_index - 1)
                option.click(timeout=timeout)
                time.sleep(1)
                self.log(f"已点击第 {choice_index} 个地址候选")
                return
            except (PlaywrightError, PlaywrightTimeoutError):
                pass
            try:
                locator = page.locator(
                    "text=/^(?!I cannot find my address)(?!Address line)(?!Postcode).*(,[ ]*)?[A-Z]{1,2}\\d[A-Z\\d]?\\s*\\d[A-Z]{2}$/i"
                ).nth(choice_index - 1)
                locator.click(timeout=timeout)
                time.sleep(1)
                self.log(f"已点击第 {choice_index} 个地址候选")
                return
            except (PlaywrightError, PlaywrightTimeoutError):
                pass
            self._wait_short(page)
        # Loqate suggestions are usually keyboard-selectable while focus remains in the postcode field.
        try:
            for _ in range(choice_index):
                page.keyboard.press("ArrowDown")
                time.sleep(0.1)
            page.keyboard.press("Enter")
            time.sleep(1)
            self.log(f"已尝试选择第 {choice_index} 个地址候选")
            return
        except PlaywrightError:
            pass
        self.log("未能自动选择地址候选，将尝试手动地址字段回填")

    def _fill_manual_address_fallback(self, page: Page) -> None:
        defaults = self.config.activation_defaults
        if defaults.address_line1.strip():
            self._try_fill_any_frame(page, defaults.address_line1.strip(), labels=[r"address line 1"], placeholders=[], selectors=[
                "input[name*='address1' i]", "input[id*='address1' i]", "input[name*='address-line1' i]",
            ])
        if defaults.address_line2.strip():
            self._try_fill_any_frame(page, defaults.address_line2.strip(), labels=[r"address line 2"], placeholders=[], selectors=[
                "input[name*='address2' i]", "input[id*='address2' i]", "input[name*='address-line2' i]",
            ])
        if defaults.town.strip():
            self._try_fill_any_frame(page, defaults.town.strip(), labels=[r"town", r"city"], placeholders=[], selectors=[
                "input[name*='town' i]", "input[id*='town' i]", "input[name*='city' i]", "input[id*='city' i]",
            ])

    def _fill_payment_details(self, page: Page) -> None:
        card = self.config.payment_card
        if not self._page_has_text(page, [r"Payment", r"Card details"]):
            return
        if not (card.card_number.strip() and card.name_on_card.strip() and card.expiry_date.strip() and card.security_code.strip()):
            self.log("支付卡预设不完整，已停在支付页等待手动填写")
            return
        self._try_fill_any_frame(page, card.card_number.strip(), labels=[r"card number"], placeholders=[], selectors=[
            "input[name*='card' i]", "input[id*='card' i]", "input[autocomplete='cc-number']",
        ])
        self._try_fill_any_frame(page, card.name_on_card.strip(), labels=[r"name on card"], placeholders=[], selectors=[
            "input[name*='name' i]", "input[id*='name' i]", "input[autocomplete='cc-name']",
        ])
        self._try_fill_any_frame(page, card.expiry_date.strip(), labels=[r"expiry"], placeholders=[r"MM/YY"], selectors=[
            "input[name*='exp' i]", "input[id*='exp' i]", "input[autocomplete='cc-exp']",
        ])
        self._try_fill_any_frame(page, card.security_code.strip(), labels=[r"security code", r"cvv", r"cvc"], placeholders=[], selectors=[
            "input[name*='security' i]", "input[id*='security' i]", "input[name*='cvv' i]", "input[name*='cvc' i]",
            "input[autocomplete='cc-csc']",
        ])
        self._try_check(page, [r"I understand and agree"])
        self.payment_page_seen = True
        self.log("已填入支付卡预设。请人工确认并点击 Place order；支付完成后将自动解绑银行卡。")

    def _auto_remove_saved_card_if_ready(self, page: Page) -> None:
        if self.saved_card_removed or not self.config.activation_defaults.auto_remove_saved_card:
            return
        if not self.payment_page_seen:
            return
        url = page.url or ""
        if "giffgaff.com" not in url:
            return
        if "/payments" in url:
            return
        ready_patterns = [
            r"Orders and payments",
            r"order.*completed",
            r"payment.*complete",
            r"activated",
            r"dashboard",
            r"topup",
        ]
        if not ("/profile/payment-details" in url or self._page_has_text(page, ready_patterns)):
            return
        try:
            self._remove_saved_card(page)
            self.saved_card_removed = True
        except Exception as exc:
            self.log(f"自动解绑银行卡失败：{exc}")

    def _remove_saved_card(self, page: Page) -> None:
        self.log("开始自动解绑银行卡...")
        payment_email_baseline = self._payment_info_email_snapshot(log_summary=True)
        baseline_changed_count = None
        if payment_email_baseline is not None:
            try:
                baseline_changed_count = int(payment_email_baseline.get("changed_count") or 0)
            except (TypeError, ValueError):
                baseline_changed_count = None
        navigation_timed_out = False
        try:
            page.goto(
                "https://www.giffgaff.com/profile/payment-details",
                wait_until="domcontentloaded",
                timeout=self._page_timeout(),
            )
        except PlaywrightTimeoutError:
            navigation_timed_out = True
            self.log("打开支付方式页面超时，将在当前页面继续尝试解绑银行卡")
        if navigation_timed_out:
            self._wait_short(page, 1)
        else:
            self._wait_ready(page)
        if not self._try_click_link_or_button(page, [r"Remove this credit/debit card", r"Remove.*card"]):
            if not self._page_has_text(page, [r"Your credit/debit card", r"XXXX"]):
                self.log("未检测到已保存信用卡，可能已经解绑")
                self._wait_for_payment_info_changed_email(baseline_changed_count=baseline_changed_count, timeout_seconds=20)
                return
            raise RuntimeError("未找到解绑银行卡入口")
        self._wait_ready(page)
        if not self._page_has_text(page, [r"Are you sure you want to remove your card"]):
            time.sleep(1)
        if not self._try_click_button(page, [r"Yes,\s*remove it", r"remove it"]):
            raise RuntimeError("未找到解绑银行卡确认按钮")
        self._wait_ready(page)
        time.sleep(2)
        if self._page_has_text(page, [r"Remove this credit/debit card"]):
            self.log("已点击解绑银行卡确认，请在页面检查是否完成")
        else:
            self.log("信用卡已自动解绑")
        self._wait_for_payment_info_changed_email(baseline_changed_count=baseline_changed_count)
        self.saved_card_removed = True

    def _agent_api(self) -> AgentApi | None:
        if not self.config.server_url.strip() or not self.config.agent_token.strip():
            return None
        return AgentApi(
            self.config.server_url,
            self.config.agent_token,
            timeout=25.0,
            cf_access_client_id=self.config.cloudflare_access.client_id,
            cf_access_client_secret=self.config.cloudflare_access.client_secret,
        )

    def _payment_info_email_snapshot(self, *, log_summary: bool = False) -> dict | None:
        customer_id = self.task.get("customer_id")
        if not customer_id:
            return None
        api = self._agent_api()
        if not api:
            if log_summary:
                self.log("未配置后台 Token，跳过支付信息邮件检查")
            return None
        try:
            data = api.payment_info_emails(int(customer_id), limit=50)
        except (ApiError, ValueError, TypeError) as exc:
            if log_summary:
                self.log(f"支付信息邮件检查不可用：{exc}")
            return None
        if log_summary:
            updated_count = data.get("updated_count") or 0
            changed_count = data.get("changed_count") or 0
            if data.get("updated_found"):
                self.log(f"已检测到绑卡/支付信息更新邮件 {updated_count} 封")
            if data.get("changed_found"):
                self.log(f"历史上已检测到取消/变更支付信息邮件 {changed_count} 封，将等待新的取消邮件")
            if not data.get("updated_found") and not data.get("changed_found"):
                self.log("暂未检测到 giffgaff 支付信息邮件")
        return data

    def _wait_for_payment_info_changed_email(
        self,
        *,
        baseline_changed_count: int | None = None,
        timeout_seconds: int = 90,
    ) -> bool:
        customer_id = self.task.get("customer_id")
        if not customer_id:
            return False
        if baseline_changed_count is None:
            baseline_changed_count = -1
        deadline = time.monotonic() + timeout_seconds
        logged_wait = False
        while time.monotonic() < deadline:
            data = self._payment_info_email_snapshot()
            if data is None:
                return False
            try:
                changed_count = int(data.get("changed_count") or 0)
            except (TypeError, ValueError):
                changed_count = 0
            if data.get("changed_found") and changed_count > baseline_changed_count:
                subject = data.get("latest_changed_subject") or "your payment info has changed"
                received_at = data.get("latest_changed_received_at") or ""
                suffix = f"（{received_at}）" if received_at else ""
                self.log(f"已收到 giffgaff 取消/变更支付信息确认邮件：{subject}{suffix}")
                try:
                    api = self._agent_api()
                    if api:
                        api.add_log(
                            int(customer_id),
                            f"已收到 giffgaff 取消/变更支付信息确认邮件：{subject}{suffix}",
                            step="payment-email",
                        )
                except (ApiError, ValueError, TypeError):
                    pass
                return True
            if data.get("updated_found") and not logged_wait:
                self.log("已看到绑卡/支付信息更新邮件，继续等待取消绑定确认邮件（payment info has changed）")
                logged_wait = True
            time.sleep(8)
        self.log("暂未收到 giffgaff 取消绑定确认邮件（payment info has changed），请稍后在 MoEmail 或客户端日志里复查")
        return False

    def _maybe_accept_cookies(self, page: Page) -> None:
        self._try_click_button(page, [r"accept all", r"accept", r"agree"], timeout=min(3000, self._step_timeout()))

    def _page_timeout(self) -> int:
        try:
            value = int(getattr(self.config, "page_timeout_ms", 120000) or 120000)
        except (TypeError, ValueError):
            value = 120000
        return max(30000, value)

    def _step_timeout(self) -> int:
        try:
            value = int(getattr(self.config, "step_timeout_ms", 15000) or 15000)
        except (TypeError, ValueError):
            value = 15000
        return max(3000, value)

    def _field_timeout(self) -> int:
        return max(700, min(3000, self._step_timeout()))

    def _action_timeout(self, timeout: int | None = None) -> int:
        if timeout is None:
            return self._step_timeout()
        try:
            value = int(timeout)
        except (TypeError, ValueError):
            value = self._step_timeout()
        return max(500, value)

    def _remaining_timeout(self, deadline: float, *, cap: int | None = None) -> int:
        remaining = int((deadline - time.monotonic()) * 1000)
        if remaining <= 0:
            return 0
        if cap is not None:
            remaining = min(remaining, cap)
        return max(100, remaining)

    def _wait_short(self, page: Page, seconds: float = 0.25) -> None:
        try:
            page.wait_for_timeout(int(seconds * 1000))
        except PlaywrightError:
            time.sleep(seconds)

    def _frames_and_page(self, page: Page) -> Iterable:
        yield page
        for frame in page.frames:
            if frame != page.main_frame:
                yield frame

    def _try_fill_any_frame(
        self,
        page: Page,
        value: str,
        *,
        labels: list[str],
        placeholders: list[str],
        selectors: list[str],
    ) -> bool:
        deadline = time.monotonic() + self._step_timeout() / 1000
        while time.monotonic() < deadline:
            for target in self._frames_and_page(page):
                for pattern in labels:
                    timeout = self._remaining_timeout(deadline, cap=self._field_timeout())
                    if not timeout:
                        return False
                    try:
                        locator = target.get_by_label(re.compile(pattern, re.I)).first
                        locator.fill(value, timeout=timeout)
                        return True
                    except (PlaywrightError, PlaywrightTimeoutError):
                        pass
                for pattern in placeholders:
                    timeout = self._remaining_timeout(deadline, cap=self._field_timeout())
                    if not timeout:
                        return False
                    try:
                        locator = target.get_by_placeholder(re.compile(pattern, re.I)).first
                        locator.fill(value, timeout=timeout)
                        return True
                    except (PlaywrightError, PlaywrightTimeoutError):
                        pass
                for selector in selectors:
                    timeout = self._remaining_timeout(deadline, cap=self._field_timeout())
                    if not timeout:
                        return False
                    try:
                        locator = target.locator(selector).first
                        locator.fill(value, timeout=timeout)
                        return True
                    except (PlaywrightError, PlaywrightTimeoutError):
                        pass
            self._wait_short(page)
        return False

    def _try_click_button(self, page: Page, names: list[str], timeout: int | None = None) -> bool:
        deadline = time.monotonic() + self._action_timeout(timeout) / 1000
        while time.monotonic() < deadline:
            for target in self._frames_and_page(page):
                for pattern in names:
                    action_timeout = self._remaining_timeout(deadline, cap=self._field_timeout())
                    if not action_timeout:
                        return False
                    try:
                        target.get_by_role("button", name=re.compile(pattern, re.I)).first.click(timeout=action_timeout)
                        time.sleep(1)
                        return True
                    except (PlaywrightError, PlaywrightTimeoutError):
                        pass
            self._wait_short(page)
        return False

    def _try_click_link_or_button(self, page: Page, names: list[str], timeout: int | None = None) -> bool:
        deadline = time.monotonic() + self._action_timeout(timeout) / 1000
        while time.monotonic() < deadline:
            for target in self._frames_and_page(page):
                for pattern in names:
                    regex = re.compile(pattern, re.I)
                    for role in ("link", "button"):
                        action_timeout = self._remaining_timeout(deadline, cap=self._field_timeout())
                        if not action_timeout:
                            return False
                        try:
                            target.get_by_role(role, name=regex).first.click(timeout=action_timeout)
                            time.sleep(1)
                            return True
                        except (PlaywrightError, PlaywrightTimeoutError):
                            pass
            self._wait_short(page)
        return self._try_click_text(page, names, timeout=500)

    def _try_click_text(self, page: Page, patterns: list[str], timeout: int | None = None) -> bool:
        deadline = time.monotonic() + self._action_timeout(timeout) / 1000
        while time.monotonic() < deadline:
            for target in self._frames_and_page(page):
                for pattern in patterns:
                    action_timeout = self._remaining_timeout(deadline, cap=self._field_timeout())
                    if not action_timeout:
                        return False
                    try:
                        locator = target.get_by_text(re.compile(pattern, re.I)).first
                        locator.scroll_into_view_if_needed(timeout=action_timeout)
                        locator.click(timeout=action_timeout)
                        time.sleep(1)
                        return True
                    except (PlaywrightError, PlaywrightTimeoutError):
                        pass
            self._wait_short(page)
        return False

    def _try_check(self, page: Page, labels: list[str]) -> bool:
        deadline = time.monotonic() + self._step_timeout() / 1000
        while time.monotonic() < deadline:
            for target in self._frames_and_page(page):
                for pattern in labels:
                    timeout = self._remaining_timeout(deadline, cap=self._field_timeout())
                    if not timeout:
                        return False
                    try:
                        checkbox = target.get_by_label(re.compile(pattern, re.I)).first
                        if not checkbox.is_checked(timeout=timeout):
                            checkbox.check(timeout=timeout)
                        return True
                    except (PlaywrightError, PlaywrightTimeoutError):
                        pass
            self._wait_short(page)
        return False

    def _page_text(self, page: Page) -> str:
        """Return the visible text of <body>, or empty string on timeout."""
        try:
            return page.locator("body").inner_text(timeout=2000)
        except PlaywrightError:
            return ""

    def _page_has_text(self, page: Page, patterns: list[str]) -> bool:
        deadline = time.monotonic() + self._step_timeout() / 1000
        while time.monotonic() < deadline:
            saw_text = False
            for target in self._frames_and_page(page):
                timeout = self._remaining_timeout(deadline, cap=1200)
                if not timeout:
                    return False
                try:
                    text = target.locator("body").inner_text(timeout=timeout)
                except (PlaywrightError, PlaywrightTimeoutError):
                    continue
                if text.strip():
                    saw_text = True
                if any(re.search(pattern, text, re.I) for pattern in patterns):
                    return True
            if saw_text:
                return False
            self._wait_short(page)
        return False

    def _first_input_value(self, page: Page, selectors: list[str]) -> str:
        deadline = time.monotonic() + self._step_timeout() / 1000
        while time.monotonic() < deadline:
            for target in self._frames_and_page(page):
                for selector in selectors:
                    try:
                        locator = target.locator(selector)
                        count = min(locator.count(), 12)
                    except (PlaywrightError, PlaywrightTimeoutError):
                        continue
                    values: list[str] = []
                    for index in range(count):
                        timeout = self._remaining_timeout(deadline, cap=800)
                        if not timeout:
                            break
                        try:
                            value = locator.nth(index).input_value(timeout=timeout).strip()
                        except (PlaywrightError, PlaywrightTimeoutError):
                            continue
                        if value:
                            values.append(value)
                    if values:
                        digits = "".join(re.sub(r"\D", "", value) for value in values)
                        if len(digits) >= 6:
                            return digits
                        return values[0]
            self._wait_short(page)
        return ""

    def _wait_ready(self, page: Page) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=self._page_timeout())
        except (PlaywrightError, PlaywrightTimeoutError):
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=min(30000, self._step_timeout()))
        except (PlaywrightError, PlaywrightTimeoutError):
            pass
        time.sleep(1)


def test_browser_proxy(config: AppConfig, log: LogCallback) -> str:
    with sync_playwright() as playwright:
        launch_options = {"headless": True}
        proxy = config.proxy.playwright_proxy()
        if proxy:
            launch_options["proxy"] = proxy
        channel = (config.browser_channel or "").strip()
        if channel and channel != "chromium":
            launch_options["channel"] = channel
        browser = playwright.chromium.launch(**launch_options)
        try:
            page = browser.new_page()
            log("正在测试浏览器出口 IP...")
            page.goto("https://api.ipify.org?format=json", wait_until="domcontentloaded", timeout=30000)
            body = page.locator("body").inner_text(timeout=5000)
            return body.strip()
        finally:
            browser.close()
