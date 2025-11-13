#!/usr/bin/env python3
"""
创建初始操作数据脚本
用于初始化系统中的所有操作（Operation）记录
"""

import sys
import os
import argparse

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(__file__)
sys.path.insert(0, project_root)

from api.common.database import SessionLocal
from api.common import models

# 定义所有可能的页面和操作组合
PAGE_NAMES = ["data", "task", "label", "device", "user", "zip_data"]
ACTIONS = ["upload", "download", "update", "delete", "view"]


def create_operation(page_name: str, action: str):
    """创建单个操作"""
    db = SessionLocal()
    try:
        # 检查操作是否已存在
        existing_operation = db.query(models.Operation).filter(
            models.Operation.page_name == page_name,
            models.Operation.action == action
        ).first()
        
        if existing_operation:
            print(f"⚠️  操作已存在: {page_name} - {action} (ID: {existing_operation.id})")
            return existing_operation
        
        # 创建新操作
        operation = models.Operation(
            page_name=page_name,
            action=action
        )
        
        db.add(operation)
        db.commit()
        db.refresh(operation)
        
        print(f"✅ 操作创建成功: {page_name} - {action} (ID: {operation.id})")
        return operation
        
    except Exception as e:
        print(f"❌ 创建操作失败: {page_name} - {action}, 错误: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def create_all_operations():
    """创建所有可能的操作组合"""
    db = SessionLocal()
    try:
        created_count = 0
        existing_count = 0
        
        print("📋 开始创建所有操作组合...\n")
        
        for page_name in PAGE_NAMES:
            for action in ACTIONS:
                # 检查操作是否已存在
                existing_operation = db.query(models.Operation).filter(
                    models.Operation.page_name == page_name,
                    models.Operation.action == action
                ).first()
                
                if existing_operation:
                    print(f"⚠️  已存在: {page_name} - {action} (ID: {existing_operation.id})")
                    existing_count += 1
                else:
                    # 创建新操作
                    operation = models.Operation(
                        page_name=page_name,
                        action=action
                    )
                    db.add(operation)
                    print(f"✅ 创建: {page_name} - {action}")
                    created_count += 1
        
        db.commit()
        
        print(f"\n📊 完成! 创建了 {created_count} 个新操作, {existing_count} 个已存在")
        return created_count
        
    except Exception as e:
        print(f"❌ 批量创建操作失败: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def delete_operation(page_name: str, action: str):
    """删除操作"""
    db = SessionLocal()
    try:
        operation = db.query(models.Operation).filter(
            models.Operation.page_name == page_name,
            models.Operation.action == action
        ).first()
        
        if not operation:
            print(f"⚠️  操作不存在: {page_name} - {action}")
            return None
        
        db.delete(operation)
        db.commit()
        print(f"✅ 操作删除成功: {page_name} - {action}")
        return True
        
    except Exception as e:
        print(f"❌ 删除操作失败: {page_name} - {action}, 错误: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def list_all_operations():
    """列出所有操作"""
    db = SessionLocal()
    try:
        operations = db.query(models.Operation).order_by(
            models.Operation.page_name, 
            models.Operation.action
        ).all()
        
        if not operations:
            print("📋 当前没有操作记录")
            return []
        
        print(f"\n📋 共找到 {len(operations)} 个操作:\n")
        print("-" * 80)
        
        # 按页面分组显示
        current_page = None
        for operation in operations:
            if current_page != operation.page_name:
                if current_page is not None:
                    print()  # 页面之间空一行
                current_page = operation.page_name
                print(f"\n📄 页面: {operation.page_name.upper()}")
            
            print(f"  • {operation.action:10} (ID: {operation.id:3}) | 创建时间: {operation.create_time}")
        
        print("\n" + "-" * 80)
        
        return operations
    except Exception as e:
        print(f"❌ 查询所有操作失败: {e}")
        return None
    finally:
        db.close()


if __name__ == "__main__":
    """
    使用方法:
    python3 operations_operation.py create-all                    # 创建所有操作组合
    python3 operations_operation.py create --page data --action upload  # 创建单个操作
    python3 operations_operation.py delete --page data --action upload  # 删除操作
    python3 operations_operation.py list                            # 列出所有操作
    """
    parser = argparse.ArgumentParser(description="创建或管理操作（Operation）数据")
    subparsers = parser.add_subparsers(dest="action", help="操作类型")
    
    # 创建所有操作子命令
    create_all_parser = subparsers.add_parser("create-all", help="创建所有可能的操作组合")
    
    # 创建单个操作子命令
    create_parser = subparsers.add_parser("create", help="创建单个操作")
    create_parser.add_argument("--page", required=True, choices=PAGE_NAMES, help="页面名称")
    create_parser.add_argument("--action", required=True, choices=ACTIONS, help="操作类型")
    
    # 删除操作子命令
    delete_parser = subparsers.add_parser("delete", help="删除操作")
    delete_parser.add_argument("--page", required=True, choices=PAGE_NAMES, help="页面名称")
    delete_parser.add_argument("--action", required=True, choices=ACTIONS, help="操作类型")
    
    # 列出所有操作子命令
    list_parser = subparsers.add_parser("list", help="列出所有操作")
    
    args = parser.parse_args()
    
    if args.action == "create-all":
        create_all_operations()
    elif args.action == "create":
        create_operation(page_name=args.page, action=args.action)
    elif args.action == "delete":
        delete_operation(page_name=args.page, action=args.action)
    elif args.action == "list":
        list_all_operations()
    else:
        parser.print_help()

