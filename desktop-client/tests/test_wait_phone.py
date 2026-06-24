from unittest.mock import MagicMock

from giffgaff_client.automation import BrowserSession


def test_returns_phone_when_text_matches(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = (
        "Your giffgaff number is 07732 212776"
    )
    session = make_session()
    result = session._wait_and_extract_phone_number(mock_page, timeout_seconds=1)
    assert result == "07732212776"


def test_returns_empty_when_text_has_no_phone(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Loading..."
    session = make_session()
    result = session._wait_and_extract_phone_number(mock_page, timeout_seconds=1)
    assert result == ""


def test_returns_empty_on_stop_requested(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Your number is 07732 212776"
    session = make_session()
    session.stop_requested = True
    result = session._wait_and_extract_phone_number(mock_page, timeout_seconds=10)
    assert result == ""


def test_first_match_wins(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = (
        "07711 222333 / 07744 555666"
    )
    session = make_session()
    result = session._wait_and_extract_phone_number(mock_page, timeout_seconds=1)
    assert result == "07711222333"