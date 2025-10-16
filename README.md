# CalSync - 企业微信日历同步工具

## 项目概述

为企业微信日历同步设计的自动化工具，支持将企业微信日历同步到iCloud日历，实现跨平台日历数据统一管理。

**注意：本工具基于macOS系统，需要macOS日历、iCloud及AppleScript支持，只能在macOS环境下运行。**

## 🎯 当前推荐方案

经过项目迭代优化，当前采用以下技术方案：

### 1. **EventKit事件获取** ⭐ 推荐
- **优势**：直接读取macOS日历应用中的事件，无需网络连接，稳定可靠
- **配置**：需要在macOS日历应用中导入企业微信CalDAV账户
- **支持**：完全支持所有EventKit功能，包括循环事件、全天事件等

### 2. **Python守护进程定时运行** ⭐ 推荐
- **优势**：基于Python定时器，完全后台运行，无权限问题
- **功能**：支持开机自启、状态监控、自动重启、详细日志
- **管理**：提供完整的控制脚本，支持启动、停止、重启、状态查看

### 3. **批量编排模式** ⭐ 推荐
- **多对多同步**：支持将多个源日历分别同步到不同的目标日历
- **一对一同步**：只设置一个map对象，则可以实现传统的单源单目标同步模式
- **配置灵活**：通过`eventkit_batch_map`配置实现灵活的映射关系

## 📋 任务背景

- 企业微信的日历导出使用CalDAV协议，但许多日程工具无法直接导入该账户
- 经过调研发现，iCloud日历可以通过AppleScript自动修改日程内容
- 脚本仅读取日历内容，不会向企业微信进行任何数据写入
- 主流工具大多支持导入ICS协议，便于后续使用

## 🚀 功能流程

1. **配置企业微信账户**：在macOS日历应用中导入企业微信CalDAV账户
2. **获取日历事件**：通过EventKit读取macOS日历中的企业微信事件
3. **连接iCloud日历**：通过AppleScript连接iCloud日历（需要手动创建目标日历）
4. **智能同步**：基于自主编写的UID键方式，比对两个日历内容，进行单向同步
5. **定时运行**：使用Python守护进程定时执行事件同步
6. **数据备份**：定时进行日历数据备份，导出ICS文件格式到本地
7. **导出使用**：在iCloud日历中导出ICS URL链接，在Google日历、Cal.com等工具中导入使用

## ⚠️ 已知问题

- **iCloud日历创建**：由于iCloud权限限制，必须手动创建目标日历
- **循环事件备份**：备份导出的ICS文件可能存在日程循环问题
- **安全建议**：建议不要在mac本地日历上对企业微信日历进行修改，以避免数据混乱

## 🔧 环境要求

- macOS 10.14+
- Python 3.7+
- 网络连接
- macOS日历访问权限

## 📦 快速安装

运行一键安装脚本：
```bash
python3 install.py
```
**注意：项目需要放置在系统盘，否则可能出现权限问题**

安装脚本会自动：
- 检查Python版本
- 安装依赖包
- 创建配置文件
- 设置macOS权限说明
- 测试连接

## 🔐 权限设置

### macOS日历访问权限
1. 打开 **系统偏好设置** > **安全性与隐私** > **隐私**
2. 在左侧列表中选择 **日历**
3. 点击左下角的锁图标并输入密码
4. 勾选 **终端** 和 **您使用的IDE**
5. 重启终端/IDE后重试

**注意：** 如果设置中找不到终端选项，可以通过以下命令触发权限请求：
```bash
osascript -e 'tell application "Calendar" to get title of calendars'
```

### iCloud专用密码
1. 访问 [Apple ID 管理页面](https://appleid.apple.com/)
2. 登录您的Apple ID
3. 在 **安全** 部分找到 **应用专用密码**
4. 点击 **生成密码**
5. 将生成的密码填入配置文件

## 🎮 使用方法

### 单次同步
```bash
# 同步所有日历（默认行为）
python3 cal_sync.py --once

# 强制重新同步（清空目标日历后重新创建所有事件）
python3 cal_sync.py --once --force-resync

# 选择特定日历同步
python3 cal_sync.py --once --select-calendars 1,3,5

# 列出所有可用日历
python3 cal_sync.py --list-calendars
```

### 手动备份
```bash
# 备份所有日历（强制执行，不检查时间间隔）
python3 cal_sync.py --backup

# 备份特定日历
python3 cal_sync.py --backup --select-calendars 1,3,5
```

### 定时同步（推荐）

**Python守护进程（推荐方案）**
```bash
# 安装守护进程
python3 daemon/setup_daemon.py

# 启动守护进程
./daemon/daemon_control.sh start

# 查看状态
./daemon/daemon_control.sh status

# 安装开机自启
./daemon/daemon_control.sh install

# 停止守护进程
./daemon/daemon_control.sh stop

# 重启守护进程
./daemon/daemon_control.sh restart
```

## ⚙️ 配置说明

### 配置文件 (config.json)

#### 批量编排模式配置（推荐）
```json
{
    "eventkit_batch_map": [
        { "source_index": 1, "target_icloud_calendar_name": "郑敏芝" },
        { "source_index": 4, "target_icloud_calendar_name": "运佳" },
        { "source_index": 5, "target_icloud_calendar_name": "杨赛" },
        { "source_index": 6, "target_icloud_calendar_name": "柏慧" }
    ],
    "source_routing": {
        "eventkit_indices": [],
        "caldav_indices": [],
        "fallback_on_404": false
    },
    "icloud": {
        "username": "your_email@icloud.com",
        "password": "your_icloud_password",
        "calendar_name": "默认日历名称",
        "app_private_password": "your_app_specific_password"
    },
    "sync": {
        "interval_minutes": 30,
        "sync_past_days": 30,
        "sync_future_days": 365,
        "expand_recurring": true,
        "verify_threshold": 1,
        "override_icloud_deletions": true,
        "skip_sync_on_too_many_missing": true
    },
    "backup": {
        "enabled": true,
        "interval_hours": 24,
        "max_backups": 10,
        "backup_folder": "backup"
    }
}
```

#### 传统单对单模式配置（已弃用）
```json
{
    "source_routing": {
        "eventkit_indices": [1,4,5,6],
        "caldav_indices": [],
        "fallback_on_404": true
    },
    "icloud": {
        "calendar_name": "合并后的日历名称"
    }
}
```

### 配置参数说明

#### 批量编排配置
- **eventkit_batch_map**: 批量映射配置，定义多个源日历到目标日历的映射关系
- **source_index**: EventKit源日历索引（在macOS日历应用中的索引）
- **target_icloud_calendar_name**: 对应的iCloud目标日历名称

#### 源路由配置
- **eventkit_indices**: EventKit日历索引数组（批量模式下应设为空）
- **caldav_indices**: CalDAV日历索引数组（批量模式下应设为空）
- **fallback_on_404**: 是否在404错误时回退到CalDAV（批量模式下应设为false）

#### iCloud配置
- **username**: iCloud邮箱地址
- **password**: iCloud密码
- **calendar_name**: 默认日历名称（批量模式下会被映射配置覆盖）
- **app_private_password**: iCloud专用密码（推荐使用）

#### 同步配置
- **interval_minutes**: 同步间隔时间（分钟）修改后需要重启timer才会作用
- **sync_past_days**: 同步过去多少天的事件
- **sync_future_days**: 同步未来多少天的事件
- **expand_recurring**: 是否展开循环事件为具体实例
- **verify_threshold**: 同步验证阈值，默认为1
- **override_icloud_deletions**: 是否自动恢复被手动删除的iCloud事件。该参数为true时，若iCloud日历中的日程被认为修改，则认为该修改为误触，会使用企微日历将其覆盖。若为false则不会检测iCloud端的变化。
- **skip_sync_on_too_many_missing**: 当检测到过多缺失事件时是否跳过同步。当缺失事件数量超过总事件的50%时，可能是AppleScript检测错误，为避免重复创建事件，系统会跳过本次同步。设置为false可禁用此安全功能，但可能导致重复创建事件。

#### 备份配置
- **enabled**: 是否启用备份功能
- **interval_hours**: 备份间隔时间（小时）
- **max_backups**: 保留的备份文件数量
- **backup_folder**: 备份文件夹名称

## 🏗️ 项目结构

```
CalSync/
├── cal_sync.py              # 主同步脚本
├── batch_orchestrator.py    # 批量编排器（核心模块）
├── mac_eventkit_bridge.py   # EventKit集成模块
├── icloud_integration.py    # iCloud集成模块
├── install.py               # 一键安装配置脚本
├── daemon/                  # Python守护进程（推荐方案）
│   ├── daemon_manager.py          # 守护进程管理器
│   ├── launchd_plist_generator.py # launchd plist文件生成器
│   ├── daemon_control.sh         # 控制脚本
│   ├── setup_daemon.py           # 安装配置脚本
│   └── README.md                 # 守护进程说明文档
├── config.json              # 配置文件
├── requirements.txt         # Python依赖
├── logs/                    # 日志和状态文件夹（自动生成）
│   ├── cal_sync.log        # 运行日志
│   ├── cal_sync_error.log  # 错误日志
│   ├── daemon.log          # 守护进程日志
│   ├── daemon_status.json  # 守护进程状态文件
│   ├── sync_state.json     # 同步状态文件（单对单模式）
│   ├── sync_state_batch_*.json # 批量模式同步状态文件
│   └── backup_state.json   # 备份状态文件
├── backup/                  # 备份文件夹（自动生成）
└── README.md               # 本文件

# 已弃用的文件和方案
├── background_timer.sh      # ❌ launchd定时任务（已弃用）
└── applescripts/           # ❌ 旧版AppleScript方案（已弃用）
```

## 🔧 核心模块

### batch_orchestrator.py - 批量编排器（核心）
- **run_eventkit_batch()**: 批量编排模式主函数
- **get_batch_summary()**: 获取批量配置摘要信息
- **支持强制同步**: 完全支持`--force-resync`参数
- **独立状态管理**: 每个映射使用独立的同步状态文件

### cal_sync.py - 主同步脚本
- **CalSync类**: 主要的同步逻辑类
- **支持批量模式**: 自动检测并调用批量编排器
- **向后兼容**: 支持传统单对单同步模式

### mac_eventkit_bridge.py - EventKit集成
- **get_events_from_eventkit()**: 从EventKit获取事件
- **get_calendar_indices()**: 获取日历索引映射
- **支持多日历**: 支持同时读取多个EventKit日历

### icloud_integration.py - iCloud集成
- **ICloudIntegration类**: iCloud日历操作类
- **create_event()**: 创建日历事件
- **delete_event_by_sync_uid()**: 根据同步UID精确删除事件
- **get_existing_events()**: 获取现有事件列表

## 🚫 已弃用的方案

### ~~CalDAV直接连接（已弃用）~~
- **原因**: 企业微信CalDAV服务器兼容性问题，连接不稳定
- **替代方案**: 使用EventKit读取macOS日历应用中的企业微信账户
- **状态**: 代码保留但默认禁用，仅在特殊情况下作为回退方案

### ~~launchd定时任务（已弃用）~~
- **原因**: EventKit权限问题，后台运行时无法访问macOS日历应用
- **替代方案**: Python守护进程，基于Python定时器，无权限问题
- **文件**: `background_timer.sh` 保留但不再推荐使用

### ~~单对单同步模式（已弃用）~~
- **原因**: 无法满足多日历分别同步的需求
- **替代方案**: 批量编排模式，支持多对多同步
- **状态**: 代码保留，通过`eventkit_batch_map`配置自动切换

## 📊 守护进程功能

### 守护进程特性
- ✅ **后台运行**: 基于Python定时器，无需保持终端运行
- ✅ **开机自启**: 支持macOS launchd服务，开机自动启动
- ✅ **状态监控**: 实时查看守护进程状态和同步统计
- ✅ **日志管理**: 详细的运行日志和错误日志
- ✅ **自动重启**: 进程异常退出时自动重启
- ✅ **配置继承**: 使用项目根目录的config.json配置
- ✅ **批量编排支持**: 完全支持批量编排模式

### 守护进程使用
```bash
# 基本控制
./daemon/daemon_control.sh start      # 启动守护进程
./daemon/daemon_control.sh stop       # 停止守护进程
./daemon/daemon_control.sh restart    # 重启守护进程
./daemon/daemon_control.sh status     # 查看状态
./daemon/daemon_control.sh logs       # 查看日志

# 开机自启
./daemon/daemon_control.sh install            # 安装开机自启
./daemon/daemon_control.sh uninstall          # 卸载开机自启
./daemon/daemon_control.sh autostart-status   # 检查开机自启状态

# 其他功能
./daemon/daemon_control.sh test       # 测试单次同步
./daemon/daemon_control.sh help       # 显示帮助
```

### 状态监控
守护进程提供详细的状态信息：
- **运行状态**: 是否正在运行
- **进程ID**: 守护进程的进程ID
- **启动时间**: 守护进程启动时间
- **上次同步**: 最后一次同步时间
- **下次同步**: 预计下次同步时间
- **同步次数**: 成功同步的次数
- **错误次数**: 同步失败的次数
- **上次耗时**: 最后一次同步的耗时

## 📝 日志和状态管理

### 日志文件
- **logs/cal_sync.log**: 详细的运行日志
- **logs/cal_sync_error.log**: 错误日志（ERROR级别以上的日志）
- **logs/daemon.log**: 守护进程日志
- **logs/sync_state.json**: 同步状态文件（单对单模式）
- **logs/sync_state_batch_*.json**: 批量模式同步状态文件（每个映射独立）
- **logs/backup_state.json**: 备份状态文件

### 查看日志
```bash
# 实时查看主日志
tail -f logs/cal_sync.log

# 查看最近20行
tail -20 logs/cal_sync.log

# 查看批量编排相关日志
grep -E "(批量编排|映射|EventKit索引)" logs/cal_sync.log

# 查看错误日志
tail -f logs/cal_sync_error.log

# 查看守护进程日志
tail -f logs/daemon.log
```

## 🛠️ 故障排除

### 常见问题

1. **权限问题**
   - 确保终端和IDE有日历访问权限
   - 重新运行权限设置步骤

2. **iCloud日历不可访问**
   - 确保目标iCloud日历已手动创建
   - 检查iCloud账户和专用密码是否正确
   - 确保macOS日历应用已启动并勾选目标日历

3. **批量编排模式问题**
   - 检查`eventkit_batch_map`配置是否正确
   - 确保`source_routing.eventkit_indices`设为空数组
   - 验证EventKit源日历索引是否正确

4. **同步状态冲突**
   - 批量模式下每个映射使用独立的同步状态文件
   - 如果出现问题，可以删除对应的`sync_state_batch_*.json`文件重新同步

5. **EventKit读取失败**
   - 如果出现"cannot unpack non-iterable NoneType object"错误
   - 这是EventKit长时间运行后的状态异常，程序已内置重试机制
   - 重启守护进程通常可以解决问题

### 调试命令
```bash
# 列出所有可用日历
python3 cal_sync.py --list-calendars

# 测试单次同步
python3 cal_sync.py --once

# 强制重新同步测试
python3 cal_sync.py --once --force-resync

# 查看守护进程状态
./daemon/daemon_control.sh status

# 查看详细日志
tail -f logs/cal_sync.log
```

## 📈 版本历史

### v2.0 - 批量编排模式（当前版本）
- ✅ 支持多对多日历同步
- ✅ Python守护进程替代launchd定时任务
- ✅ EventKit作为主要数据源
- ✅ 独立的同步状态管理
- ✅ 强制同步支持

### v1.x - 传统单对单模式（已弃用）
- ~~CalDAV直接连接~~
- ~~launchd定时任务~~
- ~~单日历合并同步~~

## 🤝 贡献指南

如果您在使用过程中遇到问题或有改进建议，欢迎：
1. 查看日志文件了解详细错误信息
2. 检查配置文件是否正确
3. 尝试重启守护进程或重新同步
4. 提交Issue描述具体问题

## 📄 许可证

本项目采用MIT许可证，详见LICENSE文件。

---

**注意：本项目专门为企业微信日历同步设计，在其他场景下使用可能需要相应调整。**