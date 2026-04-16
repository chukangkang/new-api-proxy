@echo off
REM API 调度网关启动脚本

echo.
echo ╔════════════════════════════════════════════════╗
echo ║     API 调度网关启动脚本 (Windows)              ║
echo ╚════════════════════════════════════════════════╝
echo.

REM 进入 server 目录
cd server

REM 检查虚拟环境
if not exist "venv" (
    echo [*] 创建虚拟环境...
    python -m venv venv
)

REM 激活虚拟环境
echo [*] 激活虚拟环境...
call venv\Scripts\activate.bat

REM 安装依赖
if not exist "venv\Scripts\fastapi.exe" (
    echo [*] 安装依赖...
    pip install -r requirements.txt -q
)

REM 复制配置
if not exist ".env" (
    echo [*] 配置环境变量...
    copy .env.example .env
)

REM 启动应用
echo [*] 启动应用...
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
python main.py
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
