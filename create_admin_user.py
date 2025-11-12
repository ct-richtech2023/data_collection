#!/usr/bin/env python3
"""
创建初始管理员用户脚本
用于创建第一个管理员账户，以便后续可以注册其他用户
"""

import sys
import os
import hashlib
import secrets
import argparse

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from api.common.database import SessionLocal
from api.common import models
from api.router.user.auth import hash_password  # 统一使用应用内的哈希策略（bcrypt_sha256 优先）

def create_admin_user(username: str, email: str, password: str):
    """创建管理员用户"""
    db = SessionLocal()
    try:
        # # 检查是否已有管理员用户
        # admin_exists = db.query(models.User).filter(
        #     models.User.permission_level == models.PermissionLevel.ADMIN
        # ).first()
        
        # if admin_exists:
        #     print(f"管理员用户已存在: {admin_exists.username}")
        #     return admin_exists
        
        # 创建默认管理员用户
        admin_user = models.User(
            username=username,
            email=email,
            password=hash_password(password),  # 默认密码
            permission_level=models.PermissionLevel.ADMIN,
            extra={"description": "系统管理员账户"}
        )
        
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        
        print("✅ 管理员用户创建成功!")
        print(f"用户名: {admin_user.username}")
        print(f"邮箱: {admin_user.email}")
        print(f"密码: {password}")
        print(f"权限级别: {admin_user.permission_level}")
        print("\n⚠️  请及时修改默认密码!")
        
        return admin_user
        
    except Exception as e:
        print(f"❌ 创建管理员用户失败: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def delete_admin_user(username: str):
    """删除管理员用户"""
    db = SessionLocal()
    try:
        db.query(models.User).filter(models.User.username == username).delete()
        db.commit()
        print("✅ 管理员用户删除成功!")
    except Exception as e:
        print(f"❌ 删除管理员用户失败: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def select_all_users():
    """查询所有用户并打印信息"""
    db = SessionLocal()
    try:
        users = db.query(models.User).all()
        
        if not users:
            print("📋 当前没有用户")
            return []
        
        print(f"\n📋 共找到 {len(users)} 个用户:\n")
        print("-" * 80)
        
        for idx, user in enumerate(users, 1):
            print(f"\n用户 #{idx}:")
            print(f"  ID: {user.id}")
            print(f"  用户名: {user.username}")
            print(f"  邮箱: {user.email}")
            print(f"  权限级别: {user.permission_level}")
            if user.extra:
                print(f"  扩展信息: {user.extra}")
            if user.create_time:
                print(f"  创建时间: {user.create_time}")
            if user.update_time:
                print(f"  更新时间: {user.update_time}")
        
        print("\n" + "-" * 80)
        
        return users
    except Exception as e:
        print(f"❌ 查询所有用户失败: {e}")
        return None
    finally:
        db.close()

if __name__ == "__main__":
    """
    使用方法:
    python3 create_admin_user.py create --username admin001 --email admin001@example.com --password admin123
    python3 create_admin_user.py delete --username admin001
    python3 create_admin_user.py list
    """
    parser = argparse.ArgumentParser(description="创建或删除管理员用户")
    subparsers = parser.add_subparsers(dest="action", help="操作类型")
    
    # 创建用户子命令
    create_parser = subparsers.add_parser("create", help="创建管理员用户")
    create_parser.add_argument("--username", required=True, help="用户名")
    create_parser.add_argument("--email", required=True, help="邮箱地址")
    create_parser.add_argument("--password", required=True, help="密码")
    
    # 删除用户子命令
    delete_parser = subparsers.add_parser("delete", help="删除管理员用户")
    delete_parser.add_argument("--username", required=True, help="要删除的用户名")
    
    # 列出所有用户子命令
    list_parser = subparsers.add_parser("list", help="列出所有用户")
    
    args = parser.parse_args()
    
    if args.action == "create":
        create_admin_user(username=args.username, email=args.email, password=args.password)
    elif args.action == "delete":
        delete_admin_user(username=args.username)
    elif args.action == "list":
        select_all_users()
    else:
        parser.print_help()