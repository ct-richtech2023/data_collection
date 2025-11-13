from sqlalchemy import Column, Integer, String, DateTime, func, UniqueConstraint, Text, BigInteger, Index
from sqlalchemy.dialects.postgresql import JSONB
from .database import Base


# 权限级别常量
class PermissionLevel:
    ADMIN = "admin"        # 管理员：完全权限
    USER = "user"          # 普通用户：只能查看数据


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(150), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    password = Column(String(255), nullable=False)  # 存储加密后的哈希
    permission_level = Column(String(20), nullable=False, default=PermissionLevel.USER)  # 用户权限级别
    extra = Column(JSONB, nullable=True)  # 扩展字段，存储任意 JSON

    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)
    
    def has_permission(self, required_level):
        """检查用户是否有指定权限级别"""
        level_hierarchy = {
            PermissionLevel.USER: 1,
            PermissionLevel.ADMIN: 2
        }
        user_level = level_hierarchy.get(self.permission_level, 0)
        required_level_value = level_hierarchy.get(required_level, 0)
        return user_level >= required_level_value
    
    def is_admin(self):
        """检查是否为管理员"""
        return self.permission_level == PermissionLevel.ADMIN
    
    def is_user(self):
        """检查是否为普通用户或管理员"""
        return self.has_permission(PermissionLevel.USER)


class Device(Base):
    """设备表"""
    __tablename__ = "device"
    __table_args__ = (
        UniqueConstraint("sn", name="uq_device_sn"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)  # 设备名称
    sn = Column(Text, nullable=False, unique=True, index=True)  # 设备序列号
    description = Column(Text, nullable=True)  # 设备描述
    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)


class Operation(Base):
    """操作表"""
    __tablename__ = "operation"
    __table_args__ = (
        UniqueConstraint("page_name", "action", name="uq_operation_page_action"),
    )

    id = Column(Integer, primary_key=True, index=True)
    page_name = Column(Text, nullable=False)  # 页面名称
    action = Column(Text, nullable=False)  # 操作类型（查询/上传/下载/删除等）
    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)


class Task(Base):
    """任务表"""
    __tablename__ = "task"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)  # 任务名称
    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)


class Label(Base):
    """标签表"""
    __tablename__ = "label"
    __table_args__ = (
        UniqueConstraint("name", name="uq_label_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False, unique=True, index=True)  # 标签名称
    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)


class UserDevicePermission(Base):
    """用户设备权限表"""
    __tablename__ = "user_device_permission"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_user_device_permission"),
        Index("ix_user_device_permission_user_id", "user_id"),
        Index("ix_user_device_permission_device_id", "device_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    device_id = Column(Integer, nullable=False, index=True)
    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)


class UserOperationPermission(Base):
    """用户操作权限表"""
    __tablename__ = "user_operation_permission"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_id", name="uq_user_operation_permission"),
        Index("ix_user_operation_permission_user_id", "user_id"),
        Index("ix_user_operation_permission_operation_id", "operation_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    operation_id = Column(Integer, nullable=False, index=True)
    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)


class DataFile(Base):
    """数据采集文件表"""
    __tablename__ = "data_file"
    __table_args__ = (
        Index("ix_data_file_task_id", "task_id"),
        Index("ix_data_file_user_id", "user_id"),
        Index("ix_data_file_device_id", "device_id"),
        Index("ix_data_file_create_time", "create_time"),
    )

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False, index=True)
    file_name = Column(Text, nullable=False)  # 文件名称（如 .mcap 文件）
    download_url = Column(Text, nullable=False)  # 下载地址
    duration_ms = Column(BigInteger, nullable=True)  # 文件时长（毫秒）
    user_id = Column(Integer, nullable=False, index=True)
    device_id = Column(Integer, nullable=False, index=True)
    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)


class DataFileLabel(Base):
    """数据文件标签映射表"""
    __tablename__ = "data_file_label"
    __table_args__ = (
        UniqueConstraint("data_file_id", "label_id", name="uq_data_file_label"),
        Index("ix_data_file_label_data_file_id", "data_file_id"),
        Index("ix_data_file_label_label_id", "label_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    data_file_id = Column(Integer, nullable=False, index=True)
    label_id = Column(Integer, nullable=False, index=True)
    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)


class OperationLog(Base):
    """操作日志表"""
    __tablename__ = "operation_log"
    __table_args__ = (
        Index("ix_operation_log_username", "username"),
        Index("ix_operation_log_create_time", "create_time"),
        Index("ix_operation_log_data_file_id", "data_file_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(Text, nullable=False, index=True)  # 操作人用户名
    action = Column(Text, nullable=False)  # 操作类型
    data_file_id = Column(Integer, nullable=True, index=True)  # 关联数据文件（可选）
    content = Column(Text, nullable=True)  # 操作内容描述
    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)


class ZipDataFile(Base):
    """ZIP数据文件表"""
    __tablename__ = "zip_data_file"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(Text, nullable=False)  # 文件名称（如 .zip 文件）
    file_size = Column(BigInteger, nullable=False)  # 文件大小
    download_number = Column(Integer, nullable=False)  # 下载次数  默认为0
    download_url = Column(Text, nullable=False)  # 下载地址
    user_id = Column(Integer, nullable=False, index=True)
    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)
