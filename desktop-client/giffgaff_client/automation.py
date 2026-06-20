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
            if command.name == "fill_code":
                self._fill_verification_code(page, command.value)
            if command.name == "remove_card":
                self._remove_saved_card(page)

    def _open_and_prefill(self, page: Page) -> None:
        url = self.config.activation_url.strip() or "https://www.giffgaff.com/activate"
        self.log(f"打开激活页面：{url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
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
        time.sleep(1.5)
        # Loqate suggestions are usually keyboard-selectable while focus remains in the postcode field.
        try:
            for _ in range(max(1, choice_index)):
                page.keyboard.press("ArrowDown")
                time.sleep(0.1)
            page.keyboard.press("Enter")
            time.sleep(1)
            self.log(f"已尝试选择第 {choice_index} 个地址候选")
            return
        except PlaywrightError:
            pass
        # Fallback: click the first visible suggestion-like row, skipping the manual entry link.
        try:
            locator = page.locator(
                "text=/^(?!I cannot find my address)(?!Address line)(?!Postcode).*(,[ ]*)?[A-Z]{1,2}\\d[A-Z\\d]?\\s*\\d[A-Z]{2}$/i"
            ).first
            locator.click(timeout=1500)
            time.sleep(1)
            self.log("已点击第一个地址候选")
        except (PlaywrightError, PlaywrightTimeoutError):
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
        page.goto("https://www.giffgaff.com/profile/payment-details", wait_until="domcontentloaded", timeout=60000)
        self._wait_ready(page)
        if not self._try_click_link_or_button(page, [r"Remove this credit/debit card", r"Remove.*card"]):
            if not self._page_has_text(page, [r"Your credit/debit card", r"XXXX"]):
                self.log("未检测到已保存信用卡，可能已经解绑")
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
        self.saved_card_removed = True

    def _maybe_accept_cookies(self, page: Page) -> None:
        self._try_click_button(page, [r"accept all", r"accept", r"agree"], timeout=1200)

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
        for target in self._frames_and_page(page):
            for pattern in labels:
                try:
                    locator = target.get_by_label(re.compile(pattern, re.I)).first
                    locator.fill(value, timeout=1500)
                    return True
                except (PlaywrightError, PlaywrightTimeoutError):
                    pass
            for pattern in placeholders:
                try:
                    locator = target.get_by_placeholder(re.compile(pattern, re.I)).first
                    locator.fill(value, timeout=1500)
                    return True
                except (PlaywrightError, PlaywrightTimeoutError):
                    pass
            for selector in selectors:
                try:
                    locator = target.locator(selector).first
                    locator.fill(value, timeout=1500)
                    return True
                except (PlaywrightError, PlaywrightTimeoutError):
                    pass
        return False

    def _try_click_button(self, page: Page, names: list[str], timeout: int = 1800) -> bool:
        for pattern in names:
            try:
                page.get_by_role("button", name=re.compile(pattern, re.I)).first.click(timeout=timeout)
                time.sleep(1)
                return True
            except (PlaywrightError, PlaywrightTimeoutError):
                pass
        return False

    def _try_click_link_or_button(self, page: Page, names: list[str], timeout: int = 2500) -> bool:
        for pattern in names:
            regex = re.compile(pattern, re.I)
            for role in ("link", "button"):
                try:
                    page.get_by_role(role, name=regex).first.click(timeout=timeout)
                    time.sleep(1)
                    return True
                except (PlaywrightError, PlaywrightTimeoutError):
                    pass
        return self._try_click_text(page, names, timeout=timeout)

    def _try_click_text(self, page: Page, patterns: list[str], timeout: int = 1800) -> bool:
        for pattern in patterns:
            try:
                locator = page.get_by_text(re.compile(pattern, re.I)).first
                locator.scroll_into_view_if_needed(timeout=timeout)
                locator.click(timeout=timeout)
                time.sleep(1)
                return True
            except (PlaywrightError, PlaywrightTimeoutError):
                pass
        return False

    def _try_check(self, page: Page, labels: list[str]) -> bool:
        for pattern in labels:
            try:
                checkbox = page.get_by_label(re.compile(pattern, re.I)).first
                if not checkbox.is_checked(timeout=1000):
                    checkbox.check(timeout=1500)
                return True
            except (PlaywrightError, PlaywrightTimeoutError):
                pass
        return False

    def _page_has_text(self, page: Page, patterns: list[str]) -> bool:
        try:
            text = page.locator("body").inner_text(timeout=2500)
        except (PlaywrightError, PlaywrightTimeoutError):
            return False
        return any(re.search(pattern, text, re.I) for pattern in patterns)

    def _wait_ready(self, page: Page) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except (PlaywrightError, PlaywrightTimeoutError):
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except (PlaywrightError, PlaywrightTimeoutError):
            pass
        time.sleep(0.8)


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
