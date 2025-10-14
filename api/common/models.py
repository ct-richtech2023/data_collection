from sqlalchemy import Column, Integer, String, DateTime, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from .database import Base


# 权限级别常量
class PermissionLevel:
    ADMIN = "admin"        # 管理员：完全权限
    UPLOADER = "uploader"  # 上传者：可以上传和管理自己的数据
    VIEWER = "viewer"      # 查看者：只能查看数据


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(150), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password = Column(String(255), nullable=False)  # 存储加密后的哈希
    permission_level = Column(String(20), nullable=False, default=PermissionLevel.VIEWER)  # 用户权限级别
    extra = Column(JSONB, nullable=True)  # 扩展字段，存储任意 JSON

    create_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now(), nullable=False)
    
    def has_permission(self, required_level):
        """检查用户是否有指定权限级别"""
        level_hierarchy = {
            PermissionLevel.VIEWER: 1,
            PermissionLevel.UPLOADER: 2,
            PermissionLevel.ADMIN: 3
        }
        user_level = level_hierarchy.get(self.permission_level, 0)
        required_level_value = level_hierarchy.get(required_level, 0)
        return user_level >= required_level_value
    
    def is_admin(self):
        """检查是否为管理员"""
        return self.permission_level == PermissionLevel.ADMIN
    
    def is_uploader(self):
        """检查是否为上传者或管理员"""
        return self.has_permission(PermissionLevel.UPLOADER)
    
    def is_viewer(self):
        """检查是否为查看者或更高权限"""
        return self.has_permission(PermissionLevel.VIEWER)


