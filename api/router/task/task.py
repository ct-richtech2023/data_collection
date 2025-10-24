from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from common.database import get_db
from common import models, schemas
from router.user.auth import get_current_user

router = APIRouter()


@router.post("/create_task", response_model=schemas.TaskOut)
def create_task(
    task: schemas.TaskCreate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """创建任务 - 只有管理员可以创建任务"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以创建任务
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以创建任务"
        )
    
    # 检查任务名称是否已存在
    existing_task = db.query(models.Task).filter(models.Task.name == task.name).first()
    if existing_task:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任务名称已存在"
        )
    
    # 创建任务
    db_task = models.Task(
        name=task.name
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    
    # 记录任务创建日志
    from common.operation_log_util import OperationLogUtil
    OperationLogUtil.log_task_create(
        db, current_user.username, task.name, db_task.id
    )
    
    return db_task


@router.get("/get_all_tasks", response_model=List[schemas.TaskOut])
def get_all_tasks(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取所有任务列表 - 只有管理员可以查看所有任务"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看所有任务
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看所有任务"
        )
    
    tasks = db.query(models.Task).order_by(models.Task.id.asc()).all()
    return tasks


@router.get("/get_task_by_id", response_model=schemas.TaskOut)
def get_task_by_id(
    task_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """根据ID获取任务信息 - 只有管理员可以查看任务信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看任务信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看任务信息"
        )
    
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在"
        )
    return task


@router.post("/update_task", response_model=schemas.TaskOut)
def update_task(
    task_update: schemas.TaskUpdate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """更新任务信息 - 只有管理员可以更新任务信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以更新任务信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以更新任务信息"
        )
    
    # 从task_update中获取任务ID
    task_id = task_update.id
    
    # 查找任务
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在"
        )
    
    # 更新任务信息 - 只更新提供的字段
    update_data = task_update.model_dump(exclude_unset=True)
    
    # 移除id字段，因为id不应该被更新
    update_data.pop("id", None)
    
    # 处理空字符串，将空字符串转换为None（表示不更新）
    for field, value in update_data.items():
        if value == "":
            update_data[field] = None
    
    # 验证字段值
    if "name" in update_data and update_data["name"] is not None:
        if len(update_data["name"]) < 1 or len(update_data["name"]) > 255:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="任务名称长度必须在1-255个字符之间"
            )
        
        # 检查任务名称是否已被其他任务使用
        existing_task = db.query(models.Task).filter(
            models.Task.name == update_data["name"],
            models.Task.id != task_id
        ).first()
        if existing_task:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="任务名称已被其他任务使用"
            )
    
    # 更新字段 - 只更新非None的字段
    updated_fields = []
    for field, value in update_data.items():
        if value is not None:
            setattr(task, field, value)
            updated_fields.append(field)
    
    db.commit()
    db.refresh(task)
    
    # 记录任务更新日志
    if updated_fields:
        from common.operation_log_util import OperationLogUtil
        OperationLogUtil.create_log(
            db, current_user.username, "任务更新", 
            f"用户 {current_user.username} 更新了任务 {task.name}，更新字段: {', '.join(updated_fields)}"
        )
    
    return task


@router.post("/delete_task")
def delete_task(
    task_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """删除任务 - 只有管理员可以删除任务"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以删除任务
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除任务"
        )
    
    # 查找任务
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在"
        )
    
    # 检查是否有数据文件关联此任务
    data_files_count = db.query(models.DataFile).filter(models.DataFile.task_id == task_id).count()
    if data_files_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法删除任务，该任务关联了 {data_files_count} 个数据文件"
        )
    
    # 记录任务删除日志
    from common.operation_log_util import OperationLogUtil
    OperationLogUtil.log_task_delete(
        db, current_user.username, task.name, task_id
    )
    
    db.delete(task)
    db.commit()
    return {"message": f"任务 {task.name} 已成功删除"}


@router.post("/get_tasks_with_pagination")
def get_tasks_with_pagination(
    request_data: schemas.TaskQuery,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取任务列表，支持分页和按ID查询 - 只有管理员可以查看"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看任务信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看任务信息"
        )
    
    try:
        # 构建查询
        query = db.query(models.Task)
        
        # 如果指定了任务ID，则只查询该任务
        if request_data.task_id:
            query = query.filter(models.Task.id == request_data.task_id)
        
        # 如果指定了任务名称，则进行模糊查询
        if request_data.name:
            query = query.filter(models.Task.name.ilike(f"%{request_data.name}%"))
        
        # 获取总数（用于分页信息）
        total_count = query.count()
        
        # 按ID正序排列
        query = query.order_by(models.Task.id.asc())
        
        # 应用分页
        offset = (request_data.page - 1) * request_data.page_size
        tasks = query.offset(offset).limit(request_data.page_size).all()
        
        # 构建响应数据
        result = []
        for task in tasks:
            # 获取任务关联的数据文件数量
            data_files_count = db.query(models.DataFile).filter(models.DataFile.task_id == task.id).count()
            
            task_data = {
                "id": task.id,
                "name": task.name,
                "create_time": task.create_time,
                "update_time": task.update_time,
                "data_files_count": data_files_count
            }
            
            result.append(task_data)
        
        # 计算分页信息
        total_pages = (total_count + request_data.page_size - 1) // request_data.page_size
        
        return {
            "tasks": result,
            "pagination": {
                "current_page": request_data.page,
                "page_size": request_data.page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": request_data.page < total_pages,
                "has_prev": request_data.page > 1
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取任务信息时发生错误: {str(e)}"
        )
