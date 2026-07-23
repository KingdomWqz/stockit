import time

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from auth import SECRET, get_current_user


def _token(**overrides):
    payload = {"user_id": 1, "username": "admin", "exp": int(time.time()) + 3600}
    payload.update(overrides)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def _creds(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_valid_token_returns_user():
    user = get_current_user(_creds(_token()))
    assert user["user_id"] == 1
    assert user["username"] == "admin"


def test_missing_credentials_returns_401():
    with pytest.raises(HTTPException) as exc:
        get_current_user(None)
    assert exc.value.status_code == 401


def test_invalid_token_returns_401():
    with pytest.raises(HTTPException) as exc:
        get_current_user(_creds("not-a-jwt"))
    assert exc.value.status_code == 401


def test_expired_token_returns_401():
    token = _token(exp=int(time.time()) - 10)
    with pytest.raises(HTTPException) as exc:
        get_current_user(_creds(token))
    assert exc.value.status_code == 401
