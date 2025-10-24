# app/schemas.py
from __future__ import annotations
from typing import Any, Optional, Dict, List
from datetime import datetime, date
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


class DeviceQuery(StrictModel):
    device_id: Optional[int] = Field(default=None, description="设备ID，为空则查询所有设备")
    name: Optional[str] = Field(default=None, description="设备名称，支持模糊查询")
    sn: Optional[str] = Field(default=None, description="设备SN，支持模糊查询")
    page: Optional[int] = Field(default=1, ge=1, description="页码，从1开始")
    page_size: Optional[int] = Field(default=10, ge=1, le=100, description="每页数量，最大100")

    class Config:
        json_schema_extra = {
            "example": {
                "device_id": 1,
                "name": "设备",
                "sn": "SN123",
                "page": 1,
                "page_size": 10
            }
        }


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


class OperationQuery(StrictModel):
    operation_id: Optional[int] = Field(default=None, description="操作ID，为空则查询所有操作")
    page_name: Optional[str] = Field(default=None, description="页面名称，支持模糊查询")
    action: Optional[str] = Field(default=None, description="操作动作，支持模糊查询")
    page: Optional[int] = Field(default=1, ge=1, description="页码，从1开始")
    page_size: Optional[int] = Field(default=10, ge=1, le=100, description="每页数量，最大100")

    class Config:
        json_schema_extra = {
            "example": {
                "operation_id": 1,
                "page_name": "用户管理",
                "action": "查看",
                "page": 1,
                "page_size": 10
            }
        }


# ---------- 任务管理 ----------
class TaskCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)


class TaskUpdate(StrictModel):
    id: int = Field(..., description="任务ID")
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)


class TaskOut(StrictModel):
    id: int
    name: str
    create_time: datetime
    update_time: datetime


class TaskQuery(StrictModel):
    task_id: Optional[int] = Field(default=None, description="任务ID，为空则查询所有任务")
    name: Optional[str] = Field(default=None, description="任务名称，支持模糊查询")
    page: Optional[int] = Field(default=1, ge=1, description="页码，从1开始")
    page_size: Optional[int] = Field(default=10, ge=1, le=100, description="每页数量，最大100")

    class Config:
        json_schema_extra = {
            "example": {
                "task_id": 1,
                "name": "任务",
                "page": 1,
                "page_size": 10
            }
        }


# ---------- 标签管理 ----------
class LabelCreate(StrictModel):
    name: str = Field(min_length=1, max_length=255)


class LabelUpdate(StrictModel):
    id: int = Field(..., description="标签ID")
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)


class LabelOut(StrictModel):
    id: int
    name: str
    create_time: datetime
    update_time: datetime


class LabelQuery(StrictModel):
    label_id: Optional[int] = Field(default=None, description="标签ID，为空则查询所有标签")
    name: Optional[str] = Field(default=None, description="标签名称，支持模糊查询")
    page: Optional[int] = Field(default=1, ge=1, description="页码，从1开始")
    page_size: Optional[int] = Field(default=10, ge=1, le=100, description="每页数量，最大100")

    class Config:
        json_schema_extra = {
            "example": {
                "label_id": 1,
                "name": "标签",
                "page": 1,
                "page_size": 10
            }
        }


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
    id: int = Field(..., description="数据文件ID")
    file_name: Optional[str] = Field(default=None, min_length=1, max_length=500)
    device_id: Optional[int] = Field(default=None)
    label_ids: Optional[List[int]] = Field(default=None, description="标签ID列表，可选")


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


class DataFileUpload(StrictModel):
    task_id: int = Field(..., description="任务ID")
    device_id: int = Field(..., description="设备ID")
    label_ids: Optional[List[int]] = Field(default=[], description="标签ID列表，可选")

    class Config:
        json_schema_extra = {
            "example": {
                "task_id": 1,
                "device_id": 1,
                "label_ids": [1, 2, 3]
            }
        }


class DataFileQuery(StrictModel):
    data_file_id: Optional[int] = Field(default=None, description="数据文件ID，为空则查询所有文件")
    task_id: Optional[int] = Field(default=None, description="任务ID，为空则查询所有任务的文件")
    user_id: Optional[int] = Field(default=None, description="用户ID，为空则查询所有用户的文件")
    device_id: Optional[int] = Field(default=None, description="设备ID，为空则查询所有设备的文件")
    start_date: Optional[date] = Field(default=None, description="开始日期，筛选创建日期大于等于此日期的文件")
    end_date: Optional[date] = Field(default=None, description="结束日期，筛选创建日期小于等于此日期的文件")
    page: Optional[int] = Field(default=1, ge=1, description="页码，从1开始")
    page_size: Optional[int] = Field(default=10, ge=1, le=100, description="每页数量，最大100")

    class Config:
        json_schema_extra = {
            "example": {
                "data_file_id": 1,
                "task_id": 1,
                "user_id": 1,
                "device_id": 1,
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "page": 1,
                "page_size": 10
            }
        }


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
