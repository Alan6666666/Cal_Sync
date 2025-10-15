#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CalSync守护进程安装和配置脚本
"""

import os
import sys
import json
import subprocess
from pathlib import Path


def check_dependencies():
    """检查依赖"""
    print("检查依赖...")
    
    # 检查Python版本
    if sys.version_info < (3, 7):
        print("❌ 需要Python 3.7或更高版本")
        return False
    
    # 检查必要的包
    required_packages = ['psutil', 'schedule', 'caldav', 'icalendar', 'keyring']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"❌ 缺少依赖包: {', '.join(missing_packages)}")
        print("请运行: pip3 install " + " ".join(missing_packages))
        return False
    
    print("✅ 依赖检查通过")
    return True


def check_config():
    """检查配置文件"""
    print("检查配置文件...")
    
    project_root = Path(__file__).parent.parent
    config_file = project_root / "config.json"
    
    if not config_file.exists():
        print("❌ 配置文件不存在，请先运行 python3 install.py 进行配置")
        return False
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 检查必要的配置项
        required_sections = ['caldav', 'icloud', 'sync']
        for section in required_sections:
            if section not in config:
                print(f"❌ 配置文件缺少 {section} 部分")
                return False
        
        print("✅ 配置文件检查通过")
        return True
        
    except Exception as e:
        print(f"❌ 配置文件格式错误: {e}")
        return False


def create_daemon_directories():
    """创建守护进程相关目录"""
    print("创建守护进程目录...")
    
    project_root = Path(__file__).parent.parent
    
    # 创建必要的目录
    directories = [
        project_root / "daemon",
        project_root / "logs"
    ]
    
    for directory in directories:
        directory.mkdir(exist_ok=True)
        print(f"✅ 目录已创建: {directory}")
    
    return True


def test_daemon():
    """测试守护进程功能"""
    print("测试守护进程功能...")
    
    project_root = Path(__file__).parent.parent
    daemon_script = project_root / "daemon" / "daemon_manager.py"
    
    try:
        # 测试状态检查
        result = subprocess.run([
            sys.executable, str(daemon_script), "status"
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print("✅ 守护进程功能测试通过")
            return True
        else:
            print(f"❌ 守护进程功能测试失败: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ 守护进程功能测试超时")
        return False
    except Exception as e:
        print(f"❌ 守护进程功能测试失败: {e}")
        return False


def install_launchd_service():
    """安装launchd服务"""
    print("安装开机自启服务...")
    
    project_root = Path(__file__).parent.parent
    plist_generator = project_root / "daemon" / "launchd_plist_generator.py"
    
    try:
        result = subprocess.run([
            sys.executable, str(plist_generator), "install",
            "--project-root", str(project_root)
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 开机自启服务安装成功")
            return True
        else:
            print(f"❌ 开机自启服务安装失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ 安装开机自启服务失败: {e}")
        return False


def main():
    """主函数"""
    print("CalSync守护进程安装程序")
    print("=" * 40)
    
    # 检查依赖
    if not check_dependencies():
        sys.exit(1)
    
    # 检查配置
    if not check_config():
        sys.exit(1)
    
    # 创建目录
    if not create_daemon_directories():
        sys.exit(1)
    
    # 测试守护进程
    if not test_daemon():
        sys.exit(1)
    
    # 询问是否安装开机自启
    print("\n是否安装开机自启服务？(y/n): ", end="")
    try:
        choice = input().lower().strip()
    except EOFError:
        # 非交互模式，默认不安装开机自启
        choice = 'n'
        print("n (非交互模式，默认不安装)")
    
    if choice in ['y', 'yes', '是']:
        if not install_launchd_service():
            print("⚠️  开机自启服务安装失败，但守护进程仍可手动启动")
    
    print("\n" + "=" * 40)
    print("安装完成！")
    print("\n使用方法:")
    print("  ./daemon/daemon_control.sh start     # 启动守护进程")
    print("  ./daemon/daemon_control.sh stop      # 停止守护进程")
    print("  ./daemon/daemon_control.sh status    # 查看状态")
    print("  ./daemon/daemon_control.sh logs      # 查看日志")
    print("\n开机自启服务:")
    print("  ./daemon/daemon_control.sh install   # 安装开机自启")
    print("  ./daemon/daemon_control.sh uninstall # 卸载开机自启")


if __name__ == "__main__":
    main()
