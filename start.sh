#!/bin/bash

# API 调度网关启动脚本

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║     API 调度网关启动脚本 (Linux/macOS)         ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# 进入 server 目录
cd server

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "[*] 创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "[*] 激活虚拟环境..."
source venv/bin/activate

# 安装依赖
if [ ! -f "venv/bin/fastapi" ]; then
    echo "[*] 安装依赖..."
    pip install -r requirements.txt -q
fi

# 复制配置
if [ ! -f ".env" ]; then
    echo "[*] 配置环境变量..."
    cp .env.example .env
fi

# 启动应用
echo "[*] 启动应用..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python main.py
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
