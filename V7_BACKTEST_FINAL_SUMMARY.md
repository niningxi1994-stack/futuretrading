# V7策略回测系统 - 最终总结

## ✅ 已完成功能

### 1. 完整的回测系统
- ✅ 时间转换：UTC+8 → ET（pytz自动处理夏令时/冬令时）
- ✅ 历史Premium过滤：严格大于2倍均值（`>`不是`>=`）
- ✅ 逐分钟检查持仓：从entry_time扫描到当前时间，及时触发止盈止损
- ✅ 定时退出：6个自然日（跳过周末）+ 15:00平仓
- ✅ 黑名单机制：15天不重复交易
- ✅ 真实股价数据：从`stock_data_csv_min/`读取分钟K线

### 2. 文件架构
```
future_v_0_1/market/
├── futu_client.py          # 实盘客户端
├── backtest_client.py      # 回测客户端（完全模拟FutuClient接口）
└── backtest_engine.py      # 回测引擎
```

### 3. 数据源
- **期权信号**：`future_v_0_1/database/call_csv_files_clean/`
- **股价数据**：`future_v_0_1/database/stock_data_csv_min/`

---

## 📊 回测结果（使用clean数据）

```
总信号数: 6253
买入信号: 359笔
收益率: +22.38%
过滤率: 94.3%

退出原因分布:
  定时退出: 289笔 (80.5%)
  止损: 55笔 (15.3%)
  止盈: 15笔 (4.2%)

胜率: 57.5%
平均盈利: 4.87%
平均亏损: -4.03%
```

---

## 🚀 运行命令

```bash
# 完整回测（使用clean数据）
python3 run_backtest_v7.py --save-report backtest_result.json

# 测试
python3 run_backtest_v7.py --max-files 50

# 调试
python3 run_backtest_v7.py --max-files 20 --log-level DEBUG
```

---

## 📝 关键配置（config_v7.yaml）

```yaml
trade_start_time: '12:30:00'            # 中午12:30 PM（ET）
historical_premium_multiplier: 2.0       # 严格大于2倍
min_option_premium: 100000              # $100K门槛
max_daily_trades: 5                     # 每日5笔
max_single_position: 0.40               # 单笔40%
min_cash_ratio: 0.01                    # 不允许杠杆
stop_loss: 0.10                         # 止损-10%
take_profit: 0.20                       # 止盈+20%
holding_days: 6                         # 6个自然日
blacklist_days: 15                      # 黑名单15天
```

---

## ⚙️ 核心实现

### 时间驱动架构
1. 按信号时间排序
2. 每个信号时间点：
   - 先扫描所有持仓的分钟价格，检查止盈止损
   - 再处理新信号

### 止盈止损检查
- 从entry_time扫描到当前时间的**所有分钟价格**
- 逐一检查是否触发止损（<= -10%）或止盈（>= +20%）
- 一旦触发立即平仓

### 定时退出
- entry_time + 6个自然日 + 跳过周末
- 15:00之后平仓

---

## 🎯 使用说明

V7策略回测系统已完成，可以正常使用。

**如需调整参数，直接修改 `config_v7.yaml` 即可。**

---

**回测系统交付完成！** ✅

