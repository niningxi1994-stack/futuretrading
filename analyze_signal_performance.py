import json
import pandas as pd
from datetime import datetime, timedelta
import pytz

def convert_beijing_to_eastern(date_str, time_str):
    """Convert Beijing time to Eastern time"""
    beijing_tz = pytz.timezone('Asia/Shanghai')
    eastern_tz = pytz.timezone('America/New_York')
    
    # Parse Beijing time
    beijing_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
    beijing_time = beijing_tz.localize(beijing_time)
    
    # Convert to Eastern
    eastern_time = beijing_time.astimezone(eastern_tz)
    return eastern_time

def calculate_dte_from_trade_time(trade_time_str, expiry_str):
    """Calculate DTE from JSON trade time and expiry"""
    # Extract date from trade time (remove timezone)
    if trade_time_str.count('-') >= 3:
        trade_time_str = trade_time_str[:trade_time_str.rfind('-')]
    elif '+' in trade_time_str:
        trade_time_str = trade_time_str[:trade_time_str.rfind('+')]
    
    trade_date = datetime.strptime(trade_time_str.split()[0], "%Y-%m-%d")
    expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d")
    dte = (expiry_date - trade_date).days
    return dte

def calculate_otm_rate(spot, strike, option_type='call'):
    """Calculate OTM rate"""
    if option_type.lower() == 'call':
        otm_rate = (strike - spot) / spot * 100
    else:
        otm_rate = (spot - strike) / spot * 100
    return otm_rate

# Load JSON file
print("Loading backtest results...")
with open('backtest_v8_test.json', 'r') as f:
    backtest_data = json.load(f)

# Load CSV file
print("Loading signal data...")
csv_df = pd.read_csv('future_v_0_1/database/merged_strategy_v1_calls_bell_2023M3_2025M9.csv')

# Extract buy trades from JSON
buy_trades = []
for trade in backtest_data['trades']:
    if trade['type'] == 'BUY':
        buy_trades.append(trade)

print(f"\nTotal buy trades: {len(buy_trades)}")
print(f"Total signals in CSV: {len(csv_df)}")

# Match trades with signals
matched_trades = []

for trade in buy_trades:
    symbol = trade['symbol']
    strike = trade['strike']
    expiry = trade['expiry']
    trade_time = trade['time']
    
    # Find matching signal in CSV
    # Match by ticker, strike, and expiry
    matches = csv_df[
        (csv_df['ticker'] == symbol) & 
        (csv_df['strike'] == strike) & 
        (csv_df['expiry'] == expiry)
    ]
    
    if len(matches) > 0:
        # If multiple matches, take the first one
        signal = matches.iloc[0]
        
        # Calculate DTE from JSON trade time (actual buy time) and expiry
        dte = calculate_dte_from_trade_time(trade_time, expiry)
        
        # Get premium from signal
        try:
            premium_str = str(signal['premium']).replace('$', '').replace('K', '000').replace('M', '000000').replace(',', '')
            premium = float(premium_str)
        except:
            premium = None
        
        # price column is the stock price at signal time
        try:
            stock_price_str = str(signal['price']).replace('$', '').replace(',', '')
            stock_price = float(stock_price_str)
        except:
            stock_price = None
        
        # Calculate OTM rate using stock price and strike
        otm_rate = calculate_otm_rate(stock_price, strike) if stock_price else None
        
        # Find corresponding SELL trade
        sell_trade = None
        profit = None
        profit_rate = None
        
        for i, t in enumerate(backtest_data['trades']):
            if (t['type'] == 'SELL' and 
                t['symbol'] == symbol and 
                t.get('buy_time') == trade_time):
                sell_trade = t
                profit = t.get('profit')
                profit_rate = t.get('profit_rate')
                break
        
        matched_trades.append({
            'symbol': symbol,
            'trade_time': trade_time,
            'strike': strike,
            'expiry': expiry,
            'dte': dte,
            'premium': premium,
            'stock_price': stock_price,
            'otm_rate': otm_rate,
            'buy_price': trade['price'],
            'buy_amount': trade['amount'],
            'profit': profit,
            'profit_rate': profit_rate,
            'sell_reason': sell_trade.get('reason') if sell_trade else 'holding',
            'iv': signal.get('iv', None),
            'size': signal.get('size', None),
        })

print(f"\nMatched trades: {len(matched_trades)}")

# Convert to DataFrame
df = pd.DataFrame(matched_trades)

# Filter out trades still holding
df_closed = df[df['profit'].notna()].copy()

print(f"Closed trades: {len(df_closed)}")

# === Analysis by different dimensions ===

print("\n" + "="*80)
print("SIGNAL PERFORMANCE ANALYSIS")
print("="*80)

# Overall performance
print(f"\n### Overall Performance ###")
print(f"Total closed trades: {len(df_closed)}")
print(f"Winning trades: {len(df_closed[df_closed['profit'] > 0])}")
print(f"Losing trades: {len(df_closed[df_closed['profit'] < 0])}")
print(f"Win rate: {len(df_closed[df_closed['profit'] > 0]) / len(df_closed) * 100:.2f}%")
print(f"Average profit rate: {df_closed['profit_rate'].mean():.2f}%")
print(f"Average profit (winners): {df_closed[df_closed['profit'] > 0]['profit_rate'].mean():.2f}%")
print(f"Average loss (losers): {df_closed[df_closed['profit'] < 0]['profit_rate'].mean():.2f}%")

# 1. Analysis by DTE (Days to Expiry)
print(f"\n### Analysis by DTE (Days to Expiry) ###")
dte_bins = [0, 7, 14, 30, 60, 90, 180, 365, 10000]
dte_labels = ['0-7d', '8-14d', '15-30d', '31-60d', '61-90d', '91-180d', '181-365d', '>365d']
df_closed['dte_range'] = pd.cut(df_closed['dte'], bins=dte_bins, labels=dte_labels, right=True)

dte_analysis = df_closed.groupby('dte_range').agg({
    'profit': ['count', 'sum'],
    'profit_rate': ['mean', 'median']
}).round(2)

dte_win_rate = df_closed.groupby('dte_range').apply(
    lambda x: (x['profit'] > 0).sum() / len(x) * 100
).round(2)

print(dte_analysis)
print("\nWin Rate by DTE:")
print(dte_win_rate)

# 2. Analysis by OTM Rate
print(f"\n### Analysis by OTM Rate ###")
df_closed_with_otm = df_closed[df_closed['otm_rate'].notna()].copy()
otm_bins = [-100, 0, 5, 10, 15, 20, 30, 100]
otm_labels = ['ITM', '0-5%', '5-10%', '10-15%', '15-20%', '20-30%', '>30%']
df_closed_with_otm['otm_range'] = pd.cut(df_closed_with_otm['otm_rate'], bins=otm_bins, labels=otm_labels, right=True)

otm_analysis = df_closed_with_otm.groupby('otm_range').agg({
    'profit': ['count', 'sum'],
    'profit_rate': ['mean', 'median']
}).round(2)

otm_win_rate = df_closed_with_otm.groupby('otm_range').apply(
    lambda x: (x['profit'] > 0).sum() / len(x) * 100
).round(2)

print(otm_analysis)
print("\nWin Rate by OTM Rate:")
print(otm_win_rate)

# 3. Analysis by Premium
print(f"\n### Analysis by Premium ###")
df_closed_with_premium = df_closed[df_closed['premium'].notna()].copy()
premium_bins = [0, 50000, 100000, 200000, 500000, 1000000, 10000000]
premium_labels = ['<50K', '50K-100K', '100K-200K', '200K-500K', '500K-1M', '>1M']
df_closed_with_premium['premium_range'] = pd.cut(df_closed_with_premium['premium'], bins=premium_bins, labels=premium_labels, right=True)

premium_analysis = df_closed_with_premium.groupby('premium_range').agg({
    'profit': ['count', 'sum'],
    'profit_rate': ['mean', 'median']
}).round(2)

premium_win_rate = df_closed_with_premium.groupby('premium_range').apply(
    lambda x: (x['profit'] > 0).sum() / len(x) * 100
).round(2)

print(premium_analysis)
print("\nWin Rate by Premium:")
print(premium_win_rate)

# 4. Analysis by Trade Time (hour of day)
print(f"\n### Analysis by Trade Hour (Eastern Time) ###")
def extract_hour(time_str):
    """Extract hour from time string, handling timezone info"""
    try:
        # Format: "2023-03-10 15:11:30-05:00" or "2023-03-10 15:11:30-04:00"
        # Split by last '-' or '+' to remove timezone
        if time_str.count('-') >= 3:  # Has timezone like -05:00
            time_str = time_str[:time_str.rfind('-')]
        elif '+' in time_str:
            time_str = time_str[:time_str.rfind('+')]
        
        dt = datetime.strptime(time_str.strip(), "%Y-%m-%d %H:%M:%S")
        return dt.hour
    except Exception as e:
        return None

df_closed['hour'] = df_closed['trade_time'].apply(extract_hour)

# Check hour extraction
# print(f"\nDEBUG: Sample trade_time values:")
# print(df_closed['trade_time'].head(10).tolist())
# print(f"\nDEBUG: Hour values sample:")
# print(df_closed['hour'].value_counts().head(10))
# print(f"Non-null hours: {df_closed['hour'].notna().sum()}")

# Filter out None values
df_closed_with_hour = df_closed[df_closed['hour'].notna()].copy()

# Adjust hour bins to match actual trading hours (9:30-16:00 Eastern)
hour_bins = [0, 9, 10, 12, 14, 16, 24]
hour_labels = ['Pre-9:30', '9:30-10:00', '10:00-12:00', '12:00-14:00', '14:00-16:00', 'After-16:00']
df_closed_with_hour['hour_range'] = pd.cut(df_closed_with_hour['hour'], bins=hour_bins, labels=hour_labels, right=False)

hour_analysis = df_closed_with_hour.groupby('hour_range').agg({
    'profit': ['count', 'sum'],
    'profit_rate': ['mean', 'median']
}).round(2)

hour_win_rate = df_closed_with_hour.groupby('hour_range').apply(
    lambda x: (x['profit'] > 0).sum() / len(x) * 100
).round(2)

print(hour_analysis)
print("\nWin Rate by Hour:")
print(hour_win_rate)

# 5. Analysis by Exit Reason
print(f"\n### Analysis by Exit Reason ###")
reason_analysis = df_closed.groupby('sell_reason').agg({
    'profit': ['count', 'sum'],
    'profit_rate': ['mean', 'median']
}).round(2)

reason_win_rate = df_closed.groupby('sell_reason').apply(
    lambda x: (x['profit'] > 0).sum() / len(x) * 100
).round(2)

print(reason_analysis)
print("\nWin Rate by Exit Reason:")
print(reason_win_rate)

# 6. Top performing characteristics
print(f"\n### Best Performing Signal Characteristics ###")
winners = df_closed[df_closed['profit_rate'] > 15].copy()
print(f"Number of trades with >15% profit: {len(winners)}")
if len(winners) > 0:
    print(f"\nAverage DTE for big winners: {winners['dte'].mean():.0f} days")
    if winners['otm_rate'].notna().any():
        print(f"Average OTM rate for big winners: {winners['otm_rate'].mean():.2f}%")
    print(f"Most common DTE range:")
    print(winners['dte_range'].value_counts().head())
    
    # Calculate OTM range for winners if data available
    winners_with_otm = winners[winners['otm_rate'].notna()].copy()
    if len(winners_with_otm) > 0:
        winners_with_otm['otm_range'] = pd.cut(winners_with_otm['otm_rate'], bins=otm_bins, labels=otm_labels, right=True)
        print(f"\nMost common OTM range:")
        print(winners_with_otm['otm_range'].value_counts().head())

# 7. Worst performing characteristics
print(f"\n### Worst Performing Signal Characteristics ###")
losers = df_closed[df_closed['profit_rate'] < -5].copy()
print(f"Number of trades with <-5% loss: {len(losers)}")
if len(losers) > 0:
    print(f"\nAverage DTE for losers: {losers['dte'].mean():.0f} days")
    if losers['otm_rate'].notna().any():
        print(f"Average OTM rate for losers: {losers['otm_rate'].mean():.2f}%")
    print(f"Most common DTE range:")
    print(losers['dte_range'].value_counts().head())
    
    # Calculate OTM range for losers if data available
    losers_with_otm = losers[losers['otm_rate'].notna()].copy()
    if len(losers_with_otm) > 0:
        losers_with_otm['otm_range'] = pd.cut(losers_with_otm['otm_rate'], bins=otm_bins, labels=otm_labels, right=True)
        print(f"\nMost common OTM range:")
        print(losers_with_otm['otm_range'].value_counts().head())

# Save detailed results
df_closed.to_csv('signal_analysis_details.csv', index=False)
print(f"\n\nDetailed analysis saved to: signal_analysis_details.csv")

# Summary recommendations
print("\n" + "="*80)
print("RECOMMENDATIONS")
print("="*80)

# Best DTE range
try:
    best_dte = dte_analysis[('profit_rate', 'mean')].idxmax()
    best_dte_return = dte_analysis.loc[best_dte, ('profit_rate', 'mean')]
    print(f"\n1. Best DTE Range: {best_dte} (Avg Return: {best_dte_return:.2f}%)")
except:
    print(f"\n1. Best DTE Range: Unable to determine")

# Best OTM range
try:
    if not otm_analysis.empty and otm_analysis[('profit_rate', 'mean')].notna().any():
        best_otm = otm_analysis[('profit_rate', 'mean')].idxmax()
        best_otm_return = otm_analysis.loc[best_otm, ('profit_rate', 'mean')]
        print(f"2. Best OTM Range: {best_otm} (Avg Return: {best_otm_return:.2f}%)")
    else:
        print(f"2. Best OTM Range: No data available")
except:
    print(f"2. Best OTM Range: Unable to determine")

# Best premium range
try:
    if not premium_analysis.empty and premium_analysis[('profit_rate', 'mean')].notna().any():
        best_premium = premium_analysis[('profit_rate', 'mean')].idxmax()
        best_premium_return = premium_analysis.loc[best_premium, ('profit_rate', 'mean')]
        print(f"3. Best Premium Range: {best_premium} (Avg Return: {best_premium_return:.2f}%)")
    else:
        print(f"3. Best Premium Range: No data available")
except:
    print(f"3. Best Premium Range: Unable to determine")

# Best hour
try:
    if not hour_analysis.empty and hour_analysis[('profit_rate', 'mean')].notna().any():
        best_hour = hour_analysis[('profit_rate', 'mean')].idxmax()
        best_hour_return = hour_analysis.loc[best_hour, ('profit_rate', 'mean')]
        print(f"4. Best Trading Hour: {best_hour} (Avg Return: {best_hour_return:.2f}%)")
    else:
        print(f"4. Best Trading Hour: No hour data available")
except:
    print(f"4. Best Trading Hour: Unable to determine")

