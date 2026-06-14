from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import queue
import re
import time
from typing import Callable

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
                continue
            if command.name == "stop":
                self.stop_requested = True
                break
            if command.name == "fill_code":
                self._fill_verification_code(page, command.value)

    def _open_and_prefill(self, page: Page) -> None:
        url = self.config.activation_url.strip() or "https://www.giffgaff.com/activate"
        self.log(f"打开激活页面：{url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._maybe_accept_cookies(page)

        sim_code = str(self.task.get("sim_activation_code") or "")
        email = str(self.task.get("email") or "")
        password = str(self.task.get("initial_password") or "")

        if sim_code:
            filled = self._try_fill(
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

        if email:
            filled = self._try_fill(
                page,
                email,
                labels=[r"email", r"e-mail"],
                placeholders=[r"email", r"e-mail"],
                selectors=["input[type='email']", "input[name*='email' i]", "input[id*='email' i]"],
            )
            self.log("已尝试填写邮箱" if filled else "未找到邮箱输入框")

        if password:
            filled = self._try_fill(
                page,
                password,
                labels=[r"password"],
                placeholders=[r"password"],
                selectors=["input[type='password']", "input[name*='password' i]", "input[id*='password' i]"],
            )
            self.log("已尝试填写初始密码" if filled else "未找到密码输入框")

        address = str(self.task.get("shipping_address") or "")
        if address:
            self.log(f"客户收货地址：{address}")

    def _fill_verification_code(self, page: Page, code: str) -> None:
        code = (code or "").strip()
        if not code:
            self.log("验证码为空，跳过填写")
            return
        filled = self._try_fill(
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

    def _maybe_accept_cookies(self, page: Page) -> None:
        self._try_click_button(page, [r"accept all", r"accept", r"agree"], timeout=1200)

    def _try_fill(
        self,
        page: Page,
        value: str,
        *,
        labels: list[str],
        placeholders: list[str],
        selectors: list[str],
    ) -> bool:
        for pattern in labels:
            try:
                locator = page.get_by_label(re.compile(pattern, re.I)).first
                locator.fill(value, timeout=1500)
                return True
            except (PlaywrightError, PlaywrightTimeoutError):
                pass
        for pattern in placeholders:
            try:
                locator = page.get_by_placeholder(re.compile(pattern, re.I)).first
                locator.fill(value, timeout=1500)
                return True
            except (PlaywrightError, PlaywrightTimeoutError):
                pass
        for selector in selectors:
            try:
                locator = page.locator(selector).first
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
