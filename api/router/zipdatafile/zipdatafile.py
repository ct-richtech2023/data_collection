from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
import os
import uuid
import re
from common.permission_utils import PermissionUtils
from botocore.exceptions import ClientError

from common.database import get_db
from common import models, schemas
from common.operation_log_util import OperationLogUtil
from router.user.auth import get_current_user
from router.datafile.datafile import get_s3_client, build_s3_url, S3_BUCKET_NAME, parse_s3_url
from loguru import logger

router = APIRouter()

# 配置常量
S3_KEY_PREFIX = "zipfiles/"
PRESIGNED_URL_EXPIRES_IN = 3600  # 预签名URL有效期：1小时
ALLOWED_FILE_EXTENSIONS = {".zip"}


def _validate_file_name(file_name: str) -> None:
    """
    验证文件名安全性
    防止路径遍历攻击和非法字符
    """
    if not file_name or not file_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名不能为空"
        )
    
    # 检查是否包含路径分隔符（防止路径遍历）
    if os.sep in file_name or "/" in file_name or "\\" in file_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名不能包含路径分隔符"
        )
    
    # 检查危险字符
    dangerous_chars = ["..", "<", ">", ":", '"', "|", "?", "*"]
    if any(char in file_name for char in dangerous_chars):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名包含非法字符"
        )
    
    # 检查文件扩展名
    file_extension = os.path.splitext(file_name)[1].lower()
    if file_extension not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"只允许上传 {', '.join(ALLOWED_FILE_EXTENSIONS)} 文件"
        )


def _validate_s3_key(s3_key: str) -> None:
    """
    验证 S3 key 格式和安全性
    """
    if not s3_key or not s3_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="S3键不能为空"
        )
    
    # 检查前缀
    if not s3_key.startswith(S3_KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"S3键必须以 {S3_KEY_PREFIX} 开头"
        )
    
    # 检查危险字符
    if ".." in s3_key or "//" in s3_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="S3键包含非法字符"
        )
    
    # 验证格式：zipfiles/{uuid}.zip
    pattern = rf"^{re.escape(S3_KEY_PREFIX)}[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}\.zip$"
    if not re.match(pattern, s3_key, re.IGNORECASE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="S3键格式不正确"
        )


@router.post("/upload_zip", response_model=schemas.S3PresignedUploadResponse)
def upload_zip(
    request: schemas.ZipUploadRequest,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db)
):
    """
    获取 S3 预签名上传 URL
    前端使用此 URL 直接上传文件到 S3，上传完成后调用 /save_zip_file 接口保存文件信息
    
    注意：
    - URL 有效期：{PRESIGNED_URL_EXPIRES_IN} 秒
    - 只支持 .zip 文件
    """
    try:
        # 验证token并获取当前用户
        current_user = get_current_user(token, db)
        
        # 权限检查：检查上传操作权限
        if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "upload"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您没有ZIP文件上传权限"
            )

        logger.info(
            f"[Upload ZIP] 获取 S3 上传 URL | user_id={current_user.id} "
            f"filename={request.file_name}"
        )

        # 验证文件名安全性
        _validate_file_name(request.file_name)

        # 生成唯一的 S3 对象键
        file_extension = os.path.splitext(request.file_name)[1].lower()
        unique_key = f"{S3_KEY_PREFIX}{uuid.uuid4()}{file_extension}"

        # 获取 S3 客户端
        s3 = get_s3_client()

        # 生成预签名上传 URL
        try:
            presigned_url = s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": S3_BUCKET_NAME,
                    "Key": unique_key,
                    "ContentType": "application/zip",
                },
                ExpiresIn=PRESIGNED_URL_EXPIRES_IN,
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            logger.error(
                f"[Upload ZIP] S3 客户端错误 | user_id={current_user.id} "
                f"error_code={error_code} error={e}"
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="生成 S3 预签名 URL 失败，请稍后重试",
            )
        except Exception as e:
            logger.exception(f"[Upload ZIP] 生成预签名URL异常 | user_id={current_user.id} error={e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="生成 S3 预签名 URL 失败，请稍后重试",
            )

        # 构建下载 URL
        download_url = build_s3_url(S3_BUCKET_NAME, unique_key)

        logger.info(
            f"[Upload ZIP] S3 预签名 URL 生成成功 | key={unique_key} "
            f"user_id={current_user.id} expires_in={PRESIGNED_URL_EXPIRES_IN}s"
        )

        # 记录操作日志：请求上传 ZIP 文件
        try:
            OperationLogUtil.create_log(
                db=db,
                username=current_user.username,
                action="ZIP File Upload",
                content=f"User {current_user.username} requested to upload ZIP file {request.file_name}, S3 key: {unique_key}"
            )
        except Exception as e:
            # 操作日志记录失败不影响主流程，只记录警告
            logger.warning(f"[Upload ZIP] 记录操作日志失败: {e}")

        return schemas.S3PresignedUploadResponse(
            upload_url=presigned_url,
            s3_key=unique_key,
            download_url=download_url,
        )

    except HTTPException:
        # 已经构造好的 HTTPException 直接抛出
        raise
    except Exception as e:
        logger.exception(f"[Upload ZIP] 未知异常: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="生成 S3 上传 URL 失败，请稍后重试",
        )


@router.post("/update_zip_file_name_by_zip_datafile_id", response_model=schemas.ZipDataFileOut)
def update_zip_file_name(
    zip_datafile_id: int,
    file_name: str,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db),
):
    """
    更新 ZIP 文件名称
    """
    try:
        # 验证token并获取当前用户
        current_user = get_current_user(token, db)
        
        # 权限检查：检查更新操作权限
        if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "update"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您没有ZIP文件更新权限"
            )
        
        logger.info(
            f"[Update ZIP] 更新文件名称请求 | user_id={current_user.id} "
            f"zip_datafile_id={zip_datafile_id} file_name={file_name}"
        )
        
        # 更新ZIP文件名称
        zip_datafile = db.query(models.ZipDataFile).filter(
            models.ZipDataFile.id == zip_datafile_id
        ).first()
        if not zip_datafile:
            logger.warning(
                f"[Update ZIP] ZIP文件不存在 | user_id={current_user.id} "
                f"zip_datafile_id={zip_datafile_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ZIP文件不存在"
            )
        
        zip_datafile.file_name = file_name
        try:
            db.commit()
            db.refresh(zip_datafile)
        except Exception as e:
            logger.error(f"[Update ZIP] 更新文件名称失败: {e}")
            db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新文件名称失败，请稍后重试")

        logger.info(
            f"[Update ZIP] 文件名称更新成功 | zip_datafile_id={zip_datafile_id} "
            f"user_id={current_user.id}"
        )

        # 记录操作日志：更新ZIP文件名称
        try:
            OperationLogUtil.create_log(
                db=db,
                username=current_user.username,
                action="ZIP File Update",
                content=f"User {current_user.username} updated ZIP file name {file_name} (zip_datafile_id: {zip_datafile_id})"
            )
        except Exception as e:
            # 操作日志记录失败不影响主流程，只记录警告
            logger.warning(f"[Update ZIP] 记录操作日志失败: {e}")

        return schemas.ZipDataFileOut(
            id=zip_datafile.id,
            file_name=zip_datafile.file_name,
            file_size=zip_datafile.file_size,
            download_number=zip_datafile.download_number,
            download_url=zip_datafile.download_url,
            user_id=zip_datafile.user_id,
            create_time=zip_datafile.create_time,
            update_time=zip_datafile.update_time,
        )
    except HTTPException:
        # 已经构造好的 HTTPException 直接抛出
        raise
    except Exception as e:
        logger.exception(f"[Update ZIP] 未知异常: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新文件名称失败，请稍后重试",
        )


@router.post("/save_zip_file", response_model=schemas.ZipDataFileOut)
def save_zip_file(
    zip_datafile: schemas.ZipDataFileCreate,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db),
):
    """
    保存 ZIP 文件信息到数据库
    前端上传文件到 S3 后，调用此接口保存文件名称和 S3 对象信息

    流程：
    1. 校验用户身份
    2. 验证 s3_key 格式和安全性
    3. 使用 s3_key 调用 head_object 确认文件真实存在
    4. 检查是否已存在相同 download_url 的记录（防止重复保存）
    5. 使用 build_s3_url 构造 download_url
    6. 保存到数据库
    """
    # 验证token并获取当前用户
    current_user = get_current_user(token, db)
    
    # 权限检查：检查上传操作权限
    if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "upload"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您没有ZIP文件上传权限"
        )

    logger.info(
        f"[Save ZIP] 保存文件信息请求 | user_id={current_user.id} "
        f"filename={zip_datafile.file_name} s3_key={zip_datafile.s3_key}"
    )

    # 验证文件名和 s3_key 安全性
    _validate_file_name(zip_datafile.file_name)
    _validate_s3_key(zip_datafile.s3_key)

    s3 = get_s3_client()

    # 1. 校验 S3 上是否确实存在该对象
    try:
        s3.head_object(Bucket=S3_BUCKET_NAME, Key=zip_datafile.s3_key)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey"):
            logger.warning(
                f"[Save ZIP] S3 对象不存在 | user_id={current_user.id} "
                f"s3_key={zip_datafile.s3_key}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="S3 未找到对应文件，请确认已成功上传",
            )
        logger.error(
            f"[Save ZIP] 校验 S3 对象异常 | user_id={current_user.id} "
            f"error_code={error_code} error={e}"
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="校验 S3 文件状态失败，请稍后重试",
        )
    except Exception as e:
        logger.exception(f"[Save ZIP] 调用 S3 head_object 异常: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="校验 S3 文件状态失败，请稍后重试",
        )

    # 2. 由后端根据 s3_key 生成 download_url
    download_url = build_s3_url(S3_BUCKET_NAME, zip_datafile.s3_key)
    
    # 3. 检查是否已存在相同 download_url 的记录（防止重复保存）
    existing_file = db.query(models.ZipDataFile).filter(
        models.ZipDataFile.download_url == download_url
    ).first()
    
    if existing_file:
        logger.info(
            f"[Save ZIP] 文件已存在，返回已存在记录 | user_id={current_user.id} "
            f"s3_key={zip_datafile.s3_key} existing_id={existing_file.id}"
        )
        # 返回已存在的记录而不是创建新记录
        return schemas.ZipDataFileOut(
            id=existing_file.id,
            file_name=existing_file.file_name,
            download_number=existing_file.download_number,
            download_url=existing_file.download_url,
            user_id=existing_file.user_id,
            create_time=existing_file.create_time,
            update_time=existing_file.update_time,
        )

    # 4. 保存数据库记录
    try:
        db_zip_datafile = models.ZipDataFile(
            file_name=zip_datafile.file_name,
            file_size=zip_datafile.file_size,
            download_url=download_url,
            download_number=0,  # 初始下载次数为 0
            user_id=current_user.id,
        )

        db.add(db_zip_datafile)
        try:
            db.commit()
            db.refresh(db_zip_datafile)
        except Exception as e:
            logger.error(f"[Save ZIP] 保存文件信息失败: {e}")
            db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="保存文件信息失败，请稍后重试")

        logger.info(
            f"[Save ZIP] 文件信息保存成功 | zip_datafile_id={db_zip_datafile.id} "
            f"user_id={current_user.id}"
        )

        # 记录操作日志：ZIP 文件上传成功
        try:
            OperationLogUtil.create_log(
                db=db,
                username=current_user.username,
                action="ZIP File Upload",
                content=f"User {current_user.username} successfully uploaded ZIP file {zip_datafile.file_name}, zip_datafile_id: {db_zip_datafile.id}, S3 key: {zip_datafile.s3_key}"
            )
        except Exception as e:
            # 操作日志记录失败不影响主流程，只记录警告
            logger.warning(f"[Save ZIP] 记录操作日志失败: {e}")

        return schemas.ZipDataFileOut(
            id=db_zip_datafile.id,
            file_name=db_zip_datafile.file_name,
            file_size=db_zip_datafile.file_size,
            download_number=db_zip_datafile.download_number,
            download_url=db_zip_datafile.download_url,
            user_id=db_zip_datafile.user_id,
            create_time=db_zip_datafile.create_time,
            update_time=db_zip_datafile.update_time,
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        logger.exception(f"[Save ZIP] 保存文件信息失败: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存文件信息失败，请稍后重试",
        )


@router.post("/get_download_url_by_zip_datafile_id")
def get_download_url_by_zip_datafile_id(
    zip_datafile_id: int,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db),
):
    """
    获取ZIP文件的S3预签名下载URL
    
    流程：
    1. 验证用户身份和下载权限
    2. 查找ZIP文件记录
    3. 解析S3 URL获取bucket和key
    4. 生成预签名下载URL
    5. 增加下载次数
    6. 记录操作日志
    
    返回：
    - download_url: S3预签名下载URL（前端可直接使用此URL下载文件）
    - expires_in: URL有效期（秒）
    """
    try:
        # 验证token并获取当前用户
        current_user = get_current_user(token, db)
        
        # 权限检查：检查下载操作权限
        if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "download"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您没有ZIP文件下载权限"
            )

        logger.info(
            f"[Download ZIP] 获取下载URL请求 | user_id={current_user.id} "
            f"zip_datafile_id={zip_datafile_id}"
        )

        # 查找ZIP文件
        zip_datafile = db.query(models.ZipDataFile).filter(
            models.ZipDataFile.id == zip_datafile_id
        ).first()
        if not zip_datafile:
            logger.warning(
                f"[Download ZIP] ZIP文件不存在 | user_id={current_user.id} "
                f"zip_datafile_id={zip_datafile_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ZIP文件不存在"
            )

        # 解析S3 URL
        try:
            bucket, key = parse_s3_url(zip_datafile.download_url)
        except ValueError as e:
            logger.error(
                f"[Download ZIP] S3 URL解析失败 | user_id={current_user.id} "
                f"zip_datafile_id={zip_datafile_id} download_url={zip_datafile.download_url} error={e}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效的S3 URL格式: {zip_datafile.download_url}"
            )

        # 获取S3客户端
        s3 = get_s3_client()

        # 生成预签名下载URL
        try:
            presigned_download_url = s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                },
                ExpiresIn=PRESIGNED_URL_EXPIRES_IN,
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            logger.error(
                f"[Download ZIP] 生成预签名URL失败 | user_id={current_user.id} "
                f"zip_datafile_id={zip_datafile_id} bucket={bucket} key={key} "
                f"error_code={error_code} error={e}"
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="生成下载URL失败，请稍后重试",
            )
        except Exception as e:
            logger.exception(f"[Download ZIP] 生成预签名URL异常 | user_id={current_user.id} error={e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="生成下载URL失败，请稍后重试",
            )

        # 增加下载次数
        old_download_number = zip_datafile.download_number
        zip_datafile.download_number += 1
        
        try:
            db.commit()
            db.refresh(zip_datafile)
        except Exception as e:
            logger.error(
                f"[Download ZIP] 更新下载次数失败 | user_id={current_user.id} "
                f"zip_datafile_id={zip_datafile_id} error={e}"
            )
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="更新下载次数失败，请稍后重试"
            )

        logger.info(
            f"[Download ZIP] 预签名URL生成成功 | user_id={current_user.id} "
            f"zip_datafile_id={zip_datafile_id} filename={zip_datafile.file_name} "
            f"download_number: {old_download_number} -> {zip_datafile.download_number} "
            f"expires_in={PRESIGNED_URL_EXPIRES_IN}s"
        )

        # 记录操作日志：ZIP文件下载
        try:
            OperationLogUtil.create_log(
                db=db,
                username=current_user.username,
                action="ZIP File Download",
                content=f"User {current_user.username} requested download URL for ZIP file {zip_datafile.file_name} (zip_datafile_id: {zip_datafile_id}, download_number: {zip_datafile.download_number})"
            )
        except Exception as e:
            # 操作日志记录失败不影响主流程，只记录警告
            logger.warning(f"[Download ZIP] 记录操作日志失败: {e}")

        return {
            "download_url": presigned_download_url,
            "expires_in": PRESIGNED_URL_EXPIRES_IN,
            "file_name": zip_datafile.file_name,
            "file_size": zip_datafile.file_size,
            "zip_datafile_id": zip_datafile_id,
        }

    except HTTPException:
        # 已经构造好的 HTTPException 直接抛出
        raise
    except Exception as e:
        logger.exception(f"[Download ZIP] 未知异常: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取下载URL失败，请稍后重试"
        )



# @router.post("/add_download_number_by_zip_datafile_id")
# def add_download_number_by_zip_datafile_id(
#     zip_datafile_id: int,
#     token: str = Header(..., description="JWT token"),
#     db: Session = Depends(get_db),
# ):
    """
    增加ZIP文件下载次数
    
    流程：
    1. 验证用户身份和下载权限
    2. 查找ZIP文件记录
    3. 增加下载次数并保存
    4. 记录操作日志
    """
    try:
        # 验证token并获取当前用户
        current_user = get_current_user(token, db)
        
        # 权限检查：检查下载操作权限
        if not PermissionUtils.check_operation_permission(db, current_user.id, "data", "download"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="您没有ZIP文件下载权限"
            )

        logger.info(
            f"[Download ZIP] 增加下载次数请求 | user_id={current_user.id} "
            f"zip_datafile_id={zip_datafile_id}"
        )

        # 查找ZIP文件
        zip_datafile = db.query(models.ZipDataFile).filter(
            models.ZipDataFile.id == zip_datafile_id
        ).first()
        if not zip_datafile:
            logger.warning(
                f"[Download ZIP] ZIP文件不存在 | user_id={current_user.id} "
                f"zip_datafile_id={zip_datafile_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ZIP文件不存在"
            )

        # 增加ZIP文件下载次数
        old_download_number = zip_datafile.download_number
        zip_datafile.download_number += 1
        
        try:
            db.commit()
            db.refresh(zip_datafile)
        except Exception as e:
            logger.error(f"[Download ZIP] 更新下载次数失败: {e}")
            db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新下载次数失败，请稍后重试")

        logger.info(
            f"[Download ZIP] 下载次数更新成功 | user_id={current_user.id} "
            f"zip_datafile_id={zip_datafile_id} filename={zip_datafile.file_name} "
            f"download_number: {old_download_number} -> {zip_datafile.download_number}"
        )

        # 记录操作日志：ZIP文件下载
        try:
            OperationLogUtil.create_log(
                db=db,
                username=current_user.username,
                action="ZIP File Download",
                content=f"User {current_user.username} downloaded ZIP file {zip_datafile.file_name} (zip_datafile_id: {zip_datafile_id}, download_number: {zip_datafile.download_number})"
            )
        except Exception as e:
            # 操作日志记录失败不影响主流程，只记录警告
            logger.warning(f"[Download ZIP] 记录操作日志失败: {e}")

        return {
            "message": f"ZIP文件 {zip_datafile.file_name} 增加下载次数成功",
            "zip_datafile_id": zip_datafile_id,
            "file_name": zip_datafile.file_name,
            "download_number": zip_datafile.download_number,
        }

    except HTTPException:
        # 已经构造好的 HTTPException 直接抛出
        raise
    except Exception as e:
        logger.exception(f"[Download ZIP] 未知异常: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="增加下载次数失败，请稍后重试"
        )


@router.post("/get_zip_datafiles_with_pagination")
def get_zip_datafiles_with_pagination(
    request_data: schemas.ZipDataFileQuery,
    token: str = Header(..., description="JWT token"),
    db: Session = Depends(get_db),
):
    """
    获取ZIP文件列表，支持分页和条件查询
    
    流程：
    1. 验证用户身份
    2. 根据条件构建查询（支持按ID、文件名、用户ID过滤）
    3. 应用分页
    4. 返回结果和分页信息
    """
    try:
        # 验证token并获取当前用户
        current_user = get_current_user(token, db)
        
        logger.info(
            f"[ZIP File][Page] 请求 | user_id={current_user.id} "
            f"filters={{'zip_datafile_id': {'set' if request_data.zip_datafile_id else 'unset'}, "
            f"'file_name': {'set' if request_data.file_name else 'unset'}, "
            f"'user_id': {'set' if request_data.user_id else 'unset'}}}"
        )
        
        # 构建查询
        query = db.query(models.ZipDataFile)
        
        # 如果指定了ZIP文件ID，则只查询该文件
        if request_data.zip_datafile_id:
            query = query.filter(models.ZipDataFile.id == request_data.zip_datafile_id)
        
        # 如果指定了文件名，则进行模糊查询
        if request_data.file_name:
            query = query.filter(models.ZipDataFile.file_name.ilike(f"%{request_data.file_name}%"))
        
        # 如果指定了用户ID，则只查询该用户的ZIP文件
        if request_data.user_id:
            query = query.filter(models.ZipDataFile.user_id == request_data.user_id)
        
        # 获取总数（用于分页信息）
        total_count = query.count()
        logger.info(f"[ZIP File][Page] 查询完成 | total_count={total_count}")
        
        # 按ID倒序排列（最新的在前）
        query = query.order_by(models.ZipDataFile.id.desc())
        
        # 应用分页
        offset = (request_data.page - 1) * request_data.page_size
        zip_datafiles = query.offset(offset).limit(request_data.page_size).all()
        logger.info(
            f"[ZIP File][Page] 分页 | page={request_data.page} "
            f"size={request_data.page_size} page_count={len(zip_datafiles)}"
        )
        
        # 构建响应数据
        result = []
        for zip_datafile in zip_datafiles:
            zip_datafile_data = schemas.ZipDataFileOut(
                id=zip_datafile.id,
                file_name=zip_datafile.file_name,
                file_size=zip_datafile.file_size,
                download_number=zip_datafile.download_number,
                download_url=zip_datafile.download_url,
                user_id=zip_datafile.user_id,
                create_time=zip_datafile.create_time,
                update_time=zip_datafile.update_time,
            )
            result.append(zip_datafile_data)
        
        # 计算分页信息
        total_pages = (total_count + request_data.page_size - 1) // request_data.page_size
        
        resp = {
            "zip_datafiles": result,
            "pagination": {
                "current_page": request_data.page,
                "page_size": request_data.page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": request_data.page < total_pages,
                "has_prev": request_data.page > 1
            }
        }
        
        logger.info(
            f"[ZIP File][Page] 成功 | current_page={request_data.page} "
            f"total_pages={total_pages}"
        )
        
        return resp
        
    except HTTPException:
        # 已经构造好的 HTTPException 直接抛出
        raise
    except Exception as e:
        logger.exception(f"[ZIP File][Page] 失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="查询ZIP文件列表失败，请稍后重试"
        )

