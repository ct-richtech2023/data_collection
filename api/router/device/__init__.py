from fastapi import APIRouter
from .device import router as device_router

router = APIRouter(
    prefix="/device",
    tags=["device"]
)

# 包含子路由
router.include_router(device_router)
