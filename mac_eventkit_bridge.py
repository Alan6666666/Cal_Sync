#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macOS EventKit 桥接模块
提供只读访问 macOS 日历数据库的接口
"""

import logging
import uuid
from datetime import datetime, timedelta, date, timezone
from typing import List, Dict, Optional

try:
    import objc
    from Foundation import NSDate, NSDateFormatter, NSPredicate, NSLocale
    from EventKit import EKEventStore, EKEvent, EKCalendar, EKRecurrenceRule, EKRecurrenceDayOfWeek
    # EKAuthorizationStatus 常量定义
    EKAuthorizationStatus = {
        'notDetermined': 0,
        'restricted': 1,
        'denied': 2,
        'authorized': 3
    }
except ImportError as e:
    print(f"错误：需要安装 pyobjc 库。请运行：pip install pyobjc-core pyobjc-framework-EventKit")
    raise e


def _norm_text(s: Optional[str]) -> str:
    """标准化文本字段：去除多余空白、换行等"""
    if s is None:
        return ""
    s = str(s).strip()
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
            # 假设为本地时区
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    
    # 其他情况转为字符串
    return str(dt)


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


def _convert_nsdate_to_datetime(nsdate) -> Optional[datetime]:
    """将 NSDate 转换为 Python datetime"""
    if nsdate is None:
        return None
    
    try:
        # NSDate 的时间戳（从2001年1月1日开始）
        timestamp = nsdate.timeIntervalSinceReferenceDate()
        # 转换为从1970年1月1日开始的时间戳
        unix_timestamp = timestamp + 978307200  # 2001-1970的秒数差
        dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
        # 转换为本地时间并标准化
        dt_local = dt.astimezone().replace(tzinfo=None)
        return _normalize_minutes_global(dt_local)
    except Exception:
        return None


def _convert_nsdate_to_date(nsdate) -> Optional[date]:
    """将 NSDate 转换为 Python date"""
    if nsdate is None:
        return None
    
    try:
        dt = _convert_nsdate_to_datetime(nsdate)
        if dt:
            return dt.date()
        return None
    except Exception:
        return None


def _format_rrule_from_eventkit(rrules) -> str:
    """从 EventKit 循环规则转换为 RRULE 字符串"""
    if not rrules or len(rrules) == 0:
        return ""
    
    try:
        # 取第一个循环规则（EventKit 通常只有一个）
        rule = rrules[0]
        
        # 获取频率
        frequency = rule.frequency()
        freq_map = {
            0: "DAILY",    # EKRecurrenceFrequencyDaily
            1: "WEEKLY",   # EKRecurrenceFrequencyWeekly
            2: "MONTHLY",  # EKRecurrenceFrequencyMonthly
            3: "YEARLY"    # EKRecurrenceFrequencyYearly
        }
        
        freq_str = freq_map.get(frequency, "WEEKLY")
        
        # 构建 RRULE 字符串
        rrule_parts = [f"FREQ={freq_str}"]
        
        # 添加间隔
        if rule.interval() > 1:
            rrule_parts.append(f"INTERVAL={rule.interval()}")
        
        # 添加星期几（仅对 WEEKLY 有效）
        if frequency == 1 and rule.daysOfTheWeek():
            days = []
            for day in rule.daysOfTheWeek():
                day_map = {
                    1: "SU",  # EKSunday
                    2: "MO",  # EKMonday
                    3: "TU",  # EKTuesday
                    4: "WE",  # EKWednesday
                    5: "TH",  # EKThursday
                    6: "FR",  # EKFriday
                    7: "SA"   # EKSaturday
                }
                day_str = day_map.get(day.dayOfTheWeek(), "MO")
                days.append(day_str)
            if days:
                rrule_parts.append(f"BYDAY={','.join(days)}")
        
        # 添加结束条件
        if rule.recurrenceEnd():
            end_date = rule.recurrenceEnd().endDate()
            if end_date:
                dt = _convert_nsdate_to_datetime(end_date)
                if dt:
                    rrule_parts.append(f"UNTIL={dt.strftime('%Y%m%dT%H%M%SZ')}")
        
        return ';'.join(rrule_parts)
        
    except Exception as e:
        logging.warning(f"转换 RRULE 失败：{e}")
        return ""


def read_events_from_eventkit_by_indices(
    caldav_calendar_indices: List[int],
    caldav_calendar_names: List[str],
    days_past: int,
    days_future: int
) -> List[Dict]:
    """
    根据 CalDAV 日历索引查找对应的 EventKit 日历并读取事件
    
    Args:
        caldav_calendar_indices: CalDAV 日历索引列表
        caldav_calendar_names: 对应的 CalDAV 日历名称列表
        days_past: 读取过去多少天的事件
        days_future: 读取未来多少天的事件
    
    Returns:
        事件字典列表
    """
    logger = logging.getLogger(__name__)
    events = []
    
    try:
        # 创建 EventStore
        event_store = EKEventStore.alloc().init()
        
        # 请求日历访问权限
        auth_granted = event_store.accessGrantedForEntityType_(0)  # EKEntityTypeEvent
        
        if not auth_granted:
            logger.info("请求日历访问权限...")
            # 这里会触发系统权限弹窗
            granted, error = event_store.requestAccessToEntityType_completion_(0, None)
            if not granted:
                logger.error("日历访问权限被拒绝")
                return []
            logger.info("日历访问权限已获得")
        else:
            logger.info("日历访问权限已获得")
        
        # 获取所有 EventKit 日历
        all_calendars = event_store.calendarsForEntityType_(0)  # EKEntityTypeEvent
        logger.info(f"找到 {len(all_calendars)} 个 EventKit 日历")
        
        # 创建 CalDAV 索引到名称的映射
        caldav_index_to_name = dict(zip(caldav_calendar_indices, caldav_calendar_names))
        logger.info(f"CalDAV 索引映射: {caldav_index_to_name}")
        
        # 筛选目标日历
        target_calendars = []
        for calendar in all_calendars:
            calendar_name = calendar.title().strip()
            
            # 查找匹配的 CalDAV 日历名称
            for caldav_index, caldav_name in caldav_index_to_name.items():
                caldav_name_trimmed = caldav_name.strip()
                if calendar_name == caldav_name_trimmed:
                    target_calendars.append(calendar)
                    logger.info(f"选择 EventKit 日历：{calendar_name} (对应 CalDAV 索引 {caldav_index})")
                    break
        
        if not target_calendars:
            logger.warning(f"未找到匹配的 EventKit 日历，CalDAV 日历名称：{caldav_calendar_names}")
            logger.info("可用的 EventKit 日历：")
            for cal in all_calendars:
                logger.info(f"  - {cal.title()}")
            return []
        
        # 设置时间范围
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=days_past)
        end_date = now + timedelta(days=days_future)
        
        # 转换为 NSDate
        start_nsdate = NSDate.dateWithTimeIntervalSince1970_(start_date.timestamp())
        end_nsdate = NSDate.dateWithTimeIntervalSince1970_(end_date.timestamp())
        
        # 创建谓词
        predicate = event_store.predicateForEventsWithStartDate_endDate_calendars_(
            start_nsdate, end_nsdate, target_calendars
        )
        
        # 获取事件
        ek_events = event_store.eventsMatchingPredicate_(predicate)
        logger.info(f"从 EventKit 获取到 {len(ek_events)} 个事件")
        
        # 转换事件
        for ek_event in ek_events:
            try:
                event_dict = _convert_eventkit_event_to_dict(ek_event)
                if event_dict:
                    events.append(event_dict)
            except Exception as e:
                logger.warning(f"转换事件失败：{e}")
                continue
        
        logger.info(f"成功转换 {len(events)} 个 EventKit 事件")
        return events
        
    except Exception as e:
        logger.error(f"从 EventKit 读取事件失败：{e}")
        return []


def read_events_from_eventkit(
    calendar_names: List[str],
    days_past: int,
    days_future: int
) -> List[Dict]:
    """
    只读从 macOS EventKit 拉取事件，返回与 CalSync.parse_ical_event 同结构的 event_dict
    
    Args:
        calendar_names: 要读取的日历名称列表
        days_past: 读取过去多少天的事件
        days_future: 读取未来多少天的事件
    
    Returns:
        事件字典列表，包含以下字段：
        uid, stable_key, summary, description(需附加 [SYNC_UID:stable_key]),
        location, start, end, created, last_modified, recurrence_id,
        rrule, exdate, is_recurring_instance, raw_data, hash
    """
    logger = logging.getLogger(__name__)
    events = []
    
    try:
        # 创建 EventStore
        event_store = EKEventStore.alloc().init()
        
        # 请求日历访问权限
        auth_granted = event_store.accessGrantedForEntityType_(0)  # EKEntityTypeEvent
        
        if not auth_granted:
            logger.info("请求日历访问权限...")
            # 这里会触发系统权限弹窗
            granted, error = event_store.requestAccessToEntityType_completion_(0, None)
            if not granted:
                logger.error("日历访问权限被拒绝")
                return []
            logger.info("日历访问权限已获得")
        else:
            logger.info("日历访问权限已获得")
        
        # 获取所有日历
        all_calendars = event_store.calendarsForEntityType_(0)  # EKEntityTypeEvent
        logger.info(f"找到 {len(all_calendars)} 个日历")
        
        # 筛选目标日历
        target_calendars = []
        for calendar in all_calendars:
            calendar_name = calendar.title()
            # 使用更宽松的匹配：去除首尾空格
            calendar_name_trimmed = calendar_name.strip()
            for target_name in calendar_names:
                target_name_trimmed = target_name.strip()
                if calendar_name_trimmed == target_name_trimmed:
                    target_calendars.append(calendar)
                    logger.info(f"选择日历：{calendar_name}")
                    break
        
        if not target_calendars:
            logger.warning(f"未找到指定的日历：{calendar_names}")
            return []
        
        # 设置时间范围
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=days_past)
        end_date = now + timedelta(days=days_future)
        
        # 转换为 NSDate
        start_nsdate = NSDate.dateWithTimeIntervalSince1970_(start_date.timestamp())
        end_nsdate = NSDate.dateWithTimeIntervalSince1970_(end_date.timestamp())
        
        # 创建谓词
        predicate = event_store.predicateForEventsWithStartDate_endDate_calendars_(
            start_nsdate, end_nsdate, target_calendars
        )
        
        # 获取事件
        ek_events = event_store.eventsMatchingPredicate_(predicate)
        logger.info(f"从 EventKit 获取到 {len(ek_events)} 个事件")
        
        # 转换事件
        for ek_event in ek_events:
            try:
                event_dict = _convert_eventkit_event_to_dict(ek_event)
                if event_dict:
                    events.append(event_dict)
            except Exception as e:
                logger.warning(f"转换事件失败：{e}")
                continue
        
        logger.info(f"成功转换 {len(events)} 个 EventKit 事件")
        return events
        
    except Exception as e:
        logger.error(f"从 EventKit 读取事件失败：{e}")
        return []


def _convert_eventkit_event_to_dict(ek_event: EKEvent) -> Optional[Dict]:
    """将 EventKit 事件转换为标准事件字典"""
    try:
        # 获取基本字段
        uid = ek_event.eventIdentifier()
        if not uid:
            logging.warning("事件缺少标识符，跳过")
            return None
        
        # 创建稳定主键：优先使用 calendarItemIdentifier，否则生成 UUID
        stable_key = ek_event.calendarItemIdentifier()
        if not stable_key:
            stable_key = f"MAC:{uuid.uuid4().hex}"
        
        # 获取循环相关字段
        recurrence_id = None
        is_recurring_instance = False
        
        # 检查是否是循环事件的实例
        if ek_event.hasRecurrenceRules():
            # 如果有 occurrenceDate，说明这是循环实例
            if hasattr(ek_event, 'occurrenceDate') and ek_event.occurrenceDate():
                recurrence_id = _convert_nsdate_to_datetime(ek_event.occurrenceDate())
                if recurrence_id:
                    recurrence_id = recurrence_id.isoformat()
                    stable_key = f"{uid}#{recurrence_id}"
                    is_recurring_instance = True
        
        # 获取 RRULE
        rrule = ""
        if ek_event.hasRecurrenceRules():
            rrule = _format_rrule_from_eventkit(ek_event.recurrenceRules())
        
        # 处理描述，添加同步标记
        description = _norm_text(ek_event.notes())
        if description:
            sync_marker = f" [SYNC_UID:{stable_key}]"
            if sync_marker not in description:
                description += sync_marker
        else:
            description = f"[SYNC_UID:{stable_key}]"
        
        # 构建事件字典
        event_dict = {
            "uid": uid,
            "stable_key": stable_key,
            "summary": _norm_text(ek_event.title()),
            "description": description,
            "location": _norm_text(ek_event.location()),
            "start": _convert_nsdate_to_datetime(ek_event.startDate()),
            "end": _convert_nsdate_to_datetime(ek_event.endDate()),
            "created": _convert_nsdate_to_datetime(ek_event.creationDate()),
            "last_modified": _convert_nsdate_to_datetime(ek_event.lastModifiedDate()),
            "recurrence_id": recurrence_id,
            "rrule": rrule,
            "exdate": "",  # EventKit 不直接提供 EXDATE，暂时为空
            "is_recurring_instance": is_recurring_instance,
            "raw_data": f"EventKit:{uid}"  # 简化的原始数据标识
        }
        
        # 生成事件哈希（复用 CalSync 的逻辑）
        event_dict["hash"] = _generate_event_hash(event_dict)
        
        return event_dict
        
    except Exception as e:
        logging.warning(f"转换 EventKit 事件失败：{e}")
        return None


def _generate_event_hash(event: Dict) -> str:
    """生成事件哈希值用于比较（复用 CalSync 的逻辑）"""
    import hashlib
    
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


def test_eventkit_access():
    """测试 EventKit 访问权限"""
    try:
        logger = logging.getLogger(__name__)
        logger.info("测试 EventKit 访问...")
        
        # 创建 EventStore
        event_store = EKEventStore.alloc().init()
        
        # 检查权限状态
        auth_granted = event_store.accessGrantedForEntityType_(0)
        logger.info(f"当前权限状态：{auth_granted}")
        
        if not auth_granted:
            logger.info("请求权限...")
            granted, error = event_store.requestAccessToEntityType_completion_(0, None)
            logger.info(f"权限请求结果：{granted}")
        
        # 获取日历列表
        calendars = event_store.calendarsForEntityType_(0)
        logger.info(f"找到 {len(calendars)} 个日历：")
        for cal in calendars:
            logger.info(f"  - {cal.title()}")
        
        return True
        
    except Exception as e:
        logger.error(f"EventKit 测试失败：{e}")
        return False


if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(level=logging.INFO)
    
    # 测试 EventKit 访问
    test_eventkit_access()
    
    # 测试读取事件
    events = read_events_from_eventkit(["测试"], 7, 7)
    print(f"读取到 {len(events)} 个事件")
    for event in events[:3]:  # 只显示前3个
        print(f"  - {event['summary']} ({event['stable_key']})")
