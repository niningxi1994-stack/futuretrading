# 🚀 快速启动指南

## 📋 一分钟上手

```bash
# 1. 给脚本添加执行权限（首次使用）
chmod +x *.sh

# 2. 启动交易系统
./start.sh

# 3. 查看运行状态
./status.sh

# 4. 实时监控日志
tail -f logs/trading_system.log
```

## 🎯 常用命令

| 操作 | 命令 | 说明 |
|------|------|------|
| 🚀 **启动** | `./start.sh` | 后台启动系统 |
| 🛑 **停止** | `./stop.sh` | 优雅停止系统 |
| 🔄 **重启** | `./restart.sh` | 重启系统 |
| 📊 **状态** | `./status.sh` | 查看运行状态 |
| 📝 **日志** | `tail -f logs/trading_system.log` | 实时查看日志 |
| 📈 **对账** | `python view_reconciliation_history.py` | 查看对账历史 |
| 🗄️ **数据库** | `python show_db.py` | 查看数据库 |

## 📂 项目结构

```
future/
├── start.sh                     # ⭐ 启动脚本
├── stop.sh                      # ⭐ 停止脚本
├── restart.sh                   # ⭐ 重启脚本
├── status.sh                    # ⭐ 状态查询脚本
├── config.yaml                  # ⭐ 配置文件
├── README.md                    # 详细文档
├── SCRIPTS_USAGE.md             # 脚本使用说明
├── future_v_0_1/                # 主程序代码
│   ├── config/                  # 配置模块
│   ├── database/                # 数据库模块
│   ├── market/                  # 市场接口
│   ├── optionparser/            # 期权解析
│   ├── strategy/                # 交易策略
│   └── tradingsystem/           # 系统主控
├── logs/                        # 日志目录
│   ├── trading_system.log       # 系统日志
│   ├── stdout.log              # 标准输出
│   └── stderr.log              # 错误输出
├── op_trade_data/              # 交易数据
│   └── trading.db              # SQLite 数据库
├── show_db.py                  # 数据库查询工具
└── view_reconciliation_history.py  # 对账历史工具
```

## ⚙️ 配置要点

编辑 `config.yaml`：

```yaml
# 监控目录（存放期权数据文件）
option_monitor:
  watch_dir: '/path/to/option/data'
  persistant_dir: '/path/to/data/storage'

# 对账时间（美东时间）
system:
  reconciliation:
    time: '17:00:00'

# 策略参数
strategy:
  filter:
    min_premium_usd: 100000     # 最小权利金
    entry_time_et: "15:30:00"   # 入场时间
    max_trade_time: 5           # 每日最大交易次数
  take_profit: 0.15             # 止盈 +15%
  stop_loss: 0.05               # 止损 -5%
  holding_days: 6               # 持仓天数
  blacklist_days: 15            # 黑名单天数
```

## 🔍 运行检查清单

启动前确保：

- [x] Futu OpenD 已启动（端口 11111）
- [x] `config.yaml` 配置正确
- [x] Python 3.9+ 已安装
- [x] 依赖包已安装（`pip install -r requirements.txt`）
- [x] 监控目录有读权限
- [x] 数据目录有写权限

## 📊 监控系统

### 查看实时日志

```bash
# 系统日志
tail -f logs/trading_system.log

# 只看重要信息
tail -f logs/trading_system.log | grep -E "INFO|ERROR|买入|卖出"

# 查看错误
tail -f logs/stderr.log
```

### 查看系统状态

```bash
# 完整状态信息
./status.sh

# 持续监控（每 5 秒刷新）
watch -n 5 ./status.sh
```

### 查看对账结果

```bash
# 最近 7 天对账记录
python view_reconciliation_history.py

# 查看指定日期详情
python view_reconciliation_history.py --detail 2025-10-12

# 查看统计汇总
python view_reconciliation_history.py --summary
```

## 🛠️ 故障排查

### 1. 启动失败

```bash
# 查看错误日志
tail -n 50 logs/stderr.log

# 检查 Futu 连接
nc -zv 127.0.0.1 11111

# 手动运行（查看详细错误）
python future_v_0_1/tradingsystem/system.py --config config.yaml
```

### 2. 进程异常退出

```bash
# 查看最后的日志
tail -n 100 logs/trading_system.log

# 查看系统日志
cat logs/stdout.log | grep "ERROR"

# 重启系统
./restart.sh
```

### 3. 无法停止

```bash
# 查看进程
ps aux | grep python | grep system.py

# 强制终止（替换 PID）
kill -9 <PID>

# 清理 PID 文件
rm -f trading_system.pid
```

## 💡 使用技巧

### 开机自启动（可选）

```bash
# macOS - 创建 LaunchAgent
# 详见 SCRIPTS_USAGE.md
```

### 定时备份数据库

```bash
# 添加到 crontab
crontab -e

# 每天凌晨 2 点备份
0 2 * * * cp /Users/niningxi/Desktop/future/op_trade_data/trading.db /path/to/backup/trading_$(date +\%Y\%m\%d).db
```

### 日志归档

```bash
# 压缩旧日志
cd logs
gzip trading_system.log.old

# 删除 30 天前的日志
find logs/ -name "*.log.gz" -mtime +30 -delete
```

## 📞 获取帮助

- **详细文档**: [README.md](README.md)
- **脚本说明**: [SCRIPTS_USAGE.md](SCRIPTS_USAGE.md)
- **设计文档**: [design.md](design.md)
- **GitHub**: https://github.com/niningxi1994-stack/futuretrading

## ⚡ 快捷键

创建命令别名（添加到 `~/.bashrc` 或 `~/.zshrc`）：

```bash
# 交易系统别名
alias ts-start='cd /Users/niningxi/Desktop/future && ./start.sh'
alias ts-stop='cd /Users/niningxi/Desktop/future && ./stop.sh'
alias ts-status='cd /Users/niningxi/Desktop/future && ./status.sh'
alias ts-log='tail -f /Users/niningxi/Desktop/future/logs/trading_system.log'
alias ts-recon='cd /Users/niningxi/Desktop/future && python view_reconciliation_history.py'
```

使用：
```bash
ts-start    # 启动
ts-status   # 状态
ts-log      # 查看日志
ts-stop     # 停止
```

---

**祝交易顺利！** 🎯📈✨



