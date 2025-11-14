from loguru import logger
import os
import sys
import asyncio
import time
import uuid
from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from starlette.staticfiles import StaticFiles
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # 确保可导入顶级包 api
from router.user import router as user_router
from router.device import router as device_router
from router.operation import router as operation_router
from router.task import router as task_router
from router.label import router as label_router
from router.datafile import router as datafile_router
from router.zipdatafile import router as zipdatafile_router
from router.operationlog import router as operationlog_router
from static import SwaggerUIFileNames, SwaggerUIFiles

# 尝试导入 Redis 存储（用于多 worker 分布式锁）
try:
    from common.redis_store import get_redis_store
    redis_store = get_redis_store()
    logger.info("Redis 存储已初始化，支持多 worker 分布式锁")
except Exception as e:
    logger.warning(f"Redis 初始化失败，清理任务将在每个 worker 独立运行: {e}")
    redis_store = None

app = FastAPI(
    title="Data Collection API",
    description="",
    version="1.0.0"
)

# 日志目录与文件配置
LOG_DIR = "/var/log/data_collection"
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except Exception as e:
    # 目录不可创建时，继续使用默认控制台输出
    logger.warning(f"无法创建日志目录 {LOG_DIR}: {e}")

log_path = os.path.join(LOG_DIR, "app.log")
try:
    # 清理默认 sink，重新配置控制台与文件双输出
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), enqueue=True, backtrace=True, diagnose=False)
    logger.add(
        log_path,
        rotation="200 MB",
        retention="14 days",
        compression="zip",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {process} | {name}:{function}:{line} - {message}"
    )
    logger.info(f"日志初始化完成，输出到 {log_path}")
except Exception as e:
    logger.warning(f"日志文件无法写入 {log_path}: {e}")
app.mount('/static', StaticFiles(directory=SwaggerUIFiles.current_dir), name='static')
app.mount('/uploads', StaticFiles(directory='uploads'), name='uploads')
app.mount('/tmp/data_collection', StaticFiles(directory='/tmp/data_collection'), name='temp_downloads')

# 临时文件目录配置
TMP_DOWNLOAD_DIR = "/tmp/data_collection"
CLEANUP_INTERVAL_MINUTES = 5  # 每5分钟检查一次
FILE_MAX_AGE_MINUTES = 30  # 文件最大保存时间30分钟
CLEANUP_LOCK_KEY = "cleanup_task:tmp_data_collection"  # 分布式锁的键名
LOCK_EXPIRE_SECONDS = 600  # 锁的过期时间（10分钟），防止死锁

# 生成唯一的 worker 标识（用于分布式锁）
WORKER_ID = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"

async def cleanup_old_files():
    """
    清理 /tmp/data_collection 目录中超过30分钟的文件
    使用 Redis 分布式锁确保多 worker 环境下只有一个 worker 执行清理任务
    """
    while True:
        lock_acquired = False
        try:
            # 尝试获取分布式锁（仅在 Redis 可用时）
            if redis_store:
                lock_acquired = redis_store.acquire_lock(
                    CLEANUP_LOCK_KEY,
                    WORKER_ID,
                    LOCK_EXPIRE_SECONDS
                )
                if not lock_acquired:
                    # 没有获取到锁，说明其他 worker 正在执行清理
                    logger.debug(f"清理任务跳过（其他 worker 正在执行）| worker_id={WORKER_ID}")
                    await asyncio.sleep(CLEANUP_INTERVAL_MINUTES * 60)
                    continue
                else:
                    logger.debug(f"清理任务获取锁成功 | worker_id={WORKER_ID}")
            
            # 执行清理任务
            if not os.path.exists(TMP_DOWNLOAD_DIR):
                logger.warning(f"临时目录不存在: {TMP_DOWNLOAD_DIR}")
                await asyncio.sleep(CLEANUP_INTERVAL_MINUTES * 60)
                continue
            
            current_time = time.time()
            max_age_seconds = FILE_MAX_AGE_MINUTES * 60
            deleted_count = 0
            total_size_freed = 0
            
            # 遍历目录中的所有文件
            for root, dirs, files in os.walk(TMP_DOWNLOAD_DIR):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    try:
                        # 获取文件的修改时间
                        file_mtime = os.path.getmtime(file_path)
                        file_age = current_time - file_mtime
                        
                        # 如果文件超过30分钟，删除它
                        if file_age > max_age_seconds:
                            file_size = os.path.getsize(file_path)
                            os.remove(file_path)
                            deleted_count += 1
                            total_size_freed += file_size
                            logger.info(
                                f"清理临时文件 | worker_id={WORKER_ID} | 文件: {filename} | "
                                f"年龄: {file_age/60:.1f}分钟 | 大小: {file_size/(1024*1024):.2f}MB"
                            )
                    except FileNotFoundError:
                        # 文件可能已被其他进程删除，忽略
                        pass
                    except OSError as e:
                        logger.warning(f"删除文件失败: {file_path}, 错误: {e}")
                    except Exception as e:
                        logger.error(f"处理文件时出错: {file_path}, 错误: {e}")
            
            if deleted_count > 0:
                logger.info(
                    f"临时文件清理完成 | worker_id={WORKER_ID} | 删除文件数: {deleted_count} | "
                    f"释放空间: {total_size_freed/(1024*1024):.2f}MB"
                )
            
        except Exception as e:
            logger.error(f"清理临时文件时出错 | worker_id={WORKER_ID}, 错误: {e}")
        finally:
            # 释放分布式锁
            if redis_store and lock_acquired:
                try:
                    redis_store.release_lock(CLEANUP_LOCK_KEY, WORKER_ID)
                    logger.debug(f"清理任务释放锁 | worker_id={WORKER_ID}")
                except Exception as e:
                    logger.warning(f"释放分布式锁失败 | worker_id={WORKER_ID}, 错误: {e}")
        
        # 等待指定时间后再次执行
        await asyncio.sleep(CLEANUP_INTERVAL_MINUTES * 60)


@app.on_event("startup")
async def startup_event():
    """
    应用启动时启动定时清理任务
    """
    lock_mode = "分布式锁（多 worker 安全）" if redis_store else "独立运行（单 worker 或 Redis 不可用）"
    logger.info(
        f"启动临时文件清理任务 | worker_id={WORKER_ID} | 模式: {lock_mode} | "
        f"目录: {TMP_DOWNLOAD_DIR} | 清理间隔: {CLEANUP_INTERVAL_MINUTES}分钟 | "
        f"文件最大保存时间: {FILE_MAX_AGE_MINUTES}分钟"
    )
    # 确保目录存在
    if not os.path.exists(TMP_DOWNLOAD_DIR):
        os.makedirs(TMP_DOWNLOAD_DIR, exist_ok=True)
        logger.info(f"创建临时目录: {TMP_DOWNLOAD_DIR}")
    # 启动后台清理任务
    asyncio.create_task(cleanup_old_files())

# 挂载API
app.include_router(zipdatafile_router)
app.include_router(datafile_router)
app.include_router(task_router)
app.include_router(label_router)
app.include_router(device_router)
app.include_router(operation_router)
app.include_router(operationlog_router)
app.include_router(user_router)

def get_custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=f"/openapi.json",
        title="API",
        swagger_js_url=f'/static/{SwaggerUIFileNames.js}',
        swagger_css_url=f'/static/{SwaggerUIFileNames.css}',
        swagger_favicon_url=f'/static/{SwaggerUIFileNames.favicon}'
    )


@app.get("/", include_in_schema=False)
async def root(request: Request):
    return get_custom_swagger_ui_html()


if __name__ == "__main__":
    import uvicorn
    import subprocess
    import os
    
    # 杀掉占用9000端口的进程
    try:
        # 查找占用9000端口的进程
        result = subprocess.run(['lsof', '-ti:9000'], capture_output=True, text=True)
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    print(f"正在杀掉进程 {pid}...")
                    os.kill(int(pid), 9)
                    print(f"进程 {pid} 已成功杀掉")
        else:
            print("没有发现占用9000端口的进程")
    except Exception as e:
        print(f"杀掉进程时出错: {e}")
    
    # 启动应用
    print("正在启动应用...")
    uvicorn.run("app:app", host="0.0.0.0", port=9000)