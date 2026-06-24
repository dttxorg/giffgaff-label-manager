from unittest.mock import MagicMock


def _page_with_text(text: str) -> MagicMock:
    page = MagicMock()
    page.url = "https://www.giffgaff.com/activate"
    page.locator.return_value.inner_text.return_value = text
    return page


def test_stops_on_payment_page(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Card details - payment"
    session = make_session()
    session._auto_run_until_payment(mock_page)
    assert session.payment_page_seen is True
    assert any("付款页" in line for line in session.log_lines)


def test_stops_on_unknown_page(make_session, mock_page):
    mock_page.url = "https://www.giffgaff.com/foo"
    mock_page.locator.return_value.inner_text.return_value = "Random unrelated page"
    session = make_session()
    session._auto_run_until_payment(mock_page)
    assert any("未知页面" in line for line in session.log_lines)


def test_stops_immediately_when_stop_requested(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Choose a monthly plan"
    session = make_session()
    session.stop_requested = True
    session._choose_pay_as_you_go = MagicMock()
    session._auto_run_until_payment(mock_page)
    session._choose_pay_as_you_go.assert_not_called()


def test_dispatches_to_password_handler(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Create a password"
    session = make_session()
    session._continue_after_password_if_visible = MagicMock()

    def stop_after_first(_page, _password):
        session.stop_requested = True

    session._continue_after_password_if_visible.side_effect = stop_after_first
    session._auto_run_until_payment(mock_page)
    session._continue_after_password_if_visible.assert_called_once()


def test_dispatches_to_stay_in_touch_handler(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Let's stay in touch"
    session = make_session()
    session._continue_registration_preferences = MagicMock(
        side_effect=lambda p: setattr(session, "stop_requested", True)
    )
    session._auto_run_until_payment(mock_page)
    session._continue_registration_preferences.assert_called_once()


def test_dispatches_to_payg_handler(make_session, mock_page):
    mock_page.locator.return_value.inner_text.return_value = "Choose a monthly plan"
    session = make_session()

    def advance(_page):
        # Simulate page transition after plan selection
        mock_page.locator.return_value.inner_text.return_value = "Payment page"
        return True

    session._choose_pay_as_you_go = MagicMock(side_effect=advance)
    session._auto_run_until_payment(mock_page)
    session._choose_pay_as_you_go.assert_called_once()


def test_dispatches_to_verification_handler(make_session, mock_page, mock_agent_api):
    mock_page.locator.return_value.inner_text.return_value = "Confirm your email"
    session = make_session(agent_api=mock_agent_api)

    def advance(_page):
        mock_page.locator.return_value.inner_text.return_value = "Payment page"
        return True

    session._try_poll_and_fill_verification_code = MagicMock(side_effect=advance)
    session._auto_run_until_payment(mock_page)
    session._try_poll_and_fill_verification_code.assert_called_once()