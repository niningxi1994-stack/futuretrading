#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Plot account equity curve from Futu historical orders
"""

from futu import *
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from collections import defaultdict
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration from environment variables
US_SIM_ACC_ID = int(os.getenv('US_SIM_ACC_ID'))
UNLOCK_PWD = os.getenv('UNLOCK_PWD')
INITIAL_CAPITAL = int(os.getenv('INITIAL_CAPITAL', '1000000'))

def get_historical_orders(days=90):
    """Get historical orders from Futu"""
    trd_ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host='127.0.0.1', 
        port=11111, 
        security_firm=SecurityFirm.FUTUSECURITIES
    )
    
    trd_ctx.unlock_trade(UNLOCK_PWD)
    
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    print(f"Getting orders from {start_date} to {end_date}...")
    
    ret, orders = trd_ctx.history_order_list_query(
        trd_env=TrdEnv.SIMULATE,
        acc_id=US_SIM_ACC_ID,
        start=start_date,
        end=end_date
    )
    
    # Get current account info
    ret2, acc_info = trd_ctx.accinfo_query(
        trd_env=TrdEnv.SIMULATE,
        acc_id=US_SIM_ACC_ID
    )
    current_assets = float(acc_info.iloc[0]['total_assets']) if ret2 == RET_OK else INITIAL_CAPITAL
    current_cash = float(acc_info.iloc[0]['cash']) if ret2 == RET_OK else INITIAL_CAPITAL
    
    # Get current positions
    ret3, positions = trd_ctx.position_list_query(
        trd_env=TrdEnv.SIMULATE,
        acc_id=US_SIM_ACC_ID
    )
    
    current_positions = {}
    if ret3 == RET_OK and not positions.empty:
        for _, pos in positions.iterrows():
            current_positions[pos['code']] = {
                'qty': float(pos['qty']),
                'cost_price': float(pos['cost_price']),
                'current_price': float(pos['nominal_price'])
            }
    
    trd_ctx.close()
    
    print(f"Found {len(orders)} orders")
    print(f"Current total assets: ${current_assets:,.2f}")
    print(f"Current cash: ${current_cash:,.2f}")
    print(f"Current positions: {len(current_positions)}")
    
    
    return orders, current_assets, current_cash, current_positions

def calculate_daily_equity(orders, current_assets, current_cash, current_positions):
    """Calculate daily equity from orders"""
    # Filter filled orders
    filled_orders = orders[orders['order_status'].isin(['FILLED_ALL', 'FILLED_PART'])].copy()
    
    if filled_orders.empty:
        return pd.DataFrame()
    
    # Parse dates
    filled_orders['datetime'] = pd.to_datetime(filled_orders['create_time'])
    filled_orders['date'] = filled_orders['datetime'].dt.date
    filled_orders = filled_orders.sort_values('datetime')
    
    all_dates = sorted(filled_orders['date'].unique())
    
    # Start from initial capital
    daily_data = []
    cash = INITIAL_CAPITAL
    positions = {}
    
    # Add starting point
    if all_dates:
        first_date = all_dates[0]
        day_before = pd.to_datetime(first_date) - timedelta(days=1)
        daily_data.append({
            'date': day_before,
            'total_assets': INITIAL_CAPITAL,
            'cash': INITIAL_CAPITAL,
            'position_value': 0
        })
    
    # Track total cash flows and fees for debugging
    total_buy_amount = 0
    total_sell_amount = 0
    total_commission_fee = 0  # 佣金
    total_platform_fee = 0    # 平台费
    total_settlement_fee = 0  # 交收费
    total_sec_fee = 0         # SEC费
    total_taf_fee = 0         # TAF费
    
    # Now simulate forward
    for i, date in enumerate(all_dates):
        day_orders = filled_orders[filled_orders['date'] == date]
        
        for _, order in day_orders.iterrows():
            code = order['code']
            dealt_qty = float(order['dealt_qty'])
            dealt_price = float(order['dealt_avg_price'])
            side = order['trd_side']
            
            # Calculate commission based on Futu's fee structure
            trade_amount = dealt_qty * dealt_price
            
            if side == 'BUY':
                # Buy fees breakdown (no rounding to match exact calculation)
                commission_fee = max(0.99, dealt_qty * 0.0049)
                platform_fee = max(1.00, dealt_qty * 0.005)
                settlement_fee = dealt_qty * 0.003
                
                commission = commission_fee + platform_fee + settlement_fee
                
                amount = dealt_qty * dealt_price
                cash -= amount
                cash -= commission  # Deduct commission
                total_buy_amount += amount
                total_commission_fee += commission_fee
                total_platform_fee += platform_fee
                total_settlement_fee += settlement_fee
                if code not in positions:
                    positions[code] = {'qty': 0, 'cost_price': 0}
                old_qty = positions[code]['qty']
                new_qty = old_qty + dealt_qty
                if new_qty > 0:
                    positions[code]['cost_price'] = (old_qty * positions[code]['cost_price'] + dealt_qty * dealt_price) / new_qty
                positions[code]['qty'] = new_qty
            elif side == 'SELL':
                # Sell fees breakdown (no rounding to match exact calculation)
                commission_fee = max(0.99, dealt_qty * 0.0049)
                platform_fee = max(1.00, dealt_qty * 0.005)
                settlement_fee = dealt_qty * 0.003
                sec_fee = max(0.01, trade_amount * 0.000008)  # Corrected: 0.000008 not 0.0000278
                taf_fee = min(max(dealt_qty * 0.000166, 0.01), 8.30)
                
                commission = commission_fee + platform_fee + settlement_fee + sec_fee + taf_fee
                
                amount = dealt_qty * dealt_price
                cash += amount
                cash -= commission  # Deduct commission
                total_sell_amount += amount
                total_commission_fee += commission_fee
                total_platform_fee += platform_fee
                total_settlement_fee += settlement_fee
                total_sec_fee += sec_fee
                total_taf_fee += taf_fee
                if code not in positions:
                    positions[code] = {'qty': 0, 'cost_price': 0}
                positions[code]['qty'] -= dealt_qty
        
        # Calculate position value
        # For last day, use current market prices; otherwise use cost price
        is_last_day = (i == len(all_dates) - 1)
        position_value = 0
        
        if is_last_day and current_positions:
            # Use actual current market prices for last day
            for code, pos in positions.items():
                if pos['qty'] > 0 and code in current_positions:
                    position_value += pos['qty'] * current_positions[code]['current_price']
        else:
            # Use cost price as approximation for historical days
            position_value = sum(pos['qty'] * pos['cost_price'] for pos in positions.values() if pos['qty'] > 0)
        
        total_assets = cash + position_value
        
        daily_data.append({
            'date': pd.to_datetime(date),
            'total_assets': total_assets,
            'cash': cash,
            'position_value': position_value
        })
    
    df = pd.DataFrame(daily_data)
    df = df.sort_values('date')
    
    # Validation: Compare simulated vs actual current assets
    if not df.empty:
        simulated_assets = df['total_assets'].iloc[-1]
        simulated_cash = df['cash'].iloc[-1]
        difference = simulated_assets - current_assets
        difference_pct = (difference / current_assets) * 100
        
        print("\n" + "="*60)
        print("Validation Check")
        print("="*60)
        print(f"Simulated Current Assets: ${simulated_assets:,.2f}")
        print(f"Actual Current Assets:    ${current_assets:,.2f}")
        print(f"Difference:               ${difference:,.2f} ({difference_pct:+.4f}%)")
        print(f"\nSimulated Cash:           ${simulated_cash:,.2f}")
        print(f"Actual Cash:              ${current_cash:,.2f}")
        print(f"Cash Difference:          ${simulated_cash - current_cash:,.2f}")
        
        print(f"\nFee Breakdown:")
        total_fees = total_commission_fee + total_platform_fee + total_settlement_fee + total_sec_fee + total_taf_fee
        print(f"  Commission:    ${total_commission_fee:,.2f}")
        print(f"  Platform Fee:  ${total_platform_fee:,.2f}")
        print(f"  Settlement:    ${total_settlement_fee:,.2f}")
        print(f"  SEC Fee:       ${total_sec_fee:,.2f}")
        print(f"  TAF Fee:       ${total_taf_fee:,.2f}")
        print(f"  Total Fees:    ${total_fees:,.2f}")
        
        # Compare positions
        print(f"\nPosition Comparison:")
        for code, sim_pos in positions.items():
            if sim_pos['qty'] > 0:
                actual_qty = current_positions.get(code, {}).get('qty', 0)
                print(f"  {code}: Simulated={sim_pos['qty']:.0f}, Actual={actual_qty:.0f}, Diff={sim_pos['qty']-actual_qty:.0f}")
        
        print()
        if abs(difference_pct) < 0.01:
            print("✅ Validation PASSED - Excellent match!")
        elif abs(difference_pct) < 0.2:
            print("✅ Validation PASSED - Acceptable difference (< 0.2%)")
            print("   Note: Small discrepancies may be due to system rounding or internal calculations")
        else:
            print("❌ Validation FAILED - Large difference detected")
        print("="*60 + "\n")
    
    return df

def plot_equity_curve(df):
    """Plot equity curve"""
    # Use first day as starting point
    starting_assets = df['total_assets'].iloc[0]
    
    # Calculate metrics
    df['return_pct'] = ((df['total_assets'] / starting_assets) - 1) * 100
    df['cummax'] = df['total_assets'].cummax()
    df['drawdown_pct'] = ((df['total_assets'] - df['cummax']) / df['cummax']) * 100
    
    # Create plots
    fig, axes = plt.subplots(3, 1, figsize=(14, 10))
    fig.suptitle('Account Equity Curve', fontsize=16, fontweight='bold')
    
    # Plot 1: Total Assets
    ax1 = axes[0]
    ax1.plot(df['date'], df['total_assets'], 'b-', linewidth=2, marker='o', markersize=4, label='Total Assets')
    ax1.axhline(y=starting_assets, color='gray', linestyle='--', alpha=0.5, label=f'Starting Assets')
    ax1.fill_between(df['date'], starting_assets, df['total_assets'], 
                      where=(df['total_assets'] >= starting_assets), 
                      color='green', alpha=0.2)
    ax1.fill_between(df['date'], starting_assets, df['total_assets'], 
                      where=(df['total_assets'] < starting_assets), 
                      color='red', alpha=0.2)
    ax1.set_ylabel('Total Assets ($)', fontsize=11, fontweight='bold')
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
    
    last_value = df['total_assets'].iloc[-1]
    last_date = df['date'].iloc[-1]
    ax1.annotate(f'${last_value:,.0f}', 
                xy=(last_date, last_value),
                xytext=(10, 0), textcoords='offset points',
                fontsize=10, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.7))
    
    # Plot 2: Cumulative Return
    ax2 = axes[1]
    colors = ['green' if x >= 0 else 'red' for x in df['return_pct']]
    ax2.bar(df['date'], df['return_pct'], color=colors, alpha=0.6, width=0.8)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.8)
    ax2.set_ylabel('Cumulative Return (%)', fontsize=11, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')
    
    final_return = df['return_pct'].iloc[-1]
    ax2.annotate(f'{final_return:+.2f}%', 
                xy=(last_date, final_return),
                xytext=(10, 0), textcoords='offset points',
                fontsize=10, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.7))
    
    # Plot 3: Drawdown
    ax3 = axes[2]
    ax3.fill_between(df['date'], 0, df['drawdown_pct'], color='red', alpha=0.3)
    ax3.plot(df['date'], df['drawdown_pct'], 'r-', linewidth=1.5, marker='o', markersize=3)
    ax3.set_ylabel('Drawdown (%)', fontsize=11, fontweight='bold')
    ax3.set_xlabel('Date', fontsize=11, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    
    max_dd = df['drawdown_pct'].min()
    max_dd_date = df.loc[df['drawdown_pct'].idxmin(), 'date']
    ax3.annotate(f'Max DD: {max_dd:.2f}%', 
                xy=(max_dd_date, max_dd),
                xytext=(10, -10), textcoords='offset points',
                fontsize=9,
                bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.7),
                arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
    
    # Format x-axis
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
    
    # Print stats (use actual last value from df which is the real current assets)
    actual_last_value = df['total_assets'].iloc[-1]
    actual_pnl = actual_last_value - starting_assets
    actual_return = (actual_pnl / starting_assets) * 100
    
    print("="*60)
    print("Account Statistics")
    print("="*60)
    print(f"Trading Days: {len(df)}")
    print(f"Starting Assets: ${starting_assets:,.2f}")
    print(f"Current Assets: ${actual_last_value:,.2f}")
    print(f"Total P&L: ${actual_pnl:,.2f}")
    print(f"Total Return: {actual_return:+.2f}%")
    print(f"Max Drawdown: {max_dd:.2f}%")
    print("="*60)
    
    plt.tight_layout()
    plt.savefig('account_equity_curve.png', dpi=300, bbox_inches='tight')
    print("Chart saved to: account_equity_curve.png")
    plt.clf()

def main():
    days = 90
    orders, current_assets, current_cash, current_positions = get_historical_orders(days=days)
    df = calculate_daily_equity(orders, current_assets, current_cash, current_positions)
    
    if df.empty:
        print("No data to plot")
        return
    
    print(f"Calculated equity for {len(df)} trading days\n")
    plot_equity_curve(df)

if __name__ == "__main__":
    main()
