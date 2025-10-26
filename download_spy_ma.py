#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 Polygon API 下载 SPY/QQQ 数据并计算 MA 指标

计算 MA20、MA60，并保存到 database 目录
支持下载 SPY 或 QQQ 数据
"""

import os
import pandas as pd
import requests
import pytz
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Load API key
load_dotenv(Path(__file__).parent / '.env')

def download_with_ma(symbol='SPY', start_date='2023-01-01', end_date=None, output_dir='future_v_0_1/database'):
    """
    使用 Polygon API 下载数据并计算 MA 指标
    
    Args:
        symbol: 股票代码 ('SPY' 或 'QQQ')
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)，默认为今天
        output_dir: 输出目录
        
    Returns:
        DataFrame with MA data
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    historical_file = output_dir / f'{symbol.lower()}_historical_data.csv'
    ma_file = output_dir / f'{symbol.lower()}_ma_data.csv'
    
    print(f"下载 {symbol} 数据: {start_date} 到 {end_date}")
    
    # 提前90天确保 MA60 有足够数据
    download_start = (pd.to_datetime(start_date) - pd.Timedelta(days=90)).strftime('%Y-%m-%d')
    print(f"实际起始日期: {download_start} (为 MA60 预留数据)")
    
    # 从 Polygon API 获取日线数据
    api_key = os.getenv('POLYGON_API_KEY')
    if not api_key:
        print("❌ POLYGON_API_KEY not found in .env")
        return None
    
    url = (f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day"
           f"/{download_start}/{end_date}"
           f"?adjusted=true&sort=asc&limit=50000&apiKey={api_key}")
    
    print("从 Polygon API 获取数据...")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get('resultsCount', 0) == 0:
            print("❌ 无数据返回")
            return None
        
        results = data['results']
        print(f"✓ 获取 {len(results)} 条日线数据")
        
        # 转换为 DataFrame
        records = []
        et_tz = pytz.timezone('America/New_York')
        
        for item in results:
            # Unix timestamp (milliseconds) to datetime
            timestamp = datetime.fromtimestamp(item['t'] / 1000, tz=pytz.UTC)
            timestamp = timestamp.astimezone(et_tz)
            
            records.append({
                'Date': timestamp,
                'Open': item['o'],
                'High': item['h'],
                'Low': item['l'],
                'Close': item['c'],
                'Volume': item['v'],
                'Dividends': 0.0,
                'Stock Splits': 0.0,
                'Capital Gains': 0.0,
            })
        
        df = pd.DataFrame(records)
        df.set_index('Date', inplace=True)
        
        # 去除时区信息（统一为 tz-naive，避免读取时出错）
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        
        # 保存历史数据（raw data）
        df.to_csv(historical_file)
        print(f"✓ 历史数据已保存: {historical_file}")
        
        # 计算 MA 指标
        print("计算 MA 指标...")
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        df['bullish_alignment'] = (df['MA20'] > df['MA60'])
        
        # 删除不完整数据（前60行）
        df_clean = df.dropna()
        print(f"✓ 有效数据: {len(df_clean)} 条")
        
        # 保存 MA 数据
        df_clean.to_csv(ma_file)
        print(f"✓ MA 数据已保存: {ma_file}")
        
        # 统计信息
        total_days = len(df_clean)
        bullish_days = df_clean['bullish_alignment'].sum()
        bullish_ratio = bullish_days / total_days * 100 if total_days > 0 else 0
        
        print(f"\n📊 统计:")
        print(f"  总交易日: {total_days}")
        print(f"  多头排列: {bullish_days} ({bullish_ratio:.1f}%)")
        print(f"  空头排列: {total_days - bullish_days} ({100-bullish_ratio:.1f}%)")
        
        print(f"\n最近 5 个交易日:")
        print(df_clean[['Close', 'MA20', 'MA60', 'bullish_alignment']].tail())
        
        return df_clean
        
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def check_today_alignment(ma_file='future_v_0_1/database/spy_ma_data.csv'):
    """
    检查最新交易日的多头排列状态
    
    Args:
        ma_file: MA数据文件路径
    """
    if not Path(ma_file).exists():
        print(f"❌ 文件不存在: {ma_file}")
        return None
    
    data = pd.read_csv(ma_file, index_col=0, parse_dates=True)
    
    if len(data) == 0:
        print("❌ 数据文件为空")
        return None
    
    # 获取最新一天的数据
    latest = data.iloc[-1]
    latest_date = data.index[-1]
    
    is_bullish = latest['bullish_alignment']
    
    print(f"\n📅 最新交易日: {latest_date.strftime('%Y-%m-%d')}")
    print(f"  收盘价: ${latest['Close']:.2f}")
    print(f"  MA20:   ${latest['MA20']:.2f}")
    print(f"  MA60:   ${latest['MA60']:.2f}")
    print(f"  多头排列: {'✅ 是 (MA20 > MA60)' if is_bullish else '❌ 否 (MA20 ≤ MA60)'}")
    
    if is_bullish:
        diff = latest['MA20'] - latest['MA60']
        print(f"  MA20 - MA60 = ${diff:.2f} (多头)")
    else:
        diff = latest['MA20'] - latest['MA60']
        print(f"  MA20 - MA60 = ${diff:.2f} (空头)")
    
    return is_bullish


def main():
    """主函数"""
    print("="*70)
    print("Polygon API - MA 指标下载工具")
    print("="*70)
    
    output_dir = 'future_v_0_1/database'
    
    # 下载 QQQ 数据
    print("\n1. 下载 QQQ 数据")
    print("-"*70)
    qqq_data = download_with_ma(
        symbol='QQQ',
        start_date='2023-01-01',
        end_date=None,
        output_dir=output_dir
    )
    
    if qqq_data is not None:
        print("\n" + "="*70)
        check_today_alignment(f'{output_dir}/qqq_ma_data.csv')
        print("="*70)
    
    # 下载 SPY 数据
    print("\n2. 下载 SPY 数据")
    print("-"*70)
    spy_data = download_with_ma(
        symbol='SPY',
        start_date='2023-01-01',
        end_date=None,
        output_dir=output_dir
    )
    
    if spy_data is not None:
        print("\n" + "="*70)
        check_today_alignment(f'{output_dir}/spy_ma_data.csv')
        print("="*70)


if __name__ == '__main__':
    main()

