from loguru import logger
from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from starlette.staticfiles import StaticFiles
from router.user import router as user_router
from router.device import router as device_router
from router.operation import router as operation_router
from static import SwaggerUIFileNames, SwaggerUIFiles

app = FastAPI(
    title="Data Collection API",
    description="",
    version="1.0.0"
)
app.mount('/static', StaticFiles(directory=SwaggerUIFiles.current_dir), name='static')

# 挂载API
app.include_router(user_router)
app.include_router(device_router)
app.include_router(operation_router)

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