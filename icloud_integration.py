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
    
    def _run_applescript(self, script: str) -> tuple[bool, str]:
        """运行AppleScript"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=60
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
        
        # 调试信息
        self.logger.info(f"--- 调试信息 ---")
        self.logger.info(f"准备创建事件，开始时间: {start_date}")
        self.logger.info(f"准备创建事件，结束时间: {end_date}")
        self.logger.info(f"----------------")
        
        if not start_date or not end_date:
            self.logger.warning(f"事件日期无效：{event.get('summary')}")
            return False
        
        # 格式化日期为AppleScript可以理解的格式
        start_date_str = self._format_date_for_applescript(start_date)
        end_date_str = self._format_date_for_applescript(end_date)
        
        # 调试信息
        self.logger.info(f"AppleScript开始时间: {start_date_str}")
        self.logger.info(f"AppleScript结束时间: {end_date_str}")
        
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
                tell calendar "{self.calendar_name}"
                    make new event with properties {{summary:"{summary}", description:"{description}", location:"{location}", start date:{start_date_str}, end date:{end_date_str}}}
                end tell
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
        
        success, result = self._run_applescript(script)
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
        """为AppleScript格式化日期，使用简单的日期字符串格式"""
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
                date_obj = date_obj.replace(tzinfo=None)
            
            # 使用简单的日期字符串格式
            formatted_date = date_obj.strftime("%Y-%m-%d %H:%M:%S")
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
                # 否则结束时间比开始时间晚1小时
                end_dt = start_dt + timedelta(hours=1)
            
            return start_date, end_dt
        
        return start_date, end_date
    
    def _escape_string(self, text: str) -> str:
        """转义字符串中的特殊字符"""
        if not text:
            return ""
        
        # 转义AppleScript中的特殊字符
        text = text.replace('\\', '\\\\')
        text = text.replace('"', '\\"')
        text = text.replace('\n', '\\n')
        text = text.replace('\r', '\\r')
        text = text.replace('\t', '\\t')
        # 处理中文字符和其他特殊字符
        text = text.replace("'", "\\'")
        
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
