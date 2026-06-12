"""
MoEmail API 集成：生成临时邮箱 + 获取永久分享链接
文档：https://docs.moemail.app
"""

import httpx
from typing import Optional


class MoEmailClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    def generate_email(self, name: Optional[str] = None,
                       expiry_time: int = 0) -> dict:
        """
        创建临时邮箱
        expiry_time: 0=永久, 3600000=1小时, 86400000=1天, 604800000=7天
        """
        payload = {}
        if name:
            payload["name"] = name
        if expiry_time is not None:
            payload["expiryTime"] = expiry_time

        r = httpx.post(
            f"{self.base_url}/api/emails/generate",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def create_share_link(self, email_id: str, expires_in: int = 0) -> dict:
        """
        创建邮箱分享链接
        expires_in: 0=永久有效，其他值=毫秒数
        """
        payload = {"expiresIn": expires_in}
        r = httpx.post(
            f"{self.base_url}/api/emails/{email_id}/share",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def get_config(self) -> dict:
        """获取系统配置（邮箱域名等）"""
        r = httpx.get(
            f"{self.base_url}/api/config",
            headers=self._headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json()