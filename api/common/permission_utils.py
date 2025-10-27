# permission_utils.py
from sqlalchemy.orm import Session
from typing import List, Set
from . import models


class PermissionUtils:
    """权限检查工具类"""
    
    @staticmethod
    def _get_user_info(db: Session, user_id: int):
        """获取用户信息（带缓存）"""
        user = db.query(models.User).filter(models.User.id == user_id).first()
        return user
    
    @staticmethod
    def get_user_device_permissions(db: Session, user_id: int) -> Set[int]:
        """获取用户有权限的设备ID列表"""
        permissions = db.query(models.UserDevicePermission).filter(
            models.UserDevicePermission.user_id == user_id
        ).all()
        return {perm.device_id for perm in permissions}
    
    @staticmethod
    def get_user_operation_permissions(db: Session, user_id: int) -> Set[int]:
        """获取用户有权限的操作ID列表"""
        permissions = db.query(models.UserOperationPermission).filter(
            models.UserOperationPermission.user_id == user_id
        ).all()
        return {perm.operation_id for perm in permissions}
    
    @staticmethod
    def get_operation_by_name_and_action(db: Session, page_name: str, action: str) -> models.Operation:
        """根据页面名称和操作名称获取操作对象"""
        return db.query(models.Operation).filter(
            models.Operation.page_name == page_name,
            models.Operation.action == action
        ).first()
    
    @staticmethod
    def check_device_permission(db: Session, user_id: int, device_id: int) -> bool:
        """检查用户是否有指定设备的权限"""
        if user_id is None or device_id is None:
            return False
        
        # 检查用户是否为管理员
        user = PermissionUtils._get_user_info(db, user_id)
        if user and user.is_admin():
            return True
        
        permission = db.query(models.UserDevicePermission).filter(
            models.UserDevicePermission.user_id == user_id,
            models.UserDevicePermission.device_id == device_id
        ).first()
        return permission is not None
    
    @staticmethod
    def check_operation_permission(db: Session, user_id: int, page_name: str, action: str) -> bool:
        """检查用户是否有指定操作的权限"""
        if user_id is None:
            return False
        
        # 检查用户是否为管理员
        user = PermissionUtils._get_user_info(db, user_id)
        if user and user.is_admin():
            return True
        
        # 获取操作对象
        operation = PermissionUtils.get_operation_by_name_and_action(db, page_name, action)
        if not operation:
            return False
        
        # 检查用户是否有该操作的权限
        permission = db.query(models.UserOperationPermission).filter(
            models.UserOperationPermission.user_id == user_id,
            models.UserOperationPermission.operation_id == operation.id
        ).first()
        return permission is not None
    
    @staticmethod
    def get_accessible_datafiles_query(db: Session, user_id: int, base_query=None):
        """获取用户可访问的数据文件查询（基于设备权限）"""
        if base_query is None:
            base_query = db.query(models.DataFile)
        
        # 检查用户是否为管理员
        user = PermissionUtils._get_user_info(db, user_id)
        if user and user.is_admin():
            # 管理员可以访问所有数据文件
            return base_query
        
        # 获取用户有权限的设备ID
        device_ids = PermissionUtils.get_user_device_permissions(db, user_id)
        
        if not device_ids:
            # 如果用户没有任何设备权限，返回空查询
            return base_query.filter(False)
        
        # 只返回用户有权限的设备的数据文件
        return base_query.filter(models.DataFile.device_id.in_(device_ids))
    
    @staticmethod
    def check_datafile_access(db: Session, user_id: int, datafile_id: int) -> bool:
        """检查用户是否可以访问指定的数据文件"""
        datafile = db.query(models.DataFile).filter(models.DataFile.id == datafile_id).first()
        if not datafile:
            return False
        
        # 检查用户是否为管理员
        user = PermissionUtils._get_user_info(db, user_id)
        if user and user.is_admin():
            return True
        
        return PermissionUtils.check_device_permission(db, user_id, datafile.device_id)
