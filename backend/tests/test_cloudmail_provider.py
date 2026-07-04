from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from email_providers.cloudmail import CloudMailProvider


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
