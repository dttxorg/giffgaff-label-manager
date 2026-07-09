from unittest.mock import MagicMock, patch
import pytest

from email_providers.moemail import MoEmailProvider
from email_providers.base import InboxMessage


@pytest.fixture
def mocked_provider():
    """Provider with a stubbed MoEmailClient."""
    with patch("email_providers._moemail_client.httpx") as mock_httpx:
        client = MagicMock()
        with patch("email_providers.moemail.MoEmailClient", return_value=client):
            p = MoEmailProvider(url="https://moemail.test", api_key="k")
    return p, client


def test_provider_type():
    p = MoEmailProvider(url="https://x", api_key="k")
    assert p.provider_type == "moemail"


def test_generate_email_returns_generated_email(mocked_provider):
    p, client = mocked_provider
    client.generate_email.return_value = {"id": 7, "email": "abc@681218.xyz"}
    client.create_share_link.return_value = {"link": "https://share"}

    gen = p.generate_email()

    assert gen.provider_account_id == "7"
    assert gen.address == "abc@681218.xyz"
    assert gen.share_link == "https://share"


def test_generate_email_share_link_failure_is_tolerated(mocked_provider):
    """If create_share_link fails (e.g., not supported), share_link should be None, not raise."""
    p, client = mocked_provider
    client.generate_email.return_value = {"id": 7, "email": "abc@681218.xyz"}
    client.create_share_link.side_effect = Exception("404 not found")

    gen = p.generate_email()

    assert gen.share_link is None
    assert gen.address == "abc@681218.xyz"


def test_fetch_latest_messages(mocked_provider):
    p, client = mocked_provider
    client.get_email_messages.return_value = {
        "messages": [{"id": "1"}, {"id": "2"}]
    }
    client.get_message.side_effect = [
        {"text": "code 123456"},
        {"text": "no code here"},
    ]

    msgs = p.fetch_latest_messages("42")

    assert len(msgs) == 2
    assert msgs[0].id == "1"
    assert "123456" in msgs[0].text
    assert msgs[1].id == "2"


def test_fetch_latest_messages_filters_by_after_id(mocked_provider):
    p, client = mocked_provider
    client.get_email_messages.return_value = {
        "messages": [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    }
    client.get_message.return_value = {"text": "hi"}

    msgs = p.fetch_latest_messages("42", after_message_id="2")
    # Only message "3" has id > "2"
    assert len(msgs) == 1
    assert msgs[0].id == "3"


def test_extract_verification_code():
    p = MoEmailProvider(url="https://x", api_key="k")
    msg = InboxMessage(id="1", subject="x", text="Your code is 123456", received_at="t")
    assert p.extract_verification_code(msg) == "123456"


def test_extract_verification_code_returns_none_when_absent():
    p = MoEmailProvider(url="https://x", api_key="k")
    msg = InboxMessage(id="1", subject="x", text="no code", received_at="t")
    assert p.extract_verification_code(msg) is None


def test_ping_true_on_success(mocked_provider):
    p, client = mocked_provider
    client.get_config.return_value = {"emailDomains": "x,y"}
    assert p.ping() is True


def test_ping_false_on_failure(mocked_provider):
    p, client = mocked_provider
    client.get_config.side_effect = Exception("network down")
    assert p.ping() is False

# beilunyang/moemail only accepts these four values for `expiryTime`:
#   0          (永久, expiresAt = "9999-01-01")
#   3600000    (1 hour)
#   86400000   (1 day)
#   259200000  (3 days)
# See app/types/email.ts in the upstream repo. Any other value is rejected
# with 400 `{"error":"无效的过期时间"}`. We default to 0 (=永久) so the
# inbox stays reachable for the lifetime of the giffgaff customer.
ACCEPTED_EXPIRY_TIME_MS = (0, 3_600_000, 86_400_000, 259_200_000)


def test_default_expiry_time_is_zero():
    """The default must be 0 (=永久). Any other value gets rejected."""
    from email_providers.moemail import DEFAULT_EXPIRY_TIME_MS
    assert DEFAULT_EXPIRY_TIME_MS == 0, (
        f"DEFAULT_EXPIRY_TIME_MS must be 0 (永久), got {DEFAULT_EXPIRY_TIME_MS}"
    )
    assert DEFAULT_EXPIRY_TIME_MS in ACCEPTED_EXPIRY_TIME_MS


def test_generate_email_sends_default_expiry_time_ms():
    """Regression: the default must be 0 (=永久), accepted by the
    upstream beilunyang/moemail server's whitelist.
    """
    from email_providers.moemail import DEFAULT_EXPIRY_TIME_MS
    with patch("email_providers._moemail_client.httpx") as mock_httpx:
        client = MagicMock()
        with patch("email_providers.moemail.MoEmailClient", return_value=client):
            p = MoEmailProvider(url="https://moemail.test", api_key="k")
        client.generate_email.return_value = {"id": 1, "email": "a@b.test"}
        client.create_share_link.return_value = {"link": "x"}
        p.generate_email()
        sent = client.generate_email.call_args.kwargs["expiry_time"]
        assert sent == DEFAULT_EXPIRY_TIME_MS == 0
        assert sent in ACCEPTED_EXPIRY_TIME_MS


def test_provider_expiry_time_ms_override():
    """Per-provider `expiry_time_ms` overrides the default. The override
    must still be a value the upstream server accepts, otherwise the
    server returns 400 `{"error":"无效的过期时间"}`.
    """
    with patch("email_providers._moemail_client.httpx") as mock_httpx:
        client = MagicMock()
        with patch("email_providers.moemail.MoEmailClient", return_value=client):
            p = MoEmailProvider(
                url="https://moemail.test", api_key="k",
                expiry_time_ms=259200000,  # 3 days
            )
        client.generate_email.return_value = {"id": 1, "email": "a@b.test"}
        client.create_share_link.return_value = {"link": "x"}
        p.generate_email()
        sent = client.generate_email.call_args.kwargs["expiry_time"]
        assert sent == 259200000
        assert sent in ACCEPTED_EXPIRY_TIME_MS
