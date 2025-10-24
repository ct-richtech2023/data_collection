from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from common.database import get_db
from common import models, schemas
from router.user.auth import get_current_user

router = APIRouter()


@router.post("/create_label", response_model=schemas.LabelOut)
def create_label(
    label: schemas.LabelCreate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """创建标签 - 只有管理员可以创建标签"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以创建标签
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以创建标签"
        )
    
    # 检查标签名称是否已存在
    existing_label = db.query(models.Label).filter(models.Label.name == label.name).first()
    if existing_label:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="标签名称已存在"
        )
    
    # 创建标签
    db_label = models.Label(
        name=label.name
    )
    db.add(db_label)
    db.commit()
    db.refresh(db_label)
    return db_label


@router.get("/get_all_labels", response_model=List[schemas.LabelOut])
def get_all_labels(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取所有标签列表 - 只有管理员可以查看所有标签"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看所有标签
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看所有标签"
        )
    
    labels = db.query(models.Label).order_by(models.Label.id.asc()).all()
    return labels


@router.get("/get_label_by_id", response_model=schemas.LabelOut)
def get_label_by_id(
    label_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """根据ID获取标签信息 - 只有管理员可以查看标签信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看标签信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看标签信息"
        )
    
    label = db.query(models.Label).filter(models.Label.id == label_id).first()
    if not label:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="标签不存在"
        )
    return label


@router.post("/update_label", response_model=schemas.LabelOut)
def update_label(
    label_update: schemas.LabelUpdate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """更新标签信息 - 只有管理员可以更新标签信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以更新标签信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以更新标签信息"
        )
    
    # 从label_update中获取标签ID
    label_id = label_update.id
    
    # 查找标签
    label = db.query(models.Label).filter(models.Label.id == label_id).first()
    if not label:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="标签不存在"
        )
    
    # 更新标签信息 - 只更新提供的字段
    update_data = label_update.model_dump(exclude_unset=True)
    
    # 移除id字段，因为id不应该被更新
    update_data.pop("id", None)
    
    # 处理空字符串，将空字符串转换为None（表示不更新）
    for field, value in update_data.items():
        if value == "":
            update_data[field] = None
    
    # 验证字段值
    if "name" in update_data and update_data["name"] is not None:
        if len(update_data["name"]) < 1 or len(update_data["name"]) > 255:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="标签名称长度必须在1-255个字符之间"
            )
        
        # 检查标签名称是否已被其他标签使用
        existing_label = db.query(models.Label).filter(
            models.Label.name == update_data["name"],
            models.Label.id != label_id
        ).first()
        if existing_label:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="标签名称已被其他标签使用"
            )
    
    # 更新字段 - 只更新非None的字段
    for field, value in update_data.items():
        if value is not None:
            setattr(label, field, value)
    
    db.commit()
    db.refresh(label)
    return label


@router.post("/delete_label")
def delete_label(
    label_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """删除标签 - 只有管理员可以删除标签"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以删除标签
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除标签"
        )
    
    # 查找标签
    label = db.query(models.Label).filter(models.Label.id == label_id).first()
    if not label:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="标签不存在"
        )
    
    # 检查是否有数据文件标签映射关联此标签
    data_file_labels_count = db.query(models.DataFileLabel).filter(models.DataFileLabel.label_id == label_id).count()
    if data_file_labels_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法删除标签，该标签关联了 {data_file_labels_count} 个数据文件标签映射"
        )
    
    db.delete(label)
    db.commit()
    return {"message": f"标签 {label.name} 已成功删除"}


@router.post("/get_labels_with_pagination")
def get_labels_with_pagination(
    request_data: schemas.LabelQuery,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取标签列表，支持分页和按ID查询 - 只有管理员可以查看"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看标签信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看标签信息"
        )
    
    try:
        # 构建查询
        query = db.query(models.Label)
        
        # 如果指定了标签ID，则只查询该标签
        if request_data.label_id:
            query = query.filter(models.Label.id == request_data.label_id)
        
        # 获取总数（用于分页信息）
        total_count = query.count()
        
        # 按ID正序排列
        query = query.order_by(models.Label.id.asc())
        
        # 应用分页
        offset = (request_data.page - 1) * request_data.page_size
        labels = query.offset(offset).limit(request_data.page_size).all()
        
        # 构建响应数据
        result = []
        for label in labels:
            # 获取标签关联的数据文件标签映射数量
            data_file_labels_count = db.query(models.DataFileLabel).filter(models.DataFileLabel.label_id == label.id).count()
            
            label_data = {
                "id": label.id,
                "name": label.name,
                "create_time": label.create_time,
                "update_time": label.update_time,
                "data_file_labels_count": data_file_labels_count
            }
            
            result.append(label_data)
        
        # 计算分页信息
        total_pages = (total_count + request_data.page_size - 1) // request_data.page_size
        
        return {
            "labels": result,
            "pagination": {
                "current_page": request_data.page,
                "page_size": request_data.page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": request_data.page < total_pages,
                "has_prev": request_data.page > 1
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取标签信息时发生错误: {str(e)}"
        )
