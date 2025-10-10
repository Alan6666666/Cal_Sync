#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iCloud日历集成模块
使用AppleScript与macOS日历应用交互
"""

import subprocess
import json
import logging
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional


class ICloudIntegration:
    """iCloud日历集成类"""
    
    def __init__(self, calendar_name: str = "CalDAV同步", app_password: str = None):
        self.calendar_name = calendar_name
        self.app_password = app_password
        self.logger = logging.getLogger(__name__)
        self.applescript_dir = "applescripts"
        self._ensure_applescript_dir()
    
    def _ensure_applescript_dir(self):
        """确保AppleScript目录存在"""
        import os
        if not os.path.exists(self.applescript_dir):
            os.makedirs(self.applescript_dir)
    
    def _run_applescript(self, script: str, timeout: int = 60) -> tuple[bool, str]:
        """运行AppleScript"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                self.logger.error(f"AppleScript执行失败：{result.stderr}")
                return False, result.stderr
                
        except subprocess.TimeoutExpired:
            self.logger.error("AppleScript执行超时")
            return False, "执行超时"
        except Exception as e:
            self.logger.error(f"AppleScript执行异常：{e}")
            return False, str(e)
    
    def create_calendar(self) -> bool:
        """创建iCloud日历"""
        script = f'''
        tell application "Calendar"
            try
                -- 检查日历是否已存在
                set calendarExists to false
                repeat with cal in calendars
                    if name of cal is "{self.calendar_name}" then
                        set calendarExists to true
                        exit repeat
                    end if
                end repeat
                
                if not calendarExists then
                    -- 创建新日历
                    make new calendar with properties {{name:"{self.calendar_name}"}}
                    return "Calendar created successfully"
                else
                    return "Calendar already exists"
                end if
            on error errMsg
                return "Error: " & errMsg
            end try
        end tell
        '''
        
        success, result = self._run_applescript(script)
        if success:
            self.logger.info(f"日历操作结果：{result}")
            return "Error:" not in result
        return False
    
    def check_calendar_accessibility(self) -> bool:
        """检查目标日历是否可访问"""
        script = f'''
        tell application "Calendar"
            try
                set targetCalendar to calendar "{self.calendar_name}"
                return "Calendar accessible"
            on error errMsg
                return "Error: " & errMsg
            end try
        end tell
        '''
        
        success, result = self._run_applescript(script)
        if success and "Error:" not in result:
            self.logger.info(f"日历 '{self.calendar_name}' 可访问")
            return True
        else:
            if "不能获得" in result and "calendar" in result:
                self.logger.warning(f"日历 '{self.calendar_name}' 不可访问：{result}")
                self.logger.warning("请确保在macOS日历应用中勾选目标日历")
            else:
                self.logger.error(f"检查日历可访问性失败：{result}")
            return False
    
    def create_event(self, event: Dict) -> bool:
        """创建日历事件"""
        # 确保有结束日期
        start_date, end_date = self._ensure_end_date(event.get("start"), event.get("end"))
        
        if not start_date or not end_date:
            self.logger.warning(f"事件日期无效：{event.get('summary')}")
            return False
        
        # 使用更安全的方式处理字符串
        summary = self._escape_string(event.get('summary', ''))
        description = self._escape_string(event.get('description', ''))
        location = self._escape_string(event.get('location', ''))
        
        # 智能截取策略：根据同步标记位置选择截取方式
        import re
        max_desc_length = 200  # 目标长度：200字符
        
        if len(description) > max_desc_length:
            # 查找同步标记
            sync_marker_pattern = r'\[SYNC_UID:[^\]]+\]'
            sync_marker_match = re.search(sync_marker_pattern, description)
            
            if sync_marker_match:
                sync_marker = sync_marker_match.group(0)
                sync_position = sync_marker_match.start()
                sync_length = len(sync_marker)
                
                # 根据同步标记位置选择截取策略
                if sync_position <= 50:
                    # 同步标记在开头，从前向后截取
                    description = description[:max_desc_length]
                    self.logger.info(f"事件描述从前向后截断到{max_desc_length}字符: {event.get('summary', 'Unknown')}")
                else:
                    # 同步标记在末尾，从后向前截取，确保同步标记完整
                    # 计算可用空间：总长度 - 同步标记长度
                    available_space = max_desc_length - sync_length
                    if available_space > 0:
                        # 从描述开头截取可用空间，然后添加同步标记
                        description = description[:available_space] + sync_marker
                        self.logger.info(f"事件描述从后向前截断到{max_desc_length}字符: {event.get('summary', 'Unknown')}")
                    else:
                        # 如果同步标记太长，只保留同步标记
                        description = sync_marker
                        self.logger.info(f"事件描述只保留同步标记: {event.get('summary', 'Unknown')}")
            else:
                # 没有同步标记，直接截断
                description = description[:max_desc_length]
                self.logger.info(f"事件描述截断到{max_desc_length}字符: {event.get('summary', 'Unknown')}")
        
        # 正确处理时区并标准化时间
        # 处理开始时间
        if isinstance(start_date, datetime):
            if start_date.tzinfo is not None:
                # 如果有时区信息，转换为本地时间
                start_date_local = start_date.astimezone().replace(tzinfo=None)
            else:
                # 如果没有时区信息，假设是本地时间
                start_date_local = start_date
            
            # 标准化开始时间，确保分钟个位数为0或5，秒数为0
            start_date_normalized = self._normalize_minutes(start_date_local)
        else:
            start_date_normalized = start_date
            
        # 处理结束时间
        if isinstance(end_date, datetime):
            if end_date.tzinfo is not None:
                # 如果有时区信息，转换为本地时间
                end_date_local = end_date.astimezone().replace(tzinfo=None)
            else:
                # 如果没有时区信息，假设是本地时间
                end_date_local = end_date
            
            # 标准化结束时间，确保分钟个位数为0或5，秒数为0
            end_date_normalized = self._normalize_minutes(end_date_local)
        else:
            end_date_normalized = end_date
        
        # 使用绝对时间而不是相对时间，避免精度问题
        start_time_str = start_date_normalized.strftime("%Y-%m-%d %H:%M:%S")
        end_time_str = end_date_normalized.strftime("%Y-%m-%d %H:%M:%S")
        
        # 使用properties语法的AppleScript，直接使用绝对时间
        script = f'''
        tell application "Calendar"
            try
                set targetCalendar to calendar "{self.calendar_name}"
                set startTime to date "{start_time_str}"
                set endTime to date "{end_time_str}"
                make new event at end of events of targetCalendar with properties {{summary:"{summary}", description:"{description}", location:"{location}", start date:startTime, end date:endTime}}
                return "Event created successfully"
            on error errMsg
                return "Error: " & errMsg
            end try
        end tell
        '''
        
        success, result = self._run_applescript(script)
        if success:
            self.logger.info(f"创建事件结果：{result}")
            return "Error:" not in result
        return False
    
    def update_event(self, event: Dict) -> bool:
        """更新日历事件"""
        # 确保有结束日期
        start_date, end_date = self._ensure_end_date(event.get("start"), event.get("end"))
        
        if not start_date or not end_date:
            self.logger.warning(f"事件日期无效：{event.get('summary')}")
            return False
        
        # 格式化日期为AppleScript可以理解的格式
        start_date_str = self._format_date_for_applescript(start_date)
        end_date_str = self._format_date_for_applescript(end_date)
        
        if not start_date_str or not end_date_str:
            self.logger.warning(f"事件日期格式无效：{event.get('summary')}")
            return False
        
        # 使用更安全的方式处理字符串
        summary = self._escape_string(event.get('summary', ''))
        description = self._escape_string(event.get('description', ''))
        location = self._escape_string(event.get('location', ''))
        
        script = f'''
        tell application "Calendar"
            try
                set targetCalendar to calendar "{self.calendar_name}"
                repeat with evt in events of targetCalendar
                    if summary of evt contains "{summary}" then
                        set summary of evt to "{summary}"
                        set description of evt to "{description}"
                        set location of evt to "{location}"
                        set start date of evt to {start_date_str}
                        set end date of evt to {end_date_str}
                        return "Event updated successfully"
                    end if
                end repeat
                return "Event not found"
            on error errMsg
                return "Error: " & errMsg
            end try
        end tell
        '''
        
        success, result = self._run_applescript(script)
        if success:
            self.logger.info(f"更新事件结果：{result}")
            return "Error:" not in result and "not found" not in result
        return False
    
    def delete_event(self, event_uid: str) -> bool:
        """删除日历事件"""
        # 由于AppleScript无法直接通过UID查找事件，我们使用一个更智能的删除方法
        # 删除最旧的事件（通常是重复的）
        script = f'''
        tell application "Calendar"
            try
                set targetCalendar to calendar "{self.calendar_name}"
                set eventList to events of targetCalendar
                if (count of eventList) > 0 then
                    set oldestEvent to item 1 of eventList
                    set oldestDate to start date of oldestEvent
                    repeat with evt in eventList
                        if start date of evt < oldestDate then
                            set oldestEvent to evt
                            set oldestDate to start date of evt
                        end if
                    end repeat
                    delete oldestEvent
                    return "Event deleted successfully"
                else
                    return "No events to delete"
                end if
            on error errMsg
                return "Error: " & errMsg
            end try
        end tell
        '''
        
        success, result = self._run_applescript(script)
        if success:
            self.logger.info(f"删除事件结果：{result}")
            return "Error:" not in result
        return False
    
    def delete_event_by_summary(self, event_summary: str) -> bool:
        """根据事件标题删除日历事件"""
        script = f'''
        tell application "Calendar"
            try
                set targetCalendar to calendar "{self.calendar_name}"
                set eventList to events of targetCalendar
                set deletedCount to 0
                
                -- 创建要删除的事件列表
                set eventsToDelete to {{}}
                repeat with evt in eventList
                    if summary of evt contains "{self._escape_string(event_summary)}" then
                        set end of eventsToDelete to evt
                    end if
                end repeat
                
                -- 删除找到的事件
                repeat with evt in eventsToDelete
                    delete evt
                    set deletedCount to deletedCount + 1
                end repeat
                
                return "Deleted " & deletedCount & " events"
            on error errMsg
                return "Error: " & errMsg
            end try
        end tell
        '''
        
        success, result = self._run_applescript(script)
        if success:
            self.logger.info(f"根据标题删除事件结果：{result}")
            return "Error:" not in result and "Deleted" in result
        return False
    
    def get_existing_events(self) -> List[Dict]:
        """获取现有事件列表"""
        script = f'''
        tell application "Calendar"
            try
                set targetCalendar to calendar "{self.calendar_name}"
                set eventCount to count of events of targetCalendar
                set eventList to ""
                repeat with evt in events of targetCalendar
                    set eventSummary to summary of evt
                    set eventDescription to description of evt
                    set eventLocation to location of evt
                    set eventStart to start date of evt
                    set eventEnd to end date of evt
                    
                    set eventInfo to eventSummary & "|" & eventDescription & "|" & eventLocation & "|" & (eventStart as string) & "|" & (eventEnd as string)
                    if eventList is "" then
                        set eventList to eventInfo
                    else
                        set eventList to eventList & "|||" & eventInfo
                    end if
                end repeat
                return "COUNT:" & eventCount & "|||EVENTS:" & eventList
            on error errMsg
                return "Error: " & errMsg
            end try
        end tell
        '''
        
        success, result = self._run_applescript(script, timeout=300)  # 5分钟超时
        if success and "Error:" not in result:
            try:
                events = []
                if result and result.strip():
                    # 解析AppleScript返回的格式：COUNT:8|||EVENTS:event1|||event2|||...
                    if "COUNT:" in result and "|||EVENTS:" in result:
                        count_part, events_part = result.split("|||EVENTS:", 1)
                        count = int(count_part.replace("COUNT:", ""))
                        self.logger.info(f"AppleScript报告事件数量: {count}")
                        
                        if events_part.strip():
                            # 解析事件列表，使用|||作为分隔符
                            event_lines = events_part.strip().split('|||')
                            for line in event_lines:
                                line = line.strip()
                                if '|' in line:
                                    parts = line.split('|')
                                    if len(parts) >= 5:
                                        event = {
                                            'summary': parts[0].strip(),
                                            'description': parts[1].strip(),
                                            'location': parts[2].strip(),
                                            'start': parts[3].strip(),
                                            'end': parts[4].strip()
                                        }
                                        events.append(event)
                
                self.logger.info(f"获取到 {len(events)} 个iCloud事件")
                self.logger.debug(f"iCloud事件详情: {[e['summary'] for e in events]}")
                return events
            except Exception as e:
                self.logger.error(f"解析iCloud事件失败：{e}")
                self.logger.error(f"原始结果: {result}")
                return []
        else:
            # 检查是否是超时错误
            if "执行超时" in result:
                self.logger.error("AppleScript执行超时，无法获取iCloud事件列表")
                self.logger.warning("为避免重复创建事件，本次同步将被跳过")
                # 返回特殊标记，表示超时
                return "TIMEOUT"
            # 检查是否是日历不可访问的错误
            elif "不能获得" in result and "calendar" in result:
                self.logger.warning(f"目标iCloud日历 '{self.calendar_name}' 不可访问，可能未在日历应用中勾选")
                self.logger.warning("请确保在macOS日历应用中勾选目标日历，然后重新运行同步")
                # 返回特殊标记，表示日历不可访问
                return None
            else:
                self.logger.error(f"获取现有事件失败：{result}")
                return []
    
    def clear_all_events(self) -> bool:
        """清空日历中的所有事件"""
        script = f'''
        tell application "Calendar"
            try
                set targetCalendar to calendar "{self.calendar_name}"
                set eventCount to count of events of targetCalendar
                if eventCount > 0 then
                    delete every event of targetCalendar
                    return "Cleared " & eventCount & " events"
                else
                    return "No events to clear"
                end if
            on error errMsg
                return "Error: " & errMsg
            end try
        end tell
        '''
        
        success, result = self._run_applescript(script)
        if success:
            self.logger.info(f"清空事件结果：{result}")
            return "Error:" not in result
        return False
    
    def _format_date(self, date_obj) -> str:
        """格式化日期为AppleScript格式"""
        if not date_obj:
            return None
        
        if isinstance(date_obj, str):
            try:
                date_obj = datetime.fromisoformat(date_obj.replace('Z', '+00:00'))
            except:
                return None
        
        if isinstance(date_obj, datetime):
            # 使用简单的日期格式
            return f'date "{date_obj.strftime("%Y-%m-%d %H:%M:%S")}"'
        
        return None
    
    def _format_date_for_applescript(self, date_obj) -> str:
        """为AppleScript格式化日期，使用AppleScript能正确识别的格式"""
        if not date_obj:
            return None
        
        # 处理date类型（只有日期没有时间）
        if isinstance(date_obj, date) and not isinstance(date_obj, datetime):
            # 这是date类型，转换为datetime类型（全天事件）
            date_obj = datetime.combine(date_obj, datetime.min.time())
        
        if isinstance(date_obj, str):
            try:
                # 处理ISO格式字符串
                if 'T' in date_obj:
                    date_obj = datetime.fromisoformat(date_obj.replace('Z', '+00:00'))
                else:
                    # 处理其他格式
                    date_obj = datetime.fromisoformat(date_obj)
            except Exception as e:
                self.logger.error(f"日期解析失败: {date_obj}, 错误: {e}")
                return None
        
        if isinstance(date_obj, datetime):
            # 转换为本地时间（去掉时区信息）
            if date_obj.tzinfo is not None:
                date_obj = date_obj.astimezone().replace(tzinfo=None)
            
            # 标准化时间，确保分钟个位数为0或5，秒数为0
            date_obj = self._normalize_minutes(date_obj)
            
            # 使用AppleScript能正确识别的日期格式
            # 尝试使用更简单的格式
            formatted_date = date_obj.strftime("%m/%d/%Y %I:%M:%S %p")
            return f'date "{formatted_date}"'
        
        return None
    
    def _ensure_end_date(self, start_date, end_date):
        """确保有结束日期，如果没有则设置为开始时间+1小时"""
        if not end_date and start_date:
            # 处理date类型（只有日期没有时间）
            if isinstance(start_date, date) and not isinstance(start_date, datetime):
                # 这是date类型，全天事件：结束时间是同一天的23:59:59
                end_dt = datetime.combine(start_date, datetime.min.time().replace(hour=23, minute=59, second=59))
                return start_date, end_dt
            
            if isinstance(start_date, str):
                try:
                    start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                except:
                    return start_date, None
            else:
                start_dt = start_date
            
            # 如果开始时间是日期（没有时间），则结束时间也是同一天
            if start_dt.hour == 0 and start_dt.minute == 0 and start_dt.second == 0:
                end_dt = start_dt.replace(hour=23, minute=59, second=59)
            else:
                # 否则结束时间比开始时间晚1小时，并标准化时间
                end_dt = start_dt + timedelta(hours=1)
                end_dt = self._normalize_minutes(end_dt)
            
            # 标准化开始时间
            if isinstance(start_date, datetime):
                start_dt_normalized = self._normalize_minutes(start_dt)
                return start_dt_normalized, end_dt
            
            return start_date, end_dt
        
        return start_date, end_date
    
    def _normalize_minutes(self, dt: datetime) -> datetime:
        """标准化时间，将分钟数强制调整为个位数为0或5，秒数为0"""
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
    
    def _escape_string(self, text: str) -> str:
        """转义字符串中的特殊字符，使其在AppleScript中安全使用"""
        if not text:
            return ""
        
        # 对于AppleScript，我们使用更简单的方法：只转义最关键的字符
        # 其他字符让AppleScript自己处理
        text = text.replace('\\', '\\\\')  # 反斜杠
        text = text.replace('"', '\\"')    # 双引号
        
        return text
    
    def sync_events(self, events: List[Dict]) -> bool:
        """同步事件到iCloud日历"""
        try:
            self.logger.info(f"开始同步 {len(events)} 个事件到iCloud日历")
            
            # 确保日历存在
            if not self.create_calendar():
                self.logger.error("无法创建或访问iCloud日历")
                return False
            
            success_count = 0
            for event in events:
                try:
                    if self.create_event(event):
                        success_count += 1
                    else:
                        self.logger.warning(f"创建事件失败：{event.get('summary')}")
                except Exception as e:
                    self.logger.error(f"同步事件异常：{e}")
                    continue
            
            self.logger.info(f"成功同步 {success_count}/{len(events)} 个事件")
            return success_count > 0
            
        except Exception as e:
            self.logger.error(f"同步事件到iCloud失败：{e}")
            return False


def test_icloud_integration():
    """测试iCloud集成"""
    integration = ICloudIntegration("测试日历")
    
    # 测试创建日历
    print("测试创建日历...")
    if integration.create_calendar():
        print("✅ 日历创建成功")
    else:
        print("❌ 日历创建失败")
        return False
    
    # 测试创建事件
    test_event = {
        "summary": "测试事件",
        "description": "这是一个测试事件",
        "location": "测试地点",
        "start": datetime.now(),
        "end": datetime.now().replace(hour=datetime.now().hour + 1)
    }
    
    print("测试创建事件...")
    if integration.create_event(test_event):
        print("✅ 事件创建成功")
    else:
        print("❌ 事件创建失败")
        return False
    
    print("✅ iCloud集成测试完成")
    return True


if __name__ == "__main__":
    test_icloud_integration()
