# 安装依赖
pip install -r requirements.txt

# 数据库迁移（首次运行或模型更新后）
# 1. 生成迁移文件（当模型有变化时）
alembic revision --autogenerate -m "描述你的更改"

# 2. 应用迁移到数据库
alembic upgrade head

# 3. 查看当前迁移状态
alembic current

# 4. 查看数据库表列表（验证迁移结果）
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

# 启动应用
cd api && python3 app.py

# 或者使用uvicorn启动
cd api && uvicorn app:app --reload --host 0.0.0.0 --port 9000
