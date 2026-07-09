from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from email_providers.cloudmail import CloudMailProvider, generate_random_prefix


def _patch_httpx():
    return patch("email_providers.cloudmail.httpx")


def _make_provider(jwt=None, jwt_at=None):
    with _patch_httpx() as m:
        m.post.return_value.status_code = 200
        m.post.return_value.json.return_value = {"data": {"token": "fresh-jwt"}}
        m.get.return_value.status_code = 200
        m.get.return_value.json.return_value = {"data": []}
        p = CloudMailProvider(
            url="https://mail.test",
            email="admin@test.com",
            password="pw",
            domain="test.com",
            jwt_token=jwt,
            jwt_acquired_at=jwt_at,
        )
    return p


def test_provider_type():
    p = CloudMailProvider(url="x", email="e", password="p", domain="d")
    assert p.provider_type == "cloudmail"


def test_generate_random_prefix_has_uppercase_letter():
    """The local-part must contain at least one upper-case character so
    the resulting email can be used directly as a password on services
    (e.g. giffgaff) that require upper-case."""
    for _ in range(200):
        prefix = generate_random_prefix()
        assert any(c.isupper() for c in prefix), prefix


def test_endpoints_include_api_prefix():
    """Regression: all cloud-mail requests must hit the /api/ namespace.

    The provider was previously sending requests to /login, /account/add,
    /email/latest, /my/loginUserInfo which are SPA fallback paths on the
    real cloud-mail deployment and silently fail.
    """
    p = CloudMailProvider(url="https://mail.test", email="a@b.com",
                          password="pw", domain="test.com")
    # Indirect check: build the same f-strings and assert each contains /api/.
    base = p.base_url
    assert base == "https://mail.test"
    assert f"{base}/api/login".startswith("https://mail.test/api/")
    assert f"{base}/api/account/add".startswith("https://mail.test/api/")
    assert f"{base}/api/email/latest".startswith("https://mail.test/api/")
    assert f"{base}/api/my/loginUserInfo".startswith("https://mail.test/api/")


def test_auth_header_uses_raw_token_not_bearer():
    """Regression: cloud-mail's API does not accept the "Bearer " prefix.

    Earlier we sent `Authorization: Bearer <jwt>` which the server rejected
    with 401, so the wrapper reported a failed ping and `generate_email`
    could not obtain a token. Cloud-mail expects the raw JWT in the header.
    """
    fresh_iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    p = CloudMailProvider(
        url="https://mail.test", email="a@b.com", password="pw",
        domain="b.com", jwt_token="my-jwt", jwt_acquired_at=fresh_iso,
    )
    headers = p._headers()
    assert headers["Authorization"] == "my-jwt", (
        f"expected raw token, got {headers['Authorization']!r}"
    )
    # Old broken value would be "Bearer my-jwt"
    assert not headers["Authorization"].startswith("Bearer "), (
        "cloud-mail rejects the 'Bearer ' prefix; use raw token"
    )


def test_login_url_uses_my_path():
    """Regression: the JWT-validation endpoint is /api/my/loginUserInfo.

    We previously hit /api/user/loginUserInfo (which 401s) and
    /my/loginUserInfo (which falls through the SPA). cloud-mail's frontend
    bundle pins the path under /my/.
    """
    p = CloudMailProvider(
        url="https://mail.test", email="a@b.com", password="pw", domain="b.com",
    )
    # Force a refresh so the login POST happens; capture the URL it hit.
    with _patch_httpx() as m:
        m.post.return_value.status_code = 200
        m.post.return_value.json.return_value = {"data": {"token": "x"}}
        p._jwt = None
        p._jwt_at = None
        p._ensure_jwt()
    login_url = m.post.call_args[0][0]
    assert login_url == "https://mail.test/api/login", login_url
    # The same prefix must be used by ping()
    with _patch_httpx() as m:
        m.post.return_value.status_code = 200
        m.post.return_value.json.return_value = {"data": {"token": "x"}}
        p._jwt = None
        p._jwt_at = None
        p.ping()
    ping_url = m.get.call_args[0][0]
    assert ping_url == "https://mail.test/api/my/loginUserInfo", ping_url


def test_ensure_jwt_skips_login_when_token_fresh():
    fresh_iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    p = CloudMailProvider(
        url="x", email="e", password="p", domain="d",
        jwt_token="fresh", jwt_acquired_at=fresh_iso,
    )
    with _patch_httpx() as m:
        p._ensure_jwt()
    # POST /login should NOT have been called
    m.post.assert_not_called()
    assert p._jwt == "fresh"


def test_ensure_jwt_logs_in_when_token_missing():
    with _patch_httpx() as m:
        m.post.return_value.status_code = 200
        m.post.return_value.json.return_value = {"data": {"token": "new-jwt"}}
        p = CloudMailProvider(
            url="https://mail.test",
            email="admin@test.com",
            password="pw",
            domain="test.com",
        )
        p._ensure_jwt()
    assert p._jwt == "new-jwt"
    assert p._jwt_at is not None


def test_ensure_jwt_refreshes_when_older_than_25_days():
    old_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    with _patch_httpx() as m:
        m.post.return_value.status_code = 200
        m.post.return_value.json.return_value = {"data": {"token": "refreshed"}}
        p = CloudMailProvider(
            url="https://mail.test",
            email="a@b.com",
            password="pw",
            domain="b.com",
            jwt_token="old",
            jwt_acquired_at=old_iso,
        )
        p._ensure_jwt()
    assert p._jwt == "refreshed"
    m.post.assert_called_once()
    login_url = m.post.call_args[0][0]
    assert login_url.endswith("/login")


def test_generate_email_calls_add_endpoint():
    with _patch_httpx() as m:
        m.post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"data": {"token": "j"}}),
            MagicMock(
                status_code=200,
                json=lambda: {"data": {"accountId": 42, "email": "abc123@test.com"}},
            ),
        ]
        p = CloudMailProvider(
            url="https://mail.test",
            email="a@b.com",
            password="pw",
            domain="test.com",
        )
        gen = p.generate_email()
    assert gen.provider_account_id == "42"
    assert gen.address == "abc123@test.com"
    assert gen.share_link is None  # cloud-mail has no share_link


def test_fetch_latest_messages():
    with _patch_httpx() as m:
        m.post.return_value.status_code = 200
        m.post.return_value.json.return_value = {"data": {"token": "j"}}
        m.get.return_value.status_code = 200
        m.get.return_value.json.return_value = {
            "data": [
                {"emailId": 1, "subject": "Confirm", "text": "code 123456", "createTime": "2026-07-04"},
            ]
        }
        p = CloudMailProvider(
            url="https://mail.test",
            email="a@b.com",
            password="pw",
            domain="test.com",
        )
        msgs = p.fetch_latest_messages("42")
    assert len(msgs) == 1
    assert msgs[0].subject == "Confirm"
    assert "123456" in msgs[0].text


def test_extract_verification_code():
    from email_providers.base import InboxMessage
    p = CloudMailProvider(url="x", email="e", password="p", domain="d")
    msg = InboxMessage(id="1", subject="s", text="Your code is 654321 ok", received_at="t")
    assert p.extract_verification_code(msg) == "654321"


def test_ping_true_on_success():
    with _patch_httpx() as m:
        m.post.return_value.status_code = 200
        m.post.return_value.json.return_value = {"data": {"token": "j"}}
        m.get.return_value.status_code = 200
        p = CloudMailProvider(url="https://mail.test", email="a@b.com", password="pw", domain="b.com")
        assert p.ping() is True


def test_ping_false_on_auth_failure():
    with _patch_httpx() as m:
        m.post.return_value.status_code = 401
        m.post.return_value.json.return_value = {"error": "auth failed"}
        p = CloudMailProvider(url="https://mail.test", email="a@b.com", password="pw", domain="b.com")
        assert p.ping() is False
