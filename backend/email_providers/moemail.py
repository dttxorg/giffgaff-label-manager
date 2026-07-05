"""MoEmail provider implementation.

Wraps the lower-level MoEmailClient into the EmailProvider abstraction.
"""
from __future__ import annotations

import re

from ._moemail_client import MoEmailClient, generate_email_name
from .base import EmailProvider, GeneratedEmail, InboxMessage


VERIFICATION_CODE_RE = re.compile(r"\b\d{6}\b")


class MoEmailProvider(EmailProvider):
    provider_type = "moemail"

    def __init__(self, url: str, api_key: str, *, domains: list[str] | None = None, default_domain: str | None = None):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self._client = MoEmailClient(url, api_key)
        self._domains = list(domains or [])
        self._default_domain = default_domain

    def _pick_domain(self, requested: str | None = None) -> str | None:
        if requested:
            req = requested.strip()
            if not req:
                return self._default_domain
            if not self._domains or req in self._domains:
                return req
            # Requested domain not in the provider's allow-list — fall back to provider default.
            return self._default_domain
        return self._default_domain

    def generate_email(self, *, domain: str | None = None) -> GeneratedEmail:
        chosen = self._pick_domain(domain)
        data = self._client.generate_email(
            name=generate_email_name(),
            expiry_time=0,
            domain=chosen,
        )
        share_link = None
        try:
            result = self._client.create_share_link(data["id"])
            share_link = result.get("link")
        except Exception:
            share_link = None
        return GeneratedEmail(
            provider_account_id=str(data["id"]),
            address=data["email"],
            share_link=share_link,
        )

    def list_domains(self) -> list[str]:
        if not self._domains:
            return []
        if self._default_domain and self._default_domain not in self._domains:
            return [self._default_domain] + self._domains
        return list(self._domains)

    def default_domain(self) -> str | None:
        return self._default_domain

    def fetch_latest_messages(
        self, provider_account_id: str, *, after_message_id: str = ""
    ) -> list[InboxMessage]:
        data = self._client.get_email_messages(provider_account_id)
        msgs = []
        for m in data.get("messages", []):
            mid = str(m.get("id"))
            if after_message_id and mid <= after_message_id:
                continue
            try:
                body = self._client.get_message(provider_account_id, mid)
            except Exception:
                continue
            text = body.get("text") or body.get("content") or ""
            msgs.append(InboxMessage(
                id=mid,
                subject=m.get("subject", ""),
                text=text,
                received_at=m.get("receivedAt") or m.get("createdAt") or "",
            ))
        return msgs

    def get_email_messages(self, provider_account_id: str) -> dict:
        """Alias returning raw MoEmail payload format for backward compat
        with main.py endpoints that consume MoEmail-shaped JSON."""
        return {"messages": [
            {"id": m.id, "subject": m.subject, "receivedAt": m.received_at}
            for m in self.fetch_latest_messages(provider_account_id)
        ]}

    def extract_verification_code(self, message: InboxMessage) -> str | None:
        m = VERIFICATION_CODE_RE.search(message.text)
        return m.group(0) if m else None

    def ping(self) -> bool:
        try:
            self._client.get_config()
            return True
        except Exception:
            return False
