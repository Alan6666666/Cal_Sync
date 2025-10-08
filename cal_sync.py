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


def _norm_text(s: Optional[str]) -> str:
    """标准化文本字段：去除多余空白、换行等"""
    s = (s or '').strip()
    # 折叠所有空白为单空格
    return ' '.join(s.split())


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
    
    def __init__(self, config_file: str = "config.json"):
        """初始化同步器"""
        self.config_file = config_file
        self.config = self.load_config()
        self.setup_logging()
        self.caldav_client = None
        self.icloud_client = None
        self.sync_state_file = "sync_state.json"
        self.sync_state = self.load_sync_state()
        
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
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('cal_sync.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
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
            
            event_dict = {
                "uid": uid,
                "stable_key": stable_key,  # 稳定主键
                "summary": _norm_text(event.get("SUMMARY", "")),
                "description": description,  # 包含同步标记
                "location": _norm_text(event.get("LOCATION", "")),
                "start": event.get("DTSTART").dt if event.get("DTSTART") else None,
                "end": event.get("DTEND").dt if event.get("DTEND") else None,
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
                # 查找同步标记 [SYNC_UID:key]
                import re
                matches = re.findall(r'\[SYNC_UID:([^\]]+)\]', description)
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
            
            if not self.icloud_client:
                self.logger.error("iCloud客户端未初始化")
                return False
            
            # 检查真正需要的方法
            required_methods = ('create_event', 'delete_event_by_summary', 'get_existing_events')
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
                
                # 先尝试根据标题删除旧事件
                self.logger.info(f"正在删除旧事件：{event_summary} (Key: {stable_key})")
                delete_success = self.icloud_client.delete_event_by_summary(event_summary)
                
                if delete_success:
                    self.logger.info(f"旧事件删除成功：{event_summary}")
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
                
                # 使用根据标题删除的方法
                if self.icloud_client.delete_event_by_summary(event_summary):
                    if stable_key in self.sync_state["events"]:
                        del self.sync_state["events"][stable_key]
                    success_count += 1
                    self.logger.info(f"✅ 删除事件：{event_summary} (Key: {stable_key})")
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
            
            # 获取CalDAV事件（支持多日历选择）
            current_events = self.get_caldav_events(selected_calendar_indices)
            if not current_events:
                self.logger.info("没有找到需要同步的事件")
                return True
            
            # 检测变化
            added, modified, deleted = self.detect_changes(current_events)
            
            # 检测iCloud中被手动删除的事件
            icloud_deletions = []
            override_icloud_deletions = self.config["sync"].get("override_icloud_deletions", True)
            if override_icloud_deletions:
                icloud_deletions = self.detect_icloud_deletions(current_events)
            
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


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="CalDAV到iCloud日历同步工具")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="只执行一次同步")
    parser.add_argument("--daemon", action="store_true", help="以守护进程模式运行")
    parser.add_argument("--select-calendars", type=str, help="选择要同步的日历索引，用逗号分隔，如：1,3,5")
    parser.add_argument("--list-calendars", action="store_true", help="列出所有可用日历")
    
    args = parser.parse_args()
    
    # 创建同步器
    syncer = CalSync(args.config)
    
    # 解析日历选择参数
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
    
    if args.once:
        # 只执行一次同步
        syncer.run_sync(selected_calendar_indices)
    else:
        # 启动定时同步
        syncer.start_scheduled_sync()


if __name__ == "__main__":
    main()
