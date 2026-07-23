import time

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

router = APIRouter()

SECRET = "stockit-dev-secret"
TEST_USER = {"id": 1, "username": "admin", "password": "admin123"}

security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """从 Bearer token 解码 JWT，返回当前用户；缺失或无效时返回 401。"""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="未认证")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    return {"user_id": payload.get("user_id"), "username": payload.get("username")}


@router.post("/auth/login")
def login(body: LoginRequest):
    if body.username != TEST_USER["username"] or body.password != TEST_USER["password"]:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = jwt.encode(
        {"user_id": TEST_USER["id"], "username": TEST_USER["username"], "exp": int(time.time()) + 86400 * 7},
        SECRET,
        algorithm="HS256",
    )

    return {
        "token": token,
        "user": {"id": TEST_USER["id"], "username": TEST_USER["username"]},
    }
