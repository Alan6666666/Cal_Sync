#!/bin/bash
# CalDAV到iCloud日历同步工具 - 后台定时同步管理脚本
# 集成同步功能和定时任务管理功能

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 同步执行函数
run_sync() {
    cd "$SCRIPT_DIR"
    
    # 设置环境变量
    export PATH="/usr/local/bin:/usr/bin:/bin"
    export PYTHONPATH="$SCRIPT_DIR"
    
    # 执行同步（让Python脚本自己处理日志）
    /usr/local/bin/python3 cal_sync.py --once
}

# 主函数
case "${1:-status}" in
    status)
        echo "CalDAV到iCloud日历同步 - 后台定时任务管理"
        echo "============================================="
        echo "检查launchd定时任务状态..."
        if launchctl list | grep -q "com.calsync.timer"; then
            echo "✅ launchd定时任务正在运行"
            launchctl list | grep "com.calsync.timer"
        else
            echo "❌ launchd定时任务未运行"
        fi
        
        echo ""
        echo "检查日志文件..."
        if [ -f "$SCRIPT_DIR/logs/cal_sync.log" ]; then
            echo "✅ 日志文件存在"
            echo "最后修改时间: $(stat -f "%Sm" "$SCRIPT_DIR/logs/cal_sync.log")"
            echo "文件大小: $(stat -f "%z" "$SCRIPT_DIR/logs/cal_sync.log") 字节"
            echo ""
            echo "最近5行日志:"
            tail -5 "$SCRIPT_DIR/logs/cal_sync.log"
        else
            echo "❌ 日志文件不存在"
        fi
        ;;
    
    start)
        echo "启用launchd定时任务..."
        launchctl load /Users/$(whoami)/Library/LaunchAgents/com.calsync.timer.plist
        if [ $? -eq 0 ]; then
            echo "✅ 定时任务已启用"
        else
            echo "❌ 启用失败"
        fi
        ;;
    
    stop)
        echo "禁用launchd定时任务..."
        launchctl unload /Users/$(whoami)/Library/LaunchAgents/com.calsync.timer.plist
        if [ $? -eq 0 ]; then
            echo "✅ 定时任务已禁用"
        else
            echo "❌ 禁用失败"
        fi
        ;;
    
    test)
        echo "测试单次同步..."
        run_sync
        ;;
    
    logs)
        echo "查看同步日志..."
        if [ -f "$SCRIPT_DIR/logs/cal_sync.log" ]; then
            tail -20 "$SCRIPT_DIR/logs/cal_sync.log"
        else
            echo "日志文件不存在"
        fi
        ;;
    
    setup)
        echo "设置launchd定时任务..."
        
        # 检查配置文件
        if [ ! -f "$SCRIPT_DIR/config.json" ]; then
            echo "❌ 配置文件不存在，请先运行 python3 install.py 进行配置"
            exit 1
        fi
        
        # 检查Python脚本
        if [ ! -f "$SCRIPT_DIR/cal_sync.py" ]; then
            echo "❌ 同步脚本不存在"
            exit 1
        fi
        
        # 创建plist文件
        username=$(whoami)
        plist_path="/Users/$username/Library/LaunchAgents/com.calsync.timer.plist"
        
        # 生成plist内容（从配置文件读取间隔时间）
        python3 -c "
import os
import sys
import json

username = os.getenv('USER')
script_dir = '$SCRIPT_DIR'
script_path = os.path.join(script_dir, 'background_timer.sh')
config_path = os.path.join(script_dir, 'config.json')

# 读取配置文件获取间隔时间
try:
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    interval_minutes = config.get('sync', {}).get('interval_minutes', 5)
    print(f'📋 从配置文件读取到同步间隔：{interval_minutes}分钟')
except Exception as e:
    interval_minutes = 5
    print(f'⚠️  无法读取配置文件，使用默认间隔：{interval_minutes}分钟')

# 根据间隔时间生成分钟数组
minutes_array = []
for i in range(0, 60, interval_minutes):
    minutes_array.append(f'            <integer>{i}</integer>')
minutes_xml = '\\n'.join(minutes_array)

plist_content = f'''<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
    <key>Label</key>
    <string>com.calsync.timer</string>
    <key>ProgramArguments</key>
    <array>
        <string>{script_path}</string>
        <string>test</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{script_dir}</string>
    <key>StandardOutPath</key>
    <string>{script_dir}/logs/cal_sync.log</string>
    <key>StandardErrorPath</key>
    <string>{script_dir}/logs/cal_sync_error.log</string>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
    <key>StartInterval</key>
    <integer>{interval_minutes * 60}</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
        <key>PYTHONPATH</key>
        <string>{script_dir}</string>
    </dict>
</dict>
</plist>'''

plist_path = f'/Users/{username}/Library/LaunchAgents/com.calsync.timer.plist'
os.makedirs(os.path.dirname(plist_path), exist_ok=True)

with open(plist_path, 'w') as f:
    f.write(plist_content)

print(f'✅ plist文件已创建：{plist_path}')
print(f'   脚本路径：{script_path}')
print(f'   工作目录：{script_dir}')
print(f'   同步间隔：{interval_minutes}分钟')
"
        
        if [ $? -eq 0 ]; then
            echo "✅ launchd定时任务配置完成"
            echo "使用 './background_timer.sh start' 启用定时任务"
        else
            echo "❌ 配置失败"
            exit 1
        fi
        ;;
    
    remove)
        echo "删除定时任务..."
        launchctl unload /Users/$(whoami)/Library/LaunchAgents/com.calsync.timer.plist 2>/dev/null
        rm /Users/$(whoami)/Library/LaunchAgents/com.calsync.timer.plist 2>/dev/null
        echo "✅ 定时任务已删除"
        ;;
    
    help)
        echo "CalDAV到iCloud日历同步 - 后台定时任务管理"
        echo "============================================="
        echo "使用方法: $0 [命令]"
        echo ""
        echo "命令:"
        echo "  setup   设置launchd定时任务（首次使用）"
        echo "  start   启用定时任务"
        echo "  stop    禁用定时任务"
        echo "  status  查看任务状态（默认）"
        echo "  test    测试单次运行"
        echo "  logs    查看日志"
        echo "  remove  删除定时任务"
        echo "  help    显示帮助"
        echo ""
        echo "示例:"
        echo "  $0 setup    # 首次设置定时任务"
        echo "  $0 start    # 启用定时任务"
        echo "  $0 status   # 查看任务状态"
        echo "  $0 test     # 测试同步功能"
        ;;
    
    *)
        echo "未知命令: $1"
        echo "运行 '$0 help' 查看帮助"
        ;;
esac
