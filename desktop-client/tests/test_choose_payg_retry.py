from unittest.mock import MagicMock

from giffgaff_client.automation import BrowserSession


def _make_page_with_text(text: str) -> MagicMock:
    page = MagicMock()
    page.url = "https://www.giffgaff.com/activate"
    page.locator.return_value.inner_text.return_value = text
    return page


def test_returns_false_when_page_does_not_match(make_session):
    page = _make_page_with_text("Some unrelated page")
    session = make_session()
    assert session._choose_pay_as_you_go(page) is False


def test_returns_true_on_first_attempt(make_session):
    page = _make_page_with_text("Choose a monthly plan")
    session = make_session()
    session._try_click_text = MagicMock(return_value=True)
    session._try_click_button = MagicMock(return_value=True)
    session._wait_ready = MagicMock()
    session._page_has_text = MagicMock(return_value=True)
    assert session._choose_pay_as_you_go(page) is True
    assert session._try_click_text.call_count == 1


def test_retries_then_succeeds(make_session):
    page = _make_page_with_text("Choose a monthly plan")
    session = make_session()
    session._try_click_text = MagicMock(side_effect=[False, False, True])
    session._try_click_button = MagicMock(return_value=True)
    session._wait_ready = MagicMock()
    session._page_has_text = MagicMock(return_value=True)
    assert session._choose_pay_as_you_go(page) is True
    assert session._try_click_text.call_count == 3


def test_returns_false_after_three_failures(make_session):
    page = _make_page_with_text("Choose a monthly plan")
    session = make_session()
    session._try_click_text = MagicMock(return_value=False)
    session._page_has_text = MagicMock(return_value=True)
    assert session._choose_pay_as_you_go(page) is False
    assert session._try_click_text.call_count == 3


def test_returns_early_on_stop_requested(make_session):
    page = _make_page_with_text("Choose a monthly plan")
    session = make_session()
    session.stop_requested = True
    session._page_has_text = MagicMock(return_value=True)
    session._try_click_text = MagicMock(return_value=True)
    assert session._choose_pay_as_you_go(page) is False
    session._try_click_text.assert_not_called()