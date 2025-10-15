from fastapi import APIRouter
from .operation import router as operation_router

router = APIRouter(
    prefix="/operation",
    tags=["operation"]
)

router.include_router(operation_router)
