"""
操作日志工具类
提供统一的操作日志记录功能
"""
from sqlalchemy.orm import Session
from . import models
from typing import Optional


action_list = ["User Login", "User Registration", "User Permission Update", "File Upload", "File Download", "Batch File Download", "File Delete", "File Update", "Task Create", "Task Delete", "Label Create", "Device Create", "Operation Create", "ZIP File Upload", "ZIP File Download", "ZIP File Delete", "ZIP File Update"]


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
            action="User Login",
            content=f"User {username} successfully logged in"
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
            action="User Registration",
            content=f"Admin {admin_username} registered new user {new_username}, permission level: {permission_level}"
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
            action="File Upload",
            data_file_id=data_file_id,
            content=f"User {username} uploaded file {filename}, task ID: {task_id}, device ID: {device_id}"
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
            action="Batch File Download",
            content=f"User {username} downloaded {file_count} files, file IDs: {file_ids}"
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
            action="File Delete",
            data_file_id=data_file_id,
            content=f"User {username} deleted file {filename}"
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
            action="File Update",
            data_file_id=data_file_id,
            content=f"User {username} updated file {filename}, updated fields: {', '.join(update_fields)}"
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
            action="User Permission Update",
            content=f"Admin {admin_username} updated {target_username}'s {permission_type} permissions, permission IDs: {permission_ids}"
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
            action="Task Create",
            content=f"User {username} created task {task_name}, task ID: {task_id}"
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
            action="Task Delete",
            content=f"User {username} deleted task {task_name}, task ID: {task_id}"
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
            action="Label Create",
            content=f"User {username} created label {label_name}, label ID: {label_id}"
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
            action="Device Create",
            content=f"User {username} created device {device_name}, device ID: {device_id}"
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
            action="Operation Create",
            content=f"User {username} created operation {page_name} - {action}, operation ID: {operation_id}"
        )
