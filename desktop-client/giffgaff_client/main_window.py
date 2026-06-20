from __future__ import annotations

import sys
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .api import AgentApi, ApiError
from .automation import BrowserCommand, BrowserSession, test_browser_proxy
from .config import AppConfig, ActivationDefaults, PaymentCardConfig, ProxyConfig, load_config, save_config


class ApiWorker(QThread):
    succeeded = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, action: str, api: AgentApi, fn: Callable[[], Any]):
        super().__init__()
        self.action = action
        self.api = api
        self.fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self.action, self.fn())
        except ApiError as exc:
            self.failed.emit(self.action, str(exc))
        except Exception as exc:
            self.failed.emit(self.action, f"操作失败：{exc}")


class ProxyTestWorker(QThread):
    logged = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config

    def run(self) -> None:
        try:
            result = test_browser_proxy(self.config, self.logged.emit)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class BrowserWorker(QThread):
    logged = Signal(str)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, config: AppConfig, task: dict[str, Any]):
        super().__init__()
        self.session = BrowserSession(config, task, self.logged.emit)

    def enqueue(self, command: BrowserCommand) -> None:
        self.session.enqueue(command)

    def stop(self) -> None:
        self.session.stop()

    def run(self) -> None:
        try:
            self.session.run()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.stopped.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Giffgaff Activation Client")
        self.resize(1180, 760)
        self.config = load_config()
        self.current_task: dict[str, Any] | None = None
        self.last_code = ""
        self.api_workers: list[ApiWorker] = []
        self.proxy_worker: ProxyTestWorker | None = None
        self.browser_worker: BrowserWorker | None = None
        self._build_ui()
        self._load_config_into_ui()
        self._set_task(None)

    def _build_ui(self) -> None:
        root = QWidget()
        main = QHBoxLayout(root)
        left = QVBoxLayout()
        right = QVBoxLayout()
        main.addLayout(left, 2)
        main.addLayout(right, 3)

        left.addWidget(self._build_connection_group())
        left.addWidget(self._build_proxy_group())
        left.addWidget(self._build_browser_group())
        left.addWidget(self._build_activation_defaults_group())
        left.addStretch(1)

        right.addWidget(self._build_task_group())
        right.addWidget(self._build_actions_group())
        right.addWidget(self._build_log_group(), 1)
        self.setCentralWidget(root)

    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox("后台连接")
        form = QFormLayout(group)
        self.server_url = QLineEdit()
        self.agent_token = QLineEdit()
        self.agent_token.setEchoMode(QLineEdit.Password)
        self.agent_id = QLineEdit()
        form.addRow("后台地址", self.server_url)
        form.addRow("Agent Token", self.agent_token)
        form.addRow("客户端 ID", self.agent_id)
        row = QHBoxLayout()
        self.save_btn = QPushButton("保存设置")
        self.test_btn = QPushButton("测试连接")
        self.claim_btn = QPushButton("领取下一个任务")
        self.save_btn.clicked.connect(self.save_settings)
        self.test_btn.clicked.connect(self.test_connection)
        self.claim_btn.clicked.connect(self.claim_task)
        row.addWidget(self.save_btn)
        row.addWidget(self.test_btn)
        row.addWidget(self.claim_btn)
        form.addRow(row)
        return group

    def _build_proxy_group(self) -> QGroupBox:
        group = QGroupBox("代理")
        form = QFormLayout(group)
        self.proxy_mode = QComboBox()
        self.proxy_mode.addItems(["none", "system", "custom"])
        self.proxy_type = QComboBox()
        self.proxy_type.addItems(["http", "https", "socks5"])
        self.proxy_host = QLineEdit()
        self.proxy_port = QLineEdit()
        self.proxy_username = QLineEdit()
        self.proxy_password = QLineEdit()
        self.proxy_password.setEchoMode(QLineEdit.Password)
        self.proxy_test_btn = QPushButton("测试浏览器出口 IP")
        self.proxy_mode.currentTextChanged.connect(lambda _: self.update_proxy_fields())
        self.proxy_test_btn.clicked.connect(self.test_proxy)
        form.addRow("模式", self.proxy_mode)
        form.addRow("类型", self.proxy_type)
        form.addRow("主机", self.proxy_host)
        form.addRow("端口", self.proxy_port)
        form.addRow("用户名", self.proxy_username)
        form.addRow("密码", self.proxy_password)
        form.addRow(self.proxy_test_btn)
        return group

    def _build_browser_group(self) -> QGroupBox:
        group = QGroupBox("浏览器")
        form = QFormLayout(group)
        self.activation_url = QLineEdit()
        self.browser_channel = QComboBox()
        self.browser_channel.addItems(["msedge", "chrome", "chromium"])
        self.user_data_dir = QLineEdit()
        self.headless = QCheckBox("无头模式")
        self.slow_mo_ms = QLineEdit()
        form.addRow("激活页面", self.activation_url)
        form.addRow("浏览器", self.browser_channel)
        form.addRow("用户数据目录", self.user_data_dir)
        form.addRow("慢动作 ms", self.slow_mo_ms)
        form.addRow(self.headless)
        return group

    def _build_activation_defaults_group(self) -> QGroupBox:
        group = QGroupBox("激活自动化预设")
        form = QFormLayout(group)
        self.default_first_name = QLineEdit()
        self.default_last_name = QLineEdit()
        self.default_postcode = QLineEdit()
        self.default_address_line1 = QLineEdit()
        self.default_address_line2 = QLineEdit()
        self.default_town = QLineEdit()
        self.default_address_choice_index = QLineEdit()
        self.default_topup_amount = QLineEdit()
        self.card_number = QLineEdit()
        self.card_number.setEchoMode(QLineEdit.Password)
        self.card_name = QLineEdit()
        self.card_expiry = QLineEdit()
        self.card_expiry.setPlaceholderText("MM/YY")
        self.card_security_code = QLineEdit()
        self.card_security_code.setEchoMode(QLineEdit.Password)
        self.auto_remove_saved_card = QCheckBox("支付后自动解绑银行卡")
        form.addRow("First name", self.default_first_name)
        form.addRow("Last name", self.default_last_name)
        form.addRow("UK Postcode", self.default_postcode)
        form.addRow("Address line 1", self.default_address_line1)
        form.addRow("Address line 2", self.default_address_line2)
        form.addRow("Town", self.default_town)
        form.addRow("地址候选序号", self.default_address_choice_index)
        form.addRow("充值金额 £", self.default_topup_amount)
        form.addRow("Card number", self.card_number)
        form.addRow("Name on card", self.card_name)
        form.addRow("Expiry date", self.card_expiry)
        form.addRow("Security code", self.card_security_code)
        form.addRow(self.auto_remove_saved_card)
        return group

    def _build_task_group(self) -> QGroupBox:
        group = QGroupBox("当前任务")
        layout = QGridLayout(group)
        self.task_fields: dict[str, QLineEdit | QPlainTextEdit] = {}
        rows = [
            ("customer_id", "客户 ID"),
            ("activation_status", "激活状态"),
            ("activation_date", "开通日期"),
            ("email", "邮箱"),
            ("initial_password", "初始密码"),
            ("sim_activation_code", "SIM 激活码"),
            ("phone_number", "手机号"),
        ]
        for row, (key, label) in enumerate(rows):
            layout.addWidget(QLabel(label), row, 0)
            field = QLineEdit()
            field.setReadOnly(True)
            self.task_fields[key] = field
            layout.addWidget(field, row, 1)
            copy_btn = QPushButton("复制")
            copy_btn.clicked.connect(lambda _=False, k=key: self.copy_task_field(k))
            layout.addWidget(copy_btn, row, 2)
        layout.addWidget(QLabel("收货地址"), len(rows), 0)
        address = QPlainTextEdit()
        address.setReadOnly(True)
        address.setMaximumHeight(86)
        self.task_fields["shipping_address"] = address
        layout.addWidget(address, len(rows), 1, 1, 2)
        return group

    def _build_actions_group(self) -> QGroupBox:
        group = QGroupBox("操作")
        layout = QVBoxLayout(group)
        row1 = QHBoxLayout()
        self.start_browser_btn = QPushButton("打开并预填")
        self.stop_browser_btn = QPushButton("停止浏览器")
        self.refresh_code_btn = QPushButton("刷新验证码")
        self.fill_code_btn = QPushButton("填入验证码")
        self.remove_card_btn = QPushButton("自动解绑银行卡")
        self.start_browser_btn.clicked.connect(self.start_browser)
        self.stop_browser_btn.clicked.connect(self.stop_browser)
        self.refresh_code_btn.clicked.connect(self.refresh_code)
        self.fill_code_btn.clicked.connect(self.fill_code)
        self.remove_card_btn.clicked.connect(self.remove_saved_card)
        row1.addWidget(self.start_browser_btn)
        row1.addWidget(self.stop_browser_btn)
        row1.addWidget(self.refresh_code_btn)
        row1.addWidget(self.fill_code_btn)
        row1.addWidget(self.remove_card_btn)
        layout.addLayout(row1)

        result_row = QHBoxLayout()
        self.phone_result = QLineEdit()
        self.phone_result.setPlaceholderText("拿到手机号后填这里")
        result_row.addWidget(QLabel("手机号"))
        result_row.addWidget(self.phone_result)
        layout.addLayout(result_row)

        row2 = QHBoxLayout()
        self.wait_payment_btn = QPushButton("标记等待人工支付")
        self.wait_esim_btn = QPushButton("标记等待转 eSIM")
        self.done_btn = QPushButton("标记完成")
        self.fail_btn = QPushButton("标记失败")
        self.wait_payment_btn.clicked.connect(lambda: self.update_status("等待人工支付"))
        self.wait_esim_btn.clicked.connect(lambda: self.update_result("等待转 eSIM"))
        self.done_btn.clicked.connect(lambda: self.update_result("已完成"))
        self.fail_btn.clicked.connect(self.mark_failed)
        row2.addWidget(self.wait_payment_btn)
        row2.addWidget(self.wait_esim_btn)
        row2.addWidget(self.done_btn)
        row2.addWidget(self.fail_btn)
        layout.addLayout(row2)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("日志")
        layout = QVBoxLayout(group)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)
        return group

    def _load_config_into_ui(self) -> None:
        cfg = self.config
        self.server_url.setText(cfg.server_url)
        self.agent_token.setText(cfg.agent_token)
        self.agent_id.setText(cfg.agent_id)
        self.activation_url.setText(cfg.activation_url)
        self.browser_channel.setCurrentText(cfg.browser_channel)
        self.user_data_dir.setText(cfg.user_data_dir)
        self.headless.setChecked(cfg.headless)
        self.slow_mo_ms.setText(str(cfg.slow_mo_ms))
        self.proxy_mode.setCurrentText(cfg.proxy.mode)
        self.proxy_type.setCurrentText(cfg.proxy.proxy_type)
        self.proxy_host.setText(cfg.proxy.host)
        self.proxy_port.setText(cfg.proxy.port)
        self.proxy_username.setText(cfg.proxy.username)
        self.proxy_password.setText(cfg.proxy.password)
        self.default_first_name.setText(cfg.activation_defaults.first_name)
        self.default_last_name.setText(cfg.activation_defaults.last_name)
        self.default_postcode.setText(cfg.activation_defaults.postcode)
        self.default_address_line1.setText(cfg.activation_defaults.address_line1)
        self.default_address_line2.setText(cfg.activation_defaults.address_line2)
        self.default_town.setText(cfg.activation_defaults.town)
        self.default_address_choice_index.setText(str(cfg.activation_defaults.address_choice_index))
        self.default_topup_amount.setText(cfg.activation_defaults.topup_amount)
        self.auto_remove_saved_card.setChecked(cfg.activation_defaults.auto_remove_saved_card)
        self.card_number.setText(cfg.payment_card.card_number)
        self.card_name.setText(cfg.payment_card.name_on_card)
        self.card_expiry.setText(cfg.payment_card.expiry_date)
        self.card_security_code.setText(cfg.payment_card.security_code)
        self.update_proxy_fields()

    def collect_config(self) -> AppConfig:
        try:
            slow_mo = int(self.slow_mo_ms.text().strip() or "0")
        except ValueError:
            slow_mo = 0
        try:
            address_choice_index = int(self.default_address_choice_index.text().strip() or "1")
        except ValueError:
            address_choice_index = 1
        return AppConfig(
            server_url=self.server_url.text().strip(),
            agent_token=self.agent_token.text().strip(),
            agent_id=self.agent_id.text().strip() or "windows-01",
            activation_url=self.activation_url.text().strip(),
            browser_channel=self.browser_channel.currentText(),
            user_data_dir=self.user_data_dir.text().strip(),
            headless=self.headless.isChecked(),
            slow_mo_ms=slow_mo,
            proxy=ProxyConfig(
                mode=self.proxy_mode.currentText(),
                proxy_type=self.proxy_type.currentText(),
                host=self.proxy_host.text().strip(),
                port=self.proxy_port.text().strip(),
                username=self.proxy_username.text().strip(),
                password=self.proxy_password.text(),
            ),
            activation_defaults=ActivationDefaults(
                first_name=self.default_first_name.text().strip(),
                last_name=self.default_last_name.text().strip(),
                postcode=self.default_postcode.text().strip(),
                address_line1=self.default_address_line1.text().strip(),
                address_line2=self.default_address_line2.text().strip(),
                town=self.default_town.text().strip(),
                address_choice_index=max(1, address_choice_index),
                topup_amount=self.default_topup_amount.text().strip() or "10",
                auto_remove_saved_card=self.auto_remove_saved_card.isChecked(),
            ),
            payment_card=PaymentCardConfig(
                card_number=self.card_number.text().strip(),
                name_on_card=self.card_name.text().strip(),
                expiry_date=self.card_expiry.text().strip(),
                security_code=self.card_security_code.text().strip(),
            ),
        )

    def save_settings(self) -> None:
        self.config = self.collect_config()
        save_config(self.config)
        self.log("设置已保存")

    def update_proxy_fields(self) -> None:
        custom = self.proxy_mode.currentText() == "custom"
        for widget in (self.proxy_type, self.proxy_host, self.proxy_port, self.proxy_username, self.proxy_password):
            widget.setEnabled(custom)

    def api(self) -> AgentApi:
        cfg = self.collect_config()
        return AgentApi(cfg.server_url, cfg.agent_token)

    def start_api_worker(self, action: str, fn: Callable[[AgentApi], Any]) -> None:
        api = self.api()
        worker = ApiWorker(action, api, lambda: fn(api))
        worker.succeeded.connect(self.on_api_success)
        worker.failed.connect(self.on_api_error)
        worker.finished.connect(lambda: self.api_workers.remove(worker) if worker in self.api_workers else None)
        self.api_workers.append(worker)
        worker.start()

    def test_connection(self) -> None:
        self.save_settings()
        self.log("测试后台连接...")
        self.start_api_worker("ping", lambda api: api.ping())

    def claim_task(self) -> None:
        self.save_settings()
        self.log("领取下一个激活任务...")
        agent_id = self.collect_config().agent_id
        self.start_api_worker("claim", lambda api: api.claim_next_task(agent_id))

    def refresh_code(self) -> None:
        if not self.require_task():
            return
        customer_id = int(self.current_task["customer_id"])
        self.log("刷新验证码...")
        self.start_api_worker("code", lambda api: api.verification_code(customer_id))

    def update_status(self, status: str, *, error: str = "") -> None:
        if not self.require_task():
            return
        customer_id = int(self.current_task["customer_id"])
        self.start_api_worker(
            f"status:{status}",
            lambda api: api.update_status(
                customer_id,
                status,
                message=f"Windows 客户端标记：{status}",
                error=error,
                step="desktop",
            ),
        )

    def update_result(self, status: str, *, error: str = "") -> None:
        if not self.require_task():
            return
        customer_id = int(self.current_task["customer_id"])
        phone = self.phone_result.text().strip()
        self.start_api_worker(
            f"result:{status}",
            lambda api: api.update_result(
                customer_id,
                phone_number=phone,
                status=status,
                message=f"Windows 客户端回传：{status}",
                error=error,
                step="desktop",
            ),
        )

    def mark_failed(self) -> None:
        if not self.require_task():
            return
        text, ok = QInputDialog.getText(self, "失败原因", "请输入失败原因")
        if ok:
            self.update_result("失败", error=text.strip() or "客户端标记失败")

    def test_proxy(self) -> None:
        self.save_settings()
        self.proxy_test_btn.setEnabled(False)
        self.log("开始测试代理...")
        self.proxy_worker = ProxyTestWorker(self.collect_config())
        self.proxy_worker.logged.connect(self.log)
        self.proxy_worker.succeeded.connect(self.on_proxy_success)
        self.proxy_worker.failed.connect(self.on_proxy_error)
        self.proxy_worker.finished.connect(lambda: self.proxy_test_btn.setEnabled(True))
        self.proxy_worker.start()

    def start_browser(self) -> None:
        if not self.require_task():
            return
        if self.browser_worker and self.browser_worker.isRunning():
            self.log("浏览器已经在运行")
            return
        self.save_settings()
        self.browser_worker = BrowserWorker(self.collect_config(), self.current_task or {})
        self.browser_worker.logged.connect(self.log)
        self.browser_worker.failed.connect(self.on_browser_error)
        self.browser_worker.stopped.connect(self.on_browser_stopped)
        self.browser_worker.start()

    def stop_browser(self) -> None:
        if self.browser_worker and self.browser_worker.isRunning():
            self.browser_worker.stop()
            self.log("正在停止浏览器...")

    def fill_code(self) -> None:
        if not self.last_code:
            self.log("还没有验证码，先点击刷新验证码")
            return
        if self.browser_worker and self.browser_worker.isRunning():
            self.browser_worker.enqueue(BrowserCommand("fill_code", self.last_code))
        else:
            self.copy_text(self.last_code)
            self.log("浏览器自动化未运行，验证码已复制到剪贴板")

    def remove_saved_card(self) -> None:
        if self.browser_worker and self.browser_worker.isRunning():
            self.browser_worker.enqueue(BrowserCommand("remove_card"))
            self.log("已发送自动解绑银行卡指令")
        else:
            QMessageBox.information(self, "浏览器未运行", "请先打开并预填，保持浏览器登录状态后再自动解绑银行卡")

    def on_api_success(self, action: str, data: object) -> None:
        if action == "ping":
            self.log(f"连接成功：{data}")
            return
        if action == "claim":
            if isinstance(data, dict):
                self._set_task(data)
                self.log(f"已领取客户 #{data.get('customer_id')} 的任务")
            else:
                self._set_task(None)
                self.log("当前没有待领取任务")
            return
        if action == "code":
            if isinstance(data, dict) and data.get("found") and data.get("code"):
                self.last_code = str(data["code"])
                self.copy_text(self.last_code)
                self.log(f"验证码：{self.last_code}，已复制到剪贴板")
            else:
                self.log(f"没有找到验证码：{data}")
            return
        if action.startswith("status:") or action.startswith("result:"):
            status = action.split(":", 1)[1]
            if self.current_task:
                self.current_task["activation_status"] = status
                if self.phone_result.text().strip():
                    self.current_task["phone_number"] = self.phone_result.text().strip()
                code = self.last_code
                self._set_task(self.current_task)
                self.last_code = code
            self.log(f"状态已回传：{status}")

    def on_api_error(self, action: str, message: str) -> None:
        self.log(f"{action} 失败：{message}")
        QMessageBox.warning(self, "操作失败", message)

    def on_proxy_success(self, result: str) -> None:
        self.log(f"代理测试成功：{result}")

    def on_proxy_error(self, message: str) -> None:
        self.log(f"代理测试失败：{message}")
        QMessageBox.warning(self, "代理测试失败", message)

    def on_browser_error(self, message: str) -> None:
        self.log(f"浏览器自动化失败：{message}")
        QMessageBox.warning(self, "浏览器自动化失败", message)

    def on_browser_stopped(self) -> None:
        self.log("浏览器自动化已停止")

    def _set_task(self, task: dict[str, Any] | None) -> None:
        self.current_task = task
        keys = [
            "customer_id",
            "activation_status",
            "activation_date",
            "email",
            "initial_password",
            "sim_activation_code",
            "phone_number",
            "shipping_address",
        ]
        for key in keys:
            widget = self.task_fields[key]
            value = "" if not task else str(task.get(key) or "")
            if isinstance(widget, QPlainTextEdit):
                widget.setPlainText(value)
            else:
                widget.setText(value)
        self.phone_result.setText("" if not task else str(task.get("phone_number") or ""))
        self.last_code = ""

    def require_task(self) -> bool:
        if self.current_task:
            return True
        QMessageBox.information(self, "没有任务", "请先领取一个激活任务")
        return False

    def copy_task_field(self, key: str) -> None:
        if not self.current_task:
            return
        self.copy_text(str(self.current_task.get(key) or ""))
        self.log(f"已复制：{key}")

    def copy_text(self, text: str) -> None:
        if text:
            QGuiApplication.clipboard().setText(text)

    def log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def closeEvent(self, event) -> None:
        if self.browser_worker and self.browser_worker.isRunning():
            self.browser_worker.stop()
            self.browser_worker.wait(3000)
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
