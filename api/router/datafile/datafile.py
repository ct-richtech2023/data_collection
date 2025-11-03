from fastapi import APIRouter, Depends, HTTPException, status, Header, UploadFile, File, Form, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Union
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
import aiofiles
import cv2
import numpy as np
import base64
import json
import asyncio
import time
import sys
from common.database import get_db
from common import models, schemas
from common.permission_utils import PermissionUtils
from common.mcap_loader import McapReader
from router.user.auth import get_current_user
from loguru import logger
from pathlib import Path
from common.analyze import McapReader
from mcap_protobuf.decoder import DecoderFactory

router = APIRouter()

# 配置上传目录
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# 配置临时下载目录
TMP_DOWNLOAD_DIR = "/tmp/data_collection"
if not os.path.exists(TMP_DOWNLOAD_DIR):
    os.makedirs(TMP_DOWNLOAD_DIR, exist_ok=True)

# 上传任务状态存储（内存字典，key: upload_task_id, value: UploadProgress）
# 格式: {upload_task_id: UploadProgress}
upload_tasks: dict = {}

# 下载任务状态存储（内存字典，key: download_task_id, value: DownloadProgress）
# 格式: {download_task_id: DownloadProgress}
download_tasks: dict = {}

# 下载文件路径存储（用于下载后清理，key: download_task_id, value: zip_file_path）
# 格式: {download_task_id: zip_file_path}
download_file_paths: dict = {}

# MCAP 查看器存储（支持多用户并发）
# 格式: {user_id: McapReader} 或 {websocket_id: McapReader}
mcap_readers: Dict[Union[int, str], McapReader] = {}  # MCAP读取器实例存储
mcap_temp_files: Dict[Union[int, str], str] = {}  # S3下载的临时MCAP文件路径存储

# WebSocket连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        # 改为每个 WebSocket 可以有多个任务，每个任务对应一个 topic
        # 格式: {websocket: {topic: task}}
        self.streaming_tasks: Dict[WebSocket, Dict[str, asyncio.Task]] = {}
        # 存储每个WebSocket连接对应的user_id（支持多用户并发）
        # 格式: {websocket: user_id}
        self.websocket_users: Dict[WebSocket, int] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket连接建立，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.streaming_tasks:
            # 取消该 WebSocket 的所有任务
            for topic, task in self.streaming_tasks[websocket].items():
                try:
                    task.cancel()
                except:
                    pass
            del self.streaming_tasks[websocket]
        # 清理user_id映射
        if websocket in self.websocket_users:
            del self.websocket_users[websocket]
        logger.info(f"WebSocket连接断开，当前连接数: {len(self.active_connections)}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        """发送个人消息，如果连接已断开则静默失败"""
        try:
            await websocket.send_text(message)
        except WebSocketDisconnect:
            # WebSocket 已断开，静默处理
            logger.debug("WebSocket已断开，无法发送消息")
            self.disconnect(websocket)
        except RuntimeError as e:
            # RuntimeError 可能包含连接状态错误
            error_str = str(e)
            if "not connected" in error_str.lower() or "Need to call \"accept\"" in error_str:
                logger.debug("WebSocket连接已断开，无法发送消息")
                self.disconnect(websocket)
            else:
                # 其他 RuntimeError，记录日志
                logger.warning(f"发送消息时发生运行时错误: {e}")
                self.disconnect(websocket)
        except Exception as e:
            # 其他异常，记录日志但静默处理
            logger.debug(f"发送消息失败，连接可能已断开: {type(e).__name__}: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections.copy():
            try:
                await connection.send_text(message)
            except:
                self.disconnect(connection)

# WebSocket连接管理器实例
websocket_manager = ConnectionManager()

# 全局变量用于错误计数
_encode_error_count = 0

def encode_image_to_base64(img_data: np.ndarray) -> str:
    """将numpy数组图像编码为base64字符串，默认使用低质量压缩（优化性能版本）"""
    if img_data is None:
        return None
    
    try:
        # 提高JPEG质量以获得更好的图像质量（从30提升到50）
        jpeg_quality = 50
        
        # 增加图像大小限制（从5MB提升到10MB），允许传输更大的图像
        if img_data.nbytes > 10 * 1024 * 1024:  # 10MB限制
            # 计算缩放比例
            scale = (10 * 1024 * 1024 / img_data.nbytes) ** 0.5
            new_width = int(img_data.shape[1] * scale)
            new_height = int(img_data.shape[0] * scale)
            img_data = cv2.resize(img_data, (new_width, new_height))
        
        # 优化：使用固定的编码参数列表，避免每次创建
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
        
        # 确保图像是BGR格式
        if len(img_data.shape) == 3 and img_data.shape[2] == 3:
            # 已经是BGR格式，直接编码
            _, buffer = cv2.imencode('.jpg', img_data, encode_params)
        else:
            # 灰度图像
            _, buffer = cv2.imencode('.jpg', img_data, encode_params)
        
        # 转换为base64（移除日志输出）
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return f"data:image/jpeg;base64,{img_base64}"
    except Exception as e:
        # 错误时只输出简单日志，避免影响性能
        global _encode_error_count
        _encode_error_count += 1
        
        # 每100次错误才输出一次日志
        if _encode_error_count % 100 == 0:
            logger.warning(f"图像编码失败（累计 {_encode_error_count} 次）: {e}")
        return None

# S3 配置（支持 /etc/data_collection/s3.yaml 与环境变量，环境变量优先）
S3_CONFIG_FILE = "/etc/data_collection/s3.yaml"
_S3_CFG = {}
try:
    if os.path.exists(S3_CONFIG_FILE):
        with open(S3_CONFIG_FILE, 'r') as f:
            _S3_CFG = yaml.safe_load(f) or {}
except Exception as _e:
    # 配置文件读取失败不阻断启动，后续仍可用环境变量
    logger.info(f"读取 {S3_CONFIG_FILE} 失败: {_e}")

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


@router.post("/upload_mcap", response_model=schemas.UploadResponse)
async def upload_mcap(
    background_tasks: BackgroundTasks,
    task_id: int = Form(..., description="任务ID"),
    device_id: int = Form(..., description="设备ID"),
    label_ids: str = Form(default="", description="标签ID列表，用逗号分隔，如：1,2,3"),
    file: UploadFile = File(..., description="MCAP文件或ZIP文件（包含MCAP文件）"),
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """上传文件 - 支持单个MCAP文件或ZIP文件（包含一个或多个MCAP文件） - 需要设备权限和上传操作权限
    
    立即返回上传任务ID，文件处理在后台异步执行，可通过 /upload_status 接口查询实时进度
    """
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
    
    # 验证文件类型（支持 .mcap 和 .zip）
    if not (file.filename.endswith('.mcap') or file.filename.endswith('.zip')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只支持上传.mcap文件或.zip文件"
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
    
    # 读取文件内容（在请求期间完成，确保文件不会丢失）
    file_content = await file.read()
    filename = file.filename
    
    # 生成上传任务ID
    upload_task_id = str(uuid.uuid4())
    
    # 初始化进度信息（根据文件类型判断总文件数）
    total_files = 1 if filename.endswith('.mcap') else 0
    progress = schemas.UploadProgress(
        upload_task_id=upload_task_id,
        total_files=total_files,
        processed_files=0,
        current_file=filename,
        progress_percent=0.0,
        status="processing",
        message="上传任务已创建，等待处理...",
        start_time=datetime.now(),
        update_time=datetime.now()
    )
    
    # 存储到内存字典
    upload_tasks[upload_task_id] = progress
    
    # 保存用户信息用于后台任务（不能直接传递用户对象，需要传递ID和用户名）
    user_id = current_user.id
    username = current_user.username
    
    # 根据文件扩展名添加后台任务
    if filename.endswith('.mcap'):
        background_tasks.add_task(
            _process_single_mcap_with_progress_background,
            file_content=file_content,
            filename=filename,
            task_id=task_id,
            device_id=device_id,
            label_id_list=label_id_list,
            user_id=user_id,
            username=username,
            upload_task_id=upload_task_id
        )
    elif filename.endswith('.zip'):
        background_tasks.add_task(
            _process_zip_file_with_progress_background,
            file_content=file_content,
            filename=filename,
            task_id=task_id,
            device_id=device_id,
            label_id_list=label_id_list,
            user_id=user_id,
            username=username,
            upload_task_id=upload_task_id
        )
    else:
        # 清理任务状态
        upload_tasks.pop(upload_task_id, None)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的文件类型"
        )
    
    # 立即返回任务ID
    return schemas.UploadResponse(
        upload_task_id=upload_task_id,
        message="上传任务已启动，请使用 upload_task_id 查询实时进度"
    )


def _update_progress(upload_task_id: str, **kwargs):
    """更新上传进度"""
    if upload_task_id in upload_tasks:
        progress = upload_tasks[upload_task_id]
        for key, value in kwargs.items():
            if hasattr(progress, key):
                setattr(progress, key, value)
        progress.update_time = datetime.now()
        upload_tasks[upload_task_id] = progress


def _update_download_progress(download_task_id: str, **kwargs):
    """更新下载进度"""
    if download_task_id in download_tasks:
        progress = download_tasks[download_task_id]
        for key, value in kwargs.items():
            if hasattr(progress, key):
                setattr(progress, key, value)
        progress.update_time = datetime.now()
        download_tasks[download_task_id] = progress


def _process_single_mcap_with_progress_background(
    file_content: bytes,
    filename: str,
    task_id: int,
    device_id: int,
    label_id_list: List[int],
    user_id: int,
    username: str,
    upload_task_id: str
):
    """后台任务：处理单个MCAP文件上传（带进度更新）"""
    from common.database import SessionLocal
    
    db = SessionLocal()
    try:
        # 更新进度：开始处理文件
        _update_progress(upload_task_id, progress_percent=10.0, message="正在解析文件...")
        
        logger.info(f"[Upload MCAP] 后台任务开始 | task_id={task_id} device_id={device_id} user_id={user_id} filename={filename} size={len(file_content)}")
        
        # 生成唯一对象键
        file_extension = os.path.splitext(filename)[1]
        unique_key = f"datafiles/{uuid.uuid4()}{file_extension}"
        
        # 将内容写入临时文件以便解析 MCAP 时长
        temp_path = None
        duration_ms = 60 * 1000  # 默认值
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mcap')
            temp_path = tmp.name
            tmp.write(file_content)
            tmp.close()
            mcap_reader = McapReader(temp_path)
            file_info = mcap_reader.file_info
            duration_ms = int(file_info.duration_sec * 1000)
            mcap_reader.close()
        except Exception as e:
            logger.warning(f"[Upload MCAP] 解析MCAP文件信息失败: {e}")
            duration_ms = 60 * 1000
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        
        # 更新进度：解析完成，开始上传到S3
        _update_progress(upload_task_id, progress_percent=10.0, message="正在上传到S3...")
        
        # 创建进度回调函数
        total_size = len(file_content)
        upload_progress_start = 10.0
        upload_progress_end = 99.0  # S3上传占89%
        upload_progress_range = upload_progress_end - upload_progress_start
        
        # 创建进度回调函数（优化更新频率，避免过于频繁的更新）
        last_update_percent = 0
        update_threshold = 1.0  # 每1%更新一次
        
        def upload_progress_callback(bytes_transferred):
            """S3上传进度回调"""
            nonlocal last_update_percent
            if total_size > 0:
                upload_percent = (bytes_transferred / total_size) * 100.0
                # 只在进度变化超过阈值时更新，避免过于频繁
                if abs(upload_percent - last_update_percent) >= update_threshold or bytes_transferred >= total_size:
                    progress_percent_in_range = (bytes_transferred / total_size) * upload_progress_range
                    current_progress = upload_progress_start + progress_percent_in_range
                    # 格式化文件大小显示
                    transferred_mb = bytes_transferred / (1024 * 1024)
                    total_mb = total_size / (1024 * 1024)
                    _update_progress(
                        upload_task_id,
                        progress_percent=current_progress,
                        message=f"正在上传到S3... {transferred_mb:.2f}/{total_mb:.2f} MB ({upload_percent:.1f}%)"
                    )
                    last_update_percent = upload_percent
        
        # 使用 upload_fileobj 上传到 S3（支持进度回调）
        s3 = get_s3_client()
        
        # 配置传输参数，启用进度回调（使用 TransferConfig）
        from boto3.s3.transfer import TransferConfig
        transfer_config = TransferConfig(
            multipart_threshold=1024 * 1024 * 5,  # 5MB 以上使用分块上传
            multipart_chunksize=1024 * 1024 * 10  # 10MB 分块大小
        )
        
        # 使用 upload_fileobj 配合回调跟踪进度
        try:
            # 创建包装类来跟踪上传进度
            class ProgressFile(io.BytesIO):
                def __init__(self, data, callback):
                    super().__init__(data)
                    self._callback = callback
                    self._bytes_transferred = 0
                    self._len = len(data)
                    self._last_callback_size = 0
                    self._callback_threshold = max(1024 * 1024, len(data) // 100)  # 至少1MB或1%的阈值
                
                def read(self, size=-1):
                    chunk = super().read(size)
                    if chunk:
                        self._bytes_transferred += len(chunk)
                        # 只在达到阈值或完成时调用回调，减少更新频率
                        if (self._bytes_transferred - self._last_callback_size) >= self._callback_threshold or \
                           self._bytes_transferred >= self._len:
                            if self._callback:
                                self._callback(self._bytes_transferred)
                            self._last_callback_size = self._bytes_transferred
                    return chunk
                
                def __len__(self):
                    return self._len
            
            progress_file = ProgressFile(file_content, upload_progress_callback)
            
            # 使用 upload_fileobj 上传（支持进度跟踪）
            s3.upload_fileobj(
                progress_file,
                S3_BUCKET_NAME,
                unique_key,
                ExtraArgs={'ContentType': 'application/octet-stream'},
                Config=transfer_config
            )
        except Exception as e:
            logger.warning(f"[S3] upload_fileobj 失败，尝试使用 put_object: {e}")
            # 如果 upload_fileobj 失败，回退到 put_object
            s3.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=unique_key,
                Body=file_content,
                ContentType='application/octet-stream'
            )
            # 手动更新进度为完成
            _update_progress(upload_task_id, progress_percent=upload_progress_end, message="正在上传到S3...")
        
        logger.info(f"[S3] 上传成功 | key={unique_key} bucket={S3_BUCKET_NAME} duration_ms={duration_ms} size={total_size}")
        download_url = build_s3_url(S3_BUCKET_NAME, unique_key)
        
        # 更新进度：S3上传完成，开始保存数据库记录和操作日志
        _update_progress(upload_task_id, progress_percent=99.0, message="S3上传完成，正在保存数据库记录...")
        
        # 创建数据文件记录
        db_datafile = models.DataFile(
            task_id=task_id,
            file_name=filename,
            download_url=download_url,
            duration_ms=duration_ms,
            user_id=user_id,
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
            db, username, filename, db_datafile.id, task_id, device_id
        )
        
        # 提交所有更改
        db.commit()
        db.refresh(db_datafile)
        
        # 更新进度：数据库保存和操作日志完成（总共1%），任务完成
        _update_progress(
            upload_task_id,
            progress_percent=100.0,
            processed_files=1,
            status="completed",
            message="上传完成",
            completed_files=[schemas.DataFileOut.model_validate(db_datafile)]
        )
        
        logger.info(f"[Upload MCAP] 数据库记录创建成功 | data_file_id={db_datafile.id}")
        
    except Exception as e:
        logger.exception(f"[Upload MCAP] 后台任务失败: {e}")
        db.rollback()
        _update_progress(
            upload_task_id,
            status="failed",
            progress_percent=0.0,
            message=f"上传失败: {str(e)}"
        )
    finally:
        db.close()


def _process_zip_file_with_progress_background(
    file_content: bytes,
    filename: str,
    task_id: int,
    device_id: int,
    label_id_list: List[int],
    user_id: int,
    username: str,
    upload_task_id: str
):
    """后台任务：处理ZIP文件上传（包含一个或多个MCAP文件，带进度更新）"""
    from common.database import SessionLocal
    
    db = SessionLocal()
    try:
        # 更新进度：开始读取ZIP文件
        _update_progress(upload_task_id, progress_percent=5.0, message="正在读取ZIP文件...")
        
        logger.info(f"[Upload ZIP] 后台任务开始 | task_id={task_id} device_id={device_id} user_id={user_id} filename={filename} size={len(file_content)}")
        
        # 更新进度：ZIP文件读取完成
        _update_progress(upload_task_id, progress_percent=10.0, message="正在检查ZIP文件内容...")
        
        # 创建临时ZIP文件
        temp_zip_path = None
        temp_extract_dir = None
        created_files = []
        
        try:
            # 保存ZIP到临时文件
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_zip:
                temp_zip_path = tmp_zip.name
                tmp_zip.write(file_content)
            
            # 先检查ZIP文件中是否包含MCAP文件（不解压）
            has_mcap = False
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                # 检查是否有.mcap文件
                for file_name in file_list:
                    if file_name.endswith('.mcap'):
                        has_mcap = True
                        break
            
            # 如果没有MCAP文件，直接失败（后台任务中不能抛出HTTPException，因为响应已发送）
            if not has_mcap:
                _update_progress(
                    upload_task_id,
                    status="failed",
                    progress_percent=10.0,
                    message="zip包中文件不包含mcap"
                )
                logger.error(f"[Upload ZIP] ZIP包中文件不包含mcap | filename={filename}")
                db.close()
                return
            
            # 更新进度：确认有MCAP文件，开始解压
            _update_progress(upload_task_id, progress_percent=12.0, message="检测到MCAP文件，正在解压ZIP文件...")
            
            # 创建临时解压目录
            temp_extract_dir = tempfile.mkdtemp()
            
            # 解压ZIP文件
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_dir)
            
            # 查找所有.mcap文件（只处理MCAP文件，忽略其他类型文件）
            mcap_files = []
            for file_name in file_list:
                if file_name.endswith('.mcap'):
                    # 获取完整路径
                    full_path = os.path.join(temp_extract_dir, file_name)
                    if os.path.isfile(full_path):
                        mcap_files.append((file_name, full_path))
            
            # 再次确认（双重检查）
            if not mcap_files:
                _update_progress(
                    upload_task_id,
                    status="failed",
                    progress_percent=15.0,
                    message="zip包中文件不包含mcap"
                )
                logger.error(f"[Upload ZIP] 解压后未找到MCAP文件 | filename={filename}")
                db.close()
                return
            
            # 统计文件类型信息
            total_files_count = len(file_list)
            other_files_count = total_files_count - len(mcap_files)
            
            logger.info(f"[Upload ZIP] ZIP包中包含 {total_files_count} 个文件，其中 {len(mcap_files)} 个MCAP文件（将只处理MCAP文件，忽略其他 {other_files_count} 个文件）")
            
            # 更新进度：解压完成，开始处理文件
            _update_progress(
                upload_task_id,
                total_files=len(mcap_files),
                progress_percent=15.0,
                message=f"解压完成，找到 {len(mcap_files)} 个MCAP文件，开始处理（忽略其他类型文件）..."
            )
            
            # 获取S3客户端
            s3 = get_s3_client()
            
            # 处理每个MCAP文件
            for idx, (mcap_filename, mcap_path) in enumerate(mcap_files, 1):
                # 更新当前处理的文件
                base_name = os.path.basename(mcap_filename)
                _update_progress(
                    upload_task_id,
                    current_file=base_name,
                    message=f"正在处理第 {idx}/{len(mcap_files)} 个文件: {base_name}"
                )
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
                    unique_key = f"datafiles/{uuid.uuid4()}_{base_name}"
                    
                    # 创建进度回调函数
                    total_size = len(mcap_content)
                    # 计算当前文件在整个ZIP处理中的进度范围
                    # 解压完成15% + 处理文件85%，每个文件平分这85%
                    file_index_progress = 15.0 + (85.0 * (idx - 1) / len(mcap_files))
                    file_next_progress = 15.0 + (85.0 * idx / len(mcap_files))
                    file_progress_range = file_next_progress - file_index_progress
                    # S3上传占用当前文件处理的60%（40%用于解析，60%用于上传）
                    s3_upload_start = file_index_progress + file_progress_range * 0.4
                    s3_upload_end = file_index_progress + file_progress_range * 1.0
                    s3_upload_range = s3_upload_end - s3_upload_start
                    
                    # 创建进度回调函数（优化更新频率）
                    last_update_percent = 0
                    update_threshold = 1.0  # 每1%更新一次
                    
                    def upload_progress_callback(bytes_transferred):
                        """S3上传进度回调"""
                        nonlocal last_update_percent
                        if total_size > 0:
                            upload_percent = (bytes_transferred / total_size) * 100.0
                            # 只在进度变化超过阈值时更新
                            if abs(upload_percent - last_update_percent) >= update_threshold or bytes_transferred >= total_size:
                                progress_percent_in_range = (bytes_transferred / total_size) * s3_upload_range
                                current_progress = s3_upload_start + progress_percent_in_range
                                # 格式化文件大小显示
                                transferred_mb = bytes_transferred / (1024 * 1024)
                                total_mb = total_size / (1024 * 1024)
                                _update_progress(
                                    upload_task_id,
                                    progress_percent=current_progress,
                                    message=f"正在上传第 {idx}/{len(mcap_files)} 个文件到S3... {transferred_mb:.2f}/{total_mb:.2f} MB ({upload_percent:.1f}%)"
                                )
                                last_update_percent = upload_percent
                    
                    # 使用 upload_fileobj 上传到 S3（支持进度回调）
                    s3 = get_s3_client()
                    
                    # 创建包装类来跟踪上传进度
                    class ProgressFile(io.BytesIO):
                        def __init__(self, data, callback):
                            super().__init__(data)
                            self._callback = callback
                            self._bytes_transferred = 0
                            self._len = len(data)
                            self._last_callback_size = 0
                            self._callback_threshold = max(1024 * 1024, len(data) // 100)  # 至少1MB或1%的阈值
                        
                        def read(self, size=-1):
                            chunk = super().read(size)
                            if chunk:
                                self._bytes_transferred += len(chunk)
                                # 只在达到阈值或完成时调用回调，减少更新频率
                                if (self._bytes_transferred - self._last_callback_size) >= self._callback_threshold or \
                                   self._bytes_transferred >= self._len:
                                    if self._callback:
                                        self._callback(self._bytes_transferred)
                                    self._last_callback_size = self._bytes_transferred
                            return chunk
                        
                        def __len__(self):
                            return self._len
                    
                    progress_file = ProgressFile(mcap_content, upload_progress_callback)
                    
                    # 配置传输参数（使用 TransferConfig）
                    from boto3.s3.transfer import TransferConfig
                    transfer_config = TransferConfig(
                        multipart_threshold=1024 * 1024 * 5,  # 5MB 以上使用分块上传
                        multipart_chunksize=1024 * 1024 * 10  # 10MB 分块大小
                    )
                    
                    # 使用 upload_fileobj 上传（支持进度跟踪）
                    try:
                        s3.upload_fileobj(
                            progress_file,
                            S3_BUCKET_NAME,
                            unique_key,
                            ExtraArgs={'ContentType': 'application/octet-stream'},
                            Config=transfer_config
                        )
                    except Exception as e:
                        logger.warning(f"[S3] upload_fileobj 失败，尝试使用 put_object: {e}")
                        # 如果 upload_fileobj 失败，回退到 put_object
                        s3.put_object(
                            Bucket=S3_BUCKET_NAME,
                            Key=unique_key,
                            Body=mcap_content,
                            ContentType='application/octet-stream'
                        )
                        # 手动更新进度
                        _update_progress(upload_task_id, progress_percent=s3_upload_end, message=f"正在上传第 {idx}/{len(mcap_files)} 个文件到S3...")
                    
                    logger.info(f"[S3] 上传成功 | key={unique_key} bucket={S3_BUCKET_NAME} duration_ms={duration_ms} size={total_size}")
                    download_url = build_s3_url(S3_BUCKET_NAME, unique_key)
                    
                    # 创建数据文件记录
                    db_datafile = models.DataFile(
                        task_id=task_id,
                        file_name=base_name,  # 使用原始文件名
                        download_url=download_url,
                        duration_ms=duration_ms,
                        user_id=user_id,
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
                        db, username, base_name, db_datafile.id, task_id, device_id
                    )
                    
                    created_files.append(db_datafile)
                    logger.info(f"[Upload ZIP] MCAP文件处理成功 | data_file_id={db_datafile.id} filename={base_name}")
                    
                    # 更新进度：文件处理成功
                    completed_file_data = schemas.DataFileOut.model_validate(db_datafile)
                    current_progress = upload_tasks.get(upload_task_id)
                    if current_progress:
                        completed_list = list(current_progress.completed_files) if current_progress.completed_files else []
                        completed_list.append(completed_file_data)
                        # 计算总体进度：解压15% + 处理85% * (已处理文件数/总文件数)
                        progress_percent = 15.0 + (85.0 * len(completed_list) / len(mcap_files))
                        _update_progress(
                            upload_task_id,
                            processed_files=len(completed_list),
                            progress_percent=progress_percent,
                            completed_files=completed_list
                        )
                    
                except Exception as e:
                    logger.exception(f"[Upload ZIP] 处理MCAP文件失败: {mcap_filename}, 错误: {e}")
                    # 更新失败文件列表
                    failed_name = os.path.basename(mcap_filename)
                    current_progress = upload_tasks.get(upload_task_id)
                    if current_progress:
                        failed_list = list(current_progress.failed_files) if current_progress.failed_files else []
                        failed_list.append(failed_name)
                        _update_progress(upload_task_id, failed_files=failed_list)
                    # 继续处理下一个文件，不中断整个流程
                    continue
            
            # 提交所有更改
            db.commit()
            
            # 刷新所有对象以获取完整数据
            for db_datafile in created_files:
                db.refresh(db_datafile)
            
            # 更新最终进度
            _update_progress(upload_task_id, progress_percent=100.0)
            
            if not created_files:
                _update_progress(
                    upload_task_id,
                    status="failed",
                    progress_percent=100.0,
                    message="所有MCAP文件处理失败"
                )
                logger.error("[Upload ZIP] 所有MCAP文件处理失败")
                # 注意：后台任务中不能抛出HTTPException，因为响应已发送，只需更新进度状态
                return
            else:
                current_progress = upload_tasks.get(upload_task_id)
                if current_progress and current_progress.failed_files:
                    message = f"上传完成: 成功 {len(created_files)}/{len(mcap_files)} 个文件，失败 {len(current_progress.failed_files)} 个"
                else:
                    message = f"上传完成: 成功处理所有 {len(created_files)} 个文件"
                _update_progress(
                    upload_task_id,
                    status="completed",
                    message=message
                )
            
            logger.info(f"[Upload ZIP] 批量上传完成 | 成功: {len(created_files)}/{len(mcap_files)}")
            
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
        
    except Exception as e:
        logger.exception(f"[Upload ZIP] 后台任务失败: {e}")
        db.rollback()
        _update_progress(
            upload_task_id,
            status="failed",
            message=f"上传失败: {str(e)}"
        )
        # 注意：后台任务中不能抛出HTTPException，因为响应已发送，只需更新进度状态
    finally:
        db.close()


async def _process_single_mcap_with_progress(
    file: UploadFile,
    task_id: int,
    device_id: int,
    label_id_list: List[int],
    current_user: models.User,
    db: Session,
    upload_task_id: str
) -> None:
    """处理单个MCAP文件上传（带进度更新）"""
    try:
        # 更新进度：开始读取文件
        _update_progress(upload_task_id, progress_percent=10.0, message="正在读取文件...")
        
        # 读取文件内容
        content = await file.read()
        logger.info(f"[Upload MCAP] 收到上传请求 | task_id={task_id} device_id={device_id} user_id={current_user.id} filename={file.filename} size={len(content)}")
        
        # 更新进度：文件读取完成
        _update_progress(upload_task_id, progress_percent=20.0, message="文件读取完成，正在解析...")
        
        # 生成唯一对象键
        file_extension = os.path.splitext(file.filename)[1]
        unique_key = f"datafiles/{uuid.uuid4()}{file_extension}"
        
        # 将内容写入临时文件以便解析 MCAP 时长
        temp_path = None
        duration_ms = 60 * 1000  # 默认值
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mcap')
            temp_path = tmp.name
            tmp.write(content)
            tmp.close()
            mcap_reader = McapReader(temp_path)
            file_info = mcap_reader.file_info
            duration_ms = int(file_info.duration_sec * 1000)
            mcap_reader.close()
        except Exception as e:
            logger.warning(f"[Upload MCAP] 解析MCAP文件信息失败: {e}")
            duration_ms = 60 * 1000
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        
        # 更新进度：解析完成，开始上传到S3
        _update_progress(upload_task_id, progress_percent=40.0, message="正在上传到S3...")
        
        # 上传到 S3
        s3 = get_s3_client()
        s3.put_object(Bucket=S3_BUCKET_NAME, Key=unique_key, Body=content, ContentType='application/octet-stream')
        logger.info(f"[S3] 上传成功 | key={unique_key} bucket={S3_BUCKET_NAME} duration_ms={duration_ms}")
        download_url = build_s3_url(S3_BUCKET_NAME, unique_key)
        
        # 更新进度：S3上传完成
        _update_progress(upload_task_id, progress_percent=70.0, message="S3上传完成，正在保存数据库记录...")
        
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
        db.flush()  # 获取ID但不提交
        
        # 创建标签关联
        if label_id_list:
            for label_id in label_id_list:
                db_datafile_label = models.DataFileLabel(
                    data_file_id=db_datafile.id,
                    label_id=label_id
                )
                db.add(db_datafile_label)
        
        # 更新进度：数据库记录创建完成
        _update_progress(upload_task_id, progress_percent=90.0, message="正在创建操作日志...")
        
        # 创建文件上传操作日志
        from common.operation_log_util import OperationLogUtil
        OperationLogUtil.log_file_upload(
            db, current_user.username, file.filename, db_datafile.id, task_id, device_id
        )
        
        # 提交所有更改
        db.commit()
        db.refresh(db_datafile)
        
        # 更新进度：完成
        _update_progress(
            upload_task_id,
            progress_percent=100.0,
            processed_files=1,
            status="completed",
            message="上传完成",
            completed_files=[schemas.DataFileOut.model_validate(db_datafile)]
        )
        
        logger.info(f"[Upload MCAP] 数据库记录创建成功 | data_file_id={db_datafile.id}")
        
    except Exception as e:
        logger.exception(f"[Upload MCAP] 失败: {e}")
        db.rollback()
        _update_progress(
            upload_task_id,
            status="failed",
            progress_percent=0.0,
            message=f"上传失败: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传MCAP文件时发生错误: {str(e)}"
        )


async def _process_single_mcap(
    file: UploadFile,
    task_id: int,
    device_id: int,
    label_id_list: List[int],
    current_user: models.User,
    db: Session
) -> List[schemas.DataFileOut]:
    """处理单个MCAP文件上传（旧版本，保留兼容性）"""
    try:
        # 读取文件内容
        content = await file.read()
        logger.info(f"[Upload MCAP] 收到上传请求 | task_id={task_id} device_id={device_id} user_id={current_user.id} filename={file.filename} size={len(content)}")
        
        # 生成唯一对象键
        file_extension = os.path.splitext(file.filename)[1]
        unique_key = f"datafiles/{uuid.uuid4()}{file_extension}"
        
        # 将内容写入临时文件以便解析 MCAP 时长
        temp_path = None
        duration_ms = 60 * 1000  # 默认值
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mcap')
            temp_path = tmp.name
            tmp.write(content)
            tmp.close()
            mcap_reader = McapReader(temp_path)
            file_info = mcap_reader.file_info
            duration_ms = int(file_info.duration_sec * 1000)
            mcap_reader.close()
        except Exception as e:
            logger.warning(f"[Upload MCAP] 解析MCAP文件信息失败: {e}")
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
            db, current_user.username, file.filename, db_datafile.id, task_id, device_id
        )
        
        # 提交所有更改
        db.commit()
        db.refresh(db_datafile)
        
        logger.info(f"[Upload MCAP] 数据库记录创建成功 | data_file_id={db_datafile.id}")
        return [db_datafile]
        
    except Exception as e:
        logger.exception(f"[Upload MCAP] 失败: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传MCAP文件时发生错误: {str(e)}"
        )


async def _process_zip_file_with_progress(
    file: UploadFile,
    task_id: int,
    device_id: int,
    label_id_list: List[int],
    current_user: models.User,
    db: Session,
    upload_task_id: str
) -> None:
    """处理ZIP文件上传（包含一个或多个MCAP文件，带进度更新）"""
    try:
        # 更新进度：开始读取ZIP文件
        _update_progress(upload_task_id, progress_percent=5.0, message="正在读取ZIP文件...")
        
        # 读取ZIP文件内容
        zip_content = await file.read()
        logger.info(f"[Upload ZIP] 收到上传请求 | task_id={task_id} device_id={device_id} user_id={current_user.id} filename={file.filename} size={len(zip_content)}")
        
        # 更新进度：ZIP文件读取完成
        _update_progress(upload_task_id, progress_percent=10.0, message="正在解压ZIP文件...")
        
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
            
            # 更新进度：解压完成，开始处理文件
            _update_progress(
                upload_task_id,
                total_files=len(mcap_files),
                progress_percent=15.0,
                message=f"找到 {len(mcap_files)} 个MCAP文件，开始处理..."
            )
            
            # 获取S3客户端
            s3 = get_s3_client()
            
            # 处理每个MCAP文件
            for idx, (mcap_filename, mcap_path) in enumerate(mcap_files, 1):
                # 更新当前处理的文件
                base_name = os.path.basename(mcap_filename)
                _update_progress(
                    upload_task_id,
                    current_file=base_name,
                    message=f"正在处理第 {idx}/{len(mcap_files)} 个文件: {base_name}"
                )
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
                    
                    # 更新进度：文件处理成功
                    completed_file_data = schemas.DataFileOut.model_validate(db_datafile)
                    current_progress = upload_tasks.get(upload_task_id)
                    if current_progress:
                        completed_list = list(current_progress.completed_files) if current_progress.completed_files else []
                        completed_list.append(completed_file_data)
                        # 计算总体进度：解压15% + 处理85% * (已处理文件数/总文件数)
                        progress_percent = 15.0 + (85.0 * len(completed_list) / len(mcap_files))
                        _update_progress(
                            upload_task_id,
                            processed_files=len(completed_list),
                            progress_percent=progress_percent,
                            completed_files=completed_list
                        )
                    
                except Exception as e:
                    logger.exception(f"[Upload ZIP] 处理MCAP文件失败: {mcap_filename}, 错误: {e}")
                    # 更新失败文件列表
                    failed_name = os.path.basename(mcap_filename)
                    current_progress = upload_tasks.get(upload_task_id)
                    if current_progress:
                        failed_list = list(current_progress.failed_files) if current_progress.failed_files else []
                        failed_list.append(failed_name)
                        _update_progress(upload_task_id, failed_files=failed_list)
                    # 继续处理下一个文件，不中断整个流程
                    continue
            
            # 提交所有更改
            db.commit()
            
            # 刷新所有对象以获取完整数据
            for db_datafile in created_files:
                db.refresh(db_datafile)
            
            # 更新最终进度
            _update_progress(upload_task_id, progress_percent=100.0)
            
            if not created_files:
                _update_progress(
                    upload_task_id,
                    status="failed",
                    progress_percent=100.0,
                    message="所有MCAP文件处理失败"
                )
                logger.error("[Upload ZIP] 所有MCAP文件处理失败")
                # 注意：后台任务中不能抛出HTTPException，因为响应已发送，只需更新进度状态
                return
            else:
                current_progress = upload_tasks.get(upload_task_id)
                if current_progress and current_progress.failed_files:
                    message = f"上传完成: 成功 {len(created_files)}/{len(mcap_files)} 个文件，失败 {len(current_progress.failed_files)} 个"
                else:
                    message = f"上传完成: 成功处理所有 {len(created_files)} 个文件"
                _update_progress(
                    upload_task_id,
                    status="completed",
                    message=message
                )
            
            logger.info(f"[Upload ZIP] 批量上传完成 | 成功: {len(created_files)}/{len(mcap_files)}")
            
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
        _update_progress(
            upload_task_id,
            status="failed",
            message=f"上传失败: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传ZIP文件时发生错误: {str(e)}"
        )


@router.get("/upload_status", response_model=schemas.UploadProgress)
def get_upload_status(
    upload_task_id: str,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """查询上传任务的实时进度
    
    通过上传接口返回的 upload_task_id 查询当前上传进度
    """
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 检查任务是否存在
    if upload_task_id not in upload_tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传任务不存在或已过期"
        )
    
    progress = upload_tasks[upload_task_id]
    return progress


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
        logger.info(f"已删除 {data_file_labels_count} 个关联的标签映射")
    
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
                    logger.info(f"删除物理文件失败: {e}")
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


@router.post("/download_files_zip", response_model=schemas.DownloadResponse)
def download_files_zip(
    background_tasks: BackgroundTasks,
    datafile_ids: List[int],
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """下载多个数据文件打包成ZIP - 需要设备权限和下载操作权限
    
    立即返回下载任务ID，文件打包在后台异步执行，可通过 /download_status 接口查询实时进度
    """
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
    
    # 生成下载任务ID
    download_task_id = str(uuid.uuid4())
    
    # 初始化进度信息
    progress = schemas.DownloadProgress(
        download_task_id=download_task_id,
        total_files=len(datafiles),
        processed_files=0,
        current_file=None,
        progress_percent=0.0,
        status="processing",
        message="下载任务已创建，等待处理...",
        s3_download_percent=0.0,
        zip_pack_percent=0.0,
        start_time=datetime.now(),
        update_time=datetime.now()
    )
    
    # 存储到内存字典
    download_tasks[download_task_id] = progress
    
    # 保存用户和文件信息用于后台任务
    user_id = current_user.id
    username = current_user.username
    
    # 准备文件信息（序列化为可传递的格式）
    file_info_list = []
    for df in datafiles:
        file_info_list.append({
            "id": df.id,
            "file_name": df.file_name,
            "download_url": df.download_url
        })
    
    # 添加后台任务
    background_tasks.add_task(
        _process_download_zip_background,
        file_info_list=file_info_list,
        user_id=user_id,
        username=username,
        datafile_ids=datafile_ids,
        download_task_id=download_task_id
    )
    
    # 立即返回任务ID
    return schemas.DownloadResponse(
        download_task_id=download_task_id,
        message="下载任务已启动，请使用 download_task_id 查询实时进度"
    )


def _process_download_zip_background(
    file_info_list: List[dict],
    user_id: int,
    username: str,
    datafile_ids: List[int],
    download_task_id: str
):
    """后台任务：处理ZIP文件下载（从S3拉取文件并打包，带进度更新）"""
    from common.database import SessionLocal
    
    db = SessionLocal()
    try:
        _update_download_progress(
            download_task_id,
            progress_percent=5.0,
            message="开始准备文件..."
        )
        
        logger.info(f"[Download ZIP] 后台任务开始 | files={len(file_info_list)} user_id={user_id}")
        
        # 直接创建本地ZIP文件路径
        zip_filename = f"datafiles_{len(file_info_list)}_files_{download_task_id[:8]}.zip"
        temp_zip_path = os.path.join(TMP_DOWNLOAD_DIR, zip_filename)
        
        total_files = len(file_info_list)
        
        # S3下载阶段占85%，打包阶段占10%，完成占5%
        s3_download_start = 5.0
        s3_download_end = 90.0
        zip_pack_start = 90.0
        zip_pack_end = 95.0
        
        # 直接打开本地ZIP文件进行写入
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            s3 = get_s3_client()
            
            # 阶段1：从S3下载文件并写入ZIP（85%）
            for idx, file_info in enumerate(file_info_list, 1):
                file_name = file_info['file_name']
                download_url = file_info['download_url']
                
                # 更新当前处理的文件
                file_progress_start = s3_download_start + (s3_download_end - s3_download_start) * (idx - 1) / total_files
                file_progress_end = s3_download_start + (s3_download_end - s3_download_start) * idx / total_files
                
                _update_download_progress(
                    download_task_id,
                    current_file=file_name,
                    progress_percent=file_progress_start,
                    message=f"正在从S3下载第 {idx}/{total_files} 个文件: {file_name}..."
                )
                
                try:
                    if download_url.startswith("s3://"):
                        bucket, key = parse_s3_url(download_url)
                        obj = s3.get_object(Bucket=bucket, Key=key)
                        file_size = obj.get('ContentLength', 0)
                        body = obj['Body']
                        
                        # 创建进度跟踪
                        downloaded_bytes = 0
                        last_update_bytes = 0
                        update_threshold = max(1024 * 1024, file_size // 100) if file_size > 0 else 1024 * 1024
                        
                        with zipf.open(file_name, 'w') as dest:
                            chunk_size = 1024 * 1024  # 1MB
                            while True:
                                chunk = body.read(chunk_size)
                                if not chunk:
                                    break
                                dest.write(chunk)
                                downloaded_bytes += len(chunk)
                                
                                # 更新S3下载进度
                                if downloaded_bytes - last_update_bytes >= update_threshold or downloaded_bytes >= file_size:
                                    if file_size > 0:
                                        s3_percent = (downloaded_bytes / file_size) * 100.0
                                        file_progress = file_progress_start + (file_progress_end - file_progress_start) * (downloaded_bytes / file_size)
                                        _update_download_progress(
                                            download_task_id,
                                            progress_percent=file_progress,
                                            s3_download_percent=s3_percent,
                                            message=f"正在从S3下载第 {idx}/{total_files} 个文件: {file_name}... {downloaded_bytes}/{file_size} 字节 ({s3_percent:.1f}%)"
                                        )
                                    last_update_bytes = downloaded_bytes
                        
                        # 文件下载完成
                        _update_download_progress(
                            download_task_id,
                            progress_percent=file_progress_end,
                            s3_download_percent=100.0,
                            message=f"S3下载完成: {file_name}"
                        )
                        
                    else:
                        # 兼容本地路径（历史数据）
                        if download_url.startswith("/uploads/"):
                            file_path = download_url.replace("/uploads/", UPLOAD_DIR + "/")
                        else:
                            file_path = os.path.join(UPLOAD_DIR, os.path.basename(download_url))
                        
                        if os.path.exists(file_path):
                            file_size = os.path.getsize(file_path)
                            with open(file_path, 'rb') as src, zipf.open(file_name, 'w') as dest:
                                copied_bytes = 0
                                while True:
                                    chunk = src.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    dest.write(chunk)
                                    copied_bytes += len(chunk)
                                    
                                    # 更新本地文件复制进度
                                    if file_size > 0:
                                        local_percent = (copied_bytes / file_size) * 100.0
                                        file_progress = file_progress_start + (file_progress_end - file_progress_start) * (copied_bytes / file_size)
                                        _update_download_progress(
                                            download_task_id,
                                            progress_percent=file_progress,
                                            s3_download_percent=local_percent,
                                            message=f"正在复制第 {idx}/{total_files} 个本地文件: {file_name}... {copied_bytes}/{file_size} 字节 ({local_percent:.1f}%)"
                                        )
                            
                            _update_download_progress(
                                download_task_id,
                                progress_percent=file_progress_end,
                                s3_download_percent=100.0,
                                message=f"本地文件复制完成: {file_name}"
                            )
                        else:
                            logger.warning(f"[Download ZIP] 本地文件不存在，跳过 | path={file_path}")
                            _update_download_progress(
                                download_task_id,
                                progress_percent=file_progress_end,
                                message=f"跳过：本地文件不存在 - {file_name}"
                            )
                    
                    # 更新已处理文件数
                    _update_download_progress(
                        download_task_id,
                        processed_files=idx
                    )
                    
                except Exception as e:
                    logger.exception(f"[Download ZIP] 处理文件失败: {file_name}, 错误: {e}")
                    # 更新进度，继续处理下一个文件
                    _update_download_progress(
                        download_task_id,
                        progress_percent=file_progress_end,
                        message=f"文件处理失败: {file_name} - {str(e)}"
                    )
                    continue
            
            # 阶段2：完成ZIP打包（5%）
            # ZIP文件在写入过程中已经实时打包，这里主要是状态更新
            _update_download_progress(
                download_task_id,
                progress_percent=zip_pack_start,
                zip_pack_percent=0.0,
                message="正在完成ZIP打包..."
            )
        
        # ZIP文件已经写入完成，获取文件大小
        if os.path.exists(temp_zip_path):
            zip_size = os.path.getsize(temp_zip_path)
        else:
            zip_size = 0
        
        if zip_size == 0:
            _update_download_progress(
                download_task_id,
                status="failed",
                progress_percent=0.0,
                message="ZIP文件创建失败，文件大小为0"
            )
            logger.error(f"[Download ZIP] ZIP文件创建失败，文件大小为0")
            return
        
        _update_download_progress(
            download_task_id,
            progress_percent=zip_pack_end,
            zip_pack_percent=100.0,
            message=f"ZIP打包完成，文件大小: {zip_size / (1024 * 1024):.2f} MB"
        )
        
        # 阶段3：生成下载链接（5%）
        _update_download_progress(
            download_task_id,
            progress_percent=95.0,
            message="正在生成下载链接..."
        )
        
        # 生成临时下载链接（相对于 /tmp/data_collection）
        temp_download_url = f"/tmp/data_collection/{zip_filename}"
        
        # 保存文件路径，用于下载后清理
        download_file_paths[download_task_id] = temp_zip_path
        
        # 创建文件下载操作日志
        from common.operation_log_util import OperationLogUtil
        OperationLogUtil.log_file_download(
            db, username, len(file_info_list), datafile_ids
        )
        
        # 更新完成状态
        _update_download_progress(
            download_task_id,
            progress_percent=100.0,
            status="completed",
            message=f"下载完成：成功打包 {len(file_info_list)} 个文件",
            download_url=temp_download_url
        )
        
        logger.info(f"[Download ZIP] 批量下载完成 | 成功: {len(file_info_list)} 个文件, size={zip_size}, path={temp_zip_path}")
        
    except Exception as e:
        logger.exception(f"[Download ZIP] 后台任务失败: {e}")
        _update_download_progress(
            download_task_id,
            status="failed",
            message=f"下载失败: {str(e)}"
        )
    finally:
        db.close()


@router.get("/download_status", response_model=schemas.DownloadProgress)
def get_download_status(
    download_task_id: str,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """查询下载任务的实时进度
    
    通过下载接口返回的 download_task_id 查询当前下载进度
    """
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 检查任务是否存在
    if download_task_id not in download_tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="下载任务不存在或已过期"
        )
    
    progress = download_tasks[download_task_id]
    return progress


@router.get("/download_file_by_task/{download_task_id}")
async def download_file_by_task(
    download_task_id: str,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """通过下载任务ID下载ZIP文件，下载完成后自动删除临时文件"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 检查任务是否存在
    if download_task_id not in download_tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="下载任务不存在或已过期"
        )
    
    progress = download_tasks[download_task_id]
    
    # 检查任务是否已完成
    if progress.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"下载任务尚未完成，当前状态: {progress.status}"
        )
    
    # 检查是否有下载链接
    if not progress.download_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="下载文件不存在"
        )
    
    # 获取文件路径
    file_path = None
    if download_task_id in download_file_paths:
        file_path = download_file_paths[download_task_id]
    else:
        # 从download_url解析文件路径
        if progress.download_url:
            if progress.download_url.startswith("/tmp/data_collection/"):
                file_path = progress.download_url.replace("/tmp/data_collection/", TMP_DOWNLOAD_DIR + "/")
            elif progress.download_url.startswith("/downloads/"):
                # 兼容旧路径
                file_path = progress.download_url.replace("/downloads/", TMP_DOWNLOAD_DIR + "/")
            elif progress.download_url.startswith("/uploads/"):
                # 兼容旧路径
                file_path = progress.download_url.replace("/uploads/", UPLOAD_DIR + "/")
    
    if not file_path or not os.path.exists(file_path):
        # 清理无效的任务记录
        download_tasks.pop(download_task_id, None)
        download_file_paths.pop(download_task_id, None)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="下载文件不存在或已过期"
        )
    
    # 获取文件大小
    file_size = os.path.getsize(file_path)
    
    # 从路径获取文件名
    zip_filename = os.path.basename(file_path)
    
    logger.info(f"[Download ZIP] 开始下载（本地文件） | task_id={download_task_id} file={zip_filename} size={file_size}")
    
    # 使用异步文件读取，尽快产出首块字节，浏览器会立即显示下载进度
    # 使用较小的 chunk size 以便更快地发送第一个数据包
    async def iter_file():
        """异步迭代文件内容，尽快返回第一个字节"""
        chunk_size = 512 * 1024  # 512KB chunks - 平衡性能和首字节速度
        
        async with aiofiles.open(file_path, 'rb') as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    
    # 设置响应头，确保浏览器能够立即开始下载并显示进度
    headers = {
        "Content-Disposition": f'attachment; filename="{zip_filename}"',
        "Content-Length": str(file_size),  # 必须设置，浏览器才能显示进度
        "Content-Type": "application/zip",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Accept-Ranges": "bytes",  # 支持断点续传，帮助浏览器处理下载进度
        # 禁用服务器缓冲，立即开始传输（对nginx等反向代理的提示）
        "X-Accel-Buffering": "no"
    }
    
    return StreamingResponse(
        iter_file(),
        media_type='application/zip',
        headers=headers
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
    logger.info(f"测试ZIP文件大小: {zip_size} 字节")  # 调试信息
    
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



async def download_mcap_from_s3_for_user(s3_url: str, user_id: int) -> str:
    """从S3下载MCAP文件到临时文件，返回临时文件路径（支持多用户并发）
    
    Args:
        s3_url: S3文件URL (s3://bucket/key)
        user_id: 用户ID，用于创建独立的临时文件
        
    Returns:
        临时文件路径
    """
    global mcap_temp_files
    
    try:
        bucket, key = parse_s3_url(s3_url)
        s3 = get_s3_client()
        
        logger.info(f"开始从S3下载MCAP文件 | bucket={bucket} key={key} user_id={user_id}")
        
        # 获取文件信息
        obj = s3.get_object(Bucket=bucket, Key=key)
        file_size = obj.get('ContentLength', 0)
        body = obj['Body']
        
        # 使用统一的临时目录
        temp_dir = "/tmp/data_collection"
        if not os.path.exists(temp_dir):
            try:
                os.makedirs(temp_dir, exist_ok=True, mode=0o755)
            except Exception as e:
                logger.info(f"无法创建临时目录 {temp_dir}，使用系统临时目录: {e}")
                temp_dir = None
        
        # 创建临时文件（基于user_id生成唯一文件名，避免多用户冲突）
        if temp_dir:
            # 使用key的文件名，如果key包含路径，只取文件名部分
            filename = os.path.basename(key) or "mcap_file.mcap"
            if not filename.endswith('.mcap'):
                filename += '.mcap'
            # 添加user_id确保唯一性
            temp_path = os.path.join(temp_dir, f"mcap_user_{user_id}_{uuid.uuid4().hex[:8]}_{filename}")
        else:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'.mcap', prefix=f'user_{user_id}_')
            temp_path = temp_file.name
            temp_file.close()
        
        # 流式下载文件（支持大文件，使用异步IO实现真正的并发下载）
        downloaded_bytes = 0
        chunk_size = 1024 * 1024  # 1MB chunks
        
        # 使用aiofiles进行异步文件写入，支持并发下载
        async with aiofiles.open(temp_path, 'wb') as f:
            while True:
                # 将同步的S3读取操作放到线程池中执行，避免阻塞事件循环
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    break
                # 异步写入文件
                await f.write(chunk)
                downloaded_bytes += len(chunk)
                
                # 每10MB输出一次进度
                if downloaded_bytes % (10 * 1024 * 1024) == 0 and file_size > 0:
                    progress = (downloaded_bytes / file_size * 100)
                    logger.info(f"S3下载进度 (用户{user_id}): {downloaded_bytes / (1024*1024):.2f} MB / {file_size / (1024*1024):.2f} MB ({progress:.1f}%)")
        
        actual_size = os.path.getsize(temp_path)
        logger.info(f"S3下载完成 | path={temp_path} size={actual_size / (1024*1024):.2f} MB user_id={user_id}")
        
        # 清理该用户之前的临时文件（如果有）
        if user_id in mcap_temp_files:
            old_temp_file = mcap_temp_files[user_id]
            if old_temp_file and os.path.exists(old_temp_file) and old_temp_file != temp_path:
                try:
                    os.remove(old_temp_file)
                    logger.info(f"已清理用户 {user_id} 的旧临时文件: {old_temp_file}")
                except Exception as e:
                    logger.info(f"清理旧临时文件失败: {e}")
        
        return temp_path
        
    except ValueError as e:
        # S3 URL解析错误
        logger.info(f"S3 URL解析失败: {e}")
        raise HTTPException(status_code=400, detail=f"无效的S3 URL: {str(e)}")
    except Exception as e:
        logger.info(f"从S3下载MCAP文件失败: {e}")
        import traceback
        logger.info(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"从S3下载MCAP文件失败: {str(e)}")

async def download_mcap_from_s3(s3_url: str) -> str:
    """从S3下载MCAP文件到临时文件，返回临时文件路径（兼容旧版本，使用默认user_id=0）"""
    return await download_mcap_from_s3_for_user(s3_url, user_id=0)

# 注释序列化工具
def _serialize_annotations_from_reader(reader: McapReader):
    try:
        anns = reader._load_annotations()
        result = []
        for a in anns or []:
            if isinstance(a, dict):
                result.append({
                    "timestamp_ns": a.get("timestamp_ns"),
                    "text": a.get("text"),
                    "frame_index": a.get("frame_index")
                })
            else:
                result.append({
                    "timestamp_ns": getattr(a, "timestamp_ns", None),
                    "text": getattr(a, "text", None),
                    "frame_index": getattr(a, "frame_index", None)
                })
        return result
    except Exception:
        return []

@router.get("/load_mcap")
async def load_mcap(
    file_path_or_s3_url: str,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """加载MCAP文件 - 支持本地文件路径或S3 URL (s3://bucket/key)
    
    参数:
    - file_path_or_s3_url: 本地文件路径或S3 URL (s3://bucket/key)
    
    每个用户独立存储MCAP读取器，支持多用户并发使用
    """
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    user_id = current_user.id
    
    if not file_path_or_s3_url:
        raise HTTPException(status_code=400, detail="请提供 file_path_or_s3_url 参数")
    global mcap_readers, mcap_temp_files
    
    try:
        # 关闭该用户之前打开的读取器
        if user_id in mcap_readers:
            old_reader = mcap_readers[user_id]
            try:
                old_reader.close()
            except Exception:
                pass
            del mcap_readers[user_id]
        
        # 清理该用户之前的临时文件
        if user_id in mcap_temp_files:
            old_temp_file = mcap_temp_files[user_id]
            if old_temp_file and os.path.exists(old_temp_file) and old_temp_file != file_path_or_s3_url:
                try:
                    os.remove(old_temp_file)
                    logger.info(f"已清理用户 {user_id} 的旧临时文件: {old_temp_file}")
                except Exception:
                    pass
        
        local_file_path = None
        is_s3_source = False
        
        # 判断是S3 URL还是本地路径
        if file_path_or_s3_url.startswith("s3://"):
            # 从S3下载MCAP文件
            is_s3_source = True
            logger.info(f"从S3加载MCAP文件: {file_path_or_s3_url} (用户ID: {user_id})")
            local_file_path = await download_mcap_from_s3_for_user(file_path_or_s3_url, user_id)
        else:
            # 本地文件路径
            local_file_path = file_path_or_s3_url
            
            # 处理相对路径 - 如果是相对路径，尝试从当前文件所在目录查找
            if not local_file_path.startswith('/') and not local_file_path.startswith('C:'):
                # 先尝试相对于当前 Python 文件所在目录
                current_dir = Path(__file__).parent
                potential_path = current_dir / local_file_path
                if potential_path.exists():
                    local_file_path = str(potential_path)
                else:
                    # 再尝试相对于项目根目录
                    parent_dir = current_dir.parent.parent
                    potential_path = parent_dir / local_file_path
                    if potential_path.exists():
                        local_file_path = str(potential_path)
                    else:
                        # 最后尝试相对于 api 目录
                        api_dir = current_dir.parent
                        potential_path = api_dir / local_file_path
                        if potential_path.exists():
                            local_file_path = str(potential_path)
            
            if not Path(local_file_path).exists():
                raise HTTPException(status_code=404, detail=f"MCAP文件不存在: {local_file_path}")
        
        # 加载MCAP文件
        logger.info(f"加载MCAP文件: {local_file_path} (用户ID: {user_id})")
        mcap_reader = McapReader(local_file_path)
        
        # 基于user_id存储读取器和临时文件路径
        mcap_readers[user_id] = mcap_reader
        if is_s3_source:
            mcap_temp_files[user_id] = local_file_path
        else:
            # 本地文件不需要存储临时路径
            mcap_temp_files.pop(user_id, None)
        
        return {
            "success": True,
            "message": "MCAP文件加载成功",
            "source": "s3" if is_s3_source else "local",
            "file_info": {
                "duration_sec": mcap_reader.file_info.duration_sec,
                "video_fps": mcap_reader.file_info.video_fps,
                "video_frame_count": mcap_reader.file_info.video_frame_count,
                "video_topics": mcap_reader.file_info.video_topics
            },
            "annotations": _serialize_annotations_from_reader(mcap_reader)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.info(f"加载MCAP文件失败: {e}")
        import traceback
        logger.info(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"加载MCAP文件失败: {str(e)}")


@router.get("/get_all_topics")
async def get_all_topics(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取所有视频topic（支持多用户并发）"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    user_id = current_user.id
    
    global mcap_readers
    
    if user_id not in mcap_readers:
        raise HTTPException(status_code=400, detail="请先加载MCAP文件（调用 /load_mcap 接口）")
    
    mcap_reader = mcap_readers[user_id]
    return {
        "success": True,
        "topics": mcap_reader.video_topics
    }

@router.get("/get_annotations")
async def get_annotations(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取MCAP文件中的注释列表（支持多用户并发）"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    user_id = current_user.id
    
    global mcap_readers
    if user_id not in mcap_readers:
        raise HTTPException(status_code=400, detail="请先加载MCAP文件（调用 /load_mcap 接口）")
    
    mcap_reader = mcap_readers[user_id]
    return {
        "success": True,
        "annotations": _serialize_annotations_from_reader(mcap_reader)
    }


@router.get("/view_mcap")
async def view_mcap_root():
    """返回MCAP查看器主页面"""
    # 使用绝对路径确保能找到HTML文件
    html_path = Path(__file__).parent / "video_player.html"
    if html_path.exists():
        return HTMLResponse(content=open(html_path, "r", encoding="utf-8").read())
    else:
        raise HTTPException(status_code=404, detail="MCAP查看器页面不存在")


@router.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket, token: Optional[str] = None):
    """WebSocket实时流式传输（支持多用户并发）
    
    可选查询参数:
    - token: JWT token，用于识别用户身份并获取对应的MCAP读取器
    客户端可以通过以下方式传递token:
    1. 查询参数: ws://host/ws/stream?token=xxx
    2. 在start_stream消息中包含token或user_id字段
    """
    from fastapi import Query
    from common.database import SessionLocal
    
    logger.info(f"WebSocket连接请求: {websocket.client if websocket.client else 'unknown'}")
    
    # 尝试从查询参数获取token并解析user_id（从websocket.query_params获取）
    user_id = None
    query_token = websocket.query_params.get("token") if websocket.query_params else None
    if query_token:
        token = query_token
    elif token:
        # 如果函数参数中有token，使用它
        pass
    else:
        token = None
    
    if token:
        try:
            db = SessionLocal()
            try:
                current_user = get_current_user(token, db)
                user_id = current_user.id
                websocket_manager.websocket_users[websocket] = user_id
                logger.info(f"WebSocket连接已识别用户: user_id={user_id}")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"WebSocket token验证失败: {e}，将使用连接对象作为标识")
    
    try:
        await websocket_manager.connect(websocket)
        logger.info("WebSocket连接已建立，等待客户端消息...")
        
        # 发送连接成功消息
        await websocket_manager.send_personal_message(json.dumps({
            "type": "connected",
            "message": "WebSocket连接已建立" + (f"，用户ID: {user_id}" if user_id else "")
        }), websocket)
        
        while True:
            try:
                # 等待客户端消息（如果连接断开，receive_text 会抛出 WebSocketDisconnect）
                data = await websocket.receive_text()
                logger.info(f"收到WebSocket消息: {data[:200]}...")  # 只打印前200字符，避免日志过长
                
                try:
                    message = json.loads(data)
                    logger.info(f"解析后的消息类型: {message.get('action', 'unknown')}")
                except json.JSONDecodeError as e:
                    logger.error(f"JSON解析失败: {e}, 原始数据: {data[:100]}")
                    await websocket_manager.send_personal_message(json.dumps({
                        "type": "error",
                        "message": f"消息格式错误: {str(e)}"
                    }), websocket)
                    continue
                
                action = message.get("action")
                
                if action == "start_stream":
                    topic = message.get("topic")
                    if not topic:
                        logger.error("缺少topic参数")
                        await websocket_manager.send_personal_message(json.dumps({
                            "type": "error",
                            "message": "缺少topic参数"
                        }), websocket)
                        continue
                    
                    # 尝试从消息中获取token或user_id（如果WebSocket连接时未提供）
                    stream_user_id = user_id
                    if not stream_user_id and websocket in websocket_manager.websocket_users:
                        stream_user_id = websocket_manager.websocket_users[websocket]
                    
                    # 如果消息中包含token，尝试解析获取user_id
                    if not stream_user_id and message.get("token"):
                        try:
                            db = SessionLocal()
                            try:
                                current_user = get_current_user(message.get("token"), db)
                                stream_user_id = current_user.id
                                websocket_manager.websocket_users[websocket] = stream_user_id
                                logger.info(f"从消息中获取到user_id: {stream_user_id}")
                            finally:
                                db.close()
                        except Exception as e:
                            logger.warning(f"从消息token解析user_id失败: {e}")
                    
                    # 如果消息中直接包含user_id，使用它
                    if message.get("user_id"):
                        stream_user_id = message.get("user_id")
                        websocket_manager.websocket_users[websocket] = stream_user_id
                    
                    fps = message.get("fps", 30)
                    max_frames = message.get("max_frames", 1000)
                    max_duration_seconds = message.get("max_duration_seconds", None)
                    
                    # 限制最大帧数，避免内存问题
                    max_frames = min(max_frames, 2000)  # 最大2000帧
                    # 限制最大时长，避免传输时间过长（最大10分钟）
                    if max_duration_seconds is not None:
                        max_duration_seconds = min(max_duration_seconds, 600)  # 最大600秒（10分钟）
                    
                    logger.info(f"开始流式传输 - Topic: {topic}, FPS: {fps}, Max Frames: {max_frames}, Max Duration: {max_duration_seconds}秒, User ID: {stream_user_id}")
                    
                    # 初始化该 WebSocket 的任务字典（如果不存在）
                    if websocket not in websocket_manager.streaming_tasks:
                        websocket_manager.streaming_tasks[websocket] = {}
                    
                    # 检查该 topic 是否已有正在运行的任务，如果有则先取消
                    if topic in websocket_manager.streaming_tasks[websocket]:
                        old_task = websocket_manager.streaming_tasks[websocket][topic]
                        try:
                            old_task.cancel()
                            await asyncio.wait_for(old_task, timeout=1.0)
                        except (asyncio.CancelledError, asyncio.TimeoutError):
                            pass
                        finally:
                            if topic in websocket_manager.streaming_tasks[websocket]:
                                del websocket_manager.streaming_tasks[websocket][topic]
                    
                    # 启动新的流式传输任务（允许多个任务并行运行，每个 topic 一个任务）
                    task = asyncio.create_task(stream_video_frames(websocket, topic, fps, max_frames, max_duration_seconds, user_id=stream_user_id))
                    websocket_manager.streaming_tasks[websocket][topic] = task
                    logger.info(f"流式传输任务已启动，Topic: {topic} (当前活跃任务数: {len(websocket_manager.streaming_tasks[websocket])})")
                    
                    # 发送确认消息
                    await websocket_manager.send_personal_message(json.dumps({
                        "type": "started",
                        "message": f"流式传输已启动: {topic}",
                        "topic": topic
                    }), websocket)
                    
                elif action == "stop_stream":
                    stop_topic = message.get("topic")  # 支持停止特定 topic 或停止所有
                    logger.info(f"收到停止流式传输命令，Topic: {stop_topic or 'all'}")
                    
                    if websocket in websocket_manager.streaming_tasks:
                        if stop_topic:
                            # 停止指定 topic 的任务
                            if stop_topic in websocket_manager.streaming_tasks[websocket]:
                                task = websocket_manager.streaming_tasks[websocket][stop_topic]
                                try:
                                    task.cancel()
                                    try:
                                        await asyncio.wait_for(task, timeout=1.0)
                                    except (asyncio.CancelledError, asyncio.TimeoutError):
                                        pass
                                finally:
                                    if stop_topic in websocket_manager.streaming_tasks[websocket]:
                                        del websocket_manager.streaming_tasks[websocket][stop_topic]
                                logger.info(f"流式传输任务已停止，Topic: {stop_topic}")
                                
                                await websocket_manager.send_personal_message(json.dumps({
                                    "type": "stopped",
                                    "message": f"流式传输已停止，Topic: {stop_topic}",
                                    "topic": stop_topic
                                }), websocket)
                            else:
                                logger.warning(f"没有正在运行的流式传输任务，Topic: {stop_topic}")
                        else:
                            # 停止所有任务
                            tasks_to_stop = list(websocket_manager.streaming_tasks[websocket].items())
                            for topic, task in tasks_to_stop:
                                try:
                                    task.cancel()
                                    try:
                                        await asyncio.wait_for(task, timeout=1.0)
                                    except (asyncio.CancelledError, asyncio.TimeoutError):
                                        pass
                                finally:
                                    if topic in websocket_manager.streaming_tasks[websocket]:
                                        del websocket_manager.streaming_tasks[websocket][topic]
                            
                            # 如果所有任务都停止了，清理字典
                            if not websocket_manager.streaming_tasks[websocket]:
                                del websocket_manager.streaming_tasks[websocket]
                            
                            logger.info(f"所有流式传输任务已停止 (共 {len(tasks_to_stop)} 个)")
                            
                            await websocket_manager.send_personal_message(json.dumps({
                                "type": "stopped",
                                "message": f"所有流式传输任务已停止 (共 {len(tasks_to_stop)} 个)"
                            }), websocket)
                    else:
                        logger.warning("没有正在运行的流式传输任务")
                        
                else:
                    logger.warning(f"未知的action: {action}")
                    await websocket_manager.send_personal_message(json.dumps({
                        "type": "error",
                        "message": f"未知的action: {action}"
                    }), websocket)
                    
            except WebSocketDisconnect:
                logger.info("WebSocket客户端断开连接（在消息处理中）")
                break
            except asyncio.CancelledError:
                logger.info("WebSocket任务被取消")
                break
            except RuntimeError as e:
                # RuntimeError 可能包含连接状态错误
                error_str = str(e)
                if "not connected" in error_str.lower() or "Need to call \"accept\"" in error_str:
                    logger.info("WebSocket连接已断开，退出消息循环")
                    break
                else:
                    logger.error(f"处理WebSocket消息时发生运行时错误: {e}", exc_info=True)
                    # 尝试发送错误消息，但如果连接已断开则忽略
                    try:
                        await websocket_manager.send_personal_message(json.dumps({
                            "type": "error",
                            "message": f"处理消息时发生错误: {str(e)}"
                        }), websocket)
                    except:
                        pass  # 如果发送失败，连接可能已断开
            except Exception as e:
                logger.error(f"处理WebSocket消息时发生错误: {e}", exc_info=True)
                # 尝试发送错误消息，但如果连接已断开则忽略
                try:
                    await websocket_manager.send_personal_message(json.dumps({
                        "type": "error",
                        "message": f"处理消息时发生错误: {str(e)}"
                    }), websocket)
                except:
                    pass  # 如果发送失败，可能是连接已断开
                    
    except WebSocketDisconnect:
        logger.info("WebSocket客户端主动断开连接")
        websocket_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket连接错误: {e}", exc_info=True)
        websocket_manager.disconnect(websocket)

async def stream_video_frames(websocket: WebSocket, topic: str, fps: int, max_frames: int, max_duration_seconds: Optional[float] = None, user_id: Optional[int] = None):
    """流式传输视频帧，默认使用低质量压缩（支持多用户并发）
    
    Args:
        websocket: WebSocket连接
        topic: 视频topic
        fps: 帧率
        max_frames: 最大帧数限制
        max_duration_seconds: 最大传输时长（秒），None表示不限制时间
        user_id: 用户ID，用于获取对应的MCAP读取器
    """
    global mcap_readers
    
    logger.info(f"开始流式传输函数 - Topic: {topic}, FPS: {fps}, Max Frames: {max_frames}, Max Duration: {max_duration_seconds}秒, User ID: {user_id}")
    # 打印图像编码配置（从encode_image_to_base64函数中获取实际配置）
    max_image_size_mb = 10  # 与encode_image_to_base64函数中的限制保持一致
    jpeg_quality = 50  # 与encode_image_to_base64函数中的质量保持一致
    logger.info(f"使用默认低质量压缩 (JPEG质量: {jpeg_quality}, 最大图像大小: {max_image_size_mb}MB)")
    
    # 根据user_id获取对应的MCAP读取器
    mcap_reader = None
    if user_id is not None:
        mcap_reader = mcap_readers.get(user_id)
    else:
        # 如果未提供user_id，尝试从WebSocket映射中获取
        if websocket in websocket_manager.websocket_users:
            user_id = websocket_manager.websocket_users[websocket]
            mcap_reader = mcap_readers.get(user_id)
    
    if mcap_reader is None:
        error_msg = f"MCAP文件未加载（用户ID: {user_id}），请先调用 /datafile/load_mcap 接口加载MCAP文件"
        logger.error(error_msg)
        try:
            await websocket_manager.send_personal_message(json.dumps({
                "type": "error",
                "message": error_msg
            }), websocket)
        except:
            pass  # 如果发送失败，可能是连接已断开
        return
    
    logger.info(f"MCAP文件路径: {mcap_reader.mcap_path} (用户ID: {user_id})")
    logger.info(f"可用的video_topics: {mcap_reader.video_topics}")
    
    if topic not in mcap_reader.video_topics:
        error_msg = f"Topic {topic} 不存在，可用的topics: {list(mcap_reader.video_topics)[:5]}..."
        logger.error(error_msg)
        try:
            await websocket_manager.send_personal_message(json.dumps({
                "type": "error", 
                "message": error_msg
            }), websocket)
        except:
            pass  # 如果发送失败，可能是连接已断开
        return
    
    try:
        frame_count = 0
        frame_interval = 1.0 / fps  # 帧间隔（秒）
        start_time = time.time()  # 记录开始时间
        last_frame_time = start_time  # 用于动态调整帧间隔
        total_transmitted_kb = 0  # 累计总传输的数据量（KB）
        
        # 减少sleep的使用，只在需要控制帧率时使用
        need_frame_rate_control = frame_interval > 0.01  # 只有帧率低于100fps时才需要控制
        
        logger.info(f"帧间隔: {frame_interval} 秒")
        logger.info(f"开始读取MCAP文件中的消息...")
        
        with open(mcap_reader.mcap_path, "rb") as f:
            reader = make_reader(f, decoder_factories=[DecoderFactory()])
            
            message_count = 0
            for schema, channel, message, proto_msg in reader.iter_decoded_messages(topics=[topic]):
                message_count += 1
                
                # 检查是否达到最大帧数限制
                if frame_count >= max_frames:
                    logger.info(f"达到最大帧数限制 {max_frames}，停止处理")
                    break
                
                # 检查是否超过最大传输时长（每10帧或前几帧检查一次以优化性能）
                if max_duration_seconds is not None and (frame_count < 10 or frame_count % 10 == 0):
                    elapsed_time = time.time() - start_time
                    if elapsed_time >= max_duration_seconds:
                        logger.info(f"达到最大传输时长限制 {max_duration_seconds}秒（已传输 {elapsed_time:.1f}秒），停止处理")
                        break
                
                try:
                    # 处理视频消息（移除详细日志）
                    frame = mcap_reader._process_video_message(schema, channel, message, proto_msg)
                    
                    if frame is not None:
                        # 增加图像大小限制（从20MB提升到30MB），允许处理更大的原始帧
                        if frame.nbytes > 30 * 1024 * 1024:  # 30MB限制
                            continue
                        
                        # 编码图像为base64（移除详细日志）
                        img_base64 = encode_image_to_base64(frame)
                        if img_base64:
                            # 简化计算，只在需要时计算压缩信息（每100帧计算一次用于统计）
                            if frame_count % 100 == 0:
                                base64_size_kb = len(img_base64) / 1024
                                original_size_kb = frame.nbytes / 1024
                                compression_ratio = (1 - len(img_base64) / frame.nbytes) * 100
                            else:
                                # 大部分情况下不计算，节省CPU
                                base64_size_kb = 0
                                original_size_kb = 0
                                compression_ratio = 0
                            
                            frame_data = {
                                "type": "frame",
                                "frame_index": frame_count,
                                "timestamp": message.log_time,
                                "topic": topic,
                                "image_data": img_base64,
                                "shape": frame.shape,
                                "dtype": str(frame.dtype),
                                "original_size_kb": round(original_size_kb, 1) if base64_size_kb > 0 else None,
                                "compressed_size_kb": round(base64_size_kb, 1) if base64_size_kb > 0 else None,
                                "compression_ratio": round(compression_ratio, 1) if compression_ratio > 0 else None
                            }
                            
                            # 发送帧数据（移除详细日志）
                            json_str = json.dumps(frame_data)
                            await websocket_manager.send_personal_message(json_str, websocket)
                            # 累计传输的数据量（JSON字符串大小）
                            total_transmitted_kb += len(json_str) / 1024
                            frame_count += 1
                            
                            # 动态控制帧率 - 根据实际处理速度调整
                            if need_frame_rate_control:
                                current_time = time.time()
                                actual_interval = current_time - last_frame_time
                                last_frame_time = current_time
                                
                                # 如果处理速度慢于目标帧率，不sleep；如果快于目标帧率，才sleep
                                if actual_interval < frame_interval:
                                    sleep_time = frame_interval - actual_interval
                                    if sleep_time > 0.001:  # 只sleep超过1ms的情况
                                        await asyncio.sleep(min(sleep_time, 0.05))
                            
                            # 优化内存清理频率（减少频率）
                            if frame_count % 100 == 0 and frame_count > 200:
                                import gc
                                gc.collect()
                            
                            # 减少日志输出频率（每100帧输出一次）
                            if frame_count % 100 == 0:
                                elapsed = time.time() - start_time
                                current_fps = frame_count / elapsed if elapsed > 0 else 0
                                # 计算平均每帧传输的数据量
                                avg_size_per_frame_kb = total_transmitted_kb / frame_count if frame_count > 0 else 0
                                logger.info(f"已流式传输 {frame_count} 帧，耗时 {elapsed:.1f}秒，平均帧率: {current_fps:.1f} FPS，已传输: {total_transmitted_kb:.2f}KB (平均每帧: {avg_size_per_frame_kb:.2f}KB)")
                
                except asyncio.CancelledError:
                    logger.info("检测到任务取消，停止读取帧...")
                    raise
                except Exception as e:
                    # 错误日志保留，但减少详细trace
                    if frame_count % 10 == 0:  # 每10帧才输出一次错误详情
                        logger.info(f"处理 {topic} 第 {frame_count} 帧时出错: {e}")
                    continue
        
        elapsed_time = time.time() - start_time
        # 获取视频总时长
        video_duration = mcap_reader.file_info.duration_sec if mcap_reader.file_info else 0
        # 计算总传输数据量（KB和MB）
        total_transmitted_mb = total_transmitted_kb / 1024
        logger.info(f"流式传输结束 - 总消息数: {message_count}, 成功帧数: {frame_count}, 总耗时: {elapsed_time:.2f}秒, 视频时长: {video_duration:.2f}秒, 总传输数据: {total_transmitted_kb:.2f}KB ({total_transmitted_mb:.2f}MB)")
        
        # 发送完成消息
        await websocket_manager.send_personal_message(json.dumps({
            "type": "complete",
            "message": f"流式传输完成，共 {frame_count} 帧，处理了 {message_count} 条消息，耗时 {elapsed_time:.2f}秒，视频时长: {video_duration:.2f}秒，总传输数据: {total_transmitted_kb:.2f}KB ({total_transmitted_mb:.2f}MB)"
        }), websocket)
        
    except asyncio.CancelledError:
        logger.info("流式传输任务已取消")
        # 可选：通知前端已停止
        try:
            await websocket_manager.send_personal_message(json.dumps({
                "type": "stopped",
                "message": "已停止流式传输"
            }), websocket)
        except Exception:
            pass
        return
    except Exception as e:
        logger.exception(f"流式传输失败: {e}")
        await websocket_manager.send_personal_message(json.dumps({
            "type": "error",
            "message": f"流式传输失败: {str(e)}"
        }), websocket)