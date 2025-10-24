# 数据库和表创建操作指南

## 概述

本文档详细说明了如何创建 `filesvc` 数据库以及所有必要的表结构。系统使用 PostgreSQL 数据库和 Alembic 进行数据库迁移管理。

## 数据库配置

### 连接信息
- **数据库服务器**: `192.168.2.131:5432`
- **数据库名称**: `filesvc`
- **用户名**: `postgres`
- **密码**: `richtech`

### 配置文件位置
- 数据库连接配置: `api/common/database.py`
- Alembic 配置: `alembic.ini`
- 迁移文件目录: `alembic/versions/`

## 操作步骤

### 1. 创建数据库

```bash
# 使用 psql 创建数据库
PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres -c "CREATE DATABASE filesvc;"
```

**预期输出**:
```
CREATE DATABASE
```

### 2. 安装依赖

```bash
# 安装 Python 依赖
cd /home/ubuntu/code/richtech/data_collection
pip install -r requirements.txt
```

**主要依赖**:
- `fastapi` - Web 框架
- `sqlalchemy` - ORM 框架
- `psycopg2-binary` - PostgreSQL 驱动
- `alembic` - 数据库迁移工具
- `passlib[bcrypt]` - 密码加密
- `python-jose[cryptography]` - JWT 处理

### 3. 运行数据库迁移

```bash
# 运行所有迁移
cd /home/ubuntu/code/richtech/data_collection
alembic upgrade head
```

**预期输出**:
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 4faf69075c6e, create_initial_users_table
INFO  [alembic.runtime.migration] Running upgrade 4faf69075c6e -> 23b2502e5beb, Add email and permission_level to users table
INFO  [alembic.runtime.migration] Running upgrade 23b2502e5beb -> b20d95045409, 添加所有新表：device、operation、task、label、权限映射表、数据文件表、操作日志表
INFO  [alembic.runtime.migration] Running upgrade b20d95045409 -> bec0bfe62bad, remove_email_unique_constraint
```

### 4. 验证数据库表

```bash
# 查看所有表
cd /home/ubuntu/code/richtech/data_collection
python3 -c "
from api.common.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text(\"\"\"
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name
    \"\"\"))
    tables = [row[0] for row in result]
    print('数据库表列表:')
    for table in tables:
        print(f'  - {table}')
"
```

**预期输出**:
```
数据库表列表:
  - alembic_version
  - data_file
  - data_file_label
  - device
  - label
  - operation
  - operation_log
  - task
  - user_device_permission
  - user_operation_permission
  - users
```

### 5. 测试数据库连接

```bash
# 测试数据库连接
cd /home/ubuntu/code/richtech/data_collection/api
python3 -c "
from common.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text('SELECT COUNT(*) FROM users'))
    count = result.scalar()
    print(f'用户表记录数: {count}')
    print('数据库连接测试成功！')
"
```

**预期输出**:
```
用户表记录数: 0
数据库连接测试成功！
```

## 数据库表结构

### 核心表

#### 1. users (用户表)
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(150) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,
    permission_level VARCHAR(20) NOT NULL DEFAULT 'user',
    extra JSONB,
    create_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    update_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);
```

**字段说明**:
- `id`: 主键，自增
- `username`: 用户名，唯一
- `email`: 邮箱地址（允许多个用户使用相同邮箱）
- `password`: 加密后的密码
- `permission_level`: 权限级别（admin/user）
- `extra`: 扩展字段，存储 JSON 数据
- `create_time`: 创建时间
- `update_time`: 更新时间

#### 2. device (设备表)
```sql
CREATE TABLE device (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    sn TEXT NOT NULL UNIQUE,
    description TEXT,
    create_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    update_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);
```

#### 3. operation (操作表)
```sql
CREATE TABLE operation (
    id SERIAL PRIMARY KEY,
    page_name TEXT NOT NULL,
    action TEXT NOT NULL,
    create_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    update_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE(page_name, action)
);
```

#### 4. task (任务表)
```sql
CREATE TABLE task (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    create_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    update_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);
```

#### 5. label (标签表)
```sql
CREATE TABLE label (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    create_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    update_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);
```

### 关联表

#### 6. user_device_permission (用户设备权限表)
```sql
CREATE TABLE user_device_permission (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    device_id INTEGER NOT NULL,
    create_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    update_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE(user_id, device_id)
);
```

#### 7. user_operation_permission (用户操作权限表)
```sql
CREATE TABLE user_operation_permission (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    operation_id INTEGER NOT NULL,
    create_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    update_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE(user_id, operation_id)
);
```

### 数据表

#### 8. data_file (数据文件表)
```sql
CREATE TABLE data_file (
    id SERIAL PRIMARY KEY,
    task_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    download_url TEXT NOT NULL,
    duration_ms BIGINT,
    user_id INTEGER NOT NULL,
    device_id INTEGER NOT NULL,
    create_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    update_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);
```

#### 9. data_file_label (数据文件标签映射表)
```sql
CREATE TABLE data_file_label (
    id SERIAL PRIMARY KEY,
    data_file_id INTEGER NOT NULL,
    label_id INTEGER NOT NULL,
    create_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    update_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE(data_file_id, label_id)
);
```

#### 10. operation_log (操作日志表)
```sql
CREATE TABLE operation_log (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    data_file_id INTEGER,
    content TEXT,
    create_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    update_time TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);
```

## 迁移文件说明

### 迁移文件顺序

1. **4faf69075c6e** - `create_initial_users_table.py`
   - 创建基础用户表
   - 包含 id, username, password, create_time, update_time

2. **23b2502e5beb** - `add_email_and_permission_level_to_users_.py`
   - 添加 email 和 permission_level 字段到用户表
   - 创建邮箱唯一索引（后续被移除）

3. **b20d95045409** - `添加所有新表_device_operation_task_label_.py`
   - 创建所有业务表
   - 包括设备、操作、任务、标签、权限映射、数据文件、操作日志表

4. **bec0bfe62bad** - `remove_email_unique_constraint.py`
   - 移除邮箱唯一约束
   - 允许多个用户使用相同邮箱

### 查看迁移状态

```bash
# 查看当前迁移状态
alembic current

# 查看迁移历史
alembic history

# 查看待执行的迁移
alembic show head
```

## 权限级别说明

### PermissionLevel 枚举

```python
class PermissionLevel:
    ADMIN = "admin"        # 管理员：完全权限
    USER = "user"          # 普通用户：只能查看数据
```

### 权限检查方法

```python
def has_permission(self, required_level):
    """检查用户是否有指定权限级别"""
    level_hierarchy = {
        PermissionLevel.USER: 2,
        PermissionLevel.ADMIN: 1
    }
    user_level = level_hierarchy.get(self.permission_level, 0)
    required_level_value = level_hierarchy.get(required_level, 0)
    return user_level >= required_level_value

def is_admin(self):
    """检查是否为管理员"""
    return self.has_permission(PermissionLevel.ADMIN)

def is_user(self):
    """检查是否为普通用户或管理员"""
    return self.has_permission(PermissionLevel.USER)
```

## 常见问题解决

### 1. 数据库连接失败

**错误**: `FATAL: database "filesvc" does not exist`

**解决方案**:
```bash
PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres -c "CREATE DATABASE filesvc;"
```

### 2. 迁移失败

**错误**: `relation "users" does not exist`

**解决方案**:
- 检查迁移文件依赖关系
- 确保基础表创建迁移在最前面
- 重新运行 `alembic upgrade head`

### 3. 唯一约束冲突

**错误**: `duplicate key value violates unique constraint`

**解决方案**:
- 邮箱不再有唯一约束，允许多个用户使用相同邮箱
- 只有用户名需要唯一

## 启动应用

```bash
# 启动 FastAPI 应用
cd /home/ubuntu/code/richtech/data_collection/api
python3 app.py

# 或使用 uvicorn
cd /home/ubuntu/code/richtech/data_collection/api
uvicorn app:app --reload --host 0.0.0.0 --port 9000
```

## 维护操作

### 备份数据库

```bash
# 备份数据库
PGPASSWORD=richtech pg_dump -h 192.168.2.131 -U postgres filesvc > backup.sql

# 恢复数据库
PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres filesvc < backup.sql
```

### 清理数据

```bash
# 清空所有表数据（保留表结构）
PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres filesvc -c "
TRUNCATE TABLE operation_log, data_file_label, data_file, user_operation_permission, user_device_permission, label, task, operation, device, users RESTART IDENTITY CASCADE;
"
```

### 重置数据库

```bash
# 删除所有表
PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres filesvc -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# 重新运行迁移
alembic upgrade head
```

---

**注意**: 请确保在生产环境中使用强密码，并定期备份数据库。
