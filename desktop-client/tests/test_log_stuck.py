def test_log_stuck_writes_structured_message(make_session):
    session = make_session()
    session._log_stuck("邮箱验证码", "拉取 90s 未拿到")
    assert any("【卡住】邮箱验证码" in line for line in session.log_lines)
    assert any("拉取 90s 未拿到" in line for line in session.log_lines)


def test_log_stuck_calls_add_log_with_step(make_session, mock_agent_api):
    session = make_session(agent_api=mock_agent_api)
    session._log_stuck("选套餐", "重试 3 次均失败")
    mock_agent_api.add_log.assert_called_once()
    args, kwargs = mock_agent_api.add_log.call_args
    assert args[0] == 1  # customer_id
    assert "选套餐" in args[1]
    assert kwargs.get("step") == "auto_stuck"


def test_log_stuck_does_not_raise_when_api_fails(make_session, mock_agent_api):
    from giffgaff_client.api import ApiError

    mock_agent_api.add_log.side_effect = ApiError("backend down")
    session = make_session(agent_api=mock_agent_api)
    session._log_stuck("未知页面", "URL=/foo")  # should not raise
    assert any("未知页面" in line for line in session.log_lines)


def test_log_stuck_skips_add_log_when_no_customer_id(make_session, mock_agent_api):
    session = make_session(task={"customer_id": None})
    session._log_stuck("密码页", "no password")
    mock_agent_api.add_log.assert_not_called()