"""
应用入口模块
"""
import os
import signal
import subprocess
import threading
import time
import webbrowser

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.api.router import api_router
from app.core.logging import logger
from app.config import HOST, PORT

# 创建FastAPI应用
app = FastAPI(title="实时语音转写")

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 设置模板
templates = Jinja2Templates(directory="templates")

# 注册API路由
app.include_router(api_router)

# 主页路由
@app.get('/', response_class=HTMLResponse)
async def index(request: Request):
    """
    渲染主页
    
    Args:
        request: 请求对象
    
    Returns:
        HTML响应
    """
    return templates.TemplateResponse("index.html", {"request": request})

def _kill_process_on_port(port: int) -> None:
    """
    若本机已有进程占用该端口，则结束之（避免 Address already in use）。
    依赖系统提供 lsof（macOS / 多数 Linux 自带）。
    """
    try:
        r = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except FileNotFoundError:
        logger.warning("未找到 lsof，无法自动释放端口 %s", port)
        return
    except subprocess.TimeoutExpired:
        logger.warning("检测端口 %s 占用时超时", port)
        return

    if r.returncode != 0 or not (r.stdout or "").strip():
        return

    pids = {p.strip() for p in r.stdout.split() if p.strip().isdigit()}
    my_pid = str(os.getpid())
    killed_any = False
    for pid_str in pids:
        if pid_str == my_pid:
            continue
        try:
            os.kill(int(pid_str), signal.SIGKILL)
            logger.info("已结束占用端口 %s 的进程: PID %s", port, pid_str)
            killed_any = True
        except ProcessLookupError:
            pass
        except PermissionError:
            logger.warning("无权限结束 PID %s，请手动关闭占用端口 %s 的进程", pid_str, port)

    if killed_any:
        time.sleep(0.4)


def _open_browser_after_delay():
    """本地启动后自动在默认浏览器中打开页面（使用 127.0.0.1，与监听 0.0.0.0 对应）"""
    time.sleep(1.2)
    url = f"http://127.0.0.1:{PORT}/"
    try:
        webbrowser.open(url)
        logger.info("已尝试在浏览器中打开: %s", url)
    except Exception as e:
        logger.warning("自动打开浏览器失败: %s", e)


# 应用启动入口
if __name__ == '__main__':
    try:
        logger.info("启动应用服务器")
        _kill_process_on_port(PORT)
        threading.Thread(target=_open_browser_after_delay, daemon=True).start()
        uvicorn.run(app, host=HOST, port=PORT)
    except Exception as e:
        logger.error(f"服务器启动失败: {str(e)}")