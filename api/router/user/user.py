from loguru import logger
from fastapi import FastAPI, Depends, HTTPException, status, Header, APIRouter
from sqlalchemy.orm import Session
from typing import List, Optional
from common.database import Base, engine, get_db
from common import models, schemas
from .auth import hash_password, authenticate_user, create_access_token, get_current_user

router = APIRouter()

@router.post("/auth/register")
def register(user_in: schemas.User, token: str = Header(..., description="JWT token"), db: Session = Depends(get_db)):
    """用户注册 - 只有管理员可以注册新用户"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以注册新用户
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以注册新用户"
        )
    
    # 检查用户名是否已存在
    username_exists = db.query(models.User).filter(models.User.username == user_in.username).first()
    if username_exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="用户名已存在，请使用其他用户名"
        )
    
    try:
        user = models.User(
            email=user_in.email,
            username=user_in.username,
            password=hash_password(user_in.password),
            permission_level=user_in.permission_level,
            extra=user_in.extra,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except Exception as e:
        # 发生错误时回滚事务
        db.rollback()
        # 如果是数据库完整性错误，提供更友好的错误信息
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            if "username" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="用户名已存在，请使用其他用户名"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="数据冲突，请检查输入信息"
                )
        else:
            # 其他数据库错误
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="注册用户时发生错误，请稍后重试"
            )


@router.post("/auth/login")
def login(login_data: schemas.UserLogin, db: Session = Depends(get_db)):
    """用户登录 - 使用用户名和密码"""
    user = authenticate_user(db, username=login_data.username, password=login_data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    token = create_access_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/get_all_users")
def get_all_users(token: str = Header(..., description="JWT token"), db: Session = Depends(get_db)):
    """获取所有用户数据 - 需要管理员权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 检查权限：只有管理员可以查看所有用户
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看所有用户数据"
        )
    
    users = db.query(models.User).all()
    return users


@router.post("/get_user_by_id")
def get_user_by_id(user_id: int, token: str = Header(..., description="JWT token"), db: Session = Depends(get_db)):
    """根据ID获取用户数据 - 只有管理员可以查看用户信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看用户信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看用户信息"
        )
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    return user


@router.post("/update_user")
def update_user(user_update: schemas.UserUpdate, token: str = Header(..., description="JWT token"), db: Session = Depends(get_db)):
    """修改用户信息 - 只有管理员可以修改用户信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以修改用户信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以修改用户信息"
        )
    
    # 如果没有提供更新数据，返回错误
    if user_update is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请提供要更新的用户信息"
        )
    
    # 从user_update中获取用户ID
    user_id = user_update.id
    
    # 查找要修改的用户
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 更新用户信息 - 只更新提供的字段
    update_data = user_update.model_dump(exclude_unset=True)
    
    # 移除id字段，因为id不应该被更新
    update_data.pop("id", None)
    
    # 处理空字符串，将空字符串转换为None（表示不更新）
    for field, value in update_data.items():
        if value == "":
            update_data[field] = None
    
    # 验证字段值
    if "username" in update_data and update_data["username"] is not None:
        if len(update_data["username"]) < 1 or len(update_data["username"]) > 32:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名长度必须在1-32个字符之间"
            )
        if not update_data["username"].replace("_", "").replace(".", "").isalnum():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名只能包含字母、数字、下划线和点"
            )
        # 检查用户名唯一性（排除当前用户）
        existing_user = db.query(models.User).filter(
            models.User.username == update_data["username"],
            models.User.id != user_id
        ).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在"
            )
    
    if "email" in update_data and update_data["email"] is not None:
        if len(update_data["email"]) < 1 or len(update_data["email"]) > 255:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱长度必须在1-255个字符之间"
            )
    
    if "password" in update_data and update_data["password"] is not None:
        if len(update_data["password"]) < 1 or len(update_data["password"]) > 128:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="密码长度必须在1-128个字符之间"
            )
        # 加密密码
        update_data["password"] = hash_password(update_data["password"])
    
    if "permission_level" in update_data and update_data["permission_level"] is not None:
        if update_data["permission_level"] not in [models.PermissionLevel.ADMIN, models.PermissionLevel.USER]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="权限级别必须是 admin 或 user"
            )
    
    # 更新字段 - 只更新非None的字段
    try:
        for field, value in update_data.items():
            if value is not None:
                setattr(user, field, value)
        
        db.commit()
        db.refresh(user)
        return user
    except Exception as e:
        logger.error(f"更新用户信息时发生错误: {e}")
        # 发生错误时回滚事务
        db.rollback()
        # 如果是数据库完整性错误，提供更友好的错误信息
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            if "username" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="用户名已存在，请使用其他用户名"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="数据冲突，请检查输入信息"
                )
        else:
            # 其他数据库错误
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="更新用户信息时发生错误，请稍后重试"
            )


@router.post("/delete_user")
def delete_user(user_id: int,token: str = Header(..., description="JWT token"),db: Session = Depends(get_db)):
    """删除用户 - 只有管理员可以删除用户"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以删除用户
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除用户"
        )
    
    # 查找要删除的用户
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 删除用户
    db.delete(user)
    db.commit()
    
    return {"message": f"用户 {user.username} 已成功删除"}


# ---------- 用户设备权限管理 ----------
@router.post("/add_device_permission", response_model=schemas.UserDevicePermissionOut)
def add_device_permission(
    permission: schemas.UserDevicePermissionCreate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """为用户添加设备权限 - 只有管理员可以添加设备权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以添加设备权限
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以添加设备权限"
        )
    
    # 检查用户是否存在
    user = db.query(models.User).filter(models.User.id == permission.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 检查设备是否存在
    device = db.query(models.Device).filter(models.Device.id == permission.device_id).first()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在"
        )
    
    # 检查权限是否已存在
    existing_permission = db.query(models.UserDevicePermission).filter(
        models.UserDevicePermission.user_id == permission.user_id,
        models.UserDevicePermission.device_id == permission.device_id
    ).first()
    if existing_permission:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该用户已拥有此设备权限"
        )
    
    # 创建设备权限
    db_permission = models.UserDevicePermission(
        user_id=permission.user_id,
        device_id=permission.device_id
    )
    db.add(db_permission)
    db.commit()
    db.refresh(db_permission)
    return db_permission


@router.get("/get_user_device_permissions", response_model=List[schemas.UserDevicePermissionOut])
def get_user_device_permissions(
    user_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取用户的设备权限列表 - 只有管理员可以查看用户设备权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看用户设备权限
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看用户设备权限"
        )
    
    # 检查用户是否存在
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 获取用户的设备权限
    permissions = db.query(models.UserDevicePermission).filter(
        models.UserDevicePermission.user_id == user_id
    ).all()
    return permissions


@router.get("/get_device_user_permissions", response_model=List[schemas.UserDevicePermissionOut])
def get_device_user_permissions(
    device_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取设备的用户权限列表 - 只有管理员可以查看设备用户权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看设备用户权限
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看设备用户权限"
        )
    
    # 检查设备是否存在
    device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在"
        )
    
    # 获取设备的用户权限
    permissions = db.query(models.UserDevicePermission).filter(
        models.UserDevicePermission.device_id == device_id
    ).all()
    return permissions


@router.post("/remove_device_permission")
def remove_device_permission(
    user_id: int,
    device_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """移除用户的设备权限 - 只有管理员可以移除设备权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以移除设备权限
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以移除设备权限"
        )
    
    # 查找权限记录
    permission = db.query(models.UserDevicePermission).filter(
        models.UserDevicePermission.user_id == user_id,
        models.UserDevicePermission.device_id == device_id
    ).first()
    
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="权限记录不存在"
        )
    
    # 获取用户和设备信息用于返回消息
    user = db.query(models.User).filter(models.User.id == user_id).first()
    device = db.query(models.Device).filter(models.Device.id == device_id).first()
    
    # 删除权限记录
    db.delete(permission)
    db.commit()
    
    return {"message": f"已成功移除用户 {user.username if user else user_id} 对设备 {device.name if device else device_id} 的权限"}


# ---------- 用户操作权限管理 ----------
@router.post("/add_operation_permission", response_model=schemas.UserOperationPermissionOut)
def add_operation_permission(
    permission: schemas.UserOperationPermissionCreate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """为用户添加操作权限 - 只有管理员可以添加操作权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以添加操作权限
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以添加操作权限"
        )
    
    # 检查用户是否存在
    user = db.query(models.User).filter(models.User.id == permission.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 检查操作是否存在
    operation = db.query(models.Operation).filter(models.Operation.id == permission.operation_id).first()
    if not operation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="操作不存在"
        )
    
    # 检查权限是否已存在
    existing_permission = db.query(models.UserOperationPermission).filter(
        models.UserOperationPermission.user_id == permission.user_id,
        models.UserOperationPermission.operation_id == permission.operation_id
    ).first()
    if existing_permission:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该用户已拥有此操作权限"
        )
    
    # 创建操作权限
    db_permission = models.UserOperationPermission(
        user_id=permission.user_id,
        operation_id=permission.operation_id
    )
    db.add(db_permission)
    db.commit()
    db.refresh(db_permission)
    return db_permission


@router.get("/get_user_operation_permissions", response_model=List[schemas.UserOperationPermissionOut])
def get_user_operation_permissions(
    user_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取用户的操作权限列表 - 只有管理员可以查看用户操作权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看用户操作权限
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看用户操作权限"
        )
    
    # 检查用户是否存在
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 获取用户的操作权限
    permissions = db.query(models.UserOperationPermission).filter(
        models.UserOperationPermission.user_id == user_id
    ).all()
    return permissions


@router.get("/get_operation_user_permissions", response_model=List[schemas.UserOperationPermissionOut])
def get_operation_user_permissions(
    operation_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取操作用户权限列表 - 只有管理员可以查看操作用户权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看操作用户权限
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看操作用户权限"
        )
    
    # 检查操作是否存在
    operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
    if not operation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="操作不存在"
        )
    
    # 获取操作用户权限
    permissions = db.query(models.UserOperationPermission).filter(
        models.UserOperationPermission.operation_id == operation_id
    ).all()
    return permissions


@router.post("/remove_operation_permission")
def remove_operation_permission(
    user_id: int,
    operation_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """移除用户的操作权限 - 只有管理员可以移除操作权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以移除操作权限
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以移除操作权限"
        )
    
    # 查找权限记录
    permission = db.query(models.UserOperationPermission).filter(
        models.UserOperationPermission.user_id == user_id,
        models.UserOperationPermission.operation_id == operation_id
    ).first()
    
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="权限记录不存在"
        )
    
    # 获取用户和操作信息用于返回消息
    user = db.query(models.User).filter(models.User.id == user_id).first()
    operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
    
    # 删除权限记录
    db.delete(permission)
    db.commit()
    
    return {"message": f"已成功移除用户 {user.username if user else user_id} 对操作 {operation.page_name}.{operation.action if operation else operation_id} 的权限"}
