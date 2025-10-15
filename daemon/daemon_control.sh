#!/bin/bash
# CalSync 守护进程控制脚本
# 提供简单的命令行接口来管理守护进程

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 守护进程脚本路径
DAEMON_SCRIPT="$SCRIPT_DIR/daemon_manager.py"
PLIST_GENERATOR="$SCRIPT_DIR/launchd_plist_generator.py"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# 检查守护进程是否运行
is_daemon_running() {
    python3 "$DAEMON_SCRIPT" status > /dev/null 2>&1
    return $?
}

# 主函数
case "${1:-help}" in
    start)
        print_message $BLUE "启动CalSync守护进程..."
        
        if is_daemon_running; then
            print_message $YELLOW "守护进程已在运行"
            exit 1
        fi
        
        # 检查配置文件
        if [ ! -f "$PROJECT_ROOT/config.json" ]; then
            print_message $RED "❌ 配置文件不存在，请先运行 python3 install.py 进行配置"
            exit 1
        fi
        
        # 启动守护进程
        python3 "$DAEMON_SCRIPT" start
        if [ $? -eq 0 ]; then
            print_message $GREEN "✅ 守护进程启动成功"
        else
            print_message $RED "❌ 守护进程启动失败"
            exit 1
        fi
        ;;
    
    stop)
        print_message $BLUE "停止CalSync守护进程..."
        
        if ! is_daemon_running; then
            print_message $YELLOW "守护进程未运行"
            exit 1
        fi
        
        python3 "$DAEMON_SCRIPT" stop
        if [ $? -eq 0 ]; then
            print_message $GREEN "✅ 守护进程已停止"
        else
            print_message $RED "❌ 停止守护进程失败"
            exit 1
        fi
        ;;
    
    restart)
        print_message $BLUE "重启CalSync守护进程..."
        python3 "$DAEMON_SCRIPT" restart
        if [ $? -eq 0 ]; then
            print_message $GREEN "✅ 守护进程重启成功"
        else
            print_message $RED "❌ 守护进程重启失败"
            exit 1
        fi
        ;;
    
    status)
        print_message $BLUE "CalSync守护进程状态"
        echo "=================================="
        python3 "$DAEMON_SCRIPT" status
        ;;
    
    logs)
        print_message $BLUE "查看守护进程日志..."
        if [ -f "$PROJECT_ROOT/logs/daemon.log" ]; then
            tail -20 "$PROJECT_ROOT/logs/daemon.log"
        else
            print_message $YELLOW "日志文件不存在"
        fi
        ;;
    
    install)
        print_message $BLUE "安装开机自启服务..."
        
        # 检查配置文件
        if [ ! -f "$PROJECT_ROOT/config.json" ]; then
            print_message $RED "❌ 配置文件不存在，请先运行 python3 install.py 进行配置"
            exit 1
        fi
        
        # 安装launchd服务
        python3 "$PLIST_GENERATOR" install --project-root "$PROJECT_ROOT"
        if [ $? -eq 0 ]; then
            print_message $GREEN "✅ 开机自启服务安装成功"
            print_message $YELLOW "注意：首次运行需要授权日历访问权限"
        else
            print_message $RED "❌ 开机自启服务安装失败"
            exit 1
        fi
        ;;
    
    uninstall)
        print_message $BLUE "卸载开机自启服务..."
        python3 "$PLIST_GENERATOR" uninstall --project-root "$PROJECT_ROOT"
        if [ $? -eq 0 ]; then
            print_message $GREEN "✅ 开机自启服务卸载成功"
        else
            print_message $RED "❌ 开机自启服务卸载失败"
            exit 1
        fi
        ;;
    
    autostart-status)
        print_message $BLUE "检查开机自启服务状态..."
        python3 "$PLIST_GENERATOR" status
        ;;
    
    test)
        print_message $BLUE "测试单次同步..."
        cd "$PROJECT_ROOT"
        python3 cal_sync.py --once
        ;;
    
    help)
        print_message $BLUE "CalSync守护进程控制工具"
        echo "=================================="
        echo "使用方法: $0 [命令]"
        echo ""
        echo "守护进程命令:"
        echo "  start     启动守护进程"
        echo "  stop      停止守护进程"
        echo "  restart   重启守护进程"
        echo "  status    查看守护进程状态"
        echo "  logs      查看守护进程日志"
        echo ""
        echo "开机自启命令:"
        echo "  install           安装开机自启服务"
        echo "  uninstall         卸载开机自启服务"
        echo "  autostart-status  检查开机自启服务状态"
        echo ""
        echo "其他命令:"
        echo "  test      测试单次同步"
        echo "  help      显示帮助信息"
        echo ""
        echo "示例:"
        echo "  $0 install     # 安装开机自启服务"
        echo "  $0 start       # 启动守护进程"
        echo "  $0 status      # 查看状态"
        echo "  $0 logs        # 查看日志"
        ;;
    
    *)
        print_message $RED "未知命令: $1"
        echo "运行 '$0 help' 查看帮助"
        exit 1
        ;;
esac
