from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from common.database import get_db
from common import models, schemas
from router.user.auth import get_current_user
from loguru import logger

router = APIRouter()


@router.post("/create_device", response_model=schemas.DeviceOut)
def create_device(
    device: schemas.DeviceCreate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """创建设备 - 只有管理员可以创建设备"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[Device][Create] 请求 | user_id={getattr(current_user, 'id', None)} name={device.name} sn={device.sn}")
    
    # 权限检查：只有管理员可以创建设备
    if not current_user.is_admin():
        logger.warning(f"[Device][Create] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以创建设备"
        )
    
    # 检查设备序列号是否已存在
    existing_device = db.query(models.Device).filter(models.Device.sn == device.sn).first()
    if existing_device:
        logger.warning(f"[Device][Create] 已存在相同SN | sn={device.sn}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="设备序列号已存在"
        )
    
    # 创建设备
    db_device = models.Device(
        name=device.name,
        sn=device.sn,
        description=device.description
    )
    db.add(db_device)
    db.commit()
    db.refresh(db_device)
    logger.info(f"[Device][Create] 成功 | device_id={db_device.id}")
    return db_device


@router.get("/get_all_devices", response_model=List[schemas.DeviceOut])
def get_all_devices(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取所有设备列表 - 只有管理员可以查看所有设备"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[Device][ListAll] 请求 | user_id={current_user.id}")
    
    # 权限检查：只有管理员可以查看所有设备
    if not current_user.is_admin():
        logger.warning(f"[Device][ListAll] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看所有设备"
        )
    
    devices = db.query(models.Device).order_by(models.Device.id.asc()).all()
    logger.info(f"[Device][ListAll] 成功 | count={len(devices)}")
    return devices


@router.get("/get_device_by_id", response_model=schemas.DeviceOut)
def get_device_by_id(
    device_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """根据ID获取设备信息 - 只有管理员可以查看设备信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[Device][GetById] 请求 | user_id={current_user.id} device_id={device_id}")
    
    # 权限检查：只有管理员可以查看设备信息
    if not current_user.is_admin():
        logger.warning(f"[Device][GetById] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看设备信息"
        )
    
    device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not device:
        logger.warning(f"[Device][GetById] 未找到 | device_id={device_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在"
        )
    logger.info(f"[Device][GetById] 成功 | device_id={device.id}")
    return device


@router.post("/update_device", response_model=schemas.DeviceOut)
def update_device(
    device_update: schemas.DeviceUpdate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """更新设备信息 - 只有管理员可以更新设备信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[Device][Update] 请求 | user_id={current_user.id} payload={device_update.model_dump(exclude_none=True)}")
    
    # 权限检查：只有管理员可以更新设备信息
    if not current_user.is_admin():
        logger.warning(f"[Device][Update] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以更新设备信息"
        )
    
    # 从device_update中获取设备ID
    device_id = device_update.id
    
    # 查找设备
    device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not device:
        logger.warning(f"[Device][Update] 未找到 | device_id={device_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在"
        )
    
    # 更新设备信息 - 只更新提供的字段
    update_data = device_update.model_dump(exclude_unset=True)
    
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
                detail="设备名称长度必须在1-255个字符之间"
            )
    
    if "sn" in update_data and update_data["sn"] is not None:
        if len(update_data["sn"]) < 1 or len(update_data["sn"]) > 255:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="设备序列号长度必须在1-255个字符之间"
            )
        # 检查序列号是否已被其他设备使用
        existing_device = db.query(models.Device).filter(
            models.Device.sn == update_data["sn"],
            models.Device.id != device_id
        ).first()
        if existing_device:
            logger.warning(f"[Device][Update] SN 冲突 | device_id={device_id} sn={update_data['sn']}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="设备序列号已被其他设备使用"
            )
    
    if "description" in update_data and update_data["description"] is not None:
        if len(update_data["description"]) > 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="设备描述长度不能超过1000个字符"
            )
    
    # 更新字段 - 只更新非None的字段
    for field, value in update_data.items():
        if value is not None:
            setattr(device, field, value)
    
    db.commit()
    db.refresh(device)
    logger.info(f"[Device][Update] 成功 | device_id={device.id}")
    return device


@router.post("/delete_device")
def delete_device(
    device_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """删除设备 - 只有管理员可以删除设备"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[Device][Delete] 请求 | user_id={current_user.id} device_id={device_id}")
    
    # 权限检查：只有管理员可以删除设备
    if not current_user.is_admin():
        logger.warning(f"[Device][Delete] 拒绝 | 非管理员 user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除设备"
        )
    
    # 查找设备
    device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not device:
        logger.warning(f"[Device][Delete] 未找到 | device_id={device_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在"
        )
    
    # 检查是否有数据文件关联此设备
    data_files_count = db.query(models.DataFile).filter(models.DataFile.device_id == device_id).count()
    if data_files_count > 0:
        logger.warning(f"[Device][Delete] 关联数据文件阻止删除 | device_id={device_id} count={data_files_count}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法删除设备，该设备关联了 {data_files_count} 个数据文件"
        )
    
    # 检查是否有用户权限关联此设备
    permissions_count = db.query(models.UserDevicePermission).filter(models.UserDevicePermission.device_id == device_id).count()
    if permissions_count > 0:
        logger.warning(f"[Device][Delete] 关联用户权限阻止删除 | device_id={device_id} count={permissions_count}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无法删除设备，该设备关联了 {permissions_count} 个用户权限"
        )
    
    db.delete(device)
    db.commit()
    logger.info(f"[Device][Delete] 成功 | device_id={device_id}")
    return {"message": f"设备 {device.name} 已成功删除"}


@router.post("/get_devices_with_pagination")
def get_devices_with_pagination(
    request_data: schemas.DeviceQuery,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取设备列表，支持分页和按ID查询 - 根据用户权限过滤设备"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    logger.info(f"[Device][Page] 请求 | user_id={current_user.id} filters={{'device_id': { 'set' if bool(getattr(request_data, 'device_id', None)) else 'unset' }, 'name': { 'set' if bool(getattr(request_data, 'name', None)) else 'unset' }, 'sn': { 'set' if bool(getattr(request_data, 'sn', None)) else 'unset' }}}")
    
    # 权限检查：根据用户设备权限过滤查询结果
    # 管理员可以查看所有设备，普通用户只能查看有权限的设备
    
    try:
        # 构建查询
        query = db.query(models.Device)
        
        # 根据用户权限过滤设备
        if not current_user.is_admin():
            # 非管理员用户：只显示有权限的设备
            from common.permission_utils import PermissionUtils
            user_device_permissions = PermissionUtils.get_user_device_permissions(db, current_user.id)
            if user_device_permissions:
                query = query.filter(models.Device.id.in_(user_device_permissions))
            else:
                # 如果用户没有任何设备权限，返回空结果
                query = query.filter(False)
        
        # 如果指定了设备ID，则只查询该设备
        if request_data.device_id:
            query = query.filter(models.Device.id == request_data.device_id)
        
        # 如果指定了设备名称，则进行模糊查询
        if request_data.name:
            query = query.filter(models.Device.name.ilike(f"%{request_data.name}%"))
        
        # 如果指定了设备SN，则进行模糊查询
        if request_data.sn:
            query = query.filter(models.Device.sn.ilike(f"%{request_data.sn}%"))
        
        # 获取总数（用于分页信息）
        total_count = query.count()
        logger.info(f"[Device][Page] 查询完成 | total_count={total_count}")
        
        # 按ID正序排列
        query = query.order_by(models.Device.id.asc())
        
        # 应用分页
        offset = (request_data.page - 1) * request_data.page_size
        devices = query.offset(offset).limit(request_data.page_size).all()
        logger.info(f"[Device][Page] 分页 | page={request_data.page} size={request_data.page_size} page_count={len(devices)}")
        
        # 构建响应数据
        result = []
        for device in devices:
            # 获取设备关联的数据文件数量
            data_files_count = db.query(models.DataFile).filter(models.DataFile.device_id == device.id).count()
            
            # 获取设备关联的用户权限数量
            user_permissions_count = db.query(models.UserDevicePermission).filter(models.UserDevicePermission.device_id == device.id).count()
            
            device_data = {
                "id": device.id,
                "name": device.name,
                "sn": device.sn,
                "description": device.description,
                "create_time": device.create_time,
                "update_time": device.update_time,
                "data_files_count": data_files_count,
                "user_permissions_count": user_permissions_count
            }
            
            result.append(device_data)
        
        # 计算分页信息
        total_pages = (total_count + request_data.page_size - 1) // request_data.page_size
        
        return {
            "devices": result,
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
        logger.exception(f"[Device][Page] 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取设备信息时发生错误: {str(e)}"
        )
