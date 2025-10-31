from fastapi import APIRouter, Depends, HTTPException, status, Header, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
import os
import uuid
import zipfile
import tempfile
import shutil
from datetime import datetime
from mcap.reader import make_reader
import io
import boto3
from botocore.config import Config as BotoConfig
from urllib.parse import urlparse
import yaml
from common.database import get_db
from common import models, schemas
from common.permission_utils import PermissionUtils
from common.mcap_loader import McapReader
from router.user.auth import get_current_user
from loguru import logger

router = APIRouter()

# 配置上传目录
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# S3 配置（支持 /etc/data_collection/s3.yaml 与环境变量，环境变量优先）
S3_CONFIG_FILE = "/etc/data_collection/s3.yaml"
_S3_CFG = {}
try:
    if os.path.exists(S3_CONFIG_FILE):
        with open(S3_CONFIG_FILE, 'r') as f:
            _S3_CFG = yaml.safe_load(f) or {}
except Exception as _e:
    # 配置文件读取失败不阻断启动，后续仍可用环境变量
    print(f"读取 {S3_CONFIG_FILE} 失败: {_e}")

def _cfg(name: str, default=None):
    return os.getenv(name, _S3_CFG.get(name, default))

S3_REGION_NAME = _cfg("S3_REGION_NAME", "us-east-1")
S3_BUCKET_NAME = _cfg("S3_BUCKET_NAME", None)
S3_ACCESS_KEY = _cfg("S3_ACCESS_KEY_ID", None)
S3_SECRET_KEY = _cfg("S3_SECRET_ACCESS_KEY", None)


def get_s3_client():
    if not S3_BUCKET_NAME:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="未配置 S3_BUCKET_NAME")
    if not (S3_ACCESS_KEY and S3_SECRET_KEY):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="未配置 S3 访问密钥")
    return boto3.client(
        "s3",
        region_name=S3_REGION_NAME,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY
    )


def build_s3_url(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def parse_s3_url(s3_url: str):
    # 支持 s3://bucket/key 形式
    parsed = urlparse(s3_url)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("无效的 S3 URL")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


@router.get("/s3_health")
def s3_health(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """S3 健康检查：验证客户端初始化与桶可访问性（head_bucket）。"""
    # 验证token
    current_user = get_current_user(token, db)
    try:
        logger.info(f"[S3] 健康检查开始 | bucket={S3_BUCKET_NAME} region={S3_REGION_NAME}")
        s3 = get_s3_client()
        # 校验桶是否可访问（需要对桶有 head 权限）
        s3.head_bucket(Bucket=S3_BUCKET_NAME)
        result = {
            "ok": True,
            "bucket": S3_BUCKET_NAME,
            "region": S3_REGION_NAME
        }
        logger.info(f"[S3] 健康检查成功 | {result}")
        return result
    except Exception as e:
        logger.exception(f"[S3] 健康检查失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"S3连接失败: {str(e)}"
        )


@router.post("/upload_mcap", response_model=schemas.DataFileOut)
async def upload_mcap_file(
    task_id: int = Form(..., description="任务ID"),
    device_id: int = Form(..., description="设备ID"),
    label_ids: str = Form(default="", description="标签ID列表，用逗号分隔，如：1,2,3"),
    file: UploadFile = File(..., description="MCAP文件"),
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """上传MCAP文件 - 需要设备权限和上传操作权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：检查设备权限
    if not PermissionUtils.check_device_permission(db, current_user.id, device_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有该设备的访问权限"
        )
    
    # 权限检查：检查上传操作权限
    if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "upload"):
               raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有文件上传权限"
        )
    
    # 验证文件类型
    if not file.filename.endswith('.mcap'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只支持上传.mcap文件"
        )
    
    # 验证任务是否存在
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在"
        )
    
    # 验证设备是否存在
    device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在"
        )
    
    # 解析标签ID列表
    label_id_list = []
    if label_ids.strip():
        try:
            label_id_list = [int(x.strip()) for x in label_ids.split(',') if x.strip()]
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="标签ID格式错误，请使用逗号分隔的整数，如：1,2,3"
            )
    
    # 验证标签是否存在
    if label_id_list:
        existing_labels = db.query(models.Label).filter(models.Label.id.in_(label_id_list)).all()
        existing_label_ids = [label.id for label in existing_labels]
        missing_label_ids = set(label_id_list) - set(existing_label_ids)
        if missing_label_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"以下标签不存在: {list(missing_label_ids)}"
            )
    
    try:
        # 读取文件内容
        content = await file.read()
        logger.info(f"[Upload] 收到上传请求 | task_id={task_id} device_id={device_id} user_id={current_user.id} filename={file.filename} size={len(content)}")
        
        # 生成唯一对象键
        file_extension = os.path.splitext(file.filename)[1]
        unique_key = f"datafiles/{uuid.uuid4()}{file_extension}"
        
        # 将内容写入临时文件以便解析 MCAP 时长
        temp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False)
            temp_path = tmp.name
            tmp.write(content)
            tmp.close()
            mcap_reader = McapReader(temp_path)
            file_info = mcap_reader.file_info
            duration_ms = int(file_info.duration_sec * 1000)
            mcap_reader.close()
        except Exception as e:
            print(f"解析MCAP文件信息失败: {e}")
            duration_ms = 60 * 1000
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        
        # 上传到 S3
        s3 = get_s3_client()
        s3.put_object(Bucket=S3_BUCKET_NAME, Key=unique_key, Body=content, ContentType='application/octet-stream')
        logger.info(f"[S3] 上传成功 | key={unique_key} bucket={S3_BUCKET_NAME} duration_ms={duration_ms}")
        download_url = build_s3_url(S3_BUCKET_NAME, unique_key)
        
        # 创建数据文件记录
        db_datafile = models.DataFile(
            task_id=task_id,
            file_name=file.filename,
            download_url=download_url,
            duration_ms=duration_ms,
            user_id=current_user.id,
            device_id=device_id
        )
        db.add(db_datafile)
        db.commit()
        db.refresh(db_datafile)
        
        # 创建标签关联
        if label_id_list:
            for label_id in label_id_list:
                db_datafile_label = models.DataFileLabel(
                    data_file_id=db_datafile.id,
                    label_id=label_id
                )
                db.add(db_datafile_label)
            db.commit()
        
        # 创建文件上传操作日志
        from common.operation_log_util import OperationLogUtil
        OperationLogUtil.log_file_upload(
            db, current_user.username, file.filename, db_datafile.id, task_id, device_id
        )
        
        logger.info(f"[Upload] 数据库记录创建成功 | data_file_id={db_datafile.id}")
        return db_datafile
        
    except Exception as e:
        logger.exception(f"[Upload] 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传文件时发生错误: {str(e)}"
        )


@router.post("/upload_zip", response_model=List[schemas.DataFileOut])
async def upload_zip_file(
    task_id: int = Form(..., description="任务ID"),
    device_id: int = Form(..., description="设备ID"),
    label_ids: str = Form(default="", description="标签ID列表，用逗号分隔，如：1,2,3"),
    file: UploadFile = File(..., description="ZIP文件，包含一个或多个MCAP文件"),
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """上传ZIP文件 - 解析ZIP中的MCAP文件（单个或多个） - 需要设备权限和上传操作权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：检查设备权限
    if not PermissionUtils.check_device_permission(db, current_user.id, device_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有该设备的访问权限"
        )
    
    # 权限检查：检查上传操作权限
    if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有文件上传权限"
        )
    
    # 验证文件类型
    if not file.filename.endswith('.zip'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只支持上传.zip文件"
        )
    
    # 验证任务是否存在
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在"
        )
    
    # 验证设备是否存在
    device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在"
        )
    
    # 解析标签ID列表
    label_id_list = []
    if label_ids.strip():
        try:
            label_id_list = [int(x.strip()) for x in label_ids.split(',') if x.strip()]
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="标签ID格式错误，请使用逗号分隔的整数，如：1,2,3"
            )
    
    # 验证标签是否存在
    if label_id_list:
        existing_labels = db.query(models.Label).filter(models.Label.id.in_(label_id_list)).all()
        existing_label_ids = [label.id for label in existing_labels]
        missing_label_ids = set(label_id_list) - set(existing_label_ids)
        if missing_label_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"以下标签不存在: {list(missing_label_ids)}"
            )
    
    try:
        # 读取ZIP文件内容
        zip_content = await file.read()
        logger.info(f"[Upload ZIP] 收到上传请求 | task_id={task_id} device_id={device_id} user_id={current_user.id} filename={file.filename} size={len(zip_content)}")
        
        # 创建临时ZIP文件
        temp_zip_path = None
        temp_extract_dir = None
        created_files = []
        
        try:
            # 保存ZIP到临时文件
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_zip:
                temp_zip_path = tmp_zip.name
                tmp_zip.write(zip_content)
            
            # 创建临时解压目录
            temp_extract_dir = tempfile.mkdtemp()
            
            # 解压ZIP文件
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_dir)
                file_list = zip_ref.namelist()
            
            # 查找所有.mcap文件
            mcap_files = []
            for file_name in file_list:
                if file_name.endswith('.mcap'):
                    # 获取完整路径
                    full_path = os.path.join(temp_extract_dir, file_name)
                    if os.path.isfile(full_path):
                        mcap_files.append((file_name, full_path))
            
            if not mcap_files:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ZIP文件中未找到.mcap文件"
                )
            
            logger.info(f"[Upload ZIP] 找到 {len(mcap_files)} 个MCAP文件")
            
            # 获取S3客户端
            s3 = get_s3_client()
            
            # 处理每个MCAP文件
            for mcap_filename, mcap_path in mcap_files:
                try:
                    # 读取MCAP文件内容
                    with open(mcap_path, 'rb') as f:
                        mcap_content = f.read()
                    
                    # 解析MCAP文件时长
                    duration_ms = 60 * 1000  # 默认值
                    try:
                        mcap_reader = McapReader(mcap_path)
                        file_info = mcap_reader.file_info
                        duration_ms = int(file_info.duration_sec * 1000)
                        mcap_reader.close()
                    except Exception as e:
                        logger.warning(f"[Upload ZIP] 解析MCAP文件信息失败: {mcap_filename}, 错误: {e}")
                        duration_ms = 60 * 1000
                    
                    # 生成唯一对象键（使用原始文件名但添加UUID前缀避免冲突）
                    base_name = os.path.basename(mcap_filename)
                    unique_key = f"datafiles/{uuid.uuid4()}_{base_name}"
                    
                    # 上传到S3
                    s3.put_object(
                        Bucket=S3_BUCKET_NAME,
                        Key=unique_key,
                        Body=mcap_content,
                        ContentType='application/octet-stream'
                    )
                    logger.info(f"[S3] 上传成功 | key={unique_key} bucket={S3_BUCKET_NAME} duration_ms={duration_ms}")
                    download_url = build_s3_url(S3_BUCKET_NAME, unique_key)
                    
                    # 创建数据文件记录
                    db_datafile = models.DataFile(
                        task_id=task_id,
                        file_name=base_name,  # 使用原始文件名
                        download_url=download_url,
                        duration_ms=duration_ms,
                        user_id=current_user.id,
                        device_id=device_id
                    )
                    db.add(db_datafile)
                    db.flush()  # 获取ID但不提交
                    
                    # 创建标签关联
                    if label_id_list:
                        for label_id in label_id_list:
                            db_datafile_label = models.DataFileLabel(
                                data_file_id=db_datafile.id,
                                label_id=label_id
                            )
                            db.add(db_datafile_label)
                    
                    # 创建文件上传操作日志
                    from common.operation_log_util import OperationLogUtil
                    OperationLogUtil.log_file_upload(
                        db, current_user.username, base_name, db_datafile.id, task_id, device_id
                    )
                    
                    created_files.append(db_datafile)
                    logger.info(f"[Upload ZIP] MCAP文件处理成功 | data_file_id={db_datafile.id} filename={base_name}")
                    
                except Exception as e:
                    logger.exception(f"[Upload ZIP] 处理MCAP文件失败: {mcap_filename}, 错误: {e}")
                    # 继续处理下一个文件，不中断整个流程
                    continue
            
            # 提交所有更改
            db.commit()
            
            # 刷新所有对象以获取完整数据
            for db_datafile in created_files:
                db.refresh(db_datafile)
            
            if not created_files:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="所有MCAP文件处理失败"
                )
            
            logger.info(f"[Upload ZIP] 批量上传完成 | 成功: {len(created_files)}/{len(mcap_files)}")
            return created_files
            
        finally:
            # 清理临时文件
            if temp_zip_path and os.path.exists(temp_zip_path):
                try:
                    os.remove(temp_zip_path)
                except Exception:
                    pass
            
            if temp_extract_dir and os.path.exists(temp_extract_dir):
                try:
                    shutil.rmtree(temp_extract_dir)
                except Exception:
                    pass
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Upload ZIP] 失败: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传ZIP文件时发生错误: {str(e)}"
        )


@router.get("/get_all_datafiles", response_model=List[schemas.DataFileOut])
def get_all_datafiles(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取数据文件列表 - 只返回用户有权限的设备的数据"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 只返回用户有权限的设备的数据文件（基于设备权限，管理员不受限制）
    datafiles = PermissionUtils.get_accessible_datafiles_query(db, current_user.id).order_by(models.DataFile.id.asc()).all()
    return datafiles


@router.get("/get_datafile_by_id", response_model=schemas.DataFileOut)
def get_datafile_by_id(
    datafile_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """根据ID获取数据文件信息 - 基于设备权限，管理员不受限制"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    datafile = db.query(models.DataFile).filter(models.DataFile.id == datafile_id).first()
    if not datafile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据文件不存在"
        )
    
    # 权限检查：检查设备权限（管理员不受限制）
    if not PermissionUtils.check_datafile_access(db, current_user.id, datafile_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有访问该文件的权限"
        )
    
    return datafile


@router.post("/update_datafile", response_model=schemas.DataFileOut)
def update_datafile(
    datafile_update: schemas.DataFileUpdate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """更新数据文件信息 - 需要设备权限和更新操作权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：检查更新操作权限
    if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有文件更新权限"
        )
    
    # 从datafile_update中获取数据文件ID
    datafile_id = datafile_update.id
    
    # 查找数据文件
    datafile = db.query(models.DataFile).filter(models.DataFile.id == datafile_id).first()
    if not datafile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据文件不存在"
        )
    
    # 权限检查：检查设备权限
    if not PermissionUtils.check_datafile_access(db, current_user.id, datafile_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有访问该文件的权限"
        )
    
    # 更新数据文件信息 - 只更新提供的字段
    update_data = datafile_update.model_dump(exclude_unset=True)
    
    # 移除id字段，因为id不应该被更新
    update_data.pop("id", None)
    
    # 处理空字符串，将空字符串转换为None（表示不更新）
    for field, value in update_data.items():
        if value == "":
            update_data[field] = None
    
    # 验证字段值
    if "file_name" in update_data and update_data["file_name"] is not None:
        if len(update_data["file_name"]) < 1 or len(update_data["file_name"]) > 500:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文件名称长度必须在1-500个字符之间"
            )
    
    if "download_url" in update_data and update_data["download_url"] is not None:
        if len(update_data["download_url"]) < 1 or len(update_data["download_url"]) > 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="下载地址长度必须在1-1000个字符之间"
            )
    
    if "duration_ms" in update_data and update_data["duration_ms"] is not None:
        if update_data["duration_ms"] < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文件时长不能为负数"
            )
    
    # 验证任务是否存在
    if "task_id" in update_data and update_data["task_id"] is not None:
        task = db.query(models.Task).filter(models.Task.id == update_data["task_id"]).first()
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定的任务不存在"
            )
    
    # 验证设备是否存在
    if "device_id" in update_data and update_data["device_id"] is not None:
        device = db.query(models.Device).filter(models.Device.id == update_data["device_id"]).first()
        if not device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定的设备不存在"
            )
    
    # 处理标签更新
    if "label_ids" in update_data and update_data["label_ids"] is not None:
        label_ids = update_data["label_ids"]
        # 验证标签是否存在
        if label_ids:
            existing_labels = db.query(models.Label).filter(models.Label.id.in_(label_ids)).all()
            existing_label_ids = [label.id for label in existing_labels]
            missing_label_ids = set(label_ids) - set(existing_label_ids)
            if missing_label_ids:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"以下标签不存在: {list(missing_label_ids)}"
                )
        
        # 删除现有的标签关联
        db.query(models.DataFileLabel).filter(models.DataFileLabel.data_file_id == datafile_id).delete()
        
        # 创建新的标签关联
        for label_id in label_ids:
            db_datafile_label = models.DataFileLabel(
                data_file_id=datafile_id,
                label_id=label_id
            )
            db.add(db_datafile_label)
        
        # 从update_data中移除label_ids，因为已经单独处理
        update_data.pop("label_ids", None)
    
    # 更新字段 - 只更新非None的字段
    updated_fields = []
    for field, value in update_data.items():
        if value is not None:
            setattr(datafile, field, value)
            updated_fields.append(field)
    
    db.commit()
    db.refresh(datafile)
    
    # 记录文件更新日志
    if updated_fields:
        from common.operation_log_util import OperationLogUtil
        OperationLogUtil.log_file_update(
            db, current_user.username, datafile.file_name, datafile_id, updated_fields
        )
    
    return datafile


@router.post("/delete_datafile")
def delete_datafile(
    datafile_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """删除数据文件 - 需要设备权限和删除操作权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：检查删除操作权限
    if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "delete"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有文件删除权限"
        )
    
    # 查找数据文件
    datafile = db.query(models.DataFile).filter(models.DataFile.id == datafile_id).first()
    if not datafile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据文件不存在"
        )
    
    # 权限检查：检查设备权限
    if not PermissionUtils.check_datafile_access(db, current_user.id, datafile_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有访问该文件的权限"
        )
    
    # 删除关联的数据文件标签映射
    data_file_labels_count = db.query(models.DataFileLabel).filter(models.DataFileLabel.data_file_id == datafile_id).count()
    if data_file_labels_count > 0:
        # 删除所有关联的标签映射
        db.query(models.DataFileLabel).filter(models.DataFileLabel.data_file_id == datafile_id).delete()
        print(f"已删除 {data_file_labels_count} 个关联的标签映射")
    
    # 删除 S3 或本地物理文件
    try:
        logger.info(f"[Delete] 请求删除 | datafile_id={datafile_id} user_id={current_user.id}")
        if datafile.download_url.startswith("s3://"):
            bucket, key = parse_s3_url(datafile.download_url)
            s3 = get_s3_client()
            s3.delete_object(Bucket=bucket, Key=key)
            logger.info(f"[S3] 对象删除成功 | bucket={bucket} key={key}")
        else:
            file_path = datafile.download_url.replace("/uploads/", UPLOAD_DIR + "/")
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"删除物理文件失败: {e}")
    except Exception as e:
        logger.exception(f"[Delete] 存储对象删除失败: {e}")
    
    # 记录文件删除日志
    from common.operation_log_util import OperationLogUtil
    OperationLogUtil.log_file_delete(
        db, current_user.username, datafile.file_name, datafile_id
    )
    
    db.delete(datafile)
    db.commit()
    return {"message": f"数据文件 {datafile.file_name} 已成功删除"}


@router.get("/download_file/{datafile_id}")
def download_file(
    datafile_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """下载单个数据文件 - 需要设备权限和下载操作权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：检查下载操作权限
    if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "download"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有文件下载权限"
        )
    
    # 查找数据文件
    datafile = db.query(models.DataFile).filter(models.DataFile.id == datafile_id).first()
    if not datafile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据文件不存在"
        )
    
    # 权限检查：检查设备权限
    if not PermissionUtils.check_datafile_access(db, current_user.id, datafile_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有访问该文件的权限"
        )
    
    # 记录下载日志
    from common.operation_log_util import OperationLogUtil
    OperationLogUtil.log_file_download(
        db, current_user.username, 1, [datafile_id]
    )

    # 基于 S3 或本地的下载
    if datafile.download_url.startswith("s3://"):
        try:
            bucket, key = parse_s3_url(datafile.download_url)
            s3 = get_s3_client()
            obj = s3.get_object(Bucket=bucket, Key=key)
            file_size = obj.get('ContentLength')
            body = obj['Body']
            logger.info(f"[Download] S3 文件 | datafile_id={datafile_id} key={key} size={file_size}")

            def stream_body():
                chunk_size = 1024 * 1024
                while True:
                    chunk = body.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

            headers = {"Cache-Control": "no-cache"}
            if file_size is not None:
                headers["Content-Length"] = str(file_size)

            return StreamingResponse(
                stream_body(),
                media_type='application/octet-stream',
                headers={
                    **headers,
                    "Content-Disposition": f"attachment; filename={datafile.file_name}"
                }
            )
        except Exception as e:
            logger.exception(f"[Download] 从S3下载失败: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"从S3下载失败: {str(e)}")
    else:
        # 兼容本地路径（历史数据）
        if datafile.download_url.startswith("/uploads/"):
            file_path = datafile.download_url.replace("/uploads/", UPLOAD_DIR + "/")
        else:
            file_path = os.path.join(UPLOAD_DIR, os.path.basename(datafile.download_url))
        logger.info(f"[Download] 本地文件 | path={file_path} datafile_id={datafile_id}")
        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"文件不存在于服务器上: {file_path}"
            )
        file_size = os.path.getsize(file_path)
        return FileResponse(
            path=file_path,
            filename=datafile.file_name,
            media_type='application/octet-stream',
            headers={
                "Content-Length": str(file_size),
                "Cache-Control": "no-cache"
            }
        )


@router.post("/download_files_zip")
def download_files_zip(
    datafile_ids: List[int],
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """下载多个数据文件打包成ZIP - 需要设备权限和下载操作权限"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：检查下载操作权限
    if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "download"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有文件下载权限"
        )
    
    if not datafile_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请提供要下载的文件ID列表"
        )
    
    # 查找数据文件，只返回用户有权限的文件
    accessible_datafiles = PermissionUtils.get_accessible_datafiles_query(db, current_user.id).filter(
        models.DataFile.id.in_(datafile_ids)
    ).all()
    
    if not accessible_datafiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到任何您有权限访问的数据文件"
        )
    
    datafiles = accessible_datafiles
    
    logger.info(f"[ZIP] 开始处理 | files={len(datafiles)} user_id={current_user.id}")
    
    # 创建ZIP文件（内存优先，超限落盘）
    import io
    
    try:
        logger.info(f"[ZIP] 创建开始 | files={len(datafiles)}")
        
        # 使用 SpooledTemporaryFile，超过阈值自动落盘
        zip_buffer = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            s3 = get_s3_client()
            for datafile in datafiles:
                logger.info(f"[ZIP] 添加条目 | name={datafile.file_name} url={datafile.download_url}")
                try:
                    if datafile.download_url.startswith("s3://"):
                        bucket, key = parse_s3_url(datafile.download_url)
                        obj = s3.get_object(Bucket=bucket, Key=key)
                        # 流式写入 ZIP 内条目
                        with zipf.open(datafile.file_name, 'w') as dest:
                            body = obj['Body']
                            chunk_size = 1024 * 1024
                            while True:
                                chunk = body.read(chunk_size)
                                if not chunk:
                                    break
                                dest.write(chunk)
                    else:
                        # 兼容本地路径（历史数据）
                        if datafile.download_url.startswith("/uploads/"):
                            file_path = datafile.download_url.replace("/uploads/", UPLOAD_DIR + "/")
                        else:
                            file_path = os.path.join(UPLOAD_DIR, os.path.basename(datafile.download_url))
                        if os.path.exists(file_path):
                            # 本地文件用流式复制到 ZIP
                            with open(file_path, 'rb') as src, zipf.open(datafile.file_name, 'w') as dest:
                                while True:
                                    chunk = src.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    dest.write(chunk)
                        else:
                            logger.warning(f"[ZIP] 本地文件不存在，跳过 | path={file_path}")
                except Exception as e:
                    logger.exception(f"[ZIP] 添加失败，跳过 | name={datafile.file_name} err={e}")
        
        # 获取ZIP文件大小
        zip_size = zip_buffer.tell()
        logger.info(f"[ZIP] 创建完成 | size={zip_size}")
        
        if zip_size == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ZIP文件创建失败，文件大小为0"
            )
        
        # 生成ZIP文件名
        zip_filename = f"datafiles_{len(datafiles)}_files.zip"
        
        # 创建文件下载操作日志
        from common.operation_log_util import OperationLogUtil
        OperationLogUtil.log_file_download(
            db, current_user.username, len(datafiles), datafile_ids
        )
        
        # 改进的生成器函数，分块读取数据
        def generate_zip():
            zip_buffer.seek(0)  # 确保读取位置是从头开始
            chunk_size = 1024 * 1024  # 1MB chunks
            while True:
                chunk = zip_buffer.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        
        logger.info(f"[ZIP] 返回 | name={zip_filename} size={zip_size}")
        
        # 返回ZIP文件
        return StreamingResponse(
            generate_zip(),
            media_type='application/zip',
            headers={
                "Content-Disposition": f"attachment; filename={zip_filename}",
                "Content-Length": str(zip_size),
                "Cache-Control": "no-cache"
            }
        )
        
    except Exception as e:
        logger.exception(f"[ZIP] 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建ZIP文件时发生错误: {str(e)}"
        )


@router.get("/test_download")
def test_download():
    """测试下载功能 - 返回一个简单的文本文件"""
    test_content = "这是一个测试文件\n测试下载功能是否正常工作\n时间: " + str(datetime.now())
    
    # 使用内存方式返回文件
    import io
    
    def generate_text():
        yield test_content.encode('utf-8')
    
    return StreamingResponse(
        generate_text(),
        media_type='text/plain',
        headers={"Content-Disposition": "attachment; filename=test_download.txt"}
    )


@router.get("/test_zip_download")
def test_zip_download():
    """测试ZIP下载功能 - 创建一个简单的ZIP文件"""
    import io
    import zipfile
    
    # 创建测试内容
    test_content = "这是一个测试文件\n测试ZIP下载功能\n时间: " + str(datetime.now())
    
    # 创建内存中的ZIP文件
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # 添加文本文件到ZIP
        zipf.writestr("test_file.txt", test_content)
        zipf.writestr("another_file.txt", "另一个测试文件\n内容很简单")
    
    # 获取ZIP文件大小
    zip_size = zip_buffer.tell()
    print(f"测试ZIP文件大小: {zip_size} 字节")  # 调试信息
    
    # 改进的生成器函数
    def generate_zip():
        zip_buffer.seek(0)
        chunk_size = 1024 * 1024  # 1MB chunks
        while True:
            chunk = zip_buffer.read(chunk_size)
            if not chunk:
                break
            yield chunk
    
    return StreamingResponse(
        generate_zip(),
        media_type='application/zip',
        headers={
            "Content-Disposition": "attachment; filename=test_download.zip",
            "Content-Length": str(zip_size),
            "Cache-Control": "no-cache"
        }
    )


@router.post("/get_datafiles_with_pagination")
def get_datafiles_with_pagination(
    request_data: schemas.DataFileQuery,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取数据文件列表，支持分页和多条件查询 - 只返回用户有权限的设备的数据"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    try:
        # 构建查询，只查询用户有权限的设备的数据
        query = PermissionUtils.get_accessible_datafiles_query(db, current_user.id)
        
        # 如果指定了数据文件ID，则只查询该文件
        if request_data.data_file_id:
            query = query.filter(models.DataFile.id == request_data.data_file_id)
        
        # 如果指定了任务ID，则只查询该任务的文件
        if request_data.task_id:
            query = query.filter(models.DataFile.task_id == request_data.task_id)
        
        # 如果指定了用户ID，则只查询该用户的文件
        if request_data.user_id:
            query = query.filter(models.DataFile.user_id == request_data.user_id)
        
        # 如果指定了设备ID，则只查询该设备的文件
        if request_data.device_id:
            query = query.filter(models.DataFile.device_id == request_data.device_id)
        
        # 文件名称模糊查询
        if request_data.file_name:
            query = query.filter(models.DataFile.file_name.ilike(f"%{request_data.file_name}%"))
        
        # 任务名称模糊查询
        if request_data.task_name:
            query = query.join(models.Task, models.DataFile.task_id == models.Task.id)
            query = query.filter(models.Task.name.ilike(f"%{request_data.task_name}%"))
        
        # 设备名称模糊查询
        if request_data.device_name:
            # 如果已经有Task的join，需要小心处理
            if request_data.task_name:
                query = query.join(models.Device, models.DataFile.device_id == models.Device.id)
            else:
                query = query.join(models.Device, models.DataFile.device_id == models.Device.id)
            query = query.filter(models.Device.name.ilike(f"%{request_data.device_name}%"))
        
        # 标签名称模糊查询
        if request_data.label_name:
            query = query.join(models.DataFileLabel, models.DataFile.id == models.DataFileLabel.data_file_id)
            query = query.join(models.Label, models.DataFileLabel.label_id == models.Label.id)
            query = query.filter(models.Label.name.ilike(f"%{request_data.label_name}%"))
        
        # 日期筛选
        if request_data.start_date:
            # 开始日期：筛选创建日期大于等于此日期的文件（从当天00:00:00开始）
            start_datetime = datetime.combine(request_data.start_date, datetime.min.time())
            query = query.filter(models.DataFile.create_time >= start_datetime)
        
        if request_data.end_date:
            # 结束日期：筛选创建日期小于等于此日期的文件（到当天23:59:59结束）
            end_datetime = datetime.combine(request_data.end_date, datetime.max.time().replace(microsecond=0))
            query = query.filter(models.DataFile.create_time <= end_datetime)
        
        # 获取总数（用于分页信息）
        # 使用distinct()避免重复结果，特别是在使用多个JOIN时
        total_count = query.distinct().count()
        
        # 按ID正序排列
        query = query.distinct().order_by(models.DataFile.id.asc())
        
        # 应用分页
        offset = (request_data.page - 1) * request_data.page_size
        datafiles = query.offset(offset).limit(request_data.page_size).all()
        
        # 构建响应数据
        result = []
        
        # 获取所有任务，按ID排序
        all_tasks = db.query(models.Task).order_by(models.Task.id.asc()).all()
        
        # 为每个任务计算数据文件数量和总时长
        task_data = {}
        for task in all_tasks:
            # 计算该任务的数据文件数量
            datafile_count = db.query(models.DataFile).filter(models.DataFile.task_id == task.id).count()
            
            # 计算该任务的总时长（毫秒）
            total_duration = db.query(func.coalesce(func.sum(models.DataFile.duration_ms), 0)).filter(
                models.DataFile.task_id == task.id,
                models.DataFile.duration_ms.isnot(None)
            ).scalar() or 0
            
            task_data[task.id] = {
                "id": task.id,
                "name": task.name,
                "create_time": task.create_time,
                "update_time": task.update_time,
                "datafile_count": datafile_count,
                "duration_ms": total_duration
            }
        
        for datafile in datafiles:
            # 获取关联的任务信息（从已查询的任务中获取）
            task = next((t for t in all_tasks if t.id == datafile.task_id), None)
            task_name = task.name if task else "未知任务"
            
            # 获取关联的用户信息
            user = db.query(models.User).filter(models.User.id == datafile.user_id).first()
            username = user.username if user else "未知用户"
            
            # 获取关联的设备信息
            device = db.query(models.Device).filter(models.Device.id == datafile.device_id).first()
            device_name = device.name if device else "未知设备"
            
            # 获取关联的标签信息
            label_permissions = db.query(models.DataFileLabel).filter(models.DataFileLabel.data_file_id == datafile.id).all()
            labels_info = []
            for label_perm in label_permissions:
                label = db.query(models.Label).filter(models.Label.id == label_perm.label_id).first()
                if label:
                    labels_info.append({
                        "label_id": label.id,
                        "label_name": label.name,
                        "permission_id": label_perm.id,
                        "permission_create_time": label_perm.create_time
                    })
            
            datafile_data = {
                "id": datafile.id,
                "task_id": datafile.task_id,
                "task_name": task_name,
                "file_name": datafile.file_name,
                "download_url": datafile.download_url,
                "duration_ms": datafile.duration_ms,
                "user_id": datafile.user_id,
                "username": username,
                "device_id": datafile.device_id,
                "device_name": device_name,
                "create_time": datafile.create_time,
                "update_time": datafile.update_time,
                "labels": labels_info,
                "labels_count": len(labels_info)
            }
            
            result.append(datafile_data)
        
        # 计算分页信息
        total_pages = (total_count + request_data.page_size - 1) // request_data.page_size
        
        return {
            "datafiles": result,
            "tasks": list(task_data.values()),
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
            detail=f"获取数据文件信息时发生错误: {str(e)}"
        )
