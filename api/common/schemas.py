# app/schemas.py
from __future__ import annotations
from typing import Any, Optional, Dict
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        from_attributes=True,
    )

class User(StrictModel):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_\.]+$")
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    permission_level: Optional[str] = Field(default="viewer", pattern=r"^(admin|uploader|viewer)$")
    extra: Optional[Dict[str, Any]] = None


class UserLogin(StrictModel):
    username: str
    password: str


class UserUpdate(StrictModel):
    id: int
    username: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    password: Optional[str] = Field(default=None)
    permission_level: Optional[str] = Field(default=None)
    extra: Optional[Dict[str, Any]] = None



# ---------- 认证 ----------
class Token(StrictModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(StrictModel):
    # 例如：JWT 的主体，一般放 username 或 email
    sub: str
    exp: int  # 过期时间（Unix 时间戳）
