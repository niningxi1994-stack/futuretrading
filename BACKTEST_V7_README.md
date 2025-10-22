## 📊 V7策略回测系统

基于CSV历史数据的完整回测系统，支持V7策略的所有特性。

---

## 🚀 快速开始

### 0. 安装依赖

```bash
# 安装pyyaml（如果还没安装）
pip install pyyaml
```

### 1. 基础运行

```bash
# 使用默认配置运行全部CSV文件
python3 run_backtest_v7.py

# 或者
python3 -m future_v_0_1.backtest.backtest_engine
```

### 2. 测试运行（前10个文件）

```bash
python3 run_backtest_v7.py --max-files 10
```

### 3. 自定义参数

```bash
python3 run_backtest_v7.py \
    --config config_v7.yaml \
    --csv-dir future_v_0_1/database/call_csv_files \
    --initial-cash 200000 \
    --log-level DEBUG \
    --save-report backtest_report_20251022.json
```

---

## 📁 文件结构

```
futuretrading/
├── run_backtest_v7.py                      # 回测运行脚本
├── config_v7.yaml                          # V7策略配置
├── future_v_0_1/
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── backtest_client.py              # 模拟市场客户端
│   │   └── backtest_engine.py              # 回测引擎
│   └── database/
│       └── call_csv_files/                 # CSV数据目录
│           ├── AAPL_2023-10-20_ET.csv
│           ├── MSTR_2024-12-27_ET.csv
│           └── ...
└── logs/
    └── backtest_report_*.json              # 回测报告（可选）
```

---

## 📋 CSV文件格式

### 必需列

| 列名 | 说明 | 示例 |
|-----|------|------|
| date | 日期 | 2024-12-27 |
| time | 时间 | 04:44:22 |
| underlying_symbol | 股票代码 | MSTR |
| side | 方向 | BID/ASK |
| contract | 合约 | 357.5 put 2025-01-03 |
| premium | 期权溢价 | 301000 |
| stock_price | 股票价格 | 342.17 |

### 数据组织

- **第1行**: 列名（header）
- **第2-N-1行**: 历史数据（过去7天的期权流，用于计算历史均值）
- **第N行**: 交易信号（最后一行）

### 示例

```csv
date,time,underlying_symbol,side,contract,strike_price,option_type,expiry_date,dte,stock_price,bid_ask,spot,size,premium,volume,oi,source_file
2024-12-20,03:08:36,MSTR,ASK,830 put 2024-12-20,830,put,2024-12-20,-295d,338.27,$490.70 - $492.25,$492.25,6,295000,10,0,MSTR_2024-12-27_ET.txt
2024-12-20,03:22:25,MSTR,BID,310 call 2026-12-18,310,call,2026-12-18,433d,332.7,$180.00 - $182.25,$180.00,4,72000,4,3,MSTR_2024-12-27_ET.txt
...（更多历史数据）...
2024-12-27,04:44:22,MSTR,ASK,357.5 put 2025-01-03,357.5,put,2025-01-03,-281d,342.17,$24.65 - $25.35,$25.05,120,301000,135,38,MSTR_2024-12-27_ET.txt
```

---

## 🎯 回测逻辑

### 1. 数据处理

1. 加载CSV文件
2. 读取历史数据（第2行到倒数第2行）
3. 读取交易信号（最后一行）
4. 计算历史premium均值

### 2. 策略执行

1. **历史Premium过滤**
   - 当前premium >= 历史均值 × 2倍
   - 如果无历史数据，允许交易（容错）

2. **V7策略过滤**
   - 交易时间窗口（10:00 AM ~ 15:54）
   - 期权溢价 >= $100,000
   - 黑名单检查（15天）
   - 每日交易次数限制（5笔）
   - 总仓位限制（99%）
   - 杠杆限制（1.95x）

3. **交易执行**
   - 买入：扣除现金，增加持仓
   - 卖出：增加现金，减少持仓
   - 计算手续费和滑点

### 3. 持仓管理

由于回测基于单个CSV文件（单次信号），当前版本：
- **只模拟开仓**，不模拟平仓
- 专注于**入场条件**的验证
- 适合测试信号过滤效果

---

## 📊 回测报告

### 报告内容

```
=== 账户概况 ===
  初始资金: $100,000.00
  最终资金: $45,230.50
  持仓市值: $58,450.00
  总资产: $103,680.50
  总盈亏: +$3,680.50
  收益率: +3.68%

=== 交易统计 ===
  总信号数: 100
  买入信号: 25
  过滤信号: 75
  过滤率: 75.0%
  实际交易数: 25
  持仓数: 25

=== 盈亏分析 ===
  已实现盈亏: $0.00
  未实现盈亏: $3,680.50
```

### 持仓明细

```
持仓明细:
股票       数量        成本价         现价          盈亏            盈亏率    
--------------------------------------------------------------------------------
AAPL       100        $150.50       $152.30       +$180.00       +1.2%
MSFT       50         $380.20       $390.50       +$515.00       +2.7%
...
```

---

## ⚙️ 命令行参数

### 基本参数

| 参数 | 说明 | 默认值 |
|-----|------|--------|
| `--config`, `-c` | 配置文件路径 | config_v7.yaml |
| `--csv-dir`, `-d` | CSV文件目录 | future_v_0_1/database/call_csv_files |
| `--initial-cash` | 初始资金 | 100000.0 |
| `--max-files` | 最大文件数（测试用） | None（全部） |

### 日志参数

| 参数 | 说明 | 默认值 |
|-----|------|--------|
| `--log-level` | 日志级别 | INFO |

可选值：DEBUG, INFO, WARNING, ERROR

### 输出参数

| 参数 | 说明 | 默认值 |
|-----|------|--------|
| `--save-report` | 保存报告到JSON文件 | None（不保存） |

---

## 💡 使用示例

### 示例1：快速测试

```bash
# 测试前5个文件，查看策略效果
python3 run_backtest_v7.py --max-files 5 --log-level DEBUG
```

### 示例2：完整回测

```bash
# 运行全部文件，保存报告
python3 run_backtest_v7.py \
    --initial-cash 100000 \
    --save-report reports/backtest_$(date +%Y%m%d).json
```

### 示例3：大资金测试

```bash
# 测试200万初始资金
python3 run_backtest_v7.py --initial-cash 2000000
```

### 示例4：调整配置

```bash
# 修改 config_v7.yaml 中的参数后运行
# 例如：降低历史倍数 historical_premium_multiplier: 1.5
python3 run_backtest_v7.py --config config_v7.yaml
```

---

## 🔍 常见问题

### Q1: 为什么只有买入没有卖出？

**A:** 当前回测版本专注于**入场信号验证**，每个CSV文件只包含一个交易信号。如果需要完整的买卖模拟，需要：
- 添加股票历史价格数据
- 实现持仓的止盈止损逻辑
- 模拟时间推进和定时退出

### Q2: 如何修改策略参数？

**A:** 编辑 `config_v7.yaml` 文件，修改相应参数：

```yaml
filter:
  historical_premium_multiplier: 1.5  # 降低历史倍数
  min_option_premium: 50000           # 降低溢价门槛

position_compute:
  max_single_position: 0.20           # 降低单笔仓位
```

### Q3: 如何查看详细的过滤原因？

**A:** 使用DEBUG日志级别：

```bash
python3 run_backtest_v7.py --log-level DEBUG
```

### Q4: CSV文件找不到怎么办？

**A:** 检查CSV目录路径：

```bash
# 查看CSV文件
ls -l future_v_0_1/database/call_csv_files/*.csv

# 指定正确的路径
python3 run_backtest_v7.py --csv-dir /your/path/to/csv
```

### Q5: 如何批量回测不同配置？

**A:** 创建多个配置文件，分别运行：

```bash
# 配置1：保守型
python3 run_backtest_v7.py --config config_v7_conservative.yaml --save-report report_conservative.json

# 配置2：激进型
python3 run_backtest_v7.py --config config_v7_aggressive.yaml --save-report report_aggressive.json
```

---

## 📈 回测优化建议

### 1. 参数调优

通过回测找到最优参数组合：

- **历史倍数**：1.5x ~ 3.0x
- **最小溢价**：$50K ~ $200K
- **单笔仓位**：20% ~ 50%
- **杠杆倍数**：1.0x ~ 2.0x

### 2. 过滤率分析

- **过滤率太高**（>90%）：策略过于严格，放宽条件
- **过滤率太低**（<50%）：策略过于宽松，收紧条件
- **理想范围**：60% ~ 80%

### 3. 样本量

- 至少回测100个信号
- 覆盖不同市场环境
- 关注极端情况

---

## 🛠️ 扩展功能

### 未来可添加

1. **完整交易模拟**
   - 添加分钟级股价数据
   - 实现止盈止损
   - 模拟定时退出

2. **性能指标**
   - 最大回撤
   - 夏普比率
   - 胜率统计

3. **可视化**
   - 权益曲线
   - 持仓分布
   - 盈亏分布

4. **报告增强**
   - HTML报告
   - PDF导出
   - 交易明细表

---

## 📝 注意事项

1. **历史数据质量**：确保CSV文件格式正确，数据完整
2. **配置一致性**：回测配置应与实盘配置保持一致
3. **过拟合风险**：避免过度优化参数以适应历史数据
4. **市场环境**：回测结果仅供参考，实盘可能不同

---

## 🎓 最佳实践

1. **先测试后实盘**：用少量文件验证代码正确性
2. **参数稳定性**：测试参数在不同时期的稳定性
3. **风险控制**：关注最大持仓数和杠杆使用
4. **日志审查**：定期查看过滤原因，优化策略

---

**祝回测顺利！** 📊

