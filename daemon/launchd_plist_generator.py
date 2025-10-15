#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Launchd plist文件生成器
用于创建开机自启的plist文件
"""

import os
import json
import subprocess
from pathlib import Path


def get_python_path():
    """获取Python可执行文件路径"""
    try:
        result = subprocess.run(['which', 'python3'], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            # 尝试其他可能的路径
            for path in ['/usr/local/bin/python3', '/usr/bin/python3', '/opt/homebrew/bin/python3']:
                if os.path.exists(path):
                    return path
            return '/usr/local/bin/python3'  # 默认路径
    except Exception:
        return '/usr/local/bin/python3'


def generate_plist(project_root, config_file="config.json"):
    """生成launchd plist文件"""
    
    # 获取用户信息
    username = os.getenv('USER')
    if not username:
        username = os.getenv('LOGNAME', 'unknown')
    
    # 获取Python路径
    python_path = get_python_path()
    
    # 构建路径
    daemon_script = os.path.join(project_root, "daemon", "daemon_manager.py")
    plist_path = f"/Users/{username}/Library/LaunchAgents/com.calsync.daemon.plist"
    
    # 读取配置文件获取同步间隔
    config_path = os.path.join(project_root, config_file)
    interval_minutes = 30  # 默认值
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            interval_minutes = config.get('sync', {}).get('interval_minutes', 30)
    except Exception as e:
        print(f"警告：无法读取配置文件，使用默认间隔 {interval_minutes} 分钟")
    
    # 生成plist内容
    plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.calsync.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{daemon_script}</string>
        <string>daemon</string>
        <string>--config</string>
        <string>{config_file}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{project_root}</string>
    <key>StandardOutPath</key>
    <string>{project_root}/logs/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>{project_root}/logs/daemon_error.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ProcessType</key>
    <string>Background</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
        <key>PYTHONPATH</key>
        <string>{project_root}</string>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>'''
    
    return plist_content, plist_path


def install_launchd_service(project_root, config_file="config.json"):
    """安装launchd服务"""
    
    print("正在生成launchd plist文件...")
    
    # 生成plist内容
    plist_content, plist_path = generate_plist(project_root, config_file)
    
    # 确保目录存在
    os.makedirs(os.path.dirname(plist_path), exist_ok=True)
    
    # 写入plist文件
    try:
        with open(plist_path, 'w', encoding='utf-8') as f:
            f.write(plist_content)
        print(f"✅ plist文件已创建：{plist_path}")
    except Exception as e:
        print(f"❌ 创建plist文件失败：{e}")
        return False
    
    # 加载服务
    try:
        result = subprocess.run(['launchctl', 'load', plist_path], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ launchd服务已加载")
            return True
        else:
            print(f"❌ 加载launchd服务失败：{result.stderr}")
            return False
    except Exception as e:
        print(f"❌ 加载launchd服务失败：{e}")
        return False


def uninstall_launchd_service(project_root):
    """卸载launchd服务"""
    
    username = os.getenv('USER')
    if not username:
        username = os.getenv('LOGNAME', 'unknown')
    
    plist_path = f"/Users/{username}/Library/LaunchAgents/com.calsync.daemon.plist"
    
    print("正在卸载launchd服务...")
    
    # 卸载服务
    try:
        result = subprocess.run(['launchctl', 'unload', plist_path], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ launchd服务已卸载")
        else:
            print(f"⚠️  卸载launchd服务时出现警告：{result.stderr}")
    except Exception as e:
        print(f"⚠️  卸载launchd服务时出现错误：{e}")
    
    # 删除plist文件
    try:
        if os.path.exists(plist_path):
            os.remove(plist_path)
            print(f"✅ plist文件已删除：{plist_path}")
        else:
            print("plist文件不存在，无需删除")
    except Exception as e:
        print(f"❌ 删除plist文件失败：{e}")
        return False
    
    return True


def check_launchd_service():
    """检查launchd服务状态"""
    
    print("检查launchd服务状态...")
    
    try:
        result = subprocess.run(['launchctl', 'list'], capture_output=True, text=True)
        if result.returncode == 0:
            if 'com.calsync.daemon' in result.stdout:
                print("✅ launchd服务正在运行")
                return True
            else:
                print("❌ launchd服务未运行")
                return False
        else:
            print(f"❌ 检查launchd服务状态失败：{result.stderr}")
            return False
    except Exception as e:
        print(f"❌ 检查launchd服务状态失败：{e}")
        return False


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Launchd plist文件生成器")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--project-root", help="项目根目录路径", default=None)
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # install命令
    install_parser = subparsers.add_parser("install", help="安装launchd服务")
    install_parser.add_argument("--project-root", help="项目根目录路径")
    
    # uninstall命令
    uninstall_parser = subparsers.add_parser("uninstall", help="卸载launchd服务")
    uninstall_parser.add_argument("--project-root", help="项目根目录路径")
    
    # status命令
    status_parser = subparsers.add_parser("status", help="检查launchd服务状态")
    
    args = parser.parse_args()
    
    # 确定项目根目录
    if args.project_root:
        project_root = args.project_root
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    if args.command == "install":
        install_launchd_service(project_root, args.config)
    
    elif args.command == "uninstall":
        uninstall_launchd_service(project_root)
    
    elif args.command == "status":
        check_launchd_service()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
