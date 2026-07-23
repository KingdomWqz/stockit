import jwt
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

SECRET = "stockit-dev-secret"
TEST_USER = {"id": 1, "username": "admin", "password": "admin123"}


class LoginRequest(BaseModel):
    username: str
    password: str


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
