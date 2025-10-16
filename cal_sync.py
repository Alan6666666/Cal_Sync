#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CalDAV到iCloud日历同步脚本
支持从CalDAV服务器同步日历事件到iCloud日历
"""

import os
import sys
import time
import logging
import argparse
import schedule
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Optional, Tuple
import json
import hashlib
import glob

try:
    import caldav
    from caldav import Calendar
    from caldav.elements import dav
    from caldav.lib import error
except ImportError:
    print("错误：需要安装caldav库。请运行：pip install caldav")
    sys.exit(1)

try:
    from icalendar import Calendar as ICal, Event, vCalAddress, vText
    from icalendar.prop import vDDDTypes
except ImportError:
    print("错误：需要安装icalendar库。请运行：pip install icalendar")
    sys.exit(1)

try:
    import keyring
    from keyring import get_password, set_password
except ImportError:
    print("错误：需要安装keyring库。请运行：pip install keyring")
    sys.exit(1)

try:
    from icloud_integration import ICloudIntegration
except ImportError:
    print("警告：无法导入iCloud集成模块，将使用模拟实现")
    ICloudIntegration = None

try:
    from mac_eventkit_bridge import read_events_from_eventkit, read_events_from_eventkit_by_indices
except ImportError:
    print("警告：无法导入EventKit桥接模块，EventKit功能将不可用")
    read_events_from_eventkit = None
    read_events_from_eventkit_by_indices = None


def _norm_text(s: Optional[str]) -> str:
    """标准化文本字段：去除多余空白、换行等"""
    s = (s or '').strip()
    # 折叠所有空白为单空格
    return ' '.join(s.split())


def _normalize_minutes_global(dt: datetime) -> datetime:
    """全局时间标准化函数，将分钟数强制调整为个位数为0或5，秒数为0"""
    if dt is None:
        return dt
    
    # 获取当前分钟数
    current_minute = dt.minute
    
    # 将分钟数标准化为个位数为0或5
    # 例如：09:29 -> 09:30, 09:44 -> 09:45, 09:59 -> 10:00
    minute_ones_digit = current_minute % 10
    
    if minute_ones_digit <= 2:
        # 0,1,2 -> 0 (向前调整)
        normalized_minute = (current_minute // 10) * 10
    elif minute_ones_digit <= 7:
        # 3,4,5,6,7 -> 5 (调整到5)
        normalized_minute = (current_minute // 10) * 10 + 5
    else:
        # 8,9 -> 下一个0 (进位到下一个整点)
        normalized_minute = ((current_minute // 10) + 1) * 10
        # 如果分钟数超过59，需要进位到下一小时
        if normalized_minute >= 60:
            # 使用timedelta进行安全的进位，避免小时数超过23
            dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            return dt
    
    # 返回标准化后的时间
    return dt.replace(minute=normalized_minute, second=0, microsecond=0)


def _is_allday_event(event: Dict) -> bool:
    """判断是否为全天事件"""
    start = event.get("start")
    end = event.get("end")
    
    # 如果开始时间是date类型（只有日期没有时间），则为全天事件
    if isinstance(start, date) and not isinstance(start, datetime):
        return True
    
    # 如果开始和结束时间都是datetime类型，检查是否跨整天
    if isinstance(start, datetime) and isinstance(end, datetime):
        # 转换为本地时间进行比较
        if start.tzinfo is not None:
            start = start.astimezone().replace(tzinfo=None)
        if end.tzinfo is not None:
            end = end.astimezone().replace(tzinfo=None)
        
        # 检查是否开始于00:00:00，结束于23:59:59或次日00:00:00
        if (start.hour == 0 and start.minute == 0 and start.second == 0 and
            ((end.hour == 23 and end.minute == 59 and end.second >= 59) or
             (end.hour == 0 and end.minute == 0 and end.second == 0 and end.date() > start.date()))):
            return True
    
    return False


def _get_event_duration_hours(event: Dict) -> float:
    """获取事件持续时间（小时）"""
    start = event.get("start")
    end = event.get("end")
    
    if not start or not end:
        return 0.0
    
    # 处理全天事件
    if isinstance(start, date) and not isinstance(start, datetime):
        if isinstance(end, date) and not isinstance(end, datetime):
            # 两个都是date类型
            duration_days = (end - start).days + 1  # +1因为包含结束日期
            return duration_days * 24.0
        elif isinstance(end, datetime):
            # 开始是date，结束是datetime
            end_date = end.date() if end.tzinfo is None else end.astimezone().date()
            duration_days = (end_date - start).days + 1
            return duration_days * 24.0
    elif isinstance(start, datetime):
        # 开始是datetime类型
        if isinstance(end, datetime):
            # 两个都是datetime类型
            if start.tzinfo is not None:
                start = start.astimezone().replace(tzinfo=None)
            if end.tzinfo is not None:
                end = end.astimezone().replace(tzinfo=None)
            
            duration = end - start
            return duration.total_seconds() / 3600.0  # 转换为小时
        elif isinstance(end, date):
            # 开始是datetime，结束是date
            start_date = start.date() if start.tzinfo is None else start.astimezone().date()
            duration_days = (end - start_date).days + 1
            return duration_days * 24.0
    
    return 0.0


def _should_ignore_allday_event(event: Dict, max_hours: int) -> bool:
    """判断是否应该忽略全天事件"""
    if not _is_allday_event(event):
        return False
    
    duration_hours = _get_event_duration_hours(event)
    
    # 如果持续时间严格大于指定小时数，则忽略
    # 例如：阈值24小时，只有超过24小时的事件才被忽略
    return duration_hours > max_hours


def _to_utc_iso(dt) -> str:
    """将时间统一转换为UTC ISO格式"""
    if dt is None:
        return ""
    
    # 如果是date类型（全天事件）
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return f"{dt.isoformat()}|ALLDAY"
    
    # 如果是datetime类型
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            # 假设为本地时区（实际应用中可能需要更智能的时区检测）
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    
    # 其他情况转为字符串
    return str(dt)


def _norm_rrule(rrule) -> str:
    """标准化RRULE字段：稳定序列化"""
    if not rrule:
        return ""
    
    try:
        raw = rrule.to_ical().decode('utf-8', errors='ignore')
        # 按分号分割并排序，避免顺序差异
        parts = [p.strip() for p in raw.split(';') if p.strip()]
        parts.sort()
        return ';'.join(parts)
    except Exception:
        return str(rrule)


def _norm_exdate(exdate) -> str:
    """标准化EXDATE字段：提取为ISO列表并排序"""
    if not exdate:
        return ""
    
    vals = []
    try:
        # icalendar的exdate.dts是一个列表
        for d in exdate.dts:
            dt = getattr(d, 'dt', d)
            vals.append(_to_utc_iso(dt))
    except Exception:
        # 兼容奇怪的实现
        vals.append(str(exdate))
    
    vals.sort()
    return ','.join(vals)


class CalSync:
    """CalDAV到iCloud日历同步器"""
    
    def __init__(self, config_file: str = "config.json", caldav_indices: List[int] = None, eventkit_calendars: List[str] = None, eventkit_indices: List[int] = None):
        """初始化同步器"""
        self.config_file = config_file
        self.config = self.load_config()
        self.ensure_logs_folder()
        self.setup_logging()
        self.merge_old_logs()
        self.caldav_client = None
        self.icloud_client = None
        self.sync_state_file = "logs/sync_state.json"
        self.backup_state_file = "logs/backup_state.json"
        self.sync_state = self.load_sync_state()
        
        # 处理源路由配置
        self.source_routing = self.config.get("source_routing", {})
        
        # 如果提供了命令行参数，覆盖配置文件设置
        if caldav_indices is not None:
            self.source_routing["caldav_indices"] = caldav_indices
        if eventkit_calendars is not None:
            self.source_routing["eventkit_calendars"] = eventkit_calendars
        if eventkit_indices is not None:
            self.source_routing["eventkit_indices"] = eventkit_indices
        
        # 确保默认值
        if "caldav_indices" not in self.source_routing:
            self.source_routing["caldav_indices"] = []
        if "eventkit_calendars" not in self.source_routing:
            self.source_routing["eventkit_calendars"] = []
        if "eventkit_indices" not in self.source_routing:
            self.source_routing["eventkit_indices"] = []
        if "fallback_on_404" not in self.source_routing:
            self.source_routing["fallback_on_404"] = True
    
    def ensure_logs_folder(self) -> bool:
        """确保logs文件夹存在"""
        try:
            if not os.path.exists("logs"):
                os.makedirs("logs")
                print("创建logs文件夹")
            return True
        except Exception as e:
            print(f"创建logs文件夹失败：{e}")
            return False
        
    def load_config(self) -> Dict:
        """加载配置文件"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            # 创建默认配置文件
            default_config = {
                "caldav": {
                    "server": "",
                    "username": "",
                    "password": "",
                    "calendar_url": ""
                },
                "icloud": {
                    "username": "",
                    "password": "",
                    "calendar_name": "CalDAV同步"
                },
                "sync": {
                    "interval_minutes": 30,
                    "sync_past_days": 30,
                    "sync_future_days": 365,
                    "expand_recurring": True,
                    "verify_threshold": 0.9,
                    "override_icloud_deletions": True
                },
                "backup": {
                    "enabled": True,
                    "interval_hours": 24,
                    "max_backups": 10,
                    "backup_folder": "backup"
                }
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            print(f"已创建配置文件：{self.config_file}")
            print("请编辑配置文件并填入您的CalDAV和iCloud凭据")
            sys.exit(1)
    
    def load_sync_state(self) -> Dict:
        """加载同步状态"""
        if os.path.exists(self.sync_state_file):
            with open(self.sync_state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
                
                # 检查是否需要迁移旧的同步状态格式
                if "events" in state and state["events"]:
                    # 检查第一个事件是否使用旧格式（只有hash和last_sync）
                    first_event_key = next(iter(state["events"]))
                    first_event = state["events"][first_event_key]
                    
                    if isinstance(first_event, dict) and "summary" not in first_event:
                        self.logger.info("检测到旧格式同步状态，将在下次同步时自动迁移")
                        # 清空旧状态，让系统重新建立
                        state["events"] = {}
                
                return state
        return {"last_sync": None, "events": {}}
    
    def save_sync_state(self):
        """保存同步状态"""
        with open(self.sync_state_file, 'w', encoding='utf-8') as f:
            json.dump(self.sync_state, f, indent=4, ensure_ascii=False)
    
    def setup_logging(self):
        """设置日志"""
        # 创建logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # 清除现有的handlers
        self.logger.handlers.clear()
        
        # 创建formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        # 创建文件handler（主日志）
        file_handler = logging.FileHandler('logs/cal_sync.log', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        
        # 创建错误日志handler
        error_handler = logging.FileHandler('logs/cal_sync_error.log', encoding='utf-8')
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        
        # 创建控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        
        # 添加handlers到logger
        self.logger.addHandler(file_handler)
        self.logger.addHandler(error_handler)
        self.logger.addHandler(console_handler)
    
    def merge_old_logs(self):
        """合并旧的日志文件到新的日志文件中"""
        try:
            # 合并旧的cal_sync_error.log
            old_error_log = "cal_sync_error.log"
            new_error_log = "logs/cal_sync_error.log"
            
            if os.path.exists(old_error_log):
                self.logger.info("正在合并旧的错误日志文件...")
                with open(old_error_log, 'r', encoding='utf-8') as old_file:
                    old_content = old_file.read()
                
                with open(new_error_log, 'a', encoding='utf-8') as new_file:
                    new_file.write("\n" + "="*50 + "\n")
                    new_file.write("以下是旧的错误日志内容：\n")
                    new_file.write("="*50 + "\n")
                    new_file.write(old_content)
                
                self.logger.info("旧错误日志文件已合并")
            
            # 合并旧的cal_sync.log
            old_log = "logs/cal_sync.log.old"
            new_log = "logs/cal_sync.log"
            
            if os.path.exists(old_log):
                self.logger.info("正在合并旧的主日志文件...")
                with open(old_log, 'r', encoding='utf-8') as old_file:
                    old_content = old_file.read()
                
                with open(new_log, 'a', encoding='utf-8') as new_file:
                    new_file.write("\n" + "="*50 + "\n")
                    new_file.write("以下是旧的主日志内容：\n")
                    new_file.write("="*50 + "\n")
                    new_file.write(old_content)
                
                self.logger.info("旧主日志文件已合并")
                
        except Exception as e:
            print(f"合并旧日志文件失败：{e}")
    
    def connect_caldav(self) -> bool:
        """连接CalDAV服务器"""
        try:
            self.logger.info("正在连接CalDAV服务器...")
            
            # 从keyring获取密码，如果没有则从配置文件获取
            password = get_password("cal_sync", self.config["caldav"]["username"])
            if not password:
                password = self.config["caldav"]["password"]
                if password:
                    set_password("cal_sync", self.config["caldav"]["username"], password)
            
            # 使用base_url，如果没有则从server构建
            if "base_url" in self.config["caldav"] and self.config["caldav"]["base_url"]:
                server_url = self.config["caldav"]["base_url"]
            else:
                # 确保URL有协议前缀
                server_url = self.config["caldav"]["server"]
                if not server_url.startswith(('http://', 'https://')):
                    server_url = f"https://{server_url}"
            
            self.caldav_client = caldav.DAVClient(
                url=server_url,
                username=self.config["caldav"]["username"],
                password=password
            )
            
            # 测试连接
            principal = self.caldav_client.principal()
            self.logger.info("CalDAV连接成功")
            return True
            
        except Exception as e:
            self.logger.error(f"CalDAV连接失败：{e}")
            return False
    
    def connect_icloud(self) -> bool:
        """连接iCloud"""
        try:
            self.logger.info("正在连接iCloud...")
            
            
            if ICloudIntegration:
                app_password = self.config["icloud"].get("app_private_password")
                self.icloud_client = ICloudIntegration(
                    self.config["icloud"]["calendar_name"], 
                    app_password
                )
                self.logger.info("iCloud集成模块加载成功")
                
                # 检查日历是否可访问
                if not self.icloud_client.check_calendar_accessibility():
                    self.logger.error("目标iCloud日历不可访问，请确保启动macOS日历应用并勾选目标日历")
                    return False
                
            else:
                self.logger.warning("iCloud集成模块不可用")
                self.icloud_client = None
            
            return True
            
        except Exception as e:
            self.logger.error(f"iCloud连接失败：{e}")
            return False
    
    def get_caldav_events(self, selected_calendar_indices: List[int] = None) -> List[Dict]:
        """获取CalDAV日历事件"""
        try:
            if not self.caldav_client:
                return []
            
            # 获取所有日历
            principal = self.caldav_client.principal()
            calendars = principal.calendars()
            
            if not calendars:
                self.logger.warning("未找到CalDAV日历")
                return []
            
            # 显示所有可用日历
            self.logger.info(f"找到 {len(calendars)} 个可用日历:")
            for i, cal in enumerate(calendars):
                self.logger.info(f"  {i+1}. {cal.name} (URL: {cal.url})")
            
            # 确定要使用的日历
            selected_calendars = []
            
            # 如果指定了日历索引列表
            if selected_calendar_indices:
                for idx in selected_calendar_indices:
                    if 1 <= idx <= len(calendars):
                        selected_calendars.append(calendars[idx-1])
                        self.logger.info(f"选择日历 {idx}: {calendars[idx-1].name}")
                    else:
                        self.logger.warning(f"无效的日历索引: {idx} (有效范围: 1-{len(calendars)})")
            # 如果配置文件中指定了日历索引
            elif self.config["caldav"].get("selected_calendars"):
                for idx in self.config["caldav"]["selected_calendars"]:
                    if 1 <= idx <= len(calendars):
                        selected_calendars.append(calendars[idx-1])
                        self.logger.info(f"从配置选择日历 {idx}: {calendars[idx-1].name}")
                    else:
                        self.logger.warning(f"配置中的无效日历索引: {idx} (有效范围: 1-{len(calendars)})")
            # 如果指定了特定日历URL
            elif self.config["caldav"].get("calendar_url"):
                for cal in calendars:
                    if cal.url == self.config["caldav"]["calendar_url"]:
                        selected_calendars.append(cal)
                        self.logger.info(f"使用指定的日历URL: {cal.name}")
                        break
                else:
                    self.logger.warning(f"未找到指定的日历URL，使用所有可用日历")
                    selected_calendars = calendars
            # 默认使用所有日历
            else:
                selected_calendars = calendars
                self.logger.info(f"使用所有可用日历（共{len(calendars)}个）")
            
            if not selected_calendars:
                self.logger.error("没有选择任何日历")
                return []
            
            # 设置时间范围
            start_date = datetime.now() - timedelta(days=self.config["sync"]["sync_past_days"])
            end_date = datetime.now() + timedelta(days=self.config["sync"]["sync_future_days"])
            
            # 从所有选中的日历中获取事件
            all_events = []
            expand_recurring = self.config["sync"].get("expand_recurring", True)
            
            for calendar in selected_calendars:
                self.logger.info(f"正在从日历 '{calendar.name}' 获取事件...")
                
                try:
                    events = calendar.search(
                        start=start_date,
                        end=end_date,
                        event=True,
                        expand=expand_recurring
                    )
                    
                    calendar_event_count = 0
                    for event in events:
                        try:
                            ical_data = event.data
                            cal = ICal.from_ical(ical_data)
                            
                            for component in cal.walk():
                                if component.name == "VEVENT":
                                    event_dict = self.parse_ical_event(component)
                                    if event_dict:
                                        # 为每个事件添加来源日历信息
                                        event_dict["source_calendar"] = calendar.name
                                        event_dict["source_calendar_url"] = calendar.url
                                        all_events.append(event_dict)
                                        calendar_event_count += 1
                                        
                        except Exception as e:
                            self.logger.warning(f"解析事件失败：{e}")
                            continue
                    
                    self.logger.info(f"从日历 '{calendar.name}' 获取到 {calendar_event_count} 个事件")
                    
                except Exception as e:
                    self.logger.error(f"从日历 '{calendar.name}' 获取事件失败：{e}")
                    continue
            
            self.logger.info(f"总共获取到 {len(all_events)} 个CalDAV事件")
            
            # 调试：显示所有事件的详细信息
            for i, event in enumerate(all_events):
                self.logger.debug(f"事件 {i+1}: {event.get('summary', 'Unknown')} (来源: {event.get('source_calendar', 'Unknown')}, UID: {event.get('uid', 'No UID')}, Key: {event.get('stable_key', 'No Key')}, 循环实例: {event.get('is_recurring_instance', False)})")
            
            return all_events
            
        except Exception as e:
            self.logger.error(f"获取CalDAV事件失败：{e}")
            return []
    
    def get_events_via_eventkit(self, calendar_names: List[str]) -> List[Dict]:
        """通过EventKit获取事件"""
        try:
            if not read_events_from_eventkit:
                self.logger.error("EventKit桥接模块不可用")
                return []
            
            self.logger.info(f"正在从EventKit获取事件，日历：{calendar_names}")
            
            # 使用配置的时间窗
            days_past = self.config["sync"]["sync_past_days"]
            days_future = self.config["sync"]["sync_future_days"]
            
            # 调用EventKit桥接函数（现在返回元组）
            events, debug_info = read_events_from_eventkit(calendar_names, days_past, days_future)
            
            # 如果没有事件但有调试信息，记录诊断信息
            if not events and debug_info:
                self.logger.warning(f"EventKit返回为空，诊断信息：\n{debug_info}")
                
                # 尝试一次重试
                self.logger.info("尝试EventKit重试...")
                import time
                time.sleep(2)  # 短暂等待
                events, debug_info2 = read_events_from_eventkit(calendar_names, days_past, days_future)
                if not events and debug_info2:
                    self.logger.warning(f"EventKit重试仍为空，诊断信息：\n{debug_info2}")
            
            # 为每个事件添加来源信息
            for event in events:
                event["source_calendar"] = f"EventKit:{calendar_names[0]}" if calendar_names else "EventKit:Unknown"
                event["source_calendar_url"] = "EventKit://local"
            
            self.logger.info(f"从EventKit获取到 {len(events)} 个事件")
            
            # 调试：显示所有事件的详细信息
            for i, event in enumerate(events):
                self.logger.debug(f"EventKit事件 {i+1}: {event.get('summary', 'Unknown')} (来源: {event.get('source_calendar', 'Unknown')}, UID: {event.get('uid', 'No UID')}, Key: {event.get('stable_key', 'No Key')}, 循环实例: {event.get('is_recurring_instance', False)})")
            
            return events
            
        except Exception as e:
            self.logger.error(f"通过EventKit获取事件失败：{e}")
            return []
    
    def get_events_via_eventkit_by_indices(self, caldav_calendar_indices: List[int]) -> List[Dict]:
        """通过 CalDAV 日历索引获取对应的 EventKit 事件"""
        try:
            if not read_events_from_eventkit_by_indices:
                self.logger.error("EventKit桥接模块不可用")
                return []
            
            # 获取 CalDAV 日历名称
            if not self.caldav_client:
                self.logger.error("CalDAV客户端未初始化")
                return []
            
            principal = self.caldav_client.principal()
            calendars = principal.calendars()
            
            caldav_calendar_names = []
            for idx in caldav_calendar_indices:
                if 1 <= idx <= len(calendars):
                    calendar_name = calendars[idx-1].name
                    caldav_calendar_names.append(calendar_name)
                    self.logger.info(f"CalDAV 索引 {idx} 对应日历：{calendar_name}")
                else:
                    self.logger.warning(f"无效的 CalDAV 日历索引：{idx}")
            
            if not caldav_calendar_names:
                self.logger.error("没有找到有效的 CalDAV 日历")
                return []
            
            self.logger.info(f"正在从EventKit获取事件，CalDAV索引：{caldav_calendar_indices}，对应日历：{caldav_calendar_names}")
            
            # 使用配置的时间窗
            days_past = self.config["sync"]["sync_past_days"]
            days_future = self.config["sync"]["sync_future_days"]
            
            # 调用EventKit桥接函数（现在返回元组）
            events, debug_info = read_events_from_eventkit_by_indices(caldav_calendar_indices, caldav_calendar_names, days_past, days_future)
            
            # 如果没有事件但有调试信息，记录诊断信息
            if not events and debug_info:
                self.logger.warning(f"EventKit返回为空，诊断信息：\n{debug_info}")
                
                # 尝试一次重试
                self.logger.info("尝试EventKit重试...")
                import time
                time.sleep(2)  # 短暂等待
                events, debug_info2 = read_events_from_eventkit_by_indices(caldav_calendar_indices, caldav_calendar_names, days_past, days_future)
                if not events and debug_info2:
                    self.logger.warning(f"EventKit重试仍为空，诊断信息：\n{debug_info2}")
            
            # 为每个事件添加来源信息
            for event in events:
                event["source_calendar"] = f"EventKit:{caldav_calendar_names[0]}" if caldav_calendar_names else "EventKit:Unknown"
                event["source_calendar_url"] = "EventKit://local"
            
            self.logger.info(f"从EventKit获取到 {len(events)} 个事件")
            
            # 调试：显示所有事件的详细信息
            for i, event in enumerate(events):
                self.logger.debug(f"EventKit事件 {i+1}: {event.get('summary', 'Unknown')} (来源: {event.get('source_calendar', 'Unknown')}, UID: {event.get('uid', 'No UID')}, Key: {event.get('stable_key', 'No Key')}, 循环实例: {event.get('is_recurring_instance', False)})")
            
            return events
            
        except Exception as e:
            self.logger.error(f"通过EventKit索引获取事件失败：{e}")
            return []
    
    def filter_allday_events(self, events: List[Dict]) -> List[Dict]:
        """过滤掉持续时间过长的全天事件"""
        try:
            # 获取配置参数
            max_hours = self.config["sync"].get("ignore_allday_events_longer_than_hours", None)
            
            # 如果没有设置过滤参数，返回所有事件
            if max_hours is None:
                return events
            
            filtered_events = []
            ignored_count = 0
            
            for event in events:
                if _should_ignore_allday_event(event, max_hours):
                    ignored_count += 1
                    duration_hours = _get_event_duration_hours(event)
                    self.logger.info(f"忽略全天事件：{event.get('summary', 'Unknown')} (持续时间: {duration_hours:.1f}小时, 阈值: {max_hours}小时)")
                else:
                    filtered_events.append(event)
            
            if ignored_count > 0:
                self.logger.info(f"过滤结果：忽略 {ignored_count} 个全天事件，保留 {len(filtered_events)} 个事件")
            
            return filtered_events
            
        except Exception as e:
            self.logger.error(f"过滤全天事件时发生错误：{e}")
            return events

    def get_source_events(self, selected_calendar_indices: List[int] = None) -> List[Dict]:
        """统一入口：根据配置获取源事件（CalDAV + EventKit）"""
        try:
            all_events = []
            caldav_events = []
            eventkit_events = []
            
            # 获取CalDAV事件
            caldav_indices = self.source_routing.get("caldav_indices", [])
            if caldav_indices:
                self.logger.info(f"使用CalDAV获取日历索引：{caldav_indices}")
                caldav_events = self.get_caldav_events(caldav_indices)
                all_events.extend(caldav_events)
                
                # 检查是否需要回退到EventKit
                if self.source_routing.get("fallback_on_404", False):
                    caldav_events = self._check_and_fallback_to_eventkit(caldav_events, caldav_indices)
                    # 重新获取CalDAV事件（可能已经回退）
                    all_events = caldav_events.copy()
            
            # 获取EventKit事件
            eventkit_calendars = self.source_routing.get("eventkit_calendars", [])
            eventkit_indices = self.source_routing.get("eventkit_indices", [])
            
            if eventkit_calendars:
                self.logger.info(f"使用EventKit获取日历：{eventkit_calendars}")
                eventkit_events = self.get_events_via_eventkit(eventkit_calendars)
                all_events.extend(eventkit_events)
            elif eventkit_indices:
                self.logger.info(f"使用EventKit获取日历索引：{eventkit_indices}")
                eventkit_events = self.get_events_via_eventkit_by_indices(eventkit_indices)
                all_events.extend(eventkit_events)
            
            # 去重：以stable_key为准，后加入的忽略
            unique_events = {}
            for event in all_events:
                stable_key = event.get("stable_key")
                if stable_key and stable_key not in unique_events:
                    unique_events[stable_key] = event
            
            final_events = list(unique_events.values())
            
            self.logger.info(f"合并后总事件数：{len(final_events)} (CalDAV: {len(caldav_events)}, EventKit: {len(eventkit_events)})")
            
            # 应用全天事件过滤
            filtered_events = self.filter_allday_events(final_events)
            
            return filtered_events
            
        except Exception as e:
            self.logger.error(f"获取源事件失败：{e}")
            return []
    
    def _check_and_fallback_to_eventkit(self, caldav_events: List[Dict], caldav_indices: List[int]) -> List[Dict]:
        """检查CalDAV事件获取情况，必要时回退到EventKit"""
        try:
            # 获取CalDAV日历名称映射
            if not self.caldav_client:
                return caldav_events
            
            principal = self.caldav_client.principal()
            calendars = principal.calendars()
            
            fallback_needed = False
            fallback_calendars = []
            
            for idx in caldav_indices:
                if 1 <= idx <= len(calendars):
                    calendar = calendars[idx-1]
                    calendar_name = calendar.name
                    
                    # 检查该日历的事件数量是否异常少
                    calendar_events = [e for e in caldav_events if e.get("source_calendar") == calendar_name]
                    
                    # 如果事件数量少于预期阈值（比如少于5个），可能需要回退
                    if len(calendar_events) < 5:
                        self.logger.warning(f"日历 '{calendar_name}' 事件数量异常少（{len(calendar_events)}个），可能需要回退到EventKit")
                        fallback_needed = True
                        fallback_calendars.append(calendar_name)
            
            if fallback_needed and fallback_calendars:
                self.logger.info(f"尝试回退到EventKit获取日历：{fallback_calendars}")
                eventkit_events = self.get_events_via_eventkit(fallback_calendars)
                
                if eventkit_events:
                    self.logger.info(f"EventKit回退成功，获取到 {len(eventkit_events)} 个事件")
                    # 替换CalDAV事件
                    filtered_caldav_events = [e for e in caldav_events if e.get("source_calendar") not in fallback_calendars]
                    return filtered_caldav_events + eventkit_events
                else:
                    self.logger.warning("EventKit回退失败，继续使用CalDAV事件")
            
            return caldav_events
            
        except Exception as e:
            self.logger.error(f"检查CalDAV回退条件失败：{e}")
            return caldav_events
    
    def parse_ical_event(self, event) -> Optional[Dict]:
        """解析iCal事件"""
        try:
            # 获取基本字段
            uid = event.get("UID")
            if not uid:
                self.logger.warning("事件缺少UID，跳过")
                return None
            uid = str(uid)
            
            # 获取循环相关字段
            recurrence_id = event.get("RECURRENCE-ID")
            rrule = event.get("RRULE")
            exdate = event.get("EXDATE")
            
            # 创建稳定主键：UID + RECURRENCE-ID（如果有）
            if recurrence_id:
                # 保留完整的RECURRENCE-ID ISO格式
                rec_id_dt = recurrence_id.dt if hasattr(recurrence_id, 'dt') else recurrence_id
                if hasattr(rec_id_dt, 'isoformat'):
                    rec_id_str = rec_id_dt.isoformat()
                else:
                    rec_id_str = str(rec_id_dt)
                stable_key = f"{uid}#{rec_id_str}"
                is_recurring_instance = True
            else:
                stable_key = uid
                is_recurring_instance = False
            
            # 标准化字段
            rrule_norm = _norm_rrule(rrule)
            exdate_norm = _norm_exdate(exdate)
            
            # 处理raw_data解码
            try:
                raw_bytes = event.to_ical()
                raw_data = raw_bytes.decode('utf-8', errors='ignore')
            except Exception:
                raw_data = str(event.to_ical(), 'utf-8', errors='ignore')
            
            # 在描述中添加同步标记以便在iCloud中识别
            description = _norm_text(event.get("DESCRIPTION", ""))
            if description:
                sync_marker = f" [SYNC_UID:{stable_key}]"
                if sync_marker not in description:
                    description += sync_marker
            else:
                description = f"[SYNC_UID:{stable_key}]"
            
            # 获取并标准化时间字段
            start_dt = event.get("DTSTART").dt if event.get("DTSTART") else None
            end_dt = event.get("DTEND").dt if event.get("DTEND") else None
            
            # 对开始和结束时间进行标准化
            if isinstance(start_dt, datetime):
                # 转换为本地时间（去掉时区信息）
                if start_dt.tzinfo is not None:
                    start_dt = start_dt.astimezone().replace(tzinfo=None)
                start_dt = _normalize_minutes_global(start_dt)
            
            if isinstance(end_dt, datetime):
                # 转换为本地时间（去掉时区信息）
                if end_dt.tzinfo is not None:
                    end_dt = end_dt.astimezone().replace(tzinfo=None)
                end_dt = _normalize_minutes_global(end_dt)
            
            event_dict = {
                "uid": uid,
                "stable_key": stable_key,  # 稳定主键
                "summary": _norm_text(event.get("SUMMARY", "")),
                "description": description,  # 包含同步标记
                "location": _norm_text(event.get("LOCATION", "")),
                "start": start_dt,
                "end": end_dt,
                "created": event.get("CREATED").dt if event.get("CREATED") else None,
                "last_modified": event.get("LAST-MODIFIED").dt if event.get("LAST-MODIFIED") else None,
                "recurrence_id": rec_id_str if recurrence_id else None,
                "rrule": rrule_norm,
                "exdate": exdate_norm,
                "is_recurring_instance": is_recurring_instance,
                "raw_data": raw_data
            }
            
            # 生成事件哈希用于比较
            event_dict["hash"] = self.generate_event_hash(event_dict)
            
            return event_dict
            
        except Exception as e:
            self.logger.warning(f"解析iCal事件失败：{e}")
            return None
    
    def generate_event_hash(self, event: Dict) -> str:
        """生成事件哈希值用于比较"""
        # 只使用稳定的语义字段，移除元数据字段避免误报修改
        hash_fields = [
            event.get('stable_key', event.get('uid', '')),  # 稳定主键
            _norm_text(event.get('summary', '')),  # 重新标准化
            _norm_text(event.get('description', '')),  # 重新标准化
            _norm_text(event.get('location', '')),  # 重新标准化
            event.get('rrule', '') or '',  # 已标准化
            event.get('exdate', '') or '',  # 已标准化
        ]
        
        # 统一转换为UTC ISO格式的时间
        hash_fields.append(_to_utc_iso(event.get('start')))
        hash_fields.append(_to_utc_iso(event.get('end')))
        
        # 包含RECURRENCE-ID（如果有）
        if event.get('recurrence_id'):
            hash_fields.append(event.get('recurrence_id'))
        
        hash_string = '||'.join(hash_fields)  # 使用双分隔符避免字段边界问题
        return hashlib.md5(hash_string.encode('utf-8')).hexdigest()
    
    def extract_sync_keys_from_icloud_events(self, icloud_events: List[Dict]) -> set:
        """从iCloud事件中提取同步标记的键"""
        sync_keys = set()
        
        for event in icloud_events:
            description = event.get('description', '')
            if description:
                # 只比较描述的前200字符，与创建时的截断逻辑保持一致
                description_to_check = description[:200]
                # 查找同步标记 [SYNC_UID:key]
                import re
                matches = re.findall(r'\[SYNC_UID:([^\]]+)\]', description_to_check)
                for match in matches:
                    sync_keys.add(match)
        
        return sync_keys
    
    def detect_icloud_deletions(self, caldav_events: List[Dict]) -> List[Dict]:
        """检测iCloud中被手动删除的事件"""
        try:
            self.logger.info("检测iCloud中被手动删除的事件...")
            
            if not self.icloud_client:
                self.logger.warning("iCloud客户端未初始化，跳过检测")
                return []
            
            # 获取iCloud中的事件
            icloud_events = self.icloud_client.get_existing_events()
            
            # 检查是否超时
            if icloud_events == "TIMEOUT":
                self.logger.error("获取iCloud事件超时，跳过删除检测以避免重复创建事件")
                return "TIMEOUT"
            
            # 检查日历是否不可访问
            if icloud_events is None:
                self.logger.warning("iCloud日历不可访问，跳过删除检测")
                self.logger.warning("请确保在macOS日历应用中勾选目标日历")
                return []
            
            icloud_sync_keys = self.extract_sync_keys_from_icloud_events(icloud_events)
            
            # 获取CalDAV事件的键
            caldav_keys = {event["stable_key"] for event in caldav_events}
            
            # 检查同步状态中的键
            synced_keys = set(self.sync_state["events"].keys())
            
            # 找出应该在iCloud中但实际缺失的事件
            # 这些事件在CalDAV中存在，在同步状态中存在，但在iCloud中不存在
            missing_in_icloud = []
            for stable_key in synced_keys & caldav_keys:
                if stable_key not in icloud_sync_keys:
                    # 找到对应的CalDAV事件
                    caldav_event = next((e for e in caldav_events if e["stable_key"] == stable_key), None)
                    if caldav_event:
                        missing_in_icloud.append(caldav_event)
                        self.logger.info(f"检测到iCloud中缺失的事件：{caldav_event.get('summary', 'Unknown')} (Key: {stable_key})")
            
            if missing_in_icloud:
                self.logger.warning(f"发现 {len(missing_in_icloud)} 个在iCloud中被手动删除的事件")
                
                # 安全检查：如果缺失事件数量超过总事件的一半，可能是检测错误
                total_caldav_events = len(caldav_events)
                if len(missing_in_icloud) > total_caldav_events * 0.5:
                    # 检查是否启用了跳过同步的安全功能
                    skip_sync_on_too_many_missing = self.config["sync"].get("skip_sync_on_too_many_missing", True)
                    
                    if skip_sync_on_too_many_missing:
                        self.logger.error(f"检测到过多缺失事件（{len(missing_in_icloud)}/{total_caldav_events}），可能是AppleScript检测错误")
                        self.logger.error("为避免重复创建事件，本次同步将被跳过")
                        self.logger.info("如需禁用此安全功能，请在配置文件中设置 'skip_sync_on_too_many_missing': false")
                        return "TOO_MANY_MISSING"
                    else:
                        self.logger.warning(f"检测到过多缺失事件（{len(missing_in_icloud)}/{total_caldav_events}），但安全功能已禁用，将继续同步")
                        self.logger.warning("请注意：这可能会导致重复创建事件，请确保iCloud日历状态正常")
            else:
                self.logger.info("未发现iCloud中被手动删除的事件")
            
            return missing_in_icloud
            
        except Exception as e:
            self.logger.error(f"检测iCloud删除事件时发生错误：{e}")
            return []
    
    def sync_to_icloud(self, added_events: List[Dict], modified_events: List[Dict], deleted_events: List[Dict], icloud_recovery_events: List[Dict] = None) -> bool:
        """同步事件到iCloud"""
        try:
            self.logger.info("开始同步到iCloud...")
            
            # 写入约束检查：只能写入目标iCloud日历
            assert self.icloud_client is not None, "No iCloud client"
            # 严格禁止其它写入：不允许出现 'save', 'commit', 'remove' 等对非 iCloud 目标日历的调用
            
            if not self.icloud_client:
                self.logger.error("iCloud客户端未初始化")
                return False
            
            # 检查真正需要的方法
            required_methods = ('create_event', 'delete_event_by_summary', 'delete_event_by_sync_uid', 'get_existing_events')
            missing_methods = [m for m in required_methods if not hasattr(self.icloud_client, m)]
            if missing_methods:
                self.logger.error(f"iCloud客户端缺少必要方法: {', '.join(missing_methods)}")
                return False
            
            # 处理iCloud恢复事件（如果未提供则设为空列表）
            if icloud_recovery_events is None:
                icloud_recovery_events = []
            
            success_count = 0
            total_events = len(added_events) + len(modified_events) + len(deleted_events) + len(icloud_recovery_events)
            
            if total_events == 0:
                self.logger.info("没有需要同步的事件")
                return True
            
            self.logger.info(f"开始同步 {total_events} 个事件到iCloud日历")
            
            # 处理新增事件
            for event in added_events:
                if self.icloud_client.create_event(event):
                    stable_key = event["stable_key"]
                    self.sync_state["events"][stable_key] = {
                        "uid": event["uid"],
                        "summary": event["summary"],
                        "hash": event["hash"],
                        "last_sync": datetime.now().isoformat()
                    }
                    success_count += 1
                    self.logger.info(f"✅ 新增事件：{event.get('summary', 'Unknown')} (Key: {stable_key})")
                else:
                    self.logger.error(f"❌ 新增事件失败：{event.get('summary', 'Unknown')}")
            
            # 处理修改事件（删除旧事件，创建新事件）
            for event in modified_events:
                stable_key = event["stable_key"]
                event_summary = event.get('summary', 'Unknown')
                
                # 优先使用精确的同步UID删除旧事件，避免误删循环事件的其他实例
                self.logger.info(f"正在删除旧事件：{event_summary} (Key: {stable_key})")
                delete_success = self.icloud_client.delete_event_by_sync_uid(stable_key)
                
                if delete_success:
                    self.logger.info(f"旧事件精确删除成功：{event_summary}")
                else:
                    # 如果精确删除失败，回退到按标题删除（但会记录警告）
                    self.logger.warning(f"精确删除失败，尝试按标题删除：{event_summary}")
                    delete_success = self.icloud_client.delete_event_by_summary(event_summary)
                    if delete_success:
                        self.logger.warning(f"旧事件按标题删除成功：{event_summary} - 可能误删了其他同名事件")
                    else:
                        self.logger.warning(f"旧事件删除失败，继续创建新事件：{event_summary}")
                
                # 然后创建新事件
                if self.icloud_client.create_event(event):
                    self.sync_state["events"][stable_key] = {
                        "uid": event["uid"],
                        "summary": event["summary"],
                        "hash": event["hash"],
                        "last_sync": datetime.now().isoformat()
                    }
                    success_count += 1
                    self.logger.info(f"✅ 修改事件：{event_summary} (Key: {stable_key})")
                else:
                    self.logger.error(f"❌ 修改事件失败：{event_summary}")
            
            # 处理删除事件
            for event in deleted_events:
                stable_key = event["stable_key"]
                event_summary = event.get("summary", stable_key)
                
                # 优先使用精确的同步UID删除方法，避免误删循环事件的其他实例
                if self.icloud_client.delete_event_by_sync_uid(stable_key):
                    if stable_key in self.sync_state["events"]:
                        del self.sync_state["events"][stable_key]
                    success_count += 1
                    self.logger.info(f"✅ 删除事件：{event_summary} (Key: {stable_key})")
                else:
                    # 如果精确删除失败，回退到按标题删除（但会记录警告）
                    self.logger.warning(f"精确删除失败，尝试按标题删除：{event_summary}")
                    if self.icloud_client.delete_event_by_summary(event_summary):
                        if stable_key in self.sync_state["events"]:
                            del self.sync_state["events"][stable_key]
                        success_count += 1
                        self.logger.warning(f"✅ 按标题删除事件成功：{event_summary} (Key: {stable_key}) - 可能误删了其他同名事件")
                    else:
                        self.logger.error(f"❌ 删除事件失败：{event_summary}")
            
            # 处理iCloud恢复事件（重新创建被手动删除的事件）
            for event in icloud_recovery_events:
                if self.icloud_client.create_event(event):
                    stable_key = event["stable_key"]
                    # 更新同步状态（这些事件本来就在状态中，只是iCloud中被删除了）
                    if stable_key in self.sync_state["events"]:
                        self.sync_state["events"][stable_key]["last_sync"] = datetime.now().isoformat()
                    success_count += 1
                    self.logger.info(f"✅ 恢复事件：{event.get('summary', 'Unknown')} (Key: {stable_key}) - 重新创建被手动删除的事件")
                else:
                    self.logger.error(f"❌ 恢复事件失败：{event.get('summary', 'Unknown')}")
            
            # 更新同步状态
            self.sync_state["last_sync"] = datetime.now().isoformat()
            self.save_sync_state()
            
            self.logger.info(f"成功同步 {success_count}/{total_events} 个事件")
            self.logger.info("iCloud同步完成")
            return success_count > 0
            
        except Exception as e:
            self.logger.error(f"iCloud同步失败：{e}")
            return False
    
    def detect_changes(self, current_events: List[Dict]) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """检测事件变化"""
        added_events = []
        modified_events = []
        deleted_events = []
        
        # 使用稳定主键进行比较
        current_keys = {event["stable_key"] for event in current_events}
        synced_keys = set(self.sync_state["events"].keys())
        
        # 检测新增事件
        for event in current_events:
            stable_key = event["stable_key"]
            if stable_key not in synced_keys:
                added_events.append(event)
                self.logger.info(f"检测到新增事件：{event.get('summary', 'Unknown')} (Key: {stable_key})")
            else:
                self.logger.debug(f"事件已在同步状态中：{event.get('summary', 'Unknown')} (Key: {stable_key})")
        
        # 检测删除的事件
        for stable_key in synced_keys:
            if stable_key not in current_keys:
                # 获取要删除的事件信息用于日志
                event_info = self.sync_state["events"].get(stable_key, {})
                event_summary = event_info.get('summary', stable_key)
                event_uid = event_info.get('uid', stable_key)
                deleted_events.append({
                    "uid": event_uid,
                    "stable_key": stable_key,
                    "summary": event_summary
                })
                self.logger.info(f"检测到删除事件：{event_summary} (Key: {stable_key})")
        
        # 检测修改事件（基于内容比较）
        for event in current_events:
            stable_key = event["stable_key"]
            if stable_key in synced_keys:
                stored_hash = self.sync_state["events"][stable_key]["hash"]
                current_hash = event["hash"]
                if current_hash != stored_hash:
                    modified_events.append(event)
                    self.logger.info(f"检测到修改事件：{event.get('summary', 'Unknown')} (Key: {stable_key})")
                    self.logger.debug(f"哈希变化：{stored_hash[:8]}... -> {current_hash[:8]}...")
                else:
                    self.logger.debug(f"事件未变化：{event.get('summary', 'Unknown')} (Key: {stable_key}, 哈希: {current_hash[:8]}...)")
            else:
                self.logger.debug(f"事件不在同步状态中：{event.get('summary', 'Unknown')} (Key: {stable_key})")
        
        return added_events, modified_events, deleted_events
    
    def verify_sync(self, caldav_events: List[Dict]) -> bool:
        """验证同步结果，确保CalDAV和iCloud日历基本一致"""
        try:
            self.logger.info("开始验证同步结果...")
            
            # 获取iCloud日历中的事件
            icloud_events = self.icloud_client.get_existing_events()
            
            # 检查日历是否不可访问
            if icloud_events is None:
                self.logger.warning("iCloud日历不可访问，跳过验证")
                self.logger.warning("请确保在macOS日历应用中勾选目标日历")
                return False
            
            # 比较事件数量
            caldav_count = len(caldav_events)
            icloud_count = len(icloud_events)
            
            self.logger.info(f"CalDAV事件数量: {caldav_count}")
            self.logger.info(f"iCloud事件数量: {icloud_count}")
            
            # 允许事件数量有小的差异（±2），因为循环事件展开可能有差异
            if abs(caldav_count - icloud_count) > 2:
                self.logger.warning(f"事件数量差异较大：CalDAV有{caldav_count}个，iCloud有{icloud_count}个")
                # 不直接返回False，而是继续检查内容匹配
            
            # 基于同步状态进行验证：检查已同步的事件是否在iCloud中存在
            synced_keys = set(self.sync_state["events"].keys())
            caldav_keys = {event["stable_key"] for event in caldav_events}
            
            # 从iCloud事件中提取同步标记的键
            icloud_sync_keys = self.extract_sync_keys_from_icloud_events(icloud_events)
            
            self.logger.info(f"CalDAV事件键: {len(caldav_keys)}")
            self.logger.info(f"同步状态键: {len(synced_keys)}")
            self.logger.info(f"iCloud同步标记键: {len(icloud_sync_keys)}")
            
            # 检查是否有应该同步但不在当前CalDAV事件中的事件
            orphaned_sync_keys = synced_keys - caldav_keys
            if orphaned_sync_keys:
                self.logger.warning(f"发现孤立同步状态：{len(orphaned_sync_keys)} 个事件")
                # 清理孤立的同步状态
                for key in orphaned_sync_keys:
                    del self.sync_state["events"][key]
                self.save_sync_state()
            
            # 检查当前CalDAV事件中有多少已正确同步到iCloud
            synced_caldav_keys = synced_keys & caldav_keys
            actually_in_icloud_keys = caldav_keys & icloud_sync_keys
            
            # 计算真实的同步覆盖率：CalDAV事件中有多少在iCloud中真正存在
            real_sync_coverage = len(actually_in_icloud_keys) / max(len(caldav_keys), 1)
            state_sync_coverage = len(synced_caldav_keys) / max(len(caldav_keys), 1)
            
            self.logger.info(f"状态表同步覆盖率: {state_sync_coverage:.2%} ({len(synced_caldav_keys)}/{len(caldav_keys)})")
            self.logger.info(f"实际iCloud同步覆盖率: {real_sync_coverage:.2%} ({len(actually_in_icloud_keys)}/{len(caldav_keys)})")
            
            # 使用配置的验证阈值
            verify_threshold = self.config["sync"].get("verify_threshold", 0.9)
            if real_sync_coverage < verify_threshold:
                missing_keys = caldav_keys - icloud_sync_keys
                if missing_keys:
                    self.logger.warning(f"在iCloud中缺失的事件键: {list(missing_keys)[:5]}...")  # 只显示前5个
                    
                    # 如果启用了iCloud删除覆盖功能，这些缺失的事件应该在下一次同步中被恢复
                    override_icloud_deletions = self.config["sync"].get("override_icloud_deletions", True)
                    if override_icloud_deletions:
                        self.logger.info("已启用iCloud删除覆盖功能，这些缺失的事件将在下次同步时自动恢复")
                
                self.logger.warning(f"实际同步覆盖率较低: {real_sync_coverage:.2%}")
                return False
            
            # 作为额外检查，比较标题集合（但使用更宽松的标准）
            caldav_summaries = {event.get('summary', '').strip() for event in caldav_events if event.get('summary', '').strip()}
            icloud_summaries = {event.get('summary', '').strip() for event in icloud_events if event.get('summary', '').strip()}
            
            common_summaries = caldav_summaries & icloud_summaries
            summary_match_ratio = len(common_summaries) / max(len(caldav_summaries), 1)
            
            self.logger.info(f"标题匹配度: {summary_match_ratio:.2%} ({len(common_summaries)}/{len(caldav_summaries)})")
            
            # 标题匹配度低于70%才认为验证失败
            if summary_match_ratio < 0.7:
                missing_in_icloud = caldav_summaries - icloud_summaries
                extra_in_icloud = icloud_summaries - caldav_summaries
                
                if missing_in_icloud:
                    self.logger.warning(f"iCloud中缺少的事件标题: {list(missing_in_icloud)[:3]}...")  # 只显示前3个
                if extra_in_icloud:
                    self.logger.warning(f"iCloud中多余的事件标题: {list(extra_in_icloud)[:3]}...")  # 只显示前3个
                
                self.logger.warning(f"标题匹配度过低: {summary_match_ratio:.2%}")
                return False
            
            self.logger.info("✅ 事件内容验证通过")
            return True
            
        except Exception as e:
            self.logger.error(f"验证同步结果时发生错误：{e}")
            return False
    
    def force_resync(self, caldav_events: List[Dict]) -> bool:
        """强制重新同步，清空iCloud日历并重新创建所有事件"""
        try:
            self.logger.info("开始强制重新同步...")
            
            # 清空iCloud日历中的所有事件
            self.logger.info("清空iCloud日历...")
            self.icloud_client.clear_all_events()
            
            # 重新创建所有CalDAV事件
            self.logger.info("重新创建所有事件...")
            success_count = 0
            for event in caldav_events:
                if self.icloud_client.create_event(event):
                    success_count += 1
                    self.logger.info(f"✅ 重新创建事件：{event.get('summary', 'Unknown')}")
                else:
                    self.logger.error(f"❌ 重新创建事件失败：{event.get('summary', 'Unknown')}")
            
            # 更新同步状态
            self.sync_state["events"] = {}
            for event in caldav_events:
                stable_key = event["stable_key"]
                if stable_key in self.sync_state["events"]:
                    self.logger.warning(f"发现重复的稳定键：{stable_key} ({event.get('summary', 'Unknown')})")
                self.sync_state["events"][stable_key] = {
                    "uid": event["uid"],
                    "summary": event["summary"],
                    "hash": event["hash"],
                    "last_sync": datetime.now().isoformat()
                }
            self.sync_state["last_sync"] = datetime.now().isoformat()
            self.save_sync_state()
            
            self.logger.info(f"同步状态已更新：{len(self.sync_state['events'])} 个事件")
            
            self.logger.info(f"强制重新同步完成：成功创建 {success_count}/{len(caldav_events)} 个事件")
            
            # 再次验证
            if self.verify_sync(caldav_events):
                self.logger.info("✅ 强制重新同步验证通过")
                return True
            else:
                self.logger.error("❌ 强制重新同步验证失败")
                return False
                
        except Exception as e:
            self.logger.error(f"强制重新同步失败：{e}")
            return False
    
    def sync_calendars(self, selected_calendar_indices: List[int] = None):
        """执行日历同步"""
        try:
            self.logger.info("开始日历同步...")
            
            # 连接CalDAV
            if not self.connect_caldav():
                return False
            
            # 连接iCloud
            if not self.connect_icloud():
                return False
            
            # 获取源事件（CalDAV + EventKit）
            current_events = self.get_source_events(selected_calendar_indices)
            if not current_events:
                self.logger.info("没有找到需要同步的事件")
                return True
            
            # 执行备份（如果启用）
            if self.config.get("backup", {}).get("enabled", False):
                self.backup_caldav_events(current_events)
            
            # 检测变化
            added, modified, deleted = self.detect_changes(current_events)
            
            # 检测iCloud中被手动删除的事件
            icloud_deletions = []
            override_icloud_deletions = self.config["sync"].get("override_icloud_deletions", True)
            if override_icloud_deletions:
                icloud_deletions = self.detect_icloud_deletions(current_events)
                
                # 检查是否超时或检测到过多缺失事件
                if icloud_deletions == "TIMEOUT":
                    self.logger.error("由于AppleScript超时，本次同步被跳过以避免重复创建事件")
                    self.logger.info("同步执行成功")
                    return True
                elif icloud_deletions == "TOO_MANY_MISSING":
                    self.logger.error("由于检测到过多缺失事件，本次同步被跳过以避免重复创建事件")
                    self.logger.info("同步执行成功")
                    return True
            
            total_changes = len(added) + len(modified) + len(deleted) + len(icloud_deletions)
            self.logger.info(f"检测到变化：新增 {len(added)} 个，修改 {len(modified)} 个，删除 {len(deleted)} 个，iCloud恢复 {len(icloud_deletions)} 个")
            
            # 显示详细的变化统计
            if added:
                self.logger.info("新增事件详情:")
                for event in added:
                    self.logger.info(f"  + {event.get('summary', 'Unknown')} (Key: {event.get('stable_key')})")
            
            if modified:
                self.logger.info("修改事件详情:")
                for event in modified:
                    self.logger.info(f"  ~ {event.get('summary', 'Unknown')} (Key: {event.get('stable_key')})")
            
            if deleted:
                self.logger.info("删除事件详情:")
                for event in deleted:
                    self.logger.info(f"  - {event.get('summary', 'Unknown')} (Key: {event.get('stable_key')})")
            
            if icloud_deletions:
                self.logger.info("iCloud恢复事件详情:")
                for event in icloud_deletions:
                    self.logger.info(f"  ↻ {event.get('summary', 'Unknown')} (Key: {event.get('stable_key')}) - 恢复被手动删除的事件")
            
            # 同步到iCloud
            if total_changes > 0:
                if self.sync_to_icloud(added, modified, deleted, icloud_deletions):
                    self.logger.info("日历同步完成")
                    # 验证同步结果
                    if self.verify_sync(current_events):
                        self.logger.info("✅ 同步验证通过：CalDAV和iCloud日历完全一致")
                        return True
                    else:
                        self.logger.error("❌ 同步验证失败：CalDAV和iCloud日历不一致")
                        # 尝试强制重新同步
                        self.logger.info("尝试强制重新同步...")
                        return self.force_resync(current_events)
                else:
                    self.logger.error("日历同步失败")
                    return False
            else:
                self.logger.info("没有检测到变化，跳过同步")
                return True
                
        except Exception as e:
            self.logger.error(f"同步过程中发生错误：{e}")
            return False
    
    def run_sync(self, selected_calendar_indices: List[int] = None):
        """运行一次同步"""
        self.logger.info("=" * 50)
        self.logger.info("开始执行日历同步")
        success = self.sync_calendars(selected_calendar_indices)
        if success:
            self.logger.info("同步执行成功")
        else:
            self.logger.error("同步执行失败")
        self.logger.info("=" * 50)
    
    def start_scheduled_sync(self):
        """启动定时同步"""
        interval = self.config["sync"]["interval_minutes"]
        self.logger.info(f"启动定时同步，间隔：{interval} 分钟")
        
        # 立即执行一次同步
        self.run_sync()
        
        # 设置定时任务
        schedule.every(interval).minutes.do(self.run_sync)
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # 每分钟检查一次
        except KeyboardInterrupt:
            self.logger.info("收到停止信号，正在退出...")
        except Exception as e:
            self.logger.error(f"定时同步发生错误：{e}")
    
    def ensure_backup_folder(self) -> bool:
        """确保备份文件夹存在"""
        try:
            backup_folder = self.config.get("backup", {}).get("backup_folder", "backup")
            if not os.path.exists(backup_folder):
                os.makedirs(backup_folder)
                self.logger.info(f"创建备份文件夹：{backup_folder}")
            return True
        except Exception as e:
            self.logger.error(f"创建备份文件夹失败：{e}")
            return False
    
    def export_events_to_ics(self, events: List[Dict]) -> str:
        """将事件列表导出为ICS格式字符串"""
        try:
            # 创建iCalendar对象
            cal = ICal()
            cal.add('prodid', '-//CalSync Backup//CalDAV Events//CN')
            cal.add('version', '2.0')
            cal.add('calscale', 'GREGORIAN')
            cal.add('method', 'PUBLISH')
            
            # 按UID分组事件，处理循环事件
            events_by_uid = {}
            for event_data in events:
                uid = event_data.get('uid')
                if uid not in events_by_uid:
                    events_by_uid[uid] = []
                events_by_uid[uid].append(event_data)
            
            # 处理每个UID组
            for uid, event_group in events_by_uid.items():
                if len(event_group) > 1:
                    # 这是循环事件组，只导出第一个事件并添加RRULE
                    main_event = event_group[0]
                    self._add_recurring_event_to_calendar(cal, main_event, event_group)
                else:
                    # 单个事件
                    self._add_single_event_to_calendar(cal, event_group[0])
            
            # 返回ICS字符串
            return cal.to_ical().decode('utf-8')
            
        except Exception as e:
            self.logger.error(f"导出ICS失败：{e}")
            return ""
    
    def _add_single_event_to_calendar(self, cal: ICal, event_data: Dict):
        """添加单个事件到日历"""
        try:
            event = Event()
            
            # 基本字段
            if event_data.get('uid'):
                event.add('uid', event_data['uid'])
            if event_data.get('summary'):
                event.add('summary', event_data['summary'])
            if event_data.get('description'):
                # 移除同步标记，保持原始描述
                description = event_data['description']
                # 移除 [SYNC_UID:xxx] 标记
                import re
                description = re.sub(r'\s*\[SYNC_UID:[^\]]+\]', '', description)
                if description.strip():
                    event.add('description', description.strip())
            if event_data.get('location'):
                event.add('location', event_data['location'])
            
            # 时间字段
            if event_data.get('start'):
                event.add('dtstart', event_data['start'])
            if event_data.get('end'):
                event.add('dtend', event_data['end'])
            
            # 创建和修改时间
            if event_data.get('created'):
                event.add('created', event_data['created'])
            if event_data.get('last_modified'):
                event.add('last-modified', event_data['last_modified'])
            
            # 来源日历信息
            if event_data.get('source_calendar'):
                event.add('x-source-calendar', event_data['source_calendar'])
            
            cal.add_component(event)
            
        except Exception as e:
            self.logger.warning(f"添加单个事件失败：{e}")
    
    def _add_recurring_event_to_calendar(self, cal: ICal, main_event: Dict, event_group: List[Dict]):
        """添加循环事件到日历"""
        try:
            event = Event()
            
            # 基本字段
            if main_event.get('uid'):
                event.add('uid', main_event['uid'])
            if main_event.get('summary'):
                event.add('summary', main_event['summary'])
            if main_event.get('description'):
                # 移除同步标记，保持原始描述
                description = main_event['description']
                # 移除 [SYNC_UID:xxx] 标记
                import re
                description = re.sub(r'\s*\[SYNC_UID:[^\]]+\]', '', description)
                if description.strip():
                    event.add('description', description.strip())
            if main_event.get('location'):
                event.add('location', main_event['location'])
            
            # 时间字段
            if main_event.get('start'):
                event.add('dtstart', main_event['start'])
            if main_event.get('end'):
                event.add('dtend', main_event['end'])
            
            # 创建和修改时间
            if main_event.get('created'):
                event.add('created', main_event['created'])
            if main_event.get('last_modified'):
                event.add('last-modified', main_event['last_modified'])
            
            # 从描述中提取循环信息并构建RRULE
            rrule = self._extract_rrule_from_description(main_event.get('description', ''))
            if rrule:
                try:
                    from icalendar import vRecur
                    event.add('rrule', vRecur(rrule))
                except Exception as e:
                    self.logger.warning(f"添加RRULE失败：{e}")
            
            # 来源日历信息
            if main_event.get('source_calendar'):
                event.add('x-source-calendar', main_event['source_calendar'])
            
            cal.add_component(event)
            
        except Exception as e:
            self.logger.warning(f"添加循环事件失败：{e}")
    
    def _extract_rrule_from_description(self, description: str) -> Dict:
        """从描述中提取循环规则"""
        try:
            import re
            
            # 查找循环周期信息
            # 例如："重复周期：2025/09/26-2029/07/20 10:30-11:30, 每周 (周五)"
            pattern = r'重复周期：.*?每周\s*\(([^)]+)\)'
            match = re.search(pattern, description)
            
            if match:
                weekday = match.group(1)
                weekday_map = {
                    '周一': 'MO', '周二': 'TU', '周三': 'WE', '周四': 'TH',
                    '周五': 'FR', '周六': 'SA', '周日': 'SU'
                }
                
                if weekday in weekday_map:
                    return {
                        'FREQ': 'WEEKLY',
                        'BYDAY': weekday_map[weekday]
                    }
            
            # 如果没有找到具体的循环信息，使用默认的每周循环
            return {
                'FREQ': 'WEEKLY'
            }
            
        except Exception as e:
            self.logger.warning(f"提取循环规则失败：{e}")
            return {}
    
    def _add_event_to_calendar_old(self, cal: ICal, event_data: Dict):
        """旧的添加事件方法（保留作为备用）"""
        try:
            event = Event()
            
            # 基本字段
            if event_data.get('uid'):
                event.add('uid', event_data['uid'])
            if event_data.get('summary'):
                event.add('summary', event_data['summary'])
            if event_data.get('description'):
                # 移除同步标记，保持原始描述
                description = event_data['description']
                # 移除 [SYNC_UID:xxx] 标记
                import re
                description = re.sub(r'\s*\[SYNC_UID:[^\]]+\]', '', description)
                if description.strip():
                    event.add('description', description.strip())
            if event_data.get('location'):
                event.add('location', event_data['location'])
            
            # 时间字段
            if event_data.get('start'):
                event.add('dtstart', event_data['start'])
            if event_data.get('end'):
                event.add('dtend', event_data['end'])
            
            # 创建和修改时间
            if event_data.get('created'):
                event.add('created', event_data['created'])
            if event_data.get('last_modified'):
                event.add('last-modified', event_data['last_modified'])
            
            # 循环规则（只有主事件才有RRULE）
            if event_data.get('rrule') and not event_data.get('is_recurring_instance'):
                # 需要重新解析RRULE字符串
                try:
                    from icalendar import vRecur
                    rrule_parts = {}
                    for part in event_data['rrule'].split(';'):
                        if '=' in part:
                            key, value = part.split('=', 1)
                            rrule_parts[key.strip()] = value.strip()
                    if rrule_parts:
                        event.add('rrule', vRecur(rrule_parts))
                except Exception as e:
                    self.logger.warning(f"解析RRULE失败：{e}")
            
            # 循环实例标识（只有实例事件才有RECURRENCE-ID）
            if event_data.get('recurrence_id') and event_data.get('is_recurring_instance'):
                try:
                    from icalendar import vDDDTypes
                    # 解析RECURRENCE-ID
                    rec_id_str = event_data['recurrence_id']
                    if 'T' in rec_id_str:
                        rec_id_dt = datetime.fromisoformat(rec_id_str.replace('Z', '+00:00'))
                    else:
                        rec_id_dt = datetime.fromisoformat(rec_id_str)
                    event.add('recurrence-id', rec_id_dt)
                except Exception as e:
                    self.logger.warning(f"解析RECURRENCE-ID失败：{e}")
            
            # 异常日期（只有主事件才有EXDATE）
            if event_data.get('exdate') and not event_data.get('is_recurring_instance'):
                try:
                    from icalendar import vDDDTypes
                    exdates = []
                    for exdate_str in event_data['exdate'].split(','):
                        if exdate_str.strip():
                            # 尝试解析ISO格式日期
                            try:
                                if 'T' in exdate_str:
                                    dt = datetime.fromisoformat(exdate_str.replace('Z', '+00:00'))
                                else:
                                    dt = datetime.fromisoformat(exdate_str)
                                exdates.append(dt)
                            except ValueError:
                                continue
                    if exdates:
                        event.add('exdate', exdates)
                except Exception as e:
                    self.logger.warning(f"解析EXDATE失败：{e}")
            
            # 来源日历信息
            if event_data.get('source_calendar'):
                event.add('x-source-calendar', event_data['source_calendar'])
            
            cal.add_component(event)
            
        except Exception as e:
            self.logger.warning(f"添加事件失败：{e}")
    
    def export_events_to_ics_old(self, events: List[Dict]) -> str:
        """旧的导出方法（保留作为备用）"""
        try:
            # 创建iCalendar对象
            cal = ICal()
            cal.add('prodid', '-//CalSync Backup//CalDAV Events//CN')
            cal.add('version', '2.0')
            cal.add('calscale', 'GREGORIAN')
            cal.add('method', 'PUBLISH')
            
            # 添加每个事件
            for event_data in events:
                event = Event()
                
                # 基本字段
                if event_data.get('uid'):
                    event.add('uid', event_data['uid'])
                if event_data.get('summary'):
                    event.add('summary', event_data['summary'])
                if event_data.get('description'):
                    # 移除同步标记，保持原始描述
                    description = event_data['description']
                    # 移除 [SYNC_UID:xxx] 标记
                    import re
                    description = re.sub(r'\s*\[SYNC_UID:[^\]]+\]', '', description)
                    if description.strip():
                        event.add('description', description.strip())
                if event_data.get('location'):
                    event.add('location', event_data['location'])
                
                # 时间字段
                if event_data.get('start'):
                    event.add('dtstart', event_data['start'])
                if event_data.get('end'):
                    event.add('dtend', event_data['end'])
                
                # 创建和修改时间
                if event_data.get('created'):
                    event.add('created', event_data['created'])
                if event_data.get('last_modified'):
                    event.add('last-modified', event_data['last_modified'])
                
                # 循环规则（只有主事件才有RRULE）
                if event_data.get('rrule') and not event_data.get('is_recurring_instance'):
                    # 需要重新解析RRULE字符串
                    try:
                        from icalendar import vRecur
                        rrule_parts = {}
                        for part in event_data['rrule'].split(';'):
                            if '=' in part:
                                key, value = part.split('=', 1)
                                rrule_parts[key.strip()] = value.strip()
                        if rrule_parts:
                            event.add('rrule', vRecur(rrule_parts))
                    except Exception as e:
                        self.logger.warning(f"解析RRULE失败：{e}")
                
                # 循环实例标识（只有实例事件才有RECURRENCE-ID）
                if event_data.get('recurrence_id') and event_data.get('is_recurring_instance'):
                    try:
                        from icalendar import vDDDTypes
                        # 解析RECURRENCE-ID
                        rec_id_str = event_data['recurrence_id']
                        if 'T' in rec_id_str:
                            rec_id_dt = datetime.fromisoformat(rec_id_str.replace('Z', '+00:00'))
                        else:
                            rec_id_dt = datetime.fromisoformat(rec_id_str)
                        event.add('recurrence-id', rec_id_dt)
                    except Exception as e:
                        self.logger.warning(f"解析RECURRENCE-ID失败：{e}")
                
                # 异常日期（只有主事件才有EXDATE）
                if event_data.get('exdate') and not event_data.get('is_recurring_instance'):
                    try:
                        from icalendar import vDDDTypes
                        exdates = []
                        for exdate_str in event_data['exdate'].split(','):
                            if exdate_str.strip():
                                # 尝试解析ISO格式日期
                                try:
                                    if 'T' in exdate_str:
                                        dt = datetime.fromisoformat(exdate_str.replace('Z', '+00:00'))
                                    else:
                                        dt = datetime.fromisoformat(exdate_str)
                                    exdates.append(dt)
                                except ValueError:
                                    continue
                        if exdates:
                            event.add('exdate', exdates)
                    except Exception as e:
                        self.logger.warning(f"解析EXDATE失败：{e}")
                
                # 来源日历信息
                if event_data.get('source_calendar'):
                    event.add('x-source-calendar', event_data['source_calendar'])
                
                cal.add_component(event)
            
            # 返回ICS字符串
            return cal.to_ical().decode('utf-8')
            
        except Exception as e:
            self.logger.error(f"导出ICS失败：{e}")
            return ""
    
    def generate_backup_filename(self) -> str:
        """生成备份文件名（backup+日期格式）"""
        now = datetime.now()
        date_str = now.strftime("%Y%m%d_%H%M%S")
        return f"backup_{date_str}.ics"
    
    def cleanup_old_backups(self) -> bool:
        """清理旧的备份文件，保留最近的备份"""
        try:
            backup_folder = self.config.get("backup", {}).get("backup_folder", "backup")
            max_backups = self.config.get("backup", {}).get("max_backups", 10)
            
            if not os.path.exists(backup_folder):
                return True
            
            # 获取所有备份文件
            backup_pattern = os.path.join(backup_folder, "backup_*.ics")
            backup_files = glob.glob(backup_pattern)
            
            if len(backup_files) <= max_backups:
                return True
            
            # 按修改时间排序，保留最新的
            backup_files.sort(key=os.path.getmtime, reverse=True)
            files_to_delete = backup_files[max_backups:]
            
            deleted_count = 0
            for file_path in files_to_delete:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                    self.logger.info(f"删除旧备份文件：{os.path.basename(file_path)}")
                except Exception as e:
                    self.logger.warning(f"删除备份文件失败 {file_path}：{e}")
            
            if deleted_count > 0:
                self.logger.info(f"清理完成，删除了 {deleted_count} 个旧备份文件")
            
            return True
            
        except Exception as e:
            self.logger.error(f"清理旧备份失败：{e}")
            return False
    
    def should_run_backup(self) -> bool:
        """检查是否应该执行备份"""
        try:
            backup_config = self.config.get("backup", {})
            if not backup_config.get("enabled", False):
                return False
            
            # 检查上次备份时间
            if os.path.exists(self.backup_state_file):
                with open(self.backup_state_file, 'r', encoding='utf-8') as f:
                    backup_state = json.load(f)
                last_backup = backup_state.get("last_backup")
                if last_backup:
                    last_backup_time = datetime.fromisoformat(last_backup)
                    interval_hours = backup_config.get("interval_hours", 24)
                    time_diff = datetime.now() - last_backup_time
                    if time_diff.total_seconds() < interval_hours * 3600:
                        return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"检查备份条件失败：{e}")
            return True  # 出错时执行备份
    
    def save_backup_state(self):
        """保存备份状态"""
        try:
            backup_state = {
                "last_backup": datetime.now().isoformat()
            }
            with open(self.backup_state_file, 'w', encoding='utf-8') as f:
                json.dump(backup_state, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"保存备份状态失败：{e}")
    
    def backup_caldav_events(self, events: List[Dict]) -> bool:
        """备份CalDAV事件到ICS文件"""
        try:
            # 检查是否应该执行备份
            if not self.should_run_backup():
                return True
            
            self.logger.info("开始备份CalDAV事件...")
            
            # 确保备份文件夹存在
            if not self.ensure_backup_folder():
                return False
            
            # 导出事件为ICS格式
            ics_content = self.export_events_to_ics(events)
            if not ics_content:
                self.logger.error("导出ICS内容失败")
                return False
            
            # 生成备份文件名
            backup_filename = self.generate_backup_filename()
            backup_folder = self.config.get("backup", {}).get("backup_folder", "backup")
            backup_path = os.path.join(backup_folder, backup_filename)
            
            # 写入备份文件
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(ics_content)
            
            self.logger.info(f"备份成功：{backup_filename} ({len(events)} 个事件)")
            
            # 清理旧备份
            self.cleanup_old_backups()
            
            # 保存备份状态
            self.save_backup_state()
            
            return True
            
        except Exception as e:
            self.logger.error(f"备份CalDAV事件失败：{e}")
            return False
    
    def force_backup_caldav_events(self, events: List[Dict]) -> bool:
        """强制执行CalDAV事件备份（手动备份）"""
        try:
            self.logger.info("开始手动备份CalDAV事件...")
            
            # 确保备份文件夹存在
            if not self.ensure_backup_folder():
                return False
            
            # 导出事件为ICS格式
            ics_content = self.export_events_to_ics(events)
            if not ics_content:
                self.logger.error("导出ICS内容失败")
                return False
            
            # 生成备份文件名
            backup_filename = self.generate_backup_filename()
            backup_folder = self.config.get("backup", {}).get("backup_folder", "backup")
            backup_path = os.path.join(backup_folder, backup_filename)
            
            # 写入备份文件
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(ics_content)
            
            self.logger.info(f"手动备份成功：{backup_filename} ({len(events)} 个事件)")
            
            # 清理旧备份
            self.cleanup_old_backups()
            
            # 保存备份状态
            self.save_backup_state()
            
            return True
            
        except Exception as e:
            self.logger.error(f"手动备份CalDAV事件失败：{e}")
            return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="CalDAV到iCloud日历同步工具")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="只执行一次同步")
    parser.add_argument("--daemon", action="store_true", help="以守护进程模式运行")
    parser.add_argument("--select-calendars", type=str, help="选择要同步的日历索引，用逗号分隔，如：1,3,5")
    parser.add_argument("--list-calendars", action="store_true", help="列出所有可用日历")
    parser.add_argument("--backup", action="store_true", help="强制执行一次备份")
    parser.add_argument("--force-resync", action="store_true", help="强制重新同步：清空iCloud日历并重新创建所有事件")
    parser.add_argument("--caldav-indices", type=str, help="指定使用CalDAV的日历索引，用逗号分隔，如：1,3")
    parser.add_argument("--eventkit-calendars", type=str, help="指定使用EventKit的日历名称，用逗号分隔，如：同事共享B,第三方服务")
    parser.add_argument("--eventkit-indices", type=str, help="指定使用EventKit的日历索引（对应CalDAV索引），用逗号分隔，如：5")
    
    args = parser.parse_args()
    
    # 解析命令行参数
    caldav_indices = None
    eventkit_calendars = None
    eventkit_indices = None
    
    if args.caldav_indices:
        try:
            caldav_indices = [int(x.strip()) for x in args.caldav_indices.split(',')]
            print(f"CalDAV日历索引: {caldav_indices}")
        except ValueError as e:
            print(f"错误：无效的CalDAV日历索引格式。请使用逗号分隔的数字，如：1,3")
            return
    
    if args.eventkit_calendars:
        eventkit_calendars = [x.strip() for x in args.eventkit_calendars.split(',')]
        print(f"EventKit日历名称: {eventkit_calendars}")
    
    if args.eventkit_indices:
        try:
            eventkit_indices = [int(x.strip()) for x in args.eventkit_indices.split(',')]
            print(f"EventKit日历索引: {eventkit_indices}")
        except ValueError as e:
            print(f"错误：无效的EventKit日历索引格式。请使用逗号分隔的数字，如：5")
            return
    
    # 创建同步器
    syncer = CalSync(args.config, caldav_indices, eventkit_calendars, eventkit_indices)
    
    # 解析日历选择参数（向后兼容）
    selected_calendar_indices = None
    if args.select_calendars:
        try:
            selected_calendar_indices = [int(x.strip()) for x in args.select_calendars.split(',')]
            print(f"选择的日历索引: {selected_calendar_indices}")
        except ValueError as e:
            print(f"错误：无效的日历索引格式。请使用逗号分隔的数字，如：1,3,5")
            return
    
    # 如果只是列出日历
    if args.list_calendars:
        if syncer.connect_caldav():
            # 获取所有日历并显示
            principal = syncer.caldav_client.principal()
            calendars = principal.calendars()
            
            if calendars:
                print(f"\n找到 {len(calendars)} 个可用日历:")
                for i, cal in enumerate(calendars):
                    print(f"  {i+1}. {cal.name}")
                    print(f"     URL: {cal.url}")
            else:
                print("未找到任何日历")
        return
    
    # 如果是手动备份
    if args.backup:
        syncer.logger.info("=" * 50)
        syncer.logger.info("开始执行手动备份")
        
        # 连接CalDAV
        if not syncer.connect_caldav():
            syncer.logger.error("CalDAV连接失败，无法执行备份")
            return
        
        # 获取源事件（CalDAV + EventKit）
        current_events = syncer.get_source_events(selected_calendar_indices)
        if not current_events:
            syncer.logger.info("没有找到需要备份的事件")
            return
        
        # 执行手动备份
        if syncer.force_backup_caldav_events(current_events):
            syncer.logger.info("手动备份执行成功")
        else:
            syncer.logger.error("手动备份执行失败")
        
        syncer.logger.info("=" * 50)
        return
    
    # 如果是强制重新同步
    if args.force_resync:
        syncer.logger.info("=" * 50)
        syncer.logger.info("开始执行强制重新同步")
        syncer.logger.warning("⚠️  警告：此操作将清空目标iCloud日历中的所有事件并重新创建")
        
        # 连接CalDAV
        if not syncer.connect_caldav():
            syncer.logger.error("CalDAV连接失败，无法执行强制重新同步")
            return
        
        # 连接iCloud
        if not syncer.connect_icloud():
            syncer.logger.error("iCloud连接失败，无法执行强制重新同步")
            return
        
        # 获取源事件（CalDAV + EventKit）
        current_events = syncer.get_source_events(selected_calendar_indices)
        if not current_events:
            syncer.logger.info("没有找到需要同步的事件")
            return
        
        # 执行强制重新同步
        if syncer.force_resync(current_events):
            syncer.logger.info("强制重新同步执行成功")
        else:
            syncer.logger.error("强制重新同步执行失败")
        
        syncer.logger.info("=" * 50)
        return
    
    if args.once:
        # 只执行一次同步
        syncer.run_sync(selected_calendar_indices)
    else:
        # 启动定时同步
        syncer.start_scheduled_sync()


if __name__ == "__main__":
    main()
