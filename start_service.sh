#!/bin/bash
# 启动 Data Collection API 服务的脚本

SERVICE_FILE="data-collection.service"
SERVICE_NAME="data-collection"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="${USER:-ec2-user}"

echo "=========================================="
echo "Data Collection API 服务管理"
echo "=========================================="
echo "项目路径: $PROJECT_ROOT"
echo "当前用户: $CURRENT_USER"
echo "=========================================="

# 检查服务文件是否存在
if [ ! -f "$PROJECT_ROOT/$SERVICE_FILE" ]; then
    echo "❌ 服务文件不存在: $PROJECT_ROOT/$SERVICE_FILE"
    exit 1
fi

# 自动检测并更新服务文件中的路径（如果需要）
auto_configure_service() {
    echo "🔧 检查服务配置..."
    
    # 检测 conda 环境路径
    CONDA_ENV_NAME="data_collection"
    POSSIBLE_CONDA_PATHS=(
        "/home/$CURRENT_USER/miniconda3/envs/$CONDA_ENV_NAME/bin"
        "/home/$CURRENT_USER/anaconda3/envs/$CONDA_ENV_NAME/bin"
        "$HOME/miniconda3/envs/$CONDA_ENV_NAME/bin"
        "$HOME/anaconda3/envs/$CONDA_ENV_NAME/bin"
    )
    
    CONDA_ENV_PATH=""
    for path in "${POSSIBLE_CONDA_PATHS[@]}"; do
        if [ -d "$path" ]; then
            CONDA_ENV_PATH="$path"
            break
        fi
    done
    
    if [ -z "$CONDA_ENV_PATH" ]; then
        echo "⚠️  警告: 未找到 conda 环境路径，请手动检查服务配置文件"
        echo "   预期路径之一: /home/$CURRENT_USER/miniconda3/envs/$CONDA_ENV_NAME/bin"
    else
        echo "✅ 找到 conda 环境: $CONDA_ENV_PATH"
    fi
    
    # 检查服务文件中的路径是否正确
    SERVICE_USER=$(grep "^User=" "$PROJECT_ROOT/$SERVICE_FILE" 2>/dev/null | cut -d= -f2)
    SERVICE_WORKDIR=$(grep "^WorkingDirectory=" "$PROJECT_ROOT/$SERVICE_FILE" 2>/dev/null | cut -d= -f2)
    
    if [ "$SERVICE_USER" != "$CURRENT_USER" ] || [ "$SERVICE_WORKDIR" != "$PROJECT_ROOT" ]; then
        echo "⚠️  警告: 服务配置文件中的路径可能与当前环境不匹配"
        echo "   服务文件用户: $SERVICE_USER (当前用户: $CURRENT_USER)"
        echo "   服务文件工作目录: $SERVICE_WORKDIR (当前项目: $PROJECT_ROOT)"
        echo ""
        echo "请手动编辑 $PROJECT_ROOT/$SERVICE_FILE 文件以确保配置正确"
        read -p "是否继续安装? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# 根据参数执行不同操作
case "$1" in
    install)
        # 自动检查配置
        auto_configure_service
        
        echo ""
        echo "📦 安装 systemd 服务..."
        sudo cp "$PROJECT_ROOT/$SERVICE_FILE" /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable $SERVICE_NAME
        echo "✅ 服务已安装并设置为开机自启"
        echo ""
        echo "使用以下命令管理服务:"
        echo "  启动: sudo systemctl start $SERVICE_NAME"
        echo "  停止: sudo systemctl stop $SERVICE_NAME"
        echo "  重启: sudo systemctl restart $SERVICE_NAME"
        echo "  状态: sudo systemctl status $SERVICE_NAME"
        echo "  日志: sudo journalctl -u $SERVICE_NAME -f"
        echo ""
        echo "或者使用此脚本:"
        echo "  启动: bash $0 start"
        echo "  停止: bash $0 stop"
        echo "  重启: bash $0 restart"
        ;;
    uninstall)
        echo "🗑️  卸载 systemd 服务..."
        sudo systemctl stop $SERVICE_NAME 2>/dev/null
        sudo systemctl disable $SERVICE_NAME 2>/dev/null
        sudo rm /etc/systemd/system/$SERVICE_FILE
        sudo systemctl daemon-reload
        echo "✅ 服务已卸载"
        ;;
    start)
        echo "▶️  启动服务..."
        sudo systemctl start $SERVICE_NAME
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    stop)
        echo "⏹️  停止服务..."
        sudo systemctl stop $SERVICE_NAME
        echo "✅ 服务已停止"
        ;;
    restart)
        echo "🔄 重启服务..."
        sudo systemctl restart $SERVICE_NAME
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    status)
        echo "📊 服务状态:"
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    logs)
        echo "📋 查看日志 (按 Ctrl+C 退出):"
        sudo journalctl -u $SERVICE_NAME -f
        ;;
    *)
        echo "使用方法: $0 {install|uninstall|start|stop|restart|status|logs}"
        echo ""
        echo "命令说明:"
        echo "  install   - 安装并启用服务（开机自启）"
        echo "  uninstall - 卸载服务"
        echo "  start     - 启动服务"
        echo "  stop      - 停止服务"
        echo "  restart   - 重启服务"
        echo "  status    - 查看服务状态"
        echo "  logs      - 查看实时日志"
        exit 1
        ;;
esac

