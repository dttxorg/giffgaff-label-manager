"""Email provider abstraction layer."""

from .base import EmailProvider, GeneratedEmail, InboxMessage
from .pool import (
    pick_provider,
    list_providers,
    get_provider,
    record_provider_use,
    persist_provider_jwt,
)

__all__ = [
    "EmailProvider",
    "GeneratedEmail",
    "InboxMessage",
    "pick_provider",
    "list_providers",
    "get_provider",
    "record_provider_use",
    "persist_provider_jwt",
]
