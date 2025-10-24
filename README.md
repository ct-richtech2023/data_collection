# 数据采集系统

一个基于 FastAPI 的数据采集管理系统，支持用户管理、设备管理、数据文件管理和权限控制。

## 功能特性

- 🔐 **用户权限管理**: 支持管理员和普通用户两种权限级别
- 📱 **设备管理**: 设备注册、权限分配
- 📁 **数据文件管理**: 文件上传、下载、标签管理
- 📊 **操作日志**: 完整的操作记录和审计
- 🛡️ **安全认证**: JWT token 认证机制
- 🗄️ **数据库管理**: 使用 Alembic 进行数据库迁移

## 快速开始

### 1. 环境要求

- Python 3.8+
- PostgreSQL 12+
- pip (Python 包管理器)

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 数据库设置

#### 方法一：使用自动化脚本（推荐）

```bash
# 创建数据库
./create_database.sh

# 创建表结构和初始管理员用户
./create_tables.sh
```

#### 方法二：手动设置

```bash
# 1. 创建数据库
PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres -c "CREATE DATABASE filesvc;"

# 2. 运行数据库迁移
alembic upgrade head

# 3. 创建初始管理员用户
python3 create_admin_user.py
```

### 4. 启动应用

```bash
# 方法一：直接运行
cd api && python3 app.py

# 方法二：使用 uvicorn（推荐用于开发）
cd api && uvicorn app:app --reload --host 0.0.0.0 --port 9000
```

### 5. 访问应用

- **API 文档**: http://localhost:9000/docs
- **ReDoc 文档**: http://localhost:9000/redoc

## 初始账户

系统会自动创建初始管理员账户：

- **用户名**: `admin`
- **密码**: `admin123`
- **权限**: 管理员

⚠️ **重要**: 请在生产环境中及时修改默认密码！

## 数据库管理

### 查看迁移状态

```bash
# 查看当前迁移版本
alembic current

# 查看迁移历史
alembic history
```

### 创建新的迁移

```bash
# 当模型有变化时，生成迁移文件
alembic revision --autogenerate -m "描述你的更改"

# 应用迁移到数据库
alembic upgrade head
```

### 验证数据库表

```bash
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

## 用户权限说明

### 权限级别

- **管理员 (admin)**: 完全权限，可以管理所有用户、设备、数据
- **普通用户 (user)**: 只能查看和操作被授权的数据

### 用户注册

- 用户注册功能需要管理员权限
- 普通用户无法直接注册，需要管理员代为注册
- 使用管理员账户登录后，可以注册新用户

## API 接口

### 认证接口

- `POST /user/auth/login` - 用户登录
- `POST /user/auth/register` - 用户注册（需要管理员权限）

### 用户管理

- `GET /user/get_all_users` - 获取所有用户（管理员）
- `POST /user/get_user_by_id` - 根据ID获取用户（管理员）
- `POST /user/update_user` - 更新用户信息（管理员）
- `POST /user/delete_user` - 删除用户（管理员）

### 权限管理

- `POST /user/add_device_permission` - 添加设备权限（管理员）
- `POST /user/add_operation_permission` - 添加操作权限（管理员）
- `POST /user/add_user_permissions` - 批量添加设备权限和操作权限（管理员）
- `GET /user/get_user_device_permissions` - 获取用户设备权限（管理员）
- `GET /user/get_user_operation_permissions` - 获取用户操作权限（管理员）
- `POST /user/get_users_with_permissions` - 获取所有用户及其权限信息，支持筛选（管理员）
- `POST /user/remove_device_permission` - 移除设备权限（管理员）
- `POST /user/remove_operation_permission` - 移除操作权限（管理员）

### 设备管理

- `POST /device/create_device` - 创建设备
- `GET /device/get_all_devices` - 获取所有设备
- `POST /device/get_device_by_id` - 根据ID获取设备
- `POST /device/update_device` - 更新设备信息
- `POST /device/delete_device` - 删除设备

## 批量权限管理 API

### 新增接口：`POST /user/add_user_permissions`

**功能**: 为用户同时添加设备权限和操作权限

**权限要求**: 管理员权限

**请求参数**:
```json
{
  "user_id": 1,
  "device_ids": [1, 2, 3],
  "operation_ids": [1, 2, 3]
}
```

**响应示例**:
```json
{
  "message": "权限添加完成",
  "user_id": 1,
  "username": "testuser",
  "added_device_permissions": 2,
  "added_operation_permissions": 2,
  "errors": [],
  "details": {
    "user_id": 1,
    "device_permissions": [
      {"device_id": 1, "device_name": "设备1"},
      {"device_id": 2, "device_name": "设备2"}
    ],
    "operation_permissions": [
      {"operation_id": 1, "operation_name": "页面1 - 查看"},
      {"operation_id": 2, "operation_name": "页面2 - 编辑"}
    ],
    "errors": []
  }
}
```

**特性**:
- ✅ 支持批量添加设备权限和操作权限
- ✅ 自动检查权限是否已存在，避免重复
- ✅ 详细的错误信息和成功统计
- ✅ 事务安全，失败时自动回滚
- ✅ 只有管理员可以操作

### 新增接口：`POST /user/get_users_with_permissions`

**功能**: 获取普通用户及其权限信息，支持按用户ID查询和分页 - 只返回user类型用户

**权限要求**: 管理员权限

**请求参数**:
```json
{
  "user_id": 1,        // 可选，指定用户ID，为空则查询所有用户
  "page": 1,           // 可选，页码，从1开始，默认1
  "page_size": 10      // 可选，每页数量，默认10，最大100
}
```

**参数说明**:
- `user_id`: 指定用户ID，为空则查询所有用户
- `page`: 页码，从1开始，默认1
- `page_size`: 每页数量，默认10，最大100

**响应示例**:
```json
{
  "users": [
    {
      "user_id": 1,
      "username": "admin",
      "email": "admin@example.com",
      "permission_level": "admin",
      "create_time": "2024-01-01T00:00:00Z",
      "update_time": "2024-01-01T00:00:00Z",
      "device_permissions": [
        {
          "device_id": 1,
          "device_name": "设备1",
          "device_sn": "SN001",
          "device_description": "设备描述",
          "permission_id": 1,
          "permission_create_time": "2024-01-01T00:00:00Z"
        }
      ],
      "operation_permissions": [
        {
          "operation_id": 1,
          "page_name": "用户管理",
          "action": "查看",
          "permission_id": 1,
          "permission_create_time": "2024-01-01T00:00:00Z"
        }
      ],
      "device_permission_count": 1,
      "operation_permission_count": 1
    }
  ],
  "pagination": {
    "current_page": 1,
    "page_size": 10,
    "total_count": 1,
    "total_pages": 1,
    "has_next": false,
    "has_prev": false
  }
}
```

**特性**:
- ✅ 只返回user类型的普通用户（不包含admin用户）
- ✅ 支持按用户ID查询（单个用户）
- ✅ 支持查询所有普通用户
- ✅ 支持分页功能（页码、每页数量）
- ✅ 返回完整的用户信息（用户名、邮箱等）
- ✅ 返回用户权限详情
- ✅ 性能优化，减少数据库查询次数
- ✅ 分页信息（总页数、是否有下一页等）
- ✅ 只有管理员可以操作

### 新增接口：`PUT /user/update_user_permissions`

**功能**: 修改用户权限 - 只有管理员可以修改权限

**权限要求**: 管理员权限

**请求参数**:
```json
{
  "user_id": 1,                    // 必填，用户ID
  "device_ids": [1, 2, 3],         // 可选，设备ID列表，为空表示不修改设备权限
  "operation_ids": [1, 2, 3]       // 可选，操作ID列表，为空表示不修改操作权限
}
```

**参数说明**:
- `user_id`: 必填，要修改权限的用户ID
- `device_ids`: 可选，新的设备权限列表，为空表示不修改设备权限
- `operation_ids`: 可选，新的操作权限列表，为空表示不修改操作权限

**响应示例**:

**成功修改权限**:
```json
{
  "message": "权限修改完成",
  "user_id": 1,
  "username": "testuser",
  "updated_device_permissions": 2,
  "updated_operation_permissions": 3,
  "errors": [],
  "details": {
    "user_id": 1,
    "updated_device_permissions": [
      {
        "device_id": 1,
        "device_name": "设备1"
      },
      {
        "device_id": 2,
        "device_name": "设备2"
      }
    ],
    "updated_operation_permissions": [
      {
        "operation_id": 1,
        "operation_name": "用户管理 - 查看"
      },
      {
        "operation_id": 2,
        "operation_name": "设备管理 - 查看"
      },
      {
        "operation_id": 3,
        "operation_name": "数据管理 - 查看"
      }
    ],
    "errors": []
  }
}
```

**尝试修改管理员权限**:
```json
{
  "message": "该账号是管理员，无需修改权限",
  "user_id": 1,
  "username": "admin",
  "permission_level": "admin",
  "note": "管理员拥有所有权限，无需单独设置设备权限和操作权限"
}
```

**特性**:
- ✅ 支持修改设备权限和操作权限
- ✅ 支持只修改设备权限或只修改操作权限
- ✅ 完全替换现有权限（删除旧权限，添加新权限）
- ✅ 验证设备和操作是否存在
- ✅ 管理员用户检查：尝试修改管理员权限时返回提示信息
- ✅ 事务安全，失败时自动回滚
- ✅ 详细的错误信息和修改结果
- ✅ 只有管理员可以操作

## 数据库配置

### 连接信息

- **主机**: 192.168.2.131:5432
- **数据库**: filesvc
- **用户名**: postgres
- **密码**: richtech

### 配置文件

- 数据库连接: `api/common/database.py`
- Alembic 配置: `alembic.ini`
- 迁移文件: `alembic/versions/`

## 故障排除

### 常见问题

1. **数据库连接失败**
   ```bash
   # 检查数据库服务是否运行
   PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres -c "SELECT version();"
   ```

2. **迁移失败**
   ```bash
   # 重置数据库
   PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres -c "DROP DATABASE IF EXISTS filesvc;"
   ./create_database.sh
   ./create_tables.sh
   ```

3. **权限错误**
   - 确保使用管理员账户登录
   - 检查 JWT token 是否有效
   - 验证用户权限级别

### 调试模式

```bash
# 启用详细日志
export PYTHONPATH=/home/ubuntu/code/richtech/data_collection
cd api && python3 -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from app import app
import uvicorn
uvicorn.run(app, host='0.0.0.0', port=9000, log_level='debug')
"
```

## 开发指南

### 项目结构

```
data_collection/
├── api/                    # API 应用代码
│   ├── common/            # 公共模块
│   │   ├── database.py    # 数据库配置
│   │   ├── models.py      # 数据模型
│   │   └── schemas.py     # Pydantic 模型
│   ├── router/            # 路由模块
│   │   ├── user/          # 用户相关接口
│   │   └── device/        # 设备相关接口
│   └── app.py             # 应用入口
├── alembic/               # 数据库迁移
├── create_database.sh     # 数据库创建脚本
├── create_tables.sh       # 表创建脚本
├── create_admin_user.py   # 管理员用户创建脚本
└── requirements.txt       # Python 依赖
```

### 添加新功能

1. 在 `api/common/models.py` 中定义数据模型
2. 在 `api/common/schemas.py` 中定义 API 模型
3. 在 `api/router/` 中创建路由处理函数
4. 生成并运行数据库迁移
5. 更新 API 文档

## 部署说明

### 生产环境配置

1. **修改默认密码**
   ```bash
   # 使用管理员账户登录后修改密码
   curl -X POST "http://localhost:9000/user/update_user" \
        -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"id": 1, "password": "new_secure_password"}'
   ```

2. **数据库备份**
   ```bash
   # 备份数据库
   PGPASSWORD=richtech pg_dump -h 192.168.2.131 -U postgres filesvc > backup.sql
   
   # 恢复数据库
   PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres filesvc < backup.sql
   ```

3. **使用 Gunicorn 部署**
   ```bash
   pip install gunicorn
   cd api && gunicorn app:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:9000
   ```

## 许可证

本项目采用 MIT 许可证。详情请查看 LICENSE 文件。

## 贡献指南

1. Fork 本项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 联系方式

如有问题或建议，请通过以下方式联系：

- 项目 Issues: [GitHub Issues](https://github.com/your-repo/issues)
- 邮箱: your-email@example.com

---

**注意**: 请确保在生产环境中使用强密码，并定期备份数据库。
