#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Plot backtest results - Account equity curve analysis
优化版本，支持JSON和CSV两种格式

使用方法：
    1. 修改下面的 CONFIGURATION 部分的参数
    2. 运行: python plot_account_equity.py
    
示例：
    # 绘制V7版本的回测结果（JSON格式）
    BACKTEST_FILE = 'backtest_v7_final.json'
    OUTPUT_IMAGE = 'equity_curve_v7.png'
    
    # 绘制V6版本的回测结果（CSV格式）
    BACKTEST_FILE = 'backtest_trades_v6_event_driven.csv'
    OUTPUT_IMAGE = 'equity_curve_v6.png'
"""

import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import matplotlib.dates as mdates
import os
import json
from zoneinfo import ZoneInfo

# ============================================================================
# CONFIGURATION - 修改这里的参数
# ============================================================================

# 回测结果文件路径（支持.json或.csv格式）
BACKTEST_FILE = 'backtest_v8_test.json'

# 输出图片文件名
OUTPUT_IMAGE = 'equity_curve_v8.png'

# 初始资金（如果从JSON读取则会自动使用JSON中的值）
INITIAL_CAPITAL = 1000000

# SPY和QQQ历史数据文件（使用数据库目录下的文件）
SPY_DATA_FILE = 'future_v_0_1/database/spy_historical_data.csv'
QQQ_DATA_FILE = 'future_v_0_1/database/qqq_historical_data.csv'

# ============================================================================

# 设置matplotlib参数
plt.rcParams['figure.facecolor'] = 'white'
plt.rcParams['axes.facecolor'] = 'white'
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def load_backtest_data(filename):
    """
    Load backtest data from JSON or CSV file
    
    Returns:
        tuple: (trades_df, initial_capital, report_dict)
    """
    if not os.path.exists(filename):
        print(f"Error: Cannot find {filename}")
        return None, None, None
    
    file_ext = os.path.splitext(filename)[1].lower()
    
    if file_ext == '.json':
        # Load JSON format
        print(f"Loading backtest data from JSON: {filename}...")
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        initial_capital = data.get('initial_cash', INITIAL_CAPITAL)
        trades_list = data.get('trades', [])
        report = data.get('report', {})
        
        # Convert trades to DataFrame
        trades_df = pd.DataFrame(trades_list)
        
        # Parse time - handle mixed timezone formats
        # Some times have timezone (-04:00 or -05:00), some don't
        # Strategy: parse all times, assume no-timezone times are already in ET
        parsed_times = []
        for time_str in trades_df['time']:
            try:
                # Try to parse with timezone
                dt = pd.to_datetime(time_str)
                if dt.tz is not None:
                    # Has timezone, convert to ET then remove tz
                    dt_et = dt.astimezone(ZoneInfo('America/New_York'))
                    dt_naive = dt_et.replace(tzinfo=None)
                else:
                    # No timezone, assume it's already in ET
                    dt_naive = dt
                parsed_times.append(dt_naive)
            except Exception as e:
                print(f"Warning: Failed to parse time '{time_str}': {e}")
                parsed_times.append(pd.NaT)
        
        trades_df['time'] = pd.Series(parsed_times)
        
        print(f"  Total trades: {len(trades_df)}")
        print(f"  Initial capital: ${initial_capital:,.2f}")
        if len(trades_df) > 0:
            print(f"  Date range: {trades_df['time'].iloc[0]} to {trades_df['time'].iloc[-1]}")
        
        return trades_df, initial_capital, report
        
    elif file_ext == '.csv':
        # Load CSV format
        print(f"Loading backtest data from CSV: {filename}...")
        trades_df = pd.read_csv(filename)
        trades_df['time'] = pd.to_datetime(trades_df['time'])
        
        print(f"  Total trades: {len(trades_df)}")
        print(f"  Date range: {trades_df['time'].iloc[0]} to {trades_df['time'].iloc[-1]}")
        
        return trades_df, INITIAL_CAPITAL, None
    
    else:
        print(f"Error: Unsupported file format: {file_ext}")
        return None, None, None

def load_benchmark_data(filename, symbol_name):
    """Load SPY or QQQ data from CSV file"""
    if not os.path.exists(filename):
        print(f"Warning: Cannot find {filename}")
        return None
    
    print(f"Loading {symbol_name} data from {filename}...")
    data = pd.read_csv(filename)
    
    # Parse Date column with UTC timezone handling
    data['Date'] = pd.to_datetime(data['Date'], utc=True)
    
    # Remove timezone info
    data['Date'] = data['Date'].dt.tz_localize(None)
    
    # Set Date as index
    data.set_index('Date', inplace=True)
    
    print(f"  Data range: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Total records: {len(data)}")
    
    return data['Close']

def calculate_equity_curve(trades_df, benchmark_prices, initial_capital):
    """
    Calculate daily equity curve by marking positions to market
    
    Args:
        trades_df: DataFrame with trade records (from JSON or CSV)
        benchmark_prices: Series with daily prices (used for mark-to-market)
        initial_capital: Initial account balance
        
    Returns:
        DataFrame with columns: Date, Equity
    """
    # Initialize tracking
    cash = initial_capital
    positions = {}  # {symbol: {'shares': int, 'total_cost': float}}
    
    # Sort trades by time
    trades_df = trades_df.sort_values('time').reset_index(drop=True)
    
    # Process trades and build equity curve
    equity_curve = []
    dates = []
    trade_idx = 0
    
    # Get date range
    start_date = trades_df['time'].iloc[0].date()
    end_date = trades_df['time'].iloc[-1].date()
    
    print(f"\nCalculating equity curve from {start_date} to {end_date}...")
    
    # Generate date range (trading days only - use benchmark dates + extend to cover all trades)
    trading_dates = benchmark_prices.index
    
    # Filter to date range and convert to list
    trading_dates = [d for d in trading_dates if start_date <= d.date() <= end_date]
    
    # Add a point at the very beginning with initial capital
    # Find the first trading date before or on start_date
    first_trading_date = None
    for d in benchmark_prices.index:
        if d.date() >= start_date:
            first_trading_date = d
            break
    
    if first_trading_date is None:
        first_trading_date = pd.Timestamp(start_date)
    
    # Prepend the initial date if it's not already there
    if len(trading_dates) == 0 or trading_dates[0].date() > start_date:
        trading_dates = [pd.Timestamp(start_date)] + trading_dates
    
    # If last trade date is beyond benchmark data, add it manually
    if end_date > benchmark_prices.index[-1].date():
        # Add the missing dates (convert to Timestamp for consistency)
        current = benchmark_prices.index[-1].date()
        while current < end_date:
            current = current + timedelta(days=1)
            # Only add trading days (Mon-Fri, simplified)
            if current.weekday() < 5:
                trading_dates.append(pd.Timestamp(current))
        
        print(f"  Extended date range to {end_date} to process all trades")
    
    for current_date in trading_dates:
        # Process all trades that occurred on or before this date (same day included)
        # Use date comparison to include all trades within the trading day
        current_date_only = current_date.date() if isinstance(current_date, pd.Timestamp) else current_date
        
        while trade_idx < len(trades_df):
            trade = trades_df.iloc[trade_idx]
            trade_time = trade['time']  # Already parsed and tz-naive
            
            # Compare dates only (include all trades on current_date)
            trade_date = trade_time.date() if isinstance(trade_time, pd.Timestamp) else trade_time
            
            if trade_date > current_date_only:
                break
            
            symbol = trade['symbol']
            shares = trade['shares']
            
            # Determine if BUY or SELL (handle both JSON and CSV formats)
            if 'type' in trade:
                # JSON format
                trade_type = trade['type']
                amount = trade['amount']
            else:
                # CSV format
                action = trade['action']
                trade_type = 'BUY' if action in ['BUY', 'ROTATION_BUY_BACK'] else 'SELL'
                amount = trade['net_value']
            
            # Update positions based on trade type
            if trade_type == 'BUY':
                # Buy action - decrease cash, increase position
                cash -= amount
                if symbol not in positions:
                    positions[symbol] = {'shares': 0, 'total_cost': 0}
                positions[symbol]['shares'] += shares
                positions[symbol]['total_cost'] += amount
                
            else:  # SELL
                # Sell action - increase cash, decrease position
                cash += amount
                if symbol in positions:
                    # Calculate average cost per share
                    avg_cost = positions[symbol]['total_cost'] / positions[symbol]['shares'] if positions[symbol]['shares'] > 0 else 0
                    sold_cost = avg_cost * shares
                    
                    positions[symbol]['shares'] -= shares
                    positions[symbol]['total_cost'] -= sold_cost
                    
                    # Remove position if fully closed
                    if positions[symbol]['shares'] <= 0:
                        del positions[symbol]
            
            trade_idx += 1
        
        # Calculate total equity (cash + positions market value)
        total_equity = cash
        
        # Add market value of all positions (using cost basis since we don't have all symbols' prices)
        for symbol, pos in positions.items():
            # Use cost basis for mark-to-market
            total_equity += pos['total_cost']
        
        equity_curve.append(total_equity)
        dates.append(current_date)
    
    # Create DataFrame
    equity_df = pd.DataFrame({
        'Date': dates,
        'Equity': equity_curve
    })
    
    # Debug: Print final state
    print(f"\n  Final cash: ${cash:,.2f}")
    print(f"  Final positions: {len(positions)}")
    if len(positions) > 0:
        total_position_cost = sum(pos['total_cost'] for pos in positions.values())
        print(f"  Total position cost: ${total_position_cost:,.2f}")
        for symbol, pos in positions.items():
            print(f"    {symbol}: {pos['shares']} shares, cost ${pos['total_cost']:,.2f}")
    
    return equity_df

def calculate_metrics(equity_df, initial_capital):
    """Calculate performance metrics"""
    
    # Basic metrics
    final_equity = equity_df['Equity'].iloc[-1]
    total_return = (final_equity - initial_capital) / initial_capital * 100
    
    # Max drawdown
    peak = equity_df['Equity'].iloc[0]
    max_drawdown = 0
    for equity in equity_df['Equity']:
        if equity > peak:
            peak = equity
        drawdown = (peak - equity) / peak * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    # Calculate daily returns
    daily_returns = equity_df['Equity'].pct_change().dropna()
    
    # Sharpe Ratio (annualized, assuming 252 trading days)
    if len(daily_returns) > 0 and daily_returns.std() > 0:
        sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * (252 ** 0.5)
    else:
        sharpe_ratio = 0
    
    # Sortino Ratio (annualized)
    negative_returns = daily_returns[daily_returns < 0]
    if len(negative_returns) > 0:
        downside_std = negative_returns.std()
        if downside_std > 0:
            sortino_ratio = (daily_returns.mean() / downside_std) * (252 ** 0.5)
        else:
            sortino_ratio = 0
    else:
        sortino_ratio = float('inf') if daily_returns.mean() > 0 else 0
    
    return {
        'final_equity': final_equity,
        'total_return': total_return,
        'max_drawdown': max_drawdown,
        'sharpe_ratio': sharpe_ratio,
        'sortino_ratio': sortino_ratio
    }

def calculate_benchmark_returns(benchmark_prices, equity_dates):
    """Calculate benchmark returns aligned with equity curve dates"""
    
    # Filter benchmark to same date range
    start_date = equity_dates.iloc[0]
    end_date = equity_dates.iloc[-1]
    
    # Get prices for the date range
    mask = (benchmark_prices.index >= start_date) & (benchmark_prices.index <= end_date)
    prices = benchmark_prices[mask]
    
    if len(prices) == 0:
        return pd.Series(), 0
    
    # Calculate returns
    initial_price = prices.iloc[0]
    returns = ((prices / initial_price - 1) * 100)  # Convert to percentage
    
    # Calculate final return
    final_return = returns.iloc[-1] if len(returns) > 0 else 0
    
    return returns, final_return

def calculate_yearly_returns(equity_df, spy_prices, qqq_prices, initial_capital):
    """Calculate yearly returns for strategy and benchmarks"""
    
    equity_df = equity_df.copy()
    equity_df['Year'] = equity_df['Date'].dt.year
    
    yearly_stats = []
    previous_end_equity = initial_capital
    
    for year in sorted(equity_df['Year'].unique()):
        year_data = equity_df[equity_df['Year'] == year]
        
        if len(year_data) == 0:
            continue
        
        # Get start and end dates for this year
        year_start = year_data['Date'].iloc[0]
        year_end = year_data['Date'].iloc[-1]
        
        # Get equity at start and end
        # Start equity is the previous year's end equity (or initial capital for first year)
        start_equity = previous_end_equity
        end_equity = year_data['Equity'].iloc[-1]
        
        # For the current year, get equity at the end
        previous_end_equity = end_equity
        
        # Calculate strategy return
        strategy_return = (end_equity - start_equity) / start_equity * 100
        
        # Get SPY return for the year
        spy_year = spy_prices[(spy_prices.index >= year_start) & (spy_prices.index <= year_end)]
        if len(spy_year) > 0:
            spy_return = (spy_year.iloc[-1] - spy_year.iloc[0]) / spy_year.iloc[0] * 100
        else:
            spy_return = 0
        
        # Get QQQ return for the year
        qqq_year = qqq_prices[(qqq_prices.index >= year_start) & (qqq_prices.index <= year_end)]
        if len(qqq_year) > 0:
            qqq_return = (qqq_year.iloc[-1] - qqq_year.iloc[0]) / qqq_year.iloc[0] * 100
        else:
            qqq_return = 0
        
        yearly_stats.append({
            'year': year,
            'start_equity': start_equity,
            'end_equity': end_equity,
            'strategy_return': strategy_return,
            'spy_return': spy_return,
            'qqq_return': qqq_return,
            'excess_vs_spy': strategy_return - spy_return,
            'excess_vs_qqq': strategy_return - qqq_return
        })
    
    return pd.DataFrame(yearly_stats)

def plot_equity_curve():
    """Main plotting function"""
    
    print("="*70)
    print("Account Equity Curve Analysis")
    print("="*70)
    print(f"Configuration:")
    print(f"  Backtest file: {BACKTEST_FILE}")
    print(f"  Output image: {OUTPUT_IMAGE}")
    print("="*70)
    
    # Load backtest data
    trades_df, initial_capital, report = load_backtest_data(BACKTEST_FILE)
    
    if trades_df is None:
        return
    
    if len(trades_df) == 0:
        print("Error: No trades found in backtest file")
        return
    
    print(f"  Using initial capital: ${initial_capital:,.2f}")
    
    # Load benchmark data
    spy_prices = load_benchmark_data(SPY_DATA_FILE, 'SPY')
    qqq_prices = load_benchmark_data(QQQ_DATA_FILE, 'QQQ')
    
    if spy_prices is None or qqq_prices is None:
        print("\nError: Cannot load benchmark data")
        return
    
    # Calculate equity curve (using QQQ prices for date reference)
    equity_df = calculate_equity_curve(trades_df, qqq_prices, initial_capital)
    
    print(f"\nEquity curve calculated:")
    print(f"  Initial: ${equity_df['Equity'].iloc[0]:,.2f}")
    print(f"  Final: ${equity_df['Equity'].iloc[-1]:,.2f}")
    print(f"  Min: ${equity_df['Equity'].min():,.2f}")
    print(f"  Max: ${equity_df['Equity'].max():,.2f}")
    
    # Calculate metrics
    metrics = calculate_metrics(equity_df, initial_capital)
    
    # Calculate benchmark returns
    spy_returns, spy_final_return = calculate_benchmark_returns(spy_prices, equity_df['Date'])
    qqq_returns, qqq_final_return = calculate_benchmark_returns(qqq_prices, equity_df['Date'])
    
    # Calculate yearly returns
    yearly_stats = calculate_yearly_returns(equity_df, spy_prices, qqq_prices, initial_capital)
    
    # Create plot
    fig, ax = plt.subplots(figsize=(14, 8))
    
    # Calculate strategy returns
    strategy_returns = ((equity_df['Equity'] / initial_capital - 1) * 100)
    
    # Plot returns
    ax.plot(equity_df['Date'], strategy_returns, 
            color='#FF6B6B', linewidth=2.5, label='Strategy Return')
    ax.plot(spy_returns.index, spy_returns.values, 
            color='#4ECDC4', linewidth=2.5, label='SPY Return')
    ax.plot(qqq_returns.index, qqq_returns.values, 
            color='#95E1D3', linewidth=2.5, label='QQQ Return')
    
    # Add zero line
    ax.axhline(y=0, color='black', linestyle='-', alpha=0.3, linewidth=1)
    
    # Format axes
    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('Return (%)', fontsize=12)
    
    # Determine title based on file name
    if 'v7' in BACKTEST_FILE.lower():
        title = 'V7 Strategy vs SPY vs QQQ - Returns Comparison (with MA Filter)\n'
    elif 'v6' in BACKTEST_FILE.lower():
        title = 'V6 Strategy vs SPY vs QQQ - Returns Comparison\n'
    else:
        title = 'Strategy vs SPY vs QQQ - Returns Comparison\n'
    
    ax.set_title(title, fontsize=14, pad=15)
    
    # Format y-axis as percentage
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:+.1f}%'))
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    fig.autofmt_xdate()
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
    
    # Legend
    ax.legend(loc='upper left', fontsize=11)
    
    # Statistics box
    stats_text = f'Initial Capital: ${initial_capital:,.0f}\n'
    stats_text += f'Final Equity: ${metrics["final_equity"]:,.0f}\n'
    stats_text += f'Strategy Return: {metrics["total_return"]:+.2f}%\n'
    stats_text += f'SPY Return: {spy_final_return:+.2f}%\n'
    stats_text += f'QQQ Return: {qqq_final_return:+.2f}%\n'
    stats_text += f'Excess vs SPY: {metrics["total_return"] - spy_final_return:+.2f}%\n'
    stats_text += f'Excess vs QQQ: {metrics["total_return"] - qqq_final_return:+.2f}%\n'
    stats_text += f'Max Drawdown: -{metrics["max_drawdown"]:.2f}%\n'
    stats_text += '─────────────────────────\n'
    stats_text += f'Sharpe Ratio: {metrics["sharpe_ratio"]:.2f}\n'
    if metrics["sortino_ratio"] == float('inf'):
        stats_text += 'Sortino Ratio: N/A'
    else:
        stats_text += f'Sortino Ratio: {metrics["sortino_ratio"]:.2f}'
    
    props = dict(boxstyle='round', facecolor='lightblue', alpha=0.8)
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', bbox=props, family='monospace')
    
    # Add final return annotations
    final_strategy_return = strategy_returns.iloc[-1]
    ax.text(equity_df['Date'].iloc[-1], final_strategy_return, 
            f'  {final_strategy_return:+.1f}%',
            verticalalignment='center', fontsize=10, color='#FF6B6B', weight='bold')
    
    if len(spy_returns) > 0:
        ax.text(spy_returns.index[-1], spy_returns.iloc[-1],
                f'  {spy_returns.iloc[-1]:+.1f}%',
                verticalalignment='center', fontsize=10, color='#4ECDC4', weight='bold')
    
    if len(qqq_returns) > 0:
        ax.text(qqq_returns.index[-1], qqq_returns.iloc[-1],
                f'  {qqq_returns.iloc[-1]:+.1f}%',
                verticalalignment='center', fontsize=10, color='#95E1D3', weight='bold')
    
    plt.tight_layout()
    
    # Save figure
    plt.savefig(OUTPUT_IMAGE, dpi=300, bbox_inches='tight')
    print(f"\nChart saved to: {OUTPUT_IMAGE}")
    
    # Print backtest report if available (from JSON)
    if report:
        print("\n" + "="*100)
        print("BACKTEST REPORT (from JSON)")
        print("="*100)
        for section, values in report.items():
            print(f"\n{section}")
            for key, value in values.items():
                print(f"  {key}: {value}")
    
    # Print performance summary
    print("\n" + "="*100)
    print("PERFORMANCE SUMMARY (from equity curve)")
    print("="*100)
    print(f"\nOverall Performance:")
    print(f"  Strategy Return:   {metrics['total_return']:>10.2f}%")
    print(f"  SPY Return:        {spy_final_return:>10.2f}%")
    print(f"  QQQ Return:        {qqq_final_return:>10.2f}%")
    print(f"  Excess vs SPY:     {metrics['total_return'] - spy_final_return:>10.2f}%")
    print(f"  Excess vs QQQ:     {metrics['total_return'] - qqq_final_return:>10.2f}%")
    
    print(f"\nRisk Metrics:")
    print(f"  Max Drawdown:      {metrics['max_drawdown']:>10.2f}%")
    print(f"  Sharpe Ratio:      {metrics['sharpe_ratio']:>10.2f}")
    if metrics['sortino_ratio'] == float('inf'):
        print(f"  Sortino Ratio:     {'N/A':>10}")
    else:
        print(f"  Sortino Ratio:     {metrics['sortino_ratio']:>10.2f}")
    
    # Print yearly returns
    print("\n" + "="*100)
    print("YEARLY RETURNS")
    print("="*100)
    print(f"{'Year':<6} {'Start Equity':<15} {'End Equity':<15} {'Strategy':<11} {'SPY':<11} {'QQQ':<11} {'vs SPY':<11} {'vs QQQ':<11}")
    print("-"*100)
    
    for _, row in yearly_stats.iterrows():
        print(f"{row['year']:<6} ${row['start_equity']:>13,.0f}  ${row['end_equity']:>13,.0f}  "
              f"{row['strategy_return']:>+9.2f}%  {row['spy_return']:>+9.2f}%  "
              f"{row['qqq_return']:>+9.2f}%  {row['excess_vs_spy']:>+9.2f}%  "
              f"{row['excess_vs_qqq']:>+9.2f}%")
    
    print("="*100)
    
    # Show plot
    plt.show()

def main():
    """Main function"""
    plot_equity_curve()

if __name__ == "__main__":
    main()
