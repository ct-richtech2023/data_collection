from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# 优先读取环境变量 DATABASE_URL；未设置时使用本机 Docker 的默认连接
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:richtech@127.0.0.1:5432/filesvc")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
