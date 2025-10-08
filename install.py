#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CalDAV到iCloud日历同步工具 - 统一安装配置脚本
"""

import os
import sys
import json
import getpass
import subprocess
from pathlib import Path


def check_python_version():
    """检查Python版本"""
    print("检查Python版本...")
    if sys.version_info < (3, 7):
        print("❌ 需要Python 3.7或更高版本")
        sys.exit(1)
    print(f"✅ Python版本：{sys.version}")


def install_dependencies():
    """安装Python依赖"""
    print("\n正在安装Python依赖...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ 依赖安装成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 依赖安装失败：{e}")
        return False


def create_config():
    """创建配置文件"""
    print("\n正在创建配置文件...")
    
    # 检查是否已存在配置文件
    if os.path.exists("config.json"):
        print("检测到现有配置文件，是否要重新配置？")
        choice = input("输入 y 重新配置，其他键跳过: ").strip().lower()
        if choice != 'y':
            print("跳过配置文件创建")
            return True
    
    config = {
        "caldav": {
            "server": "",
            "base_url": "",
            "username": "",
            "password": "",
            "calendar_url": ""
        },
        "icloud": {
            "username": "",
            "password": "",
            "calendar_name": "企微同步",
            "app_private_password": ""
        },
        "sync": {
            "interval_minutes": 30,
            "sync_past_days": 30,
            "sync_future_days": 365,
            "expand_recurring": True,
            "verify_threshold": 0.9,
            "override_icloud_deletions": True
        }
    }
    
    print("\n=== CalDAV服务器配置 ===")
    config["caldav"]["server"] = input("CalDAV服务器地址 (如: caldav.wecom.work): ").strip()
    
    # 自动生成base_url
    if config["caldav"]["server"]:
        if not config["caldav"]["server"].startswith(('http://', 'https://')):
            config["caldav"]["base_url"] = f"https://{config['caldav']['server']}/calendar/"
        else:
            config["caldav"]["base_url"] = f"{config['caldav']['server']}/calendar/"
        print(f"自动生成base_url: {config['caldav']['base_url']}")
    
    config["caldav"]["username"] = input("CalDAV用户名 (如: username@company.wecom.work): ").strip()
    config["caldav"]["password"] = getpass.getpass("CalDAV密码: ").strip()
    
    calendar_url = input("特定日历URL (可选，直接回车跳过): ").strip()
    if calendar_url:
        config["caldav"]["calendar_url"] = calendar_url
    
    print("\n=== iCloud账户配置 ===")
    config["icloud"]["username"] = input("iCloud邮箱地址: ").strip()
    
    print("密码选项：")
    print("1. 使用iCloud密码")
    print("2. 使用专用密码 (推荐)")
    password_choice = input("选择密码类型 (1/2，默认2): ").strip() or "2"
    
    if password_choice == "1":
        config["icloud"]["password"] = getpass.getpass("iCloud密码: ").strip()
    else:
        config["icloud"]["app_private_password"] = getpass.getpass("iCloud专用密码: ").strip()
    
    calendar_name = input("目标iCloud日历名称 (默认: 企微同步): ").strip()
    if calendar_name:
        config["icloud"]["calendar_name"] = calendar_name
    
    print("\n=== 同步设置 ===")
    try:
        interval = input("同步间隔（分钟，默认30）: ").strip()
        if interval:
            config["sync"]["interval_minutes"] = int(interval)
    except ValueError:
        print("使用默认间隔：30分钟")
    
    try:
        past_days = input("同步过去多少天的事件（默认30）: ").strip()
        if past_days:
            config["sync"]["sync_past_days"] = int(past_days)
    except ValueError:
        print("使用默认值：30天")
    
    try:
        future_days = input("同步未来多少天的事件（默认365）: ").strip()
        if future_days:
            config["sync"]["sync_future_days"] = int(future_days)
    except ValueError:
        print("使用默认值：365天")
    
    # 高级设置
    print("\n=== 高级设置 ===")
    expand_recurring = input("是否展开循环事件为具体实例？(y/n，默认y): ").strip().lower()
    if expand_recurring == 'n':
        config["sync"]["expand_recurring"] = False
    
    verify_threshold = input("同步验证阈值 (0.0-1.0，默认0.9): ").strip()
    if verify_threshold:
        try:
            config["sync"]["verify_threshold"] = float(verify_threshold)
        except ValueError:
            print("使用默认值：0.9")
    
    override_deletions = input("是否自动恢复被手动删除的iCloud事件？(y/n，默认y): ").strip().lower()
    if override_deletions == 'n':
        config["sync"]["override_icloud_deletions"] = False
    
    # 保存配置文件
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    
    print("✅ 配置文件已创建：config.json")
    return True


def setup_keyring():
    """设置钥匙串密码"""
    print("\n正在设置钥匙串密码...")
    
    try:
        import keyring
        
        # 读取配置
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        
        # 设置CalDAV密码
        if config["caldav"]["password"]:
            keyring.set_password("cal_sync", config["caldav"]["username"], config["caldav"]["password"])
            print("✅ CalDAV密码已保存到钥匙串")
        
        # 设置iCloud密码
        if config["icloud"]["password"]:
            keyring.set_password("cal_sync_icloud", config["icloud"]["username"], config["icloud"]["password"])
            print("✅ iCloud密码已保存到钥匙串")
        
        return True
        
    except ImportError:
        print("❌ keyring库未安装，无法设置钥匙串密码")
        return False
    except Exception as e:
        print(f"❌ 设置钥匙串密码失败：{e}")
        return False


def test_connection():
    """测试连接"""
    print("\n正在测试连接...")
    
    try:
        from cal_sync import CalSync
        
        syncer = CalSync()
        
        # 测试CalDAV连接
        print("测试CalDAV连接...")
        if syncer.connect_caldav():
            print("✅ CalDAV连接成功")
        else:
            print("❌ CalDAV连接失败")
            return False
        
        # 测试iCloud连接
        print("测试iCloud连接...")
        if syncer.connect_icloud():
            print("✅ iCloud连接成功")
        else:
            print("❌ iCloud连接失败")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ 连接测试失败：{e}")
        return False


def setup_macos_permissions():
    """设置macOS权限说明"""
    print("\n=== macOS权限设置 ===")
    print("请按照以下步骤设置macOS日历访问权限：")
    print("1. 打开 系统偏好设置 > 安全性与隐私 > 隐私")
    print("2. 在左侧列表中选择 日历")
    print("3. 点击左下角的锁图标并输入密码")
    print("4. 勾选 终端 和 Cursor（或您使用的IDE）")
    print("5. 重启终端/IDE后重试")
    
    input("\n设置完成后按回车继续...")


def create_launchd_plist():
    """创建macOS启动项"""
    print("\n=== macOS启动项设置 ===")
    print("是否创建macOS启动项？这样可以在系统启动时自动运行同步脚本。")
    choice = input("输入 y 创建启动项，其他键跳过: ").strip().lower()
    
    if choice != 'y':
        return True
    
    try:
        # 获取当前用户和脚本路径
        username = os.getenv('USER')
        script_path = os.path.abspath('cal_sync.py')
        
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.calsync.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{script_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{os.path.abspath('cal_sync.log')}</string>
    <key>StandardErrorPath</key>
    <string>{os.path.abspath('cal_sync_error.log')}</string>
</dict>
</plist>"""
        
        plist_path = f"/Users/{username}/Library/LaunchAgents/com.calsync.daemon.plist"
        
        # 确保目录存在
        os.makedirs(os.path.dirname(plist_path), exist_ok=True)
        
        with open(plist_path, "w") as f:
            f.write(plist_content)
        
        print(f"✅ 启动项已创建：{plist_path}")
        print("\n启动项管理命令：")
        print(f"启用：launchctl load {plist_path}")
        print(f"禁用：launchctl unload {plist_path}")
        print(f"查看状态：launchctl list | grep calsync")
        
        return True
        
    except Exception as e:
        print(f"❌ 创建启动项失败：{e}")
        return False


def run_initial_sync():
    """运行初始同步测试"""
    print("\n=== 初始同步测试 ===")
    choice = input("是否运行一次同步测试？(y/n，默认y): ").strip().lower() or "y"
    
    if choice != 'y':
        return True
    
    try:
        print("正在运行同步测试...")
        result = subprocess.run([sys.executable, "cal_sync.py", "--once"], 
                              capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            print("✅ 同步测试成功")
            print("查看日志文件 cal_sync.log 了解详细信息")
        else:
            print("❌ 同步测试失败")
            print("错误输出：", result.stderr)
            print("请检查配置和网络连接")
        
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("❌ 同步测试超时")
        return False
    except Exception as e:
        print(f"❌ 同步测试失败：{e}")
        return False


def main():
    """主函数"""
    print("CalDAV到iCloud日历同步工具 - 统一安装配置脚本")
    print("=" * 60)
    
    # 检查Python版本
    check_python_version()
    
    # 安装依赖
    if not install_dependencies():
        sys.exit(1)
    
    # 设置macOS权限说明
    setup_macos_permissions()
    
    # 创建配置
    if not create_config():
        sys.exit(1)
    
    # 设置钥匙串
    setup_keyring()
    
    # 测试连接
    if not test_connection():
        print("\n⚠️  连接测试失败，请检查配置信息")
        print("您可以稍后手动运行 'python cal_sync.py --once' 来测试")
    
    # 创建启动项
    create_launchd_plist()
    
    # 运行初始同步测试
    run_initial_sync()
    
    print("\n" + "=" * 60)
    print("🎉 安装配置完成！")
    print("\n📋 使用方法：")
    print("• 执行一次同步：python cal_sync.py --once")
    print("• 启动定时同步：python cal_sync.py")
    print("• 查看日志：tail -f cal_sync.log")
    print("• 快速启动：./run_sync.sh")
    
    print("\n📁 重要文件：")
    print("• 配置文件：config.json")
    print("• 日志文件：cal_sync.log")
    print("• 同步状态：sync_state.json")
    
    print("\n🔧 故障排除：")
    print("• 查看 README.md 了解详细说明")
    print("• 检查日志文件中的错误信息")


if __name__ == "__main__":
    main()

