from unittest.mock import MagicMock

from giffgaff_client.api import ApiError


def test_returns_true_when_code_arrives(make_session, mock_page, mock_agent_api):
    mock_agent_api.verification_code.side_effect = [
        {"code": ""},
        {"code": ""},
        {"code": "123456"},
    ]
    session = make_session(agent_api=mock_agent_api)
    session._fill_verification_code = MagicMock()
    result = session._try_poll_and_fill_verification_code(mock_page, timeout_seconds=10)
    assert result is True
    session._fill_verification_code.assert_called_once_with(mock_page, "123456")
    assert mock_agent_api.verification_code.call_count == 3


def test_returns_false_on_timeout(make_session, mock_page, mock_agent_api):
    mock_agent_api.verification_code.return_value = {"code": ""}
    session = make_session(agent_api=mock_agent_api)
    session._fill_verification_code = MagicMock()
    result = session._try_poll_and_fill_verification_code(mock_page, timeout_seconds=2)
    assert result is False
    session._fill_verification_code.assert_not_called()


def test_continues_through_api_errors(make_session, mock_page, mock_agent_api):
    mock_agent_api.verification_code.side_effect = [
        ApiError("transient"),
        {"code": ""},
        {"code": "654321"},
    ]
    session = make_session(agent_api=mock_agent_api)
    session._fill_verification_code = MagicMock()
    result = session._try_poll_and_fill_verification_code(mock_page, timeout_seconds=10)
    assert result is True
    session._fill_verification_code.assert_called_once_with(mock_page, "654321")


def test_returns_false_on_stop_requested(make_session, mock_page, mock_agent_api):
    mock_agent_api.verification_code.return_value = {"code": "777777"}
    session = make_session(agent_api=mock_agent_api)
    session._fill_verification_code = MagicMock()
    session.stop_requested = True
    result = session._try_poll_and_fill_verification_code(mock_page, timeout_seconds=10)
    assert result is False
    session._fill_verification_code.assert_not_called()


def test_logs_stuck_when_no_api(make_session, mock_page):
    session = make_session(agent_api=None)
    session._log_stuck = MagicMock()
    result = session._try_poll_and_fill_verification_code(mock_page, timeout_seconds=1)
    assert result is False
    session._log_stuck.assert_called_once()
    assert "邮箱验证码" in session._log_stuck.call_args.args[0]