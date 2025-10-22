# V7策略回测使用指南

## 📂 文件结构

```
futuretrading/
├── config_v7.yaml                       # V7策略配置（实盘+回测共用）
├── run_backtest_v7.py                   # 回测运行脚本
└── future_v_0_1/
    ├── market/
    │   ├── futu_client.py               # 实盘客户端（FutuOpenD API）
    │   ├── backtest_client.py           # 回测客户端（CSV数据）
    │   └── backtest_engine.py           # 回测引擎
    ├── strategy/
    │   └── v7.py                        # V7策略实现
    └── database/
        ├── call_csv_files_clean/        # 期权信号数据（已清洗）
        └── stock_data_csv_min/          # 股价分钟级数据
```

---

## 🚀 快速开始

### 运行完整回测

```bash
python3 run_backtest_v7.py --save-report backtest_result.json
```

### 测试运行（前N个文件）

```bash
# 测试前20个文件
python3 run_backtest_v7.py --max-files 20

# 测试前100个文件
python3 run_backtest_v7.py --max-files 100
```

### 调试模式

```bash
python3 run_backtest_v7.py --max-files 10 --log-level DEBUG
```

---

## ⚙️ 配置说明（config_v7.yaml）

### 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `trade_start_time` | `12:30:00` | 中午12:30 PM之后（ET时间）|
| `historical_premium_multiplier` | `2.0` | 历史均值的2倍 |
| `min_option_premium` | `100000` | 最小期权溢价$100K |
| `max_daily_trades` | `5` | 每日最多5笔 |
| `max_single_position` | `0.40` | 单笔仓位40% |
| `min_cash_ratio` | `0.01` | 不允许杠杆 |
| `stop_loss` | `0.10` | 止损-10% |
| `take_profit` | `0.20` | 止盈+20% |
| `holding_days` | `6` | 持仓6个交易日 |
| `blacklist_days` | `15` | 黑名单15天 |

---

## 🔍 数据说明

### 时间处理
- **CSV时间**：UTC+8（北京时间）
- **自动转换**：pytz → 纽约时间（ET）
- **夏令时/冬令时**：自动处理

### 数据源
- **期权信号**：`call_csv_files_clean/` 
  - 每个CSV最后一行是交易信号
  - 前面的行是历史数据（用于计算均值）
  
- **股价数据**：`stock_data_csv_min/`
  - 分钟级OHLCV数据
  - 用于计算真实盈亏

---

## 📊 回测结果示例

```
=== 账户概况 ===
  初始资金: $100,000.00
  最终资金: $151,063.21
  总盈亏: +$51,063.21
  收益率: +51.06%

=== 交易统计 ===
  总信号数: 20
  买入信号: 3
  过滤率: 85.0%
  实际交易数: 3

=== 盈亏分析 ===
  已实现盈亏: +$51,063.21
```

---

## 🎯 使用提示

1. **先小规模测试**：`--max-files 20` 
2. **查看过滤原因**：`--log-level DEBUG`
3. **完整回测**：不加 `--max-files` 参数
4. **保存报告**：`--save-report filename.json`

**现在可以运行完整回测了！** 🚀

