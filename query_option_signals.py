"""
查询数据库中的期权信号，包括股票价格
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent / 'future_v_0_1'))

from database.models import DatabaseManager


def query_signals(db_path: str, symbol: str = None, days: int = 7, limit: int = 50):
    """
    查询期权信号
    
    Args:
        db_path: 数据库路径
        symbol: 股票代码（可选）
        days: 查询最近多少天
        limit: 返回数量限制
    """
    db = DatabaseManager(db_path)
    
    # 计算开始日期
    et_now = datetime.now(ZoneInfo('America/New_York'))
    start_date = (et_now - timedelta(days=days)).isoformat()
    
    print(f"🔍 查询期权信号")
    print(f"📂 数据库: {db_path}")
    if symbol:
        print(f"📊 股票代码: {symbol}")
    print(f"📅 时间范围: 最近{days}天")
    print(f"📈 返回数量: 最多{limit}条\n")
    
    # 查询信号
    signals = db.get_option_signals(
        symbol=symbol,
        start_date=start_date,
        limit=limit
    )
    
    if not signals:
        print("❌ 未找到任何期权信号")
        return
    
    print(f"✅ 找到 {len(signals)} 条期权信号\n")
    print(f"{'='*120}")
    print(f"{'序号':<6} {'股票代码':<10} {'期权类型':<8} {'方向':<6} {'权利金':<12} "
          f"{'股票价格':<12} {'信号时间':<20} {'处理状态':<10}")
    print(f"{'='*120}")
    
    for idx, signal in enumerate(signals, 1):
        symbol_code = signal['symbol']
        option_type = signal['option_type']
        side = signal['side']
        premium = signal['premium']
        stock_price = signal.get('stock_price')
        signal_time = signal['signal_time']
        
        # 处理状态
        if signal['generated_order']:
            status = '✅ 已下单'
        elif signal['processed']:
            status = '❌ 已过滤'
        else:
            status = '⏳ 待处理'
        
        # 格式化时间（只显示日期和时间）
        try:
            dt = datetime.fromisoformat(signal_time)
            time_str = dt.strftime('%m-%d %H:%M:%S')
        except:
            time_str = signal_time[:16]
        
        # 格式化价格
        premium_str = f"${premium:,.0f}" if premium else "N/A"
        stock_price_str = f"${stock_price:.2f}" if stock_price else "N/A"
        
        print(f"{idx:<6} {symbol_code:<10} {option_type:<8} {side:<6} {premium_str:<12} "
              f"{stock_price_str:<12} {time_str:<20} {status:<10}")
        
        # 显示过滤原因
        if signal.get('filter_reason'):
            print(f"       过滤原因: {signal['filter_reason']}")
    
    print(f"{'='*120}\n")


def query_stats(db_path: str, days: int = 7):
    """
    查询期权信号统计
    
    Args:
        db_path: 数据库路径
        days: 统计最近多少天
    """
    db = DatabaseManager(db_path)
    
    print(f"📊 期权信号统计（最近{days}天）\n")
    
    stats = db.get_option_signal_stats(days=days)
    
    print(f"{'='*80}")
    print(f"总信号数:      {stats['total_signals']:>8}")
    print(f"已处理信号数:  {stats['processed_signals']:>8}")
    print(f"生成订单数:    {stats['orders_generated']:>8}")
    
    if stats['total_signals'] > 0:
        process_rate = stats['processed_signals'] / stats['total_signals'] * 100
        order_rate = stats['orders_generated'] / stats['total_signals'] * 100
        print(f"处理率:        {process_rate:>7.1f}%")
        print(f"下单率:        {order_rate:>7.1f}%")
    
    print(f"{'='*80}\n")
    
    if stats['top_symbols']:
        print(f"📈 热门股票 TOP {len(stats['top_symbols'])}\n")
        print(f"{'股票代码':<15} {'信号数量':<10}")
        print(f"{'-'*25}")
        for item in stats['top_symbols']:
            print(f"{item['symbol']:<15} {item['count']:<10}")
        print()


def query_specific_signal(db_path: str, symbol: str, signal_time: str):
    """
    查询特定信号的详细信息
    
    Args:
        db_path: 数据库路径
        symbol: 股票代码
        signal_time: 信号时间（格式：YYYY-MM-DD HH:MM:SS）
    """
    db = DatabaseManager(db_path)
    
    print(f"🔍 查询特定信号: {symbol} @ {signal_time}\n")
    
    # 查询信号
    signals = db.get_option_signals(symbol=symbol, limit=1000)
    
    # 筛选匹配的信号
    matched = []
    for signal in signals:
        if signal_time in signal['signal_time']:
            matched.append(signal)
    
    if not matched:
        print(f"❌ 未找到匹配的信号")
        return
    
    print(f"✅ 找到 {len(matched)} 条匹配的信号\n")
    
    for idx, signal in enumerate(matched, 1):
        print(f"{'='*80}")
        print(f"【信号 {idx}】")
        print(f"{'='*80}")
        print(f"信号ID:        {signal['signal_id']}")
        print(f"股票代码:      {signal['symbol']}")
        print(f"期权类型:      {signal['option_type']}")
        print(f"合约代码:      {signal['contract']}")
        print(f"方向:          {signal['side']}")
        print(f"权利金:        ${signal['premium']:,.0f}" if signal['premium'] else "N/A")
        print(f"股票价格:      ${signal.get('stock_price'):.2f}" if signal.get('stock_price') else "N/A")
        print(f"信号时间:      {signal['signal_time']}")
        print(f"已处理:        {'是' if signal['processed'] else '否'}")
        print(f"生成订单:      {'是' if signal['generated_order'] else '否'}")
        
        if signal.get('order_id'):
            print(f"订单ID:        {signal['order_id']}")
        
        if signal.get('filter_reason'):
            print(f"过滤原因:      {signal['filter_reason']}")
        
        print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='查询数据库中的期权信号')
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
    parser.add_argument(
        '-l', '--limit',
        type=int,
        default=50,
        help='返回数量限制（默认50）'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='显示统计信息'
    )
    parser.add_argument(
        '--time',
        type=str,
        help='查询特定时间的信号（需要配合 -s）'
    )
    
    args = parser.parse_args()
    
    if args.stats:
        query_stats(args.db, days=args.days)
    elif args.time and args.symbol:
        query_specific_signal(args.db, args.symbol, args.time)
    else:
        query_signals(args.db, symbol=args.symbol, days=args.days, limit=args.limit)

