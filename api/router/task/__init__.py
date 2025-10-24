from fastapi import APIRouter
from .task import router as task_router

router = APIRouter(
    prefix="/task",
    tags=["task"]
)

# 包含子路由
router.include_router(task_router)
