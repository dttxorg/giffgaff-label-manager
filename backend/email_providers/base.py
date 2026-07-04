"""Email provider abstract class + return dataclasses."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GeneratedEmail:
    provider_account_id: str
    address: str
    share_link: str | None = None


@dataclass
class InboxMessage:
    id: str
    subject: str
    text: str
    received_at: str


class EmailProvider(ABC):
    provider_type: str = ""

    @abstractmethod
    def generate_email(self) -> GeneratedEmail:
        """Create a new email account on this provider."""

    @abstractmethod
    def fetch_latest_messages(
        self, provider_account_id: str, *, after_message_id: str = ""
    ) -> list[InboxMessage]:
        """Return received messages newer than the given cursor (exclusive). Newest-first."""

    @abstractmethod
    def extract_verification_code(self, message: InboxMessage) -> str | None:
        """Extract a 6-digit code from the message body."""

    @abstractmethod
    def ping(self) -> bool:
        """Check provider is reachable and credentials valid."""

    def share_link(self, provider_account_id: str) -> str | None:
        """Optional. Override to return a public URL the user can open."""
        return None
