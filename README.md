# Future Trading - Options Flow Strategy Backtesting System

A professional event-driven options trading backtesting framework with V8 strategy implementation.

## Features

- **Event-Driven Architecture**: Minute-level backtesting with 20-second interval precision
- **CSV Data Source**: Historical options flow data with premium tracking
- **Fixed Position Management**: Configurable position sizing (default 5% per trade)
- **Multi-Exit Strategy**: Stop-loss, take-profit, trailing stop, strike/expiry-based exits
- **Advanced Filtering**: DTE, OTM ratio, premium range, MACD, earnings, price trend filters
- **Dynamic Caching**: Memory-efficient stock data prefetching and cleanup
- **NYSE Calendar**: Integrated trading day validation

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd futuretrading

# Install dependencies
pip install pandas pandas-market-calendars pytz pyyaml
```

### Run Backtest

```bash
# Run with default configuration
python run_backtest_v8.py

# Customize parameters
python run_backtest_v8.py \
  --config config_v8.yaml \
  --csv future_v_0_1/database/merged_strategy_v1_calls_bell_2023M3_2025M10.csv \
  --cash 1000000 \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --output backtest_results.json
```

## Configuration

Edit `config_v8.yaml` to customize strategy parameters:

### Entry Filters

```yaml
strategy:
  filter:
    # Trading time windows (ET)
    trade_time_ranges:
      - ['09:30:00', '16:00:00']
    
    # DTE (Days to Expiration) filter
    dte_min: 0
    dte_max: 365
    
    # OTM (Out of The Money) ratio filter (%)
    otm_min: 0.0
    otm_max: 30
    
    # Premium filter (USD)
    premium_min: 0
    premium_max: 50000000
    
    # MACD filter (optional)
    macd_enabled: false
    macd_threshold: 0
    
    # Earnings filter (optional)
    earnings_enabled: false
    earnings_max: 5
    
    # Price trend filter (optional)
    price_trend_enabled: false
    price_trend_lookback: 21
```

### Position Management

```yaml
  position_compute:
    fixed_position_ratio: 0.05  # 5% per trade
    max_daily_position: 0.99    # Max 99% total exposure
```

### Exit Conditions

```yaml
  stop_loss: 0.1              # -10% stop loss
  take_profit: 0.4            # +40% take profit
  trailing_stop_loss: 0.3     # -30% trailing stop
  exit_time: '10:00:00'       # Expiry day exit time (ET)
```

## Project Structure

```
futuretrading/
├── config_v8.yaml                  # Strategy configuration
├── run_backtest_v8.py              # Main backtest runner
├── plot_account_equity.py          # Performance visualization
└── future_v_0_1/
    ├── strategy/
    │   ├── v8.py                   # V8 strategy implementation
    │   └── strategy.py             # Base strategy classes
    ├── market/
    │   ├── backtest_client.py      # Backtesting market client
    │   └── futu_client.py          # Live trading client (Futu API)
    ├── database/
    │   ├── models.py               # Data models
    │   └── merged_strategy_v1_calls_bell_*.csv  # Options flow data
    └── optionparser/
        ├── parser.py               # Options data parser
        └── utils.py                # Utility functions
```

## Output

Backtest generates a JSON report containing:

- **Account Summary**: Initial/final cash, P&L, ROI
- **Trade Statistics**: Total signals, buy/sell count, filter rate
- **Trade Records**: Detailed entry/exit logs with profit tracking
- **Performance Metrics**: Realized/unrealized P&L

Example output structure:

```json
{
  "backtest_time": "2025-10-31T12:00:00",
  "initial_cash": 1000000.0,
  "report": {
    "=== Account Summary ===": {
      "Total Assets": "$1,234,567.89",
      "Total P&L": "+$234,567.89",
      "ROI": "+23.46%"
    },
    "=== Trade Statistics ===": {
      "Total Signals": 1500,
      "Buy Signals": 500,
      "Filter Rate": "66.7%"
    }
  },
  "trades": [...]
}
```

## Key Algorithms

### Signal Processing

- **10-minute delay**: Signals are delayed by 10 minutes to simulate real-world execution lag
- **20-second intervals**: Backtesting runs on 20-second time slices for precision
- **Time zone handling**: Beijing time → ET conversion for signal timestamps

### Exit Priority

1. **Expiry Exit**: Sell at `exit_time` on expiry date
2. **Strike Exit**: Sell when stock price reaches option strike
3. **Take Profit**: Sell when profit ≥ `take_profit` threshold
4. **Trailing Stop**: Sell when price drops `trailing_stop_loss` from highest
5. **Stop Loss**: Sell when loss ≥ `stop_loss` threshold

### Memory Optimization

- **Dynamic prefetching**: Load 6 days of stock data per symbol when needed
- **Auto cleanup**: Clear symbol cache after position exit
- **Memory footprint**: Only active positions kept in cache

## Advanced Usage

### Custom Date Range

```bash
python run_backtest_v8.py \
  --start-date 2024-06-01 \
  --end-date 2024-08-31
```

### Modify Position Size

```yaml
# config_v8.yaml
strategy:
  position_compute:
    fixed_position_ratio: 0.10  # 10% per trade (more aggressive)
```

### Enable MACD Filter

```yaml
strategy:
  filter:
    macd_enabled: true
    macd_threshold: 0           # Only trade when MACD > 0
    macd_short_window: 12
    macd_long_window: 26
    macd_signal_window: 9
```

## Performance Tips

- Use `--log-file` to redirect logs and reduce console overhead
- Adjust `trade_time_ranges` to focus on specific market hours
- Enable filters progressively to understand their impact
- Monitor memory usage for large date ranges (use cleanup effectively)

## License

MIT License - See LICENSE file for details

## Author

Future Trading System V0.1

