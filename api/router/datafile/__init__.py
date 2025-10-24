from fastapi import APIRouter
from .datafile import router as datafile_router

router = APIRouter(
    prefix="/datafile",
    tags=["datafile"]
)

# 包含子路由
router.include_router(datafile_router)
