from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, date
from common.database import get_db
from common import models, schemas
from common.operation_log_util import action_list
from router.user.auth import get_current_user
from loguru import logger

router = APIRouter()



@router.post("/get_logs_with_pagination")
def get_operation_logs_with_pagination(
    request_data: schemas.OperationLogQuery,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取操作日志列表，支持分页和多条件查询 - 只有管理员可以查看"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[OpLog][Page] 请求 | user_id={getattr(current_user, 'id', None)} filters={{'log_id': {'set' if bool(getattr(request_data, 'log_id', None)) else 'unset'}, 'username': {'set' if bool(getattr(request_data, 'username', None)) else 'unset'}, 'action': {'set' if bool(getattr(request_data, 'action', None)) else 'unset'}, 'data_file_id': {'set' if bool(getattr(request_data, 'data_file_id', None)) else 'unset'}, 'start_date': {'set' if bool(getattr(request_data, 'start_date', None)) else 'unset'}, 'end_date': {'set' if bool(getattr(request_data, 'end_date', None)) else 'unset'}}}")
    
    # 权限检查：只有管理员可以查看日志信息
    if not current_user.is_admin():
        logger.warning(f"[OpLog][Page] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看日志信息"
        )
    
    try:
        # 构建查询
        query = db.query(models.OperationLog)
        
        # 如果指定了日志ID，则只查询该日志
        if request_data.log_id:
            query = query.filter(models.OperationLog.id == request_data.log_id)
        
        # 如果指定了用户名，则进行模糊查询
        if request_data.username:
            query = query.filter(models.OperationLog.username.ilike(f"%{request_data.username}%"))
        
        # 如果指定了操作类型，则进行模糊查询
        if request_data.action:
            query = query.filter(models.OperationLog.action.ilike(f"%{request_data.action}%"))
        
        # 如果指定了数据文件ID，则只查询该文件相关的日志
        if request_data.data_file_id:
            query = query.filter(models.OperationLog.data_file_id == request_data.data_file_id)
        
        # 日期筛选
        if request_data.start_date:
            # 开始日期：筛选创建日期大于等于此日期的日志（从当天00:00:00开始）
            start_datetime = datetime.combine(request_data.start_date, datetime.min.time())
            query = query.filter(models.OperationLog.create_time >= start_datetime)
        
        if request_data.end_date:
            # 结束日期：筛选创建日期小于等于此日期的日志（到当天23:59:59结束）
            end_datetime = datetime.combine(request_data.end_date, datetime.max.time().replace(microsecond=0))
            query = query.filter(models.OperationLog.create_time <= end_datetime)
        
        # 获取总数（用于分页信息）
        total_count = query.count()
        logger.info(f"[OpLog][Page] 查询完成 | total_count={total_count}")
        
        # 按ID正序排列
        query = query.order_by(models.OperationLog.id.asc())
        
        # 应用分页
        offset = (request_data.page - 1) * request_data.page_size
        logs = query.offset(offset).limit(request_data.page_size).all()
        logger.info(f"[OpLog][Page] 分页 | page={request_data.page} size={request_data.page_size} page_count={len(logs)}")
        
        # 构建响应数据
        result = []
        for log in logs:
            # 获取关联的数据文件信息（如果存在）
            datafile_info = None
            if log.data_file_id:
                datafile = db.query(models.DataFile).filter(models.DataFile.id == log.data_file_id).first()
                if datafile:
                    # 获取关联的任务信息
                    task = db.query(models.Task).filter(models.Task.id == datafile.task_id).first()
                    task_name = task.name if task else "未知任务"
                    
                    # 获取关联的设备信息
                    device = db.query(models.Device).filter(models.Device.id == datafile.device_id).first()
                    device_name = device.name if device else "未知设备"
                    
                    datafile_info = {
                        "data_file_id": datafile.id,
                        "file_name": datafile.file_name,
                        "task_id": datafile.task_id,
                        "task_name": task_name,
                        "device_id": datafile.device_id,
                        "device_name": device_name,
                        "create_time": datafile.create_time
                    }
            
            log_data = {
                "id": log.id,
                "username": log.username,
                "action": log.action,
                "data_file_id": log.data_file_id,
                "content": log.content,
                "create_time": log.create_time,
                "update_time": log.update_time,
                "datafile_info": datafile_info
            }
            
            result.append(log_data)
        
        # 计算分页信息
        total_pages = (total_count + request_data.page_size - 1) // request_data.page_size
        
        resp = {
            "logs": result,
            "pagination": {
                "current_page": request_data.page,
                "page_size": request_data.page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": request_data.page < total_pages,
                "has_prev": request_data.page > 1
            }
        }
        logger.info(f"[OpLog][Page] 成功 | current_page={request_data.page} total_pages={total_pages}")
        return resp
        
    except Exception as e:
        logger.exception(f"[OpLog][Page] 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取操作日志信息时发生错误: {str(e)}"
        )


@router.get("/get_action")
def get_action_dictionary(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取操作类型数据字典 - 只有管理员可以查看"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[OpLog][ActionDict] 请求 | user_id={current_user.id}")
    
    # 权限检查：只有管理员可以查看操作类型字典
    if not current_user.is_admin():
        logger.warning(f"[OpLog][ActionDict] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看操作类型字典"
        )
    
    try:
        resp = {
            "actions": action_list,
            "total_actions": len(action_list)
        }
        logger.info(f"[OpLog][ActionDict] 成功 | total_actions={len(action_list)}")
        return resp
    except Exception as e:
        logger.exception(f"[OpLog][ActionDict] 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"获取操作类型字典时发生错误: {str(e)}"
        )
