from __future__ import annotations

from typing import Any

import httpx


class ApiError(RuntimeError):
    pass


class AgentApi:
    def __init__(
        self,
        server_url: str,
        token: str,
        timeout: float = 20.0,
        *,
        cf_access_client_id: str = "",
        cf_access_client_secret: str = "",
    ):
        self.server_url = server_url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout
        self.cf_access_client_id = cf_access_client_id.strip()
        self.cf_access_client_secret = cf_access_client_secret.strip()

    def _url(self, path: str) -> str:
        return f"{self.server_url}{path}"

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}"}
        if self.cf_access_client_id and self.cf_access_client_secret:
            headers["CF-Access-Client-Id"] = self.cf_access_client_id
            headers["CF-Access-Client-Secret"] = self.cf_access_client_secret
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.server_url:
            raise ApiError("请先填写后台地址")
        if not self.token:
            raise ApiError("请先填写桌面客户端 Token")
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.request(
                    method,
                    self._url(path),
                    headers=self._headers(),
                    params=params,
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            raise ApiError(f"请求失败：{exc}") from exc

        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            detail = data.get("detail") if isinstance(data, dict) else ""
            raise ApiError(detail or f"接口返回 {response.status_code}")
        if not isinstance(data, dict):
            raise ApiError("接口返回格式错误")
        return data

    def ping(self) -> dict[str, Any]:
        return self._request("GET", "/api/agent/ping")

    def claim_next_task(self, agent_id: str) -> dict[str, Any] | None:
        data = self._request(
            "GET",
            "/api/agent/activation-tasks/next",
            params={"agent_id": agent_id or "desktop"},
        )
        task = data.get("task")
        return task if isinstance(task, dict) else None

    def list_activation_tasks(self, limit: int = 200) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            "/api/agent/activation-tasks",
            params={"limit": limit},
        )
        tasks = data.get("tasks")
        return tasks if isinstance(tasks, list) else []

    def claim_task(self, customer_id: int, agent_id: str) -> dict[str, Any] | None:
        data = self._request(
            "POST",
            f"/api/agent/activation-tasks/{customer_id}/claim",
            params={"agent_id": agent_id or "desktop"},
        )
        task = data.get("task")
        return task if isinstance(task, dict) else None

    def add_log(self, customer_id: int, message: str, *, step: str = "", level: str = "info") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/agent/customers/{customer_id}/activation-log",
            json_body={"level": level, "step": step or None, "message": message},
        )

    def update_status(
        self,
        customer_id: int,
        status: str,
        *,
        message: str = "",
        error: str = "",
        step: str = "",
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/agent/customers/{customer_id}/activation-status",
            json_body={
                "status": status,
                "message": message or None,
                "error": error or None,
                "step": step or None,
            },
        )

    def update_result(
        self,
        customer_id: int,
        *,
        phone_number: str = "",
        status: str = "等待转 eSIM",
        message: str = "",
        error: str = "",
        step: str = "",
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/agent/customers/{customer_id}/activation-result",
            json_body={
                "phone_number": phone_number or None,
                "status": status,
                "message": message or None,
                "error": error or None,
                "step": step or None,
            },
        )

    def verification_code(self, customer_id: int) -> dict[str, Any]:
        return self._request("GET", f"/api/agent/customers/{customer_id}/verification-code")

    def payment_info_emails(self, customer_id: int, limit: int = 50) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/agent/customers/{customer_id}/payment-info-emails",
            params={"limit": limit},
        )
