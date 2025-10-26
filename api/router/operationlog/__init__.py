from fastapi import APIRouter
from .operationlog import router as operationlog_router

router = APIRouter(prefix="/operationlog", tags=["operationlog"])

# 包含子路由
router.include_router(operationlog_router)
