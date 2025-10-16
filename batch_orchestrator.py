#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量编排器 - EventKit批量同步模式
支持将同一企微账户的多个源日历分别同步到不同的iCloud目标日历
"""

import time
import logging
import copy
from typing import Dict, List, Optional
from cal_sync import CalSync


def run_eventkit_batch(config: Dict, force_resync: bool = False) -> bool:
    """
    检查配置并执行EventKit批量同步模式
    
    Args:
        config: 配置字典
        force_resync: 是否执行强制重新同步
        
    Returns:
        bool: True表示已执行批量模式，False表示需要回退到原有逻辑
    """
    # 检查是否存在且非空的eventkit_batch_map
    eventkit_batch_map = config.get("eventkit_batch_map", [])
    if not eventkit_batch_map or not isinstance(eventkit_batch_map, list):
        return False
    
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("🚀 启用EventKit批量编排模式")
    if force_resync:
        logger.info("⚠️  强制重新同步模式：将清空目标iCloud日历并重新创建所有事件")
    logger.info(f"📋 批量映射配置：{len(eventkit_batch_map)} 个映射")
    
    # 显示所有映射信息
    for i, mapping in enumerate(eventkit_batch_map, 1):
        source_index = mapping.get("source_index")
        target_calendar = mapping.get("target_icloud_calendar_name")
        logger.info(f"  映射 {i}: EventKit索引 {source_index} → iCloud日历「{target_calendar}」")
    
    # 批量执行同步
    success_count = 0
    total_count = len(eventkit_batch_map)
    
    for i, mapping in enumerate(eventkit_batch_map, 1):
        source_index = mapping.get("source_index")
        target_calendar = mapping.get("target_icloud_calendar_name")
        
        if not source_index or not target_calendar:
            logger.error(f"映射 {i} 配置无效：缺少source_index或target_icloud_calendar_name")
            continue
        
        logger.info("-" * 40)
        sync_mode = "强制重新同步" if force_resync else "增量同步"
        logger.info(f"🔄 执行映射 {i}/{total_count}: EventKit索引 {source_index} → iCloud日历「{target_calendar}」({sync_mode})")
        
        try:
            # 创建配置副本
            batch_config = copy.deepcopy(config)
            
            # 覆盖配置：单源单目标模式
            batch_config["source_routing"] = {
                "eventkit_indices": [source_index],  # 只使用当前映射的单个索引
                "caldav_indices": [],               # 强制忽略CalDAV
                "eventkit_calendars": [],           # 清空EventKit日历名称
                "fallback_on_404": False            # 禁用CalDAV回退
            }
            batch_config["icloud"]["calendar_name"] = target_calendar  # 设置目标iCloud日历
            
            # 创建同步器实例（使用原始配置文件路径）
            original_config_file = config.get("_config_file", "config.json")
            syncer = CalSync(config_file=original_config_file, caldav_indices=[], eventkit_calendars=[], eventkit_indices=[source_index])
            # 覆盖配置为批量模式配置
            syncer.config = batch_config
            syncer.source_routing = batch_config["source_routing"]
            
            # 为每个映射创建独立的同步状态文件，避免状态冲突
            syncer.sync_state_file = f"logs/sync_state_batch_{source_index}_{target_calendar.replace(' ', '_')}.json"
            syncer.sync_state = syncer.load_sync_state()
            
            # 执行同步
            if force_resync:
                # 强制重新同步模式：获取源事件并执行强制同步
                if not syncer.connect_caldav():
                    logger.error(f"❌ 映射 {i} CalDAV连接失败")
                    continue
                if not syncer.connect_icloud():
                    logger.error(f"❌ 映射 {i} iCloud连接失败")
                    continue
                
                # 获取源事件
                current_events = syncer.get_source_events()
                if not current_events:
                    logger.warning(f"⚠️  映射 {i} 没有找到需要同步的事件")
                    success_count += 1  # 没有事件也算成功
                    continue
                
                # 执行强制重新同步
                sync_success = syncer.force_resync(current_events)
            else:
                # 增量同步模式
                sync_success = syncer.sync_calendars()
            
            if sync_success:
                logger.info(f"✅ 映射 {i} 同步成功")
                success_count += 1
            else:
                logger.error(f"❌ 映射 {i} 同步失败")
            
        except Exception as e:
            logger.error(f"❌ 映射 {i} 执行异常：{e}")
        
        # 错峰暂停（除了最后一个映射）
        if i < total_count:
            pause_seconds = 8  # 默认8秒暂停
            logger.info(f"⏸️  暂停 {pause_seconds} 秒以避免iCloud限流...")
            time.sleep(pause_seconds)
    
    # 批量执行完成
    logger.info("-" * 40)
    logger.info(f"🏁 EventKit批量编排完成：{success_count}/{total_count} 个映射成功")
    
    if success_count == total_count:
        logger.info("✅ 所有映射同步成功")
    elif success_count > 0:
        logger.warning(f"⚠️  部分映射同步失败：{total_count - success_count} 个失败")
    else:
        logger.error("❌ 所有映射同步失败")
    
    logger.info("=" * 60)
    return True  # 表示已处理批量模式


def get_batch_summary(config: Dict) -> Optional[Dict]:
    """
    获取批量配置摘要信息
    
    Args:
        config: 配置字典
        
    Returns:
        Dict: 摘要信息，如果不存在批量配置则返回None
    """
    eventkit_batch_map = config.get("eventkit_batch_map", [])
    if not eventkit_batch_map or not isinstance(eventkit_batch_map, list):
        return None
    
    summary = {
        "mode": "batch",
        "total_mappings": len(eventkit_batch_map),
        "mappings": []
    }
    
    for mapping in eventkit_batch_map:
        summary["mappings"].append({
            "source_index": mapping.get("source_index"),
            "target_calendar": mapping.get("target_icloud_calendar_name")
        })
    
    return summary
