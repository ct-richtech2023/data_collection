from fastapi import APIRouter
from .label import router as label_router

router = APIRouter(
    prefix="/label",
    tags=["label"]
)

# 包含子路由
router.include_router(label_router)
