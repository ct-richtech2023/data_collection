from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from common.database import get_db
from common import models, schemas
from router.user.auth import get_current_user

router = APIRouter()


@router.post("/create_operation", response_model=schemas.OperationOut)
def create_operation(
    operation: schemas.OperationCreate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """创建操作 - 只有管理员可以创建操作"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以创建操作
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以创建操作"
        )
    
    # 检查操作是否已存在（page_name + action 组合唯一）
    existing_operation = db.query(models.Operation).filter(
        models.Operation.page_name == operation.page_name,
        models.Operation.action == operation.action
    ).first()
    if existing_operation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该页面操作组合已存在"
        )
    
    # 创建操作
    db_operation = models.Operation(
        page_name=operation.page_name,
        action=operation.action
    )
    db.add(db_operation)
    db.commit()
    db.refresh(db_operation)
    return db_operation


@router.get("/get_all_operations", response_model=List[schemas.OperationOut])
def get_all_operations(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取所有操作列表 - 只有管理员可以查看所有操作"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看所有操作
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看所有操作"
        )
    
    operations = db.query(models.Operation).all()
    return operations


@router.get("/get_operation_by_id", response_model=schemas.OperationOut)
def get_operation_by_id(
    operation_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """根据ID获取操作信息 - 只有管理员可以查看操作信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看操作信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看操作信息"
        )
    
    operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
    if not operation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="操作不存在"
        )
    return operation


@router.post("/update_operation", response_model=schemas.OperationOut)
def update_operation(
    operation_update: schemas.OperationUpdate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """更新操作信息 - 只有管理员可以更新操作信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以更新操作信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以更新操作信息"
        )
    
    # 从operation_update中获取操作ID
    operation_id = operation_update.id
    
    # 查找操作
    operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
    if not operation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="操作不存在"
        )
    
    # 更新操作信息 - 只更新提供的字段
    update_data = operation_update.model_dump(exclude_unset=True)
    
    # 移除id字段，因为id不应该被更新
    update_data.pop("id", None)
    
    # 处理空字符串，将空字符串转换为None（表示不更新）
    for field, value in update_data.items():
        if value == "":
            update_data[field] = None
    
    # 验证字段值
    if "page_name" in update_data and update_data["page_name"] is not None:
        if len(update_data["page_name"]) < 1 or len(update_data["page_name"]) > 255:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="页面名称长度必须在1-255个字符之间"
            )
    
    if "action" in update_data and update_data["action"] is not None:
        if len(update_data["action"]) < 1 or len(update_data["action"]) > 255:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="操作名称长度必须在1-255个字符之间"
            )
    
    # 检查页面操作组合是否已被其他操作使用
    if "page_name" in update_data or "action" in update_data:
        page_name = update_data.get("page_name", operation.page_name)
        action = update_data.get("action", operation.action)
        
        existing_operation = db.query(models.Operation).filter(
            models.Operation.page_name == page_name,
            models.Operation.action == action,
            models.Operation.id != operation_id
        ).first()
        if existing_operation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该页面操作组合已被其他操作使用"
            )
    
    # 更新字段 - 只更新非None的字段
    for field, value in update_data.items():
        if value is not None:
            setattr(operation, field, value)
    
    db.commit()
    db.refresh(operation)
    return operation


@router.post("/delete_operation")
def delete_operation(
    operation_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """删除操作 - 只有管理员可以删除操作"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以删除操作
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除操作"
        )
    
    # 查找操作
    operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
    if not operation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="操作不存在"
        )
    
    # 检查是否有用户权限关联此操作
    permissions_count = db.query(models.UserOperationPermission).filter(
        models.UserOperationPermission.operation_id == operation_id
    ).count()
    if permissions_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法删除操作，该操作关联了 {permissions_count} 个用户权限"
        )
    
    # 检查是否有操作日志关联此操作
    logs_count = db.query(models.OperationLog).filter(
        models.OperationLog.action == operation.action
    ).count()
    if logs_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法删除操作，该操作关联了 {logs_count} 条操作日志"
        )
    
    db.delete(operation)
    db.commit()
    return {"message": f"操作 {operation.page_name}.{operation.action} 已成功删除"}
