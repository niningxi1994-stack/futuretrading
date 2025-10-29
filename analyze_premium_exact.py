import json
import pandas as pd
from datetime import datetime, timedelta
import pytz
import numpy as np

# Load CSV
csv_df = pd.read_csv('future_v_0_1/database/merged_strategy_v1_calls_bell_2023M3_2025M10.csv')
csv_df['datetime_cn_str'] = csv_df['date'] + ' ' + csv_df['time']

# Convert string values to numeric
def parse_numeric(s):
    if pd.isna(s) or s == '':
        return 0.0
    s = str(s).replace('$', '').replace(',', '').replace('K', '000').replace('M', '000000').strip()
    try:
        return float(s)
    except:
        return 0.0

csv_df['premium_numeric'] = csv_df['premium'].apply(parse_numeric)
csv_df['share_eqv_numeric'] = csv_df['share_eqv'].apply(parse_numeric)
csv_df['price_numeric'] = csv_df['price'].apply(parse_numeric)

csv_df = csv_df[['ticker', 'datetime_cn_str', 'premium_numeric', 'share_eqv_numeric', 'price_numeric']]
csv_df.set_index(['ticker', 'datetime_cn_str'], inplace=True)

# Load backtest
with open('backtest_v8_2.json', 'r') as f:
    v2 = json.load(f)

print('='*100)
print('Premium & Eqv_Value vs Return Analysis (Exact Match)')
print('='*100)

def convert_et_to_beijing(et_time_str):
    """Converts ET time string to Beijing time."""
    et_tz = pytz.timezone('America/New_York')
    cn_tz = pytz.timezone('Asia/Shanghai')
    
    # Parse as naive first
    naive_dt = datetime.strptime(et_time_str[:19], '%Y-%m-%d %H:%M:%S')
    et_dt = et_tz.localize(naive_dt)
    cn_dt = et_dt.astimezone(cn_tz)
    
    return cn_dt

# Extract trades
trades = []
for buy in [t for t in v2['trades'] if t['type'] == 'BUY']:
    sell = next((s for s in v2['trades'] if s['type'] == 'SELL' and s['symbol'] == buy['symbol'] and s.get('buy_time') == buy['time']), None)
    if sell and 'profit_rate' in sell:
        trades.append({
            'symbol': buy['symbol'],
            'buy_time_et': buy['time'],
            'profit_rate': sell['profit_rate']
        })

print(f'\nTotal BUY-SELL pairs: {len(trades)}')

# Match premium and eqv_value
matched = 0
premium_returns = []
eqv_value_returns = []

for trade in trades:
    symbol = trade['symbol']
    buy_time_et_str = trade['buy_time_et']
    
    # Convert to Beijing time and subtract 10 mins
    buy_time_et = convert_et_to_beijing(buy_time_et_str)
    original_signal_time_cn = buy_time_et - timedelta(minutes=10)
    original_signal_cn_str = original_signal_time_cn.strftime('%Y-%m-%d %H:%M:%S')
    
    key = (symbol, original_signal_cn_str)
    
    if key in csv_df.index:
        row = csv_df.loc[key]
        
        # Handle cases where multiple signals match
        if isinstance(row, pd.DataFrame):
            premium = row['premium_numeric'].mean()
            share_eqv = row['share_eqv_numeric'].mean()
            price = row['price_numeric'].mean()
        else:
            premium = row['premium_numeric']
            share_eqv = row['share_eqv_numeric']
            price = row['price_numeric']
            
        eqv_value = share_eqv * price
        
        premium_returns.append((premium, trade['profit_rate']))
        eqv_value_returns.append((eqv_value, trade['profit_rate']))
        matched += 1

print(f'Matched with premium/eqv_value: {matched} ({matched/len(trades)*100:.1f}%)')

# Analyze Premium
if premium_returns:
    premiums, returns = zip(*premium_returns)
    corr_p = np.corrcoef(premiums, returns)[0,1]
    
    print(f'\n{"="*50}')
    print('Premium Analysis')
    print("="*50)
    print(f'Correlation: {corr_p:.3f}')
    
    df_p = pd.DataFrame({'premium': premiums, 'return': returns})
    bins_p = pd.qcut(df_p['premium'], 3, labels=['Low', 'Medium', 'High'])
    grouped_p = df_p.groupby(bins_p)['return'].agg(['count', 'mean'])
    
    print(f"\n{'Level':<10} {'Count':<8} {'Avg Return':<12}")
    print('-'*40)
    for level, row in grouped_p.iterrows():
        print(f"{level:<10} {int(row['count']):<8} {row['mean']:>+7.2f}%")

# Analyze Eqv_Value
if eqv_value_returns:
    eqv_values, returns_e = zip(*eqv_value_returns)
    corr_e = np.corrcoef(eqv_values, returns_e)[0,1]
    
    print(f'\n{"="*50}')
    print('Eqv_Value (share_eqv * price) Analysis')
    print("="*50)
    print(f'Correlation: {corr_e:.3f}')
    
    df_e = pd.DataFrame({'eqv_value': eqv_values, 'return': returns_e})
    bins_e = pd.qcut(df_e['eqv_value'], 3, labels=['Low', 'Medium', 'High'], duplicates='drop')
    grouped_e = df_e.groupby(bins_e)['return'].agg(['count', 'mean'])
    
    print(f"\n{'Level':<10} {'Count':<8} {'Avg Return':<12}")
    print('-'*40)
    for level, row in grouped_e.iterrows():
        print(f"{level:<10} {int(row['count']):<8} {row['mean']:>+7.2f}%")

# ===== Additional Analysis: Share_Eqv (Pure) and DTE =====
# Re-extract trades with share_eqv and DTE
share_eqv_returns = []
dte_returns = []

# Load full CSV for DTE data
csv_full = pd.read_csv('future_v_0_1/database/merged_strategy_v1_calls_bell_2023M3_2025M10.csv')
csv_full['datetime_cn_str'] = csv_full['date'] + ' ' + csv_full['time']

for trade in trades:
    symbol = trade['symbol']
    buy_time_et_str = trade['buy_time_et']
    
    # Convert to Beijing time and subtract 10 mins
    buy_time_et = convert_et_to_beijing(buy_time_et_str)
    original_signal_time_cn = buy_time_et - timedelta(minutes=10)
    original_signal_cn_str = original_signal_time_cn.strftime('%Y-%m-%d %H:%M:%S')
    
    key = (symbol, original_signal_cn_str)
    
    if key in csv_df.index:
        row = csv_df.loc[key]
        
        # Extract share_eqv (pure)
        if isinstance(row, pd.DataFrame):
            share_eqv_val = row['share_eqv_numeric'].mean()
        else:
            share_eqv_val = row['share_eqv_numeric']
        
        share_eqv_returns.append((share_eqv_val, trade['profit_rate']))
    
    # Extract DTE
    matches = csv_full[(csv_full['ticker'] == symbol) & (csv_full['datetime_cn_str'] == original_signal_cn_str)]
    if not matches.empty:
        dte_str = matches.iloc[0]['dte']
        try:
            dte_val = float(str(dte_str).replace('+', ''))
            dte_returns.append((dte_val, trade['profit_rate']))
        except:
            pass

# Analyze Share_Eqv (pure)
if share_eqv_returns:
    share_eqvs, returns_s = zip(*share_eqv_returns)
    corr_s = np.corrcoef(share_eqvs, returns_s)[0,1]
    
    print(f'\n{"="*50}')
    print('Share_Eqv (Pure) Analysis')
    print("="*50)
    print(f'Correlation: {corr_s:.3f}')
    
    df_s = pd.DataFrame({'share_eqv': share_eqvs, 'return': returns_s})
    bins_s = pd.qcut(df_s['share_eqv'], 3, labels=['Low', 'Medium', 'High'], duplicates='drop')
    grouped_s = df_s.groupby(bins_s)['return'].agg(['count', 'mean'], observed=False)
    
    print(f"\n{'Level':<10} {'Count':<8} {'Avg Return':<12}")
    print('-'*40)
    for level, row in grouped_s.iterrows():
        print(f"{level:<10} {int(row['count']):<8} {row['mean']:>+7.2f}%")

# Analyze DTE
if dte_returns:
    dtes, returns_d = zip(*dte_returns)
    corr_d = np.corrcoef(dtes, returns_d)[0,1]
    
    print(f'\n{"="*50}')
    print('DTE (Days To Expiration) Analysis')
    print("="*50)
    print(f'Correlation: {corr_d:.3f}')
    print(f'Total matched DTE records: {len(dte_returns)}')
    
    df_d = pd.DataFrame({'dte': dtes, 'return': returns_d})
    bins_d = pd.qcut(df_d['dte'], 3, labels=['Short', 'Medium', 'Long'], duplicates='drop')
    grouped_d = df_d.groupby(bins_d)['return'].agg(['count', 'mean'], observed=False)
    
    print(f"\n{'Level':<10} {'Count':<8} {'Avg Return':<12}")
    print('-'*40)
    for level, row in grouped_d.iterrows():
        print(f"{level:<10} {int(row['count']):<8} {row['mean']:>+7.2f}%")

print(f'\n{"="*100}')
print('Improvement Suggestions:')
print("="*100)

if premium_returns:
    print(f'\nPremium Analysis:')
    print(f'  - 相关性: {corr_p:.3f} (负相关 = 高premium交易收益低)')
    
if eqv_value_returns:
    print(f'\nEqv_Value Analysis:')
    print(f'  - 相关性: {corr_e:.3f}')
