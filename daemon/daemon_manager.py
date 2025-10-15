#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CalSync 后台守护进程管理器
基于Python定时器实现后台运行、开机自启、状态查看等功能
"""

import os
import sys
import time
import json
import signal
import threading
import subprocess
import psutil
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import logging

# 添加项目根目录到Python路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from cal_sync import CalSync
except ImportError:
    print("错误：无法导入cal_sync模块，请确保在项目根目录运行")
    sys.exit(1)


class CalSyncDaemon:
    """CalSync后台守护进程"""
    
    def __init__(self, config_file="config.json", pid_file="daemon/cal_sync_daemon.pid"):
        self.config_file = config_file
        self.pid_file = os.path.join(PROJECT_ROOT, pid_file)
        self.log_file = os.path.join(PROJECT_ROOT, "logs/daemon.log")
        self.status_file = os.path.join(PROJECT_ROOT, "logs/daemon_status.json")
        self.running = False
        self.sync_thread = None
        self.syncer = None
        self.config = None
        self._stop_requested = False
        
        # 设置日志
        self.setup_logging()
        
        # 加载配置
        self.load_config()
    
    def setup_logging(self):
        """设置日志"""
        # 确保日志目录存在
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        
        # 创建logger
        self.logger = logging.getLogger('CalSyncDaemon')
        self.logger.setLevel(logging.INFO)
        
        # 清除现有的handlers
        self.logger.handlers.clear()
        
        # 创建formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        # 创建文件handler
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        
        # 创建控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        
        # 添加handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def load_config(self):
        """加载配置文件"""
        try:
            config_path = os.path.join(PROJECT_ROOT, self.config_file)
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            self.logger.info(f"配置文件加载成功：{config_path}")
        except Exception as e:
            self.logger.error(f"加载配置文件失败：{e}")
            sys.exit(1)
    
    def signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"收到信号 {signum}，正在停止守护进程...")
        self._stop_requested = True
        self.running = False
    
    def write_pid(self):
        """写入PID文件"""
        try:
            with open(self.pid_file, 'w') as f:
                f.write(str(os.getpid()))
            self.logger.info(f"PID文件已写入：{self.pid_file}")
        except Exception as e:
            self.logger.error(f"写入PID文件失败：{e}")
    
    def remove_pid(self):
        """删除PID文件"""
        try:
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
                self.logger.info("PID文件已删除")
        except Exception as e:
            self.logger.error(f"删除PID文件失败：{e}")
    
    def is_running(self):
        """检查守护进程是否正在运行"""
        if not os.path.exists(self.pid_file):
            self.logger.debug("PID文件不存在")
            return False
        
        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            self.logger.debug(f"读取到PID: {pid}")
            
            # 检查进程是否存在
            if psutil.pid_exists(pid):
                process = psutil.Process(pid)
                cmdline = ' '.join(process.cmdline())
                process_name = process.name()
                
                self.logger.debug(f"进程名: {process_name}, 命令行: {' '.join(process.cmdline())}")
                
                # 检查进程名称是否匹配
                if ('python' in process_name.lower() and 
                    'daemon_manager.py' in cmdline and
                    ('start' in cmdline or 'daemon' in cmdline)):
                    self.logger.debug("守护进程正在运行")
                    return True
                else:
                    # 进程不匹配，删除PID文件
                    self.logger.warning(f"进程不匹配，删除PID文件。进程名: {process_name}, 命令行: {cmdline}")
                    try:
                        os.remove(self.pid_file)
                    except:
                        pass
                    return False
            else:
                # 进程不存在，删除PID文件
                self.logger.debug("进程不存在")
                try:
                    os.remove(self.pid_file)
                except:
                    pass
                return False
            
        except Exception as e:
            self.logger.error(f"检查进程状态时发生错误：{e}")
            return False
    
    def get_status(self):
        """获取守护进程状态"""
        self.logger.debug(f"检查PID文件: {self.pid_file}")
        
        if not os.path.exists(self.pid_file):
            self.logger.debug("PID文件不存在")
            return {
                "running": False,
                "pid": None,
                "start_time": None,
                "last_sync": None,
                "next_sync": None,
                "sync_count": 0,
                "error_count": 0
            }
        
        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            self.logger.debug(f"读取到PID: {pid}")
            
            # 检查进程是否存在且匹配
            if not psutil.pid_exists(pid):
                self.logger.debug("进程不存在")
                return {
                    "running": False,
                    "pid": None,
                    "start_time": None,
                    "last_sync": None,
                    "next_sync": None,
                    "sync_count": 0,
                    "error_count": 0
                }
            
            process = psutil.Process(pid)
            cmdline = ' '.join(process.cmdline())
            process_name = process.name()
            
            self.logger.debug(f"进程名: {process_name}, 命令行: {cmdline}")
            
            if not ('python' in process_name.lower() and 
                   'daemon_manager.py' in cmdline and
                   ('start' in cmdline or 'daemon' in cmdline)):
                self.logger.debug("进程不匹配")
                return {
                    "running": False,
                    "pid": None,
                    "start_time": None,
                    "last_sync": None,
                    "next_sync": None,
                    "sync_count": 0,
                    "error_count": 0
                }
            
            start_time = datetime.fromtimestamp(process.create_time())
            
            # 读取状态文件
            status = {
                "running": True,
                "pid": pid,
                "start_time": start_time.isoformat(),
                "last_sync": None,
                "next_sync": None,
                "sync_count": 0,
                "error_count": 0
            }
            
            if os.path.exists(self.status_file):
                with open(self.status_file, 'r', encoding='utf-8') as f:
                    file_status = json.load(f)
                    # 合并状态，但保持running为True
                    status.update(file_status)
                    status["running"] = True
            
            self.logger.debug("进程检查通过，守护进程正在运行")
            return status
            
        except Exception as e:
            self.logger.error(f"获取状态失败：{e}")
            return {"running": False, "error": str(e)}
    
    def update_status(self, **kwargs):
        """更新状态文件"""
        try:
            status = {}
            if os.path.exists(self.status_file):
                with open(self.status_file, 'r', encoding='utf-8') as f:
                    status = json.load(f)
            
            status.update(kwargs)
            status["last_update"] = datetime.now().isoformat()
            
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(status, f, indent=4, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"更新状态文件失败：{e}")
    
    def sync_worker(self):
        """同步工作线程"""
        self.logger.info("同步工作线程启动")
        
        # 从配置中获取源路由参数
        source_routing = self.config.get("source_routing", {})
        caldav_indices = source_routing.get("caldav_indices", [])
        eventkit_calendars = source_routing.get("eventkit_calendars", [])
        eventkit_indices = source_routing.get("eventkit_indices", [])
        
        self.logger.info(f"源路由配置 - CalDAV索引: {caldav_indices}, EventKit日历: {eventkit_calendars}, EventKit索引: {eventkit_indices}")
        
        # 创建同步器实例，传递源路由参数
        self.syncer = CalSync(
            config_file=self.config_file,
            caldav_indices=caldav_indices if caldav_indices else None,
            eventkit_calendars=eventkit_calendars if eventkit_calendars else None,
            eventkit_indices=eventkit_indices if eventkit_indices else None
        )
        
        # 获取同步间隔
        interval_minutes = self.config.get("sync", {}).get("interval_minutes", 30)
        interval_seconds = interval_minutes * 60
        
        sync_count = 0
        error_count = 0
        
        while self.running and not self._stop_requested:
            try:
                self.logger.info(f"开始第 {sync_count + 1} 次同步...")
                start_time = time.time()
                
                # 执行同步
                success = self.syncer.sync_calendars()
                
                end_time = time.time()
                duration = end_time - start_time
                
                if success:
                    sync_count += 1
                    self.logger.info(f"第 {sync_count} 次同步成功，耗时 {duration:.2f} 秒")
                else:
                    error_count += 1
                    self.logger.error(f"第 {sync_count + 1} 次同步失败，耗时 {duration:.2f} 秒")
                
                # 更新状态
                self.update_status(
                    last_sync=datetime.now().isoformat(),
                    sync_count=sync_count,
                    error_count=error_count,
                    last_duration=duration
                )
                
                # 计算下次同步时间
                next_sync_time = datetime.now() + timedelta(seconds=interval_seconds)
                self.update_status(next_sync=next_sync_time.isoformat())
                
                # 等待下次同步
                self.logger.info(f"等待 {interval_minutes} 分钟后进行下次同步...")
                
                # 分段等待，以便能够响应停止请求
                wait_seconds = 0
                while wait_seconds < interval_seconds and self.running and not self._stop_requested:
                    time.sleep(min(10, interval_seconds - wait_seconds))
                    wait_seconds += 10
                
            except Exception as e:
                error_count += 1
                self.logger.error(f"同步过程中发生错误：{e}")
                self.update_status(error_count=error_count)
                
                # 错误后等待较短时间再重试
                wait_seconds = 0
                while wait_seconds < 60 and self.running and not self._stop_requested:
                    time.sleep(min(10, 60 - wait_seconds))
                    wait_seconds += 10
        
        self.logger.info("同步工作线程结束")
    
    def start(self):
        """启动守护进程"""
        if self.is_running():
            self.logger.warning("守护进程已在运行")
            return False
        
        self.logger.info("启动CalSync守护进程...")
        
        # 写入PID文件
        self.write_pid()
        
        # 设置运行标志
        self.running = True
        self._stop_requested = False
        
        # 启动同步线程
        self.sync_thread = threading.Thread(target=self.sync_worker, daemon=False)
        self.sync_thread.start()
        
        # 更新状态
        self.update_status(
            start_time=datetime.now().isoformat(),
            sync_count=0,
            error_count=0
        )
        
        self.logger.info("守护进程启动成功")
        return True
    
    def run_daemon(self):
        """以守护进程模式运行（主循环）"""
        if self.is_running():
            self.logger.warning("守护进程已在运行")
            return False
        
        self.logger.info("启动CalSync守护进程...")
        
        # 设置信号处理
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
        # 写入PID文件
        self.write_pid()
        
        # 设置运行标志
        self.running = True
        self._stop_requested = False
        
        # 启动同步线程
        self.sync_thread = threading.Thread(target=self.sync_worker, daemon=False)
        self.sync_thread.start()
        
        # 更新状态
        self.update_status(
            start_time=datetime.now().isoformat(),
            sync_count=0,
            error_count=0
        )
        
        self.logger.info("守护进程启动成功")
        
        # 主循环
        try:
            while self.running and not self._stop_requested:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("收到中断信号，正在停止...")
            self.running = False
        except Exception as e:
            self.logger.error(f"守护进程运行时发生错误：{e}")
            self.running = False
        finally:
            # 清理资源
            self.running = False
            self._stop_requested = True
            if self.sync_thread and self.sync_thread.is_alive():
                self.sync_thread.join(timeout=5)
            self.remove_pid()
            self.logger.info("守护进程已完全停止")
        
        return True
    
    def stop(self):
        """停止守护进程"""
        self.logger.info("停止CalSync守护进程...")
        
        # 设置停止标志
        self.running = False
        self._stop_requested = True
        
        try:
            # 如果同步线程正在运行，等待其结束
            if self.sync_thread and self.sync_thread.is_alive():
                self.logger.info("等待同步线程结束...")
                self.sync_thread.join(timeout=10)
                if self.sync_thread.is_alive():
                    self.logger.warning("同步线程未在预期时间内结束")
            
            # 删除PID文件
            self.remove_pid()
            
            # 更新状态
            self.update_status(
                running=False,
                stop_time=datetime.now().isoformat()
            )
            
            self.logger.info("守护进程已停止")
            return True
            
        except Exception as e:
            self.logger.error(f"停止守护进程失败：{e}")
            return False
    
    def kill_all_daemon_processes(self):
        """终止所有守护进程"""
        killed_count = 0
        current_pid = os.getpid()  # 获取当前进程ID，避免终止自己
        
        try:
            # 查找所有包含daemon_manager.py的Python进程
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    # 跳过当前进程
                    if proc.info['pid'] == current_pid:
                        continue
                        
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if ('python' in proc.info['name'].lower() and 
                        'daemon_manager.py' in cmdline and
                        'daemon' in cmdline):
                        
                        self.logger.info(f"发现守护进程 PID: {proc.info['pid']}")
                        
                        # 尝试优雅终止
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                            killed_count += 1
                            self.logger.info(f"已终止守护进程 PID: {proc.info['pid']}")
                        except psutil.TimeoutExpired:
                            # 如果仍然存在，强制终止
                            if proc.is_running():
                                proc.kill()
                                proc.wait(timeout=2)
                                killed_count += 1
                                self.logger.info(f"强制终止守护进程 PID: {proc.info['pid']}")
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                except Exception as e:
                    self.logger.warning(f"处理进程时出错: {e}")
                    continue
            
            # 清理PID文件
            self.remove_pid()
            
            return killed_count
            
        except Exception as e:
            self.logger.error(f"清理守护进程时出错: {e}")
            return 0
    
    def restart(self):
        """重启守护进程"""
        self.logger.info("重启CalSync守护进程...")
        
        # 先停止所有守护进程
        self.kill_all_daemon_processes()
        
        # 等待一段时间确保完全停止
        time.sleep(3)
        
        # 再启动
        return self.start()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="CalSync后台守护进程管理器")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--pid-file", default="daemon/cal_sync_daemon.pid", help="PID文件路径")
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # start命令
    start_parser = subparsers.add_parser("start", help="启动守护进程")
    
    # stop命令
    stop_parser = subparsers.add_parser("stop", help="停止守护进程")
    
    # restart命令
    restart_parser = subparsers.add_parser("restart", help="重启守护进程")
    
    # status命令
    status_parser = subparsers.add_parser("status", help="查看守护进程状态")
    
    # daemon命令
    daemon_parser = subparsers.add_parser("daemon", help="以守护进程模式运行")
    
    args = parser.parse_args()
    
    # 创建守护进程实例
    daemon = CalSyncDaemon(args.config, args.pid_file)
    
    if args.command == "start":
        if daemon.is_running():
            print("守护进程已在运行")
            sys.exit(1)
        
        # 启动守护进程模式（后台运行）
        try:
            # 使用subprocess启动后台进程
            import subprocess
            cmd = [
                sys.executable, 
                os.path.join(PROJECT_ROOT, "daemon", "daemon_manager.py"),
                "daemon"
            ]
            
            # 启动后台进程
            process = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )
            
            # 等待一下确保进程启动成功
            time.sleep(2)
            
            # 检查进程是否还在运行
            if process.poll() is None:
                print("守护进程启动成功")
                sys.exit(0)
            else:
                print("守护进程启动失败")
                sys.exit(1)
                
        except Exception as e:
            print(f"启动守护进程失败：{e}")
            sys.exit(1)
    
    elif args.command == "stop":
        killed_count = daemon.kill_all_daemon_processes()
        if killed_count > 0:
            print(f"已停止 {killed_count} 个守护进程")
        else:
            print("守护进程未运行")
    
    elif args.command == "restart":
        if daemon.restart():
            print("守护进程重启成功")
        else:
            print("守护进程重启失败")
            sys.exit(1)
    
    elif args.command == "status":
        status = daemon.get_status()
        print("CalSync守护进程状态")
        print("=" * 30)
        print(f"运行状态: {'运行中' if status.get('running') else '未运行'}")
        if status.get('running'):
            print(f"进程ID: {status.get('pid')}")
            print(f"启动时间: {status.get('start_time')}")
            print(f"上次同步: {status.get('last_sync', '未同步')}")
            print(f"下次同步: {status.get('next_sync', '未知')}")
            print(f"同步次数: {status.get('sync_count', 0)}")
            print(f"错误次数: {status.get('error_count', 0)}")
            if status.get('last_duration'):
                print(f"上次耗时: {status.get('last_duration', 0):.2f} 秒")
        else:
            print("守护进程未运行")
            sys.exit(1)  # 守护进程未运行时返回非零退出码
    
    elif args.command == "daemon":
        daemon.run_daemon()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()