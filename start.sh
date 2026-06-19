#!/bin/bash
echo "===================================="
echo "商场试衣间排队叫号系统"
echo "===================================="
echo ""

echo "[1/4] 检查环境变量文件..."
if [ ! -f .env ]; then
    echo ".env 文件不存在，正在从 .env.example 复制..."
    cp .env.example .env
    echo "请手动编辑 .env 文件，配置数据库连接信息！"
    echo ""
fi

echo "[2/4] 检查 Python 依赖..."
if ! python3 -c "import falcon" 2>/dev/null; then
    echo "正在安装依赖包..."
    pip3 install -r requirements.txt
else
    echo "依赖已安装"
fi

echo ""
echo "[3/4] 初始化数据库..."
python3 init_db.py

echo ""
echo "[4/4] 启动应用服务..."
echo ""
echo "===================================="
echo "服务即将启动，请访问 http://localhost:8000"
echo "默认账号: admin / admin123"
echo "===================================="
echo ""
python3 app.py
