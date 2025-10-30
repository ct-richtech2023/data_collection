from loguru import logger
import os
import sys
from datetime import datetime
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
from router.operationlog import router as operationlog_router
from static import SwaggerUIFileNames, SwaggerUIFiles

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

# 挂载API
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