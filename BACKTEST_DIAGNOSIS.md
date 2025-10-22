# V7回测结果对比诊断

## 📊 结果对比

| 指标 | 你的代码 | 我的代码 | 差异 |
|-----|---------|---------|------|
| 交易笔数 | 538 | 359 | -179笔 (-33%) |
| 收益率 | +339.74% | +22.38% | -317% |
| 胜率 | 55.95% | 57.5% | +1.5% |
| 定时退出 | 477 (88.7%) | 289 (80.5%) | -188笔 |
| 止损 | 40 (7.4%) | 55 (15.3%) | +15笔 |
| 止盈 | 21 (3.9%) | 15 (4.2%) | -6笔 |
| 未平仓 | 6笔 | 0笔 | 我强制平仓了 |

## 🔍 可能的问题点

### 1. 时间转换逻辑

**你的代码**：
```python
hour = int(time_str.split(':')[0])
if hour < 12:  # 如果小时<12，日期+1天
    option_datetime = option_datetime + timedelta(days=1)
```

**我的代码**：
- 直接用pytz转换UTC+8 → ET
- **没有判断小时<12时+1天**

**❓ 这可能导致一些凌晨信号的日期不对？**

---

### 2. 买入价格计算

**你的代码**：
```python
# 1. 获取signal_time + entry_delay后的价格
entry_time_target = signal_time + timedelta(minutes=self.entry_delay)
entry_price = self.get_price_at_time(symbol, entry_time_target)

# 2. 实际买入价加滑点
actual_buy_price = entry_price * (1 + self.slippage)
```

**我的代码**：
- V7策略中：`buy_price = current_price * (1 + slippage)`
- 传给BacktestMarketClient的是`decision.price_limit`（已含滑点）
- BacktestMarketClient再次扣现金

**❓ 可能有双重滑点问题？**

---

### 3. 成本价vs市价

**关键问题**：止损应该用什么价格对比？

**你的代码**：
```python
pos.entry_price  # 这是原始买入价（不含滑点）
returns = (current_price - pos.entry_price) / pos.entry_price
```

**我的代码**：
```python
pos['cost_price']  # 这是什么价格？是否含滑点和手续费？
pnl_ratio = (current_price - cost_price) / cost_price
```

**❓ 如果我的cost_price已经含滑点，那计算盈亏时就不对了！**

---

### 4. 持仓天数计算

**你的代码**：
```python
exit_date = entry_time + timedelta(days=self.holding_days)  # 6个自然日
while exit_date.weekday() >= 5:  # 跳过周末
    exit_date += timedelta(days=1)
```

**我的代码**：
- 同样逻辑

**✅ 这个应该是对的**

---

## 💡 建议检查

请帮我确认以下几点：

1. **时间转换**：CSV中凌晨的时间是否需要+1天？
   - 例如：`2024-10-10 01:33:23` 是否应该变成 `2024-10-11 01:33:23`？

2. **买入价格**：
   - 策略中的`decision.price_limit`是否已含滑点？
   - BacktestMarketClient买入时用的价格是什么？
   - 持仓的`cost_price`应该是什么？

3. **止损对比**：
   - 止损时应该用 `entry_price`（不含滑点）还是 `cost_price`（含滑点）？

4. **为什么交易数少**：
   - 是否是过滤太严格？
   - 还是仓位管理的问题？

---

## 🔧 待修复项

基于诊断结果，可能需要修复：

- [ ] 时间转换逻辑（凌晨+1天）
- [ ] 买入价格/成本价的计算
- [ ] 止损对比的基准价格
- [ ] 其他未发现的差异

**请帮我确认上面的疑问点，我逐一修复！**

