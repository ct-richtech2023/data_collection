"""
操作日志工具类
提供统一的操作日志记录功能
"""
from sqlalchemy.orm import Session
from . import models
from typing import Optional


class OperationLogUtil:
    """操作日志工具类"""
    
    @staticmethod
    def create_log(
        db: Session,
        username: str,
        action: str,
        content: str,
        data_file_id: Optional[int] = None
    ) -> bool:
        """
        创建操作日志
        
        Args:
            db: 数据库会话
            username: 操作用户名
            action: 操作类型
            content: 操作内容描述
            data_file_id: 关联的数据文件ID（可选）
            
        Returns:
            bool: 是否成功创建日志
        """
        try:
            log = models.OperationLog(
                username=username,
                action=action,
                data_file_id=data_file_id,
                content=content
            )
            db.add(log)
            db.commit()
            return True
        except Exception as e:
            print(f"记录操作日志失败: {e}")
            db.rollback()
            return False
    
    @staticmethod
    def log_user_login(db: Session, username: str) -> bool:
        """记录用户登录日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=username,
            action="用户登录",
            content=f"用户 {username} 成功登录系统"
        )
    
    @staticmethod
    def log_user_register(
        db: Session, 
        admin_username: str, 
        new_username: str, 
        permission_level: str
    ) -> bool:
        """记录用户注册日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=admin_username,
            action="用户注册",
            content=f"管理员 {admin_username} 注册了新用户 {new_username}，权限级别: {permission_level}"
        )
    
    @staticmethod
    def log_file_upload(
        db: Session,
        username: str,
        filename: str,
        data_file_id: int,
        task_id: int,
        device_id: int
    ) -> bool:
        """记录文件上传日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=username,
            action="文件上传",
            data_file_id=data_file_id,
            content=f"用户 {username} 上传了文件 {filename}，关联任务ID: {task_id}，设备ID: {device_id}"
        )
    
    @staticmethod
    def log_file_download(
        db: Session,
        username: str,
        file_count: int,
        file_ids: list
    ) -> bool:
        """记录文件下载日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=username,
            action="批量文件下载",
            content=f"用户 {username} 批量下载了 {file_count} 个文件，文件ID: {file_ids}"
        )
    
    @staticmethod
    def log_file_delete(
        db: Session,
        username: str,
        filename: str,
        data_file_id: int
    ) -> bool:
        """记录文件删除日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=username,
            action="文件删除",
            data_file_id=data_file_id,
            content=f"用户 {username} 删除了文件 {filename}"
        )
    
    @staticmethod
    def log_file_update(
        db: Session,
        username: str,
        filename: str,
        data_file_id: int,
        update_fields: list
    ) -> bool:
        """记录文件更新日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=username,
            action="文件更新",
            data_file_id=data_file_id,
            content=f"用户 {username} 更新了文件 {filename}，更新字段: {', '.join(update_fields)}"
        )
    
    @staticmethod
    def log_user_permission_update(
        db: Session,
        admin_username: str,
        target_username: str,
        permission_type: str,
        permission_ids: list
    ) -> bool:
        """记录用户权限更新日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=admin_username,
            action="用户权限更新",
            content=f"管理员 {admin_username} 更新了用户 {target_username} 的{permission_type}权限，权限ID: {permission_ids}"
        )
    
    @staticmethod
    def log_task_create(
        db: Session,
        username: str,
        task_name: str,
        task_id: int
    ) -> bool:
        """记录任务创建日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=username,
            action="任务创建",
            content=f"用户 {username} 创建了任务 {task_name}，任务ID: {task_id}"
        )
    
    @staticmethod
    def log_task_delete(
        db: Session,
        username: str,
        task_name: str,
        task_id: int
    ) -> bool:
        """记录任务删除日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=username,
            action="任务删除",
            content=f"用户 {username} 删除了任务 {task_name}，任务ID: {task_id}"
        )
    
    @staticmethod
    def log_label_create(
        db: Session,
        username: str,
        label_name: str,
        label_id: int
    ) -> bool:
        """记录标签创建日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=username,
            action="标签创建",
            content=f"用户 {username} 创建了标签 {label_name}，标签ID: {label_id}"
        )
    
    @staticmethod
    def log_device_create(
        db: Session,
        username: str,
        device_name: str,
        device_id: int
    ) -> bool:
        """记录设备创建日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=username,
            action="设备创建",
            content=f"用户 {username} 创建了设备 {device_name}，设备ID: {device_id}"
        )
    
    @staticmethod
    def log_operation_create(
        db: Session,
        username: str,
        page_name: str,
        action: str,
        operation_id: int
    ) -> bool:
        """记录操作创建日志"""
        return OperationLogUtil.create_log(
            db=db,
            username=username,
            action="操作创建",
            content=f"用户 {username} 创建了操作 {page_name} - {action}，操作ID: {operation_id}"
        )
