# 安装依赖
pip install -r requirements.txt

# 数据库迁移（首次运行或模型更新后）
# 1. 生成迁移文件（当模型有变化时）
alembic revision --autogenerate -m "描述你的更改"

# 2. 应用迁移到数据库
alembic upgrade head

# 3. 查看当前迁移状态
alembic current

# 启动应用
uvicorn app.main:app --reload --host 0.0.0.0 --port 9000
