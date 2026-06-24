from unittest.mock import MagicMock


def test_page_text_returns_inner_text(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "hello world"
    session = make_session()
    result = session._page_text(mock_page)
    assert result == "hello world"


def test_page_text_returns_empty_on_timeout(make_session, mock_page):
    from playwright.sync_api import Error as PlaywrightError

    mock_page.locator.return_value.inner_text.side_effect = PlaywrightError("timeout")
    session = make_session()
    result = session._page_text(mock_page)
    assert result == ""