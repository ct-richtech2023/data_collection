from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from common.database import get_db
from common import models, schemas
from router.user.auth import get_current_user
from loguru import logger

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
    logger.info(f"[Operation][Create] 请求 | user_id={getattr(current_user, 'id', None)} page={operation.page_name} action={operation.action}")
    
    # 权限检查：只有管理员可以创建操作
    if not current_user.is_admin():
        logger.warning(f"[Operation][Create] 拒绝 | 非管理员 user_id={current_user.id}")
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
        logger.warning(f"[Operation][Create] 组合已存在 | page={operation.page_name} action={operation.action}")
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
    logger.info(f"[Operation][Create] 成功 | operation_id={db_operation.id}")
    return db_operation


@router.get("/get_all_operations", response_model=List[schemas.OperationOut])
def get_all_operations(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取所有操作列表 - 只有管理员可以查看所有操作"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[Operation][ListAll] 请求 | user_id={current_user.id}")
    
    # 权限检查：只有管理员可以查看所有操作
    if not current_user.is_admin():
        logger.warning(f"[Operation][ListAll] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看所有操作"
        )
    
    operations = db.query(models.Operation).order_by(models.Operation.id.asc()).all()
    logger.info(f"[Operation][ListAll] 成功 | count={len(operations)}")
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
    logger.info(f"[Operation][GetById] 请求 | user_id={current_user.id} operation_id={operation_id}")
    
    # 权限检查：只有管理员可以查看操作信息
    if not current_user.is_admin():
        logger.warning(f"[Operation][GetById] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看操作信息"
        )
    
    operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
    if not operation:
        logger.warning(f"[Operation][GetById] 未找到 | operation_id={operation_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="操作不存在"
        )
    logger.info(f"[Operation][GetById] 成功 | operation_id={operation.id}")
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
    logger.info(f"[Operation][Update] 请求 | user_id={current_user.id} payload={operation_update.model_dump(exclude_none=True)}")
    
    # 权限检查：只有管理员可以更新操作信息
    if not current_user.is_admin():
        logger.warning(f"[Operation][Update] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以更新操作信息"
        )
    
    # 从operation_update中获取操作ID
    operation_id = operation_update.id
    
    # 查找操作
    operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
    if not operation:
        logger.warning(f"[Operation][Update] 未找到 | operation_id={operation_id}")
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
            logger.warning(f"[Operation][Update] 组合冲突 | operation_id={operation_id} page={page_name} action={action}")
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
    logger.info(f"[Operation][Update] 成功 | operation_id={operation.id}")
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
    logger.info(f"[Operation][Delete] 请求 | user_id={current_user.id} operation_id={operation_id}")
    
    # 权限检查：只有管理员可以删除操作
    if not current_user.is_admin():
        logger.warning(f"[Operation][Delete] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除操作"
        )
    
    # 查找操作
    operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
    if not operation:
        logger.warning(f"[Operation][Delete] 未找到 | operation_id={operation_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="操作不存在"
        )
    
    # 检查是否有用户权限关联此操作
    permissions_count = db.query(models.UserOperationPermission).filter(
        models.UserOperationPermission.operation_id == operation_id
    ).count()
    if permissions_count > 0:
        logger.warning(f"[Operation][Delete] 关联用户权限阻止删除 | operation_id={operation_id} count={permissions_count}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法删除操作，该操作关联了 {permissions_count} 个用户权限"
        )
    
    # 检查是否有操作日志关联此操作
    logs_count = db.query(models.OperationLog).filter(
        models.OperationLog.action == operation.action
    ).count()
    if logs_count > 0:
        logger.warning(f"[Operation][Delete] 关联操作日志阻止删除 | operation_id={operation_id} count={logs_count}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法删除操作，该操作关联了 {logs_count} 条操作日志"
        )
    
    db.delete(operation)
    db.commit()
    logger.info(f"[Operation][Delete] 成功 | operation_id={operation_id}")
    return {"message": f"操作 {operation.page_name}.{operation.action} 已成功删除"}


@router.post("/get_operations_with_pagination")
def get_operations_with_pagination(
    request_data: schemas.OperationQuery,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取操作列表，支持分页和按ID查询 - 任何已认证用户都可以查看"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[Operation][Page] 请求 | user_id={current_user.id} filters={{'operation_id': { 'set' if bool(getattr(request_data, 'operation_id', None)) else 'unset' }, 'page_name': { 'set' if bool(getattr(request_data, 'page_name', None)) else 'unset' }, 'action': { 'set' if bool(getattr(request_data, 'action', None)) else 'unset' }}}")
    
    # 权限检查：任何已认证的用户都可以查看操作信息
    # 移除管理员限制，允许所有数据库中的用户访问
    
    try:
        # 构建查询
        query = db.query(models.Operation)
        
        # 如果指定了操作ID，则只查询该操作
        if request_data.operation_id:
            query = query.filter(models.Operation.id == request_data.operation_id)
        
        # 如果指定了页面名称，则进行模糊查询
        if request_data.page_name:
            query = query.filter(models.Operation.page_name == request_data.page_name)
        
        # 如果指定了操作动作，则进行模糊查询
        if request_data.action:
            query = query.filter(models.Operation.action == request_data.action)
        
        # 获取总数（用于分页信息）
        total_count = query.count()
        logger.info(f"[Operation][Page] 查询完成 | total_count={total_count}")
        
        # 按ID正序排列
        query = query.order_by(models.Operation.id.asc())
        
        # 应用分页
        offset = (request_data.page - 1) * request_data.page_size
        operations = query.offset(offset).limit(request_data.page_size).all()
        logger.info(f"[Operation][Page] 分页 | page={request_data.page} size={request_data.page_size} page_count={len(operations)}")
        
        # 构建响应数据
        result = []
        for operation in operations:
            # 获取操作关联的用户权限数量
            user_permissions_count = db.query(models.UserOperationPermission).filter(models.UserOperationPermission.operation_id == operation.id).count()
            
            # 获取操作关联的操作日志数量
            operation_logs_count = db.query(models.OperationLog).filter(models.OperationLog.action == operation.action).count()
            
            operation_data = {
                "id": operation.id,
                "page_name": operation.page_name,
                "action": operation.action,
                "create_time": operation.create_time,
                "update_time": operation.update_time,
                "user_permissions_count": user_permissions_count,
                "operation_logs_count": operation_logs_count
            }
            
            result.append(operation_data)
        
        # 计算分页信息
        total_pages = (total_count + request_data.page_size - 1) // request_data.page_size
        
        return {
            "operations": result,
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
        logger.exception(f"[Operation][Page] 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取操作信息时发生错误: {str(e)}"
        )
