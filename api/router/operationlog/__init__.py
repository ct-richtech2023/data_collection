from fastapi import APIRouter
from .operationlog import router

router = APIRouter(prefix="/operationlog", tags=["操作日志管理"])
