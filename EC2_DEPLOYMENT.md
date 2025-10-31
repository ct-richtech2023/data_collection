# Amazon EC2 部署指南（systemd 方式）

本指南专门针对 Amazon EC2 服务器，使用 systemd 服务管理后台运行。PostgreSQL 运行在 Docker 容器中，miniconda 安装在 `/home/ec2-user`。

## 环境信息

- **项目路径**: `/home/ec2-user/data_collection`
- **用户**: `ec2-user`
- **conda 路径**: `/home/ec2-user/miniconda3/envs/data_collection/bin`
- **数据库**: PostgreSQL (Docker 容器)
- **服务端口**: `9000`

---

## 快速开始

### 第一步：确保 Docker PostgreSQL 运行

```bash
# 检查 PostgreSQL 容器是否运行
docker ps | grep postgres

# 如果没有运行，启动 PostgreSQL 容器（根据你的实际配置）
# docker start <postgres容器名>
```

### 第二步：安装并启动 systemd 服务

```bash
cd /home/ec2-user/data_collection

# 给脚本执行权限
chmod +x start_service.sh

# 安装并启动服务（首次，只需一次）
bash start_service.sh install
bash start_service.sh start
```

### 第三步：验证服务状态

```bash
# 查看服务状态
bash start_service.sh status

# 或使用 systemctl
sudo systemctl status data-collection
```

---

## 常用命令

| 操作 | 命令 |
|------|------|
| **启动** | `bash start_service.sh start` |
| **停止** | `bash start_service.sh stop` |
| **重启** | `bash start_service.sh restart` |
| **查看状态** | `bash start_service.sh status` |
| **查看日志** | `bash start_service.sh logs` |
| **卸载服务** | `bash start_service.sh uninstall` |

### 或使用 systemctl 命令

```bash
sudo systemctl start data-collection   # 启动
sudo systemctl stop data-collection     # 停止
sudo systemctl restart data-collection  # 重启
sudo systemctl status data-collection   # 状态
sudo journalctl -u data-collection -f   # 日志
```

---

## 快速验证

### 1. 检查服务状态

```bash
bash start_service.sh status
# 或
sudo systemctl status data-collection
```

### 2. 检查端口监听

```bash
lsof -i:9000
```

### 3. 测试 API

```bash
curl http://localhost:9000/docs
# 或浏览器访问: http://your-ec2-ip:9000/docs
```

---

## 常见问题快速解决

### 问题1：端口被占用

```bash
# 停止占用端口的进程
lsof -ti:9000 | xargs kill -9

# 或停止服务后重新启动
bash start_service.sh stop
bash start_service.sh start
```

### 问题2：日志目录权限

```bash
sudo mkdir -p /var/log/data_collection
sudo chown -R ec2-user:ec2-user /var/log/data_collection
sudo chmod 750 /var/log/data_collection
```

### 问题3：PostgreSQL 连接失败

```bash
# 检查 Docker 容器是否运行
docker ps | grep postgres

# 如果容器未运行，启动它
# docker start <postgres容器名>
```

### 问题4：服务启动失败

```bash
# 查看详细日志
sudo journalctl -u data-collection -n 100 --no-pager

# 或使用脚本查看
bash start_service.sh logs
```

### 问题5：服务无法开机自启

```bash
# 确保服务已启用
sudo systemctl enable data-collection

# 检查是否已启用
sudo systemctl is-enabled data-collection
```

---

## 配置文件说明

所有配置都已针对 EC2 环境优化：

- **项目路径**: `/home/ec2-user/data_collection`
- **conda 路径**: `/home/ec2-user/miniconda3/envs/data_collection/bin`
- **数据库连接**: `postgresql://postgres:richtech@127.0.0.1:5432/filesvc`
- **日志目录**: `/var/log/data_collection`
- **Workers**: `4`（可在 `data-collection.service` 中修改）

### 修改配置后重启

```bash
# 编辑 data-collection.service 后
bash start_service.sh install
sudo systemctl daemon-reload
sudo systemctl restart data-collection
```

---

## 服务特性

✅ **开机自动启动** - 服务器重启后服务自动启动  
✅ **自动重启** - 服务崩溃后自动重启  
✅ **系统级管理** - 使用 systemctl 统一管理  
✅ **日志管理** - 使用 journalctl 查看系统日志  

---

**提示**: 这是生产环境推荐的方式，服务会随系统启动自动运行。

