# 交易系统启动脚本使用说明

## 📦 脚本列表

| 脚本 | 功能 | 说明 |
|------|------|------|
| `start.sh` | 启动系统 | 后台启动交易系统，日志重定向 |
| `stop.sh` | 停止系统 | 优雅停止交易系统 |
| `restart.sh` | 重启系统 | 停止并重新启动 |
| `status.sh` | 状态查询 | 查看运行状态、资源占用、最新日志 |

## 🚀 快速开始

### 1. 首次使用

```bash
# 给脚本添加执行权限
chmod +x start.sh stop.sh restart.sh status.sh

# 启动系统
./start.sh
```

### 2. 日常使用

```bash
# 查看状态
./status.sh

# 停止系统
./stop.sh

# 重启系统
./restart.sh
```

## 📋 详细说明

### start.sh - 启动脚本

**功能**：
- ✅ 启动前检查（Python、配置文件、Futu连接等）
- ✅ 后台运行，不占用终端
- ✅ 日志重定向到文件
- ✅ 保存 PID 文件，方便管理
- ✅ 防止重复启动

**使用方法**：
```bash
./start.sh
```

**输出文件**：
- `logs/trading_system.log` - 系统主日志（程序内部日志）
- `logs/stdout.log` - 标准输出重定向
- `logs/stderr.log` - 错误输出重定向
- `trading_system.pid` - 进程 PID 文件

**启动检查**：
1. ✓ Python3 环境
2. ✓ 配置文件存在
3. ✓ 启动脚本存在
4. ✓ 系统未重复运行
5. ⚠️  Futu OpenD 连接（可选继续）

**示例输出**：
```
========================================
   交易系统启动脚本
========================================

==> 执行启动前检查...
[INFO] ✓ Python: Python 3.9.7
[INFO] ✓ 配置文件: /Users/niningxi/Desktop/future/config.yaml
[INFO] ✓ 启动脚本: /Users/niningxi/Desktop/future/future_v_0_1/tradingsystem/system.py
[INFO] ✓ Futu OpenD 端口连接正常
[INFO] 所有检查通过！

==> 正在启动交易系统...
[INFO] ✓ 交易系统启动成功！
[INFO]   PID: 12345
[INFO]   配置: /Users/niningxi/Desktop/future/config.yaml
[INFO]   日志: /Users/niningxi/Desktop/future/logs/trading_system.log
[INFO]   标准输出: /Users/niningxi/Desktop/future/logs/stdout.log
[INFO]   错误输出: /Users/niningxi/Desktop/future/logs/stderr.log

[INFO] 查看实时日志: tail -f /Users/niningxi/Desktop/future/logs/trading_system.log
[INFO] 查看系统状态: ./status.sh
[INFO] 停止系统: ./stop.sh

========================================
```

---

### stop.sh - 停止脚本

**功能**：
- ✅ 优雅停止（先发送 SIGTERM）
- ✅ 等待最多 30 秒让进程正常退出
- ✅ 必要时强制终止（SIGKILL）
- ✅ 清理 PID 文件

**使用方法**：
```bash
./stop.sh
```

**停止过程**：
1. 发送 SIGTERM 信号（优雅停止）
2. 等待最多 30 秒
3. 如果仍在运行，发送 SIGKILL（强制终止）
4. 清理 PID 文件

**示例输出**：
```
========================================
   交易系统停止脚本
========================================

[INFO] 正在停止交易系统 (PID: 12345)...
[INFO] ✓ 交易系统已停止

========================================
```

---

### status.sh - 状态查询脚本

**功能**：
- ✅ 显示进程运行状态
- ✅ 显示 CPU、内存占用
- ✅ 显示运行时长
- ✅ 显示日志文件信息
- ✅ 显示最新日志内容
- ✅ 检查 Futu OpenD 连接
- ✅ 提供快捷命令提示

**使用方法**：
```bash
./status.sh
```

**示例输出**：
```
========================================
   交易系统状态查询
========================================

【进程信息】
  状态: 运行中 ✓
  PID: 12345
  启动时间: Sat Oct 12 09:30:15 2025
  运行时长: 02:15:30
  CPU 使用: 2.5%
  内存使用: 1.2%
  内存占用: 150 MB
  命令: python3 future_v_0_1/tradingsystem/system.py --config config.yaml

【Futu OpenD 状态】
  端口 11111: 已连接 ✓

【日志文件】
  系统日志: /Users/niningxi/Desktop/future/logs/trading_system.log
    大小: 2.5M, 行数: 15420
  标准输出: /Users/niningxi/Desktop/future/logs/stdout.log
    大小: 512K, 行数: 3250
  错误日志: /Users/niningxi/Desktop/future/logs/stderr.log
    大小: 0, 行数: 0

【最新日志】(最近10行)

--- 系统日志 ---
2025-10-12 11:45:23 - TradingSystem - INFO - 发现新信号: 1 条
2025-10-12 11:45:24 - StrategyV6 - INFO - ✓ 开仓决策: AAPL 100股 @$150.25
2025-10-12 11:45:25 - TradingSystem - INFO - 买入订单已提交: AAPL [ID: FT12345]
...

【快捷命令】
  启动系统: ./start.sh
  停止系统: ./stop.sh
  重启系统: ./restart.sh
  查看状态: ./status.sh
  实时日志: tail -f /Users/niningxi/Desktop/future/logs/trading_system.log
  查看对账: python view_reconciliation_history.py
  查看数据库: python show_db.py

========================================
```

---

### restart.sh - 重启脚本

**功能**：
- ✅ 依次执行 stop.sh 和 start.sh
- ✅ 等待 3 秒确保进程完全停止
- ✅ 简化重启流程

**使用方法**：
```bash
./restart.sh
```

---

## 📝 日志文件说明

### 1. trading_system.log
- **来源**：程序内部 logging 模块
- **内容**：系统运行日志、交易决策、错误信息
- **格式**：`时间 - 模块 - 级别 - 消息`
- **查看**：`tail -f logs/trading_system.log`

### 2. stdout.log
- **来源**：标准输出重定向
- **内容**：print 语句、启动停止记录
- **查看**：`tail -f logs/stdout.log`

### 3. stderr.log
- **来源**：标准错误重定向
- **内容**：未捕获的异常、系统错误
- **查看**：`tail -f logs/stderr.log`

---

## 🔍 常见问题

### 1. 启动失败：配置文件不存在

**问题**：
```
[ERROR] 配置文件不存在: /Users/niningxi/Desktop/future/config.yaml
```

**解决**：
- 确保 `config.yaml` 存在于项目根目录
- 检查路径是否正确

### 2. 启动失败：Futu OpenD 未启动

**问题**：
```
[WARN] ⚠️  Futu OpenD (端口 11111) 似乎未启动
```

**解决**：
- 启动 Futu 牛牛客户端
- 启动 Futu OpenD API 服务
- 确认端口 11111 已开放

### 3. 停止失败：进程无法终止

**问题**：
```
[ERROR] ✗ 无法停止进程 (PID: 12345)
```

**解决**：
```bash
# 手动强制终止
kill -9 12345

# 清理 PID 文件
rm -f trading_system.pid
```

### 4. 重复启动提示

**问题**：
```
[ERROR] 交易系统已经在运行中 (PID: 12345)
```

**解决**：
```bash
# 先停止现有进程
./stop.sh

# 然后再启动
./start.sh

# 或者直接重启
./restart.sh
```

---

## 💡 使用技巧

### 1. 实时监控日志

```bash
# 查看系统日志（彩色输出）
tail -f logs/trading_system.log | grep --color=auto "INFO\|ERROR\|WARN"

# 只看错误
tail -f logs/trading_system.log | grep ERROR

# 同时监控多个日志
tail -f logs/*.log
```

### 2. 定时查看状态

```bash
# 每 10 秒查看一次状态
watch -n 10 ./status.sh

# 持续监控进程
while true; do clear; ./status.sh; sleep 5; done
```

### 3. 日志归档

```bash
# 创建日志归档脚本
cat > archive_logs.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
ARCHIVE_DIR="logs/archive"
mkdir -p "$ARCHIVE_DIR"
tar -czf "$ARCHIVE_DIR/logs_$DATE.tar.gz" logs/*.log
echo "日志已归档: $ARCHIVE_DIR/logs_$DATE.tar.gz"
EOF

chmod +x archive_logs.sh
```

### 4. 开机自启动（可选）

**macOS (LaunchAgent)**：
```bash
# 创建 plist 文件
cat > ~/Library/LaunchAgents/com.trading.system.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trading.system</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/niningxi/Desktop/future/start.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/Users/niningxi/Desktop/future/logs/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/niningxi/Desktop/future/logs/stderr.log</string>
</dict>
</plist>
EOF

# 加载服务
launchctl load ~/Library/LaunchAgents/com.trading.system.plist

# 卸载服务
launchctl unload ~/Library/LaunchAgents/com.trading.system.plist
```

---

## 🛠️ 维护建议

### 1. 定期清理日志

```bash
# 压缩旧日志
gzip logs/trading_system.log.old

# 删除 30 天前的日志
find logs/ -name "*.log" -mtime +30 -delete
```

### 2. 监控磁盘空间

```bash
# 查看日志占用空间
du -sh logs/

# 查看数据库大小
du -sh op_trade_data/
```

### 3. 定期备份数据库

```bash
# 备份数据库
cp op_trade_data/trading.db op_trade_data/backup/trading_$(date +%Y%m%d).db

# 定时备份（crontab）
0 2 * * * cp /Users/niningxi/Desktop/future/op_trade_data/trading.db /path/to/backup/trading_$(date +\%Y\%m\%d).db
```

---

## 📞 故障排查

### 检查清单

- [ ] Futu OpenD 是否已启动？
- [ ] 配置文件是否正确？
- [ ] Python 环境是否正常？
- [ ] 网络连接是否正常？
- [ ] 磁盘空间是否充足？
- [ ] 日志文件是否有错误？

### 诊断命令

```bash
# 1. 检查进程
ps aux | grep python | grep system.py

# 2. 检查端口
lsof -i :11111

# 3. 检查日志
tail -n 100 logs/trading_system.log

# 4. 检查磁盘
df -h

# 5. 检查内存
top -l 1 | grep PhysMem
```

---

## ✅ 总结

| 操作 | 命令 | 说明 |
|------|------|------|
| 启动 | `./start.sh` | 后台启动系统 |
| 停止 | `./stop.sh` | 优雅停止系统 |
| 重启 | `./restart.sh` | 重启系统 |
| 状态 | `./status.sh` | 查看运行状态 |
| 实时日志 | `tail -f logs/trading_system.log` | 监控系统日志 |
| 对账历史 | `python view_reconciliation_history.py` | 查看对账记录 |
| 数据库 | `python show_db.py` | 查看数据库内容 |

**祝交易顺利！** 📈✨



