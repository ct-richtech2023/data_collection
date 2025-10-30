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
    logger.info(f"[User][Register] 请求 | by_user_id={getattr(current_user, 'id', None)} username={user_in.username} email={user_in.email}")
    
    # 权限检查：只有管理员可以注册新用户
    if not current_user.is_admin():
        logger.warning(f"[User][Register] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以注册新用户"
        )
    
    # 检查用户名是否已存在
    username_exists = db.query(models.User).filter(models.User.username == user_in.username).first()
    if username_exists:
        logger.warning(f"[User][Register] 重名 | username={user_in.username}")
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
        
        # 创建用户注册操作日志
        from common.operation_log_util import OperationLogUtil
        OperationLogUtil.log_user_register(
            db, current_user.username, user_in.username, user_in.permission_level
        )
        
        logger.info(f"[User][Register] 成功 | user_id={user.id} username={user.username}")
        return user
    except Exception as e:
        # 发生错误时回滚事务
        db.rollback()
        logger.exception(f"[User][Register] 失败: {e}")
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
    logger.info(f"[User][Login] 请求 | username={login_data.username}")
    user = authenticate_user(db, username=login_data.username, password=login_data.password)
    if not user:
        logger.warning(f"[User][Login] 失败 | 用户名或密码错误 username={login_data.username}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    
    # 创建登录操作日志
    from common.operation_log_util import OperationLogUtil
    OperationLogUtil.log_user_login(db, user.username)
    
    token = create_access_token({"sub": user.username})
    logger.info(f"[User][Login] 成功 | user_id={user.id} username={user.username}")
    return {"access_token": token, "token_type": "bearer"}


@router.get("/get_current_user_info")
def get_current_user_info(token: str = Header(..., description="JWT token"), db: Session = Depends(get_db)):
    """获取当前用户信息，包含设备权限和操作权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[User][Me] 请求 | user_id={current_user.id} username={current_user.username}")
    
    # 获取用户设备权限
    device_permissions = db.query(
        models.UserDevicePermission,
        models.Device
    ).join(
        models.Device, models.UserDevicePermission.device_id == models.Device.id
    ).filter(
        models.UserDevicePermission.user_id == current_user.id
    ).all()
    
    # 构建设备权限数据
    device_permissions_data = []
    for permission, device in device_permissions:
        device_permissions_data.append({
            "device_id": device.id,
            "device_name": device.name,
            "device_sn": device.sn,
            "device_description": device.description,
            "permission_id": permission.id,
            "permission_create_time": permission.create_time
        })
    
    # 获取用户操作权限
    operation_permissions = db.query(
        models.UserOperationPermission,
        models.Operation
    ).join(
        models.Operation, models.UserOperationPermission.operation_id == models.Operation.id
    ).filter(
        models.UserOperationPermission.user_id == current_user.id
    ).all()
    
    # 构建操作权限数据
    operation_permissions_data = []
    for permission, operation in operation_permissions:
        operation_permissions_data.append({
            "operation_id": operation.id,
            "page_name": operation.page_name,
            "action": operation.action,
            "permission_id": permission.id,
            "permission_create_time": permission.create_time
        })
    
    # 构建完整的用户信息响应
    user_info = {
        "user_id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "permission_level": "admin" if current_user.is_admin() else "user",
        "create_time": current_user.create_time,
        "update_time": current_user.update_time,
        "device_permissions": device_permissions_data,
        "operation_permissions": operation_permissions_data,
        "device_permission_count": len(device_permissions_data),
        "operation_permission_count": len(operation_permissions_data)
    }
    
    logger.info(f"[User][Me] 成功 | device_perms={len(device_permissions_data)} op_perms={len(operation_permissions_data)}")
    return user_info


@router.get("/get_all_users")
def get_all_users(token: str = Header(..., description="JWT token"), db: Session = Depends(get_db)):
    """获取所有用户数据 - 需要管理员权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[User][ListAll] 请求 | user_id={current_user.id}")
    
    # 检查权限：只有管理员可以查看所有用户
    if not current_user.is_admin():
        logger.warning(f"[User][ListAll] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看所有用户数据"
        )
    
    users = db.query(models.User).all()
    logger.info(f"[User][ListAll] 成功 | count={len(users)}")
    return users


@router.post("/get_user_by_id")
def get_user_by_id(user_id: int, token: str = Header(..., description="JWT token"), db: Session = Depends(get_db)):
    """根据ID获取用户数据 - 只有管理员可以查看用户信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[User][GetById] 请求 | by_user_id={current_user.id} user_id={user_id}")
    
    # 权限检查：只有管理员可以查看用户信息
    if not current_user.is_admin():
        logger.warning(f"[User][GetById] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看用户信息"
        )
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        logger.warning(f"[User][GetById] 未找到 | user_id={user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    logger.info(f"[User][GetById] 成功 | user_id={user.id} username={user.username}")
    return user


@router.post("/update_user")
def update_user(user_update: schemas.UserUpdate, token: str = Header(..., description="JWT token"), db: Session = Depends(get_db)):
    """修改用户信息 - 只有管理员可以修改用户信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[User][Update] 请求 | by_user_id={current_user.id} payload={user_update.model_dump(exclude_none=True)}")
    
    # 权限检查：只有管理员可以修改用户信息
    if not current_user.is_admin():
        logger.warning(f"[User][Update] 拒绝 | 非管理员 user_id={current_user.id}")
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
        logger.warning(f"[User][Update] 未找到 | user_id={user_id}")
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
            logger.warning(f"[User][Update] 用户名冲突 | user_id={user_id} username={update_data['username']}")
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
        logger.info(f"[User][Update] 成功 | user_id={user.id}")
        return user
    except Exception as e:
        logger.exception(f"[User][Update] 失败: {e}")
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
    logger.info(f"[User][Delete] 请求 | by_user_id={current_user.id} user_id={user_id}")
    
    # 权限检查：只有管理员可以删除用户
    if not current_user.is_admin():
        logger.warning(f"[User][Delete] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除用户"
        )
    
    # 查找要删除的用户
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        logger.warning(f"[User][Delete] 未找到 | user_id={user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 删除用户
    db.delete(user)
    db.commit()
    logger.info(f"[User][Delete] 成功 | user_id={user_id}")
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
    logger.info(f"[UserPerm][Device][Add] 请求 | by_user_id={current_user.id} user_id={permission.user_id} device_id={permission.device_id}")
    
    # 权限检查：只有管理员可以添加设备权限
    if not current_user.is_admin():
        logger.warning(f"[UserPerm][Device][Add] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以添加设备权限"
        )
    
    # 检查用户是否存在
    user = db.query(models.User).filter(models.User.id == permission.user_id).first()
    if not user:
        logger.warning(f"[UserPerm][Device][Add] 用户不存在 | user_id={permission.user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 检查设备是否存在
    device = db.query(models.Device).filter(models.Device.id == permission.device_id).first()
    if not device:
        logger.warning(f"[UserPerm][Device][Add] 设备不存在 | device_id={permission.device_id}")
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
        logger.warning(f"[UserPerm][Device][Add] 已存在 | user_id={permission.user_id} device_id={permission.device_id}")
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
    logger.info(f"[UserPerm][Device][Add] 成功 | id={db_permission.id}")
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
    logger.info(f"[UserPerm][Device][ListByUser] 请求 | by_user_id={current_user.id} user_id={user_id}")
    
    # 权限检查：只有管理员可以查看用户设备权限
    if not current_user.is_admin():
        logger.warning(f"[UserPerm][Device][ListByUser] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看用户设备权限"
        )
    
    # 检查用户是否存在
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        logger.warning(f"[UserPerm][Device][ListByUser] 用户不存在 | user_id={user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 获取用户的设备权限
    permissions = db.query(models.UserDevicePermission).filter(
        models.UserDevicePermission.user_id == user_id
    ).all()
    logger.info(f"[UserPerm][Device][ListByUser] 成功 | count={len(permissions)}")
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
    logger.info(f"[UserPerm][Device][ListByDevice] 请求 | by_user_id={current_user.id} device_id={device_id}")
    
    # 权限检查：只有管理员可以查看设备用户权限
    if not current_user.is_admin():
        logger.warning(f"[UserPerm][Device][ListByDevice] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看设备用户权限"
        )
    
    # 检查设备是否存在
    device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not device:
        logger.warning(f"[UserPerm][Device][ListByDevice] 设备不存在 | device_id={device_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在"
        )
    
    # 获取设备的用户权限
    permissions = db.query(models.UserDevicePermission).filter(
        models.UserDevicePermission.device_id == device_id
    ).all()
    logger.info(f"[UserPerm][Device][ListByDevice] 成功 | count={len(permissions)}")
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
    logger.info(f"[UserPerm][Device][Remove] 请求 | by_user_id={current_user.id} user_id={user_id} device_id={device_id}")
    
    # 权限检查：只有管理员可以移除设备权限
    if not current_user.is_admin():
        logger.warning(f"[UserPerm][Device][Remove] 拒绝 | 非管理员 user_id={current_user.id}")
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
        logger.warning(f"[UserPerm][Device][Remove] 权限记录不存在 | user_id={user_id} device_id={device_id}")
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
    logger.info(f"[UserPerm][Device][Remove] 成功 | user_id={user_id} device_id={device_id}")
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
    logger.info(f"[UserPerm][Op][Add] 请求 | by_user_id={current_user.id} user_id={permission.user_id} operation_id={permission.operation_id}")
    
    # 权限检查：只有管理员可以添加操作权限
    if not current_user.is_admin():
        logger.warning(f"[UserPerm][Op][Add] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以添加操作权限"
        )
    
    # 检查用户是否存在
    user = db.query(models.User).filter(models.User.id == permission.user_id).first()
    if not user:
        logger.warning(f"[UserPerm][Op][Add] 用户不存在 | user_id={permission.user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 检查操作是否存在
    operation = db.query(models.Operation).filter(models.Operation.id == permission.operation_id).first()
    if not operation:
        logger.warning(f"[UserPerm][Op][Add] 操作不存在 | operation_id={permission.operation_id}")
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
        logger.warning(f"[UserPerm][Op][Add] 已存在 | user_id={permission.user_id} operation_id={permission.operation_id}")
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
    logger.info(f"[UserPerm][Op][Add] 成功 | id={db_permission.id}")
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
    logger.info(f"[UserPerm][Op][ListByUser] 请求 | by_user_id={current_user.id} user_id={user_id}")
    
    # 权限检查：只有管理员可以查看用户操作权限
    if not current_user.is_admin():
        logger.warning(f"[UserPerm][Op][ListByUser] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看用户操作权限"
        )
    
    # 检查用户是否存在
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        logger.warning(f"[UserPerm][Op][ListByUser] 用户不存在 | user_id={user_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 获取用户的操作权限
    permissions = db.query(models.UserOperationPermission).filter(
        models.UserOperationPermission.user_id == user_id
    ).all()
    logger.info(f"[UserPerm][Op][ListByUser] 成功 | count={len(permissions)}")
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
    logger.info(f"[UserPerm][Op][ListByOp] 请求 | by_user_id={current_user.id} operation_id={operation_id}")
    
    # 权限检查：只有管理员可以查看操作用户权限
    if not current_user.is_admin():
        logger.warning(f"[UserPerm][Op][ListByOp] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看操作用户权限"
        )
    
    # 检查操作是否存在
    operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
    if not operation:
        logger.warning(f"[UserPerm][Op][ListByOp] 操作不存在 | operation_id={operation_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="操作不存在"
        )
    
    # 获取操作用户权限
    permissions = db.query(models.UserOperationPermission).filter(
        models.UserOperationPermission.operation_id == operation_id
    ).all()
    logger.info(f"[UserPerm][Op][ListByOp] 成功 | count={len(permissions)}")
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
    logger.info(f"[UserPerm][Op][Remove] 请求 | by_user_id={current_user.id} user_id={user_id} operation_id={operation_id}")
    
    # 权限检查：只有管理员可以移除操作权限
    if not current_user.is_admin():
        logger.warning(f"[UserPerm][Op][Remove] 拒绝 | 非管理员 user_id={current_user.id}")
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
        logger.warning(f"[UserPerm][Op][Remove] 权限记录不存在 | user_id={user_id} operation_id={operation_id}")
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
    logger.info(f"[UserPerm][Op][Remove] 成功 | user_id={user_id} operation_id={operation_id}")
    return {"message": f"已成功移除用户 {user.username if user else user_id} 对操作 {operation.page_name}.{operation.action if operation else operation_id} 的权限"}


@router.post("/add_user_permissions")
def add_user_permissions(
    permissions: schemas.UserPermissionsCreate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """为用户同时添加设备权限和操作权限 - 只有管理员可以添加权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[UserPerm][BatchAdd] 请求 | by_user_id={current_user.id} user_id={permissions.user_id} device_ids={permissions.device_ids} operation_ids={permissions.operation_ids}")
    
    # 权限检查：只有管理员可以添加权限
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以添加用户权限"
        )
    
    # 检查用户是否存在
    user = db.query(models.User).filter(models.User.id == permissions.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    results = {
        "user_id": permissions.user_id,
        "device_permissions": [],
        "operation_permissions": [],
        "errors": []
    }
    
    try:
        # 添加设备权限
        if permissions.device_ids:
            for device_id in permissions.device_ids:
                # 检查设备是否存在
                device = db.query(models.Device).filter(models.Device.id == device_id).first()
                if not device:
                    results["errors"].append(f"设备ID {device_id} 不存在")
                    continue
                
                # 检查权限是否已存在
                existing_permission = db.query(models.UserDevicePermission).filter(
                    models.UserDevicePermission.user_id == permissions.user_id,
                    models.UserDevicePermission.device_id == device_id
                ).first()
                
                if existing_permission:
                    results["errors"].append(f"用户已拥有设备ID {device_id} 的权限")
                    continue
                
                # 创建设备权限
                db_permission = models.UserDevicePermission(
                    user_id=permissions.user_id,
                    device_id=device_id
                )
                db.add(db_permission)
                results["device_permissions"].append({
                    "device_id": device_id,
                    "device_name": device.name
                })
        
        # 添加操作权限
        if permissions.operation_ids:
            for operation_id in permissions.operation_ids:
                # 检查操作是否存在
                operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
                if not operation:
                    results["errors"].append(f"操作ID {operation_id} 不存在")
                    continue
                
                # 检查权限是否已存在
                existing_permission = db.query(models.UserOperationPermission).filter(
                    models.UserOperationPermission.user_id == permissions.user_id,
                    models.UserOperationPermission.operation_id == operation_id
                ).first()
                
                if existing_permission:
                    results["errors"].append(f"用户已拥有操作ID {operation_id} 的权限")
                    continue
                
                # 创建操作权限
                db_permission = models.UserOperationPermission(
                    user_id=permissions.user_id,
                    operation_id=operation_id
                )
                db.add(db_permission)
                results["operation_permissions"].append({
                    "operation_id": operation_id,
                    "operation_name": f"{operation.page_name} - {operation.action}"
                })
        
        # 提交所有更改
        db.commit()
        logger.info(f"[UserPerm][BatchAdd] 成功 | user_id={permissions.user_id} add_devices={len(results['device_permissions'])} add_ops={len(results['operation_permissions'])} errors={len(results['errors'])}")
        
        return {
            "message": "权限添加完成",
            "user_id": permissions.user_id,
            "username": user.username,
            "added_device_permissions": len(results["device_permissions"]),
            "added_operation_permissions": len(results["operation_permissions"]),
            "errors": results["errors"],
            "details": results
        }
        
    except Exception as e:
        db.rollback()
        logger.exception(f"[UserPerm][BatchAdd] 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加权限时发生错误: {str(e)}"
        )


@router.post("/update_user_permissions")
def update_user_permissions(
    permissions: schemas.UserPermissionsUpdate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """修改用户权限 - 只有管理员可以修改权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[UserPerm][BatchUpdate] 请求 | by_user_id={current_user.id} user_id={permissions.user_id} device_ids={permissions.device_ids} operation_ids={permissions.operation_ids}")
    
    # 权限检查：只有管理员可以修改权限
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以修改用户权限"
        )
    
    # 检查用户是否存在
    user = db.query(models.User).filter(models.User.id == permissions.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 检查是否为管理员用户
    if user.permission_level == models.PermissionLevel.ADMIN:
        return {
            "message": "该账号是管理员，无需修改权限",
            "user_id": permissions.user_id,
            "username": user.username,
            "permission_level": user.permission_level,
            "note": "管理员拥有所有权限，无需单独设置设备权限和操作权限"
        }
    
    results = {
        "user_id": permissions.user_id,
        "updated_device_permissions": [],
        "updated_operation_permissions": [],
        "errors": []
    }
    
    try:
        # 修改设备权限
        if permissions.device_ids is not None:
            # 删除用户现有的所有设备权限
            db.query(models.UserDevicePermission).filter(
                models.UserDevicePermission.user_id == permissions.user_id
            ).delete()
            
            # 添加新的设备权限
            for device_id in permissions.device_ids:
                # 检查设备是否存在
                device = db.query(models.Device).filter(models.Device.id == device_id).first()
                if not device:
                    results["errors"].append(f"设备ID {device_id} 不存在")
                    continue
                
                # 创建设备权限
                db_permission = models.UserDevicePermission(
                    user_id=permissions.user_id,
                    device_id=device_id
                )
                db.add(db_permission)
                results["updated_device_permissions"].append({
                    "device_id": device_id,
                    "device_name": device.name
                })
        
        # 修改操作权限
        if permissions.operation_ids is not None:
            # 删除用户现有的所有操作权限
            db.query(models.UserOperationPermission).filter(
                models.UserOperationPermission.user_id == permissions.user_id
            ).delete()
            
            # 添加新的操作权限
            for operation_id in permissions.operation_ids:
                # 检查操作是否存在
                operation = db.query(models.Operation).filter(models.Operation.id == operation_id).first()
                if not operation:
                    results["errors"].append(f"操作ID {operation_id} 不存在")
                    continue
                
                # 创建操作权限
                db_permission = models.UserOperationPermission(
                    user_id=permissions.user_id,
                    operation_id=operation_id
                )
                db.add(db_permission)
                results["updated_operation_permissions"].append({
                    "operation_id": operation_id,
                    "operation_name": f"{operation.page_name} - {operation.action}"
                })
        
        # 提交所有更改
        db.commit()
        logger.info(f"[UserPerm][BatchUpdate] 成功 | user_id={permissions.user_id} devices={len(results['updated_device_permissions'])} ops={len(results['updated_operation_permissions'])} errors={len(results['errors'])}")
        
        return {
            "message": "权限修改完成",
            "user_id": permissions.user_id,
            "username": user.username,
            "updated_device_permissions": len(results["updated_device_permissions"]),
            "updated_operation_permissions": len(results["updated_operation_permissions"]),
            "errors": results["errors"],
            "details": results
        }
        
    except Exception as e:
        db.rollback()
        logger.exception(f"[UserPerm][BatchUpdate] 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"修改权限时发生错误: {str(e)}"
        )



@router.post("/get_users_with_pagination")
def get_users_with_pagination(
    request_data: schemas.UserPermissionsQuery,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取用户及其权限信息，支持按用户ID查询和分页 - 只有管理员可以查看"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[User][Page] 请求 | by_user_id={current_user.id} filters={{'user_id': { 'set' if bool(getattr(request_data, 'user_id', None)) else 'unset' }}}")
    
    # 权限检查：只有管理员可以查看用户权限信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看用户权限信息"
        )
    
    try:
        # 构建查询 - 只查询user类型的用户
        query = db.query(models.User).filter(models.User.permission_level == models.PermissionLevel.USER)
        
        # 如果指定了用户ID，则只查询该用户
        if request_data.user_id:
            query = query.filter(models.User.id == request_data.user_id)
        
        # 获取总数（用于分页信息）
        total_count = query.count()
        logger.info(f"[User][Page] 查询完成 | total_count={total_count}")
        
        # 按ID正序排列
        query = query.order_by(models.User.id.asc())
        
        # 应用分页
        offset = (request_data.page - 1) * request_data.page_size
        users = query.offset(offset).limit(request_data.page_size).all()
        logger.info(f"[User][Page] 分页 | page={request_data.page} size={request_data.page_size} page_count={len(users)}")
        
        # 构建设备和操作的映射字典（只获取用户权限相关的数据）
        device_map = {}
        operation_map = {}
        
        # 构建响应数据
        result = []
        for user in users:
            # 获取用户设备权限
            device_permissions = db.query(models.UserDevicePermission).filter(
                models.UserDevicePermission.user_id == user.id
            ).all()
            
            device_info = []
            for perm in device_permissions:
                # 如果设备信息不在映射中，则查询数据库
                if perm.device_id not in device_map:
                    device = db.query(models.Device).filter(models.Device.id == perm.device_id).first()
                    if device:
                        device_map[perm.device_id] = device
                
                device = device_map.get(perm.device_id)
                if device:
                    device_info.append({
                        "device_id": device.id,
                        "device_name": device.name,
                        "device_sn": device.sn,
                        "device_description": device.description,
                        "permission_id": perm.id,
                        "permission_create_time": perm.create_time
                    })
            
            # 获取用户操作权限
            operation_permissions = db.query(models.UserOperationPermission).filter(
                models.UserOperationPermission.user_id == user.id
            ).all()
            
            operation_info = []
            for perm in operation_permissions:
                # 如果操作信息不在映射中，则查询数据库
                if perm.operation_id not in operation_map:
                    operation = db.query(models.Operation).filter(models.Operation.id == perm.operation_id).first()
                    if operation:
                        operation_map[perm.operation_id] = operation
                
                operation = operation_map.get(perm.operation_id)
                if operation:
                    operation_info.append({
                        "operation_id": operation.id,
                        "page_name": operation.page_name,
                        "action": operation.action,
                        "permission_id": perm.id,
                        "permission_create_time": perm.create_time
                    })
            
            # 构建用户信息
            user_data = {
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "permission_level": user.permission_level,
                "create_time": user.create_time,
                "update_time": user.update_time,
                "device_permissions": device_info,
                "operation_permissions": operation_info,
                "device_permission_count": len(device_info),
                "operation_permission_count": len(operation_info)
            }
            
            result.append(user_data)
        
        # 计算分页信息
        total_pages = (total_count + request_data.page_size - 1) // request_data.page_size
        
        resp = {
            "users": result,
            "pagination": {
                "current_page": request_data.page,
                "page_size": request_data.page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": request_data.page < total_pages,
                "has_prev": request_data.page > 1
            }
        }
        logger.info(f"[User][Page] 成功 | current_page={request_data.page} total_pages={total_pages}")
        return resp
        
    except Exception as e:
        logger.exception(f"[User][Page] 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取用户权限信息时发生错误: {str(e)}"
        )