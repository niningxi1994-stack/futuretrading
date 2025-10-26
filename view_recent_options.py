#!/usr/bin/env python3
"""查询最近入库的期权交易数据"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

# 数据库路径
db_path = Path(__file__).parent / 'op_trade_data' / 'trading.db'

def format_datetime(dt_str):
    """格式化日期时间"""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime('%m-%d %H:%M:%S')
    except:
        return dt_str

def view_recent_options(limit=20):
    """查看最近入库的期权数据"""
    
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 查询最近的期权信号
    cursor.execute(f'''
        SELECT 
            signal_id,
            symbol,
            option_type,
            side,
            premium,
            signal_time,
            processed,
            created_at
        FROM option_signals
        ORDER BY created_at DESC
        LIMIT {limit}
    ''')
    
    results = cursor.fetchall()
    
    if not results:
        print("❌ 没有找到期权数据")
        conn.close()
        return
    
    print(f"\n{'='*100}")
    print(f"最近入库的 {len(results)} 条期权交易数据")
    print(f"{'='*100}\n")
    
    for i, row in enumerate(results, 1):
        signal_id, symbol, option_type, side, premium, signal_time, processed, created_at = row
        
        # 格式化时间
        signal_time_fmt = format_datetime(signal_time)
        created_at_fmt = format_datetime(created_at)
        
        # 显示状态
        status = "✓ 已处理" if processed == 1 else "○ 未处理"
        
        print(f"[{i:2d}] {symbol}")
        print(f"     信号ID: {signal_id}")
        print(f"     期权类型: {option_type} | 方向: {side}")
        print(f"     权利金: ${premium:,.0f}")
        print(f"     信号时间: {signal_time_fmt}")
        print(f"     入库时间: {created_at_fmt}")
        print(f"     状态: {status}")
        print()
    
    # 统计信息
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN processed = 1 THEN 1 ELSE 0 END) as processed_count,
            SUM(CASE WHEN processed = 0 THEN 1 ELSE 0 END) as unprocessed_count
        FROM option_signals
    ''')
    
    total, processed_count, unprocessed_count = cursor.fetchone()
    
    print(f"{'='*100}")
    print(f"数据库统计:")
    print(f"  总记录数: {total}")
    print(f"  已处理: {processed_count}")
    print(f"  未处理: {unprocessed_count}")
    print(f"{'='*100}\n")
    
    conn.close()

def view_today_options():
    """查看今天的期权数据"""
    
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 获取今天的日期（美东时间）
    today = datetime.now().strftime('%Y-%m-%d')
    
    cursor.execute(f'''
        SELECT 
            symbol,
            premium,
            signal_time,
            processed
        FROM option_signals
        WHERE DATE(signal_time) = ?
        ORDER BY signal_time DESC
    ''', (today,))
    
    results = cursor.fetchall()
    
    if not results:
        print(f"\n❌ 今天 ({today}) 没有期权数据")
        conn.close()
        return
    
    print(f"\n{'='*100}")
    print(f"今天 ({today}) 的期权数据 - 共 {len(results)} 条")
    print(f"{'='*100}\n")
    
    for i, row in enumerate(results, 1):
        symbol, premium, signal_time, processed = row
        signal_time_fmt = format_datetime(signal_time)
        status = "✓" if processed == 1 else "○"
        
        print(f"{status} [{i:2d}] {symbol:8s} | 权利金: ${premium:>10,.0f} | 时间: {signal_time_fmt}")
    
    print()
    conn.close()

def view_by_symbol(symbol):
    """查看指定股票的期权数据"""
    
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            signal_id,
            option_type,
            side,
            premium,
            signal_time,
            processed,
            created_at
        FROM option_signals
        WHERE symbol = ?
        ORDER BY signal_time DESC
        LIMIT 10
    ''', (symbol,))
    
    results = cursor.fetchall()
    
    if not results:
        print(f"\n❌ 没有找到 {symbol} 的期权数据")
        conn.close()
        return
    
    print(f"\n{'='*100}")
    print(f"{symbol} 的最近 {len(results)} 条期权数据")
    print(f"{'='*100}\n")
    
    for i, row in enumerate(results, 1):
        signal_id, option_type, side, premium, signal_time, processed, created_at = row
        
        signal_time_fmt = format_datetime(signal_time)
        created_at_fmt = format_datetime(created_at)
        status = "✓ 已处理" if processed == 1 else "○ 未处理"
        
        print(f"[{i}] {signal_time_fmt}")
        print(f"    类型: {option_type} | 方向: {side} | 权利金: ${premium:,.0f}")
        print(f"    状态: {status}")
        print()
    
    conn.close()

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='查询最近入库的期权交易数据')
    parser.add_argument('-n', '--limit', type=int, default=20, help='显示记录数量（默认20）')
    parser.add_argument('-t', '--today', action='store_true', help='只显示今天的数据')
    parser.add_argument('-s', '--symbol', type=str, help='查询指定股票的数据')
    
    args = parser.parse_args()
    
    if args.symbol:
        view_by_symbol(args.symbol)
    elif args.today:
        view_today_options()
    else:
        view_recent_options(args.limit)

if __name__ == '__main__':
    main()

