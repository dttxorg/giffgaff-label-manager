from giffgaff_client.api import ApiError


def test_reports_phone_with_default_status(make_session, mock_agent_api):
    session = make_session(agent_api=mock_agent_api)
    session._report_phone_number_to_backend("07732212776")
    mock_agent_api.update_result.assert_called_once()
    args, kwargs = mock_agent_api.update_result.call_args
    assert args[0] == 1  # customer_id
    assert kwargs["phone_number"] == "07732212776"
    assert kwargs["status"] == "等待转 eSIM"
    assert any("07732212776" in line for line in session.log_lines)


def test_reports_phone_with_custom_status(make_session, mock_agent_api):
    session = make_session(agent_api=mock_agent_api)
    session._report_phone_number_to_backend("07732212776", status="已完成")
    args, kwargs = mock_agent_api.update_result.call_args
    assert kwargs["status"] == "已完成"


def test_logs_only_when_no_customer_id(make_session, mock_agent_api):
    session = make_session(task={"customer_id": None}, agent_api=mock_agent_api)
    session._report_phone_number_to_backend("07732212776")
    mock_agent_api.update_result.assert_not_called()
    assert any("本地记录" in line for line in session.log_lines)


def test_logs_only_when_no_api(make_session):
    session = make_session(agent_api=None)
    session._report_phone_number_to_backend("07732212776")
    assert any("本地记录" in line for line in session.log_lines)


def test_catches_api_error(make_session, mock_agent_api):
    mock_agent_api.update_result.side_effect = ApiError("network down")
    session = make_session(agent_api=mock_agent_api)
    session._report_phone_number_to_backend("07732212776")
    assert any("回传手机号失败" in line for line in session.log_lines)