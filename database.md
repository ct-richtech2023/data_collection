
# 🗂 数据采集管理系统数据库设计文档（PostgreSQL）

## 1️⃣ 用户与权限模块

### **表：user（用户表）**

| 字段            | 类型          | 约束               | 说明     |
| ------------- | ----------- | ---------------- | ------ |
| id            | bigserial   | PK               | 主键，自增  |
| username      | text        | UNIQUE, NOT NULL | 用户名    |
| password_hash | text        | NOT NULL         | 加密后的密码 |
| email         | text        | UNIQUE           | 邮箱地址   |
| create_time   | timestamptz | DEFAULT now()    | 创建时间   |
| update_time   | timestamptz | DEFAULT now()    | 更新时间   |

---

### **表：user_device_permission（用户-设备权限表）**

| 字段          | 类型          | 约束            | 说明                  |
| ----------- | ----------- | ------------- | ------------------- |
| id          | bigserial   | PK            | 主键，自增               |
| user_id     | bigint      | FK, NOT NULL  | 用户ID，关联 `user.id`   |
| device_id   | bigint      | FK, NOT NULL  | 设备ID，关联 `device.id` |
| create_time | timestamptz | DEFAULT now() | 创建时间                |
| update_time | timestamptz | DEFAULT now() | 更新时间                |

> 🔒 唯一约束：`(user_id, device_id)`
> 📈 索引：`user_id`、`device_id`

---

### **表：user_operation_permission（用户-操作权限表）**

| 字段           | 类型          | 约束            | 说明                     |
| ------------ | ----------- | ------------- | ---------------------- |
| id           | bigserial   | PK            | 主键，自增                  |
| user_id      | bigint      | FK, NOT NULL  | 用户ID，关联 `user.id`      |
| operation_id | bigint      | FK, NOT NULL  | 操作ID，关联 `operation.id` |
| create_time  | timestamptz | DEFAULT now() | 创建时间                   |
| update_time  | timestamptz | DEFAULT now() | 更新时间                   |

> 🔒 唯一约束：`(user_id, operation_id)`
> 📈 索引：`user_id`、`operation_id`

---

## 2️⃣ 基础定义模块

### **表：task（任务表）**

| 字段          | 类型          | 约束            | 说明    |
| ----------- | ----------- | ------------- | ----- |
| id          | bigserial   | PK            | 主键，自增 |
| name        | text        | NOT NULL      | 任务名称  |
| create_time | timestamptz | DEFAULT now() | 创建时间  |
| update_time | timestamptz | DEFAULT now() | 更新时间  |

---

### **表：label（标签表）**

| 字段          | 类型          | 约束               | 说明    |
| ----------- | ----------- | ---------------- | ----- |
| id          | bigserial   | PK               | 主键，自增 |
| name        | text        | UNIQUE, NOT NULL | 标签名称  |
| create_time | timestamptz | DEFAULT now()    | 创建时间  |
| update_time | timestamptz | DEFAULT now()    | 更新时间  |

---

### **表：device（设备表）**

| 字段          | 类型          | 约束            | 说明    |
| ----------- | ----------- | ------------- | ----- |
| id          | bigserial   | PK            | 主键，自增 |
| name        | text        | NOT NULL      | 设备名称  |
| sn          | text        | NOT NULL, UNIQUE | 设备序列号 |
| description | text        | NULL          | 设备描述  |
| create_time | timestamptz | DEFAULT now() | 创建时间  |
| update_time | timestamptz | DEFAULT now() | 更新时间  |

---

### **表：operation（操作表）**

| 字段          | 类型          | 约束            | 说明                 |
| ----------- | ----------- | ------------- | ------------------ |
| id          | bigserial   | PK            | 主键，自增              |
| page_name   | text        | NOT NULL      | 页面名称               |
| action      | text        | NOT NULL      | 操作类型（查询/上传/下载/删除等） |
| create_time | timestamptz | DEFAULT now() | 创建时间               |
| update_time | timestamptz | DEFAULT now() | 更新时间               |

> 🔒 唯一约束：`(page_name, action)`

---

## 3️⃣ 数据采集模块

### **表：data_file（数据采集文件表）**

| 字段           | 类型          | 约束            | 说明                  |
| ------------ | ----------- | ------------- | ------------------- |
| id           | bigserial   | PK            | 主键，自增               |
| task_id      | bigint      | FK, NOT NULL  | 任务ID，关联 `task.id`   |
| file_name    | text        | NOT NULL      | 文件名称（如 .mcap 文件）    |
| download_url | text        | NOT NULL      | 下载地址                |
| duration_ms  | bigint      |               | 文件时长（毫秒）            |
| user_id      | bigint      | FK, NOT NULL  | 上传人，关联 `user.id`    |
| device_id    | bigint      | FK, NOT NULL  | 设备ID，关联 `device.id` |
| create_time  | timestamptz | DEFAULT now() | 创建时间                |
| update_time  | timestamptz | DEFAULT now() | 更新时间                |

> 📈 索引：`task_id`、`device_id`、`user_id`、`create_time`

---

### **表：data_file_label（数据文件标签映射表）**

| 字段           | 类型          | 约束            | 说明                       |
| ------------ | ----------- | ------------- | ------------------------ |
| id           | bigserial   | PK            | 主键，自增                    |
| data_file_id | bigint      | FK, NOT NULL  | 数据文件ID，关联 `data_file.id` |
| label_id     | bigint      | FK, NOT NULL  | 标签ID，关联 `label.id`       |
| create_time  | timestamptz | DEFAULT now() | 创建时间                     |
| update_time  | timestamptz | DEFAULT now() | 更新时间                     |

> 🔒 唯一约束：`(data_file_id, label_id)`
> 📈 索引：`data_file_id`、`label_id`

---

## 4️⃣ 日志模块

### **表：operation_log（操作日志表）**

| 字段           | 类型          | 约束            | 说明                        |
| ------------ | ----------- | ------------- | ------------------------- |
| id           | bigserial   | PK            | 主键，自增                     |
| username     | text        | NOT NULL      | 操作人用户名                    |
| action       | text        | NOT NULL      | 操作类型                      |
| data_file_id | bigint      | FK            | 关联数据文件 `data_file.id`（可选） |
| content      | text        |               | 操作内容描述                    |
| create_time  | timestamptz | DEFAULT now() | 创建时间                      |
| update_time  | timestamptz | DEFAULT now() | 更新时间                      |

> 📈 索引：`(username)`、`(create_time)`
> 💡 可扩展字段：`ip_address inet`、`result text`

---

## 5️⃣ ER 关系概览（Mermaid 可视化）

```mermaid
erDiagram
    USER ||--o{ USER_DEVICE_PERMISSION : "授权设备"
    USER ||--o{ USER_OPERATION_PERMISSION : "授权操作"
    USER ||--o{ DATA_FILE : "上传文件"
    USER ||--o{ OPERATION_LOG : "执行操作"

    TASK ||--o{ DATA_FILE : "包含文件"
    DEVICE ||--o{ DATA_FILE : "被采集设备"
    LABEL ||--o{ DATA_FILE_LABEL : "标签绑定"
    DATA_FILE ||--o{ DATA_FILE_LABEL : "文件标签"

    OPERATION ||--o{ USER_OPERATION_PERMISSION : "可执行"
    DEVICE ||--o{ USER_DEVICE_PERMISSION : "可访问"

    OPERATION_LOG }o--o{ DATA_FILE : "记录文件操作"

    USER {
      bigserial id PK
      text username UNIQUE
      text password_hash
      text email UNIQUE
      timestamptz create_time
      timestamptz update_time
    }

    USER_DEVICE_PERMISSION {
      bigserial id PK
      bigint user_id FK
      bigint device_id FK
      timestamptz create_time
      timestamptz update_time
      UNIQUE(user_id, device_id)
    }

    USER_OPERATION_PERMISSION {
      bigserial id PK
      bigint user_id FK
      bigint operation_id FK
      timestamptz create_time
      timestamptz update_time
      UNIQUE(user_id, operation_id)
    }

    TASK {
      bigserial id PK
      text name
      timestamptz create_time
      timestamptz update_time
    }

    LABEL {
      bigserial id PK
      text name UNIQUE
      timestamptz create_time
      timestamptz update_time
    }

    DEVICE {
      bigserial id PK
      text name
      timestamptz create_time
      timestamptz update_time
    }

    OPERATION {
      bigserial id PK
      text page_name
      text action
      timestamptz create_time
      timestamptz update_time
      UNIQUE(page_name, action)
    }

    DATA_FILE {
      bigserial id PK
      bigint task_id FK
      text file_name
      text download_url
      bigint duration_ms
      bigint user_id FK
      bigint device_id FK
      timestamptz create_time
      timestamptz update_time
    }

    DATA_FILE_LABEL {
      bigserial id PK
      bigint data_file_id FK
      bigint label_id FK
      timestamptz create_time
      timestamptz update_time
      UNIQUE(data_file_id, label_id)
    }

    OPERATION_LOG {
      bigserial id PK
      text username
      text action
      bigint data_file_id FK
      text content
      timestamptz create_time
      timestamptz update_time
    }
```

---

是否希望我帮你基于这个结构生成 **PostgreSQL 的建表 SQL 脚本**（包含所有约束、索引和触发器）？
可以一键复制执行到数据库中。
