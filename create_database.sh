#!/bin/bash

# 创建数据库脚本
# 用于创建 filesvc 数据库

set -e  # 遇到错误立即退出

# 数据库连接配置
DB_HOST="192.168.2.131"
DB_PORT="5432"
DB_USER="postgres"
DB_PASSWORD="richtech"
DB_NAME="filesvc"

echo "=========================================="
echo "开始创建数据库: $DB_NAME"
echo "=========================================="

# 检查 PostgreSQL 客户端是否安装
if ! command -v psql &> /dev/null; then
    echo "错误: psql 命令未找到，请先安装 PostgreSQL 客户端"
    echo "Ubuntu/Debian: sudo apt-get install postgresql-client"
    echo "CentOS/RHEL: sudo yum install postgresql"
    exit 1
fi

# 检查数据库是否已存在
echo "检查数据库是否已存在..."
DB_EXISTS=$(PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null || echo "0")

if [ "$DB_EXISTS" = "1" ]; then
    echo "警告: 数据库 '$DB_NAME' 已存在"
    read -p "是否要删除并重新创建数据库? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "删除现有数据库..."
        PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;"
    else
        echo "操作取消"
        exit 0
    fi
fi

# 创建数据库
echo "创建数据库: $DB_NAME"
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d postgres -c "CREATE DATABASE $DB_NAME;"

if [ $? -eq 0 ]; then
    echo "✅ 数据库 '$DB_NAME' 创建成功"
else
    echo "❌ 数据库创建失败"
    exit 1
fi

# 设置数据库编码和时区
echo "设置数据库编码和时区..."
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "
ALTER DATABASE $DB_NAME SET timezone TO 'Asia/Shanghai';
"

# 创建扩展（如果需要）
echo "创建必要的扩展..."
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "
CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";
CREATE EXTENSION IF NOT EXISTS \"pg_trgm\";
"

# 验证数据库创建
echo "验证数据库连接..."
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "SELECT current_database(), current_user, version();"

if [ $? -eq 0 ]; then
    echo "✅ 数据库连接测试成功"
else
    echo "❌ 数据库连接测试失败"
    exit 1
fi

echo "=========================================="
echo "数据库创建完成!"
echo "数据库名称: $DB_NAME"
echo "连接信息: $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
echo "=========================================="
