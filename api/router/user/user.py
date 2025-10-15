from fastapi import FastAPI, Depends, HTTPException, status, Header, APIRouter
from sqlalchemy.orm import Session
from typing import List, Optional
from common.database import Base, engine, get_db
from common import models, schemas
from .auth import hash_password, authenticate_user, create_access_token, get_current_user

router = APIRouter(
    tags=["user"],
)

@router.post("/auth/register")
def register(user_in: schemas.User, db: Session = Depends(get_db)):
    exists = db.query(models.User).filter(models.User.username == user_in.username).first()
    if exists:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # 检查用户名是否已存在
    username_exists = db.query(models.User).filter(models.User.username == user_in.username).first()
    if username_exists:
        raise HTTPException(status_code=400, detail="Username already taken")
    
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
        if update_data["permission_level"] not in ["admin", "uploader", "viewer"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="权限级别必须是 admin、uploader 或 viewer"
            )
    
    # 更新字段 - 只更新非None的字段
    for field, value in update_data.items():
        if value is not None:
            setattr(user, field, value)
    
    db.commit()
    db.refresh(user)
    return user


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
