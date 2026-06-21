import pytest
from app.exceptions import (
    BusinessError,
    ValidationError,
    NotFoundError,
    StateConflictError,
    BlacklistBlockedError,
    BlacklistGrayError,
    PenaltyBlockedError,
)


def test_business_error_basic():
    err = BusinessError(title="测试错误", description="这是描述")
    assert err.title == "测试错误"
    assert err.description == "这是描述"
    assert err.code == 400
    assert str(err) == "测试错误: 这是描述"


def test_business_error_with_code():
    err = BusinessError(title="未找到", description="资源不存在", code=404)
    assert err.code == 404


def test_business_error_to_http():
    import falcon
    err = BusinessError(title="参数错误", description="手机号不能为空", code=400)
    http_err = err.to_http()
    assert isinstance(http_err, falcon.HTTPError)
    assert http_err.status.split(" ")[0] == "400"


def test_validation_error():
    err = ValidationError(title="参数错误", description="手机号格式不正确")
    assert isinstance(err, BusinessError)
    assert err.code == 400


def test_not_found_error():
    err = NotFoundError(title="未找到", description="排队记录不存在")
    assert isinstance(err, BusinessError)
    assert err.code == 404


def test_state_conflict_error():
    err = StateConflictError(title="状态冲突", description="当前状态不允许此操作")
    assert isinstance(err, BusinessError)
    assert err.code == 409


def test_blacklist_blocked_error():
    err = BlacklistBlockedError(description="您已被列入黑名单")
    assert isinstance(err, BusinessError)
    assert err.title == "黑名单限制"
    assert err.code == 403


def test_blacklist_gray_error():
    err = BlacklistGrayError(description="您处于灰名单状态，需管理员验证")
    assert isinstance(err, BusinessError)
    assert err.title == "灰名单提醒"


def test_penalty_blocked_error():
    err = PenaltyBlockedError(description="您已爽约3次，7天内无法取号")
    assert isinstance(err, BusinessError)
    assert err.title == "爽约惩罚"
    assert err.code == 403
