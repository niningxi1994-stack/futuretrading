"""
综合查询工具：查询数据库中的持仓、买入决策、买入订单、卖出决策、卖出订单
"""

import sys
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent / 'future_v_0_1'))

from database.models import DatabaseManager


def format_time(time_str: str) -> str:
    """格式化时间字符串"""
    if not time_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(time_str)
        return dt.strftime('%m-%d %H:%M:%S')
    except:
        return time_str[:16] if len(time_str) > 16 else time_str


def query_positions(db_path: str, symbol: Optional[str] = None, status: Optional[str] = None):
    """
    查询持仓信息
    
    Args:
        db_path: 数据库路径
        symbol: 股票代码（可选）
        status: 状态过滤 OPEN/CLOSED（可选）
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = '''
        SELECT 
            symbol,
            shares,
            entry_time,
            entry_price,
            entry_order_id,
            target_profit_price,
            stop_loss_price,
            current_price,
            unrealized_pnl,
            unrealized_pnl_ratio,
            status,
            created_at
        FROM positions
        WHERE 1=1
    '''
    params = []
    
    if symbol:
        query += ' AND symbol = ?'
        params.append(symbol)
    
    if status:
        query += ' AND status = ?'
        params.append(status)
    
    query += ' ORDER BY entry_time DESC LIMIT 50'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    print(f"\n{'='*140}")
    print(f"📊 持仓信息")
    print(f"{'='*140}")
    
    if not rows:
        print("❌ 未找到持仓记录")
        conn.close()
        return
    
    print(f"\n找到 {len(rows)} 条持仓记录\n")
    print(f"{'股票':<8} {'数量':<8} {'买入价':<10} {'当前状态':<8} {'买入时间':<18} "
          f"{'止盈价':<10} {'止损价':<10} {'盈亏':<15} {'盈亏率':<10}")
    print(f"{'-'*140}")
    
    for row in rows:
        symbol, shares, entry_time, entry_price, entry_order_id, \
        target_profit, stop_loss, current_price, unrealized_pnl, \
        unrealized_pnl_ratio, status, created_at = row
        
        status_icon = "🟢" if status == "OPEN" else "⚪"
        entry_time_str = format_time(entry_time)
        
        if unrealized_pnl is not None:
            pnl_str = f"${unrealized_pnl:+,.2f}"
            ratio_str = f"{unrealized_pnl_ratio:+.2%}" if unrealized_pnl_ratio else "N/A"
        else:
            pnl_str = "N/A"
            ratio_str = "N/A"
        
        print(f"{symbol:<8} {shares:<8} ${entry_price:<9.2f} {status_icon}{status:<7} {entry_time_str:<18} "
              f"${target_profit:<9.2f} ${stop_loss:<9.2f} {pnl_str:<15} {ratio_str:<10}")
        
        # 显示当前价格
        if current_price and status == "OPEN":
            print(f"  └─ 当前价格: ${current_price:.2f}")
    
    print()
    conn.close()


def query_orders(db_path: str, order_type: Optional[str] = None, symbol: Optional[str] = None, 
                 status: Optional[str] = None, days: int = 7):
    """
    查询订单信息
    
    Args:
        db_path: 数据库路径
        order_type: 订单类型 BUY/SELL（可选）
        symbol: 股票代码（可选）
        status: 状态过滤 PENDING/FILLED/CANCELLED（可选）
        days: 查询最近多少天
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    et_now = datetime.now(ZoneInfo('America/New_York'))
    start_time = (et_now - timedelta(days=days)).isoformat()
    
    query = '''
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
            pnl_amount,
            pnl_ratio,
            reason,
            pos_ratio
        FROM orders
        WHERE order_time >= ?
    '''
    params = [start_time]
    
    if order_type:
        query += ' AND order_type = ?'
        params.append(order_type)
    
    if symbol:
        query += ' AND symbol = ?'
        params.append(symbol)
    
    if status:
        query += ' AND status = ?'
        params.append(status)
    
    query += ' ORDER BY order_time DESC LIMIT 100'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    title = "订单信息"
    if order_type:
        title = f"{'买入' if order_type == 'BUY' else '卖出'}订单"
    
    print(f"\n{'='*140}")
    print(f"📋 {title}")
    print(f"{'='*140}")
    
    if not rows:
        print("❌ 未找到订单记录")
        conn.close()
        return
    
    print(f"\n找到 {len(rows)} 条订单记录\n")
    
    # 分别统计买入和卖出
    buy_orders = [r for r in rows if r[2] == 'BUY']
    sell_orders = [r for r in rows if r[2] == 'SELL']
    
    print(f"📊 统计: 买入 {len(buy_orders)} 笔 | 卖出 {len(sell_orders)} 笔")
    print()
    
    print(f"{'类型':<6} {'股票':<8} {'数量':<8} {'价格':<10} {'状态':<10} "
          f"{'订单时间':<18} {'盈亏':<15} {'原因':<20}")
    print(f"{'-'*140}")
    
    for row in rows:
        order_id, symbol, order_type, order_time, shares, price, status, \
        filled_time, filled_price, filled_shares, pnl_amount, pnl_ratio, reason, pos_ratio = row
        
        type_icon = "🔵" if order_type == "BUY" else "🔴"
        status_icon = {
            'PENDING': '⏳',
            'FILLED': '✅',
            'CANCELLED': '❌',
            'REJECTED': '⛔'
        }.get(status, '❓')
        
        order_time_str = format_time(order_time)
        price_str = f"${price:.2f}" if price else "市价"
        
        # 盈亏信息
        if pnl_amount is not None:
            pnl_str = f"${pnl_amount:+,.2f}"
            if pnl_ratio:
                pnl_str += f" ({pnl_ratio:+.1%})"
        else:
            pnl_str = "N/A"
        
        reason_str = reason if reason else "-"
        if reason == 'stop_loss':
            reason_str = "🛑 止损"
        elif reason == 'take_profit':
            reason_str = "💰 止盈"
        elif reason == 'holding_days_exceeded':
            reason_str = "⏰ 到期"
        
        print(f"{type_icon}{order_type:<5} {symbol:<8} {shares:<8} {price_str:<10} "
              f"{status_icon}{status:<9} {order_time_str:<18} {pnl_str:<15} {reason_str:<20}")
        
        # 显示成交信息
        if filled_time:
            filled_str = f"  └─ 成交: {format_time(filled_time)}"
            if filled_price:
                filled_str += f" @${filled_price:.2f}"
            if filled_shares:
                filled_str += f" {filled_shares}股"
            print(filled_str)
    
    print()
    conn.close()


def query_signals(db_path: str, symbol: Optional[str] = None, days: int = 7, 
                  processed: Optional[bool] = None):
    """
    查询期权信号（买入决策）
    
    Args:
        db_path: 数据库路径
        symbol: 股票代码（可选）
        days: 查询最近多少天
        processed: 是否已处理（可选）
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    et_now = datetime.now(ZoneInfo('America/New_York'))
    start_time = (et_now - timedelta(days=days)).isoformat()
    
    query = '''
        SELECT 
            signal_id,
            symbol,
            option_type,
            side,
            premium,
            stock_price,
            signal_time,
            processed,
            generated_order,
            order_id,
            filter_reason
        FROM option_signals
        WHERE signal_time >= ?
    '''
    params = [start_time]
    
    if symbol:
        query += ' AND symbol = ?'
        params.append(symbol)
    
    if processed is not None:
        query += ' AND processed = ?'
        params.append(1 if processed else 0)
    
    query += ' ORDER BY signal_time DESC LIMIT 100'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    print(f"\n{'='*140}")
    print(f"📡 期权信号（买入决策）")
    print(f"{'='*140}")
    
    if not rows:
        print("❌ 未找到信号记录")
        conn.close()
        return
    
    print(f"\n找到 {len(rows)} 条信号记录\n")
    
    # 统计
    total = len(rows)
    generated_orders = sum(1 for r in rows if r[8])  # generated_order
    filtered = sum(1 for r in rows if r[7] and not r[8])  # processed but not generated
    
    print(f"📊 统计: 总信号 {total} | 生成订单 {generated_orders} | 已过滤 {filtered}")
    print()
    
    print(f"{'股票':<8} {'期权类型':<6} {'方向':<6} {'权利金':<12} {'股票价格':<12} "
          f"{'信号时间':<18} {'处理结果':<25}")
    print(f"{'-'*140}")
    
    for row in rows:
        signal_id, symbol, option_type, side, premium, stock_price, signal_time, \
        processed, generated_order, order_id, filter_reason = row
        
        premium_str = f"${premium:,.0f}" if premium else "N/A"
        stock_price_str = f"${stock_price:.2f}" if stock_price else "N/A"
        signal_time_str = format_time(signal_time)
        
        # 处理结果
        if generated_order:
            result = f"✅ 已下单 [{order_id[:15]}...]" if order_id else "✅ 已下单"
        elif processed:
            result = f"❌ 已过滤: {filter_reason}" if filter_reason else "❌ 已过滤"
        else:
            result = "⏳ 待处理"
        
        print(f"{symbol:<8} {option_type:<6} {side:<6} {premium_str:<12} {stock_price_str:<12} "
              f"{signal_time_str:<18} {result:<25}")
    
    print()
    conn.close()


def query_summary(db_path: str, days: int = 7):
    """
    查询交易概况
    
    Args:
        db_path: 数据库路径
        days: 统计最近多少天
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    et_now = datetime.now(ZoneInfo('America/New_York'))
    start_time = (et_now - timedelta(days=days)).isoformat()
    
    print(f"\n{'='*80}")
    print(f"📈 交易概况（最近{days}天）")
    print(f"{'='*80}\n")
    
    # 1. 期权信号统计
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN generated_order = 1 THEN 1 ELSE 0 END) as orders,
            SUM(CASE WHEN processed = 1 AND generated_order = 0 THEN 1 ELSE 0 END) as filtered
        FROM option_signals
        WHERE signal_time >= ?
    ''', (start_time,))
    signal_stats = cursor.fetchone()
    
    print(f"📡 期权信号:")
    print(f"   总信号数:    {signal_stats[0] or 0:>6}")
    print(f"   生成订单:    {signal_stats[1] or 0:>6}")
    print(f"   已过滤:      {signal_stats[2] or 0:>6}")
    if signal_stats[0] and signal_stats[0] > 0:
        print(f"   下单率:      {(signal_stats[1] or 0)/signal_stats[0]:>6.1%}")
    print()
    
    # 2. 订单统计
    cursor.execute('''
        SELECT 
            order_type,
            COUNT(*) as count,
            SUM(CASE WHEN status = 'FILLED' THEN 1 ELSE 0 END) as filled,
            SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) as pending
        FROM orders
        WHERE order_time >= ?
        GROUP BY order_type
    ''', (start_time,))
    order_stats = cursor.fetchall()
    
    print(f"📋 订单统计:")
    for order_type, count, filled, pending in order_stats:
        type_name = "买入" if order_type == "BUY" else "卖出"
        print(f"   {type_name}订单:    {count:>6} (成交:{filled:>3}, 挂单:{pending:>3})")
    print()
    
    # 3. 持仓统计
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) as open,
            SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) as closed
        FROM positions
    ''')
    pos_stats = cursor.fetchone()
    
    print(f"📊 持仓统计:")
    print(f"   总持仓记录:  {pos_stats[0] or 0:>6}")
    print(f"   当前持仓:    {pos_stats[1] or 0:>6}")
    print(f"   已平仓:      {pos_stats[2] or 0:>6}")
    print()
    
    # 4. 盈亏统计（从卖出订单中统计）
    cursor.execute('''
        SELECT 
            COUNT(*) as count,
            SUM(pnl_amount) as total_pnl,
            AVG(pnl_ratio) as avg_pnl_ratio,
            SUM(CASE WHEN pnl_amount > 0 THEN 1 ELSE 0 END) as win_count,
            SUM(CASE WHEN pnl_amount < 0 THEN 1 ELSE 0 END) as loss_count
        FROM orders
        WHERE order_type = 'SELL' AND pnl_amount IS NOT NULL
    ''')
    pnl_stats = cursor.fetchone()
    
    if pnl_stats[0] and pnl_stats[0] > 0:
        print(f"💰 盈亏统计:")
        print(f"   已平仓数:    {pnl_stats[0]:>6}")
        print(f"   总盈亏:      ${pnl_stats[1] or 0:>+,.2f}")
        print(f"   平均盈亏率:  {pnl_stats[2] or 0:>+6.1%}")
        print(f"   盈利次数:    {pnl_stats[3] or 0:>6}")
        print(f"   亏损次数:    {pnl_stats[4] or 0:>6}")
        if pnl_stats[0] > 0:
            win_rate = (pnl_stats[3] or 0) / pnl_stats[0]
            print(f"   胜率:        {win_rate:>6.1%}")
        print()
    
    # 5. 热门股票
    cursor.execute('''
        SELECT symbol, COUNT(*) as count
        FROM orders
        WHERE order_time >= ? AND order_type = 'BUY'
        GROUP BY symbol
        ORDER BY count DESC
        LIMIT 5
    ''', (start_time,))
    top_symbols = cursor.fetchall()
    
    if top_symbols:
        print(f"🔥 热门股票:")
        for symbol, count in top_symbols:
            print(f"   {symbol:<10} {count:>3}笔")
        print()
    
    print(f"{'='*80}\n")
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='综合查询工具：查询持仓、订单、信号等交易数据',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例用法:
  # 查询所有数据概况
  python query_trading_data.py --summary
  
  # 查询持仓
  python query_trading_data.py --positions
  python query_trading_data.py --positions -s AAPL
  python query_trading_data.py --positions --status OPEN
  
  # 查询订单
  python query_trading_data.py --orders
  python query_trading_data.py --orders --type BUY
  python query_trading_data.py --orders --type SELL -s AAPL
  
  # 查询期权信号（买入决策）
  python query_trading_data.py --signals
  python query_trading_data.py --signals -s NKLR
  python query_trading_data.py --signals --generated-only
  
  # 查询所有信息
  python query_trading_data.py --all
        '''
    )
    
    parser.add_argument(
        '-d', '--db',
        type=str,
        default='/Users/niningxi/Desktop/future/op_trade_data/trading.db',
        help='数据库路径'
    )
    
    parser.add_argument(
        '-s', '--symbol',
        type=str,
        help='股票代码（可选）'
    )
    
    parser.add_argument(
        '-t', '--days',
        type=int,
        default=7,
        help='查询最近多少天（默认7天）'
    )
    
    # 查询类型
    parser.add_argument('--summary', action='store_true', help='显示交易概况')
    parser.add_argument('--positions', action='store_true', help='查询持仓')
    parser.add_argument('--orders', action='store_true', help='查询订单')
    parser.add_argument('--signals', action='store_true', help='查询期权信号（买入决策）')
    parser.add_argument('--all', action='store_true', help='查询所有信息')
    
    # 持仓过滤
    parser.add_argument('--status', type=str, choices=['OPEN', 'CLOSED'], 
                        help='持仓状态过滤')
    
    # 订单过滤
    parser.add_argument('--type', type=str, choices=['BUY', 'SELL'],
                        help='订单类型过滤')
    parser.add_argument('--order-status', type=str, 
                        choices=['PENDING', 'FILLED', 'CANCELLED'],
                        help='订单状态过滤')
    
    # 信号过滤
    parser.add_argument('--generated-only', action='store_true',
                        help='只显示生成订单的信号')
    parser.add_argument('--filtered-only', action='store_true',
                        help='只显示已过滤的信号')
    
    args = parser.parse_args()
    
    # 检查数据库是否存在
    if not Path(args.db).exists():
        print(f"❌ 数据库不存在: {args.db}")
        return
    
    # 如果没有指定任何查询，默认显示概况
    if not any([args.summary, args.positions, args.orders, args.signals, args.all]):
        args.summary = True
    
    # 执行查询
    if args.all:
        query_summary(args.db, days=args.days)
        query_signals(args.db, symbol=args.symbol, days=args.days)
        query_orders(args.db, symbol=args.symbol, days=args.days)
        query_positions(args.db, symbol=args.symbol)
    else:
        if args.summary:
            query_summary(args.db, days=args.days)
        
        if args.signals:
            processed = None
            if args.generated_only:
                processed = True
            elif args.filtered_only:
                processed = True
            query_signals(args.db, symbol=args.symbol, days=args.days, processed=processed)
        
        if args.orders:
            query_orders(args.db, order_type=args.type, symbol=args.symbol, 
                        status=args.order_status, days=args.days)
        
        if args.positions:
            query_positions(args.db, symbol=args.symbol, status=args.status)


if __name__ == '__main__':
    main()

