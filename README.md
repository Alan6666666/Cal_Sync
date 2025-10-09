# 企微CalDAV到iCloud日历同步工具
基本情况介绍：

注意：本工具需要借助icloud和AppleScript，只能在mac os环境下运行

任务背景
- 企业微信的日历导出使用Caldev或exchange用户，大部分日程会议安排整合产品均不支持
- 经过调查发现，icloud日历可以借助苹果账户，导出ics的url链接，且可以通过编写applescript自动修改icloud日历中的日程内容；Mac本地日历支持Caldev账户，说明Mac os可以很方便地导入该账户类型
- 脚本仅导入CalDAV账户并读取内容，不会向企微进行任何数据输入
- 主流工具大多支持导入ics协议

功能流程
- 在企微中，导出账户名和密码
- 本地直接链接CalDAV服务器（不用经过mac日历），获取其中的日程事件；
- 通过账户和密码链接icloud日历（必须手动创建）
- 基于自主编写的uid键方式，比对两个日历内容，将所有日程事件进行单向同步
- 使用mac os的launchd系统服务，定时运行事件同步
- 在https://www.icloud.com.cn/calendar/ 中导出icloud日历的ics url链接，在google日历、cal.com中导入该链接
- 定时进行日历数据备份，导出ics文件格式到本地
- 以上使用完全自动的流程，实现了企业微信到会议产品的信息单向导入

存在问题
- 由于icloud在创建日历的操作上出现权限问题，必须手动创建好icloud日历。且目前仅支持将企微中的多个日历合并，将所有日程信息一起同步到一个icloud日历中，无法相应分别同步。
- 考虑到可能有未考虑周全的逻辑漏洞，最好不要在mac本地日历上对企微日历进行修改，以避免混乱。

## 一、部署流程

### 1. 环境要求
- macOS 10.14+
- Python 3.7+
- 网络连接
- macOS日历访问权限

### 2. 快速安装

运行一键安装脚本：
```bash
python3 install.py
```
项目需要放置在系统盘，否则可能出现权限问题

安装脚本会自动：
- 检查Python版本
- 安装依赖包
- 创建配置文件
- 设置macOS权限说明
- 测试连接

### 3. 权限设置

#### macOS日历访问权限
1. 打开 **系统偏好设置** > **安全性与隐私** > **隐私**
2. 在左侧列表中选择 **日历**
3. 点击左下角的锁图标并输入密码
4. 勾选 **终端** 和 **您使用的IDE**
5. 重启终端/IDE后重试

注意：通常情况下，终端由于没有发起过对日历的请求，设置里会找不到选项。可以通过在终端中运行任意请求，如
```bash
osascript -e 'tell application "Calendar" to get title of calendars'
```
随后即可在设置中找到终端。

#### iCloud专用密码
1. 访问 [Apple ID 管理页面](https://appleid.apple.com/)
2. 登录您的Apple ID
3. 在 **安全** 部分找到 **应用专用密码**
4. 点击 **生成密码**
5. 将生成的密码填入配置文件

### 4. 运行方式

#### 单次同步
```bash
# 同步所有日历（默认行为）
python3 cal_sync.py --once

# 选择特定日历同步
python3 cal_sync.py --once --select-calendars 1,3,5

# 列出所有可用日历
python3 cal_sync.py --list-calendars
```

#### 手动备份
```bash
# 备份所有日历（强制执行，不检查时间间隔）
python3 cal_sync.py --backup

# 备份特定日历
python3 cal_sync.py --backup --select-calendars 1,3,5
```

#### 定时同步
```bash
# 启动定时同步（使用配置文件设置）
python3 cal_sync.py
```
该方法需要在终端一直运行，不推荐
```bash
# 后台定时同步管理
./background_timer.sh setup    # 首次设置
./background_timer.sh start    # 启用定时任务
./background_timer.sh status   # 查看状态
```
该方法可以自动在后台定时执行，开机后也可以自动运行（首次运行需要允许权限）

## 二、参数设置

### 配置文件 (config.json)

```json
{
    "caldav": {
        "server": "caldav.wecom.work",
        "base_url": "https://caldav.wecom.work/calendar/",
        "username": "your_username@company.wecom.work",
        "password": "your_password",
        "calendar_url": "",
        "selected_calendars": []
    },
    "icloud": {
        "username": "your_email@icloud.com",
        "password": "your_icloud_password",
        "calendar_name": "日历名字（必须手动创建好）",
        "app_private_password": "your_app_specific_password"
    },
    "sync": {
        "interval_minutes": 30,
        "sync_past_days": 30,
        "sync_future_days": 365,
        "expand_recurring": true,
        "verify_threshold": 1,
        "override_icloud_deletions": true
    },
    "backup": {
        "enabled": true,
        "interval_hours": 24,
        "max_backups": 10,
        "backup_folder": "backup"
    }
}
```

### 配置参数说明

#### CalDAV配置
- **server**: 企业微信CalDAV服务器地址
- **base_url**: 完整的CalDAV URL
- **username**: 企业微信用户名
- **password**: 企业微信密码
- **calendar_url**: 特定日历URL（留空自动发现）
- **selected_calendars**: 要同步的日历索引数组（空数组表示同步所有日历）

#### iCloud配置
- **username**: iCloud邮箱地址
- **password**: iCloud密码
- **calendar_name**: 目标日历名称（必须手动创建）
- **app_private_password**: iCloud专用密码（推荐使用）

#### 同步配置
- **interval_minutes**: 同步间隔时间（分钟）修改后需要重启timer才会作用
- **sync_past_days**: 同步过去多少天的事件
- **sync_future_days**: 同步未来多少天的事件
- **expand_recurring**: 是否展开循环事件为具体实例
- **verify_threshold**: 同步验证阈值，默认为1
- **override_icloud_deletions**: 是否自动恢复被手动删除的iCloud事件。该参数为true时，若iCloud日历中的日程被认为修改，则认为该修改为误触，会使用企微日历将其覆盖。若为false则不会检测iCloud端的变化。

#### 备份配置
- **enabled**: 是否启用备份功能（默认：true）
- **interval_hours**: 备份间隔时间（小时，默认：24小时）
- **max_backups**: 保留的备份文件数量（默认：10个）
- **backup_folder**: 备份文件夹名称（默认：backup）

### 日历选择优先级

1. **命令行参数** (`--select-calendars`) - 最高优先级
2. **配置文件** (`selected_calendars`) - 中等优先级  
3. **特定URL** (`calendar_url`) - 低优先级
4. **所有日历** - 默认行为

### 命令行参数

```bash
python3 cal_sync.py [选项]

选项:
  --config CONFIG          配置文件路径（默认: config.json）
  --once                   只执行一次同步
  --backup                 强制执行一次备份
  --select-calendars CAL   选择要同步的日历索引，用逗号分隔，如：1,3,5
  --list-calendars         列出所有可用日历
  --help                   显示帮助信息
```

## 三、代码内容介绍

### 项目结构

```
CalSync/
├── cal_sync.py              # 主同步脚本
├── icloud_integration.py    # iCloud集成模块
├── install.py               # 一键安装配置脚本
├── background_timer.sh      # 后台定时同步管理脚本
├── config.json              # 配置文件
├── requirements.txt         # Python依赖
├── logs/                    # 日志和状态文件夹（自动生成）
│   ├── cal_sync.log        # 运行日志
│   ├── cal_sync_error.log  # 错误日志
│   ├── sync_state.json     # 同步状态文件
│   └── backup_state.json   # 备份状态文件
├── backup/                  # 备份文件夹（自动生成）
│   ├── backup_20241201_143022.ics
│   ├── backup_20241202_143045.ics
│   └── ...
└── README.md               # 本文件
```

### 核心模块

#### cal_sync.py - 主同步脚本
- **CalSync类**：主要的同步逻辑类
- **get_caldav_events()**：获取CalDAV日历事件，支持多日历选择
- **sync_calendars()**：执行日历同步流程
- **detect_changes()**：检测事件变化（新增、修改、删除）
- **sync_to_icloud()**：同步事件到iCloud
- **verify_sync()**：验证同步结果
- **backup_caldav_events()**：备份CalDAV事件到ICS文件
- **export_events_to_ics()**：将事件导出为ICS格式
- **cleanup_old_backups()**：清理旧的备份文件

#### icloud_integration.py - iCloud集成模块
- **ICloudIntegration类**：iCloud日历操作类
- **create_calendar()**：创建iCloud日历
- **create_event()**：创建日历事件
- **delete_event_by_summary()**：根据标题删除事件
- **get_existing_events()**：获取现有事件列表
- **clear_all_events()**：清空所有事件

### 技术实现

#### 多日历处理
- 使用CalDAV协议获取所有可用日历
- 支持按索引选择特定日历
- 将多个日历的事件合并到一个列表中
- 每个事件标记来源日历信息

#### 智能同步机制
- **稳定主键**：使用 `UID + RECURRENCE-ID` 创建稳定的事件标识符
- **精确哈希**：基于完整事件信息生成哈希，避免误报修改
- **同步标记**：在事件描述中添加 `[SYNC_UID:key]` 标记用于精确匹配
- **自动恢复**：检测iCloud中被手动删除的事件并自动重新创建

#### 事件处理
- **全天事件支持**：正确处理只有日期没有时间的事件
- **循环事件处理**：支持展开循环事件为具体实例
- **时区处理**：所有时间统一转换为UTC，避免时区差异

### 备份功能

#### 备份机制
- **自动备份**：每次同步时自动检查是否需要备份
- **手动备份**：通过`--backup`参数强制执行备份，不检查时间间隔
- **ICS格式**：备份文件为标准ICS格式，可导入其他日历应用
- **智能间隔**：根据配置的间隔时间执行备份，避免频繁备份
- **自动清理**：自动保留最新的N个备份文件，删除旧文件

#### 备份文件
- **命名格式**：`backup_YYYYMMDD_HHMMSS.ics`
- **存储位置**：`backup/` 文件夹（可配置）
- **内容包含**：完整的CalDAV事件信息，包括循环规则、异常日期等

#### 备份状态
- **logs/backup_state.json**: 记录上次备份时间
- **日志记录**: 备份过程详细记录在 `logs/cal_sync.log` 中

### 日志和状态管理

#### 日志文件
- **logs/cal_sync.log**: 详细的运行日志（包括备份日志）
- **logs/cal_sync_error.log**: 错误日志（ERROR级别以上的日志）
- **logs/sync_state.json**: 同步状态文件
- **logs/backup_state.json**: 备份状态文件

#### 查看日志
```bash
# 实时查看主日志
tail -f logs/cal_sync.log

# 查看最近20行
tail -20 logs/cal_sync.log

# 查看备份相关日志
grep -i backup logs/cal_sync.log

# 查看错误日志
tail -f logs/cal_sync_error.log

# 查看所有错误
grep -i error logs/cal_sync_error.log
```

### 故障排除

#### 常见问题
1. **权限问题**：确保终端和IDE有日历访问权限
2. **连接问题**：检查网络连接和认证信息
3. **同步问题**：查看日志文件了解详细错误

#### 调试命令
```bash
# 列出所有可用日历
python3 cal_sync.py --list-calendars

# 测试单次同步
python3 cal_sync.py --once

# 查看详细日志
tail -f cal_sync.log
```