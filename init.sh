#!/bin/bash

# 项目初始化脚本

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║     API 调度网关项目初始化                      ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# 检查 Python 版本
echo "[*] 检查 Python 版本..."
python3 --version
if [ $? -ne 0 ]; then
    echo "[!] 错误: 需要安装 Python 3.9 或更高版本"
    exit 1
fi

# 创建虚拟环境
echo "[*] 创建虚拟环境..."
cd server
python3 -m venv venv
source venv/bin/activate

# 升级 pip
echo "[*] 升级 pip..."
pip install --upgrade pip -q

# 安装依赖
echo "[*] 安装 Python 依赖..."
pip install -r requirements.txt

# 复制配置
echo "[*] 生成配置文件..."
cp .env.example .env

# 创建日志目录
echo "[*] 创建日志目录..."
mkdir -p logs

# 验证配置
echo ""
echo "[*] 验证配置..."
python3 -c "from config import settings; print('✅ 配置验证成功')" || {
    echo "[!] 配置验证失败"
    exit 1
}

# 验证后端配置
echo "[*] 验证后端配置..."
python3 -c "
import json
from pathlib import Path
config_path = Path('config/backends.json')
if config_path.exists():
    with open(config_path) as f:
        config = json.load(f)
    print(f'✅ 后端配置加载成功: {len(config.get(\"services\", {}))} 个服务')
else:
    print('[!] 后端配置文件不存在')
" || {
    echo "[!] 后端配置验证失败"
    exit 1
}

# 测试导入
echo "[*] 测试模块导入..."
python3 -c "
from main import app
from backends_manager import BackendsManager
from health_checker import HealthChecker
print('✅ 模块导入成功')
" || {
    echo "[!] 模块导入失败"
    exit 1
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 项目初始化完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 后续步骤:"
echo "  1. 编辑 config/backends.json 添加您的后端服务"
echo "  2. 启动网关: ./start.sh"
echo "  3. 访问仪表板: http://localhost:8000"
echo "  4. 运行测试: python test.py"
echo ""
