#!/bin/bash

# 创建表结构脚本
# 用于在 filesvc 数据库中创建所有必要的表

set -e  # 遇到错误立即退出

# 数据库连接配置
DB_HOST="127.0.0.1"
DB_PORT="5432"
DB_USER="postgres"
DB_PASSWORD="richtech"
DB_NAME="filesvc"

# 项目根目录
PROJECT_ROOT="/home/ec2-user/data_collection"

echo "=========================================="
echo "开始创建数据库表结构"
echo "=========================================="

# 检查项目目录是否存在
if [ ! -d "$PROJECT_ROOT" ]; then
    echo "错误: 项目目录不存在: $PROJECT_ROOT"
    exit 1
fi

cd "$PROJECT_ROOT"

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "错误: python3 未找到，请先安装 Python 3"
    exit 1
fi

# 检查 alembic 是否安装
if ! python3 -c "import alembic" 2>/dev/null; then
    echo "安装必要的 Python 依赖..."
    pip install -r requirements.txt
fi

# 检查数据库连接
echo "检查数据库连接..."

# 设置 psql 调用方式：本机 psql 或容器内 psql（filesvc-pg）
USE_DOCKER_PSQL=0
if ! command -v psql &> /dev/null; then
    if docker ps --format '{{.Names}}' | grep -q '^filesvc-pg$'; then
        echo "未检测到本机 psql，将使用容器 filesvc-pg 内的 psql 执行"
        USE_DOCKER_PSQL=1
    else
        echo "错误: 未找到 psql，且未检测到容器 filesvc-pg"
        echo "请安装客户端或先启动数据库容器后重试"
        exit 1
    fi
fi

run_psql() {
    if [ "$USE_DOCKER_PSQL" -eq 1 ]; then
        docker exec -e PGPASSWORD="$DB_PASSWORD" -i filesvc-pg psql "$@"
    else
        PGPASSWORD="$DB_PASSWORD" psql "$@"
    fi
}

run_psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "SELECT 1;" > /dev/null

if [ $? -ne 0 ]; then
    echo "❌ 数据库连接失败，请先运行 create_database.sh 创建数据库"
    exit 1
fi

echo "✅ 数据库连接成功"

# 检查是否已有表存在
echo "检查现有表..."
TABLE_COUNT=$(run_psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -tAc "
SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name != 'alembic_version';
" 2>/dev/null || echo "0")

if [ "$TABLE_COUNT" -gt 0 ]; then
    echo "警告: 数据库中已存在 $TABLE_COUNT 个表"
    read -p "是否要删除所有表并重新创建? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "删除现有表..."
        run_psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO $DB_USER;
GRANT ALL ON SCHEMA public TO public;
"
    else
        echo "操作取消"
        exit 0
    fi
fi

# 运行 Alembic 迁移
echo "运行数据库迁移..."
# 将脚本中的连接参数导出为 Alembic/应用读取的 DATABASE_URL，确保与上面的连接一致
export DATABASE_URL="postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"
alembic upgrade head

if [ $? -eq 0 ]; then
    echo "✅ 数据库迁移成功"
else
    echo "❌ 数据库迁移失败"
    exit 1
fi

# 验证表创建
echo "验证表创建..."
TABLE_LIST=$(run_psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -tAc "
SELECT string_agg(table_name, ', ' ORDER BY table_name) 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name != 'alembic_version';
" 2>/dev/null || echo "无表")

echo "创建的表: $TABLE_LIST"

# 显示表结构统计
echo ""
echo "表结构统计:"
run_psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "
SELECT 
    tablename as \"表名\",
    COUNT(*) as \"字段数\"
FROM pg_attribute a
JOIN pg_class c ON a.attrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
WHERE n.nspname = 'public'
AND a.attnum > 0
AND NOT a.attisdropped
GROUP BY tablename
ORDER BY tablename;
"

# 创建初始管理员用户
echo ""
echo "创建初始管理员用户..."
python3 create_admin_user.py

# 测试数据库连接
echo ""
echo "测试数据库连接..."
python3 -c "
from api.common.database import engine
from sqlalchemy import text
try:
    with engine.connect() as conn:
        result = conn.execute(text('SELECT COUNT(*) FROM users'))
        count = result.scalar()
        print(f'✅ 数据库连接测试成功，用户表记录数: {count}')
except Exception as e:
    print(f'❌ 数据库连接测试失败: {e}')
    exit(1)
"

if [ $? -eq 0 ]; then
    echo "=========================================="
    echo "✅ 数据库表创建完成!"
    echo "数据库: $DB_NAME"
    echo "主机: $DB_HOST:$DB_PORT"
    echo "用户: $DB_USER"
    echo "=========================================="
    
    echo ""
    echo "下一步操作:"
    echo "1. 启动应用: cd api && python3 app.py"
    echo "2. 或使用 uvicorn: cd api && uvicorn app:app --reload --host 0.0.0.0 --port 9000"
    echo "3. 访问 API 文档: http://localhost:9000/docs"
else
    echo "❌ 数据库连接测试失败"
    exit 1
fi
