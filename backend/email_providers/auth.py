"""JWT cache helpers for cloud-mail provider."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import EmailProvider


def hydrate_provider(provider: "EmailProvider", row) -> None:
    """Push cached JWT from a DB row into a CloudMailProvider's in-memory state.

    No-op for non-cloud-mail providers.
    """
    from .cloudmail import CloudMailProvider
    if isinstance(provider, CloudMailProvider):
        cached_jwt = row["last_jwt_token"]
        cached_at = row["last_jwt_at"]
        if cached_jwt:
            provider._jwt = cached_jwt
        if cached_at:
            provider._jwt_at = cached_at


def extract_jwt_for_persist(provider: "EmailProvider") -> tuple[str | None, str | None]:
    """Return (jwt_token, jwt_at) to persist after a cloud-mail operation.

    Returns (None, None) for non-cloud-mail providers.
    """
    from .cloudmail import CloudMailProvider
    if isinstance(provider, CloudMailProvider):
        return provider.jwt, provider.jwt_acquired_at
    return None, None
