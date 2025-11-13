from fastapi import APIRouter
from .zipdatafile import router as zipdatafile_router

router = APIRouter(
    prefix="/zipdatafile",
    tags=["zipdatafile"]
)

# 包含子路由
router.include_router(zipdatafile_router)  
