# Swagger UI 中使用 Token 认证指南

## 🚀 如何在 Swagger UI 中添加和使用 Token

### 1. 访问 Swagger UI
打开浏览器访问：`http://localhost:9000/`

### 2. 获取 Token

#### 方法一：使用默认Token（推荐用于测试）
- **默认Token**: `richtech`
- 这个token具有管理员权限，可以直接使用

#### 方法二：通过登录获取Token
1. 使用 **认证** 标签下的 `/auth/login` 端点
2. 输入用户名和密码（例如：`admin` / `admin123`）
3. 点击 "Execute" 执行请求
4. 在响应中复制 `access_token` 的值

### 3. 设置 Token
1. 在需要认证的API端点中，找到 `token` 参数字段
2. 直接输入你的token值：
   - 默认token：`richtech`
   - 或从登录获取的JWT token
3. 点击 "Execute" 执行请求

### 4. 使用受保护的端点
现在你可以：
- 使用 **用户管理** 标签下的所有端点
- 在需要认证的端点中直接输入token
- 所有用户管理操作都需要管理员权限

### 4.1 修改用户信息 - 部分更新
修改用户信息支持部分更新，**不填写的字段不会修改**：

- **只修改密码**：只提供 `password` 字段
- **只修改权限**：只提供 `permission_level` 字段  
- **只修改扩展信息**：只提供 `extra` 字段
- **同时修改多个字段**：提供需要修改的字段组合

**注意**：密码会自动加密处理，其他字段保持原值不变

### 5. 权限说明
- **管理员 (admin)**: 可以查看、修改和删除所有用户信息
- **上传者 (uploader)**: 可以上传和管理自己的数据
- **查看者 (viewer)**: 只能查看数据

### 6. 测试用户和Token
- **默认Token**: `richtech` (管理员权限，推荐用于测试)
- **管理员**: 用户名 `admin`，密码 `admin123`
- **上传者**: 用户名 `uploader`，密码 `uploader123`
- **查看者**: 用户名 `viewer`，密码 `viewer123`

### 7. 常见问题
- **401 Unauthorized**: Token 无效或已过期，请重新登录获取新 token
- **403 Forbidden**: 权限不足，请使用管理员账户或检查你的权限级别
- **Token 格式错误**: 确保输入的是完整的 token 值，不要包含 "Bearer " 前缀

## 📝 示例

### 使用默认Token（推荐）
```
Token: richtech
```

### 使用JWT Token
```
Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTc2MDQxNDc3NX0.5ovFrtL6tzxt_gs_Ojkd_WIzrUs-XnUg5mXEeJlOn58
```

### 快速测试命令

#### 使用默认Token（管理员权限）
```bash
# 获取所有用户
curl -X GET "http://localhost:9000/users" -H "token: richtech"

# 获取特定用户
curl -X GET "http://localhost:9000/users/1" -H "token: richtech"
```

#### 权限测试示例
```bash
# 1. 登录获取uploader用户的token
curl -X POST "http://localhost:9000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "uploader", "password": "uploader123"}'

# 2. 使用uploader token访问所有用户（应该被拒绝）
curl -X GET "http://localhost:9000/users" -H "token: <uploader_token>"

# 3. 使用uploader token访问特定用户信息（应该被拒绝）
curl -X GET "http://localhost:9000/users/4" -H "token: <uploader_token>"

# 4. 登录获取viewer用户的token
curl -X POST "http://localhost:9000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "viewer", "password": "viewer123"}'

# 5. 使用viewer token访问特定用户信息（应该被拒绝）
curl -X GET "http://localhost:9000/users/5" -H "token: <viewer_token>"

# 6. 使用管理员token访问用户信息（应该成功）
curl -X GET "http://localhost:9000/users" -H "token: richtech"
curl -X GET "http://localhost:9000/users/4" -H "token: richtech"

# 7. 使用管理员token修改用户信息（应该成功）
# 只修改权限级别
curl -X PUT "http://localhost:9000/users/4" \
  -H "Content-Type: application/json" \
  -H "token: richtech" \
  -d '{"permission_level": "admin"}'

# 只修改密码
curl -X PUT "http://localhost:9000/users/4" \
  -H "Content-Type: application/json" \
  -H "token: richtech" \
  -d '{"password": "newpassword123"}'

# 只修改扩展信息
curl -X PUT "http://localhost:9000/users/4" \
  -H "Content-Type: application/json" \
  -H "token: richtech" \
  -d '{"extra": {"department": "IT", "location": "Shanghai"}}'

# 同时修改多个字段
curl -X PUT "http://localhost:9000/users/4" \
  -H "Content-Type: application/json" \
  -H "token: richtech" \
  -d '{"permission_level": "uploader", "extra": {"department": "IT"}}'

# 8. 使用管理员token删除用户（应该成功）
curl -X DELETE "http://localhost:9000/users/1" -H "token: richtech"

# 9. 使用非管理员token尝试修改用户信息（应该被拒绝）
curl -X PUT "http://localhost:9000/users/5" \
  -H "Content-Type: application/json" \
  -H "token: <viewer_token>" \
  -d '{"permission_level": "admin"}'
```
