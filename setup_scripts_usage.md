# 数据库设置脚本使用说明

## 脚本文件

### 1. create_database.sh
**功能**: 创建 PostgreSQL 数据库

**主要操作**:
- 检查 PostgreSQL 客户端是否安装
- 检查数据库是否已存在
- 创建 `filesvc` 数据库
- 设置数据库编码和时区
- 创建必要的扩展
- 验证数据库连接

### 2. create_tables.sh
**功能**: 在数据库中创建所有表结构

**主要操作**:
- 检查项目环境和依赖
- 检查数据库连接
- 运行 Alembic 迁移
- 验证表创建
- 显示表结构统计
- 测试数据库连接

## 使用方法

### 方法一：按顺序执行

```bash
# 1. 创建数据库
./create_database.sh

# 2. 创建表结构
./create_tables.sh
```

### 方法二：一键执行

```bash
# 创建数据库和表结构
./create_database.sh && ./create_tables.sh
```

### 方法三：使用 bash 执行

```bash
# 如果脚本没有执行权限
bash create_database.sh
bash create_tables.sh
```

## 配置信息

### 数据库连接配置
- **主机**: 192.168.2.131
- **端口**: 5432
- **用户名**: postgres
- **密码**: richtech
- **数据库名**: filesvc

### 项目路径
- **项目根目录**: /home/ubuntu/code/richtech/data_collection

## 脚本特性

### create_database.sh 特性
- ✅ 自动检查 PostgreSQL 客户端
- ✅ 检查数据库是否已存在
- ✅ 支持删除重建数据库
- ✅ 设置数据库时区为 Asia/Shanghai
- ✅ 创建必要的 PostgreSQL 扩展
- ✅ 验证数据库连接

### create_tables.sh 特性
- ✅ 检查项目环境和 Python 依赖
- ✅ 自动安装缺失的依赖包
- ✅ 检查数据库连接状态
- ✅ 支持删除重建所有表
- ✅ 使用 Alembic 进行数据库迁移
- ✅ 显示表结构统计信息
- ✅ 测试数据库连接和查询

## 错误处理

### 常见错误及解决方案

#### 1. psql 命令未找到
```bash
# Ubuntu/Debian
sudo apt-get install postgresql-client

# CentOS/RHEL
sudo yum install postgresql
```

#### 2. Python 依赖缺失
```bash
# 脚本会自动安装，或手动安装
pip install -r requirements.txt
```

#### 3. 数据库连接失败
- 检查数据库服务器是否运行
- 检查网络连接
- 验证用户名和密码
- 确认数据库已创建

#### 4. 迁移失败
- 检查 Alembic 配置
- 验证迁移文件完整性
- 检查数据库权限

## 输出示例

### create_database.sh 输出
```
==========================================
开始创建数据库: filesvc
==========================================
检查数据库是否已存在...
创建数据库: filesvc
✅ 数据库 'filesvc' 创建成功
设置数据库编码和时区...
创建必要的扩展...
验证数据库连接...
✅ 数据库连接测试成功
==========================================
数据库创建完成!
数据库名称: filesvc
连接信息: postgres@192.168.2.131:5432/filesvc
==========================================
```

### create_tables.sh 输出
```
==========================================
开始创建数据库表结构
==========================================
检查数据库连接...
✅ 数据库连接成功
运行数据库迁移...
INFO  [alembic.runtime.migration] Running upgrade  -> 4faf69075c6e, create_initial_users_table
INFO  [alembic.runtime.migration] Running upgrade 4faf69075c6e -> 23b2502e5beb, Add email and permission_level to users table
INFO  [alembic.runtime.migration] Running upgrade 23b2502e5beb -> b20d95045409, 添加所有新表：device、operation、task、label、权限映射表、数据文件表、操作日志表
INFO  [alembic.runtime.migration] Running upgrade b20d95045409 -> bec0bfe62bad, remove_email_unique_constraint
✅ 数据库迁移成功
验证表创建...
创建的表: users, device, operation, task, label, user_device_permission, user_operation_permission, data_file, data_file_label, operation_log

表结构统计:
 表名 | 字段数
------+-------
 users |      8
 device|      6
 ...

✅ 数据库连接测试成功，用户表记录数: 0
==========================================
✅ 数据库表创建完成!
数据库: filesvc
主机: 192.168.2.131:5432
用户: postgres
==========================================

下一步操作:
1. 启动应用: cd api && python3 app.py
2. 或使用 uvicorn: cd api && uvicorn app:app --reload --host 0.0.0.0 --port 9000
3. 访问 API 文档: http://localhost:9000/docs

### 初始管理员账户:
- **用户名**: admin
- **密码**: admin123
- **权限**: 管理员
- **注意**: 请及时修改默认密码!

### 用户注册说明:
- 用户注册功能需要管理员权限
- 使用管理员账户登录后，可以注册新用户
- 普通用户无法直接注册，需要管理员代为注册
```

## 注意事项

1. **权限要求**: 确保脚本有执行权限
2. **网络连接**: 确保能连接到数据库服务器
3. **依赖安装**: 确保 Python 和 PostgreSQL 客户端已安装
4. **数据备份**: 重建数据库前请备份重要数据
5. **环境变量**: 脚本使用硬编码的数据库配置，如需修改请编辑脚本

## 故障排除

### 调试模式
```bash
# 启用调试模式查看详细输出
bash -x create_database.sh
bash -x create_tables.sh
```

### 手动验证
```bash
# 手动测试数据库连接
PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres -d filesvc -c "SELECT version();"

# 查看表列表
PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres -d filesvc -c "\dt"
```

### 重置环境
```bash
# 完全重置数据库
PGPASSWORD=richtech psql -h 192.168.2.131 -U postgres -c "DROP DATABASE IF EXISTS filesvc;"
./create_database.sh
./create_tables.sh
```
