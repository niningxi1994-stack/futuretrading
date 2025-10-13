# Future Trading System

基于期权交易信号的自动化交易系统

## 📋 项目简介

这是一个完整的期权交易自动化系统，支持：
- 📊 期权交易信号监控和解析
- 🤖 基于策略的自动买卖决策
- 💼 与富途证券（Futu）API 集成
- 📈 持仓管理和止盈止损
- 🔄 每日对账和数据校验
- 💾 完整的数据库持久化

## 🏗️ 系统架构

```
future_v_0_1/
├── config/           # 配置管理
├── database/         # 数据库模型和操作
├── market/           # 市场接口（Futu OpenD）
├── optionparser/     # 期权数据解析
├── strategy/         # 交易策略（V6）
└── tradingsystem/    # 系统主控和对账
```

## ✨ 核心功能

### 1. 期权信号监控
- 监控指定目录下的期权交易数据文件
- 解析 UnusualWhales 格式的期权数据
- 自动识别新增交易信号
- 支持时区转换（北京时间 → 美东时间）

### 2. 交易策略（V6）
- **过滤条件**：
  - 最小权利金要求
  - 入场时间限制
  - 每日交易次数限制
  - 仓位比例控制
  - 黑名单机制（避免短期重复交易）
  
- **风控管理**：
  - 止盈：+15%
  - 止损：-5%
  - 持仓天数限制：6 个交易日
  - 最大总仓位：99%
  - 单笔最大仓位：30%

### 3. 数据持久化
- **SQLite 数据库**存储：
  - 订单记录（买入/卖出）
  - 持仓信息
  - 期权信号
  - 策略状态
  - 对账结果
  
### 4. 每日对账
- **对账时间**：每日 17:00（美东时间）
- **对账内容**：
  - 持仓对账（数据库 vs Futu）
  - 订单对账
  - 资金对账
  - 自动修复数据差异
  
- **对账报告**：
  - 每日买入统计
  - 每日卖出统计
  - 当前持仓情况
  - 实现盈亏分析

## 🚀 快速开始

### 环境要求

- Python 3.9+
- Futu OpenD（富途牛牛客户端）
- SQLite 3

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置文件

编辑 `config.yaml`：

```yaml
# 期权监控配置
option_monitor:
  watch_dir: '/path/to/option/data'
  persistant_dir: '/path/to/data/storage'

# 系统配置
system:
  check_interval: 20  # 检查间隔（秒）
  reconciliation:
    time: '17:00:00'  # 对账时间
    auto_fix: true    # 自动修复差异

# 策略配置
strategy:
  name: 'v6'
  filter:
    min_premium_usd: 100000
    entry_time_et: "15:30:00"
    max_trade_time: 5
    max_position: 0.99
  take_profit: 0.15
  stop_loss: 0.05
  holding_days: 6
  blacklist_days: 15
```

### 运行系统

#### 方式 1: 使用启动脚本（推荐）

```bash
# 添加执行权限（首次使用）
chmod +x start.sh stop.sh restart.sh status.sh

# 启动系统（后台运行）
./start.sh

# 查看状态
./status.sh

# 停止系统
./stop.sh

# 重启系统
./restart.sh
```

#### 方式 2: 直接运行 Python

```bash
cd future_v_0_1/tradingsystem
python system.py --config ../../config.yaml
```

### 📜 启动脚本说明

系统提供了完整的启动管理脚本：

- **start.sh** - 后台启动系统，日志重定向
- **stop.sh** - 优雅停止系统
- **restart.sh** - 重启系统
- **status.sh** - 查看运行状态、CPU/内存占用、最新日志

详细使用说明请查看：[SCRIPTS_USAGE.md](SCRIPTS_USAGE.md)

## 📊 数据查询工具

### 查看数据库内容

```bash
python show_db.py
```

### 查看对账历史

```bash
# 查看最近对账记录
python view_reconciliation_history.py

# 查看指定日期详情
python view_reconciliation_history.py --detail 2025-10-12

# 查看统计汇总
python view_reconciliation_history.py --summary
```

## 📈 策略说明

### V6 策略核心逻辑

**开仓条件**：
1. 权利金 ≥ $100,000
2. 时间 ≥ 15:30 ET
3. 今日交易次数 < 5
4. 不在黑名单中（过去15天未交易过）
5. 总仓位 + 新仓位 ≤ 99%
6. 现金充足

**平仓条件**：
1. 止盈：浮盈 ≥ +15%
2. 止损：浮亏 ≥ -5%
3. 持仓到期：持仓 ≥ 6个交易日，且当日15:00后

**黑名单机制**：
- 买入某股票后，立即加入黑名单
- 黑名单有效期：15个交易日
- 防止短期内重复交易同一标的

## 🗄️ 数据库表结构

- `orders` - 订单记录
- `positions` - 持仓信息
- `processed_files` - 已处理文件
- `strategy_state` - 策略状态
- `option_signals` - 期权信号
- `reconciliation_results` - 对账结果

## 🔧 开发说明

### 项目结构

```
future/
├── config.yaml                    # 主配置文件
├── design.md                      # 设计文档
├── future_v_0_1/                 # 主项目代码
│   ├── config/                   # 配置模块
│   ├── database/                 # 数据库模块
│   ├── market/                   # 市场接口
│   ├── optionparser/             # 期权解析
│   ├── strategy/                 # 交易策略
│   └── tradingsystem/            # 系统主控
├── show_db.py                    # 数据库查询工具
└── view_reconciliation_history.py # 对账历史查询工具
```

### 日志

系统日志保存在 `logs/` 目录：
- `trading_system.log` - 主系统日志
- `trading_monitor.log` - 监控日志

## ⚠️ 注意事项

1. **时区统一**：系统统一使用美东时间（ET）
2. **数据备份**：定期备份 `trading.db`
3. **Futu连接**：确保 Futu OpenD 已启动并正常运行
4. **网络稳定**：对账和交易需要稳定的网络连接
5. **权限管理**：确保有文件读写权限

## 📝 更新日志

### 2025-10-12
- ✅ 实现对账结果数据库存储
- ✅ 添加黑名单实时更新机制
- ✅ 修复持仓天数计算（使用交易日）
- ✅ 优化日志输出（INFO/DEBUG分级）
- ✅ 添加每日17:00自动对账功能

### 2025-10-11
- ✅ 实现 V6 交易策略
- ✅ 集成 Futu OpenD API
- ✅ 实现数据库持久化
- ✅ 实现每日对账模块

## 📄 许可证

MIT License

## 👤 作者

niningxi1994-stack

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📧 联系方式

如有问题，请通过 GitHub Issues 联系。

