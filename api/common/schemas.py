# app/schemas.py
from __future__ import annotations
from typing import Any, Optional, Dict, List
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
    permission_level: Optional[str] = Field(default="user", pattern=r"^(admin|user)$")
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


# ---------- 设备管理 ----------
class DeviceCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    sn: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)


class DeviceUpdate(StrictModel):
    id: int
    name: Optional[str] = Field(default=None)
    sn: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)


class DeviceOut(StrictModel):
    id: int
    name: str
    sn: str
    description: Optional[str] = None
    create_time: datetime
    update_time: datetime


# ---------- 操作管理 ----------
class OperationCreate(StrictModel):
    page_name: str = Field(min_length=1, max_length=255)
    action: str = Field(min_length=1, max_length=255)


class OperationUpdate(StrictModel):
    id: int
    page_name: Optional[str] = Field(default=None)
    action: Optional[str] = Field(default=None)


class OperationOut(StrictModel):
    id: int
    page_name: str
    action: str
    create_time: datetime
    update_time: datetime


# ---------- 任务管理 ----------
class TaskCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)


class TaskUpdate(StrictModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)


class TaskOut(StrictModel):
    id: int
    name: str
    create_time: datetime
    update_time: datetime


# ---------- 标签管理 ----------
class LabelCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)


class LabelUpdate(StrictModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)


class LabelOut(StrictModel):
    id: int
    name: str
    create_time: datetime
    update_time: datetime


# ---------- 用户设备权限管理 ----------
class UserDevicePermissionCreate(StrictModel):
    user_id: int
    device_id: int


class UserDevicePermissionOut(StrictModel):
    id: int
    user_id: int
    device_id: int
    create_time: datetime
    update_time: datetime


# ---------- 用户操作权限管理 ----------
class UserOperationPermissionCreate(StrictModel):
    user_id: int
    operation_id: int


class UserOperationPermissionOut(StrictModel):
    id: int
    user_id: int
    operation_id: int
    create_time: datetime
    update_time: datetime


# ---------- 数据文件管理 ----------
class DataFileCreate(StrictModel):
    task_id: int
    file_name: str = Field(min_length=1, max_length=500)
    download_url: str = Field(min_length=1, max_length=1000)
    duration_ms: Optional[int] = Field(default=None, ge=0)
    user_id: int
    device_id: int


class DataFileUpdate(StrictModel):
    task_id: Optional[int] = Field(default=None)
    file_name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    download_url: Optional[str] = Field(default=None, min_length=1, max_length=1000)
    duration_ms: Optional[int] = Field(default=None, ge=0)
    user_id: Optional[int] = Field(default=None)
    device_id: Optional[int] = Field(default=None)


class DataFileOut(StrictModel):
    id: int
    task_id: int
    file_name: str
    download_url: str
    duration_ms: Optional[int] = None
    user_id: int
    device_id: int
    create_time: datetime
    update_time: datetime


# ---------- 数据文件标签映射管理 ----------
class DataFileLabelCreate(StrictModel):
    data_file_id: int
    label_id: int


class DataFileLabelOut(StrictModel):
    id: int
    data_file_id: int
    label_id: int
    create_time: datetime
    update_time: datetime


# ---------- 操作日志管理 ----------
class OperationLogCreate(StrictModel):
    username: str = Field(min_length=1, max_length=150)
    action: str = Field(min_length=1, max_length=255)
    data_file_id: Optional[int] = Field(default=None)
    content: Optional[str] = Field(default=None, max_length=2000)


class OperationLogOut(StrictModel):
    id: int
    username: str
    action: str
    data_file_id: Optional[int] = None
    content: Optional[str] = None
    create_time: datetime
    update_time: datetime


# ---------- 批量权限管理 ----------
class UserPermissionsCreate(StrictModel):
    user_id: int = Field(description="用户ID")
    device_ids: Optional[List[int]] = Field(default=None, description="设备ID列表")
    operation_ids: Optional[List[int]] = Field(default=None, description="操作ID列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 1,
                "device_ids": [1, 2, 3],
                "operation_ids": [1, 2, 3]
            }
        }


# ---------- 用户权限查询 ----------
class UserPermissionsQuery(StrictModel):
    user_id: Optional[int] = Field(default=None, description="用户ID，为空则查询所有用户")
    page: Optional[int] = Field(default=1, ge=1, description="页码，从1开始")
    page_size: Optional[int] = Field(default=10, ge=1, le=100, description="每页数量，最大100")

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 1,
                "page": 1,
                "page_size": 10
            }
        }


# ---------- 用户权限修改 ----------
class UserPermissionsUpdate(StrictModel):
    user_id: int = Field(description="用户ID")
    device_ids: Optional[List[int]] = Field(default=None, description="设备ID列表，为空表示不修改设备权限")
    operation_ids: Optional[List[int]] = Field(default=None, description="操作ID列表，为空表示不修改操作权限")

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 1,
                "device_ids": [1, 2, 3],
                "operation_ids": [1, 2, 3]
            }
        }
