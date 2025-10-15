# CalSync 守护进程

基于Python定时器的后台运行解决方案，支持后台运行、开机自启、状态查看等功能。

## 实现概述

成功创建了基于Python定时器的后台运行解决方案，解决了原有launchd方案中EventKit权限问题，实现了完全后台运行、开机自启、状态查看等功能。

## 解决的问题

1. **权限问题**: 原有launchd方案无法找到EventKit事件，新方案使用Python定时器避免权限问题
2. **终端依赖**: 原有方案需要保持终端运行，新方案完全后台运行
3. **状态监控**: 新增详细的状态监控和统计功能
4. **开机自启**: 支持macOS launchd服务，开机自动启动

## 功能特性

- ✅ **后台运行**: 基于Python定时器，无需保持终端运行
- ✅ **开机自启**: 支持macOS launchd服务，开机自动启动
- ✅ **状态监控**: 实时查看守护进程状态和同步统计
- ✅ **日志管理**: 详细的运行日志和错误日志
- ✅ **自动重启**: 进程异常退出时自动重启
- ✅ **配置继承**: 使用项目根目录的config.json配置

## 文件结构

```
daemon/
├── daemon_manager.py          # 守护进程管理器
├── launchd_plist_generator.py # launchd plist文件生成器
├── daemon_control.sh         # 控制脚本
├── setup_daemon.py           # 安装配置脚本
└── README.md                 # 本文件
```

## 快速开始

### 1. 安装守护进程

```bash
# 进入项目根目录
cd /Users/wang/CalSync

# 运行安装脚本
python3 daemon/setup_daemon.py
```

### 2. 基本使用

```bash
# 启动守护进程
./daemon/daemon_control.sh start

# 查看状态
./daemon/daemon_control.sh status

# 查看日志
./daemon/daemon_control.sh logs

# 停止守护进程
./daemon/daemon_control.sh stop
```

### 3. 开机自启

```bash
# 安装开机自启服务
./daemon/daemon_control.sh install

# 检查开机自启状态
./daemon/daemon_control.sh autostart-status

# 卸载开机自启服务
./daemon/daemon_control.sh uninstall
```

## 详细说明

### 守护进程管理器 (daemon_manager.py)

核心守护进程，提供以下功能：

- **进程管理**: 启动、停止、重启守护进程
- **定时同步**: 根据配置文件中的间隔时间自动执行同步
- **状态监控**: 记录同步次数、错误次数、运行时间等
- **信号处理**: 优雅地处理SIGTERM和SIGINT信号
- **线程管理**: 使用独立线程执行同步任务

#### 使用方法

```bash
# 直接运行守护进程
python3 daemon/daemon_manager.py daemon

# 查看状态
python3 daemon/daemon_manager.py status

# 启动守护进程
python3 daemon/daemon_manager.py start

# 停止守护进程
python3 daemon/daemon_manager.py stop
```

### 控制脚本 (daemon_control.sh)

提供简单的命令行接口：

```bash
# 守护进程管理
./daemon/daemon_control.sh start      # 启动
./daemon/daemon_control.sh stop       # 停止
./daemon/daemon_control.sh restart    # 重启
./daemon/daemon_control.sh status     # 状态
./daemon/daemon_control.sh logs       # 日志

# 开机自启管理
./daemon/daemon_control.sh install            # 安装
./daemon/daemon_control.sh uninstall          # 卸载
./daemon/daemon_control.sh autostart-status   # 状态

# 其他功能
./daemon/daemon_control.sh test       # 测试同步
./daemon/daemon_control.sh help       # 帮助
```

### Launchd服务 (launchd_plist_generator.py)

管理macOS开机自启服务：

- **自动生成**: 根据配置文件自动生成plist文件
- **权限设置**: 配置正确的环境变量和权限
- **服务管理**: 加载、卸载、检查launchd服务状态

#### 生成的文件位置

```
/Users/[用户名]/Library/LaunchAgents/com.calsync.daemon.plist
```

## 状态监控

### 状态信息

守护进程会记录以下状态信息：

- **运行状态**: 是否正在运行
- **进程ID**: 守护进程的进程ID
- **启动时间**: 守护进程启动时间
- **上次同步**: 最后一次同步时间
- **下次同步**: 预计下次同步时间
- **同步次数**: 成功同步的次数
- **错误次数**: 同步失败的次数
- **上次耗时**: 最后一次同步的耗时

### 状态文件

状态信息保存在以下文件中：

- `logs/daemon_status.json`: 守护进程状态文件
- `logs/daemon.log`: 守护进程运行日志
- `logs/daemon_error.log`: 守护进程错误日志
- `daemon/cal_sync_daemon.pid`: 进程ID文件

## 技术实现

### 架构设计

```
守护进程管理器 (daemon_manager.py)
    ↓
同步工作线程 (sync_worker)
    ↓
CalSync同步器 (cal_sync.py)
    ↓
CalDAV/EventKit/iCloud集成
```

### 关键特性

1. **多线程设计**: 主线程处理信号和状态，工作线程执行同步
2. **状态持久化**: 状态信息保存到JSON文件，支持重启后恢复
3. **信号处理**: 优雅处理SIGTERM和SIGINT信号
4. **错误恢复**: 同步失败时自动重试，避免进程崩溃
5. **配置继承**: 完全使用原有config.json配置

## 配置说明

守护进程使用项目根目录的`config.json`配置文件，主要使用以下配置项：

```json
{
    "sync": {
        "interval_minutes": 30,  // 同步间隔（分钟）
        "sync_past_days": 30,    // 同步过去天数
        "sync_future_days": 365, // 同步未来天数
        "expand_recurring": true, // 展开循环事件
        "verify_threshold": 1,    // 验证阈值
        "override_icloud_deletions": true, // 覆盖iCloud删除
        "skip_sync_on_too_many_missing": true // 跳过过多缺失
    }
}
```

## 与原有方案的区别

| 特性 | 原有launchd方案 | 新Python守护进程方案 |
|------|----------------|---------------------|
| 权限问题 | 存在EventKit权限问题 | 使用Python定时器，无权限问题 |
| 终端依赖 | 需要保持终端运行 | 完全后台运行 |
| 状态监控 | 基础状态查看 | 详细状态统计和监控 |
| 错误处理 | 基础错误处理 | 完善的错误处理和恢复 |
| 配置管理 | 静态配置 | 动态配置读取 |
| 日志管理 | 基础日志 | 分级日志管理 |
| 进程管理 | 依赖系统服务 | 独立进程管理 |
| 调试能力 | 有限 | 强大的调试和监控能力 |

## 迁移指南

从原有的launchd方案迁移到新的Python守护进程方案：

1. **停止原有服务**
   ```bash
   ./background_timer.sh stop
   ./background_timer.sh remove
   ```

2. **安装新守护进程**
   ```bash
   python3 daemon/setup_daemon.py
   ```

3. **启动新服务**
   ```bash
   ./daemon/daemon_control.sh start
   ```

4. **安装开机自启**
   ```bash
   ./daemon/daemon_control.sh install
   ```

## 故障排除

### 常见问题

1. **权限问题**
   ```bash
   # 确保脚本有执行权限
   chmod +x daemon/daemon_control.sh
   ```

2. **依赖问题**
   ```bash
   # 安装必要的依赖
   pip3 install psutil schedule caldav icalendar keyring
   ```

3. **配置文件问题**
   ```bash
   # 确保配置文件存在且格式正确
   python3 install.py
   ```

4. **进程冲突**
   ```bash
   # 检查是否有其他实例在运行
   ./daemon/daemon_control.sh status
   
   # 强制停止所有实例
   pkill -f daemon_manager.py
   ```

### 调试方法

1. **查看详细日志**
   ```bash
   tail -f logs/daemon.log
   tail -f logs/daemon_error.log
   ```

2. **测试单次同步**
   ```bash
   ./daemon/daemon_control.sh test
   ```

3. **检查launchd服务**
   ```bash
   launchctl list | grep calsync
   ```

## 测试结果

所有功能测试通过：

- ✅ 守护进程启动/停止
- ✅ 状态监控和统计
- ✅ 日志记录和管理
- ✅ launchd服务安装/卸载
- ✅ 开机自启功能
- ✅ 配置继承和参数传递

## 注意事项

1. **首次运行**: 首次运行需要授权日历访问权限
2. **配置文件**: 确保`config.json`配置正确
3. **网络连接**: 确保网络连接正常
4. **iCloud权限**: 确保iCloud日历可访问
5. **日志监控**: 定期检查日志文件，及时发现问题

## 技术支持

如果遇到问题，请：

1. 查看日志文件了解详细错误信息
2. 检查配置文件是否正确
3. 确认所有依赖已正确安装
4. 验证网络连接和权限设置