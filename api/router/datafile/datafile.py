from fastapi import APIRouter, Depends, HTTPException, status, Header, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
import os
import uuid
import zipfile
import tempfile
from datetime import datetime
from mcap.reader import make_reader
import io
from common.database import get_db
from common import models, schemas
from router.user.auth import get_current_user

router = APIRouter()

# 配置上传目录
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)


def parse_mcap_duration(file_content: bytes) -> Optional[int]:
    """
    解析MCAP文件获取时长（毫秒）
    """
    try:
        # 创建内存中的文件对象
        file_obj = io.BytesIO(file_content)
        
        # 使用MCAP reader解析文件
        reader = make_reader(file_obj)
        start_time = None
        end_time = None
        
        # 遍历所有消息，找到最早和最晚的时间戳
        for message in reader:
            timestamp = message.log_time
            
            if start_time is None or timestamp < start_time:
                start_time = timestamp
            
            if end_time is None or timestamp > end_time:
                end_time = timestamp
        
        # 计算时长（纳秒转毫秒）
        if start_time is not None and end_time is not None:
            duration_ns = end_time - start_time
            duration_ms = duration_ns // 1_000_000  # 纳秒转毫秒
            return int(duration_ms)
        
        return None
            
    except Exception as e:
        print(f"解析MCAP文件时长失败: {e}")
        return None


@router.post("/upload_mcap", response_model=schemas.DataFileOut)
async def upload_mcap_file(
    task_id: int = Form(..., description="任务ID"),
    device_id: int = Form(..., description="设备ID"),
    label_ids: str = Form(default="", description="标签ID列表，用逗号分隔，如：1,2,3"),
    file: UploadFile = File(..., description="MCAP文件"),
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """上传MCAP文件 - 只有管理员可以上传文件"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以上传文件
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以上传文件"
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
        
        # 解析MCAP文件获取时长 60s默认时长
        duration_ms = 60
        
        # 生成唯一文件名
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        
        # 保存文件
        with open(file_path, "wb") as buffer:
            buffer.write(content)
        
        # 生成下载URL（这里使用相对路径，实际部署时应该使用完整的URL）
        download_url = f"/uploads/{unique_filename}"
        
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
        
        return db_datafile
        
    except Exception as e:
        # 如果数据库操作失败，删除已上传的文件
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传文件时发生错误: {str(e)}"
        )


@router.get("/get_all_datafiles", response_model=List[schemas.DataFileOut])
def get_all_datafiles(
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """获取所有数据文件列表 - 只有管理员可以查看所有文件"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看所有文件
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看所有文件"
        )
    
    datafiles = db.query(models.DataFile).order_by(models.DataFile.id.asc()).all()
    return datafiles


@router.get("/get_datafile_by_id", response_model=schemas.DataFileOut)
def get_datafile_by_id(
    datafile_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """根据ID获取数据文件信息 - 只有管理员可以查看文件信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看文件信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看文件信息"
        )
    
    datafile = db.query(models.DataFile).filter(models.DataFile.id == datafile_id).first()
    if not datafile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据文件不存在"
        )
    return datafile


@router.post("/update_datafile", response_model=schemas.DataFileOut)
def update_datafile(
    datafile_update: schemas.DataFileUpdate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """更新数据文件信息 - 只有管理员可以更新文件信息"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以更新文件信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以更新文件信息"
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
    """删除数据文件 - 只有管理员可以删除文件"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以删除文件
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以删除文件"
        )
    
    # 查找数据文件
    datafile = db.query(models.DataFile).filter(models.DataFile.id == datafile_id).first()
    if not datafile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据文件不存在"
        )
    
    # 删除关联的数据文件标签映射
    data_file_labels_count = db.query(models.DataFileLabel).filter(models.DataFileLabel.data_file_id == datafile_id).count()
    if data_file_labels_count > 0:
        # 删除所有关联的标签映射
        db.query(models.DataFileLabel).filter(models.DataFileLabel.data_file_id == datafile_id).delete()
        print(f"已删除 {data_file_labels_count} 个关联的标签映射")
    
    # 删除物理文件
    file_path = datafile.download_url.replace("/uploads/", UPLOAD_DIR + "/")
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            # 记录错误但不阻止数据库删除
            print(f"删除物理文件失败: {e}")
    
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
    """下载单个数据文件 - 只有管理员可以下载文件"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以下载文件
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以下载文件"
        )
    
    # 查找数据文件
    datafile = db.query(models.DataFile).filter(models.DataFile.id == datafile_id).first()
    if not datafile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据文件不存在"
        )
    
    # 构建文件路径
    if datafile.download_url.startswith("/uploads/"):
        file_path = datafile.download_url.replace("/uploads/", UPLOAD_DIR + "/")
    else:
        file_path = os.path.join(UPLOAD_DIR, os.path.basename(datafile.download_url))
    
    print(f"下载文件路径: {file_path}")  # 调试信息
    
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"文件不存在于服务器上: {file_path}"
        )
    
    # 记录下载日志
    from common.operation_log_util import OperationLogUtil
    OperationLogUtil.log_file_download(
        db, current_user.username, 1, [datafile_id]
    )
    
    # 获取文件大小
    file_size = os.path.getsize(file_path)
    print(f"下载文件: {datafile.file_name}, 大小: {file_size} 字节")  # 调试信息
    
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
    """下载多个数据文件打包成ZIP - 只有管理员可以下载文件"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以下载文件
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以下载文件"
        )
    
    if not datafile_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请提供要下载的文件ID列表"
        )
    
    # 查找数据文件
    datafiles = db.query(models.DataFile).filter(models.DataFile.id.in_(datafile_ids)).all()
    if not datafiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到任何数据文件"
        )
    
    # 检查文件是否存在
    missing_files = []
    valid_files = []
    print(f"开始处理 {len(datafiles)} 个文件")  # 调试信息
    
    for datafile in datafiles:
        print(f"处理文件: {datafile.file_name}, URL: {datafile.download_url}")  # 调试信息
        
        # 处理文件路径，确保正确构建绝对路径
        if datafile.download_url.startswith("/uploads/"):
            file_path = datafile.download_url.replace("/uploads/", UPLOAD_DIR + "/")
        else:
            file_path = os.path.join(UPLOAD_DIR, os.path.basename(datafile.download_url))
        
        print(f"检查文件路径: {file_path}")  # 调试信息
        print(f"文件是否存在: {os.path.exists(file_path)}")  # 调试信息
        
        if os.path.exists(file_path):
            valid_files.append((datafile, file_path))
            print(f"文件添加成功: {datafile.file_name}")  # 调试信息
        else:
            missing_files.append(datafile.file_name)
            print(f"文件不存在: {file_path}")  # 调试信息
    
    if not valid_files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="所有文件都不存在于服务器上"
        )
    
    # 创建ZIP文件在内存中
    import io
    
    try:
        print(f"开始创建ZIP文件，包含 {len(valid_files)} 个文件")  # 调试信息
        
        # 创建内存中的ZIP文件
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for datafile, file_path in valid_files:
                print(f"添加文件到ZIP: {datafile.file_name} -> {file_path}")  # 调试信息
                # 使用原始文件名作为ZIP内的文件名
                zipf.write(file_path, datafile.file_name)
        
        # 获取ZIP文件大小
        zip_size = zip_buffer.tell()
        print(f"ZIP文件创建完成，大小: {zip_size} 字节")  # 调试信息
        
        if zip_size == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ZIP文件创建失败，文件大小为0"
            )
        
        # 生成ZIP文件名
        zip_filename = f"datafiles_{len(valid_files)}_files.zip"
        
        # 创建文件下载操作日志
        from common.operation_log_util import OperationLogUtil
        OperationLogUtil.log_file_download(
            db, current_user.username, len(valid_files), datafile_ids
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
        
        print(f"准备返回ZIP文件，大小: {zip_size} 字节，文件名: {zip_filename}")  # 调试信息
        
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
        print(f"创建ZIP文件时发生错误: {str(e)}")  # 详细错误日志
        import traceback
        print(f"错误堆栈: {traceback.format_exc()}")  # 完整错误堆栈
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
    """获取数据文件列表，支持分页和多条件查询 - 只有管理员可以查看"""
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：只有管理员可以查看文件信息
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以查看文件信息"
        )
    
    try:
        # 构建查询
        query = db.query(models.DataFile)
        
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
