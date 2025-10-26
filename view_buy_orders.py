#!/usr/bin/env python3
"""查询买入订单历史数据"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime
import argparse

# 数据库路径
db_path = Path(__file__).parent / 'op_trade_data' / 'trading.db'

def format_datetime(dt_str):
    """格式化日期时间"""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return dt_str

def format_short_datetime(dt_str):
    """格式化为短日期时间"""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime('%m-%d %H:%M')
    except:
        return dt_str

def view_all_buy_orders():
    """查看所有买入订单"""
    
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # 查询所有买入订单
    cursor.execute('''
        SELECT 
            order_id,
            symbol,
            order_type,
            order_time,
            shares,
            price,
            status,
            filled_time,
            filled_price,
            filled_shares,
            signal_id,
            pos_ratio,
            reason
        FROM orders
        WHERE order_type = 'BUY'
        ORDER BY order_time DESC
    ''')
    
    results = cursor.fetchall()
    
    if not results:
        print("❌ 没有找到买入订单")
        conn.close()
        return
    
    print(f"\n{'='*120}")
    print(f"📊 买入订单历史 - 共 {len(results)} 条")
    print(f"{'='*120}\n")
    
    for i, row in enumerate(results, 1):
        (order_id, symbol, order_type, order_time, shares, price, status, 
         filled_time, filled_price, filled_shares, signal_id, pos_ratio, reason) = row
        
        order_time_fmt = format_datetime(order_time)
        filled_time_fmt = format_datetime(filled_time) if filled_time else 'N/A'
        
        print(f"[{i}] {symbol}")
        print(f"    订单ID: {order_id}")
        print(f"    下单时间: {order_time_fmt}")
        print(f"    计划: {shares}股 @ ${price:.2f} = ${shares * price:,.2f}")
        
        if status == 'FILLED':
            print(f"    成交: {filled_shares}股 @ ${filled_price:.2f} = ${filled_shares * filled_price:,.2f}")
            print(f"    成交时间: {filled_time_fmt}")
        else:
            print(f"    状态: {status}")
        
        if pos_ratio:
            print(f"    仓位比例: {pos_ratio:.2%}")
        
        if signal_id:
            print(f"    信号ID: {signal_id}")
        
        if reason:
            print(f"    原因: {reason}")
        
        print()
    
    # 统计信息
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'FILLED' THEN 1 ELSE 0 END) as filled_count,
            SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending_count,
            SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) as cancelled_count,
            SUM(CASE WHEN status = 'FILLED' THEN shares * filled_price ELSE 0 END) as total_filled_amount
        FROM orders
        WHERE order_type = 'BUY'
    ''')
    
    total, filled_count, pending_count, cancelled_count, total_filled_amount = cursor.fetchone()
    
    print(f"{'='*120}")
    print(f"统计信息:")
    print(f"  总订单数: {total}")
    print(f"  已成交: {filled_count}")
    print(f"  待成交: {pending_count}")
    print(f"  已取消: {cancelled_count}")
    if total_filled_amount:
        print(f"  累计成交金额: ${total_filled_amount:,.2f}")
    print(f"{'='*120}\n")
    
    conn.close()

def view_buy_orders_by_date(date_str):
    """查看指定日期的买入订单"""
    
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            order_id,
            symbol,
            order_time,
            shares,
            price,
            status,
            filled_price,
            filled_shares
        FROM orders
        WHERE order_type = 'BUY'
        AND DATE(order_time) = ?
        ORDER BY order_time
    ''', (date_str,))
    
    results = cursor.fetchall()
    
    if not results:
        print(f"\n❌ {date_str} 没有买入订单")
        conn.close()
        return
    
    print(f"\n{'='*120}")
    print(f"📊 {date_str} 的买入订单 - 共 {len(results)} 条")
    print(f"{'='*120}\n")
    
    for i, row in enumerate(results, 1):
        order_id, symbol, order_time, shares, price, status, filled_price, filled_shares = row
        
        order_time_fmt = format_short_datetime(order_time)
        
        if status == 'FILLED':
            filled_amt = filled_shares * filled_price
            status_str = f"✓ 成交 {filled_shares}股@${filled_price:.2f} (${filled_amt:,.0f})"
        else:
            status_str = f"○ {status}"
        
        print(f"  [{i}] {order_time_fmt} | {symbol:8s} | {shares}股@${price:.2f} | {status_str}")
    
    # 统计
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'FILLED' THEN shares * filled_price ELSE 0 END) as total_amount
        FROM orders
        WHERE order_type = 'BUY'
        AND DATE(order_time) = ?
    ''', (date_str,))
    
    total, total_amount = cursor.fetchone()
    
    print(f"\n  总计: {total} 条订单")
    if total_amount:
        print(f"  成交金额: ${total_amount:,.2f}")
    print()
    
    conn.close()

def view_buy_orders_by_symbol(symbol):
    """查看指定股票的买入订单"""
    
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            order_id,
            order_time,
            shares,
            price,
            status,
            filled_time,
            filled_price,
            filled_shares
        FROM orders
        WHERE order_type = 'BUY'
        AND symbol = ?
        ORDER BY order_time DESC
        LIMIT 20
    ''', (symbol,))
    
    results = cursor.fetchall()
    
    if not results:
        print(f"\n❌ 没有找到 {symbol} 的买入订单")
        conn.close()
        return
    
    print(f"\n{'='*120}")
    print(f"📊 {symbol} 的买入订单历史 - 最近 {len(results)} 条")
    print(f"{'='*120}\n")
    
    for i, row in enumerate(results, 1):
        order_id, order_time, shares, price, status, filled_time, filled_price, filled_shares = row
        
        order_time_fmt = format_datetime(order_time)
        filled_time_fmt = format_datetime(filled_time) if filled_time else 'N/A'
        
        print(f"[{i}] {order_time_fmt}")
        print(f"    订单ID: {order_id}")
        print(f"    计划: {shares}股 @ ${price:.2f}")
        
        if status == 'FILLED':
            print(f"    成交: {filled_shares}股 @ ${filled_price:.2f}")
            print(f"    成交时间: {filled_time_fmt}")
        else:
            print(f"    状态: {status}")
        
        print()
    
    conn.close()

def view_recent_buy_orders(limit=10):
    """查看最近的买入订单"""
    
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute(f'''
        SELECT 
            order_id,
            symbol,
            order_time,
            shares,
            price,
            status,
            filled_price,
            filled_shares
        FROM orders
        WHERE order_type = 'BUY'
        ORDER BY order_time DESC
        LIMIT {limit}
    ''')
    
    results = cursor.fetchall()
    
    if not results:
        print("❌ 没有找到买入订单")
        conn.close()
        return
    
    print(f"\n{'='*120}")
    print(f"📊 最近 {len(results)} 条买入订单")
    print(f"{'='*120}\n")
    
    for i, row in enumerate(results, 1):
        order_id, symbol, order_time, shares, price, status, filled_price, filled_shares = row
        
        order_time_fmt = format_datetime(order_time)
        
        if status == 'FILLED':
            filled_amt = filled_shares * filled_price
            print(f"  [{i}] {order_time_fmt} | {symbol:8s} | "
                  f"✓ 成交 {filled_shares}股@${filled_price:.2f} (${filled_amt:,.0f})")
        else:
            plan_amt = shares * price
            print(f"  [{i}] {order_time_fmt} | {symbol:8s} | "
                  f"○ {status} {shares}股@${price:.2f} (${plan_amt:,.0f})")
    
    print()
    conn.close()

def view_buy_summary():
    """查看买入订单摘要统计"""
    
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    print(f"\n{'='*120}")
    print(f"📊 买入订单统计摘要")
    print(f"{'='*120}\n")
    
    # 总体统计
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            COUNT(DISTINCT symbol) as unique_symbols,
            SUM(CASE WHEN status = 'FILLED' THEN 1 ELSE 0 END) as filled_count,
            SUM(CASE WHEN status = 'FILLED' THEN shares * filled_price ELSE 0 END) as total_filled_amount,
            AVG(CASE WHEN status = 'FILLED' THEN shares * filled_price END) as avg_filled_amount
        FROM orders
        WHERE order_type = 'BUY'
    ''')
    
    total, unique_symbols, filled_count, total_filled_amount, avg_filled_amount = cursor.fetchone()
    
    print("【总体统计】")
    print(f"  总订单数: {total}")
    print(f"  不同股票: {unique_symbols}")
    print(f"  成交订单: {filled_count}")
    print(f"  成交率: {filled_count/total*100:.1f}%" if total > 0 else "  成交率: 0%")
    if total_filled_amount:
        print(f"  累计成交金额: ${total_filled_amount:,.2f}")
        print(f"  平均成交金额: ${avg_filled_amount:,.2f}")
    print()
    
    # 按日期统计
    cursor.execute('''
        SELECT 
            DATE(order_time) as trade_date,
            COUNT(*) as count,
            SUM(CASE WHEN status = 'FILLED' THEN 1 ELSE 0 END) as filled_count,
            SUM(CASE WHEN status = 'FILLED' THEN shares * filled_price ELSE 0 END) as filled_amount
        FROM orders
        WHERE order_type = 'BUY'
        GROUP BY DATE(order_time)
        ORDER BY trade_date DESC
        LIMIT 10
    ''')
    
    date_stats = cursor.fetchall()
    
    if date_stats:
        print("【最近10天统计】")
        for trade_date, count, filled_count, filled_amount in date_stats:
            filled_amount_str = f"${filled_amount:,.0f}" if filled_amount else "$0"
            print(f"  {trade_date}: {count}单 (成交{filled_count}) - {filled_amount_str}")
        print()
    
    # 按股票统计
    cursor.execute('''
        SELECT 
            symbol,
            COUNT(*) as count,
            SUM(CASE WHEN status = 'FILLED' THEN shares * filled_price ELSE 0 END) as total_amount
        FROM orders
        WHERE order_type = 'BUY'
        GROUP BY symbol
        ORDER BY count DESC
        LIMIT 10
    ''')
    
    symbol_stats = cursor.fetchall()
    
    if symbol_stats:
        print("【买入最多的股票 TOP10】")
        for symbol, count, total_amount in symbol_stats:
            amount_str = f"${total_amount:,.0f}" if total_amount else "$0"
            print(f"  {symbol:8s}: {count}次 - {amount_str}")
        print()
    
    print(f"{'='*120}\n")
    
    conn.close()

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='查询买入订单历史数据')
    parser.add_argument('-a', '--all', action='store_true', help='显示所有买入订单')
    parser.add_argument('-d', '--date', type=str, help='查询指定日期的订单 (格式: YYYY-MM-DD)')
    parser.add_argument('-s', '--symbol', type=str, help='查询指定股票的订单')
    parser.add_argument('-n', '--recent', type=int, default=10, help='显示最近N条订单（默认10）')
    parser.add_argument('--summary', action='store_true', help='显示统计摘要')
    
    args = parser.parse_args()
    
    if args.all:
        view_all_buy_orders()
    elif args.date:
        view_buy_orders_by_date(args.date)
    elif args.symbol:
        view_buy_orders_by_symbol(args.symbol)
    elif args.summary:
        view_buy_summary()
    else:
        # 默认显示最近的订单
        view_recent_buy_orders(args.recent)

if __name__ == '__main__':
    main()

