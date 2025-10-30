#!/usr/bin/env python3
"""
创建初始管理员用户脚本
用于创建第一个管理员账户，以便后续可以注册其他用户
"""

import sys
import os
import hashlib
import secrets

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from api.common.database import SessionLocal
from api.common import models
from api.router.user.auth import hash_password  # 统一使用应用内的哈希策略（bcrypt_sha256 优先）

def create_admin_user():
    """创建管理员用户"""
    db = SessionLocal()
    try:
        # 检查是否已有管理员用户
        admin_exists = db.query(models.User).filter(
            models.User.permission_level == models.PermissionLevel.ADMIN
        ).first()
        
        if admin_exists:
            print(f"管理员用户已存在: {admin_exists.username}")
            return admin_exists
        
        # 创建默认管理员用户
        admin_user = models.User(
            username="admin",
            email="admin@example.com",
            password=hash_password("admin123"),  # 默认密码
            permission_level=models.PermissionLevel.ADMIN,
            extra={"description": "系统管理员账户"}
        )
        
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        
        print("✅ 管理员用户创建成功!")
        print(f"用户名: {admin_user.username}")
        print(f"邮箱: {admin_user.email}")
        print(f"密码: admin123")
        print(f"权限级别: {admin_user.permission_level}")
        print("\n⚠️  请及时修改默认密码!")
        
        return admin_user
        
    except Exception as e:
        print(f"❌ 创建管理员用户失败: {e}")
        db.rollback()
        return None
    finally:
        db.close()

if __name__ == "__main__":
    print("==========================================")
    print("创建初始管理员用户")
    print("==========================================")
    
    user = create_admin_user()
    
    if user:
        print("\n==========================================")
        print("管理员用户创建完成!")
        print("现在可以使用管理员账户登录并注册其他用户")
        print("==========================================")
    else:
        print("\n❌ 管理员用户创建失败")
        sys.exit(1)
