from email_providers.base import GeneratedEmail, InboxMessage


def test_generated_email_fields():
    g = GeneratedEmail(provider_account_id="42", address="abc@example.com", share_link="https://x")
    assert g.provider_account_id == "42"
    assert g.address == "abc@example.com"
    assert g.share_link == "https://x"


def test_generated_email_share_link_optional():
    g = GeneratedEmail(provider_account_id="42", address="abc@example.com", share_link=None)
    assert g.share_link is None


def test_inbox_message_fields():
    m = InboxMessage(id="99", subject="Confirm", text="Your code is 123456", received_at="2026-07-04T10:00:00Z")
    assert m.id == "99"
    assert "123456" in m.text
