from fastapi import APIRouter

from .user import router as user_router

router = APIRouter(
    prefix="/user"
)

# 包含子路由
router.include_router(user_router)
